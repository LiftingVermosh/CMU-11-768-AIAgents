# Student-owned Modal endpoints

These files are the canonical model deployments for both student development
and staff grading. Each Modal workspace gets its own apps, volumes, endpoint
URLs, and usage charges.

From the student release directory:

```bash
uv sync
uv run modal setup
scripts/deploy_validator_model.sh
scripts/deploy_generation_models.sh  # Part 3 model servers
# Fill in the generation endpoint settings in .env.
scripts/deploy_agent_runner.sh       # Part 3 gateway and mini-SWE-agent runner
```

The validator deployment serves `Qwen/Qwen3-VL-30B-A3B-Instruct-FP8` with the
stable model alias `validator`. The generation deployment creates three
independently scaling containers:

| Endpoint class | Model | Alias | GPU |
| --- | --- | --- | --- |
| `QwenServer` | `Qwen/Qwen2.5-Coder-3B-Instruct` | `qwen` | L4 |
| `MinistralServer` | `mistralai/Ministral-3-14B-Instruct-2512` | `ministral` | L40S |
| `GlmServer` | `zai-org/GLM-4.7-Flash` | `glm-4.7` | H100 |

All endpoints require Modal proxy authentication and expose vLLM's
OpenAI-compatible API. Copy `.env.example` to `.env`, append `/v1` to the
validator URL printed by Modal, and add a Modal proxy token in combined
`<token-id>.<token-secret>` form.

The apps scale to zero after five idle minutes. Deploying creates stable URLs;
the first request after an idle period starts a GPU container and may take
several minutes while the model loads. A completely empty GLM cache can take
about 12 minutes on its first run because it downloads roughly 58 GiB of model
weights; later starts reuse the workspace volumes and compile cache.

For generation, append `/v1` to each URL printed for `QwenServer.serve`,
`MinistralServer.serve`, and `GlmServer.serve`. Put them in `.env` as
`GENERATION_QWEN_BASE_URL`, `GENERATION_MINISTRAL_BASE_URL`, and
`GENERATION_GLM_BASE_URL`, respectively, and set `GENERATION_API_KEY` to the
combined proxy token. The Part 3 generation command is documented in
`ASSIGNMENT.md`.

`deploy_agent_runner.sh` stores those settings in the private Modal secret
`hw2-generation-endpoints`, deploys `generation_gateway.py` with access to that
secret, and deploys `agent_runner.py` without it. The latter is the original
`mini-swe-agent==2.4.5` bash-tool scaffold used for the released trajectories;
agent-written commands execute in its fresh Modal container and cannot read the
generation endpoint credentials.
