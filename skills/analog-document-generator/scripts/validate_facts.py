#!/usr/bin/env python3
"""Validate normalized analog-document facts before Word generation."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def fail(errors: list[str], message: str) -> None:
    errors.append(message)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("facts", type=Path)
    parser.add_argument("--json-report", type=Path)
    args = parser.parse_args()

    data = json.loads(args.facts.read_text(encoding="utf-8"))
    errors: list[str] = []
    warnings: list[str] = []

    netlist = data.get("netlist_summary", {})
    devices = netlist.get("devices", [])
    pins = netlist.get("pins", [])
    if not netlist.get("subckt"):
        fail(errors, "netlist_summary.subckt is missing")
    if not pins:
        fail(errors, "netlist_summary.pins is empty")
    if not devices:
        fail(errors, "netlist_summary.devices is empty")

    impl = data.get("module", {}).get("design_implementation", {})
    count = impl.get("device_count", {})
    if count.get("value") != len(devices):
        fail(errors, f"device_count.value={count.get('value')} does not match parsed device count={len(devices)}")
    pin_count = impl.get("subckt_pin_count", {})
    if pin_count and pin_count.get("value") != len(pins):
        fail(errors, f"subckt_pin_count.value={pin_count.get('value')} does not match parsed pin count={len(pins)}")

    corners = data.get("simulation_corner_results", [])
    if corners and len(corners) < 1:
        fail(errors, "simulation_corner_results is present but empty")
    if not corners:
        warnings.append("No parsed simulation corner results; performance fields should remain required_input.")

    module = data.get("module", {})
    for key in ("name", "function", "features", "interfaces", "specifications"):
        if key not in module:
            fail(errors, f"module.{key} is missing")

    for metric in module.get("specifications", []):
        if metric.get("result") is not None and metric.get("result_status") not in {"confirmed", "confirmed_from_previous_run", "inferred"}:
            fail(errors, f"metric {metric.get('name')} has a result but status={metric.get('result_status')}")
        if metric.get("result") is None and metric.get("result_status") not in {"required_input", "not_applicable"}:
            warnings.append(f"metric {metric.get('name')} has no result but status={metric.get('result_status')}")

    pdk = data.get("process", {})
    for key in ("pdk_include", "model_sections"):
        if key in pdk and pdk[key].get("status") not in {"confirmed", "confirmed_from_previous_run", "inferred", "required_input"}:
            fail(errors, f"process.{key} has an invalid evidence status")

    report = {"facts": str(args.facts), "ok": not errors, "errors": errors, "warnings": warnings}
    if args.json_report:
        args.json_report.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    if errors:
        print("FACTS INVALID")
        for item in errors:
            print(f"- {item}")
        for item in warnings:
            print(f"WARNING: {item}")
        return 1

    print("FACTS VALID")
    for item in warnings:
        print(f"WARNING: {item}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
