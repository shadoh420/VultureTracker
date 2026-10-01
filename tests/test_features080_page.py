"""0.8.0 features in Chromium on a disposable song: OpenMPT's clipboard both ways. The native paste writes the system
clipboard (the owner's clipboard, when run on the desktop)."""
import os
os.environ['VT_WORKERS'] = '1'
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

from playwright.sync_api import sync_playwright
from vulturetracker import gui
from vulturetracker.wavload import write_wav
from tests.test_gui import SONG_BLOCK, sine, RATE


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
                    lacking = page.evaluate("fromModPlug('ModPlug Tracker  IT\\r\\n|PC 01u05O10|C-5:0v80...\\r\\n')")
                    self.assertEqual(lacking, {'rows': [[{'n': '...', 'i': '01', 'v': '...', 'e': 'O10'},
                                                         {'n': 'C-5', 'i': '..', 'v': '...', 'e': '...'}]], 'bad': 4})
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
                    # MIX (Ctrl+Shift+V): OpenMPT rows fill only the empty fields
                    page.evaluate("t=>navigator.clipboard.writeText(t)", 'ModPlug Tracker  IT\r\n|F-503v10...|G-503......\r\n')
                    page.evaluate('CUR.row=2;CUR.ch=0;renderPat()')
                    page.keyboard.press('Control+Shift+V')
                    page.wait_for_function("!EDQ.n && PAT.rows[2][0].startsWith('F-5')", timeout=5000)
                    self.assertEqual(page.evaluate('PAT.rows[2].join(" | ")'), 'F-5 03 v10 ... | C-5 02 ... ...')
                    # a key whose paste event never comes (a synthetic one here): the page reads the clipboard itself
                    page.evaluate("t=>navigator.clipboard.writeText(t)", 'ModPlug Tracker  IT\r\n|A-504......\r\n')
                    page.evaluate("CUR.row=3;CUR.ch=0;renderPat();document.dispatchEvent(new KeyboardEvent('keydown',{key:'v',ctrlKey:true,bubbles:true}))")
                    page.wait_for_function("!EDQ.n && PAT.rows[3][0].startsWith('A-5 04')", timeout=5000)
                    # and back: Ctrl+C puts OpenMPT's format on the system clipboard
                    page.evaluate("SEL={o:0,a:{row:0,ch:0,col:0},b:{row:1,ch:1,col:4}};renderPat()")
                    page.keyboard.press('Control+C')
                    page.wait_for_timeout(100)
                    self.assertEqual(page.evaluate('navigator.clipboard.readText()'),
                                     'ModPlug Tracker  IT\r\n|D-502v32...|...........\r\n|===........|E-501...B..\r\n')
                    # the computer's piano keys with CHORD: two keys struck together go in as one chord on key up...
                    page.evaluate("SEL=null;$('midi-chord').checked=true;CUR.row=2;CUR.ch=0;CUR.col=0;renderPat()")
                    z, x, c = page.evaluate("['z','x','c'].map(k=>noteTxt(pianoNote(k)))")
                    page.keyboard.down('c')
                    page.keyboard.down('z')
                    page.wait_for_timeout(150)
                    self.assertEqual(page.evaluate('PAT.rows[2][0]'), '... .. ... ...')  # still held
                    page.keyboard.up('z')
                    page.keyboard.up('c')
                    page.wait_for_function(f"!EDQ.n && PAT.rows[2][1].startsWith('{c}')")
                    self.assertTrue(page.evaluate(f"PAT.rows[2][0].startsWith('{z}') && CUR.row===3"))
                    # ...and a key struck 150 ms after another, still held, is a note of its own on the next row
                    page.evaluate('CUR.row=0;renderPat()')
                    page.keyboard.down('z')
                    page.wait_for_timeout(150)
                    page.keyboard.down('x')
                    page.keyboard.up('z')
                    page.keyboard.up('x')
                    page.wait_for_function(f"!EDQ.n && PAT.rows[1][0].startsWith('{x}')")
                    self.assertEqual(page.evaluate('[PAT.rows[0][0].slice(0,3),PAT.rows[0][1],CUR.row]'), [z, '... .. ... ...', 2])
                    self.assertEqual(errors, [])
                    browser.close()
            finally:
                server.shutdown()
                server.server_close()
                st.close()
                gui.Handler.state = old_state


if __name__ == '__main__':
    unittest.main()
