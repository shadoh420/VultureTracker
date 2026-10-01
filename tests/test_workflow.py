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

from vulturetracker import api, arrangement, gui, synth
from vulturetracker import history as history_io
from vulturetracker.project import collect
from vulturetracker.phrases import action as phrase_action
from vulturetracker import export
from tests import test_gui as fixtures
from tests.test_gui import SONG_BLOCK


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
        self.assertEqual(frames[0], round(4 * 6 * 2.5 / 125 * gui.RATE))
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
                self.assertEqual(len(export.render(snap)), round(.29*gui.RATE)*4)
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
        self.assertEqual((start, end), (0, round(4 * 6 * 2.5 / 125 * gui.RATE)))
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
        self.assertEqual(whole['snapshot']['loop'], (0, round(8 * 6 * 2.5 / 125 * gui.RATE)))
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
        self.assertEqual(read_wav(self.dir / 'out' / 'song.wav').loops, [(0, round(8 * 6 * 2.5 / 125 * gui.RATE), False)])
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
            old = gui.Handler.state
            try:
                gui.Handler.open_song(song)
                gui.Handler.open_song(song)
                self.assertTrue(gui.open_in_app(song))
            finally:
                gui.Handler.state.close()
                gui.Handler.state = old
        self.assertFalse(gui.open_in_app(song))


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
        with mock.patch.object(gui, 'LOCK_WAITS', (0.01,)), mock.patch.object(gui.State, 'checkpoint', checkpoint):
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
        gui.LOCKS.mkdir(parents=True, exist_ok=True)
        other = lock_file(gui.app_lock_path(song))  # the first app, in another process
        with mock.patch.object(gui, 'LOCK_WAITS', (0.01,)):
            st = self.state()
        self.assertIn('read-only', st.read_only)
        unlock_file(other)  # the first app ends
        self.assertEqual(cli('checkpoint', song, 'save', 'cli')[0], 0)
        with self.assertRaisesRegex(ValueError, 'read-only'):
            st.checkpoint('app')
        self.assertEqual(list(gui.State(song, headless=True).checkpoints), ['cli'])
        # one that lets go while the app waits: the app takes the lock and edits
        other = lock_file(gui.app_lock_path(song))
        threading.Timer(0.05, unlock_file, [other]).start()
        with mock.patch.object(gui, 'LOCK_WAITS', (0.3, 0.3)):
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
            x = np.frombuffer(lm.render(gui.RATE), '<i2')[::2].astype(int)
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
