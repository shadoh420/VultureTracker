"""Exercise 0.7.0 controls in Chromium on disposable songs and fake audio."""
import os
os.environ['VT_WORKERS'] = '1'
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock
from urllib.parse import quote

from playwright.sync_api import sync_playwright
from vulturetracker import api, gui, record
from vulturetracker.wavload import write_wav
from tests.test_gui import SONG_BLOCK, sine, RATE


class TestRelease070Page(unittest.TestCase):
    @mock.patch.dict(os.environ, {'VT_FAKE_AUDIO': '1'})
    def test_chords_spacing_conversion_recording_and_switch(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(gui, 'remember_song'):
            folder = Path(tmp)
            for name, hz in [('a', 440), ('b', 880)]:
                write_wav(folder / (name + '.wav'), RATE, [sine(hz)])
            song = folder / 'song.yaml'
            song.write_bytes(SONG_BLOCK.encode())
            short = api.from_yaml(SONG_BLOCK)
            short['patterns'] = {'short': {'rows': 8, 'data': 'E-5 01 ... ...'}}
            short['orders'] = ['short']
            second = folder / 'short.yaml'
            second.write_bytes(api.to_yaml(short).encode())
            old_state, old_rec = gui.Handler.state, gui.Handler.recorder
            first = gui.Handler.state = gui.State(song)
            gui.Handler.recorder = None
            server = gui._Server(('127.0.0.1', 0), gui.Handler)
            threading.Thread(target=server.serve_forever, daemon=True).start()
            errors, dialogs = [], []
            try:
                with sync_playwright() as pw:
                    browser = pw.chromium.launch(executable_path=os.environ.get('VT_CHROMIUM') or None)
                    page = browser.new_page(viewport={'width': 1700, 'height': 1100})
                    page.on('pageerror', lambda e: errors.append(str(e)))
                    page.on('dialog', lambda d: (dialogs.append(d.message), d.accept()))
                    page.goto(f'http://127.0.0.1:{server.server_address[1]}/')
                    page.wait_for_function('S?.song?.facts && PAT.rows')
                    page.click('[data-t="pattern"]')
                    page.evaluate("MIDI.on=true;setEdit(true);CUR.ch=0;CUR.row=1;midiMsg([0x90,62,100]);midiMsg([0x90,65,80])")
                    page.wait_for_function("S.undo===1 && PAT.rows?.[1]?.[1]?.startsWith('F-5')")
                    self.assertEqual(first.mod.patterns[0].rows[1][0].note, 62)
                    self.assertEqual(first.mod.patterns[0].rows[1][1].note, 65)
                    self.assertEqual(page.evaluate('CUR.row'), 2)
                    page.evaluate('patUndo(false)')
                    page.wait_for_function('S.redo===1')
                    self.assertIsNone(first.mod.patterns[0].rows[1][0].note)
                    self.assertIsNone(first.mod.patterns[0].rows[1][1].note)
                    page.click('[data-t="project"]')
                    page.get_by_role('button', name='CLEAR UNDO / REDO', exact=True).click()
                    page.wait_for_function('S.redo===0 && S.undo===0')
                    page.click('[data-t="song"]')
                    page.locator('#song-mod .row').filter(has_text='rows per beat').locator('.tv').click()
                    page.fill('.typein', '6')
                    page.keyboard.press('Enter')
                    page.wait_for_function('S.song.facts.highlight[0]===6')
                    self.assertIn('83.33', page.text_content('#song-mod'))
                    page.evaluate('CUR.o=1;CUR.row=2;showPattern(1)')
                    page.wait_for_function('PAT.order===1 && PAT.rows')
                    page.evaluate('(p)=>openSong(p)', str(second))
                    page.wait_for_function("PAT.rows?.length===8 && PAT.rows[0][0].startsWith('E-5')")
                    self.assertEqual(page.evaluate('CUR.o'), 0)
                    page.click('[data-t="pattern"]')
                    page.get_by_text('MAKE EDITABLE', exact=True).click()
                    page.wait_for_function('S.undo===1 && !EDQ.n')
                    self.assertIn('data: |', second.read_text())
                    page.click('[data-t="rec"]')
                    page.wait_for_function('REC.st?.devices?.length')
                    self.assertTrue(page.evaluate('REC.st.fake'))
                    self.assertIsInstance(gui.Handler.recorder.be, record.FakeBackend)
                    page.click('#rec-open')
                    page.wait_for_function('REC.st?.status.open')
                    page.check('#rec-backing')
                    page.fill('#rec-countin', '0')
                    page.fill('#rec-loops', '2')
                    page.fill('#rec-name', 'caf\u00e9')
                    page.select_option('#rec-dest', 'keep')
                    page.uncheck('#rec-root')
                    page.click('#rec-go')
                    page.wait_for_function('REC.st?.status.finished', timeout=15000)
                    self.assertEqual(page.text_content('#rec-go'), 'SAVE TAKES')
                    page.click('#rec-go')
                    page.wait_for_function('REC.st?.takes.length===2')
                    take = gui.Handler.state.takes[0]
                    response = page.request.get(f'http://127.0.0.1:{server.server_address[1]}/take/' + quote(take['file']))
                    self.assertEqual(response.status, 200)
                    self.assertEqual(response.body(), (folder / 'takes' / take['file']).read_bytes())
                    page.get_by_role('button', name='CALIBRATE LOOPBACK', exact=True).click()
                    page.wait_for_function('REC.st?.status.finished && REC.st.status.calibrating', timeout=10000)
                    page.click('#rec-go')
                    page.wait_for_function("!REC.st?.status.recording")
                    self.assertGreater(float(page.input_value('#rec-latency')), 0,
                                       page.text_content('#rec-msg') + ' | ' + str(page.evaluate('REC.st.status')))
                    self.assertAlmostEqual(float(page.input_value('#rec-latency')), 50, delta=.05)
                    self.assertEqual(errors, [])
                    self.assertEqual(dialogs, [])
                    browser.close()
            finally:
                server.shutdown()
                server.server_close()
                if gui.Handler.recorder:
                    gui.Handler.recorder.close()
                first.close()
                if gui.Handler.state:
                    gui.Handler.state.close()
                gui.Handler.state, gui.Handler.recorder = old_state, old_rec


if __name__ == '__main__':
    unittest.main()
