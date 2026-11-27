/* Path A Checkpoint 2: acoustic verification, ghost/bleed pruning, register/envelope-aware
 * GM program refinement, and orthogonal audio-driven dynamics (CC7 + CC11 + vel + CC74). */
#ifndef MP3TOMIDI_ENHANCE_H
#define MP3TOMIDI_ENHANCE_H

#include "midi.h"
#include <stddef.h>

struct enhance_opts {
    int prune_ghosts;    /* 1 = drop cross-track dups, low-SNR ghosts, peripheral drum bleed */
    int refine_gm;       /* 1 = register/sustain/harmonicity GM program refinement */
    int audio_dynamics;  /* 1 = audio-driven velocities + CC7 balance + CC11 expression */
    int emit_cc74;       /* 1 = emit CC74 Brightness from smoothed spectral centroid */
};

struct enhance_track {
    char *name;
    int program;
    int is_drum;
    struct midi_note *notes;
    size_t count;
    struct midi_cc *ccs;
    size_t n_ccs;
};

struct enhance_stats {
    size_t pitched_in;
    size_t pitched_out;
    size_t dups_dropped;
    size_t ghosts_dropped;
    size_t tracks_dropped;
    size_t drums_in;
    size_t drums_out;
    size_t drum_bleed_dropped;
    size_t cc_events_total;
    int programs_refined;
};

void enhance_opts_default(struct enhance_opts *opts);
void enhance_tracks_free(struct enhance_track *tracks, size_t n_tracks);

/* Enhance transcribed tracks using the decoded native-rate and 16 kHz mono audio.
 * Does not modify `in_tracks`. Allocates `*out_tracks` (free with enhance_tracks_free).
 * Returns 1 on success, 0 on OOM/error. */
int enhance_tracks(const struct midi_track *in_tracks, size_t n_in_tracks,
                   const float *audio_native, size_t n_native, unsigned native_rate,
                   const float *audio_16k, size_t n_16k,
                   const struct enhance_opts *opts,
                   struct enhance_track **out_tracks, size_t *n_out_tracks,
                   struct enhance_stats *stats);

#endif
