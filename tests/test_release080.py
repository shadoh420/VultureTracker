"""0.8.0 regressions: synthetic songs in disposable directories."""
import array
import json
import math
import os
import shutil
import struct
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest import mock

os.environ['VT_WORKERS'] = '1'

from vulturetracker import api, arrangement, export, gui, library, synth
from vulturetracker.itreader import import_it
from vulturetracker.itwriter import write_it
from vulturetracker.model import Cell, Channel, Envelope, Instrument, Loop, Module, Pattern, Sample
from vulturetracker.phrases import action as phrase_action
from vulturetracker.project import collect
from vulturetracker.record import FakeBackend, RecordError, calibration_signal
from vulturetracker.wavload import write_wav
from tests import test_gui as fixtures
from tests.test_record import fake_recorder


def float_wav(path, values, rate=44100):
    data = struct.pack(f'<{len(values)}f', *values)
    fmt = struct.pack('<HHIIHH', 3, 1, rate, rate * 4, 4, 32)
    path.write_bytes(b'RIFF' + struct.pack('<I', 20 + len(fmt) + len(data)) + b'WAVEfmt ' + struct.pack('<I', len(fmt))
                     + fmt + b'data' + struct.pack('<I', len(data)) + data)


class TestRelease080(unittest.TestCase):
    setUp = fixtures.TestGui.setUp
    tearDown = fixtures.TestGui.tearDown
    state = fixtures.TestGui.state

    def song(self, text):
        (self.dir / 'song.yaml').write_bytes(text.encode())
        return self.state()

    # ---- file writes

    def test_audition_refuses_an_output_its_own_glob_matched(self):
        before = (self.dir / 'a.wav').read_bytes()
        with self.assertRaisesRegex(ValueError, 'source asset'):
            synth.audition(str(self.dir / '*.wav'), self.dir / 'a.wav', log=lambda *a: None)
        self.assertEqual((self.dir / 'a.wav').read_bytes(), before)

    def test_relative_export_destination_is_beside_the_song(self):
        job = export.prepare(self.state(), {'destination': 'exports', 'fmt': 'it'})
        self.assertEqual(job['folder'], (self.dir / 'exports').resolve())

    def test_relative_collect_destination_and_dotted_zip_name(self):
        proj = self.dir / 'proj'
        proj.mkdir()
        for name in ('song.yaml', 'a.wav', 'b.wav'):
            shutil.copy2(self.dir / name, proj / name)
        st = gui.State(proj / 'song.yaml')
        self.states.append(st)
        result = collect(st, '../copy v1.5', make_zip=True)
        self.assertTrue((self.dir / 'copy v1.5' / 'song.yaml').is_file())
        self.assertEqual(Path(result['zip']), (self.dir / 'copy v1.5.zip').resolve())
        self.assertTrue((self.dir / 'copy v1.5.zip').is_file())

    # ---- crashes and refusals

    def test_zero_padded_keys_and_implicit_names_survive_capture_and_relink(self):
        text = fixtures.SONG.replace('  1: {file: a.wav, name: A tone}\n  2: {file: b.wav, name: B tone}\n',
                                     '  01: {file: a.wav}\n  02: {file: b.wav, name: B tone}\n')
        st = self.song(text.replace('patterns:\n', 'instruments:\n  1: {sample: a}\n  2: {sample: 2}\npatterns:\n'))
        phrase_action(st, {'action': 'capture', 'order': 0, 'r0': 0, 'r1': 1, 'chans': [0]})
        self.assertTrue(Path(phrase_action(st, {'action': 'render', 'variant': 0})['path']).is_file())
        st.relink(1, 'cand.wav')
        self.assertIn('01: {name: "a", file: "cand.wav"}', st.text)
        self.assertEqual(st.song['samples'][1], {'name': 'a', 'file': 'cand.wav'})

    def test_collect_keeps_the_implicit_name_of_a_numbered_duplicate(self):
        for folder, wav in (('x', 'a.wav'), ('y', 'b.wav')):
            (self.dir / folder).mkdir()
            shutil.copy2(self.dir / wav, self.dir / folder / 'kick.wav')
        text = fixtures.SONG.replace('  1: {file: a.wav, name: A tone}\n  2: {file: b.wav, name: B tone}\n',
                                     '  1: {file: x/kick.wav, name: K1}\n  2:\n    file: y/kick.wav\n')
        st = self.song(text.replace('patterns:\n', 'instruments:\n  1: {sample: 1}\n  2: {sample: kick}\npatterns:\n'))
        with tempfile.TemporaryDirectory() as dest:
            collect(st, Path(dest) / 'copy')
            copied = (Path(dest) / 'copy' / 'song.yaml').read_text()
            self.assertIn('    name: "kick"\n    file: "samples/kick-2.wav"\n', copied)
            self.assertTrue(api.check(Path(dest) / 'copy' / 'song.yaml')['ok'])

    def test_last_section_that_loops_back_exports(self):
        text = fixtures.SONG.replace('      03: ... .. ... ... | ... .. ... ...\norders: [p1, p2]\n',
                                     '      03: ... .. ... B00 | ... .. ... ...\norders: [p1, p2]\nsections:\n  Outro: [1, 2]\n')
        st = self.song(text)
        for fmt in ('wav', 'it'):
            job = export.prepare(st, {'region': 'Outro', 'fmt': fmt, 'tail': 0, 'destination': str(self.dir / 'out')})
            self.assertGreater(job['result']['seconds'], 0)

    def test_sections_block_indented_by_four_spaces_takes_new_names(self):
        text = 'orders: [p, p, p]\nsections:\n    Intro: [0, 1]\n'
        out = arrangement.sections_text(text, {'Intro': [0, 1], 'Verse': [1, 3]})
        self.assertEqual(api.from_yaml(out)['sections'], {'Intro': [0, 1], 'Verse': [1, 3]})

    def test_library_scan_survives_a_truncated_chunk_and_never_offers_a_file_that_is_gone(self):
        lib_dir = self.dir / 'lib'
        lib_dir.mkdir()
        for name in ('a.wav', 'b.wav', 'cand.wav'):
            shutil.copy2(self.dir / name, lib_dir / name)
        (lib_dir / 'short.wav').write_bytes((self.dir / 'a.wav').read_bytes() + b'smpl' + struct.pack('<I', 36) + bytes(10))
        lib = library.Library(self.dir / 'index.json')
        self.assertEqual(lib.scan([lib_dir])['files'], 4)
        (lib_dir / 'b.wav').unlink()
        t = os.stat(lib_dir / 'cand.wav').st_mtime_ns + 5 * 10**9
        os.utime(lib_dir / 'cand.wav', ns=(t, t))  # read again: the scan calls back while it runs
        offered = []

        def during(*_):
            offered.extend(lib.map()['paths'])
            offered.extend(p for p, _ in lib.nearest(str(lib_dir / 'a.wav')))
        lib.scan(progress=during)
        self.assertTrue(offered)
        self.assertNotIn('b.wav', [Path(p).name for p in offered])

    def test_check_answers_bad_values_and_files_at_their_lines(self):
        lines = fixtures.SONG.splitlines()
        sample1 = lines.index('  1: {file: a.wav, name: A tone}') + 1
        rows = lines.index('    rows: 4') + 1
        cases = [
            (fixtures.SONG.replace('name: A tone}', 'name: A tone, bits: 12}'), sample1, "'bits' must be one of 8, 16"),
            (fixtures.SONG.replace('name: A tone}', 'name: A tone, loop: {start: 0, end: 9, type: [pingpong]}}'), sample1, 'must be one of'),
            (fixtures.SONG.replace('    rows: 4\n', '    rows: 4  # \x07\n', 1), rows, 'control characters'),
        ]
        song = self.dir / 'song.yaml'
        for text, line, message in cases:
            song.write_bytes(text.encode())
            errors = api.check(song)['errors']
            self.assertIn(f'song.yaml:{line}: error:', errors[0])
            self.assertIn(message, errors[0])
        song.write_bytes(fixtures.SONG.replace('B tone', 'B t\xf6ne').encode('latin-1'))
        self.assertIn(f'song.yaml:{sample1 + 1}: error: not UTF-8', api.check(song)['errors'][0])
        for bad in (float('nan'), float('inf')):
            float_wav(self.dir / 'bad.wav', [0.0, bad, 0.5])
            song.write_bytes(fixtures.SONG.replace('file: a.wav', 'file: bad.wav').encode())
            self.assertIn('bad.wav: the float samples hold NaN or infinite values', api.check(song)['errors'][0])

    def test_names_made_from_non_ascii_files_and_tracks_compile(self):
        shutil.copy2(self.dir / 'a.wav', self.dir / 'Böse Bass.wav')
        song = self.dir / 'song.yaml'
        song.write_bytes(fixtures.SONG.replace('{file: a.wav, name: A tone}', '{file: "Böse Bass.wav"}').encode())
        r = api.check(song)
        self.assertTrue(r['ok'], r['errors'])
        self.assertEqual(r['summary']['sample_names'][0], 'Bose Bass')
        from tests.test_gpimport import tab, guitarpro
        from vulturetracker.gpimport import import_gp
        if guitarpro is None:
            self.skipTest('PyGuitarPro unavailable')
        path = self.dir / 'in.gp5'
        tab(path)
        gp = guitarpro.parse(path)
        gp.tracks[0].name = 'Guitarra acústica'
        guitarpro.write(gp, path)
        import_gp(path, self.dir / 'gp.yaml', self.dir / 'gp-samples')
        self.assertTrue(api.check(self.dir / 'gp.yaml')['ok'])
        path.write_bytes(path.read_bytes()[:200])
        with self.assertRaisesRegex(ValueError, 'not a readable Guitar Pro'):
            import_gp(path, self.dir / 'gp2.yaml', self.dir / 'gp-samples2')

    def test_imports_libopenmpt_plays_compile(self):
        tone = [round(8000 * math.sin(2 * math.pi * i / 100)) for i in range(4410)]
        m = Module(title='x', channels=[Channel()])
        m.samples = [Sample(name='t', data=[tone], c5_speed=44100, loop=Loop(0, 4400))]
        m.instruments = [Instrument(name='i', keymap=[(n, 1) for n in range(120)])]
        m.instruments[0].volume_envelope = Envelope([(0, 64), (5, 100), (12000, 0)])
        m.instruments[0].pitch_envelope = Envelope([(0, 0), (5, 40)])
        m.patterns = [Pattern('a', [[Cell(note=60, instrument=1)]] + [[Cell()] for _ in range(63)])]
        m.orders = [0] * 256
        (self.dir / 'x.it').write_bytes(write_it(m))
        _, warnings = import_it(self.dir / 'x.it', self.dir / 'x.yaml', self.dir / 'x_samples')
        self.assertTrue(api.check(self.dir / 'x.yaml')['ok'], api.check(self.dir / 'x.yaml')['errors'])
        self.assertIn('dropped 1 orders above 255', warnings)

    def test_refused_duplex_leaves_the_input_open(self):
        with mock.patch.dict(os.environ, {'VT_FAKE_AUDIO': '1'}):
            r = fake_recorder()
            r.open(0, '1', 44100)
            try:
                with mock.patch.object(FakeBackend, 'open_duplex', side_effect=RecordError('same driver')):
                    with self.assertRaisesRegex(RecordError, 'same driver'):
                        r.start_backing(calibration_signal(44100), 1, countin=0, calibration=True)
                self.assertTrue(r.status()['open'])
            finally:
                r.close()

    # ---- silent wrong output

    def test_whole_song_export_rings_out_after_an_unchanged_body(self):
        write_wav(self.dir / 'long.wav', fixtures.RATE, [fixtures.sine(440, 3.0)])
        text = fixtures.SONG.replace('{file: b.wav, name: B tone}', '{file: long.wav, name: Long}')
        st = self.song(text.replace('      03: ... .. ... ... | ... .. ... ...\norders', '      03: ... .. ... ... | C-5 02 ... ...\norders'))
        snap = export.snapshot(st.song, self.dir, tail=2)
        new = array.array('h', export.render(snap))
        old = array.array('h', export.render(dict(snap, render_it=snap['it'])))
        body = round(snap['seconds'] * export.RATE) * 2
        self.assertEqual(new[:body - 16], old[:body - 16])  # the old render's last frames stop dead
        self.assertGreater(max(map(abs, new[body + 17640:body + 44100])), 1000)  # 0.2 to 0.5 s after the end

    def test_phrase_renders_differ_by_captured_rows(self):
        st = self.song(fixtures.SONG_BLOCK)
        lengths = []
        for r1 in (3, 1):
            phrase_action(st, {'action': 'capture', 'order': 0, 'r0': 0, 'r1': r1, 'chans': [0]})
            lengths.append(Path(phrase_action(st, {'action': 'render', 'variant': 0})['path']).stat().st_size)
        self.assertGreater(lengths[0], lengths[1])

    def test_echo_carries_the_instrument_into_the_next_pattern(self):
        st = self.song(fixtures.SONG_BLOCK.replace('      00: C-5 02 ... ... | ... .. ... ...', '      00: D-5 .. ... ... | ... .. ... ...', 1))
        st.song_edit([{'op': 'echo', 'ch': 0, 'to': 1, 'rows': 1}])
        self.assertEqual(st.mod.patterns[1].rows[1][1].instrument, 1)  # D-5 plays instrument 01, set in p1

    def test_make_editable_converts_a_flow_pattern_named_by_a_number(self):
        head = fixtures.SONG[:fixtures.SONG.index('patterns:')]
        st = self.song(head + 'patterns: {1: "C-5 01 ... ...\\n", 2: "D-5 01 ... ...\\n"}\norders: [1, 2]\n')
        before = st.mod.patterns[0].rows
        st.materialize_pattern(0)
        self.assertEqual(list(st.song['patterns']), [1, 2])
        self.assertEqual(st.mod.patterns[0].rows, before)
        self.assertIn('data: |', st.text)

    def test_brackets_in_names_keep_notes_archives_and_recipe_inputs(self):
        proj = self.dir / 'proj [2]'
        proj.mkdir()
        for name in ('a.wav', 'b.wav'):
            shutil.copy2(self.dir / name, proj / name)
        shutil.copy2(self.dir / 'b.wav', proj / 'input.wav')
        (proj / 'take [2].yaml').write_bytes(fixtures.SONG.encode())
        (proj / 'sounds.yaml').write_bytes(b'out_dir: .\nsamples:\n  a: {file: input.wav, note: C-5}\n')
        st = gui.State(proj / 'take [2].yaml')
        self.states.append(st)
        st.add_note({'order': 0, 'row': 0, 'text': 'owner words'})
        (proj / 'take [2].notes-abcd1234.md').write_bytes(b'# archived\n')
        self.assertEqual(st.snapshot()['archives'], ['take [2].notes-abcd1234.md'])
        with tempfile.TemporaryDirectory() as dest:
            collect(st, Path(dest) / 'copy')
            names = {p.name for p in (Path(dest) / 'copy').rglob('*')}
            self.assertTrue({'take [2].notes.json', 'sounds.yaml', 'input.wav'} <= names, names)

    def test_a_sample_edit_past_full_scale_is_scaled_under_it_not_clipped(self):
        from vulturetracker.wavload import read_wav
        st = self.state()
        report = st.song_edit([{'op': 'sample_process', 'num': 1, 'action': 'gain', 'params': {'db': 12}}])
        wav = read_wav(self.dir / st.song['samples'][1]['file'])
        self.assertLessEqual(max(map(abs, wav.channels[0])), 32767)
        self.assertGreater(sum(abs(v) >= 32767 for v in wav.channels[0]), 0)  # the peak is at full scale
        self.assertLess(sum(abs(v) >= 32767 for v in wav.channels[0]), 3)     # a peak, not a clipped plateau
        self.assertIn('dB down to stay under full scale', json.dumps(report))

    def test_recipe_globs_inside_a_folder_named_with_brackets(self):
        proj = self.dir / 'kit [2]'
        proj.mkdir()
        shutil.copy2(self.dir / 'a.wav', proj / 'a.wav')
        self.assertEqual([Path(p).name for p in synth._wavs(proj, '*.wav', 'test')], ['a.wav'])

    def test_unexpected_server_error_is_answered(self):
        old = gui.Handler.state
        gui.Handler.state = self.state()
        srv = gui._Server(('127.0.0.1', 0), gui.Handler)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        try:
            req = urllib.request.Request(f'http://127.0.0.1:{srv.server_address[1]}/api/relink', data=b'{}')
            with mock.patch.object(gui.State, 'relink', side_effect=RuntimeError('boom')), \
                    mock.patch('traceback.print_exc'), self.assertRaises(urllib.error.HTTPError) as caught:
                urllib.request.urlopen(req, timeout=5)
            with caught.exception as e:
                self.assertEqual(e.code, 500)
                self.assertEqual(json.loads(e.read())['error'], 'RuntimeError: boom')
        finally:
            srv.shutdown()
            srv.server_close()
            gui.Handler.state = old

    # ---- the audit's suspicions confirmed on 2026-10-01 (scratch/audit-080/agentF)

    def test_sample_edits_follow_a_from_wav_loop_that_runs_past_the_audio(self):
        write_wav(self.dir / 'lp.wav', 44100, [fixtures.sine(440, 0.1)], loop=(1000, 99999, False))
        st = self.song(fixtures.SONG.replace('{file: a.wav, name: A tone}', '{file: lp.wav, loop: from_wav}'))
        self.assertIsNone(st.error)
        for op in ({'action': 'fade_out'}, {'action': 'reverse'}, {'action': 'crossfade', 'frames': 200}):
            st.song_edit([{'op': 'sample_process', 'num': 1, **op}])
            self.assertEqual(st.song['samples'][1]['loop']['end'] - st.song['samples'][1]['loop']['start'],
                             4410 - 1000, op)
            st.undo()
        # a write that fails halfway leaves nothing beside the song
        before = set(self.dir.glob('*.wav'))

        def half(path, *a, **k):
            Path(path).write_bytes(b'RIFF')
            raise OSError('disk full')
        with mock.patch('vulturetracker.wavload.write_wav', half), self.assertRaises(OSError):
            st.song_edit([{'op': 'sample_process', 'num': 1, 'action': 'fade_in'}])
        self.assertEqual(set(self.dir.glob('*.wav')), before)

    def test_an_edit_that_changes_nothing_adds_no_step_and_keeps_redo(self):
        st = self.song(fixtures.SONG_BLOCK)  # channel edits need the block-style module
        st.song_edit([{'op': 'channel_rename', 'ch': 1, 'name': 'Bee'}])
        st.undo()
        before = (self.dir / 'song.yaml').read_bytes()
        st.song_edit([{'op': 'channel_move', 'ch': 0, 'to': -1}])
        st.song_edit([{'op': 'channel_move', 'ch': 1, 'to': 2}])
        self.assertEqual((len(st.history), len(st.future)), (0, 1))
        self.assertEqual((self.dir / 'song.yaml').read_bytes(), before)
        st.undo(redo=True)
        self.assertEqual(st.mod.channels[1].name, 'Bee')

    def test_trim_history_with_an_empty_keep_field_keeps_the_steps(self):
        st = self.song(fixtures.SONG_BLOCK)  # channel edits need the block-style module
        for name in ('Aa', 'Bb'):
            st.song_edit([{'op': 'channel_rename', 'ch': 0, 'name': name}])
        with self.assertRaisesRegex(ValueError, 'how many'):
            st.trim_history('')
        self.assertEqual(len(st.history), 2)
        st.trim_history('1')
        self.assertEqual(len(st.history), 1)

    def test_windows_device_names_are_no_export_or_upload_names(self):
        st = self.state()
        for name in ('CON', 'nul', 'Com1', 'LPT9', 'aux.final'):
            with self.assertRaisesRegex(ValueError, 'device name'):
                export.prepare(st, {'fmt': 'it', 'name': name})
        self.assertEqual(export.prepare(st, {'fmt': 'it', 'name': 'CONTROL'})['todo'][0][0].name, 'CONTROL.it')
        data = (self.dir / 'a.wav').read_bytes()
        self.assertEqual(st.save_upload('CON.wav', data).name, '_CON.wav')
        self.assertEqual(st.save_upload('nul.wav', data).name, '_nul.wav')

    def test_a_rating_takes_stars_0_to_5_and_a_bad_stored_one_keeps_notes_saving(self):
        old = gui.Handler.state
        st = gui.Handler.state = self.state()
        st.meta['slot'] = 1
        st.add_candidates('cand.wav')
        srv = gui._Server(('127.0.0.1', 0), gui.Handler)
        threading.Thread(target=srv.serve_forever, daemon=True).start()

        def post(act, body):
            req = urllib.request.Request(f'http://127.0.0.1:{srv.server_address[1]}/api/{act}', data=json.dumps(body).encode())
            try:
                with urllib.request.urlopen(req, timeout=10) as r:
                    return r.status
            except urllib.error.HTTPError as e:
                with e:
                    return e.code
        try:
            self.assertEqual([post('rate', {'id': 0, 'stars': s}) for s in ('abc', 6, 2.5, True, 4)], [400, 400, 400, 400, 200])
            st.meta['ratings'][st.cands()[0]]['stars'] = 'abc'  # a hand-edited .tryout.json
            self.assertEqual(post('note', {'order': 0, 'row': 1, 'text': 'too loud'}), 200)
            self.assertIn('too loud', st.notes_path.with_suffix('.md').read_text(encoding='utf-8'))
        finally:
            srv.shutdown()
            srv.server_close()
            gui.Handler.state = old

    def test_recipe_numbers_read_as_the_song_reads_them_and_names_as_written(self):
        (self.dir / 'r.yaml').write_text('out_dir: out\nsamples:\n  010: {file: a.wav, note: C-5}\n  08: {file: a.wav, note: C-5}\n'
                                         '  01: {file: a.wav, note: C-5}\n  tone: {file: a.wav, note: C-5, velocity: 0100}\n',
                                         newline='\n')
        self.assertEqual([Path(f).name for f, _, _ in synth.recipe_outputs(self.dir / 'r.yaml')],
                         ['010.wav', '08.wav', '01.wav', 'tone.wav'])
        self.assertEqual(dict(synth.expand(synth._load_recipe(self.dir / 'r.yaml')[0]))['tone']['velocity'], 100)
        self.assertEqual(gui.State._recipe_spec('{file: a.wav, velocity: 0100}')['velocity'], 100)

    def test_a_name_like_08_stays_a_name(self):
        back = api.from_yaml(api.to_yaml({'samples': {1: {'file': 'a.wav', 'name': '08'}}, 'title': '-09'}))
        self.assertEqual((back['samples'][1]['name'], back['title']), ('08', '-09'))
        st = self.song(fixtures.SONG_BLOCK)  # channel edits need the block-style module
        st.song_edit([{'op': 'channel_rename', 'ch': 0, 'name': '08'}])
        self.assertEqual(st.mod.channels[0].name, '08')

    def test_library_reads_the_frames_an_unfinished_wav_holds(self):
        raw = bytearray((self.dir / 'a.wav').read_bytes())
        at = raw.index(b'data')
        struct.pack_into('<I', raw, 4, 0xFFFFFFFF)
        struct.pack_into('<I', raw, at + 4, 0xFFFFFFFF)
        (self.dir / 'open.wav').write_bytes(bytes(raw))
        _, info = library.file_features(self.dir / 'open.wav')
        self.assertAlmostEqual(info['duration'], 0.3, places=2)


if __name__ == '__main__':
    unittest.main()
