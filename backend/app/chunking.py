from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
import re

import tiktoken

from app.config import settings

SENTENCE_BOUNDARY_PATTERN = re.compile(r"(?<=[.!?])\s+")


@dataclass(slots=True)
class ChunkRecord:
    chunk_id: str
    document_id: str
    source_path: str
    title: str
    heading: str | None
    content: str
    topic: str
    policy_type: str
    escalation_class: str
    region: str
    effective_date: str | None


def _normalize_whitespace(text: str) -> str:
    return "\n".join(line.rstrip() for line in text.strip().splitlines()).strip()


def _extract_effective_date(text: str) -> str | None:
    match = re.search(
        r"(effective(?:\s+date)?|effective\s+on)[:\s]+([A-Za-z]+\s+\d{1,2},\s+\d{4}|\d{4}-\d{2}-\d{2})",
        text,
        flags=re.IGNORECASE,
    )
    if not match:
        return None
    return match.group(2).strip()


def _infer_topic(file_stem: str, heading: str | None, content: str) -> str:
    haystack = f"{file_stem} {heading or ''} {content}".lower()
    if any(term in haystack for term in ("vat", "gst", "tax", "reverse-charge")):
        return "tax"
    if any(term in haystack for term in ("invoice", "receipt", "billing contact")):
        return "invoices"
    if "escalat" in haystack or "finance approval" in haystack:
        return "escalation"
    if any(term in haystack for term in ("duplicate charge", "refund", "credit", "proration")):
        return "refunds"
    if any(term in haystack for term in ("soft decline", "hard decline", "retry", "card", "payment")):
        return "payments"
    return "billing"


def _infer_policy_type(topic: str, heading: str | None, content: str) -> str:
    haystack = f"{heading or ''} {content}".lower()
    if "vat" in haystack or "gst" in haystack or "tax" in haystack:
        return "tax_policy"
    if "receipt" in haystack:
        return "receipt_policy"
    if "invoice" in haystack and "refund" not in haystack:
        return "invoice_policy"
    if "duplicate" in haystack:
        return "duplicate_charge_policy"
    if "refund" in haystack:
        return "refund_policy"
    if "decline" in haystack or "retry" in haystack:
        return "payment_failure_policy"
    if "escalat" in haystack:
        return "escalation_policy"
    return f"{topic}_policy"


def _infer_escalation_class(heading: str | None, content: str) -> str:
    haystack = f"{heading or ''} {content}".lower()
    if any(term in haystack for term in ("escalation is required", "must escalate", "required for", "fraud", "chargeback")):
        return "required"
    if any(term in haystack for term in ("finance approval", "finance operations", "escalate")):
        return "conditional"
    return "standard"


def _infer_region(content: str) -> str:
    haystack = content.lower()
    if any(term in haystack for term in ("vat", "gst", "reverse-charge")):
        return "tax-region-specific"
    return "global"


@lru_cache(maxsize=4)
def _get_encoding(model_name: str) -> tiktoken.Encoding | None:
    try:
        return tiktoken.encoding_for_model(model_name)
    except Exception:
        try:
            return tiktoken.get_encoding("cl100k_base")
        except Exception:
            return None


