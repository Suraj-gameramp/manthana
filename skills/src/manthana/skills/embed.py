"""Embeddings for skill mining.

Research-grounded: neural sentence embeddings (e.g. BAAI/bge-large-en-v1.5)
outperform bag-of-words for short-text clustering, used with cosine similarity on
L2-normalized vectors (sentence-transformers docs; IEEE 9640285). The model is an
OPTIONAL extra (torch is heavy); a deterministic dependency-free ``HashingEmbedder``
keeps the clustering core testable on CI and serves as a fallback.

SPDX-License-Identifier: Apache-2.0
"""

from __future__ import annotations

import hashlib
import math
import re
from typing import Protocol, runtime_checkable

Vector = list[float]

DEFAULT_MODEL = "BAAI/bge-large-en-v1.5"  # decisions doc default
_TOKEN_RE = re.compile(r"[a-z0-9]+")


@runtime_checkable
class Embedder(Protocol):
    dim: int

    def embed(self, texts: list[str]) -> list[Vector]:
        """Return one L2-normalized vector per input text."""
        ...


def _l2_normalize(vec: Vector) -> Vector:
    norm = math.sqrt(sum(x * x for x in vec))
    if norm == 0.0:
        return vec
    return [x / norm for x in vec]


def cosine(a: Vector, b: Vector) -> float:
    """Cosine similarity. Inputs are expected L2-normalized (then this is the dot
    product), but the full formula is used so unnormalized inputs are still safe."""
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(x * x for x in b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (na * nb)


class HashingEmbedder:
    """Deterministic, dependency-free embedder (hashing trick over tokens).

    Not semantically rich, but stable and offline: similar texts (shared tokens)
    get similar vectors, which is enough to exercise + test the clustering core
    and to degrade gracefully when sentence-transformers isn't installed.
    """

    def __init__(self, dim: int = 256) -> None:
        self.dim = dim

    def embed(self, texts: list[str]) -> list[Vector]:
        out: list[Vector] = []
        for text in texts:
            vec = [0.0] * self.dim
            for token in _TOKEN_RE.findall(text.lower()):
                if len(token) < 2:
                    continue
                # Stable bucket from a hash of the WHOLE token (blake2b, not
                # Python's salted hash). Hashing the raw bytes would collapse to
                # the first byte, so distinct tokens must hash distinctly.
                digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
                bucket = int.from_bytes(digest, "big") % self.dim
                vec[bucket] += 1.0
            out.append(_l2_normalize(vec))
        return out


class SentenceTransformerEmbedder:
    """bge-large (or any sentence-transformers model). Requires the ``embeddings``
    extra (``uv sync --extra embeddings``)."""

    def __init__(self, model: str = DEFAULT_MODEL) -> None:
        from sentence_transformers import SentenceTransformer  # type: ignore[import-not-found]

        self._model = SentenceTransformer(model)
        self.dim = int(self._model.get_sentence_embedding_dimension() or 0)

    def embed(self, texts: list[str]) -> list[Vector]:
        vectors = self._model.encode(texts, normalize_embeddings=True)
        return [[float(x) for x in row] for row in vectors]


def default_embedder(model: str | None = None) -> Embedder:
    """sentence-transformers if installed, else the deterministic hashing fallback."""
    try:
        return SentenceTransformerEmbedder(model or DEFAULT_MODEL)
    except Exception:  # noqa: BLE001 - extra not installed / model unavailable
        return HashingEmbedder()


__all__ = [
    "Vector",
    "Embedder",
    "HashingEmbedder",
    "SentenceTransformerEmbedder",
    "default_embedder",
    "cosine",
    "DEFAULT_MODEL",
]
