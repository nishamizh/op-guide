import re
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.ingestion.embeddings import embed_texts, vector_space_name
from app.models import AppMeta, Document, DocumentChunk
from app.retrieval.bm25 import bm25_index, tokenize
from app.retrieval.rrf import reciprocal_rank_fusion

ERROR_RE = re.compile(r"\b([A-Za-z]\d{3,4})\b")
MODEL_TOKENS = {"R200", "R500", "P300"}
NUMBER_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(bar|psi|deg c|°c|celsius|rpm|l/min|amp)", re.I)


def ensure_bm25(db: Session) -> int:
    meta = db.get(AppMeta, 1)
    revision = meta.index_revision if meta else 0
    if bm25_index.revision == revision and bm25_index.doc_ids:
        return revision
    rows = db.execute(
        select(
            DocumentChunk.id,
            DocumentChunk.content,
            DocumentChunk.tenant_id,
            DocumentChunk.manufacturer,
            DocumentChunk.machine_model,
            DocumentChunk.revision,
            DocumentChunk.section_id,
            DocumentChunk.section_ids,
            DocumentChunk.section_title,
            DocumentChunk.page_start,
            DocumentChunk.page_end,
            DocumentChunk.document_id,
            DocumentChunk.injection_suspected,
            DocumentChunk.has_table,
            DocumentChunk.embedding_model,
            DocumentChunk.effective_date,
            DocumentChunk.token_count,
            Document.title,
        ).join(Document, Document.id == DocumentChunk.document_id)
    ).all()
    payload = []
    for row in rows:
        payload.append(
            {
                "id": str(row.id),
                "content": row.content,
                "tenant_id": row.tenant_id,
                "manufacturer": row.manufacturer,
                "machine_model": row.machine_model,
                "revision": row.revision,
                "section_id": row.section_id,
                "section_ids": row.section_ids or [],
                "section_title": row.section_title,
                "page_start": row.page_start,
                "page_end": row.page_end,
                "document_id": str(row.document_id),
                "injection_suspected": row.injection_suspected,
                "has_table": row.has_table,
                "embedding_model": row.embedding_model,
                "effective_date": row.effective_date.isoformat() if row.effective_date else None,
                "token_count": row.token_count,
                "document_title": row.title,
            }
        )
    bm25_index.rebuild(payload, revision)
    return revision


def _allowed_ids(
    tenant_id: str,
    manufacturer: str | None,
    machine_model: str | None,
) -> set[str]:
    allowed = set()
    manufacturer_key = (manufacturer or "").lower()
    model_key = (machine_model or "").lower()
    for doc_id, meta in bm25_index.meta.items():
        if meta["tenant_id"] != tenant_id:
            continue
        if manufacturer_key and meta["manufacturer"].lower() != manufacturer_key:
            continue
        if model_key and meta["machine_model"].lower() != model_key:
            continue
        allowed.add(doc_id)
    return allowed


def vector_search(
    db: Session,
    query: str,
    allowed_ids: set[str],
    top_k: int,
) -> tuple[list[dict], str, str]:
    if not allowed_ids:
        return [], vector_space_name(), ""
    vectors, model_name = embed_texts([query])
    query_vector = vectors[0]
    distance = DocumentChunk.embedding.cosine_distance(query_vector)
    stmt = (
        select(DocumentChunk.id, distance.label("distance"))
        .where(DocumentChunk.id.in_([_as_uuid(item) for item in allowed_ids]))
        .where(DocumentChunk.embedding_model == model_name)
        .order_by(distance)
        .limit(top_k)
    )
    hits = []
    for rank, row in enumerate(db.execute(stmt).all(), start=1):
        cosine_distance = float(row.distance)
        similarity = 1.0 - cosine_distance
        hits.append(
            {
                "id": str(row.id),
                "rank": rank,
                "cosine_distance": cosine_distance,
                "cosine_similarity": similarity,
            }
        )
    return hits, vector_space_name(), model_name


def _as_uuid(value: str):
    import uuid

    return uuid.UUID(value)


