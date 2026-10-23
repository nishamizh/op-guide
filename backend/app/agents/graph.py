import asyncio
import logging
import re
import time
import uuid
from contextvars import ContextVar
from datetime import UTC, datetime, timedelta

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph

from app.agents.answer import build_answer, try_llm_answer
from app.agents.guardrails import intake_decision, output_guardrail
from app.agents.intent import analyze_intent
from app.agents.state import AgentState
from app.config import get_settings
from app.db import session_scope
from app.ingestion.embeddings import embedding_model_name, vector_space_name
from app.mcp.client import call_allowlisted_tool, discover_tools
from app.models import (
    AppMeta,
    ChatMessage,
    ChatSession,
    McpToolCall,
    RetrievalRun,
    RetrievedEvidence,
)
from app.retrieval.confidence import combine_confidence
from app.retrieval.service import evidence_supports_query, find_conflicts, hybrid_search
from app.safety import classify_risk

logger = logging.getLogger(__name__)
emitter_var: ContextVar = ContextVar("manualmind_emitter", default=None)
_compiled = None


class Emitter:
    def __init__(self) -> None:
        self.queue: asyncio.Queue = asyncio.Queue()

    def emit(self, event: str, data: dict) -> None:
        self.queue.put_nowait({"event": event, "data": data})


def emit(event: str, data: dict) -> None:
    emitter = emitter_var.get()
    if emitter is not None:
        emitter.emit(event, data)


def initial_state(
    *,
    tenant_id: str,
    user_id: str,
    session_id: str,
    user_message_id: str,
    assistant_message_id: str,
    question: str,
    manufacturer: str | None,
    machine_model: str | None,
    history: list[dict],
    faults: list[str] | None = None,
) -> AgentState:
    return {
        "tenant_id": tenant_id,
        "user_id": user_id,
        "session_id": session_id,
        "user_message_id": user_message_id,
        "assistant_message_id": assistant_message_id,
        "question": question,
        "manufacturer": manufacturer,
        "machine_model": machine_model,
        "history": history,
        "intent": {},
        "route": "",
        "rewritten_query": question,
        "retrieval_attempts": 0,
        "retrieval_ready": False,
        "mcp_ready": False,
        "vector_hits": [],
        "bm25_hits": [],
        "fused": [],
        "evidence": [],
        "excluded_evidence": [],
        "retrieval_meta": {},
        "tool_catalog": [],
        "mcp_calls": [],
        "eval_action": "",
        "conflict": {},
        "answer": "",
        "blocks": {},
        "citations": [],
        "confidence": {},
        "warnings": [],
        "errors": [],
        "trace": [],
        "step_count": 0,
        "blocked": False,
        "block_reason": None,
        "faults": faults or [],
        "injection_flagged": False,
        "halt": False,
        "usage": {"prompt_tokens": 0, "completion_tokens": 0},
        "started_ms": time.perf_counter(),
    }


def _trace(name: str, started: float, status: str, output_summary: dict) -> dict:
    return {
        "node": name,
        "started_at": datetime.now(UTC).isoformat(),
        "duration_ms": round((time.perf_counter() - started) * 1000, 1),
        "status": status,
        "output_summary": output_summary,
    }


def timed(name: str):
    def decorate(fn):
        async def wrapper(state: AgentState) -> dict:
            started = time.perf_counter()
            emit("status", {"node": name, "state": "started"})
            if state.get("halt") and name not in {"output_guardrail", "persist", "abstain"}:
                entry = _trace(name, started, "skipped", {"reason": "halt"})
                emit("status", {"node": name, "state": "skipped"})
                return {"trace": [entry], "step_count": 1}
            if state.get("step_count", 0) > 24:
                entry = _trace(name, started, "bounded", {"reason": "iteration cap"})
                return {
                    "trace": [entry],
                    "step_count": 1,
                    "halt": True,
                    "eval_action": "abstain",
                    "errors": [{"node": name, "error": "iteration cap"}],
                }
            try:
                update = await asyncio.wait_for(fn(state), timeout=get_settings().node_timeout_seconds)
                status = "ok"
            except TimeoutError:
                update = {
                    "errors": [{"node": name, "error": "timeout"}],
                    "halt": True,
                    "eval_action": "abstain",
                }
                status = "timeout"
            entry = _trace(name, started, status, _summary(update))
            update = dict(update)
            update["trace"] = [entry]
            update["step_count"] = 1
            emit("status", {"node": name, "state": status, "duration_ms": entry["duration_ms"]})
            return update

        return wrapper

    return decorate


