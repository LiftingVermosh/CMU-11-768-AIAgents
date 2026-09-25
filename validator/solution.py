"""The validator you write. This is the only file you need to modify.

Each function evaluates a single run object and returns the errors it finds.
An empty list means that no errors were found. `validator/runner.py` defines
what a run object contains, and `ASSIGNMENT.md` defines the four error families you may report.
"""

from validator.model import complete  # noqa: F401
from validator.prediction import Error, ErrorFamily  # noqa: F401
from validator.runner import Run


def judge_execution(run: Run) -> list[Error]:
    """Whether the run produced a figure to judge at all."""
    raise NotImplementedError


def judge_data_and_chart(run: Run) -> list[Error]:
    """Whether the figure plots the requested data, built the requested way."""
    raise NotImplementedError


def judge_readability(run: Run) -> list[Error]:
    """Whether the figure can be read."""
    raise NotImplementedError


def validate(run: Run) -> list[Error]:
    """Everything wrong with one run."""
    raise NotImplementedError
