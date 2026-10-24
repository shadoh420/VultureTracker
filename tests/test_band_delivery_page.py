"""Actual collection delivery controls, settings, PDF parts and grouped audio stems."""
from pathlib import Path
import os
import re
import tempfile
import unittest
from unittest import mock

from tests import test_score_collection_page as helpers
from tests.test_tablature_sync import complete_song_seed
from vulturetracker import api
from vulturetracker.wavload import read_wav


class TestBandDeliveryPage(unittest.TestCase):
    page = helpers.TestScoreCollectionPage.page
    muted_page = helpers.TestScoreCollectionPage.muted_page
    scan = helpers.TestScoreCollectionPage.scan
    convert = helpers.TestScoreCollectionPage.convert

    def run_band_delivery(self, page, song_path, destination):
        """Exercise the complete band preset, retaining its real outputs for package inspection."""
        original = song_path.read_bytes()
        page.evaluate('collectionOpen()')
        self.scan(page, song_path.parent)
        page.fill('#collection-filter', song_path.name)
        page.get_by_role('checkbox', name=song_path.name, exact=True).check()
        page.select_option('#collection-format', 'band')
        self.assertIn('GP5', page.locator('#collection-format option:checked').text_content())
        page.select_option('#collection-paper', 'a4')
        page.select_option('#collection-notation', 'both')
        page.fill('#collection-scale', '60')
        page.select_option('#collection-rate', '44100')
        page.select_option('#collection-depth', '16')
        page.locator('#collection-parts').check()
        page.locator('#collection-stems').check()
        result = self.convert(page, destination, 'band')['results'][0]
        self.assertEqual(result['status'], 'done', result)
        self.assertEqual([entry['format'] for entry in result['deliveries']], ['tg', 'gp5', 'mid', 'it', 'wav', 'pdf'])
        self.assertTrue(all(entry['files'] and not entry['error'] for entry in result['deliveries']), result)
        for filename in result['files']:
            self.assertTrue(Path(filename).is_file(), filename)
        self.assertEqual(song_path.read_bytes(), original)
        page.click('#collection-close')
        return result

    def check_pdf(self, path, size=(612, 792)):
        # Chromium writes Page dictionaries directly, not in compressed object
        # streams. Check those bounded metadata objects without a PDF dependency.
        with path.open('rb') as stream:
            data = stream.read(64 * 1024 * 1024 + 1)
        self.assertLessEqual(len(data), 64 * 1024 * 1024)
        self.assertTrue(data.startswith(b'%PDF-') and data.rstrip().endswith(b'%%EOF'), path)
        objects = re.findall(rb'\b\d+\s+\d+\s+obj\b(.*?)\bendobj\b', data, re.S)
        pages = [obj for obj in objects if re.match(rb'\s*<<\s*/Type\s*/Page\b', obj)]
        self.assertGreater(len(pages), 0, path)
        for page in pages:
            box = re.search(rb'/MediaBox\s*\[([\d. -]+)\]', page)
            self.assertIsNotNone(box, path)
            x0, y0, x1, y1 = map(float, box[1].split())
            self.assertAlmostEqual(x1 - x0, size[0], delta=1)
            self.assertAlmostEqual(y1 - y0, size[1], delta=1)
            self.assertRegex(page, rb'/Contents\s+\d+\s+\d+\s+R\b')
            self.assertIn(b'/Font', page)
        return len(pages)

    def run_delivery(self, page, song_path, *, audio=False):
        """Package qualification prints one score; the small source fixture also renders stems/parts."""
        original = song_path.read_bytes()
        source = api.from_yaml(original.decode('utf-8'))
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.wait_for_function('typeof S!=="undefined"&&S&&S.song')
        preferences = page.evaluate("Object.fromEntries(['vt-score-folder','vt-delivery-settings'].map(k=>[k,localStorage.getItem(k)]))")
        result = {}
        try:
            page.evaluate('collectionOpen()')
            page.select_option('#collection-format', 'band')
            for selector in ('#collection-tg-options', '#collection-pdf-options', '#collection-audio-options'):
                self.assertTrue(page.locator(selector).is_visible(), selector)
            page.select_option('#collection-paper', 'letter')
            page.select_option('#collection-notation', 'both')
            page.fill('#collection-scale', '72')
            page.select_option('#collection-rate', '48000')
            page.select_option('#collection-depth', '24')
            page.locator('#collection-parts').set_checked(audio)
            page.locator('#collection-stems').check()
            page.click('#collection-save-settings')
            self.assertIn('remembered', page.locator('#collection-status').text_content())
            page.reload()
            page.wait_for_function('typeof S!=="undefined"&&S&&S.song')
            page.evaluate('collectionOpen()')
            for key, expected in (('format', 'band'), ('paper', 'letter'), ('notation', 'both'),
                                  ('scale', '72'), ('rate', '48000'), ('depth', '24')):
                self.assertEqual(page.input_value('#collection-' + key), expected)
            self.assertEqual(page.is_checked('#collection-parts'), audio)
            self.assertTrue(page.is_checked('#collection-stems'))
            self.scan(page, song_path.parent)
            page.fill('#collection-filter', song_path.name)
            self.assertEqual(page.locator('#collection-files input[type=checkbox]').count(), 1)
            page.locator('#collection-files input[type=checkbox]').check()
            with tempfile.TemporaryDirectory(prefix='vt-band-delivery-page-') as directory:
                folder = Path(directory)
                page.select_option('#collection-format', 'pdf')
                self.assertTrue(page.locator('#collection-pdf-options').is_visible())
                self.assertFalse(page.locator('#collection-audio-options').is_visible())
                pdf_result = self.convert(page, folder / 'pdf', 'pdf')['results'][0]
                self.assertEqual(pdf_result['status'], 'done', pdf_result)
                pdfs = [Path(path) for path in pdf_result['files'] if path.lower().endswith('.pdf')]
                self.assertEqual(len(pdfs), 1 + (len(source['score']['tracks']) if audio else 0))
                pages = 0
                for path in pdfs:
                    pages += self.check_pdf(path)
                result.update(pdf_files=len(pdfs), pdf_pages=pages, saved_settings=True)
                if audio:
                    page.select_option('#collection-format', 'wav')
                    self.assertFalse(page.locator('#collection-pdf-options').is_visible())
                    self.assertTrue(page.locator('#collection-audio-options').is_visible())
                    wav_result = self.convert(page, folder / 'audio', 'wav')['results'][0]
                    self.assertEqual(wav_result['status'], 'done', wav_result)
                    wavs = [Path(path) for path in wav_result['files'] if path.lower().endswith('.wav')]
                    expected_names = ['score.wav'] + [f"{index:02d}-{re.sub(r'[^\w-]+', '_', track.get('name') or identity).strip('_') or 'part'}.wav"
                        for index, (identity, track) in enumerate(source['score']['tracks'].items(), 1)]
                    self.assertEqual(sorted(path.name for path in wavs), sorted(expected_names))
                    lengths = []
                    for path in wavs:
                        wav = read_wav(path)
                        self.assertEqual((wav.rate, wav.bits), (48000, 24))
                        self.assertEqual(len(wav.channels), 2)
                        self.assertTrue(any(value for channel in wav.channels for value in channel), path)
                        lengths.append(len(wav.channels[0]))
                    self.assertEqual(len(set(lengths)), 1, lengths)
                    result.update(wav_files=len(wavs), grouped_stems=len(wavs) - 1, audio_frames=lengths[0])
            self.assertEqual(song_path.read_bytes(), original)
            self.assertEqual(errors, [])
            page.click('#collection-close')
            return result
        finally:
            page.evaluate("values=>{for(const[k,v]of Object.entries(values)){if(v===null)localStorage.removeItem(k);else localStorage.setItem(k,v)}}", preferences)

    def test_collection_pdf_audio_stems_and_saved_settings(self):
        from tests import test_page as browser_fixture
        if browser_fixture.sync_playwright is None:
            self.skipTest('playwright not installed')
        executable = os.environ.get('VT_CHROMIUM')
        if not executable:
            with browser_fixture.sync_playwright() as playwright:
                executable = playwright.chromium.executable_path
            if not Path(executable).is_file():
                self.skipTest('Playwright Chromium is not installed')
        source = complete_song_seed()
        for sample in source['samples'].values():
            sample['file'] = 'a.wav'
        with mock.patch.dict(os.environ, VT_CHROMIUM=executable, VT_HEADED='0'), \
                self.muted_page(api.to_yaml(source), width=1600, height=1000) as (page, state, folder):
            self.assertFalse(state.error, state.error)
            result = self.run_delivery(page, folder / 'song.yaml', audio=True)
            self.assertEqual(result['grouped_stems'], 4)
            self.assertEqual(result['pdf_files'], 5)

    def test_complete_band_preset_includes_gp5(self):
        source = complete_song_seed()
        for sample in source['samples'].values():
            sample['file'] = 'a.wav'
        with tempfile.TemporaryDirectory(prefix='vt-band-preset-') as destination, \
                self.muted_page(api.to_yaml(source), width=1600, height=1000) as (page, state, folder):
            self.assertFalse(state.error, state.error)
            result = self.run_band_delivery(page, folder/'song.yaml', Path(destination)/'delivery')
            gp5 = next(Path(path) for path in result['files'] if path.endswith('.gp5'))
            from vulturetracker import gpimport
            from tests.test_score_collection import written_notes
            restored = gpimport._native_gp_song(gpimport._read_native_gp(gp5.read_bytes()), 'Band preset')
            self.assertEqual(written_notes(restored), written_notes(source))


if __name__ == '__main__':
    unittest.main()
