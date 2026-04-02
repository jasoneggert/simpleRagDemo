# RAG Docs Copilot Demo

Small full-stack RAG demo built with:
- FastAPI
- React + Vite + TypeScript
- Chroma
- OpenAI
- Pydantic

This repo supports two execution modes:
- `demo` mode: fully local deterministic embeddings and deterministic answer synthesis for free demos
- `openai` mode: OpenAI embeddings plus structured generation

## What This App Demonstrates

This app demonstrates the core RAG loop:

1. Ingest markdown docs
2. Chunk docs into semantically meaningful sections
3. Embed chunks into vectors
4. Store vectors in Chroma
5. Embed a user question
6. Retrieve top-k nearest chunks
7. Assemble a grounded prompt
8. Generate a structured answer
9. Validate the output
10. Render answer, citations, retrieved chunks, and debug info

## Architecture Diagram

```mermaid
flowchart TD
    A["User in Browser<br/>React + Vite + TypeScript"] --> B["Frontend UI<br/>Question form, Top K input, Ingest button,<br/>mode badge, answer panel, debug panel"]
    B --> C["HTTP calls to FastAPI<br/>GET /health<br/>POST /ingest<br/>POST /ask"]

    subgraph Frontend["Frontend"]
        B1["App.tsx<br/>State + rendering"] --> B2["api.ts<br/>fetch wrappers + TS types"]
        B2 --> B
    end

    C --> D["FastAPI app<br/>backend/app/main.py"]

    subgraph Health["Health Path"]
        D --> H1["GET /health"]
        H1 --> H2["Returns status, collection name,<br/>and mode: demo or openai"]
    end

    subgraph Ingest["Ingest Path"]
        D --> I1["POST /ingest"]
        I1 --> I2{"demo_mode?"}
        I2 -->|true| I3["No OpenAI key required"]
        I2 -->|false| I4["Require OPENAI_API_KEY"]
        I3 --> I5["ingest_seed_docs()"]
        I4 --> I5
        I5 --> I6["Load markdown files from docs/seed"]
        I6 --> I7["Chunk each document"]
        I7 --> I8["Embed each chunk"]
        I8 --> I9["Reset Chroma collection"]
        I9 --> I10["Upsert chunk text + embeddings + metadata"]
        I10 --> I11["Return documents count + chunks count"]
    end

    subgraph Ask["Question Answering Path"]
        D --> Q1["POST /ask"]
        Q1 --> Q2{"demo_mode?"}
        Q2 -->|true| Q3["No OpenAI key required"]
        Q2 -->|false| Q4["Require OPENAI_API_KEY"]
        Q3 --> Q5["Retrieve top-k chunks"]
        Q4 --> Q5
        Q5 --> Q6["Embed the user question"]
        Q6 --> Q7["Query Chroma nearest neighbors"]
        Q7 --> Q8["Return top-k chunks with metadata + distances"]
        Q8 --> Q9["Build prompts"]
        Q9 --> Q10{"demo_mode?"}
        Q10 -->|true| Q11["Deterministic answer builder"]
        Q10 -->|false| Q12["OpenAI structured output generation"]
        Q11 --> Q13["Validate final response with Pydantic"]
        Q12 --> Q13
        Q13 --> Q14["Return answer + citations + prompts + retrieved chunks"]
    end

    subgraph Chunking["Chunking"]
        I7 --> K1["Normalize markdown whitespace"]
        K1 --> K2["Split file into sections by headings"]
        K2 --> K3["For each section:<br/>collect body paragraphs"]
        K3 --> K4["If a paragraph is too large,<br/>split by sentence, then words if needed"]
        K4 --> K5["Pack paragraphs into chunks<br/>until token budget is reached"]
        K5 --> K6["Preserve overlap using trailing paragraphs<br/>up to overlap token budget"]
        K6 --> K7["Prefix chunk text with heading"]
        K7 --> K8["Assign chunk_id + metadata"]
    end

    subgraph Tokens["Token Counting"]
        K5 --> T1["tiktoken"]
        T1 --> T2["encoding_for_model(openai_embedding_model)"]
        T2 --> T3["Fallback: cl100k_base"]
        T3 --> T4["Chunk size and overlap are token budgets,<br/>not character counts"]
    end

    subgraph Embeddings["Embeddings"]
        I8 --> E1{"demo_mode?"}
        Q6 --> E1
        E1 -->|true| E2["Local deterministic embedding function"]
        E1 -->|false| E3["OpenAI embeddings<br/>text-embedding-3-small by default"]
        E2 --> E4["Numeric vector per text"]
        E3 --> E4
    end

    subgraph VectorDB["Chroma"]
        E4 --> V1["Persistent local Chroma store"]
        V1 --> V2["Collection: docs-copilot"]
        V2 --> V3["Stores:<br/>id, text, embedding, metadata"]
        Q7 --> V4["Nearest-neighbor search"]
        V4 --> V5["Returns chunk ids, documents,<br/>metadata, distances"]
    end

    subgraph Prompting["Prompt Construction"]
        Q9 --> P1["System prompt"]
        Q9 --> P2["User prompt"]
        P1 --> P3["Tell model to answer only from docs,<br/>return structured JSON,<br/>set low/medium/high confidence"]
        P2 --> P4["Instruction block"]
        P4 --> P5["Question block"]
        P5 --> P6["Retrieved context block"]
        P6 --> P7["Each context entry includes:<br/>chunk_id, title, heading, chunk text"]
    end

    subgraph Generation["Answer Generation"]
        Q12 --> G1["OpenAI Responses API parse()"]
        G1 --> G2["Model outputs structured object"]
        G2 --> G3["Citations reference chunk_id values"]
        Q11 --> G4["Demo mode synthesizes answer from top chunks"]
        G4 --> G5["Builds summary + citations deterministically"]
    end

    subgraph Validation["Validation"]
        Q13 --> R1["Pydantic response models"]
        R1 --> R2["AnswerPayload"]
        R1 --> R3["Citation list"]
        R1 --> R4["RetrievalDebug"]
        R3 --> R5["Citations are mapped back to retrieved chunk metadata"]
    end

    subgraph UIResult["UI Rendering"]
        Q14 --> U1["Frontend receives JSON"]
        U1 --> U2["Render confidence badge"]
        U1 --> U3["Render answer and summary"]
        U1 --> U4["Render citations"]
        U1 --> U5["Render retrieved chunks"]
        U1 --> U6["Render system prompt"]
        U1 --> U7["Render user prompt"]
        U1 --> U8["Render mode badge from /health"]
    end
```

