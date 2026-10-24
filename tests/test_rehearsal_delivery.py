"""Song credits, reusable blank setup and finished parts use the shared native document."""
import copy
import os
import tempfile
import unittest
from pathlib import Path

from vulturetracker import api, gui, tablature, tgimport, gpexport, gpimport
from tests.test_tablature_sync import complete_song_seed
from tests.test_gui import RATE, sine
from vulturetracker.wavload import write_wav


CREDITS = dict(title='Rehearsal study', artist='VultureTracker', album='Original studies', author='Composer',
               date='2026', copyright='Original example', writer='Writer', transcriber='Editor', comments='First line\nSecond line')


class TestRehearsalCredits(unittest.TestCase):
    def test_metadata_history_export_and_audio_neutrality(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'song.yaml'
            write_wav(path.parent / 'tone.wav', RATE, [sine(440)])
            path.write_text(api.to_yaml(complete_song_seed()), encoding='utf-8', newline='\n')
            state = gui.State(path, headless=True)
            try:
                self.assertFalse(state.error, state.error)
                before = path.read_bytes()
                plan = copy.deepcopy(state.mod.native_score['plan'])
                state.score_edit(dict(op='metadata_set', value=CREDITS, revision=state.text_sha()))
                after = path.read_bytes()
                self.assertEqual(state.mod.native_score['plan'], plan)
                self.assertEqual(state.score_view()['title'], CREDITS['title'])
                routes = {tid:dict(program=t['midi']['program'], bank=t['midi'].get('bank',0)) for tid,t in state.song['score']['tracks'].items()}
                tg, _ = tgimport.native_to_tg(state.song, tgimport._raw(state.song), channels=routes)
                self.assertEqual(tgimport.read_tg(tg)[0]['score']['metadata'], CREDITS)
                gp, report = gpexport.native_to_gp5(state.song, tgimport._raw(state.song), channels=routes)
                reopened = gpimport._native_gp_song(gpimport._read_native_gp(gp), CREDITS['title'])
                self.assertEqual(reopened['score']['metadata'], {k:v for k,v in CREDITS.items() if k!='date'})
                self.assertTrue(any('date' in w for w in report['warnings']))
                state.undo(); self.assertEqual(path.read_bytes(), before)
                state.undo(redo=True); self.assertEqual(path.read_bytes(), after)
                with self.assertRaises(ValueError):
                    state.score_edit(dict(op='metadata_set', value={'title':'bad\x00'}, revision=state.text_sha()))
                self.assertEqual(path.read_bytes(), after)
            finally:
                state.close()

    def test_unicode_credits_tg_roundtrip(self):
        song = complete_song_seed()
        value = dict(CREDITS, title='Étude — 夜', author='Zoë')
        song = tablature.apply_score_edit(song, dict(op='metadata_set',value=value))
        routes = {tid:dict(program=t['midi']['program'],bank=t['midi'].get('bank',0)) for tid,t in song['score']['tracks'].items()}
        data, _ = tgimport.native_to_tg(song,tgimport._raw(song),channels=routes)
        self.assertEqual(tgimport.read_tg(data)[0]['score']['metadata'],value)


class TestRehearsalDeliveryPage(unittest.TestCase):
    def test_properties_template_and_print(self):
        from tests import test_tablature_page as page_tests
        helper = page_tests.TestTablaturePage()
        source = complete_song_seed()
        for sample in source['samples'].values(): sample['file']='a.wav'
        with helper.muted_page(api.to_yaml(source), width=1600,height=1000) as (page,state,folder):
            errors=[]; page.on('pageerror',lambda error:errors.append(str(error)))
            page.evaluate("tab('tab');setEdit(true)")
            page.wait_for_selector('[data-action=properties]')
            original=state.song_path.read_bytes()
            page.click('[data-action=properties]')
            for key,value in CREDITS.items(): page.fill(f'[data-credit={key}]',value)
            with page.expect_response('**/api/score') as response:
                page.click('[data-panel=properties] button[type=submit]')
            self.assertTrue(response.value.json().get('ok'),response.value.json())
            helper.settled(page,"SCORE.view.score.metadata?.title==='Rehearsal study'")
            page.click('[data-action=properties]'); page.fill('[data-ui=template-name]','Test band setup')
            with page.expect_response('**/api/score_template') as response: page.click('[data-action=save-template]')
            self.assertEqual(len(response.value.json()['template']['tracks']),4)
            page.wait_for_function("JSON.parse(localStorage.getItem('vt-score-templates')||'{}')['Test band setup']")
            page.click('[data-action=close-properties]')
            preview=page.context.browser.new_page(viewport={'width':1600,'height':1000})
            try:
                printer=page_tests.TestScoreDeliveryPage()
                preview.goto(printer.print_url(page,state)); printer.print_ready(preview)
                self.assertEqual(preview.input_value('[name=composer]'),CREDITS['author'])
                self.assertIn(CREDITS['artist'],preview.input_value('[name=subtitle]'))
                self.assertTrue(preview.locator('.vt-print-footer').count())
                self.assertIn('1 / ',preview.locator('.vt-print-footer').first.text_content())
                output=Path(os.environ.get('VT_REHEARSAL_EXPORTS',folder/'exports'))
                output.mkdir(parents=True,exist_ok=True)
                preview.locator('.vt-print-page').nth(min(1,preview.locator('.vt-print-page').count()-1)).screenshot(path=str(output/'expected.png'))
                printer.export_preview(preview,output)
            finally: preview.close()
            page.locator('#tab-editor').focus(); page.keyboard.press('Control+z')
            helper.settled(page,"!SCORE.view.score.metadata")
            self.assertEqual(state.song_path.read_bytes(),original)
            page.evaluate("toggle('start',true)")
            page.fill('#newpath',str(folder/'new-band.yaml')); page.select_option('#newtemplate','custom:Test band setup')
            page.fill('#newbars','8')
            with page.expect_response('**/api/new') as response: page.locator('#newpath').press('Enter')
            self.assertNotIn('error',response.value.json())
            page.wait_for_function("S?.song?.path.endsWith('new-band.yaml')&&SCORE.view?.score?.order_ids.length===8")
            self.assertEqual(page.evaluate('Object.keys(SCORE.view.score.tracks).length'),4)
            self.assertEqual(page.evaluate('SCORE.view.score.metadata.title'),CREDITS['title'])
            self.assertFalse(errors,errors)


if __name__ == '__main__': unittest.main()
