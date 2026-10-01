"""1.0 release criteria and first-use gaps: synthetic songs in disposable directories."""
import contextlib
import hashlib
import io
import json
import logging
import os
import shutil
import struct
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

os.environ['VT_WORKERS'] = '1'

from vulturetracker import __version__, api, gui
from vulturetracker.__main__ import main
from vulturetracker.itwriter import write_it
from vulturetracker.song import SongError, load_song, load_song_text
from tests import test_gui as fixtures

ROOT = Path(__file__).resolve().parent.parent


def run_cli(*argv):
    """(exit code, stdout, stderr) of the command line."""
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            code = main(list(argv))
        except SystemExit as e:
            code = e.code
    return code, out.getvalue(), err.getvalue()


class TestVersion(unittest.TestCase):
    setUp = fixtures.TestGui.setUp
    tearDown = fixtures.TestGui.tearDown
    state = fixtures.TestGui.state

    def test_one_version_everywhere(self):
        self.assertRegex(__version__, r'^\d+\.\d+\.\d+')
        self.assertIn('dynamic = ["version"]', (ROOT / 'pyproject.toml').read_text(encoding='utf-8'))
        self.assertEqual(run_cli('--version')[:2], (0, f'VultureTracker {__version__}\n'))
        self.assertEqual(gui.start_snapshot()['version'], __version__)

    def test_the_notes_report_names_the_version(self):
        st = self.state()
        st.add_note({'order': 0, 'row': 0, 'time': 0, 'text': 'x'})
        self.assertIn(f'VultureTracker {__version__}.', (self.dir / 'song.notes.md').read_text(encoding='utf-8'))



class TestDiagnostics(unittest.TestCase):
    def test_the_app_logs_unexpected_errors_and_the_page_names_the_log(self):
        hooks = sys.excepthook, threading.excepthook
        with tempfile.TemporaryDirectory() as d, mock.patch.object(gui, 'LOG', Path(d) / 'vulturetracker.log'):
            try:
                gui.start_log()

                class Request:
                    command, path = 'GET', '/api/x?y=1'

                    def _send(self, code, body):
                        self.sent = code, body
                r = Request()
                gui.Handler._guarded(lambda self: 1 / 0)(r)
                self.assertEqual(r.sent[0], 500)
                self.assertEqual(r.sent[1]['error'], f'ZeroDivisionError: division by zero (details in {gui.LOG})')
                text = gui.LOG.read_text(encoding='utf-8')
                self.assertRegex(text, rf'VultureTracker {__version__} started: libopenmpt \d+\.\d+\.\d+, Python ')
                self.assertIn('GET /api/x failed', text)
                self.assertIn('Traceback', text)
                self.assertIn('ZeroDivisionError', text)
            finally:
                for h in gui._log.handlers[:]:
                    gui._log.removeHandler(h)
                    h.close()
                gui.LOGGING = False
                sys.excepthook, threading.excepthook = hooks
        self.assertEqual(gui.logged('x'), 'x')  # no log: the message as it was


