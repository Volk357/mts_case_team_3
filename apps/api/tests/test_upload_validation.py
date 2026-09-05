from io import BytesIO
from zipfile import ZipFile

import pytest

from docreview_api.services.upload_validation import (
    DOCX_MEDIA_TYPE,
    PDF_MEDIA_TYPE,
    DocumentFormatMismatchError,
    EmptyDocumentError,
    UnsafeFilenameError,
    UnsupportedDocumentTypeError,
    UploadTooLargeError,
    validate_upload,
)


def make_docx(*, include_document: bool = True) -> bytes:
    target = BytesIO()
    with ZipFile(target, "w") as archive:
        archive.writestr("[Content_Types].xml", "<Types/>")
        if include_document:
            archive.writestr("word/document.xml", "<w:document/>")
    return target.getvalue()


def test_pdf_and_docx_actual_formats_are_accepted() -> None:
    pdf = validate_upload(
        filename="report.PDF",
        declared_media_type=PDF_MEDIA_TYPE,
        content=b"%PDF-1.7\ncontent\n%%EOF\n",
        max_size_bytes=1024,
    )
    docx = validate_upload(
        filename="specification.docx",
        declared_media_type=DOCX_MEDIA_TYPE,
        content=make_docx(),
        max_size_bytes=1024,
    )

    assert pdf.extension == ".pdf"
    assert pdf.media_type == PDF_MEDIA_TYPE
    assert docx.extension == ".docx"
    assert docx.media_type == DOCX_MEDIA_TYPE


@pytest.mark.parametrize("filename", [None, "", "   ", ".", "..", "a/b.pdf", "a\\b.pdf"])
def test_unsafe_or_missing_filename_is_rejected(filename: str | None) -> None:
    with pytest.raises(UnsafeFilenameError):
        validate_upload(
            filename=filename,
            declared_media_type=PDF_MEDIA_TYPE,
            content=b"%PDF-1.7\n%%EOF",
            max_size_bytes=1024,
        )


def test_filename_control_characters_and_excessive_length_are_rejected() -> None:
    for filename in ("bad\nname.pdf", f"{'a' * 501}.pdf"):
        with pytest.raises(UnsafeFilenameError):
            validate_upload(
                filename=filename,
                declared_media_type=PDF_MEDIA_TYPE,
                content=b"%PDF-1.7\n%%EOF",
                max_size_bytes=1024,
            )


@pytest.mark.parametrize(
    ("filename", "media_type"),
    [
        ("notes.rtf", "text/plain"),
        ("report.pdf", DOCX_MEDIA_TYPE),
        ("specification.docx", PDF_MEDIA_TYPE),
        ("report.pdf", None),
    ],
)
def test_extension_and_declared_media_type_must_agree(
    filename: str,
    media_type: str | None,
) -> None:
    with pytest.raises(UnsupportedDocumentTypeError):
        validate_upload(
            filename=filename,
            declared_media_type=media_type,
            content=b"content",
            max_size_bytes=1024,
        )


def test_empty_and_oversized_documents_are_rejected() -> None:
    with pytest.raises(EmptyDocumentError):
        validate_upload(
            filename="empty.pdf",
            declared_media_type=PDF_MEDIA_TYPE,
            content=b"",
            max_size_bytes=1024,
        )
    with pytest.raises(UploadTooLargeError):
        validate_upload(
            filename="large.pdf",
            declared_media_type=PDF_MEDIA_TYPE,
            content=b"%PDF-1.7\n%%EOF",
            max_size_bytes=8,
        )


@pytest.mark.parametrize(
    ("filename", "media_type", "content"),
    [
        ("fake.pdf", PDF_MEDIA_TYPE, b"plain text"),
        ("truncated.pdf", PDF_MEDIA_TYPE, b"%PDF-1.7 without eof"),
        ("fake.docx", DOCX_MEDIA_TYPE, b"PK not really a zip"),
        ("incomplete.docx", DOCX_MEDIA_TYPE, make_docx(include_document=False)),
    ],
)
def test_spoofed_or_incomplete_format_is_rejected(
    filename: str,
    media_type: str,
    content: bytes,
) -> None:
    with pytest.raises(DocumentFormatMismatchError):
        validate_upload(
            filename=filename,
            declared_media_type=media_type,
            content=content,
            max_size_bytes=1024,
        )


@pytest.mark.parametrize(
    "media_type",
    ["text/plain", "text/markdown", "application/octet-stream", None],
)
def test_txt_is_accepted_with_any_reasonable_declared_type(media_type: str | None) -> None:
    """Браузеры помечают текстовый файл по-разному, а иногда не помечают вовсе.
    Отбивать из-за этого годный .txt нельзя — формат заявлен как поддерживаемый."""

    result = validate_upload(
        filename="Витрина.txt",
        declared_media_type=media_type,
        content="Описание витрины\nРегламент расчёта: ежемесячно".encode(),
        max_size_bytes=1024,
    )

    assert result.extension == ".txt"
    assert result.media_type == "text/plain"


def test_binary_content_renamed_to_txt_is_rejected() -> None:
    """NUL-байты — надёжный признак двоичного файла под видом текстового."""

    with pytest.raises(DocumentFormatMismatchError):
        validate_upload(
            filename="fake.txt",
            declared_media_type="text/plain",
            content=b"PK\x03\x04\x00\x00binary\x00payload",
            max_size_bytes=1024,
        )


@pytest.mark.parametrize("encoding", ["utf-8", "utf-8-sig", "utf-16", "utf-32"])
def test_txt_in_utf16_and_utf32_is_accepted(encoding: str) -> None:
    """В UTF-16/32 каждый латинский символ содержит NUL. Проверка «есть NUL —
    значит двоичный» отбивала бы обычный текстовый файл из «Блокнота»."""

    result = validate_upload(
        filename="Витрина.txt",
        declared_media_type="text/plain",
        content="Описание витрины".encode(encoding),
        max_size_bytes=4096,
    )

    assert result.extension == ".txt"


@pytest.mark.parametrize(
    ("bom", "payload"),
    [
        (b"\xff\xfe", bytes(range(256)) * 4),
        (b"\xef\xbb\xbf", b"\x01\x02\x03\x04" * 200),
        # Двоичный хвост после валидного текста: проверка обязана смотреть
        # весь буфер, а не только его начало.
        (b"\xef\xbb\xbf", b"normal text " * 100 + b"\xff" * 100),
    ],
)
def test_bom_prefixed_binary_is_rejected(bom: bytes, payload: bytes) -> None:
    """BOM можно приписать и двоичному файлу: проверяем содержимое, а не метку."""

    with pytest.raises(DocumentFormatMismatchError):
        validate_upload(
            filename="fake.txt",
            declared_media_type="text/plain",
            content=bom + payload,
            max_size_bytes=100000,
        )


def test_long_utf16_text_survives_probe_boundary() -> None:
    """Окно проверки может оборваться посреди символа — это не повод отказать."""

    result = validate_upload(
        filename="Витрина.txt",
        declared_media_type="text/plain",
        content=("Описание витрины. " * 600).encode("utf-16"),
        max_size_bytes=100000,
    )

    assert result.extension == ".txt"
