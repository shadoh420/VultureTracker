"""TuxGuitar editing-command oracle.

Runs the same edit sequence in TuxGuitar 2.1.0 (its own managers, headless: tg_edit_oracle/TgEditProbe.java) and in
VultureTracker's score commands (gui.State, as the TAB page sends them), then compares the two documents read back
through VultureTracker's .tg reader: measures (meter, repeats, endings), beats (voice, start, written duration),
notes (string, fret, pitch) and ties. Rests are compared apart, since TuxGuitar fills gaps with rests where a song
here may leave them implicit. Needs TuxGuitar 2.1.0 and a JDK; run it under the CPU lease:

Tied-duration cases report raw invalid tiedNote flags and explicitly apply TG's Fix tied note action before
comparison. Native edits detach broken links immediately; TG duration alone can leave a silent invalid continuation.
Rhythm ranges also retain the raw TG result and compare a named live-target reference that skips detached
original voices. This deliberate native difference avoids TG's stale-rest edits; it is not raw action parity.
Section cases retain raw paste/Cut results beside named references for automatic bar extension, untouched
destination fragments, original phrase timing and each selected rest. These are explicit native differences.
Adaptation cases retain raw TG output when native keeps grace/trill sounding pitches or refuses note loss and
unsafe natural-harmonic changes. Those named safety references are not raw TG editing parity.

    coord.ps1 run -Kind cpu -Exec "python tools/tg_edit_oracle.py --json scratch/tg-oracle.json"

Options: --case NAME (repeatable; default all, --list prints them), --java PATH, --tuxguitar DIR, --json OUT.
Exit status 1 when any case differs.
"""
import argparse
import copy
import json
import subprocess
import sys
import tempfile
from fractions import Fraction
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
PROBE = Path(__file__).resolve().parent / 'tg_edit_oracle' / 'TgEditProbe.java'

