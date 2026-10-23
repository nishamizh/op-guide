import re

from app.retrieval.bm25 import tokenize
from app.safety import answer_contains_unsafe_procedure, text_looks_like_injection

RESET_RE = re.compile(r"\b(reset|restart|power cycle|reboot)\b", re.I)
STEP_RE = re.compile(r"(?m)^\s*(?:\d+[\).\]]|[-*])\s+\S+")


def intake_decision(question: str) -> dict:
    text = (question or "").strip()
    warnings = []
    if not text:
        return {"ok": False, "action": "clarify", "warnings": [_warn("empty", "Enter a question.")]}
    if len(text) > 4000:
        return {
            "ok": False,
            "action": "refuse",
            "warnings": [_warn("length", "Questions are limited to 4000 characters.")],
        }
    if text_looks_like_injection(text):
        warnings.append(
            _warn(
                "prompt_injection",
                "The question contains instruction-like text. It is treated as untrusted data, not as a new system instruction.",
            )
        )
    return {"ok": True, "action": "continue", "warnings": warnings}


def output_guardrail(answer: str, evidence: list[dict], mcp_calls: list[dict], risk: str) -> dict:
    warnings = []
    blocked = False
    reason = None
    supported_text = "\n".join((item.get("content") or item.get("snippet") or "") for item in evidence)
    supported_terms = set(tokenize(supported_text))
    citation_ids = _cited_chunk_ids(answer)
    known_ids = {item.get("chunk_id") for item in evidence}
    unknown = [item for item in citation_ids if item not in known_ids]
    if unknown:
        blocked = True
        reason = "The draft cited a document that was not retrieved."
        warnings.append(_warn("citation", reason))
    if risk == "unsafe" or answer_contains_unsafe_procedure(answer):
        blocked = True
        reason = "The draft included an unsafe or unverified equipment operation."
        warnings.append(_warn("safety", reason))
    if risk == "hazardous":
        warnings.append(
            _warn(
                "safety_gate",
                "Hazardous work stays with trained personnel, the equipment-specific approved manual, and lockout/tagout. This assistant only repeats high-level checks that appear in evidence.",
            )
        )
    for call in mcp_calls:
        if not call.get("succeeded") and _claims_tool_success(answer):
            blocked = True
            reason = "A manufacturer tool failed, so the draft cannot claim the call succeeded."
            warnings.append(_warn("mcp", reason))
            break
        if call.get("is_mock") and call.get("succeeded"):
            warnings.append(
                _warn(
                    "mock_mcp",
                    "Manufacturer tool data is a DEMO MOCK fixture, not live telemetry.",
                )
            )
    if _unsupported_reset(answer, supported_terms, supported_text):
        blocked = True
        reason = "Reset or restart guidance was not present in the cited evidence."
        warnings.append(_warn("reset", reason))
    grounded = _groundedness(answer, supported_terms)
    return {
        "blocked": blocked,
        "reason": reason,
        "warnings": warnings,
        "groundedness": grounded,
        "unknown_citations": unknown,
    }


def _warn(code: str, message: str) -> dict:
    return {"code": code, "message": message}


def _cited_chunk_ids(answer: str) -> list[str]:
    return re.findall(r"chunk:([0-9a-fA-F-]{36})", answer)


def _claims_tool_success(answer: str) -> bool:
    lowered = answer.lower()
    return any(
        phrase in lowered
        for phrase in (
            "tool succeeded",
            "tool call succeeded",
            "successfully retrieved the live",
            "live status retrieved",
            "manufacturer tool confirmed success",
        )
    )


def _unsupported_reset(answer: str, supported_terms: set[str], supported_text: str) -> bool:
    if not RESET_RE.search(answer):
        return False
    if re.search(r"\b(reset|restart|power cycle|reboot)\b", supported_text, re.I):
        return False
    return "reset" not in supported_terms and "restart" not in supported_terms


def _groundedness(answer: str, supported_terms: set[str]) -> float:
    sentences = [part.strip() for part in re.split(r"[.\n]", answer) if part.strip()]
    if not sentences or not supported_terms:
        return 0.0
    boilerplate = {
        "problem",
        "summary",
        "possible",
        "cause",
        "verified",
        "checks",
        "conditional",
        "resolution",
        "confidence",
        "provenance",
        "citations",
        "heuristic",
        "demo",
        "mock",
        "manual",
        "revision",
    }
    grounded = 0
    considered = 0
    for sentence in sentences:
        terms = [term for term in tokenize(sentence) if term not in boilerplate and len(term) > 2]
        if len(terms) < 3:
            continue
        considered += 1
        overlap = len(set(terms) & supported_terms) / len(set(terms))
        if overlap >= 0.45:
            grounded += 1
    if considered == 0:
        return 0.5
    return grounded / considered
