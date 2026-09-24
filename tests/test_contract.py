"""Independent synthetic oracles. No project input or previous output imports."""
import copy
import json
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

from analog_evidence.parser import parse
from analog_evidence.numeric import scalar, NumericError
from analog_evidence.graph import elaborate, compare
from analog_evidence.admission import Admission, AdmissionError
from analog_evidence.metadata import scan_metadata, section_closure
from analog_evidence.evidence import build_snapshot, validate


def scs(text):
    return parse(text.encode(), "A", "spectre")


class ContractTests(unittest.TestCase):
    def test_F01_continuation_and_lossless(self):
        data = b'// note\r\nsubckt unit a b\r\n Ifoo (a b) custom \\\r\n w=(6u) m=2\r\nends unit\r\n'
        v = parse(data, 'A', 'spectre')
        self.assertEqual(len(v['instances']), 1)
        self.assertEqual(v['instances'][0]['parameters'][0]['raw_expr'], '(6u)')
        covered = sorted((f for s in v['source_spans'] for f in s['fragments']), key=lambda f: f['byte_start'])
        self.assertEqual(b''.join(data[f['byte_start']:f['byte_end']] for f in covered), data)

    def test_F02_order_and_F04_ground(self):
        v = scs('global 0\nsubckt leaf ctrl\\<1\\> ctrl\\<0\\> vss\nends leaf\nsubckt root p q g\nI (p q g) leaf\nends root\n')
        occ, diag = elaborate(v, 'root')
        child = next(o for o in occ if o['instance_path'] == '/root/I')
        self.assertEqual([b['formal_name'] for b in child['port_bindings']], ['ctrl<1>', 'ctrl<0>', 'vss'])
        self.assertEqual([b['actual_name'] for b in child['port_bindings']], ['p', 'q', 'g'])
        self.assertNotEqual(child['port_bindings'][2]['resolved_net'], 'A:global:0')
        self.assertFalse(diag)

    def test_F03_local_names_and_F09_overrides(self):
        v = scs('subckt leaf a\nparameters size=6u\nM0 (a net1) custom w=size\nends leaf\nsubckt root x y\nJ (x) leaf size=9u\nK (y) leaf\nends root\n')
        occ, _ = elaborate(v, 'root')
        leaves = [o for o in occ if o['instance_path'].endswith('/M0')]
        self.assertEqual(len(leaves), 2)
        self.assertNotEqual(leaves[0]['terminal_bindings'][1]['resolved_net'], leaves[1]['terminal_bindings'][1]['resolved_net'])
        self.assertEqual([o['parameter_environment']['w'] for o in leaves], ['0.000009', '0.000006'])

    def test_F05_no_prefix_device_guess(self):
        v = scs('subckt root a b c\nIfoo (a b c) custom_cap\nRfoo (a b c) child\nends root\nsubckt child a b c\nends child\n')
        self.assertEqual(v['instances'][0]['device_class'], 'unknown')
        self.assertTrue(v['instances'][1]['is_subckt_call'])

    def test_F06_cdl_extensions_F07_annotations(self):
        text = '*.SCALE METER\n.PARAM\n.SUBCKT top a b g\n*.PININFO a:I b:O g:B\nRz a b $SUB=g $[poly] $W=6u $L=27u r=9K\nXz a b g /\n+ child\n.ENDS\n.SUBCKT child a b g\n.ENDS\n'
        v = parse(text.encode(), 'B', 'cdl')
        r = v['instances'][0]
        self.assertEqual(r['master_ref_or_name'], 'poly')
        self.assertEqual(len(r['ordered_terminals']), 3)
        self.assertEqual(r['extensions']['$SUB'], 'g')
        self.assertEqual(r['parameters'][0]['raw_key'], '$W')
        self.assertEqual(v['instances'][1]['master_ref_or_name'], 'child')
        self.assertEqual(v['definitions'][0]['formal_ports'][0]['declared_direction'], 'I')
        self.assertTrue(any(s['kind'] == 'annotation' for s in v['statements']))

    def test_F08_numbers_and_safe_expression(self):
        for expr in ['6u', '6e-6', '(6u)', '((6u))']:
            self.assertEqual(scalar(expr, 'spectre'), Decimal('0.000006'))
        self.assertEqual(scalar('base*3+1u', 'spectre', {'base': '2u'}), Decimal('0.000007'))
        for expr in ['unknown(1)', '__import__("os")', '1/0', 'NaN', 'base', '1e999999']:
            with self.assertRaises(NumericError): scalar(expr, 'spectre')
        with self.assertRaises(NumericError): scalar('a', 'spectre', {'a': 'b', 'b': 'a'})

    def test_F10_no_effective_width(self):
        v = scs('subckt root a b\nM (a b) custom w=6u m=3 nf=2 par=4\nends root\n')
        self.assertEqual([p['canonical_key'] for p in v['instances'][0]['parameters']], ['w', 'm', 'nf', 'par'])
        self.assertTrue(all(p['semantic_contract_ref'] is None for p in v['instances'][0]['parameters']))

    def test_F11_sections(self):
        m = scan_metadata(b'library L\nsection A\ninclude "x.scs" section=B\nendsection A\nsection B\nmodel dev bsim4\nendsection B\nendlibrary L\n', 'M', {'dev'})
        result = section_closure({'M': m}, 'M', 'A', lambda aid, p: 'M')
        self.assertFalse(result['cycles'])
        self.assertEqual({tuple(n) for n in result['nodes']}, {('M','A'),('M','B')})
        cyclic = scan_metadata(b'section A\ninclude "x.scs" section=B\nendsection A\nsection B\ninclude "x.scs" section=A\nendsection B\n', 'M', set())
        self.assertTrue(section_closure({'M': cyclic}, 'M', 'A', lambda aid,p:'M')['cycles'])

    def test_F12_admission_denies_before_read(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as d:
            root = Path(d); allowed = root/'a.scs'; forbidden = root/'secret.scs'
            allowed.write_bytes(b'global 0\n'); forbidden.write_text('CANARY_DO_NOT_READ')
            import hashlib
            gate = Admission(root, [{'id':'A','path':'a.scs','role':'design','sha256':hashlib.sha256(allowed.read_bytes()).hexdigest()}])
            self.assertEqual(gate.read('A'), b'global 0\n')
            with self.assertRaises(AdmissionError): gate.read('secret.scs')
            self.assertIsNone(gate.resolve('A','secret.scs'))
            allowed.write_bytes(b'changed')
            with self.assertRaises(AdmissionError): gate.read('A')

    def test_F13_fail_closed(self):
        for text in ['subckt root a\nBAD THING\n', 'subckt root a\nI (a) child\nends root\nsubckt child a b\nends child\n', 'simulator lang=spice\nsubckt root a\nends root\n']:
            v = scs(text); _, d = elaborate(v, 'root')
            self.assertTrue(any(x['severity']=='error' for x in v['diagnostics']+d))

    def test_F14_metadata_opaque_F16_case(self):
        m = scan_metadata(b'simulator lang=spectre insensitive=yes\nsection A\nsubckt cell (1 2 3)\nsecret_equation=938\nends cell\nendsection A\n', 'M', {'cell'})
        self.assertNotIn('secret_equation', json.dumps(m))
        self.assertEqual(m['declarations'][0]['formal_ports'], ['1','2','3'])
        v = scs('simulator lang=spectre insensitive=yes\nsubckt root A a\nends root\n')
        self.assertTrue(any(d['code']=='NAME_POLICY_UNRESOLVED' for d in v['diagnostics']))
        self.assertEqual([p['raw_name'] for p in v['definitions'][0]['formal_ports']], ['A','a'])

    def test_F15_comparison_no_equivalence(self):
        a = scs('subckt root a b g\nR (a b g) poly l=9u s=3\nends root\n')
        b = parse(b'.SUBCKT root a b g\nRR a b $SUB=g $[poly] $L=27u s=1 r=8K\n.ENDS\n','B','cdl')
        result = compare(a,b)
        row = next(r for r in result if r['comparison_scope']=='instance_parameters')
        self.assertEqual(row['status'], 'representation_difference')
        self.assertEqual({d['parameter'] for d in row['differences']}, {'l','s','r'})

    def test_F17_F18_F20_evidence_rejections(self):
        data = b'subckt root a b\nM (a b) unknown w=6u\nends root\n'
        v = parse(data,'A','spectre')
        ir = build_snapshot([v], 'root', 'test', [], {'A':data}, identity={'code_sha256':'a'*64,'schema_sha256':'b'*64,'manifest_sha256':'c'*64})
        self.assertEqual(validate(ir, {'A':data}), [])
        direct = next(i for i,c in enumerate(ir['claims']) if c['kind']=='DIRECT' and c['predicate'].startswith('declared_parameter'))
        for mutation in ['dangling','simulated','literal','span','template','cycle']:
            bad = copy.deepcopy(ir); c=bad['claims'][direct]
            if mutation=='dangling': c['support_refs']=['missing']
            if mutation=='simulated': c['kind']='SIMULATED'
            if mutation=='literal': c['value']['text']='77u'
            if mutation=='span': bad['source_spans'][0]['fragments'][0]['byte_end']=99999
            if mutation=='template': bad['artifacts'][0]['role']='template_example'
            if mutation=='cycle': c['support_refs']=[c['id']]
            self.assertTrue(validate(bad, {'A':data}), mutation)

    def test_F19_snapshot_identity(self):
        snapshots=[]
        for w in ['6u','7u']:
            data=f'subckt root a b\nM (a b) unknown w={w}\nends root\n'.encode()
            snapshots.append(build_snapshot([parse(data,'A','spectre')], 'root','test',[],{'A':data},identity={})['snapshot_id'])
        self.assertNotEqual(*snapshots)


if __name__ == '__main__': unittest.main()
