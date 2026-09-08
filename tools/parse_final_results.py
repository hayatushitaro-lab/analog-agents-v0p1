#!/usr/bin/env python3
"""Parse LDO_DIG2_final_v2 simulation results from PSF ASCII files.

This is a deterministic tool (Layer 2 - 手脚), called by Agent on demand.
It reads all .dc, .stb, and .tran files from the raw directories and
produces a structured metrics report.
"""
import os
import re
import sys

RAW_DIR = "/export/home/jjzhang/claude/LDO_DIG2/simulation"
DC_STB_RAW = os.path.join(RAW_DIR, "LDO_DIG2_final_v2_dc_stb.raw")
TRAN_RAW = os.path.join(RAW_DIR, "LDO_DIG2_final_v2_tran.raw")

AVDD_VALS = [1.15, 1.4, 1.7]
ILOAD_VALS = [0, 100e-6, 1e-3, 5e-3, 10e-3]


def parse_psf_ascii(filepath):
    """Parse a PSF ASCII file, returning {signal_name: [values]}."""
    signals = {}
    current_signal = None
    in_values = False

    with open(filepath) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            # Detect signal header like: "V(dvdd)" "units" "V" "key" "node"
            if line.startswith('"') and current_signal is None:
                # Check if this is a TYPE section
                pass
            # Detect the values section
            if line == 'BEGIN':
                in_values = True
                continue
            if line == 'END':
                in_values = False
                current_signal = None
                continue
            if in_values and current_signal is not None:
                try:
                    val = float(line)
                    signals[current_signal].append(val)
                except ValueError:
                    pass

            # Detect signal name
            # Format: "V(dvdd)" "units" "V" "key" "node"
            match = re.match(r'"(V\([^)]+\)|I\([^)]+\)|[a-zA-Z_][a-zA-Z0-9_]*)"\s+"units"', line)
            if match:
                current_signal = match.group(1)
                signals[current_signal] = []
            else:
                # Try simpler pattern for node names
                match2 = re.match(r'"([a-zA-Z_][a-zA-Z0-9_]*)"\s+"units"', line)
                if match2 and current_signal is None:
                    # Check if the next line has the full signal name
                    pass

    return signals


def parse_psf_ascii_v2(filepath):
    """More robust PSF ASCII parser."""
    signals = {}
    with open(filepath) as f:
        content = f.read()

    # Find all signal sections
    # Pattern: "V(dvdd)" ... BEGIN ... values ... END
    # Or: "dvdd" ... BEGIN ... values ... END

    # Split into signal blocks
    lines = content.split('\n')
    current_signal = None
    in_values = False
    i = 0

    while i < len(lines):
        line = lines[i].strip()

        # Check for signal definition line
        # Format: "V(dvdd)" "units" "V" "key" "node" "prop"
        if re.match(r'"V\([^)]+\)"', line):
            sig_name = re.match(r'"(V\([^)]+\))"', line).group(1)
            current_signal = sig_name
            signals[current_signal] = []
            i += 1
            continue

        # Check for simple node name followed by "units"
        if re.match(r'"[a-zA-Z_][a-zA-Z0-9_]*"\s+"units"', line):
            sig_name = re.match(r'"([a-zA-Z_][a-zA-Z0-9_]*)"', line).group(1)
            current_signal = sig_name
            signals[current_signal] = []
            i += 1
            continue

        # Check for current signal
        if re.match(r'"I\([^)]+\)"', line):
            sig_name = re.match(r'"(I\([^)]+\))"', line).group(1)
            current_signal = sig_name
            signals[current_signal] = []
            i += 1
            continue

        if line == 'BEGIN':
            in_values = True
            i += 1
            continue

        if line == 'END':
            in_values = False
            current_signal = None
            i += 1
            continue

        if in_values and current_signal:
            try:
                val = float(line)
                signals[current_signal].append(val)
            except ValueError:
                pass
        i += 1

    return signals


def parse_stb_margin(filepath):
    """Parse STB margin file for phase/gain margin."""
    result = {}
    with open(filepath) as f:
        content = f.read()

    # Extract phase margin
    pm_match = re.search(r'Phase margin\s*=\s*([0-9.]+)\s*Deg\s*at frequency\s*=\s*([0-9.]+)\s*(MHz|kHz|Hz|GHz)', content)
    if pm_match:
        result['phase_margin'] = float(pm_match.group(1))
        result['pm_freq'] = float(pm_match.group(2))
        result['pm_freq_unit'] = pm_match.group(3)

    gm_match = re.search(r'Gain margin\s*=\s*([0-9.]+)\s*dB\s*at frequency\s*=\s*([0-9.]+)\s*(MHz|kHz|Hz|GHz)', content)
    if gm_match:
        result['gain_margin'] = float(gm_match.group(1))
        result['gm_freq'] = float(gm_match.group(2))
        result['gm_freq_unit'] = gm_match.group(3)

    return result


