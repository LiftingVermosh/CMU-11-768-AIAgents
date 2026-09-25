#!/bin/bash
# MUTANT: the plot.py left on disk is completely correct, but the figure.png
# handed in was rendered separately from UNFILTERED totals (spoiled hauls
# included). Script and image disagree. SCORES 0.0.
#
# Caught ONLY by S3, the pixel-identity check: the delivered PNG must be what
# re-running the delivered script produces. S1 passes (valid PNG, script on
# disk), S2 passes (the script is right), S4 passes (the script does read the
# CSV), S5 passes (the sidecar declares the correct numbers). Re-executing the
# agent's code grades the CODE; something still has to grade the ARTIFACT.
#
# To run it, from harbor/example:
#   cp -r . /tmp/try
#   cp mutants/forgery/solve.sh /tmp/try/solution/solve.sh
#   cd /tmp/try && harbor run -p . -a oracle --job-name mutant-forgery
set -euo pipefail
# The script left on disk is the correct one...
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
fig, ax = plt.subplots(figsize=(6, 4))
ax.bar(orchards, values, color="#4C78A8")
ax.set_title("Cleared yield by orchard")
ax.set_xlabel("Orchard"); ax.set_ylabel("Cleared yield (kg)")
ax.set_ylim(0, max(values) * 1.1); fig.tight_layout(); fig.savefig("figure.png", dpi=100)
json.dump(dict(zip(orchards, values)), open("plotted_values.json", "w"), indent=2)
PY
# ...but the delivered figure comes from somewhere else entirely.
cd /app && python - <<'PY'
import json
import matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt
orchards = ["Brambleholt", "Cinderpeak", "Mistfen", "Willowdrift"]
values = [684.0, 525.0, 1500.0, 996.0]   # spoiled hauls left in
fig, ax = plt.subplots(figsize=(6, 4))
ax.bar(orchards, values, color="#4C78A8")
ax.set_title("Cleared yield by orchard")
ax.set_xlabel("Orchard"); ax.set_ylabel("Cleared yield (kg)")
ax.set_ylim(0, max(values) * 1.1); fig.tight_layout(); fig.savefig("figure.png", dpi=100)
json.dump(dict(zip(orchards, [558.0, 420.0, 1230.0, 816.0])), open("plotted_values.json", "w"), indent=2)
PY
