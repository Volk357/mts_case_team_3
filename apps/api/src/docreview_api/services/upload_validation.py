"""Pure validation of uploaded document metadata and bytes."""

from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Final
from unicodedata import normalize
from zipfile import BadZipFile, ZipFile

PDF_MEDIA_TYPE: Final = "application/pdf"
DOCX_MEDIA_TYPE: Final = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
TXT_MEDIA_TYPE: Final = "text/plain"
SUPPORTED_DOCUMENT_TYPES: Final = {
    ".pdf": PDF_MEDIA_TYPE,
    ".docx": DOCX_MEDIA_TYPE,
    ".txt": TXT_MEDIA_TYPE,
}

# Что клиент вправе объявить для каждого расширения. Для .pdf и .docx тип
# определяется однозначно, а вот текстовый файл браузеры помечают
# по-разному — от text/plain до application/octet-stream, а иногда не
# помечают вовсе. Требовать здесь единственного значения означало бы
# отбивать заведомо годные .txt, поэтому набор шире, а хранится всё равно
# канонический тип.
ACCEPTED_MEDIA_TYPES: Final = {
    ".pdf": frozenset({PDF_MEDIA_TYPE}),
    ".docx": frozenset({DOCX_MEDIA_TYPE}),
    ".txt": frozenset(
        {TXT_MEDIA_TYPE, "text/markdown", "application/octet-stream", ""}
    ),
}
REQUIRED_DOCX_ENTRIES: Final = frozenset({"[Content_Types].xml", "word/document.xml"})

# Сколько байт от начала файла проверяем на признаки двоичного содержимого.
TEXT_PROBE_BYTES: Final = 8192

# Метки порядка байт текстовых кодировок. В UTF-16 и UTF-32 каждый символ
# латиницы содержит NUL, поэтому без разбора BOM обычный текстовый файл в
# этих кодировках выглядит двоичным. Порядок важен: BOM UTF-32 начинается
# с BOM UTF-16, и проверка «сначала короткий» приняла бы одно за другое.
TEXT_BOMS: Final = (
    (b"\xff\xfe\x00\x00", "utf-32"),
    (b"\x00\x00\xfe\xff", "utf-32"),
    (b"\xef\xbb\xbf", "utf-8-sig"),
    (b"\xff\xfe", "utf-16"),
    (b"\xfe\xff", "utf-16"),
)


class UploadValidationError(ValueError):
    """Base class for safe, expected upload validation failures."""


class UnsafeFilenameError(UploadValidationError):
    """Raised when a client filename could represent a path or control data."""


class UnsupportedDocumentTypeError(UploadValidationError):
    """Raised for an extension or declared media type outside PDF/DOCX/TXT."""


class EmptyDocumentError(UploadValidationError):
    """Raised when no document bytes were uploaded."""


class UploadTooLargeError(UploadValidationError):
    """Raised when an upload crosses the configured byte limit."""


class DocumentFormatMismatchError(UploadValidationError):
    """Raised when bytes do not match the declared PDF/DOCX/TXT type."""


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


def _decodes_cleanly(content: bytes, encoding: str) -> bool:
    """Читается ли начало файла объявленной кодировкой как осмысленный текст."""

    probe = content[:TEXT_PROBE_BYTES]
    # Строгое декодирование, допуская ТОЛЬКО обрыв на границе окна: срезаем
    # не больше трёх байт с конца. errors="ignore" здесь недопустим — он
    # выбрасывает битые байты по всему буферу, и «BOM + текст + двоичный
    # хвост» прошёл бы как обычный текст.
    head: str | None = None
    for cut in range(4):
        chunk = probe[: len(probe) - cut] if cut else probe
        try:
            head = chunk.decode(encoding, errors="strict")
            break
        except (UnicodeDecodeError, LookupError):
            continue
    if head is None:
        return False
    if not head.strip():
        return False
    control = sum(1 for character in head if ord(character) < 32 and character not in "\t\n\r")
    if control * 20 > len(head):
        return False
    # Второй признак: в связном тексте есть пробелы и переводы строк. В UTF-16
    # произвольные байты складываются в формально печатные символы, и одной
    # проверки на управляющие мало — она такой мусор пропускает.
    if len(head) >= 40:
        spaces = sum(1 for character in head if character.isspace())
        if spaces * 50 < len(head):
            return False
    return True


def _is_text(content: bytes) -> bool:
    """Текстовый ли файл.

    Проверяем не «декодируется ли целиком», а отсутствие NUL-байтов в начале:
    ядро всё равно читает текст с errors="replace", и отбивать документ
    из-за одного битого символа в середине было бы вреднее, чем принять его.

    Исключение — файлы с BOM: UTF-16 и UTF-32 полны NUL по устройству
    кодировки, и без этой проверки обычный .txt из «Блокнота» отбивался бы
    как двоичный.
    """
    if not content.strip():
        return False
    for bom, encoding in TEXT_BOMS:
        if content.startswith(bom):
            # BOM объявляет кодировку, но не доказывает, что дальше текст:
            # пометить его можно и двоичной нагрузкой. Проверяем содержимое.
            return _decodes_cleanly(content, encoding)
    return b"\x00" not in content[:TEXT_PROBE_BYTES]


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
        raise UnsupportedDocumentTypeError("Only .pdf, .docx and .txt files are supported")
    accepted = ACCEPTED_MEDIA_TYPES[extension]
    if (declared_media_type or "") not in accepted:
        raise UnsupportedDocumentTypeError(
            "The declared media type does not match the document extension"
        )
    return ValidatedUploadMetadata(
        filename=safe_filename,
        media_type=expected_media_type,
        extension=extension,
    )


def validate_stored_format(path: Path, extension: str) -> None:
    """Validate actual PDF/DOCX/TXT structure from a bounded temporary file."""

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
    elif extension == ".txt":
        with path.open("rb") as source:
            format_matches = _is_text(source.read(TEXT_PROBE_BYTES))
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
    """Validate filename, size, declared type, and actual PDF/DOCX/TXT structure."""

    metadata = validate_upload_metadata(filename=filename, declared_media_type=declared_media_type)
    if not content:
        raise EmptyDocumentError("The uploaded document is empty")
    if len(content) > max_size_bytes:
        raise UploadTooLargeError(f"The uploaded document exceeds {max_size_bytes} bytes")

    if metadata.extension == ".pdf":
        format_matches = _is_pdf(content)
    elif metadata.extension == ".docx":
        format_matches = _is_docx(content)
    else:
        format_matches = _is_text(content)
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
