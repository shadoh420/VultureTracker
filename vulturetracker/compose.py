"""Composition helpers for the Pattern tab's selection bar: pure functions over a compiled pattern's rows (rows[row][channel]
of model.Cell) that return the cells to write, as [{"row", "ch", "cell"}] with the cell in song notation. The app writes
them into the song text in place as one undo step (State.song_edit), so what they make is plain IT that the pattern view
shows and edits like any other cell:

- groove: a repeating per-row note delay (SDx), e.g. 0 2 swings every other row by two ticks;
- accent: a repeating per-row note volume (vNN), as volumes or percents of each note's own, e.g. 64 40 52 40;
- euclid: k hits spread as evenly as they go over n steps (Euclidean rhythm), rotated, each kept with a probability from
  a seed, so the same settings always write the same cells;
- chord: each note of a channel stacked into a chord over the channels to its right, note-offs copied so it ends whole;
- layers: instruments cycled note by note (round-robin), or chosen by each note's volume (velocity layers);
- arp and strum: each written note played as an arpeggio of a chord shape; a chord's voices delayed one after another;
- interpolate (OpenMPT's, all four columns, with its sweep), automate (a curve as Zxx/Xxx/Mxx/Vxx/Txx/vNN cells), grow and
  shrink (OpenMPT's), and the note lengths: fill, set_length, cut_here, glue.
"""
import random
import re

from .model import NOTE_OFF, Cell
from .notation import VOLCMDS, format_cell

S_EFFECT = 19  # S: its high nibble D is the note delay (SDx)

CHORDS = {  # semitones above the root
    "maj": (0, 4, 7), "min": (0, 3, 7), "dim": (0, 3, 6), "aug": (0, 4, 8), "sus2": (0, 2, 7), "sus4": (0, 5, 7),
    "5": (0, 7), "6": (0, 4, 7, 9), "min6": (0, 3, 7, 9), "7": (0, 4, 7, 10), "maj7": (0, 4, 7, 11),
    "min7": (0, 3, 7, 10), "m7b5": (0, 3, 6, 10), "dim7": (0, 3, 6, 9), "add9": (0, 4, 7, 14), "maj9": (0, 4, 7, 11, 14),
    "min9": (0, 3, 7, 10, 14),
}


def _is_delay(c):
    return c.effect == S_EFFECT and c.param >> 4 == 0xD


def _write(out, row, ch, cell):
    out.append({"row": row, "ch": ch, "cell": format_cell(cell)})


def groove(rows, chans, r0, r1, ticks, speed):
    """Every note (note-offs too, so lengths hold) on rows r0..r1 of `chans` delayed by ticks[row % len(ticks)]: the
    groove repeats from the pattern's first row. An SDx already there is replaced (a 0 removes it); a note with another
    effect keeps it and is left undelayed. Returns (cells, skipped)."""
    ticks = [int(t) for t in ticks]
    if not ticks or not all(0 <= t < min(speed, 16) for t in ticks):
        raise ValueError(f"a groove is a list of tick delays, each 0-{min(speed, 16) - 1} (at speed {speed} a row has {speed} "
                         "ticks; SDx holds at most 15)")
    out, skipped = [], 0
    for r in range(r0, r1 + 1):
        t = ticks[r % len(ticks)]
        for ch in chans:
            c = rows[r][ch]
            if c.note is None:
                continue
            if _is_delay(c) or c.effect == 0 and not c.param:
                new = Cell(c.note, c.instrument, c.volcmd, S_EFFECT if t else 0, 0xD0 | t if t else 0)
                if (new.effect, new.param) != (c.effect, c.param):
                    _write(out, r, ch, new)
            elif t:
                skipped += 1
    return out, skipped


def accent(rows, chans, r0, r1, levels, default_volume=None):
    """Every note (0-119) on rows r0..r1 of `chans` given the volume levels[row % len(levels)]: the accents repeat from
    the pattern's first row, like groove's ticks. A level is a volume 0-64 (`40` or `v40`), written as vNN, or a percent
    (`60%`) of the note's own volume: its vNN, else what IT plays it at, carried down the channel from the pattern's top
    (`default_volume(cell)` where a cell names an instrument, a vNN above it); a note already playing at its level keeps
    its cell. A note with another volume-column command
    (a pan, a slide), or a percent on a note whose volume the pattern does not say, is left alone and counted. Returns
    (cells, skipped)."""
    parsed = []
    for lv in levels:
        m = re.fullmatch(r"v?(\d+(?:\.\d+)?)(%?)", str(lv).strip().lower())
        pct, n = bool(m and m[2]), float(m[1]) if m else -1
        if n < 0 or not pct and n > 64:
            raise ValueError(f"an accent is a volume 0-64 (40 or v40) or a percent of the note's volume (60%), not '{lv}'")
        parsed.append((pct, n))
    if not parsed:
        raise ValueError("give the volume of each row, e.g. 64 40 52 40 or 100% 60%")
    out, skipped = [], 0
    for ch in chans:
        vol = None  # the channel's volume as IT carries it from the pattern's top: unknown until a vNN or an instrument
        for r in range(0, r1 + 1):
            c = rows[r][ch]
            if c.note is None or c.note >= 120:
                vol = c.volcmd if c.volcmd is not None and c.volcmd <= 64 else vol
                continue
            if c.instrument and default_volume:
                vol = default_volume(c) if default_volume(c) is not None else vol
            own, vol = (c.volcmd, c.volcmd) if c.volcmd is not None and c.volcmd <= 64 else (vol, vol)
            if r < r0:
                continue
            if c.volcmd is not None and c.volcmd > 64:
                skipped += 1
                continue
            pct, n = parsed[r % len(parsed)]
            if pct and own is None:  # a bare note whose volume the pattern does not say
                skipped += 1
                continue
            v = min(64, int(own * n / 100 + 0.5)) if pct else int(n + 0.5)
            if v != c.volcmd and v != own:  # a bare note already playing at v keeps inheriting it
                _write(out, r, ch, Cell(c.note, c.instrument, v, c.effect, c.param))
    return out, skipped


