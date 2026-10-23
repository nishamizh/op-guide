import asyncio
import json
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Header
from fastapi.responses import StreamingResponse
from sqlalchemy import select

from app.agents.graph import Emitter, emitter_var, initial_state, run_turn, session_expiry
from app.api.security import Scope, get_scope, issue_token, parse_token
from app.db import session_scope
from app.errors import AppError
from app.models import ChatMessage, ChatSession, McpToolCall, RetrievalRun, RetrievedEvidence
from app.schemas import ChatRequest, FeedbackRequest

router = APIRouter(tags=["chat"])


@router.post("/api/chat")
async def chat(body: ChatRequest, scope: Scope = Depends(get_scope)):
    result = await _run(body, scope)
    return result


@router.post("/api/chat/stream")
async def chat_stream(body: ChatRequest, scope: Scope = Depends(get_scope)):
    emitter = Emitter()
    token = emitter_var.set(emitter)

    async def work() -> None:
        try:
            result = await _run(body, scope)
            emitter.emit("result", result)
        except AppError as exc:
            emitter.emit("error", {"code": exc.code, "message": exc.message})
        except Exception:
            emitter.emit("error", {"code": "chat_failed", "message": "The assistant failed before it could finish."})
        emitter.emit("done", {})

    task = asyncio.create_task(work())
    emitter_var.reset(token)

    async def events() -> AsyncIterator[str]:
        try:
            while True:
                try:
                    item = await asyncio.wait_for(emitter.queue.get(), timeout=15)
                except TimeoutError:
                    if task.done():
                        break
                    yield ": keepalive\n\n"
                    continue
                yield _sse(item["event"], item["data"])
                if item["event"] == "done":
                    break
            await task
        finally:
            if not task.done():
                task.cancel()

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/api/conversations")
def list_conversations(scope: Scope = Depends(get_scope)):
    with session_scope() as db:
        rows = (
            db.query(ChatSession)
            .filter(ChatSession.tenant_id == scope.tenant_id, ChatSession.user_id == scope.user_id)
            .order_by(ChatSession.updated_at.desc())
            .limit(50)
            .all()
        )
        return {
            "conversations": [
                {
                    "id": str(row.id),
                    "title": row.title,
                    "manufacturer": row.manufacturer,
                    "machine_model": row.machine_model,
                    "updated_at": row.updated_at.isoformat() if row.updated_at else None,
                    "session_token": issue_token(row.id, row.tenant_id, row.user_id),
                }
                for row in rows
            ]
        }


@router.get("/api/conversations/{session_id}")
def get_conversation(session_id: uuid.UUID, authorization: str | None = Header(default=None), scope: Scope = Depends(get_scope)):
    _check_bearer(authorization, session_id, scope)
    with session_scope() as db:
        session = _session(db, session_id, scope)
        return {
            "id": str(session.id),
            "title": session.title,
            "manufacturer": session.manufacturer,
            "machine_model": session.machine_model,
            "retain_until": session.retain_until.isoformat(),
            "session_token": issue_token(session.id, session.tenant_id, session.user_id),
        }


@router.get("/api/conversations/{session_id}/messages")
def list_messages(session_id: uuid.UUID, authorization: str | None = Header(default=None), scope: Scope = Depends(get_scope)):
    _check_bearer(authorization, session_id, scope)
    with session_scope() as db:
        _session(db, session_id, scope)
        messages = (
            db.query(ChatMessage)
            .filter(ChatMessage.session_id == session_id)
            .order_by(ChatMessage.created_at.asc())
            .all()
        )
        return {"messages": [_message_out(message) for message in messages]}


