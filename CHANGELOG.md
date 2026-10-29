# Changelog

What changed in each VultureTracker release (the GitHub release notes, without their download and checksum parts). Newest first.

## Unreleased

- Score shortcuts ignore hidden panels, and refreshing an order preserves typed positions and range selections.
- Shorter README with refreshed Pattern, Score, Tryout and Spectrum screenshots from the project demo.
- Print preview and Print / Save PDF now accept generated tracker staff previews, using the same full-song
  grouping as TAB / SCORE. Parts, paper settings and bar excerpts work without authoring or converting a score.
- Pattern uses larger text, clear channel boundaries and stronger beat, measure, cursor and playback highlights.
  All channels are visible by default, with horizontal scrolling that follows keyboard navigation. Selection,
  automation and composition tools are grouped under a collapsed Advanced control; shortcuts remain available.
- Imported tracker songs without authored score tracks now show a read-only staff preview of the entire song order
  in TAB / SCORE, with repeated pattern occurrences and labeled boundaries; stored unsequenced patterns are excluded.
  All active channels are represented with matching octave labels; clicking a note selects its
  original Pattern cell and occurrence. The shared playback marker follows notes, rests and pattern changes without
  replacing the score, scrolling within the score pane to stay visible. Rhythms and lengths
  are row-grid hints, not a transcription of tracker effects or sample playback. The song is not converted or saved.
- Tracker staff previews group channels using the same single sound slot into readable parts by default.
  Chords and independent voices preserve overlapping rhythms; exact unisons share a notehead with source-channel
  selection. Mixed/unknown sounds stay separate. The Track selector also offers separate channels and individual
  channel inspection. Grouping only changes notation, leaving song data and playback intact.

## 1.9.0 (2026-10-24)

- Standalone IT export handles the sub-tick gates, strums, grace notes and pitch controls in Boys In The Band
  and Advent Of Panurge by rendering only the affected passages into samples. Export notices identify them;
  other passages remain tracker notes and the native song retains every editable note. Unsafe conversions
  still refuse before writing. Ordinary tempo changes no longer produce a misleading score warning.
- Pattern defaults to a continuously scrollable song: neighbouring bars fill the pane, with a scrollbar through
  every order and click-to-edit rows. Up/Down and Page Up/Down cross pattern boundaries; manual browsing pauses Follow.
  Previous/next, direct song position and the optional single-pattern view remain available.
- TAB/SCORE starts with the clean TuxGuitar layout: horizontal all-track staff/TAB at 80%, no printed dynamics,
  and TuxGuitar written staff pitch. Explicitly saved view choices survive upgrades. The preset remains available;
  these are view preferences and notes, velocities, playback and Undo stay unchanged.

- Native GP5 import accepts ordinary double barlines, key changes, declared drum fret counts and GP5
  display/mix metadata. Ignored source values remain in the import report; placeholder sounds do not
  emulate source MIDI effects or program changes. Bend coordinates follow TuxGuitar rounding with
  the original values retained. Tied notes now find their actual preceding beat instead of an earlier
  equal-looking beat. Key/clef changes remain visible through following bars; GP3/4/5 export retains
  shared key changes and double barlines. TG export explicitly refuses double barlines.
- Switching the displayed Part or Track keeps Follow playback enabled and the playing marker in view;
  an explicitly paused Follow setting stays paused.
- Voice changes also preserve Follow playback. Selecting an empty editing voice no longer hides the
  part's playback marker. Ctrl+F6 and Ctrl+F7 retain a native caret's exact fractional start position.
- Finishing a rhythm, phrase, Paste or string-move edit no longer overrides a Voice/caret change made
  while the save was pending. The submitted edit still completes as one Undo/Redo step.
- The navigation bar wraps at narrow window widths so Project and Notes stay reachable alongside TAB/SCORE.
- Editing repeated patterns no longer falsely refuses a boundary release already supplied by a following note,
  or a harmless release at song start. Releases that would truncate another predecessor still refuse atomically.

- Free duration repacks whole beat groups across both voices using TuxGuitar's voice-end rules. Notes,
  rests, annotations and adjacent ties move together, with one exact Undo/Redo step. Matrix Free entry
  retains its distinct anchored behavior. Free duration closes unwritten gaps, including gaps created by a
  previous two-voice edit. Invalid authored bars automatically require Free mode; the control explains why.
  Free overflow preserves an unmetered pattern's original length as a meter for later repair.
  Independent beat groups that coincide retain their identity across another Free edit, save/reopen and
  TG XML/legacy interchange. Their strokes and chord metadata remain separate. Normal rest insertion,
  caret-rest deletion and unannotated Fit join the correct destination group and retain exact history.
  Rest insertion/deletion and Fit transfer chords and strokes with the last sounding voice, while text stays
  with a remaining voice, including a rest. Conflicting annotations, inexact IT timing, consumed annotated
  rests and complex ambiguous paste still refuse explicitly. GP3–5 export accepts redundant group labels;
  true independent same-onset groups still refuse because GP reimport merges their identity.

- Native Copy/Paste follows the latest beat or measure clipboard. Ctrl+C without a beat selection opens
  measure controls; Ctrl+V dispatches by clipboard kind and replaces whole beats at selection start.
  Paste safe retains empty-only behavior. Failed copies and cancelled measure controls keep the previous copy.
  Whole-beat replacement clears both voices and follows TuxGuitar's unequal-duration advancement;
  copying across unwritten silence preserves the gap, including across source bar lines. Span paste and
  sparse selections retain their existing offsets; source songs and copied data remain unchanged.
  Paste span retains exact offsets, exterior fragments and tied bar splitting. Unsafe overflow refuses atomically.

- Native ROLL adds Matrix / toggle entry: containing-beat pitch toggles across voices, caret-duration rest
  subdivision and atomic chord resizing/entry. Grid / drag remains available. Shared Undo, Pattern and
  standalone IT checks preserve the same song; unsafe peer-note loss is refused.
  Free Matrix entry stays on the containing beat and can grow a unique final bar. Successful entry previews
  the original beat's voices for 500ms; absent voices audition without editing, and unsafe overlaps refuse.

- Native stem controls and Ctrl+Up/Down apply to the caret voice's beam group, following TuxGuitar,
  including triplets and compound meter. Rests do nothing; playback and standalone IT stay unchanged.

- Delete, Cut and Rest edit the active voice across local and cross-bar selections; Cut still copies
  both voices, while Clean Beat clears both. Empty voices leave the other voice untouched.

- Native pitch/string shortcuts apply to the active voice across local and cross-bar selections. Semitone
  edits keep the original string and refuse the whole edit at a fret limit; range edits retain voice/caret.
  Select All spans the written track and checks measure-duration errors, following TuxGuitar.

- Score view adds compact beat spacing with TuxGuitar's duration/voice policy, saved as a local display
  preference. Full native glyphs keep collision spacing; multitrack view temporarily disables compact mode.

- Native range expressions now target the active voice, following TuxGuitar; untouched peer notes and ties
  remain intact. Ctrl+A/copy retain both voices, and empty voices no longer borrow expression controls.

- Native score view offers saved page/horizontal layout, zoom, staff/TAB, all tracks and chord visibility.
  Hit targets, range selection, caret and playback markers identify the part. One-bar expression ranges
  now use the same atomic command as longer phrases; display preferences never alter song history.

- Native percussion supports drum rolls and grace-note flams with independent mapped drum samples, shared
  Pattern/history/playback, drum notation, TG/GP interchange and MIDI. Existing unsupported pitch techniques
  and inexact standalone IT timing still refuse. Legacy TG no longer mistakes drum keys for guitar frets.

- Guitar Pro text encoding is selectable for GP1–5 imports and GP3–5 exports in the app, collections,
  CLI and agent tools. UTF-8, Cyrillic and Japanese text retain encoded byte limits and exact round-trip
  guards; GP6/7 keeps its XML encoding. GP1/2 credits now map to author, following TuxGuitar.

- Native MIDI export exposes transpose and Strip CC/PC in single/collection delivery, CLI and agent tools.
  TuxGuitar's grace/trill exceptions and stripped lead-in are preserved and reported; out-of-range keys
  refuse. Saved collection choices affect only exported files, leaving the shared document/history intact.

- GP5 export retains all six tapped harmonic intervals and data-0 pinch/semi harmonics, including ties and
  repeats. GP4 retains tapped/pinch/semi data0 and artificial data0/2/3. GP3 and nonrepresentable harmonic
  data keep their atomic refusals; native export preserves GP4 artificial data that TuxGuitar's writer collapses.

- GP6/7 native import retains double-dotted durations, including supported tuplets, and each measure's
  bass/alto/tenor/treble clef. These use the existing native rhythm/staff model and shared editing history.

- Native MIDI import exposes transpose, quantization, shortest-note and tuplet limits in the app, collections,
  CLI and agent. Saved collection settings also apply when opening MIDI files. Source volume/pan survives;
  later controller changes are explicitly reported as final whole-track values, following TuxGuitar.

- PowerTab and TablEdit imports retain source MIDI volume/pan through native editing, TG and MIDI export.
  TEF attenuation and pan follow TuxGuitar's exact conversion; native audio uses the existing tracker scale.
  Invalid controller values refuse before creating the destination song or samples.

- Notation delivery: single-file and collection LilyPond export expose part/range and layout settings,
  including saved collection choices. Print preview saves JPEG and lossless BMP alongside SVG/PNG.
  Invalid LilyPond selections and malformed image uploads refuse before publishing output.

- Mixer interchange: TG imports all source volume/pan values; TG and GP3–5 export uniform part mixes within
  each format's exact limits. Untouched TG/GP MIDI controllers survive round trips. Explicit mixer writes,
  including same-value writes, replace the corresponding source binding with exact shared Undo/Redo.
  Native/standalone IT audio retains the tracker mixer scale; unsupported effects and shared routes still refuse.

- Alternate tuning and part adaptation: automatic string-channel allocation, atomic tuning and track setup,
  and exact shared Undo/Redo. Reducing strings preserves raw Pattern channels; unsafe harmonic and
  string-dependent technique changes refuse atomically. First-track setup on legacy tracker songs works again.

- Repeat-aware rehearsal: follow repeats/endings, select individual visits, or play a passage once to its exact
  endpoint. Edits stop stale practice; ordinary playback reloads retain the repeat visit. Printed pages identify
  parts, source bars and continuing sections. Windows Edge PDF export avoids a detached compatibility relaunch
  and reports browser completion failures explicitly.

- Advanced rhythm and phrase rearrangement: Free duration handles explicit overfull bars and repair;
  partial paste crops representable bend/whammy curves; safe cross-bar let-ring paste preserves its gate.
  Dense exact rhythms export through finer IT rows without changing native timing or authored patterns.
  Shared Undo/Redo and raw-effect ownership remain guarded; unsupported cuts and timing refuse atomically.

- Expressive arrangement editing: Fit retains intact expression and authored velocity; safe let-ring/strum
  crossings and static-expression partial paste share exact Undo. Voice separation supports qualified
  Continue/Off envelopes and fadeout, preserving coincident key-offs in standalone IT. GP5 exports chord
  and pick/brush metadata and projects neutral spare-channel routing; Band package now includes GP5.
  TuxGuitar GP5.00 unset reverb imports correctly; conversion reports credit/encoding limitations.

- Part sounds and the score's Track selector now share one selected part. Changing either updates the
  score and sound controls immediately, without editing the song or adding Undo steps.

- Complex-score editing: full expressive notes retain their performance across rebar, Move, measure
  preparation and cross-bar paste. Explicit voice separation uses compatible spare part channels for
  strict IT export, with atomic refusal for stateful instruments and unsafe routing. Dense beat/chord
  labels reserve space in editor and print. GP3/4/5 retain supported grace notes; GP/TG fill export-only
  rests for sparse voices and pickups; TEF3 retains supported grace metadata and extended frets.
  Collection conversion applies remembered audio bit depth only to formats that support it, fixing
  notation and band exports after selecting 24-bit audio.

