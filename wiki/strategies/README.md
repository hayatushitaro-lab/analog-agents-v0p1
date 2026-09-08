# 设计 / Sizing 策略库（LDO / OTA / Bandgap / 共享）

> 结构化 `strategy` 条目（yml），按模块组织：**共享 (_shared) / LDO / OTA / Bandgap**
> 每个条目含 `name/tags/process_nodes/content{description,how,when_to_use,...}/derived_from/confidence`
> 索引见 `wiki/index.yml`（strat-shared-0xx / strat-ldo-0xx / strat-ota-0xx / strat-bandgap-0xx）
> 工艺：gpdk045 45nm / TSMC-65nm / 0.13um 3.3V | 版本：v3.0 | 日期：2026-08-18

---

## 共享策略（_shared，跨模块通用）

> 由 designer-prompt 与 shared-references 沉淀，LDO/OTA/Bandgap 都适用。

| ID | 文件 | 核心内容 |
|----|------|---------|
| strat-shared-001 | [mixed-l-for-matching.yml](mixed-l-for-matching.yml) | 混合 L：输入对用短 L，镜像/电源/cascode 用 2-4x 最小 L（匹配+增益） |
| strat-shared-002 | [cmfb-mirror-load-preference.yml](cmfb-mirror-load-preference.yml) | 全差分 CMFB 误差放大器用镜负载（非 diode 负载直驱高阻栅） |
| strat-shared-003 | [gmid-sizing-targets.yml](gmid-sizing-targets.yml) | gm/Id 参考目标：输入对 15-20 / 镜·尾·cascode 10-15 |
| strat-shared-004 | [crossmodel-review-opencode-anthropic.yml](crossmodel-review-opencode-anthropic.yml) | 跨模型 review 通道：opencode-gO-anthropic (Messages) + 手工 JSON |
| strat-shared-005 | [l3-pvt-and-crossmodel-review.yml](l3-pvt-and-crossmodel-review.yml) | 验证双轨：L3 PVT 全角（真实温度）+ 跨模型 review 互补判案 |

## LDO 策略

### LDO sizing 手册（§1~§12 + 附录，strat-ldo-005~017）

> 由原 `.md` 手册按 wiki-schema 转换而来。

| 章节 | 文件 | 核心内容 |
|------|------|---------|
| §1 增益 | [01-gain.yml](01-gain.yml) | A_OL（单级/两级/折叠cascode），环路增益 T(s)，pass 管 gmp |
| §2 带宽 | [02-bandwidth.yml](02-bandwidth.yml) | UGBW（大CL/capless），GBW_EA，带宽-PSRR关系 |
| §3 极点 | [03-poles.yml](03-poles.yml) | p1/p2/p_cascode，极点分离条件 p2>4×UGBW，ESR零点 |
| §4 零点 | [04-zeros.yml](04-zeros.yml) | RHP零点+Rz消除，自适应零点，前馈零点 |
| §5 稳定性 | [05-stability.yml](05-stability.yml) | PM/GM计算，PM-Cc关系，PM-负载关系 |
| §6 PSRR | [06-psrr.yml](06-psrr.yml) | 低频/高频PSRR，pass管/cascode PSRR |
| §7 Pass管 | [07-pass-sizing.yml](07-pass-sizing.yml) | dropout→W/L，gm/Id→W，Rds_on，栅极驱动 |
| §8 OTA | [08-ota-sizing.yml](08-ota-sizing.yml) | 差分对/电流镜/尾电流/两级OTA sizing |
| §9 补偿 | [09-compensation.yml](09-compensation.yml) | Cc/Rz/Cff/软启动方程 |
| §10 瞬态 | [10-transient.yml](10-transient.yml) | droop（大CL/capless），恢复时间，建立时间 |
| §11 gm/Id | [11-gmid.yml](11-gmid.yml) | 强/中/弱反型定义，W/L推导，本征增益，温漂 |
| §12 迭代 | [12-iteration.yml](12-iteration.yml) | 敏感度矩阵，代理模型，收敛判据 |
| 附录 | [appendix-symbols.yml](appendix-symbols.yml) | 符号表格 |

### LDO 独立策略（strat-ldo-001~004 / 018 / 019）

