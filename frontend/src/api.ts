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
  content: string;
  score?: number | null;
};

export type RetrievalDebug = {
  query: string;
  top_k: number;
  system_prompt: string;
  user_prompt: string;
  retrieved_chunks: SourceChunk[];
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
};

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "http://127.0.0.1:8000";

export type IngestResponse = {
  documents: number;
  chunks: number;
};

export async function askDocs(question: string, topK?: number): Promise<AskResponse> {
  const response = await fetch(`${API_BASE_URL}/ask`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      question,
      top_k: topK,
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

export async function getHealth(): Promise<HealthResponse> {
  const response = await fetch(`${API_BASE_URL}/health`);

  if (!response.ok) {
    throw new Error(`Health request failed with status ${response.status}`);
  }

  return (await response.json()) as HealthResponse;
}
