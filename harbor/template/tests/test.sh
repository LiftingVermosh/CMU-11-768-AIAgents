#!/bin/bash
# Copied to /tests AFTER the agent finishes, then run as root inside the
# agent's own container (harbor's default verifier mode is "shared").  So this
# sees the full post-agent /app, and the agent never saw these tests.
#
# Everything needed is already in the image, so this downloads nothing and
# works under network_mode = "no-network".
mkdir -p /logs/verifier

# /usr/local/bin/python3 is the IMAGE interpreter -- the one with matplotlib,
# numpy and Pillow.  Do not use `uvx pytest` or a bare `python`: you can end up
# in an ephemeral interpreter that has none of your libraries.
/usr/local/bin/python3 -m pytest /tests/test_state.py \
  -rA -q --no-header \
  --ctrf /logs/verifier/ctrf.json 2>&1 | tee /logs/verifier/pytest.log

# The reward file is what actually sets the score.  Write it on every path.
if [ "${PIPESTATUS[0]}" -eq 0 ]; then
  echo 1 > /logs/verifier/reward.txt
else
  echo 0 > /logs/verifier/reward.txt
fi
