"""Validate Ollama API, configured model presence and a minimal inference."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit, urlunsplit
from urllib.request import Request, urlopen

import yaml

MAX_RESPONSE_BYTES = 2 * 1024 * 1024
DEFAULT_CONFIG_PATH = "/run/secrets/model-config.yaml"
DEFAULT_PREFLIGHT_TIMEOUT_SECONDS = 900


class PreflightFailure(RuntimeError):
    def __init__(self, code: str, message: str, *, exit_code: int) -> None:
        super().__init__(message)
        self.code = code
        self.exit_code = exit_code


def _positive_integer(value: object, name: str) -> int:
    if isinstance(value, bool):
        raise PreflightFailure(
            "MODEL_CONFIG_INVALID", f"{name} must be a positive integer", exit_code=2
        )
    try:
        parsed = int(str(value).strip())
    except (TypeError, ValueError) as error:
        raise PreflightFailure(
            "MODEL_CONFIG_INVALID", f"{name} must be a positive integer", exit_code=2
        ) from error
    if parsed <= 0:
        raise PreflightFailure(
            "MODEL_CONFIG_INVALID", f"{name} must be a positive integer", exit_code=2
        )
    return parsed


def _load_config() -> dict[str, Any]:
    path = Path(os.environ.get("DOCREVIEW_ANALYSIS_MODEL_CONFIG_PATH", DEFAULT_CONFIG_PATH))
    try:
        config = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as error:
        raise PreflightFailure(
            "MODEL_CONFIG_INVALID", "model configuration is missing or unreadable", exit_code=2
        ) from error
    if not isinstance(config, dict):
        raise PreflightFailure(
            "MODEL_CONFIG_INVALID", "model configuration must be a mapping", exit_code=2
        )

    base_url = config.get("base_url") or config.get("url") or config.get("endpoint")
    model = config.get("model") or config.get("name")
    if not isinstance(base_url, str) or not isinstance(model, str) or not model.strip():
        raise PreflightFailure(
            "MODEL_CONFIG_INVALID", "base_url and model are required", exit_code=2
        )
    parsed = urlsplit(base_url)
    has_embedded_credentials = parsed.username is not None or parsed.password is not None
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or has_embedded_credentials:
        raise PreflightFailure(
            "MODEL_CONFIG_INVALID",
            "base_url must be an HTTP(S) URL without embedded credentials",
            exit_code=2,
        )
    if parsed.path.rstrip("/") != "/api/chat":
        raise PreflightFailure(
            "MODEL_CONFIG_INVALID",
            "Analysis Core requires the Ollama /api/chat endpoint",
            exit_code=2,
        )

    return {
        "base_url": base_url,
        "model": model.strip(),
        "num_ctx": _positive_integer(config.get("num_ctx", 32768), "num_ctx"),
    }


def _timeout_seconds() -> int:
    return _positive_integer(
        os.environ.get(
            "DOCREVIEW_MODEL_PREFLIGHT_TIMEOUT_SECONDS", DEFAULT_PREFLIGHT_TIMEOUT_SECONDS
        ),
        "DOCREVIEW_MODEL_PREFLIGHT_TIMEOUT_SECONDS",
    )


def _endpoint_label(url: str) -> str:
    parsed = urlsplit(url)
    return parsed.hostname or "unknown-host"


def _tags_url(chat_url: str) -> str:
    parsed = urlsplit(chat_url)
    return urlunsplit((parsed.scheme, parsed.netloc, "/api/tags", "", ""))


def _request_json(request: Request, *, timeout: int, stage: str) -> dict[str, Any]:
    try:
        with urlopen(request, timeout=timeout) as response:
            raw = response.read(MAX_RESPONSE_BYTES + 1)
    except HTTPError as error:
        if error.code in {401, 403}:
            raise PreflightFailure(
                "MODEL_AUTH_FAILED", f"{stage} rejected authentication", exit_code=4
            ) from error
        raise PreflightFailure(
            "MODEL_API_HTTP_ERROR", f"{stage} returned HTTP {error.code}", exit_code=5
        ) from error
    except (URLError, TimeoutError, OSError) as error:
        raise PreflightFailure(
            "MODEL_ENDPOINT_UNREACHABLE", f"{stage} could not reach the endpoint", exit_code=3
        ) from error
    if len(raw) > MAX_RESPONSE_BYTES:
        raise PreflightFailure("MODEL_API_INVALID", f"{stage} response is too large", exit_code=5)
    try:
        payload = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise PreflightFailure(
            "MODEL_API_INVALID", f"{stage} returned invalid JSON", exit_code=5
        ) from error
    if not isinstance(payload, dict):
        raise PreflightFailure(
            "MODEL_API_INVALID", f"{stage} returned an invalid payload", exit_code=5
        )
    return payload


def _verify_model_is_installed(config: dict[str, Any], *, timeout: int) -> None:
    payload = _request_json(
        Request(_tags_url(config["base_url"]), headers={"Accept": "application/json"}),
        timeout=min(timeout, 30),
        stage="model catalog",
    )
    models = payload.get("models")
    if not isinstance(models, list):
        raise PreflightFailure("MODEL_API_INVALID", "model catalog has no models list", exit_code=5)
    installed = {
        item.get("name")
        for item in models
        if isinstance(item, dict) and isinstance(item.get("name"), str)
    }
    if config["model"] not in installed:
        raise PreflightFailure(
            "MODEL_NOT_FOUND", f"configured model {config['model']!r} is not installed", exit_code=6
        )


def _verify_inference(config: dict[str, Any], *, timeout: int) -> None:
    body = json.dumps(
        {
            "model": config["model"],
            "messages": [{"role": "user", "content": "Reply with OK."}],
            "stream": False,
            "think": False,
            "options": {
                "num_ctx": config["num_ctx"],
                "temperature": 0,
                "num_predict": 4,
            },
            "keep_alive": "2h",
        }
    ).encode("utf-8")
    payload = _request_json(
        Request(
            config["base_url"],
            data=body,
            headers={"Accept": "application/json", "Content-Type": "application/json"},
            method="POST",
        ),
        timeout=timeout,
        stage="model inference",
    )
    message = payload.get("message")
    if not isinstance(message, dict) or not isinstance(message.get("content"), str):
        raise PreflightFailure(
            "MODEL_INFERENCE_INVALID", "model inference returned no message content", exit_code=7
        )


def main() -> int:
    try:
        config = _load_config()
        timeout = _timeout_seconds()
        _verify_model_is_installed(config, timeout=timeout)
        _verify_inference(config, timeout=timeout)
    except PreflightFailure as error:
        print(f"{error.code}: {error}", file=sys.stderr)
        return error.exit_code
    print(
        f"MODEL_READY: model {config['model']!r} is available at "
        f"{_endpoint_label(config['base_url'])}."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
