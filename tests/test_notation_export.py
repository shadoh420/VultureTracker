"""Native score -> LilyPond / MusicXML (IO-09), checked against TuxGuitar 2.1.0 output.

The golden texts were produced by the installed TuxGuitar 2.1.0 writers from the same native
document (tgimport.native_to_tg -> TG reader -> writer), by scratch/notation-export/oracle.py.
"""
import io
import unittest
from unittest.mock import patch

try:
    import guitarpro
    from guitarpro import models as M
except ImportError:
    guitarpro = None


def _write_gp5(song):
    """GP5 bytes in the TG-source header order (PyGuitarPro 0.11 swaps beams and alternates)."""
    from guitarpro.gp5 import GP5File

    def header_values(writer, header, flags):
        writer.writeU8(flags)
        if flags & 1:
            writer.writeI8(header.timeSignature.numerator)
        if flags & 2:
            writer.writeI8(header.timeSignature.denominator.value)
        if flags & 8:
            writer.writeU8(header.repeatClose + 1)
        if flags & 0x20:
            writer.writeMarker(header.marker)
        if flags & 0x40:
            writer.writeI8(header.keySignature.value[0])
            writer.writeI8(header.keySignature.value[1])
        if flags & 3:
            for beam in header.timeSignature.beams:
                writer.writeU8(beam)
        if flags & 0x10:
            writer.writeRepeatAlternative(header.repeatAlternative)
        else:
            writer.placeholder(1)
        writer.writeU8(header.tripletFeel.value)

    output = io.BytesIO()
    with patch.object(GP5File, 'writeMeasureHeaderValues', header_values):
        guitarpro.write(song, output, version=(5, 1, 0))
    return output.getvalue()


def gp_fixture(measures=6):
    """Two voices, a triplet, a tie, rests, dead note, h/p, slides, bends (moving and held)."""
    gp = M.Song()
    gp.title, gp.tempo = 'Notation export fixture', 100
    gp.measureHeaders = [M.MeasureHeader(number=i + 1, start=960 + i * 3840) for i in range(measures)]
    track = gp.tracks[0]
    track.name = 'Lead'
    track.fretCount = 24
    track.clefTranspose = track.clefTransposeSecondary = 0
    track.strings = [M.GuitarString(i + 1, p) for i, p in enumerate((64, 59, 55, 50, 45, 40))]
    track.channel.instrument, track.channel.volume = 25, 128
    track.measures = [M.Measure(track, h) for h in gp.measureHeaders]

    def beat(voice, start, value, notes=(), tuplet=None, **beat_fx):
        b = M.Beat(voice, start=start, duration=M.Duration(value=value), status=M.BeatStatus.normal)
        if tuplet:
            b.duration.tuplet = M.Tuplet(*tuplet)
        if not notes:
            b.status = M.BeatStatus.rest
        for string, fret, fx in notes:
            n = M.Note(b, value=fret, string=string, velocity=95, type=M.NoteType.normal)
            for key, value in fx.items():
                if key == 'tie':
                    n.type = M.NoteType.tie
                elif key == 'dead':
                    n.type = M.NoteType.dead
                elif key == 'bend':
                    n.effect.bend = M.BendEffect(type=M.BendType.bend, value=0,
                                                 points=[M.BendPoint(p, v, False) for p, v in value])
                elif key == 'slide':
                    n.effect.slides = [M.SlideType.shiftSlideTo]
                else:
                    setattr(n.effect, key, value)
            b.notes.append(n)
        for key, value in beat_fx.items():
            setattr(b.effect, key, value)
        voice.beats.append(b)
        return b

    for i, measure in enumerate(track.measures):
        v0, v1 = measure.voices
        t = measure.start
        if i == 0:
            beat(v0, t, 4, [(1, 5, dict(hammer=True))])
            beat(v0, t + 960, 4, [(1, 7, {})])
            beat(v0, t + 1920, 4, [(1, 7, dict(hammer=True))])
            beat(v0, t + 2880, 4, [(1, 5, {})])
            beat(v1, t, 2, [(5, 3, {})])
            beat(v1, t + 1920, 2)
        elif i == 1:
            for k, fret in enumerate((3, 5, 7)):
                beat(v0, t + k * 320, 8, [(2, fret, {})], tuplet=(3, 2))
            beat(v0, t + 960, 4, [(2, 7, dict(slide=True))])
            beat(v0, t + 1920, 4, [(2, 9, dict(slide=True))])
            beat(v0, t + 2880, 4, [(2, 5, {})])
        elif i == 2:
            beat(v0, t, 2, [(3, 7, dict(bend=[(0, 0), (6, 4), (12, 4)]))])
            beat(v0, t + 1920, 4, [(3, 9, dict(bend=[(0, 4), (12, 4)]))])
            beat(v0, t + 2880, 4, [(3, 9, dict(dead=True))])
        elif i == 3:
            beat(v0, t, 2, [(4, 5, {}), (5, 7, {})])
            beat(v0, t + 1920, 2, [(4, 5, dict(tie=True)), (5, 7, dict(tie=True))])
        else:
            for k in range(8):
                beat(v0, t + k * 480, 8, [(6, (k * 3) % 12, {})] if k != 5 else [])
    return gp


def fixture(measures=6):
    from vulturetracker import gpimport
    return gpimport._native_gp_song(gpimport._read_native_gp(_write_gp5(gp_fixture(measures))),
                                    'Notation export fixture')


CHANNELS = {'t1': dict(program=25, bank=0)}


def case_basic():
    """(song, channels) for scratch/notation-export/oracle.py."""
    return fixture(), CHANNELS


def rich_fixture():
    """The basic fixture plus chords, text, strokes, lyrics, key/clef, repeats, a marker and techniques."""
    song = fixture()
    score = song['score']
    track = score['tracks']['t1']
    track.update(key=dict(fifths=-2, mode='major'), clef='bass',
                 lyrics=dict(from_measure=2, text='Hel- lo  world wide- web\nend - ing'))
    measures = {m['id']: m for m in score['measures']}
    measures['m1']['marker'] = dict(title='Intro & <A>', color='#112233')
    measures['m2']['repeat_open'] = True
    measures['m3'].update(endings=[1], repeat_close=1)
    measures['m4'].update(endings=[2])
    beats = {name: {b['id']: b for b in p['beats']} for name, p in score['patterns'].items()}
    m1 = beats['m1']
    m1['t1_v1_b1']['text'] = 'let "it" ring'
    m1['t1_v1_b2']['stroke'] = dict(direction='down', value=16)
    m1['t1_v1_b3']['pick_stroke'] = 'up'
    m1['t1_v1_b4']['pick_stroke'] = 'down'
    beats['m4']['t1_v1_b1']['chord'] = dict(name='Dm7/A', first_fret=0, frets=[-1, -1, -1, 5, 7, -1])
    beats['m4']['t1_v1_b2']['text'] = 'tied'
    techniques = [dict(staccato=True, velocity=79), dict(accent=True, velocity=111),
                  dict(heavy_accent=True, velocity=63), dict(ghost=True, velocity=47),
                  dict(palm_mute=True), {}, dict(let_ring=True, vibrato=True),
                  dict(tapping=True, harmonic=dict(type='natural', data=0))]
    for name in ('m5', 'm6'):
        for i, beat in enumerate(sorted(beats[name].values(), key=lambda b: b['at'][0] / b['at'][1])):
            if beat['notes'] and name == 'm5':
                beat['notes'][0].update(techniques[i])
            elif beat['notes']:
                fret = beat['notes'][0]['fret']
                extra = [dict(trill=dict(fret=fret + 2, value=32)), dict(tremolo_picking=dict(value=16)),
                         dict(grace=dict(fret=fret + 1, value=32, velocity=95)),
                         dict(harmonic=dict(type='artificial', data=0)), dict(dead=True), {},
                         dict(tremolo_picking=dict(value=32)),
                         dict(grace=dict(fret=fret + 2, value=16, velocity=95, transition='slide'))][i]
                beat['notes'][0].update(extra)
    return song


def case_rich():
    return rich_fixture(), CHANNELS


