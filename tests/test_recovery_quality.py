"""Independent synthetic counterexamples; no project files or network access."""
import copy
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
def load(name, path):
    spec = importlib.util.spec_from_file_location(name, ROOT/path)
    mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
    return mod

q = load('quality_v09', 'skills/analog-recovery-evidence/scripts/check_quality.py')

def packet():
    return dict(schema_version='1', artifacts=[],
        fixtures=[dict(id='fixture', source_refs=[], dut_nodes=['supply','control'],
            edges=[['drive','control']], scans=[dict(id='enable',node='drive',kind='electrical',
                source_refs=[],observed_change=False)], domains=[])],
        calculations=[dict(id='ripple',kind='db_ratio',numerator=0.001,denominator=1,
            convention='rejection',reported=60,tolerance=1e-9,source_refs=[])],
        metrics=[dict(id='output',case_ids=['nom','low'],displayed_case_ids=['nom','low'],
            typical_case_id='nom',range_kind='observed')],
        runs=[dict(id='r1',status='valid')],
        claims=[dict(id='c1',status='supported',parents=[],run_refs=['r1'],qualifier='')],
        uses=[dict(claim_ref='c1',text='Synthetic supported observation.',qualification='supported')])

class QualityTests(unittest.TestCase):
    def result(self,p): return q.validate(p,Path('.'),verify_files=False)
    def test_correct_equal_output_is_not_failure(self): self.assertTrue(self.result(packet())['valid'])
    def test_disconnected_scan_fails(self):
        p=packet();p['fixtures'][0]['scans'][0]['node']='unwired'
        self.assertIn('unreachable_scan',str(self.result(p)['errors']))
    def test_environment_scan_needs_binding(self):
        p=packet();p['fixtures'][0]['scans'][0].update(kind='temperature',binding='simulator.temp')
        self.assertTrue(self.result(p)['valid'])
        del p['fixtures'][0]['scans'][0]['binding']
        self.assertFalse(self.result(p)['valid'])
    def test_voltage_domain_not_main_supply(self):
        p=packet();p['fixtures'][0]['domains']=[dict(id='ctrl',low=0,high=1.2,levels=[0,1.2])]
        self.assertTrue(self.result(p)['valid'])
        p['fixtures'][0]['domains'][0]['levels']=[0,5]
        self.assertIn('domain_level',str(self.result(p)['errors']))
    def test_psrr_sign_contradiction(self):
        p=packet();p['calculations'][0]['reported']=-60
        self.assertIn('calculation_mismatch',str(self.result(p)['errors']))
    def test_negative_transfer_gain_is_valid(self):
        p=packet();p['calculations'][0].update(convention='transfer',reported=-60)
        self.assertTrue(self.result(p)['valid'])
    def test_condition_omitted(self):
        p=packet();p['metrics'][0]['displayed_case_ids']=['nom']
        self.assertIn('condition_scope',str(self.result(p)['errors']))
    def test_test_boundary_not_typical(self):
        p=packet();p['metrics'][0]['range_kind']='lower_bound'
        self.assertIn('bound_not_typical',str(self.result(p)['errors']))
    def test_unmeasured_nominal_need_not_be_observed(self):
        p=packet();p['metrics'][0]['typical_case_id']=None
        self.assertTrue(self.result(p)['valid'])
    def test_diagnostic_propagates_transitively(self):
        p=packet();p['claims'][0].update(status='diagnostic',qualifier='Diagnostic only')
        p['claims'].append(dict(id='c2',status='supported',parents=['c1'],run_refs=[],qualifier=''))
        p['uses']=[dict(claim_ref='c2',text='Definitely works.',qualification='supported')]
        self.assertIn('qualification_lost',str(self.result(p)['errors']))
    def test_unknown_cannot_be_promoted(self):
        p=packet();p['claims'][0]['status']='unknown'
        self.assertFalse(self.result(p)['valid'])
    def test_invalid_run_cannot_hide_under_derived_parent(self):
        p=packet();p['runs'][0]['status']='excluded'
        self.assertFalse(self.result(p)['valid'])
    def test_cycles_are_reported(self):
        p=packet();p['claims'][0]['parents']=['c1']
        self.assertIn('lineage_cycle',str(self.result(p)['errors']))
    def test_missing_artifact_not_accepted_in_production(self):
        self.assertFalse(q.validate(packet(),Path('.'))['valid'])
    def test_unsupported_calculation_is_not_pass(self):
        p=packet();p['calculations'][0]['kind']='magical_causality'
        self.assertFalse(self.result(p)['valid'])

if __name__=='__main__': unittest.main()
