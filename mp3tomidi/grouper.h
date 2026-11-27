/* Native port of Dettato's Instrument Grouper (dettato/grouper/). */
#ifndef MP3TOMIDI_GROUPER_H
#define MP3TOMIDI_GROUPER_H

#include "evidence.h"
#include "midi.h"
#include "transcribe.h"
#include "weights.h"
#include <stddef.h>

struct grouper_model;

struct grouped_track {
    const char *instrument; /* e.g. "piano", "electric_guitar" */
    int program;            /* GM program 0..127 */
    struct midi_note *notes;
    size_t count;
};

struct grouper_model *grouper_load(const struct vtwt_file *wf);
void grouper_free(struct grouper_model *m);
void grouped_tracks_free(struct grouped_track *tracks, size_t n_tracks);

/* Group repaired pitched notes into named GM instrument tracks.
 * - audio_y: retuned 16 kHz mono audio (n_y samples)
 * - tr: transcribe_run with sub_maps, sub_hidden_f16, sub_stem_f16 populated
 * - rep_notes: repaired notes on audio_y's time axis (will be mapped back by * retune_ratio)
 * Allocates *tracks_out (free with grouped_tracks_free). Returns 1 on success. */
int grouper_run(const struct grouper_model *m,
                const float *audio_y, size_t n_y,
                const struct transcribe_run *tr,
                const struct repaired_note *rep_notes, size_t n_rep,
                double retune_ratio,
                struct grouped_track **tracks_out, size_t *n_tracks_out);

#endif
