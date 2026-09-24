---
name: analog-recovery
description: 从已有模拟或混合信号电路实现重建设计说明书，编排固定电路取证、独立复核和模板写作；适用于反向文档重建，不执行电路设计或调参。
---

# 电路反推设计文档 · v0.11

先解释电路并建立可信证据，再写工程师可用的报告。DUT 参数固定。
本套包含同目录下的 `analog-recovery-evidence` 和 `analog-recovery-report`；缺少任一项时说明缺项。

## 起步

1. 确认用户允许的 SCS、依赖、模型、输出目录和仿真预算。CDL 可选；默认使用随包 fm-analog-v1 标准模板，只有用户换模板时才适配新模板。
2. 沿用已授权范围；先检查 include 路径和来源再准入。不改原网表、模型、模板或历史运行。
3. 生产续作先按 evidence 的[仓库适配](../analog-recovery-evidence/references/repository-adapter.md)选读同线路案例及必要证据，登记可继承认识、条件与修订。用户允许的历史资料可用作线索，不自动成为当前事实；严格盲测另行声明。最终索引和必要证据必须在当前工作区内。
4. 默认从写作技能 `assets/fm-analog-v1/requirements.json` 取得章节契约，不让执行模型重新解释 Word 模板。按[有限任务交接](references/task-routing.md)分阶段取证，报告内容交确定性填充器。
5. 自主推进与集中追问按[决策规则](references/autonomy.md)执行；只有用户明确要求盲测/模型试验时才进入该文件的独立试验分支。
6. 以 [recovery 编排](references/recovery-pipeline.md)管理阶段和退回；按[角色工作卡](references/role-cards.md)分派任务、技能与写入目录。吸纳 analog-pipeline 的中央调度和交接纪律，不启动正向调参。
7. 按 [effort 配置](references/effort.md)使用 `scripts/resolve_workflow.py --repo <repo> --run-dir <WORK_TASK>` 准备当前任务的 workflow/site 和角色计划。继承 `config/effort.yml` 的档位，默认 standard；普通完整报告按已建立的项目使用约定安排验证及配置的 reviewer，显式只读/禁仿真/禁API等限制优先传入准备入口。各角色消费同一 `role_policy`，不再次套正向 effort 的规格/调参规则。主代理须实际推进阶段，准备成功不等于执行完成。
8. 当前任务已授权第三方发送且已配置评审时，按 [外部评审与修订循环](references/external-review.md)及显式 `--site <本工作区内的site.json>` 实际调用 API：分析→初审→定向修订→验证→结果复审。主代理路由问题，责任角色修复，不用主代理自身审查替代外部调用；授权沿用当前项目约定。
9. 开始分析或验证时读 [v0.9 执行与验收](references/execution-checks.md)：实际生成工作卡、登记方法产物，矩阵前核对刺激作用路径，写作前冻结证据版本。角色名称、技能阅读和 API PASS 都不是验收证据。

## 证据到报告交接

1. 调用 `../analog-recovery-evidence/SKILL.md`：分析实现、定义模式/指标、生成和复核证据包。
2. 运行该技能的 `scripts/check_bundle.py`；新仿真任务另运行 `scripts/check_protocol.py` 和 `scripts/check_measurements.py` 的独立电气门禁。错误先修；量纲/端接错误不能通过 partial 或 qualified 消解。未完成的有效内容可交付，技术错误仅作诊断产物。
   新包 manifest 用 0.2，计算 artifact 登记 input_refs；按 evidence 的 quality 契约执行有界一致性检查。旧包可只读回放，不把缺失 lineage 自动补成已验证。
   冻结前按[覆盖与停止检查](references/coverage-closeout.md)核对本轮主要功能和关键问题；已有授权、可执行且有信息价值的缺口继续交责任角色，不能以“报告可生成”结束补证。真实阻塞允许部分交付，不要求用满预算。
3. 调用 `../analog-recovery-report/SKILL.md`：只从证据包填模板、出图、生成并渲染 DOCX。
4. 写作发现问题时发回补证请求，注明影响章节；只重跑受影响步骤。不能让写作者用 raw netlist 补洞。
5. 交付 DOCX、预览、证据索引和未验证清单。阶段间不重复要求批准；只有新增访问或不可替代的关键信息才集中询问。
6. 用逐项落实清单区分写作修订、电气已测与剩余缺口；定向修复不能声称全部评语已完成。
7. 执行 S7：standard及以上主代理加载并执行本仓库 [analog-evolve](../analog-evolve/SKILL.md) 的 recovery 分支，按 resolved.closeout.evolution 复盘；随后准备同一 wiki 的项目案例归档及有依据的知识候选，复用[写回接口](references/wiki-writeback.md)。无可推广知识也记录实际复盘/去重结果并归档案例。交付分别登记 evolve 执行、引擎执行、候选和应用状态；准备计划不算技能已执行。获批或已有写回授权后应用，不把报告完成当设计收敛。checklist/技能改进仍只提议，授权范围以当前任务为准。

## 角色与资源

- 主代理管理条件、任务、资源和证据合并；分析者解释电路并准备夹具，验证者预审后执行和测量，独立复核者检查解释与结果，写作者只消费证据。职责和具体借用技能见角色工作卡。
- 默认小模块由主代理承担分析和夹具准备，子代理承担独立复核；授权仿真时可将验证单独委派。大模块按明确子块边界并行分析，主代理整合集成条件。不是每个技能都启动一个子代理。
- 模型和推理档位服从当前用户/任务选择，未指定则继承，不固定到特定型号。用户要求单代理时不派发，独立复核缺失如实记录。
- 小模块不建立庞大团队。大模块才拆独立子模块任务，按边界文件交接，最终检查反馈和共用偏置。
- 无子代理能力时完成单代理工作，但标记独立复核缺失，不宣称等价验证。
- 默认验证约定的主要指标矩阵，主动探索适用能力边界；不机械套全部分析类型。
- 运行前看服务器现有任务、资源和配额；不结束他人进程。预算/并发/超时在运行前登记，失败也计费。
- 预算耗尽或模型失效时交付明确标注的部分报告，不无限试错，也不把“未测”改成“不适用”。

## 验收

v0.10：证据角色按[工程交叉复核](../analog-recovery-evidence/references/engineering-recheck.md)执行；写作角色按[实际装配工作卡](../analog-recovery-report/references/report-assembly.md)执行。由同一 verification 清单自动生成 1.6 表格及 1.8 图文子节，并覆盖 1.3 指标。独立复核包含最终正文和图注；不以通过格式校验代替电气判断。不需要用户在启动 prompt 重述章节规则。

关键数字有条件和来源；接口与模式有证据；极值出现在指标总表；图文端接一致；未知不冒充事实。
另检查普通工程师是否能顺着“用途→原理→实现→验证”读懂，不让审计细节淹没正文。
本版通用的是流程与交接契约。新电路类别的分析正确率、规模上限需要独立项目验证。
