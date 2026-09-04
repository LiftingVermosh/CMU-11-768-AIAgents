# Token Usage Analysis: Context Compaction vs Full Context

**Instance:** `django__django-15368` (django/django @ e972620ada4f)
**Model:** `deepseek-v4-flash-vision-exp` (course OpenAI-compatible endpoint)
**Task:** run the vendored SWE-bench instance under two conditions:

| condition | configuration |
|---|---|
| compaction | `--compact-threshold-tokens 6000`, keep recent 1 step, summary budget 1,200 tokens |
| baseline | no compaction flag (full raw context, `COMPACT_THRESHOLD=0`) |

Token counts below come from the `usage.prompt_tokens` / `usage.completion_tokens` fields
recorded on each action request in the saved trajectories; the compaction events also
store a `rough_message_tokens` estimate (chars/4) before and after each compaction.

## Results

| metric | compaction | baseline |
|---|---|---|
| ReAct steps | 36 | 48 |
| compactions triggered | 6 | 0 |
| total prompt tokens | 142,535 | 1,224,005 |
| total completion tokens | 5,771 | 14,539 |
| total tokens | 148,306 | 1,238,544 |
| mean prompt tokens / step | 3,959 | 25,500 |
| max prompt tokens / single step | 6,525 | 42,493 |
| resolved | yes | yes |
| FAIL_TO_PASS | 1/1 | — |
| PASS_TO_PASS | 29/29 | — |

The compacted patch passes a fresh-testbed replay of the instance's tests; the baseline
run also resolved the issue. The compacted run used fewer steps (36 vs 48), but step
count is stochastic run-to-run; the token difference is the robust observation.

## Observed trends

**Full-context prompt grows almost monotonically.** Each ReAct step appends the whole
assistant message plus its tool observation to the history and never removes anything,
so the per-step prompt length rises linearly with the step index (1,577 → 42,493 over
48 steps). Because every step re-sends all earlier history, cumulative prompt cost is
roughly quadratic in the number of steps (Σ of step lengths ≈ 1.22M tokens for 48 steps).

**Compacted prompt follows a sawtooth.** The agent lets the context grow toward the
6,000-token threshold, then a compaction condenses the old prefix into a short
model-written working memory while keeping the system/task messages and the most recent
complete tool step. Six compactions fired (steps 5, 10, 15, 21, 24, 32), each cutting the
estimated context from ~5,200–5,700 tokens down to ~1,200–2,200:

| step | est. before | est. after | Δ |
|---|---|---|---|
| 5 | 5,466 | 1,509 | −3,957 |
| 10 | 5,228 | 1,674 | −3,554 |
| 15 | 5,567 | 1,195 | −4,372 |
| 21 | 5,681 | 2,178 | −3,503 |
| 24 | 5,468 | 1,546 | −3,922 |
| 32 | 5,621 | 1,563 | −4,058 |

As a result the per-step prompt stays bounded (max 6,525, well under the threshold) and
the cumulative cost is roughly linear in the number of steps rather than quadratic:
~143k prompt tokens for 36 steps, an **88% reduction** over the baseline total
(~8.6× less). Per-step means are 3,959 vs 25,500 tokens.

The six summarization calls are themselves extra API traffic and are deliberately not
recorded under action-request usage. Upper-bounding each at ~5.5k prompt (its input was
the ~5.2–5.7k context being summarized) plus ≤1.2k completion adds at most ~40k tokens,
which still leaves the compacted run several times cheaper than the 1.24M-token baseline.

## Why the trends appear

Full-context replay is simplest to implement and keeps every observation verbatim, which
means nothing is ever lost — but the cost grows quadratically and the agent eventually
hits the context window on long-horizon tasks. Compaction trades away that verbatim
history: an older prefix is replaced by a condensed, factual working memory (objective,
constraints, files, commands, results, failures, blockers, next action), so only the most
recent step plus the summary stay in the window. That bounds each prompt to roughly the
threshold and makes total cost grow roughly linearly.

## Tradeoffs between the two conditions

- **Cost & latency.** Compaction is dramatically cheaper on tokens (and hence wall-clock
  and spend): ~88% fewer prompt tokens here. This is the main win for long agents.
- **Horizon.** Because the window stays bounded, a compacting agent can keep going far
  past the point where a full-context agent would overflow its context window.
- **Fidelity / risk of loss.** The summary is lossy. If the model compresses poorly it may
  drop a concrete error message, exact output, or an earlier failed approach, and the
  agent may re-investigate something it already knew, or act on a distorted summary. Full
  context never has this failure mode.
- **Overhead & sensitivity.** Each compaction adds a model round-trip and a chance of a
  bad summary; aggressive settings (very low threshold, few retained steps) can discard
  useful recent detail. Here, compressing about every five steps and keeping one complete
  recent turn was sufficient — the compacted run still produced a passing patch — but on
  harder tasks the right threshold/summary-fidelity balance would need tuning.
- **Interpretability.** Full-context trajectories are trivially auditable (raw prompts are
  logged); compacted trajectories need the stored working-memory summaries and compaction
  events to reconstruct what the agent was acting on.
