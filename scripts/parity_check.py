"""Environment parity check: ask the same questions of two copies of StartRight and compare.

    python scripts/parity_check.py http://127.0.0.1:8002 https://your-app.onrender.com --out docs/parity-report.md
    python scripts/parity_check.py LOCAL_URL STAGING_URL --code YOUR_ACCESS_CODE

It uses only the standard library. It checks that both sites are healthy, run the same model,
answer the same questions with the same kind of result, and cite the same source documents. The
answer wording can differ between runs (the model is not deterministic), so wording is not compared.

Both sites count these questions against the hourly limit (default 15 per visitor), so run it
sparingly. The first call to a sleeping free Render service can take about a minute.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

QUESTIONS = [
    ("answer", "What does the Labour Act say about maternity leave?"),
    ("answer", "What do I need to register a private company?"),
    ("checklist", "Hair salon in Harare"),
]


def call(url: str, data: dict | None = None, code: str = "", timeout: int = 150):
    headers = {"Content-Type": "application/json"}
    if code:
        headers["X-Access-Code"] = code
    body = json.dumps(data).encode() if data is not None else None
    request = urllib.request.Request(url, data=body, headers=headers)
    return urllib.request.urlopen(request, timeout=timeout)


def get_json(url: str, code: str = "", timeout: int = 150) -> dict:
    with call(url, None, code, timeout) as response:
        return json.loads(response.read().decode())


def ask(base: str, mode: str, message: str, code: str) -> dict:
    """Return the last (final) event of one streamed answer, plus timing and any error."""
    started = time.time()
    try:
        with call(f"{base}/api/chat", {"message": message, "mode": mode}, code) as response:
            events = [json.loads(line[5:]) for line in response.read().decode().splitlines()
                      if line.startswith("data:")]
    except urllib.error.HTTPError as exc:
        return {"error": f"HTTP {exc.code}", "seconds": round(time.time() - started, 1)}
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        return {"error": str(exc)[:80], "seconds": round(time.time() - started, 1)}
    final = events[-1] if events else {}
    if final.get("type") == "error":
        return {"error": final.get("message", "error")[:80], "seconds": round(time.time() - started, 1)}
    sources = sorted({f"{s['title']} p{s['page']}" for s in final.get("sources", [])})
    return {"kind": final.get("kind"), "tokens": final.get("tokens"), "sources": sources,
            "seconds": round(time.time() - started, 1)}


def check_site(base: str, code: str) -> dict:
    base = base.rstrip("/")
    site = {"base": base, "health": "FAILED", "model": "?", "mode": "?", "results": []}
    try:
        site["health"] = get_json(f"{base}/api/health", code).get("status", "?")
        info = get_json(f"{base}/api/info", code)
        site["model"], site["mode"] = info.get("model"), info.get("retrieval_mode")
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
        site["error"] = str(exc)[:100]
        return site
    for mode, message in QUESTIONS:
        site["results"].append({"mode": mode, "question": message, **ask(base, mode, message, code)})
    return site


def compare(local: dict, staging: dict) -> list[tuple[str, bool, str]]:
    checks = [
        ("both sites are healthy", local["health"] == staging["health"] == "ok",
         f"{local['health']} / {staging['health']}"),
        ("same model", local["model"] == staging["model"], f"{local['model']} / {staging['model']}"),
    ]
    for a, b in zip(local["results"], staging["results"]):
        label = f"{a['mode']}: {a['question'][:40]}"
        if "error" in a or "error" in b:
            checks.append((f"{label} answered on both", False, f"{a.get('error', 'ok')} / {b.get('error', 'ok')}"))
            continue
        checks.append((f"{label}: same kind of result", a["kind"] == b["kind"], f"{a['kind']} / {b['kind']}"))
        shared = set(a["sources"]) & set(b["sources"])
        checks.append((f"{label}: cites at least one common source", bool(shared), ", ".join(sorted(shared)) or "none"))
    return checks


def report(local: dict, staging: dict, checks: list) -> str:
    lines = ["# Environment parity report", "",
             f"Run at {datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC.", "",
             "| | Local | Staging |", "|---|---|---|",
             f"| URL | {local['base']} | {staging['base']} |",
             f"| Health | {local['health']} | {staging['health']} |",
             f"| Model | {local['model']} | {staging['model']} |",
             f"| Search mode | {local['mode']} | {staging['mode']} |", "",
             "## Same questions on both", "",
             "| Question | Mode | Local (kind, tokens, seconds) | Staging (kind, tokens, seconds) |", "|---|---|---|---|"]
    for a, b in zip(local["results"], staging["results"]):
        def cell(r):
            return r["error"] if "error" in r else f"{r['kind']}, {r['tokens']}, {r['seconds']}s"
        lines.append(f"| {a['question']} | {a['mode']} | {cell(a)} | {cell(b)} |")
    lines += ["", "## Checks", "", "| Check | Result | Detail |", "|---|---|---|"]
    lines += [f"| {name} | {'PASS' if ok else 'FAIL'} | {detail} |" for name, ok, detail in checks]
    lines += ["", "Expected differences: the search mode may differ (the hosted site runs the model-free "
              "`bm25_light` mode to fit 512 MB of memory), and answer wording varies between runs."]
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("local")
    parser.add_argument("staging")
    parser.add_argument("--code", default="", help="access code, if the sites require one")
    parser.add_argument("--out", help="write the report to this Markdown file")
    args = parser.parse_args()
    print("Checking local site...", flush=True)
    local = check_site(args.local, args.code)
    print("Checking staging site (a sleeping free service can take a minute)...", flush=True)
    staging = check_site(args.staging, args.code)
    for site in (local, staging):
        if "error" in site:
            print(f"Cannot reach {site['base']}: {site['error']}")
            return 2
    checks = compare(local, staging)
    text = report(local, staging, checks)
    print(text)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as handle:
            handle.write(text)
        print(f"Saved {args.out}")
    return 0 if all(ok for _, ok, _ in checks) else 1


if __name__ == "__main__":
    sys.exit(main())
