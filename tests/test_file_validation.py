import io
import zipfile

import pytest

from app.services.file_validation import FileValidationError, validate_uploaded_file


def _docx_bytes() -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("[Content_Types].xml", "<Types />")
        archive.writestr("word/document.xml", "<document />")
    return buffer.getvalue()


def test_txt_validation() -> None:
    result = validate_uploaded_file("notes.txt", "Привіт".encode(), 1024)
    assert result.media_type == "text/plain"


def test_docx_validation_uses_file_signature() -> None:
    result = validate_uploaded_file("knowledge.docx", _docx_bytes(), 4096)
    assert "wordprocessingml" in result.media_type


def test_extension_mismatch_is_rejected() -> None:
    with pytest.raises(FileValidationError):
        validate_uploaded_file("fake.pdf", b"not a pdf", 1024)


def test_path_is_reduced_to_basename() -> None:
    result = validate_uploaded_file("../../notes.txt", b"safe", 1024)
    assert result.filename == "notes.txt"
