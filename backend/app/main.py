from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import ValidationError

from app.config import settings
from app.ingest import ingest_seed_docs
from app.llm import generate_structured_answer
from app.models import AskRequest, AskResponse, RetrievalDebug
from app.retrieval import retrieve_chunks
from app.vectorstore import get_chroma_collection_count


app = FastAPI(title="RAG Docs Copilot")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def healthcheck() -> dict[str, str | int | bool]:
    chunk_count = get_chroma_collection_count()
    return {
        "status": "ok",
        "collection": settings.chroma_collection_name,
        "mode": "demo" if settings.demo_mode else "openai",
        "chunk_count": chunk_count,
        "index_ready": chunk_count > 0,
    }


@app.post("/ingest")
def ingest_docs() -> dict[str, int]:
    if not settings.demo_mode and not settings.openai_api_key:
        raise HTTPException(status_code=500, detail="OPENAI_API_KEY is not configured.")

    return ingest_seed_docs()


@app.post("/ask", response_model=AskResponse)
def ask_docs(request: AskRequest) -> AskResponse:
    if not settings.demo_mode and not settings.openai_api_key:
        raise HTTPException(status_code=500, detail="OPENAI_API_KEY is not configured.")

    try:
        chunks = retrieve_chunks(question=request.question, top_k=request.top_k)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    if not chunks:
        raise HTTPException(status_code=404, detail="No chunks found. Ingest docs first.")

    try:
        answer, system_prompt, user_prompt = generate_structured_answer(
            question=request.question,
            chunks=chunks,
        )
    except ValidationError as exc:
        raise HTTPException(status_code=502, detail=f"Model output failed validation: {exc}") from exc
    except ValueError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    return AskResponse(
        answer=answer,
        debug=RetrievalDebug(
            query=request.question,
            top_k=request.top_k or settings.retrieval_k,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            retrieved_chunks=chunks,
        ),
    )
