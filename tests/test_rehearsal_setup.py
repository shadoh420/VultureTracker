"""Native blank-band and track-management transactions; source, routing and history stay shared."""
import copy
from pathlib import Path
import tempfile
import unittest

from vulturetracker import api, gui, tablature as tab
from vulturetracker.model import Cell, Pattern
from vulturetracker.wavload import write_wav
from tests.test_gui import RATE, sine
from tests import test_tablature as model_fixture


class TestRehearsalSetup(unittest.TestCase):
    def source(self):
        song = model_fixture.TestSectionStructure.source()
        song['score']['tracks']['guitar'].update(name='Lead', color='#234567', clef='alto',
            key=dict(fifths=2, mode='minor'), stem='up', midi=dict(program=25, bank=0),
            lyrics=dict(from_measure=1, text='original words'))
        song['score']['measures'][0]['staff'] = dict(guitar=dict(clef='tenor'))
        for pattern in song['score']['patterns'].values():
            pattern['beats'][0]['notes'][0].update(channel=0, instrument=1, palm_mute=True)
        return song

    def test_clone_metadata_both_voices_ties_and_raw_channels(self):
        song = self.source()
        peer = copy.deepcopy(song['score']['patterns']['A']['beats'][0])
        peer.update(id='peer', voice=1, at=[0, 1])
        peer['notes'][0].update(id='peer-note', pitch=48, string=6, fret=8, channel=5)
        song['score']['patterns']['A']['beats'].append(peer)
        raw = model_fixture.TestSectionStructure.raw(song)
        raw[0].rows[0][6] = Cell(note=40, instrument=1)
        before, raw_before = copy.deepcopy(song), copy.deepcopy(raw)
        after, report = tab.track_command(song, raw, dict(action='track_clone', track='guitar', new_track='clone'))
        track = after['score']['tracks']['clone']
        self.assertEqual(track, dict(song['score']['tracks']['guitar'], channels=list(range(7, 13))))
        self.assertEqual(after['score']['measures'][0]['staff']['clone'], dict(clef='tenor'))
        self.assertEqual(len(after['score']['ties']), 2)
        self.assertEqual(report['channels_added'], 6)
        for pattern in after['score']['patterns'].values():
            original = [b for b in pattern['beats'] if b['track'] == 'guitar']
            copied = [b for b in pattern['beats'] if b['track'] == 'clone']
            self.assertEqual(len(original), len(copied))
            for a, b in zip(original, copied):
                self.assertEqual((a['at'], a['written'], a['voice']), (b['at'], b['written'], b['voice']))
                for left, right in zip(a['notes'], b['notes']):
                    self.assertEqual({k: v for k, v in left.items() if k not in ('id', 'channel')},
                                     {k: v for k, v in right.items() if k not in ('id', 'channel')})
                    self.assertEqual(right['channel'], left['channel'] + 7)
                    self.assertNotEqual(left['id'], right['id'])
        self.assertEqual(song, before)
        self.assertEqual(raw, raw_before)
        self.assertEqual(after['patterns'], song['patterns'])

    def test_move_preserves_routing_and_remove_clears_only_owned_notation(self):
        song = self.source()
        raw = model_fixture.TestSectionStructure.raw(song)
        moved, _ = tab.track_command(song, raw, dict(action='track_move', track='bass', to=0))
        self.assertEqual(list(moved['score']['tracks']), ['bass', 'guitar'])
        self.assertEqual(moved['score']['tracks']['guitar'], song['score']['tracks']['guitar'])
        self.assertEqual(moved['module'], song['module'])
        removed, _ = tab.track_command(song, raw, dict(action='track_remove', track='guitar', remove_notes=True))
        self.assertEqual(list(removed['score']['tracks']), ['bass'])
        self.assertFalse(removed['score']['ties'])
        self.assertNotIn('staff', removed['score']['measures'][0])
        self.assertTrue(all(not p['beats'] for p in removed['score']['patterns'].values()))
        for key in ('patterns', 'module', 'samples'):
            self.assertEqual(removed[key], song[key])
        with self.assertRaisesRegex(ValueError, 'contains score beats'):
            tab.track_command(song, raw, dict(action='track_remove', track='guitar'))

    def test_auto_added_channels_capacity_and_malformed_actions_are_atomic(self):
        song = self.source()
        before = copy.deepcopy(song)
        value = dict(name='New bass', tuning=[43, 38, 33, 28], instrument=1)
        added, report = tab.track_command(song, model_fixture.TestSectionStructure.raw(song), dict(action='track_add', value=value))
        self.assertEqual(added['score']['tracks'][report['track']]['channels'], [7, 8, 9, 10])
        self.assertEqual(song, before)
        for edit in (dict(action='track_clone', track='missing'), dict(action='track_add', track='guitar', value=value),
                     dict(action='track_move', track='bass', to=9), dict(action='track_add', value=dict(value, tuning=[]))):
            with self.subTest(edit=edit), self.assertRaises(ValueError):
                tab.track_command(song, model_fixture.TestSectionStructure.raw(song), edit)
            self.assertEqual(song, before)
        song['module']['channels'] = 60
        with self.assertRaisesRegex(ValueError, '64 channels'):
            tab.track_command(song, [], dict(action='track_clone', track='guitar'))

    def test_blank_templates_have_full_bars_independent_tracks_and_no_notes(self):
        for template, tracks, channels in (('guitar', 1, 6), ('bass', 1, 4), ('drums', 1, 3), ('band', 4, 19)):
            with self.subTest(template=template):
                song = tab.new_score_song('Blank', 'tone.wav', template, bars=8, meter=[5, 4])
                self.assertEqual(len(song['score']['tracks']), tracks)
                self.assertEqual(len(song['module']['channels']), channels)
                self.assertEqual(len(song['orders']), 8)
                self.assertEqual({p['rows'] for p in song['patterns'].values()}, {60})
                self.assertFalse(any(b['notes'] for p in song['score']['patterns'].values() for b in p['beats']))
                self.assertFalse(tab.measure_errors(song, {p: v['rows'] for p, v in song['patterns'].items()}))
                tab.validate_score(song)

    def test_custom_setup_roundtrip_omits_music_and_paths_and_rebinds_sounds(self):
        source = self.source()
        source['score']['tracks']['guitar']['midi']['source_pan'] = dict(value=64, mixer_pan=32)
        setup = tab.score_template(source)
        self.assertNotIn('channels', setup['tracks']['guitar'])
        self.assertNotIn('lyrics', setup['tracks']['guitar'])
        self.assertNotIn('source_pan', setup['tracks']['guitar']['midi'])
        song = tab.new_score_song('New', 'new-tone.wav', setup, bars=2)
        self.assertEqual(song['score']['tracks']['guitar']['color'], '#234567')
        self.assertEqual(song['score']['tracks']['guitar']['key'], dict(fifths=2, mode='minor'))
        self.assertEqual(song['samples'][1]['file'], 'new-tone.wav')
        self.assertFalse(song['score']['ties'])
        self.assertFalse(any(b['notes'] for p in song['score']['patterns'].values() for b in p['beats']))
        for invalid in (dict(setup, raw='ignored?'), dict(setup, tracks={'bad': dict(setup['tracks']['bass'], instrument=1)})):
            with self.assertRaises(ValueError):
                tab.new_score_song('Invalid', 'tone.wav', invalid)
        preset = tab.validate_tuning_preset(dict(name='My tuning', tuning=[62, 57, 55, 50, 45, 38], capo=2))
        self.assertEqual(preset['max_fret'], 29)
        with self.assertRaises(ValueError):
            tab.validate_tuning_preset(dict(preset, channels=[0]))


