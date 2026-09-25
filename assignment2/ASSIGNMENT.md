# 11-768 Assignment 2: Evaluating a Data-Visualization Agent

## Overview

Robust evaluations are critical to the agent development process, allowing us to determine how capable or reliable agents are before deploying them into the real world. However, the complexity of agentic systems and the long timespan of tasks upon which we evaluate agents present many new complications in developing evaluations (especially compared to pre-agentic language model evaluations). In this assignment, you'll get hands-on experience designing evaluation tasks and evaluating agent trajectories, giving you a better sense of the challenges present in evaluation development.

This assignment is centered around **data-visualization agents**: LLM agents that, given access to data and a user-specified spec, can produce visualizations of that data for the user. For this assignment, you'll first build a validator to score the output of data visualization agents. Given a user task, the agent trajectory, and the final output figure, you'll need to validate whether the agent was correct, or diagnose any failures during the process. You'll then design additional tasks to probe the strengths and weaknesses of the data visualization agent and strengthen your existing evaluations. The goal of this assignment is to design a validator that generalizes to a private set of agentic trajectories, upon which you'll be graded. During grading, your validator evaluates one run at a time. It receives no ground-truth label, reference figure, or other candidate runs: just the trajectory and output figure from the agent.

## Initial setup

From the student release directory, install the environment:

```bash
uv sync
```

During development, you'll run your validator model in your own Modal workspace using the Modal credits provided by the course. Authenticate the Modal CLI and deploy the validator endpoint:

```bash
uv run modal setup
scripts/deploy_validator_model.sh
```

The deploy command prints an endpoint URL. Create a proxy token for your Modal workspace, then configure the OpenAI-compatible client:

```bash
cp .env.example .env
# Edit .env with your endpoint URL (including the /v1 suffix) and proxy token.
```

The proxy token is only needed when calling the endpoint, so you can run Modal setup and deploy before creating it. Do not commit `.env`, proxy tokens, or other credentials. The validator model we'll work with is **Qwen/Qwen3-VL-30B-A3B-Instruct-FP8** - you may not replace it or call another model from your validator. Your validator should therefore be designed to generalize rather than depend on a strong judge model. We'll grade your assignment by calling your validator using a deployment of this same model. Note that it takes ~5-10 minutes for the GPU container to load the model if you're building a new image.

### Evaluation format

You will implement `validate(run)` in `validator/solution.py`. For each run, it receives the task, input data, agent trajectory, and final figure, and returns a list of errors. An empty list means the run is acceptable. Each error contains one of four fixed families and specific evidence grounded in the run:

| Family | Meaning |
| --- | --- |
| `execution_failure` | The agent failed to produce a valid figure. |
| `wrong_data` | The plotted data does not match what was requested. |
| `wrong_chart` | The figure does not follow the requested chart design. |
| `hard_to_read` | The rendered figure is difficult or impossible to read. |

`execution_failure` is terminal in the ground truth: when the human label says
there is no valid figure, the other three families are excluded for that run,
so it is counted in none of their TP, TN, FP, or FN. A validator prediction of
`execution_failure` does not exempt the run from the other categories.
`validator/prediction.py` defines the exact output format, and
`validator/baseline.py` provides a complete example.

Each category is scored separately as a binary problem over the runs evaluated
for it. A run is a positive for a category when the ground truth lists that
family, and a prediction is positive when the validator's error list names it;
a run with several errors is a positive in each listed category. Counting true
positives (TP), true negatives (TN), false positives (FP), and false negatives
(FN) over the evaluated runs gives the Matthews correlation coefficient (MCC):

$$
\mathrm{MCC}=\frac{TP\cdot TN-FP\cdot FN}
{\sqrt{(TP+FP)(TP+FN)(TN+FP)(TN+FN)}}.
$$

MCC is 1 for perfect classification, 0 for no correlation, and negative for
inverse correlation. Scores remain in [-1, 1], including negative values. The
overall `macro_mcc` is the unweighted mean of all four category MCCs; its
denominator always remains four.

When the ground truth contains both classes but predictions are constant, MCC
is 0. When a category's ground truth lacks either class, the scorer reports MCC
0 by convention and includes an insufficient-support flag plus positive and
negative support counts. Small self-authored datasets can easily have
insufficient support because a category may never occur, or may occur on every
evaluated run. Interpret such category scores cautiously. The private grading
set will contain both classes in every category, so this convention cannot
affect official grades. MCC measures classification only; the quality of the
evidence in validator explanations is assessed separately.

### What counts as each error

