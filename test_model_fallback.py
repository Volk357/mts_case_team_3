# -*- coding: utf-8 -*-
"""Тесты фолбека модели на OpenAI-совместимый эндпоинт (OpenRouter).

Паттерн — как в test_verify.py: сетевые вызовы подменяются заглушками,
настоящая модель не дёргается и сеть не нужна.

Проверяется контракт chat():
  * primary (Ollama) упал по сети → сработал фолбек, ответ разобран;
  * primary отдал невалидный JSON → фолбек;
  * оба не вышли → наружу ИСХОДНАЯ ошибка primary (контур обработки
    ModelUnavailable не меняется);
  * fallback не задан → поведение ровно как раньше, без второй попытки;
  * секрет читается из окружения, лениво, в момент переключения.
"""
import json
import os
import sys
import tempfile

import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import docreview  # noqa: E402
import run_review  # noqa: E402

DOC = "Тут документ со строкой в документе дефект тут и ещё текстом." * 10

# Ответ OpenAI-совместимого эндпоинта с мышлением Qwen3 и обёрткой
# ```json … ``` — обязана разобраться в массив.
_OR_BODY = ("```thinking\nнадо подумать\n```\n"
            "```json\n[{\"quote\": \"строка в документе дефект тут\", "
            "\"defect_id\": \"T1\", \"explanation\": \"объяснение\", "
            "\"suggestion\": \"совет\", \"severity\": \"medium\"}]\n```")

_FALLBACK = {
    "url": "https://openrouter.ai/api/v1/chat/completions",
    "model": "qwen/qwen3-30b-a3b",
    "api_key_env": "OPENROUTER_API_KEY_TEST",
    "timeout": 30,
}

_SCHEMA = {"type": "array", "items": {"type": "object"}}
_PROMPT = "проверь фрагмент"


class _Resp:
    """Заглушка requests.Response с нужным статусом и .json()."""

    def __init__(self, payload, status=200):
        self._payload = payload
        self.status_code = status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.exceptions.HTTPError(
                "HTTP %s" % self.status_code, response=self)
        return None

    def json(self):
        return self._payload


def _ollama_ok(content='[{"quote": "дефект в тексте", "defect_id": "T1", '
                        '"explanation": "объяснение", "suggestion": "совет", '
                        '"severity": "medium"}]'):
    return lambda url, **kw: _Resp({"message": {"content": content}})


def _with_fallback(fallback, key=None):
    """Контекст: FALLBACK задан, ключ в окружении, восстановление после."""
    import contextlib

    @contextlib.contextmanager
    def ctx():
        old_fb, old_key = run_review.FALLBACK, os.environ.get(
            _FALLBACK["api_key_env"])
        run_review.FALLBACK = fallback
        if key is not None:
            os.environ[_FALLBACK["api_key_env"]] = key
        else:
            os.environ.pop(_FALLBACK["api_key_env"], None)
        try:
            yield
        finally:
            run_review.FALLBACK = old_fb
            if old_key is None:
                os.environ.pop(_FALLBACK["api_key_env"], None)
            else:
                os.environ[_FALLBACK["api_key_env"]] = old_key
    return ctx()


def test_primary_failure_uses_fallback_and_parses_answer():
    """Сетевая ошибка primary → вторая попытка на OpenRouter, ответ разобран."""
    calls = []

    def primary(url, **kw):
        calls.append(url)
        raise requests.exceptions.ConnectionError("ollama лежит")

    def fallback(url, **kw):
        calls.append(url)
        assert kw["headers"]["Authorization"] == "Bearer sk-or-test"
        assert kw["json"]["model"] == _FALLBACK["model"]
        assert kw["json"]["max_tokens"] == 4096
        # reasoning выключен: без этого deepseek истратил бы лимит на «думание»
        assert kw["json"]["reasoning"] == {"enabled": False}
        return _Resp({"choices": [{"message": {"content": _OR_BODY}}]})

    orig_post = run_review.requests.post
    run_review.requests.post = lambda url, **kw: (
        primary(url, **kw) if calls == [] else fallback(url, **kw))
    try:
        with _with_fallback(_FALLBACK, key="sk-or-test"):
            out = run_review.chat(_PROMPT, _SCHEMA, 4096)
    finally:
        run_review.requests.post = orig_post
    assert len(out) == 1 and out[0]["defect_id"] == "T1"
    assert calls[0] == run_review.OLLAMA_URL, "первой идёт Ollama"
    assert calls[1] == _FALLBACK["url"], "второй — OpenRouter"


