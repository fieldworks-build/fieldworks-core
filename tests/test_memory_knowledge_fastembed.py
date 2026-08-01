"""Slow integration test against the real FastEmbedProvider. Downloads model
weights on first run. Excluded from the default suite: pytest -m "not slow".
"""

import pytest


@pytest.mark.slow
def test_relevant_chunk_outranks_irrelevant_chunk(tmp_path):
    from fieldworks.memory.embeddings import FastEmbedProvider
    from fieldworks.memory.knowledge import KnowledgeClient, KnowledgeConfig

    config = KnowledgeConfig(db_path=tmp_path / "knowledge.duckdb")
    client = KnowledgeClient(config, FastEmbedProvider())

    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "pump.txt").write_text(
        "The raw water intake pump must not exceed 250 gallons per minute of"
        " sustained flow. Operating above this limit risks cavitation damage"
        " to the impeller."
    )
    (docs / "safety.txt").write_text(
        "All personnel must wear hearing protection in the pump room."
        " Lockout-tagout procedures apply before any maintenance."
    )

    client.ingest_directory(docs)
    excerpts = client.query(
        "what is the maximum flow rate for the intake pump?", top_k=2
    )

    assert excerpts[0].source.endswith("pump.txt")
    assert excerpts[0].score > excerpts[1].score
