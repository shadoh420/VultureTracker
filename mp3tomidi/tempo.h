/* Native tempo & 16th-note beat-grid estimator for mp3tomidi. */
#ifndef MP3TOMIDI_TEMPO_H
#define MP3TOMIDI_TEMPO_H

#include "midi.h"
#include <stddef.h>

struct tempo_info {
    double bpm;             /* Estimated BPM (120.0 fallback if unclear) */
    double initial_bpm;     /* Tempogram autocorrelation estimate before fold fit */
    double row0_s;          /* 16th-note grid phase offset in seconds */
    double clarity;         /* 16th-fold peak / mean (> 1.18 indicates clear pulse) */
    double worst_drift_ms;  /* Max residual stretch drift off steady grid */
    int is_steady;          /* 1 if clarity >= 1.18 and worst_drift_ms <= 10 ms */
};

/* Estimate tempo from 16 kHz mono audio and optional transcribed drum hits.
 * Returns 1 on success (falls back gracefully to 120.0 BPM on short/beatless audio). */
int tempo_estimate(const float *audio_16k, size_t n_16k,
                   const struct midi_note *drums, size_t n_drums,
                   struct tempo_info *out);

#endif
