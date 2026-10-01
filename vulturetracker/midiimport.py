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
import math
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
    try:
        mid = mido.MidiFile(str(src))
    except Exception as e:  # noqa: BLE001 - mido raises what its reader hits (OSError, EOFError, KeyError, ...)
        raise ValueError(f"{src}: not a readable MIDI file ({type(e).__name__}: {e})") from e
    if mid.type == 2:
        raise ValueError(f"{src}: a type 2 MIDI file (independent sequences) is not supported")
    q = mid.ticks_per_beat
    warnings, skipped = [], {}

    def skip(what):
        skipped[what] = skipped.get(what, 0) + 1

    tempos, sigs, notes, names, setup, marks, ctl = [], [], [], [], {}, [], []
    for ti, track in enumerate(mid.tracks):
        t, held, program, started = 0, {}, {}, set()
        names.append("")
        for msg in track:
            t += msg.time
            if msg.type == "set_tempo":
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
    while lines[-1] < end or len(lines) < 2:
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
    head = (f"# Imported from {Path(src).name} by vulturetracker import (MIDI: placeholder sounds, swap them in the tryout)\n"
            f"# {bpm:g} BPM, {r} rows a quarter note: speed {speed}, tempo {tempo}\n")
    song = write_song(song_path, title, lanes, bars, ph, r, speed, tempo, [s[1:] for s in sigs if not s[0]][-1], warnings, head,
                      sections)
    return song, warnings
