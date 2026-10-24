"""The live engine (vulturetracker/web: libopenmpt compiled to WebAssembly, the page's AudioWorklet) against the vendored
DLL the renders use: same version, same samples, a channel muted through the interactive interface equals the channel
disabled in the header, seeking, and a note preview. Runs tests/engine_check.js under node; skipped without node."""
import base64
import copy
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from vulturetracker import api, measure
from vulturetracker.openmpt import LoadedModule, library_version
from vulturetracker.wavload import write_wav

from tests.test_gui import RATE, SONG, sine

ROOT = Path(__file__).resolve().parent.parent
NODE = shutil.which("node")


@unittest.skipIf(NODE is None, 'node not installed')
class TestNativeTempoClock(unittest.TestCase):
    def test_rational_tempo_boundaries_inverse_and_speed(self):
        from fractions import Fraction
        changes = [(Fraction(0), 137), (Fraction(4), 83), (Fraction(19, 2), 251), (Fraction(101), 32)]
        prefixes = [Fraction(0)]
        for (at, bpm), (end, _) in zip(changes, changes[1:]):
            prefixes.append(prefixes[-1] + (end - at) * 60 / bpm)
        cases = []
        for at in [Fraction(0), Fraction(4) - Fraction(1, 13), Fraction(4), Fraction(4) + Fraction(1, 13),
                   Fraction(19, 2), Fraction(101), Fraction(13287, 13)]:
            index = max(i for i, (start, _) in enumerate(changes) if start <= at)
            seconds = prefixes[index] + (at - changes[index][0]) * 60 / changes[index][1]
            for rate in (8000, 44100, 48000, 96000):
                for q in (32768, 65536, 87381, 262144):
                    exact = seconds * rate * q / 65536
                    frame = (2 * exact.numerator + exact.denominator) // (2 * exact.denominator)
                    at_frame_seconds = Fraction(frame * 65536, rate * q)
                    inverse_index = max(i for i, start in enumerate(prefixes) if start <= at_frame_seconds)
                    inverse = changes[inverse_index][0] + (at_frame_seconds - prefixes[inverse_index]) * changes[inverse_index][1] / 60
                    cases.append(dict(at=[at.numerator, at.denominator], rate=rate, q=q, frame=frame,
                                      inverse=[str(inverse.numerator), str(inverse.denominator)]))
        script = """
const assert=require('assert/strict'), fs=require('fs');
const {nativeScoreClock}=require('./vulturetracker/web/engine-core.js');
const {tempos,cases}=JSON.parse(fs.readFileSync(0,'utf8'));
const clock=nativeScoreClock({tempo:137,tempos});
for(const c of cases) {
  assert.equal(clock.frameAt(c.at,c.rate,c.q),c.frame);
  assert.deepEqual(clock.timeAtFrame(c.frame,c.rate,c.q).map(String),c.inverse);
  assert.equal(clock.frameAt(clock.timeAtFrame(c.frame,c.rate,c.q),c.rate,c.q),c.frame);
}
tempos[1].bpm=255; // A prepared clock is independent of later caller edits.
assert.equal(clock.frameAt([4,1],48000),84088);
for(const tempos of [null,[],[{at:[1,1],bpm:120}], [{at:[0,1],bpm:120},{at:[0,1],bpm:60}],
                    [{at:[0,1],bpm:31}], [{at:[0,0],bpm:120}]])
  assert.throws(()=>nativeScoreClock({tempo:120,tempos}));
assert.equal(nativeScoreClock({tempo:120}).frameAt([1,3],48000),8000);
"""
        result = subprocess.run([NODE, '-e', script], cwd=ROOT, text=True, capture_output=True,
                                input=json.dumps(dict(tempos=[dict(at=[a.numerator, a.denominator], bpm=b) for a, b in changes], cases=cases)))
        self.assertEqual(result.returncode, 0, result.stderr)


class TestNativePitchScheduler(unittest.TestCase):
    def plan(self):
        def event(kind, frame, identity, **fields):
            return dict(type=kind, frame=frame, at=[frame, 4000], id=identity, **fields)
        note = dict(ch=0, pitch=60, source_instrument=1, volume=None)
        return dict(version=1, sample_rate=8000, tempo=120, row_step=[1, 100],
                    duration={'frames': 80, 'quarters': [1, 50]},
                    occurrences=[{'at': [0, 1], 'duration': [1, 50]}], events=[
                        event('note_on', 0, 'a', **note), event('pitch', 0, 'a', semitones=1),
                        event('note_off', 10, 'a', **note), event('note_on', 10, 'b', **note),
                        event('pitch', 10, 'a', semitones=2), event('pitch', 10, 'b', semitones=4),
                        event('pitch', 10, 'a', semitones=3), event('pitch', 20, 'a', semitones=-2),
                        event('pitch', 30, 'a', semitones=0), event('note_off', 40, 'b', **note)])

    def module(self, plan=None, stale=False):
        from types import SimpleNamespace
        module = LoadedModule.__new__(LoadedModule)
        module._mod = module._ext = None
        module._set_plan(plan or self.plan(), 8000)
        calls, serial = [], [100]
        def batch(ext, rate, offs, off_ids, notes, attacks, ids):
            calls.append(('batch', module._native_frame, list(off_ids[:offs]), notes))
            for index in range(notes):
                serial[0] += 1
                ids[index] = serial[0]
            return 1
        def pitch(ext, identity, semitones):
            calls.append(('pitch', module._native_frame, identity, semitones))
            return int(not (stale and identity == 101 and module._native_frame == 20))
        module._parent = SimpleNamespace(dispatch=batch)
        module._pitch = SimpleNamespace(set=pitch)
        module._tail = SimpleNamespace(begin=lambda ext: 1)
        return module, calls

    def test_released_handles_live_through_last_control_and_stale_never_retargets(self):
        for stale in (False, True):
            with self.subTest(stale=stale):
                module, calls = self.module(stale=stale)
                for frame in (0, 10, 20, 30, 40):
                    module._native_frame = frame
                    module._native_boundary()
                    if frame == 10:
                        self.assertEqual(module._handles, {'a': 101, 'b': 102})
                    if frame == 30:
                        self.assertEqual(module._handles, {'b': 102})
                self.assertEqual(module._handles, {})
                expected = [('batch', 0, [], 1), ('pitch', 0, 101, 1),
                            ('batch', 10, [101], 1), ('pitch', 10, 101, 2),
                            ('pitch', 10, 102, 4), ('pitch', 10, 101, 3),
                            ('batch', 20, [], 0), ('pitch', 20, 101, -2), ('batch', 30, [], 0)]
                if not stale:
                    expected.append(('pitch', 30, 101, 0))
                expected.append(('batch', 40, [102], 0))
                self.assertEqual(calls, expected)

    def test_range_boundary_batches_release_before_pitch_and_excludes_new_attack(self):
        module, calls = self.module()
        module._native_boundary()
        module._native_stop = module._native_frame = 10
        module._native_boundary()
        self.assertEqual(calls[2:], [('batch', 10, [101], 0), ('pitch', 10, 101, 2), ('pitch', 10, 101, 3)])
        self.assertTrue(module._in_tail)
        self.assertEqual(module._event_index, len(module._events))
        module._native_frame = 30
        module._native_boundary()
        self.assertEqual(len(calls), 5)

    def test_pitch_plan_validation_and_frozen_inputs(self):
        valid = self.plan()
        module, _ = self.module(valid)
        valid['events'][1]['at'][0] = 99
        self.assertEqual(module._events[1]['at'], [0, 4000])
        for value in (float('nan'), float('inf'), -float('inf'), -12.01, 12.01, True, None, '1', 10**1000):
            bad = self.plan()
            bad['events'][1]['semitones'] = value
            with self.subTest(value=str(value)[:30]), self.assertRaisesRegex(ValueError, 'pitch control'):
                self.module(bad)
        for change in ('unknown', 'before_attack', 'rank', 'decreasing', 'missing_release'):
            bad = self.plan()
            if change == 'unknown':
                bad['events'][1]['id'] = 'unknown'
            elif change == 'before_attack':
                bad['events'][0], bad['events'][1] = bad['events'][1], bad['events'][0]
            elif change == 'rank':
                bad['events'][3], bad['events'][4] = bad['events'][4], bad['events'][3]
            elif change == 'decreasing':
                bad['events'][7]['frame'] = 9
            else:
                bad['events'].pop()
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.module(bad)
        for value in (-12, 0, 12):
            good = self.plan()
            good['events'][1]['semitones'] = value
            self.assertTrue(self.module(good)[0]._has_pitch)

    def test_held_batches_keep_flags_stride_and_identity_controls(self):
        from types import SimpleNamespace
        plan = self.plan()
        plan['events'][0]['hold'] = True
        module, calls = self.module(plan)
        batches = []
        def dispatch(ext, rate, off_count, offs, count, groups, flags, capacity, identities):
            batches.append((module._native_frame, list(offs[:off_count]), list(flags[:count]), capacity))
            for index in range(count):
                identities[index * 3] = 101 + module._native_frame
            return 1
        module._held = SimpleNamespace(dispatch=dispatch)
        for frame in (0, 10, 20, 30, 40):
            module._native_frame = frame
            module._native_boundary()
        self.assertEqual(batches, [(0, [], [1], 3), (10, [101], [0], 3),
                                   (20, [], [], 0), (30, [], [], 0), (40, [111], [], 0)])
        self.assertIn(('pitch', 10, 101, 3), calls)
        self.assertIn(('pitch', 10, 111, 4), calls)
        self.assertEqual(module._handles, {})
        for change in ('number', 'release', 'inherited', 'layers', 'pulse'):
            bad = self.plan()
            first = bad['events'][0]
            first['hold'] = True
            if change == 'number':
                first['hold'] = 1
            elif change == 'release':
                bad['events'][2]['hold'] = True
            elif change == 'inherited':
                first['source_instrument'] = 0
            elif change == 'layers':
                first['layers'] = [dict(pitch=60, velocity=95)]
            else:
                first['source_id'] = 'repeating-head'
            with self.subTest(change=change), self.assertRaisesRegex(ValueError, 'hold'):
                self.module(bad)

    @unittest.skipUnless(NODE, 'needs node')
    def test_javascript_hold_guards_without_held_runtime(self):
        result = subprocess.run([NODE, str(ROOT / 'tests/engine_check.js'), '--held-guards'],
                                input=json.dumps(self.plan()), text=True, capture_output=True, cwd=ROOT)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue(json.loads(result.stdout)['held_guards'])

    def context_plan(self):
        plan = self.plan()
        plan['events'][0].update(context=1, context_open=True, context_close=False)
        plan['events'][3].update(context=1, context_open=False, context_close=True)
        plan['events'].insert(4, dict(plan['events'][3], id='c', context=2, context_open=True, pitch=67))
        plan['events'].insert(-1, dict(plan['events'][2], id='c', frame=30, at=[30, 4000]))
        plan['events'].sort(key=lambda e: (e['frame'], {'note_off': 0, 'note_on': 1, 'pitch': 2}[e['type']]))
        return plan

    def test_context_dispatch_closes_after_ordered_attacks_and_guards_lifecycle(self):
        from types import SimpleNamespace
        plan = self.context_plan()
        module, calls = self.module(plan)
        batches, serial = [], [100]
        def dispatch(ext, rate, off_count, offs, close_count, closes, count, keys, attacks, capacity, ids):
            batches.append((module._native_frame, list(offs[:off_count]), list(closes[:close_count]),
                            list(keys[:count]), [attacks[i * 8 + 7] for i in range(count)], capacity))
            for index in range(count):
                serial[0] += 1
                ids[index * 3] = serial[0]
            return 1
        module._contexts = SimpleNamespace(dispatch=dispatch)
        for frame in (0, 10, 20, 30, 40):
            module._native_frame = frame
            module._native_boundary()
        self.assertEqual(batches[:2], [(0, [], [], [1], [1], 3), (10, [101], [1, 2], [1, 2], [2, 1], 6)])
        self.assertEqual(batches[-2:], [(30, [103], [], [], [], 0), (40, [102], [], [], [], 0)])
        self.assertIn(('pitch', 10, 101, 3), calls)
        self.assertIn(('pitch', 10, 102, 4), calls)
        self.assertEqual(module._handles, {})
        for change in ('duplicate', 'closed', 'reopen', 'source', 'missing_close', 'orphan_flag', 'boolean_key', 'hold'):
            bad = self.context_plan()
            attacks = [e for e in bad['events'] if e['type'] == 'note_on']
            if change == 'duplicate':
                attacks[2].update(context=1, context_open=False)
            elif change == 'closed':
                attacks[0]['context_close'] = True
            elif change == 'reopen':
                attacks[1]['context_open'] = True
            elif change == 'source':
                attacks[1]['source_instrument'] = 2
            elif change == 'missing_close':
                attacks[1]['context_close'] = False
            elif change == 'orphan_flag':
                del attacks[0]['context']
            elif change == 'boolean_key':
                attacks[0]['context'] = True
            else:
                attacks[0]['hold'] = True
            with self.subTest(change=change), self.assertRaisesRegex(ValueError, 'context|head'):
                self.module(bad)

    @unittest.skipUnless(NODE, 'needs node')
    def test_javascript_context_guards_without_context_runtime(self):
        result = subprocess.run([NODE, str(ROOT / 'tests/engine_check.js'), '--context-guards'],
                                input=json.dumps(self.context_plan()), text=True, capture_output=True, cwd=ROOT)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue(json.loads(result.stdout)['context_guards'])

class TestNativeVelocityScheduler(TestNativePitchScheduler):
    def test_dynamic_gain_validation_frozen_values_and_retired_tail(self):
        from types import SimpleNamespace
        for value in ([],None,[float('nan')],[float('inf')],[-.1],[1.1],[True],['.5'],[.5,.6]):
            plan=self.plan();plan['events'].append(dict(type='gain',id='a',frame=50,at=[1,80],gains=value))
            with self.subTest(value=value),self.assertRaisesRegex(ValueError,'gain control'):self.module(plan)
        plan=self.plan()
        plan['events'].extend([dict(type='gain',id='a',frame=f,at=[f,4000],gains=[.5]) for f in (50,60)])
        module,calls=self.module(plan)
        seen=[]
        module._gain=SimpleNamespace(set=lambda ext,handle,gain:seen.append((handle,gain)) or 0)
        plan['events'][-2]['gains'][0]=.1
        for frame in (0,10,20,30,40,50,60):module._native_frame=frame;module._native_boundary()
        self.assertEqual(seen,[(101,.5)])  # Expired identity is never redirected or retried.
        self.assertEqual(module._handles,{})

    # Reuse the existing boundary fixture; inherited pitch cases also check
    # that an absent velocity leaves its established ordering unchanged.
    def test_velocity_validation_order_and_frozen_source(self):
        from types import SimpleNamespace
        for value in (-1, 128, True, False, 1.5, '64', float('nan'), float('inf')):
            plan = self.plan()
            plan['events'][0]['velocity'] = value
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, 'velocity'):
                self.module(plan)
        for value in (None, 0, 64, 127):
            plan = self.plan()
            plan['events'][0]['velocity'] = value
            module, calls = self.module(plan)
            self.assertEqual(module._has_gain, value is not None)
            module._gain = SimpleNamespace(set=lambda ext, handle, gain: calls.append(('gain', handle, gain)) or 1)
            plan['events'][0]['velocity'] = 12
            module._native_boundary()
            expected = [('batch', 0, [], 1)]
            if value is not None:
                expected.append(('gain', 101, value / 127))
            expected.append(('pitch', 0, 101, 1))
            self.assertEqual(calls, expected)
            self.assertEqual(module._batch_notes[3], -1)  # Nullable volume remains inherited.
        plan = self.plan()
        plan['events'][0]['velocity'] = 0
        plan['events'][3].update(frame=0, at=[0, 1], ch=1, velocity=127)
        plan['events'].sort(key=lambda e: (e['frame'], {'note_off': 0, 'note_on': 1, 'pitch': 2}[e['type']]))
        module, calls = self.module(plan)
        module._gain = SimpleNamespace(set=lambda ext, handle, gain: calls.append(('gain', handle, gain)) or 1)
        module._native_boundary()
        self.assertEqual(calls, [('batch', 0, [], 2), ('gain', 101, 0), ('gain', 102, 1), ('pitch', 0, 101, 1)])

    def test_velocity_refusal_is_fatal_zero_handle_is_ignored_and_range_excludes_gain(self):
        from types import SimpleNamespace
        from vulturetracker.openmpt import OpenMPTError
        plan = self.plan()
        plan['events'][0]['velocity'] = 0
        plan['events'][3]['velocity'] = 127
        module, calls = self.module(plan)
        module._gain = SimpleNamespace(set=lambda *args: 0)
        closed = []
        module.close = lambda: closed.append(True)
        with self.assertRaisesRegex(OpenMPTError, 'gain'):
            module._native_boundary()
        self.assertEqual(closed, [True])
        module, calls = self.module(plan)
        module._parent.dispatch = lambda ext, rate, offs, off_ids, notes, attacks, ids: 1
        module._gain = SimpleNamespace(set=lambda *args: self.fail('ignored keymap handle received gain'))
        module._native_boundary()
        self.assertFalse(calls)
        module, calls = self.module(plan)
        gains = []
        module._gain = SimpleNamespace(set=lambda ext, handle, gain: gains.append((handle, gain)) or 1)
        module._native_boundary()
        module._native_stop = module._native_frame = 10
        module._native_boundary()
        self.assertEqual(gains, [(101, 0)])

    def test_gain_interface_required_only_for_explicit_velocity(self):
        from types import SimpleNamespace
        from unittest.mock import Mock, patch
        from vulturetracker import openmpt
        create = Mock(return_value=7)
        create.argtypes = []
        library = SimpleNamespace(
            openmpt_module_create_from_memory2=create,
            openmpt_module_ext_create_from_memory=Mock(return_value=7),
            openmpt_module_ext_get_module=Mock(return_value=8),
            openmpt_module_ext_destroy=Mock(),
            openmpt_module_ext_get_interface=Mock(),
            openmpt_module_get_num_channels=Mock(return_value=1))
        for present, velocity in ((False, None), (True, None), (True, 0), (True, 127)):
            plan = self.plan()
            if present:
                plan['events'][0]['velocity'] = velocity
            interfaces = []
            def interface(module, name, structure):
                interfaces.append(name)
                if name == b'vt_gain':
                    raise openmpt.OpenMPTError('missing vt_gain')
                return SimpleNamespace(configure=lambda *args: 1)
            with self.subTest(present=present, velocity=velocity), patch.object(openmpt, '_lib', library), \
                    patch.object(LoadedModule, '_interface', interface), patch.object(LoadedModule, 'timed_at'):
                if velocity is None:
                    with LoadedModule(b'test', 8000, 1, plan=plan):
                        self.assertNotIn(b'vt_gain', interfaces)
                else:
                    with self.assertRaisesRegex(openmpt.OpenMPTError, 'vt_gain'):
                        LoadedModule(b'test', 8000, 1, plan=plan)

    @unittest.skipUnless(NODE, 'needs node')
    def test_javascript_velocity_guards_without_gain_runtime(self):
        result = subprocess.run([NODE, str(ROOT / 'tests' / 'engine_check.js'), '--velocity-guards'],
                                input=json.dumps(self.plan()), text=True, capture_output=True, cwd=ROOT)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue(json.loads(result.stdout)['velocity_guards'])


