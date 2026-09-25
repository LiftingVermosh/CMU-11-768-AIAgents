#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
student_dir="$(dirname -- "$script_dir")"
cd "$student_dir"

uv run python -m infrastructure.configure_generation
uv run modal deploy infrastructure/generation_gateway.py
uv run modal deploy infrastructure/agent_runner.py
