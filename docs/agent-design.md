# Week 5: Agent design

## Purpose
The Week 5 agent was the first step from a single retrieval-and-answer flow to a tool-using assistant. The goal was to let StartRight answer legal and compliance questions with a small, explicit tool set instead of relying on model memory. The tools were limited to regulations search, fee totals and deadline arithmetic, all backed by the ingested source documents.

## How it works
The agent loop ran in `src/startright/agent.py`. It sent the question and a system prompt to the model, then allowed up to five rounds of tool calls. The prompt required a search before rule-based or date-based claims, and it told the model to answer only from tool results.

The three tools were:
- `search_regulations`: dense vector search over the ingested documents.
- `calculate_fees`: exact fee sums using `Decimal`.
- `check_deadline`: date arithmetic using the project’s own date logic.

A guardrail was placed in code, not only in the prompt: `check_deadline` was blocked until a `search_regulations` result had already been recorded. This prevented a situation where the model guessed a due day from general knowledge and then used the calculator to produce a deadline-based answer.

The tool results were fed back into the conversation as JSON. Search results were renumbered locally from a starting value so different agents or specialists could avoid overlapping citation numbers.

## Key decisions and why
The main design choice was to keep the agent narrow. We did not let it run free-form legal reasoning. Instead, the model had to search first, use exact arithmetic for fees, and use a helper for dates. This reduced the chance of a fake due date or invented fee total.

Another key choice was the step limit. A maximum of five steps forced the model to make progress quickly and made the behaviour easier to test. It also made token use visible in the project runs.

We also kept tool errors as results instead of exceptions. A failed search or malformed tool input was returned as a JSON error to the model, which meant the agent could recover without crashing. This was useful in development, but it also showed that the model sometimes kept trying without fixing the real issue.

## Measured results
The Week 5 results were mixed but instructive:
- A fee total of 85.50 was calculated correctly and used 1,332 tokens.
- An early VAT run skipped the search and guessed the due day, which produced a bogus citation and cost 1,321 tokens.
- After the `check_deadline` guardrail was added, the agent chained search and deadline logic successfully and answered 10 July 2026 and 91 days ago.
- A maternity leave question used 2,257 tokens.
- An off-topic refusal by the agent used 588 tokens, compared with 0 tokens for the plain ask command.

## Limitations and known issues
The agent was better than plain prompting in many cases, but it was still prone to false confidence. The Guardrail in `agent.py` fixed the most obvious mistake of using a deadline without first finding the relevant day rule, but it did not stop the model from inventing a number when a tool result was not properly checked.

In practice, the model could still produce a plausible answer with a citation that looked valid but did not actually match the source. That is why the Week 6 verifier was needed.

The model also cost more tokens than the plain `ask` flow. The agent was designed for reasoning and tool use, but that flexibility came at a token cost and made a refusal more expensive than a strict retrieval-only answer.

TODO(verify): Labour Act: first run said maternity leave may start "no earlier than the 45th day" before delivery, one run said "40th day". Check page 31 of the Labour Act PDF.

## What comes next
The next step was not to add more tools blindly. It was to add a verifier and then a team of specialists. The check was simple: if a fact, amount, date, form name or percentage is not grounded in the source text or tool output, the model should not keep it. That same idea later became the basis for the Week 6 team flow and the Week 7 checklist schema.

The long-term plan still matches the Week 8 roadmap: add BM25 search next to vector search, add a reranker, tighten guardrails and test against a 40-50 question benchmark. The failures above are the early examples the model must learn from.
