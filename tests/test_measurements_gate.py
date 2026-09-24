"""Independent fixtures for the electrical measurement evidence gate.

The fixtures deliberately contain no project paths, reports, simulator runs, or
FM524-specific names.  They exercise the small JSON contract documented by the
gate itself.
"""
import copy
import hashlib
import io
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from contextlib import redirect_stdout


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "skills" / "analog-recovery-evidence" / "scripts" / "check_measurements.py"
SPEC = importlib.util.spec_from_file_location("check_measurements", SCRIPT)
gate = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(gate)


def packet():
    """A minimal, electrically coherent packet."""
    return {
        "version": "0.1",
        "dut": {"expected_count": 1, "roots": ["XDUT"]},
        "interface": {
            "expected": ["vdd", "vss", "vref", "out"],
            "observed": ["vdd", "vss", "vref", "out"],
        },
        "ports": [
            {
                "name": "vdd",
                "role": "supply",
                "state": "driven",
                "role_basis": "static:power-pin-connectivity",
                "driver": {"kind": "finite_voltage", "source": "supply:vdd"},
            },
            {
                "name": "vss",
                "role": "ground",
                "state": "driven",
                "role_basis": "static:ground-connectivity",
                "driver": {"kind": "finite_voltage", "source": "supply:vss"},
            },
            {
                "name": "vref",
                "role": "reference",
                "state": "observed",
                "role_basis": "static:feedback-pin-connectivity",
            },
            {
                "name": "out",
                "role": "output",
                "state": "observed",
                "role_basis": "static:output-connectivity",
            },
        ],
        "supply_conditions": [
            {
                "id": "nominal",
                "claim": "nominal",
                "voltage": 1.2,
                "source": {"kind": "schematic", "ref": "design-input:VDD"},
            }
        ],
        "raw_samples": [
            {
                "id": "raw_vdd",
                "signal": "V(vdd)",
                "psf_sample": '"V(vdd)" "V" 1.2',
                "source": {"format": "spectre_psf_text", "ref": "run1:dcOp.dc:1"},
            },
            {
                "id": "raw_i_vdd",
                "signal": "I(VDDsrc:p)",
                "psf_sample": '"I(VDDsrc:p)" "I" -1.0e-5',
                "source": {"format": "spectre_psf_text", "ref": "run1:dcOp.dc:2"},
            },
        ],
        "measurements": [
            {
                "id": "supply_current",
                "quantity": "current",
                "unit": "A",
                "formula": {"op": "identity", "input": "raw_i_vdd"},
                "condition": "nominal",
                "claim": "diagnostic",
            },
            {
                "id": "supply_power",
                "quantity": "power",
                "unit": "W",
                "formula": {
                    "op": "mul",
                    "inputs": ["raw_vdd", "raw_i_vdd"],
                },
                "condition": "nominal",
                "claim": "diagnostic",
            },
        ],
        "runs": [
            {
                "id": "run1",
                "status": "valid",
                "claim_scope": "operating_point",
                "raw_log": "spectre completed with no warnings",
            }
        ],
    }


SPECTRE_NORMAL_LOG = """Spectre (R) Circuit Simulator
Version 18.1.0.077 64bit
Simulating `fixture.scs' on test-host
Command line:
    spectre -64 fixture.scs
Convergence achieved in 12 iterations.
spectre completes with 0 errors, 1 warning, and 2 notices.
"""


SPECTRE_FATAL_LOG = """Spectre (R) Circuit Simulator
Version 18.1.0.077 64bit
Simulating `fixture.scs' on test-host
Command line:
    spectre -64 fixture.scs
spectre completes with 1 error, 0 warnings, and 0 notices.
spectre terminated prematurely due to fatal error.
"""


