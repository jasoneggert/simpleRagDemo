from time import perf_counter
from typing import Annotated

from fastapi import FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import ValidationError

from app.agent import AgentExecutionError, run_billing_resolution_agent
from app.auth import (
    authenticate_operator,
    require_action_approval_permission,
    require_case_reset_permission,
    require_ingest_permission,
    require_ops_access,
    require_workspace_access,
    to_session,
)
from app.case_state import build_case_context, load_case_state, reset_case_state, save_case_turn, summarize_case_state
from app.config import settings
from app.ingest import ingest_seed_docs
from app.index_state import resolve_index_state
from app.models import (
    ActionExecution,
    ApproveActionRequest,
    AskRequest,
    AskResponse,
    CaseStateSnapshot,
    ExecutionMetrics,
    IncidentSummary,
    ModelUsage,
    ObservabilityEvent,
    OperatorSession,
    ResetCaseResponse,
    RetrievalDebug,
)
from app.observability import append_observability_event, build_incident_summary, list_observability_events, list_recent_actions
from app.support_tools import (
    create_case_note,
    escalate_to_finance,
    issue_refund_request,
    resolve_workspace_scope,
    send_receipt_email,
)
from app.vectorstore import get_chroma_collection_count


app = FastAPI(title="RAG Docs Copilot")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

SUPPORTED_DOMAIN_TERMS = (
    "billing",
    "charge",
    "invoice",
    "refund",
    "receipt",
    "vat",
    "tax",
    "payment",
    "renewal",
    "decline",
    "credit",
    "chargeback",
    "fraud",
    "workspace",
    "plan",
)


def _is_supported_billing_question(question: str) -> bool:
    lowered = question.lower()
    return any(term in lowered for term in SUPPORTED_DOMAIN_TERMS)


def _require_workspace_access_with_audit(
    operator,
    workspace_id: str | None,
    *,
    event: str,
    question: str | None = None,
    case_id: str | None = None,
    customer_id: str | None = None,
    invoice_id: str | None = None,
) -> None:
    try:
        require_workspace_access(operator, workspace_id)
    except HTTPException:
        append_observability_event(
            {
                "event": event,
                "status": "guardrail_blocked",
                "guardrail_reason": "unauthorized",
                "workspace_id": workspace_id,
                "case_id": case_id,
                "customer_id": customer_id,
                "invoice_id": invoice_id,
                "question": question,
                "operator_id": operator.operator_id,
            }
        )
        raise


@app.get("/health")
def healthcheck() -> dict[str, str | int | bool | dict[str, str | int | bool] | None]:
    chunk_count = get_chroma_collection_count()
    index_state = resolve_index_state(chunk_count)
    current = index_state.current
    stored = index_state.stored
    return {
        "status": "ok",
        "collection": settings.chroma_collection_name,
        "mode": "demo" if settings.demo_mode else "openai",
        "chunk_count": index_state.chunk_count,
        "index_status": index_state.status,
        "index_ready": index_state.status == "ready",
        "index_reason": index_state.reason,
        "current_index": {
            "demo_mode": current.demo_mode,
            "embedding_model": current.embedding_model,
            "chunk_size": current.chunk_size,
            "chunk_overlap": current.chunk_overlap,
            "seed_docs_fingerprint": current.seed_docs_fingerprint,
            "last_ingested_at": current.last_ingested_at,
        },
        "stored_index": None
        if stored is None
        else {
            "demo_mode": stored.demo_mode,
            "embedding_model": stored.embedding_model,
            "chunk_size": stored.chunk_size,
            "chunk_overlap": stored.chunk_overlap,
            "seed_docs_fingerprint": stored.seed_docs_fingerprint,
            "last_ingested_at": stored.last_ingested_at,
        },
    }


