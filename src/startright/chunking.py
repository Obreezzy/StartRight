import unicodedata

SOFT_HYPHEN = "\u00ad"


def clean_text(text: str) -> str:
    """Repair PDF text-extraction artefacts before chunking.

    PDFs often store "fi", "ffi", "ff" and "fl" as single ligature characters, so
    "office" is saved as "o\ufb03ce" and a search for "office" never matches it. NFKC
    normalisation turns those back into plain letters. Also drops soft hyphens (invisible
    line-break hints) and NUL characters (which Postgres rejects).
    """
    text = unicodedata.normalize("NFKC", text)
    return text.replace(SOFT_HYPHEN, "").replace("\x00", "")


def chunk_text(text: str, max_chars: int = 1000, overlap: int = 150) -> list[str]:
    """Split text into overlapping chunks, preferring sentence/word boundaries."""
    if max_chars <= 0 or overlap < 0 or overlap >= max_chars:
        raise ValueError("Need max_chars > 0 and 0 <= overlap < max_chars")
    text = " ".join(text.split())
    if not text:
        return []
    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = min(start + max_chars, len(text))
        if end < len(text):
            cut = text.rfind(". ", start, end)
            if cut == -1 or cut <= start + max_chars // 2:
                cut = text.rfind(" ", start, end)
            if cut > start:
                end = cut + 1
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end >= len(text):
            break
        nxt = max(end - overlap, start + 1)
        space = text.find(" ", nxt, end)
        start = space + 1 if space != -1 else nxt
    return chunks
