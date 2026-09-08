# 拓扑库（LDO / OTA / Bandgap）

> 基于 gpdk045 (45nm CMOS)、TSMC-65nm、SKY130 (130nm)、0.13um 等多个工艺节点
> 来源：用户已验证项目 + AnalogGym 开源参考 + 通用电路知识
> 版本：v2.0 | 日期：2026-08-18

---

## 总览

本库收录 **LDO、OTA、Bandgap** 三类拓扑，供 architect agent 选架构、designer agent 做 sizing 时查询。

- **LDO**：11 种（7 种 PMOS pass + 4 种 NMOS pass）+ `pmos-pass-ldo-two-stage(topo-ldo-012)` + RF-OTA 65nm 变体
- **OTA**：7 种配方（topo-ota-001~007，含 5T / current-mirror-load / telescopic / folded-cascode / 两级 Miller / 全差分+CMFB）
- **Bandgap**：2 种（topo-bandgap-001 VBE+R-chain、topo-bandgap-002 current-mode active-CTAT sub-1.2V）

每个条目已登记到 `wiki/index.yml`；配方式条目（Ota 配方）附 `checklists/` 与 `templates/` 共 reference 查看。

### LDO（11 种基线）

- **7 种 PMOS pass**（用户已有项目验证 + AnalogGym 参考）
- **4 种 NMOS pass**（FVF 家族 + 电荷泵，基于通用电路知识）

---

## 四维分类树

```
维度1: pass器件类型
├── PMOS (001-007)
│   ├── 维度2: 输出电容策略
│   │   ├── 外部大电容 (CL=0.47µF~10µF, 含ESR)
│   │   │   ├── ldo_simple        (004)  ← AnalogGym
│   │   │   ├── ldo_1             (005)  ← AnalogGym
│   │   │   ├── ldo_2             (006)  ← AnalogGym
│   │   │   ├── ldo_folded_cascode (007) ← AnalogGym
│   │   │   ├── HP_LDO            (001)  ← 用户项目
│   │   │   └── LDO_DIG/DIG2      (003)  ← 用户项目
│   │   └── 片内电容 (capless, Cout<1nF)
│   │       └── LDO_0p9           (002)  ← 用户项目
│   │
│   ├── 维度3: OTA变体
│   │   ├── 五管OTA (single-stage)
│   │   │   ├── PMOS输入 → HP_LDO (001)
│   │   │   └── NMOS输入 → ldo_simple (004), LDO_DIG (003)
│   │   ├── 两级OTA (two-stage)
│   │   │   ├── PMOS差分 → LDO_0p9 (002)
│   │   │   └── NMOS差分 → ldo_1 (005)
│   │   ├── 折叠共源共栅 → ldo_folded_cascode (007)
│   │   └── cascode+前馈 → ldo_2 (006)
│   │
│   └── 维度4: 补偿策略
│       ├── Miller → 全部 (001-007)
│       ├── Miller + ESR零点 → LDO_DIG (003)
│       ├── Miller + 片内Cout → LDO_0p9 (002)
│       └── 前馈 + Miller → ldo_2 (006)
│
└── NMOS (008-011)
    ├── FVF 家族 (无电荷泵)
    │   ├── FVF LDO              (008)  ← 源跟随+cascode
    │   └── FVF + PMOS Cascode   (010)  ← FVF+PMOS cascode叠加
    └── 电荷泵家族
        ├── NMOS Pass + CP       (009)  ← 倍压电荷泵
        └── NMOS Cascode         (011)  ← NMOS cascode+CP
```

---

## 拓扑对比表

| ID | 名称 | OTA结构 | pass | CL | 补偿 | 工艺 | Iq典型 | 来源 |
|----|------|---------|------|----|------|------|--------|------|
| 001 | HP_LDO | 5T PMOS输入 | PMOS svt | 外部(1-10µF) | Miller | gpdk045 | ~23µA | 用户 |
| 002 | LDO_0p9 | 2级 PMOS差分 | PMOS | 片内(100pF) | Miller | gpdk045 | — | 用户 |
| 003 | LDO_DIG | 5T NMOS输入 | PMOS lvt | 外部+ESR(0.47µF) | Miller+软启动 | gpdk045 | ~40µA | 用户 |
| 004 | ldo_simple | 5T NMOS输入 | PMOS | 外部 | Miller | SKY130 | — | AnalogGym |
| 005 | ldo_1 | 2级 cascode | PMOS | 外部 | Miller | SKY130 | — | AnalogGym |
| 006 | ldo_2 | cascode+前馈 | PMOS | 外部+内部 | 前馈+Miller | SKY130 | — | AnalogGym |
| 007 | ldo_folded_cascode | 折叠cascode | PMOS | 外部 | Miller | SKY130 | — | AnalogGym |
| 008 | FVF LDO | 共源/折叠cascode | NMOS | 外部 | Miller | 通用 | — | 通用知识 |
| 009 | NMOS+CP | 5T | NMOS | 外部 | Miller | 通用 | — | 通用知识 |
| 010 | FVF+PMOS Cascode | 共源/折叠cascode | NMOS+PMOS | 外部 | Miller | 通用 | — | 通用知识 |
| 011 | NMOS Cascode | 5T | NMOS | 外部 | Miller | 通用 | — | 通用知识 |

