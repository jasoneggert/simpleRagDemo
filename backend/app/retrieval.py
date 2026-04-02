from __future__ import annotations

from app.config import settings
from app.embeddings import embed_texts
from app.models import SourceChunk
from app.vectorstore import get_chroma_collection


def retrieve_chunks(question: str, top_k: int | None = None) -> list[SourceChunk]:
    collection = get_chroma_collection()
    query_embedding = embed_texts([question])[0]
    limit = top_k or settings.retrieval_k
    result = collection.query(
        query_embeddings=[query_embedding],
        n_results=limit,
        include=["documents", "metadatas", "distances"],
    )

    documents = result.get("documents", [[]])[0]
    metadatas = result.get("metadatas", [[]])[0]
    distances = result.get("distances", [[]])[0]
    ids = result.get("ids", [[]])[0]

    chunks: list[SourceChunk] = []
    for chunk_id, document, metadata, distance in zip(ids, documents, metadatas, distances):
        chunks.append(
            SourceChunk(
                chunk_id=chunk_id,
                document_id=metadata["document_id"],
                source_path=metadata["source_path"],
                title=metadata["title"],
                heading=metadata.get("heading") or None,
                content=document,
                score=distance,
            )
        )
    return chunks