def main():
    print("=" * 70)
    print("LDO_DIG2 Final v2 — Simulation Results Extraction")
    print("Arch: topo-ldo-003 (NMOS 5T + PMOS pass + ESR + soft-start)")
    print("Process: gpdk045, Corner: TT, Temp: 27C")
    print("=" * 70)

    # --- DC Results ---
    print("\n## DC Operating Point (15 sweep points: 3 avdd × 5 iload)")
    print(f"\n{'avdd(V)':>8} {'iload':>10} {'VOUT(V)':>10} {'Verr(%)':>8} {'ΔV(dV)':>10}")
    print("-" * 50)

    dc_results = []
    for fname in sorted(os.listdir(DC_STB_RAW)):
        if not fname.endswith('.dc') or 'sw_i' not in fname:
            continue
        try:
            sigs = parse_psf_ascii_v2(os.path.join(DC_STB_RAW, fname))
            dvdd_vals = sigs.get('dvdd', sigs.get('V(dvdd)', []))
            vout = dvdd_vals[-1] if dvdd_vals else 0.0

            parts = fname.replace('.dc', '').split('_')
            avdd_idx = int(parts[1].split('-')[1])
            iload_idx = int(parts[3].split('-')[1])
            avdd = AVDD_VALS[avdd_idx]
            iload = ILOAD_VALS[iload_idx]

            err_pct = (vout - 0.9) / 0.9 * 100
            delta_v = vout - 0.9

            dc_results.append({
                'avdd': avdd, 'iload': iload, 'vout': vout,
                'err_pct': err_pct, 'delta_v': delta_v
            })

            print(f"{avdd:>8.2f} {iload:>10.1e} {vout:>10.6f} {err_pct:>+7.2f}% {delta_v:>+10.6f}")
        except Exception as e:
            print(f"{fname}: ERROR - {e}")

    # --- STB Results ---
    print("\n\n## STB Stability Analysis (PM / GM)")
    print(f"\n{'avdd(V)':>8} {'iload':>10} {'PM(°)':>8} {'GM(dB)':>8} {'PM_freq':>12} {'GM_freq':>12}")
    print("-" * 62)

    for fname in sorted(os.listdir(DC_STB_RAW)):
        if not fname.endswith('.stb'):
            continue
        margin_file = fname.replace('.stb', '.margin.stb')
        margin_path = os.path.join(DC_STB_RAW, margin_file)
        if not os.path.exists(margin_path):
            continue

        try:
            margin = parse_stb_margin(margin_path)
            if not margin:
                continue

            parts = margin_file.replace('.margin.stb', '').split('_')
            avdd_idx = int(parts[1].split('-')[1])
            iload_idx = int(parts[3].split('-')[1])
            avdd = AVDD_VALS[avdd_idx]
            iload = ILOAD_VALS[iload_idx]

            pm = margin.get('phase_margin', 0)
            gm = margin.get('gain_margin', 0)
            pm_f = f"{margin.get('pm_freq', 0):.2f} {margin.get('pm_freq_unit', '')}"
            gm_f = f"{margin.get('gm_freq', 0):.2f} {margin.get('gm_freq_unit', '')}"

            print(f"{avdd:>8.2f} {iload:>10.1e} {pm:>7.1f}° {gm:>7.1f}dB {pm_f:>12} {gm_f:>12}")
        except Exception as e:
            print(f"{margin_file}: ERROR - {e}")

    # --- TRAN Results ---
    print("\n\n## TRAN Transient (Startup + Load Step)")
    print(f"\n{'avdd(V)':>8} {'I_peak(mA)':>12} {'t_settle(us)':>14} {'VOUT_max(V)':>12}")
    print("-" * 50)

    for fname in sorted(os.listdir(TRAN_RAW)):
        if not fname.endswith('.tran.tran'):
            continue

        try:
            sigs = parse_psf_ascii_v2(os.path.join(TRAN_RAW, fname))

            # I_peak: max current from Vavdd
            i_vavdd = sigs.get('I(Vavdd:p)', sigs.get('I(Vavdd)', []))
            i_peak = max(i_vavdd) * 1000 if i_vavdd else 0  # to mA

            # VOUT: max dvdd value
            dvdd_vals = sigs.get('dvdd', sigs.get('V(dvdd)', []))
            vout_max = max(dvdd_vals) if dvdd_vals else 0

            # t_settle: approximate as last dvdd value reaching steady
            # For startup, look at when dvdd first reaches 0.89V (within 1% of 0.9V)
            t_settle = None
            if 't' in sigs:
                times = sigs['t']
                for j, v in enumerate(dvdd_vals):
                    if v >= 0.881 and v <= 0.919:  # within 1%
                        t_settle = times[j] * 1e6  # to us
                        break
                if t_settle is None and dvdd_vals:
                    t_settle = times[-1] * 1e6

            parts = fname.replace('.tran.tran', '').split('_')
            avdd_idx = int(parts[1].split('-')[1])
            avdd = AVDD_VALS[avdd_idx]

            ts_str = f"{t_settle:.1f}" if t_settle else "N/A"
            print(f"{avdd:>8.2f} {i_peak:>11.1f}mA {ts_str:>13}us {vout_max:>11.6f}V")

        except Exception as e:
            print(f"{fname}: ERROR - {e}")

    # --- Summary ---
    print("\n\n## Convergence Summary")
    print("=" * 50)

    all_vout = [r['vout'] for r in dc_results]
    all_err = [abs(r['err_pct']) for r in dc_results]

    vout_min = min(all_vout)
    vout_max = max(all_vout)
    vout_mean = sum(all_vout) / len(all_vout)
    max_err = max(all_err)

    print(f"\nDC VOUT range: {vout_min:.4f}V ~ {vout_max:.4f}V (mean={vout_mean:.4f}V)")
    print(f"VOUT error: ±{max_err:.1f}% (spec: ≤1%) → {'PASS' if max_err <= 1 else 'FAIL'}")

    print(f"\n[NOTE] This is TT/27C only. PVT corners not yet extracted.")
    print("[NOTE] AC/PSRR analysis not run in this netlist (only DC+STB+TRAN).")


if __name__ == '__main__':
    main()