def hybrid_search(
    db: Session,
    query: str,
    tenant_id: str,
    manufacturer: str | None,
    machine_model: str | None,
) -> dict:
    settings = get_settings()
    revision = ensure_bm25(db)
    allowed = _allowed_ids(tenant_id, manufacturer, machine_model)
    bm25_hits = bm25_index.search(query, settings.bm25_top_k, allowed)
    vector_hits, space, model_name = vector_search(db, query, allowed, settings.vector_top_k)
    fused = reciprocal_rank_fusion(
        {
            "bm25": [hit["id"] for hit in bm25_hits],
            "vector": [hit["id"] for hit in vector_hits],
        },
        weights={"bm25": settings.rrf_weight_bm25, "vector": settings.rrf_weight_vector},
        k=settings.rrf_k,
    )
    bm25_by_id = {hit["id"]: hit for hit in bm25_hits}
    vector_by_id = {hit["id"]: hit for hit in vector_hits}
    pool = fused[: settings.rerank_pool]
    max_bm25 = max((bm25_by_id.get(item["id"], {}).get("score") or 0) for item in pool) if pool else 1.0
    reranked = [
        _rerank_hit(item, query, bm25_by_id, vector_by_id, manufacturer, machine_model, max_bm25 or 1.0)
        for item in pool
    ]
    reranked.sort(key=lambda item: item["rerank_score"], reverse=True)
    reranked = _keep_conflicts(reranked, settings.return_k, query)
    return {
        "index_revision": revision,
        "vector_space": space,
        "embedding_model": model_name,
        "bm25_hits": bm25_hits,
        "vector_hits": vector_hits,
        "fused": fused[: settings.rerank_pool],
        "evidence": reranked,
        "fusion": {
            "k": settings.rrf_k,
            "formula": "weight/(k+rank)",
            "weights": {"bm25": settings.rrf_weight_bm25, "vector": settings.rrf_weight_vector},
            "vector_top_k": settings.vector_top_k,
            "bm25_top_k": settings.bm25_top_k,
            "note": "RRF contributions are rank heuristics, not calibrated probabilities.",
        },
    }


def _rerank_hit(
    item: dict,
    query: str,
    bm25_by_id: dict,
    vector_by_id: dict,
    manufacturer: str | None,
    machine_model: str | None,
    max_bm25: float,
) -> dict:
    meta = bm25_index.meta[item["id"]]
    query_terms = set(tokenize(query))
    content_terms = set(tokenize(meta["content"]))
    rare = [term for term in tokenize(query) if term not in COMMON_TERMS and len(term) > 2]
    coverage = (len(query_terms & content_terms) / len(query_terms)) if query_terms else 0.0
    rare_coverage = (sum(1 for term in rare if term in content_terms) / len(rare)) if rare else 0.0
    error_codes = {match.group(1).upper() for match in ERROR_RE.finditer(query)} - MODEL_TOKENS
    content_codes = {match.group(1).upper() for match in ERROR_RE.finditer(meta["content"])} - MODEL_TOKENS
    section_code = 1.0 if any(code.lower() in (meta["section_id"] or "").lower() for code in error_codes) else 0.0
    # A passing mention of the code in another section is a weak hint. The section written
    # for that code is the one a citation should lead with.
    if section_code:
        error_match = 1.0
    elif error_codes and error_codes & content_codes:
        error_match = 0.35
    else:
        error_match = 0.0
    meta_match = 0.0
    if manufacturer and meta["manufacturer"].lower() == manufacturer.lower():
        meta_match += 0.5
    if machine_model and meta["machine_model"].lower() == machine_model.lower():
        meta_match += 0.5
    title_terms = set(tokenize(f"{meta['section_title']} {meta['section_id']}"))
    title_overlap = (len(set(rare) & title_terms) / len(rare)) if rare else 0.0
    latest_bonus = _revision_bonus(meta)
    vector_hit = vector_by_id.get(item["id"])
    vector_similarity = vector_hit["cosine_similarity"] if vector_hit else 0.0
    bm25_hit = bm25_by_id.get(item["id"])
    bm25_norm = min(1.0, ((bm25_hit or {}).get("score") or 0) / max_bm25) if max_bm25 else 0.0
    # Scale against rank-1 on both lists. With k=60 the top ranks are close, so BM25 and the
    # section title carry the ordering. RRF stays in the trace as the fusion prior.
    rrf_norm = min(1.0, item["rrf_score"] / (2.0 / 61.0))
    injection_penalty = 0.45 if meta["injection_suspected"] else 0.0
    relevance = (
        0.22 * bm25_norm
        + 0.16 * title_overlap
        + 0.08 * rare_coverage
        + 0.06 * rrf_norm
        + 0.05 * meta_match
        + 0.10 * error_match
        + 0.24 * section_code
        + 0.05 * latest_bonus
        + 0.04 * max(0.0, vector_similarity)
        - injection_penalty
    )
    relevance = max(0.0, min(1.0, relevance))
    snippet = meta["content"].strip().replace("\n", " ")
    if len(snippet) > 480:
        snippet = snippet[:477] + "..."
    return {
        "chunk_id": item["id"],
        "document_id": meta["document_id"],
        "rrf_score": item["rrf_score"],
        "rrf_parts": item["parts"],
        "vector_rank": (vector_hit or {}).get("rank"),
        "bm25_rank": (bm25_hit or {}).get("rank"),
        "vector_similarity": vector_similarity,
        "bm25_score": (bm25_hit or {}).get("score"),
        "rerank_score": round(relevance, 4),
        "score_components": {
            "rrf_norm": round(rrf_norm, 4),
            "bm25_norm": round(bm25_norm, 4),
            "coverage": round(coverage, 4),
            "rare_coverage": round(rare_coverage, 4),
            "meta_match": meta_match,
            "error_match": error_match,
            "section_code": section_code,
            "title_overlap": round(title_overlap, 4),
            "revision_preference": latest_bonus,
            "cosine_similarity": None if vector_hit is None else round(vector_similarity, 4),
            "injection_penalty": injection_penalty,
            "note": "Heuristic rerank. Cosine similarity is not a probability.",
        },
        "page_start": meta["page_start"],
        "page_end": meta["page_end"],
        "section_id": meta["section_id"],
        "section_title": meta["section_title"],
        "section_ids": meta["section_ids"] or [meta["section_id"]],
        "revision": meta["revision"],
        "effective_date": meta["effective_date"],
        "snippet": snippet,
        "content": meta["content"],
        "manufacturer": meta["manufacturer"],
        "machine_model": meta["machine_model"],
        "document_title": meta.get("document_title"),
        "injection_suspected": meta["injection_suspected"],
        "has_table": meta["has_table"],
        "evidence_type": "manual",
        "mock": False,
    }


