"""Tests for pure text chunking."""

import pytest


def test_empty_text_returns_no_chunks():
    from fieldworks.memory.chunking import chunk_text

    assert chunk_text("") == []
    assert chunk_text("   \n\n  ") == []


def test_short_text_is_a_single_chunk():
    from fieldworks.memory.chunking import chunk_text

    chunks = chunk_text("A short paragraph about pump maintenance.")
    assert len(chunks) == 1
    assert chunks[0].text == "A short paragraph about pump maintenance."
    assert chunks[0].index == 0


def test_long_text_splits_into_multiple_chunks():
    from fieldworks.memory.chunking import chunk_text

    paragraphs = [f"Paragraph {i}. " + ("word " * 40) for i in range(10)]
    text = "\n\n".join(paragraphs)

    chunks = chunk_text(text, chunk_size=200, chunk_overlap=50)

    assert len(chunks) > 1
    for c in chunks:
        assert len(c.text) <= 200 + 50  # overlap carry can push slightly over
    assert [c.index for c in chunks] == list(range(len(chunks)))


def test_chunk_overlap_must_be_smaller_than_chunk_size():
    from fieldworks.memory.chunking import chunk_text

    with pytest.raises(ValueError):
        chunk_text("some text", chunk_size=100, chunk_overlap=100)


def test_oversized_single_sentence_falls_back_to_character_window():
    from fieldworks.memory.chunking import chunk_text

    text = "x" * 500  # one giant "sentence", no paragraph/sentence breaks
    chunks = chunk_text(text, chunk_size=100, chunk_overlap=20)
    assert len(chunks) >= 5
    assert all(len(c.text) <= 100 for c in chunks)
