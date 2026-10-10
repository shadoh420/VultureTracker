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

    def test_agent_sections_patterns_and_transforms(self):
        with self.page() as (page, d):
            def call(tool_name, **args):
                out = page.request.post(page.url + 'api/tool', data={'name': tool_name, 'args': args}).json()
                self.assertNotIn('error', out, out)
                return out
            call('edit_section', action='create', name='Intro', start=0, end=1)
            call('edit_section', action='duplicate', name='Intro', new_name='Outro', to=2)
            call('edit_pattern', action='rename', pattern='p1_copy1', new_name='Lead')
            call('edit_pattern', action='resize', pattern='Lead', rows=8)
            call('edit_pattern', action='materialize', pattern='Lead')
            call('transform_patterns', action='transpose', selections=[{'pattern': 'Lead', 'channels': [1]}], semitones=7)
            call('copy_pattern_region', source={'pattern': 'Lead', 'from_row': 0, 'to_row': 0, 'channels': [1]},
                 pattern='Lead', row=1, channel=1)
            call('write_patterns', patterns=[{'pattern': 'Lead', 'cells': [{'row': 3, 'channel': 1, 'cell': '==='}]}])
            page.evaluate("refresh()")
            page.wait_for_function("S.structure.patterns.some(p=>p.name==='Lead'&&p.rows===8)")
            page.evaluate("tab('pattern'); setEdit(true); CUR.o=2; CUR.row=0; showPattern(2); AG.view='log'; renderAgent()")
            page.wait_for_function("PAT && PAT.rows && PAT.rows.length===8 && PAT.rows[0][0].startsWith('G-5')")
            self.assertTrue(page.evaluate("PAT.rows[1][0].startsWith('G-5')"))
            self.assertEqual(page.evaluate("PAT.rows[3][0].split(' ')[0]"), '===')
            page.click('#agentbtn')
            page.evaluate("AG.view='log'; renderAgent()")
            self.assertIn('write_patterns', page.text_content('#ag-msgs'))
            if os.environ.get('VT_AGENT_SCREENSHOT'):
                page.screenshot(path=os.environ['VT_AGENT_SCREENSHOT'])
            call('undo')
            self.assertNotIn('===', (d / 'song.yaml').read_text())

    def test_agent_phrase_and_project_workflows(self):
        with self.page() as (page, d):
            def call(tool_name, **args):
                out = page.request.post(page.url + 'api/tool', data={'name': tool_name, 'args': args}).json()
                self.assertFalse(out.get('error'), out)
                return out
            original = (d / 'song.yaml').read_bytes()
            ph = call('capture_phrase', order=0, r0=0, r1=3, channels=[1], count=2)
            call('edit_phrase', phrase_id=ph['id'], variant=0, name='New melody',
                 data='D-5 01 ... ...\n... .. ... ...\n... .. ... ...\n... .. ... ...')
            rendered = call('render_phrase', phrase_id=ph['id'], variant=0)
            self.assertEqual(page.request.get(page.url.rstrip('/') + rendered['url']).status, 200)
            call('render_phrase', phrase_id=ph['id'], variant=-1)
            self.assertTrue(call('phrase_diff', phrase_id=ph['id'], variant=0)['lines'])
            page.evaluate("refresh()")
            page.evaluate("tab('phrases')")
            page.wait_for_function("document.querySelector('#phrase-choices').textContent.includes('New melody')")
            self.assertEqual((d / 'song.yaml').read_bytes(), original)
            if os.environ.get('VT_AGENT_SCREENSHOT'):
                page.screenshot(path=os.environ['VT_AGENT_SCREENSHOT'])
            # A switch requested through tools must reset the player/cursor just as OPEN does.
            made = call('create_project', path='next.yaml', channels=1, sample='a.wav')
            page.evaluate("CUR.o=1; CUR.row=3; CUR.ch=1; SEL={order:1}; $('phrase-audio').src='/wav/' + " + json.dumps(rendered['key']))
            call('open_project', path=made['path'])
            page.evaluate("refresh()")
            page.wait_for_function("S.song.path.endsWith('next.yaml') && CUR.o===0 && CUR.ch===0 && SEL===null")
            self.assertIsNone(page.get_attribute('#phrase-audio', 'src'))
            call('create_channel', name='Agent channel')
            page.evaluate("refresh()")
            page.wait_for_function("S.song.facts.channels.length===2")
            self.assertEqual((d / 'song.yaml').read_bytes(), original)
            self.assertIn('Agent channel', (d / 'next.yaml').read_text())

    def test_agent_library_and_synthesis_candidates(self):
        from vulturetracker.library import Library
        with self.page() as (page, d), mock.patch.object(gui.Handler, 'library', Library(d / 'library.json')):
            def call(tool_name, **args):
                out = page.request.post(page.url + 'api/tool', data={'name': tool_name, 'args': args}).json()
                self.assertFalse(out.get('error'), out)
                return out
            def wait(tool_name, job):
                # wait_for_function treats a returned fetch Promise as truthy before its result arrives.
                for _ in range(200):
                    status = call(tool_name, job_id=job['job_id'])
                    if status.get('done') or status.get('status') in ('done', 'failed', 'cancelled'):
                        return status
                    page.wait_for_timeout(25)
                self.fail(f'{tool_name} did not finish: {status}')
            before = (d / 'song.yaml').read_bytes()
            job = call('index_library', roots=[str(d)], replace_roots=True)
            self.assertEqual(wait('library_status', job)['result']['errors'], 0)
            self.assertEqual(call('search_library')['total'], 2,
                             (call('library_status', job_id=job['job_id']), gui.Handler.library.data))
            saved = call('save_sound_recipe', spec={'file': 'a.wav', 'note': 'A-5', 'reverse': True}, name='Reversed')
            job = call('render_synthesis', recipe=saved['recipe'], entry=saved['entry'])
            out = wait('synthesis_status', job)
            self.assertEqual(out['status'], 'done', out)
            call('offer_samples', slot=1, files=[out['file']])
            page.evaluate("tab('tryout'); refresh()")
            page.wait_for_function("S.candidates.length===1")
            self.assertTrue(Path(out['file']).is_file())
            self.assertEqual((d / 'song.yaml').read_bytes(), before)
            page.click('#agentbtn')
            page.evaluate("AG.view='log'; renderAgent()")
            self.assertIn('render_synthesis', page.text_content('#ag-msgs'))
            if os.environ.get('VT_AGENT_SCREENSHOT'):
                page.screenshot(path=os.environ['VT_AGENT_SCREENSHOT'])

    def test_agent_state_audition_and_transport(self):
        with self.page() as (page, d):
            def call(name, args=None):
                out = page.request.post(page.url + 'api/tool', data={'name': name, 'args': args or {}}).json()
                self.assertFalse(out.get('error'), out)
                return out
            page.evaluate("tab('rack'); RK_CH=1; renderRack(); agReportUI()")
            state = call('get_state')
            self.assertFalse(state['ui_stale'])
            self.assertEqual(state['ui']['rack_channel'], 2)
            self.assertEqual(state['ui']['tab'], 'rack')
            self.assertIsNone(state['audition']['solo'])  # selected does not mean soloed
            call('create_channel', {'name': 'Melody'})
            call('edit_effect', {'action': 'add', 'channel': 3, 'effect': 'distortion', 'changes': {'gain': -9}})
            self.assertEqual(call('get_state')['rack']['channel_plugins']['3'], 1)
            call('checkpoint', {'action': 'save', 'name': 'New melody'})
            page.evaluate("lvPatLoop=true")
            out = call('set_audition', {'solo': 3, 'muted': [1], 'loop': {'from': [0, 1], 'to': [1, 2]}})
            try:
                page.wait_for_function('id=>AG.applied===id', arg=out['request_id'], timeout=8000)
            except Exception:
                print('Transport diagnostics:', page.evaluate('({AG,error:LV.err,cue:S.cue,loop:S.loop})'), call('get_state'))
                raise
            self.assertEqual(page.evaluate('[S.solo,S.muted,lvPatLoop,S.loop]'), [2, [0], False, {'from': [0, 1], 'to': [1, 2]}])
            page.evaluate('lvPlay(0,1)')
            page.wait_for_function('LV.playing && LV.pos && LV.pos.playing')
            page.evaluate('agReportUI()')
            self.assertEqual(call('get_state')['ui']['playback']['engine'], 'live')
            # Reports/commands still run while a text input prevents the ordinary refresh timer.
            page.evaluate("tab('rack'); const input=document.createElement('input'); document.body.append(input); input.focus()")
            out = call('stop_playback')
            page.wait_for_function('id=>AG.applied===id && !LV.playing && audio.paused', arg=out['request_id'])
            page.evaluate('agReportUI()')
            self.assertEqual(call('get_state')['ui']['applied_request'], out['request_id'])
            page.evaluate('document.activeElement.blur(); refresh()')
            page.wait_for_function("S.own?.status==='ready' && !!audio.src")
            page.evaluate('audio.play()')
            out = call('stop_playback')
            page.wait_for_function('id=>AG.applied===id && audio.paused', arg=out['request_id'])
            # A pending live start cannot restart audio after the stop.
            page.evaluate("window.savedStart=lvStart; lvStart=()=>new Promise(r=>window.finishStart=r); window.starting=lvPlay(0,0); void 0")
            out = call('stop_playback')
            page.wait_for_function('id=>AG.applied===id', arg=out['request_id'])
            page.evaluate('finishStart(); starting.then(()=>{lvStart=savedStart})')
            self.assertFalse(page.evaluate('LV.playing'))
            page.evaluate('audio.play(); agReceiveCue({id:999,action:"stop",expires:1})')
            self.assertFalse(page.evaluate('audio.paused'))
            page.evaluate('audio.pause()')
            bad = page.request.post(page.url + 'api/uistate', data={'song': 'another song', 'state': {}}).json()
            self.assertIn('error', bad)
            if os.environ.get('VT_AGENT_SCREENSHOT'):
                page.evaluate("RK_CH=2; renderRack()")
                page.screenshot(path=os.environ['VT_AGENT_SCREENSHOT'])

    def test_agent_creation_channel_removal_and_export(self):
        with self.page() as (page, d):
            def call(name, args=None):
                out = page.request.post(page.url + 'api/tool', data={'name': name, 'args': args or {}}).json()
                self.assertFalse(out.get('error'), out)
                return out
            self.assertEqual(call('create_sample', {'file': 'a.wav', 'name': 'New sample'})['sample'], 3)
            self.assertEqual(call('create_instrument', {'sample': 3, 'name': 'New voice'})['instrument'], 4)
            call('create_channel', {'name': 'Temporary'})
            page.evaluate("refresh()")
            page.wait_for_function('S.song.facts.channels.length===3')
            page.evaluate("tab('pattern'); showPattern(0)")
            page.wait_for_function('PAT.rows && PAT.rows[0].length===3')
            page.evaluate("focus=[2]; CUR.ch=2; SEL={o:0,a:{row:0,ch:2,col:0},b:{row:2,ch:2,col:4}}; renderPat()")
            call('edit_channel', {'action': 'remove', 'channel': 3})
            page.evaluate('refresh()')
            page.wait_for_function('S.song.facts.channels.length===2 && PAT.rows && PAT.rows[0].length===2')
            self.assertEqual(page.evaluate('[focus,CUR.ch,SEL]'), [None, 1, None])
            self.assertIn('01 A', page.text_content('#pat'))
            call('edit_channel', {'action': 'move', 'channel': 1, 'to': 2})
            call('edit_channel', {'action': 'rename', 'channel': 2, 'name': 'Lead'})
            out = call('export_song', {'format': 'wav', 'destination': 'exports', 'include_it': True, 'tail': 0})
            page.evaluate("tab('export'); refresh()")
            page.wait_for_function("S.export && S.export.status==='done'", timeout=20000)
            job = call('export_status', {'job_id': out['job']['job_id']})['job']
            self.assertEqual(job['status'], 'done', job)
            self.assertTrue(all(Path(p).is_file() for p in job['files']))
            self.assertEqual(call('get_state')['instruments']['4']['sample'], 3)
            if os.environ.get('VT_AGENT_SCREENSHOT'):
                page.screenshot(path=os.environ['VT_AGENT_SCREENSHOT'])

    def test_agent_sample_processing_and_slot_deletion(self):
        with self.page() as (page, d):
            def call(name, args=None):
                out = page.request.post(page.url + 'api/tool', data={'name': name, 'args': args or {}}).json()
                self.assertFalse(out.get('error'), out)
                return out
            original = (d / 'a.wav').read_bytes()
            call('create_sample', {'file': 'a.wav', 'name': 'Experiment'})
            call('process_sample', {'number': 3, 'action': 'trim', 'start': 100, 'end': 4100})
            page.evaluate("tab('smp'); SMP_SEL='3'; refresh()")
            page.wait_for_function('W.data && W.data.num===3 && W.data.frames===4000')
            self.assertIn('Experiment', page.text_content('#smp-list'))
            call('create_instrument', {'sample': 3, 'name': 'Experiment voice'})
            call('edit_instrument', {'number': 4, 'changes': {'name': 'Edited voice', 'nna': 'fade'}})
            page.evaluate("tab('ins'); INS_SEL='4'; refresh()")
            page.wait_for_function("document.getElementById('ins-title').textContent.includes('Edited voice')")
            call('delete_slot', {'kind': 'instrument', 'number': 4})
            call('delete_slot', {'kind': 'instrument', 'number': 3})
            page.evaluate('refresh()')
            page.wait_for_function("INS_SEL==='1'")
            call('delete_slot', {'kind': 'sample', 'number': 3})
            page.evaluate("tab('smp'); refresh()")
            page.wait_for_function("SMP_SEL==='1' && W.data && W.data.num===1")
            self.assertEqual((d / 'a.wav').read_bytes(), original)
            call('undo')
            page.evaluate("SMP_SEL='3'; refresh()")
            page.wait_for_function('W.data && W.data.num===3 && W.data.frames===4000')
            if os.environ.get('VT_AGENT_SCREENSHOT'):
                page.screenshot(path=os.environ['VT_AGENT_SCREENSHOT'])

    def test_rack_bypass_and_remove_with_db_gain(self):
        with self.page() as (page, d):
            page.click('[data-t="rack"]')
            def add(effect, count):
                page.select_option('#rk-add', effect)
                page.click('text=+ ADD EFFECT')
                page.wait_for_function(f"document.querySelectorAll('#rk-chain .rkdev').length==={count} && EDQ.n===0")
            def remove(index, count):
                button = page.locator('#rk-chain .rkdev').nth(index).locator('[title="remove it (click twice): the chain closes up"]')
                button.click()
                button.click()
                page.wait_for_function(f"document.querySelectorAll('#rk-chain .rkdev').length==={count} && EDQ.n===0")
            for effect in ('distortion', 'compressor', 'param_eq'):
                add(effect, 1)
                button = page.locator('#rk-chain [title="bypass"]')
                button.click()
                page.wait_for_function("document.querySelector('#rk-chain .rkdev.byp') && EDQ.n===0")
                self.assertIn('bypass: true', (d / 'song.yaml').read_text())
                button.click()
                page.wait_for_function("!document.querySelector('#rk-chain .rkdev.byp') && EDQ.n===0")
                self.assertNotIn('bypass: true', (d / 'song.yaml').read_text())
                remove(0, 0)
            # The reported chain, with the Agent panel consuming horizontal space.
            page.evaluate("document.body.classList.add('agent-on')")
            for count, effect in enumerate(('i3dl2_reverb', 'waves_reverb', 'chorus', 'flanger', 'distortion'), 1):
                add(effect, count)
            scroll = page.locator('#rk-chain')
            self.assertTrue(scroll.evaluate('(e)=>e.scrollWidth>e.clientWidth'))
            scroll.evaluate('(e)=>e.scrollLeft=e.scrollWidth')
            button = page.locator('#rk-chain .rkdev').last.locator('[title="bypass"]')
            button.click()
            page.wait_for_function("document.querySelector('#rk-chain .rkdev:last-of-type.byp') && EDQ.n===0")
            if os.environ.get('VT_RACK_SCREENSHOT'):
                page.screenshot(path=os.environ['VT_RACK_SCREENSHOT'])
            remove(0, 4)  # removing a different effect still has to save Distortion's gain
            remove(3, 3)  # removing the last effect closes the chain
            for count in (2, 1, 0):
                remove(0, count)
            self.assertIsNone(page.evaluate('EDQ.err'))

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
            # the panel says which store holds the key, and warns when the key would travel in clear to a remote http URL
            page.evaluate("AG.view='set'; renderAgent()")
            store = page.evaluate("S.chat.settings.key_store")
            self.assertIn(store, ('keyring', 'file'))
            self.assertIn('credential store' if store == 'keyring' else 'plain text', page.text_content('#ag-store'))
            self.assertFalse(page.is_visible('#ag-warn'))
            page.fill('#ag-base', 'http://example.com/v1')
            page.click("text=SAVE")
            page.wait_for_function("S.chat.settings.base_url_warning")
            page.evaluate("AG.view='set'; renderAgent()")
            self.assertTrue(page.is_visible('#ag-warn'))
            self.assertIn('in clear', page.text_content('#ag-warn'))
            # the agent's replies are markdown, escaped first; the owner's own words stay as typed
            html = page.evaluate(r"""(()=>{S.chat={messages:[{role:'you',text:'**as typed**'},{role:'agent',text:'## Done\n- **loud** `a_b`\n<img src=x>\n| a | b |\n|---|---|\n| 1 | 2 |'}],settings:{provider:'openai'}};
                AG.view='chat';renderAgent();return $('ag-msgs').innerHTML})()""")
            for part in ('**as typed**', '<b class="mh">Done</b>', '• <b>loud</b> <code>a_b</code>', '&lt;img src=x&gt;', '<td>1</td>'):
                self.assertIn(part, html)

    def test_agent_session_workflows(self):
        from tests.test_record import fake_recorder
        recorder = fake_recorder()
        with mock.patch.object(gui.Handler, 'recorder', recorder), \
                mock.patch.object(gui.Handler, 'pending_recording', None), \
                mock.patch.object(gui.Handler, 'rec_devices', None), self.page() as (page, d):
            def call(tool_name, **args):
                result = page.evaluate("a=>fetch('/api/tool',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify(a)}).then(r=>r.json())",
                                       {'name': tool_name, 'args': args})
                self.assertFalse(result.get('error'), result)
                return result
            try:
                note = call('update_listening_note', action='add', order=0, row=0, text='Test note')['note']
                call('update_listening_note', action='update', note_id=note['id'], revision=note['revision'], text='Revised note')
                self.assertIn('Revised note', (d / 'song.notes.md').read_text())
                call('recording_status', refresh_devices=True)
                call('control_recording', action='open', device=0)
                call('control_recording', action='start')
                recorder.stream.feed(.3)
                take = call('control_recording', action='stop', name='Agent take')['take']
                self.assertTrue(Path(take['path']).is_file())
                out = call('manage_take', action='inspect', file=take['file'])
                self.assertEqual(page.request.get(page.url.rstrip('/') + out['url']).body()[:4], b'RIFF')
                page.evaluate("tab('rec');recPoll(true)")
                page.wait_for_function("$('rec-takes').textContent.includes('Agent_take')")
                if os.environ.get('VT_AGENT_SCREENSHOT'):
                    page.screenshot(path=os.environ['VT_AGENT_SCREENSHOT'])
                call('control_recording', action='close')
                call('create_channel', name='History test')
                entry = call('inspect_history')['entries'][0]
                self.assertTrue(call('inspect_history', index=0, entry_id=entry['entry_id'])['detail']['lines'])
                # Exercise actual WASM and media playback, not mocked play/pause functions.
                page.evaluate("refresh().then(()=>{tab('pattern');lvPatLoop=true;return lvPlay(0,1)})")
                page.wait_for_function("LV.playing && LV.pos && LV.pos.playing")
                call('pause_playback')
                page.wait_for_function("pausedTransport?.engine==='live' && LV.pos && !LV.pos.playing")
                seconds = page.evaluate('LV.pos.seconds')
                page.wait_for_timeout(150)
                self.assertEqual(page.evaluate('LV.pos.seconds'), seconds)
                self.assertTrue(page.evaluate('lvPatLoop'))
                call('resume_playback')
                page.wait_for_function("!pausedTransport && LV.playing && LV.pos.playing")
                self.assertTrue(page.evaluate('lvPatLoop'))
                call('pause_playback')
                page.wait_for_function("pausedTransport?.engine==='live'")
                call('stop_playback')
                page.wait_for_function("!pausedTransport && !LV.playing")
                page.wait_for_function("S.own?.status==='ready' && audio.src")
                page.evaluate('audio.play()')
                page.wait_for_function('!audio.paused')
                call('pause_playback')
                page.wait_for_function("pausedTransport?.engine==='rendered' && audio.paused")
                seconds = page.evaluate('audio.currentTime')
                page.wait_for_timeout(150)
                self.assertEqual(page.evaluate('audio.currentTime'), seconds)
                call('resume_playback')
                page.wait_for_function('!pausedTransport && !audio.paused')
                call('stop_playback')
                page.wait_for_function('audio.paused')
            finally:
                recorder.close()

    def test_tuner_tab(self):
        with self.page() as (page, d):
            page.click('.tab[data-t=tuner]')
            page.wait_for_function("$('tu-dev').textContent.includes('OPEN the input')")  # drawn by the RECORD tab's poll
            page.evaluate("renderTuner({open:true,tuner:{note:23,cents:-3,hz:30.82}})")  # a five-string's low B, 3 cents flat
            self.assertEqual(page.text_content('#tu-note'), 'B0')
            self.assertEqual(page.text_content('#tu-app'), 'B-1 in a pattern')
            self.assertEqual(page.evaluate("$('tu-needle').style.left"), '47%')


if __name__ == '__main__':
    unittest.main()
