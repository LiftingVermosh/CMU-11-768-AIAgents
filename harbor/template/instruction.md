<!-- TODO: this file IS the task. It is the only thing the agent sees.
     Everything your verifier checks must be stated here, precisely enough
     that a careful solver could not get it wrong by accident.
     Delete every TODO before you ship. -->

# TODO: task title

TODO: describe the input. Name the file, say where it is (`/app`), and list its
columns/fields and what they mean.

TODO: say exactly what to compute -- as numbered steps, not prose. Ambiguity
here is what makes a task ungradeable.

1. TODO
2. TODO

TODO: say exactly what to draw -- chart type, what goes on which axis, ordering,
axis limits, title and axis labels.

## Required outputs

Leave these behind in `/app`, which is also the working directory. `plot.py` must
refer to these files by bare filename rather than by absolute path. State this
requirement explicitly: the verifier re-runs the script in a copied workspace,
so an absolute output path would point outside that copy.

TODO: decide whether extra images are allowed and say so. The example allows
them and grades the one named `figure.png`; requiring "exactly one figure" is
also fine, but then your verifier has to actually check it -- do not state a
rule you do not enforce.

1. **`/app/plot.py`** - the plotting script. Self-contained and re-runnable:
   `python plot.py` from `/app` must reproduce the figure with no arguments and
   no manual steps. It must read the input file rather than hard-code results,
   and it must render the same image every time it runs.
2. **`/app/figure.png`** - the chart, as saved by that script.
3. **`/app/plotted_values.json`** - the values shown in the chart. Generate this
   file from the same variables used to draw the figure. Part 3 requires this
   sidecar because the verifier cannot reliably recover exact values from the
   PNG. **TODO:** Specify the exact keys and value types, and include a small
   all-zero example like the one in `harbor/example/instruction.md`.

TODO: state the prohibitions your verifier relies on, e.g. do not modify the
input file.

Only the libraries already installed are available and there is no network
access; everything you need is in the image.
