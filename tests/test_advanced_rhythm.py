"""Exact phrase cropping and explicit overfull rhythm editing."""
import copy
import tempfile
import unittest
from fractions import Fraction
from pathlib import Path

from tests import test_tablature as fixtures
from tests.test_complex_rhythm import expressive_song, performance
from tests.test_real_arrangement import raw_for
from tests.test_gui import RATE, sine
from vulturetracker import api, gui, tablature as tab
from vulturetracker.model import Module
from vulturetracker.wavload import write_wav


def curve_song(effect='bend'):
    return expressive_song({effect: dict(points=[dict(position=0, value=0),
        dict(position=2, value=2 if effect == 'bend' else -1),
        dict(position=10, value=2 if effect == 'bend' else -1), dict(position=12, value=0)])})


def middle_paste(song):
    clip = tab.capture_score_clipboard(song, 'B', ['whole'], 'ob')
    clip['beats'][0]['written'] = dict(value=2, dots=0, tuplet=[1, 1])
    return dict(op='beats_paste', pattern=0, row=12, clipboard=clip, occurrence='oa', across=True, replace=True)


def free_cohort_song():
    song, _ = fixtures.TestPlaceFitCommand().fixture()
    song['module']['title'] = 'Independent beat groups'
    beats = song['score']['patterns']['A']['beats']
    beats[:] = [b for b in beats if b['id'] != 'r']
    beats.extend([fixtures.beat('peer', [0, 1], [fixtures.note('pn0', 59, 2, 0)], value=2, voice=1),
                  fixtures.beat('peer-tail', [2, 1], [fixtures.note('pn1', 60, 2, 1)], voice=1)])
    return song


def cohort_rest_song(deleting=False):
    song, _ = fixtures.TestPlaceFitCommand().fixture(True)
    song['module']['title'] = 'Cohort rest editing'
    beats = song['score']['patterns']['A']['beats']
    if deleting:
        tab._beat(song['score'],'A','b')['notes'] = []
    beats.extend([fixtures.beat('peer',[0,1],[fixtures.note('pn0',59,2,0)],voice=1),
                  dict(fixtures.beat('peer-tail',[1,1],[fixtures.note('pn1',60,2,1)],voice=1),cohort=1),
                  fixtures.beat('peer-rest',[2,1],[],value=2,voice=1)])
    song['score']['measures']=[dict(id='m'+oid,meter=[4,4],**{'from':dict(occurrence=oid,at=[0,1])},
        to=dict(occurrence=oid,at=[4,1])) for oid in song['score']['order_ids']]
    return song


