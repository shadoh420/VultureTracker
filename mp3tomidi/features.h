/* Dettato's pitched-note model consumes nine 288-bin channels per 10 ms frame. */
#ifndef MP3TOMIDI_FEATURES_H
#define MP3TOMIDI_FEATURES_H
#include <stdio.h>

enum {
    MODEL_RATE = 16000,
    WINDOW_SAMPLES = 8 * MODEL_RATE,
    HCQT_HOP = 160,
    HCQT_BINS = 288,
    HCQT_CHANNELS = 9,
    HCQT_EXTENDED = 288 + 101 + 36 /* 425 */
};

int write_features(FILE *out, const float *mono, int samples);
/* Compute HCQT in channels-last NHWC layout: out[(frame * 288 + bin) * 9 + ch]
 * for frame in 0 .. (samples / 160) - 1. Returns frame count. */
int compute_hcqt_nhwc(const float *mono, int samples, float *out);
/* Compute HCQT log-power X_ct_f[ch, frame, bin] (9 x T x 288) and linear extended
 * power P_ne_t[bin, frame] (425 x T) for the grouper's Front. Returns frame count T. */
int compute_hcqt_with_power(const float *mono, int samples, float *X_ct_f, float *P_ne_t);
#endif
