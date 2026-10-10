"""Turn retrieved sources into a validated BusinessChecklist.

Flow: gather numbered sources (local, no tokens) -> ask the model for JSON ->
validate the shape (Pydantic) and the facts (against the sources) -> if anything
fails, show the model the problems and let it repair, up to max_retries times.
"""
import json
import os
import re
from dataclasses import dataclass, field
from datetime import date

from pydantic import BaseModel, ValidationError

from startright import tools
from startright.multiagent import (
    DECLINE_MESSAGE,
    FOOTER,
    KEYWORDS,
    SPECIALISTS,
    ungrounded_claims,
)
from startright.schemas import BusinessChecklist

MAX_RETRIES = 2
MIN_SCORE = tools.MIN_SCORE
SOURCE_CHARS = 700


class StructuredOutputError(Exception):
    def __init__(self, errors: list[list[str]], tokens: int):
        self.errors = errors
        self.tokens = tokens
        last = "; ".join(errors[-1]) if errors else "unknown"
        super().__init__(f"no valid output after {len(errors)} attempt(s): {last}")


@dataclass
class StructuredResult:
    value: BaseModel
    attempts: int
    tokens: int
    errors: list[list[str]] = field(default_factory=list)


@dataclass
class ChecklistResult:
    text: str
    checklist: BusinessChecklist | None = None
    sources: dict[int, dict] = field(default_factory=dict)
    attempts: int = 0
    tokens: int = 0
    errors: list[list[str]] = field(default_factory=list)
    declined: bool = False


def extract_json(text: str) -> str:
    """Take the outermost {...} so code fences or chatter around it do not matter."""
    start, end = text.find("{"), text.rfind("}")
    return text[start : end + 1] if start != -1 and end > start else text


def generate_structured(client, model, messages, schema, validate=None,
                        max_retries: int = MAX_RETRIES) -> StructuredResult:
    """Ask for JSON that fits `schema`; on failure show the model what was wrong."""
    messages = list(messages)
    extra = {"reasoning_effort": "low"} if "gpt-oss" in model else {}
    tokens, history = 0, []
    for attempt in range(1, max_retries + 2):
        response = client.chat.completions.create(
            model=model, messages=messages, temperature=0,
            max_completion_tokens=2500, **extra,
        )
        if response.usage:
            tokens += response.usage.total_tokens
        text = response.choices[0].message.content or ""
        value, problems = None, []
        try:
            value = schema.model_validate_json(extract_json(text))
        except ValidationError as exc:
            problems = [
                f"{'.'.join(str(p) for p in e['loc']) or 'reply'}: {e['msg']}"
                for e in exc.errors()
            ]
        if value is not None and validate:
            problems = validate(value)
        if not problems:
            return StructuredResult(value, attempt, tokens, history)
        history.append(problems)
        messages += [
            {"role": "assistant", "content": text},
            {"role": "user", "content": "Your JSON was rejected:\n- "
             + "\n- ".join(problems[:8]) + "\nReturn the corrected JSON only."},
        ]
    raise StructuredOutputError(history, tokens)


def validate_against_sources(checklist: BusinessChecklist, sources: dict[int, dict]) -> list[str]:
    """Fact checks that a schema cannot do: every step must be backed by its source."""
    problems = []
    for step in checklist.steps:
        source = sources.get(step.source_n)
        if source is None:
            problems.append(
                f"step {step.order} cites source {step.source_n}, which was not provided"
                f" (valid numbers: {sorted(sources)})"
            )
            continue
        text = source["text"]
        numbers = {float(x) for x in re.findall(r"\d+(?:\.\d+)?", text.replace(",", ""))}
        for fee in step.fees:
            if float(fee.amount) not in numbers:
                problems.append(
                    f"step {step.order}: fee '{fee.description}' of {fee.amount} does not "
                    f"appear in source {step.source_n}; remove it or list it under not_covered"
                )
        claim_text = f"{step.action} {step.deadline or ''}"
        for claim in ungrounded_claims(claim_text, text):
            problems.append(
                f"step {step.order}: '{claim}' does not appear in source {step.source_n}"
            )
    return problems