- Mixed tab library to band delivery: native PowerTab and TablEdit v2/v3 imports with explicit unsupported
  constructs; range techniques/curves/strokes; logical-part sound assignment and native SF2 preset import;
  batch PDF score/parts and audio/part stems with remembered settings, cancellation and per-format reports.
  Fixed an audition startup race by waiting for the worklet before publishing its command port.

- Native TAB now has compact controls, saved panel preferences, written-bar navigation and configurable
  score-action shortcuts. Explicit independent edits and measure preparation support reused passages and
  written bars inside larger patterns with one-step Undo. A local score collection browser and batch
  converter reuse the existing import/export paths, preserve sources and report per-file losses/errors.
  Native MIDI import fixes track-chunk parsing that rejected valid exported files.

- Native score authoring now starts from guitar/bass/drum/band or saved setup templates, with reusable tuning
  presets, independent track duplication and ordering. Mix/Push paste and Move/Copy voice extend arrangement
  editing with exact history and strict timing guards. Rehearsal adds selected-bar loops, count-in,
  meter-aware metronome, part solo/mute and stepped practice speed without rewriting the song.
  Song credits persist through supported interchange and printed parts; pages are numbered. SVG/PNG exports
  now preserve text fonts correctly instead of treating header text as music glyphs.

- Native TAB whole-song authoring now transfers phrases between tracks and songs with destination tuning
  and audio routing, maps copied measure parts, optionally copies headers/markers, makes passages unique
  and moves beats by an exact custom amount. Print preview exports selected tracks/bars to PDF and individual
  pages to self-contained SVG or PNG. GP3/4/5 import/export preserves the bass clef inferred from tuning.
  The local server accepts larger request bursts during score/audio refresh.

- Native TAB section composition now repeats and pastes phrases past the song end, splits crossing notes
  into ties, preserves the untouched parts of replacement destinations and selects the pasted phrase.
  Rest, Delete and Clean work across measures; Copy/Cut handle boundary ties. Measures can move complete
  passages, repair boundary ties on structural edits and rebar straddling notes. Move beats can extend the
  song. All use shared history and strict standalone IT checks, preserving other voices and tracker data.

- Native TAB everyday rhythm editing now keeps a complete phrase selected through Longer/Shorter, dots
  and tuplets, including regenerated rests. Selected bare rests can be absorbed without aborting the edit;
  ordinary lack of room keeps that beat's duration and reports it. Fit supports partial rests and implicit
  gaps while preserving the other voice. Copy, expression edits and exact Undo/Redo work through repeated
  edits, and selection shading survives refresh. Real conflicts still refuse the whole transaction.

- Native TAB duration edits now accept tied notes, preserving connected ties across bars and through qualified
  Fit movement. Links broken by an edit are removed with a visible report so following notes still play;
  one Undo restores the durations and ties. Single-note and range edits both check exact standalone IT timing
  before saving.

- Native TAB cross-measure duration editing now applies explicit lengths, dots, tuplets and Longer/Shorter to
  the selected voice through the existing Place/Fit path. It retains original selected identities, other voices
  and exact Undo, and repeated Apply is a no-op. Unsafe Fit and IT conflicts refuse atomically;
  generated rests join the resulting phrase selection for subsequent commands.

- Native TAB cross-measure selections now accept dynamics/custom velocity and explicit Set/Clear for ghost,
  accent, heavy accent, staccato, palm mute and dead notes. Mixed values are visible, the whole selection survives
  refresh, and each change shares one Undo without changing the clipboard. Existing technique exclusivity and
  strict IT timing/ownership checks apply atomically; unchanged settings create no history entry.

- Native TAB selected phrases now transpose across measures/patterns through semitone keys or the Transpose
  dialog, and shift to adjacent strings while preserving actual native playback and IT data. Qualified selection
  survives refresh, edits share one Undo, and unsafe strings/ties/harmonic intervals/shared patterns refuse.
  Whole-track and local edits keep their existing behavior; alternate fingering retains its audio-channel routing.

- Native TAB Cut/Ctrl+X and Repeat/Ctrl+R now handle cross-measure selections. Cut preserves note durations and
  existing rests; Repeat places the exact phrase after its end in existing compatible spans. Both use the shared
  clipboard/transaction, retain internal ties and exact Undo, and refuse unsafe boundaries without changing
  the previous clipboard. Local commands remain unchanged; cross-range rest-only Cut and song growth refuse.

- Native TAB has an explicit **Paste replace** action across existing measures/patterns. It replaces whole
  beats in copied track/voice lanes, including phrase gaps, with fresh IDs and one exact Undo. Partial beats,
  boundary ties, shared/approved destinations and unsafe tracker conflicts refuse atomically. Ctrl+V keeps
  safe Paste; other voices, raw cells, playback and standalone IT use the same shared document/compiler.

- TAB selection and Copy/Paste now span written measures and pattern/order boundaries. Repeated source visits
  keep distinct IDs; compatible empty destination spans retain voices, techniques and internal ties in one
  undoable edit. Reused/occupied destinations and unsupported boundary splits refuse without partial writes.
  Existing single-pattern shared pastes, tracker cells and native/IT timing remain intact.

- Authored tempo beat units and dots now appear in both score and print. Measures includes whole notes;
  imported units retain their exact written values. Stale units fall back to the effective quarter-note tempo
  with a warning and can be repaired by applying the same unit. Tracker, playback and IT timing are unchanged.

- Dense lyrics now reserve their measured text width in the shared score/print layout, preserving words,
  anchors, fonts and playback. A measure too wide for the view/page reports a width limitation instead of
  crowding its lyrics; widening the view restores navigation. Mixed voices retain their native lyric bands.

- Native-score IT export accepts lyrics and chord diagrams with explicit notation-loss warnings, preserving the
  original musical data and source annotations. Diagrams do not add notes and lyrics do not synthesize vocals.
- PROJECT can create a Windows song-opening shortcut with a native Save dialog, cancellation/overwrite
  confirmation and saved-path feedback. Packaged links target the installed exe; source runs use pythonw and
  the workspace. The shortcut does not copy the song or alter its history/mix.

- Native T/S/P and harmonic labels no longer collide in score or print previews. Dedicated effect bands and
  alphaTab's layout padding preserve the original glyphs, authored text and all playback/export data; combined
  and TAB-only print checks cover the supported scale extremes.

- Native-score IT export accepts tapping, slapping and popping as notation-only markings, matching the native
  playback path. Export warns that IT omits these markings while keeping source/history and sound unchanged.
  Marked/cleared IT bytes and native audio match; real control/export/Undo and independent renders cover the path.

- Fade-in now sounds in native live/rendered playback and exports. Native audio and MIDI share the TG track-wide
  expression schedule, preserving velocity, harmonic layers and released tails through existing gain controls.
  Standalone IT uses bounded volume-column projection with visible approximation warnings and atomic refusals
  for unsafe timing/state. Independent 44.1/48-kHz gain/tail checks and actual controls cover the path. Uniform
  fade glyphs no longer have duplicate overlapping text; authored cues and compact sparse-note labels remain.

- Native-score standalone IT export supports eighth/sixteenth triplet feels through the existing performed
  attack/release projection, preserving written timing, source phase, repeats and eligible voice/rest semantics.
  Exact IT ticks and safe cells/state are required; unsupported combinations refuse atomically. Independent
  44.1/48-kHz renders, real feel controls and a musical example cover the conversion. Integer tick rounding and
  short cut-ramp differences remain documented sound limitations; native playback is unchanged.

- Score and print previews no longer duplicate brush arrows and grace-note glyphs with overlapping generated
  text. Full parameters remain in controls/tooltips; mixed-timing grace keeps a compact label and authored beat
  text is retained. Song data, native playback and standalone IT are unchanged.

- Native-score standalone IT export supports brush/strum strokes on the exact IT tick grid, using native
  performed attacks/gates and shared voice cohorts. Both directions, tied strings, short gates, repeats and safe
  combinations retain their native timing. Off-grid rates, occupied cells, overlaps and unsafe mappings refuse
  atomically. Independent keyed renders, actual stroke controls and musical transport captures cover the path;
  tick rounding and short transition differences remain documented sound limitations.

- Native-score standalone IT export supports before/on-beat grace notes through the native performed events,
  including independent dynamics, delayed main notes and preceding-pattern gaps. Exact-grid 16th/32nd and
  representable dead gates are supported; overlaps, off-grid gates and unsafe cells/mapping refuse before writing.
  Transition labels remain notation only. Independent renders, actual page controls and full musical transport
  captures cover the conversion; IT tick rounding and short cut-ramp differences remain documented limitations.

- Native-score standalone IT export supports the native natural/artificial/tapped/pinch/semi harmonic layers
  through fixed appended channels. Layer pitches, velocities, keymaps, releases and parent mix/mutes are retained;
  unused layer tails retire on the next parent attack. Unsafe state inheritance, channel capacity, collisions and
  missing final release space refuse atomically. Independent renders and real-control checks cover the bounded
  conversion; IT volume/tick rounding and short transition differences remain audible-data limitations.

- Native-score standalone IT export writes trill/tremolo-picking pulses from the native performance plan as
  editable notes, preserving alternate keymaps, dynamics, ties and repeat traversal. Attacks require exact IT ticks
  and an available cell. Only the final TG pulse's one-legacy-tick-short key-off can extend by 1/960 quarter, with
  an export warning; other unsupported timing/ownership refuses atomically. Independent renders, real controls
  and a musical four-bars example cover the supported subset, including IT tick-rounding differences.

- Native-score standalone IT export supports bounded tremolo-bar/whammy dives, rises and mixed curves through
  the existing pitch-control projection. Native units, string scope, keymaps and envelopes remain intact;
  steep curves, oversized resets and unsafe ownership/effect collisions refuse before output replacement.
  Independent 44.1/48-kHz renders, real-control export and a musical four-bars example cover the supported subset.

- Native-score standalone IT export supports bounded bends, vibrato and shift slides through the existing native
  control plan and IT fine linear portamento. Row-aligned controls retain their times; off-row controls warn in CLI
  and RENDER & EXPORT, with preserved turning points and a checked 37.5-cent discrete-trajectory ceiling. Unsafe
  resets, effect/voice conflicts and missing slide targets refuse before replacing output. Samples/keymaps remain
  editable; independent 44.1/48-kHz renders and the real controls exercise the supported subset.

- Native-score IT export supports ghost/accent/heavy accent, hammer-derived velocity, and exactly representable
  staccato/palm-mute/dead/let-ring releases through the existing native performance plan. Between-row key-offs use
  IT note delay; incompatible timing, cells, channel overlaps or inherited state refuse without replacing output.

- Native-score IT export now supports percussion through the shared tracker conversion: drum keys, instrument
  keymaps/sample pitches, simultaneous voices, velocity, releases and repeats remain editable in the module.
  Missing drum sample mappings and channel collisions refuse before an existing output can be replaced.

