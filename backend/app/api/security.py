import base64
import hashlib
import hmac
import re
import uuid
from dataclasses import dataclass

from fastapi import Header

from app.config import get_settings
from app.errors import AppError

SCOPE_RE = re.compile(r"^[A-Za-z0-9_.:-]{1,64}$")


@dataclass
class Scope:
    tenant_id: str
    user_id: str


def get_scope(
    authorization: str | None = Header(default=None),
    x_tenant_id: str = Header(default=""),
    x_user_id: str = Header(default=""),
) -> Scope:
    if authorization and authorization.lower().startswith("bearer "):
        session_id, tenant, user = parse_token(authorization.split(" ", 1)[1].strip())
        return Scope(tenant, user)
    tenant = (x_tenant_id or "").strip() or get_settings().default_tenant_id
    user = (x_user_id or "").strip() or "operator"
    if not SCOPE_RE.fullmatch(tenant) or not SCOPE_RE.fullmatch(user):
        raise AppError("invalid_scope", "Tenant and user ids must be 1-64 safe characters.", 400)
    return Scope(tenant, user)


def issue_token(session_id: uuid.UUID, tenant_id: str, user_id: str) -> str:
    payload = f"{session_id}|{tenant_id}|{user_id}"
    signature = hmac.new(
        get_settings().session_secret.encode(),
        payload.encode(),
        hashlib.sha256,
    ).hexdigest()
    raw = f"{payload}|{signature}".encode()
    return base64.urlsafe_b64encode(raw).decode()


def parse_token(token: str) -> tuple[str, str, str]:
    try:
        decoded = base64.urlsafe_b64decode(token.encode()).decode()
        session_id, tenant_id, user_id, signature = decoded.split("|")
        uuid.UUID(session_id)
    except Exception as exc:
        raise AppError("invalid_token", "Session token is not valid.", 401) from exc
    payload = f"{session_id}|{tenant_id}|{user_id}"
    expected = hmac.new(
        get_settings().session_secret.encode(),
        payload.encode(),
        hashlib.sha256,
    ).hexdigest()
    if not hmac.compare_digest(signature, expected):
        raise AppError("invalid_token", "Session token is not valid.", 401)
    return session_id, tenant_id, user_id
