/* Native port of Dettato's Evidence Repairer (dettato/evidence/). */
#ifndef MP3TOMIDI_EVIDENCE_H
#define MP3TOMIDI_EVIDENCE_H

#include "transcribe.h"
#include "weights.h"
#include <stddef.h>

struct evidence_model;

struct repaired_note {
    double onset;
    double offset;
    int pitch;
    int inserted;
    float score;
};

struct repair_info {
    size_t transcribed;
    size_t kept;
    size_t dropped;
    size_t inserted;
};

struct evidence_model *evidence_load(const struct vtwt_file *wf);
void evidence_free(struct evidence_model *m);

/* Run full evidence feature extraction + 8 s windowed Repairer + safe dedup.
 * Takes maps [6, T, 88] and hidden_f16 [T, 88, 368] from transcribe_windows().
 * Allocates *out_notes (caller must free). Returns 1 on success. */
int evidence_repair(const struct evidence_model *m,
                    const float *maps, const uint16_t *hidden_f16, int T,
                    const struct vt_note *raw_notes, size_t n_raw,
                    struct repaired_note **out_notes, size_t *out_count,
                    struct repair_info *info);

#endif
