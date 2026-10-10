"""Phrase and project tool boundaries on disposable songs; no providers or user settings."""
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest import mock

from vulturetracker import agent, api, gui
from vulturetracker.wavload import write_wav
from tests.test_gui import SONG_BLOCK, RATE, sine


class ProjectToolsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        for name, hz in [('a', 440), ('b', 880)]:
            write_wav(self.dir / (name + '.wav'), RATE, [sine(hz)])
        self.path = self.dir / 'song.yaml'
        self.path.write_text(SONG_BLOCK, encoding='utf-8')
        self.st = gui.State(self.path, headless=True)
        self.states = [self.st]
        self.chat = agent.Chat()
        self.patches = [mock.patch.object(gui.Handler, 'state', self.st),
                        mock.patch.object(gui, 'CHAT', self.chat), mock.patch.object(gui, 'remember_song')]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for st in set(self.states + [gui.Handler.state]):
            if st is not None and not st.closed:
                if not st.headless:
                    for _ in range(100):
                        if not st.jobs.qsize() and not any(r['status'] in ('queued', 'rendering') for r in st.renders.values()):
                            break
                        time.sleep(.02)
                st.close()
        for p in reversed(self.patches):
            p.stop()
        self.tmp.cleanup()

    def call(self, tool_name, **a):
        out = agent.run(gui.Handler.state, tool_name, a)
        self.assertNotIn('error', out, out)
        return out

    def capture(self, **a):
        return self.call('capture_phrase', order=0, r0=0, r1=3, channels=[1], **a)['id']

    def test_phrase_drafts_render_diff_and_owner_boundaries(self):
        before = self.path.read_bytes()
        ident = self.capture(count=2)
        data = 'D-5 01 ... ...\n... .. ... ...\n... .. ... ...\n... .. ... ...'
        self.call('edit_phrase', phrase_id=ident, variant=0, name='Moving line', data=data)
        read = self.call('read_phrase', variant=0, limit=2)
        self.assertEqual(read['channels'], [1])
        self.assertEqual(read['next_offset'], 2)
        self.assertTrue(read['rows'][0].startswith('D-5'))
        outputs = [self.call('render_phrase', phrase_id=ident, variant=i) for i in (0, 1, -1)]
        self.assertEqual(len({Path(o['path']).read_bytes() for o in outputs}), 3)
        self.assertTrue(self.call('phrase_diff', phrase_id=ident, variant=0)['lines'])
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(len(self.st.history), 0)
        for a in [dict(phrase_id='stale', variant=0, data=data), dict(phrase_id=ident, variant=0, stars=5),
                  dict(phrase_id=ident, variant=-1, data=data),
                  dict(phrase_id=ident, variant=0, data=data.replace('D-5 01 ... ...', 'D-5 01 ... A03'))]:
            self.assertIn('error', agent.run(self.st, 'edit_phrase', a))
        self.assertNotIn('accept_phrase', agent.TOOLS)
        self.assertEqual(self.st.meta['phrase']['variants'][0]['stars'], 0)
        self.assertIn('error', agent.run(self.st, 'capture_phrase', dict(order=0, r0=0, r1=3, channels=[1])))
        new_id = self.capture(replace_id=ident)
        self.assertNotEqual(new_id, ident)
        self.assertTrue((self.dir / 'song.phrases' / (ident + '.json')).is_file())

    def test_frozen_phrase_survives_changed_audio_and_rejects_accept_diff(self):
        ident = self.capture()
        out = self.call('render_phrase', phrase_id=ident, variant=0)
        raw = Path(out['path']).read_bytes()
        Path(out['path']).unlink()
        (self.dir / 'a.wav').write_bytes((self.dir / 'b.wav').read_bytes())
        self.assertTrue(self.call('read_phrase')['stale'])
        self.assertEqual(Path(self.call('render_phrase', phrase_id=ident, variant=0)['path']).read_bytes(), raw)
        self.assertIn('error', agent.run(self.st, 'phrase_diff', dict(phrase_id=ident, variant=0)))
        self.assertIn('error', agent.run(self.st, 'edit_phrase', dict(phrase_id=ident, variant=0, name='Changed')))

    def test_phrase_approval_and_read_only(self):
        self.st.song_edit([{'op': 'mark', 'what': 'channel', 'key': 0, 'approved': True}])
        self.assertIn('error', agent.run(self.st, 'capture_phrase', dict(order=0, r0=0, r1=3, channels=[1])))
        self.st.read_only = 'read only test'
        self.assertIn('error', agent.run(self.st, 'capture_phrase', dict(order=0, r0=0, r1=3, channels=[2])))
        self.assertIsNone(self.st.meta.get('phrase'))

    def test_create_open_and_followup_in_same_chat(self):
        before = self.path.read_bytes()
        made = self.call('create_project', path='new.yaml', channels=3, sample='a.wav')
        self.assertIs(gui.Handler.state, self.st)
        self.assertIn('error', agent.run(self.st, 'create_project', dict(path='new.yaml')))
        self.chat.busy = True
        self.chat.tool_state = self.st
        with self.assertRaisesRegex(ValueError, 'Stop the agent'):
            gui.Handler.open_song(made['path'])
        opened = self.chat._tool(self.st, 'open_project', {'path': made['path']})
        self.assertNotIn('error', opened, opened)
        self.assertTrue(self.st.closed)
        self.assertEqual(self.chat._tool(self.st, 'get_state', {})['path'], made['path'])
        self.assertNotIn('error', self.chat._tool(self.st, 'create_channel', {'name': 'New part'}))
        self.assertEqual(len(gui.Handler.state.mod.channels), 4)
        self.assertEqual(self.path.read_bytes(), before)
        self.assertIn('error', agent.run(self.st, 'create_channel', {}))
        self.chat.cancel.set()
        self.assertIn('error', self.chat._tool(self.st, 'create_channel', {}))

    def test_open_guards_and_no_song_tools(self):
        made = self.call('create_project', path='next.yaml', channels=1)
        for attr, val in [('synthesis_job', {'status': 'rendering'}), ('export_result', {'status': 'queued'}),
                          ('recipe_job', {'status': 'fetching'}), ('ui_state', {'pending_edits': 1})]:
            with mock.patch.object(self.st, attr, val):
                self.assertIn('error', agent.run(self.st, 'open_project', {'path': made['path']}))
            self.assertIs(gui.Handler.state, self.st)
        with mock.patch.object(gui.Handler, 'recorder', mock.Mock(recording=True)):
            self.assertIn('error', agent.run(self.st, 'open_project', {'path': made['path']}))
        with mock.patch.object(self.st, 'dirty', return_value=True):
            self.assertIn('error', agent.run(self.st, 'open_project', {'path': made['path']}))
        self.assertIn('error', agent.run(self.st, 'open_project', {'path': 'missing.yaml'}))
        with mock.patch.object(gui.Handler, 'state', None), mock.patch.object(gui, 'recent_songs', return_value=[]):
            self.assertIsNone(self.call('project_status')['song'])
            created = self.call('create_project', path=str(self.dir / 'from-start.yaml'), channels=2)
            self.assertTrue(Path(created['path']).is_file())
            self.assertIn('error', agent.run(None, 'write_cells', {}))

    def test_import_and_collect_preserve_original_and_phrase(self):
        ident = self.capture()
        frozen = self.call('render_phrase', phrase_id=ident, variant=0)
        src = self.dir / 'input.it'
        src.write_bytes(self.st.it)
        original = src.read_bytes()
        first = self.call('import_project', file=str(src))
        second = self.call('import_project', file=str(src))
        self.assertNotEqual(first['path'], second['path'])
        self.assertEqual(src.read_bytes(), original)
        self.assertTrue(api.check(first['path'])['ok'])
        with tempfile.TemporaryDirectory() as outer:
            dest = Path(outer) / 'portable'
            collected = self.call('collect_project', destination=str(dest), zip=True)
            self.assertTrue(Path(collected['zip']).is_file())
            self.assertIn('error', agent.run(self.st, 'collect_project', {'destination': str(dest)}))
            new = gui.State(collected['path'], headless=True)
            self.states.append(new)
            rendered = agent.run(new, 'render_phrase', dict(phrase_id=ident, variant=0))
            self.assertEqual(Path(rendered['path']).read_bytes(), Path(frozen['path']).read_bytes())
            new.close()
            asset = self.dir / next(iter(self.st.meta['phrase']['assets']))
            asset.write_bytes((self.dir / 'b.wav').read_bytes())
            self.assertIn('error', agent.run(self.st, 'collect_project', {'destination': str(Path(outer) / 'tampered')}))
            self.assertFalse((Path(outer) / 'tampered').exists())

    def test_relink_missing_files_atomically_and_preserve_approvals(self):
        self.st.close()
        self.path.write_text(SONG_BLOCK.replace('a.wav', 'missing.wav'), encoding='utf-8')
        st = gui.Handler.state = gui.State(self.path, headless=True)
        self.states.append(st)
        self.assertEqual(self.call('project_status')['missing'][0]['slot'], 1)
        before = self.path.read_bytes()
        self.assertIn('error', agent.run(st, 'relink_samples', {'links': {'1': 'a.wav', '2': 'absent.wav'}}))
        self.assertEqual(self.path.read_bytes(), before)
        self.call('relink_samples', links={'1': 'a.wav'})
        self.assertFalse(st.error)
        self.assertEqual(len(st.history), 1)
        st.song_edit([{'op': 'mark', 'what': 'sample', 'key': 1, 'approved': True}])
        self.assertIn('error', agent.run(st, 'relink_samples', {'links': {'1': 'b.wav'}}))
        self.assertTrue(st.song['samples'][1]['approved'])


if __name__ == '__main__':
    unittest.main()