def _revision_bonus(meta: dict) -> float:
    same = [
        other
        for other in bm25_index.meta.values()
        if other["tenant_id"] == meta["tenant_id"]
        and other["manufacturer"] == meta["manufacturer"]
        and other["machine_model"] == meta["machine_model"]
    ]
    dates = [_parse_date(item["effective_date"]) for item in same]
    dates = [item for item in dates if item is not None]
    this_date = _parse_date(meta["effective_date"])
    if not dates or this_date is None:
        return 0.5
    if this_date == max(dates):
        return 1.0
    return 0.35


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    year, month, day = value.split("-")
    return date(int(year), int(month), int(day))


def _keep_conflicts(reranked: list[dict], return_k: int, query: str) -> list[dict]:
    selected = list(reranked[:return_k])
    selected_ids = {item["chunk_id"] for item in selected}
    codes = {match.group(1).upper() for match in ERROR_RE.finditer(query)} - MODEL_TOKENS
    about_revision = bool(re.search(r"revision|setpoint|conflict|which manual", query, re.I))
    conflicts = find_conflicts(reranked)
    if codes:
        conflicts = [group for group in conflicts if (group.get("error_code") or "").upper() in codes]
    elif not about_revision:
        conflicts = []
    for group in conflicts:
        for chunk_id in group["chunk_ids"]:
            if chunk_id in selected_ids:
                continue
            match = next(item for item in reranked if item["chunk_id"] == chunk_id)
            placed = False
            for index in range(min(len(selected), 5) - 1, 0, -1):
                if codes and _chunk_has_code(selected[index], codes):
                    continue
                selected_ids.discard(selected[index]["chunk_id"])
                selected[index] = match
                selected_ids.add(chunk_id)
                placed = True
                break
            if not placed and len(selected) < 8:
                selected.append(match)
                selected_ids.add(chunk_id)
    for index, item in enumerate(selected, start=1):
        item["rank"] = index
    return selected


def _chunk_has_code(item: dict, codes: set[str]) -> bool:
    blob = f"{item.get('section_id') or ''} {' '.join(item.get('section_ids') or [])}".lower()
    return any(code.lower() in blob for code in codes)


