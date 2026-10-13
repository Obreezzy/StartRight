from startright import structured, tools


def _hit(content, page=1, score=0.9, title="Companies Act"):
    return {"title": title, "page": page, "content": content, "score": score,
            "source_type": "official", "doc_date": None}


def test_foreign_company_passages_are_skipped_for_a_local_business(monkeypatch):
    def fake(query, top_k=4, scope=None):
        return [_hit("A foreign company must lodge a notice naming its principal officer.", 170),
                _hit("A private company is registered by lodging a memorandum.", 22)]
    monkeypatch.setattr(tools, "_fetch_hits", fake)
    monkeypatch.setattr(structured.retrieval, "score_floor", lambda mode=None: 0.0)
    sources = structured.gather_sources("How can I start a private company in Harare")
    texts = " ".join(s["text"] for s in sources.values())
    assert "foreign company" not in texts and "memorandum" in texts


def test_foreign_passages_are_kept_when_the_question_asks_about_them(monkeypatch):
    monkeypatch.setattr(tools, "_fetch_hits", lambda q, top_k=4, scope=None:
                        [_hit("A foreign company must lodge a notice.", 170)])
    monkeypatch.setattr(structured.retrieval, "score_floor", lambda mode=None: 0.0)
    assert structured.gather_sources("I run a foreign company, how do I register a branch")


def test_duplicate_passages_from_the_two_queries_appear_once(monkeypatch):
    monkeypatch.setattr(tools, "_fetch_hits", lambda q, top_k=4, scope=None:
                        [_hit("Register the company with the Registrar.", 22)])
    monkeypatch.setattr(structured.retrieval, "score_floor", lambda mode=None: 0.0)
    sources = structured.gather_sources("register a company")
    assert len(sources) == 1  # the same passage found twice or under two domains is listed once


def test_employer_duties_are_searched_even_when_the_question_never_mentions_staff(monkeypatch):
    """'Hair salon in Harare' has no employment word, yet the checklist must still include
    the employer passages (this was the Week 11 small-shop bug)."""
    scopes_searched = []

    def fake(query, top_k=4, scope=None):
        scopes_searched.append(tuple(scope or ()))
        if scope and "labour_act.pdf" in scope:
            return [_hit("An employer must give each employee a written contract.", 12,
                         title="Labour Act")]
        return [_hit("Register the company with the Registrar.", 22)]

    monkeypatch.setattr(tools, "_fetch_hits", fake)
    monkeypatch.setattr(structured.retrieval, "score_floor", lambda mode=None: 0.0)
    sources = structured.gather_sources(
        structured.wrap_checklist_question("Hair salon in Harare"))
    assert any("labour_act.pdf" in scope for scope in scopes_searched)
    assert any(s["title"] == "Labour Act" for s in sources.values())


def test_employment_passages_are_capped_below_registration(monkeypatch):
    many = [_hit(f"Employer duty number {i}.", i, title="Labour Act") for i in range(10)]
    monkeypatch.setattr(tools, "_fetch_hits", lambda q, top_k=4, scope=None:
                        many if scope and "labour_act.pdf" in scope else [])
    monkeypatch.setattr(structured.retrieval, "score_floor", lambda mode=None: 0.0)
    sources = structured.gather_sources("I want to open a bakery")
    assert len(sources) == structured.PASSAGE_LIMIT["employment"]
    assert structured.PASSAGE_LIMIT["employment"] < structured.PASSAGE_LIMIT["registration"]
