"""OpenAI-compatible Modal endpoints for the three fixed generation models.

Deploy all three endpoints from the student release directory with:

    uv run modal deploy infrastructure/generation_models.py

Each class runs in its own GPU container and scales to zero independently.
"""

from __future__ import annotations

import modal
import serving

QWEN_MODEL = "Qwen/Qwen2.5-Coder-3B-Instruct"
MINISTRAL_MODEL = "mistralai/Ministral-3-14B-Instruct-2512"
GLM_MODEL = "zai-org/GLM-4.7-Flash"

app = modal.App("hw2-generation-models")

# GLM-4.7 support currently requires vLLM and Transformers revisions newer than
# the stable shared image, so pin the exact pair exercised by the live smoke
# test rather than allowing either dependency to drift.
glm_image = (
    modal.Image.from_registry(serving.CUDA, add_python="3.12")
    .entrypoint([])
    .apt_install("git")
    .uv_pip_install(
        "https://wheels.vllm.ai/fcdc7c2e9c9b75c923751ea7d2dd79ef66572c81/"
        "vllm-0.26.1rc1.dev224%2Bgfcdc7c2e9-cp38-abi3-manylinux_2_28_x86_64.whl",
    )
    .uv_pip_install(
        "git+https://github.com/huggingface/transformers.git@4a2e450e601214024c8a37abdaca35df2a4a3ba3"
    )
    .env(serving.ENVIRONMENT)
    .add_local_python_source("serving")
)


@app.cls(
    image=serving.base_image(),
    gpu="L4:1",
    max_containers=1,
    scaledown_window=5 * serving.MINUTES,
    timeout=10 * serving.MINUTES,
    volumes=serving.volumes(),
)
@modal.concurrent(max_inputs=16)
class QwenServer:
    @modal.enter()
    def start(self) -> None:
        self.process = serving.start(QWEN_MODEL, "qwen", [
            "--tool-call-parser", "hermes",
            "--enable-auto-tool-choice",
            "--max-num-seqs", "4",
            "--max-model-len", "32768",
            "--max-num-batched-tokens", "32768",
        ])

    @modal.web_server(port=serving.PORT, startup_timeout=10 * serving.MINUTES,
                      requires_proxy_auth=True)
    def serve(self) -> None:
        pass

    @modal.exit()
    def stop(self) -> None:
        serving.stop(self.process)


@app.cls(
    image=serving.base_image(),
    gpu="L40S:1",
    max_containers=1,
    scaledown_window=5 * serving.MINUTES,
    timeout=10 * serving.MINUTES,
    volumes=serving.volumes(),
)
@modal.concurrent(max_inputs=16)
class MinistralServer:
    @modal.enter()
    def start(self) -> None:
        self.process = serving.start(MINISTRAL_MODEL, "ministral", [
            "--tokenizer-mode", "mistral",
            "--config-format", "mistral",
            "--load-format", "mistral",
            "--tool-call-parser", "mistral",
            "--enable-auto-tool-choice",
            "--limit-mm-per-prompt", '{"image": 0}',
            "--max-num-seqs", "2",
            "--max-model-len", "32768",
            "--max-num-batched-tokens", "32768",
        ])

    @modal.web_server(port=serving.PORT, startup_timeout=10 * serving.MINUTES,
                      requires_proxy_auth=True)
    def serve(self) -> None:
        pass

    @modal.exit()
    def stop(self) -> None:
        serving.stop(self.process)


@app.cls(
    image=glm_image,
    gpu="H100:1",
    max_containers=1,
    scaledown_window=5 * serving.MINUTES,
    timeout=15 * serving.MINUTES,
    volumes=serving.volumes(),
)
@modal.concurrent(max_inputs=16)
class GlmServer:
    @modal.enter()
    def start(self) -> None:
        self.process = serving.start(GLM_MODEL, "glm-4.7", [
            "--tool-call-parser", "glm47",
            "--reasoning-parser", "glm45",
            "--enable-auto-tool-choice",
            "--max-num-seqs", "2",
            "--max-model-len", "32768",
            "--max-num-batched-tokens", "32768",
        ])

    @modal.web_server(port=serving.PORT, startup_timeout=15 * serving.MINUTES,
                      requires_proxy_auth=True)
    def serve(self) -> None:
        pass

    @modal.exit()
    def stop(self) -> None:
        serving.stop(self.process)
