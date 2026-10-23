import re

from app.mcp.registry import registry
from app.safety import classify_risk, text_looks_like_injection

ERROR_RE = re.compile(r"\b([A-Za-z]\d{3,4})\b")
MODEL_TOKENS = {"R200", "R500", "P300"}
MACHINE_RE = re.compile(r"\b((?:R200|R500|P300)-DEMO-\d+)\b", re.I)

META_UNSUPPORTED = re.compile(
    r"no document|no manual|nothing supports|manufacturer tool supports|unsupported question",
    re.I,
)
STATUS_RE = re.compile(r"\b(status|current|telemetry|snapshot|running|right now)\b", re.I)
HISTORY_RE = re.compile(r"maintenance history|work order|cmms", re.I)
LIMITS_RE = re.compile(r"operating limit|limits|setpoint|trip", re.I)
COMPARE_RE = re.compile(r"\b(compare|versus|vs\.?|against the manual)\b", re.I)
MANUAL_RE = re.compile(
    r"\b(manuals?|alarms?|errors?|means?|checks?|startups?|sensors?|maintenance|pressures?|temperatures?|coolants?|revisions?|why|causes?|diagnos\w*|photoeyes?)\b",
    re.I,
)
VAGUE_RE = re.compile(r"\b(acting weird|broken|not working|something wrong|help)\b", re.I)


def analyze_intent(
    question: str,
    manufacturer: str | None,
    machine_model: str | None,
    history: list[dict] | None = None,
) -> dict:
    history = history or []
    text = question or ""
    prior = " ".join(item.get("content", "") for item in history[-4:])
    combined = f"{prior}\n{text}"
    codes = _codes(text) or _codes(prior)
    detected_mfr, detected_model = _detect_equipment(combined)
    manufacturer = manufacturer or detected_mfr
    machine_model = machine_model or detected_model
    machine_ids = [match.group(1).upper() for match in MACHINE_RE.finditer(combined)]
    if not machine_ids and machine_model:
        machine_ids = [f"{machine_model.upper()}-DEMO-01"]
    risk = classify_risk(text)
    injection = text_looks_like_injection(text)
    meta = bool(META_UNSUPPORTED.search(text))
    wants_status = bool(STATUS_RE.search(text))
    wants_history = bool(HISTORY_RE.search(text))
    wants_limits = bool(LIMITS_RE.search(text))
    wants_compare = bool(COMPARE_RE.search(text))
    wants_manual = bool(MANUAL_RE.search(text) or codes or wants_compare or wants_limits)
    if wants_history and not codes and not wants_compare:
        wants_manual = False
    adapter = registry.resolve(manufacturer)
    known_adapter = adapter is not None
    needs_mcp = bool(known_adapter and (wants_status or wants_history or wants_limits or codes or wants_compare))
    needs_manual = wants_manual
    if wants_status and not wants_compare and not codes and not wants_limits and not wants_history:
        needs_manual = bool(MANUAL_RE.search(text) or wants_compare)
        needs_mcp = bool(known_adapter)
    vague = bool(VAGUE_RE.search(text)) and not codes and not machine_model
    missing_model = not machine_model and not codes and not meta and not (risk == "unsafe")
    needs_clarification = (vague or missing_model) and risk != "unsafe" and not meta
    if codes and manufacturer and machine_model:
        needs_clarification = False
    if wants_status and machine_model:
        needs_clarification = False
    route = _route(
        risk=risk,
        meta=meta,
        injection=injection,
        needs_clarification=needs_clarification,
        needs_manual=needs_manual,
        needs_mcp=needs_mcp,
        has_task=bool(codes or wants_manual or wants_status or machine_model),
    )
    tools = _tools(
        route=route,
        codes=codes,
        wants_status=wants_status or wants_compare,
        wants_history=wants_history,
        wants_limits=wants_limits,
        manufacturer=manufacturer,
        machine_model=machine_model,
        machine_ids=machine_ids,
    )
    return {
        "risk": risk,
        "injection": injection,
        "meta_unsupported": meta,
        "manufacturer": manufacturer,
        "machine_model": machine_model,
        "error_codes": codes,
        "machine_ids": machine_ids,
        "needs_manual": needs_manual,
        "needs_mcp": needs_mcp,
        "needs_clarification": needs_clarification,
        "known_adapter": known_adapter,
        "route": route,
        "planned_tools": tools,
        "routing_thresholds": {
            "weak_relevance": "rerank heuristic below the configured cutoff retries retrieval once",
            "note": "Routing uses rules and score cutoffs. Similarity is not treated as a probability.",
        },
    }


def _codes(text: str) -> list[str]:
    found = []
    for match in ERROR_RE.finditer(text or ""):
        code = match.group(1).upper()
        if code in MODEL_TOKENS or code in found:
            continue
        found.append(code)
    return found


def _detect_equipment(text: str) -> tuple[str | None, str | None]:
    lowered = text.lower()
    manufacturer = None
    model = None
    if "acme" in lowered:
        manufacturer = "Acme Industrial"
    elif "rainer" in lowered:
        manufacturer = "Rainer"
    if re.search(r"\br200\b", lowered):
        model = "R200"
        manufacturer = manufacturer or "Rainer"
    elif re.search(r"\br500\b", lowered):
        model = "R500"
        manufacturer = manufacturer or "Rainer"
    elif re.search(r"\bp300\b", lowered):
        model = "P300"
        manufacturer = manufacturer or "Acme Industrial"
    return manufacturer, model


def _route(**flags) -> str:
    if flags["risk"] == "unsafe":
        return "refuse"
    if flags["meta"]:
        return "abstain"
    if flags["injection"] and not flags["has_task"]:
        return "refuse"
    if flags["needs_clarification"]:
        return "clarify"
    if flags["needs_manual"] and flags["needs_mcp"]:
        return "both"
    if flags["needs_mcp"]:
        return "mcp"
    if flags["needs_manual"]:
        return "retrieval"
    return "clarify"


def _tools(**kwargs) -> list[dict]:
    route = kwargs["route"]
    if route not in {"mcp", "both"}:
        return []
    manufacturer = kwargs["manufacturer"] or ""
    model = kwargs["machine_model"] or ""
    calls = []
    if kwargs["codes"]:
        for code in kwargs["codes"][:2]:
            calls.append(
                {
                    "name": "get_error_code",
                    "arguments": {
                        "manufacturer": manufacturer,
                        "model": model,
                        "error_code": code,
                    },
                }
            )
    if kwargs["wants_status"]:
        machine_id = (kwargs["machine_ids"] or [f"{model}-DEMO-01" if model else ""])[0]
        if machine_id:
            calls.append({"name": "get_machine_status", "arguments": {"machine_id": machine_id}})
    if kwargs["wants_history"]:
        machine_id = (kwargs["machine_ids"] or [f"{model}-DEMO-01" if model else ""])[0]
        if machine_id:
            calls.append({"name": "get_maintenance_history", "arguments": {"machine_id": machine_id}})
    if kwargs["wants_limits"] and model:
        calls.append(
            {
                "name": "get_operating_limits",
                "arguments": {"model": model, "manufacturer": manufacturer},
            }
        )
    if not calls and model:
        calls.append(
            {
                "name": "get_machine_information",
                "arguments": {"manufacturer": manufacturer, "model": model},
            }
        )
    return calls
