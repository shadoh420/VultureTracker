# Rift listening test: which dimension makes it sound like Nether Animal?

Six MP3s in this folder. v0 is Rift as it is. Each of v1-v5 changes one thing and keeps everything else exactly as
the song has it: your picked sounds, your faders, the notes. Play each against v0 and against Nether Animal in UT99.
The question is whether it still sounds like a trace of Nether. The places to check are the ones you named: the intro
(0:00-0:23) and the passage from about 2:55 (break 2 at 2:55, C at 3:06). Nothing here has been listened to by me. The
changes were checked by cell diffs and measurements only.

| File | What changes | Where to listen |
|---|---|---|
| `rift_v0_control.mp3` | nothing (the song; its module is byte-identical to rift.it) | intro 0:00, break 2 2:55, C 3:06 |
| `rift_v1_form.mp3` | **The form.** The same parts, laid out our own way. It opens on the drone and the vocal pad instead of the noise and the tonal hit. The drums and the sequence come in at 0:23. The hit and the bed are first heard in a short break at 1:10, with only the hats and then the noise. The lead enters at 1:21. The peak comes late (1:56), with the drums, sub, stab, strings, lead and sequence together. The strings close into a break with the second line at 2:20. A last section (2:31) has the lead and the second line over the drone, with no sequence. It ends on the drone with the hit (the noise and hats in its first bars) (3:06-3:24) instead of stepping the drums down. 3:24 long. | all of it: no passage sits where Nether's does |
| `rift_v2_layers.mp3` | **The layer set.** Five of Nether's roles are gone: the tonal hit, the noise swell, the strings, the vocal pad and the second line. The bed now carries the intro and the build's start (where the hit and noise were) and the peak (where the strings were). In C the drone carries the pad part alone. Same form, same idioms, same sounds. | intro 0:00 (the bed instead of hit + noise), peak 2:31, C 3:06 |
| `rift_v3_idioms.mp3` | **How each layer moves.** Our own articulation, not Nether's. The sequence: every note struck (no glides, no restart per pattern), one echo 6 rows (a dotted quarter) later, the main voice a little left and the echo a little right, instead of the two copies at +2 and +3 rows. The lead: no quiet re-strikes 4 and 8 rows later; one echo 6 rows later on the other channel. The hit: no sample offset, at v56, on beat 3 of bars 1 and 3 instead of on the downbeats. The noise: on the last bar, leading into the next pattern, without its pan command. The drone and vocal pad: no written swells (flat at v30 and v20, so the drone's v40 in 3:58-4:45 is gone). The second line: no glides, an echo 6 rows later. Side effects of these, measured: the hit about 1-3 dB quieter, the lead about 2 dB louder (echoes added, fades gone). Same form, layers, sounds and notes. | intro 0:00 (hit and noise), C 3:06 (sequence, lead) |
| `rift_v4_sounds.mp3` | **The sounds of three layers**, in classes Nether doesn't use for them. The sequence is a filtered saw instead of a near-pure tone. The lead is an electric-guitar pluck instead of a long tone. The hit is an in-tune synth tom, lower than the bell as a tom is, played from its start (the song's sample offset would cut off its attack). Levels matched on the part each plays: sequence and lead as the song's, the hit within about 1 dB (-36.0 against -34.8 and -36.5 dB). Only a test: your picks stay in the song. | intro 0:00 (the hit), C 3:06 (sequence and lead) |
| `rift_v5_groove.mp3` | **Tempo and groove.** 147 BPM instead of 165. The break is played about 2 semitones lower, tuned so its bar fills the slower bar exactly. The hats are on the offbeat 8ths only, at the on-beat hats' level (v16), so the hat channel is about 2 dB louder. Everything else as the song, so every time is 12 % later: break 2 at 3:16, C at 3:29. 5:59 long. | intro 0:00, C 3:29 |

Measured for reference (order by order against Nether, `scratch/ut99-clean/variants_likeness.txt`). The first figure
is the longest run of consecutive orders that follow Nether's orders closely. Two different UT99 tracks never share
more than 4. v0 20, v1 1, v2 19, v3 9, v4 20, v5 5. This measure hardly sees sound classes and doesn't see tempo
at all, so v4 and v5 are for your ear alone. v2 barely moved it (19). Your ear is the test for all of them.

What would help most, per file, in a word or a line: **still Nether / less / not Nether**, plus anything about
whether it still sounds like it belongs on the UT99 soundtrack. Everything is built by `make_variants.py` from
rift.yaml. The rift.yaml, rift_loop.yaml and generator files are untouched.

## Round 2: v2 with the sequence rewritten (from 3:00)

Your verdict on round 1: v2 liked, but from about 3:00 "that identical sequence from Nether"; the notes are the
problem, whatever plays them. These four are v2 exactly (every channel but the sequence's is cell for cell the same)
with the sequence section, 3:00 to about 5:08, rewritten from scratch. Nothing in them comes from the old sequence:
not its note on every 8th, not its short head repeated each bar, not its jumps of a fourth or fifth, not its range,
glides or echo copies. Each is one voice, your calliope sound, set to the old sequence's loudness (your faders still
decide).

| File | The new line |
|---|---|
| `rift_v2_seq_lament.mp3` | Slow and mostly stepwise: long notes (half notes, quarters, a held note to end each phrase) falling and rising around the upper A. It waits for the lead's call in the first bar of each pattern and answers it in the other three. An 8-bar phrase, then a varied repeat. |
| `rift_v2_seq_riff.mp3` | Low, in the bass register above the sub: a short-note syncopated riff (groups of 3, 3 and 2 sixteenths), narrow (A C D E G around the low A). A 2-bar figure with a turn every fourth bar. |
| `rift_v2_seq_pulse.mp3` | One note (E) pulsing in dotted 8ths, a rhythm that runs against the beat, stepping to its neighbours (D, C, G, A) in the last bar of each pattern. |
| `rift_v2_noseq.mp3` | The section without a sequence: the lead, the drone, sub and drums only. |

Measured, not heard: the section's level within 0.1 dB of v2 for the three lines (without the sequence 0.5 dB lower).
Clash rows over the song: v2 81, lament 52 (its B and passing notes against the drone's C), riff 0, pulse 0,
no sequence 0. Peaks 0.61-0.68. Nothing above 12 kHz beyond v2's level. The same question per file: **still Nether /
less / not Nether**, and does it belong.
