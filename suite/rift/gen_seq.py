"""Rift, layer 1 of BRIEF.md's layer plan: the sequence, written the way Nether Animal writes its sequence (measured with
scratch/ut99-clean/melodic.py and checked; only the idioms and the sample character are taken, the notes are ours).

`python suite/rift/gen_seq.py` makes the slot-8 candidates from the raw renders of seq.yaml (and a CC0 wine glass):
  - Nether's sequence sample as measured: a near-pure short tone, 0.99 s, looped over its last 0.19 s (17 whole cycles)
    from 0.80 s, stored at 23.6 kHz with its content under 1.4 kHz (-60 dB), stored low (F2) and played 18-35 semitones
    up, its floor 41.8 dB under the loop's power (between the partials, measured on the loop's exact line spectrum),
    no pitch or timbre movement.
  - So each candidate sounds E-3 (82.4 Hz) with its content under 1.5 kHz (played at most 36 semitones up, 8 times, it
    stays under 12 kHz: the bandwidth rule's 18 kHz and the hats' ceiling), cut to 0.99 s from its onset, looped over
    16 whole cycles from 0.80 s with a 30 ms crossfade and its level held flat through the loop, started at its -3 dB
    point (the reference's sample starts at full level: a slow attack dipped 8-21 dB at every restart), given a floor shaped
    like its own spectrum and periodic with the loop so that it sits 41.8 dB under the loop's power (a source already
    noisier keeps its own), levelled to one loop RMS (-15 dBFS) so the tryout compares timbre.
  - It is stored at 44.1 kHz, tuned by resampling: the compiler resamples any other rate to the song's 44.1 kHz and
    its resampler pads the sample's end with zeros, which puts a click on a loop that ends at the sample's end (found
    2026-09-22; vulturetracker/resample.py and song.py are unchanged). The low stored rate's effect, a narrow band, is
    kept by the low-pass.
`python suite/rift/gen_seq.py pattern` writes the figure into rift.yaml (channels 9-11, slot 8, instrument 8):
  - 8ths on every beat and offbeat, one voice restarted on row 0 of each pattern and moved legato (GFF) on every other
    note, one volume, no offsets. The reference's repetition: one four-note head (ours) opening every bar (and once on
    the minor seventh), three bars that stay and a fourth that changes from pattern to pattern (A B C D, A B C E; no bar
    equals the one before it, 2-bar units keep the rhythm and change the pitches); tails with octave leaps and a repeat.
  - Two copies on their own channels, +2 rows at -15.6 dB and +3 rows at -9.5 dB, panned left 17 (main), centre 34
    and right 56 (the reference's delays, levels and pans); a copy past row 63 lands at the top of the next pattern
    in the order list (the loop is a cycle: loop, loop_b), and each copy restarts on the first note it plays in a
    pattern (rows 0 and 1, as the reference's do), legato after that.
  - The level is set by the note volumes (faders stay at 64): the sequence 8 dB under the sub, as in the reference.
Channels 1-8 are not touched (7 and 8 are the silenced round-4 call).
Since Step 3 (the form) rift.yaml has no `loop`/`loop_b`: gen_form.py writes it from this writer's pattern
functions (figure(), or the form's variants beside it where there are any), and `pattern` stops there with a
message; pattern(path) still writes the loop song, rift_loop.yaml.
"""
import re
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "suite" / "nadir"))
from vulturetracker.resample import fir_filter, lowpass_fir, resample  # noqa: E402
from vulturetracker.wavload import read_wav, write_wav  # noqa: E402
from gen_floor import envelope_spectrum, shaped_noise  # noqa: E402

