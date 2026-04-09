from __future__ import annotations

from collections import Counter

from openai import OpenAI
from pydantic import BaseModel, Field

from app.config import settings
from app.models import AnswerPayload, ModelUsage, SourceChunk, ToolTraceEntry


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

AGENT_SYSTEM_PROMPT = (
    "You are a SaaS billing resolution agent. "
    "Use the supplied policy context and structured tool evidence only. "
    "Do not invent customer or invoice facts. "
    "Every string field in the JSON must be non-empty and concrete. "
    "Set escalation_required to true whenever the policy or tool evidence indicates finance review, "
    "chargeback handling, fraud handling, tax reclassification, or another explicit escalation trigger. "
    "Return citations only from the policy chunks."
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


def build_agent_user_prompt(
    question: str,
    chunks: list[SourceChunk],
    tool_trace: list[ToolTraceEntry],
    case_context: str | None = None,
) -> str:
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

    trace_lines = [
        f"- {entry.tool_name}({entry.arguments}) -> {entry.status}: {entry.output_summary}"
        for entry in tool_trace
    ]
    joined_context = "\n\n".join(context_blocks) if context_blocks else "No policy chunks retrieved."
    joined_trace = "\n".join(trace_lines) if trace_lines else "No tool evidence was collected."
    case_context_block = f"Persisted case context:\n{case_context}\n\n" if case_context else ""
    return (
        "Answer the billing resolution request using only the retrieved policy chunks and the tool evidence below. "
        "If policy or tool evidence is insufficient, say so explicitly and use low confidence. "
        "Do not cite tools directly; citations must only reference policy chunks. "
        "Recommended_action must be one short operational step.\n\n"
        f"{case_context_block}"
        f"Question:\n{question}\n\n"
        f"Tool evidence:\n{joined_trace}\n\n"
        f"Retrieved policy context:\n{joined_context}"
    )


def _extract_quote(text: str, limit: int = 180) -> str:
    compact = " ".join(text.split())
    return compact[:limit].rstrip() + ("..." if len(compact) > limit else "")


def _normalize_text(value: str | None, fallback: str) -> str:
    cleaned = " ".join((value or "").split())
    return cleaned or fallback


def _demo_summary(question: str, chunks: list[SourceChunk]) -> AnswerPayload:
    if not chunks:
        return AnswerPayload.model_validate(
            {
                "answer": "The available policy evidence is insufficient to answer this billing case confidently.",
                "rationale": "No policy chunks were retrieved for the current question.",
                "recommended_action": "Gather more customer or policy context before responding.",
                "escalation_required": True,
                "citations": [],
                "confidence": "low",
            }
        )

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


def _demo_billing_resolution_summary(
    question: str,
    chunks: list[SourceChunk],
    tool_trace: list[ToolTraceEntry],
) -> AnswerPayload:
    if not chunks:
        return _demo_summary(question=question, chunks=chunks)

    lowered_question = question.lower()
    policy_types = {chunk.policy_type for chunk in chunks if chunk.policy_type}
    tool_text = " ".join(entry.output_summary.lower() for entry in tool_trace)
    citations = [
        {
            "chunk_id": chunk.chunk_id,
            "source_path": chunk.source_path,
            "title": chunk.title,
            "quote": _extract_quote(chunk.content),
        }
        for chunk in chunks[: min(3, len(chunks))]
    ]

    if (
        "chargeback" in lowered_question
        or "fraud" in lowered_question
        or ("vat" in lowered_question and "refund" in lowered_question and "finalized" in lowered_question)
        or "requires finance review" in tool_text
        or '"requires_manual_review": true' in tool_text
    ):
        return AnswerPayload.model_validate(
            {
                "answer": "This case should be escalated because the available policy or tool evidence requires finance or risk review before support acts.",
                "rationale": "The retrieved billing policy and local fixture evidence indicate this request falls into a documented escalation path.",
                "recommended_action": "Escalate to finance and avoid making a manual policy exception in the current support reply.",
                "escalation_required": True,
                "citations": citations,
                "confidence": "high" if "escalation_policy" in policy_types or "tax_policy" in policy_types else "medium",
            }
        )

    if "receipt" in lowered_question or "receipt_policy" in policy_types:
        return AnswerPayload.model_validate(
            {
                "answer": "Support can help the customer obtain the receipt through the documented receipt workflow.",
                "rationale": "The retrieved receipt policy allows support to guide the customer to the billing portal and resend the receipt when portal access is blocked.",
                "recommended_action": "Resend the receipt or direct the customer to the billing portal receipt flow.",
                "escalation_required": False,
                "citations": citations,
                "confidence": "high",
            }
        )

    if "duplicate charge" in lowered_question or "eligible" in tool_text or "duplicate charge" in tool_text:
        return AnswerPayload.model_validate(
            {
                "answer": "This looks like a valid refund candidate under the duplicate-charge workflow.",
                "rationale": "The duplicate-charge policy and tool evidence indicate support can review the later charge as a refund candidate when no intentional second purchase occurred.",
                "recommended_action": "Verify the second charge was not intentional and start the refund workflow for the duplicate payment.",
                "escalation_required": False,
                "citations": citations,
                "confidence": "high",
            }
        )

    return _demo_summary(question=question, chunks=chunks)


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


def generate_billing_resolution_answer(
    question: str,
    chunks: list[SourceChunk],
    tool_trace: list[ToolTraceEntry],
    case_context: str | None = None,
) -> tuple[AnswerPayload, str, str, ModelUsage | None]:
    user_prompt = build_agent_user_prompt(
        question=question,
        chunks=chunks,
        tool_trace=tool_trace,
        case_context=case_context,
    )
    if settings.demo_mode:
        answer = _demo_billing_resolution_summary(question=question, chunks=chunks or [], tool_trace=tool_trace)
        return answer, AGENT_SYSTEM_PROMPT, user_prompt, None

    client = OpenAI(api_key=settings.openai_api_key)
    response = client.responses.parse(
        model=settings.openai_chat_model,
        input=[
            {
                "role": "system",
                "content": AGENT_SYSTEM_PROMPT,
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
            continue
        citations.append(
            {
                "chunk_id": citation.chunk_id,
                "source_path": source_chunk.source_path,
                "title": source_chunk.title,
                "quote": citation.quote,
            }
        )

    top_title = chunks[0].title if chunks else "the retrieved policy"
    fallback_rationale = f"The retrieved policy in {top_title} and the collected tool evidence support this billing decision."
    fallback_action = "Use the retrieved policy and collected account facts to respond, and escalate only if the evidence requires it."
    answer = AnswerPayload.model_validate(
        {
            "answer": _normalize_text(parsed.answer, "The available policy and tool evidence are insufficient to answer this case confidently."),
            "rationale": _normalize_text(parsed.rationale, fallback_rationale),
            "recommended_action": _normalize_text(parsed.recommended_action, fallback_action),
            "escalation_required": parsed.escalation_required,
            "citations": citations,
            "confidence": parsed.confidence,
        }
    )
    usage = None
    if getattr(response, "usage", None) is not None:
        usage = ModelUsage(
            input_tokens=getattr(response.usage, "input_tokens", None),
            output_tokens=getattr(response.usage, "output_tokens", None),
            total_tokens=getattr(response.usage, "total_tokens", None),
        )
    return answer, AGENT_SYSTEM_PROMPT, user_prompt, usage
