"""New finishing/sharing controls exercised through a real browser, on a synthetic song."""
import os
from fractions import Fraction
from pathlib import Path
import tempfile
import threading
import time
import unittest

from vulturetracker import api, gui
from tests import test_release100_page as page_fixture
from vulturetracker.server import Handler, _Server
from vulturetracker.wavload import write_wav
from tests.test_gui import SONG_BLOCK, sine, RATE

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    sync_playwright = None


@unittest.skipIf(sync_playwright is None, 'Playwright is unavailable')
class TestWorkflowPage(unittest.TestCase):
    def test_finishing_workflow_and_audio_playback(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            original = folder / 'original'
            original.mkdir()
            for name, hz in [('a', 440), ('b', 880)]:
                write_wav(original / (name+'.wav'), RATE, [sine(hz)])
            song = original / 'song.yaml'
            song.write_bytes(SONG_BLOCK.encode())
            st = Handler.state = gui.State(song)
            server = _Server(('127.0.0.1', 0), Handler)
            threading.Thread(target=server.serve_forever, daemon=True).start()
            errors, dialogs = [], []
            try:
                with sync_playwright() as pw:
                    browser = pw.chromium.launch(executable_path=os.environ.get('VT_CHROMIUM') or None)
                    page = browser.new_page(viewport={'width': 1600, 'height': 1000})
                    page.on('pageerror', lambda e: errors.append(str(e)))
                    page.on('dialog', lambda d: (dialogs.append(d.message), d.accept()))
                    page.goto(f'http://127.0.0.1:{server.server_address[1]}/?token={server.token}')
                    page.wait_for_function('S?.song?.facts && PAT.rows')
                    page.click('[data-t="project"]')
                    page.fill('#checkpoint-name', 'Before arrangement')
                    page.get_by_role('button', name='SAVE CHECKPOINT', exact=True).click()
                    page.wait_for_function("S.checkpoints.includes('Before arrangement')")
                    page.click('[data-t="song"]')
                    page.fill('#section-name', 'Intro')
                    page.get_by_role('button', name='SAVE NAME / SPAN').click()
                    page.wait_for_function('S.sections.Intro')
                    page.fill('#section-to', '2')
                    page.get_by_role('button', name='DUPLICATE SECTION').click()
                    page.wait_for_function('S.structure.orders.length === 3')
                    page.click('[data-t="pattern"]')
                    page.wait_for_function('PAT.rows?.length === 4')
                    page.click('[data-t="phrases"]')
                    page.get_by_role('button', name='NEW COMPARISON FROM PATTERN SELECTION').click()
                    page.wait_for_function('S.phrase?.variants?.length === 3')
                    page.fill('#phrase-name', 'Our line')
                    page.fill('#phrase-data', 'D-5 01 ... ...\n... .. ... ...\n... .. ... ...\n... .. ... ...')
                    page.fill('#phrase-stars', '4')
                    page.fill('#phrase-note', 'Disposable browser check')
                    page.get_by_role('button', name='SAVE ALTERNATIVE / RATING / NOTE').click()
                    page.wait_for_function("S.phrase.variants[0].name === 'Our line'")
                    page.get_by_role('button', name='▶ Our line', exact=True).click()
                    page.wait_for_function("!$('phrase-audio').paused && $('phrase-audio').currentTime > .05")
                    self.assertGreater(page.eval_on_selector('#phrase-audio', 'a=>a.duration'), .4)
                    page.get_by_role('button', name='▶ Line absent', exact=True).click()
                    page.wait_for_function("!$('phrase-audio').paused && $('phrase-audio').readyState >= 3")
                    page.get_by_role('button', name='YAML DIFF / ACCEPT').click()
                    page.wait_for_selector('#workflowmodal.on')
                    self.assertIn('D-5', page.text_content('#workflow-diff'))
                    page.click('#workflow-confirm')
                    page.wait_for_function('S.phrase.accepted === 0')
                    page.click('[data-t="project"]')
                    page.get_by_role('button', name='UNDO', exact=True).click()
                    page.wait_for_function('S.redo === 1')
                    page.get_by_role('button', name='REDO', exact=True).click()
                    page.wait_for_function('S.redo === 0')
                    page.click('[data-t="export"]')
                    page.fill('#export-dest', str(folder / 'exports'))
                    page.select_option('#export-format', 'wav')
                    page.select_option('#export-region', 'Intro')
                    page.select_option('#export-tail-mode', 'cut')
                    page.check('#export-stems')
                    page.click('#export-go')
                    page.wait_for_function("S.export?.status === 'done'", timeout=20000)
                    self.assertEqual(len(st.export_result['files']), 3)
                    page.click('[data-t="project"]')
                    page.fill('#collect-dest', str(folder / 'collected'))
                    page.check('#collect-zip')
                    page.get_by_role('button', name='COLLECT SAMPLES & SAVE COPY').click()
                    page.wait_for_function("$('collect-result').textContent.includes('Original untouched')")
                    self.assertTrue((folder / 'collected.zip').is_file())
                    # External edit is compared, then loaded without stale history.
                    song.write_bytes(song.read_bytes() + b'# external browser check\n')
                    page.wait_for_selector('#dirty', state='visible')
                    page.click('#dirty')
                    page.wait_for_selector('#workflowmodal.on')
                    self.assertIn('external browser check', page.text_content('#workflow-diff'))
                    page.click('#workflow-confirm')
                    page.wait_for_function('S.undo === 0 && !S.song.dirty')
                    # Exercise the AudioWorklet too, beyond HTML audio and API success.
                    page.evaluate("$('phrase-audio').pause(); tab('pattern'); lvPlay(0,0)")
                    page.wait_for_function('LV.playing && LV.pos && LV.pos.row > 0', timeout=10000)
                    page.evaluate('lvStop()')
                    browser.close()
                self.assertEqual(errors, [])
                self.assertTrue(all('External reload:' in d for d in dialogs), dialogs)
            finally:
                server.shutdown()
                server.server_close()
                Handler.state = None
                for _ in range(200):
                    if not st.jobs.qsize() and not any(r['status'] in ('queued', 'rendering') for r in st.renders.values()):
                        break
                    time.sleep(.02)
                st.close()


@unittest.skipIf(sync_playwright is None, 'Playwright is unavailable')
class TestNativeMidiPage(unittest.TestCase):
    page = page_fixture.TestRelease100Page.page

    def song(self, unsupported=False):
        from tests.test_tablature_sync import score_song
        doc = score_song()
        doc['module'].update(title='Native MIDI page', tempo=137)
        doc['module']['channels'] = doc['module']['channels'][:2]
        doc['samples'][1]['file'] = 'a.wav'
        track = doc['score']['tracks']['guitar']
        track['tuning'], track['channels'] = [64, 59], [0, 1]
        doc['patterns']['a']['data'] = '00: ... .. ... D07' if unsupported else ''

        def beat(identity, at, value, string, fret, voice=0, **technique):
            return {'id': identity, 'track': 'guitar', 'voice': voice, 'at': at,
                    'written': {'value': value},
                    'notes': [{'id': identity + '_note', 'string': string, 'fret': fret,
                               'pitch': track['tuning'][string - 1] + fret, **technique}]}

        tuplet = beat('tuplet', [3, 13], 8, 1, 0)
        tuplet['written']['tuplet'] = [13, 8]
        doc['score']['patterns']['a']['beats'] = [
            tuplet, beat('staccato', [1, 1], 4, 2, 0, voice=1, staccato=True),
            beat('palm', [2, 1], 4, 2, 1, voice=1, palm_mute=True),
            beat('dead', [3, 1], 4, 2, 2, voice=1, dead=True), beat('tie_a', [7, 2], 8, 1, 1)]
        doc['score']['patterns']['b']['beats'] = [beat('tie_b', [0, 1], 8, 1, 1)]
        doc['score']['ties'] = [{'from': {'occurrence': 'first', 'note': 'tie_a_note'},
                                'to': {'occurrence': 'second', 'note': 'tie_b_note'}}]
        return api.to_yaml(doc)

    def source(self, st, folder):
        return st.text, api.to_yaml(st.song), {name: (folder / name).read_bytes()
                                             for name in ('song.yaml', 'a.wav', 'b.wav')}

    def test_native_midi_exact_file_visible_report_and_unchanged_source(self):
        import mido
        with self.page(self.song(), width=1600, height=1000) as (page, st, folder):
            before = self.source(st, folder)
            console_errors, dialogs = [], []
            page.on('console', lambda msg: console_errors.append(msg.text) if msg.type == 'error' else None)
            page.on('dialog', lambda dialog: (dialogs.append(dialog.message), dialog.accept()))
            page.click('[data-t="export"]')
            page.fill('#export-dest', str(folder / 'midi-output'))
            page.fill('#export-name', 'exact-native')
            page.select_option('#export-format', 'mid')
            # Keep the finite audio tail selected: its omission must be visible.
            page.click('#export-go')
            page.wait_for_function("S.export?.status === 'done' || S.export?.status === 'failed'", timeout=20000)
            self.assertEqual(st.export_result['status'], 'done', st.export_result)
            report = page.locator('#export-result')
            self.assertTrue(report.is_visible())
            visible = report.inner_text()
            self.assertIn('MIDI: 5 notes · 2 channels · exact beat timing', visible)
            self.assertIn('tempo 137.000064 BPM', visible)
            self.assertIn('Warning: MIDI destination sounds are unspecified', visible)
            self.assertIn('fingering', visible)
            self.assertIn('Sample sound', visible)
            self.assertIn('Finite audio tail (2 seconds) omitted', visible)
            conversion = st.export_result['conversion']
            self.assertEqual((conversion['ppq'], conversion['quantized_events']), (12480, 0))

            path = folder / 'midi-output' / 'exact-native.mid'
            self.assertEqual(st.export_result['files'], [str(path)])
            midi = mido.MidiFile(path, charset='utf-8')
            self.assertEqual((midi.type, midi.ticks_per_beat), (1, 12480))
            notes, ends, tempos = {}, [], []
            for track in midi.tracks:
                tick = 0
                for message in track:
                    tick += message.time
                    at = Fraction(tick, midi.ticks_per_beat)
                    if message.type in ('note_on', 'note_off'):
                        notes.setdefault(message.channel, []).append((at, message.type, message.note))
                    elif message.type == 'end_of_track':
                        ends.append(at)
                    elif message.type == 'set_tempo':
                        tempos.append(message.tempo)
            self.assertEqual(notes, {
                0: [(Fraction(3, 13), 'note_on', 64), (Fraction(7, 13), 'note_off', 64),
                    (Fraction(7, 2), 'note_on', 65), (Fraction(9, 2), 'note_off', 65)],
                1: [(Fraction(1), 'note_on', 59), (Fraction(3, 2), 'note_off', 59),
                    # TG gates at 137 BPM: palm 137/960 quarters, dead floor(137/2)/960.
                    (Fraction(2), 'note_on', 60), (Fraction(2057, 960), 'note_off', 60),
                    (Fraction(3), 'note_on', 61), (Fraction(737, 240), 'note_off', 61)]})
            self.assertEqual((ends, tempos), ([Fraction(8)] * 3, [437956]))
            self.assertEqual(self.source(st, folder), before)
            self.assertEqual((console_errors, dialogs), ([], []))

    def test_native_midi_unsupported_control_shows_refusal_without_output(self):
        with self.page(self.song(unsupported=True)) as (page, st, folder):
            before = self.source(st, folder)
            destination = folder / 'refused-midi'
            page.on('dialog', lambda dialog: dialog.accept())
            page.click('[data-t="export"]')
            page.fill('#export-dest', str(destination))
            page.fill('#export-name', 'unsupported')
            page.select_option('#export-format', 'mid')
            with page.expect_response(lambda response: response.url.endswith('/api/export')) as response:
                with page.expect_event('dialog') as refusal:
                    page.click('#export-go')
            self.assertEqual(response.value.status, 400)
            self.assertIn('Native MIDI: first row 0 channel 1: Dxx', refusal.value.message)
            self.assertIn('qualified shared-engine control trace', refusal.value.message)
            self.assertIsNone(st.export_result)
            self.assertIsNone(st.export_job)
            self.assertFalse(destination.exists())
            self.assertFalse(list(folder.rglob('*.mid')))
            self.assertEqual(self.source(st, folder), before)
