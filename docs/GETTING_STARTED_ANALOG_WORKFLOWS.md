# 新手上手：运行 analog-pipeline 和 analog-recovery

这份指南面向第一次使用本仓库流程的人，说明怎样取得代码、配置环境、选择流程，并把任务清楚地交给 Codex。

本文按 Windows、PowerShell 和 Codex 桌面版编写。它讲的是**流程代码怎么运行**，不会提供任何人的服务器账号、API key、PDK或真实设计数据。GitHub 分支也不含 `WORK_*`、`wiki/projects/`、本机配置或模型文件。想验证真实电路，先确认你有权使用任务所需的网表、testbench、模型和远程服务。

## 1. 先选对流程

| 你的任务 | 使用 | DUT 会不会改动 |
|---|---|---|
| 从规格开始设计新电路，或继续正向设计和验证 | `analog-pipeline` | 设计阶段会生成或修改电路文件；要在 prompt 里限定可写目录和参数范围 |
| 固定一份已有电路，解释其原理、验证证据并写设计说明书 | `analog-recovery` | DUT 参数固定，不进行电路优化或调参 |

不要把“重建已有电路的说明书”交给 `analog-pipeline`，也不要用 `analog-recovery` 代替新电路设计。

## 2. 准备任务输入

### analog-pipeline

开始前尽量准备：

- 目标功能、工艺、供电和可量化规格；规格写成 `spec.yml` 最清楚。
- 如果是已有电路，提供 DUT 网表、testbench、模型/include 的来源和版本。
- 允许写入的任务目录、是否允许修改网表，以及是否允许仿真和调用外部 reviewer。
- 要跑真实仿真时，准备好有权限的 EDA 主机、Spectre、许可证和 PDK/model。

缺少量化规格时，流程可能退到 L1 功能目标；这不能代替完整性能或 PVT sign-off。

### analog-recovery

开始前准备：

- 需要保持不变的 DUT 网表及其完整 include/model 依赖。
- 已有 testbench、仿真结果、指标、原设计资料和报告要求；标明哪些来源可信、哪些只是线索。
- 新的 `WORK_<任务名>` 输出目录。
- 若需要实际仿真、外部复核或 Word 报告渲染，确认相应访问权限、API和软件已准备好。

仓库自带 `fm-analog-v1` 报告模板。Recovery 的目标是固定 DUT 的取证与说明，不代表 DUT 已收敛或所有指标已通过。

## 3. 从 GitHub 克隆

先确认自己有仓库访问权限。打开 PowerShell，把下面目标目录改成你想放项目的位置：

```powershell
$Repo = 'E:/AI/analog-agents-v0p1'
git clone --recurse-submodules --branch feature/update-dispatch-subagents https://github.com/hayatushitaro-lab/analog-agents-v0p1.git $Repo
Set-Location -LiteralPath $Repo
git submodule status
```

使用 `--recurse-submodules` 取得仓库固定的 `virtuoso-bridge-lite` 版本。若子模块目录为空或 `git submodule status` 前有 `-`，在仓库根目录运行：

```powershell
git submodule update --init --recursive
```

如果负责人给了更新的分支或 tag，把命令中的分支名换成负责人指定的版本。不要单独把 bridge 子模块更新到最新版本。

## 4. 安装本机 Python 环境

安装 Git、Python 3.12 和 `uv`。在仓库根目录运行：

```powershell
uv venv --python 3.12 .venv
uv pip install --python .venv/Scripts/python.exe -e ./virtuoso-bridge-lite PyYAML==6.0.3 python-docx==1.2.0 Pillow==12.3.0 PyMuPDF==1.28.2
```

`virtuoso-bridge-lite` 会 editable 安装到当前工作区。以后运行项目脚本时使用仓库自己的 Python，不要切到全局 Python：

```powershell
.\.venv\Scripts\python.exe -X utf8 -c "import sys,yaml,docx,PIL,pymupdf,virtuoso_bridge; print(sys.executable); print(virtuoso_bridge.__file__)"
```

输出的两个路径应指向当前工作区。某项任务如果提示缺额外 Python 包，再按该任务文档补装。

## 5. 配置本机服务

所有真实主机、账号、密钥和授权都留在自己的电脑上。**不要把密钥贴进 prompt，也不要提交 `config/servers.yml`、`config/reviewers.yml` 等本机配置或 `.env`。**

### 必须先做：Recovery 的本机 site

从安全模板创建忽略的本机配置：

