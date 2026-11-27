/* Native port of Dettato's grouper/retune.py, revision 51ade0f09f2272f4674166026582185d26baaeaf. */
#include "retune.h"
#include "resample.h"
#include <math.h>
#include <stdlib.h>
#include <string.h>

enum {
    RT_SR = 16000,
    RT_NFFT = 8192,
    RT_HOP = 1024,
    RT_HARM = 6
};

static const double RT_TAU = 6.2831853071795864769;
static const double RT_FMIN = 65.0;
static const double RT_FMAX = 1000.0;
static const double RT_STEP_C = 5.0;
static const double RT_REL = 0.5;
static const double RT_MIN_CENTS = 10.0;
static const double RT_MIN_STRENGTH = 0.12;

static void rfft_sqrt_mag_8192(const float *frame, const float *win,
                               double *re, double *im, float *mag_sqrt) {
    /* Bit-reversed copy of windowed input */
    for (int i = 0, j = 0; i < RT_NFFT; ++i) {
        re[j] = (double)frame[i] * (double)win[i];
        im[j] = 0.0;
        int bit = RT_NFFT >> 1;
        while (bit && (j & bit)) { j ^= bit; bit >>= 1; }
        j ^= bit;
    }
    for (int span = 2; span <= RT_NFFT; span <<= 1) {
        double step_r = cos(RT_TAU / span);
        double step_i = -sin(RT_TAU / span);
        int half = span >> 1;
        for (int start = 0; start < RT_NFFT; start += span) {
            double wr = 1.0, wi = 0.0;
            for (int j = start; j < start + half; ++j) {
                int k = j + half;
                double r = wr * re[k] - wi * im[k];
                double ii = wi * re[k] + wr * im[k];
                re[k] = re[j] - r;
                im[k] = im[j] - ii;
                re[j] += r;
                im[j] += ii;
                double nr = wr * step_r - wi * step_i;
                wi = wi * step_r + wr * step_i;
                wr = nr;
            }
        }
    }
    for (int i = 0; i <= RT_NFFT / 2; ++i)
        mag_sqrt[i] = sqrtf((float)hypot(re[i], im[i]));
}

void retune_estimate(const float *y, size_t n, struct retune_info *out) {
    out->delta_cents = 0.0;
    out->strength = 0.0;
    out->shift_cents = 0.0;
    out->ratio = 1.0;
    if (!y || n < RT_NFFT) return;

    int nfr = 1 + (int)((n - RT_NFFT) / RT_HOP);
    double c_lo = 1200.0 * log2(RT_FMIN / 440.0);
    double c_hi = 1200.0 * log2(RT_FMAX / 440.0);
    int n_cents = (int)ceil((c_hi - c_lo) / RT_STEP_C);
    if (n_cents < 3) return;

    float *win = (float *)malloc(RT_NFFT * sizeof(float));
    double *cents = (double *)malloc((size_t)n_cents * sizeof(double));
    double *f0 = (double *)malloc((size_t)n_cents * sizeof(double));
    double *re = (double *)malloc(RT_NFFT * sizeof(double));
    double *im = (double *)malloc(RT_NFFT * sizeof(double));
    float *mag = (float *)malloc((RT_NFFT / 2 + 1) * sizeof(float));
    float *sal = (float *)malloc((size_t)n_cents * sizeof(float));
    if (!win || !cents || !f0 || !re || !im || !mag || !sal) goto cleanup;

    /* np.hanning(n_fft) is symmetric: denom = n_fft - 1 */
    for (int i = 0; i < RT_NFFT; ++i)
        win[i] = (float)(0.5 - 0.5 * cos(RT_TAU * (double)i / (double)(RT_NFFT - 1)));
    for (int i = 0; i < n_cents; ++i) {
        cents[i] = c_lo + (double)i * RT_STEP_C;
        f0[i] = 440.0 * exp2(cents[i] / 1200.0);
    }

    int nb = RT_NFFT / 2 + 1;
    double harm_w[RT_HARM];
    for (int h = 0; h < RT_HARM; ++h) harm_w[h] = pow(0.85, (double)h);

    double zr = 0.0, zi = 0.0, wsum = 0.0;
    for (int f = 0; f < nfr; ++f) {
        rfft_sqrt_mag_8192(y + (size_t)f * RT_HOP, win, re, im, mag);
        float mx = 0.0f;
        for (int i = 0; i < n_cents; ++i) {
            float s = 0.0f;
            for (int h = 1; h <= RT_HARM; ++h) {
                double fb = (double)h * f0[i] * (double)RT_NFFT / (double)RT_SR;
                if (fb < (double)(nb - 2)) {
                    int i0 = (int)floor(fb);
                    float frac = (float)(fb - (double)i0);
                    s += (float)harm_w[h - 1] * ((1.0f - frac) * mag[i0] + frac * mag[i0 + 1]);
                }
            }
            sal[i] = s;
            if (s > mx) mx = s;
        }
        if (mx <= 0.0f) continue;
        float thresh = (float)RT_REL * mx;
        for (int j = 0; j < n_cents - 2; ++j) {
            float a = sal[j], b = sal[j + 1], c = sal[j + 2];
            if (b > a && b >= c && b > thresh) {
                double d = 0.5 * ((double)a - (double)c) / ((double)a - 2.0 * (double)b + (double)c - 1e-12);
                if (d < -1.0) d = -1.0;
                if (d > 1.0) d = 1.0;
                double cv = cents[j + 1] + d * RT_STEP_C + 50.0;
                cv = cv - 100.0 * floor(cv / 100.0) - 50.0;
                double ang = RT_TAU * cv / 100.0;
                zr += (double)b * cos(ang);
                zi += (double)b * sin(ang);
                wsum += (double)b;
            }
        }
    }

    if (wsum > 0.0) {
        zr /= wsum;
        zi /= wsum;
        double delta = atan2(zi, zr) * 100.0 / RT_TAU;
        double strength = hypot(zr, zi);
        out->delta_cents = delta;
        out->strength = strength;
        if (fabs(delta) >= RT_MIN_CENTS && strength >= RT_MIN_STRENGTH) {
            out->shift_cents = -delta;
            out->ratio = exp2(out->shift_cents / 1200.0);
        }
    }

cleanup:
    free(win); free(cents); free(f0); free(re); free(im); free(mag); free(sal);
}

int retune_apply(const float *y, size_t n, const struct retune_info *info,
                 float **out_y, size_t *out_n) {
    if (!info || info->ratio == 1.0) {
        float *copy = (float *)malloc(n * sizeof(float));
        if (!copy && n > 0) return 0;
        if (n > 0) memcpy(copy, y, n * sizeof(float));
        *out_y = copy;
        *out_n = n;
        return 1;
    }
    return resample_mono(y, n, (double)RT_SR, (double)RT_SR / info->ratio, out_y, out_n);
}
