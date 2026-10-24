"""MIDI file import (type 0 and 1 .mid, read by mido): the notes as a song file with the Guitar Pro import's
placeholder sounds (gpimport), so the file plays at once and every sound can be swapped in the tryout.

- Channels: each MIDI channel of a track gets as many channels as it sounds notes at once (a note goes to the first one
  free where it starts; a new note cuts the one before it, as in a tracker); drums (MIDI channel 10) a channel per drum
  key, on the placeholder kit's General MIDI keys. Basses (programs 33-40) get the bass placeholder, the rest the pluck.
- Ticks to rows: the coarsest grid that holds every note start and bar line (gpimport.grid_for: 4 rows a quarter for
  sixteenths, 12 with triplets), speed and tempo so a row lasts what it lasts in the file. A file played in (or finer
  than 12 rows a quarter) gets sixteenths at speed 6, each note delayed (SDx) to the nearest of 24 ticks a quarter.
  A note ends with a note-off (===) at the row nearest its end.
- Bars (from the time signatures, 4/4 without one) to patterns, identical bars sharing one; tempo changes to Txx on a
  channel of their own (of several on one tick or row, the last); velocity to the volume column; a channel's volume
  (CC 7) and pan (CC 10) before its first note to the channel's own.
- Track names: UTF-8 where they decode as UTF-8, else Latin-1 (OpenMPT reads Latin-1), up to a NUL as OpenMPT does.
- As OpenMPT's MIDI import does (Load_mid.cpp): pitch bends to E (down) and F (up) slides on the rows they change on,
  extra-fine under a quarter semitone, fine under a semitone, else over the row's ticks, each row correcting what the
  slides before it left over; the bend range from RPN 0 (2 semitones until set; CC 121 resets it and the bend); a note
  struck under a bend starts on the bend's nearest semitone. The sustain pedal (CC 64 at 64 or more) holds a note let go
  until the pedal is let up, an all-notes-off (CC 120, 123) or the same key struck again. Markers and cue points name
  what they fall in: OpenMPT names that pattern; here a named section runs from its bar to the next marker's.
  Deliberately not as OpenMPT: drum channels take no bends (their keys are kit pieces here).

Left out (counted in the warnings): later volume, pan and other controller changes, notes outside C-0..B-9; past 64
channels, the least used."""
import bisect
import collections
import io
import math
import struct
from pathlib import Path

from .gpimport import GM_DRUMS, Lane, Placeholders, grid_for, lane_name, note_name, speed_tempo, write_song


def _name(text):
    """A track name as written: mido reads its bytes as Latin-1, while most files today hold UTF-8."""
    text = text.split("\0", 1)[0]
    try:
        text = text.encode("latin-1").decode("utf-8")
    except UnicodeError:
        pass
    return text.strip()


KEPT = (6, 64, 98, 99, 100, 101, 120, 121, 123)  # the controllers bends and the pedal are read from


