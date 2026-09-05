import hashlib
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path
from typing import Final
from unicodedata import is_normalized
from uuid import UUID
from zipfile import ZIP_DEFLATED, ZipFile

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from docreview_api.config import Settings
from docreview_api.db.base import Base
from docreview_api.db.models import (
    CompanyModel,
    DocumentModel,
    ReviewJobModel,
    ReviewPackReferenceModel,
)
from docreview_api.db.session import create_database_engine, create_session_factory
from docreview_api.main import create_app
from docreview_api.models.review_job_state import ReviewJobStatus
from docreview_api.repositories.database import DocumentRepository

PDF_MEDIA_TYPE: Final = "application/pdf"
DOCX_MEDIA_TYPE: Final = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def docx_bytes() -> bytes:
    target = BytesIO()
    with ZipFile(target, "w", ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", "<Types/>")
        archive.writestr("word/document.xml", "<w:document/>")
    return target.getvalue()


@pytest.fixture
def upload_settings(tmp_path: Path) -> Settings:
    database_url = f"sqlite:///{(tmp_path / 'upload.db').as_posix()}"
    engine = create_database_engine(database_url)
    Base.metadata.create_all(engine)
    engine.dispose()
    return Settings(
        environment="test",
        database_url=database_url,
        documents_dir=tmp_path / "documents",
        _env_file=None,
    )


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("filename", "media_type", "content"),
    [
        ("Требования.pdf", PDF_MEDIA_TYPE, b"%PDF-1.7\ntest\n%%EOF"),
        ("Specification.docx", DOCX_MEDIA_TYPE, docx_bytes()),
        ("Витрина.txt", "text/plain", "Описание витрины\nОбновление: ежемесячно".encode()),
    ],
)
async def test_upload_accepts_pdf_and_docx_multipart(
    filename: str,
    media_type: str,
    content: bytes,
    upload_settings: Settings,
) -> None:
    app = create_app(upload_settings)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/documents",
            files={"document": (filename, content, media_type)},
        )

    assert response.status_code == 201
    payload = response.json()
    UUID(payload["document_id"])
    assert payload == {
        "document_id": payload["document_id"],
        "filename": filename,
        "size_bytes": len(content),
        "media_type": media_type,
    }
    engine = create_database_engine(upload_settings.database_url)
    sessions = create_session_factory(engine)
    with sessions() as session:
        stored = DocumentRepository(session).require(UUID(payload["document_id"]))
        stored_path = upload_settings.documents_dir.joinpath(*stored.storage_key.split("/"))
        assert stored.original_filename == filename
        assert stored.sha256 == hashlib.sha256(content).hexdigest()
        assert stored_path.read_bytes() == content
        assert filename not in stored.storage_key
        assert stored_path.is_absolute()
    engine.dispose()


@pytest.mark.anyio
async def test_upload_rejects_an_unsupported_declared_media_type(
    upload_settings: Settings,
) -> None:
    app = create_app(upload_settings)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/documents",
            files={"document": ("notes.rtf", b"{\\rtf1}", "application/rtf")},
        )

    assert response.status_code == 415
    assert response.json() == {
        "error": {
            "code": "DOCUMENT_TYPE_UNSUPPORTED",
            "message": "Only PDF, DOCX and TXT documents are supported.",
            "details": [],
        }
    }


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("filename", "content", "media_type", "expected_status"),
    [
        ("empty.pdf", b"", PDF_MEDIA_TYPE, 422),
        ("fake.pdf", b"This is not a PDF", PDF_MEDIA_TYPE, 422),
        ("wrong.docx", b"%PDF-1.7\n%%EOF", DOCX_MEDIA_TYPE, 422),
        ("../secret.pdf", b"%PDF-1.7\n%%EOF", PDF_MEDIA_TYPE, 422),
        ("folder\\secret.pdf", b"%PDF-1.7\n%%EOF", PDF_MEDIA_TYPE, 422),
    ],
)
async def test_upload_rejects_empty_fake_and_unsafe_documents(
    filename: str,
    content: bytes,
    media_type: str,
    expected_status: int,
    upload_settings: Settings,
) -> None:
    app = create_app(upload_settings)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/documents",
            files={"document": (filename, content, media_type)},
        )

    assert response.status_code == expected_status
    assert not [path for path in upload_settings.documents_dir.rglob("*") if path.is_file()]