def gather_sources(question: str) -> dict[int, dict]:
    """Search each relevant specialist's documents (local embeddings, zero tokens)."""
    domains = ["registration", "tax"]
    if any(word in question.lower() for word in KEYWORDS["employment"]):
        domains.append("employment")
    sources: dict[int, dict] = {}
    for key in domains:
        for hit in tools._fetch_hits(question, top_k=3, scope=list(SPECIALISTS[key].scope)):
            if hit["score"] >= MIN_SCORE:
                sources[len(sources) + 1] = {
                    "title": hit["title"],
                    "page": hit["page"],
                    "source_type": hit["source_type"],
                    "date": str(hit["doc_date"]) if hit["doc_date"] else "date unknown",
                    "text": hit["content"][:SOURCE_CHARS],
                }
    return sources


SYSTEM_PROMPT = (
    "You turn numbered SOURCES into a checklist for starting or running a business "
    "in Zimbabwe. Reply with JSON only, matching this JSON Schema:\n{schema}\n"
    "Rules:\n"
    "1. Use only what the sources state. Every step must set source_n to the number "
    "of the source that states it.\n"
    "2. Include a fee only if its exact amount appears in that source. Use ISO "
    "currency codes.\n"
    "3. Never write placeholders such as '?', 'TBD', 'N/A' or 'see Act'.\n"
    "4. If the sources do not state something an owner needs (fees, timelines, forms, "
    "registration steps), list it under not_covered instead of guessing.\n"
    "5. Number the steps 1, 2, 3 in the order an owner should do them.\n"
    "6. Include only steps that apply to the person in the question. Ignore sources "
    "about other situations (for example foreign companies or non-residents) unless "
    "the question mentions them.\n"
    "7. Set office whenever a source names the body to deal with (for example the "
    "Registrar of Companies, ZIMRA or a council); otherwise leave it null.\n"
    "8. not_covered means 'not found in the sources given above', not 'does not "
    "exist'. Today's date is {today}."
)


def build_messages(question: str, sources: dict[int, dict], today: date) -> list[dict]:
    schema = BusinessChecklist.model_json_schema()
    blocks = [
        f"[{n}] {s['title']} (page {s['page']}, {s['source_type']}, {s['date']})\n{s['text']}"
        for n, s in sources.items()
    ]
    return [
        {"role": "system", "content": SYSTEM_PROMPT.replace(
            "{schema}", json.dumps(schema)).replace("{today}", today.isoformat())},
        {"role": "user", "content": "SOURCES:\n\n" + "\n\n".join(blocks)
         + f"\n\nQuestion: {question}"},
    ]


def render_checklist(checklist: BusinessChecklist, sources: dict[int, dict]) -> str:
    lines = [f"Checklist: {checklist.business}", ""]
    for step in checklist.steps:
        lines.append(f"{step.order}. {step.action} [{step.source_n}]")
        if step.office:
            lines.append(f"   Office: {step.office}")
        for fee in step.fees:
            lines.append(f"   Fee: {fee.description}: {fee.currency} {fee.amount:f}")
        if step.deadline:
            lines.append(f"   Deadline: {step.deadline}")
    if checklist.not_covered:
        lines += ["", "Not found in the sources retrieved for this question (confirm with "
                  "the official office):"]
        lines += [f"- {item}" for item in checklist.not_covered]
    used = sorted({step.source_n for step in checklist.steps if step.source_n in sources})
    lines += ["", "Sources:"]
    lines += [f"[{n}] {sources[n]['title']} (page {sources[n]['page']})" for n in used]
    return "\n".join(lines) + "\n\n" + FOOTER


def make_checklist(question: str, client=None, model: str | None = None,
                   today: date | None = None) -> ChecklistResult:
    sources = gather_sources(question)
    if not sources:
        # Nothing relevant in the documents: refuse without calling the model.
        return ChecklistResult(text=DECLINE_MESSAGE, declined=True)
    if client is None:
        from groq import Groq

        client = Groq()
    model = model or os.environ["GROQ_MODEL"]
    today = today or date.today()
    try:
        result = generate_structured(
            client, model, build_messages(question, sources, today), BusinessChecklist,
            validate=lambda checklist: validate_against_sources(checklist, sources),
        )
    except StructuredOutputError as exc:
        return ChecklistResult(
            text="I could not produce a checklist that passes all checks: "
            + "; ".join(exc.errors[-1]) + "\n\n" + FOOTER,
            sources=sources, attempts=len(exc.errors), tokens=exc.tokens, errors=exc.errors,
        )
    return ChecklistResult(
        text=render_checklist(result.value, sources), checklist=result.value,
        sources=sources, attempts=result.attempts, tokens=result.tokens, errors=result.errors,
    )
