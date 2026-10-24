"""Logical-part sound assignment shares native playback, IT and exact edit history."""
import copy
from pathlib import Path
import tempfile
import unittest

from vulturetracker import api, gui
from vulturetracker.openmpt import LoadedModule
from vulturetracker.wavload import write_wav
from tests.test_gui import sine
from tests.test_modimport import bank
from tests.test_tablature_sync import complete_song_seed


class TestBandInstruments(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        write_wav(self.base / 'tone.wav', 44100, [sine(440)])
        self.path = self.base / 'song.yaml'

    def state(self, source=None):
        self.path.write_text('# Keep this owner comment\n' + api.to_yaml(source or complete_song_seed()),
                             encoding='utf-8', newline='\n')
        st = gui.State(self.path, headless=True)
        self.addCleanup(st.close)
        self.assertFalse(st.error, st.error)
        return st

    def assign(self, st, **body):
        return st.score_instrument(dict(revision=st.text_sha(), track='guitar', instrument=2, **body))

    def test_assignment_one_undo_reopen_preserves_assets_mix_other_parts_and_raw(self):
        st = self.state()
        before, original = st.text, copy.deepcopy(st.song)
        meta = copy.deepcopy(st.meta)
        result = self.assign(st)
        self.assertEqual(result['instrument'], 2)
        self.assertEqual(st.song['score']['tracks']['guitar']['instrument'], 2)
        for key in ('samples', 'instruments', 'module', 'patterns', 'orders'):
            self.assertEqual(st.song[key], original[key])
        self.assertEqual(st.meta, meta)
        for key in ('guitar2', 'bass', 'drums'):
            self.assertEqual(st.song['score']['tracks'][key], original['score']['tracks'][key])
        after = st.text
        st.undo(); self.assertEqual(st.text, before)
        st.undo(redo=True); self.assertEqual(st.text, after)
        st.close()
        reopened = gui.State(self.path, headless=True)
        self.addCleanup(reopened.close)
        self.assertEqual(reopened.song['score']['tracks']['guitar']['instrument'], 2)
        self.assertFalse(reopened.error, reopened.error)

    def test_explicit_override_replacement_and_noop_keep_exact_history(self):
        song = complete_song_seed()
        note = next(n for p in song['score']['patterns'].values() for b in p['beats']
                    if b['track'] == 'guitar' for n in b['notes'])
        note['instrument'] = 3
        st = self.state(song)
        result = self.assign(st)
        self.assertEqual(result['overrides_preserved'], 1)
        before = st.text
        self.assign(st)
        self.assertEqual(st.text, before)
        result = self.assign(st, replace_overrides=True)
        self.assertEqual(result['overrides_replaced'], 1)
        self.assertFalse(any('instrument' in n for p in st.song['score']['patterns'].values()
                             for b in p['beats'] if b['track'] == 'guitar' for n in b['notes']))
        st.undo(); self.assertEqual(st.text, before)
        st.undo(); self.assertEqual(st.song['score']['tracks']['guitar']['instrument'], 1)

    def test_invalid_stale_and_approved_assignments_are_atomic(self):
        st = self.state()
        before = st.text
        for body in (dict(instrument=99), dict(instrument=True), dict(track='missing'),
                     dict(replace_overrides='yes'), dict(revision='stale')):
            with self.subTest(body=body), self.assertRaises(ValueError):
                st.score_instrument(dict(dict(revision=st.text_sha(), track='guitar', instrument=2), **body))
            self.assertEqual(st.text, before)
        song = complete_song_seed()
        song['patterns'][song['orders'][0]]['approved'] = True
        st = self.state(song)
        before = st.text
        with self.assertRaisesRegex(ValueError, 'approved'):
            self.assign(st)
        self.assertEqual(st.text, before)

    def test_raw_inherited_memory_refuses_without_touching_source(self):
        song = complete_song_seed()
        # Last raw row follows score note release and inherits its instrument memory.
        first = song['orders'][0]
        song['patterns'][first]['data'] = '... .. ... ...\n' * 47 + 'C-5 .. ... ...\n'
        st = self.state(song)
        before = st.text
        with self.assertRaisesRegex(ValueError, 'inherit sound memory'):
            self.assign(st)
        self.assertEqual(st.text, before)

    def test_direct_sample_song_assignment(self):
        song = complete_song_seed()
        del song['instruments']
        st = self.state(song)
        self.assign(st)
        self.assertEqual(st.song['score']['tracks']['guitar']['instrument'], 2)
        self.assertNotIn('instruments', st.song)

    def test_imported_soundfont_assignment_reaches_native_and_standalone_it(self):
        st = self.state()
        (self.base / 'bank.sf2').write_bytes(bank()[0])
        st.song_edit([dict(op='sf2_preset', path='bank.sf2', preset=0)])
        number = max(st.song['instruments'])
        before = st.text
        st.score_instrument(dict(revision=st.text_sha(), track='guitar', instrument=number))
        prepared = st.prepared_playback(44100, whole=True)
        notes = [e for e in prepared['plan']['events'] if e['type'] == 'note_on']
        lead_channels = st.song['score']['tracks']['guitar']['channels']
        lead = [e for e in notes if e['ch'] in lead_channels]
        self.assertTrue(lead)
        self.assertEqual({e['instrument'] for e in lead}, {number})
        self.assertNotEqual(before, st.text)
        written = api.compile_song(st.song, st.base_dir)[0]
        with LoadedModule(written) as module:
            instruments = {module.cell(p, r, ch)['instrument'] for p, pattern in enumerate(st.mod.patterns)
                           for r in range(len(pattern.rows)) for ch in lead_channels
                           if module.cell(p, r, ch)['note'] not in (0, 253, 254, 255)}
            self.assertEqual(instruments, {number})
            self.assertTrue(any(module.render(44100, max_seconds=.2)))
        # Mute/solo remains the existing parent-channel policy; assignment never rewrites it.
        st.meta['muted'] = lead_channels
        self.assertEqual(st.silenced(), lead_channels)
        st.undo(); self.assertEqual(st.text, before)


if __name__ == '__main__':
    unittest.main()
