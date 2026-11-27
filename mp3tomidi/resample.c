/* Kaiser-windowed sinc resampler matching soxr HQ (~115 dB stopband, ~95% passband,
 * zero-phase alignment, output length llround(in_len * dst_rate / src_rate)). */
#include "resample.h"
#include <math.h>
#include <stdlib.h>
#include <string.h>

enum {
    SINC_WINGS = 92,
    SINC_OVER = 2048,
    SINC_TABLE_LEN = SINC_WINGS * SINC_OVER + 2
};

static const double PI = 3.14159265358979323846;
static const double KAISER_BETA = 12.5;   /* matches soxr HQ (~120 dB stopband) */
static const double ROLLOFF = 0.9565;     /* matches soxr HQ 91.3% passband / 100% stopband */

static float *g_sinc_table = NULL;

static double bessel_i0(double x) {
    double sum = 1.0;
    double term = 1.0;
    double half = 0.5 * x;
    double hh = half * half;
    for (int k = 1; k < 48; ++k) {
        term *= hh / ((double)k * (double)k);
        sum += term;
        if (term <= sum * 1e-16) break;
    }
    return sum;
}

static int ensure_sinc_table(void) {
    if (g_sinc_table) return 1;
    float *tbl = (float *)malloc((size_t)SINC_TABLE_LEN * sizeof(float));
    if (!tbl) return 0;
    double inv_i0 = 1.0 / bessel_i0(KAISER_BETA);
    for (int i = 0; i <= SINC_WINGS * SINC_OVER; ++i) {
        double u = (double)i / (double)SINC_OVER;
        double s = (i == 0) ? 1.0 : sin(PI * u) / (PI * u);
        double r = u / (double)SINC_WINGS;
        double arg = 1.0 - r * r;
        double w = arg > 0.0 ? bessel_i0(KAISER_BETA * sqrt(arg)) * inv_i0 : 0.0;
        tbl[i] = (float)(s * w);
    }
    tbl[SINC_WINGS * SINC_OVER + 1] = 0.0f;
    g_sinc_table = tbl;
    return 1;
}

int resample_mono(const float *in, size_t in_len, double src_rate, double dst_rate,
                  float **out, size_t *out_len) {
    if (!out || !out_len || src_rate <= 0.0 || dst_rate <= 0.0) return 0;
    *out = NULL;
    *out_len = 0;
    if (in_len == 0) return 1;
    if (!in) return 0;

    if (fabs(src_rate - dst_rate) <= 1e-12 * src_rate) {
        float *copy = (float *)malloc(in_len * sizeof(float));
        if (!copy) return 0;
        memcpy(copy, in, in_len * sizeof(float));
        *out = copy;
        *out_len = in_len;
        return 1;
    }

    if (!ensure_sinc_table()) return 0;

    double ratio = dst_rate / src_rate;
    long long n_out_ll = (long long)floor((double)in_len * ratio + 0.5);
    if (n_out_ll <= 0) return 1;
    size_t n_out = (size_t)n_out_ll;

    float *dst = (float *)malloc(n_out * sizeof(float));
    if (!dst) return 0;

    double scale = ratio < 1.0 ? ratio : 1.0;
    double gain = ROLLOFF * scale;
    double half_in = (double)SINC_WINGS / gain;
    double u_scale = gain * (double)SINC_OVER;
    double inv_ratio = src_rate / dst_rate;
    const float *tbl = g_sinc_table;
    const int max_idx = SINC_WINGS * SINC_OVER;
    const long long in_n = (long long)in_len;

    for (size_t j = 0; j < n_out; ++j) {
        double t = (double)j * inv_ratio;
        long long k_min = (long long)ceil(t - half_in);
        long long k_max = (long long)floor(t + half_in);
        if (k_min < 0) k_min = 0;
        if (k_max >= in_n) k_max = in_n - 1;

        long long k_mid = (long long)floor(t);
        if (k_mid < k_min - 1) k_mid = k_min - 1;
        if (k_mid > k_max) k_mid = k_max;

        double acc = 0.0;
        for (long long k = k_min; k <= k_mid; ++k) {
            double pos = (t - (double)k) * u_scale;
            int idx = (int)pos;
            if (idx < max_idx) {
                float frac = (float)(pos - (double)idx);
                float w = tbl[idx] + frac * (tbl[idx + 1] - tbl[idx]);
                acc += (double)in[k] * (double)w;
            }
        }
        for (long long k = k_mid + 1; k <= k_max; ++k) {
            double pos = ((double)k - t) * u_scale;
            int idx = (int)pos;
            if (idx < max_idx) {
                float frac = (float)(pos - (double)idx);
                float w = tbl[idx] + frac * (tbl[idx + 1] - tbl[idx]);
                acc += (double)in[k] * (double)w;
            }
        }
        dst[j] = (float)(acc * gain);
    }

    *out = dst;
    *out_len = n_out;
    return 1;
}
