"""Real controls for advanced rhythm; also exercised against the final executable."""
import json
from tests.test_complex_rhythm_page import TestComplexRhythmPage
from tests.test_advanced_rhythm import curve_song
from vulturetracker import api


class TestAdvancedRhythmPage(TestComplexRhythmPage):
    @staticmethod
    def song():
        song = curve_song()
        song['module']['title'] = 'Advanced rhythm editing'
        song['samples'][1]['file'] = 'a.wav'
        song['score']['patterns']['B']['beats'][0]['written']['value'] = 2
        song['score']['patterns']['C']['beats'][0]['notes'][0]['let_ring'] = True
        song['score']['patterns']['D']['beats'][0]['notes'] = []
        return song

    def test_expressive_crossing_commands_exact_history(self):
        with self.muted_page(api.to_yaml(self.song()), width=1920, height=1080) as (page, state, folder):
            self.assertFalse(state.error, state.error)
            print(self.run_advanced(page, folder / 'song.yaml'))

    def run_advanced(self, page, song_path):
        original = song_path.read_bytes()
        errors = []
        page.on('pageerror', lambda e: errors.append(str(e)))
        page.evaluate("tab('tab');setEdit(true)")
        page.wait_for_selector('[data-ui=free-edit]')
        self.capture_engraving(page)
        page.select_option('[data-ui=track]', 'bass')
        page.select_option('[data-ui=track]', 'guitar')
        revision = page.evaluate('SCORE.view.revision')
        def ready():
            self.settled(page, 'window.tabRendered&&tabRenderedRevision===SCORE.view.revision&&tabRenderApi.boundsLookup.isFinished')
        def command(selector, endpoint='score_command'):
            with page.expect_response(lambda r: r.request.method == 'POST' and r.url.endswith('/api/' + endpoint)) as response:
                page.click(selector)
            result = response.value.json()
            self.assertEqual(response.value.status, 200, result)
            self.assertNotIn('error', result)
            self.settled(page, 'SCORE.view.revision===' + json.dumps(result['revision']))
            return result
        def restore(result):
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
            ready()
        if page.locator('.vt-tab-inspector').get_attribute('open') is None:
            page.locator('.vt-tab-inspector > summary').click()
        ready()
        self.click_tab_lane(page, 1, 0, 1)
        page.check('[data-ui=free-edit]')
        page.select_option('[data-ui=duration]', '1')
        page.select_option('[data-ui=dots]', '1')
        result = command('[data-action=duration]')
        changed = api.from_yaml(song_path.read_text(encoding='utf-8'))
        self.assertEqual(changed['patterns']['B']['rows'], 72)
        self.assertTrue(any(e['bar'] == 2 and 'long' in e['errors'] for e in page.evaluate('SCORE.view.measure_errors')))
        restore(result)
        if page.is_enabled('[data-ui=free-edit]'):
            page.uncheck('[data-ui=free-edit]')
        else:
            self.assertTrue(page.is_checked('[data-ui=free-edit]'))  # Invalid bars require Free mode.
        self.click_tab_lane(page, 1, 0, 1)
        page.click('[data-action=copy]')
        page.wait_for_function("document.querySelector('.vt-tab-status').textContent.startsWith('Copied ')")
        self.click_tab_lane(page, 0, 0, 1)
        page.fill('[data-ui=at]', '1'); page.click('[data-action=go]')
        page.click('[data-action=select-none]')
        result = command('[data-action=paste-span]', 'score')
        changed = api.from_yaml(song_path.read_text(encoding='utf-8'))
        curves = [b['notes'][0]['bend'] for b in changed['score']['patterns']['A']['beats'] if b['notes'][0].get('bend')]
        self.assertEqual(len(curves), 2)
        self.assertEqual(sorted(c['points'][0]['value'] for c in curves), [0, 2])
        restore(result)
        self.click_tab_lane(page, 2, 0, 1)
        page.click('[data-action=copy]')
        page.wait_for_function("document.querySelector('.vt-tab-status').textContent.startsWith('Copied ')")
        self.click_tab_lane(page, 3, 0, 1)
        page.fill('[data-ui=at]', '3'); page.click('[data-action=go]')
        page.click('[data-action=select-none]')
        result = command('[data-action=paste-span]', 'score')
        changed = api.from_yaml(song_path.read_text(encoding='utf-8'))
        self.assertEqual(len(changed['orders']), 5)
        self.assertEqual(len(changed['score']['ties']), 1)
        restore(result)
        self.assertFalse(errors, errors)
        return dict(free_duration=True, cropped_curves=True, ring_paste=True,
                    exact_undo_redo=True, source_restored=True, page_errors=errors)
