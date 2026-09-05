"""Direct-process smoke tests for the accepted real Analysis Core CLI."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import threading
import unittest
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from contracts.validate_contract import validate_review_result

REPOSITORY = Path(__file__).resolve().parents[1]
FIXTURES = REPOSITORY / "tests" / "fixtures" / "real-core-smoke"
PACK = REPOSITORY / "review-packs" / "mts-net" / "0.2"


def _executable() -> Path:
    name = "docreview.exe" if sys.platform == "win32" else "docreview"
    return Path(sys.executable).with_name(name)


class _EmptyModelHandler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:  # noqa: N802 - method name is defined by BaseHTTPRequestHandler
        length = int(self.headers.get("Content-Length", "0"))
        request = json.loads(self.rfile.read(length).decode("utf-8"))
        if request.get("think") is not False:
            self.send_error(400)
            return
        payload = json.dumps({"message": {"content": "[]"}}).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, _format: str, *_args: object) -> None:
        return


def _write_docx(path: Path) -> None:
    word_namespace = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    text = (
        "Общие сведения\n"
        "Название: Проверка UTF-8\n"
        "Часовой пояс: UTC\n"
        "Алгоритм обработки потока\n"
        "Записи передаются без изменения."
    )
    paragraphs = "".join(
        f"<w:p><w:r><w:t>{line}</w:t></w:r></w:p>" for line in text.splitlines()
    )
    document = (
        f'<?xml version="1.0" encoding="UTF-8"?>'
        f'<w:document xmlns:w="{word_namespace}"><w:body>{paragraphs}</w:body></w:document>'
    )
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("[Content_Types].xml", "<Types/>")
        archive.writestr("word/document.xml", document.encode("utf-8"))


def _run_cli(arguments: list[str]) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        [_executable(), *arguments],
        cwd=REPOSITORY,
        capture_output=True,
        check=False,
        timeout=30,
    )


def _stable_result(result: dict[str, object]) -> dict[str, object]:
    document = result["document"]
    findings = result["findings"]
    warnings = result["warnings"]
    assert isinstance(document, dict)
    assert isinstance(findings, list)
    assert isinstance(warnings, list)
    return {
        "schema_version": result["schema_version"],
        "run_id": result["run_id"],
        "status": result["status"],
        "document": {
            "filename": document["filename"],
            "document_type": document["document_type"],
        },
        "engine": result["engine"],
        "review_pack": result["review_pack"],
        "model": result["model"],
        "findings": [
            {
                "id": finding["id"],
                "defect_id": finding["defect_id"],
                "severity": finding["severity"],
                "quote": finding["quote"],
                "detected_by": finding["detected_by"],
            }
            for finding in findings
            if isinstance(finding, dict)
        ],
        "summary": result["summary"],
        "warning_codes": [
            warning["code"] for warning in warnings if isinstance(warning, dict)
        ],
    }


class RealCoreCliSmokeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        if not _executable().is_file():
            raise unittest.SkipTest("real docreview executable is not installed")

    def test_docx_direct_cli_stdout_output_utf8_and_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            directory = Path(directory_name)
            document = directory / "требования.docx"
            output = directory / "result.json"
            artifacts = directory / "artifacts"
            model_config = directory / "model-config.yaml"
            _write_docx(document)

            server = ThreadingHTTPServer(("127.0.0.1", 0), _EmptyModelHandler)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                model_config.write_text(
                    "base_url: http://127.0.0.1:%d/api/chat\n"
                    "model: smoke-empty-model\n"
                    "num_ctx: 4096\n"
                    "timeout: 10\n" % server.server_port,
                    encoding="utf-8",
                )
                completed = _run_cli(
                    [
                        "analyze",
                        "--file",
                        str(document),
                        "--pack",
                        str(PACK),
                        "--run-id",
                        "smoke-docx-utf8",
                        "--output",
                        str(output),
                        "--artifacts-dir",
                        str(artifacts),
                        "--model-config",
                        str(model_config),
                        "--include-rejected",
                    ]
                )
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)

            stdout = completed.stdout.decode("utf-8", errors="strict")
            stderr = completed.stderr.decode("utf-8", errors="strict")
            diagnostic = output.read_text(encoding="utf-8") if output.is_file() else stderr
            self.assertEqual(completed.returncode, 0, diagnostic)
            self.assertIn("фрагментов", stdout)
            self.assertEqual(stderr, "")
            self.assertTrue(output.is_file())

            result = json.loads(output.read_bytes().decode("utf-8", errors="strict"))
            validate_review_result(result)
            self.assertEqual(result["run_id"], "smoke-docx-utf8")
            self.assertEqual(result["document"]["filename"], "требования.docx")
            self.assertEqual(
                _stable_result(result),
                json.loads((FIXTURES / "docx-result.json").read_text(encoding="utf-8")),
                json.dumps(_stable_result(result), ensure_ascii=True, indent=2),
            )

            debug = artifacts / "analysis-debug.json"
            self.assertTrue(debug.is_file())
            self.assertEqual(
                json.loads(debug.read_text(encoding="utf-8")),
                json.loads((FIXTURES / "docx-analysis-debug.json").read_text(encoding="utf-8")),
                debug.read_text(encoding="utf-8"),
            )

    def test_pdf_direct_cli_has_contract_failure_and_exit_code(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            directory = Path(directory_name)
            document = directory / "требования.pdf"
            output = directory / "result.json"
            document.write_bytes(b"%PDF-1.7\n% smoke fixture\n")

            completed = _run_cli(
                [
                    "analyze",
                    "--file",
                    str(document),
                    "--pack",
                    str(PACK),
                    "--run-id",
                    "smoke-pdf-unsupported",
                    "--output",
                    str(output),
                ]
            )

            self.assertEqual(completed.returncode, 3)
            self.assertEqual(completed.stdout.decode("utf-8", errors="strict"), "")
            self.assertEqual(completed.stderr.decode("utf-8", errors="strict"), "")
            self.assertTrue(output.is_file())
            result = json.loads(output.read_bytes().decode("utf-8", errors="strict"))
            validate_review_result(result)
            self.assertEqual(
                result,
                json.loads((FIXTURES / "pdf-result.json").read_text(encoding="utf-8")),
                json.dumps(result, ensure_ascii=True, indent=2),
            )


if __name__ == "__main__":
    unittest.main()
