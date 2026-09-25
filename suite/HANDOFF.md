# Suite handoff (2026-09-24, Nadir v6 = the last pass; Rift: nine layers picked, the full form laid out)

The compact resume authority for the UT99 tribute suite, the anti-aliasing work and the mixer GUI. Read this first; the
other docs (README, GUIDE, SONG_FORMAT, SAMPLING, PROVENANCE) hold the durable rules.

## Goal

One original VultureTracker piece per stylistic group of the Unreal Tournament (1999) soundtrack: "synthesized"
from each group's character, inspired by it, never copying audio, sample data or melodic cells (PROVENANCE.md
wording: "inspired by", never "based on"). The first piece, Nadir (the dark group), is at v5, built from the user's
first twelve listening notes (the notes tool in the GUI is how feedback arrives now); their six v5 notes made v6, which
they asked to be the last pass: "we went in the wrong direction by trying to combine too many songs in one". The
group-per-piece plan is dropped; the next pieces follow one reference track each (`suite/NEXT-PROMPT.md`).

## Where things are

- `scratch/ut99-clean/` (gitignored, (c) Epic, local only): the pristine modules (`modules/`), `analyze.py`
  (features of all 30 modules -> `features.json`/`features.md`), `structure.py` (per-channel idioms and form),
  `GROUPS.md` (the five groups and why), `compare.py` (a built module against a group's ranges, soloed channel
  levels, energy above 12 kHz, RMS/peak per order), `ltas_peaks.py` (low-end peaks with note names),
  `spectrogram.py in.wav out.png` (view it to check the high range is empty).
- `suite/nadir/`: `nadir.yaml` (the song; everything after `patterns:` is generated), `gen_patterns.py` (form, cells,
  volumes, the melody), `gen_samples.py` (additive drone and pulse, pink-noise wind), `gen_drums.py` (CC0 Big Rusty
  hits, a boom, a 16-row breakbeat bar), `gen_strings.py` (CC0 VSCO 2 string-section chord beds and the violins that
  double the lead, low-passed at 5 kHz), `kit.yaml` (Surge XT beds, choir, the arp, the sequence voice and the lead,
  with rooms and chorus; `synth kit.yaml --only NAME` renders one entry), `gen_floor.py` (adds a shaped noise floor to
  synth samples; not idempotent, pass names after re-rendering a subset), `cand.yaml`/`cand2.yaml`/`cand3.yaml` +
  `measure.py` (candidate sounds and their measurements), `cand3fin.yaml` (the finalists of the v4 rework rendered at
  the song's roots with loops, floors added; they sit in `samples/local/nadir-cand3/fin/` and were the tryout
  candidates for slots 24, 25 and 27; those lists were cleared on 2026-09-22 13:00 once the choices were written, the
  ratings stay in `nadir.tryout.json`). Samples in `samples/nadir/`
  (ATTRIBUTION.md there).
- Build: `python suite/nadir/gen_patterns.py && python -m vulturetracker build suite/nadir/nadir.yaml --render
  suite/nadir/nadir.wav`, then `python scratch/ut99-clean/compare.py suite/nadir/nadir.it Skyward Seeker Seeker2
  Enigma Colossus Nether Mech8`. MP3 for listening: ffmpeg from imageio-ffmpeg (`python -c "import imageio_ffmpeg;
  print(imageio_ffmpeg.get_ffmpeg_exe())"`), 192k -> `suite/nadir/nadir.mp3` (gitignored, as are the .it and .wav).
- Recipe lesson: `root_offset: -12` labels the file's root as note - 12 while playing `note`, so an octave-shifted
  patch must be played an octave above the wanted root (`note: E-6, root_offset: -12` gives a root of E-5 that sounds
  E-5). `measure.py`'s pitch column must equal the root.
- The program is committed and released (0.2.0, see Package changes); the suite, `samples/nadir/` and the suite
  paragraphs of GUIDE/README/PROVENANCE are not committed (content, not the program; the user decides). Package
  changes pass `python -m unittest tests.test_gui tests.test_pipeline tests.test_resample` (30 tests). The user decides commits ("let's commit"); never `git add -A`.

## The groups (details in scratch/ut99-clean/GROUPS.md)

1 Deep drift: Skyward Fire, Seeker, Seeker 2, Enigma, Colossus, Nether Animal, Mechanism Eight. 2 Dream drive:
Foregone Destruction, Run, Botpack 9, Botpack 10, Mission Landing, Phantom. 3 Machine floor: Go Down, Lock, Three
Wheels Turning, Underworld II, Into the Darkness, Organic. 4 Firefight: Cannonade, SuperFist, Save Me, Firebreath,
Razorback. 5 Ceremony: UT Title, UT Menu, Room of Champions, Ending, The Course.

## Nadir as it stands (v6, the last pass, built 2026-09-22 13:22, not yet heard)

34 patterns, 3:47, one pedal (G Dorian) throughout, 20 channels (Seq and Seq echo empty). From the six v5 notes:
- The dotted sequence line is gone everywhere ("I don't like anything SEQ or SEQ echo plays"; every seq finalist
  rejected); a3/a4 carry the melody's phrases 0/1, so the melody runs a2-a6 in alternation; p2/p4/p9 keep theirs.
- The B section has no arp figure under the riff ("still hate the arpeggio" at b4, b6); b5 keeps the melody over
  the riff, b6 the choir call. Its groove plays the closed hat (05) on the ride's rows ("the drums sound like a rock
  song too much" at b2): the one drum change, 32 rows per pattern, instrument column only.