def production_result(log_text, *, status="valid", archive_path=None):
    """Validate a packet whose artifacts are all hashed production files."""
    value = packet()
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)

        def artifact(name, text, fmt=None):
            path = root / name
            path.write_text(text, encoding="utf-8")
            result = {"path": name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
            if fmt:
                result["format"] = fmt
            return result

        value["raw_samples"][0]["psf_sample"] = "forged inline sample"
        value["raw_samples"][0]["source"] = artifact("v.psf", '"V(vdd)" "V" 1.2\n', "spectre_psf_text")
        value["raw_samples"][1]["psf_sample"] = "forged inline sample"
        value["raw_samples"][1]["source"] = artifact("i.psf", '"I(VDDsrc:p)" "I" -1e-5\n', "spectre_psf_text")
        log_source = artifact("run.log", log_text, "spectre_log")
        run = value["runs"][0]
        run.pop("raw_log", None)
        run["status"] = status
        if status == "diagnostic":
            run["claim_scope"] = "diagnostic"
            run["issue_disposition"] = "diagnostic_only"
        run["log_path"] = log_source["path"]
        run["sha256"] = log_source["sha256"]
        if archive_path is not None:
            run["archive_path"] = archive_path
        packet_path = root / "packet.json"
        packet_path.write_text(json.dumps(value), encoding="utf-8")
        return gate.validate(gate.load_packet(packet_path))


class MeasurementGateTests(unittest.TestCase):
    def test_spectre_ampere_type_supports_current_and_power(self):
        data = packet()
        for sample in data['raw_samples']:
            if 'psf_sample' in sample:
                sample['psf_sample'] = sample['psf_sample'].replace('"I"', '"A"')
        result = gate.validate(data, mode="synthetic")
        self.assertTrue(result['valid'], result['errors'])

    def assert_invalid(self, value, text):
        result = gate.validate(value, mode="synthetic")
        self.assertFalse(result["valid"], result)
        self.assertTrue(any(text in error for error in result["errors"]), result)

    def test_valid_typed_current_and_voltage_times_current_power(self):
        result = gate.validate(packet(), mode="synthetic")
        self.assertTrue(result["valid"], result)
        self.assertEqual(result["raw_units"]["raw_i_vdd"], "A")

    def test_current_cannot_be_declared_as_watts(self):
        value = packet()
        value["measurements"][0]["unit"] = "W"
        self.assert_invalid(value, "supply_current")

    def test_power_requires_voltage_and_current_formula(self):
        value = packet()
        value["measurements"][1]["formula"] = {
            "op": "identity",
            "input": "raw_i_vdd",
        }
        self.assert_invalid(value, "power")

    def test_raw_psf_type_beats_self_reported_unit(self):
        value = packet()
        value["raw_samples"][1]["declared_unit"] = "W"
        self.assert_invalid(value, "raw_i_vdd")

    def test_unknown_role_cannot_be_ideally_driven(self):
        value = packet()
        value["ports"][2] = {
            "name": "vref",
            "role": "unknown",
            "state": "driven",
            "role_basis": "unresolved",
            "driver": {"kind": "ideal_voltage", "source": "fixture:vref"},
        }
        self.assert_invalid(value, "vref")

    def test_nominal_supply_requires_provenance_and_diagnostic_is_not_nominal(self):
        value = packet()
        value["supply_conditions"][0]["source"] = {
            "kind": "diagnostic",
            "ref": "fixture-choice",
        }
        self.assert_invalid(value, "nominal")

    def test_expected_dut_count_and_interface_set_are_closed(self):
        value = packet()
        value["dut"]["roots"] = ["XDUT", "I2"]
        self.assert_invalid(value, "DUT")
        value = packet()
        value["interface"]["observed"] = ["vdd", "vss", "out"]
        self.assert_invalid(value, "interface")

    def test_gmin_or_bad_pivot_cannot_be_qualified(self):
        value = packet()
        value["runs"][0]["status"] = "qualified"
        value["runs"][0]["raw_log"] = (
            "gmin homotopy failed; GminDC changed node net15; bad pivoting"
        )
        self.assert_invalid(value, "qualified")

    def test_issue_may_be_kept_as_explicit_diagnostic(self):
        value = packet()
        value["runs"][0]["status"] = "diagnostic"
        value["runs"][0]["claim_scope"] = "diagnostic"
        value["runs"][0]["raw_log"] = "gmin homotopy failed; bad pivoting"
        value["runs"][0]["issue_disposition"] = "diagnostic_only"
        result = gate.validate(value, mode="synthetic")
        self.assertTrue(result["valid"], result)
        self.assertTrue(result["diagnostic_findings"])

    def test_normal_gmin_setting_is_not_solver_influence(self):
        value = packet()
        value["runs"][0]["raw_log"] = (
            "gmin=1e-12\nDynamic gmin stepping completed\n"
            "spectre completed with no warnings"
        )
        result = gate.validate(value, mode="synthetic")
        self.assertTrue(result["valid"], result)
        self.assertEqual(result["diagnostic_findings"], [])

    def test_confirmed_output_can_use_a_compliant_load(self):
        value = packet()
        value["ports"][3] = {
            "name": "out",
            "role": "output",
            "state": "driven",
            "role_basis": "static:output-connectivity",
            "driver": {
                "kind": "finite_load",
                "source": "fixture:load",
                "compliance": "load range from downstream evidence",
            },
        }
        result = gate.validate(value, mode="synthetic")
        self.assertTrue(result["valid"], result)

    def test_unconfirmed_role_cannot_use_even_a_finite_load(self):
        value = packet()
        value["ports"][2] = {
            "name": "vref",
            "role": "unknown",
            "state": "driven",
            "role_basis": "unresolved",
            "driver": {
                "kind": "finite_load",
                "source": "fixture:load",
                "compliance": "bounded",
            },
        }
        self.assert_invalid(value, "vref")

    def test_model_range_is_not_nominal_but_user_spec_is(self):
        value = packet()
        value["supply_conditions"][0]["source"] = {
            "kind": "model_range",
            "ref": "model metadata",
        }
        self.assert_invalid(value, "nominal")
        value["supply_conditions"][0]["source"] = {
            "kind": "user_spec",
            "ref": "approved requirement",
        }
        self.assertTrue(gate.validate(value, mode="synthetic")["valid"])

    def test_production_reads_hashed_psf_and_log_instead_of_inline_text(self):
        value = packet()
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)

            def artifact(name, text, fmt=None):
                path = root / name
                path.write_text(text, encoding="utf-8")
                result = {"path": name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
                if fmt:
                    result["format"] = fmt
                return result

            value["raw_samples"][0]["psf_sample"] = "forged inline sample"
            value["raw_samples"][0]["source"] = artifact("v.psf", '"V(vdd)" "V" 1.2\n', "spectre_psf_text")
            value["raw_samples"][1]["psf_sample"] = "forged inline sample"
            value["raw_samples"][1]["source"] = artifact("i.psf", '"I(VDDsrc:p)" "I" -1e-5\n', "spectre_psf_text")
            log_source = artifact("run.log", SPECTRE_NORMAL_LOG, "spectre_log")
            value["runs"][0].pop("raw_log")
            value["runs"][0]["log_path"] = log_source["path"]
            value["runs"][0]["sha256"] = log_source["sha256"]
            packet_path = root / "packet.json"
            packet_path.write_text(json.dumps(value), encoding="utf-8")
            result = gate.validate(gate.load_packet(packet_path))
            self.assertTrue(result["valid"], result)

    def test_production_rejects_inline_sample_when_hashed_psf_has_wrong_type(self):
        value = packet()
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)

            def artifact(name, text, fmt=None):
                path = root / name
                path.write_text(text, encoding="utf-8")
                result = {"path": name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
                if fmt:
                    result["format"] = fmt
                return result

            value["raw_samples"][0]["source"] = artifact("v.psf", '"V(vdd)" "V" 1.2\n', "spectre_psf_text")
            value["raw_samples"][1]["source"] = artifact(
                "i.psf", '"I(VDDsrc:p)" "V" -1e-5\n', "spectre_psf_text"
            )
            log_source = artifact("run.log", "completed without warnings\n", "spectre_log")
            value["runs"][0].pop("raw_log")
            value["runs"][0]["log_path"] = log_source["path"]
            value["runs"][0]["sha256"] = log_source["sha256"]
            result = gate.validate(value, base_dir=root)
            self.assertFalse(result["valid"], result)
            self.assertTrue(any("supply_current" in error for error in result["errors"]), result)

    def test_production_rejects_wrapper_summary_without_spectre_identity(self):
        result = production_result(
            "wrapper completed successfully\n"
            "spectre completes with 0 errors, 0 warnings, and 0 notices.\n"
        )
        self.assertFalse(result["valid"], result)
        self.assertTrue(any("Spectre simulator identity" in error for error in result["errors"]), result)

    def test_production_rejects_truncated_spectre_log(self):
        result = production_result(
            "\n".join(SPECTRE_NORMAL_LOG.splitlines()[:-1]) + "\n"
        )
        self.assertFalse(result["valid"], result)
        self.assertTrue(any("normal completion summary" in error for error in result["errors"]), result)

    def test_production_rejects_fatal_spectre_run_for_performance_claim(self):
        result = production_result(SPECTRE_FATAL_LOG)
        self.assertFalse(result["valid"], result)
        self.assertTrue(any("fatal failure" in error for error in result["errors"]), result)
        self.assertTrue(any("Spectre errors" in error for error in result["errors"]), result)

    def test_production_keeps_failed_diagnostic_archive_path(self):
        archive = "archive/failed-run/spectre.out"
        result = production_result(SPECTRE_FATAL_LOG, status="diagnostic", archive_path=archive)
        self.assertTrue(result["valid"], result)
        self.assertEqual(result["diagnostic_findings"][0]["archive_path"], archive)
        self.assertIn("spectre_fatal_failure", result["diagnostic_findings"][0]["issues"])

    def test_cli_example_is_a_valid_diagnostic_contract(self):
        output = io.StringIO()
        with redirect_stdout(output):
            self.assertEqual(gate.main(["--example"]), 0)
        example = json.loads(output.getvalue())
        self.assertTrue(gate.validate(example, mode="synthetic")["valid"])


if __name__ == "__main__":
    unittest.main()
