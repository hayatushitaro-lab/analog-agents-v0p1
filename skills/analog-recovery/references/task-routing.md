# 有限任务交接

目标是让执行者每次处理一组可验证的问题，不把全部 references、模型和网表塞进同一轮。主代理记录问题与进展，取证者处理局部任务；独立复核针对原始证据，不仅看摘要。小模块可以串行完成这些角色任务，独立复核缺失必须标明。

## 子代理交接包

按[角色卡](role-cards.md)选择角色，用 [execution-checks](execution-checks.md) 的 `task_card.py prepare` 生成 `tasks/<task_id>/task.json`，不再维护另一套手写字段示例。它是方法交接记录，不替代 evidence/handoff schema，也不是自动调度器。

生成卡已有 role/question、methods（实际路径、hash、阅读主题）、inputs/outputs（path/sha256）、acceptance、method_results、实际 agent、closure；scope/confirmed_conditions/unknowns 和 permissions/resource_allocation 沿用当前任务范围。主代理填入授权及资源，准备命令不自行授予仿真或外发权限。

permissions.write_roots 默认仅本卡目录；输出不得别名覆盖输入。actual model、effort、是否 delegated 和是否支持模型选择分别记录。卡完成后运行 check；partial/blocked 卡可记录有用产物，但不能得到 completed 验收。

实际包不能保留占位文字。inputs 是只读白名单，不自动许可目录内其他历史产物；include 仍按既有规则准入。当前问题的原始连接、端序和条件必须给齐，不能只说“去看整个项目”。输出目录互不重叠，子代理不得直接改合并证据、其他任务输出或原始文件。

返回时给 `task_id, status, outputs, evidence_refs, findings, unresolved, resource_used, next_action`。status 为 complete/partial/blocked，complete 表示完成所派问题，不表示产品性能通过。主代理检查来源、证据分类和验收内容，更新任务表及迭代日志后才路由下一步。

读取记录必须来自实际工具结果：记录准确绝对路径、哈希和成功/失败；不能凭记忆重写路径或把补读登记为首次已读。主代理核对返回路径存在、属于任务准入集合及哈希一致；自报 `actual_skill_reads` 本身不证明读取或采用了方法。任务消息追加准入时，同步写入带时间的追加记录，不留下消息与 task.json 两套白名单。更正单独追加，保留首次错误记录。

write_roots 是实际可写范围：ANALYST 的新夹具、VERIFIER 的新运行、REVIEWER 的审查片段、EDITOR 的报告均在分配根下；合并 evidence/review.json 由主代理写。禁止覆盖原输入、旧版本或其他任务产物。已有 BG 卡的 PASS/PARTIAL/BLOCKED 是卡级状态，分别映射任务 completed/partial/blocked；PASS 只表示该卡验收完成，不是产品指标通过，不能修改运行有效性状态。

有有效局部产物但需退回时返回 partial；问题完全无法推进时 blocked。findings 含 affected_refs、category、return_role、required_action。执行环境/解析实现问题回 VERIFIER；测量定义、端口端接、模式或激励改变回 ANALYST 出新版本再预审。缺产品条件回主代理。

### 非 BG 子块与共享接口的最小卡

主代理为每个局部问题分配唯一 question_id，不按电路名称预填答案。沿用同一任务包，至少包含：正式端口/层级绑定、相关驱动和负载连接、条件来源、所需模型端序。ANALYST 输出连接链、主解释/竞争解释、条件性方程、验证需求；验收要求来源可定位、接口不漏项、未测不冒充性能。

共享偏置/反馈任务由 ARCHITECT 给出接口两侧的 occurrence_paths 和边界，指定一个联合 owner；核对供电/回流、驱动负载、模式与计量面。输出 standalone 与 integrated 条件差异、受影响 claims/metrics；只有联合证据支持才形成系统结论。未知范围列待确认或诊断范围，不补额定值。本通用卡支持局部推进，不宣称等价于完整 LDO/ADC/PLL 专用指标卡。