@pytest.mark.anyio
async def test_upload_rejects_content_over_configured_limit(upload_settings: Settings) -> None:
    limited_settings = upload_settings.model_copy(update={"max_upload_size_bytes": 8})
    app = create_app(limited_settings)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/documents",
            files={"document": ("large.pdf", b"%PDF-1.7\n%%EOF", PDF_MEDIA_TYPE)},
        )

    assert response.status_code == 413
    assert response.json()["error"] == {
        "code": "DOCUMENT_TOO_LARGE",
        "message": "Document exceeds the configured size limit.",
        "details": [],
    }
    assert not [path for path in upload_settings.documents_dir.rglob("*") if path.is_file()]


@pytest.mark.anyio
async def test_upload_normalizes_unicode_filename_without_losing_cyrillic(
    upload_settings: Settings,
) -> None:
    decomposed_filename = "\u0438\u0306\u043e\u0433\u0443\u0440\u0442.pdf"
    app = create_app(upload_settings)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/documents",
            files={"document": (decomposed_filename, b"%PDF-1.7\n%%EOF", PDF_MEDIA_TYPE)},
        )

    assert response.status_code == 201
    filename = response.json()["filename"]
    assert filename == "\u0439\u043e\u0433\u0443\u0440\u0442.pdf"
    assert is_normalized("NFC", filename)


@pytest.mark.anyio
async def test_upload_openapi_contract_is_multipart_and_path_free(
    upload_settings: Settings,
) -> None:
    app = create_app(upload_settings)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/openapi.json")

    operation = response.json()["paths"]["/api/documents"]["post"]
    assert "multipart/form-data" in operation["requestBody"]["content"]
    response_schema = operation["responses"]["201"]["content"]["application/json"]["schema"]
    assert response_schema == {"$ref": "#/components/schemas/DocumentUploadResponse"}
    public_properties = response.json()["components"]["schemas"]["DocumentUploadResponse"][
        "properties"
    ]
    assert set(public_properties) == {"document_id", "filename", "size_bytes", "media_type"}


@pytest.mark.anyio
async def test_get_document_returns_verified_metadata_with_utc_date(
    upload_settings: Settings,
) -> None:
    app = create_app(upload_settings)
    content = b"%PDF-1.7\nget document\n%%EOF"
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        uploaded = await client.post(
            "/api/documents",
            files={"document": ("Требования.pdf", content, PDF_MEDIA_TYPE)},
        )
        response = await client.get(f"/api/documents/{uploaded.json()['document_id']}")

    assert response.status_code == 200
    payload = response.json()
    assert payload["document_id"] == uploaded.json()["document_id"]
    assert payload["filename"] == "Требования.pdf"
    assert payload["size_bytes"] == len(content)
    assert payload["media_type"] == PDF_MEDIA_TYPE
    assert payload["created_at"].endswith("Z")
    assert set(payload) == {"document_id", "filename", "size_bytes", "media_type", "created_at"}
    assert "storage" not in response.text.casefold()
    assert "sha256" not in response.text.casefold()


@pytest.mark.anyio
async def test_get_unknown_and_deleted_documents_returns_same_safe_not_found(
    upload_settings: Settings,
) -> None:
    app = create_app(upload_settings)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        missing = await client.get(f"/api/documents/{UUID(int=999)}")
        uploaded = await client.post(
            "/api/documents",
            files={"document": ("document.pdf", b"%PDF-1.7\n%%EOF", PDF_MEDIA_TYPE)},
        )
        document_id = UUID(uploaded.json()["document_id"])
        engine = create_database_engine(upload_settings.database_url)
        sessions = create_session_factory(engine)
        with sessions.begin() as session:
            document = session.get(DocumentModel, document_id)
            assert document is not None
            document.deleted_at = document.created_at
        engine.dispose()
        deleted = await client.get(f"/api/documents/{document_id}")

    expected = {
        "error": {"code": "DOCUMENT_NOT_FOUND", "message": "Document was not found.", "details": []}
    }
    assert missing.status_code == 404 and missing.json() == expected
    assert deleted.status_code == 404 and deleted.json() == expected


