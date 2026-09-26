# 11-768 作业 2：评估一个数据可视化智能体

## 概述

稳健的评估对智能体的开发过程至关重要，它使我们能够在将智能体部署到真实世界之前，判断其能力有多强、可靠性有多高。然而，智能体系统的复杂性以及我们据以评估智能体的任务时间跨度很长，这给评估的开发带来了许多新的复杂问题（尤其是与智能体出现之前的语言模型评估相比）。在本次作业中，你将获得亲手设计评估任务和评估智能体轨迹的经验，从而更好地体会评估开发中存在的种种挑战。

本次作业围绕**数据可视化智能体**展开：这类 LLM 智能体在获得数据访问权限和用户指定的规格说明后，能够为用户生成该数据的可视化图表。在本次作业中，你将首先构建一个验证器，用于给数据可视化智能体的输出打分。给定一个用户任务、智能体轨迹和最终输出图像，你需要验证智能体是否正确，或诊断过程中的任何失败。随后，你将设计额外的任务，以探查该数据可视化智能体的优势与弱点，并强化你现有的评估。本次作业的目标是设计一个能够泛化到一组私有智能体轨迹的验证器，你将据此被评分。在评分期间，你的验证器一次评估一次运行。它不会收到任何真值标签、参考图像或其他候选运行结果：只有来自智能体的轨迹和输出图像。

## 初始设置

在学生发布目录中，安装环境：

```bash
uv sync
```

在开发过程中，你将使用课程提供的 Modal 额度，在你自己的 Modal 工作区中运行你的验证器模型。对 Modal CLI 进行身份验证，并部署验证器端点：

```bash
uv run modal setup
scripts/deploy_validator_model.sh
```

部署命令会打印一个端点 URL。为你的 Modal 工作区创建一个代理令牌，然后配置 OpenAI 兼容客户端：

```bash
cp .env.example .env
# Edit .env with your endpoint URL (including the /v1 suffix) and proxy token.
```

代理令牌仅在调用端点时才需要，因此你可以在创建它之前先运行 Modal 设置和部署。不要提交 `.env`、代理令牌或其他凭据。我们将使用的验证器模型是 **Qwen/Qwen3-VL-30B-A3B-Instruct-FP8**——你不得替换它，也不得从你的验证器中调用其他模型。因此，你的验证器应设计为可泛化，而非依赖一个强大的评判模型。我们将使用同一模型的部署来调用你的验证器，以此给本次作业评分。请注意，如果你在构建新镜像，GPU 容器加载该模型大约需要 5-10 分钟。

### 评估格式

你将在 `validator/solution.py` 中实现 `validate(run)`。对于每次运行，它会接收任务、输入数据、智能体轨迹和最终图像，并返回一个错误列表。空列表意味着该运行可接受。每个错误包含四个固定类别之一，以及基于该运行的具体证据：

| 类别 | 含义 |
| --- | --- |
| `execution_failure` | 智能体未能生成有效的图像。 |
| `wrong_data` | 绘制的数据与所请求的不符。 |
| `wrong_chart` | 图像未遵循所请求的图表设计。 |
| `hard_to_read` | 渲染出的图像难以阅读或无法阅读。 |

`execution_failure` 在真值中是终结性的：当人工标签表示没有有效图像时，该运行就被排除在其他三个类别之外，因此不计入它们的任何 TP、TN、FP 或 FN。验证器预测的 `execution_failure` 并不会使该运行免于其他类别。`validator/prediction.py` 定义了确切的输出格式，而 `validator/baseline.py` 提供了一个完整示例。

每个类别在被评估的运行上分别作为一个二分类问题来评分。当真值列出了某个类别时，该运行对该类别即为正例；当验证器的错误列表列出了该类别时，预测即为正例；一个带有多个错误的运行在所列的每个类别中都是正例。对被评估的运行统计真阳性（TP）、真阴性（TN）、假阳性（FP）和假阴性（FN），即可得到马修斯相关系数（MCC）：