@router.get("/api/chat/{message_id}/trace")
def get_trace(message_id: uuid.UUID, scope: Scope = Depends(get_scope)):
    with session_scope() as db:
        message = db.get(ChatMessage, message_id)
        if message is None or message.tenant_id != scope.tenant_id or message.user_id != scope.user_id:
            raise AppError("not_found", "Message was not found.", 404)
        run = db.execute(select(RetrievalRun).where(RetrievalRun.message_id == message.id)).scalar_one_or_none()
        evidence = []
        if run is not None:
            evidence = (
                db.query(RetrievedEvidence)
                .filter(RetrievedEvidence.retrieval_run_id == run.id)
                .order_by(RetrievedEvidence.rank)
                .all()
            )
        calls = db.query(McpToolCall).filter(McpToolCall.message_id == message.id).all()
        return {
            "message": _message_out(message),
            "run": None
            if run is None
            else {
                "id": str(run.id),
                "query": run.query,
                "rewritten_query": run.rewritten_query,
                "route": run.route,
                "fusion": run.fusion,
                "score_components": run.score_components,
                "latency_ms": run.latency_ms,
                "vector_space": run.vector_space,
                "embedding_model": run.embedding_model,
                "index_revision": run.index_revision,
                "attempt": run.attempt,
                "trace": run.trace,
                "guardrail": run.guardrail,
            },
            "evidence": [
                {
                    "rank": item.rank,
                    "document_id": str(item.document_id) if item.document_id else None,
                    "chunk_id": str(item.chunk_id) if item.chunk_id else None,
                    "document_title": item.document_title,
                    "section_id": item.section_id,
                    "section_title": item.section_title,
                    "page_start": item.page_start,
                    "revision": item.revision,
                    "rerank_score": item.rerank_score,
                    "rrf_score": item.rrf_score,
                    "vector_rank": item.vector_rank,
                    "bm25_rank": item.bm25_rank,
                    "vector_similarity": item.vector_similarity,
                    "bm25_score": item.bm25_score,
                    "score_components": item.score_components,
                    "snippet": item.snippet,
                    "excluded": item.excluded,
                    "exclude_reason": item.exclude_reason,
                    "evidence_type": "manual",
                }
                for item in evidence
            ],
            "mcp_calls": [
                {
                    "tool_name": call.tool_name,
                    "arguments": call.arguments,
                    "result": call.result,
                    "status": call.status,
                    "is_mock": call.is_mock,
                    "error": call.error,
                    "latency_ms": call.latency_ms,
                    "audit": call.audit,
                }
                for call in calls
            ],
        }


@router.get("/api/traces")
def list_traces(scope: Scope = Depends(get_scope)):
    with session_scope() as db:
        messages = (
            db.query(ChatMessage)
            .filter(
                ChatMessage.tenant_id == scope.tenant_id,
                ChatMessage.user_id == scope.user_id,
                ChatMessage.role == "assistant",
            )
            .order_by(ChatMessage.created_at.desc())
            .limit(40)
            .all()
        )
        return {
            "traces": [
                {
                    "message_id": str(message.id),
                    "session_id": str(message.session_id),
                    "created_at": message.created_at.isoformat() if message.created_at else None,
                    "route": message.route,
                    "confidence_label": message.confidence_label,
                    "confidence_score": message.confidence_score,
                    "blocked": message.blocked,
                    "preview": message.content[:180],
                }
                for message in messages
            ]
        }


@router.post("/api/feedback", status_code=201)
def create_feedback(body: FeedbackRequest, scope: Scope = Depends(get_scope)):
    from app.models import Feedback

    with session_scope() as db:
        message = db.get(ChatMessage, body.message_id)
        if message is None or message.tenant_id != scope.tenant_id:
            raise AppError("not_found", "Message was not found.", 404)
        row = Feedback(
            id=uuid.uuid4(),
            message_id=message.id,
            tenant_id=scope.tenant_id,
            user_id=scope.user_id,
            rating=body.rating,
            comment=body.comment,
        )
        db.add(row)
        return {"id": str(row.id), "rating": row.rating}


async def _run(body: ChatRequest, scope: Scope) -> dict:
    prepared = await asyncio.to_thread(_prepare, body, scope)
    from app.agents.graph import emit

    emit(
        "session",
        {
            "session_id": prepared["session_id"],
            "session_token": prepared["session_token"],
            "user_message_id": prepared["user_message_id"],
        },
    )
    state = initial_state(
        tenant_id=scope.tenant_id,
        user_id=scope.user_id,
        session_id=prepared["session_id"],
        user_message_id=prepared["user_message_id"],
        assistant_message_id=prepared["assistant_message_id"],
        question=body.message.strip(),
        manufacturer=prepared["manufacturer"],
        machine_model=prepared["machine_model"],
        history=prepared["history"],
    )
    await run_turn(state)
    return await asyncio.to_thread(_load_result, prepared)


