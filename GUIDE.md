# VultureTracker guide

The short version is [README.md](README.md); this is the long one: the app, the demos, samples, tests and notes.

Write sample-based tracker music as a readable YAML text file and compile it to a real Impulse
Tracker module (`.it`). Every note, instrument, envelope and effect stays visible and editable, by
hand or by an AI.

```
song.yaml ──build──▶ song.it ──render──▶ song.wav
```

## Setup

```
git clone https://github.com/shadoh420/VultureTracker.git
cd VultureTracker
pip install pyyaml
```

Python 3.10+. On Windows x64, libopenmpt (used to verify and render) is included in `vendor/`.
Elsewhere, install libopenmpt (e.g. `apt install libopenmpt0`) or set `LIBOPENMPT` to its path.

## Usage

```
python -m vulturetracker check demo/arena.yaml                        # validate; errors show file:line
python -m vulturetracker build demo/arena.yaml -o demo/arena.it       # compile, then verify with libopenmpt
python -m vulturetracker build demo/arena.yaml --render demo/arena.wav # compile and render in one go
python -m vulturetracker render demo/arena.it -o demo/arena.wav --repeat 1
python -m vulturetracker info demo/arena.it                           # what libopenmpt sees
python -m vulturetracker import some.xm -o some.yaml                  # existing .it/.xm/.s3m/.mod -> song file + WAVs
```

`pip install -e .` also installs a `vulturetracker` command.

## GUI: choosing samples in context

```
python -m vulturetracker gui demo2/iron_relay.yaml
```

