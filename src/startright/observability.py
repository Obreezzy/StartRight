"""Week 9: observability. Every question becomes a trace: a tree of timed steps (the
coordinator, each search, each model call, the checks) with tokens and an estimated cost.

Two sinks, both optional and both safe to fail:
  1. A local file (data/traces.jsonl) that feeds the "Cost and speed" tab. Always on.
  2. Langfuse (https://langfuse.com), when LANGFUSE_PUBLIC_KEY and LANGFUSE_SECRET_KEY are set.

Privacy: traces hold timings, token counts, step names and counts only. The question and
the answer are NOT stored or sent unless TRACE_CONTENT=1 (Week 10 adds masking for that).

Why explicit objects and a "resume" wrapper instead of plain context variables: the web
page streams answers from a generator that the server resumes on different threads, and a
context variable set in one resume is gone in the next. `resume()` sets it again each time.
"""
from __future__ import annotations

import contextvars
import functools
import json
import logging
import math
import os
import threading
import time
import uuid
from collections import deque
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger("startright.obs")

_CURRENT: contextvars.ContextVar = contextvars.ContextVar("startright_trace", default=None)
_LOCK = threading.Lock()
_RECENT: deque = deque(maxlen=500)
_LOADED = {"done": False}
_LF = {"client": None, "checked": False}


# ---------- settings ----------

def _float_env(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, default))
    except ValueError:
        return default


def pricing() -> dict:
    """Dollars per million tokens. Placeholders: confirm on Groq's pricing page and set
    PRICE_INPUT_PER_M / PRICE_OUTPUT_PER_M. The free tier itself costs $0."""
    return {
        "input_per_million": _float_env("PRICE_INPUT_PER_M", 0.075),
        "output_per_million": _float_env("PRICE_OUTPUT_PER_M", 0.30),
    }


def estimate_cost(tokens_in: int, tokens_out: int) -> float:
    p = pricing()
    return (tokens_in * p["input_per_million"] + tokens_out * p["output_per_million"]) / 1_000_000


def trace_file() -> Path:
    return Path(os.getenv("TRACE_FILE", "data/traces.jsonl"))


def capture_content() -> bool:
    return os.getenv("TRACE_CONTENT", "0") == "1"


# ---------- Langfuse (optional) ----------

def langfuse_client():
    if _LF["checked"]:
        return _LF["client"]
    _LF["checked"] = True
    if os.getenv("LANGFUSE_ENABLED", "1") == "0":
        return None
    if not (os.getenv("LANGFUSE_PUBLIC_KEY") and os.getenv("LANGFUSE_SECRET_KEY")):
        return None
    try:
        from langfuse import get_client

        _LF["client"] = get_client()
    except Exception as exc:  # missing package or bad config: tracing must never break answers
        log.warning("Langfuse is not available: %s", exc)
        _LF["client"] = None
    return _LF["client"]


def langfuse_status() -> dict:
    client = langfuse_client()
    host = os.getenv("LANGFUSE_HOST") or os.getenv("LANGFUSE_BASE_URL") or "https://cloud.langfuse.com"
    return {"enabled": client is not None, "host": host if client is not None else None}


_FLUSHING = threading.Event()


def _flush_in_background(client) -> None:
    """Send the spans without making the visitor wait (a free plan that has been asleep, or an
    unreachable Langfuse, can take seconds). One flush at a time; the next trace picks up
    anything left over."""
    if _FLUSHING.is_set():
        return
    _FLUSHING.set()

    def run():
        try:
            _safe(client.flush)
        finally:
            _FLUSHING.clear()

    threading.Thread(target=run, daemon=True, name="langfuse-flush").start()


def reset() -> None:
    """For tests: forget cached state."""
    _LF.update(client=None, checked=False)
    _LOADED["done"] = False
    _RECENT.clear()


_KIND_TO_LF = {"step": "span", "llm": "generation", "retrieval": "retriever", "tool": "tool"}


