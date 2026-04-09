from __future__ import annotations

import math
import re
from collections import Counter
from typing import Any

from app.config import settings
from app.embeddings import embed_texts
from app.models import SourceChunk
from app.vectorstore import get_chroma_collection


TOKEN_PATTERN = re.compile(r"[a-z0-9]+")
STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "be",
    "can",
    "do",
    "for",
    "how",
    "i",
    "if",
    "in",
    "is",
    "it",
    "my",
    "of",
    "on",
    "or",
    "policy",
    "applies",
    "same",
    "should",
    "support",
    "the",
    "with",
    "yesterday",
    "to",
    "what",
    "when",
    "why",
}
TOPIC_KEYWORDS = {
    "refunds": {"refund", "refundable", "refunds", "duplicate", "credit", "proration", "downgrade", "upgrade", "twice"},
    "payments": {"payment", "payments", "decline", "declines", "card", "retry", "renewal", "failed", "soft", "hard"},
    "tax": {"tax", "vat", "gst", "reverse-charge"},
    "invoices": {"invoice", "receipt", "receipts", "billing", "portal"},
    "escalation": {"escalate", "escalation", "chargeback", "fraud", "finance"},
}
POLICY_KEYWORDS = {
    "duplicate_charge_policy": {"duplicate", "charged", "twice", "invoice"},
    "payment_failure_policy": {"soft", "hard", "decline", "retry", "renewal", "failed"},
    "refund_policy": {"refund", "refundable", "credit", "proration"},
    "tax_policy": {"tax", "vat", "gst", "finalized"},
    "invoice_policy": {"invoice", "receipt", "billing"},
}


def _tokenize(text: str) -> list[str]:
    return [token for token in TOKEN_PATTERN.findall(text.lower()) if token not in STOPWORDS]


def _normalize_dense_score(distance: float | None) -> float:
    if distance is None:
        return 0.0
    return 1.0 / (1.0 + max(distance, 0.0))


def _metadata_bonus(query_tokens: set[str], metadata: dict[str, Any]) -> tuple[float, list[str]]:
    bonus = 0.0
    notes: list[str] = []
    topic = str(metadata.get("topic") or "")
    policy_type = str(metadata.get("policy_type") or "")
    escalation_class = str(metadata.get("escalation_class") or "")
    region = str(metadata.get("region") or "")

    if topic:
        topic_keywords = TOPIC_KEYWORDS.get(topic, set())
        if query_tokens & topic_keywords:
            bonus += 0.18
            notes.append(f"topic matched {topic}")
    if policy_type and query_tokens & POLICY_KEYWORDS.get(policy_type, set()):
        bonus += 0.14
        notes.append(f"policy type matched {policy_type}")
    if escalation_class != "standard" and {"escalate", "escalation", "fraud", "chargeback", "finance"} & query_tokens:
        bonus += 0.12
        notes.append(f"escalation class matched {escalation_class}")
    if region != "global" and {"vat", "gst", "tax"} & query_tokens:
        bonus += 0.08
        notes.append(f"region matched {region}")
    return bonus, notes


def _lexical_score(question: str, metadata: dict[str, Any], document: str) -> tuple[float, list[str]]:
    query_tokens = _tokenize(question)
    query_set = set(query_tokens)
    if not query_set:
        return 0.0, []

    text_tokens = _tokenize(
        " ".join(
            [
                document,
                str(metadata.get("title") or ""),
                str(metadata.get("heading") or ""),
                str(metadata.get("topic") or ""),
                str(metadata.get("policy_type") or ""),
                str(metadata.get("escalation_class") or ""),
            ]
        )
    )
    if not text_tokens:
        return 0.0, []

    text_counter = Counter(text_tokens)
    overlap = query_set & set(text_tokens)
    base_score = sum(min(text_counter[token], 2) for token in overlap) / max(len(query_set), 1)
    bonus, notes = _metadata_bonus(query_set, metadata)
    phrase_bonus = 0.0
    lowered_question = question.lower()
    lowered_document = document.lower()
    if ("charged twice" in lowered_question or "duplicate" in lowered_question) and (
        "duplicate charge" in lowered_document or "same invoice amount" in lowered_document
    ):
        phrase_bonus += 0.35
        notes.append("phrase matched duplicate-charge policy")
    if "soft decline" in lowered_question and "soft decline" in lowered_document:
        phrase_bonus += 0.35
        notes.append("phrase matched soft-decline policy")
    if any(term in lowered_question for term in ("vat", "gst")) and any(term in lowered_document for term in ("vat", "gst")):
        phrase_bonus += 0.25
        notes.append("phrase matched tax policy")

    lexical = min(base_score + bonus + phrase_bonus, 1.75)
    if overlap:
        notes.insert(0, "keyword overlap: " + ", ".join(sorted(overlap)[:6]))
    return lexical, notes


