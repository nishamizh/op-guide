import re
import uuid
from datetime import UTC, date, datetime
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, UploadFile
from sqlalchemy import func, select

from app.api.security import Scope, get_scope
from app.config import get_settings
from app.db import session_scope
from app.errors import AppError
from app.ingestion.pipeline import bump_index
from app.models import Document, DocumentChunk, DocumentVersion, IngestionJob
from app.storage import get_storage, sha256_bytes

router = APIRouter(prefix="/api/documents", tags=["documents"])

ALLOWED = {".pdf", ".docx", ".txt", ".md", ".markdown"}


@router.post("/upload", status_code=201)
async def upload_document(
    file: UploadFile = File(...),
    title: str = Form(...),
    manufacturer: str = Form(...),
    machine_model: str = Form(...),
    document_revision: str = Form(...),
    equipment_type: str = Form(...),
    plant: str = Form(...),
    effective_date: str = Form(...),
    scope: Scope = Depends(get_scope),
):
    settings = get_settings()
    filename = Path(file.filename or "upload").name
    ext = Path(filename).suffix.lower()
    if ext not in ALLOWED:
        raise AppError("unsupported_type", "Upload a PDF, DOCX, TXT, or Markdown file.", 400)
    data = await file.read()
    if not data:
        raise AppError("empty_file", "The file is empty.", 400)
    if len(data) > settings.max_upload_bytes:
        raise AppError("file_too_large", "The file exceeds the upload limit.", 400)
    _sniff(ext, data)
    safe = re.sub(r"[^A-Za-z0-9._-]", "_", filename)[:120]
    parsed_date = _date(effective_date)
    doc_id = uuid.uuid4()
    ver_id = uuid.uuid4()
    job_id = uuid.uuid4()
    key = f"{scope.tenant_id}/{doc_id}/{ver_id}/{safe}"
    get_storage().put(key, data, file.content_type or "application/octet-stream")
    now = datetime.now(UTC)
    with session_scope() as db:
        document = Document(
            id=doc_id,
            tenant_id=scope.tenant_id,
            user_id=scope.user_id,
            title=title.strip(),
            manufacturer=manufacturer.strip(),
            machine_model=machine_model.strip(),
            equipment_type=equipment_type.strip(),
            plant=plant.strip(),
            document_revision=document_revision.strip(),
            effective_date=parsed_date,
            filename=safe,
            mime_type=file.content_type or "application/octet-stream",
            storage_key=key,
            size_bytes=len(data),
            status="upload",
            is_demo=False,
            current_version_id=None,
            created_at=now,
            updated_at=now,
        )
        db.add(document)
        db.flush()
        db.add(
            DocumentVersion(
                id=ver_id,
                document_id=doc_id,
                revision=document.document_revision,
                effective_date=parsed_date,
                storage_key=key,
                checksum=sha256_bytes(data),
                is_current=True,
            )
        )
        db.flush()
        document.current_version_id = ver_id
        db.add(
            IngestionJob(
                id=job_id,
                tenant_id=scope.tenant_id,
                user_id=scope.user_id,
                document_id=doc_id,
                status="queued",
                stage="upload",
                progress=5,
            )
        )
    return {"id": str(doc_id), "title": title.strip(), "status": "upload", "job_id": str(job_id), "stage": "upload"}


@router.get("")
def list_documents(scope: Scope = Depends(get_scope)):
    with session_scope() as db:
        documents = (
            db.query(Document)
            .filter(Document.tenant_id == scope.tenant_id)
            .order_by(Document.created_at.desc())
            .all()
        )
        payload = [_document_out(db, document) for document in documents]
        chunk_count = db.execute(
            select(func.count()).select_from(DocumentChunk).where(DocumentChunk.tenant_id == scope.tenant_id)
        ).scalar_one()
        from app.models import AppMeta

        meta = db.get(AppMeta, 1)
        stats = {
            "documents": len(payload),
            "chunks": chunk_count,
            "indexed": sum(1 for item in payload if item["status"] == "indexed"),
            "index_revision": meta.index_revision if meta else 0,
            "embedding_model": meta.embedding_model if meta else "",
            "demo_documents": sum(1 for item in payload if item["is_demo"]),
        }
    return {"documents": payload, "stats": stats}


