"""Input guardrails: cheap checks that run before any model is called."""
import re

MAX_QUESTION_CHARS = 1000

INJECTION = re.compile(
    r"ignore\s+(?:all\s+|any\s+|the\s+|your\s+)?(?:previous|prior|above|earlier)\s+"
    r"(?:instructions|rules|prompts?)"
    r"|disregard\s+(?:all\s+|any\s+|the\s+|your\s+)?(?:previous|prior|above|earlier)"
    r"|(?:reveal|show|print|repeat)\s+(?:me\s+)?(?:your|the)\s+(?:system\s+)?"
    r"(?:prompt|instructions|rules)"
    r"|pretend\s+(?:to\s+be|you\s+are)"
    r"|\bjailbreak\b|\bdeveloper\s+mode\b",
    re.I,
)

EMPTY_MESSAGE = "Please type a question about business registration, tax or compliance."
TOO_LONG_MESSAGE = (
    f"Your question is too long (the limit is {MAX_QUESTION_CHARS} characters). "
    "Please shorten it."
)
INJECTION_MESSAGE = (
    "I can only answer questions about business registration, tax and compliance in "
    "Zimbabwe. I can't follow instructions that change how I work."
)


def check_question(question: str) -> str | None:
    """Return a refusal message if the question must not reach a model, else None."""
    text = (question or "").strip()
    if not text:
        return EMPTY_MESSAGE
    if len(text) > MAX_QUESTION_CHARS:
        return TOO_LONG_MESSAGE
    if INJECTION.search(text):
        return INJECTION_MESSAGE
    return None
