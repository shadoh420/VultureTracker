"""Real import -> native edit -> save/reopen guards for the shared score workflow."""
import io
import json
import tempfile
import unittest
from pathlib import Path

import mido

from vulturetracker import api, export, gpimport, gpexport, gui, midiimport, tablature, tgimport
from tests import test_gpx
from tests import test_tablature_page as tab_page


def midi_bytes():
    mid = mido.MidiFile(type=1, ticks_per_beat=480)
    mid.tracks.append(mido.MidiTrack([
        mido.MetaMessage('track_name', name='Import study'),
        mido.MetaMessage('set_tempo', tempo=625000),
        mido.MetaMessage('time_signature', numerator=4, denominator=4),
        mido.MetaMessage('end_of_track', time=1920)]))
    mid.tracks.append(mido.MidiTrack([
        mido.MetaMessage('track_name', name='Guitar'),
        mido.Message('program_change', program=25),
        mido.Message('note_on', note=64, velocity=95),
        mido.Message('note_off', note=64, velocity=0, time=480),
        mido.Message('note_on', note=67, velocity=79),
        mido.Message('note_off', note=67, velocity=0, time=480),
        mido.MetaMessage('end_of_track', time=960)]))
    data = io.BytesIO(); mid.save(file=data)
    return data.getvalue()


def midi_workflow_bytes():
    mid=mido.MidiFile(type=0,ticks_per_beat=480)
    track=mido.MidiTrack([mido.MetaMessage('track_name',name='MIDI import options'),
        mido.Message('program_change',program=25),mido.Message('control_change',control=7,value=63),
        mido.Message('control_change',control=10,value=15)])
    for bar in range(4):
        for index,duration in enumerate((160,160,160,240,240,480,480)):
            pitch=64+(bar+index)%5
            track.extend([mido.Message('note_on',note=pitch,velocity=95),
                          mido.Message('note_off',note=pitch,time=duration)])
    track.append(mido.MetaMessage('end_of_track'))
    mid.tracks.append(track)
    out=io.BytesIO();mid.save(file=out);return out.getvalue()


