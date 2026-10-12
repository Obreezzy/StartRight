# Observability design

## Problem

Before tracing existed, a single web request could take 130 to 400 seconds and the app showed no intermediate signal about what was going wrong. We could not tell whether the delay was in the coordinator, a specialist, the model call, or a document search.

The root cause was a database connect delay on every search: on Windows, `localhost` could resolve to IPv6 first, causing a 130-second connect timeout before the database request ever ran. That was not visible in the page, so finding the issue required a throw-away timing script instead of normal app diagnostics.

## What we trace

Every question becomes one trace: a tree of timed spans. The trace records:

- the coordinator and each specialist step
- each search, with mode and result counts
- each model call, with model name, input/output tokens, and estimated cost
- final verification and composition steps
- total latency, token usage, estimated cost, and alert flags for the whole question

The important point is that the traces are structured around steps, not free-form logs. A trace is a hierarchy, so we can see both the total time for a question and where the time was spent inside it.

In the implementation, each trace is a `Trace` object with nested `Span` objects; every LLM call and retrieval call adds a span without rewriting the rest of the application. This is what makes the dashboard useful: it shows how long each phase took and how much each step cost in token terms.

## Where traces go

Traces are written to two optional sinks:

- Local file: `data/traces.jsonl` is always on. This file is what feeds the Cost & speed tab in the app.
- Langfuse: if `LANGFUSE_PUBLIC_KEY` and `LANGFUSE_SECRET_KEY` are set, the same trace is also exported there.

The local file is the default path for debugging and the dashboard, while Langfuse is a secondary view for richer per-trace inspection and sharing.

## Privacy

The design is intentionally privacy-preserving:

- traces store timings, counts, step names, and summary values only
- question text is not stored in the trace
- answer text is not stored in the trace
- no prompt or output body is sent to Langfuse unless an explicit future content-capture mode is enabled

This keeps the observability data useful for performance diagnosis without turning the app into a question logger. The project still reserves a `TRACE_CONTENT=1` toggle for a future masked-content mode, but the default is strict no-content tracing.

## Decisions and trade-offs

We chose explicit trace objects instead of relying only on context variables because the web app streams a response from a generator that is resumed across threads. A context variable set in one resume can disappear in the next, so the trace had to be reattached on every resume via a wrapper. The `resume()` helper makes the current trace available each time the generator continues.

We also intentionally flush Langfuse in a background thread. A slow or unreachable Langfuse flush should never block the answer from reaching the user, and the project already treats tracing as best-effort infrastructure rather than critical application logic.

Cost reporting is also deliberately approximate. The app records estimated cost by multiplying token usage by a per-million-token rate. This is useful operationally, but it is not the same as a final invoice or a real provider bill. The defaults in code are placeholders and should be validated against the actual model pricing before production use.

TODO: confirm the exact provider rate used for `PRICE_INPUT_PER_M` and `PRICE_OUTPUT_PER_M` against the live Groq pricing page before relying on the cost numbers for billing or SLO work.

## Limits

The tracing system is useful, but it is not a complete model-debugging tool:

- Groq retries inside a single model call are not visible as separate spans; the call still appears as one long LLM span
- streaming time-to-first-token is not measured because the app streams the final answer as a whole rather than measuring the incremental stream in real time
- the cost estimate ignores any cached-token discounts or other pricing exceptions
- the local trace file is a simple append-only log and not a long-term analytics store

In other words, the system is designed to answer “where did the time and tokens go?” rather than “what exactly happened inside the model provider’s backend?”

## What we measured

Using the real trace log in `data/traces.jsonl`, the Cost & speed dashboard currently shows these measured values:

- Questions traced: 9
- Typical time (p50): 1.4 s
- Slowest 5% (p95): 12.7 s
- Average tokens per question: 2,322
- Estimated cost per question: about $0.00022
- Estimated total cost across the recorded traces: about $0.002

This is the actual data captured from the live dashboard after the database issue was fixed and tracing was turned on. The visible baseline is therefore much lower and much more explainable than the original 130-400 second experience. The time split in the dashboard also shows the dominant drag from model work versus search and overhead, which is exactly the signal the project needed to diagnose the earlier outage.

TODO: capture a longer run and expand the dashboard with a larger sample before drawing strong conclusions about long-tail latency or cost by mode.