class TestPlatforms(unittest.TestCase):
    def test_per_user_folders_follow_the_platform(self):
        from vulturetracker import fileio, library, synth
        home = Path.home()
        cases = [('win32', {'APPDATA': 'C:/roam', 'LOCALAPPDATA': 'C:/local'}, Path('C:/roam'), Path('C:/local')),
                 ('darwin', {}, home / 'Library/Application Support', home / 'Library/Application Support'),
                 ('linux', {}, home / '.config', home / '.local/share'),
                 ('linux', {'XDG_CONFIG_HOME': '/x/c', 'XDG_DATA_HOME': '/x/d'}, Path('/x/c'), Path('/x/d'))]
        clean = {k: v for k, v in os.environ.items() if not k.startswith('XDG_') and k not in ('APPDATA', 'LOCALAPPDATA')}
        for platform, env, config, data in cases:
            with self.subTest(platform, **env), mock.patch.object(fileio.sys, 'platform', platform), \
                    mock.patch.dict(os.environ, {**clean, **env}, clear=True):
                self.assertEqual(fileio.user_dir(), config / 'VultureTracker')
                self.assertEqual(fileio.user_dir(local=True), data / 'VultureTracker')
        # what the app keeps there
        self.assertEqual(gui.RECENT.parent, fileio.user_dir())
        self.assertEqual(gui.LOG.parent, fileio.user_dir())
        with mock.patch.dict(os.environ, {'VT_LIBRARY': ''}):
            self.assertEqual(library.default_index(), fileio.user_dir() / 'library.json')
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(synth.tools_dir(Path(d)), fileio.user_dir(local=True) / 'tools')

    def test_installed_plugins_are_found_in_the_platforms_vst3_folders(self):
        from vulturetracker import synth
        with tempfile.TemporaryDirectory() as d:
            a, b = Path(d) / 'a', Path(d) / 'b'
            (b / 'OB-Xd.vst3').mkdir(parents=True)
            with mock.patch.object(synth, 'VST3_DIRS', [a, b]):
                self.assertEqual(synth.installed('OB-Xd.vst3'), b / 'OB-Xd.vst3')
                self.assertEqual(synth.installed('Dexed.vst3'), a / 'Dexed.vst3')  # missing: named in the first
            (b / 'Surge XT.vst3').mkdir()
            (Path(d) / 'data' / 'patches_factory' / 'Pads').mkdir(parents=True)
            (Path(d) / 'data' / 'patches_factory' / 'Pads' / 'Warm.fxp').write_bytes(b'')
            with mock.patch.object(synth, 'VST3_DIRS', [a, b]), mock.patch.object(synth, 'SURGE_DATA', Path(d) / 'data'), \
                    mock.patch.object(synth, 'DEFAULT_SURGE', Path(d) / 'none'), mock.patch.dict(os.environ):
                os.environ.pop('SURGE_XT_DIR', None)
                self.assertEqual(synth.surge_paths(), (b / 'Surge XT.vst3', Path(d) / 'data'))
                self.assertEqual(synth.patch_index()['Pads/Warm'][:2], ('surge', Path(d) / 'data' / 'patches_factory' / 'Pads' / 'Warm.fxp'))


class TestSongFormatPromise(unittest.TestCase):
    setUp = fixtures.TestGui.setUp
    tearDown = fixtures.TestGui.tearDown
    state = fixtures.TestGui.state

    # The demos whose samples are all in git, as each compiles today (sha256 of the .it bytes). 1.x keeps compiling them
    # to these bytes; a deliberate change of the compiler's output updates a hash here and says so in CHANGELOG.md. The
    # same on Windows and Linux (nadir resamples through numpy's FFT: checked under python:3.14 with numpy 2.5.3).
    CORPUS = {'demo/arena.yaml': 'f620568224a1b7a73b5cb269c023e13264c2d3fa7f3cc189d46760adeb4ae9f4',
              'demo2/iron_relay.yaml': '1a3b5571689ab31a371f50ed8c3af830af46e9494df8ce9e090f10674269112c',
              'suite/nadir/nadir.yaml': 'a20899a09eee88462a29ef2514d007cb6b88cd0c1a4f0f80d0de495cbe73732d'}

    def test_the_corpus_compiles_to_the_same_bytes(self):
        for song, want in self.CORPUS.items():
            with self.subTest(song):
                self.assertEqual(hashlib.sha256(write_it(load_song(ROOT / song)[0])).hexdigest(), want)

    def test_requires_a_newer_app_is_the_one_error(self):
        text = fixtures.SONG.replace('orders:', 'requires: "99.1"\nfuture_key: 1\norders:')
        with self.assertRaises(SongError) as e:
            load_song_text(text, self.dir, 'song.yaml')
        self.assertEqual(len(e.exception.errors), 1, e.exception.errors)
        self.assertIn(f'needs VultureTracker 99.1 or newer; this is {__version__}', e.exception.errors[0])
        (self.dir / 'song.yaml').write_text(text, encoding='utf-8')
        res = api.check(self.dir / 'song.yaml')
        self.assertFalse(res['ok'])
        self.assertIn('needs VultureTracker 99.1', res['errors'][0])

    def test_requires_this_or_an_older_app_compiles_and_survives_app_edits(self):
        for value in ('"0.6"', '0.6', f'"{__version__}"'):
            load_song_text(fixtures.SONG.replace('orders:', f'requires: {value}\norders:'), self.dir, 'song.yaml')
        for value in ('"1"', 'abc', '"1.2.3.4"'):
            with self.assertRaisesRegex(SongError, "'requires' must be a version"):
                load_song_text(fixtures.SONG.replace('orders:', f'requires: {value}\norders:'), self.dir, 'song.yaml')
        (self.dir / 'song.yaml').write_bytes(fixtures.SONG.replace('orders:', 'requires: "0.6"\norders:').encode())
        st = self.state()
        st.relink(1, 'cand.wav')
        st.section_edit({'action': 'save', 'name': 'intro', 'start': 0, 'end': 1})
        st.undo()
        st.undo(redo=True)
        self.assertIn('requires: "0.6"', (self.dir / 'song.yaml').read_text(encoding='utf-8'))
        self.assertIsNone(st.error)


