# 固定电路的第三方评审与修订循环（v0.9）

此文件是 REVIEWER 的执行卡。复用 analog-review 的独立性/分歧原则及 `tools/review_bridge.py` 的配置读取和 API 传输函数；不运行原工具的正向 `review` 命令，不复用其规格达标/调参提示，不改原仓库。

## 本机依赖与默认执行

通过必需参数 `--site` 读取准备器生成的本任务 run/site.json，共享默认值来自 skills/analog-recovery/_local/site.json，字段见 site.example.json。repository_root、reviewers_config、project_root、run_dir 必须属于当前工作区，python 使用该仓库环境。project_root限制来源范围，run_dir绑定本任务与账本；每个packet仍显式限定问题和文件。配置存在不代表其他项目授权发送；沿用当前项目已明确的发送范围，不继承旧试验授权。凭据不进入模型上下文。

运行时以实际 reviewers 配置为准，按resolved.role_policy.REVIEWER及review_transport.reviewer_batches把名称写入packet.reviewers：lite/standard取1个，intensive取2个，exhaustive覆盖启用项并按每包最多2个分批；各批共享同一个run与总额度。只有一个就调用一个并记录数量不足；不补造模型、不把两次同模型调用当多模型独立评审。低层适配器未指定名称时仍兼容选择前两个，生产必须消费准备好的选择。普通执行子代理的模型由当前任务选择；外部模型不受该子代理型号设置覆盖。

入口：`scripts/recovery_review.py`。用 site 指定的 Python（需 PyYAML；httpx 可选，原 bridge 有 urllib fallback）。环境不可用时记录缺依赖；不改用全局 Python，不自动安装或猜测仓库。代理不必阅读 bridge 源码或全部原技能来执行此卡。

## 一轮的实际动作

1. ANALYST 冻结局部原理、正式端口映射、驱动/接收边界、关键公式和验证计划。生成初审 packet，只放明确准入的局部原始材料和待审解释；不给作者自评、历史报告、先前 PASS 或其他评审者答案。
2. REVIEWER 执行适配器 `--send`，读取 `responses.json`。运输成功不等于评审通过；格式失败或模型不可用记录为评审缺失，不让主代理冒充外部评审者。默认无自动 API 重试，确需重试占预算、用新目录。
3. 将每项 finding 登记到本 run 的 `review-findings.json`，ID 加 reviewer/round/stage 前缀。原理/端接/计划问题交 ANALYST；测量/公式/日志问题交 VERIFIER；措辞/排版交 EDITOR。主代理按 owner 路由，通常不自己改技术答案。
4. 责任角色给出：接受/反驳/缺证、精确来源、修改内容或区分实验。冻结新版本后再复核；不能边写边审。评审意见自身也可能错误，不能多数投票或为了消除 FAIL 修改 DUT。
5. 初审阻塞项关闭后，VERIFIER 按原仿真授权执行或回放；记录实际输入、原生单位、信号绑定、采样集合、日志和结果。API 评审预算与 Spectre 仿真预算分开；replay 禁止新仿真但可进行已授权外部评审。
6. 对最终冻结的解释、夹具、原始结果和计算脚本进行 post 评审。只附本轮需要关闭的问题，不附其他模型的评价/票数。阻塞项再退回对应角色；变化影响端接或条件时重做相关预审与验证，不只改文字。
7. 通过证据门禁且无未处理阻塞错误，才交 EDITOR。无法补齐的性能保留未测；技术错误修复或撤回为 UNKNOWN，不以 qualified 修饰错误结论。主代理仍检查交接，只有矛盾无法由证据裁决时承担技术升级。

每条 finding：`id, owner, source_review, affected_refs, status(open/resolved/withdrawn/unresolved), response, changed_artifact_hashes, closure_evidence_refs, closure_review`。仅“已修复”“另一个模型说通过”不能关闭；反驳要给原始依据和区分性检查。复审以版本哈希为准，保留首次输出。

## 调用方式

在本次 run 下建立 packet.json，例如（所有占位须替换；文件必须先按用户范围准入）：

```json
{
  "source_root": "项目根绝对路径",
  "run_dir": "本次run绝对路径",
  "stage": "pre",
  "round": 1,
  "external_send_authorized": true,
  "questions": [{"id":"topology-1", "kind":"topology", "source_paths":["相对source_root的局部输入"]}],
  "files": [
    {"path": "相对source_root的局部输入", "sha256": "真实文件哈希", "role": "netlist"},
    {"path": "相对source_root的分析记录", "sha256": "真实文件哈希", "role": "claims"}
  ]
}
```

files 角色允许 netlist/connections/model_metadata/conditions/claims/fixture/measurements/log/calculation/open_findings。最后一类仅用于关闭问题；首次 pre 不许带旧意见。source_root 与角色名不自动授予读取/发送权限，执行者先审清单。不扫描目录、不自动追 include。单包最大240KB，过大按问题分包，不截去关键端接或日志告警。

```text
<site.python> <skill>/scripts/recovery_review.py <packet.json> --site <本地site.json> --out <run>/review/r1-pre
<site.python> <skill>/scripts/recovery_review.py <packet.json> --site <本地site.json> --out <run>/review/r1-pre-live --send
```

第一条离线检查依赖、输入哈希和模型配置，不发送请求。第二条真实调用；输出目录必须全新。一般准备好 packet 后直接执行第二条即可，不强制额外探针或重复付费。输出 request.json/prompt.txt/responses.json；失败也保留并计入预算。错误信息刻意不回显服务端原文，避免泄露凭据。

## 停止规则与评估

默认最多3轮、每次最多2个reviewer、每run最多12次API尝试。适配器落实调用次数/轮次上限，不能另建run绕过本轮预算；整体状态与退回由skill驱动主代理执行，本版不是自动状态机服务。两次同一问题无新增证据或修订收益很低时，记录分歧/影响并交付可支持部分。资金金额上限需要价格信息，调用次数不代表货币预算。

lite缩小问题范围，不跳过关键独立复核；其他effort扩大问题/验证范围，但不自动增加API上限。原始数据能确定解决的错误先算再审，不用多轮聊天代替计算。

调试直接调用 analog-recovery，不给新agent旧报告答案或本轮人工修复清单。自动保留版本、首次输出、各轮finding及关闭证据、API失败/调用数、实际仿真时间和主代理技术介入记录。没有真实API执行，不宣称外部评审已跑通；没有对照，不宣称节省成本或消除主代理介入。

## v0.9 材料与返回要求

真实发送前必须登记 questions（id/kind/source_paths）。topology 需要 netlist；fixture 需要 fixture/connections/conditions；measurement 需要实际 measurements/log/calculation；report 需要 report_excerpt/claims。后者只发授权的新生成段落，不发历史报告。角色充分只是必要条件，REVIEWER 仍须看材料是否真包含被审问题的数据，清单路径不等于波形。

模型 metadata 只接受 metadata-1 JSON：根字段 schema_version/models；每个 model 含 name/device_type/pins/source_sha256/source_locator，可有 section。无模型参数正文。open_findings 只接受 {findings:[{id,owner,locator,question,closure_check}]}，不发旧 verdict/confidence/回答。初次 pre 不带 findings。

返回 checks 必须逐项列 question_id/status(checked 或 not_checked)/source_paths/reason。PASS 必须覆盖所有请求并给所发来源；空 PASS 不关闭问题。标为 checked 不证明推理可靠，按原始结果核对反证。API 使用当前计算脚本与数据摘录，不能拿旧脚本审新指标。最终文字另作 report 复核，不能以测量评审替代。