def gp_multi():
    """Guitar (capo, high notes, double dot, quintuplet, voice-2-only bar), bass (tie over a barline), drums."""
    gp = M.Song()
    gp.title, gp.tempo = 'Three tracks', 132
    gp.measureHeaders = [M.MeasureHeader(number=i + 1, start=960 + i * 3840) for i in range(3)]

    def track(number, name, tuning, channel, program, capo=0):
        t = M.Track(gp, number=number, name=name, offset=capo, fretCount=24)
        t.clefTranspose = t.clefTransposeSecondary = 0
        t.strings = [M.GuitarString(i + 1, p) for i, p in enumerate(tuning)]
        t.channel = M.MidiChannel(channel=channel, effectChannel=channel if channel == 9 else channel + 1,
                                  instrument=program, volume=128)
        t.isPercussionTrack = channel == 9
        t.measures = [M.Measure(t, h) for h in gp.measureHeaders]
        return t

    def beat(voice, start, value, notes=(), dots=0, tuplet=None, tie=False):
        b = M.Beat(voice, start=start, duration=M.Duration(value=value), status=M.BeatStatus.normal)
        b.duration.isDotted = dots == 1
        b.duration.isDoubleDotted = dots == 2
        if tuplet:
            b.duration.tuplet = M.Tuplet(*tuplet)
        b.status = M.BeatStatus.normal if notes else M.BeatStatus.rest
        for string, fret in notes:
            b.notes.append(M.Note(b, value=fret, string=string, velocity=95,
                                  type=M.NoteType.tie if tie else M.NoteType.normal))
        voice.beats.append(b)

    guitar = track(1, 'Guitar', (64, 59, 55, 50, 45, 40), 0, 27, capo=2)
    bass = track(2, 'Bass', (43, 38, 33, 28), 2, 33)
    drums = track(3, 'Drums', (0, 0, 0), 9, 0)
    gp.tracks = [guitar, bass, drums]
    m = [h.start for h in gp.measureHeaders]
    v = guitar.measures[0].voices[0]
    beat(v, m[0], 2, [(1, 12), (2, 13)], dots=2)
    beat(v, m[0] + 3360, 8, [(1, 15)])
    v = guitar.measures[1].voices[1]
    for k in range(5):
        beat(v, m[1] + k * 192, 16, [(5, k)], tuplet=(5, 4))
    for k in range(3):
        beat(v, m[1] + 960 * (k + 1), 4, [(5, 7)])
    v = guitar.measures[2].voices[0]
    beat(v, m[2], 1, [(3, 2), (4, 2), (5, 0)])
    for i in range(3):
        v = bass.measures[i].voices[0]
        for k in range(4):
            beat(v, m[i] + 960 * k, 4, [(4, 5)], tie=i == 1 and k == 0)
        v = drums.measures[i].voices[0]
        for k in range(8):
            beat(v, m[i] + 480 * k, 8, [(1, 42)] + ([(2, 36)] if k % 4 == 0 else [(3, 38)] if k % 4 == 2 else []))
    return gp


MULTI_CHANNELS = {'t1': dict(program=27, bank=0), 't2': dict(program=33, bank=0), 't3': dict(program=0, bank=128)}


def multi_fixture():
    from vulturetracker import gpimport
    song = gpimport._native_gp_song(gpimport._read_native_gp(_write_gp5(gp_multi())), 'Three tracks')
    song['score']['tracks']['t1']['key'] = dict(fifths=7, mode='major')
    song['score']['tracks']['t2']['key'] = dict(fifths=7, mode='major')
    return song


def case_multi():
    return multi_fixture(), MULTI_CHANNELS


