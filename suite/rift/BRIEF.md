# Rift (working title): the brief from Nether Animal

Step 0 of `suite/NEXT-PROMPT.md`. Reference: Nether Animal (Michiel van den Bos, Unreal Tournament 1999, `Nether.umx`).
Measured 2026-09-22 with `scratch/ut99-clean/`: `analyze.py`, `structure.py`, `perchannel.py` (every sample and every
channel soloed) and `pitch_grid.py` (as-played pitches, drum rows timed on the rendered audio). Raw output stays there
(`perchannel_Nether.txt`, `pitch_grid_Nether.txt`, `grid_Nether.txt`). Levels are per-channel power (L and R squared),
so the surround bed counts. These are measurements only: no audio, sample data or note sequence is taken, and nothing
here has been listened to.

## Grid

- Played: tempo 117 and speed 4, set on row 0 of the patterns (the header's 125/6 never plays). Row 85.5 ms, 4 rows per
  beat = 175.5 BPM, 16-row bar = 1.37 s, 64-row pattern = 4 bars = 5.47 s. One grid for all 55 patterns (37 distinct),
  5:01.
- Feel: drum & bass. The bar repeats strongest (16 rows 0.76, 8 rows 0.62, 4 rows 0.58): half-time weight over fast hats.

## Form (lengths in patterns, level = RMS of the pattern)

| Section | Len | Starts | What plays | dB |
|---|---|---|---|---|
| Intro | 4 | 0:00 | noise swell, a tonal hit every bar; the noise snare from the 2nd pattern, hats from the 3rd | -32 to -29 |
| Build | 6 | 0:22 | + kick, bass stab, crash; the surround bed joins for the last 4 | -25 to -22.5 |
| A | 8 | 0:55 | kick and bed out, the chopped break in; the sub joins for the last 4 | -22 to -20 |
| Break | 2 | 1:38 | break and hats out, the surround bed back; then the tonal hit and the bed alone | -24, -32 |
| B | 4 | 1:49 | sub, the lead, the surround bed, noise snare and hats; no break | -23 |
| Peak | 6 | 2:11 | A's groove + a second break loop + FX hits; the lead and a string chord in the last 4; sub and bed out | -19 to -18 |
| Break | 2 | 2:44 | the strings fade; then hats, lead, a low drone and the 16th sequence begin | -26, -28 |
| C | 17 | 2:55 | sub, drone, sequence, lead, a drum-riff loop + the second break, hats; a vocal pad and a second line in its 2nd half | -21, flat |
| Outro | 6 | 4:28 | drone and pad leave; sub, lead and sequence go in the last two; it ends on the drum loops, hats and crash, stepped down over its last bar (volume steps on rows 48-56), no fade-out of the whole | -22 to -29 |

Arc: steps up to the peak at 44-55 % of the song, then one long flat section. The tonal hit (intro to peak) and the noise
swell (every pattern in the intro, then every second one until early C) are the connective tissue; each section adds or
swaps one or two layers.

## Layers (as played; loudest first by active level, i.e. over the half-seconds where the layer sounds)

| Role | Sound | Idioms | Active dB |
|---|---|---|---|
| Bass stab | 0.46 s noisy low sample, ping-pong loop, C#2 (70 Hz) with a strong fifth; flatness -9 dB | rows 0 and 6 of the first bar (build, A) or of every bar (peak), cut fast (D0F) | -21.5 |
| Sub | a 0.16 s kick whose last cycle loops (a sustained boom), 77 Hz, pure (-40 dB) | 3 to 10 notes a pattern on two alternating channels, each fading (D02/D03) | -23.0 (loudest over the song, -26.6) |
| Chopped break | 1.2 s dull break, noise-like, -35 dB above 12 kHz | re-struck on rows 0, 2, 4, 6, 10, 12, 14, from its start or 29 % or 73 % in (its loudest hit); ghost repeats at a third | -23.7 |
| Kick | 0.31 s, 87 Hz | build only | -26.1 |
| Sequence | 1 s tone with a looped tail, pure (-48 dB), 387 Hz; B3 to E5 | a note on every row, each gliding into the next (GFF); copies on 2 channels +2 and +3 rows later at 1/6 and 1/3 volume; voices panned left, centre, right | -31.0 |
| Second break | 2.6 s break loop, lo-fi | row 0 every bar, row 6 in half | -31.2 |
| Strings | 4 s bowed chord sample, 2.6 s swell, looped, flatness -23 dB | a six-voice C# minor chord once per pattern, faded | -31.6 |
| Drum riff | half-bar recorded drum loop | re-struck on most even rows, often at an offset (its middle on 4, 10 and 12) | -32.2 |
| Drone | 6.3 s pad, 6.2 s swell, looped, pure (-46 dB), 282 Hz, a C# minor chord | one note per pattern | -32.6 |
| Second line | 5.5 s tone, ping-pong loop, 0.5 s attack, flatness -25 dB | quiet, echoed 3 rows later on another channel at about half | -33.3 |
| Lead | 5.6 s one-shot, 0.17 s attack, 3.9 s tail, pure (-48 dB), 320 Hz; G#3 to E5 | one bar of 8ths per pattern; each note repeated 4 and 8 rows later at 1/2 and 1/4 volume | -33.6 |
| Noise snare | 1 s noise swelling to its peak at 0.88 s (like a reversed hit) | row 4 every bar, echo on row 10 at a third | -33.7 |
| Vocal pad | 3.2 s breathy, unpitched, 2.5 s swell, looped | once per pattern | -34.9 |
| Noise swell | 5.1 s dark noise (366 Hz), 4.9 s tail | once per pattern | -35.0 |
| Surround bed | 3.6 s, 2 s swell, looped, very pure (-52 dB), 246 Hz, an open fifth C# G# | re-struck on row 4 of every bar; S91 surround (L/R -1.0), fine fades (DF1/DF2) | -35.3 |
| Tonal hit | 3.8 s pitched hit, partials 35-75 cents above the others' C# | every bar on row 0, started 0.09 s in (offset) | -35.4 |
| Crash | 1 s | 33 notes: row 0 of 28 orders, rows 8 and 16 of order 18, row 32 of 23, rows 48 and 56 of 54 | -35.5 |
| Hats | 1 s open hat, 6.3 kHz, volume 12 of 64 | every even row in 51 patterns | -41.0 |

- Order: low end (-22 to -24) > drums (-24 to -32) > tonal layers (-31 to -35) > hats (-41).
- Sample floors: the tonal samples carry -8 to -24 dB of noise between their partials (lead -18, sequence -12, drone -14,
  bed -19, strings -24), noisier than the -24 to -34 dB `gen_floor.py` gave Nadir; breaks and noises are dull.
- Channels: 16, all centred in the header; pan commands only nudge (S87-S89) except the sequence's (S84, S88, S8D).
  ch1 breaks, ch2/5 FX and the second line, ch3/4 lead and tonal hit, ch6 noise snare, ch7 hats, ch8 kick and second
  break, ch9 crash, ch10 bass stab and vocal, ch11 drone/bed/strings, ch12-14 the sequence and its two copies, ch15/16
  the sub and the lead, alternating.

## Harmony

- One root, C#: the bass stab, sub, drone, bed (open fifth) and strings (minor triad) all sit on it; lead, sequence and
  second line use C# natural-minor notes. The sub's other notes (B, G#, E, F#) pass inside the bar; it is on C# at
  rows 0, 16 and 32; the bass stab dips to A in two patterns of A; the last peak pattern has one walking fill.
  `analyze.py`: 1.0 root change per minute, 2 roots per 2-second window.
- Tuning: the samples sit 17-41 cents above A440 (the sub +29), so the piece sounds between C# and D, nearer C#.
  `features.md` says D minor because `analyze.py` folds tuning only at +-33 cents; the as-played peaks say C#.

## Drums in rows (16-row bar, 4 rows per beat)

- Hats: every even row, quiet, nearly throughout. Crash on row 0 of a pattern.
- Build: kick 0, 6, 14 (14 in every other bar); noise snare 4 with its echo on 10.
- A and peak: break hits on 0 and 6 every bar, 12 in 3 bars of 4, 2/4/10/14 in a quarter to a half; heard low-end hits
  on 0, 4, 6, 10, 12, none on 8 or 14.
- C: drum riff + second break; the strongest low-end rises on 0, 6, 14, then 12, 2, 8; mid-band on 0, 4, 10, then 12,
  14, 6.

## Mix

RMS -21.8 dB, peak 0.65, narrow (L/R 0.96): everything centred but the surround bed and the sequence's three voices.
Spectrum: sub 50 %, bass 26 %, low-mid 14 %, mid 3 %, high 6 %; centroid 591 Hz, flatness -7 dB (a noisy mix); 4.3
onsets per second.

## Distance: the change after Vantage

Vantage kept Foregone's exact grid (140/5, 64-row patterns), its layer plan and entry order, its cell idioms at their
rows (echo delays, fades, surround, offsets) and a root a semitone away; only the notes and sounds were its own. Below,
G marks a genre trait (many UT99 and drum & bass tracks share it; keeping it is not copying) and F one of Nether
Animal's fingerprints (keeping it moves toward a copy). My default: keep the G traits you pick, change every F trait.

1. G: drum & bass tempo, 4 rows per beat, half-time weight. F: exactly 175.5 BPM (117/4); suggested instead 165 (110/4).
2. G: sampled breaks chopped with sample offsets, quiet 8th hats, a crash on pattern starts.
3. F: the drum rows above (kick 0/6/14, snare 4 echoed on 10, the chop positions, the half-bar riff re-synced per beat).
4. G: the low end loudest, a kick-with-a-looped-cycle sub, a noisy bass stab.
5. G: one root with passing tones. F: C# tuned +30 cents, the dip to A; suggested instead A minor at A440.
6. G: pure tonal layers over noisy drums, noisy sample floors, one surround bed, a narrow mix.
7. F: the colour set (open-fifth surround bed, minor string chord at the peak, detuned hit every bar, gliding 16th
   sequence on three delayed channels panned apart, lead echoed at 4 and 8 rows). The sequence is a repeating
   figure; your rule allows one only when the reference has it, and this one does: keep or drop?
8. G: the arc (quiet intro, build, short break, peak before the middle, long flat last section, no fade).
   F: the lengths 4-6-8-2-4-6-2-17-6 and the entry points.
9. F: the echo settings (lead 4/8 rows at 1/2 and 1/4, sequence +2/+3 rows, snare +6 rows at a third).

Also yours to say: which roles the piece has (not necessarily all eighteen) and its length. Step 1 then builds two bars
of drums and sub on the grid you pick.

Decided 2026-09-22: every G trait kept; every F trait changed as suggested: tempo 110 speed 4 (165 BPM), A minor at A440,
our own drum rows, section lengths and echo settings, none of the colour set (so no 16th sequence). Roles and length
are still open.

Changed 2026-09-22 (evening): the F traits may now be followed (the owner's "follow the references" decision); the
notes and melodic cells stay ours. Tempo, key and our drum rows stay as decided.

## Layer plan (melodic and colour layers, from `scratch/ut99-clean/melodic_Nether.txt`)

Measured with `melodic.py` (lines.json "Nether") and checked independently against the cells, the WAVs and
`perchannel_Nether.txt`; the check's corrections are used below. "Under the sub" is active level against the sub's
(per-channel power, where each sounds). Nether runs in sample mode: no instruments or envelopes, so every movement
below is written in the pattern. Pitches are Nether's degrees over its C# root, mapped to our A.

| # | Layer | Nether's idioms | Under the sub | Sound class (samples as played) |
|---|---|---|---|---|
| 1 | Sequence | 8ths on every beat and offbeat, 8 a bar; one voice restarted on row 0 of each pattern, every other note a legato jump (GFF, 97 %); one volume, no accents, no offsets; a shared 4-note head with changing tails, 6 cells in 88 bars, no bar equals the one before, 93 % repeat an earlier one; 4ths/5ths 48 %, octaves 22 %; copies +2 rows at -15.6 dB and +3 rows at -9.5 dB, panned left 17, centre 34, right 55 (IT S8D; our header pan 56 renders the same L-R); orders 31-52 | 8.0 dB | near-pure short tone (1.0 s, looped 0.19 s from 0.80 s, stored at 23.6 kHz a low F2, played 18-35 semitones up; partials 2-10 under -40 dB); as played centroid 381 Hz, -53 dB above 5 kHz |
| 2 | Lead call | one call per 4 bars, in bar 1: 3 notes on 8ths from row 2 (5 or 7 in a few calls), alternating two channels, each note re-struck 4 and 8 rows later at -6.6 and -11.5 dB on its own channel (no pan change), the last cut on row 32; 5 call shapes in 31 calls; 3rds, 4ths/5ths and 8-12 st leaps; degrees b3, 4, 5 over the bass | 10.6 dB | long one-shot tone (5.6 s, fast attack, 5 s tail, stored at 4.2 kHz, played 4-24 up; vibrato 21 c at 2.1 Hz, floor -20 dB) |
| 3 | Tonal hit | one hit per bar on row 0, alternating two channels, started 2 % in (O09), one volume; pitched 43-85 cents above the root (between the root and the minor second), unsteady (31 c vibrato, 63 off-harmonic peaks); intro to the peak (orders 0-25) | 12.4 dB | pitched one-shot hit (3.8 s, noisy: floor -8.6 dB, jittering pitch) |
| 4 | Surround bed | two open fifths in surround (S91): the third (C-G for us) on row 4 of every bar, the root fifth (A-E) on row 0 once per pattern; row-by-row fades and dips (D slides); build and B | 12.3 dB | very pure looped fifth (3.6 s, 2 s swell, stored at 6.7 kHz) |
| 5 | Strings | a six-voice major-seventh chord on the minor sixth (F A C E for us) once per pattern on row 32, voices panned apart (S8x), faded out by D slides; the peak's last 4 patterns | 8.6 dB | bowed section chord (4 s, 2.6 s swell, looped, floor -24 dB) |
| 6 | Drone | a minor triad on the root, one attack with a written swell (v7 to v30 over 24 rows), then held by legato for 18 patterns; C and outro | 9.6 dB | slow swelling pad chord (6.3 s, looped, stored at 8.4 kHz) |
| 7 | Noise | one dark noise hit per pattern in the intro, then every second pattern; it decays (-30 dB), pan 38 | 12.0 dB | dark noise one-shot (5.1 s, centroid 384 Hz as played) |
| 8 | Vocal pad | a minor-triad vocal, two attacks swelling v5 to 23, held by legato; second half of C | 11.9 dB | breathy vocal chord (3.2 s, looped, floor -8 dB) |
| 9 | Second line | in bar 1 of odd patterns under the lead's call: 26 attacks, steps 61 %, echo +3 rows at -7.2 dB, same pan; orders 41-47 | 10.3 dB | soft long tone (5.5 s, ping-pong loop, stored at 9.4 kHz) |

Harmony over the whole: one root with the bass moving to the minor seventh and back (0.5-0.7 changes a bar under the
lead and sequence); colours on the minor third (bed), the minor sixth (strings), a near-minor-second (tonal hit).
Figures at once: the lead alone in orders 20-23 and 26-30, lead and sequence in 31-40 and 49-52, three (with the second
line) in bar 1 of 41, 43, 45, 47. Sample tuning sits 5-43 cents above A440 (the sequence +7).

Order for the loop: 1 (the figure the longest section is built on, with its copies), 2 (it plays with 1), then the
colours 3-5, then 6-9. Each goes into its own slot and channels, stopped for the owner's pick.

Already matching Nether in the current loop: the grid (4 rows a beat, 16-row bars), the low end loudest (sub -22.4 dB
active), a kick-with-a-looped-cycle sub on one root with a passing fifth, a noisy low stab, a chopped break, a crash on
the pattern start, one surround bed, centred drums. Departing from Nether in approved sounds (for the owner to decide;
nothing changed): the break sits 10.6 dB under the sub (Nether's chopped break 0.7 dB under), the stab 11.4 dB under
(Nether's 1.5 dB over), the hats 28.4 dB under (Nether's 18), the bed 7.9 dB under (Nether's 12.3) and a full minor
triad struck once per pattern (Nether's: two fifths, one re-struck every bar); the loop's spectrum is 76 % sub against
Nether's 50 %.

Corrections to the brief above, from the check: the sequence plays 8ths (not a note on every row: its copies fill the
odd rows); the strings chord is A C# E G# over C# (not C# minor); the bed sample is an F#-C# fifth that plays E-B on
row 4 of every bar and C#-G# once per pattern; the drone is one held sound, struck once and then restated by a GFF note on row 0 of every later pattern (see the
layer-6 correction); the lead has 3 written
notes per call (7 onsets with the re-strikes).
Correction from the layer-5 check (2026-09-22, late): the strings are two three-voice groups a pattern, one struck on
row 0 and one on row 32, each held 32 rows and faded from the other group's strike (D02, then D00 for 17-18 rows), all
six voices at one pan (S87, pan 29), the sample's own volume (22 of 24 strikes; the top voice of both groups at v40 in
one pattern); not one six-voice chord on row 32 with the voices panned apart. No group holds the major seventh itself; it
sounds where the groups overlap. Sample 17 sounds about 4 semitones below its written note (-3.7 st, the same pitch
class as +8): compare in sounding pitch. Kept departure in ours (the copyright guard's price): our voicing is spread
(group spans 16-17 semitones against their 7-9, six voices over 17 against 8-12), and two semitone pairs meet across
the groups (E-4/F-4, F-4/E-5) against their one.
Correction from the layer-6 check (2026-09-23): the drone's 18 notes carry one written pitch (counts from its cells):
one chord sample (a minor triad on the root) on row 0 of every pattern, struck in order 31 and restated with the
instrument by a legato note (GFF) in orders 32-48, never retriggered or moved. Its volume column: a v7 entry struck without G and swelled one step
a row to v30 over 24 rows, nine patterns at a flat v30, then (orders 41-48, with the vocal pad and the second line)
patterns alternating a v30 note row swelling to v40 over 16 rows with a v40 hold; pan 29; D02 then D00 to silence in
order 49. The layer plan's "held by legato for 18 patterns" stands; the handoff's "7 distinct cells" came from melodic.py
reading the chord's pitch on the render. Its sample's level movement: melodic.py reads 2.06 Hz with prominence 9.4 over
one loop, but on the loop's whole-cycle lines it is an irregular wander over 0.8-2.6 Hz, strongest at 1.3 Hz (1.28 Hz read
over the loop played twice), 1.43 dB between 0.6 and 3.2 Hz; band by band (100-300, 300-700, 700-2200 Hz) it spreads
2.22/1.75/0.97 dB, nearly uncorrelated (a timbre movement: melodic.py reads its centroid moving 24 Hz). Its level under the sub: 9.6 dB over the song (the plan's
figure), 8.7 in orders 41-48, 11.2 in the v30 holds, 10.5 by melodic.py's per-order median.
Correction from the layer-7 check (2026-09-23): the noise's 19 notes carry one written pitch (counts from its cells,
`rifttools/artic.py 1`): one note on row 0 of each struck pattern at the sample's own volume (no volume column, no
fades: the one-shot plays out; the plan's "it decays (-30 dB)" is the sample's own curve, not a written fade), S89
(pan 38) on every note's row, alone on row 0 of the pattern after a strike only in orders 7, 9, 34 and 38 (nothing in
the other unstruck patterns). It strikes every pattern in orders 0-6, every second pattern in 8-18 and 24-30 (none in
B, 20-23), every fourth in C (33, 37), then stops. It plays its sample 2 semitones under the stored rate. Its sample is not a
plain decaying hit: at its storage rate the 200 ms level stays within 6 dB of its peak for 1.4 s and falls 10/20/30 dB
at 2.9/4.6/5.0 s (a held noise with a late fade; melodic.py: 0/10 ms to -10/-3 dB, tail 4.94 s, slope -3.1 dB/s over
its steady part); it carries two resonances 16-20 dB over the noise around them, one on the key root as played; as
played (5.77 s, slower than stored) 25 % of its power lies under 104 Hz (-6.0 dB); its level movement over the held
part (to its first 10 dB fall, 2.9 s) is a flicker over a broad range of rates (0.3-20 Hz, 1.9-2.0 dB), melodic.py's 1.22 Hz tremolo reading being its
1.5 s window's; band by band (126-300, 300-700, 700-2200 Hz as stored, 50 ms levels averaged over block phases) it
spreads 3.0/1.3/1.5 dB, nearly uncorrelated (0.05/0.18/0.21), and 2.4/1.6/1.1 dB after the held part. Its first 0.4 s
are bright (centroid near 1 kHz, falling as its top darkens), half of melodic.py's 91 Hz centroid movement.

