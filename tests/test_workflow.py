"""Finishing/sharing workflow regressions, using disposable synthetic songs only."""
import contextlib
import copy
import io
import json
from pathlib import Path
import shutil
import tempfile
import threading
import time
import unittest
from unittest import mock

import yaml

from vulturetracker import api, arrangement, gui, measure, server, synth
from vulturetracker import history as history_io
from vulturetracker.project import collect
from vulturetracker.phrases import action as phrase_action
from vulturetracker import export
from tests import test_gui as fixtures
from tests.test_gui import SONG_BLOCK
from tests import test_gpimport
from vulturetracker import gpexport, gpimport, tgimport, tablature


class TestSafety(unittest.TestCase):
    setUp = fixtures.TestGui.setUp
    tearDown = fixtures.TestGui.tearDown
    state = fixtures.TestGui.state

    def test_publish_without_hard_links(self):
        from vulturetracker.fileio import link_new
        src, dst = self.dir / 'src.bin', self.dir / 'dst.bin'
        src.write_bytes(b'data')
        with mock.patch('os.link', side_effect=OSError('no hard links on exFAT')):
            link_new(src, dst)
            self.assertEqual(dst.read_bytes(), b'data')
            with self.assertRaises(FileExistsError):
                link_new(src, dst)

    def test_build_and_stems_protect_source_sample(self):
        path = self.dir / 'a.yaml'
        path.write_bytes((self.dir / 'song.yaml').read_bytes())
        st = gui.State(path)
        self.states.append(st)
        before = (self.dir / 'a.wav').read_bytes()
        st._build(True)
        self.assertEqual((self.dir / 'a.wav').read_bytes(), before)
        self.assertEqual(st.build['status'], 'failed')
        st.request_stems('wav', True, True)
        self.assertEqual((self.dir / 'a.wav').read_bytes(), before)
        self.assertEqual(st.stems['status'], 'failed')

    def test_new_song_preserves_existing_tone(self):
        tone = self.dir / 'new_tone.wav'
        tone.write_bytes(b'owner audio')
        path = gui.create_song(self.dir / 'new.yaml')
        self.assertEqual(tone.read_bytes(), b'owner audio')
        self.assertNotEqual(api.load(path)['samples'][1]['file'], tone.name)

    def test_new_song_refuses_an_intervening_document(self):
        path = self.dir / 'new.yaml'
        real_write = gui._atomic

        def publish(file, raw, **kwargs):
            if Path(file) == path:
                path.write_bytes(b'# created by someone else\n')
            return real_write(file, raw, **kwargs)

        with mock.patch.object(gui, '_atomic', side_effect=publish):
            with self.assertRaises(FileExistsError):
                gui.create_song(path)
        self.assertEqual(path.read_bytes(), b'# created by someone else\n')

    def test_reload_clears_stale_undo_and_redo(self):
        for redo in (False, True):
            with self.subTest(redo=redo):
                st = self.state()
                st.edit_cells(0, [{'row': 0, 'ch': 0, 'cell': 'D-5 01 ... ...'}])
                if redo:
                    st.undo()
                external = st.song_path.read_bytes() + b'# external work\n'
                st.song_path.write_bytes(external)
                st.reload()
                st.undo(redo=redo)
                self.assertEqual(st.song_path.read_bytes(), external)
                self.assertEqual((st.history, st.future), ([], []))

    def test_failed_writes_leave_document_meta_selection_and_stacks(self):
        (self.dir / 'song.yaml').write_bytes(SONG_BLOCK.encode())
        st = self.state()
        st.set_mix({'volume': {'0': 32}})
        st.add_candidates('cand.wav')
        st.set_want(str(self.dir / 'cand.wav'))
        st.edit_cells(0, [{'row': 0, 'ch': 0, 'cell': 'D-5 01 ... ...'}])
        st.undo()
        before = (st.song_path.read_bytes(), st.meta_path.read_bytes(), copy.deepcopy(st.meta),
                  copy.deepcopy(st.history), copy.deepcopy(st.future), st.want, st.text)
        for action in (st.apply_mix, lambda: st.apply(st.want),
                       lambda: st.edit_cells(0, [{'row': 0, 'ch': 0, 'cell': 'E-5 01 ... ...'}])):
            with self.subTest(action=action), mock.patch.object(st, 'write_song', side_effect=PermissionError('locked')):
                with self.assertRaises(PermissionError):
                    action()
                after = (st.song_path.read_bytes(), st.meta_path.read_bytes(), st.meta,
                         st.history, st.future, st.want, st.text)
                self.assertEqual(after, before)

    def test_restart_history_checkpoints_and_assets(self):
        st = self.state()
        st.checkpoint('original')
        st.edit_cells(0, [{'row': 0, 'ch': 0, 'cell': 'D-5 01 ... ...'}])
        newer = st.text
        st = self.state()
        self.assertEqual(len(st.history), 1)
        st.undo()
        st = self.state()
        self.assertEqual(len(st.future), 1)
        st.undo(redo=True)
        self.assertEqual(st.text, newer)
        st.checkpoint('original', 'restore')
        self.assertIn('00: C-5 01', st.text)
        st.undo()
        self.assertEqual(st.text, newer)
        (self.dir / 'a.wav').write_bytes(b'changed asset')
        with self.assertRaisesRegex(ValueError, 'asset changed'):
            st.undo()
        self.assertEqual(st.text, newer)

    def test_failed_related_write_rolls_back_every_file(self):
        st = self.state()
        st.set_mix({'volume': {'0': 32}})
        original = st.song_path.read_bytes()
        meta = st.meta_path.read_bytes()
        real_write = history_io.atomic_write

        def fail(path, raw):
            if path == st.meta_path:
                raise PermissionError('settings locked')
            real_write(path, raw)

        with mock.patch.object(history_io, 'atomic_write', side_effect=fail):
            with self.assertRaises(PermissionError):
                st.apply_mix()
        self.assertEqual(st.song_path.read_bytes(), original)
        self.assertEqual(st.meta_path.read_bytes(), meta)
        self.assertEqual(st.mix()['volume'], {'0': 32})
        self.assertEqual((st.history, st.future), ([], []))

    def test_external_change_during_save_preparation_is_not_overwritten(self):
        st = self.state()
        external = st.song_path.read_bytes() + b'# changed while saving\n'
        real_write = history_io.atomic_write

        def changed(path, raw):
            real_write(path, raw)
            if path == st.history_store.journal:
                st.song_path.write_bytes(external)

        with mock.patch.object(history_io, 'atomic_write', side_effect=changed):
            with self.assertRaisesRegex(ValueError, 'changed'):
                st.edit_cells(0, [{'row': 0, 'ch': 0, 'cell': 'D-5 01 ... ...'}])
        self.assertEqual(st.song_path.read_bytes(), external)
        self.assertEqual((st.history, st.future), ([], []))

    def test_interrupted_save_recovers_but_external_work_wins(self):
        for external in (False, True):
            with self.subTest(external=external):
                st = self.state()
                original = st.song_path.read_bytes()
                real_write = history_io.atomic_write

                def crash(path, raw):
                    if path == st.meta_path:
                        raise KeyboardInterrupt('simulated process loss')
                    real_write(path, raw)

                with mock.patch.object(history_io, 'atomic_write', side_effect=crash):
                    with self.assertRaises(KeyboardInterrupt):
                        st.edit_cells(0, [{'row': 1, 'ch': 0, 'cell': 'E-5 01 ... ...'}])
                self.assertTrue(st.history_store.journal.exists())
                if external:
                    st.song_path.write_bytes(original + b'# newer external work\n')
                disk = st.song_path.read_bytes()
                st = self.state()
                self.assertEqual(st.song_path.read_bytes(), disk)
                self.assertTrue(st.notices)
                if not external:
                    self.assertEqual(len(st.history), 1)
                    st.undo()
                    self.assertEqual(st.song_path.read_bytes(), original)
                else:
                    self.assertEqual(st.history, [])
                    self.assertTrue(list(self.dir.glob('*.recovery.json.external-conflict-*')))
                st.meta_path.unlink(missing_ok=True)

    def test_malformed_history_and_external_same_timestamp(self):
        st = self.state()
        st.history_store.path.write_text('{"schema": 1, "undo": 12}')
        st = self.state()
        self.assertEqual(st.history, [])
        self.assertTrue(list(self.dir.glob('*.history.json.corrupt-*')))
        import os
        stamp = st.song_path.stat()
        st.song_path.write_bytes(st.song_path.read_bytes().replace(b'title: T', b'title: X'))
        os.utime(st.song_path, ns=(stamp.st_atime_ns, stamp.st_mtime_ns))
        self.assertTrue(st.dirty())
        with self.assertRaisesRegex(ValueError, 'changed on disk'):
            st.edit_cells(0, [{'row': 0, 'ch': 0, 'cell': 'D-5 01 ... ...'}])

    def test_malformed_recovery_payload_keeps_all_current_files(self):
        import base64
        st = self.state()
        st.set_mix({'volume': {'0': 32}})
        original = [history_io.read_optional(p) for p in st.history_store.paths]
        # Valid outer journal, invalid target settings. It must not be replayed or delete a valid sidecar.
        pairs = list(zip(original, [original[0], b'[]', b'{}']))
        files = [[None if raw is None else base64.b64encode(raw).decode() for raw in pair] for pair in pairs]
        st.history_store.journal.write_bytes(history_io.json_bytes(
            {'schema': 1, 'song': str(st.song_path), 'files': files}))
        history_io.History(st.song_path, st.notices)
        self.assertEqual([history_io.read_optional(p) for p in st.history_store.paths], original)
        self.assertTrue(list(self.dir.glob('*.recovery.json.corrupt-*')))

    def test_restore_candidate_fingerprints_and_missing_history_assets(self):
        st = self.state()
        st.add_candidates('cand.wav')
        st.set_want(str(self.dir / 'cand.wav'))
        st.apply(st.want)
        committed = st.text
        shutil.copyfile(self.dir / 'b.wav', self.dir / 'cand.wav')
        with self.assertRaisesRegex(ValueError, 'asset changed'):
            st.undo()
        self.assertEqual(st.text, committed)
        st.history[-1]['assets'] = {}
        with self.assertRaisesRegex(ValueError, 'fingerprint'):
            st.undo()
        self.assertEqual(st.text, committed)

    def test_collect_recipe_inputs_and_frozen_phrase(self):
        source = self.dir / 'original'
        source.mkdir()
        for name in ('a.wav', 'b.wav'):
            shutil.copyfile(self.dir / name, source / name)
        (source / 'song.yaml').write_bytes(SONG_BLOCK.encode())
        (source / 'input.wav').write_bytes((self.dir / 'cand.wav').read_bytes())
        (source / 'sounds.yaml').write_bytes(
            b'# Editable source\nout_dir: .\nsamples:\n  a: {file: input.wav, note: C-5}\n')
        (source / 'ATTRIBUTION.md').write_bytes(b'Synthetic regression audio; no third-party content.\n')
        st = gui.State(source / 'song.yaml')
        self.states.append(st)
        phrase_action(st, {'action': 'capture', 'order': 0, 'r0': 0, 'r1': 3, 'chans': [0]})
        expected = Path(phrase_action(st, {'action': 'render', 'variant': 0})['path']).read_bytes()
        dest = self.dir / 'collected'
        collect(st, dest)
        source.rename(self.dir / 'unavailable')
        new = gui.State(dest / 'song.yaml')
        self.states.append(new)
        recipe = new.slot_recipe()
        self.assertIsNotNone(recipe)
        spec = api.from_yaml(recipe['spec'])
        self.assertEqual((Path(recipe['recipe']).parent / spec['file']).read_bytes(),
                         (self.dir / 'cand.wav').read_bytes())
        self.assertTrue(list((dest / 'credits').glob('ATTRIBUTION*.md')))
        output = phrase_action(new, {'action': 'render', 'variant': 0})
        self.assertEqual(Path(output['path']).read_bytes(), expected)
        phrase_action(new, {'action': 'accept', 'variant': 0})

    def test_collected_project_is_independent_and_keeps_duplicate_names(self):
        source = self.dir / 'original'
        (source / 'one').mkdir(parents=True)
        (source / 'two').mkdir()
        shutil.copyfile(self.dir / 'a.wav', source / 'one' / 'tone.wav')
        shutil.copyfile(self.dir / 'b.wav', source / 'two' / 'tone.wav')
        shutil.copyfile(self.dir / 'cand.wav', source / 'candidate.wav')
        text = SONG_BLOCK.replace('a.wav', 'one/tone.wav').replace('b.wav', 'two/tone.wav')
        song = source / 'song.yaml'
        song.write_bytes(b'\xef\xbb\xbf' + text.replace('\n', '\r\n').encode())
        st = gui.State(song)
        self.states.append(st)
        st.add_candidates('candidate.wav')
        st.set_mix({'volume': {'0': 31}})
        st.add_note({'order': 0, 'row': 0, 'text': 'Owner words'})
        original = {p.relative_to(source): p.read_bytes() for p in source.rglob('*') if p.is_file() and '.tryout' not in p.parts}
        with gui.LoadedModule(st.it) as lm:
            expected = lm.render()
        with tempfile.TemporaryDirectory() as out:
            dest = Path(out) / 'collected'
            result = collect(st, dest, True, {'local': {'faustcode': 'process = _;'}})
            for p, raw in original.items():
                self.assertEqual((source / p).read_bytes(), raw)
            self.assertTrue(Path(result['zip']).is_file())
            with self.assertRaises(ValueError):
                collect(st, dest)
            st.closed = True
            source.rename(source.with_name('unavailable'))
            new = gui.State(dest / 'song.yaml')
            self.states.append(new)
            with gui.LoadedModule(new.it) as lm:
                self.assertEqual(lm.render(), expected)
            self.assertEqual(new.mix()['volume'], {'0': 31})
            self.assertEqual(len(new.cands()), 1)
            self.assertTrue(all(Path(p).is_relative_to(dest) for p in new.files + new.cands()))
            self.assertNotEqual(new.song['samples'][1]['file'], new.song['samples'][2]['file'])
            self.assertIn(b'# a comment', new._raw)
            self.assertTrue(new._raw.startswith(b'\xef\xbb\xbf'))
            self.assertIn(b'\r\n', new._raw)
            self.assertGreater(api.render(dest / 'song.yaml', dest / 'render.wav'), 0)
            self.assertIn('Owner words', ''.join(p.read_text() for p in dest.glob('song.notes*.md')))
            # Drain the worker before the nested disposable output directory is removed.
            import time
            for _ in range(200):
                if not new.jobs.qsize() and not any(r['status'] in ('queued', 'rendering') for r in new.renders.values()):
                    break
                time.sleep(.02)

    def test_relink_preserves_properties_and_comments(self):
        st = self.state()
        original = st.text
        (self.dir / 'a.wav').rename(self.dir / 'moved.wav')
        st.reload()
        self.assertTrue(st.error)
        st.relink(1, 'moved.wav')
        self.assertIsNone(st.error)
        self.assertEqual(st.text, original.replace('file: a.wav', 'file: "moved.wav"'))

    def test_relink_hints_from_the_library_index(self):
        from vulturetracker.library import Library
        st = self.state()
        st.song_edit([{'op': 'pattern_new', 'name': 'zz', 'rows': 4}])  # an undo step records a.wav's digest
        lib_dir = self.dir / 'library'
        for sub, src in (('other', 'b.wav'), ('moved/here', 'a.wav')):  # a different file of the same name, the moved one
            (lib_dir / sub).mkdir(parents=True)
            shutil.copyfile(self.dir / src, lib_dir / sub / 'A.WAV')
        (self.dir / 'a.wav').unlink()
        st.reload()
        lib = Library(self.dir / 'index.json')
        lib.data['files'] = {str(lib_dir / 'other' / 'A.WAV'): {}, str(lib_dir / 'moved/here' / 'A.WAV'): {},
                             str(lib_dir / 'gone.wav'): {}}
        hints = st.relink_hints(lib)
        self.assertEqual(hints['indexed'], 3)
        self.assertEqual([(Path(h['path']).parent.name, h['same']) for h in hints['hints'][1]], [('here', True), ('other', False)])
        self.assertNotIn(2, hints['hints'])  # b.wav is there
        st.relink(1, hints['hints'][1][0]['path'])
        self.assertIsNone(st.error)
        self.assertEqual(st.relink_hints(lib)['hints'], {})

    def test_api_outputs_protect_sources_and_hardlinks(self):
        song = self.dir / 'song.yaml'
        before = (self.dir / 'a.wav').read_bytes()
        with self.assertRaises(ValueError):
            api.build(song, self.dir / 'a.wav')
        with self.assertRaises(ValueError):
            api.render(song, self.dir / 'a.wav')
        import os
        os.link(self.dir / 'a.wav', self.dir / 'alias.wav')
        with self.assertRaises(ValueError):
            api.render(song, self.dir / 'alias.wav')
        self.assertEqual((self.dir / 'a.wav').read_bytes(), before)

    def test_sections_move_duplicate_jumps_metadata_and_history(self):
        text = SONG_BLOCK.replace('orders: [p1, p2]', 'orders: [p1, p2, p1, p2]')
        text = text.replace('00: C-5 01 ... ...', '00: C-5 01 ... B01')
        (self.dir / 'song.yaml').write_bytes(text.encode())
        st = self.state()
        st.section_edit({'name': 'Intro', 'start': 0, 'end': 2})
        st.section_edit({'name': 'Tail', 'start': 2, 'end': 4})
        st.section_edit({'action': 'loop', 'name': 'Intro'})
        st.set_mix({'volume': {'1': 31}})
        st.add_note({'order': 0, 'row': 0, 'text': 'Historic context'})
        notes = copy.deepcopy(st.notes)
        before = st.text
        st.section_edit({'action': 'move', 'name': 'Intro', 'to': 4})
        self.assertEqual(st.song['sections']['Intro'], [2, 4])
        self.assertIn('B03', st.text)
        self.assertEqual(st.meta['loop']['from'], [2, 0])
        self.assertEqual(st.notes, notes)
        self.assertEqual(st.mix()['volume'], {'1': 31})
        st.undo()
        self.assertEqual(st.text, before)
        st.undo(redo=True)
        moved = st.text
        st.section_edit({'action': 'duplicate', 'name': 'Intro', 'to': 4, 'independent': True})
        self.assertEqual(st.song['sections']['Intro copy'], [4, 6])
        self.assertNotEqual(st.song['orders'][2], st.song['orders'][4])
        self.assertIn('B05', st.song['patterns'][st.song['orders'][4]]['data'])
        self.assertIn('B03', st.song['patterns'][st.song['orders'][2]]['data'])
        st.undo()
        self.assertEqual(st.text, moved)
        with self.assertRaisesRegex(ValueError, 'Shared copy has jumps'):
            st.section_edit({'action': 'duplicate', 'name': 'Intro', 'to': 4, 'independent': False})

    def test_shared_sections_and_unique_occurrence(self):
        st = self.state()
        st.section_edit({'name': 'Line', 'start': 0, 'end': 1})
        st.section_edit({'name': 'Line', 'action': 'duplicate', 'to': 2, 'independent': False})
        self.assertEqual(st.song['orders'], ['p1', 'p2', 'p1'])
        st.song_edit([{'op': 'pattern_clone', 'src': 'p1', 'name': 'unique'},
                      {'op': 'orders', 'orders': ['p1', 'p2', 'unique'], 'origins': [0, 1, 2]}])
        st.edit_cells(next(i for i,p in enumerate(st.mod.patterns) if p.name == 'unique'), [{'row': 0, 'ch': 0, 'cell': 'F-5 01 ... ...'}])
        self.assertIn('C-5', st.song['patterns']['p1']['data'])
        self.assertIn('F-5', st.song['patterns']['unique']['data'])
        self.assertEqual(st.song['sections']['Line copy'], [2, 3])

    def test_section_edits_preserve_comments_inside_spans(self):
        text = SONG_BLOCK + 'sections:\n  Intro: [0, # first boundary\n          1] # last boundary\n'
        (self.dir / 'song.yaml').write_bytes(text.encode())
        st = self.state()
        st.section_edit({'name': 'Intro', 'action': 'move', 'to': 2})
        self.assertEqual(st.song['sections']['Intro'], [1, 2])
        for comment in ('# first boundary', '# last boundary'):
            self.assertIn(comment, st.text)
        st.section_edit({'name': 'Intro', 'action': 'delete'})
        for comment in ('# first boundary', '# last boundary'):
            self.assertIn(comment, st.text)

    def test_three_phrase_variants_absence_and_single_step_accept(self):
        text = SONG_BLOCK.replace('orders: [p1, p2]', 'orders: [p1, p2, p1]')
        (self.dir / 'song.yaml').write_bytes(text.encode())
        st = self.state()
        st.set_mix({'volume': {'1': 29}})
        before, mix = st.text, copy.deepcopy(st.mix())
        phrase_action(st, {'action': 'capture', 'order': 2, 'r0': 0, 'r1': 3, 'chans': [0], 'count': 3})
        for i, note in enumerate(('D-5', 'E-5', 'G-5')):
            phrase_action(st, {'action': 'update', 'variant': i, 'name': 'Line '+str(i),
                              'data': f'{note} 01 ... ...\n... .. ... ...\n... .. ... ...\n... .. ... ...',
                              'stars': i+2, 'note': 'Listening choice'})
        outputs = [phrase_action(st, {'action': 'render', 'variant': i}) for i in (0, 1, 2, -1)]
        import wave
        lengths = []
        for out in outputs:
            with wave.open(out['path'], 'rb') as w:
                lengths.append(w.getnframes())
        self.assertEqual(len(set(lengths)), 1)
        self.assertEqual(len({Path(o['path']).read_bytes() for o in outputs}), 4)
        diff = phrase_action(st, {'action': 'diff', 'variant': 1})
        self.assertTrue(diff['lines'])
        phrase_action(st, {'action': 'accept', 'variant': 1, 'token': diff['token']})
        self.assertEqual(len(st.history), 1)
        self.assertNotEqual(st.song['orders'][0], st.song['orders'][2])
        self.assertIn('C-5', st.song['patterns']['p1']['data'])
        chosen = st.mod.patterns[st.mod.orders[2]]
        self.assertEqual(chosen.rows[0][0].note, 64)
        self.assertEqual([r[1] for r in chosen.rows], [r[1] for r in st.mod.patterns[st.mod.orders[0]].rows])
        self.assertEqual(st.mix(), mix)
        accepted = st.text
        st.undo()
        self.assertEqual(st.text, before)
        st.undo(redo=True)
        self.assertEqual(st.text, accepted)

    def test_phrase_frozen_audio_and_stale_acceptance(self):
        st = self.state()
        phrase_action(st, {'action': 'capture', 'order': 0, 'r0': 0, 'r1': 3, 'chans': [0]})
        out = phrase_action(st, {'action': 'render', 'variant': 0})
        expected = Path(out['path']).read_bytes()
        Path(out['path']).unlink()
        shutil.copyfile(self.dir / 'b.wav', self.dir / 'a.wav')
        out = phrase_action(st, {'action': 'render', 'variant': 0})
        self.assertEqual(Path(out['path']).read_bytes(), expected)
        with self.assertRaisesRegex(ValueError, 'asset changed'):
            phrase_action(st, {'action': 'accept', 'variant': 0})

    def phrase_score_state(self, shared=False, tied=False):
        from tests.test_tablature_sync import score_song
        song = score_song()
        song['samples'][1]['file'] = 'a.wav'
        if not tied:
            song['score']['ties'] = []
            song['score']['patterns']['a']['beats'] = song['score']['patterns']['a']['beats'][:1]
        if shared:
            song['orders'] = ['a', 'a', 'b']
            song['score']['order_ids'] = ['first', 'copy', 'second']
        path = self.dir / 'score.yaml'
        path.write_bytes(api.to_yaml(song).encode())
        st = gui.State(path, headless=True)
        self.addCleanup(st.close)
        self.assertIsNone(st.error)
        return st

    def test_native_phrase_preserves_fractional_notes_and_frozen_audio(self):
        from tests.test_tablature_sync import TestNativeLoadedModule
        from vulturetracker.phrases import edited_text, variant_wav
        from vulturetracker.wavload import write_wav
        song = TestNativeLoadedModule().native_song()
        song['orders'], song['score']['order_ids'] = ['a', 'a', 'b'], ['first', 'copy', 'second']
        tone = self.dir / 'tone.wav'
        write_wav(tone, 48000, [fixtures.sine(220, seconds=0.5)])
        source = tone.read_bytes()
        path = self.dir / 'native.yaml'
        path.write_bytes(api.to_yaml(song).encode())
        st = gui.State(path, headless=True)
        self.addCleanup(st.close)
        self.assertIsNone(st.error)
        before, score = st.text, copy.deepcopy(st.song['score']['patterns']['a'])
        phrase_action(st, {'action': 'capture', 'order': 1, 'r0': 0, 'r1': 5, 'chans': [0, 1]})
        phrase = st.meta['phrase']
        self.assertEqual(phrase['score_positions'][0]['row'], [12, 13])
        from vulturetracker.agent_projects import read_phrase
        read = read_phrase(st, {'variant': 0, 'offset': 0, 'limit': 2})
        self.assertEqual(read['captured_score_notes'], 1)
        self.assertEqual(read['captured_score_positions'][0]['row'], [12, 13])
        self.assertEqual(read['captured_score_positions'][0]['ch'], 1)
        text = edited_text(st, phrase, 0)
        expected = variant_wav(st, phrase, text)
        self.assertGreater(len(expected), 44)
        write_wav(tone, 48000, [[0] * 100])
        self.assertEqual(variant_wav(st, phrase, edited_text(st, phrase, 1)), expected)
        tone.write_bytes(source)
        rows = phrase['variants'][0]['data'].splitlines()
        cells = rows[1].split('|')
        cells[1] = ' C-5 01 v32 D07'
        rows[1] = '|'.join(cells)
        phrase_action(st, {'action': 'update', 'variant': 0, 'data': '\n'.join(rows)})
        result = phrase_action(st, {'action': 'render', 'variant': 0})
        self.assertTrue(Path(result['path']).is_file())
        self.assertNotEqual(Path(result['path']).read_bytes(), expected)
        phrase_action(st, {'action': 'accept', 'variant': 0})
        name = st.song['orders'][1]
        self.assertNotEqual(name, 'a')
        self.assertEqual(st.song['score']['patterns']['a'], score)
        self.assertEqual(st.song['score']['patterns'][name], score)
        self.assertIn('C-5 01 v32 D07', st.song['patterns'][name]['data'])
        self.assertNotIn('C-5', st.song['patterns']['a']['data'])
        accepted = st.text
        st.undo()
        self.assertEqual(st.text, before)
        st.undo(redo=True)
        self.assertEqual(st.text, accepted)
        st.close()
        reopened = gui.State(path, headless=True)
        self.addCleanup(reopened.close)
        self.assertIsNone(reopened.error)
        self.assertEqual(reopened.song['score']['patterns'][name]['beats'][0]['at'], [1, 13])

    def test_phrase_score_shared_clone_preserves_unselected_notes_and_reopen(self):
        from vulturetracker.phrases import edited_text
        from vulturetracker.song import load_song_text
        from vulturetracker.model import NOTE_OFF
        st = self.phrase_score_state(shared=True)
        original = copy.deepcopy(st.song)
        before = st.text
        phrase_action(st, {'action': 'capture', 'order': 1, 'r0': 0, 'r1': 0, 'chans': [1]})
        unchanged, _ = load_song_text(edited_text(st, st.meta['phrase'], 1), st.base_dir)
        original_projection, _ = load_song_text(before, st.base_dir)
        self.assertEqual(unchanged.patterns[unchanged.orders[1]].rows, original_projection.patterns[original_projection.orders[1]].rows)
        phrase_action(st, {'action': 'update', 'variant': 0, 'data': 'C#5 01 ... ...'})
        phrase = st.meta['phrase']
        preview, _ = load_song_text(edited_text(st, phrase, 0), st.base_dir)
        selected = preview.patterns[preview.orders[1]]
        self.assertEqual([selected.rows[0][c].note for c in (0, 1)], [64, 61])
        self.assertEqual(selected.rows[12][1].note, NOTE_OFF)
        self.assertEqual(selected.rows[0][0].effect, 24)  # residual X40 survives
        out = phrase_action(st, {'action': 'render', 'variant': 0})
        self.assertTrue(Path(out['path']).is_file())
        diff = phrase_action(st, {'action': 'diff', 'variant': 0})
        phrase_action(st, {'action': 'accept', 'variant': 0, 'token': diff['token']})
        self.assertEqual(len(st.history), 1)
        name = st.song['orders'][1]
        self.assertNotEqual(name, 'a')
        self.assertEqual(st.song['score']['order_ids'], original['score']['order_ids'])
        self.assertEqual(st.song['score']['patterns']['a'], original['score']['patterns']['a'])
        self.assertEqual(st.song['patterns'][name], original['patterns']['a'])
        notes = st.song['score']['patterns'][name]['beats'][0]['notes']
        self.assertEqual(notes[0], original['score']['patterns']['a']['beats'][0]['notes'][0])
        self.assertEqual((notes[1]['id'], notes[1]['pitch'], notes[1]['fret']), ('c', 61, 2))
        accepted = st.text
        st.undo()
        self.assertEqual(st.text, before)
        st.undo(redo=True)
        self.assertEqual(st.text, accepted)
        st.close()
        reopened = gui.State(st.song_path, headless=True)
        self.addCleanup(reopened.close)
        self.assertIsNone(reopened.error)
        reopened_projection, _ = load_song_text(reopened.text, reopened.base_dir)
        selected = reopened_projection.patterns[reopened_projection.orders[1]]
        self.assertEqual([selected.rows[0][c].note for c in (0, 1)], [64, 61])
        self.assertEqual(selected.rows[12][1].note, NOTE_OFF)
        self.assertEqual(reopened.song['score'], st.song['score'])

    def test_phrase_score_single_occurrence_and_absence_guard(self):
        from vulturetracker.phrases import edited_text
        from vulturetracker.song import SongError
        st = self.phrase_score_state()
        phrase_action(st, {'action': 'capture', 'order': 0, 'r0': 0, 'r1': 0, 'chans': [1]})
        before = st.text, copy.deepcopy(st.meta), len(st.history), st.song_path.read_bytes()
        with self.assertRaisesRegex(SongError, 'shared mixer semantics'):
            phrase_action(st, {'action': 'update', 'variant': 0, 'data': 'D-5 01 ... Q12'})
        self.assertEqual((st.text, st.meta, len(st.history), st.song_path.read_bytes()), before)
        phrase_action(st, {'action': 'update', 'variant': 0, 'data': 'D-5 01 ... D07'})
        phrase_action(st, {'action': 'accept', 'variant': 0})
        self.assertEqual(st.song['orders'], ['a', 'b'])
        self.assertEqual(st.song['score']['patterns']['a']['beats'][0]['notes'][1]['pitch'], 62)
        self.assertIn('D07', st.song['patterns']['a']['data'])
        self.assertNotIn('D-5', st.song['patterns']['a']['data'])
        phrase_action(st, {'action': 'capture', 'order': 0, 'r0': 0, 'r1': 0, 'chans': [1]})
        absent = api.from_yaml(edited_text(st, st.meta['phrase'], -1))
        name = st.meta['phrase']['snapshot_pattern']
        self.assertEqual([n['id'] for b in absent['score']['patterns'][name]['beats'] for n in b['notes']], ['e'])
        out = phrase_action(st, {'action': 'render', 'variant': -1})
        self.assertTrue(Path(out['path']).is_file())
        before = st.text, copy.deepcopy(st.meta), len(st.history), st.song_path.read_bytes()
        with self.assertRaisesRegex(ValueError, 'explicit score rest/duration'):
            phrase_action(st, {'action': 'accept', 'variant': -1})
        self.assertEqual((st.text, st.meta, len(st.history), st.song_path.read_bytes()), before)

    def test_phrase_score_tied_capture_leaves_the_song_untouched(self):
        # A tied occurrence captures: the comparison's copy keeps the tied note's ID, so the tie stays valid
        # (tablature.apply_structure_edit, since 2026-10-21); capturing never writes the song or its history.
        st = self.phrase_score_state(tied=True)
        before = st.text, copy.deepcopy(st.meta['muted']), len(st.history), st.song_path.read_bytes()
        phrase_action(st, {'action': 'capture', 'order': 0, 'r0': 0, 'r1': 0, 'chans': [1]})
        self.assertEqual((st.text, st.meta['muted'], len(st.history), st.song_path.read_bytes()), before)

    def test_export_snapshot_mix_region_and_aligned_stems(self):
        st = self.state()
        st.section_edit({'name': 'End', 'start': 1, 'end': 2})
        st.set_mix({'volume': {'0': 20}})
        opts = {'destination': str(self.dir / 'outputs'), 'name': 'saved', 'fmt': 'wav', 'tail': 0,
                'region': 'End', 'stems': True}
        saved = export.prepare(st, opts)
        current = export.prepare(st, dict(opts, name='audition', mix='current'))
        expected = export.render(current['snapshot'])
        self.assertNotEqual(export.render(saved['snapshot']), expected)
        st.set_mix({'volume': {'0': 0}})
        st.edit_cells(1, [{'row': 0, 'ch': 0, 'cell': 'F-5 02 ... ...'}])
        result = export.run(current, gui._encode)
        self.assertEqual(result['status'], 'done', result)
        import wave
        files = [Path(p) for p in result['files']]
        frames = []
        for file in files:
            with wave.open(str(file), 'rb') as w:
                frames.append(w.getnframes())
                if file.name == 'audition.wav':
                    self.assertEqual(w.readframes(w.getnframes()), expected)
        self.assertEqual(len(set(frames)), 1)
        self.assertEqual(frames[0], round(4 * 6 * 2.5 / 125 * measure.RATE))
        st.set_mix({})
        st.meta['solo'] = 1
        muted = export.prepare(st, dict(opts, name='solo', mix='current', mutes='respect'))
        self.assertNotEqual(set(export.render(muted['snapshot'])), {0})  # its preceding note carries into this order
        st.meta.update(solo=None, muted=[0, 1])
        silent = export.prepare(st, dict(opts, name='silent', mutes='respect'))
        self.assertEqual(set(export.render(silent['snapshot'])), {0})

    def test_section_export_handles_breaks_jumps_and_skip_markers(self):
        for effect in ('C03', 'B02'):
            with self.subTest(effect=effect):
                text = SONG_BLOCK.replace('orders: [p1, p2]', 'orders: [p1, +++, p2]')
                text = text.replace('01: ... .. ... ... |', f'01: ... .. ... {effect} |', 1)
                snap = export.snapshot(api.from_yaml(text), self.dir, (0, 0, 0, 3), tail=.05)
                self.assertAlmostEqual(snap['seconds'], .24, places=6)
                self.assertEqual(len(export.render(snap)), round(.29*measure.RATE)*4)
        # A later section starts at the raw order number, past the skip marker.
        doc = api.from_yaml(SONG_BLOCK.replace('orders: [p1, p2]', 'orders: [p1, +++, p2]'))
        snap = export.snapshot(doc, self.dir, (2, 0, 2, 3), tail=0)
        self.assertAlmostEqual(snap['seconds'], .48, places=6)

    def test_export_refuses_changing_source_during_snapshot(self):
        # headless: a render worker would run the global compile_song mock too, at a moment the test does not control
        # (it copied b.wav over a.wav before the snapshot read it: about 1 run in 19 failed)
        st = gui.State(self.dir / 'song.yaml', headless=True)
        real_compile = api.compile_song

        def changed(*args, **kwargs):
            result = real_compile(*args, **kwargs)
            shutil.copyfile(self.dir / 'b.wav', self.dir / 'a.wav')
            return result

        with mock.patch.object(api, 'compile_song', side_effect=changed):
            with self.assertRaisesRegex(ValueError, 'changed'):
                export.prepare(st, {'destination': str(self.dir / 'exports')})
        self.assertFalse((self.dir / 'exports').exists())

    def test_export_failure_cancel_and_intervening_files_keep_previous_outputs(self):
        st = self.state()
        dest = self.dir / 'outputs'
        dest.mkdir()
        previous = dest / 'song.mp3'
        previous.write_bytes(b'previous finished export')
        opts = {'destination': str(dest), 'fmt': 'mp3', 'replace': True, 'stems': True}

        def failed_encoder(path, pcm, fmt, loop=None):
            path.write_bytes(b'partial encoder output')
            raise OSError('simulated encoder failure')

        job = export.prepare(st, opts)
        result = export.run(job, failed_encoder)
        self.assertEqual(result['status'], 'failed')
        self.assertEqual(previous.read_bytes(), b'previous finished export')
        job = export.prepare(st, opts)
        job['cancel'].set()
        self.assertEqual(export.run(job, gui._encode)['status'], 'cancelled')
        self.assertEqual(previous.read_bytes(), b'previous finished export')
        job = export.prepare(st, {'destination': str(dest), 'fmt': 'wav'})
        out = dest / 'song.wav'
        out.write_bytes(b'new external file')
        self.assertEqual(export.run(job, gui._encode)['status'], 'failed')
        self.assertEqual(out.read_bytes(), b'new external file')

    def test_export_publication_failure_rolls_back_completed_outputs(self):
        st = self.state()
        opts = {'destination': str(self.dir / 'outputs'), 'fmt': 'wav', 'stems': True, 'replace': True, 'tail': 0}
        export.run(export.prepare(st, opts), gui._encode)
        original = {p: p.read_bytes() for p in (self.dir / 'outputs').rglob('*.wav')}
        st.set_mix({'volume': {'0': 0}})
        job = export.prepare(st, dict(opts, mix='current'))
        real_replace = export.os.replace
        failed = False

        def replace(src, dest):
            nonlocal failed
            if Path(dest).name == '01-A.wav' and not failed:
                failed = True
                raise PermissionError('simulated publication failure')
            return real_replace(src, dest)

        with mock.patch.object(export.os, 'replace', side_effect=replace):
            result = export.run(job, gui._encode)
        self.assertEqual(result['status'], 'failed')
        for file, raw in original.items():
            self.assertEqual(file.read_bytes(), raw)

    def test_game_loop_export(self):
        # p2 (the section) starts a B note on its last row that rings past its end: the loop must start with it
        song = SONG_BLOCK.replace('      02: ... .. ... ... | C-5 02 ... ...', '      02: ... .. ... ... | ... .. ... ...')
        song = song.replace('      03: ... .. ... ... | ... .. ... ...\norders', '      03: ... .. ... ... | C-5 02 ... ...\norders')
        (self.dir / 'song.yaml').write_bytes((song + 'sections:\n  Two: [1, 2]\n').encode())
        st = self.state()
        opts = {'destination': str(self.dir / 'out'), 'fmt': 'wav', 'region': 'Two', 'loop': True, 'tail': 0.5,
                'replace': True}
        job = export.prepare(st, opts)
        start, end = job['snapshot']['loop']
        self.assertEqual((start, end), (0, round(4 * 6 * 2.5 / 125 * measure.RATE)))
        import numpy as np
        b = np.frombuffer(export.render(job['snapshot'], silenced=[0]), '<i2').reshape(-1, 2).astype(int)
        self.assertGreater(np.abs(b[:2000]).max(), 1000)  # the ring-over from the region's own end
        self.assertLessEqual(np.abs(b[64:2000] - b[end+64:end+2000]).max(), 2)  # = the release after the loop's end
        result = export.run(job, gui._encode)
        from vulturetracker.wavload import read_wav
        self.assertEqual(read_wav(result['files'][0]).loops, [(start, end, False)])
        result = export.run(export.prepare(st, dict(opts, fmt='ogg')), gui._encode)
        tags = Path(result['files'][0]).read_bytes()[:4096]
        self.assertIn(b'LOOPSTART=0', tags)
        self.assertIn(f'LOOPLENGTH={end}'.encode(), tags)
        whole = export.prepare(st, dict(opts, region='', tail=0))
        self.assertEqual(whole['snapshot']['loop'], (0, round(8 * 6 * 2.5 / 125 * measure.RATE)))
        for fmt in ('mp3', 'it'):
            with self.assertRaisesRegex(ValueError, 'game loop'):
                export.prepare(st, dict(opts, fmt=fmt))
        st.edit_cells(0, [{'row': 1, 'ch': 1, 'cell': '... .. ... B01'}])
        with self.assertRaisesRegex(ValueError, 'position jumps'):
            export.prepare(st, dict(opts, region=''))

    def test_cli_export_and_collect_are_headless(self):
        from vulturetracker.__main__ import main
        from vulturetracker.wavload import read_wav
        before = sorted(p.name for p in self.dir.iterdir())
        song = str(self.dir / 'song.yaml')
        self.assertEqual(main(['export', song, '-o', str(self.dir / 'out'), '--loop', '--tail', '0', '--stems']), 0)
        self.assertEqual(read_wav(self.dir / 'out' / 'song.wav').loops, [(0, round(8 * 6 * 2.5 / 125 * measure.RATE), False)])
        self.assertEqual(len(list((self.dir / 'out' / 'song_stems').iterdir())), 2)
        self.assertEqual(main(['export', song, '-o', str(self.dir / 'out')]), 1)  # exists: --replace
        self.assertEqual(main(['collect', song, str(self.dir.parent / (self.dir.name + '-copy')), '--zip']), 0)
        self.addCleanup(shutil.rmtree, self.dir.parent / (self.dir.name + '-copy'))
        self.addCleanup((self.dir.parent / (self.dir.name + '-copy.zip')).unlink)
        self.assertTrue((self.dir.parent / (self.dir.name + '-copy') / 'song.yaml').is_file())
        self.assertEqual(sorted(p.name for p in self.dir.iterdir()), sorted(before + ['out']))  # no .tryout cache beside the song

    def test_cli_sections_checkpoints_and_phrases_land_in_the_apps_history(self):
        import contextlib
        import io
        from vulturetracker.__main__ import main
        song = self.dir / 'song.yaml'
        song.write_bytes(SONG_BLOCK.replace('orders: [p1, p2]', 'orders: [p1, p2, p1]').encode())

        def run(*args):
            out = io.StringIO()
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
                code = main([args[0], str(song), *args[1:]])
            return code, out.getvalue()
        self.assertEqual(run('sections', 'save', 'Intro', '0', '2'), (0, 'Intro: orders 0-1 (p1 p2)\n'))
        self.assertEqual(run('sections', 'duplicate', 'Intro', '3')[0], 0)
        self.assertIn('Intro copy: orders 3-4 (p1_copy1 p2_copy1)', run('sections')[1])
        self.assertEqual(run('sections', 'save', 'Bad', '0', '9')[0], 1)  # past the orders: check's error, nothing written
        self.assertEqual(run('checkpoint', 'save', 'Before')[0], 0)
        self.assertEqual(run('sections', 'delete', 'Intro copy')[0], 0)
        self.assertIn('+  "Intro copy": [3, 5]', run('checkpoint', 'diff', 'Before')[1])
        self.assertEqual(run('checkpoint', 'restore', 'Nope')[0], 1)
        self.assertEqual(run('checkpoint', 'restore', 'Before')[0], 0)
        self.assertIn('Intro copy', api.load(song)['sections'])
        # a phrase: capture, write one alternative, hear it, accept it
        self.assertEqual(run('phrase', 'capture', '--order', '2', '--rows', '0-3', '--channels', '1', '--count', '2')[0], 0)
        (self.dir / 'cells.txt').write_text('D-5 01 ... ...\n... .. ... ...\n... .. ... ...\n... .. ... ...\n', newline='\n')
        code, shown = run('phrase', 'set', 'B', '--cells', str(self.dir / 'cells.txt'), '--stars', '4', '--note', 'rises')
        self.assertEqual(code, 0)
        self.assertIn('B: B **** (rises)\n    D-5 01 ... ...', shown)
        self.assertEqual(run('phrase', 'set', 'C')[0], 1)  # two alternatives: A and B
        self.assertEqual(run('phrase', 'render', 'B', '-o', str(self.dir / 'line-b.wav'))[0], 0)
        self.assertEqual(run('phrase', 'render', 'A', '-o', str(self.dir / 'line-b.wav'))[0], 1)  # exists: --replace
        self.assertEqual(run('phrase', 'render', 'A', '-o', str(self.dir / 'line-b.wav'), '--replace')[0], 0)
        self.assertEqual(run('phrase', 'render', 'B', '-o', str(self.dir / 'a.wav'))[0], 1)  # a source of the song
        self.assertIn('+      00: D-5 01', run('phrase', 'diff', 'B')[1])
        self.assertEqual(run('phrase', 'accept', 'B')[0], 0)
        self.assertNotIn('.tryout', [p.name for p in self.dir.iterdir()])
        # the app opens on all of it: one undo step each, the accept undone first
        st = self.state()
        self.assertIn('Before', st.checkpoints)
        self.assertEqual(st.mod.patterns[st.mod.orders[2]].rows[0][0].note, 62)
        steps = len(st.history)
        self.assertEqual(steps, 5)  # save, duplicate, delete, restore, accept
        st.undo()
        self.assertEqual(st.mod.patterns[st.mod.orders[2]].rows[0][0].note, 60)
        # while the app has the song open, the commands that write are refused; those that read still answer
        history = st.history_store.path.read_bytes()
        for args in (('checkpoint', 'save', 'Later'), ('sections', 'delete', 'Intro'), ('phrase', 'accept', 'A')):
            code, said = run(*args)
            self.assertEqual(code, 1, args)
            self.assertIn('open in VultureTracker', said)
        self.assertEqual(st.history_store.path.read_bytes(), history)
        self.assertEqual(run('checkpoint')[0], 0)
        st.release_lock()  # what State.close does when the app opens another song (the system, when it quits)
        self.assertEqual(run('checkpoint', 'save', 'Later')[0], 0)
        # the same song opened again in the app stays locked: the new state takes the lock the old one held
        with mock.patch.object(gui, 'remember_song'), mock.patch.object(gui, 'WORKERS', 0):
            old = server.Handler.state
            try:
                server.Handler.open_song(song)
                server.Handler.open_song(song)
                self.assertTrue(server.open_in_app(song))
            finally:
                server.Handler.state.close()
                server.Handler.state = old
        self.assertFalse(server.open_in_app(song))


