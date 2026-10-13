"""Cohere Rerank modes: ordering, fallback when the service fails, and no network in tests."""
import urllib.error

import pytest

from startright import observability, retrieval
from startright.retrieval import build_corpus, cohere_rerank, score_floor

HITS = [
    {"id": 1, "content": "alpha", "score": 0.9},
    {"id": 2, "content": "beta", "score": 0.8},
    {"id": 3, "content": "gamma", "score": 0.7},
]
CHUNKS = [
    {"id": 1, "source_file": "cobe.pdf", "title": "Act", "page": 1, "source_type": "official",
     "doc_date": None, "url": None, "content": "A private company must register with the Registrar of Companies."},
    {"id": 2, "source_file": "cobe.pdf", "title": "Act", "page": 2, "source_type": "official",
     "doc_date": None, "url": None, "content": "The Registrar keeps a register of members."},
]


@pytest.fixture(autouse=True)
def key(monkeypatch):
    monkeypatch.setenv("COHERE_API_KEY", "test-key")


def fake_post(order):
    def post(payload, api_key):
        assert api_key == "test-key"
        assert payload["documents"] == [h["content"] for h in HITS][: len(payload["documents"])]
        return {"results": [{"index": i, "relevance_score": 0.9 - n * 0.1} for n, i in enumerate(order)]}
    return post


def test_results_follow_cohere_order_and_keep_the_original_score():
    out = cohere_rerank("q", HITS, 2, post=fake_post([2, 0, 1]))
    assert [h["id"] for h in out] == [3, 1]
    assert out[0]["score"] == 0.7  # the refusal guardrail still sees the original score
    assert out[0]["rerank_score"] == pytest.approx(0.9)
    assert out[0]["rerank_source"] == "cohere"


def test_request_asks_for_top_n_and_the_configured_model(monkeypatch):
    monkeypatch.setenv("COHERE_RERANK_MODEL", "my-model")
    seen = {}

    def post(payload, api_key):
        seen.update(payload)
        return {"results": [{"index": 0, "relevance_score": 0.5}]}

    cohere_rerank("question", HITS, 1, post=post)
    assert seen["model"] == "my-model" and seen["top_n"] == 1 and seen["query"] == "question"


def test_missing_key_falls_back_to_existing_order(monkeypatch):
    monkeypatch.delenv("COHERE_API_KEY")
    out = cohere_rerank("q", HITS, 2, post=lambda *a: pytest.fail("must not call"))
    assert [h["id"] for h in out] == [1, 2]
    assert all(h["rerank_source"] == "fallback" for h in out)


@pytest.mark.parametrize("error", [urllib.error.URLError("down"), TimeoutError(), ValueError("bad json"),
                                   OSError("reset")])
def test_service_errors_fall_back_instead_of_failing(error):
    def post(payload, api_key):
        raise error
    out = cohere_rerank("q", HITS, 2, post=post)
    assert [h["id"] for h in out] == [1, 2]
    assert out[0]["rerank_source"] == "fallback"


def test_http_error_such_as_quota_exceeded_falls_back():
    def post(payload, api_key):
        raise urllib.error.HTTPError("u", 429, "Too Many Requests", {}, None)
    assert cohere_rerank("q", HITS, 2, post=post)[0]["rerank_source"] == "fallback"


def test_malformed_response_falls_back():
    out = cohere_rerank("q", HITS, 2, post=lambda *a: {"unexpected": 1})
    assert out[0]["rerank_source"] == "fallback"


def test_a_single_candidate_needs_no_call():
    out = cohere_rerank("q", HITS[:1], 3, post=lambda *a: pytest.fail("must not call"))
    assert out == HITS[:1]


def test_modes_are_registered_and_use_the_right_score_floor(monkeypatch):
    assert {"hybrid_cohere", "bm25_cohere"} <= set(retrieval.MODES)
    monkeypatch.setenv("LEXICAL_MIN_SCORE", "0.3")
    assert score_floor("bm25_cohere") == 0.3
    assert score_floor("hybrid_cohere") == retrieval.COSINE_FLOOR


def test_bm25_cohere_search_needs_no_database_or_embedding_model(monkeypatch):
    monkeypatch.setattr(retrieval, "_CORPUS", build_corpus(CHUNKS))
    monkeypatch.setattr(retrieval, "_cohere_post", lambda p, k: {
        "results": [{"index": 1, "relevance_score": 0.8}, {"index": 0, "relevance_score": 0.4}]})
    hits = retrieval.search("private company register", top_k=2, mode="bm25_cohere")
    assert len(hits) == 2 and hits[0]["rerank_source"] == "cohere"
    assert all("score" in h for h in hits)  # lexical coverage is kept for the floor


def test_bm25_cohere_without_a_key_still_answers_with_bm25_order(monkeypatch):
    monkeypatch.delenv("COHERE_API_KEY")
    monkeypatch.setattr(retrieval, "_CORPUS", build_corpus(CHUNKS))
    hits = retrieval.search("private company register", top_k=2, mode="bm25_cohere")
    assert hits[0]["id"] == 1 and hits[0]["rerank_source"] == "fallback"


def test_the_rerank_call_is_a_traced_step():
    trace = observability.start_trace("t")
    token = observability._CURRENT.set(trace)
    try:
        cohere_rerank("q", HITS, 2, post=fake_post([0, 1]))
    finally:
        observability._CURRENT.reset(token)
    summary = trace.finish()
    assert "rerank_cohere" in [s["name"] for s in summary["spans"]]


def test_stats_count_successful_and_fallback_calls(monkeypatch):
    monkeypatch.setattr(retrieval, "COHERE_STATS", {"cohere": 0, "fallback": 0})
    cohere_rerank("q", HITS, 2, post=fake_post([0, 1]))
    cohere_rerank("q", HITS, 2, post=lambda *a: {"bad": 1})
    assert retrieval.COHERE_STATS == {"cohere": 1, "fallback": 1}


def test_throttle_spaces_calls_by_the_configured_interval(monkeypatch):
    sleeps = []
    clock = iter([100.0, 100.5, 105.0])
    monkeypatch.setattr(retrieval.time, "time", lambda: next(clock))
    monkeypatch.setattr(retrieval.time, "sleep", sleeps.append)
    monkeypatch.setenv("COHERE_MIN_INTERVAL", "7")
    monkeypatch.setitem(retrieval._LAST_CALL, "at", 98.0)
    retrieval._throttle()  # now=100, last=98 -> wait 5
    assert sleeps == [pytest.approx(5.0)]
