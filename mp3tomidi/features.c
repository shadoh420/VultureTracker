/* Native implementation of the HCQT in Dettato's transcriber/frontend.py,
 * revision 51ade0f09f2272f4674166026582185d26baaeaf. See vendor/dettato/. */
#include "features.h"
#include <math.h>
#include <string.h>

enum { BINS = 288, LONG_FFT = 2048, SHORT_FFT = 512, HOP = 160 };
static const double tau = 6.2831853071795864769;

/* In-place radix-2 FFT, with real-valued input and zeroed imaginary parts. */
static void power_spectrum(const float *mono, int samples, int center, int size,
                           const double *window, double *power) {
    double real[LONG_FFT], imag[LONG_FFT] = {0};
    for (int i = 0, j = 0; i < size; ++i) {
        int src = center + i - size / 2;
        real[j] = src >= 0 && src < samples ? mono[src] * window[i] : 0;
        int bit = size / 2;
        while (bit && (j & bit)) { j ^= bit; bit >>= 1; }
        j ^= bit;
    }
    for (int span = 2; span <= size; span *= 2) {
        double step_r = cos(tau / span), step_i = -sin(tau / span);
        for (int start = 0; start < size; start += span) {
            double wr = 1, wi = 0;
            for (int j = start; j < start + span / 2; ++j) {
                int k = j + span / 2;
                double r = wr * real[k] - wi * imag[k], i = wi * real[k] + wr * imag[k];
                real[k] = real[j] - r; imag[k] = imag[j] - i;
                real[j] += r; imag[j] += i;
                double next_r = wr * step_r - wi * step_i;
                wi = wi * step_r + wr * step_i;
                wr = next_r;
            }
        }
    }
    for (int i = 0; i <= size / 2; ++i)
        power[i] = real[i] * real[i] + imag[i] * imag[i];
}

struct band { double center, radius, sum; int first, last; };

static double weight(const struct band *b, int bin) {
    return fmax(0, 1 - fabs(bin - b->center) / b->radius);
}

static void setup(int size, double *window, struct band *bank, int bins, int offset) {
    for (int i = 0; i < size; ++i) window[i] = 0.5 - 0.5 * cos(tau * i / size);
    double step = exp2(1.0 / 36);
    for (int i = 0; i < bins; ++i) {
        struct band *b = &bank[i];
        b->center = 27.5 * exp2((i + offset) / 36.0) * size / MODEL_RATE;
        b->radius = fmax(1, b->center * (step - 1 / step) / 2);
        b->first = (int)fmax(0, ceil(b->center - b->radius));
        b->last = (int)fmin(size / 2, floor(b->center + b->radius));
        b->sum = 0;
        for (int k = b->first; k <= b->last; ++k) b->sum += weight(b, k);
    }
}

static void filter(const double *power, const struct band *bank, int bins, float *out) {
    for (int i = 0; i < bins; ++i) {
        const struct band *b = &bank[i];
        double value = 0;
        for (int k = b->first; k <= b->last; ++k) value += weight(b, k) * power[k];
        out[i] = (float)log(1e-5 + (b->sum ? value / b->sum : 0));
    }
}

int write_features(FILE *out, const float *mono, int samples) {
    /* round(36 * log2(h)) for h = 0.5, 1, 2, 3, 4, 5, 6, 7. */
    static const int shifts[] = {-36, 0, 36, 57, 72, 84, 93, 101};
    enum { EXTENDED = BINS + 101 + 36 };
    double long_window[LONG_FFT], short_window[SHORT_FFT], power[LONG_FFT / 2 + 1];
    struct band long_bank[EXTENDED], short_bank[BINS];
    float bands[EXTENDED], short_bands[BINS];
    setup(LONG_FFT, long_window, long_bank, EXTENDED, shifts[0]);
    setup(SHORT_FFT, short_window, short_bank, BINS, 0);
    for (int frame = 0; frame < samples / HOP; ++frame) {
        power_spectrum(mono, samples, frame * HOP, LONG_FFT, long_window, power);
        filter(power, long_bank, EXTENDED, bands);
        for (int h = 0; h < 8; ++h)
            if (fwrite(bands + (shifts[h] - shifts[0]), sizeof(float), BINS, out) != BINS) return 0;
        power_spectrum(mono, samples, frame * HOP, SHORT_FFT, short_window, power);
        filter(power, short_bank, BINS, short_bands);
        if (fwrite(short_bands, sizeof(float), BINS, out) != BINS) return 0;
    }
    return 1;
}