def cli(*args):
    """The command line in this process: (exit code, stdout, stderr)."""
    from vulturetracker.__main__ import main
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = main([str(a) for a in args])
    return code, out.getvalue(), err.getvalue()


def wait_for(done, seconds=10):
    end = time.time() + seconds
    while not done() and time.time() < end:
        time.sleep(0.02)
    return done()


# a click at the start of the section, at a tempo whose ticks are no whole number of samples at 44.1 or 48 kHz
CLICK_SONG = """\
module: {title: Loop, tempo: 137, speed: 6, channels: [{name: Click}]}
samples: {1: {file: click.wav}}
patterns:
  p1: {rows: 16, data: 'C-5 01 ... ...'}
  p2: {rows: 16, data: ''}
orders: [p1, p2]
sections: {Loop: [0, 2]}
"""


NOTATION_SONG = """\
module: {title: Notation wiring, tempo: 120, speed: 2, channels: [{name: High}, {name: Low}]}
samples:
  1: {file: a.wav, name: Guitar}
patterns:
  verse: {rows: 48, data: ''}
orders: [verse]
score:
  version: 1
  tracks:
    guitar: {name: Guitar, tuning: [64, 59], channels: [0, 1], instrument: 1, midi: {program: 25, bank: 0}}
  order_ids: [pass-1]
  patterns:
    verse:
      row_step: [1, 12]
      beats:
""" + ''.join(f"        - {{id: b{i}, track: guitar, voice: 0, at: [{i}, 1], written: {{value: 4}}, "
              f"notes: [{{id: n{i}, pitch: {64 + i}, string: 1, fret: {i}, velocity: 95}}]}}\n" for i in range(4)) + """\
  measures:
    - {id: m0, meter: [4, 4], from: {occurrence: pass-1, at: [0, 1]}, to: {occurrence: pass-1, at: [4, 1]}}
  ties: []
"""