def test_invalid_json_from_primary_falls_back():
    """Невалидный JSON primary — тоже отказ: нужен фолбек, а не пустой список."""
    calls = []

    def fallback(url, **kw):
        calls.append("fallback")
        return _Resp({"choices": [{"message": {"content": _OR_BODY}}]})

    def route(url, **kw):
        if not calls:
            calls.append("primary")
            return _Resp({"message": {"content": "не json вовсе"}})
        return fallback(url, **kw)

    orig_post = run_review.requests.post
    run_review.requests.post = route
    try:
        with _with_fallback(_FALLBACK, key="sk-or-test"):
            out = run_review.chat(_PROMPT, _SCHEMA, 4096)
    finally:
        run_review.requests.post = orig_post
    assert len(out) == 1, "невалидный json primary не должен давать пустой список"


def test_both_fail_re_raises_primary_error():
    """Оба эндпоинта недоступны → наружу ИСХОДНАЯ ошибка primary.

    Требование: поведение не меняется относительно контура без фолбека
    (docreview ловит RequestException и отдаёт partial-результат/retriable).
    """
    boom = requests.exceptions.ConnectionError("ollama лежит")

    def dead(url, **kw):
        raise boom

    orig_post = run_review.requests.post
    run_review.requests.post = dead
    try:
        with _with_fallback(_FALLBACK, key="sk-or-test"):
            run_review.chat(_PROMPT, _SCHEMA, 4096)
            raise AssertionError("ожидали исключение")
    except requests.exceptions.ConnectionError as e:
        assert e is boom, "наружу должна выйти ошибка primary, а не фолбека"
    finally:
        run_review.requests.post = orig_post


def test_no_fallback_preserves_old_behavior():
    """FALLBACK не задан → вторая попытка не делается, ошибка как раньше."""
    boom = requests.exceptions.ConnectionError("сеть недоступна")
    calls = []

    def dead(url, **kw):
        calls.append(url)
        raise boom

    orig_post = run_review.requests.post
    run_review.requests.post = dead
    try:
        with _with_fallback(None):
            try:
                run_review.chat(_PROMPT, _SCHEMA, 4096)
                raise AssertionError("ожидали исключение")
            except requests.exceptions.ConnectionError:
                pass
    finally:
        run_review.requests.post = orig_post
    assert len(calls) == 1, "без фолбека — ровно одна попытка (как раньше)"


def test_missing_api_key_makes_fallback_inert():
    """Ключ не задан → фолбек невозможен, наружу исходная ошибка, без краха."""
    boom = requests.exceptions.ConnectionError("ollama лежит")

    def dead(url, **kw):
        raise boom

    orig_post = run_review.requests.post
    run_review.requests.post = dead
    try:
        with _with_fallback(_FALLBACK, key=None):
            try:
                run_review.chat(_PROMPT, _SCHEMA, 4096)
                raise AssertionError("ожидали исключение")
            except requests.exceptions.ConnectionError as e:
                assert e is boom
    finally:
        run_review.requests.post = orig_post


def test_verifier_uses_chat_with_fallback():
    """ask_verifier ходит тем же путём; вердикт применяется к кандидату."""
    orig_findings = [{"quote": "строка в документе дефект тут",
                      "defect_id": "T1", "explanation": "объяснение",
                      "suggestion": "совет", "severity": "medium"}]

    def primary(url, **kw):
        raise requests.exceptions.ConnectionError("ollama лежит")

    def fallback(url, **kw):
        body = ("[{\"id\": 1, \"verdict\": \"accept\", "
                "\"reason\": \"подтверждаю\"}]")
        return _Resp({"choices": [{"message": {"content": body}}]})

    orig_post = run_review.requests.post
    run_review.requests.post = lambda url, **kw: (
        primary(url, **kw) if url == run_review.OLLAMA_URL
        else fallback(url, **kw))
    try:
        with _with_fallback(_FALLBACK, key="sk-or-test"):
            result = run_review.verify_semantics(orig_findings, DOC)
    finally:
        run_review.requests.post = orig_post
    assert result[0]["_verdict"]["verdict"] == "accept"


def test_parse_model_json_handles_thinking_and_prose():
    """Парсер OpenAI-ответа: мышление, ```json, проза вокруг — не мешают."""
    cases = [
        ("```json\n[1, 2]\n```", [1, 2]),
        ("думаю… ```thinking\nx\n```\n```json\n{\"a\": 1}\n```", {"a": 1}),
        ("сначала пояснение, потом: [3]\nконец", [3]),
    ]
    for raw, expected in cases:
        assert run_review._parse_model_json(raw) == expected, raw