class TestRehearsalSetupState(unittest.TestCase):
    def test_create_native_file_and_existing_tracker_creation(self):
        with tempfile.TemporaryDirectory() as folder:
            path = gui.create_song(Path(folder) / 'band.yaml', template='band', bars=4)
            song = api.from_yaml(path.read_text(encoding='utf-8'))
            self.assertEqual(len(song['score']['tracks']), 4)
            self.assertEqual(len(song['orders']), 4)
            api.compile_song(path)
            original = path.read_bytes()
            with self.assertRaisesRegex(ValueError, 'exists already'):
                gui.create_song(path, template='guitar')
            self.assertEqual(path.read_bytes(), original)
            tracker = api.from_yaml(gui.create_song(Path(folder) / 'tracker.yaml').read_text(encoding='utf-8'))
            self.assertNotIn('score', tracker)
            self.assertEqual(tracker['patterns']['p00']['rows'], 64)

    def test_track_commands_exact_undo_reopen_and_raw_preservation(self):
        from tests.test_tablature_sync import complete_song_seed
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'song.yaml'
            write_wav(path.parent / 'tone.wav', RATE, [sine(440)])
            source = complete_song_seed()
            source['score']['measures'][0]['staff'] = dict(guitar=dict(clef='alto'))
            path.write_text('# owner comment\n' + api.to_yaml(source), encoding='utf-8', newline='\n')
            st = gui.State(path, headless=True)
            try:
                self.assertFalse(st.error, st.error)
                snapshots = [st.text]
                for body in (dict(action='track_clone', track='guitar', new_track='double'),
                             dict(action='track_move', track='double', to=0),
                             dict(action='track_remove', track='double', remove_notes=True)):
                    st.score_command(dict(body, revision=st.text_sha()))
                    snapshots.append(st.text)
                self.assertEqual(st.song['patterns'], source['patterns'])
                self.assertEqual(st.song['score']['ties'], source['score']['ties'])
                for expected in reversed(snapshots[:-1]):
                    st.undo(); self.assertEqual(st.text, expected)
                for expected in snapshots[1:]:
                    st.undo(redo=True); self.assertEqual(st.text, expected)
                api.compile_song(path)
                final = st.text
            finally:
                st.close()
            reopened = gui.State(path, headless=True)
            try:
                self.assertFalse(reopened.error, reopened.error)
                self.assertEqual(reopened.text, final)
            finally:
                reopened.close()


if __name__ == '__main__':
    unittest.main()
