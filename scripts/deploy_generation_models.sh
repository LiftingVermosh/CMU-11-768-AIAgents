#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
student_dir="$(dirname -- "$script_dir")"
cd "$student_dir"

exec uv run modal deploy infrastructure/generation_models.py