OUT = ROOT / "samples" / "local" / "rift-cand"
RAW = OUT / "seq" / "raw"
GLASS = ROOT / "tools/cc0/vcsl/Idiophones/Friction Idiophones/Wine Glasses/Releases/Fast/glass4_D5_Fast_1_Decay.wav"
RATE = 44100
ROOT_NOTE, F_ROOT = 40, 440 * 2 ** ((40 - 69) / 12)      # E-3 (the tracker's C-5 is 60, A-5 440 Hz): 82.41 Hz
SECS, LOOP_AT, LOOP_SECS = 0.99, 0.80, 0.19
CYCLES = 16
LOOP_LEN = round(CYCLES * RATE / F_ROOT)                  # 8562 frames: 16 whole cycles
F_LOOP = CYCLES * RATE / LOOP_LEN                         # the pitch those cycles give: E-3 +0.07 cents
BANDWIDTH = 1500.0
FLOOR_DB = -41.8                                          # Nether's sequence loop, measured the same way
LOOP_RMS_DB = -15.0

# candidate -> raw source (seq.yaml renders, or the glass): chosen for distinct partials within the near-pure class
CANDS = {
    "seq_theremin": "theremin",   # odd partials only (3rd -28 dB, 5th -42), the purest (own floor -65 dB, noise added)
    "seq_calliope": "calliope",   # FM pipe: odd partials (3rd -29 dB), own floor -44 dB (its 50 ms onset trimmed)
    "seq_sine": "sine",           # a plain sine with a 2nd partial at -23 dB (own floor -54 dB, noise added)
    "seq_ghost": "ghost",         # 2nd and 3rd partials at -27 and -20 dB, own floor -47 dB (its 270 ms onset trimmed)
    "seq_glass": "glass",         # a struck wine glass (VCSL, CC0), recorded: its strike and ring, stored 3 octaves and a 7th
}                                 # down; its own floor (-41.3 dB with the loop held flat) stays. Screened out: Butter and NuAgeDelys (floors -20 and
                                  # -19 dB, detuned voices beating in the loop), OB-Xd Horsehairs (a sub-octave), Circus 1 (odd
                                  # like the theremin, floor -35)


def f0_near(y, rate, guess):
    """The strongest peak within a semitone of `guess`, interpolated (Hann window, zero-padded)."""
    n = 1 << 20
    P = np.abs(np.fft.rfft(y * np.hanning(len(y)), n)) ** 2
    f = np.fft.rfftfreq(n, 1 / rate)
    sel = (f > guess * 2 ** (-1 / 12)) & (f < guess * 2 ** (1 / 12))
    k = int(np.argmax(P * sel))
    a, b, c = np.log(P[k - 1:k + 2] + 1e-30)
    return (k + 0.5 * (a - c) / (a - 2 * b + c)) * rate / n


def loop_floor(y, rate, f0):
    """dB of a loop's power that lies between its partials: the loop is one period of a periodic signal, so its DFT
    lines are multiples of rate/len; a line within 1.5 lines of a multiple of f0 is a partial."""
    P = np.abs(np.fft.rfft(y)) ** 2
    f = np.fft.rfftfreq(len(y), 1 / rate)
    k = f / f0
    harm = (np.abs(k - np.round(k)) * f0 < 1.5 * rate / len(y)) & (np.round(k) >= 1)
    return 10 * np.log10(P[1:][~harm[1:]].sum() / P[1:].sum() + 1e-30)


