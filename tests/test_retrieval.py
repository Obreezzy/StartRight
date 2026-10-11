from types import SimpleNamespace as NS

import pytest

from startright import retrieval
from startright.retrieval import (
    BM25Index,
    build_corpus,
    expand_query,
    rrf_fuse,
    scope_matches,
    stem,
    tokenize,
)


# ---------- text handling ----------

def test_stemmer_makes_related_words_match():
    assert (stem("registration") == stem("registered") == stem("register")
            == stem("registers") == stem("registrar"))
    assert stem("companies") == stem("company")


def test_stemmer_leaves_short_words_and_double_s_alone():
    assert stem("act") == "act" and stem("tax") == "tax"
    assert stem("business").startswith("busines")


def test_tokenize_lowercases_and_drops_stop_words():
    assert tokenize("What is the Private Company?") == [stem("private"), stem("company")]


def test_expand_query_adds_the_full_name_of_acronyms_only():
    assert "National Social Security Authority" in expand_query("When must I register with NSSA?")
    assert expand_query("insurance for my shop") == "insurance for my shop"
    assert "value added tax" in expand_query("VAT returns")


def test_scope_matches_uses_like_patterns():
    assert scope_matches("zimra_pn_41_2026.pdf", ["zimra_pn_%"])
    assert scope_matches("vat_act.pdf", ["vat_act.pdf", "labour_act.pdf"])
    assert not scope_matches("vat_act.pdf", ["zimra_pn_%"])
    assert scope_matches("anything.pdf", None)


# ---------- BM25 ----------

CHUNKS = [
    {"id": 1, "source_file": "cobe.pdf", "content": "A private business corporation may have up to twenty members."},
    {"id": 2, "source_file": "cobe.pdf", "content": "A private company limited by shares must file a memorandum. The private company has a name."},
    {"id": 3, "source_file": "labour.pdf", "content": "An employee on maternity leave receives full pay."},
    {"id": 4, "source_file": "vat.pdf", "content": "Input tax and output tax are explained here. " + "filler " * 80},
]


def test_bm25_ranks_the_chunk_that_matches_the_exact_phrase_first():
    index = BM25Index([c["content"] for c in CHUNKS])
    ranked = index.search("private company", top_k=3)
    assert ranked[0][0] == 1  # doc index 1 = the private company chunk
    assert all(score > 0 for _, score in ranked)


def test_bm25_returns_nothing_for_unknown_words():
    index = BM25Index([c["content"] for c in CHUNKS])
    assert index.search("capital of france", top_k=3) == []


def test_bm25_rare_words_beat_common_ones():
    index = BM25Index(["tax tax tax", "tax return", "return of maternity"])
    top = index.search("maternity tax", top_k=3)
    assert top[0][0] == 2  # 'maternity' is rare, so it outweighs the common 'tax'


def test_bm25_respects_an_allowed_set():
    index = BM25Index([c["content"] for c in CHUNKS])
    ranked = index.search("private", top_k=5, allowed={0})
    assert [doc for doc, _ in ranked] == [0]


def test_corpus_keyword_search_applies_the_file_scope():
    corpus = build_corpus(CHUNKS)
    hits = corpus.keyword("maternity leave pay", 5, ["labour.pdf"])
    assert [h["id"] for h in hits] == [3] and hits[0]["bm25"] > 0
    assert corpus.keyword("maternity leave pay", 5, ["cobe.pdf"]) == []


# ---------- fusion ----------

def test_rrf_puts_items_found_by_both_searches_first():
    assert rrf_fuse([[1, 2, 3], [9, 2]]) == [2, 1, 9, 3]


def test_rrf_with_one_list_keeps_its_order():
    assert rrf_fuse([[5, 4, 3]]) == [5, 4, 3]


# ---------- search modes (database and model faked) ----------

@pytest.fixture
def fake_backend(monkeypatch):
    seen = {"embedded": []}

    def fake_embed(texts):
        seen["embedded"].extend(texts)
        return [[0.0] * 3]

    def hit(i, score):
        return {"id": i, "source_file": "f.pdf", "title": f"T{i}", "url": None,
                "source_type": "official", "doc_date": None, "page": i,
                "content": f"text {i}", "score": score}

    monkeypatch.setattr(retrieval, "embed_texts", fake_embed)
    monkeypatch.setattr(retrieval.store, "search",
                        lambda conn, vec, k, scope=None: [hit(1, .6), hit(2, .5), hit(3, .4)][:k])
    monkeypatch.setattr(retrieval.store, "scores_for_ids",
                        lambda conn, vec, ids: {i: .3 for i in ids})
    monkeypatch.setattr(retrieval, "load_corpus", lambda conn: NS(
        keyword=lambda q, n, scope: [{**hit(9, 0), "bm25": 5.0}, {**hit(2, 0), "bm25": 3.0}]))
    seen["hit"] = hit
    return seen


def test_vector_mode_is_the_baseline_and_does_not_expand_the_query(fake_backend):
    hits = retrieval.search("NSSA duties", mode="vector", conn=object())
    assert [h["id"] for h in hits] == [1, 2, 3]
    assert fake_backend["embedded"] == ["NSSA duties"]


def test_hybrid_mode_fuses_both_rankings_and_keeps_cosine_scores(fake_backend):
    hits = retrieval.search("NSSA duties", top_k=4, mode="hybrid", conn=object())
    assert [h["id"] for h in hits] == [2, 1, 9, 3]
    assert hits[2]["score"] == .3  # keyword-only hit gets its cosine score for the guardrail
    assert "National Social Security Authority" in fake_backend["embedded"][0]


def test_bm25_mode_attaches_cosine_scores(fake_backend):
    hits = retrieval.search("anything", mode="bm25", conn=object())
    assert [h["id"] for h in hits] == [9, 2] and all(h["score"] == .3 for h in hits)


def test_rerank_mode_reorders_by_the_cross_encoder(fake_backend, monkeypatch):
    fake = NS(predict=lambda pairs: [0.1, 0.9, 0.2, 0.5][: len(pairs)])
    monkeypatch.setattr(retrieval, "_reranker", lambda: fake)
    hits = retrieval.search("q", top_k=2, mode="hybrid_rerank", conn=object())
    assert [h["id"] for h in hits] == [1, 3]  # fused order is [2, 1, 9, 3]; scores .1 .9 .2 .5
    assert hits[0]["rerank_score"] == .9


def test_unknown_mode_is_rejected():
    with pytest.raises(ValueError):
        retrieval.search("q", mode="magic", conn=object())


def test_default_mode_comes_from_the_environment(fake_backend, monkeypatch):
    monkeypatch.setenv("RETRIEVAL_MODE", "vector")
    assert [h["id"] for h in retrieval.search("q", conn=object())] == [1, 2, 3]
