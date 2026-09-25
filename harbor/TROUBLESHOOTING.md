# harbor troubleshooting

Symptom → cause → fix, measured on harbor **0.23.0** and Docker 29.x. Ctrl-F your
error.

Every shell command here is meant to be run from the **release root** — the
directory holding `ASSIGNMENT.md`, one level above this file. That is the same
working directory [`ASSIGNMENT.md`](../ASSIGNMENT.md) and
[`harbor/README.md`](README.md) ask for, and it is what keeps every `jobs/`
directory in one place.

## `uv add harbor` installs harbor 0.6.1, not 0.23.0

harbor is already pinned in `pyproject.toml`, so you should not run this command.
If you do, it may silently replace the pin with `harbor>=0.6.1` and successfully
install harbor **0.6.1**. The commands, messages and timings in this documentation
assume harbor **0.23.0**.

**Cause.** harbor 0.23.0 depends indirectly on `openai>=2.20,<3.0` through
litellm. If the project requires openai 3.x, the resolver instead selects the
newest compatible harbor release, which is 0.6.1. Explicitly requesting harbor
0.23.0 exposes the dependency conflict:

```text
$ uv add harbor==0.23.0
× No solution found when resolving dependencies:
  ╰─▶ ... harbor==0.23.0 depends on openai>=2.20.0,<3.0.0. And because your
      project depends on openai==3.X, your project's requirements are
      unsatisfiable.
```

**Fix.** Restore both pins — `harbor==0.23.0` and `openai==2.54.0` — in
`pyproject.toml`, then re-resolve. Do not repair this with `uv add harbor`; that
is what broke it.

```bash
uv lock && uv sync
uv run harbor --version        # -> 0.23.0
```

## pip says harbor does not exist

A wall of `Ignored the following versions ...`, ending in:

```text
ERROR: Could not find a version that satisfies the requirement harbor
ERROR: No matching distribution found for harbor
```

**Cause.** Not a missing package. You are on **Python < 3.12**; harbor requires
`>=3.12`, so the resolver reports no compatible distribution as if the name were
unknown.

```bash
python3 --version               # < 3.12 -> this is your problem
uv sync                         # uv fetches a 3.12 interpreter for you
```

## `cannot execute: required file not found` (Windows checkouts)

```text
bash: line 1: /solution/solve.sh: cannot execute: required file not found
```

Same line for `/tests/test.sh`; exit code **127**, `Exceptions 1 /
RewardFileNotFoundError`, and **no `reward.txt` written at all**.

**Cause.** `core.autocrlf=true` (the Windows default) checked the `.sh` files
out with CRLF, so Linux looks for an interpreter named `bash\r`.

**Fix.** The repo's `.gitattributes` prevents this on a fresh clone; a working
copy you already have is already broken. Repair it in place, from the
repository root, in Git Bash or WSL:

```bash
find . \( -name '*.sh' -o -name '*.csv' \) -exec sed -i 's/\r$//' {} +
```

`.csv` too: CRLF changes `harvest_log.csv`'s sha256, and the example's input
check then fails quietly — reward 0.0, no exception.

## `ValueError: Either datasets or tasks must be provided.`

This message usually means that `task.toml` failed validation, not that the task
directory is missing. harbor catches the pydantic error, falls back to treating
your path as a *dataset* directory, finds no tasks, and raises this. The real
error is never printed. To see it: `uv run python harbor/preflight.py <task-dir>`.

Two causes that actually happen. `harbor init` writes both fields *empty*, so
they break the moment you fill them in the obvious way.

```toml
# WRONG: authors.0 | Input should be a valid dictionary or instance of Author
[task]
authors = ["Jane Doe"]

# RIGHT
[[task.authors]]
name = "Jane Doe"
```

```toml
# WRONG: verifier.collect.0 | Input should be a valid dictionary or instance of
#        VerifierCollectConfig
[verifier]
collect = ["/app/figure.png"]
```

`collect` is a list of **shell commands**, not files. To pull files out of the
container, use the top-level `artifacts` list: `artifacts = ["/app/figure.png"]`.

## An empty task scores 1.0

A `harbor init` scaffold you changed nothing in returns **1.0** with `-a oracle`,
because the scaffold **fails open**: empty `instruction.md`, a `solve.sh` that is
one comment, and `tests/test_outputs.py` containing `def test_outputs(): pass`.
A passing no-op test writes `1` to `reward.txt`. The untouched scaffold therefore
reports 1.0 even though its no-op test verifies nothing.

