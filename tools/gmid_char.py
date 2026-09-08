#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
OTA Phase 0 单管表征(gmid_char):单管扫描 -> gm/Id 查找表(LUT)。

用法:
  # 1) 生成表征网表(内容来自 templates/gmid_char_{nch|pch}.scs)
  python gmid_char.py gen --type nch -o gmid_char_nch.scs

  # 2) 上传到远程 VM 跑 spectre(命令见 SKILL.md Step 4)
  #    spectre gmid_char_nch.scs -format psfascii +log gmid_char_nch.log +preset=lx
  #    (DC sweep 是小信号扫描,lx 模式足够且快)

  # 3) 解析 psfascii DC sweep -> LUT JSON
  python gmid_char.py parse ./gmid_char_nch.raw --type nch -o lut.json

  # 4) gen_netlist.py 用 LUT 查表定 W(替代平方律近似)
  python gen_netlist.py 5t_ota --spec "GBW=100MHz,CL=2p,Itail=100u" --gmid-lut lut.json -o out.scs

LUT JSON 结构:
{
  "meta": {"device": "nch_33", "W_um": 1.0, "L": 3.8e-07, "vds": 0.6},
  "points": [
    {"gmid": 20.5, "vgs": 0.42, "vov": 0.12, "id_w": 3.2,
     "gm_gds": 24.0, "ft": 8e9, "vdsat": 0.15, "region": 3},
    ...   # 按 gmid 升序
  ]
}
说明:
  - id_w 单位 uA/um(表征 W=1u,故 ids 实测值(uA) 就是 id_w)
  - 查表定 W:W = Id / (id_w * 1e-6),不依赖 muCox/Vth 假设
  - 同一工艺档(TSMC-65nm 3.3V nch_33/pch_33)表征一次,所有 OTA 设计复用;
    换工艺角(ff/ss)或换 Vds 假设时才重跑
