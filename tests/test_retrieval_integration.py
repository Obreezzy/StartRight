"""Runs only when STARTRIGHT_DB_TESTS=1 and the database is up (docker compose up -d db).
Uses made-up vectors so it needs no embedding model."""
import os

import pytest

pytestmark = pytest.mark.skipif(
    os.getenv("STARTRIGHT_DB_TESTS") != "1", reason="set STARTRIGHT_DB_TESTS=1 to run"
)


def unit_vector(position: int) -> list[float]:
    vector = [0.0] * 384
    vector[position] = 1.0
    return vector


def test_hybrid_search_finds_a_keyword_match_that_vectors_rank_last(monkeypatch):
    from dotenv import load_dotenv

    from startright import retrieval, store

    load_dotenv()
    docs = {
        "itest_a.pdf": ("An unrelated chunk about trading names", 0),
        "itest_b.pdf": ("Another unrelated chunk about stands and streets", 1),
        "itest_c.pdf": ("The National Social Security Authority registers employers", 2),
    }
    with store.connect() as conn:
        store.ensure_schema(conn)
        for name, (text, position) in docs.items():
            meta = {"filename": name, "title": name, "source_type": "official"}
            store.replace_document(conn, meta, [(1, 0, text)], [unit_vector(position)])
        retrieval.reset_corpus()
        try:
            # the question's embedding points at chunk A, so chunk C is last by vectors...
            monkeypatch.setattr(retrieval, "embed_texts", lambda texts: [unit_vector(0)])
            vector_only = retrieval.search("NSSA employers", top_k=3, mode="vector", conn=conn)
            assert vector_only[0]["source_file"] == "itest_a.pdf"
            # ...but keyword search expands NSSA and finds it
            keyword = retrieval.search("NSSA employers", top_k=3, mode="bm25", conn=conn)
            assert keyword[0]["source_file"] == "itest_c.pdf"
            hybrid = retrieval.search("NSSA employers", top_k=3, mode="hybrid", conn=conn)
            assert "itest_c.pdf" in [h["source_file"] for h in hybrid[:2]]
            assert all(0 <= h["score"] <= 1 for h in hybrid)
            # scope limits both searches
            scoped = retrieval.search("NSSA employers", top_k=3, scope=["itest_a.pdf"],
                                      mode="hybrid", conn=conn)
            assert {h["source_file"] for h in scoped} == {"itest_a.pdf"}
        finally:
            conn.execute("DELETE FROM chunks WHERE source_file LIKE 'itest_%'")
            conn.commit()
            retrieval.reset_corpus()
