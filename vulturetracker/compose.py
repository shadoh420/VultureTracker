"""Composition helpers for the Pattern tab's selection bar: pure functions over a compiled pattern's rows (rows[row][channel]
of model.Cell) that return the cells to write, as [{"row", "ch", "cell"}] with the cell in song notation. The app writes
them into the song text in place as one undo step (State.song_edit), so what they make is plain IT that the pattern view
shows and edits like any other cell:

- groove: a repeating per-row note delay (SDx), e.g. 0 2 swings every other row by two ticks;
- euclid: k hits spread as evenly as they go over n steps (Euclidean rhythm), rotated, each kept with a probability from
  a seed, so the same settings always write the same cells;
- chord: each note of a channel stacked into a chord over the channels to its right, note-offs copied so it ends whole;
- layers: instruments cycled note by note (round-robin), or chosen by each note's volume (velocity layers).
"""
import random

from .model import Cell
from .notation import format_cell

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
    if not ticks or not all(0 <= t < speed for t in ticks):
        raise ValueError(f"a groove is a list of tick delays, each 0-{speed - 1} (at speed {speed} a row has {speed} ticks)")
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


def euclid_steps(hits, steps, rotate=0):
    """`hits` onsets spread as evenly as they go over `steps` (the Euclidean rhythm, as Bresenham's line draws it: 3 over 8
    is x..x..x.), turned `rotate` steps to the left."""
    if not 0 <= hits <= steps or steps < 1:
        raise ValueError("a Euclidean rhythm has 1-64 steps and at most as many hits")
    return [((i + rotate) % steps * hits) % steps < hits for i in range(steps)]


def euclid(rows, ch, r0, r1, hits, steps, rotate=0, every=1, prob=100, seed=1):
    """Channel `ch`, rows r0..r1, made a Euclidean rhythm of the cell on row r0: a step every `every` rows, `hits` of each
    `steps` steps sounding (the rhythm repeats down the selection), each hit kept with `prob` percent from `seed` (the
    same settings write the same cells). Every other row of the selection is cleared."""
    template = rows[r0][ch]
    if template.note is None or template.note >= 120:
        raise ValueError("the rhythm plays the cell at the top of the selection: put a note there first")
    if not 1 <= every <= 64:
        raise ValueError("a step is 1-64 rows")
    pattern, rng, out = euclid_steps(hits, steps, rotate), random.Random(seed), []
    for r in range(r0, r1 + 1):
        on = (r - r0) % every == 0 and pattern[(r - r0) // every % steps]
        if on and prob < 100:
            on = rng.random() * 100 < prob
        want = template if on else Cell()
        c = rows[r][ch]
        if (c.note, c.instrument, c.volcmd, c.effect, c.param) != (want.note, want.instrument, want.volcmd, want.effect, want.param):
            _write(out, r, ch, want)
    return out


def chord(rows, ch, r0, r1, shape, inversion=0, nch=None):
    """Each note on channel `ch`, rows r0..r1, made the chord `shape` (a CHORDS name or a list of semitones) over `ch` and
    the channels to its right: the lowest tone stays on `ch` (moved up an octave for an inversion), each other tone goes
    one channel further right with the root cell's instrument (its last one, when the cell names none) and volume. A
    note-off, cut or fade on `ch` is copied across, so the chord ends as one. Cells there are overwritten."""
    iv = CHORDS.get(shape) if isinstance(shape, str) else tuple(int(x) for x in shape)
    if not iv:
        raise ValueError(f"no chord '{shape}': {', '.join(CHORDS)}")
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


def slice_rows(starts, rate, tempo, speed, ch=0, nch=1, max_rows=200):
    """Where slices that start at frames `starts` (ascending, of a WAV at `rate`) fall in a pattern played at `tempo` and
    `speed`, so that playing them in order keeps their original timing (Renoise's slices rendered to a phrase): the
    first on row 0, each on the row its start reaches and delayed by the ticks left over (SDx), rounded to the nearest
    tick (2.5 / tempo s). A slice that lands on a row already taken goes to the next channel to the right (up to `nch`).
    Returns (placed: [(slice index, row, ch, delay ticks)], rows the pattern needs, dropped: slice indices that did not
    fit: past `max_rows` or with every channel taken)."""
    tick = 2.5 / tempo
    placed, dropped, taken, last = [], [], {}, 0
    for k, s in enumerate(starts):
        t = round((s - starts[0]) / rate / tick)
        row, delay = divmod(t, speed)
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