# name: TuxGuitar operations (TgEditProbe syntax). Bars of the base song: 1 = E D C quarters and a quarter rest;
# 2 = a half note and two quarters, voice 2 a whole rest; 3 = an eighth triplet, a dotted quarter, an eighth and a
# quarter tied into bar 4's first half note; 4 = two half notes.
CASES = {
    'cohort annotations insert': ['insert_rest 4 1/1 0'],
    'cohort annotations insert shared sounding exact stroke': ['insert_rest 4 1/1 0'],
    'cohort annotations caret deletion': ['rest_delete_probe 4 1/1 0'],
    'cohort annotations caret deletion exact stroke': ['rest_delete_probe 4 1/1 0'],
    'cohort annotations ordinary insert exact stroke': ['insert_rest 4 1/1 0'],
    'cohort annotations ordinary caret deletion exact stroke': ['rest_delete_probe 4 1/1 0'],
    'cohort annotations ordinary caret deletion selected rest exact stroke': ['rest_delete_probe 4 1/1 0'],
    'cohort annotations fit dotted exact stroke': ['duration 4 0/1 0 4 1 1 1'],
    'cohort annotations ordinary fit dotted exact stroke': ['duration 4 0/1 0 4 1 1 1'],
    'cohort annotations fit half exact stroke': ['duration 4 0/1 0 2 0 1 1'],
    'cohort rest insertion right': ['insert_rest 4 1/1 0', 'snapshot shifted', 'free on', 'duration 4 0/1 0 8 0 1 1'],
    'cohort rest caret deletion': ['rest_delete_probe 4 1/1 0', 'snapshot shifted', 'free on', 'duration 4 0/1 0 8 0 1 1'],
    'cohort rest fit shortening': ['duration 4 0/1 0 8 0 1 1', 'snapshot fitted', 'free on', 'duration 4 0/1 0 4 0 1 1'],
    'cohort rest fit growth': ['duration 4 0/1 0 4 1 1 1', 'snapshot fitted', 'free on', 'duration 4 0/1 0 8 0 1 1'],
    'free duration shrink': ['free on', 'duration 4 0/1 0 8 0 1 1'],
    'free duration grow': ['free on', 'duration 4 0/1 0 2 0 1 1'],
    'free duration paired unequal shrink': ['free on', 'duration 4 0/1 0 8 0 1 1'],
    'free duration paired unequal grow': ['free on', 'duration 4 0/1 0 2 0 1 1'],
    'free duration explicit rest': ['free on', 'duration 4 1/1 0 8 0 1 1'],
    'free duration earlier gap': ['free on', 'duration 4 2/1 0 8 0 1 1'],
    'free duration tied shrink': ['free on', 'duration 4 0/1 0 8 0 1 1'],
    'free duration tied grow': ['free on', 'duration 4 0/1 0 2 0 1 1'],
    'free duration overfull then shrink': ['free on', 'duration 4 0/1 0 2 0 1 1', 'snapshot overfull', 'duration 4 0/1 0 8 0 1 1'],
    'free duration invalid automatic': ['free on', 'duration 4 0/1 0 2 0 1 1', 'free off', 'duration 4 0/1 0 8 0 1 1'],
    'free duration sparse earlier gap': ['drop_rests_probe 4', 'snapshot sparse', 'free on', 'duration 4 2/1 0 8 0 1 1'],
    'free duration sparse aligned cohorts': ['drop_rests_probe 4', 'snapshot sparse', 'free on', 'duration 4 0/1 1 4 0 1 1'],
    'free duration sparse aligned cohorts repeat': ['drop_rests_probe 4', 'snapshot sparse', 'free on',
        'duration 4 0/1 1 4 0 1 1', 'snapshot aligned', 'duration 4 0/1 0 8 0 1 1'],
    'free duration sparse selected cohorts': ['drop_rests_probe 4', 'snapshot sparse', 'free on', 'range_duration 4 4 0 8 0 1 1'],
    'clipboard replace one voice over two': ['beats_replace_probe 1 0/1 1 0/1 3 0/1'],
    'clipboard replace unequal source voices': ['beats_replace_probe 1 0/1 1 0/1 3 0/1'],
    'clipboard replace short over long': ['beats_replace_probe 1 0/1 1 0/1 3 0/1'],
    'clipboard replace explicit source rest': ['beats_replace_probe 1 0/1 1 2/1 3 0/1'],
    'clipboard replace adjacent unequal cohorts': ['beats_replace_probe 1 0/1 1 1/1 3 0/1'],
    'clipboard replace whole beat metadata': ['beats_replace_probe 1 0/1 1 0/1 3 0/1'],
    'clipboard replace incoming destination tie': ['beats_replace_probe 1 0/1 1 0/1 4 0/1'],
    'clipboard replace bar overflow': ['beats_replace_probe 1 0/1 1 0/1 3 3/1'],
    'clipboard replace song end insufficient room': ['beats_replace_probe 1 0/1 1 0/1 4 3/1'],
    'stem group eighth pair': ['stem_group 1 1/2 0 up'],
    'stem group quarter singleton': ['stem_group 1 0/1 1 down'],
    'stem group triplet': ['stem_group 2 1/3 0 down'],
    'stem group both voices': ['stem_group 2 1/3 0 down', 'stem_group 2 2/3 1 up'],
    'stem group rest break': ['stem_group 3 1/2 0 up'],
    'stem group implicit gap': ['stem_group 3 0/1 0 down'],
    'stem group rest unchanged': ['stem_group 3 1/4 0 up'],
    'stem group compound first': ['stem_group 4 1/1 0 down'],
    'stem group compound second': ['stem_group 4 3/2 0 up'],
    'stem group auto reversal': ['stem_group 1 0/1 0 up', 'stem_group 1 1/2 0 auto'],
    'voice expression upper ghost': ['range_expression 1 2 ghost true 0'],
    'voice expression lower velocity': ['range_expression 1 2 velocity 47 1'],
    'voice expression lower dead': ['tempo 160','range_expression 1 2 dead true 1'],
    'voice expression separate flags': ['range_expression 1 2 ghost true 0','range_expression 1 2 accent true 1'],
    'voice pitch upper semitone': ['range_semitone 1 2 1 0'],
    'voice pitch lower semitone': ['range_semitone 1 2 1 1'],
    'voice pitch lower atomic refusal': ['range_semitone 1 2 -1 1'],
    'voice pitch semitone reversal': ['range_semitone 1 2 1 0','range_semitone 1 2 -1 0'],
    'voice pitch local semitone': ['range_semitone 1 1 1 0'],
    'voice pitch upper string': ['range_strings 1 2 1 0'],
    'voice deletion upper range': ['beats_cut 1 0/1 2 3/1 0'],
    'voice deletion lower range': ['beats_cut 1 0/1 2 3/1 1'],
    'voice deletion local upper': ['beats_cut 1 0/1 1 1/1 0'],
    'voice deletion local lower': ['beats_cut 1 0/1 1 1/1 1'],
    'adapt uniform down': ['retune 62,57,53,48,43,38'],
    'adapt uniform up': ['retune 65,60,56,51,46,41'],
    'adapt Drop D': ['retune 64,59,55,50,45,38'],
    'adapt seven strings': ['retune 64,59,55,50,45,40,35'],
    'adapt four playable strings': ['retune 64,59,55,50'],
    'adapt reordered tuning': ['retune 40,45,50,55,59,64'],
    'adapt negative capo': ['capo -2'],
    'adapt grace uniform down': ['retune 62,57,53,48,43,38'],
    'adapt trill uniform down': ['retune 62,57,53,48,43,38'],
    'adapt grace Drop D': ['retune 64,59,55,50,45,38'],
    'adapt trill Drop D': ['retune 64,59,55,50,45,38'],
    'adapt natural harmonic uniform down': ['retune 62,57,53,48,43,38'],
    'adapt natural harmonic reordered': ['retune 40,45,50,55,59,64'],
    'adapt unplayable strings': ['retune 80,75,71,66,61,56'],
    'band range ringing and vibrato': ['measure_clean 3 4', 'range_expression 1 2 let_ring true', 'range_expression 1 2 vibrato true'],
    'band range tap slap pop exclusivity': ['measure_clean 3 4', 'range_expression 1 2 tapping true',
        'range_expression 1 2 slapping true', 'range_expression 1 2 popping true'],
    'band range hammer and clear': ['measure_clean 3 4', 'range_expression 1 2 hammer true', 'range_expression 1 2 hammer false'],
    'band range fade and clear': ['measure_clean 3 4', 'range_expression 1 2 fade_in true', 'range_expression 1 2 fade_in false'],
    'rehearsal track clone metadata notes ties': ['track_clone 1'],
    'rehearsal track clone move': ['track_clone 1', 'track_move 2 1'],
    'rehearsal track clone move remove': ['track_clone 1', 'track_move 2 1', 'track_remove 2'],
    'rehearsal track independent clone reference': ['track_clone 1', 'track_independent_channel 2'],
    'rehearsal track independent clone move reference': ['track_clone 1', 'track_independent_channel 2', 'track_move 2 1'],
    'song measure markers and line break insert': ['marker 1 Theme', 'line_break 1', 'measure_paste_portable 1 2 3 insert 1 markers'],
    'song measure marker omitted by choice': ['marker 1 Theme', 'measure_paste_portable 1 1 2 replace 1'],
    'song measure structural headers replace': ['repeat_open 1', 'repeat_close 2 1', 'ending 2 1',
        'marker 1 Theme', 'line_break 1', 'measure_paste_portable 1 2 3 replace 1 markers'],
    'song measure meter replace': ['time_signature 4 3 4 one', 'measure_paste_portable 4 4 1 replace 1', 'fix_ties'],
    'song custom move right third': ['move_beats 1 0/1 0 right 1/3'],
    'section paste across bar line': ['beats_replace 4 2/1 4 2/1 1 3/1', 'fix_ties'],
    'section copy incoming tie edge': ['beats_replace 4 0/1 4 0/1 1 0/1', 'fix_ties'],
    'section copy outgoing tie edge': ['beats_replace 3 3/1 3 3/1 1 0/1', 'fix_ties'],
    'section repeat extends song': ['beats_repeat 3 0/1 4 2/1'],
    'section paste extends song': ['remove_unused_voice 2 1', 'beats_replace 1 0/1 2 3/1 4 2/1'],
    'section paste preserves peer-rest timing': ['beats_replace 1 0/1 2 3/1 4 2/1'],
    'section insert before tie continuation': ['measure_add 4', 'fix_ties'],
    'section remove tie head': ['measure_remove 3 3', 'fix_ties'],
    'section remove tie continuation': ['measure_remove 4 4', 'fix_ties'],
    'section meter splits final half note': ['time_signature 4 3 4 to_end'],
    'section meter splits incoming tied note': ['time_signature 4 1 4 to_end'],
    'section meter reflows mixed rhythm': ['time_signature 3 3 4 to_end', 'fix_ties'],
    'section cut incoming tie edge': ['beats_cut 4 0/1 4 0/1', 'fix_ties'],
    'section cut selected rests': ['clean_beat 2 0/1', 'beats_cut 1 3/1 2 0/1'],
    'section move beats right extends song': ['move_beats 1 0/1 0 right'],
    'section move tie tail left': ['move_beats 4 0/1 0 left', 'fix_ties'],
    'rhythm implicit middle longer': ['duration 4 0/1 0 2 0 1 1'],
    'rhythm implicit middle dotted': ['duration 4 0/1 0 4 1 1 1'],
    'rhythm implicit trailing longer': ['duration 3 0/1 0 2 0 1 1'],
    'rhythm implicit trailing dotted': ['duration 3 0/1 0 4 1 1 1'],
    'rhythm implicit trailing no room': ['duration 3 0/1 0 2 1 1 1'],
    'rhythm alternating range longer': ['range_duration 1 1 0 2 0 1 1'],
    'rhythm alternating range shorter': ['range_duration 1 1 0 8 0 1 1'],
    'rhythm alternating range dotted': ['range_duration 1 1 0 4 1 1 1'],
    'rhythm alternating range triplet': ['range_duration 1 1 0 4 0 3 2'],
    'rhythm full range no room': ['range_duration 2 2 0 2 0 1 1'],
    'rhythm mixed range no room': ['range_duration 1 2 0 2 0 1 1'],
    'rhythm partial trailing rest': ['duration 3 0/1 0 4 1 1 1'],
    'rhythm partial middle rest double dotted': ['duration 4 0/1 0 4 2 1 1'],
    'rhythm partial middle rest five quarters': ['duration 4 0/1 0 2 0 8 5'],
    'rhythm partial middle rest quintuplet': ['duration 4 0/1 0 2 0 5 4'],
    'rhythm peer whole rest partial': ['duration 4 0/1 0 4 1 1 1'],
    'rhythm peer sounding partial': ['duration 4 0/1 0 4 1 1 1'],
    'rhythm peer destination partial': ['duration 4 0/1 0 4 1 1 1'],
    'rhythm peer shared onset partial': ['duration 4 0/1 0 4 1 1 1'],
    'tied head shorter repaired': ['duration 1 0/1 0 8 0 1 1', 'fix_ties'],
    'tied head longer fit': ['duration 1 0/1 0 2 0 1 1', 'fix_ties'],
    'tied middle dotted fit': ['duration 1 1/1 0 4 1 1 1', 'fix_ties'],
    'tied middle triplet repaired': ['duration 1 1/1 0 8 0 3 2', 'fix_ties'],
    'tied continuation longer': ['duration 4 0/1 0 2 0 1 1', 'fix_ties'],
    'tied continuation shorter': ['duration 4 0/1 0 8 0 1 1', 'fix_ties'],
    'tied continuation dotted': ['duration 4 0/1 0 4 1 1 1', 'fix_ties'],
    'tied continuation triplet': ['duration 4 0/1 0 4 0 3 2', 'fix_ties'],
    'tied cross-measure range shorter repaired': ['range_duration 3 4 0 8 0 1 1 3/1 0/1 strict', 'fix_ties'],
    'tied head bar overflow unchanged': ['duration 3 3/1 0 2 0 1 1', 'fix_ties'],
    'boundary duration longer strict': ['range_duration 3 4 0 8 0 1 1 15/4 0/1 strict'],
    'boundary duration longer fit': ['range_duration 3 4 0 8 0 1 1 15/4 0/1'],
    'boundary duration shorter strict': ['range_duration 3 4 0 32 0 1 1 15/4 0/1 strict'],
    'range duration shorter selected voice': ['measure_clean 3 4', 'range_duration 1 2 0 8 0 1 1'],
    'range duration dotted triplet spelling': ['measure_clean 3 4', 'range_duration 1 2 0 8 1 3 2'],
    'range dynamics and palm mute': ['measure_clean 3 4', 'range_expression 1 2 velocity 63', 'range_expression 1 2 palm_mute true'],
    'range articulation exclusivity and clear': ['measure_clean 3 4', 'range_expression 1 2 ghost true', 'range_expression 1 2 accent true',
        'range_expression 1 2 heavy_accent true', 'range_expression 1 2 heavy_accent false'],
    'range staccato and dead': ['measure_clean 3 4', 'tempo 160', 'range_expression 1 2 staccato true', 'range_expression 1 2 dead true'],
    'range transpose first two bars': ['range_transpose 1 2 2'],
    'range strings first two bars': ['range_strings 1 2 1'],
    'cross-measure phrase paste into empty spans': ['measure_clean 1', 'measure_clean 2', 'beats_paste 3 0/1 4 0/1 1 0/1'],
    'cross-measure phrase replacement': ['beats_replace 3 0/1 4 0/1 1 0/1'],
    'cross-measure Cut selected notes': ['beats_cut 3 0/1 4 0/1'],
    'cross-measure Repeat existing spans': ['beats_repeat 1 0/1 2 3/1'],
    'cross-measure Repeat one voice': ['remove_unused_voice 2 1', 'beats_repeat 1 0/1 2 3/1'],
    'fret on a rest': ['fret 1 3/1 0 1 5 4 0 1 1'],
    'duration longer': ['duration 1 0/1 0 2 0 1 1'],
    'duration dotted': ['duration 1 0/1 0 4 1 1 1'],
    'duration triplet': ['duration 1 0/1 0 8 0 3 2'],
    'insert rest strict with room': ['insert_rest 1 1/1 0'],
    'insert rest strict full bar': ['insert_rest 4 0/1 0'],
    'insert rest free': ['free on', 'insert_rest 2 0/1 0'],
    'insert rest free before a tie': ['free on', 'insert_rest 4 0/1 0'],
    'clean beat': ['clean_beat 1 1/1'],
    'remove unused voice': ['remove_unused_voice 2 1'],
    'move beats left': ['move_beats 1 1/1 0 left'],
    'move beats right after add': ['measure_add 5', 'move_beats 1 0/1 0 right'],
    'measure add': ['measure_add 2'],
    'measure remove': ['measure_remove 1 2'],
    'measure remove across a tie': ['measure_remove 2 3'],
    'measure clean': ['measure_clean 1'],
    'measure paste replace': ['measure_paste 1 1 2 replace 1'],
    'measure paste replace over a tie': ['measure_paste 1 1 3 replace 1'],
    'measure paste insert': ['measure_paste 1 2 2 insert 1'],
    'repeats and ending': ['repeat_open 1', 'repeat_close 2 1', 'ending 2 1'],
    'ending that skips a tie': ['repeat_open 2', 'repeat_close 3 1', 'ending 3 1'],
    'time signature grow': ['time_signature 4 5 4 one'],
    'time signature to end': ['time_signature 2 5 4 to_end'],
    'time signature shrink adds a bar': ['time_signature 4 2 4 to_end'],
    'transpose up 2': ['transpose 2'],
    'retune half step down': ['retune 63,58,54,49,44,39'],
    'retune drop D': ['retune 64,59,55,50,45,38'],
    'capo 2': ['capo 2'],
}

