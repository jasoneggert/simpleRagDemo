from __future__ import annotations

import json
import re
from dataclasses import dataclass
from time import perf_counter
from typing import Any, Callable

from openai import APIConnectionError, APIError
from openai import AsyncOpenAI
from openai.lib._pydantic import to_strict_json_schema
from pydantic import BaseModel, Field

from app.config import settings
from app.llm import generate_billing_resolution_answer
from app.models import ActionProposal, AnswerPayload, ModelUsage, SourceChunk, ToolTraceEntry
from app.retrieval import retrieve_chunks
from app.support_tools import (
    check_refund_eligibility,
    get_customer_account,
    get_invoice,
    get_payment_attempts,
)


MAX_AGENT_TOOL_CALLS = 2


class AgentExecutionError(RuntimeError):
    pass


class SearchPolicyArgs(BaseModel):
    question: str = Field(min_length=3)
    top_k: int = Field(default=4, ge=1, le=6)


class GetCustomerAccountArgs(BaseModel):
    workspace_id: str | None = None
    customer_id: str


class GetInvoiceArgs(BaseModel):
    workspace_id: str | None = None
    invoice_id: str


class GetPaymentAttemptsArgs(BaseModel):
    workspace_id: str | None = None
    customer_id: str
    invoice_id: str | None = None


class CheckRefundEligibilityArgs(BaseModel):
    workspace_id: str | None = None
    invoice_id: str
    customer_id: str


@dataclass
class AgentRunResult:
    answer: AnswerPayload
    system_prompt: str
    user_prompt: str
    retrieved_chunks: list[SourceChunk]
    retrieval_strategy: str
    retrieval_reason: str
    tool_trace: list[ToolTraceEntry]
    action_proposal: ActionProposal | None
    model_name: str
    model_usage: ModelUsage | None
    execution_ms: int
    cache_hit_count: int


def _tool_schema(model: type[BaseModel], name: str, description: str) -> dict[str, Any]:
    schema = to_strict_json_schema(model)
    return {
        "type": "function",
        "name": name,
        "description": description,
        "parameters": schema,
        "strict": True,
    }


def _summarize_tool_output(tool_name: str, result: Any) -> str:
    if tool_name == "search_policy":
        chunks = result["chunks"]
        headings = [
            (chunk.get("heading") or chunk.get("title")) if isinstance(chunk, dict) else (chunk.heading or chunk.title)
            for chunk in chunks[:2]
        ]
        return f"Retrieved {len(chunks)} policy chunks; top headings: {', '.join(headings) if headings else 'none'}."
    payload = _serialize_tool_result(result)
    compact = json.dumps(payload, sort_keys=True)
    return compact[:280] + ("..." if len(compact) > 280 else "")


def _serialize_tool_result(result: Any) -> Any:
    if isinstance(result, BaseModel):
        return result.model_dump()
    if isinstance(result, list):
        return [_serialize_tool_result(item) for item in result]
    if isinstance(result, tuple):
        return [_serialize_tool_result(item) for item in result]
    if isinstance(result, dict):
        return {key: _serialize_tool_result(value) for key, value in result.items()}
    return result


def _build_action_proposal(
    *,
    question: str,
    workspace_id: str | None,
    customer_id: str | None,
    invoice_id: str | None,
    answer: AnswerPayload,
    retrieved_chunks: list[SourceChunk],
    tool_trace: list[ToolTraceEntry],
) -> ActionProposal | None:
    lowered_question = question.lower()
    combined_text = f"{answer.answer} {answer.recommended_action} {answer.rationale}".lower()

    if answer.escalation_required:
        return ActionProposal(
            action_type="escalate_to_finance",
            title="Finance escalation suggested",
            reason="The agent marked this case as requiring escalation based on policy or tool evidence.",
            status="pending_approval",
            payload={
                "workspace_id": workspace_id,
                "customer_id": customer_id,
                "invoice_id": invoice_id,
                "reason": answer.recommended_action,
            },
        )

    if "receipt" in lowered_question or any(chunk.policy_type == "receipt_policy" for chunk in retrieved_chunks):
        if customer_id and invoice_id:
            return ActionProposal(
                action_type="send_receipt_email",
                title="Receipt resend suggested",
                reason="The retrieved policy indicates support can resend a receipt when the customer cannot access the billing portal.",
                status="pending_approval",
                payload={"workspace_id": workspace_id, "customer_id": customer_id, "invoice_id": invoice_id},
            )
        return None

    refund_signal = "refund" in combined_text or any(
        "duplicate charge" in entry.output_summary.lower() or "eligible" in entry.output_summary.lower()
        for entry in tool_trace
    )
    if refund_signal and customer_id and invoice_id:
        return ActionProposal(
            action_type="issue_refund_request",
            title="Refund request suggested",
            reason="The retrieved policy and tool evidence indicate this case is a candidate for a refund workflow.",
            status="pending_approval",
            payload={
                "workspace_id": workspace_id,
                "customer_id": customer_id,
                "invoice_id": invoice_id,
                "reason": answer.recommended_action,
            },
        )

    return None


