"""Scaffold a Harbor task directory from an authored task descriptor.

    python -m workflow package [TASK_ID ...] [--force]

A Part 3 task is described once, in ``tasks/<task_id>/task.json``. Harbor wants
the same task expressed as a directory of its own. The two are not the same text
-- the Harbor task also has to state whatever its verifier checks, and it runs in
a container rather than the generation sandbox -- so this does not try to keep
them in sync. It copies ``harbor/template/`` and fills in the parts that are a
straight transcription of the descriptor, leaving the parts that are yours:
the verifier, the reference solution, and whatever extra outputs the verifier
needs the agent to leave behind.
"""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path

from .tasks import AuthoredTask, load_tasks

RELEASE = Path(__file__).resolve().parents[1]
TEMPLATE = RELEASE / "harbor" / "template"
DESTINATION = RELEASE / "harbor" / "tasks"

#: Where the Dockerfile's own comment says the COPY lines belong.
COPY_MARKER = "# TODO: copy in the input data your instruction.md tells the agent to read."

#: Everything below this line in the template's instruction.md is the part the
#: student has to decide, because it depends on what their verifier checks.
OUTPUTS_HEADING = "## Required outputs"


def _task_toml(template: str, task: AuthoredTask) -> str:
    """Fill the identity and metadata the descriptor already answers."""
    replacements = {
        'name = "cmu-11768/TODO-rename-me"': f'name = "cmu-11768/{task.task_id}"',
        'task_class = "TODO"': f'task_class = "{task.task_class}"',
        'source = "TODO: which Part 3 task / spec this came from"':
            f'source = "tasks/{task.task_id}/task.json"',
    }
    for old, new in replacements.items():
        if old not in template:
            raise SystemExit(
                f"harbor/template/task.toml no longer contains {old!r}; "
                "the template and this command have drifted apart"
            )
        template = template.replace(old, new)
    return template


def _instruction(template: str, task: AuthoredTask) -> str:
    """Seed the prompt, and keep the template's TODO block for the rest.

    The descriptor's ``instructions`` are what the three fixed agents were given,
    so they are reproduced verbatim: editing them after runs exist makes
    ``check-submission`` reject the runs, since it compares the recorded text
    against the descriptor. Anything the verifier additionally needs -- a
    re-runnable script, a sidecar -- belongs under the heading below, which is
    left as the template wrote it.
    """
    head, marker, tail = template.partition(OUTPUTS_HEADING)
    if not marker:
        raise SystemExit(
            f"harbor/template/instruction.md no longer contains {OUTPUTS_HEADING!r}; "
            "the template and this command have drifted apart"
        )
    seeded = (
        f"# {task.task_id}\n"
        "\n"
        "<!-- Copied from tasks/"
        f"{task.task_id}/task.json. This is the prompt the three fixed agents\n"
        "     were given, so do NOT reword it: check-submission holds both your runs\n"
        "     and this file to the descriptor's wording. Add what your verifier needs\n"
        "     under the heading below instead. -->\n"
        "\n"
        f"{task.instructions.strip()}\n"
        "\n"
    )
    return seeded + marker + tail


def _dockerfile(template: str, task: AuthoredTask) -> str:
    """Append one COPY per input at the template's own marker."""
    if not task.inputs:
        return template
    if COPY_MARKER not in template:
        raise SystemExit(
            f"harbor/template/environment/Dockerfile no longer contains {COPY_MARKER!r}; "
            "the template and this command have drifted apart"
        )
    copies = "\n".join(f"COPY {item.name} /app/{item.name}" for item in task.inputs)
    return template.replace(COPY_MARKER, f"{COPY_MARKER}\n{copies}")


def _shown(path: Path) -> str:
    """Release-relative where possible; never raise from an error message."""
    try:
        return str(path.relative_to(RELEASE))
    except ValueError:
        return str(path)


def package(task: AuthoredTask, descriptor: Path, *, force: bool) -> Path:
    target = DESTINATION / task.task_id
    if target.exists() and not force:
        raise SystemExit(
            f"{_shown(target)} already exists. Your verifier and reference "
            "solution live there, so this will not overwrite them; pass --force if you "
            "really mean to discard that directory and start again."
        )
    if target.exists():
        shutil.rmtree(target)
    shutil.copytree(TEMPLATE, target)

    for name, fill in (
        ("task.toml", _task_toml),
        ("instruction.md", _instruction),
        ("environment/Dockerfile", _dockerfile),
    ):
        path = target / name
        path.write_text(fill(path.read_text(), task))

    for item in task.inputs:
        shutil.copyfile(descriptor.parent / item.path, target / "environment" / item.name)

    return target


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="python -m workflow package", description=__doc__)
    parser.add_argument("task_id", nargs="*", help="which tasks to package; default all")
    parser.add_argument("--force", action="store_true",
                        help="replace an existing harbor/tasks/<task_id>, discarding its contents")
    arguments = parser.parse_args(argv)

    if not TEMPLATE.is_dir():
        parser.error(f"missing {_shown(TEMPLATE)}")

    try:
        authored = load_tasks(RELEASE / "tasks")
    except ValueError as problem:
        parser.error(f"{problem}; write task.json descriptors under tasks/ first")
    if arguments.task_id:
        wanted = set(arguments.task_id)
        known = {task.task_id for task, _ in authored}
        if missing := sorted(wanted - known):
            parser.error(f"no descriptor for {', '.join(missing)} under tasks/")
        authored = [pair for pair in authored if pair[0].task_id in wanted]

    DESTINATION.mkdir(parents=True, exist_ok=True)
    for task, descriptor in authored:
        target = package(task, descriptor, force=arguments.force)
        inputs = ", ".join(item.name for item in task.inputs) or "none"
        print(f"  {_shown(target)}  (task_class={task.task_class}, inputs: {inputs})")

    print(
        f"\nwrote {len(authored)} task(s). Still yours in each one:\n"
        "  instruction.md      the '## Required outputs' block -- above all the schema\n"
        "                      of plotted_values.json, which Part 3 requires\n"
        "  tests/test_state.py the checks themselves -- the sentinel keeps the task\n"
        "                      scoring 0 until you replace it\n"
        "  solution/solve.sh   a reference solution, so -a oracle can score 1.0\n"
        "Check one before spending a Docker cycle on it:\n"
        "  uv run python harbor/preflight.py harbor/tasks/<task_id>"
    )


if __name__ == "__main__":
    main()
