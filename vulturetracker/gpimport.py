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
import io
import codecs
import copy
import math
import os
from fractions import Fraction
from pathlib import Path
import tempfile

import numpy as np

from .dsp import bandlimit
from .resample import resample
from .song import it_text

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

def grid_for(times, quarter=QUARTER):
    """Rows per quarter note: the smallest of GRIDS on which every tick position in `times` (`quarter` ticks a quarter
    note) falls (48 when none does)."""
    for r in GRIDS:
        if all((t * r) % quarter == 0 for t in times):
            return r
    return GRIDS[-1]


def speed_tempo(bpm, rows_per_quarter, top=31):
    """(speed, tempo) making a row last 60 / (bpm x rows) s: a row is speed ticks of 2.5 / tempo s, so tempo = bpm x
    rows x speed / 24. Prefers the speed that gives 24 ticks a quarter (tempo = bpm), then the most ticks a row (finer
    slides, up to `top`) with the tempo in IT's 32-255, then the closest. Returns (speed, tempo, the tempo it should be)."""
    best = None
    for s in range(1, top + 1):
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
    """A Karplus-Strong plucked string (numpy, block by block of one period): a noise burst low-passed at (2 + 30 x
    `bright`) times `freq` (first order, so the attack is a pluck rather than a hiss), averaged round a delay line of one period; returns float mono."""
    n = int(seconds * rate)
    period = max(2, int(round(rate / freq - 0.5)))  # the average adds half a sample: the loop is period + 0.5
    rng = np.random.default_rng(seed)
    burst = rng.uniform(-1, 1, period)
    spec = np.fft.rfft(burst)  # one period: bin h is the h-th harmonic
    burst = np.fft.irfft(spec / np.sqrt(1 + (np.arange(len(spec)) / (2 + 30 * bright)) ** 2), period)
    y = np.zeros(n + period + 2)  # y[0] a zero before the burst: y[i] = damping * (y[i - period] + y[i - period - 1]) / 2
    y[1: period + 1] = burst - burst.mean()
    for k in range(period + 1, n + period + 1, period):
        prev = y[k - period - 1: k]
        seg = damping * 0.5 * (prev[:-1] + prev[1:])
        y[k: k + period] = seg[: len(y[k: k + period])]
    y = resample(y[1: n + 1], freq * (period + 0.5), rate)[:n]  # from the whole-sample pitch to `freq`
    n = len(y)
    y = y * np.minimum(1, (n - np.arange(n)) / (0.02 * rate))
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


class Placeholders:
    """An import's placeholder sounds, written as WAVs into `samples_dir`, and their sample and instrument entries."""

    def __init__(self, samples_dir, song_path):
        self.dir = Path(samples_dir)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.rel = os.path.relpath(self.dir.resolve(), Path(song_path).resolve().parent).replace(os.sep, "/")
        self.samples, self.instruments, self.made = {}, {}, {}

    def add_sample(self, name, x, root=None):
        num = len(self.samples) + 1
        f = self.dir / f"{name}.wav"
        _write(f, x, root=root)
        self.samples[num] = {"file": f"{self.rel}/{f.name}", "name": name[:25], **({"base_note": note_name(root)} if root is not None else {})}
        return num

    def instrument(self, kind):
        """The instrument number of `kind`, made the first time: "drums" the kit on the General MIDI keys, any other a
        pitched multisample (a pluck every octave, roots C-2..C-8, 9 kHz wide, each over the keys 2 under to 9 over its
        root: the anti-aliasing rule), "bass" a darker, longer one."""
        if kind in self.made:
            return self.made[kind]
        if kind == "drums":
            nums = {k: self.add_sample(f"kit_{k}", drum(k)) for k in KIT}
            keymap = [{"notes": "C-0..B-9", "sample": nums["snare"], "play_note": "C-5"}]  # a key the kit lacks: snare
            keymap += [{"notes": note_name(key), "sample": nums[piece], "play_note": "C-5"} for key, piece in sorted(GM_DRUMS.items())]
            entry = {"name": "drums (placeholder)", "keymap": keymap}
        else:
            keymap = []
            for oc in range(2, 9):
                root = 12 * oc
                x = pluck(440 * 2 ** ((root - 69) / 12), 2.5 if kind == "bass" else 2.0,
                          damping=0.998 if kind == "bass" else 0.996, bright=0.2 if kind == "bass" else 0.6, seed=oc)
                x = bandlimit(x[None], 44100, 9000)[0]  # 9 kHz wide: nine semitones up stays under 18 kHz
                n = self.add_sample(f"{kind}_{note_name(root).replace('-', '').lower()}", x, root)
                lo, hi = (0 if oc == 2 else root - 2), (119 if oc == 8 else root + 9)
                keymap.append({"notes": f"{note_name(lo)}..{note_name(hi)}", "sample": n})
            entry = {"name": f"{kind} (placeholder)", "keymap": keymap, "fadeout": 64}
        num = len(self.instruments) + 1
        self.instruments[num] = entry
        self.made[kind] = num
        return num


def write_song(song_path, title, lanes, bars, ph, r, speed, tempo, ts, warnings, head, sections=None):
    """Write an import's song file and return it: `lanes` (cells on absolute rows; 64 at most are kept) cut into a
    pattern per bar (`bars`: (name, first row, rows) in play order; identical bars share a pattern), the placeholders
    `ph`, `r` rows a quarter note played at `speed` and `tempo`, a beat and a bar from the time signature `ts` =
    (numerator, denominator); `head`: the comment lines on top, the warnings after them; `sections`: named spans of
    the bars ({name: [first, end]})."""
    from .api import to_yaml
    if len(lanes) > 64:
        warnings.append(f"{len(lanes)} channels: IT has 64, the rest are left out")
        lanes = lanes[:64]
    patterns, orders, seen = {}, [], {}
    for pos, (name, a, n) in enumerate(bars):
        if n > 200:
            warnings.append(f"bar {name} is {n} rows at {r} rows a quarter: IT holds 200, cut there")
            n = 200
        data = "".join(f"{i:02d}: " + " | ".join(" ".join(ln.cells.get(a + i, ["...", "..", "...", "..."])) for ln in lanes) + "\n"
                       for i in range(n))
        got = seen.get(data)
        if got is None:
            got = name if name not in patterns else f"{name}_{pos}"
            patterns[got] = {"rows": n, "data": data}
            seen[data] = got
        orders.append(got)
    if any(ord(c) > 127 for c in title + "".join(ln.name for ln in lanes)):
        warnings.append('Non-ASCII title or track name characters transliterated for the IT song format (? where none fits)')
    chans = []
    for ln in lanes:
        c = {"name": it_text(ln.name, 20)}
        if getattr(ln, "volume", 64) != 64:
            c["volume"] = ln.volume
        if getattr(ln, "pan", 32) != 32:
            c["pan"] = ln.pan
        chans.append(c)
    beat = r * 4 / ts[1]  # a beat is the denominator's note, a bar the numerator of them
    beat, bar = (int(beat), int(beat) * ts[0]) if beat == int(beat) else (r, 4 * r)
    song = {
        "module": {"title": it_text(title, 25), "tempo": tempo, "speed": speed, "global_volume": 128,
                   "mix_volume": 48, "sample_rate": 44100, "rows_per_beat": min(255, beat), "rows_per_bar": min(255, bar), "channels": chans},
        "samples": ph.samples, "instruments": ph.instruments, "patterns": patterns, "orders": orders,
        **({"sections": sections} if sections else {}),
    }
    head += "".join(f"# import warning: {w}\n" for w in warnings)
    Path(song_path).write_bytes((head + to_yaml(song)).encode("utf-8"))
    return song


# ---------------------------------------------------------------- notes to cells

def lane_name(base, label):
    """A channel name: `base` then `label`, the base cut so that the label stays whole in IT's 20 characters once
    transliterated (write_song: ß becomes ss)."""
    while base and len(it_text(f"{base} {label}", 99)) > 20:
        base = base[:-1]
    return f"{base} {label}"


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


