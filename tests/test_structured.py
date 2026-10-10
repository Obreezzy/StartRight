import json
from datetime import date
from types import SimpleNamespace as NS

import pytest

from startright import tools
from startright.multiagent import DECLINE_MESSAGE
from startright.schemas import BusinessChecklist
from startright.structured import (
    StructuredOutputError,
    extract_json,
    generate_structured,
    make_checklist,
    render_checklist,
    validate_against_sources,
)

TODAY = date(2026, 10, 9)
SOURCES = {
    1: {"title": "Companies Act", "page": 12, "source_type": "official", "date": "2019-11-15",
        "text": "An application for registration must be lodged with the Registrar. "
                "The prescribed fee is 50 dollars and the Registrar shall act within 14 days."},
    2: {"title": "ZIMRA Notice", "page": 1, "source_type": "notice", "date": "date unknown",
        "text": "VAT returns are due on or before the 10th of the following month."},
}


def reply(content, tokens=100):
    return NS(choices=[NS(message=NS(content=content, tool_calls=None))],
              usage=NS(total_tokens=tokens))


class FakeClient:
    def __init__(self, replies):
        self.replies = list(replies)
        self.requests = []
        self.chat = NS(completions=NS(create=self._create))

    def _create(self, **kwargs):
        self.requests.append({**kwargs, "messages": list(kwargs["messages"])})
        return self.replies.pop(0)


def good(**step_overrides):
    step = {"order": 1, "action": "Lodge the application with the Registrar",
            "office": "Registrar of Companies", "source_n": 1, **step_overrides}
    return json.dumps({"business": "Hair salon", "steps": [step],
                       "not_covered": ["NSSA employer registration steps"]})


# ---------- generate_structured ----------

def test_valid_json_inside_a_code_fence_is_accepted_first_time():
    client = FakeClient([reply("```json\n" + good() + "\n```")])
    result = generate_structured(client, "test-model", [], BusinessChecklist)
    assert result.attempts == 1 and result.errors == []
    assert result.value.steps[0].office == "Registrar of Companies"


def test_invalid_json_is_repaired_and_the_model_sees_the_error():
    client = FakeClient([reply("Sure! Here is your checklist"), reply(good(), tokens=50)])
    result = generate_structured(client, "test-model", [{"role": "user", "content": "go"}],
                                 BusinessChecklist)
    assert result.attempts == 2 and result.tokens == 150
    feedback = client.requests[1]["messages"][-1]["content"]
    assert "rejected" in feedback and "corrected JSON only" in feedback


def test_schema_violations_are_reported_by_field():
    client = FakeClient([reply(good(action="Fill in Form ? at the office")), reply(good())])
    result = generate_structured(client, "test-model", [], BusinessChecklist)
    assert result.attempts == 2
    assert "steps.0.action" in client.requests[1]["messages"][-1]["content"]
    assert "placeholder" in client.requests[1]["messages"][-1]["content"]


def test_gives_up_after_the_retry_limit_with_the_reasons():
    client = FakeClient([reply("nope")] * 3)
    with pytest.raises(StructuredOutputError) as error:
        generate_structured(client, "test-model", [], BusinessChecklist, max_retries=2)
    assert len(error.value.errors) == 3 and error.value.tokens == 300


def test_extract_json_ignores_chatter():
    assert extract_json('Here: {"a": 1} thanks') == '{"a": 1}'


# ---------- fact checks against the sources ----------

def parse(**overrides):
    return BusinessChecklist.model_validate_json(good(**overrides))


def test_a_step_citing_a_missing_source_is_flagged():
    problems = validate_against_sources(parse(source_n=9), SOURCES)
    assert "source 9" in problems[0] and "[1, 2]" in problems[0]


def test_a_fee_that_is_not_in_the_cited_source_is_flagged():
    fee = [{"description": "Registration", "amount": 75, "currency": "USD"}]
    assert any("75" in p for p in validate_against_sources(parse(fees=fee), SOURCES))


def test_a_fee_that_is_in_the_cited_source_passes():
    fee = [{"description": "Registration", "amount": 50, "currency": "USD"}]
    assert validate_against_sources(parse(fees=fee), SOURCES) == []


def test_an_invented_day_count_is_flagged_and_a_stated_one_passes():
    assert any("30 days" in p for p in validate_against_sources(
        parse(action="Lodge the application within 30 days"), SOURCES))
    assert validate_against_sources(
        parse(action="Wait for the Registrar, who acts within 14 days"), SOURCES) == []


# ---------- the whole pipeline ----------

@pytest.fixture
def fake_hits(monkeypatch):
    def fetch(query, top_k=4, scope=None):
        return [{"title": "Companies Act", "page": 12, "source_type": "official",
                 "doc_date": None, "score": 0.7, "content": SOURCES[1]["text"]}]
    monkeypatch.setattr(tools, "_fetch_hits", fetch)


def test_make_checklist_repairs_an_invented_fee_then_renders(fake_hits):
    invented = good(fees=[{"description": "Registration", "amount": 75, "currency": "USD"}])
    client = FakeClient([reply(invented), reply(good())])
    result = make_checklist("I want to open a hair salon", client=client,
                            model="test-model", today=TODAY)
    assert result.attempts == 2 and len(result.errors) == 1
    assert "75" in result.errors[0][0]
    assert "75" not in result.text
    assert "1. Lodge the application with the Registrar [1]" in result.text
    assert "Not found in the sources retrieved" in result.text and "NSSA employer" in result.text
    assert "Sources:\n[1] Companies Act (page 12)" in result.text


def test_make_checklist_declines_without_calling_the_model_when_nothing_matches(monkeypatch):
    monkeypatch.setattr(tools, "_fetch_hits", lambda query, top_k=4, scope=None: [])
    client = FakeClient([])
    result = make_checklist("What is the capital of France?", client=client,
                            model="test-model", today=TODAY)
    assert result.declined and result.text == DECLINE_MESSAGE and client.requests == []


def test_make_checklist_reports_failure_honestly_after_retries(fake_hits):
    client = FakeClient([reply("not json")] * 3)
    result = make_checklist("Open a salon", client=client, model="test-model", today=TODAY)
    assert result.checklist is None and "could not produce a checklist" in result.text
    assert result.attempts == 3


def test_the_prompt_contains_numbered_sources_and_the_schema(fake_hits):
    client = FakeClient([reply(good())])
    make_checklist("Open a salon", client=client, model="test-model", today=TODAY)
    system, user = client.requests[0]["messages"]
    assert "not_covered" in system["content"] and "2026-10-09" in system["content"]
    assert user["content"].startswith("SOURCES:\n\n[1] Companies Act (page 12")


def test_render_lists_only_cited_sources():
    text = render_checklist(parse(), SOURCES)
    assert "[1] Companies Act" in text and "[2] ZIMRA Notice" not in text


def test_the_prompt_tells_the_model_to_skip_irrelevant_situations_and_fill_the_office(fake_hits):
    client = FakeClient([reply(good())])
    make_checklist("Open a salon", client=client, model="test-model", today=TODAY)
    system = client.requests[0]["messages"][0]["content"]
    assert "foreign companies" in system and "Set office" in system
