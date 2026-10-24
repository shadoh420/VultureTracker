"""Actual part routing control, atomic failures and exact Undo/Redo."""
import json
import unittest

from vulturetracker import api
from tests import test_tablature_page as helpers
from tests.test_complex_routing import routing_song, release_routing_song


class TestComplexRoutingPage(unittest.TestCase):
    page = helpers.TestTablaturePage.page
    muted_page = helpers.TestTablaturePage.muted_page
    settled = helpers.TestTablaturePage.settled

    def run_routing(self, page, path):
        original = path.read_bytes()
        page.evaluate("tab('tab')")
        page.wait_for_selector('.vt-tab-score svg')
        page.locator('#part-sounds').evaluate('e=>e.open=true')
        with page.expect_response('**/api/score_command') as response:
            page.click('#part-voices-separate')
        result = response.value.json()
        self.assertTrue(result.get('ok'), result)
        self.assertGreater(result['moved'], 0)
        self.settled(page, 'SCORE.view.revision===' + json.dumps(result['revision']))
        self.assertIn('Separated overlapping voices', page.inner_text('#part-sound-status'))
        after = path.read_bytes()
        self.assertNotEqual(after, original)
        self.assertTrue(api.compile_song(path)[0])
        page.click('[data-action=undo]')
        self.settled(page, 'SCORE.view.revision!==' + json.dumps(result['revision']))
        self.assertEqual(path.read_bytes(), original)
        page.click('[data-action=redo]')
        self.settled(page, 'SCORE.view.revision===' + json.dumps(result['revision']))
        self.assertEqual(path.read_bytes(), after)
        page.click('[data-action=undo]')
        self.settled(page, 'SCORE.view.revision!==' + json.dumps(result['revision']))
        self.assertEqual(path.read_bytes(), original)
        return dict(routed_notes=result['moved'], exact_undo_redo=True)

    def test_route_overlapping_voices_control(self):
        with self.muted_page(api.to_yaml(routing_song()), width=1600, height=1000, compact=True) as (page, state, folder):
            self.assertFalse(state.error, state.error)
            print(self.run_routing(page, state.song_path))

    def test_route_sustained_instrument_control(self):
        with self.muted_page(api.to_yaml(release_routing_song()), width=1600, height=1000, compact=True) as (page, state, folder):
            self.assertFalse(state.error, state.error)
            print('sustained instrument', self.run_routing(page, state.song_path))


if __name__ == '__main__':
    unittest.main()