验收失败给具体 finding 与负责角色；新版任务引用被替代版本和复用证据，保留首次结果。写作者不得在返回中增加未登记的技术事实。复核者不能只读取被审者摘要；独立性与实读范围写进 review 记录。

## 默认次序

| 任务 | 本次读取 | 输出与进入下一步的条件 |
|---|---|---|
| 章节需求 | 固定模板 requirements.json | 建立 report_requirements.json；明确当前模块适用指标，不读模板示例数值 |
| 端口/供电 | 静态 IR、scope_packet 局部连接、模型 metadata | 完整端口角色表；每种端接的证据；供电依据及 diagnostic/confirmed 区分。角色未定不注入理想源 |
| 原理/尺寸 | 核心回路局部包、相关类型任务卡 | 因果链、条件方程、关键器件参数、竞争解释；不是仅列模型名称 |
| 最小验证 | 上两项、boundaries/verification 契约、Spectre 执行技能 | 夹具预审通过；已保存必要信号；异常有记录；有效点后再做范围/模式覆盖 |
| 独立复核 | 原始局部包、实际夹具、原始结果单位和完整日志 | 具体问题及定位、解决或结论降级；不能仅签 pass |
| 章节内容 | 已验收证据包、requirements.json、sections.md | content.json；指标/接口/图对应证据；技术缺口明确 |
| 文档生成 | content.json、随包模板与固定生成器 | DOCX/trace→字段更新→PDF→逐页检查；不重新分析 raw netlist |

Bandgap 的类型任务卡使用 evidence 的 `references/bandgap-tasks.md`，另按角色加载必要的 analog 方法段落。其他模块按其功能建立局部问题，不能套 Bandgap 默认参数或验证项目；当前尚无完整 LDO/PLL/ADC 类型任务卡，不宣称已覆盖所有电路。

每次任务交接包含：question_id、相关实例范围、允许读的输入路径、需要回答的问题、预期输出、验收方法、当前阻碍。使用 recovery-iterations.jsonl 记录 before/action/evidence_refs/after/remaining/next_action/stop_reason，不用“读文件、跑仿真、写报告”三行代替推理轨迹。

交接时直接附当前任务必需的连接包、来源和已确认条件，以及所需 reference 的准确路径；不要只说“读 skill 后分析整个模块”。接收方先核对输入是否足够执行，缺口明确到字段/节点/文件。共享记忆或 wiki 保存方法和失败经验，当前项目条件保存在条件记录，不能要求新任务继承旧对话。

## 首个可验收闭环

复杂流程首次试用或失败修复时，先完成一个小闭环。例如 Bandgap 的有效 OP → 明确范围温度采样 → VREF极值与曲线 → 1.3/1.8 → 同一DOCX的PDF。先声明采样集合、参考点和所需输出；供电、温度、trim、负载、模型、有效性检查缺一项都不能靠文字补齐。其他模块选择其适用的一项核心指标，不强制套温度扫描。

独立验收分开报告：

- 分析是否解释了实际路径及条件；不是统计claim数量。
- 执行是否有完整真实日志、物理上可解释的结果；不是检查PSF文件存在。
- 表格是否保留工作条件和所需指标，采样极值是否自动生成；不是只有JSON合法。
- DOCX是否成功打开并导出同源预览，图表和章节是否可读；不是另做PDF兜底。

有限任务复测给执行者同一输入、条件、工具和验收要求，不给主代理答案；保留首次结果、主动修复和外部介入记录。局部复测通过只说明该环节改善，不宣称整份报告或新项目已泛化成功。

## 停止与降级

- 缺原始规格不阻断内部功能分析；未知实际电源且无模型有效范围依据时集中追问，不随意指定 nominal。
- DC 结果接近预期电压不是停止条件。先查电源、端口合规范围、主要支路电流、告警和零电流解。
- 缺仿真极值时只能写单点或未测。为缺口记录具体阻碍及累计已耗时间，不泛称“受预算限制”。
- 准备交付部分报告时检查：是否仍有可低成本完成、且影响主结论的局部任务。若有，先执行；若无，说明停止原因。
- wiki 是补充方法而非当前电路证据。不能通过多轮互相引用将推断升级为事实。
