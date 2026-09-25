"""Guitar Pro import (GP3, GP4, GP5; TuxGuitar's idea): a tab read by PyGuitarPro (LGPL-3, installed separately:
`pip install pyguitarpro`) turned into a song file with placeholder samples, so the tab plays at once and every track's
sound can be swapped in the tryout.

- Tracks to channels: a pitched track gets a channel per string it uses (a new note on a string cuts the one before, as
  on a guitar), a drum track a channel per note of its fullest beat; a tempo change gets a channel of its own (Txx).
- Beats to rows: the coarsest grid that holds every beat of the tab (4 rows a quarter for sixteenths, 12 when there
  are triplets, up to 48), with speed and tempo chosen so a row lasts what it lasts in the tab.
- Measures to patterns, the repeats and alternate endings played out into the order list; identical measures share a
  pattern.
- A note sounds for its beat's length (a note-off, ===, where it ends) unless it lets ring or is tied on; palm mutes
  and staccato are shortened, dead notes cut after a tick (SC1), ghost notes quieter; velocity to the volume column.
- Bends (and the whammy bar) to pitch slides row by row (Exx down, Fxx up: xx/16 semitone per tick) following the
  bend's points; slides between notes to Exx/Fxx over the first note's length, the second not struck again when the
  slide is legato (G with the note), slides into and out of a note likewise; hammer-ons and pull-offs to a legato
  next note (GFF); vibrato to H; natural harmonics to their pitch.
- Samples: a plucked-string multisample (a sample every octave, 9 kHz wide, each played at most two semitones under and
  nine over its root: the anti-aliasing rule) for pitched tracks, basses a darker one, and a small synthesised drum kit
  mapped on the General MIDI drum keys: placeholders, made to be replaced.

Left out (counted in the warnings): grace notes, trills, tremolo picking, mix-table volume and pan changes, the
triplet feel, lyrics."""
import math
from fractions import Fraction
from pathlib import Path

import numpy as np

from .dsp import lowpass

QUARTER = 960
GRIDS = (1, 2, 3, 4, 6, 8, 12, 16, 24, 32, 48)
E_ = "... .. ... ..."
NOTE_NAMES = ["C-", "C#", "D-", "D#", "E-", "F-", "F#", "G-", "G#", "A-", "A#", "B-"]
HARMONIC = {12: 12, 7: 19, 19: 19, 5: 24, 24: 24, 4: 28, 9: 28, 16: 28, 3: 31}  # natural harmonics: fret -> above open
GM_DRUMS = {  # General MIDI drum key -> kit piece
    35: "kick", 36: "kick", 37: "snare", 38: "snare", 39: "snare", 40: "snare", 41: "tom_low", 43: "tom_low",
    45: "tom_mid", 47: "tom_mid", 48: "tom_high", 50: "tom_high", 42: "hat", 44: "hat", 46: "hat_open",
    49: "crash", 52: "crash", 55: "crash", 57: "crash", 51: "ride", 53: "ride", 59: "ride",
}
KIT = ["kick", "snare", "hat", "hat_open", "crash", "ride", "tom_low", "tom_mid", "tom_high"]


def note_name(n):
    return f"{NOTE_NAMES[n % 12]}{n // 12}"


def _hex(v):
    return f"{max(0, min(255, int(v))):02X}"


# ---------------------------------------------------------------- timing

def grid_for(times):
    """Rows per quarter note: the smallest of GRIDS on which every tick position in `times` falls (48 when none does)."""
    for r in GRIDS:
        if all((t * r) % QUARTER == 0 for t in times):
            return r
    return GRIDS[-1]


def speed_tempo(bpm, rows_per_quarter):
    """(speed, tempo) making a row last 60 / (bpm x rows) s: a row is speed ticks of 2.5 / tempo s, so tempo = bpm x
    rows x speed / 24. Prefers the speed that gives 24 ticks a quarter (tempo = bpm), then the most ticks a row (finer
    slides) with the tempo in IT's 32-255, then the closest. Returns (speed, tempo, the tempo it should be)."""
    best = None
    for s in range(1, 32):
        exact = bpm * rows_per_quarter * s / 24
        t = max(32, min(255, round(exact)))
        err = abs(t - exact) / exact
        key = (err > 0.005, s * rows_per_quarter != 24, -s if 32 <= exact <= 255 else 0, err)
        if best is None or key < best[0]:
            best = (key, s, t, exact)
    return best[1], best[2], best[3]


# ---------------------------------------------------------------- repeats

