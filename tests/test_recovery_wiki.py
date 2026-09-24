"""Offline continuation invariants against the real, unchanged wiki_ops."""
import copy
import importlib.util
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

import yaml

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('rw', ROOT / 'tools/recovery_wiki.py')
rw = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rw)


class RecoveryWikiTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.repo = Path(self.tmp.name)
        (self.repo / 'tools').mkdir()
        shutil.copyfile(ROOT / 'tools/wiki_ops.py', self.repo / 'tools/wiki_ops.py')
        self.ops = rw.load_ops(self.repo)
        self.wiki = self.repo / 'wiki'
        (self.wiki / 'projects/existing').mkdir(parents=True)
        (self.wiki / 'corner-lessons').mkdir()
        self.ops.save_index(str(self.wiki), {
            'proj-old': {'path': 'projects/existing/summary.yml', 'type': 'project', 'summary': 'bias', 'module': 'pmu'},
            'corner-1': {'path': 'corner-lessons/bias.yml', 'type': 'corner-lesson', 'summary': 'bias'},
        })
        (self.wiki / 'projects/existing/summary.yml').write_text(yaml.safe_dump(dict(
            id='proj-old', type='project', name='bias', tags=['pmu'], convergence=True,
            result='historical L1 only', total_iterations=7, arbitrary='preserve me')))
        (self.wiki / 'corner-lessons/bias.yml').write_text(yaml.safe_dump(dict(
            id='corner-1', type='corner-lesson', name='bias', tags=['pmu'], content={'description': 'old claim'},
            confidence='verified', derived_from=['proj-old'])))
        (self.wiki / 'edges.jsonl').write_text('')
        (self.repo / 'WORK_TEST').mkdir()
        (self.repo / 'WORK_TEST/evidence.txt').write_text('actual source, line 1')
        self.ref = dict(path='WORK_TEST/evidence.txt', sha256=rw.sha(b'actual source, line 1'), locator='line 1')
        row = dict(question_id='q-bias', iteration=1, before='old claim', action='read source',
                   evidence_refs=[self.ref['path']], after='bounded correction', remaining='cause unknown',
                   next_action='review', stop_reason='offline budget')
        self.iterpath = self.repo / 'WORK_TEST/recovery-iterations.jsonl'
        self.iterpath.write_text(json.dumps(row) + '\n')
        self.request = dict(project_id='proj-old', update_id='update-1', date='2026-09-22', block='pmu',
                            delivery_status='partial', result='cause still unknown', evidence_refs=[self.ref],
                            iterations_ref=dict(path='WORK_TEST/recovery-iterations.jsonl', sha256=rw.sha(self.iterpath.read_bytes())),
                            narrative='Old claim withdrawn for this run; cause remains unknown.',
                            entry_updates=[dict(id='corner-1', content_patch={'description': 'bounded correction'}, reason='source disagrees')],
                            edges=[dict(**{'from': 'corner-1', 'to': 'proj-old', 'rel': 'discovered_in'})])
        self.out = self.repo / 'WORK_TEST/change'

    def prepare(self):
        return rw.prepare(self.repo, self.request, self.out)

    def test_partial_preserves_history_and_is_idempotent(self):
        before = (self.wiki / 'index.yml').read_bytes()
        self.prepare()
        self.assertEqual(self.ops.load_entry(str(self.wiki), 'corner-lessons/bias.yml')['confidence'], 'verified')
        rw.apply(self.repo, self.out)
        summary = self.ops.load_entry(str(self.wiki), 'projects/existing/summary.yml')
        self.assertTrue(summary['convergence'])
        self.assertEqual(summary['result'], 'historical L1 only')
        self.assertEqual(summary['total_iterations'], 7)
        self.assertEqual(summary['arbitrary'], 'preserve me')
        self.assertEqual(summary['recovery']['delivery_status'], 'partial')
        domain = self.ops.load_entry(str(self.wiki), 'corner-lessons/bias.yml')
        self.assertEqual(domain['confidence'], 'unverified')
        self.assertEqual(domain['revisions'][0]['previous_content']['description'], 'old claim')
        self.assertEqual(rw.apply(self.repo, self.out)['status'], 'no-op')
        self.assertEqual((self.wiki / 'index.yml').read_bytes(), before)
        self.assertEqual(len((self.wiki / 'edges.jsonl').read_text().splitlines()), 1)
        self.assertEqual(len(self.ops.consult(str(self.wiki), 'pmu')['cases']), 1)
        self.assertTrue(self.ops.search(str(self.wiki), 'bias'))

    def test_new_project_never_claims_convergence(self):
        del self.request['project_id']
        self.request['create_project'] = dict(name='New case', path='projects/new-case/summary.yml', tags=['pmu'])
        self.request['delivery_status'] = 'complete'
        self.prepare()
        rw.apply(self.repo, self.out)
        summary = self.ops.load_entry(str(self.wiki), 'projects/new-case/summary.yml')
        self.assertFalse(summary['convergence'])
        self.assertEqual(summary['recovery']['delivery_status'], 'complete')

    def test_project_index_question_is_findable_without_changing_historical_result(self):
        old = self.ops.load_index(str(self.wiki))['proj-old']
        self.request['project_index_summary'] = 'Historical L1; recovery partial; Q-bias-history'
        self.prepare()
        self.assertEqual(self.ops.load_index(str(self.wiki))['proj-old'], old)
        rw.apply(self.repo, self.out)
        self.assertEqual(self.ops.search(str(self.wiki), 'Q-bias-history')[0]['id'], 'proj-old')
        summary = self.ops.load_entry(str(self.wiki), 'projects/existing/summary.yml')
        self.assertEqual(summary['index_revisions'][0]['previous_index_entry'], old)
        self.assertTrue(summary['convergence'])
        self.assertEqual(summary['result'], 'historical L1 only')
        self.assertEqual(summary['total_iterations'], 7)
        self.assertEqual(rw.apply(self.repo, self.out)['status'], 'no-op')

    def test_project_index_patch_rejects_empty_or_new_project(self):
        for value in ('', {}, None):
            request = dict(self.request, project_index_summary=value)
            with self.assertRaises(rw.ContractError):
                rw.prepare(self.repo, request, self.out)
        request = dict(self.request, project_index_summary='scope', create_project={'name': 'new'})
        request.pop('project_id')
        with self.assertRaises(rw.ContractError):
            rw.prepare(self.repo, request, self.out)

    def test_legacy_project_preserves_fields_steps_and_reads_back(self):
        path = self.wiki / 'projects/existing/summary.yml'
        old = {'proj-index': 'proj-old', 'name': 'bias', 'status': 'simulation-verified',
               'converged': '2020-01-01', 'measured': {'gain': 'historical'}}
        path.write_text(yaml.safe_dump(old))
        trajectory = self.wiki / 'projects/existing/trajectory.yml'
        old_steps = {'project': 'bias', 'steps': [{'step': 1, 'outcome': 'historical pass'}]}
        trajectory.write_text(yaml.safe_dump(old_steps))
        self.request['project_index_summary'] = 'Q-bias partial'
        self.prepare()
        rw.apply(self.repo, self.out)
        new = yaml.safe_load(path.read_text())
        self.assertEqual({k: new[k] for k in old}, old)
        self.assertNotIn('id', new)
        self.assertNotIn('type', new)
        self.assertNotIn('convergence', new)
        self.assertEqual(yaml.safe_load(trajectory.read_text())['steps'], old_steps['steps'])
        packet_spec = importlib.util.spec_from_file_location('legacy_packet', ROOT / 'skills/analog-recovery-evidence/scripts/wiki_packet.py')
        packet = importlib.util.module_from_spec(packet_spec)
        packet_spec.loader.exec_module(packet)
        result = packet.packet(self.repo, entry='proj-old', projects=True, document='trajectory')
        self.assertIn('recovery_iterations', result['document']['text'])
        self.assertEqual(rw.apply(self.repo, self.out)['status'], 'no-op')

    def test_legacy_identity_conflicts_rejected_without_live_write(self):
        path = self.wiki / 'projects/existing/summary.yml'
        for i, identity in enumerate(({'proj-index': 'other'},
                                      {'proj-index': 'proj-old', 'id': 'other'},
                                      {'proj-index': 'proj-old', 'type': 'strategy'},
                                      {'id': 'proj-old', 'type': 'project', 'proj-index': 'other'},
                                      {})):
            original = yaml.safe_dump(dict(name='legacy', **identity))
            path.write_text(original)
            with self.assertRaises(rw.ContractError):
                rw.prepare(self.repo, self.request, self.repo / f'WORK_TEST/legacy-rejected-{i}')
            self.assertEqual(path.read_text(), original)

    def test_metadata_and_index_revision_preserve_old_values_and_identity(self):
        path = self.wiki / 'corner-lessons/bias.yml'
        data = yaml.safe_load(path.read_text())
        data['source'] = 'old causal assertion'
        path.write_text(yaml.safe_dump(data))
        old_index = self.ops.load_index(str(self.wiki))
        self.request['entry_updates'][0].update(
            metadata_patch={'name': 'Scoped bias history', 'source': 'local evidence with limits',
                            'confidence_note': 'independent review pending'},
            index_summary='Scoped bias history; cause unproven')
        self.prepare()
        self.assertEqual(yaml.safe_load(path.read_text())['source'], 'old causal assertion')
        rw.apply(self.repo, self.out)
        data = yaml.safe_load(path.read_text())
        revision = data['revisions'][-1]
        self.assertEqual(revision['previous_metadata'], {'name': 'bias', 'source': 'old causal assertion'})
        self.assertEqual(revision['previous_metadata_absent'], ['confidence_note'])
        self.assertEqual(revision['previous_index_entry'], old_index['corner-1'])
        self.assertEqual(data['id'], 'corner-1')
        self.assertEqual(data['confidence'], 'unverified')
        index = self.ops.load_index(str(self.wiki))
        self.assertEqual(index['proj-old'], old_index['proj-old'])
        self.assertEqual(index['corner-1']['path'], old_index['corner-1']['path'])
        self.assertEqual(self.ops.search(str(self.wiki), 'cause unproven')[0]['id'], 'corner-1')
        self.assertEqual(rw.apply(self.repo, self.out)['status'], 'no-op')

    def test_metadata_rejects_identity_confidence_and_unsynced_name_changes(self):
        for i, update in enumerate(({'metadata_patch': {'id': 'new-id'}},
                                    {'metadata_patch': {'confidence': 'verified'}},
                                    {'metadata_patch': {'name': 'unsynced'}},
                                    {'index_summary': ''})):
            request = copy.deepcopy(self.request)
            request['entry_updates'][0].update(update)
            with self.assertRaises(rw.ContractError):
                rw.prepare(self.repo, request, self.repo / f'WORK_TEST/rejected-{i}')

    def test_edge_revision_preserves_legacy_identity_history_and_unrelated_line(self):
        edge = {'from': 'proj-old', 'to': 'corner-1', 'rel': 'validates', 'note': 'root cause proven'}
        unrelated = '{"from":"corner-1", "to":"proj-old", "rel":"derived_from"}\n'
        (self.wiki / 'edges.jsonl').write_text(json.dumps(edge) + '\n' + unrelated)
        self.request['edge_updates'] = [dict(edge, expected_note=edge['note'],
                                             note='Historical scope revised; cause unknown', reason='source comparison')]
        self.prepare()
        rw.apply(self.repo, self.out)
        lines = (self.wiki / 'edges.jsonl').read_text().splitlines(keepends=True)
        revised = json.loads(lines[0])
        self.assertEqual(revised['revisions'][0]['previous_edge'], edge)
        self.assertEqual(revised['status'], 'historical_revised')
        self.assertEqual(revised['rel'], 'validates')
        self.assertEqual(lines[1], unrelated)
        self.assertEqual(rw.apply(self.repo, self.out)['status'], 'no-op')

    def test_edge_revision_rejects_missing_ambiguous_and_stale_targets(self):
        edge = {'from': 'proj-old', 'to': 'corner-1', 'rel': 'validates', 'note': 'old'}
        self.request['edge_updates'] = [dict(edge, expected_note='old', note='bounded', reason='source')]
        for i, rows in enumerate(([], [edge, edge], [dict(edge, note='concurrent')])):
            (self.wiki / 'edges.jsonl').write_text(''.join(json.dumps(e) + '\n' for e in rows))
            with self.assertRaises(rw.ContractError):
                rw.prepare(self.repo, self.request, self.repo / f'WORK_TEST/edge-rejected-{i}')

    def test_failure_after_metadata_revision_restores_entries_index_and_edges(self):
        edge = {'from': 'proj-old', 'to': 'corner-1', 'rel': 'validates', 'note': 'old'}
        (self.wiki / 'edges.jsonl').write_text(json.dumps(edge) + '\n')
        self.request['edge_updates'] = [dict(edge, expected_note='old', note='bounded', reason='source')]
        self.request['entry_updates'][0]['index_summary'] = 'bounded claim'
        before = {p: p.read_bytes() for p in self.wiki.rglob('*') if p.is_file()}
        self.prepare()
        original = rw.atomic_write
        failed = False
        def fail_once(path, data):
            nonlocal failed
            if path.name == 'edges.jsonl' and not failed:
                failed = True
                raise OSError('injected metadata write failure')
            return original(path, data)
        with patch.object(rw, 'atomic_write', fail_once):
            with self.assertRaises(OSError):
                rw.apply(self.repo, self.out)
        self.assertEqual({p: p.read_bytes() for p in self.wiki.rglob('*') if p.is_file()}, before)

    def test_new_domain_uses_original_index_and_provenance(self):
        self.request['new_entries'] = [dict(type='anti-pattern', name='Bias assumptions', tags=['pmu'], content={'description': 'check stimulus'})]
        self.prepare()
        rw.apply(self.repo, self.out)
        entries = self.ops.load_index(str(self.wiki))
        new = next(v for v in entries.values() if v['type'] == 'anti-pattern')
        data = self.ops.load_entry(str(self.wiki), new['path'])
        self.assertEqual(data['derived_from'], ['proj-old'])
        self.assertEqual(data['confidence'], 'unverified')
        self.assertEqual(entries['proj-old']['module'], 'pmu')

    def test_deprecate_keeps_old_explanation(self):
        self.request['entry_updates'][0]['deprecate'] = True
        self.prepare()
        rw.apply(self.repo, self.out)
        data = self.ops.load_entry(str(self.wiki), 'corner-lessons/bias.yml')
        self.assertEqual(data['confidence'], 'deprecated')
        self.assertEqual(data['revisions'][0]['previous_content']['description'], 'old claim')

    def test_evidence_drift_prevents_any_write(self):
        self.prepare()
        (self.repo / self.ref['path']).write_text('changed')
        with self.assertRaises(rw.ContractError):
            rw.apply(self.repo, self.out)
        self.assertFalse((self.wiki / 'projects/existing/narrative.md').exists())

    def test_bundle_semantic_file_drift_not_hidden_by_same_manifest(self):
        folder=self.repo/'WORK_TEST/bundle';folder.mkdir()
        for name in ('manifest','design_evidence','report_requirements','metrics','coverage','review'):
            (folder/(name+'.json')).write_text('{}')
        self.request['bundle_ref']=dict(path='WORK_TEST/bundle/manifest.json',sha256=rw.sha(b'{}'))
        self.prepare()
        (folder/'design_evidence.json').write_text('{"changed":true}')
        with self.assertRaises(rw.ContractError):rw.apply(self.repo,self.out)

    def test_concurrent_change_is_not_overwritten(self):
        self.prepare()
        p = self.wiki / 'projects/existing/summary.yml'
        p.write_text('concurrent editor')
        with self.assertRaises(rw.ContractError):
            rw.apply(self.repo, self.out)
        self.assertEqual(p.read_text(), 'concurrent editor')
        self.assertFalse((self.wiki / '.recovery-write.lock').exists())

    def test_changed_candidate_rejected(self):
        self.prepare()
        (self.out / 'candidate/projects/existing/summary.yml').write_text('changed')
        with self.assertRaises(rw.ContractError):
            rw.apply(self.repo, self.out)

    def test_write_failure_rolls_back(self):
        self.prepare()
        before = (self.wiki / 'projects/existing/summary.yml').read_bytes()
        target = self.wiki / 'projects/existing/narrative.md'
        original = rw.atomic_write
        def fail_once(path, data):
            if path.resolve() == target.resolve():
                raise OSError('injected write failure')
            return original(path, data)
        with patch.object(rw, 'atomic_write', fail_once):
            with self.assertRaises(OSError):
                rw.apply(self.repo, self.out)
        self.assertEqual((self.wiki / 'projects/existing/summary.yml').read_bytes(), before)
        self.assertFalse((self.wiki / '.recovery-write.lock').exists())
        self.assertEqual(rw.read_json(self.out / 'receipt.json')['status'], 'rolled_back')

    def test_crash_lock_requires_explicit_recovery(self):
        self.prepare()
        rw.dump_json(self.wiki / '.recovery-write.lock', {'plan': str(self.out)})
        candidate = self.out / 'candidate/projects/existing/summary.yml'
        (self.wiki / 'projects/existing/summary.yml').write_bytes(candidate.read_bytes())
        with self.assertRaises(rw.ContractError):
            rw.apply(self.repo, self.out)
        self.assertEqual(rw.recover(self.repo, self.out)['status'], 'rolled_back')
        self.assertNotIn('recovery', self.ops.load_entry(str(self.wiki), 'projects/existing/summary.yml'))

    def test_recovery_refuses_to_undo_concurrent_edit(self):
        self.prepare()
        rw.dump_json(self.wiki / '.recovery-write.lock', {'plan': str(self.out)})
        (self.wiki / 'projects/existing/summary.yml').write_text('someone else')
        with self.assertRaises(rw.ContractError):
            rw.recover(self.repo, self.out)
        self.assertTrue((self.wiki / '.recovery-write.lock').exists())

    def test_external_evidence_and_bad_status_rejected(self):
        for change in ({'delivery_status': 'PASS'}, {'convergence': True}):
            request = dict(self.request, **change)
            with self.assertRaises(rw.ContractError):
                rw.prepare(self.repo, request, self.out)
        self.request['evidence_refs'][0]['path'] = '../outside.txt'
        with self.assertRaises(rw.ContractError):
            self.prepare()

    def test_missing_edge_endpoint_rejected(self):
        self.request['edges'][0]['to'] = 'claim-not-wiki-id'
        with self.assertRaises(rw.ContractError):
            self.prepare()

    def test_absolute_index_path_cannot_turn_prepare_into_live_write(self):
        entries=self.ops.load_index(str(self.wiki))
        path=self.wiki/'projects/existing/summary.yml'
        before=path.read_bytes()
        entries['proj-old']['path']=str(path)
        self.ops.save_index(str(self.wiki),entries)
        with self.assertRaises(rw.ContractError):self.prepare()
        self.assertEqual(path.read_bytes(),before)

    def test_revision_cannot_resurrect_deprecated_knowledge(self):
        self.ops.deprecate(str(self.wiki),'corner-1')
        self.prepare();rw.apply(self.repo,self.out)
        self.assertEqual(self.ops.load_entry(str(self.wiki),'corner-lessons/bias.yml')['confidence'],'deprecated')

    def test_existing_trajectory_not_disguised_as_design_changes(self):
        path = self.wiki / 'projects/existing/trajectory.yml'
        old = {'pmu': {'iterations': [{'designer_changes': [{'param': 'original'}]}]}}
        path.write_text(yaml.safe_dump(old))
        self.prepare()
        rw.apply(self.repo, self.out)
        value = yaml.safe_load(path.read_text())
        self.assertEqual(value['pmu']['iterations'], old['pmu']['iterations'])
        self.assertNotIn('designer_changes', value['pmu']['recovery_iterations'][0])

    def test_original_archive_behavior_unchanged_on_temporary_data(self):
        path = self.repo / 'WORK_TEST/iteration-log.yml'
        path.write_text('project: forward\nblocks: {}\nsummary: {}\n')
        key = self.ops.archive_project(str(self.wiki), str(path))
        entries = self.ops.load_index(str(self.wiki))
        self.assertTrue(self.ops.load_entry(str(self.wiki), entries[key]['path'])['convergence'])

    def test_second_update_continues_same_case_without_duplicate_edge(self):
        self.prepare();rw.apply(self.repo,self.out)
        row=json.loads(self.iterpath.read_text());row['iteration']=2
        path=self.repo/'WORK_TEST/iterations-r2.jsonl';path.write_text(json.dumps(row)+'\n')
        self.request.update(update_id='update-2',iterations_ref=dict(path='WORK_TEST/iterations-r2.jsonl',sha256=rw.sha(path.read_bytes())))
        self.out=self.repo/'WORK_TEST/change-r2'
        self.prepare();rw.apply(self.repo,self.out)
        data=self.ops.load_entry(str(self.wiki),'projects/existing/summary.yml')
        self.assertEqual(data['recovery']['question_iterations'],2)
        self.assertEqual(data['total_iterations'],7)
        self.assertEqual(len(self.ops.load_index(str(self.wiki))),2)
        self.assertEqual(len((self.wiki/'edges.jsonl').read_text().splitlines()),1)


if __name__ == '__main__':
    unittest.main()
