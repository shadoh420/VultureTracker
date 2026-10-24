"""The live sounding strip waits for the current authored-to-playback mapping after edits."""
import unittest

from tests import test_tablature_page as helpers
from tests.test_tablature_sync import complete_song_seed
from vulturetracker import api


class TestSoundingRefreshPage(unittest.TestCase):
    page = helpers.TestTablaturePage.page
    muted_page = helpers.TestTablaturePage.muted_page
    settled = helpers.TestTablaturePage.settled
    capture_engraving = helpers.TestTablaturePage.capture_engraving
    open_panel = staticmethod(helpers.TestTablaturePage.open_panel)

    def test_repeat_edit_waits_for_state_before_fetching_sounding_pass(self):
        source = complete_song_seed()
        for sample in source['samples'].values():
            sample['file'] = 'a.wav'
        with self.muted_page(api.to_yaml(source)) as (page, state, folder):
            self.assertFalse(state.error, state.error)
            page.evaluate("tab('tab');setEdit(true)")
            page.wait_for_selector('[data-ui=track]', state='attached')
            self.capture_engraving(page)
            page.evaluate('async()=>{setCursor(1,0);await scoreRefresh()}')
            self.open_panel(page, 'measures')
            page.select_option('[data-ui=measure]', source['score']['measures'][1]['id'])
            page.fill('[data-ui=measure-repeat-close]', '1')
            self.assertIsNone(page.evaluate('playbackOrders()'))
            page.evaluate("""() => {
              window.soundingRequests=[];window.soundingPhases=[];window.repeatSaved=false;
              // A loaded rendered song may remain in the audio element while notation changes.
              Object.defineProperty(audio,'duration',{configurable:true,get:()=>10});
              const original=window.fetch;
              const probe=phase=>{
                // Exercise an uncached order at each asynchronous handoff, not just the cached row.
                for(const key of Object.keys(SND))delete SND[key];
                const before=soundingRequests.length;
                renderLive();
                soundingPhases.push({phase,edit:EDQ.n,refresh:typeof stateRefreshing==='undefined'?0:stateRefreshing,
                  requested:soundingRequests.length!==before,visits:playbackOrders()?.length||0});
              };
              window.fetch=async (...args)=>{
                const url=String(args[0]),isSounding=url.includes('/api/sounding/');
                const entry={url};if(isSounding)soundingRequests.push(entry);
                const response=await original(...args);
                if(isSounding){entry.status=response.status;if(!response.ok)entry.error=await response.clone().text()}
                if(url==='/api/score'&&args[1]?.method==='POST'&&response.ok){repeatSaved=true;probe('edit')}
                if(url==='/api/state'&&repeatSaved)probe('refresh');
                return response;
              };
            }""")
            page.click('.vt-tab-measures button[type=submit]')
            self.settled(page, 'SCORE.view.score.measures[1].repeat_close===1&&!!playbackOrders()')
            page.evaluate('renderLive()')
            page.wait_for_function('soundingRequests.some(r=>r.status===200&&r.url.includes("play_id="))')
            phases = page.evaluate('soundingPhases')
            self.assertEqual({p['phase'] for p in phases}, {'edit', 'refresh'})
            self.assertTrue(all(not p['requested'] for p in phases), phases)
            self.assertTrue(any(p['phase'] == 'edit' and p['edit'] > 0 for p in phases), phases)
            self.assertTrue(any(p['phase'] == 'refresh' and p['edit'] == 0 and p['refresh'] > 0 for p in phases), phases)
            requests = page.evaluate('soundingRequests')
            self.assertTrue(all(r.get('status') == 200 for r in requests), requests)
            self.assertTrue(all('play_id=' in r['url'] for r in requests), requests)
            self.assertEqual(page.evaluate('stateRefreshing'), 0)