class TestNotationExportWiring(unittest.TestCase):
    """The format workers' writers and readers as RENDER & EXPORT, CLI, agent and import formats."""
    setUp = fixtures.TestGui.setUp

    def tearDown(self):
        for state in self.states:
            state.close()
        self.tmp.cleanup()

    def state(self):
        path = self.dir / 'notation.yaml'
        path.write_bytes(NOTATION_SONG.encode())
        state = gui.State(path, headless=True)
        self.states.append(state)
        self.assertIsNone(state.error, state.error)
        return state

    def test_each_notation_format_publishes_the_writer_output(self):
        from vulturetracker.notation_export import native_to_lilypond, native_to_musicxml
        from vulturetracker.gpexport import native_to_gp
        from vulturetracker.tgimport import native_to_tg
        from vulturetracker.asciitab import tg_to_ascii
        state = self.state()
        before = state.song_path.read_bytes()
        channels = {'guitar': {'program': 25, 'bank': 0}}
        expected = {
            'ly': native_to_lilypond(state.song, state.mod.patterns)[0].encode('utf-8'),
            'musicxml': native_to_musicxml(state.song, state.mod.patterns, channels=channels)[0].encode('utf-8'),
            'gp3': native_to_gp(state.song, state.mod.patterns, channels=channels, version=3)[0],
            'gp4': native_to_gp(state.song, state.mod.patterns, channels=channels, version=4)[0],
            'gp5': native_to_gp(state.song, state.mod.patterns, channels=channels, version=5)[0],
            'tab': tg_to_ascii(native_to_tg(state.song, state.mod.patterns, channels=channels)[0]).encode('utf-8')}
        for fmt, data in expected.items():
            with self.subTest(fmt=fmt):
                job = export.prepare(state, {'fmt': fmt, 'name': 'score-' + fmt})
                result = export.run(job, lambda *args: self.fail('notation export must not encode audio'))
                self.assertEqual(result['status'], 'done', result['error'])
                out = (self.dir / f'score-{fmt}.{fmt}').read_bytes()
                if fmt == 'musicxml':   # the writer stamps today's date
                    self.assertEqual(out.split(b'<encoding-date>')[0], data.split(b'<encoding-date>')[0])
                else:
                    self.assertEqual(out, data)
                if fmt in ('ly', 'musicxml'):
                    self.assertNotIn(b'\r\n', out)
        legacy = export.prepare(state, {'fmt': 'tg', 'name': 'legacy', 'tg_version': '1.5'})
        self.assertEqual(legacy['tg_data'], native_to_tg(state.song, state.mod.patterns, channels=channels, version='1.5')[0])
        ly = export.prepare(state, {'fmt': 'ly', 'name': 'ly-settings', 'lilypond': {'trackName': False}})
        self.assertEqual(ly['ly_data'], native_to_lilypond(state.song, state.mod.patterns,
                                                           settings={'trackName': False})[0].encode('utf-8'))
        for bad in ({'fmt': 'gp5', 'tg_version': '1.5'}, {'fmt': 'tg', 'lilypond': {'score': False}},
                    {'fmt': 'tg', 'tg_version': '9.9'}, {'fmt': 'ly', 'stems': True}):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                export.prepare(state, dict(bad, name='rejected'))
        self.assertEqual(state.song_path.read_bytes(), before)

    def test_losses_become_export_warnings(self):
        state = self.state()
        conversion = {'losses': ['bar 1: pick stroke down (legacy formats have none)',
                                 {'scope': 'song', 'feature': 'minor mode', 'reason': 'TG keys have no mode',
                                  'count': 2, 'first': 'bar 1'}]}
        self.assertEqual(export.loss_lines('ly', conversion), [
            'LY loss: bar 1: pick stroke down (legacy formats have none)',
            'LY loss: song: minor mode: TG keys have no mode (2x, first bar 1)'])
        job = export.prepare(state, {'fmt': 'musicxml', 'name': 'warn'})
        self.assertTrue(any(w.startswith('MUSICXML notation export omits') for w in job['result']['warnings']))

    def test_cli_and_agent_accept_the_new_formats(self):
        from vulturetracker.__main__ import main, _lilypond_settings
        from vulturetracker import agent
        self.assertEqual(_lilypond_settings(['trackName=false', 'measureFrom=2', 'version=2.10.0']),
                         {'trackName': False, 'measureFrom': 2, 'version': '2.10.0'})
        with self.assertRaises(ValueError):
            _lilypond_settings(['trackName'])
        enum = agent.TOOLS['export_song'][1]['properties']['format']['enum']
        self.assertEqual(set(enum), set(export.FORMATS))
        state = self.state()
        path = state.song_path
        state.close()
        self.states.remove(state)
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            for fmt, extra in (('ly', ['--lilypond', 'trackName=false']), ('musicxml', []), ('gp4', []),
                               ('tg', ['--tg-version', '1.5'])):
                with self.subTest(fmt=fmt):
                    self.assertEqual(main(['export', str(path), '-f', fmt, '--name', 'cli-' + fmt, *extra]), 0)
                    self.assertTrue((self.dir / f'cli-{fmt}.{fmt}').stat().st_size > 0)

    def test_gtp_is_routed_to_the_guitar_pro_importer(self):
        from tests.test_gplegacy import gtp, track, FOUR, GP2
        from vulturetracker.__main__ import main
        source = self.dir / 'old.gtp'
        source.write_bytes(gtp(GP2[1], [track() for _ in range(8)], [dict(beats=[FOUR] + [[] for _ in range(7)])]))
        self.assertIn('.gtp', gui.GP_SUFFIXES)
        song_path, warnings = gui.import_beside(source, native_tab=True)
        loaded = gui.State(song_path, headless=True)
        self.states.append(loaded)
        self.assertIsNone(loaded.error, loaded.error)
        self.assertEqual(sum(len(b['notes']) for p in loaded.song['score']['patterns'].values() for b in p['beats']), 4)
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(main(['import', str(source), '-o', str(self.dir / 'cli-old.yaml'), '--native-tab']), 0)
        self.assertTrue((self.dir / 'cli-old.yaml').exists())

    def test_gpx_and_gp7_are_routed_to_the_guitar_pro_importer(self):
        from tests.test_gpx import fixture, gp6, gp7
        from vulturetracker.__main__ import main
        for suffix, data in (('.gpx', gp6(fixture(6))), ('.gp', gp7(fixture(7)))):
            with self.subTest(suffix=suffix):
                self.assertIn(suffix, gui.GP_SUFFIXES)
                source = self.dir / ('score' + suffix)
                source.write_bytes(data)
                song_path, _ = gui.import_beside(source, native_tab=True)
                loaded = gui.State(song_path, headless=True)
                self.states.append(loaded)
                self.assertIsNone(loaded.error, loaded.error)
                self.assertTrue(any(b['notes'] for p in loaded.song['score']['patterns'].values() for b in p['beats']))
                target = self.dir / f'cli{suffix.replace(".", "-")}.yaml'
                with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                    self.assertEqual(main(['import', str(source), '-o', str(target), '--native-tab']), 0)
                self.assertTrue(target.exists())


class TestNativeTg(unittest.TestCase):
    setUp = fixtures.TestGui.setUp

    def tearDown(self):
        for state in self.states:
            state.close()
        self.tmp.cleanup()

    def state(self):
        from tests.test_tablature_sync import score_song
        song = score_song()
        song['samples'][1]['file'] = 'a.wav'
        song['patterns']['a']['data'] = ''
        song['score']['tracks']['guitar']['midi'] = {'program': 24}
        for spec in song['score']['patterns'].values():
            for beat in spec['beats']:
                for note in beat['notes']:
                    note['velocity'] = 95
        # TuxGuitar closes holes in every voice on opening (TGMeasureManager.updateBeatsPreciseStart); this
        # explicit dotted-quarter rest keeps the last eighth at 7/2, as TG would open it.
        song['score']['patterns']['a']['beats'].append(dict(id='hole-rest', track='guitar', voice=0, at=[2, 1],
            written=dict(value=4, dots=1, tuplet=[1, 1]), notes=[]))
        song['score']['measures'] = [dict(id=f'm{i}', meter=[4, 4], **{
            'from': dict(occurrence=oid, at=[0, 1]), 'to': dict(occurrence=oid, at=[4, 1])})
            for i, oid in enumerate(song['score']['order_ids'])]
        path = self.dir / 'native.yaml'
        path.write_bytes(api.to_yaml(song).encode())
        state = gui.State(path, headless=True)
        self.states.append(state)
        self.assertIsNone(state.error)
        return state

    def test_frozen_tg_export_publication_and_native_import(self):
        from vulturetracker.tgimport import read_tg
        state = self.state()
        before = state.song_path.read_bytes()
        job = export.prepare(state, {'fmt': 'tg', 'name': 'notation'})
        frozen = job['tg_data']
        self.assertEqual(job['result']['conversion']['tracks'], 1)
        result = export.run(job, lambda *args: self.fail('TG export must not encode audio'))
        self.assertEqual(result['status'], 'done', result['error'])
        out = self.dir / 'notation.tg'
        self.assertEqual(out.read_bytes(), frozen)
        imported, _ = read_tg(frozen)
        self.assertEqual(len(imported['score']['measures']), 2)
        self.assertEqual(next(iter(imported['score']['tracks'].values()))['midi']['program'], 24)
        path, warnings = gui.import_beside(out)
        loaded = gui.State(path, headless=True)
        self.states.append(loaded)
        self.assertIsNone(loaded.error)
        self.assertIsNotNone(loaded.mod.native_score)
        self.assertTrue(warnings)
        self.assertEqual(state.song_path.read_bytes(), before)

    def test_ascii_tab_export_is_tuxguitars_writer_on_the_tg_score(self):
        from vulturetracker.__main__ import main
        from vulturetracker.asciitab import tg_to_ascii
        state = self.state()
        before = state.song_path.read_bytes()
        tg = export.prepare(state, {'fmt': 'tg', 'name': 'unused'})['tg_data']
        job = export.prepare(state, {'fmt': 'tab', 'name': 'ascii'})
        self.assertEqual(job['tab_data'], tg_to_ascii(tg).encode('utf-8'))
        self.assertIsNone(job['tg_data'])
        result = export.run(job, lambda *args: self.fail('TAB export must not encode audio'))
        self.assertEqual(result['status'], 'done', result['error'])
        text = (self.dir / 'ascii.tab').read_text(encoding='utf-8')
        self.assertTrue(text.startswith('Title: '))
        self.assertIn('|', text)
        self.assertFalse((self.dir / 'unused.tg').exists())
        with self.assertRaises(ValueError):
            export.prepare(state, {'fmt': 'tab', 'name': 'rejected', 'stems': True})
        path = state.song_path
        state.close()
        self.states.remove(state)
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(main(['export', str(path), '-f', 'tab', '--name', 'cli-ascii']), 0)
        self.assertEqual((self.dir / 'cli-ascii.tab').read_text(encoding='utf-8'), text)
        self.assertEqual(path.read_bytes(), before)

    def test_tg_refusal_and_output_race_preserve_files(self):
        state = self.state()
        for extra in ({'stems': True}, {'mix': 'current'}, {'mutes': 'respect'}, {'repeat': 1}):
            with self.subTest(extra=extra), self.assertRaises(ValueError):
                export.prepare(state, dict(fmt='tg', name='rejected', **extra))
        self.assertFalse((self.dir / 'rejected.tg').exists())
        job = export.prepare(state, {'fmt': 'tg', 'name': 'race'})
        out = self.dir / 'race.tg'
        out.write_bytes(b'user data')
        result = export.run(job, lambda *args: None)
        self.assertEqual(result['status'], 'failed')
        self.assertEqual(out.read_bytes(), b'user data')

    def test_cli_tg_export_and_import_dispatch(self):
        from vulturetracker.__main__ import main
        state = self.state()
        path = state.song_path
        state.close()
        self.states.remove(state)
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(main(['export', str(path), '-f', 'tg', '--name', 'cli-score']), 0)
            source = self.dir / 'cli-score.tg'
            target = self.dir / 'cli-import.yaml'
            self.assertEqual(main(['import', str(source), '-o', str(target)]), 0)
        loaded = api.from_yaml(target.read_text(encoding='utf-8'))
        self.assertEqual(len(loaded['score']['tracks']), 1)
        self.assertEqual(len(loaded['score']['measures']), 2)

    def test_agent_tg_export_uses_same_frozen_job(self):
        from vulturetracker import agent
        state = self.state()
        before = state.song_path.read_bytes()
        with mock.patch.object(state, '_put') as queue:
            reply = agent.run(state, 'export_song', {'format': 'tg', 'name': 'agent-score'})
        self.assertTrue(reply.get('ok'), reply)
        queue.assert_called_once()
        self.assertIs(queue.call_args.args[1][1], state.export_job)
        result = export.run(state.export_job, lambda *args: self.fail('notation must not render audio'))
        self.assertEqual(result['status'], 'done', result)
        status = agent.run(state, 'export_status', {'job_id': result['job_id']})['job']
        self.assertEqual(status['files'], [str(self.dir / 'agent-score.tg')])
        self.assertEqual(state.song_path.read_bytes(), before)


