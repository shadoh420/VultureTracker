"""Exact standalone rhythm delivery without changing the authored tracker grid."""
import copy
import tempfile
import unittest
from pathlib import Path

from vulturetracker import api, tablature
from vulturetracker.model import Cell, Pattern
from vulturetracker.openmpt import LoadedModule
from vulturetracker.itreader import read_it
from vulturetracker.song import SongError
from vulturetracker.wavload import write_wav
from tests.test_tablature import beat, note
from tests.test_tablature_sync import score_song
from tests.test_pipeline import sine


def advanced_timing_song():
    """A pickup of 32nd triplets, then a second voice under regular quarters."""
    song = score_song()
    song['module'].update(title='Advanced rhythm IT', speed=6)
    song['patterns']['a']['rows'] = 2
    song['patterns']['b']['rows'] = 16
    song['score']['ties'] = []
    for spec in song['score']['patterns'].values():
        spec.update(row_step=[1, 4], beats=[])
    song['score']['patterns']['a']['beats'] = [
        beat(f't{i}', [i, 12], [dict(note(f'n{i}', 64 + i, 1, i), velocity=127)], 32, [3, 2])
        for i in range(6)]
    song['score']['patterns']['b']['beats'] = [
        beat('melody', [0, 1], [dict(note('melody', 64, 1, 0), velocity=127)]),
        beat('bass', [0, 1], [dict(note('bass', 59, 2, 0), velocity=127)], 2, voice=1)]
    song['score']['measures'] = [
        dict(id='pickup', meter=[1, 8], **{'from': dict(occurrence='first', at=[0, 1]),
                                         'to': dict(occurrence='first', at=[1, 2])}),
        dict(id='bar', meter=[4, 4], **{'from': dict(occurrence='second', at=[0, 1]),
                                     'to': dict(occurrence='second', at=[4, 1])})]
    return song


