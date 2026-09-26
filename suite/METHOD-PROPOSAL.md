# How to make a piece that sits in the UT99 soundtrack without tracing one track: a proposal (2026-09-24)

Written after the owner's verdict on Rift and Vantage ("the musical equivalent of tracing") and after the diagnosis in
`suite/TRACING-DIAGNOSIS.md`. Both ends have failed:
- Nadir averaged seven tracks and sounded jumbled. Measured, its orders sit at an ordinary distance from UT99 (45th
  percentile), their nearest orders spread over seven tracks.
- Rift and Vantage followed one track, and everything that decides how a passage behaves came from it: which layers
  play when, what each does on which row, its echoes, fades and swells, its level, the form, the colour set, and for
  Vantage the tempo and grid. Rift runs 20 orders in Nether's order where two different UT99 tracks never share more
  than 4.

What Rift and Vantage made their own (notes, cells, sources) is what the measures find least decisive.

## Kept from the current method, whatever is chosen

- One layer at a time, candidates in the tryout, the owner's ear deciding every sound; U writes the pick; faders are the
  owner's; approved sounds stay.
- The anti-aliasing rules, the spectrogram check, band-limited storage, noise floors on synth sources, tuning by
  measurement.
- The measurement tools: `analyze.py`, `structure.py`, `perchannel.py`, `melodic.py`, `compare.py`, and now
  `sections.py`, `globaldims.py` and `formcurve.py`.
- Copyright: no audio, sample data or melodic cell from the UT99 modules; "inspired by" in PROVENANCE.
- Reports are measurements; nothing is claimed as heard.

## The "not a trace" check (shared by all three methods)

Every threshold here is set so that no two different UT99 tracks fail it. The corpus is 28 modules and 1086 orders
for the order measures, and 377 pairs of different tracks (Seeker and Seeker 2 share material and are not counted as a
pair; the XM module and the duplicate Save Me are left out). The whole-song measure uses 29 tracks and 405 pairs.
"Distance" is `sections.py`'s order distance: 0 means two orders do the same things with the same kind of sounds, and
the median UT99 order sits 0.214 from its nearest order in any other track.

1. **No order too close.** No order of ours closer to a UT99 order than two different UT99 tracks' orders ever get
   (0.125). Rift today: 12 orders.
2. **No track too close.** Against any one UT99 track, at most a quarter of our orders closer than 0.164 (a distance
   only 5 % of UT99 orders reach). The most two UT99 tracks share is 24 % (Go Down against Organic). Rift against
   Nether today: 53 %.
3. **No traced run.** No run of consecutive orders following one track's orders under 0.164 longer than any two UT99
   tracks share (4, Go Down and Organic). Rift today: 20.
4. **No traced form.** Our layer-count curve (how many layers sound, over the song) no closer to any one track's than
   the closest two UT99 tracks are (0.076, Room of Champions against the Title). Rift today: 0.060.
5. **No borrowed frame.** Against any one track, at most 2 of the 8 whole-song dimensions (`globaldims.py`: tempo,
   harmony, harmonic motion, spectrum, mix, dynamics, rhythm density, length) closer than 95 % of UT99 pairs are. Four
   of 405 UT99 pairs have 3. Rift has 1, Vantage 2: this check passes both. Vantage's identical tempo and grid are caught
   by check 6, not here.
6. **An inheritance audit.** The measures see Rift's trace plainly and Vantage's hardly at all, so every piece carries
   a table like the diagnosis's with a fixed list of ten dimensions:
   - tempo and grid;
   - key and root;
   - form (lengths, order, entries);
   - layer set and roles;
   - per-layer idioms;
   - sample-character targets;
   - levels;
   - drum rows;
   - melodic cells and the rhythm of the lines;
   - harmony and colours.

   Each is marked copied exactly (C), genre (G: shared by at least three UT99 tracks by at least two composers) or ours
   (O), with its source. The rule: against any one track, at most **two** of the ten marked C. Rift today: 7 of 10
   against Nether. Vantage: 7 against Foregone (tempo and grid, layer set, idioms, sample targets, levels, drum rows,
   colours).

And it must still **sit in UT99**:
- the median distance from our orders to their nearest UT99 order within the range UT99 tracks themselves show
  (0.171-0.264; Nadir 0.210, Rift 0.161, Vantage 0.189);
- every `compare.py` feature inside the whole corpus's range.

These are loose fences: Nadir passes them and still sounded jumbled. Whether a piece belongs is the owner's ear, played
against the two or three UT99 tracks the measures name as nearest, judged "traced", "belongs" or "doesn't belong".

## Method A: the soundtrack's style sheet

- **References are used for** a style sheet measured across the corpus, or across a chosen family of five to eight
  tracks by at least two composers: ranges and vocabularies, never one track's combination. It lists tempo bands and
  grids in use; section types and length distributions; the layer roles and how often each occurs; the idiom
  vocabulary with how many tracks use each entry (echo delays and levels, offsets, glides, restarts, surround, swells);
  level bands per role; harmony habits (pedals, colour intervals, root motion); sample-character ranges per role.