Correction from the layer-8 build (2026-09-23): the vocal pad's 8 notes carry one written pitch (counts from its cells,
`rifttools/artic.py 27`), and it plays its sample 11 semitones over the stored rate: the 3.22 s stored sample (a forward
loop of 2.175 s from 1.043 s) sounds 1.70 s with a 1.152 s loop, so the plan's "3.2 s" is the stored length. It is
struck on row 0 at v5 (no legato) in orders 41 and 45 and swelled one step a row to v23 over 16 rows (v13 and v22
skipped), restated by a legato note (GFF) at v23 on row 0 of the three patterns after each strike, pan 32 on every note,
faded by D01 then D00 to silence in order 49: the plan's "two attacks swelling v5 to 23, held by legato" stands. Its
sample (melodic.character at 8363 Hz with its loop): attack 129 / 675 ms (means 149.5 / 827.9 over the 83 block phases,
its peak inside the loop in every phase), aperiodicity 0.51, floor -7.9 dB, flatness -22.1 dB, centroid 290 Hz as stored
(547 scaled to as played; melodic's as-played reading of its solo render 556), -40 dB bandwidth 2234 Hz, level movement
1.83 dB (most of its power a fast flicker above 8 Hz; its slow part, 0.6-8 Hz, centred at 2.8 / 3.3 / 4.0 Hz as stored
in the 100-300 / 300-700 / 700-2200 Hz bands), slope +0.56 dB/s; its chord a minor triad on the key root, the lowest
tone on its drone's lowest as played; its tones' pitch moves (rifttools/tonevib.py at its own tones, the loop played
twice, as played) periodic 30 / 31 / 16 c at 3.5 / 2.5 / 5.2 Hz: a breathy chord that wobbles, not a steady pad.

Correction from the layer-9 build (2026-09-23, late): the second line's 58 notes are 32 on its main channel and 26 on an
echo channel (the plan's "26 attacks" is the echo's count; counts from its cells, `rifttools/artic.py 28`). It plays in
orders 41, 43, 45 and 47 (every second pattern), alternating two patterns: both open bar 1 with six notes on rows 0, 2, 4,
6, 10 and 14 at v16 (its sample's default volume), the second glided into (G54, done within a tick), the
sixth held and faded by the volume column from row 15 to silence on row 43; the fuller pattern (43, 47) glides the held
note on to a seventh on row 18 (G20, also done within a tick at its step, at v14, the fade's level there) and ends with a three-note pickup on
rows 58-62, faded out by the next pattern's first rows (DF2, then D00: silent by row 7); the echo repeats every note but
the pickup 3 rows later at v7 (v6 on the glide: -7.2 dB) with its own fade to silence on row 42; every note carries the
sample's number, so each plays at the sample's default pan, 32 (an S87 the row after a note moves it to 29 for that row
only: the line renders centred; melodic_Nether.txt's "pan 29" was read before melodic.py took a sample's default pan,
which Nether's samples 20, 22 and 28 have); no offsets, retriggers or vibrato effects; the patterns between carry only
the pickup's fade. Its sample: 5.477 s at 9387 Hz with a ping-pong loop of 2.664 s from 2.813 s to its end, sounding
D3+15c (scientific naming: 148.1 Hz, our A#3 in tracker naming once moved to our key) at its stored rate and played
6-18 semitones over it (median 13). Its 8-bit data carries a DC offset of -0.087 of full scale (13 % of its loop's
power) that melodic.py's
readings include: without it the centroid is 227 Hz (not 171), the level movement 3.61 dB (not 2.82) and the slope -1.78
dB/s (not -1.45); the rest stands: attack 0/10 ms (means over the 93 block phases 1.1/8.1 ms), a regular 2.17 Hz tremolo
(prominence 23.6), a 2.25 Hz vibrato of 7.7 c (prominence 7.1), a drift of -3.06 c/s through the loop (before the loop
its pitch wanders around the loop's median), floor -23.8 dB, flatness -25.3 dB,
-40/-60 dB bandwidths 2240/4694 Hz, partials falling about 6 dB each (odd over even +6.4 dB), harmonic; its loop starts
on a waveform peak and turns at its end mid-slope. Its level 10.3 dB under the sub (sample 28 soloed, both channels,
against sample 19) stands.
Correction from the layer-9 checks, rounds 1-3 (2026-09-24): before its loop the sample moves less than in it, and that
part is most of what our line's notes play (our 2-row notes play the first 0.31-0.41 s of our sample, 4-row notes
0.51-0.77 s). Read on a mean square under a Hann window three periods long (its nulls on every multiple of the tone's
frequency; melodic's 10 ms blocks beat with a tone whose period does not divide them: at the reference's pitch 0.2 dB
on a steady sine and 1.2-2.5 dB with neighbouring partials, at our A#3 1.0-1.4 dB, and a 20 ms Hann still 0.1-0.3 dB at
ours), DC off: the level's swing per tremolo cycle (the level less its 1 s mean, peak to peak) is 3.73/4.05/3.28/3.05/
3.05 dB in the five cycles from 0.05 s against 8.1 in its loop, stepping to 10.9 in the cycle from 2.32 s; the level's
range over its first 0.26/0.41/0.77 s (from 25 ms) is 1.07/2.12/3.52 dB: it falls about 1 dB by 0.1 s, then rises
about 3 dB to a crest at 0.54 s; its level falls 1.78 dB/s from 0.05 s to its loop start (a fitted line), as in its
loop; its pitch moves 1.8/3.0/6.6/5.1 c over 0-0.4/0.4-1.2/1.2-2.0/2.0-2.8 s against 8.3 in its loop. Its floor,
-23.83 dB, is -26.87 in the third-octave band holding its fundamental and -26.84 in the bands above it (its 8-bit noise,
white to its Nyquist), and it makes almost none of those readings: doubled, the pitch spans move at most 0.23 c and the
ranges and swings 0.06 dB over four noise draws. Its onset reaches -10 / -3 dB of its own settled level, the mean square over one whole
period centred at 25 ms, at 0.32 / 4.79 ms (means over the 93 block phases; a 10 ms block's level beats with the
waveform too: against its 10-20 ms block 0.32 / 4.90; against its loudest 10 ms block, its crest at 0.54 s, 1.07 /
8.10); its first three 2 ms blocks read -10.6/-7.5/-2.7 dB against its 10-20 ms level, but a 2 ms block reads the
waveform's phase at these pitches. `gen_second.py ref` prints its own readings (the onset against its settled level
and its loudest block, the three-period level readings, the 2 ms blocks); the onset against the 10-20 ms block, the
blocks' beat and the doubled floor come from the check rounds' scripts (samples/local/rift-cand/second/checks/
round3_generatorb/level_beat.py and onset_base.py, round4_generator/ref_floor.py).
