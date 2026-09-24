"""Independent filesystem fixtures for read-only wiki access boundaries."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / 'skills/analog-recovery-evidence/scripts/wiki_packet.py'
spec = importlib.util.spec_from_file_location('wiki_packet_test', SCRIPT)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


class WikiPacketTests(unittest.TestCase):
    def test_project_opt_in_and_bounded_narrative(self):
        self.entries['project-1']['path'] = 'projects/case/summary.yml'
        (self.repo/'wiki/index.yml').write_text(json.dumps(self.entries))
        case = self.repo/'wiki/projects/case'
        case.mkdir(parents=True)
        (case/'summary.yml').write_text(json.dumps({'type':'project', 'supersedes_context':'topo-1'}))
        (case/'narrative.md').write_text('old explanation\nretracted with evidence\nremaining unknown\n')
        result = mod.packet(self.repo, entry='project-1', projects=True, document='narrative', start=2, count=1)
        self.assertEqual(result['document']['text'], 'retracted with evidence\n')
        self.assertEqual(result['related'][0]['to'], 'topo-1')
        self.assertFalse(result['related_content_loaded'])
        self.assertEqual(mod.packet(self.repo, entry='project-1', projects=True, document='trajectory')['document']['status'], 'missing')

    def test_audit_can_read_withdrawn_entry(self):
        (self.repo/'wiki/topologies/a.yml').write_text(json.dumps({'confidence':'deprecated', 'content':'withdrawn'}))
        self.assertEqual(mod.packet(self.repo, entry='topo-1', audit=True)['entry']['content'], 'withdrawn')

    def test_legacy_document_needs_matching_index_identity(self):
        self.entries['project-1'].update(path='projects/case/summary.yml', type='project')
        (self.repo/'wiki/index.yml').write_text(json.dumps(self.entries))
        case = self.repo/'wiki/projects/case'
        case.mkdir(parents=True)
        (case/'narrative.md').write_text('bounded legacy history')
        for data in ({'proj-index':'other'}, {'proj-index':'project-1','id':'other'},
                     {'proj-index':'project-1','type':'strategy'},
                     {'proj-index':'project-1','id':'other','type':'project'}):
            (case/'summary.yml').write_text(json.dumps(data))
            with self.assertRaises(ValueError):
                mod.packet(self.repo,entry='project-1',projects=True,document='narrative')
        (case/'summary.yml').write_text(json.dumps({'proj-index':'project-1'}))
        self.assertEqual(mod.packet(self.repo,entry='project-1',projects=True,document='narrative')['document']['text'],
                         'bounded legacy history')

    def test_reverse_edges_expose_continuation_without_loading_it(self):
        self.entries['project-1']['path'] = 'projects/case/summary.yml'
        (self.repo/'wiki/index.yml').write_text(json.dumps(self.entries))
        (self.repo/'wiki/edges.jsonl').write_text(json.dumps({'from':'project-1','to':'topo-1','rel':'derived_from'})+'\n')
        result = mod.packet(self.repo, entry='topo-1', projects=True)
        self.assertEqual(result['related'][0]['from'], 'project-1')
        self.assertFalse((self.repo/'wiki/projects/case/summary.yml').exists())

    def test_workspace_escape_and_bad_excerpt_range(self):
        with self.assertRaises(ValueError): mod.allowed_path(self.repo/'wiki', '../outside.yml', True)
        with self.assertRaises(ValueError): mod.excerpt(self.repo/'x', start=0)
        with self.assertRaises(ValueError): mod.excerpt(self.repo/'x', count=501)

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.repo = Path(self.tmp.name)
        (self.repo/'tools').mkdir()
        (self.repo/'wiki/topologies').mkdir(parents=True)
        (self.repo/'tools/wiki_ops.py').write_text(
            'import json\nfrom pathlib import Path\n'
            'def load_index(root): return json.loads((Path(root)/"index.yml").read_text())\n'
            'def load_entry(root,path):\n'
            ' (Path(root)/"body_read_marker").touch()\n'
            ' return json.loads((Path(root)/path).read_text())\n', encoding='utf8')
        self.entries = {
            'topo-1': {'path':'topologies/a.yml','summary':'bias reference'},
            'project-1': {'path':'projects/case.yml','summary':'bias historical answer'},
            'topo-fm': {'path':'topologies/fm.yml','summary':'bias FM_EXCLUDED'},
        }
        (self.repo/'wiki/index.yml').write_text(json.dumps(self.entries))
        (self.repo/'wiki/topologies/a.yml').write_text(json.dumps({'confidence':'verified','content':'relation'}))

    def test_query_reads_index_only(self):
        result = mod.packet(self.repo, query='bias', excludes=['FM_EXCLUDED'])
        self.assertEqual([r['id'] for r in result['matches']], ['topo-1'])
        self.assertFalse((self.repo/'wiki/body_read_marker').exists())

    def test_entry_reads_only_selected(self):
        result = mod.packet(self.repo, entry='topo-1')
        self.assertEqual(result['entry']['content'], 'relation')
        self.assertTrue(result['sha256'])

    def test_reject_project_and_escape(self):
        with self.assertRaises(ValueError): mod.packet(self.repo, entry='project-1')
        with self.assertRaises(ValueError): mod.allowed_path(self.repo/'wiki','../outside.yml')

    def test_deprecated_and_budget(self):
        p = self.repo/'wiki/topologies/a.yml'
        p.write_text(json.dumps({'confidence':'deprecated'}))
        with self.assertRaises(ValueError): mod.packet(self.repo, entry='topo-1')
        with self.assertRaises(ValueError): mod.packet(self.repo, entry='topo-1', max_bytes=2)

    def test_exclusion_applies_to_explicit_read(self):
        with self.assertRaises(ValueError): mod.packet(self.repo, entry='topo-fm', excludes=['FM_EXCLUDED'])

    def test_hidden_source_exclusion(self):
        (self.repo/'wiki/topologies/a.yml').write_text(json.dumps({'source':'FM_EXCLUDED case'}))
        with self.assertRaises(ValueError): mod.packet(self.repo, entry='topo-1', excludes=['FM_EXCLUDED'])


if __name__ == '__main__': unittest.main()
