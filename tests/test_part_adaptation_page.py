"""Real track setup controls, reused against the packaged executable."""
import json
import unittest
from tests import test_tablature_page as helpers
from tests.test_tablature_sync import complete_song_seed
from vulturetracker import api


def adaptation_song():
    song = complete_song_seed()
    song['module']['title'] = 'Part adaptation'
    for sample in song['samples'].values():
        sample['file'] = 'a.wav'
    return song


class TestPartAdaptationPage(unittest.TestCase):
    muted_page = helpers.TestTablaturePage.muted_page
    page = helpers.TestTablaturePage.page

    def run_part_marker(self, page, path):
        original = path.read_bytes()
        page.click('[data-t=tab]')
        page.wait_for_selector('.vt-tab-score svg')
        page.locator('#part-sounds > summary').click()
        page.select_option('#part-sound-track', label='Drop D guitar')
        assert page.is_checked('[data-ui=follow]'), 'Selecting a part disabled playback following'
        page.click('[data-action=play]')
        page.wait_for_function('LV.playing && LV.pos')
        page.wait_for_selector('.vt-tab-playhead[data-track=guitar2]:not([hidden])')
        first = page.get_attribute('.vt-tab-playhead', 'data-score-at')
        page.wait_for_function("at=>document.querySelector('.vt-tab-playhead')?.dataset.scoreAt!==at", arg=first)
        # The real Part control scrolls into view to be used. Switching during
        # playback must resume following, rather than leave its select focused
        # and the marker stranded below the viewport.
        page.select_option('#part-sound-track', label='Bass')
        assert page.is_checked('[data-ui=follow]')
        page.wait_for_function("""() => {
          const e=document.querySelector('.vt-tab-playhead'),c=document.querySelector('#t-tab').getBoundingClientRect(),r=e?.getBoundingClientRect();
          return e && !e.hidden && e.dataset.track==='bass' && r.top>=c.top && r.bottom<=c.bottom && r.left>=c.left && r.right<=c.right;
        }""")
        first = page.get_attribute('.vt-tab-playhead', 'data-score-at')
        page.wait_for_function("at=>document.querySelector('.vt-tab-playhead')?.dataset.scoreAt!==at", arg=first)
        page.select_option('[data-ui=track]', 'guitar2')
        assert page.is_checked('[data-ui=follow]'), 'Track selector disabled playback following'
        page.wait_for_selector('.vt-tab-playhead[data-track=guitar2]:not([hidden])')
        page.select_option('[data-ui=voice]', label='2')
        assert page.is_checked('[data-ui=follow]'), 'Voice selector disabled playback following'
        page.wait_for_selector('.vt-tab-playhead[data-track=guitar2]:not([hidden])')
        assert page.input_value('[data-ui=voice]') == '1'
        page.keyboard.press('Control+1')
        assert page.input_value('[data-ui=voice]') == '0'
        assert page.is_checked('[data-ui=follow]')
        page.evaluate('lvStop()')
        page.uncheck('[data-ui=follow]')
        page.select_option('[data-ui=track]', 'bass')
        assert not page.is_checked('[data-ui=follow]'), 'Explicitly paused follow was reset'
        page.select_option('[data-ui=voice]', label='2')
        assert not page.is_checked('[data-ui=follow]')
        page.locator('#tab-editor').focus()
        page.keyboard.press('Control+1')
        assert not page.is_checked('[data-ui=follow]')
        assert path.read_bytes() == original
        # Leave the reusable package runner at its initial part/order; its
        # later no-rerender check deliberately navigates channel zero.
        page.select_option('[data-ui=track]', 'guitar')
        page.evaluate('async()=>{setCursor(0,0,0,0);await scoreRefresh()}')
        page.wait_for_function("document.querySelector('.vt-tab-score').dataset.tracks.split(',').includes('guitar') && document.querySelector('.vt-tab-score').dataset.bars")
        return dict(part_switch_before_and_during_playback=True, moving_visible_marker=True,
                    empty_voice_marker=True, voice_follow=True, explicit_follow_pause_preserved=True, song_unchanged=True)

    def test_part_switch_preserves_playback_marker_follow(self):
        with self.muted_page(api.to_yaml(adaptation_song()), compact=True, width=1000, height=750) as (page, state, folder):
            self.assertFalse(state.error, state.error)
            print(self.run_part_marker(page, state.song_path))

    def test_part_marker_in_clean_default_multitrack_view(self):
        with self.muted_page(api.to_yaml(adaptation_song()), compact=True, score_view=None,
                             width=1000, height=750) as (page, state, folder):
            self.assertFalse(state.error, state.error)
            print(self.run_part_marker(page, state.song_path))

    def run_pending_edit(self, page, path):
        """Use the same real response/navigation/history check in the EXE."""
        original = path.read_bytes()
        page.click('[data-t=tab]')
        page.wait_for_function('SCORE.view && !SCORE.pending && !SCORE.fetching')
        initial = page.evaluate("[EDIT,document.querySelector('.vt-tab-inspector').open,document.querySelector('.vt-tab-grid-details').open]")
        page.evaluate("setEdit(true);document.querySelector('.vt-tab-inspector').open=true;document.querySelector('.vt-tab-grid-details').open=true")
        page.select_option('[data-ui=track]', 'guitar')
        page.select_option('[data-ui=voice]', label='1')
        page.locator('.vt-tab-grid [data-note]').first.click()
        page.click('[data-action=select-all]')
        page.fill('[data-ui=velocity]', '47')
        history = page.evaluate('S.undo')
        held = []
        def hold(route):
            held.append(route)
        page.route('**/api/score_command', hold)
        try:
            with page.expect_request('**/api/score_command'):
                page.click('[data-action=velocity]')
            page.wait_for_function('EDQ.n===1')
            assert len(held) == 1
            assert page.evaluate("!!document.activeElement.closest('#tab-editor') && !document.activeElement.disabled"), 'pending save must retain keyboard focus'
            page.select_option('[data-ui=voice]', label='2')
            assert page.input_value('[data-ui=voice]') == '1'
            selection = page.evaluate('JSON.stringify(CUR.score)')
            held.pop().continue_()
            page.wait_for_function("!EDQ.n && !SCORE.pending && !document.querySelector('[data-ui=track]').disabled")
            assert page.evaluate('S.undo') == history + 1
            assert page.evaluate('JSON.stringify(CUR.score)') == selection
            assert page.input_value('[data-ui=voice]') == '1'
        finally:
            for route in held:
                route.continue_()
            page.unroute('**/api/score_command', hold)
        saved = path.read_bytes()
        assert saved != original
        for action, count, expected in [('undo', history, original), ('redo', history + 1, saved), ('undo', history, original)]:
            page.click(f'[data-action={action}]')
            page.wait_for_function('count=>!EDQ.n&&!SCORE.pending&&S.undo===count', arg=count)
            assert path.read_bytes() == expected
        page.select_option('[data-ui=voice]', label='1')
        page.evaluate("values=>{setEdit(values[0]);document.querySelector('.vt-tab-inspector').open=values[1];document.querySelector('.vt-tab-grid-details').open=values[2]}", initial)
        return dict(delayed_edit_keeps_new_voice=True, exact_undo_redo=True, original_restored=True)

    def test_pending_phrase_edit_preserves_navigation_and_history(self):
        with self.muted_page(api.to_yaml(adaptation_song()), compact=True) as (page, state, folder):
            print(self.run_pending_edit(page, state.song_path))

    def test_empty_voice_part_switch_keeps_marker_and_voice_follow(self):
        source = adaptation_song()
        source['module']['tempo'] = 60
        with self.muted_page(api.to_yaml(source), width=1000, height=750) as (page, state, folder):
            original = state.song_path.read_bytes()
            page.click('[data-t=tab]')
            page.wait_for_selector('.vt-tab-score svg')
            page.wait_for_function('SCORE.view && !SCORE.fetching && !SCORE.pending')
            page.select_option('[data-ui=voice]', label='2')
            self.assertEqual(page.input_value('[data-ui=voice]'), '1', 'voice selection')
            page.select_option('[data-ui=track]', 'guitar2')
            self.assertEqual(page.input_value('[data-ui=voice]'), '1', 'part selection')
            page.check('[data-ui=follow]')
            self.assertEqual(page.input_value('[data-ui=voice]'), '1', 'follow refresh')
            page.keyboard.press('F6')
            page.wait_for_function('LV.playing && LV.pos')
            # This part only has voice 1; retaining editing voice 2 must not
            # erase the playback marker for the whole part.
            page.wait_for_selector('.vt-tab-playhead[data-track=guitar2]:not([hidden])', timeout=3000)
            self.assertEqual(page.input_value('[data-ui=voice]'), '1')
            for value in ('0', '1'):
                page.select_option('[data-ui=voice]', index=int(value))
                self.assertTrue(page.is_checked('[data-ui=follow]'))
                page.wait_for_selector('.vt-tab-playhead:not([hidden])', timeout=3000)
            page.locator('#tab-editor').focus()
            for key in ('Control+1', 'Control+2'):
                page.keyboard.press(key)
                self.assertTrue(page.is_checked('[data-ui=follow]'))
                page.wait_for_selector('.vt-tab-playhead:not([hidden])', timeout=3000)
            page.keyboard.press('Escape')
            page.wait_for_function('!LV.playing && !pausedTransport')
            page.wait_for_function("!document.querySelector('.vt-tab-playhead:not([hidden])')")
            self.assertEqual(state.song_path.read_bytes(), original)

    def test_part_navigation_paused_transport_and_mix_keep_source(self):
        source = adaptation_song()
        source['module']['tempo'] = 60
        with self.muted_page(api.to_yaml(source), width=1100, height=800) as (page, state, folder):
            original = state.song_path.read_bytes()
            page.click('[data-t=tab]')
            page.wait_for_selector('.vt-tab-score svg')
            page.locator('#part-sounds > summary').click()
            page.keyboard.press('F6')
            page.wait_for_function('LV.playing && LV.pos?.scoreFrame>12000')
            page.keyboard.press('F8')
            page.wait_for_function('!LV.playing && pausedTransport?.engine==="live"')
            # Wait for the worklet's last position delivery before comparing.
            page.wait_for_timeout(150)
            frame = page.evaluate('LV.pos.scoreFrame')
            history = page.evaluate('[S.undo,S.redo]')
            for action, track in (('track-next','guitar2'),('track-last','drums'),
                                  ('track-previous','bass'),('track-first','guitar')):
                page.click('[data-action='+action+']')
                self.assertEqual(page.input_value('#part-sound-track'), track)
                self.assertTrue(page.is_checked('[data-ui=follow]'))
                self.assertEqual(page.evaluate('LV.pos.scoreFrame'), frame)
                page.wait_for_selector('.vt-tab-playhead[data-track='+track+']:not([hidden])')
            page.locator('#tab-editor').focus()
            page.keyboard.press('Control+Shift+ArrowDown')
            self.assertEqual(page.input_value('#part-sound-track'), 'guitar2')
            page.keyboard.press('F5')
            page.wait_for_function('frame=>LV.playing && !pausedTransport && LV.pos.scoreFrame>frame', arg=frame)
            channels = source['score']['tracks']['guitar2']['channels']
            page.click('#part-sound-mute')
            page.wait_for_function('chs=>chs.every(c=>S.muted.includes(c))', arg=channels)
            page.select_option('#part-sound-track', 'bass')
            page.click('#part-sound-solo')
            expected = [c for c in range(19) if c not in source['score']['tracks']['bass']['channels']]
            page.wait_for_function('xs=>JSON.stringify(S.muted)===JSON.stringify(xs)', arg=expected)
            page.locator('#part-sounds').get_by_role('button', name='Clear mutes').click()
            page.wait_for_function('!S.muted.length && S.solo==null')
            page.wait_for_selector('.vt-tab-playhead[data-track=bass]:not([hidden])')
            page.keyboard.press('Escape')
            page.wait_for_function('!LV.playing && !pausedTransport')
            self.assertEqual(page.evaluate('[S.undo,S.redo]'), history)
            self.assertEqual(state.song_path.read_bytes(), original)

    def test_keyboard_play_from_native_caret_keeps_fractional_row(self):
        with self.muted_page(helpers.NATIVE_SONG) as (page, state, folder):
            print(self.run_keyboard_caret(page, state.song_path))

    def run_keyboard_caret(self, page, path):
        original = path.read_bytes()
        page.click('[data-t=tab]')
        page.wait_for_selector('.vt-tab-grid-details', state='attached')
        grid_open = page.locator('.vt-tab-grid-details').evaluate('e=>e.open')
        page.locator('.vt-tab-grid-details').evaluate('e=>e.open=true')
        page.wait_for_selector('.vt-tab-grid [data-note=note-1]')
        page.wait_for_function('SCORE.view && !SCORE.fetching && !SCORE.pending')
        page.click('.vt-tab-grid [data-note=note-1]')
        assert page.evaluate('CUR.score.row') == [48,13]
        page.evaluate("""async()=>{
          await lvStart();window.caretPlays=[];
          const send=LV.node.port.postMessage.bind(LV.node.port);
          LV.node.port.postMessage=(m,...args)=>{if(m.type==='play')caretPlays.push(m);return send(m,...args)};
        }""")
        for key in ('Control+F6', 'Control+F7'):
            page.evaluate('caretPlays=[]')
            page.keyboard.press(key)
            page.wait_for_function('caretPlays.length && LV.playing')
            assert page.evaluate('caretPlays[0].row') == [48,13], key
            page.keyboard.press('Escape')
            page.wait_for_function('!LV.playing')
            page.click('.vt-tab-grid [data-note=note-1]')
        assert path.read_bytes() == original
        page.locator('.vt-tab-grid-details').evaluate('(e,open)=>e.open=open', grid_open)
        return dict(song_and_pattern_cursor_keys=True, exact_native_start=[48,13], song_unchanged=True)

    def test_rendered_playback_part_voice_and_pause_resume(self):
        with self.muted_page(api.to_yaml(adaptation_song()), compact=True) as (page, state, folder):
            original = state.song_path.read_bytes()
            page.click('[data-t=tab]')
            page.wait_for_selector('.vt-tab-score svg')
            page.wait_for_function("S.own?.status==='ready' && audio.readyState>=2")
            page.locator('#part-sounds > summary').click()
            page.click('#playbtn')
            page.wait_for_function('!audio.paused && audio.currentTime>0.2')
            self.assertFalse(page.evaluate('LV.playing'))
            page.select_option('#part-sound-track', 'drums')
            page.select_option('[data-ui=voice]', label='2')
            self.assertTrue(page.is_checked('[data-ui=follow]'))
            page.wait_for_selector('.vt-tab-playhead[data-track=drums]:not([hidden])')
            first = page.get_attribute('.vt-tab-playhead', 'data-score-at')
            page.wait_for_function("at=>document.querySelector('.vt-tab-playhead')?.dataset.scoreAt!==at", arg=first)
            page.click('#playbtn')
            page.wait_for_function('audio.paused')
            paused = page.evaluate('audio.currentTime')
            page.select_option('#part-sound-track', 'bass')
            self.assertEqual(page.evaluate('audio.currentTime'), paused)
            page.click('#playbtn')
            page.wait_for_function('t=>!audio.paused && audio.currentTime>t', arg=paused)
            page.wait_for_selector('.vt-tab-playhead[data-track=bass]:not([hidden])')
            page.locator('#tab-editor').focus()
            page.keyboard.press('Escape')
            page.wait_for_function('audio.paused && !LV.playing')
            self.assertEqual(state.song_path.read_bytes(), original)

    def run_adaptation(self, page, path):
        helper = helpers.TestTablaturePage()
        original = path.read_bytes()
        errors = []
        page.on('pageerror', lambda e: errors.append(str(e)))
        page.evaluate("tab('tab');setEdit(true)")
        page.wait_for_selector('[data-ui=track]')
        page.select_option('[data-ui=track]', 'guitar')
        helper.capture_engraving(page)
        helper.open_setup(page)
        assert page.is_checked('[data-ui=auto-channels]')
        assert page.is_disabled('[data-ui=channels]')
        revision = page.evaluate('SCORE.view.revision')
        page.fill('[data-ui=tuning]', 'E4 B3 G3 D3 A2 D2 B1')
        page.fill('[data-ui=display-name]', 'Seven-string lead')
        page.fill('[data-ui=midi-program]', '27')
        with page.expect_response('**/api/score_command') as response:
            page.locator('.vt-tab-setup button[type=submit]').first.click()
        result = response.value.json()
        assert result.get('ok'), result
        helper.settled(page, "SCORE.view.score.tracks.guitar.channels.length===7")
        saved = path.read_bytes()
        song = api.from_yaml(saved.decode('utf-8'))
        track = song['score']['tracks']['guitar']
        assert track['name'] == 'Seven-string lead' and track['midi']['program'] == 27
        assert track['channels'] == [0, 1, 2, 3, 4, 5, 19]
        assert page.input_value('[data-ui=channels]') == '1,2,3,4,5,6,20'
        helper.settled(page, 'window.tabRenderedRevision===SCORE.view.revision&&tabRenderApi.boundsLookup.isFinished')
        assert 'rendering failed' not in page.inner_text('.vt-tab-status')
        page.click('[data-action=undo]')
        helper.settled(page, 'SCORE.view.revision==='+json.dumps(revision))
        assert path.read_bytes() == original
        page.click('[data-action=redo]')
        helper.settled(page, 'SCORE.view.score.tracks.guitar.channels.length===7')
        assert path.read_bytes() == saved
        # Reduce again without discarding the newly allocated raw channel.
        helper.open_setup(page)
        page.fill('[data-ui=tuning]', '64 59 55 50 45 40')
        page.locator('.vt-tab-setup button[type=submit]').first.click()
        helper.settled(page, 'SCORE.view.score.tracks.guitar.channels.length===6')
        reduced = api.from_yaml(path.read_text(encoding='utf-8'))
        assert len(reduced['module']['channels']) == 20
        page.click('[data-action=undo]')
        helper.settled(page, 'SCORE.view.score.tracks.guitar.channels.length===7')
        assert path.read_bytes() == saved
        page.click('[data-action=undo]')
        helper.settled(page, 'SCORE.view.revision==='+json.dumps(revision))
        assert path.read_bytes() == original
        for count in (12, 25):
            helper.open_setup(page)
            page.fill('[data-ui=tuning]', '64 59 55 50 45 40' + ' 35' * (count - 6))
            page.locator('.vt-tab-setup button[type=submit]').first.click()
            helper.settled(page, f'SCORE.view.score.tracks.guitar.channels.length==={count}')
            helper.settled(page, 'window.tabRenderedRevision===SCORE.view.revision&&tabRenderApi.boundsLookup.isFinished')
            assert 'rendering failed' not in page.inner_text('.vt-tab-status')
            page.click('[data-action=undo]')
            helper.settled(page, 'SCORE.view.revision==='+json.dumps(revision))
            assert path.read_bytes() == original
        assert not errors, errors
        return dict(automatic_seven_strings=True, combined_metadata=True,
                    exact_undo_redo=True, raw_channels_preserved=True, page_errors=errors)

    def test_track_setup_and_exact_history(self):
        with self.muted_page(api.to_yaml(adaptation_song()), width=1600, height=1000) as (page, state, folder):
            self.assertFalse(state.error, state.error)
            print(self.run_adaptation(page, state.song_path))


if __name__ == '__main__': unittest.main()
