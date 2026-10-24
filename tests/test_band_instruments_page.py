"""Real headless page controls for part sounds; reusable by the packaged smoke."""
import json
import os
from pathlib import Path
import unittest

from vulturetracker import api
from tests.test_modimport import bank
from tests.test_tablature_sync import complete_song_seed
from tests import test_tablature_page as helpers


class TestBandInstrumentsPage(unittest.TestCase):
    page = helpers.TestTablaturePage.page
    muted_page = helpers.TestTablaturePage.muted_page
    settled = helpers.TestTablaturePage.settled
    capture_engraving = helpers.TestTablaturePage.capture_engraving

    def open_parts(self, page):
        page.evaluate("tab('tab');setEdit(true)")
        page.wait_for_selector('#part-sounds:not([hidden])')
        if page.get_attribute('#part-sounds', 'open') is None:
            page.click('#part-sounds > summary')

    def run_part_sound_edits(self, page, song_path):
        self.open_parts(page)
        original = song_path.read_bytes()
        source = api.from_yaml(original.decode('utf-8'))
        track = next(iter(source['score']['tracks']))
        old = source['score']['tracks'][track]['instrument']
        options = source.get('instruments') or source['samples']
        number = next(n for n in options if n != old)
        page.select_option('#part-sound-track', track)
        page.select_option('#part-sound-instrument', str(number))
        with page.expect_response('**/api/score_instrument') as response:
            page.click('#part-sound-assign')
        result = response.value.json()
        self.assertTrue(result.get('ok'), result)
        self.settled(page, 'SCORE.view.revision===' + json.dumps(result['revision']))
        self.assertEqual(api.from_yaml(song_path.read_text(encoding='utf-8'))['score']['tracks'][track]['instrument'], number)
        self.assertIn('Assigned sound', page.inner_text('#part-sound-status'))
        # Capture messages while preserving the real preview engine underneath.
        page.evaluate("""async()=>{const syncing=setInterval(()=>lvSync(),0);
            try{await lvStart()}finally{clearInterval(syncing)}
            window.bandPreviewMessages=[];const port=LV.node.port;
            const send=port.postMessage.bind(port);port.postMessage=(m,...args)=>{bandPreviewMessages.push(m);return send(m,...args)}}""")
        page.dispatch_event('#part-sound-audition', 'pointerdown')
        page.wait_for_function("bandPreviewMessages.some(m=>m.type==='note')")
        message = page.evaluate("bandPreviewMessages.find(m=>m.type==='note')")
        self.assertEqual((message['ins'], message['note']), (number - 1, 60))
        page.dispatch_event('#part-sound-audition', 'pointerup')
        page.wait_for_function("!Object.keys(LV.held).length")
        channels = source['score']['tracks'][track]['channels']
        page.click('#part-sound-mute')
        page.wait_for_function('(channels)=>channels.every(c=>S.muted.includes(c))', arg=channels)
        page.click('#part-sound-solo')
        expected = [i for i in range(len(source['module']['channels'])) if i not in channels]
        page.wait_for_function('(expected)=>JSON.stringify(S.muted)===JSON.stringify(expected)', arg=expected)
        page.locator('#part-sounds').get_by_role('button', name='Clear mutes').click()
        page.wait_for_function('!S.muted.length&&S.solo==null')
        self.assertEqual(api.from_yaml(song_path.read_text(encoding='utf-8'))['module'], source['module'])
        page.click('[data-action=undo]')
        self.settled(page, 'SCORE.view.score.tracks[' + json.dumps(track) + '].instrument===' + str(old))
        self.assertEqual(song_path.read_bytes(), original)
        page.evaluate('lvStop()')
        return dict(track=track, assigned_sound=number, audition_note=message['note'], mute_solo=True, exact_undo=True)

    def run_part_track_selection(self, page, song_path):
        self.open_parts(page)
        original = song_path.read_bytes()
        source = api.from_yaml(original.decode('utf-8'))
        tracks = source['score']['tracks']
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        self.capture_engraving(page)
        page.select_option('[data-ui=track]', 'guitar')
        self.settled(page, 'window.tabRendered&&tabRenderApi.boundsLookup.isFinished')
        history = page.evaluate('[S.undo,S.redo]')
        for selector, track in (('#part-sound-track', 'bass'), ('[data-ui=track]', 'guitar2'),
                                ('#part-sound-track', 'drums'), ('[data-ui=track]', 'guitar')):
            page.select_option(selector, track)
            try:
                page.wait_for_function("""name=>window.tabRendered?.tracks[0].name===name&&
                    tabRenderApi.boundsLookup.isFinished&&
                    document.querySelector('[data-ui=track]').value===document.querySelector('#part-sound-track').value""",
                    arg=tracks[track]['name'], timeout=5000)
            finally:
                evidence = os.environ.get('VT_PART_SELECTION_EVIDENCE')
                if evidence and track == 'bass':
                    Path(evidence).mkdir(parents=True, exist_ok=True)
                    page.screenshot(path=str(Path(evidence)/'bass-selection.png'), full_page=True)
            self.assertEqual(page.input_value('#part-sound-track'), track)
            self.assertEqual(page.input_value('[data-ui=track]'), track)
            self.assertEqual(page.input_value('#part-sound-instrument'), str(tracks[track]['instrument']))
            self.assertFalse(page.locator('.vt-tab-score .at-surface').evaluate('e=>e.hidden'))
            actual = page.evaluate('tabRendered.tracks[0].staves[0].bars[0].voices[0].beats.flatMap(b=>b.notes.map(n=>n.percussionArticulation===101?42:n.realValue)).sort((a,b)=>a-b)')
            expected = sorted(n['pitch'] for b in source['score']['patterns'][source['orders'][0]]['beats']
                              if b['track']==track and b.get('voice',0)==0 for n in b['notes'])
            self.assertEqual(actual, expected)
        # A refresh must retain the same part, and caret changes must not reset a
        # pending sound choice before Assign has been pressed.
        page.select_option('#part-sound-instrument', '2')
        page.select_option('[data-ui=voice]', label='2')
        self.assertEqual(page.input_value('[data-ui=voice]'), '1')
        self.assertEqual(page.input_value('#part-sound-instrument'), '2')
        page.select_option('[data-ui=voice]', label='1')
        page.evaluate('async()=>{SCORE.key=null;await scoreRefresh()}')
        self.assertEqual(page.input_value('#part-sound-track'), page.input_value('[data-ui=track]'))
        self.assertEqual(page.evaluate('[S.undo,S.redo]'), history)
        self.assertEqual(song_path.read_bytes(), original)
        self.assertEqual(errors, [])
        return dict(both_selectors=True, engraved_notes=True, sound_target=True, unchanged_song_history=True)

    def test_part_and_track_selectors_update_the_same_score(self):
        source = complete_song_seed()
        for sample in source['samples'].values():
            sample['file'] = 'a.wav'
        with self.muted_page(api.to_yaml(source), width=1600, height=1000, compact=True) as (page, state, folder):
            print(self.run_part_track_selection(page, state.song_path))

    def test_assignment_audition_mute_solo_and_undo(self):
        source = complete_song_seed()
        for sample in source['samples'].values():
            sample['file'] = 'a.wav'
        with self.muted_page(api.to_yaml(source), compact=True) as (page, state, folder):
            self.run_part_sound_edits(page, folder / 'song.yaml')

    def test_existing_soundfont_import_then_part_assignment(self):
        source = complete_song_seed()
        for sample in source['samples'].values():
            sample['file'] = 'a.wav'
        with self.muted_page(api.to_yaml(source), compact=True) as (page, state, folder):
            (folder / 'fixture.sf2').write_bytes(bank()[0])
            self.open_parts(page)
            page.get_by_role('button', name='Add SoundFont preset').click()
            page.fill('#ins-sf2', str(folder / 'fixture.sf2'))
            with page.expect_response('**/api/sf2presets') as response:
                page.press('#ins-sf2', 'Enter')
            self.assertFalse(response.value.json().get('error'))
            page.select_option('#ins-sf2p', '0:0')
            page.click('#ins-sf2p + span')
            page.wait_for_function('!EDQ.n&&S.song.facts.instruments.length===5')
            self.open_parts(page)
            page.select_option('#part-sound-instrument', '5')
            with page.expect_response('**/api/score_instrument') as response:
                page.click('#part-sound-assign')
            result = response.value.json()
            self.assertTrue(result.get('ok'), result)
            self.settled(page, 'SCORE.view.score.tracks.guitar.instrument===5')
            self.assertEqual(state.song['instruments'][5]['name'], 'Keys')
            page.click('[data-action=undo]')
            self.settled(page, 'SCORE.view.score.tracks.guitar.instrument===1')
            page.click('[data-action=undo]')
            self.settled(page, 'S.song.facts.instruments.length===4')


if __name__ == '__main__':
    unittest.main()
