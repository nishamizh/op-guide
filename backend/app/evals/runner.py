import json
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path

from app.agents.graph import initial_state, run_turn, session_expiry
from app.config import get_settings
from app.db import session_scope
from app.evals.metrics import (
    citation_precision,
    correctness,
    decision_accuracy,
    fact_coverage,
    mean,
    mrr_at_k,
    percentile,
    recall_at_k,
    tool_selected,
    unsafe_answer,
)
from app.models import ChatSession, EvaluationResult, EvaluationRun

DATASET_PATH = Path(__file__).with_name("dataset.json")


def load_cases() -> list[dict]:
    return json.loads(DATASET_PATH.read_text())


async def run_evaluation(tenant_id: str, user_id: str, case_ids: list[str] | None = None) -> dict:
    cases = load_cases()
    if case_ids:
        wanted = set(case_ids)
        cases = [case for case in cases if case["id"] in wanted]
        if not cases:
            raise ValueError("No evaluation cases matched the requested ids.")
    run_id = uuid.uuid4()
    started = datetime.now(UTC)
    with session_scope() as db:
        db.add(
            EvaluationRun(
                id=run_id,
                tenant_id=tenant_id,
                status="running",
                experiment=_experiment_stub(),
                metrics={},
                started_at=started,
            )
        )
    rows = []
    for case in cases:
        rows.append(await _run_case(tenant_id, user_id, run_id, case))
    metrics = _aggregate(rows)
    with session_scope() as db:
        run = db.get(EvaluationRun, run_id)
        experiment = _experiment_from_db(db)
        for row in rows:
            db.add(EvaluationResult(**row))
        if run is not None:
            run.status = "succeeded"
            run.metrics = metrics
            run.experiment = experiment
            run.finished_at = datetime.now(UTC)
    return {
        "id": str(run_id),
        "status": "succeeded",
        "metrics": metrics,
        "experiment": experiment,
        "cases": len(rows),
    }


def list_runs(tenant_id: str) -> dict:
    with session_scope() as db:
        runs = (
            db.query(EvaluationRun)
            .filter(EvaluationRun.tenant_id == tenant_id)
            .order_by(EvaluationRun.started_at.desc())
            .limit(20)
            .all()
        )
        return {
            "runs": [
                {
                    "id": str(run.id),
                    "status": run.status,
                    "metrics": run.metrics,
                    "experiment": run.experiment,
                    "started_at": run.started_at.isoformat() if run.started_at else None,
                    "finished_at": run.finished_at.isoformat() if run.finished_at else None,
                }
                for run in runs
            ],
            "dataset_size": len(load_cases()),
            "judge_note": "Scores are deterministic checks against labeled facts and sources. An LLM judge is not the source of truth.",
        }