opens the app in its own window (`pip install pywebview`; without it, or with `--browser`, it opens in your
default browser instead; either way it is served on localhost and nothing leaves your machine). Run it with
no song to get the open-a-song screen with recent songs and the demos; its NEW SONG makes a song file at the path
given (never over an existing file) with the channels asked for, an empty 64-row pattern and one instrument playing a
one-second tone written beside the song as `<name>_tone.wav`, and opens it in the Pattern tab. Pick a sample slot and
a section of the song, add candidate WAVs by path or glob, and each candidate is rendered inside the song with
only that slot swapped. Keys `1`–`0` switch candidates without losing the playback position, `S`/`M` toggle
SAMPLE ALONE (the candidate's WAV by itself) vs. IN MIX, SOLO IN SONG mutes every channel that never plays the slot,
stars/reject/notes are kept per candidate beside the song (`<song>.tryout.json`), and `U` shows the YAML change before
writing it; once written, that slot's candidate list is cleared (the choice is made; a file's rating is remembered if it
is added again). With no candidate picked, SONG plays the song itself. Slots that have candidates are marked in the slot list
(`24 arp ▸ 5 candidates`); rejected candidates sink to the bottom of the list (their number keys stay). When a sample
recipe (SAMPLING.md) in the song's folder writes the slot's WAV, a RECIPE box under the candidate input shows that
sample's entry as YAML: edit it (a hold, a note, `params:`, an `fx:` chain) and RENDER CANDIDATE renders it into a new
WAV beside the slot's (`<name>-r1.wav`, `-r2`, …, never over the recipe's own file) and adds it to the candidates, in the
background; WRITE TO RECIPE (click twice) writes the entry as it stands into the recipe file in place (a one-line
entry stays one line with its comment). A candidate rendered this way remembers its entry, so after `U` the box shows
it. Rendering needs what `synth` needs: pedalboard (inside the exe) and the synth. When Surge XT or Dexed is
missing, the box offers GET SURGE XT (a 300 MB download) or GET DEXED (10 MB): the app unpacks it (the exe into
`%LOCALAPPDATA%/VultureTracker/tools/`, a checkout into `tools/`) and renders the entry again; OB-Xd is an installer,
linked from the message. The candidate
you are listening to renders first; after a mute or fader change the old render keeps playing until the new one lands
and the player says so. Under the progress bar (click or drag to seek) SOUNDING lists the channels sounding at the
playhead with the slot each plays (a looped tone until its note-off, a one-shot until its sample runs out); click one
to solo it (playback rewinds a second when the soloed render lands, so the moment you clicked on is heard soloed).
SPEED slows playback to 75, 50, 33, 25 or 20 % with the pitch kept (type… takes any value from 10 to 200 %). The
strip just above the progress bar is the playback loop: drag on it to loop a span of what plays (snapped to rows),
click it to clear the loop; LOOP FROM / TO under SECTION TO LOOP takes the span as order and row numbers (the orders
of the song, `to` inclusive). The loop is playback only: the render stays the section, so switching candidates or
moving a fader keeps the loop and no render waits on it; it works for the song and for every candidate whenever the
span lies inside the rendered section (otherwise it says so), jumps back within a few milliseconds of its end, is kept
in `<song>.tryout.json` and recorded with listening notes. The SPECTRUM tab is the spectrogram of the render that is
playing (the song or a candidate in it, with the mutes and the unwritten mix), computed by the app from that WAV: time
across with the order boundaries marked, aligned with the playhead (click or drag to seek), frequency up in Hz on a
LOG axis (20 Hz to 22 kHz) or a LIN one (where imaging and aliasing near the top show), colour = level in dBFS from
-100 to -10 (a full-scale sine is 0 dB); each band shows its loudest bin, so a narrow tone between bands is not lost.
The Song Overview tab has a stems rail that is also a mixer: mute or solo channels, a volume and pan fader per
channel, a MIX VOL master with the peak of what is playing, and a GAIN fader per sample slot in the slot table (click
any fader's number, or an instrument-panel value, to type it: Enter applies it the way the fader would, clamped to the
song format's range, Escape cancels; a pan takes 0–64, L50, R20, C or S for surround); every
move re-renders the tryout at once (the section is compiled once and the values are patched into the module's header),
and the meter next to each channel is that channel soloed, its RMS in dB over the active part of the section (the way
the suite's comparison script measures a module: `compare.py` in `scratch/ut99-clean/`, which is local only and not in
the repository). Nothing is written until WRITE MIX → SONG, which shows the YAML
change first (`module.channels` volume/pan, `mix_volume`, the sample's `global_volume`, edited in place). EXPORT STEMS
writes one WAV per playing channel to `<song>_stems/`; EXPORT SONG AS writes the whole song beside it as MP3 (192 kbit/s),
OGG (Vorbis quality 6, about 192 kbit/s; Ogg loops gaplessly, which is what a game engine wants) or FLAC (lossless),
with + STEMS also one file per channel in `<song>_stems/`, the song as written, encoded by ffmpeg: `ffmpeg.exe` beside
the standalone exe (the build copies it to `dist/`), else imageio-ffmpeg's, else one on PATH. The tab also has the arrangement grid and the slot table. The Pattern tab is the
pattern view and editor, the whole window wide, following the selected order and the playhead. It has a cursor (click a
cell; the arrows, Tab, Page Up/Down, Home and End move it through rows, channels and the note, instrument, volume,
effect letter and effect parameter columns) and the LIVE transport: libopenmpt compiled to WebAssembly plays, in the page's
own audio thread, the whole song as it is now with the unwritten mix. ▶ FROM CURSOR (Space, F7; Space again stops,
and the cursor stays where it stopped; a double-click on a row plays from there), ▶ SONG from the start, ↻ PATTERN
(F6) loops the pattern at the cursor, ■ (F8) stops. The view follows what plays, the channel headers show each
channel's level, SOUNDING lists what sounds, N drops a note at the live position. Mutes and solo from the stems rail,
the playback loop (LOOP FROM / TO) and SPEED act on it at once, without a render; a fader, the instrument panel or a
change to the song file recompiles the song and swaps it in where it plays. The piano keys (Z to M and Q to U, two
octaves from OCT) preview the PREVIEW instrument: on the song while it plays, alone while stopped; in the Pattern tab
they take the place of the app's letter keys (M, S, N, U, X), and the NOTE… button still drops notes.

**Editing patterns.** Esc (or ● EDIT) turns on edit mode. In the note column the piano keys enter a note with the INS
instrument (and preview it) and move the cursor down by STEP rows; 1 enters a note-off (`===`), ` a fade (`~~~`), \\ a
cut (`^^^`). Digits type the instrument (two digits), the volume column takes a command letter (v p a b c d e f g h) and
two digits, the effect columns an effect letter and two hex digits; values are clamped to their range. Delete or . clears
the column under the cursor; Insert pushes the channel down from the cursor, Backspace pulls it up. Each change shows
at once and is written into the song file in place: only that row's cell changes (the other cells, the row label, the
comments and every other line stay as they are; rows the pattern leaves implied are written out when a later row is
edited). Before anything is written the whole song is compiled: a change the song format refuses (an instrument that
does not exist, say) is not written and the bar says why. Ctrl+Z / Ctrl+Y (↶ ↷) undo and redo the edits of this
session. An undo also puts back the tryout settings the step changed: after a channel is removed or moved its mutes and
unwritten faders are back on the channel they were set on, WRITE MIX undone brings the unwritten mix back, U undone the
slot's candidate list. Edits are refused while the song file has changed on disk (RELOAD first), so they never overwrite a change
made elsewhere. While the live engine plays, each edit is swapped in where it plays (about 0.35 s for Nadir) and the
view stays on the pattern being edited. A song whose patterns are written by a generator loses these edits when the
generator is rerun. Patterns whose rows are not a literal `data: |` block are shown but cannot be edited here.

**MIDI input.** Click MIDI in the live bar to switch MIDI input on: the first time, the window asks whether the page
may use MIDI devices (Allow; the answer is kept, and MIDI stays on at the next launch until it is clicked off). A MIDI
keyboard plugged in before or while the app runs is then picked up through the page's Web MIDI, and the live bar shows
its name next to MIDI and VEL→VOL. Its keys play like the piano
keys, MIDI note 60 being C-5: a preview through the live engine (the INS instrument; in the Instruments tab the
instrument on show, in the Samples tab the slot), at the key's loudness with VEL→VOL; releasing the key releases the
note. In edit mode on the Pattern tab each key also enters its note at the cursor with the INS instrument, and with
VEL→VOL its velocity as the volume column (v01-v64), then the cursor moves STEP rows. While the live engine plays the
pattern on show, a key records instead: its note goes into the cursor's channel at the row playing when it went down,
and the cursor follows (the piano keys on the computer keyboard record the same way). Notes are entered one at a time
(no chords spread over channels). The app serves its
page from port 8723 when that is free (another app window takes any free port) and keeps the window's browser profile in
`%APPDATA%\VultureTracker\webview`, so the page's own settings (speed, latency, hex rows, MIDI) and the MIDI permission
carry over from one launch to the next.

**Conveniences.** F5 plays the song from its start, F6 loops the pattern at the cursor, F7 plays from the cursor and F8
stops, in every tab (F5 no longer reloads the page). METRO in the live bar clicks on every beat while the live engine
plays, higher on the first row of each bar, by the song's row highlight (rows per beat and per bar, which also draw the
pattern's row lines); the click is mixed in the engine, so it lands within a millisecond of the row. The small scope
beside it shows the engine's output. The Pattern tab's hint line says what the volume command and the effect under the
cursor do (from this file's tables in SONG_FORMAT.md). The Song tab's CLEAN-UP lists what the order list never plays:
patterns outside it, instruments no played pattern names, samples no used instrument maps; ✕ removes one (refused, and
the bar says why, while something still uses it), REMOVE ALL UNUSED (click twice) removes them all as one undo step.
WAVs dragged from the file manager can be dropped on a slot in the Samples tab (or on its waveform) to replace the slot's
WAV the way the Tryout's apply does, on the slot list (Samples tab, or SAMPLE SLOTS in the Instruments tab) for new
slots, or on the Tryout's candidate list to try them in the slot. A dropped WAV is saved beside the song under its own
name (the page cannot see where it came from; an identical copy already there is reused, a different one is numbered).

**Selections and commands.** Drag over cells, or hold Shift with the arrows (and Page Up/Down, Home, End), to select a
block the way trackers do: the first channel from the column the selection starts in, the last up to the column it
ends in, the channels between whole. Ctrl+A selects the pattern (the channels on show), Ctrl+L the cursor's channel; a
plain move or click drops the selection. The SELECTION bar (and its keys) works on the selection, or on the cursor's
cell when there is none: COPY (Ctrl+C; also puts the rows on the system clipboard in the song's cell notation), CUT
(Ctrl+X), PASTE at the cursor (Ctrl+V: the copied fields overwrite), MIX (Ctrl+Shift+V: only into empty fields), FLOOD (Ctrl+Alt+V: the clipboard again and again down to the
end of the pattern, e.g. one bar of hats over eight), CLEAR
(Delete), TRANSPOSE by a semitone or an octave (Ctrl+Up/Down, with Shift an octave; INS ONLY limits it to notes whose
cell names the INS instrument; notes stay within C-0..B-9), INTERPOLATE (Ctrl+I: the volume column and the effect,
from the first selected row to the last, per channel, where both ends carry the same command) and AMPLIFY (the
volume column by a percentage; a note without a volume gets one, counted from 64, the usual default) and HUMANIZE
(each note's volume moved at random within ± the given amount, from 64 when it has none, kept within 1–64). ECHO is the
tracker delay: the selected channel's notes (or, with no selection, the cursor's whole channel) are copied into another
channel ROWS later (and TICKS later on top, as `SDx` on each note), each at the given percent of its volume (its own
`vNN`, else the sample's default volume where the cell names an instrument, else the channel's last); in THIS PATTERN or
the channel's notes in every pattern of the WHOLE SONG. The target is a new channel added at the end (`<name> echo`,
panned LEFT, CENTRE or RIGHT; its fader moves it after) or an existing one, where cells that are not empty are left
alone. Song-wide effects (speed, tempo, jumps, breaks, global volume, pattern loops and delays) and pan commands are not
copied, and a copy that would land past its pattern's end is dropped; the bar reports the counts. Run it twice into
channels panned apart (say 3 rows at 60 % to the left, 6 rows at 35 % to the right) for a stereo echo; one or two ticks
with no rows doubles a lead instead. Each ECHO is one step for Ctrl+Z, the channel it adds included. COMPOSE writes plain
cells too, each command one step for Ctrl+Z with a count in the bar. GROOVE delays notes (note-offs too) by a tick count
per row, repeating from the pattern's first row, as `SDx`: `0 2` swings every other row by two ticks, `0 0 2 2` the
eighths of four-row beats; a 0 removes a delay, and a note that carries another effect keeps it undelayed. EUCLID makes
the selected rows of one channel (or, with no selection, the cursor's channel from the cursor down) a Euclidean rhythm
of the cell at their top: HITS spread as evenly as they go over STEPS (3 / 8 is `x..x..x.`), turned left by ROT, a step
every EVERY rows, each hit kept with the given percent (seeded: the same settings write the same cells); the other rows
are cleared. CHORD stacks each note of the selected channel (or the cursor's cell) into the chosen chord over that
channel and the ones to its right, with the note's instrument and volume, INV lowest tones moved up an octave; note-offs
are copied across so the chord ends whole, and a chord that needs more channels than the song has is refused (add them
in the SONG tab). LAYERS rewrites the instrument column of each note: CYCLE takes the listed instruments in turn, note
by note down each channel (round-robin), BY VOLUME picks by the note's volume, the list running quietest to loudest.
GROOVE and LAYERS work on the selected channels (every channel with no selection), in THIS PATTERN or the WHOLE SONG.
RENDER → SLOT renders the selected rows and channels (with no selection: the whole pattern, the channels the mixer lets
through) as they play in the song, with everything before them setting the state and the unwritten mix applied, then
lets the notes ring on for up to TAIL seconds with nothing new struck (cut at the first silence); the WAV is saved beside
the song (`render-<song>-<pattern>-<rows>.wav`, stereo when the channels differ) and added as a new sample slot, ready to
play, slice or edit (resampling). One step for Ctrl+Z. FIND… (Ctrl+F)
finds cells by note, instrument, volume and effect (`*` any characters, `?` one, an empty field anything; F3 or NEXT
the next match, in this pattern or the whole song, on the channels on show) and REPLACE ALL writes the given fields
into every match. Every command is one step for Ctrl+Z, a song-wide replace included.

**The Song tab** edits the song's structure, each change written into the song file in place and undone by Ctrl+Z (or ↶)
in the Pattern tab. SONG SETTINGS: click the title, tempo, speed, global volume, mix volume or stereo separation to
type it (a trailing comment on its line stays). ORDER LIST: click an entry to select it (a double-click, or EDIT ▸, opens
it in the Pattern tab); ◀ ▶ move it, REMOVE, DUPLICATE (the same pattern again after it), CLONE PATTERN (a copy of its
pattern under a new name takes its place, so it can change without touching the other orders that play the pattern),
INSERT or SET a pattern (or a `+++` skip, a `---` end) from the list, NEW PATTERN (empty, the given rows, after the
selected entry). PATTERNS: click a name to rename it (the order list follows) or its row count to change it (rows past a
new end are removed); CLONE; DELETE (click twice) only when no order plays it. CHANNELS: click a name to rename it;
▲ ▼ move a channel (its cells move in every pattern, and so do its tryout mute and unwritten faders); ✕ (click twice)
removes it and its cells in every pattern; + CHANNEL adds one at the end. The order list is written in the layout it
has: on one line (`orders: [a, b]`), or as a block with one `- name` per line, where an entry that stays keeps its
trailing comment and the comment lines above it (a flow list across several lines becomes one line, and is refused when
it holds comments). Patterns are to be written as `name:` with `rows:` and `data: |`, channels one `- {...}` entry per
line and the module as a block, which is how the songs here are written; anything else is refused with the reason.

**The Instruments tab** edits the song's instruments and adds sample slots, each change written into the instrument's
entry in place (one step for Ctrl+Z in the Pattern tab) and swapped into the live engine, so the piano keys (Z to M, Q to
U, from the Pattern tab's OCT) play the instrument on show as it now is. NEW (playing the chosen slot), CLONE and DELETE
(click twice; refused while a pattern plays it). Every field of the song format: name, fadeout, global volume, pan,
random volume and pan, filter cutoff and resonance, pitch-pan separation and centre (click to type; an empty value
turns an optional one off), NNA, DCT and DCA. NOTES → SAMPLE SLOTS: one slot for every note, or USE A KEYMAP for
ranges (C-0..B-4) each playing a slot at its own pitch, transposed (+12) or at one pitch (C-5, for drums); the strip
shows the slot every one of the 120 notes plays. The volume, panning and pitch (or, with `filter`, filter-cutoff)
envelopes are graphs: drag a node, click empty space to add one, right-click a node to remove it; SUSTAIN takes a node
(2) or a span (1-3), LOOP a span, and `carry` and on/off are checkboxes. SAMPLE SLOTS adds a slot for a WAV (typed or
BROWSE…); swapping a slot's WAV stays the Tryout tab's job. Settings the Tryout's INSTRUMENT panel holds unwritten for
an instrument are written or reset there first. A pattern with no notes, and every pattern in edit mode, shows all
its channels.

**The Samples tab** edits a slot's WAV and its entry. The waveform is drawn from peaks the server computes for the span
on show (both channels of a stereo WAV); the mouse wheel zooms around the pointer, Shift+wheel or the bar under it
scrolls, VIEW ALL / SELECTION / LOOP / + / − set the span, and past one frame per pixel the frames themselves are drawn.
Drag on the waveform to select; the info line gives the frames, the selection (frames and time) and the frame under the
pointer. The LOOP (blue, `L`) and SUSTAIN LOOP (amber, `S`) lines are dragged to move them, typed (START, END: frames of
the WAV, as in the song file), set from the selection (SELECTION → LOOP), or switched between off, forward, ping-pong and
the WAV's own loop (`from_wav`); each change is written into the sample's entry in place (a one-line entry keeps its
layout when only plain values change) and is one step for Ctrl+Z (here too). ▶ HOLD plays the slot through the live
engine, with the instrument that plays it (at the note that plays it at C-5) and the song as written, so a loop just
moved is heard once the engine has swapped the song in (the bar says so while it does); letting go is the note-off, so a
sustain loop ends. The piano keys play it too. EDIT → NEW WAV: TRIM TO SELECTION, FADE IN, FADE OUT, NORMALIZE (peak to
full scale), REVERSE and REMOVE DC work on the selection, or on the whole sample when there is none; CROSSFADE LOOP fades
the end of the loop into the audio just before its start (equal power, the length in ms; it needs that much audio before
the loop start). Each writes a new WAV beside the song (`<name>-trim.wav`, numbered, never over an existing file, the
source untouched), points the slot at it and keeps the loops with the audio (a trim moves them, a reverse of the whole
sample mirrors them); undo points the slot back, and the WAVs stay on disk. EFFECTS → NEW WAV work the same way, on the
selection or the whole sample: GAIN (dB), LOW-PASS and HIGH-PASS (Hz, 12 or 24 dB per octave), EQ (one bell band: Hz,
dB, Q), LOUDNESS (the RMS of what sounds brought to a dBFS target, never past full scale), PITCH (semitones at the same
length), STRETCH (percent of the length at the same pitch; loops move with the audio) and TRUNCATE SILENCE (every
silence under the dBFS level and longer than MIN shortened to KEEP). The filters are zero-phase; PITCH and STRETCH are a
phase vocoder with phase locking, the stereo image kept (steep stretches smear sharp attacks a little: slice a drum
loop instead). SLICE cuts the WAV (the selection, else all of
it) AT THE HITS (sensitivity 0–100: higher finds softer hits; each cut 1 ms before its hit, on a zero crossing) or into
EQUAL PARTS: FIND shows the cuts on the waveform, numbered, and SLICE → SLOTS writes exactly those, each slice its own
WAV beside the song (`<name>-slice01.wav`, a 1 ms fade at its end) and a new slot keeping the source's base note, volume
and bits; in a song with instruments a new instrument plays slice 1 on C-5, slice 2 on C#5 and so on, each at its own
pitch (a kit to play the pieces from the pattern). One step for Ctrl+Z. PROPERTIES: name, base note or c5 speed
(either replaces the other), default volume, global volume (refused while the Tryout mixer holds an unwritten GAIN for
the slot), default pan, bits, stereo, and the auto-vibrato (type, speed, depth, rate). A value the song format refuses
is not written and the bar says why.

The render
player and the live engine never play at once. LATENCY LOW measured 8 ms of output latency in WebView2 (the status
shows base plus output); LATENCY SAFE (40 ms) is there if playback crackles. Render & Export builds the `.it` (and a WAV)
and verifies it with libopenmpt. Renders are cached in `<song dir>/.tryout/` (the newest 60).

**The Record tab** records from an audio input (an interface such as a Focusrite Scarlett 2i2, or any input Windows
lists) into takes beside the song. INPUT lists the devices with their drivers (on Windows WASAPI, MME and DirectSound;
tick ASIO to list ASIO drivers too, such as a Scarlett's Focusrite USB ASIO, the lowest latency: it takes effect when the
app next starts), INPUTS picks what a take keeps (input 1, input 2, both as stereo, or both mixed to mono), RATE the
sample rate, EXCLUSIVE WASAPI's exclusive mode (the app alone on the device, at its own rate). OPEN starts the meters
(peak per input with a held peak, amber from -6 dBFS, CLIP when a sample reached full scale) and the TUNER (the note the
chosen inputs hold, in cents, green within 5); nothing is played back: monitor through the interface itself (a
Scarlett's DIRECT MONITOR switch), so there is no delay to hear. ● REC and ■ STOP make a take, with up to PRE-ROLL
seconds from before the click. Each take is written as a 16-bit WAV in `takes/` beside the song (`<name>-01.wav`,
numbered), its silent edges trimmed (TRIM SILENCE UNDER, keeping 10 ms before the first sound) and its note found (FIND
THE NOTE: written as the WAV's root note), then goes where THEN says: a CANDIDATE OF THE SLOT in the Tryout (heard in
the song, rated, written with U like any candidate), a NEW SAMPLE SLOT (tuned to the cent: its c5 speed makes the note
found play true), or KEEP IN THE LIST. TAKES THIS SESSION lists them (▶ plays one; → CANDIDATE and → NEW SLOT send it on
later). In the Samples tab, AUTO LOOP proposes loop points for a sustained sound (a whole number of its periods late in
its steady part, on rising zero crossings where the waveform matches best); CROSSFADE LOOP then smooths the wrap.
Recording needs `pip install sounddevice` in a source checkout (the exe carries it); `VT_FAKE_AUDIO=1` swaps in a
simulated two-input interface to try the tab without one.

**Instrument panel.** Under SLOT, INSTRUMENT shows the instrument that plays the slot (through `sample:`) and what the
tracker does to every note it plays: a volume envelope (ATTACK and DECAY in ticks, SUSTAIN held until note-off; 0 lets
the note die away), RELEASE (the instrument's `fadeout`: how fast a replaced or released note fades), a resonant
low-pass (CUTOFF, 127 = off, labelled with its approximate -6 dB point; RESONANCE) with a SWEEP on every note (FROM and
TO a share of the cutoff, over TIME ticks), and RANDOM VOL per note. The curve above the sliders draws the volume
envelope and the sweep. The settings apply to the song and to every candidate in the slot, re-render the tryout on each
move and belong to the unwritten mix: kept in `<song>.tryout.json`, recorded with listening notes, dropped by RESET (or
RESET MIX) and written into the instrument's line (`volume_envelope`, `fadeout`, `filter_cutoff`, `filter_resonance`,
`pitch_envelope` with `filter: true`, `random_volume`) by WRITE (or WRITE MIX), which shows the change first. An
envelope in the song that the panel cannot draw (more nodes, a loop) is marked custom and stays until one of its
sliders moves. The header folds the panel.

**Listening notes.** NOTE… (`N`) in the bar under the player drops a note at the playhead. A note records the time, order and row, what was playing (the song or a candidate, the
mutes, the unwritten mix) and the channels sounding there (each channel's last note cell with its sample number;
`~` marks a looped tone held from an earlier note); click the chip of the channel you mean and add words if you like.
Notes live in `<song>.notes.json` and are rendered as `<song>.notes.md`, a report grouped by order (the tryout ratings
at the end) for a collaborator who cannot listen; the NOTES tab lists and edits them. Nothing touches the song file.
Notes belong to the version of the song they were made against: when the song changes outside the app (a rebuild), the
notes on the old version move to `<song>.notes-<hash>.json` and `.md` beside it and the NOTES tab starts empty; the
app's own writes keep them, and the report marks their version.

**Standalone binary:** `pip install pyinstaller && python tools/build_exe.py` produces `dist/vulturetracker.exe`,
the whole CLI with libopenmpt bundled: `vulturetracker.exe gui song.yaml`. Double-clicking it opens the app on its
open-a-song screen; dropping a song file onto it opens that song. Synth rendering (`synth`, `audition`)
still needs the plugins and packs from `tools/` next to a checkout, as described in SAMPLING.md.

## Making samples: synths, recordings, printed effects

`vulturetracker synth recipe.yaml` renders samples from a YAML recipe. A sample comes from a free synth
(Surge XT, Dexed's DX7 or OB-Xd's Oberheim: patch, notes or phrases, hold time) or from a recorded audio file,
such as the CC0 libraries that `tools/fetch_cc0.py` downloads or a royalty-free drum-machine pack. A recipe can print an effects chain into each
sample (reverb, delay, chorus, distortion, 8-bit / low-rate lo-fi) and bake in crossfaded loops.
`vulturetracker audition 'Pads/*'` (or a file glob) lets you hear a whole set of candidates in one WAV, and
`vulturetracker tryout` plays part of a song once per candidate sample, so you can choose sounds in context.
Setup and the recipe format are in **[SAMPLING.md](SAMPLING.md)**:

```
pip install pedalboard mido
python tools/fetch_surge.py            # Windows: portable Surge XT into tools/surge-xt/
python tools/fetch_instruments.py --install-obxd   # Dexed, OB-Xd, drum-machine samples
python tools/fetch_cc0.py              # CC0 recordings into tools/cc0/
python -m vulturetracker synth demo3/kit.yaml
```

## Writing songs

The song format is documented in **[SONG_FORMAT.md](SONG_FORMAT.md)**. It's the full reference,
written so an AI can compose from it alone. A song has `module` settings, numbered `samples`
(WAV files), `instruments` (keymaps and envelopes), named `patterns`, and an `orders` list. Pattern
rows use OpenMPT-style cells:

```yaml
patterns:
  main:
    rows: 16
    data: |
      00: C-5 01 v64 ... | E-3 02 ... ...
      01: ...            | ===
```

Four demos, and a suite:

- `suite/nadir/nadir.yaml`: "Nadir", 3:47 and loopable, the first piece of a suite where each piece is inspired by one
  stylistic group of the Unreal Tournament (1999) soundtrack, this one by its dark, sub-heavy tracks: a driving grid at
  144 BPM (tempo 120, speed 5, 16-row bars) under a dark mood, a sub drone under everything, one pedal throughout
  (G Dorian over one pitch collection), open-fifth synth and recorded string beds, a soft synth lead doubled by a
  violin section as the melody, one moving line at a time under it (a dark arp or a portamento riff with an echo), a
  choir call, and drums with booms and a recorded drum bar chopped in surround. 20 channels, 34 patterns; v6 is the
  last pass, built from the listener's notes (`suite/HANDOFF.md`). Its sounds are additive models (`gen_samples.py`),
  CC0 drums (`gen_drums.py`), CC0 string sections (`gen_strings.py`) and Surge XT patches picked by measurement and
  by ear in the tryout (`cand*.yaml`, `measure.py`, `kit.yaml`, then `gen_floor.py`); `gen_patterns.py` lays out the
  patterns. `PROVENANCE.md` says what it takes from its reference group (descriptions only); `suite/NEXT-PROMPT.md`
  is how the next pieces are meant to be made (one reference track each).
- `demo4/vantage.yaml`: "Vantage", 3:03 and loopable, E minor at 168 BPM (tempo 140, speed 5), in the style of a
  late-90s arena-shooter module: a sub-bass drone holds the tonic under everything, a synth riff on three
  round-robin channels rides over it, chord samples sit low (a minor bed, a major bed that swells once per pattern,
  a three-chord motif with an echo), a choir calls in the build and the break, drums arrive a minute in and leave
  for the break, and there is no lead melody and no chord progression. 16 channels, 32 patterns. The riff and sub
  bass are additive models (`demo4/gen_samples.py`); the beds, motif chords and choir are Surge XT patches rendered
  by `demo4/kit.yaml`; the rhythm bed is a one-bar break played by the CC0 Big Rusty Drums kit (`demo4/gen_break.py`)
  under MusicRadar drum-machine hits (`demo4/drums.yaml`) and demo3's TR-8 renders. Patterns are laid out by
  `demo4/gen_patterns.py`. UT99's Foregone Destruction was the reference for its grid and layer plan;
  `PROVENANCE.md` says what was taken from it and what was changed.
- `demo3/undertow.yaml`: "Undertow", 3:12 and loopable, E minor at 125 BPM, built on what the Unreal
  Tournament (1999) soundtrack modules measure: 16 channels in sample mode at speed 6 (4 rows per beat,
  4-bar patterns), 16-bit samples at 11 kHz (pads) to 22 kHz (bass, lead), 21 distinct patterns over 25
  orders. Its sounds were picked by ear with `tryout`: Roland TR-8 drums, an OB-Xd analog bass and gated
  string machine, a Dexed DX7 string pad, a soft DX7 Rhodes lead with chorus and a long reverb printed in,
  and CC0 cymbals (`demo3/kit.yaml`, `demo3/drums.yaml`). It shows hard-panned L/R channel pairs with small
  `Oxx` offsets (drums) or a one-tick `SD1` delay (lead) for width, per-hit `S8x` hat panning, volume-slide
  (`Dxy`) gating of a sustained chord, and `FF1`/`EF1` detune between pairs. Its patterns are laid out by
  `demo3/gen_patterns.py`. The drum samples can't be redistributed, so building it needs
  `tools/fetch_instruments.py` and `synth demo3/drums.yaml` first.
- `demo2/iron_relay.yaml`: "Iron Relay", 55 s, D minor at 140 BPM, modelled on late-90s
  arena-shooter modules. It has 16 channels at speed 3 (32nd-note grid). Its 15 samples are
  rendered from Surge XT by `demo2/kit.yaml`. It shows the classic techniques: a sequenced arp
  phrase chopped with `Oxx` and transposed per chord, `Zxx` filter sweeps, a multisampled bass
  with portamento slides, crossfade-looped stereo pads, a reverse-cymbal riser, `Qxy` snare rolls,
  note-delay swing, and echo channels. Its patterns are laid out by `demo2/gen_patterns.py`.
- `demo/arena.yaml`: the first, simpler 42-second demo with procedurally generated placeholder
  samples. Its patterns are laid out by `demo/gen_demo.py`.

Each generator holds the musical choices (chords, rhythms, melodies) as Python data and rewrites the
patterns in its song file. The song file is the source of truth and the generator is its scaffold: rerunning it
discards any hand edits made to the patterns since, so either keep composing in the generator or stop rerunning it.

## Using your own samples

The WAVs in `samples/surge/` are rendered from Surge XT, those in `samples/demo3/` from OB-Xd, Dexed
and CC0 recordings (credited in `samples/demo3/ATTRIBUTION.md`), and those in `samples/demo4/` are additive
models measured on a reference module plus a break played by a CC0 drum kit (`samples/demo4/ATTRIBUTION.md`);
see above. `samples/local/` holds renders of
samples that may not be redistributed and is gitignored. The ones directly in `samples/`
are procedurally generated placeholders (`samples/gen_placeholders.py`).
To use real ones, change a sample's `file` in the song. Also set `base_note` to the pitch recorded
in the WAV, and `loop` if it should sustain (`loop: from_wav` uses loop points saved by a sample
editor). Then `check` and `build`.

## Provenance

`PROVENANCE.md` tracks every sound or figure that was derived by measuring material we do not own (the UT99
reference modules for demo4), how far each is from the original, and what replaces it before a release.

## Tests

```
python -m unittest discover tests
python tests/fetch_fixtures.py   # optional: downloads OpenMPT's IT test modules for the import round-trip test
```

## Notes

- Output is IT 2.14 format in instrument mode with uncompressed 8/16-bit samples, playable in
  OpenMPT, Schism Tracker, Impulse Tracker and anything built on libopenmpt.
- Anti-aliasing. WAV renders are mixed at twice the output rate and band-limited back down with a windowed-sinc
  low-pass (`render --oversample 1` turns it off), so content the mixer produces above the output's Nyquist frequency
  is removed instead of folding into the audible range. Two things still create false frequencies inside a module:
  playing a sample far above what its content allows (its bandwidth times the transposition ratio should stay under
  about 18 kHz: a sample 4.5 kHz wide may play two octaves up, one 9 kHz wide one octave; render multisamples with
  `notes:` and a keymap for the rest), playing a bright sample more than about three semitones below its root (`check`
  warns when the images of its lowest note come within 60 dB), and low-rate samples interpolated by the player (the module setting
  `sample_rate: 44100` resamples every sample to the playback rate at compile time, band-limited, which removes that
  imaging in every player at the cost of file size). `vulturetracker/resample.py` holds the resampler.
- `import` keeps patterns, instruments, envelopes and samples. It drops embedded MIDI macros and
  OpenMPT-only extensions (with a warning). It also reads XM, S3M and 31-sample MOD files (`vulturetracker/modreader.py`,
  told apart by their headers; the app's start screen has IMPORT A MODULE, which writes `name.yaml` and `name_samples/`
  beside the module and opens it). Each is mapped onto IT the way it plays in libopenmpt, measured against it
  (`tests/test_modimport.py` renders small modules both ways): ProTracker and FastTracker 2 effects to their IT letters,
  notes to IT's C-5 = the sample's c5 speed (MOD samples at the PAL Amiga rate, 8287 Hz), IT's old-effects mode for
  vibrato and tremolo, MOD channels at a quarter and three quarters of the pan, Scream Tracker 3's shared effect memory
  written out, XM's per-instrument samples as one list with relative note and finetune in each c5 speed, XM key-offs on
  instruments without a volume envelope as note cuts, XM envelope loops a tick shorter, patterns longer than IT's 200
  rows split into 192-row parts (the order list, jumps and breaks follow), and only what the song plays kept when it has
  more than 99 instruments or samples. The mix volume is measured: libopenmpt mixes each format (and XMs by the tracker
  that saved them) at a level of its own, so the import renders the original and the converted module and sets the mix
  volume to match. What IT cannot say is dropped and listed at the top of the song file (Amiga filter, finetune and
  invert-loop commands, AdLib instruments, slow XM pan slides rounded); a pan law of its own (MilkyTracker files) and
  XM vibrato phases a tick apart are not converted. Measured locally on 7 MODs, 7 S3Ms and 19 XMs from the Mod Archive
  and elsewhere (those files are not in the repository, so this cannot be re-run from a checkout; `tests/test_modimport.py`
  is what can), the imported songs play within a median 0.3 dB of libopenmpt's level (the worst file 1.3 dB) over their
  first minute. IT patterns longer than 200 rows (libopenmpt plays up to 1024) are split the same way, and references
  to instruments or samples above 99 are dropped with a warning.
- Renders are as long as the song: its duration times the passes (`render --repeat N`), plus a few seconds for the
  tail. Only a render that repeats forever stops, at ten minutes.
- `vulturetracker/api.py` exposes plain functions (`new_song`, `add_sample`, `add_instrument`,
  `set_pattern`, `set_orders`, `check`, `build`, `render`) for tools and agents.
- The writer follows [ITTECH.TXT](https://github.com/schismtracker/schismtracker/wiki/ITTECH.TXT)
  and was checked against OpenMPT's
  [Load_it.cpp](https://github.com/OpenMPT/openmpt/blob/master/soundlib/Load_it.cpp).
- Bundled libopenmpt is BSD-licensed; see `vendor/LICENSE.txt` and `vendor/Licenses/`.
