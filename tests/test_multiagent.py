import json
from datetime import date
from types import SimpleNamespace as NS

import pytest

from startright import tools
from startright.multiagent import (
    DECLINE_MESSAGE,
    SPECIALISTS,
    keyword_route,
    parse_plan,
    run_team,
    verify_finding,
)

TODAY = date(2026, 10, 9)


def tool_call(call_id, name, arguments):
    return NS(id=call_id, function=NS(name=name, arguments=json.dumps(arguments)))


def reply(content=None, tool_calls=None, tokens=10):
    message = NS(content=content, tool_calls=tool_calls)
    return NS(choices=[NS(message=message)], usage=NS(total_tokens=tokens))


class FakeClient:
    def __init__(self, replies):
        self.replies = list(replies)
        self.requests = []
        self.chat = NS(completions=NS(create=self._create))

    def _create(self, **kwargs):
        self.requests.append({**kwargs, "messages": list(kwargs["messages"])})
        return self.replies.pop(0)


def plan(*pairs, decline=False):
    return reply(content=json.dumps(
        {"decline": decline, "subtasks": [{"agent": a, "task": t} for a, t in pairs]}
    ))


def search(call_id="s"):
    return reply(tool_calls=[tool_call(call_id, "search_regulations", {"query": "x"})])


@pytest.fixture
def fake_search(monkeypatch):
    """Search returns one hit whose title records which documents were in scope."""
    calls = []

    def fetch(query, top_k=4, scope=None):
        calls.append(scope)
        return [{"title": f"Doc for {scope[0]}", "page": 3, "source_type": "official",
                 "doc_date": None, "score": 0.7,
                 "content": "Employees are entitled to ninety-eight days of maternity leave."}]

    monkeypatch.setattr(tools, "_fetch_hits", fetch)
    return calls


# ---------- pure helpers ----------

def test_parse_plan_reads_valid_json_and_drops_unknown_agents():
    text = '{"decline": false, "subtasks": [{"agent": "tax", "task": "VAT?"}, {"agent": "magic", "task": "x"}]}'
    assert parse_plan(text) == ([{"agent": "tax", "task": "VAT?"}], False)


def test_parse_plan_accepts_json_inside_a_code_fence():
    text = 'Here you go:\n```json\n{"decline": true, "subtasks": []}\n```'
    assert parse_plan(text) == ([], True)


def test_parse_plan_returns_none_for_garbage():
    assert parse_plan("sorry, no idea") is None
    assert parse_plan('{"decline": false, "subtasks": []}') is None


def test_keyword_route_picks_specialists_or_declines():
    assert keyword_route("When is VAT due?")[0][0]["agent"] == "tax"
    assert keyword_route("What is the capital of France?") == ([], True)


def test_verify_flags_missing_search_unknown_citation_and_uncited_answer():
    search_step = NS(tool="search_regulations", result={})
    good = {"answer": "Rule applies [1].", "sources": {1: {}}, "steps": [search_step]}
    assert verify_finding(good) == []
    no_search = {"answer": "Rule applies.", "sources": {}, "steps": []}
    assert any("no search" in p for p in verify_finding(no_search))
    fake_cite = {"answer": "Rule [5].", "sources": {1: {}}, "steps": [search_step]}
    assert any("[5]" in p for p in verify_finding(fake_cite))
    uncited = {"answer": "Rule applies.", "sources": {1: {}}, "steps": [search_step]}
    assert any("cites none" in p for p in verify_finding(uncited))


def test_each_specialist_has_documents_and_the_search_tool():
    for spec in SPECIALISTS.values():
        assert spec.scope and "search_regulations" in spec.tools


# ---------- the whole graph, with a scripted fake model ----------

def test_single_specialist_runs_inside_its_own_scope(fake_search):
    client = FakeClient([
        plan(("employment", "What does the Labour Act say about maternity leave?")),
        search(),
        reply(content="98 days of maternity leave [1]."),
    ])
    result = run_team("Maternity leave?", client=client, model="test-model", today=TODAY)
    assert [f["agent"] for f in result.findings] == ["employment"]
    assert fake_search == [list(SPECIALISTS["employment"].scope)]
    assert "98 days of maternity leave [1]." in result.answer
    assert "Sources:\n[1] Doc for labour_act.pdf (page 3)" in result.answer
    assert "not legal advice" in result.answer
    assert result.issues == [] and result.revisions == 0
    assert result.tokens == 30


def test_two_specialists_get_unique_citation_numbers(fake_search):
    client = FakeClient([
        plan(("tax", "VAT due date?"), ("employment", "NSSA duties?")),
        search("a"), reply(content="VAT rule [1]."),
        search("b"), reply(content="NSSA rule [1]."),  # each specialist counts from [1]
    ])
    result = run_team("VAT and NSSA?", client=client, model="test-model", today=TODAY)
    assert "VAT rule [1]." in result.answer and "NSSA rule [2]." in result.answer
    assert "**Tax**" in result.answer and "**Employment and social security**" in result.answer
    assert "[1] Doc for vat_act.pdf" in result.answer
    assert "[2] Doc for labour_act.pdf" in result.answer
    assert result.issues == []


