from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class Step:
    order: int
    title: str
    office: str
    source: str
    source_date: date


def build_checklist(steps: list[Step]) -> list[Step]:
    """Return steps in order. Every step must cite a source."""
    if not steps:
        raise ValueError("A checklist needs at least one step")
    if any(not step.source for step in steps):
        raise ValueError("Every step must cite a source")
    return sorted(steps, key=lambda step: step.order)