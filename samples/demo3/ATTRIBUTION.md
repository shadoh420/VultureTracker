# Sources of the demo3 samples

The WAVs here are rendered by `demo3/kit.yaml` (`python -m vulturetracker synth demo3/kit.yaml`).

| sample | source | license |
|---|---|---|
| bass | OB-Xd, bank "001 - Bass 1", program "Bass Round Bass" | rendered audio; OB-Xd is free (discoDSP) |
| lead | Dexed, cartridge "SynprezFM_02", voice "FmRhodes18", low-passed with chorus and reverb printed in | rendered audio |
| gate | OB-Xd, bank "008 - Pads and Strings 1", program "OBXD Strings", chord E-F#-B-E | rendered audio |
| strings | Dexed, cartridge "SynprezFM_21", voice "106STRINGS" | rendered audio; Dexed is GPL-3, SynprezFM cartridges ship with it |
| swell | VSCO 2 CE `Percussion/susCymb1-cresc-Short_v1.wav` | CC0 1.0 |
| gong | VSCO 2 CE `Percussion/gongHit_mf.wav` | CC0 1.0 |

- **OB-Xd** by discoDSP (after the Oberheim OB-X): https://github.com/reales/OB-Xd
- **Dexed** by Digital Suburban (after the Yamaha DX7), with the SynprezFM cartridges: https://github.com/asb2m10/dexed
- **VSCO 2: Community Edition** by Versilian Studios (Sam Gossner), CC0 1.0:
  https://vis.versilstudios.com/vsco-community.html, https://github.com/sgossner/VSCO-2-CE

The drums (`demo3/drums.yaml`) are Roland TR-8 hits from MusicRadar's free
[hardware drum machine samples](https://www.musicradar.com/music-tech/samples/sampleradar-493-free-hardware-drum-machine-samples).
They are royalty-free for use in music, but may not be redistributed, so they're rendered into `samples/local/`
(gitignored) and aren't in this repo. For the same reason, don't publish `demo3/undertow.it`, which embeds them.