# BEGIN GOLDEN (scratch/notation-export/golden.py; TuxGuitar 2.1.0 output)
GOLDEN = {
    (('case_basic', ()), "musicxml"): (
        'eNrtXNly4jgU/RXK726DWbpTJVSVdGcyUzU1NQ/zA8IWsSreRhJ08vetzXgJBHBktvYLSFfL1T3S3SQKwIKMYjdHlP8kDA/WmDKS'
        'pXNn8mXoQPAzoy/60+WExxj+k3HERYcBfs0zygdL8spXFAOv0kdXICAhTjlZkkCP8CCQbNyYMA5ByXdAwrnz78gxzSlKMPwboxB4'
        'Zd10JynjdJWIac0g9y85riRXRzepwGtOAkFCQrJrVtUWRChNcQxHwKvVdWtOs2eKEujPTHNBMNUqK6+UGBrRNBJ1DBKMmAB0kK6S'
        'BaZzR9IQ55QsVhwzCEKyJnKHGLybDYFXVsELfoNgSZY8YlC0mBLwFJ0TicACI87gBHi6oOouf8txQdMV4OnujKO14OmLteuS3iH2'
        'liyyGKZZio0ghgKCGC9rK2fkOYVPYrz8BjFJsZxNfavObhbImRWszxi6AuYtZE1sTO8X0/93/1AwMP3EapdLN8QckZjVB6gWJSSK'
        'OaYp4lhJV1BND7lCBmdFk64Wo1cpSZ8HkqaF1ASXcZzDR4FdpVq0aXmk7HXChreibuXgNzjcW+cwbnD48SGHcQsOkwaHJ+scpg0O'
        'D9Y5zI7a6ck+Dl7tkIp6XckpDpTRzGMUYGlA5g5aZGvsVBrNiU0wp1maFfrtCgYc/r8Seomp0WpFAjmmbkJSwQKOhsJCVOrCXpWz'
        'eE0OJQGCNON4EL4Ji0oCJs7/cKgcRU54EEnc9AnVkJRYbEAw/cIVVU7BGLGiBtYZCbA0troAFP+NLBUNlX10Qa5IjRa4cRxEqfA3'
        'whRFKEmEfAJCOWruiM6UO/BP4G1apJ0rB3iVeWQZHyTrw2XKmuWO9Lc3K18ne3l/zXu5QMHLKq+scPxtUluiV/Q4AInvDSTGHyAx'
        'uvO3QOHXoYhQvNyFQ2WDIKCYcSntqabfuo/+UfvYxQZ0fhRxYuI3VTQy+XvO5pJiDqcitJTfYgyVnkwBoUo3Y3Pbg/P1GHCux0if'
        'CJDrtOonUqXbcwPtgRs3gJuWwB1wYOx5Gb9rL/OOgWfuB95fFMg88YA9/XGEOoz9/eqAyXPEo2LV8t7ATbJwc+sjLi8CvkKxK5fG'
        '5MbV6mLFNNnUfCllpa7vIRrzfeDf94j++PuK/kchurr1kFPoQg/FUVDYjfpZLG5Ia85PGfhWXu7pQqUyXsumqI9nS9O2ita1E74B'
        'g23P0ftHOfrb9wf2Yk+ryN6gu7GXAl0M0mdOBXfgcNVesT06d23QuUbv2rnJOtRL706lxvZTqe0J5ujwa8ztuCxwGg5YhKSswYqu'
        'cehooqsPuv9lKJ+ANnVdObXz7Oyy/Gjxc/ECrwZ51wOFXEEkftEAX/WaVPkdQOKhUDzzJ/IxTygFkg5SnHD9tqfbzh2ctlABe85m'
        'XNqKG9YZe+7nM3hdo5J1hN0uuQ/W1t1OauIcFwK1uMPl5H1U8SnHRXA4yCgRP2dQpLkjftFAnU9ELkGUUXXOPjoqtyVyF5trgqQu'
        'Bd0dh51ja88qsFUPfAb9thfBTz6bCl+K/tsLVKY2bwdObx9+l7NxCkTaH43dUcPUaRVt+R/ANPl27IVd+8ebpwtd1/2ei6ZLWef3'
        'PescX8g6z3b+tjze9+foQs+R1Tiq6xPX3g0MG25g1mWEcDlij7sU+9R61h6GWZcwnFqN7d2xzLp8CL4V3bfozPwrcGa9kp1NyXYn'
        'HLM+4egDxT7h6BOOPuHoE44+4ehjoT7h6BOOPuHolcxWwuGZf1Sp/5EN/AUBxv6H'
    ),
    (('case_basic', ()), "ly"): (
        '#(define (tie::tab-clear-tied-fret-numbers grob)\n'
        '   (let* ((tied-fret-nr (ly:spanner-bound grob RIGHT)))\n'
        "      (ly:grob-set-property! tied-fret-nr 'transparent #t)))\n"
        '\n'
        '\\version "2.14.0"\n'
        '\\paper {\n'
        '   indent = #0\n'
        '   print-all-headers = ##t\n'
        '   ragged-right = ##f\n'
        '   ragged-bottom = ##t\n'
        '}\n'
        '\\layout {\n'
        '   \\context { \\Score\n'
        "      \\override MetronomeMark #'padding = #'5\n"
        '   }\n'
        '   \\context { \\Staff\n'
        "      \\override TimeSignature #'style = #'numbered\n"
        "      \\override StringNumber #'transparent = ##t\n"
        '   }\n'
        '   \\context { \\TabStaff\n'
        "      \\override TimeSignature #'style = #'numbered\n"
        "      \\override Stem #'transparent = ##t\n"
        "      \\override Beam #'transparent = ##t\n"
        "      \\override Tie  #'after-line-breaking = #tie::tab-clear-tied-fret-numbers\n"
        '   }\n'
        '   \\context { \\TabVoice\n'
        "      \\override Tie #'stencil = ##f\n"
        '   }\n'
        '   \\context { \\StaffGroup\n'
        '      \\consists "Instrument_name_engraver"\n'
        '   }\n'
        '}\n'
        'TrackAVoiceAMusic = #(define-music-function (parser location inTab) (boolean?)\n'
        '#{\n'
        '   \\tempo 4=100\n'
        '   \\clef #(if inTab "tab" "treble_8")\n'
        '   \\key c \\major\n'
        '   \\time 4/4\n'
        '   \\voiceOne\n'
        '   <a\'\\1>4_"H" <b\'\\1>4 <b\'\\1>4_"H" <a\'\\1>4 \n'
        '   \\oneVoice\n'
        "   \\times 2/3 {<d'\\2>8 <e'\\2>8 <fis'\\2>8 } <fis'\\2>4\\glissando <gis'\\2>4\\glissando <e'\\2>4 \n"
        "   <\\bendAfter #+6 d'\\3>2 <\\bendAfter #+6 e'\\3>4 <\\deadNote e'\\3>4 \n"
        '   <g~\\4 e~\\5 >2 <g\\4 e\\5 >2 \n'
        '   <e,\\6>8 <g,\\6>8 <ais,\\6>8 <cis\\6>8 <e,\\6>8 r8 <ais,\\6>8 <cis\\6>8 \n'
        '   <e,\\6>8 <g,\\6>8 <ais,\\6>8 <cis\\6>8 <e,\\6>8 r8 <ais,\\6>8 <cis\\6>8 \n'
        '   \\bar "|."\n'
        '   \\pageBreak\n'
        '#})\n'
        'TrackAVoiceBMusic = #(define-music-function (parser location inTab) (boolean?)\n'
        '#{\n'
        '   \\tempo 4=100\n'
        '   \\clef #(if inTab "tab" "treble_8")\n'
        '   \\key c \\major\n'
        '   \\time 4/4\n'
        '   \\voiceTwo\n'
        '   <c\\5>2 r2 \n'
        '   \\oneVoice\n'
        '   \\skip 4*4 \n'
        '   \\skip 4*4 \n'
        '   \\skip 4*4 \n'
        '   \\skip 4*4 \n'
        '   \\skip 4*4 \n'
        '   \\bar "|."\n'
        '   \\pageBreak\n'
        '#})\n'
        'TrackALyrics = \\lyricmode {\n'
        '   \\set ignoreMelismata = ##t\n'
        '   \n'
        '   \\unset ignoreMelismata\n'
        '}\n'
        'TrackAStaff = \\new Staff <<\n'
        '   \\context Voice = "TrackAVoiceAMusic" {\n'
        '      \\TrackAVoiceAMusic ##f\n'
        '   }\n'
        '   \\context Voice = "TrackAVoiceBMusic" {\n'
        '      \\TrackAVoiceBMusic ##f\n'
        '   }\n'
        '>>\n'
        'TrackATabStaff = \\new TabStaff \\with { stringTunings = #`( ,(ly:make-pitch 0 2 NATURAL) ,(ly:make-pitch -1 6 NATURAL) ,(ly:make-pitch -1 4 NATURAL) ,(ly:make-pitch -1 1 NATURAL) ,(ly:make-pitch -2 5 NATURAL) ,(ly:make-pitch -2 2 NATURAL) ) } <<\n'
        '   \\context TabVoice = "TrackAVoiceAMusic" {\n'
        "      \\removeWithTag #'chords\n"
        "      \\removeWithTag #'texts\n"
        '      \\TrackAVoiceAMusic ##t\n'
        '   }\n'
        '   \\context TabVoice = "TrackAVoiceBMusic" {\n'
        "      \\removeWithTag #'chords\n"
        "      \\removeWithTag #'texts\n"
        '      \\TrackAVoiceBMusic ##t\n'
        '   }\n'
        '>>\n'
        'TrackAStaffGroup = \\new StaffGroup <<\n'
        '   \\TrackAStaff\n'
        '   \\TrackATabStaff\n'
        '>>\n'
        '\\score {\n'
        '   \\TrackAStaffGroup\n'
        '   \\header {\n'
        '      title = "Notation export fixture" \n'
        '      composer = "" \n'
        '      instrument = "Lead" \n'
        '   }\n'
        '}\n'
    ),
    (('case_rich', ()), "musicxml"): (
        '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'
    ),
    (('case_rich', ()), "ly"): (
        '#(define (tie::tab-clear-tied-fret-numbers grob)\n'
        '   (let* ((tied-fret-nr (ly:spanner-bound grob RIGHT)))\n'
        "      (ly:grob-set-property! tied-fret-nr 'transparent #t)))\n"
        '\n'
        '\\version "2.14.0"\n'
        '\\paper {\n'
        '   indent = #0\n'
        '   print-all-headers = ##t\n'
        '   ragged-right = ##f\n'
        '   ragged-bottom = ##t\n'
        '}\n'
        '\\layout {\n'
        '   \\context { \\Score\n'
        "      \\override MetronomeMark #'padding = #'5\n"
        '   }\n'
        '   \\context { \\Staff\n'
        "      \\override TimeSignature #'style = #'numbered\n"
        "      \\override StringNumber #'transparent = ##t\n"
        '   }\n'
        '   \\context { \\TabStaff\n'
        "      \\override TimeSignature #'style = #'numbered\n"
        "      \\override Stem #'transparent = ##t\n"
        "      \\override Beam #'transparent = ##t\n"
        "      \\override Tie  #'after-line-breaking = #tie::tab-clear-tied-fret-numbers\n"
        '   }\n'
        '   \\context { \\TabVoice\n'
        "      \\override Tie #'stencil = ##f\n"
        '   }\n'
        '   \\context { \\StaffGroup\n'
        '      \\consists "Instrument_name_engraver"\n'
        '   }\n'
        '}\n'
        'TrackAVoiceAMusic = #(define-music-function (parser location inTab) (boolean?)\n'
        '#{\n'
        '   \\tempo 4=100\n'
        '   \\clef #(if inTab "tab" "bass_8")\n'
        '   \\key bes \\major\n'
        '   \\time 4/4\n'
        '   \\voiceOne\n'
        '   <a\'\\1>4_"H"-\\tag #\'texts ^\\markup {"let "it" ring"} <b\'\\1>4\\arpeggio <b\'\\1>4_"H" <a\'\\1>4 \n'
        '   \\oneVoice\n'
        '   \\repeat volta 2 {\n'
        "      \\times 2/3 {<d'\\2>8 <e'\\2>8 <ges'\\2>8 } <ges'\\2>4\\glissando <aes'\\2>4\\glissando <e'\\2>4 \n"
        '   }\n'
        '   \\alternative {\n'
        '   {\n'
        "      <\\bendAfter #+6 d'\\3>2 <\\bendAfter #+6 e'\\3>4 <\\deadNote e'\\3>4 \n"
        '   }\n'
        '   {\n'
        '      <g~\\4 e~\\5 >2-\\tag #\'chords ^\\markup \\fret-diagram #"1-x;2-x;3-x;4-5;5-7;6-x;" <g\\4 e\\5 >2-\\tag #\'texts ^\\markup {"tied"} \n'
        '   }\n'
        '   }\n'
        '   <e,\\6>8\\staccato <g,\\6>8-> <bes,\\6>8-^ <\\parenthesize des\\6>8 <\\palmMute e,\\6>8 r8 <bes,\\6>8\\prall <des\\6\\harmonic>8 \n'
        '   <e,\\6>8\\trill <g,\\6>8:16 \\grace <b,\\6>32 <bes,\\6>8 <des\\6\\harmonic>8 <\\deadNote e,\\6>8 r8 <bes,\\6>8:32 \\grace <ees\\6>16 <des\\6>8 \n'
        '   \\bar "|."\n'
        '   \\pageBreak\n'
        '#})\n'
        'TrackAVoiceBMusic = #(define-music-function (parser location inTab) (boolean?)\n'
        '#{\n'
        '   \\tempo 4=100\n'
        '   \\clef #(if inTab "tab" "bass_8")\n'
        '   \\key bes \\major\n'
        '   \\time 4/4\n'
        '   \\voiceTwo\n'
        '   <c\\5>2 r2 \n'
        '   \\oneVoice\n'
        '   \\repeat volta 2 {\n'
        '      \\skip 4*4 \n'
        '   }\n'
        '   \\alternative {\n'
        '   {\n'
        '      \\skip 4*4 \n'
        '   }\n'
        '   {\n'
        '      \\skip 4*4 \n'
        '   }\n'
        '   }\n'
        '   \\skip 4*4 \n'
        '   \\skip 4*4 \n'
        '   \\bar "|."\n'
        '   \\pageBreak\n'
        '#})\n'
        'TrackALyrics = \\lyricmode {\n'
        '   \\set ignoreMelismata = ##t\n'
        '   \\skip 4 \\skip 4 \\skip 4 \\skip 4 \n'
        '   Hel- lo  world wide- web\n'
        'end - ing\n'
        '   \\unset ignoreMelismata\n'
        '}\n'
        'TrackAStaff = \\new Staff <<\n'
        '   \\context Voice = "TrackAVoiceAMusic" {\n'
        '      \\TrackAVoiceAMusic ##f\n'
        '   }\n'
        '   \\context Voice = "TrackAVoiceBMusic" {\n'
        '      \\TrackAVoiceBMusic ##f\n'
        '   }\n'
        '>>\n'
        'TrackATabStaff = \\new TabStaff \\with { stringTunings = #`( ,(ly:make-pitch 0 2 NATURAL) ,(ly:make-pitch -1 6 NATURAL) ,(ly:make-pitch -1 4 NATURAL) ,(ly:make-pitch -1 1 NATURAL) ,(ly:make-pitch -2 5 NATURAL) ,(ly:make-pitch -2 2 NATURAL) ) } <<\n'
        '   \\context TabVoice = "TrackAVoiceAMusic" {\n'
        "      \\removeWithTag #'chords\n"
        "      \\removeWithTag #'texts\n"
        '      \\TrackAVoiceAMusic ##t\n'
        '   }\n'
        '   \\context TabVoice = "TrackAVoiceBMusic" {\n'
        "      \\removeWithTag #'chords\n"
        "      \\removeWithTag #'texts\n"
        '      \\TrackAVoiceBMusic ##t\n'
        '   }\n'
        '   \\new Lyrics \\lyricsto "TrackAVoiceAMusic" \\TrackALyrics\n'
        '>>\n'
        'TrackAStaffGroup = \\new StaffGroup <<\n'
        '   \\TrackAStaff\n'
        '   \\TrackATabStaff\n'
        '>>\n'
        '\\score {\n'
        '   \\TrackAStaffGroup\n'
        '   \\header {\n'
        '      title = "Notation export fixture" \n'
        '      composer = "" \n'
        '      instrument = "Lead" \n'
        '   }\n'
        '}\n'
    ),
    (('case_multi', ()), "musicxml"): (
        'eNrtXFlz2joU/iuM313jhTSdEZoJTZq5b/ehf8AYAZp44Uoymfz7q814gUIxNqteinS0nPMd6SyWlAIaZQTZq5CwT0zRYI0IxVk6'
        'toJvQwuCz4x8qH9thlmM4O8lQWjASBh9UOBUGlQFAjxDKcNzHIWMzzNwIBBz2zGmDIKS2QDPxta/rqWb0zBB8D3HLCTAKSl6AE4p'
        'I3nCJ9bD7H/EyJJcH9+kA6c5DQQJnuE/zSvbomWYpiiGLnBqddW6ItmChAn0nnVzQdDVKiunRL2tAa+mgUlI6V/g93bjV6Nbo/d2'
        'oPf3oveDE9H7NfSvfMzfwPd3w9fDW+P3d63+cK8C3CPxOxVbqFtBgkKaEzRI82SKyNgStJAxgqc5QxSCGV5jYZgU/njiMpVV8IG+'
        'IJjjOVtS+B04ugQcSWdYaGCKQkYhXyxVkHWbfa1QQVMV4KjulIVrztPjsquSWiP6lUyzGKZZijQQTQFRjOY1ySlepPCdjxe/IMYp'
        'ErPJX9nZziIxs9TqAkGb63EHWREb03vF9L9fJgUD3Y9LO5/bM8RCHNP6ANkiQYYxQyQNGZLoCqruISSk8KloUtVidJ7idDEQNAVS'
        'EWzK0Aq+cd1VqkWbwiOw1wkb3pK6k4PX4PDSOQe/weF1Lwe/BYegweG9cw6jBodJ5xyejlrp4BCHKFxlYrXkb9Gotyyv102eoEgG'
        '0VUcRki4k7EVTrM1siqNev8miJEszQprtzk7Bv/LuZUiom1cksAKETvBKWcBXZ8LUqlz71XO4jQ5lAQI0oyhweyL+1ccUW4Nw6HM'
        'FlaYRUuhRaUnpSCtiBFwNirR/WY5kUkCdH94wqcVVbDOcISEc1UFIAVYhvGca7e0VtFBFYAjBPqjWNEyIzOZiVTkmxTySYcg5lIF'
        'UK7kpeStivl+hBqD58NSIbxYsuUBuaY8u8tXlZn956A2tVP0uPxGQImOSLKoEXkbRFxAORe3J4aiZcrzUh6w5gQx6PJessAHEWGc'
        'Ug+yxKcvOzuVOa5/o52gD7+hD+9UfZxzI5+Ae9R6Hzg6bdvO30T4Vn0IokzsiQ0elcDtR7fx3Af9h2FgGFw5g07DyUvDj3j73ec2'
        'BK8OwX0qvYj4/LGTbLY5vuBOO2J5GNtCMCp8Vq3O5SXJphYIvJW6+pxqzNc+E3g5EEceRhGTR90BE7MDlCJ+HlCE/yiKaObW+4Dv'
        '9Ode24BhBOsvAnYZjL2+o71hYBj0wMDkjNX40P7jdtj4th11+U1/dynpCYcIfep58rj71zuLXs3+9fvU893l6+31HPSp596T2/a4'
        'vxvcBveJZ+q+1Srb26eVZla5M2P9XGYx6vDq8e3aBTwmX+5MwF4z/q5V3F1C4/dy6fh2M/iDXvD3vYMv8UFWOkZHvSarvyK8wxdk'
        'v2ovyILbeUEWdP2CzO39BZnb+wsyr/cXZAc53PF7q6bHc4/NBd2eTtyNYGcUjGH+OJ+zH1ucK2GWiItthK0GMIxmg4xgbg6SNLa4'
        'RRBri82OiNVrStf5crWP6aOucxqD2+A+q/VfQheHH8+dR1PZ6hxuUnO5UlswMfT6X7qdY3ubWGBwG9znjne+ZZytEexxwpPxTQa3'
        'wX0dsWjrLsHv7C5heLm7BH3Czw9bo5wK0RoH/Xd08PvrhEdMnf3F6DF3cz+PuJvrW8BbUeRNL/irWfDHWnBj4cbCjSI7O+c29m/s'
        '39i/WXBj4WbBjYXfVIT3TYQ3dmXs3yy4sXCz4MbC7yDC6/sSp/7/ZsP/ASdGISk='
    ),
    (('case_multi', ()), "ly"): (
        '#(define (tie::tab-clear-tied-fret-numbers grob)\n'
        '   (let* ((tied-fret-nr (ly:spanner-bound grob RIGHT)))\n'
        "      (ly:grob-set-property! tied-fret-nr 'transparent #t)))\n"
        '\n'
        '\\version "2.14.0"\n'
        '\\paper {\n'
        '   indent = #0\n'
        '   print-all-headers = ##t\n'
        '   ragged-right = ##f\n'
        '   ragged-bottom = ##t\n'
        '}\n'
        '\\layout {\n'
        '   \\context { \\Score\n'
        "      \\override MetronomeMark #'padding = #'5\n"
        '   }\n'
        '   \\context { \\Staff\n'
        "      \\override TimeSignature #'style = #'numbered\n"
        "      \\override StringNumber #'transparent = ##t\n"
        '   }\n'
        '   \\context { \\TabStaff\n'
        "      \\override TimeSignature #'style = #'numbered\n"
        "      \\override Stem #'transparent = ##t\n"
        "      \\override Beam #'transparent = ##t\n"
        "      \\override Tie  #'after-line-breaking = #tie::tab-clear-tied-fret-numbers\n"
        '   }\n'
        '   \\context { \\TabVoice\n'
        "      \\override Tie #'stencil = ##f\n"
        '   }\n'
        '   \\context { \\StaffGroup\n'
        '      \\consists "Instrument_name_engraver"\n'
        '   }\n'
        '}\n'
        'TrackAVoiceAMusic = #(define-music-function (parser location inTab) (boolean?)\n'
        '#{\n'
        '   \\tempo 4=132\n'
        '   \\clef #(if inTab "tab" "treble_8")\n'
        '   \\key cis \\major\n'
        '   \\time 4/4\n'
        '   \\oneVoice\n'
        "    \\ottava #1 <e''\\1 c''\\2 >2 \\ottava #0  \\ottava #1 <g''\\1>8 \\ottava #0 \n"
        '   \\skip 4*4 \n'
        '   <a\\3 e\\4 a,\\5 >1 \n'
        '   \\bar "|."\n'
        '   \\pageBreak\n'
        '#})\n'
        'TrackAVoiceBMusic = #(define-music-function (parser location inTab) (boolean?)\n'
        '#{\n'
        '   \\tempo 4=132\n'
        '   \\clef #(if inTab "tab" "treble_8")\n'
        '   \\key cis \\major\n'
        '   \\time 4/4\n'
        '   \\oneVoice\n'
        '   \\skip 4*4 \n'
        '   \\times 4/5 {<a,\\5>16 <ais,\\5>16 <b,\\5>16 <c\\5>16 <cis\\5>16 } <e\\5>4 <e\\5>4 <e\\5>4 \n'
        '   \\skip 4*4 \n'
        '   \\bar "|."\n'
        '   \\pageBreak\n'
        '#})\n'
        'TrackALyrics = \\lyricmode {\n'
        '   \\set ignoreMelismata = ##t\n'
        '   \n'
        '   \\unset ignoreMelismata\n'
        '}\n'
        'TrackAStaff = \\new Staff <<\n'
        '   \\context Voice = "TrackAVoiceAMusic" {\n'
        '      \\TrackAVoiceAMusic ##f\n'
        '   }\n'
        '   \\context Voice = "TrackAVoiceBMusic" {\n'
        '      \\TrackAVoiceBMusic ##f\n'
        '   }\n'
        '>>\n'
        'TrackATabStaff = \\new TabStaff \\with { stringTunings = #`( ,(ly:make-pitch 0 2 NATURAL) ,(ly:make-pitch -1 6 NATURAL) ,(ly:make-pitch -1 4 NATURAL) ,(ly:make-pitch -1 1 NATURAL) ,(ly:make-pitch -2 5 NATURAL) ,(ly:make-pitch -2 2 NATURAL) ) } <<\n'
        '   \\context TabVoice = "TrackAVoiceAMusic" {\n'
        "      \\removeWithTag #'chords\n"
        "      \\removeWithTag #'texts\n"
        '      \\TrackAVoiceAMusic ##t\n'
        '   }\n'
        '   \\context TabVoice = "TrackAVoiceBMusic" {\n'
        "      \\removeWithTag #'chords\n"
        "      \\removeWithTag #'texts\n"
        '      \\TrackAVoiceBMusic ##t\n'
        '   }\n'
        '>>\n'
        'TrackAStaffGroup = \\new StaffGroup <<\n'
        '   \\TrackAStaff\n'
        '   \\TrackATabStaff\n'
        '>>\n'
        'TrackBVoiceAMusic = #(define-music-function (parser location inTab) (boolean?)\n'
        '#{\n'
        '   \\tempo 4=132\n'
        '   \\clef #(if inTab "tab" "bass_8")\n'
        '   \\key cis \\major\n'
        '   \\time 4/4\n'
        '   \\oneVoice\n'
        '   <a,,\\4>4 <a,,\\4>4 <a,,\\4>4 <a,,~\\4>4 \n'
        '   <a,,\\4>4 <a,,\\4>4 <a,,\\4>4 <a,,\\4>4 \n'
        '   <a,,\\4>4 <a,,\\4>4 <a,,\\4>4 <a,,\\4>4 \n'
        '   \\bar "|."\n'
        '   \\pageBreak\n'
        '#})\n'
        'TrackBVoiceBMusic = #(define-music-function (parser location inTab) (boolean?)\n'
        '#{\n'
        '#})\n'
        'TrackBLyrics = \\lyricmode {\n'
        '   \\set ignoreMelismata = ##t\n'
        '   \n'
        '   \\unset ignoreMelismata\n'
        '}\n'
        'TrackBStaff = \\new Staff <<\n'
        '   \\context Voice = "TrackBVoiceAMusic" {\n'
        '      \\TrackBVoiceAMusic ##f\n'
        '   }\n'
        '   \\context Voice = "TrackBVoiceBMusic" {\n'
        '      \\TrackBVoiceBMusic ##f\n'
        '   }\n'
        '>>\n'
        'TrackBTabStaff = \\new TabStaff \\with { stringTunings = #`( ,(ly:make-pitch -2 4 NATURAL) ,(ly:make-pitch -2 1 NATURAL) ,(ly:make-pitch -3 5 NATURAL) ,(ly:make-pitch -3 2 NATURAL) ) } <<\n'
        '   \\context TabVoice = "TrackBVoiceAMusic" {\n'
        "      \\removeWithTag #'chords\n"
        "      \\removeWithTag #'texts\n"
        '      \\TrackBVoiceAMusic ##t\n'
        '   }\n'
        '   \\context TabVoice = "TrackBVoiceBMusic" {\n'
        "      \\removeWithTag #'chords\n"
        "      \\removeWithTag #'texts\n"
        '      \\TrackBVoiceBMusic ##t\n'
        '   }\n'
        '>>\n'
        'TrackBStaffGroup = \\new StaffGroup <<\n'
        '   \\TrackBStaff\n'
        '   \\TrackBTabStaff\n'
        '>>\n'
        'TrackCVoiceAMusic = #(define-music-function (parser location inTab) (boolean?)\n'
        '#{\n'
        '   \\tempo 4=132\n'
        '   \\clef #(if inTab "tab" "treble_8")\n'
        '   \\key c \\major\n'
        '   \\time 4/4\n'
        '   \\oneVoice\n'
        '   <fis,\\1 c,\\2 >8 <fis,\\1>8 <fis,\\1 d,\\3 >8 <fis,\\1>8 <fis,\\1 c,\\2 >8 <fis,\\1>8 <fis,\\1 d,\\3 >8 <fis,\\1>8 \n'
        '   <fis,\\1 c,\\2 >8 <fis,\\1>8 <fis,\\1 d,\\3 >8 <fis,\\1>8 <fis,\\1 c,\\2 >8 <fis,\\1>8 <fis,\\1 d,\\3 >8 <fis,\\1>8 \n'
        '   <fis,\\1 c,\\2 >8 <fis,\\1>8 <fis,\\1 d,\\3 >8 <fis,\\1>8 <fis,\\1 c,\\2 >8 <fis,\\1>8 <fis,\\1 d,\\3 >8 <fis,\\1>8 \n'
        '   \\bar "|."\n'
        '   \\pageBreak\n'
        '#})\n'
        'TrackCVoiceBMusic = #(define-music-function (parser location inTab) (boolean?)\n'
        '#{\n'
        '#})\n'
        'TrackCLyrics = \\lyricmode {\n'
        '   \\set ignoreMelismata = ##t\n'
        '   \n'
        '   \\unset ignoreMelismata\n'
        '}\n'
        'TrackCStaff = \\new Staff <<\n'
        '   \\context Voice = "TrackCVoiceAMusic" {\n'
        '      \\TrackCVoiceAMusic ##f\n'
        '   }\n'
        '   \\context Voice = "TrackCVoiceBMusic" {\n'
        '      \\TrackCVoiceBMusic ##f\n'
        '   }\n'
        '>>\n'
        'TrackCTabStaff = \\new TabStaff \\with { stringTunings = #`( ,(ly:make-pitch -5 0 NATURAL) ,(ly:make-pitch -5 0 NATURAL) ,(ly:make-pitch -5 0 NATURAL) ) } <<\n'
        '   \\context TabVoice = "TrackCVoiceAMusic" {\n'
        "      \\removeWithTag #'chords\n"
        "      \\removeWithTag #'texts\n"
        '      \\TrackCVoiceAMusic ##t\n'
        '   }\n'
        '   \\context TabVoice = "TrackCVoiceBMusic" {\n'
        "      \\removeWithTag #'chords\n"
        "      \\removeWithTag #'texts\n"
        '      \\TrackCVoiceBMusic ##t\n'
        '   }\n'
        '>>\n'
        'TrackCStaffGroup = \\new StaffGroup <<\n'
        '   \\TrackCStaff\n'
        '   \\TrackCTabStaff\n'
        '>>\n'
        '\\score {\n'
        '   \\TrackAStaffGroup\n'
        '   \\header {\n'
        '      title = "Three tracks" \n'
        '      composer = "" \n'
        '      instrument = "Guitar" \n'
        '   }\n'
        '}\n'
        '\\score {\n'
        '   \\TrackBStaffGroup\n'
        '   \\header {\n'
        '      title = "Three tracks" \n'
        '      composer = "" \n'
        '      instrument = "Bass" \n'
        '   }\n'
        '}\n'
        '\\score {\n'
        '   \\TrackCStaffGroup\n'
        '   \\header {\n'
        '      title = "Three tracks" \n'
        '      composer = "" \n'
        '      instrument = "Drums" \n'
        '   }\n'
        '}\n'
    ),
    (('case_multi', ('trackGroup=true',)), "ly"): (
        '#(define (tie::tab-clear-tied-fret-numbers grob)\n'
        '   (let* ((tied-fret-nr (ly:spanner-bound grob RIGHT)))\n'
        "      (ly:grob-set-property! tied-fret-nr 'transparent #t)))\n"
        '\n'
        '\\version "2.14.0"\n'
        '\\paper {\n'
        '   indent = #30\n'
        '   print-all-headers = ##t\n'
        '   ragged-right = ##f\n'
        '   ragged-bottom = ##t\n'
        '}\n'
        '\\layout {\n'
        '   \\context { \\Score\n'
        "      \\override MetronomeMark #'padding = #'5\n"
        '   }\n'
        '   \\context { \\Staff\n'
        "      \\override TimeSignature #'style = #'numbered\n"
        "      \\override StringNumber #'transparent = ##t\n"
        '   }\n'
        '   \\context { \\TabStaff\n'
        "      \\override TimeSignature #'style = #'numbered\n"
        "      \\override Stem #'transparent = ##t\n"
        "      \\override Beam #'transparent = ##t\n"
        "      \\override Tie  #'after-line-breaking = #tie::tab-clear-tied-fret-numbers\n"
        '   }\n'
        '   \\context { \\TabVoice\n'
        "      \\override Tie #'stencil = ##f\n"
        '   }\n'
        '   \\context { \\StaffGroup\n'
        '      \\consists "Instrument_name_engraver"\n'
        '   }\n'
        '}\n'
        'TrackAVoiceAMusic = #(define-music-function (parser location inTab) (boolean?)\n'
        '#{\n'
        '   \\tempo 4=132\n'
        '   \\clef #(if inTab "tab" "treble_8")\n'
        '   \\key cis \\major\n'
        '   \\time 4/4\n'
        '   \\oneVoice\n'
        "    \\ottava #1 <e''\\1 c''\\2 >2 \\ottava #0  \\ottava #1 <g''\\1>8 \\ottava #0 \n"
        '   \\skip 4*4 \n'
        '   <a\\3 e\\4 a,\\5 >1 \n'
        '   \\bar "|."\n'
        '   \\pageBreak\n'
        '#})\n'
        'TrackAVoiceBMusic = #(define-music-function (parser location inTab) (boolean?)\n'
        '#{\n'
        '   \\tempo 4=132\n'
        '   \\clef #(if inTab "tab" "treble_8")\n'
        '   \\key cis \\major\n'
        '   \\time 4/4\n'
        '   \\oneVoice\n'
        '   \\skip 4*4 \n'
        '   \\times 4/5 {<a,\\5>16 <ais,\\5>16 <b,\\5>16 <c\\5>16 <cis\\5>16 } <e\\5>4 <e\\5>4 <e\\5>4 \n'
        '   \\skip 4*4 \n'
        '   \\bar "|."\n'
        '   \\pageBreak\n'
        '#})\n'
        'TrackALyrics = \\lyricmode {\n'
        '   \\set ignoreMelismata = ##t\n'
        '   \n'
        '   \\unset ignoreMelismata\n'
        '}\n'
        'TrackAStaff = \\new Staff <<\n'
        '   \\context Voice = "TrackAVoiceAMusic" {\n'
        '      \\TrackAVoiceAMusic ##f\n'
        '   }\n'
        '   \\context Voice = "TrackAVoiceBMusic" {\n'
        '      \\TrackAVoiceBMusic ##f\n'
        '   }\n'
        '>>\n'
        'TrackATabStaff = \\new TabStaff \\with { stringTunings = #`( ,(ly:make-pitch 0 2 NATURAL) ,(ly:make-pitch -1 6 NATURAL) ,(ly:make-pitch -1 4 NATURAL) ,(ly:make-pitch -1 1 NATURAL) ,(ly:make-pitch -2 5 NATURAL) ,(ly:make-pitch -2 2 NATURAL) ) } <<\n'
        '   \\context TabVoice = "TrackAVoiceAMusic" {\n'
        "      \\removeWithTag #'chords\n"
        "      \\removeWithTag #'texts\n"
        '      \\TrackAVoiceAMusic ##t\n'
        '   }\n'
        '   \\context TabVoice = "TrackAVoiceBMusic" {\n'
        "      \\removeWithTag #'chords\n"
        "      \\removeWithTag #'texts\n"
        '      \\TrackAVoiceBMusic ##t\n'
        '   }\n'
        '>>\n'
        'TrackAStaffGroup = \\new StaffGroup <<\n'
        '   \\set StaffGroup.instrumentName = #"Guitar"\n'
        '   \\TrackAStaff\n'
        '   \\TrackATabStaff\n'
        '>>\n'
        'TrackBVoiceAMusic = #(define-music-function (parser location inTab) (boolean?)\n'
        '#{\n'
        '   \\tempo 4=132\n'
        '   \\clef #(if inTab "tab" "bass_8")\n'
        '   \\key cis \\major\n'
        '   \\time 4/4\n'
        '   \\oneVoice\n'
        '   <a,,\\4>4 <a,,\\4>4 <a,,\\4>4 <a,,~\\4>4 \n'
        '   <a,,\\4>4 <a,,\\4>4 <a,,\\4>4 <a,,\\4>4 \n'
        '   <a,,\\4>4 <a,,\\4>4 <a,,\\4>4 <a,,\\4>4 \n'
        '   \\bar "|."\n'
        '   \\pageBreak\n'
        '#})\n'
        'TrackBVoiceBMusic = #(define-music-function (parser location inTab) (boolean?)\n'
        '#{\n'
        '#})\n'
        'TrackBLyrics = \\lyricmode {\n'
        '   \\set ignoreMelismata = ##t\n'
        '   \n'
        '   \\unset ignoreMelismata\n'
        '}\n'
        'TrackBStaff = \\new Staff <<\n'
        '   \\context Voice = "TrackBVoiceAMusic" {\n'
        '      \\TrackBVoiceAMusic ##f\n'
        '   }\n'
        '   \\context Voice = "TrackBVoiceBMusic" {\n'
        '      \\TrackBVoiceBMusic ##f\n'
        '   }\n'
        '>>\n'
        'TrackBTabStaff = \\new TabStaff \\with { stringTunings = #`( ,(ly:make-pitch -2 4 NATURAL) ,(ly:make-pitch -2 1 NATURAL) ,(ly:make-pitch -3 5 NATURAL) ,(ly:make-pitch -3 2 NATURAL) ) } <<\n'
        '   \\context TabVoice = "TrackBVoiceAMusic" {\n'
        "      \\removeWithTag #'chords\n"
        "      \\removeWithTag #'texts\n"
        '      \\TrackBVoiceAMusic ##t\n'
        '   }\n'
        '   \\context TabVoice = "TrackBVoiceBMusic" {\n'
        "      \\removeWithTag #'chords\n"
        "      \\removeWithTag #'texts\n"
        '      \\TrackBVoiceBMusic ##t\n'
        '   }\n'
        '>>\n'
        'TrackBStaffGroup = \\new StaffGroup <<\n'
        '   \\set StaffGroup.instrumentName = #"Bass"\n'
        '   \\TrackBStaff\n'
        '   \\TrackBTabStaff\n'
        '>>\n'
        'TrackCVoiceAMusic = #(define-music-function (parser location inTab) (boolean?)\n'
        '#{\n'
        '   \\tempo 4=132\n'
        '   \\clef #(if inTab "tab" "treble_8")\n'
        '   \\key c \\major\n'
        '   \\time 4/4\n'
        '   \\oneVoice\n'
        '   <fis,\\1 c,\\2 >8 <fis,\\1>8 <fis,\\1 d,\\3 >8 <fis,\\1>8 <fis,\\1 c,\\2 >8 <fis,\\1>8 <fis,\\1 d,\\3 >8 <fis,\\1>8 \n'
        '   <fis,\\1 c,\\2 >8 <fis,\\1>8 <fis,\\1 d,\\3 >8 <fis,\\1>8 <fis,\\1 c,\\2 >8 <fis,\\1>8 <fis,\\1 d,\\3 >8 <fis,\\1>8 \n'
        '   <fis,\\1 c,\\2 >8 <fis,\\1>8 <fis,\\1 d,\\3 >8 <fis,\\1>8 <fis,\\1 c,\\2 >8 <fis,\\1>8 <fis,\\1 d,\\3 >8 <fis,\\1>8 \n'
        '   \\bar "|."\n'
        '   \\pageBreak\n'
        '#})\n'
        'TrackCVoiceBMusic = #(define-music-function (parser location inTab) (boolean?)\n'
        '#{\n'
        '#})\n'
        'TrackCLyrics = \\lyricmode {\n'
        '   \\set ignoreMelismata = ##t\n'
        '   \n'
        '   \\unset ignoreMelismata\n'
        '}\n'
        'TrackCStaff = \\new Staff <<\n'
        '   \\context Voice = "TrackCVoiceAMusic" {\n'
        '      \\TrackCVoiceAMusic ##f\n'
        '   }\n'
        '   \\context Voice = "TrackCVoiceBMusic" {\n'
        '      \\TrackCVoiceBMusic ##f\n'
        '   }\n'
        '>>\n'
        'TrackCTabStaff = \\new TabStaff \\with { stringTunings = #`( ,(ly:make-pitch -5 0 NATURAL) ,(ly:make-pitch -5 0 NATURAL) ,(ly:make-pitch -5 0 NATURAL) ) } <<\n'
        '   \\context TabVoice = "TrackCVoiceAMusic" {\n'
        "      \\removeWithTag #'chords\n"
        "      \\removeWithTag #'texts\n"
        '      \\TrackCVoiceAMusic ##t\n'
        '   }\n'
        '   \\context TabVoice = "TrackCVoiceBMusic" {\n'
        "      \\removeWithTag #'chords\n"
        "      \\removeWithTag #'texts\n"
        '      \\TrackCVoiceBMusic ##t\n'
        '   }\n'
        '>>\n'
        'TrackCStaffGroup = \\new StaffGroup <<\n'
        '   \\set StaffGroup.instrumentName = #"Drums"\n'
        '   \\TrackCStaff\n'
        '   \\TrackCTabStaff\n'
        '>>\n'
        '\\score {\n'
        '   <<\n'
        '   \\TrackAStaffGroup\n'
        '   \\TrackBStaffGroup\n'
        '   \\TrackCStaffGroup\n'
        '   >>\n'
        '   \\header {\n'
        '      title = "Three tracks" \n'
        '      composer = "" \n'
        '   }\n'
        '}\n'
    ),
    (('case_rich', ('version=2.10.0', 'tablature=false', 'chordDiagram=false', 'text=false')), "ly"): (
        '#(define (tie::tab-clear-tied-fret-numbers grob)\n'
        '   (let* ((tied-fret-nr (ly:spanner-bound grob RIGHT)))\n'
        "      (ly:grob-set-property! tied-fret-nr 'transparent #t)))\n"
        '\n'
        '\\version "2.10.0"\n'
        '\\paper {\n'
        '   indent = #0\n'
        '   printallheaders = ##t\n'
        '   ragged-right = ##f\n'
        '   ragged-bottom = ##t\n'
        '}\n'
        '\\layout {\n'
        '   \\context { \\Score\n'
        "      \\override MetronomeMark #'padding = #'5\n"
        '   }\n'
        '   \\context { \\Staff\n'
        "      \\override TimeSignature #'style = #'numbered\n"
        "      \\override StringNumber #'transparent = ##t\n"
        '   }\n'
        '   \\context { \\TabStaff\n'
        "      \\override TimeSignature #'style = #'numbered\n"
        "      \\override Stem #'transparent = ##t\n"
        "      \\override Beam #'transparent = ##t\n"
        "      \\override Tie  #'after-line-breaking = #tie::tab-clear-tied-fret-numbers\n"
        '   }\n'
        '   \\context { \\TabVoice\n'
        "      \\override Tie #'stencil = ##f\n"
        '   }\n'
        '   \\context { \\StaffGroup\n'
        '      \\consists "Instrument_name_engraver"\n'
        '   }\n'
        '}\n'
        'deadNote = #(define-music-function (parser location note) (ly:music?)\n'
        "   (set! (ly:music-property note 'tweaks)\n"
        "      (acons 'stencil ly:note-head::print\n"
        '         (acons \'glyph-name "2cross"\n'
        "            (acons 'style 'special\n"
        "               (ly:music-property note 'tweaks)))))\n"
        '   note)\n'
        '\n'
        'palmMute = #(define-music-function (parser location note) (ly:music?)\n'
        "   (set! (ly:music-property note 'tweaks)\n"
        "      (acons 'style 'do (ly:music-property note 'tweaks)))\n"
        '   note)\n'
        '\n'
        'TrackAVoiceAMusic = #(define-music-function (parser location inTab) (boolean?)\n'
        '#{\n'
        '   \\tempo 4=100\n'
        '   \\clef #(if inTab "tab" "bass_8")\n'
        '   \\key bes \\major\n'
        '   \\time 4/4\n'
        '   \\voiceOne\n'
        '   <a\'\\1>4_"H"-\\tag #\'texts ^\\markup {"let "it" ring"} <b\'\\1>4\\arpeggio <b\'\\1>4_"H" <a\'\\1>4 \n'
        '   \\oneVoice\n'
        '   \\repeat volta 2 {\n'
        "      \\times 2/3 {<d'\\2>8 <e'\\2>8 <ges'\\2>8 } <ges'\\2>4\\glissando <aes'\\2>4\\glissando <e'\\2>4 \n"
        '   }\n'
        '   \\alternative {\n'
        '   {\n'
        "      <\\bendAfter #+6 d'\\3>2 <\\bendAfter #+6 e'\\3>4 <\\deadNote e'\\3>4 \n"
        '   }\n'
        '   {\n'
        '      <g~\\4 e~\\5 >2-\\tag #\'chords ^\\markup \\fret-diagram #"1-x;2-x;3-x;4-5;5-7;6-x;" <g\\4 e\\5 >2-\\tag #\'texts ^\\markup {"tied"} \n'
        '   }\n'
        '   }\n'
        '   <e,\\6>8\\staccato <g,\\6>8-> <bes,\\6>8-^ <\\parenthesize des\\6>8 <\\palmMute e,\\6>8 r8 <bes,\\6>8\\prall <des\\6\\harmonic>8 \n'
        '   <e,\\6>8\\trill <g,\\6>8:16 \\grace <b,\\6>32 <bes,\\6>8 <des\\6\\harmonic>8 <\\deadNote e,\\6>8 r8 <bes,\\6>8:32 \\grace <ees\\6>16 <des\\6>8 \n'
        '   \\bar "|."\n'
        '   \\pageBreak\n'
        '#})\n'
        'TrackAVoiceBMusic = #(define-music-function (parser location inTab) (boolean?)\n'
        '#{\n'
        '   \\tempo 4=100\n'
        '   \\clef #(if inTab "tab" "bass_8")\n'
        '   \\key bes \\major\n'
        '   \\time 4/4\n'
        '   \\voiceTwo\n'
        '   <c\\5>2 r2 \n'
        '   \\oneVoice\n'
        '   \\repeat volta 2 {\n'
        '      \\skip 4*4 \n'
        '   }\n'
        '   \\alternative {\n'
        '   {\n'
        '      \\skip 4*4 \n'
        '   }\n'
        '   {\n'
        '      \\skip 4*4 \n'
        '   }\n'
        '   }\n'
        '   \\skip 4*4 \n'
        '   \\skip 4*4 \n'
        '   \\bar "|."\n'
        '   \\pageBreak\n'
        '#})\n'
        'TrackALyrics = \\lyricmode {\n'
        '   \\set ignoreMelismata = ##t\n'
        '   \\skip 4 \\skip 4 \\skip 4 \\skip 4 \n'
        '   Hel- lo  world wide- web\n'
        'end - ing\n'
        '   \\unset ignoreMelismata\n'
        '}\n'
        'TrackAStaff = \\new Staff <<\n'
        '   \\context Voice = "TrackAVoiceAMusic" {\n'
        "      \\removeWithTag #'chords\n"
        "      \\removeWithTag #'texts\n"
        '      \\TrackAVoiceAMusic ##f\n'
        '   }\n'
        '   \\context Voice = "TrackAVoiceBMusic" {\n'
        "      \\removeWithTag #'chords\n"
        "      \\removeWithTag #'texts\n"
        '      \\TrackAVoiceBMusic ##f\n'
        '   }\n'
        '   \\new Lyrics \\lyricsto "TrackAVoiceAMusic" \\TrackALyrics\n'
        '>>\n'
        'TrackATabStaff = \\new TabStaff \\with { stringTunings = #`( 4 -1 -5 -10 -15 -20 ) } <<\n'
        '   \\context TabVoice = "TrackAVoiceAMusic" {\n'
        "      \\removeWithTag #'chords\n"
        "      \\removeWithTag #'texts\n"
        '      \\TrackAVoiceAMusic ##t\n'
        '   }\n'
        '   \\context TabVoice = "TrackAVoiceBMusic" {\n'
        "      \\removeWithTag #'chords\n"
        "      \\removeWithTag #'texts\n"
        '      \\TrackAVoiceBMusic ##t\n'
        '   }\n'
        '   \\new Lyrics \\lyricsto "TrackAVoiceAMusic" \\TrackALyrics\n'
        '>>\n'
        'TrackAStaffGroup = \\new StaffGroup <<\n'
        '   \\TrackAStaff\n'
        '>>\n'
        '\\score {\n'
        '   \\TrackAStaffGroup\n'
        '   \\header {\n'
        '      title = "Notation export fixture" \n'
        '      composer = "" \n'
        '      instrument = "Lead" \n'
        '   }\n'
        '}\n'
    ),
}
# END GOLDEN