def play_order(headers):
    """Measure indices in the order they play: repeats (open / close with a count) and alternate endings (a bitmask of
    the passes an ending is played on) played out."""
    out, i, start, passes, n = [], 0, 0, {}, len(headers)
    guard = 0
    while i < n and guard < 10000:
        guard += 1
        h = headers[i]
        if h.isRepeatOpen:
            if i != start:
                passes = {}
            start = i
        p = passes.get(start, 1)
        alt = getattr(h, "repeatAlternative", 0) or 0
        if alt and not (alt >> (p - 1)) & 1:
            # an ending for another pass: skip it (and the measures up to the next ending or repeat mark)
            i += 1
            continue
        out.append(i)
        if h.repeatClose is not None and h.repeatClose > 0 and p <= h.repeatClose:
            passes[start] = p + 1
            i = start
            continue
        i += 1
    return out


# ---------------------------------------------------------------- placeholder samples

def pluck(freq, seconds=2.0, rate=44100, damping=0.996, bright=0.5, seed=0):
    """A Karplus-Strong plucked string (numpy, block by block of one period): a noise burst low-passed by `bright`,
    averaged round a delay line of one period; returns float mono."""
    n = int(seconds * rate)
    period = max(2, int(round(rate / freq)))
    rng = np.random.default_rng(seed)
    burst = rng.uniform(-1, 1, period)
    for _ in range(int((1 - bright) * 6)):
        burst = 0.5 * (burst + np.roll(burst, 1))
    y = np.zeros(n + period + 1)
    y[:period] = burst - burst.mean()
    for k in range(period, n + period, period):
        prev = y[k - period: k + 1]
        seg = damping * 0.5 * (prev[:-1] + prev[1:])
        y[k: k + period] = seg[: len(y[k: k + period])]
    y = y[:n] * np.minimum(1, (n - np.arange(n)) / (0.02 * rate))
    return y / (np.abs(y).max() or 1) * 0.8


def drum(kind, rate=44100, seed=0):
    """A synthesised kit piece (float mono)."""
    rng = np.random.default_rng(seed + KIT.index(kind))
    def env(n, tau):
        return np.exp(-np.arange(n) / (tau * rate))
    if kind == "kick":
        n = int(0.4 * rate)
        t = np.arange(n) / rate
        x = np.sin(2 * np.pi * np.cumsum(45 + 110 * np.exp(-t * 35)) / rate) * env(n, 0.12)
    elif kind.startswith("tom"):
        f = {"tom_low": 90, "tom_mid": 130, "tom_high": 180}[kind]
        n = int(0.35 * rate)
        t = np.arange(n) / rate
        x = np.sin(2 * np.pi * np.cumsum(f + f * 0.6 * np.exp(-t * 25)) / rate) * env(n, 0.1)
    elif kind == "snare":
        n = int(0.25 * rate)
        t = np.arange(n) / rate
        x = 0.6 * rng.standard_normal(n) * env(n, 0.05) + 0.5 * np.sin(2 * np.pi * 190 * t) * env(n, 0.03)
    else:  # hats and cymbals: high-passed noise (a first difference), longer for the open ones
        tau, secs = {"hat": (0.025, 0.12), "hat_open": (0.15, 0.5), "crash": (0.6, 2.0), "ride": (0.4, 1.5)}[kind]
        n = int(secs * rate)
        x = np.diff(rng.standard_normal(n + 1)) * env(n, tau) * 0.5
    return x / (np.abs(x).max() or 1) * 0.8


def _write(path, x, rate=44100, root=None):
    from .wavload import write_wav
    write_wav(path, rate, [np.clip(np.round(x * 32767), -32768, 32767).astype(int).tolist()], root_note=root)


# ---------------------------------------------------------------- notes to cells

class Lane:
    """One channel's cells over the whole played-out tab (absolute rows): note, instrument, volume, effect texts."""

    def __init__(self, name):
        self.name = name
        self.cells = {}

    def put(self, row, note=None, ins=None, vol=None, fx=None, force=False):
        c = self.cells.setdefault(row, ["...", "..", "...", "..."])
        if note is not None and (force or c[0] in ("...", "===")):
            c[0], c[1] = note, (f"{ins:02d}" if ins else "..")
            c[2] = vol or "..."
        if fx is not None and (force or c[3] == "..."):
            c[3] = fx

    def off(self, row):
        c = self.cells.get(row)
        if c is None or c[0] == "...":
            self.put(row, "===")


