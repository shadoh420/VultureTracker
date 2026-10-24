"""Complete expressive notes can cross new bars without changing their performance."""
import copy
import tempfile
import unittest
from fractions import Fraction
from pathlib import Path

from tests import test_tablature as fixtures
from tests.test_gui import RATE, sine
from tests.test_real_arrangement import divided_song, raw_for
from tests.test_tablature_sync import it_cells
from vulturetracker import api, gui, tablature as tab
from vulturetracker.model import Module, Cell
from vulturetracker.wavload import write_wav


EFFECTS = [dict(vibrato=True), dict(staccato=True), dict(palm_mute=True), dict(dead=True),
    dict(hammer=True), dict(fade_in=True), dict(harmonic=dict(type='artificial', data=0)),
    dict(grace=dict(fret=2, value=16, velocity=47, on_beat=True)),
    dict(trill=dict(fret=7, value=16)), dict(tremolo_picking=dict(value=16)),
    dict(bend=dict(points=[dict(position=0, value=0), dict(position=12, value=2)])),
    dict(tremolo_bar=dict(points=[dict(position=0, value=0), dict(position=12, value=-1)]))]


def expressive_song(effect=None):
    song = fixtures.TestSectionStructure.source()
    song['score']['ties'] = []
    song['score']['patterns']['A']['beats'][0]['notes'][0].update(effect or dict(vibrato=True))
    return song


def performance(song, *, after=None, shift=0, raw_patterns=None):
    events = tab.playback_plan(song, raw_for(song) if raw_patterns is None else raw_patterns)['events']
    return [{k: (v + shift if k == 'frame' else v) for k, v in e.items()
        if k not in ('id', 'source_id', 'occurrence', 'beat', 'note', 'pattern', 'order', 'at', 'seconds')}
        for e in events if after is None or e['id'].startswith(after)]