def xml_tree(text):
    """Parsed tree without the encoding block (date, software) and whitespace-only text."""
    import xml.etree.ElementTree as ET
    root = ET.fromstring(text.encode())
    for parent in root.iter():
        for child in list(parent):
            if child.tag == 'encoding':
                parent.remove(child)
        if parent.text is not None and not parent.text.strip():
            parent.text = None
        parent.tail = None
    return root


def tree_items(node, path=''):
    path = f'{path}/{node.tag}'
    items = [(path, sorted(node.attrib.items()), node.text or '')]
    for child in node:
        items += tree_items(child, path)
    return items


def export(fmt, song, channels=None, **settings):
    from vulturetracker import notation_export, tgimport
    raw = tgimport._raw(song)
    if fmt == 'ly':
        return notation_export.native_to_lilypond(song, raw, settings=settings)
    return notation_export.native_to_musicxml(song, raw, channels=channels or CHANNELS)


def losses(report, feature):
    return [entry for entry in report['losses'] if entry['feature'] == feature]


@unittest.skipIf(guitarpro is None, 'PyGuitarPro not installed')
class TestTuxGuitarOutput(unittest.TestCase):
    """Same native document as TuxGuitar 2.1.0's LilyPond and MusicXML writers."""

    def test_goldens(self):
        import base64
        import xml.etree.ElementTree as ET
        import zlib
        self.assertEqual(len(GOLDEN), 8)
        for ((case, lily), fmt), expected in GOLDEN.items():
            with self.subTest(case=case, fmt=fmt, settings=lily):
                song, channels = globals()[case]()
                settings = dict(item.split('=', 1) for item in lily)
                text, _ = export(fmt, song, channels, **settings)
                self.assertNotIn('\r', text)
                if fmt == 'musicxml':
                    # Compared as trees, attribute order aside, as scratch/notation-export/oracle.py does.
                    expected = zlib.decompress(base64.b64decode(expected)).decode()
                    self.assertEqual(tree_items(xml_tree(text)), tree_items(ET.fromstring(expected)))
                else:
                    self.assertEqual(text, expected)

    def test_musicxml_identifies_vulturetracker(self):
        from vulturetracker import __version__
        text, _ = export('musicxml', fixture())
        self.assertIn(f'<software>VultureTracker {__version__}</software>', text)
        self.assertTrue(text.startswith('<?xml version="1.0" encoding="UTF-8" standalone="no"?>\n<!DOCTYPE score-partwise'))

    def test_song_credits_and_quoted_lilypond_headers(self):
        import xml.etree.ElementTree as ET
        song = fixture()
        song['score']['metadata'] = dict(title='Long "score" \\ title', author='A "Composer" \\ B',
            writer='Lyrics & words', copyright='Copyright <2026>', artist='Band', album='Record',
            date='2026', transcriber='Editor', comments='Rehearsal notes')
        song['module']['title'] = 'Tracker title'
        lily, ly_report = export('ly', song)
        self.assertIn('title = "Long \\"score\\" \\\\ title"', lily)
        self.assertIn('composer = "A \\"Composer\\" \\\\ B"', lily)
        xml, xml_report = export('musicxml', song)
        tree = ET.fromstring(xml)
        self.assertEqual(tree.findtext('work/work-title'), song['score']['metadata']['title'])
        self.assertEqual(tree.findtext('identification/creator[@type="composer"]'), song['score']['metadata']['author'])
        self.assertEqual(tree.findtext('identification/creator[@type="lyricist"]'), 'Lyrics & words')
        self.assertEqual(tree.findtext('identification/rights'), 'Copyright <2026>')
        for report in (ly_report, xml_report):
            reason = losses(report, 'message')[0]['reason']
            for field in ('artist', 'album', 'date', 'transcriber', 'comments'):
                self.assertIn(field, reason)
        self.assertIn('writer', losses(ly_report, 'message')[0]['reason'])
        self.assertNotIn('writer', losses(xml_report, 'message')[0]['reason'])
        multi = multi_fixture()
        multi['score']['tracks']['t1']['name'] = 'Lead "guitar" \\ one'
        grouped, _ = export('ly', multi, MULTI_CHANNELS, trackGroup=True)
        self.assertIn('instrumentName = #"Lead \\"guitar\\" \\\\ one"', grouped)