def _summary(update: dict) -> dict:
    summary = {}
    for key in ("route", "eval_action", "rewritten_query", "blocked", "block_reason"):
        if key in update:
            value = update[key]
            summary[key] = value if not isinstance(value, str) else value[:180]
    if "evidence" in update:
        summary["evidence"] = len(update["evidence"])
    if "mcp_calls" in update:
        summary["mcp_calls"] = [call.get("tool_name") for call in update["mcp_calls"]]
    if "tool_catalog" in update:
        summary["tools"] = [tool.get("name") for tool in update["tool_catalog"]]
    return summary


@timed("intake_guardrail")
async def intake_guardrail(state: AgentState) -> dict:
    decision = intake_decision(state["question"])
    update: dict = {"warnings": decision["warnings"], "injection_flagged": any(w["code"] == "prompt_injection" for w in decision["warnings"])}
    if decision["action"] == "refuse":
        update["route"] = "refuse"
        update["eval_action"] = "refuse"
    elif decision["action"] == "clarify":
        update["route"] = "clarify"
        update["eval_action"] = "clarify"
    return update


@timed("supervisor")
async def supervisor(state: AgentState) -> dict:
    if state.get("route") in {"refuse", "clarify"} and state.get("eval_action") in {"refuse", "clarify"}:
        return {"intent": {"route": state["route"], "risk": classify_risk(state["question"])}}
    intent = analyze_intent(
        state["question"],
        state.get("manufacturer"),
        state.get("machine_model"),
        state.get("history") or [],
    )
    return {
        "intent": intent,
        "route": intent["route"],
        "manufacturer": intent.get("manufacturer") or state.get("manufacturer"),
        "machine_model": intent.get("machine_model") or state.get("machine_model"),
        "eval_action": intent["route"] if intent["route"] in {"clarify", "refuse", "abstain"} else "",
    }


def route_after_supervisor(state: AgentState) -> str | list[str]:
    route = state.get("route") or (state.get("intent") or {}).get("route") or "clarify"
    if route == "both":
        return ["query_rewrite", "tool_discovery"]
    if route == "retrieval":
        return "query_rewrite"
    if route == "mcp":
        return "tool_discovery"
    if route == "refuse":
        return "refuse"
    if route == "abstain":
        return "abstain"
    return "clarify"


@timed("query_rewrite")
async def query_rewrite(state: AgentState) -> dict:
    intent = state.get("intent") or {}
    parts = [state["question"]]
    if intent.get("manufacturer"):
        parts.append(intent["manufacturer"])
    if intent.get("machine_model"):
        parts.append(intent["machine_model"])
    for code in intent.get("error_codes") or []:
        parts.append(code)
    if state.get("retrieval_attempts", 0) >= 1:
        parts.append("troubleshooting cause checks setpoint revision approved manual")
    rewritten = " ".join(dict.fromkeys(part for part in parts if part))
    return {"rewritten_query": rewritten}


@timed("hybrid_retrieval")
async def hybrid_retrieval(state: AgentState) -> dict:
    def _run():
        with session_scope() as db:
            return hybrid_search(
                db,
                state.get("rewritten_query") or state["question"],
                state["tenant_id"],
                state.get("manufacturer"),
                state.get("machine_model"),
            )

    result = await asyncio.to_thread(_run)
    evidence = []
    excluded = []
    for item in result["evidence"]:
        if item.get("injection_suspected"):
            excluded.append({**item, "exclude_reason": "prompt_injection_in_source"})
        else:
            evidence.append(item)
    return {
        "vector_hits": result["vector_hits"],
        "bm25_hits": result["bm25_hits"],
        "fused": result["fused"],
        "evidence": evidence,
        "excluded_evidence": excluded,
        "retrieval_meta": {
            "fusion": result["fusion"],
            "index_revision": result["index_revision"],
            "vector_space": result["vector_space"],
            "embedding_model": result["embedding_model"],
        },
        "retrieval_attempts": state.get("retrieval_attempts", 0) + 1,
    }