class TestNativeGp5(unittest.TestCase):
    setUp = fixtures.TestGui.setUp
    tearDown = TestNativeTg.tearDown

    def state(self):
        from tests.test_tablature_sync import TestNativeGp5Export
        song = TestNativeGp5Export.fixture()
        song['module']['title'] = 'GP5 workflow'
        song['samples'][1]['file'] = 'a.wav'
        song['score']['patterns']['a']['beats'][0]['notes'][0]['ghost'] = True
        path = self.dir / 'gp5-native.yaml'
        path.write_bytes(api.to_yaml(song).encode())
        state = gui.State(path, headless=True)
        self.states.append(state)
        self.assertIsNone(state.error)
        return state

    def test_frozen_gp5_publication_strict_readback_and_native_import(self):
        from vulturetracker import gpexport, gpimport
        from tests.test_tablature_sync import TestNativeGp5Export
        state = self.state()
        original = copy.deepcopy(state.song)
        before = state.song_path.read_bytes()
        job = export.prepare(state, dict(fmt='gp5', name='notation', destination=str(self.dir / 'published')))
        frozen, conversion = job['gp5_data'], copy.deepcopy(job['result']['conversion'])
        self.assertEqual(conversion['format'], 'Guitar Pro 5.00')
        self.assertEqual((conversion['tracks'], conversion['measures']), (1, 3))
        self.assertFalse((self.dir / 'published').exists())
        state.song['module']['title'] = 'Changed after prepare'
        (self.dir / 'a.wav').write_bytes(b'changed after prepare')
        with mock.patch.object(gpexport, 'native_to_gp5', side_effect=AssertionError('must publish captured GP5 bytes')):
            result = export.run(job, lambda *args: self.fail('GP5 publication must not encode audio'))
        self.assertEqual(result['status'], 'done', result.get('error'))
        out = Path(result['song'])
        self.assertEqual(out.suffix, '.gp5')
        self.assertEqual(out.read_bytes(), frozen)
        self.assertEqual(result['conversion'], conversion)
        decoded = gpimport._read_native_gp(frozen)
        restored = gpimport._native_gp_song(decoded, decoded.title)
        self.assertEqual(TestNativeGp5Export.written(restored), TestNativeGp5Export.written(original))
        self.assertEqual(decoded.title, original['module']['title'])
        path, warnings = gui.import_beside(out, native_tab=True)
        loaded = gui.State(path, headless=True)
        self.states.append(loaded)
        self.assertIsNone(loaded.error)
        self.assertIsNotNone(loaded.mod.native_score)
        self.assertEqual(TestNativeGp5Export.written(loaded.song), TestNativeGp5Export.written(original))
        self.assertEqual(loaded.song['score']['tracks']['t1']['name'], 'Guitar café')
        self.assertTrue(all(c.get('name', '').isascii() for c in loaded.song['module']['channels']))
        self.assertTrue(warnings)
        self.assertEqual(state.song_path.read_bytes(), before)
        self.assertFalse(list(out.parent.glob('.vt-export-*')))

    def test_gp5_refusals_and_cancellation_do_not_create_output(self):
        state = self.state()
        state.song['sections'] = {'whole': [0, len(state.song['orders'])]}
        destination = self.dir / 'refused'
        options = dict(fmt='gp5', name='refused', destination=str(destination))
        before = state.song_path.read_bytes(), len(state.history)
        for extra in ({'stems': True}, {'mix': 'current'}, {'mutes': 'respect'}, {'repeat': 1},
                      {'include_it': True}, {'region': 'whole'}, {'loop': True}):
            with self.subTest(extra=extra), self.assertRaises(ValueError):
                export.prepare(state, dict(options, **extra))
            self.assertFalse(destination.exists())
        note = state.song['score']['patterns']['a']['beats'][0]['notes'][0]
        note['velocity'] = 94
        with self.assertRaisesRegex(ValueError, 'GP grid'):
            export.prepare(state, options)
        note['velocity'] = 95
        self.assertFalse(destination.exists())
        note['accent'] = True
        with self.assertRaisesRegex(ValueError, 'multiple dynamics'):
            export.prepare(state, options)
        del note['accent']
        incoming = state.song['score']['patterns']['b']['beats'][0]['notes'][0]
        incoming['dead'] = True
        with self.assertRaisesRegex(ValueError, 'incoming tie and dead'):
            export.prepare(state, options)
        del incoming['dead']
        self.assertFalse(destination.exists())
        self.assertEqual((state.song_path.read_bytes(), len(state.history)), before)
        job = export.prepare(state, options)
        job['cancel'].set()
        result = export.run(job, lambda *args: self.fail('cancelled notation must not render'))
        self.assertEqual(result['status'], 'cancelled')
        self.assertFalse(destination.exists())
        self.assertEqual((state.song_path.read_bytes(), len(state.history)), before)

    def test_gp5_output_race_and_failed_replacement_preserve_existing_bytes(self):
        state = self.state()
        options = dict(fmt='gp5', name='race')
        job = export.prepare(state, options)
        out = self.dir / 'race.gp5'
        out.write_bytes(b'external GP5')
        result = export.run(job, lambda *args: self.fail('notation must not render'))
        self.assertEqual(result['status'], 'failed')
        self.assertEqual(out.read_bytes(), b'external GP5')
        replacement = export.prepare(state, dict(options, replace=True))
        with mock.patch.object(export.os, 'replace', side_effect=PermissionError('locked')):
            result = export.run(replacement, lambda *args: self.fail('notation must not render'))
        self.assertEqual(result['status'], 'failed')
        self.assertEqual(out.read_bytes(), b'external GP5')
        self.assertFalse(list(self.dir.glob('.vt-export-*')))

    def test_cli_gp5_export_and_explicit_native_import(self):
        from vulturetracker.__main__ import main
        from tests.test_tablature_sync import TestNativeGp5Export
        state = self.state()
        path, original = state.song_path, copy.deepcopy(state.song)
        state.close()
        self.states.remove(state)
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()), \
                mock.patch.object(export, 'render', side_effect=AssertionError('GP5 must not render audio')):
            self.assertEqual(main(['export', str(path), '-f', 'gp5', '--name', 'cli-score']), 0)
            source, target = self.dir / 'cli-score.gp5', self.dir / 'cli-import.yaml'
            self.assertTrue(source.is_file())
            self.assertEqual(main(['import', str(source), '-o', str(target), '--native-tab']), 0)
        restored = api.from_yaml(target.read_text(encoding='utf-8'))
        self.assertEqual(TestNativeGp5Export.written(restored), TestNativeGp5Export.written(original))
        self.assertEqual(restored['score']['tracks']['t1']['name'], 'Guitar café')
        self.assertTrue(all(c.get('name', '').isascii() for c in restored['module']['channels']))

    def test_agent_gp5_export_queues_the_frozen_job_and_reports_files(self):
        from vulturetracker import agent, gpimport
        state = self.state()
        before = state.song_path.read_bytes()
        with mock.patch.object(state, '_put') as queue:
            reply = agent.run(state, 'export_song', dict(format='gp5', name='agent-score'))
        self.assertTrue(reply.get('ok'), reply)
        queue.assert_called_once()
        self.assertIs(queue.call_args.args[1][1], state.export_job)
        frozen = state.export_job['gp5_data']
        result = export.run(state.export_job, lambda *args: self.fail('GP5 must not encode audio'))
        self.assertEqual(result['status'], 'done', result)
        status = agent.run(state, 'export_status', dict(job_id=result['job_id']))['job']
        out = self.dir / 'agent-score.gp5'
        self.assertEqual(status['files'], [str(out)])
        self.assertEqual(out.read_bytes(), frozen)
        self.assertEqual(gpimport._read_native_gp(out.read_bytes()).versionTuple, (5, 0, 0))
        self.assertEqual(state.song_path.read_bytes(), before)