- **Each piece invents** its combination: one choice per dimension, from the sheet's genre (G) entries only. Its
  notes, cells and sounds are its own.
- **"Not a trace" is checked** by the six checks above; only G-level entries of the sheet can be used without
  counting against the audit.
- **The owner picks** the combination first, from two or three short rendered sketches (MP3s) that differ in tempo,
  form and idioms, then the sounds per layer in the tryout as now; the sheet only sets the class a candidate must fall
  in.
- **Risk:** this is closest to Nadir. A combination drawn from ranges has no reason to hang together, so it can end up
  jumbled again. It needs something that holds the choices together, which is why method B exists.

## Method B: our own concept first, the references as limits (recommended by default)

- **References are used for** limits and a vocabulary, not a template: the style sheet of method A as the fence
  (what a UT99 track does and never does), and nothing else. No single track's form map, layer plan or idiom table is
  read while writing the piece.
- **Each piece invents**, without reading any single track's measurements (the style sheet is measured once, for the
  whole soundtrack):
  - A concept. Which ArenaPrototype level or moment it is for, its mood in a sentence, and its arc in plain words
    (where the tension rises, where it breaks, how it ends), which becomes the form.
  - One signature motif, a figure of our own, written first and developed through the piece.
  - One signature sound, picked in the tryout before anything else.
  - The layer set the concept needs, and not more. Each layer's idiom is chosen for what it must do in this piece,
    from the vocabulary.

  The form (section lengths, entries, arc) is written from the concept. The starting levels come from the sheet's level
  bands per role; the owner then sets them by ear.
- **"Not a trace" is checked** by the six checks. The audit table is kept from the first step. The order checks run
  on the first full-length draft and again before the form is final; a loop of one pattern is too short for them.
- **The owner picks** the concept, from two or three written options. Then the signature sound (candidates in the
  tryout) and the motif (two or three versions rendered as short MP3s, since the tryout swaps sounds, not notes). Then
  each layer as now. Nothing is arranged before the concept, the motif and the sound are approved.
- **Why it can work where the others failed:** the reference's timeline and combination never enter the piece, so the
  runs and the copied rows cannot appear. The style sheet keeps the piece inside what UT99 tracks do. The concept holds
  the choices together, where Nadir had nothing that did.

## Method C: the reference as a lens

- **References are used for** understanding one effect at a time. The brief lists effects the piece needs (forward
  motion, width, a lift at a section change, darkness, tension before a drop) and, for each, how one or two UT99
  tracks get it: which layers, which idiom, which level. Different effects may come from different tracks.
- **Each piece invents** another way to get each effect. If Nether gets motion from a gliding 8th sequence with
  delayed copies, we get it from something else the corpus also uses (a gated chord, a bass ostinato, a broken-beat
  chop), or from a device of our own. The form is ours, as in B.
- **"Not a trace" is checked** by the six checks, plus: for every effect, the mechanism differs from the lens
  track's in at least two of layer, idiom and level.
- **The owner picks** per effect: two or three mechanisms offered as short rendered loops (MP3s), then the sounds in
  the tryout as now.
- **Risk:** slower (a loop per effect). The lens tracks' fingerprints are close at hand, so the audit must be strict.

## Which one, depending on the listening test

`suite/rift/variants/LISTENING.md` changes one dimension at a time and asks two things of each file: still Nether or
not, and whether it still belongs on the UT99 soundtrack.
- **v1 (our own form) stops sounding like Nether and still belongs:** the timeline carries the likeness. Method B,
  whose form comes from the concept.
- **v1 stops sounding like Nether but no longer belongs:** the form also carried the UT99 feel. Method C: learn from
  the lens tracks how a UT99 form builds and releases, then build ours another way.
- **v3 (our own idioms) removes it most:** the per-layer habits carry it. Method B or C, with idioms from the
  vocabulary of several tracks, never one track's table.
- **v4 (other sound classes) removes it most:** sound choice by the reference's character figures carries it. Method B,
  with sounds chosen for the concept inside the sheet's ranges.
- **v2 (layer set) or v5 (tempo and groove) removes it most:** a single swap already frees the piece. Method A is
  enough, as long as the owner picks the combination.
- **None removes it alone:** the trace is the combination. Method B, where no two dimensions come from the same place.

Default recommendation: **B**, with A's style sheet as its fence and C's lens only for an effect that is hard to get.
It keeps the reference's timeline out by construction, and the check that caught Rift most plainly (the traced run)
comes from that timeline. The draft next prompt beside this file (`suite/NEXT-PROMPT-DRAFT.md`) is written for B. If
the listening points to A or C, its Steps 0-2 change as described above. Adopting any of the three also means
rewriting AGENTS.md's "Follow the reference" rule, on the owner's word. `suite/NEXT-PROMPT.md` stays as it is until
the owner agrees.

## What happens to Rift

Rift stays as built. Two ways on, for the owner to choose later:
- Re-form it by method B: keep its approved sounds, write a concept, a form and idioms of its own. v1 and v3 are two
  first sketches of what that would sound like.
- Close it as a study.

Vantage stays as it is. The PROVENANCE wording is unchanged.
