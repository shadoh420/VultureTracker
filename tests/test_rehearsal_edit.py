"""Focused exact rhythm/routing checks for flexible phrase and voice editing."""
import copy
import tempfile
import unittest
from pathlib import Path

from tests.test_tablature import fixture, beat, note
from tests.test_gui import RATE, sine
from vulturetracker import api, gui, tablature as tab
from vulturetracker.model import Cell, Module, Pattern
from vulturetracker.wavload import write_wav


def phrase_fixture():
    song, raw = fixture()
    raw[0].rows[0][1] = Cell()
    song['score']['ties'] = []
    song['score']['patterns']['A']['beats'] = [beat('source', [0, 1], [note('source_n', 64, 1, 0)])]
    song['score']['patterns']['B']['beats'] = [beat('long', [0, 1], [note('long_n', 60, 2, 1)], 1),
        beat('peer', [0, 1], [note('peer_n', 40, 6, 0)], 1, voice=1)]
    return song, raw


def raw_for(song, original):
    known = {p.name for p in original}
    return original + [Pattern(name, [[Cell() for _ in range(7)] for _ in range(spec['rows'])])
                       for name, spec in song['patterns'].items() if name not in known]


class TestRehearsalPhraseModel(unittest.TestCase):
    def test_mix_subdivides_and_ties_long_notes_without_changing_their_sound(self):
        song, raw = phrase_fixture()
        clip = tab.capture_score_clipboard(song, 'A', ['source'])
        before = copy.deepcopy((song, raw, clip))
        result = tab.paste_score_clipboard(song, Module(patterns=raw), 1, 12, clip, 'ob', across=True, mode='mix')
        active = [b for b in result['score']['patterns']['B']['beats'] if b['voice'] == 0]
        self.assertEqual([b['at'] for b in active], [[0, 1], [1, 1], [2, 1]])
        self.assertEqual([len(b['notes']) for b in active], [1, 2, 1])
        self.assertEqual(len(result['score']['ties']), 2)
        gates = lambda s: [(e['type'], e['at'], e['pitch']) for e in tab.playback_plan(s, raw)['events']
                           if e['pitch'] in (60, 40)]
        self.assertEqual(gates(result), gates(song))
        tab.project_score(result, raw)
        self.assertEqual((song, raw, clip), before)

    def test_mix_rest_never_erases_notes_and_metadata_collision_is_atomic(self):
        song, raw = phrase_fixture()
        song['score']['patterns']['A']['beats'][0]['notes'] = []
        clip = tab.capture_score_clipboard(song, 'A', ['source'])
        result = tab.paste_score_clipboard(song, Module(patterns=raw), 1, 0, clip, 'ob', across=True, mode='mix')
        self.assertEqual(sum(e['type'] == 'note_on' for e in tab.playback_plan(result, raw)['events']), 2)
        song['score']['patterns']['B']['beats'][0]['text'] = 'Retain'
        clip['beats'][0]['text'] = 'Other'
        before = copy.deepcopy((song, raw, clip))
        with self.assertRaisesRegex(ValueError, 'conflicting text'):
            tab.paste_score_clipboard(song, Module(patterns=raw), 1, 0, clip, 'ob', across=True, mode='mix')
        self.assertEqual((song, raw, clip), before)

    def test_push_splits_crossing_head_extends_song_and_preserves_peer_voice(self):
        song, raw = phrase_fixture()
        clip = tab.capture_score_clipboard(song, 'A', ['source'])
        before = copy.deepcopy((song, raw, clip))
        result = tab.paste_score_clipboard(song, Module(patterns=raw), 1, 12, clip, 'ob', across=True, mode='push')
        self.assertEqual(len(result['orders']), 3)
        raw_result = raw_for(result, raw)
        events = tab.playback_plan(result, raw_result)['events']
        self.assertEqual([(e['type'], e['at']) for e in events if e['pitch'] == 60],
                         [('note_on', [4, 1]), ('note_off', [5, 1]), ('note_on', [6, 1]), ('note_off', [9, 1])])
        self.assertEqual([(e['type'], e['at']) for e in events if e['pitch'] == 40],
                         [('note_on', [4, 1]), ('note_off', [8, 1])])
        self.assertEqual(len(result['score']['ties']), 1)
        tab.project_score(result, raw_result)
        self.assertEqual((song, raw, clip), before)

    def test_push_existing_tied_chain_keeps_sounding_length_and_raw_cells(self):
        song, raw = phrase_fixture()
        song['score']['patterns']['B']['beats'] = [beat('one', [0, 1], [note('one_n', 60, 2, 1)], 2),
            beat('two', [2, 1], [note('two_n', 60, 2, 1)], 2)]
        song['score']['ties'] = [dict(**{'from':dict(occurrence='ob', note='one_n'),
                                       'to':dict(occurrence='ob', note='two_n')})]
        clip = tab.capture_score_clipboard(song, 'A', ['source'])
        result = tab.paste_score_clipboard(song, Module(patterns=raw), 1, 0, clip, 'ob', across=True, mode='push')
        events = tab.playback_plan(result, raw_for(result, raw))['events']
        self.assertEqual([(e['type'], e['at']) for e in events if e['pitch'] == 60],
                         [('note_on', [5, 1]), ('note_off', [9, 1])])
        self.assertEqual(result['patterns']['B'], song['patterns']['B'])

    def test_collision_shared_pattern_and_technique_split_refuse_atomically(self):
        for kind in ('string', 'shared', 'technique'):
            song, raw = phrase_fixture()
            if kind == 'string':
                song['score']['patterns']['A']['beats'][0]['notes'] = [note('source_n', 61, 2, 2)]
            elif kind == 'shared':
                song['orders'].append('B'); song['score']['order_ids'].append('ob2')
            else:
                song['score']['patterns']['B']['beats'][0]['notes'][0]['slide'] = True
            clip = tab.capture_score_clipboard(song, 'A', ['source'])
            before = copy.deepcopy((song, raw, clip))
            with self.subTest(kind=kind), self.assertRaises(ValueError):
                tab.paste_score_clipboard(song, Module(patterns=raw), 1, 12, clip, 'ob', across=True, mode='mix')
            self.assertEqual((song, raw, clip), before)

    def test_voice_map_keeps_voice_identity_and_rejects_collapsing_two_voices(self):
        song, raw = phrase_fixture()
        clip = tab.capture_score_clipboard(song, 'A', ['source'])
        result = tab.paste_score_clipboard(song, Module(patterns=raw), 0, 12, clip, 'oa', voice_map={'0': 1})
        self.assertEqual(result['score']['patterns']['A']['beats'][-1]['voice'], 1)
        clip = tab.capture_score_clipboard(song, 'B', ['long', 'peer'])
        with self.assertRaisesRegex(ValueError, 'collapse'):
            tab.paste_score_clipboard(song, Module(patterns=raw), 0, 12, clip, 'oa', voice_map={'0': 1})