def euclid_steps(hits, steps, rotate=0):
    """`hits` onsets spread as evenly as they go over `steps` (the Euclidean rhythm, as Bresenham's line draws it: 3 over 8
    is x..x..x.), turned `rotate` steps to the left."""
    if not 0 <= hits <= steps or steps < 1:
        raise ValueError("a Euclidean rhythm has 1-64 steps and at most as many hits")
    return [((i + rotate) % steps * hits) % steps < hits for i in range(steps)]


RULE = re.compile(r"-|rev|inv|rot(\d+)|\+(\d+)")  # one phrase's transform: as is, reversed, inverted, turned, turned k*N


def euclid(rows, ch, r0, r1, hits, steps, rotate=0, every=1, prob=100, seed=1, more=(), phrase=0, rules=(), start=0,
           template=None, default_volume=None):
    """Channel `ch`, rows r0..r1, made a Euclidean rhythm of the cell on row r0 (or `template`): a step every `every` rows,
    `hits` of each `steps` steps sounding (the rhythm repeats down the selection), each hit kept with `prob` percent from
    `seed` (the same settings write the same cells). Every other row of the selection is cleared.

    `more` layers further (hits, steps) cycles over it: a step sounds where any cycle hits, at the top cell's volume
    where all of them do, down to half of it where one does (when that volume is known: its vNN, else
    `default_volume(template)`). With `phrase` rows the cycles restart at every phrase, counted from row 0 of a pattern
    that starts `start` rows into the song (so they realign at phrase ends), and phrase k takes rules[k % len(rules)]:
    `-` as is, `rev` reversed, `inv` hits and rests swapped, `rotN` turned N steps left, `+N` turned k*N steps left."""
    template = template or rows[r0][ch]
    if template.note is None or template.note >= 120:
        raise ValueError("the rhythm plays the cell at the top of the selection: put a note there first")
    if not 1 <= every <= 64:
        raise ValueError("a step is 1-64 rows")
    cycles = [(int(h), int(s)) for h, s in [(hits, steps), *more]]
    if not all(1 <= s <= 64 for _, s in cycles) or len(cycles) > 8:
        raise ValueError("a Euclidean rhythm has 1-64 steps, and up to 8 cycles layered")
    if not 0 <= phrase <= 4096:
        raise ValueError("a phrase is 0 (none) to 4096 rows")
    parsed = [RULE.fullmatch(str(t).strip().lower()) for t in rules]
    if not all(parsed):
        raise ValueError("a phrase rule is -, rev, inv, rotN (turned N steps) or +N (turned N more each phrase)")
    if parsed and not phrase:
        raise ValueError("rules change the rhythm at each phrase: give the phrase's rows")
    n, base = len(cycles), template.volcmd if template.volcmd is not None else (
        default_volume(template) if default_volume else None)
    if base is not None and base > 64:
        base = None  # a pan or a slide in the volume column: written as it is, no accents
    turned = {}  # (hits, steps, rotation): the cycle's steps

    def hit(h, s, rot, j):
        key = (h, s, rot % s)
        if key not in turned:
            turned[key] = euclid_steps(h, s, rot)
        return turned[key][j % s]

    rng, out = random.Random(seed), []
    for r in range(r0, r1 + 1):
        k, off = divmod(start + r, phrase) if phrase else (0, start + r - r0)
        i, rule, rot = off // every, parsed[k % len(parsed)] if parsed else None, rotate
        word = rule[0] if rule else "-"
        if word == "rev":
            i = -(-phrase // every) - 1 - i
        rot += int(rule[1]) if rule and rule[1] else k * int(rule[2]) if rule and rule[2] else 0
        count = sum(hit(h, s, rot, i) for h, s in cycles)
        if word == "inv":
            count = n if count == 0 else 0
        on = off % every == 0 and count > 0
        if on and prob < 100:
            on = rng.random() * 100 < prob
        want = template if on else Cell()
        if on and n > 1 and base is not None:
            want = Cell(template.note, template.instrument, int(base * (n + count - 2) / (2 * n - 2) + 0.5),
                        template.effect, template.param)
        c = rows[r][ch]
        if (c.note, c.instrument, c.volcmd, c.effect, c.param) != (want.note, want.instrument, want.volcmd, want.effect, want.param):
            _write(out, r, ch, want)
    return out


def chord(rows, ch, r0, r1, shape, inversion=0, nch=None):
    """Each note on channel `ch`, rows r0..r1, made the chord `shape` (a CHORDS name or a list of semitones) over `ch` and
    the channels to its right: the lowest tone stays on `ch` (moved up an octave for an inversion), each other tone goes
    one channel further right with the root cell's instrument (its last one, when the cell names none) and volume. A
    note-off, cut or fade on `ch` is copied across, so the chord ends as one. Cells there are overwritten."""
    iv = _shape(shape)
    size = len(iv)
    if not 0 <= inversion < size:
        raise ValueError(f"a {size}-note chord has inversions 0-{size - 1}")
    nch = nch if nch is not None else len(rows[0])
    if ch + size > nch:
        raise ValueError(f"a {size}-note chord on channel {ch + 1} needs channels {ch + 1}-{ch + size}; the song has "
                         f"{nch}: add channels (SONG tab) or start further left")
    last_ins, out = 0, []
    for r in range(0, r1 + 1):
        c = rows[r][ch]
        if c.instrument:
            last_ins = c.instrument
        if r < r0 or c.note is None:
            continue
        if c.note >= 120:
            cells = [c] + [Cell(c.note) for _ in range(size - 1)]
        else:
            tones = sorted(c.note + x + (12 if k < inversion else 0) for k, x in enumerate(iv))
            if tones[-1] > 119:
                raise ValueError(f"row {r}: the chord's top note is past B-9; transpose it down")
            vol = c.volcmd if c.volcmd is not None and c.volcmd <= 64 else None
            cells = [Cell(tones[0], c.instrument, c.volcmd, c.effect, c.param)]
            cells += [Cell(t, c.instrument or last_ins, vol) for t in tones[1:]]
        for k, cell in enumerate(cells):
            old = rows[r][ch + k]
            if (old.note, old.instrument, old.volcmd, old.effect, old.param) != (cell.note, cell.instrument, cell.volcmd, cell.effect, cell.param):
                _write(out, r, ch + k, cell)
    return out


def layers(rows, chans, r0, r1, instruments, mode="cycle", default_volume=None):
    """The instrument column of every note (0-119) on rows r0..r1 of `chans`: `cycle` takes `instruments` in turn, note
    by note down each channel (round-robin); `volume` picks by the note's volume, the list running from the quietest band
    to the loudest (0-64 split evenly), a note without a volume command at `default_volume(cell)` or 64."""
    instruments = [int(i) for i in instruments]
    if not instruments or not all(1 <= i <= 99 for i in instruments):
        raise ValueError("give the instruments (or samples) to use, 1-99, e.g. 03 04 05")
    if mode not in ("cycle", "volume"):
        raise ValueError("layers go round-robin (cycle) or by volume")
    out = []
    for ch in chans:
        k = 0
        for r in range(r0, r1 + 1):
            c = rows[r][ch]
            if c.note is None or c.note >= 120:
                continue
            if mode == "cycle":
                ins, k = instruments[k % len(instruments)], k + 1
            else:
                vol = c.volcmd if c.volcmd is not None and c.volcmd <= 64 else (default_volume(c) if default_volume else None)
                vol = 64 if vol is None else vol
                ins = instruments[min(len(instruments) - 1, vol * len(instruments) // 65)]
            if ins != c.instrument:
                _write(out, r, ch, Cell(c.note, ins, c.volcmd, c.effect, c.param))
    return out


def slice_rows(starts, rate, tempo, speed, ch=0, nch=1, max_rows=200, grid=None):
    """Where slices that start at frames `starts` (ascending, of a WAV at `rate`) fall in a pattern played at `tempo` and
    `speed`, so that playing them in order keeps their original timing (Renoise's slices rendered to a phrase): the
    first on row 0, each on the row its start reaches and delayed by the ticks left over (SDx), rounded to the nearest
    tick (2.5 / tempo s). A slice that lands on a row already taken goes to the next channel to the right (up to `nch`).
    `grid` = (the sample's own BPM, the song's rows per beat): each slice on the row its place in beats reaches instead,
    rounded, no delays, so a loop at another tempo follows the song's (SlicerT's notes on its grid).
    Returns (placed: [(slice index, row, ch, delay ticks)], rows the pattern needs, dropped: slice indices that did not
    fit: past `max_rows` or with every channel taken)."""
    tick = 2.5 / tempo
    placed, dropped, taken, last = [], [], {}, 0
    for k, s in enumerate(starts):
        if grid:
            row, delay = round((s - starts[0]) / rate * grid[0] * grid[1] / 60), 0
        else:
            row, delay = divmod(round((s - starts[0]) / rate / tick), speed)
        c = ch
        while c < nch and (row, c) in taken:
            c += 1
        if row >= max_rows or c >= nch:
            dropped.append(k)
            continue
        taken[(row, c)] = k
        placed.append((k, row, c, delay))
        last = max(last, row)
    return placed, last + 1, dropped


def key_splits(notes, lo=0, hi=119):
    """A keyboard split for sounds recorded at `notes` (note numbers, any order, repeats allowed): each distinct note
    plays over the keys closer to it than to its neighbours (a key halfway between two goes to the lower), the lowest down
    to `lo` and the highest up to `hi`. Returns [(index into notes, first key, last key)] from low to high; a repeated
    note keeps its first index."""
    first = {}
    for i, n in enumerate(notes):
        first.setdefault(int(n), i)
    ns = sorted(first)
    out = []
    for j, n in enumerate(ns):
        a = lo if j == 0 else (ns[j - 1] + n) // 2 + 1
        b = hi if j == len(ns) - 1 else (n + ns[j + 1]) // 2
        out.append((first[n], a, b))
    return out


# ---------------------------------------------------------------- the song's key (the SONG tab, the agent's tools)

MODES = {"major": (0, 2, 4, 5, 7, 9, 11), "ionian": (0, 2, 4, 5, 7, 9, 11), "dorian": (0, 2, 3, 5, 7, 9, 10),
         "phrygian": (0, 1, 3, 5, 7, 8, 10), "lydian": (0, 2, 4, 6, 7, 9, 11), "mixolydian": (0, 2, 4, 5, 7, 9, 10),
         "minor": (0, 2, 3, 5, 7, 8, 10), "aeolian": (0, 2, 3, 5, 7, 8, 10), "locrian": (0, 1, 3, 5, 6, 8, 10)}
PITCH = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}
NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
# Krumhansl-Kessler key profiles (probe-tone ratings)
KK = {"major": (6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88),
      "minor": (6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17)}


def scale_of(key):
    """The pitch classes of a key like 'A minor', 'F# major' or 'D dorian'."""
    from .song import KEY_RE
    m = KEY_RE.fullmatch(str(key).strip())
    if not m:
        raise ValueError(f"a key like 'A minor' or 'D dorian', got {key!r}")
    root = (PITCH[m.group(1).upper()] + {"#": 1, "b": -1}.get(m.group(2), 0)) % 12
    return {(root + i) % 12 for i in MODES[m.group(3).lower()]}


def key_report(mod, key=None):
    """How the notes the song strikes sit in `key` (the module's own when None): per channel, the share of note onsets
    whose pitch class is in the scale (a channel whose notes are drum hits on arbitrary keys reads low: the owner knows
    which channels are pitched), and the best Krumhansl-Kessler estimate of the key from the onsets of the channels that strike three or more
    pitch classes. Notes are counted
    as written in the cells (an instrument's keymap can play another note)."""
    import numpy as np
    key = key or getattr(mod, "key", "") or None
    scale = scale_of(key) if key else None
    hist = np.zeros(12)
    per = []
    for ch in range(len(mod.channels)):
        pcs = [c.note % 12 for o in mod.orders if o < 254 for row in mod.patterns[o].rows
               if ch < len(row) for c in [row[ch]] if c.note is not None and c.note < 120]
        if len(set(pcs)) >= 3:  # a channel striking one or two pitches is taken for drums: left out of the estimate
            for p in pcs:
                hist[p] += 1
        inside = sum(p in scale for p in pcs) if scale else None
        per.append({"channel": ch + 1, "name": mod.channels[ch].name or f"Ch {ch + 1}", "notes": len(pcs),
                    "in_key": round(inside / len(pcs), 2) if scale and pcs else None})
    best = None
    if hist.sum():
        for mode, prof in KK.items():
            for r in range(12):
                c = float(np.corrcoef(hist, np.roll(prof, r))[0, 1])
                if best is None or c > best[0]:
                    best = (c, f"{NAMES[r]} {mode}")
    total = sum(c["notes"] for c in per)
    inside = sum(round((c["in_key"] or 0) * c["notes"]) for c in per) if scale else None
    return {"key": key, "in_key": round(inside / total, 2) if scale and total else None, "channels": per,
            "estimate": best[1] if best else None, "estimate_r": round(best[0], 2) if best else None}


# ---------------------------------------------------------------- INTERPOLATE and AUTOMATE (the SELECTION bar)

TWO_NIBBLES = {ord(c) - 64 for c in "DHIJKLNPQRSUWY"}  # OpenMPT's CommandHasTwoNibbles, as IT letters
VOL_SLIDES = {4, 11, 12}  # D, K, L: OpenMPT's IsNormalVolumeSlide


def _cdiv(a, b):
    """C's integer division (towards zero), as OpenMPT's interpolation rounds."""
    return -(-a // b) if (a < 0) != (b < 0) else a // b


def _vol(byte):
    """A raw volume-column byte as (letter, value), (None, 0) when empty."""
    if byte is None:
        return None, 0
    for k, (base, top) in VOLCMDS.items():
        if base <= byte <= base + top:
            return k, byte - base
    return None, 0


def _is_note(n):
    return n is not None and n < 120


def _possible(a, b, field):
    """OpenMPT's IsInterpolationPossible for one column of [note, instrument, volume byte, effect, param] lists."""
    if field == 0:
        x, y = a[0], b[0]
        return (x == y and x is not None) or (x is None) != (y is None) or (
            (x is None or _is_note(x)) and (y is None or _is_note(y)) and not (x is None and y is None))
    if field == 1:
        return bool(a[1] or b[1])
    if field == 2:
        x, y = _vol(a[2])[0], _vol(b[2])[0]
        return (x == y and x is not None) or (x is None) != (y is None)
    x, y = a[3], b[3]
    return (x == y and x != 0) or (x in VOL_SLIDES and y in VOL_SLIDES) or (x != 0) != (y != 0)


def sweep(rows, ch, row, field):
    """OpenMPT's SweepPattern (interpolation with no selection): the nearest row at or above `row` with a value in the
    column, and the first row from `row` down that it can interpolate to. (r0, r1), or None when the span is one row
    (the cursor sits on the start value) or no end is found."""
    start = [lambda c: c.note is not None, lambda c: bool(c.instrument), lambda c: c.volcmd is not None,
             lambda c: c.effect != 0][field]
    end = [lambda s, e: _is_note(s.note) and _is_note(e.note), lambda s, e: e.instrument == s.instrument,
           lambda s, e: _vol(e.volcmd)[0] == _vol(s.volcmd)[0],
           lambda s, e: e.effect == s.effect or (s.effect in VOL_SLIDES and e.effect in VOL_SLIDES)][field]
    r0 = next((r for r in range(row, -1, -1) if start(rows[r][ch])), None)
    if r0 is None:
        return None
    r1 = next((r for r in range(row, len(rows)) if end(rows[r0][ch], rows[r][ch])), None)
    return (r0, r1) if r1 is not None and r1 > r0 else None


def interpolate(rows, cols, r0, r1, default_volume=None):
    """OpenMPT's Interpolate (View_pat.cpp) over rows r0..r1, for each (channel, fields) of `cols` (fields 0 note,
    1 instrument, 2 volume column, 3 effect), in that order: where the column allows it (both ends carry the same
    command, or one end is empty and the other's value fills the span), every row whose field is empty or carries the
    same command gets the value on the straight line between the ends, rounded as OpenMPT rounds; a two-nibble effect
    moves each nibble on its own line; D, K and L slide into one another. A note row also takes the start's instrument
    where it names none. An empty volume end on a note with an instrument counts from that note's default volume
    (`default_volume(cell)`, else 64)."""
    distance = r1 - r0
    out = []
    if distance < 1:
        return out
    for ch, fields in cols:
        W = [[c.note, c.instrument, c.volcmd, c.effect, c.param] for c in (rows[r][ch] for r in range(r0, r1 + 1))]
        for field in sorted(set(fields)):
            s, d = W[0], W[-1]
            if not _possible(s, d, field):
                continue
            if field == 0:
                N = lambda n: 0 if n is None else n + 1 if n < 120 else n  # OpenMPT's numbering: 0 none, 1 C-0
                vsrc, vdest, vcmd, verr = N(s[0]), N(d[0]), s[1], distance * 119 // 120
                if s[0] is None:
                    vsrc, vcmd = vdest, d[1]  # OpenMPT puts the end's note in this instrument slot: its instrument meant
                elif d[0] is None:
                    vdest = vsrc
            elif field == 1:
                vsrc, vdest, vcmd, verr = s[1], d[1], 0, distance * 63 // 128
                if not s[1]:
                    vsrc = vdest
                elif not d[1]:
                    vdest = vsrc
            elif field == 2:
                (vcmd, vsrc), (dc, vdest), verr = _vol(s[2]), _vol(d[2]), distance * 63 // 128

                def default(c):
                    v = default_volume(Cell(c[0], c[1])) if default_volume else None
                    return 64 if v is None else v
                if vcmd is None:
                    vcmd = dc
                    vsrc = default(s) if vcmd == "v" and _is_note(s[0]) and s[1] else vdest
                elif dc is None:  # OpenMPT reads the start's default here; the end's note is meant
                    vdest = default(d) if vcmd == "v" and _is_note(d[0]) and d[1] else vsrc
            else:
                vsrc, vdest, vcmd, slide = s[4], d[4], s[3], s[3] in VOL_SLIDES
                if not s[3]:
                    vsrc, vcmd, slide = vdest, d[3], d[3] in VOL_SLIDES
                elif not d[3]:
                    vdest = vsrc
                verr = distance * 63 // 128
                lo = (vsrc & 15, vdest & 15, verr if vsrc & 15 < vdest & 15 else -verr)
                hi = (vsrc >> 4, vdest >> 4, verr if vsrc >> 4 < vdest >> 4 else -verr)
            if vdest < vsrc:
                verr = -verr
            for i, c in enumerate(W):
                line = vsrc + _cdiv((vdest - vsrc) * i + verr, distance)
                if field == 0:
                    if c[0] is None or c[1] == vcmd:
                        c[0] = None if line == 0 else line - 1 if line <= 120 else line
                        if not c[1]:
                            c[1] = vcmd
                elif field == 1:
                    if not c[1]:
                        c[1] = line
                elif field == 2:
                    if _vol(c[2])[0] in (None, vcmd):
                        c[2] = VOLCMDS[vcmd][0] + line
                elif not c[3] or c[3] == vcmd or (c[3] in VOL_SLIDES and slide):
                    if not slide or c[3] not in VOL_SLIDES:
                        c[3] = vcmd
                    if c[3] in TWO_NIBBLES:
                        c[4] = (lo[0] + _cdiv((lo[1] - lo[0]) * i + lo[2], distance)) & 15 | (
                            (hi[0] + _cdiv((hi[1] - hi[0]) * i + hi[2], distance)) & 15) << 4
                    else:
                        c[4] = line & 255
        for i, c in enumerate(W):
            old = rows[r0 + i][ch]
            if c != [old.note, old.instrument, old.volcmd, old.effect, old.param]:
                _write(out, r0 + i, ch, Cell(*c))
    return out


# AUTOMATE's targets: (effect number, None for the volume column; lowest; highest value)
TARGETS = {"Z": (26, 0, 0x7F), "X": (24, 0, 0xFF), "M": (13, 0, 0x40), "V": (22, 0, 0x80), "T": (20, 0x20, 0xFF),
           "v": (None, 0, 64)}
CURVES = ("linear", "scurve", "exp", "steps")


def automate(rows, chans, r0, r1, target, frm, to, shape="linear", every=1):
    """A curve from `frm` to `to` written as plain cells on rows r0..r1 of `chans`: `target` an absolute effect (Zxx
    cutoff or macro, Xxx pan, Mxx channel volume, Vxx global volume, Txx tempo) or the volume column `v`. A value every
    `every` rows from r0; LINEAR, SCURVE (smoothstep: slow at both ends) and EXP (equal ratios per row, 0 counted as 1)
    sample the curve at each written row and always write r1 with `to`; STEPS moves in equal steps, one per written row,
    the last at `to` (EVERY past the selection leaves one step: `frm`). Vxx and Txx are song-wide: only the first channel gets them. A cell holding another command in the
    target column is left alone and counted. Returns (cells, skipped)."""
    if target not in TARGETS:
        raise ValueError(f"automate targets {', '.join(t + ('NN' if t == 'v' else 'xx') for t in TARGETS)}")
    eff, lo, hi = TARGETS[target]
    if not (lo <= frm <= hi and lo <= to <= hi):
        f = (lambda v: f"{v:02X}") if eff else str
        raise ValueError(f"{target}: values {f(lo)}-{f(hi)}" + (" (T00-T1F are tempo slides)" if target == "T" else ""))
    if shape not in CURVES:
        raise ValueError(f"a shape is one of {', '.join(CURVES)}")
    if not 1 <= every <= 64:
        raise ValueError("EVERY is 1-64 rows")
    if r1 <= r0:
        raise ValueError("select at least two rows to automate")
    at = list(range(r0, r1 + 1, every))
    if shape != "steps" and at[-1] != r1:
        at.append(r1)

    def curve(t):
        if shape == "scurve":
            return frm + (to - frm) * t * t * (3 - 2 * t)
        if shape == "exp":
            a, b = max(frm, 1), max(to, 1)
            return a * (b / a) ** t
        return frm + (to - frm) * t

    out, skipped = [], 0
    for k, r in enumerate(at):
        t = k / max(1, len(at) - 1) if shape == "steps" else (r - r0) / (r1 - r0)
        v = frm if k == 0 else to if k == len(at) - 1 else min(hi, max(lo, int(curve(t) + 0.5)))
        for ch in chans[:1] if target in "TV" else chans:
            c = rows[r][ch]
            if eff is None:
                if c.volcmd is not None and c.volcmd > 64:
                    skipped += 1
                    continue
                new = Cell(c.note, c.instrument, v, c.effect, c.param)
            else:
                if c.effect and c.effect != eff:
                    skipped += 1
                    continue
                new = Cell(c.note, c.instrument, c.volcmd, eff, v)
            if new != c:
                _write(out, r, ch, new)
    return out, skipped


# ---------------------------------------------------------------- GROW and SHRINK (OpenMPT's, View_pat.cpp)

_EMPTY = (None, 0, None, 0, 0)


def _fields(cell):
    return [cell.note, cell.instrument, cell.volcmd, cell.effect, cell.param]


def _copy(dst, src, fields):
    """Fields 0 note, 1 instrument, 2 volume column, 3 effect with its parameter, from src to dst."""
    for f in fields:
        for k in ((3, 4) if f == 3 else (f,)):
            dst[k] = src[k]


def _changed(rows, W):
    out = []
    for (r, ch), c in sorted(W.items()):
        if c != _fields(rows[r][ch]):
            _write(out, r, ch, Cell(*c))
    return out


def grow(rows, cols, r0, r1):
    """OpenMPT's OnGrowSelection: rows r0..r1 of each (channel, fields) in `cols` spread two rows apart over twice the
    span, the rows between blanked (in the selected fields), overwriting what was there; a row whose new place falls past
    the pattern's end is dropped, and the row before that place keeps what it had (OpenMPT skips both). Returns (cells,
    the number of dropped rows that held something, the new last row)."""
    W, n, end = {}, r1 - r0 + 1, len(rows)

    def cell(r, ch):
        return W.setdefault((r, ch), _fields(rows[r][ch]))
    final, dropped = r0 + (n - 1) * 2, 0
    for row in range(final, r0, -2):
        src = r0 + (row - r0) // 2
        if row >= end:
            dropped += any(any(_fields(rows[src][ch])[k] != _EMPTY[k] for f in fs for k in ((3, 4) if f == 3 else (f,)))
                           for ch, fs in cols)
            continue
        for ch, fs in cols:
            _copy(cell(row, ch), cell(src, ch), fs)
            _copy(cell(row - 1, ch), _EMPTY, fs)
    return _changed(rows, W), dropped, min(final, end - 1)


def shrink(rows, cols, r0, r1):
    """OpenMPT's OnShrinkSelection: every second row of r0..r1 kept, packed into the first half of the span; a field left
    empty on a kept row takes the next row's (so what sat on the odd rows is not lost where there is room), the rest of
    the span cleared, in the selected fields of each (channel, fields) of `cols`. Returns (cells, the new last row)."""
    W, n, end = {}, r1 - r0 + 1, len(rows)

    def cell(r, ch):
        return W.setdefault((r, ch), _fields(rows[r][ch]))
    final = r0 + (n - 1) // 2
    for row in range(r0, r1 + 1):
        for ch, fs in cols:
            src = list(_EMPTY)
            if row <= final:
                at = r0 + (row - r0) * 2
                src = list(cell(at, ch))
                if at < end - 1:
                    nxt = cell(at + 1, ch)
                    for k in (0, 2):
                        if src[k] is None:
                            src[k] = nxt[k]
                    for k in (1, 3):
                        if not src[k]:
                            src[k] = nxt[k]
                            if k == 3:
                                src[4] = nxt[4]
            _copy(cell(row, ch), src, fs)
    return _changed(rows, W), final


# ---------------------------------------------------------------- ARP and STRUM (CHORD's), from the notes written

ARP_DIRECTIONS = ("up", "down", "updown", "downup", "random")


def _shape(shape):
    iv = CHORDS.get(shape) if isinstance(shape, str) else tuple(int(x) for x in shape)
    if not iv:
        raise ValueError(f"no chord '{shape}': {', '.join(CHORDS)}")
    return iv


def arp(rows, ch, r0, r1, shape, octaves=1, direction="up", every=1, gate=0, skip=0, seed=1, off_note=NOTE_OFF):
    """Each note on channel `ch`, rows r0..r1 (a chord's root, as the owner wrote it), played as an arpeggio of `shape`
    (a CHORDS name or semitones) over `octaves` octaves: a note every `every` rows from its row up to the row before the
    channel's next note, note-off, cut or fade (or r1); `direction` up, down, updown, downup (the turning notes once) or
    random; each step after the first left out with `skip` percent; `seed` makes random and skip the same every time.
    Every step keeps the root's instrument and volume, and an effect or volume already on its row; `gate` 1-15 cuts each
    note after that many ticks (SCx, where the effect column is free), `off` puts a note-off on the row after each note
    (`off_note`: === with instruments, ^^^ with samples only; where that row is free and no step falls on it). Notes
    past B-9 are left out of the shape."""
    iv = _shape(shape)
    if direction not in ARP_DIRECTIONS:
        raise ValueError(f"an arpeggio goes {', '.join(ARP_DIRECTIONS)}")
    if not 1 <= octaves <= 4 or not 1 <= every <= 64 or not 0 <= skip <= 100:
        raise ValueError("an arpeggio spans 1-4 octaves, a step every 1-64 rows, skips 0-100 %")
    if gate != "off" and not 0 <= int(gate) <= 15:
        raise ValueError("GATE is 0 (none), 1-15 ticks (SCx) or off (a note-off row)")
    cut = 0 if gate == "off" else int(gate)
    rng, out, last_ins = random.Random(seed), [], 0
    for r in range(0, r1 + 1):
        root = rows[r][ch]
        if root.instrument:
            last_ins = root.instrument
        if r < r0 or not _is_note(root.note):
            continue
        tones = sorted({root.note + x + 12 * o for o in range(octaves) for x in iv if root.note + x + 12 * o <= 119})
        rev = tones[::-1]
        seq = {"up": tones, "down": rev, "updown": tones + tones[-2:0:-1], "downup": rev + rev[-2:0:-1]}.get(direction)
        end = next((e for e in range(r + 1, r1 + 1) if rows[e][ch].note is not None), r1 + 1)
        steps = list(range(r, end, every))
        ins = root.instrument or last_ins
        vol = root.volcmd if root.volcmd is not None and root.volcmd <= 64 else None
        for k, s in enumerate(steps):
            if k and skip and rng.random() * 100 < skip:
                continue
            tone = rng.choice(tones) if seq is None else seq[k % len(seq)]
            c = rows[s][ch]
            eff, par = (c.effect, c.param) if c.effect or c.param else (S_EFFECT, 0xC0 | cut) if cut else (0, 0)
            new = Cell(tone, c.instrument or ins, c.volcmd if c.volcmd is not None else vol, eff, par)
            if new != c:
                _write(out, s, ch, new)
            o = s + 1
            if gate == "off" and o < end and o not in steps and rows[o][ch].is_empty():
                _write(out, o, ch, Cell(off_note))
    return out


def strum(rows, ch, r0, r1, size, ticks, speed, down=False):
    """STRUM: on each row of r0..r1 where channel `ch` strikes a note, the chord's voices there (`ch` and the channels
    to its right, `size` in all) delayed one after another by `ticks` (SDx), the leftmost (the lowest, as CHORD writes
    them) first, or the rightmost with `down`; a delay past 15 ticks or past the row (speed - 1) is held there and
    counted; a voice whose cell carries another effect is left undelayed and counted; 0 removes the delays. Returns
    (cells, skipped, held)."""
    if not 0 <= ticks <= 15:
        raise ValueError("STRUM is 0-15 ticks between voices")
    top, out, skipped, held = min(15, speed - 1), [], 0, 0
    for r in range(r0, r1 + 1):
        if not _is_note(rows[r][ch].note):
            continue
        voices = [c for c in range(ch, min(ch + size, len(rows[r]))) if _is_note(rows[r][c].note)]
        for k, v in enumerate(voices[::-1] if down else voices):
            t, c = k * ticks, rows[r][v]
            if t > top:
                t, held = top, held + 1
            if _is_delay(c) or not c.effect and not c.param:
                new = Cell(c.note, c.instrument, c.volcmd, S_EFFECT if t else 0, 0xD0 | t if t else 0)
                if new != c:
                    _write(out, r, v, new)
            elif t:
                skipped += 1
    return out, skipped, held


# ---------------------------------------------------------------- note lengths: FILL, SET LENGTH, CUT HERE, GLUE

def _is_end(n):
    return n is not None and n >= 120


def _sounding_before(rows, ch, r0):
    """Whether channel `ch` has a note sounding into row r0: the last note-field event above it is a note."""
    for r in range(r0 - 1, -1, -1):
        n = rows[r][ch].note
        if n is not None:
            return _is_note(n)
    return False


def _clear_note(out, rows, r, ch):
    c = rows[r][ch]
    _write(out, r, ch, Cell(None, 0, c.volcmd, c.effect, c.param))


def fill(rows, chans, r0, r1):
    """FILL (legato): on rows r0..r1 of `chans`, every note-off, cut or fade that lies between a note (also one sounding
    into the selection from above) and the next note is removed, so each note lasts until the next; its volume and
    effect stay. An end after the last note stays. Returns (cells, ends removed)."""
    out = []
    for ch in chans:
        sounding, pending = _sounding_before(rows, ch, r0), []
        for r in range(r0, r1 + 1):
            n = rows[r][ch].note
            if _is_end(n) and sounding:
                pending.append(r)
            elif _is_note(n):
                for e in pending:
                    _clear_note(out, rows, e, ch)
                sounding, pending = True, []
    return out, len(out)


def set_length(rows, chans, r0, r1, length, off_note=NOTE_OFF):
    """SET LENGTH: each note on rows r0..r1 of `chans` made `length` rows long: the note-off, cut or fade after it moved
    to `length` rows on (`off_note` where none was), its volume and effect left where they were. A note whose next note
    comes sooner keeps sounding to it; one whose end would fall past the pattern is left alone and counted. Returns
    (cells, skipped)."""
    if not 1 <= length <= 256:
        raise ValueError("a length is 1-256 rows")
    out, skipped, end = [], 0, len(rows)
    for ch in chans:
        for r in range(r0, r1 + 1):
            if not _is_note(rows[r][ch].note):
                continue
            t = r + length
            strike = next((s for s in range(r + 1, end) if _is_note(rows[s][ch].note)), end)
            if t >= end and strike == end:
                skipped += 1
                continue
            for e in range(r + 1, min(strike, end)):
                if e != t and _is_end(rows[e][ch].note):
                    _clear_note(out, rows, e, ch)
            if t < strike and rows[t][ch].note is None:
                c = rows[t][ch]
                _write(out, t, ch, Cell(off_note, 0, c.volcmd, c.effect, c.param))
    return out, skipped


def cut_here(rows, chans, row, off_note=NOTE_OFF):
    """CUT HERE: `off_note` on `row` of every channel of `chans` where a note is sounding into it and the row's note field
    is free. Returns cells."""
    out = []
    for ch in chans:
        c = rows[row][ch]
        if c.note is None and _sounding_before(rows, ch, row):
            _write(out, row, ch, Cell(off_note, c.instrument, c.volcmd, c.effect, c.param))
    return out


def glue(rows, chans, r0, r1):
    """GLUE: on rows r0..r1 of `chans`, a restrike of the note sounding before it (the same note, its own instrument or
    none, no volume and no effect: a restrike with either is an accent and stays), right after that note or right after
    its note-off, cut or fade, is removed with that end, so the notes become one. Returns (cells, restrikes removed)."""
    out, glued = [], 0
    for ch in chans:
        last = None  # (note, instrument) of the note sounding, through its end
        ins = 0
        for r in range(0, r1 + 1):
            c = rows[r][ch]
            if c.instrument:
                ins = c.instrument
            if _is_note(c.note):
                if (r >= r0 and last and last[0] == c.note and c.instrument in (0, last[1]) and c.volcmd is None
                        and not c.effect and not c.param):
                    _write(out, r, ch, Cell())
                    if last[2] is not None:
                        _clear_note(out, rows, last[2], ch)
                    glued += 1
                    last = (last[0], last[1], None)
                    continue
                last = (c.note, c.instrument or ins, None)
            elif _is_end(c.note):
                if last and last[2] is None and r >= r0:
                    last = (last[0], last[1], r)
                else:
                    last = None
    return out, glued
