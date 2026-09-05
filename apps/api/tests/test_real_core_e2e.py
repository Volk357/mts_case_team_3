"""Full HTTP-to-worker scenario with the installed real Analysis Core."""

from __future__ import annotations

import json
import sys
import threading
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import BytesIO
from pathlib import Path
from uuid import UUID

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from docreview_api.config import REPOSITORY_DIRECTORY, Settings
from docreview_api.db.base import Base
from docreview_api.db.models import CompanyModel, ReviewJobModel, ReviewPackReferenceModel
from docreview_api.db.session import create_database_engine, create_session_factory
from docreview_api.main import create_app
from docreview_api.models.review_job_state import ReviewJobStatus
from docreview_api.workers.review_worker import build_worker


def _real_core_executable() -> Path:
    name = "docreview.exe" if sys.platform == "win32" else "docreview"
    return Path(sys.executable).with_name(name)


class _EmptyModelHandler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", "0"))
        request = json.loads(self.rfile.read(length).decode("utf-8"))
        if request.get("think") is not False:
            self.send_error(400)
            return
        payload = json.dumps({"message": {"content": "[]"}}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, _format: str, *_args: object) -> None:
        return


def _real_docx() -> bytes:
    namespace = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    lines = [
        "Общие сведения",
        "Название: Сквозная проверка UTF-8",
        "Часовой пояс: UTC",
        "Алгоритм обработки потока",
        "Записи передаются без изменения.",
    ]
    paragraphs = "".join(f"<w:p><w:r><w:t>{line}</w:t></w:r></w:p>" for line in lines)
    document = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        f'<w:document xmlns:w="{namespace}"><w:body>{paragraphs}</w:body></w:document>'
    )
    content_types = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Override PartName="/word/document.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
        "</Types>"
    )
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("[Content_Types].xml", content_types)
        archive.writestr("word/document.xml", document.encode("utf-8"))
    return buffer.getvalue()


def _write_model_config(path: Path, port: int) -> None:
    path.write_text(
        f"base_url: http://127.0.0.1:{port}/api/chat\n"
        "model: e2e-empty-model\n"
        "num_ctx: 4096\n"
        "timeout: 2\n",
        encoding="utf-8",
    )


@pytest.mark.anyio
async def test_real_core_full_journey_and_retry_after_model_failure(tmp_path: Path) -> None:
    executable = _real_core_executable()
    if not executable.is_file():
        pytest.skip("real docreview executable is not installed")

    model_config = tmp_path / "model-config.yaml"
    settings = Settings(
        environment="test",
        database_url=f"sqlite:///{(tmp_path / 'e2e.db').as_posix()}",
        documents_dir=tmp_path / "documents",
        runs_dir=tmp_path / "runs",
        artifacts_dir=tmp_path / "artifacts",
        review_packs_dir=REPOSITORY_DIRECTORY / "review-packs",
        analysis_executable=str(executable),
        analysis_model_config_path=model_config,
        analysis_timeout_seconds=20,
        process_termination_grace_seconds=1,
        worker_stale_after_seconds=30,
        _env_file=None,
    )
    engine = create_database_engine(settings.database_url)
    Base.metadata.create_all(engine)
    sessions = create_session_factory(engine)
    with sessions.begin() as session:
        company = CompanyModel(
            id=settings.default_company_id,
            slug=settings.default_company_slug,
            display_name=settings.default_company_name,
        )
        pack = ReviewPackReferenceModel(
            company_id=company.id,
            pack_key="mts-net",
            version="0.2",
            display_name="Потоковые данные и витрины",
            locator="mts-net/0.2",
        )
        session.add_all([company, pack])
        session.flush()
        pack_id = pack.id

    server = ThreadingHTTPServer(("127.0.0.1", 0), _EmptyModelHandler)
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    app = create_app(settings)
    document_bytes = _real_docx()

    try:
        _write_model_config(model_config, server.server_port)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            uploaded = await client.post(
                "/api/documents",
                files={
                    "document": (
                        "реальный-документ.docx",
                        document_bytes,
                        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    )
                },
            )
            assert uploaded.status_code == 201, uploaded.text
            document_id = uploaded.json()["document_id"]

            created = await client.post(
                "/api/reviews",
                json={"document_id": document_id, "review_pack_id": str(pack_id)},
                headers={"Idempotency-Key": "real-core-e2e-success"},
            )
            assert created.status_code == 202, created.text
            review_id = created.json()["review_id"]
            assert await build_worker(settings).run_once()

            completed = await client.get(f"/api/reviews/{review_id}")
            findings = await client.get(f"/api/reviews/{review_id}/findings")
            assert completed.json()["status"] == "completed", completed.text
            assert findings.status_code == 200
            assert findings.json()["total"] == len(findings.json()["items"])
            assert findings.json()["total"] > 0
            assert findings.json()["items"][0]["quote"] == "Общие сведения"
            assert findings.json()["items"][0]["detection_layer"] == "rule"

            with sessions() as session:
                saved = session.get(ReviewJobModel, UUID(review_id))
                assert saved is not None
                assert saved.raw_result is not None
                assert findings.json()["total"] == len(saved.raw_result["findings"])

            finding_id = findings.json()["items"][0]["finding_id"]
            feedback = await client.put(
                f"/api/findings/{finding_id}/feedback",
                headers={"X-Actor-Key": "e2e-analyst"},
                json={"decision": "accepted", "comment": "Подтверждено в E2E"},
            )
            saved_feedback = await client.get(
                f"/api/reviews/{review_id}/feedback",
                headers={"X-Actor-Key": "e2e-analyst"},
            )
            assert feedback.status_code == 200
            assert saved_feedback.json()["items"][0]["decision"] == "accepted"

            # A second real run fails at the actual model adapter, is exposed as
            # retriable, and succeeds after the endpoint configuration is repaired.
            _write_model_config(model_config, 1)
            failed_created = await client.post(
                "/api/reviews",
                json={"document_id": document_id, "review_pack_id": str(pack_id)},
                headers={"Idempotency-Key": "real-core-e2e-failure"},
            )
            failed_id = failed_created.json()["review_id"]
            assert await build_worker(settings).run_once()
            failed = await client.get(f"/api/reviews/{failed_id}")
            assert failed.json()["status"] == "failed"
            assert failed.json()["error"]["code"] == "MODEL_UNAVAILABLE"
            assert failed.json()["error"]["retriable"] is True

            _write_model_config(model_config, server.server_port)
            retried = await client.post(
                f"/api/reviews/{failed_id}/retry",
                headers={"Idempotency-Key": "real-core-e2e-retry"},
            )
            assert retried.status_code == 202, retried.text
            retry_id = retried.json()["review_id"]
            assert retry_id != failed_id
            assert await build_worker(settings).run_once()
            retry_completed = await client.get(f"/api/reviews/{retry_id}")
            assert retry_completed.json()["status"] == "completed", retry_completed.text

            with sessions() as session:
                retry_job = session.get(ReviewJobModel, UUID(retry_id))
                assert retry_job is not None
                assert retry_job.retry_of_job_id == UUID(failed_id)
                statuses = session.scalars(select(ReviewJobModel.status)).all()
                assert statuses.count(ReviewJobStatus.COMPLETED) == 2
                assert statuses.count(ReviewJobStatus.FAILED) == 1
    finally:
        server.shutdown()
        server.server_close()
        server_thread.join(timeout=5)
        engine.dispose()
