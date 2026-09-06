#!/usr/bin/env bash
# Part 3 batch: play the repaired chess app with ChessAgent.
#   1) basic game            -> artifacts/part3-trajectory.json, game-result.json
#   2) observation A/B x4     -> deepseek/gpt-oss x no-legal/legal (8 files)
#   3) skill+programmatic run -> artifacts/part3-python-skill-trajectory.json
# Billable Modal time; each step launches its own sandbox. Steps keep going if
# one fails, so a bad model run does not abort the rest. Run from a terminal.
set -u

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

# One-time Modal auth. Uncomment if not logged in yet.
# uv run modal setup

# TODO: Config your model name here
: "${MODEL:=deepseek-v4-flash-vision-exp}"
: "${DEEPSEEK_MODEL:=deepseek-v4-flash-vision-exp}"
: "${GPT_OSS_MODEL:=deepseek-v4-flash}"
export MODEL DEEPSEEK_MODEL GPT_OSS_MODEL

if [ ! -f artifacts/fix.patch ]; then
    echo "ERROR: artifacts/fix.patch not found. Every Part 3 run applies it to"
    echo "the testbed. Generate it first with the Part 1 agent:"
    echo "    make run-code-agent"
    echo "(writes artifacts/fix.patch and artifacts/part1-trajectory.json)"
    exit 1
fi

fail=0
run() {
    local name="$1"; shift
    echo; echo "========== [$name] $* =========="
    if "$@"; then
        echo "========== [$name] OK =========="
    else
        echo "========== [$name] FAILED =========="
        fail=1
    fi
}

run "basic-chess"        make run-chess-agent
run "obs-deepseek-no-legal" make run-obs-deepseek-no-legal
run "obs-deepseek-legal" make run-obs-deepseek-legal
run "obs-gpt-oss-no-legal"  make run-obs-gpt-oss-no-legal
run "obs-gpt-oss-legal"     make run-obs-gpt-oss-legal

run "skill-trajectory" uv run assignment-play-chess \
    --patch artifacts/fix.patch \
    --skills-path tasks/chess-skills \
    --programmatic-tools \
    --model "$MODEL" \
    --step-limit 200 \
    --sandbox-timeout 1800 \
    --trajectory artifacts/part3-python-skill-trajectory.json \
    --result artifacts/part3-python-skill-result.json

echo
echo "========== SUMMARY =========="
if [ "$fail" -eq 0 ]; then
    echo "All Part 3 runs finished. Expected artifacts:"
    echo "  artifacts/part3-trajectory.json / game-result.json"
    echo "  artifacts/part3-{no-legal,legal}-moves-{deepseek,gpt-oss}.json (+-result.json)"
    echo "  artifacts/part3-python-skill-trajectory.json / -result.json"
else
    echo "One or more runs FAILED; see logs above. Re-run just the failed step."
    exit 1
fi
