from __future__ import annotations

from collections import Counter

from openai import OpenAI
from pydantic import BaseModel

from app.config import settings
from app.models import AnswerPayload, SourceChunk


class LlmCitation(BaseModel):
    chunk_id: str
    quote: str


class LlmAnswerPayload(BaseModel):
    answer: str
    summary: str
    citations: list[LlmCitation]
    confidence: str


SYSTEM_PROMPT = (
    "You answer questions about local markdown docs. "
    "Produce structured JSON matching the schema. "
    "Use only the supplied context. "
    "Set confidence to low, medium, or high."
)


def build_user_prompt(question: str, chunks: list[SourceChunk]) -> str:
    context_blocks: list[str] = []
    for chunk in chunks:
        heading = f" | heading={chunk.heading}" if chunk.heading else ""
        context_blocks.append(
            "\n".join(
                [
                    f"[chunk_id={chunk.chunk_id}] title={chunk.title}{heading}",
                    chunk.content,
                ]
            )
        )

    joined_context = "\n\n".join(context_blocks)
    return (
        "Use only the retrieved context to answer the question. "
        "If the context is insufficient, say so explicitly. "
        "Return citations only for chunks that directly support the answer.\n\n"
        f"Question:\n{question}\n\n"
        f"Retrieved context:\n{joined_context}"
    )


def _extract_quote(text: str, limit: int = 180) -> str:
    compact = " ".join(text.split())
    return compact[:limit].rstrip() + ("..." if len(compact) > limit else "")


def _demo_summary(question: str, chunks: list[SourceChunk]) -> AnswerPayload:
    top_chunk = chunks[0]
    supporting_titles = ", ".join(dict.fromkeys(chunk.title for chunk in chunks[:2]))
    token_counts = Counter(word.strip(".,:;!?()[]{}").lower() for word in question.split())
    keywords = [word for word, _ in token_counts.most_common(3) if word]
    keyword_text = ", ".join(keywords) if keywords else "the question"

    answer_text = (
        f"Based on the retrieved docs, the strongest match is '{top_chunk.title}'. "
        f"It indicates that {top_chunk.content.splitlines()[0].lstrip('#').strip().lower()}. "
        f"Additional support comes from {supporting_titles}."
    )
    summary_text = (
        f"Demo mode answered from retrieved chunks matched against {keyword_text}."
    )
    citations = [
        {
            "chunk_id": chunk.chunk_id,
            "source_path": chunk.source_path,
            "title": chunk.title,
            "quote": _extract_quote(chunk.content),
        }
        for chunk in chunks[: min(3, len(chunks))]
    ]
    confidence = "medium" if len(chunks) > 1 else "low"
    return AnswerPayload.model_validate(
        {
            "answer": answer_text,
            "summary": summary_text,
            "citations": citations,
            "confidence": confidence,
        }
    )


def generate_structured_answer(question: str, chunks: list[SourceChunk]) -> tuple[AnswerPayload, str, str]:
    user_prompt = build_user_prompt(question=question, chunks=chunks)
    if settings.demo_mode:
        return _demo_summary(question=question, chunks=chunks), SYSTEM_PROMPT, user_prompt

    client = OpenAI(api_key=settings.openai_api_key)
    response = client.responses.parse(
        model=settings.openai_chat_model,
        input=[
            {
                "role": "system",
                "content": SYSTEM_PROMPT,
            },
            {
                "role": "user",
                "content": user_prompt,
            },
        ],
        text_format=LlmAnswerPayload,
    )

    if getattr(response, "output_parsed", None) is None:
        raise ValueError("Model did not return a parsed structured response.")

    parsed: LlmAnswerPayload = response.output_parsed
    chunk_map = {chunk.chunk_id: chunk for chunk in chunks}
    citations = []
    for citation in parsed.citations:
        source_chunk = chunk_map.get(citation.chunk_id)
        if source_chunk is None:
            raise ValueError(f"Model returned unknown chunk_id: {citation.chunk_id}")
        citations.append(
            {
                "chunk_id": citation.chunk_id,
                "source_path": source_chunk.source_path,
                "title": source_chunk.title,
                "quote": citation.quote,
            }
        )

    answer = AnswerPayload.model_validate(
        {
            "answer": parsed.answer,
            "summary": parsed.summary,
            "citations": citations,
            "confidence": parsed.confidence,
        }
    )
    return answer, SYSTEM_PROMPT, user_prompt
