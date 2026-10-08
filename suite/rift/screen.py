"""Rift, step 2, the third call round: a timbre screen. One held note per patch (dry, mono, sounding C-5 = 262 Hz, the
middle of the call), measured for what the notes on the calls were about:
  h1     the fundamental's share of the harmonic power (the rejected leads were nearly sine: h1 near 1)
  n30    harmonics within 30 dB of the strongest (richness)
  hcent  power-weighted centroid in harmonic numbers
  mud    dB of the power under 500 Hz against 1-4 kHz (the muddy chord stab sat low with no presence)
  pres   dB of the power in 1-4 kHz against the total
  air    dB of the power above 4 kHz against the total (buzz)
  harm   the share of power on the harmonics (bells, detuned FM and noise sit off them)
  odd    dB of the odd harmonics (3, 5, ...) against the even ones (hollow, reedy > 0)
  atk    ms from the onset to -3 dB of the early peak (the swell was hated)
  sus    dB of the RMS 0.45-0.95 s after the onset against the early peak (plucks, bells, pianos decay)
  move   dB spread of the 50 ms RMS over the hold (tremolo, chorus beating)
  cents  pitch against A440 at the sounding root; oct: the key offset the patch needs to sound C-5
Nothing is kept but the numbers. Run: python suite/rift/screen.py > samples/local/rift-cand/call_screen.txt
  or: python suite/rift/screen.py --wav FILE...   (the same numbers for rendered WAVs, e.g. the earlier screens)
  or: python suite/rift/screen.py --part K/N [--after NAME] > ...   (every Nth patch from the Kth, to run N processes at
      once; --after resumes past NAME when a patch hangs the plugin host: add it to HUNG)
  or: python suite/rift/screen.py --motion LIST   (LIST: lines "key-offset<TAB>patch"; how each held note moves, after
      "doesn't feel dynamic enough": level, timbre and pitch motion over the hold, and how bright the attack is)
"""
import math
import re
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from vulturetracker.synth import Synths  # noqa: E402
from vulturetracker.wavload import read_wav  # noqa: E402

RATE = 44100
KEY = 60                                          # C-5 in tracker names, 261.63 Hz
SURGE = ("Leads", "Brass", "Polysynths", "Keys", "Winds")
THIRD = ("Leads", "Brass", "Strings", "Synths", "Polysynths", "Keys", "Winds", "Modelled")
OBXD = ("006", "007", "008", "009", "011", "012")
# the owner's exclusions and roles that are not a call: bells, plucks, squares, flutes, saws, gongs, rolls, voices, keys
# that decay, chords, drums, basses, FX
NO = re.compile(r"bell|pluck|pizz|square|\bsq|saw|flute|flutil|whistl|ocarin|recorder|piccolo|pipe|gong|timp|roll|choir|"
                r"vox|voice|vocal|harp|guitar|gtr|banjo|piano|pno|marimb|vibe|xylo|glock|celest|chime|kalimb|music ?box|"
                r"clav|accord|bagpipe|calliope|arp|seq|chord|drone|fx|noise|sweep|riser|bass|kick|drum|perc|hit|organ|"
                r"dulcimer|santoor|psaltery|koto|sitar|steel|mallet|init|blank|default|tuba|contra|e\.?p\b|\bep\b|rhodes", re.I)


HUNG = {"3rdparty/Kinsey Dulcet/Keys/Symphonies Under My Fingertips", "3rdparty/LinnStrument MPE/Strings/Bowed String",
        "3rdparty/Luna/Brass/Wavetable Brass", "3rdparty/Slowboat/Leads/Lost Lead"}   # the plugin host never returned from these


def chosen(names):
    for n in names:
        parts = n.split("/")
        if n.startswith("obxd:"):
            ok = n[5:8] in OBXD
        elif n.startswith("dexed:"):
            ok = True
        elif n.startswith("3rdparty/"):
            ok = len(parts) > 3 and parts[2] in THIRD
        else:
            ok = parts[0] in SURGE
        if ok and not NO.search(parts[-1]) and n not in HUNG:
            yield n


