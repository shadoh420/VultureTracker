"""New finishing/sharing controls exercised through a real browser, on a synthetic song."""
import os
from pathlib import Path
import tempfile
import threading
import time
import unittest

from vulturetracker import gui
from vulturetracker.wavload import write_wav
from tests.test_gui import SONG_BLOCK, sine, RATE

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    sync_playwright = None


@unittest.skipIf(sync_playwright is None, 'Playwright is unavailable')
class TestWorkflowPage(unittest.TestCase):
    def test_finishing_workflow_and_audio_playback(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            original = folder / 'original'
            original.mkdir()
            for name, hz in [('a', 440), ('b', 880)]:
                write_wav(original / (name+'.wav'), RATE, [sine(hz)])
            song = original / 'song.yaml'
            song.write_bytes(SONG_BLOCK.encode())
            st = gui.Handler.state = gui.State(song)
            server = gui._Server(('127.0.0.1', 0), gui.Handler)
            threading.Thread(target=server.serve_forever, daemon=True).start()
            errors, dialogs = [], []
            try:
                with sync_playwright() as pw:
                    browser = pw.chromium.launch(executable_path=os.environ.get('VT_CHROMIUM') or None)
                    page = browser.new_page(viewport={'width': 1600, 'height': 1000})
                    page.on('pageerror', lambda e: errors.append(str(e)))
                    page.on('dialog', lambda d: (dialogs.append(d.message), d.accept()))
                    page.goto(f'http://127.0.0.1:{server.server_address[1]}/')
                    page.wait_for_function('S?.song?.facts && PAT.rows')
                    page.click('[data-t="project"]')
                    page.fill('#checkpoint-name', 'Before arrangement')
                    page.get_by_role('button', name='SAVE CHECKPOINT', exact=True).click()
                    page.wait_for_function("S.checkpoints.includes('Before arrangement')")
                    page.click('[data-t="song"]')
                    page.fill('#section-name', 'Intro')
                    page.get_by_role('button', name='SAVE NAME / SPAN').click()
                    page.wait_for_function('S.sections.Intro')
                    page.fill('#section-to', '2')
                    page.get_by_role('button', name='DUPLICATE SECTION').click()
                    page.wait_for_function('S.structure.orders.length === 3')
                    page.click('[data-t="pattern"]')
                    page.wait_for_function('PAT.rows?.length === 4')
                    page.click('[data-t="phrases"]')
                    page.get_by_role('button', name='NEW COMPARISON FROM PATTERN SELECTION').click()
                    page.wait_for_function('S.phrase?.variants?.length === 3')
                    page.fill('#phrase-name', 'Our line')
                    page.fill('#phrase-data', 'D-5 01 ... ...\n... .. ... ...\n... .. ... ...\n... .. ... ...')
                    page.fill('#phrase-stars', '4')
                    page.fill('#phrase-note', 'Disposable browser check')
                    page.get_by_role('button', name='SAVE ALTERNATIVE / RATING / NOTE').click()
                    page.wait_for_function("S.phrase.variants[0].name === 'Our line'")
                    page.get_by_role('button', name='▶ Our line', exact=True).click()
                    page.wait_for_function("!$('phrase-audio').paused && $('phrase-audio').currentTime > .05")
                    self.assertGreater(page.eval_on_selector('#phrase-audio', 'a=>a.duration'), .4)
                    page.get_by_role('button', name='▶ Line absent', exact=True).click()
                    page.wait_for_function("!$('phrase-audio').paused && $('phrase-audio').readyState >= 3")
                    page.get_by_role('button', name='YAML DIFF / ACCEPT').click()
                    page.wait_for_selector('#workflowmodal.on')
                    self.assertIn('D-5', page.text_content('#workflow-diff'))
                    page.click('#workflow-confirm')
                    page.wait_for_function('S.phrase.accepted === 0')
                    page.click('[data-t="project"]')
                    page.get_by_role('button', name='UNDO', exact=True).click()
                    page.wait_for_function('S.redo === 1')
                    page.get_by_role('button', name='REDO', exact=True).click()
                    page.wait_for_function('S.redo === 0')
                    page.click('[data-t="export"]')
                    page.fill('#export-dest', str(folder / 'exports'))
                    page.select_option('#export-format', 'wav')
                    page.select_option('#export-region', 'Intro')
                    page.select_option('#export-tail-mode', 'cut')
                    page.check('#export-stems')
                    page.click('#export-go')
                    page.wait_for_function("S.export?.status === 'done'", timeout=20000)
                    self.assertEqual(len(st.export_result['files']), 3)
                    page.click('[data-t="project"]')
                    page.fill('#collect-dest', str(folder / 'collected'))
                    page.check('#collect-zip')
                    page.get_by_role('button', name='COLLECT SAMPLES & SAVE COPY').click()
                    page.wait_for_function("$('collect-result').textContent.includes('Original untouched')")
                    self.assertTrue((folder / 'collected.zip').is_file())
                    # External edit is compared, then loaded without stale history.
                    song.write_bytes(song.read_bytes() + b'# external browser check\n')
                    page.wait_for_selector('#dirty', state='visible')
                    page.click('#dirty')
                    page.wait_for_selector('#workflowmodal.on')
                    self.assertIn('external browser check', page.text_content('#workflow-diff'))
                    page.click('#workflow-confirm')
                    page.wait_for_function('S.undo === 0 && !S.song.dirty')
                    # Exercise the AudioWorklet too, beyond HTML audio and API success.
                    page.evaluate("$('phrase-audio').pause(); tab('pattern'); lvPlay(0,0)")
                    page.wait_for_function('LV.playing && LV.pos && LV.pos.row > 0', timeout=10000)
                    page.evaluate('lvStop()')
                    browser.close()
                self.assertEqual(errors, [])
                self.assertTrue(all('External reload:' in d for d in dialogs), dialogs)
            finally:
                server.shutdown()
                server.server_close()
                gui.Handler.state = None
                for _ in range(200):
                    if not st.jobs.qsize() and not any(r['status'] in ('queued', 'rendering') for r in st.renders.values()):
                        break
                    time.sleep(.02)
                st.close()