The four families are binary decisions, and a run may carry several of them at once. This is the full list of what the labels in the seed set and the hidden evaluation set count under each family.

**`execution_failure`.** The agent failed to produce a valid figure in the end. This family always appears alone.

**`wrong_data`.** What is drawn is not the data the instruction asked for:

- *Wrong values.* Plotted numbers, positions, or derived quantities differ from the requested data or formula: wrong aggregation, scaling, or normalisation; a function or field sampled over the wrong range or grid; a bubble size, colour value, or error bar that should encode the data but does not.
- *Missing data.* A requested series, category, group, panel's data, or data point is not drawn, or a dimension of the data is dropped (a 3D quantity plotted with one variable missing).
- *Wrong selection.* The wrong subset, column, or filter was used, or series that were not requested are mixed in with the requested ones.
- *Wrong order.* Points, bars, categories, or sequences appear in a different order from the one requested: unsorted when sorting was asked for, a sequence reversed or shuffled, panels that do not show the data they were assigned.

**`wrong_chart`.** The data is right but the requested chart design is not followed. Whenever the instruction asked for it, we count:

- *Chart type and projection.* Wrong chart type (a line for a bar chart, no pie), grouped bars for stacked, vertical bars for horizontal, 3D requested but drawn in 2D, polar projection missing, contour or surface missing, twin axes missing or used when forbidden, a zoomed inset or its connector lines missing.
- *Layout.* Wrong number or arrangement of subplots, wrong figure size or DPI, panels that do not share the axes they were asked to share.
- *Axes.* Missing or wrong x, y, or z axis label; wrong exact title or label text; wrong axis limits (not starting from zero, wrong range, limits that cut off requested data); wrong axis scale (linear for log, non-log contour levels); ticks or tick labels shown when asked to be hidden; wrong tick labels or tick-label rotation; spines visible when asked to be hidden; grid missing.
- *Legend, colour bar, and annotations.* Legend missing; colour bar missing or not matching the data; a requested annotation or marked point missing or placed at the wrong location; a requested function label or bar value label missing; a requested formula not rendered; the wrong region shaded.
- *Style.* Wrong or forbidden colormap (a non-uniform one when a perceptually uniform one was requested); wrong line style (solid for dashed or dotted); wrong marker shape; wrong colour for a named series; areas not filled; whiskers, median markers, connector lines, or boxes missing; polygons not closed; requested line offsets not applied.
- A required text element (title, axis label) that falls *entirely* outside the saved image counts as missing, and therefore as `wrong_chart`.

**`hard_to_read`.** The figure is drawn as requested, but a reader cannot read it, or can read it only with difficulty:

- *Clipped text.* A title, axis label, tick label, or annotation is partly cut off by the edge of the image (a label cut in half is `hard_to_read`; one that is entirely outside the image is `wrong_chart`, see above).
- *Overlapping text.* Tick labels, annotations, titles, or labels overlap one another, or markers are drawn on top of the text that labels them.
- *Elements covering content.* A legend, annotation, or text box hides data, labels, or other text. A legend sitting over empty space is fine.
- *Low contrast or invisible content.* Text or value labels with a contrast ratio below about 2.5:1 against their background; a series drawn in the background colour, with zero width, or otherwise invisible.
- *Indistinguishable data.* Two series or groups that must be told apart are drawn with the same, or nearly the same, colour, line style, and marker; a colormap that merges values that should look different.
- *Squeezed layout.* Data, boxes, or panels crushed into an unreadable sliver by axis limits or by axes that overlap each other.

## Part 1: Examine seed agent runs

We've provided some seed agent runs under `artifacts/<run_id>/`. Each run subdirectory contains `result.json` (which includes the task specification, the full agent trajectory, and the outcome of the agent run), as well as `figure.png` (the final chart, if the agent was able to produce one). `run_id` is the only unique key: several runs can share a `task_id`, so index anything by `run_id`. You also have access to a simple VLM-based validator in `validator/baseline.py`. You can run the baseline validator on all existing runs with:

```bash
uv run python -m validator.runner \
  --solution validator.baseline \
  --artifacts artifacts \
  --out output/baseline_predictions.json
```

The baseline first sends the full evidence. If the model rejects a request for
exceeding its context window, it warns and retries once with shorter excerpts
of the trajectory and input files, retaining their beginnings and ends.
The fallback uses the server's tokenizer and reported context limit to budget
50% of the context for text and the response, leaving the rest for the image
and formatting. `CONTEXT_FRACTION` in `validator/baseline.py` controls this fraction;
there is no fixed context size or progressively shrinking retry loop.
The task and figure remain intact, and omissions are marked in the prompt.
This fallback can lose relevant evidence; it does not guarantee the same judgment
as the full run. If the compacted request still does not fit, or the server's
tokenizer endpoints are unavailable, the error is propagated. This is only the
baseline's approach: you can customize context management in
`validator/solution.py` however you like.

