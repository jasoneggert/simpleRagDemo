import { FormEvent, useEffect, useState } from "react";

import {
  ActionExecution,
  ActionExecutionSummary,
  AskResponse,
  CaseStateSnapshot,
  HealthResponse,
  IngestResponse,
  IncidentSummary,
  getOpsEvents,
  getOpsSummary,
  ObservabilityEvent,
  approveAction,
  askDocs,
  getCaseState,
  getHealth,
  getOperatorSession,
  getStoredAuthToken,
  ingestDocs,
  OperatorSession,
  resetCaseState,
  setStoredAuthToken,
} from "./api";

const STARTER_QUESTION =
  "A customer says they were charged twice for the same invoice within a day. What should support do?";

const SAMPLE_QUESTIONS = [
  "A customer says they were charged twice for the same invoice within a day. What should support do?",
  "The renewal failed and the card issuer returned a soft decline. What should I tell the customer?",
  "Can support refund VAT after an invoice has already been finalized?",
  "The customer downgraded mid-cycle and wants an immediate refund. Is that allowed?",
];

export default function App() {
  const [question, setQuestion] = useState(STARTER_QUESTION);
  const [authToken, setAuthToken] = useState("");
  const [topK, setTopK] = useState(4);
  const [caseId, setCaseId] = useState("");
  const [workspaceId, setWorkspaceId] = useState("");
  const [customerId, setCustomerId] = useState("");
  const [invoiceId, setInvoiceId] = useState("");
  const [result, setResult] = useState<AskResponse | null>(null);
  const [caseState, setCaseState] = useState<CaseStateSnapshot | null>(null);
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [ingestResult, setIngestResult] = useState<IngestResponse | null>(null);
  const [executedAction, setExecutedAction] = useState<ActionExecution | null>(null);
  const [operatorSession, setOperatorSession] = useState<OperatorSession | null>(null);
  const [incidentSummary, setIncidentSummary] = useState<IncidentSummary | null>(null);
  const [opsEvents, setOpsEvents] = useState<ObservabilityEvent[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [isIngesting, setIsIngesting] = useState(false);
  const [isApprovingAction, setIsApprovingAction] = useState(false);
  const [isInspectingCase, setIsInspectingCase] = useState(false);
  const [isResettingCase, setIsResettingCase] = useState(false);
  const [isLoadingSession, setIsLoadingSession] = useState(false);
  const [isLoadingOps, setIsLoadingOps] = useState(false);

  async function loadHealth() {
    const response = await getHealth();
    setHealth(response);
  }

  async function loadSession() {
    setIsLoadingSession(true);
    try {
      const session = await getOperatorSession();
      setOperatorSession(session);
    } catch (sessionError) {
      setOperatorSession(null);
      setError(sessionError instanceof Error ? sessionError.message : "Unknown session error.");
    } finally {
      setIsLoadingSession(false);
    }
  }

  useEffect(() => {
    let isMounted = true;
    setAuthToken(getStoredAuthToken());
    void (async () => {
      try {
        const response = await getHealth();
        if (isMounted) {
          setHealth(response);
        }
      } catch {
        if (isMounted) {
          setHealth(null);
        }
      }
    })();
    if (getStoredAuthToken()) {
      void loadSession();
    }
    return () => {
      isMounted = false;
    };
  }, []);

  function handleSaveAuthToken() {
    setStoredAuthToken(authToken);
    setError(null);
    if (authToken.trim()) {
      void loadSession();
    } else {
      setOperatorSession(null);
    }
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setIsLoading(true);
    setError(null);

    try {
      const response = await askDocs(
        question,
        topK,
        caseId.trim() || undefined,
        workspaceId.trim() || undefined,
        customerId.trim() || undefined,
        invoiceId.trim() || undefined,
      );
      setResult(response);
      setExecutedAction(null);
      if (caseId.trim()) {
        const persistedCase = await getCaseState(caseId.trim());
        setCaseState(persistedCase);
      }
    } catch (submissionError) {
      setResult(null);
      setError(
        submissionError instanceof Error ? submissionError.message : "Unknown request error.",
      );
    } finally {
      setIsLoading(false);
    }
  }

  async function handleIngest() {
    setIsIngesting(true);
    setError(null);

    try {
      const response = await ingestDocs();
      setIngestResult(response);
      await loadHealth();
    } catch (ingestError) {
      setError(ingestError instanceof Error ? ingestError.message : "Unknown ingest error.");
    } finally {
      setIsIngesting(false);
    }
  }

  async function handleApproveAction() {
    if (!result?.debug.action_proposal) {
      return;
    }

    setIsApprovingAction(true);
    setError(null);
    try {
      const response = await approveAction(result.debug.action_proposal);
      setExecutedAction(response);
    } catch (approvalError) {
      setError(approvalError instanceof Error ? approvalError.message : "Unknown approval error.");
    } finally {
      setIsApprovingAction(false);
    }
  }

  async function handleInspectCase() {
    if (!caseId.trim()) {
      return;
    }

    setIsInspectingCase(true);
    setError(null);
    try {
      const response = await getCaseState(caseId.trim());
      setCaseState(response);
    } catch (caseError) {
      setCaseState(null);
      setError(caseError instanceof Error ? caseError.message : "Unknown case inspection error.");
    } finally {
      setIsInspectingCase(false);
    }
  }

  async function handleResetCase() {
    if (!caseId.trim()) {
      return;
    }

    setIsResettingCase(true);
    setError(null);
    try {
      await resetCaseState(caseId.trim());
      setCaseState(null);
      setResult(null);
      setExecutedAction(null);
    } catch (caseError) {
      setError(caseError instanceof Error ? caseError.message : "Unknown case reset error.");
    } finally {
      setIsResettingCase(false);
    }
  }

  async function handleLoadOps() {
    setIsLoadingOps(true);
    setError(null);
    try {
      const [summary, events] = await Promise.all([getOpsSummary(), getOpsEvents(20)]);
      setIncidentSummary(summary);
      setOpsEvents(events);
    } catch (opsError) {
      setIncidentSummary(null);
      setOpsEvents([]);
      setError(opsError instanceof Error ? opsError.message : "Unknown ops load error.");
    } finally {
      setIsLoadingOps(false);
    }
  }

  const ingestedChunks = ingestResult?.chunks ?? 0;
  const indexStatus = health?.index_status ?? (ingestedChunks > 0 ? "ready" : "missing");
  const indexReady = indexStatus === "ready";
  const chunkCount = health?.chunk_count ?? ingestedChunks;
  const ingestDisabled = isIngesting || indexReady;
  const indexReason =
    health?.index_reason ??
    (ingestedChunks > 0
      ? "The index was rebuilt in this session and is ready to use."
      : "No persisted chunks detected yet.");
  const rationaleText =
    result?.answer.rationale?.trim() || "No internal rationale was returned for this response.";
  const recommendedActionText =
    result?.answer.recommended_action?.trim() || "No recommended action was returned for this response.";
  const retrievalStrategy =
    result?.debug.retrieval_strategy?.trim() || "vector retrieval";
  const retrievalReason =
    result?.debug.retrieval_reason?.trim() || "No retrieval explanation was returned for this response.";
  const toolTrace = result?.debug.tool_trace ?? [];
  const actionProposal = result?.debug.action_proposal ?? null;
  const caseSummary = result?.debug.case_state_summary ?? null;
  const execution = result?.debug.execution ?? null;

  return (
    <main className="page-shell">
      <section className="hero-card">
        <div className="hero-header">
          <div>
            <p className="eyebrow">Billing Support Copilot</p>
            <h1>Resolve billing questions with policy-backed answers</h1>
          </div>
          <span className={`mode-badge ${health?.mode ?? "offline"}`}>
            {health?.mode ?? "offline"}
          </span>
        </div>
        <div className="toolbar">
          <div>
            <h2>Operator Session</h2>
            <p className="toolbar-copy">
              Use a local demo operator token to authenticate and apply workspace and role permissions.
            </p>
            <p className="toolbar-copy">
              Demo tokens: <code>demo-support-token</code>, <code>demo-admin-token</code>, <code>demo-finance-token</code>
            </p>
            {operatorSession ? (
              <p className="toolbar-copy">
                Signed in as {operatorSession.name} ({operatorSession.role}) for {operatorSession.allowed_workspaces.join(", ")}.
              </p>
            ) : (
              <p className="toolbar-copy">No authenticated operator session loaded.</p>
            )}
          </div>
          <div className="toolbar-actions">
            <input
              type="password"
              value={authToken}
              onChange={(event) => setAuthToken(event.target.value)}
              placeholder="Bearer token"
            />
            <button type="button" className="force-button" onClick={handleSaveAuthToken}>
              Save Token
            </button>
            <button type="button" className="force-button" onClick={() => void loadSession()} disabled={isLoadingSession}>
              {isLoadingSession ? "Loading..." : "Refresh Session"}
            </button>
          </div>
        </div>
        <p className="lede">
          This demo retrieves billing policy chunks from Chroma, prompts FastAPI for a structured
          support decision, and returns citations, a recommended action, and an escalation signal.
        </p>

        <div className="hero-notes">
          <div className="hero-stat">
            <span className="hero-stat-label">Use case</span>
            <strong>Refunds, failed payments, taxes, invoice disputes</strong>
          </div>
          <div className="hero-stat">
            <span className="hero-stat-label">Output</span>
            <strong>Reply draft, rationale, next action, escalation flag</strong>
          </div>
          <div className="hero-stat">
            <span className="hero-stat-label">State</span>
            <strong>Optional local case memory with inspect and reset</strong>
          </div>
          <div className="hero-stat">
            <span className="hero-stat-label">Scope</span>
            <strong>Workspace-aware tenant guardrails for accounts, invoices, and actions</strong>
          </div>
          <div className="hero-stat">
            <span className="hero-stat-label">Access</span>
            <strong>Bearer-token operator auth with role-based approvals and workspace checks</strong>
          </div>
          <div className="hero-stat">
            <span className="hero-stat-label">Ops</span>
            <strong>Admin incident views for failures, guardrails, and recent actions</strong>
          </div>
        </div>
      </section>

      <section className="panel">
        <div className="toolbar">
          <div>
            <h2>Policy Corpus</h2>
            <p className="toolbar-copy">
              Rebuild the Chroma index after editing the seeded billing policies or changing the
              embedding mode.
            </p>
            <div className="index-summary">
              <span className={`index-badge ${indexStatus}`}>{indexStatus}</span>
              <p className="toolbar-copy">
                {indexReady
                  ? `Index ready with ${chunkCount} chunks persisted in Chroma.`
                  : indexStatus === "stale"
                    ? `Index is stale with ${chunkCount} persisted chunks and should be rebuilt before asking questions.`
                    : "No persisted chunks detected yet. Build the policy index once before asking questions."}
              </p>
              <p className="toolbar-copy">{indexReason}</p>
              {health?.stored_index?.last_ingested_at ? (
                <p className="toolbar-copy">
                  Last ingest: {new Date(health.stored_index.last_ingested_at).toLocaleString()}
                </p>
              ) : null}
            </div>
          </div>
          <div className="toolbar-actions">
            <button
              type="button"
              className="secondary-button"
              onClick={handleIngest}
              disabled={ingestDisabled}
            >
              {isIngesting
                ? "Rebuilding..."
                : indexReady
                  ? "Policy Index Ready"
                  : indexStatus === "stale"
                    ? "Rebuild Stale Index"
                    : "Build Policy Index"}
            </button>
            {indexStatus !== "missing" ? (
              <button
                type="button"
                className="force-button"
                onClick={handleIngest}
                disabled={isIngesting}
              >
                Force Rebuild
              </button>
            ) : null}
          </div>
        </div>

        {ingestResult ? (
          <div className="status-banner">
            Indexed {ingestResult.documents} policy documents into {ingestResult.chunks} chunks.
          </div>
        ) : null}

        <div className="sample-strip">
          {SAMPLE_QUESTIONS.map((sample) => (
            <button
              key={sample}
              type="button"
              className="sample-chip"
              onClick={() => setQuestion(sample)}
            >
              {sample}
            </button>
          ))}
        </div>

        <form className="question-form" onSubmit={handleSubmit}>
          <label className="field">
            <span>Billing question</span>
            <textarea
              value={question}
              rows={5}
              onChange={(event) => setQuestion(event.target.value)}
              placeholder="Describe the customer billing case"
            />
          </label>

          <div className="form-actions">
            <label className="field narrow">
              <span>Case ID</span>
              <input
                type="text"
                value={caseId}
                onChange={(event) => setCaseId(event.target.value)}
                placeholder="case_acme_duplicate"
              />
            </label>

            <label className="field narrow">
              <span>Workspace ID</span>
              <input
                type="text"
                value={workspaceId}
                onChange={(event) => setWorkspaceId(event.target.value)}
                placeholder="ws_acme"
              />
            </label>

            <label className="field narrow">
              <span>Customer ID</span>
              <input
                type="text"
                value={customerId}
                onChange={(event) => setCustomerId(event.target.value)}
                placeholder="cust_acme"
              />
            </label>

            <label className="field narrow">
              <span>Invoice ID</span>
              <input
                type="text"
                value={invoiceId}
                onChange={(event) => setInvoiceId(event.target.value)}
                placeholder="inv_acme_2001_dup"
              />
            </label>

            <label className="field narrow">
              <span>Top K</span>
              <input
                type="number"
                min={1}
                max={10}
                value={topK}
                onChange={(event) => setTopK(Number(event.target.value))}
              />
            </label>

            <button type="submit" disabled={isLoading || question.trim().length < 3}>
              {isLoading ? "Analyzing..." : "Draft Support Answer"}
            </button>
            <button
              type="button"
              className="force-button"
              onClick={handleInspectCase}
              disabled={isInspectingCase || caseId.trim().length < 3}
            >
              {isInspectingCase ? "Loading Case..." : "Inspect Case"}
            </button>
            <button
              type="button"
              className="force-button"
              onClick={handleResetCase}
              disabled={isResettingCase || caseId.trim().length < 3}
            >
              {isResettingCase ? "Resetting..." : "Reset Case"}
            </button>
          </div>
        </form>

        {error ? <div className="error-banner">{error}</div> : null}
      </section>

      <section className="panel result-panel">
        <div className="panel-header">
          <h2>Support Decision</h2>
          {result ? (
            <div className="result-badges">
              <span className={`confidence ${result.answer.confidence}`}>
                {result.answer.confidence}
              </span>
              <span
                className={`escalation-pill ${
                  result.answer.escalation_required ? "required" : "not-required"
                }`}
              >
                {result.answer.escalation_required ? "escalate" : "no escalation"}
              </span>
            </div>
          ) : null}
        </div>

        {result ? (
          <div className="result-grid">
            <article className="answer-card">
              <h3>Customer-Facing Answer</h3>
              <p>{result.answer.answer}</p>
              <h3>Internal Rationale</h3>
              <p>{rationaleText}</p>
              <h3>Recommended Action</h3>
              <p className="action-callout">{recommendedActionText}</p>
            </article>

            <aside className="citations-card">
              <h3>Supporting Citations</h3>
              {result.answer.citations.length > 0 ? (
                <ul className="citation-list">
                  {result.answer.citations.map((citation) => (
                    <li key={`${citation.chunk_id}-${citation.quote}`}>
                      <strong>{citation.title}</strong>
                      <span>{citation.source_path}</span>
                      <p>{citation.quote}</p>
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="empty-state">No citations were returned.</p>
              )}
            </aside>
          </div>
        ) : (
          <p className="empty-state">
            Submit a billing question to generate a grounded support recommendation.
          </p>
        )}
      </section>

      <section className="panel">
        <div className="panel-header">
          <h2>Operations</h2>
        </div>

        {operatorSession?.role === "support_admin" || operatorSession?.role === "finance_admin" ? (
          <>
            <div className="toolbar-actions">
              <button type="button" className="force-button" onClick={() => void handleLoadOps()} disabled={isLoadingOps}>
                {isLoadingOps ? "Loading Ops..." : "Load Incident View"}
              </button>
            </div>

            {incidentSummary ? (
              <div className="action-grid">
                <article className="answer-card">
                  <div className="panel-header">
                    <h3>Incident Summary</h3>
                    <span className="approval-pill pending">{incidentSummary.total_events} events</span>
                  </div>
                  <dl className="debug-meta">
                    <div>
                      <dt>Guardrail Blocks</dt>
                      <dd>{incidentSummary.guardrail_block_count}</dd>
                    </div>
                    <div>
                      <dt>Unauthorized</dt>
                      <dd>{incidentSummary.unauthorized_count}</dd>
                    </div>
                    <div>
                      <dt>High Latency</dt>
                      <dd>{incidentSummary.high_latency_count}</dd>
                    </div>
                    <div>
                      <dt>Token Budget</dt>
                      <dd>{incidentSummary.token_budget_block_count}</dd>
                    </div>
                    <div>
                      <dt>Unsupported Cases</dt>
                      <dd>{incidentSummary.unsupported_case_count}</dd>
                    </div>
                  </dl>
                </article>

                <article className="answer-card">
                  <div className="panel-header">
                    <h3>Recent Actions</h3>
                    <span className="approval-pill executed">{incidentSummary.recent_actions.length}</span>
                  </div>
                  {incidentSummary.recent_actions.length > 0 ? (
                    <ul className="trace-list">
                      {incidentSummary.recent_actions.map((action: ActionExecutionSummary, index) => (
                        <li key={`${action.action_type}-${index}`}>
                          <strong>{action.action_type}</strong>
                          <span className="trace-status ok">{action.status}</span>
                          <p>{action.result_summary}</p>
                          <p>{action.workspace_id ?? "unknown workspace"}</p>
                        </li>
                      ))}
                    </ul>
                  ) : (
                    <p className="empty-state">No recent actions recorded.</p>
                  )}
                </article>
              </div>
            ) : (
              <p className="empty-state">Load the incident view to inspect recent failures and action activity.</p>
            )}

            {opsEvents.length > 0 ? (
              <article className="answer-card">
                <div className="panel-header">
                  <h3>Recent Events</h3>
                  <span className="approval-pill waiting">{opsEvents.length}</span>
                </div>
                <ul className="trace-list">
                  {opsEvents.map((event, index) => (
                    <li key={`${event.recorded_at}-${index}`}>
                      <strong>{event.event}</strong>
                      <span className={`trace-status ${event.status === "ok" ? "ok" : "error"}`}>{event.status}</span>
                      <p>{event.guardrail_reason ?? event.question ?? "No event detail."}</p>
                      <p>
                        {event.workspace_id ?? "no workspace"} | latency {event.latency_ms ?? "n/a"} ms | tokens{" "}
                        {event.total_tokens ?? "n/a"}
                      </p>
                    </li>
                  ))}
                </ul>
              </article>
            ) : null}
          </>
        ) : (
          <p className="empty-state">Operational incident views are only available to support_admin and finance_admin operators.</p>
        )}
      </section>

      <section className="panel">
        <div className="panel-header">
          <h2>Case Memory</h2>
        </div>

        {caseSummary || caseState ? (
          <div className="action-grid">
            <article className="answer-card">
              <div className="panel-header">
                <h3>Current Case</h3>
                <span className="approval-pill waiting">
                  {(caseSummary?.case_id ?? caseState?.case_id) || "unspecified"}
                </span>
              </div>
              <dl className="debug-meta">
                <div>
                  <dt>Workspace</dt>
                  <dd>{caseSummary?.workspace_id ?? caseState?.workspace_id ?? "Unknown"}</dd>
                </div>
                <div>
                  <dt>Customer</dt>
                  <dd>{caseSummary?.customer_id ?? caseState?.customer_id ?? "Unknown"}</dd>
                </div>
                <div>
                  <dt>Invoice</dt>
                  <dd>{caseSummary?.invoice_id ?? caseState?.invoice_id ?? "Unknown"}</dd>
                </div>
                <div>
                  <dt>Turns</dt>
                  <dd>{caseSummary?.turn_count ?? caseState?.turn_count ?? 0}</dd>
                </div>
                <div>
                  <dt>Open Action</dt>
                  <dd>{caseSummary?.open_action_type ?? caseState?.open_action_type ?? "None"}</dd>
                </div>
              </dl>
              <p className="debug-explainer">
                {caseSummary?.last_question ?? caseState?.last_question ?? "No persisted question yet."}
              </p>
              {caseState ? <p className="chunk-path">{caseState.notes_path}</p> : null}
            </article>

            <article className="answer-card">
              <div className="panel-header">
                <h3>Recent Turns</h3>
                <span className="approval-pill pending">
                  {(caseState?.turns.length ?? 0).toString().padStart(2, "0")}
                </span>
              </div>
              {caseState && caseState.turns.length > 0 ? (
                <ul className="trace-list">
                  {caseState.turns.slice(-3).reverse().map((turn) => (
                    <li key={turn.turn_id}>
                      <strong>{turn.turn_id}</strong>
                      <span className={`trace-status ${turn.escalation_required ? "error" : "ok"}`}>
                        {turn.escalation_required ? "escalate" : "normal"}
                      </span>
                      <p>{turn.question}</p>
                      <p>{turn.recommended_action}</p>
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="empty-state">No persisted turns loaded for this case yet.</p>
              )}
            </article>
          </div>
        ) : (
          <p className="empty-state">
            Enter a case ID to persist multi-turn context, then inspect or reset that case locally.
          </p>
        )}
      </section>

      <section className="panel">
        <div className="panel-header">
          <h2>Action Control</h2>
        </div>

        {actionProposal ? (
          <div className="action-grid">
            <article className="answer-card">
              <div className="panel-header">
                <h3>{actionProposal.title}</h3>
                <span className="approval-pill pending">{actionProposal.status.replace("_", " ")}</span>
              </div>
              <p>{actionProposal.reason}</p>
              <pre>{JSON.stringify(actionProposal.payload, null, 2)}</pre>
              <button type="button" onClick={handleApproveAction} disabled={isApprovingAction}>
                {isApprovingAction ? "Approving..." : "Approve Action"}
              </button>
            </article>

            {executedAction ? (
              <article className="answer-card">
                <div className="panel-header">
                  <h3>Executed Action</h3>
                  <span className="approval-pill executed">{executedAction.status}</span>
                </div>
                <p>{executedAction.result_summary}</p>
                <p className="chunk-path">{executedAction.persisted_to}</p>
                <pre>{JSON.stringify(executedAction.payload, null, 2)}</pre>
              </article>
            ) : (
              <article className="answer-card">
                <div className="panel-header">
                  <h3>Execution Status</h3>
                  <span className="approval-pill waiting">recommended</span>
                </div>
                <p>This action has been recommended by the agent but has not been executed.</p>
              </article>
            )}
          </div>
        ) : (
          <p className="empty-state">
            No approval-gated action is currently proposed for this response.
          </p>
        )}
      </section>

      <section className="panel">
        <div className="panel-header">
          <h2>Prompt Debugging</h2>
        </div>

        {result ? (
          <div className="debug-grid">
            <article className="debug-card">
              <h3>Request</h3>
              <dl className="debug-meta">
                <div>
                  <dt>Query</dt>
                  <dd>{result.debug.query}</dd>
                </div>
                <div>
                  <dt>Top K</dt>
                  <dd>{result.debug.top_k}</dd>
                </div>
                <div>
                  <dt>Agent</dt>
                  <dd>{result.debug.agent_mode ?? "unknown"}</dd>
                </div>
                <div>
                  <dt>Case</dt>
                  <dd>{result.debug.case_id ?? "None"}</dd>
                </div>
                <div>
                  <dt>Workspace</dt>
                  <dd>{result.debug.workspace_id ?? "None"}</dd>
                </div>
                <div>
                  <dt>Strategy</dt>
                  <dd>{retrievalStrategy}</dd>
                </div>
                <div>
                  <dt>Latency</dt>
                  <dd>{execution ? `${execution.latency_ms} ms` : "N/A"}</dd>
                </div>
                <div>
                  <dt>Tool Calls</dt>
                  <dd>{execution?.tool_calls_made ?? toolTrace.length}</dd>
                </div>
                <div>
                  <dt>Tool Errors</dt>
                  <dd>{execution?.tool_error_count ?? 0}</dd>
                </div>
                <div>
                  <dt>Cache Hits</dt>
                  <dd>{execution?.cache_hit_count ?? 0}</dd>
                </div>
                <div>
                  <dt>Model</dt>
                  <dd>{execution?.model_name ?? "unknown"}</dd>
                </div>
              </dl>
              <p className="debug-explainer">{retrievalReason}</p>
              {execution?.model_usage ? (
                <p className="debug-explainer">
                  Usage: input {execution.model_usage.input_tokens ?? "?"}, output{" "}
                  {execution.model_usage.output_tokens ?? "?"}, total{" "}
                  {execution.model_usage.total_tokens ?? "?"}.
                </p>
              ) : null}
              {toolTrace.length > 0 ? (
                <div className="tool-trace">
                  <h3>Tool Trace</h3>
                  <ul className="trace-list">
                    {toolTrace.map((entry, index) => (
                      <li key={`${entry.tool_name}-${index}`}>
                        <strong>{entry.tool_name}</strong>
                        <span className={`trace-status ${entry.status}`}>{entry.status}</span>
                        <pre>{JSON.stringify(entry.arguments)}</pre>
                        <p>{entry.output_summary}</p>
                      </li>
                    ))}
                  </ul>
                </div>
              ) : null}
            </article>

            <article className="debug-card prompt-card">
              <h3>System Prompt</h3>
              <pre>{result.debug.system_prompt}</pre>
            </article>

            <article className="debug-card prompt-card">
              <h3>User Prompt</h3>
              <pre>{result.debug.user_prompt}</pre>
            </article>
          </div>
        ) : (
          <p className="empty-state">Prompt details will appear after the first successful question.</p>
        )}
      </section>

      <section className="panel">
        <div className="panel-header">
          <h2>Retrieved Policy Chunks</h2>
        </div>

        {result ? (
          <div className="chunk-grid">
            {result.debug.retrieved_chunks.map((chunk) => (
              <article className="chunk-card" key={chunk.chunk_id}>
                {(() => {
                  const retrievalNotes = chunk.retrieval_notes ?? [];
                  return (
                    <>
                <div className="chunk-meta">
                  <strong>{chunk.title}</strong>
                  <span>{chunk.chunk_id}</span>
                </div>
                <dl className="debug-meta">
                  <div>
                    <dt>Document</dt>
                    <dd>{chunk.document_id}</dd>
                  </div>
                  <div>
                    <dt>Heading</dt>
                    <dd>{chunk.heading ?? "None"}</dd>
                  </div>
                  <div>
                    <dt>Score</dt>
                    <dd>{typeof chunk.score === "number" ? chunk.score.toFixed(4) : "N/A"}</dd>
                  </div>
                  <div>
                    <dt>Dense</dt>
                    <dd>{typeof chunk.dense_score === "number" ? chunk.dense_score.toFixed(4) : "N/A"}</dd>
                  </div>
                  <div>
                    <dt>Lexical</dt>
                    <dd>{typeof chunk.lexical_score === "number" ? chunk.lexical_score.toFixed(4) : "N/A"}</dd>
                  </div>
                  <div>
                    <dt>Metadata</dt>
                    <dd>{typeof chunk.metadata_score === "number" ? chunk.metadata_score.toFixed(4) : "N/A"}</dd>
                  </div>
                  <div>
                    <dt>Topic</dt>
                    <dd>{chunk.topic ?? "Unknown"}</dd>
                  </div>
                  <div>
                    <dt>Policy Type</dt>
                    <dd>{chunk.policy_type ?? "Unknown"}</dd>
                  </div>
                  <div>
                    <dt>Escalation</dt>
                    <dd>{chunk.escalation_class ?? "Unknown"}</dd>
                  </div>
                  <div>
                    <dt>Region</dt>
                    <dd>{chunk.region ?? "Unknown"}</dd>
                  </div>
                </dl>
                {retrievalNotes.length > 0 ? (
                  <ul className="note-list">
                    {retrievalNotes.map((note) => (
                      <li key={`${chunk.chunk_id}-${note}`}>{note}</li>
                    ))}
                  </ul>
                ) : null}
                <p className="chunk-path">{chunk.source_path}</p>
                <pre>{chunk.content}</pre>
                    </>
                  );
                })()}
              </article>
            ))}
          </div>
        ) : (
          <p className="empty-state">Retrieved policy chunks will appear after a successful response.</p>
        )}
      </section>
    </main>
  );
}
