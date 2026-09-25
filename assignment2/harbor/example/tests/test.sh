#!/bin/bash
# ============================================================================
# The verifier entry point. harbor copies this whole tests/ directory into the
# agent's container AFTER the agent phase ends, then runs this script as root.
# The AGENT never sees it. Note what that does and does not buy: /tests is an
# ordinary writable directory at verify time, so anything the verifier itself
# re-executes can still read these files by absolute path.
#
# THE ONE THING THAT MATTERS: the reward is whatever ends up in
# /logs/verifier/reward.txt. 1 = solved, 0 = not. Nothing else here is a score.
# Your test.sh MUST write that file, and it must write 0 when things go wrong.
#
# Note there is deliberately NO `set -e`. With it, a failing pytest would abort
# this script before the reward is written, and a task with no reward.txt is a
# task that fails in a confusing way instead of failing honestly at 0. This is
# the fail-CLOSED discipline: every path out of here writes a number.
# ============================================================================
mkdir -p /logs/verifier

# Call the image interpreter by absolute path, NOT `uvx pytest` or `python3`
# off PATH. The stock harbor test.sh template apt-gets a toolchain and curls a
# fresh CPython at grade time: that needs network during grading (this task has
# none), it is slow, and the interpreter it lands on has no matplotlib -- which
# every check in test_state.py depends on. pytest is baked into the image
# instead; see environment/Dockerfile.
/usr/local/bin/python3 -m pytest /tests/test_state.py \
  -rA -q --no-header \
  --ctrf /logs/verifier/ctrf.json 2>&1 | tee /logs/verifier/pytest.log

# PIPESTATUS[0], not $?: $? is tee's exit status, and tee essentially always
# succeeds. Reading $? here would hand out reward 1 for every failed run --
# a fail-OPEN verifier, the exact bug `harbor init`'s scaffold ships with.
if [ "${PIPESTATUS[0]}" -eq 0 ]; then
  echo 1 > /logs/verifier/reward.txt
else
  echo 0 > /logs/verifier/reward.txt
fi
echo "[test.sh] reward=$(cat /logs/verifier/reward.txt)"
