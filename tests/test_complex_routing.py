"""Safe voice separation preserves notes, music, raw cells and exact history."""
import copy
from pathlib import Path
import tempfile
import unittest

from vulturetracker import api, gui
from vulturetracker.song import SongError
from vulturetracker.wavload import write_wav
from vulturetracker.openmpt import LoadedModule
from tests.test_gui import sine
from tests import test_tablature_page as helpers


def routing_song():
    song = helpers.TestTablaturePage.four_bar_song()
    song['module']['title'] = 'Complex voice routing'
    for name in ('C', 'F'):
        song['score']['patterns'][name]['beats'].append(dict(id='held', track='guitar', voice=1,
            at=[0, 1], written=dict(value=1), notes=[dict(id='held-note', pitch=60, string=2, fret=1, velocity=73)]))
    song['score']['ties'] = [{'from': {'occurrence': 'bar1', 'note': 'held-note'},
                             'to': {'occurrence': 'bar2', 'note': 'held-note'}}]
    return song


def release_routing_song(nna='continue'):
    song = routing_song()
    song['samples'][1]['loop'] = dict(start=0, end=4410)
    song['instruments'][1].update(name='Sustained guitar', nna=nna, fadeout=128,
        volume_envelope=dict(nodes=[[0, 64], [48, 64], [60, 0]], sustain=0),
        panning_envelope=dict(nodes=[[0, -12], [30, 12]]),
        pitch_envelope=dict(nodes=[[0, 0], [15, 2], [30, 0]]))
    # Repeated same-pitch attacks must preserve earlier released tails as well
    # as the long tied voice. DCT or cut/fade NNA would expose a real difference.
    for pattern in song['score']['patterns'].values():
        for beat in pattern['beats']:
            for note in beat['notes']:
                note.update(pitch=60, string=2, fret=1)
    return song


