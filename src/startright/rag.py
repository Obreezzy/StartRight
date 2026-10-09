import os

from startright import store
from startright.embeddings import embed_texts

MIN_SCORE = 0.25  # a starting guess; tune it against your test questions

SYSTEM_PROMPT = (
    "You are StartRight, an assistant that helps people in Zimbabwe understand "
    "business registration, tax and compliance. Answer ONLY from the numbered "
    "sources provided. If the sources do not contain the answer, say you do not "
    "have enough information and recommend confirming with the relevant official "
    "office. Cite sources like [1], [2]. Never invent fees, dates, form numbers "
    "or section numbers. This is general information, not legal advice."
)


def build_context(hits: list[dict]) -> str:
    blocks = []
    for number, hit in enumerate(hits, start=1):
        date = hit["doc_date"] or "date unknown"
        blocks.append(
            f"[{number}] {hit['title']} (page {hit['page']}, "
            f"{hit['source_type']}, {date})\n{hit['content']}"
        )
    return "\n\n".join(blocks)


def answer(question: str, top_k: int = 4) -> tuple[str, list[dict], int]:
    """Return (answer_text, sources_used, tokens_used)."""
    with store.connect() as conn:
        hits = store.search(conn, embed_texts([question])[0], top_k)
    hits = [h for h in hits if h["score"] >= MIN_SCORE]
    if not hits:
        # No call to Groq at all, so no tokens are spent.
        return (
            "I don't have enough information in my sources to answer that. "
            "Please confirm with the relevant official office.",
            [],
            0,
        )

    from groq import Groq

    client = Groq()  # reads GROQ_API_KEY from the environment
    model = os.environ["GROQ_MODEL"]
    # gpt-oss models think before answering, and thinking tokens count against
    # the limit, so keep the effort low and leave room for the answer.
    extra = {"reasoning_effort": "low"} if "gpt-oss" in model else {}
    response = client.chat.completions.create(
        model=model,
        temperature=0.1,
        max_completion_tokens=1000,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": f"Sources:\n{build_context(hits)}\n\nQuestion: {question}",
            },
        ],
        **extra,
    )
    tokens = response.usage.total_tokens if response.usage else 0
    text = response.choices[0].message.content or (
        "The model returned an empty answer. Try again, or raise max_completion_tokens."
    )
    return text, hits, tokens