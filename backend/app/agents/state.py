import operator
from typing import Annotated, TypedDict


class AgentState(TypedDict, total=False):
    tenant_id: str
    user_id: str
    session_id: str
    user_message_id: str
    assistant_message_id: str
    question: str
    manufacturer: str | None
    machine_model: str | None
    history: list[dict]
    intent: dict
    route: str
    rewritten_query: str
    retrieval_attempts: int
    retrieval_ready: bool
    mcp_ready: bool
    vector_hits: list[dict]
    bm25_hits: list[dict]
    fused: list[dict]
    evidence: list[dict]
    excluded_evidence: list[dict]
    retrieval_meta: dict
    tool_catalog: list[dict]
    mcp_calls: list[dict]
    eval_action: str
    conflict: dict
    answer: str
    blocks: dict
    citations: list[dict]
    confidence: dict
    warnings: Annotated[list[dict], operator.add]
    errors: Annotated[list[dict], operator.add]
    trace: Annotated[list[dict], operator.add]
    step_count: Annotated[int, operator.add]
    blocked: bool
    block_reason: str | None
    faults: list[str]
    injection_flagged: bool
    halt: bool
    usage: dict
    started_ms: float
