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
    chunk_size: int = Field(default=700, alias="CHUNK_SIZE")
    chunk_overlap: int = Field(default=120, alias="CHUNK_OVERLAP")
    retrieval_k: int = Field(default=4, alias="RETRIEVAL_K")

    @field_validator("chroma_dir", "seed_docs_dir", mode="before")
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
