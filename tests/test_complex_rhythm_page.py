"""Actual expressive rebar, Move and Paste controls; reusable on the final package."""
import json
import unittest

from tests import test_real_arrangement_page as arrangement_helpers
from tests.test_complex_rhythm import expressive_song, performance
from tests import test_tablature as fixtures
from tests.test_tablature_page import page_fixture
from vulturetracker import api


@unittest.skipIf(page_fixture.sync_playwright is None, 'playwright not installed')
class TestComplexRhythmPage(unittest.TestCase):
    page = arrangement_helpers.TestRealArrangementPage.page
    muted_page = arrangement_helpers.TestRealArrangementPage.muted_page
    settled = arrangement_helpers.TestRealArrangementPage.settled
    capture_engraving = arrangement_helpers.TestRealArrangementPage.capture_engraving
    click_tab_lane = arrangement_helpers.TestRealArrangementPage.click_tab_lane
    tab_lane_point = staticmethod(arrangement_helpers.TestRealArrangementPage.tab_lane_point)

    @staticmethod
    def song():
        song = expressive_song()
        song['module']['title'] = 'Complex rhythm editing'
        song['samples'][1]['file'] = 'a.wav'
        return song

    def run_rhythm(self, page, song_path):
        original = song_path.read_bytes()
        source = api.from_yaml(original.decode('utf-8'))
        errors = []
        page.on('pageerror', lambda e: errors.append(str(e)))
        page.evaluate("tab('tab');setEdit(true)")
        page.wait_for_selector('[data-ui=independent]')
        self.capture_engraving(page)
        page.select_option('[data-ui=track]', 'bass')
        page.select_option('[data-ui=track]', 'guitar')
        revision = page.evaluate('SCORE.view.revision')

        def ready():
            self.settled(page, 'window.tabRendered&&tabRenderedRevision===SCORE.view.revision&&tabRenderApi.boundsLookup?.isFinished')

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
        self.click_tab_lane(page, 0, 0, 1)
        page.click('[data-action=measures]')
        page.select_option('[data-ui=measure]', 'A')
        page.fill('[data-ui=meter-n]', '3')
        page.check('[data-ui=meter-to-end]')
        result = command('.vt-tab-measures button[type=submit]')
        self.assertEqual(performance(api.from_yaml(song_path.read_text(encoding='utf-8'))), performance(source))
        page.click('[data-action=close-measures]')
        restore(result)
        self.click_tab_lane(page, 0, 0, 1)
        page.fill('[data-ui=move-amount]', '1')
        result = command('[data-action=move-beats-right]')
        self.assertEqual(performance(api.from_yaml(song_path.read_text(encoding='utf-8'))), performance(source, shift=22050))
        restore(result)
        self.click_tab_lane(page, 0, 0, 1)
        page.click('[data-action=copy]')
        page.wait_for_function("document.querySelector('.vt-tab-status').textContent.startsWith('Copied ')")
        self.click_tab_lane(page, 2, 0, 1)
        page.fill('[data-ui=at]', '3')
        # The host can finish refreshing the selected order while its position
        # field is being edited. That refresh must not discard the pending value.
        page.evaluate('SCORE.key=null;scoreRefresh()')
        self.assertEqual(page.input_value('[data-ui=at]'), '3')
        page.click('[data-action=go]')
        page.click('[data-action=select-none]')
        result = command('[data-action=paste-span]', 'score')
        pasted = api.from_yaml(song_path.read_text(encoding='utf-8'))
        self.assertEqual(performance(pasted, after='oc/copy_'), performance(source, after='oa/', shift=11 * 22050))
        restore(result)
        self.assertFalse(errors, errors)
        return dict(expressive_rebar=True, expressive_move=True, expressive_paste=True,
                    exact_undo_redo=True, same_performed_events=True, page_errors=errors)

    def test_expressive_crossing_commands_exact_history(self):
        with self.muted_page(api.to_yaml(self.song()), width=1920, height=1080) as (page, state, folder):
            self.assertFalse(state.error, state.error)
            print(self.run_rhythm(page, folder / 'song.yaml'))


