import uuid

DEMO_NS = uuid.UUID("6f9c0b6e-1c3a-4f0e-9a1d-0a5d5c1e0b11")
SEED_VERSION = "2026-10-23.8"


def demo_uuid(name: str) -> uuid.UUID:
    return uuid.uuid5(DEMO_NS, name)


def document_id(key: str) -> uuid.UUID:
    return demo_uuid(f"doc:{key}")


def version_id(key: str) -> uuid.UUID:
    return demo_uuid(f"ver:{key}")


def chunk_id(document_key: str, index: int, section_id: str) -> uuid.UUID:
    return demo_uuid(f"chunk:{document_key}:{index}:{section_id}")
