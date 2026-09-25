#!/bin/bash
# MUTANT: every number is right and the chart is unreadable -- 2pt type on a
# 3x2.2in canvas, so the title, the axis labels and the four orchard names are
# each under three pixels tall. SCORES 1.0.
#
# That reward is the point of this mutant. All fifteen checks pass, measured,
# and they are right to: the totals are correct, the ordering is correct, the
# labels are present, the delivered PNG is the one plot.py renders, the sidecar
# agrees. Every property the verifier can name is satisfied. What is wrong with
# this figure is that a person cannot read it -- the `hard_to_read` family --
# and no assertion over an artist tree can see that, because legibility is not
# a property of the data or the structure. It is a property of the image.
#
# This is the half of step 4 that a strong verifier cannot do, and it is why the
# graded artifact in this assignment is a no-reference VLM judge.
#
# To run it, from harbor/example:
#   cp -r . /tmp/try
#   cp mutants/illegible/solve.sh /tmp/try/solution/solve.sh
#   cd /tmp/try && harbor run -p . -a oracle --job-name mutant-illegible
set -euo pipefail
cat > /app/plot.py <<'PY'
import csv, json
import matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt
totals = {}
with open("harvest_log.csv", newline="") as fh:
    for row in csv.DictReader(fh):
        if row["inspection"] != "cleared": continue
        totals[row["orchard"]] = totals.get(row["orchard"], 0.0) + int(row["crates"]) * float(row["kilos_per_crate"])
orchards = sorted(totals); values = [totals[o] for o in orchards]
fig, ax = plt.subplots(figsize=(3.0, 2.2))          # BUG: too small to read...
ax.bar(orchards, values, color="#4C78A8")
ax.set_title("Cleared yield by orchard", fontsize=2)  # ...and 2pt type throughout
ax.set_xlabel("Orchard", fontsize=2); ax.set_ylabel("Cleared yield (kg)", fontsize=2)
ax.tick_params(labelsize=2)
ax.set_ylim(0, max(values) * 1.1); fig.tight_layout(); fig.savefig("figure.png", dpi=100)
json.dump(dict(zip(orchards, values)), open("plotted_values.json", "w"), indent=2)
PY
cd /app && python plot.py
