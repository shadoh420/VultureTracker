"""Local delivery integration: New band score -> existing 32-bar arrangement."""
import json
import unittest
from pathlib import Path

from tests import test_tablature_page as tab_page
from vulturetracker import api, tablature, tgimport


SOURCE = Path(__file__).resolve().parents[1] / 'scratch/tab-test-fixtures/rehearsal-ready/arrangement-source/song.yaml'


@unittest.skipIf(tab_page.page_fixture.sync_playwright is None, 'playwright not installed')
class TestRehearsalArrangementPage(unittest.TestCase):
    page = tab_page.TestTablaturePage.page
    muted_page = tab_page.TestTablaturePage.muted_page
    settled = tab_page.TestTablaturePage.settled
    capture_engraving = tab_page.TestTablaturePage.capture_engraving
    open_panel = staticmethod(tab_page.TestTablaturePage.open_panel)

    def blank_to_arrangement(self, page, source_path, target_path):
        """Use actual New/Copy/Paste controls; leave the new arrangement open."""
        original = source_path.read_bytes()
        source = api.from_yaml(original.decode('utf-8'))
        errors = []
        page.on('pageerror', lambda error: errors.append(error.stack or str(error)))
        page.evaluate("tab('tab');setEdit(true)")
        page.wait_for_selector('[data-ui=track]', state='attached')
        self.capture_engraving(page)
        page.select_option('[data-ui=track]', 'guitar')
        if page.locator('.vt-tab-inspector').get_attribute('open') is None:
            page.locator('.vt-tab-inspector > summary').click()
        self.settled(page, 'SCORE.view.orders.length===32')
        self.open_panel(page, 'measures')
        page.fill('[data-ui=ops-from]', '1'); page.fill('[data-ui=ops-to]', '32')
        page.check('[data-ui=ops-all]'); page.check('[data-ui=ops-headers]'); page.check('[data-ui=ops-markers]')
        with page.expect_response('**/api/measure_copy') as response:
            page.click('[data-action=measure-copy]')
        copied = response.value.json()
        self.assertEqual(len(copied['segment']['units']), 32)
        self.assertEqual(copied['segment']['tracks'], ['guitar', 'guitar2', 'bass', 'drums'])
        page.wait_for_function("document.querySelector('.vt-tab-status').textContent.startsWith('Copied measures')")
        page.click('#songchip')
        page.wait_for_selector('#startmodal.on')
        page.fill('#newpath', str(target_path))
        page.select_option('#newtemplate', 'band')
        page.fill('#newbars', '4')
        with page.expect_response('**/api/new') as response:
            page.locator('#startmodal [onclick="newSong()"]').click()
        self.assertNotIn('error', response.value.json())
        self.settled(page, 'SCORE.view.orders.length===4')
        blank = target_path.read_bytes()
        blank_revision = page.evaluate('SCORE.view.revision')
        blank_song = api.from_yaml(blank.decode('utf-8'))
        self.assertEqual(len(blank_song['score']['tracks']), 4)
        self.assertFalse(any(b['notes'] for p in blank_song['score']['patterns'].values() for b in p['beats']))
        self.open_panel(page, 'measures')
        page.fill('[data-ui=ops-from]', '1'); page.fill('[data-ui=ops-count]', '1')
        page.check('[data-ui=ops-headers]'); page.check('[data-ui=ops-markers]')
        mappings = page.locator('[data-ui=ops-track-map] select')
        self.assertEqual(mappings.count(), 4)
        for track in copied['segment']['tracks']:
            page.select_option('[data-source-track="' + track + '"]', track)
        with page.expect_response('**/api/score_command') as response:
            page.click('[data-action=measure-paste]')
        result = response.value.json()
        self.assertTrue(result.get('ok'), result)
        self.settled(page, 'SCORE.view.orders.length===32&&SCORE.view.revision===' + json.dumps(result['revision']))
        target = api.from_yaml(target_path.read_text(encoding='utf-8'))
        self.assertEqual(len(target['score']['ties']), len(source['score']['ties']))
        self.assertEqual(len(target['score']['tracks']), 4)
        metadata = lambda s: [{k:v for k,v in m.items() if k not in ('id', 'from', 'to')}
                              for m in s['score']['measures']]
        self.assertEqual(metadata(target), metadata(source))
        def gates(song):
            return sorted((e['type'], tuple(e['at']), e['track'], e['voice'], e['pitch'], e.get('velocity'))
                for e in tablature.repeat_projection(song, tgimport._raw(song)).plan['events'])
        self.assertEqual(gates(target), gates(source))
        self.assertEqual(sum(len(b['notes']) for p in target['score']['patterns'].values() for b in p['beats']), 664)
        self.assertFalse(tablature.measure_errors(target, {p:v['rows'] for p,v in target['patterns'].items()}))
        saved = target_path.read_bytes()
        page.click('[data-action=undo]')
        self.settled(page, 'SCORE.view.revision===' + json.dumps(blank_revision))
        self.assertEqual(target_path.read_bytes(), blank)
        page.click('[data-action=redo]')
        self.settled(page, 'SCORE.view.revision===' + json.dumps(result['revision']))
        self.assertEqual(target_path.read_bytes(), saved)
        # Open another document and reopen the saved arrangement, preserving the clipboard source.
        page.evaluate('async path=>{await openSong(path)}', str(source_path))
        page.evaluate('async path=>{await openSong(path)}', str(target_path))
        page.evaluate("tab('tab');setEdit(true)")
        self.settled(page, 'SCORE.view.orders.length===32&&SCORE.view.revision===' + json.dumps(result['revision']))
        self.assertEqual(target_path.read_bytes(), saved)
        self.assertEqual(source_path.read_bytes(), original)
        self.assertFalse(errors, errors)
        return saved

    @unittest.skipUnless(SOURCE.exists(), 'requires the copied existing 32-bar delivery fixture')
    def test_new_band_to_full_existing_arrangement_and_reopen(self):
        original = SOURCE.read_bytes()
        with self.muted_page(original.decode('utf-8'), width=1920, height=1080) as (page, state, folder):
            self.assertFalse(state.error, state.error)
            self.blank_to_arrangement(page, folder / 'song.yaml', folder / 'arranged.yaml')
        self.assertEqual(SOURCE.read_bytes(), original)


if __name__ == '__main__':
    unittest.main()
