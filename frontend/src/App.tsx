import { FormEvent, useEffect, useState } from "react";

import { AskResponse, HealthResponse, IngestResponse, askDocs, getHealth, ingestDocs } from "./api";

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
  const [topK, setTopK] = useState(4);
  const [result, setResult] = useState<AskResponse | null>(null);
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [ingestResult, setIngestResult] = useState<IngestResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [isIngesting, setIsIngesting] = useState(false);

  async function loadHealth() {
    const response = await getHealth();
    setHealth(response);
  }

  useEffect(() => {
    let isMounted = true;
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
    return () => {
      isMounted = false;
    };
  }, []);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setIsLoading(true);
    setError(null);

    try {
      const response = await askDocs(question, topK);
      setResult(response);
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

  const ingestedChunks = ingestResult?.chunks ?? 0;
  const indexReady = (health?.index_ready ?? false) || ingestedChunks > 0;
  const chunkCount = health?.chunk_count ?? ingestedChunks;
  const ingestDisabled = isIngesting || indexReady;
  const rationaleText =
    result?.answer.rationale?.trim() || "No internal rationale was returned for this response.";
  const recommendedActionText =
    result?.answer.recommended_action?.trim() || "No recommended action was returned for this response.";

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
            {health ? (
              <p className="toolbar-copy">
                {indexReady
                  ? `Index ready with ${chunkCount} chunks persisted in Chroma.`
                  : "No persisted chunks detected yet. Build the policy index once before asking questions."}
              </p>
            ) : ingestResult ? (
              <p className="toolbar-copy">
                Index ready with {ingestedChunks} chunks persisted in Chroma.
              </p>
            ) : null}
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
                  : "Rebuild Policy Index"}
            </button>
            {indexReady ? (
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
              </dl>
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
                </dl>
                <p className="chunk-path">{chunk.source_path}</p>
                <pre>{chunk.content}</pre>
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
