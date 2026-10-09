"""Print the first lines of each ZIMRA notice so you can read its date."""
from pathlib import Path

from pypdf import PdfReader

for path in sorted(Path("data/raw").glob("zimra_pn_*.pdf")):
    text = PdfReader(str(path)).pages[0].extract_text() or ""
    print("=" * 60)
    print(path.name)
    print(" ".join(text.split())[:350])
