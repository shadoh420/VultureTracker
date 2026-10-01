"""0.8.0 features in Chromium on a disposable song: OpenMPT's clipboard both ways, chords from the computer keyboard.
Headless Chromium and Edge keep a clipboard of their own: the desktop's is left alone (checked 2026-10-01)."""
import os
os.environ['VT_WORKERS'] = '1'
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

try:
    from playwright.sync_api import sync_playwright
except ImportError:  # pragma: no cover
    sync_playwright = None
from vulturetracker import gui
from vulturetracker.wavload import write_wav
from tests.test_gui import SONG_BLOCK, sine, RATE


@unittest.skipIf(sync_playwright is None, 'playwright not installed')
class TestFeatures080Page(unittest.TestCase):
    def test_openmpt_clipboard_both_ways(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(gui, 'remember_song'):
            folder = Path(tmp)
            for name, hz in [('a', 440), ('b', 880)]:
                write_wav(folder / (name + '.wav'), RATE, [sine(hz)])
            song = folder / 'song.yaml'
            song.write_bytes(SONG_BLOCK.encode())
            old_state = gui.Handler.state
            st = gui.Handler.state = gui.State(song)
            server = gui._Server(('127.0.0.1', 0), gui.Handler)
            threading.Thread(target=server.serve_forever, daemon=True).start()
            errors = []
            try:
                with sync_playwright() as pw:
                    browser = pw.chromium.launch(executable_path=os.environ.get('VT_CHROMIUM') or None)
                    url = f'http://127.0.0.1:{server.server_address[1]}/'
                    context = browser.new_context(viewport={'width': 1700, 'height': 1100})
                    context.grant_permissions(['clipboard-read', 'clipboard-write'], origin=url[:-1])
                    page = context.new_page()
                    page.on('pageerror', lambda e: errors.append(str(e)))
                    page.goto(url)
                    page.wait_for_function('S?.song?.facts && PAT.rows')
                    # the format: spaces for columns outside the selection, a parameter of 0 as '..'
                    text = page.evaluate("toModPlug({rows:[[{n:'C#5',i:'01',v:'v64',e:'C00'},{e:'A06'}],[,{n:'==='}]]})")
                    self.assertEqual(text, 'ModPlug Tracker  IT\r\n|C#501v64C..|        A06\r\n|           |===        \r\n')
                    back = page.evaluate('t=>fromModPlug(t)', text)
                    self.assertEqual(back, {'rows': [[{'n': 'C#5', 'i': '01', 'v': 'v64', 'e': 'C00'}, {'e': 'A06'}],
                                                     [{}, {'n': '==='}]], 'bad': 0})
                    # audit-100 C7: an MPTM PC event pasted its plugin number as an instrument; OpenMPT turns it into Zxx
                    # (ModCommand::Convert: the value 000-999 scaled to 00-7F, the rest of the cell empty)
                    lacking = page.evaluate("fromModPlug('ModPlug Tracker  IT\\r\\n|PC 01u05O10|C-5:0v80...\\r\\n')")
                    self.assertEqual(lacking, {'rows': [[{'n': '...', 'i': '..', 'v': '...', 'e': 'Z00'},
                                                         {'n': 'C-5', 'i': '..', 'v': '...', 'e': '...'}]], 'bad': 2})
                    pc = page.evaluate("fromModPlug('ModPlug Tracker MPT\\r\\n|PCs01000500|C-501v64...|PC 02000999\\r\\n')")
                    self.assertEqual(pc, {'rows': [[{'n': '...', 'i': '..', 'v': '...', 'e': 'Z3F'},
                                                    {'n': 'C-5', 'i': '01', 'v': 'v64', 'e': '...'},
                                                    {'n': '...', 'i': '..', 'v': '...', 'e': 'Z7F'}]], 'bad': 0})
                    self.assertIn('error', page.evaluate("fromModPlug('ModPlug Tracker  XM\\r\\n|C-501.........\\r\\n')"))
                    self.assertIsNone(page.evaluate("fromModPlug('C-5 01 ... ... | ... .. ... ...')"))
                    # rows copied in OpenMPT (two patterns: the first pastes), pasted with a real Ctrl+V
                    page.click('[data-t="pattern"]')
                    page.evaluate('setEdit(true);CUR.o=0;CUR.row=0;CUR.ch=0;CUR.col=0;renderPat()')
                    page.evaluate("t=>navigator.clipboard.writeText(t)", 'ModPlug Tracker  IT\r\nOrders: 0,1\r\nRows: 2\r\n'
                                  '|D-502v32...|...........\r\n|===........|E-501...B..\r\nRows: 1\r\n|F-501......|...........\r\n')
                    page.keyboard.press('Control+V')
                    page.wait_for_function("!EDQ.n && PAT.rows[1][1].startsWith('E-5')")
                    self.assertEqual(page.evaluate('PAT.rows.slice(0,3).map(r=>r.join(" | "))'),
                                     ['D-5 02 v32 ... | ... .. ... ...', '=== .. ... ... | E-5 01 ... B00',
                                      '... .. ... ... | C-5 02 ... ...'])
                    self.assertIn('D-5 02 v32 ...', song.read_text())
                    # MIX (Ctrl+Shift+V): OpenMPT rows fill only the empty fields (the song file shows the server took it)
                    page.evaluate("t=>navigator.clipboard.writeText(t)", 'ModPlug Tracker  IT\r\n|F-501v10...|G-502......\r\n')
                    page.evaluate('CUR.row=2;CUR.ch=0;renderPat()')
                    page.keyboard.press('Control+Shift+V')
                    page.wait_for_function("!EDQ.n && PAT.rows[2][0].startsWith('F-5')")
                    self.assertIn('F-5 01 v10 ... | C-5 02 ... ...', song.read_text())
                    # and back: Ctrl+C puts OpenMPT's format on the system clipboard
                    page.evaluate("SEL={o:0,a:{row:0,ch:0,col:0},b:{row:1,ch:1,col:4}};renderPat()")
                    page.keyboard.press('Control+C')
                    page.wait_for_timeout(100)
                    self.assertEqual(page.evaluate('navigator.clipboard.readText()'),
                                     'ModPlug Tracker  IT\r\n|D-502v32...|...........\r\n|===........|E-501...B..\r\n')
                    # the computer's piano keys with CHORD (OpenMPT's way): keys struck together go in as one chord, written
                    # 60 ms after the last, while they are still held
                    page.evaluate("SEL=null;$('midi-chord').checked=true;CUR.row=2;CUR.ch=0;CUR.col=0;renderPat()")
                    z, x, c, two = page.evaluate("['z','x','c','2'].map(k=>noteTxt(pianoNote(k)))")
                    page.keyboard.down('c')
                    page.keyboard.down('z')
                    page.wait_for_function(f"!EDQ.n && PAT.rows[2][1].startsWith('{c}')")
                    self.assertTrue(page.evaluate(f"PAT.rows[2][0].startsWith('{z}') && CUR.row===3"))
                    self.assertIn(page.evaluate('PAT.rows[2].join(" | ")'), song.read_text())  # the server took it
                    page.keyboard.up('z')
                    page.keyboard.up('c')
                    # a key struck 150 ms after another is a note of its own on the next row
                    page.evaluate('CUR.row=0;renderPat()')
                    page.keyboard.down('z')
                    page.wait_for_timeout(150)
                    page.keyboard.down('x')
                    page.keyboard.up('z')
                    page.keyboard.up('x')
                    page.wait_for_function(f"!EDQ.n && PAT.rows[1][0].startsWith('{x}')")
                    self.assertIn(page.evaluate('PAT.rows[1].join(" | ")'), song.read_text())
                    self.assertEqual(page.evaluate('[PAT.rows[0][0].slice(0,3),PAT.rows[0][1],CUR.row]'), [z, '... .. ... ...', 2])
                    # Shift held (OpenMPT's chord modifier): keys struck any time apart join one chord, written when Shift
                    # is let go; Shift+2 types '@' but is still the 2
                    page.evaluate('CUR.row=3;renderPat()')
                    held = page.evaluate('PAT.rows[3].join(" | ")')
                    page.keyboard.down('Shift')
                    page.keyboard.press('z')
                    page.wait_for_timeout(150)
                    page.keyboard.press('2')
                    page.wait_for_timeout(150)
                    self.assertEqual(page.evaluate('PAT.rows[3].join(" | ")'), held)  # nothing written while Shift is held
                    page.keyboard.up('Shift')
                    page.wait_for_function(f"!EDQ.n && PAT.rows[3][1].startsWith('{two}')")
                    self.assertTrue(page.evaluate(f"PAT.rows[3][0].startsWith('{z}')"))
                    self.assertIn(page.evaluate('PAT.rows[3].join(" | ")'), song.read_text())
                    self.assertEqual(errors, [])
                    browser.close()
            finally:
                server.shutdown()
                server.server_close()
                st.close()
                gui.Handler.state = old_state

    def test_a_rolled_chord_is_one_chord(self):
        # audit-100 C8: OpenMPT's auto-chord wait (60 ms, View_pat.cpp) starts again at every note, so keys or MIDI notes
        # 30 ms apart are one chord however long the roll; the window used to be 50 ms from the first note
        four = ("module:\n  title: T\n  tempo: 125\n  speed: 6\n  channels:\n" + "".join(f"    - {{name: {c}}}\n" for c in "ABCD")
                + "samples:\n  1: {file: a.wav, name: A tone}\npatterns:\n  p1:\n    rows: 8\n    data: |\n"
                + "".join(f"      {r:02d}: " + " | ".join(["... .. ... ..."] * 4) + "\n" for r in range(8)) + "orders: [p1]\n")
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(gui, 'remember_song'):
            folder = Path(tmp)
            for name, hz in [('a', 440), ('b', 880)]:
                write_wav(folder / (name + '.wav'), RATE, [sine(hz)])
            song = folder / 'song.yaml'
            song.write_bytes(four.encode())
            old_state = gui.Handler.state
            st = gui.Handler.state = gui.State(song)
            server = gui._Server(('127.0.0.1', 0), gui.Handler)
            threading.Thread(target=server.serve_forever, daemon=True).start()
            errors = []
            try:
                with sync_playwright() as pw:
                    browser = pw.chromium.launch(executable_path=os.environ.get('VT_CHROMIUM') or None)
                    page = browser.new_page(viewport={'width': 1700, 'height': 1100})
                    page.on('pageerror', lambda e: errors.append(str(e)))
                    page.goto(f'http://127.0.0.1:{server.server_address[1]}/')
                    page.wait_for_function('S?.song?.facts && PAT.rows')
                    page.click('[data-t="pattern"]')
                    page.evaluate("setEdit(true);$('midi-chord').checked=true;$('lv-step').value=1;$('lv-oct').value=5;"
                                  "CUR.o=0;CUR.row=0;CUR.ch=0;CUR.col=0;renderPat()")
                    page.evaluate("""async()=>{const gap=()=>new Promise(r=>setTimeout(r,30));
                        for(const k of 'zxcv'){document.dispatchEvent(new KeyboardEvent('keydown',{key:k,code:'Key'+k.toUpperCase(),bubbles:true,cancelable:true}));await gap()}}""")
                    page.wait_for_function("!MIDI.pending && !EDQ.n")
                    self.assertEqual(page.evaluate("PAT.rows.slice(0,2).map(r=>r.map(c=>c.slice(0,3)).join(' '))"),
                                     ['C-5 D-5 E-5 F-5', '... ... ... ...'])
                    page.evaluate("""async()=>{MIDI.on=true;CUR.row=2;const gap=()=>new Promise(r=>setTimeout(r,30));
                        for(const n of [67,64,60,72]){midiMsg([0x90,n,100]);await gap()}}""")  # MIDI: the same wait
                    page.wait_for_function("!MIDI.pending && !EDQ.n")
                    self.assertEqual(page.evaluate("PAT.rows.slice(2,4).map(r=>r.map(c=>c.slice(0,3)).join(' '))"),
                                     ['C-5 E-5 G-5 C-6', '... ... ... ...'])
                    self.assertIn('C-5 01 v50 ... | E-5 01 v50 ... | G-5 01 v50 ... | C-6 01 v50 ...', song.read_text())
                    self.assertEqual(errors, [])
                    browser.close()
            finally:
                server.shutdown()
                server.server_close()
                st.close()
                gui.Handler.state = old_state


if __name__ == '__main__':
    unittest.main()