class TestSideFileSchemas(unittest.TestCase):
    setUp = fixtures.TestGui.setUp
    tearDown = fixtures.TestGui.tearDown
    state = fixtures.TestGui.state

    def read(self, name):
        return json.loads((self.dir / name).read_text(encoding='utf-8'))

    def test_written_with_a_schema_and_older_files_read(self):
        st = gui.State(self.dir / 'song.yaml', headless=True)
        old = dict(st.add_note({'order': 0, 'row': 0, 'text': 'old'}), version={'hash': 'gone', 'mtime': 'x'})
        st.close()
        (self.dir / 'song.notes.json').write_text(json.dumps([old]), encoding='utf-8')  # before 1.0: a list
        (self.dir / 'song.tryout.json').write_text(json.dumps({'slot': 2}), encoding='utf-8')  # no schema
        st = self.state()
        self.assertEqual(st.slot, 2)
        self.assertEqual(self.read('song.notes-gone.json'), {'schema': 1, 'notes': [old]})  # archived, as 1.0 writes it
        st.add_note({'order': 0, 'row': 0, 'text': 'new'})
        self.assertEqual(self.read('song.notes.json')['schema'], 1)
        st.set_loop({})
        self.assertEqual(self.read('song.tryout.json')['schema'], 1)
        (self.dir / 'song.tryout.json').unlink()
        st.relink(1, 'cand.wav')  # the journaled three-file save writes the settings too
        self.assertEqual(self.read('song.tryout.json')['schema'], 1)
        st2 = gui.State(self.dir / 'song.yaml', headless=True)
        self.assertEqual([n['text'] for n in st2.notes], ['new'])

    def test_a_newer_file_opens_the_song_read_only_and_is_not_written_over(self):
        for name, body in (('song.tryout.json', {'schema': 2, 'slot': 2, 'what': 'a newer layout'}),
                           ('song.notes.json', {'schema': 2, 'notes': {'a': 'newer layout'}}),
                           ('song.history.json', {'schema': 3, 'song': 'x'})):
            with self.subTest(name):
                raw = json.dumps(body).encode()
                (self.dir / name).write_bytes(raw)
                st = self.state()
                self.assertIn(f'{name} beside song.yaml was written by a newer VultureTracker', st.read_only)
                self.assertIn(st.read_only, st.notices)
                for edit in (lambda: st.relink(1, 'cand.wav'), lambda: st.add_note({'order': 0, 'row': 0}),
                             lambda: st.section_edit({'action': 'save', 'name': 'a', 'start': 0, 'end': 1})):
                    with self.assertRaisesRegex(ValueError, 'newer VultureTracker'):
                        edit()
                st.set_loop({})
                self.assertEqual((self.dir / name).read_bytes(), raw)
                self.assertEqual((self.dir / 'song.yaml').read_bytes(), fixtures.SONG.encode())
                code, _, err = run_cli('sections', str(self.dir / 'song.yaml'), 'save', 'a', '0', '1')
                self.assertEqual(code, 1)
                st.close()
                self.states.remove(st)
                code, _, err = run_cli('sections', str(self.dir / 'song.yaml'), 'save', 'a', '0', '1')
                self.assertEqual(code, 1)
                self.assertIn(f'{name} beside song.yaml was written by a newer VultureTracker', err)
                self.assertEqual((self.dir / name).read_bytes(), raw)
                self.assertEqual((self.dir / 'song.yaml').read_bytes(), fixtures.SONG.encode())
                (self.dir / name).unlink()

    def test_a_collected_project_names_its_schema(self):
        from vulturetracker.project import collect
        folder = Path(collect(self.state(), str(self.dir.parent / (self.dir.name + '-copy')))['path']).parent
        try:
            self.assertEqual(json.loads((folder / 'project.json').read_text(encoding='utf-8'))['schema'], 1)
            self.assertEqual(json.loads((folder / 'song.tryout.json').read_text(encoding='utf-8'))['schema'], 1)
        finally:
            import shutil
            shutil.rmtree(folder)