def _safe(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except Exception as exc:
        log.debug("tracing call failed: %s", exc)
        return None


# ---------- spans and traces ----------

class Span:
    def __init__(self, trace: "Trace", name: str, kind: str, parent: "Span | None", attrs: dict):
        self.trace, self.name, self.kind, self.parent = trace, name, kind, parent
        trace.counter += 1
        self.id = trace.counter
        self.attrs = dict(attrs)
        self.tokens_in = self.tokens_out = self.tokens_total = 0
        self.status, self.error = "ok", None
        self.t0 = time.perf_counter()
        self.start_ms = round((self.t0 - trace.t0) * 1000)
        self.ms = 0
        self.lf = None
        lf_parent = parent.lf if parent else trace.lf
        if lf_parent is not None:
            self.lf = _safe(
                lf_parent.start_observation, name=name, as_type=_KIND_TO_LF.get(kind, "span"),
                model=attrs.get("model") if kind == "llm" else None,
            )

    def set(self, **attrs) -> None:
        self.attrs.update({k: v for k, v in attrs.items() if v is not None})

    def tokens(self, tokens_in: int = 0, tokens_out: int = 0, total: int = 0) -> None:
        self.tokens_in, self.tokens_out = int(tokens_in or 0), int(tokens_out or 0)
        self.tokens_total = int(total or 0) or self.tokens_in + self.tokens_out

    def finish(self) -> dict:
        self.ms = round((time.perf_counter() - self.t0) * 1000)
        if self.lf is not None:
            update = {"metadata": {**self.attrs, "ms": self.ms}}
            if self.kind == "llm":
                update["usage_details"] = {"input": self.tokens_in, "output": self.tokens_out}
                update["cost_details"] = {"total": round(estimate_cost(self.tokens_in, self.tokens_out), 8)}
            if self.status == "error":
                update.update(level="ERROR", status_message=self.error)
            _safe(self.lf.update, **update)
            _safe(self.lf.end)
        record = {
            "id": self.id, "parent_id": self.parent.id if self.parent else None,
            "name": self.name, "kind": self.kind, "start_ms": self.start_ms, "ms": self.ms,
            "status": self.status, "parent": self.parent.name if self.parent else None,
            "tokens": self.tokens_total,
            "cost_usd": round(estimate_cost(self.tokens_in, self.tokens_out), 8) if self.kind == "llm" else 0,
            "attrs": self.attrs,
        }
        if self.error:
            record["error"] = self.error
        return record


class Trace:
    def __init__(self, name: str, **attrs):
        self.id = uuid.uuid4().hex[:12]
        self.name = name
        self.attrs = dict(attrs)
        self.t0 = time.perf_counter()
        self.started = datetime.now(timezone.utc)
        self.spans: list[dict] = []
        self.open: list[Span] = []
        self.counter = 0
        self.lf = None
        self.done = False
        client = langfuse_client()
        if client is not None:
            self.lf = _safe(client.start_observation, name=name, as_type="span",
                            metadata={"trace_id": self.id, **attrs})

    def annotate(self, **attrs) -> None:
        self.attrs.update({k: v for k, v in attrs.items() if v is not None})

    @contextmanager
    def span(self, name: str, kind: str = "step", **attrs):
        parent = self.open[-1] if self.open else None
        span = Span(self, name, kind, parent, attrs)
        self.open.append(span)
        try:
            yield span
        except BaseException as exc:
            # a visitor closing the page ends the generator with GeneratorExit: not an error
            span.status = "cancelled" if isinstance(exc, GeneratorExit) else "error"
            span.error = type(exc).__name__
            raise
        finally:
            if span in self.open:
                self.open.remove(span)
            self.spans.append(span.finish())

    def finish(self) -> dict:
        """Close the trace, store it, and return the summary."""
        if self.done:
            return self.summary
        self.done = True
        for span in list(self.open):  # a request that was cut off mid-step
            span.status, span.error = "cancelled", "interrupted"
            self.spans.append(span.finish())
        total_ms = round((time.perf_counter() - self.t0) * 1000)
        llm = [s for s in self.spans if s["kind"] == "llm"]
        retrieval = [s for s in self.spans if s["kind"] == "retrieval"]
        tokens = self.attrs.get("tokens") or sum(s["tokens"] for s in llm)
        cost = round(sum(s["cost_usd"] for s in llm), 8)
        roll_up_model_cost(self.spans)  # after the totals, so nothing is counted twice
        statuses = {s["status"] for s in self.spans}
        outcome = self.attrs.get("outcome") or (
            "error" if "error" in statuses else "cancelled" if "cancelled" in statuses else "ok")
        summary = {
            "id": self.id, "time": self.started.strftime("%Y-%m-%d %H:%M:%S"), "name": self.name,
            "mode": self.attrs.get("mode", self.name), "outcome": outcome, "ms": total_ms,
            "tokens": int(tokens), "cost_usd": cost,
            "llm_calls": len(llm), "searches": len(retrieval),
            "llm_ms": sum(s["ms"] for s in llm), "retrieval_ms": sum(s["ms"] for s in retrieval),
            "retrieval_mode": self.attrs.get("retrieval_mode"),
            "alerts": alerts_for(total_ms, int(tokens), outcome),
            "spans": self.spans,
        }
        self.summary = summary
        if self.lf is not None:
            _safe(self.lf.update, metadata={k: v for k, v in summary.items() if k != "spans"})
            _safe(self.lf.end)
            client = langfuse_client()
            if client is not None and os.getenv("LANGFUSE_FLUSH_EACH", "1") == "1":
                _flush_in_background(client)
        store(summary)
        for alert in summary["alerts"]:
            log.warning("trace %s alert=%s ms=%s tokens=%s", self.id, alert, total_ms, tokens)
        return summary


def roll_up_model_cost(spans: list[dict]) -> None:
    """Show each step's tokens and cost: add every model call to each step above it."""
    by_id = {s["id"]: s for s in spans}
    for step in spans:
        if step["kind"] != "llm":
            step["tokens"], step["cost_usd"] = 0, 0
    for call in [s for s in spans if s["kind"] == "llm"]:
        parent = by_id.get(call["parent_id"])
        while parent is not None:
            parent["tokens"] += call["tokens"]
            parent["cost_usd"] = round(parent["cost_usd"] + call["cost_usd"], 8)
            parent = by_id.get(parent["parent_id"])


def alerts_for(ms: int, tokens: int, outcome: str) -> list[str]:
    found = []
    if ms > _float_env("SLOW_MS", 20000):
        found.append("slow")
    if tokens > _float_env("HIGH_TOKENS", 8000):
        found.append("expensive")
    if outcome in ("error", "failed"):
        found.append("error")
    return found


# ---------- current trace helpers (safe to call anywhere) ----------

def current() -> "Trace | None":
    return _CURRENT.get()


def start_trace(name: str, **attrs) -> Trace:
    return Trace(name, **attrs)


@contextmanager
def span(name: str, kind: str = "step", **attrs):
    """A timed step inside the current trace. Does nothing when no trace is active."""
    trace = current()
    if trace is None:
        yield None
        return
    with trace.span(name, kind, **attrs) as s:
        yield s


def annotate(**attrs) -> None:
    trace = current()
    if trace is not None:
        trace.annotate(**attrs)


def resume(trace: Trace, generator):
    """Run `generator` so that `current()` is `trace` every time the generator is resumed,
    whichever thread the server resumes it on, and close the trace when it ends."""
    try:
        while True:
            token = _CURRENT.set(trace)
            try:
                item = next(generator)
            except StopIteration:
                return
            finally:
                _CURRENT.reset(token)
            yield item
    finally:
        generator.close()
        trace.finish()


def traced_node(name: str, fn):
    """Wrap one graph step so it shows up as a span."""
    @functools.wraps(fn)
    def wrapper(state):
        trace = current()
        if trace is None:
            return fn(state)
        with trace.span(name, "step"):
            return fn(state)
    return wrapper


# ---------- wrapping the model client and the search ----------

class _Completions:
    def __init__(self, inner):
        self._inner = inner

    def create(self, **kwargs):
        trace = current()
        if trace is None:
            return self._inner.create(**kwargs)
        with trace.span("llm", "llm", model=kwargs.get("model")) as span_:
            response = self._inner.create(**kwargs)
            usage = getattr(response, "usage", None)
            span_.tokens(getattr(usage, "prompt_tokens", 0), getattr(usage, "completion_tokens", 0),
                         getattr(usage, "total_tokens", 0))
            return response

    def __getattr__(self, name):
        return getattr(self._inner, name)


class _Chat:
    def __init__(self, inner):
        self._inner = inner
        self.completions = _Completions(inner.completions)

    def __getattr__(self, name):
        return getattr(self._inner, name)


class TracedClient:
    """Looks like a Groq client; every chat.completions.create call becomes a span."""

    def __init__(self, client):
        self._client = client
        self.chat = _Chat(client.chat)

    def __getattr__(self, name):
        return getattr(self._client, name)


def wrap_client(client):
    return client if isinstance(client, TracedClient) else TracedClient(client)


def instrument_retrieval() -> None:
    """Make every document search a span. Safe to call more than once."""
    from startright import retrieval

    if getattr(retrieval.search, "_traced", False):
        return
    original = retrieval.search

    @functools.wraps(original)
    def traced(query, *args, **kwargs):
        trace = current()
        if trace is None:
            return original(query, *args, **kwargs)
        mode = kwargs.get("mode") or os.getenv("RETRIEVAL_MODE", "hybrid")
        with trace.span("retrieval", "retrieval", mode=mode) as span_:
            hits = original(query, *args, **kwargs)
            span_.set(hits=len(hits), top_score=round(float(hits[0]["score"]), 3) if hits else None)
            return hits

    traced._traced = True
    retrieval.search = traced


# ---------- storage ----------

def store(summary: dict) -> None:
    with _LOCK:
        _RECENT.append(summary)
        try:
            path = trace_file()
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(summary) + "\n")
        except OSError as exc:
            log.debug("could not write traces: %s", exc)


