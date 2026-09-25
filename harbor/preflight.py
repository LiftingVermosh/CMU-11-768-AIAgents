#!/usr/bin/env python3
"""Check a harbor task directory before you spend a Docker cycle on it.

    python harbor/preflight.py <task-dir>

harbor reports almost every invalid task.toml as

    ValueError: Either datasets or tasks must be provided.

which reads as "I could not find a task", not "your task.toml is invalid":
Task.is_valid_dir() catches the pydantic ValidationError and returns False, so
the real reason never reaches you.  This prints what harbor swallowed, plus the
traps harbor does not check at all -- above all a verifier that cannot fail,
which scores an unfinished task a false 1.0.

The output names its mode.  "harbor + stdlib" means harbor's own validator ran
and is authoritative; "stdlib only" means harbor was not found and these are
structural checks, which catch the common mistakes but are not harbor.  Run this
with `uv run` and harbor is importable, so the first mode is the normal one; the
fallback exists for anyone invoking it with a bare system interpreter, and the
script will also find an interpreter that has harbor and re-run itself there.

Exit 0 if there are no errors (warnings alone are fine), 1 if there are.
"""

from __future__ import annotations

import ast
import os
import shutil
import subprocess
import sys
from pathlib import Path

try:
    import tomllib  # stdlib since Python 3.11
except ModuleNotFoundError:  # pragma: no cover - old interpreter
    sys.exit(f"preflight needs Python 3.11+ for tomllib; this is "
             f"{sys.version.split()[0]}.  Try:  uv run python {__file__} <task-dir>")

EXPECTED_FILES = ("task.toml", "instruction.md", "environment/Dockerfile",
                  "tests/test.sh", "tests/test_*.py", "solution/solve.sh")
SENTINEL = "HARBOR-TEMPLATE-SENTINEL"
REEXEC_GUARD = "HARBOR_PREFLIGHT_CHILD"

#: (level, where, message).  Continuation lines carry their own 4-space indent.
FINDINGS: list[tuple[str, str, str]] = []


def add(level: str, where: str, message: str) -> None:
    FINDINGS.append((level, where, message))


def read(path: Path) -> str:
    return path.read_text(errors="replace") if path.is_file() else ""


def as_list(value) -> list:
    """[] for absent, the value for a list, and a one-item list for anything else."""
    return [] if value is None else value if isinstance(value, list) else [value]


# --- structural checks: stdlib only, and they run in both modes ------------- #
def check_files(task_dir: Path) -> None:
    missing = [name for name in EXPECTED_FILES if not list(task_dir.glob(name))]
    if missing:
        add("ERROR", ", ".join(missing), "missing.  The six-file layout is:\n"
            f"    {', '.join(EXPECTED_FILES)}")
    for name in ("tests/test.sh", "solution/solve.sh"):
        path = task_dir / name
        if path.exists() and not os.access(path, os.X_OK):
            add("WARN", name, f"is not executable.  Run:  chmod +x {path}")


