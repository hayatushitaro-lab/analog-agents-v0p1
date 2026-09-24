import importlib.util
import json
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path
from types import SimpleNamespace

P=Path(__file__).resolve().parents[1]/'skills/analog-recovery/scripts/recovery_review.py'
s=importlib.util.spec_from_file_location('recovery_review',P);m=importlib.util.module_from_spec(s);s.loader.exec_module(m)

class ReviewTests(unittest.TestCase):
    def test_site_cannot_bind_old_copy_outside_workspace(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);p=root/'site.json'
            p.write_text(json.dumps(dict(repository_root=d,project_root=d,reviewers_config='../old-copy/config.yml')))
            with self.assertRaises(ValueError):m.local_site(p)
    def test_empty_pass_is_not_a_review(self):
        with self.assertRaises(ValueError):m.parse_response('{"verdict":"pass","findings":[],"limitations":[]}')
    def test_model_card_cannot_be_tagged_metadata(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'model.scs';p.write_text('model nmos bsim4 vth0=0.4')
            packet=dict(source_root=d,stage='pre',round=1,files=[dict(path=p.name,role='model_metadata',sha256=m.sha(p.read_bytes()))])
            with self.assertRaises(ValueError):m.assemble(packet)
    def test_prior_verdict_cannot_be_sent_as_open_findings(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'review.json';p.write_text('{"verdict":"pass","findings":[]}')
            packet=dict(source_root=d,stage='post',round=2,files=[dict(path=p.name,role='open_findings',sha256=m.sha(p.read_bytes()))])
            with self.assertRaises(ValueError):m.assemble(packet)
    def test_post_metric_review_requires_data_log_and_calculation(self):
        p=dict(questions=[dict(id='metric',kind='measurement',source_paths=['metrics.json'])])
        with self.assertRaises(ValueError):m.validate_scope(p,[dict(path='metrics.json',role='claims')])
    def test_pass_cannot_cite_a_different_questions_source(self):
        x=dict(verdict='pass',findings=[],limitations=[],checks=[dict(question_id='q',status='checked',source_paths=['other'],reason='measured')])
        with self.assertRaises(ValueError):m.parse_response(json.dumps(x),[dict(id='q',source_paths=['raw'])],[dict(path='raw'),dict(path='other')])
    def test_nonempty_scoped_pass_is_accepted(self):
        x=dict(verdict='pass',findings=[],limitations=[],checks=[dict(question_id='q',status='checked',source_paths=['raw'],reason='Input/output amplitudes give 60 dB at this sampled point.')])
        self.assertEqual(m.parse_response(json.dumps(x),[dict(id='q',source_paths=['raw'])],[dict(path='raw')])['verdict'],'pass')
    def test_extracted_metadata_is_accepted(self):
        value=dict(schema_version='metadata-1',models=[dict(name='device_x',device_type='mos',pins=['d','g','s','b'],source_sha256='a'*64,source_locator='model.scs:4')])
        m.validate_special_source('model_metadata',json.dumps(value))
    def test_packet_hash_and_boundary(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);p=root/'c.scs';p.write_text('R0 (a b) resistor r=1',encoding='utf-8')
            q={'source_root':d,'stage':'pre','round':1,'files':[{'path':'c.scs','role':'netlist','sha256':m.sha(p.read_bytes())}]}
            text,records=m.assemble(q);self.assertIn('R0 (a b)',text);self.assertEqual(len(records),1)
            p.write_text('changed',encoding='utf-8')
            with self.assertRaises(ValueError):m.assemble(q)
    def test_initial_review_rejects_previous_findings(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'x';p.write_bytes(b'previous pass')
            q={'source_root':d,'stage':'pre','round':1,'files':[{'path':'x','role':'open_findings','sha256':m.sha(p.read_bytes())}]}
            with self.assertRaises(ValueError):m.assemble(q)
    def test_input_outside_root_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)/'root';root.mkdir();p=Path(d)/'secret';p.write_bytes(b'no')
            q={'source_root':str(root),'stage':'post','round':1,'files':[{'path':str(p),'role':'log','sha256':m.sha(p.read_bytes())}]}
            with self.assertRaises(ValueError):m.assemble(q)
    def test_model_count_and_disabled(self):
        cfg={'model':'one','api_key':'fake','base_url':'https://invalid'}
        self.assertEqual(list(m.select_reviewers({'reviewers':{'a':cfg,'b':dict(cfg,enabled=False)}})),['a'])
        with self.assertRaises(ValueError):m.select_reviewers({'reviewers':{'a':dict(cfg,extra_body={'messages':[]})}})
    def test_contradictory_pass_rejected(self):
        f=dict(id='x',severity='blocking',owner='ANALYST',locator='x:1',reason='why',action='fix',closure_check='test')
        with self.assertRaises(ValueError):m.parse_response(json.dumps(dict(verdict='pass',findings=[f],limitations=[])))
    def test_routable_review_accepted(self):
        f=dict(id='x',severity='blocking',owner='VERIFIER',locator='x:1',reason='unit wrong',action='use current',closure_check='native type')
        self.assertEqual(m.parse_response(json.dumps(dict(verdict='revise',findings=[f],limitations=[])))['findings'][0]['owner'],'VERIFIER')
    def test_provider_error_not_persisted(self):
        bridge=SimpleNamespace(call_reviewer=lambda *args:dict(status='FAIL',error='credential=SECRET'))
        r=m.collect(bridge,{'a':{'model':'fake'}},'synthetic')
        self.assertNotIn('SECRET',json.dumps(r));self.assertEqual(r[0]['status'],'transport_failed')
    def test_bad_format_not_counted_as_success(self):
        bridge=SimpleNamespace(call_reviewer=lambda *args:dict(status='ok',response='PASS'))
        self.assertEqual(m.collect(bridge,{'a':{'model':'fake'}},'x')[0]['status'],'invalid_review_format')
    def test_send_reserves_budget_and_offline_never_calls(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);(root/'tools').mkdir();run=root/'run';run.mkdir()
            # Fake transport is local and cannot perform network IO.
            (root/'tools/review_bridge.py').write_text("def load_config(p):\n return {'reviewers':{'fake':{'model':'fake','base_url':'https://invalid','api_key':'fake'}}}\ndef call_reviewer(*a):\n raise RuntimeError('synthetic transport failure')\n",encoding='utf-8')
            src=root/'c.scs';src.write_bytes(b'R0 (a b) resistor r=1')
            packet=dict(source_root=d,run_dir=str(run),stage='pre',round=1,external_send_authorized=True,questions=[dict(id='ports',kind='topology',source_paths=['c.scs'])],files=[dict(path='c.scs',role='netlist',sha256=m.sha(src.read_bytes()))])
            site=dict(repository_root=d,project_root=d,reviewers_config='unused',max_calls_per_run=1,max_rounds=3)
            pp=root/'packet.json';sp=root/'site.json'
            pp.write_text(json.dumps(packet));sp.write_text(json.dumps(site))
            def execute(name,send):
                argv=['recovery_review',str(pp),'--site',str(sp),'--out',str(run/name)]+(['--send'] if send else [])
                with patch('sys.argv',argv):m.main()
            execute('offline',False);self.assertFalse((run/'external_review_budget.json').exists())
            execute('live',True);self.assertEqual(m.read(run/'external_review_budget.json')['calls_reserved'],1)
            self.assertEqual(m.read(run/'live/responses.json')['results'][0]['status'],'transport_failed')
            with self.assertRaises(ValueError):execute('exhausted',True)
            self.assertFalse((run/'external_review.lock').exists())

if __name__=='__main__':unittest.main()
