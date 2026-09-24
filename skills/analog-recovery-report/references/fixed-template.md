# 固定模板 fm-analog-v1

默认使用随包 `assets/fm-analog-v1/template.docx`。它是已批准模板的不可变副本，hash 绑定 profile。此版本只支持单模块 1.1–1.13；新模板、多模块排版需要单独适配，不能改默认脚本索引迁就新输入。

执行模型无需重新解析 DOCX，也不要为每个项目编写 Word 填充脚本。阅读本文件和 `sections.md`，只准备结构化内容。模板路径不再是用户 prompt 的必填项。

## 操作

1. 执行 `python scripts/fill_template.py --requirements <新目录>/report_requirements.json` 导出兼容证据包的需求清单，再执行 `--example <新目录>/content.example.json` 得到全部必填槽位和数据结构。合成文字不能作为真实项目内容。
2. 写 `content.json`：保留 template_id；填写封面元数据、evidence_ids、expected_ports、sections、verification。证据 ID 必须来自当前已通过检查的证据包，而非为了通过填写器而临时虚构。
   1.3 还必须填写 `condition_rows`，固定保留供电和温度两行；每行字段为 `quantity`、8 个 `cells`、`refs` 和 `source_kind`，其中 `quantity` 取 `supply_voltage` 或 `temperature`，`source_kind` 取 `DIRECT`/`DERIVED`/`SIMULATED`/`INFERRED`/`UNKNOWN`。例如：
   ```json
   "condition_rows": [
     {"quantity":"supply_voltage", "cells":["工作条件","VDD","供电电压","UNKNOWN","—","—","—","V"], "refs":["C-VDD"], "source_kind":"UNKNOWN"},
     {"quantity":"temperature", "cells":["工作条件","温度","环境温度","UNKNOWN","—","—","—","°C"], "refs":["C-MODEL"], "source_kind":"UNKNOWN"}
   ]
   ```
   条件行不设置 `metric_ref`，不要把用户条件写成 DERIVED 性能 metric；v0.4 旧内容升级时补两行 UNKNOWN，缺任一行时填写器会明确报错。
3. 每节 status 使用 supported/partial/unverified/not_applicable；后三类填写 reason。paragraphs 每项含 text 和 refs。rows 每项含 cells 和 refs；接口行另含 ports，明确覆盖的每个位。指标表 8 列固定为类型/符号/说明/条件/min/typ/max/单位；每行增加 metric_ref，指向证据包指标。生成器重新校验证据包并自动覆盖条件、数值和单位，单点不冒充范围。
4. figures 每项包含 path/caption/kind/refs；kind 为 concept/connectivity/simulation，simulation 必须引用有效运行和图数据。先分析再出图，不以此生成器代替分析。
5. verification 按验证对象分组；每项 title、refs、labels。labels 必须且只含“仿真工具、仿真路径、仿真方法、结果分析”。后续扩展统计表必须适配单位，不能沿用模板 nA 示例。
6. `python scripts/fill_template.py --content content.json --bundle <证据包目录> --source-root <准入文件根目录> --measurement-packet <measurement_packet.json> --quality-packet <quality.json> --out draft.docx`。有仿真指标时必须提供电气门禁包（纯静态无仿真可省）；其 measurements 的 id/unit 对应 metrics.json，runs id 对应真实运行。脚本重新检查实际来源文件，拒绝虚构ID和覆盖旧输出，生成 trace。独立合成测试才使用 `--synthetic`，项目名必须以 SYNTHETIC 开头。草稿不是最终交付。
7. Windows 有 Word 时，使用 `python scripts/render_report.py <draft.docx> --out <新目录>`。自动选择可用 pwsh 或 Windows PowerShell 5.1；每次尝试有超时，PDF 失败最多一次 PNG 回退，仅操作新副本，保留目录和页码域。只清理本任务通过窗口句柄识别且创建时间一致的新 Word 进程。未知进程不结束。其他环境使用 documents 渲染工具，明确缺失检查。旧 finalize_word.ps1 保留兼容，仍需 PowerShell 7；新流程不再依赖它。
8. 渲染 PDF 每页检查，核对图、表和分页。所有预览使用新目录；确认页数一致后记录 qa.json 和最终 DOCX/PDF hash。运行 `--audit <最终report.docx>`，并将所有技术块 trace 与已通过检查的证据包对照。

## 已固化/尚需判断

已固化：模板标题、原生编号和符号、表格头及网格、正文黑色非斜体、指导和示例整体排除、1.8 标签不编号、证据引用和接口覆盖、拒绝旧产物覆盖。

生成器不能证明引用支持自然语言，也不能从正确字段推出电路正确。status=supported 是待复核声明，不是自动技术签核。verify 阶段仍需电气门禁；正文中的公式/数字需要与证据逐项核对。另按[工程阅读准则](engineering-writing.md)审阅可读性、主要发现与使用条件，不把结构通过当作报告质量通过。

已有子章节承载内容的父标题（如接口定义、设计实现）允许只保留标题，不为每个父标题添加重复概述。reason 是具体缺口说明，不是所有章节重复粘贴的免责声明。

当前电气门禁自动检查 V/A/W 及相应 SI 前缀的量纲；ppm/℃、dB、时间等复合指标在 `.electrical.json` 中列为 requiring_independent_review，不能声称已通过量纲自动验证。所有有运行引用的指标仍须绑定该门禁接受的运行。原始数值抽取与任意公式求值尚未统一进此门禁，独立复核仍不可省略。

固定模板含原厂 logo/版权及样式，仅用于用户授权的项目文档，不代表公开分发许可。不将项目许可、后端空白政策、默认电压写入通用模板契约。

## v0.9 预检与语义槽位

v0.10 装配更新：先读 [report-assembly.md](report-assembly.md)。verification 新增必填 id/category/status/description/metric_refs，支持子节 figures；1.6 表格自动生成，禁止章首堆放仿真图。旧 content 需在新目录显式迁移；旧 DOCX 和证据包不覆盖。`--example` 已返回新结构。

正式生成前以相同参数加 `--check` 聚合检查，不写 DOCX。quality-packet 依照 evidence/references/quality.md 建立，绑定当前 content 和六个 bundle 文件。

接口行除了 cells/ports/refs，必须包含 interface={name,direction,hysteresis,fan_in_out,description}，值按此顺序与五个 cells 一致；迟滞/扇出未知直接填未确认，不填电源域。命名字段不能自动理解语义，仍需独立复核。

已知电源、温度值放 cells[4:7] 的 min/typ/max，未确认项留未知。条件来源（用户验证条件/原始规格/推断）写入条件栏和 source_kind，不把用户指定条件改名原始规格。

指标条件由样本选择自动覆盖；单点不自动成为典型点，测试上下界采用 quality.range_kind 并单独说明，不填写为能力典型值。

固定模板检查配置已提供 assets/fm-analog-v1/check-profile.json，与布局 profile.json 不可混用。check_docx 省略第三参数即使用该配置：逐验证子节检查四标签、保留 PAGE/NUMPAGES。生成 build.json 绑定正文、模板、填充器、quality 和 DOCX 哈希；渲染另记录最终文件哈希。渲染成功不等于逐页视觉验收。
