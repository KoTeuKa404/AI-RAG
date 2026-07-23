from app.services.chunking import chunk_sections
from app.services.text_extractors import TextSection


def test_chunking_preserves_page_and_creates_multiple_chunks() -> None:
    text = " ".join(f"word{i}" for i in range(300))
    chunks = chunk_sections(
        [TextSection(page_number=3, text=text)],
        chunk_size=180,
        overlap=30,
    )

    assert len(chunks) > 1
    assert all(chunk.page_number == 3 for chunk in chunks)
    assert [chunk.chunk_index for chunk in chunks] == list(range(len(chunks)))
    assert all(0 < len(chunk.content) <= 180 for chunk in chunks)


def test_chunking_rejects_invalid_overlap() -> None:
    try:
        chunk_sections([TextSection(page_number=None, text="hello")], 100, 100)
    except ValueError as exc:
        assert "overlap" in str(exc)
    else:
        raise AssertionError("Expected ValueError")
