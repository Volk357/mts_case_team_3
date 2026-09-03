import hashlib
from io import BytesIO
from pathlib import Path
from typing import Final
from unicodedata import is_normalized
from uuid import UUID
from zipfile import ZIP_DEFLATED, ZipFile

import pytest
from httpx import ASGITransport, AsyncClient

from docreview_api.config import Settings
from docreview_api.db.base import Base
from docreview_api.db.models import DocumentModel
from docreview_api.db.session import create_database_engine, create_session_factory
from docreview_api.main import create_app
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
            files={"document": ("notes.txt", b"text", "text/plain")},
        )

    assert response.status_code == 415
    assert response.json() == {
        "error": {
            "code": "DOCUMENT_TYPE_UNSUPPORTED",
            "message": "Only PDF and DOCX documents are supported.",
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
