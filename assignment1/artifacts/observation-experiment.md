# Observation A/B Experiment: Board-Only vs Board + Legal Moves
# 观察条件 A/B 实验:纯棋盘 vs 棋盘 + 合法走法列表

**Task / 任务:** compare how the tool interface affects a chess agent's behavior by giving
it the same game under two observation conditions: (1) board-only (no legal moves), and
(2) board plus a `legal_moves` list. ChessAgent plays White; the server's deterministic
bot replies after every legal White move.

通过在同一棋局上给 agent 两种观察条件,比较工具接口如何影响其行为:(1) 纯棋盘(不含
合法走法),(2) 棋盘外加 `legal_moves` 列表。ChessAgent 执白,服务器用确定性 bot 在每次
合法白棋后自动应手。

**Models / 模型.** The course OpenAI-compatible endpoint previously used
`openai/gpt-oss-120b`, which has since been removed (it now serves only
`deepseek-v4-pro`, `deepseek-v4-flash`, and `deepseek-v4-flash-vision-exp`). The two model are therefore:

课程 OpenAI 兼容端点此前提供的 `openai/gpt-oss-120b` 已下线(现仅支持 `deepseek-v4-pro`、
`deepseek-v4-flash` 与 `deepseek-v4-flash-vision-exp`),因此模型如下:

| leg / 组 | model actually run / 实际运行的模型 |
|---|---|
| "deepseek" | `deepseek-v4-flash-vision-exp` |
| "gpt-oss" (substituted / 替补) | `deepseek-v4-flash` |

> 梁圣的恩情还不完 🖐️ 😭 🖐️

**Metrics / 指标** are extracted from the saved artifacts: `play_move` calls from the action
requests recorded in each trajectory, calls rejected by the server (illegal moves) from
the `<chess_error>` tool observations, and the final `game_over`/history from each
`*-result.json`.

从保存的产物中提取:每次轨迹记录的动作请求得到 `play_move` 调用次数,`<chess_error>`
工具观察得到被服务器拒绝(非法)的调用数,各 `*-result.json` 给出最终 `game_over` 与回合史。

## Results / 结果

| run (file tag / 文件标记) | model / 模型 | observation / 观察条件 | play_move calls / 次数 | rejected as illegal / 非法拒绝 | invalid-move rate / 非法率 | legal White moves / 合法白棋落子 | outcome / 结果 | half-moves / 半回合 |
|---|---|---|---|---|---|---|---|---|
| no-legal-moves-deepseek | deepseek-vision | board only / 纯棋盘 | 31 | 2 | 6.5% | 28 | Black wins / 黑胜 | 58 |
| legal-moves-deepseek | deepseek-vision | + legal moves / 加合法走法 | 22 | 0 | 0.0% | 21 | White wins / 白胜 | 43 |
| no-legal-moves-gpt-oss | deepseek-v4-flash | board only / 纯棋盘 | 17 | 1 | 5.9% | 15 | White wins / 白胜 | 31 |
| legal-moves-gpt-oss | deepseek-v4-flash | + legal moves / 加合法走法 | 26 | 0 | 0.0% | 25 | White wins / 白胜 | 51 |

All four runs reached `game_over: true`; none hit the step limit. In every run each step
produced exactly one `play_move` call (call count = step count), so the games show no
recovery stalls or wasted turns — the only difference between cells is which moves were
actually legal.

四局全部到达 `game_over: true`,无一触发步数上限。每局每一步恰好产生一次 `play_move`
调用(调用数 = 步数),因此对局中没有空转或无效回合 —— 各格之间的唯一差别是哪些走法真正合法。

## Findings / 发现

**Giving the model `legal_moves` eliminates illegal moves. / 给模型 `legal_moves` 后非法走法降为零。**
In the two board-only runs the agent attempted illegal moves 6.5% (vision) and 5.9%
(flash) of the time, and those attempts were rejected as `<chess_error>` before the agent
tried again. With the `legal_moves` list present, both models made 0 illegal attempts
across the whole game. Providing legal moves lets the model spend every action on a real
move rather than on probe-and-correct cycles.

两局纯棋盘跑中,agent 分别有 6.5%(vision)与 5.9%(flash)的走法尝试非法,被
`<chess_error>` 拒绝后 agent 再试。而在带 `legal_moves` 的条件下,两个模型整局非法尝试均为
0。提供合法走法让模型把每次行动都花在真实走子上,而非"试错—纠正"循环。

**Both models play better (and win) when legal moves are shown. / 显示合法走法时两个模型都下得更好并获胜。**
With legal moves shown, both the vision leg (White wins, 43 half-moves) and the flash leg
(White wins, 51) defeated the deterministic bot. Board-only, the flash leg still won
(White wins, 31) but the vision leg lost (Black wins, 58 — the longest game of the four).
On this small sample the board-only condition degrades the vision model's move quality the most.

带合法走法时,vision 腿(白胜,43 半回合)与 flash 腿(白胜,51)都战胜确定性 bot。纯棋盘下
flash 腿仍获胜(白胜,31),但 vision 腿落败(黑胜,58 —— 四局中最长)。在这个小样本上,纯棋盘
条件对 vision 模型走法质量的伤害最大。

**Condition affects how the models differ. / 观察条件决定了模型间差异的大小。**
With the extra `legal_moves` context both models finished close in game length (43 vs 51
half-moves) and both won; the interface difference dominates any model difference.
Board-only is where model behavior diverges — the vision model's win rate collapses while
the flash model is largely unaffected.

多出的 `legal_moves` 上下文使两个模型对局长度接近(43 vs 51 半回合)且都获胜,接口差异压过
模型差异。纯棋盘才是行为分化的场景 —— vision 模型胜率崩塌,而 flash 模型几乎不受影响。

## Caveats / 说明

This is four games, one per cell — a single draw from a stochastic model, not a measured
distribution. The *mechanism* (legal-moves list ⇒ zero illegal attempts) is deterministic
and robust, but the win/loss and half-move numbers are illustrative. The observation
condition is exactly the intended ablation: identical loop, identical server, differing
only in whether `legal_moves` is included in the formatted state.

本实验每格仅一局,共四局——是随机模型的一次抽样,而非统计分布。"合法走法列表 ⇒ 零非法
尝试"这一**机制**是确定且稳健的,但胜负与半回合数仅作示意。观察条件为设计好的消融:
loop 与服务器完全一致,仅区别在于格式化状态里是否包含 `legal_moves`。