class TestRehearsalVoiceModel(unittest.TestCase):
    @staticmethod
    def song():
        song, raw = phrase_fixture()
        for name in ('A', 'B'):
            song['score']['patterns'][name]['beats'] = [beat('head', [0, 1], [note('head_n', 60, 2, 1)], 1),
                beat('rest', [0, 1], [], 1, voice=1)]
        song['score']['ties'] = [{'from': dict(occurrence='oa', note='head_n'), 'to': dict(occurrence='ob', note='head_n')}]
        return song, raw

    def edit(self, **extra):
        return dict(action='transfer_voice', track='guitar', from_voice=0, to_voice=1,
                    selection=[dict(occurrence=o, beats=['head', 'rest']) for o in ('oa', 'ob')], **extra)

    def test_move_whole_tied_voice_replaces_only_destination_rests(self):
        song, raw = self.song()
        before = copy.deepcopy(song)
        result, report = tab.transfer_score_voice(song, raw, self.edit())
        self.assertEqual(report['selection']['voice'], 1)
        self.assertEqual(len(report['selection']['range']), 2)
        self.assertTrue(all(b['voice'] == 1 for p in result['score']['patterns'].values() for b in p['beats']))
        self.assertEqual(len(result['score']['ties']), 1)
        events = lambda s: [(e['type'], e['at'], e['pitch']) for e in tab.playback_plan(s, raw)['events']]
        self.assertEqual(events(song), events(result))
        tab.project_score(result, raw)
        self.assertEqual(song, before)

    def test_copy_voice_allocates_free_string_and_keeps_both_ties(self):
        song, raw = self.song()
        result, report = tab.transfer_score_voice(song, raw, self.edit(copy=True))
        self.assertEqual(len(result['score']['ties']), 2)
        notes = [b['notes'][0] for b in result['score']['patterns']['A']['beats']]
        self.assertEqual({n['string'] for n in notes}, {2, 3})
        events = tab.playback_plan(result, raw)['events']
        self.assertEqual(sum(e['type'] == 'note_on' for e in events), 2)
        tab.project_score(result, raw)

    def test_destination_notes_need_explicit_replace_and_partial_tie_detaches(self):
        song, raw = self.song()
        song['score']['patterns']['A']['beats'][1]['notes'] = [note('other', 40, 6, 0)]
        before = copy.deepcopy(song)
        with self.assertRaisesRegex(ValueError, 'destination voice contains notes'):
            tab.transfer_score_voice(song, raw, self.edit())
        self.assertEqual(song, before)
        edit = self.edit(mode='replace'); edit['selection'] = [edit['selection'][0]]
        result, report = tab.transfer_score_voice(song, raw, edit)
        self.assertFalse(result['score']['ties'])
        self.assertEqual(len(report['removed_ties']), 1)
        self.assertEqual(result['score']['patterns']['B'], song['score']['patterns']['B'])


