"""Public history survives missing local sessions and repeated exports."""
from contextlib import redirect_stdout
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('export_interactions', ROOT/'build/scripts/export_interactions.py')
exporter = importlib.util.module_from_spec(spec)
spec.loader.exec_module(exporter)


def source(path, session, role='user', channel=None, text='project question'):
    rows = [{'type': 'session_meta', 'payload': {'id': session}},
            {'timestamp': '2026-10-25T01:00:00Z', 'type': 'response_item',
             'payload': {'type': 'message', 'role': role, 'channel': channel,
                         'content': [{'type': 'input_text', 'text': text}]}}]
    path.write_text(''.join(json.dumps(r)+'\n' for r in rows), encoding='utf-8')


class InteractionTests(unittest.TestCase):
    def test_selection_removes_other_chats_and_does_not_restore_them_on_merge(self):
        with tempfile.TemporaryDirectory() as temp, redirect_stdout(io.StringIO()):
            root = Path(temp)
            chosen, other, output = root/'chosen.jsonl', root/'other.jsonl', root/'export'
            prefix = 'Selected phase measurement conversation'
            source(chosen, 'chosen_session', text=prefix + ': original request')
            source(other, 'other_session', text='Different conversation quoting ' + prefix)
            exporter.export([chosen, other], output)
            (output/'selection.json').write_text(json.dumps({'first_user_message_prefix': prefix}))
            exporter.export([chosen], output)
            exporter.export([other], output)
            messages = [json.loads(line) for line in (output/'messages.jsonl').read_text(encoding='utf-8').splitlines()]
            self.assertEqual({m['session_id'] for m in messages}, {'chosen_session'})
            self.assertEqual({p['session_id'] for p in json.loads((output/'sources.json').read_text())}, {'chosen_session'})
            self.assertNotIn('Different conversation', (output/'transcript.md').read_text(encoding='utf-8'))

    def test_wrong_selection_replacement_preserves_previously_exported_files(self):
        with tempfile.TemporaryDirectory() as temp, redirect_stdout(io.StringIO()):
            root = Path(temp)
            chosen, other, output = root/'chosen.jsonl', root/'other.jsonl', root/'export'
            source(chosen, 'chosen_session', text='Selected first message')
            source(other, 'other_session', text='A different conversation')
            exporter.export([chosen], output)
            original = (output/'messages.jsonl').read_bytes()
            (output/'selection.json').write_text(json.dumps({'first_user_message_prefix': 'Selected first message'}))
            with self.assertRaisesRegex(ValueError, 'Exactly one conversation'):
                exporter.export([other], output, replace=True)
            self.assertEqual((output/'messages.jsonl').read_bytes(), original)

    def test_preserves_previous_chat_when_only_new_session_available(self):
        with tempfile.TemporaryDirectory() as temp, redirect_stdout(io.StringIO()):
            root = Path(temp)
            old, new, output = root/'old.jsonl', root/'new.jsonl', root/'export'
            source(old, 'old_session')
            exporter.export([old], output)
            old.unlink()
            source(new, 'new_session', text='new project question')
            exporter.export([new], output)
            messages = [json.loads(line) for line in (output/'messages.jsonl').read_text(encoding='utf-8').splitlines()]
            self.assertEqual({m['session_id'] for m in messages}, {'old_session','new_session'})
            self.assertEqual(len(json.loads((output/'sources.json').read_text())), 2)

    def test_repeat_deduplicates_and_internal_reasoning_is_excluded(self):
        with tempfile.TemporaryDirectory() as temp, redirect_stdout(io.StringIO()):
            root = Path(temp)
            public, hidden, output = root/'public.jsonl', root/'hidden.jsonl', root/'export'
            source(public, 'session', text='public project reply')
            source(hidden, 'session', role='assistant', channel='analysis', text='internal reasoning')
            exporter.export([public, hidden], output)
            exporter.export([public, hidden], output)
            self.assertEqual(len((output/'messages.jsonl').read_text(encoding='utf-8').splitlines()), 1)
            self.assertNotIn('internal reasoning', (output/'transcript.md').read_text(encoding='utf-8'))


if __name__ == '__main__': unittest.main(verbosity=2)