@pytest.mark.anyio
async def test_get_detects_missing_storage_object_without_exposing_path(
    upload_settings: Settings,
) -> None:
    app = create_app(upload_settings)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        uploaded = await client.post(
            "/api/documents",
            files={"document": ("document.pdf", b"%PDF-1.7\n%%EOF", PDF_MEDIA_TYPE)},
        )
        document_id = UUID(uploaded.json()["document_id"])
        engine = create_database_engine(upload_settings.database_url)
        sessions = create_session_factory(engine)
        with sessions() as session:
            document = DocumentRepository(session).require(document_id)
            stored_path = upload_settings.documents_dir.joinpath(*document.storage_key.split("/"))
        engine.dispose()
        stored_path.unlink()
        response = await client.get(f"/api/documents/{document_id}")

    assert response.status_code == 409
    assert response.json() == {
        "error": {
            "code": "DOCUMENT_FILE_UNAVAILABLE",
            "message": "Document content is temporarily unavailable.",
            "details": [],
        }
    }
    assert str(stored_path) not in response.text


@pytest.mark.anyio
async def test_repeated_identical_upload_creates_independent_documents(
    upload_settings: Settings,
) -> None:
    app = create_app(upload_settings)
    content = b"%PDF-1.7\nsame content\n%%EOF"
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        first = await client.post(
            "/api/documents",
            files={"document": ("first.pdf", content, PDF_MEDIA_TYPE)},
        )
        second = await client.post(
            "/api/documents",
            files={"document": ("second.pdf", content, PDF_MEDIA_TYPE)},
        )
        first_read = await client.get(f"/api/documents/{first.json()['document_id']}")
        second_read = await client.get(f"/api/documents/{second.json()['document_id']}")

    assert first.status_code == second.status_code == 201
    assert first.json()["document_id"] != second.json()["document_id"]
    assert first_read.json()["filename"] == "first.pdf"
    assert second_read.json()["filename"] == "second.pdf"
    engine = create_database_engine(upload_settings.database_url)
    sessions = create_session_factory(engine)
    with sessions() as session:
        stored = [
            DocumentRepository(session).require(UUID(response.json()["document_id"]))
            for response in (first, second)
        ]
        assert stored[0].sha256 == stored[1].sha256 == hashlib.sha256(content).hexdigest()
        assert stored[0].storage_key != stored[1].storage_key
    engine.dispose()


@pytest.mark.anyio
async def test_documents_get_openapi_uses_uuid_and_path_free_response(
    upload_settings: Settings,
) -> None:
    app = create_app(upload_settings)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        schema = (await client.get("/api/openapi.json")).json()

    operation = schema["paths"]["/api/documents/{document_id}"]["get"]
    parameter = operation["parameters"][0]
    assert parameter["name"] == "document_id"
    assert parameter["schema"]["format"] == "uuid"
    response = schema["components"]["schemas"]["DocumentResponse"]
    assert set(response["properties"]) == {
        "document_id",
        "filename",
        "size_bytes",
        "media_type",
        "created_at",
    }


@pytest.mark.anyio
async def test_uploaded_document_can_be_deleted(upload_settings: Settings) -> None:
    """Человек должен уметь убрать ранее загруженный файл сам.

    Проверяем, что файл действительно исчезает с диска, а не только из выдачи:
    ради этого удаление и делается.
    """

    app = create_app(upload_settings)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        uploaded = await client.post(
            "/api/documents",
            files={"document": ("Витрина.txt", "текст витрины".encode(), "text/plain")},
        )
        document_id = uploaded.json()["document_id"]

        stored = list(upload_settings.documents_dir.rglob("*.txt"))
        assert len(stored) == 1, stored

        deleted = await client.delete(f"/api/documents/{document_id}")
        missing = await client.get(f"/api/documents/{document_id}")

    assert uploaded.status_code == 201
    assert deleted.status_code == 204
    assert missing.status_code == 404
    assert not stored[0].exists()


@pytest.mark.anyio
async def test_deleting_a_document_twice_is_not_an_error_for_the_second_caller(
    upload_settings: Settings,
) -> None:
    """Повторное удаление отвечает 404, а не падает: запись уже помечена."""

    app = create_app(upload_settings)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        uploaded = await client.post(
            "/api/documents",
            files={"document": ("Витрина.txt", "текст".encode(), "text/plain")},
        )
        document_id = uploaded.json()["document_id"]
        first = await client.delete(f"/api/documents/{document_id}")
        second = await client.delete(f"/api/documents/{document_id}")

    assert first.status_code == 204
    assert second.status_code == 404


