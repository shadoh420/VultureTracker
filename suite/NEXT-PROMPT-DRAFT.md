# Draft next prompt: method B (concept first, the UT99 soundtrack as limits)

A draft beside `suite/METHOD-PROPOSAL.md`, for the owner to accept, change or replace once the listening test is in
(`suite/rift/variants/LISTENING.md`). `suite/NEXT-PROMPT.md` stays in force until the owner agrees. Adopting it also
means rewriting AGENTS.md's "Follow the reference" rule (one reference track, the reference's balance) on the owner's
word; until then, where AGENTS.md and this prompt differ on method, this prompt is the owner's newer instruction.
Replace `<piece>`.

---

This is a VultureTracker task (the tracker-music compiler at C:\Users\c\TrackerForge, origin
github.com/shadoh420/VultureTracker; not ArenaPrototype: work only there, with absolute paths). Read AGENTS.md, then
suite/HANDOFF.md, suite/METHOD-PROPOSAL.md and suite/TRACING-DIAGNOSIS.md. Read GUIDE.md, SONG_FORMAT.md and
SAMPLING.md only when you need them.

Goal: an original track that could sit on the Unreal Tournament (1999) soundtrack without being a trace of any one
track on it. Rift and Vantage followed one reference each and read as tracings to me; Nadir averaged seven and sounded
jumbled. This piece starts from its own concept. The soundtrack is used only as a fence (what UT99 tracks do and never
do) and a vocabulary, measured across the whole soundtrack. No single track's form map, layer plan, idiom table or
colour set is read while writing it. My ear decides, in the app, one layer at a time.

Step 0, before any sound:
- (a) **The style sheet.** Measured once across the UT99 corpus (scratch/ut99-clean/: features.json, structure.py,
  perchannel.py, melodic.py, sections.py):
  - tempo bands and grids in use;
  - section types and length distributions;
  - the layer roles and how often each occurs;
  - the idiom vocabulary, with how many tracks use each entry (echo delays and levels, offsets, glides, restarts,
    surround, swells);
  - level bands per role;
  - harmony habits (pedals, colour intervals, root motion);
  - sample-character ranges per role.

  Mark as genre (G) only what at least three tracks by at least two composers share. List the composers you can
  establish from the modules' own text, and ask me for the rest. Write it as suite/STYLE-SHEET.md, figures only, no
  notes, cells or samples; it stays uncommitted (it measures Epic's modules).
- (b) **Two or three concepts** for <piece>, each half a page:
  - which ArenaPrototype level or moment it is for;
  - the mood in a sentence;
  - the arc in plain words, which becomes the form (sections, lengths, where things enter and leave);
  - the character of the signature motif and the class of the signature sound;
  - the layer set it needs;
  - a tempo and grid from the sheet;
  - a first inheritance-audit table (METHOD-PROPOSAL.md, check 6: ten dimensions, each marked C, G or O with its
    source; at most two C against any one track).

Stop for my pick.

Step 1: the signature sound first, three to five candidates in the tryout (sources: samples/local/, Surge XT, OB-Xd,
Dexed, VSCO, VCSL, the Big Rusty kit, the TR-8 pack; noise floors on synth sources as gen_floor.py adds them; tuned by
measurement). Then the motif, our own figure: two or three versions rendered as short MP3s, since the tryout swaps
sounds, not notes. Then one pattern of drums and bass in the concept's groove, at the concept's tempo, with candidates
per role. Stop for my picks.

Step 2: one layer at a time, in the order the concept's layer plan gives. Each is written for what it has to do in this
piece, with an idiom chosen from the sheet's vocabulary (not from one track's table) and levels starting inside the
sheet's band for its role. Each is offered as 3-5 candidates, each in its own single-sample slot, and each is stopped
for my pick. Keep the audit table current. Nothing goes into the song that I did not choose.

Step 3: only when every sound is approved, lay out the form from the concept. Then run:
- the six "not a trace" checks of METHOD-PROPOSAL.md (sections.py, globaldims.py, formcurve.py, the audit table);
- the "sits in UT99" fences;
- harmony.py's clash check;
- the spectrogram: nothing above the drums' ceiling;
- the MP3.

Then stop. I listen in the app (python -m vulturetracker gui suite/<piece>/<piece>.yaml) against the UT99 tracks the
measures name as nearest, and drop notes with N. You act on the notes and their sounding lists, one round at a time,
and ask nothing the report answers.

Standing rules:
- Report measurements, never claim to have heard anything.
- Drums and sounds I approve stay row for row.
- Every melodic voice gets its own single-sample slot.
- The faders are mine.
- Anti-aliasing:
  - songs set `module: sample_rate: 44100` and renders are oversampled;
  - a sample's bandwidth times its transposition stays under about 18 kHz and under the drums' ceiling;
  - a bright sample is not played more than about three semitones below its root (store it band-limited, add a lower
    multisample, or set sample_rate 88200);
  - `check` must not warn;
  - the spectrogram check stays.
- Nothing from the UT99 modules goes into our songs or samples: no audio, no sample data, no melodic cell, no sample
  chosen by matching one of theirs. PROVENANCE says "inspired by".
- No commits or pushes unless I say so. Stage exact paths, never git add -A, git add . or commit -am. Review
  git diff --cached first. scratch/, samples/local/ and every render stay out.
- Write files with their own line endings. Big Python patches go through Write-tool script files.

Done when: Step 0's style sheet and the concepts are written and you have stopped for my pick.
