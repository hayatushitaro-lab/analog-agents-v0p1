import copy
import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path
from analog_evidence.admission import Admission, AdmissionError
from analog_evidence.parser import parse
from analog_evidence.evidence import build_snapshot, validate, digest


def seal(ir):
    ir['snapshot_id']='pending';ir['snapshot_id']=digest(ir)


class IntegrityTests(unittest.TestCase):
    def make_ir(self):
        data=b'subckt root a b\nQ (a b) custom w=6u\nends root\n'
        ir=build_snapshot([parse(data,'A','spectre')],'root','synthetic',[],{'A':data},{})
        return ir,{'A':data}

    def test_mutated_connections_and_claim_must_not_self_validate(self):
        ir,sources=self.make_ir();i=ir['instances'][0]
        i['ordered_terminals'][0]['raw_name']='b';i['ordered_terminals'][0]['canonical_name']='b'
        for c in ir['claims']:
            if c['subject_ref']==i['id'] and c['predicate']=='declared_connections':c['value']['items'][0]='b'
        seal(ir)
        self.assertTrue(any('source' in e for e in validate(ir,sources)))

    def test_mutated_formals_and_claim_must_not_self_validate(self):
        ir,sources=self.make_ir();d=ir['definitions'][0]
        d['formal_ports'][0]['raw_name']='wrong';d['formal_ports'][0]['canonical_name']='wrong'
        for c in ir['claims']:
            if c['predicate']=='declared_formal_ports':c['value']['items'][0]='wrong'
        seal(ir)
        self.assertTrue(any('source' in e for e in validate(ir,sources)))

    def test_net_ref_rewire_rejected(self):
        ir,sources=self.make_ir();i=ir['instances'][0]
        i['ordered_terminals'][0]['net_ref']=i['ordered_terminals'][1]['net_ref'];seal(ir)
        self.assertTrue(validate(ir,sources))

    def test_snapshot_hash_and_derived_value(self):
        ir,sources=self.make_ir();ir['snapshot_id']='forged';self.assertTrue(validate(ir,sources))
        ir,sources=self.make_ir()
        next(c for c in ir['claims'] if c['predicate']=='normalized_scalar.w')['value']['decimal_string']='0.2';seal(ir)
        self.assertTrue(validate(ir,sources))

    def test_schema_rejects_missing_core_collection(self):
        ir,sources=self.make_ir();del ir['source_spans'];self.assertTrue(validate(ir,sources))

    def test_symlink_denied_without_following(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as d:
            root=Path(d);target=root/'target';target.write_bytes(b'CANARY');link=root/'link'
            try:link.symlink_to(target)
            except OSError:self.skipTest('OS did not permit creating the synthetic symlink')
            with self.assertRaises(AdmissionError):Admission(root,[{'id':'A','path':'link','sha256':hashlib.sha256(b'CANARY').hexdigest()}])

    def test_malformed_duplicate_and_unknown_expression_are_visible(self):
        data=b'subckt root a\nQ (a) custom w=unknown(1)\nQ (a) custom w=6u\nends root\n'
        v=parse(data,'A','spectre')
        self.assertTrue(any(d['severity']=='error' for d in v['diagnostics']))
        self.assertEqual(v['instances'][0]['parameters'][0]['raw_expr'],'unknown(1)')

    def test_eof_continuation_and_unknown_directive(self):
        v=parse(b'subckt root a\nQ (a) custom \\\n','A','spectre')
        self.assertEqual(v['status'],'partial')

    def test_dangling_span_fails_closed_without_exception(self):
        ir,sources=self.make_ir();ir['definitions'][0]['span_refs']=['missing','missing'];seal(ir)
        self.assertTrue(validate(ir,sources))

    def test_equivalent_literals_classified_as_lexical(self):
        from analog_evidence.graph import compare
        a=parse(b'subckt root a b\nQ (a b) custom w=6.000u\nends root\n','A','spectre')
        b=parse(b'subckt root a b\nZ (a b) custom w=6e-6\nends root\n','B','spectre')
        row=next(r for r in compare(a,b) if r['comparison_scope']=='instance_parameters')
        self.assertEqual(row['differences'][0]['classification'],'lexical_representation')

    def test_reparse_attribute_rejected(self):
        from unittest.mock import patch
        from types import SimpleNamespace
        from analog_evidence.admission import no_links
        with patch.object(Path,'lstat',return_value=SimpleNamespace(st_mode=0o100644,st_file_attributes=0x400)):
            with self.assertRaises(AdmissionError):no_links(Path(__file__))
        v=parse(b'.SUBCKT top a\n.UNSUPPORTED generator\n.ENDS\n','A','cdl')
        self.assertEqual(v['status'],'partial')


if __name__=='__main__':unittest.main()
