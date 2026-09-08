#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
OTA 调参引擎(gen_netlist):结构名 + 指标 -> 预计算 -> 参数化 Spectre 网表。

用法:
  python gen_netlist.py 5t_ota --spec "Av=60dB,GBW=100MHz,CL=2p,Itail=100u,VDD=3.3" -o out.scs
  python gen_netlist.py 5t_ota --json spec.json -o out.scs

思路(pump 项目自校准法):
  1) 读配方 yml 拿方程与待校准系数初值
  2) 用方程预计算尺寸(系数标"待校准")
  3) 填模板 -> 出参数化 .scs
  4) 仿真后 parse_margin.py 反推真实系数 -> 更新 spec.json -> 再跑本脚本
"""

import argparse
import json
import math
import re
import sys
import os

HERE = os.path.dirname(os.path.abspath(__file__))
TOPOLOGIES = os.path.join(HERE, "..", "wiki", "topologies")
TEMPLATES = os.path.join(HERE, "..", "shared-references", "simulation", "templates")


def load_yaml_simple(path):
    """极简 yaml 读取:只取扁平 key: value(不用第三方库,避免依赖)。"""
    data = {}
    if not os.path.exists(path):
        return data
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.rstrip("\n")
            if ":" not in line:
                continue
            k, v = line.split(":", 1)
            k = k.strip()
            v = v.strip()
            # 跳过列表/块开头
            if v == "" or v.startswith("-") or v.startswith("{") or v.startswith("|"):
                continue
            # 去引号
            v = v.strip("\"'")
            data[k] = v
    return data


def parse_spec(spec_str):
    """解析 "Av=60dB,GBW=100MHz,CL=2p,Itail=100u,VDD=3.3" 或 "Av=60,GBW=100e6,CL=2e-12"。

    返回 {name: (value_float_SI, raw_str)}。单位后缀只解析常见量纲。
    """
    out = {}
    for part in spec_str.split(","):
        part = part.strip()
        if not part or "=" not in part:
            continue
        name, val = part.split("=", 1)
        name = name.strip()
        val = val.strip()
        try:
            parsed = parse_value(val)
        except ValueError:
            # DevN/DevP 之类字符串 token(器件档名)原样保留
            if name.upper().startswith("DEV"):
                out[name] = (val, val)
                continue
            raise
        out[name] = (parsed, val)
    return out


UNIT_SCALE = {
    "f": 1e-15, "p": 1e-12, "n": 1e-9, "u": 1e-6, "m": 1e-3,
    "k": 1e3, "M": 1e6, "G": 1e9,
}


def parse_value(s):
    """解析带单位后缀的数值 -> SI 浮点。支持 '60dB'(取数值60)、'100MHz'、'2p'、'100u'。"""
    s = s.strip()
    m = re.match(r"^([+-]?\d*\.?\d+(?:[eE][+-]?\d+)?)(.*)$", s)
    if not m:
        raise ValueError(f"无法解析数值: {s!r}")
    num = float(m.group(1))
    suffix = m.group(2).strip()
    if not suffix:
        return num
    # dB 是无量纲比值,直接取数值
    if suffix.lower() in ("db", "deg", "v/us", "v"):
        # v/us 之类复合单位这里简化:只取数值,量纲由方程处理
        if suffix.lower() == "db" or suffix.lower() == "deg":
            return num
        return num
    # 单字母/双字母单位
    key = suffix[:1]
    if key in UNIT_SCALE:
        return num * UNIT_SCALE[key]
    return num


def si(v):
    """SI 值 -> 人类可读字符串(网表参数友好)。"""
    if v == 0:
        return "0"
    a = abs(v)
    # 从大到小找第一个 scale <= a,即选最大单位使 a/scale >= 1(避免浮点边界)
    for suffix, scale in [("G", 1e9), ("M", 1e6), ("k", 1e3), ("", 1.0), ("m", 1e-3), ("u", 1e-6), ("n", 1e-9), ("p", 1e-12)]:
        if a >= scale:
            return f"{v/scale:g}{suffix}"
    return f"{v:g}"


def vov_from_gmid(gm_over_Id, n=1.35, Vt=0.02585):
    """gm/Id -> Vov(强反型平方律 Vov = 2/(gm/Id))。

    注:gm/Id > 15 进入弱反型区,平方律不再精确(会低估 Vov、高估 W),
    但该区设计点本应避免——调用方会预警,不硬算 W。
    返回 (vov, region_str)。
    """
    if gm_over_Id <= 15.0:
        # 强/中反型:平方律(这是 gm/Id 法的核心近似,量级正确)
        return 2.0 / gm_over_Id, "strong"
    else:
        # 弱反型:仅返回近似 Vov 供参考,调用方应预警
        vov = n * Vt * math.log(gm_over_Id * Vt / 0.025)
        return max(vov, 0.05), "weak"


# ============================================================
# 器件档选择:按 VDD 域候选 + 拓扑堆叠电压预算分析(非硬编码)
# ============================================================
# 工艺库档位表(TSMC-65nm 3D3 crn65lp_3d3;Vth 估算,lvt/33 为实测,其余待校准)
# 电压域: VDD>2.0 -> 3.3V 域(33 档);VDD<=1.2 -> 1.2V 域(lvt/mlvt/标准/hvt)
DEVICE_TABLE = [
    {"n": "nch_33",   "p": "pch_33",   "domain": 3.3, "vth_n": 0.648, "vth_p": 0.573, "note": "3.3V 标准 Vt(实测)"},
    {"n": "nch_lvt",  "p": "pch_lvt",  "domain": 1.2, "vth_n": 0.263, "vth_p": 0.306, "note": "1.2V 低阈值/高速(OP 实测)"},
    {"n": "nch_mlvt", "p": "pch_mlvt", "domain": 1.2, "vth_n": 0.350, "vth_p": 0.380, "note": "1.2V 中阈值(估)"},
    {"n": "nch",      "p": "pch",      "domain": 1.2, "vth_n": 0.420, "vth_p": 0.450, "note": "1.2V 标准 Vt(估)"},
    {"n": "nch_hvt",  "p": "pch_hvt",  "domain": 1.2, "vth_n": 0.550, "vth_p": 0.580, "note": "1.2V 高阈值/低漏电(估)"},
]


def stack_budget(topo, vdd, vcm, vth_n, vth_p, vov_n, vov_p):
    """拓扑电压链:按每管节点电压分配,检查能否全部饱和(Vds>=Vov)。

    返回 (min_margin, details) — min_margin<0 表示该档电压预算不足(有管进线性区)。
    各拓扑的电压链来自配方(输入对类型决定 Vcm 方向):
      - 5t: PMOS 输入,链 VDD->M5->M1/2->M3/4->VSS
      - telescopic: NMOS 输入,链 VDD->M5(pmir)->M3(casc)->M1->M7(tail)->VSS
      - folded: NMOS 输入折叠,链 VDD->负载->casc->M1->M7
      - current_mirror_load: NMOS 输入 + PMOS diode 负载,链 VDD->M3/4->M1->M5
    """
    if topo == "5t_ota":
        net_tail = vcm + vth_p + vov_p                      # PMOS 输入源 = VCM+|Vgs|
        net_d1 = vth_n + vov_n                              # NMOS diode 负载漏
        vds = {"tail(M5)": vdd - net_tail,                  # |Vds| 尾源
               "in(M1/2)": net_tail - net_d1,               # |Vds| 输入对
               "load(M3/4)": net_d1}                        # Vds 负载
        req = {"tail(M5)": vov_p, "in(M1/2)": vov_p, "load(M3/4)": vov_n}
    elif topo == "telescopic_ota":
        net_s = vcm - (vth_n + vov_n)                       # NMOS 输入源(尾源漏)
        vds = {"tail(M7)": net_s,                            # NMOS 尾源 Vds
               "in(M1/2)": vov_n,                            # 输入对最小 Vds
               "casc(M3)": vov_n,                            # cascode 最小 Vds
               "mir(M5)": vdd - (net_s + vov_n + vov_n)}     # PMOS 镜像 |Vds|
        req = {"tail(M7)": vov_n, "in(M1/2)": vov_n, "casc(M3)": vov_n, "mir(M5)": vov_p}
    elif topo == "folded_cascode_ota":
        vb2 = 0.6 if vdd <= 1.2 else 1.4                     # cascode 栅(1.2V 域低)
        net_s = vcm - (vth_n + vov_n)                        # 输入源
        net_f = vb2 + vth_p + vov_p                          # 折叠节点 = VB2+|Vgs_p|
        vds = {"tail(M7)": net_s,                            # NMOS 尾源
               "in(M1/2)": net_f - net_s,                    # 输入对 |Vds| = 折叠节点-源
               "casc(M3)": vdd - net_f - vov_p}              # PMOS cascode+负载余量
        req = {"tail(M7)": vov_n, "in(M1/2)": vov_n, "casc(M3)": vov_p}
    elif topo == "current_mirror_load_ota":
        net_s = vcm - (vth_n + vov_n)                        # NMOS 输入源
        net_d1 = vdd - (vth_p + vov_p)                       # PMOS diode 负载漏
        vds = {"tail(M5)": net_s,                            # NMOS 尾源
               "in(M1/2)": net_d1 - net_s,                   # 输入对 Vds
               "load(M3/4)": vdd - net_d1}                   # PMOS 负载 |Vds|
        req = {"tail(M5)": vov_n, "in(M1/2)": vov_n, "load(M3/4)": vov_p}
    elif topo == "two_stage_miller_ota":
        # telescopic 第一级 + CS 第二级(NMOS 输入,telescopic 案例实测 VCM=1.2):
        #   第一级 VSS->M7(tail)->net_tail->M1/2(in)->M3/4(casc)->net_c/net_a->M5/6(pmir)->VDD
        #   第二级 VSS->M9(load)->vout->M8(cs)->VDD(输出静态≈VDD-|Vgs8|,用 VCM 上界估)
        net_s = vcm - (vth_n + vov_n)                        # 尾源漏
        vds = {"tail(M7)": net_s,                            # NMOS 尾源 Vds
               "in(M1/2)": vov_n,                            # 输入对最小 Vds
               "casc(M3/4)": vov_n,                          # cascode 最小 Vds
               "mir(M5/6)": vdd - (net_s + vov_n + vov_n),   # PMOS 镜像 |Vds|
               "cs2(M8)": vdd - vcm,                         # 第二级 PMOS |Vds|(估)
               "load2(M9)": vcm}                             # 第二级 NMOS Vds(估)
        req = {"tail(M7)": vov_n, "in(M1/2)": vov_n, "casc(M3/4)": vov_n,
               "mir(M5/6)": vov_p, "cs2(M8)": vov_p, "load2(M9)": vov_n}
    elif topo == "fully_diff_cmfb_ota":
        # 全差分两级(telescopic 第一级 + NMOS CS 第二级 + CMFB):
        #   第一级 VSS->M7(tail)->net_tail->M1p/1n(in)->M3p/3n(casc)->net_ap/an->M5p/5n(pmir)->VDD
        #   (net_ap/an 是 cascode 漏,低电平 ≈VB2-Vth → 第二级用 NMOS CS,不是 PMOS CS!)
        #   第二级 VSS->M8p/8n(NMOS CS,栅=net_ap/an)->vout_p/n->M9p/9n(PMOS 负载,栅=vcmfb)->VDD
        #   输出共模由 CMFB 钳到 VCM_OUT≈VDD/2;用 vcm 估输入链,VDD/2 估输出链
        net_s = vcm - (vth_n + vov_n)                        # 尾源漏
        vout_cm = vdd / 2.0                                  # CMFB 钳输出共模 ≈ VDD/2
        vds = {"tail(M7)": net_s,                            # NMOS 尾源 Vds
               "in(M1)": vov_n,                              # 输入对最小 Vds
               "casc(M3)": vov_n,                            # cascode 最小 Vds
               "pmir(M5)": vdd - (net_s + vov_n + vov_n),    # PMOS 电流源负载 |Vds|
               "cs2(M8)": vout_cm,                           # 第二级 NMOS CS Vds(=输出共模)
               "load2(M9)": vdd - vout_cm}                   # 第二级 PMOS 负载 |Vds|
        req = {"tail(M7)": vov_n, "in(M1)": vov_n, "casc(M3)": vov_n,
               "pmir(M5)": vov_p, "cs2(M8)": vov_n, "load2(M9)": vov_p}
    else:
        return 0.0, "unknown topology"
    margins = {k: vds[k] - req[k] for k in vds}
    min_margin = min(margins.values())
    worst = min(margins, key=margins.get)
    detail = " | ".join(f"{k}:Vds={vds[k]:.2f}V" for k in vds)
    return min_margin, f"{detail} | 瓶颈={worst} marg={min_margin:+.2f}V"


def select_devices(topo, vdd, spec, vov_n, vov_p, lut_keys=None):
    """按 VDD 域候选 + 拓扑堆叠分析选器件档(不硬编码到单一器件)。

    规则:
      1) spec 显式 DevN/DevP -> 直接用(用户指定优先)
      2) 否则按 VDD 域取候选档(3.3V 域唯一 nch_33/pch_33;1.2V 域 lvt/mlvt/标准/hvt)
      3) 对每个候选跑 stack_budget,取饱和裕度最大的档;
         裕度并列时优先已表征 LUT 的档(W 可查表,免平方律回退)
      4) 输出每档裕度 + 理由;全部裕度<0 -> 警告"该结构在此 VDD 电压预算不足"
    返回 (dev_n, dev_p, reasons:list[str])
    """
    dev_n = spec.get("DevN", (None,))[0]
    dev_p = spec.get("DevP", (None,))[0]
    if dev_n or dev_p:
        dev_n = dev_n or dev_p
        dev_p = dev_p or dev_n
        return dev_n, dev_p, [f"spec 显式指定 DevN/DevP={dev_n}/{dev_p}"]

    domain = 3.3 if vdd > 2.0 else 1.2
    cands = [d for d in DEVICE_TABLE if d["domain"] == domain]
    lut_keys = lut_keys or []
    scored = []
    vcm = spec.get("VCM")
    if isinstance(vcm, (tuple, list)):
        vcm = vcm[0]
    if vcm is None:
        vcm = 0.5 if domain == 1.2 else 1.2
    for c in cands:
        marg, detail = stack_budget(topo, vdd, vcm,
                                    c["vth_n"], c["vth_p"], vov_n, vov_p)
        has_lut = (c["n"] in lut_keys) and (c["p"] in lut_keys)
        scored.append((marg, has_lut, c, detail))
    # 排序:裕度大优先;同裕度有 LUT 优先
    scored.sort(key=lambda x: (-x[0], not x[1]))
    best_marg, best_lut, best, best_detail = scored[0]
    reasons = [f"[device-select] VDD={vdd:g}V 域={domain:g}V 候选 {len(cands)} 档:"]
    for marg, has_lut, c, detail in sorted(scored, key=lambda x: -x[0]):
        tag = "LUT" if has_lut else "    "
        reasons.append(f"  {c['n']}/{c['p']:<12} margin={marg:+.2f}V [{tag}] {c['note']}")
    reasons.append(f"  堆叠分析({topo}): {best_detail}")
    reasons.append(f"  -> 选 {best['n']}/{best['p']} (margin={best_marg:+.2f}V)")
    if best_marg < 0:
        reasons.append(f"  ⚠️ 所有候选档堆叠裕度<0:该结构在 VDD={vdd:g}V 电压预算不足"
                       f"(有管会进线性区),建议升 VDD/换结构/换输入对类型")
    return best["n"], best["p"], reasons


def load_lut(path):
    """读 Phase 0 生成的 gm/Id LUT JSON(gmid_char.py parse 的产物)。"""
    with open(path, encoding="utf-8-sig") as f:  # utf-8-sig 兼容 Windows 工具写出的 BOM
        return json.load(f)


def load_luts(path_spec):
    """--gmid-lut 支持逗号分隔多个 LUT 文件 → {device: lut} 容器。"""
    luts = {}
    for p in [x.strip() for x in path_spec.split(",") if x.strip()]:
        lut = load_lut(p)
        dev = (lut.get("meta") or {}).get("device")
        if dev:
            luts[dev] = lut
        else:
            print(f"[gen_netlist] 警告: {p} 无 meta.device,跳过")
    return luts


def lookup_id_w(lut, device, target_gmid):
    """从 LUT 查 id_w(uA/um),gmid 轴上线性插值,超出范围取端点。

    lut 可为单 LUT(meta.device 匹配)或多 LUT 容器 {"nch_33": {...}, ...}。
    返回 None 表示 LUT 缺失/器件不匹配,调用方应回退平方律。
    """
    if not lut:
        return None
    # 多 LUT 容器:先按 device 取对应子 LUT
    if "points" not in lut and isinstance(lut, dict):
        sub = lut.get(device)
        if not sub:
            return None
        lut = sub
    points = lut.get("points") or []
    if not points:
        return None
    meta_dev = (lut.get("meta") or {}).get("device")
    if meta_dev and meta_dev != device:
        return None
    if len(points) == 1:
        return points[0]["id_w"]
    if target_gmid <= points[0]["gmid"]:
        return points[0]["id_w"]
    if target_gmid >= points[-1]["gmid"]:
        return None  # 超出 LUT 范围(弱反型深部)→ 回退平方律,避免取截止端点导致 W 爆炸
    for i in range(1, len(points)):
        if points[i]["gmid"] >= target_gmid:
            g0, g1 = points[i - 1]["gmid"], points[i]["gmid"]
            w0, w1 = points[i - 1]["id_w"], points[i]["id_w"]
            t = (target_gmid - g0) / (g1 - g0)
            return w0 + t * (w1 - w0)
    return points[-1]["id_w"]


def W_from_gmid(Id, L, gm_over_Id, muCox, lut=None, device="nch_33", n=1.35, Vt=0.02585):
    """由 Id/L/gm/Id 反推 W。

    优先: Phase 0 真实 LUT(device=nch_33/pch_33)查 id_w → W = Id / (id_w·1e-6),
          不依赖 μCox/Vth 假设,短沟道最准。
    回退: 平方律(强/中反型): Id = (1/2)·μCox·(W/L)·Vov² → W = 2·Id·L/(μCox·Vov²)
          弱反型(gm/Id>15): 平方律低估 Vov 会高估 W,返回平方律下限并交由调用方预警。
    返回 W 估算(单位 m)。
    """
    if lut is not None:
        # 多 LUT 容器先归一化为当前器件子 LUT(与 lookup_id_w 内部逻辑一致)
        if "points" not in lut and isinstance(lut, dict):
            lut = lut.get(device)
        id_w = lookup_id_w(lut, device, gm_over_Id)   # uA/um
        # W[m] = Id[A] / id_w[A/m];uA/um 与 A/m 数值相等,直接数值相除
        if id_w:
            # L 缩放(仅新 LUT 带 L_um 字段时):1.2V lvt 域 Vov 小,同 Vov 下过设计电流需 W∝L;
            # 老 LUT(无 L_um,3.3V 域 nch_33/pch_33)不缩放——telescopic 达标案例已验证 L=1u 直接可用。
            l_um = (lut.get("meta") or {}).get("L_um")
            if l_um is not None:
                l_ratio = L / (l_um * 1e-6)
                return Id / id_w * l_ratio
            return Id / id_w
    vov, region = vov_from_gmid(gm_over_Id, n, Vt)
    if region == "strong":
        return 2.0 * Id * L / (muCox * vov ** 2)
    # 弱反型:平方律(以 gm/Id=15 处 Vov=2/15≈0.133 为保守下限,避免 W 无限大)
    vov_floor = max(vov, 2.0 / 15.0)
    return 2.0 * Id * L / (muCox * vov_floor ** 2)


def precompute_5t_ota(spec, lut=None):
    """5T OTA 预计算。返回 (params, meta)。系数为初值,标"待校准"。

    params = 模板 parameters 行要替换的 token
    meta   = 打印/rationale 用(所有拓扑统一字段:gm1/Id/gm_over_Id/vov1/region1)
    """
    # 从 spec 取指标(缺省用默认)
    vdd = spec.get("VDD", (3.3,))[0]
    vcm = spec.get("VCM", (0.5,))[0]   # PMOS 输入默认低 Vcm;由 select_devices 域推断时会被覆盖
    gbw = spec.get("GBW", (100e6,))[0]          # Hz
    cl = spec.get("CL", (2e-12,))[0]            # F
    itail = spec.get("Itail", (100e-6,))[0]     # A

    # --- 待校准系数初值 ---
    # 实测(TSMC-65nm 3.3V, Vth_n≈0.65V/Vth_p≈0.57V, 从 OP 反推):
    #   NMOS μCox≈187uA/V², PMOS μCox≈62uA/V²
    muCox_p = 62e-6        # A/V^2 (65nm 3.3V PMOS 实测)
    muCox_n = 187e-6       # A/V^2 (65nm 3.3V NMOS 实测)

    # --- 核心方程 ---
    gm1 = 2 * math.pi * gbw * cl          # 输入管跨导
    Id = itail / 2.0                      # 每边电流
    gm_over_Id = gm1 / Id                 # 偏置点
    if gm_over_Id <= 0:
        raise ValueError(f"gm/Id={gm_over_Id:.2f} 非法,检查 GBW/Itail 是否矛盾")

    vov1, region1 = vov_from_gmid(gm_over_Id)   # 分段 Vov1(替代 2/(gm/Id))
    vov3, _ = vov_from_gmid(10.0)               # 负载镜目标 gm/Id~10(中反型)
    # 尾源电流镜:偏置用电流源 IREF=Itail(精确,不依赖 Vth),不再算 VB

    # 器件档:按 VDD 域候选 + 5T 堆叠电压预算分析(PMOS 输入,链 VDD->M5->M1/2->M3/4)
    dev_n, dev_p, dev_reasons = select_devices(
        "5t_ota", vdd, spec, vov3, vov1,
        lut_keys=list(lut.keys()) if lut else None)
    for r in dev_reasons:
        print(f"[gen_netlist] {r}")

    L1 = 380e-9                           # 输入对短 L
    L3 = 1.0e-6                           # 负载镜 2-4x 最小 L
    L5 = 1.0e-6                           # 尾源长 L

    # W 由 Id/L/gm/Id 分段反推(器件档由 select_devices 分析得出)
    W1 = W_from_gmid(Id, L1, gm_over_Id, muCox_p, lut=lut, device=dev_p)
    W3 = W_from_gmid(Id, L3, 10.0, muCox_n, lut=lut, device=dev_n)
    W5 = W_from_gmid(itail, L5, 10.0, muCox_p, lut=lut, device=dev_p)   # 尾源电流镜参考管

    # finger 规则:默认 1u/finger
    def nf_for(W, finger=1e-6):
        nf = max(1, int(round(W / finger)))
        return nf

    nf1 = nf_for(W1)
    nf3 = nf_for(W3)
    nf5 = nf_for(W5)

    params = {
        "VDD": vdd, "VCM": vcm, "IREF": itail,
        "DEV_N": dev_n, "DEV_P": dev_p,
        "L1": L1, "W1": W1, "nf1": nf1,
        "L3": L3, "W3": W3, "nf3": nf3,
        "L5": L5, "W5": W5, "nf5": nf5,
        "CL": cl,
    }
    meta = {
        "gm1": gm1, "Id": Id, "gm_over_Id": gm_over_Id, "vov1": vov1, "region1": region1,
        "dev_n": dev_n, "dev_p": dev_p,
    }
    return params, meta


# 拓扑 -> 预计算函数 分派表(新增结构 = 加一行 + 一个 precompute_xxx 函数)
# 注:此表必须在所有 precompute_xxx 函数定义之后(见文件末尾 PRECOMPUTE 真正定义处)


def precompute_current_mirror_load_ota(spec, lut=None):
    """NMOS 输入对 + PMOS 电流镜负载(与 5T 对偶,高 Vcm)。"""
    vdd = spec.get("VDD", (3.3,))[0]
    vcm_def = 0.8 if vdd <= 1.2 else 2.1    # NMOS 输入高 Vcm
    vcm = spec.get("VCM", (vcm_def,))[0]
    gbw = spec.get("GBW", (100e6,))[0]
    cl = spec.get("CL", (2e-12,))[0]
    itail = spec.get("Itail", (100e-6,))[0]

    muCox_n = 187e-6       # NMOS 输入对(实测)
    muCox_p = 62e-6        # PMOS 负载镜(实测)

    gm1 = 2 * math.pi * gbw * cl
    Id = itail / 2.0
    gm_over_Id = gm1 / Id
    if gm_over_Id <= 0:
        raise ValueError(f"gm/Id={gm_over_Id:.2f} 非法")

    vov1, region1 = vov_from_gmid(gm_over_Id)
    vov3, _ = vov_from_gmid(10.0)   # PMOS 负载镜 gm/Id~10

    # 器件档:按 VDD 域候选 + 堆叠电压预算(链 VDD->负载->in->tail)
    dev_n, dev_p, dev_reasons = select_devices(
        "current_mirror_load_ota", vdd, spec, vov3, vov1,
        lut_keys=list(lut.keys()) if lut else None)
    for r in dev_reasons:
        print(f"[gen_netlist] {r}")

    L1 = 380e-9
    L3 = 1.0e-6
    L5 = 1.0e-6

    W1 = W_from_gmid(Id, L1, gm_over_Id, muCox_n, lut=lut, device=dev_n)     # NMOS 输入对
    W3 = W_from_gmid(Id, L3, 10.0, muCox_p, lut=lut, device=dev_p)           # PMOS 负载镜
    W5 = W_from_gmid(itail, L5, 10.0, muCox_n, lut=lut, device=dev_n)        # NMOS 尾源(电流镜参考)

    def nf_for(W, finger=1e-6):
        return max(1, int(round(W / finger)))

    nf1 = nf_for(W1)
    nf3 = nf_for(W3)
    nf5 = nf_for(W5)

    # 尾源电流镜:IREF=Itail,不依赖 Vth

    params = {
        "VDD": vdd, "VCM": vcm, "IREF": itail,
        "DEV_N": dev_n, "DEV_P": dev_p,
        "L1": L1, "W1": W1, "nf1": nf1,
        "L3": L3, "W3": W3, "nf3": nf3,
        "L5": L5, "W5": W5, "nf5": nf5,
        "CL": cl,
    }
    meta = {
        "gm1": gm1, "Id": Id, "gm_over_Id": gm_over_Id, "vov1": vov1, "region1": region1,
        "dev_n": dev_n, "dev_p": dev_p,
    }
    return params, meta


def precompute_telescopic_ota(spec, lut=None):
    """Telescopic cascode OTA: NMOS 输入 + NMOS cascode + PMOS 镜像(7 管,高增益)。"""
    vdd = spec.get("VDD", (3.3,))[0]
    vcm = spec.get("VCM", (1.2,))[0]
    gbw = spec.get("GBW", (100e6,))[0]
    cl = spec.get("CL", (2e-12,))[0]
    itail = spec.get("Itail", (100e-6,))[0]
    # cascode 栅偏置(spec 可覆盖,标"待校准")
    vb2 = spec.get("VB2", (1.5,))[0]   # NMOS cascode 栅

    muCox_p = 62e-6
    muCox_n = 187e-6

    gm1 = 2 * math.pi * gbw * cl
    Id = itail / 2.0
    gm_over_Id = gm1 / Id
    if gm_over_Id <= 0:
        raise ValueError(f"gm/Id={gm_over_Id:.2f} 非法")

    vov1, region1 = vov_from_gmid(gm_over_Id)
    vov3, _ = vov_from_gmid(10.0)

    # 器件档:按 VDD 域候选 + telescopic 堆叠电压预算(链 VDD->mir->casc->in->tail)
    dev_n, dev_p, dev_reasons = select_devices(
        "telescopic_ota", vdd, spec, vov3, vov1,
        lut_keys=list(lut.keys()) if lut else None)
    for r in dev_reasons:
        print(f"[gen_netlist] {r}")

    L1 = 380e-9                      # 输入对短 L
    L3 = 1.0e-6                      # cascode 长 L(提增益)
    L5 = 1.0e-6                      # PMOS 镜像长 L
    L7 = 1.0e-6                      # 尾源长 L

    W1 = W_from_gmid(Id, L1, gm_over_Id, muCox_n, lut=lut, device=dev_n)    # NMOS 输入对
    W3 = W_from_gmid(Id, L3, 10.0, muCox_n, lut=lut, device=dev_n)          # NMOS cascode
    W5 = W_from_gmid(Id, L5, 10.0, muCox_p, lut=lut, device=dev_p)          # PMOS 镜像
    W7 = W_from_gmid(itail, L7, 10.0, muCox_n, lut=lut, device=dev_n)       # NMOS 尾源(电流镜参考)

    def nf_for(W, finger=1e-6):
        return max(1, int(round(W / finger)))

    params = {
        "VDD": vdd, "VCM": vcm, "IREF": itail, "VB2": vb2,
        "DEV_N": dev_n, "DEV_P": dev_p,
        "L1": L1, "W1": W1, "nf1": nf_for(W1),
        "L3": L3, "W3": W3, "nf3": nf_for(W3),
        "L5": L5, "W5": W5, "nf5": nf_for(W5),
        "L7": L7, "W7": W7, "nf7": nf_for(W7),
        "CL": cl,
    }
    meta = {
        "gm1": gm1, "Id": Id, "gm_over_Id": gm_over_Id, "vov1": vov1, "region1": region1,
        "dev_n": dev_n, "dev_p": dev_p,
    }
    return params, meta


def precompute_folded_cascode_ota(spec, lut=None):
    """Folded-cascode OTA: NMOS 输入折叠到 PMOS cascode(7 管,摆幅大)。"""
    vdd = spec.get("VDD", (3.3,))[0]
    vcm_def = 0.8 if vdd <= 1.2 else 1.2    # 1.2V 域:NMOS 输入 Vcm 高
    vb2_def = 0.6 if vdd <= 1.2 else 1.4    # 1.2V 域:PMOS cascode 栅偏低
    vcm = spec.get("VCM", (vcm_def,))[0]
    gbw = spec.get("GBW", (100e6,))[0]
    cl = spec.get("CL", (2e-12,))[0]
    itail = spec.get("Itail", (200e-6,))[0]
    vb2 = spec.get("VB2", (vb2_def,))[0]   # PMOS cascode 栅(1.4 折叠节点才够高,1.8 会进线性区)

    muCox_p = 62e-6
    muCox_n = 187e-6

    gm1 = 2 * math.pi * gbw * cl
    Id = itail / 2.0
    gm_over_Id = gm1 / Id
    if gm_over_Id <= 0:
        raise ValueError(f"gm/Id={gm_over_Id:.2f} 非法")

    vov1, region1 = vov_from_gmid(gm_over_Id)
    vov3, _ = vov_from_gmid(10.0)

    # 器件档:按 VDD 域候选 + folded 堆叠电压预算(链 VDD->负载->casc->in->tail)
    dev_n, dev_p, dev_reasons = select_devices(
        "folded_cascode_ota", vdd, spec, vov3, vov1,
        lut_keys=list(lut.keys()) if lut else None)
    for r in dev_reasons:
        print(f"[gen_netlist] {r}")

    L1 = 380e-9                      # 输入对短 L
    L3 = 1.0e-6                      # PMOS cascode 长 L
    L5 = 1.0e-6                      # PMOS 负载长 L
    L7 = 1.0e-6                      # 尾源长 L

    W1 = W_from_gmid(Id, L1, gm_over_Id, muCox_n, lut=lut, device=dev_n)    # NMOS 输入对
    W3 = W_from_gmid(Id, L3, 10.0, muCox_p, lut=lut, device=dev_p)          # PMOS cascode
    W5 = W_from_gmid(Id, L5, 10.0, muCox_p, lut=lut, device=dev_p)          # PMOS 负载
    W7 = W_from_gmid(itail, L7, 10.0, muCox_n, lut=lut, device=dev_n)       # NMOS 尾源(电流镜参考)

    def nf_for(W, finger=1e-6):
        return max(1, int(round(W / finger)))

    params = {
        "VDD": vdd, "VCM": vcm, "IREF": itail, "VB2": vb2,
        "DEV_N": dev_n, "DEV_P": dev_p,
        "L1": L1, "W1": W1, "nf1": nf_for(W1),
        "L3": L3, "W3": W3, "nf3": nf_for(W3),
        "L5": L5, "W5": W5, "nf5": nf_for(W5),
        "L7": L7, "W7": W7, "nf7": nf_for(W7),
        "CL": cl,
    }
    meta = {
        "gm1": gm1, "Id": Id, "gm_over_Id": gm_over_Id, "vov1": vov1, "region1": region1,
        "dev_n": dev_n, "dev_p": dev_p,
    }
    return params, meta


def precompute_two_stage_miller_ota(spec, lut=None):
    """两级 Miller OTA(telescopic 第一级 + CS 第二级):NMOS 输入 telescopic(cascode,
    A1≈53dB 实测)+ PMOS CS 第二级 + Cc/Rz 补偿。

    关键方程(两级 Miller,与单级不同!):
      GBW = gm1/(2π·CC)              # 带宽由 Miller 补偿电容决定,不是 CL
      p2  ≈ 1/(2π·(ro8‖ro9)·(CL+Cc'))  # 第二极点(65nm IO 下 Cgs8 使教科书 gm8/CL 退化)
      PM≥60° 需 p2 ≥ 1.73·GBW
    功耗预算(总 Itail = spec 上限):IREF 5% / 第一级 ~8% / 第二级 I6 剩余。
    第一级 telescopic 增益与电流无关(~53dB,器件本征),第二级 A2=gm8·(ro8‖ro9)。
    静态匹配(两级关键):M8 栅=net_a 被 PMOS 镜钳位 → |Vov8|=|Vov5|,
      M8 饱和电流 = Id1·(W8/L8)/(W5/L5) → W8 = I6·W5·L8/(Id1·L5) 使 M8 饱和电流=I6。
    第二级用 L=380n(ro 小 → p2 高);GBW 目标受 p2 物理上限约束(~3.5-4MHz @ 200uA/CL=2p)。
    """
    vdd = spec.get("VDD", (3.3,))[0]
    vcm = spec.get("VCM", (1.2,))[0]          # telescopic NMOS 输入(案例实测 VCM=1.2)
    gbw = spec.get("GBW", (3.5e6,))[0]        # 默认 3.5MHz(两级 telescopic 物理可达区)
    cl = spec.get("CL", (2e-12,))[0]
    itotal = spec.get("Itail", (200e-6,))[0]  # 总功耗预算(IREF + 两级电流)
    vb2 = spec.get("VB2", (1.8,))[0]          # cascode 栅(telescopic 案例校准值)

    muCox_p = 62e-6
    muCox_n = 187e-6

    # 功耗分配(标"待校准"):IREF 5% / 第一级 ~8%(gm1 由 GBW·CC 定,电流可小)/ 第二级剩余
    def r5(x):
        return round(x / 5e-6) * 5e-6

    iref = max(r5(itotal * 0.05), 5e-6)
    itail1 = max(r5(itotal * 0.08), 5e-6)     # telescopic 第一级增益与电流无关,小电流即可
    i6 = max(itotal - iref - itail1, 20e-6)   # 剩余全给第二级(撑 gm8/PM)

    # 补偿电容(可 spec 覆盖):起手 CC≈1.5·CL,GBW/PM 权衡旋钮
    cc = spec.get("CC", (1.5 * cl,))[0]
    gbw_tgt = gbw * 1.05                     # 5% 裕度(ss/tt GBW 比≈0.955 实测)
    gm1 = 2 * math.pi * gbw_tgt * cc         # GBW = gm1/(2π·CC)

    Id1 = itail1 / 2.0
    gm_over_Id1 = gm1 / Id1
    if gm_over_Id1 <= 0:
        raise ValueError(f"gm/Id 非法: gm/Id1={gm_over_Id1:.2f}")

    vov1, region1 = vov_from_gmid(gm_over_Id1)

    # 器件档:按 VDD 域候选 + telescopic 第一级堆叠电压预算
    dev_n, dev_p, dev_reasons = select_devices(
        "two_stage_miller_ota", vdd, spec, vov1, vov1,
        lut_keys=list(lut.keys()) if lut else None)
    for r in dev_reasons:
        print(f"[gen_netlist] {r}")

    # 混合 L:第一级 telescopic(L1=380n, cascode/镜 1u);第二级 380n(ro 小→p2 高)
    # 镜像对(M7 尾源 / M9 第二级负载 / Mbias 参考)必须同 L=380n,否则镜像比=(W/L)比失真
    L1, L3, L5 = 380e-9, 1.0e-6, 1.0e-6
    L7, L9, Lb = 380e-9, 380e-9, 380e-9
    L8 = 380e-9

    def W_lut(lut, device, Id, L, gmid, fallback_muCox):
        """查 LUT 定 W(LUT 是 L=380n 表征 → 查表后按 L/380n 缩放);
        无 LUT 或 gmid 超范围 → 回退平方律(内部含 L 缩放)。
        id_w 单位 uA/um,数值上等于 A/m → Id/id_w 直接得米。"""
        if lut is not None:
            id_w = lookup_id_w(lut, device, gmid)
            if id_w:
                return Id / id_w * (L / 380e-9)
        return W_from_gmid(Id, L, gmid, fallback_muCox)

    # ---- 第一级 telescopic(照 telescopic_ota 案例)----
    W1 = W_lut(lut, dev_n, Id1, L1, gm_over_Id1, muCox_n)    # NMOS 输入对
    W3 = W_lut(lut, dev_n, Id1, L3, 10.0, muCox_n)           # NMOS cascode(gm/Id~10)
    W5 = W_lut(lut, dev_p, Id1, L5, 10.0, muCox_p)           # PMOS 镜(gm/Id~10)
    Wb = W_lut(lut, dev_n, iref, Lb, 10.0, muCox_n)          # 偏置参考管(同 L=380n)
    W7 = Wb * (itail1 / iref)                                # 尾源镜像比 = W 比(同 L)
    W9 = Wb * (i6 / iref)                                    # 第二级负载镜像比 = W 比(同 L)

    # ---- 第二级 ----
    # 静态匹配:M8 饱和电流 = Id1·(W8/L8)/(W5/L5) = I6 → W8 = I6·W5·L8/(Id1·L5)
    W8 = i6 * W5 * L8 / (Id1 * L5)
    # gm8 = 2·I6/|Vov8|,|Vov8|=|Vov5|≈0.2(gm/Id5=10,待校准);短沟道下偏低,仿真校准
    vov5 = 2.0 / 10.0
    gm8 = 2.0 * i6 / vov5

    # PM 预算:PM≥60° 需 p2 ≥ 1.73·GBW;p2≈1/(2π·R2·(CL+Cc')),R2=ro8‖ro9
    # ro ≈ gm_gds/(gm/Id·Id),gm_gds(380n)≈40 → 粗糙预警,不阻塞
    gm8_est = 13.0 * i6
    ro_est = 40.0 / gm8_est
    r2_est = ro_est / 2.0
    p2_est = 1.0 / (2 * math.pi * r2_est * (cl + 0.3e-12))
    gbw_max = p2_est / 1.73
    if gbw_tgt > gbw_max:
        print(f"[gen_netlist] ⚠️ GBW目标 {gbw_tgt/1e6:.2f}MHz > p2 预算上限 {gbw_max/1e6:.2f}MHz"
              f"(p2≈{p2_est/1e6:.2f}MHz @ I6={i6*1e6:.0f}uA),PM 可能不足——升 I6 或降 GBW 目标")

    def nf_for(W, finger=1e-6):
        return max(1, int(round(W / finger)))

    rz = 1.0 / gm8    # 调零电阻 ≈ 1/gm8(消 RHP 零点)

    params = {
        "VDD": vdd, "VCM": vcm, "IREF": iref, "VB2": vb2,
        "DEV_N": dev_n, "DEV_P": dev_p,
        "L1": L1, "W1": W1, "nf1": nf_for(W1),
        "L3": L3, "W3": W3, "nf3": nf_for(W3),
        "L5": L5, "W5": W5, "nf5": nf_for(W5),
        "L7": L7, "W7": W7, "nf7": nf_for(W7),
        "L8": L8, "W8": W8, "nf8": nf_for(W8),
        "L9": L9, "W9": W9, "nf9": nf_for(W9),
        "Lb": Lb, "Wb": Wb, "nfb": nf_for(Wb),
        "CC": cc, "RZ": rz, "CL": cl,
    }
    meta = {
        "gm1": gm1, "Id": Id1, "gm_over_Id": gm_over_Id1, "vov1": vov1, "region1": region1,
        "gm8": gm8, "I6": i6, "p2_est": p2_est, "gbw_max": gbw_max,
        "Itail1": itail1, "IREF": iref, "CC": cc, "RZ": rz,
        "dev_n": dev_n, "dev_p": dev_p,
    }
    return params, meta


def precompute_fully_diff_cmfb_ota(spec, lut=None):
    """全差分两级 Miller + CMFB(telescopic 第一级 + NMOS CS 第二级 + 电阻检测镜负载 CMFB)。

    与单端 two_stage 的关键差异(全差分对称):
      1) 第一级 telescopic 输出 net_ap/net_an 是 NMOS cascode 漏(低电平 ≈VB2-Vth 附近),
         第二级必须用 **NMOS CS**(栅=net_ap),不能像单端版用 PMOS CS
         (单端版 net_a 是 PMOS 镜 mirror 节点,高电平 2.4V → PMOS CS;全差分无镜,低电平 → NMOS CS)
      2) 第二级 PMOS 负载 M9p/M9n 栅接 **vcmfb**(CMFB 误差放大器输出),不是固定偏置——
         CMFB 钳输出共模到 VCM_OUT,同时保证 M8/M9 电流自洽(I8=I9 串联强制)
      3) CMFB 误差放大器用 **镜负载差分对**(wiki anti-001:diode 负载直连高阻节点会杀 DM 增益)
      4) 功耗预算多一路 CMFB 尾源(5%)+ 第二级 ×2 侧
    关键方程(对称半电路,与单端相同):
      GBW = gm1/(2π·CC) | p2 = gm8/(2π·CL) ≥ 2.2·GBW 保 PM≥60°
    功耗分配(总 Itotal=200u):IREF 5% / CMFB 5% / 第一级 20% / 第二级每侧 35%×2
    """
    vdd = spec.get("VDD", (3.3,))[0]
    vcm = spec.get("VCM", (1.2,))[0]          # NMOS 输入,高 Vcm
    vcm_out = spec.get("VCM_OUT", (vdd / 2.0,))[0]  # 输出共模参考(VDD/2)
    vcm1 = spec.get("VCM1", (2.2,))[0]        # 第一级输出共模参考(net_ap/an 钳位点)
    gbw = spec.get("GBW", (20e6,))[0]
    cl = spec.get("CL", (2e-12,))[0]
    itotal = spec.get("Itail", (200e-6,))[0]
    vb2 = spec.get("VB2", (1.8,))[0]          # cascode 栅(telescopic 案例校准值)

    muCox_p = 62e-6
    muCox_n = 187e-6

    # 功耗分配(标"待校准"):IREF 5% / IPB(pbias 链 Mpb)5% / 输出 CMFB 尾源 2.5%
    #   / 第一级 CMFB 5% / 第一级 15% / 第二级每侧剩余
    # 注:① IPB 电流源支路本身是功耗(v1 忘了计入 → Itotal 超 220u);
    #    ② 输出 CMFB 尾源 Mcm5 是独立 VDD→VSS 支路,不能靠"镜像 Mpb 不额外计"
    #       (v2~v11 都漏算 → Itotal 实际 +10uA,206 vs 200);v12 起 icmfb 独立计 2.5%
    def r5(x):
        return round(x / 5e-6) * 5e-6

    iref = max(r5(itotal * 0.05), 5e-6)
    ipb = max(r5(itotal * 0.05), 5e-6)        # pbias 参考链电流(Mpb 支路,计入 Itotal)
    icmfb = max(r5(itotal * 0.025), 5e-6)     # 输出 CMFB 尾源(独立支路,单独计电)
    icmfb1 = max(r5(itotal * 0.05), 5e-6)     # 第一级 CMFB 尾源(镜像 nbias)
    itail1 = max(r5(itotal * 0.15), 5e-6)     # telescopic 第一级(增益与电流无关)
    i6 = max((itotal - iref - ipb - icmfb - icmfb1 - itail1) / 2.0, 20e-6)  # 第二级每侧

    # 补偿电容(可 spec 覆盖):起手 CC≈0.8·CL,GBW/PM 权衡旋钮
    cc = spec.get("CC", (0.8 * cl,))[0]
    gbw_tgt = gbw * 1.05                     # 5% 裕度(ss/tt GBW 比≈0.955 实测)
    gm1 = 2 * math.pi * gbw_tgt * cc         # GBW = gm1/(2π·CC)

    Id1 = itail1 / 2.0
    gm_over_Id1 = gm1 / Id1
    if gm_over_Id1 <= 0:
        raise ValueError(f"gm/Id 非法: gm/Id1={gm_over_Id1:.2f}")

    vov1, region1 = vov_from_gmid(gm_over_Id1)

    # 器件档:按 VDD 域候选 + 全差分两级堆叠电压预算
    dev_n, dev_p, dev_reasons = select_devices(
        "fully_diff_cmfb_ota", vdd, spec, vov1, vov1,
        lut_keys=list(lut.keys()) if lut else None)
    for r in dev_reasons:
        print(f"[gen_netlist] {r}")

    # 混合 L:第一级 telescopic(L1=380n, cascode/负载 1u);第二级 380n(ro 小→p2 高)
    # 镜像对(M7 尾源 / Mbias 参考)必须同 L=380n;Mpb 参考与 M5 负载同 L=1u
    L1, L3, L5 = 380e-9, 1.0e-6, 1.0e-6
    L7, L9, Lb = 380e-9, 380e-9, 380e-9
    L8 = 380e-9
    Lpb = 1.0e-6                               # PMOS 参考 diode 管(Mcm5 同 L 镜像)
    Lcm1 = 380e-9                              # 输出 CMFB 输入对(短 L)
    Lcm3, Lcm4 = 380e-9, 380e-9               # 输出 CMFB 镜负载
    Lcm5 = 1.0e-6                              # 输出 CMFB 尾源 = 镜像 Mpb(必须同 L=1u)
    # 第一级 CMFB:NMOS 输入对 + PMOS 镜负载(NMOS 输入因 VCM1≈2.2V 偏高)
    Lc1 = 380e-9                               # 输入对
    Lc1l = 1.0e-6                              # PMOS 镜负载
    Lc1t = 380e-9                              # NMOS 尾源(镜像 Mbias,同 L=380n)

    def W_lut(lut, device, Id, L, gmid, fallback_muCox):
        """查 LUT 定 W(LUT 是 L=380n 表征 → 查表后按 L/380n 缩放);
        无 LUT 或 gmid 超范围 → 回退平方律(内部含 L 缩放)。"""
        if lut is not None:
            id_w = lookup_id_w(lut, device, gmid)
            if id_w:
                return Id / id_w * (L / 380e-9)
        return W_from_gmid(Id, L, gmid, fallback_muCox)

    # ---- 第一级 telescopic(对称)----
    W1 = W_lut(lut, dev_n, Id1, L1, gm_over_Id1, muCox_n)    # NMOS 输入对
    W3 = W_lut(lut, dev_n, Id1, L3, 10.0, muCox_n)           # NMOS cascode(gm/Id~10)
    # PMOS 负载:M5p/M5n 栅=vcmfb1(第一级 CMFB 输出),net_ap/an 由环路钳位,
    # 不靠电流镜静态匹配(v3~v7 教训:net_ap 高阻节点 ±4% 镜像失配就推轨)
    W5 = W_lut(lut, dev_p, Id1, L5, 10.0, muCox_p)
    Wb = W_lut(lut, dev_n, iref, Lb, 10.0, muCox_n)          # 偏置参考管(同 L=380n)
    W7 = Wb * (itail1 / iref)                                # 尾源镜像比 = W 比(同 L)
    # Mpb 参考(pbias 链,供输出 CMFB 尾源 Mcm5 镜像)
    Wpb = W_lut(lut, dev_p, ipb, Lpb, 10.0, muCox_p)
    Wcm5 = Wpb * (icmfb / ipb)                               # 输出 CMFB 尾源镜像 Mpb(同 L=1u, 比<1)
    # 第一级 CMFB 尾源(镜像 Mbias,同 L=380n)
    Wc1t = Wb * (icmfb1 / iref)

    # ---- 第二级(PMOS CS + NMOS 负载)----
    # net_ap 由第一级 CMFB 钳到 VCM1≈2.2V(高电平)→ 第二级 PMOS CS
    # 静态匹配:M8 栅=net_ap=VCM1 → |Vsg8| = VDD−VCM1 = 1.1V,
    #   |Vov8| = |Vsg8| − |Vth_p| = 0.527V → W8 = 2·I6·L8/(μCox_p·Vov8²)
    #   (v8 教训:vov8_est 被 clamp 到 0.15 → W8=38u → 第二级 937uA/侧,Itotal 9.7× 超)
    vov8_est = (vdd - vcm1) - 0.573                    # |Vov8|,VCM1=2.2 → 0.527V
    if vov8_est < 0.05:
        vov8_est = 0.15
    W8 = 2.0 * i6 * L8 / (muCox_p * vov8_est ** 2)           # I8 = ½μCox·W/L·Vov² = I6
    gm8 = 2.0 * i6 / vov8_est
    W9 = W_lut(lut, dev_n, i6, L9, 10.0, muCox_n)          # NMOS 负载(栅=vcmfb)

    # PM 预算:p2 = gm8/(2π·CL) ≥ 2.2·GBW(65nm IO 受 Cgs8 拖累,预警不阻塞)
    p2_est = gm8 / (2 * math.pi * cl)
    gbw_max = p2_est / 2.2
    if gbw_tgt > gbw_max:
        print(f"[gen_netlist] ⚠️ GBW目标 {gbw_tgt/1e6:.2f}MHz > p2 预算上限 {gbw_max/1e6:.2f}MHz"
              f"(p2≈{p2_est/1e6:.2f}MHz @ I6={i6*1e6:.0f}uA),PM 可能不足——升 I6 或降 GBW 目标")

    # ---- 输出 CMFB 误差放大器(镜负载差分对)----
    # 尾源 icmfb(镜像 Mpb)分两管:Mcmp/Mcmn 每边 icmfb/2;Mcm3/Mcm4 镜负载每边 icmfb/2
    i_cm = icmfb / 2.0
    Wcm1 = W_lut(lut, dev_p, i_cm, Lcm1, 10.0, muCox_p)      # PMOS 输入对
    Wcm3 = W_lut(lut, dev_n, i_cm, Lcm3, 10.0, muCox_n)      # NMOS diode 负载
    Wcm4 = Wcm3                                             # NMOS 镜输出

    # ---- 第一级 CMFB 误差放大器(NMOS 输入 + PMOS 镜负载)----
    i_c1 = icmfb1 / 2.0
    Wc1 = W_lut(lut, dev_n, i_c1, Lc1, 10.0, muCox_n)        # NMOS 输入对
    Wc1l = W_lut(lut, dev_p, i_c1, Lc1l, 10.0, muCox_p)      # PMOS 镜负载(diode+mirror 同宽)

    def nf_for(W, finger=1e-6):
        return max(1, int(round(W / finger)))

    rz = 1.0 / gm8    # 调零电阻 ≈ 1/gm8(消 RHP 零点)

    params = {
        "VDD": vdd, "VCM": vcm, "VCM_OUT": vcm_out, "VCM1": vcm1,
        "IREF": iref, "Ipb": ipb, "VB2": vb2,
        "DEV_N": dev_n, "DEV_P": dev_p,
        "L1": L1, "W1": W1, "nf1": nf_for(W1),
        "L3": L3, "W3": W3, "nf3": nf_for(W3),
        "L5": L5, "W5": W5, "nf5": nf_for(W5),
        "L7": L7, "W7": W7, "nf7": nf_for(W7),
        "L8": L8, "W8": W8, "nf8": nf_for(W8),
        "L9": L9, "W9": W9, "nf9": nf_for(W9),
        "Lb": Lb, "Wb": Wb, "nfb": nf_for(Wb),
        "Lpb": Lpb, "Wpb": Wpb, "nfpb": nf_for(Wpb),
        "Lcm1": Lcm1, "Wcm1": Wcm1, "nfcm1": nf_for(Wcm1),
        "Lcm3": Lcm3, "Wcm3": Wcm3, "nfcm3": nf_for(Wcm3),
        "Lcm4": Lcm4, "Wcm4": Wcm4, "nfcm4": nf_for(Wcm4),
        "Lcm5": Lcm5, "Wcm5": Wcm5, "nfcm5": nf_for(Wcm5),
        "Lc1": Lc1, "Wc1": Wc1, "nfc1": nf_for(Wc1),
        "Lc1l": Lc1l, "Wc1l": Wc1l, "nfc1l": nf_for(Wc1l),
        "Lc1t": Lc1t, "Wc1t": Wc1t, "nfc1t": nf_for(Wc1t),
        "CC": cc, "RZ": rz, "RS": 200e3, "RS1": 3e6, "CL": cl,
    }
    meta = {
        "gm1": gm1, "Id": Id1, "gm_over_Id": gm_over_Id1, "vov1": vov1, "region1": region1,
        "gm8": gm8, "I6": i6, "p2_est": p2_est, "gbw_max": gbw_max,
        "Itail1": itail1, "IREF": iref, "IPB": ipb, "ICMFB": icmfb, "ICMFB1": icmfb1,
        "CC": cc, "RZ": rz,
        "dev_n": dev_n, "dev_p": dev_p,
    }
    return params, meta


# 拓扑理论极限(近似,待校准——不同工艺/L 组合会变;用于预计算阶段提前暴露不可达)
THEORETICAL_LIMITS = {
    "5t_ota": {"av_db": 35, "note": "单级 5T,Av≈gm/gds 本征增益;实测校准 2026-08:W1=900u 极限仍仅 35.7dB,40dB 不可达"},
    "current_mirror_load_ota": {"av_db": 40, "note": "高阻电流镜负载,仍受 ro 并联限制"},
    "telescopic_ota": {"av_db": 53, "note": "cascode 输出;实测校准 2026-08:VB2 到位后 52.8dB,60dB 需两级/增益自举"},
    "folded_cascode_ota": {"av_db": 31, "note": "折叠节点=输出,输入管 ro1 直接并联(未被 cascode 放大),增益≈gm1·ro1=输入管本征增益~31dB(NMOS L=380n);理论推导待仿真验证,40dB 需换 telescopic/两级/增益自举"},
    "two_stage_miller_ota": {"av_db": 80, "note": "两级增益相乘"},
    "rail_to_rail_ota": {"av_db": 60, "note": "双差分对并联,增益同单级"},
    "fully_diff_cmfb_ota": {"av_db": 60, "note": "全差分,增益同单级/两级"},
    "gain_boosted_ota": {"av_db": 80, "note": "增益自举,极限受辅助环路限制"},
}


# 目标增益 vs 该拓扑理论上限 → 警告列表(超限建议换结构)
def theoretical_limit_check(topo, spec):
    lim = THEORETICAL_LIMITS.get(topo)
    if not lim:
        return []
    av_target = spec.get("Av", (None,))[0]
    if av_target is None:
        return []
    warnings = []
    margin = 5.0  # dB 设计裕度
    if av_target > lim["av_db"]:
        warnings.append(
            f"目标 Av={av_target:.0f}dB 超过 {topo} 理论上限 ~{lim['av_db']}dB"
            f"({lim['note']}),建议换更高增益结构(cascode/两级/增益自举)")
    elif av_target > lim["av_db"] - margin:
        warnings.append(
            f"目标 Av={av_target:.0f}dB 接近 {topo} 理论上限 ~{lim['av_db']}dB,"
            f"需 L 取大/低 gm/Id 硬挤,裕度小,做好多轮迭代准备")
    return warnings


# 拓扑 -> 预计算函数 分派表(必须在所有 precompute_xxx 之后)
PRECOMPUTE = {
    "5t_ota": precompute_5t_ota,
    "current_mirror_load_ota": precompute_current_mirror_load_ota,
    "telescopic_ota": precompute_telescopic_ota,
    "folded_cascode_ota": precompute_folded_cascode_ota,
    "two_stage_miller_ota": precompute_two_stage_miller_ota,
    "fully_diff_cmfb_ota": precompute_fully_diff_cmfb_ota,
}


def fill_template(template_path, params):
    """读模板,替换 parameters 行;DEV_N/DEV_P 额外做模型名替换(器件档切换)。"""
    with open(template_path, encoding="utf-8") as f:
        tpl = f.read()

    def fmt(name, val):
        if isinstance(val, float):
            return si(val)
        return str(val)

    lines = []
    for line in tpl.splitlines():
        m = re.match(r"^parameters\s+(.*)$", line)
        if m:
            body = m.group(1)
            # 逐个替换 parameters 里的 token(key 与模板大小写一致)
            for k, v in params.items():
                if not isinstance(v, (int, float)):
                    continue
                body = re.sub(rf"\b{re.escape(k)}\s*=\s*[^\s]+", f"{k}={fmt(k, v)}", body)
            lines.append("parameters " + body)
        else:
            lines.append(line)
    text = "\n".join(lines)
    # 器件档切换:DEV_N/DEV_P 是模型名 token(非数值,不进 parameters 行),
    # 这里做全文模型名替换(模板默认 nch_33/pch_33;默认档时替换为 no-op)。
    dev_n = params.get("DEV_N")
    dev_p = params.get("DEV_P")
    if dev_n and dev_n != "nch_33":
        text = re.sub(r"\bnch_33\b", dev_n, text)
    if dev_p and dev_p != "pch_33":
        text = re.sub(r"\bpch_33\b", dev_p, text)
    return text


def main():
    # Windows 控制台默认 GBK,先切 UTF-8 再打印(emoji/中文不报 UnicodeEncodeError)
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    ap = argparse.ArgumentParser(description="OTA 网表生成器")
    ap.add_argument("topology", help="结构名,如 5t_ota")
    ap.add_argument("--spec", default="", help='指标串,如 "GBW=100MHz,CL=2p,Itail=100u,VDD=3.3"')
    ap.add_argument("--json", default="", help="指标 json 文件(可选)")
    ap.add_argument("--gmid-lut", default="", help="Phase 0 gm/Id LUT JSON,逗号分隔多个(gmid_char.py parse 产物),查表定 W")
    ap.add_argument("-o", "--out", default="", help="输出 .scs 路径")
    args = ap.parse_args()

    topo = args.topology.replace(".yml", "").replace("/", "_")

    # 配方文件(验证存在)
    recipe_path = os.path.join(TOPOLOGIES, f"{topo}.yml")
    if not os.path.exists(recipe_path):
        print(f"[gen_netlist] 配方不存在: {recipe_path}")
        print(f"[gen_netlist] 可用配方: {sorted(f[:-4] for f in os.listdir(TOPOLOGIES) if f.endswith('.yml') and not f.startswith('_'))}")
        sys.exit(1)

    # 指标
    spec = {}
    if args.json:
        with open(args.json, encoding="utf-8") as f:
            spec = {k: (v,) for k, v in json.load(f).items()}
    if args.spec:
        spec.update(parse_spec(args.spec))

    # 预计算(按拓扑分派)
    precompute_fn = PRECOMPUTE.get(topo)
    if precompute_fn is None:
        print(f"[gen_netlist] 拓扑 {topo} 无预计算函数(PRECOMPUTE 未注册)")
        sys.exit(1)
    lut = load_luts(args.gmid_lut) if args.gmid_lut else None
    if lut:
        print(f"[gen_netlist] 使用 Phase 0 LUT: {sorted(lut.keys())} (来自 {args.gmid_lut})")
    else:
        print("[gen_netlist] 未提供 --gmid-lut,用平方律近似定 W(建议先跑 gmid_char.py 生成 LUT)")
    params, meta = precompute_fn(spec, lut)

    # 填模板
    template_path = os.path.join(TEMPLATES, f"{topo}.scs")
    if not os.path.exists(template_path):
        print(f"[gen_netlist] 模板不存在: {template_path}")
        sys.exit(1)
    netlist = fill_template(template_path, params)

    out = args.out or f"{topo}_generated.scs"
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        f.write(netlist)

    print(f"[gen_netlist] 已生成: {out}")
    print(f"[gen_netlist] 预计算(系数待校准):")
    print(f"  gm1      = {si(meta['gm1'])}S")
    print(f"  Id/边    = {si(meta['Id'])}A")
    print(f"  gm/Id    = {meta['gm_over_Id']:.2f}  (区域: {meta['region1']})")
    print(f"  Vov1     = {si(meta['vov1'])}V")
    # 模板参数(W/L/nf/VBIAS 等,按 token 名排序打印)
    for k in sorted(params):
        if k in ("VDD", "VCM", "CL"):
            continue
        if not isinstance(params[k], (int, float)):
            continue  # DEV_N/DEV_P 等字符串 token 不打印尺寸
        print(f"  {k:<8} = {si(params[k])}")

    # gm/Id 区域预警
    gmid = meta['gm_over_Id']
    region = meta['region1']
    if region == "weak":
        print(f"  ⚠️  gm/Id={gmid:.1f} 落在弱反型区(>15):W 指数放大、线性度差、寄生大。")
        print(f"      建议:降 GBW / 降 CL / 升 Itail,把 gm/Id 拉回 ≤15 强反型区。")
    else:
        print(f"  ✓ gm/Id={gmid:.1f} 在强反型区(≤15,平方律 Vov=2/(gm/Id) 有效):W 合理。")

    # 理论极限预判(circuit-principle 框架:先算上限,超限提前换结构)
    for warn in theoretical_limit_check(topo, spec):
        print(f"  {warn}")


if __name__ == "__main__":
    main()
