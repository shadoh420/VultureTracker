"""Headless real-control phrase techniques; reusable against the final executable."""
import unittest

from tests import test_tablature_page as helpers
from vulturetracker import api


class TestBandExpressionPage(unittest.TestCase):
    page = helpers.TestTablaturePage.page
    muted_page = helpers.TestTablaturePage.muted_page
    settled = helpers.TestTablaturePage.settled
    capture_engraving = helpers.TestTablaturePage.capture_engraving
    click_tab_lane = helpers.TestTablaturePage.click_tab_lane
    tab_lane_point = staticmethod(helpers.TestTablaturePage.tab_lane_point)

    def run_expression(self, page, song_path):
        original = song_path.read_bytes()
        errors = []
        requests = []
        def command_request(request):
            if request.method == 'POST' and request.url.endswith('/api/score_command'):
                requests.append(request.post_data_json)
        page.on('request', command_request)
        page.on('pageerror', lambda e: errors.append(str(e)))
        page.wait_for_function('typeof S!=="undefined"&&S&&S.song')
        page.evaluate("tab('tab');setEdit(true)")
        page.wait_for_selector('[data-ui=track]', state='attached')
        self.capture_engraving(page)
        page.select_option('[data-ui=track]', 'guitar')
        self.settled(page, 'window.tabRendered&&tabRenderApi.boundsLookup.isFinished')
        original_revision = page.evaluate('SCORE.view.revision')
        def select_phrase():
            self.settled(page, 'window.tabRendered&&tabRenderedRevision===SCORE.view.revision&&tabRenderApi.boundsLookup.isFinished')
            self.click_tab_lane(page, 0, 0, 2)
            page.keyboard.down('Shift')
            try:
                self.click_tab_lane(page, 1, 3, 3)
            finally:
                page.keyboard.up('Shift')
            self.settled(page, "SCORE.view.order===1&&document.querySelectorAll('.vt-tab-selection').length===8")
        select_phrase()
        if not page.locator('.vt-tab-inspector').evaluate('e=>e.open'):
            page.locator('.vt-tab-inspector > summary').click()

        def check_edit(predicate):
            try:
                self.settled(page, "SCORE.view.score.patterns.F.beats.every(b=>b.notes.every(n=>" + predicate + '))')
            except AssertionError:
                print('Expression request diagnostic:', requests[-2:])
                print('Expression control diagnostic:', page.evaluate("({tap:document.querySelector('[data-ui=tap-slap-pop]').value,range:document.querySelector('[data-ui=range-articulation]').value})"))
                raise
            self.assertEqual(page.locator('.vt-tab-selection').count(), 8)
            changed = song_path.read_bytes()
            changed_revision = page.evaluate('SCORE.view.revision')
            self.assertNotEqual(changed, original)
            def history(action, revision):
                page.click(f'[data-action={action}]')
                # Queue completion precedes the asynchronous State/score refresh.
                page.wait_for_function("revision=>!EDQ.n&&!SCORE.fetching&&S.version.hash===revision.slice(0,8)&&SCORE.view.revision===revision&&tabRenderedRevision===revision&&tabRenderApi.boundsLookup.isFinished", arg=revision, timeout=10000)
            history('undo', original_revision)
            self.assertEqual(song_path.read_bytes(), original)
            history('redo', changed_revision)
            self.assertEqual(song_path.read_bytes(), changed)
            history('undo', original_revision)
            self.assertEqual(song_path.read_bytes(), original)
            select_phrase()

        page.click('[data-action=vibrato]'); check_edit('n.vibrato')
        page.select_option('[data-ui=tap-slap-pop]', 'tapping')
        page.click('[data-action=tap-slap-pop]'); check_edit('n.tapping')
        page.select_option('[data-ui=harmonic-type]', 'artificial')
        page.select_option('[data-ui=harmonic-data]', '0')
        page.click('[data-action=harmonic]'); check_edit("n.harmonic?.type==='artificial'")
        page.select_option('[data-ui=repetition-type]', 'tremolo_picking')
        page.select_option('[data-ui=repetition-value]', '16')
        page.click('[data-action=repetition]'); check_edit('n.tremolo_picking?.value===16')
        page.select_option('[data-ui=grace-kind]', 'grace')
        page.fill('[data-ui=grace-fret]', '2')
        page.select_option('[data-ui=grace-timing]', 'on')
        page.click('[data-action=grace]'); check_edit('n.grace?.fret===2')
        page.click('[data-action=bend]')
        self.assertIn('8 selected notes', page.inner_text('[data-ui=curve-title]'))
        page.fill('[data-ui=curve-points]', '0:0, 12:2')
        page.click('[data-ui=curve-apply]'); check_edit('n.bend?.points[1].value===2')
        page.select_option('[data-ui=pick-stroke]', 'up')
        page.click('[data-action=pick-stroke]'); check_edit("b.pick_stroke==='up'")
        page.select_option('[data-ui=stroke-direction]', 'up')
        page.select_option('[data-ui=stroke-value]', '16')
        page.click('[data-action=stroke]'); check_edit("b.stroke?.direction==='up'")
        self.assertFalse(errors, errors)
        return dict(edits=8, selected_beats=8, exact_history=True)

    def test_phrase_techniques_real_controls_and_history(self):
        source = helpers.TestTablaturePage.four_bar_song()
        source['module']['tempo'] = 120
        with self.muted_page(api.to_yaml(source), width=1600, height=1000) as (page, state, folder):
            self.run_expression(page, folder / 'song.yaml')


if __name__ == '__main__':
    unittest.main()