def ffmpeg():
    try:
        return gui.ffmpeg_exe()
    except OSError:
        return None


def flac_with(path, blocks):
    """The FLAC at `path` with metadata `blocks` [(type, body)] inserted after its STREAMINFO."""
    raw = path.read_bytes()
    out, pos, last = [raw[:4]], 4, False
    while not last:
        head, size = raw[pos], int.from_bytes(raw[pos + 1:pos + 4], 'big')
        last = bool(head & 0x80)
        out.append(bytes([head & 0x7F]) + raw[pos + 1:pos + 4 + size])
        if pos == 4:
            out += [bytes([kind]) + len(body).to_bytes(3, 'big') + body for kind, body in blocks]
        pos += 4 + size
    out[-1] = bytes([out[-1][0] | 0x80]) + out[-1][1:]
    path.write_bytes(b''.join(out) + raw[pos:])


@unittest.skipUnless(ffmpeg(), 'needs ffmpeg (imageio-ffmpeg)')
class TestSoundFormats(unittest.TestCase):
    setUp = fixtures.TestGui.setUp
    tearDown = fixtures.TestGui.tearDown
    state = fixtures.TestGui.state

    def encode(self, name, *args):
        """a.wav (a 440 Hz tone, 13230 frames) encoded as `name` in a folder of its own, away from the song."""
        (self.dir / 'src').mkdir(exist_ok=True)
        out = self.dir / 'src' / name
        subprocess.run([ffmpeg(), '-loglevel', 'error', '-i', str(self.dir / 'a.wav'), *args, str(out)], check=True)
        return out

    def test_flac_keeps_what_openmpt_keeps(self):
        from vulturetracker.wavload import read_wav, to_wav
        tagged = self.encode('tagged.flac', '-metadata', 'LOOPSTART=100', '-metadata', 'LOOPLENGTH=200')
        before = tagged.read_bytes()
        out, new = to_wav(tagged, self.dir, ffmpeg())
        self.assertEqual((out, new), (self.dir / 'tagged.wav', True))
        w = read_wav(out)
        self.assertEqual((w.rate, len(w.channels[0]), w.loops), (44100, 13230, [(100, 300, False)]))
        self.assertEqual(tagged.read_bytes(), before)  # never written over
        self.assertEqual(to_wav(tagged, self.dir, ffmpeg()), (out, False))  # the same again: reused
        # a sampler's smpl chunk in an APPLICATION 'riff' block: two loops (sustain, then normal, pingpong), its root
        smpl = struct.pack('<9I', 0, 0, 22676, 57, 0, 0, 0, 2, 0) + struct.pack('<6I', 0, 1, 10, 99, 0, 0) \
            + struct.pack('<6I', 1, 0, 200, 399, 0, 0)
        riff = self.encode('riff.flac')
        flac_with(riff, [(2, b'riff' + b'smpl' + struct.pack('<I', len(smpl)) + smpl)])
        w = read_wav(to_wav(riff, self.dir, ffmpeg())[0])
        self.assertEqual((w.root, w.loops), (57, [(10, 100, True), (200, 400, False)]))

    def test_aiff_keeps_its_loops_not_its_base_note(self):
        from vulturetracker.wavload import read_wav, to_wav
        aiff = self.encode('loops.aiff')
        raw = bytearray(aiff.read_bytes())
        marks = struct.pack('>H', 4) + b''.join(struct.pack('>hIB', i, at, 1) + b'm' for i, at in ((1, 1000), (2, 3000), (3, 50), (4, 500)))
        inst = struct.pack('>bbbbbbh', 72, 0, 0, 127, 1, 127, 0) + struct.pack('>hhh', 2, 3, 4) + struct.pack('>hhh', 1, 1, 2)
        raw += b'MARK' + struct.pack('>I', len(marks)) + marks + b'INST' + struct.pack('>I', len(inst)) + inst
        raw[4:8] = struct.pack('>I', len(raw) - 8)
        aiff.write_bytes(raw)
        w = read_wav(to_wav(aiff, self.dir, ffmpeg())[0])
        self.assertEqual(w.loops, [(50, 500, True), (1000, 3000, False)])  # sustain first, as OpenMPT writes a WAV
        self.assertEqual(w.root, 60)  # its base note 72 is not used (OpenMPT reads it and ignores it)

    def test_ogg_and_mp3_keep_the_audio_only(self):
        from vulturetracker.wavload import read_wav, to_wav
        for name in ('a.ogg', 'a.mp3'):
            with self.subTest(name):
                w = read_wav(to_wav(self.encode(name, '-metadata', 'LOOPSTART=100', '-metadata', 'LOOPLENGTH=200'),
                                    self.dir, ffmpeg())[0])
                self.assertEqual((w.rate, w.loops, w.root), (44100, [], None))
                self.assertGreater(len(w.channels[0]), 12000)

    def test_the_app_takes_them_as_candidates_drops_and_new_slots(self):
        flac = self.encode('kick.flac', '-metadata', 'LOOPSTART=100', '-metadata', 'LOOPLENGTH=200')
        (self.dir / 'kick.wav').write_bytes(b'not this one')  # never replaced: the WAV is numbered
        st = self.state()
        added = st.add_candidates(str(flac))
        self.assertEqual(added, [str(self.dir / 'kick-2.wav')])
        self.assertEqual((self.dir / 'kick.wav').read_bytes(), b'not this one')
        self.assertEqual(st.save_upload('dropped.mp3', self.encode('dropped.mp3').read_bytes()), self.dir / 'dropped.wav')
        with self.assertRaisesRegex(ValueError, 'not a WAV, FLAC, AIFF, OGG or MP3 file'):
            st.save_upload('x.wav', b'junk')
        st.song_edit([{'op': 'sample_new', 'file': str(self.encode('pad.aiff'))}])
        self.assertIn('file: pad.wav', (self.dir / 'song.yaml').read_text(encoding='utf-8'))
        st.song_edit([{'op': 'sample_file', 'num': 2, 'file': str(flac)}])
        self.assertIn('file: kick-2.wav', (self.dir / 'song.yaml').read_text(encoding='utf-8'))
        self.assertIsNone(st.error)
        with self.assertRaises(ValueError):  # a refused edit leaves no WAV behind
            st.song_edit([{'op': 'sample_new', 'file': str(self.encode('late.ogg'))}, {'op': 'nonsense'}])
        self.assertFalse((self.dir / 'late.wav').exists())