def load_recent(limit: int = 500) -> list[dict]:
    """Traces from this run, plus earlier ones from the file the first time it is asked."""
    with _LOCK:
        if not _LOADED["done"]:
            _LOADED["done"] = True
            earlier = []
            try:
                lines = trace_file().read_text(encoding="utf-8").splitlines()[-limit:]
                earlier = [json.loads(line) for line in lines if line.strip()]
            except (OSError, ValueError):
                earlier = []
            known = {t["id"] for t in _RECENT}
            merged = [t for t in earlier if t.get("id") not in known] + list(_RECENT)
            _RECENT.clear()
            _RECENT.extend(merged[-limit:])
        return list(_RECENT)[-limit:]


# ---------- summaries for the dashboard ----------

def percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0
    ordered = sorted(values)
    rank = max(1, math.ceil(pct / 100 * len(ordered)))
    return ordered[rank - 1]


def summarize(traces: list[dict]) -> dict:
    n = len(traces)
    if not n:
        return {"count": 0}
    ms = [t["ms"] for t in traces]
    tokens = [t["tokens"] for t in traces]
    llm_ms = sum(t["llm_ms"] for t in traces)
    retrieval_ms = sum(t["retrieval_ms"] for t in traces)
    total_ms = sum(ms)
    other_ms = max(0, total_ms - llm_ms - retrieval_ms)
    outcomes: dict[str, int] = {}
    alerts: dict[str, int] = {}
    by_mode: dict[str, dict] = {}
    steps: dict[str, dict] = {}
    for t in traces:
        outcomes[t["outcome"]] = outcomes.get(t["outcome"], 0) + 1
        for a in t["alerts"]:
            alerts[a] = alerts.get(a, 0) + 1
        m = by_mode.setdefault(t["mode"], {"count": 0, "ms": 0, "tokens": 0, "cost_usd": 0.0})
        m["count"] += 1
        m["ms"] += t["ms"]
        m["tokens"] += t["tokens"]
        m["cost_usd"] += t["cost_usd"]
        for s in t["spans"]:
            e = steps.setdefault(s["name"], {"name": s["name"], "kind": s["kind"], "calls": 0,
                                             "times": [], "tokens": 0, "cost_usd": 0.0, "errors": 0})
            e["calls"] += 1
            e["times"].append(s["ms"])
            e["tokens"] += s["tokens"]
            e["cost_usd"] += s["cost_usd"]
            e["errors"] += s["status"] == "error"
    step_rows = [
        {"name": e["name"], "kind": e["kind"], "calls": e["calls"],
         "avg_ms": round(sum(e["times"]) / e["calls"]), "p95_ms": percentile(e["times"], 95),
         "tokens": e["tokens"], "cost_usd": round(e["cost_usd"], 8), "errors": e["errors"]}
        for e in steps.values()
    ]
    step_rows.sort(key=lambda r: -r["avg_ms"] * r["calls"])
    return {
        "count": n,
        "outcomes": outcomes,
        "alerts": alerts,
        "latency_ms": {"avg": round(total_ms / n), "p50": percentile(ms, 50),
                       "p95": percentile(ms, 95), "max": max(ms)},
        "tokens": {"total": sum(tokens), "avg": round(sum(tokens) / n), "p95": percentile(tokens, 95)},
        "cost_usd": {"total": round(sum(t["cost_usd"] for t in traces), 8),
                     "avg": round(sum(t["cost_usd"] for t in traces) / n, 8)},
        "time_split_ms": {"model": round(llm_ms / n), "search": round(retrieval_ms / n),
                          "other": round(other_ms / n)},
        "by_mode": {k: {"count": v["count"], "avg_ms": round(v["ms"] / v["count"]),
                        "avg_tokens": round(v["tokens"] / v["count"]),
                        "cost_usd": round(v["cost_usd"], 8)} for k, v in by_mode.items()},
        "steps": step_rows,
    }


def dashboard(limit_recent: int = 15) -> dict:
    traces = load_recent()
    recent = traces[-limit_recent:][::-1]
    return {
        "summary": summarize(traces),
        "recent": recent,
        "pricing": pricing(),
        "thresholds": {"slow_ms": _float_env("SLOW_MS", 20000), "high_tokens": _float_env("HIGH_TOKENS", 8000)},
        "langfuse": langfuse_status(),
        "content_captured": capture_content(),
    }