TUNING = [64, 59, 55, 50, 45, 40]


def base_song(boundary_duration=False, tied_duration=False, rhythm=False, expression_voices=False):
    def note(nid, string, fret):
        return dict(id=nid, string=string, fret=fret, pitch=TUNING[string - 1] + fret, velocity=95)

    def beat(bid, at, value, notes, dots=0, tuplet=(1, 1), voice=0):
        return dict(id=bid, track='guitar', voice=voice, at=list(at), written=dict(value=value, dots=dots, tuplet=list(tuplet)),
                    notes=notes)
    bars = [
        [beat('b1', (0, 1), 4, [note('n1', 1, 0)]), beat('b2', (1, 1), 4, [note('n2', 2, 3)]),
         beat('b3', (2, 1), 4, [note('n3', 2, 1)]), beat('b4', (3, 1), 4, [])],
        [beat('b1', (0, 1), 2, [note('n1', 1, 3)]), beat('b2', (2, 1), 4, [note('n2', 3, 2)]),
         beat('b3', (3, 1), 4, [note('n3', 3, 0)]), beat('v2', (0, 1), 1, [], voice=1)],
        [beat('b1', (0, 1), 8, [note('n1', 2, 0)], tuplet=(3, 2)), beat('b2', (1, 3), 8, [note('n2', 2, 1)], tuplet=(3, 2)),
         beat('b3', (2, 3), 8, [note('n3', 2, 3)], tuplet=(3, 2)), beat('b4', (1, 1), 4, [note('n4', 1, 0)], dots=1),
         beat('b5', (5, 2), 8, [note('n5', 1, 3)]), beat('b6', (3, 1), 4, [note('n6', 1, 5)])],
        [beat('b1', (0, 1), 2, [note('n1', 1, 5)]), beat('b2', (2, 1), 2, [note('n2', 2, 5)])],
    ]
    if boundary_duration:
        bars[2] = [beat('b1', (0, 1), 4, [note('n1', 1, 0)]),
                   beat('b2', (1, 1), 4, [note('n2', 2, 3)]),
                   beat('b3', (2, 1), 4, [note('n3', 2, 1)]),
                   beat('b4', (3, 1), 8, [note('n4', 1, 3)], dots=1),
                   beat('end_rest', (15, 4), 16, [])]
        bars[3] = [beat('first', (0, 1), 16, [note('n1', 1, 5)]),
                   beat('gap', (1, 4), 8, [], dots=1),
                   beat('b2', (1, 1), 4, [note('n2', 2, 3)]),
                   beat('b3', (2, 1), 4, [note('n3', 2, 1)]),
                   beat('b4', (3, 1), 4, [note('n4', 1, 0)])]
    if tied_duration:
        bars[0] = [beat('b1', (0, 1), 4, [note('n1', 1, 0)]),
                   beat('b2', (1, 1), 4, [note('n2', 1, 0)]),
                   beat('b3', (2, 1), 4, [note('n3', 1, 0)]), beat('b4', (3, 1), 4, [])]
        bars[3] = [beat('b1', (0, 1), 4, [note('n1', 1, 5)]), beat('b2', (1, 1), 2, [], dots=1)]
    if rhythm:
        bars[0] = [beat('b1', (0, 1), 4, [note('n1', 1, 0)]), beat('r1', (1, 1), 4, []),
                   beat('b2', (2, 1), 4, [note('n2', 2, 3)]), beat('r2', (3, 1), 4, [])]
        bars[1] = [beat(f'b{i}', (i, 1), 4, [note(f'n{i}', 1, i)]) for i in range(4)]
        bars[2] = [beat('b1', (0, 1), 4, [note('n1', 1, 0)]), beat('b2', (1, 1), 4, [note('n2', 2, 3)]),
                   beat('r1', (2, 1), 2, [])]
        bars[3] = [beat('b1', (0, 1), 4, [note('n1', 1, 0)]), beat('b2', (1, 1), 4, [note('n2', 2, 3)]),
                   beat('r1', (2, 1), 4, []), beat('b3', (3, 1), 4, [note('n3', 3, 2)])]
        if isinstance(rhythm, str) and rhythm.startswith('rhythm implicit trailing '):
            bars[2] = [beat('b1', (0, 1), 4, [note('n1', 1, 0)]), beat('b2', (1, 1), 4, [note('n2', 2, 3)]),
                       beat('b3', (2, 1), 4, [note('n3', 3, 2)]), beat('r1', (3, 1), 4, [])]
        if rhythm == 'rhythm peer whole rest partial':
            bars[3].append(beat('peer', (0, 1), 1, [], voice=1))
        elif rhythm == 'rhythm peer sounding partial':
            bars[3].append(beat('peer', (0, 1), 1, [note('peer', 6, 0)], voice=1))
        elif rhythm == 'rhythm peer destination partial':
            bars[3] += [beat('peer1', (0, 1), 4, [], dots=1, voice=1),
                        beat('peer2', (3, 2), 8, [note('peer', 6, 0)], voice=1),
                        beat('peer3', (2, 1), 2, [], voice=1)]
        elif rhythm == 'rhythm peer shared onset partial':
            bars[3] += [beat('peer1', (0, 1), 2, [], voice=1),
                        beat('peer2', (2, 1), 4, [note('peer', 6, 0)], voice=1),
                        beat('peer3', (3, 1), 4, [], voice=1)]
    if expression_voices:
        for i in range(2):
            bars[i]=[b for b in bars[i] if b['voice']==0]+[beat('lower',(0,1),1,[note('low',6,i*3)],voice=1)]
    names, ids = [f'm{i + 1}' for i in range(4)], [f'o{i + 1}' for i in range(4)]
    return {
        'module': {'title': 'TG oracle', 'tempo': 120, 'speed': 2, 'channels': [{'name': f'String {i + 1}'} for i in range(6)]},
        'samples': {1: {'file': 'tone.wav', 'name': 'Tone'}}, 'instruments': {1: {'sample': 1}},
        'patterns': {n: {'rows': 48, 'data': ''} for n in names}, 'orders': names,
        'score': {'version': 1, 'tracks': {'guitar': {'tuning': TUNING, 'capo': 0, 'instrument': 1, 'channels': list(range(6)),
                                                      'midi': {'program': 25}}},
                  'order_ids': ids, 'patterns': {n: {'row_step': [1, 12], 'beats': bars[i]} for i, n in enumerate(names)},
                  'measures': [dict(id=n, meter=[4, 4], **{'from': dict(occurrence=o, at=[0, 1]), 'to': dict(occurrence=o, at=[4, 1])})
                               for n, o in zip(names, ids)],
                  'ties': [] if boundary_duration or rhythm else [
                      {'from': {'occurrence': 'o3', 'note': 'n6'}, 'to': {'occurrence': 'o4', 'note': 'n1'}}] + ([
                      {'from': {'occurrence': 'o1', 'note': 'n1'}, 'to': {'occurrence': 'o1', 'note': 'n2'}},
                      {'from': {'occurrence': 'o1', 'note': 'n2'}, 'to': {'occurrence': 'o1', 'note': 'n3'}}]
                      if tied_duration else [])}}


