"""1.0 in Chromium on disposable songs: the version, UI SCALE, section RENAME, a dropped FLAC, the FAUST tab's saves, draft,
pedal and let-go. Each confirms its edit in the files beside the song."""
import base64
import contextlib
import json
import os
os.environ['VT_WORKERS'] = '1'
import subprocess
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

try:
    from playwright.sync_api import Error as PlaywrightError, sync_playwright
except ImportError:  # pragma: no cover
    sync_playwright = None
from vulturetracker import __version__, faust, gui
from vulturetracker.wavload import write_wav
from tests.test_gui import SONG, SONG_INS, sine, RATE

LEVEL = ("(()=>{const a=FA.an,x=new Float32Array(a.fftSize);a.getFloatTimeDomainData(x);let m=0;"
         "for(const v of x)m=Math.max(m,Math.abs(v));return m})()")


def _tmpdir(self):  # TestCase.enterContext is 3.11+; the floor is 3.10
    d = tempfile.TemporaryDirectory()
    self.addCleanup(d.cleanup)
    return d.name


@unittest.skipIf(sync_playwright is None, 'playwright not installed')
class TestRelease100Page(unittest.TestCase):
    @contextlib.contextmanager
    def page(self, text=SONG, width=1400, height=900):
        """(page, state, folder) of a song made from `text` served on its own; page errors fail the test."""
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(gui, 'remember_song'):
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
                    page = browser.new_page(viewport={'width': width, 'height': height})
                    page.on('pageerror', lambda e: errors.append(str(e)))
                    page.goto(f'http://127.0.0.1:{srv.server_address[1]}/')
                    page.wait_for_function("typeof S !== 'undefined' && S && S.song && S.song.facts")
                    page.evaluate("localStorage.removeItem('uiscale'); localStorage.removeItem('faustcode')")
                    yield page, gui.Handler.state, d
                    browser.close()
                self.assertEqual(errors, [])
            finally:
                srv.shutdown()
                srv.server_close()
                for s in {st, gui.Handler.state}:
                    if s:
                        s.close()
                gui.Handler.state = None

    def test_version_ui_scale_and_section_rename(self):
        text = SONG + 'sections:\n  intro: [0, 1]  # the start\n'
        with self.page(text) as (page, st, d):
            self.assertEqual(page.title(), f'VultureTracker {__version__}')
            page.select_option('.top .uiscale', '150')
            self.assertEqual(page.evaluate("[document.documentElement.style.zoom, localStorage.uiscale, browserSettings().local.uiscale]"),
                             ['1.5', '150', '150'])
            # the app still fits the window: the transport at the bottom is on screen
            self.assertLessEqual(page.evaluate("$('playbtn').getBoundingClientRect().bottom"), 900)
            # a click lands on the cell under the pointer, and the typed note is written there
            page.evaluate("tab('pattern'); setEdit(true)")
            page.wait_for_function("PAT.rows && document.querySelector('#pat .pt[data-r=\"2\"] .pc')")
            page.click('#pat .pt[data-r="2"] .pc >> nth=0', position={'x': 4, 'y': 5})  # its note column
            self.assertEqual(page.evaluate('[CUR.row, CUR.ch, CUR.col]'), [2, 0, 0])
            page.evaluate('document.activeElement.blur()')
            page.keyboard.press('KeyZ')  # C at OCT 5
            page.wait_for_function("PAT.rows[2][0].startsWith('C-5') && !S.song.dirty")
            for _ in range(100):  # the edit's write follows the page's own update
                if '02: C-5 01' in (d / 'song.yaml').read_text(encoding='utf-8'):
                    break
                time.sleep(0.05)
            self.assertIn('02: C-5 01', (d / 'song.yaml').read_text(encoding='utf-8'))
            # a typed value's field sits on the value it edits
            left = page.evaluate("(()=>{const el=document.querySelector('#songmeta');typeIn(el,0,9,()=>{},'1');"
                                 "const i=document.querySelector('.typein'),r=[i.getBoundingClientRect().left,el.getBoundingClientRect().left];i.blur();return r})()")
            self.assertAlmostEqual(left[0], left[1], delta=2)
            # RENAME in SONG's named sections
            page.evaluate("tab('song')")
            page.wait_for_function("$('section-select').options.length === 1")
            page.fill('#section-name', 'Opening')
            page.click("button:text-is('RENAME')")
            page.wait_for_function("S.sections && S.sections.Opening")
            self.assertIn('"Opening": [0, 1]  # the start', (d / 'song.yaml').read_text(encoding='utf-8'))
            page.reload()  # the scale is kept in this browser
            page.wait_for_function("typeof S !== 'undefined' && S && S.song")
            self.assertEqual(page.evaluate("document.documentElement.style.zoom"), '1.5')

    def test_transport_controls_stay_inside_the_bottom_panel(self):
        with self.page() as (page, st, d):
            for width, scale, agent_open in [(1400, 100, False), (1180, 100, False),
                                              (1400, 100, True), (1180, 125, True), (1400, 150, True)]:
                with self.subTest(width=width, scale=scale, agent=agent_open):
                    page.set_viewport_size({'width': width, 'height': 900})
                    failures = page.evaluate("""([scale,agentOpen])=>{
                      setScale(scale);document.body.classList.toggle('agent-on',agentOpen);
                      $('outnums').textContent='-24.0 LUFS · TP -15.7 · CORR 0.97';
                      $('nowname').textContent='the song as it is';
                      const panel=document.querySelector('.bottom').getBoundingClientRect();
                      return [...document.querySelectorAll('.bottom .btn,.bottom select,.bottom .nowrow,.bottom .prog,.bottom #live')]
                        .filter(el=>{const r=el.getBoundingClientRect();return r.top<panel.top-1||r.bottom>panel.bottom+1||r.left<panel.left-1||r.right>panel.right+1})
                        .map(el=>el.id||el.textContent.trim());
                    }""", [scale, agent_open])
                    self.assertEqual(failures, [])

    def test_a_dropped_flac_becomes_a_slot(self):
        try:
            ffmpeg = gui.ffmpeg_exe()
        except OSError:
            self.skipTest('needs ffmpeg')
        with self.page() as (page, st, d):
            src = Path(_tmpdir(self)) / 'kick.flac'
            subprocess.run([ffmpeg, '-loglevel', 'error', '-i', str(d / 'a.wav'), '-metadata', 'LOOPSTART=10',
                            '-metadata', 'LOOPLENGTH=90', str(src)], check=True)
            page.evaluate("tab('smp')")
            page.evaluate("""b64=>{const bin=atob(b64),u=new Uint8Array(bin.length);for(let i=0;i<bin.length;i++)u[i]=bin.charCodeAt(i);
                const dt=new DataTransfer();dt.items.add(new File([u],'kick.flac'));
                document.querySelector('#t-smp [ondrop*="sample_new"]').dispatchEvent(new DragEvent('drop',{dataTransfer:dt,bubbles:true,cancelable:true}))}""",
                          base64.b64encode(src.read_bytes()).decode())
            page.wait_for_function("Object.keys(S.song.sample_entries).length === 3", timeout=10000)
            self.assertIn('file: kick.wav', (d / 'song.yaml').read_text(encoding='utf-8'))
            from vulturetracker.wavload import read_wav
            self.assertEqual(read_wav(d / 'kick.wav').loops, [(10, 100, False)])

    @unittest.skipUnless(faust.have(), 'needs faustwasm')
    def test_faust_saves_its_recipe_keeps_its_code_per_song_and_holds_the_pedal(self):
        with self.page(SONG_INS) as (page, st, d):
            other = d / 'other'
            other.mkdir()
            write_wav(other / 'a.wav', RATE, [sine(440)])
            write_wav(other / 'b.wav', RATE, [sine(880)])
            (other / 'song.yaml').write_bytes(SONG_INS.encode())
            page.evaluate("tab('faust')")
            page.wait_for_function("$('fa-code').value.length > 0")
            page.click("#t-faust span.btn:text-is('COMPILE')")
            page.wait_for_function("FA.node && FA.nodeCode === $('fa-code').value", timeout=30000)
            code = page.evaluate("$('fa-code').value")
            # the code being typed is kept with the song
            mine = code.replace('0.3, 0, 2', '0.4, 0, 2')
            page.fill('#fa-code', mine)
            for _ in range(100):  # written half a second after the typing stops
                if (d / 'song.tryout.json').exists() and json.loads((d / 'song.tryout.json').read_text(encoding='utf-8')).get('faust_code') == mine:
                    break
                time.sleep(0.05)
            self.assertEqual(json.loads((d / 'song.tryout.json').read_text(encoding='utf-8'))['faust_code'], mine)
            page.evaluate(f"openSong({json.dumps(str(other / 'song.yaml'))})")
            page.wait_for_function(f"S.song && S.song.path === {json.dumps(str((other / 'song.yaml').resolve()))} && $('fa-code').value.length > 0")
            self.assertEqual(page.evaluate("$('fa-code').value"), code)  # its own: the example
            page.evaluate(f"openSong({json.dumps(str(d / 'song.yaml'))})")
            page.wait_for_function(f"$('fa-code').value === {json.dumps(mine)}")
            # a save writes its faust: entry
            page.fill('#fa-note', 'A-4')
            page.fill('#fa-name', 'saw')
            page.click("#t-faust span.btn:text-is('→ NEW SLOT')")
            page.wait_for_function("$('fa-msg').textContent.includes('faust.yaml')", timeout=30000)
            self.assertIn('file: faust-saw.wav', (d / 'song.yaml').read_text(encoding='utf-8'))
            recipe = (d / 'faust.yaml').read_text(encoding='utf-8')
            self.assertIn('  faust-saw:\n    faust: |-\n      import("stdfaust.lib");', recipe)
            self.assertIn('detune = hslider("detune", 0.4, 0, 2, 0.01);', recipe)
            self.assertIn('    note: A-4\n    hold: 1.0\n    tail: 0.5\n    velocity: 100\n', recipe)
            # the sustain pedal holds a note let go; let up, the note is released
            page.wait_for_function("FA.node && FA.nodeCode === $('fa-code').value", timeout=30000)
            page.evaluate("FA.an = PK.ctx.createAnalyser(); FA.node.connect(FA.an); MIDI.on = true;"
                          "midiMsg([0x90, 60, 100]); midiMsg([0xB0, 64, 127]); midiMsg([0x80, 60, 0])")
            time.sleep(0.8)
            self.assertTrue(page.evaluate(f"!!FA.held.m60 && FA.sus.has('m60') && {LEVEL} > 0.02"))
            page.evaluate("midiMsg([0xB0, 64, 0])")
            page.wait_for_function(f"!FA.held.m60 && {LEVEL} < 1e-3", timeout=5000)
            # leaving the tab releases the notes on their own release, not cut at once
            page.evaluate("midiMsg([0x90, 64, 100])")
            page.wait_for_function(f"{LEVEL} > 0.05", timeout=5000)
            levels = page.evaluate(f"""(async()=>{{tab('pattern');const out=[];for(let i=0;i<14;i++){{await new Promise(r=>setTimeout(r,30));
                out.push({LEVEL})}}return out}})()""")
            self.assertGreater(max(levels[1:]), 0.005, levels)  # sounding on after the first 30 ms: the release is 0.4 s
            self.assertGreater(levels[0], levels[-1], levels)  # and falling
            page.wait_for_function(f"{LEVEL} < 1e-3", timeout=5000)
            page.evaluate("midiMsg([0x80, 64, 0])")


if __name__ == '__main__':
    unittest.main()
