# analog-agents 全量工作区接收与配置说明

更新日期：2026-09-24。面向收到完整工作区 ZIP、准备在另一台电脑运行相同流程的使用者。

**保留全量文件，不需要删除历史项目或整理知识库。需要重新配置的是接收方的 Python 环境、工作区路径、远程 EDA 连接、评审 API 和技能入口。** 本说明依据交付时的维护源码编写，不代表接收方环境已经验证。

以下以 **Windows + PowerShell + Microsoft Word 桌面版** 为操作环境。解压目录示例为 `E:/AI/analog-agents-v0p1`，请换成自己的实际路径。Linux/macOS 需要另行适配解释器路径和文档渲染，本说明不承诺其版式与 Windows 相同。

## 1. 哪些文件需要配置

| 文件或位置 | 是否需要处理 | 配置内容 |
|---|---|---|
| `.venv/` | 必须重建或验证，通常重建 | 压缩包内的虚拟环境可能引用发送方用户目录的基础 Python；editable 安装也可能指向旧路径 |
| `skills/analog-recovery/_local/site.json` | 必须核对 | 当前仓库、wiki、Python、reviewers 路径；本机仿真/API使用策略及额度 |
| 工作区根目录 `.env`，或接收方用户目录 `.virtuoso-bridge/.env` | 运行远程仿真时必须 | bridge 实际读取的 EDA 主机、账号、Spectre 路径、环境脚本、跳板/SSH后端等 |
| `config/servers.yml` | 使用 EDA/正向角色路由时配置 | 主机、账号、SSH key、角色映射；**不能代替 bridge 的 `.env`** |
| `config/reviewers.yml` | 使用外部评审时必须 | 可用模型、接口地址、API key或环境变量、超时及启用项 |
| `config/effort.yml` | 核对即可 | 默认 `standard`；按需设置模块覆盖档位 |
| `_local/context.yml` | 建议补充 | 接收方主机、模型位置、工作目录、网络等环境说明；供代理理解环境，不是自动连接配置 |
| `_local/sanitize-map.yml` | 使用标准下载脱敏流程时需要 | 接收方路径、账号、主机标识等的替换表 |
| 接收方代理的技能目录/插件 | 必须核对 | 让代理读到本工作区维护技能、bridge自带技能及文档技能 |
| 远程服务器的模型、许可证和初始化环境 | 仿真时必须核对 | ZIP不能替代服务器上的EDA安装、许可证服务或缺失的PDK文件 |
| Word桌面版、中文字体 | 生成同类DOCX/PDF时需要 | 当前渲染器使用Word COM；历史绘图脚本可能引用Windows字体 |

交付时的工作区没有根级 `_local/` 和根级 `.env`，但已有 `skills/analog-recovery/_local/site.json`。如果收到的 ZIP 是其他时点的快照，以解压结果为准。缺少根级配置时按下面说明新建，不能因技能的 `_local/site.json` 已存在，就认为远程连接也已配置。

API key、SSH身份、账号权限和许可证由接收方确认并配置；不默认沿用发送方凭据或发送方的服务使用授权。本文件不包含凭据。

## 2. 解压与 Python 环境

### 2.1 保留工作区结构

至少核对这些实际文件存在：

```text
AGENTS.md
pyproject.toml
skills/analog-recovery/SKILL.md
skills/analog-recovery-evidence/SKILL.md
skills/analog-recovery-report/SKILL.md
skills/analog-evolve/SKILL.md
skills/analog-evolve/references/recovery.md
tools/wiki_ops.py
tools/recovery_wiki.py
wiki/index.yml
wiki/edges.jsonl
virtuoso-bridge-lite/pyproject.toml
virtuoso-bridge-lite/src/virtuoso_bridge/
virtuoso-bridge-lite/skills/spectre/SKILL.md
```

`virtuoso-bridge-lite/` 虽是Git子模块，但ZIP中必须有实际源码。若只有空目录或Git指针，应向发送方补齐对应快照，不要直接拉最新版本替换本次已验证源码。运行Python不依赖Git历史完整，但后续提交/更新需要完整Git元数据。

