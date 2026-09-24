# Recovery effort 与生产入口

复用 analog-pipeline 的四档名称与分维度方法，档位优先级为本次 --effort/task override > config/effort.yml 的 block override > default_effort > standard。只继承档位；不继承正向默认规格、器件修改、自动优化、收敛标志或无限迭代。模型推理档位单独服从当前任务选择。

## 准备当前任务

普通完整报告遵循当前项目已建立的仿真/外部评审使用约定；本机 skills/analog-recovery/_local/site.json 的 report_defaults 记录该约定，不从其他项目搬运授权。未建立约定的新部署使用 site.example.json 的关闭默认值；主代理集中确认缺失的使用范围。当前用户限制始终优先，不因配置为 true 忽略禁令。

```text
<repo-python> <recovery>/scripts/resolve_workflow.py --repo <repo> --run-dir WORK_<TASK> [--effort intensive] [--block bandgap]
```

上式生成新的 workflow.json、workflow.resolved.json、site.json，拒绝覆盖。共享 site 绑定当前仓库及 Python、reviewers 路径；project_root 是允许的来源根，设为本工作区以同时容纳 wiki 原件和 WORK 证据；输出及调用账本用每任务 run_dir 限定。实际 API 包仍逐文件准入、哈希绑定、有体积上限，不递归发送仓库。凭据只由原 review_bridge loader 读取，不保存到产物。

本次限制通过可选首个 JSON 参数覆盖：例如 {"simulation_authorized":false,"external_review_authorized":false,"single_agent":true,"knowledge_write_policy":"read_only"}。--read-only 一次关闭新仿真、外部 API、wiki 应用；--intent replay 或 static 禁新仿真但允许项目已授权的评审。完整报告的默认 live 不允许覆盖这些显式限制。知识策略 approval 表示准备后待批准，authorized 只在本次已有写回授权时设置，read_only 只准备候选。

准备器只生成计划和离线检查评审配置，不运行代理、仿真或API，不应用wiki。review_transport.status=configured_not_executed 不是评审通过；缺配置/零额度为 blocked_configuration，模型数量不足记录 issues。主代理将计划交角色并实际调度 S2–S7，交付时逐阶段记录执行和未完成原因，不静默用 partial 替代没执行的已授权工作。

低层兼容入口 `<python> resolve_workflow.py <workflow.json> --out <新文件>` 保持原行为：缺省为 replay/未授权/零预算，不读取项目配置。生产不要拿空 JSON 调这个兼容入口代替任务准备。

## 跨角色影响

| 维度 / owner | lite | standard | intensive | exhaustive |
|---|---|---|---|---|
| 分析 / ANALYST | 核心路径、条件和关键假设 | 主要模式、偏置/尺寸比、反馈及适用方程 | 竞争解释、跨块影响、条件性权衡 | 系统追查重要剩余问题与敏感性 |
| 预审 / VERIFIER | 结构与电气安全、端接/计量 | 加入量级估算和夹具语义 | 全部适用检查 | 全部检查及可追溯gate记录 |
| 验证 / VERIFIER | 声明的主工况有效点 | 主工况与声明范围的边界工况 | 扩展工艺/供电/温度、区分性实验 | 声明的完整PVT；有失配模型和需求时MC |
| 外部reviewer / REVIEWER | 1个，只审关键范围 | 1个，主要原理/夹具/结果/正文 | 2个，分析分歧 | 全部启用项，按每包最多2个分批且共享总额度 |
| 分析/夹具修订轮数上限 | 2 | 3 | 5 | 8，仍有界 |
| 报告 / EDITOR | 核心解释、已有结果与缺口 | 主要模式/指标和实现说明 | 加入边界、权衡与冲突解释 | 当前声明范围的完整解释和复盘 |
| 项目案例归档 / 主代理 | 默认仅WORK内轨迹 | 必须准备同库案例归档 | 必须准备同库案例归档 | 必须准备同库案例归档与深入复盘 |
| evolve候选 / 主代理 | 不要求通用知识候选 | lesson / anti-pattern | 再加strategy与checklist建议 | 再加提示词改进建议、跨案例反思 |

矩阵只定深度，不自动给 TT/27C、额定供电、trim、温漂阈值或固定角数。STANDARD 的边界要来自本项目条件；没有依据就登记待确认，不套 pipeline 的固定值。不能因模板范围大就宣称 exhaustive 已穷尽。所有档位保留关键独立复核；lite 不照搬正向“跳过review”。独立性仍须真实记录，没有配置的模型不可补造。

各角色只消费同一 resolved.role_policy；借用 learn/audit/verify/review 时该策略优先于它们的正向 effort 规则。EDITOR 所有档位都交代全部模板要求（允许未知/不适用但须解释），保留数字来源、图文绑定和逐页检查。报告所需补证由主编排退回责任角色，不让写作者自由推断。

## 有限资源

| 默认上限 | lite | standard | intensive | exhaustive |
|---|---:|---:|---:|---:|
| 仿真累计远程秒数（含失败） | 900 | 3600 | 7200 | 14400 |
| 最大并行运行数 | 1 | 2 | 3 | 4 |
| 外部API尝试数 | 3 | 6 | 12 | 12 |
| 外部评审轮数 | 1 | 2 | 3 | 3 |

这是本次接入采用的默认资源上限，不是用户产品条件；任务可显式覆盖 resources，显式0保留。远程并发还须受实际服务器可用资源限制。API额度与仿真资源独立，每次失败也计费，site上限和档位上限取较小值；不能通过拆包/换目录重新领额度。exhaustive的“全部模型”若受额度限制，记录实际覆盖与缺口；不自动增加额度。external-review.md 的既有最多12次/3轮保护不变。

所有层级保存来源、端接预审、真实日志、失败分类和报告门禁；不调整DUT解决审查失败。预算耗尽或连续无信息增益时交付明确未完成的部分，不能宣布签核。用户已给合理预算时沿用，不将准备器默认值冒称用户指定。

## 归档与evolve收尾

standard及以上在 S7 使用原 wiki 身份续作；确需新案例时才通过 recovery_wiki 创建。准备 summary.recovery、recovery_iterations、追加 narrative 与证据引用，并用原索引和关系链接报告/认识。旧convergence及正向轮次不改，新项目convergence=false；complete只表示此次声明的recovery交付。

主代理显式加载并执行本仓库 analog-evolve 的[recovery 分支](../../analog-evolve/references/recovery.md)，按 closeout.evolution 限定维度。lite 默认不要求，用户显式请求时执行。技能复盘不强制新增代理/API，不把 recovery JSONL 伪装成正向调参日志；当前引擎不支持该输入，记录 engine_execution=not_run。不论有没有可推广知识，都准备案例归档；没有候选须有实际复盘和去重依据，不凑条数。按 closeout.write_policy 执行[写回接口](wiki-writeback.md)：先prepare和检查差异，已有授权时apply，否则交用户批准。checklist/技能/提示词建议单列，另有授权才修改维护源。归档需要实际回执和读回；报告交付、技能执行、候选准备、批准、已应用分开记录。只读任务照常准备候选并记录未写回，不绕过限制。

## Behavioral 边界

auto/on/off 保持兼容：独立 recovery VA→逐块替换闭环尚未实现。off禁用，auto记录deferred，on明确报不支持；高effort也不能偷偷调用正向behavioral或宣称已跑通。