@timed("rerank")
async def rerank(state: AgentState) -> dict:
    # hybrid_retrieval already returns the reranked list. This node records the ordering decision.
    ordered = sorted(state.get("evidence") or [], key=lambda item: item.get("rerank_score") or 0, reverse=True)
    return {
        "evidence": ordered,
        "retrieval_ready": True,
        "retrieval_meta": {
            **(state.get("retrieval_meta") or {}),
            "reranked": [
                {
                    "chunk_id": item.get("chunk_id"),
                    "score": item.get("rerank_score"),
                    "components": item.get("score_components"),
                    "page": item.get("page_start"),
                    "revision": item.get("revision"),
                    "section_id": item.get("section_id"),
                }
                for item in ordered
            ],
        },
    }


@timed("tool_discovery")
async def tool_discovery(state: AgentState) -> dict:
    if "mcp_timeout" in (state.get("faults") or []):
        return {
            "tool_catalog": [],
            "errors": [{"node": "tool_discovery", "error": "injected timeout"}],
            "mcp_calls": [
                {
                    "tool_name": "discovery",
                    "arguments": {},
                    "result": {"ok": False, "mock": True, "error": "timeout"},
                    "status": "timeout",
                    "is_mock": True,
                    "error": "Injected MCP timeout before any tool call.",
                    "latency_ms": get_settings().mcp_tool_timeout_seconds * 1000,
                    "manufacturer": state.get("manufacturer"),
                    "succeeded": False,
                    "audit": {"injected": "mcp_timeout"},
                }
            ],
        }
    catalog = await discover_tools()
    return {"tool_catalog": catalog}


@timed("mcp_tool_call")
async def mcp_tool_call(state: AgentState) -> dict:
    if "mcp_timeout" in (state.get("faults") or []):
        planned = (state.get("intent") or {}).get("planned_tools") or [{"name": "get_machine_status", "arguments": {}}]
        calls = []
        for tool in planned:
            calls.append(
                {
                    "tool_name": tool["name"],
                    "arguments": tool.get("arguments") or {},
                    "result": {
                        "ok": False,
                        "mock": True,
                        "error": "timeout",
                        "message": "Deadline exceeded. No sample reading was returned.",
                    },
                    "status": "timeout",
                    "is_mock": True,
                    "error": "Manufacturer tool exceeded the request deadline.",
                    "latency_ms": get_settings().mcp_tool_timeout_seconds * 1000,
                    "manufacturer": state.get("manufacturer"),
                    "succeeded": False,
                    "audit": {"injected": "mcp_timeout"},
                }
            )
        return {"mcp_calls": calls, "mcp_ready": True}
    allowlisted = {tool["name"] for tool in state.get("tool_catalog") or [] if tool.get("allowlisted", True)}
    calls = []
    for tool in (state.get("intent") or {}).get("planned_tools") or []:
        if allowlisted and tool["name"] not in allowlisted:
            calls.append(
                {
                    "tool_name": tool["name"],
                    "arguments": tool.get("arguments") or {},
                    "result": {"ok": False, "mock": True, "error": "not_advertised"},
                    "status": "not_allowlisted",
                    "is_mock": True,
                    "error": "Discovered server did not advertise this allowlisted tool.",
                    "latency_ms": 0,
                    "manufacturer": state.get("manufacturer"),
                    "succeeded": False,
                    "audit": {"discovered": False},
                }
            )
            continue
        calls.append(
            await call_allowlisted_tool(tool["name"], tool.get("arguments") or {}, state.get("manufacturer"))
        )
        return {"mcp_calls": calls, "mcp_ready": True}


async def branch_gate(state: AgentState) -> dict:
    return {}


