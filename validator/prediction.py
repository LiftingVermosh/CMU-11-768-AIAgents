"""The shape of the file a validator writes, and the four families it reports in.

Every error belongs to exactly one family, chosen by where the evidence for it is
found: the trajectory, the numbers a figure records, the structure it records, or
the rendered image. ASSIGNMENT.md defines each family and the rules for choosing
between them.
"""

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class ErrorFamily(StrEnum):
    EXECUTION_FAILURE = "execution_failure"
    WRONG_DATA = "wrong_data"
    WRONG_CHART = "wrong_chart"
    HARD_TO_READ = "hard_to_read"


class Error(BaseModel):
    model_config = ConfigDict(extra="forbid")

    family: ErrorFamily
    evidence: str = Field(min_length=1)


class Prediction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: str = Field(min_length=1)
    errors: list[Error]


class PredictionFile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    predictions: list[Prediction]


ERROR_FAMILIES: tuple[str, ...] = tuple(family.value for family in ErrorFamily)

#: Terminal. A run labelled with this one is graded on it alone, because a figure
#: that does not exist reveals nothing about the other three.
TERMINAL_FAMILY: str = ErrorFamily.EXECUTION_FAILURE.value