Every task you submit must fail **closed**: an unimplemented solution must score
0. (`harbor/template/` here does fail closed; if it scores 1.0 you have
implemented something or broken the test.) Prove both directions before you
believe any result:

```bash
uv run harbor run -p <task-dir> -a oracle --job-name t-oracle   # must be 1.0
uv run harbor run -p <task-dir> -a nop    --job-name t-nop      # must be 0.0
```

If `-a nop` scores anything but 0, your verifier is decorative.

## Other `harbor init` annoyances

It copies its template directory wholesale, so a stray `tests/__pycache__/`
that exists in the installed harbor package is copied into your new task too.
A clean 0.23.0 install does not have one; check, and delete it if it is there.

The generated and packaged templates use different timeout defaults. `harbor init`
sets the verifier, agent and build timeouts to 600 seconds. The packaged
reference template sets the verifier and agent timeouts to 900 seconds and the
build timeout to 600 seconds. Neither set is authoritative; choose values
appropriate for your task. `harbor/example/` uses
600.0 for the verifier, 900.0 for the agent and 900.0 for the build, and says why
in its `task.toml`.

## The first run looks hung

Nothing is wrong: the first run pulls the base image and runs every Dockerfile
`RUN` layer, which pip-installs matplotlib, pandas, numpy, Pillow and pytest.
**That build needs network access** — `network_mode = "no-network"` applies to
the run, not the build.

Cold: **minutes**, with long silent stretches. Warm: **~15 s** end to end
(measured 12–16 s across six runs on an Apple-silicon Mac; the pytest phase
itself is 1.2–1.7 s of that). Add `--debug` to watch it, or do the cold build
before you are in a hurry:

```bash
docker build -t probe harbor/example/environment
```

## `jobs/` appeared somewhere unexpected

`--jobs-dir` defaults to `jobs`, resolved relative to **CWD** — not to the `-p`
task directory. Run everything from the release root (as these docs do) or pass
`-o ~/harbor-jobs`.

Then **add `jobs/` to the release root's `.gitignore` yourself.** Running from
the release root puts job output at `./jobs/`, and nothing ignores it there:
`harbor/.gitignore` only covers `harbor/jobs/`, which is not where it lands.
Job directories carry full container artifacts and do not belong in your
submission.

## Where the reward and the pytest log actually are

```text
jobs/<job-name>/result.json                    # reward_stats across trials
jobs/<job-name>/job.log
jobs/<job-name>/<trial>/result.json            # this trial's reward
jobs/<job-name>/<trial>/verifier/reward.txt    # literally "1" or "0"
jobs/<job-name>/<trial>/verifier/pytest.log    # which assertion failed, and why
jobs/<job-name>/<trial>/verifier/ctrf.json
jobs/<job-name>/<trial>/verifier/test-stdout.txt
jobs/<job-name>/<trial>/trial.log              # the whole trial
jobs/<job-name>/<trial>/agent/                 # what the agent did
jobs/<job-name>/<trial>/artifacts/app/...      # your `artifacts` files, under their container path
jobs/<job-name>/<trial>/artifacts/manifest.json  # per-artifact "ok"/"empty"/"failed"
```

There is **no `logs/` level** in that path, and `<trial>` is named after the task
**directory** you passed to `-p` plus a random suffix — not after the `name` in
`task.toml`. So `-p harbor/example` gives trial directories called
`example__<suffix>`, e.g. `example__zfCZRMP`, and the reward is at
`jobs/example-oracle/*/verifier/reward.txt` — one glob, not two.

One trial directory per trial; default concurrency is `-n 4` at a time.

## `reward.txt` says nothing, or the file is missing

The reward is the value that `tests/test.sh` writes to
`/logs/verifier/reward.txt`. Each trial receives one score: `1.0` if solved and
`0.0` otherwise. There is no partial credit or alternate scoring channel. If
`test.sh` exits without writing this file — for example, because of an unguarded
`set -e` — harbor cannot grade the trial.

## `harbor check` is not part of this assignment

It needs an LLM API key (there is no course-provided one), and its reward is
**1.0 whenever the reviewer emits well-formed JSON** — including a response with
all 11 criteria marked `"fail"`. It is a source of suggestions, not a gate.
Trust the runs instead: `-a oracle` → 1.0 is the graded bar, and `-a nop` → 0.0
is the recommended fail-closed check.

Related: its default rubric includes a `test_deps_in_image` criterion that wants
test-only dependencies installed by `tests/test.sh` at run time. That is
structurally incompatible with `network_mode = "no-network"`. A no-network task
is right and that criterion does not apply to it. Do not "fix" it.