class TestComplexRouting(unittest.TestCase):
    def state(self, song=None):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        folder = temporary.name
        path = Path(folder) / 'song.yaml'
        write_wav(Path(folder) / 'a.wav', 44100, [sine(440)])
        path.write_text('# owner comment\n' + api.to_yaml(song or routing_song()), encoding='utf-8', newline='\n')
        state = gui.State(path, headless=True)
        self.addCleanup(state.close)
        self.assertFalse(state.error, state.error)
        return state

    def route(self, state):
        return state.score_command(dict(action='route_voices', track='guitar', revision=state.text_sha()))

    def test_overlap_ties_export_exact_history_reopen_and_noop(self):
        state = self.state()
        before, original = state.text, copy.deepcopy(state.song)
        prepared = api.prepare_playback(state.song_path, sample_rate=44100)
        with LoadedModule(prepared['backing_it'], 44100, 1, plan=prepared['plan']) as module:
            before_audio = module.render(44100, oversample=1, max_seconds=2)
        with self.assertRaisesRegex(SongError, 'overlap'):
            api.compile_song(state.song, state.base_dir)
        result = self.route(state)
        self.assertGreater(result['moved'], 0)
        data = api.compile_song(state.song, state.base_dir)[0]
        self.assertTrue(data)
        prepared = api.prepare_playback(state.song_path, sample_rate=44100)
        with LoadedModule(prepared['backing_it'], 44100, 1, plan=prepared['plan']) as module:
            after_audio = module.render(44100, oversample=1, max_seconds=2)
        import numpy as np
        before_audio = np.frombuffer(before_audio, dtype='<i2').astype(float) / 32768
        after_audio = np.frombuffer(after_audio, dtype='<i2').astype(float) / 32768
        self.assertLess(float(np.max(np.abs(before_audio - after_audio))), .0001)
        with LoadedModule(data, 44100, 1) as module:
            standalone = module.render(44100, oversample=1, max_seconds=2)
        standalone = np.frombuffer(standalone, dtype='<i2').astype(float) / 32768
        native_rms = float(np.sqrt(np.mean(np.square(after_audio))))
        it_rms = float(np.sqrt(np.mean(np.square(standalone))))
        # IT quantizes MIDI velocity to its 0..64 volume column, as the existing
        # standalone technique checks allow; channel routing itself is PCM-neutral.
        self.assertAlmostEqual(it_rms / native_rms, 1, delta=.04)
        from vulturetracker.itreader import read_it
        exported, _ = read_it(data)
        attacks = sum(c.note is not None and c.note < 120 for p in exported.patterns for row in p.rows for c in row)
        self.assertEqual(attacks, sum(e['type'] == 'note_on' for e in prepared['plan']['events']))
        restored = copy.deepcopy(state.song)
        for pattern in restored['score']['patterns'].values():
            for beat in pattern['beats']:
                for note in beat['notes']:
                    note.pop('channel', None)
        self.assertEqual(restored, original)
        after = state.text
        history = len(state.history)
        self.assertEqual(self.route(state)['moved'], 0)
        self.assertEqual(len(state.history), history)
        state.undo(); self.assertEqual(state.text, before)
        state.undo(redo=True); self.assertEqual(state.text, after)
        state.close()
        reopened = gui.State(state.song_path, headless=True)
        self.addCleanup(reopened.close)
        self.assertFalse(reopened.error, reopened.error)
        self.assertEqual(api.compile_song(reopened.song, reopened.base_dir)[0], data)

    def test_raw_refuses_atomically(self):
        song = routing_song()
        # All physical channels have authored raw state and cannot be reassigned.
        song['patterns']['C']['data'] = '00: ' + ' | '.join(['... .. ... V40'] * 6) + '\n'
        state = self.state(song)
        before = state.text
        with self.assertRaisesRegex(ValueError, 'spare channel'):
            self.route(state)
        self.assertEqual(state.text, before)

    def test_release_tail_and_duplicate_state_refuse_atomically(self):
        for settings in (
                dict(nna='cut', fadeout=128, volume_envelope=dict(nodes=[[0,64],[48,64],[60,0]], sustain=0)),
                dict(nna='fade'), dict(dct='sample', dca='cut'),
                dict(dct='instrument', dca='cut'), dict(fadeout=128)):
            with self.subTest(settings=settings):
                song = routing_song()
                song['samples'][1]['loop'] = dict(start=0, end=4410)
                song['instruments'][1].update(settings)
                state = self.state(song)
                before, history = state.text, len(state.history)
                with self.assertRaisesRegex(ValueError, 'instrument release or voice state'):
                    self.route(state)
                self.assertEqual(state.text, before)
                self.assertEqual(len(state.history), history)

    def test_released_envelopes_continue_and_off_keep_pcm_and_it(self):
        import numpy as np
        from vulturetracker.itreader import read_it
        for nna in ('continue', 'off'):
            with self.subTest(nna=nna):
                state = self.state(release_routing_song(nna))
                original, history = state.text, len(state.history)
                before = api.prepare_playback(state.song_path, sample_rate=44100)
                self.assertGreater(sum('context' in e for e in before['plan']['events']), 0)
                self.assertGreater(self.route(state)['moved'], 0)
                after = api.prepare_playback(state.song_path, sample_rate=44100)
                self.assertFalse(any('context' in e for e in after['plan']['events']))
                for repeat, seek, end in ((0, None, None), (1, None, None), (0, (1, 6), None),
                                          (0, (1, 6), (3, 24))):
                    rendered = []
                    for prepared in (before, after):
                        with LoadedModule(prepared['backing_it'], 44100, 1, plan=prepared['plan']) as mod:
                            if seek:
                                mod.order_start(*seek)
                            rendered.append(mod.render(44100, oversample=1, floats=True, repeat=repeat, end=end))
                    self.assertEqual(rendered[0], rendered[1], (nna, repeat, seek, end))
                data = api.compile_song(state.song, state.base_dir)[0]
                exported, _ = read_it(data)
                self.assertEqual(exported.instruments[0].nna, {'continue': 1, 'off': 2}[nna])
                self.assertEqual(exported.instruments[0].fadeout, 128)
                attacks = sum(c.note is not None and c.note < 120 for p in exported.patterns for row in p.rows for c in row)
                self.assertEqual(attacks, sum(e['type'] == 'note_on' for e in after['plan']['events']))
                with LoadedModule(data, 44100, 1) as mod:
                    standalone = np.frombuffer(mod.render(44100, oversample=1, floats=True, max_seconds=10), '<f4')
                with LoadedModule(after['backing_it'], 44100, 1, plan=after['plan']) as mod:
                    native = np.frombuffer(mod.render(44100, oversample=1, floats=True, max_seconds=10), '<f4')
                standalone = standalone[:len(native)]  # Raw IT caps at its next host block.
                ratio = float(np.sqrt(np.mean(standalone ** 2) / np.mean(native ** 2)))
                self.assertAlmostEqual(ratio, 1, delta=.04)
                difference = float(np.sqrt(np.mean((standalone - native) ** 2) / np.mean(native ** 2)))
                self.assertLess(difference, .04)
                print('release routing', nna, 'native PCM exact; strict IT RMS/native', ratio,
                      'relative PCM RMS error', difference)
                self.assertEqual(len(state.history), history + 1)
                changed = state.text
                self.assertEqual(self.route(state)['moved'], 0)
                self.assertEqual(state.text, changed)
                self.assertEqual(len(state.history), history + 1)
                state.undo(); self.assertEqual(state.text, original)
                state.undo(redo=True); self.assertEqual(state.text, changed)

    def test_continue_needs_spare_lane_for_release_tick(self):
        song = release_routing_song()
        # Two channels can carry the long tied voice plus one short voice, but
        # Continue NNA needs a third for adjacent short notes' explicit IT offs.
        song['score']['tracks']['guitar']['channels'] = [0, 1]
        song['score']['tracks']['guitar']['tuning'] = [64, 59]
        state = self.state(song)
        original, history = state.text, len(state.history)
        with self.assertRaisesRegex(ValueError, 'Part Guitar, bar .*Continue NNA'):
            self.route(state)
        self.assertEqual(state.text, original)
        self.assertEqual(len(state.history), history)

    def test_stateful_native_wasm_replay(self):
        from tests.test_engine import TestEngine
        for nna in ('continue', 'off'):
            with self.subTest(nna=nna):
                state = self.state(release_routing_song(nna))
                self.route(state)
                for rate in (44100, 48000):
                    prepared = api.prepare_playback(state.song_path, sample_rate=rate)
                    report = TestEngine.check_score_replay(self, prepared, state.song_path.parent)
                    self.assertTrue(report['paired_replay'])
                    self.assertGreater(report['checkpointRestores'], 0)
                    print('release routing WASM', nna, rate, 'PCM exact; seek/checkpoint/speed replay pass')

    def test_integer_channel_count_routes(self):
        song = routing_song()
        song['module']['channels'] = 6
        state = self.state(song)
        self.assertGreater(self.route(state)['moved'], 0)
        self.assertTrue(api.compile_song(state.song, state.base_dir)[0])

    def test_capacity_mix_approved_and_stale_refuse_atomically(self):
        song = routing_song()
        song['module']['channels'] = [dict(name='Only lane')]
        song['score']['tracks']['guitar'].update(tuning=[64], channels=[0])
        for pattern in song['score']['patterns'].values():
            for beat in pattern['beats']:
                for note in beat['notes']:
                    note.update(pitch=64, string=1, fret=0)
        state = self.state(song); before = state.text
        with self.assertRaisesRegex(ValueError, 'spare channel'):
            self.route(state)
        self.assertEqual(state.text, before)
        state = self.state()
        before = state.text
        state.meta['muted'] = [0]
        with self.assertRaisesRegex(ValueError, 'mix or mute'):
            self.route(state)
        self.assertEqual(state.text, before)
        state.meta['muted'] = []
        with self.assertRaisesRegex(ValueError, 'changed since'):
            state.score_command(dict(action='route_voices', track='guitar', revision='stale'))
        self.assertEqual(state.text, before)
        song = routing_song(); song['patterns']['C']['approved'] = True
        state = self.state(song); before = state.text
        with self.assertRaisesRegex(ValueError, 'approved'):
            self.route(state)
        self.assertEqual(state.text, before)


if __name__ == '__main__':
    unittest.main()
