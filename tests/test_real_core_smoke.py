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
    paragraphs = "".join(f"<w:p><w:r><w:t>{line}</w:t></w:r></w:p>" for line in text.splitlines())
    document = (
        f'<?xml version="1.0" encoding="UTF-8"?>'
        f'<w:document xmlns:w="{word_namespace}"><w:body>{paragraphs}</w:body></w:document>'
    )
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("[Content_Types].xml", "<Types/>")
        archive.writestr("word/document.xml", document.encode("utf-8"))


def _write_pdf(path: Path) -> None:
    """Write a minimal valid PDF with a text layer and no external fixture."""

    stream = b"BT /F1 12 Tf 20 100 Td (Hello Vitrina) Tj ET"
    objects = [
        b"<</Type/Catalog/Pages 2 0 R>>",
        b"<</Type/Pages/Kids[3 0 R]/Count 1>>",
        b"<</Type/Page/Parent 2 0 R/MediaBox[0 0 300 200]/Contents 4 0 R"
        b"/Resources<</Font<</F1 5 0 R>>>>>>",
        b"<</Length " + str(len(stream)).encode() + b">>\nstream\n" + stream + b"\nendstream",
        b"<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>",
    ]
    payload = bytearray(b"%PDF-1.4\n")
    offsets: list[int] = []
    for ordinal, body in enumerate(objects, start=1):
        offsets.append(len(payload))
        payload += str(ordinal).encode() + b" 0 obj\n" + body + b"\nendobj\n"
    xref = len(payload)
    payload += b"xref\n0 " + str(len(objects) + 1).encode() + b"\n0000000000 65535 f \n"
    for offset in offsets:
        payload += f"{offset:010d} 00000 n \n".encode()
    payload += (
        b"trailer\n<</Size "
        + str(len(objects) + 1).encode()
        + b"/Root 1 0 R>>\nstartxref\n"
        + str(xref).encode()
        + b"\n%%EOF\n"
    )
    path.write_bytes(payload)


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
        "warning_codes": [warning["code"] for warning in warnings if isinstance(warning, dict)],
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

    def test_pdf_direct_cli_produces_valid_completed_result(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            directory = Path(directory_name)
            document = directory / "требования.pdf"
            output = directory / "result.json"
            model_config = directory / "model-config.yaml"
            _write_pdf(document)

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
                        "smoke-pdf-supported",
                        "--output",
                        str(output),
                        "--model-config",
                        str(model_config),
                    ]
                )
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)

            diagnostic = (
                output.read_text(encoding="utf-8")
                if output.is_file()
                else completed.stderr.decode("utf-8", errors="replace")
            )
            self.assertEqual(completed.returncode, 0, diagnostic)
            self.assertEqual(completed.stderr.decode("utf-8", errors="strict"), "")
            self.assertTrue(output.is_file())
            result = json.loads(output.read_bytes().decode("utf-8", errors="strict"))
            validate_review_result(result)
            self.assertEqual(result["status"], "completed")
            self.assertEqual(result["run_id"], "smoke-pdf-supported")
            self.assertEqual(result["document"]["document_type"], "pdf")


if __name__ == "__main__":
    unittest.main()
