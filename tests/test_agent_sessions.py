"""Session tools on disposable songs; fake input only, never the user's microphone."""
import json
import tempfile
import unittest
import yaml
from pathlib import Path
from unittest import mock

from vulturetracker import agent, gui
from vulturetracker.wavload import write_wav
from tests.test_gui import SONG_INS, RATE, sine
from tests.test_record import fake_recorder


class TestAgentSessions(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.d = Path(self.tmp.name)
        for name, hz in [('a', 440), ('b', 880)]:
            write_wav(self.d / (name + '.wav'), RATE, [sine(hz)])
        self.path = self.d / 'song.yaml'
        self.path.write_bytes(yaml.safe_dump(yaml.safe_load(SONG_INS), sort_keys=False).encode())
        self.st = gui.State(self.path, headless=True)
        self.rec = fake_recorder()
        self.patches = [mock.patch.object(gui.Handler, 'state', self.st),
                        mock.patch.object(gui.Handler, 'recorder', self.rec),
                        mock.patch.object(gui.Handler, 'pending_recording', None),
                        mock.patch.object(gui.Handler, 'rec_devices', None)]
        for p in self.patches:
            p.start()

    def tearDown(self):
        self.rec.close()
        self.st.close()
        for p in reversed(self.patches):
            p.stop()
        self.tmp.cleanup()

    def call(self, tool_name, **a):
        out = agent.run(self.st, tool_name, a)
        self.assertFalse(out.get('error'), out)
        return out

    def capture(self, **opts):
        if not self.rec.stream:
            self.call('control_recording', action='open', device=0)
        self.call('control_recording', action='start')
        self.rec.stream.feed(.3)
        return self.call('control_recording', action='stop', name='test', **opts)['take']

    def test_record_save_offer_slot_and_multisample(self):
        status = self.call('recording_status', refresh_devices=True)
        self.assertEqual(status['devices'][0]['id'], 0)
        self.assertIsNone(self.rec.stream)
        before = self.path.read_bytes()
        take = self.capture()
        self.assertEqual(take['dest'], 'keep')
        self.assertEqual(self.path.read_bytes(), before)
        view = self.call('manage_take', action='inspect', file=take['file'])
        self.assertTrue(view['url'].startswith('/take/'))
        self.call('manage_take', action='candidate', file=take['file'])
        self.assertIn(take['path'], self.st.cands())
        self.call('manage_take', action='slot', file=take['file'])
        self.assertEqual(len(self.st.history), 1)
        self.call('manage_take', action='multisample', files=[take['file']])
        self.assertEqual(len(self.st.history), 2)
        self.assertTrue(Path(take['path']).is_file())
        self.call('control_recording', action='close')
        self.assertIsNone(self.rec.stream)

    def test_record_save_failure_retry_and_no_implicit_discard(self):
        self.call('control_recording', action='open', device=0)
        self.call('control_recording', action='start')
        self.rec.stream.feed(.3)
        for action in ('start', 'open', 'close', 'mode'):
            out = agent.run(self.st, 'control_recording', dict(action=action, device=0))
            self.assertIn('error', out)
        with mock.patch.object(self.st, 'save_take', side_effect=OSError('disk full')):
            self.assertIn('error', agent.run(self.st, 'control_recording', {'action': 'stop'}))
        self.assertTrue(self.call('recording_status')['status']['pending_save'])
        self.assertFalse(self.rec.recording)
        for action in ('start', 'open', 'close'):
            self.assertIn('error', agent.run(self.st, 'control_recording', dict(action=action, device=0)))
        with self.assertRaisesRegex(ValueError, 'Save or discard'):
            gui.Handler.open_song(self.path)
        self.call('control_recording', action='stop', trim=False)
        self.assertEqual(len(self.st.takes), 1)
        self.assertIsNone(gui.Handler.pending_recording)
        # A failed send after a successful WAV save retries the send, not the WAV creation.
        self.call('control_recording', action='start')
        self.rec.stream.feed(.2)
        original = self.st.send_take
        def send(name, dest):
            if dest == 'candidate':
                raise ValueError('offer failed')
            return original(name, dest)
        with mock.patch.object(self.st, 'send_take', side_effect=send):
            self.assertIn('error', gui.Handler.rec_command(dict(cmd='stop', trim=False, dest='candidate')))
        count = len(list(self.st.takes_dir.glob('*.wav')))
        self.assertFalse(gui.Handler.rec_command(dict(cmd='stop', trim=False, dest='candidate')).get('error'))
        self.assertEqual(len(list(self.st.takes_dir.glob('*.wav'))), count)
        self.call('control_recording', action='start')
        self.rec.stream.feed(.1)
        self.call('control_recording', action='discard')
        self.assertFalse(self.rec.recording)
        self.assertEqual(len(list(self.st.takes_dir.glob('*.wav'))), count)

    def test_record_validation_and_approved_candidates(self):
        self.assertIn('error', agent.run(self.st, 'control_recording', {'action': 'open', 'device': True}))
        self.assertIn('error', agent.run(self.st, 'control_recording', {'action': 'start', 'preroll': float('nan')}))
        take = self.capture(root=False)
        self.assertIn('error', agent.run(self.st, 'manage_take', dict(action='multisample', files=[take['file']])))
        self.st.song_edit([{'op': 'mark', 'what': 'sample', 'key': self.st.slot, 'approved': True}])
        self.assertIn('error', agent.run(self.st, 'manage_take', dict(action='candidate', file=take['file'])))
        self.st.read_only = 'test read only'
        self.assertIn('error', agent.run(self.st, 'control_recording', {'action': 'start'}))
        self.assertIn('error', agent.run(self.st, 'manage_take', dict(action='slot', file=take['file'])))

    def test_backing_passes_and_settings_history(self):
        self.call('control_recording', action='open', device=0, mode='stereo')
        self.call('control_recording', action='start', backing=True, output=0, countin=0, loops=2)
        plan = self.rec.backing
        self.rec.stream.feed(plan['end'] / self.rec.rate + .1)
        self.assertTrue(self.call('recording_status')['status']['finished'])
        out = self.call('control_recording', action='stop', name='pass')
        self.assertEqual(len(out['takes']), 2)
        self.assertTrue(all(t['channels'] == 2 for t in out['takes']))
        self.assertEqual(out['takes'][0]['seconds'], out['takes'][1]['seconds'])
        self.st._commit(self.st.text, meta=dict(self.st.meta, loop={'from': [0, 0], 'to': [0, 1]}))
        entry = self.call('inspect_history')['entries'][0]
        detail = self.call('inspect_history', index=0, entry_id=entry['entry_id'])['detail']
        self.assertIn('loop', detail['changed_settings'])
        self.assertTrue(detail['settings_lines'])

    def test_listening_notes_revision_context_and_persistence(self):
        before = self.path.read_bytes()
        note = self.call('update_listening_note', action='add', order=0, row=1,
                         channels=[1], text='Too bright', tag='sound')['note']
        self.assertEqual(note['channels'], [0])  # stored NOTES channels retain the existing 0-based shape
        rev = note.pop('revision')
        changed = self.call('update_listening_note', action='update', note_id=note['id'], revision=rev,
                            text='Try a darker sound')['note']
        self.assertEqual(changed['sounding'], note['sounding'])
        self.assertEqual(changed['playing'], note['playing'])
        self.assertIn('error', agent.run(self.st, 'update_listening_note',
                                       dict(action='delete', note_id=note['id'], revision=rev)))
        read = self.call('read_notes')['notes'][0]
        self.assertEqual(read['revision'], changed['revision'])
        self.assertEqual(json.loads(self.st.notes_path.read_text())['notes'][0]['text'], 'Try a darker sound')
        self.assertIn('Try a darker sound', self.st.notes_path.with_suffix('.md').read_text())
        self.call('update_listening_note', action='delete', note_id=note['id'], revision=read['revision'])
        self.assertEqual(self.call('read_notes')['notes'], [])
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(self.st.history, [])
        self.assertIn('error', agent.run(self.st, 'update_listening_note', dict(action='add', order=0, row=999, text='bad')))

    def test_history_details_redo_staleness_and_assets(self):
        self.call('set_module', key='title', value='First change')
        self.call('set_module', key='title', value='Changed')
        overview = self.call('inspect_history', limit=1)
        self.assertEqual(overview['total'], 2)
        self.assertEqual(overview['next_offset'], 1)
        entry = overview['entries'][0]
        before = self.path.read_bytes()
        detail = self.call('inspect_history', index=0, entry_id=entry['entry_id'], max_lines=1)['detail']
        self.assertTrue(detail['truncated'])
        self.assertTrue(detail['restorable'], detail)
        self.assertEqual(self.path.read_bytes(), before)
        self.call('undo')
        self.assertEqual(self.call('inspect_history', stack='redo')['total'], 1)
        self.assertIn('error', agent.run(self.st, 'inspect_history', dict(index=0, entry_id=entry['entry_id'])))
        redo = self.call('inspect_history', stack='redo')['entries'][0]
        (self.d / 'a.wav').write_bytes((self.d / 'b.wav').read_bytes())
        detail = self.call('inspect_history', stack='redo', index=0, entry_id=redo['entry_id'])['detail']
        self.assertFalse(detail['restorable'])
        self.assertIn('source asset changed', detail['restore_error'])

    def test_transport_queues_requests_without_editing_song(self):
        before = self.path.read_bytes()
        first = self.call('pause_playback')
        self.assertEqual(self.st.cue['action'], 'pause')
        second = self.call('resume_playback')
        self.assertEqual(self.st.cue['action'], 'resume')
        self.assertGreater(second['request_id'], first['request_id'])
        self.assertEqual(self.path.read_bytes(), before)


if __name__ == '__main__':
    unittest.main()