@unittest.skipIf(guitarpro is None, 'PyGuitarPro not installed')
class TestLossReports(unittest.TestCase):
    def test_each_format_names_what_it_drops(self):
        song = rich_fixture()
        (_, ly), (_, xml) = (export(f, song) for f in ('ly', 'musicxml'))
        for feature in ('rhythm', 'voices', 'rests', 'ties', 'lyrics', 'text', 'repeats', 'chord_frets', 'grace'):
            self.assertFalse(losses(ly, feature), feature)
        for feature in ('pick_stroke', 'marker', 'velocity', 'let_ring', 'chord_name'):
            self.assertTrue(losses(ly, feature), feature)
        for feature in ('text', 'grace', 'stroke', 'chord_name', 'chord_frets', 'vibrato'):
            self.assertTrue(losses(xml, feature), feature)
        for feature in ('pick_stroke', 'marker', 'velocity', 'let_ring', 'lyrics', 'tapping'):
            self.assertFalse(losses(xml, feature), feature)
        entry = losses(ly, 'velocity')[0]
        self.assertEqual((entry['scope'], entry['first']), ('t1', 'track t1 beat o1/t1_v1_b1'))
        self.assertEqual(entry['count'], 32)  # every written note

    def test_unrepresented_native_fields_are_reported(self):
        song = rich_fixture()
        track = song['score']['tracks']['t1']
        track['key']['mode'] = 'minor'
        track['stem'] = 'up'
        song['score']['measures'][0]['swing'] = 'eighth'
        beat = song['score']['patterns']['m5']['beats'][0]
        beat['notes'][0].update(fade_in=True, spelling=dict(step='F', alter=-1))
        song['score']['patterns']['m5']['beats'][1]['notes'][0]['slapping'] = True
        song['score']['patterns']['m5']['beats'][2]['notes'][0]['tremolo_bar'] = dict(
            points=[dict(position=0, value=0), dict(position=12, value=-4)])
        for fmt in ('ly', 'musicxml'):
            text, report = export(fmt, song)
            for feature in ('minor', 'stem', 'swing', 'fade_in', 'spelling', 'slapping', 'tremolo_bar', 'color',
                            'message', 'sound'):
                with self.subTest(fmt=fmt, feature=feature):
                    self.assertTrue(losses(report, feature))
        self.assertIn('\\key bes \\major', export('ly', song)[0])

    def test_unfingered_note_is_omitted_and_reported(self):
        song = fixture()
        note = song['score']['patterns']['m5']['beats'][0]['notes'][0]
        note.update(string=None, fret=None, pitch=119)
        for fmt in ('ly', 'musicxml'):
            text, report = export(fmt, song)
            self.assertEqual(losses(report, 'unfingered')[0]['count'], 1, fmt)
            self.assertEqual(report['notes'], 31, fmt)

    def test_missing_velocity_writes_tg_default_with_a_loss(self):
        song = fixture()
        song['score']['patterns']['m1']['beats'][0]['notes'][0].pop('velocity')
        song['score']['patterns']['m2']['beats'][0]['notes'][0]['velocity'] = 79
        text, report = export('musicxml', song)
        self.assertEqual(losses(report, 'velocity_default')[0]['count'], 1)
        self.assertIn('dynamics="83.1579"', text)

    def test_lilypond_settings_losses(self):
        _, report = export('ly', multi_fixture(), track=2, measureFrom=2, text=False, lyrics=False, trackName=False)
        self.assertEqual({e['scope'] for e in losses(report, 'setting_track')}, {'t1', 't3'})
        self.assertEqual(len(losses(report, 'setting_measures')), 3)
        self.assertEqual(len(losses(report, 'setting_name')), 3)
        self.assertFalse(losses(report, 'setting_text'))
        self.assertEqual(report['settings']['track'], 2)
        _, report = export('ly', rich_fixture(), text='false', chordDiagram='false', lyrics='false')
        for feature in ('setting_text', 'setting_chords', 'setting_lyrics'):
            self.assertTrue(losses(report, feature), feature)
        _, report = export('ly', rich_fixture(), score=False, tablature=False)
        self.assertEqual((report['settings']['score'], report['settings']['tablature']), (True, True))


