from typing import Literal

from pydantic import BaseModel, Field

ActionType = Literal["issue_refund_request", "escalate_to_finance", "send_receipt_email"]
OperatorRole = Literal["support_agent", "support_admin", "finance_admin"]


class AskRequest(BaseModel):
    question: str = Field(min_length=3, description="User question about the docs.")
    top_k: int | None = Field(default=None, ge=1, le=10)
    case_id: str | None = None
    workspace_id: str | None = None
    customer_id: str | None = None
    invoice_id: str | None = None


class SourceChunk(BaseModel):
    chunk_id: str
    document_id: str
    source_path: str
    title: str
    heading: str | None = None
    topic: str | None = None
    policy_type: str | None = None
    escalation_class: str | None = None
    region: str | None = None
    effective_date: str | None = None
    content: str
    score: float | None = None
    dense_score: float | None = None
    lexical_score: float | None = None
    metadata_score: float | None = None
    retrieval_notes: list[str] = Field(default_factory=list)


class Citation(BaseModel):
    chunk_id: str
    source_path: str
    title: str
    quote: str = Field(description="Short excerpt supporting the answer.")


class AnswerPayload(BaseModel):
    answer: str = Field(
        min_length=12,
        description="Customer-facing answer to the billing question. Must be non-empty and specific.",
    )
    rationale: str = Field(
        min_length=12,
        description="Short internal explanation grounded in cited policy. Must be non-empty.",
    )
    recommended_action: str = Field(
        min_length=8,
        description="Single next step for the support agent. Must be non-empty and operational.",
    )
    escalation_required: bool = Field(description="Whether the case should be escalated.")
    citations: list[Citation]
    confidence: Literal["low", "medium", "high"]


class ToolTraceEntry(BaseModel):
    tool_name: str
    arguments: dict[str, str | int | bool | None]
    status: Literal["ok", "error"]
    output_summary: str


class ActionProposal(BaseModel):
    action_type: ActionType
    title: str
    reason: str
    status: Literal["pending_approval"]
    payload: dict[str, str | int | bool | None]


class ActionExecution(BaseModel):
    action_type: ActionType
    status: Literal["executed"]
    result_summary: str
    payload: dict[str, str | int | bool | None]
    persisted_to: str


class ApproveActionRequest(BaseModel):
    action_type: ActionType
    payload: dict[str, str | int | bool | None]


class CaseTurn(BaseModel):
    turn_id: str
    asked_at: str
    question: str
    answer: str
    recommended_action: str
    escalation_required: bool
    tool_trace: list[ToolTraceEntry] = Field(default_factory=list)
    action_proposal: ActionProposal | None = None


class CaseStateSummary(BaseModel):
    case_id: str
    workspace_id: str | None = None
    customer_id: str | None = None
    invoice_id: str | None = None
    turn_count: int = 0
    last_question: str | None = None
    last_updated_at: str | None = None
    open_action_type: ActionType | None = None


class CaseStateSnapshot(CaseStateSummary):
    notes_path: str
    turns: list[CaseTurn] = Field(default_factory=list)


class ResetCaseResponse(BaseModel):
    case_id: str
    status: Literal["reset"]


class ModelUsage(BaseModel):
    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None


class ExecutionMetrics(BaseModel):
    request_status: Literal["ok", "guardrail_blocked"]
    latency_ms: int
    tool_calls_made: int
    tool_error_count: int
    cache_hit_count: int = 0
    model_name: str
    model_usage: ModelUsage | None = None
    guardrail_reason: str | None = None


class RetrievalDebug(BaseModel):
    agent_mode: str
    query: str
    top_k: int
    case_id: str | None = None
    case_state_summary: CaseStateSummary | None = None
    workspace_id: str | None = None
    retrieval_strategy: str
    retrieval_reason: str
    system_prompt: str
    user_prompt: str
    retrieved_chunks: list[SourceChunk]
    tool_trace: list[ToolTraceEntry] = Field(default_factory=list)
    action_proposal: ActionProposal | None = None
    execution: ExecutionMetrics


class AskResponse(BaseModel):
    answer: AnswerPayload
    debug: RetrievalDebug


class OperatorSession(BaseModel):
    operator_id: str
    name: str
    role: OperatorRole
    allowed_workspaces: list[str]
    can_ingest: bool


class ObservabilityEvent(BaseModel):
    recorded_at: str
    event: str
    status: str
    guardrail_reason: str | None = None
    mode: str | None = None
    question: str | None = None
    case_id: str | None = None
    workspace_id: str | None = None
    customer_id: str | None = None
    invoice_id: str | None = None
    latency_ms: int | None = None
    tool_calls_made: int | None = None
    tool_error_count: int | None = None
    cache_hit_count: int | None = None
    total_tokens: int | None = None
    action_type: ActionType | None = None
    confidence: str | None = None
    model_name: str | None = None


class ActionExecutionSummary(BaseModel):
    action_type: ActionType
    status: str
    result_summary: str
    workspace_id: str | None = None
    customer_id: str | None = None
    invoice_id: str | None = None
    created_at: str


class IncidentSummary(BaseModel):
    total_events: int
    guardrail_block_count: int
    unauthorized_count: int
    high_latency_count: int
    token_budget_block_count: int
    unsupported_case_count: int
    recent_failures: list[ObservabilityEvent]
    recent_actions: list[ActionExecutionSummary]
