from startright.rag import build_context
from startright.store import to_vector_literal


def test_build_context_numbers_sources_and_includes_titles():
    hits = [
        {"title": "Act A", "page": 3, "source_type": "official",
         "doc_date": "2019-11-15", "content": "Text one"},
        {"title": "Guide B", "page": 1, "source_type": "guide",
         "doc_date": None, "content": "Text two"},
    ]
    context = build_context(hits)
    assert "[1] Act A" in context and "[2] Guide B" in context
    assert "date unknown" in context


def test_vector_literal_format():
    assert to_vector_literal([0.1, 0.2]) == "[0.1,0.2]"