def _token_count(text: str) -> int:
    encoding = _get_encoding(settings.openai_embedding_model)
    if encoding is not None:
        return len(encoding.encode(text))
    # Fallback when local token encodings are unavailable: rough 4-char/token estimate.
    return max(1, len(text) // 4)


def _split_paragraphs(text: str) -> list[str]:
    return [paragraph.strip() for paragraph in re.split(r"\n\s*\n", text) if paragraph.strip()]


def _split_large_paragraph(paragraph: str, chunk_size: int) -> list[str]:
    if _token_count(paragraph) <= chunk_size:
        return [paragraph]

    sentences = [sentence.strip() for sentence in SENTENCE_BOUNDARY_PATTERN.split(paragraph) if sentence.strip()]
    if len(sentences) <= 1:
        words = paragraph.split()
        pieces: list[str] = []
        current_words: list[str] = []
        for word in words:
            candidate = " ".join([*current_words, word]).strip()
            if current_words and _token_count(candidate) > chunk_size:
                pieces.append(" ".join(current_words))
                current_words = [word]
            else:
                current_words.append(word)
        if current_words:
            pieces.append(" ".join(current_words))
        return pieces

    pieces = []
    current_sentences: list[str] = []
    for sentence in sentences:
        candidate = "\n".join([*current_sentences, sentence]).strip()
        if current_sentences and _token_count(candidate) > chunk_size:
            pieces.append("\n".join(current_sentences))
            current_sentences = [sentence]
        else:
            current_sentences.append(sentence)
    if current_sentences:
        pieces.append("\n".join(current_sentences))
    return pieces


def _build_chunks_for_section(section_heading: str | None, section_body: str, chunk_size: int, chunk_overlap: int) -> list[str]:
    body_paragraphs = _split_paragraphs(section_body)
    paragraphs: list[str] = []
    for paragraph in body_paragraphs:
        paragraphs.extend(_split_large_paragraph(paragraph, chunk_size))

    if not paragraphs:
        return []

    chunks: list[str] = []
    current_parts: list[str] = []
    for paragraph in paragraphs:
        candidate_parts = [*current_parts, paragraph]
        candidate_body = "\n\n".join(candidate_parts).strip()
        candidate_text = f"## {section_heading}\n\n{candidate_body}".strip() if section_heading else candidate_body
        if current_parts and _token_count(candidate_text) > chunk_size:
            current_body = "\n\n".join(current_parts).strip()
            if current_body:
                chunks.append(f"## {section_heading}\n\n{current_body}".strip() if section_heading else current_body)

            overlap_parts: list[str] = []
            if chunk_overlap > 0:
                running_overlap = 0
                for previous_paragraph in reversed(current_parts):
                    overlap_parts.insert(0, previous_paragraph)
                    running_overlap += _token_count(previous_paragraph)
                    if running_overlap >= chunk_overlap:
                        break
            current_parts = [*overlap_parts, paragraph]
        else:
            current_parts = candidate_parts

    if current_parts:
        current_body = "\n\n".join(current_parts).strip()
        if current_body:
            chunks.append(f"## {section_heading}\n\n{current_body}".strip() if section_heading else current_body)

    deduped_chunks: list[str] = []
    for chunk in chunks:
        if not deduped_chunks or deduped_chunks[-1] != chunk:
            deduped_chunks.append(chunk)

    return deduped_chunks


def chunk_markdown_file(file_path: Path, chunk_size: int, chunk_overlap: int) -> list[ChunkRecord]:
    raw_text = file_path.read_text(encoding="utf-8")
    normalized_text = _normalize_whitespace(raw_text)
    lines = normalized_text.splitlines()

    title = file_path.stem.replace("-", " ").title()
    heading: str | None = None
    sections: list[tuple[str | None, str]] = []
    current_body: list[str] = []

    for line in lines:
        if line.startswith("#"):
            if heading is not None or current_body:
                sections.append((heading, "\n".join(current_body).strip()))
                current_body = []
            heading = line.lstrip("#").strip() or None
            continue
        current_body.append(line)

    if heading is not None or current_body:
        sections.append((heading, "\n".join(current_body).strip()))

    chunks: list[ChunkRecord] = []
    chunk_index = 0
    for section_heading, section_body in sections:
        for content in _build_chunks_for_section(
            section_heading=section_heading,
            section_body=section_body,
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
        ):
            chunks.append(
                ChunkRecord(
                    chunk_id=f"{file_path.stem}-chunk-{chunk_index}",
                    document_id=file_path.stem,
                    source_path=str(file_path),
                    title=title,
                    heading=section_heading,
                    content=content,
                    topic=_infer_topic(file_path.stem, section_heading, content),
                    policy_type=_infer_policy_type(
                        _infer_topic(file_path.stem, section_heading, content),
                        section_heading,
                        content,
                    ),
                    escalation_class=_infer_escalation_class(section_heading, content),
                    region=_infer_region(content),
                    effective_date=_extract_effective_date(content),
                )
            )
            chunk_index += 1

    return chunks
