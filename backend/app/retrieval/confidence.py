from app.config import get_settings


def label_for_score(score: float, caps: list[str] | None = None) -> str:
    settings = get_settings()
    caps = caps or []
    if score >= settings.confidence_high:
        label = "high"
    elif score >= settings.confidence_medium:
        label = "medium"
    else:
        label = "low"
    if caps and label == "high":
        label = "medium"
    return label


def combine_confidence(
    *,
    retrieval_relevance: float,
    source_quality: float,
    evidence_coverage: float,
    consistency: float,
    groundedness: float,
    caps: list[str] | None = None,
    notes: list[str] | None = None,
) -> dict:
    settings = get_settings()
    components = {
        "retrieval_relevance": round(_clamp(retrieval_relevance), 4),
        "source_quality": round(_clamp(source_quality), 4),
        "evidence_coverage": round(_clamp(evidence_coverage), 4),
        "consistency": round(_clamp(consistency), 4),
        "groundedness": round(_clamp(groundedness), 4),
    }
    weights = {
        "retrieval_relevance": 0.30,
        "source_quality": 0.20,
        "evidence_coverage": 0.25,
        "consistency": 0.15,
        "groundedness": 0.10,
    }
    score = sum(components[name] * weight for name, weight in weights.items())
    score = round(_clamp(score), 4)
    caps = caps or []
    label = label_for_score(score, caps)
    explanation = (
        "Heuristic score assembled from retrieval relevance, source quality, evidence coverage, "
        "consistency, and groundedness. It is not a calibrated probability, and cosine similarity "
        "was not converted into a probability. "
        f"Illustrative bands: high >= {settings.confidence_high:.2f}, "
        f"medium >= {settings.confidence_medium:.2f}, low below that. "
        "Adjust the bands after evaluation on labeled data."
    )
    if caps:
        explanation += " Label capped at medium because: " + ", ".join(caps) + "."
    if notes:
        explanation += " " + " ".join(notes)
    return {
        "score": score,
        "label": label,
        "heuristic": True,
        "calibrated": False,
        "components": components,
        "weights": weights,
        "thresholds": {
            "high": settings.confidence_high,
            "medium": settings.confidence_medium,
            "note": "illustrative until calibrated",
        },
        "caps": caps,
        "explanation": explanation,
    }


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, float(value)))