def bend_fx(diff, speed):
    """A bend of `diff` 1/64 semitones as one row's slide, as OpenMPT's MIDI import writes it: extra-fine (EEx, FEx)
    under 16, fine (EFx, FFx; 1/16 semitone) under 64, else xx/16 semitone on each of the row's speed-1 ticks.
    Returns (the effect, the 1/64 semitones it moves) or (None, 0)."""
    a, ticks = abs(diff), max(1, speed - 1)
    if not a:
        return None, 0
    if a < 16:
        param, moved = 0xE0 | a, a
    elif a < max(64, 4 * ticks):  # OpenMPT keeps 16 ticks a row at most; past that a normal slide could round to 00
        f = min((a + 3) // 4, 15)
        param, moved = 0xF0 | f, 4 * f
    else:
        param = min(a // (4 * ticks), 0xDF)
        moved = 4 * param * ticks
    return f"{'E' if diff < 0 else 'F'}{param:02X}", int(math.copysign(moved, diff))


def import_midi(src, song_path, samples_dir):
    """A MIDI file as a song YAML plus placeholder WAVs in `samples_dir`. Returns (song dict, warnings)."""
    try:
        import mido
    except ImportError:
        raise ValueError("MIDI import needs mido: pip install mido")
    try:  # from memory: mido reads a chunk by its claimed size, which on a file preallocates up to 4 GB for a bad header
        mid = mido.MidiFile(file=io.BytesIO(Path(src).read_bytes()))
    except Exception as e:  # noqa: BLE001 - mido raises what its reader hits (OSError, EOFError, KeyError, ...)
        raise ValueError(f"{src}: not a readable MIDI file ({type(e).__name__}: {e})") from e
    if mid.type == 2:
        raise ValueError(f"{src}: a type 2 MIDI file (independent sequences) is not supported")
    q = mid.ticks_per_beat
    if q <= 0:
        raise ValueError(f"{src}: the time division is {q} (SMPTE timing or a broken header); ticks a quarter note are needed")
    warnings, skipped = [], {}

    def skip(what):
        skipped[what] = skipped.get(what, 0) + 1

    tempos, sigs, notes, names, setup, marks, ctl = [], [], [], [], {}, [], []
    for ti, track in enumerate(mid.tracks):
        t, held, program, started = 0, {}, {}, set()
        names.append("")
        for msg in track:
            t += msg.time
            if msg.type == "set_tempo" and msg.tempo > 0:  # a tempo of 0 us a quarter is no tempo
                tempos.append((t, msg.tempo))
            elif msg.type == "time_signature":
                sigs.append((t, msg.numerator, msg.denominator))
            elif msg.type == "track_name" and not names[ti]:
                names[ti] = _name(msg.name)
            elif msg.type in ("marker", "cue_marker") and _name(msg.text):
                marks.append((t, _name(msg.text)))
            elif msg.type == "program_change":
                program[msg.channel] = msg.program
            elif msg.type == "note_on" and msg.velocity:
                held.setdefault((msg.channel, msg.note), []).append((t, msg.velocity, program.get(msg.channel, 0)))
                started.add(msg.channel)
            elif msg.type in ("note_on", "note_off") and held.get((msg.channel, msg.note)):
                a, vel, prog = held[msg.channel, msg.note].pop(0)
                notes.append((ti, msg.channel, msg.note, a, t, vel, prog))
            elif msg.type == "control_change" and msg.control in (7, 10) and msg.channel not in started:
                setup[ti, msg.channel, msg.control] = msg.value
            elif msg.type == "pitchwheel" or msg.type == "control_change" and msg.control in KEPT:
                ctl.append((t, ti, len(ctl), msg))
            elif msg.type == "control_change":
                skip("controller changes")
        for (ch, key), left in held.items():  # held to the end of the track
            notes += [(ti, ch, key, a, t, vel, prog) for a, vel, prog in left]
    if not notes:
        raise ValueError("the file has no notes")

    # per MIDI channel, as OpenMPT keeps them (across tracks): the bend in 1/64 semitones and the pedal over time
    bends, pedal, state = {}, {}, {}
    for t, _, _, msg in sorted(ctl, key=lambda e: e[:3]):
        ch, c = msg.channel, getattr(msg, "control", None)
        s = state.setdefault(ch, {"rpn": 0x3FFF, "range": 2, "raw": 0})
        if msg.type == "pitchwheel":
            s["raw"] = msg.pitch
        elif c == 101:
            s["rpn"] = (s["rpn"] & 0x7F) | msg.value << 7
        elif c == 100:
            s["rpn"] = (s["rpn"] & 0x3F80) | msg.value
        elif c in (98, 99):
            s["rpn"] = 0x3FFF
        elif c == 6 and s["rpn"] == 0:
            s["range"] = max(1, msg.value)
        elif c == 121:
            s.update(rpn=0x3FFF, range=2, raw=0)
        if msg.type == "pitchwheel" or c in (6, 121):
            bends.setdefault(ch, []).append((t, round(s["raw"] * s["range"] * 64 / 8192)))
        if c in (64, 120, 121, 123):
            pedal.setdefault(ch, []).append((t, "down" if c == 64 and msg.value >= 64 else "up" if c == 64 else
                                             "reset" if c == 121 else "off"))
    starts = {}
    for n in sorted(notes, key=lambda n: n[3]):
        starts.setdefault((n[1], n[2]), []).append(n[3])
    last = max(n[4] for n in notes)

    def let_go(ch, key, a, b):
        """Where a note let go at `b` stops sounding: an all-notes-off before; with the pedal down at `b`, the pedal let
        up (or an all-notes-off) after, or the key struck again (OpenMPT's MIDINoteOff)."""
        ev = pedal.get(ch, ())
        cut = next((t for t, kind in ev if a < t < b and kind == "off"), None)
        if cut is not None:
            return cut
        if next((kind for t, kind in reversed(ev) if t <= b), None) != "down":
            return b
        up = next((t for t, kind in ev if t > b and kind in ("up", "off")), last)
        return min(up, next((s for s in starts[ch, key] if s >= b and s > a), up))
    notes = [(ti, ch, key, a, let_go(ch, key, a, b) if ch != 9 else b, vel, prog) for ti, ch, key, a, b, vel, prog in notes]

    end = max(n[4] for n in notes)
    sigs.sort(key=lambda s: s[0])  # stable: of several on one tick, the last in the file counts
    if not sigs or sigs[0][0]:
        sigs.insert(0, (0, 4, 4))
    lines, k, num, den = [0], 0, 4, 4  # bar lines: a time signature change mid-bar starts a bar there
    while (lines[-1] < end or len(lines) < 2) and len(lines) <= 256:  # past 256 bars the cut below applies anyway
        while k < len(sigs) and sigs[k][0] <= lines[-1]:
            num, den = sigs[k][1:]
            k += 1
        nxt = lines[-1] + max(1, round(num * q * 4 / den))
        lines.append(min(nxt, sigs[k][0]) if k < len(sigs) else nxt)
    if len(lines) > 256:
        warnings.append(f"{len(lines) - 1} bars; IT's order list holds 255: cut there")
        lines = lines[:256]
    times = {n[3] for n in notes} | set(lines)
    r = grid_for(times, q)
    delayed = any((x * r) % q for x in times) or r > 12
    if delayed:
        r = 4  # played in (or 1/32 triplets): sixteenths, each note delayed to its tick (24 a quarter at speed 6)
        warnings.append("timing finer than 12 rows a quarter: 4 rows a quarter, notes delayed (SDx) to the nearest tick")
    tempos.sort(key=lambda t: t[0])  # stable, as the signatures
    first = [us for tick, us in tempos if not tick]
    bpm = 60e6 / first[-1] if first else 120.0
    # SDx delays a note 0-15 ticks: 16 ticks a row at most (OpenMPT's MIDI import keeps 2-16 for the same reason)
    speed, tempo, exact = speed_tempo(bpm, r, 16 if delayed else 31)
    if abs(tempo - exact) / exact > 0.005:
        warnings.append(f"{bpm:g} BPM at {r} rows a quarter needs tempo {exact:.1f}: {tempo} is used")

    def row(tick):
        return round(tick * r / q)

    def at(tick):  # (row, delay in ticks): the delay is 0 on a grid that holds every note
        return divmod(round(tick * r * speed / q), speed)

    tempo_lane, now = Lane("Tempo"), exact
    for tick, us in tempos:
        want = 60e6 / us * r * speed / 24
        if tick and row(tick) < row(lines[-1]) and round(want) != round(now):
            tempo_lane.put(row(tick), fx=f"T{max(32, min(255, round(want))):02X}", force=True)  # the last on a row
            if not 32 <= want <= 255:
                warnings.append(f"tempo {60e6 / us:g} BPM is past IT's 32-255 at speed {speed}: clamped")
        now = want

    def bend_at(ch, tick):
        ev = bends.get(ch, ())
        i = bisect.bisect_right([t for t, _ in ev], tick)
        return ev[i - 1][1] if i else 0

    ph = Placeholders(samples_dir, song_path)
    lanes, total = {}, row(lines[-1])
    for ti, ch, key, a, b, vel, prog in sorted(notes, key=lambda n: (n[3], n[0], n[1], n[2])):
        bent = bend_at(ch, a) if ch != 9 else 0
        shift = int((bent + (32 if bent > 0 else -32)) / 64)  # a note under a bend: on its nearest semitone
        if 0 <= key + shift < 120:
            key += shift
        else:
            shift = 0  # past the keyboard: the note as written, the whole bend slid
        if not 0 <= key < 120:
            skip("notes outside C-0..B-9")
            continue
        start, delay = at(a)
        if start >= total:
            continue
        drums = ch == 9
        ins = ph.instrument("drums" if drums else "bass" if 32 <= prog <= 39 else "pluck")
        base = names[ti][:10] or "ch"
        if drums:
            ln = lanes.setdefault((ti, ch, 1, key), Lane(lane_name(base, GM_DRUMS.get(key, note_name(key)))))
        else:
            voices = [v for (t2, c2, d2, _), v in lanes.items() if (t2, c2, d2) == (ti, ch, 0)]
            ln = next((v for v in voices if v.free <= start), None)
            if ln is None:
                ln = lanes[ti, ch, 0, len(voices)] = Lane(lane_name(base, f"{ch + 1}.{len(voices) + 1}"))
                ln.ends = []
            ln.free = max(start + 1, row(b))
            ln.ends.append(ln.free)
            ln.spans = getattr(ln, "spans", []) + [(start, ln.free, shift * 64)]
        ln.put(start, note_name(key), ins, f"v{max(1, min(64, round(vel * 64 / 127))):02d}", f"SD{delay:X}" if delay else None, force=True)
        for control, attr in ((7, "volume"), (10, "pan")):
            if (ti, ch, control) in setup:
                setattr(ln, attr, min(64, round(setup[ti, ch, control] / 2) if control == 10 else round(setup[ti, ch, control] * 64 / 127)))
    for (ti, ch, drum, _), ln in lanes.items():  # bends: slides on the rows the bend changes on, while a note sounds
        if drum or ch not in bends:
            continue
        changes = {}
        for t, v in bends[ch]:
            changes[at(t)[0]] = v  # of several on a row, the last
        rows = sorted(changes)
        porta, span = 0, None
        for at_row in sorted(set(changes) | {s[0] for s in ln.spans}):
            span = next((s for s in ln.spans if s[0] == at_row), span)
            if span and span[0] == at_row:
                porta = span[2]
            if span is None or not span[0] <= at_row < span[1]:
                continue
            i = bisect.bisect_right(rows, at_row)
            target = changes[rows[i - 1]] if i else 0
            fx, moved = bend_fx(target - porta, speed)
            if fx and ln.cells.get(at_row, ["...", "..", "...", "..."])[3] == "...":  # a delayed note's SDx stays
                ln.put(at_row, fx=fx)
                porta += moved
    for ln in lanes.values():  # note-offs, where no other note starts on the channel
        for e in getattr(ln, "ends", ()):
            if e < total:
                ln.off(e)
    lanes = [lanes[k] for k in sorted(lanes)]
    room = 64 - bool(tempo_lane.cells)
    if len(lanes) > room:  # the busiest are kept: a chord's rare fifth voice goes before a part's only channel
        keep = set(sorted(lanes, key=lambda ln: len(ln.cells), reverse=True)[:room])
        warnings.append(f"{len(lanes) + 64 - room} channels: IT has 64, the {len(lanes) - room} least used are left out")
        lanes = [ln for ln in lanes if ln in keep]
    lanes += [tempo_lane] if tempo_lane.cells else []
    for what, count in skipped.items():
        warnings.append(f"{count} {what} left out")
    bars = [(f"b{i + 1}", row(lines[i]), row(lines[i + 1]) - row(lines[i])) for i in range(len(lines) - 1)]
    named = {}  # markers: the bar each falls in, named by it (of several in a bar, the last)
    for t, text in sorted(marks, key=lambda m: m[0]):
        i = bisect.bisect_right(lines, t) - 1
        if 0 <= i < len(bars):
            named[i] = text
    sections, firsts = {}, sorted(named)
    for i, first in enumerate(firsts):
        name = next(n for n in (named[first], *(f"{named[first]} {k}" for k in range(2, 999))) if n not in sections)
        sections[name[:80]] = [first, firsts[i + 1] if i + 1 < len(firsts) else len(bars)]
    title = names[0] if mid.type == 1 and names[0] else Path(src).stem
    from .api import written_by_line
    head = (f"# Imported from {Path(src).name} by vulturetracker import (MIDI: placeholder sounds, swap them in the tryout)\n"
            f"# {bpm:g} BPM, {r} rows a quarter note: speed {speed}, tempo {tempo}\n" + written_by_line())
    song = write_song(song_path, title, lanes, bars, ph, r, speed, tempo, [s[1:] for s in sigs if not s[0]][-1], warnings, head,
                      sections)
    return song, warnings


# ---------------------------------------------------------------------------------------------------------------
# Score import: a native TAB score from a MIDI file the way TuxGuitar 2.1.0 imports one (IO-08).
# Pinned: 2c46e2a1cccdfdfa6e6f2692f241bd60bf418129, TuxGuitar-midi MidiFileReader/MidiSongReader/MidiSettings,
# TGDuration (splitPreciseDuration[Approximately], fromTime), TGMeasureManager (updateBeatsPreciseStart,
# autoCompleteSilences, getMeasureErrors, fixVoice*), TGTrackManager (allocate*NotesToStrings,
# fixInvalidTiedNotes), GMChannelRouter, TuningManager priority tunings and TGDrumMap. TuxGuitar builds one
# voice, string 1 and velocity 64 for every note, then fingers the notes; tgimport.read_tree validates the
# result. Java integer division, float32 rounding, list order and HashMap iteration order are reproduced where
# the chosen durations depend on them. A different path from import_midi above (tracker rows).

QT = 960                                   # TGDuration.QUARTER_TIME
WHOLE = 11531520                           # TGDuration.WHOLE_PRECISE_DURATION
PER_TICK = WHOLE // (4 * QT)               # precise units per tick (toPreciseTime/toTime)
SHORTEST = 64
DIVISIONS = ((1, 1), (3, 2), (5, 4), (6, 4), (7, 4), (9, 8), (10, 8), (11, 8), (12, 8), (13, 8))
# TuningManager.getPriorityTgTunings over tunings.xml (the presets that carry a priority, in priority order).
PRIORITY_TUNINGS = ((64, 59, 55, 50, 45, 40), (64, 59, 55, 50, 45, 38), (64, 59, 55, 50, 45, 40, 35),
                    (43, 38, 33, 28), (43, 38, 33, 28, 23))
# TGDrumMap's preferred strings (default 1).
DRUM_STRINGS = {35: 6, 36: 6, 37: 4, 38: 4, 40: 4, 42: 2, 46: 2, 44: 2, 49: 1, 57: 1, 55: 1, 52: 1,
                51: 2, 59: 2, 53: 2, 41: 5, 43: 5, 45: 5, 47: 4, 48: 3, 50: 3}
MAX_FRET = 29                              # TGTrack.DEFAULT_MAX_FRET
PLAIN = (4, False, False, 1, 1)            # a new TGDuration: a quarter


class _Invalid(Exception):
    """TGDuration.setPreciseValue's IllegalArgumentException."""


def _jdiv(a, b):
    """Java long division (truncates toward zero)."""
    q = abs(a) // abs(b)
    return q if (a >= 0) == (b > 0) else -q


def _jmod(a, b):
    return a - b * _jdiv(a, b)


def _precise(d):
    value, dotted, double, enters, times = d
    p = WHOLE // value
    p = p * 3 // 2 if dotted else p * 7 // 4 if double else p
    return p * times // enters


def _ticks(d):
    value, dotted, double, enters, times = d
    t = 3840 // value
    t = t + t // 2 if dotted else t + (t // 4) * 3 if double else t
    return t * times // enters


def _duration_map():
    """createDurationMap's entries, and their order in java.util.HashMap.values()."""
    entries = {}
    for enters, times in DIVISIONS:
        for i in range(3):
            for v in (1, 2, 4, 8, 16, 32, 64):
                d = (v, i == 1, i == 2, enters, times)
                entries.setdefault(_precise(d), d)
    capacity = 16
    while len(entries) > capacity * 3 // 4:
        capacity *= 2

    def index(key):
        h = (key ^ (key >> 32)) & 0xFFFFFFFF
        return (h ^ (h >> 16)) & (capacity - 1)
    sizes = collections.Counter(index(k) for k in entries)
    # A bin of 8 or more would be a tree, whose iteration order is not insertion order.
    assert max(sizes.values()) < 8
    return entries, [entries[k] for k in sorted(entries, key=index)]   # sorted() is stable: insertion order per bin


DURATIONS, DURATION_ORDER = _duration_map()
PRIME_DIVISIONS = sorted([d for d in DIVISIONS if math.gcd(*d) == 1], key=lambda d: -d[0])


def _from_precise(p):
    if p not in DURATIONS:
        raise _Invalid(p)
    return DURATIONS[p]


def _split(D, maximum, max_value=None, max_division=None):
    """TGDuration.splitPreciseDuration(D, max, factory, maxDurationValue, maxDivision); None when it fails."""
    out = []
    if D == 0:
        return out
    maximum = min(maximum, WHOLE)
    max_base = WHOLE
    while maximum < max_base:
        max_base //= 2
    for enters0, times in PRIME_DIVISIONS:
        enters = enters0 * 3 if max_division is not None and max_division < 9 and enters0 == 3 else enters0
        if not (enters0 == 1 or (_jmod(D, enters) != 0 and (max_division is None or enters0 <= max_division))):
            continue
        found, sub = False, 1
        while sub <= 4 and not found:
            base = WHOLE * times // (enters0 * (SHORTEST if max_value is None else max_value)) // sub
            if base > max_base or (max_value is not None and sub != 1):
                break
            ratio = _jdiv(D, base)
            if enters0 == 1 or (_jmod(D, base) == 0 and (ratio & (ratio - 1)) == 0):
                subtract = D
            else:
                subtract = base
                while _jmod(D - subtract, enters) != 0 and subtract <= D:
                    subtract += base
            if _jmod(subtract, base) == 0 and subtract <= D:
                n_base, n = _jdiv(subtract, base), 1
                while n_base != 0 and _jmod(n_base, 2) == 0 and n * 2 * base <= maximum:
                    n *= 2
                    n_base = _jdiv(n_base, 2)
                ok, dotted, double = sub == 1, False, False
                if sub == 2:
                    ok, dotted = _jmod(n_base, 3) == 0, True
                    n_base, base = _jdiv(n_base, 3), base * 2
                elif sub == 4:
                    ok, double = _jmod(n_base, 7) == 0, True
                    n_base, base = _jdiv(n_base, 7), base * 4
                if ok:
                    for _ in range(max(n_base, 0)):
                        value, _, _, e, t = _from_precise(n * base)
                        out.append((value, dotted, double, e, t))
                        D -= _precise(out[-1])
                    found = True
            sub *= 2
    return out if D == 0 else None


def _complexity(d, other):
    """TGDuration.moreComplexThan."""
    if other is None:
        return 1 if d[1] or d[2] or d[3:] != (1, 1) else 0
    if d[2] and not other[2]:
        return 1
    if d[3] != other[3]:
        return 1 if d[3] > other[3] else -1
    return 1 if d[1] and not other[1] else 0


def _f32(x):
    return struct.unpack('f', struct.pack('f', x))[0]


def _split_approximately(t, maximum, max_value=None, max_division=None):
    """TGDuration.splitPreciseDurationApproximately."""
    if t == 0:
        return []
    exact = _split(t, maximum, max_value, max_division)
    approx, shortest = None, SHORTEST if max_value is None else max_value
    best_error, best = -1, None
    if t <= WHOLE // shortest:
        best_error, approx = t, []
    for d in DURATION_ORDER:
        if d[0] <= shortest and (max_division is None or d[3] <= max_division) and not d[2]:
            error = abs(_precise(d) - t)
            if error <= WHOLE * d[4] // shortest // d[3] and (
                    best_error < 0 or _complexity(d, best) < 0 or
                    (_complexity(d, best) == 0 and (error < best_error or best_error < 0))):
                best, best_error = d, error
    if best is not None:
        approx = [best]
    if approx is None:
        approx, best_error = [], 0
        maximum = min(maximum, WHOLE)
        max_base = WHOLE
        while maximum < max_base:
            max_base //= 2
        for enters, times in PRIME_DIVISIONS:
            if max_division is not None and enters > max_division:
                continue
            base = WHOLE * times // (enters * shortest)
            if base > max_base:
                break
            # Math.round((float)(t - 1) / (float)base), in float32.
            n_base, found, total = math.floor(_f32(_f32(t - 1) / _f32(base)) + 0.5), [], 0
            while n_base > 0:
                add, n_add = 0, 0
                if 2 * base > maximum:
                    add, n_add, n_base = base, n_base, 0
                elif n_base % 2:
                    add, n_add, n_base = base, 1, n_base - 1
                else:
                    n_base, base = n_base // 2, base * 2
                for _ in range(n_add):
                    found.append(_from_precise(add))
                    total += add
            found.reverse()
            if not approx or abs(t - total) <= best_error:
                approx, best_error = found, abs(t - total)
    if exact is None:
        return approx
    if any(d[3:] != exact[0][3:] for d in exact) or len(approx) < len(exact):
        return approx
    return exact


def _from_time(ticks):
    """TGDuration.fromTime(factory, time) (quantization off). Upstream looks ticks up in the precise-keyed
    map, which never matches a bar's ticks, so this is the longest plain value that fits."""
    threshold = {95: 3, 177: 3, 138: 1, 854: 1, 748: 2}.get(ticks, 2 if ticks < 60 else 0)
    for i in range(threshold + 1):
        if ticks - i in DURATIONS:
            return DURATIONS[ticks - i]
    for v in (1, 2, 4, 8, 16, 32, 64):
        if ticks >= 3840 // v:
            return (v, False, False, 1, 1)
    return (SHORTEST, False, False, 1, 1)


def _smf(data):
    """MidiFileReader.getSequence: (resolution, [[(tick, kind, payload)], ...]) per track in file order."""
    if not isinstance(data, bytes):
        raise ValueError('MIDI: input must be bytes')
    pos = 0

    def take(n):
        nonlocal pos
        if pos + n > len(data):
            raise ValueError(f'MIDI: truncated at byte {pos}')
        pos += n
        return data[pos - n:pos]
    if take(4) != b'MThd':
        raise ValueError('MIDI: not a MIDI file (wrong header magic)')
    length = int.from_bytes(take(4), 'big')
    if length < 6:
        raise ValueError('MIDI: corrupt MIDI file (header length)')
    kind, count = (int.from_bytes(take(2), 'big', signed=True) for _ in range(2))
    division = int.from_bytes(take(2), 'big')
    if kind not in (0, 1):
        raise ValueError('MIDI: TuxGuitar reads type 0 and 1 files only')
    if count <= 0 or kind == 0 and count != 1:
        raise ValueError('MIDI: corrupt MIDI file (track count)')
    if division & 0x8000:
        if 256 - (division >> 8) not in (24, 25, 29, 30):
            raise ValueError('MIDI: corrupt MIDI file (illegal frame division type)')
    resolution = division & (0xFF if division & 0x8000 else 0x7FFF)
    if resolution <= 0:
        raise ValueError('MIDI: zero time division')
    take(length - 6)
    tracks = []
    for _ in range(count):
        while take(4) != b'MTrk':
            skip = int.from_bytes(take(4), 'big')
            take(skip + skip % 2)
        length = int.from_bytes(take(4), 'big')
        end = pos + length
        ticks, status, events = 0, -1, []

        def byte():
            if pos >= end:
                raise ValueError('MIDI: an event runs past its track chunk')
            return take(1)[0]

        def vlq():
            value = 0
            for _ in range(4):
                b = byte()
                value = (value << 7) | (b & 0x7F)
                if b < 128:
                    return value
            raise ValueError('MIDI: unterminated variable-length quantity')
        while pos < end:
            ticks += vlq()
            first = byte()
            running = first < 0x80
            if running:
                if status == -1:
                    raise ValueError('MIDI: status byte missing')
                first, held = status, first
            if first < 0xF0:
                command = first & 0xF0
                if command in (0xC0, 0xD0):
                    events.append((ticks, 'short', (first, held if running else byte())))
                    status = first
                elif command in (0x80, 0x90, 0xA0, 0xB0, 0xE0):
                    d1 = held if running else byte()
                    events.append((ticks, 'short', (first, d1, byte())))
                    status = first
            elif first in (0xF0, 0xF7):
                status = -1
                for _ in range(vlq()):
                    byte()
            elif first == 0xFF:
                status = -1
                meta = byte()
                events.append((ticks, 'meta', (meta, bytes(byte() for _ in range(vlq())))))
        tracks.append(events)
    return resolution, tracks


def _start(beat):
    """TGBeat.getStart: ticks, or toTime(preciseStart) once a precise start is set."""
    return beat['start'] if beat['precise'] is None else beat['precise'] // PER_TICK


def _beat(start=None, precise=None):
    return dict(start=start, precise=precise, voice=dict(empty=True, duration=PLAIN, notes=[]))


def _place(measure):
    """TGMeasureManager.updateBeatsPreciseStart for the one voice MIDI import uses."""
    measure['beats'].sort(key=_start)
    end, keep = None, []
    for i, beat in enumerate(measure['beats']):
        if i == 0:
            beat['precise'] = measure['start'] * PER_TICK
            if not beat['voice']['empty']:
                end = beat['precise'] + _precise(beat['voice']['duration'])
        elif beat['voice']['empty'] or not end:
            continue                                  # TG removes a beat it cannot place
        else:
            beat['precise'] = end
            end += _precise(beat['voice']['duration'])
        keep.append(beat)
    measure['beats'] = keep


def _silences(measure, start, length, losses):
    """createSilences: rests from an exact split, none when there is none."""
    durations = _split(length, measure['length'] * PER_TICK)
    if durations is None:
        losses['unfilled gaps'] += 1
        return
    for d in durations:
        beat = next((b for b in measure['beats'] if b['precise'] == start), None)
        if beat is None:
            beat = _beat(precise=start)
            measure['beats'].append(beat)
        beat['voice'].update(empty=False, duration=d)
        start += _precise(d)


def _complete(measure, losses):
    """autoCompleteSilences for voice 1."""
    mstart, mend = measure['start'] * PER_TICK, (measure['start'] + measure['length']) * PER_TICK
    beat = min(measure['beats'], key=_start) if measure['beats'] else None
    used = [b for b in measure['beats'] if not b['voice']['empty']]
    if beat is None or not used:
        _silences(measure, mstart, mend - mstart, losses)
        return
    first = min(used, key=_start)
    if first['precise'] > mstart:
        _silences(measure, mstart, first['precise'] - mstart, losses)
    while beat is not None:
        if not beat['voice']['empty']:
            end = beat['precise'] + _precise(beat['voice']['duration'])
            later = [b['precise'] for b in measure['beats']
                     if b['precise'] is not None and b['precise'] > beat['precise'] and not b['voice']['empty']]
            following = min(later) if later else mend
            if end < following:
                _silences(measure, end, following - end, losses)
        after = [b for b in measure['beats'] if _start(b) > _start(beat)]
        beat = min(after, key=_start) if after else None


def _voice_errors(measure):
    """getMeasureErrors' duration bits for voice 1, in list order (overlap 1, too short 4, too long 8)."""
    code, last = 0, -1
    for b in measure['beats']:
        if not b['voice']['empty']:
            if last >= 0 and b['precise'] < last:
                code |= 1
            last = b['precise'] + _precise(b['voice']['duration'])
    if last >= 0:
        mend = (measure['start'] + measure['length']) * PER_TICK
        code |= 4 if last < mend else 8 if last > mend else 0
    return code


def _fix_voice(measure, code, losses):
    """fixVoice: fixVoiceOverlap, then fixVoiceLongShort."""
    overlap = bool(code & 1)
    while overlap:
        overlap, previous = False, None
        for beat in measure['beats']:
            if beat['voice']['empty']:
                continue
            if previous is not None:
                over = previous['precise'] + _precise(previous['voice']['duration']) - beat['precise']
                if over > 0:
                    try:
                        previous['voice']['duration'] = _from_precise(_precise(previous['voice']['duration']) - over)
                        overlap = True
                        _place(measure)
                        break
                    except _Invalid:
                        pass
            previous = beat
    if not code & 12:
        return
    mend = (measure['start'] + measure['length']) * PER_TICK

    def last_voice():
        used = [b for b in measure['beats'] if not b['voice']['empty']]
        return max(reversed(used), key=_start) if used else None   # getLastVoice: the first of equal starts

    def remove(beat):
        measure['beats'].remove(beat)                # removeVoice drops a beat left without voices
        losses['removed beats'] += 1
    while measure['beats'] and measure['beats'][-1]['precise'] >= mend:
        remove(measure['beats'][-1])
    beat = last_voice()
    if beat is not None and beat['precise'] + _precise(beat['voice']['duration']) > mend:
        try:
            beat['voice']['duration'] = _from_precise(mend - beat['precise'])
        except _Invalid:
            remove(beat)
    beat = last_voice()
    gap = mend - beat['precise'] - _precise(beat['voice']['duration']) if beat else 0
    while gap > 0:
        if _split(gap, measure['length'] * PER_TICK) is not None:
            _complete(measure, losses)
            gap = 0
        else:
            whole = _split(mend - beat['precise'], measure['length'] * PER_TICK)
            if whole is not None and len(whole) == 1:
                beat['voice']['duration'], gap = whole[0], 0
            else:
                remove(beat)
                beat = last_voice()
                gap = mend - beat['precise'] - _precise(beat['voice']['duration']) if beat else 0


def _finger(beat, tuning, percussion, losses):
    """allocateNotesToLowestFret / allocatePercussionNotesToStrings (notes arrive on string 1, fret = pitch)."""
    notes = beat['voice']['notes']
    if percussion:
        notes.sort(key=lambda n: DRUM_STRINGS.get(n['value'], 1))
    else:
        notes.sort(key=lambda n: n['value'])
        notes.reverse()
    free = list(range(1, len(tuning) + 1))
    for note in notes:
        choice = None
        if percussion:
            preferred = DRUM_STRINGS.get(note['value'], 1)
            if preferred in free:
                choice = preferred
            else:
                distance = -1
                for s in free:
                    if abs(s - preferred) <= distance or distance < 0:
                        choice, distance = s, abs(s - preferred)
        else:
            low = -1
            for s in free:
                fret = note['value'] - tuning[s - 1]
                if 0 <= fret <= MAX_FRET and (low < 0 or fret < low):
                    choice, low = s, fret
            if choice is not None:
                note['value'] -= tuning[choice - 1]
        note['string'] = choice or 0
        if choice:
            free.remove(choice)
    kept = [n for n in notes if n['string']]
    losses['unfingered notes'] += len(notes) - len(kept)
    beat['voice']['notes'] = kept


def _tuning(low, high):
    """TrackTuningHelper.getStrings."""
    for tuning in PRIORITY_TUNINGS:
        if low >= min(tuning) and high - MAX_FRET <= max(tuning):
            return list(tuning)
    count = 6
    spacing = _jdiv(high - (MAX_FRET - 4) - low, count)
    if spacing > 5:
        count = 7
        spacing = _jdiv(high - (MAX_FRET - 4) - low, count)
    top = low + count * spacing
    return [top - spacing * (i + 1) for i in range(count)]


def _fix_ties(track, losses):
    """TGTrackManager.fixInvalidTiedNotes for voice 1: each measure's errors are listed, then fixed."""
    tuning = track['tuning']
    previous = None
    for m in track['measures']:
        voices = sorted((b for b in m['beats'] if not b['voice']['empty']), key=_start)
        bad = []
        for i, beat in enumerate(voices):
            before = voices[i - 1] if i else previous
            for note in beat['voice']['notes']:
                if note['tied'] and not (before and any(p['string'] == note['string'] and p['value'] == note['value']
                                                        for p in before['voice']['notes'])):
                    bad.append((note, beat, before))
        for note, beat, before in bad:
            pitch = tuning[note['string'] - 1] + note['value']
            match = None if before is None else next(
                (p for p in before['voice']['notes'] if tuning[p['string'] - 1] + p['value'] == pitch), None)

            def move(n, string, home):
                if any(o['string'] == string for o in home['voice']['notes']):
                    return False
                fret = tuning[n['string'] - 1] + n['value'] - tuning[string - 1]
                if 0 <= fret <= MAX_FRET:
                    n['string'], n['value'] = string, fret
                    return True
                return False
            if match is not None and (move(note, match['string'], beat) or
                                      (not match['tied'] and move(match, note['string'], before))):
                continue
            note['tied'] = False
            losses['ties removed'] += 1
        if voices:
            previous = voices[-1]


def _channel(channels, ch):
    return channels.setdefault(ch, dict(program=0, volume=127, balance=64, tracks=set()))


def score_import_options(options=None):
    """Validate the shared native MIDI import settings before publication."""
    if options is not None and not isinstance(options,dict):
        raise ValueError('MIDI score options must be an object')
    settings=dict(transpose=0,quantize=True,max_duration=16,max_division=1)
    if options:
        if set(options)-set(settings):
            raise ValueError('Unknown MIDI score import option')
        settings.update(options)
    transpose,quantize,max_duration,max_division=(settings[k] for k in settings)
    if type(transpose) is not int or not -24<=transpose<=24:
        raise ValueError('MIDI score: transpose must be an integer -24..24')
    if type(quantize) is not bool:
        raise ValueError('MIDI score: quantize must be boolean')
    if type(max_duration) is not int or max_duration not in (4,8,16,32,64) or type(max_division) is not int or max_division not in (1,3,5,6,7,9,10,11,12,13):
        raise ValueError('MIDI score: max_duration must be 4..64 and max_division 1 or a TuxGuitar tuplet 3..13')
    return settings


def midi_score_tree(data, *, transpose=0, quantize=True, max_duration=16, max_division=1):
    """TuxGuitar's MIDI import as a TuxGuitar 2.0 TGSong element plus specific loss notices (no file writes).

    The options are TuxGuitar's MidiSettings: transpose (semitones), quantize (splitPreciseDurationApproximately;
    off = TGDuration.fromTime), max_duration (the shortest value written, 4..64) and max_division (1 = no
    tuplets, 3 = triplets, ... 13).
    """
    score_import_options(dict(transpose=transpose,quantize=quantize,max_duration=max_duration,max_division=max_division))
    resolution, smf_tracks = _smf(data)
    losses = collections.Counter()
    headers, tracks, channels = [], [], {}       # channels: TempChannel per MIDI channel, in creation order
    name = ''

    def header_at(tick):
        tick = max(tick, QT)
        while True:
            for h in headers:
                if h['start'] <= tick < h['start'] + h['length']:
                    return h
            last = headers[-1] if headers else None
            meter = last['meter'] if last else (4, 4)
            headers.append(dict(start=last['start'] + last['length'] if last else QT, meter=meter,
                                length=meter[0] * (3840 // meter[1]), tempo=last['tempo'] if last else 120))

    def track_of(number):
        for t in tracks:
            if t['number'] == number:
                return t
        tracks.append(dict(number=number, name='', measures=[], low=-1, high=-1))
        return tracks[-1]

    def measure_at(track, tick):
        tick = max(tick, QT)
        header_at(tick)
        for h in headers:
            if not any(m['header'] is h for m in track['measures']):
                track['measures'].append(dict(header=h, beats=[]))
        return next(m for m in track['measures'] if m['header']['start'] <= tick < m['header']['start'] + m['header']['length'])

    for index, events in enumerate(smf_tracks):
        last, held, number = [QT], [], len(tracks) + 1

        def fill(end):
            """createTempNotesBefore."""
            done = end == last[0]
            while not done:
                measure = measure_at(track_of(number), last[0])
                h = measure['header']
                mend = h['start'] + h['length']
                coarse = min(end, mend) - last[0]
                durations = (_split_approximately(coarse * PER_TICK, h['length'] * PER_TICK, max_duration, max_division)
                             if quantize else [_from_time(coarse)])
                if durations:
                    relative = (last[0] - h['start']) * PER_TICK
                    if _jmod(relative, _precise(durations[0])) != 0 and _jmod(relative, _precise(durations[-1])) == 0:
                        durations.reverse()
                for d in durations:
                    if last[0] + _ticks(d) <= mend:
                        start = max(last[0], h['start'])
                        beat = next((b for b in measure['beats'] if b['start'] == start), None)
                        if beat is None:
                            beat = _beat(start=start)
                            measure['beats'].append(beat)
                        beat['voice'].update(duration=d, empty=False)
                        for temp in held:
                            beat['voice']['notes'].append(dict(value=temp['value'] + transpose, string=1,
                                                               velocity=64, tied=temp['tied']))
                            temp['tied'] = True
                        last[0] += _ticks(d)
                    else:
                        last[0] = mend
                if not durations and end > mend:
                    last[0] = mend
                done = end <= mend

        def handle(tick, kind, payload):
            nonlocal name
            parsed = QT * (tick + resolution) // resolution
            if kind == 'meta':
                meta, body = payload
                if meta == 0x03:
                    text = body.decode('utf-8', 'replace')
                    if index == 0:
                        name = text
                    else:
                        track_of(number)['name'] = text
                elif meta == 0x58 and len(body) >= 2:
                    numerator = body[0] - 256 if body[0] > 127 else body[0]
                    if numerator < 1:
                        raise ValueError(f'MIDI score: time signature numerator {numerator} at tick {tick}')
                    h = header_at(parsed)
                    h['meter'] = (numerator, {0: 1, 1: 2, 2: 4, 3: 8, 4: 16, 5: 32}.get(body[1], 4))
                    h['length'] = h['meter'][0] * (3840 // h['meter'][1])
                    losses['meter changes moved to their bar'] += parsed != h['start']
                elif meta == 0x51 and len(body) >= 3:
                    usq = int.from_bytes(body[:3], 'big')
                    h = header_at(parsed)
                    h['tempo'] = 2 ** 31 - 1 if usq == 0 else int(60000.0 / (usq / 1000.0))
                    losses['tempo changes moved to their bar'] += parsed != h['start']
                return
            status, *values = payload
            command, ch = status & 0xF0, status & 0x0F
            if command == 0x90 and values[1] > 0:
                if values[0] > 0:
                    fill(parsed)
                    _channel(channels, ch)['tracks'].add(number)
                    t, pitch = track_of(number), values[0] + transpose
                    t['low'] = pitch if t['low'] < 0 or pitch < t['low'] else t['low']
                    t['high'] = pitch if t['high'] < 0 or pitch > t['high'] else t['high']
                    if all(n['value'] != values[0] for n in held):
                        held.append(dict(channel=ch, value=values[0], tied=False))
                    losses['velocities'] += values[1] != 64
            elif command in (0x80, 0x90):
                temp = next((n for n in held if n['channel'] == ch and n['value'] == values[0]), None)
                if temp is not None:
                    fill(parsed)
                    held.remove(temp)
            elif command == 0xC0:
                _channel(channels, ch)['program'] = values[0]
            elif command == 0xB0:
                if values[0] in (7, 10):
                    spec=_channel(channels,ch)
                    key='volume' if values[0]==7 else 'balance'
                    losses['mixer changes folded into final track values'] += bool(spec['tracks']) and spec[key]!=values[1]
                    spec[key]=values[1]
                else:
                    losses['controllers'] += 1
            else:
                losses['pitch bends and aftertouch'] += 1

        def is_off(event):
            return event[1] == 'short' and (event[2][0] & 0xF0 == 0x80 or event[2][0] & 0xF0 == 0x90 and event[2][2] == 0)
        pending = []
        for event in events + [None]:
            if event is None or pending and event[0] > pending[-1][0]:
                for e in [e for e in pending if is_off(e)] + [e for e in pending if not is_off(e)]:
                    handle(*e)
                pending = []
            if event is not None:
                pending.append(event)
        losses['notes sounding at the end of their track'] += len(held)
    if not headers or not tracks:
        raise ValueError('MIDI score: Empty Song (no notes and no named tracks)')
    for i in range(1, len(headers)):
        if headers[i]['start'] != headers[i - 1]['start'] + headers[i - 1]['length']:
            raise ValueError(f'MIDI score: a later time signature changed the length of bar {i} after bar {i + 1} '
                             'existed; TuxGuitar would keep overlapping bars')
    # checkChannels: a TG channel per MIDI channel with tracks, MIDI channels with the same track set folded
    # into its GM channel 2 (the second) or dropped (the rest); percussion always routes 9/9.
    routes = []
    for ch, spec in channels.items():
        if not spec['tracks'] or any(ch in r[:2] for r in routes):
            continue
        route = [ch, ch]
        for other, aux in list(channels.items())[list(channels).index(ch) + 1:]:
            if aux['tracks'] == spec['tracks']:
                if route[1] == route[0]:
                    route[1] = other
                else:
                    aux['tracks'] = set()
        routes.append((9, 9, spec) if ch == 9 else (*route, spec))
    for t in tracks:
        while len(t['measures']) < len(headers):
            t['measures'].append(dict(header=headers[len(t['measures'])], beats=[]))
        t['channel'] = None                           # checkTracks: the last match wins
        for ch, spec in channels.items():
            if t['number'] in spec['tracks']:
                for route in routes:
                    if route[0] == ch:
                        t['channel'] = (ch, route[2])
        t['percussion'] = t['channel'] is not None and t['channel'][0] == 9
        t['tuning'] = [0] * 6 if t['percussion'] else _tuning(t['low'], t['high'])
        for m in t['measures']:
            m['start'], m['length'] = m['header']['start'], m['header']['length']
            _place(m)
            _complete(m, losses)
            code = _voice_errors(m)
            if code:
                _fix_voice(m, code, losses)
            for beat in m['beats']:
                if beat['voice']['notes']:
                    _finger(beat, t['tuning'], t['percussion'], losses)
        _fix_ties(t, losses)
    return _midi_xml(name, headers, tracks, losses)


def _midi_xml(name, headers, tracks, losses):
    import xml.etree.ElementTree as ET

    def add(parent, tag, text=None, **attrs):
        node = ET.SubElement(parent, tag, {k: str(v) for k, v in attrs.items()})
        if text is not None:
            node.text = str(text)
        return node
    song = ET.Element('TGSong')
    add(song, 'name', name)
    for key in ('artist', 'album', 'author', 'date', 'copyright', 'writer', 'transcriber', 'comments'):
        add(song, key, '')
    notices, users = [], collections.Counter(id(t['channel'][1]) for t in tracks if t['channel'])
    for ti, t in enumerate(tracks, 1):
        spec = t['channel'][1] if t['channel'] else dict(program=0, volume=127, balance=64)
        c = add(song, 'TGChannel')
        add(c, 'id', ti)
        add(c, 'bank', 128 if t['percussion'] else 0)
        add(c, 'program', spec['program'])
        for key, value in (('volume', spec['volume']), ('balance', spec['balance']), ('chorus', 0), ('reverb', 0), ('phaser', 0), ('tremolo', 0)):
            add(c, key, value)
        add(c, 'name', f'#{ti}')
        if t['percussion']:
            for key in ('gm-channel-1', 'gm-channel-2'):
                add(c, 'TGChannelParameter', key=key, value=9)
        if (spec['volume'], spec['balance']) != (127, 64):
            notices.append(f'track {ti}: final MIDI channel volume {spec["volume"]} and pan {spec["balance"]} '
                           'apply to the whole track, as TuxGuitar imports them; controller automation is not retained.')
        if t['channel'] is None:
            notices.append(f'track {ti}: no notes, so TuxGuitar gives it no channel and an unusable tuning; '
                           'program 0 and standard tuning here.')
            t['tuning'] = list(PRIORITY_TUNINGS[0])
        elif users[id(spec)] > 1:
            notices.append(f'track {ti}: shares MIDI channel {t["channel"][0] + 1} with another track; each native '
                           'track keeps its own copy of the program.')
    for h in headers:
        header = add(song, 'TGMeasureHeader')
        add(header, 'timeSignature', numerator=h['meter'][0], denominator=h['meter'][1])
        add(header, 'tempo', h['tempo'])
    for ti, t in enumerate(tracks, 1):
        track = add(song, 'TGTrack', **({} if t['percussion'] else {'maxFret': MAX_FRET}))
        add(track, 'name', t['name'])
        add(track, 'channelId', ti)
        add(track, 'color', R=255, G=0, B=0)
        for pitch in t['tuning']:
            add(track, 'TGString', pitch)
        add(track, 'TGLyric', **{'from': 1})
        for mi, m in enumerate(t['measures']):
            measure = add(track, 'TGMeasure')
            if mi == 0:
                add(measure, 'clef', 'treble')
                add(measure, 'keySignature', 0)
            for beat in sorted(m['beats'], key=lambda b: b['precise']):
                node = add(measure, 'TGBeat')
                add(node, 'preciseStart', beat['precise'])
                voice = add(node, 'voice')
                value, dotted, double, enters, times = beat['voice']['duration']
                d = add(voice, 'duration', value=value)
                if dotted or double:
                    d.set('dotted', 'dotted' if dotted else 'doubleDotted')
                add(d, 'divisionType', enters=enters, times=times)
                if beat['voice']['empty']:
                    voice.set('empty', 'true')
                elif not beat['voice']['notes']:
                    voice.set('empty', 'false')
                for n in beat['voice']['notes']:
                    note = add(voice, 'note', string=n['string'], value=n['value'], velocity=n['velocity'])
                    if n['tied']:
                        note.set('tiedNote', 'true')
                add(add(node, 'voice', empty='true'), 'duration', value=4)
    labels = {'mixer changes folded into final track values': 'volume/pan changes folded into final whole-track values, as TuxGuitar imports them',
              'velocities': 'note velocities replaced by 64, as TuxGuitar imports every note',
              'controllers': 'controller changes other than volume (7) and pan (10) ignored',
              'pitch bends and aftertouch': 'pitch bend and aftertouch messages ignored',
              'notes sounding at the end of their track': 'notes still sounding at the end of their track dropped',
              'unfingered notes': 'notes with no free string within fret 29 dropped',
              'ties removed': 'ties TuxGuitar could not keep on one string removed',
              'removed beats': "beats removed by TuxGuitar's voice repair (past the bar or not representable)",
              'unfilled gaps': 'gaps without an exact rest split left open',
              'meter changes moved to their bar': 'time signatures off a bar line applied to their whole bar',
              'tempo changes moved to their bar': 'tempo changes off a bar line applied to their whole bar'}
    notices += [f'MIDI: {count} {labels[key]}.' for key, count in losses.items() if count]
    return song, notices


def read_midi_score(data, **options):
    """A native score from MIDI bytes as TuxGuitar 2.1.0 imports them (options: see midi_score_tree)."""
    from .tgimport import read_tree
    song, notices = midi_score_tree(data, **options)
    return read_tree(song, notices)


def import_midi_score(src, song_path, samples_dir, **options):
    """Publish a MIDI file as a native score with the shared placeholder publisher (beside import_midi)."""
    from .gpimport import publish_native_score
    song, warnings = read_midi_score(Path(src).read_bytes(), **options)
    warnings = [w.replace('TG notation imported', 'MIDI notation imported', 1) for w in warnings]
    return publish_native_score(song, src, song_path, samples_dir, warnings)
