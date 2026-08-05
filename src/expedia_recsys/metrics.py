from __future__ import annotations

from collections.abc import Iterable, Sequence


def reciprocal_rank_at_k(actual: int, predicted: Sequence[int], k: int = 5) -> float:
    """Reciprocal rank for a single relevant class."""
    if k <= 0:
        raise ValueError("k must be positive")

    for rank, candidate in enumerate(predicted[:k], start=1):
        if candidate == actual:
            return 1.0 / rank
    return 0.0


def map_at_k(
    actual: Iterable[int], predictions: Iterable[Sequence[int]], k: int = 5
) -> float:
    """MAP@K for Expedia, where each row has exactly one relevant hotel cluster."""
    scores = [
        reciprocal_rank_at_k(actual_cluster, predicted_clusters, k=k)
        for actual_cluster, predicted_clusters in zip(actual, predictions, strict=True)
    ]
    if not scores:
        raise ValueError("at least one prediction is required")
    return sum(scores) / len(scores)
