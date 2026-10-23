import hashlib
import math
import re

from app.config import EMBEDDING_DIM, get_settings

LOCAL_EMBEDDING_MODEL = "local-hashed-ngram"
TOKEN_RE = re.compile(r"[a-z0-9]+")


def embedding_model_name() -> str:
    settings = get_settings()
    if settings.openai_configured():
        return settings.openai_embedding_model
    return LOCAL_EMBEDDING_MODEL


def vector_space_name() -> str:
    if embedding_model_name() == LOCAL_EMBEDDING_MODEL:
        return "hashed-ngram-lexical"
    return "openai-semantic"


def hashed_ngram_embed(text: str, dim: int = EMBEDDING_DIM) -> list[float]:
    vector = [0.0] * dim
    tokens = TOKEN_RE.findall((text or "").lower()) or ["empty"]
    for token in tokens:
        digest = hashlib.blake2b(token.encode(), digest_size=8).digest()
        bucket = int.from_bytes(digest[:4], "little") % dim
        sign = 1.0 if digest[4] % 2 == 0 else -1.0
        vector[bucket] += sign * 2.0
        padded = f"#{token}#"
        for size in (3, 4):
            if len(padded) < size:
                continue
            for index in range(len(padded) - size + 1):
                gram = padded[index : index + size]
                gdigest = hashlib.blake2b(gram.encode(), digest_size=8).digest()
                gbucket = int.from_bytes(gdigest[:4], "little") % dim
                gsign = 1.0 if gdigest[4] % 2 == 0 else -1.0
                vector[gbucket] += gsign
    norm = math.sqrt(sum(value * value for value in vector)) or 1.0
    return [value / norm for value in vector]


def embed_texts(texts: list[str]) -> tuple[list[list[float]], str]:
    settings = get_settings()
    if not texts:
        return [], embedding_model_name()
    if not settings.openai_configured():
        return [hashed_ngram_embed(text, settings.embedding_dimensions) for text in texts], LOCAL_EMBEDDING_MODEL
    from openai import OpenAI

    client = OpenAI(api_key=settings.openai_api_key)
    vectors: list[list[float] | None] = [None] * len(texts)
    batch_size = 64
    for start in range(0, len(texts), batch_size):
        batch = texts[start : start + batch_size]
        response = client.embeddings.create(
            model=settings.openai_embedding_model,
            input=batch,
            dimensions=settings.embedding_dimensions,
            encoding_format="float",
        )
        for item in response.data:
            vector = [float(value) for value in item.embedding]
            if len(vector) != settings.embedding_dimensions:
                raise RuntimeError(
                    f"Embedding dimension {len(vector)} does not match configured "
                    f"{settings.embedding_dimensions}."
                )
            vectors[start + item.index] = vector
    if any(vector is None for vector in vectors):
        raise RuntimeError("The embedding provider returned an incomplete batch.")
    return [vector for vector in vectors if vector is not None], settings.openai_embedding_model
