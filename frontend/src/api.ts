export type Citation = {
  chunk_id: string;
  source_path: string;
  title: string;
  quote: string;
};

export type AnswerPayload = {
  answer: string;
  rationale: string;
  recommended_action: string;
  escalation_required: boolean;
  citations: Citation[];
  confidence: "low" | "medium" | "high";
};

export type SourceChunk = {
  chunk_id: string;
  document_id: string;
  source_path: string;
  title: string;
  heading?: string | null;
  topic?: string | null;
  policy_type?: string | null;
  escalation_class?: string | null;
  region?: string | null;
  effective_date?: string | null;
  content: string;
  score?: number | null;
  dense_score?: number | null;
  lexical_score?: number | null;
  metadata_score?: number | null;
  retrieval_notes: string[];
};

export type ToolTraceEntry = {
  tool_name: string;
  arguments: Record<string, string | number | boolean | null>;
  status: "ok" | "error";
  output_summary: string;
};

export type ActionProposal = {
  action_type: "issue_refund_request" | "escalate_to_finance" | "send_receipt_email";
  title: string;
  reason: string;
  status: "pending_approval";
  payload: Record<string, string | number | boolean | null>;
};

export type ActionExecution = {
  action_type: "issue_refund_request" | "escalate_to_finance" | "send_receipt_email";
  status: "executed";
  result_summary: string;
  payload: Record<string, string | number | boolean | null>;
  persisted_to: string;
};

export type CaseTurn = {
  turn_id: string;
  asked_at: string;
  question: string;
  answer: string;
  recommended_action: string;
  escalation_required: boolean;
  tool_trace: ToolTraceEntry[];
  action_proposal?: ActionProposal | null;
};

export type CaseStateSummary = {
  case_id: string;
  workspace_id?: string | null;
  customer_id?: string | null;
  invoice_id?: string | null;
  turn_count: number;
  last_question?: string | null;
  last_updated_at?: string | null;
  open_action_type?: "issue_refund_request" | "escalate_to_finance" | "send_receipt_email" | null;
};

export type CaseStateSnapshot = CaseStateSummary & {
  notes_path: string;
  turns: CaseTurn[];
};

export type ModelUsage = {
  input_tokens?: number | null;
  output_tokens?: number | null;
  total_tokens?: number | null;
};

export type ExecutionMetrics = {
  request_status: "ok" | "guardrail_blocked";
  latency_ms: number;
  tool_calls_made: number;
  tool_error_count: number;
  cache_hit_count: number;
  model_name: string;
  model_usage?: ModelUsage | null;
  guardrail_reason?: string | null;
};

export type RetrievalDebug = {
  agent_mode: string;
  query: string;
  top_k: number;
  case_id?: string | null;
  case_state_summary?: CaseStateSummary | null;
  workspace_id?: string | null;
  retrieval_strategy: string;
  retrieval_reason: string;
  system_prompt: string;
  user_prompt: string;
  retrieved_chunks: SourceChunk[];
  tool_trace: ToolTraceEntry[];
  action_proposal?: ActionProposal | null;
  execution: ExecutionMetrics;
};

export type AskResponse = {
  answer: AnswerPayload;
  debug: RetrievalDebug;
};

export type HealthResponse = {
  status: string;
  collection: string;
  mode?: "demo" | "openai";
  chunk_count: number;
  index_ready: boolean;
  index_status: "missing" | "stale" | "ready";
  index_reason: string;
  current_index: {
    demo_mode: boolean;
    embedding_model: string;
    chunk_size: number;
    chunk_overlap: number;
    seed_docs_fingerprint: string;
    last_ingested_at: string;
  };
  stored_index: {
    demo_mode: boolean;
    embedding_model: string;
    chunk_size: number;
    chunk_overlap: number;
    seed_docs_fingerprint: string;
    last_ingested_at: string;
  } | null;
};

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "http://127.0.0.1:8000";
const AUTH_TOKEN_STORAGE_KEY = "doc-copilot-auth-token";