class TestNativeGroupScheduler(TestNativePitchScheduler):
    def group_plan(self):
        plan = self.plan()
        plan['events'][0]['layers'] = [
            {'pitch': 52, 'velocity': 47}, {'pitch': 52, 'velocity': 31}, {'pitch': 64, 'velocity': 95}]
        return plan

    def group_module(self, plan=None):
        from types import SimpleNamespace
        module, calls = self.module(plan or self.group_plan())
        def groups(ext, rate, offs, off_ids, count, data, capacity, ids):
            values = [list(data[i * 7:(i + 1) * 7]) for i in range(count)]
            calls.append(('groups', values, capacity))
            serial = 201
            for i, group in enumerate(values):
                for j in range(3):
                    ids[i * 3 + j] = serial if j < group[3] else 0
                    if j < group[3]:
                        serial += 1
            return 1
        module._groups = SimpleNamespace(dispatch=groups)
        module._gain = SimpleNamespace(set=lambda ext, identity, gain: calls.append(('gain', identity, gain)) or 1)
        return module, calls

    def test_layers_validation_frozen_source_and_mixed_batch_order(self):
        for layers in (None, {}, [], [None], [{'pitch': 60}], [{'pitch': 120, 'velocity': 95}],
                       [{'pitch': 60, 'velocity': True}], [{'pitch': 60, 'velocity': float('nan')}],
                       [{'pitch': 60, 'velocity': 95, 'extra': 1}], [{'pitch': 60, 'velocity': 95}] * 4):
            plan = self.group_plan()
            plan['events'][0]['layers'] = layers
            with self.subTest(layers=layers), self.assertRaisesRegex(ValueError, 'layers'):
                self.group_module(plan)
        plan = self.group_plan()
        plan['events'][3].update(frame=0, at=[0, 1], ch=1, velocity=127)
        plan['events'].sort(key=lambda e: (e['frame'], {'note_off': 0, 'note_on': 1, 'pitch': 2}[e['type']]))
        module, calls = self.group_module(plan)
        plan['events'][0]['layers'][0].update(pitch=10, velocity=0)
        module._native_boundary()
        self.assertEqual(calls, [('groups', [[0, 1, -1, 3, 52, 52, 64], [1, 1, -1, 1, 60, 0, 0]], 6),
                                 ('gain', 201, 47 / 127), ('gain', 202, 31 / 127), ('gain', 203, 95 / 127),
                                 ('gain', 204, 1), ('pitch', 0, 201, 1), ('pitch', 0, 202, 1), ('pitch', 0, 203, 1)])
        self.assertEqual(module._handles, {'a': (201, 202, 203), 'b': 204})

    def test_layer_release_tail_controls_retire_independently(self):
        module, calls = self.group_module()
        def pitch(ext, handle, value):
            calls.append(('pitch', module._native_frame, handle, value))
            return int(not (handle == 202 and module._native_frame == 20))
        module._pitch.set = pitch
        for frame in (0, 10, 20, 30, 40):
            module._native_frame = frame
            module._native_boundary()
            if frame == 10:
                self.assertIn(('batch', 10, [201, 202, 203], 1), calls)
            if frame == 20:
                self.assertEqual(module._handles['a'], (201, 0, 203))
        self.assertIn(('pitch', 30, 201, 0), calls)
        self.assertIn(('pitch', 30, 203, 0), calls)
        self.assertNotIn(('pitch', 30, 202, 0), calls)
        self.assertEqual(module._handles, {})

    def test_release_capacity_counts_layers_and_rejects_nonattack_layers(self):
        for count in (85, 86):
            plan = self.group_plan()
            on, off = copy.deepcopy(plan['events'][0]), copy.deepcopy(plan['events'][2])
            plan['duration']['frames'] = 200
            plan['events'] = [dict(on, id=str(i), frame=i) for i in range(count)]
            plan['events'] += [dict(off, id=str(i), frame=150) for i in range(count)]
            if count == 86:
                with self.assertRaisesRegex(ValueError, 'simultaneous.*releases'):
                    self.group_module(plan)
            else:
                self.group_module(plan)
        plan = self.group_plan()
        plan['events'][2]['layers'] = copy.deepcopy(plan['events'][0]['layers'])
        with self.assertRaisesRegex(ValueError, 'only to attacks'):
            self.group_module(plan)

    def test_group_failure_stops_before_pcm_zero_group_and_exclusive_endpoint(self):
        from vulturetracker.openmpt import OpenMPTError
        for kind in ('batch', 'negative batch', 'gain'):
            module, calls = self.group_module()
            closed = []
            module.close = lambda: closed.append(True)
            if 'batch' in kind:
                module._groups.dispatch = lambda *args: -4 if kind == 'negative batch' else 0
            else:
                module._gain.set = lambda ext, handle, gain: int(handle != 202)
            with self.subTest(kind=kind), self.assertRaisesRegex(OpenMPTError, 'batch|gain'):
                module._native_boundary()
            self.assertEqual(closed, [True])
            self.assertFalse(any(c[0] == 'pitch' for c in calls))
        module, calls = self.group_module()
        module._groups.dispatch = lambda *args: 1
        module._native_boundary()
        self.assertEqual(module._handles['a'], (0, 0, 0))
        self.assertFalse(calls)
        plan = self.group_plan()
        plan['events'][3]['layers'] = copy.deepcopy(plan['events'][0]['layers'])
        module, calls = self.group_module(plan)
        module._native_boundary()
        module._native_stop = module._native_frame = 10
        module._native_boundary()
        self.assertEqual(sum(c[0] == 'groups' for c in calls), 1)
        self.assertIn(('batch', 10, [201, 202, 203], 0), calls)

    def test_optional_group_interface_and_zero_frame_stereo_initialization(self):
        from types import SimpleNamespace
        from unittest.mock import Mock, patch
        from vulturetracker import openmpt
        create = Mock(return_value=7)
        create.argtypes = []
        library = SimpleNamespace(openmpt_module_create_from_memory2=create,
            openmpt_module_ext_create_from_memory=create, openmpt_module_ext_get_module=Mock(return_value=8),
            openmpt_module_ext_destroy=Mock(), openmpt_module_ext_get_interface=Mock(),
            openmpt_module_get_num_channels=Mock(return_value=2),
            openmpt_module_read_interleaved_stereo=Mock(return_value=0))
        for present, available, prime_status in ((False, False, 1), (True, False, 1), (True, True, 1),
                                                (True, True, 0), (True, True, -4)):
            names = []
            def prime(*args):
                self.assertEqual(library.openmpt_module_read_interleaved_stereo.call_count, 1)
                self.assertEqual((args[0], args[1], args[2], args[4], args[6]), (7, 8000, 0, 0, 0))
                return prime_status
            dispatch = Mock(side_effect=prime)
            def interface(module, name, structure):
                names.append(name)
                if name == b'vt_parent_groups' and not available:
                    raise openmpt.OpenMPTError('missing vt_parent_groups')
                return SimpleNamespace(configure=lambda *args: 1, dispatch=dispatch)
            library.openmpt_module_read_interleaved_stereo.reset_mock()
            with patch.object(openmpt, '_lib', library), patch.object(LoadedModule, '_interface', interface), \
                    patch.object(LoadedModule, 'timed_at'):
                plan = self.group_plan() if present else self.plan()
                if present and not available:
                    with self.assertRaisesRegex(openmpt.OpenMPTError, 'vt_parent_groups'):
                        LoadedModule(b'test', 8000, 1, plan=plan)
                elif present and prime_status != 1:
                    with self.assertRaisesRegex(openmpt.OpenMPTError, 'group initialization'):
                        LoadedModule(b'test', 8000, 1, plan=plan)
                else:
                    with LoadedModule(b'test', 8000, 1, plan=plan):
                        self.assertEqual(b'vt_parent_groups' in names, present)
                        self.assertEqual(library.openmpt_module_read_interleaved_stereo.call_count, int(present))
                        self.assertEqual(dispatch.call_count, int(present))
                        if present:
                            self.assertEqual(library.openmpt_module_read_interleaved_stereo.call_args.args[:3], (8, 8000, 0))

    @unittest.skipUnless(NODE, 'needs node')
    def test_javascript_group_guards_without_group_runtime(self):
        result = subprocess.run([NODE, str(ROOT / 'tests' / 'engine_check.js'), '--group-guards'],
                                input=json.dumps(self.plan()), text=True, capture_output=True, cwd=ROOT)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue(json.loads(result.stdout)['group_guards'])


