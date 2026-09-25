#!/bin/bash
# Reference solution.  The oracle agent (`-a oracle`) runs this in /app; it is
# what proves your task is solvable and that your verifier can say yes.
set -euo pipefail

# --- HARBOR-TEMPLATE-SENTINEL ---------------------------------------------
# TODO: replace this whole block with the real solution, then delete the
# `exit 1` below.  It must produce, unattended, exactly the outputs
# instruction.md promises.  Until then this task scores 0, which is on purpose:
# a template that scored 1.0 unimplemented would tell you that you were done.
# ---------------------------------------------------------------------------
cat >&2 <<'MSG'
solve.sh is still the unedited template, so this task scores 0 by design.

Write the reference solution here: it must leave behind, in /app, every file
instruction.md asks the agent for -- typically the plotting script, the PNG it
saves, and any sidecar JSON.  Write the script with a heredoc and then run it,
so the delivered figure is genuinely the one the script renders.

Then run:  harbor run -p <this-task-dir> -a oracle --job-name <name>
and expect reward 1.0.
MSG
exit 1
