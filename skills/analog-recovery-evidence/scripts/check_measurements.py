"""Electrical evidence gate for typed raw measurements.

The checker consumes a small JSON *measurement packet*.  It deliberately checks
the source sample from a text PSF export before accepting a user supplied unit;
``I(VDD:p)`` is therefore an ampere sample even when a report calls it power.
Power is accepted only when a voltage and a current are multiplied in the
declared formula.  The checker is a deterministic contract check, not a SPICE
parser, a circuit-role inference engine, or a proof that a simulator log is
complete.  Independent review is still required for source authenticity,
device connectivity, and the physical sign convention.

Minimal packet shape (version 0.1)::

    {
      "dut": {"expected_count": 1, "roots": ["dut"]},
      "interface": {"expected": ["vdd"], "observed": ["vdd"]},
      "ports": [{"name": "vdd", "role": "supply", "state": "driven",
                 "role_basis": "source evidence", "driver":
                 {"kind": "finite_voltage", "source": "vdd source"}}],
      "supply_conditions": [{"id": "nominal", "claim": "nominal",
          "voltage": 1.2,
          "source": {"kind": "schematic", "ref": "input:VDD"}}],
      "raw_samples": [{"id": "v", "signal": "V(vdd)",
          "psf_sample": "\"V(vdd)\" \"V\" 1.2",
          "source": {"format": "spectre_psf_text", "ref": "run:dc:1"}}],
      "measurements": [{"id": "vdd_v", "quantity": "voltage", "unit": "V",
          "formula": {"op": "identity", "input": "v"},
          "condition": "nominal", "claim": "diagnostic"}],
      "runs": [{"id": "run", "status": "valid",
          "claim_scope": "operating_point",
          "raw_log": "completed without warnings"}]
    }

In production mode each raw sample is read from ``source.path`` with a matching
``source.sha256``; each run log is read from ``log_path`` with its matching
``sha256``.  A production run additionally has to contain the Spectre simulator
identity, execution markers, and its terminal completion summary.  Inline
``psf_sample``/``raw_log`` text is accepted only by the explicit ``--synthetic``
mode for isolated fixtures.

Use ``python check_measurements.py --example`` to print a self-contained
diagnostic-only packet skeleton.  It is a contract example, not a product
voltage or a bandgap design assumption.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
from pathlib import Path
from typing import Any


_RAW_RE = re.compile(
    r'"(?P<signal>[^"]+)"\s+"(?P<kind>[A-Za-z]+)"\s+'
    r"(?P<value>[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?)"
)
_RAW_KINDS = {"V": ("V", {"V": 1}), "I": ("A", {"A": 1}), "A": ("A", {"A": 1})}
_QUANTITY_DIMS = {"voltage": {"V": 1}, "current": {"A": 1}, "power": {"V": 1, "A": 1}}
_QUANTITY_UNITS = {"voltage": "V", "current": "A", "power": "W"}
_ACCEPTED_SOURCE_FORMATS = {"spectre_psf_text", "spectre_psf", "psf_text", "raw_type_sample"}
_NOMINAL_SOURCES = {"spec", "datasheet", "schematic", "measured", "user_spec"}
_DRIVEN_STATES = {"driven"}
_IDEAL_KINDS = {"ideal", "ideal_voltage", "ideal_current", "forced", "force"}
_UNKNOWN_ROLES = {"unknown", "unresolved", "uncertain", "bidirectional", "output"}
_UNCONFIRMED_ROLES = {"unknown", "unresolved", "uncertain"}
_LOAD_KINDS = {"load", "finite_load", "finite_impedance", "passive_load"}

_SPECTRE_BANNER_RE = re.compile(r"^\s*Spectre\s+\(R\)\s+Circuit\s+Simulator\b", re.I)
_SPECTRE_VERSION_RE = re.compile(r"^\s*Version\s+\S+", re.I)
_SPECTRE_SIMULATING_RE = re.compile(r"^\s*Simulating\s+[`']", re.I)
_SPECTRE_COMMAND_RE = re.compile(r"^\s*Command\s+line:\s*$", re.I)
_SPECTRE_SUMMARY_RE = re.compile(
    r"^\s*spectre\s+completes?\s+with\s+"
    r"(?P<errors>\d+)\s+errors?\s*,\s*"
    r"(?P<warnings>\d+)\s+warnings?\s*,\s*(?:and\s+)?"
    r"(?P<notices>\d+)\s+notices?\s*\.?\s*$",
    re.I,
)
_SPECTRE_FATAL_RE = re.compile(
    r"\bspectre\s+terminated\s+prematurely\b|\bfatal\s+error\b",
    re.I,
)


def _text(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def example_packet() -> dict[str, Any]:
    """Return a minimal diagnostic packet suitable for ``--example``."""
    return {
        "version": "0.1",
        "dut": {"expected_count": 1, "roots": ["DUT"]},
        "interface": {"expected": ["vdd"], "observed": ["vdd"]},
        "ports": [{
            "name": "vdd",
            "role": "supply",
            "state": "driven",
            "role_basis": "replace with source evidence reference",
            "driver": {"kind": "finite_voltage", "source": "replace with fixture source"},
        }],
        "supply_conditions": [{
            "id": "diagnostic_condition",
            "claim": "diagnostic",
            "voltage": 1.0,
            "source": {"kind": "user", "ref": "replace with condition source"},
        }],
        "raw_samples": [{
            "id": "raw_vdd",
            "signal": "V(vdd)",
            "psf_sample": '\"V(vdd)\" \"V\" 1.0',
            "source": {"format": "spectre_psf_text", "ref": "replace with PSF location"},
        }],
        "measurements": [{
            "id": "vdd_voltage",
            "quantity": "voltage",
            "unit": "V",
            "formula": {"op": "identity", "input": "raw_vdd"},
            "condition": "diagnostic_condition",
            "claim": "diagnostic",
        }],
        "runs": [{
            "id": "run",
            "status": "valid",
            "claim_scope": "operating_point",
            "raw_log": "replace with complete raw simulator log text",
        }],
    }


def _error(errors: list[str], message: str) -> None:
    errors.append(message)


def _dim_equal(a: dict[str, int], b: dict[str, int]) -> bool:
    return {k: v for k, v in a.items() if v} == {k: v for k, v in b.items() if v}


def _add_dims(a: dict[str, int], b: dict[str, int], sign: int = 1) -> dict[str, int]:
    out = dict(a)
    for key, value in b.items():
        out[key] = out.get(key, 0) + sign * value
        if not out[key]:
            del out[key]
    return out


def _unit_dims(unit: Any) -> dict[str, int] | None:
    """Return dimensions while tolerating ordinary SI prefixes."""
    if not _text(unit):
        return None
    normalized = unit.strip()
    if normalized in {"V", "volt", "volts"}:
        return {"V": 1}
    if normalized in {"A", "amp", "amps"}:
        return {"A": 1}
    if normalized in {"W", "watt", "watts"}:
        return {"V": 1, "A": 1}
    match = re.fullmatch(r"(?:[fpnumkMGT])?(V|A|W)", normalized)
    if match:
        base = match.group(1)
        return {"V": 1} if base == "V" else {"A": 1} if base == "A" else {"V": 1, "A": 1}
    return None


def _parse_raw_sample(sample: dict[str, Any], errors: list[str]) -> dict[str, Any] | None:
    sid = sample.get("id", "<unnamed>")
    source = sample.get("source")
    if not isinstance(source, dict) or not _text(source.get("ref")):
        _error(errors, f"raw sample {sid} lacks source ref")
    if not isinstance(source, dict) or source.get("format") not in _ACCEPTED_SOURCE_FORMATS:
        _error(errors, f"raw sample {sid} lacks inspectable PSF source format")
    raw_line = sample.get("psf_sample") or sample.get("raw_psf_sample")
    if not _text(raw_line):
        _error(errors, f"raw sample {sid} lacks psf_sample type evidence")
        return None
    match = _RAW_RE.search(raw_line)
    if not match:
        _error(errors, f"raw sample {sid} has no parseable signal/type/value sample")
        return None
    kind = match.group("kind").upper()
    if kind not in _RAW_KINDS:
        _error(errors, f"raw sample {sid} uses unsupported PSF type {kind}")
        return None
    raw_signal = match.group("signal")
    declared_signal = sample.get("signal")
    if _text(declared_signal) and declared_signal != raw_signal:
        _error(errors, f"raw sample {sid} signal disagrees with PSF sample")
    unit, dims = _RAW_KINDS[kind]
    for declared_key in ("unit", "declared_unit"):
        if declared_key in sample and sample[declared_key] != unit:
            _error(errors, f"raw sample {sid} declares {sample[declared_key]!r}, but PSF type {kind} is {unit}")
    return {"unit": unit, "dims": dims, "kind": kind, "contains": {"I" if kind == "A" else kind}, "signal": raw_signal}


def _read_hashed_artifact(
    source: dict[str, Any], base_dir: Path | None, label: str, errors: list[str]
) -> str | None:
    """Read a declared artifact and require its exact SHA-256 before parsing."""
    path_value = source.get("path")
    expected = source.get("sha256")
    if not _text(path_value):
        _error(errors, f"{label} lacks source.path in production mode")
        return None
    if not _text(expected) or not re.fullmatch(r"[0-9a-fA-F]{64}", expected):
        _error(errors, f"{label} lacks a valid source.sha256 in production mode")
        return None
    path = Path(path_value)
    if not path.is_absolute():
        path = (base_dir or Path.cwd()) / path
    try:
        data = path.read_bytes()
    except OSError as exc:
        _error(errors, f"{label} cannot read source.path {path}: {exc}")
        return None
    actual = hashlib.sha256(data).hexdigest()
    if actual.lower() != expected.lower():
        _error(errors, f"{label} source.sha256 mismatch for {path}")
        return None
    return data.decode("utf-8", errors="replace")


def _inspect_spectre_log(log: str) -> dict[str, Any]:
    """Extract the small set of provenance/termination facts required in production.

    The file name and its hash are intentionally absent from this check: a
    wrapper can be immutably archived under any name.  Production acceptance
    instead requires the characteristic Spectre banner, version, invocation
    markers, and the simulator's own final error-count summary.
    """
    lines = log.splitlines()
    has_banner = any(_SPECTRE_BANNER_RE.search(line) for line in lines)
    has_version = any(_SPECTRE_VERSION_RE.search(line) for line in lines)
    has_simulating = any(_SPECTRE_SIMULATING_RE.search(line) for line in lines)
    has_command = any(_SPECTRE_COMMAND_RE.search(line) for line in lines)
    summaries = [
        (index, match)
        for index, line in enumerate(lines)
        if (match := _SPECTRE_SUMMARY_RE.search(line))
    ]
    summary_index, summary = summaries[-1] if summaries else (None, None)
    last_nonempty = max(
        (index for index, line in enumerate(lines) if line.strip()),
        default=None,
    )
    summary_terminal = summary is not None and summary_index == last_nonempty
    fatal = any(_SPECTRE_FATAL_RE.search(line) for line in lines)
    return {
        "identity": has_banner and has_version and has_simulating and has_command,
        "has_banner": has_banner,
        "has_version": has_version,
        "has_simulating": has_simulating,
        "has_command": has_command,
        "completed": summary_terminal,
        "error_count": int(summary.group("errors")) if summary else None,
        "warning_count": int(summary.group("warnings")) if summary else None,
        "notice_count": int(summary.group("notices")) if summary else None,
        "fatal": fatal,
    }


def _parse_production_raw_sample(
    sample: dict[str, Any], base_dir: Path | None, errors: list[str]
) -> dict[str, Any] | None:
    """Parse the unique type line for a signal from its hashed PSF artifact."""
    sid = sample.get("id", "<unnamed>")
    source = sample.get("source")
    if not isinstance(source, dict):
        _error(errors, f"raw sample {sid} lacks source object")
        return None
    if source.get("format") not in _ACCEPTED_SOURCE_FORMATS:
        _error(errors, f"raw sample {sid} lacks an accepted PSF source format")
    text = _read_hashed_artifact(source, base_dir, f"raw sample {sid}", errors)
    if text is None:
        return None
    signal = sample.get("signal")
    if not _text(signal):
        _error(errors, f"raw sample {sid} lacks signal name")
        return None
    matches = [match for match in _RAW_RE.finditer(text) if match.group("signal") == signal]
    if len(matches) != 1:
        _error(errors, f"raw sample {sid} requires one unique PSF type line for {signal!r}, found {len(matches)}")
        return None
    match = matches[0]
    kind = match.group("kind").upper()
    if kind not in _RAW_KINDS:
        _error(errors, f"raw sample {sid} uses unsupported PSF type {kind}")
        return None
    unit, dims = _RAW_KINDS[kind]
    return {"unit": unit, "dims": dims, "kind": kind, "contains": {"I" if kind == "A" else kind}, "signal": signal}


def _ref_names(formula: dict[str, Any]) -> list[str]:
    names: list[str] = []
    for key in ("input", "voltage", "current"):
        if _text(formula.get(key)):
            names.append(formula[key])
    inputs = formula.get("inputs")
    if isinstance(inputs, list):
        names.extend(value for value in inputs if _text(value))
    return names


def _resolve_formula(
    ref: str,
    raw: dict[str, dict[str, Any]],
    measurements: dict[str, dict[str, Any]],
    cache: dict[str, dict[str, Any]],
    stack: set[str],
    errors: list[str],
) -> dict[str, Any] | None:
    if ref in cache:
        return cache[ref]
    if ref in stack:
        _error(errors, f"measurement formula cycle at {ref}")
        return None
    if ref in raw:
        cache[ref] = raw[ref]
        return raw[ref]
    measurement = measurements.get(ref)
    if measurement is None:
        _error(errors, f"formula references unknown signal {ref}")
        return None
    formula = measurement.get("formula")
    if not isinstance(formula, dict):
        _error(errors, f"measurement {ref} lacks formula")
        return None
    op = str(formula.get("op", "")).lower()
    stack.add(ref)
    result: dict[str, Any] | None = None
    if op in {"identity", "raw"}:
        input_ref = formula.get("input")
        if not _text(input_ref):
            inputs = formula.get("inputs")
            input_ref = inputs[0] if isinstance(inputs, list) and inputs else None
        if not _text(input_ref):
            _error(errors, f"measurement {ref} identity formula lacks input")
        else:
            result = _resolve_formula(input_ref, raw, measurements, cache, stack, errors)
    elif op in {"mul", "multiply", "product", "power"}:
        if op == "power":
            refs = [formula.get("voltage"), formula.get("current")]
            if not all(_text(value) for value in refs):
                _error(errors, f"measurement {ref} power formula requires voltage and current inputs")
                refs = []
        else:
            refs = formula.get("inputs")
            if not isinstance(refs, list) or len(refs) < 2 or not all(_text(value) for value in refs):
                _error(errors, f"measurement {ref} multiplication formula needs at least two inputs")
                refs = []
        resolved = [
            _resolve_formula(value, raw, measurements, cache, stack, errors)
            for value in refs
        ]
        if resolved and all(item is not None for item in resolved):
            dims: dict[str, int] = {}
            contains: set[str] = set()
            for item in resolved:
                dims = _add_dims(dims, item["dims"])
                contains.update(item.get("contains", set()))
            result = {"unit": None, "dims": dims, "contains": contains}
    elif op in {"div", "divide", "ratio"}:
        refs = formula.get("inputs")
        if not isinstance(refs, list) or len(refs) != 2 or not all(_text(value) for value in refs):
            _error(errors, f"measurement {ref} division formula needs two inputs")
        else:
            numerator = _resolve_formula(refs[0], raw, measurements, cache, stack, errors)
            denominator = _resolve_formula(refs[1], raw, measurements, cache, stack, errors)
            if numerator and denominator:
                result = {
                    "unit": None,
                    "dims": _add_dims(numerator["dims"], denominator["dims"], -1),
                    "contains": set(numerator.get("contains", set())) | set(denominator.get("contains", set())),
                }
    else:
        _error(errors, f"measurement {ref} uses unsupported formula op {op!r}")
    stack.remove(ref)
    if result is not None:
        cache[ref] = result
    return result


def _names(rows: Any) -> tuple[list[str], list[str]]:
    """Return names and duplicate names from string or {name: ...} rows."""
    if not isinstance(rows, list):
        return [], ["<not-a-list>"]
    names: list[str] = []
    for row in rows:
        if isinstance(row, str):
            names.append(row)
        elif isinstance(row, dict) and _text(row.get("name")):
            names.append(row["name"])
        else:
            names.append("")
    duplicates = sorted({name for name in names if name and names.count(name) > 1})
    return names, duplicates


def load_packet(path: str | Path, synthetic: bool = False) -> dict[str, Any]:
    """Load a packet and retain its directory for production artifact lookup.

    ``synthetic=True`` is intentionally explicit and is only for isolated
    fixtures that contain inline ``psf_sample``/``raw_log`` text.  Production
    packets require hashed ``source.path`` artifacts by default.
    """
    packet_path = Path(path)
    packet = json.loads(packet_path.read_text(encoding="utf-8-sig"))
    if not isinstance(packet, dict):
        raise ValueError("measurement packet must be an object")
    packet["_packet_dir"] = str(packet_path.resolve().parent)
    packet["_validation_mode"] = "synthetic" if synthetic else "production"
    return packet


def validate(
    packet: dict[str, Any], mode: str | None = None, base_dir: str | Path | None = None
) -> dict[str, Any]:
    """Validate a packet; production artifact reads are the default."""
    errors: list[str] = []
    warnings: list[str] = []
    raw_units: dict[str, str] = {}
    diagnostic_findings: list[dict[str, Any]] = []
    if not isinstance(packet, dict):
        return {"valid": False, "errors": ["packet must be an object"], "warnings": [], "limits": []}
    if mode is None:
        mode = packet.get("_validation_mode", "production")
    if mode not in {"production", "synthetic"}:
        _error(errors, f"unsupported validation mode {mode!r}")
        mode = "production"
    if base_dir is None:
        base_dir = packet.get("_packet_dir")
    resolved_base_dir = Path(base_dir) if base_dir is not None else None
    if packet.get("version") != "0.1":
        _error(errors, "unsupported measurement packet version")

    # DUT elaboration gate: the expected root count must match explicit roots.
    dut = packet.get("dut")
    if not isinstance(dut, dict):
        _error(errors, "DUT count evidence is required")
    else:
        expected = dut.get("expected_count", dut.get("expected_dut_count"))
        roots = dut.get("roots", dut.get("observed_roots"))
        observed = dut.get("observed_count", dut.get("observed_dut_count"))
        if type(expected) is not int or expected < 1:
            _error(errors, "DUT expected count must be a positive integer")
        if roots is not None:
            if not isinstance(roots, list) or not all(_text(item) for item in roots):
                _error(errors, "DUT roots must be a list of names")
            else:
                observed_count = len(roots)
                if observed is not None and observed != observed_count:
                    _error(errors, "DUT observed count disagrees with roots")
                observed = observed_count
        if type(observed) is not int:
            _error(errors, "DUT observed root count is required")
        elif type(expected) is int and expected != observed:
            _error(errors, f"DUT expected count {expected} differs from observed {observed}")

    # Interface gate: exact set equality catches omitted pins and accidental wrappers.
    interface = packet.get("interface")
    if not isinstance(interface, dict):
        _error(errors, "interface expected/observed sets are required")
    else:
        expected_names, expected_dups = _names(interface.get("expected"))
        observed_names, observed_dups = _names(interface.get("observed"))
        if not expected_names or any(not name for name in expected_names):
            _error(errors, "interface expected set is empty or malformed")
        if any(not name for name in observed_names):
            _error(errors, "interface observed set is malformed")
        if expected_dups or observed_dups:
            _error(errors, "interface sets contain duplicate names")
        missing = sorted(set(expected_names) - set(observed_names))
        extra = sorted(set(observed_names) - set(expected_names))
        if missing or extra:
            _error(errors, f"interface coverage mismatch missing={missing} extra={extra}")

    # Ports and drive roles.
    ports = packet.get("ports")
    if not isinstance(ports, list) or not ports:
        _error(errors, "port role evidence is required")
    else:
        seen_ports: set[str] = set()
        for port in ports:
            if not isinstance(port, dict) or not _text(port.get("name")):
                _error(errors, "malformed port role record")
                continue
            name = port["name"]
            if name in seen_ports:
                _error(errors, f"duplicate port role record {name}")
            seen_ports.add(name)
            if not _text(port.get("role_basis")):
                _error(errors, f"port {name} lacks role evidence")
            state = port.get("state")
            role = str(port.get("role", "unknown")).lower()
            if state in _DRIVEN_STATES:
                driver = port.get("driver")
                if not isinstance(driver, dict) or not _text(driver.get("source")):
                    _error(errors, f"driven port {name} lacks source")
                    continue
                kind = str(driver.get("kind", "")).lower()
                if role in _UNCONFIRMED_ROLES:
                    _error(errors, f"port {name} has unconfirmed role and cannot be driven")
                elif kind in _IDEAL_KINDS and role in _UNKNOWN_ROLES:
                    diagnostic = str(driver.get("intent", "")).lower() == "diagnostic"
                    if not diagnostic or not _text(driver.get("compliance")):
                        _error(errors, f"port {name} has unresolved/output role and ideal drive")
                elif role == "output" and kind not in _LOAD_KINDS:
                    _error(errors, f"output port {name} requires a proven compliant load, not direct drive")
            elif state not in {"observed", "disconnected"}:
                _error(errors, f"port {name} has invalid state {state!r}")
            if state == "disconnected" and port.get("driver"):
                _error(errors, f"disconnected port {name} has a driver")

    # Supply provenance gate.
    conditions = packet.get("supply_conditions")
    condition_map: dict[str, dict[str, Any]] = {}
    if not isinstance(conditions, list) or not conditions:
        _error(errors, "supply condition provenance is required")
    else:
        for condition in conditions:
            if not isinstance(condition, dict) or not _text(condition.get("id")):
                _error(errors, "malformed supply condition")
                continue
            cid = condition["id"]
            if cid in condition_map:
                _error(errors, f"duplicate supply condition {cid}")
            condition_map[cid] = condition
            claim = condition.get("claim")
            source = condition.get("source")
            if claim not in {"nominal", "diagnostic", "unknown"}:
                _error(errors, f"supply condition {cid} has invalid claim")
            if not isinstance(source, dict) or not _text(source.get("kind")) or not _text(source.get("ref")):
                _error(errors, f"supply condition {cid} lacks source provenance")
            elif claim == "nominal" and source["kind"] not in _NOMINAL_SOURCES:
                _error(errors, f"nominal supply condition {cid} has non-nominal source provenance")
            if not isinstance(condition.get("voltage"), (int, float)) or not math.isfinite(condition["voltage"]):
                _error(errors, f"supply condition {cid} lacks finite voltage")

    # Parse source samples first; no measurement may invent a unit.
    raw: dict[str, dict[str, Any]] = {}
    raw_rows = packet.get("raw_samples")
    if not isinstance(raw_rows, list) or not raw_rows:
        _error(errors, "raw PSF samples are required")
    else:
        for sample in raw_rows:
            if not isinstance(sample, dict) or not _text(sample.get("id")):
                _error(errors, "malformed raw sample")
                continue
            sid = sample["id"]
            if sid in raw:
                _error(errors, f"duplicate raw sample {sid}")
                continue
            parsed = (
                _parse_production_raw_sample(sample, resolved_base_dir, errors)
                if mode == "production"
                else _parse_raw_sample(sample, errors)
            )
            if parsed is not None:
                raw[sid] = parsed
                raw_units[sid] = parsed["unit"]

    # Formula and quantity/unit gate.
    measurements = packet.get("measurements")
    by_id: dict[str, dict[str, Any]] = {}
    if not isinstance(measurements, list) or not measurements:
        _error(errors, "typed measurements are required")
    else:
        for measurement in measurements:
            if not isinstance(measurement, dict) or not _text(measurement.get("id")):
                _error(errors, "malformed measurement")
                continue
            mid = measurement["id"]
            if mid in by_id:
                _error(errors, f"duplicate measurement {mid}")
            by_id[mid] = measurement
        cache: dict[str, dict[str, Any]] = {}
        for mid, measurement in by_id.items():
            quantity = measurement.get("quantity")
            expected_dims = _QUANTITY_DIMS.get(quantity)
            expected_unit = _QUANTITY_UNITS.get(quantity)
            if expected_dims is None:
                _error(errors, f"measurement {mid} has unsupported quantity {quantity!r}")
                continue
            unit_dims = _unit_dims(measurement.get("unit"))
            if unit_dims is None or not _dim_equal(unit_dims, expected_dims):
                _error(errors, f"measurement {mid} quantity {quantity} has incompatible unit {measurement.get('unit')!r}")
            result = _resolve_formula(mid, raw, by_id, cache, set(), errors)
            if result is not None and not _dim_equal(result["dims"], expected_dims):
                _error(errors, f"measurement {mid} formula dimensions do not match {quantity}")
            if quantity == "power":
                contains = result.get("contains", set()) if result else set()
                if not {"V", "I"}.issubset(contains):
                    _error(errors, f"measurement {mid} power requires both voltage and current raw inputs")
            condition = measurement.get("condition")
            if not _text(condition) or condition not in condition_map:
                _error(errors, f"measurement {mid} references unknown supply condition")
            elif condition_map[condition].get("claim") == "diagnostic" and measurement.get("claim") in {"nominal", "performance", "product"}:
                _error(errors, f"measurement {mid} promotes diagnostic supply condition to product claim")

    # Runtime evidence gate.  Solver issues are parsed from raw log text, not a
    # boolean declared by the producer.
    runs = packet.get("runs")
    if not isinstance(runs, list) or not runs:
        _error(errors, "raw runtime logs are required")
    else:
        seen_runs: set[str] = set()
        for run in runs:
            if not isinstance(run, dict) or not _text(run.get("id")):
                _error(errors, "malformed run record")
                continue
            rid = run["id"]
            if rid in seen_runs:
                _error(errors, f"duplicate run {rid}")
            seen_runs.add(rid)
            status = run.get("status")
            claim_scope = run.get("claim_scope")
            if status not in {"planned", "failed", "diagnostic", "valid", "qualified"}:
                _error(errors, f"run {rid} has invalid status")
            if mode == "production":
                source = run.get("source")
                if not isinstance(source, dict):
                    source = {"path": run.get("log_path"), "sha256": run.get("sha256")}
                log = _read_hashed_artifact(source, resolved_base_dir, f"run {rid} log", errors) or ""
            else:
                if status in {"valid", "qualified", "diagnostic", "failed"} and not _text(run.get("raw_log")):
                    _error(errors, f"run {rid} lacks raw_log text")
                log = run.get("raw_log", "")
            runtime_issues: list[str] = []
            if mode == "production" and status in {"valid", "qualified", "diagnostic", "failed"}:
                runtime = _inspect_spectre_log(log)
                if not runtime["identity"]:
                    runtime_issues.append("spectre_identity_missing")
                if not runtime["completed"]:
                    runtime_issues.append("spectre_completion_missing")
                if runtime["fatal"]:
                    runtime_issues.append("spectre_fatal_failure")
                if runtime["error_count"] is not None and runtime["error_count"] != 0:
                    runtime_issues.append(f"spectre_errors_{runtime['error_count']}")
                if status in {"valid", "qualified"}:
                    if not runtime["identity"]:
                        _error(errors, f"run {rid} log lacks complete Spectre simulator identity")
                    if not runtime["completed"]:
                        _error(errors, f"run {rid} log lacks Spectre normal completion summary")
                    if runtime["fatal"]:
                        _error(errors, f"run {rid} log reports a Spectre fatal failure")
                    if runtime["error_count"] is None:
                        _error(errors, f"run {rid} log lacks Spectre error count")
                    elif runtime["error_count"] != 0:
                        _error(errors, f"run {rid} log reports {runtime['error_count']} Spectre errors")
            # Match issue phrases within one log line.  A normal gmin value or
            # completed stepping notice must not combine with a later error.
            gmin = any(
                re.search(
                    r"\b(?:gmin|gmindc)\b[^\r\n]{0,160}(?:"
                    r"significant(?:ly)?|noticeabl(?:y)?|influenc\w*|affect\w*|"
                    r"chang\w*|impact\w*|sensitiv\w*|(?:homotopy|source)\s+(?:stepping\s+)?fail\w*)",
                    line,
                    re.I,
                )
                for line in log.splitlines()
            )
            pivot = any(
                re.search(
                    r"bad\s+pivot(?:ing)?|pivot(?:ing)?\s+(?:fail\w*|warn\w*|problem)|singular\s+(?:matrix|jacobian)",
                    line,
                    re.I,
                )
                for line in log.splitlines()
            )
            findings: list[str] = []
            solver_findings: list[str] = []
            if gmin:
                solver_findings.append("gmin_influence")
            if pivot:
                solver_findings.append("bad_pivot")
            findings.extend(solver_findings)
            findings.extend(runtime_issues)
            if findings:
                finding: dict[str, Any] = {"run": rid, "issues": findings}
                if _text(run.get("archive_path")):
                    finding["archive_path"] = run["archive_path"]
                diagnostic_findings.append(finding)
                if solver_findings and status in {"valid", "qualified"}:
                    _error(errors, f"run {rid} has solver issues and cannot be {status}")
                elif solver_findings and status == "diagnostic":
                    if claim_scope != "diagnostic" or run.get("issue_disposition") not in {"diagnostic_only", "excluded_from_metrics", "sensitivity_pending"}:
                        _error(errors, f"diagnostic run {rid} must state issue disposition")
            if status == "qualified" and not run.get("limitations"):
                _error(errors, f"qualified run {rid} lacks limitations")
            if status == "diagnostic" and claim_scope != "diagnostic":
                _error(errors, f"diagnostic run {rid} must use diagnostic claim scope")

    return {
        "valid": not errors,
        "errors": errors,
        "warnings": warnings,
        "raw_units": raw_units,
        "diagnostic_findings": diagnostic_findings,
        "limits": [
            "Production mode reads hashed text PSF/log artifacts; it does not parse binary PSF files or prove simulator provenance.",
            "Synthetic mode accepts inline samples/logs only for isolated fixtures and is not a production evidence path.",
            "Role and supply provenance fields require independent source review; this checker cannot infer circuit direction or product specifications.",
        ],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("packet", type=Path, nargs="?")
    parser.add_argument("--example", action="store_true", help="print a diagnostic-only packet example")
    parser.add_argument(
        "--synthetic",
        action="store_true",
        help="accept inline psf_sample/raw_log text for tests only; production is the default",
    )
    args = parser.parse_args(argv)
    if args.example:
        print(json.dumps(example_packet(), ensure_ascii=False, indent=2))
        return 0
    if args.packet is None:
        parser.error("packet is required unless --example is used")
    try:
        packet = load_packet(args.packet, synthetic=args.synthetic)
        result = validate(packet, base_dir=args.packet.resolve().parent)
    except (OSError, ValueError) as exc:
        result = {"valid": False, "errors": [str(exc)], "warnings": [], "limits": []}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
