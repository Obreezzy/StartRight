"""Tools the StartRight agent can choose from.

Each tool takes a dict of arguments and returns a JSON-friendly dict. Errors are
returned as {"error": ...} so the model can recover instead of the program crashing.
"""
from datetime import date
from decimal import Decimal, InvalidOperation

from startright.deadlines import days_until, due_date_next_month
from startright.fees import FeeItem, total_fees

MIN_SCORE = 0.25
MAX_CHARS_PER_SOURCE = 800  # keeps each search result cheap in tokens

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "search_regulations",
            "description": (
                "Search the ingested Zimbabwe laws, ZIMRA notices and licence forms. "
                "Use this for ANY question about what the law or an official notice "
                "requires, including rules, steps, fees, rates and due dates. Always "
                "write the query with full names instead of acronyms (for example "
                "'National Social Security Authority', not 'NSSA')."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "What to look up."}
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "calculate_fees",
            "description": (
                "Add up a list of fees exactly. Use this whenever you need a total. "
                "Only pass amounts that the user gave you or that came from search "
                "results. Never invent amounts."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "items": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "name": {"type": "string"},
                                "amount": {"type": "number"},
                                "currency": {"type": "string", "description": "e.g. USD"},
                            },
                            "required": ["name", "amount"],
                        },
                    }
                },
                "required": ["items"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "check_deadline",
            "description": (
                "Work out a due date that falls on a given day of the month AFTER a "
                "period ends (for example VAT returns for the period ended 30 June "
                "are due on the 10th of July), and how many days remain from today. "
                "Get the day of the month from a source first; do not guess it."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "period_end": {"type": "string", "description": "YYYY-MM-DD"},
                    "day_of_month": {"type": "integer", "description": "1 to 31"},
                },
                "required": ["period_end", "day_of_month"],
            },
        },
    },
]


def _fetch_hits(query: str, top_k: int = 4) -> list[dict]:
    """Search the database. Imported lazily so tests do not need a database."""
    from startright import store
    from startright.embeddings import embed_texts

    with store.connect() as conn:
        return store.search(conn, embed_texts([query])[0], top_k)


def search_regulations(args: dict) -> dict:
    query = str(args["query"]).strip()
    if not query:
        raise ValueError("query must not be empty")
    hits = [h for h in _fetch_hits(query) if h["score"] >= MIN_SCORE]
    if not hits:
        return {"results": [], "note": "No relevant sources found."}
    return {
        "results": [
            {
                "n": number,
                "title": hit["title"],
                "page": hit["page"],
                "source_type": hit["source_type"],
                "date": str(hit["doc_date"]) if hit["doc_date"] else "unknown",
                "score": round(float(hit["score"]), 2),
                "text": hit["content"][:MAX_CHARS_PER_SOURCE],
            }
            for number, hit in enumerate(hits, start=1)
        ]
    }


def calculate_fees(args: dict) -> dict:
    items = []
    for raw in args["items"]:
        try:
            amount = Decimal(str(raw["amount"]))
        except InvalidOperation:
            raise ValueError(f"Not a valid amount: {raw['amount']!r}")
        items.append(FeeItem(str(raw["name"]), amount, str(raw.get("currency", "USD"))))
    return {
        "total": str(total_fees(items)),
        "currency": items[0].currency if items else None,
        "items_counted": len(items),
    }


def check_deadline(args: dict, today: date) -> dict:
    period_end = date.fromisoformat(str(args["period_end"]))
    due = due_date_next_month(period_end, int(args["day_of_month"]))
    return {
        "due_date": due.isoformat(),
        "today": today.isoformat(),
        "days_until_due": days_until(due, today),
    }


def run_tool(name: str, args: dict, today: date) -> dict:
    try:
        if name == "search_regulations":
            return search_regulations(args)
        if name == "calculate_fees":
            return calculate_fees(args)
        if name == "check_deadline":
            return check_deadline(args, today)
        return {"error": f"Unknown tool: {name}"}
    except (KeyError, TypeError, ValueError) as exc:
        return {"error": f"{type(exc).__name__}: {exc}"}
