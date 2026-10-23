from dataclasses import dataclass, field

import tiktoken

from app.ingestion.parser import ParsedPage

_ENCODER = None


def encoder():
    global _ENCODER
    if _ENCODER is None:
        _ENCODER = tiktoken.get_encoding("cl100k_base")
    return _ENCODER


def count_tokens(text: str) -> int:
    return len(encoder().encode(text or ""))


@dataclass
class ChunkDraft:
    content: str
    token_count: int
    page_start: int
    page_end: int
    section_id: str
    section_title: str
    section_ids: list[str]
    has_table: bool
    injection_suspected: bool
    overlap_tokens: int = 0
    metadata: dict = field(default_factory=dict)


@dataclass
class _Block:
    text: str
    tokens: list[int]
    page: int
    section_id: str
    section_title: str
    has_table: bool
    injection_suspected: bool


def chunk_pages(
    pages: list[ParsedPage],
    target: int = 700,
    minimum: int = 500,
    maximum: int = 800,
    overlap: int = 100,
) -> list[ChunkDraft]:
    blocks: list[_Block] = []
    for page in pages:
        for section in page.sections:
            text = f"{section.title}\n{section.text}".strip()
            tokens = encoder().encode(text)
            if not tokens:
                continue
            if len(tokens) <= maximum:
                blocks.append(
                    _Block(
                        text,
                        tokens,
                        page.page,
                        section.section_id,
                        section.title,
                        section.has_table,
                        section.injection_suspected,
                    )
                )
            else:
                start = 0
                part = 1
                while start < len(tokens):
                    end = min(start + target, len(tokens))
                    piece = tokens[start:end]
                    blocks.append(
                        _Block(
                            encoder().decode(piece),
                            piece,
                            page.page,
                            section.section_id,
                            section.title,
                            section.has_table,
                            section.injection_suspected,
                        )
                    )
                    if end >= len(tokens):
                        break
                    start = max(end - overlap, start + 1)
                    part += 1
                    if part > 200:
                        break
    if not blocks:
        return []

    chunks: list[ChunkDraft] = []
    current: list[_Block] = []
    current_tokens = 0

    def emit(group: list[_Block], overlap_tokens: int) -> ChunkDraft:
        content = "\n\n".join(block.text for block in group).strip()
        counts: dict[str, int] = {}
        titles: dict[str, str] = {}
        for block in group:
            counts[block.section_id] = counts.get(block.section_id, 0) + len(block.tokens)
            titles[block.section_id] = block.section_title
        primary = max(counts, key=counts.get)
        # A short overlap tail must not make this chunk a citation for the previous section.
        section_ids = [
            section_id
            for section_id in dict.fromkeys(block.section_id for block in group)
            if counts.get(section_id, 0) >= 200 or section_id == primary
        ]
        counted = [block for block in group if block.section_id in section_ids]
        return ChunkDraft(
            content=content,
            token_count=count_tokens(content),
            page_start=min(block.page for block in counted),
            page_end=max(block.page for block in counted),
            section_id=primary,
            section_title=titles[primary],
            section_ids=section_ids,
            has_table=any(block.has_table for block in group),
            injection_suspected=any(block.injection_suspected for block in group),
            overlap_tokens=overlap_tokens,
            metadata={"section_token_counts": counts},
        )

    for block in blocks:
        block_len = len(block.tokens)
        if current and current_tokens + block_len > maximum and current_tokens >= minimum:
            chunks.append(emit(current, 0 if not chunks else overlap))
            tail = _overlap_block(current, overlap)
            current = [tail, block] if tail else [block]
            current_tokens = sum(len(item.tokens) for item in current)
        else:
            current.append(block)
            current_tokens += block_len
    if current:
        if chunks and current_tokens < minimum:
            previous = chunks[-1]
            merged_blocks = current
            combined = count_tokens(previous.content + "\n\n" + "\n\n".join(b.text for b in merged_blocks))
            if combined <= maximum:
                chunks[-1] = emit(
                    [
                        _Block(
                            previous.content,
                            encoder().encode(previous.content),
                            previous.page_start,
                            previous.section_id,
                            previous.section_title,
                            previous.has_table,
                            previous.injection_suspected,
                        ),
                        *merged_blocks,
                    ],
                    previous.overlap_tokens,
                )
            else:
                chunks.append(emit(current, overlap))
        else:
            chunks.append(emit(current, overlap if chunks else 0))
    return [_fit(chunk, maximum) for chunk in chunks]


def _fit(draft: ChunkDraft, maximum: int) -> ChunkDraft:
    if draft.token_count <= maximum:
        return draft
    tokens = encoder().encode(draft.content)[:maximum]
    draft.content = encoder().decode(tokens)
    draft.token_count = count_tokens(draft.content)
    return draft


def _overlap_block(group: list[_Block], overlap: int) -> _Block | None:
    if overlap <= 0 or not group:
        return None
    last = group[-1]
    if len(last.tokens) <= overlap:
        return last
    piece = last.tokens[-overlap:]
    return _Block(
        encoder().decode(piece),
        piece,
        last.page,
        last.section_id,
        last.section_title,
        False,
        last.injection_suspected,
    )
