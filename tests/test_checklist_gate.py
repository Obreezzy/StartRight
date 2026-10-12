import json
from types import SimpleNamespace as NS

import pytest
from fastapi.testclient import TestClient

from startright import structured, tools
from startright.multiagent import DECLINE_MESSAGE
from startright.webapp import create_app


def reply(content=None, tokens=10):
    return NS(choices=[NS(message=NS(content=content, tool_calls=None))], usage=NS(total_tokens=tokens))


class RecordingClient:
    def __init__(self, replies):
        self.replies, self.calls = list(replies), []
        self.chat = NS(completions=NS(create=self._create))

    def _create(self, **kwargs):
        self.calls.append(kwargs)
        return self.replies.pop(0)


GOOD = json.dumps({"business": "Pottery studio", "not_covered": ["Exact fees"], "steps": [
    {"order": 1, "action": "Return the form to the Registrar", "office": "Registrar", "source_n": 1}]})


@pytest.fixture(autouse=True)
def env(monkeypatch):
    monkeypatch.setenv("GROQ_MODEL", "test-model")
    for name in ("ACCESS_CODE", "RATE_LIMIT_PER_HOUR", "DAILY_TOKEN_BUDGET", "RETRIEVAL_MODE"):
        monkeypatch.delenv(name, raising=False)

    def fetch(query, top_k=4, scope=None):
        return [{"title": "Companies Act", "page": 7, "source_type": "official", "doc_date": None,
                 "score": 0.7, "content": "Lodge the form with the Registrar of Companies."}]
    monkeypatch.setattr(tools, "_fetch_hits", fetch)


def run(replies, text):
    fake = RecordingClient(replies)
    client = TestClient(create_app(client_factory=lambda: fake))
    response = client.post("/api/chat", json={"message": text, "mode": "checklist"})
    events = [json.loads(line[5:]) for line in response.text.splitlines() if line.startswith("data:")]
    return events[-1], fake


# ---------- the pure pieces ----------

def test_short_descriptions_become_questions_but_full_questions_are_left_alone():
    assert structured.wrap_checklist_question("hair salon in Harare") == (
        "I want to start a hair salon in Harare in Zimbabwe. What do I need to register?")
    assert structured.wrap_checklist_question("A farm supplies company").startswith("I want to start a farm supplies")
    question = "What do I need to register a private company?"
    assert structured.wrap_checklist_question(question) == question


def test_business_words_are_recognised_without_asking_the_model():
    for text in ("Hair salon in Harare", "Farm supplies company", "Small shop that hires two staff", "tuckshop"):
        assert structured.has_business_words(text)
    for text in ("what is the capital city of france", "weather in Harare today", "embark on a journey"):
        assert not structured.has_business_words(text)


def test_the_classifier_says_no_when_unsure_or_unreachable():
    assert structured.is_business_description(RecordingClient([reply('{"business": true}', 30)]), "m", "x") == (True, 30)
    assert structured.is_business_description(RecordingClient([reply('{"business": false}', 30)]), "m", "x") == (False, 30)
    assert structured.is_business_description(RecordingClient([reply("not json", 30)]), "m", "x")[0] is False
    assert structured.is_business_description(RecordingClient([]), "m", "x") == (False, 0)


# ---------- through the web app ----------

def test_an_off_topic_message_is_refused_even_though_the_page_used_to_rewrite_it():
    final, fake = run([reply('{"business": false}', 25)], "what is the capital city of france")
    assert final["kind"] == "refusal" and final["answer"] == DECLINE_MESSAGE
    assert final["tokens"] == 25 and len(fake.calls) == 1  # one small topic check, no checklist call


def test_a_description_with_business_words_skips_the_topic_check():
    final, fake = run([reply(GOOD, 100)], "Hair salon in Harare")
    assert final["kind"] == "checklist" and final["tokens"] == 100 and len(fake.calls) == 1
    assert "I want to start a Hair salon in Harare in Zimbabwe." in fake.calls[0]["messages"][-1]["content"]


def test_a_business_description_without_known_words_passes_the_topic_check():
    final, fake = run([reply('{"business": true}', 20), reply(GOOD, 100)], "Pottery studio in Bulawayo")
    assert final["kind"] == "checklist" and final["tokens"] == 120 and len(fake.calls) == 2
    assert "I want to start a Pottery studio in Bulawayo in Zimbabwe." in fake.calls[1]["messages"][-1]["content"]
