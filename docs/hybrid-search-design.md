# Hybrid retrieval design

## Purpose

Week 8 adds a hybrid search stack to the project so retrieval is less dependent on a single embedding neighborhood and is more resilient to acronym drift, exact legal wording, and pages that look semantically close but are not the right legal provision.

This is based on the repository code in `src/startright/retrieval.py`, the benchmark data in `data/benchmark.json` and `data/benchmark_results_before.json` / `_after.json`, and the benchmark logic in `src/startright/benchmark.py`. The project keeps everything local: no API tokens are used for retrieval or reranking.

The code defines four retrieval modes:

- `vector`: Week 4 baseline, embeddings only
- `bm25`: in-memory Okapi BM25 keyword search with a small stemmer
- `hybrid`: vector + BM25 merged by Reciprocal Rank Fusion (RRF)
- `hybrid_rerank`: hybrid candidates re-scored with a local cross-encoder

The environment variable `RETRIEVAL_MODE` selects the mode, and the agent, team and checklist flows all use it. The older `ask` command remains vector-only as the baseline.

## How it works

1. Query preparation
   - The search code lowercases the query and tokenizes it with a small stemmer.
   - It expands acronyms that are explicitly mapped in `ACRONYMS`, for example `nssa -> National Social Security Authority`, `zimra -> Zimbabwe Revenue Authority`, `vat -> value added tax`.
   - `expand_query()` appends the expanded full names to the query before BM25 or hybrid search.

2. BM25 index
   - `BM25Index` builds an in-memory index over all chunks using the document corpus loaded from the database.
   - The code uses a compact Okapi BM25 setup: `k1 = 1.5`, `b = 0.75`.
   - Tokenization removes stop words and applies the same small stemmer to both queries and chunks.
   - Search is limited to a candidate set and respects the optional `scope` filter for specific document families.

3. Vector search
   - Vector search uses local embeddings created by `embed_texts()`.
   - Each hit keeps the cosine similarity as `score` for the refusal guardrail (`MIN_SCORE = 0.25`) because the guardrail depends on vector similarity, not BM25 score.

4. Fusion
   - The hybrid mode performs two ranked searches: vector and BM25.
   - It fuses them with Reciprocal Rank Fusion using `RRF_K = 60`.
   - Each list contributes ranks; score scales are not compared directly because the two methods are not on the same scale.

5. Reranking
   - `hybrid_rerank` takes the top fused candidates and re-scores them with the local `cross-encoder/ms-marco-MiniLM-L-6-v2` model.
   - The code loads this model via `sentence_transformers.CrossEncoder` and applies it to `(query, chunk)` pairs.
   - This is a local model and the README also notes that it is a small local model, not a remote API call.

6. Benchmarking
   - `src/startright/benchmark.py` evaluates answerable and off-topic questions against a benchmark dataset.
   - A retrieved chunk counts as relevant only when it comes from the expected file and contains one of the key phrases in `must_contain_any`.
   - The benchmark checks exact `Hit@4`, `MRR@10`, correct refusals and false refusals.
   - `benchmark --validate` checks every answerable item against the database with plain keyword matching, to catch benchmark items whose phrases are wrong or impossible.

## Key decisions and why

- RRF instead of a direct weighted sum
  - Cosine similarity and BM25 operate on different scales, so the code uses ranks instead of raw scores.
  - This is a conservative choice and matches the code comments in `retrieval.py`.

- Acronym expansion is in-code, not just in the prompt
  - `expand_query()` adds the full legal names that the project knows, such as `NSSA` and `VAT`.
  - This is important because the benchmark documents show that acronym-only queries miss the correct source on several legal questions.

- Keep vector score on each hit
  - The refusal guardrail depends on vector cosine similarity staying attached to the retrieval result.
  - The design purposely does not replace `score` with a rerank score when the hit is fetched for refusal logic.

- Local-only retrieval stack
  - The local `/search` endpoint is intentionally not included in the Docker image because the embedding model would make the image several GB.
  - That is a design decision captured in `src/startright/search_api.py` and matches the project’s zero-budget local-first aim.