async def _run_case(tenant_id: str, user_id: str, run_id: uuid.UUID, case: dict) -> dict:
    session_id = uuid.uuid4()
    assistant_id = uuid.uuid4()
    with session_scope() as db:
        db.add(
            ChatSession(
                id=session_id,
                tenant_id=tenant_id,
                user_id=user_id,
                title=f"Eval {case['id']}",
                manufacturer=case.get("manufacturer"),
                machine_model=case.get("machine_model"),
                retain_until=session_expiry(),
            )
        )
    state = initial_state(
        tenant_id=tenant_id,
        user_id=user_id,
        session_id=str(session_id),
        user_message_id=str(uuid.uuid4()),
        assistant_message_id=str(assistant_id),
        question=case["question"],
        manufacturer=case.get("manufacturer"),
        machine_model=case.get("machine_model"),
        history=[],
        faults=case.get("faults") or [],
    )
    started = time.perf_counter()
    final = await run_turn(state)
    latency = (time.perf_counter() - started) * 1000
    evidence = final.get("evidence") or []
    citations = final.get("citations") or []
    answer = final.get("answer") or ""
    calls = final.get("mcp_calls") or []
    action = final.get("eval_action") or final.get("route")
    relevant = case.get("relevant_sections") or []
    scores = {
        "recall_at_5": recall_at_k(relevant, evidence, 5),
        "mrr_at_10": mrr_at_k(relevant, evidence, 10),
        "citation_precision": citation_precision(citations, relevant),
        "faithfulness": fact_coverage(answer, case.get("expected_facts") or []),
        "relevance": fact_coverage(answer, case.get("expected_facts") or []),
        "correctness": correctness(answer, case.get("expected_facts") or [], case.get("forbidden") or []),
        "tool_selection": tool_selected(calls, case.get("expected_tool"), case.get("expected_tool_status")),
        "decision_accuracy": decision_accuracy(action, case),
        "route_accuracy": None
        if not case.get("expected_route")
        else (1.0 if final.get("route") == case["expected_route"] else 0.0),
        "unsafe_answer": 1.0 if unsafe_answer(answer, case) else 0.0,
        "conflict_explained": _conflict_score(final, case),
    }
    usage = final.get("usage") or {}
    return {
        "id": uuid.uuid4(),
        "run_id": run_id,
        "case_id": case["id"],
        "category": case["category"],
        "question": case["question"],
        "expected": {
            "relevant_sections": relevant,
            "facts": case.get("expected_facts") or [],
            "route": case.get("expected_route"),
            "tool": case.get("expected_tool"),
        },
        "actual": {
            "route": final.get("route"),
            "eval_action": action,
            "sections": sorted({section for item in evidence for section in (item.get("section_ids") or [])}),
            "tools": [{"name": call.get("tool_name"), "status": call.get("status")} for call in calls],
            "confidence": (final.get("confidence") or {}).get("label"),
            "answer_excerpt": answer[:500],
            "blocked": final.get("blocked"),
        },
        "scores": scores,
        "latency_ms": round(latency, 1),
        "prompt_tokens": int(usage.get("prompt_tokens") or 0),
        "completion_tokens": int(usage.get("completion_tokens") or 0),
    }


def _conflict_score(final: dict, case: dict) -> float | None:
    if not case.get("expect_conflict"):
        return None
    answer = (final.get("answer") or "").lower()
    conflict = final.get("conflict") or {}
    explained = "1.5" in answer and "1.2" in answer and ("conflict" in answer or "revision a" in answer)
    detected = bool(conflict.get("groups"))
    return 1.0 if explained and detected else 0.0


def _aggregate(rows: list[dict]) -> dict:
    keys = [
        "recall_at_5",
        "mrr_at_10",
        "citation_precision",
        "faithfulness",
        "relevance",
        "correctness",
        "tool_selection",
        "decision_accuracy",
        "route_accuracy",
        "conflict_explained",
    ]
    metrics = {}
    for key in keys:
        values = [row["scores"][key] for row in rows if row["scores"].get(key) is not None]
        metrics[key] = None if not values else round(mean(values), 4)
    unsafe_flags = [row["scores"]["unsafe_answer"] for row in rows]
    latencies = [row["latency_ms"] for row in rows]
    prompt_tokens = sum(row["prompt_tokens"] for row in rows)
    completion_tokens = sum(row["completion_tokens"] for row in rows)
    settings = get_settings()
    cost = (
        prompt_tokens * settings.input_cost_per_million
        + completion_tokens * settings.output_cost_per_million
    ) / 1_000_000
    metrics.update(
        {
            "unsafe_answer_rate": round(mean(unsafe_flags) or 0, 4),
            "latency_p50_ms": round(percentile(latencies, 0.50) or 0, 1),
            "latency_p95_ms": round(percentile(latencies, 0.95) or 0, 1),
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "estimated_cost_usd": round(cost, 6),
            "cases": len(rows),
            "llm_judge": False,
            "score_note": "Deterministic labeled checks. Not an LLM-judge score and not a calibrated probability.",
        }
    )
    return metrics


def _experiment_stub() -> dict:
    settings = get_settings()
    return {
        "model": settings.openai_model if settings.openai_configured() else "template-synthesizer",
        "prompt_version": settings.prompt_version,
        "embedding_model": "pending",
    }


def _experiment_from_db(db) -> dict:
    from app.models import AppMeta

    settings = get_settings()
    meta = db.get(AppMeta, 1)
    return {
        "model": settings.openai_model if settings.openai_configured() else "template-synthesizer",
        "fallback_model": settings.openai_fallback_model,
        "prompt_version": settings.prompt_version,
        "embedding_model": meta.embedding_model if meta else "",
        "embedding_dimensions": settings.embedding_dimensions,
        "index_revision": meta.index_revision if meta else 0,
        "dataset": "manualmind-demo-v1",
        "llm_judge": False,
    }