class TestAdvancedTiming(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        write_wav(self.base / 'tone.wav', 44100, [sine(441)])

    def assert_export(self, song, raw_channels=()):
        original = copy.deepcopy(song)
        native = api.prepare_playback(song, base_dir=self.base, sample_rate=48000)
        data, compiled, _ = api.compile_song(song, self.base)
        imported, _ = read_it(data)
        expected = sorted((e['frame'] / 48000, e['ch'], e['pitch'])
                          for e in native['plan']['events'] if e['type'] == 'note_on')
        attacks = []
        with LoadedModule(data, 48000, 1) as module:
            for oi, pi in enumerate(imported.orders):
                if pi >= 254:
                    continue
                for ri, row in enumerate(imported.patterns[pi].rows):
                    for ci, cell in enumerate(row):
                        if ci in raw_channels:
                            continue
                        if cell.note is not None and cell.note < 120:
                            self.assertNotEqual((cell.effect, cell.param >> 4), (19, 13))
                            attacks.append((module.order_start(oi, ri), ci, cell.note))
            self.assertAlmostEqual(module.duration(), native['plan']['duration']['frames'] / 48000, delta=.002)
        self.assertEqual(len(attacks), len(expected))
        for actual, target in zip(sorted(attacks), expected):
            self.assertEqual(actual[1:], target[1:])
            self.assertAlmostEqual(actual[0], target[0], delta=.002)
        self.assertEqual(song, original)
        return compiled, data, native

    def test_pickup_triplets_two_voices_raw_pan_and_absolute_tempo(self):
        song = advanced_timing_song()
        song['patterns']['b']['data'] = '\n'.join(
            f'{i:02}: ... .. ... ... | ... .. ... ... | ... .. ... ' + ('T60' if i == 4 else '...')
            for i in range(5))
        compiled, _, _ = self.assert_export(song)
        self.assertEqual([len(p.rows) for p in compiled.patterns], [6, 48])
        self.assertEqual((compiled.patterns[0].rows[0][0].effect, compiled.patterns[0].rows[0][0].param), (24, 64))
        self.assertEqual((compiled.patterns[1].rows[12][2].effect, compiled.patterns[1].rows[12][2].param), (20, 96))
        self.assertIn('3 export rows', ' '.join(compiled.score_projection.diagnostics))

    def test_high_speed_delays_and_64th_triplets_are_exact(self):
        song = advanced_timing_song()
        song['module']['speed'] = 24
        song['patterns']['a']['rows'] = 1
        song['patterns']['b']['rows'] = 4
        song['score']['measures'] = []
        for spec in song['score']['patterns'].values():
            spec['row_step'] = [1, 1]
        song['score']['patterns']['a']['beats'] = [
            beat('late', [17, 24], [dict(note('late', 64, 1, 0), velocity=127)], 64, [3, 2])]
        compiled, _, _ = self.assert_export(song)
        self.assertEqual([len(p.rows) for p in compiled.patterns], [24, 96])

    def test_repeats_keep_exact_rhythm_and_timeline(self):
        song = advanced_timing_song()
        song['score']['measures'][0].update(repeat_open=True, repeat_close=1)
        compiled, _, _ = self.assert_export(song)
        self.assertEqual(len(compiled.orders), 3)

    def test_dense_repetition_preserves_documented_final_pulse_tail(self):
        from tests.test_tablature_sync import native_repetition_it_song
        write_wav(self.base / 'upper.wav', 44100, [sine(882)])
        song = native_repetition_it_song()
        song['module']['speed'] = 6
        for pattern in song['patterns'].values():
            pattern['rows'] = 16
        for spec in song['score']['patterns'].values():
            spec['row_step'] = [1, 4]
        compiled, _, _ = self.assert_export(song)
        self.assertTrue(any('export rows' in text for text in compiled.score_projection.diagnostics))
        self.assertTrue(any('1/960 quarter' in text for text in compiled.score_projection.diagnostics))

    def test_staccato_pitch_turns_fit_finer_rows_without_relaxing_bound(self):
        from tests.test_tablature_sync import native_pitch_it_song
        song = native_pitch_it_song()
        song['score']['patterns']['a']['beats'][0]['notes'][0]['staccato'] = True
        compiled, _, _ = self.assert_export(song)
        self.assertEqual(len(compiled.patterns[0].rows), 96)
        self.assertTrue(any('37.5 cents' in text for text in compiled.score_projection.diagnostics))
        pitch_cells = [cell for row in compiled.patterns[0].rows for cell in row if cell.effect in (5, 6)]
        self.assertTrue(pitch_cells)
        self.assertTrue(all(0xF1 <= cell.param <= 0xFF for cell in pitch_cells))

    def test_repetition_delay_and_raw_pan_can_use_separate_exact_rows(self):
        from tests.test_tablature_sync import native_repetition_it_song
        write_wav(self.base / 'upper.wav', 44100, [sine(882)])
        song = native_repetition_it_song()
        song['patterns']['a']['data'] = '\n'.join(
            f'{r:02}: ... .. ... ' + ('X40' if r == 13 else '...') for r in range(14))
        compiled, _, _ = self.assert_export(song)
        factor = len(compiled.patterns[0].rows) // song['patterns']['a']['rows']
        self.assertGreater(factor, 1)
        cell = compiled.patterns[0].rows[13 * factor][0]
        self.assertEqual((cell.effect, cell.param), (24, 64))

    def test_gate_release_and_raw_pan_keep_their_independent_ticks(self):
        from tests.test_tablature_sync import native_it_song
        song = native_it_song()
        song['score']['patterns']['a']['beats'][0]['notes'][0]['palm_mute'] = True
        song['patterns']['a']['data'] += '01: ... .. ... X40\n'
        compiled, _, _ = self.assert_export(song)
        factor = len(compiled.patterns[0].rows) // song['patterns']['a']['rows']
        self.assertGreater(factor, 1)
        cell = compiled.patterns[0].rows[factor][0]
        self.assertEqual((cell.effect, cell.param), (24, 64))

    def test_tick_envelope_pcm_matches_at_integer_sample_clock(self):
        import numpy as np
        song = advanced_timing_song()
        song['samples'][1]['loop'] = dict(start=0, end=22000)
        song['instruments'] = {1: dict(sample=1, volume_envelope=dict(nodes=[[0, 0], [1, 64], [2, 48], [4, 0]], sustain=2))}
        song['patterns']['a']['data'] = ('00: ... .. ... X40 | ' + '... .. ... ... | ' * 4 + 'C-3 01 v32 X60\n'
                                       '01: ' + '... .. ... ... | ' * 5 + '=== .. ... ...')
        compiled, data, native = self.assert_export(song, raw_channels=(5,))
        self.assertEqual(compiled.patterns[0].rows[0][5].volcmd, 32)
        self.assertEqual(compiled.patterns[0].rows[3][5].note, 255)
        signals = []
        for backing, plan in ((native['backing_it'], native['plan']), (data, None)):
            with LoadedModule(backing, 48000, 1, plan=plan) as module:
                pcm = module.render(rate=48000, oversample=1, max_seconds=2)
                signals.append(np.frombuffer(pcm, dtype='<i2').astype(float)[:48000 * 2 * 2])
        self.assertEqual(signals[0].shape, signals[1].shape)
        error = np.sqrt(np.mean((signals[0] - signals[1]) ** 2))
        level = np.sqrt(np.mean(signals[0] ** 2))
        self.assertLess(error / level, .005)
        print(f'Advanced rhythm envelope PCM relative RMS error: {error / level:.8f}')

    def test_unsafe_raw_effect_offtick_and_row_capacity_refuse_without_mutation(self):
        base = advanced_timing_song()
        cases = []
        song = copy.deepcopy(base)
        song['patterns']['a']['data'] = '00: ... .. ... D01'
        cases.append((song, 'raw tick/row effects'))
        song = copy.deepcopy(base)
        song['score']['patterns']['a']['beats'][0]['written']['tuplet'] = [5, 4]
        song['score']['patterns']['a']['beats'] = song['score']['patterns']['a']['beats'][:1]
        cases.append((song, 'not representable'))
        song = copy.deepcopy(base)
        song['module']['speed'] = 24
        song['patterns']['a']['rows'] = 1
        song['patterns']['b']['rows'] = 200
        song['score']['measures'] = []
        for spec in song['score']['patterns'].values():
            spec['row_step'] = [1, 1]
        song['score']['patterns']['a']['beats'] = [
            beat('late', [17, 24], [note('late', 64, 1, 0)], 64, [3, 2])]
        cases.append((song, 'more than 1024 rows'))
        target = self.base / 'existing.it'
        target.write_bytes(b'prior delivery')
        for song, message in cases:
            before = copy.deepcopy(song)
            with self.subTest(message=message), self.assertRaisesRegex(SongError, message):
                api.build(song, target, self.base)
            self.assertEqual(song, before)
            self.assertEqual(target.read_bytes(), b'prior delivery')

    def test_existing_rows_and_raw_input_unchanged_when_no_subdivision_needed(self):
        song = advanced_timing_song()
        song['score']['patterns']['a']['beats'] = [beat('plain', [0, 1], [note('plain', 64, 1, 0)], 8)]
        raw = [Pattern(name, [[Cell() for _ in range(6)] for _ in range(spec['rows'])])
               for name, spec in song['patterns'].items()]
        before = copy.deepcopy(raw)
        result = tablature.project_score(song, raw)
        self.assertEqual([len(p.rows) for p in result.patterns], [2, 16])
        self.assertFalse(any(c.effect == 1 for p in result.patterns for row in p.rows for c in row))
        self.assertEqual(raw, before)


if __name__ == '__main__':
    unittest.main()
