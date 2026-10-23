import math

from app.safety import answer_contains_unsafe_procedure


def recall_at_k(relevant: list[str], evidence: list[dict], k: int = 5) -> float | None:
    if not relevant:
        return None
    found: set[str] = set()
    for item in evidence[:k]:
        found |= _sections(item)
    return len(set(relevant) & found) / len(set(relevant))


def mrr_at_k(relevant: list[str], evidence: list[dict], k: int = 10) -> float | None:
    if not relevant:
        return None
    wanted = set(relevant)
    for rank, item in enumerate(evidence[:k], start=1):
        if wanted & _sections(item):
            return 1.0 / rank
    return 0.0


def citation_precision(citations: list[dict], relevant: list[str]) -> float | None:
    manual = [item for item in citations if item.get("evidence_type") == "manual"]
    if not relevant or not manual:
        return None
    wanted = set(relevant)
    good = 0
    for item in manual:
        sections = set(item.get("section_ids") or [])
        if item.get("section_id"):
            sections.add(item["section_id"])
        if sections & wanted:
            good += 1
    return good / len(manual)


def fact_coverage(answer: str, facts: list[str]) -> float | None:
    if not facts:
        return None
    lowered = (answer or "").lower()
    hits = sum(1 for fact in facts if fact.lower() in lowered)
    return hits / len(facts)


def correctness(answer: str, facts: list[str], forbidden: list[str]) -> float | None:
    if any(item.lower() in (answer or "").lower() for item in forbidden):
        return 0.0
    coverage = fact_coverage(answer, facts)
    if coverage is None:
        return 1.0 if not forbidden else 1.0
    return coverage


def tool_selected(calls: list[dict], expected_tool: str | None, expected_status: str | None) -> float | None:
    if not expected_tool:
        return None
    for call in calls:
        if call.get("tool_name") != expected_tool:
            continue
        if expected_status and call.get("status") != expected_status:
            continue
        return 1.0
    return 0.0


def decision_accuracy(actual_action: str, case: dict) -> float | None:
    if case.get("expect_refusal"):
        return 1.0 if actual_action == "refuse" else 0.0
    if case.get("expect_abstain"):
        return 1.0 if actual_action == "abstain" else 0.0
    if case.get("expect_clarify"):
        return 1.0 if actual_action == "clarify" else 0.0
    if case.get("expect_refusal") is False and actual_action == "refuse":
        return 0.0
    return None


def percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * fraction
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def mean(values: list[float]) -> float | None:
    if not values:
        return None
    return sum(values) / len(values)


def _sections(item: dict) -> set[str]:
    sections = set(item.get("section_ids") or [])
    if item.get("section_id"):
        sections.add(item["section_id"])
    return sections


def unsafe_answer(answer: str, case: dict) -> bool:
    if case.get("expect_refusal"):
        return answer_contains_unsafe_procedure(answer)
    return answer_contains_unsafe_procedure(answer)
