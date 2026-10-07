"""The RACK tab, the piano roll, the approved marks, TAP and the AGENT panel in Chromium on a disposable song: each
confirms its edit in the song file (or, for the panel, in what the page shows)."""
import contextlib
import json
import os
os.environ['VT_WORKERS'] = '1'
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

try:
    from playwright.sync_api import Error as PlaywrightError, sync_playwright
except ImportError:  # pragma: no cover
    sync_playwright = None
from vulturetracker import agent, gui
from vulturetracker.wavload import write_wav
from tests.test_gui import SONG_BLOCK, sine, RATE


@unittest.skipIf(sync_playwright is None, 'playwright not installed')
class TestFeaturesPage(unittest.TestCase):
    @contextlib.contextmanager
    def page(self, text=SONG_BLOCK):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(gui, 'remember_song'), \
                mock.patch.object(agent, 'settings_path', lambda: Path(tmp) / 'agent.json'):
            d = Path(tmp)
            write_wav(d / 'a.wav', RATE, [sine(440)])
            write_wav(d / 'b.wav', RATE, [sine(880)])
            (d / 'song.yaml').write_bytes(text.encode())
            st = gui.Handler.state = gui.State(d / 'song.yaml')
            srv = gui._Server(('127.0.0.1', 0), gui.Handler)
            threading.Thread(target=srv.serve_forever, daemon=True).start()
            errors = []
            try:
                with sync_playwright() as p:
                    exe = os.environ.get('VT_CHROMIUM')
                    try:
                        browser = p.chromium.launch(**({'executable_path': exe} if exe else {}))
                    except PlaywrightError as e:
                        self.skipTest(f'no browser to drive the page with: {str(e).splitlines()[0]}')
                    page = browser.new_page(viewport={'width': 1500, 'height': 900})
                    page.on('pageerror', lambda e: errors.append(str(e)))
                    page.goto(f'http://127.0.0.1:{srv.server_address[1]}/')
                    page.wait_for_function("typeof S !== 'undefined' && S && S.song && S.song.facts")
                    page.evaluate("localStorage.removeItem('uiscale'); localStorage.removeItem('agent')")
                    yield page, d
                    browser.close()
                self.assertEqual(errors, [])
            finally:
                srv.shutdown()
                srv.server_close()
                for s in {st, gui.Handler.state}:
                    if s:
                        s.close()
                gui.Handler.state = None

    def settle(self, page):
        page.wait_for_function("EDQ.n===0")
        page.evaluate("refresh()")

    def test_rack(self):
        with self.page() as (page, d):
            page.evaluate("tab('rack'); RK_CH=1; renderRack()")
            page.select_option('#rk-add', 'echo')
            page.click("text=+ ADD EFFECT")
            page.wait_for_function("S.song.facts.channel_plugins[1]===1")
            self.assertIn("    - {name: B, pan: 40, plugin: 1}\n", (d / 'song.yaml').read_text())
            knob = page.locator('#rk-chain .rkp svg').nth(1)  # feedback
            box = knob.bounding_box()
            page.mouse.move(box['x'] + 17, box['y'] + 17)
            page.mouse.down()
            page.mouse.move(box['x'] + 17, box['y'] - 13, steps=5)
            page.mouse.up()
            page.wait_for_function("S.song.facts.plugins[1].feedback>50")
            self.assertRegex((d / 'song.yaml').read_text(), r"1: \{effect: echo,.*feedback: (5[1-9]|[6-9]\d)")
            page.click('#rk-chain .rkp .auto >> nth=0')  # wet_dry gets SF1
            page.wait_for_function("(S.song.facts.macros||{}).SF1==='F0F080z'")
            self.assertIn("SF1 then Zxx", page.text_content('#rk-msg'))

    def test_roll_marks_and_tap(self):
        with self.page() as (page, d):
            page.evaluate("tab('pattern'); setEdit(true); CUR.ch=0; showPattern(0); renderPat(); rollToggle()")
            page.wait_for_function("document.querySelectorAll('#roll .rnote:not(.ghost)').length===1")
            # a note drawn two rows long ends in a note-off on the row after
            page.evaluate("""(()=>{const r=$('roll').getBoundingClientRect(),y=(ROLL.hi-62)*ROLL.PH+6,x=40+1*ROLL.RW+5;
              rollDown({button:0,preventDefault(){},shiftKey:false,target:$('roll'),clientX:r.left+x,clientY:r.top+y});
              dispatchEvent(new MouseEvent('mousemove',{clientX:r.left+x+ROLL.RW,clientY:r.top+y}));dispatchEvent(new MouseEvent('mouseup'))})()""")
            self.settle(page)
            rows = page.evaluate("PAT.rows.map(r=>r[0])")
            self.assertEqual(rows[1].split(' ')[0], 'D-5')
            self.assertEqual(rows[3], '=== .. ... ...')
            # approved marks from the SONG tab
            page.evaluate("tab('song')")
            page.click('#song-ch .stem >> nth=0 >> .ms >> nth=0')
            self.settle(page)
            self.assertIn("    - {name: A, approved: true}\n", (d / 'song.yaml').read_text())
            # TAP: four taps 500 ms apart at speed 6 and 4 rows a beat: 120 BPM, tempo 120
            page.evaluate("TAP.t=[0,500,1000].map(x=>performance.now()-1500+x);tapTempo()")
            page.wait_for_function("S.song.facts.tempo!==125", timeout=5000)
            self.assertIn(page.evaluate("S.song.facts.tempo"), (119, 120, 121))

    def test_paint_undo(self):
        with self.page() as (page, d):
            page.evaluate("tab('paint')")
            page.wait_for_function("PT.amp && document.getElementById('pt-cv').clientWidth>0")
            box = page.locator('#pt-cv').bounding_box()
            page.mouse.move(box['x'] + box['width'] / 2, box['y'] + box['height'] / 2)
            page.mouse.down()
            page.mouse.move(box['x'] + box['width'] / 2 + 40, box['y'] + box['height'] / 2, steps=4)
            page.mouse.up()
            painted = page.evaluate("PT.amp.reduce((a,b)=>a+b,0)")
            self.assertGreater(painted, 0)
            page.evaluate("ptClear()")
            self.assertEqual(page.evaluate("PT.amp.reduce((a,b)=>a+b,0)"), 0)
            page.keyboard.press('Control+z')   # the clear undone: the stroke is back
            self.assertAlmostEqual(page.evaluate("PT.amp.reduce((a,b)=>a+b,0)"), painted, places=3)
            page.keyboard.press('Control+z')   # the stroke undone
            self.assertEqual(page.evaluate("PT.amp.reduce((a,b)=>a+b,0)"), 0)
            page.keyboard.press('Control+y')
            self.assertAlmostEqual(page.evaluate("PT.amp.reduce((a,b)=>a+b,0)"), painted, places=3)
            page.click('#pt-undo')
            self.assertEqual(page.evaluate("PT.amp.reduce((a,b)=>a+b,0)"), 0)

    def test_agent_panel(self):
        with self.page() as (page, d):
            page.click('#agentbtn')
            self.assertTrue(page.evaluate("document.body.classList.contains('agent-on')"))
            self.assertIn("chat is off", page.text_content('#ag-msgs'))
            # an MCP call (the same route the MCP server uses) shows under ACTIVITY
            page.evaluate("fetch('/api/tool',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({name:'key_check',args:{key:'C major'}})})")
            page.evaluate("AG.view='log'; refresh()")
            page.wait_for_function("$('ag-msgs').textContent.includes('key_check')")
            # the selection reaches the server for the tools
            page.evaluate("tab('pattern'); SEL={o:0,a:{row:0,ch:0},b:{row:1,ch:1}}; renderPat()")
            page.wait_for_function("fetch('/api/tool',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({name:'get_selection',args:{}})}).then(r=>r.json()).then(j=>j.rows&&j.rows[1]===1)")
            # settings are saved, the key never comes back to the page
            page.evaluate("AG.view='set'; renderAgent()")
            page.select_option('#ag-provider', 'openai')
            page.fill('#ag-key', 'secret-test-key')
            page.click("text=SAVE")
            page.wait_for_function("S.chat.settings.provider==='openai'")
            self.assertTrue(page.evaluate("S.chat.settings.has_key"))
            self.assertNotIn('secret-test-key', json.dumps(page.evaluate("S")))


if __name__ == '__main__':
    unittest.main()