```powershell
New-Item -ItemType Directory -Force skills/analog-recovery/_local | Out-Null
Copy-Item skills/analog-recovery/references/site.example.json skills/analog-recovery/_local/site.json
```

编辑 `skills/analog-recovery/_local/site.json`，把仓库、wiki、Python 和 reviewer 配置路径换成当前工作区。模板默认为 `replay`，并关闭仿真和外部 reviewer。第一次设置时先保留这些安全默认值。

之后只有在确认任务允许使用相应服务时，才按长版配置说明的 live 示例启用仿真或 reviewer；只启用本次明确允许的项目。Prompt 写了“允许”也不会自动替代服务器、API和 site 配置。

### 只有需要真实 EDA 时：servers 和 bridge 环境

只有拿到真实 EDA 主机和账号后，才从示例创建配置：

```powershell
Copy-Item config/servers.example.yml config/servers.yml
```

填写接收方自己的主机、账号、SSH key 路径和角色映射。不要保留示例主机名。bridge 的连接信息单独放在工作区根目录 `.env`，字段参考 `virtuoso-bridge-lite/src/virtuoso_bridge/resources/.env_template`。`servers.yml` 不会代替 bridge 的 `.env`。远端还必须能运行 Spectre 并访问许可证、模型和 include 文件。

如果没有 EDA 配置，`analog-pipeline` 只能按 review 模式工作，不能宣称仿真验证通过。不要为了让配置检查变绿而填写虚构服务器。

### 只有需要外部 reviewer 时：评审 API

确认自己有权限使用外部服务后，才创建：

```powershell
Copy-Item config/reviewers.example.yml config/reviewers.yml
```

只启用自己实际能访问的 reviewer。API key 通过接收方认可的安全方式设置为对应环境变量，并确保启动 Codex 的进程能读取；不要把 key 写进 Git 文件或 prompt。Recovery 的共享 site 默认关闭外部 reviewer。`config/effort.yml` 是可选的；不创建时默认使用 `standard`。

## 6. 在 Codex 里打开仓库

在 Codex 桌面版打开刚克隆的仓库目录，并从这个工作区新建任务。每条任务 prompt 开头都写清楚要用的工作区技能。如果 Codex 没有自动读到项目内的技能文件，就让它直接读取对应的 `SKILL.md`；不要依赖你电脑上其他版本的全局技能。

先用下面的只读预检 prompt：

```text
请先阅读仓库根目录 AGENTS.md，以及 skills/analog-pipeline/SKILL.md 和
skills/analog-recovery/SKILL.md。现在只做环境预检：不运行仿真、不调用外部 API、
不修改 DUT、不写 wiki。检查当前 Python/bridge 路径、我提供的输入文件和本机配置，
列出可以继续的流程、缺少的文件或权限，以及下一步命令。不要猜测主机、PDK或凭据。
```

不要在第一条 prompt 里贴 API key、SSH 私钥、密码或未脱敏的服务器配置。

## 7. 做一次不访问外部服务的预检

在 PowerShell 仓库根目录运行：

```powershell
.\.venv\Scripts\python.exe -X utf8 -c "import sys,yaml,docx,PIL,pymupdf,virtuoso_bridge; print(sys.executable); print(virtuoso_bridge.__file__)"
.\.venv\Scripts\python.exe -X utf8 skills/analog-recovery/scripts/resolve_workflow.py --repo . --run-dir WORK_FIRST_READONLY --read-only
```

如果 `WORK_FIRST_READONLY` 已存在，换一个新名字。检查该目录的 `workflow.resolved.json`：

- `repository_root` 应是你克隆的工作区。
- 仿真和外部 API 应关闭，wiki 写入策略应是只读。
- `pending` 只代表计划已准备，**不代表**任何角色已执行或任务已完成。

这个检查不会验证 EDA 主机、许可证、模型或 API 是否真的可用。

## 8. 可直接改写的任务 prompt

把方括号里的内容换成真实路径和目标。路径要在当前工作区里，或明确说明外部路径是否允许读取。

### A. 新电路或正向设计：analog-pipeline

