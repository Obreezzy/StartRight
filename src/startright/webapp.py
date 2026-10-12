"""The StartRight web app: a chat page plus a small JSON / event-stream API.

Run it locally:   uvicorn startright.webapp:app --port 8002
It needs no embedding model when RETRIEVAL_MODE=bm25_light, so it fits a free 512 MB host.
Answers stream to the page step by step (Server-Sent Events), so people can watch the
plan, the searches, the checks and the final answer appear.
"""
import hmac
import json
import logging
import math
import os
import threading
import time
from collections import defaultdict, deque
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Literal

try:  # a local .env is convenient; hosted servers set real environment variables
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from startright import observability, retrieval
from startright.guardrails import check_question

log = logging.getLogger("startright.web")
STATIC = Path(__file__).parent / "static"


def _int_env(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, default))
    except ValueError:
        return default


# ---------- protecting a free-tier public demo ----------

class RateLimiter:
    """At most `limit` requests per key in a sliding one-hour window (kept in memory)."""

    def __init__(self, clock=time.time, window: int = 3600):
        self.clock, self.window = clock, window
        self._hits: dict[str, deque] = defaultdict(deque)
        self._lock = threading.Lock()

    def check(self, key: str, limit: int) -> int:
        """0 if the request is allowed (and counted); otherwise seconds to wait."""
        now = self.clock()
        with self._lock:
            queue = self._hits[key]
            while queue and now - queue[0] >= self.window:
                queue.popleft()
            if len(queue) >= limit:
                return max(1, math.ceil(self.window - (now - queue[0])))
            queue.append(now)
            if len(self._hits) > 5000:  # forget keys with no recent requests
                for stale in [k for k, q in self._hits.items() if not q]:
                    del self._hits[stale]
            return 0


class DailyBudget:
    """Counts model tokens used today (UTC) so a public link cannot drain the free quota."""

    def __init__(self, clock=time.time):
        self.clock = clock
        self._day = None
        self._used = 0
        self._lock = threading.Lock()

    def _roll(self) -> None:
        today = datetime.fromtimestamp(self.clock(), timezone.utc).date()
        if today != self._day:
            self._day, self._used = today, 0

    def used_today(self) -> int:
        with self._lock:
            self._roll()
            return self._used

    def add(self, tokens: int) -> None:
        with self._lock:
            self._roll()
            self._used += max(0, int(tokens))


class StatsLog:
    """A small in-memory usage log. Stores sizes and timings only, never the questions."""

    def __init__(self, clock=time.time):
        self.clock = clock
        self.recent: deque = deque(maxlen=50)
        self.totals = {"requests": 0, "tokens": 0, "seconds": 0.0}
        self._lock = threading.Lock()

    def record(self, mode: str, tokens: int, seconds: float, tools: int, outcome: str) -> None:
        with self._lock:
            self.totals["requests"] += 1
            self.totals["tokens"] += tokens
            self.totals["seconds"] += seconds
            self.recent.appendleft({
                "time": datetime.fromtimestamp(self.clock(), timezone.utc).strftime("%H:%M:%S"),
                "mode": mode, "tokens": tokens, "seconds": round(seconds, 1),
                "tool_calls": tools, "outcome": outcome,
            })

    def snapshot(self) -> dict:
        with self._lock:
            n = self.totals["requests"]
            return {
                "requests": n,
                "tokens": self.totals["tokens"],
                "avg_tokens": round(self.totals["tokens"] / n) if n else 0,
                "avg_seconds": round(self.totals["seconds"] / n, 1) if n else 0,
                "recent": list(self.recent),
            }


def client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


# ---------- turning results into things a page can show ----------

def sse(event: dict) -> str:
    return "data: " + json.dumps(event, ensure_ascii=False, default=str) + "\n\n"


def source_list(sources: dict[int, dict]) -> list[dict]:
    return [
        {"n": n, "title": s["title"], "page": s["page"], "source_type": s.get("source_type", ""),
         "text": s.get("text", "")[:300]}
        for n, s in sorted(sources.items())
    ]


def step_view(step) -> dict:
    """One tool call, in plain words."""
    result, args = step.result, step.arguments
    ok = "error" not in result
    if step.tool == "search_regulations":
        found = result.get("results", []) if ok else []
        return {
            "tool": step.tool, "ok": ok, "label": "Searched the documents",
            "input": str(args.get("query", "")),
            "summary": f"{len(found)} source(s) found" if ok else result["error"],
            "detail": [f"{r['title']} (page {r['page']})" for r in found[:4]],
        }
    if step.tool == "calculate_fees":
        count = len(args.get("items", [])) if isinstance(args.get("items"), list) else 0
        return {
            "tool": step.tool, "ok": ok, "label": "Added up the fees",
            "input": f"{count} item(s)",
            "summary": f"Total {result.get('currency') or ''} {result.get('total')}".strip()
            if ok else result["error"],
            "detail": [],
        }
    if step.tool == "check_deadline":
        summary = result.get("error", "")
        if ok:
            days = result["days_until_due"]
            when = f"{abs(days)} days ago" if days < 0 else f"in {days} days"
            summary = f"Due {result['due_date']} ({when})"
        return {
            "tool": step.tool, "ok": ok, "label": "Worked out the date",
            "input": f"period ended {args.get('period_end')}, due on day {args.get('day_of_month')}",
            "summary": summary, "detail": [],
        }
    return {"tool": step.tool, "ok": ok, "label": step.tool, "input": "", "summary": "", "detail": []}


