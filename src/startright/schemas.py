"""The shape of a StartRight checklist, enforced with Pydantic.

The model must return JSON that fits these classes. Anything that does not fit
(placeholders, bad numbering, malformed fees) is rejected and sent back for repair.
"""
import re
from decimal import Decimal

from pydantic import BaseModel, Field, field_validator, model_validator

# Text that means "the model did not know". Better to list it under not_covered.
PLACEHOLDER = re.compile(
    r"\?|\btbd\b|\bn/?a\b|\bsee (?:the )?(?:act|form|schedule)\b|to be confirmed|\.\.\.",
    re.I,
)


def _no_placeholder(value: str | None) -> str | None:
    if value is not None and PLACEHOLDER.search(value):
        raise ValueError(
            f"contains a placeholder ({value!r}); state a fact from the sources or "
            "list the gap under not_covered"
        )
    return value


class Fee(BaseModel):
    description: str = Field(min_length=3, max_length=120)
    amount: Decimal = Field(ge=0)
    currency: str = Field(pattern=r"^[A-Z]{3}$", description="ISO code, e.g. USD or ZWG")

    _check = field_validator("description")(_no_placeholder)


class ChecklistStep(BaseModel):
    order: int = Field(ge=1)
    action: str = Field(min_length=8, max_length=400)
    office: str | None = Field(default=None, max_length=120)
    fees: list[Fee] = Field(default_factory=list)
    deadline: str | None = Field(default=None, max_length=160)
    source_n: int = Field(ge=1, description="Number of the source that states this step")

    _check = field_validator("action", "office", "deadline")(_no_placeholder)


class BusinessChecklist(BaseModel):
    business: str = Field(min_length=3, max_length=160)
    steps: list[ChecklistStep] = Field(min_length=1, max_length=12)
    not_covered: list[str] = Field(
        default_factory=list,
        description="Things an owner needs that the given sources do not state",
    )

    @model_validator(mode="after")
    def steps_are_numbered_in_order(self):
        orders = [step.order for step in self.steps]
        if orders != list(range(1, len(orders) + 1)):
            raise ValueError(f"step orders must be 1, 2, 3... in sequence, got {orders}")
        return self