def features(x, rate=RATE, want=261.63):
    """x: mono float. Returns a dict (see the docstring) or None when there is no steady pitched note."""
    hop = rate // 100
    n = len(x) // hop
    env = np.sqrt((x[: n * hop] ** 2).reshape(n, hop).mean(axis=1)) + 1e-12
    on = int(np.argmax(env > env.max() * 10 ** (-40 / 20)))
    pk = env[on: on + 60].max()
    atk = 10 * int(np.argmax(env[on:] >= pk * 10 ** (-3 / 20)))
    sus = 20 * math.log10(np.sqrt(np.mean(env[on + 45: on + 95] ** 2)) / pk) if on + 95 <= n else -99.0
    hold = 20 * np.log10(env[on + 25: on + 105])
    move = float(np.std(np.convolve(hold, np.ones(5) / 5, mode="valid"))) if len(hold) > 10 else 0.0
    seg = x[(on + 25) * hop: (on + 105) * hop]
    if len(seg) < rate // 4:
        return None
    N = 1 << 18
    P = np.abs(np.fft.rfft(seg * np.hanning(len(seg)), N)) ** 2
    f = np.fft.rfftfreq(N, 1 / rate)
    cs = np.concatenate([[0.0], np.cumsum(P)])

    def band(lo, hi):                                  # power from lo to hi Hz
        return cs[min(len(P), int(hi * N / rate))] - cs[int(lo * N / rate)]

    def comb(f0):                                      # each harmonic's power within 1.5 % of it, up to 10 kHz
        return np.array([band(k * f0 * 0.985, k * f0 * 1.015) for k in range(1, int(10000 / f0) + 1)])

    total = band(60, 10000) + 1e-30
    top = P[(f > 60) & (f < 10000)].max()

    def peak(fk):                                      # a clear partial at fk: 10 dB over the median of +-5 %, -40 dB of the top
        i0, i1 = int(fk * 0.95 * N / rate), int(fk * 1.05 * N / rate) + 1
        near = P[int(fk * 0.99 * N / rate): int(fk * 1.01 * N / rate) + 1].max()
        return near > 10 * np.median(P[i0:i1]) and near > 1e-4 * top

    # the key is known, so the note sounds a C: per octave the best f0 within 45 cents; the note is the lowest octave with
    # clear partials at two of its odd multiples 1, 3, 5, 7 (a formant or a weak fundamental does not move it up)
    best = []
    for base in (want / 2, want, want * 2):
        grid = base * 2 ** (np.linspace(-45, 45, 61) / 1200)
        s = [comb(g).sum() for g in grid]
        best.append((grid[int(np.argmax(s))], max(s)))
    if max(c for _, c in best) < 0.5 * total:          # half the power off any C comb: noise or another pitch
        return None
    f0 = next((g for g, _ in best[:2] if sum(peak(k * g) for k in (1, 3, 5, 7)) >= 2), best[2][0])
    H = comb(f0)
    k = int(np.argmax(H)) + 1                          # refine on the strongest harmonic
    sel = np.nonzero((f > k * f0 * 0.985) & (f < k * f0 * 1.015))[0]
    i = sel[np.argmax(P[sel])]
    a, b, c = np.log(P[i - 1: i + 2] + 1e-30)
    f0 = (i + 0.5 * (a - c) / (a - 2 * b + c)) * rate / N / k
    ks = np.arange(1, int(10000 / f0) + 1)
    H = comb(f0)
    hs = H.sum() + 1e-30

    def db(sel):
        return 10 * math.log10(P[sel].sum() / total + 1e-12)

    semis = 12 * math.log2(f0 / want)
    return {"h1": H[0] / hs, "n30": int((H >= H.max() * 1e-3).sum()), "hcent": float((ks * H).sum() / hs),
            "mud": 10 * math.log10((P[(f > 60) & (f < 500)].sum() + 1e-30) / (P[(f >= 1000) & (f < 4000)].sum() + 1e-30)),
            "pres": db((f >= 1000) & (f < 4000)), "air": db((f >= 4000) & (f < 10000)), "harm": hs / total,
            "odd": 10 * math.log10((H[2::2].sum() + 1e-30) / (H[1::2].sum() + 1e-30)), "atk": atk, "sus": sus,
            "move": move, "semis": semis, "f0": f0}


