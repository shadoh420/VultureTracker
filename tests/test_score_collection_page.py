"""Real local collection scan/filter/convert/open controls, reusable for the package."""
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from tests import test_tablature_page as helpers
from tests.test_tablature_sync import complete_song_seed
from vulturetracker import api, score_collection


class TestScoreCollectionPage(unittest.TestCase):
    page = helpers.TestTablaturePage.page
    muted_page = helpers.TestTablaturePage.muted_page

    def scan(self, page, folder):
        page.fill('#collection-folder', str(folder))
        with page.expect_response(lambda response: response.request.method == 'POST' and response.url.endswith('/api/score_collection')) as response:
            page.click('#collection-scan')
        result = response.value.json()
        self.assertIn('files', result, result)
        page.wait_for_function('!document.querySelector("#collection-status").textContent.startsWith("Scanning")')
        return result

    def convert(self, page, destination, fmt):
        page.select_option('#collection-format', fmt)
        page.fill('#collection-destination', str(destination))
        with page.expect_response(lambda response: response.request.method == 'POST' and response.url.endswith('/api/score_collection')) as response:
            page.click('#collection-convert')
        initial = response.value.json()
        self.assertNotIn('error', initial, initial)
        page.wait_for_function('document.querySelector("#collection-status").textContent.startsWith("finished")', timeout=60000)
        self.assertFalse(page.locator('#collection-convert').is_disabled())
        self.assertTrue(page.locator('#collection-cancel').is_disabled())
        return page.evaluate('collectionRequest()')

    def run_collection(self, page, song_path):
        """Uses fresh temporary outputs; restores the open source and leaves it byte-exact."""
        original = song_path.read_bytes()
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.wait_for_function('typeof S!=="undefined"&&S&&S.song')
        saved_folder = page.evaluate("localStorage.getItem('vt-score-folder')")
        with tempfile.TemporaryDirectory(prefix='vt-collection-page-') as directory:
            folder = Path(directory)
            page.evaluate('collectionOpen()')
            page.wait_for_selector('#collection-dialog[open]')
            files = self.scan(page, song_path.parent)
            self.assertTrue(any(Path(item['path']) == song_path.resolve() for item in files['files']))
            page.fill('#collection-filter', song_path.name)
            self.assertEqual(page.locator('#collection-files input[type=checkbox]').count(), 1)
            page.get_by_role('button',name='Select visible',exact=True).click()
            self.assertEqual(page.locator('#collection-count').text_content(), '1 selected')
            page.get_by_role('button',name='Clear selection',exact=True).click()
            self.assertEqual(page.locator('#collection-count').text_content(), '0 selected')
            page.locator('#collection-files input[type=checkbox]').check()
            result = self.convert(page, folder/'tg', 'tg')
            self.assertEqual(result['results'][0]['status'], 'done', result)
            self.assertTrue(page.locator('#collection-tg-options').is_visible())
            tg = Path(result['results'][0]['files'][0])
            summary = page.locator('#collection-results details summary').first
            summary.click()
            self.assertIn(str(tg), page.locator('#collection-results pre').first.text_content())
            self.assertTrue(result['results'][0]['warnings'])
            # Repeating a destination reports the refusal in-place, preserving output.
            tg_bytes = tg.read_bytes()
            refused = self.convert(page, folder/'tg', 'tg')
            self.assertEqual(refused['results'][0]['status'], 'failed')
            self.assertIn('already exists', page.locator('#collection-results pre').text_content())
            self.assertEqual(tg.read_bytes(), tg_bytes)
            page.fill('#collection-filter', '')
            self.scan(page, tg.parent)
            page.locator('#collection-files input[type=checkbox]').check()
            native_result = self.convert(page, folder/'native', 'yaml')
            self.assertEqual(native_result['results'][0]['status'], 'done', native_result)
            native = Path(native_result['results'][0]['files'][0])
            page.locator('#collection-results details summary').click()
            page.get_by_role('button',name='Open converted score',exact=True).click()
            page.wait_for_function('expected=>S.song.path===expected', arg=str(native), timeout=30000)
            self.assertFalse(page.locator('#collection-dialog').evaluate('element=>element.open'))
            page.wait_for_function('S.song.facts.native_score')
            # Open the preserved original through the same collection controls.
            page.evaluate('collectionOpen()')
            self.scan(page, song_path.parent)
            page.fill('#collection-filter', song_path.name)
            page.locator('#collection-files button').click()
            page.wait_for_function('expected=>S.song.path===expected', arg=str(song_path.resolve()), timeout=30000)
            self.assertEqual(song_path.read_bytes(), original)
            self.assertEqual(errors, [])
        page.evaluate("value=>{if(value===null)localStorage.removeItem('vt-score-folder');else localStorage.setItem('vt-score-folder',value)}",saved_folder)

    def test_scan_filter_real_conversions_open_and_no_overwrite(self):
        song = complete_song_seed()
        for sample in song['samples'].values(): sample['file'] = 'a.wav'
        with self.muted_page(api.to_yaml(song)) as (page,state,folder):
            self.assertFalse(state.error, state.error)
            self.run_collection(page, folder/'song.yaml')

    def test_cancel_button_stops_pending_conversion(self):
        song = complete_song_seed()
        for sample in song['samples'].values(): sample['file'] = 'a.wav'
        original_convert = score_collection.convert
        def held_convert(body, notify, cancel):
            # Hold one real conversion at its publication boundary so the UI
            # cancellation path is deterministic even on a fast machine.
            def progress(item):
                notify(item)
                if item['status'] == 'working': cancel.wait(10)
            return original_convert(body,progress,cancel)
        with tempfile.TemporaryDirectory(prefix='vt-collection-cancel-') as output, mock.patch.object(score_collection,'convert',held_convert):
            with self.muted_page(api.to_yaml(song)) as (page,state,folder):
                original = (folder/'song.yaml').read_bytes()
                page.evaluate('collectionOpen()')
                self.scan(page,folder)
                page.fill('#collection-filter','song.yaml')
                page.locator('#collection-files input[type=checkbox]').check()
                page.select_option('#collection-format','tg')
                page.fill('#collection-destination',output)
                page.click('#collection-convert')
                page.wait_for_function('!document.querySelector("#collection-cancel").disabled')
                page.click('#collection-cancel')
                page.wait_for_function('document.querySelector("#collection-status").textContent.startsWith("cancelled")')
                self.assertIn('cancelled',page.locator('#collection-results summary').text_content())
                self.assertEqual(list(Path(output).rglob('*.tg')),[])
                self.assertEqual((folder/'song.yaml').read_bytes(),original)
                page.click('#collection-close')