We've provided ground-truth human labels for the seed agent runs in `seed_labels.json`. Score the baseline predictions with:

```bash
uv run python -m workflow score \
  --labels seed_labels.json \
  --predictions output/baseline_predictions.json
```

First, compare the ground-truth labels and validator labels. Report all four per-family MCC scores and macro-MCC, then identify two common types of validator error, each appearing in at least two agent trajectories (include the run ID for all trajectories). For each type, describe the observable evidence and propose a change to the validator that might catch this class of error.

## Part 2: Improve your validator

Implement the two proposed changes to the default validator from Part 1. Record the changes you made and your modified validator's performance on the seed agent runs, and compare it to the baseline validator. It's okay if the performance didn't improve significantly at this step; we'll have time later to continue to improve the validator. You should report all four of the new validator's per-family MCC scores and macro-MCC and report qualitatively whether your changes actually helped mitigate the error types you surfaced in Part 1. Specifically, you should identify at least one false positive and one false negative case, and attempt to explain what caused these errors and what that might imply is missing from your validator.

Implement your changes in `validator/solution.py`, then run the modified validator on the released seed runs:

```bash
uv run python -m validator.runner \
  --artifacts artifacts \
  --out output/pre_iteration_seed_predictions.json
uv run python -m workflow score \
  --labels seed_labels.json \
  --predictions output/pre_iteration_seed_predictions.json
```

The validator model is fixed: you may not replace the actual model the validator uses or call any other models, so try to design a validator that is model-agnostic. Otherwise, you may customize `validator/solution.py` however you'd like, as long as the `validate(run)` function signature and the output schema in `validator/prediction.py` remain fixed. Note that you'll need to evaluate using the input data, final output, and agent trajectory; the baseline validator shows how to call the model with all three.

## Part 3: Design new evaluation tasks

You should now have an improved validator based on your qualitative observations from Part 1. Identifying potential errors from reading real agent trajectories is one common way in which we can improve validators. Another method is to test the validator on out-of-distribution data, to measure its robustness to new task types. In this section, you'll design your own visualization tasks to stress-test your validator's performance.

First, read through your current student validator implementation, and identify two types of visualization tasks that it may have trouble generalizing to. Write five visualization tasks (including at least two for each class of task identified), run the provided agents on them, and label the results according to the four error families above. If you need custom data for your visualization task, you may either use an LLM to synthetically generate data or reuse data from another visualization task. You should then run your validator on the new agent trajectories and report all four per-family MCC scores and macro-MCC on these adversarial cases. You should not hard-code public task IDs or labels.

The provided agent models are fixed:

- **Qwen/Qwen2.5-Coder-3B-Instruct**
- **mistralai/Ministral-3-14B-Instruct-2512**
- **zai-org/GLM-4.7-Flash**

Run every new task once with each provided agent, producing at least 15 self-authored agent runs in total. Human-review every resulting run using the same evidence standard defined above. In your report, analyze which failures reflect weaknesses in the visualization agents and which reflect weaknesses in your validator.

### Before you start Part 3

```bash
scripts/deploy_generation_models.sh
# Copy the three printed URLs into the GENERATION_* settings in .env,
# append /v1 to each URL, and set GENERATION_API_KEY.
scripts/deploy_agent_runner.sh
```

Note that agents are limited to at most 20 agent steps, 120 seconds per shell command, and 15 minutes of total walltime. Deployment troubleshooting is in `infrastructure/README.md`.

### Authoring tasks

Create one directory per task under `tasks/<task_id>/`:

```text
tasks/<task_id>/
  task.json
  inputs/                 # optional; any task-local input files
```

Its `task.json` descriptor has exactly these fields:

```text
{
  "task_id": "sales-by-region",
  "task_class": "multi-series aggregation",
  "instructions": "Using matplotlib, read sales.csv and ... Save figure.png.",
  "inputs": [
    {"name": "sales.csv", "path": "inputs/sales.csv"}
  ]
}
```

