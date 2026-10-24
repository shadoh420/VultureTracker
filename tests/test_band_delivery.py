"""Band delivery reuses real exporters and preserves successful files on later failures."""
from pathlib import Path
import threading
import unittest
import os
from unittest.mock import patch

from tests import test_score_collection as collection_helpers
from vulturetracker import export, gui, score_collection


class TestBandDelivery(unittest.TestCase):
    setUp = collection_helpers.TestScoreCollection.setUp
    unchanged = collection_helpers.TestScoreCollection.unchanged

    def test_grouped_part_stems_and_real_audio(self):
        st = gui.State(self.path, headless=True)
        try:
            job = export.prepare(st, dict(fmt='wav', destination=str(self.root/'audio'),
                                         stems=True, stem_mode='tracks', tail=0))
            tracks = st.song['score']['tracks']
            self.assertEqual([group for _, group, _ in job['todo'][1:]],
                             [tuple(t['channels']) for t in tracks.values()])
            result = export.run(job, gui._encode)
            self.assertEqual(result['status'], 'done', result)
            self.assertEqual(len(result['files']), len(tracks)+1)
            for path in result['files']:
                data = Path(path).read_bytes()
                self.assertTrue(data.startswith(b'RIFF'))
                self.assertGreater(len(data), 1000)
            # The same renderer receives all channels of a logical part together.
            group = tuple(tracks['guitar']['channels'])
            expected = export.render(job['snapshot'], [c for c in range(job['snapshot']['channels']) if c not in group])
            from vulturetracker.fileio import wav_bytes
            self.assertEqual(Path(result['files'][1]).read_bytes(), wav_bytes(expected, 44100, None, 16))
        finally:
            st.close()
        self.unchanged()

    def test_band_keeps_audio_and_project_if_pdf_fails(self):
        with patch('vulturetracker.score_pdf.write_pdf', side_effect=ValueError('intentional missing browser')):
            result = score_collection.convert(dict(paths=[str(self.path)], destination=str(self.root/'band'),
                                                    format='band', stems=False, depth=24))[0]
        self.assertEqual(result['status'], 'failed', result)
        self.assertIn('intentional missing browser', result['error'])
        self.assertEqual([d['format'] for d in result['deliveries'] if d['error']], ['pdf'])
        import wave
        with wave.open(next(p for p in result['files'] if p.endswith('.wav')), 'rb') as audio:
            self.assertEqual(audio.getsampwidth(), 3)
        self.assertIn('.wav', [Path(p).suffix for p in result['files']])
        self.assertIn('.yaml', [Path(p).suffix for p in result['files']])
        self.assertIn('.tg', [Path(p).suffix for p in result['files']])
        self.assertIn('.gp5', [Path(p).suffix for p in result['files']])
        from vulturetracker import gpimport
        gp5 = Path(next(p for p in result['files'] if p.endswith('.gp5')))
        restored = gpimport._native_gp_song(gpimport._read_native_gp(gp5.read_bytes()), 'Band delivery')
        self.assertEqual(collection_helpers.written_notes(restored), collection_helpers.written_notes(self.song))
        self.assertTrue(all(Path(p).exists() for p in result['files']))
        self.unchanged()

    def test_cancel_during_delivery_retains_prior_format(self):
        cancel = threading.Event()
        def notify(item):
            if any(Path(p).suffix == '.tg' for p in item['files']):
                cancel.set()
        result = score_collection.convert(dict(paths=[str(self.path)], destination=str(self.root/'cancel'),
                                                format='band'), notify, cancel)[0]
        self.assertEqual(result['status'], 'cancelled', result)
        self.assertTrue(any(Path(p).suffix == '.tg' for p in result['files']))
        self.assertFalse(any(Path(p).suffix == '.wav' for p in result['files']))
        self.unchanged()

    def test_settings_and_new_collection_formats(self):
        for ext in ('ptb', 'tef'):
            (self.source / ('original.'+ext)).write_bytes(b'fixture')
        self.assertEqual({f['format'] for f in score_collection.scan(str(self.source))['files']}, {'ptb','tef','yaml'})
        for values in (dict(scale=0),dict(paper='poster'),dict(notation='bad'),dict(rate=123),dict(depth=8)):
            with self.subTest(values=values), self.assertRaises(ValueError):
                score_collection.options(dict(paths=[str(self.path)], destination=str(self.root/'out'), **values))


@unittest.skipUnless(os.environ.get('VT_CHROMIUM'), 'PDF browser qualification runs with VT_CHROMIUM')
class TestBandPDF(unittest.TestCase):
    setUp = collection_helpers.TestScoreCollection.setUp

    def test_cancel_active_browser_never_publishes(self):
        from vulturetracker.score_pdf import write_pdf
        st = gui.State(self.path, headless=True)
        cancel = threading.Event()
        timer = threading.Timer(.2, cancel.set)
        try:
            view = st.score_view()
            timer.start()
            output = self.root/'cancelled.pdf'
            with self.assertRaisesRegex(ValueError, 'cancelled'):
                write_pdf(view, output, dict(paper='a4', notation='both', scale=65), cancel)
            self.assertFalse(output.exists())
        finally:
            timer.cancel()
            st.close()

    def test_real_score_and_part_pdf(self):
        from vulturetracker.score_pdf import write_pdf
        st = gui.State(self.path, headless=True)
        try:
            settings = dict(paper='a4', notation='both', scale=65)
            for track in (None, 'guitar'):
                output = self.root / (str(track)+'.pdf')
                write_pdf(st.score_view(), output, settings, threading.Event(), track)
                self.assertTrue(output.read_bytes().startswith(b'%PDF-'))
                self.assertGreater(output.stat().st_size, 10000)
                with self.assertRaisesRegex(ValueError, 'already exists'):
                    write_pdf(st.score_view(), output, settings, threading.Event(), track)
        finally:
            st.close()
