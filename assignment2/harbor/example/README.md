# Worked example: a visualization task, packaged as a harbor environment

## What the task is

One complete, working harbor task: `name = "cmu-11768/viz-csv-harvest-yield"`,
`task_class = "csv_aggregation_bar"`, both set in `task.toml`. It has the same
shape as the visualization cases you wrote in Part 3: read a CSV, filter it,
derive a quantity, group it, draw the bar chart.

The agent gets `/app/harvest_log.csv`, a haul-level delivery ledger, and is asked
for a bar chart of total cleared yield per orchard. Keep the `cleared` rows,
derive `crates * kilos_per_crate`, sum within orchard. It must leave behind
`plot.py` (re-runnable, reading the CSV rather than hard-coding), `figure.png`,
and a `plotted_values.json` sidecar. The answer is `[558, 420, 1230, 816]` kg for
Brambleholt, Cinderpeak, Mistfen and Willowdrift.

The example uses an invented orchard ledger rather than data from a course task.
Use invented data in your own worked example as well. Because this directory
includes both its verifier (`tests/test_state.py`) and reference solution
(`solution/solve.sh`), using input from a real task would effectively publish
that task's answer.

## How to run it

You need Docker running and `uv sync` already done. harbor ships as a project
dependency, so every invocation is `uv run harbor`. Run from the release root,
the directory holding `ASSIGNMENT.md`:

```bash
# The reference solution. Must score 1.0.
uv run harbor run -p harbor/example -a oracle --job-name example-oracle

# The built-in do-nothing agent. Must score 0.0.
uv run harbor run -p harbor/example -a nop --job-name example-nop
```

`harbor run` is an alias for `harbor job start`. `-a oracle` skips the LLM and
runs `solution/solve.sh` as the agent, and `-a nop` runs nothing at all. Do not
reach for `harbor exec`, which is a different command that compiles paths into
tasks.

Run both, every time. The oracle proves the task is solvable and that the
verifier rewards a correct answer. The nop run proves the verifier withholds the
reward, meaning it
[fails closed](../TROUBLESHOOTING.md#an-empty-task-scores-10).

Each run produces a single number, `1` or `0`:

```text
jobs/example-oracle/*/verifier/reward.txt     # literally "1" or "0"
jobs/example-oracle/*/verifier/pytest.log     # every assertion, pass and fail
```

Start with `pytest.log`: it identifies the failed assertion and explains why it
failed. `result.json` reports only that the run failed.

The first run takes several minutes and looks like it has hung. Docker is
building the image, and that build needs network access: `network_mode =
"no-network"` applies to the run, not to the build. Warm runs take roughly 15
seconds, including the two full re-executions of the agent's script that this
verifier does. Anything else that goes wrong is in
[TROUBLESHOOTING.md](../TROUBLESHOOTING.md).

## What each file is for

The six files that make it a task:

| File | What it does |
|---|---|
| **`task.toml`** | The task definition: name, timeouts, resources, network mode, which files to pull out as artifacts. harbor reads this first, and if it cannot parse it there is no task. Heavily commented, including the three traps that cost staff the most time. |
| **`instruction.md`** | The prompt the agent sees. Nothing else is shown to it. State every requirement the verifier checks, including ones that feel pedantic like alphabetical orchard order and a zero-based y axis. An assertion you did not ask for is a trap rather than a test. |
| **`environment/Dockerfile`** | The container both the agent and the verifier run in. Pinned by digest, with every dependency baked in at build time because the run has no network. |
| **`environment/harvest_log.csv`** | The input data, copied into `/app` at build time. 20 synthetic rows, sha256 `1cc30e44…`. The verifier checks that digest, so an agent cannot doctor the input. |
| **`solution/solve.sh`** | The reference solution, run by `-a oracle`. Writes `plot.py` to disk and then executes it, because the task requires a re-runnable script to be left behind. |
| **`tests/test.sh`** | The verifier entry point. Runs pytest and translates its exit status into `/logs/verifier/reward.txt`. It deliberately has no `set -e`, because every path out of it must still write a number. |

The three that make the verifier strong. You are not expected to write anything
this strong, and section S1 alone is an acceptable verifier.

| File | What it does |
|---|---|
| **`tests/test_state.py`** | Contains 15 assertions organized into five sections, S1 through S5, in ascending order of cost. Its header explains each verification strategy, its benefit, and any mutant that only that strategy detects. Start here. |
| **`tests/sitecustomize.py`** | A short code snippet. Python auto-imports any module named `sitecustomize` at interpreter start-up, so putting this on `PYTHONPATH` lets the verifier patch matplotlib before the agent's script runs its first line, without editing that script. |
| **`tests/figure_manifest.py`** | Serializes a matplotlib figure's artist tree to JSON at save time, so the verifier can assert on bar heights and tick labels instead of pixels. Long, and you do not need to read it to understand the example. |

harbor's default verifier mode is shared. After the agent phase ends, harbor
copies `tests/` into the agent's own container and runs `test.sh` there as root.
`/app` arrives unchanged, so the agent's `plot.py` survives and not just
`figure.png`. `/tests` is copied in after the agent finished, so the agent never
saw these assertions. `/logs` holds `agent/`, `verifier/` and `artifacts/`.

This approach works because the agent's `plot.py` remains available during
verification. Instead of analyzing `figure.png` directly, the verifier re-runs
the program that created it. The optional
[reference notes](../reference/README.md) explain this technique in detail.

## What the four mutants show

`mutants/` holds four deliberately wrong solutions. Each is a drop-in replacement
for `solution/solve.sh`. Three are caught and one is not, and Part 3 asks you for
one of each:

| Mutant | What it gets wrong | Reward | Caught by |
|---|---|---|---|
| `sum_crates/` | Sums crates instead of `crates × kilos_per_crate`, plotting `[31, 56, 41, 68]` where the answer is `[558, 420, 1230, 816]`. | **0.0** | S2, the content check. The ordinary case. |
| `forgery/` | Leaves a correct `plot.py` on disk but hands in a `figure.png` rendered from the unfiltered totals `[684, 525, 1500, 996]`. | **0.0** | **S3 only**, pixel identity. Re-executing the agent's code grades the code, and something still has to grade the artifact. |
| `hardcoded/` | Types the correct totals in by hand and never opens the CSV. | **0.0** | **S4 only**, the input-perturbation probe. S1, S2, S3 and S5 all pass it. |
| `illegible/` | Every number right, on a 3×2.2in canvas in 2pt type, so the title, both axis labels and the four orchard names are under three pixels tall. | **1.0** | **None.** All fifteen checks pass because none evaluates rendered-text legibility. |

To run one:

```bash
rm -rf /tmp/try && cp -r harbor/example /tmp/try
cp harbor/example/mutants/hardcoded/solve.sh /tmp/try/solution/solve.sh
uv run harbor run -p /tmp/try -a oracle --job-name mutant-hardcoded
```

Then read `jobs/mutant-hardcoded/*/verifier/pytest.log` and find the assertion
that failed.

The `hardcoded` mutant demonstrates an important limitation of output-only
verification. It produces a correct chart and sidecar, and its script genuinely
renders the submitted image. The verifier can catch it only by changing the input
and checking that the output changes accordingly. Such a probe takes about
fifteen lines for a task that reads a data file.

The verifier accepts the `illegible` mutant because its data, ordering, labels,
PNG identity and sidecar are all correct. Its only defect is visual legibility,
which belongs to the `hard_to_read` family. Assertions over the artist tree do
not measure this property because it belongs to the rendered image rather than
the underlying data or structure.

Part 3 asks you to find your own version of both: one mutant your checks reject,
and one they let through.
