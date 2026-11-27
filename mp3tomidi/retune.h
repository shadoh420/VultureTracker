/* Native port of Dettato's grouper/retune.py (A440 tuning estimation + retuning). */
#ifndef MP3TOMIDI_RETUNE_H
#define MP3TOMIDI_RETUNE_H

#include <stddef.h>

struct retune_info {
    double delta_cents;     /* estimated offset from A440 in [-50, 50) */
    double strength;        /* circular mean resultant length in [0, 1] */
    double shift_cents;     /* applied shift (-delta_cents if triggered, else 0) */
    double ratio;           /* 2^(shift_cents / 1200), 1.0 when unshifted */
};

/* Estimate tuning offset on 16 kHz mono audio y[0..n-1]. */
void retune_estimate(const float *y, size_t n, struct retune_info *out);

/* Apply retuning if info->ratio != 1.0 (allocates *out_y; caller must free).
 * If unshifted, still allocates a copy of y so caller owns *out_y uniformly.
 * Returns 1 on success, 0 on OOM. */
int retune_apply(const float *y, size_t n, const struct retune_info *info,
                 float **out_y, size_t *out_n);

#endif
