# Token Usage Analysis: Context Compaction vs Full Context
# Token 用量分析:上下文压缩(compaction)vs 全上下文

**Instance / 实例:** `django__django-15368` (django/django @ e972620ada4f)
**Model / 模型:** `deepseek-v4-flash-vision-exp` (course OpenAI-compatible endpoint / 课程 OpenAI 兼容端点)
**Task / 任务:** run the vendored SWE-bench instance under two conditions / 在两种条件下运行内置的 SWE-bench 实例:

| condition / 条件 | configuration / 配置 |
|---|---|
| compaction / 压缩组 | `--compact-threshold-tokens 6000`, keep recent 1 step, summary budget 1,200 tokens / 保留最近 1 步,摘要预算 1,200 tokens |
| baseline / 基线组 | no compaction flag (full raw context, `COMPACT_THRESHOLD=0`) / 不带压缩参数(保留全部原始上下文) |

Token counts below come from the `usage.prompt_tokens` / `usage.completion_tokens` fields
recorded on each action request in the saved trajectories; the compaction events also
store a `rough_message_tokens` estimate (chars/4) before and after each compaction.

下文 token 数取自保存轨迹中每次动作请求的 `usage.prompt_tokens` / `usage.completion_tokens`;
每次压缩事件还记录了压缩前后的 `rough_message_tokens` 估算(字符数/4)。

## Results / 结果

| metric / 指标 | compaction / 压缩组 | baseline / 基线组 |
|---|---|---|
| ReAct steps / ReAct 步数 | 36 | 48 |
| compactions triggered / 触发压缩次数 | 6 | 0 |
| total prompt tokens / 输入 token 总量 | 142,535 | 1,224,005 |
| total completion tokens / 输出 token 总量 | 5,771 | 14,539 |
| total tokens / token 总量 | 148,306 | 1,238,544 |
| mean prompt tokens / step / 每步平均输入 token | 3,959 | 25,500 |
| max prompt tokens / single step / 单步最大输入 token | 6,525 | 42,493 |
| resolved / 是否解决 | yes / 是 | yes / 是 |
| FAIL_TO_PASS | 1/1 | — |
| PASS_TO_PASS | 29/29 | — |

The compacted patch passes a fresh-testbed replay of the instance's tests; the baseline
run also resolved the issue. The compacted run used fewer steps (36 vs 48), but step
count is stochastic run-to-run; the token difference is the robust observation.

压缩组补丁在全新 testbed 上重放实例测试通过;基线组也解决了问题。压缩组步数更少
(36 vs 48),但步数本身存在随机波动;token 差异才是稳健的观察结论。

## Observed trends / 观察到的趋势

**Full-context prompt grows almost monotonically. / 全上下文的 prompt 几乎单调增长。**
Each ReAct step appends the whole assistant message plus its tool observation to the
history and never removes anything, so the per-step prompt length rises linearly with the
step index (1,577 → 42,493 over 48 steps). Because every step re-sends all earlier
history, cumulative prompt cost is roughly quadratic in the number of steps (Σ of step
lengths ≈ 1.22M tokens for 48 steps).

每一步 ReAct 都会把整条 assistant 消息连同工具观察追加进历史且从不删除,因此单步
prompt 长度随步数线性上升(48 步内从 1,577 涨到 42,493)。由于每步都会重发此前全部
历史,累计输入成本近似为步数的平方级(48 步的步长之和 ≈ 122 万 tokens)。

**Compacted prompt follows a sawtooth. / 压缩组的 prompt 呈锯齿状。**
The agent lets the context grow toward the 6,000-token threshold, then a compaction
condenses the old prefix into a short model-written working memory while keeping the
system/task messages and the most recent complete tool step. Six compactions fired
(steps 5, 10, 15, 21, 24, 32), each cutting the estimated context from ~5,200–5,700
tokens down to ~1,200–2,200:

agent 让上下文增长到 6,000 token 阈值附近后,一次压缩把旧前缀浓缩成一小段模型生成的
工作记忆,同时原样保留 system/task 消息与最近一个完整工具步。共触发 6 次压缩(步
5、10、15、21、24、32),每次把估算上下文从约 5,200–5,700 tokens 砍到约 1,200–2,200:

