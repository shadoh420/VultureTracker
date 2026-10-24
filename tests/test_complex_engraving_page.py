"""Dense original score through the real editor and shared print projection."""
import os
from pathlib import Path
import unittest

from tests import test_tablature_page as helpers
from tests.test_tablature import beat, note
from tests.test_tablature_sync import complete_song_seed
from vulturetracker import api


def dense_score():
    source = complete_song_seed()
    source['module']['title'] = 'Crosscurrents study'
    source['score']['ties'] = []
    words = ('Across open water shifting currents carry daylight '
             'Over distant branches gentle echoes answer softly '
             'Through the turning valley scattered lanterns gather slowly '
             'Under quiet arches silver voices return home').split()
    source['score']['tracks']['guitar']['lyrics'] = dict(from_measure=1, text=' '.join(words))
    source['score']['tracks']['guitar2']['name'] = 'Rhythm guitar — low tuning'
    for sample in source['samples'].values():
        sample['file'] = 'a.wav'
    for bar, pattern in enumerate(source['score']['patterns'].values()):
        pattern['beats'] = [b for b in pattern['beats'] if b['track'] != 'guitar']
        for index, fret in enumerate((3, 7, 5, 2, 8, 5, 3, 7)):
            n = note(f'lead-{index}', 64 + fret, 1, fret)
            n.update(velocity=95, vibrato=True)
            if index % 4 == 0:
                n.update(tapping=True, harmonic=dict(type='artificial', data=0))
            b = beat(f'phrase-{index}', [index, 2], [n], value=8)
            b['pick_stroke'] = 'up' if index % 2 else 'down'
            if index in (0, 1):
                b['text'] = ('Let the melody ring clearly', 'Answer softly above the bass')[index]
            if index in (0, 4):
                b['chord'] = dict(name=('Cmaj7', 'Am7')[index // 4], first_fret=0,
                                  frets=[0, 0, 0, 2, 3, -1])
            pattern['beats'].append(b)
        for index in (0, 2):
            pattern['beats'].append(beat(f'pedal-{index}', [index, 1],
                [dict(note(f'pedal-note-{index}', 48 + bar % 2, 6, 8 + bar % 2), velocity=63)],
                value=2, voice=1))
    source['score']['measures'][0]['marker'] = dict(title='Crosscurrents')
    source['score']['measures'][2]['marker'] = dict(title='Answer')
    return source, words


@unittest.skipIf(helpers.page_fixture.sync_playwright is None, 'playwright not installed')
class TestComplexEngravingPage(unittest.TestCase):
    page = helpers.TestTablaturePage.page
    muted_page = helpers.TestTablaturePage.muted_page
    settled = helpers.TestTablaturePage.settled
    capture_engraving = helpers.TestTablaturePage.capture_engraving
    print_ready = helpers.TestTablaturePage.print_ready
    print_url = helpers.TestTablaturePage.print_url

    def annotation_boxes(self, page, selector):
        boxes = page.locator(selector).evaluate("""root=>[...root.querySelectorAll('svg text')]
            .filter(e=>/Let the melody|Answer softly/.test(e.textContent))
            .map(e=>({text:e.textContent,...e.getBoundingClientRect().toJSON()}))""")
        for first, second in zip(boxes[::2], boxes[1::2]):
            if abs(first['top'] - second['top']) < first['height']:
                self.assertGreater(second['left'] - first['right'], 1, (first, second))
        return dict(count=len(boxes), min_gap=min(b['left'] - a['right'] for a, b in zip(boxes[::2], boxes[1::2])))

    def test_dense_score_editor_and_print(self):
        source, words = dense_score()
        with self.muted_page(api.to_yaml(source), width=1600, height=1000, compact=True) as (page, state, folder):
            self.assertFalse(state.error, state.error)
            original = state.song_path.read_bytes()
            errors = []
            page.on('pageerror', lambda e: errors.append(str(e)))
            page.evaluate("tab('tab');setEdit(true)")
            page.wait_for_selector('.vt-tab-score svg')
            page.evaluate('() => document.fonts.ready')
            self.capture_engraving(page)
            page.select_option('[data-ui=track]', 'guitar')
            self.settled(page, 'window.tabRendered&&tabRenderApi.boundsLookup?.isFinished')
            self.assertEqual(len(page.evaluate('tabRendered.tracks[0].staves[0].bars[0].voices')), 2)
            print('Editor annotation gaps:', self.annotation_boxes(page, '.vt-tab-score'))
            evidence = os.environ.get('VT_ENGRAVING_EVIDENCE')
            if evidence:
                path = Path(evidence); path.mkdir(parents=True, exist_ok=True)
                page.screenshot(path=str(path / 'dense-editor.png'), full_page=True)
            print('Dense lyrics:', helpers.lyric_boxes(page, '.vt-tab-score', words))
            for width in (1100, 900):
                page.set_viewport_size(dict(width=width, height=1000))
                page.wait_for_function("document.querySelector('.vt-tab-score .at-surface').hidden")
                self.assertIn('Beat annotations', page.inner_text('.vt-tab-status'))
            page.set_viewport_size(dict(width=1600, height=1000))
            page.wait_for_function("!document.querySelector('.vt-tab-score .at-surface').hidden")
            self.annotation_boxes(page, '.vt-tab-score')
            self.assertEqual(page.locator('.vt-tab-edit-caret svg').count(), 0)
            self.assertEqual(page.locator('.vt-tab-playhead svg').count(), 0)
            for track in ('guitar2', 'bass', 'drums', 'guitar'):
                page.select_option('[data-ui=track]', track)
                self.settled(page, 'window.tabRendered&&tabRenderApi.boundsLookup?.isFinished')
                self.assertFalse(page.locator('.vt-tab-score .at-surface').evaluate('e=>e.hidden'))
                self.assertEqual(page.locator('.vt-tab-edit-caret svg').count(), 0)
            preview = page.context.browser.new_page()
            preview.on('pageerror', lambda e: errors.append(str(e)))
            preview.goto(self.print_url(page, state))
            preview.select_option('[name=orientation]', 'landscape')
            preview.fill('[name=scale]', '50')
            preview.locator('form button[type=submit]').click()
            self.print_ready(preview)
            print('Print annotations:', self.annotation_boxes(preview, '.vt-print-pages'))
            self.assertEqual(preview.locator('.vt-print-page').count(), 4)
            helpers.lyric_boxes(preview, '.vt-print-pages', words)
            if evidence:
                preview.screenshot(path=str(path / 'dense-print.png'), full_page=True)
            # Selected-part excerpts must preserve the source bar's lyrics and
            # annotations in both independent notation views.
            for track in ('guitar2', 'bass', 'drums'):
                preview.uncheck(f'[name=track][value={track}]')
            preview.fill('[name=first]', '2'); preview.fill('[name=last]', '3')
            for notation in ('tab', 'staff'):
                preview.select_option('[name=notation]', notation)
                preview.locator('form button[type=submit]').click()
                self.print_ready(preview)
                layout = self.annotation_boxes(preview, '.vt-print-pages')
                self.assertEqual(layout['count'], 4)
                helpers.lyric_boxes(preview, '.vt-print-pages', words[8:24])
                self.assertIn('Source bars 2–3', preview.inner_text('.vt-print-pages'))
                self.assertNotIn('Crosscurrents\n', preview.inner_text('.vt-print-pages'))
                print('Excerpt:', notation, layout)
            preview.close()
            if evidence:
                page.set_viewport_size(dict(width=1920, height=1080))
                page.wait_for_timeout(300)
                page.evaluate("document.querySelector('#t-tab').scrollTop=0;document.querySelector('.vt-tab').scrollTop=0")
                page.screenshot(path=str(path / 'dense-editor-1920.png'), full_page=True)
            self.assertEqual(state.song_path.read_bytes(), original)
            self.assertFalse(errors, errors)

    def test_short_dense_labels_remain_readable_at_900px(self):
        source, words = dense_score()
        for pattern in source['score']['patterns'].values():
            for b in pattern['beats']:
                if 'text' in b:
                    b['text'] = 'dolce' if b['id'] == 'phrase-0' else 'espressivo'
        with self.muted_page(api.to_yaml(source), width=900, height=1000, compact=True) as (page, state, folder):
            self.assertFalse(state.error, state.error)
            page.evaluate("tab('tab')")
            page.wait_for_selector('.vt-tab-score svg')
            page.evaluate('() => document.fonts.ready')
            self.assertFalse(page.locator('.vt-tab-score .at-surface').evaluate('e=>e.hidden'))
            self.assertNotIn('need more width', page.inner_text('.vt-tab-status'))
            print('Dense 900px short labels:', helpers.lyric_boxes(page, '.vt-tab-score', ['dolce', 'espressivo'] * 4))
            helpers.lyric_boxes(page, '.vt-tab-score', words)

    def test_long_chord_names_reserve_centered_space(self):
        source = helpers.TestTablaturePage.four_bar_song()
        names = ('Cmaj7(add13)/E', 'Abm7b5(add11)/Gb')
        for pattern in source['score']['patterns'].values():
            for index, b in enumerate(pattern['beats']):
                b['chord'] = dict(name=names[index % 2], first_fret=0, frets=[0, 0, 0, 2, 3, -1])
        with self.muted_page(api.to_yaml(source), width=1600, height=1000, compact=True) as (page, state, folder):
            self.assertFalse(state.error, state.error)
            before = state.song_path.read_bytes()
            page.evaluate("tab('tab')")
            page.wait_for_selector('.vt-tab-score svg')
            page.evaluate('() => document.fonts.ready')
            self.capture_engraving(page)
            page.select_option('[data-ui=track]', 'guitar')
            self.settled(page, 'window.tabRendered&&tabRenderApi.boundsLookup?.isFinished')
            # The two initial chord-chart captions are separate from the 16
            # beat labels, but both must be readable and remain authored text.
            info = helpers.lyric_boxes(page, '.vt-tab-score', list(names) + list(names) * 8)
            print('Long chord labels:', info)
            evidence = os.environ.get('VT_ENGRAVING_EVIDENCE')
            if evidence:
                path = Path(evidence); path.mkdir(parents=True, exist_ok=True)
                page.screenshot(path=str(path / 'long-chords.png'), full_page=True)
                # Isolate the native chord-chart padding, without changing the
                # music, font or beat-label spring widths.
                page.evaluate("""() => {
                    const a=tabRenderApi;
                    window.savedChordPadding=a.settings.display.resources.engravingSettings.chordDiagramPaddingX;
                    a.settings.display.resources.engravingSettings.chordDiagramPaddingX=5;
                    a.updateSettings(); a.renderScore(tabRendered);
                }""")
                page.wait_for_timeout(150)
                page.screenshot(path=str(path / 'long-chords-native-padding-debug.png'), full_page=True)
                page.evaluate("""() => {
                    const a=tabRenderApi;
                    a.settings.display.resources.engravingSettings.chordDiagramPaddingX=savedChordPadding;
                    a.updateSettings(); a.renderScore(tabRendered);
                }""")
                page.wait_for_timeout(150)
                helpers.lyric_boxes(page, '.vt-tab-score', list(names) + list(names) * 8)
            preview = page.context.browser.new_page()
            preview.goto(self.print_url(page, state))
            preview.fill('[name=scale]', '65')
            preview.locator('form button[type=submit]').click()
            self.print_ready(preview)
            print('Long chord print labels:', helpers.lyric_boxes(preview, '.vt-print-pages', list(names) + list(names) * 8))
            preview.close()
            self.assertEqual(state.song_path.read_bytes(), before)


if __name__ == '__main__':
    unittest.main()