def friendly_error(exc: Exception) -> str:
    name = type(exc).__name__
    module = type(exc).__module__ or ""
    if "RateLimit" in name:
        return "The AI service is busy or its free quota is used up. Please try again in a few minutes."
    if "Connection" in name or "Timeout" in name:
        if module.startswith("psycopg"):
            return "The document database is not reachable right now. Please try again."
        return "Could not reach the AI service. Please try again."
    if module.startswith("psycopg"):
        return "The document database is not reachable right now. Please try again."
    return "Something went wrong while answering. Please try again."


def load_insights() -> dict:
    """Benchmark summaries from the saved per-question ranks (before and after text cleaning)."""
    def summarise(ranks: dict) -> dict:
        n = len(ranks)

        def hit(k: int) -> int:
            return sum(1 for v in ranks.values() if v is not None and v <= k)

        return {
            "hit1": hit(1), "hit4": hit(4), "hit10": hit(10), "n": n,
            "mrr": round(sum(1 / v for v in ranks.values() if v) / n, 3) if n else 0,
        }

    runs = {}
    for label in ("before", "after"):
        path = STATIC / f"benchmark_{label}.json"
        if path.exists():
            runs[label] = {m: summarise(r) for m, r in json.loads(path.read_text()).items()}
    return {"runs": runs}


# ---------- the app ----------

class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=2000)
    mode: Literal["answer", "checklist"] = "answer"


