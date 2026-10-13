"""Personal-data masking that needs no extra packages, so it also runs on the hosted site.

Everything a visitor types is passed through mask_personal_data BEFORE it is sent to a third-party
language model (Groq) or reranker (Cohere). Zimbabwean national ID numbers, mobile numbers and email
addresses are replaced with placeholders such as [ID number].

Limits: these are patterns, not understanding. Names, street addresses and unusual formats are not caught,
and the page tells visitors not to type personal details.
"""
from __future__ import annotations

import re


PERSONAL_DATA = [
    # Zimbabwe national ID: 2 digits, 6-7 digits, a check letter, 2 digits (63-123456 K 42)
    ("ID number", re.compile(r"(?<![\w-])\d{2}[\s-]?\d{6,7}[\s-]?[A-Za-z][\s-]?\d{2}(?![\w])")),
    # mobile numbers: 077 123 4567, 0771234567, +263 77 123 4567, 263771234567
    ("phone number", re.compile(r"(?<![\w+])(?:\+?263|0)[\s-]?7[1-9](?:[\s-]?\d){7}(?!\d)")),
    ("email address", re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")),
]


def mask_personal_data(text: str) -> tuple[str, list[str]]:
    """Replace personal identifiers with placeholders. Returns (masked text, kinds found)."""
    found: list[str] = []
    for label, pattern in PERSONAL_DATA:
        text, count = pattern.subn(f"[{label}]", text)
        if count:
            found.append(label)
    return text, found
