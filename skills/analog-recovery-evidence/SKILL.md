---
name: analog-recovery-evidence
description: 分析已有固定参数模拟或混合信号电路，建立接口、模式、原理、指标及验证证据包，供设计报告使用；不优化 DUT，不负责 Word 排版。
---

# 电路分析与取证 · v0.11

输入：已准入 SCS、必要依赖/模型、可选顶层/测试夹具和 `report_requirements.json`。
输出：符合 [交接契约](references/handoff.md) 的证据包；原始运行与来源另存，不覆盖历史。

接受主编排的有界任务，按[角色工作卡](../analog-recovery/references/role-cards.md)只执行所分配角色：ANALYST 借用 learn/audit 的分析方法，VERIFIER 借用 verify 的预审与执行，REVIEWER 借用 review 的反证方法；大模块由 ARCHITECT 组织 decompose/integrate 适配。单独调用本技能时自行承担主编排职责。既有 parser、scope_packet、wiki_packet 和门禁脚本继续复用，不另造重复工具。

取证深度、预审、验证覆盖及复核数量消费同一 `workflow.resolved.json` 的 `role_policy`，映射见[recovery effort](../analog-recovery/references/effort.md)。单独调用时按任务范围准备该配置。借用其他技能不重读正向 effort 覆盖本次计划；所有档位保留关键复核、端接/计量检查与证据标准，原产品条件未知时不套默认规格。

## 1. 结构与模式

- 先使用确定性解析器提取层级、端口顺序、实例、参数和位置。随包静态工具用法见 [静态工具](references/static-tool.md)。不支持的语义保留诊断。
- 按[仓库与连接适配](references/repository-adapter.md)使用scope_packet取得带实例作用域的局部包，并按需检索已有wiki。不能把不同definition内的同名网合并。
- 区分显式连接与电气角色：从器件端接、驱动源、负载和层级绑定判断方向，不能靠 `flag/en/bias` 名称或夹具里的理想源倒推出输入。
- 为每种实际模式登记控制值、供电、参考/偏置来源、负载和反馈路径。依赖顶层的信息再读顶层，不把它作为内部分析的前提。
- 未确认的输出/双向引脚不得强加理想驱动。模式下的目标行为、观察结果、用户预期分开记录；矛盾触发复核。
- 形成功能分块与拓扑假设：支持证据、竞争解释、验证需求、confidence/uncertainty。不能恢复不存在的历史设计意图。
- Bandgap 使用[局部任务卡](references/bandgap-tasks.md)按端口、核心回路、偏置、启动、性能逐项完成；其他类型不能套用 Bandgap 条件。静态分析无需等待夹具或仿真结果。

## 2. 指标与验证计划

- 将模板要求映射到证据需求，依据该电路的功能与模式建立指标，不照搬其他类型清单。
- 按[覆盖与停止检查](../analog-recovery/references/coverage-closeout.md)将主要功能落到已有 requirements/coverage；明确本轮要回答的问题及所需证据，交接时逐项解释完成或停止依据。合法 partial 与关键声明复核通过不代表范围已经完成。
- 先定义量、单位、测量窗口/阈值、矩阵、典型工况及失败判据，再跑仿真。typ 不是平均值；min/max 只属于声明的采样集合。
- 每个模式单独覆盖。仅有 TT 不得自称完整 PVT；SS/FF 不自动等于所有指标最坏角。
- 主动探索适用能力边界：先粗扫、在临界附近细化，保留失败点和判据；不能据此声称热/SOA/可靠性保证。
- 关闭模式保留真实场景中仍在的供电、参考与偏置。分别计量 DUT 电源、注入支路和系统功耗，避免漏算/重复。
- 模型通过脚本/仿真器按需使用，只向推理暴露必要 metadata 和结果。先核对 section 组成、适用范围与重复定义选择。
- 确认仿真权限和预算；已授权范围内自行推进。具体执行复用已安装 `spectre`，审查复用 `analog-audit` 的适用部分。
- 借鉴 `analog-pipeline` 的角色分工，不启动其正向设计、默认规格、调参或自动优化流程。

## 3. 夹具预审与证据闭环

按 [验证门禁](references/verification.md) 复核端口驱动、模式真值、环路探针及 DC 等价后再运行。
新仿真任务按[模式边界与计量契约](references/boundaries.md)登记 `verification_contract.json`，区分计划/结果版并运行 `scripts/check_protocol.py`；未知产品条件不阻止有清楚边界的诊断。
另用 `scripts/check_measurements.py --example` 建立 measurement_packet.json，填入实际 PSF/日志文件路径和哈希，再运行 `python scripts/check_measurements.py measurement_packet.json`。默认生产模式直接读原始文件，不信手抄样本。对应 metrics.json 的仿真电压/电流/功率必须有同 id、同单位的 measurement；所有引用运行使用同 id。该门禁检查量纲，不执行任意公式数值计算。二进制 PSF、时序提取和复合指标需受控转换与独立复核，不伪称已自动验证。
独立复核者读取原始连接和夹具，记录可定位的问题；签字字符串本身不能证明独立性。
执行失败、未收敛、模型报错、错误边界的结果存档并排除；警告下的可用诊断须限定结论，不能当产品通过。数据文件存在不等于运行有效。
未处理的 gmin 显著影响、bad pivot 先保留为 diagnostic 并进行敏感性实验；不能仅改成 qualified 放入性能表。供电依据不足不称 nominal，缺模型有效范围依据时集中追问供电；其他局部分析继续。
运行记录保存真实命令、退出码和原始输出；不能手写预期结果冒充执行记录。校验结果是产物，不反过来作为自身的输入证据。
每次尝试使用新运行目录，包括命令行失败和夹具调试；运行前若目录已存在则换新ID。核对原生日志/PSF中的实际温度、reltol、gmin与夹具声明，不能只检查deck。nodeset所得DC解只证明该静态解，不证明启动或唯一性。
仿真反驳假设时更新假设和覆盖，不改 DUT 追求预期数字。
静态理解、工作点与动态结果互相核对；差异不明时保留争议及影响范围。

## 4. 交接

1. 输出五个文件：`manifest.json`、`report_requirements.json`、`design_evidence.json`、`metrics.json`、`coverage.json`；另加 `review.json`。
2. 每条技术声明使用 DIRECT / DERIVED / SIMULATED / INFERRED / UNKNOWN，并引用源位置、计算或运行。
3. 各指标包含原始采样、运行引用、条件、典型工况；由脚本计算极值，禁止手写与原数据分离的指标表。
4. 未测/部分/不适用分别说明原因、影响和下一步。不适用需要电路依据。
5. 执行 `python scripts/check_bundle.py <bundle目录> --source-root <准入文件根目录>`。
6. 向写作方交付校验结果和缺口。静态 IR 是支持材料；本技能的证据包是独立交接层，不覆盖旧 IR schema。

解释如何工作、现有结构的收益和代价是任务内容；声称原作者“为了某目标所以这样设计”需要原始依据。

## 工程一致性（v0.9 编排）

矩阵前和写作前按 [quality 契约](references/quality.md) 检查激励可达性、条件/公式及结论限制。新 manifest 用 0.2 并登记计算 input_refs；既有证据不原地改写。任意因果解释仍需独立复核。

分析与最终交接必须执行[工程交叉复核](references/engineering-recheck.md)：核对真实控制可达性、典型工况、图源与正文数字、异常和范围结论。直接补充原有证据/复核记录，不新增人工哈希表。REVIEWER 必须审查最终正文和图注，不能只审通过的 JSON。