export type OperatorSession = {
  operator_id: string;
  name: string;
  role: "support_agent" | "support_admin" | "finance_admin";
  allowed_workspaces: string[];
  can_ingest: boolean;
};

export type ObservabilityEvent = {
  recorded_at: string;
  event: string;
  status: string;
  guardrail_reason?: string | null;
  mode?: string | null;
  question?: string | null;
  case_id?: string | null;
  workspace_id?: string | null;
  customer_id?: string | null;
  invoice_id?: string | null;
  latency_ms?: number | null;
  tool_calls_made?: number | null;
  tool_error_count?: number | null;
  cache_hit_count?: number | null;
  total_tokens?: number | null;
  action_type?: "issue_refund_request" | "escalate_to_finance" | "send_receipt_email" | null;
  confidence?: string | null;
  model_name?: string | null;
};

export type ActionExecutionSummary = {
  action_type: "issue_refund_request" | "escalate_to_finance" | "send_receipt_email";
  status: string;
  result_summary: string;
  workspace_id?: string | null;
  customer_id?: string | null;
  invoice_id?: string | null;
  created_at: string;
};

export type IncidentSummary = {
  total_events: number;
  guardrail_block_count: number;
  unauthorized_count: number;
  high_latency_count: number;
  token_budget_block_count: number;
  unsupported_case_count: number;
  recent_failures: ObservabilityEvent[];
  recent_actions: ActionExecutionSummary[];
};

function getAuthHeaders(): HeadersInit {
  const token = getStoredAuthToken();
  return token ? { Authorization: `Bearer ${token}` } : {};
}

export function getStoredAuthToken(): string {
  if (typeof window === "undefined") {
    return "";
  }
  return window.localStorage.getItem(AUTH_TOKEN_STORAGE_KEY) ?? "";
}

export function setStoredAuthToken(token: string): void {
  if (typeof window === "undefined") {
    return;
  }
  const trimmed = token.trim();
  if (trimmed) {
    window.localStorage.setItem(AUTH_TOKEN_STORAGE_KEY, trimmed);
  } else {
    window.localStorage.removeItem(AUTH_TOKEN_STORAGE_KEY);
  }
}

export type IngestResponse = {
  documents: number;
  chunks: number;
};

export async function askDocs(
  question: string,
  topK?: number,
  caseId?: string,
  workspaceId?: string,
  customerId?: string,
  invoiceId?: string,
): Promise<AskResponse> {
  const response = await fetch(`${API_BASE_URL}/ask`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      ...getAuthHeaders(),
    },
    body: JSON.stringify({
      question,
      top_k: topK,
      case_id: caseId,
      workspace_id: workspaceId,
      customer_id: customerId,
      invoice_id: invoiceId,
    }),
  });

  if (!response.ok) {
    let message = `Request failed with status ${response.status}`;
    try {
      const errorBody = (await response.json()) as { detail?: string };
      if (errorBody.detail) {
        message = errorBody.detail;
      }
    } catch {
      // Keep the default message if the response body is not JSON.
    }
    throw new Error(message);
  }

  return (await response.json()) as AskResponse;
}

export async function ingestDocs(): Promise<IngestResponse> {
  const response = await fetch(`${API_BASE_URL}/ingest`, {
    method: "POST",
    headers: getAuthHeaders(),
  });

  if (!response.ok) {
    let message = `Request failed with status ${response.status}`;
    try {
      const errorBody = (await response.json()) as { detail?: string };
      if (errorBody.detail) {
        message = errorBody.detail;
      }
    } catch {
      // Keep the default message if the response body is not JSON.
    }
    throw new Error(message);
  }

  return (await response.json()) as IngestResponse;
}

