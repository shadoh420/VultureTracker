# VultureTracker backlog

The focused 0.7.0 scope is: fixes for the 22 reproduced audit defects, bounded history,
recording alongside playback, MIDI chord capture, conversion to editable literal patterns,
configurable beat spacing, and shared phrase-sample storage.

## Deferred proposals

- **Faust polyphony, MIDI and live audio.** Extend the current single-voice preview to multiple voices, MIDI control and a live audio node. Source: `suite/HANDOFF.md` Faust backlog and `web/faust-render.mjs`; deferred because voice allocation needs separate design and audio validation.
- **Guitar Pro tab view, fretboard entry and GPX support.** Add a read-only tab view first, then fretboard editing and GPX import alongside the existing importer. Source: `suite/HANDOFF.md` Guitar Pro backlog and `vulturetracker/gpimport.py`; deferred because round-trip editing needs a richer model than imported cells.
- **Game-loop target engine.** 0.8.0 marks a loop by the export format (WAV `smpl` chunk, OGG/FLAC `LOOPSTART`/`LOOPLENGTH`; MP3 and IT refuse a loop). Whether to target a particular engine or middleware (its own loop metadata, a sidecar file) is deferred by the owner. Source: `vulturetracker/export.py` and `gui._encode`.

Done in 0.8.0 (CHANGELOG.md): game-engine loop export, OpenMPT clipboard both ways, CLI export and collect,
computer-keyboard chord entry, continuous integration and the changelog, MIDI file import.
Done after 0.8.0 (CHANGELOG.md, Unreleased): command-line sections, checkpoints and phrase comparisons.

## Owner-declined proposals

DMO/plugin hosting, phrase generation, automatic composition and quality scores were declined;
they are recorded here to avoid proposing them again, not queued for implementation.
