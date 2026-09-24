"""Synthetic gate tests for the analog-recovery evidence handoff.

The fixtures in this file are deliberately self-contained.  They exercise the
handoff checker without reading any project netlist, report, or historical run.
"""

import copy
import hashlib
import importlib.util
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CHECKER_PATH = ROOT / "skills" / "analog-recovery-evidence" / "scripts" / "check_bundle.py"
SPEC = importlib.util.spec_from_file_location("skill_v01_check_bundle", CHECKER_PATH)
CHECKER = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(CHECKER)


def _claim(claim_id, kind, source_refs=(), run_refs=(), **extra):
    row = {
        "id": claim_id,
        "kind": kind,
        "statement": f"synthetic {claim_id}",
        "source_refs": list(source_refs),
        "locator": "fixture:1",
        "confidence": "high" if kind != "UNKNOWN" else "low",
        "uncertainty": "" if kind != "UNKNOWN" else "missing evidence",
        "impact": "synthetic fixture only",
        "method": "" if kind != "DERIVED" else "fixture arithmetic",
        "alternatives": [] if kind != "INFERRED" else ["alternative explanation"],
        "verification": [] if kind != "INFERRED" else ["run a confirming test"],
        "run_refs": list(run_refs),
    }
    row.update(extra)
    return row


