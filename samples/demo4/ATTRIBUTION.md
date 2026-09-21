# Sources of the demo4 samples

| sample | source | license |
|---|---|---|
| riff | additive model designed from a description (a near-sine), `demo4/gen_samples.py` | generated |
| bass | additive model designed from a description (a sine over a low-passed sawtooth with a slow dip), `demo4/gen_samples.py` | generated |
| bed1, bed2 | Surge XT factory patch "Pads/Burden", E minor and G major voicings, `demo4/kit.yaml` | rendered audio; Surge XT is GPL-3, the renders are ours |
| motif1-3 | Surge XT factory patch "Plucks/Nolla", E add9, E7sus4 and Em9 voicings, `demo4/kit.yaml` | rendered audio |
| choir | Surge XT factory patch "Polysynths/Ahh Polly", an E minor add9 cluster, `demo4/kit.yaml` | rendered audio |
| break | one bar of breakbeat played by the CC0 Big Rusty Drums kit with a printed room (`demo4/gen_break.py`) | CC0 (Big Rusty Drums, Karoryfer Samples, https://shop.karoryfer.com/pages/free-samples) |

The drums are not in the repo: `demo4/drums.yaml` renders a Jomox Airbase 99 snare and an Alesis HR-16b open hat
from MusicRadar's royalty-free drum-machine pack into `samples/local/demo4/` (usable in music, not
redistributable), and the kick, ride and crashes are demo3's TR-8 renders in `samples/local/demo3/`; the CC0
cymbal swell and gong are in `samples/demo3/` (see `samples/demo3/ATTRIBUTION.md`). Don't publish
`demo4/vantage.it`, which embeds the drums. `PROVENANCE.md` records how these sounds relate to the demo's reference.
