"""Real rehearsal controls, shared by source and final executable checks."""
import json
import unittest
from tests import test_tablature_page as helpers
from tests.test_repeat_rehearsal import repeat_song
from vulturetracker import api


class TestRepeatRehearsalPage(unittest.TestCase):
    muted_page = helpers.TestTablaturePage.muted_page
    page = helpers.TestTablaturePage.page

    def run_study(self,page,song_path):
        original=song_path.read_bytes()
        page.click('#rehearsal-open')
        page.fill('#rehearsal-first','25');page.fill('#rehearsal-last','29')
        page.fill('#rehearsal-from','100');page.fill('#rehearsal-to','100')
        page.uncheck('#rehearsal-count');page.uncheck('#rehearsal-metro');page.uncheck('#rehearsal-loop')
        page.select_option('#rehearsal-traversal','repeats');page.fill('#rehearsal-visit','1')
        page.click('#rehearsal-start');page.wait_for_function('REHEARSAL.active&&LV.playing')
        span=page.evaluate('REHEARSAL.span')
        orders=page.evaluate('''() => LV.plan.occurrences.filter(v=>rehearsalCmp(v.at,REHEARSAL.span.fromAt)>=0&&rehearsalCmp(v.at,REHEARSAL.span.toAt)<0).map(v=>v.source_order)''')
        assert orders==[24,25,26,27,24,25,26,28],orders
        assert len(span['points'])==36
        page.click('#rehearsal-stop')
        page.fill('#rehearsal-last','25');page.select_option('#rehearsal-traversal','visit');page.fill('#rehearsal-visit','2')
        page.click('#rehearsal-start');page.wait_for_function('REHEARSAL.active&&LV.playing')
        assert page.evaluate('REHEARSAL.span.pass')==2
        page.click('#rehearsal-stop');page.click('#rehearsal-close')
        assert song_path.read_bytes()==original
        return dict(closing_traversal=orders,mixed_meter_clicks=36,second_visit=True,source_unchanged=True)

    def test_repeat_visits_once_pause_and_refusals(self):
        with self.muted_page(api.to_yaml(repeat_song()),width=1600,height=1000) as (page,state,folder):
            self.assertFalse(state.error,state.error)
            print(self.run_repeat_rehearsal(page,state.song_path))

    def run_repeat_rehearsal(self,page,song_path):
        original=song_path.read_bytes()
        errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
        page.evaluate("tab('tab');setEdit(false)")
        page.wait_for_selector('[data-ui=track]')
        page.click('#rehearsal-open')
        page.fill('#rehearsal-first','1');page.fill('#rehearsal-last','2')
        page.fill('#rehearsal-from','100');page.fill('#rehearsal-to','100')
        page.uncheck('#rehearsal-count');page.uncheck('#rehearsal-metro');page.uncheck('#rehearsal-loop')
        page.click('#rehearsal-start')
        page.wait_for_function('REHEARSAL.active&&LV.playing')
        assert page.evaluate('REHEARSAL.span.toAt')==[12,1]
        page.wait_for_function('LV.pos?.order===2&&LV.playing',timeout=15000)
        assert page.evaluate('LV.oi')==0
        assert page.evaluate('sourcePosition(LV.pos).pass')==2
        page.evaluate("agCue({action:'pause'})")
        page.wait_for_function('!LV.playing&&pausedTransport?.engine==="live"')
        assert page.evaluate('REHEARSAL.active')
        page.evaluate("agCue({action:'resume'},S.song.path)")
        page.wait_for_function('!REHEARSAL.active&&!LV.playing',timeout=15000)
        assert 'Practice finished' in page.inner_text('#rehearsal-status')
        page.select_option('#rehearsal-traversal','visit');page.fill('#rehearsal-last','1');page.fill('#rehearsal-visit','2')
        page.click('#rehearsal-start')
        page.wait_for_function('REHEARSAL.active&&LV.playing')
        assert page.evaluate('REHEARSAL.span.from')==[2,[0,1]]
        page.click('#rehearsal-stop')
        page.fill('#rehearsal-visit','3');page.click('#rehearsal-start')
        page.wait_for_function("document.querySelector('#rehearsal-status').textContent.includes('2 available')")
        assert not page.evaluate('LV.playing||REHEARSAL.active')
        page.fill('#rehearsal-visit','1');page.fill('#rehearsal-first','2');page.fill('#rehearsal-last','3')
        page.click('#rehearsal-start')
        page.wait_for_function("document.querySelector('#rehearsal-status').textContent.includes('no contiguous')")
        assert not page.evaluate('LV.playing||REHEARSAL.active')
        # Prepare a later visit, pause it, then edit through the real note control.
        page.fill('#rehearsal-first','1');page.fill('#rehearsal-last','1');page.fill('#rehearsal-visit','2')
        page.check('#rehearsal-loop');page.click('#rehearsal-start')
        page.wait_for_function('REHEARSAL.active&&LV.playing&&LV.pos?.order===2')
        page.evaluate("agCue({action:'pause'})")
        page.click('#rehearsal-close')
        helper=helpers.TestTablaturePage()
        helper.capture_engraving(page)
        page.evaluate('setEdit(true)')
        page.select_option('[data-ui=track]','guitar')
        helper.settled(page,'window.tabRendered&&tabRenderApi.boundsLookup.isFinished')
        helper.click_tab_lane(page,0,0,2)
        if page.locator('.vt-tab-inspector').get_attribute('open') is None:
            page.locator('.vt-tab-inspector > summary').click()
        revision=page.evaluate('SCORE.view.revision')
        with page.expect_response('**/api/score') as response:
            page.click('[data-action=pitch-up]')
        changed=response.value.json();assert changed.get('ok'),changed
        page.wait_for_function('!REHEARSAL.active&&!LV.playing&&!LV.loading&&LV.key===lvKey()')
        assert 'Score changed' in page.inner_text('#rehearsal-status')
        page.click('[data-action=undo]')
        helper.settled(page,'SCORE.view.revision==='+json.dumps(revision))
        page.wait_for_function('!LV.loading&&LV.key===lvKey()')
        # Ordinary playback reload must retain the second performed visit too.
        page.click('#rehearsal-open');page.click('#rehearsal-start')
        page.wait_for_function('LV.playing&&LV.pos?.order===2')
        page.evaluate("agCue({action:'pause'})")
        page.click('#rehearsal-close')
        page.click('[data-action=play]')
        page.wait_for_function('LV.playing&&!REHEARSAL.active&&LV.pos?.order===2')
        page.evaluate("agCue({action:'pause'})")
        with page.expect_response('**/api/score') as response:
            page.click('[data-action=pitch-up]')
        assert response.value.json().get('ok')
        page.wait_for_function('!LV.loading&&LV.key===lvKey()&&LV.pos?.revision===LV.planRevision')
        assert page.evaluate('LV.pos.pass')==2
        assert page.evaluate('LV.pos.order')==2
        page.click('[data-action=undo]')
        helper.settled(page,'SCORE.view.revision==='+json.dumps(revision))
        page.evaluate('lvStop();setEdit(false)')
        assert song_path.read_bytes()==original
        assert not errors,errors
        return dict(full_repeat_end=[12,1],specific_visit=2,once_pause_resume=True,edit_cancels_practice=True,reload_retains_pass=True,source_unchanged=True)
