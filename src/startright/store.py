import os

import psycopg
from psycopg.rows import dict_row


def database_url() -> str:
    user = os.getenv("POSTGRES_USER", "startright")
    password = os.environ["POSTGRES_PASSWORD"]
    name = os.getenv("POSTGRES_DB", "startright")
    host = os.getenv("POSTGRES_HOST", "localhost")
    port = os.getenv("POSTGRES_PORT", "5433")
    return f"postgresql://{user}:{password}@{host}:{port}/{name}"


def connect() -> psycopg.Connection:
    return psycopg.connect(database_url(), row_factory=dict_row)


def to_vector_literal(vector: list[float]) -> str:
    return "[" + ",".join(str(x) for x in vector) + "]"


SCHEMA_STATEMENTS = [
    "CREATE EXTENSION IF NOT EXISTS vector",
    """CREATE TABLE IF NOT EXISTS chunks (
        id BIGSERIAL PRIMARY KEY,
        source_file TEXT NOT NULL,
        title TEXT NOT NULL,
        url TEXT,
        source_type TEXT NOT NULL,
        doc_date DATE,
        page INT NOT NULL,
        chunk_index INT NOT NULL,
        content TEXT NOT NULL,
        embedding vector(384) NOT NULL,
        UNIQUE (source_file, page, chunk_index)
    )""",
    """CREATE INDEX IF NOT EXISTS chunks_embedding_idx
        ON chunks USING hnsw (embedding vector_cosine_ops)""",
]


def ensure_schema(conn: psycopg.Connection) -> None:
    for statement in SCHEMA_STATEMENTS:
        conn.execute(statement)
    conn.commit()


def replace_document(conn, meta: dict, records: list, vectors: list) -> None:
    """Re-ingesting a file replaces its old chunks, so ingestion is repeatable."""
    rows = [
        (
            meta["filename"],
            meta["title"],
            meta.get("url") or None,
            meta["source_type"],
            meta.get("doc_date") or None,
            page,
            index,
            content,
            to_vector_literal(vector),
        )
        for (page, index, content), vector in zip(records, vectors)
    ]
    with conn.cursor() as cur:
        cur.execute("DELETE FROM chunks WHERE source_file = %s", (meta["filename"],))
        cur.executemany(
            """INSERT INTO chunks (source_file, title, url, source_type, doc_date,
                                   page, chunk_index, content, embedding)
               VALUES (%s, %s, %s, %s, %s::date, %s, %s, %s, %s::vector)""",
            rows,
        )
    conn.commit()


def search(
    conn,
    query_vector: list[float],
    top_k: int = 4,
    scope: list[str] | None = None,
) -> list[dict]:
    """Nearest chunks. `scope` limits the search to files matching any of the
    given SQL LIKE patterns (for example ['zimra_pn_%', 'vat_act.pdf'])."""
    literal = to_vector_literal(query_vector)
    where = "WHERE source_file LIKE ANY(%s)" if scope else ""
    params = [literal] + ([scope] if scope else []) + [literal, top_k]
    return conn.execute(
        f"""SELECT title, url, source_type, doc_date, page, content,
                   1 - (embedding <=> %s::vector) AS score
            FROM chunks
            {where}
            ORDER BY embedding <=> %s::vector
            LIMIT %s""",
        params,
    ).fetchall()