def free_duration_song(name):
    """Free edits retain every cohort, including rests and unequal peer voices."""
    song = base_song()
    song['score']['ties'] = []
    def beat(i, at, value=4, voice=0, rest=False):
        string = 1 if voice == 0 else 6
        return dict(id=f'v{voice}b{i}', track='guitar', voice=voice, at=[at, 1],
                    written=dict(value=value, dots=0, tuplet=[1, 1]),
                    notes=[] if rest else [dict(id=f'v{voice}n{i}', string=string, fret=i,
                                                pitch=TUNING[string - 1] + i, velocity=95)])
    beats = [beat(i, i) for i in range(4)]
    if 'paired unequal' in name:
        beats += [beat(0, 0, 2, 1), beat(2, 2, 4, 1), beat(3, 3, 4, 1)]
    elif 'explicit rest' in name:
        beats[1]['notes'] = []
    elif 'earlier gap' in name:
        beats[0]['notes'] = []
        beats[1]['notes'] = []
    elif 'cohorts' in name:
        beats = [beat(0, 0), beat(1, 1), beat(3, 3), beat(0, 0, 2, 1), beat(2, 2, 4, 1)]
    elif 'tied' in name:
        beats[1]['notes'][0].update(fret=0, pitch=64)
        song['score']['ties'] = [dict(**{'from': dict(occurrence='o4', note='v0n0')},
                                    to=dict(occurrence='o4', note='v0n1'))]
    song['score']['patterns']['m4']['beats'] = beats
    if 'ordinary' in name:
        for beat in beats:
            beat.pop('cohort', None)
    return song


def cohort_rest_song(name):
    """Two legal independent onset-one groups in a complete two-voice bar."""
    song = base_song(); song['score']['ties'] = []
    beats = []
    for voice, at, value, rest in ((0,0,4,False),(0,1,4,'deletion' in name),(0,2,4,False),(0,3,4,True),
                                   (1,0,4,False),(1,1,4,False),(1,2,2,True)):
        string = 1 if voice == 0 else 6
        beats.append(dict(id=f'v{voice}b{at}',track='guitar',voice=voice,at=[at,1],written=dict(value=value,dots=0,tuplet=[1,1]),
            notes=[] if rest else [dict(id=f'v{voice}n{at}',string=string,fret=at,pitch=TUNING[string-1]+at,velocity=95)],
            **({'cohort':1} if voice==1 and at==1 else {})))
    song['score']['patterns']['m4']['beats'] = beats
    if name.startswith('cohort annotations '):
        chosen = next(b for b in beats if b['voice']==0 and b['at']==(
            [2,1] if ('deletion' in name or 'shared sounding' in name) and 'selected rest' not in name else [1,1]))
        chosen.update(text='Transfer text',stroke=dict(direction='up',value=4 if 'exact stroke' in name else 16),pick_stroke='up',
                      chord=dict(name='Em',first_fret=1,frets=[0,0,0,2,2,0]))
        if 'shared sounding' in name:
            peer = next(b for b in beats if b['voice']==1 and b['at']==[2,1])
            peer['notes']=[dict(id='v1n2',string=6,fret=2,pitch=TUNING[5]+2,velocity=95)]
    return song


def canonical(song):
    """Each bar in play order: meter, repeats, endings; its first track's beats with written durations and notes."""
    score = song['score']
    track = next(iter(score['tracks']))
    tied = {(t['to']['occurrence'], t['to']['note']) for t in score.get('ties', [])}
    bars, rests = [], []
    for name, oid in zip(map(str, song['orders']), score['order_ids']):
        m = next((m for m in score.get('measures', []) if m['from']['occurrence'] == oid), {})
        header = dict(meter=m.get('meter'), repeat_open=bool(m.get('repeat_open')), repeat_close=m.get('repeat_close', 0),
                      endings=sorted(m.get('endings', [])), marker=(m.get('marker') or {}).get('title'),
                      line_break=bool(m.get('line_break')))
        beats = sorted((b for b in score['patterns'].get(name, {}).get('beats', []) if b['track'] == track),
                       key=lambda b: (b.get('voice', 0), Fraction(*b['at'])))
        def shape(b):
            w = b['written']
            return [b.get('voice', 0), str(Fraction(*b['at'])), w['value'], w.get('dots', 0), list(w.get('tuplet', [1, 1]))]
        bars.append(dict(header=header, notes=[shape(b) + [sorted([n.get('string'), n.get('fret'), n['pitch'],
                                                                   (oid, n['id']) in tied, n.get('velocity',95),
                                                                   [bool(n.get(k)) for k in ('ghost','accent','heavy_accent','staccato','palm_mute','dead',
                                                                       'let_ring','vibrato','hammer','slide','fade_in','tapping','slapping','popping')]] for n in b['notes'])]
                                               for b in beats if b['notes']]))
        rests.append([shape(b) for b in beats if not b['notes']])
    return dict(tuning=score['tracks'][track]['tuning'], capo=score['tracks'][track].get('capo', 0), bars=bars), rests


def canonical_tracks(song):
    """Compare every ordered track without treating native routing or imported local IDs as notation."""
    values, rests = [], []
    for tid, track in song['score']['tracks'].items():
        part = copy.deepcopy(song)
        part['score']['tracks'] = {tid: track}
        value, silence = canonical(part)
        value['metadata'] = {k: track.get(k) for k in ('name', 'clef', 'key', 'color', 'lyrics', 'stem')}
        values.append(value); rests.append(silence)
    return dict(bars=values), rests


def stem_song():
    """Beam groups, peer voices, explicit rests, and a compound meter."""
    song = base_song()
    score = song['score']
    score['ties'] = []
    def beat(index, at, value=8, voice=0, rest=False, tuplet=(1, 1)):
        string = 1 if voice == 0 else 6
        return dict(id=f'v{voice}b{index}', track='guitar', voice=voice,
                    at=list(Fraction(at).as_integer_ratio()),
                    written=dict(value=value, dots=0, tuplet=list(tuplet)),
                    notes=[] if rest else [dict(id=f'v{voice}n{index}', string=string,
                                               fret=index % 4, pitch=TUNING[string - 1] + index % 4, velocity=95)])
    score['patterns']['m1']['beats'] = [beat(i, Fraction(i, 2)) for i in range(8)] + [
        beat(i, i, value=4, voice=1) for i in range(4)]
    score['patterns']['m2']['beats'] = [
        beat(i, Fraction(i, 3), voice=v, tuplet=(3, 2)) for v in range(2) for i in range(3)] + [
        beat(i + 3, i + 1, value=4, voice=v, rest=(i == 0)) for v in range(2) for i in range(3)]
    score['patterns']['m3']['beats'] = [beat(0, 0, value=16), beat(1, '1/4', value=16, rest=True),
        beat(2, '1/2', value=16), beat(3, '3/4', value=16, rest=True)] + [
        beat(i + 3, i, value=4) for i in range(1, 4)]
    score['patterns']['m4']['beats'] = [beat(i, Fraction(i, 2)) for i in range(6)]
    song['patterns']['m4']['rows'] = 36
    score['measures'][3]['meter'] = [6, 8]
    score['measures'][3]['to']['at'] = [3, 1]
    return song


def clipboard_replace_song(name):
    """Small cohorts expose raw replaceBeats clearing, cursor advance and metadata."""
    song = base_song()
    score = song['score']
    score['ties'] = []
    def beat(index, at, value=4, voice=0, rest=False):
        string = 1 if voice == 0 else 6
        return dict(id=f'v{voice}b{index}', track='guitar', voice=voice,
                    at=list(Fraction(at).as_integer_ratio()),
                    written=dict(value=value, dots=0, tuplet=[1, 1]),
                    notes=[] if rest else [dict(id=f'v{voice}n{index}', string=string,
                        fret=index % 4, pitch=TUNING[string - 1] + index % 4, velocity=95)])
    for pattern in score['patterns'].values():
        pattern['beats'] = [beat(i, i, voice=v) for v in range(2) for i in range(4)]
    source = [beat(i, i) for i in range(4)]
    if name.endswith(('unequal source voices', 'adjacent unequal cohorts')):
        source += [beat(0, 0, value=2, voice=1), beat(2, 2, value=2, voice=1)]
    elif name.endswith('short over long'):
        source = [beat(0, 0, value=8), beat(10, '1/2', value=8)] + [beat(i, i) for i in range(1, 4)]
        score['patterns']['m3']['beats'] = [beat(i, i, value=2, voice=v) for v in range(2) for i in (0, 2)]
    elif name.endswith('explicit source rest'):
        source = [beat(0, 0), beat(1, 1, rest=True), beat(2, 2, value=2)]
    elif name.endswith(('bar overflow', 'song end insufficient room')):
        source = [beat(0, 0, value=1)]
    elif name.endswith('whole beat metadata'):
        source[0].update(text='Source text', stem='up')
        score['patterns']['m3']['beats'][0].update(text='Destination text', stem='down')
    elif name.endswith('incoming destination tie'):
        head = score['patterns']['m3']['beats'][3]['notes'][0]
        tail = score['patterns']['m4']['beats'][0]['notes'][0]
        tail.update(fret=head['fret'], pitch=head['pitch'])
        score['ties'] = [dict(**{'from': dict(occurrence='o3', note=head['id']),
                                'to': dict(occurrence='o4', note=tail['id'])})]
    score['patterns']['m1']['beats'] = source
    return song