## End-To-End Flow

```text
[1] User opens the app
    |
    +--> Frontend calls GET /health
          |
          +--> Backend returns:
               - status
               - Chroma collection name
               - mode = "demo" or "openai"
          |
          +--> UI shows mode badge

[2] User clicks "Ingest Seed Docs"
    |
    +--> Frontend POST /ingest
          |
          +--> Backend loads markdown files from docs/seed/
          |
          +--> Each file is chunked:
               - split by markdown headings
               - split section bodies into paragraphs
               - use true token counts via tiktoken
               - create overlapping token-bounded chunks
               - avoid heading-only fragments
          |
          +--> Each chunk is embedded:
               - demo mode: local deterministic vector
               - openai mode: embedding API
          |
          +--> Backend recreates the Chroma collection
          |
          +--> Chroma stores:
               - chunk id
               - chunk text
               - vector embedding
               - metadata:
                 - document id
                 - source path
                 - title
                 - heading
          |
          +--> Backend returns document/chunk counts
          |
          +--> UI shows ingest success banner

[3] User asks a question
    |
    +--> Frontend POST /ask with:
          - question
          - top_k
    |
    +--> Backend embeds the question
          |
          +--> same embedding strategy as ingest
    |
    +--> Backend queries Chroma:
          - nearest-neighbor search
          - returns top-k chunks
          - includes distances
    |
    +--> Backend builds prompts:
          - System prompt:
            "answer from docs only, structured JSON, confidence label"
          - User prompt:
            - instruction block
            - question block
            - retrieved context block
            - each context block includes chunk_id/title/heading/content
    |
    +--> Answer generation:
          - demo mode:
            deterministic summary from retrieved chunks
          - openai mode:
            model generates structured JSON
    |
    +--> Backend validates output with Pydantic
          |
          +--> ensures response schema is stable
          +--> citations match retrieved chunk ids
    |
    +--> Backend returns:
          - answer
          - summary
          - citations
          - confidence
          - retrieved chunks
          - system prompt
          - user prompt
    |
    +--> Frontend renders:
          - answer panel
          - citations
          - retrieved chunks
          - full prompt debug blocks
```

