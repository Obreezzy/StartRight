"""Runs only when STARTRIGHT_DB_TESTS=1 and the local database is up."""
import os

import pytest

pytestmark = pytest.mark.skipif(
    os.getenv("STARTRIGHT_DB_TESTS") != "1", reason="set STARTRIGHT_DB_TESTS=1 to run"
)


def test_chunks_are_copied_with_their_vectors_to_another_database():
    import psycopg
    from dotenv import load_dotenv
    from psycopg.rows import dict_row

    from startright import store

    load_dotenv()
    vector = [0.0] * 384
    vector[7] = 1.0
    admin = psycopg.connect(store.database_url(), autocommit=True)
    admin.execute("DROP DATABASE IF EXISTS itest_copy_target")
    admin.execute("CREATE DATABASE itest_copy_target")
    target_url = store.database_url().rsplit("/", 1)[0] + "/itest_copy_target"
    try:
        with store.connect() as source:
            store.ensure_schema(source)
            meta = {"filename": "itest_copy.pdf", "title": "Copy test", "source_type": "official",
                    "doc_date": "2026-01-02"}
            store.replace_document(source, meta, [(3, 0, "hello copy"), (4, 1, "second chunk")],
                                   [vector, vector])
            with psycopg.connect(target_url, row_factory=dict_row, prepare_threshold=None) as target:
                copied = store.copy_chunks(source, target)
                assert copied >= 2
                rows = target.execute(
                    "SELECT content, page, doc_date::text AS d FROM chunks "
                    "WHERE source_file = 'itest_copy.pdf' ORDER BY page").fetchall()
                assert [r["content"] for r in rows] == ["hello copy", "second chunk"]
                assert rows[0]["d"] == "2026-01-02"
                hits = store.search(target, vector, top_k=1)
                assert hits[0]["score"] > 0.99          # the vector survived the copy
                assert store.copy_chunks(source, target) == copied  # safe to run twice
            source.execute("DELETE FROM chunks WHERE source_file = 'itest_copy.pdf'")
            source.commit()
    finally:
        admin.execute("DROP DATABASE IF EXISTS itest_copy_target WITH (FORCE)")
        admin.close()
