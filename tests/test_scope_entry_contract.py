"""Independent multi-source and Unicode transport regressions; no project data."""
import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from analog_evidence.parser import parse
from analog_evidence.graph import elaborate

SCRIPT = Path(__file__).resolve().parents[1] / 'skills/analog-recovery-evidence/scripts/scope_packet.py'
SPEC = importlib.util.spec_from_file_location('entry_scope', SCRIPT)
scope = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(scope)


def design(aid, order='low high'):
    raw = f'''subckt element {order}
Part (low high) opaque
ends element
subckt block p q
Branch (p q) element
ends block
'''
    view = parse(raw.encode(), aid, 'spectre')
    view['occurrences'], diagnostics = elaborate(view, 'block')
    assert not diagnostics
    return view


def merged():
    left, right = design('alpha'), design('beta', 'high low')
    return {key: left[key] + right[key] for key in
            ('definitions', 'instances', 'occurrences', 'nets', 'source_spans')}


class ScopeEntryTests(unittest.TestCase):
    def test_same_master_uses_selected_source_in_both_orders(self):
        for reverse in (False, True):
            ir = merged()
            if reverse:
                ir['definitions'].reverse()
                ir['occurrences'].reverse()
            for aid, expected in [('alpha', {'low': 'p', 'high': 'q'}),
                                  ('beta', {'high': 'p', 'low': 'q'})]:
                row = scope.make_packet(ir, aid + ':occ:/block', 'p')['connections'][0]
                self.assertEqual({t['name']: t['actual_name'] for t in row['named_terminals']}, expected)
                self.assertTrue(all(ref.startswith(aid + ':') for ref in row['terminal_source_refs']))

    def test_incomplete_child_still_uses_local_formal_order(self):
        ir = merged()
        for occ in ir['occurrences']:
            if occ['id'].startswith('beta:'):
                occ['status'] = 'blocked'
        row = scope.make_packet(ir, 'beta:occ:/block', 'p')['connections'][0]
        self.assertEqual([t['name'] for t in row['named_terminals']], ['high', 'low'])
        self.assertTrue(all(t['resolved_net'] is None for t in row['named_terminals']))

    def test_missing_child_uses_unique_same_artifact_definition(self):
        ir = merged()
        ir['occurrences'] = [o for o in ir['occurrences'] if o['id'] != 'alpha:occ:/block/Branch']
        row = scope.make_packet(ir, 'alpha:occ:/block', 'p')['connections'][0]
        self.assertEqual([t['name'] for t in row['named_terminals']], ['low', 'high'])
        self.assertTrue(all(t['resolved_net'] is None for t in row['named_terminals']))

    def test_unqualified_repeated_occurrence_is_rejected(self):
        with self.assertRaisesRegex(ValueError, 'occurrence'):
            scope.make_packet(merged(), '/block', 'p')

    def test_true_same_source_ambiguity_is_rejected(self):
        ir = merged()
        duplicate = copy.deepcopy(next(d for d in ir['definitions'] if d['id'] == 'alpha:def:element'))
        duplicate['id'] = 'alpha:def:ambiguous-copy'
        duplicate['formal_ports'].reverse()
        ir['definitions'].append(duplicate)
        with self.assertRaises(ValueError):
            scope.make_packet(ir, 'alpha:occ:/block', 'p')

    def test_cross_source_child_reference_is_rejected(self):
        ir = merged()
        child = next(o for o in ir['occurrences'] if o['id'] == 'alpha:occ:/block/Branch')
        child['definition_ref'] = 'beta:def:element'
        with self.assertRaises(ValueError):
            scope.make_packet(ir, 'alpha:occ:/block', 'p')

    def test_foreign_definition_does_not_assign_opaque_device_roles(self):
        ir = merged()
        extra = copy.deepcopy(next(d for d in ir['definitions'] if d['id'] == 'beta:def:element'))
        extra.update(id='beta:def:opaque', raw_name='opaque', canonical_name='opaque')
        ir['definitions'].append(extra)
        row = scope.make_packet(ir, 'alpha:occ:/block/Branch', 'low')['connections'][0]
        self.assertEqual(row['terminal_semantics'], 'UNKNOWN')
        self.assertEqual(row['named_terminals'], [])

    def test_stdout_survives_legacy_python_encoding_and_utf8_consumer(self):
        with tempfile.TemporaryDirectory(prefix='证据 & ') as td:
            path = Path(td) / '输入.json'
            path.write_text(json.dumps(design('alpha')), encoding='utf-8')
            result = subprocess.run([sys.executable, str(SCRIPT), str(path),
                                     '--occurrence', '/block', '--net', 'p'],
                                    capture_output=True, env={**os.environ, 'PYTHONIOENCODING': 'gbk'})
            self.assertEqual(result.returncode, 0, repr(result.stderr))
            # Models the previously observed native-process/PowerShell decoding mismatch.
            packet = json.loads(result.stdout.decode('utf-8', errors='replace'))
            self.assertEqual(packet['source']['path'], str(path.resolve()))
            self.assertTrue(Path(packet['source']['path']).is_file())
            self.assertEqual(packet['source']['sha256'], hashlib.sha256(path.read_bytes()).hexdigest())

    def test_native_out_is_utf8_reopenable_and_does_not_overwrite(self):
        with tempfile.TemporaryDirectory(prefix='证据 & ') as td:
            path = Path(td) / '输入.json'
            target = Path(td) / '输出.json'
            path.write_text(json.dumps(design('alpha')), encoding='utf-8')
            args = [sys.executable, str(SCRIPT), str(path), '--occurrence', '/block',
                    '--net', 'p', '--out', str(target)]
            result = subprocess.run(args, capture_output=True,
                                    env={**os.environ, 'PYTHONIOENCODING': 'ascii'})
            self.assertEqual(result.returncode, 0, repr(result.stderr))
            original = target.read_bytes()
            packet = json.loads(original.decode('utf-8'))
            self.assertEqual(packet['source']['path'], str(path.resolve()))
            self.assertEqual(packet, json.loads(result.stdout))
            again = subprocess.run(args, capture_output=True,
                                   env={**os.environ, 'PYTHONIOENCODING': 'ascii'})
            self.assertNotEqual(again.returncode, 0)
            self.assertEqual(target.read_bytes(), original)
            self.assertFalse(json.loads(again.stdout)['valid'])


if __name__ == '__main__':
    unittest.main()
