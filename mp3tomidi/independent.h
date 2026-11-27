/* Independent zero-weight pure-DSP audio-to-MIDI transcriber (Checkpoint 3 Stage A).
 *
 * Pipeline:
 *   1. Tri-resolution STFT (8192 / 2048 / 1024 at 16 kHz, 20 ms hop) + 2D median HPSS
 *      with local tonal-peak floor subtraction (suppresses drums & resonant filter sweeps).
 *   2. Multi-pitch harmonic salience with fine-tuning peak search, subharmonic/odd-harmonic
 *      gating, and Klapuri-style iterative smooth-envelope harmonic subtraction.
 *   3. Per-pitch 2-state Viterbi HMM note tracking + flux-valley re-articulation splitting +
 *      neighbor-semitone deduplication and per-register polyphony limiting.
 *   4. Native-rate multi-band percussive drum transcription (HPSS + 4 bands: kick, snare
 *      body/snap, hats/crash) with cross-band bleed and tonal-note rejection.
 *   5. Adaptive register clustering + acoustic timbral GM patch assignment. */
#ifndef MP3TOMIDI_INDEPENDENT_H
#define MP3TOMIDI_INDEPENDENT_H

#include "midi.h"
#include <stddef.h>

struct independent_track {
    char *name;
    int program;
    int is_drum;
    struct midi_note *notes;
    size_t count;
};

struct independent_stats {
    size_t pitched_notes;
    size_t drum_hits;
    size_t kick_hits;
    size_t snare_hits;
    size_t hat_hits;
    size_t crash_hits;
    int split_bass_mid;
    int split_mid_high;
    double harmonic_ratio;
};

struct hybrid_stats {
    size_t dsp_candidates;
    size_t dettato_wrong_dropped;
    size_t bass_rescued;
    size_t mid_high_rescued;
    int rescue_tracks_added;
};

void independent_tracks_free(struct independent_track *tracks, size_t n_tracks);

/* Transcribe mono audio directly into named GM tracks + drums using zero neural weights.
 * - audio_native / n_native / native_rate: decoded mono audio at source sample rate.
 * - audio_retuned_16k / n_retuned_16k: 16 kHz mono audio retuned to A440.
 * - retune_ratio: time scaling ratio returned by retune_estimate (1.0 if unshifted).
 * Allocates *tracks_out (free with independent_tracks_free). Returns 1 on success, 0 on OOM. */
int independent_transcribe(const float *audio_native, size_t n_native, unsigned native_rate,
                           const float *audio_retuned_16k, size_t n_retuned_16k,
                           double retune_ratio,
                           struct independent_track **tracks_out, size_t *n_tracks_out,
                           struct independent_stats *stats);

/* Stage B hybrid acoustic rescue: fuse base Dettato tracks with our pure-DSP engine
 * (zero extra weights). Drops Dettato pitched notes that fail high-res HPSS peak checks
 * where DSP finds a strong verified pitch in the same register, and rescues prominent
 * sustained/bass lines that Dettato missed completely. Allocates *out_tracks. */
int independent_hybrid_fuse(const struct midi_track *base_tracks, size_t n_base_tracks,
                            const float *audio_retuned_16k, size_t n_retuned_16k,
                            double retune_ratio,
                            struct independent_track **out_tracks, size_t *n_out_tracks,
                            struct hybrid_stats *stats);

#endif
