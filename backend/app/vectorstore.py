from __future__ import annotations

from chromadb import PersistentClient
from chromadb.api.models.Collection import Collection

from app.config import settings


def get_chroma_collection() -> Collection:
    client = PersistentClient(path=str(settings.chroma_dir))
    return client.get_or_create_collection(name=settings.chroma_collection_name)
