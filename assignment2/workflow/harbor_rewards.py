"""Run the packaged harbor tasks and hold their rewards to Part 3's contract.

Reading a task directory says whether harbor will accept it. Only harbor says what
it scores, and Part 3 requires two scores: every packaged task 1.0 against its own
reference solution, and the mutant 0.0. This gets both by running harbor -- once
over ``harbor/tasks/`` as a dataset, so the oracles run concurrently, then once per
mutant over a scratch copy with the mutant swapped over ``solution/solve.sh`` --
and reads the reward out of each trial's ``result.json``.

It needs Docker, and it is the slow half of ``check-submission``:
``--skip-harbor-runs`` checks the structure alone, which is what you want while
you are still iterating on labels or the report.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

#: Written under <root>/jobs/, which is where `harbor run` puts results anyway.
ORACLE_JOB = "check-submission-oracle"
MUTANT_JOB = "check-submission-mutant"


@dataclass(frozen=True)
class Trial:
    """One harbor trial, reduced to what the contract is about."""

    task: Path
    reward: float | None
    log: Path
    exception: str | None

    def describe(self) -> str:
        if self.exception:
            return f"errored ({self.exception})"
        return "produced no reward at all" if self.reward is None else f"scored {self.reward}"


def _harbor() -> str:
    """The harbor beside the running interpreter, so `uv run` picks its own."""
    beside = Path(sys.executable).parent / "harbor"
    return str(beside) if beside.is_file() else (shutil.which("harbor") or "harbor")


def _tail(text: str, lines: int = 15) -> str:
    kept = [line for line in (text or "").splitlines() if line.strip()][-lines:]
    return "\n".join(f"    {line}" for line in kept) or "    (no output)"


def _run(dataset: Path, jobs: Path, job_name: str) -> list[Trial]:
    """One harbor job over every task directory under ``dataset``."""
    shutil.rmtree(jobs / job_name, ignore_errors=True)
    command = [_harbor(), "run", "-p", str(dataset), "-a", "oracle",
               "-o", str(jobs), "--job-name", job_name, "-q", "-y"]
    try:
        finished = subprocess.run(command, capture_output=True, text=True)
    except OSError as problem:
        raise ValueError(
            f"could not start harbor ({problem}). Run this as `uv run python -m workflow "
            "check-submission`, or pass --skip-harbor-runs to check the structure only."
        ) from None

    trials = [_trial(path) for path in sorted((jobs / job_name).glob("*/result.json"))]
    if not trials:
        raise ValueError(
            f"harbor ran no trials for {dataset} (exit {finished.returncode}). Docker has "
            "to be running, and every task directory has to be one harbor accepts -- "
            "`uv run python harbor/preflight.py <task-dir>` says which. harbor said:\n"
            + _tail(finished.stderr or finished.stdout)
        )
    return trials


def _trial(result: Path) -> Trial:
    record = json.loads(result.read_text())
    failure = record.get("exception_info") or {}
    return Trial(
        task=Path(record["task_id"]["path"]).resolve(),
        reward=((record.get("verifier_result") or {}).get("rewards") or {}).get("reward"),
        log=result.parent / "verifier" / "pytest.log",
        exception=failure.get("exception_message") or failure.get("exception_type") or None,
    )


def _shown(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def verify_rewards(root: Path, task_ids: set[str]) -> list[str]:
    """Raise unless every oracle scores 1.0, one mutant scores 0 and one scores 1.0.

    Returns the reward of every trial it ran, as lines worth printing: the report
    has to quote these numbers, and re-running harbor to recover them costs the
    minutes the student has just spent.
    """
    packaged = root / "harbor" / "tasks"
    jobs = root / "jobs"
    summary: list[str] = []

    oracles = {trial.task: trial for trial in _run(packaged, jobs, ORACLE_JOB)}
    unrun = sorted(task for task in task_ids if (packaged / task).resolve() not in oracles)
    if unrun:
        raise ValueError(
            f"harbor ran no trial for {', '.join(unrun)}, so it does not accept those task "
            "directories. The layout check passed, which leaves task.toml: `uv run python "
            "harbor/preflight.py harbor/tasks/<task_id>` prints the validation error harbor "
            "itself swallows."
        )
    for task in sorted(task_ids):
        trial = oracles[(packaged / task).resolve()]
        summary.append(f"  {task:<28} oracle  {trial.reward}")
        if trial.reward != 1.0:
            raise ValueError(
                f"harbor/tasks/{task}: the oracle {trial.describe()}, and Part 3 requires "
                "1.0. A task whose own reference solution fails its own verifier is broken "
                "rather than packaged -- either solve.sh does not produce what "
                "instruction.md promises, or a check asserts something the task never asked "
                f"for. The assertion that failed is in {_shown(trial.log, root)}"
            )

    rejected, accepted, mutant_lines = None, None, []
    for mutant in sorted(packaged.glob("*/mutants/*/solve.sh")):
        task_directory, name = mutant.parents[2], mutant.parent.name
        trial = _swap_and_run(task_directory, mutant, jobs, name)
        verdict = {0.0: "rejected", 1.0: "accepted"}.get(trial.reward, "neither 0 nor 1")
        mutant_lines.append(
            f"  {task_directory.name:<28} mutant  {trial.reward}  ({name}, {verdict})"
        )
        rejected = rejected or (name if trial.reward == 0.0 else None)
        accepted = accepted or (name if trial.reward == 1.0 else None)
        if rejected and accepted:
            break   # both halves of the contract are proved; any further mutants are
                    # the student's own exploring, and each one costs a container.
    summary += mutant_lines
    if rejected is None:
        raise ValueError(
            "no mutant scored 0, so nothing here shows your verifier asserts anything "
            "about content -- an agent that plots the wrong numbers passes it too:\n"
            + "\n".join(mutant_lines)
            + "\nPart 3 requires one mutant your checks reject. The cheapest one to catch "
            "is a wrong number: assert the totals you derived by hand against "
            f"plotted_values.json. {_shown(jobs, root)}/{MUTANT_JOB}-*/*/verifier/"
            "pytest.log shows which checks ran."
        )
    if accepted is None:
        raise ValueError(
            "every mutant scored 0, so none of them found where your verifier stops:\n"
            + "\n".join(mutant_lines)
            + "\nPart 3 also requires one mutant it accepts -- a wrong answer no assertion "
            "over files and numbers can see. Legibility is the usual one: correct totals, "
            "correct ordering, 2pt type on a small canvas. harbor/example/mutants/illegible/ "
            "is a worked version, and it scores 1.0 against the strongest verifier here."
        )
    return summary


def _swap_and_run(task_directory: Path, mutant: Path, jobs: Path, name: str) -> Trial:
    """Run one mutant in place of the reference solution, in a scratch copy.

    The copy is what keeps the submitted task intact: the mutant has to arrive as
    ``solution/solve.sh`` for ``-a oracle`` to run it, and swapping it in place
    would destroy the very file the oracle check just passed.
    """
    with tempfile.TemporaryDirectory(prefix="hw2-mutant-") as scratch:
        copy = Path(scratch) / task_directory.name
        shutil.copytree(task_directory, copy)
        shutil.rmtree(copy / "mutants", ignore_errors=True)
        shutil.copyfile(mutant, copy / "solution" / "solve.sh")
        (copy / "solution" / "solve.sh").chmod(0o755)
        trials = _run(Path(scratch), jobs, f"{MUTANT_JOB}-{task_directory.name}-{name}")
    return trials[0]
