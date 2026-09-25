"""Run authored tasks through the original pinned mini-SWE-agent scaffold."""

from __future__ import annotations

import argparse
import json
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import modal
from PIL import Image
from tqdm import tqdm

from .tasks import AuthoredTask, load_tasks

RELEASE = Path(__file__).resolve().parents[1]
RUNNER_APP = "hw2-agent-runner"
RUNNER_FUNCTION = "run_task"


@dataclass(frozen=True)
class Agent:
    key: str
    model: str
    url_variable: str


AGENTS: tuple[Agent, ...] = (
    Agent(
        "qwen",
        "Qwen/Qwen2.5-Coder-3B-Instruct",
        "GENERATION_QWEN_BASE_URL",
    ),
    Agent(
        "ministral",
        "mistralai/Ministral-3-14B-Instruct-2512",
        "GENERATION_MINISTRAL_BASE_URL",
    ),
    Agent("glm", "zai-org/GLM-4.7-Flash", "GENERATION_GLM_BASE_URL"),
)
AGENT_BY_KEY = {agent.key: agent for agent in AGENTS}


def _valid_png(path: Path) -> bool:
    try:
        with Image.open(path) as image:
            is_png = image.format == "PNG"
            image.verify()
        return is_png
    except (OSError, SyntaxError):
        return False


def _json_safe(value: Any) -> Any:
    if isinstance(value, bytes):
        return {"byte_count": len(value)}
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return repr(value)


def build_request(
    task: AuthoredTask, descriptor: Path, agent: Agent
) -> dict[str, Any]:
    task_record = {
        "task_id": task.task_id,
        "task_class": task.task_class,
        "instructions": task.instructions,
        "inputs": [item.model_dump() for item in task.inputs],
        "expected_output": {"path": "figure.png", "format": "png"},
    }
    input_files = {
        item.name: (descriptor.parent / item.path).read_bytes()
        for item in task.inputs
    }
    return {"task": task_record, "model": agent.model, "input_files": input_files}


def write_result(
    task: AuthoredTask,
    descriptor: Path,
    agent: Agent,
    artifacts: Path,
    result: dict[str, Any],
    *,
    force: bool,
) -> Path:
    run_id = f"{task.task_id}__{agent.key}"
    destination = artifacts / run_id
    if destination.exists() and not force:
        raise FileExistsError(f"{destination} already exists")

    artifacts.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{run_id}-", dir=artifacts))
    try:
        artifact_inputs = staging / "inputs"
        artifact_inputs.mkdir()
        input_records = []
        for item in task.inputs:
            shutil.copy2(descriptor.parent / item.path, artifact_inputs / item.name)
            final_input = destination / "inputs" / item.name
            input_records.append(
                {
                    "name": item.name,
                    "path": str(final_input.relative_to(artifacts.parent)),
                }
            )

        artifact_bytes = result.get("artifact_bytes")
        if artifact_bytes is not None:
            (staging / "figure.png").write_bytes(artifact_bytes)
        record = {
            "run_id": run_id,
            "task_id": task.task_id,
            "agent": {"key": agent.key, "model": agent.model},
            "scaffold": result.get("scaffold"),
            "outcome": _json_safe(result.get("outcome")),
            "task": {
                "task_class": task.task_class,
                "instructions": task.instructions,
                "inputs": input_records,
            },
            "trajectory": _json_safe(result.get("trajectory")),
            "artifact_present": result.get("artifact_present", False),
            "artifact_error": result.get("artifact_error"),
            "elapsed_seconds": result.get("elapsed_seconds"),
        }
        (staging / "result.json").write_text(json.dumps(record, indent=2) + "\n")
        if destination.exists():
            shutil.rmtree(destination)
        staging.rename(destination)
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    return destination


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tasks", type=Path, default=RELEASE / "tasks")
    parser.add_argument(
        "--artifacts", type=Path, default=RELEASE / "runs"
    )
    parser.add_argument(
        "--models",
        nargs="+",
        choices=tuple(AGENT_BY_KEY),
        default=list(AGENT_BY_KEY),
    )
    parser.add_argument(
        "--force", action="store_true", help="replace completed task/model runs"
    )
    arguments = parser.parse_args(argv)
    try:
        tasks = load_tasks(arguments.tasks)
    except (OSError, ValueError) as error:
        parser.error(str(error))

    remote = modal.Function.from_name(RUNNER_APP, RUNNER_FUNCTION)
    failures = 0
    jobs = [
        (task, descriptor, AGENT_BY_KEY[key])
        for task, descriptor in tasks
        for key in arguments.models
    ]
    progress = tqdm(jobs, unit="run")
    for task, descriptor, agent in progress:
        progress.set_description(
            f"generating {task.task_id} / {agent.key}", refresh=True
        )
        destination = arguments.artifacts / f"{task.task_id}__{agent.key}"
        if destination.exists() and not arguments.force:
            progress.write(f"skip {destination} (already exists)")
            continue
        try:
            result = remote.remote(build_request(task, descriptor, agent))
            written = write_result(
                task,
                descriptor,
                agent,
                arguments.artifacts,
                result,
                force=arguments.force,
            )
            progress.write(f"wrote {written}")
        except Exception as error:
            failures += 1
            progress.write(f"ERROR {task.task_id} / {agent.key}: {error}")
    if failures:
        raise SystemExit(f"{failures} run(s) failed remotely; rerun to resume")
