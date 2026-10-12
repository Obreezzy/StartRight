import pytest

from startright import retrieval, store, tools
from startright.retrieval import build_corpus, score_floor

CHUNKS = [
    {"id": 1, "source_file": "cobe.pdf", "title": "Act", "page": 1, "source_type": "official",
     "doc_date": None, "url": None, "content": "A private company must register with the Registrar of Companies."},
    {"id": 2, "source_file": "cobe.pdf", "title": "Act", "page": 2, "source_type": "official",
     "doc_date": None, "url": None, "content": "The Registrar keeps a register of members."},
    {"id": 3, "source_file": "vat.pdf", "title": "VAT", "page": 3, "source_type": "official",
     "doc_date": None, "url": None, "content": "Input tax is deducted from output tax."},
]


def test_lexical_score_is_the_share_of_known_question_words_in_the_chunk():
    corpus = build_corpus(CHUNKS)
    hits = corpus.lexical("private company register", 5, None)
    assert hits[0]["id"] == 1 and hits[0]["score"] == pytest.approx(1.0)
    partial = {h["id"]: h["score"] for h in hits}
    assert 0 < partial[2] < 1  # chunk 2 has "register" but not "private company"


def test_words_that_appear_nowhere_in_the_documents_are_ignored():
    corpus = build_corpus(CHUNKS)
    with_salon = corpus.lexical("hair salon private company", 5, None)
    without = corpus.lexical("private company", 5, None)
    assert with_salon[0]["score"] == pytest.approx(without[0]["score"])


def test_a_question_with_no_known_words_returns_nothing():
    assert build_corpus(CHUNKS).lexical("capital of France", 5, None) == []


def test_lexical_search_respects_the_file_scope():
    hits = build_corpus(CHUNKS).lexical("tax", 5, ["vat.pdf"])
    assert [h["id"] for h in hits] == [3]
    assert build_corpus(CHUNKS).lexical("tax", 5, ["cobe.pdf"]) == []


def test_bm25_light_never_calls_the_embedding_model(monkeypatch):
    def boom(texts):
        raise AssertionError("bm25_light must not embed anything")

    monkeypatch.setattr(retrieval, "embed_texts", boom)
    monkeypatch.setattr(retrieval, "load_corpus", lambda conn: build_corpus(CHUNKS))
    hits = retrieval.search("NSSA private company", top_k=2, mode="bm25_light", conn=object())
    assert hits[0]["id"] == 1


def test_score_floor_depends_on_the_mode(monkeypatch):
    monkeypatch.delenv("LEXICAL_MIN_SCORE", raising=False)
    assert score_floor("hybrid") == 0.25 and score_floor("vector") == 0.25
    assert score_floor("bm25_light") == 0.3
    monkeypatch.setenv("LEXICAL_MIN_SCORE", "0.5")
    assert score_floor("bm25_light") == 0.5
    monkeypatch.setenv("RETRIEVAL_MODE", "bm25_light")
    assert score_floor() == 0.5


def test_search_tool_uses_the_floor_of_the_active_mode(monkeypatch):
    hit = {"title": "T", "page": 1, "source_type": "official", "doc_date": None,
           "content": "text", "score": 0.4}
    monkeypatch.setattr(tools, "_fetch_hits", lambda query, top_k=4, scope=None: [hit])
    monkeypatch.setenv("RETRIEVAL_MODE", "bm25_light")
    monkeypatch.setenv("LEXICAL_MIN_SCORE", "0.5")
    assert tools.run_tool("search_regulations", {"query": "x"}, __import__("datetime").date(2026, 1, 1))["results"] == []
    monkeypatch.setenv("LEXICAL_MIN_SCORE", "0.3")
    assert len(tools.run_tool("search_regulations", {"query": "x"}, __import__("datetime").date(2026, 1, 1))["results"]) == 1


def test_hosted_database_url_is_used_when_present(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@host.neon.tech/db?sslmode=require")
    assert store.database_url() == "postgresql://u:p@host.neon.tech/db?sslmode=require"
    monkeypatch.delenv("DATABASE_URL")
    monkeypatch.setenv("POSTGRES_PASSWORD", "pw")
    assert store.database_url().startswith("postgresql://startright:pw@127.0.0.1:")


def test_light_search_needs_no_connection_once_corpus_is_loaded(monkeypatch):
    from startright import retrieval, store
    chunks = [{"id": 1, "content": "maternity leave ninety-eight days full pay", "source_file": "a.pdf",
               "page": 1, "title": "Labour Act", "source_type": "official", "topic": "employment"}]
    monkeypatch.setattr(retrieval, "_CORPUS", retrieval.build_corpus(chunks))
    monkeypatch.setattr(store, "connect", lambda *a, **k: (_ for _ in ()).throw(AssertionError("connected")))
    hits = retrieval.search("maternity leave", top_k=1, mode="bm25_light")
    assert hits and hits[0]["id"] == 1
