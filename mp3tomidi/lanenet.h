/* Native implementation of Dettato's pitched-note transcriber (LaneNet). */
#ifndef MP3TOMIDI_LANENET_H
#define MP3TOMIDI_LANENET_H

#include "weights.h"

enum {
    LANE_C = 368,
    LANE_MID = 64,
    LANE_EXP = 736,
    LANE_KEYS = 88,
    LANE_HEADS = 6,
    LANE_GRU_H = 192,
    LANE_ATTN_HEADS = 8,
    LANE_ATTN_DIM = 46,
    LANE_PMIX = 14,
    LANE_DEPTH = 15,
    LANE_REFINE = 2
};

struct lanenet;

/* Load LaneNet weights from a VTWT archive. Returns NULL on failure. */
struct lanenet *lanenet_load(const struct vtwt_file *wf);
void lanenet_free(struct lanenet *net);

/* Run one window of 16 kHz mono audio (`samples` frames, e.g. 128000 for 8 s).
 * Output frame count is T = (samples / 160 + 1) / 2 (e.g. 400 for 128000 samples).
 * - logits_out: required, [T, 88, 6] float32 (onset, frame, offset, onset2, frame2, offset2)
 * - tap_stem_out: optional (may be NULL), [T, 88, 368] float32 (stem output on lanes 0..87)
 * - tap_hidden_out: optional (may be NULL), [T, 88, 368] float32 (head input on lanes 0..87)
 * Returns T on success, 0 on failure. */
int lanenet_forward(const struct lanenet *net, const float *audio_16k, int samples,
                    float *logits_out, float *tap_stem_out, float *tap_hidden_out);

#endif
