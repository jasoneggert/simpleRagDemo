from __future__ import annotations

import hashlib
import math
import re

from openai import OpenAI

from app.config import settings


TOKEN_PATTERN = re.compile(r"[a-zA-Z0-9]+")
DEMO_EMBEDDING_DIM = 256


def _tokenize(text: str) -> list[str]:
    return TOKEN_PATTERN.findall(text.lower())


def _demo_embedding(text: str) -> list[float]:
    vector = [0.0] * DEMO_EMBEDDING_DIM
    for token in _tokenize(text):
        digest = hashlib.sha256(token.encode("utf-8")).digest()
        index = int.from_bytes(digest[:4], "big") % DEMO_EMBEDDING_DIM
        sign = 1.0 if digest[4] % 2 == 0 else -1.0
        vector[index] += sign

    norm = math.sqrt(sum(value * value for value in vector))
    if norm == 0:
        return vector
    return [value / norm for value in vector]


def embed_texts(texts: list[str]) -> list[list[float]]:
    if settings.demo_mode:
        return [_demo_embedding(text) for text in texts]

    client = OpenAI(api_key=settings.openai_api_key)
    response = client.embeddings.create(
        model=settings.openai_embedding_model,
        input=texts,
    )
    return [item.embedding for item in response.data]
