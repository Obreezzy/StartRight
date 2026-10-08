import os

import psycopg
from fastapi import FastAPI, HTTPException

app = FastAPI(title="StartRight API")


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/health/db")
def health_db():
    url = os.getenv("DATABASE_URL")
    if not url:
        raise HTTPException(status_code=503, detail="DATABASE_URL not set")
    try:
        with psycopg.connect(url, connect_timeout=3) as conn:
            row = conn.execute(
                "SELECT 1 FROM pg_extension WHERE extname = 'vector'"
            ).fetchone()
    except psycopg.Error:
        raise HTTPException(status_code=503, detail="Database unreachable")
    return {"database": "ok", "pgvector": row is not None}