"""Tests for the FakeEmbeddingProvider test double."""


def test_dimension_matches_configured_value():
    from fieldworks.memory.embeddings import FakeEmbeddingProvider

    provider = FakeEmbeddingProvider(dimension=32)
    assert provider.dimension == 32
    vectors = provider.embed(["hello"])
    assert len(vectors[0]) == 32


def test_embed_is_deterministic():
    from fieldworks.memory.embeddings import FakeEmbeddingProvider

    provider = FakeEmbeddingProvider(dimension=16)
    a = provider.embed(["pump cavitation"])
    b = provider.embed(["pump cavitation"])
    assert a == b


def test_different_texts_produce_different_vectors():
    from fieldworks.memory.embeddings import FakeEmbeddingProvider

    provider = FakeEmbeddingProvider(dimension=16)
    a, b = provider.embed(["pump cavitation", "chlorine dosing setpoint"])
    assert a != b


def test_vectors_are_not_degenerate():
    """Not all-zero/constant — needed for cosine distance to be meaningful."""
    from fieldworks.memory.embeddings import FakeEmbeddingProvider

    provider = FakeEmbeddingProvider(dimension=16)
    (vec,) = provider.embed(["some text"])
    assert len(set(round(v, 6) for v in vec)) > 1
