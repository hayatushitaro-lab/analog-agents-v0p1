"""Spectre comments must not become parameters or hide source/identity errors."""
import copy
import unittest

from analog_evidence.parser import parse, spectre_code
from analog_evidence.graph import elaborate
from analog_evidence.evidence import build_snapshot, validate, digest


class InlineCommentTests(unittest.TestCase):
    def test_parameter_comment_resolves_without_losing_bytes(self):
        raw = b'parameters width=6u // size (not syntax)\r\nsubckt root a b // ports\r\nQ (a b) custom w=width // load\r\nends root // done\r\n'
        view = parse(raw, 'A', 'spectre')
        self.assertFalse(view['diagnostics'])
        occurrences, diagnostics = elaborate(view, 'root')
        child = next(o for o in occurrences if o['instance_path'] == '/root/Q')
        self.assertEqual(child['parameter_environment']['w'], '0.000006')
        self.assertFalse(diagnostics)
        self.assertEqual(''.join(s['raw'] for s in view['statements']).encode(), raw)
        fragments = [f for s in view['source_spans'] for f in s['fragments']]
        self.assertEqual(b''.join(raw[f['byte_start']:f['byte_end']] for f in fragments), raw)
        snapshot = build_snapshot([view], 'root', 'test', [], {'A': raw}, {})
        self.assertFalse(validate(snapshot, {'A': raw}))
        bad = copy.deepcopy(snapshot)
        bad['definitions'][0]['formal_ports'][0]['raw_name'] = 'forged'
        bad['snapshot_id'] = 'pending'; bad['snapshot_id'] = digest(bad)
        self.assertTrue(validate(bad, {'A': raw}))

    def test_quoted_slashes_and_escaped_quotes_remain_literal(self):
        for text, expected in ((r'include "dir//cell.scs" // note', r'include "dir//cell.scs" '),
                               (r"include 'dir//cell.scs' // note", r"include 'dir//cell.scs' "),
                               (r'parameters x="a\"//b" // note', r'parameters x="a\"//b" ')):
            self.assertEqual(spectre_code(text), expected)
        view = parse(b'include "dir//cell.scs" // note\n', 'A', 'spectre')
        self.assertEqual(view['dependencies'][0]['requested_path'], 'dir//cell.scs')

    def test_comments_with_backslashes_do_not_join_next_statement(self):
        view = parse(b'parameters a=1 // note \\\nparameters b=2\n', 'A', 'spectre')
        self.assertEqual(len(view['statements']), 2)
        self.assertEqual([p['canonical_key'] for p in view['global_parameters']], ['a', 'b'])

    def test_continuation_before_comment_preserves_line_spans(self):
        raw = b'subckt root a \\ // comment\n b // second port\nQ (a b) custom \\ // instance\n w=6u // width\nends root\n'
        view = parse(raw, 'A', 'spectre')
        self.assertFalse(view['diagnostics'])
        self.assertEqual([p['raw_name'] for p in view['definitions'][0]['formal_ports']], ['a', 'b'])
        self.assertEqual([f['line'] for f in view['source_spans'][0]['fragments']], [1, 2])
        snapshot = build_snapshot([view], 'root', 'test', [], {'A': raw}, {})
        self.assertFalse(validate(snapshot, {'A': raw}))

    def test_malformed_code_not_repaired_by_comment_handling(self):
        for raw in (b'parameters a= // missing value\n',
                    b'parameters a="bad // unterminated string\n',
                    b'subckt root a \\\n// interrupt\nends root\n'):
            self.assertTrue(parse(raw, 'A', 'spectre')['diagnostics'])

    def test_cdl_dialect_is_not_given_spectre_comment_rules(self):
        view = parse(b'.PARAM a=1 // not supported CDL comment\n', 'A', 'cdl')
        self.assertTrue(view['diagnostics'])


if __name__ == '__main__':
    unittest.main()
