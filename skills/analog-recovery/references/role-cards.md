# 角色工作卡与技能接入

主代理负责路由；接收任务的代理只执行所分配卡，不整包加载全部 analog 技能。公共交接字段见 [task-routing.md](task-routing.md)。角色是责任边界，不要求一角色一代理。

## 依赖解析（主代理只做一次）

1. 从用户明确的仓库或项目配置解析 repo_root；有复制仓库和旧环境时记录实际 repo_root/python，不混用，不从 skill 安装位置猜源码根。
2. 下文 `skills/analog-*/SKILL.md`、`prompts/`、`shared-references/` 相对 repo_root。确认存在后，把需要的绝对路径和段落名发给代理，记录版本/哈希，不改原正向文件。
3. 缺方法源时查已安装同名技能；仍缺失则记录降级并完成本卡可做内容。执行后端用已安装 spectre 或已授权工具的实际说明；缺执行依赖不得假称已验证。
4. 原技能的调参、默认供电不属于 recovery。外部评审按 external-review.md 和本项目已有授权执行，不因借用技能扩大发送范围，不启动正向阶段。

## ARCHITECT：实际结构分块与集成（大模块）

**技能**：analog-decompose 的接口/边界规则；analog-integrate 的接口验证、局部故障路由；`prompts/architect-prompt.md` 的夹具所有权。排除设计预算分配、重新选择架构。

**输入**：顶层/子块静态 IR、正式端口映射、确认条件、章节需求。

**动作**：沿真实连接分块，逐接口登记电源/偏置/负载/控制来源；把共享反馈和互偏置交一个联合任务；按独立问题派发。返回后核对真实负载、模式和上电依赖，记录独立夹具与顶层差异。

**输出**：分块图、接口/依赖表、子块任务、集成支持/冲突。反馈边允许存在，不为得到无环图改变电路；未解层级仅限制相关结论。

**可选分支预留**：系统交互难以直接分析且已有子块表征时，可提出 behavioral 需求；但 v0.7 尚未实现 recovery VA/替换闭环，按 effort.md 记录延后，不直接启动原正向 analog-behavioral。未来接入须给模型参数来源、有效域、对照误差，模型结果不冒充原 DUT。

## ANALYST：局部原理、指标与夹具

**技能**：analog-learn 的 Study Existing Netlist / Topology Explainer；analog-audit 的静态检查及适用 `checklists/*.yml`。具体尺寸/偏置推导再选读 analog-design；权衡需要时选读 analog-explore，不开启调参。

**输入**：作用域连接包、端口绑定、模型类型/端序 metadata、条件和问题；BG 加载对应 bandgap-tasks 小节。

**步骤**：
1. 从电源、输入、反馈、偏置到输出追踪实际节点/器件，不由拓扑名反填连接。
   对控制目标先按 scope 的成对取证交接具名绑定，再分别说明直接网络关系、器件关联/条件、控制或测量有效性；三者不能用一个“可达”布尔值代替。工具没有分析的关系由有来源的推理补充，未解边界明确保留。
2. 写器件组作用、变化方向、方程及成立条件；直接参数、计算、结构推断分开。用可复算脚本做计算。
3. 给竞争解释及区分观测。列已知量可推导什么，不把可算项全留 UNKNOWN。
4. 选适用 audit 项给依据；经验数值不是规格，auto_checkable 不代表执行过。审计和 reviewer 不重复形式清单。
5. 把问题转为观察节点、条件、单位、窗口、判据；准备版本化夹具，保持 DUT。角色不明时先观察或补连接。

**输出**：绑定实例/来源的原理、尺寸关系、竞争解释、验证需求；端口/模式表、测量方法、夹具版本。只写自己的 tasks/<task_id>/，由主代理合并既有证据包。

**验收**：能沿具体连接解释机制，并说明何种观测会否定解释；不能只有器件列表、常见理论或原作者意图。

## REVIEWER：独立反证