class TestRehearsalEditState(unittest.TestCase):
    def open(self, song):
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        path = Path(tmp.name) / 'song.yaml'
        write_wav(path.parent / 'original.wav', RATE, [sine(440)])
        path.write_text('# Rehearsal editing\n' + api.to_yaml(song), encoding='utf-8', newline='\n')
        state = gui.State(path, headless=True); self.addCleanup(state.close)
        self.assertFalse(state.error, state.error)
        return state

    def test_mix_push_and_voice_transfer_are_single_exact_history_transactions(self):
        for mode in ('mix', 'push'):
            song, _ = phrase_fixture(); state = self.open(song)
            before = state.song_path.read_bytes()
            clip = state.score_clipboard(dict(pattern='A', beats=['source'], occurrence='oa', revision=state.text_sha()))['clipboard']
            state.score_edit(dict(op='beats_paste', pattern=1, row=12, occurrence='ob', clipboard=clip,
                                  across=True, mode=mode, revision=state.text_sha()))
            after = state.song_path.read_bytes()
            self.assertNotEqual(before, after)
            api.compile_song(state.song_path)
            state.undo(); self.assertEqual(state.song_path.read_bytes(), before)
            state.undo(redo=True); self.assertEqual(state.song_path.read_bytes(), after)
        song, _ = TestRehearsalVoiceModel.song(); state = self.open(song)
        before = state.song_path.read_bytes()
        result = state.score_command(dict(TestRehearsalVoiceModel().edit(), revision=state.text_sha()))
        self.assertEqual(result['selection']['voice'], 1)
        state.undo(); self.assertEqual(state.song_path.read_bytes(), before)

    def test_late_raw_collision_and_unrepresentable_paste_are_atomic(self):
        song, _ = phrase_fixture()
        song['patterns']['A']['data'] = ''.join(f'{r:02d}: ' +
            ('D-5 01 ... ...' if r == 18 else '... .. ... ...') + '\n' for r in range(48))
        state = self.open(song)
        clip = state.score_clipboard(dict(pattern='A', beats=['source'], occurrence='oa', revision=state.text_sha()))['clipboard']
        before = state.song_path.read_bytes()
        history, future = list(state.history), list(state.future)
        for mode, pattern, occurrence, row, payload in (('push', 0, 'oa', 0, clip), ('mix', 1, 'ob', [49, 4], clip)):
            with self.subTest(mode=mode), self.assertRaises((ValueError, api.SongError)):
                state.score_edit(dict(op='beats_paste', pattern=pattern, row=row, occurrence=occurrence, clipboard=payload,
                                      across=True, mode=mode, revision=state.text_sha()))
            self.assertEqual(state.song_path.read_bytes(), before)
            self.assertEqual((state.history, state.future), (history, future))


if __name__ == '__main__':
    unittest.main()
