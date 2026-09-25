"""Serving one model with vLLM behind an OpenAI-compatible port on Modal.

Both deployments in this directory stand up the same thing and differ only in
which model, on which GPU, with which vLLM arguments, so the container image and
the process handling live here and are imported by each.

The module runs inside the container as well as out, so any image built on
`base_image` has to carry it: see `add_local_python_source` below.
"""

from __future__ import annotations

import json
import socket
import subprocess
import time
from urllib.request import Request, urlopen

import modal

MINUTES = 60
PORT = 8000

CUDA = "nvidia/cuda:12.9.0-devel-ubuntu22.04"
ENVIRONMENT = {"HF_XET_HIGH_PERFORMANCE": "1", "TORCHINDUCTOR_COMPILE_THREADS": "1"}


def base_image() -> modal.Image:
    """The image both deployments serve from, with this module inside it."""
    return (
        modal.Image.from_registry(CUDA, add_python="3.12")
        .entrypoint([])
        .uv_pip_install(
            "vllm==0.13.0",
            "huggingface-hub==0.36.0",
            "flashinfer-python==0.5.3",
        )
        .env(ENVIRONMENT)
        .add_local_python_source("serving")
    )


def volumes() -> dict[str, modal.Volume]:
    """Caches shared by every deployment, so a model is downloaded once."""
    return {
        "/root/.cache/huggingface": modal.Volume.from_name(
            "hw2-huggingface-cache", create_if_missing=True),
        "/root/.cache/vllm": modal.Volume.from_name(
            "hw2-vllm-cache", create_if_missing=True),
    }


def _wait_ready(process: subprocess.Popen[bytes]) -> None:
    while True:
        try:
            socket.create_connection(("localhost", PORT), timeout=1).close()
            return
        except OSError:
            if process.poll() is not None:
                raise RuntimeError(f"vLLM exited with {process.returncode}")
            time.sleep(0.1)


def _warmup(alias: str) -> None:
    """One request through the server, so the first real one is not the cold one."""
    request = Request(
        f"http://localhost:{PORT}/v1/chat/completions",
        data=json.dumps({
            "model": alias,
            "messages": [{"role": "user", "content": "Reply with OK."}],
            "max_tokens": 8,
        }).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urlopen(request, timeout=5 * MINUTES) as response:
        if response.status != 200:
            raise RuntimeError(f"vLLM warmup returned HTTP {response.status}")


def start(model: str, alias: str, arguments: list[str]) -> subprocess.Popen[bytes]:
    """Serve `model` under both its own name and `alias`, and wait for it."""
    command = [
        "vllm", "serve", model,
        "--served-model-name", model, alias,
        "--host", "0.0.0.0",
        "--port", str(PORT),
        "--gpu-memory-utilization", "0.95",
        *arguments,
    ]
    print(*command, flush=True)
    process = subprocess.Popen(command)
    _wait_ready(process)
    _warmup(alias)
    return process


def stop(process: subprocess.Popen[bytes]) -> None:
    process.terminate()
    try:
        process.wait(timeout=30)
    except subprocess.TimeoutExpired:
        process.kill()