### 2.2 建立接收方环境

发送方使用 Python 3.12；项目最低要求为3.11。为减少差异，接收方可沿用3.12。先准备 `uv` 和可用Python；以下安装步骤只供接收方执行，本次编写说明时没有安装任何内容。

若解压后已有 `.venv`，先在文件管理器中将它改名为一个未占用的备份名，例如 `.venv.sender-backup`，保留全部内容，再建立新的 `.venv`。**不要仅修改旧的 pyvenv.cfg，也不需要删除旧环境。**

从解压后的工作区根目录运行：

```powershell
$Repo = 'E:/AI/analog-agents-v0p1'
Set-Location -LiteralPath $Repo
uv venv --python 3.12 .venv
uv pip install --python .venv/Scripts/python.exe -e ./virtuoso-bridge-lite PyYAML==6.0.3 python-docx==1.2.0 Pillow==12.3.0 PyMuPDF==1.28.2
```

上述四个库版本来自发送方当前环境，是复现参考，不是全部项目的完整依赖锁。根 `pyproject.toml` 只声明 bridge 和 PyYAML，单靠它不会自动补齐报告依赖。bridge必须editable安装到**接收方当前解压目录**。

按需项：选择Paramiko SSH后端时，另执行 `uv pip install --python .venv/Scripts/python.exe -e './virtuoso-bridge-lite[ssh]'`；特定分析任务若实际需要NumPy、Matplotlib等，再按该任务依赖安装。它们不是当前FM524报告使用Pillow出图的必需前提。外部评审桥接可回退到Python标准库HTTP实现，不能仅因没装httpx就判定必须重装工作区。

以后执行项目脚本统一使用：

```powershell
# 示例：先查看任务准备器帮助；实际任务换成相应脚本和参数。
.\.venv\Scripts\python.exe -X utf8 skills/analog-recovery/scripts/resolve_workflow.py --help
```

`-X utf8`用于避免Windows默认GBK读取中文JSON/Markdown失败。不要让代理改用全局Python，也不要不加核对地复用子目录中的旧`.venv`。

## 3. Recovery 的 site.json

编辑 `skills/analog-recovery/_local/site.json`。将五个路径都指向接收方当前工作区，JSON建议使用 `/`，避免反斜杠转义错误。

下面是完整示例；`live/true`表示接收方已经确认允许本项目执行必要仿真和外部评审后采用的生产设置：

```json
{
  "repository_root": "E:/AI/analog-agents-v0p1",
  "wiki_root": "E:/AI/analog-agents-v0p1/wiki",
  "python": "E:/AI/analog-agents-v0p1/.venv/Scripts/python.exe",
  "reviewers_config": "E:/AI/analog-agents-v0p1/config/reviewers.yml",
  "project_root": "E:/AI/analog-agents-v0p1",
  "max_calls_per_run": 12,
  "max_rounds": 3,
  "report_defaults": {
    "mode": "live",
    "simulation_authorized": true,
    "external_review_authorized": true,
    "knowledge_write_policy": "approval"
  }
}
```

- `repository_root` 和 `project_root` 均为工作区根，不能仍指向发送方路径，也不能指向某个旧 `WORK_*`。准备器会核对当前仓库绑定。
- `wiki_root` 继续用本工作区原 `wiki/`，不另建recovery知识库或索引。
- 未准备好服务时，参考 `skills/analog-recovery/references/site.example.json`，使用 `mode=replay`、两个授权字段为`false`。当前任务的只读/禁仿真/禁API限制始终优先。
- `knowledge_write_policy=approval`：生成同库归档/知识候选及差异，获批后写回；它不禁止取证和报告生成。
- 共享site不填写某个旧任务的`run_dir`；每次用准备器生成新任务的 `site.json` 和 `workflow.resolved.json`。不要直接复制旧任务site作为生产入口。
- API上限还受effort约束：当前standard默认最多6次尝试、2轮；共享site的12/3不是每轮自动送满。准备配置本身不调用API、不运行仿真。

