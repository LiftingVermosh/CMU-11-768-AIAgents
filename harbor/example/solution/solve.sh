#!/bin/bash
# ============================================================================
# The reference solution -- what harbor calls the ORACLE.
#
# `harbor run -p . -a oracle` skips the LLM entirely and runs this script in
# /app as the "agent". It is how you prove your task is solvable and that your
# verifier actually rewards a correct answer: the oracle must score 1.0. Pair
# that with `-a nop` (the built-in do-nothing agent), which must score 0.0.
# A task where nop scores 1.0 is fail-OPEN and grades nothing -- that is the
# state `harbor init` leaves you in, so always run both.
#
# Note this writes plot.py to disk and then EXECUTES it, rather than doing the
# work inline. The task requires a re-runnable script to be left behind, and
# the verifier re-executes it; an oracle that cheated here would fail its own
# verifier, which is a useful sanity check in itself.
# ============================================================================
set -euo pipefail

cat > /app/plot.py <<'PY'
"""Total cleared yield per orchard, from haul-level rows in harvest_log.csv."""
import csv
import json

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

totals: dict[str, float] = {}
with open("harvest_log.csv", newline="") as handle:
    for row in csv.DictReader(handle):
        if row["inspection"] != "cleared":         # 1. spoiled hauls contribute nothing
            continue
        yield_kg = int(row["crates"]) * float(row["kilos_per_crate"])  # 2. derive yield
        totals[row["orchard"]] = totals.get(row["orchard"], 0.0) + yield_kg  # 3. group

orchards = sorted(totals)   # alphabetical: Brambleholt, Cinderpeak, Mistfen, Willowdrift
values = [totals[orchard] for orchard in orchards]

fig, ax = plt.subplots(figsize=(6, 4))
ax.bar(orchards, values, color="#4C78A8")
ax.set_title("Cleared yield by orchard")
ax.set_xlabel("Orchard")
ax.set_ylabel("Cleared yield (kg)")
ax.set_ylim(0, max(values) * 1.1)                 # y axis starts at zero
fig.tight_layout()
fig.savefig("figure.png", dpi=100)

with open("plotted_values.json", "w") as handle:
    json.dump(dict(zip(orchards, values)), handle, indent=2)
PY

cd /app && python plot.py