| ID | 文件 | 核心内容 |
|----|------|---------|
| strat-ldo-001 | [big-cout-ldo-compensation.yml](big-cout-ldo-compensation.yml) | 大输出电容 LDO 补偿 |
| strat-ldo-002 | [gmid-tsmcN65-lookup.yml](gmid-tsmcN65-lookup.yml) | gm/Id LUT（TSMC N65） |
| strat-ldo-003 | [ldo-rf-ota-heavy-load-stability.yml](ldo-rf-ota-heavy-load-stability.yml) | LDO RF-OTA 重载稳定性 |
| strat-ldo-004 | [spectre-ac-injection.yml](spectre-ac-injection.yml) | Spectre AC 注入技术 |
| strat-ldo-018 | [fast-settle-ldo-droop-in-band.yml](fast-settle-ldo-droop-in-band.yml) | Fast-settle LDO：大 Cout + droop-in-band（settle=沿结束，非环恢复） |
| strat-ldo-019 | [behavioral-ac-model-must-match-tb.yml](behavioral-ac-model-must-match-tb.yml) | 行为级 AC 模型必须镜像 TB（ESR 零点+输出节点寄生） |

## OTA 策略（strat-ota-001~005）

> 配方式 sizing 方法 + 指标可达性 + 仿真/测试台解法；OTA 结构选型见 `topologies/README.md`（topo-ota-001~007）。

| ID | 文件 | 核心内容 |
|----|------|---------|
| strat-ota-001 | [gm-id-bandwidth-sizing.yml](gm-id-bandwidth-sizing.yml) | GBW 钉死 gm1=2π·GBW·CL，预算钉死 Id，查表反推 W（顺序 GBW→gm1→Id→gm/Id→W） |
| strat-ota-002 | [ota-spec-ranges.yml](ota-spec-ranges.yml) | 各结构 TSMC-65nm/Itail=100u/CL=2p 可达指标范围，提前预判可行性 |
| strat-ota-003 | [spectre-simulation-method.yml](spectre-simulation-method.yml) | Spectre 仿真方法：远端 spectre + PSF real/imag + netlist 兼容（LDO 法套用到 OTA） |
| strat-ota-004 | [bias-mirror-ratio-power-savings.yml](bias-mirror-ratio-power-savings.yml) | 单级 OTA 内部自偏置大镜像比(10:1)压 bias 支路功耗 |
| strat-ota-005 | [two-stage-ota-dc-feedback-tb.yml](two-stage-ota-dc-feedback-tb.yml) | 两级 OTA 测试台：unity-gain DC 反馈稳定静态点 + STB 环路增益 |

## Bandgap 策略（strat-bandgap-001~007）

> 基准源验证 / 亚 1.2V 输出 / TC-null 推导 / active-CTAT / startup，均源自 bandgap 项目迭代。

| ID | 文件 | 核心内容 |
|----|------|---------|
| strat-bandgap-001 | [bandgap-temp-sweep-startup-verify.yml](bandgap-temp-sweep-startup-verify.yml) | 验证法：温度扫描 dcOp 提取 TC + VDD-ramp startup（SS/FF 也跑） |
| strat-bandgap-002 | [sub-1v-current-mode-output.yml](sub-1v-current-mode-output.yml) | 亚 1.2V 输出用接地 current-mode（vref=R_out·(Iptat+Ictat)），非 VBE-tap |
| strat-bandgap-003 | [measured-slope-tc-null.yml](measured-slope-tc-null.yml) | 从实测斜率推 TC-null 比，拓扑变更后重推（8.98→6.93→6.2） |
| strat-bandgap-004 | [active-ctat-ota2-diffpair-sizing.yml](active-ctat-ota2-diffpair-sizing.yml) | active-CTAT OTA2 差分对 20u/1u 修复弱反型 null 增益 |
| strat-bandgap-005 | [active-ctat-ota2-load-length.yml](active-ctat-ota2-load-length.yml) | active-CTAT OTA2 NMOS 负载 1u/4u 加长 ro，恢复 null 增益 |
| strat-bandgap-006 | [startup-pulldown-leak-margin.yml](startup-pulldown-leak-margin.yml) | Startup 下拉须胜冷 FF 上拉漏电（8u，零静态功耗） |
| strat-bandgap-007 | [netlist-analysis-in-testbench-only.yml](netlist-analysis-in-testbench-only.yml) | 分析语句只在 testbench，netlist 内 SPICE .op 是 SFE-679 硬错 |

---

## 使用方式

```
# 按模块/需求加载对应 yml 策略条目
cat 11-gmid.yml             ← gm/Id 通用目标（共享）
cat 01-gain.yml             ← LDO 增益方程（§1）
cat gm-id-bandwidth-sizing.yml  ← OTA 尺寸起点（GBW→gm1→…）
cat measured-slope-tc-null.yml  ← Bandgap TC-null 推导
cat ota-spec-ranges.yml     ← OTA 指标可达性预判
```

- 每条均为独立完整的结构化策略条目，含方程与注释，不依赖其他章节。
- 结构/拓扑对应条目见 `topologies/README.md`；角点教训见 `corner-lessons/`；陷阱见 `anti-patterns/`。
- `strat-ldo-018/019` 在 `index.yml` 中未标 `module`（归类为 LDO 策略）。