def route_after_gate(state: AgentState) -> str:
    route = state.get("route")
    need_retrieval = route in {"retrieval", "both"}
    need_mcp = route in {"mcp", "both"}
    retrieval_ok = bool(state.get("retrieval_ready"))
    mcp_ok = bool(state.get("mcp_ready"))
    if (not need_retrieval or retrieval_ok) and (not need_mcp or mcp_ok):
        return "evidence_evaluator"
    return END


@timed("evidence_evaluator")
async def evidence_evaluator(state: AgentState) -> dict:
    settings = get_settings()
    evidence = state.get("evidence") or []
    question = state.get("question") or ""
    conflicts = _applicable_conflicts(find_conflicts(evidence), question)
    conflict = {"groups": conflicts} if conflicts else {}
    top = evidence[0]["rerank_score"] if evidence else 0.0
    route = state.get("route")
    supported = evidence_supports_query(question, evidence)
    mcp_ok = any(call.get("succeeded") for call in state.get("mcp_calls") or [])
    mcp_failed = any(not call.get("succeeded") for call in state.get("mcp_calls") or [])
    action = "answer"
    if route == "mcp" and not mcp_ok:
        action = "abstain" if not evidence else "answer"
    elif not evidence and not mcp_ok:
        action = "abstain"
    elif evidence and not supported and state.get("retrieval_attempts", 0) < 2 and route in {"retrieval", "both"}:
        action = "retry"
    elif evidence and not supported:
        action = "abstain"
    elif evidence and top < settings.weak_relevance_threshold and state.get("retrieval_attempts", 0) < 2 and route in {"retrieval", "both"}:
        action = "retry"
    elif route == "retrieval" and not evidence:
        action = "clarify" if (state.get("intent") or {}).get("needs_clarification") else "abstain"
    warnings = []
    if conflict:
        warnings.append(
            {
                "code": "revision_conflict",
                "message": "Indexed revisions disagree. Both values are shown; the older revision is not dropped.",
            }
        )
    if mcp_failed:
        warnings.append(
            {
                "code": "mcp_failed",
                "message": "At least one manufacturer tool call failed. The answer must not claim success.",
            }
        )
    if state.get("excluded_evidence"):
        warnings.append(
            {
                "code": "untrusted_passage",
                "message": "A retrieved passage looked like an instruction and was excluded from the answer.",
            }
        )
    return {"eval_action": action, "conflict": conflict, "warnings": warnings}


def _applicable_conflicts(groups: list[dict], question: str) -> list[dict]:
    from app.agents.intent import ERROR_RE, MODEL_TOKENS

    codes = {match.group(1).upper() for match in ERROR_RE.finditer(question or "")} - MODEL_TOKENS
    about_revision = bool(re.search(r"revision|setpoint|conflict|which manual", question or "", re.I))
    if codes:
        return [group for group in groups if (group.get("error_code") or "").upper() in codes]
    if about_revision:
        return groups
    return []


def route_after_evidence(state: AgentState) -> str:
    action = state.get("eval_action") or "abstain"
    if action == "retry":
        return "query_rewrite"
    if action == "answer":
        return "answer_generator"
    if action == "clarify":
        return "clarify"
    return "abstain"


@timed("answer_generator")
async def answer_generator(state: AgentState) -> dict:
    draft = build_answer({**state, "eval_action": "answer"})
    improved = await asyncio.to_thread(try_llm_answer, state, draft)
    if improved:
        draft = improved
    usage = draft.get("usage") or {}
    for chunk in _chunks(draft["content"]):
        emit("token", {"text": chunk})
        await asyncio.sleep(0)
    return {
        "answer": draft["content"],
        "blocks": draft["blocks"],
        "citations": draft["citations"],
        "confidence": draft["confidence"],
        "usage": usage,
    }


@timed("clarify")
async def clarify(state: AgentState) -> dict:
    draft = build_answer({**state, "eval_action": "clarify", "evidence": [], "mcp_calls": []})
    for chunk in _chunks(draft["content"]):
        emit("token", {"text": chunk})
        await asyncio.sleep(0)
    return {
        "answer": draft["content"],
        "blocks": draft["blocks"],
        "citations": [],
        "confidence": draft["confidence"],
        "eval_action": "clarify",
    }