---

## 使用指南

### Architect agent 查询路径

```
1. spec.yml 的 CL 策略 → 维度2 缩小范围
   ├── 外部大电容 → 001/003/004/005/006/007/008/009/010/011
   └── 片内电容(capless) → 002

2. spec.yml 的 PSRR/增益需求 → 维度3 选 OTA
   ├── 高增益(>70dB) → 002(两级) / 005(2级cascode) / 007(折叠cascode)
   ├── 中等增益(40-70dB) → 001/003/004/006
   └── 低增益可接受 → 008/010(FVF增益天然低)

3. spec.yml 的 dropout 需求 → 选 pass 类型
   ├── 低 dropout (<150mV) → 009(NMOS+CP) / 008(FVF)
   ├── 中 dropout (150-400mV) → PMOS pass (001-007)
   └── 高 dropout 可接受 → 任意

4. spec.yml 的 Iq 约束 → 最终筛选
   ├── Iq < 10µA → FVF (008/010)
   ├── Iq 10-50µA → 001/003/004
   └── Iq > 50µA → 002/005/006/007/009/011
```

### Designer agent sizing 路径

```
1. 选定拓扑条目 → 读取 sizing_equations
2. 填入 spec 参数 (VDD, VOUT, Iload_max, dropout, IQ)
3. 手算 W/L，参考 tradeoffs 边界
4. 确认不超 optimization_dims 的物理边界
5. 注意 pitfalls 中的已知陷阱
```

---

## OTA 拓扑（7 种配方）

> 工艺：TSMC-65nm 3.3V IO（nch_33 / pch_33）；配方式条目含 `equations`（gm/Id 法）、`calibration`（muCox/lambda 实测值）、`sensitivities`、`sizing_rules`、`pitfalls`，配套 checklist 与 template。
> 指标范围预判见 `strategies/ota-spec-ranges.yml`（各结构可达 Av/GBW/PM）。

| ID | 文件 | 结构 | 输入 | 典型 Av | 典型 GBW/PM | 摆幅 | 关键点 |
|----|------|------|------|---------|------------|------|--------|
| topo-ota-001 | [fully-differential-ota-cmfb.yml](fully-differential-ota-cmfb.yml) | 全差分+CMFB(通用) | — | — | CM PM≥45° | — | 输出共模由 CMFB 环调节；PSRR/CMRR 用 MC/dcmatch |
| topo-ota-002 | [5t_ota.yml](5t_ota.yml) | 5T 单级 | PMOS 输入(低 Vcm) | 40dB 目标 | 100MHz/60° | 2.0V | 最简单；增益 ~30-45dB；尾源用电流镜偏置 |
| topo-ota-003 | [current_mirror_load_ota.yml](current_mirror_load_ota.yml) | 电流镜负载 单级 | NMOS 输入(高 Vcm~2.1V) | 40dB 目标 | 100MHz/60° | 2.0V | 与 5T 对偶：高 Vcm 用 NMOS 输入 |
| topo-ota-004 | [folded_cascode_ota.yml](folded_cascode_ota.yml) | 折叠 cascode | NMOS 输入(低 Vcm) | 60dB 目标 | 100MHz/60° | 2.5V | 摆幅比 telescopic 大；尾电流=Itail+2×折叠电流 |
| topo-ota-005 | [telescopic_ota.yml](telescopic_ota.yml) | telescopic cascode | PMOS 输入(低 Vcm) | 60dB 目标 | 100MHz/60° | 1.5V | 5 层堆叠摆幅最小；65nm 实测可达 ~53dB |
| topo-ota-006 | [two_stage_miller_ota.yml](two_stage_miller_ota.yml) | 两级 Miller | NMOS 输入(高 Vcm~1.8V) | 70dB 目标 | 50MHz/60° | 2.0V | GBW=gm1/(2π·CC) 非 CL；第二极点 p2≥2.2×GBW |
| topo-ota-007 | [fully_diff_cmfb_ota.yml](fully_diff_cmfb_ota.yml) | 全差分两级+CMFB(telescopic 1 级+对称 CS 2 级) | NMOS 输入 | 60dB 目标 | 20MHz/60° | 2.0V | 需两级 CMFB(第一级钳 net_ap/an + 输出钳)；GBW 物理上限 ~17MHz(65nm IO) |

**OTA 选型速查（对照 `strategies/ota-spec-ranges.yml` 实测校准）：**
- Av ≤ 35dB → 5T (topo-ota-002)
- Av 35-53dB、摆幅不要求 → telescopic (topo-ota-005)
- Av 40-80dB + 摆幅 → 两级 Miller (topo-ota-006)
- 大摆幅 + 中增益 → folded-cascode (topo-ota-004)
- 全差分 + 输出共模需 CMFB 钳位 → topo-ota-007 或 topo-ota-001