def check_toml(task_dir: Path) -> None:
    raw = read(task_dir / "task.toml")
    if not raw:
        return
    try:
        data = tomllib.loads(raw)
    except tomllib.TOMLDecodeError as exc:
        add("ERROR", "task.toml", f"is not valid TOML: {exc}\n"
            "    Nothing else can be checked until it parses.")
        return

    task = data.get("task")
    if not isinstance(task, dict):
        add("WARN", "task.toml", "has no [task] table, so harbor falls back to the\n"
            '    directory name.  Add one, with  name = "org/task-name".')
        task = {}
    elif not isinstance(task.get("name"), str) or task["name"].count("/") != 1:
        add("ERROR", "task.toml [task].name", f"is {task.get('name')!r}; it must be\n"
            '    "org/name" with exactly one slash, e.g. "cmu-11768/viz-my-task".')

    # TRAP 1: `authors = ["me"]` is valid TOML and invalid harbor.
    for index, entry in enumerate(as_list(task.get("authors"))):
        if isinstance(entry, dict) and entry.get("name"):
            continue
        add("ERROR", f"task.toml [task].authors[{index}]",
            f"is {entry!r}; authors are TABLES, not strings.\n"
            "    Delete the  authors = [...]  line and write instead:\n\n"
            "        [[task.authors]]\n"
            f'        name = "{entry if isinstance(entry, str) else "your name"}"\n\n'
            '    This is the most common cause of "Either datasets or tasks must be\n'
            '    provided": that message means task.toml failed validation.')

    # TRAP 2: [verifier].collect holds shell commands, not filenames.
    verifier = data.get("verifier")
    collect = verifier.get("collect") if isinstance(verifier, dict) else None
    for index, entry in enumerate(as_list(collect)):
        if isinstance(entry, dict) and entry.get("command"):
            continue
        add("ERROR", f"task.toml [verifier].collect[{index}]",
            f"is {entry!r}; collect holds SHELL COMMANDS, not files.\n"
            "    To pull a file out of the container, use the root-level list:\n\n"
            '        artifacts = ["/app/figure.png"]\n\n'
            "    To really run a command after the agent phase:\n\n"
            "        [[verifier.collect]]\n"
            '        command = "some shell command"')

    if "TODO" in raw:
        add("WARN", "task.toml",
            "still contains TODO markers -- fill in the template fields.")


def check_text_files(task_dir: Path) -> None:
    """instruction.md, test.sh, solve.sh: one cheap grep each."""
    instruction = read(task_dir / "instruction.md")
    if (task_dir / "instruction.md").is_file() and not instruction.strip():
        add("ERROR", "instruction.md",
            "is empty.  This file is the entire task as the agent sees it.")
    elif "TODO" in instruction:
        add("WARN", "instruction.md",
            "still contains TODO markers -- your verifier can only check what is\n"
            "    stated here.")

    # uvx/pip must not supply the interpreter: that one has no matplotlib.
    body = "\n".join(line for line in read(task_dir / "tests" / "test.sh").splitlines()
                     if not line.lstrip().startswith("#"))
    if any(token in body for token in ("uvx ", "uv run", "pip install")):
        add("WARN", "tests/test.sh", "runs the tests through uvx / uv run / pip.\n"
            "    That is an ephemeral interpreter with no matplotlib, numpy or Pillow,\n"
            "    and there is no network at grade time.  Name the image interpreter:\n\n"
            "        /usr/local/bin/python3 -m pytest /tests/test_state.py")

    if SENTINEL in read(task_dir / "solution" / "solve.sh"):
        add("WARN", "solution/solve.sh",
            "is still the unedited template and exits non-zero on purpose.\n"
            "    The oracle scores 0 until you write the reference solution here.")


def check_python_tests(task_dir: Path) -> None:
    """The check that matters: a verifier that cannot fail scores a false 1.0."""
    for test_file in sorted((task_dir / "tests").glob("test_*.py")):
        rel, text = f"tests/{test_file.name}", read(test_file)
        try:
            tree = ast.parse(text)
        except SyntaxError as exc:
            add("ERROR", rel, f"does not parse: {exc}\n    pytest cannot collect it.")
            continue
        can_fail = any(isinstance(node, (ast.Assert, ast.Raise))
                       for node in ast.walk(tree)) or "pytest.fail" in text
        if not can_fail:
            add("WARN", rel,
                "has no assert, no raise and no pytest.fail: it CANNOT FAIL.\n"
                "    Every submission then scores 1.0, including an empty one, so the\n"
                "    task tells you that you are done when you are not.  This is what\n"
                "    `harbor init` scaffolds; start from template/tests/test_state.py,\n"
                "    which fails closed.")
        if SENTINEL in text:
            add("WARN", rel, "still contains the template sentinel, so this scores 0.\n"
                "    Expected while you work -- the sentinel is what stops an unfinished\n"
                "    task scoring a false 1.0.  Delete that last test once your own\n"
                "    content checks are in.")


