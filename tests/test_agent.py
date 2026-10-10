"""The agent tools (agent.py) on an open song: what they read, the edits they make as one undo step with the pattern
marked `by: agent`, what they refuse (approved entries, levels), measure's change between calls; the MCP server's
JSON-RPC; and the chat panel's loop against stand-in servers for the Anthropic API and an OpenAI-compatible local model
(no network, no tokens spent)."""
import io
import json
import os
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from vulturetracker import agent, agent_context, api, gui, mcp
from vulturetracker.wavload import write_wav

from tests.test_gui import RATE, SONG_BLOCK, sine


class Fake(BaseHTTPRequestHandler):
    """Answers POSTs with the next of `answers`, keeping the request bodies in `seen`."""
    answers, seen, headers_seen = [], [], []

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        type(self).seen.append((self.path, body))
        type(self).headers_seen.append(dict(self.headers))
        out = json.dumps(type(self).answers.pop(0)).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(out)))
        self.end_headers()
        self.wfile.write(out)

    def do_GET(self):
        type(self).seen.append((self.path, None))
        type(self).headers_seen.append(dict(self.headers))
        out = json.dumps(type(self).answers.pop(0)).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(out)))
        self.end_headers()
        self.wfile.write(out)

    def log_message(self, *a):
        pass


class FakeKeyring:
    """A dict-backed stand-in for the keyring module. `broken` raises on every call (Linux without a secret service);
    `dropping` accepts a key and forgets it (the null backend)."""

    def __init__(self, broken=False, dropping=False):
        self.store, self.broken, self.dropping = {}, broken, dropping

    def get_password(self, service, account):
        if self.broken:
            raise RuntimeError("No recommended backend was available")
        return self.store.get((service, account))

    def set_password(self, service, account, password):
        if self.broken:
            raise RuntimeError("No recommended backend was available")
        if not self.dropping:
            self.store[(service, account)] = password

    def delete_password(self, service, account):
        if self.broken or (service, account) not in self.store:
            raise RuntimeError("PasswordDeleteError")
        del self.store[(service, account)]


class AgentTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        write_wav(self.dir / "a.wav", RATE, [sine(440)], root_note=69)
        write_wav(self.dir / "b.wav", RATE, [sine(880)])
        (self.dir / "song.yaml").write_bytes(SONG_BLOCK.encode("utf-8"))
        self.states = []
        self._settings, self._keyring = agent.settings_path, agent.keyring
        agent.settings_path = lambda: self.dir / "agent.json"   # never the user's own settings
        agent.keyring = None                                    # nor the user's own credential store

    def tearDown(self):
        agent.settings_path, agent.keyring = self._settings, self._keyring
        from tests.test_gui import TestGui
        TestGui.tearDown(self)

    def state(self):
        st = gui.State(self.dir / "song.yaml")
        self.states.append(st)
        return st

    def read(self):
        return (self.dir / "song.yaml").read_bytes().decode("utf-8")

    def sound_job(self, st, tool_name, **args):
        result = agent.run(st, tool_name, args)
        self.assertNotIn('error', result, result)
        for _ in range(300):
            status = agent.run(st, 'synthesis_status', {'job_id': result['job_id']})
            if status['status'] not in ('queued', 'rendering', 'cancelling'):
                return status
            time.sleep(.02)
        self.fail('synthesis job did not finish')

    def test_library_index_search_similarity_and_ids(self):
        from vulturetracker.library import Library
        st = self.state()
        lib = Library(self.dir / 'library.json')
        with mock.patch.object(gui.Handler, 'library', lib):
            def wait(job):
                self.assertNotIn('error', job, job)
                lib.job.join(5)
                result = agent.run(st, 'library_status', {'job_id': job['job_id']})
                self.assertTrue(result['done'], result)
                return result
            before = st.text
            job = agent.run(st, 'index_library', {'roots': [str(self.dir)], 'replace_roots': True})
            result = wait(job)
            self.assertEqual(result['count'], 2)
            self.assertEqual(result['roots'], [str(self.dir)])
            result = agent.run(st, 'search_library', {'query': 'a.wav', 'limit': 1})
            self.assertEqual(result['results'][0]['file'], str(self.dir / 'a.wav'))
            self.assertTrue(result['results'][0]['current'])
            result = wait(agent.run(st, 'similar_samples', {'slot': 1}))
            self.assertEqual(result['result']['results'][0]['file'], str(self.dir / 'b.wav'))
            self.assertIn('error', agent.run(st, 'library_status', {'job_id': job['job_id']}))
            self.assertEqual(st.text, before)
            self.assertEqual(st.cands(), [])
            self.assertIn('error', agent.run(st, 'index_library', {'roots': ['missing']}))
            self.assertEqual(lib.roots, [str(self.dir)])

    def test_library_busy_and_pagination(self):
        from vulturetracker.library import Library
        st = self.state()
        lib, event = Library(self.dir / 'library.json'), threading.Event()
        with mock.patch.object(gui.Handler, 'library', lib):
            lib.scan([str(self.dir)])
            first = agent.run(st, 'search_library', {'limit': 1})
            second = agent.run(st, 'search_library', {'offset': first['next_offset'], 'limit': 1})
            self.assertNotEqual(first['results'][0]['file'], second['results'][0]['file'])
            lib.run(lambda: event.wait(3))
            try:
                self.assertIn('error', agent.run(st, 'index_library', {'roots': [str(self.dir)]}))
                self.assertIn('error', agent.run(st, 'similar_samples', {'file': 'a.wav'}))
            finally:
                event.set()
                lib.job.join(5)

    def test_recipe_versions_defaults_relative_inputs_and_render(self):
        st = self.state()
        d = self.dir / 'sources'
        d.mkdir()
        (d / 'recipe.yaml').write_text('sample_rate: 22050\ndefaults: {trim: false, fade_out: 0}\nsamples:\n  tone: {file: ../a.wav, note: A-5}\n')
        before = (d / 'recipe.yaml').read_bytes()
        result = agent.run(st, 'save_sound_recipe', {'recipe': 'sources/recipe.yaml', 'entry': 'tone',
                                                   'changes': {'reverse': True}, 'name': 'Variant'})
        self.assertNotIn('error', result, result)
        self.assertEqual(result['spec']['file'], str(self.dir / 'a.wav'))
        self.assertEqual(result['sample_rate'], 22050)
        self.assertFalse(result['spec']['trim'])
        self.assertEqual((d / 'recipe.yaml').read_bytes(), before)
        read = agent.run(st, 'read_sound_recipe', {'recipe': result['recipe'], 'entry': result['entry']})
        self.assertTrue(read['spec']['reverse'])
        song, audio = st.text, (self.dir / 'a.wav').read_bytes()
        out = self.sound_job(st, 'render_synthesis', recipe=result['recipe'], entry=result['entry'])
        from importlib.util import find_spec
        if find_spec('pedalboard') is None:
            self.assertEqual(out['status'], 'failed', out)
            self.assertIn('pedalboard', out['error'])
            self.assertIsNone(out['file'])
            self.assertEqual(st.text, song)
            self.assertEqual((self.dir / 'a.wav').read_bytes(), audio)
            self.assertEqual(st.cands(), [])
            return  # File recipes require the optional synth dependency; saved recipe checks still run.
        self.assertEqual(out['status'], 'done', out)
        self.assertEqual(out['sample_rate'], 22050)
        self.assertEqual(out['root'], 69)
        self.assertTrue(Path(out['file']).is_file())
        self.assertEqual(st.text, song)
        self.assertEqual((self.dir / 'a.wav').read_bytes(), audio)
        self.assertEqual(st.cands(), [])
        # The generated recipe is discoverable after the owner uses its WAV.
        recipes = agent.run(st, 'synthesis_catalog', {'action': 'recipes'})['results']
        self.assertIn(out['file'], [r['file'] for r in recipes])

    def test_synthesis_failure_cancel_and_close_publish_nothing(self):
        from vulturetracker import synth
        st = self.state()
        out = self.sound_job(st, 'render_synthesis', spec={'file': 'missing.wav'})
        self.assertEqual(out['status'], 'failed', out)
        self.assertEqual(list(self.dir.glob('agent-*')), [])
        started, release = threading.Event(), threading.Event()
        original = synth.render_one
        def slow(*args, **kwargs):
            started.set()
            self.assertTrue(release.wait(5))
            return original(*args, **kwargs)
        with mock.patch.object(synth, 'render_one', slow):
            job = agent.run(st, 'render_synthesis', {'spec': {'file': 'a.wav'}})
            self.assertTrue(started.wait(5))
            try:
                self.assertIn('error', agent.run(st, 'render_synthesis', {'spec': {'file': 'a.wav'}}))
                self.assertIn('error', agent.run(st, 'cancel_synthesis', {'job_id': 'old'}))
                self.assertEqual(agent.run(st, 'cancel_synthesis', {'job_id': job['job_id']})['status'], 'cancelling')
                st.close()
            finally:
                release.set()
            for _ in range(300):
                if st.synthesis_job['status'] == 'cancelled':
                    break
                time.sleep(.01)
            self.assertEqual(st.synthesis_job['status'], 'cancelled')
        self.assertEqual(list(self.dir.glob('agent-*')), [])

    def test_synthesis_validates_and_does_not_fetch_dependencies(self):
        from vulturetracker import synth
        st = self.state()
        for args in [{'spec': {'faust': 'process=0;', 'hold': float('nan')}},
                     {'spec': {'file': 'a.wav', 'patch': 'both'}},
                     {'spec': {'patch': 'X', 'notes': ['C-4', 'C-5']}},
                     {'spec': {'resynth': {'target': 'a.wav', 'corpus': 'b.wav', 'overlap': 1000}}}]:
            self.assertIn('error', agent.run(st, 'render_synthesis', args))
        self.assertIsNone(st.synthesis_job)
        with mock.patch.object(synth, 'render_one', side_effect=synth.SynthMissing('faust', 'not installed')), \
                mock.patch.object(synth, 'fetch_synth') as fetch:
            result = self.sound_job(st, 'render_synthesis', spec={'faust': 'process=0;', 'hold': .1})
            self.assertEqual(result['status'], 'failed')
            self.assertEqual(result['need'], 'faust')
            fetch.assert_not_called()
        st.read_only = 'test read-only'
        self.assertIn('error', agent.run(st, 'save_sound_recipe', {'spec': {'file': 'a.wav'}}))
        self.assertIn('error', agent.run(st, 'render_synthesis', {'spec': {'file': 'a.wav'}}))
        st.read_only = None

    def test_paint_render_reload_filter_and_silence_failure(self):
        st = self.state()
        from vulturetracker.wavload import read_wav
        before = st.text
        out = self.sound_job(st, 'render_paint', amp=[[1, .5, 0]], seconds=.1, fmin=440, fmax=880)
        self.assertEqual(out['status'], 'done', out)
        self.assertEqual(len(out['files']), 3)
        read = agent.run(st, 'read_sound_recipe', {'recipe': out['recipe']})
        self.assertEqual(read['paint']['amp'], [[1., .5, 0.]])
        again = self.sound_job(st, 'render_paint', source=out['recipe'])
        self.assertEqual(Path(out['file']).read_bytes(), Path(again['file']).read_bytes())
        filtered = self.sound_job(st, 'render_paint', amp=[[1]], file='a.wav', fmin=40, fmax=12000)
        self.assertEqual(filtered['status'], 'done', filtered)
        self.assertEqual(filtered['root'], 69)
        self.assertEqual(read_wav(filtered['file']).rate, RATE)
        failed = self.sound_job(st, 'render_paint', amp=[[0]], seconds=.1)
        self.assertEqual(failed['status'], 'failed')
        self.assertIsNone(failed['file'])
        self.assertEqual(st.text, before)

    def test_resynthesis_and_faust_recipe_sources(self):
        from vulturetracker import synth
        import numpy as np
        st = self.state()
        out = self.sound_job(st, 'render_synthesis', spec={'resynth': {'target': 'a.wav', 'corpus': ['b.wav'],
                              'corpus_seconds': .3}, 'length': .1, 'trim': False})
        self.assertEqual(out['status'], 'done', out)
        self.assertTrue(any('resynth:' in s for s in out['log']))
        # Faust integration gets the frozen source and parameters; real compiler renders have tests.test_faust.
        with mock.patch.object(synth, '_faust', return_value=(np.sin(np.arange(4410)*.1)[None, :], 'test Faust')) as render:
            out = self.sound_job(st, 'render_synthesis', spec={'faust': 'process=0;', 'hold': .1, 'params': {'tone': .2}})
            self.assertEqual(out['status'], 'done', out)
            self.assertEqual(render.call_args.args[1]['params'], {'tone': .2})

    def test_synthesis_catalog_and_note_selection(self):
        from vulturetracker import synth
        st = self.state()
        with mock.patch.object(synth, 'patch_index', return_value={'Pads/Dark': ('surge', self.dir, 0),
                                                                  'Leads/Bright': ('surge', self.dir, 0)}):
            results = agent.run(st, 'synthesis_catalog', {'action': 'patches', 'query': 'dark'})
            self.assertEqual(results['results'], [{'patch': 'Pads/Dark', 'synth': 'surge'}])
        host = mock.Mock()
        host.plugin.cutoff = 440.0
        host.plugin.parameters = {'cutoff': mock.Mock(raw_value=.4, type=float, label='Hz', min_value=20., max_value=20000.),
                                  'gain': mock.Mock(raw_value=.7)}
        with mock.patch.object(synth, 'Synths', return_value=host):
            result = agent.run(st, 'synthesis_catalog', {'action': 'parameters', 'patch': 'Pads/Dark', 'query': 'cut'})
            host.load.assert_called_once_with('Pads/Dark')
            self.assertEqual(result['results'], [{'name': 'cutoff', 'value': 440., 'type': 'float', 'units': 'Hz',
                              'min': 20., 'max': 20000., 'choices': None, 'choice_count': None, 'raw_value': .4}])
        saved = agent.run(st, 'save_sound_recipe', {'spec': {'patch': 'Pads/Dark', 'notes': ['C-4', 'C-5']}, 'note': 'C-5'})
        self.assertNotIn('error', saved, saved)
        self.assertEqual(saved['spec']['note'], 'C-5')
        self.assertNotIn('notes', saved['spec'])

    def test_synthesis_queued_cancel_and_output_collision(self):
        st = self.state()
        with mock.patch.object(st, '_put'):
            queued = agent.run(st, 'render_synthesis', {'spec': {'file': 'a.wav'}})
        agent.run(st, 'cancel_synthesis', {'job_id': queued['job_id']})
        agent.agent_sounds.render_job(st, st.synthesis_job)
        self.assertEqual(st.synthesis_job['status'], 'cancelled')
        self.assertEqual(list(self.dir.glob('agent-*')), [])
        occupied = self.dir / 'occupied.wav'
        occupied.write_bytes(b'preserve')
        with mock.patch.object(agent.agent_sounds, '_asset', return_value=occupied):
            result = self.sound_job(st, 'render_synthesis', spec={'file': 'a.wav'})
        self.assertEqual(result['status'], 'failed')
        self.assertEqual(occupied.read_bytes(), b'preserve')

    def batch4(self, st, tool_name, **args):
        result = agent.run(st, tool_name, args)
        self.assertNotIn('error', result, result)
        return result

    def test_section_tools_remap_jumps_loops_and_undo(self):
        st = self.state()
        st.song_edit([{'op': 'orders', 'orders': ['p1', 'p2', 'p1', 'p2']}])
        st.edit_patterns([(0, [{'row': 3, 'ch': 0, 'cell': '... .. ... B01'}])])
        call = lambda tool_name, **kw: self.batch4(st, tool_name, **kw)
        call('edit_section', action='create', name='Intro', start=0, end=2)
        call('edit_section', action='create', name='Tail', start=2, end=4)
        st.section_edit({'action': 'loop', 'name': 'Intro'})
        before, n = st.text, len(st.history)
        call('edit_section', action='move', name='Intro', to=4)
        self.assertEqual(st.song['sections']['Intro'], [2, 4])
        self.assertEqual(st.mod.patterns[0].rows[3][0].param, 3)
        self.assertEqual(st.meta['loop']['from'], [2, 0])
        self.assertEqual(len(st.history), n+1)
        call('undo')
        self.assertEqual(st.text, before)
        call('edit_section', action='duplicate', name='Intro', new_name='Again', to=4)
        self.assertEqual(st.song['sections']['Again'], [4, 6])
        self.assertNotEqual(st.song['orders'][4], 'p1')
        clone = next(p for p in st.mod.patterns if p.name == st.song['orders'][4])
        self.assertEqual(clone.rows[3][0].param, 5)
        call('edit_section', action='rename', name='Again', new_name='Outro')
        orders = list(st.song['orders'])
        call('edit_section', action='delete', name='Outro')
        self.assertEqual(st.song['orders'], orders)

    def test_section_tools_fail_atomically(self):
        st = self.state()
        self.batch4(st, 'edit_section', action='create', name='A', start=0, end=1)
        for args in [dict(action='create', name='A', start=0, end=1),
                     dict(action='update', name='missing', start=0, end=1),
                     dict(action='create', name='Overlap', start=0, end=2),
                     dict(action='update', name='A', start=True, end=1),
                     dict(action='move', name='A', to=3)]:
            before, n = st.text, len(st.history)
            self.assertIn('error', agent.run(st, 'edit_section', args))
            self.assertEqual((st.text, len(st.history)), (before, n))
        self.batch4(st, 'edit_section', action='update', name='A', start=0, end=2)
        self.assertEqual(st.song['sections']['A'], [0, 2])

    def test_pattern_maintenance_and_discard_guard(self):
        st = self.state()
        call = lambda **kw: self.batch4(st, 'edit_pattern', **kw)
        before = st.text
        self.assertIn('error', agent.run(st, 'edit_pattern', dict(action='resize', pattern='p1', rows=2)))
        self.assertEqual(st.text, before)
        call(action='resize', pattern='p1', rows=2, discard_rows=True)
        self.assertEqual(len(st.mod.patterns[0].rows), 2)
        self.batch4(st, 'undo')
        self.assertEqual(st.text, before)
        call(action='rename', pattern='p1', new_name='Lead')
        self.assertEqual(st.song['orders'], ['Lead', 'p2'])
        call(action='resize', pattern='Lead', rows=8)
        self.assertEqual(len(st.mod.patterns[0].rows), 8)
        self.assertIn('error', agent.run(st, 'edit_pattern', dict(action='delete', pattern='Lead')))
        self.batch4(st, 'new_pattern', name='Unused')
        call(action='delete', pattern='Unused')
        self.assertNotIn('Unused', st.song['patterns'])

    def test_materialize_preserves_marks_and_cells(self):
        st = self.state()
        st.song_edit([{'op': 'mark', 'what': 'pattern', 'key': 'p1', 'by': 'you'}])
        before, rows = st.text, st.mod.patterns[0].rows
        self.batch4(st, 'edit_pattern', action='materialize', pattern='p1')
        self.assertEqual(st.mod.patterns[0].rows, rows)
        self.assertEqual(st.pattern_entry('p1')['by'], 'you')
        self.batch4(st, 'undo')
        self.assertEqual(st.text, before)
        st.song_edit([{'op': 'mark', 'what': 'pattern', 'key': 'p1', 'approved': True}])
        self.assertIn('error', agent.run(st, 'edit_pattern', dict(action='materialize', pattern='p1')))
        st.materialize_pattern(0)  # owner operation retains approval too
        self.assertTrue(st.pattern_entry('p1')['approved'])

    def test_write_patterns_atomic_compile_and_approval_guards(self):
        st = self.state()
        before, n = st.text, len(st.history)
        groups = [{'pattern': 'p1', 'cells': [{'row': 1, 'channel': 1, 'cell': 'D-5 01'}]},
                  {'pattern': 'p2', 'cells': [{'row': 1, 'channel': 2, 'cell': 'invalid'}]}]
        self.assertIn('error', agent.run(st, 'write_patterns', {'patterns': groups}))
        self.assertEqual((st.text, len(st.history)), (before, n))
        groups[1]['cells'][0]['cell'] = 'E-5 02'
        self.assertEqual(self.batch4(st, 'write_patterns', patterns=groups)['changed_cells'], 2)
        self.assertEqual(len(st.history), n+1)
        self.assertEqual(st.pattern_entry('p1')['by'], 'you and agent')
        self.batch4(st, 'undo')
        self.assertEqual(st.text, before)
        st.song_edit([{'op': 'mark', 'what': 'pattern', 'key': 'p2', 'approved': True}])
        before, n = st.text, len(st.history)
        self.assertIn('error', agent.run(st, 'write_patterns', {'patterns': groups}))
        self.assertEqual((st.text, len(st.history)), (before, n))

    def test_transform_transpose_replace_and_clear(self):
        st = self.state()
        self.batch4(st, 'write_patterns', patterns=[{'pattern': 'p1', 'cells': [
            {'row': 1, 'channel': 1, 'cell': 'B-9 01'}, {'row': 3, 'channel': 1, 'cell': '==='}]}])
        before, n = st.text, len(st.history)
        selections = [{'pattern': 'p1', 'channels': [1]}, {'pattern': 'p2', 'channels': [1]}]
        self.batch4(st, 'transform_patterns', action='transpose', selections=selections, semitones=12)
        self.assertEqual([st.mod.patterns[0].rows[r][0].note for r in (0, 1, 3)], [72, 119, 255])
        self.assertEqual(st.mod.patterns[1].rows[0][0].note, 72)
        self.assertEqual(len(st.history), n+1)
        self.batch4(st, 'undo')
        self.assertEqual(st.text, before)
        self.batch4(st, 'transform_patterns', action='replace', selections=selections,
                    match={'note': 'C-?', 'instrument': '0*'}, replacement={'note': 'F#4', 'effect': 'R44'})
        self.assertEqual(st.mod.patterns[0].rows[0][0].note, 54)
        self.assertEqual(st.mod.patterns[1].rows[0][0].effect, 18)
        self.batch4(st, 'transform_patterns', action='clear', selections=selections, fields=['effect'])
        self.assertEqual(st.mod.patterns[1].rows[0][0].effect, 0)
        self.assertEqual(st.mod.patterns[1].rows[0][0].note, 54)

    def test_composition_helpers_and_guard_on_chord_destinations(self):
        st = self.state()
        select = [{'pattern': 'p1', 'channels': [1]}]
        call = lambda **kw: self.batch4(st, 'transform_patterns', selections=select, **kw)
        call(action='euclid', hits=2, steps=4)
        self.assertEqual([r[0].note for r in st.mod.patterns[0].rows], [60, None, 60, None])
        call(action='groove', ticks=[1, 0])
        self.assertEqual(st.mod.patterns[0].rows[0][0].param, 0xD1)
        call(action='layers', instruments=[1, 2])
        self.assertEqual([st.mod.patterns[0].rows[r][0].instrument for r in [0, 2]], [1, 2])
        before, n = st.text, len(st.history)
        self.assertIn('error', agent.run(st, 'transform_patterns', dict(action='chord', selections=select, shape='5')))
        self.assertEqual((st.text, len(st.history)), (before, n))
        call(action='chord', shape='5', overwrite=True)
        self.assertEqual(st.mod.patterns[0].rows[2][1].note, 67)
        self.batch4(st, 'undo')
        st.song_edit([{'op': 'mark', 'what': 'channel', 'key': 1, 'approved': True}])
        before, n = st.text, len(st.history)
        self.assertIn('error', agent.run(st, 'transform_patterns', dict(action='chord', selections=select, shape='5', overwrite=True)))
        self.assertEqual((st.text, len(st.history)), (before, n))

    def test_copy_move_overlap_fields_mix_and_undo(self):
        st = self.state()
        before, n = st.text, len(st.history)
        source = {'pattern': 'p1', 'from_row': 0, 'to_row': 2, 'channels': [1]}
        result = self.batch4(st, 'copy_pattern_region', source=source, pattern='p1', row=1, channel=1, move=True)
        self.assertEqual(result['changed_cells'], 2)
        self.assertIsNone(st.mod.patterns[0].rows[0][0].note)
        self.assertEqual(st.mod.patterns[0].rows[1][0].note, 60)
        self.assertEqual(len(st.history), n+1)
        self.batch4(st, 'undo')
        self.assertEqual(st.text, before)
        source['to_row'] = 0
        self.batch4(st, 'copy_pattern_region', source=source, pattern='p2', row=0, channel=1, mix=True)
        self.assertEqual(st.mod.patterns[1].rows[0][0].instrument, 2)
        self.batch4(st, 'copy_pattern_region', source=source, pattern='p2', row=1, channel=2, fields=['note'])
        self.assertEqual(st.mod.patterns[1].rows[1][1].note, 60)
        self.assertEqual(st.mod.patterns[1].rows[1][1].instrument, 0)

    def test_copy_refusals_do_not_clear_source(self):
        st = self.state()
        source = {'pattern': 'p1', 'from_row': 0, 'to_row': 0, 'channels': [1]}
        for extra in [dict(row=0, channel=1), dict(row=4, channel=1), dict(row=0, channel=1, mix=True, move=True)]:
            before, n = st.text, len(st.history)
            self.assertIn('error', agent.run(st, 'copy_pattern_region', dict(source=source, pattern='p2', **extra)))
            self.assertEqual((st.text, len(st.history)), (before, n))
        st.song_edit([{'op': 'mark', 'what': 'pattern', 'key': 'p1', 'approved': True}])
        self.batch4(st, 'copy_pattern_region', source=source, pattern='p2', row=1, channel=1)
        before, n = st.text, len(st.history)
        self.assertIn('error', agent.run(st, 'copy_pattern_region', dict(source=source, pattern='p2', row=2, channel=1, move=True)))
        self.assertEqual((st.text, len(st.history)), (before, n))

    def test_batch4_strict_bounds_readonly_noop_and_duplicates(self):
        st = self.state()
        before, n = st.text, len(st.history)
        selection = [{'pattern': 'p1', 'channels': [1]}]
        for name, args in [
            ('edit_pattern', dict(action='rename', pattern=0, new_name='Wrong')),
            ('transform_patterns', dict(action='transpose', selections=selection*2, semitones=1)),
            ('transform_patterns', dict(action='transpose', selections=selection, semitones=True)),
            ('transform_patterns', dict(action='clear', selections=[dict(pattern='p1', to_row=4)])),
            ('write_patterns', dict(patterns=[dict(pattern='p1', cells=[dict(row=0, channel=1, cell='D-5')]*2)]))]:
            self.assertIn('error', agent.run(st, name, args))
            self.assertEqual((st.text, len(st.history)), (before, n))
        self.assertEqual(self.batch4(st, 'transform_patterns', action='transpose', selections=selection, semitones=0)['changed_cells'], 0)
        self.assertEqual((st.text, len(st.history)), (before, n))
        st.read_only = True
        self.assertIn('error', agent.run(st, 'edit_section', dict(action='create', name='A', start=0, end=1)))
        self.assertIn('error', agent.run(st, 'transform_patterns', dict(action='transpose', selections=selection, semitones=1)))
        self.assertEqual((st.text, len(st.history)), (before, n))
        st.read_only = False

    def test_section_jump_guard_keeps_approved_pattern_and_history(self):
        st = self.state()
        st.edit_patterns([(0, [{'row': 3, 'ch': 0, 'cell': '... .. ... B01'}])])
        self.batch4(st, 'edit_section', action='create', name='A', start=0, end=1)
        st.song_edit([{'op': 'mark', 'what': 'pattern', 'key': 'p1', 'approved': True}])
        before, n = st.text, len(st.history)
        self.assertIn('approved', agent.run(st, 'edit_section', dict(action='move', name='A', to=2))['error'])
        self.assertEqual((st.text, len(st.history)), (before, n))

    def test_edit_instrument_and_sample_fields(self):
        from tests.test_gui import SONG_INS
        (self.dir / "song.yaml").write_bytes(SONG_INS.encode())
        st = self.state()
        def call(name, **args):
            out = agent.run(st, name, args)
            self.assertNotIn("error", out, out)
            return out
        call("edit_instrument", number=1, changes={"nna": "fade", "volume_envelope": {
            "nodes": [[0, 64], [10, 32]], "sustain": [1, 1]}})
        self.assertEqual(st.song["instruments"][1]["fadeout"], 128)
        self.assertEqual(st.mod.instruments[0].nna, 3)
        call("edit_sample", number=1, changes={"loop": {"start": 100, "end": 1000},
                                              "vibrato": {"type": "ramp_down", "speed": 3}})
        self.assertEqual(call("inspect_sample", number=1)["usage"]["instruments"], [1])
        call("edit_sample", number=1, clear=["loop"])
        self.assertNotIn("loop", st.song["samples"][1])
        for name, args in [("edit_instrument", {"number": 1, "changes": {"global_volume": 12}}),
                           ("edit_sample", {"number": 1, "changes": {"loop": {"start": 0, "end": 999999}}}),
                           ("edit_instrument", {"number": 1, "changes": {"sample": 99}})]:
            before = self.read()
            self.assertIn("error", agent.run(st, name, args))
            self.assertEqual(before, self.read())

    def test_delete_slots_checks_all_references_and_restores_holes(self):
        st = self.state()
        st.song_edit([{"op": "orders", "orders": ["p1"]}])
        out = agent.run(st, "delete_slot", {"kind": "sample", "number": 2})
        self.assertIn("error", out)
        self.assertIn("p2", {r["pattern"] for r in out["usage"]["references"]})
        st.song_edit([{"op": "sample_new", "num": 3, "file": "a.wav", "keep": {"volume": 13}},
                      {"op": "sample_new", "num": 4, "file": "b.wav"}])
        original = (self.dir / "a.wav").read_bytes()
        for name, args in [("delete_slot", {"kind": "sample", "number": 3}), ("undo", {}), ("redo", {})]:
            out = agent.run(st, name, args)
            self.assertNotIn("error", out, out)
        self.assertNotIn(3, st.song["samples"])
        self.assertIn(4, st.song["samples"])
        self.assertEqual((self.dir / "a.wav").read_bytes(), original)
        agent.run(st, "create_instrument", {"sample": 4})
        self.assertIn("error", agent.run(st, "delete_slot", {"kind": "sample", "number": 4}))
        n = max(st.song["instruments"])
        self.assertNotIn("error", agent.run(st, "delete_slot", {"kind": "instrument", "number": n}))
        # A shadowed default mapping still references a sample in the source format.
        st.song_edit([{"op": "instrument_new", "num": n, "entry": {"sample": 4,
            "keymap": [{"notes": "C-0..B-9", "sample": 1}]}}])
        self.assertIn(n, agent.run(st, "inspect_sample", {"number": 4})["usage"]["instruments"])

    def test_sample_processing_preserves_audio_and_undo(self):
        import numpy as np
        st = self.state()
        original = (self.dir / "a.wav").read_bytes()
        x = st._sample_wav(1)[3].copy()
        out = agent.run(st, "process_sample", {"number": 1, "action": "reverse"})
        self.assertNotIn("error", out, out)
        new_path = st.base_dir / st.song["samples"][1]["file"]
        self.assertTrue(np.allclose(st._sample_wav(1)[3], x[:, ::-1], atol=1 / 32768))
        self.assertEqual((self.dir / "a.wav").read_bytes(), original)
        self.assertNotIn("error", agent.run(st, "undo", {}))
        self.assertEqual(st.song["samples"][1]["file"], "a.wav")
        self.assertNotIn("error", agent.run(st, "redo", {}))
        self.assertEqual(st.base_dir / st.song["samples"][1]["file"], new_path)
        out = agent.run(st, "process_sample", {"number": 1, "action": "trim", "start": 100, "end": 2000})
        self.assertNotIn("error", out, out)
        self.assertEqual(st._sample_wav(1)[3].shape[1], 1900)
        before, files = self.read(), set(self.dir.glob("*.wav"))
        for args in [{"action": "gain", "params": {"db": float("nan")}},
                     {"action": "lowpass", "params": {"hz": -1}},
                     {"action": "trim", "start": True}, {"action": "auto_loop", "frames": 1},
                     {"action": "gain", "params": {"unrecognized": 1}},
                     {"action": "denoise", "params": {"na": 0, "nb": 999999}}]:
            self.assertIn("error", agent.run(st, "process_sample", {"number": 1, **args}))
            self.assertEqual(self.read(), before)
            self.assertEqual(set(self.dir.glob("*.wav")), files)

    def test_sample_tools_protect_approved_and_readonly_material(self):
        st = self.state()
        st.song_edit([{"op": "mark", "what": "pattern", "key": "p2", "approved": True}])
        before = self.read()
        # Sample 1 is only named in p1, but can sustain into approved p2.
        for name, args in [("process_sample", {"number": 1, "action": "reverse"}),
                           ("edit_sample", {"number": 1, "changes": {"base_note": "C-4"}})]:
            self.assertIn("approved", agent.run(st, name, args)["error"])
        self.assertEqual(self.read(), before)
        st.read_only = True
        self.assertIn("error", agent.run(st, "slice_sample", {"number": 1, "points": [0]}))
        out = agent.run(st, "inspect_sample", {"number": 1, "analysis": "slices", "slice_mode": "equal", "value": 2})
        self.assertNotIn("error", out, out)
        self.assertEqual(len(out["slices"]["points"]), 2)
        self.assertEqual(self.read(), before)

    def test_processing_effects_loops_and_failed_write_cleanup(self):
        import numpy as np
        tone = (12000 * np.sin(2 * np.pi * 440 * np.arange(RATE) / RATE)).astype(int).tolist()
        write_wav(self.dir / "a.wav", RATE, [tone])
        st = self.state()
        cases = [("fade_in", {}), ("fade_out", {}), ("normalize", {}), ("dc", {}),
                 ("gain", {"db": -6}), ("lowpass", {"hz": 1000}), ("highpass", {"hz": 200}),
                 ("eq", {"hz": 1000, "db": 3}), ("loudness", {"db": -20}),
                 ("pitch", {"semitones": 3}), ("stretch", {"percent": 125}),
                 ("denoise", {"na": 0, "nb": 4096})]
        for action, params in cases:
            with self.subTest(action=action):
                before = self.read()
                out = agent.run(st, "process_sample", {"number": 1, "action": action, "params": params})
                self.assertNotIn("error", out, out)
                self.assertNotEqual(st.song["samples"][1]["file"], "a.wav")
                self.assertNotIn("error", agent.run(st, "undo", {}))
                self.assertEqual(self.read(), before)
        before = self.read()
        out = agent.run(st, "inspect_sample", {"number": 1, "analysis": "loop"})
        self.assertNotIn("error", out, out)
        self.assertEqual(self.read(), before)
        out = agent.run(st, "process_sample", {"number": 1, "action": "auto_loop"})
        self.assertNotIn("error", out, out)
        self.assertEqual(st.song["samples"][1]["file"], "a.wav")
        self.assertEqual(st.song["samples"][1]["loop"]["start"], out["entry"]["loop"]["start"])
        out = agent.run(st, "process_sample", {"number": 1, "action": "crossfade", "frames": 50})
        self.assertNotIn("error", out, out)
        # A failure after generating the WAV must remove that new file and leave the song unchanged.
        before, files = self.read(), set(self.dir.glob("*.wav"))
        with mock.patch.object(st, "_commit", side_effect=OSError("test write failure")):
            out = agent.run(st, "process_sample", {"number": 1, "action": "reverse"})
        self.assertIn("error", out)
        self.assertEqual(self.read(), before)
        self.assertEqual(set(self.dir.glob("*.wav")), files)

    def test_slice_and_render_new_samples(self):
        st = self.state()
        original = self.read()
        out = agent.run(st, "slice_sample", {"number": 1, "points": [0, 4000], "end": 8000})
        self.assertNotIn("error", out, out)
        self.assertEqual(out["samples"], [3, 4])
        self.assertEqual(st._sample_wav(3)[3].shape[1], 4000)
        self.assertEqual(st.song["samples"][1]["file"], "a.wav")
        self.assertNotIn("error", agent.run(st, "undo", {}))
        self.assertEqual(original, self.read())
        out = agent.run(st, "render_sample", {"order": 0, "start_row": 0, "end_row": 1, "channels": [1], "tail": 0})
        self.assertNotIn("error", out, out)
        self.assertEqual(out["samples"], [3])
        self.assertGreater(st._sample_wav(3)[3].shape[1], 0)
        self.assertNotIn("error", agent.run(st, "undo", {}))
        self.assertEqual(original, self.read())
        for name, args in [("slice_sample", {"number": 1, "points": [0, 1]}),
                           ("render_sample", {"order": 0, "start_row": 0, "end_row": 1, "channels": [0]}),
                           ("render_sample", {"order": 99, "start_row": 0, "end_row": 1})]:
            self.assertIn("error", agent.run(st, name, args))
            self.assertEqual(original, self.read())

    def test_tools_read_edit_and_refuse(self):
        st = self.state()
        ov = agent.run(st, "song_overview", {})
        self.assertEqual([c["name"] for c in ov["channels"]], ["A", "B"])
        self.assertEqual(ov["orders"][0]["pattern"], "p1")
        rows = agent.run(st, "read_pattern", {"pattern": "p1", "to_row": 1})["rows"]
        self.assertEqual(rows[0], "00: C-5 01 ... ... | ... .. ... ...")
        out = agent.run(st, "write_cells", {"pattern": "p2", "cells": [{"row": 1, "channel": 2, "cell": "E-5 02 v40 ..."}]})
        self.assertTrue(out.get("ok"), out)
        self.assertIn("  p2:\n    by: you and agent\n", self.read())   # p2 had notes: the owner's and the agent's now
        self.assertEqual(st.pattern_rows(1)["rows"][1][1], "E-5 02 v40 ...")
        st.undo()
        self.assertNotIn("by:", self.read())
        # an approved channel or pattern is refused, and nothing is written
        st.song_edit([{"op": "mark", "what": "channel", "key": 1, "approved": True},
                      {"op": "mark", "what": "pattern", "key": "p1", "approved": True}])
        text = self.read()
        self.assertIn("    - {name: B, pan: 40, approved: true}\n", text)
        self.assertIn("  p1:\n    approved: true\n", text)
        self.assertIn("approved", agent.run(st, "write_cells", {"pattern": "p2", "cells": [{"row": 0, "channel": 2, "cell": "C-5 01 ... ..."}]})["error"])
        self.assertIn("approved", agent.run(st, "write_cells", {"pattern": "p1", "cells": [{"row": 0, "channel": 1, "cell": "C-5 01 ... ..."}]})["error"])
        self.assertEqual(self.read(), text)
        # a level is not a setting the tools set; a new pattern is the agent's
        self.assertIn("levels", agent.run(st, "set_module", {"key": "mix_volume", "value": 20})["error"])
        self.assertTrue(agent.run(st, "new_pattern", {"name": "p9", "rows": 4, "insert_at": 1}).get("ok"))
        self.assertIn("  p9:\n    by: agent\n", self.read())
        self.assertEqual(agent.run(st, "song_overview", {})["orders"][1]["pattern"], "p9")
        self.assertTrue(agent.run(st, "set_module", {"key": "key", "value": "A minor"}).get("ok"))
        self.assertEqual(agent.run(st, "key_check", {})["key"], "A minor")
        self.assertEqual(len(st.agent_log), 10)   # every call logged, the refused ones too

    def test_plugins_respect_approved_channels(self):
        st = self.state()
        st.song_edit([{"op": "mark", "what": "channel", "key": 0, "approved": True}])
        out = agent.run(st, "set_plugins", {"plugins": {"1": {"effect": "echo"}}, "channel_plugins": {"2": 1}})
        self.assertTrue(out.get("ok"), out)
        self.assertEqual(st.facts["channel_plugins"], [0, 1])
        self.assertIn("approved", agent.run(st, "set_plugins", {"channel_plugins": {"1": 1}})["error"])

    def test_flanger_routes_on_imported_channel_layout(self):
        # api.to_yaml (also used by module import) writes indentless channel sequences.
        song = api.load(self.dir / 'song.yaml')
        song['module']['channels'] = [{'name': f'Ch {n}'} for n in range(1, 18)]
        text = api.to_yaml(song)
        self.assertIn('  channels:\n  - ', text)
        (self.dir / 'song.yaml').write_bytes(text.encode())
        st = self.state()
        before = self.read()
        out = agent.run(st, 'set_plugins', {'plugins': {'1': {'effect': 'flanger', 'name': 'Melody flanger'}},
                                           'channel_plugins': {'9': 1}})
        self.assertTrue(out.get('ok'), out)
        self.assertEqual(st.facts['channel_plugins'], [0]*8 + [1] + [0]*8)
        self.assertEqual(st.facts['plugins'][1]['effect'], 'flanger')
        st.undo()
        self.assertEqual(self.read(), before)
        st.song_edit([{'op': 'mark', 'what': 'channel', 'key': 8, 'approved': True}])
        self.assertIn('approved', agent.run(st, 'set_plugins', {'channel_plugins': {'9': 1}})['error'])

    def test_create_channel_imported_and_limit(self):
        song = api.load(self.dir / 'song.yaml')
        song['module']['channels'] = [{'name': f'Ch {n}'} for n in range(1, 18)]
        (self.dir / 'song.yaml').write_bytes(api.to_yaml(song).encode())
        st = self.state()
        before, rows = self.read(), [p.rows for p in st.mod.patterns]
        out = agent.run(st, 'create_channel', {'name': 'Melody'})
        self.assertEqual(out.get('channel'), 18, out)
        for old, p in zip(rows, st.mod.patterns):
            for a, b in zip(old, p.rows):
                self.assertEqual(a, b[:17])
                self.assertTrue(b[17].is_empty())
        self.assertEqual(len(st.history), 1)
        st.undo()
        self.assertEqual(self.read(), before)
        for name in ['', 'x'*21, 123]:
            self.assertIn('error', agent.run(st, 'create_channel', {'name': name}))
        st.read_only = True
        self.assertIn('error', agent.run(st, 'create_channel', {}))
        st.read_only = False
        song['module']['channels'] = [{'name': f'Ch {n}'} for n in range(1, 65)]
        st._commit(api.to_yaml(song))
        self.assertIn('64', agent.run(st, 'create_channel', {})['error'])

    def test_complete_state_and_atomic_audition(self):
        st = self.state()
        st.selection = {'order': 0, 'rows': [0, 1], 'channels': [0, 1], 'pattern': 'p1'}
        st.ui_state = {'reported_at': time.time(), 'rack_channel': 2, 'applied_request': 7}
        before = self.read()
        result = agent.run(st, 'get_state', {})
        self.assertFalse(result['ui_stale'])
        self.assertEqual(result['selection']['channels'], [1, 2])
        self.assertEqual(result['samples'], st.song['samples'])
        self.assertEqual(result['rack']['channel_plugins'], {1: 0, 2: 0})
        st.ui_state['reported_at'] -= 10
        self.assertTrue(agent.run(st, 'get_state', {})['ui_stale'])
        meta = json.dumps(st.meta, sort_keys=True)
        for changes in [{'solo': 3}, {'solo': True}, {'muted': [0]},
                        {'solo': 1, 'loop': {'from': [1, 3], 'to': [0, 1]}},
                        {'loop': {'from': [0, 0], 'to': [0, 4]}}, {'mix': {}}]:
            self.assertIn('error', agent.run(st, 'set_audition', changes))
            self.assertEqual(json.dumps(st.meta, sort_keys=True), meta)
        out = agent.run(st, 'set_audition', {'solo': 2, 'muted': [1], 'loop': {'from': [0, 1], 'to': [1, 2]}})
        self.assertTrue(out.get('ok'), out)
        self.assertEqual(st.meta['solo'], 1)
        self.assertEqual(st.meta['muted'], [0])
        self.assertEqual(st.meta['orders'], [0, 2])
        self.assertEqual(json.loads(st.meta_path.read_text())['solo'], 1)
        self.assertEqual(self.read(), before)
        self.assertEqual(len(st.history), 0)
        stop = agent.run(st, 'stop_playback', {})
        self.assertEqual(stop['request_id'], out['request_id'] + 1)
        self.assertEqual(stop['status'], 'queued')
        self.assertEqual(st.cue['action'], 'stop')
        self.assertGreater(st.cue['expires'], time.time())
        self.assertTrue(agent.run(st, 'set_audition', {'solo': None, 'muted': [], 'loop': None})['ok'])
        self.assertEqual(st.mix(), result['audition']['mix'])

    def test_targeted_rack_edits_and_inspection(self):
        st = self.state()
        for effect in ['chorus', 'distortion', 'flanger']:
            out = agent.run(st, 'edit_effect', {'action': 'add', 'channel': 2, 'effect': effect})
            self.assertTrue(out.get('ok'), out)
        self.assertEqual(agent._chain(st.facts, 1), [1, 2, 3])
        self.assertTrue(agent.run(st, 'set_plugins', {'macros': {'SF1': 'F0F080z'}})['ok'])
        before = agent.run(st, 'get_state', {})['rack']
        out = agent.run(st, 'edit_effect', {'action': 'update', 'plugin': 2, 'changes': {'gain': -9, 'bypass': True}})
        self.assertTrue(out.get('ok'), out)
        after = agent.run(st, 'get_state', {})['rack']
        self.assertEqual(after['plugins'][1], before['plugins'][1])
        self.assertEqual(after['plugins'][3], before['plugins'][3])
        self.assertEqual(after['macros'], before['macros'])
        self.assertEqual(after['plugins'][2]['gain'], -9)
        self.assertTrue(after['plugins'][2]['bypass'])
        for changes in [{'gain': 999}, {'output': 1}]:
            text, steps = self.read(), len(st.history)
            self.assertIn('error', agent.run(st, 'edit_effect', {'action': 'update', 'plugin': 2, 'changes': changes}))
            self.assertEqual((self.read(), len(st.history)), (text, steps))
        out = agent.run(st, 'edit_effect', {'action': 'move', 'channel': 2, 'plugin': 3, 'position': 1})
        self.assertTrue(out.get('ok'), out)
        self.assertEqual(agent._chain(st.facts, 1), [3, 1, 2])
        self.assertTrue(agent.run(st, 'edit_effect', {'action': 'remove', 'plugin': 1})['ok'])
        self.assertEqual(agent._chain(st.facts, 1), [3, 2])
        self.assertTrue(agent.run(st, 'edit_effect', {'action': 'remove', 'plugin': 3})['ok'])
        self.assertEqual(st.facts['channel_plugins'], [0, 2])

    def test_rack_protection_preflights_shared_and_master(self):
        st = self.state()
        self.assertTrue(agent.run(st, 'set_plugins', {'plugins': {1: {'effect': 'echo'}, 2: {'effect': 'chorus', 'master': True}},
                                                      'channel_plugins': {1: 1, 2: 1}})['ok'])
        self.assertIn('shared', agent.run(st, 'edit_effect', {'action': 'move', 'channel': 2, 'plugin': 1, 'position': 1})['error'])
        st.song_edit([{'op': 'mark', 'what': 'channel', 'key': 0, 'approved': True}])
        text, steps = self.read(), len(st.history)
        for args in [{'action': 'update', 'plugin': 1, 'changes': {'bypass': True}},
                     {'action': 'remove', 'plugin': 1}, {'action': 'add', 'channel': 2, 'effect': 'flanger'},
                     {'action': 'update', 'plugin': 2, 'changes': {'bypass': True}}]:
            self.assertIn('approved', agent.run(st, 'edit_effect', args)['error'])
            self.assertEqual((self.read(), len(st.history)), (text, steps))
        self.assertIn('approved', agent.run(st, 'set_plugins', {'macros': {'SF1': 'F0F080z'}})['error'])

    def test_agent_checkpoints_restore_and_redo(self):
        st = self.state()
        def cp(action):
            return agent.run(st, 'checkpoint', {'action': action, 'name': 'Before FX'})
        self.assertTrue(cp('save').get('ok'))
        self.assertIn('exists', cp('save')['error'])
        self.assertEqual(cp('list')['checkpoints'], ['Before FX'])
        before = self.read()
        self.assertTrue(agent.run(st, 'edit_effect', {'action': 'add', 'channel': 2, 'effect': 'distortion'})['ok'])
        changed = self.read()
        self.assertTrue(cp('diff')['ok'])
        result = cp('restore')
        self.assertTrue(result.get('ok'), result)
        self.assertEqual(self.read(), before)
        st.undo()
        self.assertEqual(self.read(), changed)
        result = agent.run(st, 'redo', {})
        self.assertTrue(result.get('ok'), result)
        self.assertEqual(self.read(), before)
        self.assertTrue(cp('delete')['ok'])
        self.assertEqual(cp('list')['checkpoints'], [])

    def test_checkpoint_protects_owner_changes(self):
        st = self.state()
        self.assertTrue(agent.run(st, 'checkpoint', {'action': 'save', 'name': 'Before'})['ok'])
        st.song_edit([{'op': 'mark', 'what': 'channel', 'key': 0, 'approved': True}])
        text = self.read()
        out = agent.run(st, 'checkpoint', {'action': 'restore', 'name': 'Before'})
        self.assertIn('approved', out['error'])
        self.assertEqual(self.read(), text)
        st.undo()
        st.meta['mix'] = {'channel_volume': {'0': 20}}
        self.assertIn('levels', agent.run(st, 'checkpoint', {'action': 'restore', 'name': 'Before'})['error'])

    def wait_chat(self, chat):
        for _ in range(200):
            if not chat.busy:
                return
            time.sleep(.01)
        self.fail('chat did not stop within two seconds')

    def test_channel_operations_carry_notes_routing_and_owner_faders(self):
        st = self.state()
        st.set_mix({'volume': {'0': 23, '1': 41}, 'pan': {'0': 12}})
        st.meta.update(solo=0, muted=[1])
        self.assertTrue(agent.run(st, 'edit_effect', {'action': 'add', 'channel': 1, 'effect': 'echo'})['ok'])
        before, rows = self.read(), [p.rows for p in st.mod.patterns]
        out = agent.run(st, 'edit_channel', {'action': 'move', 'channel': 1, 'to': 2})
        self.assertEqual(out.get('channel_map'), {1: 2, 2: 1}, out)
        self.assertEqual(st.facts['channel_plugins'], [0, 1])
        self.assertEqual(st.meta['mix']['volume'], {'1': 23, '0': 41})
        self.assertEqual((st.meta['solo'], st.meta['muted']), (1, [0]))
        self.assertEqual([p.rows for p in st.mod.patterns], [[list(reversed(r)) for r in p] for p in rows])
        moved = self.read()
        for tool, expected in [('undo', before), ('redo', moved)]:
            out = agent.run(st, tool, {})
            self.assertTrue(out.get('ok'), out)
            self.assertEqual(self.read(), expected)
        self.assertTrue(agent.run(st, 'edit_channel', {'action': 'rename', 'channel': 2, 'name': 'Lead'})['ok'])
        before = self.read()
        self.assertIn('remove_notes', agent.run(st, 'edit_channel', {'action': 'remove', 'channel': 1})['error'])
        self.assertEqual(self.read(), before)
        out = agent.run(st, 'edit_channel', {'action': 'remove', 'channel': 1, 'remove_notes': True})
        self.assertEqual(out.get('channel_map'), {1: None, 2: 1}, out)
        self.assertEqual(st.meta['mix']['volume'], {'0': 23})
        out = agent.run(st, 'undo', {})
        self.assertTrue(out.get('ok'), out)
        self.assertEqual(self.read(), before)

    def test_channel_operations_protect_approved_material_and_validate(self):
        st = self.state()
        st.song_edit([{'op': 'mark', 'what': 'channel', 'key': 1, 'approved': True}])
        before = self.read()
        for args in [{'action': 'move', 'channel': 1, 'to': 2},
                     {'action': 'remove', 'channel': 1, 'remove_notes': True},
                     {'action': 'rename', 'channel': 2, 'name': 'Changed'},
                     {'action': 'move', 'channel': 1, 'to': True},
                     {'action': 'rename', 'channel': 0, 'name': 'Changed'}]:
            self.assertIn('error', agent.run(st, 'edit_channel', args))
            self.assertEqual(self.read(), before)
        st.undo()
        st.song_edit([{'op': 'mark', 'what': 'pattern', 'key': 'p1', 'approved': True}])
        self.assertIn('approved', agent.run(st, 'edit_channel', {'action': 'move', 'channel': 1, 'to': 2})['error'])
        self.assertEqual(agent.run(st, 'create_channel', {})['channel'], 3)
        self.assertIn('approved', agent.run(st, 'edit_channel', {'action': 'remove', 'channel': 3})['error'])

    def test_new_sample_is_undoable_and_never_replaces_existing_slots(self):
        st = self.state()
        st.song_edit([{'op': 'mark', 'what': 'channel', 'key': 0, 'approved': True}])
        before, audio = self.read(), (self.dir / 'a.wav').read_bytes()
        out = agent.run(st, 'create_sample', {'file': str(self.dir / 'a.wav'), 'base_note': 'A-5', 'name': 'Imported'})
        self.assertEqual(out.get('sample'), 3, out)
        self.assertEqual(out['entry']['base_note'], 'A-5')
        self.assertEqual((self.dir / 'a.wav').read_bytes(), audio)
        self.assertEqual(st.mod.samples[2].name, 'Imported')
        out = agent.run(st, 'undo', {})  # unused additions don't change the approved channel's voice
        self.assertTrue(out.get('ok'), out)
        self.assertEqual(self.read(), before)
        for args in [{'file': 'a.wav', 'number': 1}, {'file': 'a.wav', 'number': True},
                     {'file': 'missing.wav'}, {'file': 'a.wav', 'base_note': 'bad'},
                     {'file': 'a.wav', 'stereo': 'false'}, {'file': 'a.wav', 'volume': 10}]:
            self.assertIn('error', agent.run(st, 'create_sample', args))
            self.assertEqual(self.read(), before)
        st.read_only = True
        self.assertIn('error', agent.run(st, 'create_sample', {'file': 'a.wav'}))

    def test_first_instrument_wraps_samples_atomically_then_supports_keymaps(self):
        st = self.state()
        before, rows = self.read(), [p.rows for p in st.mod.patterns]
        out = agent.run(st, 'create_instrument', {'sample': 2, 'name': 'New voice'})
        self.assertEqual((out.get('instrument'), out.get('converted_samples')), (3, 2), out)
        self.assertEqual([p.rows for p in st.mod.patterns], rows)
        for i in range(2):
            self.assertEqual(st.mod.instruments[i].keymap, [(n, i + 1) for n in range(120)])
            self.assertEqual(st.mod.instruments[i].fadeout, 8)
        self.assertTrue(agent.run(st, 'undo', {})['ok'])
        self.assertEqual(self.read(), before)
        self.assertTrue(agent.run(st, 'redo', {})['ok'])
        out = agent.run(st, 'create_instrument', {'keymap': [{'notes': 'C-0..B-4', 'sample': 1},
                                                          {'notes': 'C-5..B-9', 'sample': 2}]})
        self.assertEqual(out.get('instrument'), 4, out)
        self.assertEqual([st.mod.instruments[3].keymap[n][1] for n in [0, 59, 60, 119]], [1, 1, 2, 2])
        out = agent.run(st, 'create_instrument', {})
        self.assertEqual(out.get('instrument'), 5, out)
        self.assertTrue(all(s == 0 for _, s in st.mod.instruments[4].keymap))

    def test_instrument_creation_failure_preserves_sample_mode_and_approvals(self):
        st = self.state()
        before = self.read()
        for args in [{'number': 1}, {'sample': 99}, {'sample': True},
                     {'keymap': [{'notes': 'bad', 'sample': 1}]}, {'sample': 1, 'keymap': []}]:
            self.assertIn('error', agent.run(st, 'create_instrument', args))
            self.assertEqual(self.read(), before)
            self.assertIsNone(st.mod.instruments)
        st.song_edit([{'op': 'mark', 'what': 'channel', 'key': 0, 'approved': True}])
        self.assertIn('approved', agent.run(st, 'create_instrument', {'sample': 1})['error'])

    def test_agent_export_completion_and_snapshot_options(self):
        st = self.state()
        self.assertEqual(agent.run(st, 'export_status', {}), {'job': None})
        st.section_edit({'name': 'End', 'start': 1, 'end': 2})
        before = self.read()
        st.meta.update(solo=0)
        opts = {'format': 'wav', 'destination': 'outputs', 'name': 'melody', 'region': 'End',
                'stems': True, 'include_it': True, 'game_loop': True, 'tail': 0, 'mix': 'current', 'mutes': 'respect'}
        out = agent.run(st, 'export_song', opts)
        self.assertTrue(out.get('ok'), out)
        job_id = out['job']['job_id']
        for _ in range(200):
            job = agent.run(st, 'export_status', {'job_id': job_id})['job']
            if job['status'] in ('done', 'failed', 'cancelled'):
                break
            time.sleep(.02)
        self.assertEqual(job['status'], 'done', job)
        self.assertEqual(set(job['files']), set(job['planned_files']))
        self.assertTrue(all(Path(p).is_file() for p in job['files']))
        self.assertTrue(any(Path(p).suffix == '.it' for p in job['files']))
        self.assertIsNotNone(job['loop'])
        self.assertEqual(self.read(), before)
        self.assertIn('error', agent.run(st, 'export_song', opts))  # no implicit overwrite
        self.assertIn('error', agent.run(st, 'export_status', {'job_id': 'old'}))
        self.assertFalse(agent.run(st, 'cancel_export', {'job_id': job_id})['cancellation_requested'])

    def test_agent_export_validation_cancellation_and_source_protection(self):
        from vulturetracker import export
        st = self.state()
        before = (self.dir / 'a.wav').read_bytes()
        for args in [{}, {'format': 'pdf'}, {'format': 'wav', 'replace': 'false'},
                     {'format': 'wav', 'name': 'a', 'destination': '.', 'replace': True},
                     {'format': 'wav', 'region': 'Missing'}, {'format': 'mp3', 'game_loop': True}]:
            self.assertIn('error', agent.run(st, 'export_song', args))
            self.assertEqual((self.dir / 'a.wav').read_bytes(), before)
        with mock.patch.object(st, '_put'):
            out = agent.run(st, 'export_song', {'format': 'it', 'destination': 'outputs'})
            job_id = out['job']['job_id']
            self.assertIn('error', agent.run(st, 'export_song', {'format': 'it'}))
            self.assertIn('error', agent.run(st, 'cancel_export', {'job_id': 'wrong'}))
            self.assertFalse(st.export_job['cancel'].is_set())
            out = agent.run(st, 'cancel_export', {'job_id': job_id})
            self.assertTrue(out['cancellation_requested'])
            self.assertEqual(export.run(st.export_job, gui._encode)['status'], 'cancelled')
            self.assertEqual(agent.run(st, 'export_status', {'job_id': job_id})['job']['files'], [])
            self.assertFalse((self.dir / 'outputs' / 'song.it').exists())

    def test_stop_discards_late_response_and_allows_next_message(self):
        st = self.state()
        before = self.read()
        agent.save_settings({'provider':'openai', 'model':'fixture'})
        started, release, returned = threading.Event(), threading.Event(), threading.Event()
        def delayed(*args):
            started.set()
            release.wait(5)
            returned.set()
            return {'choices':[{'message':{'role':'assistant','tool_calls':[
                {'id':'late','function':{'name':'set_module','arguments':'{"key":"key","value":"D major"}'}}]}}]}
        chat = agent.Chat()
        try:
            with mock.patch.object(agent, 'compatible_request', side_effect=delayed):
                chat.send(st, 'make a change')
                self.assertTrue(started.wait(2))
                chat.stop()
                self.wait_chat(chat)
            answer = {'choices':[{'message':{'role':'assistant','content':'Next answer'}}],
                      'usage':{'prompt_tokens':123,'completion_tokens':7}}
            with mock.patch.object(agent, 'compatible_request', return_value=answer):
                chat.send(st, 'next message')
                self.wait_chat(chat)
            release.set()
            self.assertTrue(returned.wait(2))
            self.assertEqual(self.read(), before)
            self.assertEqual(chat.display[-1]['text'], 'Next answer')
            self.assertFalse(any(m.get('tool_calls') for m in chat.history))
            context = chat.snapshot()['context']
            self.assertEqual((context['input'],context['output']), (123,7))
            self.assertEqual(context['source'],'estimate')
        finally:
            release.set()

    def test_stop_between_tools_keeps_valid_history_and_completed_edit(self):
        st = self.state()
        agent.save_settings({'provider':'openai','model':'fixture'})
        reply = {'choices':[{'message':{'role':'assistant','tool_calls':[
            {'id':'a','function':{'name':'set_module','arguments':'{"key":"key","value":"D major"}'}},
            {'id':'b','function':{'name':'undo','arguments':'{}'}}]}}]}
        chat, run = agent.Chat(), agent.run
        def first(*args):
            result = run(*args)
            chat.stop()
            return result
        with mock.patch.object(agent,'compatible_request',return_value=reply), mock.patch.object(agent,'run',side_effect=first):
            chat.send(st,'two actions')
            self.wait_chat(chat)
        self.assertEqual(st.song['module']['key'],'D major')
        results = [json.loads(m['content']) for m in chat.history if m['role']=='tool']
        self.assertTrue(results[0]['ok'])
        self.assertIn('stopped',results[1]['error'])
        self.assertEqual(len(results),2)

    def test_chat_discovers_tools_then_edits_and_undoes_through_wrapper(self):
        st = self.state()
        original = self.read()
        agent.save_settings({'provider': 'openai', 'model': 'fixture'})
        def call(name, args):
            return {'choices': [{'message': {'role': 'assistant', 'tool_calls': [
                {'id': name, 'type': 'function', 'function': {'name': name, 'arguments': json.dumps(args)}}]}}]}
        replies = [call('find_tools', {'names': ['set_module', 'undo']}),
                   call('call_tool', {'name': 'set_module', 'arguments_json': '{"key":"key","value":"D major"}'}),
                   call('call_tool', {'name': 'undo', 'arguments_json': '{}'}),
                   {'choices': [{'message': {'role': 'assistant', 'content': 'Done'}}]}]
        with mock.patch.object(agent, 'compatible_request', side_effect=replies) as request:
            chat = self._chat(st, 'Try D major then undo')
        self.assertEqual(self.read(), original)
        self.assertEqual(chat.display[-1]['text'], 'Done')
        self.assertEqual([m['tool'] for m in chat.display if m['role'] == 'tool'],
                         ['find_tools', 'set_module', 'undo'])
        for invocation in request.call_args_list:
            self.assertEqual({t['function']['name'] for t in invocation.args[2]['tools']},
                             {'find_tools', 'call_tool', 'read_tool_result'})
        self.assertEqual([m['tool'] for m in st.agent_log[-2:]], ['set_module', 'undo'])

    def test_wrapped_tool_keeps_stop_and_approved_pattern_guards(self):
        st, chat = self.state(), agent.Chat()
        st.song_edit([{'op': 'mark', 'what': 'pattern', 'key': 'p1', 'approved': True}])
        original = self.read()
        args = {'name': 'write_cells', 'arguments_json': json.dumps(
            {'pattern': 'p1', 'cells': [{'row': 0, 'channel': 1, 'cell': 'D-5 01 ... ...'}]})}
        out = chat._tool(st, 'call_tool', args)
        self.assertIn('approved', out['error'])
        self.assertEqual(self.read(), original)
        chat.busy, chat.run_id = True, 'active'
        chat.cancel.set()
        self.assertIn('stopped', chat.remote_tool(st, 'call_tool', {'name': 'undo', 'arguments_json': '{}'}, 'active')['error'])

    def test_compact_keeps_transcript_and_seeds_next_request_without_tools(self):
        st = self.state()
        agent.save_settings({'provider':'gemini','api_key':'fixture'})
        answer = lambda text: {'choices':[{'finish_reason':'stop','message':{'role':'assistant','content':text}}]}
        with mock.patch.object(agent,'compatible_request',return_value=answer('Detailed reply '*300)):
            chat=self._chat(st,'Keep the drums; change only channel 9.')
        display=list(chat.display)
        before=chat.snapshot()['context']['tokens']
        with mock.patch.object(agent,'compatible_request',return_value=answer('Owner approved drums. Work only on channel 9.')) as req:
            chat.compact(st)
            self.wait_chat(chat)
            self.assertNotIn('tools',req.call_args.args[2])
        self.assertEqual(chat.display[:len(display)],display)
        self.assertEqual(chat.display[-1]['text'], 'Context compacted.')
        self.assertFalse(any('Owner approved drums' in m.get('text', '') for m in chat.display))
        self.assertLess(chat.snapshot()['context']['tokens'],before)
        with mock.patch.object(agent,'compatible_request',return_value=answer('Continuing')) as req:
            chat.send(st,'continue')
            self.wait_chat(chat)
            messages=req.call_args.args[2]['messages']
        self.assertIn('Owner approved drums',messages[1]['content'])
        self.assertEqual(messages[-1]['content'],'continue')
        self.assertFalse(any('tool_calls' in m for m in messages))

    def test_failed_or_stopped_compaction_preserves_context(self):
        st=self.state()
        agent.save_settings({'provider':'openai','model':'fixture'})
        chat=agent.Chat()
        with mock.patch.object(agent,'compatible_request',return_value={'choices':[{'message':{'role':'assistant','content':'Prior reply'}}]}):
            chat.send(st,'prior request')
            self.wait_chat(chat)
        history=list(chat.history)
        with mock.patch.object(agent,'compatible_request',side_effect=ValueError('fixture failure')):
            chat.compact(st)
            self.wait_chat(chat)
        self.assertEqual(chat.history,history)
        started,release=threading.Event(),threading.Event()
        def delayed(*args):
            started.set();release.wait(5)
            return {'choices':[{'message':{'role':'assistant','content':'Discard me'}}]}
        try:
            with mock.patch.object(agent,'compatible_request',side_effect=delayed):
                chat.compact(st)
                self.assertTrue(started.wait(2))
                chat.stop();self.wait_chat(chat)
            self.assertEqual(chat.history,history)
        finally:
            release.set()

    def test_stopped_claude_run_rejects_late_mcp_tools(self):
        st=self.state()
        chat=agent.Chat()
        chat.busy=True;chat.run_id='current'
        proc=chat.process=mock.Mock()
        self.assertIn('channels',chat.remote_tool(st,'song_overview',{},'current'))
        proc.poll.assert_not_called()  # completing a tool must not terminate its owning model process
        chat.process=None
        self.assertIn('stopped',chat.remote_tool(st,'undo',{},'old')['error'])
        chat.stop()
        self.assertIn('stopped',chat.remote_tool(st,'undo',{},'current')['error'])
        with mock.patch.dict(os.environ,{'VT_AGENT_RUN_ID':'current'}), mock.patch.object(mcp,'_http',return_value={'ok':True}) as http:
            mcp.handle({'id':1,'method':'tools/call','params':{'name':'song_overview'}},port=8765)
        self.assertEqual(http.call_args.args[2]['run_id'],'current')

    def test_measure_reports_the_change(self):
        st = self.state()
        first = agent.run(st, "measure", {})
        self.assertIsNotNone(first["numbers"]["lufs"])
        self.assertNotIn("change_since_last", first)
        st.song_edit([{"op": "channel_add", "name": "C"}])
        second = agent.run(st, "measure", {})
        self.assertEqual(second["change_since_last"]["lufs"], 0.0)   # an empty channel changes nothing
        solo = agent.run(st, "measure", {"channels": [1]})
        self.assertLess(solo["numbers"]["lufs"], first["numbers"]["lufs"])

    def test_selection_and_cue(self):
        st = self.state()
        self.assertIsNone(agent.run(st, "get_selection", {})["selection"])
        st.selection = {"order": 0, "pattern": "p1", "rows": [0, 1], "channels": [0, 0]}
        sel = agent.run(st, "get_selection", {})
        self.assertEqual(sel["cells"], ["00: C-5 01 ... ...", "01: ... .. ... ..."])
        self.assertEqual(sel["sounding_at_first_row"][0]["name"], "A")
        agent.run(st, "cue", {"order": 1, "row": 2, "play": True})
        self.assertEqual({k: st.cue[k] for k in ('id', 'order', 'row', 'channel', 'play')},
                         {"id": 1, "order": 1, "row": 2, "channel": None, "play": True})
        before = dict(st.cue)
        for args in [{'order': 1, 'row': 4}, {'order': 1, 'channel': 0}, {'order': -1}]:
            self.assertIn('error', agent.run(st, 'cue', args))
            self.assertEqual(st.cue, before)

    def test_mcp_without_the_app(self):
        out = mcp.handle({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18"}})
        self.assertEqual(out["result"]["serverInfo"]["name"], "vulturetracker")
        self.assertIsNone(mcp.handle({"jsonrpc": "2.0", "method": "notifications/initialized"}))
        tools = mcp.handle({"jsonrpc": "2.0", "id": 2, "method": "tools/list"}, port=1)["result"]["tools"]
        self.assertIn("write_cells", [t["name"] for t in tools])
        self.assertIn("inputSchema", tools[0])
        call = mcp.handle({"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "song_overview"}}, port=1)
        self.assertTrue(call["result"]["isError"])
        out = io.StringIO()
        mcp.serve(1, io.StringIO('{"jsonrpc":"2.0","id":4,"method":"ping"}\nnot json\n'), out)
        lines = [json.loads(x) for x in out.getvalue().splitlines()]
        self.assertEqual(lines[0], {"jsonrpc": "2.0", "id": 4, "result": {}})
        self.assertEqual(lines[1]["error"]["code"], -32700)

    def test_check_error_flags(self):
        from types import SimpleNamespace

        st = self.state()
        for error in (None, ["invalid song"]):
            with self.subTest(error=error):
                st.error = error
                st.facts["warnings"] = ["unused pattern"]
                chat = agent.Chat()
                out = chat._tool(st, "check", {})
                self.assertEqual(chat.display[-1]["error"], bool(error))
                with mock.patch.object(mcp, "_http", return_value=out):
                    result = mcp.handle({"id": 1, "method": "tools/call", "params": {"name": "check"}}, port=1)["result"]
                self.assertEqual(result["isError"], bool(error))
                self.assertEqual(json.loads(result["content"][0]["text"]), out)

                client = mock.Mock()
                client.beta.messages.create.side_effect = [
                    SimpleNamespace(stop_reason="tool_use", content=[
                        SimpleNamespace(type="tool_use", id="check1", name="check", input={})]),
                    SimpleNamespace(stop_reason="end_turn", content=[])]
                with mock.patch.dict(sys.modules, {"anthropic": SimpleNamespace(Anthropic=lambda **kw: client)}):
                    chat._anthropic(st, {}, "check the song")
                result = chat.history[-2]["content"][0]
                self.assertEqual(result["is_error"], bool(error))
                self.assertEqual(json.loads(result["content"])["warnings"], ["unused pattern"])

    def _fake(self, answers):
        Fake.answers, Fake.seen, Fake.headers_seen = list(answers), [], []
        srv = ThreadingHTTPServer(("127.0.0.1", 0), Fake)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        self.addCleanup(srv.server_close)
        self.addCleanup(srv.shutdown)
        return srv.server_address[1]

    def _chat(self, st, text, context=None):
        chat = agent.Chat()
        chat.send(st, text, context)
        for _ in range(200):
            if not chat.busy:
                break
            time.sleep(0.05)
        return chat

    def test_chat_anthropic(self):
        try:
            import anthropic  # noqa: F401
        except ImportError:
            self.skipTest("needs the anthropic package")
        st = self.state()
        msg = lambda content, stop: {"id": "msg_1", "type": "message", "role": "assistant", "model": "claude-opus-5-5",  # noqa: E731
                                     "content": content, "stop_reason": stop, "stop_sequence": None,
                                     "usage": {"input_tokens": 1, "output_tokens": 1}}
        port = self._fake([msg([{"type": "text", "text": "Looking."},
                                {"type": "tool_use", "id": "tu_1", "name": "song_overview", "input": {}}], "tool_use"),
                           msg([{"type": "text", "text": "Two channels, A and B."}], "end_turn")])
        agent.save_settings({"provider": "anthropic", "api_key": "test-key"})
        old = os.environ.get("ANTHROPIC_BASE_URL")
        os.environ["ANTHROPIC_BASE_URL"] = f"http://127.0.0.1:{port}"
        try:
            chat = self._chat(st, "what channels are there?", "channel 01 A")
        finally:
            if old is None:
                os.environ.pop("ANTHROPIC_BASE_URL")
            else:
                os.environ["ANTHROPIC_BASE_URL"] = old
        self.assertEqual([m["role"] for m in chat.display], ["you", "agent", "tool", "agent"], chat.display)
        self.assertEqual(chat.display[-1]["text"], "Two channels, A and B.")
        first, second = Fake.seen[0][1], Fake.seen[1][1]
        self.assertEqual(first["model"], "claude-opus-5-5")
        self.assertEqual(first["fallbacks"], "default")
        self.assertEqual(first["output_config"], {"effort": "medium"})
        self.assertIn("[the owner's selection: channel 01 A]", first["messages"][0]["content"])
        result = second["messages"][2]["content"][0]
        self.assertEqual((result["type"], result["tool_use_id"]), ("tool_result", "tu_1"))
        self.assertEqual(json.loads(result["content"])["channels"][0]["name"], "A")
        self.assertNotIn("api_key", agent.public_settings())
        self.assertTrue(agent.public_settings()["has_key"])

    def test_chat_claude_code(self):
        # a stand-in for `claude -p --output-format stream-json`: it records its arguments and stdin and prints the
        # events Claude Code prints (init, a tool call, its result, the answer, the result line)
        fake = self.dir / "fake_claude.py"
        fake.write_text(
            "import json, sys\n"
            "from pathlib import Path\n"
            "Path(sys.argv[1]).write_text(json.dumps({'argv': sys.argv[2:], 'stdin': sys.stdin.read()}))\n"
            "for ev in [{'type': 'system', 'subtype': 'init', 'session_id': 's1', 'mcp_servers': [{'name': 'vulturetracker', 'status': 'connected'}]},\n"
            "           {'type': 'assistant', 'message': {'content': [{'type': 'tool_use', 'id': 't1', 'name': 'mcp__vulturetracker__song_overview', 'input': {}}]}},\n"
            "           {'type': 'user', 'message': {'content': [{'type': 'tool_result', 'tool_use_id': 't1', 'content': [{'type': 'text', 'text': json.dumps({'title': 'T', 'summary': 'two channels'})}]}]}},\n"
            "           {'type': 'assistant', 'message': {'usage': {'input_tokens': 100, 'cache_read_input_tokens': 900, 'output_tokens': 12}, 'content': [{'type': 'text', 'text': 'It has two channels.'}]}},\n"
            "           {'type': 'result', 'subtype': 'success', 'is_error': False, 'session_id': 's1', 'result': 'It has two channels.'}]:\n"
            "    print(json.dumps(ev), flush=True)\n", encoding="utf-8")
        seen = self.dir / "seen.json"
        old = agent.claude_command, agent.PORT
        agent.claude_command = lambda: [sys.executable, str(fake), str(seen)]
        agent.PORT = 8765
        try:
            st = self.state()
            agent.save_settings({"provider": "claude_code", "model": "sonnet", "effort": "low"})
            chat = agent.Chat()
            chat.send(st, "how many channels?")
            for _ in range(200):
                if not chat.busy:
                    break
                time.sleep(0.05)
            self.assertEqual([m["role"] for m in chat.display], ["you", "tool", "agent"], chat.display)
            self.assertEqual((chat.display[1]["tool"], chat.display[1]["text"]), ("song_overview", "two channels"))
            got = json.loads(seen.read_text())
            self.assertEqual(got["stdin"], "how many channels?")
            argv = got["argv"]
            self.assertIn("-p", argv)
            self.assertEqual(argv[argv.index("--model") + 1], "sonnet")
            self.assertEqual(argv[argv.index("--effort") + 1], "low")
            self.assertEqual(argv[argv.index("--tools") + 1], "")            # no built-in tools: only the song's
            self.assertEqual(argv[argv.index("--allowedTools") + 1], "mcp__vulturetracker")
            self.assertEqual(argv[argv.index("--system-prompt") + 1], agent.SYSTEM)
            self.assertNotIn("--append-system-prompt", argv)
            self.assertIn("--disable-slash-commands", argv)
            self.assertEqual(argv[argv.index("--setting-sources") + 1], "user")
            settings = json.loads(argv[argv.index("--settings") + 1])
            self.assertEqual(settings, {"claudeMdExcludes": ["**"], "autoMemoryEnabled": False, "disableAllHooks": True})
            cfg = json.loads(argv[argv.index("--mcp-config") + 1])["mcpServers"]["vulturetracker"]
            self.assertEqual(cfg["args"][-2:], ["--port", "8765"])
            self.assertNotIn("--resume", argv)
            self.assertEqual(chat.session, "s1")
            chat.send(st, "and the tempo?")                                   # the next message resumes the session
            for _ in range(200):
                if not chat.busy:
                    break
                time.sleep(0.05)
            argv = json.loads(seen.read_text())["argv"]
            self.assertEqual(argv[argv.index("--resume") + 1], "s1")
            self.assertEqual(chat.snapshot()['context']['tokens'],1012)
            chat.compact(st)
            self.wait_chat(chat)
            got=json.loads(seen.read_text());argv=got['argv']
            self.assertIn('--fork-session',argv)
            self.assertEqual(json.loads(argv[argv.index('--mcp-config')+1]),{'mcpServers':{}})
            self.assertEqual(argv[argv.index('--allowedTools')+1],'')
            self.assertIsNone(chat.session)
            self.assertEqual(chat.display[-1], {"role": "status", "text": "Context compacted."})
            chat.send(st,'continue after compaction')
            self.wait_chat(chat)
            got=json.loads(seen.read_text())
            self.assertNotIn('--resume',got['argv'])
            self.assertIn('Summary of earlier conversation',got['stdin'])
        finally:
            agent.claude_command, agent.PORT = old

    def test_claude_process_stop_and_resume_controls(self):
        fake=self.dir/'slow_claude.py'
        fake.write_text('import sys,time\nsys.stdin.read()\nprint(\'{}\',flush=True)\ntime.sleep(30)\n',encoding='utf-8')
        agent.save_settings({'provider':'claude_code'})
        chat=agent.Chat()
        with mock.patch.object(agent,'claude_command',return_value=[sys.executable,str(fake)]), mock.patch.object(agent,'PORT',8765):
            chat.send(self.state(),'wait')
            for _ in range(200):
                if chat.process is not None:break
                time.sleep(.01)
            proc=chat.process
            self.assertIsNotNone(proc)
            chat.stop();self.wait_chat(chat)
            self.assertIsNotNone(proc.poll())
            self.assertIn('Stopped',chat.display[-1]['text'])

    def test_anthropic_compact_keeps_only_summary_and_no_tools(self):
        try:
            import anthropic
        except ImportError:
            self.skipTest('needs anthropic')
        from types import SimpleNamespace
        agent.save_settings({'provider':'anthropic','api_key':'fixture'})
        chat=agent.Chat();chat.provider=('anthropic','','')
        chat.history=[{'role':'user','content':'Request '*500},{'role':'assistant','content':'Earlier response '*500}]
        client=mock.MagicMock()
        client.__enter__.return_value=client
        client.messages.create.return_value=SimpleNamespace(stop_reason='end_turn',content=[SimpleNamespace(type='text',text='Keep the approved drums.')])
        with mock.patch.object(anthropic,'Anthropic',return_value=client):
            chat.compact(self.state());self.wait_chat(chat)
        self.assertEqual(len(chat.history),1)
        self.assertIn('Keep the approved drums',chat.history[0]['content'])
        self.assertNotIn('tools',client.messages.create.call_args.kwargs)

    def file(self):
        return json.loads((self.dir / "agent.json").read_text(encoding="utf-8"))

    def test_settings_key_in_file_without_keyring(self):
        pub = agent.save_settings({"provider": "anthropic", "api_key": " k1 "})
        self.assertEqual((pub["key_store"], pub["has_key"]), ("file", True))
        self.assertEqual(self.file()["api_key"], "k1")
        self.assertEqual(agent.load_settings()["api_key"], "k1")
        pub = agent.save_settings({"clear_key": True})
        self.assertFalse(pub["has_key"])
        self.assertNotIn("api_key", self.file())

    def test_settings_key_in_keyring(self):
        agent.keyring = fake = FakeKeyring()
        pub = agent.save_settings({"provider": "openai", "api_key": "k2"})
        self.assertEqual((pub["key_store"], pub["has_key"]), ("keyring", True))
        self.assertEqual(fake.store, {("VultureTracker", "openai"): "k2"})
        self.assertNotIn("api_key", self.file())
        self.assertEqual(agent.load_settings()["api_key"], "k2")   # what the chat's readers see
        agent.save_settings({"model": "m"})                        # a later save never copies it back
        self.assertNotIn("api_key", self.file())
        self.assertEqual(self.file()["model"], "m")
        # a key saved before keyring was installed moves into the store on the next load
        fake.store.clear()
        (self.dir / "agent.json").write_text(json.dumps({"provider": "openai", "api_key": "legacy"}), encoding="utf-8")
        self.assertEqual(agent.load_settings()["api_key"], "legacy")
        self.assertEqual(fake.store[("VultureTracker", "openai")], "legacy")
        self.assertNotIn("api_key", self.file())
        pub = agent.save_settings({"clear_key": True})
        self.assertEqual((pub["has_key"], fake.store), (False, {}))
        agent.save_settings({"clear_key": True})                   # nothing stored: no error
        self.assertFalse(agent.public_settings()["has_key"])

    def test_settings_keyring_failures_fall_back_to_the_file(self):
        agent.keyring = FakeKeyring(broken=True)
        pub = agent.save_settings({"provider": "anthropic", "api_key": "k3"})
        self.assertEqual((pub["key_store"], pub["has_key"], self.file()["api_key"]), ("file", True, "k3"))
        agent.keyring = FakeKeyring(dropping=True)
        pub = agent.save_settings({"api_key": "k4"})
        self.assertEqual((pub["key_store"], pub["has_key"], self.file()["api_key"]), ("file", True, "k4"))

    def test_base_url_warning(self):
        warn = "the key would travel in clear: base_url is neither localhost nor https"
        for url, expect in [("http://10.0.0.5:11434/v1", warn), ("http://localhost:11434/v1", ""),
                            ("http://[::1]:8080/v1", ""), ("https://api.example.com/v1", ""), ("", "")]:
            self.assertEqual(agent.save_settings({"base_url": url})["base_url_warning"], expect, url)

    def test_chat_local_model(self):
        st = self.state()
        port = self._fake([
            {"choices": [{"message": {"role": "assistant", "content": None, "tool_calls": [
                {"id": "c1", "type": "function", "function": {"name": "key_check", "arguments": "{\"key\": \"C major\"}"}}]}}]},
            {"choices": [{"message": {"role": "assistant", "content": "All in C major."}}]}])
        agent.save_settings({"provider": "openai", "model": "local", "base_url": f"http://127.0.0.1:{port}/v1"})
        chat = self._chat(st, "is it in C?")
        self.assertEqual([m["role"] for m in chat.display], ["you", "tool", "agent"], chat.display)
        self.assertEqual(Fake.seen[0][0], "/v1/chat/completions")
        self.assertEqual(Fake.seen[0][1]["messages"][0]["role"], "system")
        self.assertEqual(Fake.seen[1][1]["messages"][-1]["role"], "tool")
        self.assertEqual(json.loads(Fake.seen[1][1]["messages"][-1]["content"])["key"], "C major")

    def test_compatible_providers_edit_refuse_and_undo(self):
        for provider in ("gemini", "ollama", "lmstudio", "openai"):
            with self.subTest(provider=provider):
                st = self.state()
                st.song_edit([{"op": "mark", "what": "pattern", "key": "p1", "approved": True}])
                original = self.read()
                def call(n, name, args):
                    return {"choices": [{"message": {"role": "assistant", "content": None, "tool_calls": [
                        {"id": str(n), "type": "function", "function": {"name": name, "arguments": json.dumps(args)},
                         "extra_content": {"google": {"thought_signature": "opaque-signature"}}}]}}]}
                port = self._fake([
                    call(1, "write_cells", {"pattern": "p2", "cells": [{"row": 1, "channel": 2, "cell": "E-5 02 v40 ..."}]}),
                    call(2, "read_pattern", {"pattern": "p2", "from_row": 1, "to_row": 1}),
                    call(3, "write_cells", {"pattern": "p1", "cells": [{"row": 0, "channel": 1, "cell": "D-5 01 ... ..."}]}),
                    call(4, "undo", {}),
                    {"choices": [{"message": {"role": "assistant", "content": "Edited, checked protection, then undone."}}]}])
                # Keep the real HTTP serialization/tool loop; redirect only Google's fixed endpoint to our fixture.
                real_connection = agent.connection
                def local_connection(s):
                    _, model, key = real_connection(s)
                    return f"http://127.0.0.1:{port}/v1", model, key
                agent.save_settings({"provider": provider, "model": "test-model", "api_key": "fixture-key"})
                with mock.patch.object(agent, "connection", side_effect=local_connection):
                    chat = self._chat(st, "Edit one note, check it, refuse approved notes, and undo")
                self.assertFalse(chat.busy)
                self.assertEqual(chat.display[-1]["text"], "Edited, checked protection, then undone.", chat.display)
                self.assertEqual(len(Fake.seen), 5)
                self.assertEqual(Fake.headers_seen[0]["Authorization"], "Bearer fixture-key")
                result = lambda i: json.loads(Fake.seen[i][1]["messages"][-1]["content"])
                self.assertTrue(result(1)["ok"])
                self.assertIn("E-5 02 v40 ...", result(2)["rows"][0])
                self.assertIn("approved", result(3)["error"])
                self.assertEqual(self.read(), original)
                self.assertEqual(Fake.seen[1][1]["messages"][-2]["tool_calls"][0]["extra_content"],
                                 {"google": {"thought_signature": "opaque-signature"}})
                self.assertTrue(any(m.get("error") for m in chat.display if m["role"] == "tool"))

    def test_model_discovery_does_not_save_or_reuse_another_providers_key(self):
        agent.save_settings({"provider": "gemini", "api_key": "private-key"})
        before = self.file()
        port = self._fake([{"data": [{"id": "local-b"}, {"id": "local-a"}, {"id": "local-a"}]}])
        out = agent.discover_models({"provider": "ollama", "base_url": f"http://127.0.0.1:{port}/v1"})
        self.assertEqual(out, {"models": ["local-a", "local-b"]})
        self.assertEqual(Fake.seen, [("/v1/models", None)])
        self.assertNotIn("Authorization", Fake.headers_seen[0])
        self.assertEqual(self.file(), before)

    def test_provider_switch_does_not_carry_file_key_or_endpoint(self):
        agent.save_settings({"provider": "gemini", "api_key": "private-key", "base_url": "https://old.example/v1"})
        agent.save_settings({"provider": "ollama"})
        self.assertFalse(agent.public_settings()["has_key"])
        self.assertEqual(agent.connection(agent.load_settings()), ("http://localhost:11434/v1", "", ""))
        agent.save_settings({"provider": "gemini"})
        self.assertEqual(agent.load_settings()["api_key"], "private-key")
        agent.keyring = FakeKeyring()
        agent.save_settings({"provider": "gemini", "api_key": "stored-key"})
        agent.save_settings({"provider": "lmstudio"})
        self.assertFalse(agent.public_settings()["has_key"])
        agent.save_settings({"provider": "gemini"})
        self.assertEqual(agent.load_settings()["api_key"], "stored-key")

    def test_gemini_rack_maps_and_invalid_arguments(self):
        st = self.state()
        original = self.read()
        def answer(name, args):
            return {"choices": [{"message": {"role": "assistant", "tool_calls": [
                {"id": name, "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}]}}]}
        replies = [answer("set_plugins", {"plugins": json.dumps({"1": {"effect": "echo"}}),
                                          "channel_plugins": json.dumps({"1": 1})}),
                   answer("undo", []),  # malformed arguments must not accidentally undo the edit
                   answer("song_overview", {}), answer("undo", {}),
                   {"choices": [{"message": {"role": "assistant", "content": "done"}}]}]
        agent.save_settings({"provider": "gemini", "api_key": "fixture"})
        with mock.patch.object(agent, "compatible_request", side_effect=replies) as request:
            chat = self._chat(st, "change the rack then undo")
        self.assertEqual(chat.display[-1]["text"], "done", chat.display)
        self.assertEqual(self.read(), original)
        results = [json.loads(m["content"]) for m in chat.history if m["role"] == "tool"]
        self.assertTrue(results[0]["ok"])
        self.assertIn("nothing changed", results[1]["error"])
        self.assertEqual(results[2]["channels"][0]["effects"], ["echo"])
        self.assertEqual({t["function"]["name"] for t in request.call_args.args[2]["tools"]},
                         {"find_tools", "call_tool", "read_tool_result"})
        tools = {t["function"]["name"]: t["function"] for t in agent.compatible_tools("gemini")}
        self.assertNotIn("parameters", tools["song_overview"])
        self.assertEqual(tools["set_module"]["parameters"]["properties"]["value"]["anyOf"],
                         [{"type": "string"}, {"type": "integer"}])
        self.assertEqual(agent.TOOLS["set_plugins"][1]["properties"]["plugins"], {"type": "object"})

    def test_gemini_defaults_and_actionable_errors(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(ValueError, "API key"):
                agent.connection({"provider": "gemini"})
        s = {"provider": "gemini", "api_key": "secret", "base_url": "http://unrelated.example/v1"}
        self.assertEqual(agent.connection(s), ("https://generativelanguage.googleapis.com/v1beta/openai", "gemini-3.8-flash", "secret"))
        for code, text in [(429, "quota"), (401, "API key"), (400, "tool-calling")]:
            with mock.patch.object(agent.urllib.request, "urlopen", side_effect=agent.urllib.error.HTTPError(
                    "https://example.com", code, "bad", {}, io.BytesIO(b'secret'))):
                with self.assertRaisesRegex(RuntimeError, text) as ctx:
                    agent.compatible_request(s, "/chat/completions", {})
                self.assertNotIn("secret", str(ctx.exception))


class ContextTests(unittest.TestCase):
    def test_directory_and_exact_schemas_cost_less_than_full_catalog(self):
        compact = agent_context.tool_list()
        self.assertLess(len(json.dumps(compact)), len(json.dumps(agent.tool_list())) // 5)
        self.assertEqual({t['name'] for t in compact}, {'find_tools', 'call_tool', 'read_tool_result'})
        context = agent_context.ToolContext()
        directory = context.call(None, 'find_tools', {'query': 'pattern'})
        self.assertIn('read_pattern', [t['name'] for t in directory['tools']])
        schemas = context.call(None, 'find_tools', {'names': ['read_pattern', 'write_cells']})
        self.assertEqual(schemas['tools'], [t for t in agent.tool_list() if t['name'] in ('read_pattern', 'write_cells')])
        for name in agent.TOOLS:
            self.assertIn(name, compact[0]['description'])
        with mock.patch.object(agent, 'run') as run:
            for args in ({'names': ['unknown']}, {'names': ['check'] * 5}, {'query': []}):
                self.assertIn('error', context.call(None, 'find_tools', args))
            run.assert_not_called()

    def test_wrapped_edits_use_original_guards_and_invalid_args_do_not_execute(self):
        context = agent_context.ToolContext()
        with mock.patch.object(agent, 'run', return_value={'error': 'approved pattern'}) as run:
            result = context.call(None, 'call_tool', {'name': 'write_cells', 'arguments_json': '{"pattern":"intro","cells":[]}'})
            self.assertEqual(result, {'error': 'approved pattern'})
            run.assert_called_once_with(None, 'write_cells', {'pattern': 'intro', 'cells': []})
            run.reset_mock()
            for args in ({'name': 'undo', 'arguments_json': '[]'}, {'name': 'undo', 'arguments_json': '{'},
                         {'name': 'call_tool', 'arguments_json': '{}'}, {'name': 'undo', 'arguments_json': {}}, []):
                self.assertIn('error', context.call(None, 'call_tool', args))
            run.assert_not_called()

    def test_paged_result_is_lossless_and_reading_it_never_repeats_an_edit(self):
        context = agent_context.ToolContext()
        original = {'ok': True, 'summary': 'edited sample', 'data': ['C-5 é' * 6000]}
        with mock.patch.object(agent, 'run', return_value=original) as run:
            first = context.call(None, 'call_tool', {'name': 'edit_sample', 'arguments_json': '{"number":1}'})
            result, page = '', first
            while True:
                self.assertLessEqual(len(page['content']), agent_context.PAGE_CHARS)
                result += page['content']
                if page['next_offset'] is None:
                    break
                page = context.call(None, 'read_tool_result', {'result_id': first['result_id'], 'offset': page['next_offset']})
            self.assertEqual(json.loads(result), original)
            run.assert_called_once()
            for args in ({'offset': -1}, {'offset': True}, {'limit': 0}, {'limit': 6001}):
                self.assertIn('error', context.call(None, 'read_tool_result', {'result_id': first['result_id'], **args}))
            context.clear()
            self.assertIn('expired', context.call(None, 'read_tool_result', {'result_id': first['result_id']})['error'])

    def test_old_outputs_shrink_and_keep_ids_errors_and_exact_snapshot(self):
        context = agent_context.ToolContext()
        raw = agent_context.dumps({'error': 'refused edit', 'usage': ['C-5'] * 400})
        history = [{'role': 'user', 'content': 'Keep the drums.'},
                   {'role': 'assistant', 'tool_calls': [{'id': 'one'}]},
                   {'role': 'tool', 'tool_call_id': 'one', 'content': raw}]
        recent = [{'role': 'tool', 'tool_call_id': str(i), 'content': raw} for i in range(4)]
        history.extend(recent)
        context.trim_history(history)
        self.assertEqual(history[0]['content'], 'Keep the drums.')
        self.assertEqual(history[2]['tool_call_id'], 'one')
        brief = json.loads(history[2]['content'])
        self.assertEqual(brief['error'], 'refused edit')
        self.assertEqual(context.page(brief['result_id'])['content'], raw)
        self.assertTrue(all(m['content'] == raw for m in recent))
        self.assertLess(len(history[2]['content']), len(raw) // 3)
        blocks = [{'type': 'tool_result', 'tool_use_id': str(i), 'content': raw, 'is_error': True} for i in range(6)]
        history = [{'role': 'user', 'content': blocks}]
        context.trim_history(history)
        self.assertTrue(blocks[0]['is_error'])
        self.assertEqual(blocks[0]['tool_use_id'], '0')
        self.assertIn('result_id', json.loads(blocks[0]['content']))

    def test_paged_history_keeps_original_reference_and_eviction_is_explicit(self):
        context = agent_context.ToolContext()
        first = context.pack({'data': 'z' * 16000})
        second = context.page(first['result_id'], first['next_offset'])
        history = [{'role': 'tool', 'content': agent_context.dumps(second)}]
        history += [{'role': 'tool', 'content': '{}'} for _ in range(4)]
        context.trim_history(history)
        self.assertEqual(json.loads(history[0]['content'])['result_id'], first['result_id'])
        for i in range(agent_context.KEEP_RESULTS):
            context.remember(str(i))
        self.assertLessEqual(len(context.results), agent_context.KEEP_RESULTS)
        self.assertIn('expired', context.call(None, 'read_tool_result', {'result_id': first['result_id']})['error'])

    def test_internal_mcp_advertises_only_directory_and_keeps_run_guard(self):
        with mock.patch.dict('os.environ', {'VT_AGENT_RUN_ID': 'run-fixture'}), mock.patch.object(mcp, '_http', return_value={'ok': True}) as http:
            listed = mcp.handle({'id': 1, 'method': 'tools/list'}, 8765)['result']['tools']
            self.assertEqual({t['name'] for t in listed}, {'find_tools', 'call_tool', 'read_tool_result'})
            args = {'name': 'check', 'arguments_json': '{}'}
            out = mcp.handle({'id': 2, 'method': 'tools/call', 'params': {'name': 'call_tool', 'arguments': args}}, 8765)
            self.assertFalse(out['result']['isError'])
            self.assertEqual(http.call_args.args[2], {'name': 'call_tool', 'args': args, 'run_id': 'run-fixture'})



if __name__ == "__main__":
    unittest.main()
