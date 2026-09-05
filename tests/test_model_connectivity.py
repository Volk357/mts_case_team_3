"""Acceptance checks for secret-backed model configuration and preflight."""

from __future__ import annotations

import importlib.util
import io
import json
import os
import tempfile
import threading
import unittest
from contextlib import redirect_stderr, redirect_stdout
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

REPOSITORY = Path(__file__).resolve().parents[1]
SCRIPT = REPOSITORY / "apps" / "api" / "scripts" / "model_preflight.py"


def _load_preflight_module():
    spec = importlib.util.spec_from_file_location("model_preflight", SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError("could not load model preflight")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _OllamaStub(BaseHTTPRequestHandler):
    model = "qwen3:30b-a3b"
    request_payload: dict[str, object] | None = None

    def do_GET(self) -> None:
        self._respond({"models": [{"name": self.model}]})

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", "0"))
        type(self).request_payload = json.loads(self.rfile.read(length))
        self._respond({"message": {"content": "OK"}})

    def log_message(self, format: str, *args: object) -> None:
        return

    def _respond(self, payload: dict[str, object]) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class ModelConnectivityTests(unittest.TestCase):
    def test_compose_mounts_ignored_config_as_secret(self) -> None:
        compose = (REPOSITORY / "compose.yaml").read_text(encoding="utf-8")
        ignored = (REPOSITORY / ".gitignore").read_text(encoding="utf-8")

        self.assertIn(
            "DOCREVIEW_ANALYSIS_MODEL_CONFIG_PATH: /run/secrets/model-config.yaml",
            compose,
        )
        self.assertIn("source: model_config", compose)
        self.assertIn('profiles: ["real"]', compose)
        self.assertIn("model-config.yaml", ignored)

    def test_preflight_checks_catalog_and_inference_parameters(self) -> None:
        module = _load_preflight_module()
        server = ThreadingHTTPServer(("127.0.0.1", 0), _OllamaStub)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with tempfile.TemporaryDirectory() as directory:
                config = Path(directory) / "model-config.yaml"
                config.write_text(
                    f"base_url: http://127.0.0.1:{server.server_port}/api/chat\n"
                    "model: qwen3:30b-a3b\nnum_ctx: 32768\n",
                    encoding="utf-8",
                )
                with (
                    patch.dict(
                        os.environ,
                        {
                            "DOCREVIEW_ANALYSIS_MODEL_CONFIG_PATH": str(config),
                            "DOCREVIEW_MODEL_PREFLIGHT_TIMEOUT_SECONDS": "5",
                        },
                    ),
                    redirect_stdout(io.StringIO()) as output,
                ):
                    self.assertEqual(module.main(), 0)
                self.assertIn("MODEL_READY", output.getvalue())
        finally:
            server.shutdown()
            server.server_close()

        payload = _OllamaStub.request_payload
        self.assertIsNotNone(payload)
        assert payload is not None
        self.assertIs(payload["think"], False)
        self.assertEqual(payload["options"]["num_ctx"], 32768)  # type: ignore[index]

    def test_preflight_reports_missing_model_without_printing_url(self) -> None:
        module = _load_preflight_module()
        server = ThreadingHTTPServer(("127.0.0.1", 0), _OllamaStub)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with tempfile.TemporaryDirectory() as directory:
                config = Path(directory) / "model-config.yaml"
                config.write_text(
                    f"base_url: http://127.0.0.1:{server.server_port}/api/chat?token=secret\n"
                    "model: missing-model\n",
                    encoding="utf-8",
                )
                with (
                    patch.dict(
                        os.environ,
                        {"DOCREVIEW_ANALYSIS_MODEL_CONFIG_PATH": str(config)},
                    ),
                    redirect_stderr(io.StringIO()) as error,
                ):
                    self.assertEqual(module.main(), 6)
                self.assertIn("MODEL_NOT_FOUND", error.getvalue())
                self.assertNotIn("token=secret", error.getvalue())
        finally:
            server.shutdown()
            server.server_close()

    def test_preflight_rejects_credentials_embedded_in_url(self) -> None:
        module = _load_preflight_module()
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / "model-config.yaml"
            config.write_text(
                "base_url: http://user:top-secret@model.internal:11434/api/chat\n"
                "model: qwen3:30b-a3b\n",
                encoding="utf-8",
            )
            with (
                patch.dict(
                    os.environ,
                    {"DOCREVIEW_ANALYSIS_MODEL_CONFIG_PATH": str(config)},
                ),
                redirect_stderr(io.StringIO()) as error,
            ):
                self.assertEqual(module.main(), 2)
            self.assertIn("MODEL_CONFIG_INVALID", error.getvalue())
            self.assertNotIn("top-secret", error.getvalue())


if __name__ == "__main__":
    unittest.main()
