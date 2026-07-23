from __future__ import annotations

from dataclasses import dataclass

from app.services.text_extractors import TextSection


@dataclass(frozen=True, slots=True)
class TextChunk:
    page_number: int | None
    chunk_index: int
    content: str


def _best_split_position(text: str, start: int, hard_end: int, minimum_end: int) -> int:
    candidates = [
        text.rfind("\n\n", minimum_end, hard_end),
        text.rfind("\n", minimum_end, hard_end),
        text.rfind(". ", minimum_end, hard_end),
        text.rfind("! ", minimum_end, hard_end),
        text.rfind("? ", minimum_end, hard_end),
        text.rfind("; ", minimum_end, hard_end),
        text.rfind(" ", minimum_end, hard_end),
    ]
    position = max(candidates)
    if position <= start:
        return hard_end
    return position + 1


def chunk_sections(
    sections: list[TextSection],
    chunk_size: int,
    overlap: int,
) -> list[TextChunk]:
    if chunk_size <= 0:
        raise ValueError("chunk_size must be positive")
    if overlap < 0 or overlap >= chunk_size:
        raise ValueError("overlap must be non-negative and smaller than chunk_size")

    chunks: list[TextChunk] = []
    chunk_index = 0

    for section in sections:
        text = section.text.strip()
        start = 0
        while start < len(text):
            hard_end = min(start + chunk_size, len(text))
            if hard_end < len(text):
                minimum_end = min(start + max(chunk_size // 2, 1), hard_end)
                end = _best_split_position(text, start, hard_end, minimum_end)
            else:
                end = hard_end

            content = text[start:end].strip()
            if content:
                chunks.append(
                    TextChunk(
                        page_number=section.page_number,
                        chunk_index=chunk_index,
                        content=content,
                    )
                )
                chunk_index += 1

            if end >= len(text):
                break
            next_start = max(end - overlap, start + 1)
            start = next_start

    return chunks
