# 有界工程一致性检查

`scripts/check_quality.py <quality.json> --source-root <准入根> --out <新结果文件>`；字段契约为 `schemas/quality.schema.json`。不运行仿真、不扫描目录、不自动读取 include。

quality 是当前证据包的检查投影，不是另一套电路真相。由 VERIFIER 提取，REVIEWER 核对来源；没有可靠输入就退回相关问题，不能填一份自洽的虚构图来过检查。

## 连接与控制的判定范围

结果的 `check_scope` 明示：仅检查导线别名/层级绑定；不验证图对原始输入的忠实性，不判断经器件路径和有效控制。`direct_connection_checks` 逐目标记录在提交图中的 reachable/not_reachable。原错误码保留兼容，`unreachable_scan_target` 不等于电气隔离，也不等于控制无效。valid=true 同样不证明控制有效。

电阻或电容两端不能为通过检查加进 edges。经器件关联及工作条件记录在原证据交接中，与直接连接结论分开；相关证据齐全时，导线检查拒绝仍可作为范围明确的诊断交付。是否可以独立驱动、是否实际改变目标、是否完成有效扫描，需要器件/驱动/负载条件或测量支持。目标端名未列在顶层实际端口中，只是继续追踪的线索，不是“不存在任何路径”的证据。

## 最少登记内容

- artifacts：本检查读取的准入文件 id/path/sha256。文件变化必须重新冻结。
- fixtures：source_refs、实际 dut_nodes、连通 edges（仅导线别名/层级端口绑定；不可跨电压源、电阻或晶体管把两端短接，更不能借公共地把所有激励连到 DUT）、scans、domains。只给被检查激励的必要节点，不复制完整模型。扫描 kind=electrical 时查可达性；temperature/corner/load/parameter 时给实际 binding。obs 相同不判错。电源域 low/high/levels 来自该端口条件，不默认 0/主 VDD。
- calculations：目前确定性求值支持 db_ratio（numerator、denominator 为幅值，convention=transfer 或 rejection、reported、tolerance、source_refs）。其他公式交专用可复算脚本和独立复核，不能冒称此检查器全支持。
- metrics：用于显示的 case_ids/displayed_case_ids 应一致；typical_case_id 可以空。range_kind=observed/lower_bound/upper_bound。测试边界不能填成 typical；单点且有预声明典型条件才可填 typ，partial 不自动取消 typ。
- runs：引用运行的 id/status；claims：与证据 ID 对应的 status=supported/diagnostic/unknown、parents、run_refs、qualifier；uses：本次重点复核段落 claim_ref/text/qualification。诊断或未知的适用限制应就近出现，并沿派生链保留。

schema 所有顶层数组须存在；不适用的数组用 []。生产模式检查来源文件，测试专用 verify_files=False 不能作为项目验收。uses 是重点审查集合，不覆盖全部正文；其余正文通过独立报告映射复核，不能声称工具判定所有自然语言正确。

## 生产写作绑定

报告填充器要求 `--quality-packet`。quality.report_snapshot 包含 content_sha256，以及 bundle_sha256 中 manifest/report_requirements/design_evidence/metrics/coverage/review 六个 JSON 的哈希。先完成证据和正文，再冻结检查，不随意重填哈希绕过审阅。

新 evidence manifest.schema_version=0.2；计算 artifacts 必须含 input_refs，递归指向其实际输入数据/日志或直接参数。DERIVED 不因 sample.run_ref=null 而免查输入运行。旧 0.1 可回放但缺 lineage 会告警，不能宣称新增规则已经补证。

质量结果只表示已登记检查通过；节点图真实性、任意公式、未登记段落、因果关系、版图/热可靠性不在自动判定范围。

独立可运行示例：`python scripts/check_quality.py references/examples/quality/quality.json --source-root references/examples/quality`。示例只有合成声明，演示字段和正反例入口，不是项目证据；生产文件替换为实际来源，不能拿示例通过项目验收。

0.2 的 model_metadata 文件必须是真正提取后的 metadata-1 JSON（格式见主编排 external-review）；原模型文件登记为 model_source，只供脚本/simulator 使用，不发给 LLM 或写作者。不能只改 role 名就把原模型当作 metadata。


## 明确刺激目标与测量交接（quality 1 的兼容扩展）

新建电气扫描检查时填写 `scans[].target_nodes`：刺激应到达的具名 DUT 控制端/目标端，所有目标均须属于 dut_nodes 且通过 edges 可达。edges 仅表达导线别名或层级绑定，不能加入晶体管从栅到漏的“因果边”，也不能跨源或器件把地并入。

同一扫描填写 `measurement={node,unit,event,threshold,window,range,source_refs}`，字符串注明测量节点、单位、事件基准、阈值定义、窗口及范围限制。无事件的 DC 测量可注明“不适用：DC”；有时序时写明确单位和基准。measurement.node 必须在 dut_nodes 中，但**不要求与控制端导线连通**。source_refs 指向 artifacts 中实际夹具/数据/定义；文件哈希按既有规则检查。

工具强制检查目标可达、必填字段非空、节点与来源 ID 存在；不会解析事件文字、证明单位正确或重算瞬态指标。这些仍用受控脚本及独立复核。相同响应不证明无效或有效。旧包不带 target_nodes 可继续回放，但返回 legacy_scan_without_target 告警，仅证明接触到某个 DUT 节点，不能称为目标控制验证通过。旧包不原地补填，新任务应交实际局部包、夹具和测量定义；不能把字段通过当作源图真实或测试已成功。
