"""Offline production setup tests: explicit restrictions, real paths, no transport."""
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import yaml

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / 'skills/analog-recovery/scripts/resolve_workflow.py'
spec = importlib.util.spec_from_file_location('recovery_run_setup', SCRIPT)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
review_spec = importlib.util.spec_from_file_location('recovery_setup_review', SCRIPT.with_name('recovery_review.py'))
review = importlib.util.module_from_spec(review_spec)
review_spec.loader.exec_module(review)


class RunSetupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.repo = Path(self.temp.name).resolve()
        for path in ('config', 'tools', 'wiki', '.venv/Scripts', 'skills/analog-recovery/_local'):
            (self.repo / path).mkdir(parents=True, exist_ok=True)
        (self.repo / '.venv/Scripts/python.exe').write_bytes(b'not executed')
        (self.repo / 'wiki/source.scs').write_text('subckt fixed a b\nends fixed\n')
        (self.repo / 'tools/review_bridge.py').write_text(
            'from pathlib import Path\nimport yaml\n'
            'def load_config(path): return yaml.safe_load(Path(path).read_text())\n'
            'def call_reviewer(*args): raise AssertionError("setup must not send")\n')
        self.site_path = self.repo / 'skills/analog-recovery/_local/site.json'
        self.site = dict(repository_root=str(self.repo), project_root=str(self.repo),
                         python=str(self.repo / '.venv/Scripts/python.exe'), reviewers_config='config/reviewers.yml',
                         max_calls_per_run=12, max_rounds=3,
                         report_defaults=dict(mode='live', simulation_authorized=True,
                                              external_review_authorized=True, knowledge_write_policy='approval'))
        self.save_site()
        self.reviewers(3)
        (self.repo / 'config/effort.yml').write_text('default_effort: standard\noverrides:\n  bandgap: intensive\n')

    def save_site(self):
        self.site_path.write_text(json.dumps(self.site), encoding='utf-8')

    def reviewers(self, count):
        data = {'reviewers': {f'r{i}': dict(model=f'model-{i}', enabled=True, base_url='https://example.invalid',
                                           api_key='SECRET_SENTINEL_DO_NOT_PERSIST') for i in range(count)}}
        (self.repo / 'config/reviewers.yml').write_text(yaml.safe_dump(data), encoding='utf-8')

    def prepare(self, name='WORK_TEST', overrides=None, **kwargs):
        return m.prepare_run(self.repo, self.repo / name, overrides, **kwargs)

    def test_two_projects_bind_current_runs_and_no_transport_or_wiki_write(self):
        original = self.site_path.read_bytes()
        source = (self.repo / 'wiki/source.scs').read_bytes()
        for name in ('WORK_ONE', 'WORK_TWO'):
            plan = self.prepare(name)
            self.assertTrue(plan['execution']['remote_execution_allowed'])
            self.assertEqual(plan['review_transport']['reviewer_batches'], [['r0']])
            self.assertEqual(plan['review_transport']['status'], 'configured_not_executed')
            self.assertTrue(plan['closeout']['case_archive_required'])
            self.assertEqual(plan['closeout']['status'], 'pending')
            self.assertFalse(plan['closeout']['new_project_convergence'])
            self.assertEqual(plan['preparation']['external_requests_sent'], 0)
            self.assertEqual(plan['preparation']['simulations_run'], 0)
            site = review.local_site(self.repo / name / 'site.json')
            self.assertEqual(site['project_root'], str(self.repo))
            self.assertEqual(site['run_dir'], str(self.repo / name))
            self.assertEqual(site['max_calls_per_run'], 6)
            for path in (self.repo / name).glob('*.json'):
                self.assertNotIn('SECRET_SENTINEL', path.read_text(encoding='utf-8'))
        self.assertEqual(original, self.site_path.read_bytes())
        self.assertEqual(source, (self.repo / 'wiki/source.scs').read_bytes())
        self.assertEqual(len(list((self.repo / 'wiki').iterdir())), 1)

    def test_tier_precedence_and_distinct_role_policies(self):
        block = self.prepare('WORK_BLOCK', block='bandgap')
        self.assertEqual(block['effort']['level'], 'intensive')
        self.assertEqual(block['preparation']['effort_source'], 'block_override')
        roles = []
        for tier, count, archive in [('lite', 1, False), ('standard', 1, True), ('intensive', 2, True), ('exhaustive', 3, True)]:
            plan = self.prepare('WORK_' + tier, {'workflow_effort': tier}, block='bandgap')
            self.assertEqual(plan['preparation']['effort_source'], 'task_override')
            self.assertEqual(len(plan['review_transport']['reviewers']), count)
            self.assertEqual(plan['closeout']['case_archive_required'], archive)
            self.assertTrue(plan['role_policy']['EDITOR']['render_and_trace_required'])
            self.assertTrue(plan['role_policy']['REVIEWER']['critical_review_required'])
            roles.append(plan['role_policy']['VERIFIER']['coverage'])
        self.assertEqual(len(set(roles)), 4)
        exhaustive = json.loads((self.repo / 'WORK_exhaustive/workflow.resolved.json').read_text())
        self.assertEqual(exhaustive['review_transport']['reviewer_batches'], [['r0', 'r1'], ['r2']])

    def test_restrictions_override_live_project_policy(self):
        plan = self.prepare(overrides=dict(mode='replay', simulation_authorized=False, external_review_authorized=False,
                                           knowledge_write_policy='read_only', single_agent=True))
        self.assertFalse(plan['execution']['remote_execution_allowed'])
        self.assertEqual(plan['review_transport']['status'], 'disabled_by_task')
        self.assertEqual(plan['review_transport']['max_calls_per_run'], 0)
        self.assertEqual(plan['closeout']['write_policy'], 'read_only')
        self.assertTrue(plan['dispatch']['single_agent'])
        self.assertTrue(plan['closeout']['case_archive_required'])  # prepare only, no mutation
        for intent in ('static', 'replay'):
            plan = self.prepare('WORK_' + intent, intent=intent)
            self.assertFalse(plan['execution']['remote_execution_allowed'])
            with self.assertRaises(m.WorkflowConfigError):
                self.prepare('WORK_BAD_' + intent, {'mode': 'live'}, intent=intent)

    def test_zero_budgets_preserved_and_missing_reviewers_are_explicit(self):
        self.site['max_calls_per_run'] = 0
        self.save_site()
        plan = self.prepare(overrides={'resources': {'remote_seconds': 0}})
        self.assertFalse(plan['execution']['remote_execution_allowed'])
        self.assertEqual(plan['review_transport']['status'], 'blocked_configuration')
        self.assertIn('zero_review_budget', plan['review_transport']['issues'])
        self.site['max_calls_per_run'] = 12
        self.save_site()
        self.reviewers(1)
        plan = self.prepare('WORK_FEWER', {'workflow_effort': 'intensive'})
        self.assertIn('fewer_configured_reviewers_than_effort_requests', plan['review_transport']['issues'])
        self.reviewers(0)
        plan = self.prepare('WORK_MISSING')
        self.assertEqual(plan['review_transport']['status'], 'blocked_configuration')

    def test_reject_old_binding_escape_and_replay_overwrite(self):
        self.site['project_root'] = str(self.repo / 'WORK_OLD')
        self.save_site()
        with self.assertRaisesRegex(m.WorkflowConfigError, 'old WORK'):
            self.prepare()
        self.assertFalse((self.repo / 'WORK_TEST').exists())
        self.site['project_root'] = str(self.repo)
        self.save_site()
        with self.assertRaises(m.WorkflowConfigError):
            m.prepare_run(self.repo, self.repo.parent / 'outside-recovery-test')
        self.prepare()
        original = (self.repo / 'WORK_TEST/workflow.json').read_bytes()
        with self.assertRaisesRegex(m.WorkflowConfigError, 'overwrite'):
            self.prepare()
        self.assertEqual(original, (self.repo / 'WORK_TEST/workflow.json').read_bytes())

    def test_packet_can_read_wiki_and_run_evidence_but_not_another_run_output(self):
        self.prepare()
        run = self.repo / 'WORK_TEST'
        (run / 'claims.txt').write_text('fixed connection observation')
        files = [dict(path='wiki/source.scs', role='netlist', sha256=review.sha((self.repo / 'wiki/source.scs').read_bytes())),
                 dict(path='WORK_TEST/claims.txt', role='claims', sha256=review.sha((run / 'claims.txt').read_bytes()))]
        packet = dict(source_root=str(self.repo), run_dir=str(run), stage='pre', round=1, files=files)
        packet_path = run / 'packet.json'
        packet_path.write_text(json.dumps(packet))
        args = ['recovery_review', str(packet_path), '--site', str(run / 'site.json'), '--out', str(run / 'review')]
        with patch('sys.argv', args):
            review.main()
        receipt = json.loads((run / 'review/request.json').read_text())
        self.assertFalse(receipt['sent'])
        self.assertEqual([r['name'] for r in receipt['reviewers']], ['r0'])
        self.assertFalse((run / 'external_review_budget.json').exists())
        packet['reviewers'] = ['r1']
        packet_path.write_text(json.dumps(packet))
        args[-1] = str(run / 'wrong-reviewer')
        with patch('sys.argv', args), self.assertRaisesRegex(review.ReviewContractError, 'frozen effort'):
            review.main()
        packet.pop('reviewers')
        (self.repo / 'WORK_OTHER').mkdir()
        packet['run_dir'] = str(self.repo / 'WORK_OTHER')
        packet_path.write_text(json.dumps(packet))
        args[-1] = str(self.repo / 'WORK_OTHER/review')
        with patch('sys.argv', args), self.assertRaisesRegex(review.ReviewContractError, 'frozen site run'):
            review.main()

    def test_cli_read_only_preparation(self):
        cmd = [sys.executable, str(SCRIPT), '--repo', str(self.repo), '--run-dir', 'WORK_CLI', '--read-only', '--effort', 'lite']
        result = subprocess.run(cmd, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        output = json.loads(result.stdout)
        self.assertFalse(output['executed'])
        self.assertFalse(output['execution']['remote_execution_allowed'])
        self.assertFalse(output['archive_required'])


if __name__ == '__main__':
    unittest.main()
