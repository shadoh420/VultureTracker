"""Real batch conversion preserves sources, isolates failures and never replaces outputs."""
from fractions import Fraction
from pathlib import Path
import tempfile
import threading
import unittest

from tests.test_gui import RATE, sine
from tests.test_tablature_sync import complete_song_seed
from vulturetracker import api, gui, score_collection, tablature
from vulturetracker.wavload import write_wav


def written_notes(song):
    tracks = list(song['score']['tracks'])
    return sorted((order, tracks.index(beat['track']), beat['voice'], Fraction(*beat['at']),
                   tablature.duration_quarters(beat['written']), note['pitch'])
                  for order, name in enumerate(song['orders'])
                  for beat in song['score']['patterns'][str(name)]['beats'] for note in beat['notes'])


class TestScoreCollection(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.source = self.root / 'originals'
        self.source.mkdir()
        self.path = self.source / 'study.yaml'
        self.song = complete_song_seed()
        self.song['score']['metadata'] = dict(title='Collection study', author='Original author', comments='Preserve this credit')
        self.path.write_text(api.to_yaml(self.song), encoding='utf-8', newline='\n')
        write_wav(self.source / 'tone.wav', RATE, [sine(440)])
        self.original = {path:path.read_bytes() for path in self.source.iterdir()}

    def unchanged(self):
        for path, data in self.original.items():
            self.assertEqual(path.read_bytes(), data)

    def test_native_midi_export_options_batch_cli_agent_and_atomic_failure(self):
        import contextlib,io,time
        import mido
        from vulturetracker import agent,export
        from vulturetracker.__main__ import main
        from tests.test_workflow import midi_export_options_song
        song=midi_export_options_song();song['samples'][1]['file']='tone.wav'
        self.path.write_text(api.to_yaml(song),encoding='utf-8',newline='\n')
        self.original[self.path]=self.path.read_bytes()
        settings=dict(transpose=12,strip=True)
        expected=export.native_to_midi(export.snapshot(song,self.source,tail=0),settings)[0]
        def musical(data):
            mid=mido.MidiFile(file=io.BytesIO(data));events=[]
            for track in mid.tracks:
                at=0
                for msg in track:
                    at+=msg.time
                    if not msg.is_meta:events.append((Fraction(at,mid.ticks_per_beat),msg.type,tuple(sorted(msg.dict().items()))))
            return events
        result=score_collection.convert(dict(paths=[str(self.path)],destination=str(self.root/'midi'),format='mid',midi_export=settings))[0]
        self.assertEqual(result['status'],'done',result)
        self.assertEqual(musical(Path(result['files'][0]).read_bytes()),musical(expected))
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(main(['export',str(self.path),'-f','mid','-o',str(self.root/'cli'),'--midi-transpose','12','--midi-strip','--tail','0']),0)
        self.assertEqual(musical((self.root/'cli'/'study.mid').read_bytes()),musical(expected))
        state=gui.State(self.path)
        try:
            out=agent.run(state,'export_song',dict(format='mid',destination='agent-output',midi_export=settings,tail=0))
            self.assertTrue(out.get('ok'),out)
            for _ in range(200):
                job=agent.run(state,'export_status',{})['job']
                if job['status'] in ('done','failed','cancelled'):break
                time.sleep(.02)
            self.assertEqual(job['status'],'done',job)
            self.assertEqual(musical(Path(job['files'][0]).read_bytes()),musical(expected))
            self.assertEqual(state.history,[])
        finally:state.close()
        for bad in (dict(transpose=25),dict(strip='yes'),dict(unknown=0)):
            target=self.root/'invalid'
            with self.assertRaises(ValueError):score_collection.convert(dict(paths=[str(self.path)],destination=str(target),format='mid',midi_export=bad))
            self.assertFalse(target.exists())
        self.unchanged()

    def test_gp_encoding_single_batch_cli_agent_and_atomic_failure(self):
        import contextlib,io,time
        from tests.test_gpimport import TestGuitarProEncoding
        from vulturetracker import agent,gpimport
        from vulturetracker.__main__ import main
        song=TestGuitarProEncoding.fixture('音楽')
        source=self.source/'japanese.gp5'
        data=TestGuitarProEncoding.convert(song,'utf-8')[0];source.write_bytes(data)
        path,_=gui.import_song(source,self.source/'japanese.yaml',self.source/'samples',native_tab=True,gp_encoding='utf-8')
        def verify(path,encoding=None):
            content=Path(path).read_bytes()
            actual=(gpimport._native_gp_song(gpimport._read_native_gp(content,encoding),'音楽') if encoding else api.from_yaml(content.decode('utf-8')))
            self.assertEqual(actual['score'],song['score'])
        verify(path)
        for fmt,src in [('yaml',source),('gp5',path)]:
            result=score_collection.convert(dict(paths=[str(src)],destination=str(self.root/fmt),format=fmt,gp_encoding='utf-8'))[0]
            self.assertEqual(result['status'],'done',result);verify(result['files'][0],'utf-8' if fmt=='gp5' else None)
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(main(['import',str(source),'-o',str(self.root/'cli.yaml'),'--native-tab','--gp-encoding','utf-8']),0)
            self.assertEqual(main(['export',str(path),'-f','gp5','-o',str(self.root/'cli-export'),'--gp-encoding','shift_jis']),0)
        verify(self.root/'cli.yaml');verify(self.root/'cli-export'/'japanese.gp5','shift_jis')
        before=path.read_bytes();state=gui.State(path)
        try:
            imported=agent.run(state,'import_project',dict(file='japanese.gp5',native_tab=True,gp_encoding='utf-8'))
            self.assertNotIn('error',imported,imported);verify(imported['path'])
            out=agent.run(state,'export_song',dict(format='gp5',destination='agent-output',gp_encoding='shift_jis'))
            self.assertTrue(out.get('ok'),out)
            for _ in range(200):
                job=agent.run(state,'export_status',{})['job']
                if job['status'] in ('done','failed','cancelled'):break
                time.sleep(.02)
            self.assertEqual(job['status'],'done',job);verify(job['files'][0],'shift_jis')
            self.assertEqual(state.history,[])
        finally:state.close()
        for invalid in ('utf-16','unknown',{}):
            with self.assertRaises(ValueError):score_collection.convert(dict(paths=[str(source)],destination=str(self.root/'invalid'),gp_encoding=invalid))
            self.assertFalse((self.root/'invalid').exists())
        result=score_collection.convert(dict(paths=[str(path)],destination=str(self.root/'unrepresentable'),format='gp5',gp_encoding='cp1252'))[0]
        self.assertEqual(result['status'],'failed',result);self.assertEqual(result['files'],[])
        self.assertFalse(list((self.root/'unrepresentable').rglob('*.gp5')))
        self.assertEqual(path.read_bytes(),before);self.assertEqual(source.read_bytes(),data);self.unchanged()

    def test_original_tg_native_and_collected_projects(self):
        result = score_collection.convert(dict(paths=[str(self.path)], destination=str(self.root/'tg'), format='tg'))[0]
        self.assertEqual(result['status'], 'done', result)
        self.assertTrue(result['warnings'], 'TG must report sample/envelope limitations')
        tg = Path(result['files'][0])
        self.assertEqual(tg.suffix, '.tg')
        imported = score_collection.convert(dict(paths=[str(tg)], destination=str(self.root/'native'), format='yaml'))[0]
        self.assertEqual(imported['status'], 'done', imported)
        native = Path(imported['files'][0])
        song = api.from_yaml(native.read_text(encoding='utf-8'))
        self.assertEqual(written_notes(song), written_notes(self.song))
        self.assertEqual(song['score']['metadata'], self.song['score']['metadata'])
        state = gui.State(native, headless=True)
        try:
            self.assertFalse(state.error, state.error)
            self.assertIsNotNone(state.mod.native_score)
        finally:
            state.close()
        collected = score_collection.convert(dict(paths=[str(self.path)], destination=str(self.root/'projects'), format='yaml'))[0]
        self.assertEqual(collected['status'], 'done', collected)
        copied = Path(collected['files'][0])
        self.assertTrue(copied.is_file())
        copied_song = api.from_yaml(copied.read_text(encoding='utf-8'))
        self.assertEqual(written_notes(copied_song), written_notes(self.song))
        for sample in copied_song['samples'].values():
            self.assertTrue((copied.parent / sample['file']).is_file())
        self.unchanged()

    def test_partial_failure_no_overwrite_and_cancel_between_files(self):
        broken = self.source / 'broken.tg'
        broken.write_bytes(b'not a TuxGuitar file')
        destination = self.root / 'partial'
        request = dict(paths=[str(self.path), str(broken)], destination=str(destination), format='tg')
        result = score_collection.convert(request)
        self.assertEqual([item['status'] for item in result], ['done','failed'], result)
        self.assertTrue(result[1]['error'])
        output = Path(result[0]['files'][0])
        before = output.read_bytes()
        repeated = score_collection.convert(dict(paths=[str(self.path)], destination=str(destination), format='tg'))
        self.assertEqual(repeated[0]['status'], 'failed')
        self.assertIn('already exists', repeated[0]['error'])
        self.assertEqual(output.read_bytes(), before)
        cancel = threading.Event()
        events = []
        def progress(item):
            events.append((item['source'],item['status']))
            if item['status'] == 'done':
                cancel.set()
        cancelled = score_collection.convert(dict(paths=[str(self.path),str(broken)], destination=str(self.root/'cancel'), format='tg'), progress, cancel)
        self.assertEqual([item['status'] for item in cancelled], ['done','cancelled'], cancelled)
        self.assertFalse((self.root/'cancel'/'broken-tg').exists())
        self.assertIn((str(self.path.resolve()),'working'), events)
        cancelled_before = threading.Event(); cancelled_before.set()
        result = score_collection.convert(dict(paths=[str(self.path)], destination=str(self.root/'cancel-before'), format='tg'), cancel=cancelled_before)
        self.assertEqual(result[0]['status'], 'cancelled')
        self.assertEqual(list((self.root/'cancel-before').iterdir()), [])
        self.unchanged()

    def test_scan_selection_validation_and_recursive_scope(self):
        (self.source/'notes.txt').write_text('not a score', encoding='utf-8')
        (self.source/'nested').mkdir()
        (self.source/'nested'/'part.gp5').write_bytes(b'fixture')
        self.assertEqual([item['name'] for item in score_collection.scan(str(self.source))['files']], ['study.yaml'])
        self.assertEqual([item['format'] for item in score_collection.scan(str(self.source), True)['files']], ['yaml','gp5'])
        for paths in [[],[str(self.path)]*2, [None], 'not a list']:
            with self.subTest(paths=paths), self.assertRaises(ValueError):
                score_collection.options(dict(paths=paths,destination=str(self.root/'output')))
        with self.assertRaises(ValueError):
            score_collection.options(dict(paths=[str(self.path)],destination=str(self.root/'output'),format='exe'))
        with self.assertRaises(ValueError):
            score_collection.scan(str(self.root/'missing'))

    def test_lilypond_settings_reach_each_file_and_invalid_range_is_reported(self):
        from vulturetracker.notation_export import native_to_lilypond
        from vulturetracker import tgimport
        settings=dict(track=2,measureFrom=2,measureTo=3,score=False,trackName=False,text=False,version='2.14.0')
        request=dict(paths=[str(self.path)],destination=str(self.root/'lily'),format='ly',lilypond=settings)
        result=score_collection.convert(request)[0]
        self.assertEqual(result['status'],'done',result)
        expected=native_to_lilypond(self.song,tgimport._raw(self.song),settings=settings)[0]
        self.assertEqual(Path(result['files'][0]).read_text(encoding='utf-8'),expected)
        request.update(destination=str(self.root/'invalid'),lilypond=dict(measureFrom=999))
        result=score_collection.convert(request)[0]
        self.assertEqual(result['status'],'failed')
        self.assertIn('bar range',result['error'])
        self.assertFalse(any(Path(p).suffix=='.ly' for p in result['files']))
        self.unchanged()
