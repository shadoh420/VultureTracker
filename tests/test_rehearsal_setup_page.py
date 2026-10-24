"""Band setup controls and local tuning presets, also reusable against the final package."""
import json
import unittest

from vulturetracker import api
from tests import test_tablature_page as helpers
from tests.test_tablature_sync import complete_song_seed


class TestRehearsalSetupPage(unittest.TestCase):
    page = helpers.TestTablaturePage.page
    muted_page = helpers.TestTablaturePage.muted_page
    settled = helpers.TestTablaturePage.settled
    capture_engraving = helpers.TestTablaturePage.capture_engraving
    open_setup = staticmethod(helpers.TestTablaturePage.open_setup)

    def prepare(self, page):
        page.wait_for_function('typeof S!=="undefined"&&S&&S.song')
        page.evaluate("tab('tab');setEdit(true)")
        page.wait_for_selector('[data-ui=track]', state='attached')
        self.capture_engraving(page)
        page.select_option('[data-ui=track]', 'guitar')
        if page.locator('.vt-tab-inspector').get_attribute('open') is None:
            page.locator('.vt-tab-inspector > summary').click()
        self.rendered(page)

    def rendered(self, page):
        self.settled(page, 'window.tabRendered&&tabRenderedRevision===SCORE.view.revision&&tabRenderApi.boundsLookup?.isFinished')

    def command(self, page, selector):
        with page.expect_response('**/api/score_command') as response:
            page.click(selector)
        result = response.value.json()
        self.assertTrue(result.get('ok'), result)
        self.settled(page, 'SCORE.view.revision===' + json.dumps(result['revision']))
        self.rendered(page)
        return result

    def restore(self, page, path, snapshot):
        page.click('[data-action=undo]')
        self.settled(page, 'SCORE.view.revision===' + json.dumps(snapshot[1]))
        self.assertEqual(path.read_bytes(), snapshot[0])
        self.rendered(page)

    def run_setup_edits(self, page, song_path):
        original = song_path.read_bytes()
        errors = []
        page.on('pageerror', lambda error: errors.append(error.stack or str(error)))
        self.prepare(page)
        before = api.from_yaml(original.decode('utf-8'))
        count = len(before['score']['tracks'])
        snapshots = [(original, page.evaluate('SCORE.view.revision'))]
        self.open_setup(page)
        result = self.command(page, '[data-action=clone-track]')
        clone = result['track']
        current = api.from_yaml(song_path.read_text(encoding='utf-8'))
        self.assertEqual(len(current['score']['tracks']), count + 1)
        self.assertEqual(list(current['score']['tracks'])[-1], clone)
        self.assertEqual(current['patterns'], before['patterns'])
        self.assertEqual(len(current['score'].get('ties', [])), 2 * len(before['score'].get('ties', [])))
        snapshots.append((song_path.read_bytes(), page.evaluate('SCORE.view.revision')))
        self.open_setup(page)
        self.command(page, '[data-action=track-up]')
        current = api.from_yaml(song_path.read_text(encoding='utf-8'))
        self.assertEqual(list(current['score']['tracks'])[-2], clone)
        snapshots.append((song_path.read_bytes(), page.evaluate('SCORE.view.revision')))
        self.open_setup(page)
        page.check('[data-ui=remove-notes]')
        self.command(page, '[data-action=delete-track]')
        current = api.from_yaml(song_path.read_text(encoding='utf-8'))
        self.assertNotIn(clone, current['score']['tracks'])
        self.assertEqual(current['patterns'], before['patterns'])
        self.assertEqual(current['score'].get('ties', []), before['score'].get('ties', []))
        for snapshot in reversed(snapshots):
            self.restore(page, song_path, snapshot)

        page.select_option('[data-ui=track]', 'guitar')
        self.open_setup(page)
        page.fill('[data-ui=tuning-name]', 'Session drop D')
        page.fill('[data-ui=tuning]', 'E4 B3 G3 D3 A2 D2')
        page.click('[data-action=save-tuning]')
        self.assertEqual(song_path.read_bytes(), original)
        self.assertEqual(page.evaluate("JSON.parse(localStorage.getItem('vt-score-tunings'))['Session drop D'].tuning"), [64,59,55,50,45,38])
        page.reload()
        self.prepare(page)
        self.open_setup(page)
        page.select_option('[data-ui=custom-tuning]', 'Session drop D')
        self.assertEqual(page.input_value('[data-ui=tuning]'), 'E4 B3 G3 D3 A2 D2')
        self.assertEqual(song_path.read_bytes(), original)
        snapshot = (original, page.evaluate('SCORE.view.revision'))
        self.command(page, '.vt-tab-setup button[type=submit]:visible')
        current = api.from_yaml(song_path.read_text(encoding='utf-8'))
        self.assertEqual(current['score']['tracks']['guitar']['tuning'], [64,59,55,50,45,38])
        pitches = lambda song: [n['pitch'] for p in song['score']['patterns'].values() for b in p['beats'] for n in b['notes']]
        self.assertEqual(pitches(current), pitches(before))
        self.restore(page, song_path, snapshot)
        self.open_setup(page)
        page.select_option('[data-ui=custom-tuning]', 'Session drop D')
        page.click('[data-action=delete-tuning]')
        self.assertNotIn('Session drop D', page.evaluate("JSON.parse(localStorage.getItem('vt-score-tunings'))"))
        self.assertEqual(song_path.read_bytes(), original)
        self.assertEqual(errors, [])

    def test_track_setup_history_and_persisted_tuning(self):
        source = complete_song_seed()
        for sample in source['samples'].values():
            sample['file'] = 'a.wav'
        with self.muted_page(api.to_yaml(source)) as (page, state, folder):
            self.assertFalse(state.error, state.error)
            self.run_setup_edits(page, folder / 'song.yaml')