class TestCommandLine(unittest.TestCase):
    setUp = fixtures.TestGui.setUp
    tearDown = fixtures.TestGui.tearDown
    state = fixtures.TestGui.state

    def cli(self, *argv):
        return run_cli(argv[0], str(self.dir / 'song.yaml'), *argv[1:])

    def text(self):
        return (self.dir / 'song.yaml').read_text(encoding='utf-8')

    def test_undo_redo_and_trim_history(self):
        self.assertEqual(self.cli('undo')[0], 1)  # nothing to undo
        self.assertEqual(self.cli('sections', 'save', 'intro', '0', '1')[0], 0)
        saved = self.text()
        code, out, _ = self.cli('undo')
        self.assertEqual((code, out), (0, 'undone: 0 undo and 1 redo steps\n'))
        self.assertEqual(self.text(), fixtures.SONG)
        self.assertEqual(self.cli('redo')[:2], (0, 'redone: 1 undo and 0 redo steps\n'))
        self.assertEqual(self.text(), saved)
        self.assertIn('nothing to redo', self.cli('redo')[2])
        self.assertEqual(self.cli('trim-history', '--keep', '0')[:2], (0, 'trimmed: 0 undo and 0 redo steps\n'))
        self.assertEqual(self.cli('undo')[0], 1)
        st = self.state()  # the app sees the same history
        self.assertEqual((len(st.history), len(st.future)), (0, 0))

    def test_sections_rename_in_place_and_json(self):
        (self.dir / 'song.yaml').write_bytes(fixtures.SONG.replace('orders: [p1, p2]\n', 'orders: [p1, p2]\nsections:\n'
                                             '  intro: [0, 1]  # the start\n  outro: [1, 2]\n').encode())
        code, out, _ = self.cli('sections', 'rename', 'intro', '--as', 'Opening', '--json')
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out), {'sections': {'Opening': {'first': 0, 'end': 1, 'orders': ['p1']},
                                                        'outro': {'first': 1, 'end': 2, 'orders': ['p2']}}})
        self.assertIn('  "Opening": [0, 1]  # the start\n  outro: [1, 2]\n', self.text())
        self.assertIn('already', self.cli('sections', 'rename', 'outro', '--as', 'Opening')[2])
        self.assertIn('--as NEW', self.cli('sections', 'rename', 'outro')[2])
        self.assertEqual(self.cli('undo')[0], 0)
        self.assertIn('  intro: [0, 1]  # the start\n', self.text())
        st = self.state()
        st.section_edit({'action': 'rename', 'name': 'outro', 'new_name': 'end'})  # the app's method
        self.assertIn('  "end": [1, 2]\n', self.text())

    def test_json_for_checkpoints_and_phrases(self):
        self.cli('checkpoint', 'save', 'first')
        out = json.loads(self.cli('checkpoint', '--json')[1])
        self.assertEqual((list(out['checkpoints']), out['undo'], out['redo']), (['first'], 0, 0))
        self.assertEqual(set(out['checkpoints']['first']), {'hash', 'mtime'})
        self.assertEqual(json.loads(self.cli('checkpoint', 'diff', 'first', '--json')[1])['diff'], [])
        self.assertEqual(json.loads(self.cli('phrase', '--json')[1]), {'phrase': None})
        self.cli('phrase', 'capture', '--order', '0', '--rows', '0-1', '--channels', '1')
        out = json.loads(self.cli('phrase', '--json')[1])['phrase']
        self.assertEqual((out['order'], out['r0'], out['r1'], out['chans'], len(out['variants'])), (0, 0, 1, [0], 3))

    def test_wait_for_the_song_lock(self):
        st = self.state()  # the app has the song open
        code, _, err = self.cli('sections', 'save', 'intro', '0', '1')
        self.assertEqual(code, 1)
        self.assertIn('is open in VultureTracker', err)
        threading.Timer(0.6, st.close).start()
        self.assertEqual(self.cli('sections', 'save', 'intro', '0', '1', '--wait', '10')[0], 0)
        self.assertIn('intro', self.text())