def motion(x, rate=RATE, f0=261.63):
    """How a held note moves, from 30 ms frames every 10 ms over 0.15-1.0 s after the onset: `lvl` the spread of the
    level (dB), `tmb` the spread of the spectral centroid (semitones), `vib` the spread of the pitch (cents, on the
    strongest of the first four partials), `bite` the centroid of the first 60 ms against the hold's (octaves; above 0
    a bright attack that darkens, below 0 one that opens)."""
    hop, win, N = rate // 100, int(0.03 * rate), 1 << 14
    e = np.sqrt(np.convolve(x * x, np.ones(hop) / hop, mode="same"))
    on = int(np.argmax(e > e.max() * 0.01))
    f = np.fft.rfftfreq(N, 1 / rate)
    band = (f > 100) & (f < 8000)

    def spec(a, n):
        seg = x[a: a + n]
        return np.abs(np.fft.rfft(seg * np.hanning(len(seg)), N)) ** 2

    def cen(P):
        return (f[band] * P[band]).sum() / (P[band].sum() + 1e-30)

    starts = range(on + int(0.15 * rate), on + int(1.0 * rate) - win, hop)
    Ps = [spec(a, win) for a in starts]
    whole = sum(Ps)
    k = max(range(1, 5), key=lambda h: whole[(f > h * f0 * 0.94) & (f < h * f0 * 1.06)].max())
    sel = np.nonzero((f > k * f0 * 0.94) & (f < k * f0 * 1.06))[0]
    lv, cn, pc = [], [], []
    for P in Ps:
        lv.append(10 * np.log10(P[band].sum() + 1e-30))
        cn.append(12 * np.log2(cen(P)))
        i = sel[np.argmax(P[sel])]
        a, b, c = np.log(P[i - 1: i + 2] + 1e-30)
        pc.append(1200 * np.log2((i + 0.5 * (a - c) / (a - 2 * b + c)) * rate / N / (k * f0)))
    bite = np.log2(cen(spec(on, int(0.06 * rate))) / cen(whole))
    return {"lvl": float(np.std(lv)), "tmb": float(np.std(cn)), "vib": float(np.std(pc)), "bite": float(bite)}


def line(name, m, oct_=0):
    cents = 100 * (m["semis"] - round(m["semis"]))
    return (f"{m['h1']:5.2f} {m['n30']:3d} {m['hcent']:5.1f} {m['mud']:6.1f} {m['pres']:6.1f} {m['air']:6.1f} "
            f"{m['harm']:5.2f} {m['odd']:6.1f} {m['atk']:4d} {m['sus']:6.1f} {m['move']:5.2f} {cents:+5.0f} {oct_:+4d}  {name}")


HEAD = f"{'h1':>5} {'n30':>3} {'hcent':>5} {'mud':>6} {'pres':>6} {'air':>6} {'harm':>5} {'odd':>6} {'atk':>4} {'sus':>6} {'move':>5} {'cents':>5} {'oct':>4}  name"


def main():
    if sys.argv[1:2] == ["--wav"]:
        print(HEAD)
        for p in sys.argv[2:]:
            w = read_wav(p)
            x = np.mean([np.asarray(c, float) for c in w.channels], axis=0) / 32768
            m = features(x, w.rate, 440 * 2 ** ((w.root - 69) / 12))
            print(line(Path(p).stem, m) if m else f"{'unpitched or no steady note':>60}  {Path(p).stem}")
        return
    s = Synths(RATE)
    if sys.argv[1:2] == ["--motion"]:
        print(f"{'lvl':>5} {'tmb':>5} {'vib':>5} {'bite':>5}  oct  name")
        for ln in Path(sys.argv[2]).read_text(encoding="utf-8").splitlines():
            oct_, name = ln.split("\t")
            try:
                s.load(name)
                x = s.render([(KEY + int(oct_), 100, 0.0, 1.2)], 1.6).astype(float).mean(axis=0)
                m = motion(x / np.abs(x).max())
                print(f"{m['lvl']:5.2f} {m['tmb']:5.2f} {m['vib']:5.1f} {m['bite']:+5.2f} {int(oct_):+4d}  {name}", flush=True)
            except Exception as e:  # noqa: BLE001
                print(f"{'error ' + type(e).__name__:>24}  {name}", flush=True)
        return
    names = list(chosen(sorted(s.patches)))
    if sys.argv[1:2] == ["--part"]:
        k, parts = map(int, sys.argv[2].split("/"))
        names = names[k::parts]
        if "--after" in sys.argv:
            names = names[names.index(sys.argv[sys.argv.index("--after") + 1]) + 1:]
    print(f"# {len(names)} patches, key C-5 held 1.2 s, velocity 100, dry, mono", flush=True)
    print(HEAD, flush=True)
    for name in names:
        try:
            s.load(name)
            oct_ = 0
            for _ in range(2):
                x = s.render([(KEY + oct_, 100, 0.0, 1.2)], 1.6).astype(float).mean(axis=0)
                if not np.abs(x).max():
                    raise ValueError("silent")
                m = features(x / np.abs(x).max())
                if not m or abs(m["semis"] - round(m["semis"])) > 0.4 or round(m["semis"]) not in (-12, 0, 12):
                    m = None
                    break
                if round(m["semis"]) == 0:
                    break
                oct_ -= round(m["semis"])                  # sounds an octave off: play the key that sounds C-5
            if m and round(m["semis"]):
                m = None
            print(line(name, m, oct_) if m else f"{'-':>60}  {name}", flush=True)
        except Exception as e:  # a patch that fails to load or render is only a missing row
            print(f"{'error ' + type(e).__name__:>60}  {name}", flush=True)


if __name__ == "__main__":
    main()
