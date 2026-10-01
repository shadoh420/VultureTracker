"""0.8.0 page regressions in Chromium on disposable songs."""
import os
os.environ['VT_WORKERS'] = '1'
import tempfile
import threading
import time
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
class TestRelease080Page(unittest.TestCase):
    def test_tryout_keys_stay_out_of_the_pattern_tab_and_new_song_waits_for_edits(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(gui, 'remember_song'):
            folder = Path(tmp)
            for name, hz in [('a', 440), ('b', 880), ('cand', 660), ('cand2', 330)]:
                write_wav(folder / (name + '.wav'), RATE, [sine(hz)])
            song = folder / 'song.yaml'
            song.write_bytes(SONG_BLOCK.encode())
            original = song.read_bytes()
            old_state = gui.Handler.state
            first = gui.Handler.state = gui.State(song)
            first.meta['slot'] = 1
            first.add_candidates('cand*.wav')
            server = gui._Server(('127.0.0.1', 0), gui.Handler)
            threading.Thread(target=server.serve_forever, daemon=True).start()
            errors = []
            try:
                with sync_playwright() as pw:
                    browser = pw.chromium.launch(executable_path=os.environ.get('VT_CHROMIUM') or None)
                    page = browser.new_page(viewport={'width': 1700, 'height': 1100})
                    page.on('pageerror', lambda e: errors.append(str(e)))
                    page.goto(f'http://127.0.0.1:{server.server_address[1]}/')
                    page.wait_for_function('S?.song?.facts && PAT.rows && S.candidates.length===2')
                    picked = page.evaluate('pick(S.candidates[1].id);sel')
                    page.click('[data-t="pattern"]')
                    # edit mode, instrument column: letters it does not use were the Tryout's apply, reject, note, alone
                    page.evaluate('setEdit(true);CUR.o=0;CUR.row=0;CUR.ch=0;CUR.col=1;renderPat()')
                    for combo in ('u', 'Control+u', 'Alt+u'):
                        page.keyboard.press(combo)
                        page.wait_for_timeout(500)  # the diff U opened arrives, then Enter applied it
                        page.keyboard.press('Enter')
                    for key in ('x', 'n', 's', 'm', 'Alt+x', 'Control+n'):
                        page.keyboard.press(key)
                    page.evaluate('setEdit(false)')
                    for key in ('1', '4', '0'):  # not piano keys: were the Tryout's candidate picks
                        page.keyboard.press(key)
                    page.wait_for_timeout(600)
                    self.assertFalse(page.evaluate("$('diffmodal').classList.contains('on')"))
                    self.assertEqual(page.evaluate('sel'), picked)
                    self.assertEqual(song.read_bytes(), original)
                    self.assertFalse(any(c['rejected'] for c in first.snapshot()['candidates']))
                    self.assertEqual(first.notes, [])
                    # an edit still queued when NEW SONG is pressed lands in the song it was made in
                    fresh = folder / 'fresh.yaml'
                    page.evaluate("""(p)=>{setEdit(true);EDQ.chain=EDQ.chain.then(()=>new Promise(r=>setTimeout(r,800)));
                        patEdit([{row:1,ch:0,cell:'G-5 01 ... ...'}]);$('newpath').value=p;newSong()}""", str(fresh))
                    for _ in range(200):
                        if gui.Handler.state is not first and page.evaluate('!EDQ.n'):
                            break
                        time.sleep(0.05)
                    new = gui.Handler.state
                    self.assertIsNot(new, first)
                    self.assertEqual(first.mod.patterns[0].rows[1][0].note, 67)
                    self.assertIsNone(new.mod.patterns[0].rows[1][0].note)
                    self.assertEqual(len(new.history), 0)
                    # a live chord whose second note lands after the next row began is still one chord, on the first row
                    page.wait_for_function('PAT.rows?.length===64')
                    page.evaluate("MIDI.on=true;setEdit(true);CUR.ch=0;CUR.row=0;$('midi-chord').checked=true")
                    page.evaluate("""async()=>{lvMsg({type:'pos',playing:true,order:0,row:1,vu:[0,0]});midiMsg([0x90,62,100]);
                        await new Promise(r=>setTimeout(r,20));lvMsg({type:'pos',playing:true,order:0,row:2,vu:[0,0]});
                        midiMsg([0x90,65,100]);await new Promise(r=>setTimeout(r,200));LV.playing=false}""")
                    page.wait_for_function("!EDQ.n && PAT.rows[1][1].startsWith('F-5')")
                    self.assertEqual(len(new.history), 1)
                    self.assertTrue(page.evaluate("PAT.rows[2].every(c=>c.startsWith('...'))"))
                    # the cursor on a pattern made shorter under it, then a note with OCT typed out of range
                    page.evaluate("setEdit(true);setCursor(0,63,0,0);songEdit([{op:'pattern_rows',name:'p00',rows:8}])")
                    page.wait_for_function('PAT.rows?.length===8 && !EDQ.n')
                    self.assertEqual(page.evaluate('CUR.row'), 7)
                    page.evaluate("$('lv-oct').value='-1'")
                    page.keyboard.press('z')
                    page.wait_for_function("!EDQ.n && PAT.rows[7][0].startsWith('C-0')")
                    self.assertEqual(errors, [])
                    browser.close()
            finally:
                server.shutdown()
                server.server_close()
                first.close()
                if gui.Handler.state is not first:
                    gui.Handler.state.close()
                gui.Handler.state = old_state


    def test_page_does_what_the_guide_says(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(gui, 'remember_song'):
            folder = Path(tmp)
            for name, hz in [('a', 440), ('b', 880)]:
                write_wav(folder / (name + '.wav'), RATE, [sine(hz)])
            (folder / 'song.yaml').write_bytes(SONG_BLOCK.encode())
            old_state = gui.Handler.state
            st = gui.Handler.state = gui.State(folder / 'song.yaml')
            server = gui._Server(('127.0.0.1', 0), gui.Handler)
            threading.Thread(target=server.serve_forever, daemon=True).start()
            errors = []
            try:
                with sync_playwright() as pw:
                    browser = pw.chromium.launch(executable_path=os.environ.get('VT_CHROMIUM') or None)
                    page = browser.new_page(viewport={'width': 1180, 'height': 720})  # #app's minimum width
                    page.on('pageerror', lambda e: errors.append(str(e)))
                    page.goto(f'http://127.0.0.1:{server.server_address[1]}/')
                    page.wait_for_function('S?.song?.facts && PAT.rows')
                    # every tab label on one line, all inside the bar
                    self.assertTrue(page.evaluate("""(()=>{const t=document.querySelector('.tabs');
                        return t.scrollWidth<=t.clientWidth&&[...t.querySelectorAll('.tab')].every(x=>x.getBoundingClientRect().height<=28)})()"""))
                    # the transport's first row stays one line above the loop strip, a long status included
                    self.assertTrue(page.evaluate("""(()=>{$('nowmode').textContent+=' · re-rendering, the old mix plays until it lands';
                        const r=$('nowmode').parentElement.getBoundingClientRect();
                        return r.height<24&&r.bottom<=$('loopbar').getBoundingClientRect().top})()"""))
                    # F5 with a dialog open does not reach the browser (it would reload the page)
                    self.assertTrue(page.evaluate("""(()=>{toggle('keys',true);const e=new KeyboardEvent('keydown',{key:'F5',cancelable:true,bubbles:true});
                        document.dispatchEvent(e);toggle('keys',false);return e.defaultPrevented})()"""))
                    # Delete with nothing selected, outside edit mode, clears the cursor's cell (row 0: C-5 01)
                    page.click('[data-t="pattern"]')
                    page.evaluate('setEdit(false);SEL=null;setCursor(0,0,0,0)')
                    page.keyboard.press('Delete')
                    page.wait_for_function("!EDQ.n && PAT.rows[0][0].startsWith('...')")
                    # AMPLIFY 0 % gives v00 (row 2, channel B: C-5 02 with no volume)
                    page.evaluate("setCursor(0,2,1,2);$('sel-amp').value='0';selAmplify()")
                    page.wait_for_function("!EDQ.n && PAT.rows[2][1].includes('v00')")
                    for _ in range(100):
                        if st.mod.patterns[0].rows[0][0].note is None and st.mod.patterns[0].rows[2][1].volcmd == 0:
                            break
                        time.sleep(0.05)
                    self.assertIsNone(st.mod.patterns[0].rows[0][0].note)
                    self.assertEqual(st.mod.patterns[0].rows[2][1].volcmd, 0)
                    # a pan typed as S shows S
                    page.click('[data-t="overview"]')
                    page.click('#mp0')
                    page.fill('.typein', 's')
                    page.keyboard.press('Enter')
                    page.wait_for_function("S.mix?.pan?.['0']==='surround'")
                    page.wait_for_function("$('mp0').textContent==='S'")
                    # Ctrl+Alt+V floods on a layout where AltGr+V types '@' (Czech, Slovak, Hungarian): the key is '@'
                    page.click('[data-t="pattern"]')
                    page.evaluate("setEdit(false);SEL=null;setCursor(0,2,1,0);selCopy(false);setCursor(0,0,1,0)")
                    page.evaluate("""document.dispatchEvent(new KeyboardEvent('keydown',{key:'@',code:'KeyV',ctrlKey:true,altKey:true,
                        bubbles:true,cancelable:true}))""")
                    for _ in range(100):
                        if all(st.mod.patterns[0].rows[r][1].note == 60 for r in range(4)):
                            break
                        time.sleep(0.05)
                    self.assertEqual([st.mod.patterns[0].rows[r][1].note for r in range(4)], [60] * 4)
                    # TRIM HISTORY with the keep field emptied keeps every undo step (it read as 0 and cleared them)
                    steps, said = len(st.history), []
                    page.once('dialog', lambda d: (said.append(d.message), d.dismiss()))
                    page.click('[data-t="project"]')
                    page.fill('#history-keep', '')
                    page.click('text=TRIM HISTORY')
                    for _ in range(100):
                        if said:
                            break
                        page.wait_for_timeout(50)
                    self.assertIn('how many', said[0])
                    self.assertEqual(len(st.history), steps)
                    self.assertEqual(errors, [])
                    browser.close()
            finally:
                server.shutdown()
                server.server_close()
                st.close()
                gui.Handler.state = old_state


if __name__ == '__main__':
    unittest.main()