## 4. 远程 Spectre / Virtuoso

### 4.1 实际连接入口是 bridge 的 .env

本工作区近期固定DUT仿真使用 `SpectreSimulator.from_env()`。源码的选择顺序是：显式/运行时指定env文件 → 从当前目录向上寻找含VB配置的`.env` → 接收方用户目录 `.virtuoso-bridge/.env`。

因此建议在**解压工作区根目录**建立自己的`.env`，避免无意读到上级目录或别的项目设置。最小单主机示例：

```dotenv
VB_REMOTE_HOST=your-eda-host
VB_REMOTE_USER=your-user
VB_SPECTRE_BIN=/your/cadence/path/bin/spectre
# 若还需要加载EDA与许可证环境，填写实际脚本：
# VB_CADENCE_CSHRC=/your/environment/setup.csh
# 有跳板才设置：
# VB_JUMP_HOST=your-bastion-host
# VB_JUMP_USER=your-bastion-user
```

详细字段参照 `virtuoso-bridge-lite/src/virtuoso_bridge/resources/.env_template`。其中端口的 `{remote_port}`、`{local_port}` 是模板占位符，不能原样当成端口使用。单独Spectre任务不必为了出报告强行启动Virtuoso GUI；需要GUI/ADE交互时再按bridge文档配置相应服务。

主机分离时可分别配置 `VB_GUI_HOST`、`VB_DEPLOY_HOST`、`VB_DAEMON_HOST`、`VB_SPECTRE_HOST`。选择 `VB_SSH_BACKEND=paramiko` 时须安装对应可选依赖；不用该后端则无需安装它。

### 4.2 servers.yml 与 SSH

按 `config/servers.example.yml` 修改 `config/servers.yml`：`host`、`user`、`key`、`tools`、`role_mapping`。单账号示例使用名为`default`的服务器；多账号则明确verifier等角色映射。确保其目标与bridge的`.env`一致，避免上层计划与实际仿真落到不同主机。

SSH私钥路径和用户目录配置需要在接收方机器上可用。按自己的SSH方式配置 `%USERPROFILE%/.ssh/config` 或ssh-agent，并验证相同账号能够登录。只在servers.yml中写key路径，不意味着 `from_env()` 会自动读取该key；bridge实际使用的SSH身份也要可解析。

远端还须具备：Spectre可执行文件、有效许可证、可写运行目录、所需模型及include文件、正确的模型section。历史deck中出现的 `/tmp/...` 模型暂存路径通常不具备可迁移性，应在**新任务目录/新夹具**中重新登记并上传依赖，不改历史DUT或旧日志。

网络代理按接收方实际环境配置。AGENTS.md中原机器的代理端口/证书做法不是新机器的通用配置，不要直接套用。

## 5. 评审 API、effort 与环境说明

### 5.1 config/reviewers.yml

参考 `config/reviewers.example.yml`。配置接收方确实可访问的接口和模型，不要求照搬示例中的所有供应商：

```yaml
reviewers:
  primary:
    provider: openai-compatible
    model: YOUR_AVAILABLE_MODEL
    api_key: "${REVIEW_API_KEY}"
    base_url: "https://YOUR_ENDPOINT/v1"
    enabled: true
    timeout: 120
```

实际key使用接收方的环境变量或经其确认的本机配置。`${REVIEW_API_KEY}`必须在**启动代理/项目Python的进程环境**中存在；这个reviewer加载器不会自动读取bridge的`.env`来补API key。在另一个终端中临时设置变量，不会自动传入已经打开的代理进程。

standard从已启用项中选择1个reviewer。配置文件可解析不等于端点可用；真正的连接测试或review会访问外部服务，应在接收方确认服务范围后运行。不要把 `review_bridge.py check` 当成纯离线命令。

### 5.2 config/effort.yml

默认保留：

```yaml
default_effort: standard
```

Recovery只继承档位，不继承正向规格、调参权限或收敛结论。standard及以上会执行analog-evolve的recovery分支并准备同wiki归档。模型选择与effort分别设置，配置了standard不等于主代理自动切换模型。

