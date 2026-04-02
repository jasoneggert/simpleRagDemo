from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(slots=True)
class ChunkRecord:
    chunk_id: str
    document_id: str
    source_path: str
    title: str
    heading: str | None
    content: str


def _normalize_whitespace(text: str) -> str:
    return "\n".join(line.rstrip() for line in text.strip().splitlines()).strip()


def chunk_markdown_file(file_path: Path, chunk_size: int, chunk_overlap: int) -> list[ChunkRecord]:
    raw_text = file_path.read_text(encoding="utf-8")
    normalized_text = _normalize_whitespace(raw_text)
    lines = normalized_text.splitlines()

    title = file_path.stem.replace("-", " ").title()
    heading: str | None = None
    segments: list[tuple[str | None, str]] = []
    current: list[str] = []

    for line in lines:
        if line.startswith("#"):
            if current:
                segments.append((heading, "\n".join(current).strip()))
                current = []
            heading = line.lstrip("#").strip() or None
        current.append(line)

    if current:
        segments.append((heading, "\n".join(current).strip()))

    chunks: list[ChunkRecord] = []
    chunk_index = 0
    for segment_heading, segment_text in segments:
        start = 0
        while start < len(segment_text):
            end = min(len(segment_text), start + chunk_size)
            content = segment_text[start:end].strip()
            if content:
                chunks.append(
                    ChunkRecord(
                        chunk_id=f"{file_path.stem}-chunk-{chunk_index}",
                        document_id=file_path.stem,
                        source_path=str(file_path),
                        title=title,
                        heading=segment_heading,
                        content=content,
                    )
                )
                chunk_index += 1
            if end >= len(segment_text):
                break
            start = max(end - chunk_overlap, start + 1)

    return chunks