$$
\mathrm{MCC}=\frac{TP\cdot TN-FP\cdot FN}
{\sqrt{(TP+FP)(TP+FN)(TN+FP)(TN+FN)}}.
$$

MCC 在完美分类时为 1，无相关性时为 0，逆相关时为负。分数保持在 [-1, 1] 区间内，包括负值。总体 `macro_mcc` 是全部四个类别 MCC 的未加权平均值；其分母始终保持为四。

当真值同时包含两个类别而预测恒定时，MCC 为 0。当某个类别的真值缺少任一类别时，评分器按惯例报告 MCC 为 0，并附带支持不足标志以及正、负支持计数。小型自编数据集很容易出现支持不足的情况，因为某个类别可能从不出现，或者在每一次被评估的运行中都出现。因此，请谨慎解读这类类别分数。私有评分集在每个类别中都会同时包含两个类别，因此这一惯例不会影响官方成绩。MCC 只衡量分类；验证器解释中证据的质量另行评估。

### 每种错误的认定标准

四个类别都是二元决策，一次运行可能同时带有其中若干类别。以下是在种子集和隐藏评估集标签中，每个类别所涵盖的全部内容。

**`execution_failure`。** 智能体最终未能生成有效的图像。这一类别总是单独出现。

**`wrong_data`。** 所绘制的内容并非指令所要求的数据：

- *数值错误。* 绘制的数字、位置或推导量与所请求的数据或公式不符：错误的聚合、缩放或归一化；函数或字段在错误的范围或网格上采样；一个本应编码数据的泡泡大小、颜色值或误差棒却未能如此。
- *数据缺失。* 所请求的某个序列、类别、分组、面板的数据或数据点未被绘制，或者数据的某一维度被丢弃（一个 3D 量在绘制时缺少了一个变量）。
- *选择错误。* 使用了错误的子集、列或过滤条件，或者将未被请求的序列与所请求的序列混在一起。
- *顺序错误。* 点、条形、类别或序列的出现顺序与所请求的不同：在要求排序时未排序，序列被反转或打乱，面板未展示分配给它们的数据。

**`wrong_chart`。** 数据是对的，但未遵循所请求的图表设计。只要指令有要求，我们就认定为：

- *图表类型与投影。* 图表类型错误（条形图却画成折线图，没有饼图）；分组条形图画成堆叠状，纵向条形图画成横向，要求 3D 却画成 2D，缺少极坐标投影，缺少等高线或曲面，缺少或违规使用了双轴，缺少缩放插图或它的连接线。
- *布局。* 子图的数量或排列错误，图形尺寸或 DPI 错误，面板未按所要求共享坐标轴。
- *坐标轴。* x、y 或 z 轴标签缺失或错误；标题或标签文本不精确；坐标轴范围错误（未从零开始、范围错误、范围截断了所请求的数据）；坐标轴刻度错误（对数轴画成线性、等高线层级非线性）；在要求隐藏时仍显示刻度或刻度标签；刻度标签错误或刻度标签旋转错误；在要求隐藏时仍显示边框线；缺少网格。
- *图例、颜色条与注释。* 缺少图例；颜色条缺失或与数据不匹配；所请求的注释或标记点缺失或位置错误；所请求的函数标签或条形数值标签缺失；所请求的公式未渲染；阴影区域错误。
- *样式。* 色图错误或被禁用（在要求感知均匀色图时使用了非均匀色图）；线型错误（虚线或点线却画成实线）；标记形状错误；命名序列的颜色错误；区域未填充；须线、中位数标记、连接线或箱体缺失；多边形未闭合；所请求的线偏移未应用。
- 一个必需的文本元素（标题、坐标轴标签）*完全*落在保存图像之外，就算作缺失，因此属于 `wrong_chart`。

**`hard_to_read`。** 图像按所请求的方式绘制了，但读者无法阅读，或只能艰难地阅读：