def _prepare(body: ChatRequest, scope: Scope) -> dict:
    with session_scope() as db:
        session = None
        if body.session_token:
            session_id, tenant, user = parse_token(body.session_token)
            if tenant != scope.tenant_id or user != scope.user_id:
                raise AppError("invalid_token", "Session token does not match this operator.", 401)
            session = db.get(ChatSession, uuid.UUID(session_id))
            if session is None:
                raise AppError("not_found", "Conversation was not found.", 404)
        if session is None:
            session = ChatSession(
                id=uuid.uuid4(),
                tenant_id=scope.tenant_id,
                user_id=scope.user_id,
                title=body.message.strip()[:80] or "New conversation",
                manufacturer=body.manufacturer,
                machine_model=body.machine_model,
                retain_until=session_expiry(),
                created_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
            )
            db.add(session)
            db.flush()
        if body.manufacturer:
            session.manufacturer = body.manufacturer
        if body.machine_model:
            session.machine_model = body.machine_model
        history_rows = (
            db.query(ChatMessage)
            .filter(ChatMessage.session_id == session.id)
            .order_by(ChatMessage.created_at.asc())
            .all()
        )
        history = [{"role": row.role, "content": row.content} for row in history_rows][-8:]
        user_message = ChatMessage(
            id=uuid.uuid4(),
            session_id=session.id,
            tenant_id=scope.tenant_id,
            user_id=scope.user_id,
            role="user",
            content=body.message.strip(),
            blocks={},
            citations=[],
            confidence_detail={},
            warnings=[],
            experiment={},
            usage={},
        )
        db.add(user_message)
        assistant_id = uuid.uuid4()
        return {
            "session_id": str(session.id),
            "session_token": issue_token(session.id, session.tenant_id, session.user_id),
            "user_message_id": str(user_message.id),
            "assistant_message_id": str(assistant_id),
            "manufacturer": session.manufacturer,
            "machine_model": session.machine_model,
            "history": history,
        }


def _load_result(prepared: dict) -> dict:
    with session_scope() as db:
        message = db.get(ChatMessage, uuid.UUID(prepared["assistant_message_id"]))
        if message is None:
            raise AppError("chat_failed", "The assistant did not persist a reply.", 500)
        payload = _message_out(message)
        payload["session_id"] = prepared["session_id"]
        payload["session_token"] = prepared["session_token"]
        payload["user_message_id"] = prepared["user_message_id"]
        return payload


def _message_out(message: ChatMessage) -> dict:
    return {
        "id": str(message.id),
        "session_id": str(message.session_id),
        "role": message.role,
        "content": message.content,
        "route": message.route,
        "blocks": message.blocks or {},
        "citations": message.citations or [],
        "confidence": message.confidence_detail or {},
        "confidence_label": message.confidence_label,
        "confidence_score": message.confidence_score,
        "warnings": message.warnings or [],
        "blocked": message.blocked,
        "block_reason": message.block_reason,
        "created_at": message.created_at.isoformat() if message.created_at else None,
    }


def _session(db, session_id: uuid.UUID, scope: Scope) -> ChatSession:
    session = db.get(ChatSession, session_id)
    if session is None or session.tenant_id != scope.tenant_id or session.user_id != scope.user_id:
        raise AppError("not_found", "Conversation was not found.", 404)
    return session


def _check_bearer(authorization: str | None, session_id: uuid.UUID, scope: Scope) -> None:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise AppError("unauthorized", "Send the conversation session token in Authorization.", 401)
    token_session, tenant, user = parse_token(authorization.split(" ", 1)[1].strip())
    if token_session != str(session_id) or tenant != scope.tenant_id or user != scope.user_id:
        raise AppError("invalid_token", "Session token does not match this conversation.", 401)


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"