class TestRealInterchange(unittest.TestCase):
    def test_native_midi_options_dispatch_collection_cli_and_controller_preservation(self):
        from vulturetracker import score_collection
        import subprocess,sys
        data=midi_workflow_bytes()
        settings=dict(transpose=12,quantize=True,max_duration=32,max_division=3)
        expected,_=midiimport.read_midi_score(data,**settings)
        baseline,_=midiimport.read_midi_score(data,max_duration=32,max_division=3)
        def notes(song):
            return [n['pitch'] for p in song['score']['patterns'].values() for b in p['beats'] for n in b['notes']]
        self.assertEqual(notes(expected),[n+12 for n in notes(baseline)])
        self.assertEqual(len(notes(expected)),28)
        with tempfile.TemporaryDirectory() as temporary:
            folder=Path(temporary);source=folder/'input.mid';source.write_bytes(data)
            target,_=gui.import_song(source,folder/'single.yaml',folder/'samples',native_tab=True,midi_options=settings)
            actual=api.from_yaml(target.read_text(encoding='utf-8'))
            self.assertEqual(actual['score'],expected['score'])
            self.assertEqual(tgimport.track_midi_mix(actual,actual['score']['tracks']['t1']),dict(volume=63,pan=15))
            result=score_collection.convert(dict(paths=[str(source)],destination=str(folder/'batch'),format='yaml',midi_options=settings))[0]
            self.assertEqual(result['status'],'done',result)
            self.assertEqual(api.from_yaml(Path(result['files'][0]).read_text(encoding='utf-8'))['score'],expected['score'])
            run=subprocess.run([sys.executable,'-m','vulturetracker','import',str(source),'-o',str(folder/'cli.yaml'),
                '--native-tab','--midi-transpose','12','--midi-shortest','32','--midi-tuplet','3'],capture_output=True,text=True)
            self.assertEqual(run.returncode,0,run.stdout+run.stderr)
            self.assertEqual(api.from_yaml((folder/'cli.yaml').read_text(encoding='utf-8'))['score'],expected['score'])
            self.exercise_edit(target)
            self.assertEqual(source.read_bytes(),data)

    def test_invalid_midi_settings_are_atomic(self):
        from vulturetracker import score_collection
        invalid=[[],dict(transpose=25),dict(transpose=True),dict(quantize='false'),dict(max_duration=3),
                 dict(max_division=True),dict(max_division=2),dict(unknown=1)]
        with tempfile.TemporaryDirectory() as temporary:
            folder=Path(temporary);source=folder/'input.mid';source.write_bytes(midi_bytes())
            for settings in invalid:
                with self.subTest(settings=settings):
                    with self.assertRaises(ValueError):
                        gui.import_song(source,folder/'bad.yaml',folder/'samples',native_tab=True,midi_options=settings)
                    with self.assertRaises(ValueError):
                        score_collection.convert(dict(paths=[str(source)],destination=str(folder/'batch'),midi_options=settings))
                    self.assertFalse((folder/'bad.yaml').exists());self.assertFalse((folder/'samples').exists())
                    self.assertFalse((folder/'batch').exists())

    def test_midi_controller_automation_reports_final_neutral_values(self):
        mid=mido.MidiFile(file=io.BytesIO(midi_workflow_bytes()))
        mid.tracks[0][-1:-1]=[mido.Message('control_change',control=7,value=127),mido.Message('control_change',control=10,value=64)]
        out=io.BytesIO();mid.save(file=out)
        song,notices=midiimport.read_midi_score(out.getvalue())
        self.assertEqual(tgimport.track_midi_mix(song,song['score']['tracks']['t1']),dict(volume=127,pan=64))
        self.assertTrue(any('2 volume/pan changes folded' in n for n in notices),notices)

    def test_native_midi_track_boundary_and_explicit_import_dispatch(self):
        data = midi_bytes()
        resolution, tracks = midiimport._smf(data)
        self.assertEqual(resolution, 480)
        self.assertEqual(len(tracks), 2)
        self.assertEqual(tracks[0][-1], (1920, 'meta', (47, b'')))
        self.assertEqual(tracks[1][-1], (1920, 'meta', (47, b'')))
        with self.assertRaises(ValueError):
            midiimport.read_midi_score(data[:-1])
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary); source = folder / 'input.mid'
            source.write_bytes(data)
            target, warnings = gui.import_song(source, folder/'score.yaml', folder/'samples', native_tab=True)
            song = api.from_yaml(target.read_text(encoding='utf-8'))
            self.assertTrue(any(w.startswith('MIDI notation imported with synthesized placeholders') for w in warnings))
            self.assertIn('score', song)
            self.assertEqual(len(song['score']['tracks']), 1)
            self.assertEqual(sum(len(b['notes']) for p in song['score']['patterns'].values() for b in p['beats']), 2)
            self.assertEqual(next(iter(song['score']['tracks'].values()))['midi']['program'], 25)
            self.exercise_edit(target)
            before = target.read_bytes()
            for native in (True,False):
                with self.assertRaisesRegex(ValueError, 'fresh destination'):
                    gui.import_song(source, target, folder/'samples', native_tab=native)
            self.assertEqual(target.read_bytes(), before)
            self.assertEqual(source.read_bytes(), data)
            beside, _ = gui.import_beside(source, native_tab=True)
            self.assertIn('score', api.from_yaml(beside.read_text(encoding='utf-8')))

    def exercise_edit(self, target):
        state = gui.State(target, headless=True)
        try:
            self.assertFalse(state.error, state.error)
            before = target.read_bytes()
            pattern, beat = next((p,b) for p,s in state.song['score']['patterns'].items() for b in s['beats'] if b['notes'])
            note = beat['notes'][0]
            state.score_edit(dict(op='note_set', pattern=pattern, beat=beat['id'],
                note=dict(id=note['id'], pitch=note['pitch']+1), revision=state.text_sha()))
            changed = target.read_bytes()
            self.assertNotEqual(before, changed)
            state.undo(); self.assertEqual(target.read_bytes(), before)
            state.undo(redo=True); self.assertEqual(target.read_bytes(), changed)
            expected = state.song['score']
        finally:
            state.close()
        reopened = gui.State(target, headless=True)
        try:
            self.assertFalse(reopened.error, reopened.error)
            self.assertEqual(reopened.song['score'], expected)
        finally:
            reopened.close()

    def test_gp6_gp7_import_edit_and_native_tg_interchange(self):
        for version, extension, writer in [(6,'gpx',test_gpx.gp6),(7,'gp',test_gpx.gp7)]:
            with self.subTest(version=version), tempfile.TemporaryDirectory() as temporary:
                folder = Path(temporary); source = folder / ('input.'+extension)
                data = writer(test_gpx.fixture(version)); source.write_bytes(data)
                target, warnings = gui.import_song(source, folder/'score.yaml', folder/'samples', native_tab=True)
                self.exercise_edit(target)
                song = api.from_yaml(target.read_text(encoding='utf-8'))
                self.assertEqual((len(song['score']['tracks']),len(song['score']['measures'])), (2,3))
                self.assertEqual(sum(len(b['notes']) for p in song['score']['patterns'].values() for b in p['beats']),23)
                self.assertTrue(any('Lyrics' in w for w in warnings))
                self.assertEqual(source.read_bytes(),data)
                # Export-only rests retain the imported pickup on TG opening.
                routes = {tid:dict(program=t['midi']['program'],bank=t['midi'].get('bank',0))
                    for tid,t in song['score']['tracks'].items()}
                data, report = tgimport.native_to_tg(song,tgimport._raw(song),channels=routes)
                from tests.test_complex_interchange import sounding
                self.assertGreater(report['generated_rests'], 0)
                self.assertEqual(sounding(tgimport.read_tg(data)[0]), sounding(song))


