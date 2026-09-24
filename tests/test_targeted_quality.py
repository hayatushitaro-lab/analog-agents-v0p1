"""Independent targeted quality-contract counterexamples (quality v1 extension).

These fixtures are synthetic and deliberately avoid project netlists, reports,
models, previous outputs, network access, and simulator execution.
"""

import copy
import importlib.util
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "targeted_quality", ROOT / "skills" / "analog-recovery-evidence" / "scripts" / "check_quality.py"
)
QUALITY = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(QUALITY)


def targeted_packet():
    source = {"id": "synthetic", "path": "synthetic.txt", "sha256": "0" * 64}
    return {
        "schema_version": "1",
        "artifacts": [source],
        "fixtures": [{
            "id": "fixture",
            "source_refs": ["synthetic"],
            "dut_nodes": ["supply", "control", "output"],
            "edges": [["drive", "control"]],
            "scans": [{
                "id": "enable",
                "node": "drive",
                "kind": "electrical",
                "target_nodes": ["control"],
                "source_refs": ["synthetic"],
                "observed_change": True,
                "measurement": {
                    "node": "output",
                    "unit": "V",
                    "event": "not_applicable",
                    "threshold": "not_applicable",
                    "window": "not_applicable",
                    "range": "observed voltage",
                    "source_refs": ["synthetic"],
                },
            }],
            "domains": [],
        }],
        "calculations": [],
        "metrics": [],
        "runs": [],
        "claims": [],
        "uses": [],
    }


class TargetedQualityTests(unittest.TestCase):
    def result(self, value):
        return QUALITY.validate(value, Path("."), verify_files=False)

    def test_all_targets_must_be_reachable(self):
        value = targeted_packet()
        value["fixtures"][0]["dut_nodes"].append("isolated")
        value["fixtures"][0]["scans"][0]["target_nodes"].append("isolated")
        result = self.result(value)
        self.assertIn("unreachable_scan_target", str(result["errors"]))

    def test_target_must_be_declared_dut_node(self):
        value = targeted_packet()
        value["fixtures"][0]["scans"][0]["target_nodes"] = ["drive"]
        result = self.result(value)
        self.assertIn("scan_target_not_dut", str(result["errors"]))

    def test_targeted_scan_requires_measurement_handoff_fields(self):
        for field in ['node', 'unit', 'event', 'threshold', 'window', 'range', 'source_refs']:
            value = targeted_packet()
            del value["fixtures"][0]["scans"][0]["measurement"][field]
            self.assertFalse(self.result(value)['valid'], field)

    def test_output_measurement_is_not_wire_connected_to_control(self):
        self.assertTrue(self.result(targeted_packet())["valid"])

    def test_reaching_supply_does_not_prove_control_reached(self):
        value = targeted_packet()
        value['fixtures'][0]['edges'] = [['drive', 'supply']]
        self.assertIn('unreachable_scan_target', str(self.result(value)['errors']))

    def test_constant_response_does_not_prove_disconnection(self):
        value = targeted_packet()
        value['fixtures'][0]['scans'][0]['observed_change'] = False
        self.assertTrue(self.result(value)['valid'])

    def test_empty_targets_and_blank_measurement_are_rejected(self):
        for field, val in [('target_nodes', []), ('measurement', None)]:
            value = targeted_packet()
            value['fixtures'][0]['scans'][0][field] = val
            self.assertFalse(self.result(value)['valid'])
        for field in ['node', 'unit', 'event', 'threshold', 'window', 'range']:
            value = targeted_packet()
            value['fixtures'][0]['scans'][0]['measurement'][field] = ' '
            self.assertFalse(self.result(value)['valid'], field)

    def test_measurement_source_and_node_must_exist(self):
        for field, val in [('node', 'foreign/output'), ('source_refs', ['missing']), ('source_refs', [])]:
            value = targeted_packet()
            value['fixtures'][0]['scans'][0]['measurement'][field] = val
            self.assertFalse(self.result(value)['valid'], field)

    def test_legacy_scan_stays_valid_but_is_not_targeted_verification(self):
        value = targeted_packet()
        scan = value['fixtures'][0]['scans'][0]
        del scan['target_nodes']; del scan['measurement']
        result = self.result(value)
        self.assertTrue(result['valid'])
        self.assertIn('legacy_scan_without_target', str(result['warnings']))

    def test_target_set_can_include_multiple_wire_aliases(self):
        value = targeted_packet()
        fixture = value['fixtures'][0]
        fixture['dut_nodes'].append('nested/control')
        fixture['edges'].append(['control', 'nested/control'])
        fixture['scans'][0]['target_nodes'].append('nested/control')
        self.assertTrue(self.result(value)['valid'])


if __name__ == "__main__":
    unittest.main()
