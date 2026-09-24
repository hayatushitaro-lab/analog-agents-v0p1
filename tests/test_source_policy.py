"""Independent source-priority contract; no project inputs or gold data."""
import copy
import unittest
import tempfile
import hashlib
import json
import io
from pathlib import Path
from contextlib import redirect_stdout

from analog_evidence.parser import parse
from analog_evidence.evidence import build_snapshot, validate, digest
from analog_evidence.acceptance import acceptance, source_status
from analog_evidence.cli import main


class SourcePolicyTests(unittest.TestCase):
    def test_cli_omitted_cdl_auxiliary_failure_and_primary_failure(self):
        cases=[(False,False,True),(True,False,True),(False,True,False)]
        for with_aux,bad_primary,expected in cases:
            with self.subTest(with_aux=with_aux,bad_primary=bad_primary), tempfile.TemporaryDirectory() as temp:
                root=Path(temp)
                s='subckt root a b\n'+('unsupported syntax\n' if bad_primary else 'Q (a b b) opaque m=3\n')+'ends root\n'
                contents={'P':s}
                if with_aux:contents['X']='.SUBCKT root a b\nQ a b b opaque\n.ENDS\n'
                entries=[]
                for aid,content in contents.items():
                    path=root/(aid+'.net');path.write_bytes(content.encode())
                    entries.append({'id':aid,'role':'design','dialect':'spectre' if aid=='P' else 'cdl','path':path.name,'sha256':hashlib.sha256(content.encode()).hexdigest()})
                manifest={'project_id':'synthetic','dut_definition':'root','structural_baseline':'P',
                          'inputs':entries,'simulation_policy':'disabled','model_policy':'metadata_only'}
                if with_aux:manifest['comparison_artifacts']=['X']
                mp=root/'manifest.json';mp.write_text(json.dumps(manifest))
                with redirect_stdout(io.StringIO()):
                    rc=main(['run','--manifest',str(mp),'--root',temp,'--output',str(root/'run')])
                self.assertEqual(rc,0 if expected else 1)
                latest=json.loads((root/'run/latest.json').read_text())
                self.assertEqual(latest['accepted'],expected)
                self.assertTrue(latest['structurally_valid'])
                self.assertNotIn('valid',latest)
                evidence=root/'run'/latest['path']/'design_evidence.json'
                with redirect_stdout(io.StringIO()):
                    rc=main(['validate','--manifest',str(mp),'--root',temp,'--evidence',str(evidence)])
                self.assertEqual(rc,0 if expected else 1)

    def snapshot(self, primary, auxiliary=None, top='root'):
        sources={'P': primary.encode()}
        views=[parse(sources['P'], 'P', 'spectre')]
        if auxiliary is not None:
            sources['X']=auxiliary.encode()
            views.append(parse(sources['X'], 'X', 'cdl'))
        return build_snapshot(views, top, 'synthetic', [], sources, {}), sources

    def test_scs_only_passes_without_comparison(self):
        ir, src=self.snapshot('subckt root a b\nQ (a b b) opaque m=3\nends root\n')
        self.assertEqual(validate(ir, src), [])
        self.assertEqual(acceptance(ir, [])['status'], 'passed_static')
        self.assertEqual(ir['scope']['comparison_refs'], [])
        self.assertEqual(ir['scope']['auxiliary_status'], 'not_requested')
        self.assertEqual(ir['scope']['stages']['model_binding'], 'partial')

    def test_auxiliary_error_does_not_hide_or_block_primary(self):
        s='subckt root a b\nQ (a b b) opaque m=3\nends root\n'
        c='.SUBCKT root a b\nQ1 a b b opaque m=3\n.ENDS\n'
        ir,src=self.snapshot(s,c)
        self.assertEqual(validate(ir, src), [])
        self.assertEqual(acceptance(ir, [])['status'], 'passed_static')
        self.assertEqual(ir['scope']['stages']['syntax'], 'complete')
        self.assertEqual(ir['scope']['auxiliary_status'], 'partial')
        self.assertTrue(any(d['severity']=='error' for d in ir['diagnostics']))
        self.assertEqual(source_status(ir)[1]['syntax'], 'partial')

    def test_primary_error_still_blocks_with_good_auxiliary(self):
        ir,src=self.snapshot('subckt root a\nunsupported syntax\nends root\n', '.SUBCKT root a\n.ENDS\n')
        self.assertEqual(validate(ir, src), [])
        self.assertEqual(acceptance(ir, [])['status'], 'blocked_primary')

    def test_missing_root_and_arity_block_primary(self):
        for s in ('subckt another a\nends another\n',
                  'subckt child a b\nends child\nsubckt root a\nI (a) child\nends root\n'):
            ir,src=self.snapshot(s)
            self.assertEqual(acceptance(ir, validate(ir,src))['status'], 'blocked_primary')

    def test_invalid_evidence_never_passes(self):
        ir,_=self.snapshot('subckt root a\nends root\n')
        self.assertEqual(acceptance(ir, ['tampered'])['status'], 'invalid_evidence')

    def test_tampered_priority_status_rejected(self):
        ir,src=self.snapshot('subckt root a\nunsupported syntax\nends root\n')
        bad=copy.deepcopy(ir)
        bad['scope']['stages']['syntax']='complete'
        bad['scope']['stages']['design_elaboration']='complete'
        bad['snapshot_id']='pending';bad['snapshot_id']=digest(bad)
        self.assertTrue(validate(bad,src))

    def test_auxiliary_does_not_replace_primary_values(self):
        s='subckt root a b\nR (a b) opaque w=3u\nends root\n'
        single,_=self.snapshot(s)
        dual,_=self.snapshot(s,'.SUBCKT root a b\nR a b $[opaque] w=9u\n.ENDS\n')
        def values(ir):
            return [(c['subject_ref'], c['predicate'], c['value'], c['kind'])
                    for c in ir['claims'] if c['subject_ref'].startswith('P:')]
        self.assertEqual(values(single), values(dual))

    def test_skipped_auxiliary_comparison_is_visible(self):
        ir,src=self.snapshot('subckt root a\\+ b\nR (a\\+ b) opaque\nends root\n',
                            '.SUBCKT root a+ b\nR a+ b $[opaque]\n.ENDS\n')
        self.assertEqual(validate(ir,src), [])
        self.assertEqual(acceptance(ir, [])['status'], 'passed_static')
        self.assertEqual(ir['scope']['auxiliary_status'], 'partial')
        coverage=ir['scope']['comparison_coverage'][0]
        self.assertEqual(len(coverage['uncompared_primary_instance_refs']),1)
        self.assertEqual(len(coverage['uncompared_auxiliary_instance_refs']),1)
