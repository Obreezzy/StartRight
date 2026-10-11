from startright.chunking import chunk_text, clean_text


def test_ligatures_become_plain_letters():
    assert clean_text("registered o\ufb03ce") == "registered office"
    assert clean_text("De\ufb01nition of an o\ufb00ence") == "Definition of an offence"
    assert clean_text("\ufb02at \ufb01nancial") == "flat financial"


def test_soft_hyphens_and_nul_characters_are_removed():
    assert clean_text("regis\u00adtered") == "registered"
    assert clean_text("a\x00b") == "ab"


def test_ordinary_text_and_curly_apostrophes_are_left_alone():
    text = "the officer\u2019s address, Section 248 (1)(a)"
    assert clean_text(text) == text


def test_a_cleaned_chunk_can_be_found_by_a_plain_search():
    chunk = chunk_text(clean_text("The registered o\ufb03ce and De\ufb01nition of terms."))[0]
    assert "registered office" in chunk.lower() and "definition of terms" in chunk.lower()