COMMON_TERMS = {
    "what", "does", "the", "how", "manual", "alarm", "error", "mean", "meaning", "machine",
    "with", "and", "for", "can", "technician", "approved", "checks", "perform", "current",
    "status", "compare", "this", "that", "from", "your", "about", "when", "where", "which",
    "should", "would", "could", "into", "using", "show", "list", "basic", "fictional",
}


def rare_terms(query: str) -> list[str]:
    return [term for term in tokenize(query) if term not in COMMON_TERMS and len(term) > 2]


GENERIC_CONTENT_TERMS = COMMON_TERMS | {
    "troubleshooting",
    "cause",
    "setpoint",
    "revision",
    "pressure",
    "pressures",
    "low",
    "technician",
    "perform",
    "diagnose",
    "diagnostics",
    "sensors",
    "sensor",
    "startup",
    "basic",
    "list",
    "coolant",
    "flow",
    "trip",
    "photoeye",
    "photoeyes",
    "approved",
    "observation",
    "fictional",
    "demo",
}


def evidence_supports_query(query: str, evidence: list[dict]) -> bool:
    """Support is judged on the operator's question, not on reformulation filler.

    An error code in the question must appear in retrieved text or section ids.
    Other identifying tokens (a manufacturer or model name that is not generic
    troubleshooting language) must mostly appear. This is a heuristic gate.
    """
    if not evidence:
        return False
    codes = {match.group(1).upper() for match in ERROR_RE.finditer(query)} - MODEL_TOKENS
    blob = " ".join(
        " ".join(
            [
                item.get("content") or "",
                item.get("section_id") or "",
                item.get("section_title") or "",
                item.get("manufacturer") or "",
                item.get("machine_model") or "",
                " ".join(item.get("section_ids") or []),
            ]
        )
        for item in evidence
    ).lower()
    if codes:
        # The asked alarm is either in the indexed text or it is not. Instruction-like
        # words in the same question must not veto a code that was actually retrieved.
        return any(code.lower() in blob for code in codes)
    identifying = [term for term in rare_terms(query) if term not in GENERIC_CONTENT_TERMS and term not in {c.lower() for c in codes}]
    if not identifying:
        return True
    hits = sum(1 for term in identifying if term in blob)
    return hits / len(identifying) >= 0.5


def find_conflicts(evidence: list[dict]) -> list[dict]:
    grouped: dict[tuple, list[tuple[dict, set[tuple[str, str]]]]] = {}
    for item in evidence:
        if item.get("injection_suspected"):
            continue
        content = item.get("content") or ""
        section_codes = {
            match.group(1).upper() for match in ERROR_RE.finditer(item.get("section_id") or "")
        } - MODEL_TOKENS
        focus = section_codes or set()
        if not focus:
            continue
        lines = [
            line
            for line in content.splitlines()
            if any(code.lower() in line.lower() for code in focus)
            or "setpoint" in line.lower()
            or "trip" in line.lower()
        ]
        numbers = {
            (match.group(1), match.group(2).lower().replace("°c", "deg c").replace("celsius", "deg c"))
            for match in NUMBER_RE.finditer("\n".join(lines))
        }
        # Keep one unit family when the section is about a single alarm so rpm and temperature
        # from neighboring sentences are not treated as the same fact.
        if section_codes and numbers:
            units = {unit for _value, unit in numbers}
            if "bar" in units:
                numbers = {pair for pair in numbers if pair[1] == "bar"}
        if not numbers:
            continue
        for code in focus:
            key = (item.get("manufacturer"), item.get("machine_model"), code)
            grouped.setdefault(key, []).append((item, numbers))
    conflicts = []
    for key, rows in grouped.items():
        revisions: dict[str, set[tuple[str, str]]] = {}
        chunk_ids = []
        for item, numbers in rows:
            revisions.setdefault(item.get("revision") or "", set()).update(numbers)
            chunk_ids.append(item["chunk_id"])
        if len(revisions) < 2:
            continue
        per_revision_values = {revision: sorted(values) for revision, values in revisions.items()}
        unique_values = {tuple(sorted(values)) for values in per_revision_values.values()}
        if len(unique_values) < 2:
            continue
        conflicts.append(
            {
                "manufacturer": key[0],
                "machine_model": key[1],
                "error_code": key[2] or None,
                "revisions": per_revision_values,
                "chunk_ids": chunk_ids,
            }
        )
    return conflicts