@timed("abstain")
async def abstain(state: AgentState) -> dict:
    draft = build_answer({**state, "eval_action": "abstain", "evidence": [], "mcp_calls": state.get("mcp_calls") or []})
    for chunk in _chunks(draft["content"]):
        emit("token", {"text": chunk})
        await asyncio.sleep(0)
    return {
        "answer": draft["content"],
        "blocks": draft["blocks"],
        "citations": draft["citations"],
        "confidence": draft["confidence"],
        "eval_action": "abstain",
    }


@timed("refuse")
async def refuse(state: AgentState) -> dict:
    draft = build_answer({**state, "eval_action": "refuse", "evidence": [], "mcp_calls": []})
    draft["confidence"] = combine_confidence(
        retrieval_relevance=0.0,
        source_quality=1.0,
        evidence_coverage=1.0,
        consistency=1.0,
        groundedness=1.0,
        notes=["Refusal is a policy decision, not a retrieval probability."],
    )
    draft["content"] = draft["content"].replace(
        f"Confidence: {build_answer({**state, 'eval_action': 'refuse'})['confidence']['label']}",
        f"Confidence: {draft['confidence']['label']}",
        1,
    )
    # Re-render with the policy confidence so the bubble matches the stored score.
    from app.agents.answer import render_markdown

    draft["content"] = render_markdown(draft["blocks"], [], [], draft["confidence"], state)
    for chunk in _chunks(draft["content"]):
        emit("token", {"text": chunk})
        await asyncio.sleep(0)
    return {
        "answer": draft["content"],
        "blocks": draft["blocks"],
        "citations": [],
        "confidence": draft["confidence"],
        "eval_action": "refuse",
        "warnings": [
            {
                "code": "safety_gate",
                "message": "Unsafe operation request blocked. No bypass, remote start, or guard-defeat steps are available.",
            }
        ],
    }


@timed("output_guardrail")
async def output_guardrail_node(state: AgentState) -> dict:
    evidence = state.get("evidence") or []
    if state.get("eval_action") in {"clarify", "abstain", "refuse"}:
        evidence = []
    verdict = output_guardrail(
        state.get("answer") or "",
        evidence,
        [] if state.get("eval_action") in {"clarify", "refuse"} else state.get("mcp_calls") or [],
        (state.get("intent") or {}).get("risk", "normal"),
    )
    update: dict = {"warnings": verdict["warnings"]}
    if verdict["blocked"] and state.get("eval_action") not in {"refuse"}:
        fallback = build_answer({**state, "eval_action": "abstain", "evidence": [], "mcp_calls": []})
        fallback["blocks"]["conditional_resolution"] = (
            f"The draft was blocked ({verdict['reason']}). Reliable step-by-step guidance was not released."
        )
        from app.agents.answer import render_markdown

        content = render_markdown(fallback["blocks"], [], state.get("mcp_calls") or [], fallback["confidence"], state)
        update.update(
            {
                "answer": content,
                "blocks": fallback["blocks"],
                "citations": [],
                "confidence": fallback["confidence"],
                "blocked": True,
                "block_reason": verdict["reason"],
                "eval_action": "abstain",
            }
        )
    else:
        confidence = dict(state.get("confidence") or {})
        if confidence:
            confidence["components"] = dict(confidence.get("components") or {})
            confidence["components"]["groundedness"] = round(verdict["groundedness"], 4)
        update["blocked"] = False
        update["confidence"] = confidence
    if (state.get("intent") or {}).get("risk") == "hazardous" and state.get("eval_action") == "answer":
        update["warnings"] = list(update.get("warnings") or []) + [
            {
                "code": "safety_gate",
                "message": "Safety gate: high-level checks only. Use trained personnel, the approved manual, and lockout/tagout.",
            }
        ]
    return update


