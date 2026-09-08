#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
OTA 结果解析(parse_margin):spectre psfascii 输出 -> 达标判定表(margin-report.md)。

用法:
  python parse_margin.py <psf目录或.raw> <spec.yml> [-o margin-report.md]

解析思路(复用 pump 项目 psfascii 经验):
  - psfascii 输出是文本,含 "VALUE" 段,每行:  "signal_name"  value
  - AC 结果是复数(real/imag),必须处理复数——只取幅度会丢掉相位
  - 从 AC 提取:Av(dB)=20log10(|vout/vdiff|)、GBW(增益=0dB 频率)、PM(相位)
  - 从 OP 提取:各管 region、gm、Vds、Vdsat
"""

import argparse
import cmath
import math
import os
import re
import sys


def read_psf_ascii_dir(psf_dir):
    """读取 spectre psfascii 目录,返回 {analysis_name: {signal: [values]}}。

    psfascii 目录结构:
      <dir>/
        ac.ac            (或 tran.tran / dc.dc)
        <signal>.ac
    简化:直接读目录下所有文本文件,按 'VALUE' 段解析。
    """
    signals = {}  # signal -> list[complex or float]
    if os.path.isdir(psf_dir):
        files = [os.path.join(psf_dir, f) for f in os.listdir(psf_dir)]
    else:
        files = [psf_dir]
    for fp in files:
        if not os.path.isfile(fp):
            continue
        try:
            with open(fp, encoding="utf-8", errors="replace") as f:
                text = f.read()
        except Exception:
            continue
        _parse_psf_text(text, signals)
    return signals


def _parse_psf_text(text, signals):
    """解析单个 psfascii 文本块,累积到 signals。

    支持两种格式:
      "name" value                    (实数)
      "name" (real imag) 或 (real, imag)   (复数)
    """
    lines = text.splitlines()
    in_value = False
    for line in lines:
        s = line.strip()
        if s == "VALUE":
            in_value = True
            continue
        if not in_value:
            continue
        # 复数: "name" (real imag)  或  "name" (real, imag)
        m = re.match(r'^\s*"([^"]+)"\s+\(\s*([+\-0-9.eE]+)(?:\s*,\s*|\s+)([+\-0-9.eE]+)\s*\)', line)
        if m:
            name = m.group(1)
            signals.setdefault(name, []).append(complex(float(m.group(2)), float(m.group(3))))
            continue
        # 实数: "name" value
        m = re.match(r'^\s*"([^"]+)"\s+([+\-0-9.eE]+)', line)
        if m:
            name = m.group(1)
            signals.setdefault(name, []).append(complex(float(m.group(2)), 0.0))
    return signals


def load_spec(spec_path):
    """读 spec.yml,提取 specs 段的目标值。

    支持单位换算:unit 字段 + 数值 → SI 值(如 unit: MHz, min: 100 → 100e6)。
    优先取 min/max(先命中者),只有 value 时用 value。
    """
    if not spec_path or not os.path.exists(spec_path):
        return {}
    specs = {}
    with open(spec_path, encoding="utf-8-sig") as f:   # utf-8-sig:兼容 Windows 工具写出的 BOM
        for line in f:
            line = line.strip()
            m = re.match(r"^([A-Za-z_][A-Za-z0-9_]*):\s*\{(.*)\}", line)
            if not m:
                continue
            name, body = m.group(1), m.group(2)
            um = re.search(r"unit\s*:\s*([^\s,}]+)", body)
            unit = um.group(1).strip("\"'") if um else ""
            for m2 in re.finditer(r"(min|max|value)\s*:\s*([^\s,}]+)", body):
                specs[name] = _to_si(m2.group(2), unit)
                if m2.group(1) in ("min", "max"):
                    break
    return specs


UNIT_SCALE = {"f": 1e-15, "p": 1e-12, "n": 1e-9, "u": 1e-6, "m": 1e-3,
              "k": 1e3, "M": 1e6, "G": 1e9}


def _to_si(num_str, unit):
    """数值字符串 + unit 字段 → SI 浮点。值自带单位后缀时优先;否则按 unit 换算。"""
    s = num_str.strip()
    m = re.match(r"^([+-]?\d*\.?\d+(?:[eE][+-]?\d+)?)(.*)$", s)
    if not m:
        return None
    num = float(m.group(1))
    suf = m.group(2).strip()
    if suf:                       # 值自带单位(如 "100M")
        key = suf[:1]
        if key in UNIT_SCALE:
            return num * UNIT_SCALE[key]
        return num
    ul = unit.lower()
    if ul in ("db", "deg", ""):   # 无量纲
        return num
    # 大小写敏感匹配:MHz→M(兆)优先于 m(毫),pF→p,uA→u
    for key, scale in (("G", 1e9), ("M", 1e6), ("k", 1e3), ("u", 1e-6),
                       ("n", 1e-9), ("p", 1e-12), ("f", 1e-15), ("m", 1e-3)):
        if unit.startswith(key):
            return num * scale
    return num


def analyze_ac(signals):
    """从 AC 信号提取 Av / GBW / PM。

    输入:输出与 vp/vn(差分输入)。支持三种输出形态:
      - 单端:vout
      - 全差分:vout_p / vout_n(取差 vout_p - vout_n)
    输入差分:vdiff = vp - vn;否则按单端输入(默认输入幅度 1)。
    """
    vp = signals.get("vp")
    vn = signals.get("vn")
    freq = signals.get("freq") or signals.get("frequency")
    if not freq:
        return {"av_db": None, "gbw": None, "pm": None, "note": "缺 freq 信号"}

    # 输出:优先全差分(vout_p - vout_n),回退单端 vout
    vout_p = signals.get("vout_p")
    vout_n = signals.get("vout_n")
    vout_s = signals.get("vout")
    if vout_p is not None and vout_n is not None:
        vout = [a - b for a, b in zip(vout_p, vout_n)]
        out_note = "diff(vout_p-vout_n)"
    elif vout_s is not None:
        vout = vout_s
        out_note = "vout"
    else:
        return {"av_db": None, "gbw": None, "pm": None, "note": "缺 vout/vout_p/vout_n 信号"}
    if not vout or len(vout) == 0:
        return {"av_db": None, "gbw": None, "pm": None, "note": "缺输出信号"}

    # 关键:目录下多个分析文件(op/dc/ac)的信号被累加,而 freq 只在 ac 文件里。
    # 以 freq 长度为基准截断,保证 AC 频点对齐(ac 的 freq 是主 sweep 变量)。
    n = len(freq)
    vout = vout[:n]
    if vp:
        vp = vp[:n]
    if vn:
        vn = vn[:n]

    # 差分输入:若 vp/vn 都有,vdiff = vp - vn;否则按单端输入(默认输入幅度 1)
    if vp and vn:
        vdiff = [a - b for a, b in zip(vp, vn)]
    else:
        vdiff = [complex(1, 0)] * len(vout)

    # 频率数组(Hz):freq 是复数信号,取实部
    freq_hz = [abs(x) for x in freq]

    # gain = vout / vdiff,幅度与相位
    gains = []
    for vo, vi in zip(vout, vdiff):
        if vi == 0:
            gains.append(0.0)
        else:
            g = vo / vi
            gains.append(abs(g))
    # 相位(vout 相对输入的相位,用于 PM)
    phases = []
    for vo, vi in zip(vout, vdiff):
        if vi == 0:
            phases.append(0.0)
        else:
            phases.append(math.degrees(cmath.phase(vo / vi)))

    # Av = 低频增益(dB),取第一个频点(或最低频)
    av_lin = gains[0]
    av_db = 20 * math.log10(av_lin) if av_lin > 0 else -999

    # GBW = 增益降到 1(0dB)的频率;线性插值
    gbw = None
    for i in range(1, len(gains)):
        if gains[i - 1] >= 1.0 >= gains[i]:
            # 线性插值 log-log
            f0, f1 = freq_hz[i - 1], freq_hz[i]
            g0, g1 = gains[i - 1], gains[i]
            if g0 > g1:
                frac = (math.log(g0) - math.log(1.0)) / (math.log(g0) - math.log(g1))
                gbw = f0 * (f1 / f0) ** frac
            break
    if gbw is None:
        gbw = freq_hz[-1] if gains[-1] >= 1.0 else None

    # PM = 在 GBW 频率处的相位 + 180
    pm = None
    if gbw is not None:
        # 找最接近 GBW 的频点相位
        idx = min(range(len(freq_hz)), key=lambda i: abs(freq_hz[i] - gbw))
        phase_at_gbw = phases[idx]
        pm = 180 + phase_at_gbw

    return {"av_db": av_db, "gbw": gbw, "pm": pm, "note": ""}


def analyze_op(psf_dir, signals):
    """从 OP 分析文件(op*.dc,单值)读各管 region;避免被 dc 扫描的终点污染。"""
    op_sigs = {}
    if os.path.isdir(psf_dir):
        for f in os.listdir(psf_dir):
            if "op" in f.lower() and f.endswith(".dc"):
                fp = os.path.join(psf_dir, f)
                try:
                    with open(fp, encoding="utf-8", errors="replace") as fh:
                        op_sigs.update(_parse_psf_text_return(fh.read()))
                except Exception:
                    continue
    result = {}
    # 全差分管名带 p/n 后缀(M1p/M1n 等);单端结构 M1..M7。两类都解析。
    devs = ["M1", "M2", "M3", "M4", "M5", "M6", "M7",
            "M1p", "M1n", "M3p", "M3n", "M5p", "M5n",
            "M8p", "M8n", "M9p", "M9n",
            "Mbias", "Mpb", "Mcmp", "Mcmn", "Mcm3", "Mcm4", "Mcm5"]
    for dev in devs:
        region = op_sigs.get(f"{dev}:region") or op_sigs.get(f"{dev}.region")
        if region:
            r = int(abs(region[-1])) if region else None
            result[dev] = r  # 0=cutoff,1=linear,2=sat,3=subth,4=breakdown
    return result


def _parse_psf_text_return(text):
    """解析单个 psfascii 文本的 VALUE 段 → {signal: [values]}。"""
    signals = {}
    _parse_psf_text(text, signals)
    return signals


def main():
    ap = argparse.ArgumentParser(description="OTA 仿真结果 -> margin-report")
    ap.add_argument("psf", help="psfascii 目录或 .raw 文件")
    ap.add_argument("spec", nargs="?", default="", help="spec.yml 路径(可选)")
    ap.add_argument("-o", "--out", default="margin-report.md", help="输出 md 路径")
    args = ap.parse_args()

    signals = read_psf_ascii_dir(args.psf)
    if not signals:
        print(f"[parse_margin] 未解析到任何信号,检查路径: {args.psf}")
        sys.exit(1)

    ac = analyze_ac(signals)
    op = analyze_op(args.psf, signals)

    spec = load_spec(args.spec)

    # 目标值(从 spec.yml 或默认)
    def target(name, default):
        v = spec.get(name)
        if v is None:
            return default
        try:
            return float(v)
        except ValueError:
            return default

    rows = [
        ("DC gain", ac["av_db"], target("Av", 40), "dB", ">="),
        ("GBW", ac["gbw"], target("GBW", 100e6), "Hz", ">="),
        ("Phase margin", ac["pm"], target("PM", 60), "deg", ">="),
    ]

    lines = []
    lines.append("# Margin Report — OTA")
    lines.append("")
    lines.append("| Spec | Measured | Target | Margin | Status |")
    lines.append("|---|---|---|---|---|")
    for name, meas, tgt, unit, op_ in rows:
        if meas is None:
            lines.append(f"| {name} | N/A | {tgt:g} {unit} | — | ⚠️ 未测到 |")
            continue
        if unit == "Hz":
            meas_s = f"{meas/1e6:.2f} MHz"
            tgt_s = f"{tgt/1e6:.2f} MHz"
        else:
            meas_s = f"{meas:.2f}"
            tgt_s = f"{tgt:g}"
        ok = meas >= tgt
        margin = f"{'+' if ok else ''}{(meas-tgt)/tgt*100:.1f}%"
        lines.append(f"| {name} | {meas_s} | {tgt_s} {unit} | {margin} | {'✅' if ok else '❌'} |")

    if op:
        lines.append("")
        lines.append("## DC Operating Point (region: 0=cutoff, 1=linear, 2=sat, 3=subth)")
        lines.append("")
        lines.append("| Device | Region |")
        lines.append("|---|---|")
        for dev, r in op.items():
            region_name = {0: "cutoff", 1: "linear", 2: "sat", 3: "subth", 4: "breakdown"}.get(r, str(r))
            flag = "✅" if r == 2 else ("⚠️" if r == 3 else "❌")
            lines.append(f"| {dev} | {region_name} {flag} |")

    if ac.get("note"):
        lines.append("")
        lines.append(f"> {ac['note']}")

    out = args.out
    with open(out, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")

    print(f"[parse_margin] 已写: {out}")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
