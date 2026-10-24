"""Phrase techniques use the same note semantics and one guarded transaction."""
import copy
import tempfile
import unittest
from pathlib import Path

from tests import test_tablature as fixtures
from tests.test_gui import RATE, sine
from tests.test_real_arrangement import divided_song, raw_for
from vulturetracker import api, gui, tablature as tab
from vulturetracker.model import Cell, Module
from vulturetracker.wavload import write_wav


def phrase():
    song, raw, selection = fixtures.TestCrossRangeCommands().fixture()
    raw[0].rows[0][6] = raw[0].rows[0][1]
    raw[0].rows[0][1] = Cell()  # Unrelated pan lives outside the authored attack lanes.
    for pattern in song['score']['patterns'].values():
        for beat in pattern['beats']:
            for note in beat['notes']:
                note['velocity'] = 95
    return song, raw, selection


def perform(song, raw):
    return [{k: v for k, v in e.items() if k not in ('id', 'occurrence', 'beat', 'note', 'pattern', 'order')}
            for e in tab.playback_plan(song, raw)['events']]


class TestBandExpression(unittest.TestCase):
    def test_range_techniques_preserve_ties_voices_and_local_semantics(self):
        song, raw, selection = phrase()
        original = copy.deepcopy((song, raw, selection))
        cases = [dict(let_ring=True), dict(fade_in=True), dict(vibrato=True), dict(hammer=True), dict(slide=True),
                 dict(tapping=True), dict(slapping=True), dict(popping=True),
                 dict(harmonic=dict(type='artificial', data=0)), dict(trill=dict(fret=7, value=16)),
                 dict(tremolo_picking=dict(value=16)),
                 dict(grace=dict(fret=2, value=16, velocity=47, on_beat=True)),
                 dict(bend=dict(points=[dict(position=0, value=0), dict(position=12, value=2)])),
                 dict(tremolo_bar=dict(points=[dict(position=0, value=0), dict(position=12, value=-1)]))]
        for changes in cases:
            with self.subTest(changes=changes):
                candidate, report = tab.score_command(song, raw, dict(action='set_expression',
                    track='guitar', selection=selection, changes=changes))
                local = song
                for name in ('A', 'B'):
                    for beat in song['score']['patterns'][name]['beats']:
                        if beat['voice'] != 0:continue
                        for note in beat['notes']:
                            local = tab.apply_score_edit(local, dict(op='note_set', pattern=name,
                                beat=beat['id'], note=dict(id=note['id'], **changes)))
                self.assertEqual(candidate, local)
                self.assertEqual(candidate['score']['ties'], song['score']['ties'])
                self.assertEqual(report['selection']['range'], selection)
                self.assertEqual(perform(candidate, raw), perform(local, raw))
                again, _ = tab.score_command(candidate, raw, dict(action='set_expression',
                    track='guitar', selection=selection, changes=changes))
                self.assertEqual(again, candidate)
        self.assertEqual((song, raw, selection), original)

    def test_range_strokes_share_cohort_and_clear_without_touching_later_bars(self):
        song, raw, selection = phrase()
        for changes in (dict(stroke=dict(direction='up', value=16)), dict(pick_stroke='down')):
            candidate, _ = tab.score_command(song, raw, dict(action='set_expression', track='guitar',
                selection=selection, changes=changes))
            for name in ('A', 'B'):
                for beat in candidate['score']['patterns'][name]['beats']:
                    for key, value in changes.items():
                        self.assertEqual(beat[key], value)
            self.assertEqual(candidate['score']['patterns']['C'], song['score']['patterns']['C'])
            cleared, _ = tab.score_command(candidate, raw, dict(action='set_expression', track='guitar',
                selection=selection, changes={key: None for key in changes}))
            self.assertEqual(cleared, song)

    def test_late_invalid_technique_and_partial_tie_are_atomic(self):
        song, raw, selection = phrase()
        for changes in (dict(grace=dict(fret=99, value=16, velocity=47)), dict(pick_stroke='sideways'),
                        dict(trill=dict(fret=1, value=3)), dict(bend=[]), dict(slapping=True, popping=True)):
            original = copy.deepcopy((song, raw))
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                tab.score_command(song, raw, dict(action='set_expression', track='guitar', selection=selection, changes=changes))
            self.assertEqual((song, raw), original)
        with self.assertRaisesRegex(ValueError, 'complete ties'):
            tab.score_command(song, raw, dict(action='set_expression', track='guitar',
                selection=selection[:1], changes=dict(vibrato=True)))

    def test_dynamic_crossing_notes_prepare_and_paste_keep_sound(self):
        for flag in ('ghost', 'accent', 'heavy_accent'):
            song = divided_song()
            for beat in song['score']['patterns']['A']['beats']:
                beat['notes'][0].update(velocity=63, **{flag: True})
            raw = raw_for(song)
            prepared = tab.prepare_score_measures(song, raw)['song']
            self.assertEqual(perform(song, raw), perform(prepared, raw_for(prepared)))
            # Paste a two-quarter marked note across a bar: generated ties retain its one attack.
            source, patterns, _ = phrase()
            source['score']['ties'] = []
            original = fixtures.beat('long', [0, 1], [dict(fixtures.note('longn', 64, 1, 0), velocity=63, **{flag: True})], value=2)
            source['score']['patterns']['A']['beats'] = [original]
            clip = tab.capture_score_clipboard(source, 'A', ['long'], 'oa')
            pasted = tab.paste_score_clipboard(source, Module(patterns=patterns), 2, 36, clip, 'oc', across=True, replace=True)
            attacks = [e for e in tab.playback_plan(pasted, patterns)['events'] if e['type'] == 'note_on' and e['id'].startswith('oc/copy_')]
            self.assertEqual(len(attacks), 1)
            self.assertTrue(any(t['from']['occurrence'] == 'oc' and t['to']['occurrence'] == 'od' for t in pasted['score']['ties']))

    def test_tied_expression_retune_keeps_grace_and_trill_pitches(self):
        song, raw, selection = phrase()
        for effect in (dict(grace=dict(fret=2, value=16, velocity=47, on_beat=True)),
                       dict(trill=dict(fret=7, value=16))):
            source, _ = tab.score_command(song, raw, dict(action='set_expression', track='guitar',
                selection=selection, changes=effect))
            tuned, _ = tab.score_command(source, raw, dict(action='retune', track='guitar',
                tuning=[63, 58, 54, 49, 44, 39], keep='pitch'))
            self.assertEqual(perform(tuned, raw), perform(source, raw))
            self.assertEqual(tuned['score']['ties'], source['score']['ties'])
            for name in ('A', 'B'):
                for before, after in zip(source['score']['patterns'][name]['beats'], tuned['score']['patterns'][name]['beats']):
                    for old, new in zip(before['notes'], after['notes']):
                        key = next(iter(effect))
                        if key in old:self.assertEqual(new[key]['fret'], old[key]['fret'] + 1)
                        else:self.assertNotIn(key,new)

    def test_state_phrase_curve_and_repetition_exact_history(self):
        song, _, selection = phrase()
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'song.yaml'
            write_wav(path.parent / 'tone.wav', RATE, [sine(440)])
            for sample in song['samples'].values():
                sample['file'] = 'tone.wav'
            path.write_text('# Owner formatting survives Undo\n' + api.to_yaml(song), encoding='utf-8', newline='\n')
            state = gui.State(path, headless=True)
            try:
                self.assertFalse(state.error, state.error)
                original = path.read_bytes()
                for changes in (dict(vibrato=True), dict(tapping=True), dict(pick_stroke='up'),
                                dict(tremolo_picking=dict(value=16))):
                    before_count = len(state.history)
                    state.score_command(dict(action='set_expression', track='guitar', selection=selection,
                        changes=changes, revision=state.text_sha()))
                    after = path.read_bytes()
                    self.assertNotEqual(after, original)
                    self.assertEqual(len(state.history), before_count + 1)
                    api.compile_song(path)
                    state.undo(); self.assertEqual(path.read_bytes(), original)
                    state.undo(redo=True); self.assertEqual(path.read_bytes(), after)
                    state.undo(); self.assertEqual(path.read_bytes(), original)
            finally:
                state.close()


if __name__ == '__main__':
    unittest.main()
