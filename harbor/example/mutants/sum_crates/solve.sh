#!/bin/bash
# MUTANT: sums crates instead of crates * kilos_per_crate -- plots
# [31, 56, 41, 68] where the answer is [558, 420, 1230, 816]. SCORES 0.0.
#
# Caught by four assertions at once, measured: test_s2_exact_yield_totals,
# test_s2_each_bar_carries_its_own_orchards_value, test_s4_totals_track_the_
# input_file and test_s5_sidecar_matches_key_and_chart (4 failed, 11 passed).
# S2 is the one that matters -- the others are incidental. This is the
# ordinary case: a wrong answer, computed honestly, that any verifier which
# actually checks the NUMBERS will catch -- and that a verifier which only
# checks "figure.png exists and is a valid PNG" will happily award 1.0.
#
# To run it, from harbor/example:
#   cp -r . /tmp/try
#   cp mutants/sum_crates/solve.sh /tmp/try/solution/solve.sh
#   cd /tmp/try && harbor run -p . -a oracle --job-name mutant-sum_crates
set -euo pipefail
cat > /app/plot.py <<'PY'
import csv, json
import matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt
totals = {}
with open("harvest_log.csv", newline="") as fh:
    for row in csv.DictReader(fh):
        if row["inspection"] != "cleared": continue
        totals[row["orchard"]] = totals.get(row["orchard"], 0.0) + int(row["crates"])  # BUG: crates, not kilograms
orchards = sorted(totals); values = [totals[o] for o in orchards]
fig, ax = plt.subplots(figsize=(6, 4))
ax.bar(orchards, values, color="#4C78A8")
ax.set_title("Cleared yield by orchard")
ax.set_xlabel("Orchard"); ax.set_ylabel("Cleared yield (kg)")
ax.set_ylim(0, max(values) * 1.1); fig.tight_layout(); fig.savefig("figure.png", dpi=100)
json.dump(dict(zip(orchards, values)), open("plotted_values.json", "w"), indent=2)
PY
cd /app && python plot.py