- *文本被裁剪。* 标题、坐标轴标签、刻度标签或注释被图像边缘部分截断（一个被切掉一半的标签是 `hard_to_read`；一个完全在图像之外的标签则是 `wrong_chart`，见上文）。
- *文本重叠。* 刻度标签、注释、标题或标签相互重叠，或标记被绘制在标注它们的文本之上。
- *元素遮盖内容。* 图例、注释或文本框遮住了数据、标签或其他文本。位于空白处的图例则没有问题。
- *对比度过低或内容不可见。* 文本或数值标签与其背景的对比度低于约 2.5:1；某个序列用背景色绘制、宽度为零，或以其他方式不可见。
- *数据难以分辨。* 必须区分开来的两个序列或分组被绘制成相同或几乎相同的颜色、线型和标记；色图将本应看起来不同的值合并在一起。
- *布局被挤压。* 数据、箱体或面板被坐标轴范围或相互重叠的坐标轴挤压成一条无法阅读的细条。

## 第 1 部分：检查种子智能体运行

我们在 `artifacts/<run_id>/` 下提供了一些种子智能体运行。每个运行子目录包含 `result.json`（其中包括任务规格、完整的智能体轨迹以及智能体运行的结果），以及 `figure.png`（最终图表，如果智能体能够生成的话）。`run_id` 是唯一的唯一键：若干次运行可以共享同一个 `task_id`，因此请以 `run_id` 索引任何内容。你还可以访问 `validator/baseline.py` 中一个简单的基于 VLM 的验证器。你可以用以下命令在所有现有运行上运行基线验证器：

```bash
uv run python -m validator.runner \
  --solution validator.baseline \
  --artifacts artifacts \
  --out output/baseline_predictions.json
```

基线首先发送完整证据。如果模型以超出上下文窗口为由拒绝请求，它会发出警告，并用轨迹和输入文件的较短摘录重试一次，保留它们的开头和结尾。该回退方案使用服务器的分词器和报告的上下文限制，为文本和响应分配 50% 的上下文，其余留给图像和格式。`validator/baseline.py` 中的 `CONTEXT_FRACTION` 控制这一比例；不存在固定的上下文大小或逐步缩小的重试循环。任务和图像保持完整，遗漏处会在提示中标注。该回退方案可能丢失相关证据；它并不保证与完整运行得出相同的判断。如果压缩后的请求仍然无法容纳，或者服务器的分词器端点不可用，错误会被传播出去。这只是基线的做法：你可以在 `validator/solution.py` 中随意自定义上下文管理。

我们在 `seed_labels.json` 中提供了种子智能体运行的真值人工标签。用以下命令给基线预测打分：

```bash
uv run python -m workflow score \
  --labels seed_labels.json \
  --predictions output/baseline_predictions.json
```

首先，比较真值标签和验证器标签。报告全部四个逐类别 MCC 分数和 macro-MCC，然后找出两种常见的验证器错误类型，每种都出现在至少两条智能体轨迹中（列出所有轨迹的 run ID）。对每种错误类型，描述可观察到的证据，并提出一项可能捕捉到该类错误的验证器改动。

## 第 2 部分：改进你的验证器

实现第 1 部分中对默认验证器提出的两项改动。记录你所做的改动以及修改后的验证器在种子智能体运行上的表现，并将其与基线验证器进行比较。如果在这一步性能没有显著提升也没关系；我们之后还有时间继续改进验证器。你应报告新验证器全部四个逐类别 MCC 分数和 macro-MCC，并定性地报告你的改动是否确实有助于缓解你在第 1 部分中揭示的错误类型。具体而言，你应至少找出一个假阳性案例和一个假阴性案例，并尝试解释这些错误由什么导致，以及这可能意味着你的验证器缺少什么。

在 `validator/solution.py` 中实现你的改动，然后在已发布的种子运行上运行修改后的验证器：

```bash
uv run python -m validator.runner \
  --artifacts artifacts \
  --out output/pre_iteration_seed_predictions.json
uv run python -m workflow score \
  --labels seed_labels.json \
  --predictions output/pre_iteration_seed_predictions.json
```