def create_app(client_factory=None, clock=time.time) -> FastAPI:
    app = FastAPI(title="StartRight", docs_url=None, redoc_url=None, openapi_url=None)
    limiter, budget, stats = RateLimiter(clock), DailyBudget(clock), StatsLog(clock)
    holder: dict = {}
    try:
        observability.instrument_retrieval()
    except Exception:  # tracing must never stop the app from starting
        log.exception("could not instrument retrieval")

    def get_client():
        if client_factory:
            return observability.wrap_client(client_factory())
        if "client" not in holder:
            from groq import Groq

            holder["client"] = observability.wrap_client(Groq())
        return holder["client"]

    def access_denied(request: Request):
        code = os.getenv("ACCESS_CODE")
        if code and not hmac.compare_digest(
            request.headers.get("x-access-code", "").encode(), code.encode()
        ):
            return JSONResponse({"error": "A valid access code is required."}, status_code=401)
        return None

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; style-src 'self' 'unsafe-inline'; "
            "script-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'"
        )
        return response

    @app.get("/")
    def index():
        return FileResponse(STATIC / "index.html", media_type="text/html")

    @app.get("/api/health")
    def health():
        return {"status": "ok"}

    @app.get("/api/info")
    def info():
        return {
            "model": os.getenv("GROQ_MODEL", "not set"),
            "retrieval_mode": os.getenv("RETRIEVAL_MODE", "hybrid"),
            "rate_limit_per_hour": _int_env("RATE_LIMIT_PER_HOUR", 15),
            "daily_token_budget": _int_env("DAILY_TOKEN_BUDGET", 60000),
            "tokens_used_today": budget.used_today(),
            "access_code_required": bool(os.getenv("ACCESS_CODE")),
        }

    @app.get("/api/stats")
    def get_stats():
        return {**stats.snapshot(), "tokens_used_today": budget.used_today()}

    @app.get("/api/insights")
    def insights():
        return load_insights()

    @app.get("/api/observability")
    def get_observability(request: Request):
        denied = access_denied(request)
        if denied:
            return denied
        return {**observability.dashboard(), "tokens_used_today": budget.used_today(),
                "daily_token_budget": _int_env("DAILY_TOKEN_BUDGET", 60000)}

    @app.post("/api/chat")
    def chat(body: ChatRequest, request: Request):
        denied = access_denied(request)
        if denied:
            return denied
        wait = limiter.check(client_ip(request), _int_env("RATE_LIMIT_PER_HOUR", 15))
        if wait:
            minutes = max(1, wait // 60)
            return JSONResponse(
                {"error": f"Too many questions from your connection. Try again in about {minutes} minute(s)."},
                status_code=429, headers={"Retry-After": str(wait)},
            )
        if budget.used_today() >= _int_env("DAILY_TOKEN_BUDGET", 60000):
            return JSONResponse(
                {"error": "Today's free demo budget is used up. Please come back tomorrow."},
                status_code=429,
            )
        return StreamingResponse(
            run_events(body), media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    def finish(mode: str, started: float, tokens: int, tools: int, outcome: str) -> float:
        seconds = time.time() - started
        observability.annotate(mode=mode, tokens=tokens, outcome=outcome)
        budget.add(tokens)
        stats.record(mode, tokens, seconds, tools, outcome)
        return seconds

    def run_events(body: ChatRequest):
        trace = observability.start_trace(
            "chat", mode=body.mode, retrieval_mode=os.getenv("RETRIEVAL_MODE", "hybrid"))
        return observability.resume(trace, request_events(body))

    def request_events(body: ChatRequest):
        started = time.time()
        refusal = check_question(body.message)
        if refusal:
            finish(body.mode, started, 0, 0, "refused")
            yield sse({"type": "final", "kind": "refusal", "answer": refusal, "tokens": 0, "seconds": 0})
            return
        try:
            client, model, today = get_client(), os.environ["GROQ_MODEL"], date.today()
            if body.mode == "checklist":
                yield from checklist_events(body.message, client, model, today, started)
            else:
                yield from answer_events(body.message, client, model, today, started)
        except Exception as exc:  # never leak internals to the page
            log.exception("request failed")
            finish(body.mode, started, 0, 0, "error")
            yield sse({"type": "error", "message": friendly_error(exc)})

    def answer_events(message, client, model, today, started):
        from startright.multiagent import SPECIALISTS, compose_parts, stream_team

        state: dict = {"question": message}
        shown: dict = {}
        for node, update in stream_team(message, client, model, today):
            state.update(update)
            if node == "coordinate":
                yield sse({
                    "type": "plan", "source": state["plan_source"], "declined": state["declined"],
                    "subtasks": [
                        {"agent": s["agent"], "title": SPECIALISTS[s["agent"]].title, "task": s["task"]}
                        for s in state["subtasks"]
                    ],
                })
            elif node == "specialists":
                for index, finding in enumerate(state["findings"]):
                    if finding is not None and finding is not shown.get(index):
                        shown[index] = finding
                        yield sse({
                            "type": "specialist", "index": index, "agent": finding["agent"],
                            "title": SPECIALISTS[finding["agent"]].title,
                            "steps": [step_view(s) for s in finding["steps"]],
                            "sources": source_list(finding["sources"]),
                        })
            elif node == "verify":
                yield sse({
                    "type": "verify", "revisions": state.get("revisions", 0),
                    "issues": [
                        {"title": SPECIALISTS[i["agent"]].title, "problems": i["problems"]}
                        for i in state["issues"]
                    ],
                })
            elif node == "prepare_revision":
                yield sse({"type": "revision", "count": state["revisions"]})
        parts = compose_parts(state)
        tools = sum(len(f["steps"]) for f in state.get("findings", []) if f)
        tokens = state.get("tokens", 0)
        seconds = finish("answer", started, tokens, tools, "declined" if state.get("declined") else "ok")
        yield sse({
            "type": "final", "kind": "answer", "declined": bool(state.get("declined")),
            "body": parts["body"], "sources": source_list(parts["sources"]),
            "notes": parts["notes"], "revisions": state.get("revisions", 0),
            "tokens": tokens, "seconds": round(seconds, 1),
            "retrieval_mode": os.getenv("RETRIEVAL_MODE", "hybrid"),
        })

    def checklist_events(message, client, model, today, started):
        from startright.multiagent import DECLINE_MESSAGE
        from startright.structured import (
            has_business_words, is_business_description, make_checklist, wrap_checklist_question,
        )

        # The topic check looks at what the visitor typed, before it is rewritten into a question.
        used = 0
        if not has_business_words(message):
            with observability.span("topic_check"):
                is_business, used = is_business_description(client, model, message)
            if not is_business:
                finish("checklist", started, used, 0, "refused")
                yield sse({"type": "final", "kind": "refusal", "answer": DECLINE_MESSAGE,
                           "tokens": used, "seconds": round(time.time() - started, 1)})
                return
        yield sse({"type": "stage", "id": "retrieve", "label": "Searching the documents"})
        result = make_checklist(wrap_checklist_question(message), client=client, model=model, today=today)
        if result.declined:
            finish("checklist", started, used, 0, "declined")
            yield sse({"type": "final", "kind": "refusal", "answer": result.text,
                       "tokens": used, "seconds": round(time.time() - started, 1)})
            return
        yield sse({"type": "stage", "id": "retrieved", "label": f"Found {len(result.sources)} relevant passages"})
        seconds = finish("checklist", started, result.tokens + used, 0,
                         "ok" if result.checklist else "failed")
        yield sse({
            "type": "final", "kind": "checklist",
            "checklist": result.checklist.model_dump(mode="json") if result.checklist else None,
            "failed": result.checklist is None,
            "message": result.text if result.checklist is None else "",
            "sources": source_list(result.sources),
            "attempts": result.attempts, "repairs": result.errors,
            "tokens": result.tokens + used, "seconds": round(seconds, 1),
            "retrieval_mode": os.getenv("RETRIEVAL_MODE", "hybrid"),
        })

    return app


app = create_app()