@timed("persist")
async def persist(state: AgentState) -> dict:
    def _write():
        with session_scope() as db:
            message = ChatMessage(
                id=uuid.UUID(state["assistant_message_id"]),
                session_id=uuid.UUID(state["session_id"]),
                tenant_id=state["tenant_id"],
                user_id=state["user_id"],
                role="assistant",
                content=state.get("answer") or "",
                route=state.get("route"),
                blocks=state.get("blocks") or {},
                citations=state.get("citations") or [],
                confidence_score=(state.get("confidence") or {}).get("score"),
                confidence_label=(state.get("confidence") or {}).get("label"),
                confidence_detail=state.get("confidence") or {},
                warnings=state.get("warnings") or [],
                blocked=bool(state.get("blocked")),
                block_reason=state.get("block_reason"),
                prompt_version=get_settings().prompt_version,
                experiment=_experiment(db),
                usage=state.get("usage") or {},
            )
            db.add(message)
            meta = state.get("retrieval_meta") or {}
            run = RetrievalRun(
                id=uuid.uuid4(),
                message_id=message.id,
                session_id=message.session_id,
                tenant_id=state["tenant_id"],
                query=state["question"],
                rewritten_query=state.get("rewritten_query") or state["question"],
                route=state.get("route") or "",
                fusion=meta.get("fusion") or {},
                score_components=(state.get("confidence") or {}).get("components") or {},
                latency_ms=round((time.perf_counter() - state.get("started_ms", time.perf_counter())) * 1000, 1),
                vector_space=meta.get("vector_space") or vector_space_name(),
                embedding_model=meta.get("embedding_model") or embedding_model_name(),
                index_revision=int(meta.get("index_revision") or 0),
                attempt=int(state.get("retrieval_attempts") or 0),
                trace=state.get("trace") or [],
                guardrail={
                    "blocked": state.get("blocked"),
                    "reason": state.get("block_reason"),
                    "warnings": state.get("warnings") or [],
                    "eval_action": state.get("eval_action"),
                    "conflict": state.get("conflict") or {},
                },
            )
            db.add(run)
            db.flush()
            for item in list(state.get("evidence") or []) + list(state.get("excluded_evidence") or []):
                db.add(
                    RetrievedEvidence(
                        id=uuid.uuid4(),
                        retrieval_run_id=run.id,
                        chunk_id=uuid.UUID(item["chunk_id"]) if item.get("chunk_id") else None,
                        document_id=uuid.UUID(item["document_id"]) if item.get("document_id") else None,
                        source_type="manual",
                        rank=int(item.get("rank") or 0),
                        rrf_score=item.get("rrf_score"),
                        vector_rank=item.get("vector_rank"),
                        bm25_rank=item.get("bm25_rank"),
                        vector_similarity=item.get("vector_similarity"),
                        bm25_score=item.get("bm25_score"),
                        rerank_score=item.get("rerank_score"),
                        score_components=item.get("score_components") or {},
                        page_start=item.get("page_start"),
                        page_end=item.get("page_end"),
                        section_id=item.get("section_id"),
                        section_title=item.get("section_title"),
                        section_ids=item.get("section_ids") or [],
                        document_title=item.get("document_title"),
                        revision=item.get("revision"),
                        snippet=item.get("snippet") or "",
                        manufacturer=item.get("manufacturer"),
                        machine_model=item.get("machine_model"),
                        excluded=bool(item.get("exclude_reason") or item.get("injection_suspected") and item in (state.get("excluded_evidence") or [])),
                        exclude_reason=item.get("exclude_reason"),
                    )
                )
            for call in state.get("mcp_calls") or []:
                db.add(
                    McpToolCall(
                        id=uuid.uuid4(),
                        message_id=message.id,
                        session_id=message.session_id,
                        tenant_id=state["tenant_id"],
                        tool_name=call.get("tool_name") or "",
                        arguments=call.get("arguments") or {},
                        result=call.get("result"),
                        status=call.get("status") or "error",
                        is_mock=bool(call.get("is_mock", True)),
                        error=call.get("error"),
                        latency_ms=float(call.get("latency_ms") or 0),
                        manufacturer=call.get("manufacturer"),
                        audit=call.get("audit") or {},
                    )
                )
            session = db.get(ChatSession, uuid.UUID(state["session_id"]))
            if session is not None:
                session.updated_at = datetime.now(UTC)
                if session.title in {"", "New conversation"}:
                    session.title = state["question"][:80]
            return str(message.id), str(run.id)

    message_id, run_id = await asyncio.to_thread(_write)
    return {"assistant_message_id": message_id, "retrieval_run_id": run_id}