@unittest.skipIf(guitarpro is None, 'PyGuitarPro not installed')
class TestRefusalsAndPurity(unittest.TestCase):
    def test_structure_tg_cannot_hold_refuses(self):
        from vulturetracker import notation_export, tgimport
        with self.assertRaisesRegex(ValueError, 'no native score'):
            notation_export.native_to_lilypond({'module': {}, 'patterns': {}, 'orders': []}, [])
        song = fixture()
        del song['score']['measures'][2]
        with self.assertRaises(ValueError):
            notation_export.native_to_lilypond(song, tgimport._raw(song))
        with self.assertRaisesRegex(ValueError, 'program/bank mapping'):
            export('musicxml', fixture(), channels={'t9': dict(program=0, bank=0)})
        with self.assertRaisesRegex(ValueError, 'program 0..127'):
            export('musicxml', fixture(), channels={'t1': dict(program=128, bank=0)})
        with self.assertRaisesRegex(ValueError, 'percussion classification'):
            export('musicxml', fixture(), channels={'t1': dict(program=0, bank=128)})
        for bad in (dict(colour=True), dict(score='yes'), dict(track=-2), dict(version='')):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                export('ly', fixture(), **bad)
        for bad in (dict(track=0), dict(track=99), dict(measureFrom=0),
                    dict(measureFrom=4,measureTo=2), dict(measureTo=999)):
            with self.subTest(bad=bad), self.assertRaisesRegex(ValueError,'part number|bar range'):
                export('ly', fixture(), **bad)
        with self.assertRaisesRegex(ValueError, 'object'):
            notation_export.native_to_lilypond(song, tgimport._raw(song), settings=[])

    def test_inputs_are_not_mutated(self):
        import copy
        from vulturetracker import notation_export, tgimport
        song = rich_fixture()
        raw = tgimport._raw(song)
        before = copy.deepcopy(song), [[[repr(c) for c in row] for row in p.rows] for p in raw]
        notation_export.native_to_lilypond(song, raw, settings=dict(trackGroup=True))
        notation_export.native_to_musicxml(song, raw, channels=CHANNELS)
        self.assertEqual((song, [[[repr(c) for c in row] for row in p.rows] for p in raw]), before)


if __name__ == '__main__':
    unittest.main()
