"""Retune and track setup share one safe native transaction."""
import copy
from pathlib import Path
import tempfile
import unittest

from tests import test_tablature as model_helpers
from tests.test_tablature_sync import complete_song_seed
from tests.test_gui import sine, RATE
from vulturetracker import api, gui, tablature as tab, tgimport
from vulturetracker.wavload import write_wav


class TestPartAdaptation(unittest.TestCase):
    def test_repeat_and_capo_keep_performed_visits(self):
        song = complete_song_seed()
        song['score']['ties'] = []  # This repeat intentionally skips the tied third-bar predecessor.
        song['score']['measures'][0]['repeat_open'] = True
        song['score']['measures'][1].update(repeat_close=1, endings=[1])
        song['score']['measures'][2]['endings'] = [2]
        raw = tgimport._raw(song)
        before = tab.repeat_projection(song, raw).plan
        changed, _ = tab.score_command(song, raw, dict(action='retune', track='guitar', capo=-1))
        after = tab.repeat_projection(changed, raw).plan
        self.assertEqual(before['occurrences'], after['occurrences'])
        expected = copy.deepcopy(before['events'])
        for event in expected:
            if event.get('track') == 'guitar' and 'pitch' in event:
                event['pitch'] -= 1
        self.assertEqual(expected, after['events'])

    def test_automatic_extended_strings_and_atomic_metadata_preserve_peers_and_raw(self):
        for count in (7, 12, 25):
            with self.subTest(strings=count):
                song, raw = model_helpers.TestRetuneCommand().fixture()
                before = copy.deepcopy(song)
                old = song['score']['tracks']['guitar']
                tuning = old['tuning'] + [35] * (count - 6)
                changed, report = tab.score_command(song, raw, dict(action='retune', track='guitar',
                    tuning=tuning, auto_channels=True, setup=dict(name='Extended lead', color='#325a70')))
                track = changed['score']['tracks']['guitar']
                self.assertEqual(track['channels'], list(range(6)) + list(range(7, count + 1)))
                self.assertEqual(len(changed['module']['channels']), count + 1)
                self.assertEqual(track['name'], 'Extended lead')
                self.assertEqual(report['added_channels'], list(range(7, count + 1)))
                self.assertEqual(changed['patterns'], song['patterns'])
                self.assertEqual(changed['score']['ties'], song['score']['ties'])
                self.assertEqual(changed['score']['tracks']['bass'], song['score']['tracks']['bass'])
                expanded = copy.deepcopy(raw)
                for pattern in expanded:
                    for row in pattern.rows:
                        row.extend(tab.Cell() for _ in report['added_channels'])
                self.assertEqual(tab.playback_plan(song,raw)['events'], tab.playback_plan(changed,expanded)['events'])
                self.assertEqual(song, before)

    def test_reduction_keeps_raw_channels_and_explicit_capacity_refusals(self):
        song, raw = model_helpers.TestRetuneCommand().fixture(low=False)
        before = copy.deepcopy(song)
        changed, report = tab.score_command(song, raw, dict(action='retune',track='guitar',
            tuning=[64,59,55,50],auto_channels=True))
        self.assertEqual(changed['module'], song['module'])
        self.assertEqual(report['retired_channels'], [4,5])
        self.assertEqual(changed['patterns'], song['patterns'])
        for extra, error in ((dict(auto_channels=1),'boolean'),
                             (dict(auto_channels=True,channels=list(range(7))),'not both'),
                             (dict(auto_channels=True,setup=dict(instrument=0)),'instrument')):
            with self.subTest(extra=extra), self.assertRaisesRegex(ValueError,error):
                tab.score_command(song,raw,dict(action='retune',track='guitar',tuning=[64,59,55,50,45,40,35],**extra))
        self.assertEqual(song,before)
        song['module']['channels']=64
        with self.assertRaisesRegex(ValueError,'64 channels'):
            tab.score_command(song,raw,dict(action='retune',track='guitar',tuning=[64,59,55,50,45,40,35],auto_channels=True))

    def test_harmonic_node_change_refuses_but_reordered_strings_preserve_sound(self):
        song, raw = model_helpers.TestRetuneCommand().fixture(low=False)
        note = tab._beat(song['score'],'A','chord')['notes'][0]
        note.update(pitch=71,string=1,fret=7,velocity=95,harmonic=dict(type='natural'))
        # Remove the original first-string chord tone so this is a valid chord.
        tab._beat(song['score'],'A','chord')['notes']=[note]
        before=copy.deepcopy(song)
        with self.assertRaisesRegex(ValueError,'harmonic or string-dependent'):
            tab.score_command(song,raw,dict(action='retune',track='guitar',tuning=[62,57,53,48,43,38]))
        self.assertEqual(song,before)
        changed,_=tab.score_command(song,raw,dict(action='retune',track='guitar',tuning=[59,64,55,50,45,40]))
        sounding=lambda s: [{k:v for k,v in e.items() if k!='ch'} for e in tab.playback_plan(s,raw)['events']]
        self.assertEqual(sorted(sounding(song),key=str),sorted(sounding(changed),key=str))

    def test_setup_history_reopen_and_failure_are_one_transaction(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'song.yaml'
            write_wav(path.parent/'tone.wav',RATE,[sine(440)])
            song=complete_song_seed()
            path.write_text('# owner comment\n'+api.to_yaml(song),encoding='utf-8',newline='\n')
            st=gui.State(path,headless=True)
            try:
                self.assertFalse(st.error,st.error)
                before=path.read_bytes()
                request=dict(action='retune',track='guitar',tuning=[64,59,55,50,45,38,35],
                    auto_channels=True,setup=dict(name='Seven-string lead',color='#aabbcc',midi=dict(program=27,bank=0)))
                st.score_command(dict(request,revision=st.text_sha()))
                after=path.read_bytes()
                self.assertEqual(len(st.history),1)
                self.assertEqual(st.song['score']['tracks']['guitar']['channels'],[0,1,2,3,4,5,19])
                self.assertEqual(st.song['score']['tracks']['guitar']['name'],'Seven-string lead')
                self.assertEqual(st.song['patterns'],song['patterns'])
                api.compile_song(path)
                with self.assertRaises(ValueError):
                    st.score_command(dict(request,setup=dict(name='Must not persist',midi=dict(program=999)),revision=st.text_sha()))
                self.assertEqual(path.read_bytes(),after)
                self.assertEqual(len(st.history),1)
                st.undo();self.assertEqual(path.read_bytes(),before)
                st.undo(redo=True);self.assertEqual(path.read_bytes(),after)
            finally: st.close()
            reopened=gui.State(path,headless=True)
            try:
                self.assertFalse(reopened.error,reopened.error)
                self.assertEqual(path.read_bytes(),after)
                reopened.undo();self.assertEqual(path.read_bytes(),before)
            finally: reopened.close()


if __name__=='__main__': unittest.main()
