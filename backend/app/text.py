"""Script segmentation and pronunciation customisation."""
from __future__ import annotations

import re
from dataclasses import dataclass

_SENT_END = re.compile(r"(?<=[.!?…。！？])[\"'”’)\]]*\s+(?=[\"'“‘(\[]?[A-ZÀ-ÖØ-Þ0-9¿¡])")
_ABBREV = {"mr.", "mrs.", "ms.", "dr.", "prof.", "sr.", "jr.", "st.", "vs.", "etc.", "e.g.", "i.e.", "no.", "fig."}


@dataclass
class Chunk:
    paragraph_index: int
    text: str


def word_count(text: str) -> int:
    return len(re.findall(r"\S+", text))


def split_paragraphs(text: str) -> list[str]:
    return [p.strip() for p in re.split(r"\n\s*\n", text.replace("\r\n", "\n")) if p.strip()]


def split_sentences(paragraph: str) -> list[str]:
    paragraph = re.sub(r"\s+", " ", paragraph).strip()
    if not paragraph:
        return []
    raw = _SENT_END.split(paragraph)
    out: list[str] = []
    for s in raw:
        if out and out[-1].split(" ")[-1].lower() in _ABBREV:
            out[-1] = f"{out[-1]} {s}"
        else:
            out.append(s)
    return [s.strip() for s in out if s.strip()]


def _split_long(sentence: str, max_chars: int) -> list[str]:
    if len(sentence) <= max_chars:
        return [sentence]
    parts: list[str] = []
    buf = ""
    for piece in re.split(r"(?<=[,;:—–])\s+", sentence):
        if len(piece) > max_chars:  # no punctuation to split on: fall back to words
            for w in piece.split(" "):
                if len(buf) + len(w) + 1 > max_chars and buf:
                    parts.append(buf)
                    buf = w
                else:
                    buf = f"{buf} {w}".strip()
            continue
        if len(buf) + len(piece) + 1 > max_chars and buf:
            parts.append(buf)
            buf = piece
        else:
            buf = f"{buf} {piece}".strip()
    if buf:
        parts.append(buf)
    return parts


def segment_script(text: str, max_chars: int = 400, min_chars: int = 25) -> list[Chunk]:
    """Paragraph -> sentence chunks. Very short sentences are merged with the next one in the
    same paragraph (single-word takes sound unnatural); very long ones are split at clause boundaries."""
    chunks: list[Chunk] = []
    for p_idx, para in enumerate(split_paragraphs(text)):
        sentences: list[str] = []
        for s in split_sentences(para):
            sentences.extend(_split_long(s, max_chars))
        merged: list[str] = []
        for s in sentences:
            if merged and len(merged[-1]) < min_chars and len(merged[-1]) + len(s) + 1 <= max_chars:
                merged[-1] = f"{merged[-1]} {s}"
            else:
                merged.append(s)
        chunks.extend(Chunk(p_idx, s) for s in merged)
    return chunks


def apply_pronunciations(text: str, rules: list[dict]) -> str:
    """rules: [{"term": "GIF", "say": "jif", "case_sensitive": false}]. Whole-word replacement."""
    for r in rules or []:
        term, say = (r.get("term") or "").strip(), (r.get("say") or "").strip()
        if not term or not say:
            continue
        flags = 0 if r.get("case_sensitive") else re.IGNORECASE
        text = re.sub(rf"(?<!\w){re.escape(term)}(?!\w)", say, text, flags=flags)
    return text