# --- harbor's own validator ------------------------------------------------- #
def run_harbor(task_dir: Path) -> str | None:
    """Surface the errors harbor swallows.  None if harbor is not importable here."""
    # Real symbols, not `import harbor`: this directory is itself named harbor/,
    # so a bare import of that name resolves to an empty namespace package.
    try:
        from importlib.metadata import version
        from harbor.models.task.config import TaskConfig
        from harbor.models.task.task import Task
    except Exception:
        return None

    config = task_dir / "task.toml"
    if config.is_file():
        try:
            TaskConfig.model_validate_toml(config.read_text())
        except Exception as exc:  # pydantic ValidationError, TOMLDecodeError, ...
            errors = getattr(exc, "errors", None)
            items = errors() if callable(errors) else []
            for item in items:
                loc = ".".join(str(part) for part in item.get("loc", ())) or "(root)"
                got = f" (got {item['input']!r})" if "input" in item else ""
                add("ERROR", f"task.toml {loc}",
                    f"harbor's validator says: {item.get('msg', 'invalid')}{got}")
            if not items:
                add("ERROR", "task.toml", f"harbor rejected it: {exc}")

    if not Task.is_valid_dir(task_dir):
        add("ERROR", "task directory",
            "harbor's Task.is_valid_dir() says this is NOT a task directory.\n"
            '    `harbor run -p <dir>` reports that as "Either datasets or tasks must\n'
            '    be provided."  The real reason is in the errors above.')
    try:
        return version("harbor")
    except Exception:
        return "version unknown"


def harbor_python() -> str | None:
    """An interpreter that has harbor, for when the current one does not.  The
    probe imports a submodule: a bare `import harbor` would succeed from the
    student directory, where harbor/ is this very (harbor-free) folder."""
    binary = shutil.which("harbor")
    for candidate in (os.environ.get("HARBOR_PREFLIGHT_PYTHON"),
                      binary and str(Path(os.path.realpath(binary)).parent / "python3"),
                      str(Path.home() / ".local/share/uv/tools/harbor/bin/python3")):
        if (candidate and Path(candidate).is_file()
                and os.access(candidate, os.X_OK)
                and subprocess.run([candidate, "-c", "import harbor.models.task.task"],
                                   capture_output=True).returncode == 0):
            return candidate
    return None


def main(argv: list[str]) -> int:
    if len(argv) != 1 or argv[0].startswith("-"):
        print(__doc__, file=sys.stderr)
        return 2
    task_dir = Path(argv[0]).expanduser().resolve()
    if not task_dir.is_dir():
        print(f"preflight: {task_dir} is not a directory", file=sys.stderr)
        return 2

    for check in (check_files, check_toml, check_text_files, check_python_tests):
        check(task_dir)
    installed = run_harbor(task_dir)

    if installed is None and not os.environ.get(REEXEC_GUARD):
        interpreter = harbor_python()
        if interpreter:
            print(f"preflight: harbor is not importable from {sys.executable};\n"
                  f"           re-running under {interpreter}\n", flush=True)
            return subprocess.run([interpreter, os.path.abspath(__file__), *argv],
                                  env={**os.environ, REEXEC_GUARD: "1"}).returncode

    mode = (f"harbor + stdlib  (harbor {installed}, imported by\n"
            f"           {sys.executable})" if installed else
            f"stdlib only  (harbor is NOT importable from\n           {sys.executable}\n"
            "           and no interpreter with harbor was found, so harbor's own\n"
            "           validator did not run.  These checks catch the common\n"
            "           mistakes but they are not authoritative.)")
    print(f"preflight: {task_dir}\nmode:      {mode}\n")

    for number, (level, where, message) in enumerate(
            sorted(FINDINGS, key=lambda finding: finding[0] != "ERROR"), start=1):
        print(f"{number}. [{level}] {where}\n    {message}\n")

    errors = sum(1 for finding in FINDINGS if finding[0] == "ERROR")
    if not FINDINGS:
        print("OK: no problems found.")
    elif errors:
        print(f"{errors} error(s), {len(FINDINGS) - errors} warning(s).  Fix the errors:\n"
              'left alone they surface as "Either datasets or tasks must be provided",\n'
              "or as a failed trial.")
    else:
        print(f"{len(FINDINGS)} warning(s), no errors: harbor will accept this directory.")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
