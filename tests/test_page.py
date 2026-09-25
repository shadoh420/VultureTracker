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

from tests.test_gui import RATE, SONG_BLOCK, sine

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


if __name__ == "__main__":
    unittest.main()
