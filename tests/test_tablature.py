"""Exact score source, ownership, and rejected transactions; no browser/audio needed."""
import copy
from fractions import Fraction
import json
import unittest

import yaml

from vulturetracker import tablature as tab
from vulturetracker.model import Cell, Pattern, Module, NOTE_OFF
from vulturetracker.notation import format_cell, parse_cell


def beat(identity, at, notes, value=4, tuplet=None, track='guitar', voice=0):
    return {'id': identity, 'track': track, 'voice': voice, 'at': at,
            'written': {'value': value, 'dots': 0, 'tuplet': tuplet or [1, 1]}, 'notes': notes}


def note(identity, pitch, string=None, fret=None):
    out = {'id': identity, 'pitch': pitch}
    if string is not None:
        out.update(string=string, fret=fret)
    return out


def fixture():
    song = {'module': {'speed': 2, 'tempo': 120, 'channels': 7},
            'patterns': {'A': {'rows': 48, 'data': ''}, 'B': {'rows': 48, 'data': ''}},
            'orders': ['A', 'B'], 'samples': {1: {'file': 'original.wav'}},
            'score': {'version': 1, 'tracks': {
                'guitar': {'tuning': [64, 59, 55, 50, 45, 40], 'channels': list(range(6)), 'instrument': 1},
                'bass': {'tuning': [40], 'channels': [6], 'instrument': 1}},
                'order_ids': ['oa', 'ob'], 'patterns': {
                    'A': {'row_step': [1, 12], 'beats': [
                        beat('chord', [0, 1], [note('c', 60, 2, 1), note('e', 64, 1, 0), note('g', 67, 3, 12)]),
                        beat('t1', [1, 1], [note('t1n', 64, 1, 0)], 8, [3, 2]),
                        beat('t2', [4, 3], [note('t2n', 65, 1, 1)], 8, [3, 2]),
                        beat('t3', [5, 3], [note('t3n', 67, 1, 3)], 8, [3, 2]),
                        beat('rest', [2, 1], []),
                        beat('tail', [7, 2], [note('tailn', 64, 1, 0)], 8),
                        beat('bass', [0, 1], [note('bassn', 40, 1, 0)], 2, track='bass')]},
                    'B': {'row_step': [1, 12], 'beats': [beat('head', [0, 1], [note('headn', 64, 1, 0)], 8)]}},
                'ties': [{'from': {'occurrence': 'oa', 'note': 'tailn'},
                          'to': {'occurrence': 'ob', 'note': 'headn'}}]}}
    raw = [Pattern(name, [[Cell() for _ in range(7)] for _ in range(48)]) for name in ('A', 'B')]
    raw[0].rows[0][1].effect, raw[0].rows[0][1].param = 24, 64  # X40: unrelated panning
    return song, raw


def plan_fixture():
    song, raw = fixture()
    raw[0].rows[0][1].effect = raw[0].rows[0][1].param = 0
    return song, raw


class TestRepeatedBoundaryRelease(unittest.TestCase):
    def test_attack_or_song_start_is_safe_but_different_predecessor_still_refuses(self):
        for attack in ('score', 'raw', 'none', 'ambiguous'):
            song, raw = plan_fixture()
            song['orders'] = ['A', 'A']
            song['score']['order_ids'] = ['oa', 'oa2']
            song['score']['ties'] = []
            song['score']['patterns'] = {'A': {'row_step': [1, 12], 'beats': [
                beat('tail', [3, 1], [note('tail-n', 64, 1, 0)])]}}
            if attack == 'score':
                song['score']['patterns']['A']['beats'].insert(0, beat('head', [0, 1], [note('head-n', 67, 1, 3)]))
            elif attack == 'raw':
                raw[0].rows[0][0] = Cell(note=67, instrument=1)
                raw[0].rows[12][0] = Cell(note=NOTE_OFF)
            elif attack == 'ambiguous':
                song['orders'] = ['A', 'A', 'B', 'A']
                song['score']['order_ids'] = ['oa', 'oa2', 'ob', 'oa3']
                raw[1].rows[36][0] = Cell(note=55, instrument=1)
            before = copy.deepcopy((song, raw))
            with self.subTest(attack=attack):
                if attack == 'ambiguous':
                    with self.assertRaisesRegex(ValueError, 'occurrence-dependent boundary release'):
                        tab.project_score(song, raw)
                else:
                    projected = tab.project_score(song, raw)
                    self.assertEqual(projected.patterns[0].rows[0][0].note, NOTE_OFF if attack == 'none' else 67)
                    self.assertEqual(projected.patterns[0].rows[36][0].note, 64)
                self.assertEqual((song, raw), before)


class TestWholeBeatPaste(unittest.TestCase):
    def test_implicit_source_silence_matches_explicit_and_keeps_selection_exact(self):
        for cross in (False, True):
            from tools.tg_edit_oracle import clipboard_replace_song
            song = clipboard_replace_song('clipboard replace explicit source rest')
            if cross:
                for name in ('m1', 'm2'):
                    song['score']['patterns'][name]['beats'] = copy.deepcopy(
                        clipboard_replace_song('clipboard replace one voice over two')['score']['patterns']['m1']['beats'])
                song['score']['patterns']['m1']['beats'][3]['notes'] = []
                song['score']['patterns']['m2']['beats'][0]['notes'] = []
            raw = [Pattern(name, [[Cell() for _ in song['module']['channels']]
                                 for _ in range(spec['rows'])]) for name, spec in song['patterns'].items()]
            names = ['m1', 'm2'] if cross else ['m1']
            selection = []
            for i, name in enumerate(names):
                beats = song['score']['patterns'][name]['beats']
                ids = [b['id'] for b in beats if (Fraction(*b['at']) >= 2 if i == 0 and cross else
                       Fraction(*b['at']) <= (1 if cross else 2))]
                selection.append(dict(occurrence=song['score']['order_ids'][i], beats=ids))
            explicit = tab.capture_score_clipboard(song, selection=selection, raw_patterns=raw)
            implicit = copy.deepcopy(song)
            for entry, name in zip(selection, names):
                beats = implicit['score']['patterns'][name]['beats']
                beats[:] = [b for b in beats if b['notes']]
                entry['beats'] = [identity for identity in entry['beats'] if any(b['id'] == identity for b in beats)]
            before = copy.deepcopy(implicit)
            captured = tab.capture_score_clipboard(implicit, selection=selection, raw_patterns=raw, complete_silence=True)
            def musical(clip):
                return sorted((b['at'], b['voice'], b['written'], [(n['pitch']) for n in b['notes']])
                              for b in clip['beats'] + clip.get('implicit_rests', []))
            with self.subTest(cross=cross):
                self.assertEqual(musical(captured), musical(explicit))
                self.assertEqual(implicit, before)
                if not cross:
                    local = tab.capture_score_clipboard(implicit, 'm1', selection[0]['beats'], complete_silence=True)
                    self.assertEqual(musical(local), musical(explicit))
        song, raw = self.fixture()
        # Skipping an authored note is a sparse selection, not implicit silence.
        clip = tab.capture_score_clipboard(song, 'A', ['0b0', '0b2'], complete_silence=True)
        self.assertEqual(len(clip['beats']), 2)
        self.assertNotIn('implicit_rests', clip)

    def test_implicit_rests_follow_remapping_and_leave_span_copy_sparse(self):
        song, raw = self.fixture()
        beats = song['score']['patterns']['A']['beats']
        beats[:] = [b for b in beats if b['voice'] == 0 and b['at'] in ([0, 1], [2, 1])]
        beats[-1]['written']['value'] = 2
        clip = tab.capture_score_clipboard(song, 'A', ['0b0', '0b2'], complete_silence=True)
        before = copy.deepcopy((song, clip))
        result = tab.paste_score_clipboard(song, Module(patterns=raw), 1, 0, clip, 'ob', across=True,
                                          mode='tg_replace', track_map={'guitar': 'guitar'}, voice_map={'0': 1})
        target = result['score']['patterns']['B']['beats']
        self.assertEqual(sorted((b['at'], b['voice']) for b in target if b['notes']), [([0, 1], 1), ([2, 1], 1)])
        sparse = dict(clip); sparse.pop('implicit_rests')
        self.assertEqual(tab.paste_score_clipboard(song, Module(patterns=raw), 1, 0, clip, 'ob', across=True, replace=True),
                         tab.paste_score_clipboard(song, Module(patterns=raw), 1, 0, sparse, 'ob', across=True, replace=True))
        invalid = copy.deepcopy(clip); invalid['implicit_rests'][0]['notes'] = [note('bad', 64, 1, 0)]
        with self.assertRaisesRegex(ValueError, 'implicit rests'):
            tab.paste_score_clipboard(song, Module(patterns=raw), 1, 0, invalid, 'ob', across=True, mode='tg_replace')
        self.assertEqual((song, clip), before)

    def fixture(self):
        song, raw = plan_fixture()
        song['score']['ties'] = []
        for name in ('A', 'B'):
            song['score']['patterns'][name]['beats'] = [
                beat(f'{v}b{i}', [i, 1], [note(f'{v}n{i}', 64+i if v == 0 else 40+i,
                                               1 if v == 0 else 6, i)], voice=v)
                for i in range(4) for v in range(2)]
        song['score']['measures'] = [dict(id=name, meter=[4,4], **{
            'from': dict(occurrence=oid, at=[0,1]), 'to': dict(occurrence=oid, at=[4,1])})
            for name, oid in (('A','oa'),('B','ob'))]
        return song, raw

    def paste(self, song, raw, ids, row=0, **options):
        clip = tab.capture_score_clipboard(song, 'A', ids, 'oa')
        return tab.paste_score_clipboard(song, Module(patterns=raw), 1, row, clip, 'ob',
                                        across=True, mode='tg_replace', **options)

    def test_both_voices_whole_notes_metadata_and_exact_span_alternative(self):
        song, raw = self.fixture()
        source = song['score']['patterns']['A']['beats'][0]
        source['written']['value'] = 8
        source.update(text='Copied annotation', stem='up')
        song['score']['patterns']['B']['beats'] = [
            beat(f'{v}b{i}', [i,1], [note(f'{v}n{i}',64+i if v==0 else 40+i,1 if v==0 else 6,i)],2,voice=v)
            for i in (0,2) for v in range(2)]
        before = copy.deepcopy(song)
        result = self.paste(song, raw, ['0b0'])
        sounding = [b for b in result['score']['patterns']['B']['beats'] if b['notes']]
        self.assertEqual([(b['voice'],b['at']) for b in sounding],[(0,[2,1]),(1,[2,1]),(0,[0,1])])
        copied = next(b for b in sounding if b['at']==[0,1])
        self.assertEqual((copied['text'],copied['stem'],copied['written']['value']),('Copied annotation','up',8))
        self.assertEqual(song,before)
        clip = tab.capture_score_clipboard(song,'A',['0b0'],'oa')
        span = tab.paste_score_clipboard(song,Module(patterns=raw),1,0,clip,'ob',across=True,replace=True)
        self.assertTrue(any(b['voice']==1 and b['at']==[0,1] and b['notes'] for b in span['score']['patterns']['B']['beats']))
        self.assertTrue(any(b['voice']==0 and b['at']==[1,2] and b['notes'] for b in span['score']['patterns']['B']['beats']))

    def test_unequal_cohorts_advance_and_select_actual_new_attacks(self):
        song, raw = self.fixture()
        beats = song['score']['patterns']['A']['beats']
        beats[:] = [b for b in beats if b['voice']==0 or b['at'] in ([0,1],[2,1])]
        for b in beats:
            if b['voice']==1:b['written']['value']=2
        report = {}
        result = self.paste(song,raw,['0b0','1b0','0b1'],report=report)
        target = result['score']['patterns']['B']['beats']
        copied = [b for b in target if b['id'] in report['selection']['beats']]
        self.assertEqual([(b['voice'],b['at']) for b in copied],[(0,[0,1]),(1,[0,1]),(0,[2,1])])
        self.assertFalse(any(b['notes'] and b['voice']==1 and b['at']==[2,1] for b in target))
        self.assertEqual(report['selection']['at'],[0,1])

    def test_implicit_destination_rests_ties_and_atomic_safety(self):
        song,raw=self.fixture()
        song['score']['patterns']['B']['beats']=[]
        report={};result=self.paste(song,raw,['0b0'],report=report)
        self.assertEqual(len([b for b in result['score']['patterns']['B']['beats'] if b['notes']]),1)
        self.assertEqual(len(report['selection']['beats']),1)
        for failure in ('overflow','approved','shared','bad tie'):
            source,raw=self.fixture(); options={}; row=0
            if failure=='overflow':source['score']['patterns']['A']['beats']=[beat('whole',[0,1],[note('wn',64,1,0)],1)];row=36
            if failure=='approved':source['patterns']['B']['approved']=True
            if failure=='shared':source['orders'].append('B');source['score']['order_ids'].append('ob2')
            ids=['whole'] if failure=='overflow' else ['0b0']
            clip=tab.capture_score_clipboard(source,'A',ids,'oa')
            if failure=='bad tie':clip['ties']=[{'from':'0n0','to':'missing'}]
            before=copy.deepcopy(source)
            with self.subTest(failure=failure),self.assertRaises(ValueError):
                tab.paste_score_clipboard(source,Module(patterns=raw),1,row,clip,'ob',across=True,mode='tg_replace')
            self.assertEqual(source,before)

    def test_internal_ties_and_next_available_destination(self):
        song,raw=self.fixture()
        source=song['score']['patterns']['A']['beats']
        tail=next(b for b in source if b['id']=='0b1')['notes'][0]
        tail.update(pitch=64,fret=0)
        song['score']['ties']=[{'from':dict(occurrence='oa',note='0n0'),'to':dict(occurrence='oa',note='0n1')}]
        report={};result=self.paste(song,raw,['0b0','0b1'],row=13,report=report)
        self.assertEqual(report['selection']['at'],[2,1])
        copied=[t for t in result['score']['ties'] if t['from']['occurrence']=='ob']
        self.assertEqual(len(copied),1)
        self.assertEqual((copied[0]['from']['note'],copied[0]['to']['note']),('copy_0n0','copy_0n1'))
        self.assertEqual(len(result['score']['ties']),2)


class TestMatrixEntry(unittest.TestCase):
    def fixture(self):
        song, raw = plan_fixture()
        song['score']['ties'] = []
        song['score']['patterns']['A']['beats'] = [beat('rest', [0, 1], [], 1)]
        song['score']['patterns']['B']['beats'] = []
        return song, raw

    def entry(self, song, raw, at, value=4, **options):
        return tab.score_command(song, raw, dict(action='matrix_entry', occurrence='oa', track='guitar',
            voice=0, at=at, pitch=67, written=dict(value=value), **options))

    def test_free_anchor_shrink_growth_and_original_cohort_audition(self):
        song,raw=self.fixture()
        candidate,result=self.entry(song,raw,[27,10],free=True,fit=True)
        placed=next(b for b in candidate['score']['patterns']['A']['beats'] if b['notes'])
        self.assertEqual((placed['at'],placed['written']['value']),([0,1],4))
        self.assertEqual([n['pitch'] for n in result['audition']],[67])
        song['score']['patterns']['A']['beats']=[beat('chord',[0,1],[dict(note('n',64,1,0),velocity=0)]),
            beat('peer',[0,1],[dict(note('p',59,2,0),velocity=63)],2,voice=1),
            beat('next',[1,1],[note('nextn',65,1,1)])]
        candidate,result=self.entry(song,raw,[7,10],value=8,free=True)
        chord=next(b for b in candidate['score']['patterns']['A']['beats'] if b['id']=='chord')
        self.assertEqual([n['pitch'] for n in chord['notes']],[64,67]);self.assertEqual(chord['at'],[0,1])
        self.assertEqual(sorted(n['pitch'] for n in result['audition']),[59,64,67])
        self.assertEqual(next(n['velocity'] for n in result['audition'] if n['pitch']==64),0)
        normal,report=self.entry(song,raw,[7,10],value=8)
        self.assertEqual(sorted(n['pitch'] for n in report['audition']),[59,64])
        self.assertEqual(report['selection']['at'],[1,2])
        before=copy.deepcopy(song)
        with self.assertRaisesRegex(ValueError,'overlaps'):
            self.entry(song,raw,[7,10],value=2,free=True,fit=True)
        self.assertEqual(song,before)
        song,raw=self.fixture();song['score']['patterns']['A']['beats']=[beat('last',[3,1],[])]
        candidate,result=self.entry(song,raw,[37,10],value=2,free=True)
        self.assertEqual(candidate['patterns']['A']['rows'],60)
        self.assertEqual(result['selection']['at'],[3,1])

    def test_free_gap_and_absent_voice_audition_are_immutable(self):
        song,raw=self.fixture();song['score']['patterns']['A']['beats']=[]
        before=copy.deepcopy(song)
        candidate,result=self.entry(song,raw,[27,10],free=True)
        self.assertEqual(candidate,before);self.assertEqual(result['matrix'],'absent_voice')
        self.assertEqual(result['audition'],[dict(pitch=67,instrument=1)])
        candidate,result=tab.score_command(song,raw,dict(action='matrix_entry',occurrence='oa',track='guitar',
            voice=1,at=[0,1],pitch=67,written=dict(value=4)))
        self.assertEqual(candidate,before);self.assertEqual(result['audition'][0]['pitch'],67)

    def test_rest_duration_cells_dots_triplets_and_implicit_silence(self):
        for authored in (True, False):
            for written, click, expected, duration in (
                    (dict(value=4), [27,10], [2,1], Fraction(1)),
                    (dict(value=8), [17,10], [3,2], Fraction(1,2)),
                    (dict(value=4,dots=1), [27,10], [3,2], Fraction(3,2)),
                    (dict(value=4,dots=1), [37,10], [3,1], Fraction(1)),
                    (dict(value=8,tuplet=[3,2]), [17,10], [5,3], Fraction(1,3))):
                with self.subTest(authored=authored, written=written, click=click):
                    song, raw = self.fixture()
                    if not authored: song['score']['patterns']['A']['beats'] = []
                    before = copy.deepcopy((song, raw))
                    candidate, report = tab.score_command(song, raw, dict(action='matrix_entry', occurrence='oa',
                        track='guitar', voice=0, at=click, pitch=67, written=written))
                    placed = next(b for b in candidate['score']['patterns']['A']['beats'] if b['notes'])
                    self.assertEqual(placed['at'], expected)
                    self.assertEqual(tab.duration_quarters(placed['written']), duration)
                    self.assertEqual(placed['notes'][0]['fret'], 3)
                    self.assertEqual(report['selection']['at'], expected)
                    self.assertEqual((song, raw), before)

    def test_chord_resize_retarget_toggle_capo_and_absent_voice(self):
        song, raw = self.fixture()
        beats = song['score']['patterns']['A']['beats'] = [
            beat('chord',[0,1],[note('e',64,1,0),note('b',59,2,0)]),
            beat('next',[1,1],[note('nextn',65,1,1)]), beat('rest',[2,1],[],2)]
        for value, at, chord_duration in ((4,[0,1],1),(8,[1,2],Fraction(1,2))):
            result, report = self.entry(song,raw,[7,10],value)
            chord = next(b for b in result['score']['patterns']['A']['beats'] if b['id']=='chord')
            self.assertEqual(tab.duration_quarters(chord['written']),chord_duration)
            self.assertEqual(report['selection']['at'],at)
            added = next(n for b in result['score']['patterns']['A']['beats'] for n in b['notes'] if n['id']=='matrix_note')
            self.assertEqual((added['string'],added['fret']),(3,12))
            self.assertEqual(next(b for b in result['score']['patterns']['A']['beats'] if b['id']=='next'),beats[1])
        with self.assertRaisesRegex(ValueError,'overlaps sounding'):
            self.entry(song,raw,[7,10],2)
        fitted, report = self.entry(song,raw,[7,10],2,fit=True)
        self.assertEqual(next(b for b in fitted['score']['patterns']['A']['beats'] if b['id']=='next')['at'],[2,1])
        self.assertEqual(report['selection']['at'],[0,1])
        song, raw = self.fixture()
        song['score']['patterns']['A']['beats'].append(beat('lower',[0,1],[note('peer',67,1,3)],voice=1))
        deleted, report = self.entry(song,raw,[7,10])
        self.assertEqual(report['matrix'],'deleted')
        self.assertEqual(report['selection']['voice'],1)
        self.assertFalse(next(b for b in deleted['score']['patterns']['A']['beats'] if b['id']=='lower')['notes'])
        song,raw=self.fixture();song['score']['tracks']['guitar']['capo']=2
        result,_=self.entry(song,raw,[27,10])
        self.assertEqual(next(b for b in result['score']['patterns']['A']['beats'] if b['notes'])['notes'][0]['fret'],1)
        absent, report=tab.score_command(song,raw,dict(action='matrix_entry',occurrence='oa',track='guitar',voice=1,
            at=[27,10],pitch=67,written=dict(value=4)))
        self.assertEqual(absent,song);self.assertEqual(report['matrix'],'absent_voice')

    def test_atomic_peer_collision_annotations_fret_and_ties(self):
        for case in ('peer','annotation','fret','tie','approved','outside'):
            with self.subTest(case=case):
                song,raw=self.fixture();beats=song['score']['patterns']['A']['beats'];at=[12,10];value=4
                if case=='peer':beats.append(beat('peer',[1,1],[note('p',66,1,2)],voice=1))
                if case=='annotation':beats[0]['text']='Keep this rest annotation'
                if case=='fret':song['score']['tracks']['guitar']['max_fret']=2
                if case=='approved':song['patterns']['A']['approved']=True
                if case=='outside':at=[4,1]
                if case=='tie':
                    beats[:]=[beat('one',[0,1],[note('n1',64,1,0)]),beat('two',[1,1],[note('n2',64,1,0)])]
                    song['score']['ties']=[{'from':dict(occurrence='oa',note='n1'),'to':dict(occurrence='oa',note='n2')}]
                    at=[7,10];value=8
                before=copy.deepcopy((song,raw))
                with self.assertRaises(ValueError):self.entry(song,raw,at,value)
                self.assertEqual((song,raw),before)


class TestPortableScoreClipboard(unittest.TestCase):
    def destination(self, source, *, tuning=None, capo=0, max_fret=29, percussion=False):
        song = copy.deepcopy(source)
        song['samples'] = {2: {'file': 'destination.wav'}}
        track = dict(tuning=tuning or [62, 57, 53, 48, 43, 38], capo=capo, max_fret=max_fret,
                     channels=list(range(len(tuning or [62, 57, 53, 48, 43, 38]))), instrument=2)
        if percussion:
            track['midi'] = {'bank': 128, 'program': 0}
        song['score']['tracks'] = {'part': track}
        song['score']['ties'] = []
        for spec in song['score']['patterns'].values():
            spec['beats'] = []
        raw = [Pattern(name, [[Cell() for _ in range(7)] for _ in range(48)]) for name in ('A', 'B')]
        return song, raw

    def test_cross_song_pitch_capo_grace_destination_routing_and_portable_json(self):
        source, _ = fixture()
        original = source['score']['patterns']['A']['beats'][1]['notes'][0]
        original.update(instrument=1, channel=0, grace=dict(fret=1, value=16, velocity=70,
                                                         transition='none', on_beat=False, dead=False))
        clip = json.loads(json.dumps(tab.capture_score_clipboard(source, 'A', ['t1', 't2', 't3'])))
        song, raw = self.destination(source, capo=1)
        before = copy.deepcopy((source, song, clip, raw))
        result = tab.paste_score_clipboard(song, Module(patterns=raw), 0, 0, clip, 'oa',
                                          track_map={'guitar': 'part'})
        notes = [b['notes'][0] for b in result['score']['patterns']['A']['beats']]
        self.assertEqual([n['pitch'] for n in notes], [64, 65, 67])
        self.assertEqual([(n['string'], n['fret']) for n in notes], [(1, 1), (1, 2), (1, 4)])
        self.assertEqual(notes[0]['grace']['fret'], 2)
        self.assertTrue(all('instrument' not in n and 'channel' not in n for n in notes))
        plan = tab.playback_plan(result, raw)
        self.assertTrue(all(n['instrument'] == 2 for n in plan['events'] if n['type'] == 'note_on'))
        self.assertEqual((source, song, clip, raw), before)

    def test_cross_track_ties_voices_and_boundary_split(self):
        source, source_raw = fixture()
        clip = tab.capture_score_clipboard(source, selection=[dict(occurrence='oa', beats=['tail']),
            dict(occurrence='ob', beats=['head'])], raw_patterns=source_raw)
        song, raw = self.destination(source, tuning=[40], capo=2)
        result = tab.paste_score_clipboard(song, Module(patterns=raw), 0, 45, clip, 'oa', across=True,
                                          track_map={'guitar': 'part'})
        notes = [n for p in result['score']['patterns'].values() for b in p['beats'] for n in b['notes']]
        self.assertEqual(len(notes), 3)
        self.assertTrue(all((n['pitch'], n['string'], n['fret']) == (64, 1, 22) for n in notes))
        self.assertEqual(len(result['score']['ties']), 2)
        self.assertEqual(sum(e['type'] == 'note_on' for e in tab.playback_plan(result, raw)['events']), 1)

    def test_both_voices_allocate_distinct_destination_strings(self):
        source, _ = fixture()
        source['score']['patterns']['A']['beats'].append(beat('peer', [0, 1], [note('peer_n', 40, 6, 0)], voice=1))
        clip = tab.capture_score_clipboard(source, 'A', ['chord', 'peer'])
        song, raw = self.destination(source)
        result = tab.paste_score_clipboard(song, Module(patterns=raw), 0, 0, clip, 'oa',
                                          track_map={'guitar': 'part'})
        beats = result['score']['patterns']['A']['beats']
        self.assertEqual({b['voice'] for b in beats}, {0, 1})
        self.assertEqual(len({n['string'] for b in beats for n in b['notes']}), 4)
        self.assertEqual(sorted(n['pitch'] for b in beats for n in b['notes']), [40, 60, 64, 67])
        tab.project_score(result, raw)

    def test_impossible_pitch_chord_and_kind_refuse_without_mutation(self):
        source, _ = fixture()
        clip = tab.capture_score_clipboard(source, 'A', ['chord'])
        for tuning, top, percussion in (([40], 29, False), ([90], 4, False), ([0] * 6, 29, True)):
            song, raw = self.destination(source, tuning=tuning, max_fret=top, percussion=percussion)
            before = copy.deepcopy((song, raw, clip))
            with self.assertRaisesRegex(ValueError, 'cannot place|pitched/percussion'):
                tab.paste_score_clipboard(song, Module(patterns=raw), 0, 0, clip, 'oa', track_map={'guitar': 'part'})
            self.assertEqual((song, raw, clip), before)

    def test_percussion_preserves_keys_and_uses_destination_instrument(self):
        source, _ = fixture()
        source['score']['tracks']['guitar'].update(tuning=[0] * 6, midi={'bank': 128, 'program': 0})
        source['score']['patterns']['A']['beats'] = [beat('drums', [0, 1], [
            dict(note('kick', 36, 1, 36), instrument=1, channel=0), note('hat', 42, 2, 42)])]
        source['score']['patterns']['B']['beats'] = []; source['score']['ties'] = []
        clip = tab.capture_score_clipboard(source, 'A', ['drums'])
        song, raw = self.destination(source, tuning=[0, 0], percussion=True)
        result = tab.paste_score_clipboard(song, Module(patterns=raw), 0, 0, clip, 'oa', track_map={'guitar': 'part'})
        notes = result['score']['patterns']['A']['beats'][0]['notes']
        self.assertEqual([n['pitch'] for n in notes], [36, 42])
        self.assertTrue(all('channel' not in n and 'instrument' not in n for n in notes))
        self.assertEqual({n['string'] for n in notes}, {1, 2})

    def test_legacy_same_track_retains_explicit_routing_and_metadata(self):
        song, raw = fixture()
        song['score']['patterns']['A']['beats'][1]['notes'][0].update(channel=0, instrument=1)
        clip = tab.capture_score_clipboard(song, 'A', ['t1'])
        result = tab.paste_score_clipboard(song, Module(patterns=raw), 1, 12, clip, 'ob')
        pasted = result['score']['patterns']['B']['beats'][-1]['notes'][0]
        self.assertEqual((pasted['channel'], pasted['instrument']), (0, 1))
        self.assertEqual(pasted['pitch'], 64)

    def test_mapping_requires_complete_unambiguous_portable_metadata(self):
        source, _ = fixture()
        clip = tab.capture_score_clipboard(source, 'A', ['chord'])
        song, raw = self.destination(source)
        for mapping in ({}, {'guitar': 'missing'}, {'guitar': 'part', 'bass': 'part'}):
            with self.assertRaisesRegex(ValueError, 'track_map'):
                tab.paste_score_clipboard(song, Module(patterns=raw), 0, 0, clip, 'oa', track_map=mapping)
        inconsistent = copy.deepcopy(clip)
        inconsistent['track_kinds']['guitar'] = 'percussion'
        with self.assertRaisesRegex(ValueError, 'kind and geometry disagree'):
            tab.paste_score_clipboard(song, Module(patterns=raw), 0, 0, inconsistent, 'oa', track_map={'guitar': 'part'})
        segment_clip = copy.deepcopy(clip)
        segment_clip.pop('track_kinds')  # Portable measure segments use track_specs as their kind authority.
        adapted = tab.remap_score_clipboard(song, segment_clip, {'guitar': 'part'})
        self.assertEqual(adapted['track_kinds'], {'part': 'pitched'})
        clip.pop('track_specs')
        with self.assertRaisesRegex(ValueError, 'copy the phrase again'):
            tab.paste_score_clipboard(song, Module(patterns=raw), 0, 0, clip, 'oa', track_map={'guitar': 'part'})

    def test_trill_negative_capo_and_harmonic_pitch_are_preserved(self):
        source, _ = fixture()
        source['score']['patterns']['A']['beats'][1]['notes'][0].update(trill={'fret': 2, 'value': 16}, velocity=95)
        clip = tab.capture_score_clipboard(source, 'A', ['t1'])
        song, raw = self.destination(source, tuning=[64, 59, 55, 50, 45, 40], capo=-1)
        pasted = tab.paste_score_clipboard(song, Module(patterns=raw), 0, 0, clip, 'oa', track_map={'guitar': 'part'})
        n = pasted['score']['patterns']['A']['beats'][0]['notes'][0]
        self.assertEqual((n['pitch'], n['fret'], n['trill']['fret']), (64, 1, 3))
        source['score']['patterns']['A']['beats'] = [beat('harmonic', [0, 1], [
            dict(note('hn', 52, 6, 12), harmonic={'type': 'natural'}, velocity=95)])]
        source['score']['ties'] = []
        clip = tab.capture_score_clipboard(source, 'A', ['harmonic'])
        with self.assertRaisesRegex(ValueError, 'cannot place'):
            tab.paste_score_clipboard(song, Module(patterns=raw), 0, 0, clip, 'oa', track_map={'guitar': 'part'})
        song['score']['tracks']['part']['tuning'][-1] = 41
        pasted = tab.paste_score_clipboard(song, Module(patterns=raw), 0, 0, clip, 'oa', track_map={'guitar': 'part'})
        self.assertEqual(pasted['score']['patterns']['A']['beats'][0]['notes'][0]['fret'], 12)

    def test_swapping_track_names_does_not_remap_a_phrase_twice(self):
        source, _ = fixture()
        source['score']['patterns']['A']['beats'] = [beat('g', [0, 1], [note('gn', 52, 6, 12)]),
            beat('b', [1, 1], [note('bn', 48, 1, 8)], track='bass')]
        source['score']['ties'] = []
        clip = tab.capture_score_clipboard(source, 'A', ['g', 'b'])
        remapped = tab.remap_score_clipboard(source, clip, {'guitar': 'bass', 'bass': 'guitar'})
        self.assertEqual([b['track'] for b in remapped['beats']], ['bass', 'guitar'])
        self.assertEqual([b['notes'][0]['pitch'] for b in remapped['beats']], [52, 48])
        self.assertEqual([b['track'] for b in clip['beats']], ['guitar', 'bass'])


class TestCrossMeasureClipboard(unittest.TestCase):
    def fixture(self):
        song, raw = fixture()
        for name in ('C', 'D', 'E', 'F'):
            song['patterns'][name] = {'rows': 48, 'data': ''}
            song['orders'].append(name)
            song['score']['order_ids'].append('o' + name.lower())
            song['score']['patterns'][name] = {'row_step': [1, 12], 'beats': []}
            raw.append(Pattern(name, [[Cell() for _ in range(7)] for _ in range(48)]))
        return song, raw

    def capture(self, song, raw):
        return tab.capture_score_clipboard(song, selection=[
            dict(occurrence='oa', beats=['tail']), dict(occurrence='ob', beats=['head'])], raw_patterns=raw)

    def test_cross_pattern_tie_fresh_ids_twice_exact_timing_and_source(self):
        song, raw = self.fixture()
        clipboard = self.capture(song, raw)
        before = copy.deepcopy((song, raw, clipboard))
        self.assertEqual([b['at'] for b in clipboard['beats']], [[0, 1], [1, 2]])
        first = tab.paste_score_clipboard(song, tab.project_score(song, raw), 2, 42, clipboard, 'oc', across=True)
        second = tab.paste_score_clipboard(first, tab.project_score(first, raw), 3, 42, clipboard, 'od', across=True)
        result = tab.project_score(yaml.safe_load(yaml.safe_dump(second)), raw)
        self.assertEqual(result.patterns[2].rows[42][0].note, 64)
        self.assertIsNone(result.patterns[3].rows[0][0].note)
        self.assertEqual(result.patterns[3].rows[6][0].note, NOTE_OFF)
        self.assertEqual(result.patterns[3].rows[42][0].note, 64)
        self.assertIsNone(result.patterns[4].rows[0][0].note)
        self.assertEqual(result.patterns[4].rows[6][0].note, NOTE_OFF)
        self.assertEqual([e['from']['occurrence'] for e in second['score']['ties']], ['oa', 'oc', 'od'])
        self.assertEqual((song, raw, clipboard), before)
        self.assertEqual(first['patterns'], song['patterns'])
        self.assertEqual(result.patterns[0], tab.project_score(song, raw).patterns[0])

    def test_repeated_source_visits_duplicate_local_ids_and_sparse_stroke(self):
        song, raw = self.fixture()
        raw[0].rows[0][1].effect = raw[0].rows[0][1].param = 0
        song['score']['ties'] = []
        song['orders'].insert(1, 'A'); song['score']['order_ids'].insert(1, 'oa2')
        first = song['score']['patterns']['A']['beats'][0]
        first.update(text='Keep this', stroke={'direction': 'up', 'value': 4})
        second = beat('lower', [0, 1], [note('low', 40, 6, 0)], voice=1)
        song['score']['patterns']['A']['beats'].append(second)
        clip = tab.capture_score_clipboard(song, selection=[dict(occurrence=o, beats=['chord', 'lower'])
            for o in ('oa', 'oa2')], raw_patterns=raw)
        self.assertEqual([b['at'] for b in clip['beats']], [[0, 1], [0, 1], [4, 1], [4, 1]])
        self.assertEqual(len({n['id'] for b in clip['beats'] for n in b['notes']}), 8)
        self.assertTrue(all(b['stroke'] == first['stroke'] for b in clip['beats']))
        self.assertEqual([b['text'] for b in clip['beats'] if 'text' in b], ['Keep this', 'Keep this'])
        pasted = tab.paste_score_clipboard(song, Module(patterns=raw), 2, 0, clip, 'oc', across=True)
        self.assertEqual(len(pasted['score']['patterns']['C']['beats']), 2)
        self.assertEqual(len(pasted['score']['patterns']['D']['beats']), 2)

    def test_cross_span_refusals_are_immutable_including_later_pattern(self):
        song, raw = self.fixture()
        clip = self.capture(song, raw)
        for case, message in [('shared', 'unique destination'), ('approved', 'approved'),
                              ('occupied', 'empty destination')]:
            with self.subTest(case=case):
                source = copy.deepcopy(song); row = 42; pi = 2; oid = 'oc'
                if case == 'shared':
                    source['orders'].append('D'); source['score']['order_ids'].append('od2')
                if case == 'approved': source['patterns']['D']['approved'] = True
                if case == 'occupied': source['score']['patterns']['D']['beats'] = [beat('rest', [0, 1], [])]
                if case == 'overflow': pi, oid = 5, 'of'
                if case == 'straddle': row = 45
                saved = copy.deepcopy((source, raw, clip))
                with self.assertRaisesRegex(ValueError, message):
                    tab.paste_score_clipboard(source, Module(patterns=raw), pi, row, clip, oid, across=True)
                self.assertEqual((source, raw, clip), saved)

    def test_legacy_shared_single_pattern_paste_stays_supported(self):
        song, raw = self.fixture()
        song['orders'].append('C'); song['score']['order_ids'].append('oc2')
        clip = tab.capture_score_clipboard(song, 'A', ['chord'])
        candidate = tab.paste_score_clipboard(song, tab.project_score(song, raw), 2, 0, clip, 'oc', across=True)
        self.assertEqual(tab.project_score(candidate, raw).patterns[2].rows[0][0].note, 64)
        self.assertEqual(candidate['orders'], song['orders'])

    def test_external_tie_and_malformed_range_payloads_refuse(self):
        song, raw = self.fixture()
        fragment = tab.capture_score_clipboard(song, selection=[dict(occurrence='oa', beats=['tail'])], raw_patterns=raw)
        self.assertEqual(fragment['ties'], [])
        clip = self.capture(song, raw)
        for value in (None, [], {'track': 'guitar', 'voice': []}, dict(clip['beats'][0], at=[-1, 1])):
            bad = dict(clip, beats=[value])
            with self.subTest(value=value), self.assertRaises(ValueError):
                tab.paste_score_clipboard(song, Module(patterns=raw), 2, 42, bad, 'oc', across=True)
        with self.assertRaisesRegex(ValueError, 'boolean'):
            tab.paste_score_clipboard(song, Module(patterns=raw), 2, 42, clip, 'oc', across=1)


class TestReplacementClipboard(unittest.TestCase):
    fixture = TestCrossMeasureClipboard.fixture
    capture = TestCrossMeasureClipboard.capture

    def test_replace_tied_phrase_twice_and_self_with_fresh_ids(self):
        song, raw = self.fixture()
        clip = self.capture(song, raw)
        saved = copy.deepcopy((song, raw, clip))
        first = tab.paste_score_clipboard(song, Module(patterns=raw), 0, 42, clip, 'oa', replace=True)
        second = tab.paste_score_clipboard(first, Module(patterns=raw), 0, 42, clip, 'oa', replace=True)
        self.assertEqual((song, raw, clip), saved)
        self.assertEqual(first['patterns'], song['patterns'])
        for name in ('A', 'B'):
            old = {n['id'] for b in first['score']['patterns'][name]['beats'] for n in b['notes']}
            new = [n['id'] for b in second['score']['patterns'][name]['beats'] if b['id'].startswith('copy_') for n in b['notes']]
            self.assertTrue(new and not old.intersection(new))
        self.assertEqual(len(second['score']['ties']), 1)
        self.assertEqual(tab.project_score(second, raw).patterns[0].rows[42][0].note, 64)
        self.assertEqual(tab.project_score(second, raw).patterns[1].rows[6][0].note, NOTE_OFF)

    def test_replace_clears_gaps_only_in_copied_lanes(self):
        song, raw = self.fixture()
        clip = tab.capture_score_clipboard(song, 'A', ['chord', 'rest'])
        destination = [beat('old0', [0, 1], [note('oldn', 64, 1, 0)]),
                       beat('gap', [1, 1], []), beat('old2', [2, 1], []),
                       beat('lower', [0, 1], [note('low', 40, 6, 0)], voice=1),
                       beat('other', [0, 1], [note('bassn', 40, 1, 0)], track='bass'),
                       beat('outside', [3, 1], [])]
        song['score']['patterns']['C']['beats'] = destination
        result = tab.paste_score_clipboard(song, Module(patterns=raw), 2, 0, clip, 'oc', replace=True)
        actual = result['score']['patterns']['C']['beats']
        self.assertEqual([b for b in actual if not b['id'].startswith('copy_')], destination[3:])
        self.assertEqual([b['at'] for b in actual if b['id'].startswith('copy_')], [[0, 1], [2, 1]])
        tab.project_score(result, raw)

    def test_replacement_refusals_are_atomic(self):
        song, raw = self.fixture()
        clip = self.capture(song, raw)
        for case, message in [('shared', 'unique destination'), ('approved', 'approved'),
                              ('stroke', 'retained voice shared'), ('flag', 'boolean')]:
            with self.subTest(case=case):
                source = copy.deepcopy(song); payload = copy.deepcopy(clip); pi, row, oid = 2, 42, 'oc'
                if case == 'partial': source['score']['patterns']['D']['beats'] = [beat('rest', [0, 1], [])]
                if case == 'tie':
                    pi, row, oid = 0, 42, 'oa'; payload['beats'] = payload['beats'][:1]; payload['ties'] = []
                if case == 'shared': source['orders'].append('D'); source['score']['order_ids'].append('od2')
                if case == 'approved': source['patterns']['D']['approved'] = True
                if case == 'stroke':
                    old = beat('old', [7, 2], [], value=8); old['stroke'] = {'direction': 'up', 'value': 4}
                    source['score']['patterns']['C']['beats'] = [old, beat('lower', [7, 2], [], value=8, voice=1)]
                saved = copy.deepcopy((source, raw, payload))
                with self.assertRaisesRegex(ValueError, message):
                    tab.paste_score_clipboard(source, Module(patterns=raw), pi, row, payload, oid,
                                              replace=1 if case == 'flag' else True)
                self.assertEqual((source, raw, payload), saved)


class TestSectionClipboard(unittest.TestCase):
    fixture = TestCrossMeasureClipboard.fixture

    @staticmethod
    def raw_for(song, raw):
        known = {p.name for p in raw}
        return raw + [Pattern(name, [[Cell() for _ in range(7)] for _ in range(spec['rows'])])
                      for name, spec in song['patterns'].items() if name not in known]

    def test_paste_at_song_end_adds_metered_bars_and_preserves_source(self):
        song, raw = self.fixture()
        song['score']['measures'] = [dict(id='final', meter=[4, 4], swing='eighth', **{
            'from': dict(occurrence='of', at=[0, 1]), 'to': dict(occurrence='of', at=[4, 1])})]
        clip = tab.capture_score_clipboard(song, 'A', ['chord', 'rest', 'tail'], 'oa')
        before = copy.deepcopy((song, raw, clip))
        result = tab.paste_score_clipboard(song, Module(patterns=raw), 5, 48, clip, 'of', across=True)
        self.assertEqual(len(result['orders']), 7)
        final = result['orders'][-1]
        self.assertEqual(result['score']['measures'][-1]['meter'], [4, 4])
        self.assertEqual(result['score']['measures'][-1]['swing'], 'eighth')
        self.assertEqual([b['at'] for b in result['score']['patterns'][final]['beats']], [[0, 1], [2, 1], [7, 2]])
        tab.project_score(result, self.raw_for(result, raw))
        self.assertEqual((song, raw, clip), before)

    def test_cross_bar_note_splits_to_one_sounding_tied_chain(self):
        song, raw = self.fixture()
        clip = tab.capture_score_clipboard(song, 'A', ['chord'])
        before = copy.deepcopy((song, clip))
        result = tab.paste_score_clipboard(song, Module(patterns=raw), 5, 45, clip, 'of', across=True)
        final = result['orders'][-1]
        left = result['score']['patterns']['F']['beats'][0]
        right = result['score']['patterns'][final]['beats'][0]
        self.assertEqual(tab.duration_quarters(left['written']), Fraction(1, 4))
        self.assertEqual(tab.duration_quarters(right['written']), Fraction(3, 4))
        self.assertEqual(len(result['score']['ties']), 4)  # original plus three chord continuations
        projected = tab.project_score(result, self.raw_for(result, raw))
        self.assertEqual(projected.patterns[5].rows[45][0].note, 64)
        self.assertIsNone(projected.patterns[-1].rows[0][0].note)
        self.assertEqual(projected.patterns[-1].rows[9][0].note, NOTE_OFF)
        self.assertEqual((song, clip), before)

    def test_replace_inside_sustain_keeps_both_exterior_fragments_and_peer(self):
        song, raw = self.fixture()
        sustained = beat('sustain', [0, 1], [note('held', 64, 1, 0)], value=1)
        peer = beat('peer', [0, 1], [note('low', 40, 6, 0)], value=1, voice=1)
        song['score']['patterns']['C']['beats'] = [sustained, peer]
        clip = tab.capture_score_clipboard(song, 'A', ['rest'])
        before = copy.deepcopy(song)
        result = tab.paste_score_clipboard(song, Module(patterns=raw), 2, 12, clip, 'oc', replace=True)
        actual = result['score']['patterns']['C']['beats']
        sounding = sorted((Fraction(*b['at']), tab.duration_quarters(b['written'])) for b in actual
                          if b['notes'] and b.get('voice', 0) == 0)
        self.assertEqual(sounding, [(Fraction(0), Fraction(1)), (Fraction(2), Fraction(2))])
        self.assertIn(peer, actual)
        projected = tab.project_score(result, raw)
        self.assertEqual(projected.patterns[2].rows[12][0].note, NOTE_OFF)
        self.assertEqual(projected.patterns[2].rows[24][0].note, 64)
        self.assertEqual(song, before)

    def test_replace_rest_middle_has_distinct_ids_and_no_spurious_ties(self):
        song, raw = self.fixture()
        song['score']['patterns']['C']['beats'] = [beat('whole_rest', [0, 1], [], value=1)]
        clip = tab.capture_score_clipboard(song, 'A', ['chord'])
        result = tab.paste_score_clipboard(song, Module(patterns=raw), 2, 12, clip, 'oc', replace=True)
        beats = result['score']['patterns']['C']['beats']
        self.assertEqual(len({b['id'] for b in beats}), len(beats))
        self.assertEqual(result['score']['ties'], song['score']['ties'])
        tab.project_score(result, raw)

    def test_copy_boundary_tie_independent_attack_and_replace_severs_only_cut_link(self):
        song, raw = self.fixture()
        before = copy.deepcopy(song)
        for pattern, bid, oid in [('A', 'tail', 'oa'), ('B', 'head', 'ob')]:
            clip = tab.capture_score_clipboard(song, pattern, [bid], oid)
            self.assertEqual(clip['ties'], [])
            pasted = tab.paste_score_clipboard(song, Module(patterns=raw), 2, 0, clip, 'oc', across=True)
            self.assertEqual(tab.project_score(pasted, raw).patterns[2].rows[0][0].note, 64)
        clip = tab.capture_score_clipboard(song, 'A', ['rest'])
        result = tab.paste_score_clipboard(song, Module(patterns=raw), 1, 0, clip, 'ob', replace=True)
        self.assertEqual(result['score']['ties'], [])
        self.assertEqual(result['score']['patterns']['A'], song['score']['patterns']['A'])
        tab.project_score(result, raw)
        self.assertEqual(song, before)

    def test_late_raw_collision_after_extension_refuses_immutably(self):
        song, raw = self.fixture()
        raw[-1].rows[47][0].note = 67
        clip = tab.capture_score_clipboard(song, 'A', ['chord'])
        before = copy.deepcopy((song, raw, clip))
        with self.assertRaisesRegex(ValueError, 'raw'):
            tab.paste_score_clipboard(song, Module(patterns=raw), 5, 45, clip, 'of', across=True)
        self.assertEqual((song, raw, clip), before)

    def test_paste_splits_at_authored_bar_inside_backing_pattern(self):
        song, raw = self.fixture()
        song['score']['measures'] = [dict(id='half' + str(i), meter=[2, 4], **{
            'from': dict(occurrence='oc', at=[i * 2, 1]),
            'to': dict(occurrence='oc', at=[(i + 1) * 2, 1])}) for i in range(2)]
        clip = tab.capture_score_clipboard(song, 'A', ['chord'])
        result = tab.paste_score_clipboard(song, Module(patterns=raw), 2, 21, clip, 'oc', across=True)
        parts = result['score']['patterns']['C']['beats']
        self.assertEqual([b['at'] for b in parts], [[7, 4], [2, 1]])
        self.assertEqual(len(result['score']['ties']), 4)
        tab.project_score(result, raw)

    def test_replacement_preserves_exterior_incoming_and_outgoing_ties(self):
        song, raw = self.fixture()
        song['score']['patterns']['C']['beats'] = [beat('head', [3, 1], [note('h', 64, 1, 0)])]
        song['score']['patterns']['D']['beats'] = [beat('body', [0, 1], [note('b', 64, 1, 0)], value=1)]
        song['score']['patterns']['E']['beats'] = [beat('tail', [0, 1], [note('t', 64, 1, 0)])]
        song['score']['ties'] += [
            {'from': dict(occurrence='oc', note='h'), 'to': dict(occurrence='od', note='b')},
            {'from': dict(occurrence='od', note='b'), 'to': dict(occurrence='oe', note='t')}]
        clip = tab.capture_score_clipboard(song, 'A', ['rest'])
        result = tab.paste_score_clipboard(song, Module(patterns=raw), 3, 12, clip, 'od', replace=True)
        self.assertEqual(len(result['score']['ties']), 3)
        projected = tab.project_score(result, raw)
        self.assertIsNone(projected.patterns[3].rows[0][0].note)
        self.assertEqual(projected.patterns[3].rows[12][0].note, NOTE_OFF)
        self.assertEqual(projected.patterns[3].rows[24][0].note, 64)
        self.assertIsNone(projected.patterns[4].rows[0][0].note)


class TestCrossRangeCommands(unittest.TestCase):
    def test_range_duration_fit_moves_following_notes_and_mixed_meter(self):
        song,raw,groups=self.fixture();song['score']['ties']=[]
        fitted,_=TestPlaceFitCommand().fixture()
        song['score']['patterns']['B']['beats']=copy.deepcopy(fitted['score']['patterns']['A']['beats'])
        song['score']['patterns']['A']['beats']=[beat('a',[0,1],[dict(note('a',64,1,0),velocity=95)],value=2)]
        groups=[dict(occurrence='oa',beats=['a']),dict(occurrence='ob',beats=['a'])]
        request=dict(action='set_duration',track='guitar',voice=0,selection=groups,fit='tg_duration',
                     written=dict(value=2,dots=0,tuplet=[1,1]))
        candidate,report=tab.score_command(song,raw,request)
        self.assertEqual(tab._beat(candidate['score'],'B','b')['at'],[2,1])
        self.assertEqual(tab._beat(candidate['score'],'B','c')['at'],[3,1])
        self.assertEqual(report['selection']['range'],groups)
        self.assertEqual(report['outcomes'],['unchanged','shifted'])
        self.assertEqual(tab._beat(candidate['score'],'B','b')['notes'],tab._beat(song['score'],'B','b')['notes'])
        # The next measure has a shorter boundary; no rebarring or pattern growth.
        song['score']['measures']=[dict(id='three',meter=[3,4],**{'from':dict(occurrence='ob',at=[0,1]),'to':dict(occurrence='ob',at=[3,1])})]
        # A valid bar exercises normal Fit; a short authored bar requires Free.
        song['score']['patterns']['B']['beats']=[beat('a',[0,1],[note('a',64,1,0)],value=2),beat('r',[2,1],[])]
        shorter,_=tab.score_command(song,raw,dict(request,written=dict(value=4,dots=1,tuplet=[1,1])))
        self.assertEqual(tab._beat(shorter['score'],'B','a')['written']['dots'],1)
        unchanged,report=tab.score_command(song,raw,dict(request,written=dict(value=1,dots=0,tuplet=[1,1])))
        self.assertEqual(tab._beat(unchanged['score'],'B','a'),tab._beat(song['score'],'B','a'))
        self.assertEqual(report['kept_durations'][0]['reason'],'bar_end')

    def test_range_duration_voice_spelling_noop_and_generated_rests(self):
        song,raw,groups=self.fixture();song['score']['ties']=[]
        before=copy.deepcopy((song,raw,groups))
        edit=dict(action='set_duration',track='guitar',voice=0,selection=groups,written=dict(value=8,dots=0,tuplet=[1,1]))
        short,report=tab.score_command(song,raw,edit)
        self.assertEqual(report['selection']['voice'],0)
        for original_group,returned_group in zip(groups,report['selection']['range']):
            self.assertTrue(set(original_group['beats']) <= set(returned_group['beats']))
        tab._score_range(short,raw,dict(edit,selection=report['selection']['range'],action='transpose'))
        self.assertEqual(tab._beat(short['score'],'A','lower'),tab._beat(song['score'],'A','lower'))
        for own in ('A','B'):
            for i in range(4):
                b=tab._beat(short['score'],own,f'b{i}')
                self.assertEqual(b['at'],[i,1]);self.assertEqual(b['written'],edit['written'])
                self.assertEqual(b['notes'],tab._beat(song['score'],own,f'b{i}')['notes'])
        again,_=tab.score_command(short,raw,edit);self.assertEqual(again,short)
        restored,_=tab.score_command(short,raw,dict(edit,written=dict(value=4,dots=0,tuplet=[1,1])))
        self.assertEqual(tab.project_score(restored,raw).patterns,tab.project_score(song,raw).patterns)
        # Dotted quarter triplet is exactly one quarter: ties survive spelling-only change.
        song['score']['ties']=self.fixture()[0]['score']['ties']
        spelling,_=tab.score_command(song,raw,dict(edit,written=dict(value=4,dots=1,tuplet=[3,2])))
        self.assertEqual(spelling['score']['ties'],song['score']['ties'])
        shorter,report=tab.score_command(song,raw,edit)
        self.assertEqual(shorter['score']['ties'],[])
        self.assertEqual(report['removed_ties'],song['score']['ties'])
        song['score']['ties']=[];self.assertEqual((song,raw,groups),before)

    def test_range_duration_fit_selected_rest_and_late_guards(self):
        song,raw,groups=self.fixture();song['score']['ties']=[]
        edit=dict(action='set_duration',track='guitar',voice=0,selection=groups,written=dict(value=2,dots=0,tuplet=[1,1]))
        for mode in ('overlap','fit-full','shared','approved','late-raw','selected-rest'):
            source,patterns=copy.deepcopy((song,raw));request=copy.deepcopy(edit)
            if mode=='fit-full':request['fit']='tg_duration'
            if mode=='shared':source['orders'].append('B');source['score']['order_ids'].append('again')
            if mode=='approved':source['patterns']['B']['approved']=True
            if mode=='late-raw':
                request['written']['value']=8;patterns[1].rows[6][0]=Cell(note=70,instrument=1)
            if mode=='selected-rest':
                for name in ('A','B'):
                    source['score']['patterns'][name]['beats'][1]['notes']=[]
            original=copy.deepcopy(source)
            with self.subTest(mode=mode):
                if mode in ('overlap','fit-full','selected-rest'):
                    candidate,report=tab.score_command(source,patterns,request)
                    if mode=='selected-rest':self.assertEqual(len(report['consumed_rests']),2)
                    else:self.assertEqual(candidate,source)
                else:
                    with self.assertRaises(ValueError):tab.score_command(source,patterns,request)
            self.assertEqual(source,original)
        # Untouched voice's tie crosses beyond selection; it does not block voice0.
        for name in ('B','C'):
            source_beat=copy.deepcopy(tab._beat(song['score'],'A','lower'));source_beat['at']=[3,1] if name=='B' else [0,1]
            song['score']['patterns'][name]['beats'].append(source_beat)
        groups[1]['beats'].append('lower')
        song['score']['ties']=[{'from':dict(occurrence='ob',note='low'),'to':dict(occurrence='oc',note='low')}]
        candidate,_=tab.score_command(song,raw,dict(edit,written=dict(value=8,dots=0,tuplet=[1,1])))
        self.assertEqual(candidate['score']['ties'],song['score']['ties'])

    def test_range_expression_reuses_local_exclusivity_and_noop(self):
        song,raw,groups=self.fixture()
        song['score']['patterns']['A']['beats'][0]['notes'][0]['velocity']=None
        song['score']['patterns']['A']['beats'][0]['notes'][0].pop('velocity')
        before=copy.deepcopy((song,raw,groups))
        def edit(source,changes):
            return tab.score_command(source,raw,dict(action='set_expression',track='guitar',selection=groups,changes=changes))
        candidate,report=edit(song,dict(velocity=63,ghost=True,staccato=True))
        self.assertEqual(report['selection']['range'],groups)
        self.assertNotIn('clipboard',report)
        for name in ('A','B'):
            for b in candidate['score']['patterns'][name]['beats']:
                if b['voice'] != 0:
                    self.assertEqual(b,tab._beat(song['score'],name,b['id']));continue
                for n in b['notes']:
                    self.assertEqual(n['velocity'],63);self.assertTrue(n['ghost']);self.assertTrue(n['staccato'])
                    self.assertNotIn('accent',n)
        self.assertEqual(candidate['score']['patterns']['C'],song['score']['patterns']['C'])
        self.assertEqual(candidate['score']['ties'],song['score']['ties'])
        again,_=edit(candidate,dict(velocity=63,ghost=True,staccato=True));self.assertEqual(again,candidate)
        muted,_=edit(candidate,dict(palm_mute=True,heavy_accent=True))
        self.assertTrue(all(n.get('palm_mute') and n.get('heavy_accent') and not n.get('staccato') and not n.get('ghost')
            for name in ('A','B') for b in muted['score']['patterns'][name]['beats'] if b['voice']==0 for n in b['notes']))
        cleared,_=edit(muted,dict(palm_mute=False,heavy_accent=False,velocity=None))
        self.assertTrue(all(not n.get('palm_mute') and not n.get('heavy_accent') and 'velocity' not in n
            for name in ('A','B') for b in cleared['score']['patterns'][name]['beats'] if b['voice']==0 for n in b['notes']))
        with self.assertRaisesRegex(ValueError,'choose one ghost'):edit(candidate,dict(ghost=True,accent=True))
        with self.assertRaisesRegex(ValueError,'not both'):edit(candidate,dict(staccato=True,palm_mute=True))
        with self.assertRaisesRegex(ValueError,'velocity'):edit(song,dict(velocity=128))
        with self.assertRaisesRegex(ValueError,'boolean'):edit(song,dict(dead=1))
        self.assertEqual((song,raw,groups),before)

    def test_range_expression_active_voice_peer_ties_and_empty_voice(self):
        song,raw,groups=self.fixture()
        original=copy.deepcopy(song)
        request=dict(action='set_expression',track='guitar',voice=1,selection=groups,changes=dict(velocity=47,ghost=True))
        result,report=tab.score_command(song,raw,request)
        self.assertEqual(report['selection']['range'],groups)
        for name,pattern in result['score']['patterns'].items():
            for b in pattern['beats']:
                if name=='A' and b['id']=='lower':
                    self.assertEqual(b['notes'][0],dict(tab._beat(song['score'],'A','lower')['notes'][0],velocity=47,ghost=True))
                else:self.assertEqual(b,tab._beat(song['score'],name,b['id']))
        # The untouched voice's incomplete outside tie must not block expression edits.
        song['score']['ties'].append({'from':dict(occurrence='ob',note='n3'),'to':dict(occurrence='oc',note='n0')})
        result,_=tab.score_command(song,raw,request)
        self.assertEqual(result['score']['ties'],song['score']['ties'])
        with self.assertRaisesRegex(ValueError,'complete ties'):
            tab.score_command(song,raw,dict(request,voice=0))
        # No note of voice1 in B: no-op, with its peer's expression untouched.
        result,_=tab.score_command(original,raw,dict(request,selection=[groups[1]]))
        self.assertEqual(result,original)
        with self.assertRaisesRegex(ValueError,'velocity'):
            tab.score_command(original,raw,dict(request,changes=dict(velocity=128,ghost=True)))
        self.assertEqual(original,self.fixture()[0])

    def test_range_expression_dead_replaces_existing_effects_and_guards(self):
        song,raw,groups=self.fixture()
        note=song['score']['patterns']['B']['beats'][1]['notes'][0]
        note['bend']=dict(points=[dict(position=0,value=0),dict(position=12,value=2)])
        request=dict(action='set_expression',track='guitar',selection=groups,changes=dict(dead=True))
        candidate,_=tab.score_command(song,raw,request)
        self.assertNotIn('bend',candidate['score']['patterns']['B']['beats'][1]['notes'][0])
        for mode in ('shared','approved','tie','raw'):
            source=copy.deepcopy(song);patterns=copy.deepcopy(raw)
            if mode=='shared':source['orders'].append('B');source['score']['order_ids'].append('again')
            if mode=='approved':source['patterns']['B']['approved']=True
            if mode=='tie':source['score']['ties'].append({'from':dict(occurrence='ob',note='n3'),'to':dict(occurrence='oc',note='n0')})
            if mode=='raw':patterns[1].rows[12][0]=Cell(note=70,instrument=1)
            before=copy.deepcopy((source,patterns))
            with self.subTest(mode=mode),self.assertRaises(ValueError):tab.score_command(source,patterns,request)
            self.assertEqual((source,patterns),before)

    def test_range_pitch_transpose_shift_routing_and_reversal(self):
        song, raw, groups = self.fixture()
        song['score']['patterns']['A']['beats'][-1]['notes'][0].update(string=3,fret=4)
        original = copy.deepcopy((song, raw, groups))
        request = dict(action='transpose', scope='selection', track='guitar', selection=groups, semitones=2)
        moved, report = tab.score_command(song, raw, request)
        self.assertEqual(report['selection']['range'], groups)
        for name in ('A', 'B'):
            for before, after in zip(song['score']['patterns'][name]['beats'], moved['score']['patterns'][name]['beats']):
                self.assertEqual([n['pitch']+2 for n in before['notes']], [n['pitch'] for n in after['notes']])
        self.assertEqual(moved['score']['patterns']['C'], song['score']['patterns']['C'])
        shift = dict(action='shift_strings', track='guitar', selection=groups, direction=1)
        alternate, report = tab.score_command(moved, raw, shift)
        self.assertEqual(tab.project_score(alternate, raw).patterns, tab.project_score(moved, raw).patterns)
        back, _ = tab.score_command(alternate, raw, dict(shift, direction=-1))
        for name in ('A','B'):
            for b, a in zip(moved['score']['patterns'][name]['beats'], back['score']['patterns'][name]['beats']):
                for n, actual in zip(b['notes'], a['notes']):
                    self.assertEqual((n['pitch'],n['string'],n['fret']), (actual['pitch'],actual['string'],actual['fret']))
        self.assertEqual((song, raw, groups), original)
        # The shared allocator may move a high note; its audio channel stays owned.
        high = song['score']['patterns']['A']['beats'][1]['notes'][0]
        high.update(pitch=87,string=2,fret=28,channel=5)
        moved, _ = tab.score_command(song, raw, dict(request, semitones=5))
        self.assertEqual(moved['score']['patterns']['A']['beats'][1]['notes'][0]['channel'], 5)

    def test_range_string_effect_frets_and_atomic_guards(self):
        song, raw, groups = self.fixture()
        song['score']['patterns']['A']['beats'][-1]['notes'][0].update(string=3,fret=4)
        n = song['score']['patterns']['B']['beats'][1]['notes'][0]
        n['trill'] = dict(fret=3, value=16)
        n['velocity'] = 95
        song['score']['patterns']['A']['beats'][1]['notes'][0]['grace'] = dict(fret=1,value=16,velocity=80,on_beat=True)
        request = dict(action='shift_strings',track='guitar',selection=groups,direction=1)
        moved, _ = tab.score_command(song,raw,request)
        self.assertEqual(moved['score']['patterns']['B']['beats'][1]['notes'][0]['trill']['fret'],8)
        self.assertEqual(moved['score']['patterns']['A']['beats'][1]['notes'][0]['grace']['fret'],6)
        for mode, message in [('shared','unique'),('approved','approved'),('tie','tie'),('edge','adjacent'),
                              ('harmonic','harmonic'),('collision','same string'),('overflow','fret'),('raw','raw')]:
            source = copy.deepcopy(song); patterns = copy.deepcopy(raw)
            with self.subTest(mode=mode):
                if mode=='shared': source['orders'].append('A'); source['score']['order_ids'].append('again')
                if mode=='approved': source['patterns']['B']['approved']=True
                if mode=='tie': source['score']['ties'].append({'from':dict(occurrence='ob',note='n3'),'to':dict(occurrence='oc',note='n0')})
                if mode=='edge': request2=dict(request,direction=-1)
                else: request2=request
                if mode=='harmonic':
                    target=source['score']['patterns']['B']['beats'][1]['notes'][0]
                    target.pop('trill');target.update(pitch=76,fret=12,harmonic=dict(type='natural',data=0))
                if mode=='overflow': source['score']['patterns']['B']['beats'][1]['notes'][0].update(pitch=93,fret=29)
                if mode=='collision':
                    # A retained voice starts before the selected range and sustains onto its target string.
                    source['score']['patterns']['A']['beats'][0]['notes'] = [note('n0', 59, 2, 0)]
                    source['score']['patterns']['A']['beats'][0]['written'] = dict(value=1)
                    source['score']['patterns']['A']['beats'][0]['voice'] = 1
                    source['score']['patterns']['A']['beats'] = source['score']['patterns']['A']['beats'][:4]
                    request2=dict(request, selection=[dict(occurrence='oa',beats=['b1','b2','b3']),groups[1]])
                if mode=='raw': patterns[1].rows[12][0]=Cell(note=70,instrument=1)
                before=copy.deepcopy((source,patterns))
                with self.assertRaisesRegex(ValueError,message): tab.score_command(source,patterns,request2)
                self.assertEqual((source,patterns),before)

    def test_selected_harmonic_interval_and_unrelated_links(self):
        song,raw,groups=self.fixture()
        song['score']['patterns']['A']['beats'][-1]['notes'][0].update(string=3,fret=4)
        target=song['score']['patterns']['B']['beats'][1]['notes'][0]
        target.update(pitch=71,fret=7,harmonic=dict(type='natural',data=0))
        request=dict(action='transpose',scope='selection',track='guitar',selection=groups,semitones=2)
        with self.assertRaisesRegex(ValueError,'requested interval'):tab.score_command(song,raw,request)
        target['harmonic']=dict(type='artificial',data=0)
        result,_=tab.score_command(song,raw,request)
        self.assertEqual(result['score']['patterns']['B']['beats'][1]['notes'][0]['pitch'],73)
        # A later unrelated hammer pair does not prevent an earlier alternate fingering.
        target.pop('harmonic')
        song['score']['patterns']['D']['beats'][1]['notes'][0]['hammer']=True
        result,_=tab.score_command(song,raw,dict(action='shift_strings',track='guitar',selection=groups,direction=1))
        self.assertEqual(tab.playback_plan(song,raw)['events'],tab.playback_plan(result,raw)['events'])
        song['score']['ties']=[]
        song['score']['patterns']['A']['beats'][3]['notes'][0]['hammer']=True
        before=copy.deepcopy(song)
        with self.assertRaisesRegex(ValueError,'changes native playback'):
            tab.score_command(song,raw,dict(action='shift_strings',track='guitar',selection=[groups[1]],direction=1))
        self.assertEqual(song,before)

    def test_semitone_active_voice_same_string_limits_and_peer_ties(self):
        song,raw,groups=self.fixture();original=copy.deepcopy(song)
        request=dict(action='shift_pitch',track='guitar',voice=0,selection=groups,direction=1)
        moved,report=tab.score_command(song,raw,request)
        self.assertEqual(report['selection']['voice'],0)
        for name in ('A','B'):
            for old,new in zip(song['score']['patterns'][name]['beats'],moved['score']['patterns'][name]['beats']):
                if old['voice']==1:self.assertEqual(new,old)
                else:
                    for a,b in zip(old['notes'],new['notes']):
                        self.assertEqual((b['pitch'],b['string'],b['fret']),(a['pitch']+1,a['string'],a['fret']+1))
        lower,report=tab.score_command(song,raw,dict(request,voice=1))
        self.assertEqual(report['selection']['voice'],1)
        self.assertEqual(lower['score']['patterns']['A']['beats'][0],song['score']['patterns']['A']['beats'][0])
        self.assertEqual(lower['score']['patterns']['A']['beats'][-1]['notes'][0]['pitch'],60)
        # An upper tie leaving the range is unrelated to a lower-voice pitch edit.
        tab.score_command(song,raw,dict(request,voice=1,selection=groups[:1]))
        with self.assertRaisesRegex(ValueError,'complete ties'):
            tab.score_command(song,raw,dict(request,selection=groups[:1]))
        for mode in ('fret','shared','approved','harmonic'):
            source=copy.deepcopy(song)
            if mode=='fret':source['score']['patterns']['A']['beats'][1]['notes'][0].update(string=2,fret=29,pitch=88)
            if mode=='shared':source['orders'].append('A');source['score']['order_ids'].append('again')
            if mode=='approved':source['patterns']['A']['approved']=True
            if mode=='harmonic':source['score']['patterns']['A']['beats'][1]['notes'][0].update(fret=7,pitch=71,harmonic=dict(type='natural',data=0))
            before=copy.deepcopy(source)
            with self.subTest(mode=mode),self.assertRaises(ValueError):tab.score_command(source,raw,request)
            self.assertEqual(source,before)
        self.assertEqual(song,original)

    def fixture(self):
        song, raw = TestCrossMeasureClipboard().fixture()
        for name in ('A', 'B', 'C', 'D'):
            song['score']['patterns'][name]['beats'] = [beat(f'b{i}', [i, 1],
                [dict(note(f'n{i}', 64 if i in (0, 3) else 64+i, 1, 0 if i in (0, 3) else i),
                      velocity=95, accent=True)]) for i in range(4)]
        song['score']['patterns']['A']['beats'].append(beat('lower', [0, 1], [note('low', 59, 2, 0)], voice=1))
        song['score']['ties'] = [dict(**{'from': dict(occurrence='oa', note='n3'), 'to': dict(occurrence='ob', note='n0')})]
        groups = [dict(occurrence='o'+name.lower(), beats=[b['id'] for b in song['score']['patterns'][name]['beats']]) for name in ('A','B')]
        return song, raw, groups

    def test_cut_whole_qualified_notes_keeps_rests_timing_and_clipboard(self):
        song, raw, groups = self.fixture()
        other = beat('bass', [0, 1], [note('bass',40,1,0)], track='bass')
        song['score']['patterns']['A']['beats'].append(other)
        song['score']['patterns']['B']['beats'][1]['notes'] = []
        before = copy.deepcopy((song, raw, groups))
        cut, result = tab.score_command(song, raw, dict(action='cut', track='guitar', selection=groups))
        self.assertTrue(all(not b['notes'] for name in ('A','B') for b in cut['score']['patterns'][name]['beats'] if b['track']=='guitar' and b['voice']==0))
        self.assertEqual(tab._beat(cut['score'],'A','lower'),tab._beat(song['score'],'A','lower'))
        self.assertEqual(cut['score']['patterns']['A']['beats'][-1],other)
        self.assertEqual(cut['score']['ties'], [])
        self.assertEqual(cut['score']['patterns']['C'], song['score']['patterns']['C'])
        self.assertEqual(cut['patterns'], song['patterns'])
        self.assertEqual([(b['id'], b['at'], b['written']) for b in cut['score']['patterns']['B']['beats']],
                         [(b['id'], b['at'], b['written']) for b in song['score']['patterns']['B']['beats']])
        restored = tab.paste_score_clipboard(cut, Module(patterns=raw), 0, 0, result['clipboard'], 'oa', replace=True)
        self.assertEqual(len(restored['score']['ties']), 1)
        self.assertEqual(tab.project_score(restored, raw).patterns, tab.project_score(song, raw).patterns)
        self.assertEqual((song, raw, groups), before)

    def test_delete_cut_rest_active_voice_local_cross_and_empty(self):
        song,raw,groups=self.fixture();original=copy.deepcopy(song)
        for action in ('delete','cut','rest'):
            for voice in (0,1):
                for selection in (groups,groups[:1],groups[1:]):
                    with self.subTest(action=action,voice=voice,selection=selection):
                        candidate,result=tab.score_command(song,raw,dict(action=action,track='guitar',voice=voice,selection=selection))
                        selected={g['occurrence'] for g in selection}
                        for name,p in candidate['score']['patterns'].items():
                            for b in p['beats']:
                                old=tab._beat(song['score'],name,b['id'])
                                if 'o'+name.lower() in selected and b['voice']==voice:
                                    self.assertEqual(b['notes'],[])
                                    self.assertEqual(b['at'],old['at']);self.assertEqual(b['written'],old['written'])
                                else:self.assertEqual(b,old)
                        self.assertEqual(result['selection']['voice'],voice)
                        if voice==1:self.assertEqual(candidate['score']['ties'],song['score']['ties'])
                        else:self.assertEqual(candidate['score']['ties'],[])
                        if action=='cut':self.assertEqual({b['voice'] for b in result['clipboard']['beats']},{0,1} if 'oa' in selected else {0})
        self.assertEqual(song,original)

    def test_delete_rest_only_closes_active_voice_and_clean_clears_both(self):
        song,raw,groups=self.fixture();song['score']['ties']=[]
        for b in song['score']['patterns']['A']['beats']:
            if b['voice']==0:b['notes']=[]
        selection=[groups[0]];original=copy.deepcopy(song)
        for action in ('cut','delete'):
            candidate,_=tab.score_command(song,raw,dict(action=action,track='guitar',voice=0,selection=selection))
            self.assertEqual(tab._beat(candidate['score'],'A','lower'),tab._beat(song['score'],'A','lower'))
            rests=[b for b in candidate['score']['patterns']['A']['beats'] if b['voice']==0]
            self.assertTrue(all(not b['notes'] for b in rests))
            self.assertEqual([b['at'] for b in rests],[[i,1] for i in range(4)])
            self.assertFalse({b['id'] for b in rests}&set(groups[0]['beats']))
        cleaned,_=tab.score_command(song,raw,dict(action='clean_beat',track='guitar',voice=0,selection=selection))
        self.assertTrue(all(not b['notes'] for b in cleaned['score']['patterns']['A']['beats']))
        self.assertEqual(song,original)

    def test_repeat_uses_replace_ties_fresh_ids_and_immutable_payload(self):
        song, raw, groups = self.fixture()
        before = copy.deepcopy((song, raw, groups))
        edit = dict(action='repeat', track='guitar', selection=groups)
        first, report = tab.score_command(song, raw, edit)
        second, again = tab.score_command(first, raw, edit)
        self.assertEqual((song, raw, groups), before)
        self.assertEqual(report['clipboard'], again['clipboard'])
        self.assertEqual([g['occurrence'] for g in report['selection']['range']], ['oc','od'])
        self.assertEqual(len(second['score']['ties']), 2)
        for name in ('C','D'):
            self.assertFalse({b['id'] for b in first['score']['patterns'][name]['beats']} &
                             {b['id'] for b in second['score']['patterns'][name]['beats']})
        self.assertEqual(second['score']['patterns']['A'], song['score']['patterns']['A'])
        tab.project_score(second, raw)

    def test_cross_commands_refuse_atomically(self):
        song, raw, groups = self.fixture()
        for action, case, message in [('cut','shared','unique source'), ('cut','approved','approved'),
                ('cut','rest',None), ('cut','tie','every onset'), ('cut','hole','every onset'),
                ('repeat','shared','unique destination'), ('repeat','approved','approved'),
                ('repeat','overflow',None), ('repeat','raw','raw note')]:
            with self.subTest(action=action,case=case):
                source, patterns, selection = copy.deepcopy((song,raw,groups))
                name = 'B' if action == 'cut' else 'D'
                if case == 'shared': source['orders'].append(name); source['score']['order_ids'].append('again')
                if case == 'approved': source['patterns'][name]['approved'] = True
                if case == 'rest':
                    for p in source['score']['patterns'].values():
                        for b in p['beats']: b['notes'] = []
                    source['score']['ties'] = []
                if case == 'tie': selection[1]['beats'].remove('b0')
                if case == 'hole': selection[0]['beats'].remove('lower')
                if case == 'overflow': source['orders']=source['orders'][:3]; source['score']['order_ids']=source['score']['order_ids'][:3]
                if case == 'raw': patterns[3].rows[12][0].note = 67
                before = copy.deepcopy((source,patterns,selection))
                if message:
                    with self.assertRaisesRegex(ValueError,message):
                        tab.score_command(source,patterns,dict(action=action,track='guitar',selection=selection))
                else:
                    candidate, report = tab.score_command(source,patterns,dict(action=action,track='guitar',selection=selection))
                    if case == 'overflow':
                        self.assertGreater(len(candidate['orders']),len(source['orders']))
                    else:
                        self.assertTrue(all(not b['notes'] for p in candidate['score']['patterns'].values() for b in p['beats']))
                self.assertEqual((source,patterns,selection),before)


class TestStemGroups(unittest.TestCase):
    def fixture(self):
        song,raw=plan_fixture();song['score']['ties']=[]
        song['score']['patterns']['A']['beats']=[beat(f'b{i}',[i,2],[note(f'n{i}',64,1,0)],value=8) for i in range(8)]
        song['score']['patterns']['A']['beats'].append(beat('peer',[0,1],[note('low',40,6,0)],value=1,voice=1))
        song['score']['patterns']['B']['beats']=[]
        song['score']['measures']=[dict(id='m',meter=[4,4],**{'from':dict(occurrence='oa',at=[0,1]),'to':dict(occurrence='oa',at=[4,1])})]
        return song,raw

    def test_groups_boundaries_peer_audio_and_noop(self):
        song,raw=self.fixture();original=copy.deepcopy(song)
        request=dict(action='set_stem',occurrence='oa',track='guitar',beat='b1',stem='down')
        candidate,report=tab.score_command(song,raw,request)
        self.assertEqual(report['changed_beats'],[dict(occurrence='oa',beat=b) for b in ('b0','b1')])
        for b in candidate['score']['patterns']['A']['beats']:
            old=tab._beat(song['score'],'A',b['id'])
            self.assertEqual(b,dict(old,stem='down') if b['id'] in ('b0','b1') else old)
        self.assertEqual(tab.playback_plan(candidate,raw),tab.playback_plan(song,raw))
        self.assertEqual(tab.project_score(candidate,raw).patterns,tab.project_score(song,raw).patterns)
        again,report=tab.score_command(candidate,raw,request);self.assertIs(again,candidate);self.assertFalse(report['changed_beats'])
        restored,_=tab.score_command(candidate,raw,dict(request,stem='inherit'));self.assertEqual(restored,song)
        self.assertEqual(song,original)
        song['orders'].append('A');song['score']['order_ids'].append('again')
        candidate,_=tab.score_command(song,raw,request)
        self.assertEqual(tab._beat(candidate['score'],'A','b0')['stem'],'down')

    def test_rests_gaps_quarters_triplets_and_compound_meter(self):
        for kind,expected in (('rest',['b1']),('gap',['b1']),('quarter',['b0']),('triplet',['b0','b1','b2']),('compound',['b0','b1','b2'])):
            song,raw=self.fixture();beats=song['score']['patterns']['A']['beats']
            target='b1'
            if kind=='rest':beats[0]['notes']=[]
            if kind=='gap':beats.pop(0)
            if kind=='quarter':beats.pop(1);beats[0]['written']['value']=4;target='b0'
            if kind=='triplet':
                beats[:]=[beat(f'b{i}',[i,3],[note(f'n{i}',64,1,0)],value=8,tuplet=[3,2]) for i in range(12)]
            if kind=='compound':song['score']['measures'][0]['meter']=[6,8]
            with self.subTest(kind=kind):
                candidate,report=tab.score_command(song,raw,dict(action='set_stem',occurrence='oa',track='guitar',beat=target,stem='up'))
                self.assertEqual([b['beat'] for b in report['changed_beats']],expected)
                self.assertEqual(tab.playback_plan(candidate,raw),tab.playback_plan(song,raw))
        song,raw=self.fixture();song['score']['patterns']['A']['beats'][0]['notes']=[]
        candidate,report=tab.score_command(song,raw,dict(action='set_stem',occurrence='oa',track='guitar',beat='b0',stem='down'))
        self.assertEqual(candidate,song);self.assertFalse(report['changed_beats'])

    def test_shared_approval_and_invalid_payload_are_atomic(self):
        for kind in ('shared','approved','stem','beat','track'):
            song,raw=self.fixture();edit=dict(action='set_stem',occurrence='oa',track='guitar',beat='b1',stem='up')
            if kind=='shared':
                song['orders'].append('A');song['score']['order_ids'].append('again')
                song['score']['measures'].append(dict(id='compound',meter=[6,8],**{'from':dict(occurrence='again',at=[0,1]),'to':dict(occurrence='again',at=[4,1])}))
            if kind=='approved':song['patterns']['A']['approved']=True
            if kind in ('stem','beat','track'):edit[kind]='invalid'
            before=copy.deepcopy((song,raw))
            with self.subTest(kind=kind),self.assertRaises(ValueError):tab.score_command(song,raw,edit)
            self.assertEqual((song,raw),before)


class TestTempoAuthoring(unittest.TestCase):
    def edit(self, bpm=60, **fields):
        return dict(op='tempo_set', occurrence='oa', at=[5, 2], bpm=bpm, **fields)

    def checked(self, song, raw, edit, error=None):
        before = copy.deepcopy((song, raw, [p.lanes for p in raw], edit))
        if error:
            with self.assertRaisesRegex(ValueError, error):
                tab.tempo_edit(song, raw, edit)
            result = None
        else:
            result = tab.tempo_edit(song, raw, edit)
        self.assertEqual((song, raw, [p.lanes for p in raw], edit), before)
        return result

    def test_set_update_clear_preserve_non_effect_fields_and_return_only_residuals(self):
        song, raw = plan_fixture()
        original = Cell(note=62, instrument=1, volcmd=32)
        raw[0].rows[30][0] = copy.deepcopy(original)
        groups = self.checked(song, raw, self.edit())
        self.assertEqual(groups, [(0, [dict(row=30, ch=0, cell='D-5 01 v32 T3C')])])
        raw[0].rows[30][0] = parse_cell(groups[0][1][0]['cell'])
        updated = self.checked(song, raw, self.edit(255))
        self.assertEqual(updated, [(0, [dict(row=30, ch=0, cell='D-5 01 v32 TFF')])])
        cleared = self.checked(song, raw, self.edit(None))
        self.assertEqual(parse_cell(cleared[0][1][0]['cell']), original)

    def test_exact_noops_and_explicit_inherited_value(self):
        song, raw = plan_fixture()
        self.assertEqual(self.checked(song, raw, self.edit(None)), [])
        groups = self.checked(song, raw, self.edit(120))
        self.assertEqual(groups[0][1][0]['cell'], '... .. ... T78')
        raw[0].rows[30][0] = parse_cell(groups[0][1][0]['cell'])
        self.assertEqual(self.checked(song, raw, self.edit(120)), [])
        # A redundant source command remains visible even though the clock collapses it.
        view = tab.authoring_view(song, raw)
        self.assertNotIn('tempos', view)
        self.assertEqual(view['tempo_commands'],
                         [dict(pattern='A', row=30, ch=0, at=[5, 2], bpm=120, automation=None)])

    def test_existing_command_wins_over_earlier_free_slots_and_other_controls_survive(self):
        song, raw = plan_fixture()
        raw[0].rows[30][4] = Cell(effect=20, param=120)
        self.assertEqual(self.checked(song, raw, self.edit())[0][1][0]['ch'], 4)
        raw[0].rows[30][4] = Cell()
        raw[0].rows[30][0] = Cell(effect=24, param=64)
        raw[0].rows[30][1] = Cell(param=1)  # malformed nonempty effect pair is never a free slot
        raw[0].lanes[(30, 2)] = ('e', 1)
        raw[0].lanes[(30, 3)] = ('v', 2)
        raw[0].rows[30][3].volcmd = 48
        groups = self.checked(song, raw, self.edit())
        self.assertEqual(groups, [(0, [dict(row=30, ch=3, cell='... .. v48 T3C')])])
        for cell in raw[0].rows[30]:
            cell.effect, cell.param = 24, 64
        self.checked(song, raw, self.edit(), 'no free unowned effect column')
        self.assertEqual(self.checked(song, raw, self.edit(None)), [])

    def test_automation_owned_command_and_duplicate_commands_refuse(self):
        song, raw = plan_fixture()
        raw[0].rows[30][2] = Cell(effect=20, param=120)
        raw[0].lanes[(30, 2)] = ('e', 3)
        for bpm in (60, 120, None):
            with self.subTest(bpm=bpm):
                self.checked(song, raw, self.edit(bpm), 'automation lane 3')
        self.assertEqual(tab.authoring_view(song, raw)['tempo_commands'][0]['automation'], 3)
        raw[0].lanes[(30, 2)] = ('v', 3)
        self.assertEqual(tab.authoring_view(song, raw)['tempo_commands'][0]['automation'], None)
        self.assertTrue(self.checked(song, raw, self.edit()))
        raw[0].rows[30][4] = Cell(effect=20, param=120)
        self.checked(song, raw, self.edit(), 'multiple T commands')

    def test_reused_patterns_require_explicit_pattern_scope_and_view_is_not_duplicated(self):
        song, raw = plan_fixture()
        song['orders'].append('A')
        song['score']['order_ids'].append('again')
        self.checked(song, raw, self.edit(), 'Make unique')
        self.checked(song, raw, self.edit(scope='occurrence'), 'Make unique')
        groups = self.checked(song, raw, self.edit(scope='pattern'))
        self.assertEqual(len(groups), 1)
        raw[0].rows[30][0] = parse_cell(groups[0][1][0]['cell'])
        raw[0].rows[31][0] = Cell(effect=20, param=60)
        raw[1].rows[0][0] = Cell(effect=20, param=240)
        view = tab.authoring_view(song, raw)
        self.assertEqual(len(view['tempo_commands']), 3)
        self.assertEqual(view['tempo_commands'][1],
                         dict(pattern='A', row=31, ch=0, at=[31, 12], bpm=60, automation=None))
        self.assertEqual(view['tempos'], [{'at': [0, 1], 'bpm': 120}, {'at': [5, 2], 'bpm': 60},
                                         {'at': [4, 1], 'bpm': 240}, {'at': [21, 2], 'bpm': 60}])

    def test_raw_only_pattern_in_native_song_can_receive_a_tempo(self):
        song, raw = plan_fixture()
        song['score']['ties'] = []
        song['score']['patterns'].pop('B')
        edit = dict(op='tempo_set', occurrence='ob', at=[0, 1], bpm=32)
        self.assertEqual(self.checked(song, raw, edit),
                         [(1, [dict(row=0, ch=0, cell='... .. ... T20')])])

    def test_strict_payload_bounds_and_exact_rows(self):
        song, raw = plan_fixture()
        invalid = [
            ({'extra': 1}, 'unsupported fields'), ({'revision': 'old'}, 'unsupported fields'),
            ({'op': 'tempo_clear'}, 'tempo_set'), ({'scope': 'all'}, 'tempo scope'),
            ({'scope': None}, 'tempo scope'), ({'occurrence': 'missing'}, 'unknown tempo occurrence'),
            ({'at': [1, 13]}, 'integral row'), ({'at': [4, 1]}, 'inside the pattern'),
            ({'at': [-1, 1]}, 'expected integer'), ({'at': [0, 0]}, 'expected integer'),
            ({'at': [True, 1]}, 'expected integer'),
            *[({'bpm': value}, 'integer 32..255') for value in (True, 31, 256, 60.0, '60')]]
        for patch, error in invalid:
            with self.subTest(patch=patch):
                self.checked(song, raw, dict(self.edit(), **patch), error)
        for field in ('op', 'occurrence', 'at', 'bpm'):
            edit = self.edit()
            edit.pop(field)
            with self.subTest(missing=field):
                self.checked(song, raw, edit, 'requires|expected')


class TestNativeTempoMap(unittest.TestCase):
    def test_exact_clock_boundaries_inverse_and_validation(self):
        changes = [{'at': [0, 1], 'bpm': 120}, {'at': [1, 1], 'bpm': 60},
                   {'at': [2, 1], 'bpm': 137}]
        clock = tab.TempoClock(125, changes)
        for at in (Fraction(0), Fraction(1), Fraction(3, 2), Fraction(2), Fraction(29, 7)):
            expected = at / 2 if at < 1 else Fraction(1, 2) + (at - 1) if at < 2 else Fraction(3, 2) + (at - 2) * Fraction(60, 137)
            self.assertEqual(clock.seconds_at(at), expected)
            self.assertEqual(clock.quarters_at(expected), at)
        self.assertEqual([clock.tempo_at(x) for x in (0, 1, 2)], [120, 60, 137])
        self.assertEqual(tab.TempoClock(120).seconds_at([3, 2]), Fraction(3, 4))
        for changes in ([], [{'at': [1, 1], 'bpm': 120}],
                        [{'at': [0, 1], 'bpm': 120}, {'at': [0, 2], 'bpm': 60}],
                        [{'at': [0, 1], 'bpm': True}],
                        [{'at': [0, 1], 'bpm': 31}],
                        [{'at': [0, 1], 'bpm': 256}],
                        [{'at': [0, 1], 'bpm': 120, 'seconds': [0, 1]}],
                        [{'at': [0, 1], 'bpm': 120}, {'at': [2**53, 1], 'bpm': 60}]):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                tab.TempoClock(120, changes)
        for value in (-1, .5, True, [1, 0]):
            with self.subTest(value=value), self.assertRaises(ValueError):
                clock.seconds_at(value)

    def test_piecewise_events_positions_duration_and_absolute_rounding(self):
        song, raw = plan_fixture()
        raw[0].rows[12][6] = Cell(effect=20, param=60)
        raw[1].rows[0][6] = Cell(effect=20, param=240)
        before = copy.deepcopy((song, raw))
        changes = [{'at': [0, 1], 'bpm': 120}, {'at': [1, 1], 'bpm': 60}, {'at': [4, 1], 'bpm': 240}]
        for rate in (8000, 44100, 48000, 88200, 96000):
            plan = tab.playback_plan(song, raw, rate)
            self.assertEqual(plan['tempos'], changes)
            self.assertEqual(plan['duration'], {'quarters': [8, 1], 'seconds': [9, 2], 'frames': rate * 9 // 2})
            for event in plan['events']:
                at = Fraction(*event['at'])
                seconds = at / 2 if at < 1 else Fraction(1, 2) + at - 1 if at < 4 else Fraction(7, 2) + (at - 4) / 4
                exact = seconds * rate
                rounded = (2 * exact.numerator + exact.denominator) // (2 * exact.denominator)
                self.assertEqual(Fraction(*event['seconds']), seconds)
                self.assertEqual(event['frame'], rounded)
            head = next(p for p in plan['positions'] if p['id'] == 'ob/headn')
            self.assertEqual(head['seconds'], [7, 2])
            self.assertEqual(head['end_frame'], (rate * 29 + 4) // 8)
        self.assertEqual(tab.authoring_view(song, raw)['tempos'], changes)
        self.assertEqual((song, raw), before)

    def test_repeated_patterns_reapply_commands_and_inherit_between_them(self):
        song, raw = plan_fixture()
        song['orders'].append('A')
        song['score']['order_ids'].append('again')
        raw[0].rows[12][6] = Cell(effect=20, param=60)
        raw[1].rows[0][6] = Cell(effect=20, param=240)
        self.assertEqual(tab.playback_plan(song, raw)['tempos'],
                         [{'at': [0, 1], 'bpm': 120}, {'at': [1, 1], 'bpm': 60},
                          {'at': [4, 1], 'bpm': 240}, {'at': [9, 1], 'bpm': 60}])

    def test_row_zero_override_noops_conflicts_and_slide_refusals(self):
        song, raw = plan_fixture()
        self.assertNotIn('tempos', tab.playback_plan(song, raw))
        raw[0].rows[0][6] = Cell(effect=20, param=150)
        raw[1].rows[0][6] = Cell(effect=20, param=150)
        plan = tab.playback_plan(song, raw)
        self.assertEqual(plan['tempo'], 120)
        self.assertEqual(plan['tempos'], [{'at': [0, 1], 'bpm': 150}])
        self.assertEqual(plan['duration']['seconds'], [16, 5])
        raw[0].rows[0][5] = Cell(effect=20, param=150)
        for view in (tab.playback_plan, tab.authoring_view):
            with self.assertRaisesRegex(ValueError, 'multiple T commands'):
                view(song, raw)
        raw[0].rows[0][5] = Cell()
        for param in (0, 0x0f, 0x10, 0x1f, 256):
            raw[0].rows[0][6].param = param
            with self.subTest(param=param), self.assertRaisesRegex(ValueError, 'absolute T20..FF'):
                tab.playback_plan(song, raw)

    def test_cross_boundary_tie_gates_and_pitch_controls_match_tg_ticks(self):
        song, raw = plan_fixture()
        song['module']['tempo'] = 240
        song['score']['tracks']['guitar']['tuning'] = list(range(60, 66))
        heads = [dict(note(f'h{i}', 60 + i, i + 1, 0), velocity=95) for i in range(6)]
        heads[1]['staccato'], heads[2]['palm_mute'], heads[3]['dead'] = True, True, True
        heads[4]['bend'] = {'points': [dict(position=p, value=v) for p, v in ((0, 0), (6, 4), (12, 0))]}
        heads[5]['vibrato'] = True
        tails = [dict(note(f't{i}', 60 + i, i + 1, 0), velocity=95) for i in range(6)]
        song['score']['patterns']['A']['beats'] = [beat('head', [63, 16], heads, 64)]
        song['score']['patterns']['B']['beats'] = [beat('tail', [0, 1], tails)]
        song['score']['ties'] = [{'from': dict(occurrence='oa', note=f'h{i}'),
                                 'to': dict(occurrence='ob', note=f't{i}')} for i in range(6)]
        raw[1].rows[0][6] = Cell(effect=20, param=60)
        plan = tab.playback_plan(song, raw, 48000)
        releases = {e['id']: e for e in plan['events'] if e['type'] == 'note_off'}
        for i, seconds in enumerate((Fraction(2), Fraction(47, 32), Fraction(19, 16),
                                     Fraction(17, 16), Fraction(2), Fraction(2))):
            self.assertEqual(Fraction(*releases[f'oa/h{i}']['seconds']), seconds)
        bend_peak = next(e for e in plan['events'] if e['id'] == 'oa/h4' and e['type'] == 'pitch' and e['bend_value'] == 75)
        self.assertEqual(bend_peak['at'], [2143, 480])  # TG's integer bend interpolation first reaches peak at tick4286.
        first_vibrato = next(e for e in plan['events'] if e['id'] == 'oa/h5' and e['type'] == 'pitch')
        self.assertEqual(first_vibrato['at'], [197, 48])
        self.assertEqual(first_vibrato['seconds'], [53, 48])
        view = tab.authoring_view(song, raw)
        palm = next(p for p in view['positions'] if p['kind'] == 'note' and p['id'] == 'oa/h2')
        self.assertEqual(palm['sounding_end'], [67, 16])
        # An attack exactly on the boundary uses the new BPM, not the module base.
        song['score']['ties'] = []
        tails[2]['palm_mute'] = True
        plan = tab.playback_plan(song, raw)
        release = next(e for e in plan['events'] if e['type'] == 'note_off' and e['id'] == 'ob/t2')
        self.assertEqual(release['at'], [65, 16])


class TestNativeContexts(unittest.TestCase):
    def fixture(self):
        song, raw = plan_fixture()
        head = dict(note('z_head', 69, 1, 5), let_ring=True, trill=dict(fret=7, value=16), velocity=95)
        later = dict(note('a_later', 71, 1, 7), instrument=2)
        song['samples'][2] = {'file': 'other.wav'}
        song['score']['patterns']['A']['beats'] = [
            beat('z_first', [0, 1], [head]), beat('a_second', [1, 1], [later])]
        song['score']['patterns']['B']['beats'] = []
        song['score']['ties'] = []
        return song, raw, head, later

    def test_interleaved_pulses_keep_source_head_lifecycle_and_release(self):
        song, raw, _, _ = self.fixture()
        before = copy.deepcopy((song, raw))
        plan = tab.playback_plan(song, raw)
        attacks = [e for e in plan['events'] if e['type'] == 'note_on']
        pulses = [e for e in attacks if e.get('source_id') == 'oa/z_head']
        later = next(e for e in attacks if e['id'] == 'oa/a_later')
        self.assertEqual([e['context'] for e in pulses], [1] * 8)
        self.assertEqual([e['source_instrument'] for e in pulses], [1] * 8)
        self.assertEqual((later['context'], later['source_instrument'], later['context_open'], later['context_close']),
                         (2, 2, True, True))
        self.assertEqual([e['context_open'] for e in pulses], [True] + [False] * 7)
        self.assertEqual([e['context_close'] for e in pulses], [False] * 7 + [True])
        self.assertEqual(pulses[-1]['at'], [7, 4])
        self.assertEqual([e['id'] for e in attacks if e['at'] == [1, 1]], ['oa/z_head/pulse/4', 'oa/a_later'])
        self.assertEqual(next(e['at'] for e in plan['events'] if e['type'] == 'note_off' and e['id'] == pulses[-1]['id']),
                         [1919, 960])
        self.assertTrue(all(not any(k.startswith('context') for k in e) for e in plan['events'] if e['type'] != 'note_on'))
        self.assertFalse(any(e.get('hold') for e in plan['events']))
        self.assertEqual((song, raw), before)

    def test_before_grace_opens_at_actual_attack_and_main_reuses_context(self):
        song, raw, head, later = self.fixture()
        head.pop('trill')
        head.pop('let_ring')
        later['grace'] = dict(fret=2, value=16, velocity=47)
        plan = tab.playback_plan(song, raw)
        attacks = [e for e in plan['events'] if e['type'] == 'note_on']
        self.assertEqual([e['at'] for e in attacks], [[0, 1], [3, 4], [1, 1]])
        self.assertEqual([e['context'] for e in attacks], [1, 2, 2])
        self.assertEqual([(e['context_open'], e['context_close']) for e in attacks],
                         [(True, True), (True, False), (False, True)])
        self.assertEqual(attacks[1]['source_id'], 'oa/a_later')
        self.assertNotIn('source_id', attacks[2])
        view = tab.authoring_view(song, raw)
        predecessor = next(p for p in view['positions'] if p['kind'] == 'note' and p['id'] == 'oa/z_head')
        self.assertEqual((predecessor['sounding_start'], predecessor['sounding_end']), ([0, 1], [1, 1]))
        self.assertEqual(view['ownership'][0]['end'], [1, 1])

    def test_final_frame_order_assigns_keys_after_rational_onset_reversal(self):
        song, raw, head, later = self.fixture()
        head.pop('trill')
        head.pop('let_ring')
        beats = song['score']['patterns']['A']['beats']
        beats[0]['at'], beats[0]['written']['value'] = [750001, 1000000], 32
        later['grace'] = dict(fret=2, value=16, velocity=47)
        attacks = [e for e in tab.playback_plan(song, raw, 8000)['events'] if e['type'] == 'note_on']
        self.assertEqual([e['id'] for e in attacks[:2]], ['oa/z_head', 'oa/a_later/grace'])
        self.assertGreater(Fraction(*attacks[0]['at']), Fraction(*attacks[1]['at']))
        self.assertEqual([e['frame'] for e in attacks[:2]], [3000, 3000])
        self.assertEqual([e['context'] for e in attacks[:2]], [1, 2])

    def test_harmonic_context_preserves_layers_and_main_only_controls(self):
        song, raw, head, later = self.fixture()
        head.pop('trill')
        head['harmonic'] = dict(type='semi', data=0)
        head['vibrato'] = True
        later.update(grace=dict(fret=2, value=16, velocity=47, on_beat=True),
                     harmonic=dict(type='semi', data=0), velocity=95)
        plan = tab.playback_plan(song, raw)
        attacks = [e for e in plan['events'] if e['type'] == 'note_on']
        self.assertEqual([e['context'] for e in attacks], [1, 2, 2])
        self.assertEqual(len(attacks[0]['layers']), 3)
        self.assertNotIn('layers', attacks[1])
        self.assertEqual(len(attacks[2]['layers']), 3)
        self.assertTrue(any(e['type'] == 'pitch' for e in plan['events']))
        self.assertTrue(all('context' not in e for e in plan['events'] if e['type'] != 'note_on'))

    def test_any_context_converts_all_ordinary_held_parents(self):
        song, raw, _, _ = self.fixture()
        song['score']['patterns']['A']['beats'] += [
            beat('bass_first', [0, 1], [dict(note('bass_head', 40, 1, 0), let_ring=True)], track='bass'),
            beat('bass_next', [1, 1], [note('bass_next', 41, 1, 1)], track='bass')]
        plan = tab.playback_plan(song, raw)
        self.assertFalse(any('hold' in e for e in plan['events']))
        self.assertTrue(all('context' in e for e in plan['events'] if e['type'] == 'note_on'))
        bass = [e for e in plan['events'] if e['type'] == 'note_on' and e['ch'] == 6]
        self.assertTrue(all(e['context_open'] and e['context_close'] for e in bass))

    def test_grace_only_short_repetition_closes_on_its_actual_last_attack(self):
        song, raw, head, later = self.fixture()
        head.pop('trill')
        later.update(grace=dict(fret=2, value=16, velocity=47, on_beat=True),
                     tremolo_picking=dict(value=16), velocity=95)
        song['score']['patterns']['A']['beats'][1]['written']['tuplet'] = [192, 49]
        plan = tab.playback_plan(song, raw)
        later_attacks = [e for e in plan['events'] if e['type'] == 'note_on' and e.get('source_id') == 'oa/a_later']
        self.assertEqual(len(later_attacks), 1)
        self.assertEqual((later_attacks[0]['role'], later_attacks[0]['context_open'],
                          later_attacks[0]['context_close']), ('grace', True, True))
        self.assertFalse(any(e['id'] == 'oa/a_later' for e in plan['events']))

    def test_context_parent_guards_cover_unused_backing_and_inherited_later_heads(self):
        for command in ('C-5 01 ... ...', '=== .. ... ...', '... 01 ... ...', '... .. v32 ...',
                        '... .. ... X40', '... .. ... D01', '... .. ... M20'):
            song, raw, _, _ = self.fixture()
            raw.append(Pattern('unused', [[parse_cell(command)] + [Cell() for _ in range(6)]]))
            with self.subTest(command=command), self.assertRaisesRegex(ValueError, 'context overlap cannot share raw'):
                tab.playback_plan(song, raw)
        song, raw, _, _ = self.fixture()
        song['score']['patterns']['A']['beats'].append(
            beat('late', [3, 1], [dict(note('late', 69, 1, 5), instrument=0)]))
        with self.assertRaisesRegex(ValueError, 'context parent requires explicit source'):
            tab.playback_plan(song, raw)
        for command in ('... .. ... T53', '... .. ... V40'):
            song, raw, _, _ = self.fixture()
            raw[1].rows[0][0] = parse_cell(command)
            self.assertTrue(any('context' in e for e in tab.playback_plan(song, raw)['events']))

    def test_context_carry_random_and_all_mapped_samples_refuse(self):
        for field in ('volume_envelope', 'panning_envelope', 'pitch_envelope', 'random_volume', 'random_pan',
                      'sample_random', 'mapped_random'):
            song, raw, _, _ = self.fixture()
            song['instruments'] = {1: {'sample': 1}, 2: {'sample': 2}}
            instrument = song['instruments'][1]
            if field.endswith('envelope'):
                instrument[field] = dict(nodes=[[0, 64], [2, 32]], carry=True)
            elif field in ('random_volume', 'random_pan'):
                instrument[field] = 1
            elif field == 'sample_random':
                song.pop('instruments')
                song['samples'][1]['vibrato'] = dict(type='random', speed=4, depth=1)
            else:
                song['samples'][3] = dict(file='mapped.wav', name='random mapped', vibrato=dict(type='random'))
                instrument['keymap'] = [dict(notes='C-9..B-9', sample='random mapped')]
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, 'context parent refuses'):
                tab.playback_plan(song, raw)
        song, raw, _, _ = self.fixture()
        song['samples'][3] = dict(file='unused.wav', vibrato=dict(type='random'))
        song['instruments'] = {1: dict(sample=3, keymap=[dict(notes='C-0..B-9', sample=1)]),
                               2: dict(sample=2)}
        self.assertTrue(any('context' in e for e in tab.playback_plan(song, raw)['events']))

    def test_repeat_context_identity_and_source_pattern_remain_separate(self):
        song, raw, _, _ = self.fixture()
        song['score']['measures'] = [
            dict(id='first', meter=[4, 4], repeat_close=1,
                 **{'from': dict(occurrence='oa', at=[0, 1])}, to=dict(occurrence='oa', at=[4, 1])),
            dict(id='second', meter=[4, 4],
                 **{'from': dict(occurrence='ob', at=[0, 1])}, to=dict(occurrence='ob', at=[4, 1]))]
        projection = tab.repeat_projection(song, raw)
        opens = [e for e in projection.plan['events'] if e.get('context_open')]
        self.assertEqual([e['context'] for e in opens], [1, 2, 3, 4])
        self.assertEqual([e['source_pattern'] for e in opens], ['A'] * 4)
        self.assertEqual([e['source_note_id'] for e in opens], ['oa/z_head', 'oa/a_later'] * 2)
        self.assertEqual([e['play_id'] for e in opens], ['play_1'] * 2 + ['play_2'] * 2)
        self.assertEqual(len(projection.source_view['occurrences']), 2)

    def schedule(self, rows):
        identities = list(dict.fromkeys(row[0] for row in rows))
        records = [dict(id=identity, occurrence='o', track='t', start=Fraction(i), voice=0)
                   for i, identity in enumerate(identities)]
        timeline = dict(context_parents={0: identities[0]}, occurrences=[dict(id='o')], track_order=['t'],
                        records=records, by_id={r['id']: r for r in records})
        events = [dict(id=f'{identity}/pulse/{index}', source_id=identity, pulse=index,
                       type='note_on', frame=frame, ch=0) for index, (identity, frame) in enumerate(rows)]
        tab._context_schedule(events, timeline)
        return events

    def test_same_head_frame_collision_and_frame_attack_capacity_refuse(self):
        with self.assertRaisesRegex(ValueError, 'same head round to one frame'):
            self.schedule([('a', 0), ('a', 0)])
        self.assertEqual(len(self.schedule([(f'h{i}', 0) for i in range(64)])), 64)
        with self.assertRaisesRegex(ValueError, '64 attacks'):
            self.schedule([(f'h{i}', 0) for i in range(65)])

    def test_live_capacity_releases_only_after_the_final_attack_frame(self):
        rows = [(f'h{i}', 0) for i in range(64)] + [('h0', 10), ('new', 10)]
        rows += [(f'h{i}', 20) for i in range(1, 64)]
        with self.assertRaisesRegex(ValueError, '64 live contexts'):
            self.schedule(rows)
        rows[65] = ('new', 11)
        events = self.schedule(rows)
        new = next(e for e in events if e['source_id'] == 'new')
        self.assertEqual((new['context'], new['context_open'], new['context_close']), (65, True, True))


class TestNativeRepeats(unittest.TestCase):
    def fixture(self, configs):
        song, _ = plan_fixture()
        song['patterns'], song['orders'] = {}, []
        score = song['score']
        score.update(patterns={}, order_ids=[], measures=[], ties=[])
        raw = []
        for i, config in enumerate(configs):
            name, oid = f'P{i}', f'o{i}'
            song['patterns'][name] = dict(rows=48, data='')
            song['orders'].append(name)
            score['order_ids'].append(oid)
            score['patterns'][name] = dict(row_step=[1, 12], beats=[
                beat('b', [0, 1], [note('n', 69 + i % 10, 1, 5 + i % 10)])])
            score['measures'].append(dict(id=f'm{i}', meter=[4, 4],
                **{'from': dict(occurrence=oid, at=[0, 1])},
                to=dict(occurrence=oid, at=[4, 1]), **config))
            raw.append(Pattern(name, [[Cell() for _ in range(7)] for _ in range(48)]))
        return song, raw

    def test_controller_traversals_and_source_identity(self):
        cases = [
            ([{}, {'repeat_close': 1}, {}], [0, 1, 0, 1, 2]),
            ([{}, {'repeat_open': True}, {'repeat_close': 2}, {}], [0, 1, 2, 1, 2, 1, 2, 3]),
            ([{'repeat_open': True}, {'repeat_close': 1}, {'repeat_open': True}, {'repeat_close': 1}],
             [0, 1, 0, 1, 2, 3, 2, 3]),
            ([{'repeat_open': True}, {'repeat_open': True}, {'repeat_close': 1}, {'repeat_close': 1}],
             [0, 1, 2, 1, 2, 3]),
            ([{'repeat_open': True}, {'endings': [1], 'repeat_close': 1}, {'endings': [2]}, {}],
             [0, 1, 0, 2, 3]),
            ([{'repeat_open': True}, {'endings': [1]}, {'repeat_close': 1}, {'endings': [2]}, {}],
             [0, 1, 2, 0, 3, 4]),
            ([{'repeat_open': True}, {'endings': [1], 'repeat_close': 2},
              {'endings': [2], 'repeat_close': 2}, {'endings': [3]}], [0, 1, 0, 2, 0, 3]),
            ([{'repeat_open': True, 'endings': [2]}, {'repeat_close': 1}, {}], [0, 1, 0, 1, 2]),
        ]
        for configs, expected in cases:
            song, raw = self.fixture(configs)
            before = copy.deepcopy((song, raw))
            projection = tab.repeat_projection(song, raw)
            visits = projection.plan['occurrences']
            self.assertEqual([v['source_order'] for v in visits], expected)
            self.assertEqual([v['at'] for v in visits], [[4 * i, 1] for i in range(len(expected))])
            self.assertEqual(projection.orders, expected)
            self.assertEqual(len({v['id'] for v in visits}), len(visits))
            attacks = [e for e in projection.plan['events'] if e['type'] == 'note_on']
            self.assertEqual([e['source_note_id'] for e in attacks], [f'o{i}/n' for i in expected])
            self.assertEqual(len({e['id'] for e in attacks}), len(attacks))
            self.assertEqual((song, raw), before)

    def test_ui_limit_close100_and_all_eight_ending_bits(self):
        song, raw = self.fixture([{'repeat_open': True}, {'repeat_close': 100}, {}])
        projection = tab.repeat_projection(song, raw)
        self.assertEqual(projection.orders, [0, 1] * 101 + [2])
        self.assertEqual([v['pass'] for v in projection.plan['occurrences'][:6]], [1, 1, 2, 2, 3, 3])
        song, raw = self.fixture([{'repeat_open': True},
            {'repeat_close': 7, 'endings': list(range(1, 8))}, {'endings': [8]}, {}])
        self.assertEqual(tab.repeat_projection(song, raw).orders, [0, 1] * 7 + [0, 2, 3])
        song, raw = self.fixture([{'repeat_open': True}, {'repeat_close': 7, 'endings': [1, 3]}, {}])
        self.assertEqual(tab.repeat_projection(song, raw).orders, [0, 1, 0, 2])

    def test_linear_identity_and_public_guards(self):
        song, raw = self.fixture([{}, {}])
        before = tab.playback_plan(song, raw)
        self.assertIsNone(tab.repeat_projection(song, raw))
        song['score']['measures'][0].update(repeat_open=False, repeat_close=0, endings=[])
        self.assertIsNone(tab.repeat_projection(song, raw))
        self.assertEqual(tab.playback_plan(song, raw), before)
        song['score']['measures'][0]['repeat_open'] = True
        with self.assertRaisesRegex(ValueError, 'backing and plan together'):
            tab.playback_plan(song, raw)
        self.assertEqual(tab.project_score(song, raw).orders, [0, 1])
        self.assertEqual(tab.authoring_view(song, raw), tab.repeat_projection(song, raw).source_view)

    def test_repeat_pattern_edit_and_adoption_keep_authored_ownership(self):
        song, raw = self.fixture([{'repeat_close': 1}])
        before = copy.deepcopy((song, raw))
        display = tab.pattern_authoring_view(song, raw, 0, 'o0')
        cell = parse_cell(display['display_rows'][0][0])
        cell.note = 71
        score, residual = tab.translate_native_pattern_edits(
            song, raw, [(0, [dict(row=0, ch=0, cell=format_cell(cell))])], occurrences={0: 'o0'})
        self.assertFalse(residual)
        changed = dict(song, score=score)
        attacks = [e for e in tab.repeat_projection(changed, raw).plan['events'] if e['type'] == 'note_on']
        self.assertEqual([e['pitch'] for e in attacks], [71, 71])
        self.assertEqual((song, raw), before)
        raw[0].rows[24][0] = parse_cell('A-5 01 ... ...')
        raw[0].rows[36][0] = Cell(note=NOTE_OFF)
        projected = tab.repeat_projection(song, raw)
        backing = Module(patterns=raw, orders=[0], native_score=dict(
            plan=projected.plan, view=projected.source_view, backing=projected))
        adopted, residual = tab.promote_pattern(song, backing, 0, 'guitar',
                                                [dict(row=24, ch=0)], occurrence='o0')
        staged = copy.deepcopy(raw)
        for index, cells in residual:
            for change in cells:
                staged[index].rows[change['row']][change['ch']] = parse_cell(change['cell'])
        adopted_plan = tab.repeat_projection(adopted, staged).plan
        self.assertEqual(len([e for e in adopted_plan['events'] if e['type'] == 'note_on']), 4)
        self.assertEqual(len(adopted['orders']), 1)

    def test_schema_edits_and_boundaries(self):
        song, raw = self.fixture([{}, {}])
        measure = song['score']['measures'][0]
        for changes in ({'repeat_open': 1}, {'repeat_close': -1}, {'repeat_close': 101},
                        {'repeat_close': True}, {'endings': [0]}, {'endings': [9]},
                        {'endings': [1, 1]}, {'endings': '1'}, {'endings': [True]}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                tab.apply_score_edit(song, dict(op='measure_set', measure=dict(measure, **changes)))
        candidate = tab.apply_score_edit(song, dict(op='measure_set', measure=dict(measure, repeat_close=1)))
        self.assertNotIn('repeat_close', measure)
        self.assertEqual(tab.repeat_projection(candidate, raw).orders, [0, 0, 1])
        candidate['score']['measures'].pop()
        with self.assertRaisesRegex(ValueError, 'entire arrangement'):
            tab.repeat_projection(candidate, raw)
        song['score']['measures'][0].update(repeat_close=1, meter=[3, 4], to=dict(occurrence='o0', at=[3, 1]))
        with self.assertRaisesRegex(ValueError, 'entire arrangement'):
            tab.repeat_projection(song, raw)
        song, raw = self.fixture([{'repeat_close': 1}, {}])
        song['score']['measures'][0].update(meter=[5, 4], to=dict(occurrence='o1', at=[1, 1]))
        song['score']['measures'][1].update(meter=[3, 4], **{'from': dict(occurrence='o1', at=[1, 1])})
        projected = tab.repeat_projection(song, raw)
        self.assertEqual([v['source_order'] for v in projected.plan['occurrences']], [0, 1, 0, 1, 1])

    def test_tempo_backing_variants_reused_without_source_mutation(self):
        song, raw = self.fixture([{'repeat_open': True}, {'repeat_close': 2}])
        raw[1].rows[0][1] = parse_cell('... .. ... T3C')
        before = copy.deepcopy((song, raw))
        result = tab.repeat_projection(song, raw)
        self.assertEqual(result.orders, [0, 1, 2, 1, 2, 1])
        self.assertEqual(len(result.patterns), 3)
        self.assertEqual((result.patterns[2].rows[0][0].effect, result.patterns[2].rows[0][0].param), (20, 120))
        self.assertIs(result.patterns[0], raw[0])
        self.assertEqual(result.plan['tempos'], [
            dict(at=[i * 4, 1], bpm=120 if i % 2 == 0 else 60) for i in range(6)])
        self.assertEqual(result.plan['duration']['seconds'], [18, 1])
        self.assertEqual((song, raw), before)
        # A source row-zero T needs no variant or overwrite.
        raw[0].rows[0][2] = parse_cell('... .. ... T78')
        self.assertEqual(tab.repeat_projection(song, raw).orders, [0, 1, 0, 1, 0, 1])

    def test_tempo_reset_free_slot_and_capacity_refusal(self):
        song, raw = self.fixture([{'repeat_open': True}, {'repeat_close': 1}])
        raw[1].rows[0][1] = parse_cell('... .. ... T3C')
        for ch in range(7):
            raw[0].rows[0][ch] = parse_cell('... .. ... X40')
        with self.assertRaisesRegex(ValueError, 'no free row-zero effect slot'):
            tab.repeat_projection(song, raw)
        raw[0].rows[0][5] = Cell()
        result = tab.repeat_projection(song, raw)
        self.assertEqual(result.patterns[2].rows[0][5].effect, 20)
        self.assertEqual(result.patterns[2].rows[0][0].effect, 24)
        raw.extend(Pattern(f'unused{i}', [[Cell() for _ in range(7)]]) for i in range(252))
        with self.assertRaisesRegex(ValueError, '254 backing patterns'):
            tab.repeat_projection(song, raw)

    def test_skipped_source_tempo_restores_first_played_entry(self):
        song, raw = self.fixture([{'endings': [2], 'repeat_close': 1}, {}])
        raw[0].rows[24][0] = parse_cell('... .. ... T3C')
        result = tab.repeat_projection(song, raw)
        self.assertEqual(result.orders, [2])
        self.assertEqual(result.plan['tempos'], [dict(at=[0, 1], bpm=60)])
        self.assertEqual(result.plan['duration']['seconds'], [4, 1])
        self.assertEqual(result.plan['occurrences'][0]['source_order'], 1)

    def test_tie_releases_differ_per_pass_and_source_view_stays_authored(self):
        song, raw = self.fixture([{'repeat_close': 1}, {}])
        for name in song['orders']:
            b = song['score']['patterns'][name]['beats'][0]
            b['written']['value'] = 1
            b['notes'][0].update(pitch=69, fret=5)
        song['score']['ties'] = [dict(**{'from': dict(occurrence='o0', note='n')}, to=dict(occurrence='o1', note='n'))]
        result = tab.repeat_projection(song, raw)
        self.assertEqual([(e['type'], e['at']) for e in result.plan['events']],
                         [('note_on', [0, 1]), ('note_off', [4, 1]), ('note_on', [4, 1]), ('note_off', [12, 1])])
        view = result.source_view
        self.assertEqual([o['id'] for o in view['occurrences']], ['o0', 'o1'])
        p = next(p for p in view['positions'] if p['kind'] == 'note' and p['id'] == 'o0/n')
        self.assertEqual((p['at'], p['end']), ([0, 1], [4, 1]))
        self.assertTrue(p['performed_ambiguous'])
        self.assertTrue(p['performed_readonly'])
        self.assertNotIn('sounding_end', p)
        self.assertEqual([v['sounding_end'] for v in p['performed_variants']], [[4, 1], [8, 1]])
        self.assertEqual(view['ownership'][0]['end'], [4, 1])
        pattern = tab.pattern_authoring_view(song, raw, 0, 'o0', view=view)
        self.assertEqual(pattern['occurrence'], 'o0')
        self.assertTrue(next(p for p in pattern['positions'] if p['kind'] == 'note')['performed_ambiguous'])
        self.assertTrue(all(b['occurrence'] == 'o0' for b in pattern['bindings']))

    def test_pattern_release_overlay_is_readonly_with_source_binding(self):
        song, raw = self.fixture([{'repeat_close': 1}])
        result = tab.repeat_projection(song, raw)
        pattern = tab.pattern_authoring_view(song, raw, 0, 'o0', view=result.source_view)
        release = next(b for b in pattern['bindings'] if b['role'] == 'release')
        self.assertEqual((release['occurrence'], release['row'], release['note']), ('o0', 12, 'n'))
        self.assertTrue(release['readonly'])
        self.assertFalse(release['performed_ambiguous'])

    def test_unmatched_performed_tie_refuses(self):
        song, raw = self.fixture([{'endings': [2], 'repeat_close': 1}, {}])
        for name in song['orders']:
            b = song['score']['patterns'][name]['beats'][0]
            b['written']['value'] = 1
            b['notes'][0].update(pitch=69, fret=5)
        song['score']['ties'] = [dict(**{'from': dict(occurrence='o0', note='n')}, to=dict(occurrence='o1', note='n'))]
        with self.assertRaisesRegex(ValueError, 'unmatched performed tie'):
            tab.repeat_projection(song, raw)

    def test_source_region_uses_one_contiguous_played_span(self):
        song, raw = self.fixture([{'repeat_close': 1}, {}])
        plan = tab.repeat_projection(song, raw).plan
        self.assertEqual(tab.resolve_source_region(plan, (0, 0, 1, 47)), (0, 0, 2, 47))
        self.assertEqual(tab.resolve_source_region(plan, (0, 0, 0, 47)), (0, 0, 1, 47))
        self.assertEqual(tab.resolve_source_region(plan, (1, 3, 1, 9)), (2, 3, 2, 9))
        with self.assertRaisesRegex(ValueError, 'disjoint'):
            tab.resolve_source_region(plan, (0, 3, 0, 9))
        for region in ((-1, 0, 0, 0), (0, 0, 2, 0), (0, 0, 1, 48), (0, 5, 0, 4)):
            with self.assertRaises(ValueError):
                tab.resolve_source_region(plan, region)
        song, raw = self.fixture([{'repeat_open': True}, {'repeat_close': 1}, {'endings': [2]}, {}])
        plan = tab.repeat_projection(song, raw).plan
        with self.assertRaisesRegex(ValueError, 'disjoint'):
            tab.resolve_source_region(plan, (0, 0, 0, 47))
        song, raw = self.fixture([{'endings': [2], 'repeat_close': 1}, {}])
        plan = tab.repeat_projection(song, raw).plan
        with self.assertRaisesRegex(ValueError, 'unreachable'):
            tab.resolve_source_region(plan, (0, 0, 0, 47))
        region = (0, 0, 0, 47)
        self.assertIs(tab.resolve_source_region({}, region), region)

    def test_repeat_order_capacity_refuses_before_projection(self):
        song, raw = self.fixture([{'repeat_open': True}, {}, {'repeat_close': 100}])
        with self.assertRaisesRegex(ValueError, '255 played orders'):
            tab.repeat_projection(song, raw)

    def test_ring_close_provenance_applies_even_on_final_pass(self):
        song, raw = self.fixture([{'repeat_close': 1}, {}])
        for i, name in enumerate(song['orders']):
            b = song['score']['patterns'][name]['beats'][0]
            b['written']['value'] = 1
            b['notes'][0] = dict(note('n', 69 if i == 0 else 62, 1 if i == 0 else 2, 5 if i == 0 else 3), let_ring=True)
        result = tab.repeat_projection(song, raw)
        self.assertEqual([e['at'] for e in result.plan['events'] if e['type'] == 'note_off'], [[4, 1], [8, 1], [12, 1]])

    def test_odd_meter_repeat_uses_source_swing_phase(self):
        song, raw = self.fixture([{'repeat_close': 1, 'swing': 'eighth'}, {'swing': 'eighth'}])
        raw[0].rows = raw[0].rows[:18]
        song['patterns']['P0']['rows'] = 18
        song['score']['measures'][0].update(meter=[3, 8], to=dict(occurrence='o0', at=[3, 2]))
        for spec in song['score']['patterns'].values():
            spec['beats'][0]['written']['value'] = 8
        result = tab.repeat_projection(song, raw)
        self.assertEqual([e['at'] for e in result.plan['events'] if e['type'] == 'note_on'],
                         [[0, 1], [3, 2], [19, 6]])
        self.assertEqual([e['at'] for e in result.plan['events'] if e['type'] == 'note_off'],
                         [[2, 3], [13, 6], [7, 2]])

    def test_generated_children_keep_performed_parent_and_source_binding(self):
        for technique in ('grace', 'tremolo_picking'):
            song, raw = self.fixture([{'repeat_close': 1}])
            head = song['score']['patterns']['P0']['beats'][0]['notes'][0]
            head['velocity'] = 95
            head[technique] = dict(fret=2, value=16, velocity=47, on_beat=True) if technique == 'grace' else dict(value=16)
            result = tab.repeat_projection(song, raw)
            children = [e for e in result.plan['events'] if 'source_id' in e]
            self.assertTrue(children)
            for event in children:
                self.assertEqual(event['source_id'], f"{event['play_id']}/n")
                self.assertEqual(event['source_note_id'], 'o0/n')
                self.assertEqual(event['source_occurrence'], 'o0')


class TestRepeatFragments(unittest.TestCase):
    def fixture(self, close=1):
        song, raw = TestNativeRepeats().fixture([{}])
        song['score']['patterns']['P0']['beats'] = [
            beat(f'b{i}', [i, 1], [note(f'n{i}', 69, 1, 5)]) for i in range(4)]
        song['score']['measures'] = [
            dict(id='left', meter=[2, 4], repeat_open=True,
                 **{'from': dict(occurrence='o0', at=[0, 1])}, to=dict(occurrence='o0', at=[2, 1])),
            dict(id='right', meter=[2, 4], repeat_close=close,
                 **{'from': dict(occurrence='o0', at=[2, 1])}, to=dict(occurrence='o0', at=[4, 1]))]
        return song, raw

    def test_slices_onset_ownership_source_rows_and_cache(self):
        song, raw = self.fixture()
        raw[0].rows[23][6] = Cell(effect=13, param=31)
        raw[0].rows[24][6] = Cell(effect=22, param=80)
        raw[0].lanes = {(23, 6): ('e', 1), (24, 6): ('e', 2)}
        before = copy.deepcopy((song, raw, raw[0].lanes))
        result = tab.repeat_projection(song, raw)
        visits = result.plan['occurrences']
        self.assertEqual(result.orders, [1, 2, 1, 2])
        self.assertEqual([len(p.rows) for p in result.patterns], [48, 24, 24])
        self.assertEqual([v['source_from'] for v in visits], [[0, 1], [2, 1]] * 2)
        self.assertEqual([v['source_at'] for v in visits], [[0, 1], [2, 1]] * 2)
        self.assertEqual([v['at'] for v in visits], [[i * 2, 1] for i in range(4)])
        self.assertEqual(len({v['measure_play_id'] for v in visits}), 4)
        self.assertEqual(result.patterns[1].lanes, {(23, 6): ('e', 1)})
        self.assertEqual(result.patterns[2].lanes, {(0, 6): ('e', 2)})
        self.assertEqual(result.patterns[2].rows[0][6], raw[0].rows[24][6])
        self.assertIsNot(result.patterns[2].rows[0][6], raw[0].rows[24][6])
        attacks = [e for e in result.plan['events'] if e['type'] == 'note_on']
        self.assertEqual([e['source_note_id'] for e in attacks], [f'o0/n{i}' for i in range(4)] * 2)
        positions = result.plan['positions']
        self.assertEqual([p['row'] for p in positions], [[0, 1], [12, 1]] * 4)
        self.assertEqual([p['source_row'] for p in positions], [[i * 12, 1] for i in range(4)] * 2)
        self.assertEqual([p['local_at'] for p in positions], [[0, 1], [1, 1]] * 4)
        self.assertEqual([p['source_local_at'] for p in positions], [[i, 1] for i in range(4)] * 2)
        self.assertEqual([p['source_end_row'] for p in positions], [[(i + 1) * 12, 1] for i in range(4)] * 2)
        self.assertEqual((song, raw, raw[0].lanes), before)
        self.assertEqual([p['id'] for p in result.source_view['positions'] if p['kind'] == 'note'],
                         [f'o0/n{i}' for i in range(4)])

    def test_selected_rows_intersect_fragments_and_refuse_gaps(self):
        song, raw = self.fixture(close=0)
        plan = tab.repeat_projection(song, raw).plan
        self.assertEqual(tab.resolve_source_region(plan, (0, 18, 0, 29)), (0, 18, 1, 5))
        self.assertEqual(tab.resolve_source_region(plan, (0, 30, 0, 35)), (1, 6, 1, 11))
        self.assertEqual(tab.resolve_source_region(plan, (0, 23, 0, 24)), (0, 23, 1, 0))
        song['score']['measures'][1]['repeat_close'] = 1
        plan = tab.repeat_projection(song, raw).plan
        with self.assertRaisesRegex(ValueError, 'disjoint'):
            tab.resolve_source_region(plan, (0, 18, 0, 29))
        self.assertEqual(tab.resolve_source_region(plan, (0, 0, 0, 47)), (0, 0, 3, 23))
        song['score']['measures'][0].pop('repeat_open')
        song['score']['measures'][0].update(endings=[2], repeat_close=1)
        song['score']['measures'][1]['repeat_close'] = 0
        plan = tab.repeat_projection(song, raw).plan
        with self.assertRaisesRegex(ValueError, 'unreachable'):
            tab.resolve_source_region(plan, (0, 0, 0, 23))

    def test_cross_order_measure_ring_stops_at_measure_not_fragment(self):
        song, raw = TestNativeRepeats().fixture([{}, {}])
        song['score']['patterns']['P0']['beats'] = [
            beat('ring', [2, 1], [dict(note('ring', 69, 1, 5), let_ring=True)], value=2)]
        song['score']['patterns']['P1']['beats'] = [
            beat('other', [0, 1], [dict(note('other', 62, 2, 3), let_ring=True)], value=2),
            beat('tail', [2, 1], [note('tail', 55, 3, 0)], value=2)]
        song['score']['measures'] = [
            dict(id='first', meter=[2, 4], **{'from': dict(occurrence='o0', at=[0, 1])},
                 to=dict(occurrence='o0', at=[2, 1])),
            dict(id='middle', meter=[4, 4], repeat_close=1,
                 **{'from': dict(occurrence='o0', at=[2, 1])}, to=dict(occurrence='o1', at=[2, 1])),
            dict(id='last', meter=[2, 4], **{'from': dict(occurrence='o1', at=[2, 1])},
                 to=dict(occurrence='o1', at=[4, 1]))]
        result = tab.repeat_projection(song, raw)
        visits = result.plan['occurrences']
        self.assertEqual([v['source_order'] for v in visits], [0, 0, 1, 0, 0, 1, 1])
        self.assertEqual(visits[1]['measure_play_id'], visits[2]['measure_play_id'])
        self.assertEqual(visits[4]['measure_play_id'], visits[5]['measure_play_id'])
        self.assertNotEqual(visits[1]['measure_play_id'], visits[4]['measure_play_id'])
        self.assertEqual(visits[2]['source_at'], [4, 1])
        releases = [e for e in result.plan['events'] if e['type'] == 'note_off' and e['note'] == 'ring']
        self.assertEqual([e['at'] for e in releases], [[6, 1], [12, 1]])

    def test_tempo_slice_reset_variant_is_distinct_from_no_reset(self):
        song, raw = self.fixture(close=2)
        raw[0].rows[12][6] = Cell(effect=20, param=60)
        raw[0].rows[36][6] = Cell(effect=20, param=90)
        result = tab.repeat_projection(song, raw)
        self.assertEqual(result.orders, [1, 2, 3, 2, 3, 2])
        self.assertEqual(result.patterns[1].rows[0][0].effect, 0)
        self.assertEqual((result.patterns[3].rows[0][0].effect, result.patterns[3].rows[0][0].param), (20, 120))
        self.assertEqual(result.plan['tempos'], [
            dict(at=[at, 1], bpm=bpm) for at, bpm in
            [(0, 120), (1, 60), (3, 90), (4, 120), (5, 60), (7, 90), (8, 120), (9, 60), (11, 90)]])
        raw[0].rows[0][6] = Cell(effect=20, param=120)
        self.assertEqual(tab.repeat_projection(song, raw).orders, [1, 2] * 3)
        raw[0].rows[0] = [Cell(effect=24, param=64) for _ in range(7)]
        with self.assertRaisesRegex(ValueError, 'no free row-zero effect slot'):
            tab.repeat_projection(song, raw)

    def test_inherited_instrument_uses_only_played_raw_rows(self):
        song, raw = self.fixture(close=0)
        song['score']['patterns']['P0']['beats'] = [
            beat('n', [2, 1], [dict(note('n', 69, 1, 5), instrument=0)])]
        raw[0].rows[23][0] = Cell(instrument=1)
        raw[0].rows[36][0] = Cell(note=NOTE_OFF)
        result = tab.repeat_projection(song, raw)
        attack = next(e for e in result.plan['events'] if e['type'] == 'note_on')
        self.assertEqual((attack['instrument'], attack['instrument_inherited']), (1, True))
        song['score']['measures'][0].pop('repeat_open')
        song['score']['measures'][0].update(endings=[2], repeat_close=1)
        with self.assertRaisesRegex(ValueError, 'instrument inheritance'):
            tab.repeat_projection(song, raw)

    def test_tie_across_measure_cut_and_skipped_predecessor(self):
        song, raw = self.fixture()
        song['score']['ties'] = [dict(**{'from': dict(occurrence='o0', note='n1')},
                                    to=dict(occurrence='o0', note='n2'))]
        result = tab.repeat_projection(song, raw)
        self.assertEqual(len([e for e in result.plan['events'] if e['type'] == 'note_on']), 6)
        continuation = next(p for p in result.plan['positions'] if p['id'] == 'play_2/n2')
        self.assertEqual(continuation['attack_id'], 'play_1/n1')
        self.assertTrue(continuation['tied_in'])
        song['score']['measures'][0].pop('repeat_open')
        song['score']['measures'][0].update(endings=[2], repeat_close=1)
        song['score']['measures'][1]['repeat_close'] = 0
        with self.assertRaisesRegex(ValueError, 'unmatched performed tie'):
            tab.repeat_projection(song, raw)

    def test_before_grace_keeps_later_fragment_identity_and_context_source(self):
        song, raw = self.fixture()
        beats = song['score']['patterns']['P0']['beats']
        for b in beats:
            b['notes'][0]['velocity'] = 95
        beats[2]['notes'][0]['grace'] = dict(fret=2, value=16, velocity=47, on_beat=False)
        result = tab.repeat_projection(song, raw)
        grace = next(e for e in result.plan['events'] if e['type'] == 'note_on' and e.get('role') == 'grace')
        self.assertEqual((grace['play_id'], grace['source_id'], grace['source_note_id']),
                         ('play_2', 'play_2/n2', 'o0/n2'))
        self.assertLess(Fraction(*grace['at']), 2)
        self.assertEqual(grace['source_pattern'], 'P0')
        self.assertIn('context', grace)

    def test_fractional_quarter_order_boundary_is_row_aligned(self):
        song, raw = TestNativeRepeats().fixture([{}, {}])
        for name, pattern, rows in zip(song['orders'], raw, (5, 7)):
            pattern.rows = pattern.rows[:rows]
            song['patterns'][name]['rows'] = rows
            song['score']['patterns'][name]['beats'] = []
        song['score']['measures'] = [dict(id='cross', meter=[1, 4], repeat_close=1,
            **{'from': dict(occurrence='o0', at=[0, 1])}, to=dict(occurrence='o1', at=[7, 12]))]
        result = tab.repeat_projection(song, raw)
        self.assertEqual(result.orders, [0, 1, 0, 1])
        self.assertEqual([v['source_at'] for v in result.plan['occurrences']], [[0, 1], [5, 12]] * 2)
        self.assertEqual(result.plan['occurrences'][0]['measure_play_id'],
                         result.plan['occurrences'][1]['measure_play_id'])

    def test_fractional_measure_cut_keeps_authored_swing_phase(self):
        song, raw = self.fixture()
        first, second = song['score']['measures']
        first.update(meter=[3, 8], to=dict(occurrence='o0', at=[3, 2]))
        second.update(meter=[5, 8], swing='eighth',
                      **{'from': dict(occurrence='o0', at=[3, 2])})
        song['score']['patterns']['P0']['beats'] = [
            beat('odd', [3, 2], [note('odd', 69, 1, 5)], value=8),
            beat('even', [2, 1], [note('even', 69, 1, 5)], value=8)]
        result = tab.repeat_projection(song, raw)
        self.assertEqual([len(result.patterns[i].rows) for i in result.orders], [18, 30] * 2)
        self.assertEqual([e['at'] for e in result.plan['events'] if e['type'] == 'note_on'],
                         [[5, 3], [2, 1], [17, 3], [6, 1]])

    def test_slice_local_volume_conflict_and_unused_raw_guards(self):
        song, raw = self.fixture()
        song['score']['patterns']['P0']['beats'][2]['notes'][0]['volume'] = 30
        raw[0].rows[24][0] = Cell(volcmd=23)
        with self.assertRaisesRegex(ValueError, 'play_2/n2: raw volume conflicts'):
            tab.repeat_projection(song, raw)
        raw[0].rows[24][0] = Cell()
        raw.append(Pattern('unused', [[Cell(effect=1, param=6)] + [Cell() for _ in range(6)]]))
        with self.assertRaisesRegex(ValueError, 'unused: raw tempo/speed/flow'):
            tab.repeat_projection(song, raw)

    def test_non_grid_cut_crossing_beat_and_capacity_refuse_without_mutation(self):
        song, raw = self.fixture()
        measures = song['score']['measures']
        measures[0].update(meter=[1, 64], to=dict(occurrence='o0', at=[1, 16]))
        measures[1].update(meter=[63, 64], **{'from': dict(occurrence='o0', at=[1, 16])})
        before = copy.deepcopy((song, raw))
        with self.assertRaisesRegex(ValueError, 'align exactly to backing rows'):
            tab.repeat_projection(song, raw)
        self.assertEqual((song, raw), before)
        song, raw = self.fixture()
        song['score']['patterns']['P0']['beats'] = [beat('crossing', [1, 1], [], value=2)]
        with self.assertRaisesRegex(ValueError, 'written beat crosses.*split and tie'):
            tab.repeat_projection(song, raw)
        song, raw = self.fixture()
        raw.extend(Pattern(f'unused{i}', [[Cell() for _ in range(7)]]) for i in range(253))
        with self.assertRaisesRegex(ValueError, '254 backing patterns'):
            tab.repeat_projection(song, raw)
        song, raw = self.fixture()
        song['score']['measures'] = [dict(id='all', meter=[4, 4], repeat_close=100,
            **{'from': dict(occurrence='o0', at=[0, 1])}, to=dict(occurrence='o0', at=[4, 1]))]
        # One measure spans three occurrences: 101 measure visits exceed 255 fragments.
        song['patterns']['P0']['rows'] = 16
        raw[0].rows = raw[0].rows[:16]
        song['orders'] = ['P0'] * 3
        song['score']['order_ids'] = ['o0', 'o1', 'o2']
        song['score']['patterns']['P0']['beats'] = []
        song['score']['measures'][0]['to'] = dict(occurrence='o2', at=[4, 3])
        with self.assertRaisesRegex(ValueError, '255 played orders'):
            tab.repeat_projection(song, raw)


class TestBeatStrokes(unittest.TestCase):
    def fixture(self, direction='down', value=4):
        song, raw = TestNativeRepeats().fixture([{}])
        chord = beat('chord', [0, 1], [
            dict(note(f's{s}', pitch, s, fret), velocity=95)
            for s, pitch, fret in ((1, 65, 1), (3, 58, 3), (6, 46, 6))])
        if direction:
            chord['stroke'] = dict(direction=direction, value=value)
        song['score']['patterns']['P0']['beats'] = [chord]
        return song, raw

    def ticks(self, song, raw):
        plan = tab.repeat_projection(song, raw)
        plan = plan.plan if plan else tab.playback_plan(song, raw)
        return {e['id']: (int(Fraction(*e['at']) * 960),
                          next(int(Fraction(*off['at']) * 960) for off in plan['events']
                               if off['type'] == 'note_off' and off['id'] == e['id']))
                for e in plan['events'] if e['type'] == 'note_on'}

    def test_direction_values_and_written_anchors(self):
        for direction in ('up', 'down'):
            for value in (4, 8, 16, 32, 64):
                song, raw = self.fixture(direction, value)
                before = copy.deepcopy(song)
                increment = (960 + value) // (2 * value)
                expected = dict(zip(('o0/s1', 'o0/s3', 'o0/s6'),
                    [(i * increment, 960) for i in (range(3) if direction == 'up' else (2, 1, 0))]))
                with self.subTest(direction=direction, value=value):
                    self.assertEqual(self.ticks(song, raw), expected)
                view = tab.authoring_view(song, raw)
                positions = [p for p in view['positions'] if p['kind'] == 'note']
                self.assertTrue(all(p['at'] == [0, 1] and p['end'] == [1, 1] for p in positions))
                self.assertEqual([int(Fraction(*p['sounding_start']) * 960) for p in positions],
                                 [expected[p['id']][0] for p in positions])
                self.assertEqual(song, before)
        with self.assertRaisesRegex(ValueError, 'stroke attack is not representable'):
            tab.project_score(song, raw)

    def test_shortest_voice_rest_dots_tuplet_and_sparse_normalization(self):
        song, raw = self.fixture()
        beats = song['score']['patterns']['P0']['beats']
        beats.append(beat('rest', [0, 1], [], value=16, voice=1))
        before = copy.deepcopy(song)
        self.assertEqual(self.ticks(song, raw), {'o0/s1': (60, 960), 'o0/s3': (30, 960), 'o0/s6': (0, 960)})
        rests = [p for p in tab.authoring_view(song, raw)['positions'] if p['kind'] == 'beat' and p['rest']]
        self.assertEqual(rests[0]['stroke'], {'direction': 'down', 'value': 4})
        self.assertEqual(song, before)
        beats[1]['notes'] = [dict(note('other', 61, 2, 2), velocity=77)]
        self.assertEqual(self.ticks(song, raw), {
            'o0/s1': (90, 960), 'o0/s3': (30, 960), 'o0/s6': (0, 960), 'o0/other': (60, 240)})
        beats.pop()
        for written, expected in (
                (dict(value=4, dots=1), [(240, 1440), (120, 1440), (0, 1440)]),
                (dict(value=8, tuplet=[13, 8]), [(74, 295), (37, 295), (0, 295)])):
            beats[0]['written'] = written
            self.assertEqual(self.ticks(song, raw), dict(zip(('o0/s1', 'o0/s3', 'o0/s6'), expected)))

    def test_same_string_voices_share_delay_and_keep_distinct_contexts(self):
        song, raw = self.fixture()
        beats = song['score']['patterns']['P0']['beats']
        other = beat('other', [0, 1], [dict(note('other', 66, 1, 2), velocity=77)], value=16, voice=1)
        beats.append(other)
        self.assertEqual(self.ticks(song, raw), {
            'o0/s1': (60, 960), 'o0/s3': (30, 960), 'o0/s6': (0, 960), 'o0/other': (60, 240)})
        on = [e for e in tab.playback_plan(song, raw)['events'] if e['type'] == 'note_on' and e['at'] == [1, 16]]
        self.assertEqual([e['id'] for e in on], ['o0/s1', 'o0/other'])
        self.assertEqual([e['ch'] for e in on], [0, 0])
        self.assertEqual([e['context'] for e in on], [1, 2])

    def test_tie_heads_only_consume_string_steps_and_rest_resets(self):
        song, raw = self.fixture()
        beats = song['score']['patterns']['P0']['beats']
        later = copy.deepcopy(beats[0])
        later.update(id='later', at=[1, 1])
        for n in later['notes']:
            n['id'] += 'later'
        beats.append(later)
        song['score']['ties'] = [dict(**{'from': dict(occurrence='o0', note='s1')},
                                    to=dict(occurrence='o0', note='s1later'))]
        self.assertEqual(self.ticks(song, raw), {
            'o0/s1': (240, 1920), 'o0/s3': (120, 960), 'o0/s6': (0, 960),
            'o0/s3later': (1080, 1920), 'o0/s6later': (960, 1920)})
        song['score']['ties'] = []
        later.pop('stroke')
        later['at'] = [2, 1]
        beats.insert(1, beat('rest', [1, 1], []))
        ticks = self.ticks(song, raw)
        self.assertTrue(all(ticks[f'o0/s{s}later'] == (1920, 2880) for s in (1, 3, 6)))

    def test_dead_gate_exhaustion_and_staccato_precede_stroke(self):
        for effect, expected in (
                ('dead', [(240, 300), (120, 180), (0, 60)]),
                ('staccato', [(240, 480), (120, 480), (0, 480)])):
            song, raw = self.fixture()
            for n in song['score']['patterns']['P0']['beats'][0]['notes']:
                n[effect] = True
            self.assertEqual(self.ticks(song, raw), dict(zip(('o0/s1', 'o0/s3', 'o0/s6'), expected)))
        # The admitted value8 has delay60 on string3: equality retains all60 ticks.
        song, raw = self.fixture(value=8)
        for n in song['score']['patterns']['P0']['beats'][0]['notes']:
            n['dead'] = True
        self.assertEqual(self.ticks(song, raw)['o0/s3'], (60, 120))

    def test_grace_repetition_harmonics_and_context_preserve_delayed_head(self):
        song, raw = self.fixture()
        chord = song['score']['patterns']['P0']['beats'][0]
        for n in chord['notes']:
            n['grace'] = dict(fret=2, value=16, velocity=47, on_beat=True)
        ticks = self.ticks(song, raw)
        self.assertEqual([ticks[f'o0/s{s}/grace'] for s in (1, 3, 6)],
                         [(240, 480), (120, 360), (0, 240)])
        self.assertEqual([ticks[f'o0/s{s}'] for s in (1, 3, 6)], [(480, 960), (360, 960), (240, 960)])
        for n in chord['notes']:
            n['grace']['on_beat'] = False
            n['harmonic'] = dict(type='semi', data=0)
        chord['at'] = [1, 1]
        song['score']['patterns']['P0']['beats'].insert(0,
            beat('prior', [1, 2], [dict(note('prior3', 58, 3, 3), velocity=95),
                                  dict(note('prior6', 46, 6, 6), velocity=95)], value=8))
        plan = tab.playback_plan(song, raw)
        mains = [e for e in plan['events'] if e['type'] == 'note_on' and e['id'] == 'o0/s6']
        self.assertEqual(mains[0]['at'], [1, 1])
        self.assertEqual(len(mains[0]['layers']), 3)
        self.assertIn('context', mains[0])
        grace = next(e for e in plan['events'] if e['type'] == 'note_on' and e['id'] == 'o0/s6/grace')
        self.assertEqual(grace['source_id'], mains[0]['id'])
        self.assertEqual(grace['context'], mains[0]['context'])
        opened = [e for e in plan['events'] if e.get('context_open')]
        self.assertEqual([e['id'] for e in opened],
                         ['o0/prior3', 'o0/prior6', 'o0/s6/grace', 'o0/s3/grace'])
        self.assertEqual([e['context'] for e in opened], [1, 2, 3, 4])
        song, raw = self.fixture()
        for n in song['score']['patterns']['P0']['beats'][0]['notes']:
            n['tremolo_picking'] = dict(value=16)
        ticks = self.ticks(song, raw)
        self.assertEqual(ticks['o0/s1/pulse/0'], (240, 480))
        self.assertEqual(max(end for identity, (_, end) in ticks.items() if identity.startswith('o0/s1/')), 959)

    def test_swing_repeat_and_pick_are_independent(self):
        song, raw = self.fixture()
        beats = song['score']['patterns']['P0']['beats']
        beats[0]['written']['value'] = 8
        later = copy.deepcopy(beats[0])
        later.update(id='second', at=[1, 2])
        for n in later['notes']:
            n['id'] += 'b'
        beats.append(later)
        song['score']['measures'][0].update(swing='eighth', repeat_close=1)
        result = self.ticks(song, raw)
        self.assertEqual([result[f'play_1/s{s}'] for s in (1, 3, 6)],
                         [(120, 640), (60, 640), (0, 640)])
        self.assertEqual([result[f'play_1/s{s}b'] for s in (1, 3, 6)],
                         [(760, 960), (700, 960), (640, 960)])
        self.assertEqual(result['play_2/s1'], (3960, 4480))
        for b in beats:
            b['pick_stroke'] = 'up'
        self.assertEqual(self.ticks(song, raw), result)
        song, raw = self.fixture(direction=None)
        plain = self.ticks(song, raw)
        song['score']['patterns']['P0']['beats'][0]['pick_stroke'] = 'down'
        self.assertEqual(self.ticks(song, raw), plain)

    def test_cohort_edits_clear_mirror_validate_and_remain_atomic(self):
        song, raw = self.fixture()
        beats = song['score']['patterns']['P0']['beats']
        beats.append(beat('rest', [0, 1], [], value=16, voice=1))
        before = copy.deepcopy(song)
        changed = tab.apply_score_edit(song, dict(op='beat_set', pattern='P0',
            beat=dict(beats[1], stroke=dict(direction='up', value=32), pick_stroke='down')))
        altered = changed['score']['patterns']['P0']['beats']
        self.assertTrue(all(b['stroke'] == dict(direction='up', value=32) and b['pick_stroke'] == 'down' for b in altered))
        changed = tab.apply_score_edit(changed, dict(op='beat_set', pattern='P0',
            beat=dict(altered[1], stroke=None, pick_stroke=None)))
        self.assertTrue(all('stroke' not in b and 'pick_stroke' not in b for b in changed['score']['patterns']['P0']['beats']))
        # A normal edit of the sparse rest retains the shared metadata.
        changed = tab.apply_score_edit(song, dict(op='beat_set', pattern='P0',
            beat=dict(beats[1], written=dict(value=8))))
        self.assertTrue(all(b['stroke'] == beats[0]['stroke'] for b in changed['score']['patterns']['P0']['beats']))
        for field, value in (
                ('stroke', dict(direction='sideways', value=4)), ('stroke', dict(direction='up', value=2)),
                ('stroke', dict(direction='up', value=True)), ('pick_stroke', False)):
            with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                tab.apply_score_edit(song, dict(op='beat_set', pattern='P0', beat=dict(beats[0], **{field: value})))
        beats[1]['stroke'] = dict(direction='up', value=4)
        with self.assertRaisesRegex(ValueError, 'conflicting stroke'):
            tab.validate_score(song)
        beats[1].pop('stroke')
        self.assertEqual(song, before)

    def test_copy_move_and_commands_preserve_sparse_cohort_metadata(self):
        from types import SimpleNamespace
        song, raw = self.fixture()
        beats = song['score']['patterns']['P0']['beats']
        beats[0]['pick_stroke'] = 'up'
        beats.append(beat('rest', [0, 1], [], value=16, voice=1))
        clip = tab.capture_score_clipboard(song, 'P0', ['rest'], 'o0')
        self.assertEqual(clip['beats'][0]['stroke'], beats[0]['stroke'])
        copied = tab.paste_score_clipboard(song, SimpleNamespace(patterns=raw), 0, 24, clip)
        self.assertEqual(copied['score']['patterns']['P0']['beats'][-1]['pick_stroke'], 'up')
        moved = tab.move_beat(song, SimpleNamespace(patterns=raw), 0, 'rest', 24)
        self.assertEqual(moved['score']['patterns']['P0']['beats'][1]['stroke'], beats[0]['stroke'])
        moved['score']['patterns']['P0']['beats'][1]['stroke']['direction'] = 'up'
        with self.assertRaisesRegex(ValueError, 'conflicting stroke/pick_stroke'):
            tab.move_beat(moved, SimpleNamespace(patterns=raw), 0, 'rest', 0)
        repeated, _ = tab.score_command(song, raw, dict(action='repeat', occurrence='o0',
            track='guitar', voice=0, beats=['chord']))
        new = [b for b in repeated['score']['patterns']['P0']['beats'] if b['id'] not in ('chord', 'rest')]
        self.assertTrue(new)
        self.assertTrue(all(b['stroke'] == beats[0]['stroke'] and b['pick_stroke'] == 'up' for b in new))

    def test_delayed_raw_and_inherited_source_refusals(self):
        song, raw = self.fixture()
        raw[0].rows[1][0] = Cell(effect=24, param=64)
        with self.assertRaisesRegex(ValueError, 'stroke delayed attack'):
            tab.playback_plan(song, raw)
        raw[0].rows[1][0] = Cell()
        song['score']['patterns']['P0']['beats'][0]['notes'][0]['instrument'] = 0
        with self.assertRaisesRegex(ValueError, 'delayed stroke.*explicit source'):
            tab.playback_plan(song, raw)
        song, raw = self.fixture()
        song['score']['patterns']['P0']['beats'][0]['notes'][0] = dict(id='bad', pitch=0)
        with self.assertRaisesRegex(ValueError, 'stroke needs resolved strings'):
            tab.playback_plan(song, raw)


class TestWrittenVoiceContexts(unittest.TestCase):
    def fixture(self, same_pitch=False):
        song, raw = TestNativeRepeats().fixture([{}])
        song['score']['patterns']['P0']['beats'] = [
            beat('long', [0, 1], [note('long', 64, 1, 0)], value=4),
            beat('short', [0, 1], [note('short', 64 if same_pitch else 66, 1, 0 if same_pitch else 2)],
                 value=16, voice=1)]
        return song, raw

    def selection(self, **extra):
        selected = dict(pattern=0, r0=0, r1=0, cols=[[0, ['note', 'instrument', 'volume']]],
                        occurrence='o0')
        selected.update(extra)
        return selected

    def test_plain_and_identical_heads_get_independent_contexts_and_gates(self):
        for same in (False, True):
            song, raw = self.fixture(same)
            before = copy.deepcopy((song, raw))
            plan = tab.playback_plan(song, raw)
            ons = [e for e in plan['events'] if e['type'] == 'note_on']
            self.assertEqual([e['id'] for e in ons], ['o0/long', 'o0/short'])
            self.assertEqual([e['context'] for e in ons], [1, 2])
            self.assertTrue(all(e['context_open'] and e['context_close'] and e['ch'] == 0 for e in ons))
            self.assertEqual([(e['id'], e['at']) for e in plan['events'] if e['type'] == 'note_off'],
                             [('o0/short', [1, 4]), ('o0/long', [1, 1])])
            self.assertEqual(len(tab.authoring_view(song, raw)['ownership']), 2)
            self.assertEqual((song, raw), before)
            with self.assertRaisesRegex(ValueError, 'overlapping notes require independent channels'):
                tab.project_score(song, raw)

    def test_staggered_overlap_and_same_voice_or_chord_refusal(self):
        song, raw = self.fixture()
        beats = song['score']['patterns']['P0']['beats']
        beats[1]['at'] = [1, 2]
        plan = tab.playback_plan(song, raw)
        self.assertEqual([e['at'] for e in plan['events'] if e['type'] == 'note_on'], [[0, 1], [1, 2]])
        self.assertTrue(all('context' in e for e in plan['events'] if e['type'] == 'note_on'))
        beats[1]['voice'] = 0
        with self.assertRaisesRegex(ValueError, 'overlapping beats in the same voice'):
            tab.playback_plan(song, raw)
        beats.pop()
        beats[0]['notes'].append(dict(note('other_string', 60, 2, 1), channel=0))
        with self.assertRaisesRegex(ValueError, 'same voice require independent channels'):
            tab.playback_plan(song, raw)

    def test_sources_all_heads_after_off_and_unused_raw_are_guarded(self):
        song, raw = self.fixture()
        song['samples'][2] = dict(file='second.wav')
        beats = song['score']['patterns']['P0']['beats']
        beats[1]['notes'][0]['instrument'] = 2
        beats.append(beat('later', [2, 1], [note('later', 64, 1, 0)]))
        plan = tab.playback_plan(song, raw)
        self.assertEqual([e['source_instrument'] for e in plan['events'] if e['type'] == 'note_on'], [1, 2, 1])
        self.assertTrue(all('context' in e for e in plan['events'] if e['type'] == 'note_on'))
        for b in beats:
            original = b['notes'][0].get('instrument')
            b['notes'][0]['instrument'] = 0
            with self.assertRaisesRegex(ValueError, 'context parent requires explicit source'):
                tab.playback_plan(song, raw)
            if original is None:
                b['notes'][0].pop('instrument')
            else:
                b['notes'][0]['instrument'] = original
        for spec in (dict(vibrato=dict(type='random')),):
            song['samples'][1].update(spec)
            with self.assertRaisesRegex(ValueError, 'random sample auto-vibrato'):
                tab.playback_plan(song, raw)
            song['samples'][1].pop('vibrato')
        for row in (0, 18, 47):
            for cell in (Cell(note=NOTE_OFF), Cell(instrument=1), Cell(volcmd=20),
                         Cell(effect=24, param=64), Cell(effect=4, param=1), Cell(effect=13, param=32)):
                raw[0].rows[row][0] = cell
                with self.subTest(row=row, cell=cell), self.assertRaises(ValueError):
                    tab.playback_plan(song, raw)
        raw[0].rows[0][0] = Cell(effect=20, param=120)
        raw[0].rows[18][0] = Cell(effect=22, param=80)
        raw[0].rows[47][0] = Cell()
        raw[0].rows[18][2] = Cell(effect=24, param=64)
        tab.playback_plan(song, raw)
        raw.append(Pattern('unused', [[Cell(instrument=1)] + [Cell() for _ in range(6)]]))
        with self.assertRaisesRegex(ValueError, 'context overlap cannot share raw instrument'):
            tab.playback_plan(song, raw)

    def test_shortened_performed_gates_do_not_drop_written_context_admission(self):
        song, raw = self.fixture()
        beats = song['score']['patterns']['P0']['beats']
        beats[0]['notes'][0]['dead'] = True
        beats[1]['at'] = [1, 2]
        plan = tab.playback_plan(song, raw)
        self.assertEqual([e['at'] for e in plan['events'] if e['type'] == 'note_off'], [[1, 16], [3, 4]])
        self.assertTrue(all('context' in e for e in plan['events'] if e['type'] == 'note_on'))

    def test_pattern_collision_keeps_all_owners_and_raw_display(self):
        for same in (False, True):
            song, raw = self.fixture(same)
            for b in song['score']['patterns']['P0']['beats']:
                b['notes'][0]['volume'] = 35
            view = tab.pattern_authoring_view(song, raw, 0, 'o0')
            collision = view['collisions'][0]
            self.assertEqual((collision['row'], collision['ch']), (0, 0))
            self.assertEqual([(o['id'], o['voice'], o['role']) for o in collision['owners']],
                             [('o0/long', 0, 'attack'), ('o0/short', 1, 'attack')])
            self.assertTrue(all(set(o['fields']) == {'note', 'instrument', 'volcmd'} for o in collision['owners']))
            self.assertEqual(view['display_rows'][0][0], view['rows'][0][0])
            self.assertFalse(any(b['row'] == 0 and b['ch'] == 0 for b in view['bindings']))
            releases = [b for b in view['bindings'] if b['role'] == 'release']
            self.assertEqual([b['row'] for b in releases], [3, 12])
            self.assertTrue(all(b['readonly'] for b in releases))
        beats = song['score']['patterns']['P0']['beats']
        beats[1]['written']['value'] = 4
        view = tab.pattern_authoring_view(song, raw, 0, 'o0')
        release = next(c for c in view['collisions'] if c['row'] == 12)
        self.assertEqual({o['id'] for o in release['owners']}, {'o0/long', 'o0/short'})
        self.assertTrue(all(o['role'] == 'release' and o['values'] == {'note': NOTE_OFF} for o in release['owners']))
        beats[1]['at'] = [1, 1]
        view = tab.pattern_authoring_view(song, raw, 0, 'o0')
        boundary = next(c for c in view['collisions'] if c['row'] == 12)
        self.assertEqual({o['role'] for o in boundary['owners']}, {'attack', 'release'})

    def test_direct_collision_edits_and_mixed_batch_refuse_atomically(self):
        song, raw = self.fixture()
        before = copy.deepcopy((song, raw))
        for cell in ('C-5 01 ... ...', '... 02 ... ...', '... .. v20 ...'):
            with self.assertRaisesRegex(ValueError, 'multiple source owners'):
                tab.translate_native_pattern_edits(song, raw, [(0, [
                    dict(row=30, ch=2, cell='... .. ... X40'), dict(row=0, ch=0, cell=cell)])])
        score, residual = tab.translate_native_pattern_edits(song, raw,
            [(0, [dict(row=0, ch=0, cell='... .. ... T78')])])
        self.assertIsNone(score)
        self.assertEqual(len(residual), 1)
        self.assertEqual((song, raw), before)

    def test_explicit_note_subset_vs_all_heads_transform_and_tie_guard(self):
        song, raw = self.fixture()
        for action in ('clear', 'transpose', 'volume'):
            with self.subTest(action=action), self.assertRaisesRegex(ValueError, 'multiple source heads'):
                tab.transform_native_selections(song, raw, dict(action=action, semitones=1, volume=30,
                    selections=[self.selection()]))
        score, _ = tab.transform_native_selections(song, raw, dict(action='clear',
            selections=[self.selection(notes=['short'])]))
        self.assertEqual([n['id'] for b in score['patterns']['P0']['beats'] for n in b['notes']], ['long'])
        score, _ = tab.transform_native_selections(song, raw, dict(action='transpose', semitones=1,
            selections=[self.selection(all_heads=True)]))
        self.assertEqual([b['notes'][0]['pitch'] for b in score['patterns']['P0']['beats']], [65, 67])
        with self.assertRaisesRegex(ValueError, 'explicit source'):
            tab.transform_native_selections(song, raw, dict(action='clear', selections=[
                self.selection(notes=['short'], cols=[[0, ['instrument']]])]))
        continued = beat('cont', [1, 1], [note('cont', 64, 1, 0)])
        song['score']['patterns']['P0']['beats'].append(continued)
        song['score']['ties'] = [dict(**{'from': dict(occurrence='o0', note='long')},
                                    to=dict(occurrence='o0', note='cont'))]
        with self.assertRaisesRegex(ValueError, 'complete tied chain'):
            tab.transform_native_selections(song, raw, dict(action='clear',
                selections=[self.selection(notes=['long'])]))

    def test_clipboard_preserves_two_heads_and_refuses_ambiguous_partial_paste(self):
        song, raw = self.fixture()
        with self.assertRaisesRegex(ValueError, 'multiple source heads'):
            tab.capture_native_clipboard(song, raw, self.selection())
        clip = tab.capture_native_clipboard(song, raw, self.selection(all_heads=True))
        self.assertEqual([b['voice'] for b in clip['score']['beats']], [0, 1])
        score, _ = tab.paste_native_clipboard(song, raw, dict(pattern=0, row=24, channel=0, clipboard=clip))
        self.assertEqual(len(score['patterns']['P0']['beats']), 4)
        played = tab.playback_plan(dict(song, score=score), raw)
        self.assertEqual(len([e for e in played['events'] if e['type'] == 'note_on']), 4)
        one = tab.capture_native_clipboard(song, raw, self.selection(notes=['short']))
        self.assertEqual([n['id'] for b in one['score']['beats'] for n in b['notes']], ['short'])
        with self.assertRaisesRegex(ValueError, 'destination is occupied'):
            tab.paste_native_clipboard(song, raw, dict(pattern=0, row=0, channel=0, clipboard=one))
        one['masks']['short'] = ['instrument']
        with self.assertRaisesRegex(ValueError, 'exact destination note'):
            tab.paste_native_clipboard(song, raw, dict(pattern=0, row=0, channel=0, clipboard=one))

    def test_ties_repeats_and_fragment_provenance_remain_separate(self):
        song, raw = self.fixture()
        beats = song['score']['patterns']['P0']['beats']
        beats[0]['written']['value'] = 2
        beats.append(beat('cont', [2, 1], [note('cont', 64, 1, 0)], value=2))
        song['score']['ties'] = [dict(**{'from': dict(occurrence='o0', note='long')},
                                    to=dict(occurrence='o0', note='cont'))]
        song['score']['measures'] = [
            dict(id='first', meter=[2, 4], repeat_open=True,
                 **{'from': dict(occurrence='o0', at=[0, 1])}, to=dict(occurrence='o0', at=[2, 1])),
            dict(id='second', meter=[2, 4], repeat_close=1,
                 **{'from': dict(occurrence='o0', at=[2, 1])}, to=dict(occurrence='o0', at=[4, 1]))]
        plan = tab.repeat_projection(song, raw).plan
        ons = [e for e in plan['events'] if e['type'] == 'note_on']
        self.assertEqual([e['source_note_id'] for e in ons], ['o0/long', 'o0/short'] * 2)
        self.assertEqual([e['context'] for e in ons], [1, 2, 3, 4])
        continuations = [p for p in plan['positions'] if p['source_note_id'] == 'o0/cont']
        self.assertEqual([p['attack_id'] for p in continuations], ['play_1/long', 'play_3/long'])
        self.assertTrue(all(p['tied_in'] for p in continuations))


class TestFadeInMetadata(unittest.TestCase):
    def test_gain_preserves_context_source_order_and_reclock_order(self):
        from vulturetracker.export import _plan_at_rate
        song,raw=TestWrittenVoiceContexts().fixture()
        beats=song['score']['patterns']['P0']['beats']
        beats[0]['notes'][0]['id']='zzz'
        beats[1]['notes'][0]['id']='aaa'
        beats[0]['stroke']=dict(direction='up',value=4)  # One used string, zero offset across voices.
        plain=tab.playback_plan(song,raw)
        beats[0]['notes'][0]['fade_in']=True
        faded=tab.playback_plan(song,raw)
        for plan in (faded,_plan_at_rate(faded,48000)):
            attacks=[e for e in plan['events'] if e['type']=='note_on']
            self.assertEqual([e['id'] for e in attacks],['o0/zzz','o0/aaa'])
            self.assertEqual([e['context'] for e in attacks],[1,2])
        self.assertEqual([e for e in faded['events'] if e['type']!='gain'],plain['events'])
        self.assertTrue(any(e['type']=='gain' and e['id']=='o0/aaa' and Fraction(*e['at'])>Fraction(1,4) for e in faded['events']))

    def test_shared_expression_validation_and_event_caps(self):
        for fades in (None,[{}],[dict(id='a',track='t',ordinal=0,ticks=-1,at=[0,1])]):
            with self.assertRaises(ValueError):tab.fade_expression_streams(fades,['t'],Fraction(4))
        fades=[dict(id=str(i),track='t',ordinal=i,ticks=960,at=[0,1]) for i in range(2100)]
        with self.assertRaisesRegex(ValueError,'200000'):tab.fade_expression_streams(fades,['t'],Fraction(4))

    @staticmethod
    def expression(plan):
        """TG's source callbacks in insertion order; expansion belongs to MIDI."""
        events = [(Fraction(0), 127)]
        for fade in plan['midi_fades']:
            start, ticks = Fraction(*fade['at']), fade['ticks']
            if ticks > 0:
                events.extend((start + Fraction(i * (ticks // 96), 960), 31 + i) for i in range(96))
            events.append((start + Fraction(ticks, 960), 127))
        return events

    def test_boolean_validation_positions_and_strict_it_guard(self):
        song, raw = TestNativeRepeats().fixture([{}])
        original = copy.deepcopy(song)
        plain = tab.playback_plan(song, raw)
        self.assertEqual(plain['midi_fades'], [])
        for invalid in (None, 0, 1, 'true', {}, []):
            with self.subTest(invalid=invalid), self.assertRaisesRegex(ValueError, 'fade_in must be boolean'):
                tab.apply_score_edit(song, dict(op='note_set', pattern='P0', beat='b',
                    note=dict(id='n', fade_in=invalid)))
        changed = tab.apply_score_edit(song, dict(op='note_set', pattern='P0', beat='b',
            note=dict(id='n', fade_in=True)))
        plan = tab.playback_plan(changed, raw)
        self.assertEqual([e for e in plan['events'] if e['type'] != 'gain'], plain['events'])
        self.assertTrue(any(e['type'] == 'gain' for e in plan['events']))
        self.assertEqual(plan['duration'], plain['duration'])
        self.assertEqual(plan['midi_fades'], [dict(id='o0/n', track='guitar', at=[0, 1], ticks=960, ordinal=0)])
        self.assertTrue(plan['positions'][0]['fade_in'])
        self.assertTrue(next(p for p in tab.authoring_view(changed, raw)['positions'] if p['kind'] == 'note')['fade_in'])
        self.assertTrue(any('IT fade_in:' in d for d in tab.project_score(changed, raw).diagnostics))
        cleared = tab.apply_score_edit(changed, dict(op='note_set', pattern='P0', beat='b',
            note=dict(id='n', fade_in=False)))
        self.assertEqual(tab.playback_plan(cleared, raw)['midi_fades'], [])
        self.assertFalse(tab.playback_plan(cleared, raw)['positions'][0]['fade_in'])
        tab.project_score(cleared, raw)
        self.assertEqual(song, original)

    def test_note_events_unchanged_and_gain_added_for_qualified_combinations(self):
        for mode in ('plain', 'dead', 'staccato', 'on_grace', 'before_grace', 'picking', 'harmonic'):
            song, raw = TestBeatStrokes().fixture()
            head = song['score']['patterns']['P0']['beats'][0]
            if mode == 'before_grace':
                head['at'] = [1, 1]
            for n in head['notes']:
                if mode in ('dead', 'staccato'):
                    n[mode] = True
                elif mode in ('on_grace', 'before_grace'):
                    n['grace'] = dict(fret=2, value=16, velocity=47, on_beat=mode == 'on_grace')
                elif mode == 'picking':
                    n['tremolo_picking'] = dict(value=16)
                elif mode == 'harmonic':
                    n['harmonic'] = dict(type='semi', data=0)
            before = tab.playback_plan(song, raw)
            for n in head['notes']:
                n['fade_in'] = True
            after = tab.playback_plan(song, raw)
            with self.subTest(mode=mode):
                self.assertEqual(before['events'], [e for e in after['events'] if e['type'] != 'gain'])
                self.assertTrue(any(e['type'] == 'gain' for e in after['events']))
                self.assertEqual(before['duration'], after['duration'])
                self.assertEqual(len(after['midi_fades']), 3)

    def test_plain_short_and_stroke_callback_vectors(self):
        song, raw = TestNativeRepeats().fixture([{}])
        head = song['score']['patterns']['P0']['beats'][0]
        head['notes'][0]['fade_in'] = True
        self.assertEqual(self.expression(tab.playback_plan(song, raw)),
            [(Fraction(0), 127)] + [(Fraction(i * 10, 960), 31 + i) for i in range(96)] + [(Fraction(1), 127)])
        head['written']['value'] = 64
        self.assertEqual(self.expression(tab.playback_plan(song, raw)),
            [(Fraction(0), 127)] + [(Fraction(0), 31 + i) for i in range(96)] + [(Fraction(1, 16), 127)])
        song, raw = TestBeatStrokes().fixture()
        for n in song['score']['patterns']['P0']['beats'][0]['notes']:
            n['fade_in'] = True
        plan = tab.playback_plan(song, raw)
        self.assertEqual([(f['id'], f['at'], f['ticks']) for f in plan['midi_fades']],
                         [('o0/s1', [1, 4], 720), ('o0/s3', [1, 8], 840), ('o0/s6', [0, 1], 960)])
        callbacks = self.expression(plan)
        self.assertEqual(len(callbacks), 292)
        self.assertEqual(callbacks[1:3], [(Fraction(1, 4), 31), (Fraction(247, 960), 32)])
        self.assertEqual(callbacks[98:100], [(Fraction(1, 8), 31), (Fraction(128, 960), 32)])

    def test_grace_uses_pre_grace_gate_and_anchor(self):
        for on_beat in (False, True):
            song, raw, _, head = TestNativeGrace().fixture(at=(1, 1), on_beat=on_beat)
            head['fade_in'] = True
            plan = tab.playback_plan(song, raw)
            fade = plan['midi_fades'][0]
            self.assertEqual((fade['at'], fade['ticks']), ([1, 1], 960))
            main = next(e for e in plan['events'] if e['type'] == 'note_on' and e.get('role') != 'grace')
            self.assertEqual(main['at'], [5, 4] if on_beat else [1, 1])
            grace = next(e for e in plan['events'] if e['type'] == 'note_on' and e.get('role') == 'grace')
            self.assertEqual(grace['at'], [1, 1] if on_beat else [3, 4])

    def test_tie_head_and_continuation_metadata_are_distinct(self):
        song, raw = TestNativeRepeats().fixture([{}])
        beats = song['score']['patterns']['P0']['beats']
        beats[0]['notes'][0]['fade_in'] = True
        beats.append(beat('continued', [1, 1], [dict(note('continued', 69, 1, 5), fade_in=True)]))
        song['score']['ties'] = [dict(**{'from': dict(occurrence='o0', note='n')},
                                    to=dict(occurrence='o0', note='continued'))]
        plan = tab.playback_plan(song, raw)
        self.assertEqual(plan['midi_fades'], [dict(id='o0/n', track='guitar', at=[0, 1], ticks=1920, ordinal=0)])
        self.assertTrue(all(p['fade_in'] for p in plan['positions']))
        beats[0]['notes'][0]['fade_in'] = False
        self.assertEqual(tab.playback_plan(song, raw)['midi_fades'], [])

    def test_repeat_fragments_swing_and_source_insertion_ordinals(self):
        song, raw = TestRepeatFragments().fixture()
        for b in song['score']['patterns']['P0']['beats']:
            b['notes'][0]['fade_in'] = True
        result = tab.repeat_projection(song, raw)
        self.assertEqual([f['id'] for f in result.plan['midi_fades']],
                         [f'play_{i // 2 + 1}/n{i % 4}' for i in range(8)])
        self.assertEqual([f['ordinal'] for f in result.plan['midi_fades']], list(range(8)))
        self.assertEqual([f['at'] for f in result.plan['midi_fades']], [[i, 1] for i in range(8)])
        song, raw = TestBeatStrokes().fixture()
        chord = song['score']['patterns']['P0']['beats'][0]
        chord['notes'].reverse()
        other = beat('voice1', [0, 1], [dict(note('aaa', 61, 2, 2), fade_in=True)], value=16, voice=1)
        song['score']['patterns']['P0']['beats'].insert(0, other)
        for n in chord['notes']:
            n['fade_in'] = True
        self.assertEqual([f['id'] for f in tab.playback_plan(song, raw)['midi_fades']],
                         ['o0/s6', 'o0/s3', 'o0/s1', 'o0/aaa'])
        song, raw, _ = TestNativeSwing().fixture('eighth')
        for b in song['score']['patterns']['A']['beats']:
            for n in b['notes']:
                n['fade_in'] = True
        fades = tab.playback_plan(song, raw)['midi_fades']
        self.assertEqual([(f['at'], f['ticks']) for f in fades[:2]], [([0, 1], 640), ([2, 3], 320)])

    def test_fractional_anchor_and_zero_legacy_ticks_gain_schedule(self):
        song, raw = TestNativeRepeats().fixture([{}])
        head = song['score']['patterns']['P0']['beats'][0]
        head['at'] = [1, 13]
        plain = tab.playback_plan(song, raw)
        head['notes'][0]['fade_in'] = True
        plan = tab.playback_plan(song, raw)
        self.assertEqual([e for e in plan['events'] if e['type'] != 'gain'], plain['events'])
        self.assertTrue(any(e['type'] == 'gain' for e in plan['events']))
        self.assertEqual(plan['midi_fades'][0]['at'], [1, 13])
        head['written'] = dict(value=64, tuplet=[1000, 1])
        plan = tab.playback_plan(song, raw)
        self.assertEqual(plan['midi_fades'][0]['ticks'], 0)
        self.assertEqual(self.expression(plan), [(Fraction(0), 127), (Fraction(1, 13), 127)])

    def test_source_copy_move_and_command_preserve_flag(self):
        from types import SimpleNamespace
        song, raw = TestNativeRepeats().fixture([{}])
        song['score']['patterns']['P0']['beats'][0]['notes'][0]['fade_in'] = True
        clip = tab.capture_score_clipboard(song, 'P0', ['b'], 'o0')
        pasted = tab.paste_score_clipboard(song, SimpleNamespace(patterns=raw), 0, 24, clip)
        self.assertTrue(all(b['notes'][0]['fade_in'] for b in pasted['score']['patterns']['P0']['beats']))
        moved = tab.move_note(song, SimpleNamespace(patterns=raw), 0, 'n', 12)
        self.assertEqual(tab.playback_plan(moved, raw)['midi_fades'][0]['at'], [1, 1])
        repeated, _ = tab.score_command(song, raw, dict(action='repeat', occurrence='o0',
            track='guitar', voice=0, beats=['b']))
        self.assertEqual(len(tab.playback_plan(repeated, raw)['midi_fades']), 2)
        restored = yaml.safe_load(yaml.safe_dump(repeated))
        self.assertEqual(tab.playback_plan(restored, raw)['midi_fades'],
                         tab.playback_plan(repeated, raw)['midi_fades'])


class TestChordDiagrams(unittest.TestCase):
    def fixture(self, second=False):
        song, raw = TestNativeRepeats().fixture([{}])
        beats = song['score']['patterns']['P0']['beats']
        beats[0]['chord'] = dict(name='C', first_fret=1, frets=[0, 1, 0, 2, 3, -1])
        if second:
            beats.append(beat('other', [0, 1], [note('other', 60, 2, 1)], voice=1))
        return song, raw

    def edit(self, song, **patch):
        value = copy.deepcopy(song['score']['patterns']['P0']['beats'][0])
        value.update(patch)
        return tab.apply_score_edit(song, dict(op='beat_set', pattern='P0', beat=value))

    def test_schema_bounds_auto_window_and_literal_muted(self):
        song, _ = self.fixture()
        valid = song['score']['patterns']['P0']['beats'][0]['chord']
        cases = [dict(name=1), dict(name='x' * 4097), dict(first_fret=True),
                 dict(first_fret=-1), dict(first_fret=30), dict(frets=[0]),
                 dict(frets=[False, 1, 0, 2, 3, -1]), dict(frets=[-2, 1, 0, 2, 3, -1]),
                 dict(frets=[30, 1, 0, 2, 3, -1]), dict(extra=True),
                 dict(first_fret=2), dict(frets=[6, 1, 0, 2, 3, -1]),
                 dict(first_fret=0, frets=[1, 6, 0, -1, -1, -1])]
        for patch in cases:
            with self.subTest(patch=patch), self.assertRaises(ValueError):
                self.edit(song, chord=dict(valid, **patch))
        for chord in (dict(name='', first_fret=0, frets=[-1] * 6),
                      dict(name='auto', first_fret=0, frets=[5, 9, 0, -1, -1, -1]),
                      dict(name='top', first_fret=29, frets=[29, 0, -1, -1, -1, -1]),
                      dict(name='x' * 4096, first_fret=1, frets=[0] * 6)):
            changed = self.edit(song, chord=chord)
            self.assertEqual(changed['score']['patterns']['P0']['beats'][0]['chord'], chord)
            self.assertEqual(yaml.safe_load(yaml.safe_dump(changed)), changed)
        for chord in ({}, [], True):
            with self.subTest(chord=chord), self.assertRaises(ValueError):
                self.edit(song, chord=chord)
        with self.assertRaises(ValueError):
            self.edit(song, notes=[], chord=dict(valid, first_fret=True))

    def test_sparse_cohort_set_clear_and_conflicts_are_atomic(self):
        song, raw = self.fixture(True)
        before = copy.deepcopy(song)
        view = tab.authoring_view(song, raw)
        self.assertEqual([p['chord'] for p in view['positions'] if p['kind'] == 'beat'],
                         [song['score']['patterns']['P0']['beats'][0]['chord']] * 2)
        self.assertEqual(song, before)
        changed = self.edit(song, chord=dict(name='label', first_fret=0, frets=[-1] * 6))
        beats = changed['score']['patterns']['P0']['beats']
        self.assertEqual(beats[0]['chord'], beats[1]['chord'])
        self.assertIsNot(beats[0]['chord'], beats[1]['chord'])
        patch = copy.deepcopy(beats[1])
        patch.pop('chord')
        inherited = tab.apply_score_edit(changed, dict(op='beat_set', pattern='P0', beat=patch))
        self.assertEqual(inherited['score']['patterns']['P0']['beats'][1]['chord'], beats[0]['chord'])
        cleared = self.edit(changed, chord=None)
        self.assertTrue(all('chord' not in b for b in cleared['score']['patterns']['P0']['beats']))
        bad = copy.deepcopy(changed)
        bad['score']['patterns']['P0']['beats'][1]['chord']['name'] = 'conflict'
        with self.assertRaisesRegex(ValueError, 'conflicting chord'):
            tab.validate_score(bad)
        self.assertEqual(song, before)

    def test_annotation_leaves_events_and_backing_unchanged(self):
        for decorated in (False, True):
            song, raw = self.fixture(True)
            if decorated:
                b = song['score']['patterns']['P0']['beats'][0]
                b['stroke'] = dict(direction='down', value=4)
                b['notes'][0].update(fade_in=True, staccato=True)
            plain = copy.deepcopy(song)
            plain['score']['patterns']['P0']['beats'][0].pop('chord')
            before = copy.deepcopy((song, raw))
            for rate in (44100, 48000):
                a, b = [tab.playback_plan(s, raw, sample_rate=rate) for s in (plain, song)]
                self.assertEqual(a['events'], b['events'])
                self.assertEqual(a['midi_fades'], b['midi_fades'])
                self.assertEqual(a['duration'], b['duration'])
            tab.authoring_view(song, raw)
            self.assertEqual((song, raw), before)
        song, raw = self.fixture(True)  # Isolate the notation guard from decorated fade timing.
        plain = copy.deepcopy(song)
        for beat in plain['score']['patterns']['P0']['beats']:
            beat.pop('chord', None)
        self.assertEqual(tab.project_score(song, raw).patterns, tab.project_score(plain, raw).patterns)

    def test_unique_voice_move_transfers_past_rests_and_refuses_conflict(self):
        from types import SimpleNamespace
        song, raw = self.fixture()
        beats = song['score']['patterns']['P0']['beats']
        beats.append(beat('rest', [0, 1], [], voice=1))
        beats[1]['chord'] = copy.deepcopy(beats[0]['chord'])
        before = copy.deepcopy(song)
        moved = tab.move_beat(song, SimpleNamespace(patterns=raw), 0, 'b', 12)
        self.assertEqual(moved['score']['patterns']['P0']['beats'][0]['chord'], beats[0]['chord'])
        self.assertNotIn('chord', moved['score']['patterns']['P0']['beats'][1])
        self.assertEqual(song, before)
        beats.append(beat('destination', [1, 1], [], voice=1))
        beats[-1]['chord'] = dict(name='different', first_fret=0, frets=[-1] * 6)
        with self.assertRaisesRegex(ValueError, 'conflicting chord'):
            tab.move_beat(song, SimpleNamespace(patterns=raw), 0, 'b', 12)
        # A same-onset complete beat edit uses the same transfer path.
        with self.assertRaisesRegex(ValueError, 'conflicting chord'):
            self.edit(song, at=[1, 1])

    def test_partial_voice_move_retains_sparse_source_and_inherits_destination(self):
        from types import SimpleNamespace
        song, raw = self.fixture(True)
        beats = song['score']['patterns']['P0']['beats']
        beats.append(beat('destination', [1, 1], [], voice=1))
        destination = dict(name='destination', first_fret=0, frets=[-1] * 6)
        beats[-1]['chord'] = destination
        moved = tab.move_beat(song, SimpleNamespace(patterns=raw), 0, 'b', 12)
        after = moved['score']['patterns']['P0']['beats']
        self.assertEqual(after[1]['chord'], beats[0]['chord'])
        self.assertEqual(after[0]['chord'], destination)
        # Without a destination annotation the moved voice has none.
        beats.pop()
        moved = self.edit(song, at=[1, 1])
        self.assertNotIn('chord', moved['score']['patterns']['P0']['beats'][0])
        self.assertEqual(moved['score']['patterns']['P0']['beats'][1]['chord'], beats[0]['chord'])

    def test_final_note_deletion_replacement_and_explicit_rest_attachment(self):
        song, _ = self.fixture(True)
        first = tab.apply_score_edit(song, dict(op='note_delete', pattern='P0', beat='b', note='n'))
        self.assertIn('chord', first['score']['patterns']['P0']['beats'][0])
        final = tab.apply_score_edit(first, dict(op='note_delete', pattern='P0', beat='other', note='other'))
        self.assertTrue(all('chord' not in b for b in final['score']['patterns']['P0']['beats']))
        chord = song['score']['patterns']['P0']['beats'][0]['chord']
        attached = self.edit(final, chord=chord)
        self.assertTrue(all(b['chord'] == chord for b in attached['score']['patterns']['P0']['beats']))
        self.assertTrue(all(not b['notes'] for b in attached['score']['patterns']['P0']['beats']))
        # Deleting the sparse carrier preserves the other sounding voice's chord.
        deleted = tab.apply_score_edit(song, dict(op='beat_delete', pattern='P0', beat='b'))
        self.assertEqual(deleted['score']['patterns']['P0']['beats'][0]['chord'], chord)
        song, _ = self.fixture()
        replaced = self.edit(song, notes=[])
        self.assertNotIn('chord', replaced['score']['patterns']['P0']['beats'][0])

    def test_whole_copy_and_note_clipboard_transpose_clear(self):
        from types import SimpleNamespace
        song, raw = self.fixture(True)
        clip = tab.capture_score_clipboard(song, 'P0', ['other'])
        self.assertEqual(clip['beats'][0]['chord'], song['score']['patterns']['P0']['beats'][0]['chord'])
        pasted = tab.paste_score_clipboard(song, SimpleNamespace(patterns=raw), 0, 24, clip)
        self.assertEqual(pasted['score']['patterns']['P0']['beats'][-1]['chord'], clip['beats'][0]['chord'])
        selection = dict(pattern=0, r0=0, r1=0, cols=[[0, ['note']], [1, ['note']]],
                         occurrence='o0', notes=['n', 'other'])
        note_clip = tab.capture_native_clipboard(song, raw, selection)
        self.assertTrue(all('chord' not in b for b in note_clip['score']['beats']))
        invalid_clip = copy.deepcopy(note_clip)
        invalid_clip['score']['beats'][0]['chord'] = clip['beats'][0]['chord']
        with self.assertRaisesRegex(ValueError, 'Pattern clipboard cannot carry chord'):
            tab.paste_native_clipboard(song, raw, dict(pattern=0, row=24, channel=0, clipboard=invalid_clip))
        transposed, _ = tab.transform_native_selections(song, raw,
            dict(action='transpose', semitones=1, selections=[selection]))
        self.assertEqual(transposed['patterns']['P0']['beats'][0]['chord'],
                         song['score']['patterns']['P0']['beats'][0]['chord'])
        cleared, _ = tab.transform_native_selections(song, raw,
            dict(action='clear', selections=[selection]))
        self.assertTrue(all('chord' not in b for b in cleared['patterns']['P0']['beats']))

    def test_cut_and_repeat_continuation_ownership(self):
        song, raw = self.fixture(True)
        cut, _ = tab.score_command(song, raw, dict(action='cut', occurrence='o0',
            track='guitar', voice=0, beats=['b', 'other'], notes=['n', 'other']))
        self.assertTrue(all('chord' not in b for b in cut['score']['patterns']['P0']['beats']))
        song, raw = self.fixture()
        # A three-quarter source copied at quarter 3 crosses the order boundary.
        source = song['score']['patterns']['P0']['beats'][0]
        source['written'] = dict(value=2, dots=1)
        repeated, _ = tab.score_command(song, raw, dict(action='repeat', occurrence='o0',
            track='guitar', voice=0, beats=['b']))
        copied = [b for p in repeated['score']['patterns'].values() for b in p['beats'] if b['id'] != 'b']
        self.assertGreater(len(copied), 1)
        self.assertEqual(sum('chord' in b for b in copied), 1)
        self.assertEqual(next(b for b in copied if 'chord' in b)['at'], [3, 1])

    def test_cut_rest_moves_only_uniquely_owned_annotations(self):
        for other_sounding in (False, True):
            song, raw = self.fixture()
            beats = song['score']['patterns']['P0']['beats']
            beats[0]['at'] = [1, 1]
            chord = copy.deepcopy(beats[0]['chord'])
            beats.append(beat('gap', [0, 1], []))
            beats.append(beat('other', [1, 1],
                [note('other', 60, 2, 1)] if other_sounding else [], voice=1))
            cut, _ = tab.score_command(song, raw, dict(action='cut', occurrence='o0',
                track='guitar', voice=0, beats=['gap']))
            after = {b['id']: b for b in cut['score']['patterns']['P0']['beats']}
            self.assertEqual(after['b']['at'], [0, 1])
            carrier, empty = ('other', 'b') if other_sounding else ('b', 'other')
            self.assertEqual(after[carrier]['chord'], chord)
            self.assertNotIn('chord', after[empty])

    def test_repeated_playback_does_not_change_events_or_source_annotation(self):
        song, raw = self.fixture()
        song['score']['measures'][0]['repeat_close'] = 1
        plain = copy.deepcopy(song)
        plain['score']['patterns']['P0']['beats'][0].pop('chord')
        before = copy.deepcopy(song)
        left, right = [tab.repeat_projection(s, raw) for s in (plain, song)]
        self.assertEqual(left.plan['events'], right.plan['events'])
        self.assertEqual(left.patterns, right.patterns)
        self.assertEqual([p['chord'] for p in right.plan['positions']],
                         [song['score']['patterns']['P0']['beats'][0]['chord']] * 2)
        self.assertEqual(song, before)

    def test_track_geometry_changes_validate_diagram(self):
        song, _ = self.fixture()
        track = song['score']['tracks']['guitar']
        for patch in (dict(tuning=track['tuning'][:-1], channels=track['channels'][:-1]), dict(max_fret=2)):
            changed = copy.deepcopy(song)
            changed['score']['tracks']['guitar'].update(patch)
            with self.subTest(patch=patch), self.assertRaisesRegex(ValueError, 'chord'):
                tab.validate_score(changed)


class TestChordNoteEntry(unittest.TestCase):
    def fixture(self, second=False):
        return TestChordDiagrams().fixture(second)

    def request(self, song, **extra):
        edit = dict(op='chord_notes', pattern='P0', beat='b',
                    chord=copy.deepcopy(song['score']['patterns']['P0']['beats'][0]['chord']))
        edit.update(extra)
        return edit

    def apply(self, song, **extra):
        edit = self.request(song, **extra)
        before = copy.deepcopy((song, edit))
        result = tab.apply_score_edit(song, edit)
        self.assertEqual((song, edit), before)
        return result

    def test_fresh_notes_preserve_beat_defaults_and_exact_played_strings(self):
        song, raw = self.fixture()
        song['samples'][2] = dict(file='old-override.wav')
        b = song['score']['patterns']['P0']['beats'][0]
        b.update(text='keep', stem='down', pick_stroke='up',
                 written=dict(value=8, dots=1, tuplet=[3, 2]))
        b['notes'][0].update(instrument=2, volume=17, velocity=47, ghost=True, fade_in=True,
                            spelling=dict(step='A', alter=0))
        original = copy.deepcopy(b)
        changed = self.apply(song)
        after = changed['score']['patterns']['P0']['beats'][0]
        self.assertEqual({k: v for k, v in after.items() if k != 'notes'},
                         {k: v for k, v in original.items() if k != 'notes'})
        self.assertEqual([(n['string'], n['fret'], n['pitch'], n['velocity']) for n in after['notes']],
                         [(1, 0, 64, 95), (2, 1, 60, 95), (3, 0, 55, 95),
                          (4, 2, 52, 95), (5, 3, 48, 95)])
        self.assertTrue(all(set(n) == {'id', 'string', 'fret', 'pitch', 'velocity'} for n in after['notes']))
        self.assertNotIn('n', {n['id'] for n in after['notes']})
        plan = tab.playback_plan(changed, raw)
        attacks = [e for e in plan['events'] if e['type'] == 'note_on']
        self.assertEqual([e['ch'] for e in attacks], list(range(5)))
        self.assertTrue(all(e['source_instrument'] == 1 and e['velocity'] == 95 for e in attacks))
        self.assertEqual(plan['midi_fades'], [])
        self.assertTrue(all(p['end'] == [1, 2] for p in plan['positions']))
        again = self.apply(changed)
        self.assertFalse({n['id'] for n in again['score']['patterns']['P0']['beats'][0]['notes']} &
                         {n['id'] for n in after['notes']})

    def test_crossvoice_same_string_only_and_other_onsets_unchanged(self):
        song, raw = self.fixture(True)
        beats = song['score']['patterns']['P0']['beats']
        beats[1]['notes'] = [note('same', 64, 1, 0), note('muted', 60, 2, 1)]
        beats.append(beat('later', [1, 1], [note('later', 64, 1, 0)], voice=1))
        diagram = dict(name='one string', first_fret=0, frets=[0, -1, -1, -1, -1, -1])
        changed = self.apply(song, chord=diagram)
        after = changed['score']['patterns']['P0']['beats']
        self.assertEqual(after[1]['notes'], [beats[1]['notes'][1]])
        self.assertEqual(after[2], beats[2])
        self.assertEqual(after[0]['chord'], after[1]['chord'])
        self.assertEqual(after[0]['chord'], diagram)
        self.assertEqual([e['pitch'] for e in tab.playback_plan(changed, raw)['events']
                          if e['type'] == 'note_on'], [64, 60, 64])

    def test_sparse_shared_fields_and_implicit_other_voice_fingering(self):
        song, _ = self.fixture(True)
        beats = song['score']['patterns']['P0']['beats']
        beats[1]['notes'] = [note('implicit', 64)]
        beats[1]['stroke'] = dict(direction='down', value=8)
        changed = self.apply(song)
        after = changed['score']['patterns']['P0']['beats']
        self.assertEqual(after[1]['notes'], [])
        self.assertTrue(all(b['stroke'] == beats[1]['stroke'] for b in after))
        beats[1]['notes'] = [note('unresolved', 0)]
        before = copy.deepcopy(song)
        with self.assertRaisesRegex(ValueError, 'unresolved.*no resolved string'):
            self.apply(song)
        self.assertEqual(song, before)

    def test_all_muted_branches_preserve_literal_diagram_and_source_noop(self):
        muted = dict(name='literal muted', first_fret=0, frets=[-1] * 6)
        for selected_sounds, other_sounds in ((True, False), (True, True), (False, True), (False, False)):
            song, _ = self.fixture(True)
            beats = song['score']['patterns']['P0']['beats']
            if not selected_sounds:
                beats[0]['notes'] = []
            if not other_sounds:
                beats[1]['notes'] = []
            with self.subTest(selected=selected_sounds, other=other_sounds):
                changed = self.apply(song, chord=muted)
                after = changed['score']['patterns']['P0']['beats']
                if not selected_sounds and not other_sounds:
                    self.assertEqual(changed, song)
                else:
                    self.assertEqual(after[0]['notes'], [])
                    self.assertEqual(after[1]['notes'], beats[1]['notes'])
                    self.assertTrue(all(b['chord'] == muted for b in after))

    def test_rest_voice_becomes_played_and_custom_tuning_capo_velocity(self):
        song, raw = self.fixture()
        song['score']['patterns']['P0']['beats'][0]['notes'] = []
        song['score']['tracks']['guitar'].update(tuning=[62, 57, 53, 48, 43, 38], capo=2)
        for velocity in (0, 47, 127):
            changed = self.apply(song, velocity=velocity)
            notes = changed['score']['patterns']['P0']['beats'][0]['notes']
            self.assertEqual([n['pitch'] for n in notes], [64, 60, 55, 52, 48])
            self.assertTrue(all(n['velocity'] == velocity for n in notes))
            self.assertEqual([e['velocity'] for e in tab.playback_plan(changed, raw)['events']
                              if e['type'] == 'note_on'], [velocity] * 5)

    def test_reused_pattern_ties_across_both_removed_voices_require_explicit_removal(self):
        song, raw = self.fixture()
        song['orders'] = ['P0', 'P0']
        score = song['score']
        score.update(order_ids=['o0', 'o1'], measures=[])
        diagram = dict(name='two', first_fret=1, frets=[0, 1, -1, -1, -1, -1])
        score['patterns']['P0']['beats'] = [
            beat('before', [0, 1], [note('before', 64, 1, 0)]),
            dict(beat('b', [1, 1], [note('n', 64, 1, 0)]), chord=diagram),
            beat('after', [2, 1], [note('after', 64, 1, 0)]),
            beat('peer', [1, 1], [note('peer', 60, 2, 1)], voice=1),
            beat('peer_after', [2, 1], [note('peer_after', 60, 2, 1)], voice=1),
            beat('bass0', [0, 1], [note('bass0', 40, 1, 0)], track='bass'),
            beat('bass1', [1, 1], [note('bass1', 40, 1, 0)], track='bass')]
        score['ties'] = [dict(**{'from': dict(occurrence=oid, note=a)}, to=dict(occurrence=oid, note=b))
                         for oid in score['order_ids'] for a, b in
                         [('before', 'n'), ('n', 'after'), ('peer', 'peer_after'), ('bass0', 'bass1')]]
        request = dict(op='chord_notes', pattern='P0', beat='b', chord=diagram)
        before = copy.deepcopy(song)
        with self.assertRaisesRegex(ValueError, 'remove_ties: true'):
            tab.apply_score_edit(song, request)
        self.assertEqual(song, before)
        changed = tab.apply_score_edit(song, dict(request, remove_ties=True))
        self.assertEqual(changed['score']['ties'], [t for t in score['ties'] if t['from']['note'] == 'bass0'])
        self.assertEqual(changed['orders'], song['orders'])
        attacks = [e['id'] for e in tab.playback_plan(changed, raw)['events'] if e['type'] == 'note_on']
        for oid in score['order_ids']:
            self.assertIn(f'{oid}/after', attacks)
            self.assertIn(f'{oid}/peer_after', attacks)
        self.assertEqual(song, before)

    def test_validation_is_atomic_and_no_defaults_from_invalid_requests(self):
        song, _ = self.fixture()
        before = copy.deepcopy(song)
        invalid = [dict(chord=None), dict(chord={}), dict(chord=dict(name='bad', first_fret=True, frets=[0] * 6)),
                   dict(velocity=None), dict(velocity=True), dict(velocity=-1), dict(velocity=128),
                   dict(remove_ties=1), dict(remove_ties=None), dict(beat='missing'),
                   dict(pattern='missing'), dict(instrument=2), dict(voice=1)]
        for patch in invalid:
            with self.subTest(patch=patch), self.assertRaises(ValueError):
                tab.apply_score_edit(song, self.request(song, **patch))
            self.assertEqual(song, before)
        changed = copy.deepcopy(song)
        changed['score']['tracks']['guitar']['capo'] = 24
        changed['score']['tracks']['guitar']['tuning'][0] = 119
        changed['score']['patterns']['P0']['beats'][0]['notes'] = []
        with self.assertRaisesRegex(ValueError, 'string 1 pitch'):
            self.apply(changed)


class TestNativeSwing(unittest.TestCase):
    def fixture(self, mode='eighth'):
        song, raw = plan_fixture()
        value = 16 if mode == 'sixteenth' else 8
        head = note('n', 69, 1, 5)
        song['score']['patterns']['A']['beats'] = [
            beat('first', [0, 1], [head], value),
            beat('second', [4, value], [note('n2', 71, 1, 7)], value)]
        song['score']['patterns']['B']['beats'] = []
        song['score']['ties'] = []
        song['score']['measures'] = [dict(id='m', meter=[4, 4], swing=mode,
            **{'from': dict(occurrence='oa', at=[0, 1])}, to=dict(occurrence='oa', at=[4, 1]))]
        return song, raw, head

    def ticks(self, plan):
        return [Fraction(*e['at']) * 960 for e in plan['events'] if e['type'] != 'pitch']

    def test_source_pairs_exact_positions_and_no_mutation(self):
        for mode, expected in [('eighth', [0, 640, 640, 960]), ('sixteenth', [0, 320, 320, 480])]:
            song, raw, _ = self.fixture(mode)
            before = copy.deepcopy((song, raw))
            plan = tab.playback_plan(song, raw)
            self.assertEqual(self.ticks(plan), expected)
            second = plan['positions'][1]
            self.assertEqual(second['at'], [1, 2] if mode == 'eighth' else [1, 4])
            self.assertEqual(Fraction(*second['sounding_start']) * 960, expected[2])
            self.assertEqual(second['attack_id'], 'oa/n2')
            self.assertEqual(second['swing'], mode)
            self.assertEqual(second['sounding_start_frame'], plan['events'][2]['frame'])
            view = tab.authoring_view(song, raw)
            self.assertEqual([p['end'] for p in view['ownership']],
                             [[1, 2], [1, 1]] if mode == 'eighth' else [[1, 4], [1, 2]])
            self.assertEqual((song, raw), before)
            self.assertEqual(tab.playback_plan(yaml.safe_load(yaml.safe_dump(song)), raw), plan)
            projected = tab.project_score(song, raw)
            self.assertEqual(sum(c.note is not None and c.note < 120 for p in projected.patterns for row in p.rows for c in row),2)

    def test_isolated_halves_rests_other_voice_and_duration_spelling(self):
        for case, expected in [
                ('first', [0, 640]), ('second', [640, 960]),
                ('rest8', [0, 640]), ('rest16', [0, 480]),
                ('next16', [0, 480, 480, 720]), ('other_voice', [0, 480, 640, 720]),
                ('dotted', [0, 720]), ('tuplet', [0, 320]), ('equal_ratio_tuplet', [0, 480])]:
            song, raw, _ = self.fixture()
            beats = song['score']['patterns']['A']['beats']
            if case in ('first', 'dotted', 'tuplet', 'equal_ratio_tuplet'):
                beats.pop()
            elif case == 'second':
                beats.pop(0)
            elif case.startswith('rest'):
                beats[1]['notes'] = []
                beats[1]['written']['value'] = int(case[4:])
            elif case == 'next16':
                beats[1]['written']['value'] = 16
            elif case == 'other_voice':
                beats[1].update(voice=1, notes=[note('n2', 62, 2, 3)])
                beats[1]['written']['value'] = 16
            if case == 'dotted':
                beats[0]['written']['dots'] = 1
            elif case in ('tuplet', 'equal_ratio_tuplet'):
                beats[0]['written']['tuplet'] = [3, 2] if case == 'tuplet' else [2, 2]
            with self.subTest(case=case):
                self.assertEqual(self.ticks(tab.playback_plan(song, raw)), expected)

    def test_fractional_floor_phase_and_subtick_neighbor_rule(self):
        delta = Fraction(1, 12480)
        for mode, value, second in [('eighth', 8, Fraction(1, 2)), ('sixteenth', 16, Fraction(1, 4))]:
            unit = 960 if mode == 'eighth' else 480
            for center in (Fraction(1), second):
                for offset in (-delta, Fraction(0), delta):
                    song, raw, head = self.fixture(mode)
                    at = center + offset
                    song['score']['patterns']['A']['beats'] = [
                        beat('first', [at.numerator, at.denominator], [head], value)]
                    tick = int(at * 960)
                    shift, length = ((0, unit * 2 // 3) if tick % unit == 0 else
                                     (unit // 6, unit // 3) if tick % (unit // 2) == 0 else (0, unit // 2))
                    self.assertEqual(self.ticks(tab.playback_plan(song, raw)),
                                     [at * 960 + shift, at * 960 + shift + length])
        song, raw, _ = self.fixture()
        beats = song['score']['patterns']['A']['beats']
        beats[1]['written']['value'] = 16
        beats[1]['at'] = [6241, 12480]  # .5 + 1/13 tick: still adjacent after flooring.
        self.assertEqual(self.ticks(tab.playback_plan(song, raw))[:2], [0, 480])
        beats[1]['at'] = [6254, 12480]  # .5 + 14/13 ticks: first note now extends through it.
        plan = tab.playback_plan(song, raw)
        self.assertFalse(tab.authoring_view(song, raw)['conflicts'])
        self.assertEqual([e['id'] for e in plan['events'] if e.get('hold')], ['oa/n'])
        self.assertEqual(self.ticks(plan), [0, Fraction(6254, 13), 640, Fraction(9374, 13)])
        beats[1]['notes'][0]['channel'] = 2
        self.assertEqual(next(e['at'] for e in tab.playback_plan(song, raw)['events']
                              if e['type'] == 'note_off' and e['id'] == 'oa/n'), [2, 3])

    def test_held_swing_keeps_whole_parent_guards(self):
        for kind in ('inherited', 'harmonic', 'later_harmonic', 'raw_volume', 'unused_raw', 'tempo', 'global_volume'):
            song, raw, head = self.fixture()
            beats = song['score']['patterns']['A']['beats']
            beats[1]['at'], beats[1]['written']['value'] = [6254, 12480], 16
            if kind == 'inherited':
                head['instrument'] = 0
            elif kind == 'harmonic':
                beats[1]['notes'][0].update(harmonic=dict(type='semi', data=0), velocity=95)
            elif kind == 'later_harmonic':
                beats.append(beat('late', [2, 1], [
                    dict(note('late', 69, 1, 5), harmonic=dict(type='semi', data=0), velocity=95)]))
            elif kind == 'unused_raw':
                raw.append(Pattern('Unused', [[parse_cell('... .. ... X40')] + [Cell() for _ in range(6)]]))
            else:
                raw[1].rows[24][0] = parse_cell({
                    'raw_volume': '... .. v32 ...', 'tempo': '... .. ... T53',
                    'global_volume': '... .. ... V40'}[kind])
            with self.subTest(kind=kind):
                if kind in ('tempo', 'global_volume'):
                    self.assertEqual([e['id'] for e in tab.playback_plan(song, raw)['events'] if e.get('hold')], ['oa/n'])
                elif kind in ('harmonic', 'later_harmonic'):
                    plan = tab.playback_plan(song, raw)
                    self.assertTrue(all('context' in e for e in plan['events'] if e['type'] == 'note_on'))
                    self.assertFalse(any(e.get('hold') for e in plan['events']))
                else:
                    with self.assertRaisesRegex(ValueError, 'unsupported swing overlap|held swing'):
                        tab.playback_plan(song, raw)

    def test_tie_and_ring_duration_keep_written_compensation(self):
        for half, expected in [(0, [0, 1120]), (1, [640, 1440])]:
            song, raw, _ = self.fixture()
            beats = song['score']['patterns']['A']['beats']
            beats[0]['at'], beats[1]['at'] = [half, 2], [half + 1, 2]
            beats[1]['notes'][0].update(pitch=69, fret=5)
            song['score']['ties'] = [{'from': dict(occurrence='oa', note='n'),
                                     'to': dict(occurrence='oa', note='n2')}]
            plan = tab.playback_plan(song, raw)
            self.assertEqual(self.ticks(plan), expected)
            self.assertTrue(all(p['attack_id'] == 'oa/n' for p in plan['positions']))
        song, raw, head = self.fixture()
        head['let_ring'] = True
        song['score']['patterns']['A']['beats'][1]['notes'] = [dict(note('n2', 62, 2, 3), let_ring=True)]
        plan = tab.playback_plan(song, raw)
        self.assertEqual(self.ticks(plan), [0, 640, 960, 1120])
        self.assertEqual(next(e['at'] for e in plan['events'] if e['id'] == 'oa/n' and e['type'] == 'note_off'), [7, 6])

    def test_effects_follow_swung_head_duration(self):
        for effect, end in [('staccato', 320), ('palm_mute', 120), ('dead', 60),
                             ('bend', 640), ('vibrato', 640), ('grace', 640), ('tremolo_picking', 639)]:
            song, raw, head = self.fixture()
            song['score']['patterns']['A']['beats'].pop()
            if effect == 'bend':
                head[effect] = dict(points=[dict(position=0, value=0), dict(position=12, value=4)])
            elif effect == 'grace':
                head[effect] = dict(fret=2, value=16, velocity=47, on_beat=True)
            elif effect == 'tremolo_picking':
                head.update(tremolo_picking=dict(value=16), velocity=95)
            else:
                head[effect] = True
            plan = tab.playback_plan(song, raw)
            self.assertEqual(max(self.ticks(plan)), end)
            if effect == 'grace':
                self.assertEqual(self.ticks(plan), [0, 240, 240, 640])
            elif effect == 'tremolo_picking':
                self.assertEqual(self.ticks(plan), [0, 240, 240, 480, 480, 639])
            elif effect in ('bend', 'vibrato'):
                self.assertEqual(Fraction(*[e for e in plan['events'] if e['type'] == 'pitch'][-1]['at']) * 960, 640)

    def test_source_measure_phase_and_neighbors_do_not_reset_at_bar(self):
        song, raw, _ = self.fixture()
        song['score']['patterns']['A']['beats'][1]['at'] = [3, 2]
        song['score']['measures'] = [
            dict(id='one', meter=[3, 8], swing='eighth',
                 **{'from': dict(occurrence='oa', at=[0, 1])}, to=dict(occurrence='oa', at=[3, 2])),
            dict(id='two', meter=[3, 8], swing='eighth',
                 **{'from': dict(occurrence='oa', at=[3, 2])}, to=dict(occurrence='oa', at=[3, 1]))]
        self.assertEqual(self.ticks(tab.playback_plan(song, raw)), [0, 640, 1600, 1920])
        # The previous measure's mismatching duration cannot block a new measure's isolated second half.
        song['score']['patterns']['A']['beats'][0]['at'] = [5, 4]
        song['score']['patterns']['A']['beats'][0]['written']['value'] = 16
        self.assertEqual(self.ticks(tab.playback_plan(song, raw))[-2:], [1600, 1920])

    def test_clock_uses_authored_tempo_commands_and_written_source_stays(self):
        song, raw, _ = self.fixture()
        raw[0].rows[7][0] = parse_cell('... .. ... T3C')
        before = copy.deepcopy(raw)
        plan = tab.playback_plan(song, raw)
        self.assertEqual([e['seconds'] for e in plan['events']], [[0, 1], [3, 8], [3, 8], [17, 24]])
        self.assertEqual(raw, before)
        song, raw, head = self.fixture()
        song['score']['patterns']['A']['beats'] = [beat('first', [7, 2], [head], 8)]
        song['score']['patterns']['B']['beats'] = [beat('tail', [0, 1], [note('tail', 69, 1, 5)], 8)]
        song['score']['ties'] = [{'from': dict(occurrence='oa', note='n'),
                                 'to': dict(occurrence='ob', note='tail')}]
        raw[1].rows[0][6] = parse_cell('... .. ... T3C')
        self.assertEqual(self.ticks(tab.playback_plan(song, raw)), [3520, 4320])

    def test_raw_local_extension_delay_and_inherited_state_refuse(self):
        for command in ('C-5 01 ... ...', '=== .. ... ...', '... 01 ... ...',
                        '... .. v32 ...', '... .. ... X40', '... .. ... M20'):
            song, raw, _ = self.fixture()
            raw[0].rows[7][0] = parse_cell(command)
            self.assertTrue(any('swing' in c['message'] for c in tab.authoring_view(song, raw)['conflicts']))
            with self.assertRaises(ValueError):
                tab.playback_plan(song, raw)
            raw[0].rows[7][0] = Cell()
            raw[0].rows[7][6] = parse_cell(command)
            tab.playback_plan(song, raw)
        song, raw, _ = self.fixture()
        song['score']['patterns']['A']['beats'][1]['notes'][0]['instrument'] = 0
        with self.assertRaisesRegex(ValueError, 'delayed swing requires an explicit source instrument'):
            tab.playback_plan(song, raw)
        song, raw, head = self.fixture()
        song['score']['patterns']['A']['beats'] = [beat('first', [1, 1], [head], 8)]
        head['instrument'] = 0
        raw[0].rows[0][0] = parse_cell('... 01 ... ...')
        self.assertTrue(tab.playback_plan(song, raw)['events'][0]['instrument_inherited'])

    def test_measure_coverage_and_arrangement_bounds_refuse_without_clipping(self):
        song, raw, _ = self.fixture()
        measure = song['score']['measures'][0]
        measure.update(meter=[1, 4], **{'from': dict(occurrence='oa', at=[1, 4])},
                       to=dict(occurrence='oa', at=[5, 4]))
        with self.assertRaisesRegex(ValueError, 'swing measure boundary'):
            tab.playback_plan(song, raw)
        song, raw, _ = self.fixture()
        song['orders'], song['score']['order_ids'] = ['A'], ['oa']
        beats = song['score']['patterns']['A']['beats']
        beats[0]['at'], beats[1]['at'] = [3, 1], [7, 2]
        beats[1]['notes'][0].update(pitch=69, fret=5)
        song['score']['ties'] = [{'from': dict(occurrence='oa', note='n'),
                                 'to': dict(occurrence='oa', note='n2')}]
        view = tab.authoring_view(song, raw)
        self.assertIn('swing sounding end', view['conflicts'][0]['message'])
        with self.assertRaisesRegex(ValueError, 'exceeds arrangement end'):
            tab.playback_plan(song, raw)

    def test_delayed_slide_preserves_written_curve_or_refuses_pre_attack_controls(self):
        song, raw, head = self.fixture()
        beats = song['score']['patterns']['A']['beats']
        beats[0]['at'], beats[1]['at'] = [1, 2], [1, 1]
        head['slide'] = True
        with self.assertRaisesRegex(ValueError, 'swing with slide controls before the main attack'):
            tab.playback_plan(song, raw)
        song, raw, head = self.fixture('sixteenth')
        beats = song['score']['patterns']['A']['beats']
        beats[0]['at'], beats[1]['at'] = [1, 4], [1, 2]
        head['slide'] = True
        plan = tab.playback_plan(song, raw)
        self.assertEqual(next(e['at'] for e in plan['events'] if e['type'] == 'pitch'), [3, 8])

    def test_measure_set_toggles_swing_without_changing_notes_or_backing(self):
        song, raw, _ = self.fixture('none')
        before = copy.deepcopy(song)
        measure = dict(song['score']['measures'][0], swing='eighth')
        changed = tab.apply_score_edit(song, dict(op='measure_set', measure=measure))
        self.assertEqual(changed['score']['patterns'], song['score']['patterns'])
        self.assertEqual(self.ticks(tab.playback_plan(changed, raw)), [0, 640, 640, 960])
        plain = tab.apply_score_edit(changed, dict(op='measure_set', measure=dict(measure, swing='none')))
        self.assertEqual(plain, before)
        self.assertEqual(self.ticks(tab.playback_plan(plain, raw)), [0, 480, 480, 960])
        self.assertEqual(song, before)
        for bad in (None, True, 'triplet', 'eighth '):
            with self.assertRaisesRegex(ValueError, 'measure swing'):
                tab.apply_score_edit(song, dict(op='measure_set', measure=dict(measure, swing=bad)))


class TestNativeGrace(unittest.TestCase):
    def fixture(self, at=(1, 1), value=16, on_beat=False):
        song, raw = plan_fixture()
        head = dict(note('n', 69, 1, 5), grace=dict(fret=2, value=value, velocity=47, on_beat=on_beat))
        source = beat('head', list(at), [head])
        song['score']['patterns']['A']['beats'] = [source]
        song['score']['patterns']['B']['beats'] = []
        song['score']['ties'] = []
        return song, raw, source, head

    def notes(self, plan):
        return [(e['type'], Fraction(*e['at']) * 960, e['pitch'], e['velocity'])
                for e in plan['events'] if e['type'] in ('note_on', 'note_off')]

    def test_installed_duration_origin_vectors_and_ownership(self):
        for value in (16, 32, 64):
            for on in (False, True):
                for at in (0, 1):
                    with self.subTest(value=value, on=on, at=at):
                        song, raw, _, head = self.fixture((at, 1), value, on)
                        head['velocity'] = 95
                        before = copy.deepcopy(song)
                        plan = tab.playback_plan(song, raw, 48000)
                        length, start = 3840 // value, at * 960
                        shifted = on or start < length
                        g = start if shifted else start - length
                        m = start + length if shifted else start
                        self.assertEqual(self.notes(plan), [
                            ('note_on', g, 66, 47), ('note_off', g + length, 66, 47),
                            ('note_on', m, 69, 95), ('note_off', start + 960, 69, 95)])
                        grace = [e for e in plan['events'] if e.get('role') == 'grace']
                        self.assertEqual(len(grace), 2)
                        self.assertTrue(all(e['id'] == 'oa/n/grace' and e['source_id'] == 'oa/n'
                                            and e['note'] == 'n' for e in grace))
                        position = plan['positions'][0]
                        self.assertEqual((position['id'], position['attack_id'], position['at']),
                                         ('oa/n', 'oa/n', [at, 1]))
                        self.assertEqual(Fraction(*position['sounding_start']) * 960, m)
                        self.assertEqual(position['sounding_start_frame'],
                                         next(e['frame'] for e in plan['events'] if e['id'] == 'oa/n'))
                        self.assertEqual(song, before)
                        self.assertEqual(tab.playback_plan(yaml.safe_load(yaml.safe_dump(song)), raw, 48000), plan)

    def test_near_origin_dead_gap_and_fractional_onset(self):
        song, raw, _, head = self.fixture((1, 8))
        plan = tab.playback_plan(song, raw)
        self.assertEqual([t for _, t, _, _ in self.notes(plan)], [120, 360, 360, 1080])
        head['grace']['value'] = 32
        self.assertEqual([t for _, t, _, _ in self.notes(tab.playback_plan(song, raw))], [0, 120, 120, 1080])
        for on in (False, True):
            song, raw, _, head = self.fixture(on_beat=on)
            head['grace']['dead'] = True
            self.assertEqual([t for _, t, _, _ in self.notes(tab.playback_plan(song, raw))],
                             [960, 1020, 1200, 1920] if on else [720, 780, 960, 1920])
            song, raw, source, _ = self.fixture((4, 13), on_beat=on)
            source['written'].update(value=8, tuplet=[13, 8])
            plan = tab.playback_plan(song, raw)
            origin = Fraction(4, 13) * 960
            self.assertEqual([t - origin for _, t, _, _ in self.notes(plan)],
                             [0, 240, 240, 295] if on else [-240, 0, 0, 295])

    def test_velocity_volume_transitions_and_pitch_resolution(self):
        song, raw, _, head = self.fixture()
        head['volume'] = 32
        baseline = tab.playback_plan(song, raw)
        self.assertIsNone(next(e['velocity'] for e in baseline['events'] if e['id'] == 'oa/n'))
        self.assertTrue(all(e['volume'] == 32 for e in baseline['events']))
        for transition in ('none', 'slide', 'bend', 'hammer'):
            head['grace']['transition'] = transition
            self.assertEqual(tab.playback_plan(song, raw), baseline)
        for velocity in (0, 1, 127):
            head['grace']['velocity'] = velocity
            plan = tab.playback_plan(song, raw)
            self.assertEqual([e['velocity'] for e in plan['events'] if e.get('role') == 'grace'],
                             [velocity, velocity])
        head.update(velocity=95, ghost=True)
        self.assertEqual(next(e['velocity'] for e in tab.playback_plan(song, raw)['events']
                              if e['id'] == 'oa/n' and e['type'] == 'note_on'), 79)
        song['score']['tracks']['guitar']['capo'] = 2
        head['pitch'] = 71
        self.assertEqual(tab.playback_plan(song, raw)['events'][0]['pitch'], 68)
        projected = tab.project_score(song, raw)
        self.assertEqual(sum(c.note is not None and c.note < 120 for p in projected.patterns for row in p.rows for c in row), 2)

    def test_ties_ignore_continuation_grace_and_keep_logical_heads(self):
        song, raw, _, head = self.fixture(on_beat=True)
        head['velocity'] = 95
        continuation = dict(note('tail', 69, 1, 5), velocity=31, grace=dict(head['grace']))
        song['score']['patterns']['A']['beats'].append(beat('tail', [2, 1], [continuation]))
        song['score']['ties'] = [{'from': dict(occurrence='oa', note='n'),
                                 'to': dict(occurrence='oa', note='tail')}]
        plan = tab.playback_plan(song, raw)
        self.assertEqual([t for _, t, _, _ in self.notes(plan)], [960, 1200, 1200, 2880])
        self.assertTrue(all(p['attack_id'] == 'oa/n' for p in plan['positions']))
        del head['grace']
        self.assertEqual(self.notes(tab.playback_plan(song, raw)),
                         [('note_on', 960, 69, 95), ('note_off', 2880, 69, 95)])

    def test_tempo_boundary_uses_head_tempo_for_dead_grace(self):
        song, raw, source, head = self.fixture((0, 1))
        head['grace']['dead'] = True
        song['module']['tempo'] = 60
        song['score']['patterns']['A']['beats'] = []
        song['score']['patterns']['B']['beats'] = [source]
        raw[1].rows[0][6] = parse_cell('... .. ... TF0')
        plan = tab.playback_plan(song, raw, 48000)
        self.assertEqual([t for _, t, _, _ in self.notes(plan)], [3600, 3720, 3840, 4800])
        self.assertEqual([e['seconds'] for e in plan['events']], [[15, 4], [31, 8], [4, 1], [17, 4]])
        self.assertTrue(all(e['occurrence'] == 'ob' for e in plan['events']))
        self.assertLess(Fraction(*plan['events'][0]['at']), Fraction(*plan['occurrences'][1]['at']))

    def test_chord_independent_durations_and_source_order(self):
        song, raw, source, _ = self.fixture(on_beat=True)
        source['notes'].append(dict(note('n2', 62, 2, 3),
                                    grace=dict(fret=1, value=64, velocity=47, on_beat=True)))
        plan = tab.playback_plan(song, raw)
        self.assertEqual([(e['id'], e['at']) for e in plan['events'] if e['type'] == 'note_on'],
                         [('oa/n/grace', [1, 1]), ('oa/n2/grace', [1, 1]),
                          ('oa/n2', [17, 16]), ('oa/n', [5, 4])])

    def test_effects_follow_main_delay_and_keep_grace_ordinary(self):
        for effect in ('bend', 'tremolo_bar', 'vibrato', 'harmonic', 'trill', 'tremolo_picking', 'let_ring'):
            song, raw, _, head = self.fixture(on_beat=True)
            head['velocity'] = 95
            if effect in ('bend', 'tremolo_bar'):
                head[effect] = dict(points=[dict(position=0, value=0), dict(position=12, value=4)])
            elif effect == 'harmonic':
                head[effect] = dict(type='semi')
            elif effect in ('trill', 'tremolo_picking'):
                head[effect] = dict(value=16, **({'fret': 7} if effect == 'trill' else {}))
            else:
                head[effect] = True
            if effect == 'let_ring':
                song['score']['patterns']['A']['beats'].append(beat('other', [2, 1], [note('other', 62, 2, 3)]))
            plan = tab.playback_plan(song, raw)
            grace = [e for e in plan['events'] if e.get('role') == 'grace']
            self.assertTrue(all(e['pitch'] == 66 and e['velocity'] == 47 and 'layers' not in e for e in grace))
            if effect in ('trill', 'tremolo_picking'):
                pulses = [e for e in plan['events'] if 'pulse' in e]
                self.assertEqual(len(pulses), 6)
                self.assertEqual((pulses[0]['at'], pulses[-1]['at']), ([5, 4], [1919, 960]))
            elif effect in ('bend', 'tremolo_bar', 'vibrato'):
                pitches = [e for e in plan['events'] if e['type'] == 'pitch']
                self.assertGreaterEqual(Fraction(*pitches[0]['at']), Fraction(5, 4))
                self.assertEqual(pitches[-1]['at'], [2, 1])
            else:
                self.assertEqual(next(e['at'] for e in plan['events'] if e['id'] == 'oa/n' and e['type'] == 'note_off'),
                                 [3 if effect == 'let_ring' else 2, 1])

    def test_exhausted_main_bounds_and_inherited_instrument_refusals(self):
        for value in (16, 32):
            song, raw, source, head = self.fixture((0, 1), on_beat=True)
            source['written']['value'] = value
            for repeat in (False, True):
                if repeat:
                    head.update(tremolo_picking=dict(value=16), velocity=95)
                with self.assertRaisesRegex(ValueError, 'grace delay exhausts'):
                    tab.playback_plan(song, raw)
        for gate in ('palm_mute', 'dead'):
            song, raw, _, head = self.fixture(on_beat=True)
            head[gate] = True
            with self.assertRaisesRegex(ValueError, 'grace delay exhausts'):
                tab.playback_plan(song, raw)
        song, raw, _, head = self.fixture()
        head['instrument'] = 0
        raw[0].rows[0][0] = parse_cell('... 01 ... ...')
        with self.assertRaisesRegex(ValueError, 'grace requires an explicit source instrument'):
            tab.playback_plan(song, raw)
        song, raw, source, head = self.fixture((2, 1), on_beat=True)
        song['orders'], song['score']['order_ids'] = ['A'], ['oa']
        head['let_ring'] = True
        song['score']['patterns']['A']['beats'].append(beat('last', [3, 1], [
            dict(note('tie', 69, 1, 5), let_ring=True), note('other', 62, 2, 3)]))
        song['score']['ties'] = [{'from': dict(occurrence='oa', note='n'),
                                 'to': dict(occurrence='oa', note='tie')}]
        with self.assertRaisesRegex(ValueError, 'grace/main duration exceeds arrangement bounds'):
            tab.playback_plan(song, raw)

    def test_short_remaining_repetition_keeps_grace_and_written_position(self):
        song, raw, source, head = self.fixture((0, 1), on_beat=True)
        source['written']['tuplet'] = [192, 49]  # 245 ticks; five remain after grace.
        head.update(tremolo_picking=dict(value=16), velocity=95)
        plan = tab.playback_plan(song, raw)
        self.assertEqual(len(plan['events']), 2)
        self.assertTrue(all(e.get('role') == 'grace' for e in plan['events']))
        self.assertEqual((plan['positions'][0]['attack_id'], plan['positions'][0]['sounding_start']),
                         ('oa/n', [1, 4]))

    def test_before_grace_overlap_uses_context_but_dead_gap_and_other_channel_do_not(self):
        song, raw, _, head = self.fixture()
        previous = beat('before', [0, 1], [note('before', 67, 1, 3)])
        song['score']['patterns']['A']['beats'].insert(0, previous)
        plan = tab.playback_plan(song, raw)
        self.assertTrue(all('context' in e for e in plan['events'] if e['type'] == 'note_on'))
        self.assertEqual(next(e['at'] for e in plan['events'] if e['id'] == 'oa/before' and e['type'] == 'note_off'), [1, 1])
        previous['notes'][0]['channel'] = 2
        self.assertFalse(any('context' in e for e in tab.playback_plan(song, raw)['events']))
        previous['notes'][0].pop('channel')
        previous['at'], previous['written']['value'] = [7, 8], 32
        head['grace']['dead'] = True  # Grace .75..8125; predecessor .875..1.
        tab.playback_plan(song, raw)

    def test_backing_prefix_and_delayed_attack_local_controls_refuse_at_original_time(self):
        for on in (False, True):
            for command in ('C-5 01 ... ...', '=== .. ... ...', '... 01 ... ...',
                            '... .. v32 ...', '... .. ... X40', '... .. ... D01', '... .. ... M20'):
                song, raw, _, _ = self.fixture(on_beat=on)
                row = 13 if on else 10
                raw[0].rows[row][0] = parse_cell(command)
                view = tab.authoring_view(song, raw)
                self.assertTrue(any('grace' in c['message'] for c in view['conflicts']))
                with self.assertRaises(ValueError):
                    tab.playback_plan(song, raw)
                raw[0].rows[row][0] = Cell()
                raw[0].rows[row][6] = parse_cell(command)
                tab.playback_plan(song, raw)
            for command in ('... .. ... T53', '... .. ... V40'):
                song, raw, _, _ = self.fixture(on_beat=on)
                raw[0].rows[13 if on else 10][0] = parse_cell(command)
                tab.playback_plan(song, raw)
        song, raw, _, _ = self.fixture(on_beat=True)
        raw[0].rows[15][0] = parse_cell('... .. v32 ...')  # Exactly the delayed attack.
        with self.assertRaisesRegex(ValueError, 'grace delayed attack'):
            tab.playback_plan(song, raw)

    def test_held_parent_upgrades_for_grace_but_other_channels_keep_hold(self):
        song, raw, _, head = self.fixture((3, 1))
        song['score']['patterns']['A']['beats'][:0] = [
            beat('ring', [0, 1], [dict(note('ring', 69, 1, 5), let_ring=True)]),
            beat('next', [1, 1], [note('next', 71, 1, 7)])]
        self.assertTrue(all('context' in e for e in tab.playback_plan(song, raw)['events'] if e['type'] == 'note_on'))
        head['channel'] = 2
        self.assertTrue(any(e.get('hold') for e in tab.playback_plan(song, raw)['events']))

    def test_schema_edit_clear_and_slide_control_boundary(self):
        song, raw, _, head = self.fixture(on_beat=True)
        before = copy.deepcopy(song)
        cleared = tab.apply_score_edit(song, dict(op='note_set', pattern='A', beat='head',
                                                  note=dict(id='n', grace=None)))
        self.assertNotIn('grace', cleared['score']['patterns']['A']['beats'][0]['notes'][0])
        self.assertEqual(song, before)
        for field, value in [('fret', True), ('fret', 30), ('value', 8), ('value', True),
                             ('velocity', None), ('velocity', 128), ('on_beat', 1),
                             ('dead', None), ('transition', 'legato'), ('unknown', 1)]:
            bad = copy.deepcopy(song)
            bad['score']['patterns']['A']['beats'][0]['notes'][0]['grace'][field] = value
            with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                tab.validate_score(bad)
        for grace in ({}, 'bad', dict(fret=2, value=16)):
            with self.assertRaises(ValueError):
                tab.apply_score_edit(song, dict(op='note_set', pattern='A', beat='head',
                                                note=dict(id='n', pitch=70, grace=grace)))
        invalid = copy.deepcopy(song)
        invalid['score']['tracks']['guitar']['tuning'][0] = 119
        invalid['score']['patterns']['A']['beats'][0]['notes'][0].update(pitch=119, fret=0)
        with self.assertRaisesRegex(ValueError, 'grace exceeds native pitch'):
            tab.validate_score(invalid)
        head['slide'] = True
        song['score']['patterns']['A']['beats'].append(beat('target', [2, 1], [note('target', 71, 1, 7)]))
        with self.assertRaisesRegex(ValueError, 'slide controls before the main attack'):
            tab.playback_plan(song, raw)
        head['grace']['value'] = 64
        pitches = [e for e in tab.playback_plan(song, raw)['events'] if e['type'] == 'pitch']
        self.assertEqual(pitches[0]['at'], [9, 8])  # Written-origin +120 ticks, not delayed-origin +120.


class TestNativeLetRing(unittest.TestCase):
    def fixture(self):
        song, raw = plan_fixture()
        head = dict(note('n', 69, 1, 5), let_ring=True)
        song['score']['patterns']['A']['beats'] = [
            beat('head', [0, 1], [head]),
            beat('other', [1, 1], [note('other', 62, 2, 3)]),
            beat('rest', [2, 1], [])]
        song['score']['patterns']['B']['beats'] = []
        song['score']['ties'] = []
        return song, raw, head

    def release(self, song, raw):
        return next(e for e in tab.playback_plan(song, raw)['events']
                    if e['type'] == 'note_off' and e['id'] == 'oa/n')

    def test_extension_without_velocity_preserves_source_and_written_ownership(self):
        song, raw, _ = self.fixture()
        before = copy.deepcopy(song)
        plan = tab.playback_plan(song, raw)
        self.assertEqual(self.release(song, raw)['at'], [2, 1])
        head = plan['positions'][0]
        self.assertEqual((head['id'], head['attack_id'], head['end'], head['sounding_end']),
                         ('oa/n', 'oa/n', [1, 1], [2, 1]))
        self.assertIsNone(next(e for e in plan['events'] if e['id'] == 'oa/n')['velocity'])
        self.assertNotIn('gate_effect', head)
        view = tab.authoring_view(song, raw)
        owner = next(o for o in view['ownership'] if o['id'] == 'oa/n')
        self.assertEqual((owner['at'], owner['end']), ([0, 1], [1, 1]))
        self.assertFalse(view['conflicts'])
        self.assertEqual(song, before)
        self.assertEqual(tab.playback_plan(yaml.safe_load(yaml.safe_dump(song)), raw), plan)
        projected = tab.project_score(song, raw)
        self.assertEqual(projected.patterns[0].rows[24][0].note, NOTE_OFF)
        self.assertEqual(song, before)

    def test_rest_absence_other_voice_and_other_string_order(self):
        for case, end in [('alone', 1), ('rest', 1), ('gap', 2), ('other-voice', 1),
                          ('chain', 3)]:
            with self.subTest(case=case):
                song, raw, _ = self.fixture()
                beats = song['score']['patterns']['A']['beats']
                if case == 'alone':
                    beats[1:] = []
                elif case == 'rest':
                    beats[1]['notes'] = []
                    beats[2] = beat('late', [2, 1], [dict(note('late', 62, 2, 3), let_ring=True)])
                elif case == 'gap':
                    beats[1]['at'] = [3, 1]
                    beats[1]['notes'][0]['let_ring'] = True
                    beats.pop()
                elif case == 'other-voice':
                    beats[1]['voice'] = 1
                else:
                    beats[1]['notes'][0]['let_ring'] = True
                    beats[2] = beat('last', [2, 1], [note('last', 64, 2, 5)])
                    # That unmarked same-string replacement overlaps "other";
                    # give its new attack an independent parent for this scan test.
                    beats[2]['notes'][0]['channel'] = 2
                self.assertEqual(self.release(song, raw)['at'], [end, 1])

    def test_ties_enable_or_end_ring_and_head_gates_apply_after_scan(self):
        for head_ring, continuation_ring, gate, end in [
                (True, True, None, [3, 1]), (True, False, None, [2, 1]),
                (False, True, None, [3, 1]), (False, True, 'staccato', [3, 2]),
                (False, True, 'palm_mute', [1, 8]), (False, True, 'dead', [1, 16])]:
            with self.subTest(head_ring=head_ring, continuation_ring=continuation_ring, gate=gate):
                song, raw, head = self.fixture()
                head['let_ring'] = head_ring
                if gate:
                    head[gate] = True
                beats = song['score']['patterns']['A']['beats']
                beats[1] = beat('tie', [1, 1], [dict(note('tie', 69, 1, 5),
                                                   let_ring=continuation_ring)])
                beats[2] = beat('other', [2, 1], [dict(note('other', 62, 2, 3), let_ring=True)])
                song['score']['ties'] = [{'from': dict(occurrence='oa', note='n'),
                                         'to': dict(occurrence='oa', note='tie')}]
                self.assertEqual(self.release(song, raw)['at'], end)
                positions = tab.playback_plan(song, raw)['positions'][:2]
                self.assertTrue(all(p['attack_id'] == 'oa/n' and p['sounding_end'] == end for p in positions))

    def test_fractional_ticks_keep_exact_head_onset_and_tie_carry(self):
        for enters, times in ((7, 4), (13, 8)):
            for kind in ('other', 'ties', 'unmarked', 'gate'):
                with self.subTest(enters=enters, kind=kind):
                    song, raw, head = self.fixture()
                    step = Fraction(times, 2 * enters)
                    beats = [beat('head', [step.numerator, step.denominator], [head], 8, [enters, times])]
                    head['let_ring'] = kind != 'gate'
                    if kind == 'gate':
                        head['staccato'] = True
                    for i in (2, 3):
                        at = step * i
                        item = dict(note(f'n{i}', 62 if kind == 'other' else 69,
                                         2 if kind == 'other' else 1, 3 if kind == 'other' else 5),
                                    let_ring=not (kind == 'unmarked' and i == 3))
                        beats.append(beat(f'b{i}', [at.numerator, at.denominator], [item], 8, [enters, times]))
                        if kind != 'other':
                            song['score']['ties'].append({
                                'from': dict(occurrence='oa', note='n' if i == 2 else 'n2'),
                                'to': dict(occurrence='oa', note=f'n{i}')})
                    song['score']['patterns']['A']['beats'] = beats
                    expected = (822 if enters == 7 else 886 if kind in ('ties', 'gate') else 885)
                    if kind == 'gate':
                        expected //= 2
                    release = Fraction(*self.release(song, raw)['at'])
                    self.assertEqual(release, step + Fraction(expected, 960))
                    attack = next(e for e in tab.playback_plan(song, raw)['events'] if e['type'] == 'note_on')
                    self.assertEqual(Fraction(*attack['at']), step)

    def test_measure_boundary_tempo_and_reused_occurrences_are_linear(self):
        song, raw, head = self.fixture()
        song['score']['patterns']['A']['beats'] = [beat('head', [0, 1], [head], 1)]
        song['score']['patterns']['B']['beats'] = [
            beat('other', [0, 1], [dict(note('other', 62, 2, 3), let_ring=True)])]
        raw[1].rows[0][6] = parse_cell('... .. ... T3C')
        release = self.release(song, raw)
        self.assertEqual((release['at'], release['seconds']), ([5, 1], [3, 1]))
        song['orders'] = ['A', 'B', 'A', 'B']
        song['score']['order_ids'] = ['oa', 'ob', 'oc', 'od']
        plan = tab.playback_plan(song, raw)
        self.assertEqual([e['at'] for e in plan['events'] if e['type'] == 'note_off' and e['note'] == 'n'],
                         [[5, 1], [13, 1]])

    def test_tied_chord_double_duration_beyond_arrangement_is_visible_but_refused(self):
        song, raw, head = self.fixture()
        song['orders'], song['score']['order_ids'] = ['A'], ['oa']
        song['score']['patterns']['A']['beats'] = [
            beat('head', [2, 1], [head]),
            beat('last', [3, 1], [dict(note('tie', 69, 1, 5), let_ring=True), note('other', 62, 2, 3)])]
        song['score']['ties'] = [{'from': dict(occurrence='oa', note='n'),
                                 'to': dict(occurrence='oa', note='tie')}]
        view = tab.authoring_view(song, raw)
        position = next(p for p in view['positions'] if p['kind'] == 'note' and p['id'] == 'oa/n')
        self.assertEqual(position['sounding_end'], [5, 1])
        self.assertIn('exceeds arrangement end', view['conflicts'][0]['message'])
        with self.assertRaisesRegex(ValueError, 'let_ring sounding end 5 exceeds arrangement end 4'):
            tab.playback_plan(song, raw)

    def test_pitch_harmonic_and_repetition_consume_extended_duration(self):
        for technique in ('bend', 'tremolo_bar', 'vibrato', 'harmonic', 'trill', 'tremolo_picking'):
            song, raw, head = self.fixture()
            if technique in ('bend', 'tremolo_bar'):
                head[technique] = dict(points=[dict(position=0, value=0), dict(position=12, value=4)])
            elif technique == 'vibrato':
                head[technique] = True
            elif technique == 'harmonic':
                head.update(harmonic=dict(type='semi'), velocity=95)
            else:
                head[technique] = dict(value=16, **({'fret': 7} if technique == 'trill' else {}))
                head['velocity'] = 95
            plan = tab.playback_plan(song, raw)
            if technique in ('trill', 'tremolo_picking'):
                pulses = [e for e in plan['events'] if e.get('source_id') == 'oa/n']
                self.assertEqual(len(pulses), 16)
                self.assertEqual(pulses[-1]['at'], [1919, 960])
            else:
                self.assertEqual(self.release(song, raw)['at'], [2, 1])
                if technique != 'harmonic':
                    pitches = [e for e in plan['events'] if e['type'] == 'pitch']
                    self.assertEqual((pitches[-1]['at'], pitches[-1]['bend_value']), ([2, 1], 64))

    def test_same_parent_hold_admission_and_chord_order_preserve_release(self):
        for repetition in (False, True):
            song, raw, head = self.fixture()
            song['score']['patterns']['A']['beats'][1]['notes'] = [note('next', 71, 1, 7)]
            if repetition:
                head.update(trill=dict(fret=7, value=16), velocity=95)
            view = tab.authoring_view(song, raw)
            position = next(p for p in view['positions'] if p['kind'] == 'note' and p['id'] == 'oa/n')
            self.assertEqual(position['sounding_end'], [2, 1])
            if repetition:
                self.assertFalse(view['conflicts'])
                self.assertTrue(all('context' in e for e in tab.playback_plan(song, raw)['events'] if e['type'] == 'note_on'))
            else:
                self.assertFalse(view['conflicts'])
                plan = tab.playback_plan(song, raw)
                self.assertEqual([e['id'] for e in plan['events'] if e.get('hold')], ['oa/n'])
                self.assertEqual(self.release(song, raw)['at'], [2, 1])
        for reverse, end in ((False, [1, 1]), (True, [2, 1])):
            song, raw, _ = self.fixture()
            chord = [dict(note('same', 69, 1, 5), let_ring=True), note('other', 62, 2, 3)]
            song['score']['patterns']['A']['beats'][1]['notes'] = chord[::-1] if reverse else chord
            view = tab.authoring_view(song, raw)
            p = next(p for p in view['positions'] if p['kind'] == 'note' and p['id'] == 'oa/n')
            self.assertEqual(p['sounding_end'], end)
            self.assertFalse(view['conflicts'])
            self.assertEqual(any(e.get('hold') for e in tab.playback_plan(song, raw)['events']), reverse)

    def test_held_overlap_refuses_inheritance_layers_and_parent_local_controls(self):
        for kind in ('inherited', 'harmonic', 'later_harmonic'):
            song, raw, head = self.fixture()
            later = note('next', 71, 1, 7)
            song['score']['patterns']['A']['beats'][1]['notes'] = [later]
            if kind == 'inherited':
                head['instrument'] = 0
            else:
                target = later if kind == 'later_harmonic' else head
                target.update(harmonic=dict(type='semi', data=0), velocity=95)
            if kind == 'inherited':
                with self.assertRaisesRegex(ValueError, 'unsupported let_ring overlap'):
                    tab.playback_plan(song, raw)
            else:
                self.assertTrue(all('context' in e for e in tab.playback_plan(song, raw)['events'] if e['type'] == 'note_on'))
        for command in ('... .. v32 ...', '... .. ... X40', '... .. ... D01', '... .. ... M20'):
            song, raw, _ = self.fixture()
            song['score']['patterns']['A']['beats'][1]['notes'] = [note('next', 71, 1, 7)]
            raw[0].rows[18][0] = parse_cell(command)
            view = tab.authoring_view(song, raw)
            self.assertIn('held let_ring overlap cannot share raw', view['conflicts'][0]['message'])
            with self.assertRaisesRegex(ValueError, 'held let_ring overlap cannot share raw'):
                tab.playback_plan(song, raw)
            raw[0].rows[18][0] = Cell()
            raw[0].rows[24][0] = parse_cell(command)
            self.assertIn('entire backing', tab.authoring_view(song, raw)['conflicts'][0]['message'])
        for command in ('... .. ... T53', '... .. ... V40'):
            song, raw, _ = self.fixture()
            song['score']['patterns']['A']['beats'][1]['notes'] = [note('next', 71, 1, 7)]
            raw[0].rows[18][0] = parse_cell(command)
            self.assertTrue(any(e.get('hold') for e in tab.playback_plan(song, raw)['events']))

    def test_raw_extended_conflicts_are_shared_and_end_boundary_is_allowed(self):
        for cell in ('C-5 01 ... ...', '=== .. ... ...', '... 01 ... ...'):
            song, raw, _ = self.fixture()
            raw[0].rows[18][0] = parse_cell(cell)
            view = tab.authoring_view(song, raw)
            conflict = view['conflicts'][0]
            self.assertEqual((conflict['id'], conflict['row'], conflict['at']), ('oa/n', [18, 1], [3, 2]))
            with self.assertRaisesRegex(ValueError, 'raw .* conflicts with extended let_ring sustain'):
                tab.playback_plan(song, raw)
            raw[0].rows[18][0] = Cell()
            raw[0].rows[24][0] = parse_cell(cell)
            self.assertFalse(tab.authoring_view(song, raw)['conflicts'])
            tab.playback_plan(song, raw)
        song, raw, head = self.fixture()
        song['score']['patterns']['A']['beats'] = [beat('head', [0, 1], [head], 1)]
        song['score']['patterns']['B']['beats'] = [beat('other', [0, 1], [note('other', 62, 2, 3)])]
        raw[1].rows[6][0] = parse_cell('... 01 ... ...')
        conflict = tab.authoring_view(song, raw)['conflicts'][0]
        self.assertEqual((conflict['occurrence'], conflict['pattern'], conflict['row']), ('ob', 'B', [6, 1]))

    def test_repetition_tail_does_not_create_false_overlap(self):
        song, raw, head = self.fixture()
        head.update(trill=dict(fret=7, value=16), velocity=95)
        song['score']['patterns']['A']['beats'].append(
            beat('tail', [1919, 960], [note('tail', 71, 1, 7)], 64, voice=1))
        plan = tab.playback_plan(song, raw)
        self.assertEqual(next(e['at'] for e in plan['events'] if e['id'] == 'oa/tail'), [1919, 960])

    def test_schema_setter_exclusions_and_unresolved_string_refusal(self):
        song, raw, head = self.fixture()
        for bad in (None, 1, 'true'):
            head['let_ring'] = bad
            with self.assertRaisesRegex(ValueError, 'let_ring must be boolean'):
                tab.validate_score(song)
        head['let_ring'] = True
        for gate in ('palm_mute', 'staccato'):
            head[gate] = True
            with self.assertRaisesRegex(ValueError, 'let_ring conflicts'):
                tab.validate_score(song)
            del head[gate]
            edit = dict(op='note_set', pattern='A', beat='head', note=dict(id='n', **{gate: True}))
            gated = tab.apply_score_edit(song, edit)
            self.assertNotIn('let_ring', gated['score']['patterns']['A']['beats'][0]['notes'][0])
            ringed = tab.apply_score_edit(gated, dict(op='note_set', pattern='A', beat='head',
                                                     note=dict(id='n', let_ring=True)))
            self.assertNotIn(gate, ringed['score']['patterns']['A']['beats'][0]['notes'][0])
            edit['note']['let_ring'] = True
            with self.assertRaisesRegex(ValueError, 'choose let_ring'):
                tab.apply_score_edit(song, edit)
        cleared = tab.apply_score_edit(song, dict(op='note_set', pattern='A', beat='head',
                                                  note=dict(id='n', let_ring=False)))
        self.assertEqual(self.release(cleared, raw)['at'], [1, 1])
        head.update(pitch=0, string=None, fret=None)
        with self.assertRaisesRegex(ValueError, 'let_ring needs resolved string/fret'):
            tab.playback_plan(song, raw)


class TestNativeRepetition(unittest.TestCase):
    def fixture(self, effect='trill', value=16):
        song, raw = plan_fixture()
        item = dict(note('n', 69, 1, 5), velocity=95)
        item[effect] = dict(value=value, **({'fret': 7} if effect == 'trill' else {}))
        source = beat('b', [0, 1], [item])
        song['score']['patterns']['A']['beats'] = [source]
        song['score']['patterns']['B']['beats'] = []
        song['score']['ties'] = []
        return song, raw, source, item

    def vector(self, plan, origin=Fraction(0)):
        ons = [e for e in plan['events'] if e['type'] == 'note_on']
        offs = {e['id']: e for e in plan['events'] if e['type'] == 'note_off'}
        return [((Fraction(*e['at']) - origin) * 960,
                 (Fraction(*offs[e['id']]['at']) - origin) * 960, e['pitch']) for e in ons]

    def test_rates_pulse_identity_and_logical_ownership(self):
        for effect, rates in [('trill', (4, 8, 16, 32, 64)), ('tremolo_picking', (8, 16, 32))]:
            for rate in rates:
                with self.subTest(effect=effect, rate=rate):
                    song, raw, _, item = self.fixture(effect, rate)
                    before = copy.deepcopy(song)
                    plan = tab.playback_plan(song, raw, 48000)
                    length, count = 3840 // rate, rate // 4
                    self.assertEqual(self.vector(plan), [
                        (i * length, min((i + 1) * length, 959),
                         71 if effect == 'trill' and i % 2 else 69) for i in range(count)])
                    self.assertEqual(plan['positions'][0]['attack_id'], 'oa/n')
                    self.assertEqual(plan['positions'][0]['pitch'], item['pitch'])
                    self.assertEqual(plan['positions'][0]['instrument'], 1)
                    for event in plan['events']:
                        self.assertEqual(event['id'], f"oa/n/pulse/{event['pulse']}")
                        self.assertEqual(event['source_id'], 'oa/n')
                        self.assertEqual((event['occurrence'], event['pattern'], event['beat'], event['note']),
                                         ('oa', 'A', 'b', 'n'))
                        self.assertEqual((event['authored_velocity'], event['velocity']), (95, 95))
                    self.assertEqual(song, before)
                    self.assertEqual(tab.playback_plan(yaml.safe_load(yaml.safe_dump(song)), raw, 48000), plan)
                    # Equal-frame retriggers release the previous pulse first.
                    for left, right in zip(plan['events'], plan['events'][1:]):
                        if left['frame'] == right['frame']:
                            self.assertEqual((left['type'], right['type']), ('note_off', 'note_on'))

    def test_dots_tuplets_clipping_and_short_tail(self):
        for value, dots, division, rate, expected in [
                (4, 1, [1, 1], 16, [(i * 240, min((i + 1) * 240, 1439)) for i in range(6)]),
                (4, 0, [13, 8], 16, [(0, 240), (240, 480), (480, 589)]),
                (4, 0, [7, 4], 64, [(i * 60, (i + 1) * 60) for i in range(9)])]:
            with self.subTest(division=division, dots=dots):
                song, raw, source, _ = self.fixture(value=rate)
                source['written'] = dict(value=value, dots=dots, tuplet=division)
                vector = self.vector(tab.playback_plan(song, raw))
                self.assertEqual([(a, b) for a, b, _ in vector], expected)

    def test_fractional_tie_carry_and_head_gate(self):
        for gate, expected in [
                (None, [(0, 240), (240, 480), (480, 720), (720, 885)]),
                ('staccato', [(0, 240), (240, 442)]),
                ('palm_mute', [(0, 119)])]:
            with self.subTest(gate=gate):
                song, raw, source, item = self.fixture()
                source['at'] = [4, 13]
                source['written'].update(value=8, tuplet=[13, 8])
                if gate:
                    item[gate] = True
                for index in (2, 3):
                    continuation = beat(f'b{index}', [4 * index, 13],
                                        [dict(note(f'n{index}', 69, 1, 5), velocity=31)], 8, [13, 8])
                    song['score']['patterns']['A']['beats'].append(continuation)
                    song['score']['ties'].append(dict(
                        **{'from': dict(occurrence='oa', note='n' if index == 2 else 'n2')},
                        to=dict(occurrence='oa', note=f'n{index}')))
                plan = tab.playback_plan(song, raw)
                self.assertEqual([(a, b) for a, b, _ in self.vector(plan, Fraction(4, 13))], expected)
                self.assertTrue(all(e['velocity'] == 95 for e in plan['events']))
                self.assertEqual([p['attack_id'] for p in plan['positions']], ['oa/n'] * 3)
                self.assertEqual(plan['events'][0]['at'], [4, 13])
                if gate is None:
                    self.assertEqual(plan['events'][-1]['at'], [1023, 832])

    def test_zero_pulses_keep_resolved_written_position(self):
        song, raw, source, item = self.fixture()
        # 60/6 = 10 ticks: TG's strict tick+10 < duration test emits nothing.
        source['written'].update(value=64, tuplet=[6, 1])
        plan = tab.playback_plan(song, raw)
        self.assertEqual(plan['events'], [])
        self.assertEqual(len(plan['positions']), 1)
        self.assertEqual((plan['positions'][0]['attack_id'], plan['positions'][0]['instrument']),
                         ('oa/n', 1))
        # A one-tick chain gated by staccato becomes zero ticks, still notation.
        source['written']['tuplet'] = [60, 1]
        item['staccato'] = True
        gated = tab.playback_plan(song, raw)
        self.assertEqual(gated['events'], [])
        self.assertEqual(gated['positions'][0]['sounding_end'], [0, 1])
        del item['velocity']
        with self.assertRaisesRegex(ValueError, 'explicit authored MIDI velocity'):
            tab.playback_plan(song, raw)

    def test_untied_heads_restart_and_continuation_effect_does_not_start(self):
        song, raw, source, item = self.fixture(value=8)
        source['written']['value'] = 8
        second = beat('b2', [1, 2], [dict(item, id='n2')], 8)
        song['score']['patterns']['A']['beats'].append(second)
        self.assertEqual(self.vector(tab.playback_plan(song, raw)), [(0, 479, 69), (480, 959, 69)])
        song['score']['ties'] = [{'from': dict(occurrence='oa', note='n'),
                                 'to': dict(occurrence='oa', note='n2')}]
        self.assertEqual(self.vector(tab.playback_plan(song, raw)), [(0, 480, 69), (480, 959, 71)])
        del item['trill']
        del item['velocity']
        self.assertEqual(self.vector(tab.playback_plan(song, raw)), [(0, 960, 69)])

    def test_tempo_boundary_and_head_owned_cross_occurrence_pulses(self):
        for effect in ('trill', 'tremolo_picking'):
            song, raw, source, item = self.fixture(effect, 8)
            song['module']['tempo'] = 240
            source['at'] = [15, 4]
            source['written']['value'] = 16
            song['score']['patterns']['B']['beats'] = [
                beat('last', [0, 1], [dict(note('lastn', 69, 1, 5), velocity=31)])]
            song['score']['ties'] = [{'from': dict(occurrence='oa', note='n'),
                                     'to': dict(occurrence='ob', note='lastn')}]
            raw[1].rows[0][6] = parse_cell('... .. ... T3C')
            plan = tab.playback_plan(song, raw, 48000)
            self.assertEqual(self.vector(plan), [(3600, 4080, 69),
                             (4080, 4560, 71 if effect == 'trill' else 69), (4560, 4799, 69)])
            middle = next(e for e in plan['events'] if e['type'] == 'note_on' and e['pulse'] == 1)
            self.assertEqual((middle['at'], middle['seconds'], middle['frame'], middle['occurrence']),
                             ([17, 4], [5, 4], 60000, 'oa'))
            item['palm_mute'] = True
            item[effect]['value'] = 32
            gated = tab.playback_plan(song, raw, 48000)
            self.assertEqual(self.vector(gated), [(3600, 3720, 69),
                             (3720, 3839, 71 if effect == 'trill' else 69)])

    def test_velocity_dynamics_hammer_and_harmonic_bypass(self):
        for flag, velocity, expected in [('ghost', 95, 79), ('ghost', 16, 15),
                                          ('accent', 120, 127), ('heavy_accent', 63, 95)]:
            song, raw, _, item = self.fixture()
            item.update(velocity=velocity, **{flag: True})
            self.assertTrue(all(e['velocity'] == expected for e in tab.playback_plan(song, raw)['events']))
        song, raw, source, item = self.fixture()
        source['at'] = [1, 1]
        song['score']['patterns']['A']['beats'].insert(
            0, beat('before', [0, 1], [dict(note('before', 69, 1, 5), velocity=95, hammer=True)]))
        self.assertTrue(all(e['velocity'] == 70 for e in tab.playback_plan(song, raw)['events']
                            if e.get('source_id') == 'oa/n'))
        for kind in ('natural', 'artificial', 'tapped', 'pinch', 'semi'):
            song, raw, _, item = self.fixture()
            # Without repetition the harmonic would exceed the native pitch range.
            song['score']['tracks']['guitar']['tuning'][0] = 100
            item.update(pitch=105, harmonic=dict(type=kind, data=5))
            plan = tab.playback_plan(song, raw)
            self.assertTrue(all('layers' not in e for e in plan['events']))
            self.assertEqual([p for _, _, p in self.vector(plan)], [105, 107, 105, 107])

    def test_trill_capo_automatic_string_and_native_pitch_bounds(self):
        song, raw, _, item = self.fixture()
        song['score']['tracks']['guitar']['capo'] = 2
        item.update(pitch=71)
        self.assertEqual([p for _, _, p in self.vector(tab.playback_plan(song, raw))], [71, 73, 71, 73])
        item.pop('string')
        item.pop('fret')
        self.assertEqual(tab.playback_plan(song, raw)['positions'][0]['string'], 1)
        item.update(pitch=0)
        with self.assertRaisesRegex(ValueError, 'resolved string/fret'):
            tab.validate_score(song)
        item.update(pitch=119, string=1, fret=19)
        song['score']['tracks']['guitar'].update(tuning=[100, 59, 55, 50, 45, 40], capo=0)
        item['trill']['fret'] = 20
        with self.assertRaisesRegex(ValueError, 'alternate exceeds native pitch'):
            tab.validate_score(song)

    def test_validation_requires_exact_rate_and_fret_shapes(self):
        for effect, bad in [('trill', {}), ('trill', dict(value=8)), ('trill', dict(value=True, fret=7)),
                            ('trill', dict(value=2, fret=7)), ('trill', dict(value=16, fret=30)),
                            ('trill', dict(value=16, fret=True)), ('trill', dict(value=16, fret=7, extra=1)),
                            ('tremolo_picking', dict(value=4)), ('tremolo_picking', dict(value=64)),
                            ('tremolo_picking', dict(value=16, fret=7)), ('tremolo_picking', [])]:
            song, _, _, item = self.fixture(effect)
            item[effect] = bad
            with self.subTest(effect=effect, bad=bad), self.assertRaises(ValueError):
                tab.validate_score(song)
        song, raw, _, item = self.fixture()
        del item['velocity']
        with self.assertRaisesRegex(ValueError, 'explicit authored MIDI velocity'):
            tab.playback_plan(song, raw)
        with self.assertRaisesRegex(ValueError, 'explicit authored MIDI velocity'):
            tab.project_score(song, raw)

    def test_conflicting_raw_effects_refuse_and_edits_clear_both_directions(self):
        conflicts = dict(bend={'points': []}, tremolo_bar={'points': []},
                         dead=True, slide=True, hammer=True, vibrato=True,
                         tremolo_picking={'value': 8})
        for key, value in conflicts.items():
            song, _, _, item = self.fixture()
            item[key] = value
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, 'repetition conflicts'):
                tab.validate_score(song)
            del item[key]
            item.update(harmonic=dict(type='semi'), ghost=True, staccato=True)
            enabled = tab.apply_score_edit(song, dict(op='note_set', pattern='A', beat='b',
                                                      note=dict(id='n', **{key: value})))
            edited = enabled['score']['patterns']['A']['beats'][0]['notes'][0]
            self.assertNotIn('trill', edited)
            restored = tab.apply_score_edit(enabled, dict(op='note_set', pattern='A', beat='b',
                                                          note=dict(id='n', trill=dict(value=4, fret=7))))
            edited = restored['score']['patterns']['A']['beats'][0]['notes'][0]
            self.assertNotIn(key, edited)
            self.assertTrue(all(k in edited for k in ('harmonic', 'ghost', 'staccato')))
            with self.assertRaisesRegex(ValueError, 'choose one repetition'):
                tab.apply_score_edit(song, dict(op='note_set', pattern='A', beat='b',
                    note=dict(id='n', trill=dict(value=4, fret=7), **{key: value})))
        for effect in ('trill', 'tremolo_picking'):
            song, _, _, _ = self.fixture(effect)
            before = copy.deepcopy(song)
            cleared = tab.apply_score_edit(song, dict(op='note_set', pattern='A', beat='b',
                                                      note=dict(id='n', **{effect: None})))
            self.assertNotIn(effect, cleared['score']['patterns']['A']['beats'][0]['notes'][0])
            self.assertEqual(song, before)

    def test_event_cap_during_expansion(self):
        song, raw, source, _ = self.fixture(value=64)
        source['written']['value'] = 1
        song['orders'] = ['A'] * 1563  # 128 events per occurrence exceeds 200000.
        song['score']['order_ids'] = [f'o{i}' for i in range(1563)]
        with self.assertRaisesRegex(ValueError, 'exceeds 200000 events'):
            tab.playback_plan(song, raw)


class TestNativeHarmonics(unittest.TestCase):
    def fixture(self, kind='semi', data=0, pitch=52, fret=12, velocity=95):
        song, raw = plan_fixture()
        song['score']['ties'] = []
        song['score']['patterns']['B']['beats'] = []
        item = dict(note('harmonic', pitch, 6, fret), harmonic=dict(type=kind, data=data))
        if velocity is not None:
            item['velocity'] = velocity
        song['score']['patterns']['A']['beats'] = [beat('h', [0, 1], [item])]
        return song, raw

    def test_source_layers_are_distinct_ordered_and_authored_pitch_survives(self):
        for kind, pitches, velocities in [('semi', [52, 52, 64], [47, 31, 95]),
                                          ('artificial', [52, 64], [31, 95]),
                                          ('tapped', [52, 64], [31, 95]),
                                          ('pinch', [52, 64], [31, 95]),
                                          ('natural', [40, 52], [31, 95])]:
            with self.subTest(kind=kind):
                song, raw = self.fixture(kind)
                before = copy.deepcopy(song)
                plan = tab.playback_plan(song, raw, 48000)
                attack, release = plan['events']
                self.assertEqual([v['pitch'] for v in attack['layers']], pitches)
                self.assertEqual([v['velocity'] for v in attack['layers']], velocities)
                self.assertEqual((attack['pitch'], release['frame'], plan['positions'][0]['pitch']), (52, 24000, 52))
                self.assertEqual(song, before)
                self.assertEqual(tab.playback_plan(yaml.safe_load(yaml.safe_dump(song)), raw, 48000), plan)

    def test_offsets_natural_modulo_dynamics_and_refusals(self):
        for data, offset in enumerate((12, 28, 24, 19, 28, 31)):
            song, raw = self.fixture('artificial', data)
            item = song['score']['patterns']['A']['beats'][0]['notes'][0]
            item['ghost'] = True
            layers = tab.playback_plan(song, raw, 48000)['events'][0]['layers']
            self.assertEqual(layers, [dict(pitch=40 + offset, velocity=15), dict(pitch=52 + offset, velocity=79)])
        song, raw = self.fixture('natural', pitch=64, fret=24)
        self.assertEqual([n['pitch'] for n in tab.playback_plan(song, raw, 48000)['events'][0]['layers']], [40, 52])
        song, raw = self.fixture('natural', pitch=0, fret=24)
        song['score']['tracks']['guitar']['tuning'][5] = 0
        song['score']['tracks']['guitar']['capo'] = -24
        self.assertEqual(tab.playback_plan(song, raw, 48000)['events'][0]['layers'], [dict(pitch=0, velocity=95)])
        song, raw = self.fixture(velocity=None)
        with self.assertRaisesRegex(ValueError, 'requires explicit'):
            tab.playback_plan(song, raw, 48000)
        song, raw = self.fixture()
        song['score']['tracks']['guitar']['tuning'][5] = 100
        item = song['score']['patterns']['A']['beats'][0]['notes'][0]
        item.update(pitch=112)
        with self.assertRaisesRegex(ValueError, 'exceeds native pitch range'):
            tab.playback_plan(song, raw, 48000)
        for value in ({'type': 'wrong'}, {'type': 'semi', 'data': 6}, {'type': 'semi', 'data': True}):
            song, raw = self.fixture()
            song['score']['patterns']['A']['beats'][0]['notes'][0]['harmonic'] = value
            with self.subTest(value=value), self.assertRaises(ValueError):
                tab.playback_plan(song, raw, 48000)

    def test_harmonic_edit_clear_and_tie_head_ownership(self):
        song, raw = self.fixture()
        original = copy.deepcopy(song)
        cleared = tab.apply_score_edit(song, dict(op='note_set', pattern='A', beat='h',
                                                note=dict(id='harmonic', harmonic=None)))
        self.assertNotIn('harmonic', cleared['score']['patterns']['A']['beats'][0]['notes'][0])
        self.assertNotIn('layers', tab.playback_plan(cleared, raw, 48000)['events'][0])
        song['score']['patterns']['A']['beats'][0]['written']['value'] = 1
        song['score']['patterns']['B']['beats'] = [beat('continuation', [0, 1], [note('continued', 52, 6, 12)])]
        song['score']['ties'] = [{'from': {'occurrence': 'oa', 'note': 'harmonic'},
                                 'to': {'occurrence': 'ob', 'note': 'continued'}}]
        plan = tab.playback_plan(song, raw, 48000)
        self.assertEqual(len(plan['events']), 2)
        self.assertEqual(plan['events'][0]['layers'], [dict(pitch=52, velocity=47), dict(pitch=52, velocity=31), dict(pitch=64, velocity=95)])
        self.assertEqual(plan['events'][1]['frame'], 120000)
        self.assertEqual(original['score']['patterns']['A']['beats'][0]['notes'][0]['harmonic']['type'], 'semi')


class TestNativeDynamics(unittest.TestCase):
    def fixture(self):
        song, raw = plan_fixture()
        song['score']['ties'] = []
        song['score']['patterns']['A']['beats'] = [
            beat('prior', [0, 1], [dict(note('prior', 64, 1, 0), hammer=True)]),
            beat('rest', [1, 1], []),
            beat('other_string', [2, 1], [note('other', 60, 2, 1)])]
        song['score']['patterns']['B']['beats'] = [
            beat('target', [0, 1], [dict(note('target', 65, 1, 1), velocity=95)])]
        return song, raw

    def attack(self, song, raw, identity='ob/target'):
        return next(e for e in tab.playback_plan(song, raw, 48000)['events']
                    if e['type'] == 'note_on' and e['id'] == identity)

    def test_source_numeric_vectors_and_authored_velocity_preservation(self):
        vectors = [(0, 15, 16, 32, 15, 15, 31), (15, 15, 31, 47, 15, 15, 31),
                   (31, 15, 47, 63, 15, 15, 31), (95, 79, 111, 127, 70, 54, 86),
                   (127, 111, 127, 127, 102, 86, 118)]
        modes = [(False, 'ghost'), (False, 'accent'), (False, 'heavy_accent'),
                 (True, None), (True, 'ghost'), (True, 'accent')]
        for velocity, *expected in vectors:
            for (hammer, dynamic), want in zip(modes, expected):
                with self.subTest(velocity=velocity, hammer=hammer, dynamic=dynamic):
                    song, raw = self.fixture()
                    song['score']['patterns']['A']['beats'][0]['notes'][0]['hammer'] = hammer
                    target = song['score']['patterns']['B']['beats'][0]['notes'][0]
                    target['velocity'] = velocity
                    if dynamic:
                        target[dynamic] = True
                    original = copy.deepcopy(song)
                    attack = self.attack(song, raw)
                    self.assertEqual((attack['velocity'], attack['authored_velocity']), (want, velocity))
                    self.assertIsNone(attack['volume'])
                    position = next(p for p in tab.authoring_view(song, raw)['positions'] if p['id'] == 'ob/target' and p['kind'] == 'note')
                    self.assertEqual(position['velocity'], velocity)
                    position = next(p for p in tab.playback_plan(song, raw)['positions'] if p['id'] == 'ob/target')
                    self.assertEqual(position['velocity'], velocity)
                    self.assertEqual(song, original)
        song, raw = self.fixture()
        target = song['score']['patterns']['B']['beats'][0]['notes'][0]
        target.update(ghost=True, accent=True, heavy_accent=True)
        self.assertEqual(self.attack(song, raw)['velocity'], 54)
        target['ghost'] = False
        self.assertEqual(self.attack(song, raw)['velocity'], 86)

    def test_missing_velocity_only_refuses_consumed_dynamics(self):
        song, raw = self.fixture()
        # The hammer predecessor itself and the unrelated other-string attack inherit.
        self.assertIsNone(self.attack(song, raw, 'oa/prior')['velocity'])
        self.assertIsNone(self.attack(song, raw, 'oa/other')['velocity'])
        target = song['score']['patterns']['B']['beats'][0]['notes'][0]
        target.pop('velocity')
        with self.assertRaisesRegex(ValueError, 'ob/target: hammer predecessor oa/prior requires explicit'):
            tab.playback_plan(song, raw)
        song['score']['patterns']['A']['beats'][0]['notes'][0]['hammer'] = False
        self.assertIsNone(self.attack(song, raw)['velocity'])
        for flag in ('ghost', 'accent', 'heavy_accent'):
            target[flag] = True
            with self.subTest(flag=flag), self.assertRaisesRegex(ValueError, f'ob/target: {flag} requires explicit'):
                tab.playback_plan(song, raw)
            target.pop(flag)

    def test_tied_written_predecessor_masks_head_and_can_own_next_hammer(self):
        song, raw = self.fixture()
        song['score']['patterns']['A']['beats'] = [
            beat('head', [3, 1], [dict(note('head', 64, 1, 0), hammer=True)])]
        song['score']['patterns']['B']['beats'] = [
            beat('cont', [0, 1], [dict(note('cont', 64, 1, 0), ghost=True)]),
            beat('target', [1, 1], [dict(note('target', 65, 1, 1), velocity=95)])]
        song['score']['ties'] = [{'from': dict(occurrence='oa', note='head'),
                                 'to': dict(occurrence='ob', note='cont')}]
        self.assertEqual(self.attack(song, raw)['velocity'], 95)
        self.assertIsNone(self.attack(song, raw, 'oa/head')['velocity'])
        self.assertFalse(any(e['id'] == 'ob/cont' for e in tab.playback_plan(song, raw)['events']))
        song['score']['patterns']['B']['beats'][0]['notes'][0]['hammer'] = True
        self.assertEqual(self.attack(song, raw)['velocity'], 70)
        # A new unmarked same-string attack now masks the continuation.
        song['score']['patterns']['B']['beats'].append(
            beat('later', [2, 1], [dict(note('later', 64, 1, 0), velocity=95)]))
        self.assertEqual(self.attack(song, raw, 'ob/later')['velocity'], 95)

    def test_voice_occurrence_and_ambiguous_raw_boundaries(self):
        song, raw = self.fixture()
        # Cross-occurrence lookup passes the rest and the other-string note.
        self.assertEqual(self.attack(song, raw)['velocity'], 70)
        raw[0].rows[18][0] = Cell(note=64, instrument=1)
        with self.assertRaisesRegex(ValueError, 'ob/target: raw attack makes hammer predecessor oa/prior ambiguous'):
            tab.playback_plan(song, raw)
        # Unrelated raw channel and raw key-off do not invalidate the lookup.
        raw[0].rows[18][0] = Cell(note=NOTE_OFF)
        raw[0].rows[18][5] = Cell(note=40, instrument=1)
        self.assertEqual(self.attack(song, raw)['velocity'], 70)
        # Moving the predecessor to the other voice removes the modifier.
        song['score']['patterns']['A']['beats'][0]['voice'] = 1
        self.assertEqual(self.attack(song, raw)['velocity'], 95)
        # Raw attacks alone do not block an independent authored ghost.
        raw[0].rows[18][0] = Cell(note=64, instrument=1)
        song['score']['patterns']['B']['beats'][0]['notes'][0]['ghost'] = True
        self.assertEqual(self.attack(song, raw)['velocity'], 79)
        song, raw = self.fixture()
        song['score']['patterns']['B']['beats'][0]['notes'][0] = dict(id='target', pitch=0, velocity=95)
        with self.assertRaisesRegex(ValueError, 'hammer predecessor lookup needs resolved'):
            tab.playback_plan(song, raw)

    def test_setters_clipboard_reload_and_history_snapshots_recompute(self):
        from types import SimpleNamespace
        from vulturetracker import history
        song, raw = self.fixture()
        original = copy.deepcopy(song)
        edit = dict(op='note_set', pattern='B', beat='target', note=dict(id='target', ghost=True))
        changed = tab.apply_score_edit(song, edit)
        self.assertEqual(self.attack(changed, raw)['velocity'], 54)
        for flag in ('accent', 'heavy_accent'):
            edit['note'] = dict(id='target', **{flag: True})
            changed = tab.apply_score_edit(changed, edit)
            n = changed['score']['patterns']['B']['beats'][0]['notes'][0]
            self.assertEqual([k for k in ('ghost', 'accent', 'heavy_accent') if n.get(k)], [flag])
        self.assertEqual(self.attack(changed, raw)['velocity'], 102)
        undo = history.pack_step({'text': yaml.safe_dump(original)})
        redo = history.pack_step({'text': yaml.safe_dump(changed)})
        restored = yaml.safe_load(history.unpack_step(undo)['text'])
        replayed = yaml.safe_load(history.unpack_step(redo)['text'])
        self.assertEqual(self.attack(restored, raw)['velocity'], 70)
        self.assertEqual(self.attack(replayed, raw)['velocity'], 102)
        clip = tab.capture_score_clipboard(changed, 'B', ['target'], 'ob')
        pasted = tab.paste_score_clipboard(changed, SimpleNamespace(patterns=raw), 1, 24, clip)
        copied = pasted['score']['patterns']['B']['beats'][-1]['notes'][0]
        self.assertTrue(copied['heavy_accent'])
        self.assertEqual(copied['velocity'], 95)
        self.assertEqual(self.attack(pasted, raw, 'ob/' + copied['id'])['velocity'], 127)
        self.assertEqual(song, original)
        for field in ('ghost', 'accent', 'heavy_accent', 'hammer'):
            candidate = copy.deepcopy(original)
            candidate['score']['patterns']['A']['beats'][0]['notes'][0] = dict(note('prior', 64, 1, 0), **{field: True})
            candidate['score']['patterns']['B']['beats'][0]['notes'][0].pop('velocity')
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, 'requires explicit authored MIDI velocity'):
                tab.project_score(candidate, raw)
            for invalid in (1, None, 'true'):
                with self.assertRaisesRegex(ValueError, 'must be boolean'):
                    tab.apply_score_edit(original, dict(op='note_set', pattern='A', beat='prior',
                                                       note={'id': 'prior', field: invalid}))
        with self.assertRaisesRegex(ValueError, 'choose one ghost'):
            tab.apply_score_edit(song, dict(op='note_set', pattern='B', beat='target',
                                           note=dict(id='target', ghost=True, accent=True)))
        for flag, value in (('dead', True), ('slide', True), ('bend', {'points': [{'position': 0, 'value': 2}]}),
                            ('tremolo_bar', {'points': []})):
            with self.subTest(flag=flag):
                changed = tab.apply_score_edit(song, dict(op='note_set', pattern='A', beat='prior',
                                                         note={'id': 'prior', flag: value}))
                self.assertNotIn('hammer', changed['score']['patterns']['A']['beats'][0]['notes'][0])
                changed = tab.apply_score_edit(changed, dict(op='note_set', pattern='A', beat='prior',
                                                            note=dict(id='prior', hammer=True)))
                self.assertNotIn(flag, changed['score']['patterns']['A']['beats'][0]['notes'][0])
                self.assertEqual(self.attack(changed, raw)['velocity'], 70)


class TestPlaceScoreCommand(unittest.TestCase):
    def fixture(self):
        song, raw = plan_fixture()
        song['score']['ties'] = []
        song['score']['patterns']['A']['beats'] = [beat('rest', [0, 1], [], 1)]
        return song, raw

    def placed(self, at=Fraction(1, 2), length=Fraction(1, 2), identity='placed'):
        result = beat(identity, [at.numerator, at.denominator], [note('new', 64, 1, 0)])
        result['written'] = dict(value=4, dots=0, tuplet=[length.denominator, length.numerator])
        return result

    def checked(self, song, raw, placed, error=None, occurrence='oa'):
        edit = dict(action='place', occurrence=occurrence, beat=placed)
        before = copy.deepcopy((song, raw, edit))
        if error:
            with self.assertRaisesRegex(ValueError, error):
                tab.score_command(song, raw, edit)
            result = None
        else:
            result = tab.score_command(song, raw, edit)
        self.assertEqual((song, raw, edit), before)
        return result

    def test_exact_interior_remainders_and_identity_at_rest_onset(self):
        for at in (Fraction(0), Fraction(1, 2), Fraction(1, 13)):
            song, raw = self.fixture()
            song['score']['patterns']['A']['beats'][0].update(stem='auto', text='')
            after, result = self.checked(song, raw, self.placed(at))
            parts = sorted(after['score']['patterns']['A']['beats'], key=lambda b: Fraction(*b['at']))
            cursor = Fraction(0)
            for part in parts:
                self.assertEqual(Fraction(*part['at']), cursor)
                cursor += tab.duration_quarters(part['written'])
            self.assertEqual(cursor, 4)
            self.assertEqual(parts[0]['id'], 'rest')
            selected = next(b for b in parts if b['notes'])
            self.assertEqual(Fraction(*selected['at']), at)
            self.assertEqual(selected['written'], self.placed(at)['written'])
            self.assertEqual(result['selection']['beats'], [selected['id']])
            self.assertEqual(result['selection']['at'], [at.numerator, at.denominator])
            self.assertNotIn('clipboard', result)
            self.assertEqual(after['patterns'], song['patterns'])
            self.assertEqual(after['score']['patterns']['B'], song['score']['patterns']['B'])

    def test_growth_consumes_only_rests_and_shrink_fills_only_vacated_tail(self):
        song, raw = self.fixture()
        beats = [beat('head', [0, 1], [note('head-note', 64, 1, 0)]),
                 beat('r1', [1, 1], []), beat('r2', [2, 1], []),
                 beat('later', [3, 1], [note('later-note', 65, 1, 1)])]
        song['score']['patterns']['A']['beats'] = beats
        placed = copy.deepcopy(beats[0])
        placed['written'] = dict(value=2, dots=0, tuplet=[4, 5])
        after, _ = self.checked(song, raw, placed)
        actual = {b['id']: b for b in after['score']['patterns']['A']['beats']}
        self.assertNotIn('r1', actual)
        self.assertEqual(actual['r2']['at'], [5, 2])
        self.assertEqual(tab.duration_quarters(actual['r2']['written']), Fraction(1, 2))
        self.assertEqual(actual['later'], beats[-1])
        self.assertEqual(actual['head']['notes'], beats[0]['notes'])
        smaller = copy.deepcopy(actual['head'])
        smaller['written'] = dict(value=4, dots=0, tuplet=[1, 1])
        shrunk, _ = self.checked(after, raw, smaller)
        unchanged = {b['id']: b for b in shrunk['score']['patterns']['A']['beats']}
        self.assertEqual(unchanged['r2'], actual['r2'])
        self.assertEqual(unchanged['later'], actual['later'])
        fill = [b for b in unchanged.values() if b['id'] not in actual]
        self.assertEqual(sum((tab.duration_quarters(b['written']) for b in fill), Fraction(0)), Fraction(3, 2))
        placed['written'] = dict(value=2, dots=1, tuplet=[6, 7])
        self.checked(song, raw, placed, 'overlaps sounding beat later')

    def test_other_voice_is_preserved_and_occupied_lane_refuses(self):
        song, raw = self.fixture()
        other = beat('peer', [1, 2], [note('peer-note', 59, 2, 0)], 2, voice=1)
        song['score']['patterns']['A']['beats'].append(other)
        after, _ = self.checked(song, raw, self.placed())
        self.assertEqual(next(b for b in after['score']['patterns']['A']['beats'] if b['id'] == 'peer'), other)
        other['notes'][0] = note('peer-note', 64, 1, 0)
        self.checked(song, raw, self.placed(), 'occupied by the other voice')

    def test_annotated_rest_and_peer_cohort_refusals(self):
        patches = [dict(text='keep'), dict(stem='up'), dict(duration_source='tracker_boundary'),
                   dict(chord=dict(name='E', first_fret=0, frets=[0, 0, 0, 0, 0, 0])),
                   dict(stroke=dict(direction='down', value=4)), dict(pick_stroke='up')]
        for patch in patches:
            song, raw = self.fixture()
            song['score']['patterns']['A']['beats'][0].update(patch)
            with self.subTest(patch=patch):
                self.checked(song, raw, self.placed(), 'annotated rest')
        song, raw = self.fixture()
        song['score']['patterns']['A']['beats'].append(dict(
            beat('peer', [0, 1], [], 1, voice=1), text='shared onset'))
        self.checked(song, raw, self.placed(), 'annotated cohort peer')

    def test_measure_pattern_and_unspellable_boundaries_refuse(self):
        song, raw = self.fixture()
        self.checked(song, raw, self.placed(Fraction(1, 17)), 'unsupported written subdivision')
        self.checked(song, raw, self.placed(Fraction(7, 2), Fraction(1)), 'pattern boundary')
        song['score']['measures'] = [
            dict(id='m', meter=[2, 4], **{'from': dict(occurrence='oa', at=[0, 1]),
                                         'to': dict(occurrence='oa', at=[2, 1])})]
        self.checked(song, raw, self.placed(), 'affected rest crosses a measure')
        song['score']['patterns']['A']['beats'][0]['written']['value'] = 2
        after, _ = self.checked(song, raw, self.placed())
        self.assertEqual(sum(tab.duration_quarters(b['written'])
                             for b in after['score']['patterns']['A']['beats']), 2)

    def test_shared_pattern_bounds_and_ties_are_checked_in_every_occurrence(self):
        song, raw = self.fixture()
        song['orders'].append('A')
        song['score']['order_ids'].append('oa2')
        song['score']['patterns']['A']['beats'][0]['written']['value'] = 4
        after, _ = self.checked(song, raw, self.placed())
        self.assertEqual(after['orders'], song['orders'])
        song['score']['measures'] = [
            dict(id='first', meter=[2, 4], **{'from': dict(occurrence='oa', at=[0, 1]),
                                             'to': dict(occurrence='oa', at=[2, 1])}),
            dict(id='last', meter=[3, 4], **{'from': dict(occurrence='oa2', at=[0, 1]),
                                            'to': dict(occurrence='oa2', at=[3, 1])})]
        self.checked(song, raw, self.placed(), 'different measure bounds')
        song['score']['measures'] = []
        source = beat('head', [0, 1], [note('head-note', 64, 1, 0)])
        tail = beat('tail', [1, 1], [note('tail-note', 64, 1, 0)])
        song['score']['patterns']['A']['beats'] = [source, tail]
        song['score']['ties'] = [dict(**{'from': dict(occurrence='oa2', note='head-note'),
                                        'to': dict(occurrence='oa2', note='tail-note')})]
        shorter = copy.deepcopy(source)
        shorter['written']['value'] = 8
        after, result = self.checked(song, raw, shorter)
        self.assertEqual(after['score']['ties'], [])
        self.assertEqual(result['removed_ties'], song['score']['ties'])
        same = copy.deepcopy(source)
        same['notes'].append(note('extra', 59, 2, 0))
        after, _ = self.checked(song, raw, same)
        self.assertEqual(after['score']['ties'], song['score']['ties'])

    def test_raw_collision_identity_and_note_mutation_refuse(self):
        song, raw = self.fixture()
        raw[0].rows[6][0] = Cell(note=64, instrument=1)
        self.checked(song, raw, self.placed(), 'raw note/release conflicts')
        raw[0].rows[6][0] = Cell()
        moved = self.placed(identity='rest')
        self.checked(song, raw, moved, 'cannot relocate')
        target = beat('head', [0, 1], [note('n', 64, 1, 0)])
        song['score']['patterns']['A']['beats'] = [target]
        changed = copy.deepcopy(target)
        changed['notes'][0]['velocity'] = 90
        self.checked(song, raw, changed, 'preserve existing notes')
        changed = copy.deepcopy(target)
        changed['notes'] = []
        self.checked(song, raw, changed, 'preserve existing notes')
        self.checked(song, raw, self.placed(Fraction(0)), 'overlaps sounding beat head')

    def test_implicit_gap_and_percussion_share_exact_interval_behavior(self):
        song, raw = self.fixture()
        song['score']['patterns']['A']['beats'] = []
        placed = self.placed(Fraction(1, 17))
        after, result = self.checked(song, raw, placed)
        self.assertEqual(result['selection']['at'], [1, 17])
        self.assertEqual(after['score']['patterns']['A']['beats'], [placed])
        song, raw = self.fixture()
        track = song['score']['tracks']['guitar']
        track.update(tuning=[0] * 6, midi=dict(program=0, bank=128))
        song['score']['patterns']['B']['beats'] = []
        placed = self.placed()
        placed['notes'] = [note('kick', 36, 1, 36)]
        after, _ = self.checked(song, raw, placed)
        actual = next(b for b in after['score']['patterns']['A']['beats'] if b['notes'])
        self.assertEqual(actual['notes'], placed['notes'])
        self.assertEqual(actual['at'], [1, 2])

    def test_generated_ids_do_not_collide_and_new_ids_cannot_reuse_note_identity(self):
        song, raw = self.fixture()
        untouched = beat('rest_rest', [0, 1], [], 1, track='bass')
        song['score']['patterns']['A']['beats'].append(untouched)
        after, _ = self.checked(song, raw, self.placed())
        actual = {b['id']: b for b in after['score']['patterns']['A']['beats']}
        self.assertEqual(actual['rest_rest'], untouched)
        self.assertIn('rest_rest_2', actual)
        song['score']['patterns']['A']['beats'].append(
            beat('elsewhere', [0, 1], [note('new', 40, 1, 0)], track='bass'))
        # Remove the bass rest so the source is valid; only the new note ID clashes.
        song['score']['patterns']['A']['beats'].remove(untouched)
        self.checked(song, raw, self.placed(), 'duplicate note')

    def test_sounding_target_metadata_stays_and_changed_provenance_is_cleared(self):
        song, raw = self.fixture()
        target = dict(beat('head', [0, 1], [note('n', 64, 1, 0)], 2),
                      text='retain', stem='up', duration_source='tracker_boundary')
        song['score']['patterns']['A']['beats'] = [target]
        smaller = copy.deepcopy(target)
        smaller['written']['value'] = 4
        after, _ = self.checked(song, raw, smaller)
        actual = next(b for b in after['score']['patterns']['A']['beats'] if b['id'] == 'head')
        self.assertEqual((actual['text'], actual['stem'], actual['notes']),
                         (target['text'], target['stem'], target['notes']))
        self.assertNotIn('duration_source', actual)
        self.assertTrue(all(not any(k in b for k in ('text', 'stem', 'duration_source'))
                            for b in after['score']['patterns']['A']['beats'] if not b['notes']))


class TestPlaceFitCommand(unittest.TestCase):
    def fixture(self, insufficient=False):
        song, raw = TestPlaceScoreCommand().fixture()
        notes = [beat('a', [0, 1], [note('a-note', 64, 1, 0)]),
                 beat('b', [1, 1], [note('b-note', 66, 1, 2)]),
                 beat('c', [2 if insufficient else 3, 1], [note('c-note', 68, 1, 4)])]
        notes.append(beat('r', [3 if insufficient else 2, 1], []))
        song['score']['patterns']['A']['beats'] = sorted(notes, key=lambda b: Fraction(*b['at']))
        return song, raw

    def request(self, song, mode='tg_duration', length=Fraction(2)):
        placed = copy.deepcopy(song['score']['patterns']['A']['beats'][0])
        placed['written'] = dict(value=4, dots=0, tuplet=[length.denominator, length.numerator])
        if mode == 'tg_insert':
            placed['notes'].append(note('added', 59, 2, 0))
        return dict(action='place', occurrence='oa', fit=mode, beat=placed)

    def checked(self, song, raw, request, error=None):
        before = copy.deepcopy((song, raw, request))
        if error:
            with self.assertRaisesRegex(ValueError, error):
                tab.score_command(song, raw, request)
            result = None
        else:
            result = tab.score_command(song, raw, request)
        self.assertEqual((song, raw, request), before)
        return result

    def test_measured_manager_cases_exact_and_fallback(self):
        for case, length in (('exact', Fraction(2)), ('insufficient', Fraction(5, 2))):
            for mode in ('tg_duration', 'tg_insert'):
                song, raw = self.fixture(case == 'insufficient')
                request = self.request(song, mode, length)
                with self.subTest(case=case, mode=mode):
                    candidate, result = self.checked(song, raw, request)
                    self.assertEqual(result['fit']['requested'], request['beat']['written'])
                    self.assertEqual(result['fit']['outcome'], 'shifted' if case == 'exact' else
                                     'old_duration' if mode == 'tg_insert' else 'unchanged')
                    self.assertEqual(tab.duration_quarters(result['fit']['applied']), 2 if case == 'exact' else 1)
                    expected = {64: (0, 1920), 66: (1920, 2880), 68: (2880, 3840)} if case == 'exact' else {
                        64: (0, 960), 66: (960, 1920), 68: (1920, 2880)}
                    if mode == 'tg_insert':
                        expected[59] = expected[64]
                    events = [e for e in tab.playback_plan(candidate, raw)['events']
                              if e['id'].startswith('oa/') and e['type'] in ('note_on', 'note_off')]
                    actual = {}
                    for event in events:
                        actual.setdefault(event['pitch'], {})[event['type']] = Fraction(*event['at']) * 960
                    self.assertEqual({key: (g['note_on'], g['note_off']) for key, g in actual.items()}, expected)
                    original = {b['id']: b for b in song['score']['patterns']['A']['beats']}
                    after = {b['id']: b for b in candidate['score']['patterns']['A']['beats']}
                    self.assertEqual(after['b']['notes'], original['b']['notes'])
                    self.assertEqual(after['b']['written'], original['b']['written'])
                    self.assertEqual(after['c'], original['c'])
                    if case == 'insufficient':
                        self.assertEqual(after['r'], original['r'])
                        if mode == 'tg_duration':
                            self.assertEqual(candidate, song)
                    else:
                        self.assertNotIn('r', after)
                    self.assertEqual(candidate['patterns'], song['patterns'])
                    self.assertEqual(candidate['score']['patterns']['B'], song['score']['patterns']['B'])

    def test_default_is_still_strict_and_no_shift_exact_edit_uses_existing_path(self):
        song, raw = self.fixture()
        request = self.request(song)
        strict = {k: v for k, v in request.items() if k != 'fit'}
        self.checked(song, raw, strict, 'overlaps sounding beat b')
        request['beat']['written']['tuplet'] = [2, 1]
        candidate, result = self.checked(song, raw, request)
        self.assertEqual(result['fit']['outcome'], 'exact')
        self.assertEqual(next(b['at'] for b in candidate['score']['patterns']['A']['beats'] if b['id'] == 'b'), [1, 1])
        request = self.request(song, length=Fraction(1))
        candidate, result = self.checked(song, raw, request)
        self.assertEqual(candidate, song)
        self.assertEqual(result['fit']['outcome'], 'unchanged')

    def test_annotations_techniques_ties_and_gaps_do_not_trigger_fallback(self):
        for case, reason in (('text', 'annotated cohort'), ('ghost', None),
                             ('tie', 'incident tied'), ('gap', 'continuous explicit'),
                             ('velocity', None)):
            song, raw = self.fixture(insufficient=True)
            beats = song['score']['patterns']['A']['beats']
            if case == 'text':
                beats[-1]['text'] = 'retain'
            elif case == 'ghost':
                beats[1]['notes'][0]['ghost'] = True
            elif case == 'tie':
                beats[2]['notes'][0].update(pitch=66, fret=2)
                song['score']['ties'] = [dict(**{'from': dict(occurrence='oa', note='b-note'),
                                                'to': dict(occurrence='oa', note='c-note')})]
            elif case == 'gap':
                beats.pop()
            else:
                beats[1]['notes'][0]['velocity'] = 79
            with self.subTest(case=case):
                self.checked(song, raw, self.request(song, 'tg_insert', Fraction(5, 2)), reason)

    def test_peer_lane_raw_conflicts_and_destination_metadata_refuse(self):
        for case, reason in (('lane', 'occupied by the other voice'),
                             ('annotation', 'annotated cohort'), ('raw', 'raw note/release conflicts')):
            song, raw = self.fixture()
            if case == 'raw':
                raw[0].rows[24][0] = Cell(note=70, instrument=1)
            else:
                peer = beat('peer', [2, 1], [note('peer-note', 66, 1, 2)] if case == 'lane' else [], voice=1)
                if case == 'annotation':
                    peer['text'] = 'stay'
                song['score']['patterns']['A']['beats'].append(peer)
            with self.subTest(case=case):
                self.checked(song, raw, self.request(song), reason)
        song, raw = self.fixture(insufficient=True)
        raw[0].rows[0][1] = Cell(note=59, instrument=1)
        self.checked(song, raw, self.request(song, 'tg_insert', Fraction(5, 2)), 'raw note/release conflicts')

    def test_shared_uses_require_equivalent_bounds_and_validate_later_ties(self):
        song, raw = self.fixture()
        song['orders'].append('A')
        song['score']['order_ids'].append('oa2')
        candidate, result = self.checked(song, raw, self.request(song))
        self.assertEqual(candidate['orders'], song['orders'])
        song['score']['measures'] = [
            dict(id='first', meter=[4, 4], **{'from': dict(occurrence='oa', at=[0, 1]),
                                             'to': dict(occurrence='oa', at=[4, 1])}),
            dict(id='later', meter=[3, 4], **{'from': dict(occurrence='oa2', at=[0, 1]),
                                             'to': dict(occurrence='oa2', at=[3, 1])})]
        self.checked(song, raw, self.request(song), 'different measure bounds')
        song, raw = self.fixture(insufficient=True)
        song['orders'].append('A')
        song['score']['order_ids'].append('oa2')
        song['score']['patterns']['A']['beats'][2]['notes'][0].update(pitch=66, fret=2)
        song['score']['ties'] = [dict(**{'from': dict(occurrence='oa2', note='b-note'),
                                        'to': dict(occurrence='oa2', note='c-note')})]
        self.checked(song, raw, self.request(song, 'tg_insert', Fraction(5, 2)), 'incident tied')

    def test_fit_intents_reject_note_replacement_and_invalid_modes(self):
        song, raw = self.fixture()
        for mode in ('bad', None, [], True):
            request = self.request(song)
            request['fit'] = mode
            with self.subTest(mode=mode):
                self.checked(song, raw, request, 'fit must be')
        request = self.request(song)
        request['beat']['notes'][0]['pitch'] = 65
        self.checked(song, raw, request, 'complete note list unchanged')
        request = self.request(song)
        request['fit'] = 'tg_insert'
        self.checked(song, raw, request, 'append exactly one')


class TestPlacePartialFitCommand(unittest.TestCase):
    fixture = TestPlaceFitCommand.fixture
    request = TestPlaceFitCommand.request
    checked = TestPlaceFitCommand.checked

    def test_middle_and_trailing_rest_rebuilds_match_retained_spans_and_gates(self):
        for trailing in (False, True):
            for mode in ('tg_duration', 'tg_insert'):
                with self.subTest(trailing=trailing, mode=mode):
                    song, raw = self.fixture(trailing)
                    request = self.request(song, mode, Fraction(3, 2))
                    candidate, result = self.checked(song, raw, request)
                    self.assertEqual(result['fit'], dict(requested=request['beat']['written'],
                                                        applied=request['beat']['written'], outcome='shifted'))
                    original = {b['id']: b for b in song['score']['patterns']['A']['beats']}
                    after = {b['id']: b for b in candidate['score']['patterns']['A']['beats']}
                    self.assertEqual(set(after), {'a', 'b', 'c'})
                    expected = {'a': (0, Fraction(3, 2)),
                                'b': (Fraction(3, 2), 1 if trailing else Fraction(3, 2)),
                                'c': (Fraction(5, 2) if trailing else 3, 1)}
                    for identity, (at, duration) in expected.items():
                        self.assertEqual(Fraction(*after[identity]['at']), at)
                        self.assertEqual(tab.duration_quarters(after[identity]['written']), duration)
                        self.assertEqual(after[identity]['notes'][:len(original[identity]['notes'])],
                                         original[identity]['notes'])
                    events = [e for e in tab.playback_plan(candidate, raw)['events']
                              if e['id'].startswith('oa/') and e['type'] in ('note_on', 'note_off')]
                    gates = {}
                    for event in events:
                        gates.setdefault(event['pitch'], {})[event['type']] = Fraction(*event['at']) * 960
                    wanted = {64: (0, 1440), 66: (1440, 2400 if trailing else 2880),
                              68: (2400, 3360) if trailing else (2880, 3840)}
                    if mode == 'tg_insert':
                        wanted[59] = (0, 1440)
                    self.assertEqual({key: (g['note_on'], g['note_off']) for key, g in gates.items()}, wanted)
                    self.assertEqual(candidate['patterns'], song['patterns'])
                    self.assertEqual(candidate['score']['patterns']['B'], song['score']['patterns']['B'])
                    strict = {k: v for k, v in request.items() if k != 'fit'}
                    self.checked(song, raw, strict, 'overlaps sounding beat b')

    def test_partial_refuses_peer_annotation_tie_technique_raw_and_shared_conflicts(self):
        for case, reason in (('peer', 'single active voice'), ('rest-text', 'annotated cohort'),
                             ('moved-text', None), ('tie', 'incident tied'),
                             ('ghost', None), ('raw', 'raw note/release conflicts'),
                             ('shared', 'different measure bounds')):
            with self.subTest(case=case):
                song, raw = self.fixture(case == 'tie')
                beats = song['score']['patterns']['A']['beats']
                if case == 'peer':
                    beats.append(beat('peer', [3, 2], [note('peer-note', 59, 2, 0)], 8, voice=1))
                elif case.endswith('text'):
                    beats[2 if case == 'rest-text' else 1]['text'] = 'must survive'
                elif case == 'tie':
                    beats[2]['notes'][0].update(pitch=66, fret=2)
                    song['score']['ties'] = [{'from': dict(occurrence='oa', note='b-note'),
                                              'to': dict(occurrence='oa', note='c-note')}]
                elif case == 'ghost':
                    beats[1]['notes'][0]['ghost'] = True
                elif case == 'raw':
                    raw[0].rows[30][0] = Cell(note=70, instrument=1)
                else:
                    song['orders'].append('A')
                    song['score']['order_ids'].append('oa2')
                    song['score']['measures'] = [
                        dict(id='first', meter=[4, 4], **{'from': dict(occurrence='oa', at=[0, 1]),
                                                        'to': dict(occurrence='oa', at=[4, 1])}),
                        dict(id='later', meter=[3, 4], **{'from': dict(occurrence='oa2', at=[0, 1]),
                                                        'to': dict(occurrence='oa2', at=[3, 1])})]
                if case == 'peer':
                    after,_ = self.checked(song, raw, self.request(song, length=Fraction(3, 2)))
                    self.assertEqual(tab._beat(after['score'], 'A', 'peer'), beats[-1])
                elif case == 'moved-text':
                    after,_ = self.checked(song, raw, self.request(song, length=Fraction(3, 2)))
                    self.assertEqual(tab._beat(after['score'], 'A', 'b')['text'], 'must survive')
                else:
                    self.checked(song, raw, self.request(song, 'tg_insert' if case == 'tie' else 'tg_duration',
                                                        length=Fraction(3, 2)), reason)

    def test_partial_checks_later_removed_rests_and_all_shared_tie_uses(self):
        song, raw = self.fixture()
        beats = song['score']['patterns']['A']['beats']
        beats[3]['written'] = dict(value=8, dots=0, tuplet=[1, 1])
        beats.append(beat('tail', [7, 2], [], 8))
        beats[-1]['text'] = 'later rest'
        self.checked(song, raw, self.request(song, length=Fraction(3, 2)), 'annotated cohort tail')
        song, raw = self.fixture(True)
        song['orders'].append('A')
        song['score']['order_ids'].append('oa2')
        beats = song['score']['patterns']['A']['beats']
        beats[2]['notes'][0].update(pitch=66, fret=2)
        song['score']['ties'] = [{'from': dict(occurrence='oa2', note='b-note'),
                                  'to': dict(occurrence='oa2', note='c-note')}]
        self.checked(song, raw, self.request(song, 'tg_insert', length=Fraction(3, 2)), 'incident tied')

    def test_record_order_and_multirest_fill_work_but_sounding_replacement_refuses(self):
        song, raw = self.fixture()
        request = self.request(song, length=Fraction(3, 2))
        expected,_ = self.checked(song, raw, request)
        song['score']['patterns']['A']['beats'].reverse()
        after,_ = self.checked(song, raw, request)
        self.assertEqual(tab.project_score(after, raw).patterns, tab.project_score(expected, raw).patterns)
        song, raw = self.fixture()
        # Splitting B at the prospective destination would require occupied
        # destination reuse, beyond the fresh-cohort measurements.
        beats = song['score']['patterns']['A']['beats']
        beats[1]['written'] = dict(value=8, dots=0, tuplet=[1, 1])
        beats.insert(2, beat('b2', [3, 2], [note('b2-note', 67, 1, 3)], 8))
        self.checked(song, raw, self.request(song, length=Fraction(3, 2)), 'sounding move destination')
        song, raw = self.fixture()
        after,_ = self.checked(song, raw, self.request(song, length=Fraction(5, 4)))
        self.assertEqual(Fraction(*tab._beat(after['score'], 'A', 'b')['at']), Fraction(5, 4))
        self.assertEqual(tab.duration_quarters(tab._beat(after['score'], 'A', 'b')['written']), Fraction(5, 4))
        tab.project_score(after, raw)


class TestPlacePeerFitCommand(unittest.TestCase):
    request = TestPlaceFitCommand.request
    checked = TestPlaceFitCommand.checked

    def fixture(self, alternate=False, voice=0):
        song, raw = TestPlaceFitCommand().fixture()
        active = song['score']['patterns']['A']['beats']
        lengths = [Fraction(1, 2), Fraction(1, 2), Fraction(1), Fraction(2)] if alternate else [Fraction(1)] * 4
        at = Fraction(0)
        for record, length in zip(active, lengths):
            record.update(at=tab._pair(at), written=tab._written_for(length), voice=voice)
            at += length
        requested = lengths[0] + lengths[1] / 2
        rest_start = lengths[0] + lengths[1]
        peers = []
        for identity, at, length, notes in (
                ('prefix', Fraction(0), requested, []),
                ('peer', requested, rest_start - requested, [note('peer-note', 59, 2, 0)]),
                ('suffix', rest_start, 4 - rest_start, [])):
            record = beat(identity, tab._pair(at), notes, voice=1 - voice)
            record['written'] = tab._written_for(length)
            peers.append(record)
        active.extend(peers)
        return song, raw, requested

    def test_retained_peer_callbacks_and_all_original_peer_records(self):
        for mode in ('tg_duration', 'tg_insert'):
            with self.subTest(mode=mode):
                song, raw, length = self.fixture()
                candidate, result = self.checked(song, raw, self.request(song, mode, length))
                before = {b['id']: b for b in song['score']['patterns']['A']['beats']}
                after = {b['id']: b for b in candidate['score']['patterns']['A']['beats']}
                self.assertEqual(set(after), set(before) - {'r'})
                for identity in ('prefix', 'peer', 'suffix'):
                    self.assertEqual(after[identity], before[identity])
                for identity in ('b', 'c'):
                    self.assertEqual(after[identity]['notes'], before[identity]['notes'])
                    self.assertEqual(after[identity]['written'], before[identity]['written'])
                self.assertEqual(after['b']['at'], [3, 2])
                self.assertEqual(after['c']['at'], [5, 2] if mode == 'tg_duration' else [3, 1])
                self.assertEqual(result['fit']['outcome'], 'shifted')
                self.assertEqual(result['selection']['beats'], ['a'])
                events = [(e['type'], Fraction(*e['at']) * 960, e['pitch'])
                          for e in tab.playback_plan(candidate, raw)['events']
                          if e['id'].startswith('oa/') and e['type'] in ('note_on', 'note_off')]
                gates = [(64, 0, 1440), (66, 1440, 2400), (59, 1440, 1920),
                         (68, 2400, 3360) if mode == 'tg_duration' else (68, 2880, 3840)]
                if mode == 'tg_insert':
                    gates.append((59, 0, 1440))
                expected = [(kind, at, pitch) for pitch, start, end in gates
                            for kind, at in (('note_on', start), ('note_off', end))]
                self.assertEqual(sorted(events), sorted(expected))
                self.assertEqual(candidate['patterns'], song['patterns'])
                self.assertEqual(candidate['score']['patterns']['B'], song['score']['patterns']['B'])

    def test_relationships_support_other_lengths_voice_and_flat_record_order(self):
        for voice in (0, 1):
            for mode in ('tg_duration', 'tg_insert'):
                with self.subTest(voice=voice, mode=mode):
                    song, raw, length = self.fixture(True, voice)
                    request = self.request(song, mode, length)
                    expected, _ = self.checked(song, raw, request)
                    song['score']['patterns']['A']['beats'].reverse()
                    candidate, _ = self.checked(song, raw, request)
                    after = {b['id']: b for b in candidate['score']['patterns']['A']['beats']}
                    self.assertEqual(after, {b['id']: b for b in expected['score']['patterns']['A']['beats']})
                    self.assertEqual(after['b']['at'], [3, 4])
                    self.assertEqual(after['c']['at'], [5, 4] if mode == 'tg_duration' else [2, 1])
                    for peer in song['score']['patterns']['A']['beats']:
                        if peer.get('voice', 0) != voice:
                            self.assertEqual(after[peer['id']], peer)

    def test_unsupported_topology_annotations_lane_technique_and_raw_refuse(self):
        for case, reason in (('incomplete', 'supported peer-only topology'),
                             ('occupied', 'sounding move destination'),
                             ('peer-move', 'supported peer-only topology'),
                             ('prefix', 'annotated cohort'), ('peer', None),
                             ('suffix', 'annotated cohort'), ('lane', 'occupied by the other voice'),
                             ('technique', None), ('raw', 'raw note/release conflicts'),
                             ('normalization', 'change another beat or shared annotation')):
            with self.subTest(case=case):
                song, raw, length = self.fixture()
                beats = song['score']['patterns']['A']['beats']
                by_id = {b['id']: b for b in beats}
                if case == 'incomplete':
                    beats.remove(by_id['prefix'])
                elif case == 'occupied':
                    by_id['b']['written'] = tab._written_for(Fraction(1, 2))
                    beats.append(beat('extra', [3, 2], [note('extra-note', 67, 1, 3)], 8))
                elif case == 'peer-move':
                    by_id['prefix']['written'] = tab._written_for(Fraction(7, 4))
                    by_id['peer']['at'] = [7, 4]
                    by_id['peer']['written'] = tab._written_for(Fraction(1, 4))
                elif case in ('prefix', 'peer', 'suffix'):
                    by_id[case]['text'] = 'retain this'
                elif case == 'lane':
                    by_id['peer']['notes'][0].update(pitch=66, string=1, fret=2)
                elif case == 'technique':
                    by_id['peer']['notes'][0]['ghost'] = True
                elif case == 'normalization':
                    by_id['prefix']['chord'] = None
                else:
                    raw[0].rows[30][0] = Cell(note=70, instrument=1)
                if case in ('incomplete', 'peer-move', 'peer'):
                    after,_ = self.checked(song, raw, self.request(song, length=length))
                    comparable=lambda b:{k:v for k,v in b.items() if case!='peer' or k!='text'}
                    self.assertEqual([comparable(b) for b in after['score']['patterns']['A']['beats'] if b['voice'] == 1],
                                     [comparable(b) for b in beats if b['voice'] == 1])
                    if case=='peer':
                        group=[b for b in after['score']['patterns']['A']['beats'] if b['at']==by_id['peer']['at']]
                        self.assertEqual([b['text'] for b in group if b.get('text')],['retain this'])
                    tab.project_score(after, raw)
                else:
                    self.checked(song, raw, self.request(song, length=length), reason)

    def test_later_shared_tie_and_unequal_bounds_refuse(self):
        for case in ('tie', 'bounds'):
            song, raw, length = self.fixture()
            song['orders'].append('A')
            song['score']['order_ids'].append('oa2')
            if case == 'tie':
                beats = song['score']['patterns']['A']['beats']
                beats[1]['notes'][0].update(pitch=64, fret=0)
                song['score']['ties'] = [{'from': dict(occurrence='oa2', note='a-note'),
                                          'to': dict(occurrence='oa2', note='b-note')}]
                reason = 'incident tied'
            else:
                song['score']['measures'] = [
                    dict(id='first', meter=[4, 4], **{'from': dict(occurrence='oa', at=[0, 1]),
                                                    'to': dict(occurrence='oa', at=[4, 1])}),
                    dict(id='later', meter=[3, 4], **{'from': dict(occurrence='oa2', at=[0, 1]),
                                                    'to': dict(occurrence='oa2', at=[3, 1])})]
                reason = 'different measure bounds'
            with self.subTest(case=case):
                self.checked(song, raw, self.request(song, 'tg_insert' if case == 'tie' else 'tg_duration',
                                                    length=length), reason)


class TestTiedDurationCommand(unittest.TestCase):
    checked = TestPlaceFitCommand.checked

    def request(self, song, pattern, identity, written, fit=False):
        placed = copy.deepcopy(tab._beat(song['score'], pattern, identity))
        placed['written'] = written
        return dict(action='place', occurrence='o' + pattern.lower(), beat=placed,
                    **({'fit': 'tg_duration'} if fit else {}))

    def test_cross_bar_continuation_values_dots_tuplets_keep_one_attack(self):
        for value, dots, tuplet in ((4, 0, [1, 1]), (16, 0, [1, 1]), (32, 0, [1, 1]),
                                    (8, 1, [1, 1]), (8, 0, [3, 2])):
            for fit in (False, True):
                with self.subTest(value=value, dots=dots, tuplet=tuplet, fit=fit):
                    song, raw = fixture()
                    written = dict(value=value, dots=dots, tuplet=tuplet)
                    after, result = self.checked(song, raw, self.request(song, 'B', 'head', written, fit))
                    self.assertEqual(after['score']['ties'], song['score']['ties'])
                    self.assertEqual(result['removed_ties'], [])
                    self.assertEqual(result['selection']['beats'], ['head'])
                    self.assertEqual(after['score']['patterns']['A'], song['score']['patterns']['A'])
                    self.assertEqual(after['patterns'], song['patterns'])
                    events = [e for e in tab.playback_plan(after, raw)['events']
                              if e['type'] in ('note_on', 'note_off') and e['id'] == 'oa/tailn']
                    self.assertEqual([(e['type'], Fraction(*e['at'])) for e in events],
                                     [('note_on', Fraction(7, 2)),
                                      ('note_off', 4 + tab.duration_quarters(written))])
                    projected = tab.project_score(after, raw).patterns
                    self.assertIsNone(projected[1].rows[0][0].note)
                    if value == 32:
                        off = projected[1].rows[1][0]
                        self.assertEqual((off.note, off.effect, off.param), (NOTE_OFF, 19, 0xD1))

    def test_shortened_cross_bar_head_detaches_only_the_broken_edge(self):
        song, raw = fixture()
        after, result = self.checked(song, raw, self.request(song, 'A', 'tail',
                                      dict(value=16, dots=0, tuplet=[1, 1])))
        self.assertEqual(result['removed_ties'], song['score']['ties'])
        self.assertEqual(after['score']['ties'], [])
        self.assertEqual(after['score']['patterns']['B'], song['score']['patterns']['B'])
        projected = tab.project_score(after, raw).patterns
        self.assertEqual(projected[0].rows[45][0].note, NOTE_OFF)
        self.assertEqual(projected[1].rows[0][0].note, 64)
        self.assertEqual(projected[0].rows[0][1].effect, 24)

    def test_middle_segment_keeps_incoming_edge_and_detaches_outgoing(self):
        song, raw = TestPlaceFitCommand().fixture(True)
        beats = song['score']['patterns']['A']['beats']
        for b in beats[:3]:
            b['notes'][0].update(pitch=64, fret=0)
        edges = [{'from': dict(occurrence='oa', note=a + '-note'),
                  'to': dict(occurrence='oa', note=b + '-note')} for a, b in (('a', 'b'), ('b', 'c'))]
        song['score']['ties'] = edges
        after, result = self.checked(song, raw, self.request(song, 'A', 'b',
                                      dict(value=8, dots=0, tuplet=[1, 1])))
        self.assertEqual(after['score']['ties'], edges[:1])
        self.assertEqual(result['removed_ties'], edges[1:])
        projection = tab.project_score(after, raw)
        self.assertIsNone(projection.patterns[0].rows[12][0].note)
        self.assertEqual(projection.patterns[0].rows[18][0].note, NOTE_OFF)
        self.assertEqual(projection.patterns[0].rows[24][0].note, 64)

    def test_fit_moves_tied_continuation_with_head_and_keeps_boundary_edge(self):
        for dots in (0, 1):
            song, raw = TestPlaceFitCommand().fixture()
            beats = song['score']['patterns']['A']['beats']
            beats[1]['notes'][0].update(pitch=64, fret=0)
            song['score']['patterns']['B']['beats'] = [beat('tail', [0, 1], [note('tail-note', 68, 1, 4)])]
            song['score']['ties'] = [
                {'from': dict(occurrence='oa', note='a-note'), 'to': dict(occurrence='oa', note='b-note')},
                {'from': dict(occurrence='oa', note='c-note'), 'to': dict(occurrence='ob', note='tail-note')}]
            written = dict(value=4 if dots else 2, dots=dots, tuplet=[1, 1])
            after, result = self.checked(song, raw, self.request(song, 'A', 'a', written, True))
            self.assertEqual(result['fit']['outcome'], 'shifted')
            self.assertEqual(result['removed_ties'], [])
            self.assertEqual(after['score']['ties'], song['score']['ties'])
            self.assertEqual(Fraction(*tab._beat(after['score'], 'A', 'b')['at']),
                             tab.duration_quarters(written))
            projection = tab.project_score(after, raw)
            attacks = [(p, row) for p, pattern in enumerate(projection.patterns)
                       for row, cells in enumerate(pattern.rows) if cells[0].note in (64, 68)]
            self.assertEqual(attacks, [(0, 0), (0, 36)])

    def test_range_retains_original_ids_and_detaches_only_changed_edges(self):
        song, raw = fixture()
        selection = [dict(occurrence='oa', beats=['tail']), dict(occurrence='ob', beats=['head'])]
        request = dict(action='set_duration', track='guitar', voice=0, selection=selection,
                       written=dict(value=16, dots=0, tuplet=[1, 1]))
        after, result = self.checked(song, raw, request)
        for original, selected in zip(selection, result['selection']['range']):
            self.assertTrue(set(original['beats']) <= set(selected['beats']))
        self.assertEqual(result['removed_ties'], song['score']['ties'])
        for name, identity in (('A', 'tail'), ('B', 'head')):
            self.assertEqual(tab._beat(after['score'], name, identity)['written'], request['written'])
        self.assertEqual([b for b in after['score']['patterns']['A']['beats'] if b['track'] == 'bass'],
                         [b for b in song['score']['patterns']['A']['beats'] if b['track'] == 'bass'])
        tab.project_score(after, raw)

    def test_overflow_raw_collision_and_unsupported_tick_remain_atomic(self):
        song, raw = fixture()
        self.checked(song, raw, self.request(song, 'A', 'tail', dict(value=4)), 'pattern boundary')
        raw[1].rows[9][0] = Cell(note=66, instrument=1)
        self.checked(song, raw, self.request(song, 'B', 'head', dict(value=4)), 'raw note/release conflicts')
        raw[1].rows[9][0] = Cell()
        before = copy.deepcopy((song, raw))
        after, _ = self.checked(song, raw, self.request(song, 'B', 'head', dict(value=64)))
        with self.assertRaisesRegex(ValueError, 'not representable'):
            tab.project_score(after, raw)
        self.assertEqual((song, raw), before)

    def test_no_space_fit_keeps_tied_source_and_insert_still_refuses(self):
        song, raw = TestPlaceFitCommand().fixture(True)
        beats = song['score']['patterns']['A']['beats']
        beats[1]['notes'][0].update(pitch=64, fret=0)
        song['score']['ties'] = [{'from': dict(occurrence='oa', note='a-note'),
                                  'to': dict(occurrence='oa', note='b-note')}]
        request = TestPlaceFitCommand().request(song, length=Fraction(5, 2))
        after, result = self.checked(song, raw, request)
        self.assertEqual(after, song)
        self.assertEqual(result['fit']['outcome'], 'unchanged')
        self.assertEqual(result['removed_ties'], [])
        self.checked(song, raw, TestPlaceFitCommand().request(song, 'tg_insert'), 'incident tied')


class TestEverydayRhythmCommand(unittest.TestCase):
    checked = TestPlaceFitCommand.checked

    def fixture(self):
        song, raw = fixture()
        song['score']['ties'] = []
        for name in ('A', 'B'):
            song['score']['patterns'][name]['beats'] = [
                beat('a', [0, 1], [note('an', 64, 1, 0)]), beat('r1', [1, 1], []),
                beat('b', [2, 1], [note('bn', 66, 1, 2)]), beat('r3', [3, 1], [])]
        song['score']['patterns']['A']['beats'].append(beat('peer', [0, 1], [note('pn', 59, 2, 0)], 1, voice=1))
        selection = [dict(occurrence='o' + name.lower(), beats=[b['id'] for b in song['score']['patterns'][name]['beats']])
                     for name in ('A', 'B')]
        return song, raw, dict(action='set_duration', track='guitar', voice=0, selection=selection,
                               written=dict(value=2, dots=0, tuplet=[1, 1]))

    def test_selected_rests_consumed_and_sequence_remains_a_qualified_phrase(self):
        for fit in (None, 'tg_duration'):
            song, raw, request = self.fixture()
            if fit:
                request['fit'] = fit
            first, report = self.checked(song, raw, request)
            self.assertEqual(len(report['consumed_rests']), 4)
            self.assertEqual(report['selection']['range'], [dict(occurrence='oa', beats=['a', 'peer', 'b']),
                                                           dict(occurrence='ob', beats=['a', 'b'])])
            source = first
            for value, dots, tuplet in ((4, 0, [1, 1]), (4, 1, [1, 1]), (4, 0, [3, 2]), (4, 0, [1, 1])):
                request.update(selection=report['selection']['range'], written=dict(value=value, dots=dots, tuplet=tuplet))
                source, report = self.checked(source, raw, request)
                # Every next command can use the returned phrase as-is.
                tab._score_range(source, raw, dict(request, action='transpose', selection=report['selection']['range']))
                tab.project_score(source, raw)
                self.assertEqual(tab._beat(source['score'], 'A', 'peer'), tab._beat(song['score'], 'A', 'peer'))

    def test_rebuilt_selected_rest_is_not_edited_twice_in_one_command(self):
        song, raw, request = self.fixture()
        request.update(fit='tg_duration', written=dict(value=4, dots=1, tuplet=[1, 1]))
        after, report = self.checked(song, raw, request)
        self.assertEqual(report['outcomes'], ['exact', 'rebuilt', 'exact', 'rebuilt'] * 2)
        self.assertEqual(report['consumed_rests'], [])
        for name in ('A', 'B'):
            beats = {b['id']: b for b in after['score']['patterns'][name]['beats']}
            self.assertEqual([beats[b]['at'] for b in ('a', 'b')], [[0, 1], [2, 1]])
            self.assertEqual([beats[b]['written'] for b in ('a', 'b')], [request['written']] * 2)
            self.assertEqual([beats[b]['at'] for b in ('r1', 'r3')], [[3, 2], [7, 2]])
            self.assertTrue(all(beats[b]['written']['value'] == 8 for b in ('r1', 'r3')))

    def test_partial_fit_multirest_fill_and_unaffected_peer_topologies(self):
        for kind in ('whole-note', 'whole-rest', 'split', 'none'):
            song, raw = TestPlaceFitCommand().fixture()
            beats = song['score']['patterns']['A']['beats']
            peers = []
            if kind.startswith('whole'):
                peers = [beat('peer', [0, 1], [note('pn', 40, 6, 0)] if kind == 'whole-note' else [], 1, voice=1)]
            elif kind == 'split':
                peers = [beat('pr1', [0, 1], [], 2, voice=1),
                         beat('peer', [2, 1], [note('pn', 40, 6, 0)], voice=1),
                         beat('pr2', [3, 1], [], voice=1)]
            beats.extend(peers)
            request = TestPlaceFitCommand().request(song)
            request['beat']['written'] = dict(value=4, dots=2, tuplet=[1, 1])
            after, report = self.checked(song, raw, request)
            self.assertEqual(report['fit']['outcome'], 'shifted')
            final = after['score']['patterns']['A']['beats']
            self.assertEqual([b for b in final if b['voice'] == 1], peers)
            self.assertEqual(tab._beat(after['score'], 'A', 'b')['at'], [7, 4])
            self.assertEqual(tab._beat(after['score'], 'A', 'b')['written']['value'], 16)
            self.assertEqual(sorted(Fraction(*b['at']) for b in final if b['voice'] == 0 and not b['notes']),
                             [Fraction(2), Fraction(9, 4), Fraction(5, 2), Fraction(11, 4)])
            tab.project_score(after, raw)

    def test_single_caret_and_mixed_bar_fallback_are_consistent(self):
        song, raw, request = self.fixture()
        song['score']['patterns']['B']['beats'] = [beat(f'b{i}', [i, 1], [note(f'n{i}', 64 + i, 1, i)])
                                                  for i in range(4)]
        request['selection'][1]['beats'] = [f'b{i}' for i in range(4)]
        for fit in (None, 'tg_duration'):
            trial = dict(request, **({'fit': fit} if fit else {}))
            after, report = self.checked(song, raw, trial)
            self.assertEqual(after['score']['patterns']['B'], song['score']['patterns']['B'])
            self.assertEqual(len(report['kept_durations']), 4)
            self.assertEqual(report['kept_durations'][-1]['reason'], 'bar_end')
            local = dict(action='set_duration', occurrence='ob', track='guitar', voice=0, beats=['b3'], written=trial['written'])
            same, result = self.checked(song, raw, local)
            self.assertEqual(same, song)
            self.assertEqual(result['selection']['beats'], ['b3'])
            self.assertEqual(result['kept_durations'][0]['reason'], 'bar_end')

    def test_moved_range_endpoint_includes_new_intervening_peer(self):
        song, raw = TestPlaceFitCommand().fixture()
        beats = song['score']['patterns']['A']['beats']
        beats.append(beat('peer', [3, 2], [note('pn', 59, 2, 0)], 8, voice=1))
        request = dict(action='set_duration', track='guitar', voice=0, selection=[dict(occurrence='oa', beats=['a', 'b'])],
                       written=dict(value=2, dots=0, tuplet=[1, 1]), fit='tg_duration')
        after, report = self.checked(song, raw, request)
        self.assertEqual(tab._beat(after['score'], 'A', 'b')['at'], [2, 1])
        self.assertIn('peer', report['selection']['range'][0]['beats'])
        tab._score_range(after, raw, dict(request, action='transpose', selection=report['selection']['range']))

    def test_real_conflicts_still_refuse_without_partial_phrase_mutation(self):
        for kind in ('annotation', 'raw'):
            song, raw, request = self.fixture()
            if kind == 'annotation':
                tab._beat(song['score'], 'B', 'r1')['text'] = 'retain this rest'
                reason = 'annotated rest'
            else:
                raw[1].rows[18][0] = Cell(note=70, instrument=1)
                reason = 'raw note/release conflicts'
            self.checked(song, raw, request, reason)

    def test_local_multi_selection_never_adopts_another_voice_rest(self):
        song, raw = TestPlaceFitCommand().fixture()
        song['score']['patterns']['A']['beats'].append(beat('peer', [0, 1], [], 1, voice=1))
        request = dict(action='set_duration', occurrence='oa', track='guitar', voice=0, beats=['a', 'b'],
                       written=dict(value=8, dots=0, tuplet=[1, 1]))
        after, report = self.checked(song, raw, request)
        self.assertNotIn('peer', report['selection']['beats'])
        self.checked(after, raw, dict(request, beats=report['selection']['beats'],
                                    written=dict(value=4, dots=0, tuplet=[1, 1])))

    def test_fit_implicit_gaps_equal_explicit_silence_and_noop_preserves_source(self):
        for trailing in (False, True):
            for length in (Fraction(3, 2), Fraction(2)):
                explicit, raw = TestPlaceFitCommand().fixture(trailing)
                request = TestPlaceFitCommand().request(explicit, length=length)
                expected, _ = self.checked(explicit, raw, request)
                implicit = copy.deepcopy(explicit)
                implicit['score']['patterns']['A']['beats'] = [b for b in implicit['score']['patterns']['A']['beats'] if b['notes']]
                after, _ = self.checked(implicit, raw, request)
                self.assertEqual(tab.project_score(after, raw).patterns, tab.project_score(expected, raw).patterns)
        # A half-quarter gap cannot absorb a whole quarter of growth. The
        # temporary explicit silence must not turn this no-op into a save.
        song, raw = TestPlaceFitCommand().fixture(True)
        song['score']['patterns']['A']['beats'] = [b for b in song['score']['patterns']['A']['beats'] if b['notes']]
        tab._beat(song['score'], 'A', 'c')['written'] = dict(value=4, dots=1, tuplet=[1, 1])
        after, result = self.checked(song, raw, TestPlaceFitCommand().request(song))
        self.assertEqual(after, song)
        self.assertEqual(result['fit']['outcome'], 'unchanged')
        # The gap may contain unrelated tracker material: moving through it
        # still cannot overwrite a raw attack or command.
        song, raw = TestPlaceFitCommand().fixture()
        song['score']['patterns']['A']['beats'] = [b for b in song['score']['patterns']['A']['beats'] if b['notes']]
        raw[0].rows[24][0] = Cell(note=70, instrument=1)
        self.checked(song, raw, TestPlaceFitCommand().request(song), 'raw note/release conflicts')


class TestSetDurationRangeCommand(unittest.TestCase):
    """TGSetDurationAction on a beat range: each beat in time order, as one candidate."""
    checked = TestPlaceFitCommand.checked

    def request(self, ids, value, fit=False, track='guitar', voice=0):
        return dict(action='set_duration', occurrence='oa', track=track, voice=voice, beats=ids,
                    written=dict(value=value, dots=0, tuplet=[1, 1]), **({'fit': 'tg_duration'} if fit else {}))

    def sequential(self, song, raw, ids, value, fit):
        """The same edits as separate single-beat commands, in time order."""
        candidate = song
        for identity in ids:
            placed = copy.deepcopy(tab._beat(candidate['score'], 'A', identity))
            placed['written'] = dict(value=value, dots=0, tuplet=[1, 1])
            candidate, _ = tab.score_command(candidate, raw, dict(
                action='place', occurrence='oa', beat=placed, **({'fit': 'tg_duration'} if fit else {})))
        return candidate

    def test_range_equals_single_beat_commands_in_time_order(self):
        for ids, value, fit in ((['b', 'a'], 8, False), (['a', 'b'], 2, True), (['a', 'b', 'c'], 8, True)):
            with self.subTest(ids=ids, value=value, fit=fit):
                song, raw = TestPlaceFitCommand().fixture()
                candidate, result = self.checked(song, raw, self.request(ids, value, fit))
                order = sorted(ids, key=lambda i: Fraction(*tab._beat(song['score'], 'A', i)['at']))
                self.assertEqual(candidate, self.sequential(song, raw, order, value, fit))
                self.assertNotEqual(candidate, song)
                self.assertEqual(len(result['outcomes']), len(ids))
                self.assertTrue(set(ids) <= set(result['selection']['beats']))
                after = {b['id']: b for b in candidate['score']['patterns']['A']['beats']}
                for identity in ids:
                    self.assertEqual(after[identity]['notes'], tab._beat(song['score'], 'A', identity)['notes'])
                self.assertEqual(candidate['patterns'], song['patterns'])

    def test_strict_shrink_keeps_onsets_and_any_refusal_writes_nothing(self):
        song, raw = TestPlaceFitCommand().fixture()
        candidate, _ = self.checked(song, raw, self.request(['a', 'b'], 8))
        after = {b['id']: b for b in candidate['score']['patterns']['A']['beats']}
        self.assertEqual([(after[i]['at'], after[i]['written']['value']) for i in ('a', 'b')], [([0, 1], 8), ([1, 1], 8)])
        self.assertEqual(after['c'], tab._beat(song['score'], 'A', 'c'))
        # A cannot grow without Fit, but B consumes the following rest in the same transaction.
        after,result = self.checked(song, raw, self.request(['a', 'b'], 2))
        self.assertEqual(tab._beat(after['score'], 'A', 'a')['written']['value'], 4)
        self.assertEqual(tab._beat(after['score'], 'A', 'b')['written']['value'], 2)
        self.assertEqual([r['reason'] for r in result['kept_durations']], ['no_space'])

    def test_selection_must_be_one_track_and_voice(self):
        song, raw = TestPlaceFitCommand().fixture()
        song['score']['patterns']['A']['beats'].append(beat('v1', [0, 1], [note('v1-note', 59, 2, 0)], voice=1))
        for request, error in (
                (self.request(['a', 'v1'], 8), 'selected track and voice'),
                (self.request(['a', 'a'], 8), 'distinct'),
                (self.request([], 8), 'distinct'),
                (dict(self.request(['a'], 8), fit='tg_insert'), 'fit'),
                (dict(self.request(['a'], 8), extra=1), 'unsupported'),
                (self.request(['a'], 3), 'power of two')):
            with self.subTest(error=error):
                self.checked(song, raw, request, error)

    def test_unchanged_range_returns_the_same_song(self):
        song, raw = TestPlaceFitCommand().fixture()
        candidate, result = self.checked(song, raw, self.request(['a', 'b'], 4, True))
        self.assertEqual(candidate, song)
        self.assertEqual(result['outcomes'], ['unchanged', 'unchanged'])


class TestRemoveUnusedVoiceCommand(unittest.TestCase):
    """TGRemoveUnusedVoiceAction: the last voice that is empty or a rest at every selected onset loses its
    rests in each selected measure where it has no note."""
    checked = TestPlaceFitCommand.checked

    def fixture(self, voice1=('rest', 'rest')):
        song, raw = TestPlaceFitCommand().fixture()
        beats = song['score']['patterns']['A']['beats']
        for i, kind in enumerate(voice1):
            notes = [note(f'v1n{i}', 59, 2, 0)] if kind == 'note' else []
            beats.append(beat(f'v1-{i}', [2 * i, 1], notes, value=2, voice=1))
        return song, raw

    def request(self, ids, track='guitar'):
        return dict(action='remove_unused_voice', occurrence='oa', track=track, beats=ids)

    def ids(self, song):
        return {b['id'] for b in song['score']['patterns']['A']['beats']}

    def test_rest_only_second_voice_is_removed_and_first_voice_kept(self):
        for selection in (['a'], ['a', 'c'], ['r']):
            with self.subTest(selection=selection):
                song, raw = self.fixture()
                candidate, result = self.checked(song, raw, self.request(selection))
                self.assertEqual((result['voice'], sorted(result['removed'])), (1, ['v1-0', 'v1-1']))
                self.assertEqual(self.ids(candidate), self.ids(song) - {'v1-0', 'v1-1'})
                voice0 = [b for b in song['score']['patterns']['A']['beats'] if b['voice'] == 0]
                self.assertEqual([b for b in candidate['score']['patterns']['A']['beats']], voice0)
                self.assertEqual(candidate['patterns'], song['patterns'])

    def test_a_note_anywhere_in_the_measure_keeps_the_voice(self):
        song, raw = self.fixture(('rest', 'note'))
        candidate, result = self.checked(song, raw, self.request(['a']))
        self.assertEqual((candidate, result['voice'], result['removed']), (song, 1, []))

    def test_both_voices_used_at_the_selection_changes_nothing(self):
        song, raw = self.fixture(('note', 'rest'))
        candidate, result = self.checked(song, raw, self.request(['a']))
        self.assertEqual((candidate, result['voice'], result['removed']), (song, None, []))

    def test_refusals(self):
        song, raw = self.fixture()
        song['score']['patterns']['A']['beats'][-1]['text'] = 'keep me'
        self.checked(song, raw, self.request(['a']), 'annotation')
        song, raw = self.fixture()
        for request, error in ((self.request([]), 'distinct'), (self.request(['a', 'a']), 'distinct'),
                               (dict(self.request(['a']), occurrence='nope'), 'occurrence'),
                               (dict(self.request(['a']), extra=1), 'unsupported'),
                               (self.request(['a'], track='other'), 'selected track')):
            with self.subTest(error=error):
                self.checked(song, raw, request, error)


class TestCleanBeatCommand(unittest.TestCase):
    """TGCleanBeatAction: both voices at each selected onset become rests and lose text/chord/strokes."""
    checked = TestPlaceFitCommand.checked

    def fixture(self):
        song, raw = TestPlaceFitCommand().fixture()
        beats = song['score']['patterns']['A']['beats']
        next(b for b in beats if b['id'] == 'a')['text'] = 'clean me'
        beats.append(beat('v1', [0, 1], [note('v1-note', 59, 2, 0)], voice=1))
        return song, raw

    def request(self, ids, track='guitar'):
        return dict(action='clean_beat', occurrence='oa', track=track, beats=ids)

    def test_both_voices_at_the_onset_become_plain_rests(self):
        for ids in (['a'], ['v1'], ['a', 'c']):
            with self.subTest(ids=ids):
                song, raw = self.fixture()
                candidate, result = self.checked(song, raw, self.request(ids))
                before = {b['id']: b for b in song['score']['patterns']['A']['beats']}
                after = {b['id']: b for b in candidate['score']['patterns']['A']['beats']}
                expected = {'a', 'v1'} | ({'c'} if 'c' in ids else set())
                self.assertEqual(set(result['cleaned']), expected)
                self.assertEqual(set(after), set(before))
                for identity, record in after.items():
                    if identity in expected:
                        self.assertEqual(record, {k: v for k, v in before[identity].items() if k != 'text'} | {'notes': []})
                    else:
                        self.assertEqual(record, before[identity])
                self.assertEqual(candidate['patterns'], song['patterns'])

    def test_rests_already_clean_change_nothing_and_ties_refuse(self):
        song, raw = TestPlaceFitCommand().fixture()
        candidate, result = self.checked(song, raw, self.request(['r']))
        self.assertEqual((candidate, result['cleaned']), (song, ['r']))
        song, raw = self.fixture()
        b = next(x for x in song['score']['patterns']['A']['beats'] if x['id'] == 'b')
        b['notes'][0].update(pitch=64, fret=0)
        song['score']['ties'] = [{'from': dict(occurrence='oa', note='a-note'), 'to': dict(occurrence='oa', note='b-note')}]
        self.checked(song, raw, self.request(['a']), 'tied')
        for request, error in ((self.request([]), 'distinct'), (self.request(['a'], track='other'), 'selected track'),
                               (dict(self.request(['a']), extra=1), 'unsupported')):
            with self.subTest(error=error):
                self.checked(song, raw, request, error)


class TestRetuneCommand(unittest.TestCase):
    """TGChangeTrackTuningAction: a uniform change keeps strings, any other reallocates; pitch is kept unless
    keep='frets' asks for a transposition; what TG would drop refuses."""
    checked = TestPlaceFitCommand.checked

    def fixture(self, low=True):
        song, raw = fixture()
        beats = song['score']['patterns']['A']['beats']
        next(b for b in beats if b['id'] == 't1')['chord'] = dict(name='E', first_fret=0, frets=[0, -1, -1, -1, -1, -1])
        if low:
            beats.append(beat('low', [3, 1], [dict(note('lown', 41, 6, 1), spelling=dict(step='F', alter=0))], 8))
        return song, raw

    def request(self, tuning, **extra):
        return dict(action='retune', track='guitar', tuning=tuning, **extra)

    def positions(self, song):
        return {n['id']: (n['string'], n['fret'], n['pitch']) for p in song['score']['patterns'].values()
                for b in p['beats'] if b['track'] == 'guitar' for n in b['notes']}

    def test_capo_keeps_frets_and_raises_the_sound_as_tuxguitars_offset(self):
        song, raw = self.fixture()
        tuning = song['score']['tracks']['guitar']['tuning']
        candidate, result = self.checked(song, raw, self.request(tuning, capo=2))   # default keep='pitch'
        before, after = self.positions(song), self.positions(candidate)
        self.assertEqual(after, {k: (s, f, p + 2) for k, (s, f, p) in before.items()})
        self.assertEqual(result['moved'], [])
        self.assertEqual(len(result['repitched']), len(before))
        guitar = set(before)
        pitches = lambda s: sorted(e['pitch'] for e in tab.playback_plan(s, raw)['events']
                                   if e['type'] == 'note_on' and e['id'].rsplit('/', 1)[-1] in guitar)
        self.assertEqual(pitches(candidate), [p + 2 for p in pitches(song)])

    def test_uniform_change_keeps_strings_and_pitch_and_transposes_the_diagram(self):
        song, raw = self.fixture()
        candidate, result = self.checked(song, raw, self.request([63, 58, 54, 49, 44, 39]))
        before, after = self.positions(song), self.positions(candidate)
        self.assertEqual(after, {k: (s, f + 1, p) for k, (s, f, p) in before.items()})
        self.assertEqual(sorted(result['moved']), sorted(f'{n}/{k}' for n, p in song['score']['patterns'].items()
                                                        for b in p['beats'] if b['track'] == 'guitar'
                                                        for k in [x['id'] for x in b['notes']]))
        self.assertEqual((result['repitched'], result['chords_transposed']), ([], ['A/t1']))
        self.assertEqual(tab._beat(candidate['score'], 'A', 't1')['chord'],
                         dict(name='', first_fret=0, frets=[1, -1, -1, -1, -1, -1]))
        self.assertEqual(candidate['score']['tracks']['bass'], song['score']['tracks']['bass'])
        self.assertEqual((candidate['patterns'], candidate['score']['ties']), (song['patterns'], song['score']['ties']))

    def test_drop_d_reallocates_to_the_closest_string_and_removes_diagrams(self):
        song, raw = self.fixture()
        candidate, result = self.checked(song, raw, self.request([64, 59, 55, 50, 45, 38]))
        self.assertEqual(self.positions(candidate)['lown'], (6, 3, 41))
        self.assertEqual((result['moved'], result['repitched'], result['chords_removed']), (['A/lown'], [], ['A/t1']))
        self.assertNotIn('chord', tab._beat(candidate['score'], 'A', 't1'))
        self.assertEqual(tab._beat(candidate['score'], 'A', 'low')['notes'][0]['spelling'], dict(step='F', alter=0))

    def test_keep_frets_is_an_explicit_transposition(self):
        song, raw = self.fixture()
        candidate, result = self.checked(song, raw, self.request([64, 59, 55, 50, 45, 38], keep='frets'))
        self.assertEqual(self.positions(candidate)['lown'], (6, 1, 39))
        self.assertEqual((result['moved'], result['repitched'], result['spellings_cleared']), ([], ['A/lown'], ['A/lown']))
        self.assertNotIn('spelling', tab._beat(candidate['score'], 'A', 'low')['notes'][0])
        self.assertEqual(tab._beat(candidate['score'], 'A', 't1')['chord'], tab._beat(song['score'], 'A', 't1')['chord'])

    def test_string_count_changes_take_channels_and_unplaceable_notes_refuse(self):
        song, raw = self.fixture()
        del song['score']['tracks']['bass']
        song['score']['patterns']['A']['beats'] = [b for b in song['score']['patterns']['A']['beats'] if b['track'] != 'bass']
        candidate, result = self.checked(song, raw, self.request([64, 59, 55, 50, 45, 40, 35], channels=list(range(7))))
        self.assertEqual((self.positions(candidate), result['moved'], result['chords_removed']),
                         (self.positions(song), [], ['A/t1']))
        five = self.request([64, 59, 55, 50, 45], channels=list(range(5)))
        self.checked(song, raw, five, 'cannot place 1 note.*A/lown')
        self.checked(song, raw, self.request([64, 59, 55, 50, 45]), 'one module channel per string')
        song, raw = self.fixture(low=False)
        song['score']['patterns']['A']['beats'] = [b for b in song['score']['patterns']['A']['beats'] if b['track'] != 'bass']
        del song['score']['tracks']['bass']
        candidate, _ = self.checked(song, raw, five)
        self.assertEqual(self.positions(candidate), self.positions(song))
        self.assertEqual(candidate['score']['tracks']['guitar']['channels'], list(range(5)))

    def tie_fixture(self, blocked=False):
        song, raw = self.fixture(low=False)
        tail = tab._beat(song['score'], 'A', 'tail')
        tail['notes'] += [note('c1', 67, 2, 8), note('c2', 66, 3, 11)]
        if blocked:
            tab._beat(song['score'], 'B', 'head')['notes'].append(note('hz', 60, 2, 1))
        return song, raw

    def test_a_tie_keeps_one_string_or_refuses(self):
        song, raw = self.tie_fixture()
        candidate, result = self.checked(song, raw, self.request([65, 59, 55, 50, 45, 40]))
        after = self.positions(candidate)
        self.assertEqual([after[k][:2] for k in ('tailn', 'headn', 'c1', 'c2')], [(3, 9), (3, 9), (1, 2), (2, 7)])
        song, raw = self.tie_fixture(blocked=True)
        self.checked(song, raw, self.request([65, 59, 55, 50, 45, 40]), 'tied note B/headn off its string')

    def test_bounds_refusals_and_no_change(self):
        song, raw = self.fixture()
        candidate, result = self.checked(song, raw, self.request([64, 59, 55, 50, 45, 40]))
        self.assertIs(candidate, song)
        self.checked(song, raw, self.request([63, 58, 54, 49, 44, 39], max_fret=3), 'cannot place')
        for request, error in ((dict(self.request([64]), track='nope'), 'existing track'),
                               (self.request([64] * 6, keep='both'), 'keep'),
                               (self.request([64] * 26, channels=list(range(26))), '1..25'),
                               (self.request([64, 59, 55, 50, 45, 40], capo=25), 'capo'),
                               (dict(self.request([64]), extra=1), 'unsupported')):
            with self.subTest(error=error):
                self.checked(song, raw, request, error)
        song['score']['tracks']['bass'] = dict(tuning=[0], channels=[6], instrument=1, midi=dict(program=0, bank=128))
        song['score']['patterns']['A']['beats'] = [b for b in song['score']['patterns']['A']['beats'] if b['track'] != 'bass']
        self.checked(song, raw, dict(self.request([0, 0], channels=[6, 5]), track='bass'), 'drum-map')


class TestTransposeCommand(unittest.TestCase):
    """TGTransposeAction: semitones on a track or all tracks, whole track or one measure, transposeNote fingering."""
    checked = TestPlaceFitCommand.checked
    positions = TestRetuneCommand.positions

    def fixture(self):
        song, raw = TestRetuneCommand().fixture(low=False)
        tab._beat(song['score'], 'A', 'chord')['notes'][0]['spelling'] = dict(step='C', alter=0)
        return song, raw

    def request(self, semitones, **extra):
        return dict(action='transpose', semitones=semitones, track='guitar', **extra)

    def test_track_scope_keeps_strings_moves_pitch_and_diagram(self):
        song, raw = self.fixture()
        candidate, result = self.checked(song, raw, self.request(2))
        before = self.positions(song)
        self.assertEqual(self.positions(candidate), {k: (s, f + 2, p + 2) for k, (s, f, p) in before.items()})
        self.assertEqual((sorted(result['transposed']), result['moved']), (sorted(
            f"{'B' if k == 'headn' else 'A'}/{k}" for k in before), []))
        self.assertEqual(result['spellings_cleared'], ['A/c'])
        self.assertEqual(tab._beat(candidate['score'], 'A', 't1')['chord'], dict(name='', first_fret=0, frets=[2, -1, -1, -1, -1, -1]))
        self.assertEqual(tab._beat(candidate['score'], 'A', 'bass'), tab._beat(song['score'], 'A', 'bass'))
        self.assertEqual((candidate['patterns'], candidate['score']['ties']), (song['patterns'], song['score']['ties']))
        unchanged, _ = self.checked(song, raw, self.request(2, apply_to_chords=False))
        self.assertEqual(tab._beat(unchanged['score'], 'A', 't1')['chord'], tab._beat(song['score'], 'A', 't1')['chord'])

    def test_transpose_note_moves_strings_as_tuxguitar(self):
        song, raw = self.fixture()
        rest = tab._beat(song['score'], 'A', 'rest')
        rest['notes'] = [note('low', 57, 3, 2)]
        rest['notes'].append(note('high', 87, 2, 28))
        candidate, result = self.checked(song, raw, self.request(5, try_keep_strings=False))
        after = self.positions(candidate)
        self.assertEqual((after['low'], after['high']), ((2, 3, 62), (1, 28, 92)))
        candidate, result = self.checked(song, raw, self.request(5))
        after = self.positions(candidate)
        self.assertEqual((after['low'], after['high']), ((3, 7, 62), (1, 28, 92)))
        self.assertEqual(result['moved'], ['A/high'])
        rest['notes'] = [note('top', 92, 1, 28)]
        self.checked(song, raw, self.request(2), 'cannot place 1 note.*A/top')

    def test_measure_scope_all_tracks_shared_uses_and_ties(self):
        song, raw = self.fixture()
        self.checked(song, raw, self.request(1, scope='measure', occurrence='oa', at=[0, 1]), 'cuts the tie')
        song['score']['ties'] = []
        song['orders'].append('A')
        song['score']['order_ids'].append('oc')
        song['score']['tracks']['drums'] = dict(tuning=[0], channels=[5], instrument=1, midi=dict(program=0, bank=128))
        song['score']['tracks']['guitar']['channels'] = [0, 1, 2, 3, 4, 7]
        song['module']['channels'] = 8
        raw = [Pattern(p.name, [[Cell() for _ in range(8)] for _ in range(48)]) for p in raw]
        candidate, result = self.checked(song, raw, self.request(1, scope='measure', occurrence='oc', at=[1, 2],
                                                                all_tracks=True))
        self.assertEqual((result['tracks'], result['occurrences']), (['guitar', 'bass'], ['oa', 'oc']))
        self.assertEqual(tab._beat(candidate['score'], 'A', 'bass')['notes'][0]['pitch'], 41)
        self.assertEqual(candidate['score']['patterns']['B'], song['score']['patterns']['B'])

    def test_refusals_and_no_change(self):
        song, raw = self.fixture()
        candidate, _ = self.checked(song, raw, self.request(0))
        self.assertIs(candidate, song)
        for request, error in ((self.request(13), 'semitones'), (self.request(1, scope='song'), 'scope'),
                               (dict(self.request(1), track='nope'), 'context track'),
                               (self.request(1, all_tracks=1), 'boolean'),
                               (self.request(1, scope='measure', occurrence='zz', at=[0, 1]), 'played occurrence'),
                               (dict(self.request(1), extra=1), 'unsupported')):
            with self.subTest(error=error):
                self.checked(song, raw, request, error)


class TestInsertRestCommand(unittest.TestCase):
    """TGInsertRestBeatAction: moveVoicesPrecise inside the measure, or addSilence where the voice is empty."""
    checked = TestPlaceFitCommand.checked

    def request(self, at, voice=0, written=None):
        return dict(action='insert_rest', occurrence='oa', track='guitar', voice=voice, at=at, rest_id='inserted',
                    written=written or dict(value=4, dots=0, tuplet=[1, 1]))

    def test_moves_later_beats_and_drops_the_trailing_rest(self):
        song, raw = TestPlaceFitCommand().fixture(True)   # a 0, b 1, c 2, rest r 3 (quarters)
        candidate, result = self.checked(song, raw, self.request([1, 1]))
        after = {b['id']: b for b in candidate['score']['patterns']['A']['beats']}
        self.assertEqual({k: after[k]['at'] for k in ('a', 'b', 'c', 'inserted')},
                         {'a': [0, 1], 'b': [2, 1], 'c': [3, 1], 'inserted': [1, 1]})
        self.assertNotIn('r', after)
        self.assertEqual((after['inserted']['notes'], after['inserted']['written']), ([], after['b']['written']))
        self.assertEqual((result['moved'], result['dropped']), (['b', 'c'], ['r']))
        for identity in ('b', 'c'):
            self.assertEqual(after[identity]['notes'], tab._beat(song['score'], 'A', identity)['notes'])

    def test_a_note_that_would_leave_the_measure_refuses(self):
        song, raw = TestPlaceFitCommand().fixture()   # a 0, b 1, rest r 2, c 3: c would move past the bar
        self.checked(song, raw, self.request([1, 1]), 'full measure unchanged')

    def test_an_empty_voice_gets_a_rest_of_the_selected_duration(self):
        song, raw = TestPlaceFitCommand().fixture()
        candidate, _ = self.checked(song, raw, self.request([0, 1], voice=1, written=dict(value=8, dots=0, tuplet=[1, 1])))
        rest = next(b for b in candidate['score']['patterns']['A']['beats'] if b['id'] == 'inserted')
        self.assertEqual((rest['voice'], rest['at'], rest['written']['value'], rest['notes']), (1, [0, 1], 8, []))

    def test_refusals(self):
        song, raw = TestPlaceFitCommand().fixture(True)
        for request, error in ((dict(self.request([1, 1]), track='other'), 'existing track'),
                               (dict(self.request([1, 1]), occurrence='nope'), 'occurrence'),
                               (dict(self.request([1, 1]), extra=1), 'unsupported')):
            with self.subTest(error=error):
                self.checked(song, raw, request, error)


class TestSectionStructure(unittest.TestCase):
    """Whole passages and exact re-barring preserve notes, raw source and occurrence identity."""

    @staticmethod
    def source():
        song, _ = fixture()
        song['orders'] = ['A', 'B', 'C', 'D']
        song['score']['order_ids'] = ['oa', 'ob', 'oc', 'od']
        song['patterns'] = {name: dict(rows=48, data='') for name in song['orders']}
        song['score']['patterns'] = {name: dict(row_step=[1, 12], beats=[
            beat('whole', [0, 1], [dict(note('n', 64, 1, 0), velocity=90)], 1)])
            for name in song['orders']}
        song['score']['measures'] = [dict(id=name, meter=[4, 4], **{
            'from': dict(occurrence=oid, at=[0, 1]), 'to': dict(occurrence=oid, at=[4, 1])})
            for name, oid in zip(song['orders'], song['score']['order_ids'])]
        song['score']['ties'] = [dict(**{'from': dict(occurrence='oa', note='n'),
                                        'to': dict(occurrence='ob', note='n')})]
        return song

    @staticmethod
    def raw(song):
        return [Pattern(name, [[Cell() for _ in range(7)] for _ in range(spec['rows'])])
                for name, spec in song['patterns'].items()]

    def sounding(self, song):
        plan = tab.playback_plan(song, self.raw(song))
        return [(e['type'], e['frame'], e.get('pitch'), e.get('ch')) for e in plan['events']
                if e['type'] in ('note_on', 'note_off')]

    def test_meter_splits_notes_rests_and_existing_tie_chains_without_retiming(self):
        song = self.source()
        song['score']['patterns']['A']['beats'][0]['text'] = 'opening'
        song['score']['patterns']['A']['beats'].append(beat('silence', [0, 1], [], 1, voice=1))
        before, sounding = copy.deepcopy(song), self.sounding(song)
        result = tab.measure_command(song, dict(action='measure_meter', at=0, meter=[3, 4], to_end=True))
        after = result['song']
        self.assertEqual(song, before)
        self.assertEqual(self.sounding(after), sounding)
        self.assertEqual(len(after['orders']), 6)
        self.assertEqual(len(after['score']['ties']), 5)
        self.assertFalse(result['removed_ties'])
        self.assertEqual([b['text'] for p in after['score']['patterns'].values() for b in p['beats'] if 'text' in b],
                         ['opening'])
        self.assertEqual(sum(tab.duration_quarters(b['written']) for p in after['score']['patterns'].values()
                             for b in p['beats'] if not b['notes']), 4)
        self.assertTrue(all(Fraction(*b['at']) + tab.duration_quarters(b['written']) <= 3
                            for p in after['score']['patterns'].values() for b in p['beats']))

    def test_meter_keeps_incoming_tie_from_untouched_prefix(self):
        song = self.source()
        before = self.sounding(song)
        result = tab.measure_command(song, dict(action='measure_meter', at=1, meter=[3, 4], to_end=True))
        self.assertEqual(self.sounding(result['song']), before)
        self.assertEqual(result['song']['score']['patterns']['A'], song['score']['patterns']['A'])
        self.assertEqual(result['song']['score']['ties'][0]['from'], dict(occurrence='oa', note='n'))

    def test_insert_remove_clean_repair_boundary_ties_without_deleting_survivors(self):
        song = self.source()
        for edit, ids in ((dict(action='measure_add', at=1), ['oa', 'occ_1', 'ob', 'oc', 'od']),
                          (dict(action='measure_remove', **{'from': 0, 'to': 0}), ['ob', 'oc', 'od']),
                          (dict(action='measure_clean', track='guitar', **{'from': 0, 'to': 0}),
                           ['oa', 'ob', 'oc', 'od'])):
            with self.subTest(action=edit['action']):
                result = tab.measure_command(song, edit)
                self.assertEqual(result['song']['score']['order_ids'], ids)
                self.assertEqual(result['song']['score']['ties'], [])
                self.assertEqual(len(result['removed_ties']), 1)
                self.assertEqual(result['song']['score']['patterns']['B'], song['score']['patterns']['B'])
                self.assertIn('surviving notes play normally', result['report'])
                self.sounding(result['song'])

    def test_move_passage_preserves_internal_tie_raw_headers_and_origins(self):
        song = self.source()
        song['patterns']['A']['data'] = 'raw tracker source retained verbatim'
        song['score']['measures'][0]['marker'] = dict(title='Theme')
        before = copy.deepcopy(song)
        moved = tab.measure_command(song, dict(action='measure_move', **{'from': 0, 'to': 1}, at=4))
        self.assertEqual(moved['orders'], ['C', 'D', 'A', 'B'])
        self.assertEqual(moved['origins'], [2, 3, 0, 1])
        self.assertEqual(moved['song']['patterns'], song['patterns'])
        self.assertEqual(moved['song']['score']['ties'], song['score']['ties'])
        self.assertEqual(moved['song']['score']['measures'][2]['marker'], dict(title='Theme'))
        self.assertFalse(moved['removed_ties'])
        restored = tab.measure_command(moved['song'], dict(action='measure_move', **{'from': 2, 'to': 3}, at=0))
        self.assertEqual(restored['song'], song)
        self.assertEqual(song, before)

    def test_move_tail_removes_only_boundary_tie_and_inside_destination_is_noop(self):
        song = self.source()
        moved = tab.measure_command(song, dict(action='measure_move', **{'from': 1, 'to': 1}, at=4))
        self.assertEqual(moved['orders'], ['A', 'C', 'D', 'B'])
        self.assertEqual(len(moved['removed_ties']), 1)
        self.assertEqual(moved['song']['score']['patterns'], song['score']['patterns'])
        for at in (0, 1, 2):
            unchanged = tab.measure_command(song, dict(action='measure_move', **{'from': 0, 'to': 1}, at=at))
            self.assertEqual(unchanged['song'], song)

    def test_rebar_refuses_technique_grid_raw_and_shared_ambiguity_atomically(self):
        cases = []
        technique = self.source()
        technique['score']['patterns']['A']['beats'][0]['notes'][0]['slide'] = True
        cases.append((technique, dict(meter=[3, 4]), {}, 'splitting a technique'))
        shared = self.source()
        shared['orders'][3] = 'A'
        cases.append((shared, dict(meter=[3, 4]), {}, 'more than one order'))
        cases.append((self.source(), dict(meter=[1, 64]), {}, 'whole number of rows'))
        cases.append((self.source(), dict(meter=[3, 4]), dict(A=0), 'tracker commands'))
        for song, extra, raw_last, reason in cases:
            before = copy.deepcopy(song)
            with self.subTest(reason=reason), self.assertRaisesRegex(ValueError, reason):
                tab.measure_command(song, dict(action='measure_meter', at=0, **extra), raw_last)
            self.assertEqual(song, before)

    def test_move_beats_extends_and_splits_with_exact_shift_and_untouched_other_track(self):
        song = self.source()
        song['score']['ties'] = [dict(**{'from': dict(occurrence='ob', note='n'),
                                        'to': dict(occurrence='oc', note='n')})]
        song['score']['patterns']['A']['beats'] = [
            beat('head', [0, 1], [dict(note('headn', 65, 1, 1), velocity=90)]),
            beat('long', [2, 1], [dict(note('longn', 67, 1, 3), velocity=90)], 2),
            beat('bass', [0, 1], [dict(note('bassn', 40, 1, 0), velocity=80)], 1, track='bass')]
        before, sounding = copy.deepcopy(song), self.sounding(song)
        after, result = tab.score_command(song, self.raw(song), dict(action='move_beats', occurrence='oa',
            track='guitar', voice=0, at=[0, 1], direction='right'))
        expected = [(kind, frame + (0 if pitch == 40 else 22050), pitch, channel)
                    for kind, frame, pitch, channel in sounding]
        self.assertEqual(sorted(self.sounding(after)), sorted(expected))
        self.assertEqual(len(after['orders']), 5)
        self.assertEqual(result['moved'], 5)
        self.assertFalse(result['removed_ties'])
        self.assertEqual(next(b for b in after['score']['patterns']['A']['beats'] if b['track'] == 'bass'),
                         song['score']['patterns']['A']['beats'][-1])
        self.assertEqual(len(after['score']['ties']), 5)
        self.assertEqual(song, before)

    def test_move_beats_left_removes_incident_tie_but_keeps_surviving_tail(self):
        song = self.source()
        after, result = tab.score_command(song, self.raw(song), dict(action='move_beats', occurrence='oa',
            track='guitar', voice=0, at=[0, 1], direction='left'))
        self.assertEqual(result['removed'], ['whole'])
        self.assertEqual(len(result['removed_ties']), 1)
        self.assertEqual(len(self.sounding(after)), 6)
        self.assertEqual(after['score']['patterns']['A']['beats'][0]['notes'][0]['pitch'], 64)

    def test_move_beats_raw_collision_refuses_without_mutating_source(self):
        song = self.source()
        song['score']['patterns']['A']['beats'][0]['written']['value'] = 4
        song['score']['ties'] = []
        raw = self.raw(song)
        raw[0].rows[12][0] = Cell(note=70, instrument=1)
        self.assertFalse(tab.authoring_view(song, raw)['conflicts'])
        before = copy.deepcopy(song)
        with self.assertRaisesRegex(ValueError, 'raw|residual|overlap|ownership|conflict'):
            tab.score_command(song, raw, dict(action='move_beats', occurrence='oa', track='guitar',
                                            voice=0, at=[0, 1], direction='right'))
        self.assertEqual(song, before)


class TestCompleteSongStructure(unittest.TestCase):
    source = staticmethod(TestSectionStructure.source)
    raw = staticmethod(TestSectionStructure.raw)

    def test_unique_preserves_occurrences_ties_raw_and_unselected_pattern(self):
        song = self.source()
        song['orders'][2] = 'A'
        song['patterns']['A']['data'] = 'owner raw data'
        before = copy.deepcopy(song)
        result = tab.measure_command(song, dict(action='measure_unique', **{'from': 2, 'to': 2}))
        after, name = result['song'], result['orders'][2]
        self.assertNotEqual(name, 'A')
        self.assertEqual(after['score']['order_ids'], song['score']['order_ids'])
        self.assertEqual(after['score']['ties'], song['score']['ties'])
        self.assertEqual(result['origins'], [0, 1, 2, 3])
        self.assertEqual(after['patterns'][name], song['patterns']['A'])
        self.assertEqual(after['score']['patterns'][name], song['score']['patterns']['A'])
        self.assertEqual(result['created'][name]['clone'], 'A')
        self.assertEqual(song, before)
        again = tab.measure_command(after, dict(action='measure_unique', **{'from': 2, 'to': 2}))
        self.assertEqual(again['song'], after)
        self.assertFalse(again['created'])

    def test_custom_move_exact_third_and_invalid_amount_atomic(self):
        song = self.source()
        song['score']['ties'] = []
        before = copy.deepcopy(song)
        original = tab.playback_plan(song, self.raw(song))['events']
        after, report = tab.score_command(song, self.raw(song), dict(action='move_beats', occurrence='oa',
            track='guitar', voice=0, at=[0, 1], direction='right', amount=[1, 3]))
        moved = tab.playback_plan(after, self.raw(after))['events']
        events = lambda values: sorted((e['type'], e['frame'], e.get('pitch')) for e in values
                                       if e['type'] in ('note_on', 'note_off'))
        self.assertEqual(events(moved), sorted((kind, frame + 7350, pitch) for kind, frame, pitch in events(original)))
        self.assertEqual(len(after['orders']), 5)
        self.assertEqual(song, before)
        for amount in ([0, 1], [1, 0], [1, 7], [257, 1]):
            with self.subTest(amount=amount), self.assertRaises(ValueError):
                tab.score_command(song, self.raw(song), dict(action='move_beats', occurrence='oa',
                    track='guitar', at=[0, 1], direction='right', amount=amount))
            self.assertEqual(song, before)

    def test_portable_copy_is_detached_tracks_headers_and_internal_ties_only(self):
        song = self.source()
        song['score']['measures'][0].update(marker=dict(title='Theme', color='#123456'), line_break=True,
            staff=dict(guitar=dict(clef='treble'), bass=dict(clef='bass')))
        clip = tab.measure_segment(song, 0, 1, 'guitar', True)
        self.assertEqual(clip['ties'], [dict(**{'from': dict(unit=0, note='n'), 'to': dict(unit=1, note='n')})])
        self.assertEqual(clip['units'][0]['measure']['staff'], dict(guitar=dict(clef='treble')))
        self.assertEqual(clip['units'][0]['measure']['marker']['title'], 'Theme')
        self.assertNotIn('pattern', clip['units'][0])
        self.assertNotIn('marker', tab.measure_segment(song, 0, 0)['units'][0]['measure'])
        song['score']['patterns']['A']['beats'][0]['notes'][0]['pitch'] = 70
        self.assertEqual(clip['units'][0]['beats'][0]['notes'][0]['pitch'], 64)

    def test_cross_song_measure_paste_maps_tracks_ties_and_destination_routing(self):
        source = self.source()
        for p in source['score']['patterns'].values():
            p['beats'][0]['notes'][0].update(channel=0, instrument=1)
        clip = tab.measure_segment(source, 0, 1, 'guitar', True)
        song = self.source()
        song['score']['tracks']['lead'] = song['score']['tracks'].pop('guitar')
        song['score']['tracks']['lead']['tuning'] = [62, 57, 53, 48, 43, 38]
        for p in song['score']['patterns'].values():
            p['beats'][0]['track'] = 'lead'
            p['beats'][0]['notes'][0]['fret'] = 2
        before = copy.deepcopy(song)
        plan = tab.measure_command(song, dict(action='measure_paste', at=2, mode='replace', segment=clip, track='lead'))
        after = plan['song']
        self.assertEqual(song, before)
        self.assertEqual(len(after['score']['ties']), 2)
        for name in after['orders'][2:]:
            b = after['score']['patterns'][name]['beats'][0]
            n = b['notes'][0]
            self.assertEqual(b['track'], 'lead')
            self.assertEqual(n['pitch'], 64)
            self.assertEqual(n['fret'], 2)
            self.assertNotIn('channel', n)
            self.assertNotIn('instrument', n)
        tab.validate_score(after)
        self.assertFalse(tab.authoring_view(after, self.raw(after))['conflicts'])

    def test_header_marker_options_and_staff_mapping_are_explicit(self):
        source = self.source()
        source['score']['measures'][0].update(marker=dict(title='Theme'), repeat_open=True, line_break=True,
                                             staff=dict(guitar=dict(clef='alto')))
        clip = tab.measure_segment(source, 0, 0, copy_markers=True)
        song = self.source()
        song['score']['measures'][2].update(marker=dict(title='Old'), repeat_close=1)
        plain = tab.measure_command(song, dict(action='measure_paste', at=2, mode='replace', segment=clip))['song']
        self.assertEqual(plain['score']['measures'][2], song['score']['measures'][2])
        selected = tab.measure_command(song, dict(action='measure_paste', at=2, mode='replace', segment=clip,
                                                  copy_headers=True, copy_markers=True))['song']
        header = selected['score']['measures'][2]
        self.assertEqual(header['marker'], dict(title='Theme'))
        self.assertEqual(header['staff'], dict(guitar=dict(clef='alto')))
        self.assertTrue(header['repeat_open'])
        self.assertTrue(header['line_break'])
        self.assertNotIn('repeat_close', header)
        markers = tab.measure_command(song, dict(action='measure_paste', at=2, mode='replace', segment=clip,
                                                 copy_markers=True))['song']['score']['measures'][2]
        self.assertEqual(markers['marker'], dict(title='Theme'))
        self.assertEqual(markers['repeat_close'], 1)
        self.assertNotIn('repeat_open', markers)

    def test_header_replace_resizes_all_tracks_and_refuses_partial_raw_shared(self):
        source = self.source()
        source['score']['ties'] = []
        source['patterns']['A']['rows'] = 36
        source['score']['patterns']['A']['beats'][0]['written'] = dict(value=2, dots=1, tuplet=[1, 1])
        source['score']['measures'][0].update(meter=[3, 4])
        source['score']['measures'][0]['to']['at'] = [3, 1]
        clip = tab.measure_segment(source, 0, 0)
        song = self.source()
        plan = tab.measure_command(song, dict(action='measure_paste', at=2, mode='replace', segment=clip,
                                             copy_headers=True))
        self.assertEqual(plan['resized'], dict(C=36))
        self.assertEqual(plan['song']['score']['measures'][2]['meter'], [3, 4])
        self.assertEqual(plan['song']['score']['measures'][2]['to']['at'], [3, 1])
        tab.validate_score(plan['song'])
        before = copy.deepcopy(song)
        with self.assertRaisesRegex(ValueError, 'tracker commands'):
            tab.measure_command(song, dict(action='measure_paste', at=2, mode='replace', segment=clip,
                                           copy_headers=True), dict(C=0))
        with self.assertRaisesRegex(ValueError, 'every destination track'):
            tab.measure_command(song, dict(action='measure_paste', at=2, mode='replace',
                segment=tab.measure_segment(source, 0, 0, 'guitar'), track='guitar', copy_headers=True))
        self.assertEqual(song, before)

    def test_portable_insert_never_clones_unrelated_same_named_raw_pattern(self):
        source = self.source()
        clip = tab.measure_segment(source, 0, 1)
        song = self.source()
        song['patterns']['A']['data'] = 'unrelated raw owner material'
        result = tab.measure_command(song, dict(action='measure_paste', at=2, mode='insert', segment=clip))
        self.assertTrue(all(spec['clone'] is None for spec in result['created'].values()))
        self.assertEqual(result['song']['patterns']['A'], song['patterns']['A'])
        self.assertEqual(len(result['song']['orders']), 6)
        tab.validate_score(result['song'])


class TestTablature(unittest.TestCase):
    def test_text_and_stem_edits_do_not_materialize_implicit_fingering(self):
        song, raw = plan_fixture()
        original = song['score']['patterns']['A']['beats'][0]
        for n in original['notes']:
            n.pop('string')
            n.pop('fret')
        notes_before = json.dumps(original['notes'])
        plan_before = tab.playback_plan(song, raw)
        changed = copy.deepcopy(original)
        changed.update(text='A new annotation', stem='down')
        candidate = tab.apply_score_edit(song, dict(op='beat_set', pattern='A', beat=changed))
        self.assertEqual(json.dumps(candidate['score']['patterns']['A']['beats'][0]['notes']), notes_before)
        self.assertEqual(tab.playback_plan(candidate, raw)['events'], plan_before['events'])
        # A pitch change still repairs genuinely changed note geometry.
        changed['notes'][0]['pitch'] = 62
        pitched = tab.apply_score_edit(song, dict(op='beat_set', pattern='A', beat=changed))
        self.assertIn('string', pitched['score']['patterns']['A']['beats'][0]['notes'][0])
        # Track tuning changes still repair existing explicit assignments.
        track = copy.deepcopy(song['score']['tracks']['guitar'])
        track['tuning'] = [63, 58, 54, 49, 44, 39]
        tuned = tab.apply_score_edit(song, dict(op='track_set', track='guitar', value=track))
        self.assertTrue(all(n.get('string') is not None for n in tuned['score']['patterns']['A']['beats'][0]['notes']))

    def test_anchored_text_and_markers_preserve_playback_clipboard_and_structure(self):
        song, raw = plan_fixture()
        before = tab.playback_plan(song, raw, 48000)
        source = copy.deepcopy(song)
        chord = copy.deepcopy(song['score']['patterns']['A']['beats'][0])
        chord['text'] = 'Verse <one> & cafÃ©\nFingerstyle'
        song = tab.apply_score_edit(song, dict(op='beat_set', pattern='A', beat=chord))
        marker = dict(title='Chorus Î©', color='#123abc')
        song = tab.apply_score_edit(song, dict(op='measure_set', measure=dict(
            id='m1', meter=[4, 4], marker=marker, **{
                'from': dict(occurrence='oa', at=[0, 1]), 'to': dict(occurrence='oa', at=[4, 1])})))
        self.assertEqual(tab.playback_plan(song, raw, 48000), before)
        clipboard = tab.capture_score_clipboard(song, 'A', ['chord'], 'oa')
        pasted = tab.paste_score_clipboard(song, tab.project_score(song, raw), 1, 12, clipboard)
        self.assertEqual(pasted['score']['patterns']['B']['beats'][-1]['text'], chord['text'])
        reopened = yaml.safe_load(yaml.safe_dump(pasted, allow_unicode=True))
        self.assertEqual(reopened, pasted)
        self.assertEqual(reopened['score']['measures'][0]['marker'], marker)
        self.assertNotIn('text', source['score']['patterns']['A']['beats'][0])
        for invalid in (None, 12, 'x' * 4097):
            with self.subTest(text=type(invalid).__name__), self.assertRaisesRegex(ValueError, 'text must'):
                tab.apply_score_edit(song, dict(op='beat_set', pattern='A', beat={**chord, 'text': invalid}))
        for invalid in ({'title': ''}, {'title': 'A', 'color': 'red'}, {'title': 'A', 'extra': True}):
            with self.subTest(marker=invalid), self.assertRaises(ValueError):
                tab.apply_score_edit(song, dict(op='measure_set', measure={**song['score']['measures'][0], 'marker': invalid}))

    def test_midi_velocity_is_authored_separately_from_tracker_volume(self):
        song, raw = plan_fixture()
        original = copy.deepcopy(song)
        for value in (0, 1, 15, 95, 127):
            candidate = tab.apply_score_edit(song, dict(op='note_set', pattern='A', beat='chord',
                                                       note=dict(id='e', velocity=value)))
            attack = next(e for e in tab.playback_plan(candidate, raw, 48000)['events']
                          if e['type'] == 'note_on' and e['id'] == 'oa/e')
            self.assertEqual(attack['velocity'], value)
            self.assertIsNone(attack['volume'])
            clip = tab.capture_score_clipboard(candidate, 'A', ['chord'], 'oa')
            self.assertEqual(next(n for n in clip['beats'][0]['notes'] if n['pitch'] == 64)['velocity'], value)
            # The standalone IT: the attack's volume column carries round(64 * velocity / 127), half up.
            projected = tab.project_score(candidate, raw)
            rec = next(r for r in projected.positions if r.get('note') == 'e' and r['kind'] == 'note')
            self.assertEqual(projected.patterns[rec['pattern']].rows[rec['row']][rec['ch']].volcmd, (64 * value * 2 + 127) // 254)
        cleared = tab.apply_score_edit(candidate, dict(op='note_set', pattern='A', beat='chord',
                                                       note=dict(id='e', velocity=None)))
        self.assertNotIn('velocity', cleared['score']['patterns']['A']['beats'][0]['notes'][1])
        for value in (-1, 128, True, 95.0):
            with self.subTest(value=value), self.assertRaises(ValueError):
                tab.apply_score_edit(song, dict(op='note_set', pattern='A', beat='chord', note=dict(id='e', velocity=value)))
        self.assertEqual(song, original)

    def test_slide_source_steps_and_owned_release_tail(self):
        self.assertEqual(list(tab._slide_controls(960, 2)),
                         [(120, 65), (240, 66), (360, 68), (480, 69), (600, 70),
                          (720, 72), (840, 73), (960, 75), (960, 64)])
        self.assertEqual(list(tab._slide_controls(1001, 2))[-2:], [(1000, 74), (1001, 64)])
        self.assertEqual(list(tab._slide_controls(119, -2)), [(119, 64)])
        self.assertEqual(list(tab._slide_controls(960, -2))[-2:], [(960, 53), (960, 64)])
        song, raw = plan_fixture()
        song['score']['ties'] = []
        song['score']['patterns']['A']['beats'] = [
            beat('a', [0, 1], [dict(note('n', 64, 1, 0), slide=True, staccato=True, vibrato=True)]),
            beat('b', [1, 1], [note('m', 66, 1, 2)])]
        song['score']['patterns']['B']['beats'] = []
        plan = tab.playback_plan(song, raw, 48000)
        old = [e for e in plan['events'] if e['id'] == 'oa/n']
        self.assertEqual(next(e['at'] for e in old if e['type'] == 'note_off'), [1, 2])
        self.assertEqual([(e['at'], e['bend_value']) for e in old if e['type'] == 'pitch'][-2:],
                         [([1, 1], 75), ([1, 1], 64)])
        self.assertEqual([e['type'] for e in plan['events'] if e['frame'] == 24000],
                         ['note_on', 'pitch', 'pitch'])
        # An explicit rest or another-string chord interrupts lookup; vibrato
        # remains suppressed because slide selected the parser branch.
        for notes in ([], [note('block', 59, 2, 0)]):
            candidate = copy.deepcopy(song)
            candidate['score']['patterns']['A']['beats'].insert(1, beat('block', [1, 2], notes, value=8, voice=0))
            candidate['score']['patterns']['A']['beats'][0]['written'] = {'value': 8}
            self.assertFalse(any(e['type'] == 'pitch' for e in tab.playback_plan(candidate, raw, 48000)['events']))
        after = tab.apply_score_edit(song, dict(op='note_set', pattern='A', beat='a',
                                              note=dict(id='n', bend={'points': [{'position': 6, 'value': 4}]})))
        self.assertNotIn('slide', after['score']['patterns']['A']['beats'][0]['notes'][0])

    def test_pitch_source_vectors_and_exact_plan_reclock(self):
        from vulturetracker.export import _plan_at_rate
        curve = {'points': [{'position': p, 'value': v} for p, v in ((0, 0), (6, 4), (12, 0))]}
        expected = [(0, 64), *[(43*i, 64+i) for i in range(1, 12)],
                    (480, 75), *[(480+43*i, 75-i) for i in range(1, 12)], (960, 64), (960, 64)]
        self.assertEqual(list(tab._pitch_controls({'bend': curve, 'vibrato': True}, 960)), expected)
        self.assertEqual(list(tab._pitch_controls({'vibrato': True}, 500)),
                         [(160, 64), (320, 65), (480, 64), (500, 65), (500, 64)])
        self.assertEqual(list(tab._pitch_controls({'vibrato': True}, 100)), [(100, 64), (100, 65), (100, 64)])
        self.assertEqual(list(tab._pitch_controls({'tremolo_bar': {'points': [
            {'position': 0, 'value': -12}, {'position': 12, 'value': 12}]}}, 960))[-2:],
                         [(960, 127), (960, 64)])
        song, raw = plan_fixture()
        song['score']['patterns']['A']['beats'][0]['notes'][1]['bend'] = curve
        before = copy.deepcopy(song)
        plan = tab.playback_plan(song, raw, 48000)
        controls = [e for e in plan['events'] if e['id'] == 'oa/e' and e['type'] == 'pitch']
        self.assertEqual([(Fraction(*e['at'])*960, e['bend_value']) for e in controls], expected)
        self.assertEqual(controls[11]['semitones'], 33/16)
        self.assertEqual(song, before)
        reclocked = _plan_at_rate(plan, 44100)
        first = [e['type'] for e in reclocked['events'] if e['id'] == 'oa/e' and e['frame'] == 0]
        self.assertEqual(first, ['note_on', 'pitch'])
        self.assertEqual([e['at'] for e in reclocked['events']], [e['at'] for e in plan['events']])
        self.assertEqual([p['end'] for p in plan['positions']], [p['end'] for p in reclocked['positions']])

    def test_pitch_gate_duration_head_precedence_and_validation(self):
        song, raw = plan_fixture()
        song['score']['patterns']['A']['beats'][0]['notes'][1].update(vibrato=True, staccato=True)
        events = tab.playback_plan(song, raw, 48000)['events']
        controls = [e for e in events if e['id'] == 'oa/e' and e['type'] == 'pitch']
        self.assertEqual(controls[-1]['at'], [1, 2])
        self.assertEqual(controls[-1]['semitones'], 0)
        tail = next(b for b in song['score']['patterns']['A']['beats'] if b['id'] == 'tail')
        song['score']['patterns']['B']['beats'][0]['notes'][0]['vibrato'] = True
        self.assertFalse(any(e['type'] == 'pitch' and e['id'] == 'oa/tailn'
                             for e in tab.playback_plan(song, raw, 48000)['events']))
        tail['notes'][0]['vibrato'] = True
        self.assertEqual([e for e in tab.playback_plan(song, raw, 48000)['events']
                          if e['type'] == 'pitch' and e['id'] == 'oa/tailn'][-1]['at'], [9, 2])
        for curve in (True, [], {'points': [{'position': 13, 'value': 0}]},
                      {'points': [{'position': 1, 'value': 0}, {'position': 0, 'value': 0}]}):
            with self.subTest(curve=curve), self.assertRaises(ValueError):
                tab.apply_score_edit(song, dict(op='note_set', pattern='A', beat='chord', note=dict(id='e', bend=curve)))
        after = tab.apply_score_edit(song, dict(op='note_set', pattern='A', beat='chord',
                                              note=dict(id='e', bend={'points': [{'position': 6, 'value': 4}]})))
        after = tab.apply_score_edit(after, dict(op='note_set', pattern='A', beat='chord', note=dict(id='e', dead=True)))
        self.assertNotIn('bend', after['score']['patterns']['A']['beats'][0]['notes'][1])

    def test_command_repeat_splits_destination_rest_with_unique_ids(self):
        song, raw = plan_fixture()
        song['score']['ties'] = []
        song['score']['patterns']['A']['beats'] = [beat('a', [0, 1], [note('n', 64)]),
            beat('next', [1, 1], [note('nextn', 64)]), beat('longrest', [1, 2], [], value=2, voice=1)]
        before = copy.deepcopy(song)
        after, _ = tab.score_command(song, raw, dict(action='repeat', occurrence='oa', track='guitar', voice=0, beats=['a']))
        rests = [b for b in after['score']['patterns']['A']['beats'] if b['voice'] == 1]
        self.assertEqual([(b['at'], tab.duration_quarters(b['written'])) for b in rests],
                         [([1, 2], Fraction(1, 2)), ([2, 1], Fraction(1, 2))])
        self.assertEqual(len({b['id'] for b in rests}), 2)
        self.assertEqual(song, before)

    def test_technique_gates_preserve_written_time_and_source_tick_truncation(self):
        song, raw = plan_fixture()
        first = song['score']['patterns']['A']['beats'][0]
        first['notes'] = [first['notes'][1]]
        first['written'] = {'value': 64, 'dots': 0, 'tuplet': [7, 4]}
        first['notes'][0]['staccato'] = True
        before = copy.deepcopy(song)
        plan = tab.playback_plan(song, raw, 48000)
        events = [e for e in plan['events'] if e['id'] == 'oa/e']
        self.assertEqual([(e['type'], e['frame']) for e in events], [('note_on', 0), ('note_off', 425)])
        self.assertEqual(events[1]['at'], [17, 960])
        self.assertIsNone(events[0]['volume'])
        position = next(p for p in plan['positions'] if p['id'] == 'oa/e')
        self.assertEqual(position['end'], [1, 28])
        self.assertEqual(position['sounding_end'], [17, 960])
        self.assertEqual(song, before)
        with self.assertRaisesRegex(ValueError, 'not representable on row_step'):
            tab.project_score(song, raw)
        for tempo, dead, palm in ((60, 30, 60), (120, 60, 120), (137, 68, 137), (240, 120, 240)):
            for flag, ticks in (('dead', dead), ('palm_mute', palm)):
                with self.subTest(tempo=tempo, effect=flag):
                    candidate = copy.deepcopy(song)
                    candidate['module']['tempo'] = tempo
                    b = candidate['score']['patterns']['A']['beats'][0]
                    b['written'] = {'value': 4}
                    b['notes'][0].update(dead=flag == 'dead', palm_mute=flag == 'palm_mute')
                    events = tab.playback_plan(candidate, raw, 48000)['events']
                    release = next(e for e in events if e['id'] == 'oa/e' and e['type'] == 'note_off')
                    self.assertEqual(Fraction(*release['at']), Fraction(ticks, 960))

    def test_technique_head_controls_tie_and_pattern_release_binding(self):
        song, raw = plan_fixture()
        tail = next(b for b in song['score']['patterns']['A']['beats'] if b['id'] == 'tail')
        continuation = song['score']['patterns']['B']['beats'][0]
        continuation['notes'][0]['staccato'] = True
        plan = tab.playback_plan(song, raw, 48000)
        release = next(e for e in plan['events'] if e['id'] == 'oa/tailn' and e['type'] == 'note_off')
        self.assertEqual(release['at'], [9, 2])
        tail['notes'][0]['staccato'] = True
        plan = tab.playback_plan(song, raw, 48000)
        events = [e for e in plan['events'] if e['id'] == 'oa/tailn']
        self.assertEqual([(e['type'], e['at']) for e in events], [('note_on', [7, 2]), ('note_off', [4, 1])])
        view = tab.authoring_view(song, raw)
        positions = [p for p in view['positions'] if p.get('attack_id') == 'oa/tailn']
        self.assertEqual([p['end'] for p in positions], [[4, 1], [9, 2]])
        self.assertTrue(all(p['sounding_end'] == [4, 1] for p in positions))
        pattern = tab.pattern_authoring_view(song, raw, 1, 'ob', view=view)
        self.assertEqual([(b['row'], b['note']) for b in pattern['bindings'] if b['role'] == 'release'], [(0, 'tailn')])
        self.assertEqual(parse_cell(pattern['display_rows'][0][0]).note, NOTE_OFF)
        with self.assertRaisesRegex(ValueError, 'generated release'):
            tab.translate_native_pattern_edits(song, raw, [(1, [{'row': 0, 'ch': 0, 'cell': '... .. ... ...'}])],
                                               occurrences={1: 'ob'})

    def test_technique_note_edit_exclusion_and_boolean_validation(self):
        song, raw = plan_fixture()
        original = copy.deepcopy(song)
        edit = dict(op='note_set', pattern='A', beat='chord', note=dict(id='e', staccato=True))
        song = tab.apply_score_edit(song, edit)
        edit['note'] = dict(id='e', palm_mute=True)
        song = tab.apply_score_edit(song, edit)
        n = next(n for n in song['score']['patterns']['A']['beats'][0]['notes'] if n['id'] == 'e')
        self.assertTrue(n['palm_mute'])
        self.assertNotIn('staccato', n)
        self.assertEqual({k: v for k, v in n.items() if k != 'palm_mute'}, original['score']['patterns']['A']['beats'][0]['notes'][1])
        for value in (1, 'true', None):
            edit['note'] = dict(id='e', dead=value)
            with self.assertRaisesRegex(ValueError, 'must be boolean'):
                tab.apply_score_edit(song, edit)

    def test_technique_tie_accounts_for_rounded_beat_start_gaps(self):
        song, raw = plan_fixture()
        song['score']['patterns']['A']['beats'] = [
            beat(f'b{i}', [i, 28], [dict(id=f'n{i}', pitch=64, string=1, fret=0,
                                         staccato=i == 0)], value=64, tuplet=[7, 4]) for i in range(8)]
        song['score']['patterns']['B']['beats'] = []
        song['score']['ties'] = [{'from': dict(occurrence='oa', note=f'n{i}'),
                                 'to': dict(occurrence='oa', note=f'n{i+1}')} for i in range(7)]
        plan = tab.playback_plan(song, raw, 48000)
        # Last start=240 ticks, last duration=34: D274 / 2 =137.
        # Summing eight independently truncated 34-tick notes would give136.
        self.assertEqual([(e['type'], e['frame']) for e in plan['events']],
                         [('note_on', 0), ('note_off', 3425)])
        self.assertEqual(plan['events'][1]['at'], [137, 960])

    def test_command_cut_note_keeps_chord_and_written_duration(self):
        song, raw = fixture()
        before = copy.deepcopy(song)
        after, result = tab.score_command(song, raw, dict(action='cut', occurrence='oa', track='guitar',
                                                        voice=0, beats=['chord'], notes=['c']))
        chord = next(b for b in after['score']['patterns']['A']['beats'] if b['id'] == 'chord')
        self.assertEqual([n['id'] for n in chord['notes']], ['e', 'g'])
        self.assertEqual(chord['written'], song['score']['patterns']['A']['beats'][0]['written'])
        self.assertEqual(len(result['clipboard']['beats'][0]['notes']), 3)
        self.assertEqual(song, before)
        after, _ = tab.score_command(after, raw, dict(action='cut', occurrence='oa', track='guitar',
                                                     voice=0, beats=['chord']))
        self.assertEqual(next(b for b in after['score']['patterns']['A']['beats'] if b['id'] == 'chord')['notes'], [])

    def test_command_cut_rest_moves_same_voice_only_inside_authored_measure(self):
        song, raw = fixture()
        song['score']['ties'] = []
        song['score']['patterns']['A']['beats'] = [
            beat('rest', [0, 1], []),
            beat('move', [1, 1], [note('n', 64)]),
            beat('other-voice', [1, 1], [note('v', 59, 2, 0)], voice=1),
            beat('stay', [2, 1], [note('s', 64)])]
        song['score']['measures'] = [
            dict(id='m', meter=[2, 4], **{'from': dict(occurrence='oa', at=[0, 1]),
                                         'to': dict(occurrence='oa', at=[2, 1])})]
        after, _ = tab.score_command(song, raw, dict(action='cut', occurrence='oa', track='guitar',
                                                    voice=0, beats=['rest'], notes=[]))
        self.assertEqual({b['id']: b['at'] for b in after['score']['patterns']['A']['beats']},
                         {'move': [0, 1], 'rest_rest': [1, 1], 'other-voice': [1, 1], 'stay': [2, 1]})
        self.assertEqual(tab._beat(after['score'], 'A', 'rest_rest')['notes'], [])

    def test_command_cut_current_voice_vs_explicit_note_range(self):
        song, raw = fixture()
        song['score']['ties'] = []
        song['score']['patterns']['A']['beats'] = [
            beat('a', [0, 1], [note('n', 64, 1, 0)]),
            beat('v', [0, 1], [note('v', 59, 2, 0)], voice=1)]
        request = dict(action='cut', occurrence='oa', track='guitar', voice=0, beats=['a', 'v'])
        after, _ = tab.score_command(song, raw, request)
        self.assertEqual([b['notes'] for b in after['score']['patterns']['A']['beats']],
                         [[], song['score']['patterns']['A']['beats'][1]['notes']])
        after, _ = tab.score_command(song, raw, dict(request, notes=['n', 'v']))
        self.assertTrue(all(not b['notes'] for b in after['score']['patterns']['A']['beats']))

    def test_command_repeat_replaces_contiguous_beats_both_voices_and_fresh_ids(self):
        song, raw = fixture()
        song['score']['ties'] = []
        song['score']['patterns']['A']['beats'] = [
            beat('a', [0, 1], [note('n', 64)]),
            beat('b', [1, 1], [note('o', 66)]),
            beat('v', [1, 1], [note('v', 59, 2, 0)], voice=1),
            beat('erase', [2, 1], [note('x', 67)], value=2)]
        after, result = tab.score_command(song, raw, dict(action='repeat', occurrence='oa', track='guitar',
                                                        voice=0, beats=['a', 'b']))
        values = after['score']['patterns']['A']['beats']
        self.assertNotIn('erase', [b['id'] for b in values])
        copied = [b for b in values if b['id'] in result['selection']['beats']]
        self.assertEqual([(b['at'], b['voice'], b['notes'][0]['pitch']) for b in copied],
                         [([2, 1], 0, 64), ([3, 1], 0, 66), ([3, 1], 1, 59)])
        self.assertTrue(all(b['id'].startswith('copy_') for b in copied))
        self.assertEqual(result['selection']['at'], [2, 1])

    def test_command_repeat_overflow_splits_exactly_with_ties_and_appends_measure(self):
        song, raw = fixture()
        song['orders'] = ['A']
        song['score']['order_ids'] = ['oa']
        song['score']['ties'] = []
        song['score']['patterns']['A']['beats'] = [
            beat('a', [5, 2], [note('n', 64)]),
            beat('rest', [7, 2], [], value=8)]
        song['score']['patterns']['A']['beats'][0]['text'] = 'Once at the attack'
        song['score']['measures'] = [dict(id='m', meter=[4, 4], **{
            'from': dict(occurrence='oa', at=[0, 1]), 'to': dict(occurrence='oa', at=[4, 1])})]
        after, result = tab.score_command(song, raw, dict(action='repeat', occurrence='oa', track='guitar',
                                                        voice=0, beats=['a']))
        self.assertEqual(len(after['orders']), 2)
        new_name = after['orders'][-1]
        self.assertEqual(after['score']['patterns'][new_name]['beats'][0]['at'], [0, 1])
        self.assertEqual(len(after['score']['ties']), 1)
        self.assertEqual(result['selection']['at'], [7, 2])
        self.assertEqual(after['score']['measures'][-1]['meter'], [4, 4])
        self.assertEqual(sum(b.get('text') == 'Once at the attack'
                             for p in after['score']['patterns'].values() for b in p['beats']), 2)
        self.assertNotIn('text', after['score']['patterns'][new_name]['beats'][0])
        self.assertEqual(song['orders'], ['A'])

    def test_command_internal_ties_and_external_guard(self):
        song, raw = fixture()
        before = copy.deepcopy(song)
        with self.assertRaisesRegex(ValueError, 'external tie'):
            tab.score_command(song, raw, dict(action='cut', occurrence='oa', track='guitar',
                                             voice=0, beats=['tail']))
        self.assertEqual(song, before)
        song['score']['patterns']['A']['beats'] = [
            beat('a', [0, 1], [note('n', 64)]),
            beat('b', [1, 1], [note('o', 64)])]
        song['score']['ties'] = [dict(**{'from': dict(occurrence='oa', note='n'),
                                        'to': dict(occurrence='oa', note='o')})]
        after, _ = tab.score_command(song, raw, dict(action='repeat', occurrence='oa', track='guitar',
                                                    voice=0, beats=['a', 'b']))
        self.assertEqual(len(after['score']['ties']), 2)
        self.assertEqual(after['score']['ties'][1]['from']['note'], 'copy_n')

    def test_command_repeat_shared_patterns_and_raw_conflict_refusal(self):
        song, raw = fixture()
        song['orders'] = ['A', 'A']
        song['score']['order_ids'] = ['oa', 'again']
        song['score']['ties'] = []
        song['score']['patterns']['A']['beats'] = [beat('a', [0, 1], [note('n', 64)])]
        after, _ = tab.score_command(song, raw, dict(action='repeat', occurrence='oa', track='guitar',
                                                    voice=0, beats=['a']))
        self.assertEqual(len(tab.authoring_view(after, raw)['positions']), 8)
        raw[0].rows[12][0].note = 65
        with self.assertRaisesRegex(ValueError, 'raw note'):
            tab.score_command(song, raw, dict(action='repeat', occurrence='oa', track='guitar',
                                             voice=0, beats=['a']))

    def test_exact_rhythm_chord_independent_sustain_and_tie(self):
        song, raw = fixture()
        original_song, original_raw = copy.deepcopy(song), copy.deepcopy(raw)
        result = tab.project_score(song, raw)
        a, b = result.patterns
        self.assertEqual([a.rows[0][ch].note for ch in (1, 0, 2)], [60, 64, 67])
        self.assertEqual([a.rows[r][0].note for r in (12, 16, 20)], [64, 65, 67])
        self.assertEqual(a.rows[24][0].note, NOTE_OFF)
        self.assertEqual(a.rows[0][6].note, 40)
        self.assertEqual(a.rows[24][6].note, NOTE_OFF)
        self.assertEqual(a.rows[42][0].note, 64)
        self.assertIsNone(b.rows[0][0].note)  # continuation is not restruck
        self.assertEqual(b.rows[6][0].note, NOTE_OFF)
        self.assertEqual((a.rows[0][1].effect, a.rows[0][1].param), (24, 64))
        self.assertEqual(result.owners[0, 0, 1, 'note']['note'], 'c')
        self.assertNotIn((0, 0, 1, 'effect'), result.owners)
        self.assertIs(result.raw_patterns, raw)
        self.assertEqual(song, original_song)
        self.assertEqual(raw, original_raw)
        self.assertIsNot(result.patterns[0].rows[0][0], raw[0].rows[0][0])
        json.dumps(tab.score_view(song, result))

    def test_written_spelling_and_exact_non_triplet_fraction(self):
        self.assertEqual(tab.duration_quarters({'value': 64, 'dots': 2, 'tuplet': [13, 8]}), Fraction(7, 104))
        self.assertEqual(tab.duration_quarters({'value': 8, 'dots': 1}), Fraction(3, 4))
        self.assertEqual(tab.duration_quarters({'value': 4, 'tuplet': [3, 2]}), Fraction(2, 3))

    def test_fret_to_pattern_to_pitch_roundtrip_preserves_raw_effect(self):
        song, raw = fixture()
        source = copy.deepcopy(song)
        changed = tab.apply_score_edit(song, {'op': 'note_set', 'pattern': 'A', 'beat': 'chord',
                                            'note': {'id': 'c', 'fret': 3}})
        projected = tab.project_score(changed, raw)
        self.assertEqual(projected.patterns[0].rows[0][1].note, 62)
        edit = copy.copy(projected.patterns[0].rows[0][1])
        edit.note = 60
        score, residual = tab.translate_pattern_edits(changed, projected, [(0, [{'row': 0, 'ch': 1, 'cell': format_cell(edit)}])])
        changed['score'] = score
        self.assertEqual(changed['score']['patterns']['A']['beats'][0]['notes'][0]['fret'], 1)
        self.assertEqual(residual, [])  # Only score changes; no raw block rewrite needed.
        self.assertEqual(tab.project_score(changed, raw).patterns, tab.project_score(song, raw).patterns)
        self.assertEqual(song, source)

    def test_save_reopen_and_sample_swap_keep_events(self):
        song, raw = fixture()
        reopened = yaml.safe_load(yaml.safe_dump(song, sort_keys=False))
        self.assertEqual(reopened['score'], song['score'])
        expected = tab.project_score(song, raw)
        reopened['samples'][1]['file'] = 'replacement.wav'
        self.assertEqual(tab.project_score(reopened, raw).patterns, expected.patterns)

    def test_rest_and_unplayable_notes_are_not_transposed(self):
        song, raw = fixture()
        change = tab.apply_score_edit(song, {'op': 'beat_set', 'pattern': 'B',
            'beat': beat('low', [1, 1], [note('low-note', 1)])})
        result = tab.project_score(change, raw)
        position = next(p for p in result.positions if p.get('note') == 'low-note')
        self.assertIsNone(position['string'])
        self.assertEqual(result.patterns[1].rows[12][position['ch']].note, 1)
        self.assertTrue(result.diagnostics)
        self.assertTrue(any(p['kind'] == 'beat' and p['beat'] == 'rest' for p in result.positions))

    def test_pitch_edit_keeps_valid_fingering_and_repairs_invalid_one(self):
        song, _ = fixture()
        changed = tab.apply_score_edit(song, {'op': 'note_set', 'pattern': 'A', 'beat': 'chord',
            'note': {'id': 'g', 'pitch': 67}})
        self.assertEqual(changed['score']['patterns']['A']['beats'][0]['notes'][2]['string'], 3)
        changed = tab.apply_score_edit(song, {'op': 'note_set', 'pattern': 'A', 'beat': 'chord',
            'note': {'id': 'c', 'pitch': 62}})
        self.assertEqual(changed['score']['patterns']['A']['beats'][0]['notes'][0]['fret'], 3)

    def test_unrepresentable_grid_refusal_is_lossless(self):
        song, raw = fixture()
        changed = tab.apply_score_edit(song, {'op': 'beat_set', 'pattern': 'B',
            'beat': beat('quint', [1, 1], [note('q', 64)], 8, [5, 4])})
        before = copy.deepcopy(changed)
        with self.assertRaisesRegex(ValueError, 'not representable'):
            tab.project_score(changed, raw)
        self.assertEqual(changed, before)
        self.assertEqual(changed['score']['patterns']['B']['beats'][1]['written']['tuplet'], [5, 4])

    def test_collisions_and_overlap_are_refused_without_mutating_source(self):
        song, raw = fixture()
        for attribute, value in [('note', 50), ('instrument', 2)]:
            broken = copy.deepcopy(raw)
            setattr(broken[0].rows[1][1], attribute, value)
            with self.assertRaisesRegex(ValueError, 'interrupts'):
                tab.project_score(song, broken)
        broken = copy.deepcopy(song)
        broken['score']['patterns']['A']['beats'].append(beat('overlap', [0, 1], [note('other', 64, 1, 0)], voice=1))
        with self.assertRaisesRegex(ValueError, 'independent channels'):
            tab.project_score(broken, raw)
        broken = copy.deepcopy(raw)
        broken[1].rows[7][6].effect = 1
        broken[1].rows[7][6].param = 6
        with self.assertRaisesRegex(ValueError, 'exact timing map'):
            tab.project_score(song, broken)

    def test_reused_pattern_context_requires_make_unique(self):
        song, raw = fixture()
        song['orders'].append('A')
        song['score']['order_ids'].append('oa2')
        with self.assertRaisesRegex(ValueError, 'make this pattern unique'):
            tab.project_score(song, raw)

    def test_reused_untied_pattern_projects_once(self):
        song, raw = fixture()
        song['score']['ties'] = []
        song['score']['patterns']['A']['beats'] = [song['score']['patterns']['A']['beats'][0]]
        song['orders'].append('A')
        song['score']['order_ids'].append('oa2')
        result = tab.project_score(song, raw)
        self.assertEqual(result.patterns[0].rows[0][1].note, 60)

    def test_delete_and_release_edit_are_atomic(self):
        song, raw = fixture()
        before = copy.deepcopy(song)
        projected = tab.project_score(song, raw)
        with self.assertRaisesRegex(ValueError, 'generated note-off'):
            tab.translate_pattern_edits(song, projected, [(1, [{'row': 6, 'ch': 0, 'cell': '...'}])])
        with self.assertRaisesRegex(ValueError, 'tied note/beat'):
            tab.apply_score_edit(song, {'op': 'note_delete', 'pattern': 'A', 'beat': 'tail', 'note': 'tailn'})
        self.assertEqual(song, before)
        score, residual = tab.translate_pattern_edits(song, projected, [(0, [{'row': 0, 'ch': 1, 'cell': '... .. ... X40'}])])
        self.assertEqual([n['id'] for n in score['patterns']['A']['beats'][0]['notes']], ['e', 'g'])
        self.assertEqual(residual, [])
        score, residual = tab.translate_pattern_edits(song, projected, [(0, [
            {'row': 0, 'ch': 1, 'cell': '... .. ... X40'}, {'row': 12, 'ch': 1, 'cell': '...'}])])
        self.assertEqual([n['id'] for n in score['patterns']['A']['beats'][0]['notes']], ['e', 'g'])
        self.assertEqual(residual, [])

    def test_legacy_projection_and_reverse_edit_are_unchanged(self):
        song, raw = fixture()
        del song['score']
        projected = tab.project_score(song, raw)
        self.assertEqual(projected.patterns, raw)
        self.assertFalse(projected.owners)
        groups = [(0, [{'row': 1, 'ch': 1, 'cell': 'C-5 01 ... X40'}])]
        score, residual = tab.translate_pattern_edits(song, projected, groups)
        self.assertIsNone(score)
        self.assertEqual(residual, groups)

    def test_structural_mappings_are_explicit(self):
        song, raw = fixture()
        renamed = tab.apply_structure_edit(song, {'op': 'pattern_rename', 'old': 'A', 'new': 'Verse'})
        self.assertIn('Verse', renamed['score']['patterns'])
        self.assertNotIn('A', renamed['score']['patterns'])
        clone = tab.apply_structure_edit(song, {'op': 'pattern_clone', 'src': 'A', 'name': 'A2'})
        self.assertEqual(clone['score']['patterns']['A2'], song['score']['patterns']['A'])
        self.assertIsNot(clone['score']['patterns']['A2'], song['score']['patterns']['A'])
        moved = tab.apply_structure_edit(song, {'op': 'channel_move', 'ch': 0, 'to': 6})
        self.assertEqual(moved['score']['tracks']['guitar']['channels'], [6, 0, 1, 2, 3, 4])
        self.assertEqual(moved['score']['tracks']['bass']['channels'], [5])
        with self.assertRaisesRegex(ValueError, 'assigned to a score track'):
            tab.apply_structure_edit(song, {'op': 'channel_remove', 'ch': 0})
        with self.assertRaisesRegex(ValueError, 'explicit origins'):
            tab.apply_structure_edit(song, {'op': 'orders', 'orders': ['B', 'A']})
        reordered = tab.apply_structure_edit(song, {'op': 'orders', 'orders': ['B', 'A'], 'origins': [1, 0]})
        self.assertEqual(reordered['score']['order_ids'], ['ob', 'oa'])
        reordered['orders'] = ['B', 'A']
        with self.assertRaisesRegex(ValueError, 'endpoints must be adjacent'):
            tab.project_score(reordered, raw)

    def test_split_preserves_exact_positions_and_ids(self):
        song, _ = fixture()
        song['score']['ties'] = []
        result = tab.apply_structure_edit(song, {'op': 'pattern_split', 'name': 'A', 'new': 'A2', 'row': 24})
        self.assertEqual(result['score']['patterns']['A2']['beats'][0]['at'], [0, 1])
        self.assertEqual(result['score']['patterns']['A2']['beats'][1]['at'], [3, 2])
        self.assertEqual(result['score']['patterns']['A2']['beats'][1]['notes'][0]['id'], 'tailn')
        self.assertEqual(len(result['score']['order_ids']), 3)
        with self.assertRaisesRegex(ValueError, 'crosses beat'):
            tab.apply_structure_edit(song, {'op': 'pattern_split', 'name': 'A', 'new': 'A2', 'row': 6})

    def test_bounds_unknown_fields_and_bad_fingering(self):
        song, _ = fixture()
        bad = [({'value': True}, 'integer'), ({'value': 3}, 'power of two'),
               ({'value': 8, 'tuplet': [3, 0]}, 'integer'), ({'value': 8, 'foo': 1}, 'unsupported')]
        for duration, message in bad:
            with self.subTest(duration=duration), self.assertRaisesRegex(ValueError, message):
                tab.duration_quarters(duration)
        with self.assertRaisesRegex(ValueError, 'conflicts'):
            tab.apply_score_edit(song, {'op': 'note_set', 'pattern': 'A', 'beat': 'chord',
                                      'note': {'id': 'c', 'pitch': 62, 'string': 2, 'fret': 1}})
        broken = copy.deepcopy(song)
        broken['score']['patterns']['A']['beats'][0]['notes'][0]['techniques'] = {'bend': True}
        with self.assertRaisesRegex(ValueError, 'unsupported'):
            tab.validate_score(broken)

    def test_roll_release_batch_resizes_whole_chord_and_keeps_raw_effect(self):
        song, raw = fixture()
        # Keep only the chord, so its releases are explicit on all three lanes.
        song['score']['patterns']['A']['beats'] = [song['score']['patterns']['A']['beats'][0]]
        song['score']['ties'] = []
        projected = tab.project_score(song, raw)
        changes = []
        for ch in (0, 1, 2):
            changes.extend([{'row': 12, 'ch': ch, 'cell': '...'},
                            {'row': 18, 'ch': ch, 'cell': '=== .. ... ...'}])
        score, residual = tab.translate_pattern_edits(song, projected, [(0, changes)])
        candidate = copy.deepcopy(song)
        candidate['score'] = score
        result = tab.project_score(candidate, raw)
        self.assertEqual(score['patterns']['A']['beats'][0]['written'], {'value': 4, 'dots': 1, 'tuplet': [1, 1]})
        for ch in (0, 1, 2):
            self.assertIsNone(result.patterns[0].rows[12][ch].note)
            self.assertEqual(result.patterns[0].rows[18][ch].note, NOTE_OFF)
        self.assertEqual(result.patterns[0].rows[0][1].effect, 24)
        self.assertEqual(residual, [])
        with self.assertRaisesRegex(ValueError, 'all generated note-offs'):
            tab.translate_pattern_edits(song, projected, [(0, changes[:2])])

    def test_resize_helper_refuses_tie_and_unspellable_length(self):
        song, raw = fixture()
        projected = tab.project_score(song, raw)
        with self.assertRaisesRegex(ValueError, 'tied beat'):
            tab.resize_beat(song, projected, 0, 'tail', 47)
        with self.assertRaisesRegex(ValueError, 'multiple tied written values'):
            tab.resize_beat(song, projected, 0, 'chord', 17)

    def test_measures_validate_exact_meter_bounds_overlap_and_identity(self):
        song, raw = fixture()
        song['score']['measures'] = [
            {'id': 'm1', 'from': {'occurrence': 'oa', 'at': [0, 1]},
             'to': {'occurrence': 'ob', 'at': [0, 1]}, 'meter': [4, 4]},
            {'id': 'm2', 'from': {'occurrence': 'ob', 'at': [0, 1]},
             'to': {'occurrence': 'ob', 'at': [4, 1]}, 'meter': [4, 4]}]
        tab.project_score(song, raw)
        for field, value, message in [('meter', [5, 4], 'does not match'),
                                       ('meter', [4, 3], 'power of two'),
                                       ('to', {'occurrence': 'ob', 'at': [5, 1]}, 'outside pattern')]:
            broken = copy.deepcopy(song)
            broken['score']['measures'][0][field] = value
            with self.subTest(field=field, value=value), self.assertRaisesRegex(ValueError, message):
                tab.project_score(broken, raw)
        broken = copy.deepcopy(song)
        broken['score']['measures'][1] = copy.deepcopy(broken['score']['measures'][0])
        broken['score']['measures'][1]['id'] = 'm2'
        with self.assertRaisesRegex(ValueError, 'overlapping measures'):
            tab.project_score(broken, raw)

    def test_reverse_edits_return_only_changed_residual_fields(self):
        song, raw = fixture()
        projected = tab.project_score(song, raw)
        score, residual = tab.translate_pattern_edits(song, projected, [(0, [
            {'row': 0, 'ch': 1, 'cell': 'D-5 01 ... X20'},
            {'row': 30, 'ch': 4, 'cell': '...'}])])
        self.assertEqual(score['patterns']['A']['beats'][0]['notes'][0]['pitch'], 62)
        self.assertEqual(residual, [(0, [{'row': 0, 'ch': 1, 'cell': '... .. ... X20'}])])
        self.assertEqual(raw[0].rows[0][1].param, 64)

    def test_old_generic_roll_move_cannot_demote_score_note_to_raw(self):
        song, raw = fixture()
        song = tab.apply_score_edit(song, {'op': 'beat_set', 'pattern': 'B',
            'beat': beat('movable', [1, 1], [note('move-me', 60, 2, 1)])})
        projection = tab.project_score(song, raw)
        before = copy.deepcopy(song)
        groups = [(1, [
            {'row': 12, 'ch': 1, 'cell': '...'},
            {'row': 18, 'ch': 1, 'cell': 'C-5 01 ... ...'},
            {'row': 24, 'ch': 1, 'cell': '...'},
            {'row': 30, 'ch': 1, 'cell': '==='}])]
        with self.assertRaisesRegex(ValueError, 'use note_move to preserve identity'):
            tab.translate_pattern_edits(song, projection, groups)
        self.assertEqual(song, before)
        self.assertEqual(projection.patterns[1].rows[12][1].note, 60)
        self.assertIsNone(raw[1].rows[12][1].note)

    def test_explicit_note_move_retains_identity_duration_and_reopens(self):
        song, raw = fixture()
        song = tab.apply_score_edit(song, {'op': 'beat_set', 'pattern': 'B',
            'beat': beat('movable', [1, 1], [note('move-me', 60, 2, 1)])})
        projection = tab.project_score(song, raw)
        before = copy.deepcopy(song)
        moved = tab.move_note(song, projection, 1, 'move-me', 18, pitch=62)
        reopened = yaml.safe_load(yaml.safe_dump(moved))
        b = next(b for b in reopened['score']['patterns']['B']['beats'] if b['id'] == 'movable')
        self.assertEqual(b['at'], [3, 2])
        self.assertEqual(b['written'], before['score']['patterns']['B']['beats'][1]['written'])
        self.assertEqual(b['notes'][0], {'id': 'move-me', 'pitch': 62, 'string': 2, 'fret': 3})
        after = tab.project_score(reopened, raw)
        self.assertIsNone(after.patterns[1].rows[12][1].note)
        self.assertEqual(after.patterns[1].rows[18][1].note, 62)
        self.assertIsNone(after.patterns[1].rows[24][1].note)
        self.assertEqual(after.patterns[1].rows[30][1].note, NOTE_OFF)
        self.assertEqual(after.owners[1, 18, 1, 'note']['note'], 'move-me')
        self.assertEqual(song, before)

    def test_note_move_refuses_partial_chords_ties_bounds_and_conflicts(self):
        song, raw = fixture()
        projection = tab.project_score(song, raw)
        before = copy.deepcopy(song)
        with self.assertRaisesRegex(ValueError, 'one chord note'):
            tab.move_note(song, projection, 0, 'c', 30)
        with self.assertRaisesRegex(ValueError, 'tied note'):
            tab.move_note(song, projection, 0, 'tailn', 30)
        with self.assertRaisesRegex(ValueError, 'boundary'):
            tab.move_note(song, projection, 0, 't1n', 47)
        for row in (-1, 48, True, 1.5):
            with self.subTest(row=row), self.assertRaises(ValueError):
                tab.move_note(song, projection, 0, 't1n', row)
        candidate = tab.move_note(song, projection, 0, 't1n', 16)
        with self.assertRaisesRegex(ValueError, 'overlapping beats'):
            tab.project_score(candidate, raw)
        self.assertEqual(song, before)

    @staticmethod
    def apply_residual(raw, groups):
        output = copy.deepcopy(raw)
        for pi, cells in groups:
            for cell in cells:
                output[pi].rows[cell['row']][cell['ch']] = parse_cell(cell['cell'])
        return output

    def test_promotion_preserves_all_cells_effects_automation_and_channel_identity(self):
        song, raw = fixture()
        # Tracker channel 0 cannot play this pitch on string 1. Fingering may
        # change strings, but the original playback channel must remain zero.
        raw[1].rows[12][0] = parse_cell('C-5 01 v37 X40')
        raw[1].rows[24][0] = parse_cell('=== .. ... H34')
        raw[1].lanes[(12, 0)] = ('e', 1)
        before = tab.project_score(song, raw)
        original_song, original_raw = copy.deepcopy(song), copy.deepcopy(raw)
        adopted, residual = tab.promote_pattern(song, before, 1, 'guitar', [{'row': 12, 'ch': 0}])
        combined_raw = self.apply_residual(raw, residual)
        after = tab.project_score(adopted, combined_raw)
        self.assertEqual(after.patterns, before.patterns)
        self.assertEqual(combined_raw[1].lanes, raw[1].lanes)
        self.assertEqual(combined_raw[1].rows[12][0], parse_cell('... .. v37 X40'))
        self.assertEqual(combined_raw[1].rows[24][0], parse_cell('... .. ... H34'))
        newbeat = adopted['score']['patterns']['B']['beats'][-1]
        newnote = newbeat['notes'][0]
        self.assertEqual(newbeat['duration_source'], 'tracker_boundary')
        self.assertEqual((newnote['pitch'], newnote['channel'], newnote['string'], newnote['fret']), (60, 0, 2, 1))
        edited = tab.apply_score_edit(adopted, {'op': 'note_set', 'pattern': 'B', 'beat': newbeat['id'],
            'note': {'id': newnote['id'], 'fret': 3}})
        self.assertEqual(tab.project_score(edited, combined_raw).patterns[1].rows[12][0].note, 62)
        self.assertEqual(song, original_song)
        self.assertEqual(raw, original_raw)

    def test_new_pattern_attack_is_visible_editable_and_stable_after_adoption(self):
        song, raw = fixture()
        raw[1].rows[12][0] = parse_cell('C-5 01 ... ...')
        raw[1].rows[12][1] = parse_cell('E-5 .. ... ...')  # retain instrument inheritance
        raw[1].rows[24][0] = parse_cell('===')
        raw[1].rows[24][1] = parse_cell('===')
        projected = tab.project_score(song, raw)
        adopted, residual = tab.promote_pattern(song, projected, 1, 'guitar')
        combined_raw = self.apply_residual(raw, residual)
        reopened = yaml.safe_load(yaml.safe_dump(adopted))
        after = tab.project_score(reopened, combined_raw)
        self.assertEqual(after.patterns, projected.patterns)
        notes = reopened['score']['patterns']['B']['beats'][-1]['notes']
        self.assertEqual([n['instrument'] for n in notes], [1, 0])
        self.assertEqual(len({n['id'] for n in notes}), 2)
        self.assertEqual({p['note'] for p in after.positions if p['pattern'] == 1 and p.get('row') == 12 and p['kind'] == 'note'},
                         {n['id'] for n in notes})
        with self.assertRaisesRegex(ValueError, 'no raw pitched attacks'):
            tab.promote_pattern(reopened, after, 1, 'guitar')

    def test_partial_promotion_ends_at_next_raw_attack_without_added_noteoff(self):
        song, raw = fixture()
        raw[1].rows[12][0] = parse_cell('C-5 01 ... X40')
        raw[1].rows[24][0] = parse_cell('D-5 01 ... ...')
        # The second attack has unknown final duration; selective adoption can
        # still retain it as the boundary of the first note without inventing off.
        projected = tab.project_score(song, raw)
        adopted, residual = tab.promote_pattern(song, projected, 1, 'guitar', [{'row': 12, 'ch': 0}])
        after = tab.project_score(adopted, self.apply_residual(raw, residual))
        self.assertEqual(after.patterns, projected.patterns)
        self.assertNotIn((1, 24, 0, 'note'), after.owners)
        with self.assertRaisesRegex(ValueError, 'unknown duration'):
            tab.promote_pattern(song, projected, 1, 'guitar')

    def test_promotion_unknown_or_cut_ending_refuses_entire_selection(self):
        song, raw = fixture()
        for ending, message in [(None, 'unknown duration'), (254, 'cut/fade')]:
            raw[1].rows[12][0] = parse_cell('C-5 01 ... ...')
            raw[1].rows[24][0] = Cell(note=ending)
            projected = tab.project_score(song, raw)
            original_song, original_raw = copy.deepcopy(song), copy.deepcopy(raw)
            with self.subTest(ending=ending), self.assertRaisesRegex(ValueError, message):
                tab.promote_pattern(song, projected, 1, 'guitar')
            self.assertEqual(song, original_song)
            self.assertEqual(raw, original_raw)

    def test_twenty_five_strings_signed_capo_and_channel_mapping(self):
        song = {'module': {'channels': 25, 'speed': 6}, 'patterns': {'A': {'rows': 16}}, 'orders': ['A']}
        song = tab.apply_score_edit(song, {'op': 'track_set', 'track': 'wide', 'value': {
            'tuning': list(range(64, 39, -1)), 'channels': list(range(25)), 'instrument': 1, 'capo': -24}})
        song = tab.apply_score_edit(song, {'op': 'beat_set', 'pattern': 'A',
            'beat': beat('n', [0, 1], [dict(note('n1', 40, 1, 0), channel=24)], track='wide')})
        raw = [Pattern('A', [[Cell() for _ in range(25)] for _ in range(16)])]
        self.assertEqual(tab.project_score(song, raw).patterns[0].rows[0][24].note, 40)
        moved = tab.apply_structure_edit(song, {'op': 'channel_move', 'ch': 24, 'to': 0})
        self.assertEqual(moved['score']['patterns']['A']['beats'][0]['notes'][0]['channel'], 0)
        for capo in (-25, 25):
            invalid = copy.deepcopy(song)
            invalid['score']['tracks']['wide']['capo'] = capo
            with self.assertRaises(ValueError):
                tab.validate_score(invalid)

    def test_explicit_tie_set_delete_preserves_endpoints_and_validation(self):
        song, raw = fixture()
        tie = copy.deepcopy(song['score']['ties'][0])
        removed = tab.apply_score_edit(song, {'op': 'tie_delete', 'from': tie['from'], 'to': tie['to']})
        self.assertEqual(removed['score']['ties'], [])
        restored = tab.apply_score_edit(removed, {'op': 'tie_set', **tie})
        self.assertEqual(tab.project_score(restored, raw).patterns, tab.project_score(song, raw).patterns)
        self.assertEqual(tab.apply_score_edit(restored, {'op': 'tie_set', **tie})['score']['ties'], [tie])
        with self.assertRaisesRegex(ValueError, 'no matching tie'):
            tab.apply_score_edit(removed, {'op': 'tie_delete', 'from': tie['from']})
        bad = dict(tie, to={'occurrence': 'ob', 'note': 'missing'})
        with self.assertRaisesRegex(ValueError, 'unknown note'):
            tab.apply_score_edit(removed, {'op': 'tie_set', **bad})

    def test_tracker_staff_groups_follow_sound_memory_and_keep_ambiguous_parts(self):
        from vulturetracker.model import Channel, Sample, Instrument
        rows = [[Cell() for _ in range(6)] for _ in range(2)]
        for ch, slot in enumerate([1, 0, 2, 0, 1, 0]):
            rows[0][ch] = Cell(note=60 + ch, instrument=slot)
        rows[0][1] = Cell(instrument=1)  # Instrument-only event, then a remembered note.
        rows[1][1] = Cell(note=67)
        rows[1][4] = Cell(note=68, instrument=2)  # Mixed sounds must not merge.
        next_rows = [[Cell(note=70), Cell(note=72), Cell(), Cell(note=72, instrument=1), Cell(), Cell()]]
        mod = Module(channels=[Channel(name=str(i)) for i in range(6)], samples=[Sample(), Sample()],
                     patterns=[Pattern('first', rows), Pattern('next', next_rows), Pattern('unused', [[Cell(note=60, instrument=2)]])],
                     orders=[0, 254, 1, 1, 255, 2])
        for instruments in (None, [Instrument(name='same'), Instrument(name='same')]):
            with self.subTest(instruments=instruments is not None):
                mod.instruments = instruments
                before = copy.deepcopy(mod)
                groups = tab.tracker_staff_groups(mod)
                self.assertEqual([g['channels'] for g in groups], [[0, 1], [2], [3], [4], [5]])
                self.assertEqual([g['slot'] for g in groups], [1, 2, None, None, None])
                self.assertEqual(groups[0]['name'], 'Sample 01' if instruments is None else 'Instrument 01')
                self.assertEqual(mod, before)

    def test_raw_preview_is_visible_without_adoption_or_fake_note_identity(self):
        song, raw = fixture()
        raw[1].rows[12][0] = parse_cell('C-5 01 v37 X40')
        raw[1].rows[24][0] = parse_cell('D-5 01 ... ...')
        projection = tab.project_score(song, raw)
        source = copy.deepcopy(song)
        entries = tab.raw_note_view(song, projection)
        self.assertEqual(len(entries), 2)
        self.assertEqual(entries[0]['pitch'], 60)
        self.assertEqual(entries[0]['duration'], [1, 1])
        self.assertEqual(entries[0]['source'], 'raw')
        self.assertFalse(entries[0]['editable'])
        self.assertNotIn('note', entries[0])
        self.assertEqual(entries[0]['string'], 2)
        self.assertIsNone(entries[1]['duration'])
        self.assertIn('unknown duration', entries[1]['reason'])
        json.dumps(tab.score_view(song, projection))
        self.assertEqual(song, source)

    def test_tied_note_and_beat_deletion_require_explicit_incident_cleanup(self):
        song, raw = fixture()
        original = copy.deepcopy(song)
        for edit in ({'op': 'note_delete', 'pattern': 'A', 'beat': 'tail', 'note': 'tailn'},
                     {'op': 'beat_delete', 'pattern': 'A', 'beat': 'tail'}):
            with self.subTest(op=edit['op']), self.assertRaisesRegex(ValueError, 'remove_ties: true'):
                tab.apply_score_edit(song, edit)
            candidate = tab.apply_score_edit(song, dict(edit, remove_ties=True))
            self.assertEqual(candidate['score']['ties'], [])
            result = tab.project_score(candidate, raw)
            self.assertIsNone(result.patterns[0].rows[42][0].note)
            self.assertEqual(result.patterns[1].rows[0][0].note, 64)  # surviving continuation attacks
            self.assertEqual(result.patterns[1].rows[6][0].note, NOTE_OFF)
        self.assertEqual(song, original)
        with self.assertRaisesRegex(ValueError, 'must be a boolean'):
            tab.apply_score_edit(song, {'op': 'beat_delete', 'pattern': 'A', 'beat': 'tail', 'remove_ties': 1})

    def test_tie_cleanup_keeps_unrelated_edges_and_chain_endpoints(self):
        song, raw = fixture()
        a = beat('a2', [7, 2], [note('a2n', 45, 1, 5)], 8, track='bass')
        b = beat('b2', [0, 1], [note('b2n', 45, 1, 5)], 8, track='bass')
        song = tab.apply_score_edit(song, {'op': 'beat_set', 'pattern': 'A', 'beat': a})
        song = tab.apply_score_edit(song, {'op': 'beat_set', 'pattern': 'B', 'beat': b})
        other_tie = {'from': {'occurrence': 'oa', 'note': 'a2n'}, 'to': {'occurrence': 'ob', 'note': 'b2n'}}
        song = tab.apply_score_edit(song, {'op': 'tie_set', **other_tie})
        tab.project_score(song, raw)
        candidate = tab.apply_score_edit(song, {'op': 'note_delete', 'pattern': 'A', 'beat': 'tail',
                                              'note': 'tailn', 'remove_ties': True})
        self.assertEqual(candidate['score']['ties'], [other_tie])
        result = tab.project_score(candidate, raw)
        self.assertEqual(result.patterns[1].rows[0][0].note, 64)
        self.assertIsNone(result.patterns[1].rows[0][6].note)
        self.assertEqual(result.patterns[1].rows[6][6].note, NOTE_OFF)
        detached = tab.apply_score_edit(song, {'op': 'tie_delete', **other_tie})
        self.assertEqual(detached['score']['ties'], [song['score']['ties'][0]])

    def test_tied_pitch_fret_channel_and_instrument_changes_refuse_atomically(self):
        song, raw = fixture()
        before = copy.deepcopy(song)
        for patch in ({'pitch': 65}, {'fret': 1}, {'channel': 1}, {'instrument': 2}, {'volume': 30}):
            with self.subTest(patch=patch), self.assertRaisesRegex(ValueError, 'tie continuity would change'):
                tab.apply_score_edit(song, {'op': 'note_set', 'pattern': 'A', 'beat': 'tail',
                                          'note': dict(id='tailn', **patch)})
            self.assertEqual(song, before)
        projected = tab.project_score(song, raw)
        with self.assertRaisesRegex(ValueError, 'tie continuity would change'):
            tab.translate_pattern_edits(song, projected, [(0, [{'row': 42, 'ch': 0, 'cell': 'F-5 01 ... ...'}])])
        self.assertEqual(song, before)

    def test_retuning_and_channel_moves_preserve_tie_continuity(self):
        song, raw = fixture()
        track = copy.deepcopy(song['score']['tracks']['guitar'])
        track['capo'] = -1
        tuned = tab.apply_score_edit(song, {'op': 'track_set', 'track': 'guitar', 'value': track})
        self.assertEqual(tuned['score']['patterns']['A']['beats'][-2]['notes'][0]['pitch'], 64)
        self.assertEqual(tuned['score']['patterns']['A']['beats'][-2]['notes'][0]['fret'], 1)
        self.assertEqual(tab.project_score(tuned, raw).patterns, tab.project_score(song, raw).patterns)
        moved = tab.apply_structure_edit(tuned, {'op': 'channel_move', 'ch': 0, 'to': 2})
        moved_raw = copy.deepcopy(raw)
        for p in moved_raw:
            for row in p.rows:
                row.insert(2, row.pop(0))
        projected = tab.project_score(moved, moved_raw)
        self.assertEqual(projected.patterns[0].rows[42][2].note, 64)
        self.assertIsNone(projected.patterns[1].rows[0][2].note)
        self.assertEqual(projected.patterns[1].rows[6][2].note, NOTE_OFF)

    def test_whole_beat_move_preserves_chord_ids_channels_duration_and_raw_fields(self):
        song, raw = fixture()
        song['score']['patterns']['A']['beats'] = [song['score']['patterns']['A']['beats'][0]]
        song['score']['ties'] = []
        raw[0].rows[18][1].effect, raw[0].rows[18][1].param = 8, 52
        raw[0].lanes[(18, 1)] = ('e', 1)
        before = copy.deepcopy(song)
        original_raw = copy.deepcopy(raw)
        projected = tab.project_score(song, raw)
        candidate = tab.move_beat(song, projected, 0, 'chord', 18)
        reopened = yaml.safe_load(yaml.safe_dump(candidate))
        moved = reopened['score']['patterns']['A']['beats'][0]
        self.assertEqual(moved['id'], 'chord')
        self.assertEqual(moved['notes'], before['score']['patterns']['A']['beats'][0]['notes'])
        self.assertEqual(moved['written'], before['score']['patterns']['A']['beats'][0]['written'])
        self.assertEqual(moved['at'], [3, 2])
        result = tab.project_score(reopened, raw)
        for ch, pitch in ((0, 64), (1, 60), (2, 67)):
            self.assertIsNone(result.patterns[0].rows[0][ch].note)
            self.assertEqual(result.patterns[0].rows[18][ch].note, pitch)
            self.assertEqual(result.patterns[0].rows[30][ch].note, NOTE_OFF)
        self.assertEqual(result.patterns[0].rows[0][1].effect, 24)
        self.assertEqual(result.patterns[0].rows[18][1].effect, 8)
        self.assertEqual(result.patterns[0].lanes, raw[0].lanes)
        self.assertEqual(song, before)
        self.assertEqual(raw, original_raw)

    def test_beat_move_refuses_tied_member_or_destination_conflicts(self):
        song, raw = fixture()
        projected = tab.project_score(song, raw)
        with self.assertRaisesRegex(ValueError, 'tied note'):
            tab.move_beat(song, projected, 0, 'tail', 30)
        candidate = tab.move_beat(song, projected, 0, 'chord', 12)
        with self.assertRaisesRegex(ValueError, 'overlapping beats'):
            tab.project_score(candidate, raw)
        with self.assertRaisesRegex(ValueError, 'pattern boundary'):
            tab.move_beat(song, projected, 0, 'chord', 47)

    def test_deleting_middle_of_tie_chain_removes_both_incident_edges(self):
        song, raw = fixture()
        song = tab.apply_score_edit(song, {'op': 'beat_set', 'pattern': 'B',
            'beat': beat('third', [1, 2], [note('thirdn', 64, 1, 0)], 8)})
        song = tab.apply_score_edit(song, {'op': 'tie_set',
            'from': {'occurrence': 'ob', 'note': 'headn'}, 'to': {'occurrence': 'ob', 'note': 'thirdn'}})
        before = tab.project_score(song, raw)
        self.assertIsNone(before.patterns[1].rows[6][0].note)
        candidate = tab.apply_score_edit(song, {'op': 'beat_delete', 'pattern': 'B', 'beat': 'head', 'remove_ties': True})
        self.assertEqual(candidate['score']['ties'], [])
        after = tab.project_score(candidate, raw)
        self.assertEqual(after.patterns[0].rows[42][0].note, 64)
        self.assertEqual(after.patterns[1].rows[0][0].note, NOTE_OFF)
        self.assertEqual(after.patterns[1].rows[6][0].note, 64)
        self.assertEqual(after.patterns[1].rows[12][0].note, NOTE_OFF)
        self.assertEqual(len(song['score']['ties']), 2)

    def test_clipboard_chord_rest_two_voices_preserve_properties_not_raw_effects(self):
        song, raw = fixture()
        song = tab.apply_score_edit(song, {'op': 'beat_set', 'pattern': 'A',
            'beat': beat('lower_voice', [0, 1], [note('lower', 40, 6, 0)], 2, voice=1)})
        chord = song['score']['patterns']['A']['beats'][0]
        chord['notes'][0].update(volume=37, spelling={'step': 'C', 'alter': 0}, channel=1)
        raw[1].rows[6][1] = parse_cell('... .. ... X20')
        projected = tab.project_score(song, raw)
        original, original_raw = copy.deepcopy(song), copy.deepcopy(raw)
        clipboard = tab.capture_score_clipboard(song, 'A', ['rest', 'lower_voice', 'chord'])
        frozen_clipboard = copy.deepcopy(clipboard)
        json.dumps(clipboard)
        candidate = tab.paste_score_clipboard(song, projected, 1, 6, clipboard)
        result = tab.project_score(candidate, raw)
        pasted = {b['id']: b for b in candidate['score']['patterns']['B']['beats']}
        self.assertEqual(pasted['copy_chord']['at'], [1, 2])
        self.assertEqual(pasted['copy_lower_voice']['voice'], 1)
        self.assertEqual(pasted['copy_rest']['at'], [5, 2])
        self.assertEqual(pasted['copy_rest']['notes'], [])
        copied_note = pasted['copy_chord']['notes'][0]
        self.assertEqual({k: v for k, v in copied_note.items() if k != 'id'},
                         {k: v for k, v in chord['notes'][0].items() if k != 'id'})
        self.assertEqual(result.patterns[1].rows[6][1].note, 60)
        self.assertEqual(result.patterns[1].rows[6][1].param, 32)
        self.assertEqual(result.patterns[0].rows[0][1].param, 64)
        self.assertEqual(song, original)
        self.assertEqual(raw, original_raw)
        self.assertEqual(clipboard, frozen_clipboard)

    def test_clipboard_paste_twice_gets_fresh_ids_and_roundtrips(self):
        song, raw = fixture()
        long_id = 'n' * 80
        song['score']['patterns']['A']['beats'][0]['notes'][0]['id'] = long_id
        projection = tab.project_score(song, raw)
        clipboard = tab.capture_score_clipboard(song, 'A', ['chord'])
        first = tab.paste_score_clipboard(song, projection, 1, 12, clipboard)
        first_projection = tab.project_score(first, raw)
        second = tab.paste_score_clipboard(first, first_projection, 1, 24, clipboard)
        reopened = yaml.safe_load(yaml.safe_dump(second))
        self.assertEqual(tab.project_score(reopened, raw).patterns, tab.project_score(second, raw).patterns)
        beats = reopened['score']['patterns']['B']['beats']
        self.assertEqual([b['id'] for b in beats], ['head', 'copy_chord', 'copy_chord_2'])
        ids = [n['id'] for b in beats for n in b['notes']]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertTrue(all(len(i) <= 80 for i in ids))
        self.assertNotEqual(beats[1]['notes'][0]['id'], beats[2]['notes'][0]['id'])
        self.assertEqual(len(song['score']['patterns']['B']['beats']), 1)

    def test_clipboard_internal_tie_uses_fresh_destination_note_ids(self):
        song, raw = fixture()
        song['score']['patterns']['A']['beats'] = [
            beat('first', [0, 1], [note('one', 60, 2, 1)]),
            beat('second', [1, 1], [note('two', 60, 2, 1)])]
        song['score']['patterns']['B']['beats'] = []
        song['score']['ties'] = [{'from': {'occurrence': 'oa', 'note': 'one'},
                                 'to': {'occurrence': 'oa', 'note': 'two'}}]
        projected = tab.project_score(song, raw)
        clipboard = tab.capture_score_clipboard(song, 'A', ['second', 'first'])
        self.assertEqual(clipboard['ties'], [{'from': 'one', 'to': 'two'}])
        candidate = tab.paste_score_clipboard(song, projected, 1, 12, clipboard)
        self.assertEqual(candidate['score']['ties'][-1], {'from': {'occurrence': 'ob', 'note': 'copy_one'},
                                                       'to': {'occurrence': 'ob', 'note': 'copy_two'}})
        result = tab.project_score(candidate, raw)
        self.assertEqual(result.patterns[1].rows[12][1].note, 60)
        self.assertIsNone(result.patterns[1].rows[24][1].note)
        self.assertEqual(result.patterns[1].rows[36][1].note, NOTE_OFF)
        self.assertEqual(tab.capture_score_clipboard(song, 'A', ['first'])['ties'], [])
        # An exact end at the final pattern boundary: the standalone IT ends there, so no release cell is
        # invented; every other release stays.
        boundary = tab.paste_score_clipboard(song, projected, 1, 24, clipboard)
        ended = tab.project_score(boundary, raw)
        self.assertFalse(any(o['role'] == 'release' and o['note'] == 'first' for o in ended.owners.values()))

    def test_clipboard_external_ties_and_ambiguous_occurrences_are_refused(self):
        song, raw = fixture()
        self.assertEqual(tab.capture_score_clipboard(song, 'A', ['tail'])['ties'], [])
        song['score']['patterns']['A']['beats'] = [
            beat('first', [0, 1], [note('one', 60, 2, 1)]),
            beat('second', [1, 1], [note('two', 60, 2, 1)])]
        song['score']['patterns']['B']['beats'] = []
        song['orders'] = ['A', 'A', 'B']
        song['score']['order_ids'] = ['oa', 'oa2', 'ob']
        song['score']['ties'] = [{'from': {'occurrence': oid, 'note': 'one'},
                                 'to': {'occurrence': oid, 'note': 'two'}} for oid in ('oa', 'oa2')]
        projected = tab.project_score(song, raw)
        with self.assertRaisesRegex(ValueError, 'source occurrence explicitly'):
            tab.capture_score_clipboard(song, 'A', ['first', 'second'])
        clipboard = tab.capture_score_clipboard(song, 'A', ['first', 'second'], 'oa2')
        self.assertEqual(len(clipboard['ties']), 1)
        with self.assertRaisesRegex(ValueError, 'make the pattern unique'):
            tab.paste_score_clipboard(song, projected, 0, 24, clipboard, 'oa')
        bad = copy.deepcopy(clipboard)
        bad['ties'][0]['to'] = 'not-selected'
        with self.assertRaisesRegex(ValueError, 'dangling/external tie'):
            tab.paste_score_clipboard(song, projected, 1, 12, bad)

    def test_clipboard_collision_and_unrepresentable_timing_leave_source_immutable(self):
        song, raw = fixture()
        projected = tab.project_score(song, raw)
        source = copy.deepcopy(song)
        clipboard = tab.capture_score_clipboard(song, 'A', ['chord'])
        candidate = tab.paste_score_clipboard(song, projected, 0, 12, clipboard)
        with self.assertRaisesRegex(ValueError, 'overlapping beats'):
            tab.project_score(candidate, raw)
        bad = copy.deepcopy(clipboard)
        bad['beats'][0]['at'] = [1, 5]
        with self.assertRaisesRegex(ValueError, 'not representable'):
            tab.paste_score_clipboard(song, projected, 1, 12, bad)
        with self.assertRaisesRegex(ValueError, 'pattern boundary'):
            tab.paste_score_clipboard(song, projected, 1, 47, clipboard)
        self.assertEqual(song, source)

    def test_clipboard_rejects_duplicate_selection_and_malformed_local_ids(self):
        song, raw = fixture()
        projected = tab.project_score(song, raw)
        with self.assertRaisesRegex(ValueError, 'duplicate beat IDs'):
            tab.capture_score_clipboard(song, 'A', ['chord', 'chord'])
        with self.assertRaisesRegex(ValueError, '1..1024'):
            tab.capture_score_clipboard(song, 'A', [])
        clipboard = tab.capture_score_clipboard(song, 'A', ['chord'])
        clipboard['beats'][0]['notes'][1]['id'] = clipboard['beats'][0]['notes'][0]['id']
        with self.assertRaisesRegex(ValueError, 'duplicate note IDs'):
            tab.paste_score_clipboard(song, projected, 1, 12, clipboard)

    def test_measure_set_updates_exact_meter_without_retiming_notes(self):
        song, raw = fixture()
        original = copy.deepcopy(song)
        expected = tab.project_score(song, raw).patterns
        measure = {'id': 'bar_a', 'from': {'occurrence': 'oa', 'at': [0, 1]},
                   'to': {'occurrence': 'oa', 'at': [4, 1]}, 'meter': [4, 4]}
        added = tab.apply_score_edit(song, {'op': 'measure_set', 'measure': measure})
        self.assertEqual(tab.project_score(added, raw).patterns, expected)
        shorter = copy.deepcopy(measure)
        shorter.update(to={'occurrence': 'oa', 'at': [3, 1]}, meter=[3, 4])
        changed = tab.apply_score_edit(added, {'op': 'measure_set', 'measure': shorter})
        self.assertEqual(changed['score']['measures'], [shorter])
        self.assertEqual(tab.project_score(changed, raw).patterns, expected)
        deleted = tab.apply_score_edit(changed, {'op': 'measure_delete', 'measure': 'bar_a'})
        self.assertEqual(deleted['score']['measures'], [])
        self.assertEqual(deleted['score']['patterns'], original['score']['patterns'])
        self.assertEqual(deleted['score']['ties'], original['score']['ties'])
        # The original immutable candidate remains a complete undo snapshot.
        self.assertEqual(song, original)
        self.assertEqual(yaml.safe_load(yaml.safe_dump(added))['score']['measures'], [measure])
        with self.assertRaisesRegex(ValueError, 'unknown measure'):
            tab.apply_score_edit(deleted, {'op': 'measure_delete', 'measure': 'bar_a'})

    def test_measure_operations_refuse_bounds_overlap_and_unsupported_playback_headers(self):
        song, raw = fixture()
        measure = {'id': 'm', 'from': {'occurrence': 'oa', 'at': [0, 1]},
                   'to': {'occurrence': 'oa', 'at': [4, 1]}, 'meter': [4, 4]}
        candidate = tab.apply_score_edit(song, {'op': 'measure_set', 'measure': measure})
        overlap = tab.apply_score_edit(candidate, {'op': 'measure_set', 'measure': dict(measure, id='overlap')})
        with self.assertRaisesRegex(ValueError, 'overlapping measures'):
            tab.project_score(overlap, raw)
        for change, message in [({'to': {'occurrence': 'oa', 'at': [5, 1]}, 'meter': [5, 4]}, 'outside pattern'),
                                ({'meter': [5, 4]}, 'does not match its meter')]:
            invalid = tab.apply_score_edit(song, {'op': 'measure_set', 'measure': dict(measure, **change)})
            with self.assertRaisesRegex(ValueError, message):
                tab.project_score(invalid, raw)
        for change, message in [({'from': {'occurrence': 'missing', 'at': [0, 1]}}, 'unknown occurrence'),
                                ({'meter': [4, 3]}, 'power of two'),
                                ({'tempo': 90}, 'unsupported by shared playback'),
                                ({'key_change': {'fifths': 1}}, 'unsupported fields')]:
            with self.subTest(change=change), self.assertRaisesRegex(ValueError, message):
                tab.apply_score_edit(song, {'op': 'measure_set', 'measure': dict(measure, **change)})

    def test_measure_identity_distinguishes_reused_pattern_occurrences(self):
        song, raw = fixture()
        song['score']['patterns']['A']['beats'] = [song['score']['patterns']['A']['beats'][0]]
        song['score']['ties'] = []
        song['orders'] = ['A', 'A', 'B']
        song['score']['order_ids'] = ['oa', 'oa2', 'ob']
        for identity, occurrence in [('m_first', 'oa'), ('m_second', 'oa2')]:
            song = tab.apply_score_edit(song, {'op': 'measure_set', 'measure': {
                'id': identity, 'from': {'occurrence': occurrence, 'at': [0, 1]},
                'to': {'occurrence': occurrence, 'at': [4, 1]}, 'meter': [4, 4]}})
        expected = tab.project_score(song, raw).patterns
        deleted = tab.apply_score_edit(song, {'op': 'measure_delete', 'measure': 'm_first'})
        self.assertEqual([m['id'] for m in deleted['score']['measures']], ['m_second'])
        self.assertEqual(deleted['score']['measures'][0]['from']['occurrence'], 'oa2')
        self.assertEqual(tab.project_score(deleted, raw).patterns, expected)

    def test_track_delete_explicitly_removes_only_its_beats_and_incident_ties(self):
        song, raw = fixture()
        song = tab.apply_score_edit(song, {'op': 'measure_set', 'measure': {
            'id': 'm', 'from': {'occurrence': 'oa', 'at': [0, 1]},
            'to': {'occurrence': 'oa', 'at': [4, 1]}, 'meter': [4, 4]}})
        original = copy.deepcopy(song)
        with self.assertRaisesRegex(ValueError, 'remove_notes: true'):
            tab.apply_score_edit(song, {'op': 'track_delete', 'track': 'guitar'})
        deleted = tab.apply_score_edit(song, {'op': 'track_delete', 'track': 'guitar', 'remove_notes': True})
        self.assertEqual(set(deleted['score']['tracks']), {'bass'})
        self.assertEqual([b['id'] for b in deleted['score']['patterns']['A']['beats']], ['bass'])
        self.assertEqual(deleted['score']['patterns']['B']['beats'], [])
        self.assertEqual(deleted['score']['ties'], [])
        self.assertEqual(deleted['score']['measures'], original['score']['measures'])
        self.assertEqual(deleted['module'], original['module'])
        self.assertEqual(deleted['samples'], original['samples'])
        self.assertEqual(deleted['patterns'], original['patterns'])
        result = tab.project_score(deleted, raw)
        self.assertEqual(result.patterns[0].rows[0][1], parse_cell('... .. ... X40'))
        self.assertEqual(result.patterns[0].rows[0][6].note, 40)
        self.assertEqual(song, original)
        self.assertEqual(tab.project_score(yaml.safe_load(yaml.safe_dump(deleted)), raw).patterns, result.patterns)

    def test_unused_track_delete_and_strict_removal_flag(self):
        song, _ = fixture()
        song['score']['patterns']['A']['beats'] = [b for b in song['score']['patterns']['A']['beats'] if b['track'] != 'bass']
        removed = tab.apply_score_edit(song, {'op': 'track_delete', 'track': 'bass'})
        self.assertNotIn('bass', removed['score']['tracks'])
        self.assertEqual(removed['score']['patterns'], song['score']['patterns'])
        for flag in (1, 'yes', None):
            with self.subTest(flag=flag), self.assertRaisesRegex(ValueError, 'must be a boolean'):
                tab.apply_score_edit(song, {'op': 'track_delete', 'track': 'guitar', 'remove_notes': flag})

    def test_track_midi_metadata_preserves_implicit_fingering_and_playback(self):
        song, raw = plan_fixture()
        for spec in song['score']['patterns'].values():
            for entry in spec['beats']:
                for item in entry['notes']:
                    item.pop('string', None)
                    item.pop('fret', None)
        original = copy.deepcopy(song)
        before = tab.playback_plan(song, raw, 48000)['events']
        track = dict(song['score']['tracks']['guitar'], name='Export guitar',
                     midi={'program': 24, 'bank': 129})
        changed = tab.apply_score_edit(song, {'op': 'track_set', 'track': 'guitar', 'value': track})
        self.assertEqual(changed['score']['patterns'], song['score']['patterns'])
        self.assertEqual(tab.playback_plan(changed, raw, 48000)['events'], before)
        reopened = yaml.safe_load(yaml.safe_dump(changed))
        self.assertEqual(reopened, changed)
        self.assertEqual(song, original)
        for midi in ({'program': 0}, {'program': 127, 'bank': 16383}):
            tab.apply_score_edit(song, {'op': 'track_set', 'track': 'guitar', 'value': dict(track, midi=midi)})
        for midi in (None, {}, {'program': True}, {'program': -1}, {'program': 128},
                     {'program': 0, 'bank': -1}, {'program': 0, 'bank': 16384},
                     {'program': 0, 'bank': True}, {'program': 0, 'channel': 1}):
            with self.subTest(midi=midi), self.assertRaises(ValueError):
                tab.apply_score_edit(song, {'op': 'track_set', 'track': 'guitar', 'value': dict(track, midi=midi)})

    def test_midi_source_pan_exact_schema_and_required_program(self):
        song, _ = plan_fixture()
        track = song['score']['tracks']['guitar']
        for value, anchor in ((0, 0), (63, 32), (127, 64), (63, 0)):
            binding = dict(value=value, mixer_pan=anchor)
            changed = tab.apply_score_edit(song, dict(op='track_set', track='guitar',
                value=dict(track, midi=dict(program=25, source_pan=binding))))
            self.assertEqual(changed['score']['tracks']['guitar']['midi']['source_pan'], binding)
            self.assertEqual(yaml.safe_load(yaml.safe_dump(changed)), changed)
        invalid = [None, {}, [], dict(value=63), dict(mixer_pan=32),
                   dict(value=True, mixer_pan=32), dict(value=63, mixer_pan=False),
                   dict(value=-1, mixer_pan=32), dict(value=128, mixer_pan=32),
                   dict(value=63, mixer_pan=-1), dict(value=63, mixer_pan=65),
                   dict(value=63.0, mixer_pan=32), dict(value=63, mixer_pan=32.0),
                   dict(value='63', mixer_pan=32), dict(value=63, mixer_pan=32, extra=0)]
        before = copy.deepcopy(song)
        for binding in invalid:
            with self.subTest(binding=binding), self.assertRaises(ValueError):
                tab.apply_score_edit(song, dict(op='track_set', track='guitar',
                    value=dict(track, midi=dict(program=25, source_pan=binding))))
            self.assertEqual(song, before)
        with self.assertRaisesRegex(ValueError, 'MIDI program'):
            tab.apply_score_edit(song, dict(op='track_set', track='guitar',
                value=dict(track, midi=dict(source_pan=dict(value=63, mixer_pan=32)))))

    def test_midi_source_pan_track_edits_preserve_or_clear_ownership(self):
        song, _ = plan_fixture()
        track = song['score']['tracks']['guitar']
        track['midi'] = dict(program=25, bank=0, source_pan=dict(value=63, mixer_pan=32))
        before = copy.deepcopy(song)
        for field, value in (('name', 'New name'), ('program', 26), ('bank', 129)):
            edited = copy.deepcopy(track)
            (edited['midi'] if field in ('program', 'bank') else edited)[field] = value
            changed = tab.apply_score_edit(song, dict(op='track_set', track='guitar', value=edited))
            self.assertEqual(changed['score']['tracks']['guitar']['midi']['source_pan'],
                             track['midi']['source_pan'])
            self.assertEqual(song, before)
            self.assertEqual(edited['midi']['source_pan'], track['midi']['source_pan'])
        reassigned = copy.deepcopy(track)
        reassigned['channels'] = list(reversed(track['channels']))
        changed = tab.apply_score_edit(song, dict(op='track_set', track='guitar', value=reassigned))
        self.assertEqual(changed['score']['tracks']['guitar']['midi'], dict(program=25, bank=0))
        self.assertEqual(reassigned['midi'], track['midi'])
        removed = copy.deepcopy(track)
        removed.pop('midi')  # Clearing the program removes its entire optional MIDI mapping.
        cleared = tab.apply_score_edit(song, dict(op='track_set', track='guitar', value=removed))
        self.assertNotIn('midi', cleared['score']['tracks']['guitar'])
        self.assertEqual(song, before)

    def test_midi_source_pan_is_audio_neutral_and_keeps_implicit_fingering(self):
        song, raw = plan_fixture()
        for spec in song['score']['patterns'].values():
            for b in spec['beats']:
                for n in b['notes']:
                    n.pop('string', None)
                    n.pop('fret', None)
        track = copy.deepcopy(song['score']['tracks']['guitar'])
        track['midi'] = dict(program=25, source_pan=dict(value=63, mixer_pan=32))
        changed = tab.apply_score_edit(song, dict(op='track_set', track='guitar', value=track))
        self.assertEqual(changed['module'], song['module'])
        self.assertEqual(changed['score']['patterns'], song['score']['patterns'])
        self.assertEqual(tab.project_score(changed, raw).patterns, tab.project_score(song, raw).patterns)
        for rate in (44100, 48000):
            self.assertEqual(tab.playback_plan(changed, raw, rate), tab.playback_plan(song, raw, rate))

    def test_track_notation_metadata_stem_override_and_auto_spelling_do_not_change_audio_cells(self):
        song, raw = fixture()
        before = tab.project_score(song, raw).patterns
        track = copy.deepcopy(song['score']['tracks']['guitar'])
        track.update(name='Rhythm Guitar', color='#12aBcF', clef='treble', key={'fifths': -3, 'mode': 'minor'}, stem='up')
        changed = tab.apply_score_edit(song, {'op': 'track_set', 'track': 'guitar', 'value': track})
        chord = copy.deepcopy(changed['score']['patterns']['A']['beats'][0])
        chord['stem'] = 'down'
        chord['notes'][0]['spelling'] = None
        changed = tab.apply_score_edit(changed, {'op': 'beat_set', 'pattern': 'A', 'beat': chord})
        projection = tab.project_score(changed, raw)
        self.assertEqual(projection.patterns, before)
        positions = [p for p in projection.positions if p['kind'] == 'beat']
        self.assertEqual(next(p['stem'] for p in positions if p['beat'] == 'chord'), 'down')
        self.assertEqual(next(p['stem'] for p in positions if p['beat'] == 't1'), 'up')
        reopened = yaml.safe_load(yaml.safe_dump(changed))
        self.assertEqual(reopened['score']['tracks']['guitar'], track)
        self.assertIsNone(reopened['score']['patterns']['A']['beats'][0]['notes'][0]['spelling'])
        with self.assertRaisesRegex(ValueError, 'spelling does not match pitch'):
            tab.apply_score_edit(changed, {'op': 'note_set', 'pattern': 'A', 'beat': 'chord',
                'note': {'id': 'c', 'spelling': {'step': 'D', 'alter': 0}}})

    def test_track_and_beat_metadata_validation(self):
        song, _ = fixture()
        for patch, message in [({'color': 'red'}, '#rrggbb'), ({'clef': 'other'}, 'unsupported clef'),
                               ({'key': {'fifths': 8}}, 'integer -7..7'),
                               ({'key': {'fifths': 1, 'mode': 'dorian'}}, 'major or minor'),
                               ({'stem': 'sideways'}, 'auto, up or down')]:
            track = dict(song['score']['tracks']['guitar'], **patch)
            with self.subTest(patch=patch), self.assertRaisesRegex(ValueError, message):
                tab.apply_score_edit(song, {'op': 'track_set', 'track': 'guitar', 'value': track})
        invalid = copy.deepcopy(song['score']['patterns']['A']['beats'][0])
        invalid['stem'] = 1
        with self.assertRaisesRegex(ValueError, 'stem must be'):
            tab.apply_score_edit(song, {'op': 'beat_set', 'pattern': 'A', 'beat': invalid})

    def test_exact_plan_arbitrary_tuplet_double_dots_and_fractional_overlay(self):
        song, raw = plan_fixture()
        tiny = beat('thirteen', [1, 13], [note('n13', 60, 2, 1)], 64, [13, 8])
        tiny['written']['dots'] = 2
        song['score']['patterns']['A']['beats'] = [tiny]
        song['score']['patterns']['B']['beats'] = []
        song['score']['ties'] = []
        source, source_raw = copy.deepcopy(song), copy.deepcopy(raw)
        with self.assertRaisesRegex(ValueError, 'not representable'):
            tab.project_score(song, raw)
        plan = tab.playback_plan(song, raw, 48000)
        on, off = plan['events']
        self.assertEqual(on['at'], [1, 13])
        self.assertEqual(off['at'], [15, 104])
        self.assertEqual(on['seconds'], [1, 26])
        self.assertEqual(plan['positions'][0]['row'], [12, 13])
        self.assertEqual(plan['positions'][0]['end_row'], [45, 26])
        self.assertEqual(on['frame'], round(Fraction(48000, 26)))
        self.assertEqual(off['frame'], round(Fraction(15, 208) * 48000))
        self.assertEqual(on['id'], 'oa/n13')
        self.assertEqual(on['instrument'], 1)
        json.dumps(plan)
        self.assertEqual(song, source)
        self.assertEqual(raw, source_raw)

    def test_exact_plan_long_run_rounds_absolute_time_without_accumulating_drift(self):
        song, _ = plan_fixture()
        song['module'].update(speed=6, tempo=137)
        song['patterns'] = {'A': {'rows': 200, 'data': ''}}
        song['orders'] = ['A'] * 255
        song['score']['order_ids'] = [f'occ_{i}' for i in range(255)]
        song['score']['ties'] = []
        song['score']['patterns'] = {'A': {'row_step': [1, 4], 'beats': [
            beat('pulse', [1, 13], [note('pulse_n', 60, 2, 1)], 8, [13, 8])]}}
        raw = [Pattern('A', [[Cell() for _ in range(7)] for _ in range(200)])]
        plan = tab.playback_plan(song, raw)
        attacks = [event for event in plan['events'] if event['type'] == 'note_on']
        self.assertEqual(len(attacks), 255)
        def nearest(value):
            return value.numerator // value.denominator + (2 * (value.numerator % value.denominator) >= value.denominator)
        for i, event in enumerate(attacks):
            exact = (50 * i + Fraction(1, 13)) * Fraction(60, 137) * 44100
            self.assertEqual(event['frame'], nearest(exact))
            self.assertLessEqual(abs(Fraction(event['frame']) - exact), Fraction(1, 2))
        accumulated = attacks[0]['frame'] + 254 * nearest(Fraction(50 * 60 * 44100, 137))
        self.assertGreater(abs(accumulated - attacks[-1]['frame']), 1)

    def test_exact_plan_ties_are_occurrence_specific_and_final_release_is_explicit(self):
        song, raw = plan_fixture()
        song['orders'].append('A')
        song['score']['order_ids'].append('oa2')
        with self.assertRaisesRegex(ValueError, 'occurrence-dependent tie'):
            tab.project_score(song, raw)
        plan = tab.playback_plan(song, raw, 48000)
        tails = [e for e in plan['events'] if e['note'] == 'tailn']
        self.assertEqual([(e['id'], e['type'], e['at']) for e in tails], [
            ('oa/tailn', 'note_on', [7, 2]), ('oa/tailn', 'note_off', [9, 2]),
            ('oa2/tailn', 'note_on', [23, 2]), ('oa2/tailn', 'note_off', [12, 1])])
        head = next(p for p in plan['positions'] if p['id'] == 'ob/headn')
        self.assertTrue(head['tied_in'])
        self.assertEqual(head['attack_id'], 'oa/tailn')
        self.assertFalse(any(e['id'] == 'ob/headn' for e in plan['events']))
        self.assertEqual(plan['duration']['frames'], 288000)
        self.assertEqual(tails[-1]['frame'], plan['duration']['frames'])

    def test_exact_plan_chords_and_equal_frame_noteoffs_precede_noteons(self):
        song, raw = plan_fixture()
        song['score']['patterns']['A']['beats'][0]['notes'][0]['volume'] = 37
        plan = tab.playback_plan(song, raw, 48000)
        first = [e for e in plan['events'] if e['frame'] == 0 and e['type'] == 'note_on']
        self.assertEqual({e['pitch'] for e in first}, {40, 60, 64, 67})
        self.assertEqual(next(e['volume'] for e in first if e['note'] == 'c'), 37)
        at_boundary = [e['type'] for e in plan['events'] if e['frame'] == 24000]
        self.assertEqual(at_boundary, ['note_off', 'note_off', 'note_off', 'note_on'])
        # The same rule applies when distinct rational times round to one frame.
        song['score']['patterns']['A']['beats'] = [
            beat('early', [0, 1], [note('early_n', 60, 2, 1)]),
            beat('late', [1000001, 1000000], [note('late_n', 60, 2, 1)])]
        # Fraction input bound is 1,000,000; use an equivalent bounded onset.
        song['score']['patterns']['A']['beats'][1]['at'] = [1000000, 999999]
        song['score']['ties'] = []
        later = tab.playback_plan(song, raw, 48000)
        boundary = [e for e in later['events'] if e['frame'] == 24000]
        self.assertEqual([e['type'] for e in boundary], ['note_off', 'note_on'])

    def test_exact_plan_instrument_inheritance_resolves_prior_raw_state_or_refuses(self):
        song, raw = plan_fixture()
        song['score']['patterns']['A']['beats'] = [beat('inherit', [1, 1], [dict(note('in', 64, 1, 0), instrument=0)])]
        song['score']['patterns']['B']['beats'] = []
        song['score']['ties'] = []
        with self.assertRaisesRegex(ValueError, 'inheritance 0 has no preceding'):
            tab.playback_plan(song, raw)
        raw[0].rows[0][0].instrument = 1
        plan = tab.playback_plan(song, raw)
        attack = next(e for e in plan['events'] if e['type'] == 'note_on')
        self.assertEqual(attack['instrument'], 1)
        self.assertEqual(attack['source_instrument'], 0)
        self.assertTrue(attack['instrument_inherited'])
        self.assertIsNone(attack['volume'])
        self.assertTrue(plan['diagnostics'])
        raw[0].rows[0][0].instrument = 2
        with self.assertRaisesRegex(ValueError, 'no declared instrument/sample'):
            tab.playback_plan(song, raw)

    def test_exact_plan_rejects_raw_controls_and_same_channel_sustain_conflicts(self):
        song, raw = plan_fixture()
        for effect, param in [(1, 6), (20, 0x1f), (2, 0), (3, 1), (19, 0xB0), (19, 0xE1)]:
            changed = copy.deepcopy(raw)
            changed[0].rows[30][6].effect, changed[0].rows[30][6].param = effect, param
            with self.subTest(effect=effect, param=param), self.assertRaisesRegex(ValueError, 'tempo/speed/flow'):
                tab.playback_plan(song, changed)
        changed = copy.deepcopy(raw)
        changed[0].rows[30][6] = parse_cell('... .. ... X40')
        self.assertEqual(tab.playback_plan(song, changed)['events'], tab.playback_plan(song, raw)['events'])
        for cell in (Cell(note=60), Cell(note=NOTE_OFF), Cell(instrument=1)):
            changed = copy.deepcopy(raw)
            changed[0].rows[1][1] = cell
            with self.subTest(cell=cell), self.assertRaisesRegex(ValueError, 'conflicts with score sustain'):
                tab.playback_plan(song, changed)
        # A residual attack outside the sustain remains backing material, not a
        # duplicate scheduled attack, and does not mutate its source.
        changed = copy.deepcopy(raw)
        changed[0].rows[30][1] = Cell(note=62, instrument=1)
        result = tab.playback_plan(song, changed)
        self.assertTrue(result['diagnostics'])
        self.assertFalse(any(e['pitch'] == 62 for e in result['events']))
        self.assertEqual(changed[0].rows[30][1].note, 62)

    def test_exact_plan_keeps_absolute_global_volume_in_backing_only(self):
        song, raw = plan_fixture()
        expected = tab.playback_plan(song, raw, 48000)
        for row, channel, value in ((0, 0, 0), (1, 1, 64), (30, 6, 128)):
            raw[0].rows[row][channel].effect = 22
            raw[0].rows[row][channel].param = value
        before = copy.deepcopy(raw)
        actual = tab.playback_plan(song, raw, 48000)
        self.assertEqual(actual['events'], expected['events'])
        self.assertEqual(actual['duration'], expected['duration'])
        self.assertEqual(raw, before)
        for cell in (Cell(effect=22, param=129), Cell(effect=22, param=255),
                     Cell(effect=13, param=65), Cell(volcmd=65), Cell(volcmd=128),
                     Cell(effect=8, param=64)):
            changed = copy.deepcopy(raw)
            changed[0].rows[30][6] = cell
            with self.subTest(cell=cell), self.assertRaisesRegex(ValueError, 'raw effect/volume'):
                tab.playback_plan(song, changed, 48000)

    def test_exact_plan_admits_qualified_parent_batch_commands_without_rewriting_source(self):
        song, raw = plan_fixture()
        expected = tab.playback_plan(song, raw, 48000)
        for cell in (Cell(effect=24, param=0), Cell(effect=24, param=255),
                     Cell(effect=13, param=0), Cell(effect=13, param=64),
                     Cell(effect=4, param=0), Cell(effect=4, param=7), Cell(effect=4, param=255),
                     Cell(volcmd=0), Cell(volcmd=64), Cell(effect=22, param=64, volcmd=32)):
            changed = copy.deepcopy(raw)
            changed[0].rows[30][6] = cell
            before = copy.deepcopy(changed)
            with self.subTest(cell=cell):
                self.assertEqual(tab.playback_plan(song, changed, 48000)['events'], expected['events'])
                self.assertEqual(changed, before)

    def test_qualified_volume_does_not_override_score_owned_attack_volume(self):
        song, raw = plan_fixture()
        song['score']['patterns']['A']['beats'][0]['notes'][0]['volume'] = 37
        for volume in (23, 37):
            raw[0].rows[0][1].volcmd = volume
            with self.subTest(volume=volume), self.assertRaisesRegex(ValueError, 'score-owned attack volume'):
                tab.playback_plan(song, raw)
        raw[0].rows[0][1].volcmd = None
        raw[0].rows[1][1].volcmd = 23
        self.assertTrue(tab.playback_plan(song, raw)['events'])  # Later residual volume commands remain allowed.

    def test_exact_plan_reuses_measure_checks_and_refuses_zero_frame_notes(self):
        song, raw = plan_fixture()
        song['score']['measures'] = [{'id': 'm', 'from': {'occurrence': 'oa', 'at': [0, 1]},
                                    'to': {'occurrence': 'oa', 'at': [4, 1]}, 'meter': [5, 4]}]
        with self.assertRaisesRegex(ValueError, 'does not match its meter'):
            tab.playback_plan(song, raw)
        song['score']['measures'] = []
        song['score']['ties'] = []
        song['score']['patterns']['A']['beats'] = [beat('tiny', [0, 1], [note('tiny_n', 60, 2, 1)], 64, [1000000, 1])]
        song['score']['patterns']['B']['beats'] = []
        with self.assertRaisesRegex(ValueError, 'zero sample frames'):
            tab.playback_plan(song, raw, 8000)

    def test_exact_plan_half_frame_rounding_is_explicit_half_up(self):
        song, raw = plan_fixture()
        song['score']['ties'] = []
        song['score']['patterns']['A']['beats'] = [
            beat('half_frame', [1, 48000], [note('half_n', 60, 2, 1)], 8)]
        song['score']['patterns']['B']['beats'] = []
        plan = tab.playback_plan(song, raw, 48000)
        self.assertEqual([event['frame'] for event in plan['events']], [1, 12001])

    def test_pattern_authoring_aligned_fields_preserve_raw_source_and_inheritance(self):
        song, raw = fixture()
        chord = song['score']['patterns']['A']['beats'][0]
        chord['notes'][0].update(instrument=0, volume=37)
        raw[0].rows[0][0].volcmd = 23  # This note has no authored volume; the raw field remains raw.
        view = tab.authoring_view(song, raw)
        before = copy.deepcopy((song, raw, view))
        result = tab.pattern_authoring_view(song, raw, 0, 'oa', view=view)
        fields = {(b['row'], b['ch'], b['field']): b for b in result['bindings']}
        self.assertEqual(fields[0, 1, 'instrument']['value'], 0)
        self.assertEqual(fields[0, 1, 'volcmd']['value'], 37)
        self.assertNotIn((0, 0, 'volcmd'), fields)
        self.assertEqual(fields[0, 1, 'note'], dict(row=0, ch=1, field='note', role='attack',
            occurrence='oa', pattern='A', beat='chord', note='c', value=60))
        self.assertEqual(len(fields), len(result['bindings']))
        cell = parse_cell(result['display_rows'][0][1])
        self.assertEqual((cell.note, cell.instrument, cell.volcmd, cell.effect, cell.param), (60, 0, 37, 24, 64))
        self.assertEqual(parse_cell(result['display_rows'][0][0]).volcmd, 23)
        self.assertEqual(result['rows'], [[format_cell(c) for c in row] for row in raw[0].rows])
        self.assertEqual({p['occurrence'] for p in result['positions'] + result['ownership']}, {'oa'})
        self.assertEqual(json.loads(json.dumps(result)), result)
        result['positions'][0]['written']['dots'] = 2
        result['ownership'][0]['fields'].append('effect')
        result['display_rows'][0][0] = 'changed'
        self.assertEqual((song, raw, view), before)

    def test_pattern_authoring_fractional_attacks_and_releases_never_round(self):
        for at, expected_fields in (([1, 13], []), ([0, 1], ['instrument', 'note'])):
            song, raw = fixture()
            song['score']['ties'] = []
            song['score']['patterns']['A']['beats'] = [
                beat('thirteen', at, [note('n13', 60, 2, 1)], 8, [13, 8])]
            result = tab.pattern_authoring_view(song, raw, 0, 'oa')
            position = next(p for p in result['positions'] if p['kind'] == 'note')
            self.assertEqual(position['row'], tab._pair(Fraction(*at) * 12))
            self.assertEqual(position['end_row'], tab._pair((Fraction(*at) + Fraction(4, 13)) * 12))
            self.assertEqual([b['field'] for b in result['bindings']], expected_fields)
            self.assertFalse(any(b['role'] == 'release' for b in result['bindings']))
            if at[0]:
                self.assertEqual(result['display_rows'], result['rows'])
            self.assertEqual(raw[0].rows[0][1].note, None)

    def test_pattern_authoring_repeated_occurrences_keep_different_tie_bindings(self):
        song, raw = fixture()
        song['orders'].append('B')
        song['score']['order_ids'].append('ob2')
        tied = tab.pattern_authoring_view(song, raw, 1, 'ob')
        restruck = tab.pattern_authoring_view(song, raw, 1, 'ob2')
        self.assertEqual([(b['row'], b['role'], b['occurrence']) for b in tied['bindings']], [(6, 'release', 'ob')])
        self.assertEqual([(b['row'], b['role']) for b in restruck['bindings']],
                         [(0, 'attack'), (0, 'attack'), (6, 'release')])
        left = next(p for p in tied['positions'] if p['kind'] == 'note')
        right = next(p for p in restruck['positions'] if p['kind'] == 'note')
        self.assertEqual((left['id'], left['attack_id'], left['tied_in']), ('ob/headn', 'oa/tailn', True))
        self.assertEqual((right['id'], right['attack_id'], right['tied_in']), ('ob2/headn', 'ob2/headn', False))
        self.assertEqual(parse_cell(tied['display_rows'][0][0]).note, None)
        self.assertEqual(parse_cell(restruck['display_rows'][0][0]).note, 64)

    def test_pattern_authoring_boundary_release_retains_source_and_yields_to_attacks(self):
        song, raw = fixture()
        song['score']['ties'] = []
        song['score']['patterns']['A']['beats'] = [song['score']['patterns']['A']['beats'][-2]]
        head = copy.deepcopy(song['score']['patterns']['B']['beats'])
        song['score']['patterns']['B']['beats'] = []
        result = tab.pattern_authoring_view(song, raw, 1, 'ob')
        self.assertEqual(result['bindings'], [dict(row=0, ch=0, field='note', role='release',
            occurrence='oa', pattern='A', beat='tail', note='tailn', value=NOTE_OFF, readonly=True)])
        self.assertEqual(result['positions'], [])
        self.assertEqual(result['ownership'], [])
        self.assertEqual(parse_cell(result['display_rows'][0][0]).note, NOTE_OFF)
        self.assertIsNone(raw[1].rows[0][0].note)
        song['score']['patterns']['B']['beats'] = head
        replaced = tab.pattern_authoring_view(song, raw, 1, 'ob')
        self.assertEqual({b['role'] for b in replaced['bindings'] if b['row'] == 0}, {'attack'})
        self.assertTrue(all(b['occurrence'] == 'ob' for b in replaced['bindings']))
        song['score']['patterns']['B']['beats'] = []
        raw[1].rows[0][0] = Cell(note=64, instrument=1)
        replaced = tab.pattern_authoring_view(song, raw, 1, 'ob')
        self.assertEqual(replaced['bindings'], [])
        self.assertEqual(replaced['display_rows'], replaced['rows'])
        song['orders'], song['score']['order_ids'] = ['A'], ['oa']
        final = tab.pattern_authoring_view(song, raw, 0, 'oa')
        self.assertFalse(any(b['role'] == 'release' for b in final['bindings']))
        self.assertEqual(final['ownership'][0]['end_row'], [48, 1])

    def test_pattern_authoring_conflicts_do_not_overwrite_or_claim_raw_fields(self):
        song, raw = fixture()
        song['score']['patterns']['A']['beats'][0]['notes'][0]['volume'] = 37
        raw[0].rows[0][1] = Cell(note=61, instrument=2, volcmd=9, effect=24, param=64)
        raw[0].rows[12][1] = Cell(note=NOTE_OFF)
        before = copy.deepcopy((song, raw))
        result = tab.pattern_authoring_view(song, raw, 0, 'oa')
        for row in (0, 12):
            self.assertEqual(result['display_rows'][row][1], result['rows'][row][1])
            self.assertFalse(any(b['row'] == row and b['ch'] == 1 for b in result['bindings']))
        fields = {f for c in result['conflicts'] if c['row'] == [0, 1] and c['ch'] == 1 for f in c['fields']}
        self.assertEqual(fields, {'note', 'instrument', 'volcmd'})
        self.assertTrue(any(c['row'] == [12, 1] and c['fields'] == ['note'] for c in result['conflicts']))
        self.assertEqual((song, raw), before)

    def test_pattern_authoring_requires_matching_played_occurrence(self):
        song, raw = fixture()
        for index, occurrence, message in [(0, None, 'explicit played'), (0, 'missing', 'unknown occurrence'),
                                           (0, 'ob', 'does not match'), (2, 'oa', 'pattern index'),
                                           (True, 'oa', 'pattern index')]:
            with self.subTest(index=index, occurrence=occurrence), self.assertRaisesRegex(ValueError, message):
                tab.pattern_authoring_view(song, raw, index, occurrence)
        view = tab.authoring_view(song, raw)
        view['occurrences'][0]['pattern'] = 'B'
        with self.assertRaisesRegex(ValueError, 'view does not match'):
            tab.pattern_authoring_view(song, raw, 0, 'oa', view=view)
        song['orders'], song['score']['order_ids'], song['score']['ties'] = ['A'], ['oa'], []
        with self.assertRaisesRegex(ValueError, 'explicit played'):
            tab.pattern_authoring_view(song, raw, 1, None)

    def test_native_pattern_edits_aligned_fields_leave_fractional_notes_and_raw_cells_untouched(self):
        song, raw = fixture()
        beats = song['score']['patterns']['A']['beats']
        beats[1:4] = [beat('thirteen', [14, 13], [note('n13', 64, 1, 0)], 8, [13, 8])]
        beats[0]['notes'][0]['volume'] = 37
        view = tab.authoring_view(song, raw)
        shown = tab.pattern_authoring_view(song, raw, 0, 'oa', view=view)
        cell = parse_cell(shown['display_rows'][0][1])
        cell.note, cell.instrument, cell.volcmd = 62, 0, 19
        groups = [(0, [dict(row=0, ch=1, cell=format_cell(cell))])]
        before = copy.deepcopy((song, raw, groups, view))
        score, residual = tab.translate_native_pattern_edits(song, raw, groups, view=view)
        changed = score['patterns']['A']['beats'][0]['notes'][0]
        self.assertEqual((changed['pitch'], changed['instrument'], changed['volume']), (62, 0, 19))
        self.assertEqual(score['patterns']['A']['beats'][1], beats[1])
        self.assertEqual(residual, [])
        self.assertEqual((song, raw, groups, view), before)

    def test_native_pattern_edits_strip_untouched_bindings_from_residual_effect_changes(self):
        song, raw = fixture()
        shown = tab.pattern_authoring_view(song, raw, 0, 'oa')
        cell = parse_cell(shown['display_rows'][0][1])
        cell.effect, cell.param = 8, 33
        score, residual = tab.translate_native_pattern_edits(song, raw, [(0, [dict(row=0, ch=1, cell=format_cell(cell))])])
        self.assertIsNone(score)
        self.assertEqual(len(residual), 1)
        stored = parse_cell(residual[0][1][0]['cell'])
        self.assertEqual(stored, Cell(effect=8, param=33))
        # A truly raw insertion remains raw and creates no score identity.
        score, residual = tab.translate_native_pattern_edits(song, raw, [(0, [dict(row=30, ch=6, cell='C-3 01 ... ...')])])
        self.assertIsNone(score)
        self.assertEqual(parse_cell(residual[0][1][0]['cell']), Cell(note=36, instrument=1))

    def test_native_pattern_edits_delete_owned_attack_and_preserve_tie_protection(self):
        song, raw = fixture()
        song['score']['patterns']['A']['beats'][0]['notes'][0]['volume'] = 37
        score, residual = tab.translate_native_pattern_edits(song, raw, [(0, [dict(row=0, ch=1, cell='... .. ... X40')])])
        self.assertEqual(residual, [])
        self.assertEqual([n['id'] for n in score['patterns']['A']['beats'][0]['notes']], ['e', 'g'])
        before = copy.deepcopy((song, raw))
        with self.assertRaisesRegex(ValueError, 'tie'):
            tab.translate_native_pattern_edits(song, raw, [(0, [dict(row=42, ch=0, cell='... .. ... ...')])])
        self.assertEqual((song, raw), before)

    def test_native_pattern_edits_boundary_release_identity_and_occurrence_context(self):
        song, raw = fixture()
        song['score']['ties'] = []
        song['score']['patterns']['A']['beats'] = [song['score']['patterns']['A']['beats'][-2]]
        song['score']['patterns']['B']['beats'] = []
        score, residual = tab.translate_native_pattern_edits(song, raw, [(1, [dict(row=0, ch=0, cell='=== .. ... V40')])])
        self.assertIsNone(score)
        self.assertEqual(parse_cell(residual[0][1][0]['cell']), Cell(effect=22, param=64))
        with self.assertRaisesRegex(ValueError, 'generated release'):
            tab.translate_native_pattern_edits(song, raw, [(1, [dict(row=0, ch=0, cell='... .. ... ...')])])
        song['orders'].append('B')
        song['score']['order_ids'].append('ob2')
        groups = [(1, [dict(row=0, ch=0, cell='... .. ... V40')])]
        with self.assertRaisesRegex(ValueError, 'explicit occurrence'):
            tab.translate_native_pattern_edits(song, raw, groups)
        with self.assertRaisesRegex(ValueError, 'generated release'):
            tab.translate_native_pattern_edits(song, raw, groups, occurrences={1: 'ob'})
        score, residual = tab.translate_native_pattern_edits(song, raw, groups, occurrences={1: 'ob2'})
        self.assertIsNone(score)
        self.assertEqual(parse_cell(residual[0][1][0]['cell']), Cell(effect=22, param=64))
        with self.assertRaisesRegex(ValueError, 'does not match'):
            tab.translate_native_pattern_edits(song, raw, groups, occurrences={1: 'oa'})

    def test_native_pattern_edits_repeated_pattern_changes_shared_source_only_with_context(self):
        song, raw = fixture()
        song['orders'].append('A')
        song['score']['order_ids'].append('oa2')
        cell = parse_cell(tab.pattern_authoring_view(song, raw, 0, 'oa2')['display_rows'][0][1])
        cell.note = 62
        groups = [(0, [dict(row=0, ch=1, cell=format_cell(cell))])]
        with self.assertRaisesRegex(ValueError, 'explicit occurrence'):
            tab.translate_native_pattern_edits(song, raw, groups)
        score, residual = tab.translate_native_pattern_edits(song, raw, groups, occurrences={0: 'oa2'})
        self.assertEqual(residual, [])
        candidate = dict(song, score=score)
        self.assertEqual([p['pitch'] for p in tab.authoring_view(candidate, raw)['positions']
                          if p['kind'] == 'note' and p['note'] == 'c'], [62, 62])
        with self.assertRaisesRegex(ValueError, 'tie'):
            tab.translate_native_pattern_edits(song, raw, [(0, [dict(row=42, ch=0, cell='... .. ... ...')])],
                                               occurrences={0: 'oa2'})

    def test_native_pattern_edits_refuse_sustain_conflicts_and_ambiguous_moves_atomically(self):
        song, raw = fixture()
        cell = parse_cell(tab.pattern_authoring_view(song, raw, 0, 'oa')['display_rows'][0][1])
        cell.note = 62
        for conflicting in ('C-5 01 ... ...', '... 01 ... ...'):
            groups = [(0, [dict(row=0, ch=1, cell=format_cell(cell)), dict(row=1, ch=1, cell=conflicting)])]
            before = copy.deepcopy((song, raw, groups))
            with self.subTest(conflicting=conflicting), self.assertRaisesRegex(ValueError, 'conflicts with score sustain'):
                tab.translate_native_pattern_edits(song, raw, groups)
            self.assertEqual((song, raw, groups), before)
        with self.assertRaisesRegex(ValueError, 'ambiguous score-note deletion'):
            tab.translate_native_pattern_edits(song, raw, [(0, [
                dict(row=0, ch=1, cell='... .. ... X40'), dict(row=30, ch=1, cell='C-5 01 ... ...')])])
        with self.assertRaisesRegex(ValueError, 'generated release'):
            tab.translate_native_pattern_edits(song, raw, [(0, [dict(row=12, ch=1, cell='... .. ... ...')])])
        with self.assertRaisesRegex(ValueError, 'duplicate cell'):
            tab.translate_native_pattern_edits(song, raw, [(0, [dict(row=30, ch=1, cell='... .. ... ...')])] * 2)

    def test_native_gestures_move_and_resize_exact_rows_using_backing_module(self):
        song, raw = fixture()
        song['score']['ties'] = []
        source = beat('thirteen', [1, 13], [note('n13', 64, 1, 0)], 8, [13, 8])
        song['score']['patterns']['A']['beats'] = [source]
        backing = Module(patterns=raw)
        before = copy.deepcopy((song, raw))
        moved = tab.move_beat(song, backing, 0, 'thirteen', [25, 13])  # Original row 12/13 plus one.
        moved_beat = moved['score']['patterns']['A']['beats'][0]
        self.assertEqual(moved_beat, dict(source, at=[25, 156]))
        moved_note = tab.move_note(song, backing, 0, 'n13', [25, 13], pitch=65)
        changed = moved_note['score']['patterns']['A']['beats'][0]
        self.assertEqual((changed['id'], changed['at'], changed['notes'][0]['id']), ('thirteen', [25, 156], 'n13'))
        self.assertEqual((changed['notes'][0]['pitch'], changed['notes'][0]['fret']), (65, 1))
        resized = tab.resize_beat(song, backing, 0, 'thirteen', [36, 13])
        resized_beat = resized['score']['patterns']['A']['beats'][0]
        self.assertEqual(resized_beat['at'], [1, 13])
        self.assertEqual(tab.duration_quarters(resized_beat['written']), Fraction(2, 13))
        self.assertEqual(resized_beat['notes'], source['notes'])
        for candidate in (moved, moved_note, resized):
            self.assertFalse(tab.authoring_view(candidate, raw)['conflicts'])
        self.assertEqual((song, raw), before)

    def test_native_gestures_paste_fractional_clipboard_without_projected_cells(self):
        from types import SimpleNamespace
        song, raw = fixture()
        song['score']['ties'] = []
        song['score']['patterns']['A']['beats'] = [
            beat('thirteen', [1, 13], [note('n13', 64, 1, 0)], 8, [13, 8])]
        song['score']['patterns']['B']['beats'] = []
        clipboard = tab.capture_score_clipboard(song, 'A', ['thirteen'])
        before = copy.deepcopy((song, raw, clipboard))
        for row, at in (([25, 13], [25, 156]), (12, [1, 1])):
            candidate = tab.paste_score_clipboard(song, SimpleNamespace(patterns=raw), 1, row, clipboard, 'ob')
            pasted = candidate['score']['patterns']['B']['beats'][0]
            self.assertEqual(pasted['at'], at)
            self.assertEqual(pasted['written'], clipboard['beats'][0]['written'])
            self.assertEqual((pasted['id'], pasted['notes'][0]['id']), ('copy_thirteen', 'copy_n13'))
            self.assertFalse(tab.authoring_view(candidate, raw)['conflicts'])
        self.assertEqual((song, raw, clipboard), before)

    def test_native_gestures_fractional_bounds_and_existing_refusals(self):
        song, raw = fixture()
        backing = Module(patterns=raw)
        with self.assertRaisesRegex(ValueError, 'one chord note'):
            tab.move_note(song, backing, 0, 'c', [25, 13])
        with self.assertRaisesRegex(ValueError, 'tied note'):
            tab.move_beat(song, backing, 0, 'tail', [25, 13])
        with self.assertRaisesRegex(ValueError, 'tied beat'):
            tab.resize_beat(song, backing, 0, 'tail', [47, 1])
        song['score']['ties'] = []
        song['score']['patterns']['A']['beats'] = [beat('tiny', [0, 1], [note('tiny_n', 64, 1, 0)], 64, [13, 8])]
        clipboard = tab.capture_score_clipboard(song, 'A', ['tiny'])
        before = copy.deepcopy((song, raw))
        moved = tab.move_note(song, backing, 0, 'tiny_n', [95, 2])
        resized = tab.resize_beat(moved, backing, 0, 'tiny', [48, 1])
        position = next(p for p in tab.authoring_view(resized, raw)['positions'] if p['kind'] == 'note' and p['note'] == 'tiny_n')
        self.assertEqual((position['row'], position['end_row']), ([95, 2], [48, 1]))
        for value in (True, 1.5, [-1, 2], [1, 0], [1.5, 2], [48, 1], [97, 2]):
            for operation in (lambda: tab.move_beat(song, backing, 0, 'tiny', value),
                              lambda: tab.move_note(song, backing, 0, 'tiny_n', value),
                              lambda: tab.paste_score_clipboard(song, backing, 0, value, clipboard)):
                with self.subTest(value=value), self.assertRaises(ValueError):
                    operation()
        for value in ([0, 1], [97, 2], [1, 0], 1.5):
            with self.subTest(end=value), self.assertRaises(ValueError):
                tab.resize_beat(song, backing, 0, 'tiny', value)
        with self.assertRaisesRegex(ValueError, 'without rounding'):
            tab.resize_beat(song, backing, 0, 'tiny', [1, 17])
        self.assertEqual((song, raw), before)

    def test_native_gestures_fractional_paste_preserves_internal_ties(self):
        song, raw = fixture()
        song['score']['patterns']['A']['beats'] = [
            beat('one', [0, 1], [note('n1', 64, 1, 0)], 8, [13, 8]),
            beat('two', [4, 13], [note('n2', 64, 1, 0)], 8, [13, 8])]
        song['score']['patterns']['B']['beats'] = []
        song['score']['ties'] = [{'from': {'occurrence': 'oa', 'note': 'n1'},
                                  'to': {'occurrence': 'oa', 'note': 'n2'}}]
        clipboard = tab.capture_score_clipboard(song, 'A', ['one', 'two'], 'oa')
        candidate = tab.paste_score_clipboard(song, Module(patterns=raw), 1, [25, 13], clipboard, 'ob')
        notes = [p for p in tab.authoring_view(candidate, raw)['positions']
                 if p['kind'] == 'note' and p['occurrence'] == 'ob']
        self.assertEqual([p['row'] for p in notes], [[25, 13], [73, 13]])
        self.assertEqual([p['attack_id'] for p in notes], ['ob/copy_n1', 'ob/copy_n1'])
        self.assertEqual([p['tied_in'] for p in notes], [False, True])

    def test_authoring_view_exact_tuplet_rest_and_no_generated_cells(self):
        song, raw = fixture()
        song['score']['ties'] = []
        tiny = beat('thirteen', [1, 13], [note('n13', 60, 2, 1)], 64, [13, 8])
        tiny['written']['dots'] = 2
        song['score']['patterns']['A']['beats'] = [tiny, beat('silence', [2, 1], [], 8, [13, 8])]
        before = copy.deepcopy((song, raw))
        view = tab.authoring_view(song, raw)
        position = next(p for p in view['positions'] if p['kind'] == 'note' and p['note'] == 'n13')
        self.assertEqual((position['at'], position['duration'], position['end']), ([1, 13], [7, 104], [15, 104]))
        self.assertEqual((position['row'], position['end_row']), ([12, 13], [45, 26]))
        self.assertEqual((position['id'], position['attack_id']), ('oa/n13', 'oa/n13'))
        rest = next(p for p in view['positions'] if p['kind'] == 'beat' and p['rest'])
        self.assertEqual((rest['id'], rest['duration']), ('oa/silence', [4, 13]))
        self.assertFalse(any(o['beat'] == 'silence' for o in view['ownership']))
        self.assertNotIn('patterns', view)
        self.assertNotIn('events', view)
        self.assertEqual(json.loads(json.dumps(view)), view)
        view['positions'][0]['written']['dots'] = 0
        self.assertEqual((song, raw), before)
        with self.assertRaisesRegex(ValueError, 'not representable'):
            tab.project_score(song, raw)
        self.assertTrue(tab.playback_plan(song, raw)['events'])  # X40 is now qualified; exact timing stays native.

    def test_authoring_view_occurrence_ties_and_final_release_match_plan(self):
        song, raw = plan_fixture()
        song['orders'].append('A')
        song['score']['order_ids'].append('oa2')
        view, plan = tab.authoring_view(song, raw), tab.playback_plan(song, raw)
        positions = {p['id']: p for p in view['positions'] if p['kind'] == 'note'}
        for planned in plan['positions']:
            for key in ('occurrence', 'pattern', 'beat', 'note', 'ch', 'at', 'end', 'row', 'end_row',
                        'local_at', 'attack_id', 'tied_in', 'tied_out', 'source_instrument', 'volume'):
                self.assertEqual(positions[planned['id']][key], planned[key], (planned['id'], key))
        owners = {o['id']: o for o in view['ownership']}
        self.assertFalse(owners['oa/tailn']['release'])
        self.assertFalse(owners['ob/headn']['attack'])
        self.assertEqual(owners['ob/headn']['attack_id'], 'oa/tailn')
        self.assertTrue(owners['oa2/tailn']['release'])
        self.assertEqual(owners['oa2/tailn']['end'], view['duration'])
        self.assertEqual(view['duration'], [12, 1])
        with self.assertRaisesRegex(ValueError, 'occurrence-dependent tie'):
            tab.project_score(song, raw)
        # A final release alone is also authorable without an extra tracker row.
        song['orders'], song['score']['order_ids'] = ['A'], ['oa']
        song['score']['ties'] = []
        self.assertEqual(tab.authoring_view(song, raw)['duration'], [4, 1])
        # The standalone IT ends there, so the release needs no note-off row (the module's end releases it).
        final = tab.project_score(song, raw)
        self.assertTrue(final.patterns)   # projects instead of refusing

    def test_authoring_view_rejects_invalid_timeline_semantics(self):
        for case, message in [('voice', 'overlapping beats'), ('channel', 'independent channels'),
                              ('bounds', 'outside pattern'), ('tie_gap', 'adjacent'),
                              ('tie_identity', 'unknown note'), ('tie_pitch', 'tie continuity'),
                              ('measure', 'does not match its meter')]:
            song, raw = plan_fixture()
            beats = song['score']['patterns']['A']['beats']
            if case == 'voice':
                beats.append(beat('overlapping_rest', [0, 1], []))
            elif case == 'channel':
                beats[0]['notes'][2]['channel'] = 0
            elif case == 'bounds':
                beats[-2]['at'] = [4, 1]
            elif case == 'tie_gap':
                song['score']['patterns']['B']['beats'][0]['at'] = [1, 1]
            elif case == 'tie_identity':
                song['score']['ties'][0]['to']['note'] = 'missing'
            elif case == 'tie_pitch':
                song['score']['patterns']['B']['beats'][0]['notes'][0].update(pitch=65, fret=1)
            else:
                song['score']['measures'] = [{'id': 'm', 'from': {'occurrence': 'oa', 'at': [0, 1]},
                    'to': {'occurrence': 'oa', 'at': [4, 1]}, 'meter': [5, 4]}]
            with self.subTest(case=case), self.assertRaisesRegex(ValueError, message):
                tab.authoring_view(song, raw)

    def test_authoring_conflicts_are_occurrence_addressed_but_planner_still_refuses(self):
        song, raw = plan_fixture()
        song['orders'].append('A')
        song['score']['order_ids'].append('oa2')
        raw[0].rows[1][1] = Cell(note=61, instrument=1)
        before = copy.deepcopy(raw)
        view = tab.authoring_view(song, raw)
        self.assertEqual([(c['id'], c['at'], c['row'], c['fields']) for c in view['conflicts']], [
            ('oa/c', [1, 12], [1, 1], ['note', 'instrument']),
            ('oa2/c', [97, 12], [1, 1], ['note', 'instrument'])])
        self.assertEqual(raw, before)
        self.assertTrue(view['diagnostics'])
        with self.assertRaisesRegex(ValueError, 'conflicts with score sustain'):
            tab.playback_plan(song, raw)

    def test_authoring_checks_unused_pattern_bounds_and_channel_overlap(self):
        for problem in ('bounds', 'channel'):
            song, raw = plan_fixture()
            song['orders'], song['score']['order_ids'], song['score']['ties'] = ['A'], ['oa'], []
            if problem == 'bounds':
                song['score']['patterns']['B']['beats'][0]['at'] = [4, 1]
            else:
                song['score']['patterns']['B']['beats'][0]['notes'].append(
                    dict(note('other_n', 60, 2, 1), channel=0))
            with self.subTest(problem=problem), self.assertRaises(ValueError):
                tab.authoring_view(song, raw)

    def test_authoring_is_not_subject_to_sample_frame_quantization(self):
        song, raw = plan_fixture()
        song['score']['ties'] = []
        song['score']['patterns']['A']['beats'] = [
            beat('tiny', [0, 1], [note('tiny_n', 60, 2, 1)], 64, [1000000, 1])]
        song['score']['patterns']['B']['beats'] = []
        view = tab.authoring_view(song, raw)
        self.assertEqual(view['positions'][0]['duration'], [1, 16000000])
        with self.assertRaisesRegex(ValueError, 'zero sample frames'):
            tab.playback_plan(song, raw, 8000)

    def test_authoring_view_does_not_interpret_controls_or_invent_instrument_memory(self):
        song, raw = plan_fixture()
        song['score']['ties'] = []
        song['score']['patterns']['A']['beats'] = [beat('inherit', [0, 1],
            [dict(note('inherited', 64, 1, 0), instrument=0)])]
        song['score']['patterns']['B']['beats'] = []
        inherited = next(p for p in tab.authoring_view(song, raw)['positions'] if p['kind'] == 'note')
        self.assertEqual(inherited['source_instrument'], 0)
        self.assertNotIn('instrument', inherited)
        self.assertIsNone(inherited['volume'])
        with self.assertRaisesRegex(ValueError, 'inheritance 0 has no preceding'):
            tab.playback_plan(song, raw)
        for cell in (Cell(effect=20, param=90), Cell(effect=2, param=0), Cell(volcmd=32)):
            raw[0].rows[30][6] = cell
            view = tab.authoring_view(song, raw)
            self.assertEqual(any('not a playback timing map' in d for d in view['diagnostics']), cell.effect != 20)
            with self.assertRaises(ValueError):
                tab.playback_plan(song, raw)

    def test_note_set_preserves_explicit_spelling_for_pitch_and_computed_fret_changes(self):
        song, _ = fixture()
        for patch in ({'pitch': 61, 'spelling': {'step': 'D', 'alter': -1}},
                      {'fret': 2, 'spelling': {'step': 'D', 'alter': -1}},
                      {'pitch': 61, 'spelling': None}):
            with self.subTest(patch=patch):
                candidate = tab.apply_score_edit(song, {'op': 'note_set', 'pattern': 'A', 'beat': 'chord',
                    'note': dict(id='c', **patch)})
                result = candidate['score']['patterns']['A']['beats'][0]['notes'][0]
                self.assertEqual(result['pitch'], 61)
                self.assertIn('spelling', result)
                self.assertEqual(result['spelling'], patch['spelling'])

    def test_invalid_explicit_spelling_is_rejected_instead_of_discarded(self):
        song, _ = fixture()
        original = copy.deepcopy(song)
        for patch in ({'pitch': 61, 'spelling': {'step': 'D', 'alter': 0}},
                      {'fret': 2, 'spelling': {'step': 'D', 'alter': 0}}):
            with self.subTest(patch=patch), self.assertRaisesRegex(ValueError, 'spelling does not match pitch'):
                tab.apply_score_edit(song, {'op': 'note_set', 'pattern': 'A', 'beat': 'chord',
                    'note': dict(id='c', **patch)})
            self.assertEqual(song, original)

    def test_same_pitch_and_refingering_keep_spelling_but_actual_pitch_change_clears_it(self):
        song, raw = fixture()
        named = note('spelled_n', 61, 2, 2)
        named['spelling'] = {'step': 'D', 'alter': -1}
        song = tab.apply_score_edit(song, {'op': 'beat_set', 'pattern': 'B',
            'beat': beat('spelled_b', [1, 1], [named])})
        for patch in ({'pitch': 61}, {'string': 3, 'fret': 6}, {'pitch': 61, 'string': 3, 'fret': 6}):
            candidate = tab.apply_score_edit(song, {'op': 'note_set', 'pattern': 'B', 'beat': 'spelled_b',
                'note': dict(id='spelled_n', **patch)})
            result = candidate['score']['patterns']['B']['beats'][-1]['notes'][0]
            self.assertEqual(result['spelling'], named['spelling'])
        for patch in ({'pitch': 62}, {'fret': 3}):
            candidate = tab.apply_score_edit(song, {'op': 'note_set', 'pattern': 'B', 'beat': 'spelled_b',
                'note': dict(id='spelled_n', **patch)})
            result = candidate['score']['patterns']['B']['beats'][-1]['notes'][0]
            self.assertEqual(result['pitch'], 62)
            self.assertNotIn('spelling', result)
        projection = tab.project_score(song, raw)
        for pitch in (None, 61):
            moved = tab.move_note(song, projection, 1, 'spelled_n', 18, pitch=pitch)
            self.assertEqual(moved['score']['patterns']['B']['beats'][-1]['notes'][0]['spelling'], named['spelling'])
        shifted = tab.move_note(song, projection, 1, 'spelled_n', 18, pitch=62)
        self.assertNotIn('spelling', shifted['score']['patterns']['B']['beats'][-1]['notes'][0])
        moved_beat = tab.move_beat(song, projection, 1, 'spelled_b', 18)
        self.assertEqual(moved_beat['score']['patterns']['B']['beats'][-1]['notes'][0]['spelling'], named['spelling'])


class TestSubrowDurationProjection(unittest.TestCase):
    def fixture(self):
        song, raw = plan_fixture()
        song['score']['ties'] = []
        song['score']['patterns']['A']['beats'] = [
            beat('tail-rest', [15, 4], [], 16)]
        song['score']['patterns']['B']['beats'] = [
            beat('head', [0, 1], [note('head-note', 64, 1, 0)], 16),
            beat('following', [1, 1], [note('following-note', 67, 1, 3)])]
        return song, raw

    def test_cross_range_32nd_keeps_grid_and_exact_delayed_keyoff(self):
        song, raw = self.fixture()
        raw[0].rows[2][6].effect, raw[0].rows[2][6].param = 24, 64
        before = copy.deepcopy((song, raw))
        changed, _ = tab.score_command(song, raw, dict(action='set_duration', track='guitar', voice=0,
            selection=[dict(occurrence='oa', beats=['tail-rest']), dict(occurrence='ob', beats=['head'])],
            written=dict(value=32, dots=0, tuplet=[1, 1])))
        projection = tab.project_score(changed, raw)
        self.assertEqual(changed['module']['speed'], 2)
        self.assertEqual(changed['patterns'], song['patterns'])
        self.assertEqual([len(p.rows) for p in projection.patterns], [48, 48])
        self.assertEqual(projection.patterns[0].rows[2][6], raw[0].rows[2][6])
        release = projection.patterns[1].rows[1][0]
        self.assertEqual((release.note, release.effect, release.param), (NOTE_OFF, 19, 0xD1))
        events = [e for e in tab.playback_plan(changed, raw)['events'] if e['id'] == 'ob/head-note']
        self.assertEqual([e['at'] for e in events], [[4, 1], [33, 8]])
        json.dumps(tab.score_view(changed, projection))
        self.assertEqual((song, raw), before)

    def test_delayed_attack_and_exact_tie_use_existing_tick_projection(self):
        song, raw = self.fixture()
        song['score']['patterns']['B']['beats'] = [
            beat('head', [0, 1], [note('head-note', 64, 1, 0)], 32),
            beat('next', [1, 8], [note('next-note', 64, 1, 0)], 32)]
        projected = tab.project_score(song, raw)
        delayed = projected.patterns[1].rows[1][0]
        self.assertEqual((delayed.note, delayed.effect, delayed.param), (64, 19, 0xD1))
        self.assertEqual(projected.patterns[1].rows[3][0].note, NOTE_OFF)
        song['score']['ties'] = [dict(**{'from': dict(occurrence='ob', note='head-note'),
                                       'to': dict(occurrence='ob', note='next-note')})]
        tied = tab.project_score(song, raw)
        self.assertIsNone(tied.patterns[1].rows[1][0].note)
        self.assertEqual(tied.patterns[1].rows[3][0].note, NOTE_OFF)

    def test_non_tick_notes_and_raw_collisions_refuse_without_mutation(self):
        for failure in ('non-tick', 'effect', 'instrument'):
            with self.subTest(failure=failure):
                song, raw = self.fixture()
                song['score']['patterns']['B']['beats'][0]['written']['value'] = 64 if failure == 'non-tick' else 32
                if failure == 'effect':
                    # Row-dependent volume slides cannot use exact export subdivision.
                    raw[1].rows[1][0].effect, raw[1].rows[1][0].param = 4, 1
                if failure == 'instrument':
                    raw[1].rows[1][0].instrument = 1
                before = copy.deepcopy((song, raw))
                with self.assertRaisesRegex(ValueError, 'not representable|conflicting effect|conflicts with score sustain'):
                    tab.project_score(song, raw)
                self.assertEqual((song, raw), before)

    def test_pan_collision_preserves_raw_effect_with_exact_export_subdivision(self):
        song, raw = self.fixture()
        song['score']['patterns']['B']['beats'][0]['written']['value'] = 32
        raw[1].rows[1][0].effect, raw[1].rows[1][0].param = 24, 64
        before = copy.deepcopy((song, raw))
        projection = tab.project_score(song, raw)
        self.assertEqual(len(projection.patterns[1].rows), 96)
        self.assertEqual((projection.patterns[1].rows[2][0].effect, projection.patterns[1].rows[2][0].param), (24, 64))
        self.assertEqual(projection.patterns[1].rows[3][0].note, NOTE_OFF)
        self.assertEqual((song, raw), before)

    def test_non_tick_rest_needs_no_tracker_cells(self):
        song, raw = self.fixture()
        song['score']['patterns']['A']['beats'][0].update(at=[31, 8], written=dict(value=64))
        projection = tab.project_score(song, raw)
        self.assertEqual(projection.patterns[0], raw[0])
        rest = next(p for p in projection.positions if p['beat'] == 'tail-rest')
        self.assertEqual((rest['at'], rest['duration']), ([31, 8], [1, 16]))


class TestNativeRawAdoption(unittest.TestCase):
    def fixture(self):
        from types import SimpleNamespace
        song, raw = plan_fixture()
        song['score']['ties'] = []
        song['score']['patterns']['A']['beats'] = [beat('fractional', [1, 13], [note('n', 64, 1, 0)], 64, [13, 8])]
        song['score']['patterns']['B']['beats'] = []
        raw[0].rows[0][6] = Cell(note=40, instrument=1, effect=22, param=64)
        raw[0].rows[4][6] = Cell(note=NOTE_OFF)
        native = {'view': tab.authoring_view(song, raw), 'plan': tab.playback_plan(song, raw, 48000)}
        return song, SimpleNamespace(patterns=raw, native_score=native)

    def test_raw_preview_stops_at_fractional_score_boundary_without_projection(self):
        song, module = self.fixture()
        raw = module.patterns
        raw[0].rows[0][0] = Cell(note=60, instrument=1)
        raw[0].rows[12][0] = Cell(note=NOTE_OFF)
        before = copy.deepcopy((song, raw))
        from unittest.mock import patch
        with patch.object(tab, 'project_score', side_effect=AssertionError('must not project')):
            preview = tab.native_raw_note_view(song, raw)
        first = next(p for p in preview if p['ch'] == 0)
        self.assertEqual((first['row'], first['end_row'], first['duration']), (0, [12, 13], [1, 13]))
        self.assertEqual(first['boundary'], 'score_attack')
        self.assertFalse(first['adoptable'])
        self.assertEqual(tab.duration_quarters(first['written']), Fraction(1, 13))
        self.assertEqual(first['occurrence'], 'oa')
        self.assertEqual((song, raw), before)

    def test_native_adoption_keeps_explicit_instrument_inheritance(self):
        song, module = self.fixture()
        raw = module.patterns
        raw[0].rows[0][6] = Cell(instrument=1)
        raw[0].rows[1][6] = Cell(note=40)
        module.native_score = {'view': tab.authoring_view(song, raw), 'plan': tab.playback_plan(song, raw, 48000)}
        candidate, groups = tab.promote_pattern(song, module, 0, 'bass', [{'row': 1, 'ch': 6}], occurrence='oa')
        self.assertEqual(candidate['score']['patterns']['A']['beats'][-1]['notes'][0]['instrument'], 0)
        self.assertNotIn(0, [c['row'] for _, cells in groups for c in cells])
        self.assertEqual(raw[0].rows[0][6].instrument, 1)

    def test_native_adoption_preserves_raw_controls_and_existing_score_events(self):
        song, module = self.fixture()
        before = copy.deepcopy((song, module.patterns))
        from unittest.mock import patch
        with patch.object(tab, 'project_score', side_effect=AssertionError('must not project')):
            candidate, groups = tab.promote_pattern(song, module, 0, 'bass', [{'row': 0, 'ch': 6}], occurrence='oa')
        self.assertEqual((song, module.patterns), before)
        adopted = candidate['score']['patterns']['A']['beats'][-1]
        self.assertEqual(adopted['at'], [0, 1])
        self.assertEqual(tab.duration_quarters(adopted['written']), Fraction(1, 3))
        self.assertEqual(adopted['notes'][0]['instrument'], 1)
        raw = copy.deepcopy(module.patterns)
        for pi, cells in groups:
            for cell in cells:
                raw[pi].rows[cell['row']][cell['ch']] = parse_cell(cell['cell'])
        self.assertIsNone(raw[0].rows[0][6].note)
        self.assertEqual(raw[0].rows[0][6].instrument, 0)
        self.assertEqual((raw[0].rows[0][6].effect, raw[0].rows[0][6].param), (22, 64))
        self.assertIsNone(raw[0].rows[4][6].note)
        plan = tab.playback_plan(candidate, raw, 48000)
        self.assertTrue(all(e in plan['events'] for e in module.native_score['plan']['events']))

    def test_native_reused_occurrences_are_explicit_and_previewed_separately(self):
        song, module = self.fixture()
        song['orders'].append('A')
        song['score']['order_ids'].append('oa_again')
        module.native_score = {'view': tab.authoring_view(song, module.patterns),
                               'plan': tab.playback_plan(song, module.patterns, 48000)}
        records = tab.native_raw_note_view(song, module.patterns, view=module.native_score['view'])
        self.assertEqual([p['occurrence'] for p in records], ['oa', 'oa_again'])
        self.assertEqual(len(tab.native_raw_note_view(song, module.patterns, occurrence='oa_again')), 1)
        with self.assertRaisesRegex(ValueError, 'explicit played occurrence'):
            tab.promote_pattern(song, module, 0, 'bass')
        with self.assertRaisesRegex(ValueError, 'does not match'):
            tab.promote_pattern(song, module, 0, 'bass', occurrence='ob')
        result, _ = tab.promote_pattern(song, module, 0, 'bass', occurrence='oa_again')
        self.assertEqual(len(result['score']['patterns']['A']['beats']), 2)

    def test_native_adoption_refuses_unknown_cut_fade_and_attack_endings_atomically(self):
        from vulturetracker.model import NOTE_CUT, NOTE_FADE
        for ending in (None, NOTE_CUT, NOTE_FADE, 42):
            song, module = self.fixture()
            module.patterns[0].rows[4][6] = Cell(note=ending)
            module.native_score = {'view': tab.authoring_view(song, module.patterns),
                                   'plan': tab.playback_plan(song, module.patterns, 48000)}
            before = copy.deepcopy((song, module.patterns))
            with self.subTest(ending=ending), self.assertRaisesRegex(ValueError, 'explicit raw note-off'):
                tab.promote_pattern(song, module, 0, 'bass', [{'row': 0, 'ch': 6}], occurrence='oa')
            self.assertEqual((song, module.patterns), before)


class TestChordTools(unittest.TestCase):
    # Expected vectors are from the installed pinned TG original methods,
    # including its ordering/rounding quirks. No Java or scratch files in CI.
    def recognize(self, tuning, frets, **options):
        from vulturetracker.chord_tools import recognize_chord
        track = dict(tuning=tuning, capo=7, max_fret=36)
        chord = dict(name='Keep my authored name', first_fret=0, frets=frets)
        before = copy.deepcopy((track, chord))
        result = recognize_chord(track, chord, **options)
        self.assertEqual((track, chord), before)
        return [(p['name'], p['completeness'], p['unusualness'], p['score_percent'],
                 p['source_parameters']) for p in result]

    def test_all_source_qualities_and_spellings(self):
        from vulturetracker.chord_tools import QUALITIES, chord_spec
        bases = [(0, 4, 7), (0, 4, 7, 10), (0, 4, 7, 11), (0, 4, 7, 9),
                 (0, 3, 7), (0, 3, 7, 10), (0, 3, 7, 11), (0, 3, 7, 9),
                 (0, 2, 7), (0, 5, 7), (0, 2, 7, 10), (0, 5, 7, 10),
                 (0, 3, 6), (0, 3, 6, 9), (0, 4, 8), (0, 7)]
        self.assertEqual(QUALITIES, ('M', '7', 'maj7', '6', 'm', 'm7', 'm/maj7', 'm6',
                                    'sus2', 'sus4', '7sus2', '7sus4', 'dim', 'dim7', 'aug', '5'))
        for i, (quality, base) in enumerate(zip(QUALITIES, bases)):
            for sharp, name in ((True, 'C#'), (False, 'Db')):
                with self.subTest(quality=quality, sharp=sharp):
                    spec = dict(root=1, quality=quality, sharp=sharp)
                    result = chord_spec(spec)
                    self.assertEqual(spec, dict(root=1, quality=quality, sharp=sharp))
                    self.assertEqual(result['base'], list(base))
                    self.assertEqual(result['extensions'], [])
                    self.assertEqual(result['name'], name + (quality if i else ''))
                    self.assertEqual(result['pitch_classes'], sorted((n + 1) % 12 for n in base))
                    self.assertEqual(result['source_parameters'], [1, i, 0, 0, 1, 0, 0, 0, 0])
                    self.assertEqual(chord_spec(result['spec']), result)

    def test_extensions_add_alterations_and_source_seventh_overlap(self):
        from vulturetracker.chord_tools import chord_spec
        vectors = [
            (dict(quality='maj7', extension=9), 'Cmaj7/9', [0, 4, 7, 11], [10, 2]),
            (dict(quality='7', extension=11), 'C7/11', [0, 4, 7], [10, 5, 2]),
            (dict(quality='6', extension=13), 'C6/13', [0, 4, 7], [10, 9, 2, 5]),
            (dict(quality='sus2', extension=9, add=True), 'Csus2add9', [0, 7], [2]),
            (dict(extension=13, extension_shift=-1, fifth_shift=1,
                  ninth_shift=-1, eleventh_shift=1, bass=1, sharp=False),
             'C13-/5+/9-/11+ \\Db', [0, 4], [10, 8, 1, 6]),
            (dict(extension=13, extension_shift=1), 'C13+', [0, 4, 7], [10, 10, 2, 5]),
            (dict(quality='5', fifth_shift=-1), 'C5/5-', [0, 6], []),
        ]
        for fields, name, base, extensions in vectors:
            with self.subTest(fields=fields):
                result = chord_spec(dict(root=0, **fields))
                self.assertEqual((result['name'], result['base'], result['extensions']),
                                 (name, base, extensions))
        self.assertEqual(chord_spec(dict(root=0, bass=1))['pitch_classes'], [0, 1, 4, 7])

    def test_theory_refuses_malformed_and_disabled_source_controls(self):
        from vulturetracker.chord_tools import chord_spec
        bad = [dict(root=True), dict(root=-1), dict(root=12), dict(bass=False),
               dict(quality='major'), dict(quality=[]), dict(extension=True),
               dict(extension=7), dict(extension_shift=2), dict(fifth_shift=False),
               dict(add=1), dict(sharp=0), dict(extra=1), dict(extension_shift=1),
               dict(add=True), dict(ninth_shift=1), dict(eleventh_shift=-1),
               dict(quality='dim', fifth_shift=1), dict(quality='dim7', extension=9),
               dict(quality='aug', extension=9), dict(quality='5', extension=9),
               dict(extension=9, ninth_shift=1), dict(extension=11, eleventh_shift=1),
               dict(extension=13, add=True, ninth_shift=1),
               dict(extension=13, add=True, eleventh_shift=-1)]
        for fields in bad:
            value = dict(root=0, **{k: v for k, v in fields.items() if k != 'root'})
            if 'root' in fields:
                value['root'] = fields['root']
            before = copy.deepcopy(value)
            with self.subTest(fields=fields), self.assertRaises(ValueError):
                chord_spec(value)
            self.assertEqual(value, before)
        for value in (None, [], {}, 'C'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                chord_spec(value)

    def test_recognition_complete_and_incomplete_proposal_order(self):
        tuning, frets = [64, 59, 55, 50, 45, 40], [0, 1, 0, 2, 3, -1]
        complete = [('C', 0, 0, 100, [0, 0, 0, 0, 0, 0, 0, 0, 0]),
                    ('Em/5+ \\C', 0, -55, 100, [4, 4, 0, 0, 0, 0, 1, 0, 0])]
        self.assertEqual(self.recognize(tuning, frets, incomplete=0), complete)
        self.assertEqual(self.recognize(tuning, frets), [
            complete[0],
            ('C7', -50, -2, 65, [0, 1, 0, 0, 0, 0, 0, 0, 0]),
            ('Cmaj7', -50, -4, 65, [0, 2, 0, 0, 0, 0, 0, 0, 0]),
            ('C6', -50, -6, 65, [0, 3, 0, 0, 0, 0, 0, 0, 0]),
            ('Gsus4add13 \\C', -20, -48, 86, [7, 9, 3, 0, 0, 1, 0, 0, 0]),
            complete[1]])
        # Source cut==0 leaves the first incomplete proposal instead of hiding it.
        self.assertEqual(self.recognize([64], [0], incomplete=0),
                         [('E5', -20, -30, 86, [4, 15, 0, 0, 4, 0, 0, 0, 0])])
        self.assertEqual(self.recognize(tuning, [-1] * 6), [])

    def test_recognition_reentrant_bass_tied_grades_and_integer_rounding(self):
        self.assertEqual(self.recognize([61, 55, 42, 78, 59, 37, 60],
                                       [10, 7, 7, 10, -1, 7, 10]), [
            ('C#m6/9- \\A#', 0, -59, 100, [1, 7, 1, 2, 10, 0, 0, 0, 0]),
            ('A#m11-/5-/9-', 0, -75, 100, [10, 4, 2, 2, 10, 0, 2, 2, 0]),
            ('C#m13/9- \\A#', -10, -75, 93, [1, 4, 3, 0, 10, 0, 0, 2, 0]),
            ('E13/11+ \\A#', -10, -75, 93, [4, 0, 3, 0, 10, 0, 0, 0, 1]),
            ('E6/11+ \\A#', -10, -81, 93, [4, 3, 2, 1, 10, 0, 0, 0, 0]),
            ('A#m7/11-/5-/9-', -25, -85, 83, [10, 5, 2, 2, 10, 0, 2, 2, 0])])
        self.assertEqual(self.recognize([49, 50, 53, 56, 58], [0] * 5, sharp=False), [
            ('Bb9+', 0, -25, 100, [10, 0, 1, 1, 10, 0, 0, 0, 0]),
            ('Bb7add9+', 0, -27, 100, [10, 1, 1, 1, 10, 1, 0, 0, 0]),
            ('Bbm7add11-', 0, -35, 100, [10, 5, 2, 2, 10, 1, 0, 0, 0]),
            ('Db6add9- \\Bb', 0, -51, 100, [1, 3, 1, 2, 10, 1, 0, 0, 0]),
            ('Bbm11-', -10, -55, 93, [10, 4, 2, 2, 10, 0, 0, 0, 0]),
            ('Db13/9- \\Bb', -35, -75, 76, [1, 0, 3, 0, 10, 0, 0, 2, 0]),
            ('Fm6add11/5+ \\Bb', 0, -79, 100, [5, 7, 2, 0, 10, 1, 1, 0, 0])])

    def test_recognition_native_validation_and_result_isolation(self):
        from vulturetracker.chord_tools import recognize_chord
        track = dict(tuning=[64, 59, 55, 50, 45, 40])
        chord = dict(name='', first_fret=0, frets=[0, 1, 0, 2, 3, -1])
        result = recognize_chord(track, chord)
        before = copy.deepcopy(result)
        result[0]['source_parameters'][0] = 9
        result[0]['spec']['root'] = 9
        self.assertEqual(recognize_chord(track, chord), before)
        for fields in (dict(tuning=[]), dict(tuning=[True]), dict(tuning=[120]),
                       dict(tuning=[0] * 26), dict(max_fret=True), dict(capo=25)):
            with self.subTest(fields=fields), self.assertRaises(ValueError):
                recognize_chord(dict(track, **fields), chord)
        for fields in (dict(name=0), dict(first_fret=False), dict(frets=[0]),
                       dict(frets=[0, 1, 0, 2, 7, -1]), dict(extra=True)):
            with self.subTest(fields=fields), self.assertRaises(ValueError):
                recognize_chord(track, dict(chord, **fields))
        for options in (dict(sharp=1), dict(incomplete=True), dict(incomplete=-1), dict(incomplete=101)):
            with self.subTest(options=options), self.assertRaises(ValueError):
                recognize_chord(track, chord, **options)
        with self.assertRaises(ValueError):
            recognize_chord(track, None)


class TestChordGeneration(unittest.TestCase):
    def generate(self, tuning=None, spec=None, **settings):
        from vulturetracker.chord_tools import generate_chords
        track = dict(tuning=tuning or [64, 59, 55, 50, 45, 40], max_fret=36)
        spec = dict(root=0) if spec is None else spec
        before = copy.deepcopy((track, spec, settings))
        try:
            result = generate_chords(track, spec, **settings)
        finally:
            self.assertEqual((track, spec, settings), before)
        for chord in result['chords']:
            tab._validate_chord(chord, track)
            self.assertEqual(chord['first_fret'], 0)
        return result

    def test_default_complete_order_and_source_suppression(self):
        result = self.generate()
        # Entire original-Java retained list, not just its highest-scoring item.
        self.assertEqual([c['frets'] for c in result['chords']], [
            [8, 8, 9, 10, 10, 8], [0, 1, 0, 2, 3, -1], [3, 1, 0, 2, 3, -1],
            [-1, 5, 5, 5, 7, 8], [3, 5, 5, 5, 3, -1], [12, 13, 12, 14, 15, -1],
            [-1, 8, 5, 5, 7, 8], [12, 13, 12, 10, -1, -1], [-1, 5, 9, 5, 7, 8],
            [12, 8, 9, 10, -1, -1], [12, 8, 12, 10, -1, -1], [8, 8, 9, 10, 7, 8],
            [15, 13, 12, 14, 15, -1], [8, 8, 9, 5, 7, 8], [3, 5, 5, 2, 3, -1],
            [3, 1, 5, 2, 3, -1], [8, 8, 12, 10, 10, 8], [12, 13, 9, 10, -1, -1],
            [-1, 13, 12, 14, 10, -1], [-1, -1, 5, 5, 7, 3], [-1, 1, 5, 5, 3, -1],
            [8, 8, 9, 10, 10, 12], [8, 8, 12, 10, 10, 12]])
        self.assertTrue(all(c['name'] == 'C' for c in result['chords']))
        self.assertEqual(result['settings'], dict(profile='normal', min_fret=0, max_fret=15,
                                                  open_strings=False, count=30))
        self.assertEqual(self.generate(count=3)['chords'], result['chords'][:3])

    def test_remaining_profiles_and_duplicate_extension_roles(self):
        for root, profile, expected in [
            (3, 'inversions', [[-1, 8, 8, 8, -1, -1], [3, 4, 3, -1, -1, -1], [11, 11, 12, -1, -1, -1]]),
            (6, 'close-voiced', [[-1, 11, 11, 11, -1, -1], [-1, 2, 3, 4, -1, -1], [6, 7, 6, -1, -1, -1]]),
            (9, 'open-voiced', [[-1, 2, -1, 2, 0, -1], [-1, 5, 6, -1, -1, 5], [12, 14, -1, -1, 12, -1]])]:
            with self.subTest(profile=profile):
                result = self.generate(spec=dict(root=root), profile=profile, count=3)
                self.assertEqual([c['frets'] for c in result['chords']], expected)
        result = self.generate(spec=dict(root=1, extension=13, extension_shift=1),
                               min_fret=3, max_fret=12, open_strings=True, count=5)
        self.assertEqual([c['frets'] for c in result['chords']], [
            [11, 9, 10, 9, 9, 9], [7, 6, 6, 6, 8, 9], [9, 9, 10, 9, 11, 9],
            [9, 9, 10, 9, 9, 9], [11, 9, 10, 9, 11, 9]])
        self.assertTrue(all(c['name'] == 'C#13+' for c in result['chords']))

    def test_first_open_string_source_edge_and_zero_not_banned(self):
        self.assertEqual(self.generate([54, 60], min_fret=6, max_fret=6,
                                       open_strings=True)['chords'], [])
        self.assertEqual(self.generate([60, 54], min_fret=6, max_fret=6,
                                       open_strings=True)['chords'],
                         [dict(name='C', first_fret=0, frets=[0, 6])])
        self.assertEqual(self.generate([60, 54], min_fret=6, max_fret=6,
                                       open_strings=False)['chords'], [])
        self.assertEqual(self.generate([64, 60], max_fret=0, open_strings=False)['chords'],
                         [dict(name='C', first_fret=0, frets=[0, 0])])

    def test_java_merge_order_for_nontransitive_near_ties(self):
        result = self.generate([40, 37, 46, 79, 72, 36, 42],
            spec=dict(root=3, quality='sus4', bass=2, extension=9, fifth_shift=-1, extension_shift=-1),
            profile='close-voiced', min_fret=2, max_fret=9, count=100)
        self.assertEqual(len(result['chords']), 100)
        # Python's built-in sort gave different positions68..71 despite the
        # exact same candidates and float scores. Pinned installed Java output:
        self.assertEqual([c['frets'] for c in result['chords'][66:74]], [
            [5, 7, 5, 6, 8, -1, -1], [-1, 7, 5, 6, 3, 3, 3],
            [4, 3, 3, 6, 3, 3, 7], [9, 7, 6, 8, 9, 9, 8],
            [-1, -1, 6, 6, 4, 4, -1], [-1, -1, 5, 2, 3, 4, 2],
            [-1, -1, -1, 6, 3, 4, 7], [-1, -1, -1, 9, 8, 8, 8]])

    def test_native_fret_pitch_bounds_and_capo_shape_semantics(self):
        from vulturetracker.chord_tools import generate_chords
        track = dict(tuning=[64, 60], max_fret=0)
        original = generate_chords(track, dict(root=0))
        self.assertEqual(original['settings']['max_fret'], 0)
        self.assertEqual(generate_chords(dict(track, capo=7), dict(root=0)), original)
        self.assertEqual(generate_chords(dict(tuning=[119, 119], capo=1), dict(root=11),
                                         max_fret=0)['chords'], [])
        self.assertEqual(generate_chords(dict(tuning=[0, 0], capo=-1), dict(root=0),
                                         max_fret=0)['chords'], [])
        result = generate_chords(dict(tuning=[119, 116, 112], max_fret=36), dict(root=11))
        for chord in result['chords']:
            self.assertTrue(all(p + f <= 119 for p, f in zip([119, 116, 112], chord['frets']) if f >= 0))
        with self.assertRaisesRegex(ValueError, 'track max_fret'):
            generate_chords(track, dict(root=0), max_fret=1)
        original['chords'][0]['frets'][0] = 9
        self.assertEqual(generate_chords(track, dict(root=0))['chords'][0]['frets'], [0, 0])

    def test_all_native_string_counts_with_sparse_work(self):
        self.assertEqual(self.generate([60], max_fret=0)['chords'], [])
        self.assertEqual(self.generate([61] * 25, max_fret=0)['chords'], [])
        for strings in (2, 7, 9, 25):
            with self.subTest(strings=strings):
                result = self.generate([61] * (strings - 2) + [64, 60], max_fret=0)
                self.assertEqual(result['chords'], [
                    dict(name='C', first_fret=0, frets=[-1] * (strings - 2) + [0, 0])])

    def test_bounded_requests_refuse_without_partial_results_or_mutation(self):
        # Real bounds, not lowered mocked thresholds: display count1 must
        # still enumerate and grade the complete admitted search.
        with self.assertRaisesRegex(ValueError, 'candidate limit'):
            self.generate([60] * 25, max_fret=0, count=1)
        with self.assertRaisesRegex(ValueError, 'work limit'):
            self.generate([54] * 13 + [60] * 12, min_fret=6, max_fret=6,
                          open_strings=True, count=1)

    def test_malformed_settings_refuse(self):
        for settings in (dict(profile='close'), dict(profile=[]), dict(min_fret=True),
                         dict(min_fret=-1), dict(min_fret=16), dict(max_fret=True),
                         dict(max_fret=-1), dict(max_fret=26), dict(min_fret=5, max_fret=4),
                         dict(open_strings=1), dict(count=True), dict(count=0), dict(count=101)):
            with self.subTest(settings=settings), self.assertRaises(ValueError):
                self.generate(**settings)


class TestLyrics(unittest.TestCase):
    def fixture(self, text='one two three four five six', start=1):
        song, raw = plan_fixture()
        song['score']['tracks']['guitar']['lyrics'] = dict(from_measure=start, text=text)
        song['score']['measures'] = [
            dict(id='m1', meter=[4, 4], **{'from': dict(occurrence='oa', at=[0, 1]),
                                         'to': dict(occurrence='oa', at=[4, 1])}),
            dict(id='m2', meter=[4, 4], **{'from': dict(occurrence='ob', at=[0, 1]),
                                         'to': dict(occurrence='ob', at=[4, 1])})]
        return song, raw

    def view(self, song, raw):
        before = copy.deepcopy((song, raw))
        try:
            return tab.authoring_view(song, raw)['lyrics']
        finally:
            self.assertEqual((song, raw), before)

    def test_track_set_validation_exact_text_clearing_and_roundtrip(self):
        song, raw = self.fixture(' \tÎ±\r\nÎ²\rgamma\nçµ‚  ', 2147483647)
        track = song['score']['tracks']['guitar']
        value = copy.deepcopy(track)
        value['lyrics']['from_measure'] = 2
        before = copy.deepcopy((song, value))
        changed = tab.apply_score_edit(song, dict(op='track_set', track='guitar', value=value))
        self.assertEqual((song, value), before)
        self.assertEqual(changed['score']['tracks']['guitar'], value)
        self.assertEqual(changed['score']['patterns'], song['score']['patterns'])
        self.assertEqual(yaml.safe_load(yaml.safe_dump(changed)), changed)
        changed['score']['tracks']['guitar']['lyrics']['text'] = 'isolated'
        self.assertEqual(song['score']['tracks']['guitar'], track)
        for lyrics in (None, {}, dict(from_measure=1), dict(text='a'), dict(from_measure=True, text='a'),
                       dict(from_measure=0, text='a'), dict(from_measure=2147483648, text='a'),
                       dict(from_measure=1, text=7), dict(from_measure=1, text='x' * 65537),
                       dict(from_measure=1, text='a', verse=1)):
            with self.subTest(lyrics=lyrics), self.assertRaisesRegex(ValueError, 'lyrics'):
                tab.apply_score_edit(song, dict(op='track_set', track='guitar', value=dict(track, lyrics=lyrics)))
            self.assertEqual((song, value), before)
        large = tab.apply_score_edit(song, dict(op='track_set', track='guitar',
            value=dict(track, lyrics=dict(from_measure=1, text='\U0001f3b5' * 65536))))
        self.assertEqual(len(large['score']['tracks']['guitar']['lyrics']['text']), 65536)
        cleared_track = {k: v for k, v in track.items() if k != 'lyrics'}
        cleared = tab.apply_score_edit(song, dict(op='track_set', track='guitar', value=cleared_track))
        self.assertNotIn('lyrics', cleared['score']['tracks']['guitar'])
        self.assertNotIn('lyrics', tab.authoring_view(cleared, raw))
        empty = tab.apply_score_edit(song, dict(op='track_set', track='guitar',
            value=dict(track, lyrics=dict(from_measure=9, text=''))))
        self.assertEqual(empty['score']['tracks']['guitar']['lyrics'], dict(from_measure=9, text=''))

    def test_java_space_split_and_trim_slots(self):
        vectors = [('', ['']), (' ', []), (' a  b ', ['', 'a', '', 'b']),
                   ('a\r\nb', ['a', '', 'b']), ('a\tb', ['a\tb']),
                   ('hy-phen + _ [literal]', ['hy-phen', '+', '_', '[literal]']),
                   ('\u00a0a\u00a0', ['\u00a0a\u00a0'])]
        for text, tokens in vectors:
            with self.subTest(text=text):
                self.assertEqual(tab._lyric_tokens(text), tokens)
        song, raw = self.fixture(' \x00\tone\t\r\n\u00a0two\u00a0 ')
        anchors = self.view(song, raw)['anchors']
        self.assertEqual([(a['slot'], a['text'], a['display_text']) for a in anchors],
                         [(0, '', ''), (1, '\x00\tone\t', 'one'),
                          (2, '', ''), (3, '\u00a0two\u00a0', '\u00a0two\u00a0')])
        self.assertEqual([a['beat'] for a in anchors], ['chord', 't1', 't2', 't3'])

    def test_written_cohorts_ties_rests_and_technique_expansion(self):
        song, raw = self.fixture('a b c d e f g h i')
        beats = song['score']['patterns']['A']['beats']
        beats.extend([beat('v1same', [0, 1], [note('v1n', 50, 4, 0)], voice=1),
                      beat('v1rest', [1, 1], [], voice=1),
                      beat('v1only', [2, 1], [note('v1onlyn', 45, 5, 0)], value=8, voice=1),
                      beat('long', [5, 2], [note('longn', 50, 4, 0)], voice=1),
                      beat('silent', [3, 1], [], value=8)])
        beats[4]['chord'] = dict(name='Rest label', first_fret=0, frets=[-1] * 6)
        beats[1]['notes'][0].update(velocity=95, grace=dict(fret=1, value=32, velocity=70))
        beats[2]['notes'][0].update(velocity=95, trill=dict(fret=2, value=32))
        beats[3]['notes'][0].update(velocity=0, dead=True)
        view = self.view(song, raw)
        self.assertEqual(view['errors'], [])
        self.assertEqual([(a['beat'], a['voice'], a['text']) for a in view['anchors']],
                         [('chord', 0, 'a'), ('t1', 0, 'b'), ('t2', 0, 'c'), ('t3', 0, 'd'),
                          ('v1only', 1, 'e'), ('long', 1, 'f'), ('tail', 0, 'g'), ('head', 0, 'h')])
        # Tied continuation still consumes; rests and an earlier sounding
        # sustain do not invent lyric slots. Principal beats own technique labels.
        self.assertEqual(view['anchors'][-1], dict(track='guitar', occurrence='ob', pattern='B',
            beat='head', voice=0, measure='m2', measure_number=2, slot=7,
            at=[4, 1], local_at=[0, 1], text='h', display_text='h'))

    def test_rational_onsets_and_half_open_measure_boundaries(self):
        song, raw = self.fixture('first second third fourth')
        song['score']['ties'] = []
        song['score']['patterns']['A']['beats'] = [
            beat('a', [0, 1], [note('an', 64, 1, 0)], value=64),
            beat('b', [1, 16], [note('bn', 65, 1, 1)], value=64),
            beat('c', [2, 13], [note('cn', 67, 1, 3)], tuplet=[13, 1])]
        m2 = song['score']['measures'][1]
        song['score']['measures'] = [
            dict(id='remainder', meter=[63, 64], **{'from': dict(occurrence='oa', at=[1, 16]),
                                                   'to': dict(occurrence='oa', at=[4, 1])}),
            m2, dict(id='tiny', meter=[1, 64], **{'from': dict(occurrence='oa', at=[0, 1]),
                                                 'to': dict(occurrence='oa', at=[1, 16])})]
        anchors = self.view(song, raw)['anchors']
        self.assertEqual([(a['at'], a['measure'], a['measure_number']) for a in anchors],
                         [([0, 1], 'tiny', 1), ([1, 16], 'remainder', 2),
                          ([2, 13], 'remainder', 2), ([4, 1], 'm2', 3)])

    def test_cross_pattern_measure_and_reused_occurrence_identity(self):
        song, raw = self.fixture()
        song['score']['measures'] = [
            dict(id='cross', meter=[6, 4], **{'from': dict(occurrence='oa', at=[0, 1]),
                                             'to': dict(occurrence='ob', at=[2, 1])}),
            dict(id='end', meter=[2, 4], **{'from': dict(occurrence='ob', at=[2, 1]),
                                           'to': dict(occurrence='ob', at=[4, 1])})]
        self.assertTrue(all(a['measure'] == 'cross' for a in self.view(song, raw)['anchors']))
        song, raw = self.fixture('a b c d e f g h i j')
        song['orders'], song['score']['order_ids'], song['score']['ties'] = ['A', 'A'], ['oa', 'oa2'], []
        song['score']['measures'][1]['from']['occurrence'] = 'oa2'
        song['score']['measures'][1]['to']['occurrence'] = 'oa2'
        anchors = self.view(song, raw)['anchors']
        self.assertEqual([(a['occurrence'], a['beat'], a['text']) for a in anchors if a['beat'] == 'chord'],
                         [('oa', 'chord', 'a'), ('oa2', 'chord', 'f')])
        self.assertEqual(anchors[5]['at'], [4, 1])
        self.assertEqual(anchors[5]['local_at'], [0, 1])

    def test_missing_gapped_maps_preserve_text_and_valid_audio(self):
        for missing in (True, False):
            song, raw = self.fixture()
            if missing:
                song['score'].pop('measures')
            else:
                song['score']['measures'].pop(0)
            baseline = copy.deepcopy(song)
            baseline['score']['tracks']['guitar'].pop('lyrics')
            view = tab.authoring_view(song, raw)
            self.assertEqual(view['lyrics']['anchors'], [])
            self.assertEqual(view['lyrics']['errors'][0]['code'], 'lyrics_measure_map')
            self.assertIn(view['lyrics']['errors'][0]['message'], view['diagnostics'])
            self.assertEqual(tab.playback_plan(song, raw), tab.playback_plan(baseline, raw))
            self.assertEqual(song['score']['tracks']['guitar']['lyrics']['text'], 'one two three four five six')
        song, raw = self.fixture()
        song['score']['measures'][1] = dict(song['score']['measures'][0], id='overlap')
        with self.assertRaisesRegex(ValueError, 'overlapping measures'):
            self.view(song, raw)

    def test_empty_dormant_and_unconsumed_streams(self):
        for text in ('', ' ', '\r\n'):
            song, raw = self.fixture(text, 9)
            song['score'].pop('measures')
            self.assertEqual(self.view(song, raw), dict(anchors=[], errors=[]))
        song, raw = self.fixture('dormant', 3)
        self.assertEqual(self.view(song, raw), dict(anchors=[], errors=[]))
        song['score']['tracks']['guitar']['lyrics']['from_measure'] = 2
        self.assertEqual([(a['text'], a['occurrence'], a['slot']) for a in self.view(song, raw)['anchors']],
                         [('dormant', 'ob', 0)])
        song['score']['tracks']['bass']['lyrics'] = dict(from_measure=2, text='unconsumed')
        self.assertEqual(len(self.view(song, raw)['anchors']), 1)
        # Raw-only Pattern notes do not become written lyric anchors.
        raw[1].rows[12][6] = Cell(note=40, instrument=1)
        self.assertEqual(len(self.view(song, raw)['anchors']), 1)

    def test_structure_preserves_raw_stream_and_reflows_without_remapping_start(self):
        song, raw = self.fixture('raw\r\nwords', 2)
        song['score']['ties'] = []
        lyrics = copy.deepcopy(song['score']['tracks']['guitar']['lyrics'])
        for operation in (dict(op='pattern_rename', old='A', new='Verse'),
                          dict(op='pattern_clone', src='A', name='A2'),
                          dict(op='pattern_rows', name='A', rows=48),
                          dict(op='channel_move', ch=0, to=6)):
            candidate = tab.apply_structure_edit(song, operation)
            self.assertEqual(candidate['score']['tracks']['guitar']['lyrics'], lyrics)
        candidate = tab.apply_structure_edit(song, dict(op='orders', orders=['B', 'A'], origins=[1, 0]))
        candidate['orders'] = ['B', 'A']  # Complete the corresponding raw-side operation.
        self.assertEqual(candidate['score']['tracks']['guitar']['lyrics'], lyrics)
        self.assertEqual(self.view(candidate, raw)['anchors'][0]['beat'], 'chord')
        shortened = copy.deepcopy(song)
        shortened['score']['measures'].pop(1)
        shortened = tab.apply_structure_edit(shortened, dict(op='orders', orders=['A'], origins=[0]))
        shortened['orders'] = ['A']
        self.assertEqual(shortened['score']['tracks']['guitar']['lyrics'], lyrics)
        self.assertEqual(self.view(shortened, raw), dict(anchors=[], errors=[]))
        before = copy.deepcopy(song)
        with self.assertRaisesRegex(ValueError, 'orphan a measure'):
            tab.apply_structure_edit(song, dict(op='orders', orders=['A'], origins=[0]))
        self.assertEqual(song, before)
        copied = tab.capture_score_clipboard(song, 'A', ['chord'], 'oa')
        self.assertNotIn('lyrics', json.dumps(copied))
        cut, _ = tab.score_command(song, raw, dict(action='cut', occurrence='oa', track='guitar',
                                                   voice=0, beats=['chord']))
        self.assertEqual(cut['score']['tracks']['guitar']['lyrics'], lyrics)

    def test_complete_playback_plan_unchanged_and_repeat_mapping_written_once(self):
        song, raw = self.fixture('a b c d e f')
        baseline = copy.deepcopy(song)
        baseline['score']['tracks']['guitar'].pop('lyrics')
        for rate in (44100, 48000):
            self.assertEqual(tab.playback_plan(song, raw, rate), tab.playback_plan(baseline, raw, rate))
        repeated, raw = TestNativeRepeats().fixture([{'repeat_open': True}, {'repeat_close': 1}])
        baseline = copy.deepcopy(repeated)
        repeated['score']['tracks']['guitar']['lyrics'] = dict(from_measure=1, text='once twice unused')
        for rate in (44100, 48000):
            projection = tab.repeat_projection(repeated, raw, rate)
            original = tab.repeat_projection(baseline, raw, rate)
            self.assertEqual(projection.plan, original.plan)
            self.assertEqual(projection.patterns, original.patterns)
            self.assertEqual([(a['occurrence'], a['text']) for a in projection.source_view['lyrics']['anchors']],
                             [('o0', 'once'), ('o1', 'twice')])

    def test_strict_it_warns_only_for_nonempty_lyrics_metadata(self):
        for text in ('word', ''):
            song, raw = self.fixture(text, 9)
            before = copy.deepcopy((song, raw))
            result = tab.project_score(song, raw)
            self.assertEqual(sum('IT notation: lyrics omitted' in d for d in result.diagnostics),int(bool(text)))
            self.assertEqual((song, raw), before)


def percussion_ornaments_song(*, roll=16, grace=16, on_beat=True, dead=False, repeat=False):
    """Two-bar mapped-kit study; a.wav/b.wav are ordinary C5-root test samples.

    Drum 38 uses sample 1/C5; its grace drum 42 uses sample 2/G5. The trailing
    empty bar keeps standalone release placement explicit. No source audio.
    """
    roll_note = dict(note('roll', 38, 1, 38), velocity=95)
    flam_note = dict(note('flam', 38, 1, 38), velocity=95)
    if roll is not None:
        roll_note['tremolo_picking'] = dict(value=roll)
    if grace is not None:
        flam_note['grace'] = dict(fret=42, value=grace, velocity=47, on_beat=on_beat, dead=dead)
    song = dict(module=dict(title='Drum rolls and flams', speed=1, tempo=160,
                            sample_rate=44100, channels=[dict(name='Kit')]),
                samples={1: dict(file='a.wav', name='Main drum'), 2: dict(file='b.wav', name='Grace drum')},
                instruments={1: dict(name='Mapped kit', keymap=[
                    dict(notes='D-3', sample=1, play_note='C-5'),
                    dict(notes='F#3', sample=2, play_note='G-5')])},
                patterns={p: dict(rows=96, data='') for p in ('a', 'b')}, orders=['a', 'b'])
    song['score'] = dict(version=1, tracks=dict(drums=dict(tuning=[0], channels=[0], instrument=1,
                        max_fret=0, capo=0, name='Kit', clef='percussion', midi=dict(program=0, bank=128))),
                        order_ids=['first', 'second'], patterns={
                            'a': dict(row_step=[1, 24], beats=[
                                beat('roll', [0, 1], [roll_note], track='drums'),
                                beat('gap', [1, 1], [], track='drums'),
                                beat('flam', [2, 1], [flam_note], track='drums'),
                                beat('rest', [3, 1], [], track='drums')]),
                            'b': dict(row_step=[1, 24], beats=[beat('tail', [0, 1], [], value=1, track='drums')])},
                        ties=[], measures=[dict(id=f'm{i+1}', meter=[4, 4], **{
                            'from': dict(occurrence=o, at=[0, 1]), 'to': dict(occurrence=o, at=[4, 1])})
                            for i, o in enumerate(('first', 'second'))])
    if repeat:
        song['score']['measures'][0]['repeat_open'] = True
        song['score']['measures'][1]['repeat_close'] = 1
    return song


class TestPercussionOrnaments(unittest.TestCase):
    def plan(self, song):
        raw = [Pattern(p, [[Cell()] for _ in range(96)]) for p in ('a', 'b')]
        repeated = tab.repeat_projection(song, raw)
        return repeated.plan if repeated else tab.playback_plan(song, raw)

    def test_roll_rates_and_dynamics_use_tg_ticks_and_source_identity(self):
        for rate in (8, 16, 32):
            for flag, velocity in ((None, 95), ('ghost', 79), ('accent', 111), ('heavy_accent', 127)):
                song = percussion_ornaments_song(roll=rate, grace=None)
                head = song['score']['patterns']['a']['beats'][0]['notes'][0]
                if flag:
                    head[flag] = True
                before = copy.deepcopy(song)
                plan = self.plan(song)
                ons = [e for e in plan['events'] if e['type'] == 'note_on' and e['note'] == 'roll']
                offs = {e['id']: e for e in plan['events'] if e['type'] == 'note_off'}
                length = 3840 // rate
                self.assertEqual([(Fraction(*e['at']) * 960, Fraction(*offs[e['id']]['at']) * 960,
                                   e['pitch'], e['velocity']) for e in ons],
                                 [(i * length, min((i + 1) * length, 959), 38, velocity) for i in range(rate // 4)])
                self.assertTrue(all(e['source_id'] == 'first/roll' and e['instrument'] == 1 for e in ons))
                self.assertEqual(song, before)

    def test_grace_duration_dead_gate_origin_and_independent_drum_key(self):
        for value in (16, 32, 64):
            for on in (False, True):
                for at in (0, 2):
                    for dead in (False, True):
                        song = percussion_ornaments_song(roll=None, grace=value, on_beat=on, dead=dead)
                        beats = song['score']['patterns']['a']['beats']
                        source = beats[2]
                        source['at'] = [at, 1]
                        song['score']['patterns']['a']['beats'] = [source]
                        length, origin = 3840 // value, at * 960
                        shift = on or origin < length
                        g = origin if shift else origin - length
                        plan = self.plan(song)
                        self.assertEqual([(e['type'], Fraction(*e['at']) * 960, e['pitch'], e['velocity'])
                                          for e in plan['events']], [
                            ('note_on', g, 42, 47), ('note_off', g + min(length, 80) if dead else g + length, 42, 47),
                            ('note_on', origin + length if shift else origin, 38, 95), ('note_off', origin + 960, 38, 95)])
                        self.assertEqual(plan['positions'][0]['at'], [at, 1])
        for key in (1, 100):
            song = percussion_ornaments_song()
            song['score']['patterns']['a']['beats'][2]['notes'][0]['grace']['fret'] = key
            self.assertEqual(next(e['pitch'] for e in self.plan(song)['events'] if e.get('role') == 'grace'), key)

    def test_ties_repeat_and_grace_then_roll_keep_one_written_head(self):
        song = percussion_ornaments_song(repeat=True)
        beats = song['score']['patterns']['a']['beats']
        beats[1]['notes'] = [dict(note('continuation', 38, 1, 38), velocity=31,
                                 grace=dict(fret=42, value=16, velocity=15))]
        song['score']['ties'] = [{'from': dict(occurrence='first', note='roll'),
                                 'to': dict(occurrence='first', note='continuation')}]
        beats[2]['notes'][0]['tremolo_picking'] = dict(value=16)
        plan = self.plan(song)
        ons = [e for e in plan['events'] if e['type'] == 'note_on']
        self.assertFalse(any(e['note'] == 'continuation' for e in ons))
        self.assertEqual(sum(e['note'] == 'roll' for e in ons), 16)
        self.assertEqual(sum(e.get('role') == 'grace' for e in ons), 2)
        self.assertEqual(sum(e['note'] == 'flam' and 'pulse' in e for e in ons), 6)
        self.assertEqual([e['at'] for e in ons if e.get('role') == 'grace'], [[2, 1], [10, 1]])

    def test_invalid_keys_techniques_and_combinations_refuse_atomically(self):
        song = percussion_ornaments_song()
        before = copy.deepcopy(song)
        patches = [dict(grace=dict(fret=k, value=16, velocity=47)) for k in (0, 101, True)]
        patches += [dict(tremolo_picking=dict(value=v)) for v in (4, 64, True)]
        patches += [dict(trill=dict(fret=42, value=16)), dict(bend=dict(points=[])),
                    dict(harmonic=dict(type='natural')), dict(vibrato=True),
                    dict(dead=True, tremolo_picking=dict(value=16))]
        for patch in patches:
            with self.subTest(patch=patch), self.assertRaises(ValueError):
                tab.apply_score_edit(song, dict(op='note_set', pattern='a', beat='roll', note=dict(id='roll', **patch)))
            self.assertEqual(song, before)


class TestPercussion(unittest.TestCase):
    def fixture(self):
        song, raw = plan_fixture()
        track = song['score']['tracks']['guitar']
        track.update(tuning=[0] * 6, capo=0, max_fret=0, midi=dict(bank=128, program=0))
        keys = [36, 38, 42, 46, 49, 51]
        for spec in song['score']['patterns'].values():
            for b in spec['beats']:
                if b['track'] == 'guitar':
                    for n in b['notes']:
                        n.update(pitch=keys[n['string'] - 1], fret=keys[n['string'] - 1], velocity=95)
        return song, raw

    def test_bank_authority_keys_and_guitar_bounds(self):
        song, raw = self.fixture()
        before = copy.deepcopy((song, raw))
        tab.validate_score(song)
        plan = tab.playback_plan(song, raw)
        self.assertEqual({e['pitch'] for e in plan['events'] if e['type'] == 'note_on' and e['track'] == 'guitar'},
                         {36, 38, 42})
        for key in (1, 100):
            changed = tab.apply_score_edit(song, dict(op='note_set', pattern='A', beat='chord',
                                                    note=dict(id='c', pitch=key)))
            actual = changed['score']['patterns']['A']['beats'][0]['notes'][0]
            self.assertEqual((actual['pitch'], actual['fret'], actual['string']), (key, key, 2))
            tab.playback_plan(changed, raw)
        for patch in (dict(pitch=0), dict(pitch=101), dict(pitch=True),
                      dict(string=2, fret=0), dict(string=2, fret=101), dict(string=7, fret=38),
                      dict(string=2, fret=38, pitch=42)):
            with self.subTest(patch=patch), self.assertRaises(ValueError):
                tab.apply_score_edit(song, dict(op='note_set', pattern='A', beat='chord', note=dict(id='c', **patch)))
        for patch in (dict(tuning=[1, 0, 0, 0, 0, 0]), dict(capo=1), dict(capo=-1)):
            with self.subTest(patch=patch), self.assertRaisesRegex(ValueError, 'zero tuning and capo'):
                tab.apply_score_edit(song, dict(op='track_set', track='guitar',
                    value=dict(song['score']['tracks']['guitar'], **patch)))
        pitched, _ = plan_fixture()
        pitched['score']['tracks']['guitar']['clef'] = 'percussion'
        tab.validate_score(pitched)
        self.assertFalse(tab.is_percussion(pitched['score']['tracks']['guitar']))
        pitched['score']['tracks']['guitar']['midi'] = dict(bank=128, program=0)
        with self.assertRaisesRegex(ValueError, 'zero tuning and capo'):
            tab.validate_score(pitched)
        self.assertEqual((song, raw), before)

    def test_null_resolution_preserves_parent_and_reserves_explicit_lanes(self):
        song, raw = self.fixture()
        notes = song['score']['patterns']['A']['beats'][0]['notes']
        notes[0].update(string=None, fret=None, channel=4)
        view = tab.authoring_view(song, raw)
        c = next(p for p in view['positions'] if p['kind'] == 'note' and p['note'] == 'c')
        self.assertEqual((c['string'], c['fret'], c['ch']), (5, 38, 4))
        changed = tab.apply_score_edit(song, dict(op='note_set', pattern='A', beat='chord',
                                                note=dict(id='c', pitch=46)))
        actual = changed['score']['patterns']['A']['beats'][0]['notes'][0]
        self.assertEqual((actual['string'], actual['fret'], actual['channel']), (5, 46, 4))
        changed = tab.apply_score_edit(changed, dict(op='note_set', pattern='A', beat='chord',
                                                   note=dict(id='c', fret=100)))
        self.assertEqual(changed['score']['patterns']['A']['beats'][0]['notes'][0]['pitch'], 100)
        with self.assertRaisesRegex(ValueError, 'share string/channel'):
            duplicate = copy.deepcopy(song)
            duplicate['score']['patterns']['A']['beats'][0]['notes'][0].update(string=1, fret=38)
            tab.validate_score(duplicate)

    def test_pattern_pitch_edit_and_roll_move_keep_source_identity(self):
        from types import SimpleNamespace
        song, raw = self.fixture()
        before = copy.deepcopy((song, raw))
        display = tab.pattern_authoring_view(song, raw, 0, 'oa')
        cell = parse_cell(display['display_rows'][0][1])
        cell.note = 46
        score, residual = tab.translate_native_pattern_edits(song, raw,
            [(0, [dict(row=0, ch=1, cell=format_cell(cell))])], occurrences={0: 'oa'})
        self.assertFalse(residual)
        actual = score['patterns']['A']['beats'][0]['notes'][0]
        self.assertEqual((actual['id'], actual['pitch'], actual['string'], actual['fret']), ('c', 46, 2, 46))
        moved = tab.move_note(song, SimpleNamespace(patterns=raw), 0, 't1n', 13, pitch=42)
        n = next(n for b in moved['score']['patterns']['A']['beats'] for n in b['notes'] if n['id'] == 't1n')
        self.assertEqual((n['string'], n['pitch'], n['fret']), (1, 42, 42))
        self.assertEqual((song, raw), before)

    def test_track_conversion_and_transpose_are_atomic_but_metadata_is_preserved(self):
        song, raw = self.fixture()
        track = song['score']['tracks']['guitar']
        track['lyrics'] = dict(from_measure=3, text=' raw\r\ntext ')
        track['midi']['source_pan'] = dict(value=63, mixer_pan=32)
        before = copy.deepcopy(song)
        changed = tab.apply_score_edit(song, dict(op='track_set', track='guitar', value=dict(track, name='Kit')))
        self.assertEqual(changed['score']['patterns'], song['score']['patterns'])
        self.assertEqual(changed['score']['tracks']['guitar']['lyrics'], track['lyrics'])
        self.assertEqual(changed['score']['tracks']['guitar']['midi'], track['midi'])
        with self.assertRaisesRegex(ValueError, 'populated pitched/percussion'):
            tab.apply_score_edit(song, dict(op='track_set', track='guitar', value=dict(track, midi=dict(program=0))))
        pitched, _ = plan_fixture()
        with self.assertRaisesRegex(ValueError, 'populated pitched/percussion'):
            tab.apply_score_edit(pitched, dict(op='track_set', track='guitar', value=track))
        selection = dict(pattern=0, r0=0, r1=0, cols=[[1, ['note']]], occurrence='oa')
        with self.assertRaisesRegex(ValueError, 'musical transpose'):
            tab.transform_native_selections(song, raw, dict(action='transpose', semitones=1, selections=[selection]))
        tab.capture_native_clipboard(song, raw, selection)  # Its transpose0 validator must remain usable.
        converted = dict(song['score']['patterns']['A']['beats'][0], track='bass',
                         notes=[note('c', 40, 1, 0)])
        with self.assertRaisesRegex(ValueError, 'populated pitched/percussion beat'):
            tab.apply_score_edit(song, dict(op='beat_set', pattern='A', beat=converted))
        self.assertEqual(song, before)
        empty = copy.deepcopy(song)
        empty['score']['ties'] = []
        for p in empty['score']['patterns'].values():
            p['beats'] = [b for b in p['beats'] if b['track'] != 'guitar']
        tab.apply_score_edit(empty, dict(op='track_set', track='guitar', value=dict(track, midi=dict(program=0))))
        raw[1].rows[12][4] = Cell(note=46, instrument=1)
        raw[1].rows[18][4] = Cell(note=NOTE_OFF)
        with self.assertRaisesRegex(ValueError, 'musical transpose'):
            tab.transform_native_selections(song, raw, dict(action='transpose', semitones=1,
                selections=[dict(pattern=1, r0=12, r1=12, cols=[[4, ['note']]])]))

    def test_unqualified_techniques_refuse_instead_of_running_pitched_semantics(self):
        song, _ = self.fixture()
        flags = ('vibrato', 'slide', 'hammer', 'fade_in', 'tapping', 'slapping', 'popping')
        values = dict.fromkeys(flags, True)
        values.update(spelling=dict(step='C', alter=0), bend=dict(points=[]), tremolo_bar=dict(points=[]),
                      harmonic=dict(type='natural'), trill=dict(fret=38, value=16))
        before = copy.deepcopy(song)
        for key, value in values.items():
            changed = copy.deepcopy(song)
            changed['score']['patterns']['A']['beats'][0]['notes'][0][key] = value
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, 'unsupported percussion technique'):
                tab.validate_score(changed)
        for field, value in (('stroke', dict(direction='down', value=8)), ('pick_stroke', 'up'),
                             ('chord', dict(name='shape', first_fret=0, frets=[0]*6))):
            b = dict(song['score']['patterns']['A']['beats'][0], **{field: value})
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, 'percussion'):
                tab.apply_score_edit(song, dict(op='beat_set', pattern='A', beat=b))
        with self.assertRaisesRegex(ValueError, 'percussion chord'):
            tab.apply_score_edit(song, dict(op='chord_notes', pattern='A', beat='chord',
                                           chord=dict(name='shape', first_fret=0, frets=[0]*6)))
        self.assertEqual(song, before)

    def test_drum_dynamics_and_gates_match_qualified_tg_callbacks(self):
        song, raw = self.fixture()
        song['score']['ties'] = []
        song['score']['patterns']['B']['beats'] = []
        song['score']['patterns']['A']['beats'] = [
            beat('hit', [0, 1], [dict(note('hit', 38, 2, 38), velocity=95)], value=2),
            beat('next', [2, 1], [dict(note('next', 38, 2, 38), velocity=95)], value=2)]
        for flag, velocity, expected in (('ghost', 95, 79), ('ghost', 15, 15),
                                         ('accent', 95, 111), ('accent', 120, 127),
                                         ('heavy_accent', 15, 47), ('heavy_accent', 95, 127)):
            changed = tab.apply_score_edit(song, dict(op='note_set', pattern='A', beat='hit',
                note=dict(id='hit', velocity=velocity, **{flag: True})))
            before = copy.deepcopy(changed)
            attack = next(e for e in tab.playback_plan(changed, raw)['events']
                          if e['id'] == 'oa/hit' and e['type'] == 'note_on')
            with self.subTest(flag=flag, velocity=velocity):
                self.assertEqual((attack['pitch'], attack['velocity']), (38, expected))
                self.assertEqual(changed, before)
                self.assertEqual(changed['score']['patterns']['A']['beats'][0]['notes'][0]['velocity'], velocity)
        for bpm in (60, 137):
            for flag, ticks in (('staccato', 960), ('dead', bpm // 2), ('palm_mute', bpm)):
                changed = tab.apply_score_edit(song, dict(op='note_set', pattern='A', beat='hit',
                                                         note=dict(id='hit', **{flag: True})))
                changed['module']['tempo'] = bpm
                release = next(e for e in tab.playback_plan(changed, raw)['events']
                               if e['id'] == 'oa/hit' and e['type'] == 'note_off')
                with self.subTest(flag=flag, bpm=bpm):
                    self.assertEqual(Fraction(*release['at']), Fraction(ticks, 960))
        song['score']['ties'] = [dict(
            **{'from': dict(occurrence='oa', note='hit'), 'to': dict(occurrence='oa', note='next')})]
        for target, release_at in (('hit', 2), ('next', 4)):
            changed = tab.apply_score_edit(song, dict(op='note_set', pattern='A', beat=target,
                                                     note=dict(id=target, staccato=True)))
            events = tab.playback_plan(changed, raw)['events']
            with self.subTest(tied_flag=target):
                self.assertEqual(sum(e['type'] == 'note_on' for e in events), 1)
                self.assertEqual(next(e['at'] for e in events if e['type'] == 'note_off'), [release_at, 1])

    def test_let_ring_reuses_held_gates_and_preserves_existing_guards(self):
        def fixture():
            song, raw, head = TestNativeLetRing.fixture(self)
            song['score']['tracks']['guitar'].update(tuning=[0] * 6, midi=dict(bank=128, program=0))
            for b in song['score']['patterns']['A']['beats']:
                for n in b['notes']:
                    key = 36 if n['string'] == 1 else 42
                    n.update(pitch=key, fret=key, velocity=95)
            return song, raw, head

        for same_lane in (False, True):
            song, raw, head = fixture()
            if same_lane:
                song['score']['patterns']['A']['beats'][1]['notes'][0].update(string=1, pitch=38, fret=38)
            before = copy.deepcopy((song, raw))
            plan = tab.playback_plan(song, raw)
            release = next(e for e in plan['events'] if e['type'] == 'note_off' and e['id'] == 'oa/n')
            attack = next(e for e in plan['events'] if e['type'] == 'note_on' and e['id'] == 'oa/n')
            self.assertEqual((attack['pitch'], release['at']), (36, [2, 1]))
            self.assertEqual(bool(attack.get('hold')), same_lane)
            self.assertEqual((song, raw), before)
        for gate in ('staccato', 'palm_mute'):
            song, raw, head = fixture()
            head[gate] = True
            with self.subTest(gate=gate), self.assertRaisesRegex(ValueError, 'let_ring conflicts'):
                tab.playback_plan(song, raw)
        song, raw, head = fixture()
        head['let_ring'] = 1
        with self.assertRaisesRegex(ValueError, 'let_ring must be boolean'):
            tab.validate_score(song)
        song, raw, head = fixture()
        song['score']['patterns']['A']['beats'][1]['notes'][0].update(string=1, pitch=38, fret=38)
        raw[0].rows[18][0] = parse_cell('... .. v32 ...')
        with self.assertRaisesRegex(ValueError, 'held let_ring overlap cannot share raw'):
            tab.playback_plan(song, raw)
        raw[0].rows[18][0] = Cell()
        head['instrument'] = 0
        with self.assertRaisesRegex(ValueError, 'unsupported let_ring overlap'):
            tab.playback_plan(song, raw)

    def test_plain_two_voices_velocity_zero_ties_repeats_and_lyrics(self):
        song, raw = self.fixture()
        song['score']['patterns']['A']['beats'].append(
            beat('other', [1, 2], [dict(note('othern', 46, 1, 46), velocity=0, instrument=1)], voice=1))
        song['score']['tracks']['guitar']['lyrics'] = dict(from_measure=1, text='one two three four five six seven')
        song['score']['measures'] = [
            dict(id='m1', meter=[4, 4], **{'from': dict(occurrence='oa', at=[0, 1]), 'to': dict(occurrence='oa', at=[4, 1])}),
            dict(id='m2', meter=[4, 4], **{'from': dict(occurrence='ob', at=[0, 1]), 'to': dict(occurrence='ob', at=[4, 1])})]
        plan = tab.playback_plan(song, raw)
        self.assertFalse(any(e['id'] == 'ob/headn' for e in plan['events']))
        other = next(e for e in plan['events'] if e['type'] == 'note_on' and e['note'] == 'othern')
        self.assertEqual((other['pitch'], other['velocity']), (46, 0))
        lyrics = tab.authoring_view(song, raw)['lyrics']
        song['score']['measures'][0]['repeat_open'] = True
        song['score']['measures'][1]['repeat_close'] = 1
        repeated = tab.repeat_projection(song, raw)
        self.assertEqual(repeated.source_view['lyrics'], lyrics)
        self.assertEqual(sum(e['type'] == 'note_on' for e in repeated.plan['events']),
                         2 * sum(e['type'] == 'note_on' for e in plan['events']))
        self.assertEqual(yaml.safe_load(yaml.safe_dump(song)), song)

    def test_score_clipboard_kind_guard_and_same_kind_fresh_ids(self):
        from types import SimpleNamespace
        song, raw = self.fixture()
        clip = tab.capture_score_clipboard(song, 'A', ['chord'], 'oa')
        self.assertEqual(clip['track_kinds'], {'guitar': 'percussion'})
        pasted = tab.paste_score_clipboard(song, SimpleNamespace(patterns=raw), 1, 12, clip, 'ob')
        copied = pasted['score']['patterns']['B']['beats'][-1]
        self.assertEqual([(n['pitch'], n['string'], n['fret']) for n in copied['notes']],
                         [(38, 2, 38), (36, 1, 36), (42, 3, 42)])
        self.assertTrue(all(n['id'].startswith('copy_') for n in copied['notes']))
        tab.playback_plan(pasted, raw)
        untyped = copy.deepcopy(clip)
        del untyped['track_kinds']
        for invalid in (untyped, dict(clip, track_kinds={'guitar': 'pitched'}), dict(clip, track_kinds=None)):
            with self.assertRaisesRegex(ValueError, 'clipboard'):
                tab.paste_score_clipboard(song, SimpleNamespace(patterns=raw), 1, 12, invalid, 'ob')
        pitched, pitched_raw = plan_fixture()
        with self.assertRaisesRegex(ValueError, 'clipboard track conversion'):
            tab.paste_score_clipboard(pitched, SimpleNamespace(patterns=pitched_raw), 1, 12, clip, 'ob')
        ordinary = tab.capture_score_clipboard(pitched, 'A', ['chord'], 'oa')
        del ordinary['track_kinds']
        tab.paste_score_clipboard(pitched, SimpleNamespace(patterns=pitched_raw), 1, 12, ordinary, 'ob')

    def test_native_clipboard_kind_guard_and_raw_preview_lane(self):
        song, raw = self.fixture()
        selection = dict(pattern=0, r0=0, r1=0, cols=[[1, ['note']]], occurrence='oa', notes=['c'])
        clip = tab.capture_native_clipboard(song, raw, selection)
        score, _ = tab.paste_native_clipboard(song, raw, dict(pattern=1, row=12, channel=1,
                                                            clipboard=clip, occurrence='ob'))
        copied = score['patterns']['B']['beats'][-1]['notes'][0]
        self.assertEqual((copied['pitch'], copied['string'], copied['channel']), (38, 2, 1))
        pitched, pitched_raw = plan_fixture()
        with self.assertRaisesRegex(ValueError, 'clipboard track conversion'):
            tab.paste_native_clipboard(pitched, pitched_raw, dict(pattern=1, row=12, channel=1,
                                                                  clipboard=clip, occurrence='ob'))
        raw[1].rows[12][4] = Cell(note=46, instrument=1)
        raw[1].rows[18][4] = Cell(note=NOTE_OFF)
        preview = next(p for p in tab.native_raw_note_view(song, raw) if p['pitch'] == 46)
        self.assertEqual((preview['string'], preview['fret'], preview['ch']), (5, 46, 4))
        self.assertTrue(preview['adoptable'])
        raw[1].rows[12][4].note = 101
        preview = next(p for p in tab.native_raw_note_view(song, raw) if p['pitch'] == 101)
        self.assertFalse(preview['adoptable'])
        self.assertIn('1..100', preview['reason'])

    def test_strict_it_preserves_drum_keys_in_tracker_notes(self):
        song, raw = self.fixture()
        song['score']['ties'] = []
        for pattern in raw:
            pattern.rows = [[Cell() for cell in row] for row in pattern.rows]
        for spec in song['score']['patterns'].values():
            spec['beats'] = spec['beats'][:1]
            spec['beats'][0].update(at=[0, 1], written=dict(value=4))
        projected = tab.project_score(song, raw)
        self.assertTrue(any(cell.note in (36, 38, 42) for p in projected.patterns for row in p.rows for cell in row))

    def test_repeat_command_and_raw_adoption_reuse_existing_paths(self):
        song, raw = self.fixture()
        song['score']['ties'] = []
        song['score']['patterns']['A']['beats'] = song['score']['patterns']['A']['beats'][:1]
        song['score']['patterns']['B']['beats'] = []
        repeated, report = tab.score_command(song, raw, dict(action='repeat', occurrence='oa',
            track='guitar', voice=0, beats=['chord']))
        tab.playback_plan(repeated, raw)
        self.assertEqual(report['clipboard']['track_kinds'], {'guitar': 'percussion'})
        copies = repeated['score']['patterns']['A']['beats']
        self.assertEqual(len(copies), 2)
        self.assertEqual([n['pitch'] for n in copies[0]['notes']], [n['pitch'] for n in copies[1]['notes']])
        from types import SimpleNamespace
        raw[1].rows[12][4] = Cell(note=46, instrument=1)
        raw[1].rows[18][4] = Cell(note=NOTE_OFF)
        module = SimpleNamespace(patterns=raw, native_score={'view': tab.authoring_view(song, raw),
                                                            'plan': tab.playback_plan(song, raw)})
        promoted, _ = tab.promote_pattern(song, module, 1, 'guitar', [dict(row=12, ch=4)], occurrence='ob')
        n = promoted['score']['patterns']['B']['beats'][0]['notes'][0]
        self.assertEqual((n['pitch'], n['string'], n['fret'], n['channel']), (46, 5, 46, 4))


if __name__ == '__main__':
    unittest.main()
