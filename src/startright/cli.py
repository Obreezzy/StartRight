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


def main() -> None:
    load_dotenv()
    parser = argparse.ArgumentParser(prog="startright")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("ingest")
    ask_parser = sub.add_parser("ask")
    ask_parser.add_argument("question")
    agent_parser = sub.add_parser("agent")
    agent_parser.add_argument("question")
    args = parser.parse_args()
    if args.command == "ingest":
        ingest()
    elif args.command == "ask":
        ask(args.question)
    else:
        agent(args.question)


if __name__ == "__main__":
    main()
