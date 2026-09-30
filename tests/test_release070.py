"""0.7.0 regressions: synthetic songs and audio in disposable directories."""
import copy
import json
import os
import struct
import tempfile
from pathlib import Path
import unittest
from unittest import mock

os.environ['VT_WORKERS'] = '1'

import numpy as np
from vulturetracker import api, arrangement, gui, history, itreader, mosaic, phrases
from vulturetracker.itwriter import write_it
from vulturetracker.model import Cell, Channel, Module, Pattern
from tests import test_gui as fixtures
from tests.test_record import fake_recorder


class TestRelease070(unittest.TestCase):
    setUp = fixtures.TestGui.setUp
    tearDown = fixtures.TestGui.tearDown
    state = fixtures.TestGui.state

    def song(self, text):
        (self.dir / 'song.yaml').write_bytes(text.encode())
        return self.state()

    def test_tryout_protects_song_samples_candidates_and_hardlinks(self):
        song = self.dir / 'song.yaml'
        cand = self.dir / 'cand.wav'
        link = self.dir / 'linked.wav'
        os.link(cand, link)
        for out in (song, self.dir / 'a.wav', cand, link):
            before = out.read_bytes()
            with self.subTest(out=out), self.assertRaisesRegex(ValueError, 'source asset'):
                api.tryout(song, 1, [cand], out_wav=out)
            self.assertEqual(out.read_bytes(), before)

    def test_large_song_history_keeps_editing_undo_restart_and_checkpoints(self):
        st = self.song(fixtures.SONG + '# ' + 'x' * 815000 + '\n')
        original = st.text
        st.checkpoint('original')
        for i in range(40):
            st.edit_cells(0, [{'row': 0, 'ch': 0, 'cell': ('D-5' if i % 2 else 'E-5') + ' 01 ... ...'}])
        self.assertEqual(len(st.history), 40)
        self.assertLess(st.history_store.path.stat().st_size, 1024 * 1024)
        latest = st.text
        st.undo()
        self.assertNotEqual(st.text, latest)
        st = self.state()
        st.undo(redo=True)
        self.assertEqual(st.text, latest)
        st.trim_history(3)
        self.assertEqual((len(st.history), len(st.future)), (3, 0))
        st.trim_history()
        self.assertEqual(st.history, [])
        st.checkpoint('original', 'restore')
        self.assertEqual(st.text, original)

    def test_history_budget_and_legacy_load(self):
        st = self.state()
        step = history.unpack_step(st._step())
        legacy = {'schema': 1, 'song': str(st.song_path), 'head': history.digest(st._raw),
                  'undo': [step], 'redo': [], 'checkpoints': {'old': step}}
        st.history_store.path.write_text(json.dumps(legacy), encoding='utf-8')
        st = self.state()
        self.assertEqual(len(st.history), 1)
        self.assertIn('text_z', st.history[0])
        with mock.patch.object(history, 'HISTORY_BYTES', len(st.history_store.data(st._raw, [], [], st.checkpoints)) + 10):
            st.edit_cells(0, [{'row': 0, 'ch': 0, 'cell': 'D-5 01 ... ...'}])
        self.assertEqual(st.history, [])
        self.assertIn('old', st.checkpoints)

    def test_legacy_checkpoints_can_be_deleted_when_over_new_budget(self):
        st = self.state()
        for name in ('one', 'two', 'three'):
            st.checkpoint(name)
        with mock.patch.object(history, 'HISTORY_BYTES', 1):
            st.checkpoint('one', 'delete')
            self.assertEqual(set(st.checkpoints), {'two', 'three'})
            st.checkpoint('two', 'delete')
            st.checkpoint('three', 'delete')
            self.assertEqual(st.checkpoints, {})

    def test_last_section_delete_then_recreate(self):
        for text in ('orders: [p, p, p]\nsections:\n  Intro: [0, 1]\n', 'orders: [p, p, p]\nsections:\n'):
            empty = arrangement.sections_text(text, {})
            updated = arrangement.sections_text(empty, {'Verse': [1, 3]})
            self.assertEqual(api.from_yaml(updated)['sections'], {'Verse': [1, 3]})

    def test_missing_candidate_collect_remedy(self):
        from vulturetracker.project import collect
        st = self.state()
        st.add_candidates('cand.wav')
        (self.dir / 'cand.wav').unlink()
        with tempfile.TemporaryDirectory() as dest:
            with self.assertRaisesRegex(ValueError, 'remove it in TRYOUT'):
                collect(st, Path(dest) / 'collected')
            self.assertFalse((Path(dest) / 'collected').exists())

    def test_remove_channel_keeps_shorthand_empty_row(self):
        text = fixtures.SONG_BLOCK.replace('00: C-5 01 ... ... | ... .. ... ...', 'C-5 01 ... ...', 1)
        st = self.song(text)
        before = [row[1] for row in st.mod.patterns[0].rows]
        st.song_edit([{'op': 'channel_remove', 'ch': 0}])
        self.assertEqual([row[0] for row in st.mod.patterns[0].rows], before)

    def test_multiline_channel_move_refused_without_changing_mix(self):
        st = self.song(fixtures.SONG_BLOCK.replace('- {name: A}', '- name: A\n      pan: 0\n      volume: 10'))
        before = st.song_path.read_bytes()
        with self.assertRaisesRegex(ValueError, 'one-line'):
            st.song_edit([{'op': 'channel_move', 'ch': 0, 'to': 1}])
        self.assertEqual(st.song_path.read_bytes(), before)

    def test_unsigned_it_pcm(self):
        for bits in (8, 16):
            half = 1 << (bits - 1)
            vals = [0, half, half * 2 - 1]
            raw = struct.pack('<3' + ('B' if bits == 8 else 'H'), *vals)
            got = itreader._read_samples_data(raw, 0, 3, 0 if bits == 8 else 2, 0)
            self.assertEqual(got, [[-half, 0, half - 1]])

    def test_signed_unsigned_and_delta_pcm_render_identically_after_import(self):
        from vulturetracker.openmpt import LoadedModule
        original = api.compile_song(self.dir / 'song.yaml')[0]
        nord, nins = struct.unpack_from('<HH', original, 32)
        header = struct.unpack_from('<I', original, 192 + nord + 4*nins)[0]
        start = struct.unpack_from('<I', original, header + 72)[0]
        size = struct.unpack_from('<I', original, header + 48)[0]
        samples = np.frombuffer(original[start:start+size*2], dtype='<i2').astype(np.int32)
        for cvt in (0, 4, 5):
            with self.subTest(cvt=cvt):
                data = bytearray(original)
                data[header+46] = cvt
                converted = samples + 32768 if cvt == 0 else np.diff(samples, prepend=0)
                data[start:start+size*2] = (converted % 65536).astype('<u2').tobytes()
                imported, _ = itreader.read_it(bytes(data))
                with LoadedModule(bytes(data)) as native, LoadedModule(write_it(imported)) as rebuilt:
                    self.assertEqual(native.render(oversample=1), rebuilt.render(oversample=1))

    def test_high_it_order_indexes_survive_import(self):
        mod = Module(channels=[Channel()], patterns=[Pattern(str(i), [[Cell()]]) for i in range(254)], orders=[200, 253])
        got, warnings = itreader.read_it(write_it(mod))
        self.assertEqual(got.orders, [200, 253])
        self.assertFalse(warnings)

    def test_pattern_index_limit_rejected_before_build(self):
        for count in (254, 255, 257):
            doc = api.load(self.dir / 'song.yaml')
            doc['patterns'] = {f'p{i}': {'rows': 1, 'data': ''} for i in range(count)}
            doc['orders'] = [f'p{count - 1}']
            report = api.check(doc, self.dir)
            self.assertEqual(report['ok'], count == 254)
            if count > 254:
                self.assertTrue(any('254 patterns' in e for e in report['errors']))

    def test_slice_unrepresentable_delay_is_refused(self):
        st = self.song(fixtures.SONG_BLOCK.replace('speed: 6', 'speed: 24'))
        lines = st.text.splitlines(keepends=True)
        with self.assertRaisesRegex(ValueError, 'delay above 15'):
            st._slice_pattern(lines, [], [], [0, 17640, 26460], 44100, [1, 1, 1], [60, 60, 60], 0, 0, 'slice')
        self.assertEqual(''.join(lines), st.text)

    def test_echo_remembers_instrument_before_selection(self):
        text = fixtures.SONG_BLOCK.replace('01: ... .. ... ... | ... .. ... ...', '01: D-5 .. ... ... | ... .. ... ...', 1)
        st = self.song(text)
        st.song_edit([{'op': 'echo', 'ch': 0, 'to': None, 'rows': 1, 'pattern': 0, 'r0': 1, 'r1': 1}])
        self.assertEqual(st.mod.patterns[0].rows[2][2].instrument, 1)

    def test_mosaic_preserves_target_tail(self):
        target = np.zeros(44000)
        target[-300:] = .5 * np.sin(np.arange(300) * 2 * np.pi / 20)
        corpus = .5 * np.sin(np.arange(4410) * 2 * np.pi / 20)
        out, report = mosaic.resynth(target, [corpus], 44100)
        self.assertEqual(len(out), len(target))
        self.assertGreater(np.max(np.abs(out[-300:])), .01)

    def test_preroll_after_take_contains_recent_input(self):
        r = fake_recorder()
        try:
            r.open(0, '1', 44100)
            r.stream.feed(.7)
            r.start(.5)
            r.stream.feed(1.3)
            first = r.stop()
            r.start(.5)
            second = r.stop()
            np.testing.assert_array_equal(second, first[:, -22050:])
        finally:
            r.close()

    def test_blank_line_in_sample_mapping_can_be_edited(self):
        text = fixtures.SONG_BLOCK.replace('  1: {file: a.wav, name: A tone}', '  1:\n    file: a.wav\n\n    name: A tone')
        st = self.song(text)
        st.set_mix({'sample_volume': {'1': 32}})
        st.apply_mix()
        self.assertEqual(st.mod.samples[0].global_volume, 32)
        self.assertEqual(st.text.count('name: A tone'), 1)

    def test_implicit_sample_name_references_survive_swap(self):
        doc = api.load(self.dir / 'song.yaml')
        del doc['samples'][1]['name']
        doc['instruments'] = {1: {'sample': 'a'}, 2: {'sample': 2}}
        api.swap_sample(doc, 1, self.dir / 'cand.wav')
        self.assertEqual(doc['samples'][1]['name'], 'a')
        self.assertTrue(api.check(doc, self.dir)['ok'])

    def test_gp_unicode_title_import_compiles(self):
        from tests.test_gpimport import tab, guitarpro
        from vulturetracker.gpimport import import_gp
        if guitarpro is None:
            self.skipTest('PyGuitarPro unavailable')
        path = self.dir / 'in.gp5'
        tab(path)
        gp = guitarpro.parse(path)
        gp.title = 'café'
        guitarpro.write(gp, path)
        dest = self.dir / 'out.yaml'
        _, warnings = import_gp(path, dest, self.dir / 'gp-samples')
        self.assertTrue(api.check(dest)['ok'])
        self.assertTrue(any('Non-ASCII title' in w for w in warnings))

    def test_instrument_only_cell_updates_listening_annotation(self):
        text = fixtures.SONG.replace('01: ... .. ... ... | ... .. ... ...', '01: ... 02 ... ... | ... .. ... ...', 1)
        text = text.replace('02: ... .. ... ... | C-5 02 ... ...', '02: C-5 .. ... ... | ... .. ... ...', 1)
        st = self.song(text)
        table = gui.sounding_table(st.mod, st.facts)
        self.assertEqual(next(x for x in table[0][2] if x['ch'] == 0)['sample'], 2)

    def test_channel_meter_ignores_other_channel_volume_effects(self):
        text = fixtures.SONG.replace('C-5 01 ... ...', '... .. ... ...').replace('C-5 02 ... ...', 'C-5 02 ... M40')
        doc = api.from_yaml(text)
        doc['orders'] = ['p1']
        data = api.compile_song(doc, self.dir)[0]
        self.assertEqual(gui.channel_levels(data, 2)[0]['db'], -120.0)

    def test_peak_negative_full_scale(self):
        for values in ([-32768], [-32768, 0]):
            self.assertEqual(gui._peak(np.array(values, dtype='<i2').tobytes()), 1.0)

    def test_decimal_yaml_leading_zeros_agree(self):
        for value, expected in [('08', 8), ('010', 10), ('+010', 10), ('-010', -10)]:
            self.assertEqual(api.from_yaml('n: ' + value)['n'], expected)
            if expected > 0:
                mod, _ = gui.load_song_text(fixtures.SONG.replace('speed: 6', 'speed: ' + value), self.dir)
                self.assertEqual(mod.speed, expected)
        self.assertEqual(api.from_yaml('n: "08"')['n'], '08')

    def test_phrase_captures_share_identical_samples(self):
        st = self.song(fixtures.SONG_BLOCK)
        body = {'order': 0, 'r0': 0, 'r1': 1, 'chans': [0], 'count': 2}
        a = phrases.capture(st, body)
        first = list(self.dir.rglob('*.phrases/assets/*.wav'))
        b = phrases.capture(st, body)
        self.assertNotEqual(a['id'], b['id'])
        self.assertEqual(a['assets'], b['assets'])
        self.assertEqual(len(list(self.dir.rglob('*.phrases/assets/*.wav'))), len(first))
        phrases.edited_text(st, a, 0)
        phrases.edited_text(st, b, 0)

    def test_beat_spacing_roundtrip_and_bpm(self):
        st = self.song(fixtures.SONG_BLOCK)
        st.song_edit([{'op': 'module', 'key': 'rows_per_beat', 'value': 6},
                      {'op': 'module', 'key': 'rows_per_bar', 'value': 18}])
        self.assertEqual(st.mod.row_highlight, (6, 18))
        self.assertEqual(st.facts['bpm'], 83.33)
        imported, _ = itreader.read_it(st.compiled_it())
        self.assertEqual(imported.row_highlight, (6, 18))
        self.assertEqual(st.snapshot()['structure']['module']['rows_per_bar'], 18)
        st.undo()
        self.assertEqual(st.mod.row_highlight, (4, 16))
        for key in ('rows_per_beat', 'rows_per_bar'):
            doc = api.load(self.dir / 'song.yaml')
            doc['module'][key] = 0
            self.assertFalse(api.check(doc, self.dir)['ok'])

    def test_materialize_quoted_flow_and_direct_patterns(self):
        for spec in ('"C-5 01 ... ...\\n"', '{rows: 4, data: "C-5 01 ... ...\\n"}'):
            with self.subTest(spec=spec):
                text = fixtures.SONG_BLOCK[:fixtures.SONG_BLOCK.index('patterns:')] + 'patterns:\n  p: ' + spec + '\norders: [p]\n# keep me\n'
                st = self.song(text)
                before = st.compiled_it()
                st.materialize_pattern(0)
                self.assertEqual(st.compiled_it(), before)
                self.assertIn('data: |', st.text)
                self.assertIn('# keep me', st.text)
                st.edit_cells(0, [{'row': 0, 'ch': 0, 'cell': 'D-5 01 ... ...'}])
                st.undo()
                st.undo()
                self.assertEqual(st.text, text)
        text = fixtures.SONG_BLOCK[:fixtures.SONG_BLOCK.index('patterns:')] + 'patterns: {p: {rows: 4, data: "C-5 01 ... ..."}}\norders: [p]\n'
        st = self.song(text)
        st.materialize_pattern(0)
        self.assertIn('data: |', st.text)
        st.edit_cells(0, [{'row': 0, 'ch': 0, 'cell': 'E-5 01 ... ...'}])

    def test_backing_route_saves_separate_untrimmed_takes(self):
        st = self.song(fixtures.SONG_BLOCK)
        r = fake_recorder()
        old = gui.Handler.state, gui.Handler.recorder
        gui.Handler.state, gui.Handler.recorder = st, r
        try:
            r.open(0, '1', 44100)
            result = gui.Handler.rec_command({'cmd': 'start', 'backing': True, 'output': 0, 'countin': 0, 'loops': 2})
            self.assertNotIn('error', result)
            size = len(r.backing['pcm'])
            self.assertGreater(float(np.max(np.abs(r.backing['pcm']))), .01)
            r.stream.feed(2 * size / 44100 + .1)
            self.assertTrue(r.status()['finished'])
            result = gui.Handler.rec_command({'cmd': 'stop', 'name': 'along', 'trim': True, 'root': False, 'dest': 'keep'})
            self.assertEqual(len(result['takes']), 2)
            for t in result['takes']:
                self.assertAlmostEqual(t['seconds'], size / 44100, places=3)
        finally:
            r.close()
            gui.Handler.state, gui.Handler.recorder = old