def test_verifier_sends_a_bad_answer_back_once_and_it_is_fixed(fake_search):
    client = FakeClient([
        plan(("tax", "When is VAT due?")),
        reply(content="Due 10 July [5]."),          # no search, invented citation
        search(), reply(content="Due 10 July 2026 [1]."),  # revised answer
    ])
    result = run_team("VAT?", client=client, model="test-model", today=TODAY)
    assert result.revisions == 1
    assert result.issues == []
    assert "Due 10 July 2026 [1]." in result.answer
    assert "Verification notes" not in result.answer
    revision_request = client.requests[2]["messages"][1]["content"]
    assert "reviewer found problems" in revision_request and "no search" in revision_request


def test_unresolved_problems_are_shown_to_the_user(fake_search):
    client = FakeClient([
        plan(("tax", "When is VAT due?")),
        reply(content="Due 10 July [5]."),
        reply(content="Still due 10 July [5]."),
    ])
    result = run_team("VAT?", client=client, model="test-model", today=TODAY)
    assert result.revisions == 1  # never loops more than MAX_REVISIONS
    assert "Verification notes" in result.answer


def test_off_topic_questions_are_declined_without_specialists():
    client = FakeClient([plan(decline=True)])
    result = run_team("Capital of France?", client=client, model="test-model", today=TODAY)
    assert result.answer == DECLINE_MESSAGE
    assert len(client.requests) == 1
    assert result.findings == []


def test_unreadable_coordinator_reply_falls_back_to_keywords(fake_search):
    client = FakeClient([
        reply(content="I am not sure how to answer in JSON."),
        search(), reply(content="Rule [1]."),
    ])
    result = run_team("When is my VAT return due?", client=client, model="test-model", today=TODAY)
    assert result.plan_source == "fallback"
    assert [f["agent"] for f in result.findings] == ["tax"]


# ---------- grounding check: catches invented figures ----------

from startright.multiagent import number_words, ungrounded_claims  # noqa: E402


def test_number_words():
    assert number_words(98) == "ninety-eight"
    assert number_words(21) == "twenty-one"
    assert number_words(7) == "seven"


def test_invented_percentages_and_forms_are_flagged():
    answer = "Employer pays 10 % and employee 5 %. File Form NSSA‑M within 30 days."
    evidence = "contributions are payable at rates set by the Minister. The employer must register."
    flagged = ungrounded_claims(answer, evidence)
    assert "10 %" in flagged and "5 %" in flagged
    assert "Form NSSA‑M" in flagged and "30 days" in flagged


def test_figures_written_as_words_in_the_source_count_as_grounded():
    evidence = "entitled to ninety-eight days of maternity leave on full pay"
    assert ungrounded_claims("She gets 98 days on full pay [1].", evidence) == []


def test_amounts_compare_by_value_not_by_spelling():
    evidence = '{"total": "85.5", "currency": "USD"}'
    assert ungrounded_claims("The total is USD 85.50.", evidence) == []
    assert ungrounded_claims("The total is USD 90.", evidence) == ["USD 90"]


def test_real_form_names_and_percentages_in_sources_pass():
    evidence = "submit form cr6 and pay 15 per centum of the amount"
    assert ungrounded_claims("Submit Form CR6 and pay 15% [1].", evidence) == []


def test_dates_and_list_numbers_are_not_treated_as_claims():
    assert ungrounded_claims("1. Register.\n2. Due 10 July 2026 [1].", "nothing relevant") == []


def test_verifier_flags_invented_figures_even_when_citations_are_valid():
    step = NS(tool="search_regulations",
              result={"results": [{"n": 1, "text": "the employer must register with the Authority"}]})
    finding = {
        "answer": "Employers pay 10% of salary [1].",
        "sources": {1: {}}, "steps": [step], "question": "NSSA?",
    }
    assert any("10%" in p for p in verify_finding(finding))


def test_revision_that_cites_from_one_again_is_accepted(fake_search):
    client = FakeClient([
        plan(("tax", "When is VAT due?")),
        search("a"), reply(content="Due 10 July [9]."),        # unknown citation
        search("b"), reply(content="Due 10 July 2026 [1]."),   # revised, counts from [1]
    ])
    result = run_team("VAT?", client=client, model="test-model", today=TODAY)
    assert result.revisions == 1 and result.issues == []
    assert "Due 10 July 2026 [1]." in result.answer
    assert "[1] Doc for vat_act.pdf" in result.answer


def test_fullwidth_brackets_are_normalised_and_tool_figures_are_grounded(fake_search):
    deadline = reply(tool_calls=[tool_call("d", "check_deadline",
                                           {"period_end": "2026-06-30", "day_of_month": 10})])
    client = FakeClient([
        plan(("tax", "When is VAT due, and how many days ago?")),
        search("s"), deadline,
        reply(content="Due 10 July 2026【1】, which was 91 days ago."),
    ])
    result = run_team("VAT?", client=client, model="test-model", today=TODAY)
    assert result.issues == [] and result.revisions == 0
    assert "Due 10 July 2026[1], which was 91 days ago." in result.answer


def test_figures_from_tool_results_and_the_question_count_as_grounded():
    assert ungrounded_claims("That was 91 days ago.", "", '{"days_until_due": -91}') == []
    assert ungrounded_claims("The licence is 20 USD.", "", "I can pay 20 USD") == []
    assert ungrounded_claims("The licence is 25 USD.", "", "I can pay 20 USD") == ["25 USD"]