@pytest.mark.anyio
async def test_document_under_review_is_not_deleted(upload_settings: Settings) -> None:
    """Пока проверка не завершилась, воркер читает файл — сносить его нельзя."""

    app = create_app(upload_settings)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        uploaded = await client.post(
            "/api/documents",
            files={"document": ("Витрина.txt", "текст".encode(), "text/plain")},
        )
        document_id = uploaded.json()["document_id"]

    engine = create_database_engine(upload_settings.database_url)
    sessions = create_session_factory(engine)
    with sessions.begin() as session:
        company = session.scalar(select(CompanyModel))
        if company is None:
            company = CompanyModel(
                id=upload_settings.default_company_id,
                slug=upload_settings.default_company_slug,
                display_name=upload_settings.default_company_name,
            )
            session.add(company)
            session.flush()
        pack = ReviewPackReferenceModel(
            company_id=company.id,
            pack_key="requirements",
            version="1.0",
            display_name="Requirements",
            locator="review-packs/requirements/1.0",
        )
        session.add(pack)
        session.flush()
        session.add(
            ReviewJobModel(
                run_id="review-active",
                company_id=company.id,
                document_id=UUID(document_id),
                review_pack_reference_id=pack.id,
                status=ReviewJobStatus.RUNNING,
                queued_at=datetime.now(UTC),
            )
        )
    engine.dispose()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        blocked = await client.delete(f"/api/documents/{document_id}")

    assert blocked.status_code == 409
    assert blocked.json()["error"]["code"] == "DOCUMENT_BUSY"
    assert list(upload_settings.documents_dir.rglob("*.txt"))


@pytest.mark.anyio
async def test_review_cannot_be_created_for_a_deleted_document(
    upload_settings: Settings,
) -> None:
    """Гонка «удаляем файл ↔ ставим проверку» закрыта порядком операций.

    Удаление сначала помечает документ и лишь потом стирает файл, поэтому
    момента «файла нет, а ставить проверку ещё можно» не существует.
    Проверяем следствие: после удаления постановка отвергается, а не создаёт
    задачу, которая упадёт на чтении отсутствующего исходника.
    """

    app = create_app(upload_settings)

    engine = create_database_engine(upload_settings.database_url)
    sessions = create_session_factory(engine)
    with sessions.begin() as session:
        company = session.scalar(select(CompanyModel))
        if company is None:
            company = CompanyModel(
                id=upload_settings.default_company_id,
                slug=upload_settings.default_company_slug,
                display_name=upload_settings.default_company_name,
            )
            session.add(company)
            session.flush()
        pack = ReviewPackReferenceModel(
            company_id=company.id,
            pack_key="requirements",
            version="1.0",
            display_name="Requirements",
            locator="review-packs/requirements/1.0",
        )
        session.add(pack)
        session.flush()
        pack_id = str(pack.id)
    engine.dispose()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        uploaded = await client.post(
            "/api/documents",
            files={"document": ("Витрина.txt", "текст".encode(), "text/plain")},
        )
        document_id = uploaded.json()["document_id"]

        await client.delete(f"/api/documents/{document_id}")
        queued = await client.post(
            "/api/reviews",
            json={"document_id": document_id, "review_pack_id": pack_id},
            headers={"Idempotency-Key": "after-delete-1"},
        )

    assert queued.status_code == 404, queued.text
    assert not list(upload_settings.documents_dir.rglob("*.txt"))


@pytest.mark.anyio
async def test_delete_marks_the_row_before_removing_the_file(
    upload_settings: Settings,
) -> None:
    """Порядок внутри удаления: пометка, потом файл.

    Если бы файл стирался первым, между его исчезновением и запретом на новые
    проверки оставался бы промежуток, в который задача успевала бы встать в
    очередь. Проверяем сам инвариант: файла нет и запись помечена.
    """

    app = create_app(upload_settings)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        uploaded = await client.post(
            "/api/documents",
            files={"document": ("Витрина.txt", "текст".encode(), "text/plain")},
        )
        document_id = uploaded.json()["document_id"]
        await client.delete(f"/api/documents/{document_id}")

    engine = create_database_engine(upload_settings.database_url)
    sessions = create_session_factory(engine)
    with sessions() as session:
        row = session.get(DocumentModel, UUID(document_id))
        assert row is not None
        assert row.deleted_at is not None
    engine.dispose()
    assert not list(upload_settings.documents_dir.rglob("*.txt"))