```text
请使用当前工作区的 analog-pipeline 流程。先阅读 AGENTS.md 和
skills/analog-pipeline/SKILL.md，并按该流程需要的阶段技能执行。

目标：设计/继续设计 [电路块及功能]。
规格： [spec.yml 路径；如果还没有，列出工艺、供电和定量指标]
已有输入： [现有网表、testbench、模型/include 路径；没有就写“新设计”]
输出目录： [仓库下一个新的 WORK_<任务名> 目录]
工作范围： [允许创建/修改哪些文件和参数；明确禁止改动的文件]
执行模式： [review-only；或允许使用已配置的 EDA 做仿真]
外部 reviewer： [禁止；或允许调用 config/reviewers.yml 中已配置的服务]
预算：最多 [次数] 次仿真、[次数] 次外部评审；达到后总结现状。

缺少规格、模型、权限或关键输入时，先列缺项，不要编造。review-only 模式下不要
启动仿真/API，也不要把结果标成已仿真验证。修改只放在指定任务目录；若要改已有
DUT，先遵守上面列出的修改范围。每个阶段报告产物路径、验证级别、未解决问题。
```

要完成 full pipeline，需要可用的 EDA/PDK 条件，并明确允许相应仿真。只有 review 结果不能称为 simulation-verified；没有 L3 PVT 结果也不能称为完成 L3 sign-off。

### B. 固定电路反推说明书：analog-recovery

```text
请使用当前工作区的 analog-recovery、analog-recovery-evidence 和
analog-recovery-report 技能。先阅读 AGENTS.md 及这三个技能的 SKILL.md。

目标：为 [电路/模块] 重建工程设计说明书。
固定 DUT： [网表路径；明确版本或校验信息]
依赖与资料： [models/include、testbench、仿真数据、原理图/规格等路径]
输出目录： [仓库下一个新的 WORK_<任务名> 目录]
验证模式： [只读/静态；或允许在已配置 EDA 上进行固定 DUT 仿真]
外部 reviewer： [禁止；或允许使用已配置服务]
wiki 写回：只准备差异，未经我批准不要应用。

保持 DUT、模型、历史运行和模板不变，不做 sizing/优化，不把历史线索直接当成
当前事实。先核对输入和依赖；缺少证据时标清未验证项。按流程检查主要功能覆盖，
输出证据包、DOCX、页面渲染预览及未解决问题。准备计划或生成 DOCX 本身不算
证据完整或电路收敛。
```

完整报告还需要相应仿真/复核权限。生成和检查 DOCX 需要安装好的 Microsoft Word 桌面版、中文字体，以及本机可用的文档渲染/审阅技能或等效工具。

## 9. 怎样判断这次真的跑通

### analog-pipeline

- **review-only**：得到有输入依据的架构/网表审查和明确限制；不得标成仿真通过。
- **仿真流程**：在新任务目录里有设计与 testbench 产物、verifier 报告、仿真日志及对应输入/条件；报告覆盖本次承诺的规格和角落。
- **L3 sign-off**：只有按规格完成 PVT 矩阵并检查通过，才称为 L3 sign-off。

### analog-recovery

- 有可追溯的 evidence bundle，且 bundle/测量/质量检查结果和实际内容一致。
- 有生成的 DOCX 和对应页面渲染/预览；只生成 DOCX 不算版式验收。
- 已验证事实、历史线索、未验证项和阻塞原因区分清楚；wiki 变化未经批准仍只保留候选。
- 报告交付状态和 DUT 收敛状态分开记录。

## 10. 常见情况

| 现象 | 怎么处理 |
|---|---|
| clone 后 bridge 目录为空 | 在仓库根目录运行 `git submodule update --init --recursive` |
| import 指向别的 Python 或旧路径 | 用本仓库 `.venv/Scripts/python.exe` 重建环境，并重新 editable 安装 bridge |
| 找不到 `skills/analog-recovery/_local/site.json` | 按第5节从已跟踪模板复制并填写本机路径 |
| pipeline 进入 review 模式 | 说明没有检测到真实 EDA 配置；先确定是否有远端权限，不要填假主机 |
| recovery 显示 reviewer/API 被阻断 | 先核对 site 模式、授权设置和 Codex 进程环境；不要贴出 key |
| 有计划文件但没有仿真结果 | 计划只表示已准备；需要有权限的执行角色实际运行并产生日志 |
| DOCX 有但 PDF/预览缺失 | 核对 Word、字体、文档渲染工具和实际渲染日志 |
| 要求把 wiki 结果写回 | 先看候选差异；只有收到批准后才应用 |

本指南和长版机器配置说明可以一起使用：长版见 [`WORKSPACE_HANDOFF_SETUP.md`](../WORKSPACE_HANDOFF_SETUP.md)。
