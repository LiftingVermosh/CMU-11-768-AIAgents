# Packaging your tasks as harbor environments

Your Part 3 tasks are `task.json` descriptors that only `workflow generate` knows
how to run. In this part you convert each one into a harbor task: a
self-contained, containerized environment that anyone can run with one command,
graded by a deterministic verifier instead of a model judge.

[`../ASSIGNMENT.md`](../ASSIGNMENT.md), Part 3, states the graded requirements.
This file gives the commands and examples for completing them.

Run every command below from the release root, the directory holding
`ASSIGNMENT.md`. `harbor run` writes `./jobs/` relative to your current
directory, so working from one place keeps the results together. You also need
Docker running.

```bash
uv sync
uv run harbor --version        # 0.23.0
```

## 1. Run the worked example

```bash
uv run harbor run -p harbor/example -a oracle --job-name example-oracle   # 1.0
uv run harbor run -p harbor/example -a nop    --job-name example-nop      # 0.0
```

`-a oracle` runs the task's own `solution/solve.sh`, and `-a nop` is the built-in
do-nothing agent. Your verifier has to separate those two.

Then run at least one of the four wrong solutions in `harbor/example/mutants/`.
Three of them score 0.0 and `illegible/` scores 1.0.
[`example/README.md`](example/README.md) walks through the task, what each file
does, and the command that swaps a mutant in. Read it before step 4.

The first run on a new machine builds a Docker image. This takes several minutes
and looks like it has hung.

## 2. Package each Part 3 task

Do not build a task directory by hand, and do not run `harbor init`: its scaffold
[fails open](TROUBLESHOOTING.md#an-empty-task-scores-10). Scaffold from the
descriptors you already wrote.

```bash
uv run python -m workflow package          # every task under tasks/
uv run python -m workflow package <id>     # or just one
```

At minimum, complete the checks, the reference solution, and the `## Required
outputs` block in `instruction.md`. Also replace the remaining TODOs in
`task.toml` and adjust the Dockerfile and artifact list as needed. The command
will not overwrite a directory that already exists, so pass `--force` only if
you mean to discard the verifier in it.

Part 3 requires every packaged task to ask the agent for `plot.py` and
`plotted_values.json`. The scaffold asks for both already. What you still have to
write is the sidecar's schema, meaning the exact keys and value types, the way
[`example/instruction.md`](example/instruction.md) states them.

You get:

```text
harbor/tasks/<task_id>/
  task.toml                 # metadata, timeouts, network mode
  instruction.md            # what the agent is told
  environment/Dockerfile    # base image + pinned deps + COPY your inputs
  environment/<inputs>      # your Part 3 input files
  solution/solve.sh         # YOUR reference solution; what `-a oracle` runs
  tests/test.sh             # runs the verifier, writes /logs/verifier/reward.txt
  tests/test_*.py           # the checks themselves
```

`harbor/template/` is that layout emptied out and commented, and
`harbor/example/` is a complete working task to copy from. Check a task before
spending a Docker cycle on it:

```bash
uv run python harbor/preflight.py harbor/tasks/<task_id>   # exit 0 = harbor accepts it
```

Derive your expected values by hand and write them into the test file as
literals. A test file that re-implements the aggregation will pass a solution
that repeats its own bug.

Keep harbor-only requirements inside `harbor/tasks/`. A requirement that leaks
back into `tasks/<task_id>/task.json` changes what your validator is measured on.

## 3. Confirm each task scores 1.0 with the oracle (required)

```bash
uv run harbor run -p harbor/tasks/<task_id> -a oracle --job-name <task_id>-oracle
cat jobs/<task_id>-oracle/*/verifier/reward.txt          # must be 1
```

If a task's reference solution does not score 1.0, fix the task before submitting
it. When it scores 0, `jobs/<task_id>-oracle/*/verifier/pytest.log` names the
assertion that failed.

Recommended but not required: run `-a nop` as well and confirm 0.

## 4. Write two mutants total (required)

Across all of your packaged tasks, write two mutants total. Each goes under
`harbor/tasks/<task_id>/mutants/<name>/solve.sh`; they may belong to the same
task or to different tasks. Both should be the kind of mistake a real agent
makes rather than "do nothing".

**One must score 0.** A wrong number is the cheapest to catch: drop a filter, sum
the wrong column, sort by value instead of by label. You already ask for
`plotted_values.json`, so assert the totals you derived by hand against it and
this mutant fails.

**The other must score 1.0.** It should expose a real limitation of the verifier.
For example, a chart can contain the correct data and labels but remain
unreadable because it uses 2pt text on a small canvas.
[`example/mutants/illegible/`](example/mutants/illegible/solve.sh) is a worked
version that scores 1.0 against the example's own verifier.

Swap each one over the reference solution in a scratch copy, so the task you
submit keeps its real `solve.sh`:

```bash
rm -rf /tmp/mut && cp -r harbor/tasks/<task_id> /tmp/mut
cp harbor/tasks/<task_id>/mutants/<name>/solve.sh /tmp/mut/solution/solve.sh
uv run harbor run -p /tmp/mut -a oracle --job-name <task_id>-<name>
```

For each mutant, report what it gets wrong and its reward. For the rejected
mutant, name the assertion that caught it. For the accepted mutant, explain what
the verifier failed to detect.

`uv run python -m workflow check-submission` runs every packaged task's oracle,
then runs mutants until it observes one reward of 0 and one reward of 1. Run
steps 3 and 4 before reporting the results. Pass `--skip-harbor-runs` to check
the structure alone while you are still iterating.

## How strong does the verifier have to be?

Strong enough to reject one of your two mutants. The simplest approach is to
compare the values in `plotted_values.json` with expected values that you derived
by hand and wrote as literals in the test file. Any mutant that changes a plotted
number is then caught, and you never read anything off the PNG.

"`figure.png` exists, is a valid PNG, is not blank, and the input file was not
modified" is not enough on its own. That is section S1 of the example's
`tests/test_state.py`, and it passes a chart of the wrong numbers.

Add other content checks when they are straightforward to implement. You are not
required to detect every possible visual error. Describe any remaining
limitations in the report. The verifier in `harbor/example/` is more thorough
than what is asked of you, so read it for ideas rather than as a bar to clear.

## What is provided

| Path | What it is | Required? |
| --- | --- | --- |
| `harbor/example/` | A complete, working harbor task on invented data. 1.0 with `-a oracle`, 0.0 with `-a nop`. | Read and run it |
| `harbor/example/mutants/` | Four wrong `solve.sh` variants: three score 0.0, and `illegible/` scores 1.0. Worked versions of step 4. | Run at least one |
| `harbor/template/` | A commented starter layout with generic checks, TODO markers and a fail-closed sentinel. | Recommended |
| `harbor/preflight.py` | Validates a task directory before you spend a Docker cycle, and prints the pydantic error harbor swallows. | Recommended |
| `harbor/TROUBLESHOOTING.md` | Symptom, cause and fix for the errors you are most likely to hit. | Read when stuck |
| `harbor/reference/` | Notes on the strong-verifier technique the example uses. | Optional |

## When you are stuck

1. `uv run python harbor/preflight.py <task-dir>` validates the task directory
   offline, without Docker, and prints the pydantic error harbor hides.
2. [TROUBLESHOOTING.md](TROUBLESHOOTING.md) is a symptom list. Find your error
   message there.
3. `jobs/<job-name>/<trial>/verifier/pytest.log` is the verifier's own output.
4. `jobs/<job-name>/<trial>/trial.log` and `agent/` show what the agent did.