- Benchmark validation is intentionally plain and conservative
  - The code does not attempt deep semantic matching when validating benchmark items; it checks for `expected_files` and phrase presence.
  - That makes the benchmark repeatable but also means some hits may still be judged as missed if a phrase is too specific or the extracted text is unusual.

## Measured results

These numbers come from the benchmark output files already in the repo (`data/benchmark_results_before.json` and `data/benchmark_results_after.json`). I did not rerun the benchmark in this session.

### After text cleaning

| Mode | Hit@4 | MRR@10 | Notes |
|---|---:|---:|---|
| vector | 84% | 0.76 | Week 4 baseline |
| bm25 | 82% | 0.74 | keyword-only baseline |
| hybrid | 84% | 0.75 | RRF fusion alone |
| hybrid_rerank | 89% | 0.82 | hybrid + cross-encoder |

Refusals: 6/6 correct refusals in every mode; 0 false refusals in every mode.

### Before text cleaning

| Mode | Hit@4 | MRR@10 | Notes |
|---|---:|---:|---|
| vector | 82% | 0.73 | |
| bm25 | 80% | 0.71 | |
| hybrid | 82% | 0.72 | |
| hybrid_rerank | 86% | 0.80 | |

The only known benchmark difference in the miss lists before vs after was `q02` (the impossible item that got corrected). That matches the project notes: a text-cleaning fix changed only one benchmark item in this dataset.

### Question-type breakdown (after text cleaning)

Based on the benchmark summary in the repo, the hit rates by type were:

- acronym: vector 3/5, bm25 3/5, hybrid 4/5, hybrid_rerank 4/5
- entity-type: vector 5/7, bm25 6/7, hybrid 5/7, hybrid_rerank 6/7
- exact-term: vector 10/12, bm25 10/12, hybrid 10/12, hybrid_rerank 11/12
- missed-before: all modes 1/1
- notice: vector 5/6, bm25 6/6, hybrid 6/6, hybrid_rerank 6/6
- paraphrase: vector 13/13, bm25 10/13, hybrid 11/13, hybrid_rerank 11/13

### Misses in the top 4 (after text cleaning)

- vector: `q03 q04 q18 q21 q24 q33 q40`
- bm25: `q03 q18 q23 q24 q26 q31 q32 q33`
- hybrid: `q03 q04 q18 q24 q26 q31 q33`
- hybrid_rerank: `q03 q21 q26 q31 q33`

### Honest findings

- Plain hybrid did not beat vector on Hit@4; it was tied on Hit@4 and slightly lower on MRR. The gain appears only when the reranker is added.
- The reranker produced the measurable gain: after text cleaning, hybrid_rerank was 89% Hit@4 and 0.82 MRR vs vector at 84% and 0.76.
- No mode wins everywhere: vector still found `q26` and `q31`, while hybrid fixed the acronym case `q21` and some notice questions.
- The benchmark is small enough that small differences are directional rather than decisive: with 44 answerable questions, one question is worth 2.3 percentage points.
- `q03` and `q33` were missed by every mode, and the project still needs to verify whether that is a retrieval failure or a benchmark phrase problem.

## Limitations

- The benchmark labels are approximate, not deep legal semantics. A chunk is marked relevant only if it comes from an expected file and contains one of the manually defined phrases.
- Some legal wording is awkward in the extracted PDF text. The project found ligature issues (`fi`, `ffi`, `ff`, `fl`) and cleaned them before re-ingesting the corpus.
- The benchmark validation noted that `q02` and `q09` had zero matching chunks before the text clean-up, which caused the benchmark to be re-run.
- The question set is small and targeted. It is good for regression testing, not a broad claim about all legal retrieval.
- TODO(verify): paste the ligature count query result before and after the text-cleaning fix.
- TODO(verify): determine whether `q03` and `q33` are retrieval misses or benchmark-keyphrase errors.

## What comes next

- Week 9 observability: add Langfuse tracing, token cost, and latency per step.
- Continue collecting focused retrieval regressions around acronym-heavy queries and notices.
- Keep the benchmark validation step in place so bad key phrases are caught before claims are made about search quality.
- Keep local-only deployment and zero-token retrieval as a design principle unless the project deliberately moves to a hosted service.
