#!/bin/bash
# MUTANT: the correct totals typed in by hand. harvest_log.csv is never opened.
# SCORES 0.0 -- and it is the interesting one.
#
# Caught ONLY by S4, the input-perturbation probe. Everything else passes it
# cleanly: the files are there (S1), the bar heights are exactly right (S2),
# the delivered PNG really is what the script renders (S3), and the sidecar
# agrees with the chart (S5). No amount of checking the OUTPUT can distinguish
# a solution from a transcription of the answer. Only changing the INPUT and
# demanding the output move can. If you take one idea from this example, this
# is the one -- it is about fifteen lines in any task that reads a data file.
#
# To run it, from harbor/example:
#   cp -r . /tmp/try
#   cp mutants/hardcoded/solve.sh /tmp/try/solution/solve.sh
#   cd /tmp/try && harbor run -p . -a oracle --job-name mutant-hardcoded
set -euo pipefail
cat > /app/plot.py <<'PY'
import json
import matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt
# I worked the totals out by hand and typed them in.
orchards = ["Brambleholt", "Cinderpeak", "Mistfen", "Willowdrift"]
values = [558.0, 420.0, 1230.0, 816.0]
fig, ax = plt.subplots(figsize=(6, 4))
ax.bar(orchards, values, color="#4C78A8")
ax.set_title("Cleared yield by orchard")
ax.set_xlabel("Orchard"); ax.set_ylabel("Cleared yield (kg)")
ax.set_ylim(0, max(values) * 1.1); fig.tight_layout(); fig.savefig("figure.png", dpi=100)
json.dump(dict(zip(orchards, values)), open("plotted_values.json", "w"), indent=2)
PY
cd /app && python plot.py
