"""Production entry counterexamples with temporary synthetic evidence only."""
import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from test_skill_handoff import make_bundle, CHECKER
from test_recovery_quality import load

f = load('bounded_fill', 'skills/analog-recovery-report/scripts/fill_template.py')


class ProductionReviewGateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.bundle_dir = self.root/'bundle'; self.bundle_dir.mkdir()
        self.content = self.root/'content.json'
        self.quality = self.root/'quality.json'
        self.b = make_bundle(self.root)
        self.b['manifest']['schema_version'] = '0.2'
        self.b['manifest']['artifacts'][2]['input_refs'] = ['a_net']
        # No measured metrics: production must allow a truthful partial document.
        for m in self.b['metrics']['metrics']:
            m.update(samples=[], status='unmeasured', reason='not measured',
                     impact='unknown performance', next_action='collect evidence')
        self.b['coverage']['items'][0].update(status='partial', reason='not measured',
            impact='limited', next_action='collect evidence')
        self.data = json.loads(json.dumps(f.example_payload()).replace('"synthetic"', '"c_direct"'))
        self.data['project_id'] = 'gate-fixture'
        self.data['expected_ports'] = ['vin', 'vout']
        row = self.data['sections']['1.4.1']['rows'][0]
        row['ports'] = ['vin', 'vout']
        self.data['sections']['1.3']['rows'][0].update(metric_ref='m_sim', refs=['m_sim'])
        self.data['evidence_ids'] = ['c_direct', 'm_sim']
        self.data['verification'][0]['metric_refs'] = ['m_sim']
        self.caption = 'Synthetic caption: no electrical result established'
        # The caption tests only inspect/preflight; no image or project report generated.
        self.image = self.root/'fixture.png'; self.image.write_bytes(b'fixture')
        self.data['verification'][0]['figures'] = [dict(path=str(self.image),
            caption=self.caption, kind='concept', refs=['c_direct'])]
        self.q = dict(schema_version='1', artifacts=[{k:self.b['manifest']['artifacts'][0][k]
            for k in ('id','path','sha256')}], fixtures=[], calculations=[],
            metrics=[], runs=[], claims=[dict(id='c_direct', status='supported', parents=[],
                run_refs=[], qualifier='')],
            uses=[dict(claim_ref='c_direct', text=self.caption, qualification='supported')])
        self.save_inputs(); self.freeze()

    def write(self, path, value):
        path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf8')

    def save_inputs(self):
        self.write(self.content, self.data)
        for name in CHECKER.FILES:
            self.write(self.bundle_dir/(name+'.json'), self.b[name])

    def freeze(self):
        digest = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
        self.q['report_snapshot'] = dict(content_sha256=digest(self.content),
            bundle_sha256={n:digest(self.bundle_dir/(n+'.json')) for n in CHECKER.FILES})
        self.write(self.quality, self.q)

    def preflight(self):
        return f.production_preflight(self.data, self.content, self.bundle_dir, self.root, self.quality)

    def cli(self, *args):
        return subprocess.run([sys.executable, '-X', 'utf8', f.__file__, '--content', str(self.content),
            '--bundle', str(self.bundle_dir), '--source-root', str(self.root),
            '--quality-packet', str(self.quality), *args], capture_output=True, text=True, encoding='utf8')

    def test_verification_caption_and_existing_text_locations(self):
        self.assertEqual(self.preflight(), [])
        del self.data['verification'][0]['figures']
        for location in ('paragraph', 'section_caption', 'label'):
            with self.subTest(location=location):
                if location == 'paragraph':
                    self.data['sections']['1.7.1']['paragraphs'] = [dict(text=self.caption, refs=['c_direct'])]
                elif location == 'section_caption':
                    self.data['sections']['1.7.1']['paragraphs'] = []
                    self.data['sections']['1.7.1']['figures'] = [dict(caption=self.caption)]
                else:
                    self.data['sections']['1.7.1']['figures'] = []
                    self.data['verification'][0]['labels'][f.LABELS[0]] = self.caption
                self.save_inputs(); self.freeze()
                self.assertEqual(self.preflight(), [])

    def test_obsolete_use_and_unknown_claim_are_rejected(self):
        self.q['uses'][0]['text'] = 'obsolete caption'
        self.write(self.quality, self.q)
        self.assertIn('quality use is not current report text', str(self.preflight()))
        self.q['uses'][0].update(text=self.caption, claim_ref='ghost')
        self.write(self.quality, self.q)
        self.assertTrue(self.preflight())

    def test_caption_change_even_with_duplicate_text_breaks_snapshot(self):
        self.data['sections']['1.7.1']['paragraphs'] = [dict(text=self.caption, refs=['c_direct'])]
        self.data['verification'][0]['figures'][0]['caption'] = 'changed caption'
        self.save_inputs()
        errors = self.preflight()
        self.assertNotIn('quality use is not current report text', str(errors))
        self.assertIn('quality review content snapshot missing/changed', errors)

    def test_8a_bundle_mutation_breaks_snapshot(self):
        self.b['design_evidence']['claims'][0]['critical_review_required'] = True
        self.save_inputs()
        self.assertIn('quality review bundle snapshot missing/changed: design_evidence', self.preflight())

    def test_8b_rehashed_stale_review_semantics_are_not_proven(self):
        for c in self.b['design_evidence']['claims']:
            c['critical_review_required'] = c['id'] == 'c_direct'
        self.b['review']['checks'][0]['subject_refs'].append('c_direct')
        self.save_inputs(); self.freeze()
        previous_review = (self.bundle_dir/'review.json').read_bytes()
        self.b['design_evidence']['claims'][0]['statement'] = 'Opposite technical assertion; old review retained'
        self.save_inputs(); self.freeze()  # File identity updated, no semantic re-review.
        self.assertEqual((self.bundle_dir/'review.json').read_bytes(), previous_review)
        self.assertEqual(self.preflight(), [])
        r = CHECKER.validate(self.b, self.root)
        self.assertTrue(r['valid'], r)
        self.assertEqual(r['key_claim_review']['status'], 'covered')
        self.assertIn('semantic freshness', str(r['limits']))

    def test_production_check_exposes_partial_and_rejects_invalid(self):
        proc = self.cli('--check')
        self.assertEqual(proc.returncode, 0, proc.stdout+proc.stderr)
        result = json.loads(proc.stdout)
        self.assertEqual(result['bundle_delivery_status'], 'partial')
        self.assertEqual(result['key_claim_review']['status'], 'undeclared')
        self.b['design_evidence']['claims'] = []
        self.save_inputs(); self.freeze()
        out = self.root/'invalid.docx'
        proc = self.cli('--out', str(out))
        self.assertNotEqual(proc.returncode, 0)
        self.assertFalse(out.exists())
        self.assertIn('claims, requirements and modes must be nonempty', proc.stdout)

    def test_partial_build_receipt_and_legacy_production_rejection(self):
        del self.data['verification'][0]['figures']
        self.data['sections']['1.7.1']['paragraphs'] = [dict(text=self.caption, refs=['c_direct'])]
        self.save_inputs(); self.freeze()
        out = self.root/'synthetic.docx'
        proc = self.cli('--out', str(out))
        self.assertEqual(proc.returncode, 0, proc.stdout+proc.stderr)
        receipt = json.loads(out.with_suffix('.build.json').read_text(encoding='utf8'))
        self.assertEqual(receipt['bundle_delivery_status'], 'partial')
        self.assertEqual(receipt['key_claim_review']['status'], 'undeclared')
        self.b['manifest']['schema_version'] = '0.1'
        self.save_inputs(); self.freeze()
        proc = self.cli('--check')
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn('production requires a new 0.2 bundle', proc.stdout)


if __name__ == '__main__':
    unittest.main()