`task_id` must match its directory name and contain only letters, digits, periods, underscores, and hyphens. `task_class` names one of the two weakness classes you identified; use the same value for tasks in the same class. `instructions` must fully specify the chart and should make correctness human-reviewable. Each input `name` is the plain filename the agent sees; `path` is relative to the task directory. Paths may not be absolute or contain `..`. Use an empty `inputs` list when the prompt contains all data. The released runs under `artifacts/` provide examples of task instructions and inputs. Your tasks should not include any additional packages other than those included in the existing environment (matplotlib, numpy, pandas, Pillow, scipy, and seaborn); the private set will also not require you to consider tasks that require the agent to use any additional packages.

Validate all descriptors and referenced files before generating runs:

```bash
uv run python -m workflow validate-tasks
uv run python -m workflow generate
```

Runs are resumable: existing task/model runs are skipped. To regenerate existing runs, add `--force`; to run a subset during development, add `--models qwen`, `--models ministral`, or `--models glm`.

Each generated run is written in this layout:

```text
runs/<task_id>__<agent>/
  result.json             # task, agent identity, and complete trajectory
  inputs/                 # copies of this run's task inputs
  figure.png              # present when the agent left an output file
```

Run your validator on the generated runs:

```bash
uv run python -m validator.runner \
  --artifacts runs \
  --out output/pre_iteration_authored_predictions.json
```

### Human labels and scoring

Create `labels.json` with one blank entry for every generated run:

```bash
uv run python -m workflow init-labels
```

Then human-review every run. In each entry, replace `"errors": null` with `[]` if the run is acceptable, or with a list of `{family, evidence}` errors if it is not. Every error requires specific evidence, and `execution_failure` must appear alone. See `labels.example.json` for examples.

Validate coverage and schema, then report all four family MCC scores and macro-MCC:

```bash
uv run python -m workflow validate-labels
uv run python -m workflow score \
  --predictions output/pre_iteration_authored_predictions.json
```

### Package your tasks as Harbor environments

