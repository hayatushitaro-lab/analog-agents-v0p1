# 证据包文件契约（新包 manifest 0.2，兼容读取 0.1）

机器形状以 `schemas/handoff.schema.json` 为准，校验程序使用其实际字段子集，不依赖 pip 包。
同一包包括下列六个 UTF-8 JSON 文件。`report_map.json` 是写作阶段追加的第七个文件。
所有数组里的 id 稳定且唯一；跨文件靠 id 引用，不能以叙述文字作为连接键。

| 文件 | 内容 |
|---|---|
| manifest.json | schema_version="0.2", project_id, reference_assisted, artifacts[], runs[] |
| report_requirements.json | requirements[]：id, section, request, required |
| design_evidence.json | claims[], ports[], modes[] |
| metrics.json | metrics[]：定义、模式、采样集合、原始值和状态 |
| coverage.json | items[]：每条 requirement 的完成状态、引用、缺口解释 |
| review.json | author_id, reviewer_id, independent, checks[], findings[] |
| report_map.json | blocks[]：id, section, claim_refs, metric_refs, stance, text |

## 来源与声明

artifact：id, path（相对命令行 source-root；禁止上跳/链接）, sha256, role, origin。
role 可选 netlist/static_ir/model_metadata/template/run_log/data/calculation/review/reference。
源清单只能收已准入文件。模型全文不作为交接正文；从文件哈希流式读取不等于把模型暴露给 LLM。
新包的计算 artifact 必须登记 input_refs，递归绑定实际数据/日志或直接参数；模型原文用 model_source，仅供脚本/仿真器读取，写作者只消费提取后的 model_metadata。0.1 仅保留旧包读取/回放兼容，缺 lineage 会告警；生产填充要求新建 0.2 包，不能只改版本号或覆盖旧证据。manifest 版本与 quality.schema_version="1"、静态 IR 版本相互独立。

claim：id, kind, statement, source_refs, locator, confidence, uncertainty, impact,
method, alternatives[], verification[], run_refs[]。不适用字段用空字符串/空数组，不能省略。
locator 可为行号、JSON pointer、实例层级、波形名和窗口，但必须足够定位。kind 的含义：

- DIRECT：直接记录连接/配置；用户意见或参考报告独自不能证明电气事实。
- DERIVED：确定性计算，method 给算法、输入和单位换算。
- SIMULATED：实际有效运行；run_refs 指向 manifest 的 runs。
- INFERRED：结构/功能解释；必须写竞争解释、验证需求和不确定性。
- UNKNOWN：不足以成立；uncertainty 写缺什么，impact 写影响哪些结论。

port：name, direction=input/output/inout/supply/ground/unknown, claim_refs。
mode：id, description, claim_refs, drivers[]。
driver：port, behavior=drive/observe/load, setting, claim_refs, external_drive_justification。
强驱输出/双向/未知 pin 必须明确外部条件依据；推荐仅观测，不能拿理想源当角色证据。

## 指标与运行

metric：id, name, unit, kind=SIMULATED/DERIVED, mode_ref, definition, method, scope,
expected_cases[], typical_case_id（无典型则 null）, samples[], status,
reason, impact, next_action, claim_refs。
expected_case：id, conditions（包括电源、温度、corner组合、负载、trim、模型、边界、窗口；可引用单独条件 artifact 的明确位置）。
sample：case_id, value（有限数字）, source_ref, locator, run_ref（DERIVED 为 null）。
不能混合单位或定义后再算极值；变化的维度必须写进 conditions，独立/集成及不同模式分 metric。

run：id, status=valid/failed/partial/excluded, artifact_refs, mode_ref, conditions, fixture_review_ref, reason。
run 的 mode_ref 必须与使用它的 metric 相同，避免把另一模式的结果填过来。
valid 必须关联通过的夹具检查；原始 log、deck 身份与数据分别存档。记录“valid”不能代替检查日志。
status=complete 表示完成当前 expected_cases，不代表自动满足产品规格、完整 PVT 或连续区间极值。
partial 是已测非空子集；unmeasured 无值；not_applicable 有电路依据。后三者必须给 reason/impact/next_action。
表格 min/typ/max 由 check_bundle --summary 生成，每个极值携带 case/source/run。typ 缺失时保持 null。

## 覆盖与复核

