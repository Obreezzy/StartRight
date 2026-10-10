import pytest
from pydantic import ValidationError

from startright.schemas import BusinessChecklist, ChecklistStep, Fee


def step(order=1, **kwargs):
    base = {"order": order, "action": "Reserve the company name", "source_n": 1}
    return {**base, **kwargs}


def checklist(*steps, **kwargs):
    return {"business": "Hair salon", "steps": list(steps), **kwargs}


def test_a_valid_checklist_parses_and_keeps_decimals_exact():
    parsed = BusinessChecklist.model_validate(checklist(
        step(fees=[{"description": "Filing", "amount": 25.5, "currency": "USD"}])
    ))
    assert str(parsed.steps[0].fees[0].amount) == "25.5"
    assert parsed.not_covered == []


@pytest.mark.parametrize("bad_action", [
    "Fill in Form ? from the Registrar",
    "Pay the fee, TBD at the office",
    "Submit the documents (see Act for details)",
    "Wait for the certificate...",
])
def test_placeholders_are_rejected(bad_action):
    with pytest.raises(ValidationError):
        BusinessChecklist.model_validate(checklist(step(action=bad_action)))


def test_steps_must_be_numbered_in_sequence():
    with pytest.raises(ValidationError) as error:
        BusinessChecklist.model_validate(checklist(step(1), step(3)))
    assert "sequence" in str(error.value)


@pytest.mark.parametrize("fee", [
    {"description": "Filing", "amount": -5, "currency": "USD"},
    {"description": "Filing", "amount": 5, "currency": "dollars"},
    {"description": "Filing", "amount": "lots", "currency": "USD"},
])
def test_bad_fees_are_rejected(fee):
    with pytest.raises(ValidationError):
        BusinessChecklist.model_validate(checklist(step(fees=[fee])))


def test_a_step_must_name_its_source():
    with pytest.raises(ValidationError):
        ChecklistStep.model_validate({"order": 1, "action": "Reserve the company name"})


def test_a_checklist_needs_at_least_one_step():
    with pytest.raises(ValidationError):
        BusinessChecklist.model_validate(checklist())


def test_fee_model_is_usable_directly():
    assert Fee(description="Name search", amount=50, currency="USD").amount == 50
