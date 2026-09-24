# What VultureTracker needs to be a working tracker (compared with OpenMPT)

Written 2026-09-24, after program round 6 (spectrogram, typed values, MP3 export, playback loop). The yardstick is
OpenMPT 1.3x as a tracker for IT modules. VultureTracker is not built that way today: the song is a YAML file written by
hand or by a generator, compiled to `.it` and rendered to WAV by libopenmpt; the app (`vulturetracker/gui.py` +
`gui.html`) picks samples in context, mixes, takes listening notes and shows the patterns **read-only**. Every row
below is marked:

- **have**: works now, in the app or the CLI;
- **partial**: some of it exists, or it exists only as YAML/CLI and not in the app;
- **missing**: nothing yet.

"YAML" means the song format (`SONG_FORMAT.md`) can express it, so the compiler already supports it and only the
editor is missing. Estimates are in **sessions** the size of round 6 (four app features, each with a test and a check in
the real window). One design rule holds for every editing feature: the YAML stays the source of truth, so every edit is
a small in-place text change of the song file (the way `State._edit_text` writes the mix today), with an undo history
of song texts; a song whose patterns come from a generator (`gen_patterns.py`) loses app edits when the generator is
rerun, as GUIDE.md already says for hand edits.

## 1. Pattern editing

| Feature (OpenMPT) | Status | Where it is now | Missing piece | Est. |
|---|---|---|---|---|
| Pattern display: notes, instruments, volume and effect columns, row highlights, hex/dec rows, channel names | have | `gui.py` `pattern_rows`, `gui.html` `renderPat`, `setHex` | — | — |
| Cursor in the pattern (row, channel, column), scrolling with the keyboard | missing | the view is read-only | a cursor model per column, keyboard navigation | with the row below |
| Keyboard note entry (QWERTY piano, octave keys, edit step, instrument and volume columns, effect entry, note-off/cut/fade keys, delete, insert/remove row) | missing (YAML: yes) | patterns are `data: \|` text blocks, one line per row (`song.py` `_pattern`) | page-side entry; server edits one row line in place, recompiles, re-renders the section | 2 |
| Undo / redo | missing | the song file is in git; the app writes it only on U / WRITE MIX | a stack of song texts per session (every edit is one text write), Ctrl+Z / Ctrl+Y | in the 2 above |
| Selections (block, whole channel, whole pattern), copy, cut, paste, mix-paste, paste flood | missing | — | selection model in the page; clipboard as cell text (the notation is already OpenMPT's) | 1 |
| Transpose (semitone, octave, on a selection or an instrument only) | missing | the generators transpose in Python | server-side cell rewrite over a selection | in the 1 above |
| Interpolate (volume column, effect parameters) over a selection; amplify; humanize | missing | — | server-side cell rewrite | 0.5 |
| Find / replace (note, instrument, effect) | missing | `grep` on the YAML | a find panel over the parsed patterns | 0.5 |
| Pattern resize (rows), clear, duplicate channel, swap channels | missing (YAML: yes) | edit `rows:` by hand | server-side pattern rewrite | in orders (§2) |

Subtotal: about 4 sessions.

## 2. Orders and patterns

| Feature (OpenMPT) | Status | Where it is now | Missing piece | Est. |
|---|---|---|---|---|
| Order list: view, jump to an order | have | arrangement grid (`gui.html` `grid`), SECTION TO LOOP, the Pattern tab follows the selected order | — | — |
| Order list editing: insert, delete, duplicate, move, `+++` skip / `---` end markers | partial (YAML: yes) | `orders:` in the YAML, `api.set_orders` | editing in the grid, written in place | 1 |
| New / clone / rename / delete pattern, pattern length | partial (YAML: yes) | `api.set_pattern`, by hand | pattern list panel | in the 1 above |
| Channel management: add, remove, rename, reorder, default volume and pan | partial | volume/pan in the mixer (have, WRITE MIX); names and count by hand | add/remove/rename; reordering rewrites every pattern column | 0.5 |
| Song properties: title, tempo, speed, rows per beat/bar, global and mix volume | partial | mix volume in the mixer; the rest by hand | a song panel | in the 0.5 above |
| New song from the app | partial | `api.new_song` (CLI/agents) | a NEW button on the start screen | 0.1 |

Subtotal: about 1.5 sessions.

## 3. Real-time playback

| Feature (OpenMPT) | Status | Where it is now | Missing piece | Est. |
|---|---|---|---|---|
| Play the song / a section | have | renders through libopenmpt to WAV (`State._worker`), played by the page's `<audio>` | — | — |
| Follow the playhead in the pattern | have | `followPlayhead` | — | — |
| Pattern/section loop | have | SECTION TO LOOP renders whole orders; the playback loop (round 6) loops any row span, playback only | — | — |
| Play from the cursor / from a row, play row | partial | seek on the progress bar or the spectrogram, within the rendered section | the live engine below; with renders only, "play from here" needs the section re-rendered from that order | with the engine |
| Live mute / solo | partial | every change re-renders the section (0.35 s for 4 orders, about 3 s for a whole song at 2x) and the old render plays until the new one lands | the engine: libopenmpt's interactive interface mutes a channel at once | with the engine |
| Note preview (hear a sample or instrument at a pitch from the keyboard) | missing | SAMPLE ALONE plays a candidate's WAV at its own pitch | the engine: `play_note` in libopenmpt's interactive interface (the vendored 0.8.9 DLL exports `openmpt_module_ext_*`) | with the engine |
| Instant audition of edits | partial | a mixer or instrument-panel move re-renders the section; a pattern edit would need a write, a recompile (0.3 s with the resampling cache) and a render | the engine swaps in the recompiled module at the current order and row | with the engine |
| Live VU meters per channel | partial | soloed RMS meters per section (`channel_levels`), not live | `openmpt_module_get_current_channel_vu_*` from the engine | with the engine |
| Tempo/pitch change while playing | partial | SPEED (the browser's playback rate, pitch kept) | engine: tempo factor | with the engine |

**What live playback needs (architecture).** Today nothing plays in real time: the server renders a WAV and the page
plays it, which is right for the tryout (identical renders to compare) and stays. An editor needs a second path, a
live engine:

1. **Engine in the Python process (recommended).** A `LoadedModule` created through `openmpt_module_ext_create_from_memory`
   from the compiled `.it`, pulled by an audio callback (`read_interleaved_stereo`, 512-1024 frames, WASAPI shared mode,
   about 20-30 ms latency) on its own thread. Output needs one new dependency: `sounddevice` (MIT, bundles PortAudio,
   about 1 MB, works in the exe), or WASAPI through ctypes with no dependency at more code. The page gets the position
   (`get_current_order/row`, channel VU) by polling a small endpoint each animation frame, or by server-sent events.
   Commands (play from order/row = `set_position_order_row`, mute = interactive `set_channel_mute_status`, note preview =
   `play_note` / `note_off`, tempo factor) are POSTs. An edit recompiles the song (0.3 s, the resampling is memoised)
   and the callback swaps modules at the same order and row. Same DLL as the renders, so it sounds like the renders
   except for the 2x oversampling and band-limiting (a monitoring path; renders and exports keep the anti-aliased path).
2. **Engine in the page.** libopenmpt compiled to WebAssembly (the official emscripten build, BSD) in an AudioWorklet; the
   server sends compiled `.it` bytes. The page owns the clock (sample-accurate playhead, no polling), but the build must
   export the interactive `ext` functions for mute and note preview (to be checked for the build used), and the wasm build would have to track the vendored DLL's version so both play alike.

Option 1 reuses `openmpt.py` and the vendored DLL and keeps one libopenmpt; option 2 avoids an audio dependency. Engine
with play from cursor, live mute/solo, note preview, VU and edit swap: **2 sessions** (1 for the engine and position sync,
1 for the page's transport, preview and edit swap).

## 4. Sample editor

| Feature (OpenMPT) | Status | Where it is now | Missing piece | Est. |
|---|---|---|---|---|
| Waveform view | have | the SAMPLES tab (round 12): peaks per pixel column from `/api/wave` (`wave_peaks`), wheel zoom to single frames, scrolling, selection | — | — |
| Loop and sustain-loop points (forward, ping-pong), loop from the WAV | have | dragged, typed or set from the selection on the waveform, written in place (`sample_set`); ▶ HOLD previews through the live engine | — | — |
| Trim, fade in/out, normalize, reverse, DC removal, crossfade loop | have | `sample_process`: a **new** WAV beside the song (never the source file), the slot pointed at it, one undo step | — | — |
| Resample, bit depth, stereo/mono | partial | `bits` and `stereo` in the properties panel; resampling stays the module's `sample_rate` (`resample.py`) | per-sample resampling, not proposed | — |
| Sample properties: base note / C5 speed, default volume, global volume, pan, auto-vibrato, name | have | the PROPERTIES panel, typed values | — | — |
| Draw / pencil, record from input | missing | — | not proposed (samples come from synths and recordings by recipe) | — |

Subtotal: about 2.5 sessions.

## 5. Instrument editor

| Feature (OpenMPT) | Status | Where it is now | Missing piece | Est. |
|---|---|---|---|---|
| Volume envelope, fadeout, filter cutoff/resonance, filter sweep, random volume | partial | the instrument panel (attack/decay/sustain shape only; `voice_of`, `voice_entry`, `renderVoice`) for instruments that play one sample through `sample:` | — | — |
| Full envelope editor: any nodes, loop and sustain loop, for volume, panning and pitch/filter | missing (YAML: yes) | envelopes the panel cannot draw are marked custom and kept | a node editor on the envelope curve | 1 |
| Keymap / sample map (multisamples, `play_note`) | missing (YAML: yes) | `keymap:` by hand; the panel skips keymapped instruments | a keyboard map editor | 0.5 |
| NNA, duplicate check (DCT/DCA), global volume, pan, pitch-pan separation, random pan | missing (YAML: yes) | by hand | fields in the panel | 0.25 |
| New / delete / clone instrument | partial | `api.add_instrument` | buttons in the app | 0.25 |

Subtotal: about 2 sessions.

## 6. Formats

| Feature (OpenMPT) | Status | Where it is now | Missing piece | Est. |
|---|---|---|---|---|
| IT export | have | `itwriter.py` (IT 2.14, instrument mode, uncompressed 8/16-bit), verified by libopenmpt on every build | IT sample compression (file size only) | 0.5 if wanted |
| IT import | have | `itreader.py` `import_it` (IT 2.14/2.15 compressed samples), CLI `import` | — | — |
| MOD / S3M / XM import | have | round 15: `modreader.py` (own readers into `Module`, measured against libopenmpt), CLI `import` and IMPORT A MODULE on the start screen | — | — |
| WAV / MP3 / OGG / FLAC / stems export | have | Build + render WAV, EXPORT STEMS, EXPORT SONG AS (round 6) | — | — |
| MPTM / XM / MOD export | missing | — | not proposed: the target is IT for the game | — |

Subtotal: about 3 sessions for the three imports.

## 7. MIDI input

| Feature (OpenMPT) | Status | Where it is now | Missing piece | Est. |
|---|---|---|---|---|
| Note entry and note preview from a MIDI keyboard, velocity to volume column | have | round 13: Web MIDI in the page (WebView2 grants it without a prompt), preview through the live engine, entry at the cursor in edit mode, VEL→VOL | — | — |
| MIDI record while playing (quantised to rows) | missing | — | engine position + entry | 0.5 |

## 8. Live plugins

| Feature (OpenMPT) | Status | Where it is now | Missing piece | Est. |
|---|---|---|---|---|
| VST instruments and effects played live in the module | partial (offline) | synths and effects are printed into samples by recipe (`synth.py` via pedalboard: Surge XT, Dexed, OB-Xd; `SAMPLING.md`) | not proposed: IT cannot carry plugins (only OpenMPT's MPTM can), the music is meant to play as `.it` in the game, and pedalboard is GPL-3 and kept out of the exe | — |
| Re-render a synth sample from the app (change a recipe parameter, hear it in the song) | missing | CLI `synth recipe.yaml --only` then the tryout | a recipe panel that renders a candidate into the slot's list | 1 |

## 9. Tracker conveniences

| Feature (OpenMPT) | Status | Where it is now | Missing piece | Est. |
|---|---|---|---|---|
| Keyboard map for transport (play song, play pattern, stop, play from cursor) | have | F5-F8 in every tab (round 14), Space in the Pattern tab | — | — |
| Effect help (what `Dxy` does, on hover or in a status line) | have | the Pattern tab's hint line at the cursor, from SONG_FORMAT.md's tables (`effect_help`, bundled with the exe) | — | — |
| Channel mute/solo, channel names, recent songs, song length and timing | have | stems rail, start screen, top bar | — | — |
| Clean-up: unused samples, instruments, patterns | have | the Song tab's CLEAN-UP (`State.unused`, `sample_delete`) | — | — |
| Drag a WAV onto a slot | have | drops on a slot, the slot lists and the candidates; uploaded and saved beside the song | — | — |
| Metronome, row/beat highlight while playing | have | METRO (a click mixed in the worklet on beat rows); row lines follow the song's highlight | — | — |
| Autosave / backups | have in effect | every edit is a write to a text file in git; undo would add the session history | — | — |
| Spectrum analyser, oscilloscope | have | SPECTRUM tab (round 6); a scope of the engine's output in the live bar (round 14) | — | — |

Subtotal: about 1 session.

## Summary and proposed order

| Group | Status | Sessions |
|---|---|---|
| 3. Live playback engine (play from cursor, live mute, note preview, VU, edit swap) | partial | 2 |
| 1. Pattern editing (cursor, entry, undo; selections, transpose, interpolate, find) | missing | 4 |
| 2. Orders, patterns, channels, song properties | partial | 1.5 |
| 5. Instrument editor (full envelopes, keymap, the rest of the fields) | partial | 2 |
| 4. Sample editor (waveform, loop points, non-destructive edits, properties) | have (round 12) | 2.5 |
| 7. MIDI input (Web MIDI) | entry and preview have (round 13); record while playing missing | 1 |
| 9. Conveniences | have (round 14) | 1 |
| 6. MOD/S3M/XM import | have (round 15) | 3 |
| 8. Live plugins | not proposed | — (1 for the recipe panel) |

About 17 sessions for everything proposed. Suggested order:

1. **Live engine** (2): everything interactive rests on it, and it is useful at once for the listening the owner does now
   (play from any row, mute without waiting for a render).
2. **Pattern editing core** (2): cursor, keyboard entry, in-place row writes, undo; with the engine, every edit is heard
   at once.
3. **Selections, transpose, interpolate, find** (2).
4. **Orders and patterns** (1.5).
5. **Instrument editor** (2), then **sample editor** (2.5).
6. **MIDI input** (1) and **conveniences** (1).
7. **MOD/S3M/XM import** (3), only if older modules are to be edited here; OpenMPT can convert them to IT meanwhile.

Alternative if the owner wants editing before real-time audio: 2 and 3 first (each edit re-renders the section, 0.35 s
for 4 orders), then the engine.

**Owner's choice (2026-09-24)**: the order above; the engine as option 2, libopenmpt in the page. Its proof is done:
the official 0.8.9 wasm build exports the `ext` functions; memory and the function table come from the instance, so
the interactive interface is callable; in the node check it renders within 2 LSB of the DLL, mutes exactly like the
header's disable bit, seeks, and previews notes; in WebView2's AudioWorklet (after polyfilling TextDecoder,
performance and crypto, which a worklet lacks) it starts in about 20 ms, loads Nadir's 9.3 MB module in 44 ms,
renders 250-860 times faster than real time, and runs at 8 ms output latency. It is now the Pattern tab's transport
(round 7): play from the cursor or the start, loop the pattern or the playback loop's span, follow, live mutes and
solo, header VU, note preview, SPEED as tempo factor, edits swapped in where it plays. Pattern editing core (§1: a
cell cursor, keyboard entry, clear, insert/remove, in-place writes checked by a full compile, undo/redo) is built
(round 8), and so are selections, copy/cut/paste/mix-paste, clear, transpose, interpolate, amplify and find/replace
(round 9; humanize and paste flood left out), and orders and patterns (§2) in the SONG tab (round 10: order list,
new/clone/rename/resize/delete pattern, channels renamed, added, moved and removed, song settings; a new song from the
app followed in round 11), the instrument editor (§5: every field, envelopes as graphs, the keymap, new / clone /
delete, sample slots added) and paste flood (round 11), and the sample editor (§4, round 12: waveform, loop points,
edits written as new WAVs, properties), and MIDI note entry and preview (§7, round 13; recording while playing left out).
The conveniences (§9) followed in round 14 and MOD/S3M/XM import (§6) in round 15: every proposed group is built.