class TestExpressiveArrangementPage(TestComplexRhythmPage):
    @staticmethod
    def song():
        song = expressive_song()
        song['module']['title'] = 'Expressive arrangement'
        song['samples'][1]['file'] = 'a.wav'
        fit, _ = fixtures.TestPlaceFitCommand().fixture()
        song['score']['patterns']['A']['beats'] = fit['score']['patterns']['A']['beats']
        song['score']['patterns']['A']['beats'][0]['notes'][0].update(slide=True, velocity=79)
        song['score']['patterns']['A']['beats'][1]['notes'][0].update(vibrato=True, velocity=63)
        song['score']['patterns']['C']['beats'][0]['notes'][0]['vibrato'] = True
        head = song['score']['patterns']['D']['beats'][0]
        head['stroke'] = dict(direction='down', value=4)
        head['notes'].append(dict(fixtures.note('chord', 59, 2, 0), velocity=90))
        return song

    def test_expressive_crossing_commands_exact_history(self):
        # The inherited fixture is replaced by the broader end-to-end edit path.
        with self.muted_page(api.to_yaml(self.song()), width=1920, height=1080) as (page, state, folder):
            self.assertFalse(state.error, state.error)
            print(self.run_expressive_edits(page, folder / 'song.yaml'))

    def run_expressive_edits(self, page, song_path):
        original = song_path.read_bytes()
        source = api.from_yaml(original.decode('utf-8'))
        errors = []
        page.on('pageerror', lambda e: errors.append(str(e)))
        page.evaluate("tab('tab');setEdit(true)")
        page.wait_for_selector('[data-ui=independent]')
        self.capture_engraving(page)
        page.select_option('[data-ui=track]', 'bass')
        page.select_option('[data-ui=track]', 'guitar')
        revision = page.evaluate('SCORE.view.revision')
        def ready():
            self.settled(page, 'window.tabRendered&&tabRenderedRevision===SCORE.view.revision&&tabRenderApi.boundsLookup?.isFinished')
        def command(selector, endpoint='score_command'):
            with page.expect_response(lambda r: r.request.method == 'POST' and r.url.endswith('/api/' + endpoint)) as response:
                page.click(selector)
            result = response.value.json()
            self.assertEqual(response.value.status, 200, result)
            self.assertNotIn('error', result)
            self.settled(page, 'SCORE.view.revision===' + json.dumps(result['revision']))
            return result
        def restore(result):
            after = song_path.read_bytes()
            page.click('[data-action=undo]')
            self.settled(page, 'SCORE.view.revision===' + json.dumps(revision))
            self.assertEqual(song_path.read_bytes(), original)
            page.click('[data-action=redo]')
            self.settled(page, 'SCORE.view.revision===' + json.dumps(result['revision']))
            self.assertEqual(song_path.read_bytes(), after)
            page.click('[data-action=undo]')
            self.settled(page, 'SCORE.view.revision===' + json.dumps(revision))
            self.assertEqual(song_path.read_bytes(), original)
            ready()
        if page.locator('.vt-tab-inspector').get_attribute('open') is None:
            page.locator('.vt-tab-inspector > summary').click()
        ready()
        self.click_tab_lane(page, 0, 0, 1)
        page.check('[data-ui=fit]')
        result = command('[data-action=longer]')
        changed = api.from_yaml(song_path.read_text(encoding='utf-8'))
        beats = {b['id']: b for b in changed['score']['patterns']['A']['beats']}
        self.assertEqual(beats['a']['written']['value'], 2)
        self.assertEqual(beats['b']['at'], [2, 1])
        self.assertTrue(beats['a']['notes'][0]['slide'])
        self.assertTrue(beats['b']['notes'][0]['vibrato'])
        self.assertEqual(beats['b']['notes'][0]['velocity'], 63)
        restore(result)
        self.click_tab_lane(page, 0, 0, 1)
        page.uncheck('[data-ui=fit]')
        result = command('[data-action=shorter]')
        changed = api.from_yaml(song_path.read_text(encoding='utf-8'))
        self.assertEqual(next(b for b in changed['score']['patterns']['A']['beats'] if b['id'] == 'a')['written']['value'], 8)
        restore(result)
        # Copy a quarter into the middle of a vibrato whole note; both retained
        # edge fragments keep vibrato and the trailing fragment starts afresh.
        self.click_tab_lane(page, 0, 3, 1)
        page.click('[data-action=copy]')
        page.wait_for_function("document.querySelector('.vt-tab-status').textContent.startsWith('Copied ')")
        self.click_tab_lane(page, 2, 0, 1)
        page.fill('[data-ui=at]', '1')
        page.click('[data-action=go]')
        page.click('[data-action=select-none]')
        result = command('[data-action=paste-span]', 'score')
        changed = api.from_yaml(song_path.read_text(encoding='utf-8'))
        beats = sorted(changed['score']['patterns']['C']['beats'], key=lambda b: b['at'][0] / b['at'][1])
        self.assertEqual([b['at'] for b in beats], [[0, 1], [1, 1], [2, 1]])
        self.assertTrue(beats[0]['notes'][0]['vibrato'])
        self.assertTrue(beats[-1]['notes'][0]['vibrato'])
        restore(result)
        self.click_tab_lane(page, 3, 0, 1)
        page.click('[data-action=measures]')
        page.select_option('[data-ui=measure]', 'D')
        page.fill('[data-ui=meter-n]', '3')
        page.check('[data-ui=meter-to-end]')
        result = command('.vt-tab-measures button[type=submit]')
        changed = api.from_yaml(song_path.read_text(encoding='utf-8'))
        self.assertEqual(performance(changed), performance(source))
        page.click('[data-action=close-measures]')
        restore(result)
        self.assertFalse(errors, errors)
        return dict(expressive_fit=True, expressive_shorter=True, partial_expressive_paste=True,
                    strum_rebar=True, exact_undo_redo=True, no_song_changes_left=True, page_errors=errors)


if __name__ == '__main__':
    unittest.main()