def test_delete_and_create_review_do_not_interleave(upload_settings: Settings) -> None:
    """Конкурентный сценарий: удаление и постановка проверки в двух потоках.

    Запрещённое состояние — задача в очереди на документ, файла которого уже
    нет: воркер поднимет её и упадёт на чтении исходника. Оба исхода гонки
    допустимы (успела проверка или успело удаление), недопустимо только их
    сочетание. Прогоняем повторно, потому что гонка по своей природе
    воспроизводится не с первого раза.
    """

    import threading

    from docreview_api.services.documents import (
        DocumentBusyError,
        DocumentCleanupService,
        DocumentUnavailableError,
    )
    from docreview_api.services.review_jobs import (
        ReviewJobDocumentUnavailableError,
        ReviewJobService,
    )

    engine = create_database_engine(upload_settings.database_url)
    Base.metadata.create_all(engine)
    sessions = create_session_factory(engine)

    with sessions.begin() as session:
        company = session.scalar(select(CompanyModel))
        if company is None:
            company = CompanyModel(
                id=upload_settings.default_company_id,
                slug=upload_settings.default_company_slug,
                display_name=upload_settings.default_company_name,
            )
            session.add(company)
            session.flush()
        pack = ReviewPackReferenceModel(
            company_id=company.id,
            pack_key="requirements",
            version="1.0",
            display_name="Requirements",
            locator="review-packs/requirements/1.0",
        )
        session.add(pack)
        session.flush()
        company_id, pack_id = company.id, pack.id

    documents_dir = upload_settings.documents_dir
    documents_dir.mkdir(parents=True, exist_ok=True)

    for attempt in range(12):
        storage_key = f"{company_id.hex}/race-{attempt}.txt"
        path = documents_dir / storage_key
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("текст витрины", encoding="utf-8")
        with sessions.begin() as session:
            document = DocumentModel(
                company_id=company_id,
                original_filename="Витрина.txt",
                media_type="text/plain",
                size_bytes=path.stat().st_size,
                sha256="d" * 64,
                storage_key=storage_key,
            )
            session.add(document)
            session.flush()
            document_id = document.id

        start = threading.Barrier(2)
        outcome: dict[str, object] = {}

        def do_delete() -> None:
            start.wait()
            try:
                DocumentCleanupService(sessions, documents_root=documents_dir).delete(
                    document_id, company_id=company_id
                )
                outcome["deleted"] = True
            except (DocumentUnavailableError, DocumentBusyError):
                outcome["deleted"] = False
            except Exception as error:  # noqa: BLE001 - фиксируем для отчёта
                outcome["delete_error"] = repr(error)

        def do_create() -> None:
            start.wait()
            try:
                with sessions.begin() as session:
                    ReviewJobService(session).create(
                        company_id=company_id,
                        document_id=document_id,
                        review_pack_reference_id=pack_id,
                        idempotency_key=f"race-{attempt}",
                    )
                outcome["queued"] = True
            except ReviewJobDocumentUnavailableError:
                outcome["queued"] = False
            except Exception as error:  # noqa: BLE001 - фиксируем для отчёта
                outcome["create_error"] = repr(error)

        threads = [threading.Thread(target=do_delete), threading.Thread(target=do_create)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=15)

        assert "delete_error" not in outcome, outcome
        assert "create_error" not in outcome, outcome

        with sessions() as session:
            row = session.get(DocumentModel, document_id)
            assert row is not None
            marked_deleted = row.deleted_at is not None
            job_exists = session.scalar(
                select(ReviewJobModel.id).where(ReviewJobModel.document_id == document_id)
            )

        file_exists = path.exists()
        # Инвариант: задачи на документ без файла быть не может.
        assert not (job_exists is not None and not file_exists), (
            attempt,
            outcome,
            {"marked_deleted": marked_deleted, "file_exists": file_exists},
        )
        # И наоборот: помечен удалённым — значит файла нет.
        assert marked_deleted == (not file_exists), (attempt, outcome)

    engine.dispose()