## Visual Retrieval Model

```text
Seed docs
  |
  v
[Chunk 1] --embed--> [vector 1] \
[Chunk 2] --embed--> [vector 2]  \
[Chunk 3] --embed--> [vector 3]   > stored in Chroma
[Chunk 4] --embed--> [vector 4]  /
                                /
User question
  |
  +--embed--> [query vector]
                  |
                  v
        Chroma nearest-neighbor search
                  |
                  v
      top-k most similar chunk vectors
                  |
                  v
      corresponding chunk texts + metadata
```

## Prompt Structure

The app now exposes both prompt layers in the UI.

### System Prompt

Controls model behavior:
- answer questions about local markdown docs
- return structured JSON
- use only supplied context
- set `low`, `medium`, or `high` confidence

### User Prompt

Contains:
- task instructions
- the user question
- the retrieved chunks

Conceptually:

```text
SYSTEM:
You answer questions about local markdown docs.
Produce structured JSON matching the schema.
Use only the supplied context.
Set confidence to low, medium, or high.

USER:
Use only the retrieved context to answer the question.
If the context is insufficient, say so explicitly.
Return citations only for chunks that directly support the answer.

Question:
<user question>

Retrieved context:
[chunk_id=... ] title=... | heading=...
<chunk text>
```

## Modes

### Demo Mode

Enabled by setting:

```env
DEMO_MODE=true
```

Behavior:
- no OpenAI key required
- embeddings are local and deterministic
- answer generation is deterministic
- Chroma vector retrieval is still real

This is good for:
- free demos
- architecture walkthroughs
- UI/debug demonstrations

### OpenAI Mode

Enabled by setting:

```env
DEMO_MODE=false
OPENAI_API_KEY=...
```

Behavior:
- chunk embeddings use OpenAI
- answer generation uses OpenAI structured output parsing

This is the stronger demonstration of actual generation quality.

## Confidence And Scores

### Confidence

The `confidence` label is answer-level confidence, not retrieval distance.

- in `openai` mode: the model sets it
- in `demo` mode: it is assigned deterministically

### Chunk Score

The chunk `score` shown in the UI is Chroma distance.

Important:
- lower is better
- it is not a probability
- it is not answer confidence

## Top K

`Top K` is the number of chunks retrieved for a question.

Effects:
- lower `k`: smaller context, lower cost, less noise
- higher `k`: more coverage, larger context, potentially more noise

Current default:
- `4`

## Running The App

### Backend

```bash
cd /Users/jasoneggert/misc/docCopilot
./.venv/bin/python -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8000
```

### Frontend

```bash
cd /Users/jasoneggert/misc/docCopilot/frontend
npm run dev
```

Open:
- <http://127.0.0.1:5173>

## Demo Flow

1. Open the app
2. Confirm the mode badge says `demo` or `openai`
3. Click `Ingest Seed Docs`
4. Ask a question
5. Walk through:
   - answer
   - citations
   - retrieved chunks
   - system prompt
   - user prompt

## Good Demo Questions

- `What should a RAG UI show to help developers understand why an answer was generated?`
- `How should structured JSON answers be validated before the frontend renders them?`
- `What error response behavior do the docs recommend for validation errors versus server errors?`
- `How does retrieval-augmented generation work in this demo?`
- `What should citations contain in the UI?`

## Repo Notes

The repo intentionally ignores local and generated files such as:
- `.env`
- `.venv/`
- `.pycache/`
- `.chroma/`
- `frontend/node_modules/`
- `frontend/dist/`

This keeps the committed history focused on source code and configuration templates.