def canonical_clipboard(song):
    result, rests = canonical(song)
    result['beat_metadata'] = [[[b.get('voice', 0), str(Fraction(*b['at'])),
                                {k: b[k] for k in ('text', 'stem', 'chord', 'stroke') if k in b}]
        for b in sorted(song['score']['patterns'][str(name)]['beats'],
                        key=lambda b: (b.get('voice', 0), Fraction(*b['at'])))
        if any(k in b for k in ('text', 'stem', 'chord', 'stroke'))] for name in song['orders']]
    return result, rests


def canonical_cohorts(song):
    from vulturetracker.tablature import _beat_cohorts, _cohort_strokes, _cohort_key
    song = copy.deepcopy(song)
    groups = []
    for name in song['orders']:
        beats = song['score']['patterns'][str(name)]['beats']
        shared = _cohort_strokes(beats)
        for b in beats:
            b.update(shared[_cohort_key(b)])
        groups.append([[str(Fraction(*g[0]['at'])), sorted(b.get('voice',0) for b in g),
                        {k:g[0][k] for k in ('stroke','pick_stroke','chord') if k in g[0]}]
                       for g in _beat_cohorts(beats)])
    result, rests = canonical_clipboard(song)
    result['beat_groups'] = groups
    return result, rests


def canonical_stems(song):
    result, rests = canonical(song)
    track = next(iter(song['score']['tracks']))
    result['stems'] = [[[b.get('voice', 0), str(Fraction(*b['at'])), b.get('stem', 'auto')]
                        for b in sorted(song['score']['patterns'][str(name)]['beats'],
                                        key=lambda b: (b.get('voice', 0), Fraction(*b['at'])))
                        if b['track'] == track and b['notes']] for name in song['orders']]
    return result, rests


def adaptation_song(name):
    """Small real note/effect fixtures sharing the normal manager oracle path."""
    song = base_song()
    song['module']['channels'].append({'name': 'Spare seventh string'})
    first = song['score']['patterns']['m1']['beats'][0]['notes'][0]
    if 'Drop D' in name:
        first.update(string=6, fret=0, pitch=40)
    if 'grace' in name:
        first['grace'] = dict(fret=2, value=16, velocity=95, on_beat=True)
    elif 'trill' in name:
        first['trill'] = dict(fret=2, value=16)
    elif 'harmonic' in name:
        first.update(fret=7, pitch=71, harmonic=dict(type='natural', data=0))
    return song


def canonical_adaptation(song):
    result, rests = canonical(song)
    track = next(iter(song['score']['tracks']))
    result['effects'] = [[{k: copy.deepcopy(n[k]) for k in ('grace', 'trill', 'harmonic') if k in n}
                          for b in sorted(song['score']['patterns'][str(name)]['beats'],
                                          key=lambda b: (b.get('voice', 0), Fraction(*b['at'])))
                          if b['track'] == track for n in b['notes']] for name in song['orders']]
    return result, rests


