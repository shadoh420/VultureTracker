"""Performance parts retain musical context through excerpts and page turns."""
import os
from pathlib import Path
import unittest

from tests import test_tablature_page as helpers
from tests.test_tablature_sync import complete_song_seed
from vulturetracker import api


@unittest.skipIf(helpers.page_fixture.sync_playwright is None, 'playwright not installed')
class TestPerformancePartsPage(unittest.TestCase):
    page = helpers.TestTablaturePage.page
    muted_page = helpers.TestTablaturePage.muted_page
    print_ready = helpers.TestTablaturePage.print_ready
    print_url = helpers.TestTablaturePage.print_url
    capture_engraving = helpers.TestTablaturePage.capture_engraving

    def test_staff_overrides_and_source_bar_labels_survive_excerpt(self):
        source = complete_song_seed()
        for sample in source['samples'].values():
            sample['file'] = 'a.wav'
        source['score']['measures'][1]['staff'] = {
            'guitar': dict(clef='bass', key=dict(fifths=-2, mode='minor'))}
        source['score']['measures'][3]['staff'] = {'guitar': dict(key=dict(fifths=1, mode='major'))}
        with self.muted_page(api.to_yaml(source), width=1400, height=1000) as (page, state, folder):
            self.assertFalse(state.error, state.error)
            before = state.song_path.read_bytes()
            errors = []
            page.on('pageerror', lambda e: errors.append(str(e)))
            page.evaluate("tab('tab')")
            page.wait_for_selector('.vt-tab-score svg')
            self.capture_engraving(page)
            page.select_option('[data-ui=track]', 'guitar2')
            page.select_option('[data-ui=track]', 'guitar')
            page.wait_for_function('window.tabRendered&&tabRenderApi.boundsLookup.isFinished')
            model = "tabRendered.tracks[0].staves[0].bars.map(b=>[b.clef,b.keySignature,b.keySignatureType])"
            bass = page.evaluate('alphaTab.model.Clef.F4')
            treble = page.evaluate('alphaTab.model.Clef.G2')
            # Staff changes remain effective until changed again, including
            # when the first changed measure is outside the printed excerpt.
            self.assertEqual(page.evaluate(model)[1:], [[bass, -2, 1], [bass, -2, 1], [bass, 1, 0]])
            preview = page.context.browser.new_page()
            preview.on('pageerror', lambda e: errors.append(str(e)))
            preview.goto(self.print_url(page, state))
            self.print_ready(preview)
            self.capture_engraving(preview)
            preview.fill('[name=first]', '3')
            preview.fill('[name=last]', '4')
            preview.locator('form button[type=submit]').click()
            self.print_ready(preview)
            self.assertEqual(preview.evaluate(model), [[bass, -2, 1], [bass, 1, 0]])
            self.assertIn('Bars 3–4', preview.locator('.vt-print-footer').text_content())
            self.assertEqual(state.song_path.read_bytes(), before)
            self.assertFalse(errors, errors)
            preview.close()

    def test_page_turns_identify_part_bars_and_preserve_ties_lyrics(self):
        source = helpers.TestTablaturePage.four_bar_song()
        source['score']['measures'][0]['marker'] = dict(title='Opening')
        source['score']['measures'][2]['marker'] = dict(title='Bridge')
        source['score']['tracks']['guitar']['lyrics'] = dict(from_measure=1, text=' '.join(f'word{i}' for i in range(16)))
        source['score']['patterns']['F']['beats'][0]['notes'][0].update(pitch=64, string=1, fret=0)
        source['score']['ties'] = [dict(
            **{'from': dict(occurrence='bar1', note='note3')},
            to=dict(occurrence='bar2', note='note0'))]
        with self.muted_page(api.to_yaml(source), width=1400, height=1000) as (page, state, folder):
            self.assertFalse(state.error, state.error)
            before = state.song_path.read_bytes()
            preview = page.context.browser.new_page()
            preview.goto(self.print_url(page, state))
            self.print_ready(preview)
            self.capture_engraving(preview)
            preview.select_option('[name=breaks]', ['1', '2', '3'])
            preview.locator('form button[type=submit]').click()
            self.print_ready(preview)
            self.assertEqual(preview.locator('.vt-print-page').count(), 4)
            self.assertIn('Opening (cont.)', preview.locator('.vt-print-footer').nth(1).text_content())
            self.assertIn('Bridge (cont.)', preview.locator('.vt-print-footer').nth(3).text_content())
            self.assertTrue(preview.evaluate('tabRendered.tracks[0].staves[0].bars[1].voices[0].beats[0].notes[0].tieOrigin != null'))
            for index, footer in enumerate(preview.locator('.vt-print-footer').all()):
                self.assertIn('Guitar', footer.text_content())
                self.assertIn(f'Bar {index + 1}', footer.text_content())
                self.assertIn(f'{index + 1} / 4', footer.text_content())
            words = preview.evaluate('tabRendered.tracks[0].staves[0].bars.flatMap(b=>b.voices[0].beats.flatMap(b=>b.lyrics||[]))')
            helpers.lyric_boxes(preview, '.vt-print-pages', words)
            self.assertTrue(preview.evaluate("[...document.querySelectorAll('.vt-print-content')].every(e=>e.scrollHeight<=e.clientHeight+1)"))
            evidence = os.environ.get('VT_ENGRAVING_EVIDENCE')
            if evidence:
                path = Path(evidence); path.mkdir(parents=True, exist_ok=True)
                # Layout evidence only: headless capture is not foreground visual acceptance.
                preview.screenshot(path=str(path / 'performance-parts-headless.png'), full_page=True)
            self.assertEqual(state.song_path.read_bytes(), before)
            preview.close()


if __name__ == '__main__':
    unittest.main()