- The breakdown is on G like the rest and three patterns instead of five ("weird and out of place", "prog rock
  nonsense"): beds and the choir; the melody over a dotted pulse; the build with hats, the snare roll and the riser
  (its drums equal the old c5's). p10's 16ths use the first arp figure (the second is retired).
- One change beyond the proposal, from the after-measurement: the choir call is G D G. Its ninth (A) sat a semitone
  from the riff's and the melody's Bb on 38-41 % of the rows of b6, p5 and p7; re-rendered from kit.yaml
  (`synth --only "choir*"` + `gen_floor.py choir choir_hi`), same register as before (the patch sounds an octave under
  its label, as in v5).
- Measurements (nothing heard): `harmony.py --v5` 7 % clash rows of 2304 (v5) -> 7 % of 2176 after the arrangement
  changes alone (the sequence's share was small) -> 3 % with the choir change; what remains is the melody's hanging
  A or its F against the riff's Bb or E (b3, b5, p5-p8, 11-16 % of their rows) and the arp's E under the melody's F
  (i4, a5, p1, p3, o1, 3-5 %). Drum cell diff against the v5 copy: 28 shared patterns identical, b2-b6 hats 07 -> 05
  only, new c3 = old c5, c4/c5 gone. compare.py against the dark group: inside for RMS (-21.9 dB), peak 0.888,
  correlation 0.90, width, dynamics, onsets 3.98/s, pulse clarity 0.858, harmonic motion, playing channels 11.9;
  flagged as in v5: rolloff 587 Hz (max 484), low-mid 34.7 % and mid 7.8 % HIGH, sub 29.8 % (min 32.6) and bass
  25.5 % (min 25.8) LOW, flatness -18.9 dB LOW, and root changes 0/min against the group's 0.9-12.9 (one pedal by
  design). Soloed active levels: Lead -25.5, Drone -28.8, Bed A -30.3, Riff -30.3, Arp -30.7, Kick -31.5, String
  bed -32.5, Choir -34.6, Loop -34.7, Snare -35.5, Bed B -35.8, Perc -37.4, Hats -38.0, Riff echo -40.1, Pulse -40.3,
  Violins -40.8, FX -41.7, Wind -42.2 dB; every channel below -58 dB above 12 kHz; the spectrogram is empty above the
  drums' ceiling. Levels untouched for the faders. WAV and MP3 rendered 13:22.
- Files: `gen_patterns.py` (v6 docstring and layout), `kit.yaml` (choir chords), `harmony.py` (the v5/v6 choir
  voicing), `nadir.yaml` header (v6 paragraph), PROVENANCE's Nadir line (one pedal, no sequence line). The app archives
  the six v5 notes to `nadir.notes-17ebaf5e.*` when it next opens the song; the v5 ratings are quoted under What the
  user said.

## Nadir v5 (built 2026-09-22 12:15; heard, six notes)

Tempo 120 speed 5 (144 BPM, 16-row bars, 64-row patterns, 36 patterns, 4:00, loops to order 4), 20 channels. Two
pedals: G Dorian everywhere but the C Mixolydian breakdown (v4 had the B section on Bb major). The drums are v4's
row for row except the intro hats (i3, i4: closed hats on the offbeat 8ths, centred, v30, no sweep), verified by a
cell diff against a v4 copy. Everything v5 changed came from the notes report (`nadir.notes.md`, 12 notes at 11:30):
- The sustained layers hold root and fifth only: beda_g and bedb_g G-2 D-3 G-3 D-4 (Surge "Moody Statement" /
  "Distant"), beda_c C-3 G-3 C-4 G-4, the string beds G-3 D-4 G-4 D-5 and C-4 G-4 C-5 G-5 (VSCO), the choir call
  G-3 D-4 A-4 G-4 (no E). The v4 voicings (G minor add9, C ninth, Gm7 add9, the G A D E G cluster) held A next to
  Bb and E next to F inside the pads. `suite/nadir/harmony.py` (per order: pitch classes stacked per row, rows with a
  semitone or major seventh between any two sounding notes, notes ringing at once on the fade instruments; `--v5`
  selects the open voicings) measured a clash on 95 % of all rows in v4 and 7 % in v5, the remainder being passing
  notes (the riff's and arp's Bb against the choir's ninth at the peaks).
- No line stacks its own notes: seq fadeout 16 -> 160 (a note rang 12.8 rows, now 1.3), lead 24 -> 96 (8.5 -> 2.1),
  violins 12 -> 64 (17.1 -> 3.2); the sequence has no echo (channel 13 is silent).
- The B section (b1-b6) stays on G: the G riff cells, the second arp figure (G2) at v24 instead of the Bb arp at v18,
  bed B at v24 instead of v30, the G string bed; b1 and b2 keep the texture the user liked.
- i4's arp v26 -> v34 (their TOO QUIET at 0:24). Slots as the user wrote them in the tryout: 24 fin_arp_gentle,
  25 fin_seq_somewhere, 27 fin_lead_owl_lp.
- compare.py against the dark group: inside for RMS, dynamics, onsets (4.2/s), pulse clarity (0.84 at 144 BPM),
  harmonic motion and playing channels; still HIGH for rolloff (587 Hz vs max 484; v4 700), low-mid (33 % vs 21) and
  mid (7.7 % vs 4.7; v4 10), LOW for sub (29 % vs min 33) and flatness (-18.2 vs -16.5). Soloed levels: Lead
  -25.6 dB, Drone -28.8, Seq -29.6, Bed A -30.3, Riff -30.3, Arp -31.1, Kick -31.5, String bed -32.4, Loop -34.7,
  Choir -35.0, Snare -35.5, Bed B -35.8, Perc -37.3, Hats -37.8, Riff echo -40.1, Pulse -40.4, Violins -40.8, FX
  -41.8, Wind -42.2; peak 0.89, no order clips; every channel below -58 dB above 12 kHz. Levels were left for the
  user's faders. WAV and MP3 rendered at 12:15; the spectrogram is empty above the drums' ceiling.
- Nothing was heard: every claim above is a measurement or a cell diff.
- The twelve v4 notes now live in `suite/nadir/nadir.notes-e440c7c6.json` and `.md` (the app archives notes made
  against another song text when it sees a new one); `nadir.notes.json` is empty for v5.

## What the user said (the rules)

- v1: "relaxed/downtempo, could work for a menu track, not regular gameplay"; after 2:00 "like some NES/N64 music".
- v2: "the melody that comes in around 0:19/0:20 is very quiet", "volumes are all over the place", "around 0:47-0:50
  it just becomes a jumbled mess... the drums are good but the rest is not".
- v3: "Sounds way better." But 0:19/0:20 "the sounds that come in here are pretty anemic" (the arp 8ths and the violin
  line: that sample took 3.5 s to reach its peak while its notes lasted 1-2 s, and it was low-passed at 3 kHz);
  "the volume mixing is still pretty bad, I think a better solution to this is fixing up/altering the GUI program so I
  can collaborate better since you can't actually listen"; 0:40/0:41 "I absolutely hate whatever sound the instrument
  is that starts up around here" (the dotted sequence in the Uni 1 detuned-saw tone); stopped at 1:15: "the drums
  continue to be good, the melody/instrumentation continues to leave much to be desired".
- v4 (late evening, after the MP3): "I'm still not happy with it" (no specifics given); "I think we need a
  software/GUI solution (to let us collaborate better/more easily)"; wants to refine the piece later. Read this as: the
  chat loop (they listen, describe in words, I guess) is the bottleneck; the next thing to build is the tool that lets
  them show me what they hear and decide, before more Nadir sound changes.
- After v4, on the tool: they picked option 1 (listening notes) from four designs (notes; a per-section mixer in the
  arrangement grid written back as pattern edits; a finalist pass per role; a version journal), with the ratings in
  the report and a version stamp per note. First GUI use: the tryout SOLO (the raw WAV) read as a drone and clashed
  with the overview's channel solo (now SAMPLE ALONE + SOLO IN SONG); slots with candidates were invisible in the slot
  list (now marked). They had not done the tryouts or moved a fader yet. Asked what MIDI is (answered: a tracker song
  is note events like MIDI but the `.it` carries its samples; `synth` drives the plugins with MIDI to render samples).
- First notes through the tool (2026-09-22, 11:30-11:40, `suite/nadir/nadir.notes.md`, 12 notes, all while playing
  a candidate with WHOLE SONG): they wrote three slots with `U` (24 fin_arp_gentle, four stars, every other arp
  rejected; 25 fin_seq_somewhere; 27 fin_lead_owl_lp; most other leads and sequences rejected), which rebuilt the
  `.it` (the WAV/MP3 beside it are still the 03:29 v4 render). The notes: intro hats "too similar to Vantage" (0:13);
  the arp TOO QUIET at 0:24; "one of the synth drones that is going on here sounds bad" (0:37, a2: Pulse, Drone,
  Bed A, String bed sounding); "a bit discordant" (0:44, a3); "whatever arpeggio is happening here, I do not like"
  (0:52, a4: Arp plus Seq/Seq echo sounding, so the dotted sequence is the likelier culprit); "slightly better"
  (0:58); "the sounds clash too much, the drones don't seem to match what's going on in the rest of the song at
  times" (1:15, p2) and "atonal chaos again" (1:19); "I like this little break" (1:43, b1); "ok but now it just sounds
  too different" (1:57, b3); "too ambient all of a sudden, tone shifted too much, we aren't making prog rock" (2:12,
  b5); "better" (2:56, p5). Reading: the pedal/colour changes (Bb-major B section, C-Mixolydian breakdown and the
  peaks' clusters) read as clashes and a tone shift, the B section is too ambient, and one bed or the pulse sounds
  wrong to them; the drums stay approved. They said go (with "commit and push and update the release"); v5 above.
- Tool feedback after that first use (all fixed in round 2): no drag seeking; SOLO IN SONG "sometimes does not work"
  (the old render kept playing behind a long queue); rejected candidates should sink; "slot 24" was looked for in
  the stems rail (channels, 20 rows) so the stems now show the slot name; they could not tell which drone was playing
  (now the live SOUNDING strip).
- Second round of tool feedback (after v5 was built, before they heard it): the released 0.2.0 exe still turned the
  song file CRLF on U/WRITE MIX (fixed in 3d25497, shipped in 0.2.1); the v4 notes lingered in the NOTES tab and the
  last-note strip ("these should be cleared after each revision": now archived per song version); a solo from the
  SOUNDING strip landed too late for quick passages (now rewinds a second when the render lands); a speed control
  (SPEED, 100 to 20 %, pitch kept). All in 0.2.1. They want these sorted before more Nadir work and asked for a
  continuation prompt (the context was large).
- Third round (2026-09-22 13:00, sent with the v5 notes): the pattern rail could not be expanded enough ("the vertical
  scroll"), so it is its own tab; the finalists were still listed after the choices had been written; only the NOTE
  button is wanted in the bar; the 0.2.1 release notes showed "â†’" for "→". All in round 5 (Package changes).
- On the v6 proposal (2026-09-22 13:15): "Go ahead but let's make this the last pass for Nadir, I think we went in
  the wrong direction by trying to combine too many songs in one"; they want tracks that could have fit in with the
  other UT99 music and asked for a better prompt to get there (`suite/NEXT-PROMPT.md`). The ride-or-hat question went
  unanswered, so the proposal's default (the hat) stands; the release-notes edit still waits for an explicit yes.
- The v5 tryout ratings, for the record: every seq finalist rejected (fin_seq_retro, separate, slowpoly, somewhere,
  xpander2; mks70 unrated), every lead finalist rejected (etwas, oberheim, owl, violini, xpander, xpander_lp) but
  fin_lead_owl_lp (current, unrated) and fin_lead_generic (unrated), fin_arp_gentle four stars, the other arps rejected.
- Standing taste: dark, subdued, dream-like; no bell, pluck, pizzicato, square, flute or buzzy saw leads; no
  orchestral rolls or gongs; gameplay drive (a kick pattern, 8th hats, motion) even when dark; the drums as built are
  approved and stay; one moving line at a time; melody and kick at the top of the balance, drone under.
- From the user's friend L. Spiro (audio veteran): oversample, anti-alias, keep the high range empty. Done.

## Package changes (uncommitted)

- Anti-aliasing (earlier today): `vulturetracker/resample.py` (windowed-sinc `resample`, `lowpass_fir`, `fir_filter`,
  `resample_pcm`); `LoadedModule.render(oversample=2)`; `api.render(oversample=)`, CLI `render --oversample`; song
  `module: sample_rate: 44100` resamples every sample at compile time; rule: no note plays a sample more than about
  seven semitones above its root. Docs: SONG_FORMAT, GUIDE, SAMPLING. Test: `tests/test_resample.py`.
- The mixer GUI (this session, the user's request so they can balance by ear):
  - `song.py` memoises each file's resampling on its stamp (`_RESAMPLED`), so a Nadir compile drops from 7 s to 0.3 s
    after the first; `api.tryout_song` accepts a song dict.
  - `gui.py`: the tryout section is compiled once per candidate (`State.compiled_it`, `ckey`); mutes, solo and the mix
    are patched into the compiled module's header before each render (`patch_it`: channel volumes 0x80.., pans 0x40..,
    the disable bit, mix volume 0x31, sample global volume via the sample-header table), so a fader move costs one
    0.4 s render; `channel_levels` measures every channel soloed the way `compare.py` does (worker job "meters",
    re-measured after every change, ~1 s for Nadir); the song's own render (no candidate) is queued first and plays
    when nothing is picked; `_prune` keeps the newest 60 cache WAVs; the unwritten mix lives in `<song>.tryout.json`
    under `mix` (`volume`, `pan`, `mix_volume`, `sample_volume`, string keys); `mix_text`/`_edit_text` write it into
    the YAML in place (channel lines and sample lines keep their alignment: only the values change; `mix_volume` is
    replaced or inserted after `module:`; anything not found falls back to a whole-file re-dump and the diff says
    so); `EXPORT STEMS` compiles once and patches per channel. Routes: GET `/api/mixdiff`, POST `mix`, `applymix`.
  - `gui.html`: the stems rail is a mixer (MIX VOL master with the peak of what is playing, VOL/PAN faders and a meter
    per channel, WRITE MIX → SONG (diff modal), RESET MIX, UNMUTE), a GAIN fader per slot in the slot table, a SONG
    button in the player; a fader move keeps the old render playing until the new one lands and keeps the position;
    meters shown between passes are the last pass scaled by the fader ratio.
  - Tests: `tests/test_gui.py` (header patching, meters, in-place writes, worker drained in tearDown). GUIDE updated.
  - Verified in a real WebView2 window with a pywebview harness (start the server headless: `python -m vulturetracker
    gui suite/nadir/nadir.yaml --no-browser --port 8765`, then `webview.create_window` on that URL + `evaluate_js`
    + `ImageGrab` of the client rect; drone fader 30 -> 16 moved its meter by the expected 4.1 dB with the master at
    96, the diff showed exactly the edited lines, playback continued across the re-render).
- Listening notes (this session): `gui.py` `sounding(mod, order, row)` (each channel's last note cell at or before the
  row, back through up to 8 earlier orders unless a note-off/cut/fade came after it: sample through the keymap, note,
  rows ago, the order it started in, loop flag), `State.add_note/edit_note/save_notes/report`, `<song>.notes.json` +
  `<song>.notes.md` beside the song, routes POST `note`/`noteedit`, snapshot fields `notes`, `notes_path`, `version`
  (sha1[:8] of the text + mtime), `cand_counts`. `gui.html`: the tag bar under the player (`addNote`, `noteRow`, chips
  `toggleCh`, key `N`), the NOTES tab, SAMPLE ALONE (was SOLO) + SOLO IN SONG (`soloSlot`: mutes every channel that
  never plays the slot through the mute list, so candidates render the same way; second click unmutes), the slot
  dropdown/table marks. Tests `test_sounding`, `test_notes_file_and_report`. Verified in the real WebView2 window
  (two notes dropped while the song played at ord 3-6, a chip and words saved, the NOTES tab, the marks, 19 channels
  muted by SOLO IN SONG and unmuted by the second click); the harness notes were deleted afterwards and the song file
  was never written. Harness pitfall: `window.S` is undefined (top-level `let`), poll bare `S`; `.click()` on the
  page's buttons and an input's `value` + `dispatchEvent(new Event('change'))` work through `evaluate_js`.
- Round 2 (same day): `gui.py` `sounding_table(mod, facts)` replaces the backward scan (one forward pass over the
  playable orders carrying each channel's last note; dropped at a note-off and, for one-shots, once the sample's
  length has played at the order's row rate), `State.sounding/sounding_rows`, GET `/api/sounding/<order>` (per row
  `[ch, sample, looped]`); the job queue is a `PriorityQueue` (`_put`: builds 0, the wanted candidate 1, the song 2,
  other candidates 3, meters 4), POST `want` (`set_want`: the page's pick, its queued render re-put at 1),
  `channel_levels(cancel=)` so a stale meters pass stops between channels. Timings (Nadir, whole song): render 3.1 s
  at 2x, 0.44 s at 1x (a meters pass is 20 of those); a 4-order section renders in 0.35 s. `gui.html`: the SOUNDING
  strip under the progress bar (`renderLive`, chips = channel + slot, `~` held, muted dimmed, click = `soloCh`),
  `seekDrag` (click or drag), `visible()` puts rejected last, `pick` posts `want`, the stems' sample column shows
  `24 fin_arp_gentle`, the player says "re-rendering, the old mix plays until it lands". Tests: `test_sounding`
  rewritten for the table, `test_want_and_priorities`. Round 3: a note without an instrument keeps the channel's last instrument (the Riff
  slide targets showed `??`), and notes made against the current song text get their sounding lists recomputed when
  the table is rebuilt (`_rescan_notes`); the user's 12 notes were rescanned.
- Committed and released (this session, on the user's word): dc35517 (anti-aliasing, the mixer, the notes, the tests,
  the demo-video tool; GUIDE/README staged without their suite paragraphs), 18d14e2 "Version 0.2.0" + tag v0.2.0 +
  GitHub release "VultureTracker 0.2.0" with `dist/vulturetracker.exe` (34 MB, SHA256 522e564b..., smoke-tested
  headless on demo2: the bundled page has the notes bar, SOUNDING and SOLO IN SONG), then 3d25497: the song file
  keeps its line endings when the app writes it (`Path.write_text` had turned nadir.yaml CRLF on the first apply;
  `write_song` writes bytes with the file's convention; the test fixture is written in binary). The exe on the
  0.2.0 release predates 3d25497.
- Round 4 and 0.2.1 (same day): notes belong to the version of the song text they were made against
  (`_archive_old_notes` on `reload()` when the song changed outside the app: the old notes move to
  `<song>.notes-<hash>.json` + `.md`; `reload(archive=False)` for the app's own writes; the report is rewritten on
  every reload so its header and version labels follow the song text; snapshot `archives`); a solo or mute while
  playing sets `landAt` = click time - 1 s and the next render starts there when it lands (`markLanding` in muteCh,
  soloCh, resetStems, soloSlot; applied at `loadedmetadata`); SPEED (`setSpeed`: `defaultPlaybackRate` +
  `playbackRate` + `preservesPitch`, remembered in localStorage; a source change resets playbackRate to the default,
  hence both). Verified in the real window (notes 0 with the archive listed, speed 0.5 kept across a candidate
  switch, click at 2.15 s resumed at 1.15 s soloed). Commits 0a665b5 and a68ff8c "Version 0.2.1", tag v0.2.1,
  GitHub release 0.2.1 (exe 34 MB, SHA256 ccd46979..., smoke-tested headless), 31 GUI/pipeline/resample tests.
- Round 5 (2026-09-22 13:00, uncommitted, not released): the pattern view is its own PATTERN tab, the whole window wide
  (it was a 340 px rail in the overview where 3 of 20 channels fit and the handle stopped at 820 px; `tab('pattern')`
  re-renders it, the playhead follows there); the notes bar keeps only NOTE… (`N`) (the tag buttons went unused: every
  note came as NOTE with words; the row no longer shows a tag chip; the server still stores whatever tag it is sent);
  `State.apply` drops the slot's candidate list once the song is written (the choice is made; ratings stay keyed by
  file), and the finalist lists for 24/25/27 were cleared from `nadir.tryout.json` by hand, since the v4 writes had
  left them (the report's ratings section is gone with them; the ratings are quoted under Next steps). GUIDE.md
  follows. 31 tests; verified in the real WebView2 window (tabs, one tag button, 11 active channels fitting, a note
  by `addNote()` then deleted, the notes file byte-identical). The 0.2.1 GitHub release body starts with a UTF-8 BOM
  and shows "â†’" for "→" (the notes file went through a PowerShell 5.1 read as ANSI and a write as UTF-8 with BOM;
  0.2.0's body is clean); a corrected body is ready for `gh release edit v0.2.1 --notes-file`, on the user's word.
  Write release notes with Python or the editor as UTF-8 without BOM and check `gh api
  repos/shadoh420/VultureTracker/releases/tags/vX --jq .body` afterwards.

- Instrument panel (2026-09-22 evening, uncommitted, not released; the user's pick of option B over sample effects):
  `gui.py` `voice_of(ins)` / `voice_entry(ins, edit)` translate an instrument line into the panel's params and back
  (attack, decay, sustain, release = fadeout, cutoff, resonance, sweep from/to in 64ths of the cutoff and its ticks,
  random volume; an envelope of another shape is `custom` and kept until one of its sliders moves); the edits live in
  the unwritten mix under `instrument` (set_mix drops values equal to the song's), are applied in `compiled_it` (part of
  `ckey`), recorded with notes and written by WRITE MIX through `_edit_text(instruments=)` (the instrument's flow line
  re-dumped, its comment kept); the snapshot's `voice` lists the instruments that play the slot through `sample:`.
  `gui.html`: the INSTRUMENT panel under SLOT (foldable, a curve of the volume envelope and the sweep, labels in ticks
  and ms, dB, % and an approximate kHz, RESET and WRITE), the tryout's left column scrolls. Measured before building:
  libopenmpt's cutoff 40/60/80/100/120 puts the -6 dB point near 0.8/1.3/2.1/3.4/5.8 kHz (127 = off), the filter
  envelope scales the cutoff by (value + 32) / 64, resonance 40/80/120 peaks +6/+12.5/+16 dB. Tests 33 (two new:
  `test_voice_params`, `test_instrument_panel_compile_and_write`); verified in the real WebView2 window on a copy of
  rift.yaml (five slider moves, the diff, fold, reset; the user's files untouched). GUIDE.md has the panel.

- Program round 6 (2026-09-24, uncommitted, not released; the owner's list, built in their order): (1) the SPECTRUM tab:
  `gui.py` `spectrogram(path, scale)` (numpy, 4096-point frames, mean power per column, the loudest bin per band, dBFS
  with a full-scale sine at 0), `png_rgb` (stdlib zlib: the exe needs no Pillow), `spectrogram_png` (lru_cache 12), GET
  `/spec/<render key>?scale=log|lin` (only renders: the sample alone has none); the page draws the Hz axis (LOG 20 Hz to
  22 kHz, LIN), order boundaries, the playhead, the loop and the -100..-10 dBFS legend; about 0.5 s for a 5-minute
  render. (2) typed values: click the number of a channel volume or pan (0-64, L50/R20/C/S), MIX VOL, a slot GAIN, any
  instrument-panel value (its song units: RELEASE types the fadeout 0-256) or SPEED's type… (10-200 %); Enter goes
  through the slider's own handler (setMix/setVoice), clamped to the song format's ranges (the snapshot's `voice_range`
  = `VOICE_RANGE`), Escape or blur cancels. (3) EXPORT MP3 (+ STEMS): `request_stems(fmt, song, stems)` renders the song
  as written to `<song>.mp3` (192k) and optionally per-channel MP3s, `_write_mp3` pipes PCM into ffmpeg (no console
  window); `ffmpeg_exe()` imports imageio_ffmpeg by name at run time so PyInstaller's hook for it (it exists and would
  collect the binary) does not put the 88 MB GPL-3 ffmpeg into the exe; the exe needs ffmpeg on PATH until the owner
  decides (bundling: +31 MB compressed, exe 36 -> ~67 MB, the binary extracted to %TEMP% on every start, GPL-3 source
  and licence duties for the binary). (4) the playback loop, playback only (renders and their cache keys unchanged, so
  candidates and faders keep the loop): `State.set_loop` (POST `loop`, [order, row] from/to clamped and ordered, kept in
  tryout.json as `loop`, recorded in notes and the report), the strip above the progress bar (drag = loop, click = off),
  LOOP FROM/TO fields under SECTION TO LOOP; the page jumps back on a requestAnimationFrame tick (measured in the window:
  0-2 ms past the end, also across the file's own wrap and on a candidate). Found on the way and fixed: `api.swap_sample`
  renamed the slot to the WAV's stem, so a keymap naming the slot (`sample: Kick`, iron_relay) failed to compile every
  candidate in it; the name now stays when an instrument refers to it. Tests 43 (new: spectrogram, typed-value clamps,
  MP3 export and missing ffmpeg, the loop, the swap name); each feature checked in a real WebView2 window on a scratch
  copy of demo2/iron_relay.yaml (the owner's recent list restored, no notes on a real song). `docs/TRACKER-GAPS.md`
  (since retired, every row built): the gap analysis against OpenMPT, waiting for the owner's choice.
  Owner's decisions after it (same day): ffmpeg ships **beside** the exe, not inside (inside = 0.2 s more per launch,
  measured, and 88 MB more in every %TEMP%\_MEI folder a crash leaves; 36 such leftovers, 6.5 GB, were deleted on the
  owner's word): `ffmpeg_exe()` looks beside a frozen exe first, `tools/build_exe.py` copies imageio-ffmpeg's binary to
  `dist/ffmpeg.exe`, AGENTS.md's release recipe uploads both, THIRD_PARTY.md lists it (GPL-3, a separate program).
  EXPORT SONG AS offers MP3, OGG (Vorbis q6; game engines loop Ogg gaplessly) and FLAC (`ENCODE`, `_encode`). Tests 44.
  The gap order stands as proposed; the live engine is to be libopenmpt compiled to WebAssembly in an AudioWorklet
  (the owner has no language preference), first step a proof that the interactive ext functions (play_note, channel
  mute) are reachable from the official 0.8.9 JS/wasm build; Python + sounddevice is the fallback. Not built yet;
  the owner has not tested this round.
- Live engine proof (2026-09-24 evening, the owner's go-ahead to download what is needed): the official
  `libopenmpt-0.8.9+release.dev.js.tar.gz` (lib.openmpt.org; the download is kept in the ignored
  `tools/libopenmpt-js/`), its wasm build copied to `vulturetracker/web/` with its licences. `web/engine-core.js`
  (openmptEngine: Song with read/seek/position/vu/mute/playNote/noteOff/tempoFactor; loadOpenmpt takes the memory
  and function table from the instance, since the glue exports neither), `web/engine-worklet.js` (the processor;
  polyfills for TextDecoder, performance and crypto, all missing in an AudioWorkletGlobalScope; a second copy of the
  song with every channel muted plays note previews while stopped), `web/engine.html` (the `/engine` test page,
  linked from the Pattern tab), routes `/engine`, `/engine-worklet.js` (glue + core + processor, `worklet_js`),
  `/web/libopenmpt.wasm`, `/api/it` (`State.live_it`: the whole song with the unwritten mix; `compiled_it(whole=)`),
  facts gain `instruments`; build_exe adds `web/`. Measured: node check (`tests/test_engine.py` runs
  `tests/engine_check.js`) within 2 LSB of the DLL over one pass, interactive mute = the header disable bit, seek,
  preview on channel 2+; real WebView2 window on the iron_relay copy: engine ready in 20 ms, 4.6 MB module compiled
  and fetched in 344 ms (32 ms cached) and loaded in 41 ms, play from ord 2 row 16 advancing, a mute zeroes that
  channel's VU at once, RELOAD swaps at the same position (17.09 -> 17.25 s), preview -26 dB while stopped and
  silent after note-off; latencyHint 0 gives 2.7 ms base / 8 ms output latency (interactive: 10 / 40). Node: Nadir
  9.3 MB loads in 44 ms, 20 s renders in 80 ms. Tests 46 (+ test_engine with node). Next: the engine into the Pattern
  tab (group 1), then pattern editing.
- Round 7 (same evening, the owner's go): the engine is the Pattern tab's LIVE transport and the `/engine` test page is
  gone. `gui.html`: `LV` (lvStart/lvLoad/lvMsg/lvSync/lvPlay/lvStop/lvLoopPattern/lvNoteOn/Off), a cursor `CUR` (click,
  arrows, Page Up/Down, Home/End; double-click plays), keys in the Pattern tab through a capture listener (Space/F7
  from the cursor, F6 loop the pattern, F8 stop, the piano keys preview), `playPos` prefers the live position, so
  follow, SOUNDING and N work on it; `lvSync` (on every render) sends only changes: mutes (solo = the others), the loop
  span (pattern loop, else the playback loop), SPEED as tempo factor, and swaps the song in when `song.mtime` or the mix
  changes. Worklet: `loop` message, read in 32-frame steps while a span loops (jump back within 0.7 ms). Core: `read`
  at an offset. facts orders carry `order` (the module order index, which libopenmpt reports; differs past `+++`).
  Found on the way and fixed: the pattern's playing row carried the class `play`, which is also the play button's
  (36 px, grid), so that row was 36 px tall; it is `now`. Checked in the real window (iron_relay copy): play from the
  cursor (ord 0 row 16), the view follows, 6 SOUNDING chips and 6 header VU bars, a stems-rail mute zeroes the
  channel's VU at once, a fader move swapped in at 4.23 -> 4.39 s, F6 looped rows 0-127 of ord 0, Space stopped with
  the cursor at the stop row, the playback loop ord 5 rows 8-23 held, the render player's play stops the engine, a
  preview while stopped, N recorded 'live engine ord 3 row 13' (deleted). Tests 46 + the facts `order` check.
- Round 8 (same evening): pattern editing core. `gui.py`: `State.edit_cells(index, [{row, ch, cell}])` finds the
  pattern's literal block (`_pattern_block`: `name:` + `data: |`, or `name: |`), rewrites only the cell's text in its row
  (`_put_cell` keeps the neighbours' spacing, the label, the `;` comment; missing cells filled), writes out implied rows
  with labels in the block's width, compiles the whole text first (SongError: nothing written), keeps `history`/`future`
  (song texts, per session) for `undo(redo=)`, refuses when the file changed on disk; POST `edit`, `undo`, `redo`;
  snapshot `undo`/`redo` counts; `reload(loaded=)` reuses the edit's compile; measurements are memoised per file stamp
  instead of being dropped on every reload. `song.py` and `api.from_yaml` use libyaml's CSafeLoader when PyYAML has it:
  the 8 songs in the repository compile byte-identically, compiling them all took 1.2 s instead of 10.8 s (the first run
  included the resampling cache), an edit on Nadir 1.06 -> 0.35 s; YAML syntax errors keep their line (the wording
  differs slightly). `gui.html`: CUR gains `ch` and `col` (note, instrument, volume, effect letter, effect parameter),
  a click picks the cell, Esc toggles edit mode (● EDIT, STEP, ↶ ↷ with counts), `editKey` (piano keys enter a note with
  the INS instrument and preview it, 1 / ` / \\ off, fade, cut, two-digit entry `digit`, volume letters, effect letter +
  hex, Delete or . clears, Insert/Backspace shift the channel), `patEdit` shows each change at once and posts the edits in
  order (EDQ; a refused one shows in the bar in red, the refetch restores the cell), a refetch keeps the rows it has (no
  flicker) and never overwrites edits in flight; in edit mode the view stays on the cursor's pattern while the engine
  plays. Checked in the real window on a fresh iron_relay copy: a click on ch 8 row 1, Esc, z / 0 3 / v 4 0 / a / 0 6
  typed `C-5 03 v40 A06`, written in place as that one cell of row 001; Insert and Backspace moved and restored it; 9 9
  refused ('instrument 99 is not defined', no dialog, cell back to 09); an edit while playing live was swapped in; 13
  undos brought the file back byte for byte, redo and undo again. Tests 47 (+ test_pattern_edit_in_place_and_undo).
- Round 9 (same night): selections and commands. `gui.py`: `edit_patterns([(index, cells), ...])` writes several
  patterns as one undo step (`edit_cells` calls it; `_edit_block` per pattern; POST `edit` takes `patterns: [...]`).
  `gui.html`: `SEL` (anchor and extent: row, channel, column; `selNorm`, `selFields`, `inSel` for the tracker-style
  block), mouse press/drag/Shift+click (`cellAt`), Shift+moves (`withSel`), Ctrl+A / Ctrl+L, `targets` (the selection
  or the cursor's cell), `applyCells` (one POST, one undo step), `selCopy` (CLIP by field, plus the rows as text on the
  system clipboard), `selPaste(mix)`, `selClear`, `selTranspose` (INS ONLY), `selInterpolate` (volume and effect, same
  command at both ends), `selAmplify` (from 64 for notes without a volume), find/replace (`findSpec` wildcards, `findNext`
  across orders with `patRows`, `replaceAll` as one multi-pattern POST); the SELECTION and FIND bars; `patEdit` targets
  the pattern on show (`PAT.idx`). Checked in the real window on a fresh iron_relay copy: Ctrl+L + Ctrl+Up turned the
  arp's D-4 into D#4 (file too) and Ctrl+Z back; a drag over rows 0-7 of the arp (40 fields highlighted), Ctrl+C, paste
  at row 64 equal to rows 0-7; interpolate v34 -> v10 over rows 0-8 (v31 ... v13), amplify 50 %; find D-4 landed on ord 0
  row 0 ch 8; replace D-4 by E-4 in the whole song: 283 cells in 8 patterns, one undo step; 6 undos gave the file back
  byte for byte. Tests 48 (+ test_edits_across_patterns_are_one_undo_step). Next group: orders and patterns.
- Round 10 (same night): orders and patterns. `gui.py`: `State.song_edit(ops)` (one undo step; `_song_op` for orders,
  pattern_new / clone / rename / delete / rows, channel_rename / add / remove / move, module), text helpers `_span`,
  `_top`, `_children`, `_pattern_key`, `_row` / `_rejoin` / `_map_rows` (a channel removed or moved in every row of every
  pattern, each cell slot keeping its spacing), `_channel_lines`, `_yname` (plain YAML when it reads back the same, else
  quoted), `_commit` (compile, history, write, reload; `edit_patterns` uses it too); the orders line is rewritten on one
  line keeping its comment; the tryout's mutes, solo and unwritten faders follow a moved or removed channel, its section
  and loop are dropped when outside a changed order list; snapshot `structure` (orders, patterns with rows and use
  count, module settings); POST `songedit`. Fixed on the way: rows written out for a pattern that had none now all carry
  labels. `gui.html`: the SONG tab (settings by typeIn, order chips with move / remove / duplicate / clone / edit / insert
  / set / new pattern, the patterns table, the channels list with rename / ▲ ▼ / ✕ twice / + CHANNEL), `songEdit` queued
  with the pattern edits; `patUndo` counts as pending, so the page refetches only once all queued undos have landed.
  Checked in the real window on a fresh iron_relay copy: tempo 150 typed (its comment kept), duplicate + move + remove
  an order, a new 32-row pattern after order 0 (EDIT ▸ opened it in the Pattern tab), a clone of order 2's pattern, rename
  + rows 16, a channel renamed and moved, one added and removed; 12 undos gave the file back byte for byte. Tests 49
  (+ test_song_structure_edits). Paste flood and humanize explained to the owner (paste flood offered, humanize not
  recommended: RANDOM VOL does it live). Next group: the instrument editor.
- Round 11 (same night; the owner: the instrument editor, a new song from the app, paste flood if useful): `gui.py`
  `create_song(path, channels, sample)` (refuses an existing file; the layout the editors expect; a one-second C-5 sine
  `<stem>_tone.wav` as slot 1 unless a WAV is given, since a song needs a sample), POST `new`, `browsewav`; song_edit ops
  `instrument_set` (the whole entry re-dumped in place by `_redump`; refused while the tryout panel holds unwritten
  settings for it), `instrument_new`, `instrument_delete`, `sample_new` (path relative to the song); snapshot
  `instruments`; a song without the remembered slot or with odd samples still opens (`current_file`, slot fallback).
  `gui.html`: NEW SONG on the start screen; FLOOD (Ctrl+Alt+V); the INSTRUMENTS tab (`renderIns`, `insSet` with an
  optimistic copy, fields by typeIn, NNA/DCT/DCA selects, keymap table + a 120-note strip, three envelope graphs with
  drag / click-to-add / right-click-to-remove (`envDown`, `envCtx`, `shiftIdx` keeps sustain and loop on their nodes),
  sustain / loop / carry / filter, slots added by path or BROWSE…); the piano keys preview the instrument on show; empty
  patterns and edit mode show every channel. Found and fixed in the window check: after NEW or CLONE the page fell back
  to instrument 1 until the write landed, so a quick DELETE took instrument 1 (the selection now waits for its write;
  CLONE and DELETE wait for pending writes); a new song's empty pattern showed no channels, so the cursor had none.
  Checked in the real window: NEW SONG made `newsong/first.yaml` + tone (4 channels), fadeout 64, NNA fade, the volume
  envelope switched on, a node added by a click and one dragged (16,64 -> 16,38), sustain 1, a node removed by
  right-click, a keymap with a +12 entry, a second slot, NEW, CLONE, DELETE (the clone went), a preview on channel 1,
  a note flooded every 4 rows (16 of 64). Tests 51 (+ test_new_song_and_instrument_edits).
- Round 12 (2026-09-24, uncommitted; the owner's list, item 1): the sample editor (§4). `gui.py`: `wav_array` (the WAV
  as float32, lru_cache on its stamp), `wave_peaks` (min/max per column by numpy reduceat, or the frames themselves when
  zoomed past one per column), `entry_loops` (loop and sustain loop in the WAV's frames, `from_wav` resolved),
  `process_wav` (trim, fade_in, fade_out, normalize, reverse, dc, crossfade: the synth recipes' equal-power formula;
  loops follow the audio), `State.sample_view` (GET `/api/wave/<slot>?a=&b=&n=`: the WAV's facts, peaks of the span, the
  loops, and `player` = [libopenmpt instrument index, note] that previews the slot, preferring the note that plays it at
  C-5), `_new_wav` (`<stem>-<action>.wav` beside the song, numbered, never an existing file); song_edit ops `sample_set`
  (the whole entry; a one-line entry whose changed values are all scalars keeps its layout, anything else is re-dumped;
  refused when the global volume changes while the mixer holds an unwritten GAIN for the slot) and `sample_process` (writes
  the new WAV, then a sample_set pointing at it; the WAVs a refused edit wrote are deleted again). `gui.html`: the SAMPLES
  tab (slot list, a canvas waveform, wheel zoom around the pointer, Shift+wheel / scroll bar, VIEW ALL / SELECTION / LOOP,
  drag to select, loop and sustain-loop lines dragged, typed or set from the selection, mode off / forward / ping-pong /
  from the WAV, ▶ HOLD and the piano keys preview through the live engine (`lvNoteOn` takes an explicit note), the edit
  buttons, PROPERTIES with typed values and the auto-vibrato, Ctrl+Z / Ctrl+Y, Esc drops the selection); `patUndo` clears
  a stale refusal message. Checked in the real window (steps30.py, fresh iron_relay copy, slot 10 Warm pad: stereo, 286650
  frames, `from_wav` loop): three wheel steps zoomed to 69943-216708 and the peaks followed, a drag selected 57184-171795
  and SELECTION → LOOP wrote `loop: {start: 57184, end: 171795}` into the slot's one line (its layout kept), the end line
  dragged to 143082, ▶ HOLD played through the engine's preview copy on channel 17 once the engine held the written
  song, a 20 ms crossfade, a fade in and a trim wrote pad-crossfade / pad-fade_in / pad-trim.wav beside the copy (loop
  moved to 28519-114417, 229320 frames), volume typed 99 clamped to 64, vibrato square with speed 12, base note H-9
  refused in red with the file unchanged, 9 × Ctrl+Z gave the song back byte for byte. Measured: an edit 0.2-0.35 s, an
  undo 0.26-0.34 s on iron_relay. A block-style sample entry (iron_relay's slot 13) is re-dumped as a block when edited
  here, so a comment inside it goes (instrument_set does the same). Tests 51 (+ test_sample_editor).
- Round 13 (same day; item 2): MIDI input, page only. `gui.html`: `MIDI` (access, on, vel; remembered in localStorage),
  `midiStart` (requestMIDIAccess once at load; `onstatechange` rebinds, so a keyboard plugged in later works),
  `midiMsg` (note-on, note-off and note-on at velocity 0), `midiNoteOn` (preview through `lvNoteOn` with the tab's
  instrument: INS, the INSTRUMENTS tab's, the SAMPLES tab's player; loudness = velocity / 127 with VEL→VOL; in edit mode on
  the Pattern tab `enterNote` writes note, INS instrument and v01-v64 at the cursor and steps), `enterNote` shared with
  the piano keys, `lvNoteOn(k, ins, note, vol)`; the live bar's MIDI toggle, VEL→VOL and the input names. WebView2 grants
  Web MIDI without a prompt (probed: access true, no inputs on this machine). Test: `tests/test_engine.py`
  `TestMidi.test_midi_input` runs the page's MIDI functions (cut from gui.html) under node with the DOM stubbed. Checked in
  the real window with the handler fed a keyboard's messages (no device here): a preview on channel 16 of the preview
  copy while stopped, released by note-off; in edit mode D-5 at velocity 96 written as `D-5 01 v48` at the cursor (ch 3
  row 4) and the cursor stepped; VEL→VOL off wrote `E-5 01 ... ...`; the Instruments tab previewed its instrument; MIDI
  off ignored a note; 2 undos gave the file back byte for byte. Left out: chords spread over channels and recording
  quantised to the play position while the song plays (§7's second row). Tests 52.
- MIDI permission (round 14, the owner's report: they clicked Allow at every launch). WebView2 asks for MIDI (the probe had
  missed the prompt); the answer and the page's localStorage were lost every launch because pywebview ran WebView2 in
  private mode and the server took a random port (a new origin each time). Now `serve` starts pywebview with
  `private_mode=False, storage_path=%APPDATA%/VultureTracker/webview` (`PROFILE`) and `make_server` binds port 8723 (`PORT`)
  when free, else any free port (`_Server` without SO_REUSEADDR, so a second app window cannot share a port on Windows);
  CLI `--port` help says so. The page asks for MIDI only once MIDI is clicked on (`MIDI.on` defaults off, remembered);
  switched on, it connects at every launch. Checked with scratch/app-harness/persist_check.py (two launches, one scratch
  profile, a fixed port): launch 1 showed no prompt until MIDI was clicked, then the prompt, Allow clicked; launch 2 had
  MIDI on with access at load, no prompt, and the speed set in launch 1 (0.75) kept. Test `test_the_page_keeps_its_address`.
- Round 15 (2026-09-24; item 4, MOD / S3M / XM import, the owner's go): `vulturetracker/modreader.py`: `read_mod`
  (31-sample MODs, M.K. / xCHN / xxCH; sample mode), `read_s3m`, `read_xm` (1.04), `read_module` (by signature, IT
  included); `itreader.import_it` reads any of them. Measured against libopenmpt with modules written byte by byte in
  `tests/test_modimport.py` (level per 10 ms, pitch from interpolated zero crossings, balance) and calibrated there:
  MOD samples at the PAL Amiga rate (7093789.2 / 856 = 8287 Hz at C-5; 8363 was 15.8 cents flat), MOD pans 16 / 48 (not
  0 / 64), MOD mix volume 64 (libopenmpt plays a MOD 2.5 dB over an IT at 48), IT's old effects for all three (vibrato
  depth and phase like ProTracker, FT2 and ST3; new effects were half as deep and started upward), MOD and XM tremolo
  depth doubled (capped at F), S3M mono songs with ultraclick 0 at 0.73 of the master volume (libopenmpt: -2.74 dB; with
  ultraclick set, none), a mono S3M keeps its own pan table, ST3's shared memory (D E F I J K L Q R S) written out, XM
  fadeout / 32, XM volume-column pan x * 4, XM pan slides / 4 (warned when not exact), XM key-offs on instruments
  without a volume envelope as note cuts (following the instrument each channel plays along the orders; an envelope
  stand-in cut a tick late), XM envelope loop end a tick earlier (FT2 loops a tick sooner). Real modules (7 MOD, 7 S3M
  from the Mod Archive into scratch/modimport, never committed; 19 XMs already in scratch/ref and UT99's firebr / Mech8,
  `scratch/modimport/batch.py`): the level differed by tracker (FT2 and MilkyTracker files -3 dB, old ModPlug XMs
  +8 to +9 dB by channel count), so `match_level` renders both for 30 s and sets the mix volume (the MOD and S3M rules
  stay as the starting point); patterns over 200 rows had been cut (a whole song misaligned), now `_split_long` splits
  them into 192-row parts with orders, Bxx and Cxx following; songs over 99 instruments or samples keep only what they
  play (`_compact`). All 33 files import; median level difference within +-0.3 dB except two XMs (-1.3, +1.0), 90th
  percentile under 4 dB. App: IMPORT A MODULE on the start screen (`import_beside`: `<stem>.yaml` + `<stem>_samples/`
  beside the module, numbered, POST `import`, `browse(module=True)`), opened in the Pattern tab. Checked in the real
  window (steps33.py): space_debris.mod (4 ch, 42 orders, 5:06), mfm4.xm (12 ch, 13 instruments) and dust.s3m (16 ch)
  imported, opened and played by the live engine. Left out: a pan law of its own (MilkyTracker: balance differs for panned
  samples), XM vibrato's one-tick phase, 15-sample Soundtracker MODs, XM 1.02/1.03, ADPCM samples, AdLib instruments.
  Tests: test_modimport (5 tests, 48 cases, 3 s), test_import_beside_the_module.
- Committed and pushed on the owner's word: 1be2a7a (rounds 6-15, README with new screenshots, pyproject shipping
  `web/`). After it (uncommitted): the server refuses requests from other web pages (an Origin that is not its own) and
  under another host name (DNS rebinding), `Handler._foreign`, 403; every POST can open, create or write files, and the
  fixed port made the server easy to find. Test `test_other_pages_are_refused`; the window's own requests pass (steps32).
- Round 14 (same day; item 3, the conveniences of §9): `gui.py` `effect_help` (SONG_FORMAT.md's volume, effect and S tables
  parsed; `tools/build_exe.py` bundles SONG_FORMAT.md; GET `/api/effects`), facts `highlight` (rows per beat and bar),
  `State.unused` (patterns outside the orders, instruments no played cell names, samples no used instrument maps;
  snapshot `unused`), song_edit ops `sample_delete` and `sample_file` (the slot pointed at another WAV by
  `api.swap_sample`'s rules, loops past its end dropped), `save_upload` + POST `/api/upload?name=` (raw WAV bytes saved
  beside the song, an identical copy reused, others numbered, non-WAVs refused and removed). Worklet: `metro` message; with
  the metronome or a loop on, the song is read in 32-frame steps and a new beat row starts a 30 ms click (2 kHz on the bar,
  1.25 kHz on the beat). `gui.html`: F5-F8 in every tab (capture listener, before the tabs' own keys; F5 no longer reloads),
  METRO, the scope (an AnalyserNode on the engine, drawn from a rising zero crossing), `patHelp` in the Pattern tab's hint
  line, the pattern's row lines from `highlight`, the CLEAN-UP panel (✕ each, REMOVE ALL UNUSED twice = one step),
  `dragOver` / `dropWav` targets (Samples slot rows and waveform: `sample_file`; the slot lists: `sample_new`; the Tryout's
  candidates: `add`), a drop elsewhere ignored. Tests: `test_conveniences` (help tables, unused + refused lone delete + one
  step, uploads, `sample_file`), `test_metronome_clicks_on_beat_rows` (the real processor under node with the worklet scope
  stubbed: every click starts within 2 frames of where its beat row starts). Checked in the real window (steps32.py, fresh
  iron_relay copy): F5 in the Samples tab played from order 0 without a reload, F8 stopped; METRO sent [true, [4, 16]], the
  scope drew; the cursor on `D-4 05 v34 O28` read "v34: set note volume (00–64) · O28: sample offset: …"; 8 bar and 24
  beat lines on the 128-row pattern; CLEAN-UP "nothing unused", a spare pattern listed and removed by REMOVE ALL UNUSED;
  WAVs built in the page and dropped as files: on slot 01 (dropped_kick.wav, name Kick kept since an instrument names it),
  on the list (slot 16 new_one.wav), on the candidates (cand_drop); 4 undos gave the file back byte for byte. Tests 55 (with the port test below).
- Cloud session, 2026-09-25 (branch `claude/wonderful-johnson-1decm2`, Linux, libopenmpt 0.7.3, headless Chromium; no
  Windows window, exe or 0.8.9 DLL there). Every open finding of the September audit fixed with a test each (undo puts
  the tryout settings back, tryout sections with Bxx, block order lists, whole-song renders, atomic writes and corrupt
  meta/notes files, BOM, archives' own orders, the `}`-in-a-comment entry, Range, the old worker stopped, IT patterns
  over 200 rows and numbers over 99, a faster `_decompress`, pattern size and message length in `check`, 0-prefixed
  numbers, engine load ids), the docs it named corrected; the tracker gaps left built (HUMANIZE, MIDI and piano keys
  record at the playing row while the engine plays the pattern on show, the Tryout tab's RECIPE box with
  `synth.render_one`); `docs/AUDIT-2026-09.md` and `docs/TRACKER-GAPS.md` removed; ArenaPrototype no longer named.
  Then, at the owner's request (a friend heard the leads in a video and suggested tracker delay): ECHO in the Pattern
  tab's selection bar, song_edit op `echo` (`State._echo`: a channel's notes copied into a new or existing channel, rows
  and ticks later, at a percent of their volume; song-wide and pan effects not copied), `test_echo` and the page test.
  Tests 108 there (`VT_CHROMIUM` drives `tests/test_page.py`). To check locally in the real window: the RECIPE box with
  a Surge patch (only file recipes could be rendered there), MIDI recording with a keyboard, and the build of the exe.
- Cloud session, 2026-09-25 (branch `claude/clever-ramanujan-il8dju`): a research pass (speed, features from other
  projects, recording from the owner's Scarlett 2i2), given as a chat report; its chunks, in order: 0 cloud setup,
  1 speed, 2 recording through `sounddevice`, 3 render-to-sample / slicing / the effects panel, 4 sample discovery
  (similarity index, FIND SIMILAR, a sample map), 5 compile-time helpers (groove, generators, chords, phrases, velocity
  layers), 6 spectral tools, 7 spikes (OpenMPT's built-in DMO effects in the .it, Guitar Pro import, a SuperCollider or
  Faust recipe source). Built: chunk 0 (`.claude/hooks/session-start.sh`: libopenmpt, PyYAML with libyaml, numpy,
  Pillow, imageio-ffmpeg, Playwright, `VT_CHROMIUM`) and chunk 1a. `tools/bench.py` times compile, facts, render, an
  edit and the module the live engine then loads, on the demos (stand-in WAVs for samples kept in samples/local/).
  Measured in the container, server time from an edit to the engine's module (median of 7): arena 149 -> 35 ms,
  iron_relay 1141 -> 72, undertow 1624 -> 113, vantage 1327 -> 169; a warm compile of vantage 239-490 -> 44 ms. How:
  the compiler memoises samples on their file's stamp (read, resampled, converted: compact arrays that compiled modules
  share), the image check per sample and rate, parsed patterns per text and position, and cell parses; the app keeps
  the .it bytes of its reload compile (`State.it`), which `facts_of` and the live engine use unless the instrument
  panel edits an instrument (before: the whole song compiled a second time through the dict and YAML). Every demo's
  .it (text path, dict path, a section, a candidate swapped in) is byte-identical to before. Chunk 1b: the 2x render
  through a polyphase decimator (`resample.decimate`: only the kept samples, in blocks, from the int16 mix), bit-
  identical on every demo, vantage 4.1-5.6 s -> 1.2-1.7 s (libopenmpt's own mixing at 88.2 kHz is about 0.5 s of it);
  VOL and PAN faders reach the engine while they move (chvol / chpan, libopenmpt's interactive channel volume and pan,
  equal to the header value in a node test; the release swaps in the exact module as before); the worklet allocates
  nothing per quantum and renders the preview copy only from a preview note to 0.3 s of silence after its key (before:
  every quantum, the whole song muted, also while the song played); `/api/state` hashes the song text once per text
  and reads the WAV stamps once per poll (before: once per candidate each); WAVs are served range by range from the
  file (before: the whole file read per request); undo keeps the newest 200 steps. Left as it was: the meters pass
  (one soloed render per channel, stopped at the next channel when the mix changes) and the swap's catch-up while
  stopped (up to 4 s of the song rendered at once, silent). Checked in Chromium (demo2): the fader's moves reach the
  playing engine, the release swaps, no page errors. Measured by the owner on Windows (7-run medians): edit -> live
  arena 93 -> 35 ms, iron_relay 543 -> 70, undertow 913 -> 77, vantage 912 -> 230; warm compile 6-8x faster; 2x render
  about 2x faster there (undertow 2.53 -> 1.44 s, vantage 2.22 -> 1.14; libopenmpt's own mixing is a larger share on
  that machine), 1x unchanged; a fader dragged while the Pattern tab plays sent 20/20 chvol and 20/20 chpan to the
  engine, the release swapped, playback went on, no page or worklet errors; tests OK; the exe rebuilt and smoke-tested.
  Chunk 5 (Pattern tab COMPOSE: GROOVE, EUCLID, CHORD, LAYERS; `compose.py`) and chunk 3a (RENDER -> SLOT in the
  Pattern tab: rows rendered as they play into a new slot, with a ring-out; SLICE in the Samples tab: onsets by
  spectral flux in `dsp.py` or equal parts, shown on the waveform, written as a WAV and slot per slice plus a kit
  instrument) followed, each checked in Chromium on a scratch song. Phrases (chunk 5) were left out: the other
  helpers write the same cells, and phrases would need a new song-format feature. Chunk 3b: the Samples tab's EFFECTS
  → NEW WAV (gain, low/high-pass, an EQ band, loudness, pitch at the same length, stretch at the same pitch, truncate
  silence; `dsp.py`, new `sample_process` actions, loops following changes of length), checked in Chromium. Chunk 2a,
  built against a simulated interface (no audio hardware in the cloud): the RECORD tab (`record.py` on sounddevice:
  devices and drivers, inputs 1 / 2 / stereo / mono, meters with clip, a YIN tuner, pre-roll; takes in `takes/` beside
  the song, trimmed, their note found, sent to the slot's candidates or a new slot tuned to the cent), AUTO LOOP in the
  Samples tab, an ASIO choice saved in %APPDATA%/VultureTracker/record.json (read before sounddevice loads), the exe
  build collecting sounddevice and its PortAudio DLLs. `VT_FAKE_AUDIO=1` runs the tab on the simulated interface.
  2c (recording along with the song: count-in, latency calibration, loop takes) is not built.
  Tested on the owner's machine 2026-09-25 with a **Scarlett Solo 3rd Gen** (USB 1235:8211; mic XLR = input 1, the
  instrument jack = input 2; Focusrite driver 4.143 installed that day; its devices are named "Analogue 1 + 2
  (Focusrite USB Audio)", MME cuts it to 31 characters, and "Focusrite USB ASIO"), a guitar on input 2, no mic:
  1. Listed under MME, DirectSound, WASAPI, WDM-KS; WASAPI shared input 2 at 44100 and 48000: meters follow, input 1
     sits at -95 dBFS, CLIP lights with the gain up. 2. Tuner: all six open strings in the right octave, steady within
     about 3 cents (the guitar 20-42 cents sharp); once an octave-up D-5 for a second on the D attack. No reference tuner
     to compare with; a take's note (pitch_of) agreed with the tuner within 2-3 cents. 3. Candidate, new slot (A-3 at
     110.0 Hz from c5_speed) and keep all work; a 45 s take: 45.10 s after REC against 45.13 s of wall clock (50 ms
     polling), 0 overflows; trims right. 4. Stereo: input 1 left, input 2 right; mono is the mean (-6 dB for one
     input). 5. EXCLUSIVE opens at the device's rate (48000), refuses 44100 and 96000 ("Invalid sample rate
     [PaErrorCode -9997]"). 6. ASIO listed and opens at 44100 and 48000 (it switches the device's rate); a take matched
     WASAPI (level within 1 dB, pitch within 3 cents). 7. AUTO LOOP + CROSSFADE LOOP work; the owner: "a bit smoother
     with the crossfade"; measured: the wrap step 10x -> 1.5x the normal sample step, but a fading guitar note loses
     9-13 dB across the 1.75 s loop AUTO LOOP chose (a pulse per loop). 8. The exe (built that day) lists all four
     drivers, records, plays takes, makes the tuned slot with its instrument.
  Fixed (tests in test_record and test_page; test_page runs here with `pip install playwright` and
  VT_CHROMIUM=Edge's msedge.exe): the takes table was rebuilt on every 100 ms poll, so ▶ / → CANDIDATE / → NEW SLOT
  clicks were lost (now rebuilt only when the takes change); RATE (and INPUT) snapped back to the open values (a change
  now reopens the input); a take sent to a new slot had no instrument, so nothing could play it in a song with
  instruments (it now gets one, as SLICE does); ▶ HOLD played every slot at C-5, a take 15 semitones up (it now plays
  the note that plays the WAV at its own speed: base_note, or what c5_speed puts there); ASIO failed to open ("Failed
  to load ASIO driver": the driver opens only on the thread that loaded PortAudio, and each request has its own thread;
  every PortAudio call now runs on one audio thread); EXCLUSIVE at another rate now names the device's rate. Not
  changed: FIND THE NOTE on a strummed chord reads an octave low (E-2 for an E chord: the chord's common period);
  the app plays no input back (monitoring is the interface's; the owner had no headphones for the Solo, and Windows'
  "Listen to this device" works); 2 s per request to `localhost` from Python's urllib on this machine (IPv6 first):
  scripts should use 127.0.0.1.

## Next steps, in order

1. The user listens to v6 (`python -m vulturetracker gui suite/nadir/nadir.yaml` or `nadir.mp3`); the NOTES tab starts
   empty for v6 (the v5 notes are archived on open). It is the last pass by their word: record what they say, and change
   Nadir again only if they ask.
2. The next piece follows `suite/NEXT-PROMPT.md`: one reference track, measured into a brief, then drums and bass as a
   two-bar loop with candidates the user picks in the tryout, then one layer at a time, and the full form only after
   every sound is approved. The group-per-piece plan (groups 2-5) is dropped; the group analysis in `scratch/ut99-clean/`
   stays useful as measurement tooling. Started 2026-09-22: Rift (working title) against Nether Animal (the user's
   pick). Step 0 is done: `suite/rift/BRIEF.md`, from the new `scratch/ut99-clean/perchannel.py` (every sample and
   channel soloed: character, idioms, per-channel-power loudness, a per-order layer map, bass notes) and `pitch_grid.py`
   (as-played pitches, drum rows timed on the render). It holds measurements of Epic's module, so under the scratch/
   rule it stays uncommitted unless the user says otherwise. The user's new rule: Vantage is too close to Foregone for
   their comfort, so the brief marks each trait genre (G) or Nether's fingerprint (F), default keep the G traits they
   pick and change every F. They kept every G trait and took the F suggestions (tempo 110 speed 4 = 165 BPM, A minor at
   A440, own rows, lengths and echoes, no colour set, so no 16th sequence). Step 1 is built and waits for their picks:
   `suite/rift/rift.yaml` (two bars twice: break, hats, crash, sub, stab; the rows are in its header),
   `rift.tryout.json` (21 candidates: 4 breaks, 5 hats, 3 crashes, 4 subs, 5 stabs), made by `gen_cand.py` (Big Rusty
   breaks in four treatments, kit and TR-8 hats and crashes, subs as a kick attack into a looped 11-cycle 55 Hz wave,
   Surge XT stab finalists of `cand.yaml` plus a noise stab; floors from Nadir's `gen_floor.add_floor`) into
   `samples/local/rift-cand/`. TR-8 candidates cannot be committed (MusicRadar pack). Their Step 1 picks (written with
   U, no notes): break_room, hat_rusty_closed, crash_tr8_1 (TR-8: stays local), sub_rusty, stab_helmeto; their stab
   fader (channel volume 44) was left unwritten in the tryout mix and is now written into the song. Step 2, the bed, is
   built and waits for their pick: channel 6 in surround, slot 6, one A minor chord (A-3 E-4 C-5, not the reference's
   open fifth) per pattern with nna fade 8; the song plays the loop twice (`orders: [loop, loop]`), rows 0-63 of the
   first five channels unchanged. Candidates: `bed.yaml` screened 22 dark Surge XT pads (none of Vantage's or Nadir's),
   `bedfin.yaml` renders the five finalists (Alone, Worried, Endgame, Yeti Funeral, Still) looped at 5.5 kHz bandwidth
   with a room, `gen_cand.py beds` adds a -26 dB floor. Soloed, the bed is at -25.1 dB active against the sub's -22.4
   (the reference's bed sat about 12 dB under its low end); levels are the user's. They picked bed_endgame and wrote
   the mix (Bed volume 34). Step 2, the line, is built and waits for their pick: channel 7, slot 7, one slow line in A
   minor pentatonic (A C D E G: never a semitone from the bed's A C E; 0 clash rows of 128), long notes, phrase A in
   `loop` (bars 1-4), its answer in the new `loop_b` (bars 5-8, channels 1-6 copied row for row), each released on row
   60, no echo channel; `orders: [loop, loop_b]`. Candidates: `line.yaml` screened 32 voices (Surge XT, OB-Xd, Dexed),
   `linefin.yaml` renders five (Dexed Mute SINES, Surge Gentle, Lera, Smoothness World Cup, Dexed SOFT TOUCH) looped with
   a room, `gen_cand.py lines` adds a -28 dB floor and tunes each loop to its root by rewriting the WAV rate (the Dexed
   voices played 14-18 cents sharp, Gentle drifts per render). Soloed, the line is at -21.0 dB active at full volume,
   the loudest channel (the reference's lead sat about 10 dB under its low end; the user's standing taste puts the
   melody at the top). The user rejected all five and the melody: "they don't seem to match the style. It seems too
   melodic for a drum and bass track." Second line round, built and waiting: the melody is gone (the voices are marked
   rejected in the tryout); channel 7 is now Call, one short figure per 8 bars (row 16 of `loop`; `loop_b` has none),
   each candidate a whole figure rendered as one sample by `hooks.yaml` (root label C-5, dotted-8th echo of our own
   printed in): two notes (Slow Poly MW), a three-note fall (OB-Xd 3 voice Soft Lead), an A minor chord stab with dub
   echoes (Semihaunt), a noisy swell (Winter Warmer), a breathy vocal A (Giana Brotherz Dark Whisper, an octave up since
   it sounds an octave under the key). `gen_cand.py hooks` floors them and tunes each by its first held note (Winter
   Warmer read -12 cents; a 90 ms window on the chord misread +26 cents, so the chord is measured over its echoes).
   Channels 1-6 unchanged in both patterns. Their five notes on the calls (15:18, `suite/rift/rift.notes.md`, against
   song version 7e4f320d; no pick written, slot 7 still lists the five and holds hook_two as a placeholder, no unwritten
   mix): hook_two "too sparse and front loaded"; hook_swell "hate it."; hook_vox "mostly hate it."; hook_fall "the tone or
   timbre isn't right, but this is the closest one. still too front loaded"; hook_chord "it's alright, the tone is a bit
   too muddy and again, there's just one note at the beginning and then nothing". Reading: the falling three-note figure
   is the direction; the call must be spread through the 8 bars instead of one gesture on bar 2 and then silence; the
   OB-Xd soft-lead timbre is wrong; the chord stab is acceptable but muddy (A-3 C-4 E-4 on Semihaunt, low) and also
   front-loaded; swells and vocal textures are out. Third call round, built 16:10 and waiting for their pick (the five
   notes are archived as `rift.notes-7e4f320d.*`): the figure lives in the pattern now, so the tryout compares timbre
   alone. Channel 7 plays a falling three-note call every two bars through the 8 (E D A, E D G, E D A, D C A on rows 0,
   6 and 12 of bars 1, 3, 5, 7, the last note held; G-4..E-5), the new channel 8 (Call echo) repeats each note 3 rows
   later at v27 from the same slot, instrument 7 has fadeout 128 (a note fades under the next over two rows); channels
   1-6 identical cell for cell in both patterns (54 written cells each). Voices: `suite/rift/screen.py` measured 2001
   Surge XT, OB-Xd and Dexed patches at a held C-5 (fundamental share, richness, mud = power under 500 Hz against 1-4 kHz,
   presence, top, power off the harmonics, odd/even, attack, sustain, motion; a key-aware octave test; `--part K/N` for
   parallel runs, `HUNG` for the four patches that hang the plugin host); 1421 held a steady C, 16 sat in the zone the
   notes point at (fast, steady, not pure, not muddy, less nasal than the soft lead, no buzz, some grit). Five of distinct
   character are in `callfin.yaml` (the hooks' room, stored 9 kHz wide at an 18 kHz rate because E-5 plays 4 semitones
   over the root and E-MU.II's FM top at 11 kHz had put the call at -32 dB above 12 kHz), floored at -24 dB and tuned by
   `gen_cand.py calls` on the power-weighted centre of partials 1-6 (`tune(..., centre=True)`): call_brass (Surge Synth
   Brass 1), call_moog (Luna Moogy Staccato), call_jim (Surge Jim), call_emu (Dexed E-MU.II), call_retro (Vospi Nice And
   Elegant Retro); the song's slot 7 holds call_brass as the placeholder. Measured: centres -0.7 to 0.0 cents after
   tuning; `suite/rift/clash.py` 0 clash rows of 128; soloed active Call -22.1 (retro) to -25.3 dB (jim), Call echo -29.6
   to -32.9, above 12 kHz -70 to -79 dB (hats -52); no unwritten mix. Dropped on the way: Kuniklo Mini (oscillators a
   fifth up and a fourth down: a B against the bed's C on every E) and YAMAHA GX1 (a built-in delay near 250 ms). Their
   word on it (16:30, no pick written): torn between call_brass and call_moog, likes neither fully; "doesn't feel
   dynamic enough, both the melody and the sound"; they asked what an Audacity-like effects panel in the GUI would take.
   Measured: the screen selected for steadiness (hold within 3 dB; brass moves 0.2 dB over the hold, moog 1.1), and
   every call note plays at one volume on the same rows 0, 6, 12. In the tryout they rejected call_jim, call_emu and
   call_retro (16:25). They chose the instrument panel first (built: Package changes), then a call round. Fourth call
   round, built 17:40, waiting for their pick (no notes on round 3; no unwritten mix): the figure has accents (v64 down
   to v32), four rhythms (bars 1-2 broad: E D A on 0, 6, 12, the D cut short; bars 3-4 the answer higher and off the
   beat: G-5 E D on 34, 38, 43, a C pickup on 62; bars 5-6 quicker: E D A a dotted 8th apart; bars 7-8 the close: D C A
   and a D pickup), note fades (~~~) setting the lengths, echoes on channel 8 only for the accented and held notes
   (v22-24, faded after 8-10 rows); instrument 7 moves per note (attack 1 tick, decay 12 ticks to 44, low-pass 96 with
   resonance 24 opening from 36/64 of it over 10 ticks, random volume 12 %; the panel reads it back). Candidates:
   call_brass and call_moog as heard in round 3, plus three from `screen.py --motion` (level, timbre and pitch motion over
   the hold, attack brightness) over the zone's 124 patches: call_ebm (OB-Xd EBMLead), call_trumpet (Dexed BR TRUMPET:
   one partial 17 dB down, 84 cents above the 2nd harmonic), call_analyse (Surge Analyse, the warmest: mud +10.8);
   `synth --only` and `gen_cand.py calls NAMES` rendered them without touching brass and moog. Toto Brass and OB-Xd Warm
   Brass (a sub-octave as strong as the top partial) and OB-Xd Complex Poly (a repeat 0.6 s after release) were dropped.
   Measured: channels 1-6 identical to the approved song (54 written cells per pattern); 0 clash rows of 128; tuning
   centres within 0.1 cents; soloed active Call -27.7 (analyse) to -29.9 dB (trumpet), about 4 dB under round 3 (the
   accents, the sustain level, the filter, the shorter notes), Call echo -35.6 to -37.9; above 12 kHz -67 dB or lower
   (hats -52, although G-5 plays the samples 7 semitones up); on an accented note the centroid rises from 543 to 933 Hz
   over 200 ms. Their verdict on round 4 (18:00, no pick, no notes): "It still really doesn't sound correct to my
   ears"; "so far I still feel like we haven't really been successful at emulating this style". Next, in a new
   conversation (context was at 70 %): study the more melodic modules, Mechanism Eight (`modules/Mech8.s3m`) and The
   Course (`modules/Course.it`), measure how their melodies and sounds are built, contrast that with Nadir and Rift, and
   stop for their decision before building anything; Rift stays at round 4 until then. Done the same evening:
   `scratch/ut99-clean/CONTRAST.md` (local, it measures Epic's modules; new scratch tools `s3m.py`, `melodic.py` +
   `lines.json`, `excerpts.py`, soloed reference excerpts in `scratch/ut99-clean/excerpts/`). Measured: the references'
   melodic figures are one-bar 16th cells repeated (71-97 % of bars) whose sound changes on 93-100 % of notes (sample
   offsets sweeping 11-49 values, gates, accents, echoes panned away), sitting 5-15 dB under the kick or bass; ours move
   the notes (Nadir's lead a stepwise on-beat tune, Rift's call 6 cells in 6 bars), 0 % of their notes articulated in
   the pattern, and sit on top; ours are also darker and cleaner as played, and Nadir runs two figures at once in 22 of
   34 orders. It offers three options (pattern writing, sources, harmony and arrangement) and asks about the taste rules
   the references break (repeating arpeggio figures, a saw-like 303, distortion, bass motion). The user's decision after
   reading it (2026-09-22): "the taste rules haven't been serving us so far. These reference songs are proven so we
   should follow their lead"; they want whatever it takes to succeed. They asked for a continuation prompt: Rift's
   melodic and colour layers rebuilt the way Nether Animal builds them (measured with melodic.py first), proved on the
   8-bar loop. Seen in passing: rift.yaml's instrument 7 has `filter_cutoff: 42` while its header comment says 96
   (probably written from the instrument panel). Pitfalls met:
   libopenmpt renders a tick as whole samples (942 at 44.1 kHz for tempo 117) while `order_start` rounds another way,
   so time rows from the render; `analyze.py`'s +-33 cent tuning fold read Nether's C# (tuned +30 cents) as D. A patch
   can carry interval oscillators, which the clash check (cell notes only) cannot see: look for tonal peaks off the
   harmonic series before offering a voice. A detuned stack (Jim: voices at 0, +11 and +21 cents) is tuned on its
   centre, not its strongest peak, and the same patch drifts from render to render (Jim +5.6 and -10.6 cents), so tune
   after every render. The app's pitch column is a single-frame hint (it shows call_retro +17 cents; its 0.85 s centre
   reads -0.1). Brass patches often layer a sub-octave (Toto Brass, OB-Xd Warm Brass): check for a strong partial an
   octave under the key before offering one. Big Python patches through a Bash heredoc lose backslashes (`\n` became a
   newline in a test): write them with the Write tool.
   **Follow the references (2026-09-22, evening, the user's decision after CONTRAST.md).** The taste rules are gone
   (AGENTS.md "Follow the reference" and the bandwidth-based anti-aliasing bullet; `suite/NEXT-PROMPT.md` carries the
   same in plain words): nothing is excluded in advance, every choice starts from what the reference measurably does, the
   balance starts at the reference's (faders stay theirs), a sample may play as far up as its bandwidth allows (content
   times transposition under ~18 kHz and the drums' ceiling; spectrogram check stays), the brief's F traits may be
   followed; notes, cells and sounds stay ours, copyright unchanged. Rift's round-4 call is silenced, not deleted
   (channels 7 and 8 `muted: true`; cells, slot 7 and instrument 7 with the user's panel edits kept).
   - Step 0 done: Nether added to `scratch/ut99-clean/lines.json`; `melodic_Nether.txt/.json` measured and checked
     independently against the cells, WAVs and perchannel (ten corrections, used in the plan: the lead's same-channel
     re-strikes were counted as notes by melodic.py; the sub alternates two channels; strings are A C# E G#; the bed
     sample is an F#-C# fifth playing E-B every bar and C#-G# once per pattern; the drone is one held note; levels are
     active against the sub). `suite/rift/BRIEF.md` now ends with the **layer plan**: 1 sequence (8.0 dB under the sub),
     2 lead call (10.6), 3 tonal hit (12.4), 4 surround bed (12.3), 5 strings (8.6), 6 drone (9.6), 7 noise (12.0),
     8 vocal pad (11.9), 9 second line (10.3), each with Nether's idioms and sound class; the departures of the
     approved sounds are listed there and put to the user, nothing changed (break 10.6 dB under the sub vs Nether's
     0.7, stab 11.4 under vs 1.5 over, hats 28.4 vs 18, bed 7.9 vs 12.3 and a triad once per pattern vs two fifths).
   - Step 1 built (final 19:12, three rounds, each checked by an independent agent). **Picked 19:24: `seq_calliope`**
     (written with U; no notes, no ratings, no unwritten mix): channels 9-11 (Seq, Seq copy 2, Seq copy 3), slot 8, instrument 8 (no envelopes), written by
     `suite/rift/gen_seq.py pattern` (do not hand-edit those columns): 8ths, one voice restarted per pattern at v36 and
     moved legato with GFF on the other notes; our head E A D A (E-5 A-5 D-6 A-5) opens every bar (once also on G);
     bars A B C D in `loop`, A B C E in `loop_b` (three stay, the fourth changes, as Nether's do); copies +2 rows v6 pan
     34 and +3 rows v12 pan 56, main pan 17 (Nether's delays, levels and pans), each copy restarting on its first note
     of the pattern (rows 0/1) as Nether's do. Our five cells share at most one interval in a row with any of Nether's
     six (a scratch check that prints counts only). Candidates in the tryout (slot 8): `seq_theremin` (placeholder in
     the song), `seq_calliope`, `seq_sine`, `seq_ghost`, `seq_glass`, from `suite/rift/seq.yaml` (Surge LinnStrument
     Theremin, Dexed CALIOPE, Surge Sine Lead, Surge Malfunction Ghost, all rendered at E-3) and VCSL's struck wine glass
     (CC0; the file named D5 sounds D6). `gen_seq.py` gives each Nether's measured layout: 0.994 s, 16 whole cycles
     looped from 0.80 s (0.194 s), sounding E-3 and played 17-36 semitones up, band-limited at 1.5 kHz (the top note
     stays under 12 kHz), started at its -3 dB point, the loop level held flat, a loop-periodic floor at Nether's
     -41.8 dB of the loop's power (the glass's own -41.3), one loop RMS. Screened out: Butter and NuAgeDelys (floors
     -20/-19 dB from detuned voices), Horsehairs (a sub-octave), Circus 1.
   - Stored at 44.1 kHz on purpose: the compiler resamples other rates and `resample()` pads the sample's end with
     zeros, which clicked at every loop pass in round 1 (wrap 412x the loop's own second difference, a 21 % jump; now
     0.5-1x and 0 %). Fixed in the compiler since (ec61d33, below); storing at 44.1 kHz stays the habit.
   - Measured (nothing heard), final build: the sequence 8.2-8.3 dB under the sub for every candidate (Nether 8.0 over
     the song, 8.1-8.3 in its section), 9.9-10.0 under the mix (10.0); 8 notes a bar, 50/50 beat and offbeat, 97 %
     legato G, one volume; copies exactly -15.6 / -9.5 dB by volume, rendered L-R within 0.1 dB of Nether's; 5 cells,
     no bar equal to the previous, 2-bar units all "answer", 94 % repeats over a 22-order section (93); written range
     A3-E5, median A4 (Nether B3-E5, F#4); pitch classes A 31, E 23, D 22, G 14 % (A 51, E 19, G 18 mapped to A);
     over the real bass 1 34, 5 22, b7 19, 4 16 %; intervals 4ths/5ths 70, octaves 13, thirds 11, steps 5, repeats 2 %
     (48, 22, 6, 12, 9: our head's content); as played centroid 439-450 Hz (381: the median note is 3 semitones higher),
     flatness 100 Hz-5 kHz -40.8 to -48.1 dB (-40.4), -40 dB bandwidth 0.9-2.0 kHz (0.86), above 5 kHz -58.5 to -69.2
     dB (-53.2); restart dip at most -2.3 dB in the first 5 ms (was 8-21 dB in round 2). Above 12 kHz (compare.py,
     relative): Seq -71.8, copies -56.7 and -64.4 dB, hats -52.1; the spectrogram is empty above the drums' ceiling.
     compare.py against Nether (the loop): sub band 68 % (50), centroid 247 Hz (591). WAV and MP3 19:13 (theremin).
   - Tool notes: melodic.py on our songs misreads the samples (it takes the WAV's rate as the C-5 rate, so 44.1 kHz
     candidates print 20 semitones low; with 22 kHz WAVs it read the IT loop in the wrong units), reads the sub's
     E-2 notes as F (the kick's pitch drop), counts same-channel re-strikes as notes, and reuses
     `melodic_cache_<name>.npz` when present (delete it after a rebuild; the stale rift cache was removed and the
     `rift` entry lists the sequence). Candidate builds for measurement live in `scratch/ut99-clean/ours/rift/cand/`
     (lines.json `rift_seq_*`). VSCO 2 and VCSL files may sound an octave above their names (the glass confirmed); if
     VSCO's do, Nadir's string beds sit an octave above their voicing: not checked further.
   - Layer 2, the lead call, built 20:23 (two rounds, each checked by an independent agent). **Picked 20:32:
     `lead_rhodes`** (written with U; lead_harp rated four stars; no notes, no unwritten mix): channels 12-13 (Lead A, Lead B, centred: Nether's lead renders centred because its sample's own pan overrides
     the channel's), slot 9, instrument 9, written by `suite/rift/gen_lead.py pattern`. Nether's idioms from the checked
     measurement and its cells' articulation (read without its notes): one call per pattern in bar 1, three notes on the
     8ths from row 2 on two alternating channels at v30, each channel re-striking its last note +4 and +8 rows at v14 and
     v8, a variant with two new notes at v14 each re-struck once (loop_b), the same written fades after every note (D03
     for three rows after a v30 note, D01 after a v14, the row-12 re-strike's D01 two rows on), cut on row 32. Our notes:
     E C A (E-5 C-5 A-4), variant + D G; E D A was dropped because its two intervals open one of Nether's calls (a scratch
     guard compares shapes and prints counts only). Candidates: `lead_cry` (placeholder; Dexed Annie'sCry trimmed, its own
     20 c vibrato), `lead_rhodes` (Dexed FmRhodes18 trimmed), `lead_suffer` (Surge Zoozither Suffer as a one-shot),
     `lead_harp` (VSCO 2 harp F4, CC0), `lead_tile` (OB-Xd Tile Drop): five of sixteen finalists from three parallel
     screens of about 1100 patches and files (recipes in `samples/local/rift-cand/lead/`: Dexed params inline, Surge edits
     written into .fxp copies because Surge re-applies a loaded patch over host params). `gen_lead.py` makes each like
     Nether's lead sample: a 5.57 s one-shot sounding D-4 (played 5-14 up), band-limited at 2.1 kHz, a 2 ms fade-in,
     irregular vibrato (21 c around 2.1 Hz, from band-limited noise) where its own is under 10 c and irregular level
     wobble (3 dB around 1.6 Hz, faded in over 0.4 s so the onset stays the peak) where its own is under 2 dB, both
     measured the way melodic.py does (its YIN copied in), a floor at Nether's -19.9 dB (measured at 4.41 kHz: melodic's
     fixed FFT reads a pure tone as -0.2 dB at 44.1 kHz), a gain per candidate.
     Measured (nothing heard): 10.6 dB under the sub for cry, rhodes and suffer, 11.0 harp, 11.6 tile (their transients
     hit the -1 dBFS peak limit first; Nether 10.6), 14.9-15.9 under the mix (15.2); 75 % of notes articulated, shapes
     fade 50 / dip 25 / flat 25 % (Nether 76 %, the same shapes); stored vibrato 15-20 c with prominence 2-12 (21 c, 3.0),
     level wander 2.0-3.4 dB (3.3), onsets 0-30 ms to -3 dB (10), tails 3.3-5.1 s (5.15); as played centroid 263-271 Hz
     (337: our call sits 3-4 semitones lower), flatness -39.0 to -42.6 dB (-35.3), above 5 kHz -67 to -68.5 dB (-55.9;
     Nether's top comes from images of its 4.2 kHz storage, which our band-limited compile does not make); note-start
     energy above 7 kHz within 3 dB of the held note at the median (was 26-28 dB over before the fade-in). No clash rows
     added; nothing clips (mix peak 0.634). Kept as they are and reported: the row-14 re-strike rings to the row-32 cut
     8-17 dB louder than Nether's (our lower call plays the sample slower; faster-decaying voices ring less), and the
     call shares a pitch class with the sequence in 25 % of sounding pairs (Nether 6 %), mostly that ringing A or G.
     WAV and MP3 20:23 (cry in the slot).
   - Layer 3, the tonal hit, built 21:34 (four rounds, each checked by an independent agent). **Picked 21:37:
     `hit_bells`** (written with U; no ratings, no notes, no unwritten mix): channels 14-15 (Hit A, Hit B, centred), slot 10, instrument 10, written by `suite/rift/gen_hit.py pattern`:
     Nether's idioms (one hit on row 0 of every bar alternating two channels so each rings two bars, A-5 v64, started
     2.3 % into the sample with O0F), sounding A +60 cents because the samples are stored at G-5 +60 c (Nether's hit sits
     43-85 c over its root, between the root and the minor second; an F trait, followed now). Candidates: `hit_vibes`
     (placeholder; OB-Xd Vibes, partials 1-2 with its own 3 Hz beating), `hit_tape` (Surge Cybersoda Tape Keys as a
     one-shot), `hit_kalimba` (VCSL kalimba, CC0), `hit_bells` (Surge John Valentine Handbells, FM inharmonic),
     `hit_mayan` (Dexed Mayan Vibs): five of thirteen finalists of three screens (468 sounds; recipes in
     `samples/local/rift-cand/hit/`); the VCSL tube bell was dropped after the first check (its pitch reads an octave low
     and it swells). `gen_hit.py` makes each like Nether's hit sample, measured the way melodic.py measures (its numbers
     reproduced on Nether's WAV): 3.82 s, band 2 kHz, an irregular 5.9 Hz pitch wobble of 31 c (topped up where the sound
     already moves at that rate), drift set to -7 c/s, an irregular 12 Hz level flutter of 3.1 dB (all measured over
     melodic.py's steady part: from -3 dB of the peak, up to 1.5 s, while within 30 dB), noise shaped like the
     sound for Nether's floor (-8.6 dB) and a hiss to 9.5 kHz for its share above 5 kHz as played (-53.1 dB), the offset
     frame on the nearer side of a zero crossing (within 1 % of the peak), fades last, a gain per candidate; the 87 ms the offset skips is held under the played part's
     peak (the kalimba's pluck lives there). Tried and dropped on the way: a pink floor (-28 dB flat as played against
     -37) and a hiss set for the stored whole-band flatness (10-13 dB too much above 5 kHz, and a faint band to 12.3 kHz).
     Measured (nothing heard): 12.4 dB under the sub for all five (Nether 12.4); as played, energy above 5 kHz -53.0 to
     -53.4 dB (-53.2), flatness 100 Hz-5 kHz -40.2 to -44.7 dB (-37.1), centroid 458-491 Hz (575); stored floor -8.5/-8.6
     (-8.6), whole-band flatness -49.6 to -52.2 (-45.5), wobble 27-37 c at 5.5-6.7 Hz with prominence 2.3-5.1 (31 c at 5.9,
     3.6), drift -4 to -8 c/s (vibes -18 over its first second, cut short by its beating dip; -7.3), flutter 2.7-4.5 dB
     at 11-14 Hz (vibes keeps its own 3 Hz pulse; 3.1 at 12),
     off-harmonic peaks 8-25 (63); partials, noise curve and decay stay each source's own (decay 5-13 dB/s against 5.9;
     tape is closest). Above 12 kHz the hit channels read -66 to -67 dB of their power (hats -52); the spectrogram is empty
     above the drums' ceiling; mix peak under 0.66. In this 8-bar test all layers sound together, so the hit's A +60 c sits
     against the sequence's A on 38 of 128 rows; Nether never plays its hit with its sequence (orders 0-25 against 31-52),
     which the full form will follow. Nether also thins the hit to two a pattern without the offset in some sections:
     form work, not in the loop. WAV and MP3 21:34 (vibes in the slot). Tool note: melodic.py's "as-played check"
     misreads every Rift layer (it ignores the base-note tuning); measure pitches on the render.
   - Next (a continuation prompt was given to the user): ask the open questions on the approved sounds' departures,
     then layer 4 (surround bed, the user's approved sound: ask first) or layer 5 (strings). Measurement helpers from
     this session are in `scratch/ut99-clean/rifttools/` (README.txt).
   - 2026-09-22, late: the open questions answered: "whatever I already built the song with is fine" (break, stab,
     hats, bed_endgame and their levels stay; do not ask about approved sounds' departures again), the sub stays on A.
     So layer 4 is the approved bed as it is; layer 5 (strings) is next.
   - Layer 5, the strings, built 2026-09-22 late to 09-23 (three rounds, each checked by independent agents). **Picked
     2026-09-23 00:21: `str_viola`** (written with U; no ratings, notes or unwritten mix): channels 16-21 (Str 1-6), slot
     11, instrument 11, written by
     `suite/rift/gen_strings.py pattern`. Nether's idiom from its cells (counts only; BRIEF.md now carries the corrected
     reading): two three-voice groups a pattern, one on row 0 (ch 16-18), one on row 32 (ch 19-21), each held 32 rows and
     faded from the other group's strike (D02, then D00 for 18 rows), S87 on every note (one shared pan: the brief's
     "voices panned apart" was wrong), the sample's own volume. Our chord: the reference's colour (a major seventh on the
     minor sixth: F A C E over A), voiced F-4 C-5 A-5 / E-4 E-5 A-5 (5 under to 12 over the stored A-4). The first voicing
     (F-4 C-5 E-5 / A-4 C-5 F-5) put 5 of 6 voices where Nether's sit once the guard used sample 17's sounding pitch (it
     sounds 3.7 st under its written note); `scratch/ut99-clean/rifttools/chordcheck.py` (counts only) now reads 0
     identical group stacks, 3 of 6 voices, no group holding the major seventh (theirs 0 of 8). Kept departure, the
     guard's price: our groups span 16-17 semitones (theirs 7-9), two semitone pairs meet across the groups (theirs one).
     Candidates in the tryout (slot 11): `str_viola` (VSCO 2 viola section D3 v2, CC0; Nadir's beds use v1), `str_cello`
     (Surge Dan Maurer "Overdriven Cello", noise through a resonator), `str_fmstg` (Dexed SynprezFM_19 "STG 3"), `str_pwm`
     (OB-Xd "Strings IV OB-Xa", the PWM oscillator alone), `str_comb` (Surge Dan Maurer "Comb String Section"): five of
     seventeen finalists of three screens of 1032 recordings and patches (recipes and screen.txt in
     `samples/local/rift-cand/strings/{rec,surge,dx_obxd}/`; the rejected Nadir/Rift sources skipped; Violini Poly left
     out as a relative of the rejected Violini Solo). The screens were relaunched at A-4 once the reference's sample
     measured about 25 harmonics in its 5.3 kHz band (a note near 210 Hz, not 440).
     `gen_strings.py` makes each like Nether's string sample, measured with melodic.character at its 15986 Hz storage
     rate (calibration: `gen_strings.py ref` reproduces its figures): 4.05 s, a forward loop of 1.85 s from 2.20 s (407
     whole cycles of A-4; the loop's last 0.2 s blended into what precedes it with gains set by the two parts'
     correlation), a swell through -24 dB at 0.1 s and -10 dB at 537 ms to the loop's level (the -3 dB point sits where
     the loop's level wander crests, 0.1 s in, as the reference's does), band-limited at 5.3 kHz, a vibrato of 7.7 c and
     a level wander of 2.0 dB around 2.9 and 1.7 Hz, irregular and periodic with the loop, added only where the sound
     moves less (the level wander spreads to 15 Hz only as far as the floor allows), a floor of -23.9 dB (shaped noise,
     periodic with the loop) where the sound is purer, the loop level held flat, tuned by melodic's median pitch or by the
     loop's harmonic lines where partials 1-3 agree, a gain per candidate.
     Measured (nothing heard): 8.6 dB under the sub for all five (Nether 8.6), 10.4-11.1 under the mix (12.8 in Nether's
     louder peak); attack 507-537 ms to -10 dB (537), -3 dB at 2.16-2.39 s (2.308; the pre-loop swell is held under
     -3.2 dB of melodic's own peak reading until 50 ms before the loop); floor -23.8/-23.9/-23.9 for viola, pwm, comb (-23.9), cello -21.6 and fmstg -17.4 their own; vibrato cello
     7.6 c, comb 7.8 c (7.7), viola 13.2 c at 3.7 Hz, fmstg 13.3 c at 4.1 Hz, pwm 10.6 c at 4.5 Hz their own (nothing
     added), cello's rate reads 5.2 Hz (its own 5.5 Hz shimmer through the spread wander); level wander 1.7-2.2 dB at
     1.2-1.8 Hz (2.0 at 1.7), prominence 5.6-86 (3.2: a broadband wander would raise the floor); bw40 3.8-5.3 kHz (5.3),
     centroid 351-591 Hz stored (438); pitch: viola -0.4, cello -0.1, pwm +0.6 c; comb's partials on 407 cycles (-0.3 to
     0.0 c; YIN reads -3.4); fmstg YIN -0.4 c, its FM partials stretched (-8.5/-4.3/+1.3 c). As played: centroid 554-855
     Hz (509), flatness 100 Hz-5 kHz -14.7 to -25.2 dB (-17.0), -40 dB band 7.9-10.6 kHz (7.0), above 5 kHz -17.1 to
     -26.7 dB (-28.0): brighter than Nether's, the top voice sits 12 over the stored note (theirs 8). Loop wraps 0.08-0.62x
     the loop's own roughness; the blend's lowest point sits above the rest of the loop's; wrap steps 1.0-2.1 dB, inside
     each loop's own 50 ms steps. Above 12 kHz the Str channels read -65 to -69 dB (hats -52); the spectrogram shows a
     faint line to 10.6 kHz from the A-5 voice, under the drums' top; mix peak 0.659 (0.653). clash.py (now following D
     volume fades to melodic.py's audible end, max(2, strike volume / 8), and leaving muted channels out; the app's table
     does neither) 88 of 128 rows (7 before): the bed's E against the strings' F on 82 (form work: Nether's bed is out
     where its strings play), string against string 9-18 a pattern
     where the groups overlap (the colour; Nether's strings clash on 242 of 256 rows by the old rule). Onsets: str_cello's
     first second is noise-dominated (its resonator building up), str_cello and str_comb onsets 8-13 dB brighter than
     their loops: the sources' own, reported. The candidates' level wanders share one shape (the strongest line at 1.7
     Hz, cresting 0.1 s into the loop), by design. Third check (2026-09-23): every earlier fix holds; the -3 dB hold and
     clash.py's audible end were fixed after it. WAV and MP3 2026-09-23 00:15 (viola in the slot).
   - Layer 6, the drone, built 2026-09-23 (final build 06:35; ten check rounds by independent agents, every finding fixed
     or reported; the tenth reproduced all five WAVs bit for bit and found notes only). **Picked 2026-09-23 11:14: `drone_ahhs`** (written with U; no ratings, notes or unwritten mix; so
     layer 8's vocal pad needs a timbre distinct from this vowel pad). Channel 22 (Drone, pan 29), slot 12, instrument 12 (sample mode), written by
     `suite/rift/gen_drone.py pattern` (do not hand-edit channel 22; channels 1-21 unchanged). Nether's idiom from its
     cells (counts only; `scratch/ut99-clean/rifttools/artic.py 24` prints them with notes and pitch-bearing parameters
     blanked; BRIEF.md's layer-6 correction): its 18 drone notes carry **one written pitch**: one chord sample struck in
     order 31 and restated with the instrument by a legato note (GFF) on row 0 of every later pattern (32-48), never
     moved; the movement is the volume column: a v7 entry swelled one step a row to v30 over 24 rows, nine flat v30
     patterns, then (with the vocal pad and the second line, orders 41-48) patterns alternating a v30 note row swelling to
     v40 over 16 rows and a v40 hold; pan 29; D02 then D00 to silence in 49. The earlier entry's "7 distinct cells" and
     "moves ours to write" came from melodic.py reading the chord's pitch on the render. The loop takes the alternation
     (loop swells, loop_b holds; the wrap is the reference's v40->v30 step); the entry swell (write it without G), the
     flat v30 patterns and the fade are form work. Our chord: A minor voiced A-3 E-4 A-4 C-5 inside the sample (stored at
     A-3), held on A, no moves (the reference's idiom; `gen_drone.NOTES` is one line if moves are wanted).
     `rifttools/dronecheck.py` (counts only, sounding pitch): 0 of 17 / 0 of 2 moves, the same chord quality on the root
     (a minor triad: a G trait), at most 2 of 4 voices shared (our third an octave higher, the root doubled), 0 tones
     outside our chord in any candidate.
     Candidates (slot 12): `drone_lushpwm` (Surge Dan Maurer "Lush PWM Strings", steadied: a still pulse/wavetable pad),
     `drone_tables` (Surge Inigo Kennedy "Tables Turning", stock; its own 1.9 Hz swing is its +-15 c octave layers
     beating), `drone_ahhs` (Surge "Poly Ahhs" without its vibrato LFO: a vowel/formant pad), `drone_fmvoice` (Dexed
     SynprezFM_18 "VOICE 2", carriers undetuned, modulators on whole ratios), `drone_churchlike` (Surge Malfunction
     "Churchlike", stock: a noise-excited organ with its own 5.1 Hz rotary): five of fourteen finalists of three parallel
     screens (925 Surge patches, 621 Dexed voices / OB-Xd programs, 204 chords from 208 CC0 recordings, all rendered as
     our chord; recipes and screen.txt in `samples/local/rift-cand/drone/{surge,dx_obxd,rec}/`; screened by scalar class
     figures, never spectral likeness). Changes after the screens, all from the checks: (1) steady pitch: YIN finds no
     period in a chord, so the screens' "vibrato <= 12 c" never applied; per-tone measurement
     (`rifttools/tonevib.py`: each tone's periodic part; the reference's tones pass) found Poly Ahhs' LFO1 vibrato (5.2
     Hz, 45 c), Lush PWM's pitch LFOs, oscillator detune and PWM/skew LFOs (its root moving 90 c at 2.2 Hz) and VOICE 2's
     detuned carriers (15-28 c); `drone/steady.py` re-rendered them steady (Lush PWM: take 3 of four of the pwm_off
     variant; with nothing modulating, its takes differ by a static comb, 3-9 dB on the chord's fundamentals); their own
     floors are then purer (-52/-48/-48 dB), so their -13.7 dB floor is mostly the added noise. (2) The recordings
     screen's finalists were cello-section chords only: every VSCO 2 cello take carries vibrato (31-94 c per tone,
     coherent), outside the steady class; horn chords lose their roots' fundamentals (the chord reads with E at the
     bottom); `rec/drone_cello.wav` (built without Nadir's bed takes) stays there, none of the five is a recording.
     (3) OB-Xd "WindSong" (obnoise) measured nearest tables after processing; the organ took the fifth slot (by one
     distance set it is the farther, by another it sits nearest fmvoice; its own rotary, which neither reads, decided
     it); `gen_drone.py drone_obnoise` still makes obnoise.
     `gen_drone.py` makes each like Nether's drone sample, measured with melodic.character at its 8353 Hz storage rate
     (`gen_drone.py ref` reproduces its figures): 6.26 s, a forward loop of 3.86 s from 2.39 s (425 root cycles; the
     tone's last 0.4 s blended), band-limited at 2.2 kHz, nothing under 20 Hz, the chord tuned on its tones' centres, a
     -13.7 dB floor (noise shaped like the sound, above 108 Hz, periodic with the loop, meeting the loop exactly at its
     start), a slow wander band by band (the reference's loop moves as an irregular 0.8-2.6 Hz wander strongest at 1.3 Hz,
     1.43 dB in 0.6-3.2 Hz, its bands 100-300/300-700/700-2200 Hz spreading 2.22/1.75/0.97 dB nearly uncorrelated;
     melodic's "2.06 Hz, prominence 9.4" is a one-loop window effect, the loop played twice reads 1.28 Hz): three draws
     on the loop's lines from 0.6 Hz, uncorrelated with each other and with each band's own movement, each band topped
     up over its own movement, the draw nearest the reference's melodic readings, slope and centroid movement; the
     reference's swell read over all 83 block phases on a sliding envelope (-21 dB, a -14 dB plateau, -10/-3 dB knots
     scanned to the reference's phase means, a crest at 0.81 s under the loop's top, then its pre-loop level 0.7 dB under
     the loop's); a gain per candidate. Measured (nothing heard): 9.56-9.66 dB under the sub (whole-song power, channels
     soloed; the layer plan's whole-song figure 9.6; the reference's orders 41-48, the alternation the loop takes, read 8.7, its v30 holds 11.2),
     12.2-12.3 under the mix; attack means over the 83 phases 279-284 / 568-575 ms against the file's and the loop's top
     (reference 284.6/572.4), 270-290 / 570-600 ms as melodic.py reads the stored files; the file's peak before the loop
     in 0-11 % of phases (13 %); crest -0.66 to -0.85 dB (-0.59); pre-loop level -0.70 dB (-0.74); floor -13.7 dB;
     0.6-3.2 Hz 1.42-1.46 dB; loop played twice 1.28 Hz (lushpwm, fmvoice, churchlike), 1.33 (tables, ahhs); band spreads
     lushpwm 1.95/1.53/0.84, tables 1.56/1.73/1.18, ahhs 2.42/1.92/1.57, fmvoice 2.15/1.68/0.93, churchlike 1.94/1.53/0.84
     dB (tables' and ahhs' upper bands are their own), correlations within +-0.28; centroid moving 14/3/25/25/13 Hz (24;
     where 80 % or more of a sound's power sits under 300 Hz it moves less); sources' per-tone periodic parts under 12 c
     (tables' A-4 beat 10.5-11 c, at the limit; on the finals tables' beat and fmvoice's floor jitter read just over it);
     wraps 0.04-1.47 % against the loops' own 0.59-2.92 %; tuning within 1 c. As played: centroid 199-312 Hz (281),
     flatness 100 Hz-5 kHz -48.6 to -55.3 dB (-23.5), bw40 1.1-2.2 kHz (2.5), above 5 kHz -70 dB (-50.9: its 8-bit
     storage noise and images); above 12 kHz the Drone channel -72.4 dB (hats -52.1); the spectrogram is empty above the
     drums' ceiling; mix peak 0.651 (0.653); clash.py 88 of 128 rows (the drone adds none; its E meets the strings' F on
     the bed's rows, and in the loop it doubles the bed's A-3 E-4 C-5: form work, Nether keeps drone, bed and strings
     apart). Closest pairs: lushpwm-fmvoice and fmvoice-churchlike (churchlike differs mainly by its rotary). Kept
     departures (report only): partial tables, flatness/noise curve, the post-crest dip, each sound's own movement
     (bands and under 0.6 Hz), the purer own floors, a -50 to -75 dB trace under 104 Hz from the root's own sidebands
     under the wander (tables' own -39 dB), attack spreads over the phases wider than the reference's. If `drone_ahhs` is
     picked, layer 8's vocal pad needs a distinct timbre. Tool notes: melodic.py's pitch and interval lines misread a held
     chord (use the render); its partial interpolation was fixed 09-23 04:00 (a parabola only through a true maximum;
     reports made before used the old one); `gen_strings.py` has the pre-loop noise step the drone's first check found
     (str_viola's wrap 4 % of RMS, 0.62x its own: approved, not changed); new helpers `rifttools/{dronecheck,artic,
     tonevib}.py` (README.txt); `lines.json` has rift_drone_* entries (the strings line 11 now registered by
     cand_builds.py). WAV and MP3 2026-09-23 06:35 (lushpwm in the slot); rebuilt 11:18 with the pick.
   - 2026-09-23 11:14, with the pick, the owner set the string channels' volumes in the app (the viola was too loud):
     Str 1-6 at 34/26/18/40/18/22 (were 64); the strings now sit 16.7 dB under the sub (8.6 before; voices 20.9-24.8).
     Every `gen_*.py pattern` used to rewrite its channel lines at volume 64 (gen_strings.py would have undone this):
     all five now keep an existing channel line and only add a missing one (all five re-run leave rift.yaml byte
     for byte).
   - Layer 7, the noise, built 2026-09-23 (final files 16:07-16:13, song 16:14; five check rounds by independent agents,
     every finding fixed or reported; the fifth found text and log lines only, fixed after it with the WAVs unchanged
     byte for byte; a sixth, text-only check of those edits, 2026-09-23 evening, reran the generator into scratch: the five
     WAVs byte-identical and the log line for line; its six text items, docstring figures and wording in gen_noise.py and
     cand_builds.py and one sentence here, fixed in text). **Picked 2026-09-23 16:46:
     `noise_faraway`** (written with U; no ratings, notes or unwritten mix; every writer leaves the song byte for byte; WAV
     and MP3 rebuilt 16:54). The owner's caveat with the pick: the tryout's 8-bar loop strikes the noise once, so a pick is
     judged on about one hearing and repetition over the form is hard to judge; revisit it if the laid-out form makes it
     read too repetitive. Channel 23 (Noise, pan 32 in the header), slot 13 (base_note B-3), instrument 13 (sample mode), written by
     `suite/rift/gen_noise.py pattern` (do not hand-edit channel 23): `A-3 13 ... S89` on row 0 of `loop`, nothing in
     `loop_b`. Nether's idiom from its cells (`rifttools/artic.py 1`, counts only; BRIEF.md's layer-7 correction): one
     note on row 0 of each struck pattern, one written pitch for all 19, the sample's own volume (no volume column, no
     fades), S89 (pan 38) on the note row (alone only in the pattern after a strike in orders 7, 9, 34, 38); struck every
     pattern in orders 0-6, every second in 8-18 and 24-30 (none in B), every fourth in C (33, 37); the loop takes every
     second pattern. The plan line understated it: a held noise with a late fade (hold 1.4 s, -10/-20/-30 dB at
     2.9/4.6/5.0 s), two resonances 16-20 dB over the noise (one on the root as played), 25 % of its power under 104 Hz as
     played, played 2 semitones under its stored rate (5.77 s).
     Candidates (slot 13): `noise_faraway` (Surge Inigo Kennedy "Faraway Tree", its noise generator soloed through the
     patch's own filter), `noise_wind` (OB-Xd "Wind at -50 C": a band-pass swept by a 0.16 Hz LFO), `noise_deepnote` (Surge
     Rare Earth "Deep Note": six detuned window oscillators, aperiodic), `noise_saturn` (Surge Inigo Kennedy "Saturn V":
     sines ring-modulated by S&H noise, one resonance sounding 440 Hz), `noise_timproll` (VSCO 2 timpani roll, CC0: drum-head
     modes, the tuned one sounding 220 Hz): five of eleven finalists of three parallel screens (2331 Surge renders of 977
     patches, 1310 Dexed/OB-Xd renders of 593 voices and programs, 1294 takes of 251 CC0 recordings; the shared class
     measure `samples/local/rift-cand/noise/measure.py`; recipes and screen.txt in `samples/local/rift-cand/noise/
     {surge,dx_obxd,rec}/`), one per kind, the five farthest apart. Left out: Space FM (sidebands on every pitch class),
     the Cybersoda sax model's S&H breath noise (near layer 8's breathy pad), Sea Pipe (slow onset), Dexed OffTheWall (45 %
     under 104 Hz), OB-Xd Claps and Wurlitzer noise (faraway's kind).
     `gen_noise.py` (its docstring has every step) makes each like Nether's noise sample, read with melodic.character at its
     16217 Hz storage rate through an FFT resample (vulturetracker's resampler cuts at 0.45 of the new rate and read the
     reference's -60 dB bandwidth as 7170 Hz): stored at B-3 and played at A-3 (the reference's 2-semitone relation), the raw
     take's strongest resonance tuned onto B (sounding A); nothing under 20 Hz or over 8.1 kHz; nothing generated or moved
     under 104 Hz as played (116.7 Hz stored) but the gains' start-edge spill; a floor to -3.5 dB where purer (none was);
     band movement (125.7-300, 300-700, 700-2200 Hz stored, 50 ms levels over the held part, ten block phases) topped up
     where a band moves less than the reference's (2.97/1.31/1.47 dB, nearly uncorrelated), bounded by the whole level
     movement (the larger of 1.76 dB and the take's own on the finished frame, plus 0.1), a second depth after the held part
     for the reference's 2.41/1.63/1.11; of 12 draw sets (seeded by the candidate's name) the one meeting the onset maxima,
     then its loudest block in its first 0.5 s, then no re-swell, then the nearest correlations; the onset matched over
     all 162 block phases (maxima 0/10 ms, means 0.0/3.3; a start trimmed at most 40 ms; wind's rise lifted above the
     split); last a smooth roll-off solved for the -40/-60 dB bandwidths 3860/7570 Hz; 5.14 s with a 0.2 s end fade; a
     gain per candidate. Log of the final build: every figure below; `gen_noise.py ref` prints the calibration.
     Measured (nothing heard): 12.0 dB under the sub for all five (Nether 12.0), 14.4-14.5 under the mix; every file meets
     the screens' class limits; attack maxima over the 162 phases 0/10 ms (wind 0/0); stored floor -0.2 to -2.4 dB (-3.5:
     all noisier), flatness -22.3 to -25.2 (-21.3), centroid 355-545 Hz (401), aperiodicity 0.53-0.87 (0.59), bw40/60
     faraway 3977/7495, wind 3831/7449, deepnote 3963/7586, saturn 3468/6604 and timproll 3480/7113 (theirs, narrower;
     3860/7570); melodic level movement 1.58-2.56 dB (1.76; the bound on each finished frame met); band movement held part
     faraway 2.04/1.43/2.40 (band 1 limited by the whole-level bound), wind 2.93/1.33/1.82, deepnote 2.98/1.33/1.51,
     saturn 2.96/1.34/1.53, timproll 2.04/1.73/2.05 (bound) against 2.97/1.31/1.47; re-swell after the held part within
     the caps. As played (melodic's as-played lines): 5.77 s, 16 beats (Nether 17: the length is matched in seconds, our
     tempo is slower), centroid faraway 379, wind 481, deepnote 458, saturn 364, timproll 404 Hz (the plan's 384; the
     reference's sample alone reads 438 by that measure), flatness 100 Hz-5 kHz -16.5 to -18.9 dB (-13.0), -40 dB
     bandwidth 3402-3779 Hz (4721), above 5 kHz -41.7 to -48.3 dB (-37.4); under 104 Hz as played faraway -13.0, wind
     -12.5, deepnote -51.4, saturn -6.8, timproll -26.1 dB of the whole (the takes' own; the generator's spill -54 to -76
     dB of the whole); above 12 kHz -63 to -72 dB (hats -52); the spectrograms empty above 8.1 kHz; mix peak 0.687
     unchanged; clash.py 88 of 128 (the noise adds none). Guard (`rifttools/noisecheck.py`, counts only): one written
     pitch and 0 moves on both sides; saturn's and timproll's tuned resonance on the root class as theirs is; 0 of ours on
     the class of their other resonance.
     Kept departures (report only; matching them would take the reference's partial table, noise curve or decay): decay
     curves (timproll's roll holds to the end fade, cut near full level; faraway's level barely falls before 3 s); the
     reference's bright first 0.4 s (-24 dB above 5.6 kHz, ours -39 to -57; half its 91 Hz centroid movement, ours 12-23 Hz
     but wind's own sweep 120); our darkness against the body at 2.2 kHz (faraway 5.8 + 2.8 from its roll-off, wind 14,
     deepnote 18, saturn 10, timproll 9 dB: the takes' noise curves; the bandwidths are read against the reference's
     resonance peak); wind's and deepnote's as-played centroids over 384; saturn's rumble under 104 Hz (-6.8 dB) and its
     resonance; timproll's modes within 1 dB (220 Hz tuned, 214 Hz beside it); the after-held bands the takes already move
     over the reference's (up to about +0.06 dB of it is ours: deepnote's top band from the held depth's 0.3 s taper,
     faraway's two lower bands mostly from the whole-file band masks carrying the moved held part into that span, about
     0.04 dB from the held depth reaching past the file's held end, which its roll-off moves 91 ms earlier).
     Tool notes: the app's sounding table (vulturetracker/gui.py `sounding_table`) timed a one-shot at C-5, ignoring the
     note (the noise dropped out of SOUNDING 2.43 s into its 5.77 s; the lead and hit were mistimed too): fixed on the
     owner's word 2026-09-23 (the length at the played note's rate, through the keymap) with a test in tests/test_gui.py
     (37 tests pass); clash.py unchanged at 88. `cand_builds.py` now copies every sample at its module C5 speed except the drone's chord (melodic.py reads
     every tonal line's pitch classes and the one-shots' lengths right; before, the sequence, lead, hit, stab, strings, sub
     and the noise's length were misread). Every `gen_*.py pattern` keeps existing channel lines (the owner's mix) through
     `gen_seq.ensure_channels`, which also re-adds a single missing line in place; `write_columns` pads generated columns so
     each writer leaves the others' bytes alone (rift.yaml's whitespace canonicalised once, cells unchanged). WAV and MP3
     2026-09-23 16:14 (faraway in the slot).
   - Layer 8, the vocal pad, built 2026-09-23 evening (final files 19:47-19:50, the WAVs rewritten byte-identical
     20:11-20:12 by round 4's log rerun; song 19:48; independent checks: rounds 1-4 found 38, 19, 15 and 12 items, all
     fixed or reported below; rounds 1-3 each rebuilt the five, round 4 changed printouts and text only; a fifth,
     text-only check of round 4's edits, 2026-09-23 late, reran the generator into scratch: the five WAVs byte-identical
     and the logs line for line; its six text items, one printout's wording in gen_vocal.py and five sentences here,
     fixed in text). **Picked 2026-09-23 22:46: `vocal_obghost`** (written with U; no ratings, notes or unwritten mix;
     obghost was already the song's placeholder, so the song's text and module are unchanged: rift.it byte-identical to
     obghost's candidate build; `gen_vocal.py pattern` leaves rift.yaml byte for byte; WAV and MP3 rebuilt 22:51).
     Longer listening renders, since one pass of the 8-bar loop is
     little to judge repetition on: `suite/rift/<cand>_x4.mp3`, each candidate's build played four times (46.6 s;
     `.gitignore`'s `suite/*/*.mp3` keeps them out). Channel 24 (Vocal, pan 32), slot 14 (base_note A#2), instrument 14
     (sample mode), written by `suite/rift/gen_vocal.py pattern` (do not hand-edit channel 24): `A-3 14 v05` on row 0 of
     `loop` swelled to v23 over 16 rows, `A-3 14 v23 GFF` on row 0 of `loop_b`. Nether's idiom from its cells
     (`rifttools/artic.py 27`, counts only; BRIEF.md's layer-8 correction): one written pitch for all 8 notes, played 11
     semitones over the stored rate; struck at v5 and swelled one step a row to v23 over 16 rows, restated by GFF at v23
     for three patterns, struck again; pan 32; D01/D00 to silence at the end. The loop takes a strike and a hold (its wrap
     is the reference's hold -> re-strike step); the strike every fourth pattern and the fade are form work. Our chord: A
     minor voiced A-3 E-4 C-5 (sounding), its lowest tone on the drone's (the reference's vocal sits on its drone's lowest
     tone as played); `rifttools/vocalcheck.py` (counts only, sounding pitch; the 11-semitone relation derived from the
     written note, BASE_NOTE and each WAV's smpl root; ours read at the reference's rate at 12 dB): 0 of 7 / 0 of 2 moves,
     both played 11 over their stored rate, the same chord quality on the root (a G trait), 1 voice shared at 9 dB (their
     loop reads 3 tones there; ours, read at 12 dB, 3, breathhum and bethbreath 4), 2 at 12 dB (the root and one more;
     theirs 4 tones); at 18 dB their breathy loop reads 12 tones, so the shared counts there mean little; 0 tones outside
     our chord in any candidate.
     Candidates (slot 14): `vocal_obghost` (OB-Xd "Ghost Hunter": one saw+pulse oscillator with a 16 Hz sine+S&H
     pulse-width LFO, which makes most of its floor, -8.1 dB with its mixer noise off; osc2 and the pitch LFO off),
     `vocal_breathhum` (our own model: a breathy nasal hum), `vocal_oowhisper` (our own model: a whisper over a weak
     voice, its aspiration as loud as the voice), `vocal_andespipe` (Surge Dan Maurer "Andes Pipes": noise into notch and
     comb filters beside a wavetable, a blown pipe), `vocal_bethbreath` (Surge Vincent Zauhar "Beth's Breath": wavetable
     and sine layers over the patch's own noise generators, its fifth-up wavetable muted): five of sixteen finalists of
     three parallel screens (1715 measured Surge takes, 1746 renders, of 1204 patches; 2334 Dexed/OB-Xd takes of 781
     voices and programs; 943 takes of our own source-filter voice models: neither the local CC0 libraries nor their
     upstream repositories hold a voice recording), measured by the shared `samples/local/rift-cand/vocal/measure.py` (the
     character figures read as stored at the reference's rate, the chord, pitch, hold and envelope figures as played;
     after the screens and the checks it gained a hold limit, the attack limits on the means over all 83 block phases,
     which reproduce the reference's 149.5/827.9 ms, and a second distance from drone_ahhs under 1 kHz, its vowel, beside
     the full-band one, which is mostly the vocal's energy above 1.1 kHz where the band-limited drone has little): at most
     one per kind, the five farthest apart (`vocal/finalists.py`, finalists.txt: the largest smallest pairwise distance
     over the figures gen_vocal keeps, aperiodicity, flatness, centroid and its movement, and the timbre envelopes; 1.98
     median distances). Sensitivity: three sets tie at 1.98, all limited by the oowhisper-bethbreath pair; the fifth
     member is andespipe by the lower pref sum (5.77 against obhaunt 6.03 and obflutes 9.44; a tie-break on the next
     distance would take obflutes); the kind rule does not bind here (the same three sets tie without it); the next set
     sits at 1.95. The nearest pair in the finished files, oowhisper and bethbreath, sits 1.92 dB apart by envelope (under
     the drone finalists' own nearest pair, 2.10), apart by floor (-2.9 against -7.9 dB), flatness (-19.4 against -33.4)
     and aperiodicity (0.62 against 0.40); the other pairs 4.4-12.7 dB. Every finished file at least 11.1 dB from
     drone_ahhs on the full band and 6.2 under 1 kHz (raw 11.2 / 6.4; the class needs 6.1 and 3.7, the drone finalist
     nearest drone_ahhs on each band: drone_tables 6.15, drone_fmvoice 3.73). Out after round 1: `pitchwhisper` and
     `schwabreath` (our models) sit within 3.7 dB of drone_ahhs under 1 kHz (3.5 raw; the first build's pitchwhisper file
     2.9), so the first build's pitchwhisper and obformant were replaced. Rejected sources skipped (Dark Whisper, the
     rejected hook's, and the rest); Poly Ahhs and the Rift candidates' patches left out, except the Cybersoda sax model
     the noise screen set aside for this layer (it failed the class). Close pairs left out: the models' choir and sigh,
     Surge's Choir For Tape (the Surge take nearest the reference's breath, floor -7.7 dB, aperiodicity 0.52: 1.8 dB by
     envelope from obghost; the best set with it reaches 1.63). obghost's floor, like OB-Xd VinCellOh!'s (ruled out as a
     bowed-string program), is mostly its oscillator's modulation.
     `gen_vocal.py` (its docstring has every step) makes each like Nether's sample, read with melodic.character at its
     8363 Hz storage rate through an FFT resample (`gen_vocal.py ref` reproduces its figures): the take stored 11
     semitones under (root A#2) so it plays at A-3 as the reference's does; the root's centre on equal temperament, then
     retuned by the root band's own period over the loop, so the loop holds whole cycles of what the root band plays
     (loop_period, the best correlation at the loop's lag: bethbreath's sat 0.51 cycle off, whose blend cancelled its root
     band in round 1's build; retuned -6.9 c, its loop now holding 126 cycles of its root band; the others -1.2 to +1.7
     c); after the tuning and the wobble a low-pass at 4061.5 Hz stored (-73 dB from the reference's storage Nyquist,
     4181.5 Hz; 7.9 kHz as played); 3.22 s stored, a forward loop of 127 root-note cycles (2.180 s) from 1.043 s; the loop
     held flat band by band around its middle (four bands; a take's own spectral sweep would restart at every wrap:
     obghost's 700 Hz-up band fell 12 dB across its loop and reset in the blend, round 1's spectrogram stripes; before the
     loop each band keeps the loop start's gain, obghost's -2.2/-0.2/+0.6/-7.4 dB, bethbreath's -3.2/-1.1/-0.3/+0.2, the
     others within 0.7 dB) and each band's last 0.4 s blended into what precedes the loop start, level-matched first (the
     reference's loop rises 0.56 dB/s and steps down 1.2 dB at every wrap: not followed); a pitch wobble (one time map for
     the chord, periodic with the loop, one sine on the loop's line nearest the reference's root line, 1.835 Hz stored,
     3.46 Hz as played) where the take's own root, read over 3 s of the take as played, moves less than the reference's 30
     c, capped so no other tone passes the larger of 30 c and its own plus 2 c and the floor reading stays within 0.5 dB
     of the larger of the reference's and the take's own; a -7.88 dB floor of noise shaped like the take's envelope,
     periodic, where the take is purer; band movement (100-300, 300-700, 700-2200 Hz stored, 0.6-8 Hz) topped up to the
     reference's 1.71/1.97/1.10 dB on draws whose lines carry each reference band's own per-line power (the draws alone
     read about 3.0/3.5/4.1 Hz by median against the reference's 2.8/3.3/4.0), above 70 Hz stored only (the root's
     fundamental, and the sub's side, not moved), bounded by the whole level movement on the finished file, the draw whose
     readings come nearest the reference's (level movement, tremolo rate once and twice, band correlations), plus 10
     per dB by which its loop peak, read after the roll-off, passes the -1 dBFS limit at the candidate's gain
     (gen_drone.py's rule; obghost and
     bethbreath, whose every draw passes it, took their lowest-crest draw); a roll-off toward the reference's bandwidths
     that moves the centroid at most 5 %, solved before the swell; the reference's swell over all 83 block phases (five
     knots, searched from four starts), nothing before the loop over the loop's lowest per-phase top; every filter after
     the loop forms runs on the sample as it plays (circular in the loop: a zero-padded roll-off put a 14-86 % jump at the
     wrap in the first build); a gain per candidate.
     Measured (nothing heard): under the sub breathhum, oowhisper and andespipe 11.9 dB (the plan's 11.9), bethbreath
     12.1, obghost 12.8 (the last two held by the -1 dBFS peak limit: their loops' own crest, 12.0 and 12.6 dB over their
     RMS); 14.4-15.4 under the mix (14.0); attack means over the 83 phases 148.6-149.7 / 827.8-828.1 ms (149.5/827.9), the
     file's peak inside the loop in every phase (as the reference's); spans before the loop obghost -7.58/-2.69/-0.37,
     breathhum -7.09/-2.59/-0.29, oowhisper -6.97/-2.67/+0.17, andespipe -7.14/-3.00/-0.01, bethbreath -6.79/-2.53/-0.48
     dB (-6.78/-2.67/-0.92: the attack means matched, the spans as near as the knot search found; the loops' 10 ms tops
     sit 4.5-5.4 dB over their RMS against the reference's 4.6); floor -7.88/-7.90 (bethbreath, andespipe: noise added),
     breathhum -7.43 and obghost -7.10 their own (obghost's wobble lifts its floor reading 0.5 dB, the guard's limit),
     oowhisper -2.86 (its own, noisier: gen_vocal only adds noise); aperiodicity 0.30-0.62 (0.51); flatness andespipe
     -14.5, bethbreath -33.4, the others -19.4 to -24.0 (-22.1); centroid as stored 246-399 Hz (290; obghost 399 its own);
     level movement 1.74-2.83 dB (1.83; breathhum's 2.83 its own); band movement obghost and bethbreath at the reference's
     in the bands moved, the rest 1.23-1.38/1.41-1.69/0.86-0.94 dB (held there by the level bound), their slow parts
     centred at 2.5-4.0 / 2.5-4.7 / 3.3-4.0 Hz as stored (the reference's 2.8/3.3/4.0; each take's own movement shares
     them); pitch movement over 3 s of the take as played: andespipe 5/5/3 c -> 30/29/29 with a 26 c wobble (its floor
     reading -11.6 -> -9.2 dB), obghost 6/4/2 -> 14/11/11 with 10 c (deeper lifts its floor past the guard), breathhum
     26/36/29 -> 27/35/31 with 2 c (its C passes its cap from 4 c: 34 against 32 c; its E only from 44 c), oowhisper
     44/30/38 and bethbreath 45/34/27 their own (they move as much); the step across the wrap band by band within each
     band's own 20 ms steps inside the loop (95th percentile, sliding) but bethbreath's 300-700 Hz band (+4.5 against
     4.4); inside the blend region no band's 20 ms level falls more than 1.4 dB under its lowest elsewhere in the loop
     (obghost's 300-700 Hz band; round 2's cancelling blend read 6.5 dB under); loop wraps 0.00-2.28 % of the loop's RMS
     against their own steps 1.1-10.6 % (loopscope compiled the same), the first pass into the loop 0.04-2.28 %; under 104
     Hz as played -30.0 to -51.5 dB of the loop (the takes' own, nothing generated there); as played (melodic): centroid
     457-732 Hz (556), flatness -12.9 to -24.1 (-17.0), bw40 3133-6665 Hz (4667), above 5 kHz -40.9 to -59.0 dB (-37.8),
     andespipe -21.5 (its comb noise near the band top; the 5 % centroid cap stops its roll-off at 3148 Hz); the soloed
     vocal's spectrum within 60 dB of its peak ends at 4.7-7.7 kHz (hats 11.8 kHz), above 12 kHz -69.2 to -70.1 dB (hats
     -52.1); `check` OK; mix peak 0.676-0.713; clash.py 88 of 128 (the vocal adds no clash row: its E meets Str 1's F on
     the 82 rows where the bed's and the drone's E already do). The loop repeats every 1.15 s as played (9.6 passes after
     its 0.55 s entry in the 8 bars; the reference's own loop length): what the x4 renders are for.
     Kept departures (report only): the loop's flat level (the reference's rising slope), the takes' own partials,
     formants, noise colour and movement, oowhisper's noisier floor, obghost's higher centroid and its shallow wobble, the
     bands' held gains before the loop (obghost's attack 7.4 dB darker above 700 Hz than its take's own, so it swells into
     the loop's timbre), andespipe's bright top and low aperiodicity (0.35), bethbreath's dark band (bw40 1404 Hz stored:
     no roll-off) and its chord about 6 c flat by centre (-6.3/-5.8/-0.9 c; its lowest tone -17 c by vocalcheck: its loop
     holds 126 cycles of its root band), the attack spreads over the phases wider than the reference's, obghost's and
     bethbreath's level shortfalls from the peak limit. Tool notes: melodic.py reads the vocal's copy at its C5 speed (198
     kHz), so its sample line is not comparable with the reference's 8363 Hz line and YIN finds a spurious tuning in two
     copies (breathhum prints its notes A-1, andespipe A1; the other three A2 from the render; the class A is right in
     all): use gen_vocal's printout or vocal/measure.py; tonevib over a tiled loop reads loop-periodic breath jitter as
     periodic pitch movement (the finished loop's readings are printed as information only), and the reference's E reads
     25-48 c over one to three passes (its root 30-32: the cap uses the root); clash.py knows the vocal's chord;
     `cand_builds.py` registers the noise (13) and leaves the vocal and the noise out of the harmony, as Nether's
     lines.json does; the finished root readings are loop_period's retune and what follows it (bethbreath +1.2 c after the
     centre tuning, -5.2 after the retune, -6.3 finished; oowhisper's -1.7 is -0.6 left by the centre tuning and its
     -1.2 c retune; the other three equal their retuned readings, within 1.7 c).
     Checks: round 1 (three lenses: the generator, the song and text, the screens and the measure) found 38 items: the
     wobble decided before the loop was formed, a level step into every wrap from the blend, obghost's band sweep
     resetting at the wrap, the single-phase attack limits, the drone distance read on the drone's dark top, and text;
     all fixed, the choice rerun (two candidates replaced; the first build's zero-padded roll-off, which jumped at the
     wrap, and its centroid drag were fixed before round 1). Round 2 (two lenses) found 19: bethbreath's root band half a cycle off whole over the loop (fixed by
     loop_period), the draws' bump reading faster than the reference's rates (now the reference bands' own per-line
     power), the swell search stuck on one knot (more starts), andespipe's wobble on a line 25 % above the reference's
     (one line now), the measure's attack means 4.9 ms short (zero-padded now), the choice's scalar figures including two
     the generator sets (dropped; the same five), and text; all fixed, and the draw rule gained gen_drone's peak-limit
     term (obghost had fallen to 14.4 dB under the sub). Round 3 (two lenses) found 15: the peak term read before the
     roll-off (now after it; with the unsmoothed templates the same draws win either way, and obghost moved 13.0 -> 12.8
     dB under the sub from the two changes together), the draws' templates smoothed out of their band (unsmoothed now), no
     reading that would catch a cancelling blend (each band's 20 ms level range in the blend region now printed), a better
     swell start missed (other starts beat andespipe's middle span; a fourth start now), loop_period's parabola
     extrapolated past its scan (scanned wider, the best correlation kept), and text; all fixed. Round 4 (two lenses)
     found 12, none reaching the audio (its rebuild matched byte for byte): the wrap step still ranked on the 20 ms block
     grid, which named the wrong bands (now sliding 20 ms steps), blend_range's blocks starting 19.5 ms before the blend
     region (now ending at the loop's end), and text; all fixed, the logs rerun with the WAVs byte-identical. The fifth,
     text-only check (above) found the round-1 sentence crediting two fixes made before it ran, and wording.
   - Layer 9, the second line, built 2026-09-24: a first build (00:09-00:12) checked in round 1; the generator reworked
     on round 1's findings, the five re-chosen on its output and rebuilt; round 2's fixes rebuilt again (files 02:41,
     song 02:42); round 3: 19 items, four reaching the audio, all fixed and rebuilt (files 04:19-04:27, song 04:30; the
     eighteen regenerated, the same five chosen); round 4: 13 items, none reaching the audio (the five, their logs, the
     builds, the song and the choice reproduced byte for byte), the text fixed. **Picked 2026-09-24 05:35:
     `second_sine`** (written with U; no ratings, notes or unwritten mix; the tryout's slot-15 list cleared; rift.it
     byte-identical to sine's candidate build, `scratch/ut99-clean/ours/rift/cand/second_sine.it`; every
     `gen_*.py pattern` leaves rift.yaml byte for byte; WAV and MP3 rebuilt 2026-09-24 12:11). Listening
     renders: `suite/rift/<cand>_x4.mp3`, each candidate's build played four times (46.6 s; git-ignored by
     `suite/*/*.mp3`). The first build's dropped candidates (fmpiano, tuff, hollow, dxglass: their WAVs and x4 renders)
     are in `samples/local/rift-cand/second/prefix_build/`; piglet (in the five under an intermediate metric, never in
     the tryout) in `second/dropped/`.
     Channels 25-26 (Second, Second echo, both pan 32), slot 15 (base_note A#3), instrument 15 (sample mode), written by
     `suite/rift/gen_second.py pattern` (do not hand-edit channels 25-26). Nether's idiom from its cells
     (`rifttools/artic.py 28`, counts only; BRIEF.md's layer-9 correction): 32 main notes and 26 echo notes (the plan's
     "26 attacks" is the echo's count) in orders 41, 43, 45, 47 (every second pattern), alternating two patterns: six
     notes in bar 1 on rows 0 2 4 6 10 14 at v16 (its sample's default volume), the second glided into (G54), the sixth
     held and faded by the volume column to silence on row 43; the fuller pattern glides the held note on to a seventh on
     row 18 (G20, v14: the fade's level there) and ends with a three-note pickup on rows 58-62 faded out by the next
     pattern's DF2/D00; the echo repeats every note but the pickup 3 rows later at v7 (-7.2 dB) with its own fade; every
     note carries the sample's number, so the line plays at the sample's default pan, 32 (melodic.py read 29 before its
     default-pan fix, below); it plays its sample 6-18 semitones over the stored rate (median 13). Ours: the loop takes the
     fuller pattern (`loop`) and the rest after it (`loop_b`: DF8/D00, the pickup's fade), the other pattern being form
     work; every volume written x4 (the reference writes its sample's default volume, 16; ours is 64: the same in dB, and
     at v16 the -1 dBFS peak limit would hold the line about 5 dB under its level); our notes (A minor, sounding) B-4 A-4
     C-5 B-4 E-4 A-4, gliding on to B-4, the pickup G-4 A-4 B-4 (E-4..C-5: 6-14 semitones over the stored A#3). Guard
     (`rifttools/secondcheck.py`, counts only, sounding pitch with their key moved onto ours): 0 identical bar cells,
     longest shared run of intervals 1 of 5 in our figure (2 of 9 over the line), first two intervals shared 0, 1-2 notes
     on the same row with the same pitch class; a first figure whose opening two intervals matched one of theirs was
     dropped (as the lead's E D A was). melodic.py on the builds: range 8 st, steps 56 / thirds 22 / 4ths-5ths 22 % (the
     reference's 61/19/19), up 56 % (55), 16th positions and written lengths as the reference's, echo -7.2 dB at +3 rows
     and pan 32, portamento speeds 84/32 (decimal: G54/G20); the rebuilt five read the same.
     Candidates (slot 15): `second_badnews` (Surge Bluelight "Bad News": one shaped-sine oscillator, odd partials 3-9 at
     -14 to -18 dB, the evens under -50, through a 12 dB low-pass and a comb; its two sub wavetables muted, one unison
     voice, attacks at Surge's minimum), `second_blown` (our own model: a blown pipe, noise exciting a comb on A#3 at
     loop gain 0.9995, the tone the noise's resonance; its own noise floor, -30.8 dB between the partials, topped up
     like the others'), `second_organ` (our own model: the fundamental and its octave at one level, 8' and 4'),
     `second_pulse` (our own model: a 20 % pulse, every 5th partial missing, under a 2-pole low-pass from 3 x f0),
     `second_sine` (our own model: a near-sine, the 2nd partial at -12 dB and the 3rd at -20, nothing above): five of
     eighteen finalists of three parallel screens (1889 Surge patches: 55 stock and 255 edited takes in class; 2458
     Dexed/OB-Xd sources: 448 in class, 167 stock and 281 edited; 660 CC0 recordings, none in class (22 of the 23
     measured fail the onset, the sustained sets 28-706 ms to -10 dB against the reference's 0-1); 310 takes of our own
     numpy models, 215 in class), one shared class measure `samples/local/rift-cand/second/measure.py` (the take
     rendered at A#3, the stored pitch, read as stored at the reference's 9387 Hz through an FFT resample, the
     reference's loop place as the window, DC off; attack means over the 93 block phases, a hold limit, colour in
     partials; its docstring now gives our notes' reach, E-4..C-5, 6-14 semitones up). The choice
     (`second/finalists.py`, finalists.txt) reads what the generator makes: gen_second's make() run on all eighteen
     (into `second/gen/`, the final generator's output, at gain 0 and under each take's own name, which seeds the floor
     noise: blown, organ, pulse and sine differ from the slot's files in their noise, onset stages and turns; on the
     slot's five the choice is the same, 4.622, 24 tied), each file measured over its own loop, the distance in
     surge/work/kinds.py's fixed units as the brief set them (one Euclidean distance over the centroid in partials per
     0.25 octave, the flatness floored at -80 per 15 dB, odd over even clipped to +-30 per 10 dB and partials 2-8 from
     -60 per 10 dB; the flatness holds the generator's floor, which lifts a pure take's by 3-38 dB on 12 of the 18 as
     the distance reads it (floored at -80; unfloored 3-54 dB on 14, of which the int16 rounding of a -18 dBFS file
     makes 5-11 dB on the purest takes); aperiodicity and what the generator sets outright left out), at most one per
     kind (kinds by partial structure: the octave pair dxoctave with the organs, the detuned pulse pair ob70s with the
     pulses). The largest smallest pairwise distance, 4.633, is the blown-pulse distance, and 24 sets tie there: the
     distance fixes blown and pulse, and the pref sum takes the lowest-pref take of each other kind (badnews 0.05, organ
     0.20 against dxoctave 0.23, sine 3.06 against piglet 3.12); a tie-break on the distances (lexicographic, a variant)
     takes dxsine and m_hollow instead. Over 32 variants of the metric (other units, each figure dropped, the centroid's
     movement added, other tables, the odd/even clip moved, the scalar and table distances summed, the kind rule
     loosened, the lexicographic tie-break) the five hold in 10, are the most frequent set (10; the next two 3 each) and
     each the most frequent take of its kind (badnews 31, pulse 28, blown 21, organ 21, sine 19; dxoctave 10, piglet 10,
     fmpiano 5, ringemu 4, dxsine 4); the fragile pick is organ (its distance to sine, 4.693, 1.3 % over the limit;
     dxoctave replaces it in 122 of 500 draws of small noise on the figures, re-read on round 3's files). Each pick left
     out: m_hollow, fmpiano, dxoctave, obpulse, and piglet with dxoctave come in. Round 1's own metric (z-scores over
     the pool, without the constant floor and aperiodicity, with the centroid's movement) keeps its choice on the final
     files, badnews, dxsine, fmpiano, organ, pulse, in 19 of its 36 variants (checks/choose5_fixed.py, .log): the two
     differ by the centroid's movement (fmpiano moves 20-21 Hz), which the brief's units leave out; without it round 1's
     metric takes badnews, organ, pulse, sine and ringemu, four of these five. The first build's five (fmpiano, tuff,
     organ, hollow, dxglass) came from figures the generator overwrites (the floor kept constant, aperiodicity at YIN
     noise) z-scored over the pool. Only slot candidates count as Rift candidates; unpromoted family finalists do not
     (Polysynths/Analyse, round 4's call_analyse, was missing from the exclusion lists and was screened, out of class;
     it is on both lists now, `second/surge/work/selectlist.py` and the layer-8 EXCL2; the slot-candidate rule is noted
     in both screen.txt, Analyse in the Surge one). Recipes, screens and every take in `second/{surge,dx_obxd,rec}/`;
     tuff's recipe and screen notes now say its "pitch LFO off" edit did nothing (no LFO routed to pitch; oscillator
     drift 0.72 left on, so re-renders differ; its saved WAV is the take of record); the screens' reference pref is 0.02
     since the lo term went live. By partial tables (read on the final files, information): sine is the nearest of the
     five to both the lead (lead_rhodes: sine 13.0, organ 15.6, badnews 20.8, pulse 22.8, blown 27.5 dB) and the
     sequence (seq_calliope: 19.1, 25.3, 21.3, 33.8, 37.7; lead to sequence 19.2).
     `gen_second.py` (its docstring has every step) makes each like Nether's sample, read with melodic.character at its
     9387 Hz storage rate through an FFT resample with the sample's DC offset off (-0.087 of full scale, 13 % of the
     loop's power: with it melodic reads the centroid 171 Hz, the level movement 2.82 dB and the slope -1.45 dB/s;
     without it 227, 3.61 and -1.78; `gen_second.py ref` prints both and every target below): the take tuned to A#3 over
     the loop, its own slow pitch before the loop levelled to the loop's median (its pitch track's running median over
     0.5 s; at most 0.0-0.6 c on the five, the first build's tuff sat +4.5 c over its loop); nothing over the
     reference's storage Nyquist (4693.5 Hz) and a roll-off toward its bandwidths moving the centroid at most 5 % (blown
     only: 0.5 dB per octave from 588 Hz); every movement where the take's own reads less, solved on the reading of the
     file without its floor noise (below), with the loop at its nominal place: over the loop the vibrato (7.67 c) and
     the tremolo (3.61 dB) on the loop's 12th mirror line (2.252 Hz; the loop starts 2.886 s in, 73 ms after the
     reference's, the file 5.55 s), the drift (-3.06 c/s) and the slope (-1.78 dB/s); before the loop the reference's
     shallower movements, which is what most of our notes play (a 2-row note plays the first 0.31-0.41 s of the sample,
     a 4-row note 0.51-0.77 s), each depth the least that brings its reading to the reference's. The levels before the
     loop are read on a mean square under a Hann window three periods long (level_track; its nulls fall on every
     multiple of f0): melodic's 10 ms block holds 1.155 periods of our A#3 and its level beats with the waveform,
     1.0-1.4 dB on a steady tone (at the reference's pitch 0.2 dB on a sine, 1.2-2.5 dB with neighbouring partials),
     which round 1's build matched in place of a movement, and round 2's 20 ms Hann still beat 0.1-0.3 dB at ours; on
     three of its periods the reference reads the same to 0.01 dB. The tremolo: held over the first 0.26 s for the
     level's range there (the reference's 1.07 dB: 0.00-0.08 of the loop's depth), a knot at 0.41 s for the range over
     the first 0.41 s (2.12 dB: 0.47-0.58), then a knot at the centre of each of the tremolo cycles 2-5 for its swing
     (4.05/3.28/3.05/3.05 dB: 0.43-0.46/0.32-0.37/0.32-0.33/0.37-0.49), the last held to the end of cycle 5 (2.32 s),
     full from 2.43 s (the reference's swing steps from 3.05 dB in cycle 5 to 10.9 in cycle 6). The vibrato: a knot in
     each pitch span for its movement (1.8/3.0/6.6/5.1 c over 0-0.4/0.4-1.2/1.2-2.0/2.0-2.8 s:
     0.00-0.24/0.34-0.41/1.02-1.07/0.49-0.53 of the loop's depth), fitted once more after the onset search, since YIN's
     first frames hold the onset (sine without its noise read its first span 2.57 c with the solve's provisional onset
     and 1.42 with its final one). The level's trend before the loop to the reference's -1.78 dB/s (a line fitted from
     0.05 s to the loop start; badnews falls 1.50 dB/s of its own there and takes -0.11, the others -0.98 to -1.65). The
     floor between the partials above the third-octave band holding the fundamental to the reference's -26.84 dB (its
     -23.83 is -26.87 in its fundamental's band and -26.84 above it): noise shaped like the take, cut under 126 Hz as
     stored (what the level shaping folds back lifts that band up to 1.0 dB), 25.9-28.6 dB under the 10 ms level on all
     five. The movements are solved without that noise: shaped like the take, it sits where the partials are (7-11 dB
     more of it under 500 Hz than the reference's white floor at the same floor reading), and its random wobble reads as
     movement (0.5-3.6 c of the pitch spans and up to 0.8 dB of the ranges on sine, organ and pulse, which round 2's
     solve matched in place of a movement: sine had no vibrato before 1.2 s), where the reference's own floor reads as
     almost none (doubled, its spans move at most 0.23 c and its ranges and swings 0.06 dB over four noise draws); the
     log prints both, the file as solved and the finished file. Last the onset from silence in two stages searched
     together over a fine grid (a raised cosine to a level in 1.5 ms, then another to full; the first stage 0-20 dB
     every 0.25 dB, the second 0.5-18 ms every 0.125 ms, the whole grid: round 2's coarse-to-fine search missed organ's
     best point and its 10 ms cap stopped sine short) so the times to -10 / -3 dB of the onset's own settled level (the
     mean square over one whole period centred at 25 ms: the 10-20 ms block read before beats with our A#3, -0.5..+1.0
     dB off the period's), means over the 93 block phases, come nearest the reference's 0.32 / 4.79 ms (kept exact,
     0.3196 / 4.7939: the readings step by 1/93 of a frame); first stage -4.0 to -12.8 dB, second 5.0-13.6 ms; the turns
     on the frames where the tracker's step is smallest; a gain per candidate, the line 10.3 dB under the sub, a -1 dBFS
     guard none reaches.
     Measured (nothing heard): 10.3 dB under the sub for all five (the plan's 10.3; main and echo, active level), 13.0
     under the mix, peaks -8.1 to -10.5 dBFS. As solved (the file without its floor noise; the log's "as solved" line):
     over the loop vibrato 7.67 c and level movement 3.61 dB on all five (7.67/3.61); before the loop the level's trend
     -1.78 (-1.78), its range over the first 0.26/0.41 s 1.07/2.12 dB (blown 1.30 over 0.26 s: its own movement), over
     0.77 s 4.9-6.8 (3.52: our tremolo's trough at 0.67 s falls inside it, the reference's lower point after it;
     badnews's 6.8 holds its own early decay), its swing in cycles 2-5 4.05/3.28/3.05/3.05 on all five and in cycle 1
     2.4-2.7 (3.73), the pitch's movement over the spans 1.8/3.0/6.6/5.1 c (the same; sine's first 1.764: the knots are
     refit once, see the tool notes) but badnews's first span 17.0 (its own onset: 40 ms frames read about
     -15/+60/-35/-16 c over its first 80 ms, then its take holds within 0.2 c; melodic's as-played check reads its notes
     7 c flat on the render, the other four within 1 c). The finished files, which hold the floor noise's own wobble:
     over the loop vibrato 7.68-8.53 c at 2.25 Hz (sine 8.53, organ 8.13, the others 7.68-7.73), drift -3.03..-3.08 c/s,
     level movement 3.59-3.62 dB at 2.27 Hz, slope -1.75..-1.80 dB/s (7.67, -3.06, 3.61 at 2.17, -1.78); before the loop
     the trend -1.77..-1.80, the ranges over the first 0.26/0.41/0.77 s 1.3-1.7/2.0-2.8/5.2-7.4 dB (1.07/2.12/3.52), the
     swings in cycles 1-5 2.9-3.1/4.1-4.7/3.3-4.0/3.1-3.6/3.1-3.5, the pitch spans 1.9-3.0/3.1-4.9/6.6-7.0/5.1-5.6 c
     (badnews's first 17.1); the onset against its own settled level (one period at 25 ms) badnews, blown and sine
     0.32/4.79, organ 0.32/5.01, pulse 0.32/5.11 ms (0.32/4.79; organ's and pulse's the nearest on the grid), against
     the file's loudest block 0.7-3.7 / 8.1-17.7 ms (1.07/8.10: each file peaks at the tremolo's first crest, 0.39-0.49
     s in, 1.4-2.7 dB over its 10-20 ms level, means over the 93 phases; the reference at 0.54 s, 2.1 dB); the floor
     between the partials above the fundamental's band -26.83..-26.85 dB (-26.84), in that band -22.2..-26.5 (-26.87),
     the whole -20.9..-23.6 (-23.83); flatness badnews -45.6, blown -34.1, organ -77.1, pulse -55.8, sine -77.0 dB
     (-25.3); centroid as stored 126-207 Hz = 1.08-1.78 partials (1.53); bw40/60 organ 276/304, sine 359/421, pulse
     1054/2687, badnews 1754/4322, blown 2224/4561 Hz (2240/4694); the turns as the tracker plays them 0.00-0.54 % of
     the loop's RMS against its own 0.22-2.81 % (loopscope, source and compiled: 0.0 %); under 104 Hz as played at the
     lowest note -55 to -76 dB of the loop but blown -39.2 (its own noise; the reference's -41.1 over its loop, -40.4
     over its whole sample); as played (melodic's solo render): centroid badnews 347, blown 353, organ 336, pulse 350,
     sine 243 Hz (434), flatness 100 Hz-5 kHz -22.8/-28.4/-52.9/-39.6/-52.2 dB (-20.5), bw40 4640/3967/662/2003/797 Hz
     (8177), above 5 kHz -32.4/-38.2/-68.4/-56.1/-68.3 dB (-23.7); the soloed line's spectrum within 60 dB of its peak
     ends at 1.2-9.7 kHz (hats 11.8), above 12 kHz -71 dB on the main channel and -64 on the echo (compare.py's int16
     render: its rounding floor, the same on all five; a float render read under -82 in round 3; hats -52.1); note
     starts against each line's held full-band level at the median badnews -24.9, blown -40.5, organ -68.0, pulse -59.1,
     sine -65.6 dB (the reference's -18.4; above 7 kHz against the held top +1.2 to +20.3, the reference's +25.8:
     checks/onsets.py and ref_onsets.py print both); mix peak 0.69-0.72 (0.653); melodic.py on the builds: the notes as
     before (range 8 st, steps 56 / thirds 22 / 4ths-5ths 22 %, echo -7.2 dB at +3 rows, pan 32); clash.py 91 of 128
     (the line's 3 rows, as before); `check` OK with each candidate; every gen_*.py pattern leaves the song byte for
     byte (the sample-15 line was moved to the placeholder by checks/slot15.py, which also wrote the tryout's list).
     Kept departures (report only): the takes' own partials, noise colour and onsets (badnews's first 80 ms), and so the
     finished files' readings over the reference's by the floor noise's own wobble (the movements are solved to the
     reference's without it; the noise, shaped like the take, sits at the partials, where the reference's white floor
     gives little); the flatness under the reference's (its 8-bit noise floor is white to its Nyquist; ours follows the
     take's spectrum, so the pure takes stay far under), the whole floor reading over the reference's (the movements'
     sidebands in the fundamental's band), the narrower bands as played, our movements single sines (tremolo prominence
     76-184 against 23.6, vibrato 23-73 against 7.1) on one line with a fixed phase (so the range over the first 0.77 s
     runs over the reference's and cycle 1's swing under it, while the 0.26 and 0.41 s ranges and cycles 2-5 match; the
     cycle from 2.32 s swings 9.4-9.7 dB against the reference's 10.9, and our loop's cycles 9.2-9.6 on average against
     its 8.1), badnews's early decay, the loop start 73 ms later, the reference's DC offset (and so its note-start
     clicks) not copied, blown's energy under 104 Hz, note-start transients 7-50 dB weaker than the reference's against
     the held level, the harmony under the line read by melodic.py against the strings' F in bars 2 and 4 (our sub stays
     on A).
     Tool notes: `melodic.py` now takes a sample's default pan (Nether's samples 20, 22 and 28 have one; the pan lines
     of melodic_Nether.txt for them predate the fix and read 29 for the second line); melodic reads our sample's copy at
     its C5 speed (99 kHz), so its sample line is not comparable with the reference's 9387 Hz line (use gen_second's
     log); `loopscope.py` reads ping-pong turns; `cand_builds.py` registers the vocal pad (14); the Surge screen found
     `vulturetracker.synth._juce_base64` quadratic in the patch size (36 patches of 0.7-8.4 MB timed out at 45 s; its
     `work/fastb64.py` is linear and matches; not changed in the program). New helpers
     (samples/local/rift-cand/second/checks/): gen_into.py (make() into another folder, the slot's files untouched),
     slot15.py (the song's sample 15 and the tryout's slot-15 list from CANDS, the tryout rewritten only after a
     load/dump round trip reproduces it), table8.py (the build logs side by side; logs_build8/ holds the final build's,
     logs_build7/ round 2's for table7.py), choose5_fixed.py (.log), levels_all.py, listen.py, solo_spec.py, onsets.py /
     ref_onsets.py, onset_local.py, diag_span1.py (the first pitch span with the provisional and the final onset); the
     patches applied to gen_second.py are kept there (pending_patch_gs3.py, patch_gs4/5/8/9/10/11/16/17/18/19/24.py,
     patch_gain20.py, patch_doc6/12/21.py, patch_cands7.py; BRIEF.md's patch_brief22.py, finalists.py's and measure.py's
     patch_text15.py, this entry's patch_handoff25.py); the check rounds' reports in round1_*.txt, round2_generator/,
     round2_choice/, round3_choice/, round3_generatorb/ (round3_generator/ is the first, cut-short run); round3_fix/
     holds the choice checks rerun on round 3's files. gen_second's pitch track (melodic's YIN) folds octave readings
     back (an octave pair's frames read either) and skips a frame whose YIN frequency is not positive (one of
     latenight's uncut tail read -53.8 Hz). Pitfalls met: the -10 dB onset crossing is marginal (in some phases a block
     sits within 0.01 dB of its threshold), so any change of FFT length flips a phase or two (a 0.2 s prefix, whose
     resample differs slightly from the whole file's, moved the reading by a frame: read on the whole file, not a
     prefix; the final file, cut at its turn with its knots refit, reads the same on the five, and the whole grid
     re-read that way picks the same pair); melodic's 10 ms blocks beat with tones whose period is not a block divisor,
     and a 20 ms Hann still beat 0.1-0.3 dB at our A#3 (read slow level shapes on a Hann window three periods long, a
     settled level over one whole period); an added floor noise shaped like the take reads as movement (solve the
     movements without it); YIN's first frames hold the onset (fit the first vibrato knot with the final onset); a
     quantised reading with many ties needs the whole grid (a coarse-to-fine search missed the best point) and an exact
     target (a rounded one can prefer a neighbouring step). Left as they are (round 4's notes; each would change a file,
     not a reading): the vibrato knots are refit once after the onset search, so sine's first span as solved reads 1.764
     c against 1.77 (neighbouring knots share a span; one more pass moves its knots at most 0.0017 of the loop depth and
     reads 1.770); the onset's tie rule takes the first tied pair in grid order, which can sit next to a flip (pulse's
     least phase margin to a threshold 0.0014 dB, where pairs tied with it reach 0.060): a tie-break on the largest
     least margin would guard later rebuilds.
     Checks: a pre-build review of the code found three fixes (the drift ran from the first sample, so every short note
     played about 12 c sharp: now through the loop only, ramped in over its last 0.25 s; the pan, 29 -> 32; the glide
     speeds written as their decimal readings, G84/G32 -> G54/G20) and eleven notes; all fixed. Before round 1 the
     spectrograms showed a step at every note start (the filters' ringing before a take's onset started each file mid
     wave): the onset from silence since. Round 1 (two lenses; checks/round1_generator.txt, round1_screens.txt) found
     the tremolo and vibrato at full depth from the onset, the floor matched mostly in the fundamental's band, tuff's
     own pre-loop pitch, the onset faster than the reference's, the turns moving between readings, the choice not robust
     and reading figures the generator overwrites, Analyse missing from the exclusion lists, tuff's recipe text, the
     log's wording, the onset comparison's normalisation (now against the held full-band level) and docstrings; all
     applied (the depths before the loop solved per candidate, not fixed ratios; the pitch levelling by a running
     median; the choice on the generator's output in the brief's fixed units, with the variants). Found while applying
     them: the slope added from the onset doubled a take's own early decay (now solved before the loop to the
     reference's trend). Round 2 (two lenses; checks/round2_generator/report.txt, round2_choice/report.txt) reproduced
     all five files and logs byte for byte and found: the pre-loop level readings on melodic's 10 ms blocks, whose beat
     with our A#3 the solve had matched, so organ and pulse came out shallower than the reference before the loop (now
     on a Hann-weighted level, the targets re-read); the vibrato's pre-loop ratios not holding over the spans (now four
     knots solved); full tremolo depth later than the reference's (now full from 2.43 s); the onset's first stage copied
     from a phase-dependent 2 ms block and the attack read against a loudest block that is a later tremolo crest (now
     both stages searched against the onset's own 10-20 ms level); the robustness count inflated by pool variants that
     cannot change a fixed-unit choice, "the five farthest apart" overstating what the distance decides, the flatness
     called untouched by the generator, the CANDS header's counts, blown's floor, badnews's partials, the reason round
     1's metric differs, the aperiodicity figure, wording; all fixed (the choice unchanged: the same five on the final
     files, 10 of 32 metric variants). Round 3 (two lenses; checks/round3_choice/report.txt and
     round3_generatorb/report.txt, the generator lens run again after its first run, round3_generator/, stopped before
     its report) found 19 items. Reaching the audio: the movements were solved with the floor noise in place, whose own
     wobble (shaped like the take, it sits at the partials) made 0.5-3.6 c of the pitch spans and up to 0.8 dB of the
     ranges on sine, organ and pulse, so the solve matched it in place of a movement (sine had no vibrato before 1.2 s):
     now solved without the noise; the onset's settled level was read on a 10 ms block that beats with our A#3
     (-0.5..+1.0 dB): now one whole period at 25 ms, the target re-read (0.32/4.79 ms, kept exact); the onset search
     missed organ's best point on its own grid and its 10 ms cap stopped sine short: now the whole fine grid to 18 ms;
     level_track's 20 ms Hann still beat 0.1-0.3 dB at our A#3 with neighbouring partials: now three periods, the
     targets re-read (early2 2.12, am2 3.28, am4 3.05). Text and printout: `ref` did not print the onset target; the
     flatness lift mixed two conventions (3-38 dB on 12 as the distance reads it, 3-54 on 14 unfloored); the generated
     aperiodicity count (12, not 13); measure.py's full-level onset reading (-3 to -4 ms, not -2.6); the floor noise's
     readings credited to the take or to the reading's floor; the loudest-block sentence (every file now peaks at the
     tremolo's first crest); the blocks' beat at the reference's pitch (0.2 dB only on a sine); the prefix pitfall's
     cause (a marginal crossing, not the resample ratio). Notes: above 12 kHz the int16 render's floor; badnews's onset
     pitch on the file; the reference's -41.1 dB under 104 Hz is its loop's; the cycle from 2.32 s; pref read on round
     2's generated files took dxorgan (on round 3's it keeps the five; pref is defined on the raw takes); the 500-draw
     and bar-1 figures re-read; a screen.txt wording; an unused argument in finalists.py. All fixed. Found while
     applying them: the first pitch span's reading holds the onset (YIN's first frames), which the solve read with its
     provisional onset (sine without its noise read 2.57 c there, 1.42 with its final onset): the vibrato's knots are
     fitted once more after the onset search; and YIN returned a negative frequency on latenight's uncut tail, which the
     new "as solved" log line reads (pitch_track skips such a frame). Rebuilt: the five (files 04:19-04:27; GAIN -5.3
     for badnews, organ and sine, 0.1 dB less; all five 10.3 dB under the sub), the song (04:30; rift.it the badnews
     build byte for byte), the x4 renders; the eighteen regenerated into `second/gen/` (round 2's kept in
     checks/gen_r3pre/) and the choice rerun: the same five, 24 sets tied at 4.633, 10 of 32 variants, organ-sine 4.693
     (1.3 % over the limit), dxoctave replacing organ in 122 of 500 noise draws, round 1's metric keeping its own choice
     in 19 of 36 (checks/round3_fix/ holds the choice checks rerun on these files). Round 4 (two lenses;
     checks/round4_generator/report.txt, round4_choice/report.txt) reproduced the five files and their logs, the builds,
     the song, the eighteen (four spot-checked), finalists.txt, choose5_fixed.log and round 3's choice checks byte for
     byte, and found 13 items, none reaching the audio. Text, fixed: the onset search's "as the final reading is" (the
     final file is cut at its turn and its knots refit after the search; it reads the same on the five, and the whole
     grid re-read that way picks the same pair); the floor noise's share on the final files (0.6-3.8 c of the pitch
     spans, up to 0.6 dB of the ranges); the loudest block 1.4-2.7 dB over the 10-20 ms level (pulse 1.43); the
     reference's doubled floor over four noise draws (0.23 c, 0.06 dB; one draw had read 0.08 and 0.03); what `ref`
     prints (BRIEF); the choice reads the generator's files, not exactly the song's (gen/ is made at gain 0 under each
     take's own name, which seeds the floor noise; on the slot's five the choice is the same, 4.622, 24 tied); pref on
     round 3's generated files keeps the five (round 2's took dxorgan); measure.py's hold_db sentence, stale since round
     1 (a flat take now reads about -9 against the reference's -12.0: its level shape before and in its loop); the int16
     rounding's share of the unfloored lift; the odd/even clip among the variants, ringemu's 4, fmpiano's 20-21 Hz;
     patch_next26.py's line lengths and its lesson's wording. Notes, left as they are: the knots refit once and the
     onset's tie rule (tool notes).
   - Step 3, the form (2026-09-24; NEXT-PROMPT.md Step 3, every sound approved). **The plan**, written before the script
     (`suite/rift/gen_form.py` writes exactly this). Nether's form map in its own lengths, one order of ours for each of
     its 55 (5:20 at 165 BPM; Nether 5:01): intro 0-3, build 4-9, A 10-17, break 18-19, B 20-23, peak 24-29, break
     30-31, C 32-48, outro 49-54. The reference's layers per order are counted from its cells, no pitch read
     (`scratch/ut99-clean/rifttools/formmap.py`: per order and sample the notes struck, held or restated;
     `cellorder.py SAMPLE bar|call`: which of its own cells a line plays per order, as indices), and each of our layers
     plays where its counterpart plays, with its own form work:
     - noise (13): row 0 of orders 0-6, then every second, 8-18 and 24-30, then 33 and 37 (the connective tissue; the
       reference's lone S89 rows in 7, 9, 34 and 38 re-set the pan the note already set, so they are left out);
     - tonal hit (10): the loop's four a pattern with O0F in 0-9 and 18-23; two a pattern (rows 0 and 16) without the
       offset in A (10-17) and the peak's first two (24-25), as the reference thins it (`gen_hit.thin`); it ends at 25
       and the sequence starts at 31, so the two never sound together;
     - bed (6, approved as it is): its loop cell (struck on row 0) in 6-8 and 18-23; in 9 struck and released by a
       note-off on row 32 (its own fadeout, about 3 s: the reference's bed fades out inside its order 9); ended on the
       first rows of 24, where the reference cuts its bed (^^^; ours faded by D0F on rows 0-1, silent early in row 1,
       and cut on row 2, a hard cut having read 16.8 dB over the bed's steady 12-20 kHz energy: amended after check
       round 1);
     - lead (9): 20-23 and 26-52; the reference plays its main call everywhere but 34, 38 and 41-48, its second call in
       34, 38 and the even orders 42-48 and two more in 41/45 and 43/47 (`cellorder.py 20 call`): ours plays the loop's
       variant (`loop_b`) where the reference plays its second call and the loop's call (`loop`) everywhere else;
     - strings (11): the loop's two groups a pattern in 26-29 (the peak's last four); in 30 the row-32 group's fade from
       row 0 and nothing struck, the reference's order 30 (`gen_strings.closing`);
     - sequence (8): 31-52, bar 4 alternating by order (A B C D in the odd orders, A B C E in the even: the reference
       changes its fourth bar from pattern to pattern but once (its 40 and 41 end alike), with three fourth bars to our
       two), the copies spilling into the next order as the writer does (`gen_seq.columns` over the orders: nothing
       spills into 31), the three voices cut on row 0 of 53 as the reference cuts its sequence (amended after the first
       render, see Built);
     - drone (12): struck in 31 at v7 without G and swelled one step a row to v30 over 24 rows, restated by GFF at a flat
       v30 in 32-40, the loop's alternation in 41-48 (swell v30 to v40 in the odd orders, hold v40 in the even), D02 then
       D00 to silence in 49 (`gen_drone.form_column`);
     - vocal pad (14): struck (v5 swelled to v23) in 41 and 45, restated by GFF at v23 in 42-44 and 46-48, D01 then D00
       to silence in 49 (`gen_vocal.fade`);
     - second line (15): the reference's other pattern in 41 and 45 (the six notes, the sixth held and faded; no glide,
       no pickup: `gen_second.figure(fuller=False)`), the loop's fuller pattern in 43 and 47, the pickup's fade in 44 and
       48 (`gen_second.close`);
     - drone, bed and strings kept apart as the reference keeps them: bed 6-9 and 18-24, strings 26-30, drone 31-49;
     - figures at once as the reference's: the lead alone in 20-23 and 26-30, lead and sequence in 31-40 and 49-52, three
       with the second line in bar 1 of 41, 43, 45 and 47;
     - roots and colours: one root, A, everywhere (the sub on A with its approved passing E); the colours where the
       reference puts them: the bed's minor triad in the build, the break and B, the strings' major seventh on the minor
       sixth in the peak, the hit's A +60 c from the intro to the peak, the drone's and the vocal pad's minor triads in
       C.
     The approved break, hats, crash, sub and stab play their loop cells row for row (read from
     `suite/rift/rift_loop.yaml`, the 8-bar loop as picked, kept beside the song), each inside a window of rows per
     order where the reference's layer plays only part of a pattern: hats in 2-17, 20-22 and 24-53, to row 32 in 23 and
     to row 54 in 54 (out in the break, as the reference's; the last bar stepped down as the reference's, see Built:
     amended after check round 1); the crash on row 0 of the reference's row-0 crashes (4, 6, 8, 10, 12, 14, 16, 18,
     24-30, 33, 35-37, 39-41, 43, 45, 47, 49, 51, 53); the break in A (10-17), the peak (24-29) and 33-54 (in 54 its
     last bar slid down by its volume column and cut on row 58, where the reference cuts its drum riff and second break:
     amended after check rounds 1-2): our one break stands for the reference's chopped break (A, peak) and for its drum
     riff and second break (C, outro), and is out where the reference has no break loop (intro, build, the breaks, B,
     32; cut on row 0 of 18 and 30, since its sample loops: amended after the first render); the stab in bar 1 (row 10)
     in 4, 6-14, 16, 18 and 30 and every bar in the peak, as the reference's stab; the sub as in departure 1 (where it
     leaves, 18, 19, 30 and 53, faded by D0F on rows 0-1 (silent early in row 1) and cut on row 2: amended after check
     rounds 1-2). Channels 7-8 (the muted round-4 call) keep their lines, sample 7 and instrument 7; the form places no
     cells there (they stay in rift_loop.yaml).
     Departures from the reference's map, and why:
     1. The sub (4) plays its full rows in the build (4-9), all of A (10-17) and the peak (24-29), where the reference's
        sub is out (build, A's first four, peak) or plays fills (A's last four); elsewhere it follows the reference's
        sub: rows 26-32 in 18 (its fill), the first two bars (rows 0-32) in B and in 50 and 52, row 0 alone in 49 and
        51, full in C (32-48), out in 19, 30-31 and 53-54. Why: the level arc. The reference's low end in the build is
        its kick, in A its chopped break (0.7 dB under its sub) and in the peak its stab (1.5 dB over its sub, its
        loudest layer); our approved balance holds the break 10.6 and the stab 11.4 dB under our sub, so without the sub
        those sections fall far under the reference's arc. Measured (`rifttools/arc.py`: one pass rendered as compare.py
        renders, each section's mean power against the song's loudest order; `logs5/arc_strict.txt`), intro, build, A,
        break, B, peak, break, C, outro: the reference -12.2, -5.1, -2.9, -7.9, -5.0, -0.8, -9.2, -2.9, -6.5 dB; the
        built song (14:12) -11.6, -1.3, -1.4, -5.8, -2.1, -1.2, -9.1, -0.5, -4.7; the same song with the sub only where
        the reference's plays (`logs5/strict_trial.yaml`) -11.6, -8.7, -6.7, -5.8, -2.1, -8.4, -9.4, -0.5, -4.7 (the
        build and the peak become troughs; the plan's first trials, before the exits were cut, read the same there).
        What stays off: our peak does not rise over C (C is 0.7 dB louder: the reference's peak gets its height from its
        stab, a second break and FX hits we don't have), and the build and B sit nearer the top than the reference's
        (the faders are the owner's).
     2. No kick, noise snare, second break, drum riff or FX hits of our own (none of the approved sounds is one): the
        intro has the hit, the noise and the hats (the reference's noise snare from order 1 is not followed); the build's
        groove is our sub standing for the reference's kick, with the stab, hats and crash; our break enters at A, as the
        reference's chopped break does.
     3. The approved rows stay: the crash only on row 0 (two of the reference's three crashes in 18, on rows 8 and 16,
        its crash on row 32 of 23 and its closing two on rows 48 and 56 of 54 are not copied, so the song ends on the
        break's and the hats' stepped-down last bar without a crash; and there our break, struck once on row 48, slides
        down by its volume column where the reference re-strikes its drum riff and second break at each step); the stab
        stays on A (the reference's dip to its minor sixth in two A patterns and its walking fill in 29 not followed);
        the sub stays on A (the owner's word; the reference's bass moves to its minor seventh under C's lead and
        sequence).
     4. Two sequence fourth bars and two lead calls against the reference's three and four: the loop's own, no new cells
        (so no new copyright guard).
     5. The sequence's entry: the reference's entry pattern (its order 31) also has copy notes on rows 0-1, which its
        song never played before; ours has none there.
     The patterns: 34 (the reference's 37), named by section (intro_1 ... outro_5), shared where orders agree. Tools:
     `gen_form.py` rewrites rift.yaml's patterns, its order list and the header's "Step 3" paragraph, and leaves the
     rest of the header, the channel lines (the owner's mix), samples and instruments as the song has them; the writers
     gained the form's variants (`gen_seq.columns`, `gen_hit.thin`, `gen_strings.closing`,
     `gen_drone.form_column`/`FORM`/`FADE`, `gen_vocal.fade`, `gen_second.figure(fuller=False)`, `gen_second.close`) and
     still leave the loop byte for byte (all eight checked on a copy of rift_loop.yaml); on the form song each `gen_*.py
     pattern` stops with a message and writes nothing (no `loop`/`loop_b` there; pattern(path) still writes the loop),
     so after changing a writer, run gen_form.py. The writers as they were before this step, and the loop song (as it
     was before the "# Picked ... second_sine." header line rift_loop.yaml has), are in
     `samples/local/rift-cand/form/pre/`; the patches (`patch_writers1.py`, `patch_writers2.py`, `patch_form3.py`,
     `patch_form4.py`, `patch_form5.py`, this entry's `patch_handoff_*.py`) beside them.
     **Built** 2026-09-24 12:37; rebuilt 13:20 after check round 1 and 14:12 after check round 2 (rift.it 4,211,470
     bytes; the render 320.0 s, the rows' 319.9 s and libopenmpt's 0.1 s tail, its duration estimate 5:19.7; WAV and MP3
     14:12; `check` OK, no warnings). The first build (12:33) showed in clash.py's table and compare.py's soloed break
     (active 262 s against the plan's 210) that looped samples keep sounding past a layer's last note: the break (its
     sample loops over its whole bar) through the break section and B and through 30-32, the sequence's last notes
     through 53-54. Fixed before round 1: the break cut (^^^) on row 0 of 18 and 30 (the reference, whose breaks are
     one-shots, cuts the channels they played on in its order 30), the sequence's three voices on row 0 of 53 with
     nothing spilling there (the reference's order 53 does exactly that), and each closing fade ending in a cut on the
     row after (strings row 19 of 30, drone and vocal pad row 16 of 49, the second line row 0 of 42 and 46 and row 8 of
     44 and 48): digitally silent before each (check round 1), but the app's SOUNDING table follows cuts, not D fades,
     so the listening notes' sounding lists drop those layers. Check round 1's fixes (13:20): the sub leaving on row 0
     of 18, 19, 30 and 53 (the loop's passing E-2 on row 60 of 17 and 29 rang on for 26-32 rows from -23 dBFS, as the
     bass, where the plan has the sub out or on its fill; in 19 and 53 the row-32 A's short tail); the bed's exit at 24
     faded (a hard cut there read 16.8 dB over the bed's steady 12-20 kHz energy, level with the rest of the mix); the
     last bar stepped down as the reference's is (the hats' last three at v05/v04/v01 against the reference's v12 to
     6/3/1) and the break cut before the song ends (its loop had wrapped in the render's 0.1 s tail to the next bar's
     kick, peak -14.3 dBFS). Check round 2's fixes (14:12): the sub's hard cuts at 18 and 30 read by the same measure
     17.4 dB over its steady level, 1.2 and 6.3 dB over the rest of the mix, so the sub now leaves by D0F on rows 0-1
     and a cut on row 2 wherever it leaves; the break's last cut on row 58, where the reference cuts its drum riff and
     second break (at v05 ours had played on through row 62, a kick and a snare); and, found by this build's own exit
     measure, the last bar's set volumes on the break stepped, and the v20 step on row 52, on the break's snare, made a
     burst above 12 kHz (11.6 dB over its steady level, 7.4 over the rest of the mix; round 2's audio lens had noted the
     steps' bumps), so the break now slides down by its volume column (d04, d03, d02, d01 on ticks 1-3, two rows each,
     d01 to row 57: 64, 40, 22, 10 and 4 at rows 48, 50, 52, 54 and 56 against the reference's 64/40/20/10/5, silent
     early in row 57) to the cut. The writers still leave rift_loop.yaml byte for byte; on the form every `gen_*.py
     pattern` stops with a message and writes nothing; gen_form.py reruns byte for byte (patch_writers2.py,
     patch_form3.py, patch_form4.py, patch_form5.py).
     Measured on the 14:12 build (nothing heard; `samples/local/rift-cand/form/logs5/`):
     - the exits (`form_checks.txt`: each exit's 12-20 kHz peak in 256-frame windows against its soloed channel's steady
       level over the 16 rows before, and against the rest of the mix at the same instant, dB): the sub's fades
       +8.5/-4.2 (18), +3.3/+2.9 (19), +8.5/+0.6 (30), +3.3/+1.2 (53), against its ordinary note start's +38.4/+37.3
       (the second figures read at the fades' first tick, where the crash and the noise strike: in ticks 1-3 the fades
       at 18 and 30 sit 4-6 dB over the rest of the mix above 12 kHz, at about -93 dB re full scale, 10 dB under the
       hard cuts' and 14-30 dB under the sub's own note starts; at 19 and 53 within 4 dB of the render's rounding floor:
       check round 3); the bed's fade at 24 +6.3/-11.3 (4/64 at the end of row 0, silent early in row 1: libopenmpt
       slides D0F from the first tick), its note-off in 9 +3.0/+0.3 (an ordinary strike +2.7/+0.9); the break's cuts at
       18 and 30 +2.5/-14.1 and +2.5/-10.0, its last-bar slide +1.2 to +3.2 / +1.3 to +3.2 (at the render's rounding
       floor, as is the rest of the mix there: check round 3; an ordinary strike +15.5/-6.7), its row-58 cut on silence;
       the sequence's cut at 53 +7.9/-4.3 (an ordinary restart +12.1/-6.9); digital silence after every cut, in the
       song's rows 58-63 and in libopenmpt's tail;
     - where each line sounds (melodic.py on `lines.json` rift_form, registered by `rifttools/form_build.py`): every
       layer in the reference's orders (sequence 31-52, lead 20-23 and 26-52, hit 0-25, strings 26-30, bed 6-9 and 18-24
       (its fade in 24's first row), stab 4, 6-14, 16, 18 and 24-30, drone 31-49, noise its 13 strike groups, vocal pad
       41-49, second line 41, 43-45 and 47-48); the sub 4-18, 20-30, 32-52 (its fade in 30's first row; the reference's
       14-18, 20-23, 32-52: departure 1); line levels, the median per order where each plays, against the reference's:
       sequence -30.7 (-31.0), lead -35.5 (-36.3), hit -34.8 (-34.6), drone -34.1 (-33.7), noise -35.1 (-34.7), vocal
       pad -34.8 (-34.6), second line -33.3 (-34.5), sub -22.4 (-23.3); the owner's levels: strings -38.8 (-31.7), bed
       -30.0 (-35.1), stab -42.3 (-28.3) dB;
     - the level arc (`rifttools/arc.py`, RMS per order, ours and the reference's): intro -31.8..-31.9 (-31.7..-29.1),
       build -21.2..-21.9 (-22.5..-24.8), A -21.5/-21.8 (-20.1..-21.8), 18 -24.4 (-23.5), 19 -28.8 (-31.7), B -22.4
       (-23.0), peak -21.3..-21.6 (-18.0..-19.2), 30-31 -30.4/-28.7 (-26.2/-28.5), C -20.3..-21.4 (-20.7..-21.7), outro
       49-52 -25.0/-22.3/-25.2/-22.3 (-25.1/-22.0/-25.3/-22.0), 53-54 -31.7/-33.8 (-28.6/-29.2: our break, hats and
       crash in 53 and the stepped-down last bar in 54, against the reference's drum riff, second break, hats and
       crash); the section means in departure 1 (arc.py credits each 4096-frame chunk to the order playing at its end,
       so its orders start up to 0.9 rows early: within 0.3 dB of exact rows, check round 2); per bar (dBFS), 18 opens
       at -26.8 (17's bars -21.6 to -22.0: the break section begins with the sub out until its fill on row 26), 30 reads
       -25.7, -32.0, -39.1, -50.4 (in its bars 3-4 only the hats and the noise's tail sound; check round 1 read the
       reference's same bars at -36.5 and -38.8 with the same layers, its hats 10 dB higher against its sub than ours),
       then +22.9 dB into 31's first bar (the reference's +11.5), the song's largest bar-to-bar rise (next +13.4 into
       the build, +8.0 at 32); the last bar -37.9 (the three before -32.5 to -33.3);
     - compare.py against Nether alone: 320 s (301), RMS -22.2 dB (-21.8), peak 0.681 (0.653; the oversampled WAV's own
       0.682), L/R correlation 0.921 (0.962), centroid 213 Hz (591), flatness -17 dB (-7), sub band 72.1 % (50.2),
       onsets 5.0 (4.3) a second; soloed active levels sub -22.7, sequence -31.5, break -33.1, drone -33.2 dB;
       analyze.py reads 13.2 root changes a minute (Nether 1, our loop 0) and the bass root E (0.44; the loop 0.41). Its
       root is the strongest chroma class of each 1.95 s window; check round 1 traced the changes on the 12:37 build and
       round 2 found every window's root the same on the 13:20 build: 72 changes over 164 windows, roots D 81, A 58, C
       25; the break's chroma and the hats' both read D-strongest, and D wins 18 of 24 windows in A, 13 of 17 in the
       peak, 18 of 18 in the outro, all three of 30 and one of the three of 31 (the hats, the crash and the noise
       there); the bed carries the C windows of the build, the break and B, the vocal pad five of the eight in C (the
       drone's chord reads A over E over C); in 33-48 A still wins 13 of 48;
     - clash.py: 263 of 3520 rows (7.5 %; the loop 91 of 128): the peak's last four 16-22 a pattern (the strings' own
       colour where the groups overlap, and our sub's passing E under Str 1's F, 4 a pattern; 24-25 none), C 3-6 a
       pattern (the sequence's B against the drone's C), 41-48 6-38 a pattern (the second line's held B-4 and the
       sequence's B against the drone's and the vocal pad's C-5; 38 in 43 and 47, where the glided B-4 holds from row 18
       to 43), 3 in 49, none elsewhere (the bed and the strings, which made most of the loop's clash rows, never meet in
       the form);
     - the spectrum (`form_checks.txt`, `spectrogram.png`): the long-term spectrum (Hann, L and R power) ends 60 dB
       under its peak at 9.93 kHz and 80 dB under at 11.50 kHz at 8192 points (9.97 and 13.37 kHz at the PNG's 2048);
       above 12 kHz -66.2 dB of the whole; by each soloed channel's loudest 1024-frame frame above 12 kHz the stab's and
       the sub's note starts lead (-67.3 and -70.6 dB against a full-scale sine's frame: their samples' own attacks, as
       in the loop), then the break and the hits (-91.6 to -93.0), then the sequence, the hats and the rest within 8 dB
       of the int16 render's rounding floor (at most -103.5, read on the strings' near-silent solos; the sequence and
       the hats 0.2 dB apart); the exits add nothing above that floor but the bed's fade at 24 (its loudest frame there,
       3 dB over it); the PNG is a mono sum, in which the surround bed cancels (check round 1: -63 dB), so the bed is
       read by compare.py's per-channel power;
     - the copyright guards (cellcheck, leadcheck, chordcheck, dronecheck, noisecheck, vocalcheck, secondcheck;
       `logs3/guards.txt`, the cells unchanged since) print the counts each layer's entry gives: no new cells (the
       second line's other pattern is the figure's first six notes);
     - the noise, for the owner's repetition caveat: 19 strikes of its one sample (the reference's 19), seven in a row
       in orders 0-6, one every 5.8 s; soloed against the mix it reads -3.2 dB in the intro (only the hit and, from
       order 2, the hats play with it), -10.7 dB in 18, -13.2 to -14.3 elsewhere and -4.5 dB in 30 (the second break's
       first order);
     - left as they are: the hit sample's decaying DC offset (-54 dBFS over its active frames, the mix's -57; it ends at
       0, so no step), older than the form; the MP3 plays 0.26 dB under the WAV (the encoder's own: a test sine loses
       0.27 dB, check round 2).
     Logs in `samples/local/rift-cand/form/`: `logs1/` (the 12:33 build), `logs2/` (12:37, with the loop's own module
     for comparison), `logs3/` (13:20, the guards), `logs4/` (14:07: round 2's fixes before the slide), `logs5/` (14:12:
     compare, melodic, the arc and the strict trial, clash, the spectrogram, form_checks).
     Checks: round 1 (two independent read-only lenses on the 12:37 build: `checks/round1_layout/report.txt`,
     `checks/round1_audio/report.txt`) found 26 items (17 + 9), two of them by both lenses: 24 distinct, by the reports'
     own labels 3 audio/layout (the break's loop in the render's tail at the song's end; the reference's stepped last
     bar not followed; the sub's E ringing into 18 and 30), 9 text errors (the reference's fourth bar kept once, in
     40-41; what it cuts in its order 30; "no groove" for sections with the reference's kick and snare, and the bed's
     colour also in the break; our crash in 53; BRIEF's crash count; the spectrogram bullet's ranking and "nothing else
     above the hats' band"; the root-change account; the peak's clash rows only in 26-29; departure 1's pre-fix figures)
     and 12 notes (among them the bed's hard cut at 24, fixed as an audio item; the level hole at the end of 30,
     reported above; libopenmpt's duration estimate; the header replacement running to `module:`; the writers' `pattern`
     on the form; gen_second.close missing from the lists; the stop rule at a cycle's entry 0; one dict for six strings
     columns and no 26-column check; the pre/ song lacking this step's "# Picked" header line; the CHECKS placeholder;
     the hit's DC offset; gen_form needing scratch/ and samples/local/ files through the writers' module-level imports,
     so a clone cannot regenerate the form: to be made lazy before any Rift commit); all fixed and rebuilt 13:20, or
     noted as said. Round 2 (the same two lenses on the 13:20 build: `checks/round2_layout/report.txt`,
     `checks/round2_audio/report.txt`) found 26 items (15 + 11), five of them by both lenses: 21 distinct, 1 reaching
     the audio (the sub's new hard cuts at 18 and 30), 9 text and measurement errors (logs3's missing spectrogram and
     loop module; BRIEF's outro range, -22 to -29; two of the reference's three crashes in 18 left out, not three; D
     winning four of the six windows of 30-31; order 30 is the second break, not the peak, and the sequence's and the
     hats' order above 12 kHz, 0.2 dB apart near the floor; "noted below"; the plan's break clause, and the break
     playing past row 56 at v05 where the reference cuts on row 58; "-58 dBFS" for digital silence after a cut's ramp;
     the bed's fade measured only at row starts, and over within one row) and 11 notes (the writers' "wrote" line after
     the note, now a stop with a message and a docstring line; the last-bar rule dropping a note from a cell without a
     volume, now a volume-field rule; the sub-exit test keyed on the window's first row, now on whether it strikes row
     0, and its comment; a bare ValueError if the paragraph's last line changes, now a message; the round-1 tally; a
     cause given for the loop's 0 root changes, dropped; BRIEF's "patterns" for orders; the bars the fixes lowered, now
     above; the break's set volumes leaving 12-20 kHz bumps, now a slide; arc.py's early order starts; the MP3's 0.26
     dB); all fixed and rebuilt 14:12, or noted as said. Round 3 (the same two lenses on the 14:12 build:
     `checks/round3_layout/report.txt`, `checks/round3_audio/report.txt`) found 17 items (10 + 7), two of the audio
     lens's also the layout lens's (one covering two of its items): 15 distinct, none reaching the audio: 6 text and
     measurement errors (the plan's "D0F on row 0" for the sub, which fades on rows 0-1; "silent within the first row"
     for the bed and the sub, silent early in row 1; "each jump a burst", where only the v20 step on the break's snare
     made one; the round-2 tally, with five shared items, not four, and a note missing from its list; the sub's fades
     against the rest of the mix read only at their first tick; the rounding floor's reading and "the exits add nothing
     there") and 9 notes (the sub's fades at 19 and 53 read against rounding noise; with_volume reading fields by
     position, now by shape; the sub-exit rule resting on the loop's sub striking row 0, now asserted, and its comment's
     "clicked"; the writers' docstring note too generic, reworded; BRIEF's Build range, now -25 to -22.5;
     `rifttools/cand_builds.py` still building candidates from rift.yaml, now the form (see Next); form_checks skipping
     the slide's first row and comparing rounding noise there; the reference re-striking its riff at each step where
     ours slides, now in departure 3, and the song's last 0.713 s of digital silence; clash.py's D0F model, 45 a row
     against libopenmpt's 60 from the first tick, which adds a sounding row at each fade exit and no clash row); all
     fixed in the text or in the code without changing the song (rift.yaml regenerated byte for byte, so rift.it and the
     renders stand: patch_form6.py), so no rebuild and no further round.
   - Next: the owner's listening notes on the form (N in `python -m vulturetracker gui suite/rift/rift.yaml`); act on
     their words and sounding lists only. Before a new candidate screen, point
     `scratch/ut99-clean/rifttools/cand_builds.py`'s SONG at `suite/rift/rift_loop.yaml` (it builds from rift.yaml, now
     the full form). Before Rift is committed, PROVENANCE.md needs a Rift section (the measured character figures the
     generators follow; notes, cells, partials and sounds ours, the voice and tone models ours; the
     Dexed/Surge/OB-Xd/VSCO sources credited). The owner, 2026-09-24, on the form: "I like this but it feels like we are
     doing the musical equivalent of tracing for tracks like rift and vantage. Regardless of what you say about how
     different they are, to me they still sound way too similar to the original UT tracks they are inspired by." The
     method (NEXT-PROMPT.md since "Follow the references") is to be reworked in a new conversation, from a prompt given
     in chat; Rift's form stays as built meanwhile.
   - The tracing rework (2026-09-24, afternoon; the owner's prompt: diagnose, listening tests, method proposal; nothing
     committed). The owner added: the likeness is per section ("the introduction to rift is nearly identical to Nether,
     the section that starts at 2:59 sounds nearly identical"; the same holds for Vantage and Foregone).
     - `suite/TRACING-DIAGNOSIS.md` (uncommitted: it measures Epic's modules): what Rift and Vantage inherit, dimension by
       dimension (copied exactly / genre / ours), and how close each sits to its reference against how close different
       UT99 tracks get. New scratch tools: `scratch/ut99-clean/sections.py` (order-by-order likeness: each order a set of
       layers with rhythm, density, held, sound class, idioms and level; the baseline is each UT99 order's nearest order in
       another track, min 0.125, 5 % 0.164, median 0.214; Seeker/Seeker2 not a pair, firebr and Savemeg skipped),
       `globaldims.py` (whole-song dimensions as percentiles of 405 UT99 pairs), `formcurve.py`,
       `variants_likeness.py`. Findings: Rift runs 20 consecutive orders under the 5 % along Nether's orders (UT99 pairs
       at most 4), 12 orders under the corpus minimum; its intro (0.0 %) and break 2 + C (0.0 / 0.2 %) are the closest
       sections, carried by rhythm, density and idioms, not by sound class; Vantage copies the frame and the idioms
       (tempo and grid identical, drum, riff and bed rows, the colour set), which the order measure sees only weakly.
     - `suite/rift/variants/` (uncommitted): `make_variants.py` builds six songs from rift.yaml (which it never writes):
       v0 control (byte-identical .it), v1 our own form (3:24), v2 another layer set, v3 our own idioms, v4 other sound
       classes for the sequence, lead and hit (`kit.yaml` -> `samples/local/rift-variants/`), v5 147 BPM with another hat
       groove; WAV and MP3 each; `LISTENING.md` is the owner's one-page sheet. Waiting for their listening.
     - `suite/METHOD-PROPOSAL.md`: three methods (A the soundtrack's style sheet, B our own concept first with the
       references as limits, C the reference as a lens), a shared "not a trace" check (no order under 0.125, at most
       5 % under 0.164, no run over 3, at most 2 whole-song dimensions under their 5 % against one track, an inheritance
       audit with at most two dimensions copied exactly from any one track) and a "sits in UT99" check; B recommended by
       default, the choice to follow the listening. `suite/NEXT-PROMPT-DRAFT.md` drafts B's prompt; `suite/NEXT-PROMPT.md`
       is unchanged until the owner agrees.
     - Checks (three independent read-only agents, 2026-09-24): the diagnosis (8 errors, 2 missing, 5 notes: C's and the
       intro's wording against the corpus minimum, the nearest-order share, the drums' placement and the arc marks, the
       riff's first row, the run baseline counting Seeker/Seeker2; all fixed, sections.py rerun), the proposal (7 errors, 5
       missing, 5 notes: floors that real UT99 tracks failed, now set so no pair of different UT99 tracks fails them; a
       fixed ten-dimension audit; the draft's rules written out; all fixed) and the variants (no audio defect; v3's echo
       is 6 rows, a dotted quarter; v4's hit had lost its attack to the O0F offset and sat 5 dB low, now played without the
       offset and matched on its played part; v5's break wrapped 0.5 ms early, now fine-tuned; the sheet's wording). Found
       on the way, flagged as a separate task, not fixed here: an explicit `c5_speed` is not rescaled when `sample_rate`
       resamples the WAV (vulturetracker/song.py ~367); v5 gives its c5_speed at the compiled rate.
     - The owner's listening (2026-09-24): v1 "just moved the traced section" to 0:23; v2 "I actually like this a lot";
       v3 liked (its beat-3 hit "a bit too repetitive"); v4 liked ("loud wind blowing or something" distracting); v5
       "hate this"; in v1-v4 the sequence from about 3:00 is "the same exact sequence" whatever plays it: "the issue is
       not with the sounds ... it is with the actual sequences of notes/melodies", "to my ears they sound like the exact
       same melody" (not a copyright question: never answer with guard counts). Round 2 built on v2
       (`make_seqlines.py`): the sequence section rewritten from scratch in three lines (lament, low riff, pulse) plus
       one without a sequence, MP3s, LISTENING.md "Round 2"; waiting for their pick. The lead call and second line were
       built the same way as the sequence (from Nether's measured shape); ask whether they read as Nether too.
     - Round 2 verdicts: lament "absolutely hate", riff "has potential ... doesn't sound wholly derivative" (the clear
       winner; its voice "a bit too different from the rest of the song"), pulse "potentially interesting", no sequence
       "kinda boring"; the intro "a bit too long" (the length matched Nether's too closely). Built: `suite/rift/rift2.yaml`
       (the working song from here; `variants/make_rift2.py`): v2 + the riff, intro 2 orders and build 4 (was 4 and 6),
       51 orders, 4:57, the riff from 2:37; `rift2.tryout.json` opens slot 8 with the calliope and five voices from
       `variants/riffkit.yaml` (Helmeto, the stab's patch; FmRhodes18, the lead's source; E-Bass; Fingered; Rubber Bass),
       rendered at A-3, band-limited to 5 kHz, floored -26 dB, tuned within 6 cents; Mellow, FM Bass 2, Piano Bass
       (interval partials or an octave low) and Smoothie (a pure sine) dropped by measurement; `check` passes with each.
     - Picked 2026-09-24 16:37: `riff_helmeto` (written with U into rift2.yaml slot 8; no ratings, no unwritten mix).
       Rift 2 waits for the owner's next listening notes. Open items from their round-1 notes: v3's beat-3 hit "too
       repetitive" and v4's "loud wind" (both variants only, not in rift2); the lead call was built from Nether's measured
       shape like the old sequence (not flagged by the owner so far). The method choice: B by default
       (METHOD-PROPOSAL.md), with "melodies are always our own" as its main lesson; NEXT-PROMPT.md and AGENTS.md's
       "Follow the reference" unchanged until the owner says. Next session (the owner's word): program features.
3. Program side: done on the user's word (2026-09-22 13:35): round 5 committed (6d7b4ca), the suite committed
   (b83b2c6, the three tryout picks copied into samples/nadir so the song builds from the repository), "Version 0.2.2"
   (80c1504), all pushed with tag v0.2.2; GitHub release 0.2.2 with the exe (SHA256 76eae8a9..., smoke-tested
   headless on demo2: the PATTERN tab and the single NOTE button are in the bundled page); the 0.2.1 release body
   repaired (plain UTF-8, the arrow back). The compiler loop-click fix, committed on the user's word 2026-09-22 late
   (ec61d33 on main, fast-forwarded from `claude/sweet-gates-0586c2`; not pushed; the image warning below is 4c66b97): with `sample_rate`, each loop is
   resampled as it plays (forward wraps, ping-pong reflects), fitted to whole frames, and every frame follows one time
   map through the loop borders (no jump into a loop, out of a released sustain loop, or in a loop inside another).
   An independent review found five defects in the first version (entry/exit jumps, overlapping sustain loops, adjacent
   loops a frame apart); all fixed and rechecked before the commit. Unlooped samples compile bit-identically; only
   Nadir's 9 and Rift's 1 looped samples change (1-3 frames longer). Rebuilt both (WAV, MP3); loopscope, compiled
   wrap in % of the loop RMS, before -> after: Nadir drone 15.2 -> 0.3, riff 19.9 -> 0.3, wind 62.6 -> 8.3 (its source
   66.9), strings 68.0 -> 10.3, strbed_g/bb/c 26.4/14.6/53.4 -> 4.5/6.9/4.4, loop 6.2 -> 1.1; Rift break_room 16.0 ->
   26.7 (a noise-like break: the metric scatters, its own steps reach 143 %). Known and unchanged: a very short loop
   rounded to whole frames can be detuned (10 frames: up to 36 cents), as before the fix. The pitch-down image warning
   from another session, committed on the owner's word 2026-09-23 (4c66b97, not pushed): `check` warns when a sample's
   lowest note leaves interpolation images within 60 dB of it under 20 kHz (libopenmpt's 8-tap interpolator measured);
   no song in the repository warns. Its one sentence in AGENTS.md's anti-aliasing bullet stays uncommitted inside the
   owner's uncommitted rule rewrite there (one diff hunk; commit the two together when the owner says).
