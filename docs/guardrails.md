# Guardrails

## Purpose

Guardrails are the fully local checks that stop bad or unsupported input from reaching a model, reject weak retrieval before an answer is formed, and keep answers tied to the retrieved sources.

The implementation lives in `src/startright/guardrails.py`, `src/startright/multiagent.py`, `src/startright/structured.py`, and relevant tool and agent flows in `src/startright/tools.py`.

The main goals are:

- block empty, hostile, or overlong user input before any model call
- refuse when search is too weak to support an answer
- keep citations to source material that actually appeared in retrieval results
- check figures, percentages, dates, amounts, sections, chapters and form names against source text
- ensure checklist steps and fees are grounded in the retrieved evidence

## How it works

### 1. Input checks before any model call

These checks run in `check_question()` before the system calls Groq or any other model.

| Guardrail | Where it runs | What it catches | Token cost |
|---|---|---|---|
| empty question | `check_question()` | blank or whitespace input | 0 tokens |
| max length | `check_question()` | questions longer than 1,000 characters | 0 tokens |
| prompt-injection patterns | `check_question()` | phrases like “ignore all previous instructions”, “reveal your system prompt”, “developer mode” | 0 tokens |

If any check triggers, the code returns a refusal message and never sends the request to a model.

### 2. Retrieval refusal guardrail

The code uses `MIN_SCORE = 0.25` in `src/startright/tools.py`.

- `search_regulations()` filters out hits whose `score` is below `0.25`.
- The code comments in `src/startright/retrieval.py` state that each hit keeps its vector cosine score specifically because the refusal guardrail depends on it.
- This is a pre-model refusal: if the best retrieved vector similarity is below the threshold, the system refuses without generating an answer.

| Guardrail | Where it runs | What it catches | Token cost |
|---|---|---|---|
| low similarity refusal | `search_regulations()` and agent/tool search paths | weak retrieval results, no reliable legal source | 0 tokens |

### 3. Agent and verifier guardrails

The team-based answer flow in `src/startright/multiagent.py` includes additional verification and retry logic.

- The coordinator only routes to relevant specialists and declines clearly off-topic questions.
- The verifier checks that answer claims are grounded in retrieved evidence before accepting a finding.
- Un-grounded or unsupported numeric claims are flagged via `ungrounded_claims()`.
- The code checks several claim types: percentages, days and periods, cents, money amounts, sections, chapters and form names.

| Guardrail | Where it runs | What it catches | Token cost |
|---|---|---|---|
| agent/team verifier | `verify_finding()` and `ungrounded_claims()` | invented percentages, amounts, day counts, form names, section/chapter references | model-backed retry cost |
| checklist validation | `validate_against_sources()` | unsupported fee amounts and steps | model-backed retry cost |

Unlike the early input and retrieval checks, these are not zero-token guardrails. They can trigger a model retry loop when the output is not sufficiently supported by the retrieved sources.

### 4. Citation and grounding checks

The project keeps a strong rule: a citation must refer to a source that a search returned. This is enforced in the structured checklist path.

In `src/startright/structured.py`:

- `validate_against_sources()` checks that each step references a valid source number.
- Every fee amount in the checklist must appear in the cited source text.
- Every text claim in the checklist step is checked with `ungrounded_claims()` against the retrieved source evidence.
- The code also blocks placeholders such as `?`, `TBD`, `N/A` and similar invalid values at the schema layer.

| Guardrail | Where it runs | What it catches | Token cost |
|---|---|---|---|
| citation source existence | `validate_against_sources()` | source_n that does not exist or was not returned | model-backed retry cost |
| claim grounding | `ungrounded_claims()` | unsupported percentages, fees, day counts, chapters, forms | model-backed retry cost |
| schema validation | `generate_structured()` + Pydantic | placeholders and bad schema output | model-backed retry cost |

### 5. Code-level guardrails for tool use

The business tools are also protected by code rules.

- `check_deadline` is not allowed to run until a search has returned results; the code comments and flow in `multiagent.py` require this.
- `calculate_fees` only accepts amounts that are explicit numbers or values supplied by the user or a search result; it refuses invalid amounts.
- A mandatory notice is appended to the checklist output: “This is general information, not legal advice. Please confirm with the relevant official office.”

| Guardrail | Where it runs | What it catches | Token cost |
|---|---|---|---|
| date tool gating | `multiagent.py` / tool flow | using `check_deadline` without evidence | 0 tokens while the tool is gated |
| fee validation | `calculate_fees()` | invalid or invented numeric values | 0 tokens |
| legal-advice footer | `render_checklist()` | missing required disclaimer | 0 tokens |

## Key decisions and why

- Cheap checks come first
  - A user prompt is rejected before any model attempt if it is empty, too long, or explicitly trying to override system instructions.
  - This is the cheapest and most reliable safety layer.

- Retrieval score guardrail is intentionally simple
  - The project does not run a model to judge whether evidence is strong enough; it uses the vector cosine threshold directly.
  - This is cheap and predictable, but it can also be conservative.

- Grounding checks are claim-based, not just citation-based
  - A citation alone is not enough. The project checks that the numbers and named entities in the answer actually appear in the evidence text.
  - This specifically addresses the failure mode where a citation looks valid but the claim is wrong.

- Structured output is an enforcement layer, not a substitute for retrieval quality
  - The Pydantic schema rejects placeholders and malformed responses, but it cannot create missing legal evidence.
  - This is why retrieval quality remains important even with strong validation.

## Limitations

- Personal-data masking is noted as not yet done; this is a future Week 10 item.
- The guardrails do not do LLM-based answer judging. They are rule-based and evidence-based rather than a learned judge.
- A citation can still be attached to a claim that is only partly supported. The current grounding checks are better than naive citation checks but are not a full claim-level verifier.
- The code explicitly catches percentages, amounts, day counts, form names, chapter references and section references; the design notes that years, months and other temporal references are not treated with the same strictness yet.

## What comes next

- Week 9 observability: trace when guardrails trigger and record the token cost and latency around each model step.
- Extend the enforcement to personal-data masking and claim-level checking across longer answer chains.
- Keep the zero-token refusal paths as the first line of defense; the model-backed checks should only run when retrieval has produced real evidence.
