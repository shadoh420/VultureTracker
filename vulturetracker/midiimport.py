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
  channel of their own; velocity to the volume column; a channel's volume (CC 7) and pan (CC 10) before its first note
  to the channel's own.

Left out (counted in the warnings): pitch bends, later volume, pan and other controller changes, the sustain pedal,
notes outside C-0..B-9; past 64 channels, the least used."""
from pathlib import Path

from .gpimport import GM_DRUMS, Lane, Placeholders, grid_for, note_name, speed_tempo, write_song


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

    tempos, sigs, notes, names, setup = [], [], [], [], {}
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
                names[ti] = msg.name.strip()
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
            elif msg.type == "control_change":
                skip("sustain pedal changes" if msg.control == 64 else "controller changes")
            elif msg.type == "pitchwheel":
                skip("pitch bends")
        for (ch, key), left in held.items():  # held to the end of the track
            notes += [(ti, ch, key, a, t, vel, prog) for a, vel, prog in left]
    if not notes:
        raise ValueError("the file has no notes")

    end = max(n[4] for n in notes)
    sigs.sort()
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
    if any((x * r) % q for x in times) or r > 12:
        r = 4  # played in (or 1/32 triplets): sixteenths, each note delayed to its tick (24 a quarter at speed 6)
        warnings.append("timing finer than 12 rows a quarter: 4 rows a quarter, notes delayed (SDx) to the nearest tick")
    tempos.sort()
    bpm = 60e6 / tempos[0][1] if tempos and tempos[0][0] == 0 else 120.0
    speed, tempo, exact = speed_tempo(bpm, r)
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
            tempo_lane.put(row(tick), fx=f"T{max(32, min(255, round(want))):02X}")
            if not 32 <= want <= 255:
                warnings.append(f"tempo {60e6 / us:g} BPM is past IT's 32-255 at speed {speed}: clamped")
        now = want

    ph = Placeholders(samples_dir, song_path)
    lanes, total = {}, row(lines[-1])
    for ti, ch, key, a, b, vel, prog in sorted(notes, key=lambda n: (n[3], n[0], n[1], n[2])):
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
            ln = lanes.setdefault((ti, ch, 1, key), Lane(f"{base} {GM_DRUMS.get(key, note_name(key))}"))
        else:
            voices = [v for (t2, c2, d2, _), v in lanes.items() if (t2, c2, d2) == (ti, ch, 0)]
            ln = next((v for v in voices if v.free <= start), None)
            if ln is None:
                ln = lanes[ti, ch, 0, len(voices)] = Lane(f"{base} {ch + 1}.{len(voices) + 1}")
                ln.ends = []
            ln.free = max(start + 1, row(b))
            ln.ends.append(ln.free)
        ln.put(start, note_name(key), ins, f"v{max(1, min(64, round(vel * 64 / 127))):02d}", f"SD{delay:X}" if delay else None, force=True)
        for control, attr in ((7, "volume"), (10, "pan")):
            if (ti, ch, control) in setup:
                setattr(ln, attr, min(64, round(setup[ti, ch, control] / 2) if control == 10 else round(setup[ti, ch, control] * 64 / 127)))
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
    title = names[0] if mid.type == 1 and names[0] else Path(src).stem
    head = (f"# Imported from {Path(src).name} by vulturetracker import (MIDI: placeholder sounds, swap them in the tryout)\n"
            f"# {bpm:g} BPM, {r} rows a quarter note: speed {speed}, tempo {tempo}\n")
    song = write_song(song_path, title, lanes, bars, ph, r, speed, tempo, sigs[0][1:], warnings, head)
    return song, warnings
