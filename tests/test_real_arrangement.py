"""Explicit native bar preparation and independent edits retain one guarded history transaction."""
import copy
import tempfile
import unittest
from pathlib import Path

from tests import test_tablature as fixtures
from tests.test_gui import RATE, sine
from vulturetracker import api, gui, tablature as tab
from vulturetracker.model import Cell, Module, Pattern
from vulturetracker.wavload import write_wav


def divided_song():
    song = fixtures.TestSectionStructure.source()
    song['module']['title'] = 'Real-world arrangement'
    song['patterns'] = {'A': dict(rows=96, data='')}
    song['orders'] = ['A', 'A']
    score = song['score']
    score['order_ids'] = ['first', 'second']
    score['patterns'] = {'A': dict(row_step=[1, 12], beats=[
        fixtures.beat('opening', [0, 1], [fixtures.note('opening_n', 64, 1, 0)]),
        fixtures.beat('crossing', [3, 1], [fixtures.note('crossing_n', 60, 2, 1)], 2),
        fixtures.beat('closing', [6, 1], [fixtures.note('closing_n', 67, 1, 3)], 2)])}
    score['ties'] = []
    score['measures'] = [dict(id=f'bar{i * 2 + j}', meter=[4, 4], marker=dict(title=f'Part {i + 1}', color='#334455'), **{
        'from': dict(occurrence=oid, at=[j * 4, 1]), 'to': dict(occurrence=oid, at=[j * 4 + 4, 1])})
        for i, oid in enumerate(score['order_ids']) for j in range(2)]
    return song


def raw_for(song):
    return [Pattern(str(n), [[Cell() for _ in range(7)] for _ in range(p['rows'])])
            for n, p in song['patterns'].items()]


def sound(song):
    return [(e['type'], e['frame'], e.get('pitch'), e.get('ch'))
            for e in tab.playback_plan(song, raw_for(song))['events'] if e['type'] in ('note_on', 'note_off')]


class TestRealArrangement(unittest.TestCase):
    def test_prepare_divided_reused_patterns_preserves_sound_raw_and_headers(self):
        song = divided_song()
        raw = raw_for(song)
        raw[0].rows[53][6] = Cell(note=40, instrument=1)
        before = copy.deepcopy((song, raw))
        plan = tab.prepare_score_measures(song, raw)
        result = plan['song']
        self.assertEqual(sound(result), sound(song))
        self.assertEqual(len(set(result['orders'])), 4)
        self.assertEqual(len(tab.measure_units(result)), 4)
        self.assertEqual(len(result['score']['ties']), 2)
        self.assertEqual([m['marker']['title'] for m in result['score']['measures']], ['Part 1'] * 2 + ['Part 2'] * 2)
        self.assertIn('05:', result['patterns'][result['orders'][1]]['data'])
        self.assertNotIn('A', result['patterns'])
        self.assertEqual((song, raw), before)
        segment = tab.measure_segment(song, 1, 2, independent=True, raw_patterns=raw)
        self.assertEqual(len(segment['units']), 2)
        self.assertEqual(song, before[0])

    def test_prepare_and_meter_is_one_candidate_without_retiming(self):
        song = divided_song()
        result = tab.measure_command(song, dict(action='measure_meter', at=0, meter=[3, 4],
            to_end=True, independent=True), raw_patterns=raw_for(song))['song']
        self.assertEqual(sound(result), sound(song))
        self.assertEqual(len(result['orders']), 6)
        self.assertTrue(all(u['measure']['meter'] == [3, 4] for u in tab.measure_units(result)))

    def test_prepare_refuses_flow_offgrid_and_unsafe_technique_atomically(self):
        for problem in ('flow', 'technique', 'approved', 'gap'):
            song, raw = divided_song(), raw_for(divided_song())
            if problem == 'flow': raw[0].rows[0][6] = Cell(effect=2, param=1)
            if problem == 'technique': song['score']['patterns']['A']['beats'][1]['notes'][0]['slide'] = True
            if problem == 'approved': song['patterns']['A']['approved'] = True
            if problem == 'gap': song['score']['measures'].pop()
            before = copy.deepcopy((song, raw))
            with self.subTest(problem=problem), self.assertRaises(ValueError):
                tab.prepare_score_measures(song, raw)
            self.assertEqual((song, raw), before)

    def test_independent_duration_and_paste_preserve_other_visit(self):
        song = divided_song()
        raw = raw_for(song)
        edited, result = tab.score_command(song, raw, dict(action='set_duration', occurrence='first',
            track='guitar', voice=0, beats=['opening'], written=dict(value=8, dots=0, tuplet=[1, 1]),
            independent=True))
        self.assertNotEqual(edited['orders'][0], edited['orders'][1])
        self.assertEqual(edited['score']['patterns']['A'], song['score']['patterns']['A'])
        clip = tab.capture_score_clipboard(song, 'A', ['opening'], 'first')
        pasted = tab.paste_score_clipboard(song, Module(patterns=raw), 0, 12, clip, 'first', independent=True)
        self.assertNotEqual(pasted['orders'][0], pasted['orders'][1])
        self.assertEqual(pasted['score']['patterns']['A'], song['score']['patterns']['A'])
        self.assertEqual(len(pasted['score']['patterns'][pasted['orders'][0]]['beats']), 4)

    def test_state_prepare_meter_duration_and_paste_exact_history(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'song.yaml'
            write_wav(path.parent / 'tone.wav', RATE, [sine(440)])
            source = divided_song()
            source['samples'][1]['file'] = 'tone.wav'
            path.write_text('# Keep this owner comment\n' + api.to_yaml(source), encoding='utf-8', newline='\n')
            state = gui.State(path, headless=True)
            try:
                self.assertFalse(state.error, state.error)
                original = state.text
                state.meta['loop'] = dict(**{'from': [0, 53], 'to': [1, 80]})
                for command in (dict(action='prepare_measures'),
                    dict(action='measure_meter', at=0, meter=[3, 4], to_end=True, independent=True),
                    dict(action='set_duration', occurrence='first', track='guitar', voice=0, beats=['opening'],
                         written=dict(value=8, dots=0, tuplet=[1, 1]), independent=True)):
                    state.score_command(dict(command, revision=state.text_sha()))
                    after = state.text
                    self.assertNotEqual(after, original)
                    if command['action'] == 'prepare_measures':
                        self.assertEqual(state.meta['loop'], dict(**{'from': [1, 5], 'to': [3, 32]}))
                    state.undo(); self.assertEqual(state.text, original)
                    state.undo(redo=True); self.assertEqual(state.text, after)
                    state.undo(); self.assertEqual(state.text, original)
                clip = tab.capture_score_clipboard(source, 'A', ['opening'], 'first')
                state.score_edit(dict(op='beats_paste', pattern=0, row=12, clipboard=clip,
                                      occurrence='first', independent=True, revision=state.text_sha()))
                after = state.text
                state.undo(); self.assertEqual(state.text, original)
                state.undo(redo=True); self.assertEqual(state.text, after)
                api.compile_song(path)
            finally:
                state.close()


if __name__ == '__main__':
    unittest.main()