def _experiment(db) -> dict:
    settings = get_settings()
    meta = db.get(AppMeta, 1)
    return {
        "model": settings.openai_model if settings.openai_configured() else "template-synthesizer",
        "fallback_model": settings.openai_fallback_model,
        "prompt_version": settings.prompt_version,
        "embedding_model": meta.embedding_model if meta else embedding_model_name(),
        "embedding_dimensions": settings.embedding_dimensions,
        "index_revision": meta.index_revision if meta else 0,
        "rrf_k": settings.rrf_k,
        "confidence_thresholds": {
            "high": settings.confidence_high,
            "medium": settings.confidence_medium,
            "note": "illustrative until calibrated",
        },
    }


def _chunks(text: str, size: int = 24) -> list[str]:
    return [text[index : index + size] for index in range(0, len(text), size)] or [""]


def route_to_guardrail(state: AgentState) -> str:
    return "output_guardrail"


def build_graph(checkpointer=None):
    graph = StateGraph(AgentState)
    graph.add_node("intake_guardrail", intake_guardrail)
    graph.add_node("supervisor", supervisor)
    graph.add_node("query_rewrite", query_rewrite)
    graph.add_node("hybrid_retrieval", hybrid_retrieval)
    graph.add_node("rerank", rerank)
    graph.add_node("tool_discovery", tool_discovery)
    graph.add_node("mcp_tool_call", mcp_tool_call)
    graph.add_node("branch_gate", branch_gate)
    graph.add_node("evidence_evaluator", evidence_evaluator)
    graph.add_node("answer_generator", answer_generator)
    graph.add_node("clarify", clarify)
    graph.add_node("abstain", abstain)
    graph.add_node("refuse", refuse)
    graph.add_node("output_guardrail", output_guardrail_node)
    graph.add_node("persist", persist)

    graph.add_edge(START, "intake_guardrail")
    graph.add_edge("intake_guardrail", "supervisor")
    graph.add_conditional_edges(
        "supervisor",
        route_after_supervisor,
        ["query_rewrite", "tool_discovery", "clarify", "refuse", "abstain"],
    )
    graph.add_edge("query_rewrite", "hybrid_retrieval")
    graph.add_edge("hybrid_retrieval", "rerank")
    graph.add_edge("rerank", "branch_gate")
    graph.add_edge("tool_discovery", "mcp_tool_call")
    graph.add_edge("mcp_tool_call", "branch_gate")
    graph.add_conditional_edges("branch_gate", route_after_gate, ["evidence_evaluator", END])
    graph.add_conditional_edges(
        "evidence_evaluator",
        route_after_evidence,
        ["query_rewrite", "answer_generator", "clarify", "abstain"],
    )
    graph.add_edge("answer_generator", "output_guardrail")
    graph.add_edge("clarify", "output_guardrail")
    graph.add_edge("abstain", "output_guardrail")
    graph.add_edge("refuse", "output_guardrail")
    graph.add_edge("output_guardrail", "persist")
    graph.add_edge("persist", END)
    return graph.compile(checkpointer=checkpointer or MemorySaver())


def get_graph():
    global _compiled
    if _compiled is None:
        _compiled = build_graph(MemorySaver())
    return _compiled


def set_graph(graph) -> None:
    global _compiled
    _compiled = graph


async def run_turn(state: AgentState) -> dict:
    graph = get_graph()
    return await graph.ainvoke(
        state,
        config={"configurable": {"thread_id": state["assistant_message_id"]}},
    )


def session_expiry(now: datetime | None = None) -> datetime:
    current = now or datetime.now(UTC)
    return current + timedelta(days=get_settings().retention_days)
