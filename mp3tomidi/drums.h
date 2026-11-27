/* Native port of Dettato's Drum Transcriber (dettato/drums/). */
#ifndef MP3TOMIDI_DRUMS_H
#define MP3TOMIDI_DRUMS_H

#include "midi.h"
#include "weights.h"
#include <stddef.h>

enum { DRUMS_MIN_SOURCE_RATE = 40000 };

struct drums_model;

struct drums_info {
    double router;
    int used_orchestral;
    size_t hits;
};

struct drums_model *drums_load(const struct vtwt_file *wf);
void drums_free(struct drums_model *m);

/* Transcribe drum hits from native mono audio (requires source_rate >= 40000).
 * Internally resamples to 44100 Hz if needed.
 * Allocates *notes_out (caller must free) with onset, offset=onset+0.1, GM pitch, vel 1..127.
 * Returns 1 on success, 0 on failure. */
int drums_transcribe(const struct drums_model *m,
                     const float *audio_native, size_t n_frames, unsigned source_rate,
                     struct midi_note **notes_out, size_t *count_out,
                     struct drums_info *info);

#endif