"""

import argparse
import glob
import json
import math
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
TEMPLATES = os.path.join(HERE, "..", "shared-references", "simulation", "templates")

# 器件别名 -> 模型名(与 LUT meta 里的 device 一致)
DEVICE_ALIAS = {
    "nch": "nch_33", "n": "nch_33", "nch_33": "nch_33",
    "pch": "pch_33", "p": "pch_33", "pch_33": "pch_33",
    # 1.2V 域(阈值档别名)
    "nch_lvt": "nch_lvt", "nlvt": "nch_lvt",
    "pch_lvt": "pch_lvt", "plvt": "pch_lvt",
    "nch_hvt": "nch_hvt", "pch_hvt": "pch_hvt",
    "nch_mlvt": "nch_mlvt", "pch_mlvt": "pch_mlvt",
}
# 器件 -> 工艺描述(写进 LUT meta,便于区分档位)
DEVICE_PROCESS = {
    "nch_33": "TSMC-65nm 3.3V", "pch_33": "TSMC-65nm 3.3V",
    "nch_lvt": "TSMC-65nm 1.2V lvt", "pch_lvt": "TSMC-65nm 1.2V lvt",
    "nch_hvt": "TSMC-65nm 1.2V hvt", "pch_hvt": "TSMC-65nm 1.2V hvt",
    "nch_mlvt": "TSMC-65nm 1.2V mlvt", "pch_mlvt": "TSMC-65nm 1.2V mlvt",
}
TRACES = ["gm", "gds", "ids", "vgs", "vth", "vdsat", "region", "cgg", "cgd", "cgs"]


# ─────────────────────────────────────────────
# gen:生成表征网表
# ─────────────────────────────────────────────
def cmd_gen(device, out):
    model = DEVICE_ALIAS.get(device)
    if model is None:
        sys.exit(f"[gmid_char] 未知器件类型: {device!r}(可选 nch/pch)")
    tpl = os.path.join(TEMPLATES, f"gmid_char_{device}.scs")
    if not os.path.exists(tpl):
        sys.exit(f"[gmid_char] 表征模板不存在: {tpl}")
    with open(tpl, encoding="utf-8") as f:
        text = f.read()
    with open(out, "w", encoding="utf-8") as f:
        f.write(text)
    print(f"[gmid_char] 已生成表征网表: {out}")
    print(f"[gmid_char] 下一步: 上传远程跑 spectre(见 SKILL.md Step 4),再 parse 生成 LUT")


# ─────────────────────────────────────────────
# parse:解析 psfascii DC sweep -> LUT JSON
# ─────────────────────────────────────────────
def _parse_values(text):
    """解析 psfascii 文本的 VALUE 段 -> {signal_name: [values]}。

    兼容两种输出结构:
      a) 单文件含全部 trace(dc.dc 主文件,每 sweep 点一行所有 trace)
      b) 每信号独立文件(文件内 sweep 值行 + 该信号值行交替)
    """
    data = {}
    lines = text.splitlines()
    in_value = False
    for line in lines:
        s = line.strip()
        if s == "VALUE":
            in_value = True
            continue
        if not in_value:
            continue
        m = re.match(r'^"([^"]+)"\s+([+\-0-9.eE]+)', s)
        if m:
            name = m.group(1)
            try:
                val = float(m.group(2))
            except ValueError:
                continue
            data.setdefault(name, []).append(val)
    return data


def _find_sweep(text, data):
    """从 SWEEPVAR 段或已知键找 sweep 变量名。"""
    m = re.search(r'"SWEEPVAR"\s+"([^"]+)"', text)
    if m and m.group(1) in data:
        return m.group(1)
    for cand in ("V_GS", "vgs", "V_DS", "vds"):
        if cand in data:
            return cand
    return None


def parse_dc_sweep(raw_dir):
    """解析 psfascii DC sweep 目录 -> ({signal: [values]}, sweep_name)。

    只取每个信号第一次出现的完整数组(避免多文件重复),
    以 sweep 轴长度为基准截断对齐。
    """
    if os.path.isdir(raw_dir):
        files = sorted(glob.glob(os.path.join(raw_dir, "*.dc")))
        if not files:
            files = sorted(
                os.path.join(raw_dir, f)
                for f in os.listdir(raw_dir)
                if os.path.isfile(os.path.join(raw_dir, f))
            )
    else:
        files = [raw_dir]

    merged = {}      # name -> values(首次出现)
    order = []       # 出现顺序
    sweep_name = None
    for fp in files:
        try:
            with open(fp, encoding="utf-8", errors="replace") as f:
                text = f.read()
        except Exception:
            continue
        data = _parse_values(text)
        if not data:
            continue
        if sweep_name is None:
            sweep_name = _find_sweep(text, data)
        for name, vals in data.items():
            if name not in merged:
                merged[name] = vals
                order.append(name)

    if not merged:
        sys.exit(f"[gmid_char] 未解析到任何信号,检查 raw 路径: {raw_dir}")

    if sweep_name is None:
        sweep_name = "V_GS" if "V_GS" in merged else order[0]
    n = len(merged.get(sweep_name, []))
    if n == 0:
        sys.exit(f"[gmid_char] sweep 轴 {sweep_name} 无数据,检查网表/仿真")

    # 各信号截断到 sweep 长度对齐
    signals = {}
    for name in order:
        vals = merged[name]
        if len(vals) >= n:
            signals[name] = vals[:n]
    return signals, sweep_name


def build_lut(signals, sweep_name, device, W_um=1.0):
    """从解析结果提取 LUT 点集(过滤截止区/漏电,按 gmid 升序)。"""
    n = len(signals[sweep_name])

    def arr(key):
        return signals.get(key) or [None] * n

    gm = arr("M0:gm")
    gds = arr("M0:gds")
    ids = arr("M0:ids")
    vgs = arr("M0:vgs")
    vth = arr("M0:vth")
    vdsat = arr("M0:vdsat")
    region = arr("M0:region")
    cgg = arr("M0:cgg")

    points = []
    for i in range(n):
        ids_i = ids[i]
        if ids_i is None or abs(ids_i) < 1e-12:   # abs:PMOS ids 为负,不能按 < 1e-12 滤
            continue
        reg = region[i]
        if reg is not None and int(reg) == 0:
            continue  # 截止区(cutoff)无 gm/Id 意义,滤掉
        gm_i = gm[i] if gm[i] is not None else 1e-15
        gds_i = gds[i] if gds[i] is not None else 1e-15
        gmid = abs(gm_i) / abs(ids_i)              # spectre 的 gm 报正幅值(PMOS 的 ids 为负),取绝对值
        if gmid <= 0:
            continue
        vth_i = vth[i] if vth[i] is not None else 0.0
        vgs_i = vgs[i] if vgs[i] is not None else 0.0
        cgg_i = cgg[i] if cgg[i] is not None else 1e-18
        points.append({
            "gmid": round(gmid, 3),
            "vgs": round(vgs_i, 5),
            "vov": round(vgs_i - vth_i, 5),
            "id_w": round(abs(ids_i) * 1e6 / W_um, 4),        # uA/um(取幅值)
            "gm_gds": round(gm_i / gds_i, 2),
            "ft": round(gm_i / (2 * math.pi * cgg_i), 3),  # Hz
            "vdsat": round(vdsat[i], 5) if vdsat[i] is not None else None,
            "region": int(region[i]) if region[i] is not None else None,
        })
    points.sort(key=lambda p: p["gmid"])
    if not points:
        sys.exit("[gmid_char] LUT 无有效点(所有点 ids<1e-12?),检查仿真是否收敛")
    return points


def cmd_parse(raw_dir, device, out, W_um=1.0):
    model = DEVICE_ALIAS.get(device)
    if model is None:
        sys.exit(f"[gmid_char] 未知器件类型: {device!r}(可选 nch/pch)")
    signals, sweep_name = parse_dc_sweep(raw_dir)
    points = build_lut(signals, sweep_name, model, W_um)

    lut = {
        "meta": {
            "device": model,
            "process": DEVICE_PROCESS.get(model, "TSMC-65nm"),
            "W_um": W_um,
            "L_um": 0.38,          # 表征管 L(模板固定 380n),W_from_gmid 按 L 比缩放
            "sweep": sweep_name,
            "n_points": len(points),
        },
        "points": points,
    }
    with open(out, "w", encoding="utf-8") as f:
        json.dump(lut, f, indent=2, ensure_ascii=False)
    print(f"[gmid_char] 已写 LUT: {out}({len(points)} 点,device={model})")
    # 打印 gm/Id 分区速览(供预计算选点)
    for target in (8, 10, 12, 15, 18, 22):
        pt = min(points, key=lambda p: abs(p["gmid"] - target))
        print(f"  gm/Id≈{pt['gmid']:6.2f} | id_w={pt['id_w']:8.3f} uA/um | "
              f"gm/gds={pt['gm_gds']:6.1f} | ft={pt['ft']/1e9:6.2f} GHz | "
              f"vdsat={pt['vdsat'] if pt['vdsat'] is not None else float('nan'):.4f} V")


def main():
    # Windows 控制台默认 GBK,先切 UTF-8 再打印(中文不报 UnicodeEncodeError)
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    ap = argparse.ArgumentParser(description="OTA Phase 0 单管表征(gmid_char):gm/Id 查找表(LUT)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_gen = sub.add_parser("gen", help="生成单管表征网表")
    p_gen.add_argument("--type", required=True, help="nch 或 pch")
    p_gen.add_argument("-o", "--out", default="", help="输出 .scs 路径")

    p_parse = sub.add_parser("parse", help="解析 psfascii DC sweep -> LUT JSON")
    p_parse.add_argument("raw", help="psfascii raw 目录或文件")
    p_parse.add_argument("--type", required=True, help="nch 或 pch")
    p_parse.add_argument("-o", "--out", default="", help="输出 lut.json 路径")
    p_parse.add_argument("--W-um", type=float, default=1.0, help="表征 W(um),默认 1.0")
    args = ap.parse_args()

    if args.cmd == "gen":
        out = args.out or f"gmid_char_{args.type}.scs"
        cmd_gen(args.type, out)
    elif args.cmd == "parse":
        out = args.out or f"lut_{DEVICE_ALIAS.get(args.type, args.type)}.json"
        cmd_parse(args.raw, args.type, out, args.W_um)


if __name__ == "__main__":
    main()