- Native TAB / SCORE editing is in development. Fret, chord, rest and written-duration edits share the song,
  Pattern/ROLL, instruments, transport and persistent undo/redo. Staff/tab rendering uses bundled alphaTab assets;
  playback uses VultureTracker's existing engine. Score identities survive supported arrangement and phrase edits.
  The engraved TAB is the default editing surface, with string selection, fret entry and a separate editing cursor.
  Detailed properties and the alternate string grid are collapsible.
  An optional fretboard shares the score selection and edit history, with note toggling, separate audition,
  275 reference scales, orientation and appearance settings. Concert-pitch labels include capo.
  An optional native piano shares exact score selection, duration controls and undo, with both-voice
  note toggles, capo-aware string allocation and percussion keys. Stale queued entry is cancelled.
  Piano placement and native duration changes can split or consume bare rests in one undo step,
  preserving the exact caret, clipboard and later notes. Annotated rests and sounding overlaps refuse.
  Direct fret typing and fretboard insertion use the same rest placement; serial digit entry cancels
  stale targets while retaining successful earlier digits and their undo history.
  Optional Fit within measure applies supported note/rest rearrangements and reports the actual duration;
  it can reuse a destination that only the other voice occupies and keeps that voice unchanged.
  Apply duration, + and − change every selected beat of the current voice as one undo step.
  Remove unused voice clears a rest-only voice from the selected measures, and Clean beat turns the selected
  beats into plain rests, as in TuxGuitar. The TAB takes more of TuxGuitar's default keys: * / X O H P S V F,
  Ctrl+Delete, Ctrl+1/2, Ctrl+A and Alt+arrows for markers. Setup tuning changes retune the notes (tuning written as
  note names with presets; a capo applies at once, keeps frets and raises the sound, shown as "Capo N"), a
  Transpose dialog follows TuxGuitar's, and Ins inserts a rest as TuxGuitar does. Dragging across the engraved TAB selects a beat
  range, shown shaded, for the range commands; Select buttons extend or clear it as TuxGuitar's Edit > Selection.
  The Measures panel carries TuxGuitar's Measure menu: add, remove, clean, copy and paste (replace or insert) measure
  ranges, one undo step each, on songs with one measure per order (as imported tabs are). A new meter length
  re-bars the music as TuxGuitar's time signature does (notes keep their times, bars added at the end as needed); tempos can be written in other beat units (also in .tg files);
  alternate endings are checkboxes; the header line counts TuxGuitar's measure errors. A live reload superseded by a
  newer edit no longer flashes "compile failed". A native score now exports to a standalone, editable IT (RENDER &
  EXPORT and `build`): notes as tracker cells, authored velocities as volume-column values. Repeats and alternate
  endings now expand into ordinary IT patterns/orders using native playback's traversal, retaining performed ties,
  raw tracker cells and repeat-entry tempo resets without changing the written song. Unsupported conversion or
  excessive expansion refuses before writing.
  ROLL's Native track scope edits each source note of a track, across its channels and both voices, with
  separate lanes for notes that overlap. Ghosts stay read-only, and a drag is cancelled when its context changes.
  Its GRID draws meter-aware guide lines (1–16 per beat), and percussion rows show drum key names.
  A blank click there enters a note at the grid line through the TAB's own note entry, with one Undo step.
  Unchanged duration commands preserve the file, undo history and redo branch.
  Native playback and audio exports preserve fractional timing between tracker rows, including section exports
  and aligned stems. Default native SONG renders discard empty padding after the written ending while keeping
  note decay and written rests; explicitly requested export tails retain their lengths.
  GP5.00 notation export is available through RENDER & EXPORT, CLI and agent tools for a checked subset of
  authored scores. Unsupported content is refused before publication; sample sounds are not embedded.
  The same paths also export GP3.00 and GP4.00, TuxGuitar 2.0 or legacy 1.x files, and TuxGuitar's ASCII tab,
  LilyPond and MusicXML text. Losses are listed in the export's warnings. Guitar Pro 1 and 2 `.gtp`, GP6 `.gpx` and GP7 `.gp` tabs import.
  GP5 exports retain ghost/accent/heavy-accent, staccato, dead, palm-mute and let-ring markings per note,
  including independent chord notes and voices; conflicting combinations refuse without writing a file.
  Supported GP5 pitched effects include natural/artificial data-0 harmonics and representable trill/
  tremolo-picking rates, with explicit warnings for the artificial-harmonic payload convention.
  GP5 bend curves and shift slides preserve written metadata; destructive combinations refuse.
  GP5 vibrato and hammer-on/pull-off flags retain note ownership and tied metadata.
  GP5 whammy-bar curves export with uniform per-voice ownership; conflicting note-local curves refuse.
  GP5 fade-in and tap/slap/pop export as beat flags when every note of the beat agrees; mixed beats refuse.
  Absolute tempo changes share one clock across TAB, Pattern, seek, playback and exports;
  TAB measure tempo edits use the existing Pattern commands and history. Harmonics retain their separate sounding
  layers, with supported native TG/GP interchange and independent MIDI pitch controls. Trill and tremolo-picking
  edits preserve written notes while scheduling their repeated attacks through the same playback and export paths.
  Grace notes retain their own timing and velocity; supported let-ring, harmonic, repetition and grace overlaps
  keep independent note heads on one tracker channel. These share editor/print, history, TG/GP import and
  native/MIDI playback paths.
  Measure swing keeps written positions while changing performed timing. Native repeats and alternate endings
  preserve source bars and map playback passes back to TAB/Pattern, tempo, sections, exports and listening notes.
  Row-aligned measure boundaries can split or span patterns without changing authored orders. Stroke and
  pick-stroke controls share beat metadata across voices while retaining written Pattern positions.
  Different written voices can overlap on one supported tracker channel, retaining separate source notes and gates.
  Ambiguous Pattern cells require selecting a source note or an explicit range covering all voices.
  Fade-in markings retain per-note ownership. Native live/audio and MIDI export apply the same ordered track-wide
  expression schedule; standalone IT supports bounded volume-column projection with explicit approximation warnings.
  Chord diagrams retain shared-beat annotations independently of played notes, with native editing and print.
  A separate diagram-to-notes action replaces the selected voice through shared Pattern/history state.
  Native imports retain exact source MIDI pan without changing the audio mixer's scale or overriding later pan edits.
  Tap, slap and pop retain per-note markings, including mixed chords and tied continuations, without changing audio.
  Chord diagrams have a persistent custom-shape library, name recognition and four voicing-generation profiles.
  Suggestions change only the dialog draft until explicitly applied; library changes persist separately from songs.
  Track lyrics preserve raw text and starting measure through native song saves, agent edits and shared history.
  Written placement uses authored measures without changing playback. Native TG retains lyrics; GP4/5 accepts
  the first lyric line and refuses additional nonempty lines. MIDI export reports omitted lyrics explicitly.
  The editor engraves the entire written arrangement in wrapped systems, with cross-bar note selection and
  a shared playback highlight. Following playback scrolls through the score without replacing its bars.
  Percussion tracks retain authored drum keys and lanes through Pattern edits, native playback and MIDI export.
  Drum entry and print use percussion notation, with keys 1–100, qualified dynamics/gate techniques and let-ring.
  TG interchange preserves these markings; GP3–5 accepts drum keys 1–99 with version-specific technique
  support and explicit refusal of unrepresentable or conflicting flags.
  MIDI uses channel 10 and refuses conflicting controls or overlapping gates on the same drum key.
  Short Pattern windows keep a usable piano-roll viewport.
  Unsupported timing or structural edits fail before saving. Full TuxGuitar parity is still in progress; see
  `TABLATURE-PARITY.md` and the current implementation status in `BACKLOG.md`.

## 1.8.0 (2026-10-18)

- Pattern tab: ACCENT sets a repeating list of volumes (vNN, or a percent of the note's own) on the selected channels'
  notes, in the pattern or the whole song. EUCLID layers more cycles (`+ 2/5 3/7`: a row plays where any cycle hits,
  quieter where fewer do), restarts them every PHRASE rows, changes each phrase by RULES (`-`, `rev`, `inv`, `rotN`,
  `+N`), and walks the WHOLE SONG with the phrase count running on. Both are agent tools too. A selection tool's refusal
  (nothing to change) shows whole in the selection bar.
- Tryout: MATCH LEVEL (off by default) plays every candidate at the current sample's integrated loudness, in the mix and
  alone, the gain shown on each candidate. Playback only: the song, the faders and what U writes are unchanged.
- Recipes: a `drum:` sample takes `general: {seed: N}` for another take of the same hit, and `takes: 4` (or `takes:
  {count, tuning, stretch, level}`) renders `name_t1.wav` … `name_tN.wav`, each later take moved at random within the
  spreads, the same on every render, for LAYERS CYCLE round-robin.
- `check` warns when a sample played at one note only (a drum, a one-shot) has a steady partial between 50 Hz and 5 kHz
  more than 30 cents from every tone of the song's key, with its Hz, nearest note, cents and level (SONG_FORMAT.md §9).
- Claude Code in this repository: `.mcp.json` registers the app's MCP server, hooks guard against `git add -A` and run
  `tests.test_docs` after an edit to a file it checks, and the `/release` and `run-app` skills and the `openmpt-parity`
  reviewer come with the checkout.
- Keys follow OpenMPT's defaults (`DefaultKeyBindings.h`; the owner's call, 2026-10-18). Transport, in every tab: F5
  play/pause, F6 the song from its start (Ctrl+F6 from the cursor), F7 the pattern looped from its first row (Ctrl+F7
  from the cursor), F8 pause, Esc stop. Pattern tab: Ctrl+Space edit mode (was Esc), Enter / Space cursor copy and paste
  (Space played from the cursor), Ctrl+5 select the pattern (was Ctrl+A), Ctrl+Q / Ctrl+A transpose (were Ctrl+Up /
  Down), Ctrl+Up / Down the previous / next INS instrument, Ctrl+I set the INS instrument on the selection (Ctrl+I
  interpolated), Ctrl+J / Ctrl+K interpolate the volume / effect column, Shift+V paste flood outside the note column,
  Ctrl+Alt+V push-forward paste (it flooded).
