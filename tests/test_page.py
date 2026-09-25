"""The page (vulturetracker/gui.html): values from the song that reach the markup stay text. The static check runs
everywhere; the browser check drives the page in Playwright's Chromium (pip install playwright; VT_CHROMIUM names a
browser to use instead of Playwright's own) and is skipped without one."""
import os
import re
import tempfile
import threading
import time
import unittest
from pathlib import Path

from vulturetracker import gui
from vulturetracker.wavload import write_wav

from tests.test_gui import RATE, SONG_BLOCK, SONG_INS, sine

try:
    from playwright.sync_api import Error as PlaywrightError, sync_playwright
except ImportError:  # pragma: no cover
    sync_playwright = None

HTML = gui.HTML.read_text(encoding="utf-8")


class TestPage(unittest.TestCase):
    def test_values_in_inline_handlers_go_through_attr(self):
        # a value inside an inline handler (onclick="typeIn(this,...,"<value>")") is HTML first and JavaScript second:
        # `&quot;` in a song title decodes to a quote that ends the JavaScript string. attr() escapes the & as well.
        self.assertIn("const attr=x=>esc(JSON.stringify(x)).replace(/'/g,'&#39;')", HTML)
        self.assertNotIn(".replace(/\"/g,'&quot;')", HTML)
        self.assertEqual(len(re.findall(r"\.replace\(/'/g,'&#39;'\)", HTML)), 1)  # attr's own

    def test_a_name_with_an_entity_in_it_stays_text(self):
        if sync_playwright is None:
            self.skipTest("playwright not installed")
        title, chan = "x&quot;);alert(7);//", "c&quot;);alert(8);//"  # legal: 19 ASCII characters each
        text = SONG_BLOCK.replace("title: T", f"title: '{title}'").replace("- {name: A}", f"- {{name: '{chan}'}}")
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            write_wav(d / "a.wav", RATE, [sine(440)], root_note=69)
            write_wav(d / "b.wav", RATE, [sine(880)])
            (d / "song.yaml").write_bytes(text.encode("utf-8"))
            st = gui.Handler.state = gui.State(d / "song.yaml")
            self.assertIsNone(st.error)
            srv = gui._Server(("127.0.0.1", 0), gui.Handler)
            threading.Thread(target=srv.serve_forever, daemon=True).start()
            dialogs = []
            try:
                with sync_playwright() as p:
                    exe = os.environ.get("VT_CHROMIUM")
                    try:
                        browser = p.chromium.launch(**({"executable_path": exe} if exe else {}))
                    except PlaywrightError as e:
                        self.skipTest(f"no browser to drive the page with: {str(e).splitlines()[0]}")
                    page = browser.new_page()
                    page.on("dialog", lambda dlg: (dialogs.append(dlg.message), dlg.dismiss()))
                    page.goto(f"http://127.0.0.1:{srv.server_address[1]}/")
                    page.wait_for_function("typeof S !== 'undefined' && S && S.song && S.song.facts")
                    page.evaluate("tab('song')")
                    page.click("#song-mod .tv >> nth=0")   # the title, click to type
                    typed_title = page.input_value(".typein")
                    page.keyboard.press("Escape")
                    page.click("#song-ch .nm.tv >> nth=0")  # the channel name
                    typed_chan = page.input_value(".typein")
                    page.keyboard.press("Escape")
                    browser.close()
                self.assertEqual((dialogs, typed_title, typed_chan), ([], title, chan))
            finally:
                srv.shutdown()
                srv.server_close()
                gui.Handler.state = None
                for _ in range(400):  # the state's worker renders on its own thread: let it finish before the dir goes
                    if not (st.jobs.qsize() or any(r["status"] in ("queued", "rendering") for r in st.renders.values())):
                        break
                    time.sleep(0.05)

    def test_pattern_editing_in_the_page(self):
        # T3: the page's editing code in the browser: a note entered at the cursor from the piano keys, a channel
        # selected and transposed, copy and paste, humanize, an echo, undo; every change lands in the song file. And a notice the server
        # gives (a meta file it could not read) is shown once
        if sync_playwright is None:
            self.skipTest("playwright not installed")
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            write_wav(d / "a.wav", RATE, [sine(440)], root_note=69)
            write_wav(d / "b.wav", RATE, [sine(880)])
            song = d / "song.yaml"
            song.write_bytes(SONG_BLOCK.encode("utf-8"))
            (d / "song.tryout.json").write_text("{", encoding="utf-8")
            st = gui.Handler.state = gui.State(song)
            srv = gui._Server(("127.0.0.1", 0), gui.Handler)
            threading.Thread(target=srv.serve_forever, daemon=True).start()
            dialogs, text = [], lambda: song.read_bytes().decode("utf-8")  # noqa: E731
            try:
                with sync_playwright() as p:
                    exe = os.environ.get("VT_CHROMIUM")
                    try:
                        browser = p.chromium.launch(**({"executable_path": exe} if exe else {}))
                    except PlaywrightError as e:
                        self.skipTest(f"no browser to drive the page with: {str(e).splitlines()[0]}")
                    page = browser.new_page()
                    page.on("dialog", lambda dlg: (dialogs.append(dlg.message), dlg.dismiss()))
                    page.goto(f"http://127.0.0.1:{srv.server_address[1]}/")
                    page.wait_for_function("typeof S !== 'undefined' && S && S.song && S.song.facts")
                    page.evaluate("tab('pattern')")
                    page.wait_for_function("PAT.rows && PAT.rows.length === 4")
                    settle = lambda: page.wait_for_function("EDQ.n === 0 && PAT.key !== null")  # noqa: E731
                    page.evaluate("document.activeElement && document.activeElement.blur()")
                    page.keyboard.press("Escape")  # edit mode
                    page.evaluate("$('lv-oct').value = 5; setCursor(0, 1, 0, 0)")
                    page.keyboard.press("x")       # D-5 on the piano keys, with INS 01
                    settle()
                    self.assertIn("      01: D-5 01 ... ... | ... .. ... ...\n", text())
                    page.keyboard.press("Control+l")           # the whole channel
                    page.keyboard.press("Control+ArrowUp")     # a semitone up
                    settle()
                    self.assertIn("      00: C#5 01 ... ... | ... .. ... ...\n      01: D#5 01", text())
                    page.evaluate("SEL = null; setCursor(0, 0, 0, 0)")
                    page.keyboard.press("Control+c")
                    page.evaluate("setCursor(0, 3, 1, 0)")
                    page.keyboard.press("Control+v")
                    settle()
                    self.assertIn("      03: ... .. ... ... | C#5 01 ... ...\n", text())
                    page.evaluate("Math.random = () => 0; SEL = null; setCursor(0, 0, 0, 0); selHumanize()")  # the most down
                    settle()
                    self.assertIn("      00: C#5 01 v58 ... |", text())
                    # ECHO: the cursor's channel into a new channel on the right, one row later at half the volume
                    page.evaluate("SEL = null; setCursor(0, 0, 0, 0)")
                    page.select_option("#echo-to", "new:48")
                    page.fill("#echo-rows", "1")
                    page.fill("#echo-lvl", "50")
                    page.click("#selbar >> text=ECHO")
                    settle()
                    self.assertIn("    - {name: A echo, pan: 48}\n", text())
                    self.assertIn("      01: D#5 01 ... ... | ... .. ... ... | C#5 01 v29 ...\n", text())
                    self.assertIn("echo of channel 1 into new channel 3: 2 cells", page.text_content("#sel-msg"))
                    for _ in range(5):
                        page.keyboard.press("Control+z")
                        settle()
                    browser.close()
                self.assertEqual(text(), SONG_BLOCK)
                self.assertEqual(len(dialogs), 1)
                self.assertIn("song.tryout.json could not be read", dialogs[0])
            finally:
                srv.shutdown()
                srv.server_close()
                gui.Handler.state = None
                for _ in range(400):
                    if not (st.jobs.qsize() or any(r["status"] in ("queued", "rendering") for r in st.renders.values())):
                        break
                    time.sleep(0.05)

    def test_samples_tab_reports_and_resets_its_view(self):
        # SLICE's report shows in the Samples tab (it used to land in the Pattern tab's line), MULTISAMPLE + PATTERN reach
        # the server, and an edit that changes the length (STRETCH) shows the whole new WAV instead of the old view
        if sync_playwright is None:
            self.skipTest("playwright not installed")
        import numpy as np
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            write_wav(d / "a.wav", RATE, [sine(440)], root_note=69)
            write_wav(d / "b.wav", RATE, [sine(880)])
            hits = np.zeros(int(0.9 * RATE))
            for k, t0 in enumerate((0.0, 0.3, 0.6)):
                i = np.arange(int(0.29 * RATE))
                hits[int(t0 * RATE):int(t0 * RATE) + len(i)] = 0.6 * np.sin(2 * np.pi * 220 * 2 ** (k * 4 / 12) * i / RATE) * np.exp(-i / 2000)
            write_wav(d / "hits.wav", RATE, [np.round(hits * 32767).astype(int).tolist()])
            (d / "song.yaml").write_bytes(SONG_INS.replace("  2: {file: b.wav, name: B tone}\n",
                                                           "  2: {file: b.wav, name: B tone}\n  3: {file: hits.wav, name: Hits}\n").encode())
            st = gui.Handler.state = gui.State(d / "song.yaml")
            srv = gui._Server(("127.0.0.1", 0), gui.Handler)
            threading.Thread(target=srv.serve_forever, daemon=True).start()
            errors = []
            try:
                with sync_playwright() as p:
                    exe = os.environ.get("VT_CHROMIUM")
                    try:
                        browser = p.chromium.launch(**({"executable_path": exe} if exe else {}))
                    except PlaywrightError as e:
                        self.skipTest(f"no browser to drive the page with: {str(e).splitlines()[0]}")
                    page = browser.new_page(viewport={"width": 1400, "height": 900})
                    page.on("pageerror", lambda e: errors.append(str(e)))
                    page.goto(f"http://127.0.0.1:{srv.server_address[1]}/")
                    page.wait_for_function("typeof S !== 'undefined' && S && S.song && S.song.facts")
                    page.evaluate("tab('smp');SMP_SEL='3';renderSmp()")
                    page.wait_for_function("W.data && W.data.num === 3")
                    page.click("#t-smp span.btn:text-is('FIND')")
                    page.wait_for_function("W.slices && W.slices.points.length === 3")
                    page.select_option("#slc-as", "multi")
                    page.check("#slc-pat")
                    page.click("#t-smp span.btn:text-is('SLICE → SLOTS')")
                    page.wait_for_function("SMP_MSG.includes('pattern')", timeout=15000)
                    page.wait_for_function("!EDQ.n")
                    self.assertIn("plays each over the keys nearest its note (A-4, C#5, F-5)", page.inner_text("#smp-msg"))
                    self.assertEqual(page.inner_text("#sel-msg"), "")
                    self.assertIn("hits_slices", [pt.name for pt in st.mod.patterns])
                    page.evaluate("SMP_SEL='4';renderSmp()")
                    page.wait_for_function("W.data && W.data.num === 4")
                    frames = page.evaluate("W.data.frames")
                    page.evaluate("smpView(100, 2000)")
                    page.fill("#fx-stretch", "200")
                    page.click("#t-smp span.btn:text-is('STRETCH')")
                    page.wait_for_function(f"W.data && W.data.frames === {2 * frames} && W.a === 0 && W.b === {2 * frames}",
                                           timeout=20000)
                    browser.close()
                self.assertEqual(errors, [])
            finally:
                srv.shutdown()
                srv.server_close()
                gui.Handler.state = None
                st.close()
                for _ in range(400):
                    if not any(r["status"] in ("queued", "rendering") for r in st.renders.values()):
                        break
                    time.sleep(0.05)

    def test_faust_tab_renders_in_the_page(self):
        # the FAUST tab compiles the example in the page (faustwasm), shows its sliders, renders a note, uploads it as a
        # new slot with the note as its base note; a compile error is shown and the next compile works
        from vulturetracker import faust
        if sync_playwright is None or not faust.have():
            self.skipTest("needs playwright and faustwasm")
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            write_wav(d / "a.wav", RATE, [sine(440)])
            write_wav(d / "b.wav", RATE, [sine(880)])
            (d / "song.yaml").write_bytes(SONG_INS.encode())
            st = gui.Handler.state = gui.State(d / "song.yaml")
            srv = gui._Server(("127.0.0.1", 0), gui.Handler)
            threading.Thread(target=srv.serve_forever, daemon=True).start()
            errors = []
            try:
                with sync_playwright() as p:
                    exe = os.environ.get("VT_CHROMIUM")
                    try:
                        browser = p.chromium.launch(**({"executable_path": exe} if exe else {}))
                    except PlaywrightError as e:
                        self.skipTest(f"no browser to drive the page with: {str(e).splitlines()[0]}")
                    page = browser.new_page(viewport={"width": 1400, "height": 900})
                    page.on("pageerror", lambda e: errors.append(str(e)))
                    page.goto(f"http://127.0.0.1:{srv.server_address[1]}/")
                    page.wait_for_function("typeof S !== 'undefined' && S && S.song && S.song.facts")
                    page.evaluate("localStorage.removeItem('faustcode'); tab('faust')")
                    page.wait_for_function("$('fa-code').value.length > 0")
                    page.click("#t-faust span.btn:text-is('COMPILE')")
                    page.wait_for_function("FA.ctrls.length === 5", timeout=30000)
                    self.assertEqual(page.locator("#fa-ctrls input").count(), 2)  # cutoff and detune; freq, gate, gain set by the note
                    page.fill("#fa-note", "A-4")
                    page.fill("#fa-name", "saw")
                    page.click("#t-faust span.btn:text-is('→ NEW SLOT')")
                    page.wait_for_function("$('fa-msg').textContent.includes('new slot')", timeout=30000)
                    self.assertEqual(st.song["samples"][3], {"file": "faust-saw.wav", "name": "faust-saw", "stereo": True,
                                                             "base_note": "A-4"})
                    page.fill("#fa-code", "process = foo;")
                    page.click("#t-faust span.btn:text-is('COMPILE')")
                    page.wait_for_function("$('fa-err').textContent.includes('undefined symbol')")
                    page.click("#t-faust span.btn:text-is('EXAMPLE')")
                    page.wait_for_function("$('fa-err').textContent === '' && FA.ctrls.length === 5")
                    browser.close()
                self.assertEqual(errors, [])
            finally:
                srv.shutdown()
                srv.server_close()
                gui.Handler.state = None
                st.close()
                for _ in range(400):
                    if not any(r["status"] == "rendering" for r in st.renders.values()):
                        break
                    time.sleep(0.05)

    def test_record_tab_controls_hold_between_polls(self):
        # found on a real Scarlett: the tab polls ten times a second, and each poll rebuilt the takes table (a click on ▶
        # was lost between press and release) and put the open rate back into RATE (48000 could not be picked)
        if sync_playwright is None:
            self.skipTest("playwright not installed")
        import numpy as np
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            write_wav(d / "a.wav", RATE, [sine(440)], root_note=69)
            write_wav(d / "b.wav", RATE, [sine(880)])
            (d / "song.yaml").write_bytes(SONG_BLOCK.encode("utf-8"))
            os.environ["VT_FAKE_AUDIO"] = "1"
            st = gui.Handler.state = gui.State(d / "song.yaml")
            srv = gui._Server(("127.0.0.1", 0), gui.Handler)
            threading.Thread(target=srv.serve_forever, daemon=True).start()
            try:
                with sync_playwright() as p:
                    exe = os.environ.get("VT_CHROMIUM")
                    try:
                        browser = p.chromium.launch(**({"executable_path": exe} if exe else {}))
                    except PlaywrightError as e:
                        self.skipTest(f"no browser to drive the page with: {str(e).splitlines()[0]}")
                    page = browser.new_page()
                    page.goto(f"http://127.0.0.1:{srv.server_address[1]}/")
                    page.wait_for_function("typeof S !== 'undefined' && S && S.song && S.song.facts")
                    page.evaluate("tab('rec')")
                    page.wait_for_function("REC.st && REC.st.devices && REC.st.devices.length")
                    page.click("#rec-open")
                    page.wait_for_function("REC.st.status.open && REC.st.status.rate === 44100")
                    t = np.arange(RATE) / RATE
                    st.save_take((0.5 * np.sin(2 * np.pi * 196 * t))[None], RATE, {"name": "pluck", "dest": "keep"})
                    page.wait_for_function("document.querySelector('#rec-takes .btn')")
                    play = page.query_selector("#rec-takes .btn")
                    time.sleep(0.5)  # five polls
                    self.assertTrue(play.evaluate("e => e.isConnected"))
                    page.select_option("#rec-rate", "48000")  # reopens at the new rate
                    page.wait_for_function("REC.st.status.open && REC.st.status.rate === 48000")
                    time.sleep(0.3)
                    self.assertEqual(page.input_value("#rec-rate"), "48000")
                    browser.close()
            finally:
                srv.shutdown()
                srv.server_close()
                if gui.Handler.recorder:
                    gui.Handler.recorder.close()
                gui.Handler.state = gui.Handler.recorder = gui.Handler.rec_devices = None
                os.environ.pop("VT_FAKE_AUDIO", None)
                st.close()


if __name__ == "__main__":
    unittest.main()
