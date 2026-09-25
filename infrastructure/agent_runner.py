"""Run the pinned mini-SWE-agent scaffold in a fresh Modal container."""

from __future__ import annotations

import json
import os
import tempfile
import time
from pathlib import Path
from typing import Any

import modal

MINI_SWE_AGENT_VERSION = "2.4.5"
APP_NAME = "hw2-agent-runner"
FUNCTION_NAME = "run_task"
GATEWAY_APP = "hw2-generation-gateway"
GATEWAY_FUNCTION = "complete"
COMMAND_TIMEOUT_SECONDS = 120
STEP_LIMIT = 20
WALL_TIME_LIMIT_SECONDS = 15 * 60
MODEL_MAX_TOKENS = 4096

app = modal.App(APP_NAME)
image = (
    modal.Image.debian_slim(python_version="3.12")
    .apt_install("git")
    .uv_pip_install(
        f"mini-swe-agent=={MINI_SWE_AGENT_VERSION}",
        "matplotlib==3.10.5",
        "numpy==2.3.2",
        "pandas==2.3.1",
        "pillow==11.3.0",
        "scipy==1.16.1",
        "seaborn==0.13.2",
    )
)


def _task_prompt(task: dict[str, Any]) -> str:
    expected = task["expected_output"]
    inputs = [item["name"] for item in task.get("inputs", [])]
    return (
        f"TASK ID: {task['task_id']}\n\n"
        f"USER REQUEST:\n{task['instructions']}\n\n"
        f"INPUT FILES: {json.dumps(inputs)}\n"
        f"REQUIRED OUTPUT: create {expected['path']} in the workspace "
        f"as a valid {expected['format']} file.\n"
        "Do not merely describe code: run it and leave the artifact at that "
        "exact path."
    )


def _within_workspace(workspace: Path, relative: str) -> Path:
    candidate = (workspace / relative).resolve()
    if Path(relative).is_absolute() or not candidate.is_relative_to(
        workspace.resolve()
    ):
        raise ValueError(f"unsafe task path: {relative!r}")
    return candidate


@app.function(image=image, timeout=20 * 60, max_containers=20)
def run_task(request: dict[str, Any]) -> dict[str, Any]:
    from litellm import ModelResponse
    from minisweagent.agents.default import DefaultAgent
    from minisweagent.config import get_config_from_spec
    from minisweagent.environments.local import LocalEnvironment, _run
    from minisweagent.models.litellm_model import LitellmModel
    from minisweagent.models.utils.actions_toolcall import BASH_TOOL

    task = request["task"]
    model_name = request["model"]
    started = time.monotonic()

    class GatewayModel(LitellmModel):
        def _query(self, messages: list[dict[str, Any]], **kwargs: Any):
            gateway = modal.Function.from_name(GATEWAY_APP, GATEWAY_FUNCTION)
            generation: dict[str, Any] = {
                "temperature": 0.0,
                "max_tokens": MODEL_MAX_TOKENS,
            }
            if self.config.model_name.startswith("Qwen/Qwen2.5-Coder-"):
                generation["tool_choice"] = "required"
            raw = gateway.remote(
                {
                    "model": self.config.model_name,
                    "messages": messages,
                    "tools": [BASH_TOOL],
                    "generation": generation,
                }
            )
            return ModelResponse(**raw)

        def _calculate_cost(self, response):
            return {"cost": 0.0}

    class CredentialScrubbedEnvironment(LocalEnvironment):
        """Keep infrastructure credentials out of model-written processes."""

        def execute(
            self,
            action: dict[str, Any],
            cwd: str = "",
            *,
            timeout: int | None = None,
        ):
            command = action.get("command", "")
            cwd = cwd or self.config.cwd or os.getcwd()
            child_env = {
                key: value
                for key, value in (os.environ | self.config.env).items()
                if not any(marker in key for marker in ("TOKEN", "SECRET", "API_KEY"))
            }
            try:
                result = _run(command, cwd, child_env, timeout or self.config.timeout)
                output = {
                    "output": result.stdout,
                    "returncode": result.returncode,
                    "exception_info": "",
                }
            except Exception as error:
                raw_output = getattr(error, "output", None)
                if isinstance(raw_output, bytes):
                    raw_output = raw_output.decode("utf-8", errors="replace")
                output = {
                    "output": raw_output or "",
                    "returncode": -1,
                    "exception_info": (
                        f"An error occurred while executing the command: {error}"
                    ),
                    "extra": {
                        "exception_type": type(error).__name__,
                        "exception": str(error),
                    },
                }
            self._check_finished(output)
            return output

    with tempfile.TemporaryDirectory(prefix="agent-eval-") as raw_workspace:
        workspace = Path(raw_workspace)
        (workspace / "task.json").write_text(json.dumps(task, indent=2) + "\n")
        for name, content in request.get("input_files", {}).items():
            target = _within_workspace(workspace, name)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)

        os.environ.update({"MPLBACKEND": "Agg", "PYTHONUNBUFFERED": "1"})
        baseline = get_config_from_spec("mini")
        model = GatewayModel(
            model_name=model_name,
            model_kwargs={},
            cost_tracking="ignore_errors",
            observation_template=baseline["model"]["observation_template"],
            format_error_template=baseline["model"]["format_error_template"],
        )
        environment = CredentialScrubbedEnvironment(
            cwd=str(workspace),
            timeout=COMMAND_TIMEOUT_SECONDS,
            env=baseline["environment"]["env"]
            | {"MPLBACKEND": "Agg", "PYTHONUNBUFFERED": "1"},
        )
        agent = DefaultAgent(
            model,
            environment,
            system_template=baseline["agent"]["system_template"],
            instance_template=baseline["agent"]["instance_template"],
            step_limit=STEP_LIMIT,
            cost_limit=0,
            wall_time_limit_seconds=WALL_TIME_LIMIT_SECONDS,
        )
        outcome = agent.run(_task_prompt(task))

        relative_artifact = Path(task["expected_output"]["path"])
        artifact = _within_workspace(workspace, str(relative_artifact))
        artifact_bytes = artifact.read_bytes() if artifact.is_file() else None
        artifact_error = None
        if artifact_bytes and task["expected_output"]["format"].lower() == "png":
            try:
                from PIL import Image

                with Image.open(artifact) as rendered:
                    rendered.verify()
            except Exception as error:
                artifact_error = f"Invalid PNG: {error}"

        return {
            "task_id": task["task_id"],
            "task": task,
            "model": model_name,
            "scaffold": f"mini-swe-agent=={MINI_SWE_AGENT_VERSION}",
            "outcome": outcome,
            "trajectory": agent.serialize(),
            "artifact_path": str(relative_artifact),
            "artifact_present": artifact_bytes is not None,
            "artifact_error": artifact_error,
            "artifact_bytes": artifact_bytes,
            "elapsed_seconds": time.monotonic() - started,
        }