def make_bundle(source_root):
    """Create a complete, schema-shaped bundle and only synthetic source files."""
    files = {
        "netlist.txt": b"synthetic netlist fixture\n",
        "run.log": b"synthetic valid run log\n",
        "calculation.txt": b"synthetic calculation\n",
        "review.txt": b"synthetic fixture review\n",
    }
    for name, data in files.items():
        (source_root / name).write_bytes(data)

    def artifact(artifact_id, name, role):
        return {
            "id": artifact_id,
            "path": name,
            "sha256": hashlib.sha256(files[name]).hexdigest(),
            "role": role,
            "origin": "synthetic unittest fixture",
        }

    artifacts = [
        artifact("a_net", "netlist.txt", "netlist"),
        artifact("a_run", "run.log", "run_log"),
        artifact("a_calc", "calculation.txt", "calculation"),
        artifact("a_review", "review.txt", "review"),
    ]
    claims = [
        _claim("c_direct", "DIRECT", ["a_net"]),
        _claim("c_sim", "SIMULATED", ["a_run"], ["run1"]),
        _claim("c_derived", "DERIVED", ["a_calc"]),
    ]
    return {
        "manifest": {
            "schema_version": "0.1",
            "project_id": "synthetic-gate",
            "reference_assisted": False,
            "artifacts": artifacts,
            "runs": [
                {
                    "id": "run1",
                    "status": "valid",
                    "artifact_refs": ["a_run"],
                    "mode_ref": "mode1",
                    "conditions": "VDD=1.2V; TT; 25C",
                    "fixture_review_ref": "check_run",
                    "reason": "",
                }
            ],
        },
        "report_requirements": {
            "requirements": [
                {
                    "id": "req1",
                    "section": "synthetic",
                    "request": "cover the synthetic metric",
                    "required": True,
                }
            ]
        },
        "design_evidence": {
            "claims": claims,
            "ports": [
                {"name": "vin", "direction": "input", "claim_refs": ["c_direct"]},
                {"name": "vout", "direction": "output", "claim_refs": ["c_direct"]},
            ],
            "modes": [
                {
                    "id": "mode1",
                    "description": "synthetic operating mode",
                    "drivers": [
                        {
                            "port": "vin",
                            "behavior": "drive",
                            "setting": "1.2V",
                            "claim_refs": ["c_direct"],
                            "external_drive_justification": "input source is the test fixture",
                        },
                        {
                            "port": "vout",
                            "behavior": "observe",
                            "setting": "monitor",
                            "claim_refs": ["c_direct"],
                            "external_drive_justification": "",
                        },
                    ],
                    "claim_refs": ["c_direct"],
                }
            ],
        },
        "metrics": {
            "metrics": [
                {
                    "id": "m_sim",
                    "name": "synthetic response",
                    "unit": "V",
                    "kind": "SIMULATED",
                    "mode_ref": "mode1",
                    "definition": "fixture output",
                    "method": "read the fixture waveform",
                    "scope": "synthetic conditions",
                    "expected_cases": [
                        {"id": "case_low", "conditions": "low"},
                        {"id": "case_typ", "conditions": "typical"},
                        {"id": "case_high", "conditions": "high"},
                    ],
                    "typical_case_id": "case_typ",
                    "samples": [
                        {
                            "case_id": "case_low",
                            "value": -1e308,
                            "source_ref": "a_run",
                            "locator": "wave:low",
                            "run_ref": "run1",
                        },
                        {
                            "case_id": "case_typ",
                            "value": 2.5,
                            "source_ref": "a_run",
                            "locator": "wave:typ",
                            "run_ref": "run1",
                        },
                        {
                            "case_id": "case_high",
                            "value": 1e308,
                            "source_ref": "a_run",
                            "locator": "wave:high",
                            "run_ref": "run1",
                        },
                    ],
                    "status": "complete",
                    "reason": "",
                    "impact": "",
                    "next_action": "",
                    "claim_refs": ["c_sim"],
                },
                {
                    "id": "m_derived",
                    "name": "synthetic derived value",
                    "unit": "1",
                    "kind": "DERIVED",
                    "mode_ref": "mode1",
                    "definition": "fixture arithmetic",
                    "method": "fixture arithmetic",
                    "scope": "synthetic conditions",
                    "expected_cases": [{"id": "case_one", "conditions": "one"}],
                    "typical_case_id": "case_one",
                    "samples": [
                        {
                            "case_id": "case_one",
                            "value": 3.2,
                            "source_ref": "a_calc",
                            "locator": "calc:1",
                            "run_ref": None,
                        }
                    ],
                    "status": "complete",
                    "reason": "",
                    "impact": "",
                    "next_action": "",
                    "claim_refs": ["c_derived"],
                },
            ]
        },
        "coverage": {
            "items": [
                {
                    "requirement_ref": "req1",
                    "status": "complete",
                    "claim_refs": ["c_direct", "c_sim"],
                    "metric_refs": ["m_sim", "m_derived"],
                    "reason": "",
                    "impact": "",
                    "next_action": "",
                }
            ]
        },
        "review": {
            "author_id": "author",
            "reviewer_id": "reviewer",
            "independent": True,
            "checks": [
                {
                    "id": "check_run",
                    "subject_refs": ["run1", "mode1", "vin", "vout", "m_sim", "m_derived"],
                    "result": "pass",
                    "artifact_refs": ["a_review"],
                }
            ],
            "findings": [],
        },
        "report_map": {
            "blocks": [
                {
                    "id": "block1",
                    "section": "synthetic",
                    "claim_refs": ["c_direct", "c_sim"],
                    "metric_refs": ["m_sim", "m_derived"],
                    "stance": "asserted",
                    "text": "synthetic evidence block",
                }
            ]
        },
    }


