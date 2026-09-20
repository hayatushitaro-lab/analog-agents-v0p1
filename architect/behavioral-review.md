# OTA 2-stage Miller：Phase 2 behavioral gate

## 执行边界

- Effort: `standard`，因此执行 key-spec quick check，而非 exhaustive sensitivity sweep。
- EDA mode: `full`（项目已确认 `default` server 可达，Spectre 18.1 可探测）。
- 输入：`spec.yml`、`architect/architecture.md`、`architect/budget.md`、
  `blocks/ota_2stage_miller/spec.yml`、`verification-plan.md`。
- 输出：`blocks/ota_2stage_miller/behavioral.va` 与根目录
  `testbench_system.scs`。
- 模型是 Phase-2 架构模型，不是 transistor/PDK 模型；`VBP/VBN/VBN2`
  保留为接口但不建模镜像电流，因此 bias-mirror completeness 不能在本 gate 中宣称通过。

## Behavioral model contract

`behavioral.va` 使用 `VINN-VINP` 作为差分输入，`X1` 为有限 DC gain 的第一阶段状态，
`VOUT` 为带第二极点的输出状态。名义参数为 `A0=1496.2 V/V (63.5 dB)`、
`GBW=13.4 MHz`、`p2=120 MHz`、`SR=8 V/us`、`CL=1 pF`、`Cc` 对应的第一阶段状态电容为
`1 pF`。输出命令限制为 `VSS+0.15 V` 到 `VDD-0.15 V`，所以模型会显式暴露
`VDD=1.62 V` 时的 high-swing/headroom 冲突，而不会把它隐藏成理想 rail-to-rail 输出。

接口：`VINP, VINN, VBP, VBN, VBN2` 为输入，`VOUT` 为单端输出，`VDD/VSS` 为电源。
`VBP/VBN/VBN2` 的值只用于接口兼容；本模型不从这些端口抽取偏置电流。

## Quick-validation evidence

运行方式：使用项目 `.venv\Scripts\python.exe`、`virtuoso-bridge status` 确认 remote
Spectre/daemon 可达，然后将 `testbench_system.scs` 与 `behavioral.va` 交给当前 bridge
执行。结果应在本报告中记录为 `MEASURED`；若运行失败则保留 `SKIPPED/UNKNOWN`，不得用
模型参数冒充测量。

### 规格结果表

| Spec | Measured / estimated | Target | Margin | Confidence | Status |
|---|---:|---:|---:|---|---|
| DC gain | TBD until quick validation | ≥60 dB | TBD | medium from model structure; measured value pending | UNKNOWN |
| UGBW | TBD until quick validation | ≥10 MHz | TBD | medium from model structure; measured value pending | UNKNOWN |
| Phase margin | estimated 83.6° from 2-pole model (`p1≈8.95 kHz`, `p2=120 MHz`) | ≥60° | +23.6° | medium; must be confirmed by STB/loop measurement | ESTIMATED |
| Slew rate | TBD until quick validation | ≥5 V/us | TBD | medium from bounded output current; measured value pending | UNKNOWN |
| Output low | nominal clamp estimate 0.15 V | ≤0.20 V | +0.05 V | medium; behavioral clamp, not transistor headroom | ESTIMATED |
| Output high, nominal | nominal clamp estimate 1.65 V | ≥1.60 V | +0.05 V | medium; behavioral clamp, not transistor headroom | ESTIMATED |
| Output high, VDD=1.62 V | literal clamp estimate 1.47 V | ≥1.60 V | −0.13 V | high for this behavioral contract; confirms Phase-1 risk | FAIL (literal PVT) |
| Quiescent power | not represented by zero-current bias override model | ≤5 mW | not measurable | low / not modeled | UNKNOWN |
| Saturation fraction | not represented; no MOS regions in VA model | ≥1.0 | not measurable | none | UNKNOWN |

`TBD` rows must be replaced by the actual bridge/Spectre quick-validation output before
claiming a measured behavioral pass. The two output-high entries are intentionally shown
separately: nominal acceptance can pass the clamp target, while the literal full-PVT target
fails at VDD-min exactly as predicted by Phase 1.

## Gate decision

**Gate: FAIL / HOLD. Do not enter transistor design yet based on this report.**

Reason: the current report has not established measured AC/SR results, and the literal
full-PVT `output_high` target is structurally incompatible with the selected generic 180 nm
headroom screen (`1.62 V - 1.60 V = 20 mV` remaining PMOS VSD). The model is suitable as a
Phase-2 behavioral scaffold and nominal architecture screen, but transistor design is
allowed only after both conditions are met:

1. the quick validation produces measured DC gain, UGBW and slew-rate margins, and
2. the upstream owner resolves the VDD-min swing requirement (revise the spec/corner target,
   or explicitly change the output architecture/device assumptions). No waiver is inferred.

## Handoff notes

- The model does not modify `circuit/`, Phase-1 files, `spec.yml`, or `iteration-log.yml`.
- A later designer may use `behavioral.va` as the interface/target contract, but must replace
  the idealized gain/pole/clamp behavior with transistor-level devices and re-check DCOP, STB,
  transient SR, bias completeness, and all three corners.
- `Rz/Cc` is not separately instantiated in this abstract state-space model; the first-stage
  `C1=1 pF` and `p2`/PM screen preserve the intended Miller-level bandwidth/stability target.
  Transistor-level verification must explicitly implement and measure the Phase-1 `Cc=1 pF`,
  `Rz≈1.33 kOhm` strategy.
