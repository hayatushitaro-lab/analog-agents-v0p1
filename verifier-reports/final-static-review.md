# Final Static Review — FM399 `bandgap_vcc`

**Verdict: `CONDITIONAL`**

Static topology lock passes. Final behavioral disposition remains conditional because the supplied TT DC-op parse is inconsistent with the final DUT default, and no SS/FF evidence is supplied. This report does not claim SS/FF signoff.

## Inputs reviewed

- `WORK_FM399_BANDGAP_TUNE_20260910/circuit/bandgap_vcc_dut.scs`
- `WORK_FM399_BANDGAP_TUNE_20260910/circuit/reference_original.scs`
- `WORK_FM399_BANDGAP_TUNE_20260910/spec.yml`
- `WORK_FM399_BANDGAP_TUNE_20260910/verifier-reports/iter4-tt-dcop-parse.json`
- `WORK_FM399_BANDGAP_TUNE_20260910/verifier-reports/iter4-r5-sweep.json`
- `WORK_FM399_BANDGAP_TUNE_20260910/verifier-reports/iter4-temp-r5-9p1.json`

## Topology-lock checks

| Check | Result | Evidence |
|---|---|---|
| Subcircuit count and names | PASS | 7 matching subcircuits: `COMP_BG`, `BG_DET2`, `inv_3p3`, `Schmitt_3p3`, `BG_DET1`, `BGAMP`, `bandgap_vcc` |
| Top-level interface | PASS | `bandgap_vcc` has the same 29 pins in the same order |
| Device/instance connectivity | PASS | After the four permitted resistor-length substitutions, all 7 subcircuit bodies match the reference |
| Device multiplicities/types | PASS | Primitive signatures and multiplicities match; no device type changes detected |
| BJT multiplicities | PASS | `Q8/Q3/Q2/Q6/Q5/Q7`: `m=8/2/14/2/1/4` in both netlists |
| Permitted parameterization | PASS | Only `R5_LEN`, `R2_LEN`, `R11_LEN`, `R12_LEN` are exposed; defaults are `9.1u`, `8.4u`, `8.4u`, `8.4u` respectively |
| Non-DUT tail | PASS | DUT has no standalone top-level TB instance or simulator/options tail after `ends bandgap_vcc` |

The final DUT therefore preserves the locked electrical topology. `R5` defaults to `9.1u`; `R2`, `R11`, and `R12` default to `8.4u`, as requested. No circuit or testbench source was modified for this review.

## Evidence consistency

All three JSON files report successful parsing/execution with no listed errors. The constrained R5 sweep is monotonic and supports the selected R5 value: `vref1p2_buf` is 1.19190 V at 9.0u and 1.205996 V at 9.2u, so 9.1u is expected near 1.199 V.

The final temperature evidence at R5=9.1u reports:

- sweep: -40 °C to 125 °C, 166 points;
- `vref_min` = 1.1939187 V, `vref_max` = 1.1996655 V;
- `vref_at_27` = 1.1989426 V;
- TC = -29.41 ppm/°C linear, -28.58 ppm/°C endpoint;
- maximum reported power = 63.50 µW.

These TT temperature results meet the supplied vref, TC, and power limits.

The inconsistency is that `iter4-tt-dcop-parse.json` reports `vref1p2_buf` = 1.1499228 V and `VCC` current magnitude = 15.8255 µA, exactly matching the R5=8.4u sweep point, not the final DUT default R5=9.1u. Thus it is not valid evidence of the final default TT/27 °C DC operating point without rerunning or clearly re-identifying that deck.

## Scope limits and required disposition

- The temperature JSON is TT-only; no SS or FF temperature/power results were supplied.
- The TT DC-op JSON is stale or otherwise associated with the 8.4u sweep point, so it cannot close the final-default DC check.
- Startup evidence is not established by these three JSON files alone.
- External cross-model review was unavailable due to the prior transport error (stream disconnected). This is an availability limitation, not an external PASS.

**Final static gate: PASS. Overall final review: CONDITIONAL.** Re-run the final-default TT/27 °C DC/startup check and provide SS/FF evidence before any broader signoff. Do not claim SS/FF signoff from this review.