@router.get("/{document_id}")
def get_document(document_id: uuid.UUID, scope: Scope = Depends(get_scope)):
    with session_scope() as db:
        document = _owned(db, document_id, scope.tenant_id)
        payload = _document_out(db, document)
        chunks = (
            db.query(DocumentChunk)
            .filter(DocumentChunk.document_id == document.id)
            .order_by(DocumentChunk.chunk_index)
            .all()
        )
        payload["chunks"] = [
            {
                "id": str(chunk.id),
                "chunk_index": chunk.chunk_index,
                "token_count": chunk.token_count,
                "page_start": chunk.page_start,
                "page_end": chunk.page_end,
                "section_id": chunk.section_id,
                "section_title": chunk.section_title,
                "section_ids": chunk.section_ids,
                "revision": chunk.revision,
                "has_table": chunk.has_table,
                "injection_suspected": chunk.injection_suspected,
                "preview": chunk.content[:280],
            }
            for chunk in chunks
        ]
        return payload


@router.delete("/{document_id}")
def delete_document(document_id: uuid.UUID, scope: Scope = Depends(get_scope)):
    with session_scope() as db:
        document = _owned(db, document_id, scope.tenant_id)
        key = document.storage_key
        db.delete(document)
        bump_index(db, document_model_name(db))
    try:
        get_storage().delete(key)
    except Exception:
        pass
    return {"deleted": str(document_id)}


@router.post("/{document_id}/reindex", status_code=202)
def reindex_document(document_id: uuid.UUID, scope: Scope = Depends(get_scope)):
    with session_scope() as db:
        document = _owned(db, document_id, scope.tenant_id)
        job_id = uuid.uuid4()
        document.status = "upload"
        document.updated_at = datetime.now(UTC)
        db.add(
            IngestionJob(
                id=job_id,
                tenant_id=scope.tenant_id,
                user_id=scope.user_id,
                document_id=document.id,
                status="queued",
                stage="upload",
                progress=5,
            )
        )
    return {"id": str(document_id), "job_id": str(job_id), "status": "queued"}


def _owned(db, document_id: uuid.UUID, tenant_id: str) -> Document:
    document = db.get(Document, document_id)
    if document is None or document.tenant_id != tenant_id:
        raise AppError("not_found", "Document was not found in this tenant.", 404)
    return document


def _document_out(db, document: Document) -> dict:
    chunk_count = db.execute(
        select(func.count()).select_from(DocumentChunk).where(DocumentChunk.document_id == document.id)
    ).scalar_one()
    job = (
        db.query(IngestionJob)
        .filter(IngestionJob.document_id == document.id)
        .order_by(IngestionJob.created_at.desc())
        .first()
    )
    return {
        "id": str(document.id),
        "title": document.title,
        "manufacturer": document.manufacturer,
        "machine_model": document.machine_model,
        "equipment_type": document.equipment_type,
        "plant": document.plant,
        "document_revision": document.document_revision,
        "effective_date": document.effective_date.isoformat() if document.effective_date else None,
        "filename": document.filename,
        "mime_type": document.mime_type,
        "size_bytes": document.size_bytes,
        "status": document.status,
        "is_demo": document.is_demo,
        "chunk_count": chunk_count,
        "created_at": document.created_at.isoformat() if document.created_at else None,
        "job": None
        if job is None
        else {
            "id": str(job.id),
            "status": job.status,
            "stage": job.stage,
            "progress": job.progress,
            "error": job.error,
        },
    }


def _sniff(ext: str, data: bytes) -> None:
    if ext == ".pdf" and not data.startswith(b"%PDF"):
        raise AppError("bad_mime", "The file extension says PDF but the bytes do not.", 400)
    if ext == ".docx" and not data.startswith(b"PK"):
        raise AppError("bad_mime", "The file extension says DOCX but the bytes do not.", 400)


def _date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise AppError("invalid_date", "effective_date must be YYYY-MM-DD.", 400) from exc


def document_model_name(db) -> str:
    from app.models import AppMeta

    meta = db.get(AppMeta, 1)
    return meta.embedding_model if meta and meta.embedding_model else "local-hashed-ngram"
