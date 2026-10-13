# StartRight: feature-complete list (Week 11)

StartRight gives Zimbabwean business owners sourced guidance on registration, tax and
compliance. It gives general information, not legal advice. Every answer cites the document
and page it came from, and the app refuses when the documents do not cover the question.

## What it does (built and tested)

| Area | Feature | Where |
|---|---|---|
| Knowledge base | PDFs ingested, cleaned, split into 1,000-character chunks (150 overlap), embedded locally (MiniLM, 384 dimensions), stored in Postgres 16 + pgvector | `ingest`, `store.py`, `embeddings.py` |
| Search | Hybrid: vector + BM25 keyword search merged by Reciprocal Rank Fusion, optional rerank (local cross-encoder or Cohere Rerank), model-free `bm25_light` mode for the 512 MB hosted server | `retrieval.py` |
| Refusal | Refuses when the best match scores below the threshold (0.25) | `retrieval.py` |
| Agent | Chooses between 3 tools: search_regulations, calculate_fees, check_deadline | `agent.py`, `tools.py` |
| Multi-agent | Coordinator routes to registration, tax and employment specialists; a verifier checks claims; one revision; composed answer | `multiagent.py` |
| Structured output | Business checklist as validated JSON (Pydantic), with retry-with-feedback and fact checks against the sources | `structured.py`, `schemas.py` |
| Checklist coverage | Registration, tax and employer duties are always searched (Week 11 fix), so a small shop gets employer steps without typing "staff" | `structured.py` |
| Guardrails | Own code layer always on (topic, injection, citations); optional Guardrails AI layer (valid question, personal-data masking, citation check) | `guardrails.py`, `guards.py` |
| Privacy | ID numbers, mobile numbers and emails masked before any third-party call | `privacy.py` |
| Observability | Trace per request, span per step, Cost & speed tab, Langfuse export (metadata only) | `observability.py` |
| Web app | FastAPI with live progress (SSE), access code, per-hour rate limit, daily token budget | `webapp.py` |
| Deployment | Docker image, Neon Postgres, Render Blueprint, parity check between local and staging | `Dockerfile.web`, `render.yaml`, `scripts/parity_check.py` |
| Security | Secret scanner (working tree and history), secrets audit, data-flow diagram, LLM data compliance note | `scripts/secret_scan.py`, `docs/` |
| Quality | Benchmark of 44 + 6 questions (Hit@k, MRR, refusals, paired bootstrap), automated tests, CI | `benchmark.py`, `tests/` |

## What it deliberately does not do

- It does not give legal advice, and it does not file anything with the Registrar or ZIMRA.
- It does not remember users or store their questions beyond the trace file.
- It does not answer from general knowledge. If the documents do not cover a question, it says so.
- It does not mask names or addresses in questions (only ID numbers, mobile numbers, emails).

## Known limits (state these before being asked)

- The documents are a fixed set. Rates and deadlines change, so answers carry the document date.
- Hybrid search beat pure vector on the benchmark, but the gain is not statistically established
  (paired bootstrap). Reranking gain is also not established.
- The hosted site runs `bm25_light` (no embedding model, to fit 512 MB), so its results can
  differ from local. The parity check compares them; wording varies between runs.
- Render's free tier sleeps when idle (cold start) and is about 2 to 3 times slower than local.
- Cost figures in the Cost & speed tab use placeholder prices, not real Groq billing.
- Employer steps in a checklist are conditional ("If you hire staff:") unless the owner says
  they have staff.
- Not done: Vault demo for the secrets audit, LangSmith.

## How to demonstrate it (Demo Day order)

1. Ask a factual question: "What does the Labour Act say about maternity leave?" Show the citation.
2. Ask something off-topic. Show the refusal.
3. Type "Hair salon in Harare" in the checklist box. Show registration, tax and employer steps.
4. Open the Cost & speed tab, then the Langfuse trace for the same request.
5. Show the parity report, the benchmark table and the data-flow diagram.
