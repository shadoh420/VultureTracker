/* High-quality arbitrary-ratio mono resampler (Kaiser-windowed sinc). */
#ifndef MP3TOMIDI_RESAMPLE_H
#define MP3TOMIDI_RESAMPLE_H

#include <stddef.h>

/* Resample `in` (in_len mono float32 samples at src_rate) to dst_rate.
 * Allocates `*out` (caller must free) and sets `*out_len`.
 * Returns 1 on success, 0 on invalid parameters or allocation failure. */
int resample_mono(const float *in, size_t in_len, double src_rate, double dst_rate,
                  float **out, size_t *out_len);

#endif