def _infer_identifiers(question: str, customer_id: str | None, invoice_id: str | None) -> tuple[str | None, str | None]:
    inferred_customer = customer_id
    inferred_invoice = invoice_id
    if inferred_customer is None:
        match = re.search(r"\b(cust_[a-z0-9_]+)\b", question)
        if match:
            inferred_customer = match.group(1)
    if inferred_invoice is None:
        match = re.search(r"\b(inv_[a-z0-9_]+)\b", question)
        if match:
            inferred_invoice = match.group(1)
    return inferred_customer, inferred_invoice


def _run_demo_agent(
    question: str,
    top_k: int,
    workspace_id: str | None,
    customer_id: str | None,
    invoice_id: str | None,
    case_context: str | None = None,
) -> AgentRunResult:
    trace: list[ToolTraceEntry] = []
    retrieval_query = question if not case_context else f"{question}\n{case_context}"
    chunks, retrieval_strategy, retrieval_reason = retrieve_chunks(retrieval_query, top_k=top_k)
    trace.append(
        ToolTraceEntry(
            tool_name="search_policy",
            arguments={"question": retrieval_query, "top_k": top_k},
            status="ok",
            output_summary=_summarize_tool_output("search_policy", {"chunks": chunks}),
        )
    )

    if customer_id:
        try:
            account = get_customer_account(customer_id, workspace_id=workspace_id)
            trace.append(
                ToolTraceEntry(
                    tool_name="get_customer_account",
                    arguments={"workspace_id": workspace_id, "customer_id": customer_id},
                    status="ok",
                    output_summary=_summarize_tool_output("get_customer_account", account),
                )
            )
        except ValueError as exc:
            trace.append(
                ToolTraceEntry(
                    tool_name="get_customer_account",
                    arguments={"workspace_id": workspace_id, "customer_id": customer_id},
                    status="error",
                    output_summary=str(exc),
                )
            )
    if customer_id and invoice_id:
        try:
            eligibility = check_refund_eligibility(
                invoice_id=invoice_id,
                customer_id=customer_id,
                workspace_id=workspace_id,
            )
            trace.append(
                ToolTraceEntry(
                    tool_name="check_refund_eligibility",
                    arguments={"workspace_id": workspace_id, "customer_id": customer_id, "invoice_id": invoice_id},
                    status="ok",
                    output_summary=_summarize_tool_output("check_refund_eligibility", eligibility),
                )
            )
        except ValueError as exc:
            trace.append(
                ToolTraceEntry(
                    tool_name="check_refund_eligibility",
                    arguments={"workspace_id": workspace_id, "customer_id": customer_id, "invoice_id": invoice_id},
                    status="error",
                    output_summary=str(exc),
                )
            )

    answer, system_prompt, user_prompt, synthesis_usage = generate_billing_resolution_answer(
        question=question,
        chunks=chunks,
        tool_trace=trace,
        case_context=case_context,
    )
    return AgentRunResult(
        answer=answer,
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        retrieved_chunks=chunks,
        retrieval_strategy=retrieval_strategy,
        retrieval_reason=retrieval_reason,
        tool_trace=trace,
        action_proposal=_build_action_proposal(
            question=question,
            workspace_id=workspace_id,
            customer_id=customer_id,
            invoice_id=invoice_id,
            answer=answer,
            retrieved_chunks=chunks,
            tool_trace=trace,
        ),
        model_name="demo-agent",
        model_usage=synthesis_usage,
        execution_ms=0,
        cache_hit_count=0,
    )


