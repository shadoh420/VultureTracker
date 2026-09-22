# Suite handoff (2026-09-22, Nadir v6 = the last pass, app 0.2.1 + round 5)

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

## Next steps, in order

1. The user listens to v6 (`python -m vulturetracker gui suite/nadir/nadir.yaml` or `nadir.mp3`); the NOTES tab starts
   empty for v6 (the v5 notes are archived on open). It is the last pass by their word: record what they say, and change
   Nadir again only if they ask.
2. The next piece follows `suite/NEXT-PROMPT.md`: one reference track (Nether Animal or Run first), measured into a
   brief, then drums and bass as a two-bar loop with candidates the user picks in the tryout, then one layer at a time,
   and the full form only after every sound is approved. The group-per-piece plan (groups 2-5) is dropped; the group
   analysis in `scratch/ut99-clean/` stays useful as measurement tooling.
3. Program side: round 5 (PATTERN tab, one NOTE button, `U` clears the slot's list) is uncommitted; commit and release
   0.2.2 when the user says. The corrected 0.2.1 release body waits for an explicit yes (`gh release edit v0.2.1
   --notes-file`).