class Ours:
    """The same operations through gui.State's score commands, as the TAB page sends them."""

    def __init__(self, folder, song):
        from tests.test_gui import RATE, sine
        from vulturetracker import api, gui
        from vulturetracker.wavload import write_wav
        write_wav(folder / 'tone.wav', RATE, [sine(220)])
        (folder / 'song.yaml').write_text(api.to_yaml(song), encoding='utf-8')
        self.st, self.free = gui.State(folder / 'song.yaml', headless=True), False

    def run(self, edit):
        return self.st.score_command(dict(edit, revision=self.st.text_sha()))

    def where(self, bar, at=None, voice=None):
        song = self.st.song
        oid, name = song['score']['order_ids'][int(bar) - 1], str(song['orders'][int(bar) - 1])
        beats = song['score']['patterns'].get(name, {}).get('beats', [])
        if at is None:
            return oid, beats
        pos = Fraction(at)
        return oid, [b for b in beats if Fraction(*b['at']) == pos and (voice is None or b.get('voice', 0) == int(voice))]

    def apply(self, line):
        a = line.split()
        track = next(iter(self.st.song['score']['tracks']))   # the .tg reader names it t1
        spec = self.st.song['score']['tracks'][track]
        written = lambda v, d, n, t: dict(value=int(v), dots=int(d), tuplet=[int(n), int(t)])
        if a[0] == 'free':
            self.free = a[1] == 'on'
        elif a[0] in ('snapshot', 'drop_rests_probe'):
            pass  # Diagnostic/setup only; sparse native inputs are prepared before State.
        elif a[0] == 'tempo':
            self.st.song_edit([dict(op='module',key='tempo',value=int(a[1]))])
        elif a[0] == 'track_independent_channel':
            pass  # Native track cloning already allocates independent tracker channels.
        elif a[0] in ('track_clone', 'track_move', 'track_remove'):
            selected = list(self.st.song['score']['tracks'])[int(a[1]) - 1]
            self.run(dict(action=a[0], track=selected, **(dict(to=int(a[2]) - 1) if a[0] == 'track_move' else
                                                       dict(remove_notes=True) if a[0] == 'track_remove' else {})))
        elif a[0] in ('beats_paste', 'beats_replace', 'beats_replace_probe', 'beats_cut', 'beats_repeat'):
            song = self.st.song
            start, stop = int(a[1]) - 1, int(a[3]) - 1
            groups = []
            for i in range(start, stop + 1):
                name, oid = str(song['orders'][i]), song['score']['order_ids'][i]
                ids = [b['id'] for b in song['score']['patterns'][name]['beats'] if b['track'] == track and
                       (i != start or Fraction(*b['at']) >= Fraction(a[2])) and
                       (i != stop or Fraction(*b['at']) <= Fraction(a[4]))]
                groups.append(dict(occurrence=oid, beats=ids))
            if a[0] in ('beats_cut', 'beats_repeat'):
                self.run(dict(action=a[0][6:], track=track, selection=groups,
                              voice=int(a[5]) if a[0] == 'beats_cut' and len(a) > 5 else 0))
                return
            clip = self.st.score_clipboard(dict(revision=self.st.text_sha(), selection=groups))['clipboard']
            dest = int(a[5]) - 1
            name = str(song['orders'][dest]); step = Fraction(*song['score']['patterns'][name]['row_step'])
            pi = next(i for i, p in enumerate(self.st.mod.patterns) if p.name == name)
            self.st.score_edit(dict(op='beats_paste', revision=self.st.text_sha(), pattern=pi,
                occurrence=song['score']['order_ids'][dest], row=list((Fraction(a[6]) / step).as_integer_ratio()),
                clipboard=clip, across=True, replace=a[0].startswith('beats_replace'),
                **({'mode': 'tg_replace'} if a[0] == 'beats_replace_probe' else {})))
        elif a[0] == 'fret':
            oid, _ = self.where(a[1])
            s, f = int(a[4]), int(a[5])
            self.run(dict(action='place', occurrence=oid, beat=dict(
                id='oracle_beat', track=track, voice=int(a[3]), at=list(Fraction(a[2]).as_integer_ratio()),
                written=written(*a[6:10]), notes=[dict(id='oracle_note', string=s, fret=f, velocity=95,
                                                       pitch=spec['tuning'][s - 1] + spec.get('capo', 0) + f)])))
        elif a[0] == 'duration':
            oid, beats = self.where(a[1], a[2], a[3])
            self.run(dict(action='set_duration', occurrence=oid, track=track, voice=int(a[3]), beats=[beats[0]['id']],
                          written=written(*a[4:8]), fit='tg_duration', **({'free': True} if self.free else {})))
        elif a[0] == 'stem_group':
            oid, beats = self.where(a[1], a[2], a[3])
            self.run(dict(action='set_stem', occurrence=oid, track=track, beat=beats[0]['id'], stem=a[4]))
        elif a[0] == 'fix_ties':
            # Native duration edits detach broken links immediately. TG 2.1.0 requires
            # its explicit Fix tied note action; never hide that difference in readback.
            pass
        elif a[0] == 'insert_rest':
            oid, beats = self.where(a[1], a[2], a[3])
            self.run(dict(action='insert_rest', occurrence=oid, track=track, voice=int(a[3]),
                          at=list(Fraction(a[2]).as_integer_ratio()), written=beats[0]['written'] if beats else written(4, 0, 1, 1),
                          rest_id='oracle_rest', **({'free': True} if self.free else {})))
        elif a[0] == 'rest_delete_probe':
            oid, beats = self.where(a[1], a[2], a[3])
            self.run(dict(action='cut', occurrence=oid, track=track, voice=int(a[3]), beats=[beats[0]['id']]))
        elif a[0] == 'clean_beat':
            oid, beats = self.where(a[1], a[2])
            self.run(dict(action='clean_beat', occurrence=oid, track=track, beats=[b['id'] for b in beats]))
        elif a[0] == 'remove_unused_voice':
            oid, beats = self.where(a[1])
            self.run(dict(action='remove_unused_voice', occurrence=oid, track=track, beats=[b['id'] for b in beats]))
        elif a[0] == 'move_beats':
            oid, _ = self.where(a[1])
            self.run(dict(action='move_beats', occurrence=oid, track=track, voice=int(a[3]),
                          at=list(Fraction(a[2]).as_integer_ratio()), direction=a[4],
                          **(dict(amount=list(Fraction(a[5]).as_integer_ratio())) if len(a) > 5 else {})))
        elif a[0] == 'measure_add':
            self.run(dict(action='measure_add', at=int(a[1]) - 1, count=1))
        elif a[0] == 'measure_remove':
            self.run(dict(action='measure_remove', **{'from': int(a[1]) - 1, 'to': int(a[2]) - 1}))
        elif a[0] == 'measure_clean':
            self.run(dict(action='measure_clean', track=track, **{'from': int(a[1]) - 1, 'to': int(a[2] if len(a)>2 else a[1]) - 1}))
        elif a[0] == 'measure_paste_portable':
            from vulturetracker.tablature import measure_segment
            markers = len(a) > 6 and a[6] == 'markers'
            clip = measure_segment(self.st.song, int(a[1]) - 1, int(a[2]) - 1, copy_markers=markers)
            self.run(dict(action='measure_paste', mode=a[4], at=int(a[3]) - 1, count=int(a[5]),
                          segment=clip, track=track, copy_headers=True, copy_markers=markers))
        elif a[0] == 'measure_paste':
            song = self.st.song
            first, last = int(a[1]) - 1, int(a[2]) - 1
            units = []
            for i in range(first, last + 1):
                name, oid = str(song['orders'][i]), song['score']['order_ids'][i]
                m = next((m for m in song['score']['measures'] if m['from']['occurrence'] == oid), None)
                units.append(dict(pattern=name, rows=song['patterns'][name]['rows'], row_step=song['score']['patterns'][name]['row_step'],
                                  beats=copy.deepcopy([b for b in song['score']['patterns'][name]['beats'] if b['track'] == track]),
                                  measure=m and {k: v for k, v in m.items() if k not in ('id', 'from', 'to', 'marker')}))
            ids = song['score']['order_ids']
            ties = [{s: dict(unit=ids.index(t[s]['occurrence']) - first, note=t[s]['note']) for s in ('from', 'to')}
                    for t in song['score']['ties'] if all(first <= ids.index(t[s]['occurrence']) <= last for s in ('from', 'to'))]
            self.run(dict(action='measure_paste', mode=a[4], at=int(a[3]) - 1, count=int(a[5]), track=track,
                          segment=dict(tracks=[track], units=units, ties=ties)))
        elif a[0] in ('repeat_open', 'repeat_close', 'ending', 'marker', 'line_break'):
            oid, _ = self.where(a[1])
            measure = copy.deepcopy(next(m for m in self.st.song['score']['measures'] if m['from']['occurrence'] == oid))
            if a[0] == 'repeat_open':
                measure['repeat_open'] = not measure.get('repeat_open')
            elif a[0] == 'repeat_close':
                measure['repeat_close'] = int(a[2])
            elif a[0] == 'ending':
                measure['endings'] = [i + 1 for i in range(8) if int(a[2]) >> i & 1]
            elif a[0] == 'marker':
                measure['marker'] = dict(title=a[2])
            else:
                measure['line_break'] = True
            measure = {k: v for k, v in measure.items() if v not in (False, 0, [])}
            self.st.score_edit(dict(op='measure_set', measure=measure, revision=self.st.text_sha()))
        elif a[0] == 'time_signature':
            self.run(dict(action='measure_meter', at=int(a[1]) - 1, meter=[int(a[2]), int(a[3])], to_end=a[4] == 'to_end'))
        elif a[0] in ('range_transpose', 'range_strings', 'range_semitone', 'range_expression', 'range_duration'):
            groups=[dict(occurrence=self.where(i)[0],beats=[b['id'] for b in self.where(i)[1] if b['track']==track])
                    for i in range(int(a[1]),int(a[2])+1)]
            if a[0]=='range_duration':
                if len(a)>8:
                    for i, group in enumerate(groups, int(a[1])):
                        group['beats']=[b['id'] for b in self.where(i)[1] if b['id'] in group['beats'] and
                            (i!=int(a[1]) or Fraction(*b['at'])>=Fraction(a[8])) and
                            (i!=int(a[2]) or Fraction(*b['at'])<=Fraction(a[9]))]
                self.run(dict(action='set_duration',track=track,selection=groups,voice=int(a[3]),
                    **({} if a[-1]=='strict' else dict(fit='tg_duration')),
                    **({'free': True} if self.free else {}),
                    written=dict(value=int(a[4]),dots=int(a[5]),tuplet=[int(a[6]),int(a[7])])))
            elif a[0]=='range_expression':
                self.run(dict(action='set_expression',track=track,selection=groups,
                    voice=int(a[5]) if len(a)>5 else 0,
                    changes={a[3]:int(a[4]) if a[3]=='velocity' else a[4]=='true'}))
            else:
                extra = dict(scope='selection',semitones=int(a[3])) if a[0]=='range_transpose' else dict(direction=int(a[3]),voice=int(a[4]) if len(a)>4 else 0)
                action={'range_transpose':'transpose','range_strings':'shift_strings','range_semitone':'shift_pitch'}[a[0]]
                self.run(dict(action=action,track=track,selection=groups,**extra))
        elif a[0] == 'transpose':
            self.run(dict(action='transpose', semitones=int(a[1]), track=track, scope='track', all_tracks=False,
                          apply_to_chords=True, try_keep_strings=True))
        elif a[0] in ('retune', 'capo'):
            tuning = [int(x) for x in a[1].split(',')] if a[0] == 'retune' else spec['tuning']
            channels = list(spec['channels'][:len(tuning)])
            if len(channels) < len(tuning):
                channels += [c for c in range(len(self.st.song['module']['channels'])) if c not in channels][:len(tuning)-len(channels)]
            self.run(dict(action='retune', track=track, tuning=tuning, channels=channels,
                          capo=int(a[1]) if a[0] == 'capo' else spec.get('capo', 0), max_fret=spec.get('max_fret', 29), keep='pitch'))
        else:
            raise ValueError(f'unknown operation {line}')


