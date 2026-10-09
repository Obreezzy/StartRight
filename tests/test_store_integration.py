"""Runs only when STARTRIGHT_DB_TESTS=1 and the database is up (docker compose up -d db)."""
import os

import pytest

pytestmark = pytest.mark.skipif(
    os.getenv("STARTRIGHT_DB_TESTS") != "1", reason="set STARTRIGHT_DB_TESTS=1 to run"
)


def unit_vector(position: int) -> list[float]:
    vector = [0.0] * 384
    vector[position] = 1.0
    return vector


def test_scoped_search_only_returns_files_matching_the_patterns():
    from dotenv import load_dotenv

    from startright import store

    load_dotenv()  # pytest does not read .env by itself
    with store.connect() as conn:
        store.ensure_schema(conn)
        files = {
            "itest_vat.pdf": unit_vector(0),
            "itest_zimra_1.pdf": unit_vector(1),
            "itest_labour.pdf": unit_vector(2),
        }
        for name, vector in files.items():
            meta = {"filename": name, "title": name, "source_type": "official"}
            store.replace_document(conn, meta, [(1, 0, f"text of {name}")], [vector])
        try:
            query = unit_vector(2)  # closest to the labour file
            everything = store.search(conn, query, top_k=10)
            assert "text of itest_labour.pdf" in [h["content"] for h in everything]

            scoped = store.search(conn, query, top_k=10, scope=["itest_vat.pdf", "itest_zimra_%"])
            titles = {h["title"] for h in scoped}
            assert titles == {"itest_vat.pdf", "itest_zimra_1.pdf"}
        finally:
            conn.execute("DELETE FROM chunks WHERE source_file LIKE 'itest_%'")
            conn.commit()
