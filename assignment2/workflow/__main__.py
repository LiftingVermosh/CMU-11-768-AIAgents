"""Student workflow for authoring, running, evaluating, and checking work."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable

from . import evaluate, generate, package, submission, tasks

COMMANDS: dict[str, tuple[str, Callable[[list[str]], None]]] = {
    "validate-tasks": ("validate authored task descriptors", tasks.main),
    "generate": ("generate runs for authored tasks", generate.main),
    "package": ("scaffold harbor tasks from authored descriptors", package.main),
    "init-labels": ("create a blank human-label file", evaluate.init_labels_main),
    "validate-labels": ("validate labels and run coverage", evaluate.validate_labels_main),
    "score": ("score predictions against human labels", evaluate.score_main),
    "check-submission": ("validate the complete submission", submission.main),
}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, add_help=False)
    parser.add_argument("command", nargs="?")
    arguments, _ = parser.parse_known_args(sys.argv[1:2])
    if arguments.command in {None, "-h", "--help"}:
        print("usage: python -m workflow <command> [options]")
        print(f"\n{__doc__}\n")
        print("commands:")
        for command, (description, _) in COMMANDS.items():
            print(f"  {command:17} {description}")
        return
    if arguments.command not in COMMANDS:
        parser.error(f"unknown command: {arguments.command}")
    COMMANDS[arguments.command][1](sys.argv[2:])


if __name__ == "__main__":
    main()