def guitar_pro_encoding(value=None):
    """Canonical ASCII-compatible text codec for binary Guitar Pro 1-5 files.

    Keep the historic cp1252 default. GP6/7 XML declares its own encoding.
    Binary transforms, BOM codecs and escape codecs cannot safely encode GP's
    fixed ASCII signatures and byte-sized text fields.
    """
    value = 'cp1252' if value is None else value
    if not isinstance(value, str) or not value.strip():
        raise ValueError('Guitar Pro encoding must name an ASCII-compatible text codec')
    try:
        codec = codecs.lookup(value.strip())
        probe = ''.join(chr(i) for i in range(32, 127)) + '\t\r\n' + r'\u0041\U00000041\x41\n\N{LATIN CAPITAL LETTER A}'
        raw = probe.encode('ascii')
        if (not getattr(codec, '_is_text_encoding', False)
                or probe.encode(codec.name) != raw or raw.decode(codec.name) != probe):
            raise ValueError
    except (LookupError, UnicodeError, ValueError, TypeError):
        raise ValueError(f'Guitar Pro encoding {value!r} is not a supported ASCII-compatible text codec') from None
    return codec.name


def _read_native_gp(data, encoding=None):
    """Use the installed reader with source-qualified native decoding.

    Scoped subclasses only: legacy imports and other PyGuitarPro users are unchanged.
    GP and TG both use bend positions /60 -> /12, bend values /25. TG bar
    values are /50 (GP3 encodes a single dip depth). Raw curve coordinates are
    retained for reporting when TG's rounded projection changes them.
    """
    from guitarpro import io as gp_io, models as M
    from guitarpro.iobase import GPFileBase
    encoding = guitar_pro_encoding(encoding)

    class ExactReader:
        def getTiedNoteValue(self, note):
            # Beat.start is excluded from PyGuitarPro equality: list.index can
            # find an earlier equal beat and therefore the wrong predecessor.
            measure = note.beat.voice.measure
            vi = next(i for i, voice in enumerate(measure.voices) if voice is note.beat.voice)
            mi = next(i for i, item in enumerate(measure.track.measures) if item is measure)
            for previous in reversed(measure.track.measures[:mi + 1]):
                voice = previous.voices[vi]
                stop = next(i for i, beat in enumerate(voice.beats) if beat is note.beat) if previous is measure else len(voice.beats)
                for beat in reversed(voice.beats[:stop]):
                    if beat.status != M.BeatStatus.empty:
                        for old in beat.notes:
                            if old.string == note.string:
                                return old.value
            return -1

        def readTrack(self, track, channels):
            # Inspect only the flag byte; the installed reader owns the layout.
            start = self.data.tell()
            if self.versionTuple[0] == 5 and (track.number == 1 or self.versionTuple == (5, 0, 0)):
                self.skip(1)
            self._percussion_flag = bool(self.readU8() & 1)
            self.data.seek(start)
            super().readTrack(track, channels)

        def readChannel(self, channels):
            start = self.data.tell()
            primary, secondary = self.readI32() - 1, self.readI32() - 1
            self.data.seek(start)
            if self._percussion_flag != (primary == 9):
                raise ValueError('native import: GP percussion flag contradicts primary MIDI route')
            if primary == 9 and secondary != 9:
                raise ValueError('native import: GP percussion secondary MIDI route must be 9')
            return super().readChannel(channels)

        def readNote(self, note, guitarString, track):
            if not track.isPercussionTrack:
                return super().readNote(note, guitarString, track)
            # TG's GP3/4/5 readers change key 100 to zero; PyGuitarPro also
            # clamps invalid keys. Refuse before that written identity is lost.
            start = self.data.tell()
            flags = self.readU8()
            if self.versionTuple[0] < 5 and flags & 0x02 or self.versionTuple[0] == 3 and flags & 0x40:
                raise ValueError('native import: unsupported percussion accent/heavy-accent bit in this GP version')
            kind = self.readU8() if flags & 0x20 else None
            if self.versionTuple[0] < 5 and flags & 1:
                self.skip(2)
            if flags & 0x10:
                self.skip(1)
            key = self.readI8() if flags & 0x20 else None
            self.data.seek(start)
            result = super().readNote(note, guitarString, track)
            if kind != M.NoteType.tie.value:
                if key is None or not 1 <= key <= 99:
                    raise ValueError('native import: GP percussion key must be 1..99; TG normalizes key 100 to zero')
                note.value = key
            else:
                note.value = self.getTiedNoteValue(note)
            return result

        def readChord(self, stringCount):
            # Read the raw fields before PyGuitarPro normalizes pitch classes,
            # truncates fixed names, or discards strings outside the track.
            def block(size):
                value = self.data.read(size)
                if len(value) != size:
                    raise ValueError('native import: truncated GP chord')
                return value

            def unsupported(field):
                raise ValueError(f'native import: unsupported GP chord {field}')

            version = self.versionTuple[0]
            header = self.readU8()
            if header not in (0, 1) or version == 5 and header != 1:
                unsupported('format')
            chord = M.Chord(stringCount)
            if header == 0:
                chord.name = self.readIntByteSizeString()
                chord.firstFret = self.readI32()
                frets = [self.readI32() for _ in range(6)] if chord.firstFret else [-1] * 6
            else:
                prefix = block(25 if version == 3 else 16)
                # Canonical basic diagrams emitted by TG4 (zero fields), TG5
                # (custom root/bass sentinels), and PyGuitarPro (zero fields).
                basic = bytes([1, 0, 0, 0, 12, 0, 0, 255, 255, 255, 255, 0, 0, 0, 0, 0])
                if prefix != bytes(len(prefix)) and not (version == 5 and prefix == basic):
                    unsupported('structured harmonic fields')
                size = self.readU8()
                raw_name = block(34 if version == 3 else 21)
                if size > (22 if version == 3 else 21):
                    unsupported('name length (would overlap or truncate other fields)')
                chord.name = raw_name[:size].decode(self.encoding)
                alterations = raw_name[22:] if version == 3 else block(4)
                if any(alterations):
                    unsupported('alterations/name padding')
                chord.firstFret = self.readI32()
                frets = [self.readI32() for _ in range(6 if version == 3 else 7)]
                detail = block(36 if version == 3 else 32)
                # All-zero is the pinned TG writer's basic block. The second
                # encoding is PyGuitarPro's default unused omissions/fingers.
                default = (bytes(28) + bytes([1]) * 7 + bytes(1) if version == 3 else
                           bytes(16) + bytes([1]) * 7 + bytes(1) + bytes([254]) * 7 + bytes(1))
                if detail not in (bytes(len(detail)), default):
                    unsupported('barres, omissions, fingerings or visibility')
            if any(fret != -1 for fret in frets[stringCount:]):
                unsupported('played string outside the track')
            chord.strings = frets[:stringCount] + [-1] * max(0, stringCount - len(frets))
            if not any(fret >= 0 for fret in chord.strings):
                raise ValueError('native import: GP name-only/all-muted chord is dropped by TuxGuitar')
            return chord

        def readBeat(self, start, voice):
            duration = super().readBeat(start, voice)
            beat = self.getBeat(voice, start)
            # An empty beat does not advance time. The library reuses it for
            # the next record at this start, which can erase its fade flag.
            if beat.effect.fadeIn and (beat.status in (M.BeatStatus.empty, M.BeatStatus.rest) or not beat.notes):
                raise ValueError('native Guitar Pro import: fade-in on a rest or empty beat cannot be preserved')
            if beat.effect.slapEffect != M.SlapEffect.none and (
                    beat.status in (M.BeatStatus.empty, M.BeatStatus.rest) or not beat.notes):
                raise ValueError('native Guitar Pro import: tap/slap/pop on a rest or empty beat cannot be preserved')
            if beat.effect.chord is not None and beat.status == M.BeatStatus.empty:
                raise ValueError('native Guitar Pro import: chord on an empty beat cannot be preserved')
            return duration

        def readBeatStroke(self):
            first, second = self.readI8(), self.readI8()
            if any(value < 0 or value > 6 for value in (first, second)) or first and second:
                raise ValueError('native import: unsupported GP stroke bytes')
            if not (first or second):
                return M.BeatStroke()
            # GP5 stores up/down; GP3/4 store down/up. TG maps BOTH speed
            # bytes 1 and 2 to 64th (PyGuitarPro otherwise maps 1 to 128th).
            direction = ('up' if self.versionTuple[0] == 5 else 'down') if first else (
                'down' if self.versionTuple[0] == 5 else 'up')
            return M.BeatStroke(getattr(M.BeatStrokeDirection, direction),
                               {1: 64, 2: 64, 3: 32, 4: 16, 5: 8, 6: 4}[first or second])

        def readRepeatAlternative(self, measureHeaders):
            value = self.readU8()
            if self.versionTuple[0] == 5:
                return value
            # TG GP3/4: cumulative ordinal minus preceding endings, including
            # the opening header. XOR would resurrect bits above the ordinal.
            existing = 0
            for header in measureHeaders:
                if header.isRepeatOpen:
                    existing = 0
                existing |= header.repeatAlternative
            return ((1 << min(value, 8)) - 1) & ~existing

        def readMeasureHeader(self, number, song, previous=None):
            if self.versionTuple[0] != 5:
                return super().readMeasureHeader(number, song, previous)
            # TG GP5 places ending masks AFTER the four time-signature bytes.
            if previous is not None:
                self.skip(1)
            flags = self.readU8()
            header = M.MeasureHeader(number=number, start=0)
            header.timeSignature.numerator = self.readI8() if flags & 1 else previous.timeSignature.numerator
            header.timeSignature.denominator.value = self.readI8() if flags & 2 else previous.timeSignature.denominator.value
            header.isRepeatOpen = bool(flags & 4)
            if flags & 8:
                header.repeatClose = self.readU8() - 1
            if flags & 0x20:
                header.marker = self.readMarker(header)
            if flags & 0x40:
                header.keySignature = M.KeySignature((self.readI8(), self.readI8()))
            elif previous is not None:
                header.keySignature = previous.keySignature
            if flags & 3:
                header.timeSignature.beams = [self.readU8() for _ in range(4)]
            else:
                header.timeSignature.beams = previous.timeSignature.beams
            if flags & 0x10:
                header.repeatAlternative = self.readRepeatAlternative(song.measureHeaders)
            else:
                self.skip(1)
            header.hasDoubleBar = bool(flags & 0x80)
            header.tripletFeel = M.TripletFeel(self.readU8())
            return header, flags

        def readGrace(self):
            # TG's GP3/4 readers use transition then duration, unlike the
            # installed PyGuitarPro reader/writer. GP5 uses this order too.
            fret, velocity = self.readU8(), self.unpackVelocity(self.readU8())
            transition, duration = self.readU8(), self.readU8()
            if transition not in (0, 1, 2, 3) or duration not in (1, 2, 3):
                raise ValueError('native import: unsupported GP grace transition/duration byte')
            flags = self.readU8() if self.versionTuple[0] == 5 else 0
            if flags & ~3:
                raise ValueError('native import: unsupported GP grace flags')
            dead = bool(flags & 1) if self.versionTuple[0] == 5 else fret == 255
            return M.GraceEffect(fret=0 if dead and self.versionTuple[0] < 5 else fret,
                                 velocity=velocity, duration={1: 64, 2: 32, 3: 16}[duration],
                                 transition=M.GraceEffectTransition(transition), isDead=dead, isOnBeat=bool(flags & 2))

        def fromTrillPeriod(self, value):
            if value not in (1, 2, 3):
                raise ValueError(f'native import: unsupported GP trill period byte {value}')
            return {1: 16, 2: 32, 3: 64}[value]

        def fromTremoloValue(self, value):
            if value not in (1, 2, 3):
                raise ValueError(f'native import: unsupported GP tremolo-picking rate byte {value}')
            return {1: 8, 2: 16, 3: 32}[value]

        def readDuration(self, flags):
            value = self.readI8()
            if not -2 <= value <= 4:
                raise ValueError('native import: written duration is outside whole..64th')
            duration = M.Duration(value=1 << (value + 2), isDotted=bool(flags & 1))
            if flags & 0x20:
                count = self.readI32()
                times = {3: 2, 5: 4, 6: 4, 7: 4, 9: 8, 10: 8, 11: 8, 12: 8, 13: 8}.get(count)
                if times is None:
                    raise ValueError(f'native import: unsupported written tuplet {count}')
                duration.tuplet = M.Tuplet(count, times)
            return duration

        def readBend(self):
            curve = M.BendEffect(type=M.BendType(self.readI8()), value=self.readI32())
            curve.source_points = []
            count = self.readI32()
            if not 1 <= count <= 129:
                raise ValueError('native import: bend/bar needs 1..129 points')
            for _ in range(count):
                position, value, vibrato = self.readI32(), self.readI32(), self.readBool()
                if not 0 <= position <= 60:
                    raise ValueError('native import: bend/bar position outside 0..60')
                if curve.source_points and position < curve.source_points[-1][0]:
                    raise ValueError('native import: bend/bar points are out of order')
                if vibrato:
                    raise ValueError('native import: per-point bend/bar vibrato is unsupported')
                curve.source_points.append((position, value))
                # GP5InputStream.readBend: Java Math.round on the /60 and /25
                # coordinates. Retain the raw values for the import report.
                curve.points.append(M.BendPoint((position * 2 + 5) // 10, (value * 2 + 25) // 50))
            return curve

        def readTremoloBar(self):
            if self.versionTuple[0] != 3:
                return super().readTremoloBar()
            value = self.readI32()
            if value % 50:
                raise ValueError('native import: GP3 tremolo-bar depth cannot be represented exactly')
            return M.BendEffect(type=M.BendType.dip, value=value,
                                points=[M.BendPoint(0, 0), M.BendPoint(6, -value // 25), M.BendPoint(12, 0)])

    stream = io.BytesIO(data)
    version_string = GPFileBase(stream, 'ascii').readVersion()
    version, reader = gp_io.getVersionAndGPFile(version_string)
    native_reader = type('NativeGPReader', (ExactReader, reader), {})
    return native_reader(stream, encoding, version=version_string, versionTuple=version).readSong()


def _native_gp_song(gp, title, *, warnings=None):
    """Pure preflight/conversion. No samples, directories or YAML are written here."""
    from guitarpro import models as M
    from .model import Cell, Pattern
    from .tablature import playback_plan, repeat_projection
    from .tgimport import _normalize_let_ring, _normalize_repetition
    import attr

    preserved = {}

    def retain(kind, where, values):
        if values:
            preserved.setdefault(kind, {}).setdefault(repr(values), []).append(where)

    def gp5_metadata(obj, default, fields, where, kind):
        if gp.versionTuple[0] != 5:
            return defaults(obj, default, fields, where)
        values = {field: getattr(obj, field, None) for field in fields
                  if getattr(obj, field, None) != getattr(default, field, None)}
        retain(kind, where, {k: attr.asdict(v) if attr.has(type(v)) else v for k, v in values.items()})

    def refuse(where, what):
        raise ValueError(f'native Guitar Pro import, {where}: {what}')

    def pair(value):
        value = Fraction(value)
        return [value.numerator, value.denominator]

    def defaults(obj, default, fields, where):
        for field in fields:
            if getattr(obj, field, None) != getattr(default, field, None):
                refuse(where, f'unsupported {field}')

    def curve(source, bar, where):
        if source is None:
            return None
        source_points = getattr(source, 'source_points', None)
        projected = source.points
        if source_points is not None:
            projected = [M.BendPoint((p * 2 + 5) // 10, (v * 2 + (50 if bar else 25)) // (100 if bar else 50))
                         for p, v in source_points]
            if any(p % 5 or v % (50 if bar else 25) for p, v in source_points):
                notice = (f'{where}: source {"tremolo-bar" if bar else "bend"} points {source_points!r}; '
                          'playback/notation uses TuxGuitar 2.1.0 rounded coordinates.')
                metadata.append(notice)
                if warnings is not None:
                    warnings.append(notice)
        points, previous = [], -1
        for p in projected:
            if p.vibrato or p.position < previous or not 0 <= p.position <= 12:
                refuse(where, 'unsupported bend/bar point order, position or vibrato')
            if bar and source_points is None and p.value % 2:
                refuse(where, 'tremolo-bar value cannot be represented exactly')
            value = p.value // 2 if bar and source_points is None else p.value
            if not (-12 if bar else 0) <= value <= 12:
                refuse(where, 'bend/bar value outside native range')
            points.append(dict(position=p.position, value=value))
            previous = p.position
        if not 1 <= len(points) <= 129:
            refuse(where, 'bend/bar needs 1..129 points')
        return dict(points=points)

    def repetition(source, trill, track, string, where):
        if source is None:
            return None
        effect = 'trill' if trill else 'tremolo picking'
        if gp.versionTuple[0] < 4:
            refuse(where, f'{effect} is not representable in GP{gp.versionTuple[0]}')
        duration = source.duration
        rates = (16, 32, 64) if trill else (8, 16, 32)
        if (type(duration.value) is not int or duration.value not in rates or
                duration.isDotted or duration.tuplet != M.Tuplet()):
            refuse(where, f'unsupported GP {effect} duration/rate')
        result = dict(value=duration.value)
        if trill:
            if (type(source.fret) is not int or not 0 <= source.fret <= track.fretCount or
                    not 0 <= track.strings[string - 1].value + track.offset + source.fret <= 119):
                refuse(where, 'trill fret or alternate pitch outside native range')
            result['fret'] = source.fret
        return result

    def harmonic(note, where):
        """Invert PyGuitarPro's version-specific fields to TG 2.1.0's data index."""
        source = note.effect.harmonic
        if source is None:
            return None
        types = {M.NaturalHarmonic: 'natural', M.ArtificialHarmonic: 'artificial',
                 M.TappedHarmonic: 'tapped', M.PinchHarmonic: 'pinch', M.SemiHarmonic: 'semi'}
        kind = types.get(type(source))
        version = gp.versionTuple[0]
        if version >= 6:  # gpx.py already applied TG's GPX parser; it carries TG's data index
            if kind not in ('natural', 'artificial', 'pinch') or getattr(source, 'tg_data', None) not in range(6):
                refuse(where, 'unsupported GPX harmonic type/data')
            return dict(type=kind, data=source.tg_data)
        if kind is None or version not in (1, 2, 3, 4, 5) or version <= 3 and kind not in ('natural', 'artificial'):
            refuse(where, 'unsupported harmonic type/source version')
        data, notice = 0, None
        if kind == 'artificial' and version == 4:
            # GP4's reader uniquely encodes bytes 15/17/22 as these pairs.
            # TG maps those bytes to data 2/3/0, not to their decoded pitches.
            decoded = (getattr(source.pitch, 'value', None), source.octave)
            mapping = {((note.realValue + 7) % 12, M.Octave.ottava): 2,
                       (note.realValue % 12, M.Octave.quindicesima): 3,
                       (note.realValue % 12, M.Octave.ottava): 0}
            if decoded not in mapping:
                refuse(where, 'ambiguous GP4 artificial harmonic; cannot recover source code 15/17/22')
            data = mapping[decoded]
        elif kind == 'artificial' and version == 5:
            notice = (f'GP5 artificial harmonic pitch={getattr(source.pitch, "just", None)}, '
                      f'accidental={getattr(source.pitch, "accidental", None)}, octave={getattr(source.octave, "name", source.octave)} '
                      'retained here as source metadata; TuxGuitar 2.1.0 ignores these fields and plays harmonic data 0.')
        elif kind == 'tapped' and version == 5:
            if type(source.fret) is not int or not 0 <= source.fret <= 255:
                refuse(where, 'invalid GP5 tapped harmonic right-hand fret')
            # GP5 TG reads a signed byte; PyGuitarPro exposes an unsigned one.
            right = source.fret if source.fret < 128 else source.fret - 256
            delta = right - note.value
            frets = (12, 9, 5, 7, 4, 3)
            if delta in frets:
                data = frets.index(delta)
            else:
                notice = (f'GP5 tapped harmonic right-hand fret {source.fret} does not match a TuxGuitar harmonic interval; '
                          'TuxGuitar 2.1.0 plays harmonic data 0.')
        if notice:
            notice = f'{where}: {notice}'
            metadata.append(notice)
            if warnings is not None:
                warnings.append(notice)
        return dict(type=kind, data=data)

    if not 1 <= len(gp.measureHeaders) <= 254 or not gp.tracks:
        refuse('song', 'requires 1..254 measures and at least one track')
    if not 32 <= gp.tempo <= 255:
        refuse('song', 'initial tempo must be 32..255 BPM')
    if gp.clipboard is not None:
        refuse('song', 'clipboard fragments are unsupported')
    lyric_track, lyric_value = gp.lyrics.trackChoice, None
    if type(lyric_track) is not int or not 0 <= lyric_track <= len(gp.tracks):
        refuse('lyrics', 'target track must be 0 (unused) or an existing track')
    if len(gp.lyrics.lines) != 5:
        refuse('lyrics', 'expected exactly five GP lyric lines')
    for li, line in enumerate(gp.lyrics.lines):
        where = f'lyrics line {li + 1}'
        if not isinstance(line.lyrics, str) or len(line.lyrics) > 65536:
            refuse(where, 'text must be a string of at most 65536 codepoints')
        if type(line.startingMeasure) is not int:
            refuse(where, 'start measure must be an integer')
        if li == 0 and lyric_track:
            if not 1 <= line.startingMeasure <= 2147483647:
                refuse(where, 'start measure must be 1..2147483647')
            lyric_value = dict(from_measure=line.startingMeasure, text=line.lyrics)
        else:
            if line.lyrics:
                refuse(where, 'additional lyric lines are unsupported' if li else 'text has no target track')
            # TG writes 0 for wholly unused lyrics; PyGuitarPro defaults to 1.
            # Other empty-line starts are metadata we cannot silently discard.
            if line.startingMeasure not in (0, 1):
                refuse(where, 'unused line has unsupported start-measure metadata')
    master = gp.masterEffect
    # TG 2.1 GP5.00 writes all 42 direction/reverb bytes as 0xff: -1 is
    # its unset master-reverb sentinel, not an authored effect setting.
    neutral_reverbs = (0, -1) if gp.versionTuple == (5, 0, 0) else (0,)
    if ((gp.versionTuple > (5, 0, 0) and master.volume != 100) or master.reverb not in neutral_reverbs
            or master.equalizer is not None and (master.equalizer.gain or any(master.equalizer.knobs))):
        refuse('song', 'master volume/reverb/equalizer is unsupported')
    headers = gp.measureHeaders
    lengths = []
    key = headers[0].keySignature
    fifths, minor = key.value
    if not -7 <= fifths <= 7:
        refuse('measure 1', 'key signature outside native range')
    for mi, h in enumerate(headers):
        where = f'measure {mi + 1}'
        if type(h.isRepeatOpen) is not bool or type(h.repeatClose) is not int or not -1 <= h.repeatClose <= 100:
            refuse(where, 'repeat open/count outside native range (close 0..100)')
        if type(h.repeatAlternative) is not int or not 0 <= h.repeatAlternative <= 255:
            refuse(where, 'ending mask outside native range (passes 1..8)')
        if h.direction is not None or h.fromDirection is not None:
            refuse(where, 'navigation is unsupported')
        if h.tripletFeel not in (M.TripletFeel.none, M.TripletFeel.eighth, M.TripletFeel.sixteenth):
            refuse(where, 'unsupported triplet feel')
        if not -7 <= h.keySignature.value[0] <= 7:
            refuse(where, 'key signature outside native range')
        ts = h.timeSignature
        if not 1 <= ts.numerator <= 64 or ts.denominator.value not in (1, 2, 4, 8, 16, 32, 64):
            refuse(where, 'meter is outside native range')
        if ts.denominator.isDotted or ts.denominator.tuplet != M.Tuplet():
            refuse(where, 'nonstandard meter denominator is unsupported')
        lengths.append(Fraction(4 * ts.numerator, ts.denominator.value))
    speed = next((s for s in [6, *range(1, 6), *range(7, 256)]
                  if all((q * 24 / s).denominator == 1 and 1 <= q * 24 / s <= 200 for q in lengths)), None)
    if speed is None:
        refuse('song', 'measure lengths cannot fit exact backing rows (1..200)')
    step = Fraction(speed, 24)
    score = dict(version=1, tracks={}, patterns={}, order_ids=[], ties=[], measures=[])
    score['metadata'] = {key: str(value) for key, value in dict(title=gp.title or title, artist=gp.artist,
        album=gp.album, author=gp.music, writer=gp.words, copyright=gp.copyright,
        transcriber=gp.tab, comments='\n'.join(str(line) for line in gp.notice)).items() if value}
    song = dict(module=dict(title=it_text(title, 25), tempo=gp.tempo, speed=speed, sample_rate=44100,
                            global_volume=128, mix_volume=48, channels=[]),
                samples={}, instruments={1: {'name': 'guitar (placeholder)'}}, patterns={}, orders=[], score=score)
    metadata = [f'Source title: {title}'] + [f'{label}: {getattr(gp, label)}' for label in
                ('subtitle', 'artist', 'album', 'words', 'music', 'copyright', 'tab', 'instructions')
                if getattr(gp, label, '')]
    metadata += [str(line) for line in gp.notice]
    raw_patterns, tempo_sources = [], [[] for _ in headers]
    for mi, h in enumerate(headers):  # GPX: TG keeps tempo on the header, not on a beat
        value = getattr(h, 'tg_tempo', None)
        if value is not None:
            if not 32 <= value <= 255:
                refuse(f'measure {mi + 1}', 'tempo must be 32..255 BPM')
            tempo_sources[mi].append((f'measure {mi + 1}', Fraction(0), value, 0, None, False))
    for mi, (h, length) in enumerate(zip(headers, lengths)):
        name, occurrence, rows = f'm{mi + 1}', f'o{mi + 1}', int(length / step)
        song['orders'].append(name)
        score['order_ids'].append(occurrence)
        song['patterns'][name] = dict(rows=rows, data='')
        score['patterns'][name] = dict(row_step=pair(step), beats=[])
        score['measures'].append(dict(id=name, **{'from': dict(occurrence=occurrence, at=[0, 1]),
                                                'to': dict(occurrence=occurrence, at=pair(length))},
                                      meter=[h.timeSignature.numerator, h.timeSignature.denominator.value]))
        if h.tripletFeel != M.TripletFeel.none:
            score['measures'][-1]['swing'] = h.tripletFeel.name
        if h.hasDoubleBar:
            score['measures'][-1]['double_bar'] = True
        if h.isRepeatOpen:
            score['measures'][-1]['repeat_open'] = True
        if h.repeatClose >= 0:
            score['measures'][-1]['repeat_close'] = h.repeatClose
        if h.repeatAlternative:
            score['measures'][-1]['endings'] = [i + 1 for i in range(8) if h.repeatAlternative & (1 << i)]
        if h.marker is not None:
            score['measures'][-1]['marker'] = dict(title=h.marker.title,
                color=f'#{h.marker.color.r:02x}{h.marker.color.g:02x}{h.marker.color.b:02x}')
    # TG routes expression through both MIDI channels, and its GP reader
    # shares channels by the primary number even when GP ports differ.
    # Native tracks have independent routes, so splitting a shared fade
    # would change the other track's expression.
    for ti, track in enumerate(gp.tracks):
        if any(beat.effect.fadeIn for measure in track.measures
               for voice in measure.voices for beat in voice.beats):
            routes = {track.channel.channel, track.channel.effectChannel}
            for oi, other in enumerate(gp.tracks):
                if oi != ti and routes & {other.channel.channel, other.channel.effectChannel}:
                    refuse(f'track {ti + 1}',
                           f'fade-in shares MIDI routing with track {oi + 1}; native tracks cannot preserve it')
    for ti, track in enumerate(gp.tracks):
        where, tid = f'track {ti + 1}', f't{ti + 1}'
        percussion = track.isPercussionTrack
        if percussion != (track.channel.channel == 9) or percussion and track.channel.effectChannel != 9:
            refuse(where, 'percussion flag and MIDI routes must agree')
        if percussion and (track.offset or any(s.value for s in track.strings)):
            refuse(where, 'percussion requires zero tuning and capo')
        if not percussion and track.channel.bank == 128:
            refuse(where, 'percussion bank contradicts pitched MIDI route')
        defaults(track, M.Track(gp), ('is12StringedGuitarTrack', 'isBanjoTrack', 'isMute', 'isSolo', 'useRSE'), where)
        defaults(track.settings, M.TrackSettings(), ('autoLetRing', 'autoBrush'), where)
        effects = {field: getattr(track.channel, field) for field in ('chorus', 'reverb', 'phaser', 'tremolo')
                   if getattr(track.channel, field)}
        if any(type(value) is not int or not 0 <= value <= 128 for value in effects.values()):
            refuse(where, 'MIDI effect setting outside 0..128')
        retain('MIDI effects (retained, not emulated by synthesized placeholders)', where, effects)
        defaults(track.rse, M.TrackRSE(), ('humanize', 'autoAccentuation', 'equalizer'), where)
        if len(track.measures) != len(headers):
            refuse(where, 'measure count differs from song')
        if not 1 <= len(track.strings) <= 25 or [s.number for s in track.strings] != list(range(1, len(track.strings) + 1)):
            refuse(where, 'strings must be numbered consecutively from 1')
        first = len(song['module']['channels'])
        if first + len(track.strings) > 64:
            refuse(where, 'native channel capacity exceeded')
        authored_max = max((n.value for measure in track.measures for voice in measure.voices for beat in voice.beats
                            for n in beat.notes), default=0)
        max_fret = 29 if percussion else max(min(track.fretCount, 36), authored_max)
        if track.fretCount > 36 or not percussion and authored_max > track.fretCount:
            retain('declared fret count (TG ignores this display limit)', where, dict(source=track.fretCount, native=max_fret))
        if not -24 <= track.offset <= 24 or not 0 <= track.fretCount <= 255 or not 0 <= max_fret <= 36 or any(not 0 <= s.value <= 119 for s in track.strings):
            refuse(where, 'tuning, capo or fret count outside native range')
        transpose = {field: getattr(track, field, None) for field in ('clefTranspose', 'clefTransposeSecondary')
                     if getattr(track, field, None) not in (None, 0)}
        if transpose and gp.versionTuple[0] != 5:
            refuse(where, 'unsupported clef transposition')
        retain('clef octave display (TG ignores; sounding pitches unchanged)', where, transpose)
        if not 0 <= track.channel.volume <= 128 or track.channel.volume % 2 or not 0 <= track.channel.balance <= 128 or track.channel.balance % 2:
            refuse(where, 'mixer volume/balance cannot be represented exactly')
        song['module']['channels'] += [dict(name=it_text(lane_name(track.name, f'str {s.number}'), 20),
                                           volume=track.channel.volume // 2, pan=track.channel.balance // 2)
                                       for s in track.strings]
        score['tracks'][tid] = dict(name=track.name, tuning=[s.value for s in track.strings],
                                   channels=list(range(first, first + len(track.strings))),
                                   capo=track.offset, max_fret=max_fret, instrument=1,
                                   midi=dict(program=track.channel.instrument, bank=128 if percussion else track.channel.bank,
                                             source_volume=dict(value=getattr(track.channel, 'source_volume', max(track.channel.volume - 1, 0)),
                                                                mixer_volume=track.channel.volume // 2),
                                             source_pan=dict(value=max(track.channel.balance - 1, 0),
                                                             mixer_pan=track.channel.balance // 2)),
                                   color=f'#{track.color.r:02x}{track.color.g:02x}{track.color.b:02x}',
                                   key=dict(fifths=fifths, mode='minor' if minor else 'major'))
        # Pinned TG GP3/4/5 getClef uses tuning, not MIDI program. The formats
        # have no clef selector; omitting this inference changed bass parts to treble.
        if not percussion and any(s.value <= 34 for s in track.strings):
            score['tracks'][tid]['clef'] = 'bass'
        if ti + 1 == lyric_track:
            score['tracks'][tid]['lyrics'] = lyric_value
        metadata.append(f'Track {ti + 1} source MIDI program {track.channel.instrument}, bank {track.channel.bank}; placeholder sound')
        if percussion:
            metadata.append(f'Track {ti + 1} source GP percussion flag true, port {track.port}, '
                            'primary MIDI route 9, secondary MIDI route 9.')
        previous = {}
        absolute = Fraction(0)
        for mi, measure in enumerate(track.measures):
            pname, occurrence = song['orders'][mi], score['order_ids'][mi]
            cohorts = {}
            if mi and headers[mi].keySignature != headers[mi - 1].keySignature:
                fifths_at, minor_at = headers[mi].keySignature.value
                score['measures'][mi].setdefault('staff', {}).setdefault(tid, {})['key'] = dict(
                    fifths=fifths_at, mode='minor' if minor_at else 'major')
            clef = getattr(measure,'tg_clef',None)
            if clef is not None:
                if mi == 0:
                    score['tracks'][tid]['clef'] = clef
                elif clef != score['tracks'][tid].get('clef','treble'):
                    score['measures'][mi].setdefault('staff',{}).setdefault(tid,{})['clef'] = clef
            if measure.lineBreak != M.LineBreak.none:
                refuse(f'{where}, measure {mi + 1}', 'explicit line breaks are unsupported')
            for vi, voice in enumerate(measure.voices):
                for bi, beat in enumerate(voice.beats):
                    loc = f'{where}, measure {mi + 1}, voice {vi + 1}, beat {bi + 1}'
                    if percussion and (beat.effect.vibrato or beat.effect.tremoloBar is not None or
                                       beat.effect.fadeIn or beat.effect.slapEffect != M.SlapEffect.none or
                                       beat.effect.stroke != M.BeatStroke() or beat.effect.chord is not None or
                                       beat.effect.pickStroke != M.BeatStrokeDirection.none):
                        refuse(loc, 'percussion techniques/chords are unsupported')
                    defaults(beat.effect, M.BeatEffect(), ('hasRasgueado',), loc)
                    technique = beat.effect.slapEffect
                    if not isinstance(technique, M.SlapEffect):
                        refuse(loc, 'unsupported tap/slap/pop value')
                    if technique != M.SlapEffect.none and (
                            beat.status in (M.BeatStatus.empty, M.BeatStatus.rest) or not beat.notes):
                        refuse(loc, 'tap/slap/pop on a rest or empty beat cannot be preserved')
                    if type(beat.effect.fadeIn) is not bool:
                        refuse(loc, 'fadeIn must be boolean')
                    if beat.effect.fadeIn and (beat.status in (M.BeatStatus.empty, M.BeatStatus.rest) or not beat.notes):
                        refuse(loc, 'fade-in on a rest or empty beat cannot be preserved')
                    shared = {}
                    if beat.effect.chord is not None:
                        chord = beat.effect.chord
                        defaults(chord, M.Chord(len(track.strings)),
                                 ('sharp', 'root', 'type', 'extension', 'bass', 'tonality', 'add', 'fifth',
                                  'ninth', 'eleventh', 'barres', 'omissions', 'fingerings', 'show'), loc + ' chord')
                        if not any(fret >= 0 for fret in chord.strings) and gp.versionTuple[0] <= 5:
                            refuse(loc, 'GP name-only/all-muted chord is dropped by TuxGuitar')
                        shared['chord'] = dict(name=chord.name, first_fret=chord.firstFret, frets=list(chord.strings))
                    stroke = beat.effect.stroke
                    if not isinstance(stroke, M.BeatStroke) or stroke.direction not in tuple(M.BeatStrokeDirection):
                        refuse(loc, 'unsupported stroke')
                    if stroke.direction == M.BeatStrokeDirection.none:
                        if stroke.value != 0:
                            refuse(loc, 'none stroke must have value 0')
                    elif type(stroke.value) is not int or stroke.value not in (4, 8, 16, 32, 64):
                        refuse(loc, 'unsupported stroke value')
                    else:
                        shared['stroke'] = dict(direction=stroke.direction.name, value=stroke.value)
                    pick = beat.effect.pickStroke
                    if pick not in tuple(M.BeatStrokeDirection):
                        refuse(loc, 'unsupported pickStroke')
                    if pick != M.BeatStrokeDirection.none:
                        if gp.versionTuple[0] == 3:
                            refuse(loc, 'pickStroke is not representable in GP3')
                        shared['pick_stroke'] = pick.name
                    gp5_metadata(beat, M.Beat(voice), ('octave', 'display'), f'{tid}/m{mi + 1}/v{vi + 1}/b{bi + 1}',
                                 'beat display (TG ignores)')
                    mix = beat.effect.mixTableChange
                    if mix is not None:
                        gp5_metadata(mix, M.MixTableChange(), ('instrument', 'volume', 'balance', 'chorus', 'reverb',
                                     'phaser', 'tremolo', 'rse', 'useRSE'), f'{tid}/m{mi + 1}/v{vi + 1}/b{bi + 1}',
                                     'non-tempo mix changes (TG ignores)')
                        # GP5 decodes its mandatory "no wah" byte as an object.
                        if mix.wah is not None and mix.wah != M.WahEffect.none:
                            refuse(loc, 'unsupported mixTableChange wah')
                        if mix.tempo is None and gp.versionTuple[0] != 5:
                            refuse(loc, 'unsupported mixTableChange without tempo')
                        if mix.tempo is not None and (type(mix.tempo.value) is not int or not 32 <= mix.tempo.value <= 255):
                            refuse(loc, 'tempo change must be 32..255 BPM')
                        if mix.tempo is not None:
                            tempo_sources[mi].append((loc, Fraction(beat.start - measure.start, QUARTER),
                                                      mix.tempo.value, mix.tempo.duration, mix.tempoName, mix.hideTempo))
                    if beat.status == M.BeatStatus.empty:
                        if beat.notes or beat.effect != M.BeatEffect(mixTableChange=mix) or beat.text:
                            refuse(loc, 'empty beat carries unsupported content')
                        continue
                    at = Fraction(beat.start - measure.start, QUARTER)
                    duration = Fraction(beat.duration.time, QUARTER)
                    bid = f'{tid}_v{vi + 1}_b{bi + 1}'
                    entry = dict(id=bid, track=tid, voice=vi, at=pair(at),
                                 written=dict(value=beat.duration.value, dots=2 if getattr(beat.duration,'isDoubleDotted',False) else int(beat.duration.isDotted),
                                              tuplet=[beat.duration.tuplet.enters, beat.duration.tuplet.times]), notes=[])
                    entry.update(shared)
                    cohorts.setdefault(at, []).append(entry)
                    if beat.text:
                        entry['text'] = beat.text
                    if voice.direction != M.VoiceDirection.none:
                        entry['stem'] = voice.direction.name
                    if beat.status == M.BeatStatus.rest and beat.notes:
                        refuse(loc, 'rest contains notes')
                    if not beat.notes and (beat.effect.vibrato or beat.effect.tremoloBar is not None):
                        refuse(loc, 'pitch technique on a rest is unsupported')
                    bar = curve(beat.effect.tremoloBar, True, loc)
                    for note in beat.notes:
                        nloc = f'{loc}, string {note.string}'
                        eff = note.effect
                        if percussion:
                            allowed = ['ghostNote', 'letRing']
                            if gp.versionTuple[0] >= 4:
                                allowed += ['accentuatedNote', 'staccato', 'palmMute']
                            if gp.versionTuple[0] >= 5:
                                allowed += ['heavyAccentuatedNote']
                            flags = {field: getattr(eff, field) for field in allowed}
                            expected = M.NoteEffect(**flags, grace=eff.grace,
                                tremoloPicking=eff.tremoloPicking if gp.versionTuple[0] >= 4 else None)
                            if any(type(value) is not bool for value in flags.values()) or eff != expected:
                                refuse(nloc, 'percussion techniques are unsupported in this GP version')
                            if (sum(bool(getattr(eff, field)) for field in
                                    ('ghostNote', 'accentuatedNote', 'heavyAccentuatedNote')) > 1 or
                                    eff.palmMute and eff.staccato):
                                refuse(nloc, 'percussion technique conflict would be normalized by the GP reader')
                            if type(note.velocity) is not int:
                                refuse(nloc, 'percussion requires explicit MIDI velocity')
                        defaults(eff, M.NoteEffect(), ('leftHandFinger', 'rightHandFinger'), nloc)
                        if not math.isfinite(note.durationPercent) or note.durationPercent < 0 or type(note.swapAccidentals) is not bool:
                            refuse(nloc, 'invalid note duration percentage or accidental override')
                        gp5_metadata(note, M.Note(beat), ('durationPercent', 'swapAccidentals'), f'{pname}/{bid}/s{note.string}',
                                     'note duration percentages and accidental swaps (TG ignores)')
                        if hasattr(note, 'duration') or hasattr(note, 'tuplet'):
                            refuse(nloc, 'note-specific duration or accidental override is unsupported')
                        if note.type not in (M.NoteType.normal, M.NoteType.tie, M.NoteType.dead):
                            refuse(nloc, 'unsupported note type')
                        if not 1 <= note.string <= len(track.strings) or not 0 <= note.velocity <= 127:
                            refuse(nloc, 'invalid string or MIDI velocity')
                        if percussion and not 1 <= note.value <= 99:
                            refuse(nloc, 'GP percussion key must be 1..99')
                        if not percussion and (not 0 <= note.value <= max_fret or not 0 <= track.strings[note.string - 1].value + track.offset + note.value <= 119):
                            refuse(nloc, 'fret or sounding pitch outside native range')
                        if eff.slides and eff.slides != [M.SlideType.shiftSlideTo]:
                            refuse(nloc, 'only shift slide to the next note has a native equivalent')
                        nid = f'{bid}_s{note.string}'
                        converted = dict(id=nid, string=note.string, fret=note.value,
                                         pitch=track.strings[note.string - 1].value + track.offset + note.value,
                                         velocity=note.velocity)
                        if beat.effect.fadeIn:
                            converted['fade_in'] = True
                        if technique != M.SlapEffect.none:
                            converted[technique.name] = True
                        if eff.grace is not None:
                            grace = eff.grace
                            if (type(grace.duration) is not int or grace.duration not in (16, 32, 64) or
                                    type(grace.fret) is not int or not (1 if percussion else 0) <= grace.fret <= (100 if percussion else track.fretCount) or
                                    not 0 <= track.strings[note.string - 1].value + track.offset + grace.fret <= 119 or
                                    type(grace.velocity) is not int or not 0 <= grace.velocity <= 127 or
                                    type(grace.isOnBeat) is not bool or type(grace.isDead) is not bool or
                                    grace.transition not in tuple(M.GraceEffectTransition)):
                                refuse(nloc, 'unsupported grace fields, fret or sounding pitch')
                            converted['grace'] = dict(fret=grace.fret, value=grace.duration, velocity=grace.velocity,
                                transition=grace.transition.name, on_beat=grace.isOnBeat, dead=grace.isDead)
                        harmonics = harmonic(note, nloc)
                        if harmonics is not None:
                            converted['harmonic'] = harmonics
                        for field, enabled in (('staccato', eff.staccato), ('palm_mute', eff.palmMute),
                                               ('let_ring', eff.letRing),
                                               ('dead', note.type == M.NoteType.dead),
                                               ('vibrato', eff.vibrato or beat.effect.vibrato), ('slide', bool(eff.slides)),
                                               ('ghost', eff.ghostNote), ('accent', eff.accentuatedNote),
                                               ('heavy_accent', eff.heavyAccentuatedNote), ('hammer', eff.hammer)):
                            if enabled:
                                converted[field] = True
                        bend = curve(eff.bend, False, nloc)
                        if bend is not None:
                            converted['bend'] = bend
                        if bar is not None:
                            converted['tremolo_bar'] = bar
                        for field, value in (
                                ('trill', repetition(eff.trill, True, track, note.string, nloc)),
                                ('tremolo_picking', repetition(eff.tremoloPicking, False, track, note.string, nloc))):
                            if value is not None:
                                converted[field] = value
                        # Beat effects precede note flags; GP5 moves hammer/vibrato
                        # after trill, while GP4 applies them before bend/picking.
                        setters = [('vibrato', beat.effect.vibrato), ('tremolo_bar', bar),
                                   ('dead', note.type == M.NoteType.dead)]
                        late = [('hammer', eff.hammer), ('vibrato', eff.vibrato)]
                        if gp.versionTuple[0] == 4:
                            setters += late
                        setters += [(k, converted.get(k)) for k in ('bend', 'tremolo_picking', 'slide', 'trill')]
                        if gp.versionTuple[0] >= 5:
                            setters += late
                        dropped = _normalize_repetition(converted, setters)
                        if dropped:
                            notice = (f'{nloc}: TuxGuitar 2.1.0 GP{gp.versionTuple[0]} reader normalized repetition '
                                      f'conflicts; removed source fields {dropped!r}.')
                            metadata.append(notice)
                            if warnings is not None:
                                warnings.append(notice)
                        dropped = _normalize_let_ring(converted, ('let_ring', 'palm_mute', 'staccato'))
                        if dropped:
                            notice = (f'{nloc}: TuxGuitar 2.1.0 GP{gp.versionTuple[0]} reader normalized let-ring '
                                      f'conflicts; removed source fields {dropped!r}.')
                            metadata.append(notice)
                            if warnings is not None:
                                warnings.append(notice)
                        endpoint = dict(occurrence=occurrence, note=nid)
                        old = previous.get((vi, note.string))
                        if note.type == M.NoteType.tie:
                            if old is None or old[0] != absolute + at or old[1] != converted['pitch']:
                                refuse(nloc, 'tie has no adjacent same-pitch predecessor in this voice/string')
                            score['ties'].append({'from': old[2], 'to': endpoint})
                        previous[(vi, note.string)] = (absolute + at + duration, converted['pitch'], endpoint)
                        entry['notes'].append(converted)
                    score['patterns'][pname]['beats'].append(entry)
            for entries in cohorts.values():
                for field in ('stroke', 'pick_stroke', 'chord'):
                    values = [entry[field] for entry in entries if field in entry]
                    if any(value != values[0] for value in values[1:]):
                        refuse(f'{where}, measure {mi + 1}', f'conflicting shared beat {field}')
                    if values:
                        for entry in entries:
                            entry[field] = copy.deepcopy(values[0])
            absolute += lengths[mi]
    tempo = gp.tempo
    for mi, sources in enumerate(tempo_sources):
        if not sources:
            continue
        effective = sources[-1][2]
        for index, (loc, at, value, duration, name, hidden) in enumerate(sources):
            metadata.append(f'{loc}: source tempo {value} BPM at quarter {at}, transition duration {duration}, '
                            f'name={name!r}, hidden={hidden}.')
            if at != 0 or duration != 0 or index != len(sources) - 1:
                notice = (f'{loc}: source tempo {value} BPM at quarter {at}, transition duration {duration}; '
                          f'TuxGuitar 2.1.0 uses the last traversed tempo ({effective} BPM) for the entire measure '
                          'and discards transition durations.')
                metadata.append(notice)
                if warnings is not None:
                    warnings.append(notice)
        if effective != tempo:
            song['patterns'][song['orders'][mi]]['data'] = f'00: ... .. ... T{effective:02X}\n'
        tempo = effective
    for kind, groups in preserved.items():
        for values, locations in groups.items():
            metadata.append(f'Source {kind}: {values}; at {", ".join(locations)}.')
        if warnings is not None:
            warnings.append(f'Source {kind}: {sum(map(len, groups.values()))} occurrence(s); original values and locations retained in module.message.')
    song['module']['message'] = '\n'.join(metadata)
    if len(song['module']['message']) > 65534:
        refuse('song', 'source metadata exceeds the module message capacity')
    for name, spec in song['patterns'].items():
        pattern = Pattern(name, [[Cell() for _ in song['module']['channels']] for _ in range(spec['rows'])])
        if spec['data']:
            pattern.rows[0][0] = Cell(effect=20, param=int(spec['data'].strip()[-2:], 16))
        raw_patterns.append(pattern)
    # Includes exact spans, channel collisions, ties and pitch-event limits.
    # Slot 1 is the single placeholder instrument that publication fills below.
    if repeat_projection(song, raw_patterns, 44100) is None:
        playback_plan(song, raw_patterns, 44100)
    return song


def _import_native_gp(gp, src, song_path, samples_dir, read_warnings=(), balances=None):
    warnings = ['Native score imported with synthesized placeholders; source programs/banks are descriptive metadata, not reproduced sounds.',
                *read_warnings]
    song = _native_gp_song(gp, gp.title or Path(src).stem, warnings=warnings)
    for track, balance in zip(song['score']['tracks'].values(), balances or ()):
        track['midi']['source_pan']['value'] = balance  # GP1/2: TG's raw MIDI pan, not GP3-5's x8 - 1
    if song['module']['title'] != (gp.title or Path(src).stem):
        warnings.append('Backing IT title shortened/transliterated; full source title preserved in module.message.')
    return publish_native_score(song, src, song_path, samples_dir, warnings)


def publish_native_score(song, src, song_path, samples_dir, warnings):
    """Publish a preflighted native score with guitar/drum placeholder instruments."""
    import copy
    from .api import prepare_playback, to_yaml, written_by_line
    from .fileio import atomic_write, device_name, link_new, protect_outputs

    song_path, samples_dir = Path(song_path), Path(samples_dir)
    protect_outputs([song_path, samples_dir], [src])
    for path in (song_path, samples_dir):
        if path.exists() or path.is_symlink():
            raise ValueError(f'native score import needs a fresh destination: {path}')
        if not path.parent.is_dir() or device_name(path.name) or any(c in path.name for c in '<>:"|?*\0') or path.name.endswith((' ', '.')):
            raise ValueError(f'native score import: invalid output path {path}')
    # Generate privately after complete preflight; publish YAML only after its samples.
    with tempfile.TemporaryDirectory(prefix='.gp-native-', dir=song_path.parent) as tmp:
        ph = Placeholders(Path(tmp) / 'samples', song_path)
        ph.rel = os.path.relpath(samples_dir.resolve(), song_path.resolve().parent).replace(os.sep, '/')
        for track in song['score']['tracks'].values():
            track['instrument'] = ph.instrument('drums' if track.get('midi', {}).get('bank') == 128 else 'guitar')
        song['samples'], song['instruments'] = ph.samples, ph.instruments
        staged = copy.deepcopy(song)
        for sample in staged['samples'].values():
            sample['file'] = str(ph.dir / Path(sample['file']).name)
        # Exercise the real compiler and complete native bundle while all assets
        # are still private. Failure removes only TemporaryDirectory's own files.
        prepare_playback(staged, base_dir=tmp)
        data = (written_by_line() + ''.join('# ' + w + '\n' for w in warnings) + to_yaml(song)).encode('utf-8')
        samples_dir.mkdir()
        for sample in ph.dir.iterdir():
            link_new(sample, samples_dir / sample.name)
        atomic_write(song_path, data, replace=False)
    return song, warnings


def import_gp(src, song_path, samples_dir, *, native=False, encoding=None):
    """A Guitar Pro file (.gtp GP1/GP2, .gp3, .gp4, .gp5; detected by header) as a song YAML plus placeholder WAVs in
    `samples_dir`. Returns (song dict,
    warnings). `native=True` preserves exact written score and refuses unsupported source
    features before writing; it requires fresh destinations and never flattens repeats."""
    try:
        import guitarpro
        from guitarpro import models as gp_models
    except ImportError:
        raise ValueError("Guitar Pro import needs PyGuitarPro: pip install pyguitarpro (LGPL-3)")
    from . import gplegacy, gpx
    selected_encoding = guitar_pro_encoding(encoding)
    read_warnings, balances = [], None
    try:  # from memory: a size-prefixed read on a file preallocates what a bad header claims (gigabytes)
        data = Path(src).read_bytes()
        # Detected by content, as TuxGuitar does, never by extension.
        if gplegacy.version_of(data) in gplegacy.VERSIONS:
            gp, balances = gplegacy.read_gtp(data, read_warnings, encoding=encoding)
            read_warnings.append(f'Guitar Pro text decoded with {selected_encoding}.')
        elif gpx.detect(data):
            gp, balances = gpx.read(data, read_warnings)
            if encoding is not None:
                read_warnings.append('GP6/7 XML declares its own text encoding; the binary Guitar Pro encoding option was not applied.')
        elif data[:2] == b'PK':
            raise ValueError('a zip container that is not GP7: TuxGuitar 2.1.0 reads only VERSION 7.0 '
                             '(GP8 and other zips are not claimed)')
        else:
            gp = (_read_native_gp(data, selected_encoding) if native
                  else guitarpro.parse(io.BytesIO(data), encoding=selected_encoding))
            read_warnings.append(f'Guitar Pro text decoded with {selected_encoding}.')
    except Exception as e:  # noqa: BLE001 - PyGuitarPro raises what its reader hits (GPException, struct.error, ...)
        raise ValueError(f"{src}: not a readable Guitar Pro 1-7 file ({type(e).__name__}: {e})") from e
    if native:
        return _import_native_gp(gp, src, song_path, samples_dir, read_warnings, balances)
    warnings, skipped = list(read_warnings), {}
    for h in gp.measureHeaders[1:]:  # GPX header tempos, as the mix-table changes this path reads
        if getattr(h, 'tg_tempo', None) is None:
            continue
        beat = next((b for t in gp.tracks for v in t.measures[h.number - 1].voices for b in v.beats
                     if b.start == h.start and b.effect.mixTableChange is None), None)
        if beat is not None:
            beat.effect.mixTableChange = gp_models.MixTableChange(tempo=gp_models.MixTableItem(h.tg_tempo, duration=0))
    if not gp.measureHeaders:
        raise ValueError(f"{src}: the tab has no measures")
    if not gp.tempo > 0:
        warnings.append(f"the tab's tempo is {gp.tempo}: 120 BPM is used")
        gp.tempo = 120

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

    ph = Placeholders(samples_dir, song_path)
    lanes, tempo_lane = [], Lane("Tempo")
    for track in tracks:
        drums = track.isPercussionTrack
        program = track.channel.instrument
        ins = ph.instrument("drums" if drums else "bass" if 32 <= program <= 39 else "guitar")
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
                        else:  # frets count from the capo (track.offset): TuxGuitar plays offset + string + fret
                            pitch = note.realValue + track.offset
                            if eff.harmonic is not None:
                                pitch = (track.strings[note.string - 1].value + track.offset + HARMONIC[note.value]
                                         if eff.harmonic.type == 1 and note.value in HARMONIC
                                         and 1 <= note.string <= len(track.strings) else pitch + 12)
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
            ln = Lane(lane_name(track.name.strip()[:13], label))
            # PyGuitarPro gives the mixer's 0-16 steps times 8: 0-128, balance 64 = centre
            ln.volume = min(64, round(track.channel.volume / 2))
            ln.pan = min(64, round(track.channel.balance / 2))
            _lane_cells(ln, evs, speed, r, skip)
            lanes.append(ln)
    if tempo_lane.cells:
        lanes.append(tempo_lane)
    if not lanes:
        raise ValueError("the tab has no notes")
    for what, count in skipped.items():
        warnings.append(f"{count} {what} left out")
    ts = headers[0].timeSignature  # the first measure's
    bars = [(f"m{mi + 1}", starts[pos], mrows[pos]) for pos, mi in enumerate(order)]
    from .api import written_by_line
    head = (f"# Imported from {Path(src).name} by vulturetracker import (Guitar Pro: placeholder sounds, swap them in the tryout)\n"
            f"# {gp.tempo} BPM, {r} rows a quarter note: speed {speed}, tempo {tempo}\n" + written_by_line())
    song = write_song(song_path, gp.title or Path(src).stem, lanes, bars, ph, r, speed, tempo,
                      (ts.numerator, ts.denominator.value), warnings, head)
    return song, warnings
