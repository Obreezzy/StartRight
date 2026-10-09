from pathlib import Path

from pypdf import PdfReader


def read_pdf_pages(path: Path) -> list[tuple[int, str]]:
    """Return (page_number, text) for every page that has text."""
    reader = PdfReader(str(path))
    pages = []
    for number, page in enumerate(reader.pages, start=1):
        text = (page.extract_text() or "").replace("\x00", "")
        if text.strip():
            pages.append((number, text))
    return pages
