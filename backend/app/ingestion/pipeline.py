import uuid
from datetime import UTC, datetime

from sqlalchemy import delete, update
from sqlalchemy.orm import Session

from app.config import get_settings
from app.ingestion.chunker import chunk_pages
from app.ingestion.embeddings import embed_texts
from app.ingestion.parser import parse_file
from app.models import AppMeta, Document, DocumentChunk, DocumentVersion, IngestionJob
from app.seed.ids import chunk_id
from app.storage import get_storage

STAGE_PROGRESS = {"parse": 15, "chunk": 40, "embed": 75, "indexed": 100}


def _touch_job(db: Session, job: IngestionJob, document: Document, stage: str, status: str) -> None:
    job.stage = stage
    job.status = status
    job.progress = STAGE_PROGRESS.get(stage, job.progress)
    document.status = stage if status != "failed" else "failed"
    document.updated_at = datetime.now(UTC)
    db.flush()


def bump_index(db: Session, embedding_model: str) -> int:
    settings = get_settings()
    meta = db.get(AppMeta, 1)
    if meta is None:
        meta = AppMeta(
            id=1,
            embedding_model=embedding_model,
            embedding_dimensions=settings.embedding_dimensions,
            index_revision=1,
            prompt_version=settings.prompt_version,
            seed_version="",
        )
        db.add(meta)
    else:
        meta.index_revision += 1
        meta.embedding_model = embedding_model
        meta.embedding_dimensions = settings.embedding_dimensions
        meta.prompt_version = settings.prompt_version
        meta.updated_at = datetime.now(UTC)
    db.flush()
    return meta.index_revision


def process_job(db: Session, job_id: uuid.UUID) -> None:
    job = db.get(IngestionJob, job_id)
    if job is None:
        return
    document = db.get(Document, job.document_id)
    if document is None:
        job.status = "failed"
        job.error = "Document disappeared before indexing."
        return
    settings = get_settings()
    job.status = "running"
    job.started_at = datetime.now(UTC)
    job.locked_at = job.started_at
    try:
        _touch_job(db, job, document, "parse", "running")
        data = get_storage().get(document.storage_key)
        pages = parse_file(document.filename, data)
        if not pages:
            raise RuntimeError("The parser found no text.")
        _touch_job(db, job, document, "chunk", "running")
        drafts = chunk_pages(
            pages,
            target=settings.chunk_target_tokens,
            minimum=settings.chunk_min_tokens,
            maximum=settings.chunk_max_tokens,
            overlap=settings.chunk_overlap_tokens,
        )
        if not drafts:
            raise RuntimeError("Chunking produced no text.")
        _touch_job(db, job, document, "embed", "running")
        vectors, model_name = embed_texts([draft.content for draft in drafts])
        version_id = document.current_version_id
        if version_id is None:
            raise RuntimeError("Document has no current version.")
        db.execute(delete(DocumentChunk).where(DocumentChunk.document_id == document.id))
        doc_key = str(document.id)
        for index, (draft, vector) in enumerate(zip(drafts, vectors, strict=True)):
            db.add(
                DocumentChunk(
                    id=chunk_id(doc_key, index, draft.section_id),
                    tenant_id=document.tenant_id,
                    document_id=document.id,
                    version_id=version_id,
                    chunk_index=index,
                    content=draft.content,
                    token_count=draft.token_count,
                    page_start=draft.page_start,
                    page_end=draft.page_end,
                    section_id=draft.section_id,
                    section_title=draft.section_title,
                    section_ids=draft.section_ids,
                    manufacturer=document.manufacturer,
                    machine_model=document.machine_model,
                    revision=document.document_revision,
                    effective_date=document.effective_date,
                    embedding=vector,
                    embedding_model=model_name,
                    has_table=draft.has_table,
                    injection_suspected=draft.injection_suspected,
                    metadata_json={
                        **draft.metadata,
                        "overlap_tokens": draft.overlap_tokens,
                        "below_target": draft.token_count < settings.chunk_min_tokens,
                    },
                )
            )
        bump_index(db, model_name)
        job.status = "succeeded"
        job.stage = "indexed"
        job.progress = 100
        job.error = None
        job.finished_at = datetime.now(UTC)
        document.status = "indexed"
        document.updated_at = job.finished_at
        db.execute(
            update(DocumentVersion)
            .where(DocumentVersion.document_id == document.id)
            .values(is_current=False)
        )
        db.execute(
            update(DocumentVersion)
            .where(DocumentVersion.id == version_id)
            .values(is_current=True)
        )
    except Exception as exc:
        job.status = "failed"
        job.stage = "failed"
        job.error = str(exc)[:2000]
        job.finished_at = datetime.now(UTC)
        document.status = "failed"
        document.updated_at = job.finished_at
        raise