验证器模型是固定的：你不能替换验证器实际使用的模型，也不能调用任何其他模型，因此请尽量设计一个模型无关的验证器。除此之外，你可以随意自定义 `validator/solution.py`，只要 `validate(run)` 函数签名和 `validator/prediction.py` 中的输出模式保持固定即可。请注意，你需要使用输入数据、最终输出和智能体轨迹进行评估；基线验证器展示了如何用这三者调用模型。

## 第 3 部分：设计新的评估任务

现在你应该已经基于第 1 部分的定性观察得到了一个改进的验证器。从阅读真实智能体轨迹中识别潜在错误，是改进验证器的一种常见方式。另一种方法是在分布外数据上测试验证器，以衡量它对新的任务类型的稳健性。在本节中，你将设计自己的可视化任务，以对你的验证器性能进行压力测试。

首先，通读你当前的学生验证器实现，找出它可能难以泛化的两类可视化任务。编写五个可视化任务（每类任务至少两个），在其上运行所提供的智能体，并根据上述四个错误类别对结果进行标注。如果你的可视化任务需要自定义数据，你可以使用 LLM 合成生成数据，或复用另一个可视化任务中的数据。然后你应在新的智能体轨迹上运行你的验证器，并报告这些对抗性案例上全部四个逐类别 MCC 分数和 macro-MCC。你不应硬编码公开的任务 ID 或标签。

所提供的智能体模型是固定的：

- **Qwen/Qwen2.5-Coder-3B-Instruct**
- **mistralai/Ministral-3-14B-Instruct-2512**
- **zai-org/GLM-4.7-Flash**

用每个所提供的智能体将每个新任务运行一次，总共产生至少 15 次自编智能体运行。使用上文定义的同一证据标准对每一次生成的运行进行人工审查。在你的报告中，分析哪些失败反映了可视化智能体的弱点，哪些反映了你的验证器的弱点。

### 在开始第 3 部分之前

```bash
scripts/deploy_generation_models.sh
# Copy the three printed URLs into the GENERATION_* settings in .env,
# append /v1 to each URL, and set GENERATION_API_KEY.
scripts/deploy_agent_runner.sh
```

请注意，智能体最多进行 20 个智能体步骤，每条 shell 命令限制为 120 秒，总墙钟时间限制为 15 分钟。部署故障排除见 `infrastructure/README.md`。

### 编写任务

在 `tasks/<task_id>/` 下每个任务创建一个目录：

```text
tasks/<task_id>/
  task.json
  inputs/                 # optional; any task-local input files
```

其 `task.json` 描述符恰好包含以下字段：

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

`task_id` 必须与其目录名匹配，且只能包含字母、数字、句点、下划线和连字符。`task_class` 命名你所找出的两个弱点类别之一；同一类别中的任务使用相同的值。`instructions` 必须完整指定图表，并应使正确性可供人工审查。每个输入 `name` 是智能体看到的纯文件名；`path` 相对于任务目录。路径不得为绝对路径，也不得包含 `..`。当提示中包含全部数据时，请使用空的 `inputs` 列表。`artifacts/` 下已发布的运行提供了任务指令和输入的示例。你的任务除现有环境中已包含的包（matplotlib、numpy、pandas、Pillow、scipy 和 seaborn）外，不应包含任何其他包；私有集也不会要求你考虑需要智能体使用任何额外包的任务。

在生成运行之前，验证所有描述符和所引用的文件：

```bash
uv run python -m workflow validate-tasks
uv run python -m workflow generate
```

运行是可恢复的：已存在的任务/模型运行会被跳过。要重新生成已有运行，请添加 `--force`；要在开发过程中运行子集，请添加 `--models qwen`、`--models ministral` 或 `--models glm`。

每次生成的运行都写入以下布局：

```text
runs/<task_id>__<agent>/
  result.json             # task, agent identity, and complete trajectory
  inputs/                 # copies of this run's task inputs
  figure.png              # present when the agent left an output file
```

在你的验证器上运行生成的运行：

```bash
uv run python -m validator.runner \
  --artifacts runs \
  --out output/pre_iteration_authored_predictions.json
```

### 人工标签与评分

为每次生成的运行创建一个带一个空白条目的 `labels.json`：

