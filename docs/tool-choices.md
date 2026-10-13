# Tool choices: the programme's stack versus what StartRight uses

The AIIA programme lists a reference stack. This note records, for each tool, what StartRight
uses instead (or as well), why, and what the listed tool would add. It exists so the choices
are deliberate and explainable, not accidental.

**Constraints that drove the choices**

1. **Zero budget.** Free tiers only: Groq's free plan for generation, Neon and Render free
   plans for hosting. Anything that bills per call was ruled out unless it has a free tier
   that fits.
2. **Free hosting is small.** Render's free plan has 512 MB of RAM, which cannot hold an
   embedding model plus a reranker. That produced the model-free `bm25_light` search mode.
3. **Learning goal.** Every week is assessed on a working deliverable, so building the core
   mechanism (BM25, fusion, validators, tracing) was worth the extra code.
4. **Legal-style content.** Answers must be traceable to a source. That favours rules the
   code can check (citations, figures, amounts) over a general-purpose guardrail framework.

## Comparison

| Area | Programme tool | StartRight uses | Why | What the listed tool would add |
|---|---|---|---|---|
| Vector store | Pgvector, Pinecone, Weaviate | **pgvector** (Postgres 16, HNSW, cosine) | Listed in the programme; free; chunks, metadata and vectors in one database | A managed service removes database upkeep |
| Orchestration | LangGraph, CrewAI, AutoGen | **LangGraph** | Explicit graph with a revision loop and shared state | None needed |
| Structured output | Pydantic, Instructor | **Pydantic v2 + own retry loop** | Same pattern as Instructor: validate, then re-ask the model with the exact errors | Less code to maintain |
| Keyword search | BM25 | **Own Okapi BM25** (k1 1.5, b 0.75) with a small stemmer | Free, no extra service, and the scoring is understood and unit-tested | A maintained library would be less code |
| Fusion | (hybrid search) | **Reciprocal Rank Fusion**, k = 60 | Combines two rankings without tuning score scales | None needed |
| Reranking | Cohere Rerank, cross-encoders | **Both**: local cross-encoder (`hybrid_rerank`) and **Cohere Rerank** (`hybrid_cohere`, `bm25_cohere`) | Local is free and private; Cohere needs no model in memory, so it fits the 512 MB server. Cohere falls back to the plain order if unavailable. | Measured below |
| Guardrails | Guardrails AI, NeMo Guardrails | **Custom code guardrails** always on, plus **Guardrails AI** as an optional layer (`GUARDRAILS_AI=on`): valid-question, no-personal-data (fix), has-citation validators | The rules are few and checkable; each is unit-tested. Guardrails AI is about 450 MB installed, so it runs locally, not on the free server. NeMo Guardrails was skipped: heavy, and it spends extra model calls. | Declared validators and a standard pass / fail / fix outcome (now used) |
| Observability | LangSmith, Arize, Langfuse, OpenTelemetry | **Own trace layer and Cost & speed dashboard**, plus an optional **Langfuse** export | Free, private, no text stored; Langfuse v4 is built on OpenTelemetry, so the same spans can be exported | Searchable trace history, sharing and team features |
| Secrets | Vault or equivalent | **Environment variables** (`.env` locally, Render dashboard when hosted), GitHub secret scanning | Appropriate for one developer and one service | A secrets manager adds rotation, audit logs and access control |

## How each choice was checked, not just assumed

- **Hybrid versus vector:** measured on a 44-question benchmark (plus 6 off-topic) with Hit@k,
  MRR and refusals. Hybrid with reranking scored higher than vector search, but a paired
  bootstrap did not establish that the difference is statistically significant. The claim in
  this project is "higher on this benchmark", not "proven better".
- **Guardrails:** each rule has a test (see `tests/test_guardrails.py`, `tests/test_multiagent.py`,
  `tests/test_checklist_gate.py`). Real failures found and fixed: the agent skipping search, invented
  figures with valid-looking citations, and an off-topic message passing the checklist gate.
- **Local reranker versus hosted:** compared on the same 44 + 6 questions (50 Cohere calls, none fell back):

  | Mode | Hit@4 | MRR@10 |
  |---|---|---|
  | vector | 84% | 0.76 |
  | hybrid | 84% | 0.75 |
  | hybrid_rerank (local) | 89% | 0.82 |
  | hybrid_cohere | 89% | 0.85 |

  Both rerankers beat plain hybrid and vector. Cohere is slightly ahead on MRR and better on acronym
  questions (5/5 against 4/5) but missed one exact-term question the local model got. The gap is small on 44
  questions and was not tested for significance, so the claim is "slightly higher on this benchmark".

## What would change with a budget

| If budget allowed | Change |
|---|---|
| Hosted reranker | Run Cohere Rerank against the local cross-encoder on the same benchmark; keep whichever wins on quality and latency |
| Larger server | Use `hybrid_rerank` in production instead of the model-free mode |
| Team of engineers | Move traces to LangSmith or hosted Langfuse for shared search; add a secrets manager |
| More compliance pressure | Adopt a guardrails framework so rules are declared in one standard format |

## Still not used, and why
| Tool | Reason |
|---|---|
| LangSmith | Langfuse covers tracing and is free and open source; one tracing backend is enough |
| NeMo Guardrails | Heavy dependencies and extra LLM calls per request; Guardrails AI covers the same need |
| Pinecone, Weaviate | pgvector in the same Postgres keeps chunks, metadata and vectors together at no cost |
| CrewAI, AutoGen | LangGraph already gives an explicit graph with a revision loop |
| Instructor | Pydantic with an own retry loop does the same job |

## Short answer for an assessor

"I built the core pieces myself on a zero budget so I understand how they work, then added the
programme's tools where they fit: Cohere Rerank (benchmarked against my local reranker), Guardrails AI
(as validators over my own checks) and Langfuse (as the trace export). Where I did not use a tool, I can say
why. The choices were measured on my own benchmark and tests."
