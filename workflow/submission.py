"""Validate a complete Assignment 2 submission before upload."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

from .generate import AGENTS, _valid_png
from .evaluate import load_labels, score
from .harbor_rewards import verify_rewards
from .tasks import AuthoredTask, load_tasks
from validator.runner import Run

RELEASE = Path(__file__).resolve().parents[1]

#: The layout harbor needs, as glob patterns, the same six as harbor/preflight.py.
HARBOR_REQUIRED_FILES = (
    "task.toml",
    "instruction.md",
    "environment/Dockerfile",
    "solution/solve.sh",
    "tests/test.sh",
    "tests/test_*.py",
)

#: Both halves of harbor/template/ carry this marker, and deleting it is the last
#: step of writing a task. While it survives, the task scores 0 by construction.
TEMPLATE_SENTINEL = "HARBOR-TEMPLATE-SENTINEL"

#: ASSIGNMENT.md, Part 3: every packaged task has to ask for these two, because a
#: deterministic verifier cannot read plotted numbers back off a PNG.
HARBOR_REQUIRED_OUTPUTS = ("plot.py", "plotted_values.json")


def _harbor_problems(directory: Path, task: AuthoredTask) -> list[str]:
    """Everything wrong with one packaged task, gathered in a single pass.

    ``harbor/preflight.py`` reports these same signals as warnings, because an
    unfinished verifier is the expected state while you are still writing a task.
    At submission time it is not, so here they are errors -- and they are
    collected rather than raised one at a time, since a student who has just
    scaffolded five tasks has the same problem five times over.
    """
    problems: list[str] = []

    if missing := [name for name in HARBOR_REQUIRED_FILES if not list(directory.glob(name))]:
        problems.append(
            f"missing {', '.join(missing)}; harbor needs the whole harbor/template/ "
            f"layout -- re-scaffold with `uv run python -m workflow package "
            f"{task.task_id} --force`"
        )

    unwritten = sorted(
        path.relative_to(directory).as_posix()
        for path in [*directory.glob("tests/test_*.py"), directory / "solution" / "solve.sh"]
        if path.is_file() and TEMPLATE_SENTINEL in path.read_text(errors="replace")
    )
    if unwritten:
        problems.append(
            f"{', '.join(unwritten)} still "
            f"{'carries' if len(unwritten) == 1 else 'carry'} the {TEMPLATE_SENTINEL} "
            "marker, so this task scores 0 whatever an agent does; write the checks and "
            "the reference solution, then delete the marker"
        )

    instruction = directory / "instruction.md"
    if instruction.is_file():
        stated = instruction.read_text(errors="replace")
        if "TODO" in stated:
            problems.append(
                f"instruction.md still holds {stated.count('TODO')} TODO marker(s) from "
                "harbor/template/, and this file is the whole task as the agent sees it"
            )
        if task.instructions.strip() not in stated:
            problems.append(
                f"instruction.md no longer states the prompt in tasks/{task.task_id}/"
                "task.json verbatim; a packaged task may add requirements to that prompt "
                "but may not reword it, or your runs no longer describe the task"
            )
        if absent := [name for name in HARBOR_REQUIRED_OUTPUTS if name not in stated]:
            problems.append(
                f"instruction.md never asks the agent for {', '.join(absent)}; "
                "ASSIGNMENT.md, Part 3 requires both from every packaged task"
            )
    return problems


def validate_harbor_packaging(root: Path, tasks: dict[str, AuthoredTask]) -> None:
    """One finished harbor task per authored task, plus the two mutants.

    Structural only: it never runs harbor and never starts Docker, so it cannot
    tell you the oracle scores 1.0 -- only that nothing here stops it. Confirming
    the reward is still `harbor run -p harbor/tasks/<task_id> -a oracle`.
    """
    packaged_root = root / "harbor" / "tasks"
    packaged = {
        path.name: path
        for path in packaged_root.iterdir()
        if path.is_dir() and not path.name.startswith(".")
    }
    if unpackaged := sorted(set(tasks) - set(packaged)):
        raise ValueError(
            f"harbor/tasks/ holds nothing for {', '.join(unpackaged)}; every authored "
            "task has to be packaged -- `uv run python -m workflow package` does them all"
        )
    if stray := sorted(set(packaged) - set(tasks)):
        raise ValueError(
            f"harbor/tasks/ holds {', '.join(stray)}, which no tasks/<task_id>/task.json "
            "describes; delete the leftover, or restore the descriptor it came from"
        )
    faults = [
        f"  harbor/tasks/{task_id}: {problem}"
        for task_id, directory in sorted(packaged.items())
        for problem in _harbor_problems(directory, tasks[task_id])
    ]
    if faults:
        raise ValueError(
            "packaged harbor tasks are unfinished:\n"
            + "\n".join(faults)
            + "\n`uv run python harbor/preflight.py harbor/tasks/<task_id>` reports the "
            "same things per task, with the fix for each."
        )
    mutants = [path for path in packaged_root.glob("*/mutants/*/solve.sh") if path.is_file()]
    if len(mutants) < 2:
        raise ValueError(
            f"found {len(mutants)} mutant(s) under harbor/tasks/<task_id>/mutants/<name>/"
            "solve.sh; ASSIGNMENT.md, Part 3 asks for two plausible-but-wrong solutions -- "
            "one your verifier rejects and one it accepts -- and check-submission runs both"
        )


def validate_submission(root: Path, *, run_harbor: bool = True) -> list[str]:
    """Everything a submission has to satisfy. Returns the harbor rewards it read.

    The cheap checks run first and the harbor runs last, so a malformed labels.json
    is reported in a second rather than after several minutes of Docker.
    """
    required = (
        root / "validator" / "solution.py",
        root / "output",
        root / "output" / "authored_predictions.json",
        root / "tasks",
        root / "runs",
        root / "labels.json",
        root / "harbor" / "tasks",
        root / "report.pdf",
        root / "report.tex",
        root / "AI_USAGE.md",
    )
    missing = [str(path.relative_to(root)) for path in required if not path.exists()]
    if missing:
        raise ValueError(f"missing required submission paths: {', '.join(missing)}")

    tasks = load_tasks(root / "tasks")
    if len(tasks) < 5:
        raise ValueError(f"at least five authored tasks are required; found {len(tasks)}")
    task_ids = {task.task_id for task, _ in tasks}
    tasks_by_id = {task.task_id: (task, descriptor) for task, descriptor in tasks}
    class_counts = Counter(task.task_class for task, _ in tasks)
    if len(class_counts) < 2 or any(count < 2 for count in class_counts.values()):
        raise ValueError(
            "authored tasks must cover at least two task_class values with at least "
            f"two tasks in each; found {dict(class_counts)}"
        )
    validate_harbor_packaging(root, {task.task_id: task for task, _ in tasks})
    expected_agents = {agent.key for agent in AGENTS}
    pairs: list[tuple[str, str]] = []
    artifact_ids: set[str] = set()
    agent_models = {agent.key: agent.model for agent in AGENTS}
    for result_path in sorted((root / "runs").glob("*/result.json")):
        record = json.loads(result_path.read_text())
        if result_path.parent.name != record.get("run_id"):
            raise ValueError(f"{result_path}: directory name and run_id differ")
        pair = (record.get("task_id"), (record.get("agent") or {}).get("key"))
        if (record.get("agent") or {}).get("model") != agent_models.get(pair[1]):
            raise ValueError(
                f"{result_path}: agent key/model is not one of the fixed agents"
            )
        pairs.append(pair)
        artifact_ids.add(record["run_id"])
        if record["run_id"] != f"{pair[0]}__{pair[1]}":
            raise ValueError(f"{result_path}: run_id must be <task_id>__<agent>")
        if pair[0] not in tasks_by_id:
            raise ValueError(f"{result_path}: unknown authored task {pair[0]!r}")
        source_task, source_descriptor = tasks_by_id[pair[0]]
        recorded_task = record.get("task") or {}
        if (
            recorded_task.get("instructions") != source_task.instructions
            or recorded_task.get("task_class") != source_task.task_class
        ):
            raise ValueError(f"{result_path}: recorded task does not match its descriptor")
        run = Run.load(result_path.parent, root)
        if set(run.inputs) != {item.name for item in source_task.inputs}:
            raise ValueError(f"{result_path}: recorded inputs do not match its descriptor")
        for item in source_task.inputs:
            source_input = source_descriptor.parent / item.path
            if run.inputs[item.name].read_bytes() != source_input.read_bytes():
                raise ValueError(f"{result_path}: copied input differs from {item.path}")
    duplicates = [pair for pair, count in Counter(pairs).items() if count > 1]
    if duplicates:
        raise ValueError(f"duplicate task/agent runs: {duplicates}")
    expected_pairs = {
        (task_id, agent) for task_id in task_ids for agent in expected_agents
    }
    actual_pairs = set(pairs)
    if actual_pairs != expected_pairs:
        raise ValueError(
            f"authored runs incomplete; missing={sorted(expected_pairs - actual_pairs)}, "
            f"extra={sorted(actual_pairs - expected_pairs)}"
        )
    labels = load_labels(root / "labels.json", root / "runs")
    if {label.run_id for label in labels} != artifact_ids:
        raise ValueError("labels do not cover every generated run exactly once")
    by_id = {label.run_id: label for label in labels}
    for run_id in artifact_ids:
        figure = root / "runs" / run_id / "figure.png"
        execution_failed = by_id[run_id].values["execution_failure"]
        if not execution_failed and not _valid_png(figure):
            raise ValueError(f"{run_id}: completed-run label requires a valid figure.png")
    score(root / "labels.json", root / "output" / "authored_predictions.json")
    return verify_rewards(root, task_ids) if run_harbor else []


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=RELEASE)
    parser.add_argument(
        "--skip-harbor-runs", action="store_true",
        help="check the harbor packaging structurally and stop there: no Docker, and "
             "no oracle or mutant rewards. For iterating; not for the run before you "
             "upload, which has to prove both rewards.",
    )
    arguments = parser.parse_args(argv)
    try:
        rewards = validate_submission(
            arguments.root.resolve(), run_harbor=not arguments.skip_harbor_runs
        )
    except (OSError, ValueError) as error:
        parser.error(str(error))
    if rewards:
        print("harbor rewards:\n" + "\n".join(rewards))
    print("submission valid"
          + (" -- structure only, harbor runs skipped" if arguments.skip_harbor_runs else ""))
