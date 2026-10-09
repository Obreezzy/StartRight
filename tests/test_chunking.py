import pytest

from startright.chunking import chunk_text


def test_short_text_is_one_chunk():
    assert chunk_text("Register your company first.") == ["Register your company first."]


def test_empty_text_gives_no_chunks():
    assert chunk_text("   \n  ") == []


def test_chunks_never_exceed_max_chars():
    text = "This is a sentence about registration. " * 200
    assert all(len(c) <= 300 for c in chunk_text(text, max_chars=300, overlap=50))


def test_consecutive_chunks_overlap():
    chunks = chunk_text("word " * 500, max_chars=200, overlap=50)
    assert len(chunks) > 1
    assert chunks[1][:20] in chunks[0]


def test_first_and_last_words_are_kept():
    text = "Start " + "middle " * 300 + "End"
    chunks = chunk_text(text, max_chars=200, overlap=40)
    assert chunks[0].startswith("Start")
    assert chunks[-1].endswith("End")


def test_text_without_spaces_still_terminates():
    chunks = chunk_text("x" * 1000, max_chars=100, overlap=10)
    assert len(chunks) > 1
    assert all(len(c) <= 100 for c in chunks)


@pytest.mark.parametrize("max_chars,overlap", [(0, 0), (100, 100), (100, -1)])
def test_invalid_settings_raise(max_chars, overlap):
    with pytest.raises(ValueError):
        chunk_text("hello", max_chars=max_chars, overlap=overlap)