int compute_hcqt_nhwc(const float *mono, int samples, float *out) {
    static const int shifts[] = {-36, 0, 36, 57, 72, 84, 93, 101};
    enum { EXTENDED = BINS + 101 + 36 };
    double long_window[LONG_FFT], short_window[SHORT_FFT], power[LONG_FFT / 2 + 1];
    struct band long_bank[EXTENDED], short_bank[BINS];
    float bands[EXTENDED], short_bands[BINS];
    setup(LONG_FFT, long_window, long_bank, EXTENDED, shifts[0]);
    setup(SHORT_FFT, short_window, short_bank, BINS, 0);
    int n_frames = samples / HOP;
    for (int frame = 0; frame < n_frames; ++frame) {
        power_spectrum(mono, samples, frame * HOP, LONG_FFT, long_window, power);
        filter(power, long_bank, EXTENDED, bands);
        power_spectrum(mono, samples, frame * HOP, SHORT_FFT, short_window, power);
        filter(power, short_bank, BINS, short_bands);
        float *dst = out + (size_t)frame * BINS * HCQT_CHANNELS;
        for (int b = 0; b < BINS; ++b) {
            float *p = dst + b * HCQT_CHANNELS;
            for (int h = 0; h < 8; ++h)
                p[h] = bands[(shifts[h] - shifts[0]) + b];
            p[8] = short_bands[b];
        }
    }
    return n_frames;
}

int compute_hcqt_with_power(const float *mono, int samples, float *X_ct_f, float *P_ne_t) {
    static const int shifts[] = {-36, 0, 36, 57, 72, 84, 93, 101};
    enum { EXTENDED = BINS + 101 + 36 };
    double long_window[LONG_FFT], short_window[SHORT_FFT], power[LONG_FFT / 2 + 1];
    struct band long_bank[EXTENDED], short_bank[BINS];
    float short_bands[BINS];
    setup(LONG_FFT, long_window, long_bank, EXTENDED, shifts[0]);
    setup(SHORT_FFT, short_window, short_bank, BINS, 0);
    int n_frames = samples / HOP;
    for (int frame = 0; frame < n_frames; ++frame) {
        power_spectrum(mono, samples, frame * HOP, LONG_FFT, long_window, power);
        float lf[EXTENDED];
        for (int i = 0; i < EXTENDED; ++i) {
            const struct band *b = &long_bank[i];
            double val = 0.0;
            for (int k = b->first; k <= b->last; ++k) val += weight(b, k) * power[k];
            double lin = b->sum ? val / b->sum : 0.0;
            P_ne_t[(size_t)i * (size_t)n_frames + (size_t)frame] = (float)lin;
            lf[i] = (float)log(1e-5 + lin);
        }
        for (int h = 0; h < 8; ++h) {
            float *dst = X_ct_f + ((size_t)h * (size_t)n_frames + (size_t)frame) * BINS;
            memcpy(dst, lf + (shifts[h] - shifts[0]), BINS * sizeof(float));
        }
        power_spectrum(mono, samples, frame * HOP, SHORT_FFT, short_window, power);
        filter(power, short_bank, BINS, short_bands);
        memcpy(X_ct_f + ((size_t)8 * (size_t)n_frames + (size_t)frame) * BINS,
               short_bands, BINS * sizeof(float));
    }
    return n_frames;
}