### 5.3 根级 _local 配置

如没有 `_local/context.yml`，可新建一份简短环境说明，写明接收方主机用途、模型根目录、运行目录、初始化脚本和路径约定，不放API key。它帮助代理选路，不替代`.env`、reviewers.yml或servers.yml。

标准下载使用 `tools/sanitizer.py` 时会读取 `_local/sanitize-map.yml`，其格式是平铺替换表，例如：

```yaml
"E:/AI/analog-agents-v0p1": "<WORKSPACE>"
"/home/your-user": "<REMOTE_HOME>"
"your-eda-host": "<EDA_HOST>"
```

填写真实需要替换的标识，并检查下载后的sanitized副本。当前发送方部分历史任务用了局部替换表，那不是新机器的全局配置。根级 `_local/site.yaml` 若存在，仅按实际调用它的技能配置；不要新建一个同名文件并假定recovery会读取它，recovery入口使用的是前述 `_local/site.json`。

## 6. 技能与文档输出依赖

### 6.1 使用打包的维护源

| 能力 | 本包内路径 |
|---|---|
| recovery编排、取证、报告 | `skills/analog-recovery*` 三个目录 |
| evolve、wiki、分析/预审/验证 | `skills/analog-evolve`、`analog-wiki`、`analog-learn`、`analog-audit`、`analog-review`、`analog-verify` 等 |
| Spectre、Virtuoso、netlist、optimizer | `virtuoso-bridge-lite/skills/` 下对应目录 |
| Word文档技能 `documents` | 发送方由代理插件提供；不在上述项目技能目录中，接收方须核对自己的插件/技能环境 |

发送方机器的 `.codex`、`.gemini`、`.dsh`、`.zcode` 全局技能入口曾映射到发送方工作区；**工作区ZIP不会在另一台电脑自动建立这些用户目录映射**。接收方按自己代理支持的技能发现方式，把入口指向当前解压目录，不要保留指向发送方盘符的链接，也不要只复制SKILL.md而漏掉scripts/references/assets。

若尚未配置全局入口，可先明确让代理读取当前工作区 `skills/analog-recovery/SKILL.md`。辅助技能位置也须可定位；缺少 `documents` 时需提供等效渲染与逐页审阅能力并如实记录，不能仅生成DOCX就宣称报告交付完成。

### 6.2 Word、字体与模板

- 当前 `render_report.py` 调用Windows Word COM。需要Microsoft Word桌面版已安装、完成首次启动及许可初始化。只有python-docx不能替代这一渲染步骤。
- 支持Windows PowerShell 5.1或可用pwsh；不要求为了这套入口强制安装PowerShell 7。
- 包内 `skills/analog-recovery-report/assets/fm-analog-v1/` 含模板、profile及章节契约。通常不用修改；不能换了template.docx却沿用旧hash/profile。
- 近期FM524绘图使用 `C:/Windows/Fonts/msyh.ttc`。接收方要确认字体可用；若使用其他中文字体，在新任务绘图脚本中显式选择并重新检查排版，不全库替换旧图。

## 7. 哪些历史文件不要批量改

保留原wiki、项目、证据、报告和WORK历史。不要为了换盘符，对整个工作区批量替换 `D:/AI/...` 或用户名。

需要修改的是**活动配置和新任务绑定**；旧 `WORK_*/site.json`、workflow、manifest、trace、report_map、运行日志中的旧路径和hash是历史记录。直接批量替换会破坏追溯关系。

新任务采用当前根目录和新的 `WORK_*`。读取历史材料时，先依据工作区相对位置定位；若旧产物只含发送方绝对路径而校验器不能直接消费，应在新任务记录路径映射/重建绑定并保留原文件，不伪称旧运行在新机器重新执行过。

无需修改：DUT参数、原wiki索引结构、原项目收敛记录、parser、evolve_engine和模板工具实现。出现环境问题先查配置，不为绕过校验重写工具。

## 8. 首次启动检查顺序