export async function approveAction(actionProposal: ActionProposal): Promise<ActionExecution> {
  const response = await fetch(`${API_BASE_URL}/actions/approve`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      ...getAuthHeaders(),
    },
    body: JSON.stringify({
      action_type: actionProposal.action_type,
      payload: actionProposal.payload,
    }),
  });

  if (!response.ok) {
    let message = `Request failed with status ${response.status}`;
    try {
      const errorBody = (await response.json()) as { detail?: string };
      if (errorBody.detail) {
        message = errorBody.detail;
      }
    } catch {
      // Keep the default message if the response body is not JSON.
    }
    throw new Error(message);
  }

  return (await response.json()) as ActionExecution;
}

export async function getCaseState(caseId: string): Promise<CaseStateSnapshot> {
  const response = await fetch(`${API_BASE_URL}/cases/${encodeURIComponent(caseId)}`, {
    headers: getAuthHeaders(),
  });
  if (!response.ok) {
    let message = `Request failed with status ${response.status}`;
    try {
      const errorBody = (await response.json()) as { detail?: string };
      if (errorBody.detail) {
        message = errorBody.detail;
      }
    } catch {
      // Keep the default message if the response body is not JSON.
    }
    throw new Error(message);
  }
  return (await response.json()) as CaseStateSnapshot;
}

export async function resetCaseState(caseId: string): Promise<{ case_id: string; status: "reset" }> {
  const response = await fetch(`${API_BASE_URL}/cases/${encodeURIComponent(caseId)}/reset`, {
    method: "POST",
    headers: getAuthHeaders(),
  });
  if (!response.ok) {
    let message = `Request failed with status ${response.status}`;
    try {
      const errorBody = (await response.json()) as { detail?: string };
      if (errorBody.detail) {
        message = errorBody.detail;
      }
    } catch {
      // Keep the default message if the response body is not JSON.
    }
    throw new Error(message);
  }
  return (await response.json()) as { case_id: string; status: "reset" };
}

export async function getHealth(): Promise<HealthResponse> {
  const response = await fetch(`${API_BASE_URL}/health`);

  if (!response.ok) {
    throw new Error(`Health request failed with status ${response.status}`);
  }

  return (await response.json()) as HealthResponse;
}

export async function getOperatorSession(): Promise<OperatorSession> {
  const response = await fetch(`${API_BASE_URL}/auth/session`, {
    headers: getAuthHeaders(),
  });

  if (!response.ok) {
    let message = `Request failed with status ${response.status}`;
    try {
      const errorBody = (await response.json()) as { detail?: string };
      if (errorBody.detail) {
        message = errorBody.detail;
      }
    } catch {
      // Keep the default message if the response body is not JSON.
    }
    throw new Error(message);
  }

  return (await response.json()) as OperatorSession;
}

export async function getOpsSummary(): Promise<IncidentSummary> {
  const response = await fetch(`${API_BASE_URL}/ops/summary`, {
    headers: getAuthHeaders(),
  });
  if (!response.ok) {
    let message = `Request failed with status ${response.status}`;
    try {
      const errorBody = (await response.json()) as { detail?: string };
      if (errorBody.detail) {
        message = errorBody.detail;
      }
    } catch {
      // Keep the default message if the response body is not JSON.
    }
    throw new Error(message);
  }
  return (await response.json()) as IncidentSummary;
}

export async function getOpsEvents(limit = 20): Promise<ObservabilityEvent[]> {
  const response = await fetch(`${API_BASE_URL}/ops/events?limit=${encodeURIComponent(String(limit))}`, {
    headers: getAuthHeaders(),
  });
  if (!response.ok) {
    let message = `Request failed with status ${response.status}`;
    try {
      const errorBody = (await response.json()) as { detail?: string };
      if (errorBody.detail) {
        message = errorBody.detail;
      }
    } catch {
      // Keep the default message if the response body is not JSON.
    }
    throw new Error(message);
  }
  return (await response.json()) as ObservabilityEvent[];
}