try:
    import mido
except ImportError:
    mido = None


@unittest.skipIf(mido is None, 'needs mido')
class TestMidiImportKeeps(unittest.TestCase):
    """Markers, pitch bends and the sustain pedal, as OpenMPT's Load_mid.cpp reads them."""

    def imported(self, *events, sig=(4, 4)):
        from tests.test_midiimport import track
        mid = mido.MidiFile(type=1, ticks_per_beat=480)
        mid.tracks.append(track('Song', (0, mido.MetaMessage('time_signature', numerator=sig[0], denominator=sig[1]))))
        mid.tracks.append(track('Keys', *events))
        d = Path(self.enterContext(tempfile.TemporaryDirectory()))
        mid.save(d / 't.mid')
        out, warnings = gui.import_beside(d / 't.mid')
        self.assertEqual(api.check(out)['errors'], [])
        song = api.load(out)
        cells = {(p, i): row.split(': ', 1)[1].split(' | ')[0] for p, pat in song['patterns'].items()
                 for i, row in enumerate(pat['data'].splitlines())}
        return song, [cells[p, i] for p in song['orders'] for i in range(song['patterns'][p]['rows'])], warnings

    def test_markers_become_named_sections(self):
        from tests.test_midiimport import note
        song, _, _ = self.imported(*note(0, 60, 0, 480 * 16), (0, mido.MetaMessage('marker', text='Intro')),
                                   (1920 * 2, mido.MetaMessage('marker', text='Verse')),
                                   (1920 * 2 + 100, mido.MetaMessage('cue_marker', text='Hook')),  # the same bar: the last
                                   (1920 * 3, mido.MetaMessage('marker', text='Intro')))
        self.assertEqual(song['sections'], {'Intro': [0, 2], 'Hook': [2, 3], 'Intro 2': [3, 4]})

    def test_pitch_bends_slide_as_openmpt_writes_them(self):
        from tests.test_midiimport import note
        cc = lambda t, c, v: (t, mido.Message('control_change', channel=0, control=c, value=v))  # noqa: E731
        bend = lambda t, v: (t, mido.Message('pitchwheel', channel=0, pitch=v))  # noqa: E731
        song, rows, warnings = self.imported(
            cc(0, 101, 0), cc(0, 100, 0), cc(0, 6, 12),               # RPN 0: a 12-semitone range
            *note(0, 60, 0, 480), bend(120, 4096), bend(240, 0),      # +6 semitones on row 1, back on row 2
            bend(480, 683), *note(0, 62, 480, 240),                   # +1 semitone as the next note starts
            cc(720, 121, 0), *note(0, 64, 960, 240), *note(0, 72, 1320, 60))  # CC 121: centred, range 2
        self.assertEqual(warnings, [])
        self.assertEqual((song['module']['speed'], song['module']['rows_per_beat']), (6, 4))
        # 6 semitones = 384/64 over a row's 5 sliding ticks: F13 (19/16 a tick) moves 380, and E13 takes it back; the note
        # struck under a semitone's bend starts there (D#5, not D-5) with nothing left to slide
        self.assertEqual(rows[:9], ['C-5 01 v50 ...', '... .. ... F13', '... .. ... E13', '... .. ... ...',
                                    'D#5 01 v50 ...', '... .. ... ...', '=== .. ... ...', '... .. ... ...', 'E-5 01 v50 ...'])

    def test_a_bent_note_past_the_keyboard_slides_the_whole_bend(self):
        from tests.test_midiimport import note
        _, rows, _ = self.imported((0, mido.Message('pitchwheel', channel=0, pitch=4096)), *note(0, 119, 480, 480))
        # +1 semitone over B-9 is no note: B-9 stays and the semitone is slid (fine, 15/16 of it at 24 ticks a row)
        self.assertEqual(rows[1], 'B-9 01 v50 FFF')

    def test_the_sustain_pedal_holds_notes_until_it_is_let_up(self):
        from tests.test_midiimport import note
        cc = lambda t, c, v: (t, mido.Message('control_change', channel=0, control=c, value=v))  # noqa: E731
        _, rows, warnings = self.imported(cc(0, 64, 127), *note(0, 60, 0, 240), cc(960, 64, 0),
                                          *note(0, 67, 1920, 240), cc(1920, 64, 100), cc(2400, 123, 0))
        self.assertEqual(warnings, [])
        # a row a quarter: let go at tick 240 (row 1 without the pedal), held to the pedal's release (tick 960, row 2);
        # then held again until all notes off (CC 123, tick 2400, row 5)
        self.assertEqual([r[:3] for r in rows[:6]], ['C-5', '...', '===', '...', 'G-5', '==='])