def test_parse_model_json_rejects_garbage():
    try:
        run_review._parse_model_json("вообще не json")
        raise AssertionError("ожидали JSONDecodeError")
    except json.JSONDecodeError:
        pass


DOC = "Тут документ со строкой в документе дефект тут и ещё текстом." * 10

def test_model_config_normalizes_fallback_keys():
    """Реальный конфиг пишет base_url, а клиент ждёт url: нормализация есть.

    Проверяет именно путь из продакшена (model-config.yaml), а не прямо
    заданный словарь: рассинхрон имён ловился на реальном прогоне, хотя
    юнит-тесты с FALLBACK={"url": ...} проходили.
    """
    body = (
        "base_url: http://x:11434/api/chat\n"
        "model: qwen3:30b-a3b\n"
        "num_ctx: 32768\n"
        "timeout: 900\n"
        "fallback:\n"
        "  base_url: https://openrouter.ai/api/v1/chat/completions\n"
        "  model: qwen/qwen3-30b-a3b\n"
        "  api_key_env: OPENROUTER_API_KEY\n"
        "  timeout: 30\n"
    )
    fd, path = tempfile.mkstemp(suffix=".yaml")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(body)
    try:
        conf = docreview.load_model_config(path)
    finally:
        os.unlink(path)
    fb = conf["fallback"]
    assert fb["url"] == "https://openrouter.ai/api/v1/chat/completions"
    assert fb["model"] == "qwen/qwen3-30b-a3b"
    assert fb["api_key_env"] == "OPENROUTER_API_KEY"
    assert fb["timeout"] == 30


def test_model_config_rejects_broken_fallback():
    cases = [
        ("base_url: http://x:11434/api/chat\nmodel: m\n"
         "fallback:\n  url: http://elsewhere:9999/foo\n  model: m\n"
         "  api_key_env: K\n", "chat/completions"),
        ("base_url: http://x:11434/api/chat\nmodel: m\n"
         "fallback:\n  url: https://or.ai/api/v1/chat/completions\n"
         "  api_key_env: K\n", "model"),
        ("base_url: http://x:11434/api/chat\nmodel: m\n"
         "fallback:\n  url: https://or.ai/api/v1/chat/completions\n"
         "  model: m\n", "api_key_env"),
        ("base_url: http://x:11434/api/chat\nmodel: m\n"
         "fallback:\n  url: https://or.ai/api/v1/chat/completions\n"
         "  model: m\n  api_key_env: K\n  timeout: true\n", "timeout"),
        ("base_url: http://x:11434/api/chat\nmodel: m\n"
         "fallback: строка\n", "словарём"),
    ]
    for body, expected in cases:
        fd, path = tempfile.mkstemp(suffix=".yaml")
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(body)
        try:
            try:
                docreview.load_model_config(path)
                raise AssertionError("принято: %s" % body)
            except docreview.ModelConfigInvalid as e:
                assert expected in str(e), (body, str(e))
        finally:
            os.unlink(path)


def test_empty_content_from_fallback_is_a_clean_failure():
    """content=null (весь бюджет ушёл в reasoning) — сбой фолбека, а не AttributeError.

    Наружу — исходная ошибка primary, как задумано для двойного сбоя.
    """
    boom = requests.exceptions.ConnectionError("ollama лежит")

    def dead(url, **kw):
        raise boom

    def empty(url, **kw):
        return _Resp({"choices": [{"message": {"content": None}}]})

    orig_post = run_review.requests.post
    run_review.requests.post = lambda url, **kw: (
        dead(url, **kw) if url == run_review.OLLAMA_URL else empty(url, **kw))
    try:
        with _with_fallback(_FALLBACK, key="sk-or-test"):
            try:
                run_review.chat(_PROMPT, _SCHEMA, 100)
                raise AssertionError("ожидали исключение")
            except requests.exceptions.ConnectionError as e:
                assert e is boom
    finally:
        run_review.requests.post = orig_post


def test_force_fallback_skips_primary():
    """DOCREVIEW_FORCE_FALLBACK=1 → primary не вызывается, сразу фолбек."""
    calls = []

    def route(url, **kw):
        calls.append(url)
        return _Resp({"choices": [{"message": {"content": _OR_BODY}}]})

    orig_post = run_review.requests.post
    run_review.requests.post = route
    old = run_review.FORCE_FALLBACK
    run_review.FORCE_FALLBACK = True
    try:
        with _with_fallback(_FALLBACK, key="sk-or-test"):
            out = run_review.chat(_PROMPT, _SCHEMA, 4096)
    finally:
        run_review.FORCE_FALLBACK = old
        run_review.requests.post = orig_post
    assert len(out) == 1
    assert calls == [_FALLBACK["url"]], "primary не должен вызываться: %s" % calls


