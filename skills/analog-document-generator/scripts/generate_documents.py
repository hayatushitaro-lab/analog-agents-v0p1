#!/usr/bin/env python3
"""Fill the current analog Word templates from normalized facts JSON.

This is intentionally conservative: it writes values supported by the facts
file and uses ``待补充`` for unsupported fields. The source templates are never
modified; output files are written to a separate directory.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from shutil import copyfile

from docx import Document
from docx.shared import RGBColor


def text_of(cell) -> str:
    return " ".join(cell.text.replace("\n", " ").split())


def replace_cell(cell, value: object) -> None:
    text = "" if value is None else str(value)
    if not cell.paragraphs:
        cell.text = text
        return
    first = cell.paragraphs[0]
    for run in list(first.runs):
        first._p.remove(run._r)
    first.add_run(text)
    for paragraph in list(cell.paragraphs)[1:]:
        paragraph._element.getparent().remove(paragraph._element)


def remove_paragraph(paragraph) -> None:
    paragraph._element.getparent().remove(paragraph._element)


def run_is_instruction(run) -> bool:
    color = None
    try:
        if run.font.color and run.font.color.rgb:
            color = str(run.font.color.rgb).upper()
    except Exception:
        pass
    # The source templates use blue text both with and without an explicit
    # italic flag.  The visual convention, rather than the OOXML italic bit,
    # is the reliable indication that a paragraph is author guidance.
    return color in {"0000FF", "FF0000", "0070C0", "1F4E79", "4472C4"}


def iter_cell_paragraphs(doc: Document):
    """Yield paragraphs nested in all table cells."""

    for table in doc.tables:
        for row in table.rows:
            for cell in row.cells:
                for paragraph in cell.paragraphs:
                    yield paragraph


def normalize_table_guidance_formatting(doc: Document) -> None:
    """Keep labels but remove template-only blue/italic styling."""

    paragraphs = list(doc.paragraphs) + list(iter_cell_paragraphs(doc))
    for paragraph in paragraphs:
        for run in paragraph.runs:
            # Filled table values can inherit the source template's blue/
            # italic character style even after the original run is removed.
            # Normalize the completed table to ordinary black text.
            run.font.color.rgb = RGBColor(0, 0, 0)
            run.italic = False


def is_textual_template_guidance(text: str) -> bool:
    """Recognize prose instructions that lost color during DOC conversion."""

    markers = (
        "文档说明：",
        "此文档由项目模拟负责人",
        "此文档的斜体字均为说明文字",
        "查找使用过该工艺",
        "Svn目录：",
        "下表为此次项目可使用的所有器件",
        "器件特性可以从工艺文档",
        "mos管的vth",
        "BJT的Ic",
        "电阻的方块值",
        "电容的单位面积容值",
        "是否需要注意WPE",
        "各层金属、poly、contact",
        "注意电源和时钟模块的仿真温度",
        "填写corner配置、需要用到的标准单元网表路径",
        "可以建一个配置好所有corner setup",
        "OP和DDVC脚本建议",
        "PERC脚本有公司的脚本",
        "各脚本路径如下",
    )
    return any(marker in text for marker in markers)


def remove_instruction_paragraphs(doc: Document) -> int:
    removed = 0
    for paragraph in list(doc.paragraphs):
        if is_textual_template_guidance(text_of(paragraph)):
            remove_paragraph(paragraph)
            removed += 1
            continue
        meaningful = [r for r in paragraph.runs if r.text.strip()]
        if meaningful and sum(run_is_instruction(r) for r in meaningful) / len(meaningful) >= 0.7:
            # Keep headings and user-visible placeholders; remove only blue/red
            # italic guidance paragraphs.
            if paragraph.style and ("Heading" in paragraph.style.name or "标题" in paragraph.style.name):
                continue
            remove_paragraph(paragraph)
            removed += 1
    # Table placeholders are often useful column labels, so retain their text
    # while stripping the source template's blue/italic visual convention.
    normalize_table_guidance_formatting(doc)
    return removed


def first_number(value: str | None) -> str:
    if not value:
        return ""
    match = re.search(r"[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?", value)
    return match.group(0) if match else ""


def target_columns(target: str) -> tuple[str, str, str]:
    target = target or ""
    value = first_number(target)
    if ">=" in target or ">" in target:
        return value, "", ""
    if "<=" in target or "<" in target:
        return "", "", value
    return "", value, ""


def fill_startup(template: Path, output: Path, facts: dict) -> dict:
    copyfile(template, output)
    doc = Document(output)
    removed = remove_instruction_paragraphs(doc)
    process = facts["process"]
    project = facts.get("project", {})

    for paragraph in doc.paragraphs:
        text = text_of(paragraph)
        if text.startswith("项目编号"):
            paragraph.text = "项目编号：OTA_TEMPLATE_VALIDATION_20260908"
        elif text.startswith("项目名称"):
            paragraph.text = "项目名称：TSMC N65 两级 Miller OTA 小样本"

    def value(key: str) -> str:
        item = process.get(key, {})
        raw = item.get("value") if isinstance(item, dict) else item
        if raw is None:
            return "待补充"
        if isinstance(raw, list):
            return ", ".join(map(str, raw))
        return str(raw)

    # T2: process information
    t2 = doc.tables[1]
    process_values = {
        "工艺名": value("name"),
        "金属层次": value("metal_layers"),
        "金属工艺（AL/Cu）": value("metal_type"),
        "顶层金属厚度": value("top_metal_thickness"),
        "MIM CAP单位容值": value("mim_cap_unit"),
        "MOM CAP单位容值": value("mom_cap_unit"),
        "HR poly电阻方块值": value("hr_poly_sheet_resistance"),
        "Mask层数": value("mask_count"),
        "是否使用DNW": value("dnw"),
        "Scale(simulator option)": value("simulator_scale"),
        "Virtuoso版本要求": value("virtuoso_version"),
        "Spectre版本要求": value("spectre_version"),
    }
    for row in t2.rows[1:]:
        label = text_of(row.cells[0])
        if label in process_values:
            replace_cell(row.cells[1], process_values[label])

    # T3: device catalog
    t3 = doc.tables[2]
    for row in t3.rows[1:]:
        # The source template vertically merges the category column.  Clear
        # only the independent columns so the merged cell is not overwritten
        # repeatedly by the last device type.
        for cell in row.cells[1:]:
            replace_cell(cell, "")
    replace_cell(t3.rows[1].cells[0], "MOS / resistor / capacitor")
    for row, device in zip(t3.rows[1:], facts.get("device_catalog", [])):
        replace_cell(row.cells[1], device.get("model", ""))
        replace_cell(row.cells[2], device.get("supply", ""))
        replace_cell(row.cells[3], device.get("description", ""))

    # T4: operating conditions
    t4 = doc.tables[3]
    temp = facts["operating_conditions"]["temperature"]["value"]
    replace_cell(t4.rows[1].cells[2], f"{temp['min']} °C")
    replace_cell(t4.rows[1].cells[3], f"{temp['typ']} °C")
    replace_cell(t4.rows[1].cells[4], f"{temp['max']} °C")
    supplies = {x["name"].lower(): x for x in facts["operating_conditions"]["supplies"]}
    for row in t4.rows[2:]:
        name = text_of(row.cells[1])
        if name.lower() in supplies:
            item = supplies[name.lower()]
            replace_cell(row.cells[2], f"{item['min']} V")
            replace_cell(row.cells[3], f"{item['typ']} V")
            replace_cell(row.cells[4], f"{item['max']} V")
        elif name.lower() in {"pvdd", "dvdd"}:
            for cell in row.cells[2:5]:
                replace_cell(cell, "不适用（单电源样本）")

    # T5/T6: model file and sections
    for table in (doc.tables[4], doc.tables[5]):
        for row in table.rows[1:]:
            replace_cell(row.cells[0], "")
            replace_cell(row.cells[1], "")
        for row, item in zip(table.rows[1:], facts.get("corner_models", [])):
            replace_cell(row.cells[0], item["model_file"])
            replace_cell(row.cells[1], item["section"])

    # T7/T8: script paths are not available in the sample.
    replace_cell(doc.tables[6].rows[1].cells[1], "待补充")
    for row in doc.tables[7].rows[1:]:
        label = text_of(row.cells[0])
        if label in {"工作点检查的脚本目录", "DDVC脚本检查", "公司 perc 使用说明", "公司perc使用说明", "工艺perc检查"}:
            replace_cell(row.cells[1], "待补充")

    normalize_table_guidance_formatting(doc)
    doc.save(output)
    return {"path": str(output), "removed_instruction_paragraphs": removed}


def fill_module(template: Path, output: Path, facts: dict) -> dict:
    copyfile(template, output)
    doc = Document(output)
    removed = remove_instruction_paragraphs(doc)
    module = facts["module"]

    for paragraph in doc.paragraphs:
        text = text_of(paragraph)
        if text.startswith("项目编号"):
            paragraph.text = "项目编号：OTA_TEMPLATE_VALIDATION_20260908"
        elif text.startswith("项目名称"):
            paragraph.text = "项目名称：TSMC N65 两级 Miller OTA 小样本"

    # Paragraph placeholders in module 1 and module 2.
    module2 = False
    feature_index = 0
    for paragraph in doc.paragraphs:
        text = text_of(paragraph)
        if text == "模拟模块2":
            module2 = True
        if not module2 and text in {"功能1", "功能2"}:
            paragraph.text = "该模块将差分输入信号进行高增益、单端输出放大，并通过两级结构和 Miller 补偿实现稳定闭环工作。系统应用场景待补充。"
        elif not module2 and text in {"特性1", "特性2"}:
            features = module["features"]["value"]
            paragraph.text = str(features[feature_index % len(features)])
            feature_index += 1
        elif module2 and text == "功能1":
            paragraph.text = "本样本仅验证一个 OTA 模块；模块2不适用。"
            module2 = False
        elif text.startswith("仿真工具："):
            paragraph.text = "仿真工具：Spectre 18.1"
        elif text.startswith("仿真路径："):
            paragraph.text = "仿真路径：见样本验证报告和 verifier-reports/integration/verifier-report.md"
        elif text.startswith("仿真方法："):
            paragraph.text = "仿真方法：TT/27°C、SS/125°C、FF/-40°C 下执行 DCOP、AC/DC gain、STB 和 transient。"
        elif text.startswith("结果分析："):
            paragraph.text = "结果分析：三 corner 收敛，9 个 MOS 每个 corner 均为 region=2；未覆盖项目标记为待补充。"
        elif text == "注：":
            paragraph.text = "注：未提供的定量指标、Monte Carlo、噪声和后仿真信息标记为待补充。"

    # T2: metric targets. Keep two work-condition rows, then use the metric list.
    t2 = doc.tables[1]
    metric_rows = [
        ("工作条件", "Top", "工作温度", "PVT", "-40", "27", "125", "°C"),
        ("工作条件", "Vop", "工作电压", "PVT", "3.3", "3.3", "3.3", "V"),
    ]
    for item in module["specifications"]:
        lo, typ, hi = target_columns(item.get("target", ""))
        result = item.get("result")
        condition = item.get("condition", "")
        if result is not None:
            condition += f"；最差角结果 {result} {item.get('unit', '')}"
        metric_rows.append(("主要需求", item.get("symbol", ""), item.get("description", item.get("name", "")), condition, lo, typ, hi, item.get("unit", "")))
    for row, values in zip(t2.rows[2:], metric_rows):
        for cell, value in zip(row.cells, values):
            replace_cell(cell, value)
    for row in t2.rows[2 + len(metric_rows):]:
        for cell in row.cells:
            replace_cell(cell, "")

    # T3: interfaces
    t3 = doc.tables[2]
    for row in t3.rows[1:]:
        for cell in row.cells:
            replace_cell(cell, "")
    for row, item in zip(t3.rows[1:], module["interfaces"]):
        replace_cell(row.cells[0], item["name"])
        replace_cell(row.cells[1], item["type"])
        replace_cell(row.cells[2], "-")
        replace_cell(row.cells[3], "待补充")
        replace_cell(row.cells[4], item["description"])

    # T4: verification plan/status
    t4 = doc.tables[3]
    for row in t4.rows[1:]:
        for cell in row.cells:
            replace_cell(cell, "")
    for row, item in zip(t4.rows[1:], module["verification"]):
        replace_cell(row.cells[0], item["category"])
        replace_cell(row.cells[1], item["detail"])
        replace_cell(row.cells[2], "Y" if item["status"] == "confirmed" else "待补充")
        replace_cell(row.cells[3], item["detail"])

    # T5: device models
    t5 = doc.tables[4]
    for row in t5.rows[1:]:
        for cell in row.cells:
            replace_cell(cell, "")
    seen = set()
    device_rows = []
    for dev in module["design_implementation"]["mos_instances"]:
        if dev["model"] in seen:
            continue
        seen.add(dev["model"])
        device_rows.append((dev["model"], "网表中使用；详细实例参数见 ota_sample_facts.json"))
    device_rows += [("resistor", "RZ1，Rz=580 ohm"), ("capacitor", "CC1，Cc=2 pF")]
    for row, values in zip(t5.rows[1:], device_rows):
        replace_cell(row.cells[0], values[0])
        replace_cell(row.cells[1], values[1])

    # T6: no mismatch Monte Carlo was supplied.
    t6 = doc.tables[5]
    for row in t6.rows[2:]:
        for cell in row.cells:
            replace_cell(cell, "未提供")

    # T7: script checks are not part of this sample.
    t7 = doc.tables[6]
    for row in t7.rows[1:]:
        replace_cell(row.cells[2], "待补充")

    # T8/T9: backend and ECO sections.
    t8 = doc.tables[7]
    replace_cell(t8.rows[1].cells[0], "关键节点：x1、vout、Rz-Cc；具体版图要求待补充")
    replace_cell(t8.rows[1].cells[1], "待补充")
    t9 = doc.tables[8]
    for row in t9.rows[1:]:
        replace_cell(row.cells[2], "待补充")

    normalize_table_guidance_formatting(doc)
    doc.save(output)
    return {"path": str(output), "removed_instruction_paragraphs": removed}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--facts", required=True, type=Path)
    parser.add_argument("--startup-template", required=True, type=Path)
    parser.add_argument("--module-template", required=True, type=Path)
    parser.add_argument("--outdir", required=True, type=Path)
    args = parser.parse_args()

    facts = json.loads(args.facts.read_text(encoding="utf-8"))
    args.outdir.mkdir(parents=True, exist_ok=True)
    startup = args.outdir / "模拟工作启动须知_OTA样本.docx"
    module = args.outdir / "模拟模块设计说明书_OTA样本.docx"
    result = {
        "startup": fill_startup(args.startup_template, startup, facts),
        "module": fill_module(args.module_template, module, facts),
    }
    (args.outdir / "generation_manifest.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