class TestModuleImportKeeps(unittest.TestCase):
    def module(self, **kw):
        from vulturetracker.model import Cell, Channel, Instrument, Module, Pattern, Sample
        mod = Module()
        mod.title = 'T'
        mod.channels = [Channel()]
        mod.samples = [Sample(name='s', data=[[0] * 64], bits=8)]
        if kw.get('instruments'):
            mod.instruments = [Instrument(name='i', keymap=[(n, 1) for n in range(120)])]
        mod.patterns = [Pattern('p', [[Cell()] for _ in range(4)])]
        mod.orders = [0]
        return bytearray(write_it(mod))

    def test_names_are_transliterated_in_openmpts_character_set(self):
        from vulturetracker.itreader import read_it
        data = self.module()
        data[4:13] = b'Caf\x82 B\x94se'  # CP437: Café Böse
        self.assertEqual(read_it(bytes(data))[0].title, 'Cafe Bose')
        data[4:13] = b'Caf\xe9 B\xf6se'  # an OpenMPT saved it: Windows-1252
        struct.pack_into('<H', data, 0x28, 0x5130)
        self.assertEqual(read_it(bytes(data))[0].title, 'Cafe Bose')
        data[4:13] = b'Gro\xdfe\x00\x00\x00\x00'  # ß becomes ss: the name grows and keeps its end
        self.assertEqual(read_it(bytes(data))[0].title, 'Grosse')

    def test_what_is_dropped_is_said(self):
        from vulturetracker.itreader import read_it
        data = self.module(instruments=True)
        data[0x35] = 12  # the MIDI pitch wheel depth
        ins = struct.unpack_from('<I', data, 0xC0 + struct.unpack_from('<H', data, 0x20)[0])[0]
        data[ins + 0x3C] = 3  # instrument 1 sends on MIDI channel 3
        warnings = read_it(bytes(data))[1]
        self.assertIn('the MIDI pitch wheel depth (12 semitones; for MIDI output) is not carried over', warnings)
        self.assertIn('instrument 1: MIDI channel, program, bank or plugin (for MIDI output and plugins) not carried over', warnings)
        head = bytearray(0xC0)
        head[:4] = b'IMPM'
        struct.pack_into('<8H', head, 0x20, 1, 0, 0, 0, 0x214, 0x214, 9, 2)  # special bit 1: the edit history follows
        warnings = read_it(bytes(head) + b'\xff' + struct.pack('<H', 3) + bytes(24))[1]
        self.assertIn('the edit history (3 editing sessions) is not carried over', warnings)