@app.post("/ingest")
def ingest_docs(authorization: Annotated[str | None, Header()] = None) -> dict[str, int]:
    operator = authenticate_operator(authorization)
    require_ingest_permission(operator)
    if not settings.demo_mode and not settings.openai_api_key:
        raise HTTPException(status_code=500, detail="OPENAI_API_KEY is not configured.")

    return ingest_seed_docs()


@app.post("/actions/approve", response_model=ActionExecution)
def approve_action(
    request: ApproveActionRequest,
    authorization: Annotated[str | None, Header()] = None,
) -> ActionExecution:
    operator = authenticate_operator(authorization)
    require_action_approval_permission(operator, request.action_type)
    payload = request.payload
    _require_workspace_access_with_audit(
        operator,
        str(payload.get("workspace_id")) if payload.get("workspace_id") is not None else None,
        event="action_approve",
        case_id=None,
        customer_id=str(payload.get("customer_id")) if payload.get("customer_id") is not None else None,
        invoice_id=str(payload.get("invoice_id")) if payload.get("invoice_id") is not None else None,
    )
    if request.action_type == "issue_refund_request":
        result = issue_refund_request(
            workspace_id=str(payload.get("workspace_id")) if payload.get("workspace_id") is not None else None,
            customer_id=str(payload.get("customer_id") or ""),
            invoice_id=str(payload.get("invoice_id") or ""),
            reason=str(payload.get("reason") or "Approved from UI."),
        )
    elif request.action_type == "escalate_to_finance":
        result = escalate_to_finance(
            workspace_id=str(payload.get("workspace_id")) if payload.get("workspace_id") is not None else None,
            customer_id=str(payload.get("customer_id")) if payload.get("customer_id") is not None else None,
            invoice_id=str(payload.get("invoice_id")) if payload.get("invoice_id") is not None else None,
            reason=str(payload.get("reason") or "Approved from UI."),
        )
    elif request.action_type == "send_receipt_email":
        result = send_receipt_email(
            workspace_id=str(payload.get("workspace_id")) if payload.get("workspace_id") is not None else None,
            customer_id=str(payload.get("customer_id") or ""),
            invoice_id=str(payload.get("invoice_id") or ""),
        )
    else:
        raise HTTPException(status_code=400, detail=f"Unsupported action type: {request.action_type}")

    return ActionExecution.model_validate(result.model_dump())


@app.get("/auth/session", response_model=OperatorSession)
def auth_session(authorization: Annotated[str | None, Header()] = None) -> OperatorSession:
    operator = authenticate_operator(authorization)
    return to_session(operator)


@app.get("/ops/events", response_model=list[ObservabilityEvent])
def get_ops_events(authorization: Annotated[str | None, Header()] = None, limit: int = 20) -> list[ObservabilityEvent]:
    operator = authenticate_operator(authorization)
    require_ops_access(operator)
    return list_observability_events(limit=limit)


@app.get("/ops/summary", response_model=IncidentSummary)
def get_ops_summary(authorization: Annotated[str | None, Header()] = None) -> IncidentSummary:
    operator = authenticate_operator(authorization)
    require_ops_access(operator)
    return build_incident_summary()


@app.get("/cases/{case_id}", response_model=CaseStateSnapshot)
def get_case_state(case_id: str, authorization: Annotated[str | None, Header()] = None) -> CaseStateSnapshot:
    operator = authenticate_operator(authorization)
    state = load_case_state(case_id)
    if state is None:
        raise HTTPException(status_code=404, detail=f"No persisted case state found for {case_id}.")
    _require_workspace_access_with_audit(operator, state.workspace_id, event="case_read", case_id=case_id)
    return state


@app.post("/cases/{case_id}/reset", response_model=ResetCaseResponse)
def reset_case(case_id: str, authorization: Annotated[str | None, Header()] = None) -> ResetCaseResponse:
    operator = authenticate_operator(authorization)
    state = load_case_state(case_id)
    if state is not None:
        _require_workspace_access_with_audit(operator, state.workspace_id, event="case_reset", case_id=case_id)
    require_case_reset_permission(operator)
    reset_case_state(case_id)
    return ResetCaseResponse(case_id=case_id, status="reset")


