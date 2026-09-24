# 本工作区 wiki 写回接口

使用 repo 的 Python，显式给 `--repo`。原 `wiki/index.yml`、`edges.jsonl`、项目目录是唯一知识结构；准备目录仅含本次受影响文件的候选、备份、差异与回执，不作为检索入口。

standard及以上的S7用本接口完成案例归档，消费workflow.resolved.json的closeout；不是调用正向archive-project。已有项目续作，缺少同源案例才create_project。至少准备summary.recovery、追加trajectory/narrative与证据/报告定位；没有可推广知识仍准备案例记录。默认先交差异待批准；已有写回授权才直接应用，只读保留候选。交付说明分别记录报告状态和归档状态（pending/awaiting_approval/applied/blocked），applied须有回执与读回。知识候选不强制凑数；checklist/技能修改建议不由本接口自动执行。

候选来源为实际执行的 [analog-evolve recovery 复盘](../../analog-evolve/references/recovery.md)：稳定证据/审阅结果→复盘与同库去重→案例及知识候选→prepare/diff→按授权apply/readback。演化建议文件存在不等于技能已执行，prepare成功不等于wiki已更新；各状态分别记录。没有有效新增知识时仍可仅归档案例，不因此重复分析或自动升级confidence。

```text
<repo-python> tools/recovery_wiki.py --repo <repo> prepare <repo内request.json> --out WORK_<TASK>/wiki-change
<repo-python> tools/recovery_wiki.py --repo <repo> apply WORK_<TASK>/wiki-change
<repo-python> tools/recovery_wiki.py --repo <repo> audit-index
```

请求示例（hash、路径、日期和正文换成当前真实值）：

```json
{
  "project_id": "proj-existing",
  "update_id": "bias-r1",
  "date": "2026-09-22",
  "block": "pmu",
  "delivery_status": "partial",
  "result": "局部连接已确认，因果尚未完成复核",
  "evidence_refs": [
    {"path": "WORK_<TASK>/source-observation.json", "sha256": "实际SHA256", "locator": "/observations/0"}
  ],
  "iterations_ref": {"path": "WORK_<TASK>/recovery-iterations.jsonl", "sha256": "实际SHA256"},
  "bundle_ref": {"path": "WORK_<TASK>/evidence/manifest.json", "sha256": "实际SHA256"},
  "narrative": "旧解释及适用范围、修订、证据相对repo路径、未决问题和下一步。",
  "entry_updates": [
    {"id": "corner-existing", "content_patch": {"description": "有范围的新表述"}, "reason": "具体源记录反驳旧概括"}
  ],
  "edges": [
    {"from": "corner-existing", "to": "proj-existing", "rel": "discovered_in", "note": "修订出处"}
  ]
}
```

bundle_ref 可省略（尚未生成报告交接包时）；证据与轨迹引用不能省略。JSONL 每项为 question_id、iteration、before、action、evidence_refs、after、remaining、next_action、stop_reason，evidence_refs 使用请求中已声明的本地 path。iteration 是同问题追加序号，不得改写已有轮次。审阅是否独立、结论是否充分仍依赖正式 review 记录与实际执行，不由哈希代证。

选已有 project_id 续作；确需新案例时以 `create_project: {name,path,tags,architecture}` 替代 project_id，path 必须为 `projects/<case>/summary.yml`，工具用原 next_id 分配。新案例 convergence=false；已有 convergence/result/total_iterations 保持历史原值，新的交付状态只写 summary.recovery。新建案例前仍需按来源、DUT和作用域排查已有身份，工具不会从电路文件名猜项目。

已有项目可用 `project_index_summary` 更新原索引摘要，旧索引项保存到项目 summary.index_revisions，并记录本次依据。摘要应能定位当前问题及 recovery 状态，同时区分历史验证结果。知识修订检查直接关联的策略及其边是否仍给出已撤回的执行建议；归档报告、夹具注释不改写，在当前消费入口限定其用途。已确认范围、可找到当前问题且无影响继承的残留冲突时即可结束本次修订，不因明确保留的未决项反复开启相同验收。

旧项目的 summary.yml 若使用 `proj-index`，须与原索引选定 project_id 精确一致，且任何已存在的 id/type 不冲突，才允许原地续作；不补造 id/type/convergence、不迁移旧测量字段。旧 trajectory 的 steps 等字段原样保留，另在指定 block 追加 recovery_iterations。读取叙事/轨迹也支持该受控身份映射；身份不明或矛盾时停止写回，不另建同线路案例绕过。

entry_updates 修改已有四类领域条目的 content，保留旧 content/confidence 到 revisions，新的置信度为 unverified；整条撤回可以加 `deprecate: true`。不自动授予 verified。可选 `metadata_patch` 仅允许非空字符串 name/source/confidence_note；可选 `index_summary` 同步原索引摘要，改 name 必须同时指定它。旧元数据、原先缺失的字段及旧索引条目存入同一 revision。ID、类型、路径不能通过补丁改变。撤回过强认识时检查正文、来源说明、置信度注释及检索摘要，不能只降低状态而保留当前因果断言。

new_entries 可指定 type/name/tags/content，通过原 add_entry 创建并关联项目，同路径拒绝覆盖。新边必须符合原十种关系和索引端点；同三元组同 note 跳过，改 note 明确拒绝，避免静默覆盖历史。修订既有边另用 `edge_updates: [{from,to,rel,expected_note,note,reason}]`：必须唯一匹配既有边及原 note；保留端点/关系类型（包括历史遗留拼写），将旧边字段存入 revisions，当前 note 写清撤回范围，status 标为 historical_revised。此状态不改变原图工具的遍历规则，因此 note 本身必须明确其历史性质；不能仅靠 status 消解过强认证。不得用该接口新建遗留关系类型。

首期写入接口不新增 block-case 文件；既有 block-case 可定向读取，block 的 recovery 轨迹写在原 trajectory.yml。

prepare 不写活动 wiki。审查 changes.diff 后在已有用户授权内 apply；不因每一条局部修订重复索要授权。重复 apply 同一准备目录为 no-op；已经应用的 update_id 不重新 prepare。后续修订用新 update_id/新问题轮次，继续相同 project_id。独立复核未完成时保持 partial/unverified；技术错误必须撤回，不仅改一个状态词。

apply 检查准备期 wiki/hash 和证据版本。单写者工作，原 wiki_ops 不使用 recovery 锁，期间不要同时用其他编辑器改 wiki。普通写入失败自动回滚；进程硬中断会保留 `wiki/.recovery-write.lock`，检查该文件记录的计划及 live/diff 后运行：

```text
<repo-python> tools/recovery_wiki.py --repo <repo> recover WORK_<TASK>/wiki-change
```

恢复只允许文件处于本次 before/after 状态；其他人已改过则拒绝自动撤销。不要靠删除锁绕过恢复。receipt 是文件操作回执，不是电气复核。audit-index 只查索引目标位置与存在性，不声称全库历史证据都已迁入。

维护：parser 只改 repo/src/analog_evidence，再更新 skill 的 vendor 冻结副本与 identity；不要双边开发。静态 IR schema、手工 handoff schema 继续各自使用。未迁入的 inference/report_mapping 开发链不属于当前生产入口。repo Python 缺 docx 等依赖时保留报告分支未验证，不改变解释器或自动安装。
