from datetime import date

import pytest

from startright.checklist import Step, build_checklist


def make_step(order, source="Companies and Other Business Entities Act"):
    return Step(order, f"Step {order}", "Registrar", source, date(2024, 1, 1))


def test_checklist_is_sorted_by_order():
    result = build_checklist([make_step(3), make_step(1), make_step(2)])
    assert [step.order for step in result] == [1, 2, 3]


def test_checklist_rejects_empty_list():
    with pytest.raises(ValueError):
        build_checklist([])


def test_checklist_rejects_step_without_source():
    with pytest.raises(ValueError):
        build_checklist([make_step(1, source="")])