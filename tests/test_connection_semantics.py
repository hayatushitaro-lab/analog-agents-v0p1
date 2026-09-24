"""Endpoint evidence must not turn device incidence into a wire/control claim."""
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from analog_evidence.parser import parse
from analog_evidence.graph import elaborate

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT/'skills/analog-recovery-evidence/scripts'
def module(name):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS/(name+'.py'))
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value
scope = module('scope_packet')
quality = module('check_quality')

def fixture(aid='unit'):
    view = parse(b'''subckt portblock sense ref
Load (sense ref) resistor r=5k
ends portblock
subckt bench drive sense ref
Branch (drive sense) resistor r=7k
Target (sense ref) portblock
Unrelated (spare ref) capacitor c=2p
ends bench
''', aid, 'spectre')
    view['occurrences'], _ = elaborate(view, 'bench')
    return view

def quality_packet(edges):
    return {'schema_version':'1', 'artifacts':[], 'fixtures':[{
        'id':'f', 'source_refs':[], 'dut_nodes':['goal'], 'edges':edges,
        'scans':[{'id':'s','kind':'electrical','node':'drive','source_refs':[],
            'observed_change':False, 'target_nodes':['goal'],
            'measurement':{'node':'goal','unit':'V','event':'DC', 'threshold':'none',
                           'window':'DC','range':'unspecified','source_refs':['src']}}],
        'domains':[]}], 'calculations':[], 'metrics':[], 'runs':[], 'claims':[], 'uses':[]}

class ConnectionSemanticsTests(unittest.TestCase):
    def test_resistor_incidence_preserves_two_distinct_nets(self):
        packet = scope.make_target_packet(fixture(), '/bench', 'drive', 'sense')
        relation = packet['connection_assessment']
        self.assertEqual(relation['direct_local_net'], 'distinct')
        self.assertEqual(relation['shared_component_refs'], ['unit:def:bench:inst:Branch'])
        self.assertEqual(relation['global_device_path'], 'NOT_EVALUATED')
        self.assertEqual(relation['effective_control'], 'NOT_EVALUATED')
        rows = packet['target_context']['connections']
        target = next(r for r in rows if r['instance_ref'].endswith(':Target'))
        self.assertEqual({t['name']: t['actual_name'] for t in target['named_terminals']},
                         {'sense':'sense', 'ref':'ref'})
        self.assertTrue(target['source_locations'])

    def test_same_net_does_not_create_between_node_components(self):
        packet = scope.make_target_packet(fixture(), '/bench', 'sense', 'sense')
        self.assertEqual(packet['connection_assessment']['direct_local_net'], 'same')
        self.assertEqual(packet['connection_assessment']['shared_component_refs'], [])
        self.assertEqual(packet['connection_assessment']['effective_control'], 'NOT_EVALUATED')

    def test_no_shared_component_is_not_global_isolation(self):
        packet = scope.make_target_packet(fixture(), '/bench', 'drive', 'spare')
        self.assertEqual(packet['connection_assessment']['shared_component_refs'], [])
        self.assertEqual(packet['connection_assessment']['global_device_path'], 'NOT_EVALUATED')

    def test_incomplete_ancestry_withholds_both_endpoint_boundaries(self):
        ir = fixture()
        next(o for o in ir['occurrences'] if o['instance_path']=='/bench')['status']='blocked'
        packet = scope.make_target_packet(ir, '/bench', 'drive', 'sense')
        self.assertFalse(packet['connection_assessment']['hierarchy_links_available'])
        self.assertEqual(packet['boundaries'], [])
        self.assertEqual(packet['target_context']['boundaries'], [])
        self.assertTrue(all(t['resolved_net'] is None for r in packet['target_context']['connections']
                            for t in r['named_terminals']))

    def test_source_qualified_targets_do_not_merge_names(self):
        a,b=fixture('a'),fixture('b')
        ir={k:a[k]+b[k] for k in ('definitions','instances','nets','occurrences','source_spans')}
        with self.assertRaises(ValueError): scope.make_target_packet(ir, '/bench','drive','sense')
        packet=scope.make_target_packet(ir,'b:occ:/bench','drive','sense')
        self.assertTrue(all(ref.startswith('b:') for ref in packet['connection_assessment']['shared_component_refs']))

    def test_unknown_component_is_incidence_without_device_semantics(self):
        ir=fixture()
        inst=next(i for i in ir['instances'] if i['id'].endswith(':Branch'))
        inst['master_ref_or_name']='unprovided_model'
        packet=scope.make_target_packet(ir,'/bench','drive','sense')
        self.assertEqual(packet['connections'][0]['terminal_semantics'],'UNKNOWN')
        self.assertEqual(packet['connection_assessment']['component_relation'],'terminal_incidence_only')

    def test_compaction_retains_target_members_and_named_projection(self):
        packet=scope.make_target_packet(fixture(),'/bench','drive','sense')
        compact=scope.compact_packet(packet)
        self.assertNotIn('connections',compact['target_context'])
        groups=compact['target_context']['connection_groups']
        target=next(g for g in groups if any(m['instance_ref'].endswith(':Target') for m in g['members']))
        self.assertEqual(target['named_terminals'],packet['target_context']['connections'][1]['named_terminals'])

    def test_cli_pair_roundtrip_with_source_hash_and_no_overwrite(self):
        with tempfile.TemporaryDirectory(prefix='端点 ') as td:
            src=Path(td)/'ir.json'; dst=Path(td)/'pair.json'
            src.write_text(json.dumps(fixture()),encoding='utf-8')
            args=[sys.executable,str(SCRIPTS/'scope_packet.py'),str(src),'--occurrence','/bench',
                  '--net','drive','--target-net','sense','--out',str(dst)]
            result=subprocess.run(args,capture_output=True)
            self.assertEqual(result.returncode,0,result.stdout)
            packet=json.loads(dst.read_text(encoding='utf-8'))
            self.assertEqual(packet['source']['sha256'],hashlib.sha256(src.read_bytes()).hexdigest())
            self.assertEqual(packet,json.loads(result.stdout))
            frozen=dst.read_bytes()
            self.assertEqual(subprocess.run(args,capture_output=True).returncode,1)
            self.assertEqual(dst.read_bytes(),frozen)

    def test_quality_negative_result_has_only_wire_graph_meaning(self):
        value=quality_packet([])
        value['artifacts']=[{'id':'src','path':'source.scs','sha256':'0'*64}]
        result=quality.validate(value,Path('.'),verify_files=False)
        self.assertFalse(result['valid'])
        self.assertEqual(result['direct_connection_checks'][0]['in_submitted_wire_graph'],'not_reachable')
        self.assertEqual(result['check_scope']['device_mediated_paths'],'NOT_EVALUATED')
        self.assertEqual(result['check_scope']['effective_control'],'NOT_EVALUATED')
        value['fixtures'][0]['edges']=[['drive','goal']]
        result=quality.validate(value,Path('.'),verify_files=False)
        self.assertTrue(result['valid'],result)
        self.assertEqual(result['check_scope']['graph_source_fidelity'],'NOT_VERIFIED')
        self.assertEqual(result['check_scope']['effective_control'],'NOT_EVALUATED')

    def test_malformed_quality_does_not_claim_semantic_assessment(self):
        result=quality.validate({},Path('.'),verify_files=False)
        self.assertFalse(result['valid'])
        self.assertEqual(result['direct_connection_checks'],[])
        self.assertEqual(result['check_scope']['effective_control'],'NOT_EVALUATED')

if __name__=='__main__': unittest.main()
