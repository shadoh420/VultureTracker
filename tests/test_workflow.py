"""Finishing/sharing workflow regressions, using disposable synthetic songs only."""
import copy
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest import mock

from vulturetracker import api, gui
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
        st = self.state()
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
