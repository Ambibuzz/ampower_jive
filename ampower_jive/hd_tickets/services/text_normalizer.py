"""Plain-text normalization helpers for HD Tickets payloads."""

from __future__ import annotations

import html
import re
from typing import Any

SUMMARY_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")
LOW_SIGNAL_SUMMARY_RE = re.compile(
    r"^(?:dear\b|hi\b|hello\b|thanks\b|thank you\b|regards\b|kind regards\b|best regards\b|sincerely\b|yours\b)",
    re.IGNORECASE,
)


def to_plain_text(value: Any) -> str:
    """Convert rich HTML-ish ticket content into readable plain text."""
    text = str(value or "").strip()
    if not text:
        return ""

    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = re.sub(r"(?i)</(?:p|div|li|h[1-6]|tr|blockquote)>", "\n", text)
    text = re.sub(r"(?i)<li[^>]*>", "- ", text)
    text = re.sub(r"(?i)<blockquote[^>]*>", "", text)
    text = re.sub(r"(?i)<p[^>]*>", "", text)
    text = re.sub(r"(?i)<div[^>]*>", "", text)
    text = re.sub(r"<[^>]+>", "", text)
    text = html.unescape(text)
    text = text.replace("\r\n", "\n").replace("\xa0", " ")
    text = re.sub(r"\n{3,}", "\n\n", text)
    return "\n".join(line.strip() for line in text.split("\n") if line.strip()).strip()


def summarize_text_points(
    value: Any,
    *,
    max_points: int = 6,
    max_point_chars: int = 220,
) -> list[str]:
    """Return concise bullet-ready points from rich activity text."""
    text = to_plain_text(value)
    if not text:
        return []

    candidates: list[str] = []
    for block in text.split("\n"):
        normalized_block = _normalize_summary_fragment(block)
        if not normalized_block or _is_low_signal_summary_fragment(normalized_block):
            continue

        if ":" in normalized_block or len(normalized_block) <= max_point_chars:
            candidates.append(normalized_block)
            continue

        for sentence in SUMMARY_SENTENCE_SPLIT_RE.split(normalized_block):
            normalized_sentence = _normalize_summary_fragment(sentence)
            if normalized_sentence and not _is_low_signal_summary_fragment(normalized_sentence):
                candidates.append(normalized_sentence)

    points: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        normalized_key = re.sub(r"\s+", " ", candidate).strip().lower()
        if not normalized_key or normalized_key in seen:
            continue
        seen.add(normalized_key)
        points.append(_truncate_summary_fragment(candidate, max_point_chars))
        if len(points) >= max_points:
            return points

    if points:
        return points

    fallback = _truncate_summary_fragment(text.replace("\n", " "), max_point_chars)
    return [fallback] if fallback else []


def _normalize_summary_fragment(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip(" -\t\r\n")).strip()


def _is_low_signal_summary_fragment(value: str) -> bool:
    lowered = value.strip().lower()
    if not lowered:
        return True
    if LOW_SIGNAL_SUMMARY_RE.match(lowered):
        return True
    return lowered in {"support team", "dear support team", "[your name]", "your name"}


def _truncate_summary_fragment(value: str, max_chars: int) -> str:
    text = str(value or "").strip()
    if len(text) <= max_chars:
        return text
    truncated = text[: max_chars - 3].rstrip(" ,;:")
    return f"{truncated}..."