def test_force_fallback_without_config_raises():
    old = run_review.FORCE_FALLBACK
    run_review.FORCE_FALLBACK = True
    try:
        with _with_fallback(None):
            try:
                run_review.chat(_PROMPT, _SCHEMA, 4096)
                raise AssertionError("ожидали ошибку")
            except RuntimeError as e:
                assert "fallback не настроен" in str(e)
    finally:
        run_review.FORCE_FALLBACK = old


def test_non_object_findings_are_rejected_not_fatal():
    """Модель вернула массив строк вместо объектов — отбрасываем, не роняем.

    Измерено на deepseek-v4-flash-0731 (synth_2): без этого verify() падал
    на f.get() и весь прогон уходил в INTERNAL_ERROR.
    """
    findings = ["строка вместо объекта", 42,
                {"quote": "дефект в тексте", "defect_id": "T1",
                 "explanation": "объяснение", "suggestion": "совет",
                 "severity": "medium"}]
    kept, dropped = run_review.verify(findings, "Текст с дефект в тексте.",
                                      {"T1"})
    assert len(kept) == 1, kept
    assert any(d.get("reject_reason") == "not_an_object" for d in dropped), dropped


def test_retry_on_429_then_success():
    """429 (провайдер временно недоступен) → ретрай, затем успех.

    Без ретрая 429 ронял весь прогон (измерено на qwen3.8-flash:
    провайдер банил ключ, повтор через пару секунд проходил).
    """
    calls = []

    def flaky(url, **kw):
        calls.append(1)
        if len(calls) == 1:
            r = requests.Response()
            r.status_code = 429
            r.url = url
            raise requests.exceptions.HTTPError(
                "429 Too Many Requests", response=r)
        return _Resp({"choices": [{"message": {"content": _OR_BODY}}]})

    # sleep подменяем, чтобы не ждать реальные паузы
    orig_sleep = run_review.time.sleep
    run_review.time.sleep = lambda s: None
    orig_post = run_review.requests.post
    run_review.requests.post = flaky
    try:
        with _with_fallback(_FALLBACK, key="sk-or-test"):
            out = run_review.chat(_PROMPT, _SCHEMA, 4096)
    finally:
        run_review.time.sleep = orig_sleep
        run_review.requests.post = orig_post
    assert len(out) == 1
    assert len(calls) == 2, "429 должен уйти в ретрай, а не наружу: %s" % calls


def test_api_key_from_config_used_over_env():
    """api_key из конфига приоритетнее api_key_env (путь через воркер)."""
    seen = []

    def route(url, **kw):
        seen.append(kw["headers"]["Authorization"])
        return _Resp({"choices": [{"message": {"content": _OR_BODY}}]})

    conf = dict(_FALLBACK)
    conf["api_key"] = "sk-or-from-file"
    orig_post = run_review.requests.post
    run_review.requests.post = route
    try:
        with _with_fallback(conf, key="sk-or-from-env"):
            run_review.chat(_PROMPT, _SCHEMA, 4096)
    finally:
        run_review.requests.post = orig_post
    assert seen == ["Bearer sk-or-from-file"], seen


def test_model_config_accepts_api_key_instead_of_env():
    """Валидация: fallback с api_key (без api_key_env) — допустимо."""
    body = (
        "base_url: http://x:11434/api/chat\n"
        "model: m\n"
        "fallback:\n"
        "  base_url: https://openrouter.ai/api/v1/chat/completions\n"
        "  model: qwen/qwen3.8-flash\n"
        "  api_key: sk-or-test-secret\n"
    )
    fd, path = tempfile.mkstemp(suffix=".yaml")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(body)
    try:
        conf = docreview.load_model_config(path)
    finally:
        os.unlink(path)
    assert conf["fallback"]["api_key"] == "sk-or-test-secret"
    assert "api_key_env" not in conf["fallback"]


TESTS = [v for k, v in sorted(globals().items()) if k.startswith("test_")]

if __name__ == "__main__":
    for t in TESTS:
        t()
        print("ok  %s" % t.__name__)
    print("\n%d passed" % len(TESTS))