def _slide_fx(semis, ticks):
    """The effect that moves the pitch `semis` semitones over a row of `ticks` sliding ticks (E down, F up; xx/16
    semitone per tick, at most DF), and the semitones it really moves."""
    if ticks < 1 or abs(semis) < 1 / 32:
        return None, 0.0
    xx = min(0xDF, round(abs(semis) * 16 / ticks))
    if xx == 0:
        return None, 0.0
    return f"{'F' if semis > 0 else 'E'}{xx:02X}", math.copysign(xx * ticks / 16, semis)


def _glide(lane, row0, rows, pitch_at, ticks):
    """Pitch slides over rows row0..row0+rows-1 following `pitch_at(fraction of the span) -> semitones`, each row
    correcting what the rows before left over (the slide's rounding)."""
    done = 0.0
    for k in range(rows):
        target = pitch_at((k + 1) / rows)
        fx, moved = _slide_fx(target - done, ticks)
        if fx:
            lane.put(row0 + k, fx=fx)
            done += moved


def _lane_cells(ln, events, speed, rows_per_quarter, skip):
    """Every note event of one lane (sorted by row) written as cells: the note (a legato one with GFF), its bend, vibrato
    and slides as effects, then a note-off where it ends unless it rings on."""
    ticks = speed - 1
    for i, ev in enumerate(events):
        if ev["tie"]:
            continue
        note, eff, row, dur, pitch = ev["note"], ev["note"].effect, ev["row"], ev["dur"], ev["pitch"]
        prev = next((events[j] for j in range(i - 1, -1, -1) if not events[j]["tie"]), None)
        legato = (prev is not None and prev["end"] >= row and not ev["drum"]
                  and (prev["note"].effect.hammer or any(x.name == "legatoSlideTo" for x in prev["note"].effect.slides)))
        into = next((x.name for x in eff.slides if x.name in ("intoFromBelow", "intoFromAbove")), None)
        start = pitch + (-3 if into == "intoFromBelow" else 3 if into else 0)
        bend = eff.bend if eff.isBend else ev["bar"]
        pts = sorted((q.position / 12, q.value / 2) for q in bend.points) if bend is not None and bend.points else None
        if pts and pts[0][1]:  # a pre-bend: the note starts bent
            start = min(119, pitch + round(pts[0][1]))
            pts = [(x, y - round(pts[0][1])) for x, y in pts]
        text = note_name(start)
        if note.type.name == "dead":
            ln.put(row, text, ev["ins"], "v16", "SC1", force=True)
        else:
            ln.put(row, text, ev["ins"], ev["vol"], "GFF" if legato else None, force=True)
        if into:
            _glide(ln, row, min(dur, max(1, rows_per_quarter // 4)), lambda f, d=pitch - start: d * f, ticks)
        nxt = next((e for e in events[i + 1:] if not e["tie"]), None)
        to_next = any(x.name in ("shiftSlideTo", "legatoSlideTo") for x in eff.slides)
        if pts:
            if to_next:
                skip("slides on a bent note")
            _glide(ln, row, dur, lambda f, xs=[p[0] for p in pts], ys=[p[1] for p in pts]: float(np.interp(f, xs, ys)), ticks)
        elif to_next and nxt is not None:
            _glide(ln, row, max(1, nxt["row"] - row), lambda f, d=nxt["pitch"] - pitch: d * f, ticks)
        elif eff.vibrato or ev["vibrato"]:
            for k in range(dur):
                ln.put(row + k, fx="H44" if k == 0 else "H00")
        out = next((x.name for x in eff.slides if x.name in ("outDownwards", "outUpwards")), None)
        if out:
            n2 = max(1, dur // 2)
            _glide(ln, row + dur - n2, n2, lambda f, d=(-5 if out == "outDownwards" else 5): d * f, ticks)
    for ev in events:  # note-offs: where a note ends and no other note starts on its lane
        if not ev["tie"] and not ev["ring"] and ev["end"] < ev["total"]:
            ln.off(ev["end"])


def import_gp(src, song_path, samples_dir):
    """A Guitar Pro file (.gp3, .gp4, .gp5) as a song YAML plus placeholder WAVs in `samples_dir`. Returns (song dict,
    warnings)."""
    import os
    try:
        import guitarpro
    except ImportError:
        raise ValueError("Guitar Pro import needs PyGuitarPro: pip install pyguitarpro (LGPL-3)")
    from .api import to_yaml
    gp = guitarpro.parse(str(src))
    warnings, skipped = [], {}

    def skip(what):
        skipped[what] = skipped.get(what, 0) + 1

    headers = gp.measureHeaders
    tracks = [t for t in gp.tracks if t.measures]
    times = set()  # every beat start and length, in ticks from its measure's start
    for t in tracks:
        for m in t.measures:
            for v in m.voices:
                for b in v.beats:
                    times.add(b.start - m.start)
                    times.add(b.duration.time)
    r = grid_for(times)
    if any((x * r) % QUARTER for x in times):
        warnings.append(f"some beats fall between rows at {r} rows a quarter: rounded to the nearest row")
    tick = QUARTER / r
    speed, tempo, exact = speed_tempo(gp.tempo, r)
    if abs(tempo - exact) / exact > 0.005:
        warnings.append(f"{gp.tempo} BPM at {r} rows a quarter needs tempo {exact:.1f}: {tempo} is used")
    order = play_order(headers)
    if len(order) > 255:
        warnings.append(f"the repeats play out to {len(order)} measures; IT's order list holds 255: cut there")
        order = order[:255]
    mrows = [round(headers[i].length / tick) for i in order]
    starts = [0]
    for n in mrows:
        starts.append(starts[-1] + n)
    total = starts[-1]

    sdir = Path(samples_dir)
    sdir.mkdir(parents=True, exist_ok=True)
    rel = os.path.relpath(sdir.resolve(), Path(song_path).resolve().parent).replace(os.sep, "/")
    samples, instruments, made = {}, {}, {}

    def add_sample(name, x, root=None):
        num = len(samples) + 1
        f = sdir / f"{name}.wav"
        _write(f, x, root=root)
        samples[num] = {"file": f"{rel}/{f.name}", "name": name[:25], **({"base_note": note_name(root)} if root is not None else {})}
        return num

    def instrument(kind):
        """A pitched multisample (a pluck every octave, roots C-2..C-8, 9 kHz wide, each over the keys 2 under to 9 over its
        root: the anti-aliasing rule) or the drum kit on the General MIDI keys."""
        if kind in made:
            return made[kind]
        if kind == "drums":
            nums = {k: add_sample(f"kit_{k}", drum(k)) for k in KIT}
            keymap = [{"notes": "C-0..B-9", "sample": nums["snare"], "play_note": "C-5"}]  # a key the kit lacks: snare
            keymap += [{"notes": note_name(key), "sample": nums[piece], "play_note": "C-5"} for key, piece in sorted(GM_DRUMS.items())]
            entry = {"name": "drums (placeholder)", "keymap": keymap}
        else:
            keymap = []
            for oc in range(2, 9):
                root = 12 * oc
                x = pluck(440 * 2 ** ((root - 69) / 12), 2.5 if kind == "bass" else 2.0,
                          damping=0.998 if kind == "bass" else 0.996, bright=0.2 if kind == "bass" else 0.6, seed=oc)
                x = lowpass(x[None], 44100, 9000)[0]  # 9 kHz wide: nine semitones up stays under 18 kHz
                n = add_sample(f"{kind}_{note_name(root).replace('-', '').lower()}", x, root)
                lo, hi = (0 if oc == 2 else root - 2), (119 if oc == 8 else root + 9)
                keymap.append({"notes": f"{note_name(lo)}..{note_name(hi)}", "sample": n})
            entry = {"name": f"{kind} (placeholder)", "keymap": keymap, "fadeout": 64}
        num = len(instruments) + 1
        instruments[num] = entry
        made[kind] = num
        return num

    lanes, tempo_lane = [], Lane("Tempo")
    for track in tracks:
        drums = track.isPercussionTrack
        program = track.channel.instrument
        ins = instrument("drums" if drums else "bass" if 32 <= program <= 39 else "guitar")
        by_lane = {}
        for pos, mi in enumerate(order):
            m = track.measures[mi]
            for vi, voice in enumerate(m.voices):
                for b in voice.beats:
                    row = starts[pos] + round((b.start - m.start) / tick)
                    length = max(1, round(b.duration.time / tick))
                    mix = b.effect.mixTableChange
                    if mix is not None and mix.tempo is not None and mix.tempo.value > 0:
                        want = mix.tempo.value * r * speed / 24
                        tempo_lane.put(row, fx=f"T{_hex(max(32, min(255, round(want))))}")
                        if not 32 <= want <= 255:
                            warnings.append(f"tempo {mix.tempo.value} BPM is past IT's 32-255 at speed {speed}: clamped")
                    if mix is not None and (mix.volume is not None or mix.balance is not None):
                        skip("mix-table volume and pan changes")
                    for k, note in enumerate(sorted(b.notes, key=lambda n: n.string)):
                        if note.type.name == "rest":
                            continue
                        eff = note.effect
                        key = (0, vi * 16 + k) if drums else (1, note.string)
                        if drums:
                            pitch = note.value
                        else:
                            pitch = note.realValue
                            if eff.harmonic is not None:
                                pitch = (track.strings[note.string - 1].value + HARMONIC[note.value]
                                         if eff.harmonic.type == 1 and note.value in HARMONIC else pitch + 12)
                        for flag, what in ((eff.isGrace, "grace notes"), (eff.isTrill, "trills"),
                                           (eff.isTremoloPicking, "tremolo picking")):
                            if flag:
                                skip(what)
                        if note.type.name == "tie":
                            evs = by_lane.get(key)
                            last = next((e for e in reversed(evs or []) if not e["tie"]), None)
                            if last is not None:
                                last["end"] = max(last["end"], row + length)
                            by_lane.setdefault(key, []).append({"row": row, "tie": True})
                            continue
                        if not 0 <= pitch < 120:
                            skip("notes outside C-0..B-9")
                            continue
                        dur = max(1, length // 2) if eff.palmMute or eff.staccato else length
                        vel = note.velocity * (0.6 if eff.ghostNote else 1.0)
                        by_lane.setdefault(key, []).append({
                            "row": row, "dur": dur, "end": row + dur, "pitch": pitch, "note": note, "tie": False,
                            "ins": ins, "vol": f"v{max(1, min(64, round(vel * 64 / 127))):02d}", "drum": drums,
                            "bar": b.effect.tremoloBar, "vibrato": b.effect.vibrato, "total": total,
                            "ring": drums or eff.letRing or track.settings.autoLetRing})
        for key in sorted(by_lane):
            evs = sorted(by_lane[key], key=lambda e: e["row"])
            label = f"drum {key[1] + 1}" if drums else f"str {key[1]}"
            ln = Lane(f"{track.name.strip()[:13]} {label}")
            ln.volume = round(track.channel.volume * 64 / 127)
            ln.pan = round(track.channel.balance * 64 / 127)
            _lane_cells(ln, evs, speed, r, skip)
            lanes.append(ln)
    if tempo_lane.cells:
        lanes.append(tempo_lane)
    if not lanes:
        raise ValueError("the tab has no notes")
    if len(lanes) > 64:
        warnings.append(f"{len(lanes)} channels: IT has 64, the rest are left out")
        lanes = lanes[:64]
    patterns, orders, seen = {}, [], {}
    for pos, mi in enumerate(order):
        a, n = starts[pos], mrows[pos]
        if n > 200:
            warnings.append(f"measure {mi + 1} is {n} rows at {r} rows a quarter: IT holds 200, cut there")
            n = 200
        data = "".join(f"{i:02d}: " + " | ".join(" ".join(ln.cells.get(a + i, ["...", "..", "...", "..."])) for ln in lanes) + "\n"
                       for i in range(n))
        name = seen.get(data)
        if name is None:
            name = f"m{mi + 1}" if f"m{mi + 1}" not in patterns else f"m{mi + 1}_{pos}"
            patterns[name] = {"rows": n, "data": data}
            seen[data] = name
        orders.append(name)
    for what, count in skipped.items():
        warnings.append(f"{count} {what} left out")
    chans = []
    for ln in lanes:
        c = {"name": ln.name[:20]}
        if getattr(ln, "volume", 64) != 64:
            c["volume"] = ln.volume
        if getattr(ln, "pan", 32) != 32:
            c["pan"] = ln.pan
        chans.append(c)
    song = {
        "module": {"title": (gp.title or Path(src).stem)[:25], "tempo": tempo, "speed": speed, "global_volume": 128,
                   "mix_volume": 48, "sample_rate": 44100, "channels": chans},
        "samples": samples, "instruments": instruments, "patterns": patterns, "orders": orders,
    }
    head = (f"# Imported from {Path(src).name} by vulturetracker import (Guitar Pro: placeholder sounds, swap them in the tryout)\n"
            f"# {gp.tempo} BPM, {r} rows a quarter note: speed {speed}, tempo {tempo}\n")
    for w in warnings:
        head += f"# import warning: {w}\n"
    Path(song_path).write_bytes((head + to_yaml(song)).encode("utf-8"))
    return song, warnings