[Harbor](https://github.com/harbor-framework/harbor) is an evaluation harness that has recently become an industry standard for agent benchmarks since it was popularized by Terminal-Bench 2.0. Harbor defines tasks as self-contained directories which define sandboxes and evaluation criteria that any agent can be run against. In this part of the assignment, we'll package our tasks (which currently only support our internal `workflow generate`) in Harbor format so they can be run by anyone. Because Harbor tasks require deterministic verifiers, you may need to add more features to each of your private tasks, but you should not redesign the actual content of the task. Specifically, you must require agents to write `plot.py` and `plotted_values.json`, which your original task did not require. Keep any such addition inside `harbor/tasks/<task_id>/`. See `harbor/README.md` for more details about this section of the assignment.

Start by looking over the synthetic worked example in `harbor/example/` to get a sense of the requirements. You should run it both against the example's reference solution and against a do-nothing agent.

```bash
uv run harbor run -p harbor/example -a oracle --job-name example-oracle   # reward 1.0
uv run harbor run -p harbor/example -a nop    --job-name example-nop      # reward 0.0
```

You should then run at least one of the four deliberately wrong example solutions in `harbor/example/mutants/`. Three score 0.0; `illegible/` scores 1.0 because the verifier misses that its chart is too small to read. See `harbor/example/README.md` for the command that swaps in a mutant and reruns the Harbor verifier. You'll then package each of your own tasks. You can run the following command to initialize your Harbor tasks from the private tasks that you already wrote (specifically, it copies the Harbor template into a new `harbor/tasks/<task_id>/` directory for each of your previous tasks, then fills in some boilerplate information and the initial `instruction.md`). **Do not edit the seeded prompt after generating runs.**

```bash
uv run python -m workflow package
```

For each of your private tasks, you'll need to implement the deterministic checks in `harbor/tasks/<task_id>/tests/test_state.py`, a reference solution in `harbor/tasks/<task_id>/solution/solve.sh`, and anything else the scaffold left as "Required Outputs". Check each task before spending a Docker cycle on it, then confirm your reference solution actually passes:

```bash
uv run python harbor/preflight.py harbor/tasks/<task_id>
uv run harbor run -p harbor/tasks/<task_id> -a oracle --job-name <task_id>-oracle
```

To complete this section, you must get every packaged task to score 1.0 against your reference solution. Across all of your packaged tasks, you must also write **two** mutant solutions total, as `harbor/tasks/<task_id>/mutants/<name>/solve.sh`. They may belong to the same task or to different tasks. Both give a plausible wrong answer; what separates them is what the verifier does with each. One must **score 0**: your checks reject it. The cheap route there is the `plotted_values.json` you are already required to ask for -- derive the expected numbers by hand, write them into the test file as literals, and compare, and any mutant that changes a number then fails. The other must **score 1.0**: a genuinely wrong answer your checks wave through. This mutant should expose a real limitation of the verifier. For example, a chart can contain the correct data and labels but remain unreadable because it uses 2pt text on a small canvas. `harbor/example/mutants/illegible/` is a worked version that scores 1.0 against the strongest verifier in the handout. `check-submission` runs all of these, so none of it is something you can report without having run it. In the report, give each mutant's reward, what it gets wrong, and either the assertion that caught it or why nothing could have. The second mutant is the point of this part: it is where you measure, rather than being told, the boundary that your VLM validator exists to cross. `harbor/TROUBLESHOOTING.md` covers the errors you are most likely to hit, including the one where an invalid `task.toml` is reported as "no task found".

## Part 4: Iterate on your design

Using your results from Part 3, you should make at least one additional improvement to your validator. Evaluate the final validator on both the seed tasks and your new tasks, and report all four new per-family MCC scores and macro-MCC along with a qualitative analysis of whether this change led to improvements on your hand-written tasks. Similarly to the previous part, you should identify at least one false-positive and one false-negative, including any relevant text from the trajectory and a hypothesis for why the validator was incorrect.

Run the final validator on both sets of trajectories:

```bash
uv run python -m validator.runner \
  --artifacts artifacts \
  --out output/final_seed_predictions.json
uv run python -m validator.runner \
  --artifacts runs \
  --out output/authored_predictions.json
uv run python -m workflow score \
  --labels seed_labels.json \
  --predictions output/final_seed_predictions.json
uv run python -m workflow score \
  --predictions output/authored_predictions.json
```

You can make additional improvements to the validator or design more tasks after this step, as you will be partially graded based on the performance of your final validator on a private test set. Please report all additional changes made to your validator in the report, as well as the motivation behind including them and how successful you judged them to be (qualitatively and quantitatively).

## Submission and grading

Submit:

```text
validator/solution.py   # final validator implementation
output/                 # predictions for the seed and self-authored runs
tasks/                  # five or more self-authored tasks and their inputs
runs/                   # all three fixed-agent runs for every authored task
labels.json             # one human-reviewed label per self-authored agent run
harbor/tasks/           # each authored task packaged as a Harbor environment,
                        #   including the two mutant solutions
report.pdf              # compiled report
report.tex              # report source
AI_USAGE.md             # declared use of AI tools (not graded)
```

Before submission, run the end-to-end structural check:

```bash
uv run python -m workflow check-submission
```

It verifies the required files, validates every task and input, requires at least five tasks spanning at least two `task_class` values with two tasks per class, requires exactly one run from each fixed agent per task, and checks that `labels.json` covers those runs exactly once. It also checks the Harbor packaging, in two stages. Structurally: one `harbor/tasks/<task_id>/` per authored task and no extras, the full `harbor/template/` layout in each, the template sentinel gone from each task's reference solution and verifier, no TODO markers left in its `instruction.md`, that `instruction.md` still carrying its descriptor's prompt verbatim and asking for `plot.py` and `plotted_values.json`, and two mutants total under `harbor/tasks/<task_id>/mutants/<name>/solve.sh`. It reports every fault in every task at once. Then it runs Harbor and holds the rewards to the contract: every packaged task must score 1.0 with `-a oracle`, one mutant must score 0, and one mutant must score 1.0. It prints the rewards it read, and a failure names the `jobs/check-submission-<job>/<trial>/verifier/pytest.log` that explains it. That stage needs Docker and takes a few minutes; `--skip-harbor-runs` stops after the structural half, which is what you want while iterating. It does not judge label correctness or report quality; those still require human review. Use `report_template.tex` as the starting point for your final `report.tex`. The report should answer every question in Parts 1--4 and contain enough detail to reproduce your experiments.

You should also include an AI_USAGE.md file. This should detail your use of any AI technologies for this assignment. List all the tools you used, and provide a clear description of how you used each of these tools. If you did not use any AI assistance, declare that in this file. We will not grade your submitted AI_USAGE.md file, but we will check your understanding of the code you submitted through a quiz (details of which have been posted on Piazza).

Part of your grade will depend on your submitted validator's macro-MCC on a private set. The private set may include task and chart types that do not appear in the seed runs, so avoid designs that overfit the public examples.

| Weight | Component |
| ---: | --- |
| 40% | Report and design rationale |
| 30% | Based on Validator macro-MCC on the private set |
| 20% | Quiz / comprehension check |
| 10% | Code quality and reproducibility |
