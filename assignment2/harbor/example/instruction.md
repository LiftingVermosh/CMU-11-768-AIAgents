# Cleared yield by orchard, from a haul-level CSV

The file `harvest_log.csv` in your working directory (`/app`) is the delivery ledger of
the Thornwick Skyfarm, an entirely fictional floating orchard. It holds one row per
crate haul brought down from the canopy, with the columns:

```
haul_id         - an integer identifier
orchard         - one of Brambleholt, Cinderpeak, Mistfen, Willowdrift
crew            - dawn or dusk
crates          - integer number of crates in the haul
kilos_per_crate - mass of one crate, in kilograms
inspection      - cleared or spoiled
```

Read that file and, using matplotlib, draw a bar chart of total cleared yield per
orchard. Compute it like this:

1. Keep only the rows whose inspection is `cleared`; spoiled hauls contribute nothing.
2. The file has no total-mass column, so derive each remaining haul's yield as
   `crates * kilos_per_crate`.
3. Sum that yield within each orchard.

Draw the result as a single chart on one set of axes: one vertical bar per orchard,
with the four orchards along the x axis in alphabetical order (Brambleholt, Cinderpeak,
Mistfen, Willowdrift), and yield in kilograms on the y axis.
Keep the y axis starting at zero so the bar lengths stay proportional.
Give the chart a title and label both the x and the y axis.

## Required outputs

Create the following three files in `/app`. In `plot.py`, refer to
`harvest_log.csv` and `figure.png` by bare filename rather than by absolute path.
The grader re-runs the script in a copied workspace, so an absolute output path
would point outside that copy.

Saving extra images is allowed — an exploratory chart you looked at along the
way does no harm, and the answer is graded from the figure saved as
`figure.png`. Give any extra image a different *stem*, though: a second save
named `figure.<anything>` collides with the graded one.

1. **`/app/plot.py`** - the plotting script itself. It must be a self-contained,
   re-runnable Python program: running `python plot.py` from `/app` must read
   `harvest_log.csv` and write `figure.png`, with no arguments and no manual steps.
   Do not do the work in a heredoc or with `python -c`; the script must survive
   on disk, and it must read the numbers out of `harvest_log.csv` rather than
   hard-coding the totals. It must also render the same image every time it
   runs: no random colours, no timestamp in the title.
2. **`/app/figure.png`** - the chart. It must be the file that `plot.py` saves:
   re-running the script must reproduce this exact image.
3. **`/app/plotted_values.json`** - the values shown in the chart. Generate this
   file from the same variables passed to the plotting function. It must contain
   one JSON object with exactly four keys: `Brambleholt`, `Cinderpeak`, `Mistfen`
   and `Willowdrift`. Each value must be a JSON number representing kilograms,
   with no unit suffix or thousands separator. For example:
   `{"Brambleholt": 0.0, "Cinderpeak": 0.0, "Mistfen": 0.0, "Willowdrift": 0.0}`.

Do not modify `harvest_log.csv`.

Only matplotlib, numpy, pandas and Pillow are available, and there is no network
access; everything you need is already installed.
