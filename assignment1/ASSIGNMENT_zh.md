# 作业 1：构建 Agent Harness（智能体框架）

Agent Harness（智能体框架）提供了一种接口，使语言模型（生成可能字符串的模型）能够观察环境并采取行动。构建 Agent Harness 最流行的框架之一是 [ReAct](https://arxiv.org/abs/2210.03629)，它会在语言模型的提示词中交替穿插环境观察文本、推理/思维链以及智能体动作。在本次作业中，你将在 ReAct 框架下构建一个 Agent Harness。

在第 1 部分中，你将实现基础 `Agent` 的 ReAct 循环；该 `Agent` 会被实例化为 `CodeAgent`，在终端中行动以解决软件问题。你的 ReAct 循环应当是抽象的，并可应用于多个领域，从而让你看到 Agent Harness 的一般结构。你将实现相关机制，使你的编码智能体（coding agent）能够在终端环境中观察和行动，并应用可复用的智能体技能（agent skills）来解决问题。然后，你将让这个编码智能体修复一个国际象棋游戏应用中的问题。

在第 2 部分中，你将处理编码智能体在解决更复杂的软件问题时如何使用上下文。你将实现一种简单的上下文压缩（context compaction）方法，以管理智能体对语言模型上下文窗口的占用。

在第 3 部分中，你将使用已构建的基础 `Agent`，将其实例化为 `ChessAgent`，在你用 `CodeAgent` 修复的应用上下棋。你将实现该智能体的工具规范，使语言模型能够与运行在应用中的象棋游戏中的基于规则的机器人（bot）对弈（你可以观战！）。你还将探索程序化工具调用（programmatic tool calling），它将程序的能力引入智能体动作中，并使你的智能体能够通过 Python 代码执行来实现更复杂的策略。

三个部分的关系如下：

```text
                SWE-Bench issue
                      |
                      v
buggy chess app -> CodeAgent -> fix.patch -> repaired chess server
                                              ^
                                              |
                                    ChessAgent tools
```

<!-- 目标应用运行在 Modal 上。你的智能体及其 OpenAI 兼容模型客户端在本地运行。`run_python` 是例外：模型编写的 Python 代码运行在象棋沙盒中，与服务器相邻。 -->

<!--
## 实现清单

这里列出了每一个学生 TODO。搜索对应的 `TODO(...)` 注释以查看详细约定。

| 部分 | 文件 | 实现内容 |
|---|---|---|
| 1 | `src/assignment/agent/base.py` | `Agent.build_prompt`、`Agent.run` 中的 ReAct 部分 |
| 1 | `src/assignment/agent/code_agent.py` | `CodeAgent.execute_tool_calls` |
| 2 | `src/assignment/agent/base.py` | `COMPACTION_SYSTEM_PROMPT`、`Agent.compact_context`，以及循环中对 `maybe_compact_context` 的调用 |
| 3 | `src/assignment/agent/tools.py` | `PLAY_MOVE_TOOL`、`SIMULATE_MOVE_TOOL`、`RUN_PYTHON_TOOL` |
| 3 | `src/assignment/agent/chess_tools.py` | `_play_move`、`_simulate_move`、`_run_python`、`_invoke_skill` |
| 3 | `src/assignment/agent/chess_agent.py` | 注册启用的工具并实现 `ChessAgent.execute_tool_calls` |
| 3 | `src/assignment/agent/base.py` | `Agent.load_skills` |

不要仅仅为了让测试通过而修改提供的设施。尤其要保持 `Agent.run` 中的日志和清理代码块、`execute_python_code`、沙盒运行器、任务文件、测试和固定版本的象棋应用不变。
-->

## 提供的内容

- 位于 `src/assignment/env.py` 的、由 Modal 支撑的命令环境。
- `chess_app/` 子模块中锁定版本的象棋源码。
- `tasks/` 下的公共象棋任务和随附的 SWE-bench 实例。
- 编码智能体 `execute` 和 `finish_task` 的 schema 及其环境。
- 象棋服务器端点、状态格式化器、提示词、沙盒 Python 运行器，以及象棋搜索技能。
- 离线公共测试、可选参与的可计费 Modal 测试，以及生成产物的 CLI 运行器。

任务构建器会检查锁定的源码提交，在将目标复制到 Modal 时移除 Git 历史，并在 `/testbed` 创建一个全新的单提交仓库。编码智能体可以检查和编辑该工作树，但无法从仓库历史中恢复解决方案。

## 设置

安装 [uv](https://docs.astral.sh/uv/)，然后运行：
```bash
make setup
```
这会设置一个 Python 环境（使用 `uv`），并下载和安装相关依赖。如果两个锁定版本的 `chess_app` 源码（用于你的智能体将要处理的任务）中任何一个缺失或不在正确的提交上，该命令会失败。

本次作业将使用 [Modal](https://modal.com/)，这是一个用于运行代码的云平台。该平台允许你在云机器上安全地运行你的智能体生成的代码。你的智能体所处的环境将是远程 Modal 沙盒，并运行执行智能体动作的代码。首先，设置一个 Modal 账户（如果你还没有），并按照你将收到的说明获取 Modal 上的计算额度。然后运行
```bash
uv run modal setup
```
以登录并在你的环境中设置 Modal。

设置好 Modal 后，运行
```bash
cp .env.example .env
```
以创建包含你环境密钥的文件——主要是 LLM API 信息。如果你已注册本课程，你将收到有关如何获取 LLM 提供商额度的说明。按照说明生成 API 密钥，并确保你正确配置了服务的 base URL。

```dotenv
OPENAI_BASE_URL=<OpenAI-compatible base URL>
OPENAI_API_KEY=...
OPENAI_MODEL=deepseek/deepseek-v4-flash-0731
OPENAI_MAX_RETRIES=5
```

如上所见，默认情况下你将使用 DeepSeek-V4-Flash 模型。当有指示时，你应该使用其他模型。如果额度允许，你也可以自由探索同一提供商的其他模型，但我们希望本次作业使用此模型完成。

我们将任何会使用 API 额度（来自 Modal 或 LLM 提供商）的活动称为_可计费_活动。在整个作业中，你将运行可计费评估。我们建议你监控相关仪表盘上的使用情况，以确保合理使用 API 额度。

在进行可计费运行之前，请验证子模块、Modal 认证和模型端点，而无需启动沙盒或生成 token：
```bash
make doctor
```

_（可选）_ 如果你想测试所有 Modal 组件是否按预期运行，请运行
```bash
make test-modal
make test-chess-modal
```

一个通用提示：你可以使用
```bash
modal container list
```
检查是否有可计费的 Modal 沙盒正在运行。如果环境未正确关闭，沙盒可能会保持运行并消耗额度。你可以使用 `modal container stop <container ID>` 停止未正确终止的沙盒。

## 公共测试

`make test` 速度快、离线且不可计费。初始代码会故意让与学生 TODO 相关的测试失败。请将这些里程碑作为指南；如果添加了澄清性测试，确切的 pytest 数量可能会变化。

<!-- | 完成以下部分后 | 应通过的公共行为 |
|---|---|
| 第 1 部分循环和分发器 | 提示词历史、截断、步数限制、格式错误/未知工具、补丁提交 |
| 第 2 部分压缩 | 摘要调用、有效的保留工具对、更小的活动提示词、保存的压缩事件 |
| 第 3 部分基础象棋工具 | 严格 schema、注册、状态更新、可恢复的非法走法 |
| 第 3 部分程序化工具和技能 | 模拟隔离、沙盒 Python 执行、状态刷新、技能加载 | -->

通过公共测试并不能证明完全正确。私有测试还涵盖失败时的清理、重复/格式错误的技能、并行的象棋调用、传输错误、产物一致性、补丁重放和真实的 Modal 集成。

## 规则

- 不要修改 `tests/`、`tasks/`、`chess_app/`。
- 不要修改提供的日志/清理机制，也不要在子类中复制共享的 ReAct 循环。
- 不要为了通过测试而硬编码某个智能体任务的预期解决方案。你的智能体应为给定任务生成走法或补丁。
- **绝不要暴露、记录或提交 API 密钥等凭据。** 注意 `.env` 文件的内容。
- 在整个作业过程中，你将使用多个智能体以及这些智能体的多个版本。在任何时候，都只使用该智能体对应的预期工具集。

## 第 1 部分：构建编码智能体并修复象棋应用

共享的 `Agent` 必须实现一个传统的 ReAct 循环：构建请求、获取助手动作、执行其工具调用、添加关联的观察结果，并重复直到完成。

### 1. 构建提示词

语言模型的提示词是一系列消息，用于在交互的每一步查询语言模型。消息是一个字典对象。它至少具有 `role` 和 `content` 键，也可能包含额外信息。消息的 `content` 可以是一个字符串，也可以是一个包含推理 token 的结构化对象，或者（在本作业未涉及的情况下）图像。消息的 `role` 可以取少数几个值之一。

`system` 角色用于提供长期指令——关于领域的指令、环境信息、要遵守的规则、跨任务可能有用的通用策略等。`user` 角色提供任务信息[^1]，并在必要时提供解决任务的额外指南。`assistant` 角色消息用于表示 LLM 的生成内容，`tool` 角色消息表示作为环境观察结果的工具调用结果。你的任务是构建这些消息的序列。按照惯例，恰好一条 `system` 消息出现在最前面，并且在任何 `assistant` 消息之前有一条 `user` 消息。由于 LLM 一次只生成一个响应，`assistant` 消息后面应跟 `tool` 消息（显示工具调用的结果）或 `user` 消息。你可以在 [OpenAI API 参考](https://developers.openai.com/api/reference/python/resources/chat/subresources/completions/methods/create) 以及来自 vLLM 文档的这个[示例](https://docs.vllm.ai/en/v0.7.2/getting_started/examples/openai_chat_completion_client_with_tools.html)中找到关于这些消息结构的信息。

你需要实现 `Agent.build_prompt` 方法。给定系统提示词，以及作为 agent 类属性可访问的任务提示词，再加上你可能添加的任何额外记录信息，该方法应准备输入给语言模型的内容。如你所见，我们提供了一个 `Agent.query_language_model` 方法，它直接使用此方法的输出来查询语言模型 API。你的实现需要为该查询提供正确的输入。`Agent.query_language_model` 方法向语言模型 API 提供工具和推理参数，并返回包含所有相关信息的结构。它还维护步数——即 API 被查询的次数。API 负责将提供的提示词和工具渲染为单个 token 序列，这不需要你处理。它还提供了额外的机制来记录你的请求以供评分，你不应修改。

智能体的 LLM 客户端最多会重试 `OPENAI_MAX_RETRIES` 次临时性提供商故障。

> **TODO(1.1.a)**
> 添加用于维护智能体状态的机制，使它在采取行动并观察结果时能保持状态。构建形成语言模型提示词的消息序列。这应包含长期指令、任务说明，以及先前的交互，包括之前轮次的观察、推理和动作。注意，此方法应与领域无关，并以适用于任何继承它的领域特定智能体的方式构建提示词。

接下来，你应为 `CodeAgent` 构建系统提示词和任务提示词。系统消息必须逐字包含以下代码块，并使用环境暴露的值：
```text
<system_information>
{
  "machine": <machine>,
  "release": <release>,
  "system": <system>,
  "version": <version>
}
</system_information>
```

> **TODO(1.1.b)**
> 为 `CodeAgent` 构建系统提示词和 `task_prompt`。它们应能被 `Agent.build_prompt` 方法使用。

### 2. 运行 ReAct 循环

实现 `Agent.run` 的主体。

> **TODO(1.2)**
> 运行 ReAct 循环。编排以下过程：提示语言模型产生推理和动作，提取模型生成的工具调用，并执行工具调用以获得智能体下一步的观察结果。确保你通过设置 `Agent.finished` 来识别智能体何时完成任务。如果智能体超过 `step_limit`，则抛出 `StepLimitError`。

### 3. 执行编码工具

实现 `CodeAgent.execute_tool_calls`。编码智能体支持两个工具：`execute` 和 `send_message`。你可以[在此](./src/assignment/agent/tools.py)找到这些工具的定义。你需要实现一种让这些工具被执行的机制，并准备其输出以展示给语言模型。这些输出也是形如 `{"role": str, "tool_call_id": str, "content": str}` 的消息。每条消息都是执行其中一个工具的观察结果，其角色是一种名为 `tool` 的特殊角色。[^2] 你应该使用 `Environment.execute` 方法，确保在正确的 Modal 沙盒上执行代码。你可以让可选参数保持当前默认值，但应允许智能体在其工具调用中覆盖它们。

> **TODO(1.3)**
> 让智能体可以使用 `execute` 和 `send_message` 工具。解析每个调用，执行已识别的工具，并为每个调用返回一条消息（一次智能体响应中可能有多个工具调用！）。格式错误的 JSON 和未知工具必须变成传递给智能体的可恢复观察结果，而不是异常。

### 4. 加载技能

你可能会认为我们已经准备好让智能体处理软件问题了，但还没有！`CodeAgent` 需要知道的最后一项知识是如何提交解决方案。我们使用的具体协议是：一旦智能体解决了问题，它就将解决方案保存到一个名为 `patch.txt` 的文件中。该文件会从环境中提取出来用于评估。

为了教会智能体这个协议，我们将使用技能（skill）。技能是以专门的、可复用的工作流扩展智能体能力的方式。[Agent Skills 协议](https://agentskills.io/home) 为技能定义了一套标准，使它们能被多个智能体框架支持。`tasks/code-skills/submit-task` 定义了一个遵循该协议提交解决方案的基础技能。虽然该协议有更多你可以探索的高级特性，但本次作业你将使用一个极简技能。

你需要实现的核心特性是_渐进式披露_（progressive disclosure）。为了让智能体能够使用许多可能很复杂的技能，技能中的信息会以逐级增加的细节程度向智能体披露，智能体按需访问所需信息。对于本次作业，你将实现一种简单的渐进式披露形式：在系统提示词中向智能体提供所有可用技能的描述。你还将让智能体能够使用 `invoke_skill` 工具，智能体可以传入技能名称来查看完整技能。这样，当智能体查看完整的 `submit-task` 技能时，它就会知道如何提交修复以进行评分。我们会检查系统提示词是否提及技能名称和描述。当智能体没有可用技能时，提示词的任何部分都不应提及 `patch.txt`，也不应给出提交说明。

技能文件可在[本地](./tasks/code-skills/)获得；当智能体运行时，如果使用技能，`Agent.skills_path` 指向该位置（否则为 `None`）。注意，本次作业中智能体只会使用一个技能（`./tasks/code-skills/` 下的一个子文件夹），但原则上智能体可以使用许多技能，这使得渐进式披露更加重要和有用。

> **TODO(1.4)**
> 验证 ``skills_path``，在每个子目录中发现一个 ``SKILL.md``，解析其 YAML frontmatter（即文件头部 `---` 标记之间的内容），并返回一个以 frontmatter 中 ``name`` 为键的映射。每个值必须包含一个供模型技能目录使用的简洁 ``metadata`` 字符串，以及供 ``invoke_skill`` 使用的技能文件完整 ``content``。对于重名以及格式错误或缺失 frontmatter 的情况，抛出明确的 ``ValueError``。如果智能体有任何可用技能，请在提示词中向智能体提供它们的描述/元数据。

例如，`SKILL.md` 的 `content` 为
```
---
name: hello-world
description: Write "hello, world" to the terminal
---

echo "hello, world"
```
而 `metadata` 为
```
name: hello-world
description: Write "hello, world" to the terminal
```

### 5. 运行并检查修复

现在，让我们让智能体修复一个软件问题。

```bash
make run-code-agent
make check-part1
```

默认模型是 `deepseek/deepseek-v4-flash-0731`。智能体接收 `tasks/chess-terminal-move/problem_statement.md`，在 `/testbed` 内工作，并且必须复现、修复并验证该故障。一次运行会产生：

- `artifacts/fix.patch`
- `artifacts/part1-trajectory.json`

`make check-part1` 会将生成的补丁应用到一个全新的 testbed，并运行公共回归测试以及象棋应用测试套件。不要直接编辑 `chess_app/` 中的目标。

完成第 1 部分后，你的解决方案应通过与提示词构建、截断、步数限制、格式错误/未知工具、补丁提交相关的测试。

## 第 2 部分：实现上下文压缩

长的 ReAct 交互记录会增加成本，并最终挤占有用的上下文。随着智能体承担越来越复杂和长周期的任务，它们最终也会触及语言模型上下文窗口的极限。为了使智能体能够高效处理长时间运行的任务，我们希望只保留先前动作和观察结果中的相关信息。这可以通过将上下文压缩为工作记忆（working memory）来实现。现在，你将在共享的 `Agent` 中实现由模型生成的工作记忆；不要使用提供商特有的压缩端点。

> **TODO(2.1)**
> 实现 `Agent.compact_context`。提示模型压缩上下文。压缩系统提示词应要求生成简洁、事实性的工作记忆，并保留目标、约束、文件、命令、编辑、具体结果、失败方法、测试、阻碍因素和下一步行动。只对较早的前缀进行摘要；原样保留原始系统/任务消息，以及至少最近一个完整的助手动作及其所有关联的工具观察结果。生成的摘要应改变 `build_prompt` 的输出，并缩短提示词的长度。

**不要**改动 `Agent` 类的 `api_prompt` 和 `api_responses` 属性。它们用于记录和评估。

> **TODO(2.2)**
> 在你的共享循环中，每次请求新动作之前调用 `maybe_compact_context()`。它已经会估算活动 token 数量并处理阈值，同时记录压缩事件用于日志。

以 6,000 token 的阈值运行随附的 `django__django-15368` 任务：

```bash
COMPACT_THRESHOLD=6000 \
SWEBENCH_PATCH=artifacts/django__django-15368.patch \
SWEBENCH_TRAJECTORY=artifacts/django__django-15368-trajectory.json \
make run-swebench-agent INSTANCE=django__django-15368
make check-swebench INSTANCE=django__django-15368
```

设置 `COMPACT_THRESHOLD=0` 可省略压缩标志并运行全上下文基线。如果希望保留两次运行，请使用不同的输出名称，例如：

```bash
COMPACT_THRESHOLD=0 \
SWEBENCH_PATCH=artifacts/django__django-15368-baseline.patch \
SWEBENCH_TRAJECTORY=artifacts/django__django-15368-baseline-trajectory.json \
make run-swebench-agent INSTANCE=django__django-15368
```

提交的压缩运行必须至少触发一次压缩，显著减少活动上下文，并生成一个通过 `check-swebench` 的补丁。生成过程是随机的，因此它不需要比每个基线样本使用更少的 ReAct 步数。

在同时获得压缩和不压缩两种轨迹后，比较各轨迹之间的 token 用量。在 `artifacts/token-usage-analysis.md` 中呈现你的观察，并简要解释你观察到的趋势。压缩与不压缩条件之间在上下文使用上有哪些权衡取舍？

## 第 3 部分：构建 `ChessAgent`

你的智能体已经在第 1 部分中修复了象棋应用的问题，所以现在你可以构建一个下棋的智能体了。`ChessAgent` 复用第 1 部分和第 2 部分中的同一个循环。它执白棋，服务器的确定性 bot 执黑棋。服务器会在白方每步合法走棋后自动回应。

### 1. 实现 `play_move`

你将首先定义一个允许智能体在运行中的应用中对弈的新工具。按照 [OpenAI 函数调用指南](https://developers.openai.com/api/docs/guides/function-calling) 定义工具。

> **TODO(3.1.a)**
> 定义一个名为 ``play_move`` 的 OpenAI 函数工具 schema。它必须只接受一个名为 ``move`` 的必需字符串参数，说明走法使用 [UCI 记法](https://en.wikipedia.org/wiki/Universal_Chess_Interface)（例如 `e2e4` 和 `e7e8q`），并拒绝额外参数。

然后，你将实现运行该工具的机制。[^3]

> **TODO(3.1.b)**
> 在 `chess_tools.py` 中实现 `_play_move`。解析参数并将 `{"move": <uci move>}` POST 到 `/api/move`。返回其序列化后的 JSON 对象。捕获工具引发的任何错误，并返回 `<chess_error></chess_error>` 之间的错误消息供智能体处理。覆盖格式错误的 JSON 参数、非对象的参数、缺失或非字符串的 fen、非字符串的 move、服务器拒绝的局面或走法，以及传输失败。

你可以查看 `chess_app` 来了解 API 的工作方式。

使用 `format_state` 方法格式化成功返回的状态，更新 `last_state`，并根据 `game_over` 设置 `finished`。使用原始的 `tool_call_id` 关联观察结果。格式错误的 JSON、未知工具、非法走法和网络错误应变成 `<chess_error>...</chess_error>` 观察结果。由于实际局面在走棋后会发生变化，因此在一组并行调用中最多执行一步棋，并以可恢复的方式拒绝其余调用。

初始的和成功走子后的观察结果已经显示棋盘、黑方应手和下一步合法走法。不需要单独的读盘工具。

运行：

```bash
make run-chess-agent
```

这会应用你的 `fix.patch`，启动修复后的服务器，并保存：

- `artifacts/part3-trajectory.json`
- `artifacts/game-result.json`

打印出的 HTTPS URL 提供棋盘界面和 API。棋盘会在智能体下棋时轮询实时状态；其按钮可刷新状态而不会重置游戏。`CHESS_TIMEOUT=1800` 控制沙盒的存活时间。

### 2. 运行观察 A/B 实验

为了观察工具接口对智能体行为的影响，你将比较两个模型在“仅棋盘观察”和“棋盘加合法走法观察”下的表现。运行脚本无需修改源码即可配置此实验，并使用不同的文件名：

```bash
make run-obs-deepseek-no-legal
make run-obs-deepseek-legal
make run-obs-gpt-oss-no-legal
make run-obs-gpt-oss-legal
```

对四次运行中的每一次，记录 `play_move` 调用总数、被拒绝为非法走法的调用数、非法走法率，以及是否达到 `game_over: true`。在 `artifacts/observation-experiment.md` 中写一份简短对比。你的评分依据是实验和证据，而不是特定结果或赢得对局。

### 3. 添加 `simulate_move`

为了让智能体能够规划更复杂的策略，你将赋予它模拟走棋的能力。模拟允许智能体预演一步棋的效果，但不会实际改变真实棋盘的状态。你将定义并注册 `SIMULATE_MOVE_TOOL`，实现 `_simulate_move`，并将其添加到现有分发器中。

> **TODO(3.3.a)**
> 定义 `simulate_move` 工具，类似于 `play_move` 工具。

`simulate_move(fen, move=None)` 调用 `POST /api/simulate`。

单独向 `simulate_move` 传入一个完整的六字段 [FEN](https://en.wikipedia.org/wiki/Forsyth%E2%80%93Edwards_Notation) 会返回该局面及其合法走法。传入 FEN 加 UCI 走法会返回恰好一个半回合（ply）之后的局面，无论哪一方。返回 JSON，以便 Python 可以使用 `fen`、`squares`、`turn`、`legal_moves` 和终局结果字段。

> **TODO(3.3.b)**
> 在 `chess_tools.py` 中实现 `_simulate_move`。解析参数，使用 FEN 和可选的 move 调用提供的 `/api/simulate` 端点，并返回其序列化后的 JSON。捕获工具引发的任何错误，并返回 `<chess_error></chess_error>` 之间的错误消息供智能体处理。覆盖格式错误的 JSON 参数、非对象的参数、缺失或非字符串的 fen、非字符串的 move、服务器拒绝的局面或走法，以及传输失败。

你应该使用 `ChessAgent.chess_client` 发起该请求。

### 4. 添加 `run_python`

有了在棋盘上模拟走棋的能力，智能体现在可以进行更复杂的规划。能够执行代码将使智能体更可靠地执行它制定的计划，而你将通过程序化工具调用来实现这一点。定义并注册 `RUN_PYTHON_TOOL`，实现 `_run_python`，并将其添加到分发器中。模型提供 `run_python(code)`，代码片段可以将 `simulate_move` 和 `play_move` 作为普通的同步 Python 函数来调用。

> **TODO(3.4)**
> 解析参数，并在沙盒中运行代码，使已注册的工具可以按名称使用。`/opt/assignment/sandbox_python.py` 是 `env` 沙盒上的一个脚本，它可以访问本文件中的同一组工具定义。使用该脚本运行模型作为 `run_python` 工具参数提供的代码。该脚本接受两个位置参数——`port` 和 base64 编码的代码字符串（以避免引号问题）。实现此工具调用。
> 该脚本会打印一个 JSON 对象，包含运行代码得到的 `stdout`、`stderr` 和 `error`——原样返回该字符串。非零返回码表示沙盒本身运行失败，而不是模型代码的问题。将 `exception_info` 或 `stderr` 报告为 `<chess_error>`。
> 如果出现类型不匹配或解析失败等问题，则返回 `<chess_error>{message}</chess_error>`。

模型编写的代码不得在本地智能体进程中运行。`_run_python` 通过 `env.execute` 将 base64 编码的代码发送到提供的沙盒运行器：

```text
python /opt/assignment/sandbox_python.py <port> <base64-code>
```

返回运行器的 JSON 字符串，其中包含 `stdout`、`stderr` 和 `error`。非零的沙盒命令结果应变为 `<chess_error>`。代码片段中的 Python 异常属于运行器调用成功，应放在其 `error` 字段中。在每个代码片段之后，重新读取实时棋盘，更新 `last_state` 和 `finished`，并将格式化后的状态追加到观察结果中；否则，模型可能会重放代码片段已经执行过的走法。

使用以下命令启用这些工具：

```bash
uv run assignment-play-chess --programmatic-tools
```

完成这一实现后，你的智能体应该能够生成一段选择走法的代码，并在对局中走出那步棋。你可能仍会发现，你的下棋智能体没有利用手头工具走出好棋，而是经常直接使用 `play_move` 行动。为了给它更多结构和策略，我们再次转向之前探讨过的技能概念。

### 5. 加载并使用象棋技能

虽然运行 Python 代码的能力使智能体可以选择执行复杂计划，但智能体可能没有这样做的倾向。为了给智能体一个具体的执行策略，我们在 `tasks/chess-skills/select-move` 中提供了另一个技能。为了让模型使用它，你需要赋予 `ChessAgent` 一些来自 `CodeAgent` 的技能使用能力。由于工具执行机制略有不同，你需要在 `_invoke_skill(skills, arguments)` 中重新实现 `ChessAgent` 对 `invoke_skill` 工具的处理，并且仅在加载了技能时注册 `INVOKE_SKILL_TOOL`，然后返回指定技能的完整内容。

> **TODO(3.5)**
> 解析参数并返回指定技能的内容。如果出现类型不匹配或解析失败等问题，返回 `<chess_error>{message}</chess_error>`。

```bash
uv run assignment-play-chess \
  --programmatic-tools \
  --skills-path tasks/chess-skills \
  --trajectory artifacts/part3-python-skill-trajectory.json
```

轨迹必须显示 `invoke_skill`，然后是 `run_python` 代码，其中调用 `simulate_move` 进行搜索并调用一次 `play_move` 落子。仅仅读取技能，然后每回合直接调用一次 `play_move`，并不能证明这些工具协同工作。对局不需要完成或获胜。

## 评分

本次作业满分 **100 分**。每一行独立评分；一次随机模型运行失败不会抹掉其他不相关实现的得分。

| 部分 | 评分标准 | 分数 | 证据 |
|---|---|---|---|
| 1 | 提示词构建与有效的动作/观察历史 | 6 | 私有单元测试 |
| 1 | ReAct 生命周期、纯文本恢复、步数限制、清理、轨迹 | 6 | 私有单元测试 |
| 1 | 编码工具分发、可恢复错误、补丁提交 | 6 | 私有单元测试 |
| 1 | 象棋补丁可应用并通过私有/回归测试 | 8 | 在全新 testbed 中重放补丁 |
| 1 | 技能发现与 `invoke_skill` 行为 | 4 | 私有测试 |
| 2 | 压缩触发与模型生成的摘要 | 6 | 私有测试和轨迹 |
| 2 | 原始指令和最近完整工具步骤保持有效 | 6 | 私有测试和轨迹 |
| 2 | 可审计的压缩显著减少活动上下文 | 4 | 压缩事件和用量 |
| 2 | 全上下文与压缩的 token 用量分析报告 | 4 | 报告 |
| 2 | SWE-bench 补丁通过 FAIL_TO_PASS 和 PASS_TO_PASS | 8 | 补丁重放 |
| 3 | `play_move` schema 与注册 | 4 | 私有测试 |
| 3 | `play_move` 状态更新与可恢复错误 | 6 | 私有测试 |
| 3 | 基础象棋轨迹达到终局状态 | 4 | 轨迹和结果 |
| 3 | 四次运行的观察 A/B 实验完成 | 4 | 四条轨迹、四个结果 |
| 3 | 观察 A/B 实验报告 | 4 | 报告 |
| 3 | `simulate_move` 无状态行为与错误 | 6 | 私有单元/集成测试 |
| 3 | `run_python` 沙盒执行、状态刷新、错误 | 6 | 使用沙盒替身的私有测试 |
| 3 | 技能轨迹结合了技能、程序化搜索和实盘走子 | 6 | 轨迹重放 |
| — | 完整、可解析、符合规则的提交 | 2 | 归档验证 |
| | **总分** | **100** | |

评分器会重放补丁和提交的轨迹；它不会发起新的 LLM 调用。证据缺失或不一致只会影响对应行的得分。课程方的测试和参考补丁不包含在本仓库中。

## 提交

提交一个归档文件，其中包含你在 `src/assignment/agent/` 下修改的文件，以及以下产物：

```text
artifacts/fix.patch
artifacts/part1-trajectory.json
artifacts/django__django-15368.patch
artifacts/django__django-15368-trajectory.json
artifacts/token-usage-analysis.md
artifacts/part3-trajectory.json
artifacts/game-result.json
artifacts/part3-no-legal-moves-deepseek.json
artifacts/part3-no-legal-moves-deepseek-result.json
artifacts/part3-legal-moves-deepseek.json
artifacts/part3-legal-moves-deepseek-result.json
artifacts/part3-no-legal-moves-gpt-oss.json
artifacts/part3-no-legal-moves-gpt-oss-result.json
artifacts/part3-legal-moves-gpt-oss.json
artifacts/part3-legal-moves-gpt-oss-result.json
artifacts/observation-experiment.md
artifacts/part3-python-skill-trajectory.json
```

仅当你修改了 `src/assignment/prompts.py` 时才需包含它。不要提交凭据、`.env`、任务文件、测试、子模块内容或课程方文件。

[^1]: 在这种离线评估设置中，你通常通过将任务组织为来自用户的请求来指定任务。更多示例请参阅这些[文档](https://learn.microsoft.com/en-us/azure/foundry/openai/how-to/chatgpt?tabs=python-key%2Cdotnet-secure%2Cjavascript-secure&pivots=programming-language-python) 。

[^2]: 供应商重复返回 `call_0` ID 是合法的：将每个工具观察结果与同一助手动作中的调用相匹配，不要假设 ID 在整个轨迹中全局唯一。

[^3]: `_play_move` 和其他工具被隔离在 `chess_tools.py` 中，以便可以在远程沙盒中执行这些工具。请在此代码结构内正确使用 Modal 沙盒来执行象棋走法。