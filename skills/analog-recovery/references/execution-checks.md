# v0.9 工作卡到实际执行

本文件补充现有 pipeline，不增加角色，不调用正向调参。方法职责见 role-cards；不要把全部 analog 技能塞进每个任务。

## 开始一个有实质产物的任务

用 `scripts/task_card.py prepare --role ANALYST --question "本块反馈如何形成，哪些观察能否定解释" --repo <repo_root> --installed <技能根目录> --out <新tasks目录>/task.json`。

该工具解析方法文件及其哈希、给出阅读主题；它不启动代理，也不证明主题在各版本中逐字存在。接收者查相应小节，找不到则记录实际替代位置，不能声称已执行不存在的方法。

补充 inputs（path/sha256）、acceptance（可检查的结果）、实际 agent 信息；完成时补 outputs、method_results（skill/observation/output_refs）、closure（reviewer_id/evidence_refs），再运行 `task_card.py check <task.json>`。输出引用为卡中登记的绝对路径。仅“读过技能”不能作为 observation。

模型/effort 不可选择时填写实际能力、limitations。主代理执行与子代理执行明确区分；子代理 Luna/high 无法满足时披露，不伪造模型字段。没有独立代理时继续可做内容，但保留独立性缺口。

## 分工和退回

- ANALYST：沿实际连接解释机制，采用 learn/audit；给竞争解释、接口域、模式和验证问题。
- VERIFIER：采用 verify/spectre；检查正式 DUT 端口、激励、负载、初值及测量后执行。多电源/模式、共享偏置、诊断数据重用或复杂矩阵应设独立复核责任；不是按仿真数量机械拆代理。
- REVIEWER：按 external-review 执行原始材料反证、API 评审及关闭检查。方法复用不等于启动原正向 review 命令。
- EDITOR：从审定证据生成自然语言、图表并核对条件。不自行把未接控制扫描、初值结果或测试上界升级成结论。

每项 finding 的关闭记录要关联修订后的文件哈希及复核依据。原理退 ANALYST，夹具/公式/日志退 VERIFIER，条件措辞/表格退 EDITOR。已有结果可离线复算就不补跑仿真。

## 三个检查点

1. 批量验证之前：按[局部连接包](../../analog-recovery-evidence/references/repository-adapter.md)生成具名端口及需要的成对端点包；逐目标分开交接直接网络关系、器件关联/条件、控制有效性。按[质量契约](../../analog-recovery-evidence/references/quality.md)登记 target_nodes 和 measurement（旧包另建版本），按 check_scope 解释结果。复核者用自己的源观察逐项对照上述结论并处理冲突，核对端序、原夹具、环境参数 binding 和端口电源域，不以自填 edges 或器件短接代替取证。相同输出只触发调查。关断时外部偏置/负载由场景决定，不自动替用户关闭。
2. 写作之前：运行 evidence 的 check_quality；审查当前测量脚本与数据，确定指标定义/符号/范围/典型条件。主代理按[覆盖与停止检查](coverage-closeout.md)核对主要功能及剩余工作的处置依据。因果、范围取舍与自然语言需实际复核，脚本只负责声明中可计算的一部分。
3. 交付之前：审阅最终段落/表格与证据，filler --check，逐子节模板检查，最后渲染。证据或正文改变后冻结新 snapshot，复核受影响项，不重用旧 PASS。

## 停止与追问

追问只包含：具体未知、影响的指标/章节、最小所需信息、可替代诊断条件。其余任务继续。无新证据时停止循环，保留分歧；“少一条门禁”不是消除技术问题的方法。
