import { FormEvent, useEffect, useState } from "react";

import { AskResponse, HealthResponse, IngestResponse, askDocs, getHealth, ingestDocs } from "./api";

const STARTER_QUESTION = "How should a RAG answer be validated before the UI renders it?";

export default function App() {
  const [question, setQuestion] = useState(STARTER_QUESTION);
  const [topK, setTopK] = useState(4);
  const [result, setResult] = useState<AskResponse | null>(null);
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [ingestResult, setIngestResult] = useState<IngestResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [isIngesting, setIsIngesting] = useState(false);

  useEffect(() => {
    let isMounted = true;

    async function loadHealth() {
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
    }

    void loadHealth();
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
    } catch (ingestError) {
      setError(ingestError instanceof Error ? ingestError.message : "Unknown ingest error.");
    } finally {
      setIsIngesting(false);
    }
  }

  return (
    <main className="page-shell">
      <section className="hero-card">
        <div className="hero-header">
          <p className="eyebrow">Docs Copilot Demo</p>
          <span className={`mode-badge ${health?.mode ?? "offline"}`}>
            {health?.mode ?? "offline"}
          </span>
        </div>
        <h1>Ask the seeded docs a question</h1>
        <p className="lede">
          This demo retrieves markdown chunks from Chroma, builds a grounded prompt, and renders a
          validated structured answer from FastAPI.
        </p>
      </section>

      <section className="panel">
        <div className="toolbar">
          <div>
            <h2>Seeded Docs</h2>
            <p className="toolbar-copy">Embed the markdown docs into Chroma before asking questions.</p>
          </div>
          <button type="button" className="secondary-button" onClick={handleIngest} disabled={isIngesting}>
            {isIngesting ? "Ingesting..." : "Ingest Seed Docs"}
          </button>
        </div>

        {ingestResult ? (
          <div className="status-banner">
            Indexed {ingestResult.documents} documents into {ingestResult.chunks} chunks.
          </div>
        ) : null}

        <form className="question-form" onSubmit={handleSubmit}>
          <label className="field">
            <span>Question</span>
            <textarea
              value={question}
              rows={5}
              onChange={(event) => setQuestion(event.target.value)}
              placeholder="Ask about the seeded docs"
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
            {isLoading ? "Asking..." : "Ask Docs"}
          </button>
        </form>

        {error ? <div className="error-banner">{error}</div> : null}
      </section>

      <section className="panel result-panel">
        <div className="panel-header">
          <h2>Structured Answer</h2>
          {result ? <span className={`confidence ${result.answer.confidence}`}>{result.answer.confidence}</span> : null}
        </div>

        {result ? (
          <div className="result-grid">
            <article className="answer-card">
              <h3>Answer</h3>
              <p>{result.answer.answer}</p>
              <h3>Summary</h3>
              <p>{result.answer.summary}</p>
            </article>

            <aside className="citations-card">
              <h3>Citations</h3>
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
            Submit a question to render the validated answer payload from the backend.
          </p>
        )}
      </section>

      <section className="panel">
        <div className="panel-header">
          <h2>Debug</h2>
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
              <h3>Prompt Preview</h3>
              <pre>{result.debug.prompt_preview ?? "No prompt preview available."}</pre>
            </article>
          </div>
        ) : (
          <p className="empty-state">Debug details will appear after the first successful question.</p>
        )}
      </section>

      <section className="panel">
        <div className="panel-header">
          <h2>Retrieved Chunks</h2>
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
          <p className="empty-state">Retrieved chunks will appear after a successful response.</p>
        )}
      </section>
    </main>
  );
}