以下从工作区根目录执行。先离线，再验证外部服务，最后跑真实项目；不需要先重跑全部历史测试。

### 第一步：离线导入与路径

```powershell
.\.venv\Scripts\python.exe -X utf8 -c "import sys,yaml,docx,PIL,pymupdf,virtuoso_bridge; print(sys.executable); print(virtuoso_bridge.__file__)"
```

两条路径应属于接收方当前工作区。然后核对site的五个路径及实际文件，确认主技能和辅助技能都可读取。

### 第二步：只准备一次只读任务

```powershell
.\.venv\Scripts\python.exe -X utf8 skills/analog-recovery/scripts/resolve_workflow.py --repo . --run-dir WORK_RECEIVER_SETUP_CHECK --read-only
```

它只在新目录生成计划，不发API、不跑仿真、不写wiki。该目录已存在时用新的名字，准备器拒绝覆盖。检查生成的 `workflow.resolved.json`：根目录正确、仿真/API禁用、wiki策略为read_only；pending表示尚未执行，不能当通过记录。

### 第三步：准备生产配置并核对状态

确认接收方允许使用所配置服务后，按第3–5节完成生产配置，再执行：

```powershell
.\.venv\Scripts\python.exe -X utf8 skills/analog-recovery/scripts/resolve_workflow.py --repo . --run-dir WORK_RECEIVER_PRODUCTION_CHECK
```

这一步仍只准备配置。期望需要的服务显示可用计划；`configured_not_executed`不等于API已连接，`blocked_configuration`要先查reviewer环境变量、模型及配置；`remote_execution_allowed=true`不等于SSH、许可证和PDK已经验证。

### 第四步：实际运行前的小范围验证

在已确认授权的范围内检查SSH、远端Spectre/许可证/模型与一个有限夹具；检查一次配置的reviewer真实返回；用现有小文档检查Word渲染及中文字体。外部连接失败与电路失败分开记录，已有通过的检查不重复。

之后给代理的项目任务可以简写为：

> 使用本工作区 analog-recovery，对【DUT路径】重建设计说明书，输出到新的 WORK_【项目名】目录。按已配置的 standard 流程执行，保留固定DUT，复用同wiki及有效证据；wiki先准备差异。

首次环境配置未完成时，不要直接让代理复跑历史任务脚本；这些脚本可能保留原主机、绝对路径、模型暂存位置或固定输出目录。

## 9. 配置失败时先看哪里

| 现象 | 优先检查 |
|---|---|
| Python不存在、导入落到旧盘符 | `.venv`基础Python、editable安装路径 |
| shared site绑定错误/指向旧WORK | recovery的`_local/site.json` |
| servers已改但仍连旧主机 | 工作区/上级目录/用户级bridge `.env`，是否选了profile |
| SSH成功但Spectre启动失败 | Spectre路径、初始化脚本、许可证环境、远端权限 |
| include/model/section错误 | 当前DUT所需模型及新任务依赖上传/路径绑定 |
| reviewer配置阻断或401/404 | API环境变量是否进入代理进程、base_url、模型标识及访问权限 |
| 有DOCX但没有PDF/页码未更新 | Word COM、首次启动状态、字体及实际渲染日志 |
| 提示找不到spectre/documents技能 | bridge子目录技能入口、接收方插件配置 |
| 中文JSON读取报GBK错误 | 用项目Python加`-X utf8`，文件保存为UTF-8 |
| 报告partial或wiki待批准 | 阅读实际缺口/停止依据；它不一定是安装故障，也不表示设计收敛 |

维护源码及本次流程改进的定位入口：`AGENTS.md`、`skills/analog-recovery/SKILL.md`、`WORK_RECOVERY_QUALITY_EVOLVE_20260923/DELIVERY.md`。后者是历史维护说明，若ZIP没有该目录，前两个维护入口仍是当前执行依据。

本说明只新增Markdown文件；未检查或改写用户手动生成的ZIP，未修改现有配置，也未验证接收方机器。若ZIP已打好，可将本文件单独随包发送，或手动补入ZIP。
