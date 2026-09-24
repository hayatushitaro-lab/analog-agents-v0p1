"""Independent source fixtures; no project answers or model files."""
import copy
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
SPEC = importlib.util.spec_from_file_location('binding_scope', ROOT / 'skills/analog-recovery-evidence/scripts/scope_packet.py')
scope = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(scope)


def fixture(ports='bulk src gate drain', actual='rail bias enable output'):
    text = f'''subckt leaf {ports}
Odd (drain gate src bulk) wrapped w=7u nf=3
ends leaf
subckt root rail bias enable output
Branch ({actual}) leaf
ends root
'''
    ir = parse(text.encode(), 'synthetic', 'spectre')
    ir['occurrences'], diags = elaborate(ir, 'root')
    assert not diags
    return ir


def contract():
    return {'wrapped': {'terminal_order': ['D', 'G', 'S', 'B'],
                        'source_refs': ['synthetic:model-port-declaration']}}


class LocalBindingContractTests(unittest.TestCase):
    def test_formal_order_comes_from_definition(self):
        for ports, actual in [('bulk src gate drain', 'rail bias enable output'),
                              ('gate drain bulk src', 'enable output rail bias')]:
            p = scope.make_packet(fixture(ports, actual), '/root', 'rail')
            named = p['connections'][0]['named_terminals']
            self.assertEqual({t['name']: t['actual_name'] for t in named},
                             {'bulk': 'rail', 'src': 'bias', 'gate': 'enable', 'drain': 'output'})

    def test_mos_source_body_not_inferred_from_names(self):
        ir = fixture()
        for swapped in [False, True]:
            if swapped:
                ir = fixture(actual='bias rail enable output')
            p = scope.make_packet(ir, '/root/Branch', 'src', contract())
            named = {t['name']: t for t in p['connections'][0]['named_terminals']}
            self.assertTrue(named['S']['resolved_net'].endswith(':port:' + ('rail' if swapped else 'bias')))
            self.assertTrue(named['B']['resolved_net'].endswith(':port:' + ('bias' if swapped else 'rail')))

    def test_unknown_master_has_no_invented_roles_or_width(self):
        row = scope.make_packet(fixture(), '/root/Branch', 'src')['connections'][0]
        self.assertEqual(row['terminal_semantics'], 'UNKNOWN')
        self.assertEqual(row['named_terminals'], [])
        self.assertEqual(row['width_semantics'], 'UNKNOWN')
        self.assertEqual([p['raw_expr'] for p in row['parameters']], ['7u', '3'])

    def test_terminal_contract_does_not_authorize_width_conversion(self):
        for convention in ['per_finger', 'total_width']:
            c = contract()
            c['wrapped']['width_convention'] = convention
            row = scope.make_packet(fixture(), '/root/Branch', 'src', c)['connections'][0]
            self.assertEqual(row['width_semantics'], 'UNKNOWN')
            self.assertNotIn('effective_width', row)

    def test_arity_and_missing_provenance_rejected(self):
        for change in [{'terminal_order': ['D', 'S']}, {'source_refs': []},
                       {'terminal_order': ['D', 'G', 'S', 'S']}]:
            c = contract(); c['wrapped'].update(change)
            with self.assertRaises(ValueError):
                scope.make_packet(fixture(), '/root/Branch', 'src', c)

    def test_compact_retains_bindings_and_provenance(self):
        p = scope.make_packet(fixture(), '/root/Branch', 'src', contract())
        compact = scope.compact_packet(p)
        self.assertEqual(compact['connection_groups'][0]['named_terminals'], p['connections'][0]['named_terminals'])
        self.assertTrue(compact['connection_groups'][0]['members'][0]['source_locations'])

    def test_incomplete_parent_withholds_resolved_bindings(self):
        ir = fixture()
        next(o for o in ir['occurrences'] if o['instance_path'] == '/root/Branch')['status'] = 'blocked'
        row = scope.make_packet(ir, '/root/Branch', 'src', contract())['connections'][0]
        self.assertTrue(all(t['resolved_net'] is None for t in row['named_terminals']))

    def test_incomplete_ancestor_withholds_resolved_bindings(self):
        ir = fixture()
        next(o for o in ir['occurrences'] if o['instance_path'] == '/root')['status'] = 'blocked'
        row = scope.make_packet(ir, '/root/Branch', 'src', contract())['connections'][0]
        self.assertTrue(all(t['resolved_net'] is None for t in row['named_terminals']))

    def test_repeated_children_keep_occurrence_specific_bindings(self):
        text = '''subckt cell a b
device (a b) opaque
ends cell
subckt renamed p q
First (p q) cell
Second (q p) cell
ends renamed
'''
        ir = parse(text.encode(), 'independent', 'spectre')
        ir['occurrences'], _ = elaborate(ir, 'renamed')
        meta = {'opaque': {'terminal_order': ['left', 'right'], 'source_refs': ['synthetic:declaration']}}
        for occurrence, expected in [('First', 'p'), ('Second', 'q')]:
            row = scope.make_packet(ir, '/renamed/'+occurrence, 'a', meta)['connections'][0]
            self.assertTrue(row['named_terminals'][0]['resolved_net'].endswith(':port:'+expected))

    def test_subckt_contract_cannot_override_formal_order(self):
        row = scope.make_packet(fixture(), '/root', 'rail',
            {'leaf': {'terminal_order': ['D','G','S','B'], 'source_refs': ['wrong:override']}})['connections'][0]
        self.assertEqual([t['name'] for t in row['named_terminals']], ['bulk','src','gate','drain'])

    def test_invalid_metadata_rejected_without_guessing(self):
        for order, refs in [('DGSB', ['source']), (['D','G','S',''], ['source']),
                            (['D','G','S','B'], 'source'), (['D','G','S','B'], [''])]:
            with self.assertRaises(ValueError):
                scope.make_packet(fixture(), '/root/Branch', 'src',
                    {'wrapped': {'terminal_order': order, 'source_refs': refs}})

    def test_subckt_arity_mismatch_rejected(self):
        ir = parse(b'subckt cell a b\nends cell\nsubckt root x\nCall (x) cell\nends root\n',
                   'arity', 'spectre')
        ir['occurrences'], diagnostics = elaborate(ir, 'root')
        self.assertTrue(diagnostics)
        # The parser/elaborator diagnosed the mismatch; no zip truncation in projection.
        with self.assertRaises(ValueError):
            scope.make_packet(ir, '/root', 'x')

    def test_cli_records_metadata_identity(self):
        with tempfile.TemporaryDirectory() as td:
            ir = Path(td)/'ir.json'; meta = Path(td)/'metadata.json'
            ir.write_text(json.dumps(fixture()), encoding='utf8')
            meta.write_text(json.dumps(contract()), encoding='utf8')
            result = subprocess.run([sys.executable, str(Path(scope.__file__)), str(ir),
                '--occurrence', '/root/Branch', '--net', 'src', '--terminal-contracts', str(meta)],
                capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stdout+result.stderr)
            output = json.loads(result.stdout)
            self.assertEqual(output['connection_groups'][0]['named_terminals'][2]['name'], 'S')
            self.assertEqual(len(output['terminal_contract_source']['sha256']), 64)


if __name__ == '__main__':
    unittest.main()
