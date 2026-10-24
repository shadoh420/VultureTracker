"""The native score, tracker edits and existing persistent history share one song."""
import copy
import math
import os
import tempfile
import unittest
from fractions import Fraction
from pathlib import Path
from unittest.mock import patch
from types import SimpleNamespace

from vulturetracker import agent, api, gui
from vulturetracker.model import NOTE_OFF
from vulturetracker.notation import format_cell, parse_cell
from vulturetracker.song import SongError
from vulturetracker.wavload import write_wav
from tests.test_gui import RATE, sine


def score_song():
    def beat(identity, at, value, notes, tuplet=(1, 1)):
        return dict(id=identity, track='guitar', voice=0, at=at,
                    written=dict(value=value, dots=0, tuplet=list(tuplet)), notes=notes)

    def note(identity, string, fret):
        return dict(id=identity, string=string, fret=fret, pitch=[64, 59, 55, 50, 45, 40][string - 1] + fret)

    return {
        'module': {'title': 'Native TAB integration', 'tempo': 120, 'speed': 2,
                   'channels': [{'name': f'String {i + 1}'} for i in range(6)]},
        'samples': {1: {'file': 'tone.wav', 'name': 'Tone'}},
        'patterns': {'a': {'rows': 48, 'data': '00: ... .. ... X40\n'},
                     'b': {'rows': 48, 'data': ''}},
        'orders': ['a', 'b'],
        'score': {'version': 1, 'tracks': {'guitar': {'tuning': [64, 59, 55, 50, 45, 40],
                  'capo': 0, 'instrument': 1, 'channels': list(range(6))}},
                  'order_ids': ['first', 'second'],
                  'patterns': {
                      'a': {'row_step': [1, 12], 'beats': [
                          beat('chord', [0, 1], 4, [note('e', 1, 0), note('c', 2, 1)]),
                          *[beat(f'triplet{i}', [3 + i, 3], 8, [note(f't{i}', 2, i + 1)], (3, 2))
                            for i in range(3)],
                          beat('tail', [7, 2], 8, [note('tie_a', 1, 0)])]},
                      'b': {'row_step': [1, 12], 'beats': [beat('head', [0, 1], 8, [note('tie_b', 1, 0)])]}},
                  'measures': [],
                  'ties': [{'from': {'occurrence': 'first', 'note': 'tie_a'},
                            'to': {'occurrence': 'second', 'note': 'tie_b'}}]}}


def let_ring_song():
    """One ringing string held through a second string, then an explicit rest."""
    from tests.test_tablature import beat, note
    song = score_song()
    song['module']['tempo'] = 137
    song['patterns']['a']['data'] = ''.join(
        f"{row:02d}: ... .. ... {'T53' if row == 12 else '...'}\n" for row in range(48))
    song['samples'][1]['loop'] = {'start': 0, 'end': 1024}
    song['instruments'] = {1: {'sample': 1}}
    song['score']['ties'] = []
    song['score']['patterns']['a']['beats'] = [
        beat('ring', [0, 1], [dict(note('ring', 64, 1, 0), let_ring=True)]),
        beat('next', [1, 1], [note('next', 59, 2, 0)]),
        beat('rest', [2, 1], [])]
    song['score']['patterns']['b']['beats'] = []
    return song


def swing_song(mode='eighth'):
    """A written straight pair around a tempo change, with measure-local swing."""
    song = let_ring_song()
    first, second, _ = song['score']['patterns']['a']['beats']
    value = 8 if mode in ('eighth', 'none') else 16
    first['notes'][0].pop('let_ring')
    first['written']['value'] = second['written']['value'] = value
    second['at'] = [1, value // 4]
    song['score']['measures'] = [dict(id='bar', meter=[4, 4], swing=mode,
        **{'from': dict(occurrence='first', at=[0, 1]), 'to': dict(occurrence='first', at=[4, 1])})]
    song['patterns']['a']['data'] = song['patterns']['a']['data'].replace(
        '12: ... .. ... T53', '12: ... .. ... ...').replace('06: ... .. ... ...', '06: ... .. ... T53')
    return song


def repeat_song():
    """Three authored bars, A/B repeated then C, restoring A's entry tempo."""
    from tests.test_tablature import beat, note
    song = let_ring_song()
    song['patterns']['c'] = {'rows': 48, 'data': ''}
    song['orders'] = ['a', 'b', 'c']
    song['score']['order_ids'] = ['first', 'second', 'third']
    song['score']['patterns'] = {name: {'row_step': [1, 12], 'beats': [
        beat('head', [0, 1], [dict(note('head', pitch, 1, pitch - 64), velocity=90)])]}
        for name, pitch in zip(song['orders'], (64, 66, 67))}
    song['score']['measures'] = [dict(id=name, meter=[4, 4],
        **{'from': dict(occurrence=oid, at=[0, 1]), 'to': dict(occurrence=oid, at=[4, 1])}, **flow)
        for name, oid, flow in zip(song['orders'], song['score']['order_ids'],
                                   ({'repeat_open': True}, {'repeat_close': 1}, {}))]
    song['sections'] = {'first': [0, 1], 'outro': [2, 3]}
    return song


def repeat_fragment_song():
    """Two repeated half-pattern measures share one authored pattern."""
    from tests.test_tablature import beat, note
    song = let_ring_song()
    song['orders'] = ['a']
    song['patterns'].pop('b')
    song['score']['order_ids'] = ['first']
    song['score']['patterns'] = {'a': {'row_step': [1, 12], 'beats': [
        beat('head', [0, 1], [note('head', 64, 1, 0)]),
        beat('later', [2, 1], [note('later', 66, 1, 2)])]}}
    song['score']['measures'] = [dict(id=f'half{i}', meter=[2, 4],
        **{'from': dict(occurrence='first', at=[i * 2, 1]),
           'to': dict(occurrence='first', at=[(i + 1) * 2, 1])},
        **({'repeat_open': True} if i == 0 else {'repeat_close': 1})) for i in range(2)]
    return song


def stroke_song():
    """A three-string chord and a short second-voice rest share stroke metadata."""
    from tests.test_tablature import beat, note
    song = let_ring_song()
    song['score']['patterns']['a']['beats'] = [
        dict(beat('chord', [0, 1], [dict(note(f's{s}', pitch, s, 0), velocity=95)
                                  for s, pitch in ((1, 64), (3, 55), (6, 40))]),
             stroke={'direction': 'down', 'value': 4}, pick_stroke='up'),
        dict(beat('rest', [0, 1], [], value=16), voice=1)]
    return song


def written_voice_song():
    """Independent written voices use one string and parent with unequal gates."""
    from tests.test_tablature import beat, note
    song = let_ring_song()
    song['score']['patterns']['a']['beats'] = [
        beat('long', [0, 1], [dict(note('long', 65, 1, 1), velocity=95)]),
        dict(beat('short', [0, 1], [dict(note('short', 66, 1, 2), velocity=77)], value=16), voice=1)]
    return song


class TestChordLibrary(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'custom-chords.json'
        self.shape = dict(name='C', first_fret=0, frets=[0, 1, 0, 2, 3, -1])

    def test_store_lifecycle_clone_isolation_names_and_stale_revision(self):
        from vulturetracker.chord_library import read_library, edit_library
        empty = read_library(self.path)
        self.assertFalse(self.path.exists())
        self.assertEqual(empty, dict(version=1, revision=0, chords=[]))
        first = edit_library(dict(op='add', revision=0, chord=self.shape), self.path)
        self.shape['frets'][0] = 3
        first['chords'][0]['name'] = 'Changed returned copy'
        self.assertEqual(read_library(self.path)['chords'][0]['name'], 'C')
        self.assertEqual(read_library(self.path)['chords'][0]['frets'][0], 0)
        before = self.path.read_bytes()
        with self.assertRaisesRegex(ValueError, 'changed'):
            edit_library(dict(op='remove', revision=0, name='C'), self.path)
        with self.assertRaisesRegex(ValueError, 'already'):
            edit_library(dict(op='add', revision=1, chord=dict(self.shape, name='C')), self.path)
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(edit_library(dict(op='rename', revision=1, name='C', new_name='C'), self.path)['revision'], 1)
        self.assertEqual(self.path.read_bytes(), before)
        renamed = edit_library(dict(op='rename', revision=1, name='C', new_name='C shape'), self.path)
        self.assertEqual(renamed['revision'], 2)
        self.assertEqual(read_library(self.path)['chords'][0]['name'], 'C shape')
        removed = edit_library(dict(op='remove', revision=2, name='C shape'), self.path)
        self.assertEqual(removed, dict(version=1, revision=3, chords=[]))

    def test_malformed_store_invalid_shapes_and_atomic_failure_preserve_data(self):
        from vulturetracker.chord_library import read_library, edit_library
        for bad in (b'{', b'{"version":1,"version":1,"revision":0,"chords":[]}',
                    b'{"version":1,"revision":0,"chords":[null]}'):
            self.path.write_bytes(bad)
            with self.assertRaisesRegex(ValueError, 'not changed'):
                edit_library(dict(op='add', revision=0, chord=self.shape), self.path)
            self.assertEqual(self.path.read_bytes(), bad)
        self.path.unlink()  # This test's own malformed temporary fixture.
        edit_library(dict(op='add', revision=0, chord=self.shape), self.path)
        before = self.path.read_bytes()
        for chord in (dict(self.shape, name=' '), dict(self.shape, name='Bad', frets=[]),
                      dict(self.shape, name='Bad', frets=[True] * 6),
                      dict(self.shape, name='Bad', frets=[1, 12, -1, -1, -1, -1])):
            with self.assertRaises(ValueError):
                edit_library(dict(op='add', revision=1, chord=chord), self.path)
            self.assertEqual(self.path.read_bytes(), before)
        with patch('vulturetracker.chord_library.atomic_write', side_effect=OSError('write failed')):
            with self.assertRaisesRegex(OSError, 'write failed'):
                edit_library(dict(op='rename', revision=1, name='C', new_name='Renamed'), self.path)
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(read_library(self.path)['revision'], 1)
        self.assertEqual(edit_library(dict(op='rename', revision=1, name='C', new_name='Renamed'), self.path)['revision'], 2)

    def test_existing_os_lock_refuses_parallel_writer_and_releases_after_failure(self):
        from vulturetracker.chord_library import edit_library
        from vulturetracker.fileio import lock_file, unlock_file
        held = lock_file(self.path.with_suffix('.lock'))
        self.assertIsNotNone(held)
        try:
            with self.assertRaisesRegex(ValueError, 'another app'):
                edit_library(dict(op='add', revision=0, chord=self.shape), self.path)
            self.assertFalse(self.path.exists())
        finally:
            unlock_file(held)
        self.assertEqual(edit_library(dict(op='add', revision=0, chord=self.shape), self.path)['revision'], 1)


class TestTablatureSync(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        write_wav(self.base / 'tone.wav', RATE, [sine(220)])
        self.path = self.base / 'song.yaml'
        self.path.write_bytes(('# Keep this source comment.\n' + api.to_yaml(score_song())).encode())
        self.st = gui.State(self.path, headless=True)
        self.addCleanup(lambda: self.st.close())

    def edit(self, **edit):
        self.st.score_edit(dict(edit, revision=self.st.text_sha()))

    def cell(self, pattern, row, ch):
        occurrence = next(o['occurrence'] for o in self.st.facts['orders'] if o['index'] == pattern)
        return parse_cell(self.st.pattern_rows(pattern, occurrence)['display_rows'][row][ch])

    def test_lyrics_state_preserves_raw_text_reopen_history_and_atomic_refusals(self):
        before = self.path.read_bytes()
        track = copy.deepcopy(self.st.song['score']['tracks']['guitar'])
        track['lyrics'] = {'from_measure': 2, 'text': '  one\r\ntwo\rthree\n\tfour\u00a0five  '}
        revision, history = self.st.text_sha(), len(self.st.history)
        self.edit(op='track_set', track='guitar', value=track)
        changed = self.path.read_bytes()
        self.assertTrue(changed.startswith(b'# Keep this source comment.\n'))
        self.assertEqual(len(self.st.history), history + 1)
        self.assertEqual(self.st.score_view()['score']['tracks']['guitar'], track)
        filtered = agent.run(self.st, 'read_score', {'pattern': 'b'})
        self.assertEqual(filtered['lyrics']['anchors'], [])
        self.assertEqual(filtered['lyrics']['errors'][0]['code'], 'lyrics_measure_map')
        self.edit(op='track_set', track='guitar', value=track)
        self.assertEqual((self.path.read_bytes(), len(self.st.history)), (changed, history + 1))
        for payload in (
                dict(op='track_set', track='guitar', value=track, revision=revision),
                dict(op='track_set', track='guitar', value=dict(track, lyrics=None), revision=self.st.text_sha())):
            with self.assertRaises(ValueError):
                self.st.score_edit(payload)
            self.assertEqual((self.path.read_bytes(), len(self.st.history)), (changed, history + 1))
        self.st.close()
        self.st = gui.State(self.path, headless=True)
        self.assertEqual(self.st.song['score']['tracks']['guitar'], track)
        self.st.undo()
        self.assertEqual(self.path.read_bytes(), before)
        self.st.undo(redo=True)
        self.assertEqual(self.path.read_bytes(), changed)
        clear = copy.deepcopy(track)
        del clear['lyrics']
        self.edit(op='track_set', track='guitar', value=clear)
        self.assertNotIn('lyrics', self.st.song['score']['tracks']['guitar'])
        self.st.undo()
        self.assertEqual(self.path.read_bytes(), changed)

    def test_lyrics_agent_history_filtering_and_approved_channel_guard(self):
        for number, occurrence in enumerate(('first', 'second'), 1):
            self.edit(op='measure_set', measure=dict(id=f'bar{number}', meter=[4, 4],
                **{'from': dict(occurrence=occurrence, at=[0, 1]),
                   'to': dict(occurrence=occurrence, at=[4, 1])}))
        before = self.path.read_bytes()
        track = copy.deepcopy(self.st.song['score']['tracks']['guitar'])
        track['lyrics'] = {'from_measure': 1, 'text': 'one  two\r\nthree\tfour five six seven  '}
        result = agent.run(self.st, 'edit_score', dict(revision=self.st.text_sha(),
            edit=dict(op='track_set', track='guitar', value=track)))
        self.assertTrue(result.get('ok'), result)
        changed = self.path.read_bytes()
        full = agent.run(self.st, 'read_score', {})
        self.assertEqual(full['score']['tracks']['guitar']['lyrics'], track['lyrics'])
        self.assertEqual({p['pattern'] for p in full['lyrics']['anchors']}, {'a', 'b'})
        for pattern in ('a', 'b'):
            view = agent.run(self.st, 'read_score', {'pattern': pattern})
            self.assertEqual(view['lyrics']['anchors'],
                             [p for p in full['lyrics']['anchors'] if p['pattern'] == pattern])
            self.assertEqual(view['lyrics']['errors'], full['lyrics']['errors'])
            self.assertEqual(view['score']['tracks']['guitar']['lyrics'], track['lyrics'])
        self.st.undo()
        self.assertEqual(self.path.read_bytes(), before)
        self.st.undo(redo=True)
        self.assertEqual(self.path.read_bytes(), changed)
        self.st.close()
        self.st = gui.State(self.path, headless=True)
        self.assertEqual(self.st.song['score']['tracks']['guitar']['lyrics'], track['lyrics'])
        protected = copy.deepcopy(self.st.song)
        protected['module']['channels'][1]['approved'] = True
        self.st.close()
        self.path.write_bytes(api.to_yaml(protected).encode())
        self.st = gui.State(self.path, headless=True)
        before = self.path.read_bytes(), len(self.st.history)
        track['lyrics']['text'] = 'changed'
        result = agent.run(self.st, 'edit_score', dict(revision=self.st.text_sha(),
            edit=dict(op='track_set', track='guitar', value=track)))
        self.assertIn('approved', result.get('error', ''))
        self.assertEqual((self.path.read_bytes(), len(self.st.history)), before)

    def test_lyrics_export_preserves_audio_inputs_and_reports_midi_loss(self):
        from vulturetracker import export
        source = score_song()
        source['patterns']['a']['data'] = ''
        baseline = export.snapshot(source, self.base, tail=0)
        midi, report = export.native_to_midi(baseline)
        for lyrics in ({'from_measure': 1, 'text': '  exact\r\nlyrics\ttext  '},
                       {'from_measure': 123, 'text': ''}):
            with self.subTest(lyrics=lyrics):
                source['score']['tracks']['guitar']['lyrics'] = lyrics
                marked = export.snapshot(source, self.base, tail=0)
                for key in ('plan', 'render_it', 'seek', 'end', 'tail', 'range_at', 'seconds', 'frames'):
                    self.assertEqual(marked[key], baseline[key], key)
                actual_midi, actual_report = export.native_to_midi(marked)
                self.assertEqual(actual_midi, midi)
                self.assertEqual(marked['midi_metadata']['lyrics_tracks'], ['guitar'])
                losses = actual_report.pop('losses')
                self.assertEqual(actual_report, {k: v for k, v in report.items() if k != 'losses'})
                self.assertEqual([s for s in losses if s not in report['losses']],
                    ['Track lyrics and their starting measures are omitted from MIDI: guitar.'])

    def test_tap_slap_pop_share_history_clipboard_and_leave_native_midi_unchanged(self):
        from vulturetracker import export
        source = score_song()
        source['patterns']['a']['data'] = ''
        path = self.base / 'tap-slap-pop.yaml'
        path.write_bytes(api.to_yaml(source).encode())
        st = gui.State(path, headless=True)
        self.addCleanup(st.close)
        baseline = export.snapshot(st.song, self.base, tail=0)
        midi, report = export.native_to_midi(baseline)
        before = path.read_bytes()
        for flag in ('tapping', 'slapping', 'popping'):
            with self.subTest(flag=flag):
                result = agent.run(st, 'edit_score', dict(revision=st.text_sha(), edit=dict(
                    op='note_set', pattern='a', beat='chord', note={'id': 'e', flag: True})))
                self.assertTrue(result.get('ok'), result)
                note = st.song['score']['patterns']['a']['beats'][0]['notes'][0]
                self.assertEqual([k for k in ('tapping', 'slapping', 'popping') if note.get(k)], [flag])
                marked = export.snapshot(st.song, self.base, tail=0)
                self.assertEqual(marked['plan']['events'], baseline['plan']['events'])
                self.assertEqual(marked['render_it'], baseline['render_it'])
                self.assertEqual(export.native_to_midi(marked), (midi, report))
                position = next(p for p in marked['plan']['positions'] if p['id'] == 'first/e')
                self.assertTrue(position[flag])
                clip = st.score_clipboard(dict(revision=st.text_sha(), pattern='a', beats=['chord'],
                                               occurrence='first'))['clipboard']
                self.assertTrue(clip['beats'][0]['notes'][0][flag])
                rows = st.pattern_rows(0, 'first')['display_rows']
                self.assertEqual(parse_cell(rows[0][0]).note, 64)
        changed = path.read_bytes()
        for _ in range(3):
            st.undo()
        self.assertEqual(path.read_bytes(), before)
        for _ in range(3):
            st.undo(redo=True)
        self.assertEqual(path.read_bytes(), changed)
        reopened = gui.State(path, headless=True)
        self.addCleanup(reopened.close)
        self.assertEqual(reopened.song['score'], st.song['score'])

    def test_tap_slap_pop_validate_conflicts_ties_and_strict_it_without_mutation(self):
        from vulturetracker.tablature import apply_score_edit, project_score, playback_plan
        source = score_song()
        source['patterns']['a']['data'] = ''
        for fields in ({'tapping': 1}, {'slapping': None}, {'popping': 'yes'},
                       {'tapping': True, 'slapping': True}):
            with self.subTest(fields=fields):
                before = copy.deepcopy(source)
                with self.assertRaises(ValueError):
                    apply_score_edit(source, dict(op='note_set', pattern='a', beat='chord', note=dict(id='e', **fields)))
                self.assertEqual(source, before)
        changed = apply_score_edit(source, dict(op='note_set', pattern='b', beat='head', note=dict(id='tie_b', tapping=True)))
        mod = api.prepare_playback(source, self.base)['module']
        original = playback_plan(source, mod.patterns)
        marked = playback_plan(changed, mod.patterns)
        self.assertEqual(marked['events'], original['events'])
        position = next(p for p in marked['positions'] if p['id'] == 'second/tie_b')
        self.assertTrue(position['tapping'])
        self.assertTrue(position['tied_in'])
        projected = project_score(changed, mod.patterns)
        self.assertEqual(projected.patterns, project_score(source, mod.patterns).patterns)
        self.assertTrue(any('IT notation: tapping markings omitted' in d for d in projected.diagnostics))
        cleared = apply_score_edit(changed, dict(op='note_set', pattern='b', beat='head', note=dict(id='tie_b', tapping=False)))
        self.assertFalse(cleared['score']['patterns']['b']['beats'][0]['notes'][0]['tapping'])

    def test_chord_recognition_agent_is_read_only_and_guards_stale_track_context(self):
        diagram = dict(name='My authored label', first_fret=1, frets=[0, 1, 0, 2, 3, -1])
        before = self.path.read_bytes()
        history, future = len(self.st.history), len(self.st.future)
        result = agent.run(self.st, 'recognize_chord', dict(revision=self.st.text_sha(), track='guitar', chord=diagram))
        self.assertIn('proposals', result, result)
        self.assertEqual(result['proposals'][0]['name'], 'C')
        self.assertEqual(diagram['name'], 'My authored label')
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual((len(self.st.history), len(self.st.future)), (history, future))
        with self.assertRaisesRegex(ValueError, 'changed'):
            self.st.chord_suggestions(dict(revision='stale', track='guitar', chord=diagram))
        with self.assertRaisesRegex(ValueError, 'existing TAB track'):
            self.st.chord_suggestions(dict(revision=self.st.text_sha(), track='missing', chord=diagram))
        with self.assertRaises(ValueError):
            self.st.chord_suggestions(dict(revision=self.st.text_sha(), track='guitar', chord=diagram, sharp='yes'))
        self.assertEqual(self.path.read_bytes(), before)

    def test_percussion_shared_edits_clipboard_and_chord_refusal(self):
        source = score_song()
        track = source['score']['tracks']['guitar']
        track.update(tuning=[0] * 6, midi=dict(bank=128, program=0))
        source['score']['ties'] = []
        for pattern in source['score']['patterns'].values():
            for beat in pattern['beats']:
                for note in beat['notes']:
                    note.update(pitch=38 if note['string'] == 1 else 42,
                                fret=38 if note['string'] == 1 else 42)
        path = self.base / 'drums.yaml'
        path.write_bytes(api.to_yaml(source).encode())
        st = gui.State(path, headless=True)
        self.addCleanup(st.close)
        self.assertIsNone(st.error)
        before, history = path.read_bytes(), len(st.history)
        for tool, payload in (('recognize_chord', dict(chord=dict(name='', first_fret=1, frets=[0] * 6))),
                              ('generate_chords', dict(spec=dict(root=0)))):
            result = agent.run(st, tool, dict(revision=st.text_sha(), track='guitar', **payload))
            self.assertIn('percussion', result.get('error', ''), result)
        self.assertEqual((path.read_bytes(), len(st.history)), (before, history))
        clip = st.score_clipboard(dict(revision=st.text_sha(), pattern='a', beats=['chord'],
                                       occurrence='first'))['clipboard']
        self.assertEqual(clip['track_kinds'], {'guitar': 'percussion'})
        st.score_edit(dict(revision=st.text_sha(), op='beats_paste', pattern=1, row=12,
                           occurrence='second', clipboard=clip))
        pasted = st.song['score']['patterns']['b']['beats'][-1]
        self.assertEqual([(n['pitch'], n['fret'], n['string']) for n in pasted['notes']],
                         [(38, 38, 1), (42, 42, 2)])
        st.undo()
        self.assertEqual(path.read_bytes(), before)
        st.score_edit(dict(revision=st.text_sha(), op='note_set', pattern='a', beat='chord',
                           note=dict(id='c', pitch=46)))
        edited = st.song['score']['patterns']['a']['beats'][0]['notes'][1]
        self.assertEqual((edited['pitch'], edited['fret'], edited['string']), (46, 46, 2))
        st.undo()
        self.assertEqual(path.read_bytes(), before)

    def test_chord_generation_agent_stays_read_only_until_explicit_apply(self):
        from vulturetracker.chord_tools import generate_chords
        request = dict(revision=self.st.text_sha(), track='guitar', spec=dict(root=0),
                       profile='inversions', min_fret=0, max_fret=5, open_strings=True, count=3)
        before = self.path.read_bytes()
        history, future = len(self.st.history), len(self.st.future)
        result = agent.run(self.st, 'generate_chords', request)
        expected = generate_chords(self.st.song['score']['tracks']['guitar'], request['spec'],
                                   profile='inversions', min_fret=0, max_fret=5, open_strings=True, count=3)
        self.assertEqual(result['chords'], expected['chords'])
        self.assertEqual(result['settings'], expected['settings'])
        self.assertEqual(result['revision'], request['revision'])
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual((len(self.st.history), len(self.st.future)), (history, future))
        for changes, message in ((dict(revision='stale'), 'changed'),
                                 (dict(track='absent'), 'existing TAB track'),
                                 (dict(profile='unknown'), 'profile'),
                                 (dict(count=True), 'count')):
            with self.subTest(changes=changes), self.assertRaisesRegex(ValueError, message):
                self.st.chord_suggestions(dict(request, **changes), generate=True)
        self.assertEqual(self.path.read_bytes(), before)
        self.st.score_edit(dict(op='chord_notes', pattern='a', beat='chord', chord=result['chords'][0],
                                revision=self.st.text_sha()))
        self.assertEqual(len(self.st.history), history + 1)
        self.assertEqual(self.st.song['score']['patterns']['a']['beats'][0]['chord'], result['chords'][0])
        self.st.undo()
        self.assertEqual(self.path.read_bytes(), before)

    def pattern_edit(self, pattern, cells):
        occurrence = next(o['occurrence'] for o in self.st.facts['orders'] if o['index'] == pattern)
        self.st.edit_patterns([(pattern, cells)], occurrences={pattern: occurrence}, revision=self.st.text_sha())

    def test_repeats_keep_source_patterns_history_and_played_facts(self):
        source = repeat_song()
        path = self.base / 'repeats.yaml'
        path.write_bytes(api.to_yaml(source).encode())
        st = gui.State(path, headless=True)
        self.addCleanup(st.close)
        self.assertIsNone(st.error)
        self.assertEqual(st.mod.orders, [0, 1, 2])
        self.assertEqual(len(st.mod.patterns), 3)
        self.assertEqual([o['source_order'] for o in st.facts['playback_orders']], [0, 1, 0, 1, 2])
        self.assertEqual([o['occurrence'] for o in st.facts['orders']], ['first', 'second', 'third'])
        self.assertTrue(all(o['start'] is None for o in st.facts['orders']))
        self.assertEqual(len(st.mod.native_score['view']['occurrences']), 3)
        overview = agent.song_overview(st, {})
        self.assertEqual(len(overview['orders']), 3)
        self.assertEqual(len(overview['playback_orders']), 5)
        self.assertEqual(agent.read_pattern(st, {'pattern': 2})['occurrence'], 'third')
        before = path.read_bytes()
        st.edit_patterns([(0, [dict(row=0, ch=0, cell='F-5 01 ... ...')])],
                         occurrences={0: 'first'}, revision=st.text_sha())
        self.assertEqual([e['pitch'] for e in st.mod.native_score['plan']['events'] if e['type'] == 'note_on'],
                         [65, 66, 65, 66, 67])
        self.assertEqual(st.song['orders'], source['orders'])
        self.assertEqual(st.song['score']['order_ids'], source['score']['order_ids'])
        after = path.read_bytes()
        st.undo()
        self.assertEqual(path.read_bytes(), before)
        st.undo(redo=True)
        self.assertEqual(path.read_bytes(), after)
        reopened = gui.State(path, headless=True)
        self.addCleanup(reopened.close)
        self.assertIsNone(reopened.error)
        self.assertEqual(reopened.mod.native_score['plan'], st.mod.native_score['plan'])

    def test_repeats_ranges_and_listening_notes_keep_pass_identity(self):
        from vulturetracker import export
        path = self.base / 'repeat_ranges.yaml'
        path.write_bytes(api.to_yaml(repeat_song()).encode())
        st = gui.State(path, headless=True)
        self.addCleanup(st.close)
        self.assertIsNone(st.error)
        before = copy.deepcopy(st.meta)
        with self.assertRaisesRegex(ValueError, 'disjoint'):
            st.set_loop({'from': [0, 0], 'to': [0, 47]})
        self.assertEqual(st.meta, before)
        with self.assertRaisesRegex(ValueError, 'disjoint'):
            agent.set_audition(st, {'loop': {'from': [0, 0], 'to': [0, 47]}})
        self.assertEqual(st.meta, before)
        with self.assertRaisesRegex(ValueError, 'disjoint'):
            st.section_edit({'action': 'select', 'name': 'first'})
        st.section_edit({'action': 'delete', 'name': 'first'})
        st.section_edit({'action': 'save', 'name': 'body', 'start': 0, 'end': 2})
        st.section_edit({'action': 'select', 'name': 'body'})
        st.set_loop({'from': [0, 0], 'to': [1, 47]})
        resolved = st._playback_selection()
        self.assertEqual(resolved['playback_region']['to'], [3, 47])
        self.assertEqual(resolved['playback_loop']['to'], [3, 47])
        snap = export.snapshot(st.song, self.base, region=st._order_region(st.orders), tail=0)
        self.assertEqual(snap['range_at'], [[0, 1], [16, 1]])
        bundle = st.prepared_playback(48000)
        self.assertEqual(bundle['snapshot']['range_at'], snap['range_at'])
        measured = agent.run(st, 'measure', {'orders': [0, 2]})
        self.assertNotIn('error', measured)
        self.assertEqual([v['order'] for v in measured['per_order']], [0, 1, 0, 1])
        self.assertEqual([v['pass'] for v in measured['per_order']], [1, 1, 2, 2])
        with self.assertRaisesRegex(ValueError, 'disjoint'):
            api.measure(st.song, orders=[0, 1], base_dir=self.base, rate=8000)
        with self.assertRaisesRegex(ValueError, 'pass'):
            st.add_note(dict(order=0, row=0, text='ambiguous'))
        for i in (0, 2):
            visit = st.facts['playback_orders'][i]
            item = st.add_note(dict(order=0, row=0, text=f'pass {visit["pass"]}',
                play_id=visit['id'], revision=st.text_sha()))
            self.assertEqual((item['order'], item['play_order'], item['source_occurrence']), (0, i, 'first'))
            self.assertEqual(item['time'], round(visit['start'], 2))
        self.assertIn('pass 2 (played 2)', st.report())
        with self.assertRaisesRegex(ValueError, 'revision'):
            st.sounding_rows(0, play_id='play_3', revision='stale')

    def test_repeat_fragments_source_rows_notes_and_shared_ranges(self):
        from vulturetracker import export
        path = self.base / 'fragments.yaml'
        path.write_bytes(api.to_yaml(repeat_fragment_song()).encode())
        st = gui.State(path, headless=True)
        self.addCleanup(st.close)
        self.assertIsNone(st.error)
        self.assertEqual(len(st.facts['orders']), 1)
        self.assertEqual([o['rows'] for o in st.facts['playback_orders']], [24] * 4)
        self.assertEqual(st.facts['orders'][0]['playback_loop'], {'from': [0, 0], 'to': [3, 23]})
        for i in (1, 3):
            visit = st.facts['playback_orders'][i]
            revision = st.text_sha()
            self.assertEqual(st._played_position(0, 30, visit['id'], revision), (i, 6))
            rows = st.sounding_rows(0, play_id=visit['id'], revision=revision)
            self.assertEqual(len(rows), 24)
            sounding = st.sounding(0, 30, play_id=visit['id'], revision=revision)
            self.assertTrue(sounding)
            item = st.add_note(dict(order=0, row=30, play_id=visit['id'], revision=revision, text='later fragment'))
            self.assertEqual((item['row'], item['play_row'], item['play_order']), (30, 6, i))
            self.assertEqual(item['time'], round(visit['start'] + visit['row_times'][6], 2))
            item['sounding'] = []
            st._rescan_notes()
            self.assertEqual(item['sounding'], sounding)
            with self.assertRaisesRegex(ValueError, 'reachable'):
                st.sounding(0, 6, play_id=visit['id'], revision=revision)
        before = copy.deepcopy(st.meta)
        with self.assertRaisesRegex(ValueError, 'disjoint'):
            st.set_loop({'from': [0, 18], 'to': [0, 29]})
        self.assertEqual(st.meta, before)
        st.set_loop({'from': [0, 0], 'to': [0, 47]})
        self.assertEqual(st._playback_selection()['playback_loop']['to'], [3, 23])
        self.assertEqual(export.snapshot(st.song, self.base, region=(0, 0, 0, 47), tail=0)['range_at'], [[0, 1], [8, 1]])
        st.edit_patterns([(0, [dict(row=24, ch=0, cell='G-5 01 ... ...')])],
                         occurrences={0: 'first'}, revision=st.text_sha())
        self.assertEqual([e['pitch'] for e in st.mod.native_score['plan']['events'] if e['type'] == 'note_on'],
                         [64, 67, 64, 67])
        st.undo()
        reopened = gui.State(path, headless=True)
        self.addCleanup(reopened.close)
        self.assertIsNone(reopened.error)
        self.assertEqual(reopened.mod.native_score['plan'], st.mod.native_score['plan'])

    def test_stroke_shared_voice_edit_pattern_agent_history_and_reopen(self):
        source = stroke_song()
        source['score']['patterns']['a']['beats'][0].pop('stroke')
        source['score']['patterns']['a']['beats'][0].pop('pick_stroke')
        path = self.base / 'stroke.yaml'
        path.write_bytes(api.to_yaml(source).encode())
        st = gui.State(path, headless=True)
        self.addCleanup(st.close)
        self.assertIsNone(st.error)
        before = path.read_bytes()
        chord = copy.deepcopy(st.song['score']['patterns']['a']['beats'][0])
        chord.update(stroke={'direction': 'down', 'value': 4}, pick_stroke='up')
        result = agent.run(st, 'edit_score', {'revision': st.text_sha(), 'edit': {
            'op': 'beat_set', 'pattern': 'a', 'beat': chord}})
        self.assertTrue(result.get('ok'), result)
        beats = st.song['score']['patterns']['a']['beats']
        self.assertTrue(all(b['stroke'] == chord['stroke'] and b['pick_stroke'] == 'up' for b in beats))
        ons = [e for e in st.mod.native_score['plan']['events'] if e['type'] == 'note_on']
        self.assertEqual({e['pitch']: Fraction(*e['at']) for e in ons}, {64: Fraction(1, 16), 55: Fraction(1, 32), 40: 0})
        rows = st.pattern_rows(0, 'first')
        self.assertEqual([parse_cell(rows['display_rows'][0][ch]).note for ch in (0, 2, 5)], [64, 55, 40])
        self.assertTrue(all(p['row'] == [0, 1] for p in st.score_view()['positions'] if p['kind'] == 'note'))
        changed = path.read_bytes()
        st.undo()
        self.assertEqual(path.read_bytes(), before)
        st.undo(redo=True)
        self.assertEqual(path.read_bytes(), changed)
        reopened = gui.State(path, headless=True)
        self.addCleanup(reopened.close)
        self.assertIsNone(reopened.error)
        self.assertEqual(reopened.mod.native_score['plan'], st.mod.native_score['plan'])

    def test_written_voices_pattern_identity_agent_ranges_history_and_reopen(self):
        path = self.base / 'voices.yaml'
        path.write_bytes(api.to_yaml(written_voice_song()).encode())
        st = gui.State(path, headless=True)
        self.addCleanup(st.close)
        self.assertIsNone(st.error)
        before = path.read_bytes()
        view = st.pattern_rows(0, 'first')
        collision = next(c for c in view['collisions'] if (c['row'], c['ch']) == (0, 0))
        self.assertEqual({o['id'] for o in collision['owners']}, {'first/long', 'first/short'})
        read = agent.read_pattern(st, dict(pattern='a', occurrence='first', from_row=0, to_row=0))
        self.assertEqual(read['collisions'], view['collisions'])
        st.selection = dict(pattern='a', order=0, rows=[0, 0], channels=[0, 0], occurrence='first',
                            source_note=dict(id='first/short', beat='short', note='short', voice=1, occurrence='first'))
        selected = agent.get_selection(st, {})
        self.assertEqual(selected['source_note']['id'], 'first/short')
        self.assertEqual(selected['collisions'], [collision])
        self.assertIsNone(parse_cell(view['display_rows'][0][0]).note)
        self.assertIsNone(parse_cell(view['display_rows'][3][0]).note)
        self.assertTrue(next(b for b in view['bindings'] if b['row'] == 3 and b['role'] == 'release')['sounding_overlap'])
        sounding = gui.native_sounding_table(st.mod)[0]
        self.assertEqual(len(sounding[0]), 2)
        self.assertEqual(len(sounding[3]), 1)
        self.assertEqual(sounding[3][0]['note'], 'F-5')
        for cell in ('G-5 01 ... ...', '... 02 ... ...', '... .. v20 ...'):
            with self.subTest(cell=cell), self.assertRaises((ValueError, SongError)):
                st.edit_patterns([(0, [dict(row=0, ch=0, cell=cell)])],
                                 occurrences={0: 'first'}, revision=st.text_sha())
            self.assertEqual(path.read_bytes(), before)
        selection = dict(pattern=0, occurrence='first', r0=0, r1=0,
                         cols=[[0, ['note', 'instrument', 'volume']]])
        with self.assertRaises((ValueError, SongError)):
            st.pattern_clipboard(dict(revision=st.text_sha(), selection=selection, cut=True))
        self.assertEqual(path.read_bytes(), before)
        st.score_edit(dict(op='note_set', pattern='a', beat='short', note=dict(id='short', pitch=67, fret=3),
                           revision=st.text_sha()))
        self.assertEqual([b['notes'][0]['pitch'] for b in st.song['score']['patterns']['a']['beats']], [65, 67])
        st.undo()
        self.assertEqual(path.read_bytes(), before)
        result = agent.run(st, 'transform_patterns', dict(action='transpose', semitones=1,
            revision=st.text_sha(), selections=[dict(pattern='a', from_row=0, to_row=0, channels=[1])]))
        self.assertTrue(result.get('ok'), result)
        self.assertEqual([b['notes'][0]['pitch'] for b in st.song['score']['patterns']['a']['beats']], [66, 67])
        changed = path.read_bytes()
        st.undo()
        self.assertEqual(path.read_bytes(), before)
        st.undo(redo=True)
        self.assertEqual(path.read_bytes(), changed)
        reopened = gui.State(path, headless=True)
        self.addCleanup(reopened.close)
        self.assertIsNone(reopened.error)
        self.assertEqual(reopened.mod.native_score['plan'], st.mod.native_score['plan'])
        both = st.pattern_clipboard(dict(revision=st.text_sha(), selection=dict(selection, all_heads=True)))['clipboard']
        st.paste_pattern_clipboard(dict(revision=st.text_sha(), pattern=1, occurrence='second',
                                       row=0, channel=0, clipboard=both))
        pasted = st.song['score']['patterns']['b']['beats']
        self.assertEqual({b['voice'] for b in pasted}, {0, 1})
        self.assertEqual(sum(len(b['notes']) for b in pasted), 2)
        self.assertEqual(len({b['notes'][0]['id'] for b in pasted}), 2)
        current = path.read_bytes()
        with self.assertRaises((ValueError, SongError)):
            st.paste_pattern_clipboard(dict(revision=st.text_sha(), pattern=1, occurrence='second',
                                           row=0, channel=0, clipboard=both))
        self.assertEqual(path.read_bytes(), current)

    def test_chord_annotation_shared_history_copy_and_playback_identity(self):
        source = stroke_song()
        # Use a tick-exact stroke for the subsequent strict-IT clipboard edit.
        source['score']['patterns']['a']['beats'][1]['written']['value'] = 4
        path = self.base / 'chord-diagram.yaml'
        path.write_bytes(api.to_yaml(source).encode())
        st = gui.State(path, headless=True)
        self.addCleanup(st.close)
        self.assertIsNone(st.error)
        before = path.read_bytes()
        events = copy.deepcopy(st.mod.native_score['plan']['events'])
        diagram = dict(name='C / chosen voicing', first_fret=1, frets=[0, 1, 0, 2, 3, -1])
        edited = copy.deepcopy(st.song['score']['patterns']['a']['beats'][0])
        edited['chord'] = diagram
        result = agent.run(st, 'edit_score', {'revision': st.text_sha(), 'edit': {
            'op': 'beat_set', 'pattern': 'a', 'beat': edited}})
        self.assertTrue(result.get('ok'), result)
        self.assertEqual(st.mod.native_score['plan']['events'], events)
        self.assertTrue(all(b['chord'] == diagram for b in st.song['score']['patterns']['a']['beats']))
        self.assertEqual({name: {k: v for k, v in spec.items() if k != 'by'}
                          for name, spec in st.song['patterns'].items()}, source['patterns'])
        changed = path.read_bytes()
        st.undo()
        self.assertEqual(path.read_bytes(), before)
        st.undo(redo=True)
        self.assertEqual(path.read_bytes(), changed)
        reopened = gui.State(path, headless=True)
        self.addCleanup(reopened.close)
        self.assertIsNone(reopened.error)
        self.assertEqual(reopened.song['score'], st.song['score'])
        clip = st.score_clipboard(dict(revision=st.text_sha(), pattern='a', beats=['chord', 'rest'],
                                       occurrence='first'))['clipboard']
        st.score_edit(dict(op='beats_paste', pattern=1, row=0, occurrence='second', clipboard=clip,
                           revision=st.text_sha()))
        self.assertTrue(all(b['chord'] == diagram for b in st.song['score']['patterns']['b']['beats']))
        notes = st.pattern_clipboard(dict(revision=st.text_sha(), selection=dict(pattern=0,
            occurrence='first', r0=0, r1=0, cols=[[0, ['note', 'instrument', 'volume']]], notes=['s1'])))['clipboard']
        self.assertTrue(all('chord' not in b for b in notes['score']['beats']))

    def test_chord_notes_agent_pattern_midi_history_and_reopen(self):
        from tests.test_tablature import note
        from vulturetracker import export
        import io
        import mido

        source = written_voice_song()
        source['instruments'][2] = {'sample': 1}
        selected, other = source['score']['patterns']['a']['beats']
        selected['notes'][0].update(instrument=2, fade_in=True)
        other['notes'].append(dict(note('keep', 59, 2, 0), velocity=77))
        path = self.base / 'chord-notes.yaml'
        path.write_bytes(api.to_yaml(source).encode())
        st = gui.State(path, headless=True)
        self.addCleanup(st.close)
        self.assertIsNone(st.error)
        before, history = path.read_bytes(), len(st.history)
        diagram = dict(name='Chosen notes', first_fret=1, frets=[3, -1, 2, -1, -1, -1])
        result = agent.run(st, 'edit_score', dict(revision=st.text_sha(), edit=dict(
            op='chord_notes', pattern='a', beat='long', chord=diagram, velocity=80)))
        self.assertTrue(result.get('ok'), result)
        self.assertEqual(len(st.history), history + 1)
        selected, other = st.song['score']['patterns']['a']['beats']
        self.assertEqual({(n['string'], n['pitch'], n['velocity']) for n in selected['notes']},
                         {(1, 67, 80), (3, 57, 80)})
        self.assertTrue(all(n['id'] not in {'long', 'short', 'keep'} for n in selected['notes']))
        self.assertTrue(all('instrument' not in n and 'fade_in' not in n for n in selected['notes']))
        self.assertEqual([n['id'] for n in other['notes']], ['keep'])
        self.assertEqual(selected['written'], source['score']['patterns']['a']['beats'][0]['written'])
        self.assertEqual((selected['chord'], other['chord']), (diagram, diagram))
        self.assertEqual(st.song['patterns']['a']['data'], source['patterns']['a']['data'])
        rows = st.pattern_rows(0, 'first')['display_rows']
        self.assertEqual([parse_cell(rows[0][ch]).note for ch in (0, 1, 2)], [67, 59, 57])
        self.assertEqual([parse_cell(rows[0][ch]).instrument for ch in (0, 2)], [1, 1])
        midi, report = export.native_to_midi(export.snapshot(st.song, self.base, tail=0))
        mid = mido.MidiFile(file=io.BytesIO(midi))
        ons, offs = [], []
        for track in mid.tracks:
            at = 0
            for msg in track:
                at += msg.time
                if msg.type == 'note_on' and msg.velocity:
                    ons.append((Fraction(at, mid.ticks_per_beat), msg.note, msg.velocity))
                elif msg.type == 'note_off':
                    offs.append((Fraction(at, mid.ticks_per_beat), msg.note))
        self.assertEqual(sorted(ons), [(0, 57, 80), (0, 59, 77), (0, 67, 80)])
        self.assertEqual(sorted(offs), [(Fraction(1, 4), 59), (1, 57), (1, 67)])
        self.assertEqual(report['note_count'], 3)
        changed = path.read_bytes()
        st.undo()
        self.assertEqual(path.read_bytes(), before)
        st.undo(redo=True)
        self.assertEqual(path.read_bytes(), changed)
        reopened = gui.State(path, headless=True)
        self.addCleanup(reopened.close)
        self.assertIsNone(reopened.error)
        self.assertEqual(reopened.mod.native_score['plan'], st.mod.native_score['plan'])

    def test_chord_notes_tie_refusal_is_atomic_and_explicit_removal_is_one_step(self):
        st = self.st
        before, history = self.path.read_bytes(), len(st.history)
        edit = dict(op='chord_notes', pattern='a', beat='tail',
                    chord=dict(name='F', first_fret=1, frets=[1, -1, -1, -1, -1, -1]))
        with self.assertRaises((ValueError, SongError)):
            st.score_edit(dict(edit, revision=st.text_sha()))
        self.assertEqual((self.path.read_bytes(), len(st.history)), (before, history))
        st.score_edit(dict(edit, remove_ties=True, revision=st.text_sha()))
        self.assertEqual(st.song['score']['ties'], [])
        self.assertEqual(len(st.history), history + 1)
        self.assertEqual(len([e for e in st.mod.native_score['plan']['events']
                              if e['type'] == 'note_on' and e['id'] == 'second/tie_b']), 1)
        st.undo()
        self.assertEqual(self.path.read_bytes(), before)

    def test_chord_notes_whole_rest_noop_keeps_source_text_and_history(self):
        from tests.test_tablature import beat
        source = score_song()
        source['patterns']['a']['data'] = ''
        source['score']['ties'] = []
        source['score']['patterns']['a']['beats'] = [beat('rest', [0, 1], [])]
        source['score']['patterns']['b']['beats'] = []
        path = self.base / 'chord-noop.yaml'
        path.write_bytes(api.to_yaml(source).encode())
        st = gui.State(path, headless=True)
        self.addCleanup(st.close)
        before, history = path.read_bytes(), len(st.history)
        st.score_edit(dict(op='chord_notes', pattern='a', beat='rest',
                           chord=dict(name='No change', first_fret=0, frets=[-1] * 6), revision=st.text_sha()))
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(len(st.history), history)

    def test_write_mix_clears_exact_source_pan_only_for_explicit_pan_and_undo_restores(self):
        source = score_song()
        source['score']['tracks']['guitar']['midi'] = dict(program=25, source_pan=dict(value=63, mixer_pan=32))
        path = self.base / 'source-pan.yaml'
        path.write_bytes(('# Keep this comment.\n' + api.to_yaml(source)).encode())
        st = gui.State(path, headless=True)
        self.addCleanup(st.close)
        self.assertIsNone(st.error)
        before = path.read_bytes()
        binding = source['score']['tracks']['guitar']['midi']['source_pan']
        self.assertEqual(st.snapshot()['source_pan_channels'], list(range(6)))
        st.set_mix({'volume': {'0': 32}})
        self.assertEqual(path.read_bytes(), before)
        st.apply_mix()
        self.assertEqual(st.song['score']['tracks']['guitar']['midi']['source_pan'], binding)
        self.assertEqual(st.song['module']['channels'][0]['volume'], 32)
        st.undo()
        self.assertEqual(path.read_bytes(), before)
        history = len(st.history)
        st.set_mix({'pan': {'5': 32}})  # Explicit center, even though the audio value is unchanged.
        self.assertEqual(path.read_bytes(), before)
        st.apply_mix()
        self.assertNotIn('source_pan', st.song['score']['tracks']['guitar']['midi'])
        self.assertEqual(st.snapshot()['source_pan_channels'], [])
        self.assertEqual(len(st.history), history + 1)
        self.assertTrue(path.read_text().startswith('# Keep this comment.'))
        changed = path.read_bytes()
        reopened = gui.State(path, headless=True)
        self.addCleanup(reopened.close)
        self.assertNotIn('source_pan', reopened.song['score']['tracks']['guitar']['midi'])
        st.undo()
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(st.song['score']['tracks']['guitar']['midi']['source_pan'], binding)
        st.undo(redo=True)
        self.assertEqual(path.read_bytes(), changed)

    def test_let_ring_shares_pattern_release_history_and_conflict_guard(self):
        source = let_ring_song()
        source['score']['patterns']['a']['beats'][0]['notes'][0].pop('let_ring')
        path = self.base / 'ring.yaml'
        path.write_bytes(api.to_yaml(source).encode())
        st = gui.State(path, headless=True)
        self.addCleanup(st.close)
        self.assertIsNone(st.error)
        before = path.read_bytes()
        st.score_edit(dict(op='note_set', pattern='a', beat='ring', note=dict(id='ring', let_ring=True),
                           revision=st.text_sha()))
        rows = st.pattern_rows(0, 'first')['display_rows']
        self.assertIsNone(parse_cell(rows[12][0]).note)
        self.assertEqual(parse_cell(rows[12][0]).param, 83)
        self.assertEqual(parse_cell(rows[24][0]).note, NOTE_OFF)
        position = next(p for p in st.mod.native_score['plan']['positions'] if p['id'] == 'first/ring')
        self.assertEqual((position['end'], position['sounding_end']), ([1, 1], [2, 1]))
        changed, history = path.read_bytes(), len(st.history)
        with self.assertRaises((ValueError, SongError)):
            st.edit_patterns([(0, [dict(row=18, ch=0, cell='E-5 01 ... ...')])],
                             occurrences={0: 'first'}, revision=st.text_sha())
        self.assertEqual((path.read_bytes(), len(st.history)), (changed, history))
        st.undo()
        self.assertEqual(path.read_bytes(), before)
        st.undo(redo=True)
        self.assertEqual(path.read_bytes(), changed)
        reopened = gui.State(path, headless=True)
        self.addCleanup(reopened.close)
        self.assertIsNone(reopened.error)
        self.assertEqual(reopened.mod.native_score['plan'], st.mod.native_score['plan'])

    def test_swing_measure_keeps_written_pattern_and_shared_history(self):
        source = swing_song('none')
        path = self.base / 'swing.yaml'
        path.write_bytes(api.to_yaml(source).encode())
        st = gui.State(path, headless=True)
        self.addCleanup(st.close)
        before = path.read_bytes()
        measure = copy.deepcopy(source['score']['measures'][0])
        measure['swing'] = 'eighth'
        st.score_edit(dict(op='measure_set', measure=measure, revision=st.text_sha()))
        plan = st.mod.native_score['plan']
        ons = [e for e in plan['events'] if e['type'] == 'note_on']
        self.assertEqual([e['at'] for e in ons], [[0, 1], [2, 3]])
        self.assertEqual(parse_cell(st.pattern_rows(0, 'first')['display_rows'][6][1]).note, 59)
        self.assertEqual(st.song['patterns'], source['patterns'])
        changed, history = path.read_bytes(), len(st.history)
        with self.assertRaises((ValueError, SongError)):
            st.edit_patterns([(0, [dict(row=7, ch=1, cell='C-5 01 ... ...')])],
                             occurrences={0: 'first'}, revision=st.text_sha())
        self.assertEqual((path.read_bytes(), len(st.history)), (changed, history))
        st.undo()
        self.assertEqual(path.read_bytes(), before)
        st.undo(redo=True)
        self.assertEqual(path.read_bytes(), changed)
        reopened = gui.State(path, headless=True)
        self.addCleanup(reopened.close)
        self.assertIsNone(reopened.error)
        self.assertEqual(reopened.mod.native_score['plan'], plan)

    def test_held_coincident_releases_share_read_only_pattern_marker(self):
        source = let_ring_song()
        source['score']['patterns']['a']['beats'][1]['notes'][0].update(pitch=66, string=1, fret=2)
        path = self.base / 'held.yaml'
        path.write_bytes(api.to_yaml(source).encode())
        st = gui.State(path, headless=True)
        self.addCleanup(st.close)
        self.assertIsNone(st.error)
        view = st.pattern_rows(0, 'first')
        self.assertEqual(parse_cell(view['display_rows'][24][0]).note, NOTE_OFF)
        self.assertEqual(len([b for b in view['bindings'] if b['row'] == 24 and b['ch'] == 0]), 1)
        plan = st.mod.native_score['plan']
        self.assertEqual({e['id'] for e in plan['events'] if e['type'] == 'note_off' and e['at'] == [2, 1]},
                         {'first/ring', 'first/next'})
        before, history = path.read_bytes(), len(st.history)
        with self.assertRaisesRegex(ValueError, 'generated release'):
            st.edit_patterns([(0, [dict(row=24, ch=0, cell='... .. ... ...')])],
                             occurrences={0: 'first'}, revision=st.text_sha())
        self.assertEqual((path.read_bytes(), len(st.history)), (before, history))
        st.edit_patterns([(0, [dict(row=12, ch=0, cell='G-5 01 ... T53')])],
                         occurrences={0: 'first'}, revision=st.text_sha())
        self.assertEqual(st.song['score']['patterns']['a']['beats'][1]['notes'][0]['pitch'], 67)
        self.assertTrue(st.song['score']['patterns']['a']['beats'][0]['notes'][0]['let_ring'])
        self.assertEqual(parse_cell(st.pattern_rows(0, 'first')['display_rows'][24][0]).note, NOTE_OFF)

    def test_grace_edit_keeps_written_anchor_and_atomic_history_through_reopen(self):
        st = self.st
        self.assertIsNone(st.error)
        before, history = self.path.read_bytes(), len(st.history)
        written = copy.deepcopy(st.song['score']['patterns']['a']['beats'][1])
        self.edit(op='note_set', pattern='a', beat='triplet0',
                  note=dict(id='t0', grace=dict(fret=0, value=16, velocity=47,
                                               transition='hammer', on_beat=True)))
        self.assertIsNone(st.error)
        self.assertEqual(len(st.history), history + 1)
        authored = st.song['score']['patterns']['a']['beats'][1]
        self.assertEqual((authored['id'], authored['at'], authored['written']),
                         (written['id'], written['at'], written['written']))
        self.assertEqual(self.cell(0, 12, 1).note, 60)  # Pattern entry remains at written quarter 1.
        self.assertIsNone(self.cell(0, 15, 1).note)     # No materialized entry at performed quarter 5/4.
        view = st.score_view()
        position = next(p for p in view['positions'] if p.get('id') == 'first/t0')
        self.assertEqual((position['at'], position['end'], position['sounding_start'], position['attack_id']),
                         ([1, 1], [4, 3], [5, 4], 'first/t0'))
        plan = copy.deepcopy(st.mod.native_score['plan'])
        main = next(e for e in plan['events'] if e['id'] == 'first/t0' and e['type'] == 'note_on')
        grace = next(e for e in plan['events'] if e['id'] == 'first/t0/grace' and e['type'] == 'note_on')
        self.assertEqual((main['at'], grace['at'], grace['source_id'], grace['role'], grace['velocity']),
                         ([5, 4], [1, 1], 'first/t0', 'grace', 47))
        self.assertIsNone(main['velocity'])  # Grace did not invent a main dynamic.
        self.assertTrue(all(c.note is None for p in st.mod.patterns for row in p.rows for c in row))
        changed, history = self.path.read_bytes(), len(st.history)
        with self.assertRaisesRegex((ValueError, SongError), 'grace delayed attack'):
            self.pattern_edit(0, [dict(row=13, ch=1, cell='... .. v32 ...')])
        self.assertEqual((self.path.read_bytes(), len(st.history)), (changed, history))
        self.assertEqual(st.mod.native_score['plan'], plan)
        self.assertIsNone(st.error)
        st.undo()
        self.assertEqual(self.path.read_bytes(), before)
        st.undo(redo=True)
        self.assertEqual(self.path.read_bytes(), changed)
        self.assertEqual(st.mod.native_score['plan'], plan)
        st.close()
        self.st = gui.State(self.path, headless=True)
        self.assertIsNone(self.st.error)
        self.assertEqual(self.st.mod.native_score['plan'], plan)
        self.assertEqual(self.cell(0, 12, 1).note, 60)
        self.assertIsNone(self.cell(0, 15, 1).note)
        self.st.undo()  # History also survives reopening, not only the authored mapping.
        self.assertEqual(self.path.read_bytes(), before)
        self.st.undo(redo=True)
        self.assertEqual(self.path.read_bytes(), changed)
        self.assertEqual(self.st.mod.native_score['plan'], plan)

    def test_before_grace_crosses_occurrence_without_moving_source_or_raw_backing(self):
        source = score_song()
        source['score']['ties'] = []
        source['score']['patterns']['a']['beats'] = [
            b for b in source['score']['patterns']['a']['beats'] if b['id'] != 'tail']
        path = self.base / 'grace-crossing.yaml'
        path.write_bytes(api.to_yaml(source).encode())
        st = gui.State(path, headless=True)
        self.addCleanup(st.close)
        self.assertIsNone(st.error)
        backing = copy.deepcopy(st.song['patterns'])
        st.score_edit(dict(op='note_set', pattern='b', beat='head',
                           note=dict(id='tie_b', grace=dict(fret=2, value=16, velocity=47, on_beat=False)),
                           revision=st.text_sha()))
        plan = copy.deepcopy(st.mod.native_score['plan'])
        grace = next(e for e in plan['events'] if e['id'] == 'second/tie_b/grace' and e['type'] == 'note_on')
        main = next(e for e in plan['events'] if e['id'] == 'second/tie_b' and e['type'] == 'note_on')
        self.assertEqual((grace['at'], grace['occurrence'], grace['pattern'], main['at']),
                         ([15, 4], 'second', 'b', [4, 1]))
        position = next(p for p in plan['positions'] if p['id'] == 'second/tie_b')
        self.assertEqual((position['local_at'], position['at'], position['grace_start']),
                         ([0, 1], [4, 1], [15, 4]))
        actions = gui.native_actions(st.mod)
        self.assertEqual(next(a['order'] for a in actions if a['id'] == grace['id'] and a['type'] == 'note_on'), 0)
        self.assertEqual(next(a['order'] for a in actions if a['id'] == main['id'] and a['type'] == 'note_on'), 1)
        self.assertIsNone(parse_cell(st.pattern_rows(0, 'first')['display_rows'][45][0]).note)
        self.assertEqual(parse_cell(st.pattern_rows(1, 'second')['display_rows'][0][0]).note, 64)
        self.assertEqual(st.song['patterns'], backing)
        changed, history = path.read_bytes(), len(st.history)
        with self.assertRaisesRegex((ValueError, SongError), 'grace before-beat prefix'):
            st.edit_patterns([(0, [dict(row=46, ch=0, cell='C-5 01 ... ...')])],
                             occurrences={0: 'first'}, revision=st.text_sha())
        self.assertEqual((path.read_bytes(), len(st.history)), (changed, history))
        self.assertEqual(st.mod.native_score['plan'], plan)
        self.assertEqual(st.song['patterns'], backing)
        st.close()
        reopened = gui.State(path, headless=True)
        self.addCleanup(reopened.close)
        self.assertIsNone(reopened.error)
        self.assertEqual(reopened.mod.native_score['plan'], plan)
        self.assertEqual(reopened.song['patterns'], backing)

    def test_tempo_edit_pattern_history_and_reopen_share_one_command(self):
        st = self.st
        before, count = self.path.read_bytes(), len(st.history)
        score = copy.deepcopy(st.song['score'])
        request = dict(op='tempo_set', occurrence='first', at=[0, 1], bpm=83, scope='occurrence')
        self.edit(**request)
        self.assertEqual(len(st.history), count + 1)
        self.assertEqual(st.song['score'], score)
        self.assertEqual(st.mod.patterns[0].rows[0][0].effect, 24)  # unrelated pan retained
        self.assertEqual((self.cell(0, 0, 1).effect, self.cell(0, 0, 1).param), (20, 83))
        self.assertEqual(st.score_view()['tempos'][0], {'at': [0, 1], 'bpm': 83})
        saved = self.path.read_bytes()
        self.edit(**request)
        self.assertEqual((self.path.read_bytes(), len(st.history)), (saved, count + 1))
        st.undo()
        self.assertEqual(self.path.read_bytes(), before)
        st.undo(redo=True)
        self.assertEqual(self.path.read_bytes(), saved)
        reopened = gui.State(self.path, headless=True)
        self.addCleanup(reopened.close)
        self.assertEqual(reopened.score_view()['tempos'], st.score_view()['tempos'])
        self.pattern_edit(0, [{'row': 0, 'ch': 1, 'cell': 'C-5 01 ... T89'}])
        self.assertEqual(st.score_view()['tempo_commands'][0]['bpm'], 137)
        self.edit(**dict(request, bpm=None))
        self.assertEqual((self.cell(0, 0, 1).effect, self.cell(0, 0, 1).param), (0, 0))
        self.assertEqual(self.cell(0, 0, 1).note, 60)
        self.assertNotIn('tempos', st.score_view())
        self.assertEqual(st.mod.tempo, 120)

    def test_tempo_edit_refusals_leave_source_and_history_unchanged(self):
        st = self.st
        request = dict(op='tempo_set', occurrence='first', at=[1, 1], bpm=83, scope='occurrence')
        before = self.path.read_bytes(), len(st.history)
        with self.assertRaisesRegex(ValueError, 'changed'):
            st.score_edit(dict(request, revision='stale'))
        with self.assertRaisesRegex(RuntimeError, 'guard refused'):
            st.score_edit(dict(request, revision=st.text_sha()),
                          guard=lambda *_: (_ for _ in ()).throw(RuntimeError('guard refused')))
        with patch.object(st, '_write_step', side_effect=OSError('write refused')):
            with self.assertRaisesRegex(OSError, 'write refused'):
                self.edit(**request)
        self.assertEqual((self.path.read_bytes(), len(st.history)), before)
        st.song_edit([dict(op='mark', what='pattern', key='a', approved=True)])
        before = self.path.read_bytes(), len(st.history)
        with self.assertRaisesRegex(ValueError, 'approved'):
            self.edit(**request)
        self.assertEqual((self.path.read_bytes(), len(st.history)), before)

    def test_agent_tempo_edit_uses_existing_approval_and_history_guard(self):
        st = self.st
        request = dict(op='tempo_set', occurrence='first', at=[1, 1], bpm=83, scope='pattern')
        before, count = self.path.read_bytes(), len(st.history)
        result = agent.run(st, 'edit_score', {'revision': st.text_sha(), 'edit': request})
        self.assertTrue(result.get('ok'), result)
        self.assertEqual(len(st.history), count + 1)
        self.assertEqual(self.cell(0, 12, 0).param, 83)
        st.undo()
        self.assertEqual(self.path.read_bytes(), before)
        song = copy.deepcopy(st.song)
        song['module']['channels'][0]['approved'] = True
        st._commit(api.to_yaml(song))
        before = self.path.read_bytes(), len(st.history)
        result = agent.run(st, 'edit_score', {'revision': st.text_sha(), 'edit': request})
        self.assertIn('approved', result.get('error', ''))
        self.assertEqual((self.path.read_bytes(), len(st.history)), before)

    def test_cut_command_one_history_entry_and_atomic_guards(self):
        st = self.st
        before, history = self.path.read_bytes(), len(st.history)
        request = dict(action='cut', occurrence='first', track='guitar', voice=0, beats=['chord'], notes=['e'])
        result = st.score_command(dict(request, revision=st.text_sha()))
        self.assertEqual(result['revision'], st.text_sha())
        self.assertEqual(len(st.history), history + 1)
        self.assertEqual([n['id'] for n in st.song['score']['patterns']['a']['beats'][0]['notes']], ['c'])
        self.assertEqual(len(result['clipboard']['beats'][0]['notes']), 2)
        st.undo()
        self.assertEqual(self.path.read_bytes(), before)
        unchanged = self.path.read_bytes(), len(st.history)
        with self.assertRaisesRegex(ValueError, 'changed'):
            st.score_command(dict(request, revision='stale'))
        with self.assertRaisesRegex(RuntimeError, 'guard refused'):
            st.score_command(dict(request, revision=st.text_sha()),
                             guard=lambda *_: (_ for _ in ()).throw(RuntimeError('guard refused')))
        self.assertEqual((self.path.read_bytes(), len(st.history)), unchanged)
        with patch.object(st, '_write_step', side_effect=OSError('write refused')):
            with self.assertRaisesRegex(OSError, 'write refused'):
                st.score_command(dict(request, revision=st.text_sha()))
        self.assertEqual((self.path.read_bytes(), len(st.history)), unchanged)
        self.assertTrue(self.path.read_text().startswith('# Keep this source comment.'))

    def test_retune_command_one_undo_keeps_playback_pitch_and_refusal_writes_nothing(self):
        st = self.st
        before, history = self.path.read_bytes(), len(st.history)
        pitches = [e['pitch'] for e in st.mod.native_score['plan']['events'] if e['type'] == 'note_on']
        result = st.score_command(dict(action='retune', track='guitar', tuning=[63, 58, 54, 49, 44, 39],
                                       revision=st.text_sha()))
        self.assertEqual(len(st.history), history + 1)
        self.assertEqual(st.song['score']['tracks']['guitar']['tuning'], [63, 58, 54, 49, 44, 39])
        self.assertEqual([e['pitch'] for e in st.mod.native_score['plan']['events'] if e['type'] == 'note_on'], pitches)
        self.assertEqual(st.song['patterns'], score_song()['patterns'])
        self.assertIn('a/e', result['moved'])
        changed = self.path.read_bytes()
        st.undo()
        self.assertEqual(self.path.read_bytes(), before)
        st.undo(redo=True)
        self.assertEqual(self.path.read_bytes(), changed)
        st.undo()
        unchanged = self.path.read_bytes(), len(st.history)
        with self.assertRaisesRegex(ValueError, 'cannot place'):
            st.score_command(dict(action='retune', track='guitar', tuning=[64, 59, 55, 50, 45, 40], max_fret=0,
                                  revision=st.text_sha()))
        self.assertEqual((self.path.read_bytes(), len(st.history)), unchanged)
        self.assertTrue(self.path.read_text().startswith('# Keep this source comment.'))

    def test_transpose_command_one_undo_moves_playback_pitch(self):
        st = self.st
        before, history = self.path.read_bytes(), len(st.history)
        pitches = [e['pitch'] for e in st.mod.native_score['plan']['events'] if e['type'] == 'note_on']
        st.score_command(dict(action='transpose', semitones=-3, track='guitar', revision=st.text_sha()))
        self.assertEqual(len(st.history), history + 1)
        self.assertEqual([e['pitch'] for e in st.mod.native_score['plan']['events'] if e['type'] == 'note_on'],
                         [p - 3 for p in pitches])
        self.assertEqual(st.song['patterns'], score_song()['patterns'])
        changed = self.path.read_bytes()
        st.undo()
        self.assertEqual(self.path.read_bytes(), before)
        st.undo(redo=True)
        self.assertEqual(self.path.read_bytes(), changed)
        unchanged = self.path.read_bytes(), len(st.history)
        with self.assertRaisesRegex(ValueError, 'cuts the tie'):
            st.score_command(dict(action='transpose', semitones=1, track='guitar', scope='measure',
                                  occurrence='first', at=[0, 1], revision=st.text_sha()))
        self.assertEqual((self.path.read_bytes(), len(st.history)), unchanged)

    def test_repeat_command_approval_and_extension_one_undo(self):
        st = self.st
        source = score_song()
        source['score']['ties'] = []
        source['score']['patterns']['a']['beats'] = []
        source['score']['patterns']['b']['beats'][0]['at'] = [7, 2]
        st._commit('# Retain source.\n' + api.to_yaml(source))
        before, history = self.path.read_bytes(), len(st.history)
        request = dict(action='repeat', occurrence='second', track='guitar', voice=0, beats=['head'])
        result = st.score_command(dict(request, revision=st.text_sha()))
        self.assertEqual(len(st.song['orders']), 3)
        self.assertEqual(result['selection']['occurrence'], st.song['score']['order_ids'][2])
        self.assertEqual(len(st.history), history + 1)
        self.assertTrue(self.path.read_text().startswith('# Retain source.'))
        st.undo()
        self.assertEqual(self.path.read_bytes(), before)
        st.song_edit([{'op': 'mark', 'what': 'pattern', 'key': 'b', 'approved': True}])
        unchanged = self.path.read_bytes(), len(st.history)
        with self.assertRaisesRegex(ValueError, 'approved'):
            st.score_command(dict(action='cut', occurrence='second', track='guitar', voice=0,
                                  beats=['head'], revision=st.text_sha()))
        self.assertEqual((self.path.read_bytes(), len(st.history)), unchanged)

    def test_fret_pattern_undo_and_reopen_share_content(self):
        st = self.st
        self.assertIsNone(st.error)
        self.assertEqual(st.facts['bpm'], 120)  # score quarter notes, independent of tracker highlight spacing
        self.assertEqual(self.cell(0, 0, 1).note, 60)
        self.assertEqual(self.cell(0, 16, 1).note, 61)
        self.assertIsNone(self.cell(1, 0, 0).note)  # tied, not retriggered
        self.assertEqual(self.cell(1, 6, 0).note, NOTE_OFF)
        self.edit(op='note_set', pattern='a', beat='chord', note={'id': 'c', 'fret': 3})
        self.assertEqual(self.cell(0, 0, 1).note, 62)
        self.assertEqual(st.mod.patterns[0].rows[0][0].effect, 24)
        cell = self.cell(0, 0, 1)
        cell.note = 60
        self.pattern_edit(0, [{'row': 0, 'ch': 1, 'cell': format_cell(cell)}])
        note = st.song['score']['patterns']['a']['beats'][0]['notes'][1]
        self.assertEqual((note['pitch'], note['string'], note['fret']), (60, 2, 1))
        st.undo()
        self.assertEqual(self.cell(0, 0, 1).note, 62)
        st.undo(redo=True)
        self.assertEqual(self.cell(0, 0, 1).note, 60)
        st.close()
        self.st = gui.State(self.path, headless=True)
        self.assertIsNone(self.st.error)
        self.assertEqual(self.cell(0, 0, 1).note, 60)
        self.assertTrue(all(c.note is None for p in self.st.mod.patterns for row in p.rows for c in row))
        self.assertTrue(self.path.read_text().startswith('# Keep this source comment.'))
        self.assertNotIn('C-5', self.st.song['patterns']['a']['data'])  # no duplicate authored attack

    def test_stale_edit_and_timing_conflict_leave_history_and_file_unchanged(self):
        before = self.path.read_bytes(), len(self.st.history)
        with self.assertRaisesRegex(ValueError, 'changed'):
            self.st.score_edit({'op': 'note_delete', 'pattern': 'a', 'beat': 'chord', 'note': 'c', 'revision': 'old'})
        self.assertEqual((self.path.read_bytes(), len(self.st.history)), before)
        beat = copy.deepcopy(self.st.song['score']['patterns']['a']['beats'][0])
        beat['written'] = {'value': 64, 'dots': 2, 'tuplet': [13, 8]}
        beat['at'] = [7, 6]  # Valid fractional duration, but overlaps triplet0 on channel 1.
        with self.assertRaises((ValueError, SongError)):
            self.edit(op='beat_set', pattern='a', beat=beat)
        self.assertEqual((self.path.read_bytes(), len(self.st.history)), before)

    def test_rename_and_channel_move_retain_event_identity(self):
        self.st.song_edit([{'op': 'pattern_rename', 'old': 'a', 'new': 'intro'}])
        self.assertIn('intro', self.st.song['score']['patterns'])
        self.assertEqual(self.st.song['score']['order_ids'], ['first', 'second'])
        self.st.song_edit([{'op': 'channel_move', 'ch': 0, 'to': 2}])
        self.assertEqual(self.st.song['score']['tracks']['guitar']['channels'], [2, 0, 1, 3, 4, 5])
        self.assertEqual(self.cell(0, 0, 2).note, 64)
        self.assertEqual(self.st.mod.patterns[0].rows[0][2].effect, 24)

    def test_track_change_cannot_bypass_approved_pattern(self):
        song = score_song()
        song['patterns']['a']['approved'] = True
        self.st.close()
        self.path.write_bytes(api.to_yaml(song).encode())
        self.st = gui.State(self.path, headless=True)
        track = copy.deepcopy(song['score']['tracks']['guitar'])
        track['capo'] = 1
        before = self.path.read_bytes(), len(self.st.history)
        with self.assertRaisesRegex(ValueError, 'approved'):
            self.edit(op='track_set', track='guitar', value=track)
        self.assertEqual((self.path.read_bytes(), len(self.st.history)), before)

    def test_materialize_keeps_generated_notes_out_of_raw_source(self):
        self.st.materialize_pattern(0)
        self.assertEqual(self.cell(0, 0, 1).note, 60)
        self.assertNotIn('C-5', self.st.song['patterns']['a']['data'])
        self.assertIn('X40', self.st.song['patterns']['a']['data'])

    def test_pattern_note_preview_adoption_and_edit_preserve_playback(self):
        self.pattern_edit(0, [{'row': 24, 'ch': 2, 'cell': 'G-5 01 v48 X20'},
                             {'row': 30, 'ch': 2, 'cell': '=== .. ... ...'}])
        preview = next(p for p in self.st.score_view()['raw_positions'] if p['row'] == 24 and p['ch'] == 2)
        self.assertEqual(preview['pitch'], 67)
        self.assertFalse(preview['editable'])
        before = api.compile_song(self.st.song, self.base)[0]
        self.edit(op='promote_pattern', pattern='a', track='guitar', cells=[{'row': 24, 'ch': 2}])
        self.assertEqual(api.compile_song(self.st.song, self.base)[0], before)
        position = next(p for p in self.st.score_view()['positions'] if p.get('row') == [24, 1] and p.get('ch') == 2)
        self.edit(op='note_set', pattern='a', beat=position['beat'], note={'id': position['note'], 'pitch': 68})
        self.assertEqual(self.cell(0, 24, 2).note, 68)
        self.assertEqual(self.st.mod.patterns[0].rows[24][2].effect, 24)
        self.st.undo()
        self.st.undo()
        self.assertEqual(api.compile_song(self.st.song, self.base)[0], before)
        self.assertTrue(any(p['row'] == 24 and p['ch'] == 2 for p in self.st.score_view()['raw_positions']))

    def test_agent_score_edit_shares_history_and_protects_approved_channels(self):
        view = agent.run(self.st, 'read_score', {'pattern': 'a'})
        payload = {'revision': view['revision'], 'edit': {'op': 'note_set', 'pattern': 'a', 'beat': 'chord',
                                                        'note': {'id': 'c', 'fret': 3}}}
        result = agent.run(self.st, 'edit_score', payload)
        self.assertTrue(result.get('ok'), result)
        self.assertEqual(self.cell(0, 0, 1).note, 62)
        self.assertEqual(self.st.song['patterns']['a']['by'], 'you and agent')
        self.st.undo()
        self.assertEqual(self.cell(0, 0, 1).note, 60)
        song = copy.deepcopy(self.st.song)
        song['module']['channels'][1]['approved'] = True
        self.st.close()
        self.path.write_bytes(api.to_yaml(song).encode())
        self.st = gui.State(self.path, headless=True)
        payload['revision'] = self.st.text_sha()
        before = self.path.read_bytes(), len(self.st.history)
        result = agent.run(self.st, 'edit_score', payload)
        self.assertIn('approved', result.get('error', ''))
        self.assertEqual((self.path.read_bytes(), len(self.st.history)), before)

    def test_roll_resizes_authored_chord_as_one_history_step(self):
        before = len(self.st.history)
        self.edit(op='beat_resize', pattern=0, beat='chord', end_row=6)
        self.assertEqual(len(self.st.history), before + 1)
        self.assertEqual(self.st.song['score']['patterns']['a']['beats'][0]['written']['value'], 8)
        for ch in (0, 1):
            self.assertEqual(self.cell(0, 6, ch).note, NOTE_OFF)
        self.assertEqual(self.st.mod.patterns[0].rows[0][0].effect, 24)
        self.st.undo()
        self.assertEqual(self.st.song['score']['patterns']['a']['beats'][0]['written']['value'], 4)

    def test_tryout_and_export_keep_native_backing_paired_and_refuse_flattening(self):
        from vulturetracker import export
        before = self.path.read_bytes()
        with self.assertRaises(ValueError):
            api.tryout_song(self.st.song, (0, 1), compiled=self.st.mod)
        self.st.meta['orders'] = [0, 1]
        with self.assertRaises(ValueError):
            self.st.compiled_it()
        result = export.snapshot(self.st.song, self.base, tail=0)
        self.assertGreater(result['frames'], 0)
        self.assertIsNone(result['it'])
        self.assertTrue(result['plan']['events'])
        self.assertEqual(self.path.read_bytes(), before)

    def test_roll_move_preserves_identity_effect_and_history(self):
        self.edit(op='note_move', pattern=0, note='t0', to_row=25, pitch=62)
        moved = next(b for b in self.st.song['score']['patterns']['a']['beats'] if b['id'] == 'triplet0')
        self.assertEqual(moved['notes'][0]['id'], 't0')
        self.assertEqual(moved['at'], [25, 12])
        self.assertEqual(self.cell(0, 25, 1).note, 62)
        self.assertEqual(self.st.mod.patterns[0].rows[0][0].effect, 24)
        self.st.undo()
        self.assertEqual(self.cell(0, 12, 1).note, 60)

    def test_roll_chord_move_preserves_all_notes(self):
        self.edit(op='beat_move', pattern=0, beat='chord', to_row=24)
        moved = next(b for b in self.st.song['score']['patterns']['a']['beats'] if b['id'] == 'chord')
        self.assertEqual([n['id'] for n in moved['notes']], ['e', 'c'])
        self.assertEqual([self.cell(0, 24, ch).note for ch in (0, 1)], [64, 60])
        self.assertEqual(self.st.mod.patterns[0].rows[0][0].effect, 24)
        self.st.undo()
        self.assertEqual(self.cell(0, 0, 1).note, 60)

    def test_native_clipboard_uses_same_transaction(self):
        clipboard = self.st.score_clipboard({'pattern': 'a', 'beats': ['chord'], 'occurrence': 'first',
                                             'revision': self.st.text_sha()})['clipboard']
        self.edit(op='beats_paste', pattern=0, row=24, clipboard=clipboard, occurrence='first')
        beats = self.st.song['score']['patterns']['a']['beats']
        copied = next(b for b in beats if b['at'] == [2, 1])
        self.assertNotEqual(copied['id'], 'chord')
        self.assertEqual([self.cell(0, 24, ch).note for ch in (0, 1)], [64, 60])
        self.assertEqual(self.st.mod.patterns[0].rows[0][0].effect, 24)
        self.st.undo()
        self.assertFalse(any(b['at'] == [2, 1] for b in self.st.song['score']['patterns']['a']['beats']))

    def test_replacement_clipboard_atomic_history_raw_playback_it_and_reopen(self):
        self.test_cross_measure_clipboard_atomic_history_raw_playback_it_and_reopen(replace=True)

    def test_cross_measure_clipboard_atomic_history_raw_playback_it_and_reopen(self, replace=False):
        from vulturetracker import tablature, itreader
        source = score_song()
        for name in ('c', 'd'):
            source['patterns'][name] = dict(rows=48, data='')
            source['orders'].append(name)
            source['score']['order_ids'].append(name)
            source['score']['patterns'][name] = dict(row_step=[1, 12], beats=[])
        if replace:
            source['score']['patterns']['c']['beats'] = [dict(id='old', track='guitar', voice=0,
                at=[7, 2], written=dict(value=8, dots=0, tuplet=[1, 1]), notes=[])]
            source['score']['patterns']['d']['beats'] = [dict(id='old', track='guitar', voice=0,
                at=[0, 1], written=dict(value=8, dots=0, tuplet=[1, 1]), notes=[])]
        self.st.close()
        self.path.write_text('# Preserved comment\n' + api.to_yaml(source), encoding='utf-8')
        self.st = gui.State(self.path, headless=True)
        before = self.path.read_bytes()
        clip = self.st.score_clipboard(dict(revision=self.st.text_sha(), selection=[
            dict(occurrence='first', beats=['tail']), dict(occurrence='second', beats=['head'])]))['clipboard']
        frozen = copy.deepcopy(clip)
        edit = dict(op='beats_paste', pattern=2, row=42, occurrence='c', across=True, clipboard=clip, replace=replace)
        self.edit(**edit)
        saved = self.path.read_bytes()
        self.assertNotEqual(saved, before)
        self.assertEqual(self.st.song['patterns'], source['patterns'])
        self.assertEqual(self.st.song['score']['patterns']['a'], source['score']['patterns']['a'])
        plan = self.st.mod.native_score['plan']
        performed = [e for e in plan['events'] if e['type'] == 'note_on' and e['occurrence'] == 'c']
        self.assertEqual([(e['at'], e['pitch']) for e in performed], [([23, 2], 64)])
        release = next(e for e in plan['events'] if e['type'] == 'note_off' and e['id'] == performed[0]['id'])
        self.assertEqual(release['at'], [25, 2])
        compiled = api.compile_song(self.path)[0]
        reopened_it = itreader.read_it(compiled)[0]
        self.assertEqual(reopened_it.patterns[2].rows[42][0].note, 64)
        self.assertIsNone(reopened_it.patterns[3].rows[0][0].note)
        self.assertEqual(reopened_it.patterns[3].rows[6][0].note, NOTE_OFF)
        reopened = gui.State(self.path, headless=True)
        try:
            self.assertEqual(reopened.mod.native_score['plan'], plan)
        finally:
            reopened.close()
        self.st.undo()
        self.assertEqual(self.path.read_bytes(), before)
        self.st.undo(redo=True)
        self.assertEqual(self.path.read_bytes(), saved)
        self.assertEqual(clip, frozen)

    def test_replacement_later_raw_conflict_refuses_without_history_or_source_change(self):
        self.test_cross_measure_later_raw_conflict_refuses_without_history_or_source_change(replace=True)

    def test_cross_measure_later_raw_conflict_refuses_without_history_or_source_change(self, replace=False):
        source = score_song()
        for name in ('c', 'd'):
            source['patterns'][name] = dict(rows=48, data='')
            source['orders'].append(name); source['score']['order_ids'].append(name)
            source['score']['patterns'][name] = dict(row_step=[1, 12], beats=[])
        if replace:
            source['score']['patterns']['c']['beats'] = [dict(id='old', track='guitar', voice=0,
                at=[7, 2], written=dict(value=8, dots=0, tuplet=[1, 1]), notes=[])]
        source['patterns']['d']['data'] = '00: E-5 01 ... ...\n'
        self.st.close(); self.path.write_text(api.to_yaml(source), encoding='utf-8')
        self.st = gui.State(self.path, headless=True)
        clip = self.st.score_clipboard(dict(revision=self.st.text_sha(), selection=[
            dict(occurrence='first', beats=['tail']), dict(occurrence='second', beats=['head'])]))['clipboard']
        before = (self.path.read_bytes(), list(self.st.history), list(self.st.future), copy.deepcopy(clip))
        with self.assertRaisesRegex((SongError, ValueError), 'raw note/release conflicts'):
            self.edit(op='beats_paste', pattern=2, row=42, occurrence='c', across=True, clipboard=clip, replace=replace)
        self.assertEqual((self.path.read_bytes(), list(self.st.history), list(self.st.future), clip), before)

    def test_range_duration_history_native_it_and_atomic_failure(self):
        import numpy as np
        from tests.test_tablature import TestCrossRangeCommands
        from vulturetracker.itreader import read_it
        from vulturetracker.openmpt import LoadedModule
        source,_,groups=TestCrossRangeCommands().fixture();source['score']['ties']=[]
        source['samples'][1]['file']='tone.wav'
        self.st.close();self.path.write_text('# Keep duration comment\n'+api.to_yaml(source),encoding='utf-8')
        self.st=gui.State(self.path,headless=True);self.assertFalse(self.st.error,self.st.error)
        original=self.path.read_bytes()
        request=dict(action='set_duration',track='guitar',voice=0,selection=groups,written=dict(value=8,dots=0,tuplet=[1,1]))
        self.st.score_command(dict(request,revision=self.st.text_sha()))
        saved=self.path.read_bytes();count=len(self.st.history);plan=self.st.mod.native_score['plan']
        self.st.score_command(dict(request,revision=self.st.text_sha()))
        self.assertEqual((self.path.read_bytes(),len(self.st.history)),(saved,count))
        data=api.compile_song(self.path)[0];decoded=read_it(data)[0]
        attacks=[e for e in plan['events'] if e['type']=='note_on' and e['occurrence'] in ('oa','ob')]
        for e in attacks:
            off=next(x for x in plan['events'] if x['type']=='note_off' and x['id']==e['id'])
            self.assertEqual(Fraction(*off['at'])-Fraction(*e['at']),1 if e['note']=='low' else Fraction(1,2))
        for p in decoded.patterns[:2]:
            self.assertEqual([r for r,row in enumerate(p.rows) if row[0].note is not None and row[0].note<120],[0,12,24,36])
            self.assertEqual([r for r,row in enumerate(p.rows) if row[0].note==NOTE_OFF],[6,18,30,42])
        for rate in (44100,48000):
            pair=self.st.prepared_playback(rate,whole=True)
            with LoadedModule(pair['backing_it'],rate,1,plan=pair['plan']) as native, LoadedModule(data,rate,1) as it:
                a=np.frombuffer(native.render(rate,oversample=1,max_seconds=4,floats=True),dtype='<f4')
                b=np.frombuffer(it.render(rate,oversample=1,max_seconds=4,floats=True),dtype='<f4')
            # Independent decoder, no native plan: compare settled on/off windows, away from ramp boundaries.
            for start,end in ((.05,.15),(.32,.42),(1.05,1.15),(1.32,1.42),(2.05,2.15),(2.32,2.42)):
                aa=a[int(start*rate)*2:int(end*rate)*2];bb=b[int(start*rate)*2:int(end*rate)*2]
                energy=float(np.mean(aa*aa));actual=float(np.mean(bb*bb))
                self.assertLess(abs(actual-energy),max(energy*.06,1e-9))
            print(f'range duration {rate}: standalone attacks 0/12/24/36, keyoffs6/18/30/42; settled gate windows agree')
        reopened=gui.State(self.path,headless=True)
        try:self.assertEqual(reopened.mod.native_score['plan'],plan)
        finally:reopened.close()
        self.st.undo();self.assertEqual(self.path.read_bytes(),original)
        self.st.undo(redo=True);self.assertEqual(self.path.read_bytes(),saved)
        # Off-grid tuplets never publish a partly changed range.
        before=self.path.read_bytes(),list(self.st.history),list(self.st.future)
        with self.assertRaises((ValueError,SongError)):
            self.st.score_command(dict(request,written=dict(value=8,dots=0,tuplet=[7,4]),revision=self.st.text_sha()))
        self.assertEqual((self.path.read_bytes(),list(self.st.history),list(self.st.future)),before)
        self.st.undo();self.assertEqual(self.path.read_bytes(),original)
        # A late residual collision rolls back after the first pattern's candidate was shortened.
        from vulturetracker.model import Cell
        cell=self.st.mod.patterns[1].rows[6][0]
        self.st.mod.patterns[1].rows[6][0]=Cell(note=70,instrument=1)
        before=self.path.read_bytes(),list(self.st.history),list(self.st.future)
        try:
            with self.assertRaises((ValueError,SongError)):
                self.st.score_command(dict(request,revision=self.st.text_sha()))
            self.assertEqual((self.path.read_bytes(),list(self.st.history),list(self.st.future)),before)
        finally:self.st.mod.patterns[1].rows[6][0]=cell
        self.assertEqual(self.st.song['patterns'],source['patterns'])
        self.assertEqual(self.st.song['score']['patterns']['C'],source['score']['patterns']['C'])

    def test_range_duration_boundary_rest_tick_playback_it_history_and_refusal(self):
        import numpy as np
        from tests.test_tablature_page import TestTablaturePage
        from vulturetracker.itreader import read_it
        from vulturetracker.openmpt import LoadedModule
        source = TestTablaturePage.duration_boundary_song()
        source['samples'][1]['file'] = 'tone.wav'
        source['patterns']['C']['data'] = '00: ... .. ... X40\n'
        selection = [dict(occurrence='bar3', beats=['rest_copy_visit0_beat3']),
                     dict(occurrence='bar4', beats=['copy_visit1_beat0'])]
        for fit in (False, True):
            for value in (32, 8):
                with self.subTest(fit=fit, value=value):
                    self.st.close()
                    self.path.write_bytes(('# Preserve boundary source comment\n' + api.to_yaml(source)).encode())
                    self.st = gui.State(self.path, headless=True)
                    self.assertFalse(self.st.error, self.st.error)
                    original = self.path.read_bytes()
                    count = len(self.st.history)
                    request = dict(action='set_duration', track='guitar', voice=0, selection=selection,
                                   written=dict(value=value, dots=0, tuplet=[1, 1]),
                                   **({'fit': 'tg_duration'} if fit else {}))
                    result = self.st.score_command(dict(request, revision=self.st.text_sha()))
                    saved = self.path.read_bytes()
                    self.assertEqual(len(self.st.history), count + 1)
                    self.assertEqual(self.st.song['patterns'], source['patterns'])
                    self.assertEqual(self.st.song['score']['patterns']['C'], source['score']['patterns']['C'])
                    self.assertEqual(self.st.song['score']['patterns']['F'], source['score']['patterns']['F'])
                    rest = next(b for b in self.st.song['score']['patterns']['G']['beats'] if b['id'] == selection[0]['beats'][0])
                    self.assertEqual(rest['written']['value'], 16 if value == 8 else 32)
                    self.assertEqual(result['kept_durations'], [dict(occurrence='bar3', beat=rest['id'],
                        written=dict(value=16, dots=0, tuplet=[1, 1]), reason='bar_end')] if value == 8 else [])
                    plan = self.st.mod.native_score['plan']
                    onset = next(e for e in plan['events'] if e['type'] == 'note_on' and e['occurrence'] == 'bar4'
                                 and e['note'] == 'copy_visit1_note0')
                    release = next(e for e in plan['events'] if e['type'] == 'note_off' and e['id'] == onset['id'])
                    self.assertEqual(onset['at'], [12, 1])
                    self.assertEqual(Fraction(*release['at']) - Fraction(*onset['at']), Fraction(4, value))
                    data = api.compile_song(self.path)[0]
                    decoded = read_it(data)[0]
                    self.assertEqual(decoded.patterns[3].rows[0][3].note, 55)
                    if value == 32:
                        # Three ticks from the bar start is row 1 + tick 1 at speed 2, without regridding.
                        self.assertEqual([len(p.rows) for p in decoded.patterns], [48] * 4)
                        off = decoded.patterns[3].rows[1][3]
                        self.assertEqual((off.note, off.effect, off.param), (NOTE_OFF, 19, 0xD1))
                    if value == 32 and not fit:
                        for rate in (44100, 48000):
                            pair = self.st.prepared_playback(rate, whole=True)
                            with LoadedModule(pair['backing_it'], rate, 1, plan=pair['plan']) as native, LoadedModule(data, rate, 1) as it:
                                a = np.frombuffer(native.render(rate, oversample=1, max_seconds=8.3, floats=True), dtype='<f4')
                                b = np.frombuffer(it.render(rate, oversample=1, max_seconds=8.3, floats=True), dtype='<f4')
                            for start, end in ((8.02, 8.05), (8.14, 8.20)):
                                aa = a[int(start * rate) * 2:int(end * rate) * 2]
                                bb = b[int(start * rate) * 2:int(end * rate) * 2]
                                energy, actual = float(np.mean(aa * aa)), float(np.mean(bb * bb))
                                self.assertLess(abs(actual - energy), max(energy * .06, 1e-9))
                            print(f'boundary duration {rate}: standalone bar4 attack 0, keyoff row1 SD1; settled gate windows agree')
                    reopened = gui.State(self.path, headless=True)
                    try:
                        self.assertEqual(reopened.mod.native_score['plan'], plan)
                    finally:
                        reopened.close()
                    self.st.undo()
                    self.assertEqual(self.path.read_bytes(), original)
                    self.st.undo(redo=True)
                    self.assertEqual(self.path.read_bytes(), saved)
                    # A sixty-fourth needs 1.5 ticks here: never round it or publish a partial edit.
                    before = self.path.read_bytes(), list(self.st.history), list(self.st.future)
                    with self.assertRaises((ValueError, SongError)):
                        self.st.score_command(dict(request, written=dict(value=64, dots=0, tuplet=[1, 1]),
                                                   revision=self.st.text_sha()))
                    self.assertEqual((self.path.read_bytes(), list(self.st.history), list(self.st.future)), before)

        # Row-dependent slides cannot be preserved by the exact export subdivision used for pan.
        self.st.close()
        source['patterns']['C2']['data'] = '00: ... .. ... ...\n01: ' + '... .. ... ... | ' * 3 + '... .. ... D01\n'
        self.path.write_bytes(api.to_yaml(source).encode())
        self.st = gui.State(self.path, headless=True)
        self.assertFalse(self.st.error, self.st.error)
        before = self.path.read_bytes(), list(self.st.history), list(self.st.future)
        with self.assertRaisesRegex((ValueError, SongError), 'conflicting effect'):
            self.st.score_command(dict(action='set_duration', track='guitar', voice=0, selection=selection,
                written=dict(value=32, dots=0, tuplet=[1, 1]), revision=self.st.text_sha()))
        self.assertEqual((self.path.read_bytes(), list(self.st.history), list(self.st.future)), before)

    def test_tied_duration_history_native_it_and_atomic_failure(self):
        import numpy as np
        from tests.test_tablature_page import TestTablaturePage
        from vulturetracker.itreader import read_it
        from vulturetracker.openmpt import LoadedModule
        source = TestTablaturePage.tied_duration_song()
        source['samples'][1]['file'] = 'tone.wav'
        source['samples'][1]['loop'] = dict(start=0, end=1024)
        source['patterns']['C']['data'] = '00: ... .. ... X40\n'
        peer = source['score']['patterns']['F']['beats'][-1]
        cases = [('tail shorter', 'tail', 8, 0, [1, 1], Fraction(1, 2)),
                 ('tail tick', 'tail', 32, 0, [1, 1], Fraction(1, 8)),
                 ('tail longer', 'tail', 2, 0, [1, 1], Fraction(2)),
                 ('tail dotted', 'tail', 4, 1, [1, 1], Fraction(3, 2)),
                 ('tail triplet', 'tail', 4, 0, [3, 2], Fraction(2, 3)),
                 ('head shorter', 'head', 8, 0, [1, 1], Fraction(1, 2)),
                 ('range shorter', 'range', 8, 0, [1, 1], Fraction(1, 2))]
        for fit in (False, True):
            for label, target, value, dots, tuplet, duration in cases:
                with self.subTest(case=label, fit=fit):
                    self.st.close()
                    self.path.write_bytes(('# Keep tied source comment\n' + api.to_yaml(source)).encode())
                    self.st = gui.State(self.path, headless=True)
                    self.assertFalse(self.st.error, self.st.error)
                    original, count = self.path.read_bytes(), len(self.st.history)
                    written = dict(value=value, dots=dots, tuplet=tuplet)
                    if target == 'range':
                        request = dict(action='set_duration', track='guitar', voice=0, written=written,
                            selection=[dict(occurrence='bar1', beats=['beat3']),
                                       dict(occurrence='bar2', beats=['beat0', 'lower'])])
                    else:
                        pattern, index, occurrence = ('F', 0, 'bar2') if target == 'tail' else ('C', 3, 'bar1')
                        beat = copy.deepcopy(source['score']['patterns'][pattern]['beats'][index])
                        beat['written'] = written
                        request = dict(action='place', occurrence=occurrence, beat=beat)
                    if fit:
                        request['fit'] = 'tg_duration'
                    result = self.st.score_command(dict(request, revision=self.st.text_sha()))
                    saved = self.path.read_bytes()
                    self.assertEqual(len(self.st.history), count + 1)
                    self.assertEqual(self.st.song['patterns'], source['patterns'])
                    self.assertEqual(next(b for b in self.st.song['score']['patterns']['F']['beats'] if b['id'] == 'lower'), peer)
                    self.assertEqual(self.st.song['score']['patterns']['G'], source['score']['patterns']['G'])
                    self.assertEqual(self.st.song['score']['patterns']['C2'], source['score']['patterns']['C2'])
                    self.assertEqual(self.st.song['score']['ties'], source['score']['ties'] if target == 'tail' else [])
                    events = self.st.mod.native_score['plan']['events']
                    attacks = [e for e in events if e['type'] == 'note_on']
                    self.assertEqual(len(attacks), 15 if target == 'tail' else 16)
                    head = next(e for e in attacks if e['note'] == 'tie_C')
                    release = next(e for e in events if e['type'] == 'note_off' and e['id'] == head['id'])
                    self.assertEqual(head['at'], [3, 1])
                    self.assertEqual(Fraction(*release['at']), 4 + duration if target == 'tail' else 3 + duration)
                    data = api.compile_song(self.path)[0]
                    decoded = read_it(data)[0]
                    self.assertEqual(sum(c.note is not None and c.note < 120 for p in decoded.patterns for row in p.rows for c in row), len(attacks))
                    self.assertEqual(decoded.patterns[0].rows[36][0].note, 64)
                    self.assertEqual(decoded.patterns[1].rows[0][0].note, None if target == 'tail' else 64)
                    if value == 32:
                        off = decoded.patterns[1].rows[1][0]
                        self.assertEqual((off.note, off.effect, off.param), (NOTE_OFF, 19, 0xD1))
                    for rate in (44100, 48000):
                        prepared = self.st.prepared_playback(rate, whole=True)
                        self.assertEqual([{k: v for k, v in e.items() if k != 'frame'} for e in prepared['plan']['events']],
                                         [{k: v for k, v in e.items() if k != 'frame'} for e in events])
                        if label == 'tail shorter' and not fit:
                            with LoadedModule(prepared['backing_it'], rate, 1, plan=prepared['plan']) as native, LoadedModule(data, rate, 1) as it:
                                a = np.frombuffer(native.render(rate, oversample=1, max_seconds=3.2, floats=True), dtype='<f4')
                                b = np.frombuffer(it.render(rate, oversample=1, max_seconds=3.2, floats=True), dtype='<f4')
                            for start, end in ((2.60, 2.64), (2.70, 2.74), (3.08, 3.12)):
                                aa, bb = a[int(start * rate) * 2:int(end * rate) * 2], b[int(start * rate) * 2:int(end * rate) * 2]
                                energy, actual = float(np.mean(aa * aa)), float(np.mean(bb * bb))
                                self.assertLess(abs(actual - energy), max(energy * .06, 1e-9))
                            print(f'tied duration {rate}: one sustained attack across bar; native/standalone gate windows agree')
                    reopened = gui.State(self.path, headless=True)
                    try:
                        self.assertEqual(reopened.mod.native_score['plan'], self.st.mod.native_score['plan'])
                    finally:
                        reopened.close()
                    self.st.undo()
                    self.assertEqual(self.path.read_bytes(), original)
                    self.st.undo(redo=True)
                    self.assertEqual(self.path.read_bytes(), saved)
                    # Unsupported sub-tick sounding endpoints must not partially change a tie or history.
                    invalid = copy.deepcopy(next(b for b in self.st.song['score']['patterns']['F']['beats'] if b['id'] == 'beat0'))
                    invalid['written'] = dict(value=64, dots=0, tuplet=[1, 1])
                    before = self.path.read_bytes(), list(self.st.history), list(self.st.future)
                    with self.assertRaises((ValueError, SongError)):
                        self.st.score_command(dict(action='place', occurrence='bar2', beat=invalid, revision=self.st.text_sha()))
                    self.assertEqual((self.path.read_bytes(), list(self.st.history), list(self.st.future)), before)

    def test_tied_duration_fit_moves_continuations_without_reattack(self):
        from tests.test_tablature_page import TestTablaturePage
        from vulturetracker.itreader import read_it
        source = TestTablaturePage.four_bar_song()
        source['samples'][1]['file'] = 'tone.wav'
        beats = source['score']['patterns']['C']['beats']
        for i in range(3):
            beats[i]['notes'] = [dict(id=f'sustain{i}', pitch=64, string=1, fret=0, velocity=95)]
        beats[3]['notes'] = []
        source['score']['ties'] = [dict(**{'from': dict(occurrence='bar1', note=f'sustain{i}')},
                                       to=dict(occurrence='bar1', note=f'sustain{i + 1}')) for i in range(2)]
        self.st.close()
        self.path.write_bytes(('# Keep Fit source comment\n' + api.to_yaml(source)).encode())
        self.st = gui.State(self.path, headless=True)
        self.assertFalse(self.st.error, self.st.error)
        original = self.path.read_bytes()
        requested = copy.deepcopy(beats[0])
        requested['written']['value'] = 2
        result = self.st.score_command(dict(action='place', occurrence='bar1', beat=requested,
                                            fit='tg_duration', revision=self.st.text_sha()))
        self.assertEqual(result['removed_ties'], [])
        actual = {b['id']: b for b in self.st.song['score']['patterns']['C']['beats']}
        self.assertEqual([actual[f'beat{i}']['at'] for i in range(3)], [[0, 1], [2, 1], [3, 1]])
        self.assertEqual(self.st.song['score']['ties'], source['score']['ties'])
        events = self.st.mod.native_score['plan']['events']
        attacks = [e for e in events if e['type'] == 'note_on' and e['occurrence'] == 'bar1']
        self.assertEqual(len(attacks), 1)
        release = next(e for e in events if e['type'] == 'note_off' and e['id'] == attacks[0]['id'])
        self.assertEqual(release['at'], [4, 1])
        decoded = read_it(api.compile_song(self.path)[0])[0]
        self.assertEqual(sum(c.note is not None and c.note < 120 for row in decoded.patterns[0].rows for c in row), 1)
        self.assertEqual(len(self.st.history), 1)
        self.st.undo()
        self.assertEqual(self.path.read_bytes(), original)

    def test_everyday_rhythm_sequence_selection_history_playback_and_it(self):
        from tests.test_tablature_page import TestTablaturePage
        from vulturetracker.itreader import read_it
        source = TestTablaturePage.everyday_rhythm_song()
        source['samples'][1]['file'] = 'tone.wav'
        peer = source['score']['patterns']['C']['beats'][-1]
        for fit in (False, True):
            with self.subTest(fit=fit):
                self.st.close()
                self.path.write_bytes(('# Keep rhythm source comment\n' + api.to_yaml(source)).encode())
                self.st = gui.State(self.path, headless=True)
                self.assertFalse(self.st.error, self.st.error)
                original = self.path.read_bytes()
                selection = [dict(occurrence=occurrence, beats=[b['id'] for b in source['score']['patterns'][pattern]['beats']])
                             for occurrence, pattern in (('bar1', 'C'), ('bar2', 'F'))]
                checkpoints = []
                for value, dots, tuplet, duration, selected_count in (
                        (4, 0, [1, 1], Fraction(1), 9), (8, 0, [1, 1], Fraction(1, 2), 17),
                        (8, 1, [1, 1], Fraction(3, 4), None), (8, 1, [3, 2], Fraction(1, 2), None)):
                    request = dict(action='set_duration', track='guitar', voice=0, selection=selection,
                                   written=dict(value=value, dots=dots, tuplet=tuplet))
                    if fit:
                        request['fit'] = 'tg_duration'
                    count = len(self.st.history)
                    result = self.st.score_command(dict(request, revision=self.st.text_sha()))
                    self.assertEqual(len(self.st.history), count + 1)
                    selection = result['selection']['range']
                    if selected_count:
                        self.assertEqual(sum(len(group['beats']) for group in selection), selected_count)
                    if value == 4:
                        self.assertEqual(len(result['consumed_rests']), 8)
                    self.assertEqual(next(b for b in self.st.song['score']['patterns']['C']['beats'] if b['id'] == 'lower'), peer)
                    self.assertEqual(self.st.song['patterns'], source['patterns'])
                    for name in ('G', 'C2'):
                        self.assertEqual(self.st.song['score']['patterns'][name], source['score']['patterns'][name])
                    events = self.st.mod.native_score['plan']['events']
                    attacks = [e for e in events if e['type'] == 'note_on']
                    self.assertEqual(len(attacks), 16)
                    for onset in attacks:
                        if onset['occurrence'] not in ('bar1', 'bar2') or onset['voice'] != 0:
                            continue
                        release = next(e for e in events if e['type'] == 'note_off' and e['id'] == onset['id'])
                        self.assertEqual(Fraction(*release['at']) - Fraction(*onset['at']), duration)
                    decoded = read_it(api.compile_song(self.path)[0])[0]
                    self.assertEqual(sum(c.note is not None and c.note < 120 for p in decoded.patterns for row in p.rows for c in row), 16)
                    clip = self.st.score_clipboard(dict(selection=selection, revision=self.st.text_sha()))['clipboard']
                    self.assertEqual(sum(len(b['notes']) for b in clip['beats']), 9)
                    checkpoints.append(self.path.read_bytes())
                result = self.st.score_command(dict(action='set_expression', track='guitar', voice=0,
                    selection=selection, changes=dict(velocity=63), revision=self.st.text_sha()))
                selection = result['selection']['range']
                clip = self.st.score_clipboard(dict(selection=selection, revision=self.st.text_sha()))['clipboard']
                self.assertTrue(all(n['velocity'] == (63 if b.get('voice', 0) == 0 else 95)
                                    for b in clip['beats'] for n in b['notes']))
                self.assertEqual(next(b for b in self.st.song['score']['patterns']['C']['beats'] if b['id'] == 'lower'), peer)
                plan = self.st.mod.native_score['plan']
                for rate in (44100, 48000):
                    events = self.st.prepared_playback(rate, whole=True)['plan']['events']
                    self.assertEqual([(e['type'], e['id'], e['at']) for e in events],
                                     [(e['type'], e['id'], e['at']) for e in plan['events']])
                reopened = gui.State(self.path, headless=True)
                try:
                    self.assertEqual(reopened.mod.native_score['plan'], plan)
                finally:
                    reopened.close()
                saved = self.path.read_bytes()
                self.st.undo()
                self.assertEqual(self.path.read_bytes(), checkpoints[-1])
                self.st.undo(redo=True)
                self.assertEqual(self.path.read_bytes(), saved)
                for expected in [*reversed(checkpoints), original]:
                    self.st.undo()
                    self.assertEqual(self.path.read_bytes(), expected)
                # A full bar and its final note cannot fit the requested growth; both modes preserve history/redo.
                for occurrence, beat, reason in (('bar4', 'beat0', 'no_space'), ('bar4', 'beat3', 'bar_end')):
                    for bounded_fit in (False, True):
                        request = dict(action='set_duration', occurrence=occurrence, track='guitar', voice=0,
                            beats=[beat], written=dict(value=2, dots=0, tuplet=[1, 1]))
                        if bounded_fit:
                            request['fit'] = 'tg_duration'
                        before = self.path.read_bytes(), list(self.st.history), list(self.st.future)
                        result = self.st.score_command(dict(request, revision=self.st.text_sha()))
                        self.assertEqual(result['kept_durations'][0]['reason'], reason)
                        self.assertEqual((self.path.read_bytes(), list(self.st.history), list(self.st.future)), before)

    def test_everyday_rhythm_late_raw_collision_stays_atomic(self):
        from tests.test_tablature_page import TestTablaturePage
        source = TestTablaturePage.everyday_rhythm_song()
        source['samples'][1]['file'] = 'tone.wav'
        # This raw attack lies in the original rest after bar2's first note, but inside its requested longer span.
        source['patterns']['F']['data'] = ''.join(f'{row:02d}: ... .. ... ...\n' for row in range(9)) + \
            '09: ' + '... .. ... ... | ' * 3 + 'C-5 01 ... ...\n'
        self.st.close()
        self.path.write_bytes(('# Preserve collision source\n' + api.to_yaml(source)).encode())
        self.st = gui.State(self.path, headless=True)
        self.assertFalse(self.st.error, self.st.error)
        selection = [dict(occurrence=occurrence, beats=[b['id'] for b in source['score']['patterns'][pattern]['beats']])
                     for occurrence, pattern in (('bar1', 'C'), ('bar2', 'F'))]
        for fit in (False, True):
            request = dict(action='set_duration', track='guitar', voice=0, selection=selection,
                written=dict(value=4, dots=0, tuplet=[1, 1]))
            if fit:
                request['fit'] = 'tg_duration'
            before = self.path.read_bytes(), list(self.st.history), list(self.st.future)
            with self.assertRaisesRegex((ValueError, SongError), 'raw|residual'):
                self.st.score_command(dict(request, revision=self.st.text_sha()))
            self.assertEqual((self.path.read_bytes(), list(self.st.history), list(self.st.future)), before)

    def test_everyday_rhythm_automatic_free_gap_peer_history_and_it(self):
        from tests.test_tablature_page import TestTablaturePage
        from vulturetracker.itreader import read_it
        source = TestTablaturePage.everyday_rhythm_song()
        source['samples'][1]['file'] = 'tone.wav'
        self.st.close()
        self.path.write_bytes(('# Keep implicit gap source\n' + api.to_yaml(source)).encode())
        self.st = gui.State(self.path, headless=True)
        self.assertFalse(self.st.error, self.st.error)
        original = self.path.read_bytes()
        result = self.st.score_command(dict(action='set_duration', occurrence='bar3', track='guitar', voice=0,
            beats=['beat0'], written=dict(value=4, dots=2, tuplet=[1, 1]), fit='tg_duration', revision=self.st.text_sha()))
        self.assertEqual(result['selection']['beats'], ['beat0'])
        self.assertTrue(result['automatic_free'])
        self.assertEqual(self.st.song['patterns'], source['patterns'])
        for pattern in ('C', 'F', 'C2'):
            self.assertEqual(self.st.song['score']['patterns'][pattern], source['score']['patterns'][pattern])
        beats = {b['id']: b for b in self.st.song['score']['patterns']['G']['beats']}
        self.assertEqual(beats['peer-rest'], source['score']['patterns']['G']['beats'][-1])
        self.assertEqual(beats['beat1']['at'], [7, 4])
        self.assertEqual(beats['beat1']['written'], dict(value=4, dots=0, tuplet=[1, 1]))
        self.assertEqual(beats['beat3']['at'], [11, 4])
        self.assertEqual(len(self.st.history), 1)
        events = self.st.mod.native_score['plan']['events']
        attacks = [e for e in events if e['type'] == 'note_on' and e['occurrence'] == 'bar3']
        self.assertEqual([(e['at'], e['pitch']) for e in attacks], [([8, 1], 55), ([39, 4], 59), ([43, 4], 59)])
        self.assertEqual([next(e['at'] for e in events if e['type'] == 'note_off' and e['id'] == onset['id'])
                          for onset in attacks], [[39, 4], [43, 4], [47, 4]])
        decoded = read_it(api.compile_song(self.path)[0])[0]
        actual = [(r, ch, c.note) for r, row in enumerate(decoded.patterns[2].rows) for ch, c in enumerate(row)
                  if c.note is not None and c.note < 120]
        self.assertEqual(actual, [(0, 2, 55), (21, 1, 59), (33, 1, 59)])
        self.assertEqual(decoded.patterns[2].rows[45][1].note, NOTE_OFF)
        saved = self.path.read_bytes()
        reopened = gui.State(self.path, headless=True)
        try:
            self.assertEqual(reopened.mod.native_score['plan'], self.st.mod.native_score['plan'])
        finally:
            reopened.close()
        self.st.undo()
        self.assertEqual(self.path.read_bytes(), original)
        self.st.undo(redo=True)
        self.assertEqual(self.path.read_bytes(), saved)

    def test_range_expression_history_native_it_and_atomic_failure(self):
        from tests.test_tablature import TestCrossRangeCommands
        from vulturetracker.itreader import read_it
        source,_,groups=TestCrossRangeCommands().fixture()
        source['samples'][1]['file']='tone.wav'
        source['score']['ties']=[]
        self.st.close();self.path.write_text('# Keep comment\n'+api.to_yaml(source),encoding='utf-8')
        self.st=gui.State(self.path,headless=True);self.assertFalse(self.st.error,self.st.error)
        original=self.path.read_bytes()
        request=dict(action='set_expression',track='guitar',selection=groups)
        peer_before=[e for e in self.st.mod.native_score['plan']['events'] if e.get('id')=='oa/low']
        peer_cell=read_it(api.compile_song(self.path)[0])[0].patterns[0].rows[0][1]
        self.st.score_command(dict(request,changes=dict(velocity=63,palm_mute=True,ghost=True),revision=self.st.text_sha()))
        saved=self.path.read_bytes();history=len(self.st.history)
        self.assertEqual(self.st.song['patterns'],source['patterns'])
        self.assertEqual(self.st.song['score']['patterns']['C'],source['score']['patterns']['C'])
        plan=self.st.mod.native_score['plan'];events=plan['events']
        attacks=[e for e in events if e['type']=='note_on' and e['occurrence'] in ('oa','ob')]
        self.assertEqual([e['velocity'] for e in attacks if e['id']!='oa/low'],[63-16]*8)
        self.assertEqual([e for e in events if e.get('id')=='oa/low'],peer_before)
        module=read_it(api.compile_song(self.path)[0])[0]
        cells=[c for p in module.patterns[:2] for row in p.rows for c in row if c.note is not None and c.note<120]
        self.assertEqual(len(cells),9)
        self.assertEqual({c.volcmd for p in module.patterns[:2] for row in p.rows for c in row[:1] if c.note is not None and c.note<120},{round(47*64/127)})
        self.assertEqual(module.patterns[0].rows[0][1],peer_cell)
        for e in (e for e in attacks if e['id']!='oa/low'):
            off=next(x for x in events if x['type']=='note_off' and x['id']==e['id'])
            self.assertLess(Fraction(*off['at'])-Fraction(*e['at']),1)
        self.st.score_command(dict(request,changes=dict(velocity=63,palm_mute=True,ghost=True),revision=self.st.text_sha()))
        self.assertEqual(len(self.st.history),history);self.assertEqual(self.path.read_bytes(),saved)
        before=self.path.read_bytes(),list(self.st.history),list(self.st.future)
        with self.assertRaisesRegex((ValueError,SongError),'velocity'):
            self.st.score_command(dict(request,changes=dict(velocity=None),revision=self.st.text_sha()))
        self.assertEqual((self.path.read_bytes(),list(self.st.history),list(self.st.future)),before)
        reopened=gui.State(self.path,headless=True)
        try:self.assertEqual(reopened.mod.native_score['plan'],plan)
        finally:reopened.close()
        self.st.undo();self.assertEqual(self.path.read_bytes(),original)
        self.st.undo(redo=True);self.assertEqual(self.path.read_bytes(),saved)
        self.st.undo();self.assertEqual(self.path.read_bytes(),original)
        # A missing velocity in the later pattern makes a whole-range dynamic fail, not default to95.
        source['score']['patterns']['B']['beats'][2]['notes'][0].pop('velocity')
        source['score']['patterns']['B']['beats'][2]['notes'][0].pop('accent')
        self.st.close();self.path.write_text(api.to_yaml(source),encoding='utf-8');self.st=gui.State(self.path,headless=True)
        before=self.path.read_bytes(),list(self.st.history)
        with self.assertRaisesRegex((ValueError,SongError),'velocity'):
            self.st.score_command(dict(request,changes=dict(heavy_accent=True),revision=self.st.text_sha()))
        self.assertEqual((self.path.read_bytes(),list(self.st.history)),before)

        tied,_,groups=TestCrossRangeCommands().fixture();tied['samples'][1]['file']='tone.wav'
        self.st.close();self.path.write_text(api.to_yaml(tied),encoding='utf-8');self.st=gui.State(self.path,headless=True)
        self.st.score_command(dict(request,changes=dict(velocity=47,staccato=True),revision=self.st.text_sha()))
        self.assertEqual(self.st.song['score']['ties'],tied['score']['ties'])
        self.assertEqual(len([e for e in self.st.mod.native_score['plan']['events']
                             if e['type']=='note_on' and e['occurrence'] in ('oa','ob')]),8)
        self.assertEqual(len([c for p in read_it(api.compile_song(self.path)[0])[0].patterns[:2]
                             for row in p.rows for c in row if c.note is not None and c.note<120]),8)

    def test_range_pitch_history_audio_it_and_reopen(self):
        from tests.test_tablature import TestCrossRangeCommands
        from vulturetracker.itreader import read_it
        from vulturetracker.openmpt import LoadedModule
        source, _, groups = TestCrossRangeCommands().fixture()
        source['score']['patterns']['A']['beats'][-1]['notes'][0].update(string=3,fret=4)
        source['samples'][1]['file'] = 'tone.wav'
        self.st.close(); self.path.write_text('# Keep comment\n'+api.to_yaml(source),encoding='utf-8')
        self.st=gui.State(self.path,headless=True)
        self.assertFalse(self.st.error,self.st.error)
        original=self.path.read_bytes()
        request=dict(action='transpose',scope='selection',track='guitar',selection=groups,semitones=2)
        self.st.score_command(dict(request,revision=self.st.text_sha()))
        pitched=self.path.read_bytes()
        plan=copy.deepcopy(self.st.mod.native_score['plan'])
        standalone=api.compile_song(self.path)[0]
        pairs={rate:self.st.prepared_playback(rate,whole=True) for rate in (44100,48000)}
        module=read_it(standalone)[0]
        attacks=[(pi,ri,ci,c.note) for pi,p in enumerate(module.patterns) for ri,row in enumerate(p.rows)
                 for ci,c in enumerate(row) if c.note is not None and c.note<120]
        self.assertEqual(len(attacks),16)
        self.assertEqual([p for pi,ri,ci,p in attacks if pi==0],[66,61,67,68,66])
        self.st.score_command(dict(action='shift_strings',track='guitar',selection=groups,direction=1,revision=self.st.text_sha()))
        shifted=self.path.read_bytes()
        # Existing gain/pitch/timing and owned audio channels are byte-for-byte unchanged.
        self.assertEqual(self.st.mod.native_score['plan']['events'],plan['events'])
        self.assertEqual(api.compile_song(self.path)[0],standalone)
        for rate in (44100,48000):
            prepared=pairs[rate]
            actual=self.st.prepared_playback(rate,whole=True)
            with LoadedModule(prepared['backing_it'],rate,1,plan=prepared['plan']) as before, LoadedModule(actual['backing_it'],rate,1,plan=actual['plan']) as after:
                self.assertEqual(before.render(rate,oversample=1,max_seconds=8),after.render(rate,oversample=1,max_seconds=8))
            # Standalone decoder intentionally receives no native plan.
            with LoadedModule(standalone,rate,1) as decoded:
                self.assertGreater(len(decoded.render(rate,oversample=1,max_seconds=8)),rate)
        reopened=gui.State(self.path,headless=True)
        try:self.assertEqual(reopened.mod.native_score['plan']['events'],plan['events'])
        finally:reopened.close()
        self.st.undo();self.assertEqual(self.path.read_bytes(),pitched)
        self.st.undo(redo=True);self.assertEqual(self.path.read_bytes(),shifted)
        self.st.undo();self.st.undo();self.assertEqual(self.path.read_bytes(),original)
        source['patterns']['B']['approved']=True
        self.st.close();self.path.write_text(api.to_yaml(source),encoding='utf-8');self.st=gui.State(self.path,headless=True)
        before=self.path.read_bytes(),list(self.st.history),list(self.st.future)
        with self.assertRaisesRegex(ValueError,'approved'):self.st.score_command(dict(request,revision=self.st.text_sha()))
        self.assertEqual((self.path.read_bytes(),list(self.st.history),list(self.st.future)),before)

    def test_semitone_range_history_pattern_and_standalone_it(self):
        from tests.test_tablature import TestCrossRangeCommands
        from vulturetracker.itreader import read_it
        source,_,groups=TestCrossRangeCommands().fixture()
        source['samples'][1]['file']='tone.wav'
        self.st.close();self.path.write_text('# Keep comment\n'+api.to_yaml(source),encoding='utf-8')
        self.st=gui.State(self.path,headless=True);self.assertFalse(self.st.error,self.st.error)
        original=self.path.read_bytes()
        request=dict(action='shift_pitch',track='guitar',voice=0,selection=groups,direction=1)
        self.st.score_command(dict(request,revision=self.st.text_sha()));saved=self.path.read_bytes()
        standalone=api.compile_song(self.path)[0];module=read_it(standalone)[0]
        self.assertEqual([c.note for row in module.patterns[0].rows for c in row if c.note is not None and c.note<120],
                         [65,59,66,67,65])
        self.assertEqual(self.st.song['score']['patterns']['A']['beats'][-1],source['score']['patterns']['A']['beats'][-1])
        plan=copy.deepcopy(self.st.mod.native_score['plan'])
        reopened=gui.State(self.path,headless=True)
        try:self.assertEqual(reopened.mod.native_score['plan'],plan)
        finally:reopened.close()
        self.st.undo();self.assertEqual(self.path.read_bytes(),original)
        self.st.undo(redo=True);self.assertEqual(self.path.read_bytes(),saved)
        self.st.undo();self.assertEqual(self.path.read_bytes(),original)
        before=self.path.read_bytes(),list(self.st.history),list(self.st.future)
        with self.assertRaisesRegex(ValueError,'fret range'):
            self.st.score_command(dict(request,direction=-1,revision=self.st.text_sha()))
        self.assertEqual((self.path.read_bytes(),list(self.st.history),list(self.st.future)),before)

    def test_cohort_annotation_transfer_history_it_and_unsafe_stroke(self):
        from tests.test_advanced_rhythm import cohort_rest_song
        from vulturetracker.itreader import read_it
        source=cohort_rest_song(True);source['samples'][1]['file']='tone.wav'
        next(b for b in source['score']['patterns']['A']['beats'] if b['id']=='c').update(
            text='Keep this text',stroke=dict(direction='up',value=4),pick_stroke='up',
            chord=dict(name='Em',first_fret=1,frets=[0,0,0,2,2,0]))
        self.st.close();self.path.write_text('# Preserve transferred metadata\n'+api.to_yaml(source),encoding='utf-8')
        self.st=gui.State(self.path,headless=True);self.assertFalse(self.st.error,self.st.error)
        original=self.path.read_bytes();request=dict(action='cut',occurrence='oa',track='guitar',voice=0,beats=['b'])
        self.st.score_command(dict(request,revision=self.st.text_sha()));saved=self.path.read_bytes()
        events={e['id']:e for e in self.st.mod.native_score['plan']['events'] if e['type']=='note_on'}
        self.assertEqual(Fraction(*events['oa/pn1']['at'])-Fraction(*events['oa/c-note']['at']),Fraction(1,8))
        standalone=read_it(api.compile_song(self.path)[0])[0]
        self.assertEqual(sum(c.note is not None and c.note<120 for row in standalone.patterns[0].rows for c in row),4)
        self.st.undo();self.assertEqual(self.path.read_bytes(),original)
        self.st.undo(redo=True);self.assertEqual(self.path.read_bytes(),saved)
        self.st.undo();self.assertEqual(self.path.read_bytes(),original)
        b=copy.deepcopy(next(b for b in self.st.song['score']['patterns']['A']['beats'] if b['id']=='c'))
        b['stroke']['value']=16
        self.st.score_edit(dict(op='beat_set',pattern='A',beat=b,revision=self.st.text_sha()))
        before=self.path.read_bytes(),list(self.st.history),list(self.st.future)
        with self.assertRaisesRegex(SongError,'stroke attack.*IT tick grid'):
            self.st.score_command(dict(request,revision=self.st.text_sha()))
        self.assertEqual((self.path.read_bytes(),list(self.st.history),list(self.st.future)),before)

    def test_annotated_fit_exact_history_pattern_it_and_atomic_rest_guard(self):
        from tests.test_advanced_rhythm import cohort_rest_song
        from vulturetracker.itreader import read_it
        source=cohort_rest_song();source['samples'][1]['file']='tone.wav'
        next(b for b in source['score']['patterns']['A']['beats'] if b['id']=='b').update(
            text='Follow the phrase',stroke=dict(direction='up',value=4),pick_stroke='up',
            chord=dict(name='Em',first_fret=1,frets=[0,0,0,2,2,0]))
        self.st.close();self.path.write_text('# Annotated Fit\n'+api.to_yaml(source),encoding='utf-8')
        self.st=gui.State(self.path,headless=True);self.assertFalse(self.st.error,self.st.error)
        original=self.path.read_bytes()
        request=dict(action='set_duration',occurrence='oa',track='guitar',voice=0,beats=['a'],fit='tg_duration')
        for value,dots,row in ((2,0,24),(4,1,18)):
            self.st.score_command(dict(request,written=dict(value=value,dots=dots,tuplet=[1,1]),revision=self.st.text_sha()))
            saved=self.path.read_bytes()
            standalone=read_it(api.compile_song(self.path)[0])[0]
            self.assertEqual(standalone.patterns[0].rows[row][0].note,66)
            position=next(p for p in self.st.pattern_rows(0,'oa')['score_positions'] if p.get('note')=='b-note')
            self.assertEqual(Fraction(*position['local_at'])*12,row);self.assertEqual(position['pitch'],66)
            self.st.undo();self.assertEqual(self.path.read_bytes(),original)
            self.st.undo(redo=True);self.assertEqual(self.path.read_bytes(),saved)
            self.st.undo();self.assertEqual(self.path.read_bytes(),original)
        rest=copy.deepcopy(next(b for b in self.st.song['score']['patterns']['A']['beats'] if b['id']=='r'))
        rest['text']='Do not discard'
        self.st.score_edit(dict(op='beat_set',pattern='A',beat=rest,revision=self.st.text_sha()))
        before=self.path.read_bytes(),list(self.st.history),list(self.st.future)
        with self.assertRaisesRegex(ValueError,'annotated cohort'):
            self.st.score_command(dict(request,written=dict(value=2),revision=self.st.text_sha()))
        self.assertEqual((self.path.read_bytes(),list(self.st.history),list(self.st.future)),before)

    def test_cohort_rest_fit_history_pattern_and_it(self):
        from tests.test_advanced_rhythm import cohort_rest_song
        from vulturetracker.itreader import read_it
        source=cohort_rest_song();source['samples'][1]['file']='tone.wav'
        self.st.close();self.path.write_text('# Preserve voice moves\n'+api.to_yaml(source),encoding='utf-8')
        self.st=gui.State(self.path,headless=True);self.assertFalse(self.st.error,self.st.error)
        original=self.path.read_bytes()
        cases=[(dict(action='insert_rest',at=[1,1],rest_id='inserted'),[(0,59),(0,64),(12,60),(24,66),(36,68)]),
               (dict(action='set_duration',beats=['a'],fit='tg_duration',written=dict(value=4,dots=1,tuplet=[1,1])),
                [(0,59),(0,64),(12,60),(18,66),(30,68)])]
        for request,expected in cases:
            self.st.score_command(dict(request,occurrence='oa',track='guitar',voice=0,revision=self.st.text_sha()))
            saved=self.path.read_bytes();standalone=read_it(api.compile_song(self.path)[0])[0]
            attacks=sorted((i,c.note) for i,row in enumerate(standalone.patterns[0].rows) for c in row
                           if c.note is not None and c.note<120)
            self.assertEqual(attacks,expected)
            positions=sorted((int(Fraction(*p['local_at'])*12),p['pitch'])
                for p in self.st.pattern_rows(0,'oa')['score_positions'] if p['kind']=='note')
            self.assertEqual(positions,expected)
            self.st.undo();self.assertEqual(self.path.read_bytes(),original)
            self.st.undo(redo=True);self.assertEqual(self.path.read_bytes(),saved)
            self.st.undo();self.assertEqual(self.path.read_bytes(),original)
        b=copy.deepcopy(next(b for b in self.st.song['score']['patterns']['A']['beats'] if b['id']=='b'));b['notes']=[]
        self.st.score_edit(dict(op='beat_set',pattern='A',beat=b,revision=self.st.text_sha()));rested=self.path.read_bytes()
        self.st.score_command(dict(action='cut',occurrence='oa',track='guitar',voice=0,beats=['b'],revision=self.st.text_sha()))
        cut=self.path.read_bytes();standalone=read_it(api.compile_song(self.path)[0])[0]
        self.assertEqual(sorted((i,c.note) for i,row in enumerate(standalone.patterns[0].rows) for c in row
                         if c.note is not None and c.note<120),[(0,59),(0,64),(12,60),(12,68)])
        for saved in (rested,original):self.st.undo();self.assertEqual(self.path.read_bytes(),saved)
        for saved in (rested,cut):self.st.undo(redo=True);self.assertEqual(self.path.read_bytes(),saved)

    def test_coincident_groups_reopen_history_pattern_playback_it(self):
        from tests.test_advanced_rhythm import free_cohort_song
        from vulturetracker.itreader import read_it
        source=free_cohort_song();source['samples'][1]['file']='tone.wav'
        self.st.close();self.path.write_text('# Keep cohort history\n'+api.to_yaml(source),encoding='utf-8')
        self.st=gui.State(self.path,headless=True);self.assertFalse(self.st.error,self.st.error)
        original=self.path.read_bytes()
        edit=dict(action='set_duration',occurrence='oa',track='guitar',voice=1,beats=['peer'],free=True,
                  written=dict(value=4,dots=0,tuplet=[1,1]))
        self.st.score_command(dict(edit,revision=self.st.text_sha()));aligned=self.path.read_bytes()
        self.st.close();self.st=gui.State(self.path,headless=True)
        self.assertFalse(self.st.error,self.st.error)
        self.st.score_command(dict(edit,voice=0,beats=['a'],written=dict(value=8,dots=0,tuplet=[1,1]),
                                  revision=self.st.text_sha()));saved=self.path.read_bytes()
        positions={p['note']:p['local_at'] for p in self.st.pattern_rows(0,'oa')['score_positions'] if p['kind']=='note'}
        self.assertEqual({n:positions[n] for n in ('a-note','b-note','c-note','pn0','pn1')},
                         {'a-note':[0,1],'b-note':[1,2],'c-note':[3,2],'pn0':[0,1],'pn1':[1,1]})
        standalone=read_it(api.compile_song(self.path)[0])[0]
        attacks=sorted((i,c.note) for i,row in enumerate(standalone.patterns[0].rows) for c in row
                       if c.note is not None and c.note<120)
        self.assertEqual(attacks,[(0,59),(0,64),(6,66),(12,60),(18,68)])
        self.assertEqual(sorted(Fraction(*e['at']) for e in self.st.mod.native_score['plan']['events']
                                if e['type']=='note_on' and e['id'].startswith('oa/')),
                         [Fraction(0),Fraction(0),Fraction(1,2),Fraction(1),Fraction(3,2)])
        self.st.undo();self.assertEqual(self.path.read_bytes(),aligned)
        self.st.undo();self.assertEqual(self.path.read_bytes(),original)
        self.st.undo(redo=True);self.assertEqual(self.path.read_bytes(),aligned)
        self.st.undo(redo=True);self.assertEqual(self.path.read_bytes(),saved)
        before=self.path.read_bytes(),list(self.st.history),list(self.st.future)
        with patch.object(api,'compile_song',side_effect=ValueError('cohort atomic refusal')):
            with self.assertRaisesRegex(ValueError,'cohort atomic refusal'):
                self.st.score_command(dict(edit,written=dict(value=2),revision=self.st.text_sha()))
        self.assertEqual((self.path.read_bytes(),list(self.st.history),list(self.st.future)),before)

    def test_free_duration_repack_history_pattern_it_and_compile_failure(self):
        from tests.test_tablature import TestPlaceFitCommand
        from vulturetracker.itreader import read_it
        source,_=TestPlaceFitCommand().fixture();source['samples'][1]['file']='tone.wav'
        self.st.close();self.path.write_text('# Preserve Free duration comment\n'+api.to_yaml(source),encoding='utf-8')
        self.st=gui.State(self.path,headless=True);self.assertFalse(self.st.error,self.st.error)
        original=self.path.read_bytes()
        edit=dict(action='set_duration',occurrence='oa',track='guitar',voice=0,beats=['a'],free=True,
                  written=dict(value=8,dots=0,tuplet=[1,1]))
        self.st.score_command(dict(edit,revision=self.st.text_sha()));saved=self.path.read_bytes()
        self.assertEqual(len(self.st.history),1)
        positions={p['note']:p['local_at'] for p in self.st.pattern_rows(0,'oa')['score_positions'] if p['kind']=='note'}
        self.assertEqual({n:positions[n] for n in ('a-note','b-note','c-note')},
                         {'a-note':[0,1],'b-note':[1,2],'c-note':[5,2]})
        standalone=read_it(api.compile_song(self.path)[0])[0]
        attacks=[(i,c.note) for i,row in enumerate(standalone.patterns[0].rows) for c in row if c.note is not None and c.note<120]
        self.assertEqual(attacks,[(0,64),(6,66),(30,68)])
        self.assertEqual([e['at'] for e in self.st.mod.native_score['plan']['events']
                          if e['type']=='note_on' and e['id'].startswith('oa/')],[[0,1],[1,2],[5,2]])
        self.st.undo();self.assertEqual(self.path.read_bytes(),original)
        self.st.undo(redo=True);self.assertEqual(self.path.read_bytes(),saved)
        before=self.path.read_bytes(),list(self.st.history),list(self.st.future)
        with patch.object(api,'compile_song',side_effect=ValueError('strict IT Free refusal')):
            with self.assertRaisesRegex(ValueError,'strict IT Free refusal'):
                self.st.score_command(dict(edit,written=dict(value=2),revision=self.st.text_sha()))
        self.assertEqual((self.path.read_bytes(),list(self.st.history),list(self.st.future)),before)

    def test_matrix_free_growth_exact_history_pattern_and_standalone_it(self):
        from tests.test_tablature import TestMatrixEntry,beat
        from vulturetracker.itreader import read_it
        source,_=TestMatrixEntry().fixture();source['samples'][1]['file']='tone.wav'
        source['score']['patterns']['A']['beats']=[beat('tail',[3,1],[])]
        self.st.close();self.path.write_text('# Keep free Matrix comment\n'+api.to_yaml(source),encoding='utf-8')
        self.st=gui.State(self.path,headless=True);self.assertFalse(self.st.error,self.st.error)
        original=self.path.read_bytes()
        result=self.st.score_command(dict(action='matrix_entry',occurrence='oa',track='guitar',voice=0,
            at=[37,10],pitch=67,written=dict(value=2),free=True,fit=True,revision=self.st.text_sha()))
        self.assertEqual(self.st.song['patterns']['A']['rows'],60)
        self.assertEqual(result['selection']['at'],[3,1]);self.assertEqual(result['audition'][0]['pitch'],67)
        positions=self.st.pattern_rows(0,'oa')['score_positions']
        self.assertEqual([p['local_at'] for p in positions if p['kind']=='note'],[[3,1]])
        standalone=read_it(api.compile_song(self.path)[0])[0]
        self.assertEqual(sum(c.note==67 for p in standalone.patterns for row in p.rows for c in row),1)
        self.assertEqual(len([e for e in self.st.mod.native_score['plan']['events'] if e['type']=='note_on']),1)
        saved=self.path.read_bytes();self.st.undo();self.assertEqual(self.path.read_bytes(),original)
        self.st.undo(redo=True);self.assertEqual(self.path.read_bytes(),saved)

    def test_whole_beat_paste_history_pattern_playback_it_and_atomic_failure(self):
        from tests.test_tablature import TestWholeBeatPaste
        from vulturetracker import tablature
        from vulturetracker.itreader import read_it
        source,_=TestWholeBeatPaste().fixture();source['samples'][1]['file']='tone.wav'
        self.st.close();self.path.write_text('# Preserve whole-beat source comment\n'+api.to_yaml(source),encoding='utf-8')
        self.st=gui.State(self.path,headless=True);self.assertFalse(self.st.error,self.st.error)
        original=self.path.read_bytes()
        clip=tablature.capture_score_clipboard(self.st.song,'A',['0b0'],'oa')
        request=dict(op='beats_paste',pattern=1,row=0,occurrence='ob',clipboard=clip,across=True,mode='tg_replace')
        report=self.st.score_edit(dict(request,revision=self.st.text_sha()));saved=self.path.read_bytes()
        self.assertEqual(len(self.st.history),1);self.assertEqual(len(report['selection']['beats']),1)
        plan=self.st.mod.native_score['plan'];attacks=[e for e in plan['events'] if e['type']=='note_on']
        self.assertEqual(len(attacks),15)
        standalone=read_it(api.compile_song(self.path)[0])[0]
        self.assertEqual(sum(c.note is not None and c.note<120 for p in standalone.patterns for row in p.rows for c in row),15)
        positions=self.st.pattern_rows(1,'ob')['score_positions']
        at_zero=[p for p in positions if p['kind']=='note' and p['local_at']==[0,1]]
        self.assertEqual(len(at_zero),1);self.assertEqual(at_zero[0]['voice'],0)
        reopened=gui.State(self.path,headless=True)
        try:self.assertEqual(reopened.mod.native_score['plan'],plan)
        finally:reopened.close()
        self.st.undo();self.assertEqual(self.path.read_bytes(),original)
        self.st.undo(redo=True);self.assertEqual(self.path.read_bytes(),saved)
        before=self.path.read_bytes(),list(self.st.history),list(self.st.future)
        with patch.object(api,'compile_song',side_effect=ValueError('strict IT paste refusal')):
            with self.assertRaisesRegex(ValueError,'strict IT paste refusal'):
                self.st.score_edit(dict(request,row=12,revision=self.st.text_sha()))
        self.assertEqual((self.path.read_bytes(),list(self.st.history),list(self.st.future)),before)

    def test_implicit_clipboard_silence_history_pattern_playback_it_and_atomic_failure(self):
        from tests.test_tablature import TestWholeBeatPaste
        from vulturetracker.itreader import read_it
        source, _ = TestWholeBeatPaste().fixture()
        source['samples'][1]['file'] = 'tone.wav'
        beats = source['score']['patterns']['A']['beats']
        beats[:] = [b for b in beats if b['voice'] == 0 and b['at'] in ([0, 1], [2, 1])]
        beats[-1]['written']['value'] = 2
        self.st.close()
        self.path.write_text('# Preserve implicit silence\n' + api.to_yaml(source), encoding='utf-8')
        self.st = gui.State(self.path, headless=True)
        self.assertFalse(self.st.error, self.st.error)
        original = self.path.read_bytes()
        copied = self.st.score_clipboard(dict(revision=self.st.text_sha(),
            selection=[dict(occurrence='oa', beats=['0b0', '0b2'])]))
        self.assertEqual(self.path.read_bytes(), original)
        self.assertFalse(self.st.history)
        clip = copied['clipboard']; frozen = copy.deepcopy(clip)
        self.assertEqual(sorted((b['at'], bool(b['notes'])) for b in clip['beats'] + clip['implicit_rests']),
                         [([0, 1], True), ([1, 1], False), ([2, 1], True)])
        request = dict(op='beats_paste', pattern=1, row=0, occurrence='ob',
                       clipboard=clip, across=True, mode='tg_replace')
        self.st.score_edit(dict(request, revision=self.st.text_sha()))
        saved = self.path.read_bytes()
        self.assertEqual(clip, frozen)
        positions = self.st.pattern_rows(1, 'ob')['score_positions']
        self.assertEqual([p['local_at'] for p in positions if p['kind'] == 'note'], [[0, 1], [2, 1]])
        plan = self.st.mod.native_score['plan']
        self.assertEqual(sum(e['type'] == 'note_on' for e in plan['events']), 4)
        standalone = read_it(api.compile_song(self.path)[0])[0]
        self.assertEqual(sum(c.note is not None and c.note < 120 for p in standalone.patterns
                             for row in p.rows for c in row), 4)
        reopened = gui.State(self.path, headless=True)
        try: self.assertEqual(reopened.mod.native_score['plan'], plan)
        finally: reopened.close()
        self.st.undo(); self.assertEqual(self.path.read_bytes(), original)
        self.st.undo(redo=True); self.assertEqual(self.path.read_bytes(), saved)
        before = self.path.read_bytes(), list(self.st.history), list(self.st.future)
        with self.assertRaisesRegex(ValueError, 'insufficient room'):
            self.st.score_edit(dict(request, row=36, revision=self.st.text_sha()))
        self.assertEqual((self.path.read_bytes(), list(self.st.history), list(self.st.future)), before)
        self.assertEqual(clip, frozen)

    def test_repeated_pattern_clean_history_playback_pattern_and_standalone_it(self):
        from tests.test_tablature_page import TestTablaturePage
        from vulturetracker.itreader import read_it
        source = TestTablaturePage.fit_song()
        source['samples'][1]['file'] = 'tone.wav'
        self.st.close()
        self.path.write_bytes(('# Preserve repeated pattern\n' + api.to_yaml(source)).encode())
        self.st = gui.State(self.path, headless=True)
        self.assertFalse(self.st.error, self.st.error)
        original = self.path.read_bytes()
        self.st.score_command(dict(action='clean_beat', track='guitar',
            occurrence='pass-1', beats=['a'], revision=self.st.text_sha()))
        saved = self.path.read_bytes()
        self.assertEqual(len(self.st.history), 1)
        plan = self.st.mod.native_score['plan']
        self.assertEqual([(e['at'], e['pitch']) for e in plan['events'] if e['type']=='note_on'],
                         [([1,1],66),([3,1],68),([5,1],66),([7,1],68),([9,1],66),([11,1],68)])
        self.assertEqual([p['local_at'] for p in self.st.pattern_rows(0, 'pass-1')['score_positions']
                          if p['kind']=='note'], [[1,1],[3,1]])
        standalone = read_it(api.compile_song(self.path)[0])[0]
        self.assertEqual(sum(c.note is not None and c.note < 120 for pi in standalone.orders
            if pi < len(standalone.patterns) for row in standalone.patterns[pi].rows for c in row), 6)
        reopened = gui.State(self.path, headless=True)
        try: self.assertEqual(reopened.mod.native_score['plan'], plan)
        finally: reopened.close()
        self.st.undo(); self.assertEqual(self.path.read_bytes(), original)
        self.st.undo(redo=True); self.assertEqual(self.path.read_bytes(), saved)

    def test_matrix_entry_shared_history_pattern_playback_and_it(self):
        from tests.test_tablature import TestMatrixEntry
        from vulturetracker.itreader import read_it
        source,_=TestMatrixEntry().fixture();source['samples'][1]['file']='tone.wav'
        self.st.close();self.path.write_text('# Preserve matrix source comment\n'+api.to_yaml(source),encoding='utf-8')
        self.st=gui.State(self.path,headless=True);self.assertFalse(self.st.error,self.st.error)
        original=self.path.read_bytes()
        edit=dict(action='matrix_entry',occurrence='oa',track='guitar',voice=0,at=[27,10],pitch=67,written=dict(value=4))
        self.st.score_command(dict(edit,revision=self.st.text_sha()));saved=self.path.read_bytes()
        plan=self.st.mod.native_score['plan'];attacks=[e for e in plan['events'] if e['type']=='note_on']
        self.assertEqual(len(attacks),1)
        standalone=read_it(api.compile_song(self.path)[0])[0]
        self.assertEqual(sum(c.note==67 for p in standalone.patterns for row in p.rows for c in row),1)
        positions=self.st.pattern_rows(0,'oa')['score_positions']
        self.assertEqual([p['local_at'] for p in positions if p['kind']=='note'],[[2,1]])
        reopened=gui.State(self.path,headless=True)
        try:self.assertEqual(reopened.mod.native_score['plan'],plan)
        finally:reopened.close()
        self.st.undo();self.assertEqual(self.path.read_bytes(),original)
        self.st.undo(redo=True);self.assertEqual(self.path.read_bytes(),saved)
        before=self.path.read_bytes(),list(self.st.history),list(self.st.future)
        with patch.object(api,'compile_song',side_effect=ValueError('strict IT test refusal')):
            with self.assertRaisesRegex(ValueError,'strict IT test refusal'):
                self.st.score_command(dict(edit,pitch=69,revision=self.st.text_sha()))
        self.assertEqual((self.path.read_bytes(),list(self.st.history),list(self.st.future)),before)
        self.st.score_command(dict(edit,revision=self.st.text_sha()))
        self.assertFalse([e for e in self.st.mod.native_score['plan']['events'] if e['type']=='note_on'])
        self.st.undo();self.assertEqual(self.path.read_bytes(),saved)
        self.st.undo();self.assertEqual(self.path.read_bytes(),original)
        absent=dict(edit,voice=1,revision=self.st.text_sha())
        self.st.score_command(absent);self.assertEqual(self.path.read_bytes(),original);self.assertFalse(self.st.history)

    def test_stem_group_exact_history_audio_pattern_and_it(self):
        from tests.test_tablature import TestStemGroups
        source,_=TestStemGroups().fixture();source['samples'][1]['file']='tone.wav'
        self.st.close();self.path.write_text('# Preserve comment\n'+api.to_yaml(source),encoding='utf-8')
        self.st=gui.State(self.path,headless=True);self.assertFalse(self.st.error,self.st.error)
        before=self.path.read_bytes();audio=copy.deepcopy(self.st.mod.native_score['plan'])
        standalone=api.compile_song(self.path)[0];pattern=copy.deepcopy(self.st.pattern_rows(0,'oa')['display_rows'])
        edit=dict(action='set_stem',occurrence='oa',track='guitar',beat='b1',stem='down')
        self.st.score_command(dict(edit,revision=self.st.text_sha()));saved=self.path.read_bytes()
        self.assertEqual(api.compile_song(self.path)[0],standalone)
        self.assertEqual(self.st.mod.native_score['plan'],audio)
        self.assertEqual(self.st.pattern_rows(0,'oa')['display_rows'],pattern)
        self.st.score_command(dict(edit,revision=self.st.text_sha()));self.assertEqual(len(self.st.history),1)
        reopened=gui.State(self.path,headless=True)
        try:self.assertEqual(reopened.song,self.st.song)
        finally:reopened.close()
        self.st.undo();self.assertEqual(self.path.read_bytes(),before)
        self.st.undo(redo=True);self.assertEqual(self.path.read_bytes(),saved)
        self.st.undo();self.assertEqual(self.path.read_bytes(),before)

    def test_cross_cut_repeat_history_reopen_plan_it_and_late_failure(self):
        from tests.test_tablature import TestCrossRangeCommands
        from vulturetracker.itreader import read_it
        source, _, groups = TestCrossRangeCommands().fixture()
        source['samples'][1]['file'] = 'tone.wav'
        self.st.close(); self.path.write_text('# Keep this comment\n' + api.to_yaml(source), encoding='utf-8')
        self.st = gui.State(self.path, headless=True)
        self.assertFalse(self.st.error, self.st.error)
        original = self.path.read_bytes()
        for action in ('cut', 'delete', 'rest', 'repeat'):
            with self.subTest(action=action):
                report = self.st.score_command(dict(action=action, track='guitar', selection=groups, revision=self.st.text_sha()))
                saved = self.path.read_bytes()
                self.assertNotEqual(saved, original)
                self.assertEqual(self.st.song['patterns'], source['patterns'])
                plan = self.st.mod.native_score['plan']
                compiled = read_it(api.compile_song(self.path)[0])[0]
                expected = 16 if action == 'repeat' else 9
                self.assertEqual(len([e for e in plan['events'] if e['type']=='note_on']), expected)
                self.assertEqual(sum(c.note is not None and c.note < 120 for p in compiled.patterns for row in p.rows for c in row), expected)
                reopened = gui.State(self.path, headless=True)
                try: self.assertEqual(reopened.mod.native_score['plan'], plan)
                finally: reopened.close()
                frozen = copy.deepcopy(report.get('clipboard'))
                self.st.undo(); self.assertEqual(self.path.read_bytes(), original)
                self.st.undo(redo=True); self.assertEqual(self.path.read_bytes(), saved)
                self.assertEqual(report.get('clipboard'), frozen)
                self.st.undo(); self.assertEqual(self.path.read_bytes(), original)
        # Native backing accepts this raw note, but the final Repeat overlaps it.
        source['patterns']['D']['data'] = '\n'.join(['... .. ... ...'] * 12 + ['G-5 01 ... ...'])
        source['score']['patterns']['D']['beats'] = []
        self.st.close(); self.path.write_text(api.to_yaml(source), encoding='utf-8')
        self.st = gui.State(self.path, headless=True)
        self.assertFalse(self.st.error, self.st.error)
        before = self.path.read_bytes(), list(self.st.history), list(self.st.future)
        with self.assertRaisesRegex(ValueError, 'raw note'):
            self.st.score_command(dict(action='repeat', track='guitar', selection=groups, revision=self.st.text_sha()))
        self.assertEqual((self.path.read_bytes(), list(self.st.history), list(self.st.future)), before)

    def test_agent_new_pattern_retains_occurrences_and_score_history(self):
        result = agent.run(self.st, 'new_pattern', {'name': 'c', 'rows': 48, 'insert_at': 2})
        self.assertTrue(result.get('ok'), result)
        self.assertEqual(self.st.song['orders'], ['a', 'b', 'c'])
        self.assertEqual(self.st.song['score']['order_ids'][:2], ['first', 'second'])
        self.assertEqual(self.st.pattern_entry('c')['by'], 'agent')
        result = agent.run(self.st, 'set_orders', {'orders': ['c', 'a', 'b'], 'origins': [2, 0, 1]})
        self.assertTrue(result.get('ok'), result)
        self.assertEqual(self.st.song['score']['order_ids'][1:], ['first', 'second'])
        self.st.undo()
        self.st.undo()
        self.assertEqual(self.st.song['orders'], ['a', 'b'])
        self.assertNotIn('c', self.st.song['patterns'])

    def test_clone_and_channel_move_remap_residual_cells_and_automation(self):
        song = copy.deepcopy(self.st.song)
        song['score']['ties'] = []
        song['score']['patterns']['a']['beats'] = song['score']['patterns']['a']['beats'][:-1]
        song['patterns']['b']['automation'] = [{'target': 'X', 'rows': [0, 4], 'from': 0, 'to': 64}]
        self.st.close()
        self.path.write_bytes(api.to_yaml(song).encode())
        self.st = gui.State(self.path, headless=True)
        self.st.song_edit([{'op': 'pattern_clone', 'src': 'a', 'name': 'a2'},
                           {'op': 'channel_move', 'ch': 0, 'to': 2}])
        for name in ('a', 'a2'):
            pattern = next(p for p in self.st.mod.patterns if p.name == name)
            self.assertEqual((pattern.rows[0][2].note, pattern.rows[0][2].effect), (None, 24))
            self.assertEqual(self.st.song['score']['patterns'][name]['beats'][0]['notes'][0]['pitch'], 64)
            self.assertEqual(pattern.rows[0][0].effect, 0)
        self.assertEqual(self.st.song['patterns']['b']['automation'][0]['channel'], 3)
        self.assertEqual(self.st.mod.patterns[1].rows[0][2].effect, 24)
        self.st.undo()
        self.assertNotIn('a2', self.st.song['patterns'])
        self.assertNotIn('channel', self.st.song['patterns']['b']['automation'][0])

    def test_section_move_keeps_measure_on_its_occurrence(self):
        song = score_song()
        song['score']['ties'] = []
        song['score']['patterns']['a']['beats'] = song['score']['patterns']['a']['beats'][:-1]
        song['score']['measures'] = [{'id': 'bar_a', 'from': {'occurrence': 'first', 'at': [0, 1]},
                                    'to': {'occurrence': 'first', 'at': [4, 1]}, 'meter': [4, 4]}]
        song['sections'] = {'intro': [0, 1]}
        self.st.close()
        self.path.write_bytes(api.to_yaml(song).encode())
        self.st = gui.State(self.path, headless=True)
        self.st.section_edit({'name': 'intro', 'action': 'move', 'to': 2})
        self.assertEqual(self.st.song['orders'], ['b', 'a'])
        self.assertEqual(self.st.song['score']['order_ids'], ['second', 'first'])
        self.assertEqual(self.st.song['score']['measures'][0]['from']['occurrence'], 'first')
        self.st.undo()
        self.assertEqual(self.st.song['score']['order_ids'], ['first', 'second'])

    def test_measure_edit_protects_approved_pattern_and_uses_shared_history(self):
        measure = {'id': 'bar_a', 'from': {'occurrence': 'first', 'at': [0, 1]},
                   'to': {'occurrence': 'first', 'at': [4, 1]}, 'meter': [4, 4]}
        before = len(self.st.history)
        result = agent.run(self.st, 'edit_score', {'revision': self.st.text_sha(),
                           'edit': {'op': 'measure_set', 'measure': measure}})
        self.assertTrue(result.get('ok'), result)
        self.assertEqual(len(self.st.history), before + 1)
        self.assertEqual(self.st.pattern_entry('a')['by'], 'you and agent')
        self.assertNotIn('by', self.st.pattern_entry('b'))
        self.st.undo()
        self.assertEqual(self.st.song['score']['measures'], [])
        song = copy.deepcopy(self.st.song)
        song['patterns']['a']['approved'] = True
        self.st.close()
        self.path.write_bytes(api.to_yaml(song).encode())
        self.st = gui.State(self.path, headless=True)
        before = self.path.read_bytes(), len(self.st.history)
        with self.assertRaisesRegex(ValueError, 'approved'):
            self.edit(op='measure_set', measure=measure)
        self.assertEqual((self.path.read_bytes(), len(self.st.history)), before)

    def test_section_duplicate_clones_score_and_measure(self):
        self.test_section_move_keeps_measure_on_its_occurrence()
        self.st.section_edit({'name': 'intro', 'action': 'duplicate', 'to': 2, 'independent': True})
        clone = self.st.song['orders'][2]
        self.assertIn(clone, self.st.song['score']['patterns'])
        self.assertEqual(len(self.st.song['score']['measures']), 2)
        self.assertEqual(self.st.song['score']['measures'][1]['from']['occurrence'], self.st.song['score']['order_ids'][2])
        pi = self.st.mod.orders[2]
        display = self.st.pattern_rows(pi, self.st.facts['orders'][2]['occurrence'])['display_rows']
        self.assertEqual(parse_cell(display[0][1]).note, 60)


class TestPlaceScoreState(unittest.TestCase):
    setUp = TestTablatureSync.setUp

    def prepare(self):
        from tests.test_tablature import beat, note
        song = copy.deepcopy(self.st.song)
        song['score']['ties'] = []
        song['score']['patterns']['a']['beats'] = [beat('rest', [0, 1], [], 1)]
        self.st._commit('# Keep this source comment.\n' + api.to_yaml(song))
        return dict(action='place', occurrence='first',
                    beat=beat('new-beat', [1, 2], [note('new-note', 64, 1, 0)], 8))

    def test_place_is_one_history_entry_with_exact_undo_redo_and_reopen(self):
        request = self.prepare()
        before, history = self.path.read_bytes(), len(self.st.history)
        result = self.st.score_command(dict(request, revision=self.st.text_sha()))
        after = self.path.read_bytes()
        self.assertEqual(len(self.st.history), history + 1)
        self.assertEqual(result['selection']['at'], [1, 2])
        self.assertNotIn('clipboard', result)
        self.assertTrue(after.startswith(b'# Keep this source comment.\n'))
        self.st.undo()
        self.assertEqual(self.path.read_bytes(), before)
        self.st.undo(redo=True)
        self.assertEqual(self.path.read_bytes(), after)
        self.st.close()
        reopened = gui.State(self.path, headless=True)
        self.addCleanup(reopened.close)
        self.assertIsNone(reopened.error)
        self.assertEqual(reopened.song['score'], self.st.song['score'])

    def test_place_stale_approved_guard_write_and_model_failures_are_atomic(self):
        request = self.prepare()
        before = self.path.read_bytes(), len(self.st.history), copy.deepcopy(self.st.song)
        with self.assertRaisesRegex(ValueError, 'changed'):
            self.st.score_command(dict(request, revision='stale'))
        with self.assertRaisesRegex(RuntimeError, 'guard refused'):
            self.st.score_command(dict(request, revision=self.st.text_sha()),
                                  guard=lambda *_: (_ for _ in ()).throw(RuntimeError('guard refused')))
        with patch.object(self.st, '_write_step', side_effect=OSError('write refused')):
            with self.assertRaisesRegex(OSError, 'write refused'):
                self.st.score_command(dict(request, revision=self.st.text_sha()))
        bad = copy.deepcopy(request)
        bad['beat']['at'] = [1, 17]
        with self.assertRaisesRegex(ValueError, 'unsupported written subdivision'):
            self.st.score_command(dict(bad, revision=self.st.text_sha()))
        self.assertEqual((self.path.read_bytes(), len(self.st.history), self.st.song), before)
        self.st.song_edit([{'op': 'mark', 'what': 'pattern', 'key': 'a', 'approved': True}])
        before = self.path.read_bytes(), len(self.st.history), copy.deepcopy(self.st.song)
        with self.assertRaisesRegex(ValueError, 'approved'):
            self.st.score_command(dict(request, revision=self.st.text_sha()))
        self.assertEqual((self.path.read_bytes(), len(self.st.history), self.st.song), before)


class TestPlaceFitState(unittest.TestCase):
    setUp = TestTablatureSync.setUp

    def prepare(self, insufficient=False, mode='tg_duration', length=Fraction(2)):
        from tests.test_tablature import TestPlaceFitCommand
        helper = TestPlaceFitCommand()
        source, _ = helper.fixture(insufficient)
        song = copy.deepcopy(self.st.song)
        song['score']['ties'] = []
        song['score']['patterns']['a']['beats'] = source['score']['patterns']['A']['beats']
        self.st._commit('# Preserve block YAML and comments.\n' + api.to_yaml(song))
        request = helper.request(source, mode, length)
        request['occurrence'] = 'first'
        return request

    def test_shift_and_insertion_fallback_have_one_exact_undo(self):
        for insufficient in (False, True):
            request = self.prepare(insufficient, 'tg_insert', Fraction(5, 2) if insufficient else Fraction(2))
            before, count = self.path.read_bytes(), len(self.st.history)
            result = self.st.score_command(dict(request, revision=self.st.text_sha()))
            self.assertEqual(result['fit']['outcome'], 'old_duration' if insufficient else 'shifted')
            self.assertEqual(len(self.st.history), count + 1)
            after = self.path.read_bytes()
            self.st.undo()
            self.assertEqual(self.path.read_bytes(), before)
            self.st.undo(redo=True)
            self.assertEqual(self.path.read_bytes(), after)

    def test_duration_noop_preserves_block_yaml_history_and_redo(self):
        request = self.prepare(True, 'tg_duration', Fraction(5, 2))
        # Leave a redo branch, while restoring the hand-written block layout.
        prior = self.path.read_bytes()
        modified = copy.deepcopy(self.st.song)
        modified['module']['title'] = 'temporary'
        self.st._commit(api.to_yaml(modified))
        self.st.undo()
        self.assertEqual(self.path.read_bytes(), prior)
        before = self.path.read_bytes(), copy.deepcopy(self.st.history), copy.deepcopy(self.st.future), self.st.text_sha()
        with patch.object(self.st, '_write_step', side_effect=AssertionError('no-op must not write')):
            result = self.st.score_command(dict(request, revision=self.st.text_sha()))
        self.assertEqual(result['fit']['outcome'], 'unchanged')
        self.assertEqual(result['revision'], before[-1])
        self.assertEqual((self.path.read_bytes(), self.st.history, self.st.future, self.st.text_sha()), before)

    def test_fit_stale_guard_write_and_approval_failures_are_atomic(self):
        request = self.prepare()
        before = self.path.read_bytes(), len(self.st.history), copy.deepcopy(self.st.song)
        with self.assertRaisesRegex(ValueError, 'changed'):
            self.st.score_command(dict(request, revision='stale'))
        with self.assertRaisesRegex(RuntimeError, 'guard refused'):
            self.st.score_command(dict(request, revision=self.st.text_sha()),
                                  guard=lambda *_: (_ for _ in ()).throw(RuntimeError('guard refused')))
        with patch.object(self.st, '_write_step', side_effect=OSError('write refused')):
            with self.assertRaisesRegex(OSError, 'write refused'):
                self.st.score_command(dict(request, revision=self.st.text_sha()))
        self.assertEqual((self.path.read_bytes(), len(self.st.history), self.st.song), before)
        self.st.song_edit([dict(op='mark', what='pattern', key='a', approved=True)])
        before = self.path.read_bytes(), len(self.st.history)
        with self.assertRaisesRegex(ValueError, 'approved'):
            self.st.score_command(dict(request, revision=self.st.text_sha()))
        self.assertEqual((self.path.read_bytes(), len(self.st.history)), before)


class TestPlacePartialFitState(unittest.TestCase):
    setUp = TestTablatureSync.setUp
    prepare = TestPlaceFitState.prepare

    def test_partial_fit_has_one_history_entry_exact_undo_redo_and_reopen(self):
        from vulturetracker import tablature as tab
        for trailing in (False, True):
            for mode in ('tg_duration', 'tg_insert'):
                with self.subTest(trailing=trailing, mode=mode):
                    request = self.prepare(trailing, mode, Fraction(3, 2))
                    before, count = self.path.read_bytes(), len(self.st.history)
                    result = self.st.score_command(dict(request, revision=self.st.text_sha()))
                    self.assertEqual(result['fit']['outcome'], 'shifted')
                    self.assertEqual(len(self.st.history), count + 1)
                    after = self.path.read_bytes()
                    self.assertTrue(after.startswith(b'# Preserve block YAML and comments.\n'))
                    beats = {b['id']: b for b in self.st.song['score']['patterns']['a']['beats']}
                    self.assertNotIn('r', beats)
                    self.assertEqual(tab.duration_quarters(beats['b']['written']),
                                     1 if trailing else Fraction(3, 2))
                    self.assertEqual(beats['c']['at'], [5, 2] if trailing else [3, 1])
                    self.st.undo()
                    self.assertEqual(self.path.read_bytes(), before)
                    self.st.undo(redo=True)
                    self.assertEqual(self.path.read_bytes(), after)
        expected = copy.deepcopy(self.st.song)
        self.st.close()
        reopened = gui.State(self.path, headless=True)
        self.addCleanup(reopened.close)
        self.assertIsNone(reopened.error)
        self.assertEqual(reopened.song, expected)

    def test_partial_stale_peer_guard_write_and_approval_failures_are_atomic(self):
        from tests.test_tablature import beat, note
        request = self.prepare(length=Fraction(3, 2))
        before = self.path.read_bytes(), len(self.st.history), copy.deepcopy(self.st.song)
        with self.assertRaisesRegex(ValueError, 'changed'):
            self.st.score_command(dict(request, revision='stale'))
        with self.assertRaisesRegex(RuntimeError, 'guard refused'):
            self.st.score_command(dict(request, revision=self.st.text_sha()),
                                  guard=lambda *_: (_ for _ in ()).throw(RuntimeError('guard refused')))
        with patch.object(self.st, '_write_step', side_effect=OSError('write refused')):
            with self.assertRaisesRegex(OSError, 'write refused'):
                self.st.score_command(dict(request, revision=self.st.text_sha()))
        self.assertEqual((self.path.read_bytes(), len(self.st.history), self.st.song), before)
        peer_song = copy.deepcopy(self.st.song)
        peer_song['score']['patterns']['a']['beats'].append(
            beat('peer', [3, 2], [note('peer-note', 59, 2, 0)], 8, voice=1))
        self.st._commit(api.to_yaml(peer_song))
        before = self.path.read_bytes(), len(self.st.history), copy.deepcopy(self.st.song)
        peer = copy.deepcopy(peer_song['score']['patterns']['a']['beats'][-1])
        result = self.st.score_command(dict(request, revision=self.st.text_sha()))
        self.assertEqual(result['fit']['outcome'], 'shifted')
        self.assertEqual(next(b for b in self.st.song['score']['patterns']['a']['beats'] if b['id'] == 'peer'), peer)
        saved = self.path.read_bytes()
        self.assertEqual(len(self.st.history), before[1] + 1)
        self.st.undo()
        self.assertEqual((self.path.read_bytes(), len(self.st.history), self.st.song), before)
        self.st.undo(redo=True); self.assertEqual(self.path.read_bytes(), saved)
        request = self.prepare(length=Fraction(3, 2))
        self.st.song_edit([dict(op='mark', what='pattern', key='a', approved=True)])
        before = self.path.read_bytes(), len(self.st.history), copy.deepcopy(self.st.song)
        with self.assertRaisesRegex(ValueError, 'approved'):
            self.st.score_command(dict(request, revision=self.st.text_sha()))
        self.assertEqual((self.path.read_bytes(), len(self.st.history), self.st.song), before)


class TestPlacePeerFitState(unittest.TestCase):
    setUp = TestTablatureSync.setUp

    def prepare(self, mode='tg_duration'):
        from tests.test_tablature import TestPlacePeerFitCommand
        helper = TestPlacePeerFitCommand()
        source, _, length = helper.fixture()
        song = copy.deepcopy(self.st.song)
        song['score']['ties'] = []
        song['score']['patterns']['a']['beats'] = source['score']['patterns']['A']['beats']
        self.st._commit('# Peer identities must survive.\n' + api.to_yaml(song))
        request = helper.request(source, mode, length)
        request['occurrence'] = 'first'
        return request

    def test_both_peer_modes_preserve_records_with_exact_undo_redo_and_reopen(self):
        for mode in ('tg_duration', 'tg_insert'):
            with self.subTest(mode=mode):
                request = self.prepare(mode)
                before, count = self.path.read_bytes(), len(self.st.history)
                peers = {b['id']: copy.deepcopy(b) for b in self.st.song['score']['patterns']['a']['beats']
                         if b.get('voice', 0) == 1}
                result = self.st.score_command(dict(request, revision=self.st.text_sha()))
                self.assertEqual(result['fit']['outcome'], 'shifted')
                self.assertEqual(len(self.st.history), count + 1)
                after = self.path.read_bytes()
                self.assertTrue(after.startswith(b'# Peer identities must survive.\n'))
                records = {b['id']: b for b in self.st.song['score']['patterns']['a']['beats']}
                self.assertEqual({key: records[key] for key in peers}, peers)
                self.assertEqual(records['c']['at'], [5, 2] if mode == 'tg_duration' else [3, 1])
                self.st.undo()
                self.assertEqual(self.path.read_bytes(), before)
                self.st.undo(redo=True)
                self.assertEqual(self.path.read_bytes(), after)
        expected = copy.deepcopy(self.st.song)
        self.st.close()
        reopened = gui.State(self.path, headless=True)
        self.addCleanup(reopened.close)
        self.assertIsNone(reopened.error)
        self.assertEqual(reopened.song, expected)

    def test_peer_stale_annotation_guard_write_and_approval_failures_are_atomic(self):
        request = self.prepare()
        before = self.path.read_bytes(), len(self.st.history), copy.deepcopy(self.st.song)
        with self.assertRaisesRegex(ValueError, 'changed'):
            self.st.score_command(dict(request, revision='stale'))
        with self.assertRaisesRegex(RuntimeError, 'guard refused'):
            self.st.score_command(dict(request, revision=self.st.text_sha()),
                                  guard=lambda *_: (_ for _ in ()).throw(RuntimeError('guard refused')))
        with patch.object(self.st, '_write_step', side_effect=OSError('write refused')):
            with self.assertRaisesRegex(OSError, 'write refused'):
                self.st.score_command(dict(request, revision=self.st.text_sha()))
        self.assertEqual((self.path.read_bytes(), len(self.st.history), self.st.song), before)
        annotated = copy.deepcopy(self.st.song)
        next(b for b in annotated['score']['patterns']['a']['beats'] if b['id'] == 'suffix')['text'] = 'keep'
        self.st._commit(api.to_yaml(annotated))
        before = self.path.read_bytes(), len(self.st.history), copy.deepcopy(self.st.song)
        with self.assertRaisesRegex(ValueError, 'annotated cohort'):
            self.st.score_command(dict(request, revision=self.st.text_sha()))
        self.assertEqual((self.path.read_bytes(), len(self.st.history), self.st.song), before)
        request = self.prepare()
        self.st.song_edit([dict(op='mark', what='pattern', key='a', approved=True)])
        before = self.path.read_bytes(), len(self.st.history), copy.deepcopy(self.st.song)
        with self.assertRaisesRegex(ValueError, 'approved'):
            self.st.score_command(dict(request, revision=self.st.text_sha()))
        self.assertEqual((self.path.read_bytes(), len(self.st.history), self.st.song), before)


class TestNativePlaybackPreparation(unittest.TestCase):
    def test_sampled_it_timing_preserves_audio_source_and_strict_guards(self):
        import numpy as np
        from vulturetracker.openmpt import LoadedModule
        from tests.test_tablature import beat, note
        song = score_song()
        song['module'].update(tempo=125, global_volume=128, mix_volume=128)
        song['patterns']['a']['data'] = ''
        song['score']['ties'] = []
        song['score']['patterns']['a']['beats'] = [
            beat('before', [0,1], [note('before',64,1,0)]),
            dict(beat('strum', [2,1], [note('high',64,1,0), note('low',59,2,0)]), stroke=dict(direction='down',value=64))]
        song['score']['patterns']['b']['beats'] = [beat('after', [1,1], [note('after',64,1,0)])]
        before = copy.deepcopy(song)
        with self.assertRaisesRegex(SongError, 'IT tick grid'):
            api.compile_song(song, self.base)
        data, module, warnings = api.compile_song(song, self.base, render_timing=True)
        self.assertTrue(any('IT timing:' in w for w in warnings))
        self.assertEqual(len(module.samples), 2)  # Only the delayed string needs a sample.
        self.assertIsNone(module.native_score)
        self.assertEqual(song, before)
        native = api.prepare_playback(song, self.base, sample_rate=88200)
        with LoadedModule(native['backing_it'],88200,1,plan=native['plan']) as player:
            expected = np.frombuffer(player.render(88200,oversample=1,floats=True,max_seconds=3.8),'<f4')
        with LoadedModule(data,88200,1) as player:
            actual = np.frombuffer(player.render(88200,oversample=1,floats=True,max_seconds=3.8),'<f4')
        size=min(len(actual),len(expected))
        error = np.sqrt(np.mean((actual[:size]-expected[:size])**2))
        self.assertLess(error, .0001)
        # A failed fallback cannot replace an existing destination or rewrite its source.
        bad=copy.deepcopy(song);bad['patterns']['a']['data']='00: ... .. v32 ...\n'
        path=self.base/'atomic.yaml';path.write_bytes(api.to_yaml(bad).encode())
        original=path.read_bytes();out=self.base/'keep.it';out.write_bytes(b'owner output')
        with self.assertRaisesRegex(SongError, 'raw notes, mix controls') as refused:
            api.build(path,out)
        self.assertIn('IT tick grid', str(refused.exception))
        self.assertIn('sampled export also refused', str(refused.exception))
        self.assertEqual(path.read_bytes(),original);self.assertEqual(out.read_bytes(),b'owner output')

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        write_wav(self.base / 'tone.wav', RATE, [sine(220)])

    def native_song(self):
        song = score_song()
        song['patterns']['a']['data'] = ''
        song['score']['ties'] = []
        first = song['score']['patterns']['a']['beats'][0]
        first['at'], first['notes'] = [1, 13], first['notes'][:1]
        first['written'] = {'value': 64, 'dots': 2, 'tuplet': [13, 8]}
        song['score']['patterns']['a']['beats'] = [first]
        song['score']['patterns']['b']['beats'][0]['at'] = [7, 2]
        return song

    def test_exact_preparation_is_rate_specific_single_compile_and_strict_stays_strict(self):
        from vulturetracker import song as compiler
        song = self.native_song()
        before = copy.deepcopy(song)
        for rate in (44100, 48000, 88200, 96000):
            with self.subTest(rate=rate), patch.object(compiler, 'compile_tree', wraps=compiler.compile_tree) as compile:
                result = api.prepare_playback(song, self.base, rate)
                self.assertEqual(compile.call_count, 1)
            self.assertEqual(set(result), {'backing_it', 'plan', 'view', 'module', 'warnings'})
            plan = result['plan']
            self.assertEqual(plan['sample_rate'], rate)
            exact = Fraction(rate, 26)
            nearest = exact.numerator // exact.denominator + (2 * (exact.numerator % exact.denominator) >= exact.denominator)
            self.assertEqual(plan['events'][0]['frame'], nearest)
            self.assertEqual(plan['events'][-1]['type'], 'note_off')
            self.assertEqual(plan['events'][-1]['frame'], plan['duration']['frames'])
            self.assertEqual(plan['duration']['frames'], 4 * rate)
            self.assertEqual(result['view']['positions'][0]['duration'], [7, 104])
            self.assertIs(result['module'].native_score['plan'], plan)
            self.assertIsNone(result['module'].score_projection)
            self.assertTrue(all(c.note is None for p in result['module'].patterns for row in p.rows for c in row))
        with self.assertRaisesRegex(SongError, 'not representable'):
            api.compile_song(song, self.base)
        with self.assertRaisesRegex(SongError, 'not representable'):
            compiler.load_song_text(api.to_yaml(song), self.base)
        self.assertEqual(song, before)

    def test_backing_cannot_be_exported_by_ordinary_writer(self):
        from vulturetracker.itwriter import write_it
        result = api.prepare_playback(self.native_song(), self.base)
        for module in (result['module'], copy.deepcopy(result['module'])):
            with self.assertRaisesRegex(ValueError, 'not a standalone IT export'):
                write_it(module)
        stripped = self.native_song()
        stripped.pop('score')
        self.assertEqual(result['backing_it'], api.compile_song(stripped, self.base)[0])

    def test_compiled_global_volume_lane_stays_in_backing_not_score_events(self):
        from vulturetracker.openmpt import LoadedModule
        song = self.native_song()
        plain = api.prepare_playback(song, self.base)
        lane = {'target': 'V', 'channel': 1, 'rows': [0, 4], 'from': 0, 'to': 128}
        song['patterns']['a']['automation'] = [lane]
        handwritten = copy.deepcopy(song)
        del handwritten['patterns']['a']['automation']
        handwritten['patterns']['a']['data'] = ''.join(
            f'{row:02d}: ... .. ... V{value:02X}\n' for row, value in enumerate((0, 32, 64, 96, 128)))
        before = copy.deepcopy(song), copy.deepcopy(handwritten)
        automated = api.prepare_playback(song, self.base)
        written = api.prepare_playback(handwritten, self.base)
        self.assertEqual(automated['backing_it'], written['backing_it'])
        self.assertEqual(automated['plan']['events'], plain['plan']['events'])
        self.assertEqual(written['plan']['events'], plain['plan']['events'])
        controls = [(row, ch, cell.effect, cell.param) for row, cells in
                    enumerate(automated['module'].patterns[0].rows) for ch, cell in enumerate(cells) if cell.effect]
        self.assertEqual(controls, [(row, 0, 22, value) for row, value in enumerate((0, 32, 64, 96, 128))])
        with LoadedModule(automated['backing_it']) as module:
            self.assertEqual([module.cell(0, row, 0)['effect_text'] for row in range(5)],
                             ['V00', 'V20', 'V40', 'V60', 'V80'])
        self.assertEqual((song, handwritten), before)
        for mode, effect in [('data', 'X40'), ('data', 'M40'), ('data', 'D07'), ('data', 'T78'),
                             ('lane', 'X'), ('lane', 'M'), ('lane', 'T')]:
            refused = self.native_song()
            if mode == 'data':
                refused['patterns']['a']['data'] = f'00: ... .. ... {effect}\n'
            else:
                refused['patterns']['a']['automation'] = [dict(lane, target=effect, **{'from': 32, 'to': 64})]
            original = copy.deepcopy(refused)
            with self.subTest(mode=mode, effect=effect):
                result = api.prepare_playback(refused, self.base)
                if effect == 'T':
                    self.assertEqual(result['plan']['tempos'][0], {'at': [0, 1], 'bpm': 32})
                    self.assertNotEqual(result['plan']['events'], plain['plan']['events'])
                else:
                    self.assertEqual(result['plan']['events'], plain['plan']['events'])
                self.assertTrue(any(c.effect for row in result['module'].patterns[0].rows for c in row))
            self.assertEqual(refused, original)

    def test_residual_cells_and_inherited_instrument_command_are_preserved(self):
        song = self.native_song()
        song['patterns']['a']['data'] = 'E-5 01 ... ...\n' + '... .. ... ...\n' * 5 + '=== .. ... ...\n'
        first = song['score']['patterns']['a']['beats'][0]
        first['at'] = [1, 1]
        first['notes'][0]['instrument'] = 0
        before = copy.deepcopy(song)
        result = api.prepare_playback(song, self.base)
        on = result['plan']['events'][0]
        self.assertEqual((on['instrument'], on['source_instrument'], on['instrument_inherited']), (1, 0, True))
        self.assertIsNone(on['volume'])
        pattern = result['module'].patterns[0]
        self.assertEqual((pattern.rows[0][0].note, pattern.rows[0][0].instrument), (64, 1))
        self.assertEqual(pattern.rows[6][0].note, NOTE_OFF)
        self.assertIsNone(pattern.rows[12][0].note)
        self.assertEqual(song, before)

    def test_backing_keeps_unnamed_score_only_channels_when_loaded(self):
        from vulturetracker.openmpt import LoadedModule
        for count in (6, 64):
            with self.subTest(channels=count):
                song = self.native_song()
                song['module']['channels'] = [{} for _ in range(count)]
                song['score']['tracks']['guitar']['channels'] = list(range(count - 6, count))
                song['score']['patterns']['a']['beats'][0]['notes'][0]['channel'] = count - 1
                result = api.prepare_playback(song, self.base)
                self.assertIn(count - 1, [e['ch'] for e in result['plan']['events']])
                with LoadedModule(result['backing_it']) as module:
                    self.assertEqual(module.info()['channels'], count)
                self.assertTrue(all(not c.name for c in result['module'].channels))
                self.assertTrue(all(c.note is None for p in result['module'].patterns for row in p.rows for c in row))

    def test_legacy_dict_text_and_path_bytes_are_identical(self):
        from vulturetracker.itwriter import write_it
        song = score_song()
        song.pop('score')
        song['patterns']['a']['data'] = '00: C-5 01 v32 X40\n'
        text = api.to_yaml(song)
        path = self.base / 'legacy.yaml'
        path.write_bytes(text.encode('utf-8'))
        expected, _, warnings = api.compile_song(song, self.base)
        for source in (song, text, path):
            result = api.prepare_playback(source, self.base, 96000)
            self.assertEqual(result['backing_it'], expected)
            self.assertEqual(write_it(result['module']), expected)
            self.assertEqual(result['warnings'], warnings if source is not path else
                             api.compile_song(path, self.base)[2])
            self.assertIsNone(result['plan'])
            self.assertIsNone(result['view'])
            self.assertIsNone(result['module'].native_score)

    def test_native_rejections_do_not_fall_back_to_strict_projection(self):
        for change, message in [('sample', 'no declared instrument/sample'),
                                ('instrument', 'no declared instrument/sample'),
                                ('keymap', 'not defined'), ('effect', 'raw effect/volume')]:
            song = score_song()  # ordinarily strict-projectable
            song['patterns']['a']['data'] = ''
            if change == 'effect':
                song['patterns']['a']['data'] = '00: ... .. ... H40\n'
                api.compile_song(song, self.base)  # legacy strict playback supports this
            elif change == 'keymap':
                song['instruments'] = {1: {'keymap': [{'notes': 'C-0..B-9', 'sample': 2}]}}
            else:
                if change == 'instrument':
                    song['instruments'] = {1: {'sample': 1}}
                song['score']['tracks']['guitar']['instrument'] = 2
            before = copy.deepcopy(song)
            with self.subTest(change=change), self.assertRaisesRegex(SongError, message):
                api.prepare_playback(song, self.base)
            self.assertEqual(song, before)
        for rate in (None, True, 0, 44100.0):
            with self.subTest(rate=rate), self.assertRaisesRegex(ValueError, 'mixer rate'):
                api.prepare_playback(self.native_song(), self.base, rate)

    def test_score_pitches_use_existing_mapped_sample_bandwidth_checks(self):
        from vulturetracker import song as compiler
        from vulturetracker import resample
        song = self.native_song()
        song['instruments'] = {1: {'name': 'Mapped', 'keymap': [
            {'notes': 'C-0..B-9', 'sample': 1, 'play_note': 'C-6'}]}}
        with patch.dict(compiler._IMAGES, clear=True), patch.dict(compiler._EDGES, clear=True), \
             patch.object(resample, 'image_level', return_value=-20) as images, \
             patch.object(resample, 'spectral_edge', return_value=0.49) as edges:
            result = api.prepare_playback(song, self.base)
        sample = result['module'].samples[0]
        self.assertEqual(images.call_args.args[1], sample.c5_speed * 2)
        self.assertTrue(edges.called)
        self.assertTrue(any('score first/e' in w and 'interpolation images' in w for w in result['warnings']))
        self.assertTrue(any('score first/e' in w and 'over the ceiling' in w for w in result['warnings']))
        # Empty keymap entries keep the same audible-silence warning as strict cells.
        song['instruments'][1]['keymap'] = [{'notes': 'C-0', 'sample': 1}]
        result = api.prepare_playback(song, self.base)
        self.assertTrue(any('no sample in instrument' in w for w in result['warnings']))


class TestNativeSelectionTransforms(unittest.TestCase):
    setUp = TestNativePlaybackPreparation.setUp
    native_song = TestNativePlaybackPreparation.native_song

    def state(self, song):
        return TestPreparedPlaybackBundle.state(self, song)

    def transform(self, st, action, selections=None, **params):
        st.edit_patterns([], revision=st.text_sha(), transform=dict(action=action,
            selections=selections or [dict(pattern=0, r0=0, r1=0,
                cols=[[0, ['note', 'instrument', 'volume']]])], **params))

    def test_fractional_transpose_preserves_identity_timing_controls_and_reopen_undo(self):
        song = self.native_song()
        song['patterns']['a']['data'] = '00: ... .. ... X40\n'
        st = self.state(song)
        original = copy.deepcopy(st.song)
        before = copy.deepcopy(st.mod.native_score['view']['positions'])
        self.transform(st, 'transpose', semitones=2)
        beat = st.song['score']['patterns']['a']['beats'][0]
        expected = copy.deepcopy(original['score']['patterns']['a']['beats'][0])
        expected['notes'][0].update(pitch=66, fret=2)
        self.assertEqual(beat, expected)
        self.assertEqual(st.mod.patterns[0].rows[0][0].effect, 24)
        after = st.mod.native_score['view']['positions']
        for a, b in zip(before, after):
            for field in ('id', 'row', 'end_row', 'at', 'end', 'voice', 'track'):
                self.assertEqual(a[field], b[field])
        st.close()
        reopened = gui.State(st.song_path, headless=True)
        self.addCleanup(reopened.close)
        reopened.undo()
        self.assertEqual(reopened.song, original)

    def test_tied_chain_batch_transpose_cut_and_partial_refusal(self):
        st = self.state(score_song())
        first = dict(pattern=0, r0=42, r1=47, cols=[[0, ['note']]])
        second = dict(pattern=1, r0=0, r1=5, cols=[[0, ['note']]])
        before = st.song_path.read_bytes(), len(st.history)
        with self.assertRaisesRegex(ValueError, 'complete tied chain'):
            self.transform(st, 'transpose', [first], semitones=1)
        self.assertEqual((st.song_path.read_bytes(), len(st.history)), before)
        self.transform(st, 'transpose', [first, second], semitones=1)
        self.assertEqual(st.song['score']['ties'], score_song()['score']['ties'])
        events = [e for e in st.mod.native_score['plan']['events'] if e.get('note') == 'tie_a']
        self.assertTrue(events)
        self.assertTrue(all(e['pitch'] == 65 for e in events))
        self.transform(st, 'cut', [first, second])
        self.assertEqual(st.song['score']['ties'], [])
        self.assertEqual(st.song['score']['patterns']['a']['beats'][-1]['notes'], [])
        self.assertEqual(len(st.history), 2)
        st.undo()
        self.assertTrue(st.song['score']['ties'])

    def test_volumes_humanize_and_clear_preserve_fractional_timing_and_raw_effects(self):
        song = self.native_song()
        song['patterns']['a']['data'] = ('00: ... .. ... X40 | G-4 01 v40 M20\n'
                                       '01: ... .. ... ...\n02: ... .. ... ... | === .. ... D07\n')
        st = self.state(song)
        selection = [dict(pattern=0, r0=0, r1=2, cols=[[0, ['volume']], [1, ['volume']]])]
        self.transform(st, 'amplify', selection, percent=50)
        note = st.song['score']['patterns']['a']['beats'][0]['notes'][0]
        self.assertEqual(note['volume'], 32)
        self.assertEqual(st.mod.patterns[0].rows[0][1].volcmd, 20)
        raw_effects = [(c.effect, c.param) for row in st.mod.patterns[0].rows for c in row]
        timing = st.song['score']['patterns']['a']['beats'][0]['at']
        self.transform(st, 'humanize', selection, amount=6, seed=42)
        humanized = copy.deepcopy(st.song)
        st.undo()
        self.transform(st, 'humanize', selection, amount=6, seed=42)
        self.assertEqual(st.song, humanized)
        self.assertEqual(raw_effects, [(c.effect, c.param) for row in st.mod.patterns[0].rows for c in row])
        self.transform(st, 'clear', selection)
        self.assertNotIn('volume', st.song['score']['patterns']['a']['beats'][0]['notes'][0])
        self.assertEqual(st.song['score']['patterns']['a']['beats'][0]['at'], timing)
        self.assertEqual(raw_effects, [(c.effect, c.param) for row in st.mod.patterns[0].rows for c in row])

    def test_tied_humanize_is_one_delta_and_keeps_ties(self):
        st = self.state(score_song())
        selections = [dict(pattern=0, r0=42, r1=47, cols=[[0, ['volume']]]),
                      dict(pattern=1, r0=0, r1=5, cols=[[0, ['volume']]])]
        self.transform(st, 'humanize', selections, seed=4, amount=32)
        notes = [st.song['score']['patterns']['a']['beats'][-1]['notes'][0],
                 st.song['score']['patterns']['b']['beats'][0]['notes'][0]]
        self.assertEqual(notes[0]['volume'], notes[1]['volume'])
        self.assertEqual(st.song['score']['ties'], score_song()['score']['ties'])

    def test_exact_cursor_target_does_not_change_neighbor_or_raw_cells(self):
        song = self.native_song()
        song['patterns']['a']['data'] = '00: ... .. ... X40\n'
        chord = song['score']['patterns']['a']['beats'][0]
        chord['notes'].append(dict(id='neighbor', string=2, fret=1, pitch=60))
        st = self.state(song)
        raw = copy.deepcopy(st.mod.patterns)
        self.transform(st, 'clear', [dict(pattern=0, notes=['e'],
            cols=[[0, ['note']], [1, ['note']]])])
        self.assertEqual(st.song['score']['patterns']['a']['beats'][0]['notes'], [chord['notes'][1]])
        self.assertEqual(st.mod.patterns, raw)

    def test_stale_approved_readonly_invalid_fingering_and_write_failure_are_atomic(self):
        st = self.state(self.native_song())
        edit = dict(action='transpose', semitones=1,
                    selections=[dict(pattern=0, cols=[[0, ['note']]])])
        before = st.song_path.read_bytes(), copy.deepcopy(st.song), len(st.history)
        with self.assertRaisesRegex(ValueError, 'changed'):
            st.edit_patterns([], transform=edit, revision='old')
        with self.assertRaisesRegex(ValueError, 'fingering'):
            self.transform(st, 'transpose', semitones=-1)
        with patch.object(st, 'write_song', side_effect=OSError('write failed')):
            with self.assertRaisesRegex(OSError, 'write failed'):
                self.transform(st, 'transpose', semitones=1)
        st.read_only = 'owner holds the song'
        with self.assertRaisesRegex(ValueError, 'owner holds'):
            self.transform(st, 'transpose', semitones=1)
        st.read_only = None
        self.assertEqual((st.song_path.read_bytes(), st.song, len(st.history)), before)
        st.song['patterns']['a']['approved'] = True
        with self.assertRaisesRegex(ValueError, 'approved'):
            self.transform(st, 'transpose', semitones=1)
        self.assertEqual((st.song_path.read_bytes(), len(st.history)), (before[0], before[2]))

    def test_aligned_raw_volume_keeps_ownership_and_unused_repeated_patterns(self):
        song = self.native_song()
        song['score']['patterns']['a']['beats'][0]['at'] = [0, 1]
        song['patterns']['a']['data'] = '00: ... .. v40 X40\n'
        song['orders'] = ['a', 'a']
        song['score']['order_ids'] = ['first', 'again']
        st = self.state(song)
        self.transform(st, 'humanize', amount=32, seed=4)
        self.assertNotIn('volume', st.song['score']['patterns']['a']['beats'][0]['notes'][0])
        self.assertNotEqual(st.mod.patterns[0].rows[0][0].volcmd, 40)
        self.assertEqual(st.mod.patterns[0].rows[0][0].param, 0x40)
        self.transform(st, 'transpose', [dict(pattern=1, cols=[[0, ['note']]])], semitones=2)
        self.assertEqual(st.song['score']['patterns']['b']['beats'][0]['notes'][0]['pitch'], 66)

    def test_http_and_agent_share_transaction_revision_and_approved_channel_guard(self):
        import json
        from tests.test_gui import TestGui
        st = self.state(self.native_song())
        port, stop = TestGui.serve(self, st)
        self.addCleanup(stop)
        body = dict(action='volume', volume=21, revision=st.text_sha(),
                    selections=[dict(pattern=0, r0=0, r1=0, cols=[[0, ['volume']]])])
        status, _, payload = TestGui.fetch(port, '/api/transform', json.dumps(body).encode(),
                                           **{'Content-Type': 'application/json'})
        self.assertEqual(status, 200, payload)
        self.assertEqual(json.loads(payload)['revision'], st.text_sha())
        self.assertEqual(st.song['score']['patterns']['a']['beats'][0]['notes'][0]['volume'], 21)
        result = agent.run(st, 'transform_patterns', dict(action='amplify', percent=200,
            revision=st.text_sha(), selections=[dict(pattern='a', from_row=0, to_row=0, channels=[1])]))
        self.assertTrue(result.get('ok'), result)
        self.assertEqual(st.song['score']['patterns']['a']['beats'][0]['notes'][0]['volume'], 42)
        self.assertEqual(len(st.history), 2)
        st.song['module']['channels'][0]['approved'] = True
        before = st.song_path.read_bytes(), len(st.history)
        result = agent.run(st, 'transform_patterns', dict(action='transpose', semitones=1,
            revision=st.text_sha(), selections=[dict(pattern='a')]))
        self.assertIn('approved', result['error'])
        self.assertEqual((st.song_path.read_bytes(), len(st.history)), before)


class TestNativePatternClipboard(unittest.TestCase):
    setUp = TestNativePlaybackPreparation.setUp
    native_song = TestNativePlaybackPreparation.native_song

    def state(self, song):
        return TestPreparedPlaybackBundle.state(self, song)

    def capture(self, st, selection=None, cut=False, **kwargs):
        return st.pattern_clipboard(dict(revision=st.text_sha(), cut=cut,
            selection=selection or dict(pattern=0, r0=0, r1=2,
                cols=[[0, ['note', 'instrument', 'volume', 'effect']]], occurrence='first')), **kwargs)

    def paste(self, st, clip, row=12, channel=0, **kwargs):
        return st.paste_pattern_clipboard(dict(revision=st.text_sha(), pattern=1,
            row=row, channel=channel, occurrence='second', clipboard=clip), **kwargs)

    def test_mixed_partial_chord_cut_paste_fresh_ids_immutable_clipboard_and_reopen(self):
        song = self.native_song()
        song['patterns']['a']['data'] = '00: ... .. ... X40\n'
        beat = song['score']['patterns']['a']['beats'][0]
        beat['notes'].append(dict(id='neighbor', pitch=60, string=2, fret=1))
        st = self.state(song)
        original = copy.deepcopy(st.song)
        clip = self.capture(st, cut=True)['clipboard']
        frozen = copy.deepcopy(clip)
        self.assertEqual(st.song['score']['patterns']['a']['beats'][0]['notes'], [beat['notes'][1]])
        self.assertFalse(st.mod.patterns[0].rows[0][0].effect)
        self.assertEqual(len(st.history), 1)
        self.paste(st, clip)
        first = st.song['score']['patterns']['b']['beats'][-1]
        self.assertEqual(first['at'], [14, 13])
        self.assertEqual(first['written'], beat['written'])
        self.assertEqual(first['notes'][0]['string'], 1)
        self.assertEqual(first['notes'][0]['instrument'], 1)
        self.assertEqual(st.mod.patterns[1].rows[12][0].param, 0x40)
        self.paste(st, clip, row=24)
        second = st.song['score']['patterns']['b']['beats'][-1]
        self.assertNotEqual(first['id'], second['id'])
        self.assertNotEqual(first['notes'][0]['id'], second['notes'][0]['id'])
        st.score_edit(dict(op='note_set', pattern='b', beat=first['id'],
                          note=dict(id=first['notes'][0]['id'], fret=2), revision=st.text_sha()))
        self.assertEqual(clip, frozen)
        self.assertEqual(second['notes'][0]['pitch'], 64)
        st.close()
        reopened = gui.State(st.song_path, headless=True)
        self.addCleanup(reopened.close)
        self.assertIsNone(reopened.error)
        for _ in range(4):
            reopened.undo()
        self.assertEqual(reopened.song, original)

    def test_exact_cursor_copy_can_paste_fractionally_without_copying_neighbor_controls(self):
        song = self.native_song()
        song['patterns']['a']['data'] = '00: ... .. ... X40\n'
        st = self.state(song)
        clip = self.capture(st, dict(pattern=0, notes=['e'], cols=[[0, ['note', 'instrument']]]))['clipboard']
        self.assertEqual(clip['origin'], [12, 13])
        self.assertEqual(clip['raw'], [])
        self.paste(st, clip, row=[120, 13], channel=1)
        note = st.song['score']['patterns']['b']['beats'][-1]['notes'][0]
        self.assertEqual(note['channel'], 1)
        self.assertEqual(note['string'], 1)
        self.assertEqual(st.song['score']['patterns']['b']['beats'][-1]['at'], [10, 13])
        self.assertFalse(any(c.effect for row in st.mod.patterns[1].rows for c in row))

    def test_partial_chord_paste_joins_matching_beat_and_field_masks_do_not_copy_note(self):
        song = self.native_song()
        source = song['score']['patterns']['a']['beats'][0]
        destination = copy.deepcopy(source)
        destination.update(id='target', at=[14, 13])
        destination['notes'] = [dict(id='neighbor', pitch=60, string=2, fret=1)]
        song['score']['patterns']['b']['beats'] = [destination]
        st = self.state(song)
        clip = self.capture(st)['clipboard']
        self.paste(st, clip)
        self.assertEqual(len(st.song['score']['patterns']['b']['beats']), 1)
        self.assertEqual(len(st.song['score']['patterns']['b']['beats'][0]['notes']), 2)
        st.undo()
        st.score_edit(dict(op='note_set', pattern='a', beat='chord', note=dict(id='e', volume=25),
                          revision=st.text_sha()))
        volume = self.capture(st, dict(pattern=0, notes=['e'], cols=[[0, ['volume']]]))['clipboard']
        self.paste(st, volume, row=[168, 13], channel=1)
        actual = st.song['score']['patterns']['b']['beats'][0]['notes'][0]
        self.assertEqual(actual['pitch'], 60)
        self.assertEqual(actual['volume'], 25)
        self.assertEqual(len(st.song['score']['patterns']['b']['beats'][0]['notes']), 1)

    def test_internal_ties_copy_but_external_ties_and_occupied_paste_refuse(self):
        song = self.native_song()
        a = song['score']['patterns']['a']['beats'][0]
        a['at'], a['written'] = [0, 1], dict(value=8, dots=0, tuplet=[1, 1])
        b = copy.deepcopy(a)
        b['id'], b['at'], b['notes'][0]['id'] = 'next', [1, 2], 'f'
        song['score']['patterns']['a']['beats'].append(b)
        song['score']['ties'] = [dict(**{'from': dict(occurrence='first', note='e')},
                                    to=dict(occurrence='first', note='f'))]
        st = self.state(song)
        before = st.song_path.read_bytes(), len(st.history)
        with self.assertRaisesRegex(ValueError, 'tie'):
            self.capture(st, cut=True)
        self.assertEqual((st.song_path.read_bytes(), len(st.history)), before)
        clip = self.capture(st, dict(pattern=0, r0=0, r1=11,
            cols=[[0, ['note', 'instrument', 'volume']]], occurrence='first'))['clipboard']
        self.paste(st, clip)
        self.assertEqual(len(st.song['score']['ties']), 2)
        self.assertEqual(st.song['score']['ties'][-1]['from']['occurrence'], 'second')
        before = st.song_path.read_bytes(), len(st.history)
        with self.assertRaisesRegex(ValueError, 'occupied'):
            self.paste(st, clip)
        self.assertEqual((st.song_path.read_bytes(), len(st.history)), before)

    def test_cut_stale_write_failure_and_approval_refuse_without_clipboard_publication(self):
        st = self.state(self.native_song())
        before = st.song_path.read_bytes(), len(st.history)
        with patch.object(st, 'write_song', side_effect=OSError('cut write failed')):
            with self.assertRaisesRegex(OSError, 'cut write failed'):
                self.capture(st, cut=True)
        self.assertEqual((st.song_path.read_bytes(), len(st.history)), before)
        with self.assertRaisesRegex(ValueError, 'changed'):
            st.pattern_clipboard(dict(revision='stale', cut=True,
                selection=dict(pattern=0, cols=[[0, ['note']]])))
        st.song['patterns']['a']['approved'] = True
        self.assertTrue(self.capture(st)['clipboard'])
        with self.assertRaisesRegex(ValueError, 'approved'):
            self.capture(st, cut=True)
        self.assertEqual((st.song_path.read_bytes(), len(st.history)), before)

    def test_raw_fractional_destination_and_agent_approved_channel_guard(self):
        song = self.native_song()
        song['patterns']['a']['data'] = '00: ... .. ... X40\n'
        st = self.state(song)
        clip = self.capture(st)['clipboard']
        before = st.song_path.read_bytes(), len(st.history)
        with self.assertRaisesRegex(ValueError, 'integral'):
            self.paste(st, clip, row=[120, 13])
        st.song['module']['channels'][0]['approved'] = True
        with self.assertRaisesRegex(ValueError, 'approved'):
            self.paste(st, clip, who='agent', guard=agent._edit_guard(st))
        self.assertEqual((st.song_path.read_bytes(), len(st.history)), before)

    def test_http_copy_cut_paste_revision_and_failed_paste_leave_one_history_step(self):
        import json
        from tests.test_gui import TestGui
        st = self.state(self.native_song())
        port, stop = TestGui.serve(self, st)
        self.addCleanup(stop)
        def post(action, body):
            status, _, data = TestGui.fetch(port, '/api/' + action, json.dumps(body).encode(),
                                            **{'Content-Type': 'application/json'})
            return status, json.loads(data)
        status, copied = post('pattern_copy', dict(revision=st.text_sha(), cut=True,
            selection=dict(pattern=0, notes=['e'], cols=[[0, ['note', 'instrument', 'volume']]])))
        self.assertEqual(status, 200, copied)
        self.assertEqual(copied['revision'], st.text_sha())
        self.assertEqual(len(st.history), 1)
        payload = dict(revision=copied['revision'], pattern=1, row=[120, 13], channel=0,
                       clipboard=copied['clipboard'])
        with patch.object(st, 'write_song', side_effect=OSError('paste write failed')):
            with self.assertRaisesRegex(OSError, 'paste write failed'):
                st.paste_pattern_clipboard(payload)
        self.assertEqual(len(st.history), 1)
        status, pasted = post('pattern_paste', payload)
        self.assertEqual(status, 200, pasted)
        self.assertEqual(pasted['revision'], st.text_sha())
        self.assertEqual(len(st.history), 2)
        status, stale = post('pattern_paste', payload)
        self.assertEqual(status, 400, stale)
        self.assertEqual(len(st.history), 2)


class TestPreparedPlaybackBundle(unittest.TestCase):
    setUp = TestNativePlaybackPreparation.setUp
    native_song = TestNativePlaybackPreparation.native_song

    def state(self, song):
        path = self.base / 'song.yaml'
        path.write_bytes(api.to_yaml(song).encode())
        state = gui.State(path, headless=True)
        self.addCleanup(state.close)
        return state

    def legacy_song(self):
        song = score_song()
        del song['score']
        song['patterns']['a']['data'] = '00: C-5 01 v32 X40\n'
        song['patterns']['b']['data'] = '00: D-5 01 v24 ...\n'
        song['instruments'] = {1: {'sample': 1}}
        return song

    def test_exact_pair_and_requested_rate_keep_standalone_compile_strict(self):
        song = self.native_song()
        state = self.state(song)
        self.assertIsNone(state.error)
        original = state.song_path.read_bytes()
        for rate in (48000, 96000):
            expected = api.prepare_playback(song, self.base, rate)
            bundle = state.prepared_playback(rate, whole=True)
            self.assertEqual(bundle['sample_rate'], rate)
            self.assertEqual(bundle['plan']['sample_rate'], rate)
            self.assertEqual(bundle['plan'], expected['plan'])
            self.assertEqual(bundle['backing_it'], expected['backing_it'])
            self.assertEqual(bundle['revision'], state.text_sha())
            self.assertEqual(bundle['song'], str(state.song_path))
            self.assertEqual(bundle['gain'], 1)
        self.assertIsNone(state.error)
        self.assertIsNotNone(state.mod.native_score)
        self.assertIsNone(state.it)
        self.assertEqual(state.song_path.read_bytes(), original)
        with self.assertRaises(SongError):
            state.compiled_it(whole=True)
        state.meta['orders'] = [0, 1]
        bundle = state.prepared_playback(48000)
        self.assertEqual(bundle['snapshot']['seek'], (0, 0))
        self.assertEqual(bundle['snapshot']['end'], (1, 0))
        self.assertEqual(bundle['plan']['sample_rate'], 48000)

    def test_legacy_mix_candidate_selection_and_match_gain_are_preserved(self):
        from vulturetracker import measure
        from vulturetracker.openmpt import LoadedModule
        state = self.state(self.legacy_song())
        state.set_mix({'volume': {'0': 31}, 'pan': {'0': 8}, 'mix_volume': 80,
                       'sample_volume': {'1': 40}, 'instrument': {'1': {'cutoff': 12, 'attack': 4}}})
        state.meta['muted'] = [1]
        live = state.live_it()
        bundle = state.prepared_playback(48000, whole=True)
        self.assertIsNone(bundle['plan'])
        self.assertEqual(bundle['backing_it'], live)
        with LoadedModule(live, 48000, 1) as old, LoadedModule(bundle['backing_it'], 48000, 1) as new:
            self.assertEqual(old.render(48000, oversample=1, max_seconds=.05),
                             new.render(48000, oversample=1, max_seconds=.05))
        candidate = self.base / 'candidate.wav'
        write_wav(candidate, RATE, [sine(330, amp=1000)])
        state.meta['orders'], state.meta['match_level'] = [1, 2], True
        original = state.song_path.read_bytes()
        with patch.object(state, 'match_db', return_value=6):
            candidate_bundle = state.prepared_playback(88200, str(candidate))
        expected = measure.patch_it(state.compiled_it(str(candidate)), state.silenced(), state.mix())
        expected, gain = measure.match_level(expected, state.slot, 6)
        self.assertEqual(candidate_bundle['backing_it'], expected)
        self.assertEqual(candidate_bundle['gain'], gain)
        self.assertGreater(gain, 1)
        self.assertEqual(state.song_path.read_bytes(), original)

    def test_cache_tracks_revision_mix_rate_and_fresh_sample_stamps(self):
        state = self.state(self.legacy_song())
        with patch.object(api, 'prepare_playback', wraps=api.prepare_playback) as prepare:
            first = state.prepared_playback(48000, whole=True)
            self.assertEqual(state.prepared_playback(48000, whole=True), first)
            self.assertEqual(prepare.call_count, 1)
            second = state.prepared_playback(96000, whole=True)
            self.assertNotEqual(second['key'], first['key'])
            state.meta['mix'] = {'volume': {'0': 17}}
            mixed = state.prepared_playback(48000, whole=True)
            self.assertEqual(mixed['backing_it'][0x80], 17)
            self.assertNotEqual(mixed['key'], first['key'])
            self.assertEqual(mixed['revision'], first['revision'])
            state._stamps = 'obsolete snapshot stamps'
            write_wav(self.base / 'tone.wav', RATE, [sine(440, seconds=.2)])
            changed_sample = state.prepared_playback(48000, whole=True)
            self.assertNotEqual(changed_sample['key'], mixed['key'])
            self.assertNotEqual(changed_sample['backing_it'], mixed['backing_it'])
            state._stamps = None
            state.song_path.write_bytes(('# New source revision\n' + state.text).encode())
            state.reload()
            revised = state.prepared_playback(48000, whole=True)
            self.assertNotEqual(revised['revision'], first['revision'])
            self.assertNotEqual(revised['key'], changed_sample['key'])
        native = self.state(self.native_song())
        bundle = native.prepared_playback(48000, whole=True)
        bundle['plan']['events'][0]['frame'] = -1
        self.assertGreaterEqual(native.prepared_playback(48000, whole=True)['plan']['events'][0]['frame'], 0)

    def test_changes_during_preparation_are_rejected_without_caching_partial_pair(self):
        state = self.state(self.legacy_song())
        prepare = api.prepare_playback
        for change in ('mix', 'sample'):
            def during(*args, **kwargs):
                result = prepare(*args, **kwargs)
                if change == 'mix':
                    state.meta['mix'] = {'volume': {'0': 19}}
                else:
                    write_wav(self.base / 'tone.wav', RATE, [sine(550, seconds=.25)])
                return result
            with self.subTest(change=change), patch.object(api, 'prepare_playback', side_effect=during):
                with self.assertRaisesRegex(ValueError, 'changed during preparation'):
                    state.prepared_playback(48000, whole=True)
            self.assertFalse(state.prepared)
        self.assertEqual(state.prepared_playback(48000, whole=True)['backing_it'][0x80], 19)

    def test_playback_endpoint_is_authenticated_and_returns_one_rate_bound_pair(self):
        import base64
        import json
        from tests.test_gui import TestGui
        state = self.state(self.native_song())
        port, stop = TestGui.serve(self, state)
        self.addCleanup(stop)
        path = '/api/playback?sample_rate=96000'
        self.assertEqual(TestGui.fetch(port, path, **{'X-VT-Token': ''})[0], 401)
        self.assertEqual(TestGui.fetch(port, path, Origin='http://foreign.example')[0], 403)
        for query in ('', '?sample_rate=0', '?sample_rate=48000.0', '?sample_rate=48000&sample_rate=96000'):
            self.assertEqual(TestGui.fetch(port, '/api/playback' + query)[0], 400)
        status, headers, body = TestGui.fetch(port, path)
        self.assertEqual(status, 200)
        self.assertIn('application/json', headers['Content-Type'])
        wire = json.loads(body)
        bundle = state.prepared_playback(96000, whole=True)
        self.assertEqual(base64.b64decode(wire.pop('backing_it')), bundle.pop('backing_it'))
        self.assertEqual(wire, bundle)
        self.assertEqual(wire['sample_rate'], wire['plan']['sample_rate'])


class TestNativeStateBackend(unittest.TestCase):
    setUp = TestNativePlaybackPreparation.setUp
    native_song = TestNativePlaybackPreparation.native_song
    state = TestPreparedPlaybackBundle.state

    def test_pitch_controls_do_not_retrigger_sounding_or_instrument_memory(self):
        song = self.native_song()
        beat = song['score']['patterns']['a']['beats'][0]
        beat['at'], beat['written'] = [0, 1], {'value': 4}
        beat['notes'][0].update(staccato=True, vibrato=True,
                               bend={'points': [{'position': 0, 'value': 0}, {'position': 12, 'value': 4}]})
        song['score']['patterns']['b']['beats'] = []
        song['patterns']['a']['data'] = ''.join(
            f"{r:02d}: {'C-5 .. ... ...' if r == 18 else '... .. ... ...'}\n" for r in range(48))
        st = self.state(song)
        self.assertIsNone(st.error)
        mod = st.mod
        mod.samples[0].loop = (0, mod.samples[0].length)
        self.assertTrue(any(e['type'] == 'pitch' for e in mod.native_score['plan']['events']))
        # A late pitch reset must not resurrect a released note, even when it
        # carries the note's identity and follows the release at the same time.
        control = copy.deepcopy(next(e for e in mod.native_score['plan']['events'] if e['type'] == 'pitch'))
        control['at'] = [3, 4]
        mod.native_score['plan']['events'].append(control)
        baseline = copy.deepcopy(mod)
        baseline.native_score['plan']['events'] = [
            e for e in baseline.native_score['plan']['events'] if e['type'] != 'pitch']
        self.assertEqual(gui.native_actions(mod), gui.native_actions(baseline))
        table = gui.native_sounding_table(mod)
        self.assertEqual(table, gui.native_sounding_table(baseline))
        self.assertEqual(next(s['ago'] for s in table[0][4] if s['ch'] == 0), 4)
        self.assertFalse(any(s['ch'] == 0 for s in table[0][9]))
        inherited = next(s for s in table[0][18] if s['ch'] == 0)
        self.assertEqual((inherited['sample'], inherited['ago']), (1, 0))

    def test_gate_edit_preserves_written_score_clipboard_undo_and_reopen(self):
        from vulturetracker import tablature
        st = self.state(self.native_song())
        before = copy.deepcopy(st.song)
        st.score_edit(dict(op='note_set', pattern='a', beat='chord', note=dict(id='e', staccato=True),
                           revision=st.text_sha()))
        after = copy.deepcopy(st.song)
        beat = after['score']['patterns']['a']['beats'][0]
        self.assertEqual(beat['written'], before['score']['patterns']['a']['beats'][0]['written'])
        view = st.score_view()
        position = next(p for p in view['positions'] if p.get('note') == 'e')
        self.assertEqual(position['gate_effect'], 'staccato')
        self.assertLess(Fraction(*position['sounding_end']), Fraction(*position['end']))
        clipboard = tablature.capture_score_clipboard(st.song, 'a', ['chord'], 'first')
        self.assertTrue(clipboard['beats'][0]['notes'][0]['staccato'])
        self.assertEqual(len(st.history), 1)
        st.undo()
        self.assertEqual(st.song['score'], before['score'])
        st.undo(redo=True)
        self.assertEqual(st.song['score'], after['score'])
        path = st.song_path
        st.close()
        reopened = gui.State(path, headless=True)
        self.addCleanup(reopened.close)
        self.assertIsNone(reopened.error)
        self.assertEqual(reopened.song['score'], after['score'])

    def test_offgrid_state_fret_undo_reopen_and_exact_views(self):
        st = self.state(self.native_song())
        self.assertIsNone(st.error)
        self.assertIsNone(st.it)
        self.assertTrue(st.facts['native_score'])
        self.assertEqual(st.facts['duration'], 4)
        self.assertEqual(st.facts['orders'][0]['occurrence'], 'first')
        self.assertEqual(st.facts['use'][0][0], [1])
        self.assertEqual(st.unused()['samples'], [])
        view = st.pattern_rows(0, 'first')
        note = next(p for p in view['positions'] if p['kind'] == 'note')
        self.assertEqual(note['row'], [12, 13])
        self.assertEqual(note['duration'], [7, 104])
        self.assertTrue(all(c.note is None for row in st.mod.patterns[0].rows for c in row))
        with self.assertRaisesRegex(ValueError, 'occurrence'):
            st.pattern_rows(0)
        original = copy.deepcopy(st.song)
        st.score_edit({'op': 'note_set', 'pattern': 'a', 'beat': 'chord', 'note': {'id': 'e', 'fret': 3},
                       'revision': st.text_sha()})
        self.assertEqual(st.song['score']['patterns']['a']['beats'][0]['notes'][0]['pitch'], 67)
        self.assertEqual(len(st.history), 1)
        self.assertEqual(st.song['score']['patterns']['a']['beats'][0]['at'], [1, 13])
        st.undo()
        self.assertEqual(st.song, original)
        st.undo(redo=True)
        saved = copy.deepcopy(st.song)
        st.close()
        reopened = gui.State(st.song_path, headless=True)
        self.addCleanup(reopened.close)
        self.assertIsNone(reopened.error)
        self.assertEqual(reopened.song, saved)
        self.assertIsNone(reopened.it)

    def test_native_edit_failures_preserve_file_history_mix_and_model(self):
        st = self.state(self.native_song())
        st.meta['mix'] = {'volume': {'0': 23}}
        before = (st.song_path.read_bytes(), copy.deepcopy(st.history), copy.deepcopy(st.meta), st.mod)
        edit = {'op': 'note_set', 'pattern': 'a', 'beat': 'chord', 'note': {'id': 'e', 'fret': 3},
                'revision': st.text_sha()}
        with patch.object(st, '_write_step', side_effect=OSError('write refused')):
            with self.assertRaisesRegex(OSError, 'write refused'):
                st.score_edit(edit)
        invalid = copy.deepcopy(st.song['score']['patterns']['a']['beats'][0])
        invalid['at'] = [999, 1]
        with self.assertRaises((SongError, ValueError)):
            st.score_edit({'op': 'beat_set', 'pattern': 'a', 'beat': invalid, 'revision': st.text_sha()})
        with self.assertRaisesRegex(ValueError, 'changed'):
            st.score_edit({**edit, 'revision': 'stale'})
        self.assertEqual((st.song_path.read_bytes(), st.history, st.meta, st.mod), before)

    def test_unsupported_pattern_selection_operations_refuse_before_mutation(self):
        st = self.state(self.native_song())
        before = st.song_path.read_bytes(), copy.deepcopy(st.history), copy.deepcopy(st.meta)
        operations = [
            lambda: st.edit_patterns([(0, [{'row': 1, 'ch': 0, 'cell': 'C-5 01 ... ...'}])],
                                     revision=st.text_sha(), occurrences={0: 'first'}),
            lambda: st.score_edit({'op': 'promote_pattern', 'pattern': 0, 'track': 'guitar',
                                  'revision': st.text_sha()}),
            lambda: st.compose_cells(0, {'op': 'grow'}),
        ]
        for operation in operations:
            with self.assertRaises(ValueError):
                operation()
            self.assertEqual((st.song_path.read_bytes(), st.history, st.meta), before)

    def test_exact_move_resize_and_clipboard_share_native_transaction(self):
        st = self.state(self.native_song())
        def edit(**operation):
            st.score_edit({**operation, 'revision': st.text_sha()})
        edit(op='beat_move', pattern=0, beat='chord', to_row=[24, 13])
        beat = st.song['score']['patterns']['a']['beats'][0]
        self.assertEqual(beat['at'], [2, 13])
        edit(op='beat_resize', pattern=0, beat='chord', end_row=[45, 13])
        from vulturetracker.tablature import duration_quarters
        self.assertEqual(duration_quarters(st.song['score']['patterns']['a']['beats'][0]['written']), Fraction(7, 52))
        edit(op='note_move', pattern=0, note='e', to_row=[36, 13], pitch=65)
        self.assertEqual(st.song['score']['patterns']['a']['beats'][0]['at'], [3, 13])
        clipboard = st.score_clipboard({'pattern': 'a', 'beats': ['chord'], 'occurrence': 'first',
                                       'revision': st.text_sha()})['clipboard']
        before = st.song_path.read_bytes(), list(st.history), list(st.future)
        # Exact native edits remain possible; Copy/Paste promises standalone IT
        # and must refuse this existing nonintegral-tick song without rounding.
        with self.assertRaisesRegex(SongError, 'not representable'):
            edit(op='beats_paste', pattern=0, row=[120, 13], clipboard=clipboard, occurrence='first')
        self.assertEqual((st.song_path.read_bytes(), list(st.history), list(st.future)), before)
        self.assertEqual(len(st.history), 3)
        st.undo()
        self.assertEqual(st.song['score']['patterns']['a']['beats'][0]['at'], [2, 13])

    def test_pattern_http_context_edits_and_revision_lineage(self):
        import json
        from tests.test_gui import TestGui
        st = self.state(self.native_song())
        port, stop = TestGui.serve(self, st)
        self.addCleanup(stop)
        status, _, data = TestGui.fetch(port, '/api/pattern/1?occurrence=second')
        self.assertEqual(status, 200)
        view = json.loads(data)
        self.assertEqual(view['occurrence'], 'second')
        self.assertTrue(view['positions'])
        self.assertNotEqual(view['rows'][42][0], view['display_rows'][42][0])
        old = st.text_sha()
        def post(revision, cell):
            body = json.dumps({'pattern': 1, 'occurrence': 'second', 'revision': revision,
                               'cells': [{'row': 42, 'ch': 0, 'cell': cell}]}).encode()
            status, _, payload = TestGui.fetch(port, '/api/edit', body, **{'Content-Type': 'application/json'})
            return status, json.loads(payload)
        status, response = post(old, 'F-5 01 ... V40')
        self.assertEqual(status, 200, response)
        self.assertEqual(response['revision'], st.text_sha())
        self.assertNotEqual(response['revision'], old)
        self.assertEqual(st.song['score']['patterns']['b']['beats'][0]['notes'][0]['pitch'], 65)
        self.assertIsNone(st.mod.patterns[1].rows[42][0].note)
        self.assertEqual(st.mod.patterns[1].rows[42][0].effect, 22)
        before = st.song_path.read_bytes(), len(st.history)
        self.assertEqual(post(old, 'G-5 01 ... V40')[0], 400)
        self.assertEqual((st.song_path.read_bytes(), len(st.history)), before)
        status, response = post(response['revision'], 'G-5 01 ... V40')
        self.assertEqual(status, 200, response)
        self.assertEqual(response['revision'], st.text_sha())

    def test_whole_tryout_worker_and_meters_render_the_native_pair(self):
        import queue
        import wave
        from vulturetracker import measure
        from vulturetracker.openmpt import LoadedModule
        st = self.state(self.native_song())
        st.meta['mix'] = {'volume': {'0': 23}, 'pan': {'0': 8}}
        st.cache_dir.mkdir(exist_ok=True)
        st.jobs = queue.PriorityQueue()
        key = st.key()
        st.renders = {key: {'status': 'queued'}}
        st._put(1, (key, None))
        st._put(9, ('close',))
        st._worker()
        self.assertEqual(st.renders[key]['status'], 'ready', st.renders[key])
        with wave.open(st.renders[key]['file'], 'rb') as rendered:
            actual = rendered.readframes(rendered.getnframes())
        bundle = st.prepared_playback(measure.RATE * 2)
        with LoadedModule(bundle['backing_it'], rate=measure.RATE, oversample=2, plan=bundle['plan']) as lm:
            expected = lm.render(measure.RATE)
        self.assertEqual(actual, expected)
        self.assertTrue(any(actual))
        mk = st.meter_key()
        st.meters = {'key': mk, 'status': 'queued', 'mix': st.mix()}
        st._meters(mk)
        self.assertEqual(st.meters['status'], 'ready', st.meters)
        self.assertGreater(st.meters['levels'][0]['db'], -100)
        self.assertEqual(st.meters['levels'][1]['db'], -120)

    def test_selected_tryout_meter_rows_and_agent_measure_reuse_export_snapshot(self):
        import queue
        import wave
        from vulturetracker import export, measure
        write_wav(self.base / 'tone.wav', RATE, [sine(220, seconds=1)])
        song = score_song()
        song['patterns']['a']['data'] = ''
        st = self.state(song)
        original = st.song_path.read_bytes()
        st.meta['orders'] = [1, 2]  # Starts during the cross-pattern tie.
        st.meta['mix'] = {'volume': {'0': 27}, 'pan': {'0': 8}}
        bundle = st.prepared_playback(48000)
        expected = export.render(export.snapshot(st.song, st.base_dir, region=(1, 0, 1, 47),
                                                 mix=st.mix(), tail=0))
        self.assertEqual(export.render(bundle['snapshot']), expected)
        self.assertTrue(any(expected[:44100]))  # The inherited tied voice plays at the selected start.
        st.cache_dir.mkdir(exist_ok=True)
        st.jobs = queue.PriorityQueue()
        key = st.key()
        st.renders = {key: {'status': 'queued'}}
        st._put(1, (key, None))
        st._put(9, ('close',))
        st._worker()
        self.assertEqual(st.renders[key]['status'], 'ready', st.renders[key])
        with wave.open(st.renders[key]['file'], 'rb') as rendered:
            self.assertEqual(rendered.readframes(rendered.getnframes()), expected)
        pcm, seconds = st.render_rows(1, 0, 47, tail=0)
        self.assertEqual(pcm, expected)
        self.assertEqual(seconds, 2)
        mk = st.meter_key()
        st.meters = {'key': mk, 'status': 'queued', 'mix': st.mix()}
        st._meters(mk)
        self.assertEqual(st.meters['status'], 'ready', st.meters)
        self.assertGreater(st.meters['levels'][0]['db'], -100)
        self.assertEqual(st.meters['levels'][1]['db'], -120)
        result = agent.run(st, 'measure', {'orders': [1, 2]})
        self.assertNotIn('error', result)
        self.assertEqual([o['order'] for o in result['per_order']], [1])
        self.assertEqual(st.song_path.read_bytes(), original)
        st.set_loop({'from': [1, 0], 'to': [1, 5]})
        self.assertEqual(st.meta['loop'], {'from': [1, 0], 'to': [1, 5]})

    def test_selected_render_to_slot_is_one_undo_and_retains_score(self):
        st = self.state(self.native_song())
        original = copy.deepcopy(st.song['score'])
        st.song_edit([dict(op='render_sample', order=0, r0=0, r1=4, chans=[0], tail=0)])
        self.assertEqual(st.song['score'], original)
        self.assertEqual(len(st.history), 1)
        self.assertEqual(len(st.song['samples']), 2)
        rendered = st.base_dir / st.song['samples'][2]['file']
        self.assertTrue(rendered.is_file())
        st.undo()
        self.assertEqual(st.song['score'], original)
        self.assertEqual(len(st.song['samples']), 1)

    def test_raw_inheritance_after_score_and_unused_authored_voice_references(self):
        song = self.native_song()
        song['samples'][2] = dict(song['samples'][1], name='Raw inherited')
        song['samples'][3] = dict(song['samples'][1], name='Unused score')
        song['score']['patterns']['a']['beats'][0]['notes'][0]['instrument'] = 2
        song['patterns']['a']['data'] = ''.join(f'{r:02d}: ... .. ... ...\n' for r in range(12)) + '12: C-5 .. ... ...\n'
        song['patterns']['unused'] = {'rows': 48, 'data': ''}
        unused = copy.deepcopy(song['score']['patterns']['a'])
        unused['beats'][0]['notes'][0]['instrument'] = 3
        song['score']['patterns']['unused'] = unused
        st = self.state(song)
        self.assertIsNone(st.error)
        self.assertEqual(st.facts['use'][0][0], [2])
        sounding = st.sounding(0, 12)
        self.assertEqual(next(s['sample'] for s in sounding if s['ch'] == 0), 2)
        self.assertIn(3, st.unused()['samples'])
        self.assertEqual(gui.voice_references(st.song, st.mod), {1, 2, 3})
        bad = copy.deepcopy(song)
        del bad['samples'][3]
        with self.assertRaisesRegex(SongError, 'missing samples'):
            gui.load_for_state(api.to_yaml(bad), self.base)


class TestNativeAdoptionState(unittest.TestCase):
    setUp = TestNativePlaybackPreparation.setUp
    native_song = TestNativePlaybackPreparation.native_song
    state = TestPreparedPlaybackBundle.state

    def adoption_song(self):
        song = self.native_song()
        song['patterns']['a']['data'] = (
            '00: ... .. ... ... | C-5 01 ... V40\n' +
            ''.join(f'{r:02d}: ... .. ... ...\n' for r in range(1, 4)) +
            '04: ... .. ... ... | === .. ... ...\n')
        return song

    def test_native_adoption_preserves_paired_audio_source_mix_and_undo(self):
        from vulturetracker.openmpt import LoadedModule
        write_wav(self.base / 'tone.wav', RATE, [sine(220, seconds=.5)])
        for instrument_mode, inherited in ((False, False), (True, False), (True, True)):
            song = self.adoption_song()
            if inherited:
                song['patterns']['a']['data'] = (
                    '00: ... .. ... ... | ... 01 ... V40\n'
                    '01: ... .. ... ... | C-5 .. ... ...\n'
                    '02: ... .. ... ...\n03: ... .. ... ...\n'
                    '04: ... .. ... ... | === .. ... ...\n')
            song['samples'][1]['loop'] = {'start': 0, 'end': RATE // 2}
            if instrument_mode:
                song['instruments'] = {1: {'sample': 1, 'nna': 'continue', 'fadeout': 128,
                                          'volume_envelope': {'nodes': [[0, 64], [5, 48], [20, 0]],
                                                              'sustain': [1, 1]}}}
            st = self.state(song)
            self.assertIsNone(st.error)
            st.meta['mix'] = {'volume': {'1': 27}, 'pan': {'1': 8}}
            original, mix = st.song_path.read_bytes(), copy.deepcopy(st.meta['mix'])
            pairs = {rate: st.prepared_playback(rate, whole=True) for rate in (44100, 48000, 88200, 96000)}
            preview = next(p for p in st.score_view()['raw_positions'] if p['ch'] == 1)
            self.assertEqual((preview['occurrence'], preview['end_row']), ('first', [4, 1]))
            st.score_edit({'op': 'promote_pattern', 'pattern': 0, 'track': 'guitar',
                           'cells': [{'row': 1 if inherited else 0, 'ch': 1}], 'occurrence': 'first',
                           'revision': st.text_sha()})
            self.assertFalse(st.score_view()['raw_positions'])
            self.assertEqual(st.meta['mix'], mix)
            self.assertIsNone(st.mod.patterns[0].rows[0][1].note)
            self.assertEqual(st.mod.patterns[0].rows[0][1].effect, 22)
            for rate, before in pairs.items():
                after = st.prepared_playback(rate, whole=True)
                with self.subTest(instruments=instrument_mode, inherited=inherited, rate=rate):
                    with LoadedModule(before['backing_it'], rate, 1, plan=before['plan']) as left:
                        a = left.render(rate, oversample=1, max_seconds=.6)
                    with LoadedModule(after['backing_it'], rate, 1, plan=after['plan']) as right:
                        b = right.render(rate, oversample=1, max_seconds=.6)
                    self.assertEqual(a, b)
                    self.assertTrue(any(a))
            self.assertEqual(len(st.history), 1)
            st.undo()
            self.assertEqual(st.song_path.read_bytes(), original)
            self.assertEqual(st.meta['mix'], mix)
            st.close()

    def test_native_adoption_write_failure_and_approved_source_are_atomic(self):
        st = self.state(self.adoption_song())
        edit = {'op': 'promote_pattern', 'pattern': 0, 'track': 'guitar', 'cells': [{'row': 0, 'ch': 1}],
                'occurrence': 'first', 'revision': st.text_sha()}
        before = st.song_path.read_bytes(), copy.deepcopy(st.history), copy.deepcopy(st.song)
        with patch.object(st, '_write_step', side_effect=OSError('adoption write failed')):
            with self.assertRaisesRegex(OSError, 'adoption write failed'):
                st.score_edit(edit)
        self.assertEqual((st.song_path.read_bytes(), st.history, st.song), before)
        st.song_edit([{'op': 'mark', 'what': 'pattern', 'key': 'a', 'approved': True}])
        before = st.song_path.read_bytes(), len(st.history)
        with self.assertRaisesRegex(ValueError, 'approved'):
            st.score_edit({**edit, 'revision': st.text_sha()})
        self.assertEqual((st.song_path.read_bytes(), len(st.history)), before)

    def test_native_adoption_preserves_qualified_attack_controls_in_parent_batch(self):
        from vulturetracker.openmpt import LoadedModule
        write_wav(self.base / 'tone.wav', RATE, [sine(220, seconds=.5)])
        for command in ('v48 X20', 'v32 M20', 'v64 D07'):
            song = self.adoption_song()
            song['patterns']['a']['data'] = song['patterns']['a']['data'].replace('... V40', command)
            song['samples'][1]['loop'] = {'start': 0, 'end': RATE // 2}
            song['instruments'] = {1: {'sample': 1, 'nna': 'continue', 'fadeout': 128}}
            st = self.state(song)
            self.assertIsNone(st.error)
            before = {rate: st.prepared_playback(rate, whole=True) for rate in (44100, 48000, 88200, 96000)}
            source = copy.copy(st.mod.patterns[0].rows[0][1])
            st.score_edit({'op': 'promote_pattern', 'pattern': 0, 'track': 'guitar', 'occurrence': 'first',
                           'cells': [{'row': 0, 'ch': 1}], 'revision': st.text_sha()})
            retained = st.mod.patterns[0].rows[0][1]
            self.assertEqual((retained.volcmd, retained.effect, retained.param),
                             (source.volcmd, source.effect, source.param))
            self.assertIsNone(retained.note)
            self.assertEqual(retained.instrument, 0)
            for rate, original in before.items():
                after = st.prepared_playback(rate, whole=True)
                with self.subTest(command=command, rate=rate):
                    with LoadedModule(original['backing_it'], rate, 1, plan=original['plan']) as lm:
                        expected = lm.render(rate, oversample=1, max_seconds=.6)
                    with LoadedModule(after['backing_it'], rate, 1, plan=after['plan']) as lm:
                        self.assertEqual(lm.render(rate, oversample=1, max_seconds=.6), expected)
            st.close()

    def test_native_structural_rename_clone_split_channel_move_and_reopen(self):
        st = self.state(self.native_song())
        original = st.song_path.read_bytes()
        st.song_edit([{'op': 'pattern_rename', 'old': 'a', 'new': 'intro'}])
        st.song_edit([{'op': 'channel_move', 'ch': 0, 'to': 2}])
        self.assertEqual(st.mod.native_score['plan']['events'][0]['ch'], 2)
        st.song_edit([{'op': 'pattern_clone', 'src': 'intro', 'name': 'copy'}])
        self.assertEqual(st.song['score']['patterns']['copy'], st.song['score']['patterns']['intro'])
        st.song_edit([{'op': 'pattern_rows', 'name': 'copy', 'rows': 12}])
        self.assertEqual(len(next(p for p in st.mod.patterns if p.name == 'copy').rows), 12)
        st.song_edit([{'op': 'pattern_split', 'pattern': 0, 'row': 12}])
        self.assertEqual(st.song['orders'], ['intro', 'intro_2', 'b'])
        self.assertEqual(st.song['score']['patterns']['intro']['beats'][0]['at'], [1, 13])
        self.assertEqual(len(set(st.song['score']['order_ids'])), 3)
        saved = copy.deepcopy(st.song)
        st.close()
        reopened = gui.State(st.song_path, headless=True)
        self.addCleanup(reopened.close)
        self.assertIsNone(reopened.error)
        self.assertEqual(reopened.song, saved)
        for _ in range(5):
            reopened.undo()
        self.assertEqual(reopened.song_path.read_bytes(), original)

    def test_native_section_duplicate_select_loop_and_undo_are_atomic(self):
        song = self.native_song()
        song['sections'] = {'intro': [0, 1]}
        st = self.state(song)
        st.meta['loop'] = None
        before = st.song_path.read_bytes(), copy.deepcopy(st.meta), len(st.history)
        for action in ('select', 'loop'):
            st.section_edit({'name': 'intro', 'action': action})
            self.assertEqual(st.orders, (0, 1))
            self.assertEqual(st.prepared_playback(88200)['snapshot']['seek'], (0, 0))
            if action == 'loop':
                self.assertEqual(st.meta['loop'], {'from': [0, 0], 'to': [0, 47]})
            st.undo()
            self.assertEqual((st.song_path.read_bytes(), st.meta, len(st.history)), before)
        st.section_edit({'name': 'intro', 'action': 'duplicate', 'to': 2})
        self.assertEqual(st.song['score']['patterns']['a_copy1'], st.song['score']['patterns']['a'])
        self.assertEqual(len(set(st.song['score']['order_ids'])), 3)
        st.undo()
        self.assertEqual((st.song_path.read_bytes(), st.meta, len(st.history)), before)

    def test_native_structural_truncation_and_crossing_split_preserve_source(self):
        st = self.state(self.native_song())
        before = st.song_path.read_bytes(), copy.deepcopy(st.meta), len(st.history)
        for op in ({'op': 'pattern_rows', 'name': 'a', 'rows': 1},
                   {'op': 'pattern_split', 'pattern': 0, 'row': 1},
                   {'op': 'channel_remove', 'ch': 0}):
            with self.subTest(op=op), self.assertRaises(ValueError):
                st.song_edit([op])
            self.assertEqual((st.song_path.read_bytes(), st.meta, len(st.history)), before)

    def test_native_section_copy_preserves_internal_ties_and_measure_anchors(self):
        song = score_song()
        song['patterns']['a']['data'] = ''
        song['sections'] = {'both': [0, 2]}
        song['score']['measures'] = [
            {'id': 'bar', 'from': {'occurrence': 'first', 'at': [0, 1]},
             'to': {'occurrence': 'second', 'at': [0, 1]}, 'meter': [4, 4]}]
        st = self.state(song)
        self.assertIsNone(st.error)
        original = st.song_path.read_bytes()
        st.section_edit({'name': 'both', 'action': 'duplicate', 'to': 2})
        score = st.song['score']
        self.assertEqual(len(score['ties']), 2)
        self.assertEqual(len(score['measures']), 2)
        self.assertEqual(score['ties'][1]['from']['occurrence'], score['order_ids'][2])
        self.assertEqual(score['ties'][1]['to']['occurrence'], score['order_ids'][3])
        self.assertEqual(score['measures'][1]['from']['occurrence'], score['order_ids'][2])
        self.assertEqual(score['measures'][1]['to']['occurrence'], score['order_ids'][3])
        self.assertNotEqual(score['measures'][0]['id'], score['measures'][1]['id'])
        st.undo()
        self.assertEqual(st.song_path.read_bytes(), original)


class TestNativeTempoSeekFrames(unittest.TestCase):
    def test_plan_copies_map_and_seek_rounds_global_piecewise_seconds_without_engine(self):
        from vulturetracker import openmpt as om, tablature as tab
        from tests.test_tablature import plan_fixture
        song, raw = plan_fixture()
        raw[0].rows[12][6].effect, raw[0].rows[12][6].param = 20, 137
        raw[1].rows[0][6].effect, raw[1].rows[0][6].param = 20, 60
        for rate in (44100, 48000, 88200, 96000):
            plan = tab.playback_plan(song, raw, rate)
            module = om.LoadedModule.__new__(om.LoadedModule)
            module._has_groups = False
            module._set_plan(plan, rate)
            clock = tab.TempoClock(plan['tempo'], plan['tempos'])
            for order, row in ((0, 12), (0, Fraction(239, 13)), (1, 0), (1, Fraction(17, 3))):
                at = Fraction(*plan['occurrences'][order]['at']) + row * Fraction(1, 12)
                frames = clock.seconds_at(at) * rate
                expected = (2 * frames.numerator + frames.denominator) // (2 * frames.denominator)
                self.assertEqual(module._native_order_frame(order, row), expected)
            plan['tempos'][1]['bpm'] = 255
            self.assertEqual(module._native_plan['tempos'][1]['bpm'], 137)
            self.assertEqual(module._native_order_frame(2, 0), module._native_end)
            # __del__ must not attempt a native destroy for this scheduler-only object.
            module._mod = module._ext = None


class TestNativeLoadedModule(unittest.TestCase):
    setUp = TestNativePlaybackPreparation.setUp
    native_song = TestNativePlaybackPreparation.native_song

    def test_technique_gates_match_explicit_reference_releases_at_four_rates(self):
        song = self.native_song()
        first = song['score']['patterns']['a']['beats'][0]
        first['at'], first['written'] = [0, 1], {'value': 4}
        song['module']['tempo'] = 120
        song['samples'][1]['sustain_loop'] = {'start': 0, 'end': 512}
        for effect, value in (('staccato', 8), ('palm_mute', 32), ('dead', 64)):
            for rate in (44100, 48000, 88200, 96000):
                with self.subTest(effect=effect, rate=rate):
                    gated, reference = copy.deepcopy(song), copy.deepcopy(song)
                    gated['score']['patterns']['a']['beats'][0]['notes'][0][effect] = True
                    reference['score']['patterns']['a']['beats'][0]['written'] = {'value': value}
                    outputs = []
                    for source in (gated, reference):
                        prepared = api.prepare_playback(source, self.base, rate)
                        with self.native(prepared, rate) as module:
                            outputs.append(module.render(rate, oversample=1, floats=True, max_seconds=1))
                    self.assertEqual(outputs[0], outputs[1])

    def prepared(self, rate=48000):
        return api.prepare_playback(self.native_song(), self.base, rate)

    def native(self, prepared, rate, oversample=1):
        from vulturetracker.openmpt import LoadedModule, OpenMPTError
        try:
            return LoadedModule(prepared['backing_it'], rate, oversample, plan=prepared['plan'])
        except OpenMPTError as exc:
            if 'requires' not in str(exc):
                raise
            # Promotion CI must set VT_REQUIRE_NATIVE_SCORE=1: missing patched binaries then fail, never skip.
            if os.environ.get('VT_REQUIRE_NATIVE_SCORE') == '1':
                self.fail(str(exc))
            self.skipTest(str(exc))

    def test_missing_capability_destroys_extension_and_rate_mismatch_never_allocates(self):
        from vulturetracker import openmpt as om
        prepared = self.prepared()
        module = om.LoadedModule.__new__(om.LoadedModule)
        with patch.object(om.LoadedModule, '_interface', side_effect=om.OpenMPTError('requires vt_tail')):
            with self.assertRaisesRegex(om.OpenMPTError, 'requires vt_tail'):
                module.__init__(prepared['backing_it'], 48000, 1, plan=prepared['plan'])
        self.assertIsNone(module._ext)
        self.assertIsNone(module._mod)
        module.close()  # No double destroy after partial initialization.
        with patch.object(om._lib, 'openmpt_module_ext_create_from_memory') as create:
            with self.assertRaisesRegex(ValueError, 'actual mixer rate'):
                om.LoadedModule(prepared['backing_it'], 48000, 2, plan=prepared['plan'])
        create.assert_not_called()

    def test_missing_context_capability_refuses_before_mixer_initialization(self):
        from vulturetracker import openmpt as om
        prepared = self.prepared()
        plan = copy.deepcopy(prepared['plan'])
        for key, event in enumerate((e for e in plan['events'] if e['type'] == 'note_on'), 1):
            event.update(context=key, context_open=True, context_close=True)
        original = om.LoadedModule._interface
        def interface(module, name, structure):
            if name == b'vt_score_contexts':
                raise om.OpenMPTError('requires vt_score_contexts')
            return original(module, name, structure)
        module = om.LoadedModule.__new__(om.LoadedModule)
        with patch.object(om.LoadedModule, '_interface', interface), patch.object(
                om._lib, 'openmpt_module_read_interleaved_stereo') as read:
            with self.assertRaisesRegex(om.OpenMPTError, 'vt_score_contexts'):
                module.__init__(prepared['backing_it'], 48000, 1, plan=plan)
        read.assert_not_called()
        self.assertIsNone(module._ext)

    def test_consumer_order_identity_inheritance_rate_guards_and_cancellation(self):
        from vulturetracker import openmpt as om
        prepared = self.prepared()
        plan = copy.deepcopy(prepared['plan'])
        # Tighten the consumer schedule only; engine correctness is exercised with actual preparation below.
        for event, frame in zip(plan['events'], (0, 2, 2, 4)):
            event['frame'] = frame
            event['source_instrument'] = 0
            event['volume'] = None
        plan['duration']['frames'] = 4
        calls, serial = [], iter((2**60 + 1, 2**60 + 2))
        def dispatch(ext, rate, off_count, offs, note_count, notes, identities):
            calls.append(('batch', off_count, note_count))
            for i in range(off_count):
                calls.append(('off', offs[i]))
            for i in range(note_count):
                handle = next(serial)
                calls.append(('on', notes[i * 4 + 2], notes[i * 4 + 3], handle))
                identities[i] = handle
            return 1
        interfaces = [SimpleNamespace(configure=lambda *args: 1),
                      SimpleNamespace(dispatch=dispatch),
                      SimpleNamespace(begin=lambda *args: calls.append(('tail',)) or 1)]
        with patch.object(om.LoadedModule, '_interface', side_effect=interfaces):
            with om.LoadedModule(prepared['backing_it'], 48000, 1, plan=plan) as module:
                plan['events'][0]['source_instrument'] = 99  # The paired schedule was captured at creation.
                with self.assertRaisesRegex(ValueError, 'actual mixer rate'):
                    module.render(44100, oversample=1)
                with self.assertRaisesRegex(ValueError, 'repeat'):
                    module.render(48000, repeat=-2, oversample=1)
                with self.assertRaisesRegex(ValueError, 'seek'):
                    module.order_start(999)
                with self.assertRaisesRegex(ValueError, 'row scanning'):
                    module.row_starts()
                out = module.render(48000, oversample=1, max_seconds=4 / 48000)
                self.assertEqual(len(out), 4 * 4)
                self.assertEqual(module._handles, {})
                self.assertEqual(len(module.render(48000, oversample=1, max_seconds=2 / 48000)), 2 * 4)
        self.assertEqual(calls, [('batch', 0, 1), ('on', 0, -1, 2**60 + 1),
                                ('batch', 1, 1), ('off', 2**60 + 1), ('on', 0, -1, 2**60 + 2),
                                ('tail',), ('batch', 1, 0), ('off', 2**60 + 2)])
        for answers in ((True,), (False, True)):
            serial = iter((2**60 + 3,))
            cancelled = iter(answers)
            with patch.object(om.LoadedModule, '_interface', side_effect=interfaces):
                with om.LoadedModule(prepared['backing_it'], 48000, 1, plan=prepared['plan']) as module:
                    with self.assertRaisesRegex(ValueError, 'Export cancelled'):
                        module.render(48000, oversample=1, cancel=lambda: next(cancelled))
                    self.assertEqual(module._native_frame, 0 if len(answers) == 1 else prepared['plan']['events'][0]['frame'])
            self.assertIsNone(module._ext)

    def test_actual_prepared_fractional_onsets_releases_float_and_int_tail(self):
        import numpy as np
        # A sustained DC sample makes both releases observable without confusing a finished one-shot with key-off.
        write_wav(self.base / 'tone.wav', 48000, [[10000] * 128 + [0] * 128])
        song = self.native_song()
        song['module']['tempo'] = 137
        song['samples'][1]['sustain_loop'] = {'start': 0, 'end': 128}
        with self.native(api.prepare_playback(song, self.base, 48000), 48000):
            pass  # Refuse/skip once, outside the per-rate subtests, when the loaded library is unpatched.
        for rate in (44100, 48000, 88200, 96000):
            prepared = api.prepare_playback(song, self.base, rate)
            events = prepared['plan']['events']
            end = prepared['plan']['duration']['frames']
            for floats in (False, True):
                with self.subTest(rate=rate, floats=floats), self.native(prepared, rate) as module:
                    pcm = module.render(rate, oversample=1, floats=floats, max_seconds=(end + 2048) / rate)
                    x = np.frombuffer(pcm, '<f4' if floats else '<i2').reshape(-1, 2)
                    self.assertEqual(len(x), end + 2048)
                    on, off, second, final = (event['frame'] for event in events)
                    self.assertFalse(np.any(x[:on]))
                    self.assertTrue(np.any(x[on:on + 512]))
                    self.assertFalse(np.any(x[off + 1024:second]))
                    self.assertTrue(np.any(x[second:final]))
                    self.assertFalse(np.any(x[final + 1024:]))
                    self.assertTrue(module._in_tail)
                    self.assertEqual(module._event_index, len(events))
                    self.assertEqual(module._handles, {})

    def test_actual_oversampling_uses_plan_mixer_rate_and_existing_decimator(self):
        prepared = self.prepared(96000)
        with self.native(prepared, 48000, 2) as module:
            pcm = module.render(48000, oversample=2, max_seconds=0.25, floats=True)
        self.assertEqual(len(pcm), 12000 * 8)

    def test_native_repeat_restarts_both_streams_at_the_exact_arrangement_boundary(self):
        prepared = self.prepared(48000)
        end = prepared['plan']['duration']['frames']
        with self.native(prepared, 48000) as reference:
            first = reference.render(48000, oversample=1, floats=True, max_seconds=(end + 0.25) / 48000)
            tail = reference.render(48000, oversample=1, floats=True, max_seconds=2048 / 48000)
        for repeat in (1, 2, -1):
            passes = 3 if repeat == -1 else repeat + 1
            frames = passes * end + (0 if repeat == -1 else 2048)
            with self.subTest(repeat=repeat), self.native(prepared, 48000) as module:
                actual = module.render(48000, repeat=repeat, oversample=1, floats=True,
                                       max_seconds=(frames + 0.25) / 48000)
                self.assertEqual(actual, first * passes + (b'' if repeat == -1 else tail))
                self.assertEqual(module._native_frame, end if repeat == -1 else end + 2048)


    def seek_song(self):
        song = score_song()
        song['module']['tempo'] = 137
        song['samples'][1]['loop'] = {'start': 0, 'end': 1000}
        song['instruments'] = {1: {'sample': 1, 'nna': 'continue', 'fadeout': 128,
                                   'volume_envelope': {'nodes': [[0, 64], [30, 32], [60, 0]], 'sustain': 0}}}
        song['patterns']['a']['data'] = (
            '00: ... 01 ... V40 | ... .. ... ... | ... .. ... ... | ... .. ... ... | ... .. ... ... | C-3 01 ... ...\n'
            + '... .. ... ...\n' * 5 + '06: ... .. ... V20\n')
        song['patterns']['b']['data'] = '00: ... .. ... V60\n'
        beats = song['score']['patterns']['a']['beats']
        first = copy.deepcopy(beats[0])
        first.update(id='first', at=[1, 1], notes=[dict(first['notes'][0], instrument=0)])
        second = copy.deepcopy(first)
        second.update(id='second', at=[2, 1])
        second['notes'][0].update(id='second_note', fret=3, pitch=67)
        beats[-1]['notes'][0]['instrument'] = 0
        song['score']['patterns']['a']['beats'] = [first, second, beats[-1]]
        song['score']['patterns']['b']['beats'][0]['notes'][0]['instrument'] = 0
        song['orders'].append('a')
        song['score']['order_ids'].append('third')
        return song

    @staticmethod
    def seek_frame(rate, order, row):
        exact = (4 * order + Fraction(row, 12)) * 60 * rate / 137
        return exact.numerator // exact.denominator + (2 * (exact.numerator % exact.denominator) >= exact.denominator)

    def test_native_order_seek_matches_fresh_paired_replay_with_memory_ties_nna_and_v(self):
        song = self.seek_song()
        with self.native(api.prepare_playback(song, self.base, 48000), 48000):
            pass
        for rate in (48000, 96000):
            prepared = api.prepare_playback(song, self.base, rate)
            for floats in (False, True):
                with self.native(prepared, rate) as module:
                    module.render(rate, oversample=1, floats=floats, max_seconds=0.1)
                    for order, row in ((0, 24), (1, 0), (1, 3), (2, 12), (3, 0), (0, 0)):
                        target = self.seek_frame(rate, order, row)
                        with self.subTest(rate=rate, floats=floats, order=order, row=row), self.native(prepared, rate) as reference:
                            # Matching partitions avoid ordinary OpenMPT's block-dependent rounding under Vxx.
                            reference.render(rate, oversample=1, floats=floats, max_seconds=(target + 0.25) / rate)
                            expected = reference.render(rate, oversample=1, floats=floats, max_seconds=2048 / rate)
                            self.assertEqual(module.order_start(order, row), target / rate)
                            self.assertEqual(module._native_frame, target)
                            self.assertEqual(module._in_tail, order == 3)
                            self.assertEqual(module._event_index, sum(e['frame'] <= target for e in prepared['plan']['events']))
                            actual = module.render(rate, oversample=1, floats=floats, max_seconds=2048 / rate)
                            self.assertEqual(actual, expected)

    def test_native_seek_cancellation_is_bounded_transactional_and_retryable(self):
        import ctypes as C
        from vulturetracker import openmpt as om
        prepared = api.prepare_playback(self.seek_song(), self.base, 96000)
        with self.native(prepared, 48000, 2) as module:
            module.render(48000, oversample=2, max_seconds=0.2)
            original = module._ext, module._native_frame, module._event_index, dict(module._handles)
            read = om.LoadedModule._native_read
            answers = iter((False, False, False, True))
            with patch.object(om.LoadedModule, '_native_read', autospec=True, side_effect=read) as reads, \
                 patch.object(om._lib, 'openmpt_module_ext_destroy', wraps=om._lib.openmpt_module_ext_destroy) as destroy:
                with self.assertRaisesRegex(ValueError, 'Export cancelled'):
                    module.order_start(1, 3, cancel=lambda: next(answers))
                self.assertEqual(reads.call_count, 2)
                self.assertTrue(all(call.args[2] <= 4096 and C.sizeof(call.args[3]) == 4096 * 2 * 4
                                    for call in reads.call_args_list))
                destroy.assert_called_once()
            self.assertEqual((module._ext, module._native_frame, module._event_index, module._handles), original)
            for order, row in ((-1, 0), (0, 48), (3, 1), (4, 0), (True, 0)):
                with self.subTest(order=order, row=row), self.assertRaises(ValueError):
                    module.order_start(order, row)
            self.assertEqual(module._native_frame, original[1])
            target = self.seek_frame(96000, 1, 3)
            self.assertEqual(module.order_start(1, 3), target / 96000)
            self.assertFalse(module._in_tail)
            with self.native(prepared, 96000) as reference:
                reference.render(96000, oversample=1, floats=True, max_seconds=(target + 0.25) / 96000)
                raw = reference.render(96000, oversample=1, floats=True, max_seconds=4096 / 96000)
            import numpy as np
            from vulturetracker.resample import decimate, lowpass_fir
            expected = decimate(np.frombuffer(raw, '<f4').reshape(-1, 2), 2, lowpass_fir(0.45 / 2)).astype('<f4').tobytes()
            self.assertEqual(module.render(48000, oversample=2, floats=True, max_seconds=4096 / 96000), expected)


class TestPercussionMidi(unittest.TestCase):
    """Drum keys use the shared State/plan but one fixed MIDI percussion route."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        write_wav(self.base / 'tone.wav', RATE, [sine(440)])

    def song(self, source=None):
        song = copy.deepcopy(source or score_song())
        song['samples'] = {1: dict(file='tone.wav'), 2: dict(file='tone.wav')}
        song['instruments'] = {1: dict(name='Kit', keymap=[
            dict(notes='C-0..B-9', sample=1, play_note='C-5'),
            dict(notes='F#3', sample=2, play_note='C-5')])}
        song['score']['tracks']['guitar'].update(
            tuning=[0] * 6, midi=dict(bank=128, program=0, source_pan=dict(value=63, mixer_pan=32)))
        for ch in song['module']['channels']:
            ch.update(pan=32, volume=64)
        for pattern in song['patterns'].values():
            pattern['data'] = ''
        for pattern in song['score']['patterns'].values():
            for beat in pattern['beats']:
                for note in beat['notes']:
                    key = 36 if note['string'] == 1 else 42
                    note.update(pitch=key, fret=key, velocity=95)
                    note.pop('let_ring', None)
        return song

    def converted(self, song, **options):
        from vulturetracker import export
        from tests.test_workflow import TestNativeMidi
        snap = export.snapshot(song, self.base, tail=0, **options)
        data, report = export.native_to_midi(snap)
        mid, events = TestNativeMidi.read(self, data)
        return snap, report, mid, events

    def second_track(self, song, percussion=True):
        track = song['score']['tracks']['guitar']
        track['channels'], track['tuning'] = [0, 1, 2], [0] * 3
        other = copy.deepcopy(track)
        other['channels'] = [3, 4, 5]
        if not percussion:
            other.update(tuning=[64, 59, 55], midi=dict(program=25))
        song['score']['tracks']['other'] = other
        beat = copy.deepcopy(song['score']['patterns']['a']['beats'][0])
        beat.update(id='other', track='other')
        beat['notes'] = [dict(id='other', string=1, pitch=38 if percussion else 64,
                              fret=38 if percussion else 0, velocity=95)]
        song['score']['patterns']['a']['beats'].append(beat)
        return other, beat

    def test_authored_keys_keymap_ties_and_single_fixed_initialization(self):
        from vulturetracker.itreader import read_it
        snap, report, mid, events = self.converted(self.song())
        mod, _ = read_it(snap['render_it'])
        self.assertEqual(mod.instruments[0].keymap[36], (60, 1))
        self.assertEqual(mod.instruments[0].keymap[42], (60, 2))
        attacks = [(Fraction(at, mid.ticks_per_beat), m.note, m.velocity)
                   for _, at, m in events if m.type == 'note_on']
        expected = [(Fraction(*e['at']), e['pitch'], e['velocity'])
                    for e in snap['plan']['events'] if e['type'] == 'note_on']
        self.assertEqual(sorted(attacks), sorted(expected))
        releases = [(Fraction(at, mid.ticks_per_beat), m.note)
                    for _, at, m in events if m.type == 'note_off']
        self.assertEqual(sorted(releases), sorted((Fraction(*v['release']), v['pitch']) for v in report['voices']))
        self.assertTrue(all(m.channel == 9 for _, _, m in events if hasattr(m, 'channel')))
        self.assertEqual([m.program for _, _, m in events if m.type == 'program_change'], [0])
        self.assertEqual(sorted((m.control, m.value) for _, _, m in events if m.type == 'control_change'),
                         sorted([(7, 127), (10, 63), (11, 127), (93, 0), (91, 0), (95, 0), (92, 0)]))
        self.assertFalse(any(m.type == 'pitchwheel' for _, _, m in events))

    def test_ghost_staccato_preserves_drum_key_and_performed_velocity_gate(self):
        song = self.song()
        song['score']['ties'] = []
        first = song['score']['patterns']['a']['beats'][0]
        first['notes'] = [dict(first['notes'][0], pitch=38, fret=38, ghost=True, staccato=True)]
        song['score']['patterns']['a']['beats'] = [first]
        song['score']['patterns']['b']['beats'] = []
        _, _, mid, events = self.converted(song)
        self.assertEqual([(Fraction(at, mid.ticks_per_beat), m.type, m.channel, m.note, m.velocity)
                          for _, at, m in events if m.type in ('note_on', 'note_off')],
                         [(Fraction(0), 'note_on', 9, 38, 79),
                          (Fraction(1, 2), 'note_off', 9, 38, 0)])
        self.assertEqual(first['notes'][0]['velocity'], 95)

    def test_compatible_tracks_share_drums_and_melodic_sibling_keeps_other_route(self):
        for percussion in (True, False):
            with self.subTest(percussion=percussion):
                song = self.song()
                self.second_track(song, percussion)
                _, report, _, events = self.converted(song)
                other = next(v for v in report['voices'] if v['source_channel'] == 3)
                self.assertEqual(other['midi_channel'] == 9, percussion)
                self.assertEqual(other['pitch'], 38 if percussion else 60)
                self.assertTrue(all(v['midi_channel'] == 9 for v in report['voices'] if v['source_channel'] < 3))
                self.assertFalse(any(m.type == 'control_change' and m.channel == 9 and m.control in (0, 32, 6, 38, 100, 101)
                                     for _, _, m in events))

    def test_same_key_overlap_refused_across_lanes_voices_and_tracks(self):
        for kind in ('lane', 'voice', 'track'):
            song = self.song()
            first = song['score']['patterns']['a']['beats'][0]
            if kind == 'lane':
                first['notes'][1].update(pitch=36, fret=36)
            elif kind == 'voice':
                other = copy.deepcopy(first)
                other.update(id='voice', voice=1)
                other['notes'] = [dict(first['notes'][0], id='voice')]
                song['score']['patterns']['a']['beats'].append(other)
            else:
                _, other = self.second_track(song)
                other['notes'][0].update(pitch=36, fret=36)
            with self.subTest(kind=kind), self.assertRaisesRegex(ValueError, 'percussion key 36 overlaps'):
                self.converted(song)

    def test_fixed_program_pan_volume_expression_conflicts_are_atomic(self):
        from vulturetracker import export
        for kind in ('program', 'pan', 'volume', 'expression'):
            song = self.song()
            other, beat = self.second_track(song)
            # Even non-overlapping drum tracks cannot switch fixed channel state.
            beat['at'] = [2, 1]
            if kind == 'program':
                other['midi']['program'] = 1
            elif kind == 'pan':
                other['midi']['source_pan']['value'] = 64
            elif kind == 'volume':
                song['module']['channels'][3]['volume'] = 32
            else:
                song['samples'][2]['global_volume'] = 32
            snap = export.snapshot(song, self.base, tail=0)
            before = copy.deepcopy(snap)
            with self.subTest(kind=kind), self.assertRaisesRegex(ValueError, 'identical fixed'):
                export.native_to_midi(snap)
            self.assertEqual(snap, before)
            self.assertEqual(list(self.base.iterdir()), [self.base / 'tone.wav'])

    def test_raw_controls_attacks_and_forged_pitch_or_fade_refused(self):
        from vulturetracker import export
        from tests.test_workflow import TestNativeMidi
        for raw, reason in (('06: ... .. ... X80', 'volume/pan changes'),
                            ('06: ... .. ... M20', 'volume/pan changes'),
                            ('24: C-3 01 ... ...\n30: === .. ... ...', 'raw percussion attacks')):
            song = self.song()
            TestNativeMidi.raw(self, song, raw)
            with self.subTest(raw=raw), self.assertRaisesRegex(ValueError, reason):
                self.converted(song)
        snap, _, _, _ = self.converted(self.song())
        first = next(e for e in snap['plan']['events'] if e['type'] == 'note_on')
        for kind in ('pitch', 'fade'):
            altered = copy.deepcopy(snap)
            if kind == 'pitch':
                altered['plan']['events'].append(dict(first, type='pitch', semitones=1))
            else:
                altered['plan']['midi_fades'] = [dict(id='fade', track='guitar', ticks=0, ordinal=0, at=[0, 1])]
            with self.subTest(kind=kind), self.assertRaisesRegex(ValueError, 'percussion .* (controls|fades)'):
                export.native_to_midi(altered)

    def test_repeated_keys_boundaries_range_and_muting(self):
        song = self.song(repeat_song())
        for i, pattern in enumerate(song['score']['patterns'].values()):
            pattern['beats'][0]['notes'][0].update(pitch=(1, 100, 38)[i], fret=(1, 100, 38)[i])
        _, _, mid, events = self.converted(song)
        self.assertEqual([(Fraction(at, mid.ticks_per_beat), m.note) for _, at, m in events if m.type == 'note_on'],
                         [(Fraction(q), k) for q, k in ((0, 1), (4, 100), (8, 1), (12, 100), (16, 38))])
        song = self.song()
        song['score']['ties'] = []
        song['score']['patterns']['a']['beats'] = song['score']['patterns']['a']['beats'][:1]
        first = song['score']['patterns']['a']['beats'][0]
        first['notes'] = first['notes'][:1]
        second = copy.deepcopy(first)
        second.update(id='second', at=[1, 1])
        second['notes'][0]['id'] = 'second'
        song['score']['patterns']['a']['beats'].append(second)
        _, _, mid, events = self.converted(song)
        self.assertEqual([m.type for _, at, m in events if at == mid.ticks_per_beat and m.type.startswith('note_')],
                         ['note_off', 'note_on'])
        song['patterns']['a']['data'] = '00: ... .. ... X40\n'
        _, _, _, events = self.converted(song, region=(0, 12, 0, 17))
        self.assertEqual([m.value for _, _, m in events if m.type == 'control_change' and m.control == 10], [32])
        self.assertEqual([m.note for _, _, m in events if m.type == 'note_on'], [36])
        self.assertEqual(self.converted(song, muted=list(range(6)))[1]['note_count'], 0)

    def test_actual_imported_kit_state_edit_undo_reopen_and_export(self):
        from tests.test_gpimport import TestPercussionInterchange, TestTgInterchange
        from vulturetracker import export, tgimport
        source = self.base / 'drums.tg'
        source.write_bytes(TestTgInterchange.archive(TestPercussionInterchange.xml()))
        path = self.base / 'drums.yaml'
        song, _ = tgimport.import_tg(source, path, self.base / 'samples')
        st = gui.State(path, headless=True)
        self.addCleanup(st.close)
        self.assertIsNone(st.error)
        snap, report, _, _ = self.converted(st.song)
        ons = [e for e in snap['plan']['events'] if e['type'] == 'note_on']
        self.assertTrue(all(e['instrument'] == e['source_instrument'] ==
                            song['score']['tracks']['t1']['instrument'] for e in ons))
        first_pattern = next(iter(st.song['score']['patterns']))
        first = st.song['score']['patterns'][first_pattern]['beats'][0]
        before = path.read_bytes()
        st.score_edit(dict(revision=st.text_sha(), op='note_set', pattern=first_pattern,
                           beat=first['id'], note=dict(id=first['notes'][0]['id'], pitch=38)))
        self.assertEqual(st.song['score']['patterns'][first_pattern]['beats'][0]['notes'][0]['pitch'], 38)
        st.undo()
        self.assertEqual(path.read_bytes(), before)
        st.close()
        reopened = gui.State(path, headless=True)
        self.addCleanup(reopened.close)
        self.assertIsNone(reopened.error)
        again = export.snapshot(reopened.song, self.base, tail=0)
        self.assertEqual(export.native_to_midi(again)[1]['voices'], report['voices'])
        destination = self.base / 'export'
        job = export.prepare(reopened, dict(fmt='mid', destination=str(destination)))
        self.assertFalse(destination.exists())
        result = export.run(job, lambda *args: self.fail('MIDI must not render audio'))
        self.assertEqual(result['status'], 'done')
        self.assertEqual(len(list(destination.glob('*.mid'))), 1)

    def test_actual_mixed_import_preserves_instrument_assignment_in_both_orders(self):
        import xml.etree.ElementTree as ET
        from tests.test_gpimport import TestPercussionInterchange, TestTgInterchange
        from vulturetracker import export, tgimport
        from vulturetracker.itreader import read_it
        for drum_first in (True, False):
            root = ET.fromstring(TestPercussionInterchange.xml())
            target = root.find('TGSong')
            channel = copy.deepcopy(target.find('TGChannel'))
            channel.find('id').text = '2'
            channel.find('bank').text = '0'
            target.append(channel)
            guitar = copy.deepcopy(target.find('TGTrack'))
            guitar.find('channelId').text = '2'
            for string in guitar.findall('TGString'):
                string.text = '64'
            for note in guitar.findall('.//note'):
                note.set('value', '0')
            target.insert(len(target) if drum_first else list(target).index(target.find('TGTrack')), guitar)
            folder = self.base / str(drum_first)
            folder.mkdir()
            source = folder / 'mixed.tg'
            source.write_bytes(TestTgInterchange.archive(ET.tostring(root, encoding='unicode')))
            song, _ = tgimport.import_tg(source, folder / 'song.yaml', folder / 'samples')
            snap = export.snapshot(song, folder, tail=0)
            mod, _ = read_it(snap['render_it'])
            _, report = export.native_to_midi(snap)
            notes = {e['id']: e for e in snap['plan']['events'] if e['type'] == 'note_on'}
            with self.subTest(drum_first=drum_first):
                for voice in report['voices']:
                    event = notes[voice['id']]
                    track = next(t for t in song['score']['tracks'].values() if event['ch'] in t['channels'])
                    self.assertEqual(event['instrument'], track['instrument'])
                    self.assertEqual(event['source_instrument'], track['instrument'])
                    drum = track['midi']['bank'] == 128
                    instrument = mod.instruments[track['instrument'] - 1]
                    mapped, sample = instrument.keymap[event['pitch']]
                    self.assertGreater(mod.samples[sample - 1].length, 0)
                    self.assertEqual(voice['pitch'], event['pitch'] if drum else mapped)
                    self.assertEqual(voice['midi_channel'] == 9, drum)
                    if drum:
                        self.assertEqual(mapped, 60)
                drum_track = next(t for t in song['score']['tracks'].values() if t['midi']['bank'] == 128)
                keymap = mod.instruments[drum_track['instrument'] - 1].keymap
                self.assertNotEqual(keymap[36][1], keymap[38][1])

    def test_conflict_prepare_never_creates_destination_or_changes_state(self):
        from vulturetracker import export
        song = self.song()
        other, _ = self.second_track(song)
        other['midi']['program'] = 8
        path = self.base / 'conflict.yaml'
        path.write_bytes(api.to_yaml(song).encode())
        st = gui.State(path, headless=True)
        self.addCleanup(st.close)
        before = path.read_bytes(), len(st.history)
        destination = self.base / 'refused'
        with self.assertRaisesRegex(ValueError, 'identical fixed'):
            export.prepare(st, dict(fmt='mid', destination=str(destination)))
        self.assertFalse(destination.exists())
        self.assertEqual((path.read_bytes(), len(st.history)), before)

    def ring_song(self):
        song = self.song()
        song['score']['ties'] = []
        first = song['score']['patterns']['a']['beats'][0]
        first['notes'] = first['notes'][:1]
        second = copy.deepcopy(first)
        second.update(id='second', at=[1, 1])
        second['notes'][0].update(id='second', pitch=38, fret=38)
        song['score']['patterns']['a']['beats'] = [first, second]
        song['score']['patterns']['b']['beats'] = []
        return song

    def test_let_ring_state_edit_undo_redo_reopen_and_distinct_key_midi(self):
        song = self.ring_song()
        path = self.base / 'ring.yaml'
        path.write_bytes(api.to_yaml(song).encode())
        st = gui.State(path, headless=True)
        self.addCleanup(st.close)
        self.assertIsNone(st.error)
        before, history = path.read_bytes(), len(st.history)
        st.score_edit(dict(revision=st.text_sha(), op='note_set', pattern='a', beat='chord',
                           note=dict(id='e', let_ring=True)))
        self.assertEqual(len(st.history), history + 1)
        saved = path.read_bytes()
        st.undo()
        self.assertEqual(path.read_bytes(), before)
        st.undo(redo=True)
        self.assertEqual(path.read_bytes(), saved)
        st.close()
        reopened = gui.State(path, headless=True)
        self.addCleanup(reopened.close)
        self.assertIsNone(reopened.error)
        self.assertTrue(reopened.song['score']['patterns']['a']['beats'][0]['notes'][0]['let_ring'])
        snap, _, mid, events = self.converted(reopened.song)
        self.assertTrue(next(e for e in snap['plan']['events'] if e['id'] == 'first/e' and e['type'] == 'note_on')['hold'])
        self.assertEqual([(Fraction(at, mid.ticks_per_beat), m.type, m.channel, m.note)
                          for _, at, m in events if m.type in ('note_on', 'note_off')],
                         [(Fraction(0), 'note_on', 9, 36), (Fraction(1), 'note_on', 9, 38),
                          (Fraction(2), 'note_off', 9, 36), (Fraction(2), 'note_off', 9, 38)])

    def test_let_ring_same_key_overlap_refuses_midi_publication_atomically(self):
        from vulturetracker import export
        song = self.ring_song()
        first, second = song['score']['patterns']['a']['beats']
        first['notes'][0]['let_ring'] = True
        second['notes'][0].update(pitch=36, fret=36)
        path = self.base / 'same-key.yaml'
        path.write_bytes(api.to_yaml(song).encode())
        st = gui.State(path, headless=True)
        self.addCleanup(st.close)
        self.assertIsNone(st.error)  # Native identities remain independently representable.
        before = path.read_bytes(), len(st.history)
        destination = self.base / 'refused-ring'
        with self.assertRaisesRegex(ValueError, 'percussion key 36 overlaps'):
            export.prepare(st, dict(fmt='mid', destination=str(destination)))
        self.assertFalse(destination.exists())
        self.assertEqual((path.read_bytes(), len(st.history)), before)


class TestNativeGp5Export(unittest.TestCase):
    """Pure GP5 bytes, checked through the existing strict native importer."""

    flags = ('ghost', 'accent', 'heavy_accent', 'staccato', 'dead', 'palm_mute', 'let_ring')

    @staticmethod
    def fixture():
        from tests.test_tablature import beat, note
        song = score_song()
        song['module'].update(title='GP5 caf\u00e9', message='Literal source notes')
        song['patterns']['a']['data'] = ''
        track = song['score']['tracks']['guitar']
        track.update(name='Guitar caf\u00e9', color='#123456', midi=dict(program=25, bank=0),
                     key=dict(fifths=-1, mode='minor'),
                     lyrics=dict(from_measure=2, text='one  caf\u00e9\r\nthree\tfour'))
        def n(identity, pitch=64, lane=1, fret=0):
            return dict(note(identity, pitch, lane, fret), velocity=95)
        song['score']['patterns']['a']['beats'] = [
            beat('chord', [0, 1], [n('e'), n('c', 60, 2, 1)]),
            dict(beat('dot', [1, 1], [n('dot', 65, 1, 1)]), written=dict(value=4, dots=1, tuplet=[1, 1])),
            beat('eighth', [5, 2], [], 8),
            beat('tail', [3, 1], [n('tail')]),
            beat('voice2', [0, 1], [n('low', 55, 3, 0)], 2, voice=1),
            beat('voice2rest', [2, 1], [], 2, voice=1)]
        song['score']['patterns']['b']['beats'] = [
            beat('head', [0, 1], [n('head')]),
            beat('triplet1', [1, 1], [n('t1', 65, 1, 1)], 8, [3, 2]),
            beat('triplet2', [4, 3], [n('t2', 67, 1, 3)], 8, [3, 2]),
            beat('triplet3', [5, 3], [n('t3', 69, 1, 5)], 8, [3, 2]),
            beat('rest', [2, 1], [], 2)]
        song['orders'] = ['a', 'b', 'a']
        song['score']['order_ids'] = ['first', 'second', 'third']
        song['score']['ties'] = [dict(**{'from': dict(occurrence='first', note='tail'),
                                       'to': dict(occurrence='second', note='head')})]
        song['score']['measures'] = [
            dict(id=oid, meter=[4, 4], **{'from': dict(occurrence=oid, at=[0, 1]),
                                         'to': dict(occurrence=oid, at=[4, 1])})
            for oid in song['score']['order_ids']]
        song['score']['measures'][0]['marker'] = dict(title='Verse caf\u00e9', color='#abcdef')
        song['score']['patterns']['a']['beats'][0]['text'] = 'Play softly'
        return song

    @staticmethod
    def convert(song):
        from vulturetracker import gpexport, tgimport, gpimport
        raw = tgimport._raw(song)
        mappings = {tid: dict(program=t['midi']['program'], bank=t['midi'].get('bank', 0))
                    for tid, t in song['score']['tracks'].items()}
        data, report = gpexport.native_to_gp5(song, raw, channels=mappings)
        decoded = gpimport._read_native_gp(data)
        restored = gpimport._native_gp_song(decoded, decoded.title)
        return data, report, decoded, restored

    @staticmethod
    def written(song):
        from vulturetracker import tablature, tgimport
        view = tablature.authoring_view(song, tgimport._raw(song))
        tids = list(song['score']['tracks'])
        result, at = [], Fraction(0)
        for name in song['orders']:
            pattern = song['score']['patterns'][name]
            for b in pattern['beats']:
                result.append((tids.index(b['track']), b['voice'], at + Fraction(*b['at']), b['written'],
                               b.get('text', ''), [(n['pitch'], n['string'], n['fret'], n['velocity'],
                                   tuple(bool(n.get(k)) for k in TestNativeGp5Export.flags)) for n in b['notes']]))
            at += song['patterns'][name]['rows'] * Fraction(*pattern['row_step'])
        ties = sorted((Fraction(*p['at']), p['pitch'], p['string'], p['tied_in'], p['tied_out'])
                      for p in view['positions'] if p['kind'] == 'note')
        return sorted(result, key=lambda b: b[:3]), ties

    def test_written_two_voices_ties_tuplets_text_and_shared_pattern_roundtrip(self):
        song = self.fixture()
        before = copy.deepcopy(song)
        data, report, decoded, restored = self.convert(song)
        self.assertEqual(decoded.versionTuple, (5, 0, 0))
        self.assertEqual(decoded.title, song['module']['title'])
        self.assertEqual(decoded.notice, [song['module']['message']])
        self.assertEqual(self.written(restored), self.written(song))
        original, actual = song['score']['tracks']['guitar'], restored['score']['tracks']['t1']
        for field in ('name', 'color', 'key', 'lyrics', 'tuning', 'capo'):
            self.assertEqual(actual.get(field, 0), original.get(field, 0), field)
        self.assertEqual(actual['midi']['source_pan'], dict(value=63, mixer_pan=32))
        self.assertEqual(restored['score']['measures'][0]['marker'], song['score']['measures'][0]['marker'])
        self.assertEqual((report['tracks'], report['measures']), (1, 3))
        self.assertEqual(report['format'], 'Guitar Pro 5.00')
        self.assertTrue(data.startswith(b'\x18FICHIER GUITAR PRO v5.00'))
        self.assertEqual(song, before)

    @staticmethod
    def header_fixture():
        from tests.test_gpimport import repeat_gp_tab, write_repeat_gp
        from guitarpro import models as M
        from vulturetracker import gpimport
        source = repeat_gp_tab([dict(isRepeatOpen=True), dict(repeatAlternative=1, repeatClose=1),
                                dict(repeatAlternative=2)])
        source.measureHeaders[1].timeSignature = M.TimeSignature(3, M.Duration(4))
        for track in source.tracks:
            track.measures[1].voices[0].beats[0].duration = M.Duration(2, True)
        source.measureHeaders[2].tripletFeel = M.TripletFeel.eighth
        source.tracks[0].measures[2].voices[0].beats[0].effect.mixTableChange = M.MixTableChange(
            tempo=M.MixTableItem(90, duration=0))
        return gpimport._native_gp_song(gpimport._read_native_gp(write_repeat_gp(source, 5)), 'Repeats')

    def test_repeat_alternate_meter_swing_and_boundary_tempo_roundtrip(self):
        from tests.test_gpimport import TestRepeatInterchange
        from guitarpro import models as M
        song = self.header_fixture()
        _, _, decoded, restored = self.convert(song)
        self.assertEqual([(h.timeSignature.numerator, h.repeatAlternative, h.repeatClose) for h in decoded.measureHeaders],
                         [(4, 0, -1), (3, 1, 1), (4, 2, -1)])
        self.assertEqual(decoded.measureHeaders[2].tripletFeel, M.TripletFeel.eighth)
        def gates(s):
            return [(e['type'], e['at'], e['pitch'], e['velocity'])
                    for e in TestRepeatInterchange.plan(self, s)['events'] if e['type'] in ('note_on', 'note_off')]
        self.assertEqual(gates(restored), gates(song))
        self.assertEqual([m.get('endings') for m in restored['score']['measures']], [None, [1], [2]])

    @staticmethod
    def mixed_fixture():
        song = TestNativeGp5Export.fixture()
        track = copy.deepcopy(song['score']['tracks']['guitar'])
        track.pop('lyrics')
        track.update(name='Drums', tuning=[0, 0], channels=[6, 7], midi=dict(program=0, bank=128))
        song['module']['channels'] += [dict(name='kick'), dict(name='snare')]
        song['score']['tracks']['drums'] = track
        from tests.test_tablature import beat, note
        song['score']['patterns']['a']['beats'].append(beat('drums', [0, 1], [
            dict(note('kick', 1, 1, 1), velocity=95), dict(note('snare', 99, 2, 99), velocity=79)], 1, track='drums'))
        return song

    def test_melodic_drum_program_routes_and_key_bounds(self):
        song = self.mixed_fixture()
        _, report, decoded, restored = self.convert(song)
        self.assertEqual(self.written(restored), self.written(song))
        self.assertEqual([(t.isPercussionTrack, t.channel.channel, t.channel.effectChannel) for t in decoded.tracks],
                         [(False, 0, 1), (True, 9, 9)])
        self.assertEqual([r['program'] for r in report['channels']], [25, 0])
        song['score']['patterns']['a']['beats'][-1]['notes'][1].update(pitch=100, fret=100)
        with self.assertRaisesRegex(ValueError, 'key must be1..99'):
            self.convert(song)

    def test_exactness_and_metadata_refusals_leave_source_unchanged(self):
        changes = [
            ('lane order', lambda s: s['score']['patterns']['a']['beats'][0]['notes'].reverse(), 'lane order'),
            ('velocity', lambda s: s['score']['patterns']['a']['beats'][0]['notes'][0].update(velocity=94), 'GP grid'),
            ('effect', lambda s: s['score']['patterns']['a']['beats'][0]['notes'][0].update(
                grace=dict(fret=0, value=16, velocity=80)), 'grace velocity'),
            ('encoding', lambda s: s['score']['tracks']['guitar'].update(name='Guitar \u03a9'), 'cp1252'),
            ('name length', lambda s: s['score']['tracks']['guitar'].update(name='x' * 41), '40 encoded'),
            ('pan', lambda s: s['score']['tracks']['guitar']['midi'].update(source_pan=dict(value=64, mixer_pan=32)), 'source pan'),
            ('bank', lambda s: s['score']['tracks']['guitar']['midi'].update(bank=1), 'bank0'),
            ('clef', lambda s: s['score']['tracks']['guitar'].update(clef='alto'), 'clef'),
            ('shared text', lambda s: s['score']['patterns']['a']['beats'][4].update(text='Other voice'), 'beat text'),
        ]
        for name, change, reason in changes:
            song = self.fixture()
            change(song)
            before = copy.deepcopy(song)
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, reason):
                self.convert(song)
            self.assertEqual(song, before)

    def test_eighth_ending_mask_is_unsigned_and_preserves_performed_visits(self):
        from tests.test_gpimport import TestRepeatInterchange
        song = self.header_fixture()
        song['score']['measures'][1].update(endings=list(range(1, 8)), repeat_close=7)
        song['score']['measures'][2]['endings'] = [8]
        _, _, decoded, restored = self.convert(song)
        self.assertEqual([h.repeatAlternative for h in decoded.measureHeaders], [0, 127, 128])
        def events(s):
            return [(e['type'], e['at'], e['pitch']) for e in TestRepeatInterchange.plan(self, s)['events']]
        self.assertEqual(events(restored), events(song))

    def test_inferred_clef_boundary_and_percussion_exception(self):
        # Include a later string: GP5InputStream.getClef checks every string.
        for lane in (0, 5):
            for pitch in (34, 35):
                song = self.fixture()
                track = song['score']['tracks']['guitar']
                track.update(clef='treble', max_fret=36)
                track['tuning'][lane] = pitch
                for pattern in song['score']['patterns'].values():
                    for beat in pattern['beats']:
                        for note in beat['notes']:
                            if note['string'] == lane + 1:
                                note['fret'] = note['pitch'] - pitch
                before = copy.deepcopy(song)
                with self.subTest(lane=lane, pitch=pitch):
                    if pitch == 34:
                        with self.assertRaisesRegex(ValueError, 'infers bass clef'):
                            self.convert(song)
                    else:
                        _, _, decoded, _ = self.convert(song)
                        self.assertEqual(decoded.tracks[0].strings[lane].value, 35)
                self.assertEqual(song, before)
        song = self.mixed_fixture()
        drums = song['score']['tracks']['drums']
        self.assertEqual(drums['tuning'], [0, 0])
        drums['clef'] = 'treble'
        _, _, decoded, _ = self.convert(song)
        self.assertTrue(decoded.tracks[1].isPercussionTrack)
        for clef in ('bass', 'percussion'):
            drums['clef'] = clef
            with self.subTest(clef=clef), self.assertRaisesRegex(ValueError, 'clef'):
                self.convert(song)

    def test_unarranged_authored_material_refuses_without_mutation(self):
        from tests.test_tablature import beat, note
        song = self.fixture()
        song['patterns']['unused'] = dict(rows=16, data='')
        song['score']['patterns']['unused'] = dict(
            row_step=copy.deepcopy(song['score']['patterns']['a']['row_step']), beats=[])
        self.convert(song)  # An empty unused backing pattern has no notation to lose.
        for notes in ([], [dict(note('unused-note', 64, 1, 0), velocity=95, vibrato=True)]):
            song['score']['patterns']['unused']['beats'] = [beat('unused-beat', [0, 1], notes)]
            before = copy.deepcopy(song)
            with self.subTest(notes=bool(notes)), self.assertRaisesRegex(
                    ValueError, 'unused: unarranged authored beats'):
                self.convert(song)
            self.assertEqual(song, before)

    @staticmethod
    def flags_fixture(drums=False):
        from guitarpro import models as M
        from tests.test_gpimport import harmonic_tab, write_repeat_gp
        from vulturetracker import gpimport
        source = harmonic_tab([None, None], fret=5, tuning=64)
        track = source.tracks[0]
        track.channel.volume = 128
        track.channel.balance = 64
        track.strings = [M.GuitarString(i + 1, pitch) for i, pitch in enumerate(
            [0] * 7 if drums else [64, 59, 55, 50, 45, 40, 35])]
        if drums:
            track.isPercussionTrack = True
            track.channel.channel = track.channel.effectChannel = 9
            track.channel.instrument = 0
        fields = ('ghostNote', 'accentuatedNote', 'heavyAccentuatedNote', 'staccato', None, 'palmMute', 'letRing')
        for bi, beat in enumerate(track.measures[0].voices[0].beats):
            beat.notes = []
            for i, field in enumerate(fields):
                note = M.Note(beat, value=36 + i if drums else 5, string=i + 1,
                              velocity=95, type=M.NoteType.dead if bi == 0 and field is None else M.NoteType.normal)
                if bi == 0 and field:
                    setattr(note.effect, field, True)
                beat.notes.append(note)
        return gpimport._native_gp_song(gpimport._read_native_gp(write_repeat_gp(source, 5)), 'Seven flags')

    @staticmethod
    def gates(song):
        from vulturetracker import tablature, tgimport
        return sorted([(e['type'], e['at'], e['ch'], e['pitch'], e['velocity'])
                for e in tablature.playback_plan(song, tgimport._raw(song))['events']
                if e['type'] in ('note_on', 'note_off')],
                key=lambda e: (Fraction(*e[1]), e[0], e[2:]))

    def test_seven_flags_are_note_local_and_preserve_written_velocity(self):
        for drums in (False, True):
            song = self.flags_fixture(drums)
            beats = song['score']['patterns']['m1']['beats']
            for note in beats[1]['notes']:
                note.update({key: False for key in self.flags})
            before = copy.deepcopy(song)
            with self.subTest(drums=drums):
                _, _, decoded, restored = self.convert(song)
                self.assertEqual(self.written(restored), self.written(song))
                self.assertEqual(self.gates(restored), self.gates(song))
                notes = restored['score']['patterns']['m1']['beats'][0]['notes']
                self.assertEqual([{key for key in self.flags if n.get(key)} for n in notes],
                                 [{key} for key in self.flags])
                self.assertTrue(all(n.velocity == 95 for b in decoded.tracks[0].measures[0].voices[0].beats for n in b.notes))
                self.assertTrue(all(not any(n.get(k) for k in self.flags)
                                    for n in restored['score']['patterns']['m1']['beats'][1]['notes']))
                self.assertEqual(song, before)

    def test_flags_stay_in_their_written_voice(self):
        song = self.fixture()
        beats = song['score']['patterns']['a']['beats']
        beats[0]['notes'][0]['ghost'] = True
        beats[4]['notes'][0]['accent'] = True
        _, _, _, restored = self.convert(song)
        self.assertEqual(self.written(restored), self.written(song))
        self.assertEqual(self.gates(restored), self.gates(song))

    def test_dead_head_ring_continuation_and_incoming_dead_refusal(self):
        from guitarpro import models as M
        from tests.test_gpimport import let_ring_tab, TestPercussionInterchange, write_repeat_gp
        from vulturetracker import gpimport
        for drums in (False, True):
            for continuation_ring in (False, True):
                source = TestPercussionInterchange.gp_ring('tie') if drums else let_ring_tab('tie')
                beats = source.tracks[0].measures[0].voices[0].beats
                beats[0].notes[0].type = M.NoteType.dead
                beats[1].notes[0].effect.letRing = continuation_ring
                song = gpimport._native_gp_song(gpimport._read_native_gp(write_repeat_gp(source, 5)), 'Dead tie')
                with self.subTest(drums=drums, continuation_ring=continuation_ring):
                    _, _, decoded, restored = self.convert(song)
                    actual = decoded.tracks[0].measures[0].voices[0].beats
                    self.assertEqual([b.notes[0].type for b in actual[:2]], [M.NoteType.dead, M.NoteType.tie])
                    self.assertEqual(actual[1].notes[0].effect.letRing, continuation_ring)
                    self.assertEqual(self.written(restored), self.written(song))
                    self.assertEqual(self.gates(restored), self.gates(song))
                    self.assertEqual(Fraction(*next(e[1] for e in self.gates(restored) if e[0] == 'note_off')) * 960, 60)
                    incoming = song['score']['patterns']['m1']['beats'][1]['notes'][0]
                    incoming['dead'] = True
                    before = copy.deepcopy(song)
                    with self.assertRaisesRegex(ValueError, incoming['id'] + ': incoming tie and dead'):
                        self.convert(song)
                    self.assertEqual(song, before)

    def test_flag_conflicts_refuse_without_normalizing_or_mutating(self):
        cases = [(('ghost', 'accent'), 'multiple dynamics'), (('ghost', 'heavy_accent'), 'multiple dynamics'),
                 (('accent', 'heavy_accent'), 'multiple dynamics'), (('palm_mute', 'staccato'), 'palm_mute and staccato'),
                 (('let_ring', 'palm_mute'), 'let_ring conflicts'), (('let_ring', 'staccato'), 'let_ring conflicts')]
        for drums in (False, True):
            for fields, reason in cases + ([(('vibrato',), 'unsupported .*vibrato')] if drums else []):
                song = self.flags_fixture(drums)
                note = song['score']['patterns']['m1']['beats'][1]['notes'][0]
                note.update({field: True for field in fields})
                before = copy.deepcopy(song)
                with self.subTest(drums=drums, fields=fields), self.assertRaisesRegex(ValueError, reason):
                    self.convert(song)
                self.assertEqual(song, before)
            song = self.flags_fixture(drums)
            song['score']['patterns']['m1']['beats'][1]['notes'][0]['ghost'] = 1
            with self.assertRaisesRegex(ValueError, 'ghost.*boolean'):
                self.convert(song)

    def test_duration_lane_lyric_and_route_capacity_refusals(self):
        for written in (dict(value=8, dots=2, tuplet=[1, 1]),
                        dict(value=4, dots=0, tuplet=[7, 4]),
                        dict(value=4, dots=0, tuplet=[2, 1])):
            song = self.fixture()
            song['score']['patterns']['a']['beats'][0]['written'] = written
            with self.subTest(written=written), self.assertRaisesRegex(ValueError, 'duration needs'):
                self.convert(song)
        song = self.fixture()
        track = song['score']['tracks']['guitar']
        track['tuning'] += [36, 31]
        track['channels'] += [6, 7]
        song['module']['channels'] += [{}, {}]
        with self.assertRaisesRegex(ValueError, 'seven lanes'):
            self.convert(song)
        for copies, lyrics, reason in ((2, True, 'one target track'), (8, False, 'seven independent')):
            song = self.fixture()
            for i in range(1, copies):
                track = copy.deepcopy(song['score']['tracks']['guitar'])
                track['channels'] = list(range(i * 6, (i + 1) * 6))
                if not lyrics:
                    track.pop('lyrics')
                song['score']['tracks'][f'track{i}'] = track
                song['module']['channels'] += [{} for _ in range(6)]
            with self.subTest(reason=reason), self.assertRaisesRegex(ValueError, reason):
                self.convert(song)


def complete_section_song():
    """Original four-bar seed: melody, an independent bass voice and a tied reply."""
    from tests.test_tablature_page import TestTablaturePage
    song = TestTablaturePage.four_bar_song()
    song['module'].update(title='Section composition', sample_rate=44100)
    song['samples'][1]['file'] = 'tone.wav'
    melodies = ((60, 64, 67, 65), (64, 62, 60, 60), (60, 64, 62), (67, 64, 62, 60))
    for name, pitches, bass in zip(song['orders'], melodies, (48, 45, 43, 48)):
        beats = []
        for i, pitch in enumerate(pitches):
            at = (0, 2, 3)[i] if name == 'G' else i
            value = 2 if name == 'G' and i == 0 else 4
            beats.append(dict(id=f'n{i}', track='guitar', voice=0, at=[at, 1],
                written=dict(value=value, dots=0, tuplet=[1, 1]),
                notes=[dict(id=f'pitch{i}', pitch=pitch, string=2, fret=pitch-59, velocity=88)]))
        beats.append(dict(id='bass', track='guitar', voice=1, at=[0, 1],
            written=dict(value=1, dots=0, tuplet=[1, 1]),
            notes=[dict(id='bass-note', pitch=bass, string=6, fret=bass-40, velocity=68)]))
        song['score']['patterns'][name]['beats'] = beats
    song['score']['ties'] = [{'from': dict(occurrence='bar2', note='pitch3'),
                              'to': dict(occurrence='bar3', note='pitch0')}]
    return song


def section_groups(song, first, last):
    return [dict(occurrence=song['score']['order_ids'][i],
                 beats=[b['id'] for b in song['score']['patterns'][str(song['orders'][i])]['beats']
                        if b['track'] == 'guitar']) for i in range(first, last + 1)]


def compose_complete_section(st):
    """The same authoring transactions used by controls; leaves a complete16-bar section."""
    snapshots = [st.song_path.read_bytes()]
    def command(**edit):
        result = st.score_command(dict(edit, revision=st.text_sha()))
        snapshots.append(st.song_path.read_bytes())
        return result
    groups = section_groups(st.song, 0, 3)
    for expected in (8, 12, 16):
        result = command(action='repeat', track='guitar', voice=0, selection=groups)
        assert len(st.song['orders']) == expected
        groups = result['selection']['range']
    command(action='measure_move', **{'from':12, 'to':15, 'at':4})
    # Vary the complete tied phrase before moving barlines through its bass notes.
    groups = section_groups(st.song, 12, 15)
    command(action='transpose', scope='selection', track='guitar', voice=0, selection=groups, semitones=2)
    result = command(action='set_duration', track='guitar', voice=0, selection=groups,
                     written=dict(value=8, dots=0, tuplet=[1, 1]))
    command(action='set_expression', track='guitar', voice=0, selection=result['selection']['range'],
            changes=dict(velocity=78))
    sounding = lambda: sorted(((e['type'], e['frame'], e.get('pitch'), e.get('ch'))
                               for e in st.mod.native_score['plan']['events']), key=repr)
    before = sounding()
    command(action='measure_meter', at=1, meter=[5, 4])
    assert sounding() == before  # Equal-time ordering may change when source IDs split; sounding events do not.
    # Insert and remove a passage in the middle; existing headers and both voices survive.
    command(action='measure_add', at=8, count=2)
    command(action='measure_remove', **{'from':8, 'to':9})
    assert len(st.song['orders']) == 16
    return snapshots


def complete_song_seed():
    """Four original bars for two guitars, bass and a mapped drum kit."""
    song = complete_section_song()
    song['module'].update(title='Complete song authoring', tempo=96,
        channels=[dict(name=f'String {i+1}', pan=32, volume=64) for i in range(19)])
    tracks = song['score']['tracks']
    tracks['guitar'].update(name='Lead guitar', midi=dict(program=25, bank=0), instrument=1)
    tracks['guitar2'] = dict(name='Drop D guitar', tuning=[64, 59, 55, 50, 45, 38],
        channels=list(range(6, 12)), capo=0, max_fret=24, instrument=2, midi=dict(program=27, bank=0))
    tracks['bass'] = dict(name='Bass', tuning=[43, 38, 33, 28], channels=list(range(12, 16)),
        capo=0, max_fret=24, instrument=3, clef='bass', midi=dict(program=33, bank=0))
    tracks['drums'] = dict(name='Drums', tuning=[0, 0, 0], channels=[16, 17, 18],
        capo=0, max_fret=24, instrument=4, midi=dict(program=0, bank=128))
    song['samples'] = {i: dict(file='tone.wav', name=f'Voice {i}', base_note='C-5') for i in range(1, 7)}
    song['instruments'] = {i: dict(name=tracks[t]['name'], sample=i) for i, t in enumerate(('guitar', 'guitar2', 'bass'), 1)}
    song['instruments'][4] = dict(name='Study kit', keymap=[dict(notes='C-0..B-9', sample=6, play_note='C-5'),
        dict(notes='C-3', sample=4, play_note='C-5'), dict(notes='D-3', sample=5, play_note='C-5')])
    for bar, (name, root_pitch) in enumerate(zip(song['orders'], (48, 45, 43, 48))):
        beats = song['score']['patterns'][name]['beats']
        for slot in (0, 2):
            beats.append(dict(id=f'rhythm{slot}', track='guitar2', voice=0, at=[slot, 1],
                written=dict(value=2, dots=0, tuplet=[1, 1]), notes=[
                    dict(id=f'rhythm-low{slot}', pitch=root_pitch, string=6, fret=root_pitch-38, velocity=79),
                    dict(id=f'rhythm-high{slot}', pitch=root_pitch+12, string=3, fret=root_pitch+12-55, velocity=79)]))
            pitch = root_pitch - 12 if slot == 0 else root_pitch - 5
            beats.append(dict(id=f'low{slot}', track='bass', voice=0, at=[slot, 1],
                written=dict(value=2, dots=0, tuplet=[1, 1]), notes=[
                    dict(id=f'low-note{slot}', pitch=pitch, string=4, fret=pitch-28, velocity=80)]))
        for slot in range(4):
            notes = [dict(id=f'hat{slot}', pitch=42, string=3, fret=42, velocity=62)]
            key, lane = (36, 1) if slot % 2 == 0 else (38, 2)
            notes.append(dict(id=f'drum{slot}', pitch=key, string=lane, fret=key, velocity=85))
            beats.append(dict(id=f'kit{slot}', track='drums', voice=0, at=[slot, 1],
                written=dict(value=4, dots=0, tuplet=[1, 1]), notes=notes))
    song['score']['measures'][0]['marker'] = dict(title='Opening', color='#4ca3dd')
    for pattern in song['score']['patterns'].values():
        for beat in pattern['beats']:
            beat['notes'].sort(key=lambda n: n['string'])
            for note in beat['notes']:
                note['velocity'] = min(range(15, 128, 16), key=lambda v: abs(v-note['velocity']))
    return song


def compose_complete_song(st):
    from vulturetracker import tablature
    snapshots = [st.text]
    def command(**body):
        result = st.score_command(dict(body, revision=st.text_sha()))
        snapshots.append(st.text)
        return result
    clip = tablature.measure_segment(st.song, 0, 3)
    command(action='measure_paste', mode='insert', at=4, count=7, segment=clip,
        copy_headers=True, copy_markers=False, track_map={t: t for t in st.song['score']['tracks']})
    for tid in ('guitar', 'guitar2', 'bass'):
        groups = [dict(occurrence=st.song['score']['order_ids'][i],
            beats=[b['id'] for b in st.song['score']['patterns'][st.song['orders'][i]]['beats'] if b['track'] == tid])
            for i in range(24, 32)]
        command(action='transpose', track=tid, selection=groups, scope='selection', semitones=2)
    command(action='measure_meter', at=16, meter=[5, 4], to_end=False)
    # Rebar keeps performed time; explicitly write the final silent quarter in every used voice.
    for tid, voices in [('guitar', (0, 1)), ('guitar2', (0,)), ('bass', (0,)), ('drums', (0,))]:
        for voice in voices:
            command(action='place', occurrence=st.song['score']['order_ids'][-1],
                beat=dict(id=f'closing-{tid}-{voice}', track=tid, voice=voice, at=[3, 1],
                    written=dict(value=4, dots=0, tuplet=[1, 1]), notes=[]))
    headers = {0: dict(marker=dict(title='Opening', color='#4ca3dd'), repeat_open=True),
        3: dict(endings=[1], repeat_close=1), 4: dict(endings=[2]),
        8: dict(marker=dict(title='Response', color='#74bf76')),
        16: dict(marker=dict(title='Bridge', color='#c6a661')),
        24: dict(marker=dict(title='Lift', color='#b58bd5'))}
    for index, fields in headers.items():
        measure = dict(st.song['score']['measures'][index], **fields)
        st.score_edit(dict(op='measure_set', measure=measure, revision=st.text_sha()))
        snapshots.append(st.text)
    return snapshots


class TestCompleteSongArrangementState(unittest.TestCase):
    def test_32_bar_four_track_composition_history_and_it(self):
        from vulturetracker import tablature
        from vulturetracker.itreader import read_it
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'song.yaml'
            write_wav(path.parent / 'tone.wav', RATE, [sine(440)])
            path.write_text(api.to_yaml(complete_song_seed()), encoding='utf-8', newline='\n')
            st = gui.State(path, headless=True)
            try:
                self.assertFalse(st.error, st.error)
                snapshots = compose_complete_song(st)
                self.assertEqual(len(st.song['orders']), 32)
                self.assertEqual(len(st.song['score']['tracks']), 4)
                self.assertFalse(tablature.measure_errors(st.song, {p.name: len(p.rows) for p in st.mod.patterns}))
                data, _, _ = api.compile_song(path)
                it, _ = read_it(data)
                self.assertEqual(sum(c.note is not None and c.note < 120 for p in it.patterns for row in p.rows for c in row),
                    sum(e['type'] == 'note_on' for e in st.mod.native_score['plan']['events']))
                from vulturetracker import tgimport, gpexport, gpimport
                def notes(song):
                    tracks, rows, at = list(song['score']['tracks']), [], Fraction(0)
                    for name in song['orders']:
                        pattern = song['score']['patterns'][name]
                        for beat in pattern['beats']:
                            for note in beat['notes']:
                                rows.append((tracks.index(beat['track']), beat['voice'], at+Fraction(*beat['at']),
                                    tablature.duration_quarters(beat['written']), note['pitch'], note['velocity']))
                        at += song['patterns'][name]['rows'] * Fraction(*pattern['row_step'])
                    return sorted(rows)
                routing = {tid: dict(program=t['midi']['program'], bank=t['midi'].get('bank', 0))
                    for tid, t in st.song['score']['tracks'].items()}
                raw = tgimport._raw(st.song)
                tg, _ = tgimport.native_to_tg(st.song, raw, channels=routing)
                gp, _ = gpexport.native_to_gp5(st.song, raw, channels=routing)
                reopened_tg, _ = tgimport.read_tg(tg)
                reopened_gp = gpimport._native_gp_song(gpimport._read_native_gp(gp), 'Roundtrip')
                for reopened in (reopened_tg, reopened_gp):
                    self.assertEqual(notes(reopened), notes(st.song))
                    self.assertEqual(len(reopened['score']['ties']), len(st.song['score']['ties']))
                    self.assertEqual([m.get('meter') for m in reopened['score']['measures']],
                        [m.get('meter') for m in st.song['score']['measures']])
                    self.assertEqual([m.get('endings', []) for m in reopened['score']['measures']],
                        [m.get('endings', []) for m in st.song['score']['measures']])
                for expected in reversed(snapshots[:-1]):
                    st.undo()
                    self.assertEqual(st.text, expected)
                for expected in snapshots[1:]:
                    st.undo(redo=True)
                    self.assertEqual(st.text, expected)
            finally:
                st.close()


class TestCompleteSectionState(unittest.TestCase):
    def open(self, song):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = Path(tmp.name) / 'song.yaml'
        write_wav(path.parent / 'tone.wav', RATE, [sine(440)])
        path.write_text('# Section session\n' + api.to_yaml(song), encoding='utf-8', newline='\n')
        st = gui.State(path, headless=True)
        self.addCleanup(st.close)
        self.assertFalse(st.error, st.error)
        return st

    def test_sixteen_bar_session_history_native_it_and_reopen(self):
        from vulturetracker.itreader import read_it
        st = self.open(complete_section_song())
        snapshots = compose_complete_section(st)
        self.assertEqual(len(st.song['orders']), 16)
        self.assertEqual(st.song['score']['measures'][1]['meter'], [5, 4])
        it, _, _ = api.compile_song(st.song_path)
        module, _ = read_it(it)
        attacks = sum(c.note is not None and c.note < 120 for p in module.patterns for row in p.rows for c in row)
        self.assertEqual(attacks, sum(e['type'] == 'note_on' for e in st.mod.native_score['plan']['events']))
        reopened = gui.State(st.song_path, headless=True)
        try:
            self.assertEqual(reopened.mod.native_score['plan'], st.mod.native_score['plan'])
        finally:
            reopened.close()
        for expected in reversed(snapshots[:-1]):
            st.undo()
            self.assertEqual(st.song_path.read_bytes(), expected)
        for expected in snapshots[1:]:
            st.undo(redo=True)
            self.assertEqual(st.song_path.read_bytes(), expected)

    def test_phrase_rest_delete_boundary_ties_and_exact_undo(self):
        st = self.open(complete_section_song())
        original = st.song_path.read_bytes()
        groups = section_groups(st.song, 2, 3)  # incoming tie originates outside this selection
        for action in ('rest', 'delete', 'delete_beats', 'clean_beat', 'cut'):
            with self.subTest(action=action):
                result = st.score_command(dict(action=action, track='guitar', voice=0,
                                                selection=groups, revision=st.text_sha()))
                self.assertFalse(st.song['score']['ties'])
                self.assertEqual(len(result['removed_ties']), 1)
                if action == 'rest':
                    self.assertTrue(next(b for b in st.song['score']['patterns']['G']['beats'] if b['voice'] == 1)['notes'])
                if action != 'cut':
                    self.assertNotIn('clipboard', result)
                st.undo()
                self.assertEqual(st.song_path.read_bytes(), original)
        # A duration edit may now select the continuation without selecting its predecessor.
        st.score_command(dict(action='set_duration', track='guitar', voice=0, selection=groups,
            written=dict(value=8, dots=0, tuplet=[1, 1]), revision=st.text_sha()))
        st.undo()
        self.assertEqual(st.song_path.read_bytes(), original)

    def test_phrase_paste_extension_boundary_replacement_and_strict_history(self):
        from vulturetracker import tablature
        st = self.open(complete_section_song())
        original = st.song_path.read_bytes()
        clip = tablature.capture_score_clipboard(st.song, 'G', ['n0'], 'bar3')
        self.assertFalse(clip['ties'])  # Independent copy of an incoming continuation.
        for pattern, row, occurrence, replace in ((3, 48, 'bar4', False), (1, 42, 'bar2', True)):
            with self.subTest(replace=replace):
                result = st.score_edit(dict(op='beats_paste', pattern=pattern, row=row, occurrence=occurrence,
                    clipboard=clip, across=True, replace=replace, revision=st.text_sha()))
                self.assertEqual(len(st.song['orders']), 4 if replace else 5)
                self.assertTrue(result['selection']['range'])
                copied = tablature.capture_score_clipboard(st.song, selection=result['selection']['range'], raw_patterns=st.mod.patterns)
                self.assertTrue(copied['beats'])
                api.compile_song(st.song_path)
                if replace:
                    bass = next(b for b in st.song['score']['patterns']['F']['beats'] if b['voice'] == 1)
                    self.assertEqual(bass, next(b for b in complete_section_song()['score']['patterns']['F']['beats'] if b['voice'] == 1))
                saved = st.song_path.read_bytes()
                st.undo(); self.assertEqual(st.song_path.read_bytes(), original)
                st.undo(redo=True); self.assertEqual(st.song_path.read_bytes(), saved)
                st.undo(); self.assertEqual(st.song_path.read_bytes(), original)


class TestMeasureMenuState(unittest.TestCase):
    """TuxGuitar's Measure menu (Add, Remove, Clean, Copy/Paste) on whole-order measures, one Undo each."""

    def open(self, song):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        base = Path(tmp.name)
        write_wav(base / 'tone.wav', RATE, [sine(220)])
        self.path = base / 'song.yaml'
        self.path.write_bytes(('# Keep this source comment.\n' + api.to_yaml(song)).encode())
        self.st = gui.State(self.path, headless=True)
        self.addCleanup(lambda: self.st.close())
        self.before = self.path.read_bytes()
        return self.st

    def run_command(self, **edit):
        return self.st.score_command(dict(edit, revision=self.st.text_sha()))

    def undone(self):
        self.st.undo()
        self.assertEqual(self.path.read_bytes(), self.before)

    def segment(self, a, b, tracks=('guitar',)):
        """What the page's Copy measures holds: the measures' beats of `tracks`, their ties, meters without markers."""
        score, orders = self.st.song['score'], [str(o) for o in self.st.song['orders']]
        ids = score['order_ids']
        units = [dict(pattern=orders[i], rows=self.st.song['patterns'][orders[i]]['rows'],
                      row_step=score['patterns'][orders[i]]['row_step'],
                      beats=[b for b in score['patterns'][orders[i]]['beats'] if b['track'] in tracks],
                      measure=next(({k: v for k, v in m.items() if k not in ('id', 'from', 'to', 'marker')}
                                    for m in score['measures'] if m['from']['occurrence'] == ids[i]), None))
                 for i in range(a, b + 1)]
        ties = [{side: dict(unit=ids.index(t[side]['occurrence']) - a, note=t[side]['note']) for side in ('from', 'to')}
                for t in score['ties'] if all(a <= ids.index(t[s]['occurrence']) <= b for s in ('from', 'to'))]
        return dict(tracks=list(tracks), units=units, ties=ties)

    def test_add_measure_clones_the_previous_meter_keeps_raw_cells_and_widens_the_section(self):
        st = self.open(repeat_song())
        result = self.run_command(action='measure_add', at=1, count=2)
        self.assertEqual([str(o) for o in st.song['orders']], ['a', 'bar1', 'bar2', 'b', 'c'])
        self.assertEqual(st.song['patterns']['bar1']['rows'], 48)
        self.assertIn('T53', self.path.read_text())   # pattern a's raw tempo cell stays
        added = [m for m in st.song['score']['measures'] if m['from']['occurrence'] not in ('first', 'second', 'third')]
        self.assertEqual([{k: m[k] for k in m if k not in ('id', 'from', 'to')} for m in added], [{'meter': [4, 4]}] * 2)
        self.assertEqual(st.song['sections'], {'first': [0, 3], 'outro': [4, 5]})
        self.assertEqual(len(st.history), 1)
        self.assertTrue(result['report'].startswith('Added 2 measures at 2'))
        self.undone()

    def test_remove_measure_drops_its_time_pattern_and_entry_and_refuses_ties_and_removing_all(self):
        st = self.open(repeat_song())
        self.run_command(action='measure_remove', **{'from': 1, 'to': 1})
        self.assertEqual([str(o) for o in st.song['orders']], ['a', 'c'])
        self.assertNotIn('b', st.song['patterns'])
        self.assertEqual([m['id'] for m in st.song['score']['measures']], ['a', 'c'])
        self.assertEqual(st.song['sections'], {'first': [0, 1], 'outro': [1, 2]})
        self.undone()
        with self.assertRaisesRegex(ValueError, 'keep at least one'):
            self.run_command(action='measure_remove', **{'from': 0, 'to': 2})
        self.open(score_song())   # tie_a in bar 1 continues into bar 2
        result = self.run_command(action='measure_remove', **{'from': 1, 'to': 1})
        self.assertFalse(self.st.song['score']['ties'])
        self.assertIn('tie', result['report'])
        self.undone()

    def test_clean_measure_removes_the_tracks_beats_and_refuses_a_crossing_tie(self):
        st = self.open(score_song())
        self.run_command(action='measure_clean', track='guitar', **{'from': 0, 'to': 0})
        self.assertFalse(st.song['score']['patterns']['a']['beats'])
        self.assertTrue(st.song['score']['patterns']['b']['beats'])
        self.assertFalse(st.song['score']['ties'])
        self.undone()
        self.run_command(action='measure_clean', track='guitar', **{'from': 0, 'to': 1})
        self.assertEqual([p['beats'] for p in st.song['score']['patterns'].values()], [[], []])
        self.assertEqual(st.song['score']['ties'], [])
        self.assertIn('X40', self.path.read_text())   # raw tracker cells are not the track's beats
        self.assertEqual(len(st.history), 1)
        self.undone()

    def test_paste_replace_and_insert_copy_beats_ties_and_meters_with_fresh_ids(self):
        st = self.open(score_song())
        segment = self.segment(0, 1)
        self.run_command(action='measure_paste', mode='insert', at=2, count=2, segment=segment, track='guitar')
        self.assertEqual([str(o) for o in st.song['orders']], ['a', 'b', 'bar1', 'bar2', 'bar3', 'bar4'])
        score = st.song['score']
        pitches = lambda name: sorted(n['pitch'] for b in score['patterns'][name]['beats'] for n in b['notes'])
        self.assertEqual([pitches(n) for n in ('bar1', 'bar2', 'bar3', 'bar4')], [pitches('a'), pitches('b')] * 2)
        self.assertEqual(len(score['ties']), 3)   # the source tie and one per pasted copy
        pasted = score['ties'][1]
        self.assertEqual((pasted['from']['occurrence'], pasted['to']['occurrence']), tuple(score['order_ids'][2:4]))
        self.assertNotIn('X40', st.song['patterns']['bar1'].get('data', ''))   # one track copied: no raw cells
        self.undone()
        self.run_command(action='measure_paste', mode='insert', at=0, segment=dict(segment, all_tracks=True), track='guitar')
        self.assertIn('X40', st.song['patterns']['bar1']['data'])   # all tracks: the raw cells come too
        self.undone()
        st = self.open(repeat_song())
        self.run_command(action='measure_paste', mode='replace', at=2, count=1, segment=self.segment(0, 0), track='guitar')
        heads = {name: [n['pitch'] for b in st.song['score']['patterns'][name]['beats'] for n in b['notes']] for name in 'abc'}
        self.assertEqual(heads, {'a': [64], 'b': [66], 'c': [64]})
        self.assertEqual([str(o) for o in st.song['orders']], ['a', 'b', 'c'])
        self.undone()
        # Past the end, TG adds the measures it needs.
        self.run_command(action='measure_paste', mode='replace', at=2, count=2, segment=self.segment(0, 0), track='guitar')
        self.assertEqual([str(o) for o in st.song['orders']], ['a', 'b', 'c', 'bar1'])
        self.undone()

    @staticmethod
    def full_bar_song(shared=False):
        """repeat_song with bar 3 (pattern c, the last order) full of four quarter notes; `shared` plays c twice."""
        from tests.test_tablature import beat, note
        song = repeat_song()
        song['score']['patterns']['c']['beats'] = [beat(f'q{i}', [i, 1], [dict(note(f'n{i}', 67, 1, 3), velocity=90)])
                                                   for i in range(4)]
        if shared:
            song['orders'].append('c')
            song['score']['order_ids'].append('fourth')
            song['score']['measures'].append(dict(id='d', meter=[4, 4], **{'from': dict(occurrence='fourth', at=[0, 1]),
                                                                          'to': dict(occurrence='fourth', at=[4, 1])}))
        return song

    def insert_rest(self, free):
        return self.run_command(action='insert_rest', occurrence='third', track='guitar', voice=0, at=[0, 1],
                                written=dict(value=4, dots=0, tuplet=[1, 1]), rest_id='r1', free=free)

    def test_free_edit_insert_rest_overfills_the_bar_grows_its_pattern_and_is_flagged_long(self):
        from vulturetracker.tablature import measure_errors
        st = self.open(self.full_bar_song())
        with self.assertRaisesRegex(ValueError, 'needs room in this measure'):   # strict, TG's default
            self.insert_rest(False)
        result = self.insert_rest(True)
        self.assertTrue(result['overfull'])
        self.assertEqual(st.song['patterns']['c']['rows'], 60)   # five quarters at 12 rows each
        self.assertEqual(st.song['score']['measures'][2]['meter'], [4, 4])
        self.assertEqual(st.song['score']['measures'][2]['to'], {'occurrence': 'third', 'at': [5, 1]})
        ats = sorted(Fraction(*b['at']) for b in st.song['score']['patterns']['c']['beats'])
        self.assertEqual(ats, [0, 1, 2, 3, 4])
        rows = {p.name: len(p.rows) for p in st.mod.patterns}
        self.assertIn((3, ['long']), [(e['bar'], e['errors']) for e in measure_errors(st.song, rows)])
        self.assertEqual(len(st.history), 1)
        from vulturetracker import export
        with self.assertRaisesRegex(ValueError, 'bar 3 is overfull'):   # notation files place bars by their meter
            export.prepare(st, {'destination': 'out', 'fmt': 'tg', 'name': 'x'})
        # Repair, as in TG: remove what overflows, then the bar's own meter shrinks it back.
        st.score_edit(dict(op='beat_delete', pattern='c', beat='q3', revision=st.text_sha()))
        self.run_command(action='measure_meter', at=2, meter=[4, 4])
        self.assertEqual(st.song['patterns']['c']['rows'], 48)
        self.assertEqual(st.song['score']['measures'][2]['to'], {'occurrence': 'third', 'at': [4, 1]})
        rows = {p.name: len(p.rows) for p in st.mod.patterns}
        self.assertNotIn(3, [e['bar'] for e in measure_errors(st.song, rows)])
        st.undo(); st.undo(); self.undone()
        self.open(self.full_bar_song(shared=True))
        with self.assertRaisesRegex(ValueError, 'make this measure unique'):
            self.insert_rest(True)
        self.assertEqual(self.path.read_bytes(), self.before)

    def move(self, direction, occurrence='first', at=(0, 1)):
        return self.run_command(action='move_beats', occurrence=occurrence, track='guitar', voice=0, at=list(at),
                                direction=direction)

    def placed(self):
        """Each guitar note as (occurrence, quarter offset) by note id, through the order list."""
        st = self.st
        out = {}
        for oid, name in zip(st.song['score']['order_ids'], map(str, st.song['orders'])):
            for b in st.song['score']['patterns'][name]['beats']:
                for n in b['notes']:
                    out.setdefault(n['id'], (oid, Fraction(*b['at'])))
        return out

    def test_move_beats_right_and_left_cross_bar_lines_keep_ties_and_undo(self):
        # score_song: bar 1 holds the chord (0), triplets (1..2) and tie_a (3.5, an eighth); bar 2 starts with tie_b.
        st = self.open(score_song())
        before = self.placed()
        self.move('right')   # by the chord's quarter: tie_a crosses into bar 2 at 0.5, tie_b moves to 1
        after = self.placed()
        self.assertEqual(after['e'], ('first', 1))
        self.assertEqual(after['tie_a'], ('second', Fraction(1, 2)))
        self.assertEqual(after['tie_b'], ('second', 1))
        self.assertEqual(st.song['score']['ties'], [{'from': {'occurrence': 'second', 'note': 'tie_a'},
                                                     'to': {'occurrence': 'second', 'note': 'tie_b'}}])
        self.assertEqual(len(st.history), 1)
        self.undone()
        self.move('left')    # removes the chord's span, pulls the rest left: tie_b comes back into bar 1 at 3
        after = self.placed()
        self.assertNotIn('e', after)
        self.assertEqual(after['t0'], ('first', 0))
        self.assertEqual(after['tie_a'], ('first', Fraction(5, 2)))
        self.assertEqual(after['tie_b'], ('first', 3))
        self.assertEqual(st.song['score']['ties'], [{'from': {'occurrence': 'first', 'note': 'tie_a'},
                                                     'to': {'occurrence': 'first', 'note': 'tie_b'}}])
        self.undone()
        self.assertEqual(self.placed(), before)

    def test_move_beats_refuses_a_pattern_played_at_another_order(self):
        song = score_song()
        song['orders'] = ['a', 'b', 'a']
        song['score']['order_ids'] = ['first', 'second', 'third']
        self.open(song)
        with self.assertRaisesRegex(ValueError, 'pattern a also plays at order 3.*unique'):
            self.move('right')
        self.assertEqual(self.path.read_bytes(), self.before)

    def test_measure_errors_are_tuxguitars_gap_and_short_voice_checks(self):
        from vulturetracker.tablature import measure_errors
        rows = {'a': 48, 'b': 48, 'c': 48}
        # score_song has no measure entries: each order is a bar. Bar 1 rests between beat 2 and 3.5; bar 2 ends at 0.5.
        self.assertEqual([(e['bar'], e['errors']) for e in measure_errors(score_song(), rows)], [(1, ['gap']), (2, ['short'])])
        self.assertEqual([(e['bar'], e['errors']) for e in measure_errors(repeat_song(), rows)], [(1, ['short']), (2, ['short']), (3, ['short'])])
        st = self.open(score_song())
        self.assertEqual(len(st.score_view()['measure_errors']), 2)

    def onsets(self):
        """What the live engine plays: each note-on's frame and pitch."""
        return sorted((e['frame'], e['pitch']) for e in self.st.mod.native_score['plan']['events'] if e['type'] == 'note_on')

    def test_time_signature_reflows_like_tuxguitar_notes_keep_their_times(self):
        song = repeat_song()   # bars a b c, one quarter note each at their start; a holds a T53 tempo cell
        for m in song['score']['measures']:   # without its repeat, so performed times equal written times
            m.pop('repeat_open', None), m.pop('repeat_close', None)
        st = self.open(song)
        result = self.run_command(action='measure_meter', at=2, meter=[3, 4])
        self.assertEqual(st.song['patterns']['c']['rows'], 36)
        self.assertEqual({k: st.song['score']['measures'][2][k] for k in ('meter', 'to')},
                         {'meter': [3, 4], 'to': {'occurrence': 'third', 'at': [3, 1]}})
        self.assertEqual(result['report'], 'Time signature 3/4 from measure 3; notes keep their times.')
        self.undone()
        # 6/8 from bar 2 to the end: b and c become three quarters long and c's note, still at quarter 8 of the
        # song, now falls a quarter into c. The live engine plays every note at the same frame as before.
        from vulturetracker.openmpt import LoadedModule

        def seconds():   # the length libopenmpt plays the backing IT with its score plan for (what IT/WAV exports use)
            pair = st.prepared_playback(48000, whole=True)
            with LoadedModule(pair['backing_it'], 48000, 1, plan=pair['plan']) as module:
                return module.duration()
        played, before = self.onsets(), seconds()
        self.run_command(action='measure_meter', at=1, meter=[6, 8], to_end=True)
        self.assertEqual([st.song['patterns'][n]['rows'] for n in 'abc'], [48, 36, 36])
        self.assertEqual([m['meter'] for m in st.song['score']['measures']], [[4, 4], [6, 8], [6, 8]])
        self.assertEqual([b['at'] for b in st.song['score']['patterns']['c']['beats']], [[1, 1]])
        self.assertEqual(self.onsets(), played)
        # The tracker side: Pattern shows c's note on row 12 of its bar, and the backing IT with its plan plays two
        # quarters shorter, at bar 1's tempo from row 12 on (T53 = 83 BPM).
        self.assertEqual(parse_cell(st.pattern_rows(2, occurrence='third')['display_rows'][12][0]).note, 67)
        self.assertAlmostEqual(before - seconds(), 2 * 60 / 83, delta=0.01)
        self.assertIn('T53', self.path.read_text())   # bar 1's tracker tempo cell is untouched
        self.assertEqual(len(st.history), 1)
        self.undone()
        with self.assertRaisesRegex(ValueError, 'has tracker commands'):
            self.run_command(action='measure_meter', at=0, meter=[3, 4])   # pattern a's T53 would move
        with self.assertRaisesRegex(ValueError, 'whole number of rows'):
            self.run_command(action='measure_meter', at=1, meter=[1, 64])
        self.assertEqual(self.path.read_bytes(), self.before)

    def test_time_signature_reflow_standalone_it_build_keeps_note_rows_and_export_writes_the_same_it(self):
        """The standalone .it, as `python -m vulturetracker build` writes it (no native plan beside it), before and after
        a re-flow: reopened with the IT reader and libopenmpt, every note attack sits on the same absolute row and the
        module is a bar's worth shorter. RENDER & EXPORT's IT writes the same standalone module."""
        import subprocess
        import sys
        from vulturetracker import export
        from vulturetracker.itreader import read_it
        from vulturetracker.openmpt import LoadedModule
        song = score_song()
        song['patterns']['a']['data'] = ''   # no tracker commands in the re-barred range
        st = self.open(song)

        def build(name):
            out = self.path.parent / name
            run = subprocess.run([sys.executable, '-m', 'vulturetracker', 'build', str(self.path), '-o', str(out)],
                                 cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True)
            self.assertEqual(run.returncode, 0, run.stderr + run.stdout)
            data = out.read_bytes()
            module, _ = read_it(data)
            attacks, origin = [], 0
            for index in module.orders:
                if index >= 254:
                    continue
                rows = module.patterns[index].rows
                attacks += [(origin + r, ch, cell.note) for r, cells in enumerate(rows) for ch, cell in enumerate(cells)
                            if cell.note is not None and cell.note < 120]
                origin += len(rows)
            with LoadedModule(data) as played:
                return sorted(attacks), origin, played.duration()
        attacks, rows, seconds = build('before.it')
        self.assertEqual(len(attacks), 6, attacks)   # the chord's two notes, three triplets, tie_a (tie_b continues it)
        self.run_command(action='measure_meter', at=0, meter=[2, 4], to_end=True)
        self.assertEqual([str(o) for o in st.song['orders']], ['a', 'b', 'bar1'])
        after, after_rows, after_seconds = build('after.it')
        self.assertEqual(after, attacks)   # every attack on the same absolute row, channel and note
        self.assertEqual((rows, after_rows), (96, 72))   # two 4/4 bars became three 2/4 bars
        self.assertAlmostEqual(seconds - after_seconds, 24 * 2 * 2.5 / 120, delta=0.01)   # 24 rows of speed 2 at 120 BPM
        result = export.run(export.prepare(st, {'fmt': 'it', 'name': 'reflowed'}), gui._encode)
        self.assertEqual(result['status'], 'done', result)
        self.assertEqual((self.path.parent / 'reflowed.it').read_bytes(), (self.path.parent / 'after.it').read_bytes())

    def test_time_signature_reflow_adds_bars_carries_ties_and_refuses_a_straddling_note(self):
        song = score_song()
        song['patterns']['a']['data'] = ''   # no tracker commands in the re-barred range
        st = self.open(song)
        played = self.onsets()
        # 2/4 to the end: the four quarters of bar 1 and bar 2's opening eighth need three 2/4 bars; tie_a (quarter
        # 3.5) and tie_b (quarter 4) now meet inside bar 2, keeping their tie.
        result = self.run_command(action='measure_meter', at=0, meter=[2, 4], to_end=True)
        self.assertEqual([str(o) for o in st.song['orders']], ['a', 'b', 'bar1'])
        self.assertEqual([st.song['patterns'][n]['rows'] for n in ('a', 'b', 'bar1')], [24, 24, 24])
        self.assertTrue(result['report'].endswith('1 measure added.'))
        tie = st.song['score']['ties'][0]
        self.assertEqual((tie['from']['occurrence'], tie['to']['occurrence']), ('second', st.song['score']['order_ids'][2]))
        self.assertEqual(self.onsets(), played)
        self.undone()
        self.run_command(action='measure_meter', at=0, meter=[1, 8])   # opening chord splits into tied eighths
        self.assertEqual(self.onsets(), played)
        self.assertGreater(len(st.song['score']['ties']), 1)
        self.undone()

def native_it_song():
    """Two 4/4 bars: guitar quarters with authored velocities (one also a volume), a tie across the bar line and a raw
    tracker pan command on channel 6 that the score does not own."""
    from tests.test_tablature import beat, note
    song = score_song()
    song['patterns']['a']['data'] = '00: ... .. ... ... | ... .. ... ... | ... .. ... ... | ... .. ... ... | ... .. ... ... | ... .. ... X40\n'
    vel = lambda n, v, **extra: dict(n, velocity=v, **extra)
    song['score']['patterns']['a']['beats'] = [
        beat('q0', [0, 1], [vel(note('n0', 64, 1, 0), 95)]), beat('q1', [1, 1], [vel(note('n1', 62, 2, 3), 64, volume=32)]),
        beat('q2', [2, 1], [vel(note('n2', 60, 2, 1), 127)]), beat('q3', [3, 1], [vel(note('n3', 64, 1, 0), 95)])]
    song['score']['patterns']['b']['beats'] = [
        beat('h0', [0, 1], [vel(note('m0', 64, 1, 0), 95)]), beat('h1', [1, 1], [vel(note('m1', 67, 1, 3), 1)]),
        beat('h2', [2, 1], [vel(note('m2', 64, 1, 0), 95)], value=2)]
    song['score']['ties'] = [{'from': {'occurrence': 'first', 'note': 'n3'}, 'to': {'occurrence': 'second', 'note': 'm0'}}]
    song['score']['measures'] = [dict(id=m, meter=[4, 4], **{'from': dict(occurrence=o, at=[0, 1]), 'to': dict(occurrence=o, at=[4, 1])})
                                 for m, o in (('a', 'first'), ('b', 'second'))]
    return song


def native_percussion_it_song():
    """A pitched guitar plus a keymapped kit: chords, two voices, keys 1/100, per-note instrument and raw pan."""
    from tests.test_tablature import beat, note
    song = native_it_song()
    song['samples'] = {1: dict(file='tone.wav'), 2: dict(file='tone.wav', volume=32),
                       3: dict(file='tone.wav', volume=48)}
    song['instruments'] = {
        1: dict(name='Guitar', sample=1),
        2: dict(name='Kit', keymap=[dict(notes='C-0..B-9', sample=2, play_note='C-5'),
                                  dict(notes='F#3', sample=3, play_note='D-5')]),
        3: dict(name='Other drum', keymap=[dict(notes='C-0..B-9', sample=3, play_note='C-4')])}
    song['score']['tracks']['guitar'].update(tuning=[64, 59], channels=[0, 1])
    song['score']['tracks']['drums'] = dict(tuning=[0, 0, 0], channels=[2, 3, 4], instrument=2,
                                            capo=0, midi=dict(bank=128, program=0))
    song['score']['patterns']['a']['beats'] += [
        beat('drums0', [0, 1], [dict(note('kick', 36, 1, 36), velocity=127),
                              dict(note('hat', 42, 2, 42), velocity=95)], track='drums'),
        beat('drums1', [0, 1], [dict(note('highkey', 100, 3, 100), instrument=3, velocity=127)],
             voice=1, track='drums'),
        beat('drums2', [2, 1], [dict(note('lowkey', 1, 1, 1), velocity=64, volume=40)], track='drums')]
    song['score']['patterns']['b']['beats'] += [
        beat('drums3', [1, 1], [dict(note('quiet', 38, 1, 38), velocity=0)], track='drums')]
    return song


def native_technique_it_song():
    """A mixed kit/guitar technique fixture, including tied notes and repeated written patterns."""
    song = native_percussion_it_song()
    song['module']['tempo'] = 160  # TG palm/dead gates fall exactly on IT ticks at this tempo.
    song['samples'][1]['loop'] = dict(start=0)
    song['instruments'][1]['volume_envelope'] = dict(nodes=[[0, 64], [1, 64], [3, 0]], sustain=1)
    a, b = (song['score']['patterns'][p]['beats'] for p in ('a', 'b'))
    a[0]['notes'][0].update(ghost=True, staccato=True)
    a[1]['notes'][0].update(accent=True, palm_mute=True, hammer=True)
    a[2]['notes'][0].update(heavy_accent=True, dead=True)
    a[3]['notes'][0].update(staccato=True, hammer=True)
    b[1]['notes'][0].update(velocity=95, hammer=True)
    b[2]['notes'][0].update(let_ring=True)
    a[4]['notes'][0].update(staccato=True, accent=True)
    a[4]['notes'][1].update(palm_mute=True, ghost=True)
    a[5]['notes'][0].update(dead=True, heavy_accent=True)
    song['score']['measures'][1]['repeat_close'] = 1
    return song


def native_pitch_it_song():
    """Sequential bend, vibrato and shift slide, then a plain note; original samples/keymap remain editable."""
    from tests.test_tablature import beat, note
    song = native_it_song()
    song['module']['title'] = 'Native IT pitch fixture'
    song['score']['ties'] = []
    # The 441-Hz, .5-second probe contains 220.5 cycles; wrap at 220 whole cycles, not its half-cycle end.
    song['samples'][1]['loop'] = dict(start=0, end=22000)
    song['instruments'] = {1: dict(keymap=[dict(notes='C-0..B-9', sample=1, play_note='C-5')],
        volume_envelope=dict(nodes=[[0, 64], [1, 64], [3, 0]], sustain=1))}
    curve = dict(points=[dict(position=0, value=0), dict(position=6, value=4), dict(position=12, value=0)])
    song['score']['patterns']['a']['beats'] = [
        beat('bend', [0, 1], [dict(note('bend', 64, 1, 0), velocity=95, bend=curve)]),
        beat('vibrato', [1, 1], [dict(note('vibrato', 64, 1, 0), velocity=95, vibrato=True)]),
        beat('slide', [2, 1], [dict(note('slide', 64, 1, 0), velocity=95, slide=True)]),
        beat('plain', [3, 1], [dict(note('plain', 66, 1, 2), velocity=95)])]
    song['score']['patterns']['b']['beats'] = []
    return song


def native_articulations_it_song():
    """Notation-only tap/slap/pop on the existing keyed, swung attack probe."""
    song = native_swing_it_song()
    song['module']['title'] = 'Native IT articulations'
    for beat, flag in zip(song['score']['patterns']['a']['beats'], ('tapping', 'slapping', 'popping')):
        beat['notes'][0][flag] = True
    return song


def native_fade_it_song():
    from tests.test_tablature import beat, note
    song=native_grace_it_song();song['module']['title']='Native IT fade'
    song['score'].pop('measures',None)
    song['score']['patterns']['a']['beats']=[
        beat(identity,[at,1],[dict(note(identity,pitch,1,pitch-64),velocity=velocity,**effects)])
        for identity,at,pitch,velocity,effects in [('fade',0,64,95,{'fade_in':True}),
            ('plain',1,66,63,{}),('soft',2,64,79,{'fade_in':True,'volume':32}),('reset',3,64,95,{})]]
    song['score']['patterns']['b']['beats']=[]
    return song


def fade_render_metrics(path,data,rate):
    """Independent gain trajectories, normalized against the same unchanged instrument/sample without fade."""
    import numpy as np
    from vulturetracker.openmpt import LoadedModule
    from vulturetracker.itreader import read_it
    song=api.from_yaml(path.read_text());plain=copy.deepcopy(song)
    for p in plain['score']['patterns'].values():
        for b in p['beats']:
            for n in b['notes']:n.pop('fade_in',None)
    pair=api.prepare_playback(song,path.parent,rate);reference=api.prepare_playback(plain,path.parent,rate)
    plain_it=api.compile_song(plain,path.parent)[0]
    arrays=[]
    for backing,plan in ((pair['backing_it'],pair['plan']),(data,None),(reference['backing_it'],reference['plan']),(plain_it,None)):
        with LoadedModule(backing,rate,1,plan=plan) as mod:
            arrays.append(np.frombuffer(mod.render(rate=rate,oversample=1,floats=True,max_seconds=2.2),'<f4').reshape(-1,2).mean(axis=1))
    native,it,ref_native,ref_it=arrays
    module,_=read_it(data);baseline,_=read_it(plain_it)
    attacks=[e for e in pair['plan']['events'] if e['type']=='note_on']
    checks=[]
    for attack in attacks:
        start=Fraction(*attack['at']);first=int(start*24/module.speed)
        native_gains=[e for e in pair['plan']['events'] if e['type']=='gain' and e['id']==attack['id']]
        volume=baseline.patterns[0].rows[first][0].volcmd
        current=volume
        for row in range(first,first+12):
            cell=module.patterns[0].rows[row][0]
            if cell.volcmd is not None:current=cell.volcmd
            # Fixed 4ms windows centered half a row after each tracker change, beyond the mixer ramp.
            at=Fraction(row*module.speed,24)+Fraction(module.speed,48)
            center=round(float(at)*rate/2)
            it_center=round((row+.5)*module.speed*int(rate*2.5/120))
            width=round(rate*.002)
            def ratio(a,b,c):
                x,y=a[c-width:c+width],b[c-width:c+width]
                denominator=np.dot(y,y)
                return float(np.sqrt(np.dot(x,x)/denominator)) if denominator else (0 if not np.any(x) else float('inf'))
            ng,ig=ratio(native,ref_native,center),ratio(it,ref_it,it_center)
            frames=np.arange(center-width,center+width)
            expressions=np.full(len(frames),1.0)
            for event in native_gains:
                expressions[frames>=event['frame']]=event['expression']/127
            reference_window=ref_native[center-width:center+width]
            expected=float(np.sqrt(np.dot(reference_window*expressions,reference_window*expressions)/np.dot(reference_window,reference_window)))
            checks.append(dict(row=row,native=ng,it=ig,expected=expected,it_expected=current/volume))
    tail=[int(np.flatnonzero(abs(a)>1e-6)[-1]) for a in (native,it)]
    result=dict(max_native_error=max(abs(c['native']-c['expected']) for c in checks),
                max_it_cell_error=max(abs(c['it']-c['it_expected']) for c in checks),
                max_native_it_gain_difference=max(abs(c['native']-c['it']) for c in checks),tail=tail,checks=checks)
    # Independently locate the first fade's steps from PCM ratios, not a fitted alignment.
    def detected(a,b,frame,old,new,radius):
        indices=np.arange(max(0,frame-radius),min(len(a),frame+radius+1))
        valid=abs(b[indices])>max(abs(b))*0.05
        indices=indices[valid]
        ratios=a[indices]/b[indices]
        crossed=ratios >= old+(new-old)*.95
        return int(indices[np.flatnonzero(crossed)[0]]) if np.any(crossed) else None
    first_gains=[e for e in pair['plan']['events'] if e['type']=='gain' and e['id']==attacks[0]['id']]
    native_offsets=[]
    for previous,event in zip(first_gains,first_gains[1:]):
        if not .04*rate<event['frame']<.45*rate:continue
        found=detected(native,ref_native,event['frame'],previous['expression']/127,event['expression']/127,4)
        if found is not None:
            first_valid=event['frame']+int(np.flatnonzero(abs(ref_native[event['frame']:event['frame']+5])>max(abs(ref_native))*.05)[0])
            if found!=first_valid:raise AssertionError(('native fade step timing',found,first_valid))
            native_offsets.append(found-event['frame'])
    result['native_step_offsets']=native_offsets
    it_offsets=[]
    for row in range(1,12):
        old=module.patterns[0].rows[row-1][0].volcmd/48
        new=module.patterns[0].rows[row][0].volcmd/48
        frame=row*module.speed*int(rate*2.5/120)
        found=detected(it,ref_it,frame,old,new,round(rate*.005))
        if found is not None:it_offsets.append(found-frame)
    result['it_step_settle_frames']=it_offsets
    if (result['max_native_error']>.0001 or result['max_it_cell_error']>.001 or
            result['max_native_it_gain_difference']>.04 or not native_offsets or
            len(it_offsets)!=11 or min(it_offsets)<0 or max(it_offsets)>rate*.005 or abs(tail[1]-tail[0])>100):
        raise AssertionError((rate,result))
    return result


def native_swing_it_song():
    """Eighth and sixteenth feel in adjacent measures, alternate mapped pitch, then a plain successor."""
    from tests.test_tablature import beat, note
    song=native_grace_it_song();song['module']['title']='Native IT swing'
    song['score']['patterns']['a']['beats']=[
        beat(identity,at,[dict(note(identity,pitch,1,pitch-64),velocity=velocity)],value)
        for identity,at,pitch,velocity,value in [('e0',[0,1],64,95,8),('e1',[1,2],66,63,8),
            ('s0',[2,1],64,95,16),('s1',[9,4],66,63,16),('plain',[3,1],64,95,4)]]
    song['score']['measures']=[dict(id=identity,meter=[2,4],swing=mode,**{
        'from':dict(occurrence='first',at=[start,1]),'to':dict(occurrence='first',at=[start+2,1])})
        for identity,start,mode in [('eighth',0,'eighth'),('sixteenth',2,'sixteenth')]]
    return song


def swing_render_metrics(path,data,rate):
    """Reuse the keyed attack probe; measure offsets independently before comparing IT tick rounding."""
    from vulturetracker.openmpt import LoadedModule
    pair=api.prepare_playback(path,sample_rate=rate);renders=[]
    for backing,plan in ((pair['backing_it'],pair['plan']),(data,None)):
        with LoadedModule(backing,rate,1,plan=plan) as mod:
            renders.append(mod.render(rate=rate,oversample=1,max_seconds=2.2))
    metrics=repetition_render_metrics(*renders,rate,pair['plan'])
    for actual,event in zip(metrics['attacks'],[e for e in pair['plan']['events'] if e['type']=='note_on']):
        shift=int(Fraction(*event['at'])*24)*int(rate*2.5/120)-event['frame']
        if abs(actual['shift_frames']-shift)>1 or actual['settled_rms_error']>.025 or abs(actual['settled_level_ratio']-1)>.02:
            raise AssertionError((rate,shift,actual))
        if any(abs(pitch-(200 if event['pitch']==66 else 0))>.5 for pitch in actual['pitch_cents']):
            raise AssertionError((rate,actual))
    if abs(metrics['last_audible_frames'][1]-metrics['last_audible_frames'][0])>(1 if rate==48000 else 100):
        raise AssertionError((rate,metrics))
    return metrics


def native_stroke_it_song():
    """Opposite three-string brushes, then plain successors; keyed whole-cycle tone probe."""
    from tests.test_tablature import beat, note
    song=native_pitch_it_song()
    song['module']['title']='Native IT strokes'
    song['instruments'][1]['volume_envelope']=dict(nodes=[[0,0],[1,64],[2,64],[3,0]],sustain=2)
    song['instruments'][1]['keymap']=[dict(notes='C-0..B-9',sample=1,play_note='C-5'),
        dict(notes='B-4',sample=1,play_note='D-5'),dict(notes='G-4',sample=1,play_note='E-5')]
    beats=[]
    for name,at,direction in [('down',0,'down'),('up',2,'up'),('plain',3,None)]:
        b=beat(name,[at,1],[dict(note(f'{name}{s}',pitch,s,0),velocity=velocity)
            for s,pitch,velocity in [(1,64,127),(2,59,95),(3,55,63)]])
        if direction: b['stroke']=dict(direction=direction,value=4)
        beats.append(b)
    song['score']['patterns']['a']['beats']=beats
    return song


def stroke_render_metrics(path, data, rate):
    """Solo the existing parent channels to measure simultaneous keyed voices with the shared attack probe."""
    from vulturetracker.measure import patch_it
    from vulturetracker.openmpt import LoadedModule
    pair=api.prepare_playback(path,sample_rate=rate)
    result={}
    for ch in (0,1,2):
        renders=[]
        for backing,plan in ((pair['backing_it'],pair['plan']),(data,None)):
            with LoadedModule(patch_it(backing,silenced=[c for c in range(6) if c!=ch]),rate,1,plan=plan) as mod:
                renders.append(mod.render(rate=rate,oversample=1,max_seconds=2.2))
        plan=dict(pair['plan'],events=[e for e in pair['plan']['events'] if e['ch']==ch])
        metrics=repetition_render_metrics(*renders,rate,plan)
        for actual,event in zip(metrics['attacks'],[e for e in plan['events'] if e['type']=='note_on']):
            expected=int(Fraction(*event['at'])*24)*int(rate*2.5/120)-event['frame']
            if abs(actual['shift_frames']-expected)>1 or actual['settled_rms_error']>.025 or abs(actual['settled_level_ratio']-1)>.02:
                raise AssertionError((rate,ch,expected,actual))
            if any(abs(pitch-ch*200)>.5 for pitch in actual['pitch_cents']):
                raise AssertionError((rate,ch,actual))
        if abs(metrics['last_audible_frames'][1]-metrics['last_audible_frames'][0])>(1 if rate==48000 else 100):
            raise AssertionError((rate,ch,metrics))
        result[ch]=metrics
    return result


def native_grace_it_song():
    """Origin fallback, delayed main and before-beat prefix, with independently keyed grace samples."""
    from tests.test_tablature import beat, note
    song=native_repetition_it_song()
    song['module']['title']='Native IT grace notes'
    song['score']['patterns']['a']['beats']=[
        beat('origin',[0,1],[dict(note('origin',64,1,0),velocity=95,
            grace=dict(fret=2,value=16,velocity=47,on_beat=False,transition='none'))]),
        beat('on',[1,1],[dict(note('on',64,1,0),velocity=95,
            grace=dict(fret=2,value=32,velocity=64,on_beat=True,transition='hammer'))]),
        beat('before',[3,1],[dict(note('before',64,1,0),velocity=95,
            grace=dict(fret=2,value=16,velocity=95,on_beat=False,transition='slide'))])]
    return song


def native_harmonic_it_song():
    """Five native harmonic types, duplicate semi layers and plain successors on a whole-cycle probe."""
    from tests.test_tablature import beat, note
    song = native_pitch_it_song()
    song['module']['title'] = 'Native IT harmonic layers'
    song['instruments'][1].pop('keymap')
    song['instruments'][1]['sample'] = 1
    for p in ('a', 'b'):
        song['score']['patterns'][p]['beats'] = []
    for i, kind in enumerate(('natural', 'artificial', 'tapped', 'pinch', 'semi', None, 'natural')):
        fret = 12 if kind == 'natural' else 0
        n = dict(note(f'h{i}',64+fret,1,fret), velocity=95)
        if kind:
            n['harmonic'] = dict(type=kind, **({} if kind=='natural' else dict(data=(0,2,1,3,0)[i] if i<5 else 0)))
        song['score']['patterns']['a' if i<4 else 'b']['beats'].append(beat(f'h{i}',[i%4,1],[n]))
    return song


def harmonic_render_metrics(native, standalone, rate, plan):
    """Whole-cycle harmonic probe: actual spectral layer gains/pitches, bounded attack alignment and final tail."""
    import numpy as np
    a,b=[np.frombuffer(data,np.int16)[::2].astype(float)/32768 for data in (native,standalone)]
    out=[]
    for event in (e for e in plan['events'] if e['type']=='note_on'):
        at=event['frame']
        lo,hi=at+int(.08*rate),at+int(.3*rate)
        bound=int(float(Fraction(*event['at']))*24)+3
        shifts=range(-bound,4)
        shift=min(shifts,key=lambda d:np.mean((a[lo:hi]-b[lo+d:hi+d])**2))
        x,y=a[lo:hi],b[lo+shift:hi+shift]
        pitches=sorted({l['pitch'] for l in event.get('layers',[dict(pitch=event['pitch'])])})
        measured=[]
        for pitch in pitches:
            wanted=441*2**((pitch-60)/12)
            spectra=[abs(np.fft.rfft(z*np.hanning(len(z)),262144)) for z in (x,y)]
            estimates=[]
            for spectrum in spectra:
                left,right=int(wanted*.99*262144/rate),int(wanted*1.01*262144/rate)
                k=left+int(np.argmax(spectrum[left:right]))
                p=np.log(spectrum[k-1:k+2])
                delta=.5*(p[0]-p[2])/(p[0]-2*p[1]+p[2])
                estimates.append((k+delta)*rate/262144)
            t=np.arange(len(x))/rate
            # Complex projection at the independently measured native frequency resolves each distinct layer.
            amps=[abs(np.sum(z*np.hanning(len(z))*np.exp(-2j*np.pi*estimates[0]*t))) for z in (x,y)]
            measured.append(dict(pitch=pitch,cents=[1200*math.log2(f/wanted) for f in estimates],gain_ratio=amps[1]/amps[0]))
        first=max(at,-shift)
        last=at+int(.005*rate)
        tx,ty=a[first:last],b[first+shift:last+shift]
        out.append(dict(id=event['id'],shift_frames=shift,layers=measured,
                        transient_error=float(np.sqrt(np.mean((tx-ty)**2)/np.mean(tx*tx))),
                        settled_error=float(np.sqrt(np.mean((x-y)**2)/np.mean(x*x)))))
    tails=[int(np.flatnonzero(abs(z)>1/32768)[-1]) for z in (a,b)]
    return dict(attacks=out,last_audible_frames=tails)


def native_repetition_it_song():
    """Whole-cycle keyed probe: alternate sample/pitch, delayed picking pulses, plain successor and final release."""
    from tests.test_tablature import beat, note
    song = native_pitch_it_song()
    song['module']['title'] = 'Native IT repeat pulses'
    song['samples'][2] = dict(file='upper.wav', volume=32, loop=dict(start=0, end=22000))
    song['instruments'][1]['keymap'].append(dict(notes='F#5', sample=2, play_note='D-4'))
    song['instruments'][1]['volume_envelope'] = dict(nodes=[[0,0],[1,64],[2,64],[3,0]], sustain=2)
    song['score']['patterns']['a']['beats'] = [
        beat('trill', [0,1], [dict(note('trill',64,1,0), velocity=95, trill=dict(fret=2,value=16))]),
        beat('picking', [1,1], [dict(note('picking',64,1,0), velocity=95, tremolo_picking=dict(value=32))]),
        beat('plain', [2,1], [dict(note('plain',64,1,0), velocity=95)]),
        beat('final', [3,1], [dict(note('final',64,1,0), velocity=95, trill=dict(fret=2,value=4))])]
    return song


def repetition_render_metrics(native, standalone, rate, plan):
    """Compare actual attack waveforms/pitches and the final envelope tail of the keyed pulse probe."""
    import numpy as np
    x, y = [np.frombuffer(data, np.int16)[::2].astype(float) / 32768 for data in (native, standalone)]
    ons = [e for e in plan['events'] if e['type'] == 'note_on']
    offs = {e['id']: e for e in plan['events'] if e['type'] == 'note_off'}
    results = []
    for event in ons:
        frame, end = event['frame'], offs[event['id']]['frame']
        size = min(round(rate*.05), end-frame-round(rate*.004))
        # At 120 BPM IT floors each audio tick; this search bounds accumulated rounding, not musical retiming.
        bound = int(np.ceil(frame / rate * 48)) + 2
        shifts = range(max(-frame,-bound), bound+1)
        settled = round(rate*.005)  # align the new voice, not the preceding voice's phase-dependent cut ramp
        shift = min(shifts, key=lambda d: np.mean((x[frame+settled:frame+size]-y[frame+d+settled:frame+d+size])**2))
        a, b = x[frame:frame+size], y[frame+shift:frame+shift+size]
        pitches = []
        for segment in (a, b):
            segment = segment[round(rate*.025):]
            i = np.flatnonzero((segment[:-1]<0)&(segment[1:]>=0))
            crossings = i-segment[i]/(segment[i+1]-segment[i])
            pitches.append(float(1200*np.log2(rate/np.mean(np.diff(crossings))/441)))
        transient_reference = np.mean(a[:settled]**2)
        transient_error = np.mean((a[:settled]-b[:settled])**2)
        transient_ratio = (float(np.sqrt(transient_error/transient_reference)) if transient_reference
                           else (0.0 if transient_error == 0 else float('inf')))
        results.append(dict(id=event['id'], shift_frames=shift, pitch_cents=pitches,
                            level_ratio=float(np.sqrt(np.mean(b*b)/np.mean(a*a))),
                            settled_level_ratio=float(np.sqrt(np.mean(b[settled:]**2)/np.mean(a[settled:]**2))),
                            transient_rms_error=transient_ratio,
                            settled_rms_error=float(np.sqrt(np.mean((a[settled:]-b[settled:])**2)/np.mean(a[settled:]**2))),
                            relative_rms_error=float(np.sqrt(np.mean((a-b)**2)/np.mean(a*a)))))
    tails = [int(np.flatnonzero(np.abs(signal)>2/32768)[-1]) for signal in (x,y)]
    return dict(attacks=results, last_audible_frames=tails)


def native_whammy_it_song():
    """Whole-cycle probe: a negative dive/return, positive lift/return, mixed curve and plain successor."""
    song = native_pitch_it_song()
    song['module']['title'] = 'Native IT whammy fixture'
    curves = [([(0, 0), (6, -2), (12, 0)], 'dive'), ([(0, 0), (6, 2), (12, 0)], 'raise'),
              ([(0, 0), (3, -1), (9, 1), (12, 0)], 'mixed')]
    for beat, (points, name) in zip(song['score']['patterns']['a']['beats'], curves):
        note = beat['notes'][0]
        for flag in ('bend', 'vibrato', 'slide'):
            note.pop(flag, None)
        beat['id'] = note['id'] = name
        note['tremolo_bar'] = dict(points=[dict(position=p, value=v) for p, v in points])
    return song


def pitch_render_metrics(native, standalone, rate, *, whammy=False, plan=None):
    """Independent cycle measurements of the 441-Hz pitch fixture, in cents and milliseconds.

    Each interpolated rising crossing measures one complete period. Compare short-window frequencies
    (20 ms, no attack/ramp edge); locate threshold crossings separately so timing error isn't hidden by RMS.
    """
    import numpy as np
    def cycles(pcm):
        signal = np.frombuffer(pcm, dtype=np.int16)[::2].astype(float)
        i = np.flatnonzero((signal[:-1] < 0) & (signal[1:] >= 0))
        at = (i - signal[i] / (signal[i + 1] - signal[i])) / rate
        return (at[1:] + at[:-1]) / 2, 1200 * np.log2(1 / np.diff(at) / 441)
    signals = [cycles(pcm) for pcm in (native, standalone)]
    result = {}
    result['minimum_cycle_cents'] = [round(float(np.min(c[(t > .01) & (t < 1.99) &
        (np.abs(t * 2 - np.round(t * 2)) > .015)])), 4) for t, c in signals]
    if plan is not None:
        # Continuity is relative to the actual native controls, not a positive-pitch floor: whammy dives are valid.
        controls = [(0, 0)] + [(e['frame'] / plan['sample_rate'], (e['bend_value'] - 64) * 18.75)
                              for e in plan['events'] if e['type'] == 'pitch']
        result['cycle_error_cents'] = []
        for times, cents in signals:
            valid = (times > .01) & (times < 1.99) & (np.abs(times * 2 - np.round(times * 2)) > .015)
            expected = [next(value for at, value in reversed(controls) if at <= time) for time in times[valid]]
            result['cycle_error_cents'].append(round(float(np.max(np.abs(cents[valid] - expected))), 4))
    segments = ([('dive', 0, .5, (-46.875, -103.125, -159.375)),
                 ('raise', .5, 1, (46.875, 103.125, 159.375)), ('mixed', 1, 1.5, (-46.875, 46.875))] if whammy else
                [('bend', 0, .5, (46.875, 103.125, 159.375)), ('vibrato', .5, 1, (9.375,)),
                 ('slide', 1, 1.5, (46.875, 103.125, 159.375))])
    for name, start, stop, levels in segments:
        means = []
        for at, cents in signals:
            means.append([float(np.mean(cents[(at >= t) & (at < t + .02)]))
                          for t in np.arange(start + .02, stop - .025, .005)])
        error = float(np.max(np.abs(np.array(means[0]) - means[1])))
        shifts = []
        for level in levels:
            transitions = []
            for at, cents in signals:
                mask = (at > start + .01) & (at < stop - .01)
                t, values = at[mask], cents[mask]
                changes = np.flatnonzero((values[:-1] < level) != (values[1:] < level))
                transitions.append([float((t[i] + t[i+1]) / 2) for i in changes])
            if len(transitions[0]) != len(transitions[1]):
                raise AssertionError((name, level, transitions))
            shifts.extend(abs(a - b) * 1000 for a, b in zip(*transitions))
        result[name] = dict(cents=round(error, 4), milliseconds=round(max(shifts), 4))
    endpoints = ([('bar_low', .252, .263), ('bar_high', .752, .763), ('mixed_low', 1.13, 1.14), ('mixed_high', 1.38, 1.39)] if whammy else
                 [('bend_peak', .252, .263), ('vibrato_depth', .69, .73)])
    for name, start, stop in [('plain', 1.53, 1.9)] + endpoints:
        result[name] = [round(float(np.mean(c[(t > start) & (t < stop)])), 4) for t, c in signals]
    return result


def it_cells(data):
    """Reopen a standalone .it without any native plan: every non-empty cell as (absolute row, channel, note, volume,
    effect, param), the rows in play order, and libopenmpt's own length in seconds."""
    from vulturetracker.itreader import read_it
    from vulturetracker.openmpt import LoadedModule
    module, _ = read_it(data)
    cells, origin = [], 0
    for index in module.orders:
        if index >= 254:
            continue
        for r, row in enumerate(module.patterns[index].rows):
            cells += [(origin + r, ch, c.note, c.volcmd, c.effect, c.param) for ch, c in enumerate(row) if not c.is_empty()]
        origin += len(module.patterns[index].rows)
    with LoadedModule(data) as played:
        return cells, origin, played.duration()


class TestNativeStandaloneIt(unittest.TestCase):
    def test_lyrics_diagrams_notation_loss_without_audio_changes(self):
        from tests.test_pipeline import sine as tone
        from vulturetracker.openmpt import LoadedModule
        plain = native_swing_it_song()
        self.open(plain, {'tone.wav':tone(441),'upper.wav':tone(882)})
        baseline = api.compile_song(plain,self.path.parent)[0]
        for lyrics, diagrams in ((True,False),(False,True),(True,True),(False,False)):
            marked = copy.deepcopy(plain)
            if lyrics: marked['score']['tracks']['guitar']['lyrics'] = dict(from_measure=1,text='Soft light drifts home')
            if diagrams:
                for b in marked['score']['patterns']['a']['beats']:
                    b['chord'] = dict(name='Em',first_fret=0,frets=[0,0,0,2,2,0])
            before = copy.deepcopy(marked)
            data,_,warnings = api.compile_song(marked,self.path.parent)
            self.assertEqual(data,baseline);self.assertEqual(marked,before)
            self.assertEqual(sum('IT notation: lyrics' in w for w in warnings),int(lyrics))
            self.assertEqual(sum('IT notation: chord diagrams' in w for w in warnings),int(diagrams))
            for rate in (44100,48000):
                a,b = [api.prepare_playback(s,self.path.parent,rate) for s in (plain,marked)]
                self.assertEqual(a['plan']['events'],b['plan']['events']);self.assertEqual(a['backing_it'],b['backing_it'])
                if lyrics and diagrams:
                    pcm=[]
                    for pair in (a,b):
                        with LoadedModule(pair['backing_it'],rate,1,plan=pair['plan']) as mod:
                            pcm.append(mod.render(rate=rate,oversample=1,max_seconds=2.2))
                    self.assertEqual(*pcm)
                    print('notation',rate,swing_render_metrics(self.path,data,rate))

    def test_diagrams_lyrics_repeats_ties_and_rest_do_not_generate_notes(self):
        from tests.test_tablature_page import TestTablaturePage
        for source in (TestTablaturePage.four_bar_song(),native_it_song()):
            source['samples'][1]['file']='tone.wav'
            if len(source['score']['measures'])==4:
                for m,fields in zip(source['score']['measures'],({'repeat_open':True},{'endings':[1],'repeat_close':1},{'endings':[2]},{})):m.update(fields)
            self.open(source)
            baseline=api.compile_song(source,self.path.parent)[0]
            source['score']['tracks']['guitar']['lyrics']=dict(from_measure=1,text='One two')
            for p in source['score']['patterns'].values():
                for b in p['beats']:b['chord']=dict(name='C',first_fret=0,frets=[0,1,0,2,3,-1])
            data,_,warnings=api.compile_song(source,self.path.parent)
            self.assertEqual(data,baseline)
            self.assertEqual(sum('IT notation: lyrics' in w for w in warnings),1)
            self.assertEqual(sum('IT notation: chord diagrams' in w for w in warnings),1)
        from tests.test_tablature import beat
        source=native_it_song();source['score']['ties']=[]
        source['score']['patterns']['a']['beats']=[beat('rest',[0,1],[])]
        self.open(source);baseline=api.compile_song(source,self.path.parent)[0]
        source['score']['patterns']['a']['beats'][0]['chord']=dict(name='Em',first_fret=0,frets=[0,0,0,2,2,0])
        self.assertEqual(api.compile_song(source,self.path.parent)[0],baseline)

    def test_articulations_notation_warning_and_independent_render_neutrality(self):
        from vulturetracker.openmpt import LoadedModule
        from tests.test_pipeline import sine as tone
        song = native_articulations_it_song()
        st, data = self.assert_repeat_it(song, raw_channels=(5,), waves={'tone.wav': tone(441), 'upper.wav': tone(882)})
        plain = copy.deepcopy(song)
        for b in plain['score']['patterns']['a']['beats']:
            for flag in ('tapping', 'slapping', 'popping'):
                b['notes'][0][flag] = False
        cleared, _, warnings = api.compile_song(plain, self.path.parent)
        self.assertEqual(data, cleared)
        self.assertFalse(any('IT notation:' in w for w in warnings))
        warnings = api.compile_song(self.path)[2]
        self.assertEqual(sum('IT notation: tapping, slapping, popping markings omitted' in w for w in warnings), 1)
        for rate in (48000, 44100):
            marked = api.prepare_playback(song, self.path.parent, rate)
            unmarked = api.prepare_playback(plain, self.path.parent, rate)
            self.assertEqual(marked['plan']['events'], unmarked['plan']['events'])
            self.assertEqual(marked['backing_it'], unmarked['backing_it'])
            rendered = []
            for pair in (marked, unmarked):
                with LoadedModule(pair['backing_it'], rate, 1, plan=pair['plan']) as mod:
                    rendered.append(mod.render(rate=rate, oversample=1, max_seconds=2.2))
            self.assertEqual(*rendered)
            print('articulations', rate, swing_render_metrics(self.path, data, rate))

    def test_articulation_flags_preserve_existing_techniques_and_raw_state(self):
        from tests.test_pipeline import sine as tone
        for factory in (native_it_song, native_percussion_it_song, native_technique_it_song,
                        native_pitch_it_song, native_whammy_it_song, native_repetition_it_song,
                        native_harmonic_it_song, native_grace_it_song, native_stroke_it_song,
                        native_swing_it_song, native_fade_it_song):
            with self.subTest(factory=factory.__name__):
                plain = factory()
                self.open(plain, {'tone.wav': tone(441), 'upper.wav': tone(882)})
                baseline = api.compile_song(plain, self.path.parent)[0]
                marked = copy.deepcopy(plain)
                for spec in marked['score']['patterns'].values():
                    for b in spec['beats']:
                        if b['track'] == 'drums': continue  # Native percussion does not admit these guitar markings.
                        for i, n in enumerate(b['notes']):
                            n[('tapping', 'slapping', 'popping')[i % 3]] = True
                before = copy.deepcopy(marked)
                data, _, warnings = api.compile_song(marked, self.path.parent)
                self.assertEqual(data, baseline)
                self.assertEqual(marked, before)
                self.assertEqual(api.prepare_playback(marked, self.path.parent)['plan']['events'],
                                 api.prepare_playback(plain, self.path.parent)['plan']['events'])
                self.assertEqual(sum('IT notation:' in w for w in warnings), 1)
                self.st.close()

    def test_articulation_repeat_endings_and_tie_only_warning(self):
        from tests.test_tablature_page import TestTablaturePage
        source = TestTablaturePage.four_bar_song()
        source['samples'][1]['file'] = 'tone.wav'
        for m, fields in zip(source['score']['measures'],
                             ({'repeat_open': True}, {'endings': [1], 'repeat_close': 1}, {'endings': [2]}, {})):
            m.update(fields)
        self.open(source)
        baseline = api.compile_song(source, self.path.parent)[0]
        for spec in source['score']['patterns'].values():
            for b in spec['beats']:
                for n in b['notes']: n['popping'] = True
        data, _, warnings = api.compile_song(source, self.path.parent)
        self.assertEqual(data, baseline)
        self.assertEqual(sum('IT notation: popping' in w for w in warnings), 1)
        tied = native_it_song()
        self.open(tied)
        baseline = api.compile_song(tied, self.path.parent)[0]
        tied['score']['patterns']['b']['beats'][0]['notes'][0]['slapping'] = True
        data, _, warnings = api.compile_song(tied, self.path.parent)
        self.assertEqual(data, baseline)
        self.assertEqual(sum('IT notation: slapping' in w for w in warnings), 1)

    def test_fade_it_gain_trajectory_reset_mapping_source_and_warning(self):
        from tests.test_pipeline import sine as tone
        from vulturetracker import export
        waves={'tone.wav':tone(441),'upper.wav':tone(882)}
        st,data=self.assert_repeat_it(native_fade_it_song(),raw_channels=(5,),waves=waves)
        self.assertTrue(any('IT fade_in:' in w for w in api.compile_song(self.path)[2]))
        snap=export.prepare(st,{'fmt':'it','name':'fade-warning'})
        self.assertIn('IT fade_in:',str(snap))
        for rate in (48000,44100):
            metrics=fade_render_metrics(self.path,data,rate)
            print('IT fade',rate,{k:v for k,v in metrics.items() if k!='checks'})

    def test_fade_it_combinations_track_scope_tails_and_repeat(self):
        from tests.test_pipeline import sine as tone
        from tests.test_tablature import beat,note
        waves={'tone.wav':tone(441),'upper.wav':tone(882)}
        for mode in ('chord','grace','harmonic','picking','swing','tie','repeat','pitch','tail'):
            song=native_fade_it_song();beats=song['score']['patterns']['a']['beats'];head=beats[0]['notes'][0]
            if mode=='chord':beats[0]['notes'].append(dict(note('unmarked',59,2,0),velocity=63))
            elif mode=='grace':head['grace']=dict(fret=2,value=16,velocity=63,on_beat=True)
            elif mode=='harmonic':head['harmonic']=dict(type='semi',data=0)
            elif mode=='picking':head['tremolo_picking']=dict(value=16)
            elif mode=='pitch':head['vibrato']=True
            elif mode=='swing':
                beats[0]['written']['value']=8
                song['score']['measures']=[dict(id='s',meter=[4,4],swing='eighth',**{'from':dict(occurrence='first',at=[0,1]),'to':dict(occurrence='first',at=[4,1])})]
            elif mode=='tie':
                beats[1]['notes'][0].update(pitch=64,fret=0,velocity=95)
                song['score']['ties']=[{'from':dict(occurrence='first',note='fade'),'to':dict(occurrence='first',note='plain')}]
            elif mode=='repeat':
                song['score']['measures']=[dict(id='r',meter=[4,4],repeat_open=True,repeat_close=2,**{'from':dict(occurrence='first',at=[0,1]),'to':dict(occurrence='first',at=[4,1])})]
                song['score']['measures'].append(dict(id='tail',meter=[4,4],**{'from':dict(occurrence='second',at=[0,1]),'to':dict(occurrence='second',at=[4,1])}))
            elif mode=='tail':
                beats[0]['written']['value']=8
                beats[1]['notes'][0]['fade_in']=True
                beats[1]['notes'][0].update(string=2,pitch=59,fret=0)
                song['instruments'][1]['volume_envelope']=dict(nodes=[[0,64],[48,64],[60,0]],sustain=0)
            with self.subTest(mode=mode):
                st,data=self.assert_repeat_it(song,raw_channels=(5,),waves=waves,pulse_release=mode=='picking')
                gain=[e for e in st.mod.native_score['plan']['events'] if e['type']=='gain']
                self.assertTrue(gain)
                if mode=='chord':self.assertTrue(any(e['id'].endswith('/unmarked') and e['gains'][0]<.2 for e in gain))
                if mode=='tail':self.assertTrue(any(e['id']=='first/fade' and Fraction(*e['at'])>1 for e in gain))

    def test_fade_refusals_atomic_and_no_raw_or_instrument_loss(self):
        from tests.test_pipeline import sine as tone
        from vulturetracker.song import SongError
        waves={'tone.wav':tone(441),'upper.wav':tone(882)}
        for mode,message in [('coarse','gain bound'),('volume','raw volume'),('nna','cut NNA'),
                             ('carry','carried'),('random','randomized'),('delay','SDx'),('raw','owned voice')]:
            song=native_fade_it_song();head=song['score']['patterns']['a']['beats'][0]['notes'][0]
            if mode=='coarse':
                song['module']['speed']=6
                for name in ('a','b'):song['patterns'][name]['rows']=16;song['score']['patterns'][name]['row_step']=[1,4]
            elif mode=='volume':song['patterns']['a']['data']+='01: ... .. v32\n'
            elif mode=='nna':song['instruments'][1]['nna']='continue'
            elif mode=='carry':song['instruments'][1]['volume_envelope']['carry']=True
            elif mode=='random':song['instruments'][1]['random_volume']=20
            elif mode=='delay':
                from tests.test_tablature import note
                song['score']['patterns']['a']['beats'][0]['notes'].append(dict(note('short',59,2,0),palm_mute=True))
            elif mode=='raw':song['patterns']['b']['data']='00: C-5 01 ...\n'
            self.open(native_fade_it_song(),waves)
            target=self.path.parent/'guard.it';target.write_bytes(b'keep')
            before=copy.deepcopy(song)
            with self.subTest(mode=mode),self.assertRaisesRegex(SongError,message):api.build(song,target,self.path.parent)
            self.assertEqual(target.read_bytes(),b'keep');self.assertEqual(song,before)

    """A native score as a standalone, editable .it (api.compile_song: CLI build and RENDER & EXPORT's IT)."""

    def open(self, song, waves=None):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        base = Path(tmp.name)
        for filename, samples in (waves or {'tone.wav': sine(220)}).items():
            write_wav(base / filename, RATE, [samples])
        self.path = base / 'song.yaml'
        self.path.write_bytes(api.to_yaml(song).encode())
        self.st = gui.State(self.path, headless=True)
        self.addCleanup(lambda: self.st.close())
        return self.st

    def test_swing_exact_attacks_render_and_source_ownership(self):
        from tests.test_pipeline import sine as tone
        song=native_swing_it_song()
        st,data=self.assert_repeat_it(song,raw_channels=(5,),waves={'tone.wav':tone(441),'upper.wav':tone(882)})
        self.assertEqual([(r,n,fx,p) for r,ch,n,v,fx,p in it_cells(data)[0] if n is not None and n<120],
                         [(0,64,0,0),(8,66,0,0),(24,64,0,0),(28,66,0,0),(36,64,0,0)])
        for rate in (48000,44100): print('IT swing',rate,swing_render_metrics(self.path,data,rate))

    def test_swing_neighbors_spelling_voices_gates_and_combinations(self):
        from tests.test_pipeline import sine as tone
        from tests.test_tablature import beat,note
        waves={'tone.wav':tone(441),'upper.wav':tone(882)}
        for case in ('isolated_first','isolated_second','rest','mismatched_rest','dotted','tuplet','other_voice',
                     'staccato','palm_mute','grace','vibrato','harmonic','tremolo_picking','stroke'):
            song=native_swing_it_song();bs=song['score']['patterns']['a']['beats'];n=bs[0]['notes'][0]
            if case=='isolated_first': bs.pop(1)
            elif case=='isolated_second': bs.pop(0)
            elif case in ('rest','mismatched_rest'):
                bs[1]['notes']=[]
                if case=='mismatched_rest':bs[1]['written']['value']=16
            elif case=='dotted': bs.pop(1);bs[0]['written']['dots']=1
            elif case=='tuplet': bs.pop(1);bs[0]['written']['tuplet']=[3,2]
            elif case=='other_voice': bs[1].update(voice=1,notes=[dict(note('e1',59,2,0),velocity=95)])
            elif case=='grace':n['grace']=dict(fret=2,value=16,velocity=47,on_beat=True)
            elif case=='harmonic':n['harmonic']=dict(type='semi',data=0)
            elif case=='tremolo_picking':n[case]=dict(value=16)
            elif case=='stroke':
                # Quarter-triplet feel doesn't alter the quarter; the short swung pair uses a single-string stroke.
                bs[0]['stroke']=dict(direction='down',value=4)
            else:n[case]=True
            with self.subTest(case=case):self.assert_repeat_it(song,raw_channels=(5,),waves=waves,pulse_release=case=='tremolo_picking')
        # Swing-only export uses the sample default when no velocity/volume is authored.
        song=native_swing_it_song()
        for b in song['score']['patterns']['a']['beats']:b['notes'][0].pop('velocity')
        _,data=self.assert_repeat_it(song,waves=waves)
        self.assertIn((8,0,66,32,0,0),it_cells(data)[0])

    def test_swing_repeat_source_phase_endings_shared_patterns_and_tie_boundary(self):
        from tests.test_pipeline import sine as tone
        from tests.test_tablature import beat,note
        waves={'tone.wav':tone(441),'upper.wav':tone(882)}
        song=native_swing_it_song();song['patterns']['a']['rows']=18
        song['score']['patterns']['a']['beats']=song['score']['patterns']['a']['beats'][:1]
        song['score']['patterns']['b']['beats']=[beat('next',[0,1],[dict(note('next',64,1,0),velocity=95)],8)]
        song['score']['measures']=[dict(id='odd',meter=[3,8],swing='eighth',repeat_close=1,**{
            'from':dict(occurrence='first',at=[0,1]),'to':dict(occurrence='first',at=[3,2])}),
            dict(id='later',meter=[4,4],swing='eighth',**{
            'from':dict(occurrence='second',at=[0,1]),'to':dict(occurrence='second',at=[4,1])})]
        _,data=self.assert_repeat_it(song,waves=waves)
        self.assertEqual([r for r,ch,n,*_ in it_cells(data)[0] if n is not None and n<120],[0,18,38])
        song=native_swing_it_song()
        song['score']['measures']=[dict(id='all',meter=[4,4],swing='eighth',**{
            'from':dict(occurrence='first',at=[0,1]),'to':dict(occurrence='first',at=[4,1])})]
        song['score']['patterns']['a']['beats']=[beat('head',[7,2],[dict(note('head',64,1,0),velocity=95)],8)]
        song['score']['patterns']['b']['beats']=[beat('tail',[0,1],[dict(note('tail',64,1,0),velocity=95)],8)]
        song['score']['ties']=[dict(**{'from':dict(occurrence='first',note='head')},to=dict(occurrence='second',note='tail'))]
        song['patterns']['b']['data']='00: '+'... .. ... ... | '*5+'... .. ... T3C'
        self.assert_repeat_it(song,raw_channels=(5,),waves=waves)
        from tests.test_tablature_page import TestTablaturePage
        song=TestTablaturePage.four_bar_song();song['samples'][1]['file']='tone.wav'
        for p in song['score']['patterns'].values():
            p['beats'][0]['written']['value']=8
        for m in song['score']['measures']:m['swing']='eighth'
        song['score']['measures'][0]['repeat_open']=True
        song['score']['measures'][1].update(endings=[1],repeat_close=1)
        song['score']['measures'][2]['endings']=[2]
        self.assert_repeat_it(song,waves=waves)

    def test_swing_refusals_are_atomic(self):
        from tests.test_pipeline import sine as tone
        base=native_swing_it_song();self.open(base,{'tone.wav':tone(441),'upper.wav':tone(882)})
        target=self.path.parent/'keep.it';target.write_bytes(b'prior IT');cases=[]
        song=copy.deepcopy(base);song['score']['patterns']['a']['beats'][0]['notes'][0]['dead']=True
        cases.append((song,'release.*tick grid'))
        song=copy.deepcopy(base);song['patterns']['a']['data']='\n'.join(
            f'{r:02}: ... .. ... '+('X40' if r==7 else '...') for r in range(8))
        cases.append((song,'swing'))
        song=copy.deepcopy(base);song['score']['patterns']['a']['beats'][1]['notes'][0]['instrument']=0
        cases.append((song,'delayed swing.*explicit'))
        song=copy.deepcopy(base);song['instruments'][1]['nna']='continue';cases.append((song,'cut NNA'))
        song=copy.deepcopy(base);song['score']['patterns']['a']['beats'][0]['at']=[1,13]
        cases.append((song,'not representable'))
        song=copy.deepcopy(base);b=song['score']['patterns']['a']['beats'][1];b['at']=[7,12];b['written']['value']=16
        cases.append((song,'overlap'))
        song=copy.deepcopy(base);song['patterns']['unused']=copy.deepcopy(song['patterns']['a'])
        song['score']['patterns']['unused']=copy.deepcopy(song['score']['patterns']['a']);cases.append((song,'unplayed pattern'))
        # Same written pattern has different measure feels in different occurrences: don't choose one silently.
        song=copy.deepcopy(base);song['orders']=['a','a'];song['patterns'].pop('b');song['score']['patterns'].pop('b')
        song['score']['measures'].append(dict(id='straight',meter=[4,4],**{
            'from':dict(occurrence='second',at=[0,1]),'to':dict(occurrence='second',at=[4,1])}))
        cases.append((song,'occurrence-dependent'))
        for song,message in cases:
            before=copy.deepcopy(song)
            with self.subTest(message=message),self.assertRaisesRegex(SongError,message):api.build(song,target,self.path.parent)
            self.assertEqual(song,before);self.assertEqual(target.read_bytes(),b'prior IT')

    def test_swing_note_delays_releases_and_global_tempo_on_speed_six(self):
        from tests.test_pipeline import sine as tone
        song=native_swing_it_song();song['module']['speed']=6
        for p in song['patterns'].values():p['rows']=16
        for p in song['score']['patterns'].values():p['row_step']=[1,4]
        song['patterns']['a']['data']+='01: '+'... .. ... ... | '*5+'... .. ... TA0\n'
        waves={'tone.wav':tone(441),'upper.wav':tone(882)}
        _,data=self.assert_repeat_it(song,raw_channels=(5,),waves=waves)
        self.assertIn((2,0,66,16,19,0xD4),it_cells(data)[0])
        self.assertIn((9,0,66,16,19,0xD2),it_cells(data)[0])
        song['score']['patterns']['a']['beats']=[b for b in song['score']['patterns']['a']['beats'] if b['id'] not in ('e1','s1')]
        _,data=self.assert_repeat_it(song,raw_channels=(5,),waves=waves)
        self.assertIn((2,0,NOTE_OFF,None,19,0xD4),it_cells(data)[0])
        self.assertIn((9,0,NOTE_OFF,None,19,0xD2),it_cells(data)[0])

    def test_stroke_direction_cohorts_and_source_ownership(self):
        from tests.test_pipeline import sine as tone
        from tests.test_tablature import beat
        song=native_stroke_it_song()
        st,data=self.assert_repeat_it(song,raw_channels=(5,),waves={'tone.wav':tone(441)})
        attacks=[c for c in it_cells(data)[0] if c[2] is not None and c[2]<120]
        self.assertEqual([(r,ch,fx,p) for r,ch,n,v,fx,p in attacks[:6]],
                         [(0,2,0,0),(1,1,19,0xD1),(3,0,0,0),(24,0,0,0),(25,1,19,0xD1),(27,2,0,0)])
        # Sparse metadata on a co-onset rest controls both voices without rewriting the source.
        b=song['score']['patterns']['a']['beats'][0]
        rest=beat('rest',[0,1],[],voice=1);rest['stroke']=b.pop('stroke')
        song['score']['patterns']['a']['beats'].append(rest)
        self.assertEqual(self.assert_repeat_it(song,raw_channels=(5,),waves={'tone.wav':tone(441)})[1],data)
        b['notes'][0].pop('velocity');b['notes'][0]['volume']=40
        _,volume_data=self.assert_repeat_it(song,raw_channels=(5,),waves={'tone.wav':tone(441)})
        self.assertIn((3,0,64,40,0,0),it_cells(volume_data)[0])
        # One string has zero offset at every authored rate.
        for value in (4,8,16,32,64):
            source=native_stroke_it_song()
            for b in source['score']['patterns']['a']['beats']:
                b['notes']=b['notes'][:1]
                if 'stroke' in b: b['stroke']['value']=value
            self.assert_repeat_it(source,waves={'tone.wav':tone(441)})

    def test_stroke_independent_render_order_pitch_gain_and_tail(self):
        from tests.test_pipeline import sine as tone
        self.open(native_stroke_it_song(),{'tone.wav':tone(441)})
        data=api.compile_song(self.path)[0]
        for rate in (48000,44100):
            print('IT strokes',rate,stroke_render_metrics(self.path,data,rate))

    def test_stroke_combinations_tied_strings_repeats_and_exact_tuplet_rate(self):
        from tests.test_pipeline import sine as tone
        from tests.test_tablature import beat
        waves={'tone.wav':tone(441)}
        for technique,value in [('staccato',True),('let_ring',True),('vibrato',True),
                                ('harmonic',dict(type='semi',data=0)),
                                ('grace',dict(fret=2,value=16,velocity=47,on_beat=True)),
                                ('tremolo_picking',dict(value=16))]:
            source=native_stroke_it_song()
            for n in source['score']['patterns']['a']['beats'][0]['notes']: n[technique]=value
            with self.subTest(technique=technique):
                self.assert_repeat_it(source,waves=waves,pulse_release=technique=='tremolo_picking')
        source=native_stroke_it_song()
        beats=source['score']['patterns']['a']['beats']
        beats[1]['at']=[1,1]
        source['score']['ties']=[dict(**{'from':dict(occurrence='first',note='down1')},
                                    to=dict(occurrence='first',note='up1'))]
        source['score']['measures'][1]['repeat_close']=1
        st,data=self.assert_repeat_it(source,waves=waves)
        self.assertNotIn((12,0),[(r,c) for r,c,n,*_ in it_cells(data)[0] if n is not None and n<120])
        # A quarter triplet is 640 TG ticks; value8 gives exactly one IT tick per string.
        source=native_stroke_it_song();b=source['score']['patterns']['a']['beats'][0]
        b['written']['tuplet']=[3,2];b['stroke']['value']=8
        self.assert_repeat_it(source,waves=waves)
        from tests.test_tablature_page import TestTablaturePage
        from tests.test_tablature import note
        source=TestTablaturePage.four_bar_song();source['samples'][1]['file']='tone.wav'
        for p in source['score']['patterns'].values():
            b=p['beats'][0];b['stroke']=dict(direction='down',value=4)
            b['notes'].append(dict(note(b['id']+'chord',40,6,0),velocity=95))
        source['score']['measures'][0]['repeat_open']=True
        source['score']['measures'][1].update(endings=[1],repeat_close=1)
        source['score']['measures'][2]['endings']=[2]
        self.assert_repeat_it(source,waves=waves)

    def test_stroke_short_gate_cross_pattern_release_and_dead_render(self):
        from tests.test_pipeline import sine as tone
        from vulturetracker.openmpt import LoadedModule
        from vulturetracker.measure import patch_it
        import numpy as np
        source=native_stroke_it_song();source['module'].update(tempo=160,speed=1)
        for p in source['patterns'].values(): p['rows']=96
        for p in source['score']['patterns'].values(): p['row_step']=[1,24]
        beats=source['score']['patterns']['a']['beats'];beats[:]=beats[:1]
        for n in beats[0]['notes']: n['dead']=True
        self.assert_repeat_it(source,waves={'tone.wav':tone(441)})
        data=api.compile_song(self.path)[0]
        for rate in (48000,44100):
            pair=api.prepare_playback(self.path,sample_rate=rate);tails=[]
            for ch in range(3):
                ends=[]
                for backing,plan in ((pair['backing_it'],pair['plan']),(data,None)):
                    with LoadedModule(patch_it(backing,silenced=[c for c in range(6) if c!=ch]),rate,1,plan=plan) as mod:
                        samples=np.frombuffer(mod.render(rate=rate,oversample=1,max_seconds=.3),np.int16)[::2]
                    ends.append(int(np.flatnonzero(abs(samples)>2)[-1]))
                self.assertLessEqual(abs(ends[1]-ends[0]),10);tails.append(ends)
            print('IT stroke dead tails',rate,tails)
        # Six-string offset exhausts the staccato gate: TG keeps the full gate, crossing the pattern boundary.
        from tests.test_tablature import note
        source=native_stroke_it_song()
        b=source['score']['patterns']['a']['beats'][0];b['at']=[3,1]
        b['notes']=[dict(note(f's{s}',pitch,s,0),velocity=95,staccato=True)
                    for s,pitch in enumerate((64,59,55,50,45,40),1)]
        source['score']['patterns']['a']['beats']=[b]
        _,data=self.assert_repeat_it(source,waves={'tone.wav':tone(441)})
        self.assertIn((49,0,NOTE_OFF,None,19,0xD1),it_cells(data)[0])

    def test_stroke_refusals_are_atomic(self):
        from tests.test_pipeline import sine as tone
        from tests.test_tablature import beat
        base=native_stroke_it_song();self.open(base,{'tone.wav':tone(441)})
        target=self.path.parent/'keep.it';target.write_bytes(b'previous IT')
        cases=[]
        for value in (8,16,32,64):
            song=copy.deepcopy(base);song['score']['patterns']['a']['beats'][0]['stroke']['value']=value
            cases.append((song,'stroke attack.*tick grid'))
        song=copy.deepcopy(base);song['score']['patterns']['a']['beats'].append(beat('short',[0,1],[],value=16,voice=1))
        cases.append((song,'stroke attack.*tick grid'))
        # Strict projection still refuses sub-tick strokes. Explicit export may now
        # sample them; its audio and failed-fallback atomicity are covered above.
        for song,message in cases:
            before=copy.deepcopy(song)
            with self.subTest(message=message),self.assertRaisesRegex(SongError,message):
                api.compile_song(song,self.path.parent)
            self.assertEqual(song,before)
        cases=[]
        for key,value in [('nna','continue'),('volume_envelope',dict(nodes=[[0,64],[2,64]],carry=True))]:
            song=copy.deepcopy(base);song['instruments'][1][key]=value;cases.append((song,'cut NNA'))
        song=copy.deepcopy(base);song['instruments'][1]['keymap']=[dict(notes='E-5',sample=1)]
        cases.append((song,'mapped sample'))
        song=copy.deepcopy(base);song['patterns']['a']['data']='00: ... .. ... X40'
        cases.append((song,'stroke delayed attack'))
        song=copy.deepcopy(base);song['orders']=['b'];song['score']['order_ids']=['second'];song['score']['measures']=[]
        cases.append((song,'unplayed pattern'))
        song=copy.deepcopy(base);b=song['score']['patterns']['a']['beats'][0]
        other=copy.deepcopy(b);other.update(id='overlap',voice=1);other['notes']=other['notes'][:1];other['notes'][0]['id']='overlap'
        song['score']['patterns']['a']['beats'].append(other);cases.append((song,'overlap'))
        for song,message in cases:
            before=copy.deepcopy(song)
            with self.subTest(message=message),self.assertRaisesRegex(SongError,message): api.build(song,target,self.path.parent)
            self.assertEqual(song,before);self.assertEqual(target.read_bytes(),b'previous IT')

    def test_grace_performed_attacks_transitions_dynamics_and_source_ownership(self):
        from tests.test_pipeline import sine as tone
        song=native_grace_it_song()
        waves={'tone.wav':tone(441),'upper.wav':tone(882)}
        st,data=self.assert_repeat_it(song,raw_channels=(5,),waves=waves)
        cells=it_cells(data)[0]
        self.assertIn((0,0,66,12,0,0),cells)
        self.assertIn((3,0,64,48,0,0),cells)
        self.assertIn((13,0,64,48,19,0xD1),cells)
        self.assertIn((33,0,66,24,0,0),cells)
        for transition in ('none','slide','bend','hammer'):
            variant=copy.deepcopy(song)
            for beat in variant['score']['patterns']['a']['beats']:
                beat['notes'][0]['grace']['transition']=transition
            self.assertEqual(api.compile_song(variant,self.path.parent)[0],data)
        n=song['score']['patterns']['a']['beats'][0]['notes'][0]
        n.pop('velocity'); n['volume']=32
        self.open(song,waves)
        cells=it_cells(api.compile_song(self.path)[0])[0]
        self.assertIn((0,0,66,12,0,0),cells)
        self.assertIn((3,0,64,32,0,0),cells)

    def test_grace_cross_pattern_prefix_ties_repeats_endings_and_harmonic_main(self):
        from tests.test_pipeline import sine as tone
        from tests.test_tablature import beat,note
        song=native_grace_it_song()
        waves={'tone.wav':tone(441),'upper.wav':tone(882)}
        song['score']['patterns']['a']['beats']=song['score']['patterns']['a']['beats'][:2]
        song['score']['patterns']['b']['beats']=[
            beat('head',[0,1],[dict(note('head',64,1,0),velocity=95,grace=dict(fret=2,value=16,velocity=47))]),
            beat('tail',[1,1],[dict(note('tail',64,1,0),velocity=95,grace=dict(fret=3,value=64,velocity=31))])]
        song['score']['ties']=[dict(**{'from':dict(occurrence='second',note='head'),'to':dict(occurrence='second',note='tail')})]
        song['score']['measures'][1]['repeat_close']=1
        st,data=self.assert_repeat_it(song,raw_channels=(5,),waves=waves)
        self.assertIn((45,0,66,12,0,0),it_cells(data)[0])
        source=native_grace_it_song()
        source['score']['patterns']['a']['beats'][0]['notes'][0]['harmonic']=dict(type='semi',data=0)
        self.assert_repeat_it(source,raw_channels=(5,),waves=waves)
        source['score']['patterns']['a']['beats'][0]['notes'][0].pop('harmonic')
        source['score']['patterns']['a']['beats'][0]['notes'][0]['vibrato']=True
        self.assert_repeat_it(source,raw_channels=(5,),waves=waves)
        source['score']['patterns']['a']['beats'][0]['notes'][0].pop('vibrato')
        source['score']['patterns']['a']['beats'][0]['notes'][0]['trill']=dict(fret=2,value=16)
        self.assert_repeat_it(source,raw_channels=(5,),waves=waves,pulse_release=True)
        from tests.test_tablature_page import TestTablaturePage
        source=TestTablaturePage.four_bar_song()
        source['samples'][1]['file']='tone.wav'
        for pattern in source['score']['patterns'].values():
            n=pattern['beats'][0]['notes'][0]
            n['grace']=dict(fret=n['fret']+2,value=16,velocity=47,on_beat=True)
        source['score']['measures'][0]['repeat_open']=True
        source['score']['measures'][1].update(endings=[1],repeat_close=1)
        source['score']['measures'][2]['endings']=[2]
        self.assert_repeat_it(source)

    def test_grace_refusals_do_not_shorten_predecessor_or_replace_output(self):
        from tests.test_pipeline import sine as tone
        from tests.test_tablature import beat,note
        base=native_grace_it_song()
        self.open(base,{'tone.wav':tone(441),'upper.wav':tone(882)})
        target=self.path.parent/'keep.it'; target.write_bytes(b'prior IT')
        cases=[]
        for field,value,reason in [('value',64,'IT tick grid'),('dead',True,'release.*IT tick grid')]:
            song=copy.deepcopy(base); song['score']['patterns']['a']['beats'][0]['notes'][0]['grace'][field]=value
            cases.append((song,reason))
        song=copy.deepcopy(base)
        song['score']['patterns']['a']['beats'].insert(2,beat('previous',[2,1],[dict(note('previous',64,1,0),velocity=95)]))
        pair=api.prepare_playback(song,self.path.parent)
        self.assertEqual(next(e['at'] for e in pair['plan']['events'] if e['id']=='first/previous' and e['type']=='note_off'),[3,1])
        cases.append((song,'overlap needs independent IT channels'))
        song=copy.deepcopy(base); song['instruments'][1]['keymap']=[dict(notes='E-5',sample=1)]
        cases.append((song,'mapped sample'))
        song=copy.deepcopy(base); song['instruments'][1]['nna']='continue'; cases.append((song,'cut NNA'))
        song=copy.deepcopy(base); song['patterns']['a']['data']='00: ... .. ... X40'; cases.append((song,'grace delayed attack'))
        for song,reason in cases:
            before=copy.deepcopy(song)
            with self.subTest(reason=reason),self.assertRaisesRegex(SongError,reason): api.build(song,target,self.path.parent)
            self.assertEqual(song,before); self.assertEqual(target.read_bytes(),b'prior IT')

    def test_grace_independent_render_attacks_pitches_levels_and_release(self):
        from tests.test_pipeline import sine as tone
        from vulturetracker.openmpt import LoadedModule
        song=native_grace_it_song()
        self.open(song,{'tone.wav':tone(441),'upper.wav':tone(882)})
        data=api.compile_song(self.path)[0]
        for rate in (48000,44100):
            pair=api.prepare_playback(self.path,sample_rate=rate)
            renders=[]
            for backing,plan in ((pair['backing_it'],pair['plan']),(data,None)):
                with LoadedModule(backing,rate,1,plan=plan) as mod:
                    renders.append(mod.render(rate=rate,oversample=1,max_seconds=2.2))
            metrics=repetition_render_metrics(*renders,rate,pair['plan'])
            print('IT grace',rate,metrics)
            for actual,event in zip(metrics['attacks'],(e for e in pair['plan']['events'] if e['type']=='note_on')):
                expected=int(Fraction(*event['at'])*24)*int(rate*2.5/120)-event['frame']
                self.assertAlmostEqual(actual['shift_frames'],expected,delta=1)
                self.assertLess(abs(actual['pitch_cents'][1]-(200 if event['pitch']==66 else 0)),.5)
                self.assertLess(actual['settled_rms_error'],.035)
                self.assertLess(abs(actual['settled_level_ratio']-1),.02)
                self.assertLessEqual(abs(actual['shift_frames']),float(Fraction(*event['at']))*24+3)
            self.assertLessEqual(abs(metrics['last_audible_frames'][1]-metrics['last_audible_frames'][0]),1 if rate==48000 else 100)

    def test_grace_dead_gate_chord_and_tempo_keep_exact_native_times(self):
        import numpy as np
        from tests.test_pipeline import sine as tone
        from tests.test_tablature import note
        from vulturetracker.openmpt import LoadedModule
        song=native_grace_it_song()
        song['module'].update(tempo=160,speed=1)
        for pattern in song['patterns'].values(): pattern['rows']=96
        for pattern in song['score']['patterns'].values(): pattern['row_step']=[1,24]
        song['score']['patterns']['a']['beats']=song['score']['patterns']['a']['beats'][:1]
        head=song['score']['patterns']['a']['beats'][0]['notes'][0]
        head['grace']['dead']=True
        waves={'tone.wav':tone(441),'upper.wav':tone(882)}
        self.assert_repeat_it(song,raw_channels=(5,),waves=waves)
        data=api.compile_song(self.path)[0]
        self.assertIn((2,0,255,None,0,0),it_cells(data)[0])
        for rate in (48000,44100):
            pair=api.prepare_playback(self.path,sample_rate=rate)
            tails=[]
            for backing,plan in ((pair['backing_it'],pair['plan']),(data,None)):
                with LoadedModule(backing,rate,1,plan=plan) as mod:
                    z=np.frombuffer(mod.render(rate=rate,oversample=1,max_seconds=.5),np.int16)[::2]
                    grace=z[:int(.08*rate)]
                    tails.append((int(np.flatnonzero(abs(grace)>2)[-1]),int(np.flatnonzero(abs(z)>2)[-1])))
            print('IT dead grace tails',rate,tails)
            self.assertLessEqual(abs(tails[0][0]-tails[1][0]),5)
            self.assertLessEqual(abs(tails[0][1]-tails[1][1]),30)
        head['grace'].update(dead=False,value=32,velocity=0)
        song['score']['patterns']['a']['beats'][0]['notes'].append(dict(note('chord',59,2,0),velocity=95,
            grace=dict(fret=2,value=16,velocity=127,on_beat=True)))
        song['patterns']['a']['data']='\n'.join(f'{r:02}: '+'... .. ... ... | '*5+
            ('... .. ... TA0' if r==0 else '... .. ... V60' if r==12 else '... .. ... ...') for r in range(96))
        self.assert_repeat_it(song,raw_channels=(5,),waves=waves)

    def test_harmonic_types_layers_mappings_and_retirement(self):
        from tests.test_pipeline import sine as tone
        from vulturetracker.model import NOTE_CUT
        song = native_harmonic_it_song()
        st, data = self.assert_repeat_it(song, raw_channels=(5,), waves={'tone.wav':tone(441)})
        mod = api.compile_song(self.path)[1]
        self.assertEqual(mod.score_projection.channel_parents, {6:0,7:0})
        self.assertEqual([(c.volume,c.pan,c.muted,c.plugin) for c in mod.channels[6:]],
                         [(mod.channels[0].volume,mod.channels[0].pan,mod.channels[0].muted,mod.channels[0].plugin)]*2)
        cells = it_cells(data)[0]
        self.assertEqual([(ch,n,v) for r,ch,n,v,*_ in cells if r==48 and n is not None and n<120],
                         [(0,76,48),(6,64,24),(7,64,16)])
        self.assertIn((60,6,NOTE_CUT,None,0,0), cells)
        self.assertIn((60,7,NOTE_CUT,None,0,0), cells)
        self.assertIn((72,7,NOTE_CUT,None,0,0), cells)  # semi -> natural has only one lower layer

    def test_harmonic_ties_repeats_chord_controls_and_raw_cells(self):
        from tests.test_pipeline import sine as tone
        from tests.test_tablature import note
        song = native_it_song()
        song['samples'][1]['loop'] = dict(start=0,end=22000)
        song['instruments'] = {1:dict(sample=1,volume_envelope=dict(nodes=[[0,64],[1,64],[3,0]],sustain=1))}
        a = song['score']['patterns']['a']['beats']
        a[0]['notes'][0].update(harmonic=dict(type='artificial',data=2),vibrato=True)
        a[0]['notes'].append(dict(note('chord',59,2,0),velocity=95,harmonic=dict(type='pinch',data=0)))
        a[3]['notes'][0]['harmonic'] = dict(type='semi',data=0)
        song['score']['measures'][1]['repeat_close'] = 1
        song['patterns']['b']['data'] = '\n'.join(f'{r:02}: '+'... .. ... ... | '*5+
            ('C-3 01 v40 ...' if r==0 else '=== .. ... ...' if r==24 else '... .. ... ...') for r in range(48))
        self.assert_repeat_it(song,raw_channels=(5,),waves={'tone.wav':tone(441)})
        a[3]['notes'][0].pop('harmonic')
        a[3]['notes'][0]['trill'] = dict(fret=2,value=32)
        self.assert_repeat_it(song,raw_channels=(5,),waves={'tone.wav':tone(441)},pulse_release=True)

    def test_harmonic_refusals_are_atomic(self):
        from tests.test_pipeline import sine as tone
        base = native_harmonic_it_song()
        self.open(base,{'tone.wav':tone(441)})
        target = self.path.parent/'keep.it'
        target.write_bytes(b'old module')
        cases = []
        for key,value in [('nna','continue'),('dct','note'),('pitch_envelope',dict(nodes=[[0,0],[2,0]],carry=True))]:
            song=copy.deepcopy(base); song['instruments'][1][key]=value; cases.append((song,'cut NNA'))
        song=copy.deepcopy(base); song['instruments'][1]={'keymap':[dict(notes='C-0..B-5',sample=1)]}
        cases.append((song,'mapped sample'))
        song=copy.deepcopy(base); song['module']['channels']=64; cases.append((song,'64-channel'))
        song=copy.deepcopy(base); song['score']['patterns']['b']['beats'][-1]['written']['value']=2
        cases.append((song,'following release row'))
        for effect in ('M20','X40','D01'):
            song=copy.deepcopy(base); song['patterns']['a']['data']='00: ... .. ... '+effect
            cases.append((song,'raw channel state'))
        for field,value in [('random_volume',5),('random_pan',5),('pan',12),('pitch_pan_separation',4),('filter_cutoff',80)]:
            song=copy.deepcopy(base); song['instruments'][1][field]=value; cases.append((song,'harmonic.*state'))
        for song,message in cases:
            before=copy.deepcopy(song)
            with self.subTest(message=message), self.assertRaisesRegex(SongError,message):
                api.build(song,target,self.path.parent)
            self.assertEqual(song,before); self.assertEqual(target.read_bytes(),b'old module')

    def test_harmonic_keymapped_samples_keep_independent_pitch_volume_and_envelopes(self):
        import numpy as np
        from tests.test_pipeline import sine as tone
        from vulturetracker.openmpt import LoadedModule
        from vulturetracker.itreader import read_it
        song=native_harmonic_it_song()
        song['score']['patterns']['a']['beats']=song['score']['patterns']['a']['beats'][:1]
        song['score']['patterns']['b']['beats']=[]
        song['samples'][2]=dict(file='upper.wav',volume=32,loop=dict(start=0,end=22000))
        ins=song['instruments'][1]
        ins.pop('sample')
        ins['keymap']=[dict(notes='C-0..B-9',sample=1,play_note='C-5'),dict(notes='E-5',sample=2,play_note='C-5')]
        ins['panning_envelope']=dict(nodes=[[0,0],[1,0]])
        ins['pitch_envelope']=dict(nodes=[[0,0],[1,0]])
        self.open(song,{'tone.wav':tone(441),'upper.wav':tone(882)})
        data,model,_=api.compile_song(self.path)
        actual,_=read_it(data)
        self.assertEqual(actual.instruments[0].keymap,model.instruments[0].keymap)
        self.assertEqual(actual.instruments[0].volume_envelope,model.instruments[0].volume_envelope)
        self.assertIn((0,6,64,8,0,0),it_cells(data)[0])
        for rate in (48000,44100):
            pair=api.prepare_playback(self.path,sample_rate=rate)
            spectra=[]
            for backing,plan in ((pair['backing_it'],pair['plan']),(data,None)):
                with LoadedModule(backing,rate,1,plan=plan) as mod:
                    z=np.frombuffer(mod.render(rate=rate,oversample=1,max_seconds=.4),np.int16)[::2]/32768.
                    z=z[int(.08*rate):int(.3*rate)]
                    spectra.append([abs(np.sum(z*np.hanning(len(z))*np.exp(-2j*np.pi*f*np.arange(len(z))/rate))) for f in (441,882)])
            ratios=np.array(spectra[1])/spectra[0]
            print('harmonic independent sample gains',rate,ratios)
            self.assertLess(max(abs(ratios-1)),.027)

    def test_harmonic_export_copies_saved_and_current_mix_mutes(self):
        from tests.test_pipeline import sine as tone
        from vulturetracker import export
        from unittest.mock import patch
        song=native_harmonic_it_song()
        st=self.open(song,{'tone.wav':tone(441)})
        with patch.object(st,'mix',return_value={'volume':{'0':23},'pan':{'0':12}}), patch.object(st,'silenced',return_value=[0]):
            job=export.prepare(st,dict(fmt='it',name='mixed',mix='current',mutes='respect'))
            self.assertEqual(len(st.mod.channels),6)
            self.assertEqual(job['snapshot']['channels'],6)
            self.assertTrue(any('layers' in e for e in job['snapshot']['plan']['events']))
            result=export.run(job,gui._encode)
        self.assertEqual(result['status'],'done',result)
        data=(self.path.parent/'mixed.it').read_bytes()
        for ch in (0,6,7):
            self.assertEqual(data[0x80+ch],23)
            self.assertEqual(data[0x40+ch],128|12)

    def test_harmonic_independent_render_layers_retirement_and_release(self):
        from tests.test_pipeline import sine as tone
        from vulturetracker.openmpt import LoadedModule
        self.open(native_harmonic_it_song(),{'tone.wav':tone(441)})
        data=api.compile_song(self.path)[0]
        for rate in (48000,44100):
            pair=api.prepare_playback(self.path,sample_rate=rate)
            renders=[]
            for backing,plan in ((pair['backing_it'],pair['plan']),(data,None)):
                with LoadedModule(backing,rate,1,plan=plan) as mod:
                    renders.append(mod.render(rate=rate,oversample=1,max_seconds=4.2))
            metrics=harmonic_render_metrics(*renders,rate,pair['plan'])
            print(f'IT harmonic layers {rate}: {metrics}')
            for attack,event in zip(metrics['attacks'],(e for e in pair['plan']['events'] if e['type']=='note_on')):
                expected=int(Fraction(*event['at'])*24)*int(rate*2.5/120)-event['frame']
                self.assertAlmostEqual(attack['shift_frames'],expected,delta=1)
                self.assertLess(attack['settled_error'],.02,attack)
                for layer in attack['layers']:
                    self.assertLess(max(abs(c) for c in layer['cents']),.5,layer)
                    self.assertLess(abs(layer['gain_ratio']-1),.027,layer)
            self.assertLessEqual(abs(metrics['last_audible_frames'][1]-metrics['last_audible_frames'][0]),
                                 1 if rate==48000 else 3.6*48+3,metrics)

    def test_harmonic_released_tails_retire_on_plain_and_fewer_layers(self):
        import numpy as np
        from tests.test_pipeline import sine as tone
        from vulturetracker.openmpt import LoadedModule
        song=native_harmonic_it_song()
        song['instruments'][1]['volume_envelope']=dict(nodes=[[0,64],[1,64],[41,0]],sustain=1)
        beats=song['score']['patterns']['a']['beats']
        beats[0]['notes'][0]['harmonic']=dict(type='semi',data=0)
        beats[0]['notes'][0]['staccato']=True
        beats[1]['notes'][0]['harmonic']=dict(type='natural')
        beats[1]['notes'][0].update(pitch=76,fret=12)
        beats[1]['notes'][0]['staccato']=True
        beats[2]['notes'][0].pop('harmonic')
        beats[2]['notes'][0].update(pitch=64,fret=0)
        self.open(song,{'tone.wav':tone(441)})
        data=api.compile_song(self.path)[0]
        for rate in (48000,44100):
            pair=api.prepare_playback(self.path,sample_rate=rate)
            arrays=[]
            for backing,plan in ((pair['backing_it'],pair['plan']),(data,None)):
                with LoadedModule(backing,rate,1,plan=plan) as mod:
                    arrays.append(np.frombuffer(mod.render(rate=rate,oversample=1,max_seconds=1.45),np.int16)[::2]/32768.)
            # The first release is at .25s, but its 40-tick envelope remains audible at the .5s successor.
            # The unused semi lane must be cut at .5, and both lower lanes at the plain 1s attack.
            for start,shift in ((.65,-18 if rate==44100 else 0),(1.15,-36 if rate==44100 else 0)):
                lo,hi=int(start*rate),int((start+.15)*rate)
                x,y=arrays[0][lo:hi],arrays[1][lo+shift:hi+shift]
                error=float(np.sqrt(np.mean((x-y)**2)/np.mean(x*x)))
                print('harmonic retired released tails',rate,start,error)
                self.assertLess(error,.02)

    def test_harmonic_pitch_controls_reset_all_layers_without_replacing_envelopes(self):
        from tests.test_pipeline import sine as tone
        from vulturetracker.openmpt import LoadedModule
        song=native_pitch_it_song()
        for beat in song['score']['patterns']['a']['beats'][:3]:
            beat['notes'][0]['harmonic']=dict(type='artificial',data=0)
        self.open(song,{'tone.wav':tone(441)})
        with self.assertRaisesRegex(SongError,'step/reset exceeds'):
            api.compile_song(self.path)  # lower slide layer has no successor attack to reset its period
        song['score']['patterns']['a']['beats'][2]['notes'][0].pop('harmonic')
        self.open(song,{'tone.wav':tone(441)})
        data=api.compile_song(self.path)[0]
        for rate in (48000,44100):
            pair=api.prepare_playback(self.path,sample_rate=rate)
            renders=[]
            for backing,plan in ((pair['backing_it'],pair['plan']),(data,None)):
                with LoadedModule(backing,rate,1,plan=plan) as mod:
                    renders.append(mod.render(rate=rate,oversample=1,max_seconds=2.1))
            metrics=pitch_render_metrics(*renders,rate,plan=pair['plan'])
            print('harmonic pitch controls',rate,metrics)
            self.assertLess(max(metrics[n]['cents'] for n in ('bend','vibrato','slide')),38.5)
            self.assertLess(abs(metrics['plain'][1]),.5)

    def test_velocity_volume_tie_and_raw_cells_become_tracker_cells(self):
        st = self.open(native_it_song())
        before, history = self.path.read_bytes(), len(st.history)
        cells, rows, seconds = it_cells(api.compile_song(self.path)[0])
        attacks = [(r, ch, n, v) for r, ch, n, v, *_ in cells if n is not None and n < 120]
        # Velocity becomes the volume column, round(base * velocity / 127) half up: base 64 (the sample's default
        # volume) for 95 -> 48, 127 -> 64, 1 -> 1 (0.504); base 32 (the note's own volume) for 64 -> 16.
        self.assertEqual(attacks, [(0, 0, 64, 48), (12, 1, 62, 16), (24, 1, 60, 64), (36, 0, 64, 48),
                                   (60, 0, 67, 1), (72, 0, 64, 48)])   # m0 (row 48) continues n3's tie: no attack
        offs = sorted((r, ch) for r, ch, n, *_ in cells if n == NOTE_OFF)
        # A release where no next attack on that channel ends the note; the last note ends with the song.
        self.assertEqual(offs, [(12, 0), (36, 1)])
        self.assertIn((0, 5, None, None, 24, 0x40), cells)   # the raw X40 pan stays where it was
        self.assertEqual(rows, 96)
        self.assertAlmostEqual(seconds, 96 * 2 * 2.5 / 120, delta=0.01)   # speed 2 at 120 BPM: 4 s
        self.assertEqual((self.path.read_bytes(), len(st.history)), (before, history))   # the song is untouched

    def test_export_runner_writes_four_bars_it_and_reflow_keeps_every_attack_row(self):
        from vulturetracker import export
        from tests.test_tablature_page import TestTablaturePage
        song = TestTablaturePage.four_bar_song()
        song['samples'][1]['file'] = 'tone.wav'
        st = self.open(song)

        def export_it(name):
            result = export.run(export.prepare(st, {'fmt': 'it', 'name': name}), gui._encode)
            self.assertEqual(result['status'], 'done', result)
            return it_cells((self.path.parent / f'{name}.it').read_bytes())
        cells, rows, seconds = export_it('four-bars')
        attacks = [(r, n, v) for r, ch, n, v, *_ in cells if n is not None and n < 120]
        self.assertEqual(len(attacks), 16)
        self.assertEqual(attacks[:4], [(0, 60, 48), (12, 64, 48), (24, 67, 48), (36, 64, 48)])   # velocity 95 -> v48
        self.assertEqual(rows, 192)
        self.assertAlmostEqual(seconds, 192 * 2 * 2.5 / 90, delta=0.01)   # 16 quarters at 90 BPM: 10.667 s
        st.score_command(dict(action='measure_meter', at=1, meter=[3, 4], to_end=True, revision=st.text_sha()))
        after, after_rows, _ = export_it('reflowed')
        self.assertEqual([(r, n, v) for r, ch, n, v, *_ in after if n is not None and n < 120], attacks)
        self.assertEqual(after_rows, 192)   # bars of 3/4 plus the added one: the same 16 quarters

    def assert_repeat_it(self, song, raw_channels=(), *, waves=None, pulse_release=False):
        from vulturetracker import export
        from vulturetracker.itreader import read_it
        from vulturetracker.openmpt import LoadedModule
        st = self.open(song, waves)
        self.assertFalse(st.error, st.error)
        before = self.path.read_bytes(), copy.deepcopy(st.song), len(st.history)
        plan = st.mod.native_score['plan']
        result = export.run(export.prepare(st, {'fmt': 'it', 'name': 'repeated'}), gui._encode)
        self.assertEqual(result['status'], 'done', result)
        data = (self.path.parent / 'repeated.it').read_bytes()
        self.assertEqual(data, api.compile_song(self.path)[0])
        api.build(self.path, self.path.parent / 'build.it')
        self.assertEqual(data, (self.path.parent / 'build.it').read_bytes())
        module, _ = read_it(data)
        attacks, releases, held, intervals = [], {}, {}, []
        # Standalone IT advances in integer audio ticks; allow at most one 48 kHz sample per tick.
        tolerance = float(Fraction(*plan['duration']['quarters']) * 24 / 48000) + 1 / plan['sample_rate']
        with LoadedModule(data, 48000, 1) as played:
            for oi, pi in enumerate(module.orders):
                if pi >= 254:
                    continue
                for row, cells in enumerate(module.patterns[pi].rows):
                    for ch, cell in enumerate(cells):
                        if ch in raw_channels:
                            continue
                        if cell.note is not None:
                            at = played.order_start(oi, row)
                            if cell.effect == 19 and cell.param >> 4 == 13:
                                next_row = (played.order_start(oi, row + 1) if row + 1 < len(module.patterns[pi].rows)
                                            else played.order_start(oi + 1) if oi + 1 < len(module.orders) and module.orders[oi + 1] < 254
                                            else played.duration())
                                at += (next_row - at) * (cell.param & 15) / module.speed
                            if ch in held:
                                start, pitch = held.pop(ch)
                                intervals.append((start, at, ch, pitch))
                            if cell.note < 120:
                                attacks.append((at, ch, cell.note))
                                held[ch] = (at, cell.note)
            for ch, (start, pitch) in held.items():
                intervals.append((start, played.duration(), ch, pitch))
            parents = api.compile_song(self.path)[1].score_projection.channel_parents
            performed = []
            for e in plan['events']:
                if e['type'] != 'note_on': continue
                layers = e.get('layers', [dict(pitch=e['pitch'], velocity=e['velocity'])])
                channels = [ch for ch, parent in parents.items() if parent == e['ch']][:len(layers)-1] + [e['ch']]
                performed.extend(dict(e, ch=ch, **layer) for ch, layer in zip(channels, layers))
            expected = [(e['frame'] / plan['sample_rate'], e['ch'], e['pitch']) for e in performed]
            self.assertEqual(len(attacks), len(expected))
            for actual, wanted in zip(sorted(attacks), sorted(expected)):
                self.assertEqual(actual[1:], wanted[1:])
                self.assertAlmostEqual(actual[0], wanted[0], delta=tolerance)
            self.assertAlmostEqual(played.duration(), plan['duration']['frames'] / plan['sample_rate'], delta=tolerance)
            releases = {e['id']: e['frame'] / plan['sample_rate'] for e in plan['events'] if e['type'] == 'note_off'}
            expected_intervals = [(e['frame'] / plan['sample_rate'], releases[e['id']], e['ch'], e['pitch'])
                                 for e in performed]
            self.assertEqual(len(intervals), len(expected_intervals))
            for actual, wanted in zip(sorted(intervals), sorted(expected_intervals)):
                self.assertEqual(actual[2:], wanted[2:])
                self.assertAlmostEqual(actual[0], wanted[0], delta=tolerance)
                self.assertAlmostEqual(actual[1], wanted[1], delta=tolerance +
                                       (60 / song['module']['tempo'] / 960 if pulse_release else 0))
        self.assertEqual((self.path.read_bytes(), st.song, len(st.history)), before)
        return st, data

    def test_repeat_endings_and_counts_match_native_performed_timing(self):
        from tests.test_tablature_page import TestTablaturePage
        cases = [([{}, {'repeat_close': 2}, {}, {}], [0, 1, 0, 1, 0, 1, 2, 3]),
                 ([{'repeat_open': True}, {'endings': [1], 'repeat_close': 1}, {'endings': [2]}, {}],
                  [0, 1, 0, 2, 3]),
                 ([{'repeat_open': True}, {'endings': [1], 'repeat_close': 2},
                   {'endings': [2], 'repeat_close': 2}, {'endings': [3]}], [0, 1, 0, 2, 0, 3])]
        for configs, expected in cases:
            with self.subTest(configs=configs):
                song = TestTablaturePage.four_bar_song()
                song['samples'][1]['file'] = 'tone.wav'
                for measure, config in zip(song['score']['measures'], configs):
                    measure.update(config)
                st, data = self.assert_repeat_it(song)
                self.assertEqual([v['source_order'] for v in st.mod.native_score['plan']['occurrences']], expected)
                cells, rows, _ = it_cells(data)
                self.assertEqual(rows, 48 * len(expected))
                self.assertEqual({v for r, ch, n, v, *_ in cells if n is not None and n < 120}, {48})

    def test_repeat_ties_raw_cells_and_tempo_reset(self):
        song = native_it_song()
        song['score']['measures'][0]['repeat_open'] = True
        song['score']['measures'][1]['repeat_close'] = 1
        song['patterns']['b']['data'] = '00: ... .. ... ... | ... .. ... ... | ... .. ... ... | ... .. ... ... | ... .. ... ... | ... .. ... T53\n'
        st, data = self.assert_repeat_it(song)
        cells, _, _ = it_cells(data)
        self.assertEqual(len([c for c in cells if c[2] is not None and c[2] < 120]), 12)  # tie attacks only once per pass
        self.assertIn((96, 5, None, None, 24, 0x40), cells)  # the repeat retained raw X40
        self.assertTrue(any(r == 96 and fx == 20 and param == 120 for r, ch, n, v, fx, param in cells))
        self.assertNotIn(48, [r for r, ch, n, *_ in cells if ch == 0 and n is not None and n < 120])

    def test_repeat_preserves_raw_tracker_notes_and_releases(self):
        song = native_it_song()
        blank = '... .. ... ... | ' * 5
        rows = [blank + '... .. ... ...'] * 48
        rows[0], rows[12] = blank + 'C-3 01 v40 X40', blank + '=== .. ... ...'
        song['patterns']['a']['data'] = '\n'.join(rows) + '\n'
        song['score']['measures'][1]['repeat_close'] = 1
        st, data = self.assert_repeat_it(song, raw_channels=(5,))
        cells = it_cells(data)[0]
        self.assertEqual([(r, n, v, fx, p) for r, ch, n, v, fx, p in cells if ch == 5],
                         [(0, 36, 40, 24, 64), (12, NOTE_OFF, None, 0, 0),
                          (96, 36, 40, 24, 64), (108, NOTE_OFF, None, 0, 0)])

    def test_repeat_fragments_and_shared_authored_pattern_are_disposable(self):
        song = native_it_song()
        song['score']['ties'] = []
        song['orders'] = ['a', 'a']
        song['score']['patterns'].pop('b')
        song['patterns'].pop('b')
        song['score']['measures'] = [dict(id=f'm{i}', meter=[2, 4],
            **{'from': dict(occurrence=oid, at=[start, 1]), 'to': dict(occurrence=oid, at=[start + 2, 1])})
            for i, (oid, start) in enumerate([('first', 0), ('first', 2), ('second', 0), ('second', 2)])]
        song['score']['measures'][1]['repeat_close'] = 1
        st, data = self.assert_repeat_it(song)
        self.assertEqual(st.song['orders'], ['a', 'a'])
        self.assertEqual(it_cells(data)[1], 144)

    def test_repeat_capacity_and_unmatched_tie_refuse_without_output_replacement(self):
        from vulturetracker import export
        song = native_it_song()
        # The first measure is skipped, but its tied continuation is still reached.
        song['score']['measures'][0].update(repeat_close=1, endings=[2])
        st = self.open(song)
        target = self.path.parent / 'keep.it'
        target.write_bytes(b'previous export')
        with self.assertRaisesRegex(SongError, 'unmatched performed tie'):
            api.build(self.path, target)
        self.assertEqual(target.read_bytes(), b'previous export')
        from tests.test_tablature import TestNativeRepeats
        from vulturetracker import tablature
        for configs, message in [([{'repeat_open': True}, {}, {'repeat_close': 100}], '255 played orders'),
                                 ([{'repeat_open': True}, {}, {}, {'repeat_close': 62}, {}, {}, {}], '254 played fragment')]:
            candidate, raw = TestNativeRepeats().fixture(configs)
            before = copy.deepcopy((candidate, raw))
            with self.assertRaisesRegex(ValueError, message):
                tablature.project_score(candidate, raw)
            self.assertEqual((candidate, raw), before)

    def test_percussion_mixed_keymap_voices_repeats_and_tracker_content(self):
        from vulturetracker.itreader import read_it
        song = native_percussion_it_song()
        song['score']['measures'][1]['repeat_close'] = 1
        st, data = self.assert_repeat_it(song)
        module, _ = read_it(data)
        self.assertEqual(module.instruments[1].keymap[36], (60, 2))
        self.assertEqual(module.instruments[1].keymap[42], (62, 3))
        self.assertEqual(module.instruments[2].keymap[100], (48, 3))
        cells, rows, seconds = it_cells(data)
        drums = [(r, ch, n, v) for r, ch, n, v, *_ in cells if ch in (2, 3, 4) and n is not None and n < 120]
        expected = [(0, 2, 36, 32), (0, 3, 42, 36), (0, 4, 100, 48), (24, 2, 1, 20), (60, 2, 38, 0)]
        self.assertEqual(drums, expected + [(r + 96, ch, n, v) for r, ch, n, v in expected])
        self.assertEqual(module.patterns[0].rows[0][4].instrument, 3)
        self.assertIn((96, 5, None, None, 24, 64), cells)
        self.assertEqual(rows, 192)
        self.assertAlmostEqual(seconds, 8.0, delta=0.01)

    def test_percussion_render_keymap_pitch_velocity_one_shot_and_release_match_native(self):
        from tests.test_tablature import beat, note
        from tests.test_pipeline import sine as tone, left, rms, zero_crossing_freq
        from vulturetracker.openmpt import LoadedModule
        song = native_percussion_it_song()
        song['score']['ties'] = []
        song['samples'][2].update(file='short.wav')
        song['samples'][3].update(file='loop.wav', loop=dict(start=0))
        for instrument in (2, 3):
            song['instruments'][instrument]['volume_envelope'] = dict(nodes=[[0, 64], [1, 64], [3, 0]], sustain=1)
        for pattern, keys in [('a', [36, 42]), ('b', [1, 100])]:
            song['score']['patterns'][pattern]['beats'] = [
                beat(f'd{i}{pattern}', [i * 2, 1], [dict(note(f'n{i}{pattern}', key, 1, key),
                    instrument=3 if key == 100 else 2, velocity=64 if key == 1 else 127)], track='drums')
                for i, key in enumerate(keys)]
        self.open(song, {'tone.wav': tone(220), 'short.wav': tone(441, seconds=0.15), 'loop.wav': tone(882)})
        prepared = api.prepare_playback(self.path)
        data = api.compile_song(self.path)[0]
        rendered = []
        for backing, plan in [(prepared['backing_it'], prepared['plan']), (data, None)]:
            with LoadedModule(backing, 44100, 1, plan=plan) as module:
                rendered.append(left(module.render(rate=44100, oversample=1, max_seconds=4)))
        native, standalone = rendered
        def window(samples, start, stop):
            return samples[round(start * 44100):round(stop * 44100)]
        # Actual sample and mapped pitch, independently measured from the reopened module with no score plan.
        for onset, frequency in [(0, 441), (1, 882 * 2 ** (2 / 12)), (2, 441), (3, 441)]:
            for samples in rendered:
                self.assertAlmostEqual(zero_crossing_freq(window(samples, onset + .03, onset + .13)), frequency, delta=15)
            self.assertAlmostEqual(rms(window(standalone, onset + .03, onset + .13)) /
                                   rms(window(native, onset + .03, onset + .13)), 1, delta=.04)
        for samples in rendered:
            # Natural one-shot expiry, and loop/envelope key-off after the quarter-note duration (.5 s).
            self.assertLess(rms(window(samples, .3, .45)), 1)
            self.assertGreater(rms(window(samples, 1.3, 1.45)), 100)
            self.assertLess(rms(window(samples, 1.7, 1.9)), 1)
            self.assertLess(rms(window(samples, 3.7, 3.9)), 1)
            self.assertAlmostEqual(rms(window(samples, 2.03, 2.13)) / rms(window(samples, .03, .13)), .5, delta=.03)

    def test_percussion_sample_mode_keys_and_unsupported_mapping_are_atomic(self):
        song = native_percussion_it_song()
        song.pop('instruments')  # Instrument numbers now directly name samples, exactly as native playback does.
        st = self.open(song)
        self.assertFalse(st.error, st.error)
        cells = it_cells(api.compile_song(self.path)[0])[0]
        self.assertIn((0, 2, 36, 32, 0, 0), cells)
        target = self.path.parent / 'keep.it'
        target.write_bytes(b'old export')
        base = native_percussion_it_song()
        variants = []
        unmapped = copy.deepcopy(base)
        unmapped['instruments'][2]['keymap'] = [dict(notes='F#3', sample=3, play_note='C-5')]
        variants.append((unmapped, 'no mapped sample'))
        inherited = copy.deepcopy(base)
        inherited['score']['tracks']['drums']['instrument'] = 0
        variants.append((inherited, 'instrument: expected integer'))
        collision = copy.deepcopy(base)
        collision['score']['patterns']['a']['beats'][-2]['notes'][0].update(string=1, channel=2)
        variants.append((collision, 'overlapping notes'))
        for key in (0, 101):
            invalid = copy.deepcopy(base)
            invalid['score']['patterns']['a']['beats'][-1]['notes'][0].update(pitch=key, fret=key)
            variants.append((invalid, 'percussion key'))
        for candidate, message in variants:
            before = copy.deepcopy(candidate)
            with self.subTest(message=message), self.assertRaisesRegex(SongError, message):
                api.build(candidate, target, self.path.parent)
            self.assertEqual(target.read_bytes(), b'old export')
            self.assertEqual(candidate, before)

    def test_repetition_rates_delays_keymaps_and_independent_render(self):
        from tests.test_pipeline import sine as tone
        from vulturetracker.openmpt import LoadedModule
        from vulturetracker.itreader import read_it
        waves = {'tone.wav': tone(441), 'upper.wav': tone(882)}
        for kind, rates in [('trill', (4,8,16,32)), ('tremolo_picking', (8,16,32))]:
            for value in rates:
                song = native_repetition_it_song()
                note = song['score']['patterns']['a']['beats'][0]['notes'][0]
                note.pop('trill')
                note[kind] = dict(value=value, **({'fret':2} if kind == 'trill' else {}))
                with self.subTest(kind=kind, value=value):
                    self.assert_repeat_it(song, raw_channels=(5,), waves=waves, pulse_release=True)
        boundary = native_repetition_it_song()
        boundary['orders'] = ['a']
        boundary['score']['order_ids'] = ['first']
        boundary['score']['measures'] = boundary['score']['measures'][:1]
        self.assert_repeat_it(boundary,raw_channels=(5,),waves=waves,pulse_release=True)
        song = native_repetition_it_song()
        self.open(song, waves)
        data, original, warnings = api.compile_song(self.path)
        self.assertTrue(any('IT repetition:' in w for w in warnings))
        cells, _, _ = it_cells(data)
        self.assertIn((13,0,64,48,19,0xD1), cells)  # second picking pulse is halfway through row 13
        self.assertIn((3,0,66,24,0,0), cells)       # alternate key selects the quieter mapped sample
        readback, _ = read_it(data)
        self.assertEqual(readback.instruments[0].keymap, original.instruments[0].keymap)
        self.assertEqual(readback.instruments[0].volume_envelope, original.instruments[0].volume_envelope)
        for rate in (48000,44100):
            pair = api.prepare_playback(self.path, sample_rate=rate)
            renders = []
            for backing, plan in [(pair['backing_it'],pair['plan']), (data,None)]:
                with LoadedModule(backing,rate,1,plan=plan) as module:
                    renders.append(module.render(rate=rate,oversample=1,max_seconds=2.2))
            metrics = repetition_render_metrics(*renders,rate,pair['plan'])
            print(f'IT repetition {rate}: {metrics}')
            self.assertEqual(len(metrics['attacks']),14)
            for attack, event in zip(metrics['attacks'], [e for e in pair['plan']['events'] if e['type']=='note_on']):
                self.assertLessEqual(abs(attack['shift_frames']), math.ceil(event['frame']/rate*48)+2)
                self.assertLess(attack['settled_rms_error'], .025)
                self.assertLess(abs(attack['level_ratio']-1), .015)
                self.assertLess(abs(attack['pitch_cents'][0]-attack['pitch_cents'][1]), .5)
                self.assertAlmostEqual(attack['pitch_cents'][1], 200 if event['pitch']==66 else 0, delta=.5)
            # The intended late keyoff adds <=1 TG tick; IT audio tick floors accumulate independently.
            self.assertLessEqual(abs(metrics['last_audible_frames'][1]-metrics['last_audible_frames'][0]),
                                 math.ceil(rate/1920)+100)

    def test_repetition_ties_endings_dotted_gates_and_raw_data(self):
        from tests.test_pipeline import sine as tone
        from tests.test_tablature import beat, note
        song = native_it_song()
        song['module']['tempo'] = 160
        song['samples'][1]['loop'] = dict(start=0,end=22000)
        song['instruments'] = {1: dict(sample=1, volume_envelope=dict(nodes=[[0,64],[1,64],[3,0]],sustain=1))}
        a, b = (song['score']['patterns'][p]['beats'] for p in ('a','b'))
        a[0]['notes'][0].update(trill=dict(fret=2,value=32), ghost=True, staccato=True)
        a[0]['notes'].append(dict(note('chord',59,2,0), velocity=95, tremolo_picking=dict(value=16)))
        a[1]['notes'][0].update(tremolo_picking=dict(value=8), accent=True, palm_mute=True)
        a[2]['notes'][0].update(trill=dict(fret=3,value=16), heavy_accent=True, staccato=True)
        a[3]['notes'][0].update(trill=dict(fret=2,value=16))  # crosses into b under the head identity
        b[1]['notes'][0].update(pitch=60,string=2,fret=1,velocity=95, tremolo_picking=dict(value=16), let_ring=True)
        b[2]['written'] = dict(value=4,dots=1)  # dotted note leaves room for a final shortened pulse
        b[2]['notes'][0].update(trill=dict(fret=2,value=4))
        song['patterns']['b']['data'] = '\n'.join(f'{r:02}: ' + '... .. ... ... | '*5 +
            ('C-3 01 v40 ...' if r==0 else '=== .. ... ...' if r==24 else '... .. ... ...') for r in range(48))
        song['score']['measures'][1]['repeat_close'] = 1
        song['patterns']['a']['data'] = '\n'.join(f'{r:02}: ' + '... .. ... ... | '*5 +
            ('... .. ... X40' if r==0 else '... .. ... T80' if r==24 else '... .. ... ...') for r in range(48))
        st, data = self.assert_repeat_it(song, raw_channels=(5,), waves={'tone.wav':tone(441)}, pulse_release=True)
        cells, _, _ = it_cells(data)
        self.assertTrue(any(48 <= row < 60 and ch==0 and pitch is not None and pitch<120 for row,ch,pitch,*_ in cells))
        self.assertIn((48,5,36,40,0,0),cells)
        # First/second endings reuse the same native traversal and pulse projection.
        from tests.test_tablature_page import TestTablaturePage
        endings = TestTablaturePage.four_bar_song()
        endings['samples'][1]['file'] = 'tone.wav'
        for pattern in endings['score']['patterns'].values():
            pattern['beats'][0]['notes'][0]['trill'] = dict(fret=3,value=16)
        endings['score']['measures'][0]['repeat_open'] = True
        endings['score']['measures'][1].update(endings=[1],repeat_close=1)
        endings['score']['measures'][2]['endings'] = [2]
        self.assert_repeat_it(endings,pulse_release=True)

    def test_repetition_refusals_are_atomic_and_final_gap_is_specific(self):
        from tests.test_pipeline import sine as tone
        base = native_repetition_it_song()
        self.open(base, {'tone.wav':tone(441),'upper.wav':tone(882)})
        target = self.path.parent/'keep.it'
        target.write_bytes(b'previous module')
        cases = []
        for value in (64,):
            song = copy.deepcopy(base)
            song['score']['patterns']['a']['beats'][0]['notes'][0]['trill']['value'] = value
            cases.append((song,'attack.*IT tick grid'))
        song = copy.deepcopy(base)
        song['module']['tempo'] = 100
        song['score']['patterns']['a']['beats'][0]['notes'][0]['palm_mute'] = True
        cases.append((song,'release.*IT tick grid'))  # 100-BPM gate plus one TG tick is still off-grid
        for key, value in [('nna','continue'),('dct','note'),('volume_envelope',dict(nodes=[[0,64],[2,0]],carry=True))]:
            song = copy.deepcopy(base)
            song['instruments'][1][key] = value
            cases.append((song,'cut NNA'))
        song = copy.deepcopy(base)
        song['instruments'][1]['keymap'] = [dict(notes='E-5',sample=1)]
        cases.append((song,'no mapped sample'))
        song = copy.deepcopy(base)
        song['score']['patterns']['a']['beats'][0]['notes'][0].update(let_ring=True)
        cases.append((song,'share an IT cell|overlap'))
        for flag in ('dead','hammer'):
            song = copy.deepcopy(base)
            song['score']['patterns']['a']['beats'][0]['notes'][0][flag] = True
            cases.append((song,'repetition conflicts'))
        for song, reason in cases:
            before = copy.deepcopy(song)
            with self.subTest(reason=reason), self.assertRaisesRegex(SongError,reason):
                api.build(song,target,self.path.parent)
            self.assertEqual(song,before)
            self.assertEqual(target.read_bytes(),b'previous module')
        from vulturetracker import tablature
        original_plan = tablature._playback_plan
        def off_grid_release(*args, **kwargs):
            plan = original_plan(*args, **kwargs)
            middle = next(e for e in plan['events'] if e['type']=='note_off' and e['id']=='first/trill/pulse/1')
            end = Fraction(*middle['at'])-Fraction(1,960)
            middle['at'] = [end.numerator,end.denominator]
            return plan
        with patch('vulturetracker.tablature._playback_plan', side_effect=off_grid_release), self.assertRaisesRegex(SongError,'release.*IT tick grid'):
            api.compile_song(base,self.path.parent)
        self.assertEqual(target.read_bytes(),b'previous module')

    def test_whammy_chord_untouched_string_ties_repeats_and_sample_ownership(self):
        import numpy as np
        from tests.test_tablature import beat, note
        from tests.test_pipeline import sine as tone
        from vulturetracker.openmpt import LoadedModule
        from vulturetracker.itreader import read_it
        from vulturetracker.measure import patch_it
        song = native_it_song()
        curve = lambda value: dict(points=[dict(position=0, value=0), dict(position=6, value=value), dict(position=12, value=0)])
        song['samples'] = {1: dict(file='tone.wav', loop=dict(start=0, end=22000)),
                           2: dict(file='upper.wav', loop=dict(start=0, end=22000))}
        song['instruments'] = {i: dict(keymap=[dict(notes='C-0..B-9', sample=i, play_note='C-5' if i == 1 else 'C-4')],
            volume_envelope=dict(nodes=[[0, 64], [1, 64], [3, 0]], sustain=1),
            pitch_envelope=dict(nodes=[[0, 0], [8, 2], [16, 0]])) for i in (1, 2)}
        beats = song['score']['patterns']['a']['beats']
        beats[0]['notes'][0].update(tremolo_bar=curve(-1), staccato=True, ghost=True)
        beats[0]['notes'].append(dict(note('other-bar', 59, 2, 0), velocity=95, instrument=2, tremolo_bar=curve(2)))
        beats.append(beat('untouched', [0, 1], [dict(note('untouched', 55, 3, 0), velocity=95)], voice=1))
        beats[3]['notes'][0]['tremolo_bar'] = curve(-2)  # tied across the bar; played again after repeat close
        song['score']['measures'][1]['repeat_close'] = 1
        blanks = '... .. ... ... | ' * 5
        raw = {0: '... .. ... X40', 12: 'C-3 01 v40 ...', 24: '=== .. ... ...'}
        song['patterns']['a']['data'] = '\n'.join(f'{r:02}: {blanks}{raw.get(r, "... .. ... ...")}' for r in range(48))
        self.open(song, {'tone.wav': tone(441), 'upper.wav': tone(882)})
        before = self.path.read_bytes(), copy.deepcopy(self.st.song), len(self.st.history)
        data = api.compile_song(self.path)[0]
        cells, rows, _ = it_cells(data)
        self.assertEqual(rows, 192)
        self.assertIn((6, 0, NOTE_OFF, None, 6, 243), cells)  # final return and keyoff share the row
        self.assertFalse(any(ch == 2 and fx in (5, 6) for _, ch, _, _, fx, _ in cells))
        module, _ = read_it(data)
        original = api.prepare_playback(self.path, sample_rate=48000)['module']
        self.assertEqual([i.keymap for i in module.instruments], [i.keymap for i in original.instruments])
        for actual, expected in zip(module.instruments, original.instruments):
            self.assertEqual(actual.volume_envelope, expected.volume_envelope)
            self.assertEqual(actual.pitch_envelope, expected.pitch_envelope)
        self.assertIn((12, 5, 36, 40, 0, 0), cells)
        self.assertIn((24, 5, NOTE_OFF, None, 0, 0), cells)
        for rate in (48000, 44100):
            pair = api.prepare_playback(self.path, sample_rate=rate)
            for channel in (0, 1, 2):
                values = []
                for backing, plan in [(pair['backing_it'], pair['plan']), (data, None)]:
                    isolated = patch_it(backing, [c for c in range(6) if c != channel])
                    with LoadedModule(isolated, rate, 1, plan=plan) as played:
                        x = np.frombuffer(played.render(rate=rate, oversample=1, max_seconds=.4), np.int16)[::2].astype(float)
                    i = np.flatnonzero((x[:-1] < 0) & (x[1:] >= 0))
                    times = (i - x[i] / (x[i+1] - x[i])) / rate
                    select = (times[1:] > .18) & (times[1:] < .23)
                    values.append(float(np.mean(1200 * np.log2(1 / np.diff(times)[select] / 441))))
                self.assertLess(abs(values[0] - values[1]), .5 if channel == 2 else 38.5, (rate, channel, values))
                print(f'whammy isolated ch{channel} {rate}: native/IT cents {values}')
        self.assertEqual((self.path.read_bytes(), self.st.song, len(self.st.history)), before)

    def test_whammy_unsafe_curves_ownership_and_effects_refuse_atomically(self):
        from tests.test_pipeline import sine as tone
        base = native_whammy_it_song()
        self.open(base, {'tone.wav': tone(441)})
        target = self.path.parent / 'keep.it'
        target.write_bytes(b'previous module')
        cases = []
        for points, message in [([(0, -12)], 'fine-portamento'),
                                ([(0, 0), (1, -2), (2, 0)], 'endpoint|37.5-cent'),
                                ([(0, 0), (6, -2), (9, -2)], 'fine-portamento')]:
            song = copy.deepcopy(base)
            song['score']['patterns']['a']['beats'] = song['score']['patterns']['a']['beats'][:1]
            song['score']['patterns']['a']['beats'][0]['notes'][0]['tremolo_bar']['points'] = [dict(position=p, value=v) for p,v in points]
            cases.append((song, message))
        for field, value in [('nna', 'continue'), ('dct', 'note'),
                             ('volume_envelope', dict(nodes=[[0,64],[2,0]], carry=True))]:
            song = copy.deepcopy(base)
            song['instruments'][1][field] = value
            cases.append((song, 'cut NNA'))
        conflict = copy.deepcopy(base)
        conflict['patterns']['a']['data'] = '\n'.join(f'{r:02}: ... .. ... ' + ('X40' if r == 4 else '...') for r in range(48))
        cases.append((conflict, 'existing tracker effect'))
        for song, message in cases:
            before = copy.deepcopy(song)
            with self.subTest(message=message), self.assertRaisesRegex(SongError, message):
                api.build(song, target, self.path.parent)
            self.assertEqual(target.read_bytes(), b'previous module')
            self.assertEqual(song, before)

    def test_whammy_independent_render_negative_positive_mixed_and_continuity(self):
        from vulturetracker.openmpt import LoadedModule
        from tests.test_pipeline import sine as tone
        song = native_whammy_it_song()
        self.open(song, {'tone.wav': tone(441)})
        data, _, warnings = api.compile_song(self.path)
        self.assertTrue(any('IT pitch:' in w for w in warnings))
        for rate in (48000, 44100):
            pair = api.prepare_playback(self.path, sample_rate=rate)
            renders = []
            for backing, plan in [(pair['backing_it'], pair['plan']), (data, None)]:
                with LoadedModule(backing, rate, 1, plan=plan) as module:
                    renders.append(module.render(rate=rate, oversample=1, max_seconds=2.1))
            metrics = pitch_render_metrics(*renders, rate, whammy=True, plan=pair['plan'])
            print(f'IT whammy {rate}: {metrics}')
            for name in ('dive', 'raise', 'mixed'):
                self.assertLessEqual(metrics[name]['cents'], 38.5, metrics)
                self.assertLessEqual(metrics[name]['milliseconds'], 1000 / 48 + 1000 / 390 + 72000 / rate, metrics)
            # A cycle straddling a native step can average either pitch; 75c detects the old >500c loop defect.
            # This continuity guard is separate from the unchanged 37.5c compiler trajectory admission bound.
            self.assertLess(max(metrics['cycle_error_cents']), 75, metrics)
            for name, expected in [('bar_low', -206.25), ('bar_high', 206.25), ('mixed_low', -93.75),
                                   ('mixed_high', 93.75), ('plain', 0)]:
                self.assertLess(abs(metrics[name][1] - expected), .5, metrics)

    def test_pitch_probe_loop_seam_is_not_an_unintended_pitch_jump(self):
        from vulturetracker.openmpt import LoadedModule
        from tests.test_pipeline import sine as tone
        song = native_pitch_it_song()
        self.open(song, {'tone.wav': tone(441)})
        minima = []
        for half_cycle in (True, False):
            candidate = copy.deepcopy(song)
            if half_cycle:
                candidate['samples'][1]['loop'].pop('end')
            pair = api.prepare_playback(candidate, self.path.parent, sample_rate=48000)
            with LoadedModule(pair['backing_it'], 48000, 1, plan=pair['plan']) as module:
                pcm = module.render(rate=48000, oversample=1, max_seconds=2.1)
            minima.append(pitch_render_metrics(pcm, pcm, 48000)['minimum_cycle_cents'][0])
        self.assertLess(minima[0], -500)  # reproduces the bad probe's spurious cycle, not a native bend step
        self.assertGreater(minima[1], -1)
        print('pitch probe original/corrected minimum cycle cents:', minima)

    def test_pitch_rounded_reset_cannot_detune_a_later_attack_or_tail(self):
        from vulturetracker.tablature import _project_pitch_controls
        from vulturetracker.model import Pattern, Cell
        rec = dict(pitch_technique=True)
        plan = dict(occurrences=[dict(id='first')], duration=dict(quarters=[4, 1]), events=[
            dict(type='note_on', id='head', note='head', occurrence='first', at=[0, 1], ch=0, instrument=1, pitch=64),
            dict(type='note_off', id='head', at=[1, 8]),
            dict(type='pitch', id='head', at=[1, 16], bend_value=65),
            dict(type='pitch', id='head', at=[1, 8], bend_value=64),
            dict(type='note_on', id='next', note='next', occurrence='first', at=[1, 6], ch=0, instrument=1, pitch=64),
            dict(type='note_off', id='next', at=[1, 1])])
        projection = SimpleNamespace(patterns=[Pattern('a', [[Cell()] for _ in range(48)])], raw_patterns=[], diagnostics=[])
        def run():
            return _project_pitch_controls({}, plan, projection, {('a', 'head'): rec, ('a', 'next'): dict(pitch_technique=False)},
                ['a'], {'a': 0}, [0], 2, lambda *a: None, None)
        with self.assertRaisesRegex(ValueError, 'lands on another attack'):
            run()
        plan['events'] = plan['events'][:4]  # a held instrument release tail, no successor resetting its period
        plan['events'][2]['bend_value'] = 67
        with self.assertRaisesRegex(ValueError, '37.5-cent trajectory bound'):
            run()
        plan['events'][2]['bend_value'] = 65
        run()  # bounded one-step tail reset is retained, with a quantization warning
        self.assertTrue(projection.diagnostics)

    def test_pitch_ties_voices_repeats_raw_cells_and_instruments(self):
        from vulturetracker.itreader import read_it
        song = native_technique_it_song()
        a, b = (song['score']['patterns'][p]['beats'] for p in ('a', 'b'))
        a[0]['notes'][0].pop('staccato')
        a[0]['notes'][0]['vibrato'] = True
        a[3]['notes'][0].pop('staccato')
        a[3]['notes'][0]['vibrato'] = True  # follows the tied head through the repeat traversal
        from tests.test_tablature import note
        a[0]['notes'].append(dict(note('second-string', 59, 2, 0), velocity=95, vibrato=True))
        song['instruments'][1]['pitch_envelope'] = dict(nodes=[[0, 0], [8, 2], [16, 0]])
        blanks = '... .. ... ... | ' * 5
        raw = {0: '... .. ... X40', 12: 'C-3 01 v40 ...', 24: '=== .. ... ...'}
        song['patterns']['a']['data'] = '\n'.join(f'{r:02}: {blanks}{raw.get(r, "... .. ... ...")}' for r in range(48))
        st, data = self.assert_repeat_it(song, raw_channels=(5,))
        module, _ = read_it(data)
        self.assertEqual([i.keymap for i in module.instruments], [i.keymap for i in api.compile_song(self.path)[1].instruments])
        self.assertEqual(module.instruments[0].volume_envelope, api.compile_song(self.path)[1].instruments[0].volume_envelope)
        self.assertEqual(module.instruments[0].pitch_envelope.nodes, [(0, 0), (8, 2), (16, 0)])
        self.assertIn((4, 0, None, None, 6, 0xf3), it_cells(data)[0])
        self.assertIn((4, 1, None, None, 6, 0xf3), it_cells(data)[0])

    def test_pitch_refusals_keep_existing_output_and_authored_data(self):
        from tests.test_tablature import beat, note
        base = native_pitch_it_song()
        self.open(base)
        target = self.path.parent / 'keep.it'
        target.write_bytes(b'previous module')
        cases = []
        for field, value, message in [('linear_slides', False, 'require linear_slides')]:
            candidate = copy.deepcopy(base)
            candidate['module'][field] = value
            cases.append((candidate, message))
        for field, value in [('nna', 'continue'), ('dct', 'note'),
                             ('pitch_envelope', dict(nodes=[[0, 0], [1, 2]], carry=True))]:
            candidate = copy.deepcopy(base)
            candidate['instruments'][1][field] = value
            cases.append((candidate, 'cut NNA'))
        jump = copy.deepcopy(base)
        jump['score']['patterns']['a']['beats'][0]['notes'][0]['bend']['points'] = [dict(position=0, value=4)]
        cases.append((jump, 'exceeds one IT fine'))
        conflict = copy.deepcopy(base)
        conflict['patterns']['a']['data'] = '\n'.join(f'{r:02}: ... .. ... ' + ('X40' if r == 4 else '...') for r in range(48))
        cases.append((conflict, 'existing tracker effect'))
        raw_pitch = copy.deepcopy(base)
        raw_pitch['patterns']['a']['data'] = '\n'.join(f'{r:02}: ... .. ... ' + ('H01' if r == 2 else '...') for r in range(48))
        cases.append((raw_pitch, 'shared mixer semantics'))
        for song, message in cases:
            before = copy.deepcopy(song)
            with self.subTest(message=message), self.assertRaisesRegex(SongError, message):
                api.build(song, target, self.path.parent)
            self.assertEqual(target.read_bytes(), b'previous module')
            self.assertEqual(song, before)

    def test_slide_without_immediate_target_keeps_plain_it_pitch_and_gate(self):
        from tests.test_pipeline import sine as tone
        for rest in (False, True):
            song = native_pitch_it_song()
            beats = song['score']['patterns']['a']['beats']
            if rest:
                target = beats[-1]
                target['notes'] = []
            else:
                beats.pop()
            before = copy.deepcopy(song)
            self.open(song, {'tone.wav': tone(441)})
            written = self.path.read_bytes()
            data, _, _ = api.compile_song(self.path)
            plain = copy.deepcopy(song)
            for b in plain['score']['patterns']['a']['beats']:
                for n in b['notes']:
                    n.pop('slide', None)
            reference, _, _ = api.compile_song(plain, self.path.parent)
            self.assertEqual(data, reference)
            self.assertEqual(it_cells(data), it_cells(reference))
            self.assertEqual(self.path.read_bytes(), written)
            self.assertEqual(song, before)

    def test_pitch_exact_vibrato_and_down_bend_endpoints(self):
        from vulturetracker.openmpt import LoadedModule
        from tests.test_pipeline import sine as tone
        import numpy as np
        for flag in ('vibrato', 'bend', 'envelope'):
            song = native_pitch_it_song()
            beats = song['score']['patterns']['a']['beats']
            beats[0]['notes'][0].pop('bend')
            if flag == 'envelope':
                song['instruments'][1]['pitch_envelope'] = dict(nodes=[[0, 0], [8, 2], [16, 0]])
            beats[0]['notes'][0]['vibrato' if flag == 'envelope' else flag] = (True if flag != 'bend' else
                dict(points=[dict(position=0, value=2), dict(position=12, value=0)]))
            beats[3]['at'] = [1, 1]
            song['score']['patterns']['a']['beats'] = [beats[0], beats[3]]
            self.open(song, {'tone.wav': tone(441)})
            data, _, warnings = api.compile_song(self.path)
            if flag == 'vibrato':
                self.assertFalse(any('IT pitch:' in w for w in warnings), warnings)
            for rate in (48000, 44100):
                pair = api.prepare_playback(self.path, sample_rate=rate)
                curves = []
                for backing, plan in [(pair['backing_it'], pair['plan']), (data, None)]:
                    with LoadedModule(backing, rate, 1, plan=plan) as module:
                        x = np.frombuffer(module.render(rate=rate, oversample=1, max_seconds=1), np.int16)[::2].astype(float)
                    i = np.flatnonzero((x[:-1] < 0) & (x[1:] >= 0))
                    t = (i - x[i] / (x[i+1]-x[i])) / rate
                    cents = 1200 * np.log2(1 / np.diff(t) / 441)
                    curves.append([float(np.mean(cents[(t[1:] > a) & (t[1:] < a + .025)]))
                                   for a in (.03, .12, .22, .32, .42, .53)])
                error = max(abs(a-b) for a,b in zip(*curves))
                self.assertLess(error, 38.5)
                if flag == 'bend':
                    self.assertLess(abs(curves[1][0] - 93.75), .5)
                    self.assertLess(abs(curves[1][-1]), .5)
                print(f'IT {flag} {rate}: measured pitch windows {curves}; max error {error:.4f} cents')

    def test_pitch_standalone_render_curves_and_visible_export_warning(self):
        from vulturetracker.openmpt import LoadedModule
        from tests.test_pipeline import sine as tone
        from vulturetracker.export import prepare
        song = native_pitch_it_song()
        st = self.open(song, {'tone.wav': tone(441)})
        before, history = self.path.read_bytes(), len(st.history)
        data, mod, warnings = api.compile_song(self.path)
        self.assertTrue(any('IT pitch:' in w for w in warnings), warnings)
        job = prepare(st, dict(fmt='it', name='pitch'))
        self.assertTrue(any('IT pitch:' in w for w in job['snapshot']['warnings']), job)
        for rate in (48000, 44100):
            pair = api.prepare_playback(self.path, sample_rate=rate)
            renders = []
            for backing, plan in [(pair['backing_it'], pair['plan']), (data, None)]:
                with LoadedModule(backing, rate, 1, plan=plan) as played:
                    renders.append(played.render(rate=rate, oversample=1, max_seconds=2))
            metrics = pitch_render_metrics(*renders, rate)
            print(f'IT pitch {rate}: {metrics}')
            for name in ('bend', 'vibrato', 'slide'):
                self.assertLessEqual(metrics[name]['cents'], 38.5, (rate, name, metrics))
                # Half a 41.667-ms row + one carrier cycle for independent crossing detection,
                # plus accumulated tick rounding through the 1.5-second curve sequence.
                self.assertLessEqual(metrics[name]['milliseconds'], 1000 / 48 + 1000 / 441 + 72 * 1000 / rate)
            self.assertGreater(min(metrics['minimum_cycle_cents']), -1, metrics)
            self.assertLess(abs(metrics['bend_peak'][1] - 206.25), .5, metrics)
            self.assertLess(abs(metrics['plain'][1]), .5, metrics)
            self.assertLess(abs(metrics['vibrato_depth'][1] - 18.75), .5, metrics)
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(len(st.history), history)

    def test_techniques_mixed_voices_ties_repeats_and_raw_cells(self):
        song = native_technique_it_song()
        # Native precedence uses dead before palm mute and staccato; preserve residual tracker attacks too.
        song['score']['patterns']['a']['beats'][2]['notes'][0].update(palm_mute=True, staccato=True)
        blanks = '... .. ... ... | ' * 5
        raw = {0: '... .. ... X40', 12: 'C-3 01 v40 ...', 24: '=== .. ... ...'}
        song['patterns']['a']['data'] = '\n'.join(f'{r:02}: {blanks}{raw.get(r, "... .. ... ...")}' for r in range(48))
        st, data = self.assert_repeat_it(song, raw_channels=(5,))
        cells, rows, _ = it_cells(data)
        self.assertIn((0, 0, 64, 40, 0, 0), cells)  # ghost 95 -> 79 -> v40
        self.assertIn((12, 1, 62, 20, 0, 0), cells)  # accent 64 -> 80, explicit v32
        self.assertIn((72, 0, 64, 35, 0, 0), cells)  # previous hammer 95 -> 70 -> v35
        for row, channel in [(6, 0), (14, 1), (25, 1), (48, 0), (2, 3), (1, 4)]:
            self.assertIn((row, channel, NOTE_OFF, None, 0, 0), cells)
        self.assertIn((0, 5, None, None, 24, 64), cells)
        self.assertIn((12, 5, 36, 40, 0, 0), cells)
        self.assertIn((24, 5, NOTE_OFF, None, 0, 0), cells)
        self.assertEqual(rows, 192)

    def test_technique_renders_match_native_without_a_plan(self):
        from tests.test_pipeline import sine as tone, left, rms
        from vulturetracker.openmpt import LoadedModule
        from tests.test_tablature import beat, note
        for flag, tempo in [('ghost', 120), ('accent', 120), ('heavy_accent', 120), ('hammer', 120),
                            ('staccato', 120), ('palm_mute', 120), ('dead', 160), ('let_ring', 120)]:
            with self.subTest(technique=flag):
                song = native_it_song()
                song['module']['tempo'] = tempo
                song['score']['ties'] = []
                song['instruments'] = {1: dict(sample=1, volume_envelope=dict(nodes=[[0, 64], [1, 64], [3, 0]], sustain=1))}
                song['samples'][1]['loop'] = dict(start=0)
                song['score']['patterns']['a']['beats'] = [
                    beat('head', [0, 1], [dict(note('head', 64, 1, 0), velocity=95, **{flag: True})]),
                    beat('other', [1, 1], [dict(note('other', 59, 2, 0), velocity=0, let_ring=flag == 'let_ring')]),
                    beat('next', [2, 1], [dict(note('next', 64, 1, 0), velocity=95, let_ring=flag == 'let_ring')])]
                song['score']['patterns']['b']['beats'] = []
                self.open(song, {'tone.wav': tone(441)})
                bundle = api.prepare_playback(self.path, sample_rate=48000)
                data = api.compile_song(self.path)[0]
                signals = []
                for backing, plan in [(bundle['backing_it'], bundle['plan']), (data, None)]:
                    with LoadedModule(backing, 48000, 1, plan=plan) as module:
                        signals.append(left(module.render(rate=48000, oversample=1, max_seconds=3)))
                native, standalone = signals
                # Sample-aligned tick rounding can shift phase slightly; compare short-window energy throughout
                # attacks, sustains and envelope releases, not just the internal event plan.
                peak = max(rms(native[i:i + 480]) for i in range(0, len(native) - 480, 480))
                for i in range(0, min(len(native), len(standalone)) - 480, 480):
                    self.assertLess(abs(rms(native[i:i + 480]) - rms(standalone[i:i + 480])) / peak, .06,
                                    (flag, i / 48000))
                if flag == 'palm_mute':
                    self.assertIn((1, 0, NOTE_OFF, None, 19, 0xD1), it_cells(data)[0])

    def test_technique_release_at_44100_bounds_real_render_tail_by_tick_rounding(self):
        from tests.test_pipeline import sine as tone, left
        from tests.test_tablature import beat, note
        from vulturetracker.openmpt import LoadedModule
        for flag, tempo in [('staccato', 120), ('palm_mute', 120), ('dead', 160), ('let_ring', 120)]:
            with self.subTest(technique=flag):
                song = native_it_song()
                song['module']['tempo'] = tempo
                song['score']['ties'] = []
                song['samples'][1]['loop'] = dict(start=0)
                song['instruments'] = {1: dict(keymap=[dict(notes='C-0..B-9', sample=1, play_note='C-5')],
                    volume_envelope=dict(nodes=[[0, 64], [1, 64], [3, 0]], sustain=1))}
                song['score']['patterns']['a']['beats'] = [
                    beat('head', [0, 1], [dict(note('head', 64, 1, 0), velocity=95, **{flag: True})]),
                    beat('other', [1, 1], [dict(note('other', 59, 2, 0), velocity=0, let_ring=flag == 'let_ring')]),
                    beat('rest', [2, 1], [])]
                song['score']['patterns']['b']['beats'] = []
                self.open(song, {'tone.wav': tone(441)})
                pair = api.prepare_playback(self.path, sample_rate=44100)
                ends = []
                for data, plan in [(pair['backing_it'], pair['plan']), (api.compile_song(self.path)[0], None)]:
                    with LoadedModule(data, 44100, 1, plan=plan) as module:
                        signal = left(module.render(rate=44100, oversample=1, max_seconds=2))
                        ends.append(max(i for i, sample in enumerate(signal) if abs(sample) > 4))
                off = next(e for e in pair['plan']['events'] if e['type'] == 'note_off' and e['note'] == 'head')
                # One sample maximum per rounded IT tick, through the gate and three envelope ticks,
                # plus the known native frame-rounding edge (one sample). No relaxed amplitude threshold.
                bound = int(Fraction(*off['at']) * 24) + 4
                self.assertLessEqual(abs(ends[0] - ends[1]), bound, (flag, ends, bound))
                print(f'44100 {flag}: native/IT last audible frame {ends}; drift {ends[0]-ends[1]}, bound {bound}')

    def test_technique_refusals_are_atomic_and_do_not_quantize(self):
        from tests.test_tablature import beat, note
        base = native_it_song()
        self.open(base)
        target = self.path.parent / 'keep.it'
        target.write_bytes(b'previous module')
        candidates = []
        inherited = copy.deepcopy(base)
        inherited['score']['patterns']['a']['beats'][2]['notes'][0].update(instrument=0, ghost=True)
        candidates.append((inherited, 'need explicit note instruments'))
        shared = copy.deepcopy(base)
        shared['orders'] = ['a', 'a']
        shared['patterns'].pop('b')
        shared['score']['patterns'].pop('b')
        shared['score']['ties'] = []
        shared['score']['patterns']['a']['beats'][-1]['notes'][0]['hammer'] = True
        candidates.append((shared, 'occurrence-dependent technique velocity'))
        off_grid = copy.deepcopy(base)
        off_grid['score']['patterns']['a']['beats'][0]['notes'][0]['dead'] = True  # 1.5 IT ticks
        candidates.append((off_grid, 'IT tick grid'))
        overlap = copy.deepcopy(base)
        overlap['score']['ties'] = []
        overlap['score']['patterns']['a']['beats'] = [
            beat('first', [0, 1], [dict(note('first', 64, 1, 0), let_ring=True)]),
            beat('second', [1, 1], [note('second', 66, 1, 2)])]
        candidates.append((overlap, 'performed technique overlap'))
        for song, message in candidates:
            before = copy.deepcopy(song)
            with self.subTest(message=message), self.assertRaisesRegex(SongError, message):
                api.build(song, target, self.path.parent)
            self.assertEqual(song, before)
            self.assertEqual(target.read_bytes(), b'previous module')

    def test_notation_loss_warnings_reach_export_prepare(self):
        from vulturetracker import export
        song = native_it_song()
        song['score']['measures'][0]['swing'] = 'eighth'
        song['score']['patterns']['a']['beats'][0]['chord'] = dict(name='C', first_fret=0, frets=[0,0,0,0,0,0])
        st = self.open(song)
        snap = export.prepare(st, {'fmt': 'it', 'name': 'swung'})
        self.assertIn('IT notation: chord diagrams omitted',str(snap))
        self.assertFalse((self.path.parent / 'swung.it').exists())


class TestCompleteSongClipboardState(unittest.TestCase):
    """Portable phrases outlive their source and follow the receiving instrument."""

    @staticmethod
    def song_pair():
        source = complete_section_song()
        source['module']['title'] = 'Portable phrase source'
        source['module']['channels'] = [dict(name=f'Lane {i + 1}') for i in range(12)]
        source['samples'] = {1: dict(file='a.wav', name='Source'), 2: dict(file='a.wav', name='Reply')}
        source.pop('instruments', None)
        source['score']['tracks']['guitar']['name'] = 'Standard guitar'
        source['score']['tracks']['reply'] = dict(name='Drop D reply', tuning=[64, 59, 55, 50, 45, 38],
            channels=list(range(6, 12)), instrument=2, capo=0, max_fret=29)
        source['score']['patterns']['C']['beats'][0]['notes'][0].update(instrument=1, channel=1)
        destination = copy.deepcopy(source)
        destination['module']['title'] = 'Portable destination'
        destination['samples'] = {7: dict(file='a.wav', name='Destination only')}
        destination['score']['tracks'] = {'part': dict(source['score']['tracks']['reply'], instrument=7, name='Destination guitar')}
        destination['score']['ties'] = []
        for pattern in destination['score']['patterns'].values():
            pattern['beats'] = []
        return source, destination

    def open(self, song):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = Path(tmp.name) / 'song.yaml'
        write_wav(path.parent / 'a.wav', RATE, [sine(440)])
        path.write_text('# Portable phrase\n' + api.to_yaml(song), encoding='utf-8', newline='\n')
        st = gui.State(path, headless=True)
        self.addCleanup(st.close)
        self.assertFalse(st.error, st.error)
        return st

    def test_cross_song_closed_source_destination_routing_ties_and_exact_history(self):
        source, destination = self.song_pair()
        st = self.open(source)
        source_bytes = st.song_path.read_bytes()
        clip = st.score_clipboard(dict(selection=section_groups(source, 0, 3), revision=st.text_sha()))['clipboard']
        original_clip = copy.deepcopy(clip)
        source_events = [(e['type'], e['at'], e['pitch']) for e in st.mod.native_score['plan']['events']]
        st.close()
        target = self.open(destination)
        before = target.song_path.read_bytes()
        result = target.score_edit(dict(op='beats_paste', pattern=0, row=0, occurrence='bar1',
            clipboard=clip, track_map={'guitar': 'part'}, across=True, revision=target.text_sha()))
        self.assertEqual(result['selection']['track'], 'part')
        self.assertEqual(len(result['selection']['range']), 4)
        self.assertEqual(len(target.song['score']['ties']), 1)
        self.assertEqual({b['voice'] for p in target.song['score']['patterns'].values() for b in p['beats']}, {0, 1})
        events = target.mod.native_score['plan']['events']
        self.assertEqual([(e['type'], e['at'], e['pitch']) for e in events], source_events)
        self.assertTrue(all(e['instrument'] == 7 and 6 <= e['ch'] < 12 for e in events if e['type'] == 'note_on'))
        self.assertTrue(all('instrument' not in n and 'channel' not in n for p in target.song['score']['patterns'].values()
                            for b in p['beats'] for n in b['notes']))
        saved = target.song_path.read_bytes()
        target.undo(); self.assertEqual(target.song_path.read_bytes(), before)
        target.undo(redo=True); self.assertEqual(target.song_path.read_bytes(), saved)
        reopened = gui.State(target.song_path, headless=True)
        try:
            self.assertEqual(reopened.mod.native_score['plan'], target.mod.native_score['plan'])
        finally:
            reopened.close()
        self.assertEqual(st.song_path.read_bytes(), source_bytes)
        self.assertEqual(clip, original_clip)

    def test_cross_track_selection_copy_and_stale_or_impossible_map_are_atomic(self):
        source, _ = self.song_pair()
        st = self.open(source)
        before, revision = st.song_path.read_bytes(), st.text_sha()
        clip = st.score_clipboard(dict(selection=section_groups(source, 0, 3), revision=revision))['clipboard']
        result = st.score_edit(dict(op='beats_paste', pattern=0, row=0, occurrence='bar1',
            clipboard=clip, track_map={'guitar': 'reply'}, across=True, revision=revision))
        self.assertEqual(result['selection']['track'], 'reply')
        self.assertEqual(st.score_clipboard(dict(selection=result['selection']['range'],
            revision=st.text_sha()))['clipboard']['track_kinds'], {'reply': 'pitched'})
        saved, history = st.song_path.read_bytes(), list(st.history)
        with self.assertRaisesRegex(ValueError, 'changed|revision|stale'):
            st.score_edit(dict(op='beats_paste', pattern=0, row=0, occurrence='bar1',
                clipboard=clip, track_map={'guitar': 'reply'}, across=True, revision=revision))
        self.assertEqual((st.song_path.read_bytes(), st.history), (saved, history))
        st.undo(); self.assertEqual(st.song_path.read_bytes(), before)
        bad = copy.deepcopy(clip); bad['beats'][0]['notes'][0].update(pitch=119, string=None, fret=None)
        for mapping, payload in (({'guitar': 'missing'}, clip), ({'guitar': 'reply'}, bad)):
            history, future = list(st.history), list(st.future)
            with self.assertRaises(ValueError):
                st.score_edit(dict(op='beats_paste', pattern=0, row=0, occurrence='bar1',
                    clipboard=payload, track_map=mapping, across=True, revision=st.text_sha()))
            self.assertEqual(st.song_path.read_bytes(), before)
            self.assertEqual((st.history, st.future), (history, future))


if __name__ == '__main__':
    unittest.main()
