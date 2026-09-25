"""Load and validate self-authored visualization task descriptors.

Each task is a directory containing ``task.json`` and, optionally, files below
that directory. Paths in the descriptor are always relative to the task
directory; absolute paths and ``..`` traversal are rejected.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, model_validator

TASK_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


class TaskInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=255)
    path: str = Field(min_length=1)

    @model_validator(mode="after")
    def safe_names(self) -> "TaskInput":
        if Path(self.name).name != self.name or self.name in {".", ".."}:
            raise ValueError("input name must be a plain filename")
        if self.name in {"figure.png", "solution.py", "task.json"}:
            raise ValueError(
                f"input name {self.name!r} is reserved by the generation runner"
            )
        path = Path(self.path)
        if path.is_absolute() or ".." in path.parts:
            raise ValueError("input path must be relative and may not contain '..'")
        return self


class AuthoredTask(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task_id: str = Field(min_length=1, max_length=64)
    task_class: str = Field(min_length=1, max_length=100)
    instructions: str = Field(min_length=1)
    inputs: list[TaskInput] = Field(default_factory=list)

    @model_validator(mode="after")
    def valid_descriptor(self) -> "AuthoredTask":
        if not TASK_ID.fullmatch(self.task_id):
            raise ValueError(
                "task_id may contain only letters, digits, '.', '_', and '-'"
            )
        if not self.task_class.strip() or not self.instructions.strip():
            raise ValueError("task_class and instructions may not be blank")
        names = [item.name for item in self.inputs]
        if len(names) != len(set(names)):
            raise ValueError("input names must be unique within a task")
        return self

    @classmethod
    def load(cls, descriptor: Path) -> "AuthoredTask":
        task = cls.model_validate_json(descriptor.read_text())
        if descriptor.parent.name != task.task_id:
            raise ValueError(
                f"{descriptor}: directory name must equal task_id {task.task_id!r}"
            )
        root = descriptor.parent.resolve()
        for item in task.inputs:
            candidate = (descriptor.parent / item.path).resolve()
            if not candidate.is_relative_to(root):
                raise ValueError(f"{descriptor}: input escapes task directory: {item.path}")
            if not candidate.is_file():
                raise ValueError(f"{descriptor}: input does not exist: {item.path}")
        return task


def load_tasks(root: Path) -> list[tuple[AuthoredTask, Path]]:
    descriptors = sorted(root.glob("*/task.json"))
    if not descriptors:
        raise ValueError(f"no task descriptors found below {root}")
    loaded = [(AuthoredTask.load(path), path) for path in descriptors]
    ids = [task.task_id for task, _ in loaded]
    if len(ids) != len(set(ids)):
        raise ValueError("task_id values must be unique")
    return loaded


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tasks", type=Path, default=Path("tasks"))
    arguments = parser.parse_args(argv)
    try:
        loaded = load_tasks(arguments.tasks)
    except (OSError, ValueError) as error:
        parser.error(str(error))
    print(f"valid: {len(loaded)} task descriptor(s)")
