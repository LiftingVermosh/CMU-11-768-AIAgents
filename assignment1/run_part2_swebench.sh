#!/usr/bin/env bash
# Part 2 SWE-bench runs for django__django-15368:
#   1) compaction run  (COMPACT_THRESHOLD=6000)  + check-swebench on its patch
#   2) baseline run    (COMPACT_THRESHOLD=0, full context, no compaction)
# Billable Modal time; run from a terminal and leave it alone. Skip [1] once
# `uv run modal setup` has authed this machine.
set -euo pipefail

cd "$(dirname "$0")"          # assignment1
mkdir -p artifacts


# NOTE: WSL2 Usage -> Windows host proxy
WSL_PROXY_HOST="$(ip route show default | awk '/default/ {print $3; exit}')"
# TODO: Config your proxy port here
PORT=10808

export HTTP_PROXY="http://${WSL_PROXY_HOST}:${PORT}"
export HTTPS_PROXY="http://${WSL_PROXY_HOST}:${PORT}"
export ALL_PROXY="http://${WSL_PROXY_HOST}:${PORT}"
export NO_PROXY="localhost,127.0.0.1,::1,api.deepseek.com"

# One-time Modal auth. Comment out if already logged in.
# uv run modal setup

echo "==> [1/3] compaction run (threshold 6000)"
COMPACT_THRESHOLD=6000 \
SWEBENCH_PATCH=artifacts/django__django-15368.patch \
SWEBENCH_TRAJECTORY=artifacts/django__django-15368-trajectory.json \
make run-swebench-agent INSTANCE=django__django-15368

echo "==> [2/3] check-swebench on the compacted patch"
make check-swebench INSTANCE=django__django-15368

echo "==> [3/3] baseline run (no compaction)"
COMPACT_THRESHOLD=0 \
SWEBENCH_PATCH=artifacts/django__django-15368-baseline.patch \
SWEBENCH_TRAJECTORY=artifacts/django__django-15368-baseline-trajectory.json \
make run-swebench-agent INSTANCE=django__django-15368

echo "==> done"
