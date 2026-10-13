"""The always-on personal-data masking (src/startright/privacy.py), no extra packages needed."""
import pytest

from startright import privacy


@pytest.mark.parametrize("text,kind", [
    ("my id is 63-123456 K 42", "ID number"),
    ("ID 63123456K42", "ID number"),
    ("call 0771234567", "phone number"),
    ("call 077 123 4567", "phone number"),
    ("call +263 77 123 4567", "phone number"),
    ("write to owner@example.co.zw", "email address"),
])
def test_identifiers_are_masked(text, kind):
    masked, found = privacy.mask_personal_data(text)
    assert found == [kind]
    assert f"[{kind}]" in masked


def test_several_kinds_in_one_message():
    masked, found = privacy.mask_personal_data("ID 63-123456 K 42, 0771234567, a@b.com")
    assert set(found) == {"ID number", "phone number", "email address"}
    assert "63-123456" not in masked and "0771234567" not in masked and "a@b.com" not in masked


def test_legal_text_is_not_mangled():
    text = "Register within 30 days. Fee USD 150. See Chapter 24:03 of 2007 and section 12(1)(a)."
    assert privacy.mask_personal_data(text) == (text, [])


def test_webapp_masks_before_the_model_sees_the_question(monkeypatch):
    """The text that reaches the model client must not contain the personal data."""
    from fastapi.testclient import TestClient

    from startright import webapp

    seen = {}

    def fake_stream_team(message, client, model, today):
        seen["message"] = message
        return iter([])

    import startright.multiagent as multiagent
    monkeypatch.setattr(multiagent, "stream_team", fake_stream_team)
    monkeypatch.setenv("GROQ_MODEL", "test-model")
    from types import SimpleNamespace as NS
    app = webapp.create_app(client_factory=lambda: NS(chat=NS(completions=NS(create=lambda **kw: None))))
    with TestClient(app) as client:
        client.post("/api/chat", json={"message": "I am 63-123456 K 42 how do I register a company", "mode": "answer"})
    assert "63-123456" not in seen.get("message", "")
    assert "[ID number]" in seen.get("message", "")