**GM/Id 通用手算** 见 `strategies/11-gmid.yml`、`strategies/08-ota-sizing.yml`（差分对/电流镜/尾源/两级 sizing 方程）。

---

## Bandgap 拓扑（2 种）

> 覆盖 0.13um 3.3V 与 65nm 两种工艺基线的基准源拓扑，均含 `content.description/key_tradeoffs/typical_specs/sizing_anchors`。

| ID | 文件 | 结构 | 工艺 | Vref | TC | 关键点 |
|----|------|------|------|------|-----|--------|
| topo-bandgap-001 | [vbe-r-chain-bandgap.yml](vbe-r-chain-bandgap.yml) | VBE + R-chain + tap 选择 Vntat | 0.13um 3.3V | ~1.2V(TT 27C) | 15-20 ppm/C | tap 选择是输出监视，非 trim 返回；启动 ~50µs；顶 PNP 面积比 12:1 |
| topo-bandgap-002 | [current-mode-bandgap-active-ctat.yml](current-mode-bandgap-active-ctat.yml) | current-mode + active-CTAT 环 | 65nm | 1.000V(27C) | 16.8 TT/9.4 SS/21.4 FF ppm/C | 亚 1.2V 必须 active-CTAT；R_out 是 TC 中性缩放位；三个主极点电容防振 |

**Bandgap 设计要点速查：**
- 亚 1.2V 输出不可用 VBE tap（provably CTAT-tilted）→ 用 current-mode ground-referenced + active-CTAT（见 `anti-bandgap-002`）。
- TC null 比从实测斜率推导（非教科书值）：`strategies/measured-slope-tc-null.yml`、`strategies/sub-1v-current-mode-output.yml`。
- 顶 PNP 面积比、R_chain、tap 定位参考各条 `sizing_anchors`。

---

## 文件清单

```
~/claude/ldo_topo_library/
├── README.md                              ← 本文档
├── index.yml                              ← wiki 索引
├── edges.jsonl                            ← 拓扑↔项目关系
├── wiki-schema-reference.md               ← wiki schema 精简参考
├── topologies/
│   ├── topo-ldo-001-pmos-input-5t-ota-external-cl-miller.yml      ← HP_LDO
│   ├── topo-ldo-002-2stage-ota-pmos-diff-internal-cl-miller.yml  ← LDO_0p9
│   ├── topo-ldo-003-nmos-input-5t-ota-external-cl-softstart.yml ← LDO_DIG/DIG2
│   ├── topo-ldo-004-nmos-input-5t-ota-external-cl-basic.yml     ← ldo_simple
│   ├── topo-ldo-005-2stage-ota-nmos-input-external-cl.yml       ← ldo_1
│   ├── topo-ldo-006-cascode-ota-feedforward-miller.yml          ← ldo_2
│   ├── topo-ldo-007-folded-cascode-ota-external-cl.yml          ← ldo_folded_cascode
│   ├── topo-ldo-008-fvf-ldo.yml                                  ← FVF LDO
│   ├── topo-ldo-009-nmos-pass-chargepump.yml                    ← NMOS+CP
│   ├── topo-ldo-010-fvf-pmos-cascode-ldo.yml                    ← FVF+PMOS Cascode
│   ├── topo-ldo-011-nmos-cascode-ldo.yml                        ← NMOS Cascode
│   ├── topo-ldo-012-pmos-pass-ldo-two-stage.yml                 ← PMOS-pass 两级(大输出电容)
│   ├── topo-ldo-2stage-rf-ota-65nm.yml                          ← 两级 RF OTA (TSMC-65nm)
│   ├── fully-differential-ota-cmfb.yml                          ← topo-ota-001 全差分+CMFB(通用)
│   ├── 5t_ota.yml                                               ← topo-ota-002 5T 单级
│   ├── current_mirror_load_ota.yml                              ← topo-ota-003 电流镜负载
│   ├── folded_cascode_ota.yml                                   ← topo-ota-004 折叠 cascode
│   ├── telescopic_ota.yml                                       ← topo-ota-005 telescopic
│   ├── two_stage_miller_ota.yml                                 ← topo-ota-006 两级 Miller
│   ├── fully_diff_cmfb_ota.yml                                  ← topo-ota-007 全差分两级+CMFB
│   ├── vbe-r-chain-bandgap.yml                                  ← topo-bandgap-001 VBE+R-chain
│   └── current-mode-bandgap-active-ctat.yml                     ← topo-bandgap-002 active-CTAT
├── strategies/README.md                 ← 预留
├── corner-lessons/README.md             ← 预留
├── anti-patterns/README.md              ← 预留
└── projects/
    ├── HP_LDO/summary.yml
    ├── LDO_0p9/summary.yml
    ├── LDO_DIG/summary.yml
    ├── AnalogGym_ldo_simple/summary.yml
    ├── AnalogGym_ldo_1/summary.yml
    ├── AnalogGym_ldo_2/summary.yml
    └── AnalogGym_ldo_folded_cascode/summary.yml
```