```bash
uv run python -m workflow init-labels
```

然后对每次运行进行人工审查。在每个条目中，如果该运行可接受，将 `"errors": null` 替换为 `[]`；如果不可接受，则替换为一个由 `{family, evidence}` 错误组成的列表。每个错误都需要具体证据，并且 `execution_failure` 必须单独出现。示例见 `labels.example.json`。

验证覆盖范围和模式，然后报告全部四个类别 MCC 分数和 macro-MCC：

```bash
uv run python -m workflow validate-labels
uv run python -m workflow score \
  --predictions output/pre_iteration_authored_predictions.json
```

### 将你的任务打包为 Harbor 环境

[Harbor](https://github.com/harbor-framework/harbor) 是一个评估框架，自 Terminal-Bench 2.0 推广以来，它最近已成为智能体基准测试的行业标准。Harbor 将任务定义为自包含的目录，这些目录定义了沙箱和评估标准，任何智能体都可以针对它们运行。在作业的这一部分，我们将把我们的任务（目前只支持我们内部的 `workflow generate`）打包为 Harbor 格式，以便任何人都可以运行它们。由于 Harbor 任务需要确定性验证器，你可能需要为每个私有任务添加更多特性，但你不应重新设计任务的实际内容。具体而言，你必须要求智能体编写 `plot.py` 和 `plotted_values.json`，而你原来的任务并未要求这些。将任何此类添加保留在 `harbor/tasks/<task_id>/` 内。关于作业这一部分的更多细节见 `harbor/README.md`。

首先查看 `harbor/example/` 中的合成工作示例，以了解相关要求。你应该既针对该示例的参考解决方案运行它，也针对一个什么都不做的智能体运行它。

```bash
uv run harbor run -p harbor/example -a oracle --job-name example-oracle   # reward 1.0
uv run harbor run -p harbor/example -a nop    --job-name example-nop      # reward 0.0
```

然后你应运行 `harbor/example/mutants/` 中四个故意错误的示例解决方案中的至少一个。其中三个得分为 0.0；`illegible/` 得分为 1.0，因为验证器漏掉了它的图表太小而无法阅读这一问题。运行命令见 `harbor/example/README.md`，该命令会换入一个变异体并重新运行 Harbor 验证器。然后你将打包你自己的每个任务。你可以运行以下命令，从你已经编写的私有任务初始化你的 Harbor 任务（具体来说，它为你的每个先前任务将 Harbor 模板复制到一个新的 `harbor/tasks/<task_id>/` 目录中，然后填入一些样板信息以及初始 `instruction.md`）。**生成运行后，不要编辑已播种的提示。**

```bash
uv run python -m workflow package
```

对于你的每个私有任务，你需要实现 `harbor/tasks/<task_id>/tests/test_state.py` 中的确定性检查、`harbor/tasks/<task_id>/solution/solve.sh` 中的参考解决方案，以及脚手架留作“必需输出”的任何其他内容。在花 Docker 周期之前检查每个任务，然后确认你的参考解决方案确实通过：

```bash
uv run python harbor/preflight.py harbor/tasks/<task_id>
uv run harbor run -p harbor/tasks/<task_id> -a oracle --job-name <task_id>-oracle
```

要完成本节，你必须让每个已打包任务针对你的参考解决方案得分为 1.0。在你所有已打包任务中，你还必须总共编写**两个**变异体解决方案，形式为 `harbor/tasks/<task_id>/mutants/<name>/solve.sh`。它们可以属于同一个任务，也可以属于不同任务。两者都给出一个看似合理的错误答案；它们的区别在于验证器对每个答案的处理。一个必须**得分为 0**：你的检查会拒绝它。一条捷径是使用你已经要求提供的 `plotted_values.json`——手工推导出期望的数值，将它们作为字面量写入测试文件并比较，任何更改了数值的变异体随后都会失败。另一个必须**得分为 1.0**：一个真正错误但你的检查却放行的答案。这个变异体应暴露验证器的一个真实局限。例如，一个图表可以包含正确的数据和标签，但由于在小画布上使用了 2pt 的文字而仍然无法阅读。`harbor/example/mutants/illegible/` 就是一个已完成的版本，它针对讲义中最强的验证器得分为 1.0。`check-submission` 会运行所有这些，因此没有哪一项是你可以不实际运行就报告出来的。在报告中，给出每个变异体的奖励、它错在哪里，以及是哪个断言抓住了它，或者为什么没有任何东西能抓住它。第二个变异体正是本节的意义所在：在这里，你是在测量而非被告知，你的 VLM 验证器所要跨越的边界。`harbor/TROUBLESHOOTING.md` 涵盖了你最可能遇到的错误，包括无效的 `task.toml` 被报告为“no task found”这一错误。

## 第 4 部分：迭代你的设计

利用你第 3 部分的结果，你应至少对你的验证器再做一项额外改进。在种子任务和你的新任务上评估最终验证器，并报告全部四个新的逐类别 MCC 分数和 macro-MCC，同时定性地分析这一改动是否在你的手写任务上带来了改进。与前一部分类似，你应至少找出一个假阳性和一个假阴性，包括轨迹中任何相关文本，以及关于验证器为何出错的假设。

在两组轨迹上运行最终验证器：

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

在这一步之后，你可以对验证器做额外改进，或设计更多任务，因为你的部分成绩将取决于你的最终验证器在私有测试集上的表现。请在报告中报告你对验证器所做的所有额外改动，以及纳入它们的动机，以及你判断它们有多成功（定性和定量地）。

## 提交与评分

提交：

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

在提交之前，运行端到端结构检查：

```bash
uv run python -m workflow check-submission
```

它会验证必需的文件、验证每个任务和输入、要求至少五个任务跨越至少两个 `task_class` 值且每个类别有两个任务、要求每个任务恰好有来自每个固定智能体的一次运行，并检查 `labels.json` 恰好覆盖这些运行各一次。它还会分两个阶段检查 Harbor 打包。首先是结构上：每个已编写任务有一个 `harbor/tasks/<task_id>/` 且没有多余的、每个任务中都有完整的 `harbor/template/` 布局、每个任务的参考解决方案和验证器中的模板哨兵已被移除、其 `instruction.md` 中没有遗留 TODO 标记、`instruction.md` 仍然逐字保留其描述符的提示词并要求提供 `plot.py` 和 `plotted_values.json`，以及 `harbor/tasks/<task_id>/mutants/<name>/solve.sh` 下总共两个变异体。它会一次性报告每个任务中的每个故障。然后它运行 Harbor 并将奖励与契约对照：每个已打包任务用 `-a oracle` 都必须得分为 1.0，一个变异体必须得分为 0，一个变异体必须得分为 1.0。它会打印它读取到的奖励，失败时会指出解释它的 `jobs/check-submission-<job>/<trial>/verifier/pytest.log`。该阶段需要 Docker，需要几分钟；`--skip-harbor-runs` 会在结构检查的一半之后停止，这在你迭代时正是你想要的。它不评判标签正确性或报告质量；这些仍需要人工审查。使用 `report_template.tex` 作为你最终 `report.tex` 的起点。报告应回答第 1--4 部分中的每一个问题，并包含足以重现你实验的细节。

你还应包含一个 AI_USAGE.md 文件。它应详细说明你为本次作业使用任何 AI 技术的情况。列出你使用的所有工具，并清楚描述你如何使用每个工具。如果你没有使用任何 AI 协助，请在该文件中声明这一点。我们不会给你的 AI_USAGE.md 文件评分，但我们会通过一次测验（详情已发布在 Piazza 上）检查你对所提交代码的理解。

你成绩的一部分将取决于你提交的验证器在私有集上的 macro-MCC。私有集可能包含种子运行中未出现的任务和图表类型，因此请避免过度拟合公开示例的设计。

| 权重 | 组成部分 |
| ---: | --- |
| 40% | 报告和设计理由 |
| 30% | 基于验证器在私有集上的 macro-MCC |
| 20% | 测验 / 理解性检查 |
| 10% | 代码质量和可复现性 |