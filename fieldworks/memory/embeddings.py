"""Embedding providers for the knowledge/RAG layer.

FastEmbedProvider (local ONNX, no API key, on-prem friendly) is the
framework default. EmbeddingProvider is a Protocol, not an ABC — swap in
Voyage AI or another provider by implementing embed()/dimension, no
inheritance required. FakeEmbeddingProvider is a deterministic test double,
shipped here (not test-only) so downstream deployments can unit-test their
own KnowledgeClient wiring without downloading model weights.
"""

from __future__ import annotations

import hashlib
from typing import Protocol, runtime_checkable


@runtime_checkable
class EmbeddingProvider(Protocol):
    dimension: int

    def embed(self, texts: list[str]) -> list[list[float]]:
        """Return one embedding vector per input text, same order."""
        ...


class FastEmbedProvider:
    """Local ONNX embeddings via fastembed. No API key, no network after the
    one-time model download. Requires the `knowledge` extra:
    pip install fieldworks-core[knowledge]
    """

    def __init__(self, model_name: str = "BAAI/bge-small-en-v1.5"):
        try:
            from fastembed import TextEmbedding
        except ImportError as exc:
            raise ImportError(
                "FastEmbedProvider requires the 'knowledge' extra:"
                " pip install fieldworks-core[knowledge]"
            ) from exc

        self._model = TextEmbedding(model_name=model_name)
        self.dimension = len(next(self._model.embed(["dimension probe"])))

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [vec.tolist() for vec in self._model.embed(texts)]


class FakeEmbeddingProvider:
    """Deterministic sha256-derived unit vectors. No model weights, no
    network. Real distance variation (not degenerate/constant), so
    similarity-ordered query tests are meaningful.
    """

    def __init__(self, dimension: int = 16):
        self.dimension = dimension

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._vec(t) for t in texts]

    def _vec(self, text: str) -> list[float]:
        digest = hashlib.sha256(text.encode()).digest()
        raw = [digest[i % len(digest)] / 255.0 + 0.01 for i in range(self.dimension)]
        norm = sum(x * x for x in raw) ** 0.5
        return [x / norm for x in raw]
