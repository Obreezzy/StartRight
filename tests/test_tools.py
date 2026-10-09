from datetime import date

from startright import tools
from startright.tools import run_tool

TODAY = date(2026, 10, 9)


def test_calculate_fees_adds_amounts_exactly():
    result = run_tool(
        "calculate_fees",
        {"items": [{"name": "Name search", "amount": 50}, {"name": "Filing", "amount": 25.5}]},
        TODAY,
    )
    assert result["total"] == "75.5"
    assert result["currency"] == "USD"
    assert result["items_counted"] == 2


def test_calculate_fees_rejects_mixed_currencies():
    result = run_tool(
        "calculate_fees",
        {"items": [
            {"name": "A", "amount": 10, "currency": "USD"},
            {"name": "B", "amount": 10, "currency": "ZWG"},
        ]},
        TODAY,
    )
    assert "error" in result


def test_check_deadline_matches_zimra_vat_example():
    result = run_tool(
        "check_deadline", {"period_end": "2026-06-30", "day_of_month": 10}, TODAY
    )
    assert result["due_date"] == "2026-07-10"
    assert result["days_until_due"] == -91  # already passed on 9 Oct 2026


def test_check_deadline_rejects_bad_date():
    result = run_tool(
        "check_deadline", {"period_end": "30 June 2026", "day_of_month": 10}, TODAY
    )
    assert "error" in result


def test_missing_argument_returns_error_not_crash():
    assert "error" in run_tool("calculate_fees", {}, TODAY)


def test_unknown_tool_returns_error():
    assert "error" in run_tool("make_coffee", {}, TODAY)


def test_search_filters_weak_matches_and_truncates(monkeypatch):
    hits = [
        {"title": "Act A", "page": 2, "source_type": "official",
         "doc_date": None, "content": "x" * 5000, "score": 0.6},
        {"title": "Weak", "page": 9, "source_type": "guide",
         "doc_date": None, "content": "noise", "score": 0.1},
    ]
    monkeypatch.setattr(tools, "_fetch_hits", lambda query, top_k=4, scope=None: hits)
    result = run_tool("search_regulations", {"query": "company"}, TODAY)
    assert len(result["results"]) == 1
    assert result["results"][0]["title"] == "Act A"
    assert len(result["results"][0]["text"]) == tools.MAX_CHARS_PER_SOURCE


def test_search_with_no_good_hits_says_so(monkeypatch):
    monkeypatch.setattr(tools, "_fetch_hits", lambda query, top_k=4, scope=None: [])
    result = run_tool("search_regulations", {"query": "capital of France"}, TODAY)
    assert result["results"] == []