async def run_billing_resolution_agent(
    question: str,
    top_k: int,
    workspace_id: str | None = None,
    customer_id: str | None = None,
    invoice_id: str | None = None,
    case_context: str | None = None,
) -> AgentRunResult:
    started_at = perf_counter()
    customer_id, invoice_id = _infer_identifiers(question, customer_id, invoice_id)

    if settings.demo_mode:
        return _run_demo_agent(
            question=question,
            top_k=top_k,
            workspace_id=workspace_id,
            customer_id=customer_id,
            invoice_id=invoice_id,
            case_context=case_context,
        )

    tools = [
        _tool_schema(SearchPolicyArgs, "search_policy", "Retrieve relevant billing policy chunks for a support question."),
        _tool_schema(GetCustomerAccountArgs, "get_customer_account", "Fetch the local fixture account record for a customer."),
        _tool_schema(GetInvoiceArgs, "get_invoice", "Fetch the local fixture invoice record."),
        _tool_schema(GetPaymentAttemptsArgs, "get_payment_attempts", "Fetch payment attempts for a customer, optionally filtered by invoice."),
        _tool_schema(CheckRefundEligibilityArgs, "check_refund_eligibility", "Evaluate local refund eligibility rules for a customer and invoice."),
    ]

    tool_impls: dict[str, Callable[..., Any]] = {
        "get_customer_account": get_customer_account,
        "get_invoice": get_invoice,
        "get_payment_attempts": get_payment_attempts,
        "check_refund_eligibility": check_refund_eligibility,
    }

    trace: list[ToolTraceEntry] = []
    retrieved_chunks: list[SourceChunk] = []
    cache_hit_count = 0
    retrieval_strategy = "agent tool selection"
    retrieval_reason = "The agent selected tools to gather policy and local fixture evidence before synthesizing an answer."

    prompt = (
        "Resolve the billing support request by calling tools when needed. "
        "Always call search_policy first. "
        "Only call account tools if the question or provided identifiers supply enough information. "
        "Do not call the same tool twice with the same arguments unless the earlier call returned an error. "
        "Never invent identifiers. "
        "Stop once you have enough evidence to answer.\n\n"
        f"Question: {question}\n"
        f"Known workspace_id: {workspace_id or 'none'}\n"
        f"Known customer_id: {customer_id or 'none'}\n"
        f"Known invoice_id: {invoice_id or 'none'}\n"
        f"Persisted case context: {case_context or 'none'}"
    )

    async with AsyncOpenAI(api_key=settings.openai_api_key) as client:
        planning_usage = ModelUsage(input_tokens=0, output_tokens=0, total_tokens=0)

        def add_usage(response_obj: Any) -> None:
            if getattr(response_obj, "usage", None) is None:
                return
            usage = response_obj.usage
            planning_usage.input_tokens = (planning_usage.input_tokens or 0) + int(getattr(usage, "input_tokens", 0) or 0)
            planning_usage.output_tokens = (planning_usage.output_tokens or 0) + int(getattr(usage, "output_tokens", 0) or 0)
            planning_usage.total_tokens = (planning_usage.total_tokens or 0) + int(getattr(usage, "total_tokens", 0) or 0)

        try:
            response = await client.responses.create(
                model=settings.openai_chat_model,
                input=prompt,
                tools=tools,
                tool_choice="auto",
                max_tool_calls=MAX_AGENT_TOOL_CALLS,
                parallel_tool_calls=False,
                temperature=0,
            )
        except APIConnectionError as exc:
            raise AgentExecutionError(
                "The billing-resolution agent could not reach OpenAI while planning tool calls. "
                "Check network connectivity from the backend process and try again."
            ) from exc
        except APIError as exc:
            raise AgentExecutionError(
                f"The billing-resolution agent failed during tool planning: {exc}"
            ) from exc
        add_usage(response)
        calls_made = 0
        tool_result_cache: dict[tuple[str, str], Any] = {}
        while calls_made < MAX_AGENT_TOOL_CALLS:
            tool_calls = [output for output in response.output if output.type == "function_call"]
            if not tool_calls:
                break

            outputs = []
            for call in tool_calls:
                calls_made += 1
                name = call.name
                arguments = json.loads(call.arguments)
                cache_key = (name, json.dumps(arguments, sort_keys=True))
                if cache_key in tool_result_cache:
                    cache_hit_count += 1
                    cached_result = tool_result_cache[cache_key]
                    trace.append(
                        ToolTraceEntry(
                            tool_name=name,
                            arguments={key: value for key, value in arguments.items()},
                            status="ok",
                            output_summary=f"Cache hit. {_summarize_tool_output(name, cached_result)}",
                        )
                    )
                    outputs.append(
                        {
                            "type": "function_call_output",
                            "call_id": call.call_id,
                            "output": json.dumps(_serialize_tool_result(cached_result)),
                        }
                    )
                    continue
                try:
                    if name == "search_policy":
                        chunks, retrieval_strategy, retrieval_reason = retrieve_chunks(
                            arguments["question"],
                            top_k=arguments.get("top_k"),
                        )
                        retrieved_chunks = chunks
                        result: Any = {
                            "retrieval_strategy": retrieval_strategy,
                            "retrieval_reason": retrieval_reason,
                            "chunks": [
                                {
                                    "chunk_id": chunk.chunk_id,
                                    "title": chunk.title,
                                    "heading": chunk.heading,
                                    "topic": chunk.topic,
                                    "policy_type": chunk.policy_type,
                                }
                                for chunk in chunks
                            ],
                        }
                    else:
                        impl = tool_impls[name]
                        result = impl(**arguments)
                    trace.append(
                        ToolTraceEntry(
                            tool_name=name,
                            arguments={key: value for key, value in arguments.items()},
                            status="ok",
                            output_summary=_summarize_tool_output(name, result),
                        )
                    )
                    tool_result_cache[cache_key] = result
                    serialized = _serialize_tool_result(result)
                except Exception as exc:
                    trace.append(
                        ToolTraceEntry(
                            tool_name=name,
                            arguments={key: value for key, value in arguments.items()},
                            status="error",
                            output_summary=str(exc),
                        )
                    )
                    serialized = {"error": str(exc)}

                outputs.append(
                    {
                        "type": "function_call_output",
                        "call_id": call.call_id,
                        "output": json.dumps(serialized),
                    }
                )

            if calls_made >= MAX_AGENT_TOOL_CALLS:
                break

            try:
                response = await client.responses.create(
                    model=settings.openai_chat_model,
                    previous_response_id=response.id,
                    input=outputs,
                    tools=tools,
                    tool_choice="auto",
                    max_tool_calls=max(1, MAX_AGENT_TOOL_CALLS - calls_made),
                    parallel_tool_calls=False,
                    temperature=0,
                )
            except APIConnectionError as exc:
                raise AgentExecutionError(
                    "The billing-resolution agent lost connectivity to OpenAI while continuing tool calls. "
                    "Check network connectivity from the backend process and try again."
                ) from exc
            except APIError as exc:
                raise AgentExecutionError(
                    f"The billing-resolution agent failed while continuing tool calls: {exc}"
                ) from exc
            add_usage(response)

    if not retrieved_chunks:
        retrieved_chunks, retrieval_strategy, retrieval_reason = retrieve_chunks(question, top_k=top_k)
        trace.insert(
            0,
            ToolTraceEntry(
                tool_name="search_policy",
                arguments={"question": question, "top_k": top_k},
                status="ok",
                output_summary=_summarize_tool_output("search_policy", {"chunks": retrieved_chunks}),
            )
        )

    answer, system_prompt, user_prompt, synthesis_usage = generate_billing_resolution_answer(
        question=question,
        chunks=retrieved_chunks,
        tool_trace=trace,
        case_context=case_context,
    )
    combined_usage = planning_usage
    if synthesis_usage is not None:
        combined_usage = ModelUsage(
            input_tokens=(planning_usage.input_tokens or 0) + (synthesis_usage.input_tokens or 0),
            output_tokens=(planning_usage.output_tokens or 0) + (synthesis_usage.output_tokens or 0),
            total_tokens=(planning_usage.total_tokens or 0) + (synthesis_usage.total_tokens or 0),
        )
    elif (planning_usage.total_tokens or 0) == 0:
        combined_usage = None
    return AgentRunResult(
        answer=answer,
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        retrieved_chunks=retrieved_chunks,
        retrieval_strategy=retrieval_strategy,
        retrieval_reason=retrieval_reason,
        tool_trace=trace,
        action_proposal=_build_action_proposal(
            question=question,
            workspace_id=workspace_id,
            customer_id=customer_id,
            invoice_id=invoice_id,
            answer=answer,
            retrieved_chunks=retrieved_chunks,
            tool_trace=trace,
        ),
        model_name=settings.openai_chat_model,
        model_usage=combined_usage,
        execution_ms=int((perf_counter() - started_at) * 1000),
        cache_hit_count=cache_hit_count,
    )
