import argparse
import csv
from pathlib import Path

from dotenv import load_dotenv

from startright import store
from startright.chunking import chunk_text
from startright.embeddings import embed_texts
from startright.loaders import read_pdf_pages
from startright.rag import answer

RAW_DIR = Path("data/raw")
SOURCES_CSV = Path("data/sources.csv")


def ingest() -> None:
    with SOURCES_CSV.open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    with store.connect() as conn:
        store.ensure_schema(conn)
        for row in rows:
            path = RAW_DIR / row["filename"]
            if not path.exists():
                print(f"SKIP (file not found): {path}")
                continue
            pages = read_pdf_pages(path)
            if not pages:
                print(f"SKIP (no text; maybe a scanned PDF): {path}")
                continue
            records = [
                (page, index, chunk)
                for page, text in pages
                for index, chunk in enumerate(chunk_text(text))
            ]
            vectors = embed_texts([content for _, _, content in records])
            store.replace_document(conn, row, records, vectors)
            print(f"OK {row['filename']}: {len(pages)} pages, {len(records)} chunks")


def ask(question: str) -> None:
    text, hits, tokens = answer(question)
    print("\n" + text + "\n")
    for number, hit in enumerate(hits, start=1):
        print(f"[{number}] {hit['title']} (page {hit['page']}, score {hit['score']:.2f})")
    print(f"\nTokens used: {tokens}")


def agent(question: str) -> None:
    from startright.agent import run_agent

    result = run_agent(question)
    print("\nAgent steps:")
    if not result.steps:
        print("  (no tools called)")
    for number, step in enumerate(result.steps, start=1):
        outcome = "error" if "error" in step.result else "ok"
        print(f"  {number}. {step.tool}({step.arguments}) -> {outcome}")
    print("\n" + result.answer + "\n")
    print(f"Tokens used: {result.tokens}")


def team(question: str) -> None:
    from startright.multiagent import SPECIALISTS, run_team

    result = run_team(question)
    print(f"\nPlan ({result.plan_source}):")
    if not result.subtasks:
        print("  (declined: not a business registration, tax or compliance question)")
    for item in result.subtasks:
        print(f"  - {item['agent']}: {item['task']}")
    for finding in result.findings:
        title = SPECIALISTS[finding["agent"]].title
        print(f"\n{title} specialist steps:")
        if not finding["steps"]:
            print("  (no tools called)")
        for number, step in enumerate(finding["steps"], start=1):
            outcome = "error" if "error" in step.result else "ok"
            print(f"  {number}. {step.tool}({step.arguments}) -> {outcome}")
    if result.revisions:
        print(f"\nVerifier asked for {result.revisions} revision(s).")
    print("\n" + result.answer + "\n")
    print(f"Tokens used: {result.tokens}")


def checklist(question: str, as_json: bool) -> None:
    from startright.structured import make_checklist

    result = make_checklist(question)
    if as_json and result.checklist:
        print(result.checklist.model_dump_json(indent=2))
    else:
        print("\n" + result.text)
    if result.errors:
        print(f"\nRepairs needed: {len(result.errors)} (the model was shown these problems)")
        for number, problems in enumerate(result.errors, start=1):
            print(f"  attempt {number}: " + "; ".join(problems))
    print(f"\nAttempts: {result.attempts}   Tokens used: {result.tokens}")


def benchmark(validate_only: bool, modes: list[str], save: str) -> None:
    import json

    from startright import benchmark as bench
    from startright import retrieval

    items = bench.load_items(Path("data/benchmark.json"))
    with store.connect() as conn:
        if validate_only:
            print(bench.format_validation(bench.validate_items(conn, items)))
            return
        reports = {}
        for mode in modes:
            print(f"running {mode}...")
            reports[mode] = bench.evaluate(
                items,
                lambda question, m=mode: retrieval.search(question, top_k=10, mode=m, conn=conn),
                mode=mode,
            )
    print(bench.format_report(reports))
    if any("cohere" in m for m in modes):
        used, fell_back = retrieval.COHERE_STATS["cohere"], retrieval.COHERE_STATS["fallback"]
        print(f"\nCohere Rerank calls: {used} worked, {fell_back} fell back to the un-reranked order.")
        if fell_back:
            print("Some results are NOT reranked (key missing, quota or rate limit). Set "
                  "COHERE_MIN_INTERVAL=7 and rerun before quoting these numbers.")
    Path(save).write_text(
        json.dumps({m: r.ranks for m, r in reports.items()}, indent=2), encoding="utf-8"
    )
    print(f"\nPer-question ranks saved to {save}")


def copydb() -> None:
    import os

    import psycopg
    from psycopg.rows import dict_row

    target_url = os.environ.get("TARGET_DATABASE_URL")
    if not target_url:
        raise SystemExit("Set TARGET_DATABASE_URL to the hosted database's connection string first.")
    from urllib.parse import urlparse

    source_url = store.database_url()
    source_host, target_host = urlparse(source_url).hostname, urlparse(target_url).hostname
    print(f"Copying FROM host {source_host} TO host {target_host}")
    if source_url == target_url or source_host == target_host:
        raise SystemExit(
            "The source and the target are the same database, so copying would empty it.\n"
            "The app reads DATABASE_URL when it is set. Clear it in this terminal with\n"
            "  Remove-Item Env:DATABASE_URL\n"
            "and check Windows environment variables, so the source is your local database (127.0.0.1)."
        )
    with store.connect() as source, psycopg.connect(
        target_url, row_factory=dict_row, prepare_threshold=None
    ) as target:
        have = source.execute("SELECT count(*) AS n FROM chunks").fetchone()["n"]
        if have == 0:
            raise SystemExit("The source database has 0 chunks, so there is nothing to copy. "
                             "Run: python -m startright.cli ingest")
        count = store.copy_chunks(source, target)
    print(f"Copied {count} chunks to the hosted database.")


def main() -> None:
    load_dotenv()
    parser = argparse.ArgumentParser(prog="startright")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("ingest")
    ask_parser = sub.add_parser("ask")
    ask_parser.add_argument("question")
    agent_parser = sub.add_parser("agent")
    agent_parser.add_argument("question")
    team_parser = sub.add_parser("team")
    team_parser.add_argument("question")
    checklist_parser = sub.add_parser("checklist")
    checklist_parser.add_argument("question")
    checklist_parser.add_argument("--json", action="store_true")
    bench_parser = sub.add_parser("benchmark")
    bench_parser.add_argument("--validate", action="store_true",
                              help="only check the benchmark file against the database")
    bench_parser.add_argument("--modes", default="vector,bm25,hybrid,hybrid_rerank")
    bench_parser.add_argument("--save", default="data/benchmark_results.json")
    sub.add_parser("copydb", help="copy all chunks to the database in TARGET_DATABASE_URL")
    args = parser.parse_args()
    if args.command == "ingest":
        ingest()
    elif args.command == "ask":
        ask(args.question)
    elif args.command == "agent":
        agent(args.question)
    elif args.command == "team":
        team(args.question)
    elif args.command == "checklist":
        checklist(args.question, args.json)
    elif args.command == "copydb":
        copydb()
    else:
        benchmark(args.validate, args.modes.split(","), args.save)


if __name__ == "__main__":
    main()
