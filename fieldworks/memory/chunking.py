"""Text chunking — pure functions, no I/O, no format awareness.

Splits already-extracted plain text into overlapping chunks for embedding.
Callers handle document format (PDF/markdown/etc.); this module only ever
sees flat text.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_PARAGRAPH_RE = re.compile(r"\n\s*\n")
_SENTENCE_RE = re.compile(r"(?<=[.!?])\s+")


@dataclass(frozen=True)
class Chunk:
    text: str
    index: int
    start_char: int
    end_char: int


def chunk_text(
    text: str, *, chunk_size: int = 800, chunk_overlap: int = 150
) -> list[Chunk]:
    """Split text into overlapping chunks no larger than chunk_size chars.

    Splits on paragraph boundaries first. Paragraphs still over chunk_size
    are split on sentence boundaries; sentences still over chunk_size fall
    back to a raw character-window slice. chunk_overlap chars of trailing
    context from one chunk are prepended to the next so a fact split across
    a boundary still appears whole in at least one chunk.
    """
    if chunk_overlap >= chunk_size:
        raise ValueError("chunk_overlap must be smaller than chunk_size")

    text = text.strip()
    if not text:
        return []

    units = _split_paragraphs(text, chunk_size)
    return _pack(units, text, chunk_size, chunk_overlap)


def _split_paragraphs(text: str, chunk_size: int) -> list[str]:
    units: list[str] = []
    for para in _PARAGRAPH_RE.split(text):
        para = para.strip()
        if not para:
            continue
        if len(para) <= chunk_size:
            units.append(para)
            continue
        units.extend(_split_sentences(para, chunk_size))
    return units


def _split_sentences(para: str, chunk_size: int) -> list[str]:
    units: list[str] = []
    for sentence in _SENTENCE_RE.split(para):
        sentence = sentence.strip()
        if not sentence:
            continue
        if len(sentence) <= chunk_size:
            units.append(sentence)
        else:
            units.extend(
                sentence[i : i + chunk_size]
                for i in range(0, len(sentence), chunk_size)
            )
    return units


def _pack(
    units: list[str], text: str, chunk_size: int, chunk_overlap: int
) -> list[Chunk]:
    """Greedily pack units (paragraphs/sentences) into chunk_size-bounded
    chunks, carrying chunk_overlap trailing chars forward between chunks.
    """
    chunks: list[Chunk] = []
    current = ""
    for unit in units:
        candidate = f"{current} {unit}".strip() if current else unit
        if len(candidate) <= chunk_size or not current:
            current = candidate
        else:
            chunks.append(current)
            carry = current[-chunk_overlap:] if chunk_overlap else ""
            carried = f"{carry} {unit}".strip() if carry else unit
            current = carried if len(carried) <= chunk_size else unit
    if current:
        chunks.append(current)

    result: list[Chunk] = []
    search_from = 0
    for i, chunk_str in enumerate(chunks):
        start = text.find(chunk_str, max(0, search_from - len(chunk_str)))
        if start == -1:
            start = search_from
        end = start + len(chunk_str)
        result.append(Chunk(text=chunk_str, index=i, start_char=start, end_char=end))
        search_from = end
    return result
