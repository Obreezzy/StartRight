import json

import pytest

from startright.benchmark import (
    evaluate,
    format_report,
    format_validation,
    is_relevant,
    load_items,
)

ITEM = {"id": "q1", "question": "private company?", "expected_files": ["cobe.pdf"],
        "must_contain_any": ["private company"], "should_refuse": False, "tag": "entity-type"}
OFF = {"id": "q2", "question": "capital of France?", "expected_files": [],
       "must_contain_any": [], "should_refuse": True, "tag": "off-topic"}


def hit(file, text, score=0.6):
    return {"source_file": file, "content": text, "score": score}


def test_a_chunk_must_come_from_the_right_file_and_contain_the_phrase():
    assert is_relevant(hit("cobe.pdf", "Definition of Private Company means..."), ITEM)
    assert not is_relevant(hit("cobe.pdf", "private business corporation only"), ITEM)
    assert not is_relevant(hit("labour.pdf", "a private company"), ITEM)


def test_evaluate_scores_rank_and_hit_rate():
    wrong, right = hit("cobe.pdf", "pbc"), hit("cobe.pdf", "a private company")
    report = evaluate([ITEM], lambda q: [wrong, wrong, right], mode="m")
    assert report.ranks == {"q1": 3} and report.hit_rate == 1.0
    assert report.mrr == pytest.approx(1 / 3)


def test_a_relevant_chunk_below_the_cutoff_is_a_miss():
    wrong, right = hit("cobe.pdf", "pbc"), hit("cobe.pdf", "a private company")
    report = evaluate([ITEM], lambda q: [wrong] * 4 + [right], k=4)
    assert report.hit_rate == 0 and report.misses == ["q1"] and report.ranks == {"q1": 5}


def test_off_topic_questions_should_be_refused_and_good_ones_should_not():
    low = [hit("cobe.pdf", "x", score=0.1)]
    report = evaluate([ITEM, OFF], lambda q: low)
    assert report.correct_refusals == 1 and report.false_refusals == 1
    answered = evaluate([ITEM, OFF], lambda q: [hit("cobe.pdf", "a private company", 0.6)])
    assert answered.correct_refusals == 0 and answered.false_refusals == 0


def test_hybrid_style_improvement_shows_up_in_the_report():
    vector = evaluate([ITEM], lambda q: [hit("cobe.pdf", "pbc")] * 5, mode="vector")
    hybrid = evaluate([ITEM], lambda q: [hit("cobe.pdf", "a private company")], mode="hybrid")
    text = format_report({"vector": vector, "hybrid": hybrid})
    assert "vector" in text and "hybrid" in text and "entity-type" in text and "q1" in text
    assert hybrid.hit_rate > vector.hit_rate


def test_load_items_rejects_answerable_items_without_expectations(tmp_path):
    bad = [{"id": "x", "question": "q", "expected_files": [], "must_contain_any": [],
            "should_refuse": False, "tag": "t"}]
    path = tmp_path / "b.json"
    path.write_text(json.dumps(bad))
    with pytest.raises(ValueError):
        load_items(path)


def test_the_shipped_benchmark_file_is_well_formed():
    items = load_items("data/benchmark.json")
    assert 40 <= len(items) <= 60
    assert len({i["id"] for i in items}) == len(items)
    assert sum(i["should_refuse"] for i in items) >= 5


def test_validation_report_names_the_questions_with_no_matching_chunk():
    text = format_validation([
        {"id": "q1", "question": "ok?", "matching_chunks": 3},
        {"id": "q2", "question": "bad?", "matching_chunks": 0},
    ])
    assert "q2" in text and "q1" not in text.split("NO matching chunk")[1]
