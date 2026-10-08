# VultureTracker backlog

Historical (closed with 0.7.0, 2026-09-30): the focused 0.7.0 scope was fixes for the 22 reproduced audit defects, bounded history,
recording alongside playback, MIDI chord capture, conversion to editable literal patterns,
configurable beat spacing, and shared phrase-sample storage.

## Deferred proposals

- **Guitar Pro tab view, fretboard entry and GPX support.** Add a read-only tab view first, then fretboard editing and GPX import alongside the existing importer. Source: `suite/HANDOFF.md` Guitar Pro backlog and `vulturetracker/gpimport.py`; deferred because round-trip editing needs a richer model than imported cells.
- **Game-loop target engine.** 0.8.0 marks a loop by the export format (WAV `smpl` chunk, OGG/FLAC `LOOPSTART`/`LOOPLENGTH`; MP3 and IT refuse a loop). Whether to target a particular engine or middleware (its own loop metadata, a sidecar file) is deferred by the owner. Source: `vulturetracker/export.py` and `gui._encode`.

Done in 0.8.0 (CHANGELOG.md): game-engine loop export, OpenMPT clipboard both ways, CLI export and collect,
computer-keyboard chord entry, continuous integration and the changelog, MIDI file import.
Done in 0.9.0 (CHANGELOG.md): command-line sections, checkpoints and phrase comparisons.
Done since (CHANGELOG.md, Unreleased): Faust polyphony, MIDI and the live node.

## Owner-declined proposals

Phrase generation, automatic composition and quality scores were declined (2026-09-25); they are recorded here to
avoid proposing them again, not queued for implementation. DMO/plugin hosting was declined the same day, reversed on
2026-10-07 and shipped in 1.3.0 (mix plugins and the RACK tab, CHANGELOG.md).