class TestComplexRhythm(unittest.TestCase):
    def test_rebar_and_move_preserve_full_expressive_performance(self):
        for effect in EFFECTS:
            with self.subTest(effect=effect):
                song = expressive_song(effect)
                before = copy.deepcopy(song)
                result = tab.measure_command(song, dict(action='measure_meter', at=0, meter=[3, 4], to_end=True))['song']
                self.assertEqual(performance(result), performance(song))
                moved, _ = tab.score_command(song, raw_for(song), dict(action='move_beats', occurrence='oa',
                    track='guitar', at=[0, 1], direction='right', amount=[1, 1]))
                self.assertEqual(performance(moved), performance(song, shift=22050))
                self.assertEqual(song, before)

    def test_divided_measure_preparation_keeps_expressive_crossing_notes(self):
        for effect in EFFECTS:
            with self.subTest(effect=effect):
                song = divided_song()
                for beat in song['score']['patterns']['A']['beats']:
                    beat['notes'][0]['velocity'] = 90
                song['score']['patterns']['A']['beats'][1]['notes'][0].update(effect)
                result = tab.prepare_score_measures(song, raw_for(song))['song']
                self.assertEqual(performance(result), performance(song))
                self.assertEqual(len(result['score']['ties']), 2)

    def test_existing_tie_chain_and_second_voice_keep_combined_expression(self):
        song = fixtures.TestSectionStructure.source()
        head = song['score']['patterns']['A']['beats'][0]['notes'][0]
        head.update(bend=dict(points=[dict(position=0, value=0), dict(position=12, value=2)]),
                    harmonic=dict(type='artificial', data=0),
                    grace=dict(fret=2, value=16, velocity=47, on_beat=True))
        song['score']['patterns']['A']['beats'].append(fixtures.beat('voice2', [0, 1],
            [dict(fixtures.note('voice2n', 59, 2, 0), velocity=70, vibrato=True)], value=1, voice=1))
        before = copy.deepcopy(song)
        result = tab.measure_command(song, dict(action='measure_meter', at=0, meter=[3, 4], to_end=True))['song']
        self.assertEqual(performance(result), performance(song))
        self.assertEqual(song, before)

    def test_paste_complete_span_preserves_effects_and_head_only_notation(self):
        for effect in EFFECTS:
            with self.subTest(effect=effect):
                song = expressive_song(effect)
                source = song['score']['patterns']['A']['beats'][0]
                source['text'] = 'Expressive phrase'
                clip = tab.capture_score_clipboard(song, 'A', ['whole'], 'oa')
                pasted = tab.paste_score_clipboard(song, Module(patterns=raw_for(song)), 2, 36,
                    clip, 'oc', across=True, replace=True)
                copied = performance(pasted, after='oc/copy_')
                self.assertEqual(copied, performance(song, after='oa/', shift=11 * 22050))
                tails = [b for b in pasted['score']['patterns']['D']['beats'] if b['id'].startswith('copy_')]
                self.assertTrue(tails)
                self.assertTrue(all('text' not in b for b in tails))
                key = next(iter(effect))
                if key != 'hammer':
                    self.assertTrue(all(key not in n for b in tails for n in b['notes']))

    def test_dependent_splits_and_truncated_paste_refuse_atomically(self):
        for effect in (dict(slide=True),):
            song = expressive_song(effect)
            before = copy.deepcopy(song)
            with self.assertRaisesRegex(ValueError, 'splitting a technique'):
                tab.measure_command(song, dict(action='measure_meter', at=0, meter=[3, 4], to_end=True))
            self.assertEqual(song, before)
        song = expressive_song(dict(bend=dict(points=[dict(position=0, value=0), dict(position=12, value=2)])))
        clip = tab.capture_score_clipboard(song, 'B', ['whole'], 'ob')
        before = copy.deepcopy(song)
        with self.assertRaisesRegex(ValueError, 'bend crop'):
            tab.paste_score_clipboard(song, Module(patterns=raw_for(song)), 0, 12,
                clip, 'oa', across=True, replace=True)
        self.assertEqual(song, before)
        # The same representable span must also retain TG's integer tick count.
        beat = copy.deepcopy(song['score']['patterns']['A']['beats'][0])
        beat['written'] = dict(value=4, dots=0, tuplet=[1, 1])
        with self.assertRaisesRegex(ValueError, 'performed tick duration'):
            tab._split_moved_beat(beat, Fraction(0), [Fraction(1, 7)])

    def test_ring_and_strum_complete_crossings_keep_performance(self):
        for kind in ('let_ring', 'stroke'):
            song = expressive_song(dict(let_ring=True) if kind == 'let_ring' else dict(vibrato=True))
            if kind == 'let_ring':
                # The next sounding beat must stay intact: TG adds that beat's
                # entire duration to let-ring, even on a different string.
                song['score']['patterns']['B']['beats'][0]['notes'] = []
            if kind == 'stroke':
                head = song['score']['patterns']['A']['beats'][0]
                head['stroke'] = dict(direction='down', value=8)
                head['notes'].append(dict(fixtures.note('chord', 59, 2, 0), velocity=90))
            before = copy.deepcopy(song)
            changed = tab.measure_command(song, dict(action='measure_meter', at=0, meter=[3, 4], to_end=True))['song']
            self.assertEqual(performance(changed), performance(song), kind)
            moved, _ = tab.score_command(song, raw_for(song), dict(action='move_beats', occurrence='oa',
                track='guitar', at=[0, 1], direction='right', amount=[1, 1]))
            self.assertEqual(performance(moved), performance(song, shift=22050), kind)
            self.assertEqual(song, before)

    def test_partial_paste_retains_static_expression_and_restarts_tail(self):
        for effect in (dict(vibrato=True), dict(staccato=True), dict(palm_mute=True), dict(dead=True),
                       dict(harmonic=dict(type='artificial', data=0)), dict(tremolo_picking=dict(value=16))):
            song = expressive_song(effect)
            clip = tab.capture_score_clipboard(song, 'B', ['whole'], 'ob')
            # Replace the middle half of A, retaining an expressive quarter at either edge.
            clip['beats'][0]['written'] = dict(value=2, dots=0, tuplet=[1, 1])
            result = tab.paste_score_clipboard(song, Module(patterns=raw_for(song)), 0, 12,
                clip, 'oa', across=True, replace=True)
            beats = sorted(result['score']['patterns']['A']['beats'], key=lambda b: Fraction(*b['at']))
            self.assertEqual([Fraction(*b['at']) for b in beats], [0, 1, 3])
            for key, value in effect.items():
                self.assertEqual(beats[0]['notes'][0][key], value)
                self.assertEqual(beats[-1]['notes'][0][key], value)
            self.assertTrue(performance(result))

    def test_expressive_fit_and_shorter_keep_note_properties(self):
        fit = fixtures.TestPlaceFitCommand()
        for effect in EFFECTS + [dict(slide=True), dict(let_ring=True)]:
            with self.subTest(effect=effect):
                song, raw = fit.fixture()
                notes = song['score']['patterns']['A']['beats']
                notes[0]['notes'][0].update(effect, velocity=79)
                notes[1]['notes'][0].update(velocity=63, ghost=True)
                changed, result = tab.score_command(song, raw, fit.request(song))
                self.assertEqual(result['fit']['outcome'], 'shifted')
                for identity in ('a', 'b', 'c'):
                    self.assertEqual(tab._beat(changed['score'], 'A', identity)['notes'],
                                     tab._beat(song['score'], 'A', identity)['notes'])
                self.assertTrue(performance(changed, raw_patterns=raw))
                short = copy.deepcopy(tab._beat(changed['score'], 'A', 'a'))
                short['written'] = dict(value=8, dots=0, tuplet=[1, 1])
                shorter, _ = tab.score_command(changed, raw, dict(action='place', occurrence='oa', beat=short))
                self.assertEqual(tab._beat(shorter['score'], 'A', 'a')['notes'], short['notes'])

    def test_boundary_dependent_refusals_name_source_and_preserve_document(self):
        song = expressive_song(dict(let_ring=True))
        before = copy.deepcopy(song)
        with self.assertRaisesRegex(ValueError, 'part guitar, bar 1, beat whole: let-ring.*following beat intact'):
            tab.measure_command(song, dict(action='measure_meter', at=0, meter=[3, 4], to_end=True))
        self.assertEqual(song, before)

    def test_reflow_gate_guard_uses_actual_tempo_for_dead_ringing_note(self):
        song = expressive_song(dict(let_ring=True, dead=True))
        song['orders'] = ['A']
        song['score']['order_ids'] = ['oa']
        song['patterns'] = {'A': dict(rows=96, data='')}
        song['module']['speed'] = 1
        song['module']['tempo'] = 120
        song['score']['patterns'] = {'A': dict(row_step=[1, 24], beats=[
            fixtures.beat('head', [0, 1], [dict(fixtures.note('head', 64, 1, 0), velocity=90, let_ring=True, dead=True)], 64),
            fixtures.beat('target', [1, 16], [dict(fixtures.note('target', 66, 1, 2), velocity=90)], 32)])}
        song['score']['measures'] = song['score']['measures'][:1]
        edit = dict(action='measure_meter', at=0, meter=[1, 32], to_end=True)
        # At120 BPM dead-note caps both gates to60ticks. At255 BPM the original
        # gate is127ticks, but cutting its non-ring neighbor shortens it to120.
        candidate = tab.measure_command(song, edit)['song']
        song['module']['tempo'] = 255
        with self.assertRaisesRegex(ValueError, 'let-ring timing changes'):
            tab.measure_command(song, edit)
        song['module']['tempo'] = 120
        raw = raw_for(song)
        raw[0].rows[0][0] = Cell(effect=20, param=255)
        remap = {('oa', 'head'): [dict(occurrence='oa', note=candidate['score']['patterns']['A']['beats'][0]['notes'][0]['id'])]}
        with self.assertRaisesRegex(ValueError, 'let-ring timing changes'):
            tab._check_reflow_gates(song, candidate, remap, raw)
        song = expressive_song()
        beat = song['score']['patterns']['A']['beats'][0]
        beat['stroke'] = dict(direction='down', value=8)
        beat['notes'].append(dict(fixtures.note('chord', 59, 2, 0), velocity=90))
        before = copy.deepcopy(song)
        with self.assertRaisesRegex(ValueError, 'part guitar, beat whole: split strum.*quarter note'):
            tab.score_command(song, raw_for(song), dict(action='move_beats', occurrence='oa',
                track='guitar', at=[0, 1], direction='right', amount=[7, 2]))
        self.assertEqual(song, before)

    def test_rebar_and_independent_rebar_keep_prefix_raw_tempo(self):
        song = expressive_song()
        head = song['score']['patterns']['D']['beats'][0]
        head['stroke'] = dict(direction='down', value=4)
        head['notes'].append(dict(fixtures.note('chord', 59, 2, 0), velocity=90, dead=True))
        song['patterns']['A']['data'] = '00: ... .. ... TFF'
        raw = raw_for(song)
        raw[0].rows[0][0] = Cell(effect=20, param=255)
        before = copy.deepcopy(song)
        for independent in (False, True):
            changed = tab.measure_command(song, dict(action='measure_meter', at=3, meter=[3, 4],
                to_end=True, independent=independent), {'A': 0}, raw)['song']
            after_raw = raw_for(changed)
            after_raw[0].rows[0][0] = Cell(effect=20, param=255)
            self.assertEqual(performance(changed, raw_patterns=after_raw), performance(song, raw_patterns=raw))
            self.assertEqual(changed['patterns']['A'], song['patterns']['A'])
        self.assertEqual(song, before)

    def test_move_left_deleted_ring_head_is_not_rechecked_when_id_is_reused(self):
        song = expressive_song(dict(let_ring=True))
        changed, result = tab.score_command(song, raw_for(song), dict(action='move_beats', occurrence='oa',
            track='guitar', at=[0, 1], direction='left', amount=[4, 1]))
        self.assertEqual(result['removed'], ['whole'])
        self.assertFalse(any(n.get('let_ring') for p in changed['score']['patterns'].values()
                             for b in p['beats'] for n in b['notes']))
        attacks = [e for e in tab.playback_plan(changed, raw_for(changed))['events'] if e['type'] == 'note_on']
        self.assertEqual([e['frame'] for e in attacks], [0, 88200, 176400])

    def test_state_rebar_move_and_paste_exact_history_reopen(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'song.yaml'
            write_wav(path.parent / 'tone.wav', RATE, [sine(440)])
            song = expressive_song(dict(bend=dict(points=[dict(position=0, value=0), dict(position=12, value=2)])))
            song['samples'][1]['file'] = 'tone.wav'
            path.write_text('# Preserve owner formatting\n' + api.to_yaml(song), encoding='utf-8', newline='\n')
            state = gui.State(path, headless=True)
            try:
                self.assertFalse(state.error, state.error)
                original = path.read_bytes()
                clip = tab.capture_score_clipboard(song, 'A', ['whole'], 'oa')
                edits = [dict(action='measure_meter', at=0, meter=[3, 4], to_end=True),
                    dict(action='move_beats', occurrence='oa', track='guitar', at=[0, 1], direction='right', amount=[1, 1]),
                    dict(op='beats_paste', pattern=2, row=36, clipboard=clip, occurrence='oc', across=True, replace=True)]
                for edit in edits:
                    count = len(state.history)
                    (state.score_edit if 'op' in edit else state.score_command)(dict(edit, revision=state.text_sha()))
                    after = path.read_bytes()
                    self.assertNotEqual(after, original)
                    self.assertEqual(len(state.history), count + 1)
                    compiled = api.compile_song(path)
                    cells, rows, duration = it_cells(compiled[0])
                    saved = api.from_yaml(after.decode('utf-8'))
                    expected = [e['pitch'] for e in tab.playback_plan(saved, raw_for(saved))['events']
                                if e['type'] == 'note_on']
                    self.assertEqual([n for _, _, n, _, _, _ in cells if n is not None and n < 120], expected)
                    self.assertGreater(rows, 0)
                    self.assertGreater(duration, 0)
                    state.undo(); self.assertEqual(path.read_bytes(), original)
                    state.undo(redo=True); self.assertEqual(path.read_bytes(), after)
                    state.undo(); self.assertEqual(path.read_bytes(), original)
            finally:
                state.close()


if __name__ == '__main__':
    unittest.main()
