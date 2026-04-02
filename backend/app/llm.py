from __future__ import annotations

from collections import Counter

from openai import OpenAI
from pydantic import BaseModel, Field

from app.config import settings
from app.models import AnswerPayload, SourceChunk


class LlmCitation(BaseModel):
    chunk_id: str
    quote: str


class LlmAnswerPayload(BaseModel):
    answer: str = Field(min_length=12)
    rationale: str = Field(min_length=12)
    recommended_action: str = Field(min_length=8)
    escalation_required: bool
    citations: list[LlmCitation]
    confidence: str


SYSTEM_PROMPT = (
    "You are a SaaS billing support copilot. "
    "Answer using only the supplied policy context. "
    "Write the answer as if it could be pasted into an internal support reply draft. "
    "Every string field in the JSON must be non-empty and concrete. "
    "Explain the policy briefly in rationale, recommend exactly one operational next action, "
    "and set escalation_required truthfully. "
    "Produce structured JSON matching the schema and set confidence to low, medium, or high."
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
        "Use only the retrieved context to answer the billing support question. "
        "If the context is insufficient, say so explicitly in the answer or rationale. "
        "Return citations only for chunks that directly support the answer. "
        "Keep the recommended action short and operational. "
        "Do not leave answer, rationale, or recommended_action blank.\n\n"
        "Example output style:\n"
        "{\n"
        '  "answer": "Because the second charge appears to be a duplicate within 24 hours, support can treat it as a potential duplicate charge and review it for a refund.",\n'
        '  "rationale": "The duplicate charge policy allows a full refund when two successful charges for the same invoice amount appear within 24 hours and the second purchase was not intentional.",\n'
        '  "recommended_action": "Verify the charges match and issue a refund for the duplicate payment if no second workspace was intentionally purchased.",\n'
        '  "escalation_required": false,\n'
        '  "citations": [{"chunk_id": "billing-handbook-chunk-2", "quote": "If two successful charges for the same invoice amount appear within 24 hours..."}],\n'
        '  "confidence": "high"\n'
        "}\n\n"
        f"Question:\n{question}\n\n"
        f"Retrieved context:\n{joined_context}"
    )


def _extract_quote(text: str, limit: int = 180) -> str:
    compact = " ".join(text.split())
    return compact[:limit].rstrip() + ("..." if len(compact) > limit else "")


def _normalize_text(value: str | None, fallback: str) -> str:
    cleaned = " ".join((value or "").split())
    return cleaned or fallback


def _demo_summary(question: str, chunks: list[SourceChunk]) -> AnswerPayload:
    top_chunk = chunks[0]
    supporting_titles = ", ".join(dict.fromkeys(chunk.title for chunk in chunks[:2]))
    token_counts = Counter(word.strip(".,:;!?()[]{}").lower() for word in question.split())
    keywords = [word for word, _ in token_counts.most_common(3) if word]
    keyword_text = ", ".join(keywords) if keywords else "the question"

    answer_text = (
        f"The strongest policy match is '{top_chunk.title}'. "
        f"Based on that context, the case should follow the documented billing rule in that section."
    )
    rationale_text = (
        f"Demo mode grounded the response in {supporting_titles} using the keywords {keyword_text}."
    )
    recommended_action = "Review the cited policy section and respond to the customer using that rule."
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
            "rationale": rationale_text,
            "recommended_action": recommended_action,
            "escalation_required": False,
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

    top_title = chunks[0].title if chunks else "the retrieved policy"
    fallback_rationale = f"The retrieved policy in {top_title} supports this support decision."
    fallback_action = "Reply using the cited policy and escalate only if the case falls outside the documented rules."

    answer = AnswerPayload.model_validate(
        {
            "answer": _normalize_text(parsed.answer, "The retrieved policy does not provide enough detail to answer this case confidently."),
            "rationale": _normalize_text(parsed.rationale, fallback_rationale),
            "recommended_action": _normalize_text(parsed.recommended_action, fallback_action),
            "escalation_required": parsed.escalation_required,
            "citations": citations,
            "confidence": parsed.confidence,
        }
    )
    return answer, SYSTEM_PROMPT, user_prompt
