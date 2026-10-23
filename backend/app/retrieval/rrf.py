def reciprocal_rank_fusion(
    rankings: dict[str, list[str]],
    weights: dict[str, float] | None = None,
    k: int = 60,
) -> list[dict]:
    """Fuse ranked lists with score = weight * 1/(k + rank). Rank is 1-based."""
    weights = weights or {}
    scores: dict[str, float] = {}
    parts: dict[str, dict] = {}
    for source, ids in rankings.items():
        weight = float(weights.get(source, 1.0))
        for rank, doc_id in enumerate(ids, start=1):
            contribution = weight * (1.0 / (k + rank))
            scores[doc_id] = scores.get(doc_id, 0.0) + contribution
            parts.setdefault(doc_id, {})
            parts[doc_id][source] = {"rank": rank, "contribution": contribution}
    ordered = sorted(scores, key=lambda doc_id: scores[doc_id], reverse=True)
    return [
        {"id": doc_id, "rrf_score": scores[doc_id], "parts": parts[doc_id]}
        for doc_id in ordered
    ]
