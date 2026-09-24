"""Task model choice is inherited or explicit, never tied to a vendor default."""
import importlib.util
from pathlib import Path
import tempfile
import unittest

P = Path(__file__).resolve().parents[1] / 'skills/analog-recovery/scripts/task_card.py'
s = importlib.util.spec_from_file_location('task_card_model_test', P)
t = importlib.util.module_from_spec(s)
s.loader.exec_module(t)


class TaskModelTests(unittest.TestCase):
    def test_astra_is_accepted_and_explicit_mismatch_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);p=root/'skills/analog-review/SKILL.md';p.parent.mkdir(parents=True);p.write_text('method')
            output=root/'review.txt';output.write_text('source observation')
            card=t.prepare('REVIEWER','Check ports',root,root)
            card['permissions']['write_roots']=[str(root)]
            card.update(status='completed', inputs=[t.record(p)], outputs=[t.record(output)], acceptance=['port mapping'],
                        agent=dict(id='reviewer',model='gpt-6-astra',effort='medium',model_selection_supported=True,delegated=True),
                        author_id='author',requires_independent=True,
                        closure=dict(reviewer_id='reviewer',evidence_refs=[str(output.resolve())]))
            card['method_results']=[dict(skill='analog-review',observation='mapping checked',output_refs=[str(output.resolve())])]
            self.assertTrue(t.validate(card)['valid'])
            card['requested_agent']={'model':'gpt-6-astra','effort':'high'}
            self.assertIn('unapproved model override',t.validate(card)['errors'])


if __name__=='__main__':unittest.main()