class TestDuplexRecording(unittest.TestCase):
    def test_countin_loop_boundaries_and_compensation_share_one_clock(self):
        r = fake_recorder()
        try:
            r.open(0, '1', 44100)
            pcm = np.stack([np.linspace(-.2, .2, 1000)] * 2, axis=1).astype(np.float32)
            r.start_backing(pcm, 0, countin=1, bpm=600, loops=2, latency_ms=10)
            plan = r.backing
            received, outputs = [], []
            pos = 0
            while pos < plan['end'] + 512:
                x = np.stack([np.arange(pos, pos + 137) / 44100] * 2, axis=1).astype(np.float32)
                out = np.empty((137, 2), np.float32)
                r._duplex(x, out, len(x), None, None)
                received.append(x)
                outputs.append(out)
                pos += 137
            self.assertTrue(r.status()['finished'])
            all_out = np.concatenate(outputs)
            np.testing.assert_array_equal(all_out[:plan['head']], plan['click'])
            np.testing.assert_array_equal(all_out[plan['head']:plan['head'] + 2000], np.tile(pcm, (2, 1)))
            self.assertTrue(np.all(all_out[plan['head'] + 2000:] == 0))
            takes, _ = r.stop_takes()
            self.assertEqual([x.shape for x in takes], [(1, 1000), (1, 1000)])
            source = np.concatenate(received)[:, 0]
            for i, take in enumerate(takes):
                np.testing.assert_array_equal(take[0], source[plan['offset'] + i * 1000:plan['offset'] + (i + 1) * 1000])
        finally:
            r.close()

    def test_loopback_is_configured_before_any_callback(self):
        from vulturetracker.record import FakeBackend, calibration_signal, measure_latency
        r = fake_recorder()
        original = FakeBackend.open_duplex
        def early_callbacks(backend, *args, **kwargs):
            stream = original(backend, *args, **kwargs)
            stream.feed(.5)  # the entire calibration pulse before open_duplex returns
            return stream
        try:
            r.open(0, '1', 44100)
            reference = calibration_signal(r.rate)
            with mock.patch.object(FakeBackend, 'open_duplex', early_callbacks):
                r.start_backing(reference, 0, countin=0, calibration=True)
            r.stream.feed(2.1)
            takes, _ = r.stop_takes()
            self.assertAlmostEqual(measure_latency(reference, takes[0], r.rate), 50, delta=.03)
        finally:
            r.close()

    def test_native_backend_duplex_uses_one_thread_and_rejects_mixed_drivers(self):
        import threading
        from types import SimpleNamespace
        from vulturetracker.record import SoundDeviceBackend, RecordError
        calls, settings = [], []
        def call(name):
            calls.append((name, threading.get_ident()))
        devices = [dict(index=0, name='Input', hostapi=0, max_input_channels=2, max_output_channels=0, default_samplerate=48000),
                   dict(index=1, name='Output', hostapi=0, max_input_channels=0, max_output_channels=2, default_samplerate=48000)]
        class Stream:
            def __init__(self, **kw):
                call('create'); settings.append(kw)
            def start(self): call('start')
            def stop(self): call('stop')
            def close(self): call('close')
        def query(device=None):
            call('devices')
            return devices if device is None else devices[device]
        sd = SimpleNamespace(query_devices=query, query_hostapis=lambda i=None: [{'name':'WASAPI'}] if i is None else {'name':'WASAPI'},
                             WasapiSettings=dict, Stream=Stream)
        with mock.patch('vulturetracker.record.importlib.import_module', return_value=sd):
            be = SoundDeviceBackend()
        try:
            self.assertEqual(be.outputs()[0]['id'], 1)
            stream = be.open_duplex(0, 1, 2, 48000, lambda *args: None)
            stream.stop(); stream.close()
            self.assertEqual(settings[0]['device'], (0, 1))
            self.assertEqual(settings[0]['channels'], (2, 2))
            self.assertEqual(len({tid for _, tid in calls}), 1)
            self.assertNotEqual(calls[0][1], threading.get_ident())
            devices[1]['hostapi'] = 1
            with self.assertRaisesRegex(RecordError, 'same driver'):
                be.open_duplex(0, 1, 2, 48000, None)
        finally:
            be.ex.shutdown()

    def test_latency_calibration_from_delayed_loopback_and_silence_rejection(self):
        from vulturetracker.record import calibration_signal, measure_latency, RecordError
        r = fake_recorder()
        try:
            r.open(0, '1', 44100)
            reference = calibration_signal(r.rate)
            r.start_backing(reference, 0, countin=0, calibration=True)
            r.stream.feed(2.6)
            takes, _ = r.stop_takes()
            self.assertAlmostEqual(measure_latency(reference, takes[0], r.rate), 50, delta=.03)
            with self.assertRaisesRegex(RecordError, 'No clear loopback'):
                measure_latency(reference, np.zeros_like(takes[0]), r.rate)
        finally:
            r.close()


if __name__ == '__main__':
    unittest.main()