def diff(a, b, path=''):
    if type(a) is not type(b) or not isinstance(a, (dict, list)):
        return [] if a == b else [f'{path}: TuxGuitar {a!r} / here {b!r}']
    if isinstance(a, dict):
        return [d for k in sorted(set(a) | set(b)) for d in diff(a.get(k), b.get(k), f'{path}.{k}')]
    out = [d for i, (x, y) in enumerate(zip(a, b)) for d in diff(x, y, f'{path}[{i}]')]
    return out + ([f'{path}: TuxGuitar has {len(a)} items, here {len(b)}'] if len(a) != len(b) else [])


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--case', action='append', help='a case name (repeatable); default every case')
    ap.add_argument('--list', action='store_true', help='print the case names and their TuxGuitar operations')
    ap.add_argument('--java', default=r'C:\Program Files\Java\jdk-24\bin\java.exe', help='a JDK 11+ java (runs the probe source)')
    ap.add_argument('--tuxguitar', default=r'C:\Program Files\tuxguitar', help='the TuxGuitar 2.1.0 installation')
    ap.add_argument('--json', help='write every result here')
    args = ap.parse_args(argv)
    if args.list:
        for name, ops in CASES.items():
            print(f'{name}: {"; ".join(ops)}')
        return 0
    unknown = [c for c in args.case or [] if c not in CASES]
    if unknown:
        ap.error(f'unknown case {unknown[0]!r}; --list shows them')
    if not Path(args.java).exists() or not (Path(args.tuxguitar) / 'lib' / 'tuxguitar-lib.jar').exists():
        ap.error('needs a JDK (--java) and TuxGuitar 2.1.0 (--tuxguitar)')
    from vulturetracker import api, tgimport
    results = {}
    with tempfile.TemporaryDirectory(prefix='tg-oracle-') as tmp:
        tmp = Path(tmp)
        song = base_song()
        data, _ = tgimport.native_to_tg(song, tgimport._raw(song), channels={'guitar': {'program': 25, 'bank': 0}})
        (tmp / 'base.tg').write_bytes(data)
        start, _ = tgimport.read_tg(data)   # both sides start from what TuxGuitar reads
        start['samples'], start['instruments'] = song['samples'], song['instruments']
        for name in args.case or CASES:
            ops = CASES[name]
            if name.startswith(('free duration ', 'cohort rest ', 'cohort annotations ')):
                ops = ['snapshot initial', *ops, 'snapshot final']
            compare = (canonical_cohorts if name.startswith('cohort annotations ') else canonical_clipboard if name.startswith('clipboard replace ') else canonical_stems if name.startswith('stem group ') else canonical_adaptation if name.startswith('adapt ')
                       else canonical_tracks if name.startswith('rehearsal track ') else canonical)
            folder = tmp / f'case{len(results)}'
            folder.mkdir()
            case_start, source = start, tmp / 'base.tg'
            if name.startswith(('cohort annotations ', 'cohort rest ', 'free duration ', 'boundary duration ', 'tied ', 'rhythm ', 'adapt ', 'voice expression ', 'voice pitch ', 'voice deletion ', 'stem group ', 'clipboard replace ')):
                fixture=cohort_rest_song(name) if name.startswith(('cohort rest ', 'cohort annotations ')) else free_duration_song(name) if name.startswith('free duration ') else clipboard_replace_song(name) if name.startswith('clipboard replace ') else stem_song() if name.startswith('stem group ') else adaptation_song(name) if name.startswith('adapt ') else base_song(boundary_duration=name.startswith('boundary duration '),
                                  tied_duration=name.startswith('tied '), rhythm=name if name.startswith('rhythm ') else False,
                                  expression_voices=name.startswith(('voice expression ', 'voice pitch ', 'voice deletion ')))
                data, _=tgimport.native_to_tg(fixture,tgimport._raw(fixture),channels={'guitar':{'program':25,'bank':0}})
                source=folder/'base.tg';source.write_bytes(data)
                case_start, _=tgimport.read_tg(data)
                case_start['samples'],case_start['instruments']=song['samples'],song['instruments']
                if name.startswith('adapt '):
                    case_start['module']['channels'].append({'name': 'Spare seventh string'})
            (folder / 'ops.txt').write_text('\n'.join(ops) + '\n')
            run = subprocess.run([args.java, '--class-path', str(Path(args.tuxguitar) / 'lib' / '*'), str(PROBE),
                                  str(source), str(folder / 'ops.txt'), str(folder / 'tg.tg')],
                                 capture_output=True, text=True)
            result = dict(ops=ops)
            if name.startswith(('free duration ', 'cohort rest ', 'cohort annotations ')) and args.json:
                retained = Path(args.json).parent / name.replace(' ', '-')
                retained.mkdir(parents=True, exist_ok=True)
                for filename, content in [('input.tg', source.read_bytes()), ('ops.txt', (folder / 'ops.txt').read_bytes()),
                                          ('stdout.txt', run.stdout.encode()), ('stderr.txt', run.stderr.encode())]:
                    (retained / filename).write_bytes(content)
                if (folder / 'tg.tg').exists():
                    (retained / 'raw.tg').write_bytes((folder / 'tg.tg').read_bytes())
                result['raw_tuxguitar_directory'] = str(retained)
            if run.stdout.strip():
                result['tuxguitar_diagnostics'] = run.stdout.strip().splitlines()
            if name in ('section repeat extends song', 'section paste extends song', 'section paste preserves peer-rest timing'):
                # TG's raw paste neither reserves enough space nor reliably grows
                # at the song end. Preserve its raw outcome, then compare native
                # automatic extension to the explicit TG add-bars workflow.
                result['raw_tuxguitar_returncode'] = run.returncode
                result['raw_tuxguitar_diagnostics'] = run.stderr.strip().splitlines()
                if not run.returncode:
                    try:
                        raw_song, _ = tgimport.read_tg((folder / 'tg.tg').read_bytes())
                        result['raw_tuxguitar_result'] = canonical(raw_song)
                    except Exception as exc:
                        result['raw_tuxguitar_read_error'] = str(exc)
                result['reference_mode'] = 'TG with two destination measures explicitly added; native adds them automatically'
                reference_ops = ['measure_add 5', 'measure_add 6'] + ops
                result['reference_ops'] = reference_ops
                (folder / 'ops.txt').write_text('\n'.join(reference_ops) + '\n')
                run = subprocess.run([args.java, '--class-path', str(Path(args.tuxguitar) / 'lib' / '*'), str(PROBE),
                                      str(source), str(folder / 'ops.txt'), str(folder / 'tg.tg')], capture_output=True, text=True)
            try:
                if run.returncode:
                    raise RuntimeError('TuxGuitar: ' + (run.stderr.strip().splitlines() or ['failed'])[-1])
                tg_song, _ = tgimport.read_tg((folder / 'tg.tg').read_bytes())
                theirs, their_rests = compare(tg_song)
                if name.startswith('rhythm ') and any(op.startswith('range_duration ') for op in ops):
                    result['raw_tuxguitar_result'] = dict(notes=theirs['bars'], rests=their_rests)
                    result['reference_mode'] = 'TG duration manager with detached original voices skipped (deliberate native difference)'
                    live_ops = [op.replace('range_duration ', 'range_duration_live ', 1) for op in ops]
                    (folder / 'ops.txt').write_text('\n'.join(live_ops) + '\n')
                    run = subprocess.run([args.java, '--class-path', str(Path(args.tuxguitar) / 'lib' / '*'), str(PROBE),
                                          str(source), str(folder / 'ops.txt'), str(folder / 'tg-live.tg')], capture_output=True, text=True)
                    if run.returncode:
                        raise RuntimeError('TuxGuitar live-target reference: ' + run.stderr.strip()[-300:])
                    live_song, _ = tgimport.read_tg((folder / 'tg-live.tg').read_bytes())
                    live, live_rests = canonical(live_song)
                    result['raw_to_live_differences'] = diff(theirs, live)
                    result['tuxguitar_diagnostics'] = run.stdout.strip().splitlines()
                    theirs, their_rests = live, live_rests
                if name == 'section cut selected rests':
                    result['raw_tuxguitar_result'] = dict(notes=theirs['bars'], rests=their_rests)
                    result['reference_mode'] = 'TG removeVoice applied to each selected rest; raw action repeatedly uses the caret voice'
                    live_ops = [op.replace('beats_cut ', 'beats_cut_rest_live ', 1) for op in ops]
                    (folder / 'ops.txt').write_text('\n'.join(live_ops) + '\n')
                    run = subprocess.run([args.java, '--class-path', str(Path(args.tuxguitar) / 'lib' / '*'), str(PROBE),
                                          str(source), str(folder / 'ops.txt'), str(folder / 'tg-live.tg')], capture_output=True, text=True)
                    if run.returncode:
                        raise RuntimeError('TuxGuitar per-rest reference: ' + run.stderr.strip()[-300:])
                    live_song, _ = tgimport.read_tg((folder / 'tg-live.tg').read_bytes())
                    live, live_rests = canonical(live_song)
                    result['raw_to_live_differences'] = diff(theirs, live)
                    theirs, their_rests = live, live_rests
            except Exception as e:
                theirs, their_rests, result['tuxguitar_error'] = None, None, str(e)[:300]
                if name.startswith('clipboard replace ') and args.json and (folder / 'tg.tg').exists():
                    retained = Path(args.json).parent / (name.replace(' ', '-') + '-raw.tg')
                    retained.parent.mkdir(parents=True, exist_ok=True)
                    retained.write_bytes((folder / 'tg.tg').read_bytes())
                    result['unreadable_tuxguitar_file'] = str(retained)
            ours_start=copy.deepcopy(case_start)
            if name.startswith('free duration sparse '):
                pattern = ours_start['score']['patterns'][str(ours_start['orders'][3])]
                pattern['beats'] = [b for b in pattern['beats'] if b['notes']]
                result['fixture_setup'] = 'Both inputs omit measure 4 rests without repacking; exported and sparse TG states are printed separately'
            if name.startswith(('cohort annotations ', 'cohort rest ', 'free duration ', 'tied ', 'rhythm ', 'section ', 'song ', 'rehearsal ', 'adapt ', 'stem group ', 'clipboard replace ')) or any(op.startswith(('range_expression ', 'range_duration ')) for op in ops):
                # Imported TG defaults to six ticks/row. These sample-backed IT cases need
                # release cells separate from attack volume: use the existing exact two-tick grid.
                assert all(not p['data'] for p in ours_start['patterns'].values())
                ours_start['module']['speed']=2
                for pattern in ours_start['patterns'].values():pattern['rows']*=3
                for pattern in ours_start['score']['patterns'].values():pattern['row_step']=[1,12]
            if name == 'stem group implicit gap':
                pattern = ours_start['score']['patterns'][str(ours_start['orders'][2])]
                pattern['beats'] = [b for b in pattern['beats'] if b['notes'] or b.get('voice', 0) != 0]
                result['reference_mode'] = 'TG explicit rests compared with equivalent native implicit gaps'
            if name.startswith('rhythm implicit '):
                # TG represents silence explicitly. Remove only its equivalent
                # native voice-zero rests to exercise real implicit input gaps.
                pattern = ours_start['score']['patterns'][str(ours_start['orders'][2 if 'trailing' in name else 3])]
                pattern['beats'] = [b for b in pattern['beats'] if b['notes'] or b.get('voice', 0) != 0]
                result['reference_mode'] = 'TG explicit silence compared with equivalent native implicit gap'
            ours = Ours(folder, ours_start)
            before = copy.deepcopy(ours.st.song)
            try:
                for op in ops:
                    ours.apply(op)
            except Exception as e:   # a refused command, or a song the compiler refuses (SongError)
                result['ours_refused'] = str(e)[:300]
            mine, my_rests = compare(ours.st.song)
            unchanged_song = ours.st.song == before
            ours.st.close()
            if name.startswith(('cohort annotations ', 'cohort rest ', 'free duration ', 'clipboard replace ')):
                result['native_result'] = dict(document=mine, rests=my_rests)
                result['initial_result'] = dict(document=compare(case_start)[0], rests=compare(case_start)[1])
                result['native_song_unchanged'] = unchanged_song
            if theirs is None:
                result['verdict'] = 'tuxguitar output not readable here'
            else:
                result['differences'] = diff(theirs, mine)
                result['rest_differences'] = diff(their_rests, my_rests)
                if name.startswith(('cohort annotations ', 'cohort rest ', 'free duration ', 'clipboard replace ')):
                    result['tuxguitar_result'] = dict(document=theirs, rests=their_rests)
                if name.startswith('adapt '):
                    result['tuxguitar_result'] = theirs
                    result['native_result'] = mine
                    result['native_song_unchanged'] = unchanged_song
                    if name in ('adapt grace uniform down', 'adapt trill uniform down', 'adapt trill Drop D'):
                        effect = 'grace' if 'grace' in name else 'trill'
                        expected = copy.deepcopy(theirs)
                        expected['effects'][0][0][effect]['fret'] = 4
                        result['raw_tuxguitar_differences'] = result['differences']
                        result['reference_mode'] = ('Native preserves effect sounding pitch: old open pitch + effect fret = '
                                                    'new open pitch + effect fret; TG leaves the original effect fret')
                        result['differences'] = diff(expected, mine)
                    if name in ('adapt unplayable strings', 'adapt natural harmonic uniform down'):
                        result['raw_tuxguitar_differences'] = result['differences']
                        result['reference_mode'] = ('Native atomic safety refusal; TG drops an unplaceable note' if
                            name == 'adapt unplayable strings' else
                            'Native atomic safety refusal; TG moves natural harmonic node 7 to 9 and changes its sound')
                        result['differences'] = diff(compare(case_start)[0], mine)
                        wanted = 'cannot place' if name == 'adapt unplayable strings' else 'harmonic'
                        if wanted not in result.get('ours_refused', '').lower() or not unchanged_song:
                            result['differences'].append('expected unchanged document and explicit safety refusal')
                        if not diff(theirs, compare(case_start)[0]):
                            result['differences'].append('raw TG action unexpectedly left the song unchanged')
                if name.startswith(('rhythm ', 'section ')):
                    result['tuxguitar_result'] = dict(notes=theirs['bars'], rests=their_rests)
                    result['native_result'] = dict(notes=mine['bars'], rests=my_rests)
                if name == 'section paste across bar line':
                    # Raw TG clears the entire half note at the destination even
                    # though only its first quarter is replaced. Native retains
                    # the untouched final quarter as a fresh attack.
                    expected = copy.deepcopy(theirs)
                    suffix = copy.deepcopy(canonical(case_start)[0]['bars'][1]['notes'][0])
                    suffix[1:5] = ['1', 4, 0, [1, 1]]
                    expected['bars'][1]['notes'] = [expected['bars'][1]['notes'][0], suffix,
                        *copy.deepcopy(canonical(case_start)[0]['bars'][1]['notes'][1:])]
                    result['raw_tuxguitar_differences'] = result['differences']
                    result['reference_mode'] = 'Native preserves untouched destination quarter and later attack times; TG deletes the quarter and shifts later attacks'
                    result['differences'] = diff(expected, mine)
                if name == 'section paste preserves peer-rest timing':
                    # TG advances the last copied attack an extra quarter when
                    # a longer peer rest is present. Native keeps copied offsets.
                    expected = copy.deepcopy(theirs)
                    expected['bars'][5]['notes'][1][1] = '1'
                    result['raw_tuxguitar_differences'] = result['differences']
                    result['reference_mode'] += '; native retains last copied attack at its original relative time'
                    result['differences'] = diff(expected, mine)
                if name == 'rhythm implicit trailing no room':
                    result['native_song_unchanged'] = unchanged_song
                    if not unchanged_song:
                        result['differences'].append('no-room Fit saved its temporary implicit-gap rests')
                if name == 'rhythm partial middle rest quintuplet':
                    result['refused_tuxguitar_differences'] = result['differences']
                    result['differences'] = diff(canonical(case_start)[0], mine)
                    if 'not representable' not in result.get('ours_refused', ''):
                        result['differences'].append('expected atomic refusal of nonintegral IT tick timing')
                    if not unchanged_song:
                        result['differences'].append('unsafe timing refusal changed the native song')
                    result['reference_mode'] = 'Exact IT timing safeguard: TG accepts nonintegral IT tick durations; native must refuse atomically'
                if name.startswith('tied '):
                    repaired = 1 if name.endswith('repaired') else 0
                    expected = f'explicit Fix tied note repaired {repaired} invalid flags after duration edit'
                    if result.get('tuxguitar_diagnostics') != [expected]:
                        result['differences'].append(f'expected TG raw tie state diagnostic: {expected}')
                if name.startswith('boundary duration '):
                    expected=32 if 'shorter' in name else 16
                    target=[0,'15/4',expected,0,[1,1]]
                    for label, rests in [('TuxGuitar',their_rests),('here',my_rests)]:
                        if [r for r in rests[2] if r[0]==0 and r[1]=='15/4'] != [target]:
                            result['differences'].append(f'{label}: selected final rest did not retain/apply {target}')
                    target=[0,'0',32 if 'shorter' in name else 8,0,[1,1]]
                    for label, document in [('TuxGuitar',theirs),('here',mine)]:
                        if [n[:5] for n in document['bars'][3]['notes'] if n[0]==0 and n[1]=='0'] != [target]:
                            result['differences'].append(f'{label}: selected next-bar note did not apply {target}')
                    if 'ours_refused' in result:
                        result['differences'].append('here refused a range with a valid duration change')
                result['verdict'] = 'mismatch' if result['differences'] else (
                    'match' if 'ours_refused' not in result else 'match (both left it unchanged)'
                    if mine == compare(case_start)[0] else 'match')
                if name == 'rhythm partial middle rest quintuplet' and not result['differences']:
                    result['verdict'] = 'match (atomic IT timing refusal; TG differs)'
                if name.startswith('section ') and result.get('reference_mode') and not result['differences']:
                    result['verdict'] = 'match (explicit reference; raw TG differs)'
                if name.startswith('adapt ') and result.get('reference_mode') and not result['differences']:
                    result['verdict'] = 'match (native safety reference; raw TG differs)'
            results[name] = result
            print(f"{result['verdict']:>10}  {name}" + (f"  (here refused: {result['ours_refused']})" if 'ours_refused' in result else '')
                  + (f"  ({len(result.get('rest_differences') or [])} rest differences)" if result.get('rest_differences') else '')
                  + ('  [live-target reference; raw TG differs]' if result.get('raw_to_live_differences') else ''))
            for d in result.get('differences', [])[:6]:
                print('            ' + d)
            if result.get('tuxguitar_error'):
                print('            ' + result['tuxguitar_error'])
    counts = {v: sum(r['verdict'].startswith(v) for r in results.values()) for v in ('match', 'mismatch')}
    unchanged = sum(r['verdict'] == 'match (both left it unchanged)' for r in results.values())
    print(f"{counts['match']} match ({unchanged} with both unchanged), {counts['mismatch']} mismatch, "
          f"{len(results) - sum(counts.values())} not comparable")
    if args.json:
        Path(args.json).write_text(json.dumps(results, indent=1), encoding='utf-8')
    return 0 if counts['match'] == len(results) else 1


if __name__ == '__main__':
    sys.exit(main())
