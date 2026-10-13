"""An optional Guardrails AI layer on top of StartRight's own guardrails.

StartRight already has code guardrails (startright.guardrails.check_question, the score
threshold, the grounding check). This module runs the same kind of checks through the
Guardrails AI framework (https://github.com/guardrails-ai/guardrails), so each rule is a
declared validator attached to a Guard, with a standard pass / fail / fix outcome.

  input guard   1. valid-question   re-uses check_question (length, prompt injection, ...)
                2. no-personal-data masks Zimbabwean ID numbers, phone numbers and emails
                                    BEFORE the text is sent to the language model
  output guard  3. has-citation     an answer must cite sources, and only sources that exist

Switch it on with GUARDRAILS_AI=on and `pip install -r requirements-guardrails.txt`. It is off by
default because the package is large (about 450 MB installed, about 120 MB of memory to import),
which does not fit the 512 MB hosted server. Without it the rest of the app is unchanged.

PRIVACY: Guardrails AI sends anonymous usage traces to its own server unless told not to.
_load() replaces that exporter with one that discards everything, so no question text or
personal data leaves the app through this library (tests/test_guards.py checks this).
"""
from __future__ import annotations

import importlib.util
import os
import re
from functools import lru_cache

# ---------- personal data: lives in startright.privacy (works with or without Guardrails AI) ----------

from startright.privacy import PERSONAL_DATA, mask_personal_data  # noqa: E402,F401


CITATION = re.compile(r"\[(\d+)\]")


def citation_problems(body: str, source_numbers: set[int]) -> list[str]:
    """Plain-Python version of the output rule, shared by the validator and the tests."""
    cited = {int(n) for n in CITATION.findall(body)}
    if not source_numbers:
        return []  # nothing to cite (for example a refusal)
    if not cited:
        return ["the answer cites no sources"]
    unknown = sorted(cited - set(source_numbers))
    return [f"the answer cites [{n}], which is not one of its sources" for n in unknown]


# ---------- Guardrails AI wiring ----------

def available() -> bool:
    return importlib.util.find_spec("guardrails") is not None


def enabled() -> bool:
    return os.getenv("GUARDRAILS_AI", "off").strip().lower() in ("on", "1", "true", "yes") and available()


def status() -> dict:
    return {"requested": os.getenv("GUARDRAILS_AI", "off"), "installed": available(), "active": enabled()}


def _silence_telemetry() -> None:
    """Stop Guardrails AI exporting usage traces to the internet (see the module note)."""
    from guardrails.settings import settings
    from guardrails.utils import hub_telemetry_utils
    from opentelemetry.sdk.trace.export import SpanExporter, SpanExportResult

    class DiscardExporter(SpanExporter):
        def export(self, spans):
            return SpanExportResult.SUCCESS

    hub_telemetry_utils.OTLPSpanExporter = lambda *args, **kwargs: DiscardExporter()
    settings.rc.enable_metrics = False
    settings.disable_tracing = True


@lru_cache(maxsize=1)
def _load():
    """Import Guardrails AI (once) with telemetry off, and build the two guards."""
    _silence_telemetry()
    from guardrails import Guard, OnFailAction
    from guardrails.validators import FailResult, PassResult, Validator, register_validator

    from startright.guardrails import check_question

    @register_validator(name="startright/valid-question", data_type="string")
    class ValidQuestion(Validator):
        def _validate(self, value, metadata):
            refusal = check_question(value)
            return FailResult(error_message=refusal) if refusal else PassResult()

    @register_validator(name="startright/no-personal-data", data_type="string")
    class NoPersonalData(Validator):
        def _validate(self, value, metadata):
            masked, found = mask_personal_data(value)
            if not found:
                return PassResult()
            return FailResult(error_message="personal data found: " + ", ".join(found), fix_value=masked)

    @register_validator(name="startright/has-citation", data_type="string")
    class HasCitation(Validator):
        def _validate(self, value, metadata):
            problems = citation_problems(value, set((metadata or {}).get("source_numbers", ())))
            return FailResult(error_message="; ".join(problems)) if problems else PassResult()

    question_guard = Guard(name="startright-input").use(
        ValidQuestion(on_fail=OnFailAction.NOOP),
        NoPersonalData(on_fail=OnFailAction.FIX),
    )
    answer_guard = Guard(name="startright-output").use(HasCitation(on_fail=OnFailAction.NOOP))
    return question_guard, answer_guard


def _failures(guard, only: tuple[str, ...] = ()) -> list[str]:
    """Error messages from the validators that failed in the guard's most recent run."""
    last = guard.history.last
    if last is None or last.iterations.last is None:
        return []
    return [str(log.validation_result.error_message)
            for log in last.iterations.last.validator_logs
            if getattr(log.validation_result, "outcome", "") == "fail"
            and (not only or log.validator_name in only)]


def screen_input(text: str) -> tuple[str, str | None]:
    """Run the input guard. Returns (text to use, refusal message or None).

    The text to use has personal identifiers masked. A refusal comes from the valid-question
    rule; when it fires the question is not sent anywhere."""
    question_guard, _ = _load()
    outcome = question_guard.validate(text)
    refusals = _failures(question_guard, only=("ValidQuestion", "startright/valid-question"))
    if refusals:
        return text, refusals[0]
    return (outcome.validated_output or text), None


def check_answer(body: str, source_numbers: set[int]) -> list[str]:
    """Run the output guard. Returns a list of problems (empty when the answer is fine)."""
    _, answer_guard = _load()
    answer_guard.validate(body, metadata={"source_numbers": sorted(source_numbers)})
    return _failures(answer_guard)
