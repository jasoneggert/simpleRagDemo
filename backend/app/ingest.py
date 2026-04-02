from __future__ import annotations

from pathlib import Path

from app.chunking import ChunkRecord, chunk_markdown_file
from app.config import settings
from app.embeddings import embed_texts
from app.vectorstore import get_chroma_collection


def load_seed_docs(seed_docs_dir: Path | None = None) -> list[Path]:
    docs_dir = seed_docs_dir or settings.seed_docs_dir
    return sorted(docs_dir.glob("*.md"))


def build_chunks() -> list[ChunkRecord]:
    chunks: list[ChunkRecord] = []
    for doc_path in load_seed_docs():
        chunks.extend(
            chunk_markdown_file(
                file_path=doc_path,
                chunk_size=settings.chunk_size,
                chunk_overlap=settings.chunk_overlap,
            )
        )
    return chunks


def ingest_seed_docs() -> dict[str, int]:
    chunks = build_chunks()
    collection = get_chroma_collection()

    if not chunks:
        return {"documents": 0, "chunks": 0}

    embeddings = embed_texts([chunk.content for chunk in chunks])
    collection.upsert(
        ids=[chunk.chunk_id for chunk in chunks],
        documents=[chunk.content for chunk in chunks],
        embeddings=embeddings,
        metadatas=[
            {
                "document_id": chunk.document_id,
                "source_path": chunk.source_path,
                "title": chunk.title,
                "heading": chunk.heading or "",
            }
            for chunk in chunks
        ],
    )
    return {
        "documents": len({chunk.document_id for chunk in chunks}),
        "chunks": len(chunks),
    }
