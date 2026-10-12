"""A small, repeatable retrieval benchmark. Zero API tokens: everything runs locally.

Each item says which document should answer the question and which words the answering
chunk must contain, so a retrieved chunk can be judged automatically. Off-topic items
should be refused. Two measures: Hit@k (is a relevant chunk in the top k?) and
MRR (how high is the first relevant chunk? 1/rank, averaged).
"""
import json
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from startright.retrieval import scope_matches, score_floor


def load_items(path: Path) -> list[dict]:
    items = json.loads(Path(path).read_text(encoding="utf-8"))
    for item in items:
        if not item["should_refuse"] and not (item["expected_files"] and item["must_contain_any"]):
            raise ValueError(f"{item['id']}: needs expected_files and must_contain_any")
    return items


def is_relevant(hit: dict, item: dict) -> bool:
    """A chunk is relevant if it comes from an expected file and contains a key phrase."""
    if not scope_matches(hit["source_file"], item["expected_files"]):
        return False
    text = hit["content"].lower()
    return any(phrase.lower() in text for phrase in item["must_contain_any"])


@dataclass
class ModeReport:
    mode: str
    answerable: int = 0
    hits_at_k: int = 0
    reciprocal_ranks: list[float] = field(default_factory=list)
    false_refusals: int = 0
    off_topic: int = 0
    correct_refusals: int = 0
    by_tag: dict[str, list[int]] = field(default_factory=lambda: defaultdict(lambda: [0, 0]))
    ranks: dict[str, int | None] = field(default_factory=dict)
    misses: list[str] = field(default_factory=list)

    @property
    def hit_rate(self) -> float:
        return self.hits_at_k / self.answerable if self.answerable else 0.0

    @property
    def mrr(self) -> float:
        return sum(self.reciprocal_ranks) / self.answerable if self.answerable else 0.0


def evaluate(items: list[dict], search_fn, mode: str = "", k: int = 4,
             min_score: float | None = None) -> ModeReport:
    """search_fn(question) must return ranked hits (best first), at least 10 deep."""
    if min_score is None:
        min_score = score_floor(mode or None)
    report = ModeReport(mode)
    for item in items:
        hits = search_fn(item["question"])
        refused = not hits or max(h["score"] for h in hits) < min_score
        if item["should_refuse"]:
            report.off_topic += 1
            report.correct_refusals += int(refused)
            continue
        report.answerable += 1
        report.false_refusals += int(refused)
        rank = next((i for i, h in enumerate(hits, start=1) if is_relevant(h, item)), None)
        report.ranks[item["id"]] = rank
        found = rank is not None and rank <= k
        report.hits_at_k += int(found)
        report.reciprocal_ranks.append(1.0 / rank if rank else 0.0)
        report.by_tag[item["tag"]][1] += 1
        report.by_tag[item["tag"]][0] += int(found)
        if not found:
            report.misses.append(item["id"])
    return report


def format_report(reports: dict[str, ModeReport], k: int = 4) -> str:
    modes = list(reports)
    lines = ["", f"{'mode':<15}{'Hit@' + str(k):>8}{'MRR@10':>9}{'refused ok':>12}{'false refusals':>16}"]
    for mode, r in reports.items():
        lines.append(
            f"{mode:<15}{r.hit_rate:>8.0%}{r.mrr:>9.2f}"
            f"{str(r.correct_refusals) + '/' + str(r.off_topic):>12}{r.false_refusals:>16}"
        )
    tags = sorted({tag for r in reports.values() for tag in r.by_tag})
    lines += ["", f"Hit@{k} by question type (hits/total):", f"{'type':<15}" + "".join(f"{m:>15}" for m in modes)]
    for tag in tags:
        cells = []
        for r in reports.values():
            hits, total = r.by_tag.get(tag, [0, 0])
            cells.append(f"{hits}/{total}")
        lines.append(f"{tag:<15}" + "".join(f"{c:>15}" for c in cells))
    lines += ["", "Questions with no relevant chunk in the top " + str(k) + ":"]
    for mode, r in reports.items():
        lines.append(f"  {mode}: {', '.join(r.misses) or 'none'}")
    return "\n".join(lines)


def validate_items(conn, items: list[dict]) -> list[dict]:
    """Check each answerable item against the database with plain keyword matching:
    how many chunks in the expected files contain a key phrase? Zero means the item
    is wrong (bad phrase or file), not that retrieval failed."""
    results = []
    for item in items:
        if item["should_refuse"]:
            continue
        files = item["expected_files"]
        row = conn.execute(
            """SELECT count(*) AS n FROM chunks
               WHERE source_file LIKE ANY(%s) AND content ILIKE ANY(%s)""",
            [files, [f"%{p}%" for p in item["must_contain_any"]]],
        ).fetchone()
        results.append({"id": item["id"], "question": item["question"], "matching_chunks": row["n"]})
    return results


def format_validation(results: list[dict]) -> str:
    bad = [r for r in results if r["matching_chunks"] == 0]
    lines = [f"Checked {len(results)} answerable questions against the database."]
    if not bad:
        lines.append("Every question has at least one chunk that could answer it.")
    else:
        lines.append(f"{len(bad)} question(s) have NO matching chunk. Fix their phrase or file in data/benchmark.json:")
        lines += [f"  {r['id']}: {r['question']}" for r in bad]
    return "\n".join(lines)
