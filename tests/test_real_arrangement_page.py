"""Actual independent-edit controls, reusable on the final executable."""
import json
import unittest

from tests import test_tablature_page as tab_page
from tests.test_tablature_page import page_fixture
from tests.test_real_arrangement import divided_song, sound
from vulturetracker import api


@unittest.skipIf(page_fixture.sync_playwright is None, 'playwright not installed')
class TestRealArrangementPage(unittest.TestCase):
    page = tab_page.TestTablaturePage.page
    muted_page = tab_page.TestTablaturePage.muted_page
    settled = tab_page.TestTablaturePage.settled
    capture_engraving = tab_page.TestTablaturePage.capture_engraving
    click_tab_lane = tab_page.TestTablaturePage.click_tab_lane
    tab_lane_point = staticmethod(tab_page.TestTablaturePage.tab_lane_point)

    @staticmethod
    def song():
        song = divided_song()
        song['samples'][1]['file'] = 'a.wav'
        return song

    def run_arrangement(self, page, song_path):
        original = song_path.read_bytes()
        source = api.from_yaml(original.decode('utf-8'))
        errors = []
        page.on('pageerror', lambda e: errors.append(str(e)))
        page.evaluate("tab('tab');setEdit(true)")
        page.wait_for_selector('[data-ui=independent]')
        self.capture_engraving(page)
        revision = page.evaluate('SCORE.view.revision')

        def command(action):
            with page.expect_response('**/api/score_command') as response:
                page.click('[data-action=' + action + ']')
            result = response.value.json()
            self.assertTrue(result.get('ok'), result)
            self.settled(page, 'SCORE.view.revision===' + json.dumps(result['revision']))
            return result

        def undo_redo(result):
            saved = song_path.read_bytes()
            page.click('[data-action=undo]')
            self.settled(page, 'SCORE.view.revision===' + json.dumps(revision))
            self.assertEqual(song_path.read_bytes(), original)
            page.click('[data-action=redo]')
            self.settled(page, 'SCORE.view.revision===' + json.dumps(result['revision']))
            self.assertEqual(song_path.read_bytes(), saved)
            page.click('[data-action=undo]')
            self.settled(page, 'SCORE.view.revision===' + json.dumps(revision))
            self.assertEqual(song_path.read_bytes(), original)

        if page.locator('.vt-tab-inspector').get_attribute('open') is None:
            page.locator('.vt-tab-inspector > summary').click()
        page.click('[data-action=measures]')
        result = command('prepare-measures')
        prepared = api.from_yaml(song_path.read_text(encoding='utf-8'))
        self.assertEqual(len(set(prepared['orders'])), 4)
        self.assertEqual(sound(prepared), sound(source))
        undo_redo(result)
        page.check('[data-ui=independent]')
        page.fill('[data-ui=ops-from]', '2'); page.fill('[data-ui=ops-to]', '2')
        page.check('[data-ui=ops-all]')
        with page.expect_response('**/api/measure_copy') as response:
            page.click('[data-action=measure-copy]')
        copied = response.value.json()
        self.assertEqual(response.value.status, 200, copied)
        self.assertEqual(song_path.read_bytes(), original)
        page.fill('[data-ui=ops-from]', '4'); page.fill('[data-ui=ops-to]', '4')
        result = command('measure-paste')
        pasted = api.from_yaml(song_path.read_text(encoding='utf-8'))
        self.assertEqual(len(set(pasted['orders'])), 4)
        last = pasted['score']['patterns'][pasted['orders'][3]]['beats']
        self.assertEqual([(b['at'], [n['pitch'] for n in b['notes']]) for b in last],
                         [([0, 1], [60]), ([2, 1], [67])])
        undo_redo(result)
        page.click('[data-action=measures]')
        if page.locator('.vt-tab-inspector').get_attribute('open') is None:
            page.locator('.vt-tab-inspector > summary').click()
        self.settled(page, 'window.tabRendered&&tabRenderedRevision===SCORE.view.revision&&tabRenderApi.boundsLookup.isFinished')
        self.click_tab_lane(page, 0, 0, 1)
        result = command('shorter')
        edited = api.from_yaml(song_path.read_text(encoding='utf-8'))
        self.assertNotEqual(edited['orders'][0], edited['orders'][1])
        self.assertEqual(edited['score']['patterns']['A'], source['score']['patterns']['A'])
        undo_redo(result)
        page.uncheck('[data-ui=independent]')
        self.assertFalse(errors, errors)
        return dict(prepared_bars=4, independent_duration=True, divided_bar_copy_paste=True, exact_history=True)

    def test_prepare_and_duration_actual_controls_one_undo(self):
        with self.muted_page(api.to_yaml(self.song()), width=1920, height=1080) as (page, state, folder):
            self.assertFalse(state.error, state.error)
            self.run_arrangement(page, folder / 'song.yaml')


if __name__ == '__main__':
    unittest.main()
