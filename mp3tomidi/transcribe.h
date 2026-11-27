/* Windowed Dettato transcriber runner + two-voice note decoder. */
#ifndef MP3TOMIDI_TRANSCRIBE_H
#define MP3TOMIDI_TRANSCRIBE_H

#include "lanenet.h"
#include <stddef.h>
#include <stdint.h>

enum {
    PITCH_LO = 21,
    HEAD_ONSET = 0,
    HEAD_FRAME = 1,
    HEAD_OFFSET = 2,
    HEAD_ONSET2 = 3,
    HEAD_FRAME2 = 4,
    HEAD_OFFSET2 = 5
};

struct vt_note {
    double onset;
    double offset;
    int pitch;
    float conf;
    int slot;   /* 1 or 2 */
};

struct transcribe_run {
    int T;
    float *maps;            /* [6, T, 88] float32 (head-major for clean indexing) */
    uint16_t *hidden_f16;   /* optional [T, 88, 368] float16 (for evidence repairer) */
    /* Sub-run (every other window, hop_frac=0.5) for grouper */
    float *sub_maps;        /* optional [6, T, 88] float32 */
    uint16_t *sub_hidden_f16;/* optional [T, 88, 368] float16 */
    uint16_t *sub_stem_f16; /* optional [T, 88, 368] float16 */
};

/* Run overlapping 8 s windows (hop_frac=0.25 -> every 2 s) over 16 kHz mono audio.
 * - want_hidden: capture main hidden tap (for evidence repairer)
 * - want_sub: capture sub-average (every 4 s: sub_maps, sub_hidden, sub_stem) for grouper
 * Returns 1 on success, 0 on failure. */
int transcribe_windows(const struct lanenet *net, const float *audio_16k, size_t n_samples,
                       int want_hidden, int want_sub, struct transcribe_run *out);

void transcribe_run_free(struct transcribe_run *r);

/* Decode two voices from maps [6, T, 88] using Dettato's default thresholds.
 * Allocates *notes_out (caller must free) and sets *count_out. Returns 1 on success. */
int transcribe_decode(const float *maps, int T, struct vt_note **notes_out, size_t *count_out);

/* Helper IEEE-754 float16 conversion for tap buffers. */
uint16_t vt_f32_to_f16(float x);
float vt_f16_to_f32(uint16_t h);

#endif
