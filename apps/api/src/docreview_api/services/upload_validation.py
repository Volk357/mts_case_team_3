"""Pure validation of uploaded document metadata and bytes."""

from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Final
from unicodedata import normalize
from zipfile import BadZipFile, ZipFile

PDF_MEDIA_TYPE: Final = "application/pdf"
DOCX_MEDIA_TYPE: Final = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
SUPPORTED_DOCUMENT_TYPES: Final = {
    ".pdf": PDF_MEDIA_TYPE,
    ".docx": DOCX_MEDIA_TYPE,
}
REQUIRED_DOCX_ENTRIES: Final = frozenset({"[Content_Types].xml", "word/document.xml"})


class UploadValidationError(ValueError):
    """Base class for safe, expected upload validation failures."""


class UnsafeFilenameError(UploadValidationError):
    """Raised when a client filename could represent a path or control data."""


class UnsupportedDocumentTypeError(UploadValidationError):
    """Raised for an extension or declared media type outside PDF/DOCX."""


class EmptyDocumentError(UploadValidationError):
    """Raised when no document bytes were uploaded."""


class UploadTooLargeError(UploadValidationError):
    """Raised when an upload crosses the configured byte limit."""


class DocumentFormatMismatchError(UploadValidationError):
    """Raised when bytes do not match the declared PDF/DOCX type."""


@dataclass(frozen=True)
class ValidatedUpload:
    """Validated public metadata; original bytes are deliberately not retained here."""

    filename: str
    size_bytes: int
    media_type: str
    extension: str


@dataclass(frozen=True)
class ValidatedUploadMetadata:
    """Safe normalized metadata available before document bytes are read."""

    filename: str
    media_type: str
    extension: str


def _normalize_filename(filename: str | None) -> str:
    if filename is None:
        raise UnsafeFilenameError("A document filename is required")
    normalized = normalize("NFC", filename).strip()
    if not normalized:
        raise UnsafeFilenameError("A document filename is required")
    if len(normalized) > 500:
        raise UnsafeFilenameError("The document filename is too long")
    if any(ord(character) < 32 or ord(character) == 127 for character in normalized):
        raise UnsafeFilenameError("The document filename contains control characters")
    if "/" in normalized or "\\" in normalized or normalized in {".", ".."}:
        raise UnsafeFilenameError("The document filename must not contain a path")
    return normalized


def _is_pdf(content: bytes) -> bool:
    return content.startswith(b"%PDF-") and b"%%EOF" in content[-1024:]


def _is_docx(content: bytes) -> bool:
    try:
        with ZipFile(BytesIO(content)) as archive:
            return set(archive.namelist()) >= REQUIRED_DOCX_ENTRIES
    except (BadZipFile, OSError):
        return False


def validate_upload_metadata(
    *, filename: str | None, declared_media_type: str | None
) -> ValidatedUploadMetadata:
    """Validate and normalize a client filename and its declared media type."""

    safe_filename = _normalize_filename(filename)
    extension = Path(safe_filename).suffix.casefold()
    expected_media_type = SUPPORTED_DOCUMENT_TYPES.get(extension)
    if expected_media_type is None:
        raise UnsupportedDocumentTypeError("Only .pdf and .docx files are supported")
    if declared_media_type != expected_media_type:
        raise UnsupportedDocumentTypeError(
            "The declared media type does not match the document extension"
        )
    return ValidatedUploadMetadata(
        filename=safe_filename,
        media_type=expected_media_type,
        extension=extension,
    )


def validate_stored_format(path: Path, extension: str) -> None:
    """Validate actual PDF/DOCX structure from a bounded temporary file."""

    if extension == ".pdf":
        with path.open("rb") as source:
            header = source.read(5)
            source.seek(max(0, path.stat().st_size - 1024))
            trailer = source.read()
        format_matches = header == b"%PDF-" and b"%%EOF" in trailer
    elif extension == ".docx":
        try:
            with ZipFile(path) as archive:
                format_matches = set(archive.namelist()) >= REQUIRED_DOCX_ENTRIES
        except (BadZipFile, OSError):
            format_matches = False
    else:  # pragma: no cover - metadata validation guarantees this invariant
        format_matches = False
    if not format_matches:
        raise DocumentFormatMismatchError(
            "The document content does not match its extension and media type"
        )


def validate_upload(
    *,
    filename: str | None,
    declared_media_type: str | None,
    content: bytes,
    max_size_bytes: int,
) -> ValidatedUpload:
    """Validate filename, size, declared type, and actual PDF/DOCX structure."""

    metadata = validate_upload_metadata(filename=filename, declared_media_type=declared_media_type)
    if not content:
        raise EmptyDocumentError("The uploaded document is empty")
    if len(content) > max_size_bytes:
        raise UploadTooLargeError(f"The uploaded document exceeds {max_size_bytes} bytes")

    format_matches = _is_pdf(content) if metadata.extension == ".pdf" else _is_docx(content)
    if not format_matches:
        raise DocumentFormatMismatchError(
            "The document content does not match its extension and media type"
        )
    return ValidatedUpload(
        filename=metadata.filename,
        size_bytes=len(content),
        media_type=metadata.media_type,
        extension=metadata.extension,
    )
