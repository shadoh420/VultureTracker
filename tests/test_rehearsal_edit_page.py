"""Real TAB controls for additive/inserting phrase paste and voice transfer."""
import json
import unittest

from tests import test_tablature_page as tab_page
from tests.test_tablature_page import page_fixture
from tests.test_rehearsal_edit import phrase_fixture
from vulturetracker import api


@unittest.skipIf(page_fixture.sync_playwright is None, 'playwright not installed')
class TestRehearsalEditPage(unittest.TestCase):
    page = tab_page.TestTablaturePage.page
    muted_page = tab_page.TestTablaturePage.muted_page
    settled = tab_page.TestTablaturePage.settled
    capture_engraving = tab_page.TestTablaturePage.capture_engraving
    click_tab_lane = tab_page.TestTablaturePage.click_tab_lane
    tab_lane_point = staticmethod(tab_page.TestTablaturePage.tab_lane_point)

    @staticmethod
    def song():
        song, _ = phrase_fixture()
        song['module']['title'] = 'Rehearsal phrase editing'
        song['samples'][1]['file'] = 'a.wav'
        return song

    def rehearsal_phrase_edits(self, page, song_path):
        """Shared source/package check; always returns to the exact original song."""
        original = song_path.read_bytes()
        errors = []
        page.on('pageerror', lambda error: errors.append(error.stack or str(error)))
        page.evaluate("tab('tab');setEdit(true)")
        page.wait_for_selector('[data-ui=track]', state='attached')
        self.capture_engraving(page)
        page.select_option('[data-ui=track]', 'guitar')
        if page.locator('.vt-tab-inspector').get_attribute('open') is None:
            page.locator('.vt-tab-inspector > summary').click()
        revision = page.evaluate('SCORE.view.revision')

        def rendered():
            self.settled(page, 'window.tabRendered&&tabRenderedRevision===SCORE.view.revision&&tabRenderApi.boundsLookup?.isFinished')

        def select(bar, string, at=0):
            page.select_option('[data-ui=voice]', '0')
            rendered()
            self.click_tab_lane(page, bar, 0, string)
            self.settled(page, f'SCORE.view.order==={bar}')
            if at:
                page.fill('[data-ui=at]', str(at)); page.click('[data-action=go]')

        def edit(action, endpoint='score'):
            with page.expect_response('**/api/' + endpoint) as response:
                page.click('[data-action=' + action + ']')
            result = response.value.json()
            self.assertTrue(result.get('ok'), result)
            self.settled(page, 'SCORE.view.revision===' + json.dumps(result['revision']))
            self.assertNotIn('refused', page.inner_text('.vt-tab-status'))
            return result

        def roundtrip(result):
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

        select(0, 1)
        page.click('[data-action=copy]')
        page.wait_for_function("document.querySelector('.vt-tab-status').textContent.startsWith('Copied 1')")
        select(1, 2, 1)
        result = edit('paste-mix')
        song = api.from_yaml(song_path.read_text(encoding='utf-8'))
        active = [b for b in song['score']['patterns']['B']['beats'] if b['voice'] == 0]
        self.assertEqual([len(b['notes']) for b in active], [1, 2, 1])
        self.assertEqual(len(song['score']['ties']), 2)
        self.assertEqual(next(b for b in song['score']['patterns']['B']['beats'] if b['voice'] == 1)['notes'][0]['pitch'], 40)
        self.assertGreater(page.locator('.vt-tab-selection').count(), 0)
        roundtrip(result)
        select(1, 2, 1)
        result = edit('paste-push')
        song = api.from_yaml(song_path.read_text(encoding='utf-8'))
        self.assertEqual(len(song['orders']), 3)
        self.assertEqual(len(song['score']['ties']), 1)
        self.assertEqual(next(b for b in song['score']['patterns']['B']['beats'] if b['voice'] == 1)['at'], [0, 1])
        roundtrip(result)
        for action in ('move-voice', 'copy-voice'):
            select(0, 1)
            self.assertEqual(page.input_value('[data-ui=voice-transfer-mode]'), 'safe')
            result = edit(action, 'score_command')
            self.assertEqual(result['selection']['voice'], 1)
            self.assertEqual(page.input_value('[data-ui=voice]'), '1')
            song = api.from_yaml(song_path.read_text(encoding='utf-8'))
            voices = {b['voice'] for b in song['score']['patterns']['A']['beats']}
            self.assertEqual(voices, {1} if action == 'move-voice' else {0, 1})
            roundtrip(result)
        # The exact same note/string cannot be mixed with itself. Refusal leaves
        # history/source intact, and a subsequent valid edit can still proceed.
        select(0, 1)
        with page.expect_response('**/api/score') as response:
            page.click('[data-action=paste-mix]')
        self.assertFalse(response.value.json().get('ok'))
        self.assertEqual(response.value.status, 400)
        self.assertIn('simultaneous notes share string/channel', response.value.json()['error'])
        expected_refusal = response.value
        self.settled(page, "document.querySelector('.vt-tab-status').textContent.includes('refused')")
        self.assertEqual(song_path.read_bytes(), original)
        self.assertEqual(page.evaluate('SCORE.view.revision'), revision)
        result = edit('move-voice', 'score_command')
        roundtrip(result)
        select(0, 1)
        self.assertFalse(errors, errors)
        rendered()
        return expected_refusal

    def test_mix_push_voice_controls_and_exact_history(self):
        with self.muted_page(api.to_yaml(self.song()), width=1920, height=1080) as (page, state, folder):
            self.assertFalse(state.error, state.error)
            self.rehearsal_phrase_edits(page, folder / 'song.yaml')


if __name__ == '__main__':
    unittest.main()