def source(name):
    """The raw tone at 44.1 kHz, sounding E-3, band-limited, from its -3 dB point."""
    if name == "glass":
        w = read_wav(GLASS)
        x = np.asarray(w.channels, float).mean(axis=0) / 2 ** (w.bits - 1)
        f0 = f0_near(x[int(0.2 * w.rate): int(0.7 * w.rate)], w.rate, 1174.7)  # named D5, it sounds D6 (1180 Hz measured)
    else:
        w = read_wav(RAW / f"{name}.wav")
        x = np.asarray(w.channels[0], float) / 2 ** (w.bits - 1)
        on = int(np.nonzero(np.abs(x) > np.abs(x).max() * 10 ** (-30 / 20))[0][0])
        f0 = f0_near(x[on + int(0.80 * w.rate): on + int(0.99 * w.rate)], w.rate, F_ROOT)
    x = resample(x, w.rate * F_LOOP / f0, RATE)                               # relabelled so it sounds F_LOOP, then stored
    x = fir_filter(x, lowpass_fir(BANDWIDTH / RATE))
    hop = RATE // 200                                                       # 5 ms RMS
    env = np.sqrt(np.convolve(x * x, np.ones(hop) / hop, mode="same"))
    onset = int(np.nonzero(env > env[:RATE].max() * 10 ** (-3 / 20))[0][0])  # from -3 dB of its first second's peak
    y = x[onset:].copy()
    y[:hop // 2] *= np.linspace(0, 1, hop // 2)                             # 2.5 ms in, so the cut does not click
    return y


def make(cand, name):
    x = source(name)
    start = round(LOOP_AT * RATE)
    f0, L = F_LOOP, LOOP_LEN
    end = start + L
    y = x[:end].copy()
    q = L // 8                                                              # 2 cycles at each end of the loop
    drift = 20 * np.log10(np.sqrt(np.mean(y[end - q:end] ** 2)) / np.sqrt(np.mean(y[start:start + q] ** 2)))
    y[start:end] *= 10 ** (-drift * np.linspace(0, 1, L) / 20)            # the loop's level held flat (the glass decays)
    x = np.concatenate([x[:start], y[start:end], x[end:]]) if drift else x
    C = round(0.03 * RATE)                                                  # the loop's last 30 ms blend into what precedes its start
    r = np.linspace(0, 1, C)
    y[end - C:end] = y[end - C:end] * (1 - r) + x[start - C:start] * r
    # the floor: noise shaped like the loop's own spectrum, periodic with the loop, following the level before it
    f, S = envelope_spectrum(np.tile(y[start:end], 8), RATE)
    burst = shaped_noise(L, RATE, f, S, seed=L)
    burst = fir_filter(np.tile(burst, 3), lowpass_fir(BANDWIDTH / RATE))[L:2 * L]
    noise = burst[(np.arange(end) - start) % L]
    hop = RATE // 100
    env = np.sqrt(np.convolve(y * y, np.ones(hop) / hop, mode="same"))
    loop_env = np.sqrt(np.mean(y[start:end] ** 2))
    noise[:start] *= np.minimum(env[:start] / loop_env, 1.5)
    noise *= loop_env / np.sqrt(np.mean(burst ** 2))
    own = loop_floor(y[start:end], RATE, f0)
    g_db = None
    if own < FLOOR_DB:
        lo, hi = -80.0, 0.0
        for _ in range(30):                                                 # the noise gain that puts the floor at FLOOR_DB
            g_db = (lo + hi) / 2
            z = y[start:end] + noise[start:end] * 10 ** (g_db / 20)
            lo, hi = (g_db, hi) if loop_floor(z, RATE, f0) < FLOOR_DB else (lo, g_db)
        y = y + noise * 10 ** (g_db / 20)
    floor = loop_floor(y[start:end], RATE, f0)
    y *= 10 ** (LOOP_RMS_DB / 20) / np.sqrt(np.mean(y[start:end] ** 2))
    peak = np.abs(y).max()
    if peak > 10 ** (-1 / 20):
        y *= 10 ** (-1 / 20) / peak
    f1 = f0_near(np.tile(y[start:end], 16), RATE, F_ROOT)
    pcm = np.clip(np.round(y * 32767), -32768, 32767).astype(int).tolist()
    write_wav(OUT / f"{cand}.wav", RATE, [pcm], 16, loop=(start, end, False), root_note=ROOT_NOTE)
    print(f"{cand:13s} <- {name:9s} {end / RATE:.3f} s at {RATE} Hz, loop {start}-{end} ({L / RATE:.3f} s, {CYCLES} cycles), "
          f"pitch {1200 * np.log2(f1 / F_ROOT):+.1f} c, loop level drift {drift:+.1f} dB flattened, own floor {own:.1f} dB"
          + (f", noise added at {g_db:+.1f} dB" if g_db is not None else ", no noise added") + f", floor now {floor:.1f} dB")


# ------------------------------------------------------------------------------------------------ the pattern

HALF = {"hA": ["E-5", "A-5", "D-6", "A-5"],                # the head (5 1 4 1 over A), and the same shape on G
        "hG": ["D-5", "G-5", "C-6", "G-5"],
        "t1": ["C-6", "G-5", "D-5", "D-6"],                # tails
        "t2": ["E-6", "B-5", "E-5", "B-4"],
        "t3": ["E-6", "E-5", "A-5", "G-5"],
        "d": ["A-4", "A-5", "G-5", "E-5"]}                 # the turnaround: octaves, landing on the head's first note
CELLS = {"A": HALF["hA"] + HALF["hG"], "B": HALF["hA"] + HALF["t1"], "C": HALF["hA"] + HALF["t3"],
         "D": HALF["hA"] + HALF["d"], "E": HALF["hA"] + HALF["t2"]}
BARS = {"loop": ["A", "B", "C", "D"], "loop_b": ["A", "B", "C", "E"]}   # three bars stay, the fourth changes
VOL = 36                                                     # the main voice (8.3 dB under the sub, as the reference's section)
COPIES = [(2, -15.6), (3, -9.5)]                             # v6 and v12 at v36
PATTERNS = ["loop", "loop_b"]
CHANNELS = """    - {name: Seq, pan: 17, volume: 64}
    - {name: Seq copy 2, pan: 34, volume: 64}
    - {name: Seq copy 3, pan: 56, volume: 64}
"""


def columns(variants, cycle=False):
    """Per entry of `variants` (a BARS key, or None where the sequence rests), per row: the cells of channels 9-11. A copy
    past row 63 lands at the top of the next entry (with `cycle`, the last entry's at the top of the first: the loop
    plays loop, loop_b, loop, ...; gen_form.py passes the form's orders); where the sequence stops, its three voices are
    cut on row 0 of the next entry and nothing spills there (the reference cuts its sequence so, its order 53)."""
    n = len(variants)
    notes = [[dict() for _ in range(3)] for _ in range(n)]
    for k, p in enumerate(variants):
        for b, cell in enumerate(BARS[p] if p else []):
            for i, note in enumerate(CELLS[cell]):
                r = 16 * b + 2 * i
                notes[k][0][r] = note
                for j, (d, _db) in enumerate(COPIES, start=1):
                    if r + d < 64:
                        notes[k][j][r + d] = note
                    elif (cycle or k + 1 < n) and variants[(k + 1) % n]:
                        notes[(k + 1) % n][j][r + d - 64] = note
    cols = [[dict() for _ in range(3)] for _ in range(n)]
    for k in range(n):
        for j, col in enumerate(notes[k]):
            v = round(VOL * 10 ** ((COPIES[j - 1][1] if j else 0) / 20))
            first = min(col, default=None)                     # each voice restarts on its first note in the pattern
            for r, note in col.items():
                cols[k][j][r] = f"{note} 08 v{v:02d}" if r == first else f"{note} .. ... GFF"
        if not variants[k] and (k or cycle) and variants[k - 1]:
            cols[k] = [{0: "^^^"} for _ in range(3)]
    return cols


def figure():
    """Per pattern, per row: the cells of channels 9-11 (the loop, a cycle)."""
    return dict(zip(PATTERNS, columns(PATTERNS, cycle=True)))


def ensure_channels(t, block, after):
    """The song text with each channel line of `block` kept where the song has it (its volume and pan are the owner's
    mix) and a missing one added after the line before it (the first after the channel line matching `after`; with
    neither there, the writer stops and names the line it cannot place)."""
    anchor = re.search(after, t)
    pos = anchor.end() if anchor else None
    for line in block.splitlines(keepends=True):
        name = re.search(r"name: ([^,}]+)", line).group(1)
        have = re.search(r"    - \{name: " + re.escape(name) + r",[^\n]*\n", t)
        if have:
            pos = have.end()
        else:
            if pos is None:
                who = re.search(r"name: ([^\[\\]+)", after)
                raise SystemExit(f"cannot place the channel line {line.strip()}: neither the line before it nor the "
                                 f"channel line {who.group(1) if who else after!r} is in the song")
            t = t[:pos] + line + t[pos:]
            pos += len(line)
    return t


def write_columns(t, first, cols):
    """The song text with columns `first`.. (0-based) of each row of the patterns in `cols` replaced by
    cols[pattern][j][row] ('...' where a row has none). The song's hand-written columns 1-8 keep their text byte for
    byte (a column 8 with no trailing space gets one); every generated column (9 on) keeps its cell and is padded to 14 characters, the last one unpadded, so each
    writer leaves the others' bytes as they were."""
    n = len(next(iter(cols.values())))
    out, pat, found = [], None, set()
    for line in t.split("\n"):
        m = re.match(r"  (\w+):$", line)
        if m:
            pat = m.group(1) if m.group(1) in cols else None
            found.add(pat)
        elif re.match(r"\S", line):
            pat = None
        row = re.match(r"\s+(\d\d): ", line)
        if pat and row:
            r = int(row.group(1))
            parts = line.split("|")
            parts += [" ... "] * (first - len(parts))
            keep = min(first, 8)
            new = ([c.strip() for c in parts[keep:first]] + [cols[pat][j].get(r, "...") for j in range(n)]
                   + [c.strip() for c in parts[first + n:]])
            head = "|".join(parts[:keep])                   # column 8's trailing spaces kept too
            line = head + ("" if head.endswith(" ") else " ") + "| " + " | ".join(f"{c:14s}" for c in new).rstrip()
        out.append(line)
    if not found - {None}:                                   # the full form: stop before the writer writes or reports
        raise SystemExit(f"the song has no {'/'.join(cols)} pattern: the full form is written by suite/rift/gen_form.py "
                         "(a writer's pattern(path) still writes the loop, rift_loop.yaml); nothing written")
    return "\n".join(out)


def pattern(path=HERE / "rift.yaml"):
    b = path.read_bytes()
    crlf = b"\r\n" in b
    t = b.decode("utf-8").replace("\r\n", "\n")
    t = ensure_channels(t, CHANNELS, r"    - \{name: Call echo[^\n]*\n")   # the owner's lines stay
    line8 = "  8: {file: ../../samples/local/rift-cand/seq_theremin.wav, base_note: E-3, loop: from_wav, name: seq_theremin}\n"
    if "\n  8: {file:" not in t:
        anchor = "\n\ninstruments:\n"
        assert t.count(anchor) == 1
        t = t.replace(anchor, "\n" + line8 + "\ninstruments:\n", 1)
    ins8 = "  8: {name: Seq, sample: 8}   # sample mode, as in the reference: no envelopes; the movement is in the pattern\n"
    if "\n  8: {name: Seq" not in t:
        anchor = "\n\npatterns:\n"
        assert t.count(anchor) == 1
        t = t.replace(anchor, "\n" + ins8 + "\npatterns:\n", 1)
    t = write_columns(t, 8, figure())
    if crlf:
        t = t.replace("\n", "\r\n")
    path.write_bytes(t.encode("utf-8"))
    print(f"wrote channels 9-11 into {path.name}: bars {BARS}, main v{VOL}, copies "
          + ", ".join(f"+{d} rows v{round(VOL * 10 ** (db / 20))}" for d, db in COPIES))


if __name__ == "__main__":
    if sys.argv[1:2] == ["pattern"]:
        pattern()
    else:
        for cand, name in CANDS.items():
            if not sys.argv[1:] or cand in sys.argv[1:]:
                make(cand, name)
