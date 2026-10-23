import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends

from app.api.security import Scope, get_scope
from app.config import EMBEDDING_DIM, get_settings
from app.db import check_database, session_scope
from app.errors import AppError
from app.evals.runner import list_runs, run_evaluation
from app.mcp.client import discover_tools
from app.mcp.registry import registry
from app.models import EvaluationResult, EvaluationRun
from app.schemas import EvaluationRequest
from app.storage import get_storage

router = APIRouter(tags=["system"])


@router.get("/api/health")
def health():
    return {"status": "ok", "service": "manualmind-api"}


@router.get("/api/ready")
def ready():
    settings = get_settings()
    checks: dict = {"app_env": settings.app_env}
    problems = settings.production_problems()
    try:
        checks.update(check_database())
    except Exception as exc:
        checks["database"] = f"error: {exc.__class__.__name__}"
        return _not_ready(checks, problems)
    if checks.get("embedding_typmod") not in {EMBEDDING_DIM, None}:
        checks["embedding_dimension"] = "mismatch"
        return _not_ready(checks, problems + [f"vector column typmod is {checks.get('embedding_typmod')}"])
    checks["embedding_dimension"] = "ok" if checks.get("embedding_typmod") == EMBEDDING_DIM else "pending"
    try:
        checks["object_storage"] = get_storage().kind()
    except Exception as exc:
        checks["object_storage"] = f"error: {exc.__class__.__name__}"
        return _not_ready(checks, problems)
    if problems:
        checks["configuration"] = problems
        return _not_ready(checks, problems)
    checks["status"] = "ready"
    return checks


@router.get("/api/manufacturers")
def manufacturers():
    return {"manufacturers": registry.list_adapters(), "demo": True}


@router.get("/api/mcp/tools")
async def mcp_tools():
    catalog = await discover_tools()
    return {
        "server_url": get_settings().mcp_server_url,
        "demo": True,
        "mock": True,
        "tools": catalog,
        "allowlist": [
            "get_machine_information",
            "get_error_code",
            "get_maintenance_history",
            "get_operating_limits",
            "get_machine_status",
        ],
        "reachable": bool(catalog),
        "checked_at": datetime.now(UTC).isoformat(),
    }


@router.get("/api/evaluations")
def evaluations(scope: Scope = Depends(get_scope)):
    return list_runs(scope.tenant_id)


@router.post("/api/evaluations/run", status_code=201)
async def evaluations_run(body: EvaluationRequest, scope: Scope = Depends(get_scope)):
    try:
        return await run_evaluation(scope.tenant_id, scope.user_id, body.case_ids)
    except Exception as exc:
        raise AppError("evaluation_failed", str(exc)[:500], 500) from exc


@router.get("/api/evaluations/{run_id}")
def evaluation_detail(run_id: uuid.UUID, scope: Scope = Depends(get_scope)):
    with session_scope() as db:
        run = db.get(EvaluationRun, run_id)
        if run is None or run.tenant_id != scope.tenant_id:
            raise AppError("not_found", "Evaluation run was not found.", 404)
        rows = db.query(EvaluationResult).filter(EvaluationResult.run_id == run.id).all()
        return {
            "id": str(run.id),
            "status": run.status,
            "experiment": run.experiment,
            "metrics": run.metrics,
            "started_at": run.started_at.isoformat() if run.started_at else None,
            "finished_at": run.finished_at.isoformat() if run.finished_at else None,
            "results": [
                {
                    "case_id": row.case_id,
                    "category": row.category,
                    "question": row.question,
                    "scores": row.scores,
                    "latency_ms": row.latency_ms,
                    "actual": row.actual,
                }
                for row in rows
            ],
        }


def _not_ready(checks: dict, problems: list[str]):
    from fastapi.responses import JSONResponse

    checks["status"] = "not_ready"
    checks["problems"] = problems
    return JSONResponse(status_code=503, content=checks)