class TestNativeMidi(unittest.TestCase):
    def test_exact_source_pan_preserves_import_scale_and_explicit_mix_precedence(self):
        for raw in range(17):
            with self.subTest(raw=raw):
                song = self.simple()
                for channel in song['module']['channels']:
                    channel['pan'] = raw * 4
                song['score']['tracks']['guitar']['midi'] = dict(program=25)
                plain = export.snapshot(song, self.dir, tail=0)
                song['score']['tracks']['guitar']['midi']['source_pan'] = dict(
                    value=max(0, raw * 8 - 1), mixer_pan=raw * 4)
                snap = export.snapshot(song, self.dir, tail=0)
                self.assertEqual(snap['render_it'], plain['render_it'])
                self.assertEqual(snap['plan'], plain['plan'])
                data, report = export.native_to_midi(snap)
                _, events = self.read(data)
                self.assertEqual([m.value for _, _, m in events if m.type == 'control_change' and m.control == 10],
                                 [max(0, raw * 8 - 1)])
                self.assertEqual(report['source_pan'][0]['reason'], 'preserved')
                self.assertEqual(snap['midi_metadata']['assignments'][0], {'program': 25})
        song = self.simple()
        song['score']['tracks']['guitar']['midi'] = dict(program=25, source_pan=dict(value=63, mixer_pan=32))
        for mix, expected, reason in ((None, 63, 'preserved'), ({'volume': {'0': 32}}, 63, 'preserved'),
                                      ({'pan': {'0': 32}}, 64, 'explicit_mix_override'),
                                      ({'pan': {'5': 32}}, 64, 'explicit_mix_override')):
            with self.subTest(mix=mix):
                (_, events), report = self.converted(song, tail=0, mix=mix)
                self.assertEqual([m.value for _, _, m in events if m.type == 'control_change' and m.control == 10], [expected])
                self.assertEqual(report['source_pan'][0]['reason'], reason)
        song['module']['channels'][5]['pan'] = 31
        (_, events), report = self.converted(song, tail=0)
        self.assertEqual([m.value for _, _, m in events if m.type == 'control_change' and m.control == 10], [64])
        self.assertEqual(report['source_pan'][0]['reason'], 'mixer_changed')

    def test_exact_source_pan_yields_to_raw_prefix_and_range_start(self):
        song = self.simple()
        song['score']['tracks']['guitar']['midi'] = dict(program=25, source_pan=dict(value=63, mixer_pan=32))
        song['score']['patterns']['a']['beats'][0]['at'] = [1, 1]
        for start_command, initial in (('', 32), ('12: ... .. ... X20\n', 16)):
            with self.subTest(start_command=start_command):
                self.raw(song, '00: ... .. ... X40\n' + start_command + '18: ... .. ... X80\n')
                (_, events), _ = self.converted(song, tail=0, region=(0, 12, 0, 35))
                self.assertEqual([(at, m.value) for _, at, m in events if m.type == 'control_change' and m.control == 10],
                                 [(0, initial), (240, 64)])

    def test_exact_source_pan_fans_out_to_independent_voices_with_fade(self):
        from tests.test_tablature_sync import written_voice_song
        song = written_voice_song()
        song['samples'][1]['file'] = 'a.wav'
        song['score']['tracks']['guitar']['midi'] = dict(program=25, source_pan=dict(value=63, mixer_pan=32))
        song['score']['patterns']['a']['beats'][1]['notes'][0]['fade_in'] = True
        (_, events), report = self.converted(song, tail=0)
        channels = {v['midi_channel'] for v in report['voices']}
        self.assertEqual(len(channels), 2)
        for ch in channels:
            self.assertEqual([m.value for _, _, m in events
                              if m.type == 'control_change' and m.control == 10 and m.channel == ch], [63])
            self.assertIn(31, [m.value for _, _, m in events
                              if m.type == 'control_change' and m.control == 11 and m.channel == ch])
        (_, muted_events), _ = self.converted(song, tail=0, muted=[0])
        self.assertFalse(any(m.type == 'control_change' and m.control == 10 for _, _, m in muted_events))

    def test_repeats_export_performed_visits_and_source_provenance(self):
        from fractions import Fraction
        from tests.test_tablature_sync import repeat_song
        song = repeat_song()
        song['samples'][1]['file'] = 'a.wav'
        song['score']['patterns']['a']['beats'][0]['text'] = 'Repeat text'
        song['score']['measures'][0]['marker'] = {'title': 'Start'}
        before = copy.deepcopy(song)
        (mid, events), report = self.converted(song, tail=0)
        ons = [(Fraction(at, mid.ticks_per_beat), msg.note) for _, at, msg in events
               if msg.type == 'note_on' and msg.velocity]
        self.assertEqual(ons, [(0, 64), (4, 66), (8, 64), (12, 66), (16, 67)])
        self.assertEqual([Fraction(at, mid.ticks_per_beat) for _, at, msg in events if msg.type == 'set_tempo'],
                         [0, 1, 8, 9])
        self.assertEqual([Fraction(at, mid.ticks_per_beat) for _, at, msg in events if msg.type == 'marker'], [0, 8])
        self.assertEqual([Fraction(at, mid.ticks_per_beat) for _, at, msg in events if msg.type == 'text'], [0, 8])
        self.assertEqual([v['source_occurrence'] for v in report['voices']], ['first', 'second', 'first', 'second', 'third'])
        self.assertEqual([v['play_id'] for v in report['voices']], [f'play_{i}' for i in range(1, 6)])
        self.assertEqual(song, before)

    def test_repeat_fragments_export_each_measure_and_source_head_once(self):
        from fractions import Fraction
        from tests.test_tablature_sync import repeat_fragment_song
        song = repeat_fragment_song()
        song['samples'][1]['file'] = 'a.wav'
        song['score']['patterns']['a']['beats'][1]['text'] = 'Second half'
        song['score']['measures'][1]['marker'] = {'title': 'Later'}
        before = copy.deepcopy(song)
        (mid, events), report = self.converted(song, tail=0)
        times = lambda kind: [Fraction(at, mid.ticks_per_beat) for _, at, msg in events if msg.type == kind]
        self.assertEqual([(Fraction(at, mid.ticks_per_beat), msg.note) for _, at, msg in events
                          if msg.type == 'note_on' and msg.velocity], [(0, 64), (2, 66), (4, 64), (6, 66)])
        self.assertEqual(times('marker'), [2, 6])
        self.assertEqual(times('text'), [2, 6])
        self.assertEqual(times('time_signature'), [0, 2, 4, 6])
        self.assertEqual(times('set_tempo'), [0, 1, 4, 5])
        self.assertEqual([v['source_note_id'] for v in report['voices']], ['first/head', 'first/later'] * 2)
        self.assertEqual([v['source_occurrence'] for v in report['voices']], ['first'] * 4)
        self.assertEqual(song, before)

    def test_stroke_midi_preserves_offsets_gates_and_pick_is_notation_only(self):
        from fractions import Fraction
        from tests.test_tablature_sync import stroke_song
        song = stroke_song()
        song['samples'][1]['file'] = 'a.wav'
        before = copy.deepcopy(song)
        (mid, events), report = self.converted(song, tail=0)
        ons = {msg.note: Fraction(at, mid.ticks_per_beat) for _, at, msg in events
               if msg.type == 'note_on' and msg.velocity}
        self.assertEqual(ons, {64: Fraction(1, 16), 55: Fraction(1, 32), 40: 0})
        self.assertEqual([Fraction(at, mid.ticks_per_beat) for _, at, msg in events if msg.type == 'note_off'], [1] * 3)
        song['score']['patterns']['a']['beats'][0].pop('pick_stroke')
        (plain, plain_events), _ = self.converted(song, tail=0)
        self.assertEqual(events, plain_events)
        self.assertEqual(before['score']['patterns']['a']['beats'][0]['at'], [0, 1])
        self.assertEqual(report['note_count'], 3)

    def test_chord_diagram_does_not_change_native_midi(self):
        song = self.simple()
        snapshot = export.snapshot(song, self.dir, tail=0)
        plain, report = export.native_to_midi(snapshot)
        song['score']['patterns']['a']['beats'][0]['chord'] = dict(
            name='C', first_fret=1, frets=[0, 1, 0, 2, 3, -1])
        marked = export.snapshot(song, self.dir, tail=0)
        annotated, annotated_report = export.native_to_midi(marked)
        self.assertEqual(annotated, plain)
        self.assertEqual(annotated_report, report)
        self.assertEqual(marked['render_it'], snapshot['render_it'])
        self.assertEqual(marked['plan']['events'], snapshot['plan']['events'])

    def test_fade_midi_literal_staircase_collapsed_steps_and_gain_composition(self):
        from fractions import Fraction
        for value, volume in ((4, 64), (64, 64), (4, 32)):
            with self.subTest(value=value, volume=volume):
                song = self.simple()
                beat = song['score']['patterns']['a']['beats'][0]
                beat['written']['value'] = value
                beat['notes'][0].update(fade_in=True, velocity=95, volume=volume)
                before = copy.deepcopy(song)
                (mid, events), report = self.converted(song, tail=0)
                ticks = 3840 // value
                base = (volume * 127 * 2 + 64) // 128
                scale = lambda v: (base * v * 2 + 127) // 254
                controls = [(Fraction(at, mid.ticks_per_beat), msg.value) for _, at, msg in events
                            if msg.type == 'control_change' and msg.control == 11]
                expected = [(Fraction(0), scale(127))] + [
                    (Fraction(i * (ticks // 96), 960), scale(31 + i)) for i in range(96)] + [
                    (Fraction(ticks, 960), scale(127))]
                self.assertEqual(controls, expected)
                self.assertEqual(report['fade_in']['logical_events'], 98)
                self.assertEqual([m.velocity for _, _, m in events if m.type == 'note_on'], [95])
                self.assertEqual(song, before)

    def test_fade_midi_track_scope_pulses_and_range_prefix(self):
        from fractions import Fraction
        from tests.test_tablature import beat, note
        song = self.simple()
        song['score']['patterns']['a']['beats'] = [
            beat('long', [0, 1], [dict(note('long', 40, 6, 0), velocity=95)], value=2),
            beat('fade', [1, 2], [dict(note('fade', 64, 1, 0), fade_in=True, velocity=95,
                                     tremolo_picking={'value': 16})], voice=1)]
        (mid, events), report = self.converted(song, tail=0)
        long = next(v for v in report['voices'] if v['id'] == 'first/long')
        controls = [(Fraction(at, mid.ticks_per_beat), msg.value) for _, at, msg in events
                    if msg.type == 'control_change' and msg.control == 11 and msg.channel == long['midi_channel']]
        self.assertIn((Fraction(1, 2), 31), controls)
        self.assertIn((Fraction(3, 2), 127), controls)
        pulses = [v for v in report['voices'] if v.get('pulse') is not None]
        self.assertGreater(len(pulses), 1)
        for voice in pulses[1:]:
            at = Fraction(*voice['at'])
            boundary = [msg.value for _, t, msg in events if msg.type == 'control_change' and msg.control == 11
                        and msg.channel == voice['midi_channel'] and Fraction(t, mid.ticks_per_beat) == at]
            self.assertTrue(boundary)
            self.assertNotIn(127, boundary)
        # A new export starts on a later pulse, with no earlier note carried across it.
        song['score']['patterns']['a']['beats'] = [song['score']['patterns']['a']['beats'][1]]
        (mid, events), _ = self.converted(song, tail=0, region=(0, 9, 0, 17))
        boundary = [m.value for _, t, m in events if t == 0 and m.type == 'control_change' and m.control == 11]
        self.assertEqual(boundary[-1], 55)
        self.assertNotIn(127, boundary)

    def test_fade_midi_overlapping_ramps_preserve_equal_tick_source_order(self):
        from fractions import Fraction
        from tests.test_tablature_sync import written_voice_song
        song = written_voice_song()
        song['samples'][1]['file'] = 'a.wav'
        for beat in song['score']['patterns']['a']['beats']:
            beat['notes'][0]['fade_in'] = True
        (mid, events), report = self.converted(song, tail=0)
        long = next(v for v in report['voices'] if v['id'] == 'first/long')
        controls = [(Fraction(at, mid.ticks_per_beat), msg.value) for _, at, msg in events
                    if msg.type == 'control_change' and msg.control == 11 and msg.channel == long['midi_channel']]
        expected = [(Fraction(0), -1, 127)]
        for ordinal, ticks in enumerate((960, 240)):
            expected.extend((Fraction(i * (ticks // 96), 960), ordinal, 31 + i) for i in range(96))
            expected.append((Fraction(ticks, 960), ordinal, 127))
        expected.sort(key=lambda e: (e[0], e[1]))
        self.assertEqual(controls, [(at, value) for at, _, value in expected])
        self.assertEqual([v for at, v in controls if at == Fraction(1, 4)], [55, 127])

    def test_fade_midi_old_track_does_not_control_reassigned_channel(self):
        from fractions import Fraction
        from tests.test_tablature import beat, note
        song = self.simple()
        song['module']['channels'] = [{'name': f'Track {i}'} for i in range(16)]
        song['orders'] = ['a']
        song['patterns'] = {'a': {'rows': 48, 'data': ''}}
        score = song['score']
        score['order_ids'] = ['first']
        score['tracks'] = {f't{i}': {'tuning': [64], 'channels': [i], 'instrument': 1,
                                   'midi': {'program': 25}} for i in range(16)}
        score['tracks']['t0']['midi']['source_pan'] = dict(value=63, mixer_pan=32)
        score['patterns'] = {'a': {'row_step': [1, 12], 'beats': [
            beat('fade', [0, 1], [dict(note('fade', 64, 1, 0), fade_in=True, velocity=95,
                                      tremolo_picking={'value': 16})], track='t0'),
            *[beat(f'hold{i}', [0, 1], [note(f'hold{i}', 64, 1, 0)], value=2, track=f't{i}')
              for i in range(1, 15)],
            beat('new', [959, 960], [dict(note('new', 65, 1, 1), velocity=95)], track='t15')]}}
        (mid, events), report = self.converted(song, tail=0)
        old = next(v for v in report['voices'] if v['source_channel'] == 0)
        new = next(v for v in report['voices'] if v['id'] == 'first/new')
        self.assertEqual(old['midi_channel'], new['midi_channel'])
        controls = [(Fraction(at, mid.ticks_per_beat), m.value) for _, at, m in events
                    if m.type == 'control_change' and m.control == 11 and m.channel == new['midi_channel']]
        self.assertEqual(controls[-1], (Fraction(959, 960), 127))
        pans = [(Fraction(at, mid.ticks_per_beat), m.value) for _, at, m in events
                if m.type == 'control_change' and m.control == 10 and m.channel == new['midi_channel']]
        self.assertEqual(pans, [(0, 63), (Fraction(959, 960), 64)])

    def test_written_voices_midi_keeps_identical_heads_and_independent_gates(self):
        from fractions import Fraction
        from tests.test_tablature_sync import written_voice_song
        song = written_voice_song()
        song['samples'][1]['file'] = 'a.wav'
        song['score']['patterns']['a']['beats'][1]['notes'][0].update(pitch=65, fret=1, velocity=95)
        before = copy.deepcopy(song)
        (mid, events), report = self.converted(song, tail=0)
        ons = [(Fraction(at, mid.ticks_per_beat), msg.note, msg.channel) for _, at, msg in events
               if msg.type == 'note_on' and msg.velocity]
        offs = sorted((Fraction(at, mid.ticks_per_beat), msg.note, msg.channel) for _, at, msg in events
                      if msg.type == 'note_off')
        self.assertEqual([item[:2] for item in ons], [(0, 65), (0, 65)])
        self.assertNotEqual(ons[0][2], ons[1][2])
        self.assertEqual([item[:2] for item in offs], [(Fraction(1, 4), 65), (1, 65)])
        self.assertEqual(offs[0][2], ons[1][2])
        self.assertEqual(offs[1][2], ons[0][2])
        self.assertEqual(report['note_count'], 2)
        self.assertEqual(song, before)

    def test_swing_exports_performed_notes_and_tempo_without_changing_written_positions(self):
        from fractions import Fraction
        from tests.test_tablature_sync import swing_song
        song = swing_song()
        song['samples'][1]['file'] = 'a.wav'
        before = copy.deepcopy(song)
        (mid, events), report = self.converted(song, tail=0)
        ons = [(Fraction(at, mid.ticks_per_beat), msg.note) for _, at, msg in events
               if msg.type == 'note_on' and msg.velocity]
        self.assertEqual(ons, [(Fraction(0), 64), (Fraction(2, 3), 59)])
        self.assertEqual([(Fraction(at, mid.ticks_per_beat), msg.note) for _, at, msg in events if msg.type == 'note_off'],
                         [(Fraction(2, 3), 64), (Fraction(1), 59)])
        self.assertEqual([Fraction(at, mid.ticks_per_beat) for _, at, msg in events if msg.type == 'set_tempo'],
                         [Fraction(0), Fraction(1, 2)])
        self.assertEqual(report['note_count'], 2)
        self.assertEqual(song, before)

    def test_grace_keeps_performed_timing_velocity_and_written_identity(self):
        from fractions import Fraction
        for on_beat in (False, True):
            with self.subTest(on_beat=on_beat):
                song = self.simple()
                beat = song['score']['patterns']['a']['beats'][0]
                beat['at'] = [1, 1]
                beat['notes'][0]['grace'] = dict(fret=2, value=16, velocity=47, on_beat=on_beat)
                before = copy.deepcopy(song)
                original_plan = export.snapshot(song, self.dir, tail=0)['plan']
                reclocked = export._plan_at_rate(original_plan, 48000)
                position = reclocked['positions'][0]
                self.assertEqual(position['sounding_start_frame'],
                                 export._score_frame(reclocked, position['sounding_start'], 48000))
                (mid, events), report = self.converted(song, tail=0)
                ons = [(Fraction(at, mid.ticks_per_beat), msg.note, msg.velocity)
                       for _, at, msg in events if msg.type == 'note_on' and msg.velocity]
                self.assertEqual(ons[0], (Fraction(1) if on_beat else Fraction(3, 4), 66, 47))
                self.assertEqual(ons[1][:2], (Fraction(5, 4) if on_beat else Fraction(1), 64))
                grace = report['voices'][0]
                self.assertEqual((grace['id'], grace['source_id'], grace['role']),
                                 ('first/e/grace', 'first/e', 'grace'))
                self.assertEqual(report['voices'][1]['release'], [2, 1])
                self.assertEqual(song, before)

    def test_let_ring_exports_extended_gate_without_changing_written_duration(self):
        from fractions import Fraction
        from tests.test_tablature_sync import let_ring_song
        song = let_ring_song()
        song['samples'][1]['file'] = 'a.wav'
        before = copy.deepcopy(song)
        (mid, events), report = self.converted(song, tail=0)
        ons = [(Fraction(at, mid.ticks_per_beat), msg.note) for _, at, msg in events
               if msg.type == 'note_on' and msg.velocity]
        offs = [(Fraction(at, mid.ticks_per_beat), msg.note) for _, at, msg in events if msg.type == 'note_off']
        self.assertEqual(ons, [(Fraction(0), 64), (Fraction(1), 59)])
        self.assertEqual(offs, [(Fraction(2), 64), (Fraction(2), 59)])
        self.assertEqual(report['note_count'], 2)
        self.assertEqual(song, before)

    def held_snapshot(self, song=None):
        snap = export.snapshot(song or self.simple(), self.dir, tail=0)
        original = next(e for e in snap['plan']['events'] if e['type'] == 'note_on')
        snap['plan']['events'] = [
            dict(original, id='held', at=[0, 1], hold=True),
            dict(original, id='new', at=[1, 1]),
            dict(original, type='note_off', id='held', at=[2, 1]),
            dict(original, type='note_off', id='new', at=[3, 1])]
        return snap

    def test_context_pulses_and_harmonic_head_share_frame_without_losing_gates(self):
        from fractions import Fraction
        snap = export.snapshot(self.simple(), self.dir, tail=0)
        base = next(e for e in snap['plan']['events'] if e['type'] == 'note_on')
        def on(identity, at, key, opening, closing, **fields):
            return dict(base, id=identity, at=at, context=key, context_open=opening, context_close=closing, **fields)
        def off(identity, at):
            return dict(base, type='note_off', id=identity, at=at)
        snap['plan']['events'] = [on('pulse0', [0, 1], 1, True, False, source_id='head', pulse=0),
            off('pulse0', [1, 2]), on('pulse1', [1, 2], 1, False, True, source_id='head', pulse=1),
            on('harmonic', [1, 2], 2, True, True, layers=[dict(pitch=64, velocity=47), dict(pitch=64, velocity=95)]),
            off('pulse1', [1, 1]), off('harmonic', [3, 2])]
        before = copy.deepcopy(snap)
        data, report = export.native_to_midi(snap)
        mid, events = self.read(data)
        self.assertEqual(len(report['voices']), 4)
        simultaneous = [v for v in report['voices'] if v['id'] != 'pulse0']
        self.assertEqual(len({v['midi_channel'] for v in simultaneous}), 3)
        self.assertEqual([v['context'] for v in report['voices']], [1, 1, 2, 2])
        self.assertEqual(sorted(Fraction(at, mid.ticks_per_beat) for _, at, m in events if m.type == 'note_off'),
                         [Fraction(1, 2), 1, Fraction(3, 2), Fraction(3, 2)])
        self.assertEqual(snap, before)
        snap['plan']['events'][2]['context_close'] = False
        with self.assertRaisesRegex(ValueError, 'missing context closes'):
            export.native_to_midi(snap)

    def test_model_let_ring_same_parent_hold_exports_without_velocity_or_rendering(self):
        from tests.test_tablature_sync import let_ring_song
        song = let_ring_song()
        song['samples'][1]['file'] = 'a.wav'
        song['score']['patterns']['a']['beats'][1]['notes'][0].update(pitch=66, string=1, fret=2)
        before = copy.deepcopy(song)
        snap = export.snapshot(song, self.dir, tail=0)
        attacks = [e for e in snap['plan']['events'] if e['type'] == 'note_on']
        self.assertEqual([(e['id'], e.get('hold', False), e['velocity']) for e in attacks],
                         [('first/ring', True, None), ('first/next', False, None)])
        data, report = export.native_to_midi(snap)
        mid, events = self.read(data)
        self.assertEqual([(v['id'], v['source_channel'], v['release']) for v in report['voices']],
                         [('first/ring', 0, [2, 1]), ('first/next', 0, [2, 1])])
        self.assertEqual(len({v['midi_channel'] for v in report['voices']}), 2)
        self.assertEqual(sorted((at, m.note) for _, at, m in events if m.type == 'note_off'),
                         [(2 * mid.ticks_per_beat, 64), (2 * mid.ticks_per_beat, 66)])
        self.assertEqual(song, before)

    def test_held_equal_pitch_gates_use_independent_channels_and_keep_control_ownership(self):
        from fractions import Fraction
        snap = self.held_snapshot()
        attack = next(e for e in snap['plan']['events'] if e['id'] == 'new')
        snap['plan']['events'].extend([
            dict(type='pitch', id='held', ch=0, at=[5, 2], semitones=3),
            dict(attack, id='reused', at=[3, 1]),
            dict(attack, type='note_off', id='reused', at=[4, 1])])
        before = copy.deepcopy(snap)
        data, report = export.native_to_midi(snap)
        mid, events = self.read(data)
        voices = {v['id']: v for v in report['voices']}
        old, new = voices['held']['midi_channel'], voices['new']['midi_channel']
        self.assertNotEqual(old, new)
        self.assertEqual(voices['reused']['midi_channel'], old)
        self.assertEqual(voices['held']['controls_end'], [5, 2])
        self.assertEqual(report['held_gates'], [
            dict(id='held', source_channel=0, at=[0, 1], release=[2, 1])])
        self.assertIn('scheduled releases', report['held_gate_policy'])
        self.assertTrue(voices['held']['hold'])
        self.assertNotIn('hold', voices['new'])
        gates = [(Fraction(at, mid.ticks_per_beat), m.type, m.channel, m.note)
                 for _, at, m in events if m.type in ('note_on', 'note_off')]
        self.assertEqual(sorted(gates), sorted([
            (0, 'note_on', old, 64), (2, 'note_off', old, 64),
            (1, 'note_on', new, 64), (3, 'note_off', new, 64),
            (3, 'note_on', old, 64), (4, 'note_off', old, 64)]))
        self.assertEqual([(m.channel, m.pitch) for _, at, m in events
                          if m.type == 'pitchwheel' and Fraction(at, mid.ticks_per_beat) == Fraction(5, 2)],
                         [(old, 2048), (old, 0)])
        self.assertEqual(snap, before)

    def test_held_overlap_refuses_unprotected_ambiguous_or_nonordinary_attacks(self):
        for case in ('unprotected', 'third', 'group', 'pulse', 'inherited',
                     'hold-type', 'hold-off', 'duplicate-parent', 'duplicate-id'):
            with self.subTest(case=case):
                snap = self.held_snapshot()
                first, second = snap['plan']['events'][:2]
                if case == 'unprotected':
                    first.pop('hold')
                elif case == 'third':
                    snap['plan']['events'].extend([
                        dict(second, id='third', at=[3, 2]),
                        dict(second, id='third', type='note_off', at=[4, 1])])
                elif case == 'group':
                    second['layers'] = [dict(pitch=64, velocity=95)]
                elif case == 'pulse':
                    second.update(source_id='head', pulse=0)
                elif case == 'inherited':
                    second['source_instrument'] = 0
                elif case == 'hold-type':
                    first['hold'] = 1
                elif case == 'hold-off':
                    snap['plan']['events'][2]['hold'] = True
                elif case == 'duplicate-parent':
                    second['at'] = [0, 1]
                else:
                    second['id'] = first['id']
                with self.assertRaisesRegex(ValueError, 'held gate|held overlap|hold must|inherited|duplicate attack'):
                    export.native_to_midi(snap)
        song = self.simple()
        song['instruments'] = {1: dict(sample=1, nna='continue')}
        with self.assertRaisesRegex(ValueError, 'NNA, duplicate-note'):
            export.native_to_midi(self.held_snapshot(song))

    def test_held_cohort_refuses_parent_raw_controls_but_accepts_tempo_and_global(self):
        from vulturetracker.itreader import read_it
        from vulturetracker.model import Cell, NOTE_OFF
        cases = [dict(note=65, instrument=1), dict(note=NOTE_OFF), dict(instrument=1),
                 dict(volcmd=32), dict(effect=4, param=1), dict(effect=13, param=32),
                 dict(effect=24, param=64)]
        for row in (0, 6, 30):
            for fields in cases:
                with self.subTest(row=row, fields=fields):
                    snap = self.held_snapshot()
                    mod, warnings = read_it(snap['render_it'])
                    mod.patterns[0].rows[row][0] = Cell(**fields)
                    with mock.patch('vulturetracker.itreader.read_it', return_value=(mod, warnings)):
                        with self.assertRaisesRegex(ValueError, 'held parent backing'):
                            export.native_to_midi(snap)
        snap = self.held_snapshot()
        mod, warnings = read_it(snap['render_it'])
        mod.patterns[0].rows[6][0] = Cell(effect=20, param=snap['plan']['tempo'])
        mod.patterns[0].rows[18][0] = Cell(effect=22, param=64)
        with mock.patch('vulturetracker.itreader.read_it', return_value=(mod, warnings)):
            data, report = export.native_to_midi(snap)
        _, events = self.read(data)
        self.assertEqual(report['note_count'], 2)
        self.assertEqual(len([m for _, _, m in events if m.type == 'sysex']), 2)

    def test_held_parent_scope_covers_attacks_and_backing_outside_export_range(self):
        from vulturetracker.itreader import read_it
        from vulturetracker.model import Cell
        for case in ('group', 'pulse', 'inherited', 'local-backing', 'unused-backing'):
            with self.subTest(case=case):
                snap = self.held_snapshot()
                snap['range_at'] = [[0, 1], [3, 1]]
                later = dict(snap['plan']['events'][1], id='outside', at=[4, 1])
                if case == 'group':
                    later['layers'] = [dict(pitch=64, velocity=95)]
                elif case == 'pulse':
                    later.update(source_id='outside-head', pulse=0)
                elif case == 'inherited':
                    later['source_instrument'] = 0
                snap['plan']['events'].extend([
                    later, dict(snap['plan']['events'][3], id='outside', at=[5, 1])])
                mod, warnings = read_it(snap['render_it'])
                if case == 'local-backing':
                    mod.patterns[mod.orders[1]].rows[6][0] = Cell(effect=24, param=64)
                elif case == 'unused-backing':
                    mod.patterns.append(copy.deepcopy(mod.patterns[0]))
                    mod.patterns[-1].rows[6][0] = Cell(effect=13, param=32)
                with mock.patch('vulturetracker.itreader.read_it', return_value=(mod, warnings)):
                    with self.assertRaisesRegex(ValueError, 'held overlap|inherited|held parent backing'):
                        export.native_to_midi(snap)
        # An unrelated parent's normal controls and harmonic attacks stay supported.
        snap = self.held_snapshot()
        other = dict(snap['plan']['events'][1], id='other', ch=1, at=[0, 1],
                     layers=[dict(pitch=60, velocity=95), dict(pitch=72, velocity=95)])
        snap['plan']['events'].extend([
            other, dict(snap['plan']['events'][3], id='other', ch=1, at=[2, 1])])
        mod, warnings = read_it(snap['render_it'])
        # The reader trims the empty backing to one channel; append channel 1.
        mod.patterns[0].rows[6].append(Cell(effect=24, param=64))
        with mock.patch('vulturetracker.itreader.read_it', return_value=(mod, warnings)):
            _, report = export.native_to_midi(snap)
        self.assertEqual(report['note_count'], 4)

    def test_held_overlap_capacity_refuses_before_output_and_region_gates_stay_exact(self):
        snap = self.held_snapshot()
        attack = snap['plan']['events'][0]
        snap['plan']['events'] = []
        for i in range(16):
            snap['plan']['events'].extend([
                dict(attack, id=f'held-{i}', at=[i, 16]),
                {k: v for k, v in dict(attack, type='note_off', id=f'held-{i}', at=[3, 1]).items()
                 if k != 'hold'}])
        state = self.state(self.simple())
        destination = self.dir / 'held-capacity'
        with mock.patch.object(export, 'snapshot', return_value=snap):
            with self.assertRaisesRegex(ValueError, 'more than 15'):
                export.prepare(state, dict(fmt='mid', destination=str(destination)))
        self.assertFalse(destination.exists())
        snap = self.held_snapshot()
        snap['range_at'] = [[0, 1], [3, 2]]
        _, report = export.native_to_midi(snap)
        self.assertEqual(set(report['clipped_releases']), {'held', 'new'})
        self.assertTrue(all(v['release'] == [3, 2] for v in report['voices']))
        snap['range_at'] = [[1, 1], [4, 1]]
        with self.assertRaisesRegex(ValueError, 'carries across the range start'):
            export.native_to_midi(snap)

    def test_repetition_keeps_every_pulse_pitch_gate_and_source_identity(self):
        from fractions import Fraction
        song = self.simple()
        note = song['score']['patterns']['a']['beats'][0]['notes'][0]
        note.update(velocity=95, trill={'fret': 2, 'value': 16},
                    harmonic={'type': 'semi', 'data': 0})
        (mid, events), report = self.converted(song, tail=0)
        ons = [(Fraction(at, mid.ticks_per_beat), m.note, m.velocity)
               for _, at, m in events if m.type == 'note_on' and m.velocity]
        offs = [(Fraction(at, mid.ticks_per_beat), m.note)
                for _, at, m in events if m.type == 'note_off']
        self.assertEqual(ons, [(Fraction(i, 4), 64 if i % 2 == 0 else 66, 95) for i in range(4)])
        self.assertEqual(offs, [(Fraction(1, 4), 64), (Fraction(1, 2), 66),
                               (Fraction(3, 4), 64), (Fraction(959, 960), 66)])
        self.assertEqual([v['pulse'] for v in report['voices']], list(range(4)))
        self.assertTrue(all(v['source_id'] == 'first/e' for v in report['voices']))
        self.assertEqual(len({v['id'] for v in report['voices']}), 4)

    def test_track_program_bank_are_frozen_and_precede_notes(self):
        song = self.simple()
        song['score']['tracks']['guitar']['midi'] = {'program': 24, 'bank': 129}
        snapshot = export.snapshot(song, self.dir, tail=0)
        song['score']['tracks']['guitar']['midi']['program'] = 99
        data, report = export.native_to_midi(snapshot)
        _, events = self.read(data)
        setup = [(at, m.type, getattr(m, 'control', None), getattr(m, 'value', None),
                  getattr(m, 'program', None)) for _, at, m in events
                 if m.type == 'program_change' or m.type == 'control_change' and m.control in (0, 32)]
        self.assertEqual(setup, [(0, 'control_change', 0, 1, None),
                                (0, 'control_change', 32, 1, None),
                                (0, 'program_change', None, None, 24)])
        kinds = [m.type for _, _, m in events]
        self.assertLess(kinds.index('program_change'), kinds.index('note_on'))
        self.assertEqual((report['channels'][0]['bank'], report['channels'][0]['program']), (129, 24))
        self.assertFalse(any('destination sounds are unspecified' in loss for loss in report['losses']))
        song['score']['tracks']['guitar']['midi'] = {'program': 0}
        (_, events), _ = self.converted(song, tail=0)
        self.assertEqual([m.program for _, _, m in events if m.type == 'program_change'], [0])
        self.assertEqual([m.value for _, _, m in events if m.type == 'control_change' and m.control in (0, 32)], [0, 0])

    def test_midi_uses_performed_dynamics_without_rewriting_authored_velocity(self):
        import copy
        song = self.simple()
        first = song['score']['patterns']['a']['beats'][0]
        first['notes'][0].update(velocity=95, hammer=True)
        second = copy.deepcopy(first)
        second.update(id='ghost_following', at=[1, 1])
        second['notes'][0].update(id='ghost_note', hammer=False, ghost=True)
        song['score']['patterns']['a']['beats'].append(second)
        before = copy.deepcopy(song)
        (_, events), _ = self.converted(song, tail=0)
        self.assertEqual([msg.velocity for _, _, msg in events if msg.type == 'note_on'], [95, 54])
        self.assertEqual(song, before)

    def test_frozen_beat_text_and_markers_keep_exact_anchors_and_region(self):
        from fractions import Fraction
        from tests.test_tablature import beat
        song = self.simple()
        song['score']['patterns']['a']['beats'][0]['text'] = 'Start <softly>'
        track = song['score']['patterns']['a']['beats'][0]['track']
        rest = beat('annotation', [4, 3], [], value=8, tuplet=[3, 2], track=track)
        rest['text'] = 'Café Ω'
        song['score']['patterns']['a']['beats'].append(rest)
        ids = song['score']['order_ids']
        song['score']['measures'] = [dict(id=f'm{i}', meter=[4, 4], marker=dict(title=f'Part {i}', color='#123456'), **{
            'from': dict(occurrence=oid, at=[0, 1]), 'to': dict(occurrence=oid, at=[4, 1])}) for i, oid in enumerate(ids)]
        snapshot = export.snapshot(song, self.dir, tail=0)
        song['score']['patterns']['a']['beats'][0]['text'] = 'Later edit'
        data, report = export.native_to_midi(snapshot)
        mid, events = self.read(data)
        text = [(Fraction(at, mid.ticks_per_beat), msg.text) for _, at, msg in events if msg.type == 'text']
        self.assertIn((Fraction(0), 'Start <softly>'), text)
        self.assertIn((Fraction(4, 3), 'Café Ω'), text)
        self.assertNotIn('Later edit', [t for _, t in text])
        self.assertEqual([(at // mid.ticks_per_beat, msg.text) for _, at, msg in events if msg.type == 'marker'],
                         [(0, 'Part 0'), (4, 'Part 1')])
        self.assertEqual(report['annotations'], dict(markers=2, texts=2))
        (mid, events), report = self.converted(song, region=(0, 12, 1, 47), tail=0)
        self.assertEqual([(Fraction(at, mid.ticks_per_beat), msg.text) for _, at, msg in events if msg.type == 'text'],
                         [(Fraction(1, 3), 'Café Ω')])
        self.assertEqual(report['annotations'], dict(markers=1, texts=1))

    setUp = fixtures.TestGui.setUp

    def tearDown(self):
        for st in self.states:
            st.close()  # These States are headless; no render worker needs draining.
        self.tmp.cleanup()

    def song(self):
        from tests.test_tablature_sync import score_song
        song = score_song()
        song['samples'][1]['file'] = 'a.wav'
        return song

    def simple(self):
        song = self.song()
        song['score']['ties'] = []
        song['score']['patterns']['a']['beats'] = song['score']['patterns']['a']['beats'][:1]
        song['score']['patterns']['a']['beats'][0]['notes'] = song['score']['patterns']['a']['beats'][0]['notes'][:1]
        song['score']['patterns']['b']['beats'] = []
        song['patterns']['a']['data'] = ''
        return song

    def state(self, song=None):
        path = self.dir / 'native.yaml'
        path.write_bytes(api.to_yaml(song or self.song()).encode())
        st = gui.State(path, headless=True)
        self.states.append(st)
        self.assertIsNone(st.error)
        return st

    def converted(self, song=None, **options):
        snap = export.snapshot(song or self.song(), self.dir, **options)
        data, report = export.native_to_midi(snap)
        return self.read(data), report

    def read(self, data):
        import mido
        mid = mido.MidiFile(file=io.BytesIO(data), charset='utf-8')
        events = []
        for index, track in enumerate(mid.tracks):
            at = 0
            for event in track:
                at += event.time
                events.append((index, at, event))
        return mid, events

    def raw(self, song, rows):
        cells = {int(line.split(':', 1)[0]): line.split(':', 1)[1].strip() for line in rows.splitlines()}
        song['patterns']['a']['data'] = '\n'.join(cells.get(row, '... .. ... ...') for row in range(48))

    def test_exact_ties_and_end_rests_parse_as_midi(self):
        (mid, events), report = self.converted()
        notes = [(at, msg.type, msg.note) for _, at, msg in events
                 if msg.type in ('note_on', 'note_off') and msg.channel == 0]
        self.assertEqual(notes, [(0, 'note_on', 64), (480, 'note_off', 64),
                                 (1680, 'note_on', 64), (2160, 'note_off', 64)])
        self.assertEqual([at for _, at, msg in events if msg.type == 'end_of_track'], [3840] * 3)
        self.assertEqual((mid.type, mid.ticks_per_beat, report['note_count']), (1, 480, 6))
        self.assertEqual(report['quantized_events'], 0)
        self.assertTrue(any('destination sounds' in loss for loss in report['losses']))
        self.assertTrue(any('Finite audio tail' in loss for loss in report['losses']))

    def test_independent_pitch_uses_rpn_and_exact_native_control_times(self):
        from fractions import Fraction
        song = self.simple()
        chord = song['score']['patterns']['a']['beats'][0]['notes']
        chord[0].update(velocity=95, vibrato=True)
        chord.append(dict(id='other', string=2, fret=1, pitch=60, velocity=73,
                          bend={'points': [{'position': 0, 'value': 0}, {'position': 12, 'value': 4}]}))
        before = copy.deepcopy(song)
        snap = export.snapshot(song, self.dir, tail=0)
        data, report = export.native_to_midi(snap)
        mid, events = self.read(data)
        voices = report['voices']
        self.assertEqual(len({v['midi_channel'] for v in voices}), 2)
        for voice in voices:
            channel = voice['midi_channel']
            actual = [(Fraction(at, mid.ticks_per_beat), msg.pitch) for _, at, msg in events
                      if msg.type == 'pitchwheel' and msg.channel == channel]
            expected = [(Fraction(*e['at']), int(e['semitones'] * 8192 / 12))
                        for e in snap['plan']['events'] if e['type'] == 'pitch' and e['id'] == voice['id']]
            # Neutral initialization and final neutral ownership reset surround
            # every frozen control, including a control coincident with release.
            self.assertEqual(actual, [(Fraction(0), 0), *expected, (Fraction(*voice['controls_end']), 0)])
            rpn = [(m.control, m.value) for _, _, m in events if m.type == 'control_change'
                   and m.channel == channel and m.control in (101, 100, 6, 38)]
            self.assertEqual(rpn, [(101, 0), (100, 0), (6, 12), (38, 0), (101, 127), (100, 127)])
            messages = [m for _, at, m in events if at == 0 and getattr(m, 'channel', None) == channel]
            self.assertLess(next(i for i, m in enumerate(messages) if m.type == 'pitchwheel'),
                            next(i for i, m in enumerate(messages) if m.type == 'note_on'))
        self.assertEqual(report['pitch'], dict(range_semitones=12, max_error_semitones=[0, 1]))
        self.assertEqual(song, before)

    def test_harmonic_duplicate_layers_ties_and_region_clipping(self):
        song = self.simple()
        head = song['score']['patterns']['a']['beats'][0]
        head['written']['value'] = 1
        head['notes'][0].update(pitch=52, string=6, fret=12, velocity=95,
                                harmonic=dict(type='semi', data=0), vibrato=True)
        continuation = copy.deepcopy(head)
        continuation.update(id='continued', written={'value': 4})
        continuation['notes'] = [dict(id='continued', pitch=52, string=6, fret=12)]
        song['score']['patterns']['b']['beats'] = [continuation]
        song['score']['ties'] = [dict(**{'from': dict(occurrence='first', note='e')},
                                    to=dict(occurrence='second', note='continued'))]
        before = copy.deepcopy(song)
        (mid, events), report = self.converted(song, tail=0)
        attacks = [(at, m.note, m.velocity, m.channel) for _, at, m in events if m.type == 'note_on']
        self.assertEqual([(at, pitch, velocity) for at, pitch, velocity, _ in attacks],
                         [(0, 52, 47), (0, 52, 31), (0, 64, 95)])
        self.assertEqual(len({ch for _, _, _, ch in attacks}), 3)
        self.assertEqual([(at, m.note) for _, at, m in events if m.type == 'note_off'],
                         [(5 * mid.ticks_per_beat, 52), (5 * mid.ticks_per_beat, 52), (5 * mid.ticks_per_beat, 64)])
        wheels = [[(at, m.pitch) for _, at, m in events if m.type == 'pitchwheel' and m.channel == ch]
                  for _, _, _, ch in attacks]
        self.assertEqual(wheels[0], wheels[1])
        self.assertEqual(wheels[1], wheels[2])
        self.assertEqual((report['note_count'], song), (3, before))
        (mid, events), report = self.converted(song, region=(0, 0, 0, 47), tail=0)
        self.assertEqual(report['clipped_releases'], ['first/e'])
        self.assertEqual([at for _, at, m in events if m.type == 'note_off'], [4 * mid.ticks_per_beat] * 3)
        self.assertTrue(all(at <= 4 * mid.ticks_per_beat for _, at, _ in events))

    def test_tail_controls_hold_channels_and_reuse_orders_off_reset_pitch_on(self):
        song = self.simple()
        first = song['score']['patterns']['a']['beats'][0]
        for at in (1, 2):
            later = copy.deepcopy(first)
            later.update(id=f'later{at}', at=[at, 1])
            later['notes'][0]['id'] = f'n{at}'
            song['score']['patterns']['a']['beats'].append(later)
        snap = export.snapshot(song, self.dir, tail=0)
        # The native engine can control a release tail; retain that ownership
        # even though MIDI has already received the matching gate release.
        for identity, at, semitones in [('first/e', [0, 1], 2.0625), ('first/e', [2, 1], 1.5),
                                         ('first/n2', [2, 1], -3)]:
            snap['plan']['events'].append(dict(type='pitch', id=identity, ch=0, at=at, semitones=semitones))
        data, report = export.native_to_midi(snap)
        mid, events = self.read(data)
        self.assertEqual([v['midi_channel'] for v in report['voices']], [0, 1, 0])
        at_reuse = [(m.type, getattr(m, 'pitch', None)) for _, at, m in events
                    if at == 2 * mid.ticks_per_beat and getattr(m, 'channel', None) == 0
                    and m.type in ('note_off', 'note_on', 'pitchwheel')]
        self.assertEqual(at_reuse, [('pitchwheel', 1024), ('pitchwheel', 0),
                                   ('pitchwheel', -2048), ('note_on', None)])
        self.assertEqual([m.pitch for _, at, m in events if at == 0 and m.type == 'pitchwheel'], [0, 1408])
        # When the previous gate also ends at reuse, its note-off precedes its
        # terminal control/reset and the next attack on that physical channel.
        next(e for e in snap['plan']['events'] if e['type'] == 'note_off' and e['id'] == 'first/e')['at'] = [2, 1]
        snap['plan']['events'] = [e for e in snap['plan']['events'] if e['id'] not in ('first/n1', 'first/n2')]
        first_on = next(e for e in snap['plan']['events'] if e['type'] == 'note_on')
        snap['plan']['events'].extend([dict(first_on, id='reused', at=[2, 1]),
                                      dict(first_on, type='note_off', id='reused', at=[3, 1])])
        data, _ = export.native_to_midi(snap)
        _, events = self.read(data)
        self.assertEqual([m.type for _, at, m in events if at == 960 and getattr(m, 'channel', None) == 0],
                         ['note_off', 'pitchwheel', 'pitchwheel', 'note_on'])

    def test_program_reuse_is_explicit_and_unspecified_sound_conflict_refuses(self):
        song = self.simple()
        song['module']['channels'] = [{'name': f'Part {i}'} for i in range(16)]
        song['score']['tracks'] = {
            f't{i}': dict(tuning=[60], channels=[i], instrument=1, midi=dict(program=i, bank=i))
            for i in range(16)}
        song['score']['patterns']['a']['beats'] = [
            dict(id=f'b{i}', track=f't{i}', voice=0, at=[i, 4], written=dict(value=16),
                 notes=[dict(id=f'n{i}', pitch=60, string=1, fret=0)]) for i in range(16)]
        (mid, events), report = self.converted(song, tail=0)
        self.assertEqual(report['note_count'], 16)
        reused = report['voices'][-1]['midi_channel']
        self.assertEqual(reused, report['voices'][0]['midi_channel'])
        programs = [(at, m.program) for _, at, m in events if m.type == 'program_change' and m.channel == reused]
        self.assertEqual(programs, [(0, 0), (15 * mid.ticks_per_beat // 4, 15)])
        last = [m.type for _, at, m in events if at == 15 * mid.ticks_per_beat // 4
                and getattr(m, 'channel', None) == reused]
        self.assertLess(last.index('program_change'), last.index('note_on'))
        del song['score']['tracks']['t15']['midi']
        with self.assertRaisesRegex(ValueError, 'incompatible unspecified/program ownership'):
            self.converted(song)

    def test_harmonic_capacity_and_percussion_refuse_before_publication(self):
        song = self.simple()
        chord = song['score']['patterns']['a']['beats'][0]['notes']
        chord[:] = [dict(id=f'n{i}', string=i + 1, fret=0, pitch=pitch, velocity=95,
                         harmonic=dict(type='semi', data=0))
                    for i, pitch in enumerate(song['score']['tracks']['guitar']['tuning'])]
        state = self.state(song)
        destination = self.dir / 'capacity'
        with self.assertRaisesRegex(ValueError, 'more than 15'):
            export.prepare(state, dict(fmt='mid', destination=str(destination)))
        self.assertFalse(destination.exists())
        (_, events), report = self.converted(song, muted=[5], tail=0)
        self.assertEqual(report['note_count'], 15)
        self.assertEqual({m.channel for _, _, m in events if m.type == 'note_on'}, set(range(16)) - {9})
        song = self.simple()
        song['score']['tracks']['guitar']['midi'] = dict(program=0, bank=128)
        from vulturetracker.song import SongError
        with self.assertRaisesRegex(SongError, 'percussion requires zero tuning and capo'):
            self.converted(song)

    def test_pitch_endpoint_precision_and_invalid_range(self):
        snap = export.snapshot(self.simple(), self.dir, tail=0)
        for at, value in [([0, 1], -12), ([1, 2], 12)]:
            snap['plan']['events'].append(dict(type='pitch', id='first/e', ch=0, at=at, semitones=value))
        data, report = export.native_to_midi(snap)
        _, events = self.read(data)
        self.assertEqual([m.pitch for _, _, m in events if m.type == 'pitchwheel'], [0, -8192, 8191, 0])
        self.assertEqual(report['pitch']['max_error_semitones'], [3, 2048])
        snap['plan']['events'][-1]['semitones'] = 13
        with self.assertRaisesRegex(ValueError, '12-semitone range'):
            export.native_to_midi(snap)

    def test_piecewise_tempo_snapshot_region_and_reclock_use_absolute_prefixes(self):
        from fractions import Fraction
        song = self.simple()
        song['score']['patterns']['a']['beats'][0]['at'] = [1, 1]
        self.raw(song, '06: ... .. ... TB4\n24: ... .. ... T3C')
        full = export.snapshot(song, self.dir, tail=0)
        self.assertEqual(full['seconds'], 6.75)
        self.assertEqual(full['frames'], 297675)
        snap = export.snapshot(song, self.dir, region=(0, 12, 0, 35), tail=.25)
        self.assertEqual(snap['range_at'], [[1, 1], [3, 1]])
        self.assertEqual(snap['seconds'], 4 / 3)
        self.assertEqual(snap['frames'], 58800 + 11025)
        plan = export._plan_at_rate(snap['plan'], 48000)
        self.assertEqual(plan['duration']['frames'], 324000)
        self.assertEqual([(e['type'], e['frame']) for e in plan['events']],
                         [('note_on', 20000), ('note_off', 36000)])
        self.assertEqual(export._score_frame(plan, [3, 1], 48000) -
                         export._score_frame(plan, [1, 1], 48000), 64000)
        self.assertEqual(snap['plan']['sample_rate'], 88200)
        data, report = export.native_to_midi(snap)
        mid, events = self.read(data)
        self.assertEqual([(Fraction(at, mid.ticks_per_beat), m.tempo) for _, at, m in events if m.type == 'set_tempo'],
                         [(Fraction(0), 333333), (Fraction(1), 1000000)])
        self.assertEqual(report['tempo']['duration_error_microseconds'], [-1, 3])
        self.assertEqual(report['duration_seconds'], 1.333333)

    def test_tempo_map_is_frozen_includes_muted_controls_and_exact_rounding_report(self):
        from fractions import Fraction
        song = self.simple()
        song['score']['patterns']['a']['beats'][0]['notes'][0].update(
            velocity=95, harmonic=dict(type='semi'), vibrato=True)
        self.raw(song, '00: ... .. ... ... | ... .. ... T89\n04: ... .. ... ... | ... .. ... TB3\n'
                       '24: ... .. ... ... | ... .. ... T43')
        original = copy.deepcopy(song)
        snapshot = export.snapshot(song, self.dir, muted=[1], tail=0)
        song['patterns']['a']['data'] = ''
        data, report = export.native_to_midi(snapshot)
        mid, events = self.read(data)
        self.assertEqual([(Fraction(at, mid.ticks_per_beat), m.tempo) for _, at, m in events if m.type == 'set_tempo'],
                         [(Fraction(0), 437956), (Fraction(1, 3), 335196), (Fraction(2), 895522)])
        expected_error = ((Fraction(437956) - Fraction(60_000_000, 137)) / 3 +
                          (Fraction(335196) - Fraction(60_000_000, 179)) * Fraction(5, 3) +
                          (Fraction(895522) - Fraction(60_000_000, 67)) * 6)
        self.assertEqual(report['tempo']['duration_error_microseconds'],
                         [expected_error.numerator, expected_error.denominator])
        self.assertEqual([s['source_bpm'] for s in report['tempo']['segments']], [137, 179, 67])
        self.assertEqual(report['note_count'], 3)
        self.assertEqual(report['quantized_events'], 0)
        # A range starts with the latest prefix tempo, not module.tempo or
        # the first authored tempo. The end boundary's T43 is outside it.
        (mid, events), report = self.converted(original, muted=[1], region=(0, 12, 0, 23), tail=0)
        self.assertEqual([(at, m.tempo) for _, at, m in events if m.type == 'set_tempo'], [(0, 335196)])
        self.assertEqual(report['tempo']['source_bpm'], 179)
        snapshot['plan'].pop('tempos')
        with self.assertRaisesRegex(ValueError, 'disagrees with the frozen tempo clock'):
            export.native_to_midi(snapshot)

    def test_authored_velocity_survives_sample_gain_and_resets_expression(self):
        song = self.simple()
        song['samples'][1]['volume'] = 32
        first = song['score']['patterns']['a']['beats'][0]
        first['notes'][0]['velocity'] = 95
        second = copy.deepcopy(first)
        second.update(id='later', at=[1, 1])
        second['notes'][0].update(id='later-note')
        del second['notes'][0]['velocity']
        song['score']['patterns']['a']['beats'].append(second)
        (_, events), _ = self.converted(song)
        self.assertEqual([m.velocity for _, _, m in events if m.type == 'note_on'], [95, 64])
        self.assertEqual([(at, m.value) for _, at, m in events if m.type == 'control_change' and m.control == 11],
                         [(0, 64), (480, 127)])
        second['notes'][0]['velocity'] = 15
        (_, events), _ = self.converted(song, region=(0, 12, 0, 23))
        self.assertEqual([m.velocity for _, _, m in events if m.type == 'note_on'], [15])
        self.assertIn((0, 64), [(at, m.value) for _, at, m in events
                               if m.type == 'control_change' and m.control == 11])

    def test_adaptive_ppq_uses_small_exact_denominator_not_480_multiple(self):
        from fractions import Fraction
        song = self.simple()
        first = song['score']['patterns']['a']['beats'][0]
        first['at'] = [1, 7]
        first['written']['tuplet'] = [11, 1]
        second = copy.deepcopy(first)
        second.update(id='later', at=[1, 1], written={'value': 4, 'tuplet': [13, 1]})
        second['notes'][0]['id'] = 'later_note'
        song['score']['patterns']['a']['beats'].append(second)
        (mid, events), report = self.converted(song)
        self.assertEqual((mid.ticks_per_beat, report['ppq']), (1001, 1001))
        notes = [(Fraction(at, mid.ticks_per_beat), msg.type) for _, at, msg in events
                 if msg.type in ('note_on', 'note_off')]
        self.assertEqual(notes, [(Fraction(1, 7), 'note_on'), (Fraction(18, 77), 'note_off'),
                                 (Fraction(1), 'note_on'), (Fraction(14, 13), 'note_off')])
        for number, denominator in enumerate((5, 9)):
            beat = copy.deepcopy(first)
            beat.update(id=f'other{number}', at=[2 + number, 1],
                        written={'value': 4, 'tuplet': [denominator, 1]})
            beat['notes'][0]['id'] = f'other_note{number}'
            song['score']['patterns']['a']['beats'].append(beat)
        with self.assertRaisesRegex(ValueError, 'PPQ 45045.*32767'):
            self.converted(song)

    def test_absolute_sorting_and_collapsed_identity_guards(self):
        song = self.simple()
        snap = export.snapshot(song, self.dir)
        snap['plan']['events'].reverse()  # Input frame ordering is not the MIDI clock.
        data, _ = export.native_to_midi(snap)
        _, events = self.read(data)
        self.assertEqual([(at, msg.type) for _, at, msg in events if msg.type in ('note_on', 'note_off')],
                         [(0, 'note_on'), (480, 'note_off')])
        snap['plan']['events'][0]['id'] = 'wrong/identity'
        with self.assertRaisesRegex(ValueError, 'identity'):
            export.native_to_midi(snap)
        snap = export.snapshot(song, self.dir)
        snap['plan']['events'][1]['at'] = [0, 1]
        with self.assertRaisesRegex(ValueError, 'matching active identity|collapsed'):
            export.native_to_midi(snap)
        snap['plan']['events'].pop()
        with self.assertRaisesRegex(ValueError, 'no matching explicit note-off'):
            export.native_to_midi(snap)

    def test_performed_technique_gate_comes_from_plan(self):
        from fractions import Fraction
        song = self.simple()
        song['score']['patterns']['a']['beats'][0]['notes'][0]['staccato'] = True
        snap = export.snapshot(song, self.dir)
        release = next(Fraction(*e['at']) for e in snap['plan']['events'] if e['type'] == 'note_off')
        self.assertLess(release, 1)
        data, _ = export.native_to_midi(snap)
        mid, events = self.read(data)
        self.assertEqual([Fraction(at, mid.ticks_per_beat) for _, at, msg in events if msg.type == 'note_off'], [release])

    def test_residual_controls_notes_and_default_volume(self):
        song = self.simple()
        song['samples'][1]['volume'] = 32
        self.raw(song, '00: ... .. v16 X40\n06: ... .. ... M20\n12: C-5 01 ... V40\n18: === .. ... ...')
        (mid, events), report = self.converted(song, tail=0)
        notes = [(at, msg.type, msg.note, msg.velocity) for _, at, msg in events
                 if msg.type in ('note_on', 'note_off')]
        self.assertEqual(notes, [(0, 'note_on', 64, 32), (480, 'note_off', 64, 0),
                                 (480, 'note_on', 60, 64), (720, 'note_off', 60, 0)])
        self.assertIn((240, 7, 64), [(at, msg.control, msg.value) for _, at, msg in events if msg.type == 'control_change'])
        self.assertIn((0, 10, 32), [(at, msg.control, msg.value) for _, at, msg in events if msg.type == 'control_change'])
        self.assertEqual([at for _, at, msg in events if msg.type == 'sysex'], [0, 480])
        self.assertEqual(report['instruments'][0]['program'], None)
        self.assertFalse(any(msg.type == 'program_change' for _, _, msg in events))

    def test_plain_instrument_keymap_and_frozen_global_volume(self):
        song = self.simple()
        song['instruments'] = {1: {'name': 'Mapped', 'keymap': [{'notes': 'C-0..B-8', 'sample': 1, 'transpose': 12}],
                                   'global_volume': 64}}
        (_, events), report = self.converted(song, mix={'sample_volume': {'1': 32}})
        self.assertEqual([(msg.note, msg.velocity) for _, _, msg in events if msg.type == 'note_on'], [(76, 32)])
        self.assertEqual(report['instruments'][0]['name'], 'Mapped')

    def test_muted_global_control_and_raw_boundary_release(self):
        song = self.simple()
        self.raw(song, '00: ... .. ... ... | ... .. ... V40\n12: C-5 01 ... ...\n18: === .. ... V20')
        (_, events), _ = self.converted(song, muted=[1], region=(0, 0, 0, 17))
        # V40 on the muted channel still belongs to the conductor. V20 is outside
        # the exclusive range; the boundary release closes the raw gate only.
        self.assertEqual([msg.data[-2:] for _, _, msg in events if msg.type == 'sysex'], [(127, 127), (0, 64)])
        self.assertIn((720, 'note_off', 60), [(at, msg.type, msg.note) for _, at, msg in events
                                             if msg.type in ('note_on', 'note_off')])
        self.raw(song, '00: ... .. ... ... | C-5 01 ... V40')
        with self.assertRaisesRegex(ValueError, 'global volume on a muted note'):
            self.converted(song, muted=[1])

    def test_residual_and_instrument_refusals_are_located(self):
        for raw, reason in [('12: C-5 01 ... ...', 'no explicit note-off'),
                            ('00: ... .. ... D01', 'Dxx'),
                            ('06: ... .. v20 ...', 'instrument/volume-only'),
                            ('12: C-5 .. ... ...\n18: === .. ... ...', 'inherited instrument'),
                            ('12: C-5 01 ... ...\n18: ^^^ .. ... ...', 'cut/fade'),
                            ('12: C-5 01 ... ...\n18: D-5 01 ... ...', 'overlapping identity')]:
            with self.subTest(raw=raw):
                song = self.simple()
                self.raw(song, raw)
                with self.assertRaisesRegex(ValueError, f'Native MIDI: first row .*{reason}'):
                    self.converted(song)
        song = self.simple()
        song['instruments'] = {1: {'sample': 1, 'nna': 'continue'}}
        with self.assertRaisesRegex(ValueError, 'first/e: NNA'):
            self.converted(song)
        song = self.simple()
        song['score']['patterns']['a']['beats'][0]['notes'][0]['volume'] = 0
        with self.assertRaisesRegex(ValueError, 'velocity zero'):
            self.converted(song)
        song = self.simple()
        song['score']['patterns']['a']['beats'][0]['notes'][0]['instrument'] = 0
        song['score']['patterns']['a']['beats'][0]['at'] = [1, 4]
        # A raw instrument field supplies the planner's inheritance, which remains
        # deliberately unsupported by this MIDI subset.
        self.raw(song, '00: ... 01 ... ...')
        with self.assertRaisesRegex(ValueError, 'inheritance trace|inherited instrument'):
            self.converted(song)

    def test_regions_clip_end_refuse_carry_and_initialize_prefix(self):
        (_, events), report = self.converted(region=(0, 0, 0, 47), tail=0)
        self.assertEqual(report['clipped_releases'], ['first/tie_a'])
        self.assertIn((1920, 'note_off'), [(at, msg.type) for _, at, msg in events if msg.type == 'note_off'])
        with self.assertRaisesRegex(ValueError, 'carries across the range start'):
            self.converted(region=(1, 0, 1, 47))
        song = self.simple()
        self.raw(song, '00: ... .. ... X40\n06: ... .. ... M20\n12: ... .. ... V40')
        song['score']['patterns']['b']['beats'] = [copy.deepcopy(song['score']['patterns']['a']['beats'][0])]
        (_, events), _ = self.converted(song, region=(1, 0, 1, 47))
        controls = [(at, msg.control, msg.value) for _, at, msg in events if msg.type == 'control_change']
        self.assertIn((0, 10, 32), controls)
        self.assertIn((0, 7, 64), controls)
        self.assertEqual([at for _, at, msg in events if msg.type == 'sysex'], [0])

    def test_meter_tempo_and_smf_limits(self):
        song = self.simple()
        song['module']['tempo'] = 137
        song['score']['measures'] = [{'id': 'one', 'from': {'occurrence': 'first', 'at': [0, 1]},
                                      'to': {'occurrence': 'first', 'at': [3, 1]}, 'meter': [3, 4]}]
        (_, events), report = self.converted(song)
        self.assertEqual([(msg.numerator, msg.denominator) for _, _, msg in events if msg.type == 'time_signature'], [(3, 4)])
        self.assertEqual([msg.tempo for _, _, msg in events if msg.type == 'set_tempo'], [437956])
        self.assertEqual(report['tempo']['error_microseconds_per_quarter'], [-28, 137])
        for events, end in [([(0x10000000, 0, b'\x90\x40\x7f')], 0x10000000), ([], 0x10000000)]:
            with self.assertRaisesRegex(ValueError, 'SMF limit'):
                export._midi_track(events, end)

    def test_routing_avoids_drum_channel_and_refuses_aliasing(self):
        song = self.simple()
        song['module']['channels'] = [{'name': f'Part {i}'} for i in range(16)]
        song['score']['tracks'] = {}
        song['score']['patterns']['a']['beats'] = []
        for i in range(16):
            song['score']['tracks'][f't{i}'] = {'tuning': [60], 'channels': [i], 'instrument': 1}
            song['score']['patterns']['a']['beats'].append(
                {'id': f'b{i}', 'track': f't{i}', 'voice': 0, 'at': [0, 1], 'written': {'value': 4},
                 'notes': [{'id': f'n{i}', 'string': 1, 'fret': 0, 'pitch': 60}]})
        with self.assertRaisesRegex(ValueError, 'more than 15'):
            self.converted(song)
        (mid, events), report = self.converted(song, muted=[15])
        channels = {msg.channel for _, _, msg in events if msg.type == 'note_on'}
        self.assertEqual(channels, set(range(16)) - {9})
        self.assertEqual(len(report['channels']), 15)

    def test_prepare_freezes_mix_mutes_bytes_and_conversion(self):
        st = self.state()
        st.set_mix({'volume': {'0': 20}, 'sample_volume': {'1': 32}})
        st.meta['muted'] = [1]
        opts = {'fmt': 'mid', 'mix': 'current', 'mutes': 'respect', 'destination': str(self.dir / 'out')}
        job = export.prepare(st, opts)
        frozen, report = job['midi_data'], copy.deepcopy(job['result']['conversion'])
        _, events = self.read(frozen)
        self.assertEqual({msg.velocity for _, _, msg in events if msg.type == 'note_on'}, {64})
        self.assertEqual({msg.control: msg.value for _, at, msg in events if at == 0 and msg.type == 'control_change'}[7], 40)
        self.assertEqual([c['source_channel'] for c in report['channels']], [0])
        st.set_mix({'volume': {'0': 0}})
        st.meta['muted'] = []
        st.song['module']['title'] = 'changed after prepare'
        (self.dir / 'a.wav').write_bytes(b'changed after prepare')
        with mock.patch.object(export, 'native_to_midi', side_effect=AssertionError('must not recompile')):
            result = export.run(job, gui._encode)
        self.assertEqual(result['status'], 'done', result)
        self.assertEqual(Path(result['song']).read_bytes(), frozen)
        self.assertEqual(result['conversion'], report)
        self.assertFalse(list((self.dir / 'out').glob('.vt-export-*')))

    def test_prepare_refusals_and_atomic_job_guards(self):
        st = self.state(self.simple())
        opts = {'fmt': 'mid', 'destination': str(self.dir / 'out')}
        st.section_edit({'name': 'Start', 'start': 0, 'end': 1})
        for extra, reason in [({'repeat': 1}, 'repeat'), ({'fmt': 'it', 'region': 'Start'}, 'covers the whole song')]:
            with self.subTest(extra=extra), self.assertRaisesRegex(ValueError, reason):
                export.prepare(st, dict(opts, **extra))
        for extra in ({'fmt': 'it'}, {'include_it': True}):   # the standalone IT of the score (api.compile_song)
            with self.subTest(extra=extra):
                self.assertTrue(export.prepare(st, dict(opts, **extra))['native_it'].startswith(b'IMPM'))
        self.assertFalse((self.dir / 'out').exists())
        job = export.prepare(st, opts)
        job['cancel'].set()
        self.assertEqual(export.run(job, gui._encode)['status'], 'cancelled')
        self.assertFalse((self.dir / 'out').exists())
        job = export.prepare(st, opts)
        out = Path(job['result']['song'])
        out.parent.mkdir()
        out.write_bytes(b'external MIDI')
        self.assertEqual(export.run(job, gui._encode)['status'], 'failed')
        self.assertEqual(out.read_bytes(), b'external MIDI')
        job = export.prepare(st, dict(opts, replace=True))
        with mock.patch.object(export.os, 'replace', side_effect=PermissionError('locked')):
            result = export.run(job, gui._encode)
        self.assertEqual(result['status'], 'failed')
        self.assertEqual(out.read_bytes(), b'external MIDI')


class TestAudit090(unittest.TestCase):
    """The 0.9.0 audit's bugs (scratch/audit-100/REPORT.md), each test named by what it pins."""
    setUp = fixtures.TestGui.setUp
    tearDown = fixtures.TestGui.tearDown
    state = fixtures.TestGui.state

    def test_two_commands_on_one_song_one_is_refused_and_nothing_is_lost(self):
        # B1: the command line held no lock; a second command saved over the first and both answered "saved"
        song = self.dir / 'song.yaml'
        real, inner = gui.State.checkpoint, []

        def checkpoint(st, name, action='save'):
            if not inner:
                inner.append(None)
                inner[0] = cli('checkpoint', song, 'save', 'second')
            return real(st, name, action)
        with mock.patch.object(gui.State, 'checkpoint', checkpoint):
            self.assertEqual(cli('checkpoint', song, 'save', 'first')[0], 0)
        code, _, said = inner[0]
        self.assertEqual(code, 1)
        self.assertIn('open in VultureTracker', said)
        self.assertEqual(list(gui.State(song, headless=True).checkpoints), ['first'])

    def test_the_app_opening_a_song_a_command_is_changing_opens_it_read_only(self):
        # B2: the lock was checked once, before the command opened the song; an app opening it meanwhile later wrote
        # its own history over the command's change
        song = self.dir / 'song.yaml'
        real, apps = gui.State.checkpoint, []

        def checkpoint(st, name, action='save'):
            if not apps:
                apps.append(self.state())  # the app opens the song while the command works on it
            return real(st, name, action)
        with mock.patch.object(server, 'LOCK_WAITS', (0.01,)), mock.patch.object(gui.State, 'checkpoint', checkpoint):
            self.assertEqual(cli('checkpoint', song, 'save', 'cli')[0], 0)
        app = apps[0]
        self.assertIn('read-only', app.read_only)
        self.assertIn(app.read_only, app.notices)  # the page shows it once
        with self.assertRaisesRegex(ValueError, 'read-only'):
            app.checkpoint('app')
        with self.assertRaisesRegex(ValueError, 'read-only'):
            app.edit_cells(0, [{'row': 0, 'ch': 0, 'cell': 'D-5 01 ... ...'}])
        self.assertEqual(list(gui.State(song, headless=True).checkpoints), ['cli'])

    def test_a_second_app_on_a_song_another_holds_opens_it_read_only(self):
        # B3: State ignored a lock it could not take: a second app ran unlocked; once the first ended, a command wrote
        # and the second app wrote its own history over it
        from vulturetracker.fileio import lock_file, unlock_file
        song = self.dir / 'song.yaml'
        server.LOCKS.mkdir(parents=True, exist_ok=True)
        other = lock_file(server.app_lock_path(song))  # the first app, in another process
        with mock.patch.object(server, 'LOCK_WAITS', (0.01,)):
            st = self.state()
        self.assertIn('read-only', st.read_only)
        unlock_file(other)  # the first app ends
        self.assertEqual(cli('checkpoint', song, 'save', 'cli')[0], 0)
        with self.assertRaisesRegex(ValueError, 'read-only'):
            st.checkpoint('app')
        self.assertEqual(list(gui.State(song, headless=True).checkpoints), ['cli'])
        # one that lets go while the app waits: the app takes the lock and edits
        other = lock_file(server.app_lock_path(song))
        threading.Timer(0.05, unlock_file, [other]).start()
        with mock.patch.object(server, 'LOCK_WAITS', (0.3, 0.3)):
            st = self.state()
        self.assertIsNone(st.read_only)
        st.checkpoint('app')

    def test_commands_that_read_leave_the_files_of_a_song_open_in_the_app(self):
        # B4: a listing or an export ran History.recover (and moved bad files aside) beside a song the app had open
        song = self.dir / 'song.yaml'
        st = self.state()
        st.history_store.journal.write_bytes(b'{"schema": 2}')  # the journal of a save of the app's, in flight
        st.meta_path.write_bytes(b'{"slot":')
        self.assertEqual(cli('checkpoint', song)[0], 0)
        self.assertEqual(cli('export', song, '-o', self.dir / 'out', '-f', 'it')[0], 0)
        self.assertEqual(st.history_store.journal.read_bytes(), b'{"schema": 2}')
        self.assertEqual(st.meta_path.read_bytes(), b'{"slot":')

    def test_the_command_line_says_what_the_app_would_tell(self):
        # B5: notices were never printed: after an external edit `checkpoint save` dropped every undo step silently
        song = self.dir / 'song.yaml'
        self.assertEqual(cli('sections', song, 'save', 'Intro', '0', '1')[0], 0)
        song.write_bytes(song.read_bytes() + b'# a hand edit\n')
        code, _, said = cli('checkpoint', song, 'save', 'later')
        self.assertEqual(code, 0)
        self.assertIn('External edits since the last session', said)

    def test_game_loop_and_song_lengths_are_the_audio_s_at_any_tempo(self):
        # B6: positions were taken at libopenmpt's default 48 kHz while the audio mixes at 88.2 kHz, each counting a tick
        # in whole samples: at tempo 137 the loop was 114 frames short of the region it plays
        import numpy as np
        from vulturetracker.openmpt import LoadedModule
        from vulturetracker.wavload import read_wav, write_wav
        write_wav(self.dir / 'click.wav', fixtures.RATE, [[30000] + [0] * 400])
        (self.dir / 'song.yaml').write_bytes(CLICK_SONG.encode())
        st = gui.State(self.dir / 'song.yaml', headless=True)
        twice = dict(st.song, orders=['p1', 'p2', 'p1', 'p2'])
        twice.pop('sections')
        with LoadedModule(api.compile_song(twice, self.dir)[0]) as lm:
            x = np.frombuffer(lm.render(measure.RATE), '<i2')[::2].astype(int)
        clicks = np.nonzero(x > x.max() // 2)[0]
        self.assertEqual(len(clicks), 2)
        length = int(clicks[1] - clicks[0])  # what one pass of the section (and of the song) lasts in the audio
        for fmt in ('wav', 'ogg', 'flac'):
            res = export.run(export.prepare(st, {'destination': str(self.dir / 'out'), 'fmt': fmt, 'region': 'Loop',
                                                 'loop': True, 'tail': 0.5, 'replace': True}), gui._encode)
            self.assertEqual(tuple(res['loop']), (0, length), fmt)
            out = Path(res['files'][0])
            if fmt == 'wav':
                self.assertEqual(read_wav(out).loops, [(0, length, False)])
            else:
                self.assertIn(f'LOOPLENGTH={length}'.encode(), out.read_bytes()[:8192])
        self.assertEqual(export.snapshot(st.song, self.dir, tail=0)['frames'], length)  # the whole song, cut at its end

    def test_checkpoints_save_and_restore_a_song_that_is_not_valid_yaml(self):
        # B7: the undo step's asset fingerprints parsed the current text: ParserError (a traceback; a 500 in the app)
        song = self.dir / 'song.yaml'
        good = song.read_bytes()
        self.assertEqual(cli('checkpoint', song, 'save', 'good')[0], 0)
        song.write_bytes(good.replace(b'orders: [p1, p2]', b'orders: [p1, p2'))
        self.assertEqual(cli('checkpoint', song, 'save', 'broken')[0], 0)
        self.assertEqual(cli('checkpoint', song, 'restore', 'good')[0], 0)
        self.assertEqual(song.read_bytes(), good)
        with mock.patch.object(gui.State, 'checkpoint', side_effect=yaml.YAMLError('bad')):
            code, _, said = cli('checkpoint', song, 'diff', 'good')
        self.assertEqual((code, said.strip().splitlines()[-1]), (1, 'error: bad'))

    def test_app_files_beside_the_song_are_no_outputs(self):
        # B8: `phrase render -o song.notes.md --replace` wrote a WAV over the notes report
        song = self.dir / 'song.yaml'
        for name in ('song.notes.md', 'song.notes-abc.json', 'song.notes-abc.md'):
            (self.dir / name).write_bytes(b'kept')
        (self.dir / 'song.phrases').mkdir()
        (self.dir / 'song.phrases' / 'old.json').write_bytes(b'kept')
        st = gui.State(song, headless=True)
        protected = {Path(p).resolve() for p in export.sources(st)}
        for name in ('song.notes.md', 'song.notes-abc.json', 'song.notes-abc.md', 'song.recovery.json', 'song.phrases/old.json'):
            self.assertIn((self.dir / name).resolve(), protected, name)
        self.assertEqual(cli('phrase', song, 'capture', '--order', '0', '--rows', '0-3', '--channels', '1')[0], 0)
        self.assertEqual(cli('phrase', song, 'render', 'A', '-o', self.dir / 'song.notes.md', '--replace')[0], 1)
        self.assertEqual((self.dir / 'song.notes.md').read_bytes(), b'kept')

    def test_api_save_writes_lf_in_one_atomic_write(self):
        # B9: api.save wrote with Path.write_text: CRLF on Windows, and not atomically
        path = self.dir / 'saved.yaml'
        with mock.patch.object(api, 'atomic_write', wraps=api.atomic_write) as write:
            api.save(api.load(self.dir / 'song.yaml'), path)
        write.assert_called_once()
        self.assertNotIn(b'\r\n', path.read_bytes())
        self.assertEqual(api.load(path)['orders'], ['p1', 'p2'])

    def test_phrase_stars_outside_0_to_5_are_refused(self):
        # B10: a phrase alternative's stars were clamped silently (the rating route refuses them since 0.9.0)
        st = self.state()
        phrase_action(st, {'action': 'capture', 'order': 0, 'r0': 0, 'r1': 3, 'chans': [0], 'count': 2})
        for stars in (9, -3):
            with self.assertRaisesRegex(ValueError, '0 to 5'):
                phrase_action(st, {'action': 'update', 'variant': 0, 'stars': stars})
        self.assertEqual(cli('phrase', self.dir / 'song.yaml', 'set', 'A', '--stars', '9')[0], 1)
        phrase_action(st, {'action': 'update', 'variant': 0, 'stars': 5})
        self.assertEqual(st.meta['phrase']['variants'][0]['stars'], 5)

    def test_an_output_that_is_a_folder_or_has_no_folder_is_named_in_the_error(self):
        # B11: the error named the hidden temporary file beside the output
        from vulturetracker.fileio import atomic_write
        (self.dir / 'taken.wav').write_bytes(b'x')
        for out, named, kw in ((self.dir, str(self.dir), {}), (self.dir / 'nowhere' / 'x.wav', 'nowhere', {}),
                               (self.dir / 'taken.wav', 'taken.wav', {'replace': False})):
            with self.assertRaises(OSError) as e:
                atomic_write(out, b'data', **kw)
            self.assertNotIn('.tmp', str(e.exception))
            self.assertIn(named, str(e.exception))
        self.assertEqual((self.dir / 'taken.wav').read_bytes(), b'x')
        self.assertEqual([p.name for p in self.dir.iterdir() if p.name.endswith('.tmp')], [])

    def test_deleting_a_section_leaves_no_blank_line(self):
        # B13: the deleted entry's indentation stayed behind on a line of its own, one more per deletion
        text = SONG_BLOCK + 'sections:\n  Intro: [0, 1]  # the start\n  Main: [1, 2]\n'
        one = arrangement.sections_text(text, {'Intro': [0, 1]})
        self.assertEqual(one, SONG_BLOCK + 'sections:\n  Intro: [0, 1]  # the start\n')
        self.assertEqual(arrangement.sections_text(SONG_BLOCK + 'sections:\n  Intro: [0, 1]\n  Main: [1, 2]\n', {}),
                         SONG_BLOCK + 'sections:\n')
        self.assertIsNone(api.from_yaml(SONG_BLOCK + 'sections:\n').get('sections'))

    def test_a_job_that_raises_fails_alone_and_the_worker_goes_on(self):
        # A5: an exception outside a job's own catch list (a RECIPE entry `chord: []`, IndexError) ended the State's only
        # worker; every later render, build and export stayed queued
        st = self.state()
        rec = {'wav': str(self.dir / 'a.wav'), 'recipe': str(self.dir / 'kit.yaml'), 'name': 'a', 'note': 'A-5'}
        st.recipe_job = {'status': 'queued', 'error': None, 'log': [], 'file': None}
        with mock.patch.object(synth, 'render_one', side_effect=IndexError('list index out of range')):
            st._put(0, ('recipe', (rec, {}, 'chord: []', 1)))
            self.assertTrue(wait_for(lambda: st.recipe_job['status'] == 'failed'))
        self.assertIn('IndexError', st.recipe_job['error'])
        st._put(0, ('build', False))
        self.assertTrue(wait_for(lambda: st.build is not None))
        self.assertEqual(st.build['status'], 'done')

class TestPercussionOrnamentsWorkflow(unittest.TestCase):
    def setUp(self):
        from tests.test_pipeline import sine
        from vulturetracker.wavload import write_wav
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        for name, frequency in (('a', 441), ('b', 882)):
            write_wav(self.dir / (name + '.wav'), 44100, [sine(frequency)])

    def fixture(self, **kwargs):
        from tests.test_tablature import percussion_ornaments_song
        return percussion_ornaments_song(**kwargs)

    def state(self, song):
        path = self.dir / 'ornaments.yaml'
        path.write_bytes(('# Preserve source comments.\n' + api.to_yaml(song)).encode())
        state = gui.State(path, headless=True)
        self.addCleanup(state.close)
        self.assertFalse(state.error, state.error)
        return state

    def test_shared_undo_redo_pattern_identity_and_atomic_invalid_edit(self):
        from vulturetracker.notation import parse_cell
        state = self.state(self.fixture(roll=None, grace=None))
        before = state.song_path.read_bytes()
        history = len(state.history)
        state.score_edit(dict(op='notes_set', pattern='a', revision=state.text_sha(), notes=[
            dict(beat='roll', note=dict(id='roll', tremolo_picking=dict(value=32))),
            dict(beat='flam', note=dict(id='flam', grace=dict(fret=42, value=16, velocity=47, on_beat=True)))]))
        changed = state.song_path.read_bytes()
        self.assertNotEqual(changed, before)
        self.assertEqual(len(state.history), history + 1)
        display = state.pattern_rows(0, 'first')['display_rows']
        self.assertEqual((parse_cell(display[0][0]).note, parse_cell(display[48][0]).note), (38, 38))
        self.assertIsNone(parse_cell(display[54][0]).note)  # Generated main remains a projection, not another saved note.
        self.assertEqual(len([n for b in state.song['score']['patterns']['a']['beats'] for n in b['notes']]), 2)
        self.assertEqual(state.sounding(0, 48)[0]['sample'], 2)
        self.assertEqual(state.sounding(0, 54)[0]['sample'], 1)
        state.undo()
        self.assertEqual(state.song_path.read_bytes(), before)
        state.undo(redo=True)
        self.assertEqual(state.song_path.read_bytes(), changed)
        for patch in (dict(trill=dict(fret=42, value=16)), dict(bend=dict(points=[])),
                      dict(grace=dict(fret=101, value=16, velocity=47))):
            before_bad = state.song_path.read_bytes(), len(state.history), state.text_sha(), copy.deepcopy(state.song)
            with self.assertRaises(ValueError):
                state.score_edit(dict(op='note_set', pattern='a', beat='flam', note=dict(id='flam', **patch),
                                      revision=state.text_sha()))
            self.assertEqual((state.song_path.read_bytes(), len(state.history), state.text_sha(), state.song), before_bad)

    def test_standalone_it_reopens_rolls_grace_and_keymap_without_native_plan(self):
        from tests.test_tablature_sync import it_cells
        from vulturetracker.itreader import read_it
        song = self.fixture(repeat=True)
        before = copy.deepcopy(song)
        data, _, warnings = api.compile_song(song, self.dir)
        reopened, _ = read_it(data)
        self.assertIsNone(reopened.native_score)
        self.assertEqual(reopened.instruments[0].keymap[38], (60, 1))
        self.assertEqual(reopened.instruments[0].keymap[42], (67, 2))
        cells, rows, seconds = it_cells(data)
        attacks = [(r, ch, n, v) for r, ch, n, v, *_ in cells if n is not None and n < 120]
        expected = [(0, 0, 38, 48), (6, 0, 38, 48), (12, 0, 38, 48), (18, 0, 38, 48),
                    (48, 0, 42, 24), (54, 0, 38, 48)]
        self.assertEqual(attacks, expected + [(r + 192, ch, n, v) for r, ch, n, v in expected])
        self.assertEqual(rows, 384)
        self.assertAlmostEqual(seconds, 6.0, delta=.01)
        self.assertTrue(any('IT repetition:' in str(w) for w in warnings))
        self.assertEqual(song, before)

    def test_native_and_standalone_pcm_use_grace_sample_and_mapped_play_note(self):
        from tests.test_pipeline import left, rms, zero_crossing_freq
        from vulturetracker.openmpt import LoadedModule
        song = self.fixture(roll=None)
        prepared = api.prepare_playback(song, self.dir)
        standalone = api.compile_song(song, self.dir)[0]
        results = []
        for data, plan in ((prepared['backing_it'], prepared['plan']), (standalone, None)):
            with LoadedModule(data, 44100, 1, plan=plan) as module:
                results.append(left(module.render(rate=44100, oversample=1, max_seconds=1.3)))
        def window(pcm, start, end):
            return pcm[round(start * 44100):round(end * 44100)]
        for samples in results:
            # Grace starts at .75 s; sample 2 at G5 is 882 * 2^(7/12),
            # distinct from either the principal sample or an unmapped C5.
            self.assertAlmostEqual(zero_crossing_freq(window(samples, .765, .825)), 882 * 2 ** (7 / 12), delta=25)
            self.assertAlmostEqual(zero_crossing_freq(window(samples, .87, .97)), 441, delta=15)
            self.assertGreater(rms(window(samples, .765, .825)), 100)
        for start, end in ((.03, .13), (.765, .825), (.87, .97)):
            self.assertAlmostEqual(rms(window(results[1], start, end)) / rms(window(results[0], start, end)), 1, delta=.04)

    def test_standalone_unsafe_mapping_timing_and_carried_voices_refuse_without_output(self):
        from vulturetracker.song import SongError
        target = self.dir / 'keep.it'
        target.write_bytes(b'owner export')
        variants = []
        unmapped = self.fixture()
        unmapped['instruments'][1]['keymap'].pop()
        variants.append((unmapped, 'no mapped sample'))
        carried = self.fixture()
        carried['instruments'][1]['nna'] = 'continue'
        variants.append((carried, 'cut NNA'))
        variants.append((self.fixture(grace=64), 'IT tick grid'))
        for song, message in variants:
            before = copy.deepcopy(song)
            with self.subTest(message=message), self.assertRaisesRegex(SongError, message):
                api.build(song, target, self.dir)
            self.assertEqual(song, before)
            self.assertEqual(target.read_bytes(), b'owner export')


class TestMixerInterchange(unittest.TestCase):
    setUp = TestNativeMidi.setUp
    tearDown = TestNativeMidi.tearDown
    song = TestNativeMidi.song
    simple = TestNativeMidi.simple
    state = TestNativeMidi.state
    read = TestNativeMidi.read
    raw = TestNativeMidi.raw
    converted = TestNativeMidi.converted

    def test_all_tg_controller_values_roundtrip_and_uniform_native_mix(self):
        for value in range(128):
            with self.subTest(value=value):
                xml = test_gpimport.TestTgInterchange.xml().replace('<volume>127</volume>', f'<volume>{value}</volume>')
                xml = xml.replace('<balance>64</balance>', f'<balance>{127-value}</balance>')
                song, warnings = tgimport.read_tg(test_gpimport.TestTgInterchange.archive(xml))
                before = copy.deepcopy(song)
                data, _ = tgimport.native_to_tg(song, tgimport._raw(song), channels={'t1': dict(program=25, bank=0)})
                channel = tgimport._xml(data).find('TGChannel')
                self.assertEqual((int(channel.findtext('volume')), int(channel.findtext('balance'))), (value,127-value))
                self.assertEqual(song, before)
                restored = tgimport.read_tg(data)[0]
                self.assertEqual(restored['module']['channels'], song['module']['channels'])
                self.assertEqual(restored['score'], song['score'])
                if value != 127:
                    self.assertTrue(any('mixer scale' in w for w in warnings))

    def test_gp_steps_preserve_source_volume_pan_and_refuse_inexact_settings(self):
        for version in (3, 4, 5):
            for step in range(17):
                with self.subTest(version=version, step=step):
                    gp = test_gpimport.harmonic_tab([None], fret=5, tuning=64)
                    gp.tracks[0].channel.volume = step * 8
                    gp.tracks[0].channel.balance = (16-step) * 8
                    gp = gpimport._read_native_gp(test_gpimport.TestFadeInterchange.gp_bytes(version, song=gp))
                    song = gpimport._native_gp_song(gp, 'Mixer')
                    data, _ = gpexport.native_to_gp(song, tgimport._raw(song), channels={'t1': dict(program=25,bank=0)}, version=version)
                    restored = gpimport._native_gp_song(gpimport._read_native_gp(data), 'Mixer')
                    self.assertEqual(restored['score']['tracks']['t1']['midi'], song['score']['tracks']['t1']['midi'])
                    self.assertEqual(restored['module']['channels'], song['module']['channels'])
        for field in ('pan', 'volume'):
            song = gpimport._native_gp_song(gp, 'Mixer')
            for c in song['module']['channels']: c[field] = 31
            with self.assertRaisesRegex(ValueError, 'multiple of four'):
                gpexport.native_to_gp5(song, tgimport._raw(song), channels={'t1': dict(program=25,bank=0)})
            for c in song['module']['channels']: c[field] = 32
            song['score']['tracks']['t1']['midi']['source_'+field] = dict(value=62, **{'mixer_'+field:32})
            with self.assertRaisesRegex(ValueError, 'exact GP mixer step'):
                gpexport.native_to_gp5(song, tgimport._raw(song), channels={'t1': dict(program=25,bank=0)})

    def test_volume_binding_midi_override_raw_prefix_and_audio_neutrality(self):
        song = self.simple()
        for c in song['module']['channels']: c['volume'] = 32
        song['score']['tracks']['guitar']['midi'] = dict(program=25)
        plain = export.snapshot(song, self.dir, tail=0)
        song['score']['tracks']['guitar']['midi']['source_volume'] = dict(value=63, mixer_volume=32)
        snap = export.snapshot(song, self.dir, tail=0)
        self.assertEqual(snap['render_it'], plain['render_it'])
        self.assertEqual(snap['plan'], plain['plan'])
        for mix, expected, reason in ((None,63,'preserved'), ({'pan':{'0':32}},63,'preserved'),
                                      ({'volume':{'0':32}},64,'explicit_mix_override'),
                                      ({'volume':{'5':32}},64,'explicit_mix_override')):
            (_, events), report = self.converted(song, tail=0, mix=mix)
            self.assertEqual([m.value for _,_,m in events if m.type=='control_change' and m.control==7], [expected])
            self.assertEqual(report['source_volume'][0]['reason'], reason)
        song['module']['channels'][5]['volume'] = 31
        (_, events), report = self.converted(song, tail=0)
        self.assertEqual(report['source_volume'][0]['reason'], 'mixer_changed')
        song['module']['channels'][5]['volume'] = 32
        song['score']['patterns']['a']['beats'][0]['at'] = [1,1]
        self.raw(song, '00: ... .. ... M10\n18: ... .. ... M20\n')
        (_, events), _ = self.converted(song, tail=0, region=(0,12,0,35))
        self.assertEqual([(at,m.value) for _,at,m in events if m.type=='control_change' and m.control==7], [(0,32),(240,64)])

    def test_write_mix_history_reopen_and_track_binding_invalidation(self):
        song = self.simple()
        midi = dict(program=25, source_pan=dict(value=63,mixer_pan=32), source_volume=dict(value=126,mixer_volume=64))
        song['score']['tracks']['guitar']['midi'] = midi
        state = self.state(song)
        before = state.song_path.read_bytes()
        state.set_mix({'volume':{'0':64}})
        state.apply_mix()
        self.assertNotIn('source_volume', state.song['score']['tracks']['guitar']['midi'])
        self.assertIn('source_pan', state.song['score']['tracks']['guitar']['midi'])
        changed = state.song_path.read_bytes()
        state.close()
        reopened = gui.State(state.song_path, headless=True)
        self.states.append(reopened)
        reopened.undo()
        self.assertEqual(reopened.song_path.read_bytes(), before)
        reopened.undo(redo=True)
        self.assertEqual(reopened.song_path.read_bytes(), changed)
        template = tablature.score_template(song)
        self.assertEqual(template['tracks']['guitar']['midi'], {'program':25})
        track = copy.deepcopy(song['score']['tracks']['guitar'])
        track['channels'] = list(reversed(track['channels']))
        changed_song = tablature.apply_score_edit(song, dict(op='track_set',track='guitar',value=track))
        self.assertEqual(changed_song['score']['tracks']['guitar']['midi'], {'program':25})

    def test_mixed_strings_and_muting_refuse_without_mutation(self):
        song = self.simple()
        song['module']['channels'][0]['volume'] = 32
        original = copy.deepcopy(song)
        with self.assertRaisesRegex(ValueError,'per-string mixer volume'):
            tgimport.track_midi_mix(song,song['score']['tracks']['guitar'])
        self.assertEqual(song,original)
        song['module']['channels'][0]['volume'] = 64
        song['module']['channels'][0]['muted'] = True
        with self.assertRaisesRegex(ValueError,'per-string mixer mute'):
            tgimport.track_midi_mix(song,song['score']['tracks']['guitar'])


def midi_export_options_song(percussion=False):
    """Two full authored bars repeated once, for MIDI source-oracle/page checks."""
    from tests.test_tablature_sync import score_song
    from tests.test_tablature import beat
    song = score_song()
    song['module'].update(title='MIDI export options', tempo=150)
    song['samples'][1]['file'] = 'a.wav'
    song['patterns']['a']['data'] = ''
    score = song['score']
    score['ties'] = []
    track = score['tracks']['guitar']
    track['midi'] = dict(program=0 if percussion else 24, bank=128 if percussion else 0)
    if percussion:
        track['tuning'] = [0] * len(track['channels'])
    effects = [{}, {'grace': dict(fret=2, value=16, velocity=47, on_beat=True)},
               {'trill': dict(fret=0, value=16)}, {'tremolo_picking': dict(value=16)},
               {'harmonic': dict(type='semi', data=0)},
               {'fade_in': True, 'bend': dict(points=[dict(position=0, value=0), dict(position=12, value=4)])},
               {'trill': dict(fret=2, value=16)}, {'harmonic': dict(type='natural', data=0)}]
    for index, pattern in enumerate(('a', 'b')):
        beats = []
        for i in range(4):
            key = 38 + i if percussion else 64
            note = dict(id=f'n{index}_{i}', string=1, fret=key if percussion else 0, pitch=key, velocity=95)
            if not percussion:
                note.update(effects[4 * index + i])
            beats.append(beat(f'b{index}_{i}', [i, 1], [note]))
        score['patterns'][pattern]['beats'] = beats
    score['measures'] = [dict(id=f'm{i}', meter=[4, 4],
        **{'from': dict(occurrence=oid, at=[0, 1]), 'to': dict(occurrence=oid, at=[4, 1])}, **flow)
        for i, (oid, flow) in enumerate(zip(score['order_ids'], ({'repeat_open': True}, {'repeat_close': 1})))]
    return song


class TestNativeMidiExportOptions(unittest.TestCase):
    setUp = TestNativeMidi.setUp
    tearDown = TestNativeMidi.tearDown
    song = TestNativeMidi.song
    simple = TestNativeMidi.simple
    state = TestNativeMidi.state
    read = TestNativeMidi.read

    def converted(self, song, settings=None):
        from fractions import Fraction
        snap = export.snapshot(song, self.dir, tail=0)
        before = copy.deepcopy(snap)
        data, report = export.native_to_midi(snap, settings)
        self.assertEqual(snap, before)
        mid, events = self.read(data)
        return data, report, [(Fraction(at, mid.ticks_per_beat), msg) for _, at, msg in events]

    def test_defaults_and_frozen_snapshot_are_unchanged(self):
        song = self.simple()
        snap = export.snapshot(song, self.dir, tail=0)
        before = copy.deepcopy(snap)
        plain = export.native_to_midi(snap)
        self.assertEqual(plain, export.native_to_midi(snap, {}))
        self.assertEqual(plain, export.native_to_midi(snap, dict(transpose=0, strip=False)))
        export.native_to_midi(snap, dict(transpose=12, strip=True))
        self.assertEqual(snap, before)
        self.assertEqual(plain[1]['settings'], dict(transpose=0, strip=False))
        self.assertEqual(plain[1]['lead_in_quarters'], [0, 1])

    def test_repeated_workflow_fixture_preserves_source_exceptions(self):
        for percussion in (False, True):
            with self.subTest(percussion=percussion):
                song = midi_export_options_song(percussion)
                snap = export.snapshot(song, self.dir, tail=0)
                before = copy.deepcopy(snap)
                _, plain = export.native_to_midi(snap)
                _, shifted = export.native_to_midi(snap, dict(transpose=12, strip=True))
                self.assertEqual(len(snap['plan']['occurrences']), 4)
                exempt = set(snap['midi_metadata']['transpose_exempt'])
                self.assertEqual(bool(exempt), not percussion)
                for old, new in zip(plain['voices'], shifted['voices']):
                    self.assertEqual(new['pitch'], old['pitch'] + (0 if old['id'] in exempt else 12))
                self.assertEqual(snap, before)

    def test_source_transpose_principal_drums_grace_trill_and_tremolo_in_repeated_occurrences(self):
        for kind in ('ordinary', 'drum', 'grace', 'trill', 'same_key_trill', 'tremolo'):
            with self.subTest(kind=kind):
                song = self.simple()
                song['orders'] = ['a', 'a']
                song['score']['order_ids'] = ['first', 'again']
                track = song['score']['tracks']['guitar']
                track['midi'] = dict(program=0, bank=128 if kind == 'drum' else 0)
                note = song['score']['patterns']['a']['beats'][0]['notes'][0]
                note['velocity'] = 95
                if kind == 'drum':
                    track['tuning'] = [0] * len(track['channels'])
                    note['fret'] = note['pitch']
                if kind == 'grace':
                    note['grace'] = dict(fret=2, value=16, velocity=47, on_beat=True)
                elif 'trill' in kind:
                    note['trill'] = dict(fret=0 if kind == 'same_key_trill' else 2, value=16)
                elif kind == 'tremolo':
                    note['tremolo_picking'] = dict(value=16)
                _, plain, _ = self.converted(song)
                _, shifted, events = self.converted(song, dict(transpose=12))
                self.assertEqual(len(plain['voices']), len(shifted['voices']))
                self.assertGreaterEqual(len(shifted['voices']), 2)
                for before, after in zip(plain['voices'], shifted['voices']):
                    exempt = before.get('role') == 'grace' or 'trill' in kind and before.get('pulse', 0) % 2
                    self.assertEqual(after['pitch'], before['pitch'] + (0 if exempt else 12))
                    self.assertEqual(after['at'], before['at'])
                    self.assertEqual(after['release'], before['release'])
                self.assertEqual([msg.note for _, msg in events if msg.type == 'note_on'],
                                 [v['pitch'] for v in shifted['voices']])

    def test_harmonic_layers_transpose_and_source_lower_octave_boundary(self):
        for kind in ('natural', 'artificial', 'tapped', 'pinch', 'semi'):
            with self.subTest(kind=kind):
                song = self.simple()
                song['score']['patterns']['a']['beats'][0]['notes'][0].update(
                    velocity=95, harmonic=dict(type=kind, data=0))
                _, plain, _ = self.converted(song)
                _, shifted, _ = self.converted(song, dict(transpose=-12))
                self.assertEqual([n['pitch'] for n in shifted['voices']], [n['pitch'] - 12 for n in plain['voices']])
        song = self.simple()
        song['score']['tracks']['guitar']['tuning'][0] = 0
        song['score']['patterns']['a']['beats'][0]['notes'][0].update(
            pitch=0, velocity=95, harmonic=dict(type='natural', data=0))
        _, plain, _ = self.converted(song)
        _, shifted, _ = self.converted(song, dict(transpose=12))
        self.assertEqual([v['pitch'] for v in plain['voices']], [12])
        self.assertEqual([v['pitch'] for v in shifted['voices']], [12, 24])
        self.assertTrue(any('adds the harmonic lower octave' in s for s in shifted['losses']))
        song['score']['tracks']['guitar']['tuning'][0] = 12
        song['score']['patterns']['a']['beats'][0]['notes'][0]['pitch'] = 12
        _, shifted, _ = self.converted(song, dict(transpose=-12))
        self.assertEqual([v['pitch'] for v in shifted['voices']], [12])
        self.assertTrue(any('removes the harmonic lower octave' in s for s in shifted['losses']))

    def test_strip_keeps_pitch_and_shifts_performance_tempo_meter_text(self):
        from fractions import Fraction
        song = self.simple()
        song['module']['tempo'] = 150
        song['score']['tracks']['guitar']['midi'] = dict(bank=1, program=24)
        beat = song['score']['patterns']['a']['beats'][0]
        beat['text'] = 'Begin here'
        beat['notes'][0].update(velocity=95, fade_in=True,
                              bend=dict(points=[dict(position=0, value=0), dict(position=12, value=4)]))
        _, plain, before = self.converted(song)
        _, stripped, after = self.converted(song, dict(strip=True))
        self.assertTrue(any(msg.type == 'control_change' and msg.control == 6 for _, msg in before))
        self.assertTrue(any(msg.type == 'control_change' and msg.control == 11 for _, msg in before))
        self.assertTrue(any(msg.type == 'program_change' for _, msg in before))
        self.assertFalse(any(msg.type in ('control_change', 'program_change', 'sysex') for _, msg in after))
        for kind in ('note_on', 'note_off', 'pitchwheel', 'set_tempo', 'time_signature'):
            first = [(at + 1, msg.copy(time=0)) for at, msg in before if msg.type == kind]
            second = [(at, msg.copy(time=0)) for at, msg in after if msg.type == kind]
            self.assertEqual(first, second, kind)
        self.assertIn((Fraction(1), 'Begin here'), [(at, msg.text) for at, msg in after if msg.type == 'text'])
        self.assertEqual(stripped['duration_seconds'], plain['duration_seconds'] + .5)
        self.assertEqual(stripped['lead_in_quarters'], [1, 1])
        self.assertTrue(any('receiving synth range' in s for s in stripped['losses']))

    def test_invalid_options_and_pitch_refuse_without_publication_or_history_changes(self):
        song = self.simple()
        song['score']['tracks']['guitar']['tuning'][0] = 110
        song['score']['patterns']['a']['beats'][0]['notes'][0]['pitch'] = 110
        state = self.state(song)
        before = copy.deepcopy(state.song)
        files = {p: p.read_bytes() for p in self.dir.rglob('*') if p.is_file()}
        for settings in ([], '', {'unknown': 1}, {'transpose': True}, {'transpose': 25},
                         {'transpose': None}, {'transpose': '12'}, {'strip': 1}, {'strip': None}, {'transpose': 24}):
            with self.subTest(settings=settings), self.assertRaises(ValueError):
                export.prepare(state, dict(fmt='mid', destination='never-created', midi_export=settings))
        self.assertEqual(state.song, before)
        self.assertEqual({p: p.read_bytes() for p in self.dir.rglob('*') if p.is_file()}, files)
        self.assertFalse((self.dir / 'never-created').exists())
        job = export.prepare(state, dict(fmt='mid', destination='never-created', midi_export={'transpose': 17}))
        self.assertEqual([m.note for _, _, m in self.read(job['midi_data'])[1] if m.type == 'note_on'], [127])
        self.assertFalse((self.dir / 'never-created').exists())
        self.assertEqual(state.song, before)
        low = self.simple()
        low['score']['tracks']['guitar']['tuning'][0] = 0
        low['score']['patterns']['a']['beats'][0]['notes'][0]['pitch'] = 0
        snap = export.snapshot(low, self.dir, tail=0)
        original = copy.deepcopy(snap)
        with self.assertRaisesRegex(ValueError, 'outside 0..127'):
            export.native_to_midi(snap, dict(transpose=-1))
        self.assertEqual(snap, original)
        tracker = copy.deepcopy(song)
        tracker.pop('score')
        state = self.state(tracker)
        for settings in ({}, None, {'transpose': 0, 'strip': False}):
            with self.subTest(tracker=settings), self.assertRaisesRegex(ValueError, 'native score'):
                export.prepare(state, dict(fmt='mid', midi_export=settings))
        with self.assertRaisesRegex(ValueError, 'MID export'):
            export.prepare(state, dict(fmt='wav', midi_export={}))
