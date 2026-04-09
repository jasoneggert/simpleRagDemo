from pathlib import Path

from pydantic import Field
from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


ROOT_DIR = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    demo_mode: bool = Field(default=False, alias="DEMO_MODE")
    openai_api_key: str = Field(default="", alias="OPENAI_API_KEY")
    openai_chat_model: str = Field(default="gpt-4.1-mini", alias="OPENAI_CHAT_MODEL")
    openai_embedding_model: str = Field(
        default="text-embedding-3-small",
        alias="OPENAI_EMBEDDING_MODEL",
    )
    chroma_dir: Path = Field(default=ROOT_DIR / ".chroma", alias="CHROMA_DIR")
    chroma_collection_name: str = Field(
        default="docs-copilot",
        alias="CHROMA_COLLECTION_NAME",
    )
    seed_docs_dir: Path = Field(default=ROOT_DIR / "docs" / "seed", alias="SEED_DOCS_DIR")
    support_fixtures_path: Path = Field(
        default=ROOT_DIR / "backend" / "fixtures" / "billing_data.json",
        alias="SUPPORT_FIXTURES_PATH",
    )
    support_operators_path: Path = Field(
        default=ROOT_DIR / "backend" / "fixtures" / "operators.json",
        alias="SUPPORT_OPERATORS_PATH",
    )
    support_db_path: Path = Field(
        default=ROOT_DIR / "backend" / "fixtures" / "support.sqlite3",
        alias="SUPPORT_DB_PATH",
    )
    support_case_notes_dir: Path = Field(
        default=ROOT_DIR / "backend" / "fixtures" / "case-notes",
        alias="SUPPORT_CASE_NOTES_DIR",
    )
    support_case_state_dir: Path = Field(
        default=ROOT_DIR / "backend" / "fixtures" / "cases",
        alias="SUPPORT_CASE_STATE_DIR",
    )
    support_action_log_path: Path = Field(
        default=ROOT_DIR / "backend" / "fixtures" / "action-log.jsonl",
        alias="SUPPORT_ACTION_LOG_PATH",
    )
    support_observability_log_path: Path = Field(
        default=ROOT_DIR / "backend" / "fixtures" / "observability-log.jsonl",
        alias="SUPPORT_OBSERVABILITY_LOG_PATH",
    )
    chunk_size: int = Field(default=700, alias="CHUNK_SIZE")
    chunk_overlap: int = Field(default=120, alias="CHUNK_OVERLAP")
    retrieval_k: int = Field(default=4, alias="RETRIEVAL_K")
    agent_max_latency_ms: int = Field(default=20000, alias="AGENT_MAX_LATENCY_MS")
    agent_max_total_tokens: int = Field(default=5000, alias="AGENT_MAX_TOTAL_TOKENS")

    @field_validator(
        "chroma_dir",
        "seed_docs_dir",
        "support_fixtures_path",
        "support_operators_path",
        "support_db_path",
        "support_case_notes_dir",
        "support_case_state_dir",
        "support_action_log_path",
        "support_observability_log_path",
        mode="before",
    )
    @classmethod
    def resolve_project_relative_paths(cls, value: str | Path) -> Path:
        path_value = Path(value)
        if path_value.is_absolute():
            return path_value
        return ROOT_DIR / path_value

    model_config = SettingsConfigDict(
        env_file=ROOT_DIR / ".env",
        env_file_encoding="utf-8",
        populate_by_name=True,
    )


settings = Settings()