| step / 步 | est. before / 压缩前 | est. after / 压缩后 | Δ |
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

因此单步 prompt 保持有界(最大 6,525,远低于阈值),累计成本随步数近似线性而非平方:
36 步约 14.3 万输入 token,较基线总量减少 **88%**(约为 1/8.6)。每步均值 3,959 vs
25,500 tokens。

The six summarization calls are themselves extra API traffic and are deliberately not
recorded under action-request usage. Upper-bounding each at ~5.5k prompt (its input was
the ~5.2–5.7k context being summarized) plus ≤1.2k completion adds at most ~40k tokens,
which still leaves the compacted run several times cheaper than the 1.24M-token baseline.

六次摘要调用本身是额外 API 流量,刻意不计入动作请求的 usage。按每次输入约 5.5k
(即被压缩的约 5.2–5.7k 上下文)加上 ≤1.2k 输出上限估算,最多额外增加约 4 万 tokens,
压缩组仍比 124 万 token 的基线便宜数倍。

## Why the trends appear / 趋势成因

Full-context replay is simplest to implement and keeps every observation verbatim, which
means nothing is ever lost — but the cost grows quadratically and the agent eventually
hits the context window on long-horizon tasks. Compaction trades away that verbatim
history: an older prefix is replaced by a condensed, factual working memory (objective,
constraints, files, commands, results, failures, blockers, next action), so only the most
recent step plus the summary stay in the window. That bounds each prompt to roughly the
threshold and makes total cost grow roughly linearly.

全上下文重放实现最简单,且逐字保留每条观察、信息永不丢失——但成本呈平方增长,长程任务
最终会撞上上下文窗口上限。压缩组则牺牲逐字历史:旧前缀被替换为一段凝练的事实性工作
记忆(目标、约束、文件、命令、结果、失败、阻塞点、下一步),窗口里只保留最近一步加摘要。
于是每个 prompt 都被约束在阈值附近,总成本近似线性增长。

## Tradeoffs between the two conditions / 两种条件的取舍

- **Cost & latency / 成本与延迟.** Compaction is dramatically cheaper on tokens (and hence
  wall-clock and spend): ~88% fewer prompt tokens here. This is the main win for long
  agents. 压缩组在 token(因而墙钟时间与花费)上大幅节省:本实验输入 token 减少约
  88%,这是长程 agent 的主要收益。
- **Horizon / 任务长度.** Because the window stays bounded, a compacting agent can keep
  going far past the point where a full-context agent would overflow its context window.
  窗口保持有界,压缩 agent 能走到的任务长度远超全上下文 agent 溢出上下文窗口的点。
- **Fidelity / risk of loss / 保真度与丢失风险.** The summary is lossy. If the model
  compresses poorly it may drop a concrete error message, exact output, or an earlier
  failed approach, and the agent may re-investigate something it already knew, or act on
  a distorted summary. Full context never has this failure mode. 摘要有损。若模型压缩不当,
  可能丢掉具体报错、精确输出或某条失败尝试,agent 可能重查已知信息或基于失真的摘要行动;
  全上下文不存在此失效模式。
- **Overhead & sensitivity / 开销与敏感性.** Each compaction adds a model round-trip and a
  chance of a bad summary; aggressive settings (very low threshold, few retained steps) can
  discard useful recent detail. Here, compressing about every five steps and keeping one
  complete recent turn was sufficient — the compacted run still produced a passing patch —
  but on harder tasks the right threshold/summary-fidelity balance would need tuning.
  每次压缩都多一次模型往返并带来一次坏摘要的可能;激进配置(阈值极低、保留步数少)可能
  丢弃有用的近期细节。本实验中约每 5 步压缩一次、保留最近一个完整回合即已足够——压缩组
  仍产出通过测试的补丁——但在更难的任务上需要调阈值与摘要保真度的平衡。
- **Interpretability / 可解释性.** Full-context trajectories are trivially auditable (raw
  prompts are logged); compacted trajectories need the stored working-memory summaries and
  compaction events to reconstruct what the agent was acting on. 全上下文轨迹极易审计(原始
  prompt 全被记录);压缩轨迹需借助保存的工作记忆摘要与压缩事件,才能还原 agent 当时依据什么行动。