coverage item：requirement_ref, status, claim_refs, metric_refs, reason, impact, next_action。
要求不能凭空消失；不适用也需解释。complete 不可引用 UNKNOWN 或未完成指标。
review check：id, subject_refs（claim/metric/mode/run/port/requirement）, result=pass/fail, artifact_refs。
finding：id, severity=blocking/nonblocking, status=open/resolved, affected_refs, description, resolution。
author 与 reviewer 不同仅是最低检查，运行编排还要保存真实代理交接记录，不能虚构两个名字通过门禁。
阻塞问题可修复，也可把受影响技术结论撤回为 UNKNOWN/未测并记录 resolution，不能静默忽略。

### 关键 claim 的声明与复核覆盖

claim 可选字段 `critical_review_required` 为布尔值；true 表示当前交付必须有复核记录的关键结论，false 表示明确未列为关键，缺失表示尚未声明，不能当 false。ANALYST 提议，主代理作为交接包责任人确认并合并（沿用 review.author_id）；REVIEWER 查漏，在既有 findings 中记录漏标，由主代理修订。写作者不能取消标记以绕过复核。

每条 claim 显式标记才算声明完整。关键集合直接取 true 的 claim，复用 review.checks 的 pass/subject_refs/artifact_refs，不维护第二份关键清单。一条 check 可覆盖多个 claim。关键 claim ID 若与 metric、mode、run、port 名称或 requirement ID 重名，因 subject_refs 无类型而判 invalid；其他对象的同名 pass 不计入关键覆盖。

| 状态 | 处置 |
|---|---|
| claims 为空 | 沿用原约束：invalid |
| 全部缺字段 / 部分缺字段 | undeclared / declaration_incomplete；合法但 partial，列声明缺口 |
| 非空 claims 全 false | empty_declared；合法 partial，不能靠空关键集合取得完整就绪 |
| 关键项未复核 / 仅部分有 pass | unreviewed / partial；合法 partial，列缺失 ID |
| 声明完整、关键项非空且全部有 pass | covered；仅本项通过，其他门禁仍决定整体状态 |
| 歧义 ID、非法字段/引用、已有 fail 或 open blocking finding | invalid；不能用另一条 pass 抵消 |

summary 的 `key_claim_review` 是派生结果，包含 status、claim_count、declared_count、required_count、covered_count；不写回输入清单。covered 不自动表示 ready_for_editorial_review，更不证明电气正确。UNKNOWN/INFERRED 的 pass 可以表示其限定或未知处理恰当，不改变原 kind。是否漏标、复核是否充分、记录是否真正独立仍需专业审阅。

兼容：新检查器可读无字段的 0.1/0.2 旧包，但返回 partial 和告警，不改历史文件。0.1 的既有生产限制不变。旧检查器会因未知字段拒绝带新标记的包，不能混用；manifest 和 quality 版本号不随本可选扩展变化。

生产填充的 --check 输出和既有 .build.json 回执保留 `bundle_delivery_status`、`key_claim_review`；合法 partial 可按原规则生成部分文档。valid 或生成成功不是电气签核。production_preflight 的文本集合包含 verification[].figures[].caption，复用 quality.uses 文本匹配及报告快照；这不保证所有 caption 已登记，也不检查图像的真实来源。

快照与语义时效分开：文件改变而保留旧 hash 会被拒绝；重新计算 hash 后沿用旧 pass，结构门禁可能通过，不能证明复核仍适用。REVIEWER 必须确认修改影响及旧认识可继承的范围，必要时更新既有复核依据。本检查不新增逐 claim 版本系统，不自动证明自然语言蕴含、复核时效或任意电气公式。

report block：stance=asserted/qualified/unknown；INFERRED 至少 qualified，UNKNOWN 必须 unknown。
脚本可检查引用关系，不能证明自由文本没有额外断言。独立审阅须核对语句、数字、图端接和来源。

## 调用

```text
python <技能目录>/scripts/check_bundle.py <证据包目录> --source-root <文件根> --summary <新文件.json>
```

返回码 0 表示结构和引用检查通过；查看 delivery_status 是 partial 还是 ready_for_editorial_review。
没有证据时也能做合法的部分交接：登记 UNKNOWN claim、未测 metric 和原因，不创建虚假的 run。
静态工具输出保留原 schema，只在 artifact 中引用；不要用这个手工交接模型替换其精确端接与源码位置。