- SELECTION bar: PUSH (OpenMPT's Push Forward Paste) and OVERFLOW (OpenMPT's Overflow Paste: a paste past the pattern's
  end goes on in the next order's pattern).
- MIDI note entry with VEL→VOL uses OpenMPT's velocity curve (squared): velocity 64 enters v17, not v32.
- The .it carries the channel and pattern names (OpenMPT's `CNAM` and `PNAM` chunks), so OpenMPT and libopenmpt show
  them; the demos' compiled bytes change by those chunks only (the corpus hashes in `tests/test_release100.py`).
- The Pattern tab tells a screen reader the cursor's cell in OpenMPT's accessibility format ("Row 4, Channel 2,
  Volume: …"); the tab bar has tab roles, the icon-only buttons in the live bar names.

## 1.7.0 (2026-10-14)

The October 2026 external audit's findings, fixed (code-signing the exe stays open):

- The app's server needs a token each launch makes: the window's address carries it, the page sends it with every
  request, `running.json` in the user folder holds it for the MCP bridge. Requests without it get 401, so a web page's
  `<img>` or `<audio>` (which sends no Origin) and other accounts on the PC get nothing. `Origin: null` is refused.
- Agent tools reach files only inside the song's folder and the sample library's folders; `export_song` writes only
  inside the song's folder and replaces earlier exports only after ALLOW REPLACE in the AGENT panel. Text read from a
  song is data to the model, never instructions. A tryout glob that matches nothing adds nothing.
- The AGENT panel says once per provider what it sends and where the key is (OS credential store, a plaintext file, or
  an environment variable it names); `agent.json` is readable by its owner only on Linux and macOS. The chat's Claude
  Code loads no settings files (`--setting-sources ""`). The custom-server preset no longer points at Ollama's port.
- No GET request writes anything (the RECORD tab's poll is a POST); request bodies are capped at 8 MiB (uploads 512
  MiB); the render cache is pruned to 2 GiB as well as by count; every ffmpeg run passes `-nostdin` and stops after 300 s.
- Builds and CI install pinned, hashed packages (`requirements-test.txt`, `requirements-build.txt`; `build_exe.py`
  refuses an environment that differs); THIRD_PARTY.md lists the SHA-256 and source of every vendored libopenmpt file,
  checked by `tests/test_vendor.py`. `tools/fuzz_import.py` also fuzzes SoundFont banks and GUS patches.
- `gui.py` split: the HTTP side in `server.py`, measurements in `measure.py`, the Samples and PAINT helpers in
  `sample_edit.py`. With it, adding candidates saves under the song's lock, `recent.json` is written atomically, and
  each song has one measuring thread with its own small lock.
- README: working with an AI agent, what the app writes beside a song (with a `.gitignore`), the local server, checking
  the exe's SHA-256. pyproject: license, readme, authors, URLs, and `agent` and `build` extras.

## 1.6.0 (2026-10-14)

- Recipes: `fx:` parameters that take a name reach pedalboard's enums (`resample: {quality: ZeroOrderHold}`, the
  aliasing lo-fi; `ladder_filter: {mode: HPF24}`); SAMPLING.md lists all 24 effects `fx:` accepts.
- Undo history: every step carries the name of the operation it undoes and its time ("edit pattern 3: 4 cells",
  "song: orders", "WRITE MIX", "agent: write_cells", "command: checkpoint restore"), as OpenMPT names its undo steps;
  PROJECT lists the nearest twelve of each stack and `inspect_history` returns them. Schema stays 2; older steps show
  none.
- Tests: `tests/test_docs.py` checks that SONG_FORMAT's effect and volume tables match what the compiler accepts, that
  every command is in README or GUIDE, that every agent tool is named in GUIDE's agent section, and that CI and
  AGENTS.md run every test module. GUIDE now names the nine tools and two commands it had left out.
- CI: a newer push cancels the run still going for the same branch, and pip downloads are cached.
- Pattern tab: QUANT in the live bar is OpenMPT's record quantize: a note or chord recorded while the song plays goes to
  the nearest multiple of QUANT rows (past the pattern's end into the next order's pattern, a note already there pushes
  it a row on, as OpenMPT does). Kept between launches; 0 is off.
- Piano roll: GHOST FROM draws the previous or next order's pattern, or any pattern by name, under the one shown in a
  third shade, clipped at the shorter pattern and never editable.
- GitHub: a bug report form (version, steps, the app's log, the song if shareable) and a "Reporting a problem"
  section in README.
- `check` warns when a note plays a sample so far above its root that its content (the top of its spectrum, within
  60 dB of its loudest band) passes `module: ceiling` (18 kHz by default), the upward half of the anti-aliasing rule.
  It finds two such notes in demo2 (Iron Relay) and one in demo3 (Undertow); the demos are unchanged.
- Recipes: `fx:` runs its items in list order and mixes pedalboard's effects with eight of VultureTracker's own
  (numpy): `bandlimit` (below), `multitap` (tempo-synced echoes, each tap with its gain, low-pass and pan, or
  ping-pong), `waveshape` (a curve or tanh, sine, foldback, rectify, half_rectify, soft), `slew`, `shift`
  (frequency shifter and ring modulator), `stereo` (matrix, width, Haas delay, swap), `dispersion` (all-pass smear) and `granular`. `fx_tail`
  grows to fit their tails; a bad parameter is reported before any rendering.
- Samples tab: GRANULAR in EFFECTS (grain, density, pitch, jitter, spray), also the agent's `process_sample`.
- Tests: a `../samples/x.wav` path through Collect Samples, a hard-driven render's frames, the reader's NaN refusal.
- Recipes: `bandlimit: {hz}` in `fx:`, the compiler's own steep sinc low-pass, so a sample measures as wide as asked.
- Import: the Guitar Pro and MIDI placeholder plucks are band-limited at 9 kHz by that sinc (a 24 dB per octave
  low-pass before), so their keymaps meet the ceiling check they were laid out for.
- AUTOMATE on the Pattern tab's SELECTION bar: a curve (linear, S-curve, exponential or steps) from FROM to TO written
  as plain `Zxx`, `Xxx`, `Mxx`, `Vxx`, `Txx` or `vNN` cells every n rows, one undo step. INTERPOLATE is now OpenMPT's:
  the note and instrument columns too, one empty end filled from the other, rows holding another command left alone,
  OpenMPT's rounding, and with no selection the span around the cursor.
- REC OFF in the live bar: with it on, letting go of a piano key or a MIDI key in edit mode writes a note-off on the
  channel its note went to, at the row playing (or the cursor), as OpenMPT's Record Note Off does; a chord's notes each
  end on their own channel.
- GROW and SHRINK on the SELECTION bar (Alt+E, Alt+D): OpenMPT's Grow and Shrink Selection, the rows spread two apart
  or packed into half the span, the overflow dropped and counted.
- ARP and STRUM in COMPOSE: ARP plays each note the owner wrote on a channel as the root of an arpeggio (the CHORD
  shape over 1-4 octaves; up, down, up-down, down-up or random; a step every n rows; seeded skips; a gate as `SCx` or a
  note-off row), STRUM delays a chord's voices one after another by n ticks (`SDx`).
- LENGTH on the SELECTION bar: FILL (legato), SET n rows, CUT HERE and GLUE; in the roll, a note's right edge drags its
  length and its body drags it in rows. An approved pattern refuses them.
- SPLIT HERE in the Pattern tab: OpenMPT's Split Pattern, the rows from the cursor on a new pattern played after every
  order of the source; sections widen to take it in and `Bxx` jumps follow.
- SONG SETTINGS: a MESSAGE box for the IT song message, written to `module: message` as a literal block exactly as
  typed, with the Latin-1 and length warnings `check` gives.
- Channels: an optional `color: "#rrggbb"` (set from the SONG tab's channel list) colours the channel in the rail, the
  Pattern tab's header and the roll's ghosts; the .it does not hold it.
- Recipes: `wave:`, a looped chip or drawn cycle (pulse, saw, square, triangle, the NES triangle and noise, a Game Boy
  table, any table) summed from its harmonics under a ceiling, in tune to 0.1 cent; and `mip:` on any source, copies
  band-limited per octave and stored at matching rates, with the song's `samples:`/`keymap:` printed to paste.
- Recipes: `sfxr:`, Tomas Pettersson's sfxr (MIT) reimplemented: its parameters by name and its seven generators as
  `preset` + `seed`, reproducible, rendered at its eight sub-steps per frame and resampled instead of averaged.
- Recipes: `drum:`, Paul Kellett's DrumSynth 2.0 (MIT) reimplemented from his renderer and help file: tone with sweep
  and droop, noise, two overtones (mixed, FM, ring, 808 cymbal), two noise bands, distortion and a resonant
  filter as YAML sections, or a user's own `.ds` file.
- Recipes: `additive:`, Nasca Octavian Paul's PADsynth (public domain): each harmonic a Gaussian band, random phases from
  a seed, one inverse FFT, so the pad loops exactly over its whole length.
- Recipes: seven Faust examples shipped with the app and usable as `faust: NAME.dsp`: a Karplus-Strong pluck with a pick
  position, a nylon guitar, a marimba, a drawbar organ, a two-operator OPL2-style FM voice with its four waves, an
  acid bass through a diode ladder, and a kick with start, end, slope, envelope and drive.
- Instruments: `lfo:` in place of an envelope's nodes (sine, triangle, square, saw, ramp or random; period, depth,
  centre, delay, attack), written as envelope nodes and a loop when the song compiles, so the module is plain IT;
  the Instruments tab shows it as a line. Envelope loops play their end tick too (Impulse Tracker's rule), and the
  lfo's loop is placed for it.
- Instruments: `filter_mode: highpass` (or `lowpass`), OpenMPT's instrument extension written after the sample data as
  OpenMPT writes it (`XTPM`, `FM..`), played by libopenmpt as a high-pass, and read back on import.
- Import: `import bank.sf2 --preset N [--bank B]` and the Instruments tab's SoundFont row make a SoundFont preset (or a
  GUS `.pat`) one instrument, its zones WAVs, read the way OpenMPT's loader reads a bank (key ranges, tuning, loops,
  envelope, stereo pairs); velocity layers keep the loudest, a drum kit is one instrument.
- Recipes: `file:` reads a Hydrogen drum kit (`.h2drumkit`) as Hydrogen does, `instrument:` and `layer:` choosing a
  sound (the loudest layer by default), `layers: [..]` one sample per velocity layer to try out; its gains applied,
  its pan and licence in the log.
- Export: MIDI (`export -f mid` and RENDER & EXPORT): the notes as a type 1 MIDI file the way OpenMPT exports one, a
  track per instrument, rows timed as libopenmpt plays them, tempo changes, the effects a MIDI file cannot hold counted.
- Export: sample rate (22050-96000 Hz), depth (24-bit WAV and FLAC, float WAV), MP3 bitrate, OGG quality and
  repeated passes of the whole song, in RENDER & EXPORT and as `export --rate --depth --bitrate --quality --repeat`;
  the defaults are unchanged.
- Export: NORMALISE TO N LUFS under a true-peak ceiling (-1 dBTP by default), off unless chosen: one gain on the song and
  its stems, no limiter, the .it untouched (`export --normalize --ceiling`).
- Samples tab SLICE: ORIGINAL BPM (a guess from the length, editable), SNAP to a 1/4-1/32 grid at it, and + PATTERN ON
  GRID, the slices placed on the song's rows by beat so a loop at another tempo follows the song.
- PROJECT: each missing sample offers same-named WAVs from the sample library's index, one click each, the one whose
  contents match the digest the undo history recorded marked SAME FILE.
- RECORD: finished passes not yet saved are kept in the user folder's `recordings/` until saved or discarded; the next
  session lists them as UNSAVED TAKES to recover or discard, and drops them after 7 days.
- Meters over time: per order the highest short-term loudness (3 s) and the stereo correlation, as a strip under the
  SPECTRUM tab and in the agent's `measure` (`per_order`), and the loudness range (LRA) beside OUT and in `measure`.
- Songs the app creates or imports carry `# written by VultureTracker X.Y.Z`, refreshed by an app write only when the
  version changes (never added to a song without it); `check --json` reports it as `written_by`.
- Releases: a `v*` tag (or a run by hand) builds the Windows exe on a clean runner with `tools/build_exe.py`, checks
  it with `tools/exe_check.py` and keeps the exe, ffmpeg and the zip as the run's artifact; the published exe is still
  the local build (AGENTS.md). `release.py --check` has a test that plants a wrong digest.
- MAP tab: Up and Down in the filter box step through the matching sounds, each selected and played (the view
  follows it); with no filter they step through all of them.
- Patterns: `automation:` lanes, a curve the compiler writes into a pattern's cells on every compile (target, channel,
  rows, from, to, shape, every: the SELECTION bar's AUTOMATE kept in the song); a lane owns its column there, the Pattern
  tab draws its cells dimmed and refuses edits of that column, and MAKE EDITABLE turns lanes into plain cells.
- Instruments: microtuning, `tuning: scale.scl` and `keymap_file: map.kbm` (Scala's formats) for scales that repeat at
  the octave over 12 keys; the .it plays each retuned key through a copy of its sample at that pitch, sharing the
  sample's data.
- Agents: the tools reach what phases 3-6 added to the app: `transform_patterns` runs the SELECTION bar's INTERPOLATE,
  AUTOMATE, GROW, SHRINK, ARP, FILL, SET LENGTH, CUT HERE and GLUE and chord STRUM through the page's own code;
  `edit_pattern` splits a pattern and sets its automation lanes; `edit_channel` colours, `set_module` writes the message;
  `edit_instrument` takes `lfo` envelopes, `filter_mode`, `tuning` and `keymap_file`; the recipe tools list and render
  the numpy sources, the shipped Faust examples and `mip` copies; new `import_soundfont` and `relink_hints`;
  `export_song` exports MIDI with the render settings; slices snap to a grid and can write a pattern on it;
  `control_recording` recovers or forgets unsaved passes.

## 1.5.2 (2026-10-10)

- Agent chat loads tool definitions on demand through a small tool directory, reducing the upfront catalog from
  roughly 47,000 to 2,400 characters while keeping every song operation available.
- Large tool results are paged; older API tool output becomes retrievable references. Existing undo, approval and
  stop protections still apply, and retrieving a result never repeats an edit.
- COMPACT keeps its continuation summary private and shows only a short confirmation in the chat.
- App-launched Claude Code sessions exclude personal/project coding instructions, auto memory, hooks and skills,
  preventing unrelated wiki-maintenance reminders. Normal Claude Code settings are unchanged; managed policy applies.

## 1.5.1 (2026-10-10)

- Release validation now checks the expected missing-dependency result for file-recipe synthesis when optional
  `pedalboard` is absent. Includes all 1.5.0 agent integration and Rack fixes below; application behavior is unchanged.

## 1.5.0 (2026-10-10)

- Claude Code chat now passes the selected effort level to the CLI, including Low, instead of silently using its default.

- Agent tools now cover recording inputs/takes, listening-note add/update/delete with revision checks, live/rendered
  pause/resume, and detailed read-only undo/redo inspection. Failed recording saves retain unsaved passes for retry;
  reopening inputs or switching projects cannot silently discard them. Recording tests use simulated input.

- **Agent phrase comparisons and projects:** capture, inspect, edit, render and diff frozen alternatives; final
  ratings and acceptance stay in PHRASES. Create/import/open projects, inspect missing samples, collect portable
  copies/ZIPs and relink sample paths. Follow-up chat tools and the player now follow an agent-requested project
  switch. Collection rejects modified frozen phrase samples; headless phrase renders create their cache folder.

- **Background synth rendering:** Recipe and agent plugin renders now run in a separate process so VST resets can
  execute on the plugin's main thread. This fixes Surge renders failing in the packaged app.

- **Agent library and synthesis:** index configured WAV folders, search filenames and measured timbre, discover
  installed patches/parameters, inspect recipes and save new recipe versions. Render patches, file recipes, Faust,
  resynthesis and spectral Paint/filtering into new assets with job IDs, status and cancellation. Original sources
  remain intact; audition candidates and song-slot creation are explicit follow-up operations. Missing dependencies
  are reported without automatic downloads.

- **Agent arrangement and pattern tools:** create/update/rename/delete/move/duplicate named sections; rename, resize,
  delete and materialize patterns; transpose, clear, find/replace, groove, Euclidean rhythm, chords and layers;
  copy/move regions and write multiple patterns atomically. Edits support undo and approval guards; shrinking populated
  patterns and overwriting occupied copy/chord destinations require explicit options. Materializing preserves marks.

- **Agent sample editing:** edit instrument mappings/envelopes/behavior and sample tuning/loops/format, inspect sample
  usage and loop/slice suggestions, delete unused slots, process audio, slice kits/multisamples, and render rows into a
  new sample. Uses the existing editor and DSP, preserves original WAVs, supports undo/redo, and protects approved
  voices and owner mixer settings. Deletion checks unused patterns and mapping references without renumbering slots.

- **More agent song tools:** import new sample slots, create instruments (with atomic sample-mode conversion), rename,
  move and remove channels while preserving their settings, and export IT/audio/stems with status and cancellation.
  Existing slots and source assets cannot be overwritten; approved material and owner levels stay guarded.
  Removing the last focused channel also clears the Pattern tab's stale focus and selection.
- **Agent song controls:** create empty channels; inspect complete Rack settings and the window's reported playback
  state; solo, mute, loop and stop; edit one effect without replacing the Rack; and list/save/diff/restore/delete
  PROJECT checkpoints, with guarded redo. Playback requests are acknowledged by the window, and stopping cancels
  pending live starts/render resumes. Approved material and owner-controlled levels remain protected.
- **Rack bypass and removal:** Distortion, Compressor and Parametric EQ no longer block rack edits because their
  gain in dB was also validated as an output multiplier. `output_gain` sets that multiplier separately.
- **Agent controls:** context size and provider token counts, STOP for an active turn, and COMPACT to continue from a
  summary while retaining the visible transcript. Late replies and stopped Claude Code tool calls cannot start edits;
  completed edits remain undoable. Draft messages stay while the agent works.
- **Imported-song rack routing:** valid channel lists with unindented sequence dashes now support channel edits and
  plugin routing, fixing the agent's "no channel 9" failure when assigning a flanger.

## 1.4.1 (2026-10-10)

- **Import Browse:** the native file picker accepts the module, tab and MIDI filter again.
- **Agent checks:** a successful check with warnings is no longer shown or sent to the model as a tool error.
  Actual compiler errors still report failure.

## 1.4.0 (2026-10-10)

- **Playback bar layout:** status, ALL OFF and speed controls stay inside the panel. The status row spans the full
  available width, and the panel grows when it needs to wrap, including with the Agent panel open or a larger UI scale.

- **More chat providers:** Gemini with free-tier setup guidance, plus Ollama and LM Studio presets with local model
  discovery. Existing Claude Code, Anthropic and custom OpenAI-compatible connections remain. Provider switches no
  longer carry a file-backed API key into another provider; quota failures explain the limit without a paid fallback.
  Chat settings keep unsaved input during refresh, and changing the model or server starts a fresh conversation.
- **Chat formatting:** bold and italic text can contain inline code without leaving raw Markdown markers; underscore
  bold and combined bold/italic render too. Code stays literal and model-authored HTML stays escaped.

Hardening after the 2026-10-08 audit of the repository: nothing changes for songs or modules.

- **Downloads are verified**: Surge XT, Dexed, faustwasm, OB-Xd's installer and the MusicRadar pack are checked
  against a SHA-256 pinned beside each URL before anything is unpacked or run; a mismatch deletes the file and says
  which asset from which URL did not match.
- **The chat panel's API key** goes to the OS credential store (Windows Credential Manager, the macOS Keychain, a Linux
  secret service) when the `keyring` package is installed, under the provider's name; a key already in `agent.json`
  moves there on the next read. Without keyring it stays in the file as before. The panel says which, and warns when
  the server URL is remote and not https: the key would travel in clear.
- **Malformed modules, MIDI files and Guitar Pro tabs** are refused with one error instead of taking minutes or
  gigabytes (a header claiming 65535 instruments or patterns, a chunk size of 4 GB, a tempo of zero); an XM or S3M
  the reader accepts but libopenmpt refuses imports with its level unmatched and a warning. `tools/fuzz_import.py`
  found them and reruns after a reader changes.
- **A song nested more than 100 levels deep is refused with an error** instead of killing the process: with PyYAML's
  libyaml loader on Windows under Python 3.10-3.13 (a source install; the exe's 3.14 was safe), such a file overflowed
  the C stack. Recipes and every other YAML the app reads get the same guard.
- **The app's write paths**: a negative pattern, candidate or channel index no longer picks from the end of the list, a
  muted or mixed channel past 63 no longer writes into the module header, a section, slot, Euclidean step count and
  request size are bounded.
- **CI** runs the portable tests on Windows (Python 3.14, the vendored libopenmpt 0.8.9) and on Linux with Python 3.10
  and 3.14; `pip install -e .` works again.
- **Releases**: `tools/release.py X.Y.Z` does the mechanical steps and prints the commands; `tools/exe_check.py`
  starts a built exe headless and runs its new `--selfcheck` (every packed module and data file).
- SECURITY.md, and README's privacy and download-check paragraphs.

## 1.3.2 (2026-10-08)

A tuner tab, and the agent chat shows markdown.

- **TUNER tab** (before RECORD): a chromatic tuner with a cents needle, on the RECORD tab's input. It now reaches a
  five-string bass's low B (30.9 Hz); the tuner read nothing under 40 Hz before. It left the RECORD tab.
- **The AGENT chat shows the agent's replies as markdown** instead of the raw `**` and `#` marks.

## 1.3.1 (2026-10-07)

One fix: the app on a Windows PC without Microsoft's WebView2 runtime.

- **A PC without WebView2**: the app opened in Internet Explorer's engine there (white boxes, no song screen). It now
  opens in the browser instead and says where to get WebView2; OK on that message quits the app.

## 1.3.0 (2026-10-07)

OpenMPT's DMO effects and an effect rack, agents that work on the open song (from Claude Code over MCP, or a chat
panel on your own Claude Code login, the API or a local model) without touching your levels or what you approved,
loudness numbers, a piano roll, and undo in the Paint tab.

- **Mix plugins and the RACK tab**: OpenMPT's nine built-in DMO effects (chorus, compressor, distortion, echo, flanger,
  gargle, I3DL2 reverb, parametric EQ, Waves reverb) in the song format (`module: plugins:`, a channel's `plugin:`,
  `module: macros:` for their Zxx automation), saved in the .it as OpenMPT saves them. The RACK tab shows each channel's
  chain as devices with knobs: add, bypass, reorder, remove, and AUTO gives a parameter an SFx macro for Zxx. Only
  OpenMPT and libopenmpt play them; other trackers play those channels dry. Importing an .it keeps OpenMPT's DMO
  plugins, its SFx macros and its channel names.
- **Agents**: one set of tools on the song open in the app (`vulturetracker/agent.py`: read the song, a pattern and the
  owner's selection, write cells, orders, patterns, settings and the rack, measure, cue and play a place, offer tryout
  candidates, read the listening notes, check the key, undo). No tool sets a level, and anything marked `approved` is
  refused; every edit is one undo step and marks the pattern `by: agent`. Reached from Claude Code or any MCP client
  (`python -m vulturetracker mcp`) or from the new AGENT panel, a chat with Claude Code on your own login (your
  subscription, no API key), the Anthropic API, or a local model behind an OpenAI-compatible server (optional; set up in
  its SETTINGS). ACTIVITY lists every call.
- **Undo in the Paint tab**: Ctrl+Z / Ctrl+Y (and ↶ ↷) for strokes, CLEAR, LOAD IMAGE and resizes.
- **Marks**: `approved: true` on a pattern, channel or sample (✓ in the SONG and SAMPLES tabs), `by:` on a pattern.
- **Loudness**: OUT under the player shows the playing render's integrated loudness (LUFS, BS.1770), true peak and
  stereo correlation; `python -m vulturetracker measure` does the same for a song, module or WAV.
- **The piano roll** (ROLL in the Pattern tab's live bar): the cursor's channel over the pattern's rows, the other
  channels as ghosts, a volume lane, and scale lock from the song's key.
- **Key, TAP, ALL OFF**: `module: key:` (shown in the SONG tab with the share of notes in it and an estimate), tap
  tempo in the SONG tab, and a button that stops every sound the app makes.

## 1.2.0 (2026-10-06)

The transcription tools follow a recording that gains half a bar, put every part in the Guitar Pro tab and check a run
in one tool, and the synth host hands a large patch to its plugin in a fraction of a second.

- **A 2/4 bar** (`tools/stems_to_song.py` and `tools/make_notes.py`, `--short-bar ROW`): for a recording that gains half
  a bar at a row, the bars after it start 8 rows later: the song has an 8-row pattern there, the MIDI changes its time
  signature and the tab has a 2/4 measure.
- **Every part in the tab** (`tools/make_notes.py`): the parts that are no guitar or bass (other, piano, vocals) are
  notation tracks: 7 strings tuned in equal steps across the part's range, any frets, the MIDI's sound.
- **`tools/transcription_checks.py`**: the checks a transcription run needs, in one tool: `downbeats` (beat_this's
  downbeats on the tools' grid: K and its share, the runs of one phase, crashes on bar lines, a swing or triplet feel),
  `score` (each transcriber's notes against their stem, the pick per stem and its make_notes.py arguments), `gp5` (the
  tab read back against the MIDI), `it` (the exported .it's DELTA against the song's) and `missing` (rows where a stem
  sounds with no note).
- Fixed: handing a large plugin state to the synth host (a Surge XT patch of about 1 MB) took minutes: its encoding
  grew with the square of the size. It is linear now (1 MB in 0.16 s).
- Fixed: `tools/yourmt3_transcribe.py` failed with a relative `--model-dir` (it changed into that folder before using
  the path).

**Upgrade note:** song files, history and checkpoints are unchanged from 1.1.0, and so are renders. The transcription
tools are not in the exe: they run from a source checkout in their own Python environments (`python
tools/transcribe_audio.py --setup`); `transcription_checks.py downbeats` also needs beat_this in the torch environment
(its error message gives the install line).

## 1.1.0 (2026-10-05)

A recording can sit under the song in the SPECTRUM tab, to compare the two cell by cell, and new tools outside the app
turn a recording into a song, a MIDI file and a Guitar Pro tab.

- **A reference in the SPECTRUM tab.** REFERENCE sets another recording (WAV, MP3, FLAC, OGG…) under what plays: REF
  shows its spectrogram over the same span, its level matched to the song's, and DELTA the song minus the reference in
  each cell (red: louder in the song), with the mean |Δ| per order and the span's median. OFFSET (ms) and ALIGN (the
  onsets of both cross-correlated) line it up; a section is compared with the part of the reference it covers.
- **Transcribing a recording** (`tools/transcribe_audio.py`, with `stems_to_midi.py`, `yourmt3_transcribe.py` and
  `transcription_diff.py`): stems by demucs or a RoFormer model, notes by basic-pitch and/or YourMT3+ (each makes its own
  song; the bass optionally by VultureTracker's YIN), drums by ADTOF, merged on the track's own beat grid into a MIDI
  file, imported and rendered, and scored against the recording. The tools run in their own Python environments
  (`--setup`, with `--cuda` for an NVIDIA card and `--yourmt3` for its model); `tools/transcribe_setup.cmd` and
  `transcribe.cmd` set up and run it all on a Windows PC with nothing installed. `tools/stems_to_song.py` then plays such a
  transcription on samples cut from the recording's own stems: drum hits sliced and grouped into types, notes on a sample
  per pitch, or a stem itself in sections, with a tempo channel that keeps the render on the recording's grid.
  `tools/tempo_check.py` says first whether a recording sits on a steady grid: its BPM, where row 0 falls, and how far
  each stretch of it is off the grid. `tools/make_notes.py` writes the transcribed notes as a MIDI file and a Guitar Pro 5
  tab on that grid, the bar lines on a given downbeat: guitar and bass on the standard tuning their lowest notes need,
  frets chosen so the hand moves least, and the drums. Nothing is added to the app or the exe.
- Fixed: under numpy 1.x on Windows the SPECTRUM view (and DELTA) went blank past about 40 s of a render: a 32-bit
  column index overflowed. The exe and numpy 2 were not affected.

**Upgrade note:** song files, history and checkpoints are unchanged from 1.0.0, and so are renders. The reference is
kept with the tryout settings beside the song. The transcription tools are not in the exe: they run from a source
checkout in their own Python environments (`python tools/transcribe_audio.py --setup`, 3 to 6 GB).

## 1.0.0 (2026-10-01)

A song, its history and its exports stay right from version to version, and the first things a new user reaches for
work: other sample formats, imports that keep more, a command line on a par with the app, Faust sounds that can be
made again, and a UI scale.

- **Songs stay readable across versions** (SONG_FORMAT.md, section 10). 1.x opens every song that 0.6 or later wrote,
  unchanged, and compiles it to the same module: the demos whose samples are in git are held to their exact `.it`
  bytes. A song can name the oldest app that reads it, `requires: "1.2"`; an older app then says only that, instead of
  listing the keys it does not know. The files beside the song carry a `schema` number, and one written by a newer
  VultureTracker opens the song read-only with a notice naming it, instead of being written over (a newer history was
  moved aside as corrupt). `<song>.notes.json` is now `{"schema": 1, "notes": [...]}`; the older list is read, and an
  app before this one reads the new file as empty. A listening note in a read-only window is refused, as edits are,
  instead of being written over the other window's notes.
- **The app says its version**: `vulturetracker --version`, the window title, the start screen and the listening-notes
  report. It is set in one place, `vulturetracker/__init__.py`, which a pip install reads too.
- **A log for bug reports.** The exe has no console, so what failed unexpectedly went nowhere. The app now writes it,
  with the traceback, to `vulturetracker.log` in its settings folder (`%APPDATA%\VultureTracker`; two files of 256 KB
  at most, each start naming the version, libopenmpt's and the system), and the error the page shows ends with the path.
- **Installing from source** goes through extras: `pip install -e ".[all]"` (or `gui`, `record`, `synth`, `gp`, `midi`,
  `test`); CI installs `.[test]`, so the package test runs there too.
- **Linux and macOS paths.** The settings, library index, window profile and log live where each system keeps an
  application's (`~/.config/VultureTracker` on Linux, `~/Library/Application Support/VultureTracker` on macOS; they were
  in `~/VultureTracker`, whose recent list is still read), the downloads in `~/.local/share/VultureTracker`, and
  installed Surge XT, Dexed and OB-Xd are found in the system's VST3 folders. GUIDE.md's Platforms says what stays
  Windows-only.
- **FLAC, AIFF, OGG and MP3 samples.** Wherever the app takes a WAV (a drop, a candidate path or glob, a new slot, a
  slot's file) it now takes these too: each becomes a 16-bit WAV beside the song through the ffmpeg the export uses,
  never over a file there, with the loops and root note OpenMPT keeps from it (a FLAC's embedded sampler chunks or its
  LOOPSTART/LOOPLENGTH tags, an AIFF's loops; nothing from Ogg or MP3).
- **The command line does what the app does to a song's history**: `undo`, `redo` and `trim-history --keep N`;
  `sections rename NAME --as NEW` (also in the app's `section_edit`; the section keeps its place and comment);
  `--json` on `sections`, `checkpoint` and `phrase`; and `--wait SECONDS` on all of them, to wait for a song the app or
  another command has open instead of failing at once.
- **Imports keep more, as OpenMPT does.** A MIDI file's pitch bends become E/F slides (with its RPN bend range), its
  sustain pedal holds notes until it comes up, and its markers become named sections. Module names keep their letters
  (`Böse` is `Bose`, read in the character set OpenMPT reads them in; it was `B?se`), and what an import drops without
  a sound (an IT's edit history, MIDI pitch wheel depth, instruments' MIDI channel, program and bank) is now listed
  with the other warnings.
- **Faust sounds can be made again.** Each FAUST tab save also writes a `faust:` entry for its WAV (the code, the
  notes, hold, tail, velocity and sliders) into `faust.yaml` beside the song, so `synth` and the RECIPE box render it
  again and edit it. The code being typed is kept with each song (it was one draft per browser). The sustain pedal
  (CC 64) holds notes on the FAUST tab. Leaving the tab, or COMPILE while notes sound, now lets the notes ring out on
  their release: faustwasm's soft all-notes-off was a hard one (CC 123) and cut them at once.
- **UI SCALE** (top bar and start screen, 90-200 %): the whole app larger or smaller, kept in the browser with the
  other page settings. The app's window has no Ctrl+wheel or Ctrl+= zoom (pywebview turns WebView2's off).
- **Faust plays chords, live and from MIDI.** The FAUST tab's code is now a polyphonic instrument, a voice per note in
  Faust's own way (`freq`, `gain` and `gate` set per voice; an `effect` in the code runs once on the sum). NOTE takes a
  chord (`C-5 E-5 G-5`) for PREVIEW and the saves. The piano keys play the code live at their real pitch (before, one
  render was replayed faster or slower) and hold the note until let go; sliders act on the notes sounding; with the
  tab open a MIDI keyboard plays it, with velocity, and pitch bend and controllers reach the controls the code maps
  with `[midi:...]`. Recipes: `faust:` samples take `chord:` and `phrase:` like synth patches.

- **Following OpenMPT** (GUIDE.md, "Following OpenMPT"; where the app does what OpenMPT does, it does it OpenMPT's
  way): the piano keys go by their place on the keyboard, so QWERTZ and AZERTY play what QWERTY does; the edit keys are
  OpenMPT's IT-style ones: `1` a note cut, `` ` `` a note-off, Shift+`` ` `` or `\` a fade (they were `1` note-off,
  `` ` `` fade, `\` cut); CHORD joins a key
  or MIDI note struck within 60 ms of the one before (OpenMPT's auto-chord wait; it was 50 ms from the first), so a
  rolled chord stays on one row; an MPTM parameter-control (PC) event pastes as `Zxx`, as OpenMPT converts it (it
  pasted its plugin number as an instrument).
- **The command line and the app share a song safely.** `sections`, `checkpoint` and `phrase` hold the song's lock for
  the whole command: a second command at the same time, or one while the app has the song open, is refused (exit 1)
  instead of losing a change while saying it saved. An app opening a song that a command is changing, or that another
  app window has open, waits a moment, then opens it read-only with a notice. Commands that only read leave the app's
  files alone, and the commands print what the app would show as a notice as `note:` lines.

Fixes, from an audit of 0.9.0 (36 bugs, each with a regression test): a background job that failed unexpectedly (a
RECIPE entry `chord: []`) stopped every later render, build and export until a restart; it now fails alone. Game loops
are frame-exact at every tempo (only tempos dividing 1500 were: at tempo 137 a 3.5 s loop was 114 frames short), and so
are whole-song lengths and phrase renders. Checkpoints save and restore a song whose text is not valid YAML. A phrase
render can no longer overwrite the notes report, its archives, the phrase comparisons or the recovery journal. Deleting
a section no longer leaves a blank line. A phrase's stars outside 0-5 are refused, an output path that is a folder or in
a missing folder is named in the error, and `api.save` writes LF in one atomic write.

Recipes: a render over full scale is scaled just under it, and the log says so, instead of clipped (unless
`normalize:` is set); an empty chord or phrase, a missing or zero `bpm`, a short phrase note or a velocity outside
1-127 is an error naming the key (some stopped the command with a traceback). Faust: a render's release no longer starts
up to 127 samples late; a note of zero length is released after one frame instead of sounding to the end; an `effect`
that does not compile is an error instead of being dropped; two overlapping notes of one pitch each end on their own
key-off; renders never steal a voice; on the FAUST tab a MIDI controller moves its slider (PREVIEW and the saves
rendered the slider's old value), leaving the tab puts a pitch-wheel control back, and code that does not compile is
not compiled again at every key.

Imports: a MIDI file played in without a click and slower than about 90 BPM got note delays the format lacks (`SD10`
and up) and did not compile; of several tempos or time signatures on one tick the last counts, and of tempo changes
landing on one row the last stays; track names written as UTF-8 read as such ("Böse" became "BA?se"), a name ends at a
NUL and names lose control characters. Guitar Pro: a capo raises the pitch (capo tabs imported too low, harmonics too),
and long or transliterated track names keep their " str N" numbers. Modules with a pattern over 200 rows: a jump past
the order list is dropped (it landed on a split part and changed the loop), and a jump and a break on one row land on
the row they name.

Install and tests: a pip-installed package has the Pattern tab's effect help and keeps the synth and Faust downloads in
`%LOCALAPPDATA%/VultureTracker/tools`, not in site-packages; the page tests and the Guitar Pro tests skip without
Playwright or PyGuitarPro; a test that failed about one run in 19 no longer does.

**Upgrade note:** the note-off, note cut and fade keys moved to OpenMPT's (above). Song files, history and checkpoints
are unchanged from 0.9.0, and so are renders. The listening notes (`<song>.notes.json`) are written in a new layout
when the next note is made: 0.9.0 and older read that file as empty, and a note added there replaces the others, so
keep a song's notes in 1.0. On Linux and macOS the settings, the library index and the window profile move to the
system's folder (the recent list is read from the old `~/VultureTracker`; the library is indexed again). Song lengths
are now taken at the rate the audio is mixed at, so a game loop's length and a song's reported length can differ from
0.9.0's by a few hundredths of a percent. A MIDI file imported again comes out with its bends, pedal and markers (and
one played in under about 90 BPM at speed 16 or less), and a module's names keep their letters. A recipe that clipped
renders a little quieter, unclipped.

## 0.9.0 (2026-10-01)

The finishing workflows on the command line, chords the OpenMPT way, and a second pass over the 0.7.0 audit.

- **Chords from the computer keyboard follow OpenMPT:** with CHORD checked, keys struck within 50 ms are one chord,
  written as the keys go down (0.8.0 waited until they were let go); holding Shift, OpenMPT's chord modifier, gathers
  any keys into one chord, written when Shift is let go.
- **Names from non-ASCII file names are transliterated:** `Böse Bass.wav` becomes the sample name "Bose Bass" instead
  of "B?se Bass"; imported titles and track names likewise. What has no ASCII form still becomes `?`.
- **Sections, checkpoints and phrases from the command line:** `sections`, `checkpoint` and `phrase` list, save,
  move, duplicate, diff, restore, capture, render and accept as SONG, PROJECT and PHRASES do, each change an undo step
  the app opens with. While the app has the song open, the commands that would change it are refused (the app would
  write its own history over theirs).

Fixes: a pattern loop across the 192-row split of a long imported pattern plays as the original (its part ends after
the loop, and a loop longer than any part is played out); an XM restart position whose last row has no free effect
slot gets a channel of its own; SLICE finds a hit in the last half millisecond of a selection; a naive (aliased) saw
high up is no longer read an octave low (the sample library reads its pitches again once).

More fixes, from the audit's unconfirmed suspicions (16 of 26 confirmed, each with a regression test): sample edits on
a `loop: from_wav` whose loop runs past the audio work (FADE, REVERSE and CROSSFADE were refused, and a refused edit
could leave a WAV behind); an edit that changes nothing (▲ on channel 1) adds no undo step and keeps the redo steps;
TRIM HISTORY with the keep field emptied no longer clears every undo step; export names and dropped WAVs called CON,
NUL, COM1 or another Windows device name are refused or renamed (an export called CON froze the app run from a
terminal); a rating outside 0-5 is refused, and a bad one in a hand-edited `.tryout.json` no longer stops the notes
report. Imports: an S3M or XM order entry past the last pattern becomes `+++` (a later jump could skip a whole
pattern), an IT `---` that a jump aims at is kept, a beat highlight with no bar gives bars of four beats, and the song
is written LF in one atomic write. SLICE skips a hit's abrupt end (a click) and places a hit over a pad or a tail at
its start (up to 30 ms early before; a point now needs the level to rise about 3 dB over what sounds just before it,
so a softer hit inside a louder sound is no longer one); STRETCH of a selection shorter than about 90 ms keeps its
level (it lost up to 30 dB); recipes read `0100` as a hundred and a sample `010` writes `010.wav`, as song files read
them; a name such as "08" stays "08" when the app writes it; the sample library reads an unfinished WAV's real length
(it reads every file again once); Ctrl+Alt+V floods on layouts where AltGr+V types `@`; a ring-out ending on a
full-scale negative peak is no longer cut short.

**Upgrade note:** song files, history and checkpoints are unchanged from 0.8.0. The sample library reads every file
again once. SLICE's automatic points and STRETCH on short selections can differ from 0.8.0's (see above). In a sample
recipe, numbers with leading zeros read as decimals and a sample named `01` writes `01.wav` (it wrote `1.wav`).

## 0.8.0 (2026-10-01)

Getting music and sounds in and out.

- **Game loop export:** RENDER & EXPORT's Game loop (and `export --loop`) writes a section, or the whole song, for a
  game engine to loop: the region's second pass, so it starts with what its own end leaves ringing and the seam is
  continuous, then the tail as its release. WAV marks the loop in a `smpl` chunk, OGG and FLAC in `LOOPSTART` and
  `LOOPLENGTH` tags.
- **MIDI file import:** `.mid` and `.midi` (type 0 and 1) become song files with the Guitar Pro import's placeholder
  sounds, from the command line and the app's import. Quantised files get the coarsest grid that holds every note;
  played-in ones get sixteenths with note delays (SDx). Needs `pip install mido`.
- **OpenMPT clipboard both ways:** COPY puts the rows on the system clipboard in OpenMPT's format; Ctrl+V pastes rows
  copied in OpenMPT from an IT or MPTM module.
- **Command-line export and collect:** `export` (formats, sections, stems, game loops, the app's current mix) and
  `collect` (with `--zip`) without opening the app; neither writes anything beside the song.
- **Chords from the computer keyboard:** with CHORD, piano keys struck within 100 ms of each other go in as one chord.
- **Continuous integration** on GitHub Actions runs the portable and browser tests; this changelog.

Fixes: the 55 defects of an audit of 0.7.0, each with a regression test (`tests/test_release080*.py`): file writes
(the Tryout's keys no longer act from the Pattern tab; export and collect destinations relative to the song's folder),
crashes (sample keys, sections, library scans, non-ASCII and corrupt imports), silent wrong output (whole-song
ring-out, phrase renders, ECHO across patterns, live MIDI chords, imported loops and breaks, the resampler's images
above the source Nyquist: 128 taps, cut at 0.95), and the page against GUIDE.md.

## 0.7.0 (2026-09-30)

Longer editing sessions and performance capture, with fixes for 22 reproduced audit defects.

- **Bounded history:** compressed undo/redo and recovery data, a 16 MiB history budget, and PROJECT controls to trim or clear undo/redo while keeping named checkpoints. Large songs no longer hit the old recovery-journal limit after a short editing session.
- **Record alongside playback:** play the saved song or a named section with the current mixer and mutes, count in, record separate loop passes, and compensate round-trip latency using a loopback calibration. Input and output use one duplex stream and must share a driver/host API.
- **MIDI chords:** capture notes arriving within 50 ms across consecutive channels, as one undo step. Chords that exceed the remaining channels are refused without partial writes.
- **MAKE EDITABLE:** convert quoted or compact patterns to literal tracker rows; undo restores the original notation.
- **Beat spacing:** set rows per beat and bar in SONG. The grid, metronome and BPM display use these values, which round-trip through IT import/export.
- **Shared phrase samples:** frozen WAVs are stored once by content hash across new captures. Existing phrase folders remain readable.

Fixes include source-file overwrite protection in CLI tryout; section deletion/recreation; channel-row and YAML edits; inherited sample names and ECHO instruments; unsigned IT samples and pattern orders above 199; Guitar Pro Unicode titles; slice-delay overflow; mosaic tails; recorder pre-roll; Unicode take playback; song-switch cursor state; sounding-note reports; channel level measurement; full-scale peak detection; leading-zero decimal values; and the missing-candidate collection remedy.

**Upgrade note:** 0.6.0 history and checkpoints are read and migrated on the next write. The resulting compressed history format requires 0.7.0 or later. Named checkpoints are never automatically discarded; PROJECT explains when one must be removed to fit the storage budget. Song YAML remains the musical source of truth.

**Validation:** 230 tests passed; one optional synth test was skipped because Dexed is not installed. Browser and native-window checks passed. The packaged executable loaded the bundled demo, saved a checkpoint, changed and undid beat spacing, measured a simulated 50 ms loopback, and exported IT and MP3 using the companion ffmpeg. Physical-interface latency remains unvalidated; calibrate the actual device/rate/driver combination before recording.

Deferred proposals are tracked in [BACKLOG.md](https://github.com/shadoh420/VultureTracker/blob/v0.7.0/BACKLOG.md).

## 0.6.0 (2026-09-27)

**Finishing and sharing a song.** Four new tabs and a safer save underneath (walkthrough: GUIDE.md, "Finishing and sharing a song").

- **PROJECT:** undo/redo now survives restarts (200 steps), plus up to 32 named checkpoints you can compare and restore. When the song changes on disk, COMPARE / RELOAD shows the difference before reloading. Save Copy / Collect Samples writes a self-contained copy of the project (optionally a ZIP) with its samples, candidates, notes, recipes and credits. Missing samples can be relinked.
- **SONG:** named sections over the order list. Select, loop, move or duplicate a section (shared or independent pattern copies), and `Bxx` jumps follow their targets. MAKE THIS OCCURRENCE UNIQUE clones one order's pattern. Sections are stored as a `sections:` key (SONG_FORMAT.md).
- **PHRASES:** capture a selection, write two to four versions of a line yourself, and play them against the same frozen accompaniment and mix, with a version where the line is absent. Rate and note them, then diff and accept one (one undo step).
- **RENDER & EXPORT:** one panel for IT, WAV, MP3, OGG, FLAC and aligned stems. You choose the destination, the name, the whole song or a section, the saved or current mix, whether audition mutes apply, and the tail. A job is fixed when queued, can be cancelled, and never overwrites a source sample. Existing files are only replaced when you ask.
- Fixes: exports and builds can no longer overwrite a sample the song plays; a new song's tone never replaces an existing WAV; the song, its tryout settings and its history are saved together, and an interrupted save is recovered on reopening.

## 0.5.3 (2026-09-26)

**New: one download.** `vulturetracker-win64.zip` holds the exe, ffmpeg, the licences and two demo songs (Arena and Iron Relay) with all their samples. Unzip it anywhere, run `vulturetracker.exe`, and the start screen lists the demos.

- Fix: a downloaded exe looked for demos and `samples/` one folder above its own and found none. It now looks in its own folder first (still one level up for `dist/` in a checkout). The sample library's default folders follow the same rule.
- README: Install starts with the download.

## 0.5.2 (2026-09-26)

VultureTracker 0.5.2 fixes what a code review of 0.5.1 turned up: two ways to lose work, and a set of smaller correctness bugs.

- **Export never overwrites a sample.** Exporting `song.yaml` as `song.wav` used to replace a sample of the same name without warning. The export now stops and names the file.
- **RECORD keeps the take.** Changing INPUTS during a take could throw the whole take away. INPUTS is now locked while recording.
- **S3M import.** 16-bit samples (stored unsigned, the S3M default) now import correctly. They used to come out as full-scale noise.
- **Undo.** An undo whose write fails (Windows sometimes holds the file a moment) no longer loses its step. Saves now retry briefly when that happens.
- **Live playback follows the samples.** A WAV re-rendered in place now reaches the live engine without a RELOAD.
- **Piano keys on PAINT and FAUST.**
  - Keys pressed while a sound renders share one render and play in order, each at the pitch it had when pressed.
  - Nothing plays once you leave the tab, and ■ stops the keys too.
- **Smaller fixes.**
  - A song section of the wrong shape (such as `samples: [1]`) shows as an error instead of breaking the app.
  - GROOVE rejects delays over 15 ticks, which SDx cannot hold.
  - Memory no longer grows with every compile.
  - Two settings saved at the same moment no longer collide.
  - 8-bit WAVs of odd length keep their loop and root note.
- **Guitar Pro placeholders are in tune.** The pluck model played up to 35 cents flat on high notes. Import a tab again to get the new placeholder sounds.

## 0.5.1 (2026-09-26)

VultureTracker 0.5.1 fixes what the first listening pass over 0.5.0 turned up.

- **Piano keys on the PAINT and FAUST tabs.** Z–M and Q–U now play the painted picture (as C-5) or the Faust note (at NOTE), pitched per key. The sound is rendered again after every change.
- **RECIPE box.** It grows to fit the whole entry, so keys further down (such as a `resynth:` entry's `block:`) are no longer hidden.
- **Guitar Pro import.**
  - A track at full mixer volume no longer fails to compile (the volume came out as 65 of 64).
  - The placeholder guitar and bass no longer hiss. The string model had a bug, and each note started with a burst of unfiltered noise. Import a tab again to get the new placeholder sounds.

## 0.5.0 (2026-09-25)

VultureTracker 0.5.0 finds and makes sounds. Your sample folders are indexed by timbre so the Tryout can offer the nearest sounds, two new tabs make sounds in the app, and Guitar Pro tabs import as songs.

- **Finding sounds.**
  - Your WAV folders are indexed by timbre, brightness, attack, length, pitch and harmonics. A rescan reads only new or changed files.
  - In the Tryout, ≈ LIKE SLOT and ≈ FIND SIMILAR TO THIS add the library's nearest sounds as candidates, each with its distance.
  - The MAP tab lays the library out by likeness: click a point to hear it, zoom, pan, filter by name, and send it to the candidates. FOLDERS INDEXED chooses what is indexed.
  - On the command line: `index [folders] --like WAV` and `tryout --like WAV`.
- **PAINT tab.** Paint over frequency and time (brightness is level, colour is pan), then play it, send it to a new slot or a candidate, or lay it over a sample as a filter. LOAD IMAGE paints from a picture.
- **FAUST tab.** Write [Faust](https://faust.grame.fr) code, compile it in the page and render notes into a new slot or a candidate. GET FAUST downloads the compiler (about 6 MB) on first use. Recipes can use `faust:` too (needs node).
- **Recipe source `resynth:`.** Rebuilds a target WAV from short blocks of other WAVs, matched by timbre.
- **Guitar Pro import.** GP3, GP4 and GP5 tabs become song files with placeholder sounds to swap in the Tryout: ties, hammer-ons, slides, bends, vibrato, dead and palm-muted notes, harmonics, triplets, tempo changes, repeats and alternate endings. IMPORT A MODULE OR A TAB on the start screen, or `import tab.gp5`. GP6+ files are not read yet.
- **Samples tab.**
  - SLICE AS MULTISAMPLE maps each pitched slice over the keys nearest its note. + PATTERN writes the slices as a pattern at their original timing.
  - LEARN NOISE and DENOISE reduce steady background noise.
  - SLICE's report shows in the tab; after STRETCH, TRUNCATE SILENCE or TRIM the view shows the whole new WAV.
- **RECORD tab.** TAKES → MULTISAMPLE turns recorded takes into one multisampled instrument.
- **Speed.** Faster library indexing on Windows. `VT_WORKERS=3` renders tryout candidates on three workers (15-20 % sooner, but edits reach the live engine later, so it is off by default).

## 0.4.0 (2026-09-25)

VultureTracker 0.4.0 records. A new RECORD tab takes audio from an interface into the song, and the Samples and Pattern tabs gain tools to cut, process and compose with what you record.

- **RECORD tab.**
  - Records from any audio input Windows lists: WASAPI (shared or exclusive), MME, DirectSound, or ASIO. Tick ASIO and restart the app to list drivers such as Focusrite USB ASIO.
  - Takes input 1, input 2, both as stereo, or both mixed to mono. It shows a peak meter per input with clip, a tuner, and up to 0.5 s of pre-roll.
  - Each take is saved beside the song with its silence trimmed and its note found. It then becomes a tryout candidate for the slot, or a new slot tuned to the cent with an instrument that plays it, or stays in the list.
  - Tested on a Focusrite Scarlett Solo (3rd Gen) under WASAPI shared and exclusive and under ASIO, in the exe. Monitoring is the interface's own; the app does not play the input back.
- **Samples tab.**
  - AUTO LOOP proposes loop points for a sustained sound; CROSSFADE LOOP smooths the wrap.
  - SLICE cuts a sample at its hits or into equal parts, as new slots plus a kit instrument.
  - EFFECTS → NEW WAV: gain, low-pass and high-pass, an EQ band, loudness, pitch at the same length, stretch at the same pitch, truncate silence.
  - ▶ HOLD plays a slot at its own note (its base note, or the note its speed sets).
- **Pattern tab.**
  - COMPOSE: GROOVE (a note delay per row for swing), EUCLID (Euclidean rhythms), CHORD (a chord over the channels to the right, 17 shapes with inversions), LAYERS (round-robin or velocity layers).
  - RENDER → SLOT renders the selected rows as they play in the song into a new slot, with their ring-out.
- **Speed.**
  - An edit compiles in about a sixth of the time.
  - Oversampled renders are about three times faster and bit-identical.
  - Faders are heard in the live engine while they move.

## 0.3.0 (2026-09-25)

VultureTracker is now a tracker as well as a compiler: a live engine, pattern and sample editors, MIDI input, and import of MOD, S3M and XM. The RECIPE box renders new samples from Surge XT or Dexed straight from the exe.

- **Live engine.** libopenmpt runs as WebAssembly in the page and plays the song as it stands, unwritten mix included, from any order and row. It has mutes, solo, a metronome, an oscilloscope and pattern loop.
- **Editing.**
  - The Pattern tab edits in place: notes, instruments, volumes and effects, with selections, copy, paste, flood, transpose, interpolate, amplify, find and undo.
  - HUMANIZE moves note volumes at random.
  - ECHO copies a channel's notes into another channel, later and quieter: a tracker delay, in one undo step.
  - The Song, Instruments and Samples tabs edit orders, instruments (envelopes, keymaps) and samples (trim, loops, processing).
- **MIDI.**
  - A keyboard previews notes and, in edit mode, enters them at the cursor, with velocity as the volume.
  - While the pattern plays, notes land on the row that is playing.
- **RECIPE box.**
  - When a sample recipe in the song's folder writes a slot's WAV, the Tryout tab shows its entry. Edit it, render it as a new candidate (never over the original), or write it back into the recipe.
  - If Surge XT (300 MB) or Dexed (10 MB) is missing, the box offers the download. It goes into `%LOCALAPPDATA%\VultureTracker\tools`, then the render runs again.
- **Import.** MOD, S3M and XM as well as IT.
- **Anti-aliasing.**
  - Looped samples are resampled as they play, so loops stay seamless at any storage rate.
  - `check` warns when a note plays a sample far enough below its root to image.
- **Robustness.**
  - The fixes from a full audit, with a test for each: undo covers mix and tryout changes, files are written atomically, and malformed songs, modules and WAVs are reported instead of crashing.
  - The server refuses requests from other web pages and host names.

## 0.2.2 (2026-09-22)

Patch release for the listening loop: the pattern view has its own tab, the notes bar is one button, and a written candidate choice clears its list.

- PATTERN is its own tab: the read-only pattern view, the whole window wide, following the selected order and the playhead. It was a narrow rail in the Song Overview where a few channels fit.
- The notes bar keeps only NOTE… (`N`). Every note lands at the playhead with the channels sounding there; the words are yours.
- `U` (use this candidate for the slot) clears that slot's candidate list once the song is written: the choice is made. Ratings are remembered per file, so a rejected sound shows as rejected if it is added again.
- The repository now carries the first piece of the UT99 tribute suite (`suite/nadir/`) with its generators, samples and listening notes; the exe is unchanged by that.

`synth` and `audition` still need a source checkout with the plugins and packs from `tools/`, as SAMPLING.md describes; the exe does not include them.

## 0.2.1 (2026-09-22)

Patch release for the listening loop: the song file keeps its line endings, notes belong to the version they were made on, a solo lands where you clicked, and playback can be slowed down.

- Fixed: writing the song from the app (U, WRITE MIX → SONG) turned every line ending into CRLF on Windows. The file is now written back with the endings it had. The 0.2.0 exe has this bug; the content it wrote is otherwise correct.
- Listening notes belong to the version of the song they were made against. When the song changes outside the app (a rebuild), the notes on the old version move to `<song>.notes-<hash>.json` and `.md` beside it and the NOTES tab starts empty; the app's own writes keep them, and the report marks their version.
- Soloing or muting while playing (the SOUNDING chips, the stems rail, SOLO IN SONG, UNMUTE) rewinds a second when the new render lands, so the moment you clicked on is heard with the change, even when the render takes a few seconds.
- SPEED in the player slows playback to 75, 50, 33, 25 or 20 % with the pitch kept; the setting survives switching candidates and is remembered.

`synth` and `audition` still need a source checkout with the plugins and packs from `tools/`, as SAMPLING.md describes; the exe does not include them.

## 0.2.0 (2026-09-22)

Anti-aliased renders, a mixer in the app, and listening notes: a way to say what you hear at the playhead without having to describe it.

- Renders are anti-aliased: the mixer runs at twice the output rate and the result is band-limited back down with a windowed sinc (`render --oversample 1` turns it off). A song can set `module: sample_rate: 44100` to resample every sample at compile time, band-limited, so playback in any player neither images nor aliases.
- The Song Overview's stems rail is a mixer: a volume and pan fader per channel, a MIX VOL master showing the peak of what is playing, a GAIN fader per sample slot, and a meter per channel measured with that channel soloed. Every move re-renders the tryout at once (the section is compiled once and the values are patched into the module header). WRITE MIX → SONG shows the YAML change and edits the song in place; EXPORT STEMS writes one WAV per playing channel.
- Listening notes: while the song or a candidate plays, click TOO LOUD, TOO QUIET, HATE THIS SOUND, TOO BUSY, KEEP or NOTE… (`N`). The note records the time, order and row, what was playing, and the channels sounding there with the slot each plays; click the one you mean and add words. Notes live in `<song>.notes.json` and are rendered as `<song>.notes.md`, a report grouped by section for a collaborator who cannot listen; the NOTES tab lists and edits them. Nothing touches the song file.
- The player: a SOUNDING strip under the progress bar shows the channels sounding at the playhead (click one to solo it); the bar seeks on click or drag; SAMPLE ALONE (the candidate's WAV by itself) and SOLO IN SONG (every channel that never plays the slot muted) replace the old SOLO; the slot list marks slots that have candidates; rejected candidates sink to the bottom; the render you are listening to goes first in the queue, a stale meters pass stops itself, and the player says when the old render is still playing while a new one lands.
- Compiles are memoised per sample file, so a song with `sample_rate` compiles in a fraction of a second after the first time; `tryout_song` accepts a song dict.

`synth` and `audition` still need a source checkout with the plugins and packs from `tools/`, as SAMPLING.md describes; the exe does not include them.

## 0.1.1 (2026-09-22)

Patch release: the app's comparisons and overview are now trustworthy on their own promise, and the first-run demo works from a bare checkout.

- The render cache key now stamps every WAV in the mix, not just the candidate. A kit re-rendered in place under the same paths no longer plays back from the old mix. Existing `.tryout/` renders are redone once.
- Order timing in the Song Overview comes from libopenmpt, so speed and tempo changes, pattern breaks (including into the middle of a pattern) and jumps count; an order that never plays reads as 0 s.
- Applying a candidate patches a block-mapping sample slot in place as well as a one-line flow mapping, so comments elsewhere in the song survive. The full re-dump is only the fallback when the slot's lines cannot be found, and the diff still says when that happens.
- The README and GUIDE open `demo2/iron_relay.yaml` first: every sample it needs is in the repository. `demo4/vantage.yaml` still needs the drum renders that live in the gitignored `samples/local/`, as its header explains.
- The song file is the source of truth and each pattern generator is its scaffold: rerunning a generator discards hand edits made to the patterns since (GUIDE, the Vantage header, the generator docstring).

`synth` and `audition` need a source checkout with the plugins and packs from `tools/`, as SAMPLING.md describes; the exe does not include them.

## 0.1.0 (2026-09-21)

First release under the new name. Write tracker music as a YAML file, compile it to an Impulse Tracker module (`.it`), render it to WAV, and audition candidate samples inside the song from the app.

- The tryout app: candidate WAVs rendered inside a section of the song with only one slot swapped, keys 1 to 0 to switch without losing the position, stars, reject and notes per candidate, and a one-line YAML apply with a diff preview.
- Song Overview: a stems rail with mute and solo (the section re-renders without those channels), the arrangement grid and slot table with measurements, a read-only pattern view that follows the selected order and the playhead, and stems export (one WAV per playing channel).
- Render & Export builds the `.it` and verifies it with libopenmpt.
- CLI: `check`, `build`, `render`, `info`, `import`, `synth`, `audition`, `tryout`.
- Four demo songs; the song format is in SONG_FORMAT.md and sample making in SAMPLING.md.

`synth` and `audition` need a source checkout with the plugins and packs from `tools/`, as SAMPLING.md describes; the exe does not include them.
