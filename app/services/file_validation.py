from __future__ import annotations

import io
import zipfile
from dataclasses import dataclass
from pathlib import Path


class FileValidationError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class ValidatedFile:
    filename: str
    media_type: str
    data: bytes


_ALLOWED_EXTENSIONS = {
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".txt": "text/plain",
}


def _safe_display_name(filename: str) -> str:
    normalized = filename.replace("\\", "/")
    name = Path(normalized).name.strip().replace("\x00", "")
    name = "".join(character for character in name if ord(character) >= 32)
    if not name:
        raise FileValidationError("File name is empty")
    if len(name) > 255:
        raise FileValidationError("File name is too long")
    return name


def _looks_like_docx(data: bytes) -> bool:
    if not data.startswith(b"PK"):
        return False
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            entries = archive.infolist()
            if len(entries) > 5000:
                return False
            total_uncompressed = sum(entry.file_size for entry in entries)
            if total_uncompressed > 50 * 1024 * 1024:
                return False
            for entry in entries:
                compressed = max(entry.compress_size, 1)
                if entry.file_size / compressed > 200:
                    return False
            names = {entry.filename for entry in entries}
            return "[Content_Types].xml" in names and "word/document.xml" in names
    except (zipfile.BadZipFile, OSError):
        return False


def _looks_like_text(data: bytes) -> bool:
    if b"\x00" in data:
        return False
    try:
        data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return False
    return True


def validate_uploaded_file(filename: str, data: bytes, max_bytes: int) -> ValidatedFile:
    safe_name = _safe_display_name(filename)
    if not data:
        raise FileValidationError("File is empty")
    if len(data) > max_bytes:
        raise FileValidationError(f"File exceeds the {max_bytes} byte limit")

    extension = Path(safe_name).suffix.lower()
    if extension not in _ALLOWED_EXTENSIONS:
        raise FileValidationError("Only PDF, DOCX, and UTF-8 TXT files are supported")

    if extension == ".pdf" and data.startswith(b"%PDF-"):
        detected = "application/pdf"
    elif extension == ".docx" and _looks_like_docx(data):
        detected = _ALLOWED_EXTENSIONS[extension]
    elif extension == ".txt" and _looks_like_text(data):
        detected = "text/plain"
    else:
        raise FileValidationError("File content does not match its extension")

    return ValidatedFile(filename=safe_name, media_type=detected, data=data)
