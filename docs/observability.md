# Observability: tracing, cost and speed (Week 9)

## Why this exists

During the web-app build one question took 130 to 400 seconds and nothing in the app said why.
The cause was a 130-second database connection on every search (Windows resolving `localhost`
to IPv6 first). It was found only by writing a throw-away timing script. Observability makes
that kind of problem visible in seconds instead of an afternoon.

## What is recorded

Every question becomes one **trace**: a tree of timed steps.

| Step | What it is |
|---|---|
| `coordinate` | the coordinator reads the question and plans |
| `specialists` / `specialist` | each specialist's work (one per agent) |
| `retrieval` | each document search: mode, number of hits, top score |
| `llm` | each model call: model, input and output tokens, estimated cost |
| `verify`, `compose` | the code checks and the final answer assembly |
| `gather_sources`, `generate` | the two phases of checklist mode |

Each trace also carries total time, total tokens, estimated cost, outcome
(`ok`, `declined`, `refused`, `failed`, `error`, `cancelled`) and alerts.

## Where it goes

1. **Local file `data/traces.jsonl`** (always on). It feeds the **Cost & speed** tab in
   *Behind the scenes*. On Render's free plan the disk is wiped on each deploy or restart, so
   the tab shows history since then.
2. **Langfuse** (optional). Set the keys and every trace also appears in your Langfuse project,
   with timings, token usage and cost per step, searchable and shareable.

## Privacy rules

* Traces hold **timings, counts and step names only**. The question and the answer are not
  stored or sent. `TRACE_CONTENT=1` is reserved for later: Week 10 adds masking of personal
  data before any text may leave the app.
* The dashboard endpoint `/api/observability` needs the access code when `ACCESS_CODE` is set.

## Cost numbers are estimates

Groq's free tier costs nothing. The dashboard shows what the same traffic would cost on a paid
plan, using `PRICE_INPUT_PER_M` and `PRICE_OUTPUT_PER_M` (dollars per million tokens). The
defaults (0.075 and 0.30) are placeholders: check the current rate for your model on Groq's
pricing page and set both values in `.env`.

## Alerts

A trace is flagged `slow` above `SLOW_MS` (default 20000 ms), `expensive` above `HIGH_TOKENS`
(default 8000) and `error` when a step fails or the outcome is `error` or `failed`. Alerts are
shown on the dashboard and written to the server log as warnings.

## Setting up Langfuse (free, 10 minutes)

1. Go to https://cloud.langfuse.com and sign up (use https://us.cloud.langfuse.com if you want
   US data storage).
2. Create an organization, then a project named `startright`.
3. In the project, open **Settings > API Keys > Create new API key**. Copy the **public** key
   (`pk-lf-...`) and the **secret** key (`sk-lf-...`). The secret is shown once.
4. Add to `.env` (never commit it):

   ```
   LANGFUSE_PUBLIC_KEY=pk-lf-...
   LANGFUSE_SECRET_KEY=sk-lf-...
   LANGFUSE_HOST=https://cloud.langfuse.com
   ```
5. `pip install -r requirements-web.txt`, restart `uvicorn`, ask a question, and open
   **Tracing** in the Langfuse project. Open a trace to see the step tree.

Langfuse failing (wrong key, offline) never affects answers: errors are swallowed and the
upload happens in a background thread.

## Design notes

* **Explicit trace objects, not just context variables.** The page streams answers from a
  generator that the server resumes on different threads, and a context variable set in one
  resume is lost in the next. `observability.resume()` sets it again on every resume.
* **The model client and the search are wrapped, not rewritten.** `TracedClient` and
  `instrument_retrieval()` add spans without changing the agent or retrieval code.
* **Roll-up.** A step's tokens and cost are the sum of the model calls inside it, found by
  parent links, so the totals are never counted twice.
* **Tracing must never break an answer.** Every Langfuse call is wrapped to swallow errors.

## Limits

* Groq's own retries inside one call are invisible: a call that retried shows as one long span.
* Streaming time-to-first-token is not measured (answers are produced whole).
* The cost estimate ignores cached-token discounts.