class SkillHandoffGateTests(unittest.TestCase):
    def evaluate(self, mutate=None):
        with tempfile.TemporaryDirectory() as directory:
            source_root = Path(directory)
            bundle = make_bundle(source_root)
            if mutate is not None:
                mutate(bundle, source_root)
            return CHECKER.validate(bundle, source_root)

    def test_complete_bundle_and_extreme_values_have_expected_summary(self):
        result = self.evaluate()
        self.assertTrue(result["valid"], result)
        self.assertEqual(result["delivery_status"], "partial")
        self.assertEqual(result["key_claim_review"]["status"], "undeclared")
        simulated = next(row for row in result["summaries"] if row["id"] == "m_sim")
        self.assertEqual(simulated["measured_cases"], 3)
        self.assertEqual(simulated["expected_cases"], 3)
        self.assertEqual(simulated["min"]["case_id"], "case_low")
        self.assertEqual(simulated["min"]["value"], -1e308)
        self.assertEqual(simulated["typ"]["case_id"], "case_typ")
        self.assertEqual(simulated["typ"]["value"], 2.5)
        self.assertEqual(simulated["max"]["case_id"], "case_high")
        self.assertEqual(simulated["max"]["value"], 1e308)

    def test_unknown_mode_and_artifact_references_are_rejected(self):
        mutations = {
            "mode": lambda b, _: b["metrics"]["metrics"][0].update(mode_ref="ghost-mode"),
            "claim source": lambda b, _: b["design_evidence"]["claims"][0]["source_refs"].append("ghost-artifact"),
            "run artifact": lambda b, _: b["manifest"]["runs"][0]["artifact_refs"].append("ghost-artifact"),
        }
        for label, mutation in mutations.items():
            with self.subTest(label=label):
                result = self.evaluate(mutation)
                self.assertFalse(result["valid"], result)
                self.assertTrue(result["errors"], result)

        def cross_mode_sample(bundle, _):
            other_mode = copy.deepcopy(bundle["design_evidence"]["modes"][0])
            other_mode["id"] = "mode2"
            bundle["design_evidence"]["modes"].append(other_mode)
            bundle["manifest"]["runs"][0]["mode_ref"] = "mode2"

        result = self.evaluate(cross_mode_sample)
        self.assertFalse(result["valid"], result)
        self.assertTrue(any("sample run mode differs from metric" in e for e in result["errors"]))

    def test_missing_case_rejects_complete_metric(self):
        def remove_case_sample(bundle, _):
            bundle["metrics"]["metrics"][0]["samples"] = bundle["metrics"]["metrics"][0]["samples"][:-1]

        result = self.evaluate(remove_case_sample)
        self.assertFalse(result["valid"], result)
        self.assertTrue(any("complete metric missing cases: m_sim" in e for e in result["errors"]))

    def test_failed_run_cannot_contaminate_simulated_claim_or_sample(self):
        def fail_run(bundle, _):
            bundle["manifest"]["runs"][0].update(status="failed", reason="synthetic solver failure")

        result = self.evaluate(fail_run)
        self.assertFalse(result["valid"], result)
        self.assertTrue(any("SIMULATED claim needs valid runs" in e for e in result["errors"]))
        self.assertTrue(any("invalid simulation sample" in e for e in result["errors"]))

    def test_forced_output_requires_external_drive_justification(self):
        def force_output(bundle, _):
            driver = bundle["design_evidence"]["modes"][0]["drivers"][1]
            driver.update(behavior="drive", external_drive_justification="")

        result = self.evaluate(force_output)
        self.assertFalse(result["valid"], result)
        self.assertTrue(any("unjustified forced output" in e for e in result["errors"]))

    def test_unknown_and_inferred_claims_cannot_enter_asserted_report_text(self):
        def add_claims(bundle, _):
            bundle["design_evidence"]["claims"].extend(
                [
                    _claim("c_unknown", "UNKNOWN", uncertainty="not measured"),
                    _claim(
                        "c_inferred",
                        "INFERRED",
                        ["a_net"],
                        uncertainty="polarity not established",
                    ),
                ]
            )
            bundle["report_map"]["blocks"] = [
                {
                    "id": "unknown_block",
                    "section": "synthetic",
                    "claim_refs": ["c_unknown"],
                    "metric_refs": [],
                    "stance": "asserted",
                    "text": "unknown text",
                },
                {
                    "id": "inferred_block",
                    "section": "synthetic",
                    "claim_refs": ["c_inferred"],
                    "metric_refs": [],
                    "stance": "asserted",
                    "text": "inferred text",
                },
            ]

        result = self.evaluate(add_claims)
        self.assertFalse(result["valid"], result)
        self.assertTrue(any("UNKNOWN promoted into assertion" in e for e in result["errors"]))
        self.assertTrue(any("inference needs qualified stance" in e for e in result["errors"]))

    def test_hash_tamper_and_path_escape_are_rejected(self):
        def tamper_file(bundle, source_root):
            (source_root / "run.log").write_bytes(b"tampered synthetic run log")

        result = self.evaluate(tamper_file)
        self.assertFalse(result["valid"], result)
        self.assertTrue(any("hash mismatch: a_run" in e for e in result["errors"]))

        def escape_path(bundle, _):
            bundle["manifest"]["artifacts"][0]["path"] = "../outside.txt"

        result = self.evaluate(escape_path)
        self.assertFalse(result["valid"], result)
        self.assertTrue(any("artifact path must stay relative" in e for e in result["errors"]))

    def test_absent_independent_review_is_valid_but_partial(self):
        def remove_independence(bundle, _):
            bundle["review"]["independent"] = False

        result = self.evaluate(remove_independence)
        self.assertTrue(result["valid"], result)
        self.assertEqual(result["delivery_status"], "partial")
        self.assertTrue(any("independent review not established" in w for w in result["warnings"]))

    def test_driver_unknown_claim_ref_should_be_rejected(self):
        def unknown_driver_claim(bundle, _):
            bundle["design_evidence"]["modes"][0]["drivers"][0]["claim_refs"] = ["ghost-claim"]

        result = self.evaluate(unknown_driver_claim)
        self.assertFalse(result["valid"], result)

    def test_duplicate_expected_case_ids_should_be_rejected(self):
        def duplicate_case(bundle, _):
            cases = bundle["metrics"]["metrics"][0]["expected_cases"]
            cases[1]["id"] = cases[0]["id"]
            metric = bundle["metrics"]["metrics"][0]
            metric["typical_case_id"] = "case_low"
            metric["samples"] = [metric["samples"][0], metric["samples"][2]]

        result = self.evaluate(duplicate_case)
        self.assertFalse(result["valid"], result)

    def test_unknown_claim_hidden_behind_metric_should_not_be_complete_assertion(self):
        """Known gap: UNKNOWN is checked only on direct coverage/report claims."""
        def hide_unknown_behind_metric(bundle, _):
            bundle["design_evidence"]["claims"].append(
                _claim("c_unknown_metric", "UNKNOWN", uncertainty="not measured")
            )
            bundle["metrics"]["metrics"][0]["claim_refs"] = ["c_unknown_metric"]
            bundle["coverage"]["items"][0]["claim_refs"] = ["c_direct", "c_sim"]
            bundle["report_map"]["blocks"][0].update(
                claim_refs=[], metric_refs=["m_sim"], stance="asserted"
            )

        result = self.evaluate(hide_unknown_behind_metric)
        self.assertFalse(result["valid"], result)

    def test_duplicate_finding_ids_should_be_rejected(self):
        """Known gap: finding IDs are not indexed for uniqueness."""
        def duplicate_finding(bundle, _):
            bundle["review"]["findings"] = [
                {
                    "id": "finding1",
                    "severity": "nonblocking",
                    "status": "open",
                    "affected_refs": ["c_direct"],
                    "description": "synthetic finding",
                    "resolution": "",
                },
                {
                    "id": "finding1",
                    "severity": "nonblocking",
                    "status": "open",
                    "affected_refs": ["c_direct"],
                    "description": "synthetic finding duplicate",
                    "resolution": "",
                },
            ]

        result = self.evaluate(duplicate_finding)
        self.assertFalse(result["valid"], result)



class CriticalReviewTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.b = make_bundle(self.root)
        for c in self.b['design_evidence']['claims']:
            c['critical_review_required'] = c['id'] in ('c_direct', 'c_sim')
        self.b['review']['checks'][0]['subject_refs'] += ['c_direct', 'c_sim']

    def result(self):
        return CHECKER.validate(self.b, self.root)

    def test_full_and_partial_coverage(self):
        self.assertEqual(self.result()['delivery_status'], 'ready_for_editorial_review')
        self.b['review']['checks'][0]['subject_refs'].remove('c_sim')
        r = self.result()
        self.assertTrue(r['valid'], r)
        self.assertEqual(r['key_claim_review']['status'], 'partial')
        self.assertEqual(r['key_claim_review']['covered_count'], 1)
        self.assertIn('review missing for critical claims: c_sim', r['warnings'])
        self.b['review']['checks'][0]['subject_refs'].remove('c_direct')
        self.assertEqual(self.result()['key_claim_review']['status'], 'unreviewed')

    def test_declaration_states_and_empty_claims_invalid(self):
        claims = self.b['design_evidence']['claims']
        del claims[0]['critical_review_required']
        self.assertEqual(self.result()['key_claim_review']['status'], 'declaration_incomplete')
        for c in claims:
            c.pop('critical_review_required', None)
        for version in ('0.1', '0.2'):
            self.b['manifest']['schema_version'] = version
            self.b['manifest']['artifacts'][2]['input_refs'] = ['a_net']
            r = self.result()
            self.assertTrue(r['valid'], r)
            self.assertEqual(r['delivery_status'], 'partial')
            self.assertEqual(r['key_claim_review']['status'], 'undeclared')
        for c in claims:
            c['critical_review_required'] = False
        self.assertEqual(self.result()['key_claim_review']['status'], 'empty_declared')
        self.assertEqual(self.result()['delivery_status'], 'partial')
        claims.clear()
        r = self.result()
        self.assertFalse(r['valid'])
        self.assertEqual(r['delivery_status'], 'invalid')
        self.assertIn('claims, requirements and modes must be nonempty', r['errors'])

    def test_cross_type_subject_collision_cannot_cover_claim(self):
        # Each name already denotes another type, with a pass for that other object.
        for name in ('m_sim', 'mode1', 'run1', 'vin', 'req1'):
            with self.subTest(name=name):
                b = copy.deepcopy(self.b)
                b['design_evidence']['claims'].append(_claim(name, 'DIRECT', ['a_net'], critical_review_required=True))
                b['review']['checks'][0]['subject_refs'].append(name)
                r = CHECKER.validate(b, self.root)
                self.assertFalse(r['valid'], r)
                self.assertIn('ambiguous critical claim subject IDs: '+name, r['errors'])
                self.assertEqual(r['key_claim_review']['covered_count'], 2)
                self.assertEqual(r['key_claim_review']['required_count'], 3)

    def test_invalid_records_and_flag_types(self):
        mutations = [
            lambda b: b['review']['checks'][0].update(artifact_refs=[]),
            lambda b: b['review']['checks'][0]['subject_refs'].append('ghost'),
            lambda b: b['review']['checks'][0].update(artifact_refs=['ghost']),
        ]
        mutations += [lambda b, v=v: b['design_evidence']['claims'][0].update(critical_review_required=v)
                      for v in ('true', 1, None)]
        for mutate in mutations:
            b = copy.deepcopy(self.b); mutate(b)
            self.assertFalse(CHECKER.validate(b, self.root)['valid'])

    def test_fail_blocking_and_independence_still_apply(self):
        failed = dict(self.b['review']['checks'][0], id='failed', result='fail')
        self.b['review']['checks'].append(failed)
        self.assertFalse(self.result()['valid'])
        self.b['review']['checks'].pop()
        self.b['review']['findings'] = [dict(id='f', severity='blocking', status='open',
            affected_refs=['c_direct'], description='not resolved', resolution='')]
        self.assertFalse(self.result()['valid'])
        self.b['review']['findings'] = []
        self.b['review']['independent'] = False
        self.assertEqual(self.result()['delivery_status'], 'partial')

    def test_reviewed_unknown_and_inferred_keep_their_kind(self):
        for kind in ('UNKNOWN', 'INFERRED'):
            with self.subTest(kind=kind):
                b = copy.deepcopy(self.b)
                b['design_evidence']['claims'].append(_claim('extra', kind, ['a_net'],
                    critical_review_required=True, uncertainty='scope not established'))
                b['review']['checks'][0]['subject_refs'].append('extra')
                r = CHECKER.validate(b, self.root)
                self.assertTrue(r['valid'], r)
                self.assertEqual(r['key_claim_review']['status'], 'covered')
                self.assertEqual(b['design_evidence']['claims'][-1]['kind'], kind)

if __name__ == "__main__":
    unittest.main()