class TestAdvancedRhythm(unittest.TestCase):
    def test_coincident_voice_rebinding_for_insert_cut_and_fit(self):
        song=cohort_rest_song();raw=raw_for(song);before=copy.deepcopy(song)
        inserted,_=tab.score_command(song,raw,dict(action='insert_rest',occurrence='oa',track='guitar',
            voice=0,at=[1,1],rest_id='inserted'))
        beats={b['id']:b for b in inserted['score']['patterns']['A']['beats']}
        self.assertEqual([beats[k]['at'] for k in ('a','b','c','inserted')],[[0,1],[2,1],[3,1],[1,1]])
        self.assertEqual(tab._cohort_key(beats['inserted']),tab._cohort_key(beats['peer-tail']))
        self.assertEqual(tab._cohort_key(beats['b']),tab._cohort_key(beats['peer-rest']))
        grown,_=tab.score_command(song,raw,dict(action='set_duration',occurrence='oa',track='guitar',voice=0,
            beats=['a'],fit='tg_duration',written=dict(value=4,dots=1,tuplet=[1,1])))
        self.assertEqual(tab._beat(grown['score'],'A','b')['at'],[3,2])
        self.assertEqual(tab._beat(grown['score'],'A','c')['at'],[5,2])
        self.assertEqual([b for b in grown['score']['patterns']['A']['beats'] if b['voice']==1],
                         [b for b in song['score']['patterns']['A']['beats'] if b['voice']==1])
        self.assertEqual(song,before)
        resting=cohort_rest_song(True);raw=raw_for(resting);before=copy.deepcopy(resting)
        cut,_=tab.score_command(resting,raw,dict(action='cut',occurrence='oa',track='guitar',voice=0,beats=['b']))
        self.assertEqual(tab._beat(cut['score'],'A','c')['at'],[1,1])
        self.assertEqual(tab._cohort_key(tab._beat(cut['score'],'A','c')),
                         tab._cohort_key(tab._beat(cut['score'],'A','peer-tail')))
        self.assertEqual(resting,before)
        annotated=copy.deepcopy(song);tab._beat(annotated['score'],'A','b')['text']='keep me'
        tab._beat(annotated['score'],'A','peer-rest')['text']='keep the destination'
        before=copy.deepcopy(annotated)
        with self.assertRaisesRegex(ValueError,'conflicting text'):
            tab.score_command(annotated,raw,dict(action='insert_rest',occurrence='oa',track='guitar',voice=0,
                at=[1,1],rest_id='inserted'))
        self.assertEqual(annotated,before)

    def test_cohort_voice_moves_transfer_shared_metadata_and_retain_text(self):
        song=cohort_rest_song(True);raw=raw_for(song)
        metadata=dict(stroke=dict(direction='up',value=4),pick_stroke='up',
                      chord=dict(name='Em',first_fret=1,frets=[0,0,0,2,2,0]))
        tab._beat(song['score'],'A','c').update(text='Keep text on the old group',**copy.deepcopy(metadata))
        before=copy.deepcopy(song)
        cut,_=tab.score_command(song,raw,dict(action='cut',occurrence='oa',track='guitar',voice=0,beats=['b']))
        beats={b['id']:b for b in cut['score']['patterns']['A']['beats']}
        for bid in ('c','peer-tail'):
            self.assertEqual({k:beats[bid][k] for k in metadata},metadata)
            self.assertNotIn('text',beats[bid])
        old=[b for b in beats.values() if b['at']==[2,1]]
        self.assertEqual([b['text'] for b in old if b.get('text')],['Keep text on the old group'])
        self.assertTrue(all(not any(k in b for k in metadata) for b in old))
        timing=tab._score_timeline(cut,raw)
        self.assertEqual(tab._stroke_delays(timing)['oa/pn1'],120)
        self.assertEqual(tab._stroke_delays(timing)['oa/c-note'],0)
        self.assertEqual(song,before)
        insert=cohort_rest_song();tab._beat(insert['score'],'A','b').update(text='Move text too',**copy.deepcopy(metadata))
        moved,_=tab.score_command(insert,raw_for(insert),dict(action='insert_rest',occurrence='oa',track='guitar',
            voice=0,at=[1,1],rest_id='inserted'))
        self.assertEqual(tab._beat(moved['score'],'A','b')['text'],'Move text too')
        self.assertEqual(tab._beat(moved['score'],'A','b')['at'],[2,1])
        self.assertEqual(tab._beat(moved['score'],'A','peer-rest')['chord'],metadata['chord'])

    def test_repeated_free_preserves_coincident_group_identity(self):
        import yaml
        song = free_cohort_song()
        raw = raw_for(song)
        request = dict(action='set_duration', occurrence='oa', track='guitar', voice=1,
                       beats=['peer'], free=True, written=dict(value=4, dots=0, tuplet=[1, 1]))
        aligned, _ = tab.score_command(song, raw, request)
        self.assertEqual(tab._beat(aligned['score'], 'A', 'b')['at'], [1, 1])
        self.assertEqual(tab._beat(aligned['score'], 'A', 'peer-tail')['at'], [1, 1])
        self.assertEqual(tab._beat(aligned['score'], 'A', 'peer-tail')['cohort'], 1)
        reopened = yaml.safe_load(api.to_yaml(aligned))
        changed, _ = tab.score_command(reopened, raw_for(reopened), dict(request, voice=0, beats=['a'],
            written=dict(value=8, dots=0, tuplet=[1, 1])))
        positions = {b['id']: b['at'] for b in changed['score']['patterns']['A']['beats']}
        self.assertEqual(positions, dict(a=[0,1], b=[1,2], c=[3,2], peer=[0,1], **{'peer-tail':[1,1]}))
        self.assertFalse(any('cohort' in b for b in changed['score']['patterns']['A']['beats']))

    def test_cut_rest_keeps_group_text(self):
        song=cohort_rest_song(True)
        tab._beat(song['score'],'A','peer-tail').pop('cohort')
        tab._beat(song['score'],'A','b')['text']='Stay with the peer'
        before=copy.deepcopy(song)
        cut,_=tab.score_command(song,raw_for(song),dict(action='cut',occurrence='oa',track='guitar',voice=0,beats=['b']))
        at_one=[b for b in cut['score']['patterns']['A']['beats'] if b['at']==[1,1]]
        self.assertEqual([b['text'] for b in at_one if b.get('text')],['Stay with the peer'])
        self.assertEqual(song,before)

    def test_annotated_fit_transfers_groups_and_refuses_consumed_metadata(self):
        metadata=dict(text='Move with this group',stroke=dict(direction='up',value=4),pick_stroke='up',
                      chord=dict(name='Em',first_fret=1,frets=[0,0,0,2,2,0]))
        for ordinary,value,dots in ((False,4,1),(True,4,1),(False,2,0)):
            with self.subTest(ordinary=ordinary,value=value,dots=dots):
                song=cohort_rest_song()
                if ordinary:tab._beat(song['score'],'A','peer-tail').pop('cohort')
                tab._beat(song['score'],'A','b').update(copy.deepcopy(metadata))
                before=copy.deepcopy(song);raw=raw_for(song)
                changed,_=tab.score_command(song,raw,dict(action='set_duration',occurrence='oa',track='guitar',
                    voice=0,beats=['a'],fit='tg_duration',written=dict(value=value,dots=dots,tuplet=[1,1])))
                moved=tab._beat(changed['score'],'A','b');self.assertEqual(moved['at'],[3,2] if dots else [2,1])
                source_group=[b for b in changed['score']['patterns']['A']['beats'] if b['at']==([1,1] if ordinary else moved['at'])]
                self.assertEqual([b['text'] for b in source_group if b.get('text')],[metadata['text']])
                for peer in (b for b in before['score']['patterns']['A']['beats'] if b['voice']==1):
                    actual=tab._beat(changed['score'],'A',peer['id'])
                    for key in ('at','written','notes'):self.assertEqual(actual[key],peer[key])
                self.assertEqual(song,before)
        song=cohort_rest_song();tab._beat(song['score'],'A','r')['text']='Keep this rest'
        before=copy.deepcopy(song)
        with self.assertRaisesRegex(ValueError,'annotated cohort'):
            tab.score_command(song,raw_for(song),dict(action='set_duration',occurrence='oa',track='guitar',
                voice=0,beats=['a'],fit='tg_duration',written=dict(value=2)))
        self.assertEqual(song,before)

    def test_cut_rest_moves_across_backing_patterns(self):
        song,_=fixtures.TestPlaceFitCommand().fixture(True)
        song['score']['patterns']['A']['beats']=[
            fixtures.beat('head',[0,1],[fixtures.note('hn',64,1,0)],value=2),
            fixtures.beat('gap',[3,1],[])]
        song['score']['patterns']['B']['beats']=[
            fixtures.beat('next',[0,1],[fixtures.note('nn',66,1,2)]),
            fixtures.beat('tail',[1,1],[],value=2),
            fixtures.beat('peer',[0,1],[fixtures.note('pn',59,2,0)],value=1,voice=1)]
        song['score']['patterns']['A']['beats'][0]['written']['dots']=1
        song['score']['patterns']['B']['beats'][1]['written']['dots']=1
        song['score']['patterns']['B']['beats'][0]['text']='Stay in B'
        song['score']['measures']=[dict(id='wide',meter=[8,4],**{'from':dict(occurrence='oa',at=[0,1])},
            to=dict(occurrence='ob',at=[4,1]))]
        before=copy.deepcopy(song)
        cut,_=tab.score_command(song,raw_for(song),dict(action='cut',occurrence='oa',track='guitar',voice=0,beats=['gap']))
        moved=next(b for b in cut['score']['patterns']['A']['beats'] if b['notes'] and b['notes'][0]['pitch']==66)
        self.assertEqual(moved['at'],[3,1]);self.assertNotIn('text',moved)
        self.assertEqual([b['text'] for b in cut['score']['patterns']['B']['beats'] if b.get('text')],['Stay in B'])
        self.assertEqual(tab._beat(cut['score'],'B','peer')['at'],[0,1])
        self.assertEqual(song,before)

    def test_coincident_metadata_and_strokes_stay_independent(self):
        song, raw = fixtures.TestPlaceFitCommand().fixture()
        beats = song['score']['patterns']['A']['beats']
        other = fixtures.beat('peer', [1,1], [fixtures.note('pn',59,2,0)], voice=1)
        other.update(cohort=1, stroke=dict(direction='down',value=8), pick_stroke='down')
        beats.append(other)
        b = tab._beat(song['score'],'A','b')
        b.update(stroke=dict(direction='up',value=16), pick_stroke='up')
        view = tab._score_timeline(song, raw)
        self.assertEqual(tab._stroke_delays(view)['oa/b-note'], 0)
        self.assertEqual(tab._stroke_delays(view)['oa/pn'], 0)
        patched = copy.deepcopy(other);patched['pick_stroke']='up'
        changed = tab.apply_score_edit(song, dict(op='beat_set',pattern='A',beat=patched))
        self.assertEqual(tab._beat(changed['score'],'A','b'),b)
        moved = tab.move_beat(changed,Module(patterns=raw),0,'peer',30)
        self.assertNotIn('cohort',tab._beat(moved['score'],'A','peer'))
        for invalid in (True,-1,128,'1'):
            bad=copy.deepcopy(song);tab._beat(bad['score'],'A','peer')['cohort']=invalid
            with self.assertRaises(ValueError):tab.validate_score(bad)
        bad=copy.deepcopy(song);tab._beat(bad['score'],'A','peer')['voice']=0
        with self.assertRaises(ValueError):tab._score_timeline(bad,raw)

    def test_coincident_copy_move_and_whole_beat_replacement(self):
        song=free_cohort_song()
        aligned,_=tab.score_command(song,raw_for(song),dict(action='set_duration',occurrence='oa',track='guitar',
            voice=1,beats=['peer'],free=True,written=dict(value=4)))
        clip=tab.capture_score_clipboard(aligned,'A',['b','peer-tail'],'oa')
        self.assertEqual([b.get('cohort',0) for b in clip['beats']],[0,1])
        aligned['score']['patterns']['B']['beats']=[]
        raw=raw_for(aligned)
        pasted=tab.paste_score_clipboard(aligned,Module(patterns=raw),1,0,clip,'ob')
        self.assertEqual([b.get('cohort',0) for b in pasted['score']['patterns']['B']['beats']],[0,1])
        self.assertEqual([b['at'] for b in pasted['score']['patterns']['B']['beats']],[[0,1],[0,1]])
        before = copy.deepcopy((aligned, clip))
        for mode, row, across in (('mix', 0, False), ('push', 0, False), ('replace', 42, True)):
            with self.subTest(mode=mode), self.assertRaisesRegex(ValueError, 'independent coincident beat groups'):
                tab.paste_score_clipboard(aligned, Module(patterns=raw), 1, row, clip, 'ob',
                                          mode=mode, across=across)
            self.assertEqual((aligned, clip), before)
        moved,_=tab.score_command(aligned,raw,dict(action='move_beats',occurrence='oa',track='guitar',voice=0,
            at=[1,1],direction='right',amount=[1,2]))
        at=tab._beat(moved['score'],'A','b')['at']
        self.assertEqual(at,[3,2]);self.assertEqual(tab._beat(moved['score'],'A','peer-tail')['at'],at)
        self.assertNotEqual(tab._cohort_key(tab._beat(moved['score'],'A','b')),
                            tab._cohort_key(tab._beat(moved['score'],'A','peer-tail')))
        replaced=tab.paste_score_clipboard(aligned,Module(patterns=raw),1,0,clip,'ob',mode='tg_replace')
        notes=[b for b in replaced['score']['patterns']['B']['beats'] if b['notes']]
        self.assertEqual([(b['voice'],b['at']) for b in notes],[(0,[0,1]),(1,[1,1])])
        self.assertFalse(any('cohort' in b for b in notes))

    def test_coincident_cleanup_preview_projection_and_guarded_edits(self):
        from vulturetracker import notation_export
        song=free_cohort_song()
        aligned,_=tab.score_command(song,raw_for(song),dict(action='set_duration',occurrence='oa',track='guitar',
            voice=1,beats=['peer'],free=True,written=dict(value=4)))
        raw=raw_for(aligned);before=copy.deepcopy(aligned)
        cleaned,_=tab.score_command(aligned,raw,dict(action='clean_beat',occurrence='oa',track='guitar',beats=['b']))
        self.assertTrue(tab._beat(cleaned['score'],'A','peer-tail')['notes'])
        self.assertFalse(tab._beat(cleaned['score'],'A','b')['notes'])
        entered,report=tab.score_command(aligned,raw,dict(action='matrix_entry',occurrence='oa',track='guitar',
            voice=1,at=[1,1],pitch=55,free=True,written=dict(value=4)))
        self.assertEqual([n['pitch'] for n in report['audition']],[60,55])
        self.assertEqual(tab._beat(entered['score'],'A','b'),tab._beat(aligned['score'],'A','b'))
        self.assertEqual(aligned,before)
        aligned['score']['measures']=[dict(id='m'+oid,meter=[4,4],**{'from':dict(occurrence=oid,at=[0,1])},
            to=dict(occurrence=oid,at=[4,1])) for oid in aligned['score']['order_ids']]
        model=notation_export._model(aligned,raw)
        groups=[b for b in model['tracks'][0].measures[0].beats if b.start==2*960]
        self.assertEqual(len(groups),2)
        self.assertEqual([[not v.empty for v in b.voices] for b in groups],[[True,False],[False,True]])

    def test_cross_bar_ring_paste_keeps_unsplit_gate_and_ties(self):
        song = expressive_song(dict(let_ring=True))
        song['score']['patterns']['D']['beats'][0]['notes'] = []
        clip = tab.capture_score_clipboard(song, 'A', ['whole'], 'oa')
        result = tab.paste_score_clipboard(song, Module(patterns=raw_for(song)), 2, 36,
            clip, 'oc', across=True, replace=True)
        attacks = [e for e in tab.playback_plan(result, raw_for(result))['events']
                   if e['id'].startswith('oc/copy_')]
        self.assertEqual([(e['type'], e['frame']) for e in attacks if e['type'] in ('note_on', 'note_off')],
                         [('note_on', 11 * 22050), ('note_off', 15 * 22050)])
        self.assertEqual(len(result['score']['ties']), 1)

    def test_paste_refuses_ring_neighbor_split_that_changes_sustain(self):
        song = expressive_song(dict(let_ring=True))
        clip = tab.capture_score_clipboard(song, 'A', ['whole'], 'oa')
        neighbor = copy.deepcopy(song['score']['patterns']['B']['beats'][0])
        neighbor.update(id='neighbor', at=[4, 1])
        neighbor['notes'][0]['id'] = 'neighbor'
        clip['beats'].append(neighbor)
        before = copy.deepcopy(song)
        with self.assertRaisesRegex(ValueError, 'let-ring timing changes'):
            tab.paste_score_clipboard(song, Module(patterns=raw_for(song)), 2, 36,
                clip, 'oc', across=True, replace=True)
        self.assertEqual(song, before)

    def test_mixed_tuplet_pickup_move_and_rebar_keep_events(self):
        from tests.test_advanced_timing import advanced_timing_song
        from vulturetracker.tgimport import _raw
        song = advanced_timing_song()
        song['module']['tempo'] = 120
        before = performance(song, raw_patterns=_raw(song))
        changed = tab.measure_command(song, dict(action='measure_meter', at=1, meter=[3, 4], to_end=True))['song']
        self.assertEqual(performance(changed, raw_patterns=_raw(changed)), before)
        moved, _ = tab.score_command(song, _raw(song), dict(action='move_beats', occurrence='first',
            track='guitar', at=[0, 1], direction='right', amount=[1, 3]))
        key = lambda e: (e['frame'], e['ch'], e['type'])
        self.assertEqual(sorted(performance(moved, raw_patterns=_raw(moved)), key=key),
                         sorted(performance(song, raw_patterns=_raw(song), shift=7350), key=key))

    def test_partial_paste_crops_both_curve_edges_exactly(self):
        for effect in ('bend', 'tremolo_bar'):
            song = curve_song(effect)
            before = copy.deepcopy(song)
            edit = middle_paste(song)
            result = tab.paste_score_clipboard(song, Module(patterns=raw_for(song)), 0, 12,
                edit['clipboard'], 'oa', across=True, replace=True)
            beats = sorted(result['score']['patterns']['A']['beats'], key=lambda b: Fraction(*b['at']))
            self.assertEqual([b['at'] for b in beats], [[0, 1], [1, 1], [3, 1]])
            peak = 2 if effect == 'bend' else -1
            self.assertEqual(beats[0]['notes'][0][effect]['points'],
                [dict(position=0, value=0), dict(position=8, value=peak), dict(position=12, value=peak)])
            self.assertEqual(beats[-1]['notes'][0][effect]['points'],
                [dict(position=0, value=peak), dict(position=4, value=peak), dict(position=12, value=0)])
            # Compare sounding pitch steps in retained portions, excluding the new key-off reset.
            old = [e for e in performance(song, after='oa/') if e['type'] == 'pitch']
            new = [e for e in performance(result, after='oa/') if e['type'] == 'pitch']
            self.assertEqual([e for e in new if e['frame'] < 22050],
                             [e for e in old if e['frame'] < 22050])
            self.assertTrue(new)
            self.assertEqual(song, before)

    def test_inexact_curve_crop_refuses_without_mutation(self):
        song = expressive_song(dict(bend=dict(points=[dict(position=0, value=0), dict(position=12, value=2)])))
        before = copy.deepcopy(song)
        with self.assertRaisesRegex(ValueError, 'crop'):
            edit = middle_paste(song)
            tab.paste_score_clipboard(song, Module(patterns=raw_for(song)), 0, 12,
                edit['clipboard'], 'oa', across=True, replace=True)
        self.assertEqual(song, before)

    def test_free_duration_overflow_and_meter_repair(self):
        song = expressive_song()
        edit = dict(action='set_duration', occurrence='oa', track='guitar', voice=0,
                    beats=['whole'], written=dict(value=1, dots=1, tuplet=[1, 1]), free=True)
        changed, report = tab.score_command(song, raw_for(song), edit)
        self.assertEqual(changed['patterns']['A']['rows'], 72)
        self.assertTrue(report['free'])
        self.assertEqual(changed['score']['measures'][0]['to']['at'], [6, 1])
        self.assertEqual(changed['score']['patterns']['B'], song['score']['patterns']['B'])
        fixed = tab.measure_command(changed, dict(action='measure_meter', at=0, meter=[3, 4], to_end=True))['song']
        self.assertEqual(performance(fixed), performance(changed))

    def test_free_duration_repacks_sounding_beats_and_refuses_unsafe_reuse(self):
        song, raw = fixtures.TestPlaceFitCommand().fixture()
        before = copy.deepcopy(song)
        edit = dict(action='set_duration', occurrence='oa', track='guitar', voice=0,
                    beats=['a'], written=dict(value=2, dots=0, tuplet=[1, 1]), free=True)
        changed, _ = tab.score_command(song, raw, edit)
        self.assertEqual([(b['id'], b['at']) for b in changed['score']['patterns']['A']['beats']],
                         [('a', [0, 1]), ('b', [2, 1]), ('r', [3, 1]), ('c', [4, 1])])
        self.assertEqual(changed['patterns']['A']['rows'], 60)
        self.assertEqual(song, before)
        song = expressive_song()
        song['orders'].append('A'); song['score']['order_ids'].append('again')
        edit.update(beats=['whole'], written=dict(value=1, dots=1, tuplet=[1, 1]))
        with self.assertRaisesRegex(ValueError, 'reused'):
            tab.score_command(song, raw_for(song), edit)
        changed, _ = tab.score_command(song, raw_for(song), dict(edit, independent=True))
        self.assertNotEqual(changed['orders'][0], changed['orders'][-1])
        self.assertEqual(changed['score']['patterns'][changed['orders'][-1]]['beats'][0]['written']['dots'], 0)

    def test_free_duration_shrink_preserves_cohorts_rests_and_annotations(self):
        song, raw = fixtures.TestPlaceFitCommand().fixture()
        song['score']['patterns']['A']['beats'][1]['text'] = 'keep this'
        peer = fixtures.beat('peer', [0, 1], [fixtures.note('peer-note', 59, 2, 0)], value=2, voice=1)
        peer_tail = fixtures.beat('peer-tail', [2, 1], [fixtures.note('peer-tail-note', 60, 2, 1)], value=2, voice=1)
        song['score']['patterns']['A']['beats'].extend([peer, peer_tail])
        before = copy.deepcopy(song)
        changed, result = tab.score_command(song, raw, dict(action='set_duration', occurrence='oa',
            track='guitar', voice=0, beats=['a'], free=True, written=dict(value=8, dots=0, tuplet=[1, 1])))
        beats = {b['id']: b for b in changed['score']['patterns']['A']['beats']}
        self.assertEqual({key: beats[key]['at'] for key in ('a','b','r','c','peer','peer-tail')},
                         dict(a=[0,1],b=[1,2],r=[2,1],c=[3,1],peer=[0,1],**{'peer-tail':[2,1]}))
        self.assertEqual(beats['b']['text'], 'keep this')
        self.assertEqual(beats['peer'], peer);self.assertEqual(beats['peer-tail'], peer_tail)
        self.assertEqual(result['selection']['beats'], ['a'])
        self.assertEqual(song, before)

    def test_free_duration_closes_raw_gaps_and_keeps_adjacent_ties(self):
        song, raw = fixtures.TestPlaceFitCommand().fixture()
        song['score']['patterns']['A']['beats'] = [b for b in song['score']['patterns']['A']['beats'] if b['id'] != 'r']
        tab._beat(song['score'],'A','b')['notes'][0].update(pitch=64,fret=0)
        song['score']['ties'] = [dict(**{'from':dict(occurrence='oa',note='a-note')},
                                   to=dict(occurrence='oa',note='b-note'))]
        changed, result = tab.score_command(song, raw, dict(action='set_duration', occurrence='oa',
            track='guitar', voice=0, beats=['a'], free=True, written=dict(value=8,dots=0,tuplet=[1,1])))
        beats = changed['score']['patterns']['A']['beats']
        self.assertEqual(tab._beat(changed['score'],'A','b')['at'],[1,2])
        self.assertEqual(tab._beat(changed['score'],'A','c')['at'],[3,2])
        rests = [b for b in beats if not b['notes']]
        self.assertEqual(rests, [])
        self.assertEqual(changed['score']['ties'],song['score']['ties'])
        self.assertEqual(result['removed_ties'],[])
        self.assertEqual(len([e for e in tab.playback_plan(changed,raw_for(changed))['events']
                             if e['type']=='note_on' and e['id'].startswith('oa/')]),2)

    def test_free_duration_approved_and_divided_overflow_fail_atomically(self):
        song, raw = fixtures.TestPlaceFitCommand().fixture()
        request = dict(action='set_duration',occurrence='oa',track='guitar',voice=0,beats=['a'],
                       free=True,written=dict(value=2,dots=0,tuplet=[1,1]))
        song['patterns']['A']['approved'] = True
        before = copy.deepcopy((song,raw))
        with self.assertRaisesRegex(ValueError,'approved'):tab.score_command(song,raw,request)
        self.assertEqual((song,raw),before)
        song['patterns']['A'].pop('approved')
        song['score']['measures'] = [dict(id='one',**{'from':dict(occurrence='oa',at=[0,1])},
            to=dict(occurrence='oa',at=[2,1]),meter=[2,4]),
            dict(id='two',**{'from':dict(occurrence='oa',at=[2,1])},to=dict(occurrence='oa',at=[4,1]),meter=[2,4])]
        before = copy.deepcopy((song,raw))
        with self.assertRaisesRegex(ValueError,'measure ending its pattern'):tab.score_command(song,raw,request)
        self.assertEqual((song,raw),before)

    def test_overfull_implicit_bar_keeps_nominal_meter_and_automatic_mode(self):
        song, raw = fixtures.TestPlaceFitCommand().fixture()
        edit = dict(action='set_duration',occurrence='oa',track='guitar',voice=0,beats=['a'],
                    free=True,written=dict(value=2,dots=0,tuplet=[1,1]))
        grown, _ = tab.score_command(song,raw,edit)
        measure = grown['score']['measures'][0]
        self.assertEqual(measure['meter'],[4,4]);self.assertEqual(measure['to']['at'],[5,1])
        errors = tab.measure_errors(grown,{p.name:len(p.rows) for p in raw_for(grown)})
        self.assertEqual([(e['errors'],e['automatic_free']) for e in errors],[(['long'],True)])
        shrunk, report = tab.score_command(grown,raw_for(grown),dict(edit,free=False,written=dict(value=8)))
        self.assertTrue(report['automatic_free'])
        self.assertEqual(tab._beat(shrunk['score'],'A','b')['at'],[1,2])
        self.assertEqual(tab._beat(shrunk['score'],'A','c')['at'],[5,2])
        # Quarter restores the note lengths; Apply measure then removes only empty backing rows.
        repaired, _ = tab.score_command(shrunk,raw_for(shrunk),dict(edit,free=False,written=dict(value=4)))
        fixed = tab.measure_command(repaired,dict(action='measure_meter',at=0,meter=[4,4]))['song']
        self.assertEqual(fixed['patterns']['A']['rows'],48)
        self.assertFalse([e for e in tab.measure_errors(fixed,{p.name:len(p.rows) for p in raw_for(fixed)})
                          if e['occurrence']=='oa'])

    def test_automatic_short_bar_matrix_and_insert_rest(self):
        song, raw = fixtures.TestPlaceFitCommand().fixture()
        song['score']['patterns']['A']['beats'] = song['score']['patterns']['A']['beats'][:1]
        song['score']['measures'] = [dict(id='m',meter=[4,4],**{
            'from':dict(occurrence='oa',at=[0,1]),'to':dict(occurrence='oa',at=[4,1])})]
        changed, _ = tab.score_command(song,raw,dict(action='matrix_entry',occurrence='oa',track='guitar',voice=0,
            at=[7,10],pitch=67,written=dict(value=8),free=False))
        added = next(b for b in changed['score']['patterns']['A']['beats'] if any(n['pitch']==67 for n in b['notes']))
        self.assertEqual(added['at'],[0,1])
        rest, _ = tab.score_command(song,raw,dict(action='insert_rest',occurrence='oa',track='guitar',voice=0,
            at=[0,1],written=dict(value=4),rest_id='inserted',free=False))
        self.assertEqual(tab._beat(rest['score'],'A','a')['at'],[1,1])
        self.assertEqual(tab._beat(rest['score'],'A','inserted')['at'],[0,1])

    def test_automatic_mode_distinguishes_internal_gap_from_late_start(self):
        song,raw=fixtures.TestPlaceFitCommand().fixture()
        song['score']['measures']=[dict(id='m',meter=[4,4],**{
            'from':dict(occurrence='oa',at=[0,1]),'to':dict(occurrence='oa',at=[4,1])})]
        tail=fixtures.beat('tail',[2,1],[fixtures.note('tail-note',66,1,2)],2)
        song['score']['patterns']['A']['beats']=[fixtures.beat('a',[0,1],[fixtures.note('a-note',64,1,0)]),tail]
        errors=tab.measure_errors(song,{p.name:len(p.rows) for p in raw})
        self.assertEqual(errors[0]['errors'],['gap']);self.assertTrue(errors[0]['automatic_free'])
        changed,report=tab.score_command(song,raw,dict(action='set_duration',occurrence='oa',track='guitar',
            voice=0,beats=['a'],written=dict(value=8)))
        self.assertTrue(report['automatic_free']);self.assertEqual(tab._beat(changed['score'],'A','tail')['at'],[1,2])
        song['score']['patterns']['A']['beats']=[tail]
        self.assertFalse(tab.measure_errors(song,{p.name:len(p.rows) for p in raw})[0]['automatic_free'])

    def test_mixed_range_uses_automatic_free_only_in_invalid_bar(self):
        song,raw=fixtures.TestPlaceFitCommand().fixture()
        song['score']['patterns']['B']['beats']=[fixtures.beat('b'+str(i),[i,1],
            [fixtures.note('bn'+str(i),64+i,1,i)]) for i in range(4)]
        song['score']['measures']=[dict(id=oid,meter=[4,4],**{
            'from':dict(occurrence=oid,at=[0,1]),'to':dict(occurrence=oid,at=[4,1])}) for oid in ('oa','ob')]
        grown,_=tab.score_command(song,raw,dict(action='set_duration',occurrence='oa',track='guitar',
            voice=0,beats=['a'],free=True,written=dict(value=2)))
        changed,report=tab.score_command(grown,raw_for(grown),dict(action='set_duration',track='guitar',voice=0,
            selection=[dict(occurrence='oa',beats=['a','b','r','c']),dict(occurrence='ob',beats=['b0'])],written=dict(value=8)))
        self.assertTrue(report['automatic_free'])
        self.assertEqual(tab._beat(changed['score'],'A','b')['at'],[1,2])
        self.assertEqual(tab._beat(changed['score'],'B','b1')['at'],[1,1])
        self.assertEqual([g['beats'] for g in report['selection']['range']],[['a','b','r','c'],['b0','rest_b0']])
        self.assertEqual(tab._beat(changed['score'],'B','rest_b0')['at'],[1,2])

    def test_free_tuplets_keep_other_voice_raw_cells_and_selection(self):
        song, raw = fixtures.TestPlaceFitCommand().fixture()
        song['score']['patterns']['A']['beats'].append(fixtures.beat('peer', [0, 1],
            [dict(fixtures.note('peer', 59, 2, 0), velocity=63)], value=1, voice=1))
        from vulturetracker.model import Cell
        raw[0].rows[4][6] = Cell(effect=24, param=32)
        original_raw = copy.deepcopy(raw)
        source = copy.deepcopy(song)
        changed, report = tab.score_command(song, raw, dict(action='set_duration', occurrence='oa',
            track='guitar', voice=0, beats=['a', 'b', 'c'], free=True,
            written=dict(value=8, dots=0, tuplet=[3, 2])))
        for identity in ('a', 'b', 'c'):
            self.assertEqual(tab.duration_quarters(tab._beat(changed['score'], 'A', identity)['written']), Fraction(1, 3))
        self.assertEqual(tab._beat(changed['score'], 'A', 'peer'), tab._beat(source['score'], 'A', 'peer'))
        self.assertEqual(report['selection']['beats'], ['a', 'b', 'c'])
        self.assertEqual(raw, original_raw)
        self.assertEqual(song, source)

    def test_free_duration_and_curve_paste_exact_history_reopen(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'song.yaml'
            write_wav(path.parent / 'tone.wav', RATE, [sine(440)])
            song = curve_song()
            song['samples'][1]['file'] = 'tone.wav'
            path.write_text('# Keep formatting\n' + api.to_yaml(song), encoding='utf-8', newline='\n')
            state = gui.State(path, headless=True)
            try:
                self.assertFalse(state.error, state.error)
                original = path.read_bytes()
                for edit in [middle_paste(song), dict(action='set_duration', occurrence='oa', track='guitar', voice=0,
                    beats=['whole'], written=dict(value=1, dots=1, tuplet=[1, 1]), free=True)]:
                    count = len(state.history)
                    (state.score_edit if 'op' in edit else state.score_command)(dict(edit, revision=state.text_sha()))
                    after = path.read_bytes()
                    self.assertEqual(len(state.history), count + 1)
                    api.compile_song(path)
                    state.undo(); self.assertEqual(path.read_bytes(), original)
                    state.undo(redo=True); self.assertEqual(path.read_bytes(), after)
                    state.undo(); self.assertEqual(path.read_bytes(), original)
            finally:
                state.close()


if __name__ == '__main__':
    unittest.main()