class TestRealInterchangePage(unittest.TestCase):
    page = tab_page.TestTablaturePage.page
    muted_page = tab_page.TestTablaturePage.muted_page
    settled = tab_page.TestTablaturePage.settled
    capture_engraving = tab_page.TestTablaturePage.capture_engraving
    click_tab_lane = tab_page.TestTablaturePage.click_tab_lane
    tab_lane_point = staticmethod(tab_page.TestTablaturePage.tab_lane_point)

    def run_imported_edits(self, page, song_path):
        """Actual rendered note edit, exact Undo/Redo; restores this imported song."""
        before = song_path.read_bytes()
        song = api.from_yaml(before.decode('utf-8'))
        first_track = next(iter(song['score']['tracks']))
        pattern = song['orders'][0]
        beat = next(b for b in song['score']['patterns'][pattern]['beats']
            if b['track']==first_track and b['voice']==0 and b['notes'])
        note = beat['notes'][0]
        page.evaluate("tab('tab');setEdit(true)")
        page.wait_for_selector('[data-ui=track]',state='attached')
        self.capture_engraving(page)
        page.select_option('[data-ui=track]',list(song['score']['tracks'])[-1])
        page.select_option('[data-ui=track]',first_track)
        page.select_option('[data-ui=voice]','0')
        self.settled(page,'window.tabRendered&&tabRenderedRevision===SCORE.view.revision&&tabRenderApi.boundsLookup?.isFinished')
        revision = page.evaluate('SCORE.view.revision')
        # Sparse and pickup imports may have an explicit rest before this note.
        rendered_beat = page.evaluate('tabRendered.tracks[0].staves[0].bars[0].voices[0].beats.findIndex(b=>b.notes.length)')
        self.assertGreaterEqual(rendered_beat, 0)
        self.click_tab_lane(page,0,rendered_beat,note['string'])
        if page.locator('.vt-tab-inspector').get_attribute('open') is None:
            page.locator('.vt-tab-inspector > summary').click()
        with page.expect_response('**/api/score') as response:
            page.click('[data-action=pitch-up]')
        result=response.value.json();self.assertTrue(result.get('ok'),result)
        self.settled(page,'SCORE.view.revision==='+json.dumps(result['revision']))
        changed=song_path.read_bytes()
        edited=api.from_yaml(changed.decode('utf-8'))
        actual=next(n for b in edited['score']['patterns'][pattern]['beats'] if b['id']==beat['id'] for n in b['notes'] if n['id']==note['id'])
        self.assertEqual(actual['pitch'],note['pitch']+1)
        self.assertNotIn('refused',page.inner_text('.vt-tab-status'))
        page.click('[data-action=undo]');self.settled(page,'SCORE.view.revision==='+json.dumps(revision))
        self.assertEqual(song_path.read_bytes(),before)
        page.click('[data-action=redo]');self.settled(page,'SCORE.view.revision==='+json.dumps(result['revision']))
        self.assertEqual(song_path.read_bytes(),changed)
        page.click('[data-action=undo]');self.settled(page,'SCORE.view.revision==='+json.dumps(revision))
        self.assertEqual(song_path.read_bytes(),before)
        return dict(title=song.get('score',{}).get('metadata',{}).get('title'),restored=True)

    def test_actual_imported_study_note_controls(self):
        root=Path(__file__).resolve().parents[1]/'scratch/tab-test-fixtures/real-world'
        if not (root/'imported-tg/song.yaml').exists():self.skipTest('local imported study fixtures required')
        for fmt in ('tg','gp5','mid'):
            with self.subTest(format=fmt):
                source=root/('imported-'+fmt)/'song.yaml'
                song=api.from_yaml(source.read_text(encoding='utf-8'))
                for sample in song['samples'].values():sample['file']=str((source.parent/sample['file']).resolve())
                with self.muted_page(api.to_yaml(song),width=1920,height=1080) as (page,state,folder):
                    errors=[];page.on('pageerror',lambda error:errors.append(str(error)))
                    self.assertFalse(state.error,state.error)
                    self.run_imported_edits(page,folder/'song.yaml')
                    self.assertFalse(errors,errors)


if __name__ == '__main__':
    unittest.main()