@unittest.skipUnless(NODE and (ROOT / "vulturetracker" / "web" / "libopenmpt.wasm").exists(), "needs node and web/libopenmpt.wasm")
class TestEngine(unittest.TestCase):
    def test_imported_percussion_keys_keep_kit_mapping_and_native_wasm_replay(self):
        from tests.test_gpimport import TestPercussionInterchange, TestTgInterchange
        from vulturetracker import tgimport
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            source = folder / 'drums.tg'
            source.write_bytes(TestTgInterchange.archive(TestPercussionInterchange.xml()))
            output = folder / 'song.yaml'
            song, _ = tgimport.import_tg(source, output, folder / 'samples')
            saved = output.read_bytes()
            for rate in (44100, 48000):
                with self.subTest(rate=rate):
                    prepared = api.prepare_playback(song, folder, rate)
                    attacks = [e for e in prepared['plan']['events'] if e['type'] == 'note_on']
                    self.assertTrue({1, 36, 38, 42, 100} <= {e['pitch'] for e in attacks})
                    self.assertTrue(all(e['source_instrument'] == 1 for e in attacks))
                    module = prepared['module']
                    for key, name in ((36, 'kit_kick'), (38, 'kit_snare'), (42, 'kit_hat')):
                        pitch, sample = module.instruments[0].keymap[key]
                        self.assertEqual(pitch, 60)
                        self.assertEqual(module.samples[sample - 1].name, name)
                    self.check_score_replay(prepared, folder)
                    self.assertEqual(output.read_bytes(), saved)

    def test_native_pitch_controls_replay_tail_repeat_and_wasm_checkpoint(self):
        self.check_pitch_runtime()

    def test_percussion_dynamics_and_gates_native_wasm_replay(self):
        from tests.test_tablature_sync import score_song
        song = score_song()
        song['module']['tempo'] = 137
        song['score']['tracks']['guitar'].update(tuning=[0] * 6, midi=dict(bank=128, program=0))
        flags = iter(('ghost', 'accent', 'heavy_accent', 'staccato', 'dead', 'palm_mute'))
        for pattern in song['score']['patterns'].values():
            for beat in pattern['beats']:
                for note in beat['notes']:
                    note.update(pitch=38, fret=38, velocity=95)
                    flag = next(flags, None)
                    if flag:
                        note[flag] = True
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            write_wav(folder / 'tone.wav', 48000, [sine(220, seconds=0.5)])
            for rate in (44100, 48000):
                with self.subTest(rate=rate):
                    self.check_score_replay(api.prepare_playback(song, folder, rate), folder)

    def test_native_velocity_controls_replay_tail_repeat_and_wasm_checkpoint(self):
        self.check_pitch_runtime(velocity=True)

    def test_percussion_let_ring_kit_overlaps_native_wasm_replay(self):
        from tests.test_gpimport import TestPercussionInterchange, TestTgInterchange
        from tests.test_tablature_sync import let_ring_song
        from tests.test_tablature import beat, note
        from vulturetracker import tgimport
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            source = folder / 'kit.tg'
            source.write_bytes(TestTgInterchange.archive(TestPercussionInterchange.xml()))
            kit, _ = tgimport.import_tg(source, folder / 'kit.yaml', folder / 'samples')
            for variant in ('same_parent', 'same_key_other_voice'):
                song = let_ring_song()
                song['samples'], song['instruments'] = kit['samples'], kit['instruments']
                song['patterns']['a']['data'] = ''
                song['score']['tracks']['guitar'].update(
                    tuning=[0] * 6, midi=dict(bank=128, program=0))
                first, second, _ = song['score']['patterns']['a']['beats']
                first['notes'][0].update(pitch=36, fret=36, velocity=95)
                second['notes'][0].update(pitch=38, fret=38, string=1, velocity=79)
                if variant == 'same_key_other_voice':
                    second['notes'][0].update(pitch=42, fret=42, string=2)
                    song['score']['patterns']['a']['beats'].append(dict(
                        beat('voice-two', [1, 1], [dict(note('voice-two', 36, 1, 36), velocity=63)]),
                        voice=1))
                original = copy.deepcopy(song)
                for rate in (44100, 48000):
                    with self.subTest(variant=variant, rate=rate):
                        prepared = api.prepare_playback(song, folder, rate)
                        events = prepared['plan']['events']
                        head = next(e for e in events if e['type'] == 'note_on' and e['id'] == 'first/ring')
                        release = next(e for e in events if e['type'] == 'note_off' and e['id'] == head['id'])
                        self.assertEqual((head['pitch'], release['at']), (36, [2, 1]))
                        replacement = next(e for e in events if e['type'] == 'note_on' and
                                           e['ch'] == head['ch'] and e['id'] != head['id'])
                        self.assertLess(replacement['frame'], release['frame'])
                        self.assertTrue(head.get('hold') or head.get('context'))
                        self.assertEqual(prepared['module'].instruments[0].keymap[36][0], 60)
                        report = self.check_score_replay(prepared, folder)
                        self.assertGreater(report['checkpointRestores'], 0)
                        self.assertEqual(song, original)

    def test_native_group_layers_replay_tail_repeat_and_wasm_checkpoint(self):
        self.check_pitch_runtime(groups=True)

    def test_native_tempo_groups_replay_tail_repeat_and_wasm_checkpoint(self):
        self.check_pitch_runtime(groups=True, tempo=True)

    def test_native_repetition_tie_tempo_and_wasm_replay(self):
        from tests.test_tablature_sync import score_song
        from tests.test_tablature import beat, note
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            write_wav(folder / 'tone.wav', 48000, [sine(220, seconds=0.5)])
            song = score_song()
            song['module']['tempo'] = 137
            song['samples'][1]['loop'] = {'start': 0, 'end': 1024}
            song['instruments'] = {1: {'sample': 1, 'nna': 'continue'}}
            song['patterns']['a']['data'] = ''
            song['patterns']['b']['data'] = '00: ... .. ... T53'
            tail = song['score']['patterns']['a']['beats'][-1]
            tail['notes'][0].update(velocity=95, trill={'fret': 2, 'value': 8})
            song['score']['patterns']['a']['beats'] = [tail]
            song['score']['patterns']['b']['beats'].append(beat('picking', [1, 1], [
                dict(note('picked', 64, 1, 0), velocity=79, tremolo_picking={'value': 16},
                     harmonic={'type': 'semi', 'data': 0})]))
            for rate in (44100, 48000):
                prepared = api.prepare_playback(song, folder, rate)
                plan = prepared['plan']
                attacks = [e for e in plan['events'] if e['type'] == 'note_on']
                self.assertEqual([e['pitch'] for e in attacks], [64, 66, 64, 64, 64, 64])
                self.assertEqual(len({e['id'] for e in attacks}), 6)
                self.assertTrue(all('source_id' in e and 'layers' not in e for e in attacks))
                report = self.check_score_replay(prepared, folder)
                self.assertEqual(report['gainCalls'], 6)
                self.assertEqual(report['checkpointRestores'], 64)

    def test_native_let_ring_sustain_pitch_repetition_and_wasm_replay(self):
        from tests.test_tablature_sync import let_ring_song
        from fractions import Fraction
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            write_wav(folder / 'tone.wav', 48000, [sine(220, seconds=0.5)])
            for effect in ('plain', 'bend', 'repetition'):
                song = let_ring_song()
                note = song['score']['patterns']['a']['beats'][0]['notes'][0]
                if effect == 'bend':
                    note['bend'] = {'points': [{'position': 0, 'value': 0}, {'position': 12, 'value': 4}]}
                elif effect == 'repetition':
                    note.update(velocity=95, tremolo_picking={'value': 16})
                for rate in (44100, 48000):
                    with self.subTest(effect=effect, rate=rate):
                        prepared = api.prepare_playback(song, folder, rate)
                        plan = prepared['plan']
                        position = next(p for p in plan['positions'] if p['id'] == 'first/ring')
                        self.assertEqual(position['end'], [1, 1])
                        self.assertEqual(position['sounding_end'], [2, 1])
                        releases = [e for e in plan['events'] if e['type'] == 'note_off' and
                                    (e['id'] == 'first/ring' or e.get('source_id') == 'first/ring')]
                        self.assertEqual(Fraction(*releases[-1]['at']),
                                         Fraction(1919, 960) if effect == 'repetition' else Fraction(2))
                        report = self.check_score_replay(prepared, folder)
                        self.assertGreater(report['checkpointRestores'], 0)
                        # A two-quarter written sustain in the other voice is an
                        # independent schedule reference for this measured ring case.
                        reference = copy.deepcopy(song)
                        first, second = reference['score']['patterns']['a']['beats'][:2]
                        first['notes'][0].pop('let_ring')
                        first['written']['value'] = 2
                        second['voice'] = 1
                        expected = api.prepare_playback(reference, folder, rate)
                        musical = lambda p: [{k: e[k] for k in ('type', 'id', 'at', 'frame', 'pitch', 'semitones') if k in e}
                                              for e in p['events']]
                        self.assertEqual(musical(plan), musical(expected['plan']))

    def test_native_repeats_tempo_endings_and_wasm_replay(self):
        from tests.test_tablature_sync import repeat_song
        from vulturetracker.itreader import read_it
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            write_wav(folder / 'tone.wav', 48000, [sine(220, seconds=0.5)])
            for effect in ('plain', 'endings', 'grace'):
                song = repeat_song()
                if effect == 'endings':
                    song['score']['measures'][1]['endings'] = [1]
                    song['score']['measures'][2]['endings'] = [2]
                elif effect == 'grace':
                    song['score']['patterns']['a']['beats'][0]['notes'][0]['grace'] = dict(
                        fret=2, value=16, velocity=47, on_beat=True)
                for rate in (44100, 48000):
                    with self.subTest(effect=effect, rate=rate):
                        prepared = api.prepare_playback(song, folder, rate)
                        plan = prepared['plan']
                        self.assertEqual(prepared['module'].orders, [0, 1, 2])
                        sequence = [0, 1, 0, 2] if effect == 'endings' else [0, 1, 0, 1, 2]
                        self.assertEqual([v['source_order'] for v in plan['occurrences']], sequence)
                        backing, _ = read_it(prepared['backing_it'])
                        self.assertEqual(backing.orders[:len(sequence)], prepared['module'].playback_backing().orders)
                        self.assertIn({'at': [8, 1], 'bpm': 137}, plan['tempos'])
                        self.assertEqual(len({e['id'] for e in plan['events'] if e['type'] == 'note_on'}),
                                         sum(e['type'] == 'note_on' for e in plan['events']))
                        report = self.check_score_replay(prepared, folder)
                        self.assertGreater(report['checkpointRestores'], 0)
                        self.assertTrue(report['repeat_source_mapping'])

    def test_native_repeat_fragments_source_seek_and_wasm_replay(self):
        from tests.test_tablature_sync import repeat_fragment_song
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            write_wav(folder / 'tone.wav', 48000, [sine(220, seconds=0.5)])
            for effect in ('plain', 'before_grace', 'context'):
                song = repeat_fragment_song()
                first, second = song['score']['patterns']['a']['beats']
                first['notes'][0]['velocity'] = 95
                second['notes'][0]['velocity'] = 83
                if effect == 'before_grace':
                    second['notes'][0]['grace'] = dict(fret=2, value=16, velocity=47)
                elif effect == 'context':
                    first['written']['value'] = 2
                    first['notes'][0].update(let_ring=True, trill={'fret': 2, 'value': 16})
                    second['notes'][0]['harmonic'] = {'type': 'semi', 'data': 0}
                for rate in (44100, 48000):
                    with self.subTest(effect=effect, rate=rate):
                        prepared = api.prepare_playback(song, folder, rate)
                        visits = prepared['plan']['occurrences']
                        self.assertEqual([v['source_from'] for v in visits], [[0, 1], [2, 1]] * 2)
                        self.assertEqual([len(p.rows) for p in prepared['module'].patterns], [48])
                        report = self.check_score_replay(prepared, folder)
                        self.assertTrue(report['repeat_source_mapping'])
                        if effect == 'context':
                            self.assertTrue(report['contexts'])

    def test_native_cross_order_repeat_measure_keeps_ringing_head(self):
        from tests.test_tablature_sync import let_ring_song
        from tests.test_tablature import beat, note
        song = let_ring_song()
        song['score']['patterns']['a']['beats'] = [
            beat('ring', [2, 1], [dict(note('ring', 64, 1, 0), let_ring=True)], value=2)]
        song['score']['patterns']['b']['beats'] = [
            beat('other', [0, 1], [dict(note('other', 59, 2, 0), let_ring=True)], value=2),
            beat('tail', [2, 1], [note('tail', 55, 3, 0)], value=2)]
        point = lambda occurrence, at: dict(occurrence=occurrence, at=[at, 1])
        song['score']['measures'] = [
            dict(id='first', meter=[2, 4], **{'from': point('first', 0), 'to': point('first', 2)}),
            dict(id='middle', meter=[4, 4], repeat_close=1,
                 **{'from': point('first', 2), 'to': point('second', 2)}),
            dict(id='last', meter=[2, 4], **{'from': point('second', 2), 'to': point('second', 4)})]
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            write_wav(folder / 'tone.wav', 48000, [sine(220, seconds=0.5)])
            for rate in (44100, 48000):
                with self.subTest(rate=rate):
                    prepared = api.prepare_playback(song, folder, rate)
                    visits = prepared['plan']['occurrences']
                    self.assertEqual(visits[1]['measure_play_id'], visits[2]['measure_play_id'])
                    self.assertEqual([e['at'] for e in prepared['plan']['events']
                                      if e['type'] == 'note_off' and e['note'] == 'ring'], [[6, 1], [12, 1]])
                    self.check_score_replay(prepared, folder)

    def test_native_contiguous_fragments_preserve_raw_memory_pcm(self):
        from tests.test_tablature_sync import repeat_fragment_song
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            write_wav(folder / 'tone.wav', 48000, [sine(220, seconds=0.5)])
            song = repeat_fragment_song()
            song['score']['measures'][1]['repeat_close'] = 0
            # A raw voice begins immediately before the cut. Its inherited source,
            # volume/pan and release execute once across the backing boundary.
            raw = {23: 'C-5 01 v48 ...', 24: 'E-5 .. ... X20',
                   25: '... .. ... D01', 30: '=== .. ... ...'}
            song['patterns']['a']['data'] = '\n'.join(
                f'{r:02d}: ... .. ... {"T53" if r == 12 else "..."} | {raw.get(r, "... .. ... ...")}'
                for r in range(48))
            reference = copy.deepcopy(song)
            reference['score']['measures'][0].pop('repeat_open')
            for rate in (44100, 48000):
                with self.subTest(rate=rate):
                    split = api.prepare_playback(song, folder, rate)
                    linear = api.prepare_playback(reference, folder, rate)
                    self.assertEqual(len(split['plan']['occurrences']), 2)
                    self.assertEqual(len(linear['plan']['occurrences']), 1)
                    self.check_score_replay(split, folder)
                    pcm = []
                    for prepared in (split, linear):
                        with LoadedModule(prepared['backing_it'], rate, 1, plan=prepared['plan']) as module:
                            pcm.append(module.render(rate, oversample=1, floats=True))
                    self.assertEqual(pcm[0], pcm[1])

    def test_native_stroke_voices_grace_harmonics_and_wasm_replay(self):
        from tests.test_tablature_sync import stroke_song
        from fractions import Fraction
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            write_wav(folder / 'tone.wav', 48000, [sine(220, seconds=0.5)])
            for effect in ('plain', 'dead', 'grace', 'harmonic', 'repetition', 'repeat', 'swing'):
                song = stroke_song()
                chord = song['score']['patterns']['a']['beats'][0]
                for note in chord['notes']:
                    if effect == 'dead':
                        note['dead'] = True
                    elif effect == 'grace':
                        note['grace'] = dict(fret=2, value=16, velocity=47, on_beat=True)
                    elif effect == 'harmonic':
                        note['harmonic'] = {'type': 'semi', 'data': 0}
                    elif effect == 'repetition':
                        note['tremolo_picking'] = {'value': 16}
                if effect in ('repeat', 'swing'):
                    song['score']['measures'] = [dict(id=name, meter=[4, 4],
                        **{'from': dict(occurrence=oid, at=[0, 1]), 'to': dict(occurrence=oid, at=[4, 1])})
                        for name, oid in (('a', 'first'), ('b', 'second'))]
                    if effect == 'repeat':
                        song['score']['measures'][0].update(repeat_open=True, repeat_close=1)
                    else:
                        song['score']['measures'][0]['swing'] = 'eighth'
                        chord['written']['value'] = 8
                        next_chord = copy.deepcopy(chord)
                        next_chord.update(id='next', at=[1, 2])
                        for note in next_chord['notes']:
                            note['id'] += '_next'
                        song['score']['patterns']['a']['beats'].append(next_chord)
                before = copy.deepcopy(song)
                for rate in (44100, 48000):
                    with self.subTest(effect=effect, rate=rate):
                        prepared = api.prepare_playback(song, folder, rate)
                        if effect == 'plain':
                            ons = [e for e in prepared['plan']['events'] if e['type'] == 'note_on']
                            self.assertEqual({e['pitch']: Fraction(*e['at']) for e in ons},
                                             {64: Fraction(1, 16), 55: Fraction(1, 32), 40: 0})
                        self.check_score_replay(prepared, folder)
                        self.assertEqual(song, before)

    def test_native_written_voices_keep_independent_heads_and_wasm_replay(self):
        from tests.test_tablature_sync import written_voice_song
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            write_wav(folder / 'tone.wav', 48000, [sine(220, seconds=0.5)])
            for variant in ('plain', 'identical', 'staggered', 'stroke', 'techniques', 'repeat', 'tie_fragment'):
                song = written_voice_song()
                long, short = song['score']['patterns']['a']['beats']
                if variant == 'identical':
                    short['notes'][0].update(pitch=65, fret=1, velocity=95)
                elif variant == 'staggered':
                    short['at'] = [1, 2]
                elif variant == 'stroke':
                    from tests.test_tablature import note
                    long['notes'].extend(dict(note(f's{s}', pitch, s, fret), velocity=95)
                                         for s, pitch, fret in ((3, 58, 3), (6, 46, 6)))
                    long['stroke'] = {'direction': 'down', 'value': 4}
                elif variant == 'techniques':
                    long['notes'][0]['tremolo_picking'] = {'value': 16}
                    short['notes'][0]['harmonic'] = {'type': 'semi', 'data': 0}
                    song['instruments'][2] = {'sample': 1, 'global_volume': 37}
                    short['notes'][0]['instrument'] = 2
                elif variant == 'repeat':
                    song['score']['measures'] = [dict(id=name, meter=[4, 4],
                        **{'from': dict(occurrence=oid, at=[0, 1]), 'to': dict(occurrence=oid, at=[4, 1])})
                        for name, oid in (('a', 'first'), ('b', 'second'))]
                    song['score']['measures'][0].update(repeat_open=True, repeat_close=1)
                elif variant == 'tie_fragment':
                    from tests.test_tablature_sync import repeat_fragment_song
                    from tests.test_tablature import beat, note
                    fragments = repeat_fragment_song()
                    song['orders'] = fragments['orders']
                    song['patterns'] = fragments['patterns']
                    song['score']['order_ids'] = fragments['score']['order_ids']
                    song['score']['measures'] = fragments['score']['measures']
                    song['score']['patterns'].pop('b')
                    long['written']['value'] = 2
                    short.update(at=[2, 1], written={'value': 4})
                    song['score']['patterns']['a']['beats'].append(
                        beat('tail', [2, 1], [note('tail', 65, 1, 1)], value=2))
                    song['score']['ties'] = [{'from': {'occurrence': 'first', 'note': 'long'},
                                             'to': {'occurrence': 'first', 'note': 'tail'}}]
                before = copy.deepcopy(song)
                for rate in (44100, 48000):
                    with self.subTest(variant=variant, rate=rate):
                        prepared = api.prepare_playback(song, folder, rate)
                        ons = [e for e in prepared['plan']['events'] if e['type'] == 'note_on' and e['ch'] == 0]
                        self.assertGreaterEqual(len(ons), 2)
                        self.assertTrue(all('context' in e for e in ons))
                        self.assertNotEqual(ons[0]['context'], ons[1]['context'])
                        if variant == 'tie_fragment':
                            self.assertEqual(len(ons), 4)  # Two heads per pass; the continuation never retriggers.
                        self.check_score_replay(prepared, folder)
                        self.assertEqual(song, before)

    def test_native_fade_track_isolation_released_tail_and_tempo(self):
        import numpy as np
        from fractions import Fraction
        from tests.test_tablature_sync import native_fade_it_song
        from tests.test_tablature import beat,note
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp)
            write_wav(folder/'tone.wav',44100,[sine(441,seconds=.5)])
            write_wav(folder/'upper.wav',44100,[sine(882,seconds=.5)])
            song=native_fade_it_song()
            song['module']['channels']=[dict(pan=0) for _ in range(6)]+[dict(pan=64)]
            song['score']['tracks']['other']=dict(name='Other',tuning=[64],channels=[6],instrument=1)
            song['score']['patterns']['a']['beats']=[
                beat('tail',[0,1],[note('tail',64,1,0)],8),
                beat('fade',[1,1],[dict(note('fade',59,2,0),fade_in=True)]),
                dict(beat('isolated',[0,1],[note('isolated',64,1,0)],1),track='other')]
            song['patterns']['a']['data']='\n'.join(f'{row:02d}: '+' | '.join('... .. ... T5A' if row==24 and ch==5 else '... .. ...' for ch in range(7)) for row in range(48))
            song['instruments'][1]['volume_envelope']=dict(nodes=[[0,64],[48,64],[60,0]],sustain=0)
            plain=copy.deepcopy(song);plain['score']['patterns']['a']['beats'][1]['notes'][0].pop('fade_in')
            for rate in (44100,48000):
                pair=api.prepare_playback(song,folder,rate);ref=api.prepare_playback(plain,folder,rate)
                report=self.check_score_replay(pair,folder)
                reference=self.check_score_replay(ref,folder)
                a=np.frombuffer(base64.b64decode(report['pcm']),'<f4').reshape(-1,2)
                b=np.frombuffer(base64.b64decode(reference['pcm']),'<f4').reshape(-1,2)
                self.assertLess(float(np.max(abs(a[:,1]-b[:,1]))),1e-7)
                start,stop=int(rate*.55),int(rate*.60)
                ratio=float(np.sqrt(np.mean(a[start:stop,0]**2)/np.mean(b[start:stop,0]**2)))
                self.assertTrue(.30<ratio<.42,ratio)
                self.assertTrue(any(e['type']=='gain' and e['id']=='first/tail' and Fraction(*e['at'])>1 for e in pair['plan']['events']))
                rendered=[]
                for source in (song,plain):
                    data=api.compile_song(source,folder)[0]
                    with LoadedModule(data,rate,1) as standalone:
                        rendered.append(np.frombuffer(standalone.render(rate,oversample=1,floats=True,max_seconds=1),'<f4').reshape(-1,2))
                self.assertLess(float(np.max(abs(rendered[0][:,1]-rendered[1][:,1]))),1e-7)
                it_ratio=float(np.sqrt(np.mean(rendered[0][start:stop,0]**2)/np.mean(rendered[1][start:stop,0]**2)))
                self.assertLess(abs(it_ratio-ratio),.0625)
                print('fade released tail and isolated track',rate,ratio,it_ratio)

    def test_native_fade_gain_matches_live_offline_and_replay(self):
        from tests.test_tablature_sync import written_voice_song
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            write_wav(folder / 'tone.wav', 48000, [sine(220, seconds=0.5)])
            song = written_voice_song()
            beats = song['score']['patterns']['a']['beats']
            beats[0]['notes'][0]['tremolo_picking'] = {'value': 16}
            beats[1]['notes'][0]['harmonic'] = {'type': 'semi', 'data': 0}
            marked = copy.deepcopy(song)
            for beat in marked['score']['patterns']['a']['beats']:
                beat['notes'][0]['fade_in'] = True
            for rate in (44100, 48000):
                with self.subTest(rate=rate):
                    plain = api.prepare_playback(song, folder, rate)
                    fade = api.prepare_playback(marked, folder, rate)
                    self.assertEqual([e for e in fade['plan']['events'] if e['type'] != 'gain'], plain['plan']['events'])
                    self.assertTrue(any(e['type'] == 'gain' and max(e['gains']) < .3 for e in fade['plan']['events']))
                    self.assertEqual(fade['backing_it'], plain['backing_it'])
                    self.assertEqual(len(fade['plan']['midi_fades']), 2)
                    before = self.check_score_replay(plain, folder)
                    after = self.check_score_replay(fade, folder)
                    self.assertNotEqual(after['pcm'], before['pcm'])

    def test_native_context_host_pair_keeps_simultaneous_heads_and_replay(self):
        from tests.test_tablature_sync import let_ring_song
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            write_wav(folder / 'tone.wav', 48000, [sine(220, seconds=0.5)])
            write_wav(folder / 'other.wav', 48000, [sine(330, seconds=0.5)])
            for effect in ('trill', 'harmonic', 'before_grace', 'mixed'):
                song = let_ring_song()
                song['samples'][2] = dict(song['samples'][1], file='other.wav')
                song['instruments'][2] = {'sample': 2}
                first, second, _ = song['score']['patterns']['a']['beats']
                first['notes'][0]['velocity'] = 95
                second['notes'][0].update(instrument=2, velocity=83)
                if effect in ('trill', 'mixed'):
                    first['notes'][0]['trill'] = {'fret': 2, 'value': 16}
                    if effect == 'mixed':
                        second['notes'][0]['harmonic'] = {'type': 'semi', 'data': 0}
                elif effect == 'harmonic':
                    first['notes'][0]['harmonic'] = {'type': 'semi', 'data': 0}
                else:
                    first['notes'][0].pop('let_ring')
                    second['notes'][0]['grace'] = dict(fret=2, value=16, velocity=47)
                for rate in (44100, 48000):
                    with self.subTest(effect=effect, rate=rate):
                        prepared = api.prepare_playback(song, folder, rate)
                        # Prepare independently authored parents, then exercise the new host ABI directly on one
                        # parent. Model-generated overlap admission has its own separate integration test.
                        ons = [e for e in prepared['plan']['events'] if e['type'] == 'note_on']
                        heads, last = {}, {}
                        for e in ons:
                            head = e.get('source_id', e['id'])
                            last[head] = e
                        for e in prepared['plan']['events']:
                            if effect == 'mixed' and e['ch'] != 0:
                                continue  # Ordinary grouped ABI row mixed into one context transaction.
                            e['ch'] = 0
                            if e['type'] != 'note_on':
                                continue
                            head = e.get('source_id', e['id'])
                            opening = head not in heads
                            if opening:
                                heads[head] = len(heads) + 1
                            e.update(context=heads[head], context_open=opening, context_close=last[head] is e)
                        report = self.check_score_replay(prepared, folder)
                        self.assertGreater(report['checkpointRestores'], 0)

    def test_native_context_model_pair_replays_techniques_on_one_parent(self):
        from tests.test_tablature_sync import let_ring_song
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            write_wav(folder / 'tone.wav', 48000, [sine(220, seconds=0.5)])
            write_wav(folder / 'other.wav', 48000, [sine(330, seconds=0.5)])
            for effect in ('trill', 'harmonic', 'before_grace'):
                song = let_ring_song()
                song['samples'][2] = dict(song['samples'][1], file='other.wav')
                song['instruments'][2] = {'sample': 2}
                first, second, _ = song['score']['patterns']['a']['beats']
                first['notes'][0]['velocity'] = 95
                second['notes'][0].update(string=1, fret=2, pitch=66, instrument=2, velocity=83)
                if effect == 'trill':
                    first['notes'][0]['trill'] = {'fret': 2, 'value': 16}
                elif effect == 'harmonic':
                    first['notes'][0]['harmonic'] = {'type': 'semi', 'data': 0}
                else:
                    first['notes'][0].pop('let_ring')
                    second['notes'][0]['grace'] = dict(fret=2, value=16, velocity=47)
                for rate in (44100, 48000):
                    with self.subTest(effect=effect, rate=rate):
                        prepared = api.prepare_playback(song, folder, rate)
                        ons = [e for e in prepared['plan']['events'] if e['type'] == 'note_on']
                        self.assertTrue(all('context' in e for e in ons))
                        self.assertEqual(len({e['context'] for e in ons}), 2)
                        self.assertEqual({e['ch'] for e in ons}, {0})
                        report = self.check_score_replay(prepared, folder)
                        self.assertTrue(report['contexts'])

    def test_native_swing_tempo_techniques_and_wasm_replay(self):
        from tests.test_tablature_sync import swing_song
        from fractions import Fraction
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            write_wav(folder / 'tone.wav', 48000, [sine(220, seconds=0.5)])
            for effect in ('eighth', 'sixteenth', 'grace', 'repetition', 'tie', 'overlap'):
                song = swing_song('sixteenth' if effect == 'sixteenth' else 'eighth')
                first, second, _ = song['score']['patterns']['a']['beats']
                note = first['notes'][0]
                if effect == 'grace':
                    note['grace'] = dict(fret=2, value=16, velocity=47, on_beat=True)
                elif effect == 'repetition':
                    note.update(velocity=95, trill={'fret': 2, 'value': 16})
                elif effect == 'tie':
                    second['notes'][0].update(pitch=64, string=1, fret=0)
                    song['score']['ties'] = [{'from': dict(occurrence='first', note='ring'),
                                             'to': dict(occurrence='first', note='next')}]
                elif effect == 'overlap':
                    second['at'] = [3127, 6240]
                    second['written']['value'] = 16
                    second['notes'][0].update(pitch=66, string=1, fret=2)
                for rate in (44100, 48000):
                    with self.subTest(effect=effect, rate=rate):
                        prepared = api.prepare_playback(song, folder, rate)
                        plan = prepared['plan']
                        if effect == 'tie':
                            self.assertEqual([Fraction(*e['at']) for e in plan['events']], [0, Fraction(7, 6)])
                        if effect == 'overlap':
                            self.assertTrue(next(e for e in plan['events'] if e['type'] == 'note_on')['hold'])
                        self.assertEqual(plan['positions'][0]['at'], [0, 1])
                        report = self.check_score_replay(prepared, folder)
                        self.assertGreater(report['checkpointRestores'], 0)

    def test_native_grace_timing_layers_and_wasm_replay(self):
        from tests.test_tablature_sync import let_ring_song
        from fractions import Fraction
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            write_wav(folder / 'tone.wav', 48000, [sine(220, seconds=0.5)])
            for effect in ('plain', 'before', 'bend', 'repetition', 'harmonic'):
                song = let_ring_song()
                head = song['score']['patterns']['a']['beats'][0]
                head['notes'][0].pop('let_ring')
                note = head['notes'][0]
                note['grace'] = dict(fret=2, value=16, velocity=47, on_beat=effect != 'before')
                song['score']['patterns']['a']['beats'] = [head]
                if effect == 'before':
                    song['score']['patterns']['a']['beats'] = []
                    song['score']['patterns']['b']['beats'] = [head]
                elif effect == 'bend':
                    note['bend'] = {'points': [{'position': 0, 'value': 0}, {'position': 12, 'value': 4}]}
                elif effect == 'repetition':
                    note.update(velocity=95, trill={'fret': 3, 'value': 16})
                elif effect == 'harmonic':
                    note.update(velocity=95, harmonic={'type': 'semi', 'data': 0})
                for rate in (44100, 48000):
                    with self.subTest(effect=effect, rate=rate):
                        prepared = api.prepare_playback(song, folder, rate)
                        plan = prepared['plan']
                        attacks = [e for e in plan['events'] if e['type'] == 'note_on']
                        grace = attacks[0]
                        self.assertEqual((grace['role'], grace['pitch'], grace['velocity']), ('grace', 66, 47))
                        self.assertEqual(Fraction(*grace['at']), Fraction(15, 4) if effect == 'before' else 0)
                        self.assertEqual(Fraction(*attacks[1]['at']), 4 if effect == 'before' else Fraction(1, 4))
                        self.assertNotIn('layers', grace)
                        self.assertEqual(plan['positions'][0]['at'], [4, 1] if effect == 'before' else [0, 1])
                        report = self.check_score_replay(prepared, folder)
                        self.assertGreater(report['checkpointRestores'], 0)
                        self.assertGreater(report['gainCalls'], 0)

    def test_native_holds_require_capability_before_audio(self):
        from unittest import mock
        from tests.test_tablature_sync import let_ring_song
        from vulturetracker import openmpt
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            write_wav(folder / 'tone.wav', 48000, [sine(220, seconds=0.5)])
            song = let_ring_song()
            song['score']['patterns']['a']['beats'][1]['notes'][0].update(pitch=66, string=1, fret=2)
            prepared = api.prepare_playback(song, folder, 48000)
            original = LoadedModule._interface
            def unavailable(module, name, structure):
                if name == b'vt_held_score':
                    raise openmpt.OpenMPTError('Native score playback requires patched libopenmpt interface vt_held_score')
                return original(module, name, structure)
            with mock.patch.object(LoadedModule, '_interface', unavailable), \
                 mock.patch.object(openmpt._lib, 'openmpt_module_read_interleaved_stereo') as read:
                with self.assertRaisesRegex(openmpt.OpenMPTError, 'vt_held_score'):
                    LoadedModule(prepared['backing_it'], 48000, 1, plan=prepared['plan'])
                read.assert_not_called()

    def test_native_held_overlap_pitch_tempo_and_wasm_replay(self):
        from tests.test_tablature_sync import let_ring_song
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            write_wav(folder / 'tone.wav', 48000, [sine(220, seconds=0.5)])
            song = let_ring_song()
            beats = song['score']['patterns']['a']['beats']
            beats[0]['notes'][0].update(velocity=79,
                bend={'points': [{'position': 0, 'value': 0}, {'position': 12, 'value': 4}]})
            beats[1]['notes'][0].update(pitch=66, string=1, fret=2, velocity=95)
            for rate in (44100, 48000):
                prepared = api.prepare_playback(song, folder, rate)
                attacks = [e for e in prepared['plan']['events'] if e['type'] == 'note_on']
                self.assertEqual([(e['id'], e.get('hold', False), e['at']) for e in attacks],
                                 [('first/ring', True, [0, 1]), ('first/next', False, [1, 1])])
                report = self.check_score_replay(prepared, folder)
                self.assertEqual(report['gainCalls'], 2)
                self.assertGreater(report['pitchCalls'], 0)
                self.assertGreater(report['checkpointRestores'], 0)

    def check_score_replay(self, prepared, folder):
        """Existing native/WASM replay harness, with equal host read partitions."""
        import ctypes as C
        from fractions import Fraction
        from vulturetracker import openmpt
        plan = prepared['plan']
        rate = plan['sample_rate']
        count = plan['duration']['frames'] + 1024
        with LoadedModule(prepared['backing_it'], rate, 1, plan=plan) as native:
            native.render(rate, oversample=1, floats=True, max_seconds=Fraction(0))
            buf, chunks = (C.c_float * 254)(), []
            for at in range(0, count, 127):
                remaining = min(127, count - at)
                while remaining:
                    got = native._native_read(openmpt._lib.openmpt_module_read_interleaved_float_stereo, remaining, buf)
                    self.assertGreater(got, 0)
                    chunks.append(bytes(buf)[:got * 8])
                    remaining -= got
            pcm = b''.join(chunks)
            self.assertEqual(native._handles, {})
        (folder / 'backing.it').write_bytes(prepared['backing_it'])
        (folder / 'plan.json').write_text(json.dumps(plan), encoding='utf-8')
        result = subprocess.run([NODE, str(ROOT / 'tests/engine_check.js'), '--score',
                                 str(folder / 'backing.it'), str(folder / 'plan.json'), '--matching-replay'],
                                capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        self.assertTrue(report['available'], report.get('error'))
        self.assertEqual(base64.b64decode(report['pcm']), pcm)
        return report

    def check_pitch_runtime(self, velocity=False, groups=False, tempo=False):
        from fractions import Fraction
        from vulturetracker.tablature import TempoClock
        import numpy as np
        from vulturetracker.openmpt import OpenMPTError
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            write_wav(folder / 'tone.wav', 48000, [sine(220, seconds=0.5)])
            song = {
                'module': {'tempo': 120, 'speed': 6, 'channels': [{'pan': 0}, {'pan': 64}]},
                'samples': {1: {'file': 'tone.wav', 'loop': {'start': 0, 'end': 1024}}},
                'instruments': {1: {'sample': 1, 'nna': 'continue'}},
                'patterns': {'a': {'rows': 12, 'data': '00: ... .. ... ... | C-5 01 ... ...'}}, 'orders': ['a'],
                'score': {'version': 1, 'order_ids': ['first'],
                          'tracks': {'guitar': {'tuning': [60], 'channels': [0], 'instrument': 1}},
                          'patterns': {'a': {'row_step': [1, 4], 'beats': [
                              {'id': name, 'track': 'guitar', 'voice': 0, 'at': [i, 1], 'written': {'value': 4},
                               'notes': [{'id': name, 'pitch': 60 + i * 7, 'string': 1, 'fret': i * 7}]}
                              for i, name in enumerate(('a', 'b'))]}}}}
            if velocity:
                for beat, value in zip(song['score']['patterns']['a']['beats'], (64, 0)):
                    beat['notes'][0]['velocity'] = value
            if groups:
                for beat in song['score']['patterns']['a']['beats']:
                    beat['notes'][0].update(velocity=95, harmonic={'type': 'semi', 'data': 0})
                song['module']['channels'].append({'pan': 0})
                song['score']['tracks']['ordinary'] = {'tuning': [60], 'channels': [2], 'instrument': 1}
                song['score']['patterns']['a']['beats'].append(
                    {'id': 'c', 'track': 'ordinary', 'voice': 0, 'at': [0, 1], 'written': {'value': 4},
                     'notes': [{'id': 'c', 'pitch': 60, 'string': 1, 'fret': 0}]})
            if tempo:
                song['module']['tempo'] = 137
                song['patterns']['a']['data'] = ''.join(
                    f"{row:02d}: ... .. ... { {4: 'T53', 6: 'TFB'}.get(row, '...')} | "
                    f"{'C-5 01 ... ...' if row == 0 else '... .. ... ...'}\n" for row in range(12))
            for rate in (44100, 48000):
                prepared = api.prepare_playback(song, folder, rate)
                if velocity:
                    attacks = [e for e in prepared['plan']['events'] if e['type'] == 'note_on']
                    self.assertEqual([e['velocity'] for e in attacks], [64, 0])
                    self.assertTrue(all(e['volume'] is None for e in attacks))
                plan = copy.deepcopy(prepared['plan'])
                clock = TempoClock(plan['tempo'], plan.get('tempos'))
                controls = [('first/a', [0, 1], 0), ('first/a', [0, 1], 2), ('first/a', [0, 1], 1),
                            ('first/a', [1, 1], 3), ('first/b', [1, 1], -1), ('first/a', [1, 1], 2),
                            ('first/a', [5, 4], -2), ('first/a', [3, 2], 0),
                            ('first/b', [7, 4], 2), ('first/b', [9, 4], 0), ('first/b', [3, 1], 0)]
                for identity, at, semitones in controls:
                    frames = clock.seconds_at(Fraction(*at)) * rate
                    frame = (2 * frames.numerator + frames.denominator) // (2 * frames.denominator)
                    plan['events'].append(dict(type='pitch', id=identity, at=at, frame=frame, semitones=semitones))
                plan['events'].sort(key=lambda e: (e['frame'], {'note_off': 0, 'note_on': 1, 'pitch': 2}[e['type']]))
                try:
                    native = LoadedModule(prepared['backing_it'], rate, 1, plan=plan)
                except OpenMPTError as error:
                    capability = next((name for name in ('vt_parent_groups', 'vt_gain', 'vt_pitch') if name in str(error)), 'vt_pitch')
                    required = {'vt_parent_groups': 'VT_REQUIRE_GROUPS', 'vt_gain': 'VT_REQUIRE_GAIN', 'vt_pitch': 'VT_REQUIRE_PITCH'}[capability]
                    if capability not in str(error) or os.environ.get(required) == '1' or os.environ.get('VT_REQUIRE_NATIVE_SCORE') == '1':
                        raise
                    self.skipTest('Pitch runtime candidate is not selected: ' + str(error))
                count = plan['duration']['frames'] + 1024
                with native:
                    pcm = native.render(rate, oversample=1, floats=True, max_seconds=Fraction(count, rate))
                    self.assertEqual(native._handles, {})
                (folder / 'backing.it').write_bytes(prepared['backing_it'])
                (folder / 'plan.json').write_text(json.dumps(plan), encoding='utf-8')
                out = subprocess.run([NODE, str(ROOT / 'tests' / 'engine_check.js'), '--score',
                                      str(folder / 'backing.it'), str(folder / 'plan.json')],
                                     capture_output=True, text=True, timeout=60)
                self.assertEqual(out.returncode, 0, out.stderr)
                result = json.loads(out.stdout)
                self.assertTrue(result['available'], result.get('error'))
                self.assertTrue(result['pitch'])
                self.assertEqual(result['pitchCalls'], len(controls) * (3 if groups else 1))
                self.assertEqual(result['gainCalls'], 6 if groups else 2 if velocity else 0)
                self.assertEqual(result['checkpointRestores'], 96)
                reference = np.frombuffer(pcm, '<f4').reshape(-1, 2)
                wasm = np.frombuffer(base64.b64decode(result['pcm']), '<f4').reshape(-1, 2)
                self.assertEqual(reference.shape, wasm.shape)
                if groups:
                    self.assertEqual(base64.b64decode(result['pcm']), pcm)
                self.assertLessEqual(float(np.abs(reference - wasm).max()), 1e-8)
                # Extra neutral pitch-only boundaries must not perturb raw PCM;
                # non-neutral controls must leave the independent raw right channel alone.
                neutral = copy.deepcopy(plan)
                for event in neutral['events']:
                    if event['type'] == 'pitch':
                        event['semitones'] = 0
                outputs = []
                for schedule in (prepared['plan'], neutral):
                    with LoadedModule(prepared['backing_it'], rate, 1, plan=schedule) as module:
                        outputs.append(module.render(rate, oversample=1, floats=True, max_seconds=Fraction(count, rate)))
                self.assertEqual(outputs[0], outputs[1])
                plain = np.frombuffer(outputs[0], '<f4').reshape(-1, 2)
                self.assertTrue(np.array_equal(plain[:, 1], reference[:, 1]))
                self.assertGreater(float(np.abs(plain[:, 0] - reference[:, 0]).max()), .001)
                if velocity:
                    variants = {}
                    for value in (None, 0, 1, 15, 95, 127):
                        schedule = copy.deepcopy(prepared['plan'])
                        for event in schedule['events']:
                            if event['type'] == 'note_on':
                                if value is None:
                                    event.pop('velocity', None)
                                else:
                                    event['velocity'] = value
                        with LoadedModule(prepared['backing_it'], rate, 1, plan=schedule) as module:
                            variants[value] = module.render(rate, oversample=1, floats=True, max_seconds=count / rate)
                        (folder / 'plan.json').write_text(json.dumps(schedule), encoding='utf-8')
                        out = subprocess.run([NODE, str(ROOT / 'tests' / 'engine_check.js'), '--score',
                                              str(folder / 'backing.it'), str(folder / 'plan.json')],
                                             capture_output=True, text=True, timeout=60)
                        self.assertEqual(out.returncode, 0, out.stderr)
                        checked = json.loads(out.stdout)
                        self.assertTrue(checked['available'], checked.get('error'))
                        self.assertEqual(base64.b64decode(checked['pcm']), variants[value])
                        self.assertEqual(checked['gainCalls'], 0 if value is None else 2)
                    self.assertEqual(variants[None], variants[127])  # Full velocity is an exact neutral gain.
                    muted = np.frombuffer(variants[0], '<f4').reshape(-1, 2)
                    full = np.frombuffer(variants[None], '<f4').reshape(-1, 2)
                    self.assertFalse(np.any(muted[:, 0]))
                    self.assertTrue(np.array_equal(muted[:, 1], full[:, 1]))  # Raw channel untouched.
                    for value in (1, 15, 95):
                        actual = np.frombuffer(variants[value], '<f4').reshape(-1, 2)
                        self.assertTrue(np.array_equal(actual[:, 1], full[:, 1]))
                        self.assertLess(float(np.abs(actual[:, 0] - full[:, 0] * (value / 127)).max()), 2e-6)
                with LoadedModule(prepared['backing_it'], rate, 1, plan=plan) as module:
                    target = module._native_order_frame(0, [9, 2])  # Old note released; its final reset remains ahead.
                    module.order_start(0, [9, 2])
                    self.assertIn('first/a', module._handles)
                    sought = module.render(rate, oversample=1, floats=True, max_seconds=512 / rate)
                    self.assertEqual(sought, pcm[target * 8:(target + 512) * 8])
                    before = module._native_frame
                    with self.assertRaisesRegex(ValueError, 'cancelled'):
                        module.order_start(0, cancel=lambda: True)
                    self.assertEqual(module._native_frame, before)
                with LoadedModule(prepared['backing_it'], rate, 1, plan=plan) as module:
                    repeated = module.render(rate, repeat=1, oversample=1, floats=True,
                                             max_seconds=Fraction(2 * plan['duration']['frames'], rate))
                    size = plan['duration']['frames'] * 8
                    self.assertEqual(repeated, pcm[:size] * 2)
                with LoadedModule(prepared['backing_it'], rate, 1, plan=plan) as module:
                    module.render(rate, oversample=1, floats=True, end=(0, 6), max_seconds=rate / rate)
                    self.assertTrue(module._in_tail)
                    self.assertEqual(module._event_index, len(plan['events']))

    def test_native_default_render_keeps_written_rests_and_decay_without_silent_padding(self):
        import numpy as np
        from tests.test_tablature_sync import TestNativeLoadedModule
        song = TestNativeLoadedModule().native_song()
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            for ringing in (False, True):
                # A short tone finishes inside the score; a longer one rings beyond its final note.
                write_wav(folder / 'tone.wav', RATE, [sine(220, seconds=2 if ringing else .05)])
                for oversample, floats, repeat, seek in ((1, False, 0, False), (2, True, 0, False),
                                                        (2, False, 1, False), (2, False, 0, True)):
                    with self.subTest(ringing=ringing, oversample=oversample, floats=floats, repeat=repeat, seek=seek):
                        prepared = api.prepare_playback(song, folder, RATE * oversample)
                        outputs = []
                        for explicit in (True, False):
                            with LoadedModule(prepared['backing_it'], RATE, oversample, plan=prepared['plan']) as module:
                                if seek:
                                    module.order_start(1)
                                written = (module._native_end * (repeat + 1) - module._native_frame +
                                           oversample - 1) // oversample
                                outputs.append(module.render(RATE, oversample=oversample, floats=floats,
                                    repeat=repeat, max_seconds=12 if explicit else None))
                        padded, actual = (np.frombuffer(pcm, '<f4' if floats else '<i2').reshape(-1, 2)
                                          for pcm in outputs)
                        sounding = np.flatnonzero(np.any(padded != 0, axis=1))
                        expected = max(written, int(sounding[-1]) + 1 if len(sounding) else 0)
                        self.assertEqual(len(padded), 12 * RATE)  # Explicit export padding is preserved.
                        self.assertEqual(len(actual), expected)
                        self.assertTrue(np.array_equal(actual, padded[:expected]))
                        if ringing:
                            self.assertGreater(len(actual), written)  # Do not truncate sample decay.
                        else:
                            self.assertEqual(len(actual), written)  # Do not remove the written silence.

    def test_native_export_length_rounds_absolute_output_boundaries_once(self):
        from fractions import Fraction
        from vulturetracker import export
        from tests.test_tablature_sync import TestNativeLoadedModule
        song = TestNativeLoadedModule().native_song()
        song['module']['tempo'] = 137
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            write_wav(folder / 'tone.wav', 48000, [sine(220, seconds=0.5)])
            for region, bounds in (((0, 0, 0, 47), (Fraction(0), Fraction(4))),
                                   ((0, 3, 0, 9), (Fraction(3, 12), Fraction(10, 12)))):
                snap = export.snapshot(song, folder, region=region, tail=0)
                for rate in (22050, 44100, 48000, 96000):
                    def rounded(q):
                        v = q * 60 * rate / 137
                        return (v.numerator * 2 + v.denominator) // (2 * v.denominator)
                    expected = rounded(bounds[1]) - rounded(bounds[0])
                    pcm = export.render(snap, rate=rate)
                    self.assertEqual(len(pcm) // 4, expected, (region, rate))
                    if rate == 44100:
                        self.assertEqual(snap['frames'], expected)

    def test_native_section_export_publishes_matching_song_and_stems(self):
        import wave
        from vulturetracker import export, gui
        from tests.test_tablature_sync import TestNativeLoadedModule
        song = TestNativeLoadedModule().native_song()
        song['sections'] = {'First': [0, 1]}
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            write_wav(folder / 'tone.wav', 48000, [sine(220, seconds=0.5)])
            path = folder / 'song.yaml'
            path.write_bytes(api.to_yaml(song).encode())
            state = gui.State(path, headless=True)
            try:
                job = export.prepare(state, {'destination': 'out', 'fmt': 'wav', 'name': 'section',
                                             'region': 'First', 'stems': True, 'tail': 0.1, 'rate': 48000})
                expected = export.render(job['snapshot'], rate=48000)
                count = len(job['todo'])
                self.assertGreater(count, 1)
                write_wav(folder / 'tone.wav', 48000, [[0] * 100])
                result = export.run(job, gui._encode)
                self.assertEqual(result['status'], 'done', result)
                self.assertEqual(len(result['files']), count)
                for name in result['files']:
                    with wave.open(name, 'rb') as wav:
                        self.assertEqual(wav.getframerate(), 48000)
                        self.assertEqual(wav.getnframes(), len(expected) // 4)
                        if Path(name).name == 'section.wav':
                            self.assertEqual(wav.readframes(wav.getnframes()), expected)
            finally:
                state.close()

    def test_native_region_replays_history_and_stops_before_next_attack(self):
        import copy
        from types import SimpleNamespace
        from vulturetracker import export
        from tests.test_tablature_sync import TestNativeLoadedModule
        song = TestNativeLoadedModule().native_song()
        first = song['score']['patterns']['a']['beats'][0]
        first['at'], first['written'] = [0, 1], {'value': 2}
        second = copy.deepcopy(first)
        second['id'], second['at'] = 'next', [2, 1]
        second['notes'][0]['id'] = 'next-note'
        second['notes'][0]['fret'] += 12
        second['notes'][0]['pitch'] += 12
        song['score']['patterns']['a']['beats'].append(second)
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            write_wav(folder / 'tone.wav', 48000, [sine(220, seconds=3)])
            original = copy.deepcopy(song)
            snap = export.snapshot(song, folder, region=(0, 12, 0, 23), tail=0.1)
            for rate in (44100, 48000):
                prepared = api.prepare_playback(song, folder, rate * 2)
                with LoadedModule(prepared['backing_it'], rate, 2, plan=prepared['plan']) as module:
                    module.order_start(0, [12, 1])
                    calls, parent = [], module._parent
                    def dispatch(ext, mixed, count, offs, notes, attacks, identities):
                        calls.append((module._native_frame, count, notes))
                        return parent.dispatch(ext, mixed, count, offs, notes, attacks, identities)
                    module._parent = SimpleNamespace(dispatch=dispatch)
                    frames = round((0.5 + 0.1) * rate)
                    expected = module.render(rate, max_seconds=frames/rate, end=(0, 24))
                    self.assertTrue(module._in_tail)
                    self.assertEqual(module._event_index, len(module._events))
                    self.assertTrue(any(expected))
                    self.assertTrue(all(notes == 0 for _, _, notes in calls), calls)
                    self.assertTrue(any(offs == 1 for _, offs, _ in calls), calls)
                self.assertEqual(export.render(snap, rate=rate), expected)
            with self.assertRaisesRegex(ValueError, 'cancelled'):
                export.render(snap, cancel=lambda: True)
            with self.assertRaisesRegex(ValueError, 'whole-song'):
                export.render(snap, repeat=1)
            for region in ((0, 8, 0, 7), (0, -1, 0, 7), (0, 0, 9, 0)):
                with self.assertRaises(ValueError):
                    export.snapshot(song, folder, region=region)
            self.assertEqual(song, original)

    def test_native_export_snapshot_keeps_audio_after_source_changes(self):
        from fractions import Fraction
        from vulturetracker import export
        from tests.test_tablature_sync import TestNativeLoadedModule
        song = TestNativeLoadedModule().native_song()
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            write_wav(folder / 'tone.wav', 48000, [sine(220, seconds=0.5)])
            snap = export.snapshot(song, folder, tail=0.1)
            self.assertIsNone(snap['it'])
            expected = {}
            for rate in (44100, 48000):
                prepared = api.prepare_playback(song, folder, rate * 2)
                for repeat in (0, 1):
                    frames = round((snap['frames'] / export.RATE + snap['seconds'] * repeat) * rate)
                    with LoadedModule(prepared['backing_it'], rate, 2, plan=prepared['plan']) as module:
                        expected[rate, repeat] = module.render(rate, repeat=repeat, max_seconds=Fraction(frames, rate))
            write_wav(folder / 'tone.wav', 48000, [[0] * 100])
            song['score']['patterns'].clear()
            for (rate, repeat), pcm in expected.items():
                with self.subTest(rate=rate, repeat=repeat):
                    self.assertEqual(export.render(snap, rate=rate, repeat=repeat), pcm)
            self.assertEqual(set(export.render(snap, silenced=range(snap['channels']))), {0})
            with self.assertRaisesRegex(ValueError, 'cancelled'):
                export.render(snap, cancel=lambda: True)

    def test_song_wav_render_uses_exact_pair_at_oversampled_rate(self):
        import copy
        import wave
        from vulturetracker.fileio import wav_bytes
        from tests.test_tablature_sync import TestNativeLoadedModule
        song = TestNativeLoadedModule().native_song()
        original = copy.deepcopy(song)
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            write_wav(folder / 'tone.wav', 48000, [sine(220, seconds=0.5)])
            for native in (True, False):
                candidate = copy.deepcopy(song)
                if not native:
                    candidate.pop('score')
                    candidate['patterns']['a']['data'] = '00: C-5 01 v48 ...\n'
                for rate, oversample in ((44100, 2), (48000, 1)):
                    with self.subTest(native=native, rate=rate):
                        prepared = api.prepare_playback(candidate, folder, rate * oversample)
                        data = prepared['backing_it'] if native else api.compile_song(candidate, folder)[0]
                        with LoadedModule(data, rate, oversample, plan=prepared['plan']) as module:
                            expected = module.render(rate, oversample=oversample)
                        output = folder / 'render.wav'
                        seconds = api.render(candidate, output, rate=rate, oversample=oversample, base_dir=folder)
                        with wave.open(str(output), 'rb') as wav:
                            self.assertEqual(wav.getframerate(), rate)
                            self.assertEqual(wav.readframes(wav.getnframes()), expected)
                        self.assertEqual(seconds, len(expected) / 4 / rate)
                        if native and oversample == 2:
                            self.assertEqual(api.measure(candidate, rate=rate, base_dir=folder),
                                             api.measure(output, rate=rate))
                            with LoadedModule(data, rate, 2, plan=prepared['plan']) as module:
                                selected = module.render(rate, end=(1, 0))
                            (folder / 'selected.wav').write_bytes(wav_bytes(selected, rate))
                            self.assertEqual(api.measure(candidate, orders=(0, 1), rate=rate, base_dir=folder),
                                             api.measure(folder / 'selected.wav', rate=rate))
            self.assertEqual(song, original)

    def test_roll_score_gestures_keep_fractional_position_and_source_identity(self):
        page = (ROOT / 'vulturetracker' / 'gui.html').read_text(encoding='utf-8')
        code = page[page.index('function rollGestureTarget('):page.index('function rollDown(')]
        check = r"""
const assert = require('assert/strict'), events = {}, commits = [], selected = [], hint = {};
const p = {id:'occ:n', beat:'b', note:'n', pitch:60, row:[7,3], end_row:[11,3], kind:'note',
  occurrence:'occ',track:'guitar',voice:0,ch:0};
const PAT = {idx:2,order:0,occurrence:'occ',revision:'rev',score_positions:[p]}, EDIT = true,
  ROLL = {RW:10,pitchHeight:8,on:true,scopeVersion:0}, CUR = {o:0,row:2,ch:0}, EDQ = {n:0};
const S = {song:{path:'fixture.yaml'},version:{hash:'rev'}}, rollTrack = () => 'guitar';
hint.value='channel';
const zf = () => 1, $ = () => hint, selectScorePosition = id => {selected.push(id);CUR.score=p}, rollApproved = () => false;
const scoreCommit = async (op, rev) => commits.push({op,rev}), noteTxt = n => String(n), scoreRowText = r => r.join('/');
const addEventListener = (k,f) => events[k]=f, removeEventListener = k => delete events[k];
PAGE
const event = x => ({button:0, clientX:x, clientY:50, target:{dataset:{scoreId:p.id}, getBoundingClientRect:()=>({right:100})}});
rollScoreDown(event(50)); events.mousemove({clientX:60,clientY:42}); events.mouseup();
assert.deepEqual(commits.pop(), {op:{op:'note_move',note:'n',to_row:[10,3],pitch:61,pattern:2},rev:'rev'});
rollScoreDown(event(99)); events.mousemove({clientX:109,clientY:50}); events.mouseup();
assert.deepEqual(commits.pop(), {op:{op:'beat_resize',beat:'b',end_row:[14,3],pattern:2},rev:'rev'});
rollScoreDown({...event(50),button:2});
assert.deepEqual(commits.pop(), {op:{op:'note_delete',beat:'b',note:'n',pattern:2},rev:'rev'});
assert.deepEqual(selected, [p.id,p.id,p.id]);
rollScoreDown(event(50)); events.mousemove({clientX:60,clientY:42}); S.version.hash='changed';events.mouseup();
assert.equal(commits.length,0);assert.match(hint.textContent,/Drag cancelled/);
""".replace('PAGE', code)
        out = subprocess.run([NODE, '-e', check], capture_output=True, text=True, timeout=30)
        self.assertEqual(out.returncode, 0, out.stderr)

    def test_pattern_queue_rebases_only_successful_edits_and_stops_after_failure(self):
        page = (ROOT / 'vulturetracker' / 'gui.html').read_text(encoding='utf-8')
        code = page[page.index('function editPost('):page.index('function patUndo(')]
        check = r"""
const assert = require('assert/strict'), PAT = {}, refresh = () => {};
let EDQ, sent, fail;
const fetch = async (url, options) => {
  const body = JSON.parse(options.body); sent.push(body);
  return {json: async () => fail && sent.length === 2 ? {error: 'Refused'} : {ok: true, revision: ['B','A','C'][sent.length - 1]}};
};
PAGE
(async () => {
  for (fail of [false, true]) {
    EDQ = {chain: Promise.resolve(), n: 0}; sent = [];
    for (let i = 0; i < 3; i++) editPost({pattern: 0, occurrence: 'first', revision: 'A', cells: [{row: i}]});
    await EDQ.chain;
    assert.deepEqual(sent.map(x => x.revision), fail ? ['A','B'] : ['A','B','A']);
    assert.equal(EDQ.n, 0);
    assert.equal(EDQ.revisions, null);
    if (fail) assert.match(EDQ.err, /earlier edit failed/);
  }
})().catch(e => { console.error(e.stack); process.exitCode = 1; });
""".replace('PAGE', code)
        out = subprocess.run([NODE, '-e', check], capture_output=True, text=True, timeout=30)
        self.assertEqual(out.returncode, 0, out.stderr)

    def test_shared_cursor_retains_exact_score_identity_without_rounding_it(self):
        page = (ROOT / 'vulturetracker' / 'gui.html').read_text(encoding='utf-8')
        code = page[page.index('function setCursor('):page.index('function cellAt(')]
        check = r"""
const assert = require('assert/strict'), CUR = {}, PAT = {rows: null, order: -1}, selected = [], paused = [];
const SCORE = {editor: {setSelection: s => selected.push(s), pauseFollow: order => paused.push(order)}};
const S = {song: {facts: {orders: [{pattern: 'A'}, {pattern: 'A'}]}}}, $ = () => ({});
PAGE
const exact = {occurrence: 'second', beat: 'b', note: 'n', track: 'guitar', voice: 1, string: 2,
               at: [7, 12], row: [7, 3]};
setCursor(1, exact.row, 2, 0, exact);
assert.equal(CUR.row, 2); // Containing tracker row is navigation only.
assert.deepEqual(CUR.score, exact);
assert.deepEqual(selected[0].row, [7, 3]);
assert.equal(selected[0].occurrence, 'second');
assert.equal(selected[0].note, 'n');
setCursor(1, 3, 2, 0);
assert.equal(CUR.score, null);
assert.equal(selected[1].row, 3);
assert.equal(selected[1].note, undefined);
assert.deepEqual(paused,[1,1]);
""".replace('PAGE', code)
        out = subprocess.run([NODE, '-e', check], capture_output=True, text=True, timeout=30)
        self.assertEqual(out.returncode, 0, out.stderr)

    def test_live_load_discards_an_older_response(self):
        page = (ROOT / 'vulturetracker' / 'gui.html').read_text(encoding='utf-8')
        code = page[page.index('async function lvLoad('):page.index('function lvMsg(')]
        check = r"""
const assert = require('assert/strict'), replies = [], posted = [];
let key = 'first';
const lvKey = () => key, renderLiveBar = () => {}, lvSync = () => {};
const playbackOrders = () => null, REHEARSAL = {active: false};
const fetch = () => new Promise(resolve => replies.push(resolve));
const S = {song: {path: 'fixture.yaml'}, version: {hash: 'revision'}};
const LV = {ctx: {sampleRate: 48000}, node: {port: {postMessage(m) { posted.push(m); LV.loads[m.id].ok(); }}}};
const response = bytes => ({ok: true, json: async () => ({song: 'fixture.yaml', revision: 'revision',
  sample_rate: 48000, backing_it: Buffer.alloc(bytes).toString('base64'), plan: null, gain: 1})});
PAGE
(async () => {
  const first = lvLoad(true);
  key = 'second';
  const second = lvLoad(true);
  replies[1](response(2));
  await second;
  replies[0](response(1));
  await first;
  assert.equal(posted.length, 1);
  assert.equal(posted[0].id, 2);
  assert.equal(posted[0].bytes.byteLength, 2);
  assert.equal(LV.key, 'second');
})().catch(e => { console.error(e.stack); process.exitCode = 1; });
""".replace('PAGE', code)
        out = subprocess.run([NODE, '-e', check], capture_output=True, text=True, timeout=30)
        self.assertEqual(out.returncode, 0, out.stderr)

    def test_native_worklet_replays_seeks_and_swaps_atomically(self):
        from tests.test_tablature_sync import TestNativeLoadedModule
        song = TestNativeLoadedModule().seek_song()
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            write_wav(folder / 'tone.wav', 48000, [sine(220, seconds=0.5)])
            prepared = api.prepare_playback(song, folder, 48000)
            (folder / 'backing.it').write_bytes(prepared['backing_it'])
            (folder / 'plan.json').write_text(json.dumps(prepared['plan']), encoding='utf-8')
            (folder / 'worklet.js').write_text(NATIVE_WORKLET_JS, encoding='utf-8')
            out = subprocess.run([NODE, str(folder / 'worklet.js'), str(ROOT / 'vulturetracker' / 'web'),
                                  str(folder / 'backing.it'), str(folder / 'plan.json')],
                                 capture_output=True, text=True, timeout=60)
            self.assertEqual(out.returncode, 0, out.stderr)
            result = json.loads(out.stdout)
        self.assertTrue(result['seek'])
        self.assertTrue(result['swap'])
        self.assertTrue(result['restart'])
        self.assertTrue(result['speed'])

    def test_native_checkpoint_loops_restore_within_quantum(self):
        from tests.test_tablature_sync import TestNativeLoadedModule
        song = TestNativeLoadedModule().seek_song()
        song['orders'] = ['a', 'b'] * 16
        song['score']['order_ids'] = ['first', 'second'] + [f'order{i}' for i in range(2, 32)]
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            write_wav(folder / 'tone.wav', 48000, [sine(220, seconds=.5)])
            prepared = api.prepare_playback(song, folder, 48000)
            (folder / 'backing.it').write_bytes(prepared['backing_it'])
            (folder / 'plan.json').write_text(json.dumps(prepared['plan']), encoding='utf-8')
            (folder / 'check.js').write_text(CHECKPOINT_WORKLET_JS, encoding='utf-8')
            out = subprocess.run([NODE, str(folder / 'check.js'), str(ROOT / 'vulturetracker' / 'web'),
                str(folder / 'backing.it'), str(folder / 'plan.json')],
                capture_output=True, text=True, timeout=60)
            self.assertEqual(out.returncode, 0, out.stderr)
            result = json.loads(out.stdout)
        self.assertTrue(result['available'], 'Promoted checkpoint ABI is required')
        self.assertEqual(result['cases'], 8)
        self.assertGreater(result['restores'], 2000)

    def test_native_speed_matches_raw_backing_exact_clock(self):
        import copy
        song = {
            'module': {'tempo': 137, 'speed': 6, 'channels': 1},
            'samples': {1: {'file': 'pulse.wav', 'c5_speed': 48000,
                            'sustain_loop': {'start': 0, 'end': 256}}},
            'patterns': {'a': {'rows': 16, 'data': ''}}, 'orders': ['a'],
            'score': {'version': 1, 'order_ids': ['first'],
                      'tracks': {'t': {'tuning': [60], 'channels': [0], 'instrument': 1}},
                      'patterns': {'a': {'row_step': [1, 4], 'beats': [
                          {'id': f'b{i}', 'track': 't', 'at': [i, 1], 'voice': 0,
                           'written': {'value': 8, 'dots': 1, 'tuplet': [1, 1]},
                           'notes': [{'id': f'n{i}', 'pitch': 60, 'string': 1, 'fret': 0, 'volume': 48}]}
                          for i in range(4)]}}}}
        raw = copy.deepcopy(song)
        del raw['score']
        raw['patterns']['a']['data'] = '\n'.join(
            'C-5 01 v48 ...' if r % 4 == 0 else '=== .. ... ...' if r % 4 == 3 else '... .. ... ...'
            for r in range(16)) + '\n'
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            write_wav(folder / 'pulse.wav', 48000, [[10000] * 128 + [0] * 384])
            (folder / 'raw.it').write_bytes(api.compile_song(raw, folder)[0])
            (folder / 'check.js').write_text(SPEED_REFERENCE_JS, encoding='utf-8')
            for rate in (44100, 48000):
                prepared = api.prepare_playback(song, folder, rate)
                (folder / 'backing.it').write_bytes(prepared['backing_it'])
                (folder / 'plan.json').write_text(json.dumps(prepared['plan']), encoding='utf-8')
                out = subprocess.run([NODE, str(folder / 'check.js'), str(ROOT / 'vulturetracker' / 'web'),
                    str(folder / 'backing.it'), str(folder / 'plan.json'), str(folder / 'raw.it')],
                    capture_output=True, text=True, timeout=60)
                self.assertEqual(out.returncode, 0, out.stderr)
                self.assertEqual(len(json.loads(out.stdout)), 4)

    def test_native_score_plan_capability_and_scheduled_reads(self):
        import numpy as np
        rate = 48000
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            write_wav(folder / 'pulse.wav', rate, [[10000] * 128 + [0] * 384])
            song = {
                'module': {'tempo': 137, 'speed': 6, 'sample_rate': rate, 'channels': 2},
                'samples': {1: {'file': 'pulse.wav', 'c5_speed': rate,
                                'sustain_loop': {'start': 0, 'end': 256}}},
                'patterns': {'a': {'rows': 16, 'data': ''}}, 'orders': ['a'],
                'score': {'version': 1, 'order_ids': ['first'],
                          'tracks': {'guitar': {'tuning': [60], 'channels': [0], 'instrument': 1}},
                          'patterns': {'a': {'row_step': [1, 4], 'beats': [
                              {'id': f'b{i}', 'track': 'guitar', 'voice': 0, 'at': [4 * i, 13],
                               'written': {'value': 8, 'tuplet': [13, 8]},
                               'notes': [{'id': f'n{i}', 'pitch': 60, 'string': 1, 'fret': 0,
                                          **({('staccato', 'palm_mute', 'dead')[i % 4 - 1]: True} if i % 4 else {})}]}
                              for i in range(13)]}}}}
            prepared = api.prepare_playback(song, folder, rate)
            with self.assertRaisesRegex(ValueError, 'paired event plan'):
                api.playback_document(song, prepared['module'])
            with self.assertRaisesRegex(ValueError, 'paired event plan'):
                api.tryout_song(song, (0, 1), compiled=prepared['module'])
            (folder / 'backing.it').write_bytes(prepared['backing_it'])
            (folder / 'plan.json').write_text(json.dumps(prepared['plan']), encoding='utf-8')
            out = subprocess.run([NODE, str(ROOT / 'tests' / 'engine_check.js'), '--score',
                                  str(folder / 'backing.it'), str(folder / 'plan.json')],
                                 capture_output=True, text=True, timeout=60)
            self.assertEqual(out.returncode, 0, out.stderr)
            result = json.loads(out.stdout)
        self.assertTrue(result['available'], result.get('error'))
        self.assertTrue(result['checkpoint'], 'Promoted checkpoint ABI is required')
        self.assertEqual(result['checkpointRestores'], 64)
        self.assertTrue(result['block_independent'])
        self.assertTrue(result['speed'])
        self.assertTrue(result['guarded_transport'])
        pcm = np.frombuffer(base64.b64decode(result['pcm']), '<f4').reshape(-1, 2)
        self.assertEqual(len(pcm), prepared['plan']['duration']['frames'] + 1024)
        self.assertGreater(float(np.abs(pcm).max()), 0.01)
        self.assertEqual(float(np.abs(pcm[-128:]).max()), 0)
        self.assertEqual(result['position']['scoreFrame'], len(pcm))
        from vulturetracker.openmpt import OpenMPTError
        try:
            native = LoadedModule(prepared['backing_it'], rate, 1, plan=prepared['plan'])
        except OpenMPTError as error:
            if 'requires' not in str(error) or os.environ.get('VT_REQUIRE_NATIVE_SCORE') == '1':
                raise
            self.skipTest('Native WASM checks passed; matching DLL unavailable: ' + str(error))
        with native:
            rendered = native.render(rate, oversample=1, floats=True, max_seconds=len(pcm) / rate)
            self.assertEqual(native.info()['duration_seconds'], round(prepared['plan']['duration']['frames'] / rate, 3))
        reference = np.frombuffer(rendered, '<f4').reshape(-1, 2)
        self.assertEqual(reference.shape, pcm.shape)
        self.assertLessEqual(float(np.abs(reference - pcm).max()), 1e-8)

    def test_metronome_clicks_on_beat_rows(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            write_wav(d / "a.wav", RATE, [sine(440)], root_note=69)
            write_wav(d / "b.wav", RATE, [sine(880)])
            (d / "song.it").write_bytes(api.compile_song(api.from_yaml(SONG), d)[0])
            (d / "metro.js").write_text(METRO_JS, encoding="utf-8")
            out = subprocess.run([NODE, str(d / "metro.js"), str(ROOT / "vulturetracker" / "web"), str(d / "song.it")],
                                 capture_output=True, text=True, timeout=60, check=True)
        r = json.loads(out.stdout)
        expect = [f for f in r["expect"] if f < 128 * 600 - 32]
        self.assertGreater(len(expect), 5)  # rows 0 and 2 of both 4-row patterns, the song looping (0.12 s a row)
        self.assertEqual(len(r["onsets"]), len(expect))
        for got, want in zip(r["onsets"], expect):
            self.assertLessEqual(abs(got - want), 2)  # the first click sample is sin(0) = 0

    def test_swap_goes_on_from_the_same_frame(self):
        # a song swapped in while it plays (an edit, a fader) must not replay the part of the row already played: every
        # row after the swap starts on the frame it starts on without one
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            write_wav(d / "a.wav", RATE, [sine(440)], root_note=69)
            write_wav(d / "b.wav", RATE, [sine(880)])
            (d / "song.it").write_bytes(api.compile_song(api.from_yaml(SONG), d)[0])
            (d / "swap.js").write_text(SWAP_JS, encoding="utf-8")
            out = subprocess.run([NODE, str(d / "swap.js"), str(ROOT / "vulturetracker" / "web"), str(d / "song.it")],
                                 capture_output=True, text=True, timeout=60, check=True)
        r = json.loads(out.stdout)
        self.assertGreater(len(r["plain"]), 4)
        self.assertEqual(r["swapped"], r["plain"])

    def test_swap_keeps_the_voices_still_fading(self):
        # a note re-struck under NNA fade leaves the old voice fading under the new one; a song swapped in just after
        # (an edit) must keep that voice: a seek straight to the row dropped it (a pad dipped 12 dB for a second)
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            write_wav(d / "a.wav", RATE, [sine(440, seconds=2.0)])
            (d / "song.it").write_bytes(api.compile_song(api.from_yaml(FADE_SONG), d)[0])
            (d / "fade.js").write_text(FADE_JS, encoding="utf-8")
            out = subprocess.run([NODE, str(d / "fade.js"), str(ROOT / "vulturetracker" / "web"), str(d / "song.it")],
                                 capture_output=True, text=True, timeout=60, check=True)
        r = json.loads(out.stdout)
        self.assertGreater(r["level"], 0.05)       # the song sounds after the swap
        self.assertLess(r["diff"], 1e-4)           # and exactly as without one

    def test_a_moving_fader_plays_like_the_header_and_the_preview_sleeps(self):
        # chvol / chpan while the song plays = the channel's volume and pan written into the header (what the fader's
        # release then swaps in); the preview copy renders only while a preview note sounds, then sleeps
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            write_wav(d / "a.wav", RATE, [sine(440)], root_note=69)
            write_wav(d / "b.wav", RATE, [sine(880)])
            (d / "song.it").write_bytes(api.compile_song(api.from_yaml(SONG), d)[0])
            (d / "fader.js").write_text(FADER_JS, encoding="utf-8")
            out = subprocess.run([NODE, str(d / "fader.js"), str(ROOT / "vulturetracker" / "web"), str(d / "song.it")],
                                 capture_output=True, text=True, timeout=60, check=True)
        r = json.loads(out.stdout)
        self.assertGreater(r["level"], 0.05)
        self.assertLess(r["diff"], 1e-6)                  # a fader moved live = the same value in the header
        self.assertGreater(r["plain_diff"], 0.01)         # and the values do change the sound
        self.assertEqual(r["reads_playing"], 0)           # the preview copy is idle while the song plays
        self.assertEqual(r["reads_idle"], 0)              # and while stopped with no note
        self.assertGreater(r["preview_level"], 0.01)      # a preview note sounds
        self.assertTrue(r["asleep"])                      # and some silence after its key is up, the copy sleeps again

    def test_preview_uses_its_paired_bundle_gain_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            write_wav(d / "a.wav", RATE, [sine(440)], root_note=69)
            write_wav(d / "b.wav", RATE, [sine(880)])
            (d / "song.it").write_bytes(api.compile_song(api.from_yaml(SONG), d)[0])
            (d / "preview-gain.js").write_text(PREVIEW_GAIN_JS, encoding="utf-8")
            out = subprocess.run([NODE, str(d / "preview-gain.js"), str(ROOT / "vulturetracker" / "web"),
                                  str(d / "song.it")], capture_output=True, text=True, timeout=60, check=True)
        result = json.loads(out.stdout)
        self.assertGreater(result['unity_peak'], 0.01)
        self.assertEqual(result['gains'], [0.25, 1, 0])
        self.assertTrue(result['pending_reload'])
        self.assertTrue(result['replaced_pending'])
        self.assertTrue(result['invalid_reload_preserved'])

    def test_loads_report_their_id(self):
        # a module the engine cannot load answers with the load's id (the page's wait for it ends, E1); a swap replaced
        # by a newer one before it took over is covered by the newer one's 'loaded', whose id is higher (E2)
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            write_wav(d / "a.wav", RATE, [sine(440)], root_note=69)
            write_wav(d / "b.wav", RATE, [sine(880)])
            (d / "song.it").write_bytes(api.compile_song(api.from_yaml(SONG), d)[0])
            (d / "load.js").write_text(LOAD_JS, encoding="utf-8")
            out = subprocess.run([NODE, str(d / "load.js"), str(ROOT / "vulturetracker" / "web"), str(d / "song.it")],
                                 capture_output=True, text=True, timeout=60, check=True)
        msgs = json.loads(out.stdout)
        self.assertEqual(msgs[0][:2], ["error", 1])
        self.assertEqual(msgs[1:], [["loaded", 2], ["loaded", 4]])
        # the page's side: a 'loaded' ends the wait for its load and every earlier one, an 'error' the wait for its own
        page = (ROOT / "vulturetracker" / "gui.html").read_text(encoding="utf-8")
        a = page.index("function lvMsg(")
        b = page.index("\n// what the engine should be doing")
        with tempfile.TemporaryDirectory() as tmp:
            js = Path(tmp) / "msg.js"
            js.write_text(LVMSG_JS.replace("PAGE", page[a:b]), encoding="utf-8")
            got = json.loads(subprocess.run([NODE, str(js)], capture_output=True, text=True, timeout=30, check=True).stdout)
        self.assertEqual(got, {"done": ["ok 1", "fail 3 bad module", "ok 2", "ok 4"], "left": ["5"], "err": None})

    def test_wasm_engine_matches_the_dll(self):
        import numpy as np
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            write_wav(d / "a.wav", RATE, [sine(440)], root_note=69)
            write_wav(d / "b.wav", RATE, [sine(880)])
            it = api.compile_song(api.from_yaml(SONG), d)[0]
            (d / "song.it").write_bytes(it)
            rate = 48000
            with LoadedModule(it) as lm:
                frames = int(lm.duration() * rate)  # one pass: after it the DLL render stops, the engine loops the song
                ref = np.frombuffer(lm.render(rate, oversample=1), "<i2").astype(int)[: 2 * frames]
                seek = lm.order_start(1, 2)
            with LoadedModule(measure.patch_it(it, [0])) as lm:
                ref_muted = np.frombuffer(lm.render(rate, oversample=1), "<i2").astype(int)[: 2 * frames]
            out = subprocess.run([NODE, str(ROOT / "tests" / "engine_check.js"), str(d / "song.it"), str(rate), str(frames), "0", "0", "60"],
                                 capture_output=True, text=True, timeout=60)
            self.assertEqual(out.returncode, 0, out.stderr)
            r = json.loads(out.stdout)
        pcm = lambda k: np.frombuffer(base64.b64decode(r[k]), "<i2").astype(int)  # noqa: E731
        # the wasm build is 0.8.9, as the vendored DLL is; a system library of another version (Linux distributions ship
        # 0.7.x) is compared by its renders alone, which agree within 2 LSB all the same
        self.assertEqual(r["version"].split("+")[0], "0.8.9")
        if not library_version().startswith("0.8.9"):
            print(f"\n  note: libopenmpt {library_version()} here, the engine's {r['version']}: renders compared, versions not")
        plain, muted = pcm("plain"), pcm("muted")
        self.assertEqual(len(plain), len(ref))
        self.assertGreater(np.abs(ref).max(), 2000)
        self.assertLessEqual(np.abs(plain - ref).max(), 2)             # the same mixer: within 2 LSB of the DLL's int16 render
        self.assertLessEqual(np.abs(muted - ref_muted).max(), 2)       # interactive mute = the header's channel-disable bit
        self.assertTrue(r["muted_flag"])
        self.assertAlmostEqual(r["seek_seconds"], seek, places=6)
        self.assertEqual((r["pos"]["order"], r["pos"]["row"]), (1, 2))
        self.assertEqual(np.abs(pcm("preview_silent_before")).max(), 0)  # every song channel muted
        self.assertGreaterEqual(r["preview_channel"], 2)                 # a free channel past the pattern's two
        self.assertGreater(np.abs(pcm("preview")).max(), 1000)           # the note preview sounds


# the worklet's metronome under node: the processor itself (engine-worklet.js on engine-core.js and the wasm) with the
# AudioWorkletGlobalScope stubbed, rendered with and without the metronome; the clicks must start where a beat row starts
METRO_JS = r"""
const fs = require('fs'), path = require('path'), WEB = process.argv[2], it = new Uint8Array(fs.readFileSync(process.argv[3]));
const ASSETS = process.env.VT_ENGINE_DIR || WEB;
const glue = new Function('libopenmpt', 'require', '__dirname', fs.readFileSync(path.join(ASSETS, 'libopenmpt.js'), 'utf8') + '\nreturn Module;');
Object.assign(globalThis, {sampleRate: 48000, currentTime: 0, currentFrame: 0, loadGlue: cfg => glue(cfg, require, ASSETS),
  loadOpenmpt: require(path.join(WEB, 'engine-core.js')).loadOpenmpt,
  AudioWorkletProcessor: class { constructor() { this.port = {postMessage: m => this.onmsg && this.onmsg(m)} } },
  registerProcessor: (n, c) => { globalThis.Proc = c }});
require(path.join(WEB, 'engine-worklet.js'));
const make = () => new Promise(ok => { const p = new Proc({processorOptions: {wasm: fs.readFileSync(path.join(ASSETS, 'libopenmpt.wasm'))}}); p.onmsg = m => m.type === 'ready' && ok(p) });
function run(p, metro, blocks) {
  p.command({type: 'load', bytes: it.slice().buffer});
  if (metro) p.command({type: 'metro', on: true, beat: 2, bar: 4});
  p.command({type: 'play', order: 0, row: 0});
  const out = [];
  for (let b = 0; b < blocks; b++) { const L = new Float32Array(128), R = new Float32Array(128); p.process([], [[L, R]]); out.push(...L) }
  return out;
}
(async () => {
  const blocks = 600, a = run(await make(), true, blocks), b = run(await make(), false, blocks);
  const onsets = [];
  for (let i = 0, quiet = 1e9; i < a.length; i++) { const d = Math.abs(a[i] - b[i]) > 1e-4; if (d && quiet > 400) onsets.push(i); quiet = d ? 0 : quiet + 1 }
  // where the processor sees each beat row start: the end of the 32-frame step after which the row changed
  const E = await loadOpenmpt(cfg => glue(cfg, require, WEB), fs.readFileSync(path.join(WEB, 'libopenmpt.wasm')));
  const s = new E.Song(it), L = new Float32Array(32), R = new Float32Array(32), expect = [];
  let last = null;
  for (let i = 0; i < 128 * blocks; i += 32) { s.read(48000, 32, L, R); const p = s.position(), k = p.order * 1024 + p.row; if (k !== last) { last = k; if (p.row % 2 === 0) expect.push(i + 32) } }
  console.log(JSON.stringify({onsets, expect}));
})();
"""


# the worklet's loads: garbage (id 1), a good module (2), then while playing two swaps in a row (3, 4): the second
# replaces the first before it takes over. Prints the loaded/error messages as [type, id]
LOAD_JS = r"""
const fs = require('fs'), path = require('path'), WEB = process.argv[2], it = new Uint8Array(fs.readFileSync(process.argv[3]));
const glue = new Function('libopenmpt', 'require', '__dirname', fs.readFileSync(path.join(WEB, 'libopenmpt.js'), 'utf8') + '\nreturn Module;');
Object.assign(globalThis, {sampleRate: 48000, currentTime: 0, currentFrame: 0, loadGlue: cfg => glue(cfg, require, WEB),
  loadOpenmpt: require(path.join(WEB, 'engine-core.js')).loadOpenmpt,
  AudioWorkletProcessor: class { constructor() { this.port = {postMessage: m => this.onmsg && this.onmsg(m)} } },
  registerProcessor: (n, c) => { globalThis.Proc = c }});
require(path.join(WEB, 'engine-worklet.js'));
(async () => {
  const p = await new Promise(ok => { const p = new Proc({processorOptions: {wasm: fs.readFileSync(path.join(WEB, 'libopenmpt.wasm'))}}); p.onmsg = m => m.type === 'ready' && ok(p) });
  const out = [];
  p.onmsg = m => { if (m.type === 'loaded' || m.type === 'error') out.push([m.type, m.id]) };
  p.command({type: 'load', bytes: new Uint8Array(100).buffer, id: 1});
  p.command({type: 'load', bytes: it.slice().buffer, id: 2});
  p.command({type: 'play', order: 0, row: 0});
  for (let b = 0; b < 50; b++) p.process([], [[new Float32Array(128), new Float32Array(128)]]);
  p.command({type: 'load', bytes: it.slice().buffer, keep: true, id: 3});
  p.command({type: 'load', bytes: it.slice().buffer, keep: true, id: 4});
  for (let b = 0; b < 200; b++) p.process([], [[new Float32Array(128), new Float32Array(128)]]);
  console.log(JSON.stringify(out));
})();
"""


# the page's lvMsg under node, with loads 1-5 waiting: an error for 3, then 'loaded' for 2 and for 4
LVMSG_JS = r"""
const done = [], LV = {loads: {}, err: null}, S = null, renderLiveBar = () => {}, $ = () => ({classList: {contains: () => false}});
for (const id of [1, 2, 3, 4, 5]) LV.loads[id] = {ok: () => done.push('ok ' + id), fail: e => done.push('fail ' + id + ' ' + e.message)};
PAGE
lvMsg({type: 'loaded', id: 1});
lvMsg({type: 'error', id: 3, text: 'bad module'});
lvMsg({type: 'loaded', id: 4});
console.log(JSON.stringify({done, left: Object.keys(LV.loads), err: LV.err}));
"""


# the worklet swapping the song in mid-row (load with keep, as the page does after an edit) against one that plays on:
# the frame (to the 128-frame block) where each row starts, over 300 blocks after the swap
SWAP_JS = r"""
const fs = require('fs'), path = require('path'), WEB = process.argv[2], it = new Uint8Array(fs.readFileSync(process.argv[3]));
const ASSETS = process.env.VT_ENGINE_DIR || WEB;
const glue = new Function('libopenmpt', 'require', '__dirname', fs.readFileSync(path.join(ASSETS, 'libopenmpt.js'), 'utf8') + '\nreturn Module;');
Object.assign(globalThis, {sampleRate: 48000, currentTime: 0, currentFrame: 0, loadGlue: cfg => glue(cfg, require, ASSETS),
  loadOpenmpt: require(path.join(WEB, 'engine-core.js')).loadOpenmpt,
  AudioWorkletProcessor: class { constructor() { this.port = {postMessage: m => this.onmsg && this.onmsg(m)} } },
  registerProcessor: (n, c) => { globalThis.Proc = c }});
require(path.join(WEB, 'engine-worklet.js'));
const make = () => new Promise(ok => { const p = new Proc({processorOptions: {wasm: fs.readFileSync(path.join(ASSETS, 'libopenmpt.wasm'))}}); p.onmsg = m => m.type === 'ready' && ok(p) });
async function run(swapAt) {
  const p = await make(), rows = [];
  p.command({type: 'load', bytes: it.slice().buffer});
  p.command({type: 'play', order: 0, row: 0});
  let last = null;
  for (let b = 0; b < 400; b++) {
    if (b === swapAt) p.command({type: 'load', bytes: it.slice().buffer, keep: true});
    p.process([], [[new Float32Array(128), new Float32Array(128)]]);
    const q = p.song.position(), k = q.order * 1024 + q.row;
    if (k !== last) { last = k; if (b > 100) rows.push([b, k]) }
  }
  return rows;
}
(async () => { console.log(JSON.stringify({plain: await run(-1), swapped: await run(100)})) })();
"""


SPEED_REFERENCE_JS = SWAP_JS.split("async function run")[0] + r"""
const assert = require('assert/strict'), plan = JSON.parse(fs.readFileSync(process.argv[4], 'utf8')),
      raw = new Uint8Array(fs.readFileSync(process.argv[5]));
(async () => {
  const p = await make(), results = [];
  for (const factor of [.5, .75, 1.3, 2]) {
    const score = new p.E.Song(it, plan, factor),
          reference = new p.E.Song(raw, {...plan, events: [], positions: []}, factor);
    try {
      const a = [new Float32Array(4096), new Float32Array(4096)],
            b = [new Float32Array(4096), new Float32Array(4096)];
      let peak = 0, difference = 0;
      for (let at = 0; at < score.score.end; at += 127) {
        const n = Math.min(127, score.score.end - at);
        score.read(plan.sample_rate, n, ...a);
        reference.read(plan.sample_rate, n, ...b);
        for (let ch = 0; ch < 2; ch++) for (let i = 0; i < n; i++) {
          peak = Math.max(peak, Math.abs(a[ch][i]));
          difference = Math.max(difference, Math.abs(a[ch][i] - b[ch][i]));
        }
      }
      assert.ok(peak > .01);
      assert.ok(difference < 1e-6, `factor ${factor}: raw/native PCM difference ${difference}`);
      results.push({factor, factorQ:score.factorQ, difference});
    } finally { score.free(); reference.free(); }
  }
  console.log(JSON.stringify(results));
})().catch(e => { console.error(e.stack); process.exitCode = 1; });
"""


NATIVE_WORKLET_JS = SWAP_JS.split("async function run")[0] + r"""
const assert = require('assert/strict'), plan = JSON.parse(fs.readFileSync(process.argv[4], 'utf8'));
const quantum = p => {
  const L = new Float32Array(128), R = new Float32Array(128);
  p.process([], [[L, R]]);
  return [L, R];
};
const finish = p => {
  let blocks = 0;
  while (p.pending) { assert.ok(++blocks < 2000, 'Replay did not complete'); quantum(p); }
  return blocks;
};
const checkNext = (p, reference) => {
  const expected = [new Float32Array(128), new Float32Array(128)];
  reference.read(sampleRate, 128, ...expected);
  const actual = quantum(p);
  // Ordinary OpenMPT volume ramps have sub-float-ulp block partition differences under Vxx.
  // Seek/reference use identical replay partitions and must match exactly.
  assert.deepEqual(actual, expected);
};
(async () => {
  const p = await make(), messages = [];
  p.onmsg = m => messages.push(m);
  p.command({type: 'load', bytes: it.slice().buffer, plan, id: 1});
  assert.equal(messages.at(-1).type, 'loaded');
  p.command({type: 'play', order: 1, row: [7, 3]});
  const target = p.pending.target;
  assert.ok(p.pending && !p.playing, 'Deep seek must remain pending');
  const reference = p.song.fresh(), scratch = [new Float32Array(4096), new Float32Array(4096)];
  while (!reference.advanceTo(target, 4096, ...scratch)) {}
  assert.ok(finish(p) > 1, 'Replay must be bounded per quantum');
  assert.equal(p.song.score.frame, target);
  assert.equal(p.song.position().order, 1);
  assert.equal(p.song.position().occurrence, plan.occurrences[1].id);
  assert.equal(p.song.position().sampleRate, sampleRate);
  assert.ok(Math.abs(p.song.position().scoreRow[0] / p.song.position().scoreRow[1] - 7 / 3) < 0.001);
  checkNext(p, reference);
  reference.free();
  for (let i = 0; i < 4; i++) quantum(p);
  const positionMessage = messages.findLast(m => m.type === 'pos');
  assert.ok(Number.isSafeInteger(positionMessage.scoreFrame));
  assert.equal(positionMessage.sampleRate, sampleRate);
  assert.equal(positionMessage.occurrence, plan.occurrences[1].id);
  assert.ok(Array.isArray(positionMessage.scoreAt) && Array.isArray(positionMessage.scoreRow));
  p.command({type: 'load', bytes: it.slice().buffer, plan, keep: true, id: 2});
  const old = p.song;
  assert.notEqual(p.pending.song, old);
  p.command({type: 'load', bytes: it.slice().buffer, plan, keep: true, id: 3});
  assert.equal(p.song, old, 'Unprepared load replaced sounding song');
  const cuts = [], candidate = p.pending.song, read = candidate.read.bind(candidate);
  candidate.read = (...args) => { cuts.push(args[1]); return read(...args); };
  finish(p);
  assert.ok(!messages.some(m => m.type === 'loaded' && m.id === 2));
  assert.ok(messages.some(m => m.type === 'loaded' && m.id === 3));
  // Compare the live swap to a fresh full replay at the identical resulting frame.
  const swapped = p.song.fresh();
  for (const frames of cuts) swapped.read(sampleRate, frames, ...scratch);
  assert.equal(swapped.score.frame, p.song.score.frame);
  checkNext(p, swapped);
  swapped.free();
  p.command({type: 'play', order: 1, row: 3});
  p.command({type: 'stop'});
  finish(p);
  assert.equal(p.playing, false, 'Stop during replay resumed playback');
  p.command({type: 'play', order: 3, row: 0});
  finish(p);
  const restart = p.song.fresh();
  checkNext(p, restart);
  restart.free();
  p.command({type: 'loop', span: {from: [1, 0], to: [1, 3]}});
  p.command({type: 'play', order: 1, row: 0});
  finish(p);
  const bounds = p.scoreLoop(p.song);
  let frame = bounds.from, wraps = 0;
  for (let b = 0; b < 200; b++) {
    quantum(p);
    frame += 128;
    while (frame > bounds.to) { frame = bounds.from + frame - bounds.to; wraps++; }
    assert.equal(p.song.score.frame, frame, 'Range wrap must be at its exact exclusive frame');
    assert.equal(p.pending, null, 'Prepared normal range loop unexpectedly stalled');
  }
  assert.ok(wraps >= 2);
  p.command({type: 'loop', span: null});
  const kept = p.song;
  p.command({type: 'load', bytes: it.slice().buffer, plan: {...plan, sample_rate: 44100}, id: 4});
  assert.equal(p.song, kept);
  assert.equal(messages.at(-1).id, 4);
  assert.equal(messages.at(-1).type, 'error');
  const untouched = JSON.stringify(plan);
  p.command({type:'chvol',ch:0,value:.37});
  p.command({type:'chpan',ch:0,value:-.6});
  if (p.song.channels > 1) p.command({type:'mute',ch:1,on:true});
  for (const factor of [0.5, 0.75, 1.3, 2]) {
    const old = p.song, oldFrame = old.score.frame, oldQ = old.factorQ;
    p.command({type: 'tempo', factor});
    assert.equal(p.factor, factor);
    assert.equal(old.factorQ, oldQ, 'Speed mutated the sounding clock');
    assert.equal(old.score.frame, oldFrame);
    assert.ok(p.pending, 'Deep speed change must be staged');
    const candidate = p.pending.song, cuts = [], read = candidate.read.bind(candidate);
    candidate.read = (...args) => { cuts.push(args[1]); return read(...args); };
    quantum(p);
    assert.ok(old.score.frame > oldFrame, 'Old playback stopped during speed preparation');
    finish(p);
    assert.equal(p.song.factorQ, Math.floor(65536 / factor + .5));
    const check = p.song.fresh();
    for (const count of cuts) check.read(sampleRate, count, ...scratch);
    assert.equal(check.score.frame, p.song.score.frame);
    checkNext(p, check);
    check.free();
    for (let i = 0; i < 4; i++) quantum(p);
    const message = messages.findLast(m => m.type === 'pos');
    assert.equal(message.factorQ, p.song.factorQ);
    assert.ok(Array.isArray(message.scoreTime));
  }
  const factorBefore = p.factor, songBefore = p.song;
  for (const factor of [0, -1, NaN, Infinity, 4.01, null, '2']) {
    p.command({type: 'tempo', factor});
    assert.equal(p.factor, factorBefore);
    assert.equal(p.song, songBefore);
    assert.equal(p.pending, null);
    assert.equal(messages.at(-1).type, 'error');
  }
  p.command({type: 'tempo', factor: .5});
  const obsolete = p.pending.song;
  quantum(p);
  p.command({type: 'tempo', factor: .75});
  assert.equal(obsolete.ext, 0, 'Superseded speed replay leaked');
  const editCancelled = p.pending.song;
  p.command({type:'load', bytes:it.slice().buffer, plan, keep:true, id:6});
  assert.equal(editCancelled.ext, 0);
  assert.equal(p.pending.song.factorQ, Math.floor(65536 / .75 + .5));
  finish(p);
  p.command({type:'play', order:1, row:[7,3]});
  p.command({type:'tempo', factor:1.3});
  const seekCancelled = p.pending.song;
  p.command({type:'load', bytes:it.slice().buffer, plan, keep:true, id:7});
  assert.equal(seekCancelled.ext, 0);
  p.command({type:'stop'});
  finish(p);
  assert.equal(p.playing, false);
  assert.equal(p.song.score.frame, p.song.scoreFrameAt(1, [7,3]));
  p.command({type:'loop',span:{from:[1,0],to:[1,3]}});
  p.command({type:'play',order:1,row:0});
  finish(p);
  const speedBounds = p.scoreLoop(p.song);
  let speedFrame = speedBounds.from, speedWraps = 0;
  for (let b = 0; b < 200; b++) {
    quantum(p);
    speedFrame += 128;
    while (speedFrame > speedBounds.to) { speedFrame = speedBounds.from + speedFrame - speedBounds.to; speedWraps++; }
    assert.equal(p.song.score.frame, speedFrame, 'Speed loop uses an unscaled boundary');
  }
  assert.ok(speedWraps > 1);
  p.command({type:'loop',span:null});
  assert.equal(JSON.stringify(plan), untouched);
  p.command({type: 'load', bytes: it.slice().buffer, plan, keep: true, id: 5});
  const beforeFailure = p.song;
  p.pending.song.read = () => { throw new Error('Injected replay failure'); };
  quantum(p);
  assert.equal(p.song, beforeFailure, 'Failed replay replaced the sounding song');
  assert.equal(p.pending, null);
  assert.ok(messages.some(m => m.type === 'error' && m.id === 5 && m.text.includes('Injected')));
  p.clearLoopReplay(); p.song.free(); p.preview.free();
  // A legacy edit waiting at an unprepared native wrap keeps ownership of its
  // candidate. Previously the loop staging path overwrote and leaked this load.
  const transition = await make(), transitionMessages = [];
  transition.onmsg = m => transitionMessages.push(m);
  transition.command({type:'load',bytes:it.slice().buffer,plan,id:1});
  transition.command({type:'loop',span:{from:[1,0],to:[1,3]}});
  transition.command({type:'play',order:1,row:0});
  finish(transition);
  const end = transition.scoreLoop(transition.song).to;
  transition.song.advanceTo(end, end, ...scratch);
  transition.command({type:'load',bytes:it.slice().buffer,keep:true,id:2});
  const incoming = transition.pending.song;
  transition.clearLoopReplay();
  quantum(transition);
  assert.ok(transition.pending?.song === incoming || transition.song === incoming);
  finish(transition);
  assert.equal(transition.song, incoming);
  assert.equal(transition.playing, true);
  assert.ok(transitionMessages.some(m => m.type === 'loaded' && m.id === 2));
  transition.clearLoopReplay(); transition.song.free(); transition.preview.free();
  const gained = await make();
  gained.command({type: 'load', bytes: it.slice().buffer, plan, gain: 0.5, id: 1});
  gained.command({type: 'play', order: 0, row: 0});
  const full = gained.song.fresh(), referenceGain = [new Float32Array(128), new Float32Array(128)];
  full.read(sampleRate, 128, ...referenceGain);
  for (const channel of referenceGain) for (let i = 0; i < channel.length; i++) channel[i] *= 0.5;
  assert.deepEqual(quantum(gained), referenceGain);
  assert.equal(full.outputGain, 0.5, 'Replay discarded the bundle output gain');
  full.free();
  const failures = [], failed = gained.song;
  gained.onmsg = m => failures.push(m);
  failed.read = () => { throw new Error('Injected sounding batch failure'); };
  assert.deepEqual(quantum(gained), [new Float32Array(128),new Float32Array(128)]);
  assert.equal(gained.song, null);
  assert.equal(gained.playing, false);
  assert.equal(failed.ext, 0);
  assert.ok(failures.some(m=>m.type==='error' && m.fatal && m.text.includes('batch failure')));
  gained.command({type:'load',bytes:it.slice().buffer,plan,id:2});
  gained.command({type:'play',order:0,row:0});
  assert.ok(quantum(gained)[0].some(x=>x!==0), 'Processor did not recover after replacing the failed pair');
  gained.clearLoopReplay(); gained.song.free(); gained.preview.free();
  console.log(JSON.stringify({seek: true, swap: true, restart: true, speed: true}));
})().catch(e => { console.error(e.stack); process.exitCode = 1; });
"""


CHECKPOINT_WORKLET_JS = NATIVE_WORKLET_JS.split("(async () => {")[0] + r"""
const pair = (n, d) => {
  let a = n, b = d; while (b) [a,b] = [b,a%b];
  return [Number(n/a), Number(d/a)];
};
const rowAt = (frame, order, q, subtractOne = false) => {
  const [an,ad] = plan.occurrences[order].at.map(BigInt), [sn,sd] = plan.row_step.map(BigInt);
  const n = BigInt(frame)*BigInt(plan.tempo)*65536n, d = 60n*BigInt(sampleRate)*BigInt(q);
  return pair((n*ad-an*d)*sd - (subtractOne ? d*ad*sn : 0n), d*ad*sn);
};
(async () => {
  let cases = 0, restores = 0;
  for (const [order, factor] of [[1,1],[17,1.3]]) for (const length of [1,17,127,2049]) {
    const p = await make(), messages = [];
    p.onmsg = m => messages.push(m);
    p.command({type:'tempo', factor});
    p.command({type:'load',bytes:it.slice().buffer,plan,id:1});
    if (!p.song.checkpointAvailable) {
      p.song.free(); p.preview.free();
      console.log(JSON.stringify({available:false})); return;
    }
    const target = p.song.scoreFrameAt(order, 6) - 40, q = p.song.factorQ,
          span = {from:[order,rowAt(target,order,q)],to:[order,rowAt(target+length,order,q,true)]};
    p.command({type:'loop',span});
    p.command({type:'play',order,row:span.from[1]});
    finish(p);
    assert.equal(p.song.score.frame, target);
    const reference = p.song.fresh(), scratch = [new Float32Array(4096),new Float32Array(4096)];
    while (!reference.advanceTo(target,4096,...scratch)) {}
    reference.captureCheckpoint();
    const sounding = p.song, fresh = sounding.fresh.bind(sounding),
          restore = sounding.restoreCheckpoint.bind(sounding), retired = new Set();
    sounding.fresh = () => { throw new Error('A prepared loop replayed its prefix'); };
    sounding.restoreCheckpoint = () => {
      restore(); restores++;
      for (const id of sounding.score.voices.values()) if (id > 0n) {
        assert.ok(!retired.has(id), 'Lap reused a retired native identity');
        retired.add(id);
      }
    };
    let peak = 0;
    for (let block=0;block<12;block++) {
      const expected=[new Float32Array(128),new Float32Array(128)];
      for (let at=0;at<128;) {
        if (reference.score.frame===target+length) reference.restoreCheckpoint();
        const n=Math.min(128-at,target+length-reference.score.frame);
        reference.read(sampleRate,n,...expected,false,at); at+=n;
      }
      const actual=quantum(p);
      assert.deepEqual(actual,expected,`Checkpoint loop ${order}/${factor}/${length}`);
      assert.equal(p.song,sounding);
      assert.equal(p.pending,null);
      assert.equal(p.playing,true);
      peak=Math.max(peak,...actual[0].map(Math.abs),...actual[1].map(Math.abs));
    }
    assert.ok(peak>1e-5,'Fixture must exercise sounding voices');
    assert.equal(messages.some(m=>m.type==='preparing'),false,'Prepared tiny loop stalled');
    assert.ok(sounding.hasCheckpoint(target));
    sounding.fresh=fresh;
    reference.free();
    const settleLoop = () => {
      let blocks=0;
      while (!p.song?.hasCheckpoint(target)) {
        assert.ok(++blocks<2000, 'Invalidated loop did not prepare a new checkpoint');
        quantum(p);
      }
    };
    // Same/rejected settings calls also invalidate. Reprepare once, then the
    // replacement module keeps its own checkpoint for subsequent laps.
    p.command({type:'mute',ch:0,on:true});
    assert.equal(sounding.hasCheckpoint(target),false);
    settleLoop();
    assert.equal(p.song.muted(0),true);
    assert.ok(p.song.hasCheckpoint(target));
    p.command({type:'chpan',ch:-1,value:0});
    assert.equal(p.song.hasCheckpoint(target),false);
    settleLoop();
    p.command({type:'load',bytes:it.slice().buffer,plan,keep:true,id:2,muted:[0]});
    const obsolete=p.pending?.song;
    p.command({type:'load',bytes:it.slice().buffer,plan,keep:true,id:3,muted:[0]});
    if (obsolete) assert.equal(obsolete.ext,0);
    finish(p); settleLoop();
    assert.ok(p.song.hasCheckpoint(target));
    assert.equal(messages.some(m=>m.type==='loaded'&&m.id===2),false);
    assert.ok(messages.some(m=>m.type==='loaded'&&m.id===3));
    // Native refusal must kill this consumer; there is no replay fallback.
    const invalid=p.song;
    invalid.fn.mute(invalid.ext,0,1);
    let attempts=0;
    while (p.song) { assert.ok(++attempts<30); quantum(p); }
    assert.equal(invalid.ext,0);
    assert.equal(p.playing,false);
    assert.ok(messages.some(m=>m.type==='error'&&m.fatal&&m.text.includes('restore refused')));
    p.clearLoopReplay(); p.preview.free(); cases++;
  }
  console.log(JSON.stringify({available:true,cases,restores}));
})().catch(e=>{console.error(e.stack);process.exitCode=1});
"""


FADER_JS = SWAP_JS.split("async function run")[0] + r"""
function render(p, quanta) {
  const L = [], R = [];
  for (let b = 0; b < quanta; b++) {
    const o = [new Float32Array(128), new Float32Array(128)];
    p.process([], [o]);
    L.push(...o[0]); R.push(...o[1]);
  }
  return [L, R];
}
const maxDiff = (a, b) => a[0].reduce((m, v, i) => Math.max(m, Math.abs(v - b[0][i]), Math.abs(a[1][i] - b[1][i])), 0);
const peak = a => a[0].reduce((m, v, i) => Math.max(m, Math.abs(v), Math.abs(a[1][i])), 0);
(async () => {
  const header = it.slice();
  header[0x80] = 32;                        // channel 1 at volume 32 of 64
  header[0x41] = header[0x41] & 0x80;       // channel 2 panned hard left
  const a = await make();
  a.command({type: 'load', bytes: header.buffer});
  a.command({type: 'play', order: 0, row: 0});
  const want = render(a, 300);
  const b = await make();
  b.command({type: 'load', bytes: it.slice().buffer});
  let reads = 0;
  const read = b.preview.read.bind(b.preview);
  b.preview.read = (...x) => { reads++; return read(...x) };
  b.command({type: 'play', order: 0, row: 0});
  b.command({type: 'chvol', ch: 0, value: 0.5});
  b.command({type: 'chpan', ch: 1, value: -1});
  const got = render(b, 300), readsPlaying = reads;
  const c = await make();
  c.command({type: 'load', bytes: it.slice().buffer});
  c.command({type: 'play', order: 0, row: 0});
  const plain = render(c, 300);
  b.command({type: 'stop'});
  render(b, 20);
  const readsIdle = reads - readsPlaying;
  let ch = -1;
  b.onmsg = m => { if (m.type === 'note') ch = m.ch };
  b.command({type: 'note', id: 'k', ins: 0, note: 60});
  const note = render(b, 60);
  b.command({type: 'noteoff', ch, on: 'preview'});
  render(b, Math.ceil(2.5 * 48000 / 128));  // the 0.3 s sine's tail, then the quiet time
  console.log(JSON.stringify({level: peak(want), diff: maxDiff(got, want), plain_diff: maxDiff(plain, want),
    reads_playing: readsPlaying, reads_idle: readsIdle, preview_level: peak(note), asleep: b.previewQuiet === -1}));
})();
"""


PREVIEW_GAIN_JS = FADER_JS.split("(async () => {")[0] + r"""
const assert = require('assert/strict');
const scaled = (pcm, gain) => pcm.map(channel => channel.map(value => value * gain));
const close = (actual, expected) => assert.ok(maxDiff(actual, expected) < 1e-7);
const note = p => p.command({type:'note', id:'preview', ins:0, note:60, vol:0.6});
const cleanup = p => { p.pending?.song.free(); p.song.free(); p.preview.free(); };
async function loaded(gain) {
  const p = await make();
  p.command({type:'load', bytes:it.slice().buffer, gain});
  // Silence the pattern so the active case measures only its interactive note.
  for (let c = 0; c < p.song.channels; c++) p.command({type:'mute', ch:c, on:true});
  return p;
}
(async () => {
  const reference = await loaded(1);
  note(reference);
  const full = render(reference, 60);
  cleanup(reference);
  for (const gain of [0.25, 1, 0]) {
    for (const playing of [false, true]) {
      const p = await loaded(gain);
      if (playing) p.command({type:'play', order:0, row:0});
      note(p);
      close(render(p, 60), scaled(full, gain));
      cleanup(p);
    }
  }
  // During a keep/reload the current transport is still the old song, while
  // the stopped-preview copy already belongs to the newly loaded bundle.
  const p = await loaded(1);
  p.command({type:'play', order:0, row:0});
  render(p, 100);
  p.command({type:'load', bytes:it.slice().buffer, gain:0.25, keep:true, id:2});
  assert.ok(p.pending);
  assert.equal(p.song.outputGain, 1);
  assert.equal(p.preview.outputGain, 0.25);
  p.command({type:'stop'});
  note(p);
  close(render(p, 1), scaled(full.map(channel => channel.slice(0,128)), 0.25));
  // Replace the pending bundle, then prove neither the old transport gain nor
  // the replaced preview's gain is used for the latest stopped preview.
  p.command({type:'play'});
  render(p, 100);
  p.command({type:'load', bytes:it.slice().buffer, gain:0.25, keep:true, id:3});
  p.command({type:'load', bytes:it.slice().buffer, gain:0, keep:true, id:4});
  assert.ok(p.pending);
  assert.equal(p.preview.outputGain, 0);
  p.command({type:'stop'});
  note(p);
  assert.equal(peak(render(p, 60)), 0);
  const preview = p.preview;
  p.command({type:'load', bytes:it.slice().buffer, gain:NaN, id:5});
  assert.equal(p.preview, preview);
  assert.equal(p.preview.outputGain, 0);
  cleanup(p);
  console.log(JSON.stringify({unity_peak:peak(full), gains:[0.25,1,0], pending_reload:true,
    replaced_pending:true, invalid_reload_preserved:true}));
})().catch(e=>{console.error(e.stack);process.exitCode=1});
"""


# one channel, a two-second tone struck on rows 0 and 4 with NNA fade: after row 4 the first note fades under the second
FADE_SONG = """module: {title: F, tempo: 125, speed: 6, channels: [{name: A}]}
samples:
  1: {file: a.wav, name: A tone}
instruments:
  1: {name: Pad, sample: 1, nna: fade, fadeout: 8}
patterns:
  p1:
    rows: 8
    data: |
      00: C-5 01 ... ...
      01: ... .. ... ...
      02: ... .. ... ...
      03: ... .. ... ...
      04: C-5 01 ... ...
      05: ... .. ... ...
      06: ... .. ... ...
      07: ... .. ... ...
orders: [p1]
"""
# plays FADE_SONG from the start twice, once with the same song swapped in on row 5; prints the largest difference
# between the two from there on and the level there
FADE_JS = SWAP_JS.split("async function run")[0] + r"""
async function run(swap) {
  const p = await make(), out = [];
  p.command({type: 'load', bytes: it.slice().buffer});
  p.command({type: 'play', order: 0, row: 0});
  let at = -1;
  for (let b = 0; b < 700; b++) {
    if (at < 0 && p.song.position().row >= 5) { at = b; if (swap) p.command({type: 'load', bytes: it.slice().buffer, keep: true}) }
    const L = new Float32Array(128), R = new Float32Array(128);
    p.process([], [[L, R]]);
    if (at >= 0 && b < at + 200) out.push(...L);
  }
  return out;
}
(async () => {
  const a = await run(false), b = await run(true);
  let diff = 0, level = 0;
  for (let i = 0; i < a.length; i++) { diff = Math.max(diff, Math.abs(a[i] - b[i])); level = Math.max(level, Math.abs(a[i])) }
  console.log(JSON.stringify({diff, level}));
})();
"""


# the page's MIDI input run under node: its functions cut from gui.html, the tracker helpers and the DOM stubbed
MIDI_JS = r"""
const NOTES=['C-','C#','D-','D#','E-','F-','F#','G-','G#','A-','A#','B-'],noteTxt=n=>NOTES[n%12]+Math.floor(n/12),pad=n=>String(n).padStart(2,'0');
const cellOf=s=>{const [n,i,v,e]=s.split(' ');return {n,i,v,e}},cellText=p=>`${p.n} ${p.i} ${p.v} ${p.e}`;
const out=[],tabs=new Set(['t-pattern']),$=id=>({classList:{contains:c=>tabs.has(id)}}),document={querySelector:()=>null};
let S={song:{facts:{}}},EDIT=false,PAT={rows:[['... .. v20 A06'],['... .. ... ...'],['... .. ... ...']],order:0},CUR={o:0,row:0,ch:0},INS_SEL=null,W={data:null};
const LV={playing:false,pos:null,oi:-1},playbackOrders=()=>null;
const insNum=()=>3,putCell=(p,adv)=>out.push(['cell',cellText(p),adv,CUR.row]),lvNoteOn=(...a)=>out.push(['on',...a]),lvNoteOff=k=>out.push(['off',k]);
const faOn=()=>tabs.has('t-faust'),faMidi=d=>out.push(['faust',...d]);
PAGE
MIDI.on=true;midiMsg([0x90,60,127]);midiMsg([0x80,60,0]);          // preview only
EDIT=true;midiMsg([0x90,61,64]);midiMsg([0x90,61,0]);  // edit mode: entered with the velocity (OpenMPT curve: 64 is v17), note-on at 0 = note-off
MIDI.vel=false;midiMsg([0x90,72,10]);                 // velocity off: the volume column is left alone, full loudness
MIDI.on=false;midiMsg([0x90,50,100]);                 // MIDI switched off: nothing
MIDI.on=true;LV.playing=true;LV.oi=0;LV.pos={order:0,row:2};midiMsg([0x90,62,127]);  // recorded at the row playing, no step
LV.oi=1;midiMsg([0x90,63,127]);LV.playing=false;                      // another pattern plays: at the cursor
EDIT=false;MIDI.on=true;tabs.clear();tabs.add('t-smp');W.data={player:[4,60]};midiMsg([0x90,64,127]);  // the Samples tab plays the slot's player
EDIT=true;tabs.add('t-faust');midiMsg([0x90,60,100]);midiMsg([0xE0,0,64]);midiMsg([0x80,60,0]);  // the FAUST tab: all to Faust, no entry
MIDI.on=false;midiMsg([0x90,61,100]);                 // switched off: nothing there either
console.log(JSON.stringify(out));
"""


@unittest.skipUnless(NODE, "needs node")
class TestMidi(unittest.TestCase):
    def test_midi_input(self):
        page = (ROOT / "vulturetracker" / "gui.html").read_text(encoding="utf-8")
        a, b = page.index("function enterNote("), page.index("if(MIDI.on)midiStart();else renderMidi();")
        code = '\n'.join((page[page.index('function liveSourceRow('):].splitlines()[0],
                          page[page.index('function selectedScoreHead('):page.index('async function selectScorePosition(')], page[a:b]))
        with tempfile.TemporaryDirectory() as tmp:
            js = Path(tmp) / "midi.js"
            js.write_text(MIDI_JS.replace("PAGE", code), encoding="utf-8")
            result = subprocess.run([NODE, str(js)], capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            out = json.loads(result.stdout)
        self.assertEqual(out, [["on", "m60", None, 60, 1], ["off", "m60"],
                               ["cell", "C#5 03 v17 A06", True, 0], ["on", "m61", None, 61, 64 / 127], ["off", "m61"],
                               ["cell", "C-6 03 v20 A06", True, 0], ["on", "m72", None, 72, 1],
                               ["cell", "D-5 03 ... ...", False, 2], ["on", "m62", None, 62, 1],
                               ["cell", "D#5 03 ... ...", True, 2], ["on", "m63", None, 63, 1],
                               ["on", "m64", 4, 64, 1],
                               ["faust", 0x90, 60, 100], ["faust", 0xE0, 0, 64], ["faust", 0x80, 60, 0]])

    def test_record_quantize(self):
        """OpenMPT's QuantizeRow with QUANT 4 on a 16-row pattern played live: the nearest multiple of 4 (a tie goes
        later), a cell holding a note pushes the new one a row on, past the end to the next order's pattern row 0 (with
        its own grace check), and to the last row when no order follows. QUANT 0 enters at the row playing."""
        page = (ROOT / "vulturetracker" / "gui.html").read_text(encoding="utf-8")
        a, b = page.index("function enterNote("), page.index("if(MIDI.on)midiStart();else renderMidi();")
        code = '\n'.join((page[page.index('function liveSourceRow('):].splitlines()[0],
                          page[page.index('function selectedScoreHead('):page.index('async function selectScorePosition(')], page[a:b]))
        js_text = r"""
const NOTES=['C-','C#','D-','D#','E-','F-','F#','G-','G#','A-','A#','B-'],noteTxt=n=>NOTES[n%12]+Math.floor(n/12),pad=n=>String(n).padStart(2,'0');
const cellOf=s=>{const [n,i,v,e]=s.split(' ');return {n,i,v,e}},cellText=p=>`${p.n} ${p.i} ${p.v} ${p.e}`;
const out=[],Q={value:'4'},$=id=>id==='lv-quant'?Q:{classList:{contains:()=>false}},document={querySelector:()=>null};
const blank=n=>Array.from({length:n},()=>['... .. ... ...']);
const other=blank(8);other[0][0]='C-4 01 ... ...';
let S={song:{facts:{orders:[{index:0},{index:5}]}}},EDIT=true,PAT={idx:0,rows:blank(16),order:0},CUR={o:0,row:0,ch:0};
PAT.rows[8][0]='E-5 01 ... ...';
let lvPatLoop=false;const LV={playing:true,pos:{row:0},oi:0},playbackOrders=()=>null,insNum=()=>3,putCell=(p,adv)=>out.push(['cell',CUR.row,cellText(p)]);
const patEdit=c=>out.push(['edit',PAT.idx,c]),editPost=b=>out.push(['post',b.pattern,b.cells]),patRows=async i=>i===PAT.idx?PAT.rows:other;
PAGE
(async()=>{
  for(const r of [5,6,9,15]){LV.pos.row=r;await enterNote(62,null)}  // 4; 8 (a tie) holds a note: 9; 8; past the end
  lvPatLoop=true;LV.pos.row=14;await enterNote(65,null);lvPatLoop=false;    // F6 loops the pattern: its own row 0
  S.song.facts.orders=[{index:0}];LV.pos.row=15;await enterNote(63,null);  // no next order: the last row
  Q.value='0';LV.pos.row=5;await enterNote(64,null);                       // off: the row playing
  console.log(JSON.stringify(out));
})();
"""
        with tempfile.TemporaryDirectory() as tmp:
            js = Path(tmp) / "quant.js"
            js.write_text(js_text.replace("PAGE", code), encoding="utf-8")
            result = subprocess.run([NODE, str(js)], capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            out = json.loads(result.stdout)
        d = "D-5 03 ... ..."
        self.assertEqual(out, [["edit", 0, [{"row": 4, "ch": 0, "cell": d}]],
                               ["edit", 0, [{"row": 9, "ch": 0, "cell": d}]],
                               ["edit", 0, [{"row": 9, "ch": 0, "cell": d}]],
                               ["post", 5, [{"row": 1, "ch": 0, "cell": d}]],
                               ["edit", 0, [{"row": 0, "ch": 0, "cell": "F-5 03 ... ..."}]],
                               ["edit", 0, [{"row": 15, "ch": 0, "cell": "D#5 03 ... ..."}]],
                               ["cell", 5, "E-5 03 ... ..."]])


if __name__ == "__main__":
    unittest.main()