@app.post("/ask", response_model=AskResponse)
async def ask_docs(
    request: AskRequest,
    authorization: Annotated[str | None, Header()] = None,
) -> AskResponse:
    request_started_at = perf_counter()
    operator = authenticate_operator(authorization)
    if not settings.demo_mode and not settings.openai_api_key:
        raise HTTPException(status_code=500, detail="OPENAI_API_KEY is not configured.")

    index_state = resolve_index_state(get_chroma_collection_count())
    if index_state.status != "ready":
        raise HTTPException(status_code=409, detail=index_state.reason)

    existing_case_state = load_case_state(request.case_id) if request.case_id else None
    effective_customer_id = request.customer_id or (
        existing_case_state.customer_id if existing_case_state is not None else None
    )
    effective_invoice_id = request.invoice_id or (
        existing_case_state.invoice_id if existing_case_state is not None else None
    )
    if (
        existing_case_state is not None
        and request.workspace_id is not None
        and existing_case_state.workspace_id is not None
        and request.workspace_id != existing_case_state.workspace_id
    ):
        raise HTTPException(
            status_code=409,
            detail=(
                f"Case {request.case_id} is already scoped to workspace {existing_case_state.workspace_id} "
                f"and cannot be reused for workspace {request.workspace_id}."
            ),
        )
    request_workspace_id = request.workspace_id or (
        existing_case_state.workspace_id if existing_case_state is not None else None
    )
    try:
        effective_workspace_id = resolve_workspace_scope(
            workspace_id=request_workspace_id,
            customer_id=effective_customer_id,
            invoice_id=effective_invoice_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    _require_workspace_access_with_audit(
        operator,
        effective_workspace_id,
        event="ask",
        question=request.question,
        case_id=request.case_id,
        customer_id=effective_customer_id,
        invoice_id=effective_invoice_id,
    )
    case_context = build_case_context(existing_case_state)

    if not _is_supported_billing_question(request.question):
        latency_ms = int((perf_counter() - request_started_at) * 1000)
        append_observability_event(
            {
                "event": "ask",
                "status": "guardrail_blocked",
                "guardrail_reason": "unsupported_case",
                "mode": "demo" if settings.demo_mode else "openai",
                "question": request.question,
                "case_id": request.case_id,
                "workspace_id": effective_workspace_id,
                "customer_id": effective_customer_id,
                "invoice_id": effective_invoice_id,
                "latency_ms": latency_ms,
            }
        )
        raise HTTPException(
            status_code=422,
            detail="This copilot only supports billing, invoices, payments, tax, refunds, receipts, and escalation workflows.",
        )

    try:
        effective_top_k = min(request.top_k or settings.retrieval_k, 3)
        result = await run_billing_resolution_agent(
            question=request.question,
            top_k=effective_top_k,
            workspace_id=effective_workspace_id,
            customer_id=effective_customer_id,
            invoice_id=effective_invoice_id,
            case_context=case_context,
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except AgentExecutionError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Unexpected billing-resolution agent failure: {exc}",
        ) from exc

    if not result.retrieved_chunks:
        raise HTTPException(status_code=404, detail="No chunks found. Ingest docs first.")

    total_latency_ms = int((perf_counter() - request_started_at) * 1000)
    total_tokens = result.model_usage.total_tokens if result.model_usage is not None else None
    if total_latency_ms > settings.agent_max_latency_ms:
        append_observability_event(
            {
                "event": "ask",
                "status": "guardrail_blocked",
                "guardrail_reason": "latency_budget_exceeded",
                "mode": "demo" if settings.demo_mode else "openai",
                "question": request.question,
                "case_id": request.case_id,
                "workspace_id": effective_workspace_id,
                "customer_id": effective_customer_id,
                "invoice_id": effective_invoice_id,
                "latency_ms": total_latency_ms,
                "tool_calls_made": len(result.tool_trace),
                "tool_error_count": sum(1 for entry in result.tool_trace if entry.status == "error"),
            }
        )
        raise HTTPException(
            status_code=504,
            detail=(
                "The billing-resolution agent exceeded the configured latency budget and did not return a safe response."
            ),
        )
    if total_tokens is not None and total_tokens > settings.agent_max_total_tokens:
        append_observability_event(
            {
                "event": "ask",
                "status": "guardrail_blocked",
                "guardrail_reason": "token_budget_exceeded",
                "mode": "demo" if settings.demo_mode else "openai",
                "question": request.question,
                "case_id": request.case_id,
                "workspace_id": effective_workspace_id,
                "customer_id": effective_customer_id,
                "invoice_id": effective_invoice_id,
                "latency_ms": total_latency_ms,
                "tool_calls_made": len(result.tool_trace),
                "tool_error_count": sum(1 for entry in result.tool_trace if entry.status == "error"),
                "cache_hit_count": result.cache_hit_count,
                "total_tokens": total_tokens,
            }
        )
        raise HTTPException(
            status_code=429,
            detail=(
                "The billing-resolution agent exceeded the configured token budget and did not return a safe response."
            ),
        )

    answer = result.answer
    case_state_summary = None
    if request.case_id:
        persisted_case_state = save_case_turn(
            case_id=request.case_id,
            workspace_id=effective_workspace_id,
            customer_id=effective_customer_id,
            invoice_id=effective_invoice_id,
            question=request.question,
            answer=answer,
            tool_trace=result.tool_trace,
            action_proposal=result.action_proposal,
        )
        create_case_note(
            case_id=request.case_id,
            note=f"Q: {request.question}\nA: {answer.answer}\nNext: {answer.recommended_action}",
        )
        case_state_summary = summarize_case_state(persisted_case_state)

    execution = ExecutionMetrics(
        request_status="ok",
        latency_ms=total_latency_ms,
        tool_calls_made=len(result.tool_trace),
        tool_error_count=sum(1 for entry in result.tool_trace if entry.status == "error"),
        cache_hit_count=result.cache_hit_count,
        model_name=result.model_name,
        model_usage=result.model_usage,
        guardrail_reason=None,
    )

    append_observability_event(
            {
                "event": "ask",
                "status": execution.request_status,
                "mode": "demo" if settings.demo_mode else "openai",
                "question": request.question,
                "case_id": request.case_id,
                "workspace_id": effective_workspace_id,
                "customer_id": effective_customer_id,
                "invoice_id": effective_invoice_id,
            "latency_ms": execution.latency_ms,
            "tool_calls_made": execution.tool_calls_made,
            "tool_error_count": execution.tool_error_count,
            "cache_hit_count": execution.cache_hit_count,
            "retrieval_strategy": result.retrieval_strategy,
            "confidence": answer.confidence,
            "escalation_required": answer.escalation_required,
            "action_type": result.action_proposal.action_type if result.action_proposal is not None else None,
            "model_name": execution.model_name,
            "model_usage": None if execution.model_usage is None else execution.model_usage.model_dump(),
        }
    )

    return AskResponse(
        answer=answer,
        debug=RetrievalDebug(
            agent_mode="billing-resolution-agent",
            query=request.question,
            top_k=effective_top_k,
            case_id=request.case_id,
            case_state_summary=case_state_summary,
            workspace_id=effective_workspace_id,
            retrieval_strategy=result.retrieval_strategy,
            retrieval_reason=result.retrieval_reason,
            system_prompt=result.system_prompt,
            user_prompt=result.user_prompt,
            retrieved_chunks=result.retrieved_chunks,
            tool_trace=result.tool_trace,
            action_proposal=result.action_proposal,
            execution=execution,
        ),
    )
