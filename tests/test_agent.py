import json
from datetime import date
from types import SimpleNamespace as NS

from startright import tools
from startright.agent import run_agent

TODAY = date(2026, 10, 9)

NOTICE_HIT = {
    "title": "ZIMRA Public Notice 41 of 2026", "page": 1, "source_type": "notice",
    "doc_date": None, "score": 0.6,
    "content": "Returns for the period ended 30 June 2026 are due on or before 10 July 2026.",
}


def tool_call(call_id, name, arguments):
    text = arguments if isinstance(arguments, str) else json.dumps(arguments)
    return NS(id=call_id, function=NS(name=name, arguments=text))


def reply(content=None, tool_calls=None, tokens=10):
    message = NS(content=content, tool_calls=tool_calls)
    return NS(choices=[NS(message=message)], usage=NS(total_tokens=tokens))


class FakeClient:
    """Stands in for Groq: returns scripted replies, records what it was sent."""

    def __init__(self, replies):
        self.replies = list(replies)
        self.requests = []
        self.chat = NS(completions=NS(create=self._create))

    def _create(self, **kwargs):
        # copy the message list: the agent keeps appending to the same list
        self.requests.append({**kwargs, "messages": list(kwargs["messages"])})
        return self.replies.pop(0)


DEADLINE_ARGS = {"period_end": "2026-06-30", "day_of_month": 10}


def test_agent_chains_search_then_deadline_then_answers(monkeypatch):
    monkeypatch.setattr(tools, "_fetch_hits", lambda query, top_k=4: [NOTICE_HIT])
    client = FakeClient([
        reply(tool_calls=[tool_call("1", "search_regulations", {"query": "VAT return due date"})]),
        reply(tool_calls=[tool_call("2", "check_deadline", DEADLINE_ARGS)]),
        reply(content="Due 10 July 2026 [1]."),
    ])
    result = run_agent("When is VAT due?", client=client, model="test-model", today=TODAY)
    assert result.answer == "Due 10 July 2026 [1]."
    assert [s.tool for s in result.steps] == ["search_regulations", "check_deadline"]
    assert result.steps[1].result["due_date"] == "2026-07-10"
    assert result.tokens == 30
    roles = [m["role"] for m in client.requests[1]["messages"]]
    assert roles == ["system", "user", "assistant", "tool"]


def test_deadline_without_a_source_is_blocked():
    client = FakeClient([
        reply(tool_calls=[tool_call("1", "check_deadline", DEADLINE_ARGS)]),
        reply(content="Let me look that up first."),
    ])
    result = run_agent("When is VAT due?", client=client, model="test-model", today=TODAY)
    assert "search_regulations" in result.steps[0].result["error"]
    assert "due_date" not in result.steps[0].result


def test_deadline_is_blocked_if_search_found_nothing(monkeypatch):
    monkeypatch.setattr(tools, "_fetch_hits", lambda query, top_k=4: [])
    client = FakeClient([
        reply(tool_calls=[tool_call("1", "search_regulations", {"query": "anything"})]),
        reply(tool_calls=[tool_call("2", "check_deadline", DEADLINE_ARGS)]),
        reply(content="I could not find the rule."),
    ])
    result = run_agent("When?", client=client, model="test-model", today=TODAY)
    assert "error" in result.steps[1].result


def test_agent_answers_directly_without_tools():
    client = FakeClient([reply(content="I can only help with business questions.")])
    result = run_agent("Capital of France?", client=client, model="test-model", today=TODAY)
    assert result.steps == []
    assert "business" in result.answer


def test_agent_survives_invalid_tool_arguments():
    client = FakeClient([
        reply(tool_calls=[tool_call("1", "calculate_fees", "this is not json")]),
        reply(content="Sorry, I could not add those."),
    ])
    result = run_agent("Total?", client=client, model="test-model", today=TODAY)
    assert "error" in result.steps[0].result
    assert result.answer == "Sorry, I could not add those."


def test_agent_stops_at_step_limit():
    looping = [
        reply(tool_calls=[tool_call(str(i), "calculate_fees",
                                    {"items": [{"name": "x", "amount": 1}]})])
        for i in range(2)
    ]
    result = run_agent("Loop", client=FakeClient(looping), model="test-model",
                       max_steps=2, today=TODAY)
    assert "step limit" in result.answer
    assert len(result.steps) == 2


def test_system_prompt_contains_todays_date():
    client = FakeClient([reply(content="ok")])
    run_agent("Hi", client=client, model="test-model", today=TODAY)
    assert "2026-10-09" in client.requests[0]["messages"][0]["content"]