关键 claim 的声明由 ANALYST 提议、主代理确认合并；REVIEWER 查漏并在既有 findings 中记录，写作者不能自行撤销标记。字段和覆盖/兼容规则只在 [handoff](../../analog-recovery-evidence/references/handoff.md#关键-claim-的声明与复核覆盖) 定义。续用旧复核时检查当前结论的语义适用性，重新计算快照不等于完成重新复核。

**技能**：analog-review 的 Reviewer Independence、Divergence；`shared-references/review-protocol.md`。执行时读取 [external-review.md](external-review.md)，通过 recovery_review.py 复用 review_bridge 的传输层和用户指定配置，使用固定电路评审提示。REVIEWER 代理负责组织请求、核对来源和路由 findings；第三方 API 才是外部评审执行者。原技能的票决/人审默认策略按本 recovery 的证据关闭循环适配。

**输入**：准入原始局部连接/IR、端序、条件、待审问题；之后读分析记录、夹具和原始结果。不给预期答案或先前通过标签。

**步骤**：先独立判断路径/符号/边界，再核对主解释；找误连、错误端接、模型端序、遗漏计量、过度推广。每项问题给位置、证据、影响、最小区分动作，不以票数裁决电路。

检查控制结论时，先保存自己的逐目标源观察，再读待审交接。最终逐项对照“源观察—执行结论—是否一致—冲突处理及证据”；发现器件路径却接受无范围的“不连通”，或缺条件却接受“有效控制”，均为未解冲突。修正原观察也需来源依据；整体 PARTIAL/PASS 标签不能关闭具体冲突。只在有误的范围退回，不要求正确的导线检查负结果改成通过。

**输出**：具体 findings、支持项、未解分歧、所读来源；写作前核对主结论和数字。原理/夹具问题回 ANALYST，数据/日志问题回 VERIFIER；不可替代条件交主代理追问。相同模型的独立任务不是跨模型验证，自身复看不是独立审阅。

## VERIFIER：夹具预审、执行与测量

**技能**：analog-verify、`prompts/verifier-prompt.md` 的预审和记录；已安装 spectre 的执行接口；evidence 的 verification/boundaries 与现有检查脚本。

**输入**：准入 DUT、夹具版本、端口/模式依据、模型 metadata、方法和条件、run_id、分配预算。

**步骤**：审驱动/负载、探针和计量，检查计划版协议；检查资源后提交本任务，保存命令、日志、退出码。核验实际条件/有效性，按声明集合算极值与典型点。量纲门禁不代替数值复算。

**输出**：真实运行、measurements、异常、公式/脚本、图数据、引用和资源消耗。旧数据复核不称新仿真。

**权限**：DUT/模型只读；已审夹具不静默改，修改退 ANALYST 或由主代理承担该角色出新版本再预审。修工具须记录版本，不改变被测电路。未授权仿真只准备计划。

## EDITOR：证据到模板

**技能**：analog-recovery-report；使用已有固定模板、填充、检查、Word 渲染工具。

**输入**：冻结证据、校验/复核结果、章节需求和缺口，不发 raw netlist 自由推断。

**输出**：内容、真实 claim/metric 映射、图表、DOCX、同源预览、逐页检查。保留工作条件和未测指标，不改模板禁止修改的部分。

**退回**：新结论或缺数据发带章节号的补证请求；格式问题本角色处理。主代理核验图文/数字与证据再交付。

## 收尾：项目知识

主代理结合 analog-wiki/analog-evolve 记录认识变化，消费 resolved.closeout：standard及以上必须准备同库项目案例归档（summary、trajectory、narrative），即使无新增通用知识也记录本次事实、缺口和“无候选”。已有 wiki_packet 用于定向案例检索；用 tools/recovery_wiki.py prepare、审查差异，并在获批或已有写回授权时apply和读回。归档状态与报告状态分开；旧convergence不改、新项目false。按effort选择知识/checklist/提示词改进候选，后两者只提议。用条件、反例和验证引用决定是否推广，不以循环次数提高 confidence。

## 可执行交接（v0.9）

v0.10 补充：ANALYST/VERIFIER/REVIEWER 读取 `../../analog-recovery-evidence/references/engineering-recheck.md`；REPORTER 读取 `../../analog-recovery-report/references/report-assembly.md`。REVIEWER 最后审正文、图注和对应图源，不能停在中间包。重点是电路分析与数据是否一致，不增加新的角色或签字表。

每个实质分析/验证/复核任务使用 [execution-checks](execution-checks.md) 的 task_card.py 生成并验收工作卡，按风险分配独立责任。只是 resolve_workflow 成功、读过方法或返回 PASS 不算完成。
