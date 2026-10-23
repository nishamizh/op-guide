import re

INJECTION_PATTERNS = [
    r"ignore (all|any|previous|prior) instructions",
    r"system prompt",
    r"you are now",
    r"developer message",
    r"reveal (the )?(hidden|system)",
    r"<\s*/?\s*(system|assistant|developer)\s*>",
    r"do not follow the manual",
    r"system override",
]

UNSAFE_PATTERNS = [
    r"bypass\w*\s+(the\s+)?(door\s+)?(interlock|guard|safety|e-?stop)",
    r"defeat\w*\s+(the\s+)?(interlock|guard|safety)",
    r"disable\w*\s+(the\s+)?(interlock|guard|safety|e-?stop)",
    r"override\w*\s+(the\s+)?(interlock|guard|safety|e-?stop)",
    r"jump(er)?\s+(the\s+)?(contactor|safety|interlock)",
    r"run\s+with\s+the\s+guard\s+open",
    r"hot\s+wire",
    r"start (the )?(machine|spindle|conveyor|pump) remotely",
    r"stop (the )?(machine|equipment) remotely",
    r"defeat the door",
]

HAZARDOUS_PATTERNS = [
    r"\b(electrical|wiring|spindle replacement|inside the cabinet|lockout|tagout|motor replacement)\b",
    r"\bopen the (guard|cabinet|electrical)\b",
]

REFUSAL_MARKERS = [
    "will not provide",
    "cannot provide",
    "refusing",
    "do not bypass",
    "trained personnel",
    "safety gate",
]

ACTIONABLE_UNSAFE = re.compile(
    r"\b(loosen|jumper|tape over|wedge|remove the interlock|force the guard|defeat the)\b",
    re.I,
)


def text_looks_like_injection(text: str) -> bool:
    sample = (text or "").lower()
    return any(re.search(pattern, sample) for pattern in INJECTION_PATTERNS)


def classify_risk(text: str) -> str:
    sample = text or ""
    if any(re.search(pattern, sample, re.I) for pattern in UNSAFE_PATTERNS):
        return "unsafe"
    if any(re.search(pattern, sample, re.I) for pattern in HAZARDOUS_PATTERNS):
        return "hazardous"
    return "normal"


NEGATION_RE = re.compile(r"\b(do not|don't|never|must not|cannot|can't|will not)\b", re.I)


def _affirmative_match(text: str, pattern: re.Pattern[str]) -> bool:
    for match in pattern.finditer(text):
        prefix = text[max(0, match.start() - 64) : match.start()]
        if not NEGATION_RE.search(prefix):
            return True
    return False


def answer_contains_unsafe_procedure(answer: str) -> bool:
    if not answer:
        return False
    lowered = answer.lower()
    affirmative_action = _affirmative_match(answer, ACTIONABLE_UNSAFE)
    if any(marker in lowered for marker in REFUSAL_MARKERS) and not affirmative_action:
        return False
    if affirmative_action:
        return True
    affirmative_unsafe = any(_affirmative_match(answer, re.compile(pattern, re.I)) for pattern in UNSAFE_PATTERNS)
    return affirmative_unsafe and "step" in lowered
