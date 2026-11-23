from __future__ import annotations

import math
from collections import Counter


def normalize(text: str | None) -> str:
    if not text:
        return ""
    return "".join(ch for ch in text.lower() if ch.isalnum())


def gram_counts(text: str | None) -> dict[str, int]:
    normalized = normalize(text)
    if len(normalized) < 2:
        return {normalized: 1} if normalized else {}
    return dict(Counter(normalized[i : i + 2] for i in range(len(normalized) - 1)))


def idf(gram: str, chunk_count: int, document_frequency: dict[str, int]) -> float:
    frequency = document_frequency.get(gram, 0)
    return math.log((chunk_count + 1.0) / (frequency + 1.0)) + 1.0


def lexical_ceiling(query_grams: dict[str, int], chunk_count: int, document_frequency: dict[str, int]) -> float:
    return sum(idf(gram, chunk_count, document_frequency) * 3 for gram in query_grams)


def lexical_score(
    query_grams: dict[str, int],
    chunk_grams: dict[str, int],
    chunk_count: int,
    document_frequency: dict[str, int],
    ceiling: float,
) -> float:
    if not query_grams or not chunk_grams or ceiling <= 0:
        return 0.0
    score = 0.0
    for gram in query_grams:
        frequency = chunk_grams.get(gram)
        if frequency is None:
            continue
        score += idf(gram, chunk_count, document_frequency) * min(frequency, 3)
    return score / ceiling


def cosine(left: list[float] | None, right: list[float] | None) -> float:
    if not left or not right or len(left) != len(right):
        return 0.0
    dot = sum(a * b for a, b in zip(left, right))
    left_norm = sum(a * a for a in left)
    right_norm = sum(b * b for b in right)
    if left_norm == 0 or right_norm == 0:
        return 0.0
    return dot / (math.sqrt(left_norm) * math.sqrt(right_norm))


def hybrid(cosine_score: float, lexical: float) -> float:
    if cosine_score <= 0:
        return lexical
    return 0.7 * cosine_score + 0.3 * lexical


def document_frequency(query_grams: dict[str, int], gram_sets: list[dict[str, int]]) -> dict[str, int]:
    result: dict[str, int] = {}
    for gram in query_grams:
        result[gram] = sum(1 for grams in gram_sets if gram in grams)
    return result