def _all_collection_rows() -> list[tuple[str, str, dict[str, Any]]]:
    collection = get_chroma_collection()
    result = collection.get(include=["documents", "metadatas"])
    ids = result.get("ids", [])
    documents = result.get("documents", [])
    metadatas = result.get("metadatas", [])
    rows: list[tuple[str, str, dict[str, Any]]] = []
    for chunk_id, document, metadata in zip(ids, documents, metadatas):
        rows.append((chunk_id, document, metadata or {}))
    return rows


def retrieve_chunks(question: str, top_k: int | None = None) -> tuple[list[SourceChunk], str, str]:
    collection = get_chroma_collection()
    query_embedding = embed_texts([question])[0]
    limit = top_k or settings.retrieval_k
    dense_limit = max(limit * 4, limit)

    try:
        dense_result = collection.query(
            query_embeddings=[query_embedding],
            n_results=dense_limit,
            include=["documents", "metadatas", "distances"],
        )
    except Exception as exc:
        mode = "demo mode" if settings.demo_mode else settings.openai_embedding_model
        raise ValueError(
            "Vector store query failed. The existing Chroma collection is likely incompatible "
            f"with the current embedding configuration ({mode}). Re-run POST /ingest after "
            "changing DEMO_MODE, OPENAI_API_KEY, or OPENAI_EMBEDDING_MODEL."
        ) from exc

    dense_documents = dense_result.get("documents", [[]])[0]
    dense_metadatas = dense_result.get("metadatas", [[]])[0]
    dense_distances = dense_result.get("distances", [[]])[0]
    dense_ids = dense_result.get("ids", [[]])[0]

    candidate_map: dict[str, dict[str, Any]] = {}
    for chunk_id, document, metadata, distance in zip(dense_ids, dense_documents, dense_metadatas, dense_distances):
        dense_score = _normalize_dense_score(distance)
        candidate_map[chunk_id] = {
            "chunk_id": chunk_id,
            "document": document,
            "metadata": metadata or {},
            "dense_score": dense_score,
            "lexical_score": 0.0,
            "metadata_score": 0.0,
            "distance": distance,
            "notes": [f"dense retrieval score {dense_score:.3f}"],
        }

    lexical_rows = _all_collection_rows()
    max_lexical_score = 0.0
    for chunk_id, document, metadata in lexical_rows:
        lexical_score, notes = _lexical_score(question, metadata, document)
        max_lexical_score = max(max_lexical_score, lexical_score)
        candidate = candidate_map.setdefault(
            chunk_id,
            {
                "chunk_id": chunk_id,
                "document": document,
                "metadata": metadata or {},
                "dense_score": 0.0,
                "lexical_score": 0.0,
                "metadata_score": 0.0,
                "distance": None,
                "notes": [],
            },
        )
        candidate["document"] = document
        candidate["metadata"] = metadata or {}
        candidate["lexical_score"] = lexical_score
        candidate["notes"].extend(notes)

    for candidate in candidate_map.values():
        metadata_notes = [note for note in candidate["notes"] if note.startswith(("topic matched", "policy type matched", "escalation class matched", "region matched"))]
        candidate["metadata_score"] = min(0.25, 0.08 * len(metadata_notes))
        normalized_lexical = candidate["lexical_score"] / max(max_lexical_score, 1.0)
        combined_score = (0.62 * candidate["dense_score"]) + (0.28 * normalized_lexical) + (0.10 * candidate["metadata_score"])
        if metadata_notes and candidate["dense_score"] < 0.25:
            combined_score += 0.03
        candidate["combined_score"] = combined_score

    sorted_candidates = sorted(
        candidate_map.values(),
        key=lambda item: (
            item["combined_score"],
            item["lexical_score"],
            item["dense_score"],
            -len(item["document"]),
        ),
        reverse=True,
    )

    selected = sorted_candidates[:limit]
    chunks: list[SourceChunk] = []
    for candidate in selected:
        metadata = candidate["metadata"]
        chunks.append(
            SourceChunk(
                chunk_id=candidate["chunk_id"],
                document_id=str(metadata["document_id"]),
                source_path=str(metadata["source_path"]),
                title=str(metadata["title"]),
                heading=str(metadata.get("heading") or "") or None,
                topic=str(metadata.get("topic") or "") or None,
                policy_type=str(metadata.get("policy_type") or "") or None,
                escalation_class=str(metadata.get("escalation_class") or "") or None,
                region=str(metadata.get("region") or "") or None,
                effective_date=str(metadata.get("effective_date") or "") or None,
                content=candidate["document"],
                score=round(candidate["combined_score"], 4),
                dense_score=round(candidate["dense_score"], 4),
                lexical_score=round(candidate["lexical_score"], 4),
                metadata_score=round(candidate["metadata_score"], 4),
                retrieval_notes=list(dict.fromkeys(candidate["notes"]))[:5],
            )
        )

    retrieval_strategy = "hybrid dense + lexical + metadata reranking"
    retrieval_reason = (
        "Selected chunks are ranked by vector similarity, keyword overlap with the billing question, "
        "and metadata matches such as topic, policy type, escalation class, and tax region."
    )
    return chunks, retrieval_strategy, retrieval_reason
