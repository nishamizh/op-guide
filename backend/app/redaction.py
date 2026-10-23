import re

SECRET_RE = re.compile(
    r"(sk-[A-Za-z0-9_\-]{8,}|AKIA[0-9A-Z]{16}|-----BEGIN [A-Z ]+PRIVATE KEY-----|"
    r"(?:api[_-]?key|secret|password|token|authorization)\s*[:=]\s*\S+)",
    re.IGNORECASE,
)
EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b")
CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")


def redact(text: str) -> str:
    if not text:
        return text
    cleaned = SECRET_RE.sub("[redacted]", text)
    cleaned = EMAIL_RE.sub("[redacted-email]", cleaned)
    return cleaned


def sanitize_text(value: str, limit: int = 8000) -> str:
    cleaned = CONTROL_RE.sub("", value or "")
    cleaned = cleaned.replace("\r\n", "\n").strip()
    if len(cleaned) > limit:
        cleaned = cleaned[:limit]
    return cleaned


def sanitize_payload(value, depth: int = 0):
    if depth > 6:
        return "[truncated]"
    if isinstance(value, str):
        return redact(sanitize_text(value, 4000))
    if isinstance(value, dict):
        cleaned = {}
        for key, item in value.items():
            key_text = str(key)
            if key_text.lower() in {"password", "secret", "token", "api_key", "authorization"}:
                cleaned[key_text] = "[redacted]"
            else:
                cleaned[key_text] = sanitize_payload(item, depth + 1)
        return cleaned
    if isinstance(value, list):
        return [sanitize_payload(item, depth + 1) for item in value[:40]]
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    return redact(sanitize_text(str(value), 1000))
