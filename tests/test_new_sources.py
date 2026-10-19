from startright import multiagent, structured


def _scope(agent):
    return multiagent.SPECIALISTS[agent].scope


def test_new_documents_are_in_the_right_specialist_scope():
    assert "income_tax_act.pdf" in _scope("tax")
    assert "zimra_new_businesses.pdf" in _scope("tax")
    assert "shop_licences_act.pdf" in _scope("registration")
    assert "harare_business_licensing.pdf" in _scope("registration")


def test_every_scope_entry_has_a_row_in_sources_csv():
    import csv
    from pathlib import Path

    files = {row["filename"] for row in csv.DictReader(Path("data/sources.csv").open(encoding="utf-8"))}
    for agent in ("registration", "tax", "employment"):
        for pattern in _scope(agent):
            if "%" in pattern:
                prefix = pattern.split("%")[0].replace("_", "")
                assert any(name.replace("_", "").startswith(prefix) for name in files), pattern
            else:
                assert pattern in files, f"{pattern} is searched but has no row in sources.csv"


def test_a_fee_cannot_come_from_a_guide():
    from types import SimpleNamespace as NS

    step = NS(order=1, action="Apply for a shop licence", source_n=1, deadline=None,
              fees=[NS(description="Licence fee", amount=50, currency="USD")])
    checklist = NS(steps=[step])
    sources = {1: {"title": "IBZIM guide", "page": 1, "source_type": "guide",
                   "date": "date unknown", "text": "The licence fee is 50 dollars."}}
    problems = structured.validate_against_sources(checklist, sources)
    assert any("official source" in p for p in problems)
