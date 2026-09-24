"""Behavioral tests for the bounded recovery workflow resolver."""

import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "skills/analog-recovery/scripts/resolve_workflow.py"
SPEC = importlib.util.spec_from_file_location("recovery_workflow", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class ResolveWorkflowTests(unittest.TestCase):
    def test_task_model_and_site_are_explicit(self):
        result = MODULE.resolve({'subagent_model': 'gpt-6-astra', 'reasoning_effort': 'medium',
                                 'repository_root': str(ROOT), 'site_config': 'skills/analog-recovery/_local/site.json'})
        self.assertEqual(result['subagent_model'], 'gpt-6-astra')
        self.assertEqual(result['reasoning_effort'], 'medium')
        self.assertTrue(Path(result['review_transport']['site_config']).is_relative_to(ROOT))
        self.assertFalse(result['dispatch']['starts_agents'])
        with self.assertRaises(MODULE.WorkflowConfigError):
            MODULE.resolve({'repository_root': str(ROOT), 'site_config': '../outside.json'})

    def test_all_efforts_change_strategy_only_and_keep_budget_policy(self):
        strategies = {}
        for effort in ("lite", "standard", "intensive", "exhaustive"):
            result = MODULE.resolve(
                {
                    "workflow_effort": effort,
                    "resources": {"remote_seconds": 12, "max_concurrent_runs": 2},
                }
            )
            strategies[effort] = result["effort"]["coverage_strategy"]
            self.assertEqual(result["effective_config"]["resources"], {
                "remote_seconds": 12,
                "max_concurrent_runs": 2,
            })
            self.assertEqual(result["effort"]["evidence_standard"], "fixed_for_all_efforts")
            self.assertIsNone(result["subagent_model"])
            self.assertIsNone(result["reasoning_effort"])
        self.assertEqual(len(set(strategies.values())), 4)

    def test_defaults_and_role_routing(self):
        result = MODULE.resolve({})
        self.assertEqual(result["effective_config"], {
            "workflow_effort": "standard",
            "behavioral": "auto",
            "module_scale": "small",
            "mode": "replay",
            "resources": {"remote_seconds": 0, "max_concurrent_runs": 0},
            "simulation_authorized": False,
        })
        self.assertEqual(result["role_routing"], {
            "ANALYST": ["analog-learn", "analog-audit"],
            "REVIEWER": ["analog-review"],
            "VERIFIER": ["analog-verify", "spectre"],
            "EDITOR": ["analog-recovery-report"],
        })
        self.assertNotIn("ARCHITECT", result["role_routing"])

        large = MODULE.resolve({"module_scale": "large"})
        self.assertEqual(
            large["role_routing"]["ARCHITECT"],
            ["analog-decompose", "analog-integrate"],
        )

    def test_live_requires_authorization_and_both_positive_resources(self):
        base = {
            "mode": "live",
            "simulation_authorized": True,
            "resources": {"remote_seconds": 1, "max_concurrent_runs": 1},
        }
        self.assertTrue(MODULE.resolve(base)["execution"]["remote_execution_allowed"])
        for field in ("remote_seconds", "max_concurrent_runs"):
            config = dict(base)
            config["resources"] = dict(base["resources"])
            config["resources"][field] = 0
            execution = MODULE.resolve(config)["execution"]
            self.assertFalse(execution["remote_execution_allowed"])
        unauthorized = dict(base)
        unauthorized["simulation_authorized"] = False
        self.assertFalse(MODULE.resolve(unauthorized)["execution"]["remote_execution_allowed"])

    def test_replay_always_forbids_remote_execution(self):
        result = MODULE.resolve({
            "mode": "replay",
            "simulation_authorized": True,
            "resources": {"remote_seconds": 999, "max_concurrent_runs": 99},
        })
        self.assertFalse(result["execution"]["remote_execution_allowed"])
        self.assertEqual(result["execution"]["reason"], "replay_mode_forbids_remote_execution")

    def test_behavioral_branches(self):
        auto = MODULE.resolve({"behavioral": "auto"})["behavioral"]
        self.assertEqual(auto["state"], "deferred")
        self.assertFalse(auto["selected"])
        self.assertFalse(auto["executes_va"])
        self.assertIn("this round does not execute Verilog-A", auto["message"])

        off = MODULE.resolve({"behavioral": "off"})["behavioral"]
        self.assertEqual(off["state"], "disabled")
        self.assertFalse(off["executes_va"])

        with self.assertRaisesRegex(MODULE.UnsupportedBehavioralError, "unsupported"):
            MODULE.resolve({"behavioral": "on"})

    def test_unknown_fields_and_strict_types_are_rejected(self):
        with self.assertRaisesRegex(MODULE.WorkflowConfigError, "unknown configuration field"):
            MODULE.resolve({"unexpected": 1})
        with self.assertRaisesRegex(MODULE.WorkflowConfigError, "unknown resources field"):
            MODULE.resolve({"resources": {"remote_seconds": 1, "extra": 0}})
        with self.assertRaises(MODULE.WorkflowConfigError):
            MODULE.resolve({"resources": {"remote_seconds": True}})
        with self.assertRaises(MODULE.WorkflowConfigError):
            MODULE.resolve({"resources": {"max_concurrent_runs": 1.0}})
        with self.assertRaises(MODULE.WorkflowConfigError):
            MODULE.resolve({"simulation_authorized": 1})
        with self.assertRaises(MODULE.WorkflowConfigError):
            MODULE.resolve({"workflow_effort": "fast"})
        with self.assertRaises(MODULE.WorkflowConfigError):
            MODULE.resolve({"repository_root": Path(".")})

    def test_cli_writes_json_and_refuses_overwrite(self):
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            config = directory / "config.json"
            output = directory / "plan.json"
            config.write_text(json.dumps({"module_scale": "large"}), encoding="utf-8")
            command = [sys.executable, str(SCRIPT), str(config), "--out", str(output)]
            first = subprocess.run(command, capture_output=True, text=True, check=False)
            self.assertEqual(first.returncode, 0, first.stderr)
            plan = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(plan["effective_config"]["module_scale"], "large")
            original = output.read_text(encoding="utf-8")

            second = subprocess.run(command, capture_output=True, text=True, check=False)
            self.assertNotEqual(second.returncode, 0)
            self.assertIn("refusing to overwrite", second.stderr)
            self.assertEqual(output.read_text(encoding="utf-8"), original)


if __name__ == "__main__":
    unittest.main()
