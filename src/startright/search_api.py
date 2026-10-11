"""A small local search endpoint:  uvicorn startright.search_api:app --port 8001

It is not part of the Docker image on purpose: it needs the embedding model, which
would make the image several gigabytes. Run it on your own computer.
"""
from fastapi import FastAPI, HTTPException, Query

from startright import retrieval
from startright.guardrails import check_question

app = FastAPI(title="StartRight search")


@app.get("/search")
def search(
    q: str = Query(..., description="The question"),
    mode: str = Query("hybrid", description="vector, bm25, hybrid or hybrid_rerank"),
    top_k: int = Query(4, ge=1, le=20),
):
    refusal = check_question(q)
    if refusal:
        raise HTTPException(status_code=422, detail=refusal)
    if mode not in retrieval.MODES:
        raise HTTPException(status_code=422, detail=f"mode must be one of {retrieval.MODES}")
    hits = retrieval.search(q, top_k=top_k, mode=mode)
    return {
        "query": q,
        "mode": mode,
        "results": [
            {
                "title": h["title"],
                "page": h["page"],
                "source_type": h["source_type"],
                "score": round(float(h["score"]), 3),
                "text": h["content"][:400],
            }
            for h in hits
        ],
    }