class TestFaustSaves(unittest.TestCase):
    setUp = fixtures.TestGui.setUp
    tearDown = fixtures.TestGui.tearDown
    state = fixtures.TestGui.state

    CODE = ('import("stdfaust.lib");\nfreq = hslider("freq", 440, 20, 4000, 0.01);\ngate = button("gate");\n'
            'gain = hslider("gain", 0.8, 0, 1, 0.01);\nbright = hslider("bright", 0.5, 0, 1, 0.01);\n'
            'process = os.osc(freq) * en.asr(0.01, 1, 0.1, gate) * gain * bright;')

    def test_a_saved_sound_gets_its_faust_entry_and_renders_again(self):
        from vulturetracker import faust
        from vulturetracker.synth import recipe_outputs, render_one
        from vulturetracker.wavload import read_wav
        st = self.state()
        wav = self.dir / 'faust-tone.wav'
        fixtures.write_wav(wav, fixtures.RATE, [fixtures.sine(440)])  # what the tab rendered and uploaded
        st.place_wav(wav, 'slot')
        report = st.faust_recipe(wav, {'code': self.CODE, 'notes': [69], 'hold': 0.5, 'tail': 0.2, 'velocity': 90,
                                       'params': {'bright': 0.25}})
        self.assertEqual(report, '; its faust: entry is in faust.yaml')
        text = (self.dir / 'faust.yaml').read_text(encoding='utf-8')
        self.assertIn('  faust-tone:\n    faust: |-\n      import("stdfaust.lib");\n', text)
        self.assertEqual(recipe_outputs(self.dir / 'faust.yaml'), [(wav, 'faust-tone', None)])
        st.meta['slot'] = 3  # the new slot: the RECIPE box shows the entry
        rec = st.slot_recipe()
        self.assertEqual((rec['name'], rec['recipe']), ('faust-tone', str(self.dir / 'faust.yaml')))
        self.assertIn('note: A-5\nhold: 0.5\ntail: 0.2\nvelocity: 90\nparams: {bright: 0.25}\ntrim: false\nfade_out: 0\n', rec['spec'])
        self.assertEqual(st.faust_recipe(wav, {'code': 'other'}), '; its faust: entry is in faust.yaml')  # kept as written
        self.assertEqual((self.dir / 'faust.yaml').read_text(encoding='utf-8'), text)
        st.faust_recipe(self.dir / 'faust-chord.wav', {'code': self.CODE, 'notes': [60, 64, 67]})
        self.assertIn('  faust-chord:\n    faust: |-', (self.dir / 'faust.yaml').read_text(encoding='utf-8'))
        if faust.have() and shutil.which('node'):  # the entry renders the sound again (as the RECIPE box does)
            out = render_one(self.dir / 'faust.yaml', 'faust-tone', out=self.dir / 'again.wav', log=lambda *a: None)[0]
            w = read_wav(out)
            self.assertEqual((w.rate, len(w.channels[0]), w.root), (44100, round(0.7 * 44100), 69))

    def test_a_faust_yaml_laid_out_otherwise_is_left_alone(self):
        st = self.state()
        (self.dir / 'faust.yaml').write_text('samples: {}\nout_dir: elsewhere\n', encoding='utf-8')
        self.assertIn('was not written', st.faust_recipe(self.dir / 'x.wav', {'code': self.CODE}))
        self.assertEqual((self.dir / 'faust.yaml').read_text(encoding='utf-8'), 'samples: {}\nout_dir: elsewhere\n')

    def test_the_code_being_typed_is_kept_with_the_song(self):
        import urllib.request
        st = gui.Handler.state = self.state()
        srv = gui._Server(('127.0.0.1', 0), gui.Handler)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        try:
            url = f'http://127.0.0.1:{srv.server_address[1]}/api/'
            urllib.request.urlopen(urllib.request.Request(url + 'faustcode', json.dumps({'code': 'process = _;'}).encode(),
                                                          {'content-type': 'application/json'}))
            self.assertEqual(json.loads(urllib.request.urlopen(url + 'state').read())['faust_code'], 'process = _;')
        finally:
            srv.shutdown()
            srv.server_close()
            gui.Handler.state = None
        self.assertEqual(json.loads((self.dir / 'song.tryout.json').read_text(encoding='utf-8'))['faust_code'], 'process = _;')


if __name__ == '__main__':
    unittest.main()
