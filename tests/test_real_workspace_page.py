"""Compact score workspace, persistent panels and contextual keyboard controls."""
import unittest

from tests import test_tablature_page as helpers
from tests.test_tablature_sync import complete_song_seed
from vulturetracker import api


class TestRealWorkspacePage(unittest.TestCase):
    page = helpers.TestTablaturePage.page
    muted_page = helpers.TestTablaturePage.muted_page
    settled = helpers.TestTablaturePage.settled
    capture_engraving = helpers.TestTablaturePage.capture_engraving

    def ready(self, page):
        page.wait_for_function('typeof S!=="undefined"&&S&&S.song')
        page.evaluate("tab('tab');setEdit(true)")
        page.wait_for_selector('[data-ui=track]')
        self.capture_engraving(page)
        page.wait_for_function('SCORE.view?.score?.tracks && document.querySelector("[data-ui=track]").options.length>1')
        page.select_option('[data-ui=track]', index=1)
        page.select_option('[data-ui=track]', index=0)
        self.settled(page, 'window.tabRendered&&tabRenderedRevision===SCORE.view.revision&&tabRenderApi.boundsLookup.isFinished')

    def run_workspace(self, page, song_path):
        """Reusable against the package; leaves document bytes and preferences intact."""
        original = song_path.read_bytes()
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        self.ready(page)
        saved = page.evaluate("Object.fromEntries(['vt.scoreWorkspace','vt.scoreShortcuts','vt.fretboard'].map(k=>[k,localStorage.getItem(k)]))")
        page.evaluate("localStorage.removeItem('vt.scoreWorkspace');localStorage.removeItem('vt.scoreShortcuts')")
        page.reload()
        self.ready(page)
        self.assertFalse(page.locator('.vt-tab-inspector').evaluate('e=>e.open'))
        page.click('[data-action=workspace-focus]')
        geometry = page.evaluate("""() => {
          const root=document.querySelector('#tab-editor').getBoundingClientRect(), score=document.querySelector('.vt-tab-score').getBoundingClientRect();
          return {distance:score.top-root.top, width:root.width};
        }""")
        self.assertLess(geometry['distance'], 420, geometry)
        page.locator('.vt-tab-inspector > summary').click()
        self.assertLessEqual(page.locator('.vt-tab-inspector').bounding_box()['height'], 252)
        page.locator('.vt-tab-grid-details > summary').click()
        page.locator('.vt-piano > summary').click()
        page.wait_for_function("JSON.parse(localStorage.getItem('vt.scoreWorkspace')).piano===true")
        page.reload()
        self.ready(page)
        for panel in ['.vt-tab-inspector', '.vt-tab-grid-details', '.vt-piano']:
            self.assertTrue(page.locator(panel).evaluate('e=>e.open'))
        page.click('[data-action=workspace-focus]')
        for panel in ['.vt-tab-inspector', '.vt-tab-grid-details', '.vt-piano', '.vt-fretboard']:
            self.assertFalse(page.locator(panel).evaluate('e=>e.open'))

        page.fill('[data-ui=jump-bar]', '2')
        page.click('[data-action=jump-bar]')
        self.settled(page, 'SCORE.view.order===1')
        page.click('[data-action=quick-next]')
        self.settled(page, 'SCORE.view.order===2')
        page.locator('#tab-editor').focus()
        page.keyboard.press('Control+ArrowLeft')
        self.settled(page, 'SCORE.view.order===1')
        first = page.input_value('[data-ui=track]')
        page.keyboard.press('Control+Shift+ArrowDown')
        self.assertNotEqual(page.input_value('[data-ui=track]'), first)
        page.keyboard.press('Control+Shift+ArrowUp')
        self.assertEqual(page.input_value('[data-ui=track]'), first)

        page.locator('.vt-tab-keyboard-help > summary').click()
        page.select_option('[data-ui=shortcut-action]', 'measure-next')
        page.locator('[data-ui=shortcut-key]').press('a')
        page.click('[data-action=shortcut-save]')
        self.assertIn('Already assigned', page.locator('[data-ui=shortcut-status]').text_content())
        page.locator('[data-ui=shortcut-key]').press('Control+s')
        page.click('[data-action=shortcut-save]')
        self.assertIn('Reserved', page.locator('[data-ui=shortcut-status]').text_content())
        page.locator('[data-ui=shortcut-key]').press('Alt+n')
        page.click('[data-action=shortcut-save]')
        page.reload()
        self.ready(page)
        page.fill('[data-ui=jump-bar]', '1')
        page.click('[data-action=jump-bar]')
        page.locator('#tab-editor').focus()
        page.keyboard.press('Control+ArrowRight')
        self.assertEqual(page.evaluate('SCORE.view.order'), 0, 'Old overridden shortcut must be unbound')
        page.keyboard.press('Alt+n')
        self.settled(page, 'SCORE.view.order===1')
        # The same chord in text fields must neither navigate nor modify notes.
        page.click('[data-action=properties]')
        page.locator('[data-credit=title]').press('Alt+n')
        self.assertEqual(page.evaluate('SCORE.view.order'), 1)
        page.locator('[data-credit=title]').press('Escape')
        page.evaluate("tab('pattern')")
        page.keyboard.press('Alt+n')
        self.assertEqual(page.evaluate('SCORE.view.order'), 1)
        page.evaluate("tab('tab')")
        page.locator('#tab-editor').focus()
        page.keyboard.press('g')
        self.assertEqual(page.evaluate('document.activeElement.dataset.ui'), 'grace-kind')
        self.assertEqual(song_path.read_bytes(), original)
        page.click('[data-action=workspace-focus]')
        page.fill('[data-ui=jump-bar]', '1')
        page.click('[data-action=jump-bar]')
        page.evaluate("async saved=>{await new Promise(resolve=>setTimeout(resolve,0));for(const[k,v]of Object.entries(saved)){if(v===null)localStorage.removeItem(k);else localStorage.setItem(k,v)}}", saved)
        page.reload()
        self.ready(page)
        self.assertEqual(errors, [])

    def test_workspace_preferences_shortcuts_and_navigation(self):
        song = complete_song_seed()
        for sample in song['samples'].values():
            sample['file'] = 'a.wav'
        with self.muted_page(api.to_yaml(song)) as (page, state, folder):
            self.assertFalse(state.error, state.error)
            self.run_workspace(page, folder / 'song.yaml')
