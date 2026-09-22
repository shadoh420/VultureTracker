# Sources of the Nadir samples

| sample | source | license |
|---|---|---|
| drone, pulse | additive models designed from a description (a sine with its octave and a low-passed sawtooth under it; a rounder sub), `suite/nadir/gen_samples.py` | generated |
| wind | a pink-noise loop under a breathing low-pass, `suite/nadir/gen_samples.py` | generated |
| kick, snare, ghost, side, hat, hatopen, ride, crash, tomlow, loop | Big Rusty Drums (Karoryfer Samples), mixed, filtered and given a printed room by `suite/nadir/gen_drums.py`; `loop` is one bar of breakbeat played by the kit at the song's tempo | CC0 (https://shop.karoryfer.com/pages/free-samples) |
| boom | Big Rusty kick and low tom struck together, in a printed room (`gen_drums.py`) | CC0 |
| revcrash | the crash above, reversed (`suite/nadir/kit.yaml`) | CC0 |
| strbed_g, strbed_bb, strbed_c, strings | VSCO 2 Community Edition cello, viola and violin sections (Versilian Studios), chords assembled from the nearest recorded notes with a printed room (root-and-fifth voicings since v5); `strings` is the violins that double the lead, low-passed at 5 kHz, `suite/nadir/gen_strings.py` | CC0 |
| beda_g, beda_c | Surge XT factory patch "Pads/Moody Statement", open G and open C voicings (root and fifth, v5) with chorus and a room, `suite/nadir/kit.yaml`; a shaped noise floor added by `gen_floor.py` | rendered audio; Surge XT is GPL-3, the renders are ours |
| bedb_bb, bedb_g | Surge XT factory patch "Pads/Distant", a Bb major seventh voicing (unused since v5) and an open G (v5), chorus and a room; noise floor | rendered audio |
| choir, choir_hi | Surge XT factory patch "Pads/Choir Pad Thing", a G D G call in a hall (v5 dropped the v4 cluster's E, v6 its A), at pitch and an octave up; noise floor | rendered audio |
| fin_arp_gentle (slot 24) | Surge XT factory patch "Polysynths/Gentle" at D-4, the user's tryout pick from `suite/nadir/cand3fin.yaml`, with chorus and a short room; noise floor. `arp` ("Leads/Cottage", v4) is unused | rendered audio |
| fin_seq_somewhere (slot 25, unused since v6) | Surge XT factory patch "Leads/Somewhere MW" at D-4, held and looped, in a long room; noise floor. `seq` ("Polysynths/Xpander 2", v4) is unused | rendered audio |
| fin_lead_owl_lp (slot 27) | Surge XT factory patch "Leads/Owl" at E-5, held and looped, low-passed, with chorus and a hall, the user's tryout pick from `cand3fin.yaml`; noise floor. `lead` ("Polysynths/Xpander 1", v4) is unused | rendered audio |
| riff | demo4's additive near-sine (`demo4/gen_samples.py`, `samples/demo4/riff.wav`) with a noise floor added by `gen_floor.py` | generated |

The cymbal swell the song also uses is `samples/demo3/swell.wav` (VSCO 2, CC0; see `samples/demo3/ATTRIBUTION.md`).
Everything here may be redistributed; `PROVENANCE.md` records what the piece takes from its reference group
(descriptions only).
