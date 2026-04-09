from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from app.config import settings


IndexStatus = Literal["missing", "stale", "ready"]


@dataclass
class IndexMetadata:
    demo_mode: bool
    embedding_model: str
    chunk_size: int
    chunk_overlap: int
    seed_docs_fingerprint: str
    last_ingested_at: str


@dataclass
class IndexState:
    status: IndexStatus
    chunk_count: int
    reason: str
    current: IndexMetadata
    stored: IndexMetadata | None


def _metadata_path() -> Path:
    return settings.chroma_dir / f"{settings.chroma_collection_name}.metadata.json"


def _hash_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def compute_seed_docs_fingerprint() -> str:
    digest = hashlib.sha256()
    docs = sorted(settings.seed_docs_dir.glob("*.md"))
    for doc_path in docs:
        digest.update(str(doc_path.relative_to(settings.seed_docs_dir)).encode("utf-8"))
        digest.update(b"\0")
        digest.update(_hash_bytes(doc_path.read_bytes()).encode("utf-8"))
        digest.update(b"\0")
    return digest.hexdigest()


def build_current_index_metadata() -> IndexMetadata:
    return IndexMetadata(
        demo_mode=settings.demo_mode,
        embedding_model=settings.openai_embedding_model,
        chunk_size=settings.chunk_size,
        chunk_overlap=settings.chunk_overlap,
        seed_docs_fingerprint=compute_seed_docs_fingerprint(),
        last_ingested_at="",
    )


def read_index_metadata() -> IndexMetadata | None:
    metadata_path = _metadata_path()
    if not metadata_path.exists():
        return None

    payload = json.loads(metadata_path.read_text(encoding="utf-8"))
    return IndexMetadata(
        demo_mode=bool(payload["demo_mode"]),
        embedding_model=str(payload["embedding_model"]),
        chunk_size=int(payload["chunk_size"]),
        chunk_overlap=int(payload["chunk_overlap"]),
        seed_docs_fingerprint=str(payload["seed_docs_fingerprint"]),
        last_ingested_at=str(payload["last_ingested_at"]),
    )


def write_index_metadata(metadata: IndexMetadata) -> None:
    metadata_path = _metadata_path()
    metadata_path.parent.mkdir(parents=True, exist_ok=True)
    metadata_path.write_text(
        json.dumps(
            {
                "demo_mode": metadata.demo_mode,
                "embedding_model": metadata.embedding_model,
                "chunk_size": metadata.chunk_size,
                "chunk_overlap": metadata.chunk_overlap,
                "seed_docs_fingerprint": metadata.seed_docs_fingerprint,
                "last_ingested_at": metadata.last_ingested_at,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )


def clear_index_metadata() -> None:
    metadata_path = _metadata_path()
    if metadata_path.exists():
        metadata_path.unlink()


def resolve_index_state(chunk_count: int) -> IndexState:
    current = build_current_index_metadata()
    stored = read_index_metadata()

    if chunk_count == 0:
        return IndexState(
            status="missing",
            chunk_count=0,
            reason="No persisted chunks were found for the active collection.",
            current=current,
            stored=stored,
        )

    if stored is None:
        return IndexState(
            status="stale",
            chunk_count=chunk_count,
            reason="Chunks exist, but index metadata is missing. Rebuild the index once to record compatibility metadata.",
            current=current,
            stored=None,
        )

    mismatches: list[str] = []
    if stored.demo_mode != current.demo_mode:
        mismatches.append("DEMO_MODE")
    if stored.embedding_model != current.embedding_model:
        mismatches.append("OPENAI_EMBEDDING_MODEL")
    if stored.chunk_size != current.chunk_size:
        mismatches.append("CHUNK_SIZE")
    if stored.chunk_overlap != current.chunk_overlap:
        mismatches.append("CHUNK_OVERLAP")
    if stored.seed_docs_fingerprint != current.seed_docs_fingerprint:
        mismatches.append("seed docs")

    if mismatches:
        return IndexState(
            status="stale",
            chunk_count=chunk_count,
            reason="The persisted index is stale because these inputs changed: " + ", ".join(mismatches) + ".",
            current=current,
            stored=stored,
        )

    return IndexState(
        status="ready",
        chunk_count=chunk_count,
        reason="The persisted Chroma index matches the active configuration and seed docs.",
        current=current,
        stored=stored,
    )


def build_ingested_metadata() -> IndexMetadata:
    current = build_current_index_metadata()
    return IndexMetadata(
        demo_mode=current.demo_mode,
        embedding_model=current.embedding_model,
        chunk_size=current.chunk_size,
        chunk_overlap=current.chunk_overlap,
        seed_docs_fingerprint=current.seed_docs_fingerprint,
        last_ingested_at=datetime.now(UTC).isoformat(),
    )
