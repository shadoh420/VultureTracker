/* Independent zero-weight pure-DSP audio-to-MIDI transcriber (Checkpoint 3 Stage A). */
#include "independent.h"
#include "nn.h"
#include <math.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

enum {
    IND_SR16 = 16000,
    IND_HOP16 = 320,      /* 20 ms hop (50 fps) for pitched analysis */
    IND_NFFT_LO = 8192,   /* 1.953 Hz bins (512 ms Hann) for bass & low harmonics */
    IND_NFFT_MD = 2048,   /* 7.8125 Hz bins (128 ms Hann) for mids & harmonics */
    IND_NFFT_HI = 1024,   /* 15.625 Hz bins (64 ms Hann) for high notes & fast arps */
    IND_NB_LO = 640,      /* 0..1250 Hz in 8192-pt FFT */
    IND_NB_MD = 768,      /* 0..6000 Hz in 2048-pt FFT */
    IND_NB_HI = 480,      /* 0..7500 Hz in 1024-pt FFT */
    IND_P_LO = 24,        /* C1 (32.70 Hz) */
    IND_P_HI = 96,        /* C7 (2093.0 Hz) */
    IND_NP = 73,          /* IND_P_HI - IND_P_LO + 1 */
    IND_MAX_VOICES = 8,   /* Max iterative polyphonic picks per frame */
    IND_MAX_HARM = 8      /* Harmonics summed in salience */
};

static const double IND_TAU = 6.2831853071795864769;

static int clamp_i(int v, int lo, int hi) {
    return v < lo ? lo : (v > hi ? hi : v);
}

static double clamp_d(double v, double lo, double hi) {
    return v < lo ? lo : (v > hi ? hi : v);
}

static char *ind_dup_str(const char *s) {
    size_t len = strlen(s);
    char *p = (char *)malloc(len + 1);
    if (p) memcpy(p, s, len + 1);
    return p;
}

static int cmp_double(const void *pa, const void *pb) {
    double a = *(const double *)pa, b = *(const double *)pb;
    return (a > b) - (a < b);
}

static double ind_percentile(const double *arr, size_t n, double q) {
    if (!n) return 0.0;
    double *tmp = (double *)malloc(n * sizeof(double));
    if (!tmp) return arr[0];
    memcpy(tmp, arr, n * sizeof(double));
    qsort(tmp, n, sizeof(double), cmp_double);
    double idx = q * (double)(n - 1);
    size_t i0 = (size_t)floor(idx);
    size_t i1 = (i0 + 1 < n) ? (i0 + 1) : (n - 1);
    double f = idx - (double)i0;
    double v = tmp[i0] * (1.0 - f) + tmp[i1] * f;
    free(tmp);
    return v;
}

static float median_small_f(float *buf, int n) {
    /* Insertion sort on tiny stack buffer (n <= 31): deterministic and fast. */
    for (int i = 1; i < n; ++i) {
        float key = buf[i];
        int j = i - 1;
        while (j >= 0 && buf[j] > key) {
            buf[j + 1] = buf[j];
            --j;
        }
        buf[j + 1] = key;
    }
    return buf[n / 2];
}

static double median_small_d(double *buf, int n) {
    for (int i = 1; i < n; ++i) {
        double key = buf[i];
        int j = i - 1;
        while (j >= 0 && buf[j] > key) {
            buf[j + 1] = buf[j];
            --j;
        }
        buf[j + 1] = key;
    }
    return buf[n / 2];
}

static double ind_a_weight_db(double f) {
    if (f < 10.0) f = 10.0;
    double f2 = f * f;
    double c1 = 12194.0 * 12194.0;
    double c2 = 20.6 * 20.6;
    double c3 = 107.7 * 107.7;
    double c4 = 737.9 * 737.9;
    double num = c1 * f2 * f2;
    double den = (f2 + c2) * sqrt((f2 + c3) * (f2 + c4)) * (f2 + c1);
    double ra = num / (den > 1e-30 ? den : 1e-30);
    return 20.0 * log10(ra > 1e-12 ? ra : 1e-12) + 2.0;
}

static void ind_fft_f64(double *re, double *im, int n) {
    for (int i = 1, j = 0; i < n; ++i) {
        int bit = n >> 1;
        while (j & bit) { j ^= bit; bit >>= 1; }
        j ^= bit;
        if (i < j) {
            double tr = re[i]; re[i] = re[j]; re[j] = tr;
            double ti = im[i]; im[i] = im[j]; im[j] = ti;
        }
    }
    for (int span = 2; span <= n; span <<= 1) {
        double ang = -IND_TAU / (double)span;
        double sr = cos(ang), si = sin(ang);
        int half = span >> 1;
        for (int start = 0; start < n; start += span) {
            double wr = 1.0, wi = 0.0;
            for (int j = start; j < start + half; ++j) {
                int k = j + half;
                double r = wr * re[k] - wi * im[k];
                double ii = wi * re[k] + wr * im[k];
                re[k] = re[j] - r; im[k] = im[j] - ii;
                re[j] += r; im[j] += ii;
                double nr = wr * sr - wi * si;
                wi = wi * sr + wr * si;
                wr = nr;
            }
        }
    }
}

void independent_tracks_free(struct independent_track *tracks, size_t n_tracks) {
    if (!tracks) return;
    for (size_t i = 0; i < n_tracks; ++i) {
        free(tracks[i].name);
        free(tracks[i].notes);
    }
    free(tracks);
}

/* =========================================================================
 * Stage 1: Tri-Resolution STFT & 2D Median HPSS (16 kHz, 20 ms hop)
 * ========================================================================= */

struct stft_ctx {
    const float *x;
    size_t n_x;
    int T;
    int hop;
    int nfft;
    int nb;
    const double *win;
    double norm;
    float *mag; /* [T, nb] */
};

static void stft_worker(int start, int end, void *arg) {
    const struct stft_ctx *c = (const struct stft_ctx *)arg;
    double *re = (double *)malloc((size_t)c->nfft * sizeof(double));
    double *im = (double *)malloc((size_t)c->nfft * sizeof(double));
    if (!re || !im) { free(re); free(im); return; }

    int half = c->nfft / 2;
    for (int t = start; t < end; ++t) {
        int center = t * c->hop;
        for (int i = 0; i < c->nfft; ++i) {
            int idx = center + i - half;
            re[i] = (idx >= 0 && (size_t)idx < c->n_x) ? (double)c->x[idx] * c->win[i] : 0.0;
            im[i] = 0.0;
        }
        ind_fft_f64(re, im, c->nfft);
        float *row = c->mag + (size_t)t * (size_t)c->nb;
        for (int k = 0; k < c->nb; ++k) {
            row[k] = (float)(hypot(re[k], im[k]) * c->norm);
        }
    }
    free(re);
    free(im);
}

static int compute_mag_stft(const float *x, size_t n_x, int T, int hop,
                            int nfft, int nb, float **mag_out) {
    *mag_out = (float *)malloc((size_t)T * (size_t)nb * sizeof(float));
    double *win = (double *)malloc((size_t)nfft * sizeof(double));
    if (!*mag_out || !win) { free(*mag_out); *mag_out = NULL; free(win); return 0; }

    double wsum = 0.0;
    for (int i = 0; i < nfft; ++i) {
        win[i] = 0.5 - 0.5 * cos(IND_TAU * (double)i / (double)(nfft - 1));
        wsum += win[i];
    }
    struct stft_ctx ctx = { x, n_x, T, hop, nfft, nb, win, 2.0 / wsum, *mag_out };
    int grain = (nfft >= 4096) ? 16 : 64;
    nn_parallel_for(T, grain, stft_worker, &ctx);
    free(win);
    return 1;
}

struct hpss_ctx {
    const float *mag; /* [T, nb] */
    float *harm;      /* [T, nb] (may be NULL) */
    float *perc;      /* [T, nb] (may be NULL) */
    float *tonal;     /* [T, nb] harmonic with local broadband floor removed (may be NULL) */
    double *h_e;      /* [T] optional per-frame harmonic power */
    double *p_e;      /* [T] optional per-frame percussive power */
    int T;
    int nb;
    int lt;
    int lf;
    float beta;
    float floor_sub;  /* fraction of p_med subtracted for tonal-peak enhancement */
};

static void hpss_worker(int start, int end, void *arg) {
    const struct hpss_ctx *c = (const struct hpss_ctx *)arg;
    float tbuf[31], fbuf[31];
    int lt = c->lt > 15 ? 15 : c->lt;
    int lf = c->lf > 15 ? 15 : c->lf;

    for (int t = start; t < end; ++t) {
        const float *row = c->mag + (size_t)t * (size_t)c->nb;
        float *hrow = c->harm ? (c->harm + (size_t)t * (size_t)c->nb) : NULL;
        float *prow = c->perc ? (c->perc + (size_t)t * (size_t)c->nb) : NULL;
        float *trow = c->tonal ? (c->tonal + (size_t)t * (size_t)c->nb) : NULL;
        double he = 0.0, pe = 0.0;

        int ta = t - lt > 0 ? t - lt : 0;
        int tb = t + lt < c->T ? t + lt : c->T - 1;

        for (int k = 0; k < c->nb; ++k) {
            /* Temporal median (harmonic structure) */
            int nt = 0;
            for (int tt = ta; tt <= tb; ++tt)
                tbuf[nt++] = c->mag[(size_t)tt * (size_t)c->nb + (size_t)k];
            float hm = median_small_f(tbuf, nt);

            /* Frequency median (percussive / broadband structure) */
            int ka = k - lf > 0 ? k - lf : 0;
            int kb = k + lf < c->nb ? k + lf : c->nb - 1;
            int nf = 0;
            for (int kk = ka; kk <= kb; ++kk) fbuf[nf++] = row[kk];
            float pm = median_small_f(fbuf, nf);

            float hp = hm * hm;
            float pp = (c->beta * pm) * (c->beta * pm);
            float wh = hp / (hp + pp + 1e-18f);
            float m = row[k];
            float hv = wh * m;
            float pv = (1.0f - wh) * m;

            if (hrow) hrow[k] = hv;
            if (prow) prow[k] = pv;
            if (c->h_e) he += (double)hv * (double)hv;
            if (c->p_e) pe += (double)pv * (double)pv;
        }
        if (trow) {
            /* Subtract local HARMONIC broadband floor (freq median of hrow, NOT raw percussive pm!)
             * so filter sweeps & static wash vanish while transient drum hits (kicks/snares/hats)
             * never punch holes into sustained mid-register chord tones. */
            const float *src = hrow ? hrow : row;
            for (int k = 0; k < c->nb; ++k) {
                int ka = k - lf > 0 ? k - lf : 0;
                int kb = k + lf < c->nb ? k + lf : c->nb - 1;
                int nf = 0;
                for (int kk = ka; kk <= kb; ++kk) fbuf[nf++] = src[kk];
                float hpm = median_small_f(fbuf, nf);
                float tv = src[k] - c->floor_sub * hpm;
                trow[k] = tv > 0.0f ? tv : 0.0f;
            }
        }
        if (c->h_e) c->h_e[t] = he;
        if (c->p_e) c->p_e[t] = pe;
    }
}

/* =========================================================================
 * Stage 2: Multi-Pitch Salience & Iterative Smooth-Envelope Cancellation
 * ========================================================================= */

/* Sample local peak magnitude near frequency `hz` from a residual spectrum. */
static float sample_spec_peak(const float *r, int nfft, int nb, double hz,
                              double *exact_bin_out) {
    double c = hz * (double)nfft / (double)IND_SR16;
    if (c < 1.0 || c >= (double)(nb - 2)) {
        if (exact_bin_out) *exact_bin_out = c;
        return 0.0f;
    }
    /* Search +-max(1, 28 cents) clamped to +-2 bins */
    double rad = c * 0.0165;
    if (rad < 1.0) rad = 1.0;
    if (rad > 2.2) rad = 2.2;
    int k0 = (int)floor(c - rad);
    int k1 = (int)ceil(c + rad);
    if (k0 < 1) k0 = 1;
    if (k1 > nb - 2) k1 = nb - 2;

    int best_k = (int)floor(c + 0.5);
    if (best_k < k0) best_k = k0;
    if (best_k > k1) best_k = k1;
    float best_v = r[best_k];
    for (int k = k0; k <= k1; ++k) {
        if (r[k] > best_v) {
            best_v = r[k];
            best_k = k;
        }
    }
    /* Parabolic peak refinement when at a strict local maximum */
    double ek = (double)best_k;
    if (best_k > 1 && best_k < nb - 2 && r[best_k] >= r[best_k - 1] && r[best_k] >= r[best_k + 1]) {
        double a = (double)r[best_k - 1], b = (double)r[best_k], d = (double)r[best_k + 1];
        double den = a - 2.0 * b + d;
        if (den < -1e-12) {
            double off = 0.5 * (a - d) / den;
            if (off > -0.5 && off < 0.5) ek += off;
        }
    }
    if (exact_bin_out) *exact_bin_out = ek;
    return best_v;
}

/* Exact-bin linearly interpolated magnitude at `hz` (zero neighbor-semitone grabbing). */
static float sample_spec_at(const float *r, int nfft, int nb, double hz) {
    double c = hz * (double)nfft / (double)IND_SR16;
    if (c < 1.0 || c >= (double)(nb - 1)) return 0.0f;
    int k0 = (int)floor(c);
    int k1 = k0 + 1;
    if (k1 >= nb) k1 = nb - 1;
    double f = c - (double)k0;
    return (float)((1.0 - f) * (double)r[k0] + f * (double)r[k1]);
}

/* Sample local noise/neighborhood background around `hz` (median of +-4..6 semitones or +-8 bins). */
static float sample_spec_bg(const float *r, int nfft, int nb, double hz) {
    double c = hz * (double)nfft / (double)IND_SR16;
    int ic = (int)floor(c + 0.5);
    if (ic < 2 || ic >= nb - 2) return 0.0f;
    float vals[16];
    int n = 0;
    int step = (int)floor(c * 0.06 + 0.5);
    if (step < 3) step = 3;
    if (step > 14) step = 14;
    static const int mults[8] = { -4, -3, -2, -1, 1, 2, 3, 4 };
    for (int i = 0; i < 8; ++i) {
        int k = ic + mults[i] * step;
        if (k >= 1 && k < nb - 1) vals[n++] = r[k];
    }
    return n > 0 ? median_small_f(vals, n) : 0.0f;
}

/* Hann window main lobe shape for clean partial cancellation (|d| < 2.5 bins). */
static float hann_lobe(double d) {
    double ad = fabs(d);
    if (ad < 1e-4) return 1.0f;
    if (ad >= 2.3) return 0.0f;
    if (fabs(ad - 1.0) < 1e-4) return 0.5f;
    if (fabs(ad - 2.0) < 1e-4) return 0.0f;
    double pi_d = 3.14159265358979323846 * ad;
    double v = sin(pi_d) / (pi_d * (1.0 - ad * ad));
    return v > 0.0 ? (float)v : 0.0f;
}

static void subtract_partial(float *r, int nfft, int nb, double hz, float sub_amp) {
    if (sub_amp <= 0.0f) return;
    double c = hz * (double)nfft / (double)IND_SR16;
    if (c < 1.0 || c >= (double)(nb - 1)) return;
    /* Snap subtraction center to local peak within +-1.2 bins so phase/vibrato cancels cleanly */
    int k0 = (int)floor(c - 1.2);
    int k1 = (int)ceil(c + 1.2);
    if (k0 < 1) k0 = 1;
    if (k1 > nb - 2) k1 = nb - 2;
    int pk = clamp_i((int)floor(c + 0.5), k0, k1);
    for (int k = k0; k <= k1; ++k) if (r[k] > r[pk]) pk = k;
    double center = (double)pk;
    if (pk > 1 && pk < nb - 2 && r[pk] >= r[pk - 1] && r[pk] >= r[pk + 1]) {
        double a = r[pk - 1], b = r[pk], d = r[pk + 1];
        double den = a - 2.0 * b + d;
        if (den < -1e-12) {
            double off = 0.5 * (a - d) / den;
            if (off > -0.5 && off < 0.5) center += off;
        }
    }
    int sa = (int)floor(center - 2.3);
    int sb = (int)ceil(center + 2.3);
    if (sa < 0) sa = 0;
    if (sb >= nb) sb = nb - 1;
    for (int k = sa; k <= sb; ++k) {
        float w = hann_lobe((double)k - center);
        float nv = r[k] - sub_amp * w;
        r[k] = nv > 0.0f ? nv : 0.0f;
    }
}

/* Read magnitude at `hz` from the best-resolution residual spectrogram. */
static float read_best_res(const float *r_lo, const float *r_md, const float *r_hi,
                           double hz, double *exact_hz_out) {
    double eb = 0.0;
    float v;
    if (hz < 285.0) {
        v = sample_spec_peak(r_lo, IND_NFFT_LO, IND_NB_LO, hz, &eb);
        if (exact_hz_out) *exact_hz_out = eb * (double)IND_SR16 / (double)IND_NFFT_LO;
    } else if (hz < 1500.0) {
        v = sample_spec_peak(r_md, IND_NFFT_MD, IND_NB_MD, hz, &eb);
        if (exact_hz_out) *exact_hz_out = eb * (double)IND_SR16 / (double)IND_NFFT_MD;
    } else {
        v = sample_spec_peak(r_hi, IND_NFFT_HI, IND_NB_HI, hz, &eb);
        if (exact_hz_out) *exact_hz_out = eb * (double)IND_SR16 / (double)IND_NFFT_HI;
    }
    return v;
}

static float read_best_bg(const float *r_lo, const float *r_md, const float *r_hi, double hz) {
    if (hz < 285.0) return sample_spec_bg(r_lo, IND_NFFT_LO, IND_NB_LO, hz);
    if (hz < 1500.0) return sample_spec_bg(r_md, IND_NFFT_MD, IND_NB_MD, hz);
    return sample_spec_bg(r_hi, IND_NFFT_HI, IND_NB_HI, hz);
}

/* Narrowband peak-to-shoulder sharpness on raw HPSS harmonic spectrum (h_md / h_hi):
 * genuine tonal partials have sharp Hann lobes (ratio 6..40), while resonant reverb/noise
 * washes spanning several bins have flat plateaus (ratio ~2..4). */
static double sample_h_sharpness(const float *h, int nfft, int nb, double hz, int one_sided_safe) {
    double c = hz * (double)nfft / (double)IND_SR16;
    int ic = (int)floor(c + 0.5);
    if (ic < 5 || ic >= nb - 5) return 10.0;
    int pk = ic;
    for (int k = ic - 1; k <= ic + 1; ++k) {
        if (h[k] > h[pk]) pk = k;
    }
    if (pk < 4 || pk >= nb - 4) return 10.0;
    double lsh = 0.5 * ((double)h[pk - 3] + (double)h[pk - 4]);
    double rsh = 0.5 * ((double)h[pk + 3] + (double)h[pk + 4]);
    /* For lower-high notes (65..69) where a real minor-2nd chord sits ~3 bins away on one side,
     * measure against the quieter shoulder so minor 2nds stay sharp while broad flat washes fail */
    double sh = one_sided_safe ? fmin(lsh, rsh) : (0.5 * (lsh + rsh));
    return (double)h[pk] / (sh + 1e-9);
}

struct pitch_ctx {
    const float *t_lo, *t_md, *t_hi;   /* HPSS tonal-floor-subtracted spectra */
    const float *h_lo, *h_md, *h_hi;   /* Raw HPSS harmonic spectra (for envelope & timbre) */
    const float *m_md, *m_hi;          /* Un-HPSS raw short-window spectra (for crisp onsets) */
    const double *h_e, *p_e;           /* Frame harmonic & percussive energy */
    double global_h_p95;               /* 95th percentile harmonic amplitude scale */
    int T;
    double p_freq[IND_NP];
    double p_perc_wt[IND_NP];          /* Mild perceptual (half-A) weight for threshold balance */
    float *act;                        /* [T, IND_NP] normalized activation (>1 = strong) */
    float *amp;                        /* [T, IND_NP] extracted pitch amplitude */
    float *raw_env;                    /* [T, IND_NP] pre-subtraction harmonic amplitude (for sustain) */
    float *fast_f1;                    /* [T, IND_NP] un-HPSS short-window 1f amp (for gap/edge timing) */
    float *fast_env;                   /* [T, IND_NP] un-HPSS short-window harmonic attack amp */
    float *fast_bg;                    /* [T, IND_NP] un-HPSS short-window local broadband floor */
    float *p_h1;                       /* [T, IND_NP] raw 1st harmonic amp (for timbre) */
    float *p_h2;                       /* [T, IND_NP] raw 2nd harmonic amp */
    float *p_h3;                       /* [T, IND_NP] raw 3rd harmonic amp */
    float *p_h4;                       /* [T, IND_NP] raw 4th harmonic amp */
};

static void pitch_frame_worker(int start, int end, void *arg) {
    const struct pitch_ctx *c = (const struct pitch_ctx *)arg;
    float r_lo[IND_NB_LO], r_md[IND_NB_MD], r_hi[IND_NB_HI];
    static const double harm_w[IND_MAX_HARM] = { 1.00, 0.45, 0.28, 0.19, 0.14, 0.10, 0.08, 0.06 };

    /* Global noise floor relative to 95th percentile harmonic RMS (-52 dB so quiet
     * intros and fade-outs remain tracked; local SNR + rel_thr reject true silence) */
    double floor_amp = c->global_h_p95 * 0.0025;
    if (floor_amp < 1e-5) floor_amp = 1e-5;

    for (int t = start; t < end; ++t) {
        const float *tlo = c->t_lo + (size_t)t * IND_NB_LO;
        const float *tmd = c->t_md + (size_t)t * IND_NB_MD;
        const float *thi = c->t_hi + (size_t)t * IND_NB_HI;
        const float *hlo = c->h_lo + (size_t)t * IND_NB_LO;
        const float *hmd = c->h_md + (size_t)t * IND_NB_MD;
        const float *hhi = c->h_hi + (size_t)t * IND_NB_HI;
        const float *mmd = c->m_md + (size_t)t * IND_NB_MD;
        const float *mhi = c->m_hi + (size_t)t * IND_NB_HI;

        float *act_row = c->act + (size_t)t * IND_NP;
        float *amp_row = c->amp + (size_t)t * IND_NP;
        float *env_row = c->raw_env + (size_t)t * IND_NP;
        float *ff1_row = c->fast_f1 + (size_t)t * IND_NP;
        float *fenv_row = c->fast_env + (size_t)t * IND_NP;
        float *fbg_row = c->fast_bg + (size_t)t * IND_NP;
        float *h1_row = c->p_h1 + (size_t)t * IND_NP;
        float *h2_row = c->p_h2 + (size_t)t * IND_NP;
        float *h3_row = c->p_h3 + (size_t)t * IND_NP;
        float *h4_row = c->p_h4 + (size_t)t * IND_NP;

        /* Pre-subtraction raw harmonic tracking (for sustain, GM timbre, & fast onset flux) */
        for (int pi = 0; pi < IND_NP; ++pi) {
            double f0 = c->p_freq[pi];
            float a1 = read_best_res(hlo, hmd, hhi, f0, NULL);
            float a2 = (2.0 * f0 < 6500.0) ? read_best_res(hlo, hmd, hhi, 2.0 * f0, NULL) : 0.0f;
            float a3 = (3.0 * f0 < 6500.0) ? read_best_res(hlo, hmd, hhi, 3.0 * f0, NULL) : 0.0f;
            float a4 = (4.0 * f0 < 6500.0) ? read_best_res(hlo, hmd, hhi, 4.0 * f0, NULL) : 0.0f;
            h1_row[pi] = a1;
            h2_row[pi] = a2;
            h3_row[pi] = a3;
            h4_row[pi] = a4;
            env_row[pi] = a1 + 0.5f * a2 + 0.25f * a3;

            /* Fast un-HPSS short-window (128 ms / 64 ms) pitch-specific attack & background */
            float mf1 = (f0 < 260.0) ? sample_spec_at(mmd, IND_NFFT_MD, IND_NB_MD, f0)
                                     : sample_spec_at(mhi, IND_NFFT_HI, IND_NB_HI, f0);
            float mf2 = (2.0 * f0 < 6500.0)
                ? ((2.0 * f0 < 180.0) ? sample_spec_at(mmd, IND_NFFT_MD, IND_NB_MD, 2.0 * f0)
                                      : sample_spec_at(mhi, IND_NFFT_HI, IND_NB_HI, 2.0 * f0))
                : 0.0f;
            float mf3 = (3.0 * f0 < 6500.0)
                ? ((3.0 * f0 < 180.0) ? sample_spec_at(mmd, IND_NFFT_MD, IND_NB_MD, 3.0 * f0)
                                      : sample_spec_at(mhi, IND_NFFT_HI, IND_NB_HI, 3.0 * f0))
                : 0.0f;
            float mf4 = (4.0 * f0 < 6500.0)
                ? sample_spec_at(mhi, IND_NFFT_HI, IND_NB_HI, 4.0 * f0)
                : 0.0f;
            float mb1 = (f0 < 260.0) ? sample_spec_bg(mmd, IND_NFFT_MD, IND_NB_MD, f0)
                                     : sample_spec_bg(mhi, IND_NFFT_HI, IND_NB_HI, f0);
            float mb2 = (2.0 * f0 < 6500.0)
                ? ((2.0 * f0 < 180.0) ? sample_spec_bg(mmd, IND_NFFT_MD, IND_NB_MD, 2.0 * f0)
                                      : sample_spec_bg(mhi, IND_NFFT_HI, IND_NB_HI, 2.0 * f0))
                : 0.0f;
            float mb3 = (3.0 * f0 < 6500.0)
                ? ((3.0 * f0 < 180.0) ? sample_spec_bg(mmd, IND_NFFT_MD, IND_NB_MD, 3.0 * f0)
                                      : sample_spec_bg(mhi, IND_NFFT_HI, IND_NB_HI, 3.0 * f0))
                : 0.0f;
            ff1_row[pi] = mf1;
            fenv_row[pi] = mf1 + 0.60f * mf2 + 0.38f * mf3 + 0.22f * mf4;
            fbg_row[pi] = mb1 + 0.60f * mb2 + 0.38f * mb3;

            act_row[pi] = 0.0f;
            amp_row[pi] = 0.0f;
        }

        double he = c->h_e[t], pe = c->p_e[t];
        double frame_h_rms = sqrt(he);
        if (frame_h_rms < floor_amp) continue;

        /* Frame-relative SNR regularization floor: scales down in quiet intros/outros so
         * real quiet lines stay tracked, and scales up in loud sections to reject rumble/ghosts */
        double snr_reg = frame_h_rms * 0.014;
        if (snr_reg < floor_amp * 0.5) snr_reg = floor_amp * 0.5;

        /* Harmonicity fraction: raise threshold slightly during pure percussive crashes/risers */
        double h_ratio = he / (he + pe + 1e-18);
        double noise_mult = (h_ratio < 0.25) ? (1.0 + 1.5 * (0.25 - h_ratio) / 0.25) : 1.0;

        memcpy(r_lo, tlo, IND_NB_LO * sizeof(float));
        memcpy(r_md, tmd, IND_NB_MD * sizeof(float));
        memcpy(r_hi, thi, IND_NB_HI * sizeof(float));

        uint8_t picked[IND_NP];
        memset(picked, 0, sizeof(picked));

        /* Adaptive per-frame perceptual reference (strongest tonal peak in frame) */
        double frame_ref_sal = 0.0;
        double abs_thr = pow(c->global_h_p95 * 0.0045, 0.67) * noise_mult;

        for (int pass = 0; pass < IND_MAX_VOICES; ++pass) {
            int best_pi = -1;
            double best_score = 0.0;
            double best_perc_sal = 0.0;
            double best_thr = 0.0;
            double best_f0 = 0.0;
            float best_a[IND_MAX_HARM];
            memset(best_a, 0, sizeof(best_a));

            for (int pi = 0; pi < IND_NP; ++pi) {
                if (picked[pi]) continue;
                int midi_p = IND_P_LO + pi;
                double f_nom = c->p_freq[pi];

                /* Locate exact fine fundamental within +-28 cents */
                double f_exact = f_nom;
                float a1 = read_best_res(r_lo, r_md, r_hi, f_nom, &f_exact);
                /* Guard against locking onto an adjacent semitone:
                 * >= 220 Hz uses tight +-45 cents (0.974..1.026) across the 285 Hz r_lo/r_md
                 * boundary; < 220 Hz uses +-62 cents (0.965..1.036) to block +-100 cent bass
                 * neighbor steals while allowing minor attack/chorus detune on real bass notes */
                double tol_lo = (midi_p >= 70) ? 0.978 : ((f_nom >= 220.0) ? 0.974 : 0.965);
                double tol_hi = (midi_p >= 70) ? 1.022 : ((f_nom >= 220.0) ? 1.026 : 1.036);
                if (f_exact < f_nom * tol_lo || f_exact > f_nom * tol_hi) {
                    if (midi_p >= 70) {
                        /* High register: do not grab the flat skirt of a broad noise wash or
                         * adjacent semitone unless f_nom itself is a local spectral maximum */
                        const float *rr = (f_nom < 1500.0) ? r_md : r_hi;
                        int rn = (f_nom < 1500.0) ? IND_NFFT_MD : IND_NFFT_HI;
                        int rnb = (f_nom < 1500.0) ? IND_NB_MD : IND_NB_HI;
                        int kn = clamp_i((int)floor(f_nom * (double)rn / (double)IND_SR16 + 0.5), 1, rnb - 2);
                        if (rr[kn] < 0.97f * fmaxf(rr[kn - 1], rr[kn + 1])) continue;
                    }
                    f_exact = f_nom;
                    a1 = (f_nom < 285.0) ? sample_spec_at(r_lo, IND_NFFT_LO, IND_NB_LO, f_nom)
                       : ((f_nom < 1500.0) ? sample_spec_at(r_md, IND_NFFT_MD, IND_NB_MD, f_nom)
                                           : sample_spec_at(r_hi, IND_NFFT_HI, IND_NB_HI, f_nom));
                }
                /* If 1f is weak in deep sub-bass (< C2), try refining f_exact from 2f */
                if (midi_p < 36 && a1 < (float)floor_amp) {
                    double f2_ex = 2.0 * f_nom;
                    float a2_t = read_best_res(r_lo, r_md, r_hi, 2.0 * f_nom, &f2_ex);
                    if (a2_t > a1 && f2_ex > 1.95 * f_nom && f2_ex < 2.05 * f_nom)
                        f_exact = 0.5 * f2_ex;
                }

                float a[IND_MAX_HARM];
                memset(a, 0, sizeof(a));
                a[0] = a1;
                float max_a = a1;
                int n_h = 1;
                for (int h = 2; h <= IND_MAX_HARM; ++h) {
                    double fh = (double)h * f_exact;
                    if (fh > 5800.0) break;
                    a[h - 1] = read_best_res(r_lo, r_md, r_hi, fh, NULL);
                    if (a[h - 1] > max_a) max_a = a[h - 1];
                    n_h = h;
                }
                if (max_a <= (float)(floor_amp * 0.5)) continue;

                /* Fundamental & subharmonic gate (kills octave-down & fifth-down ghosts!) */
                double odd = (double)a[0] + 0.70 * (double)a[2] + 0.45 * (double)a[4];
                double even = (double)a[1] + 0.70 * (double)a[3] + 0.45 * (double)a[5];
                if (midi_p >= 36) {
                    double min_f1_r = (midi_p >= 48 && midi_p <= 63) ? 0.11 : 0.14;
                    if ((double)a[0] < min_f1_r * (double)max_a) continue;
                    if (odd < 0.30 * even && (double)a[0] < 0.28 * (double)a[1]) continue;
                } else {
                    /* Deep sub-bass (< C2): allow mild missing-fundamental if 2f AND 3f agree */
                    int has_f1 = ((double)a[0] >= 0.08 * (double)max_a);
                    int has_23 = ((double)a[1] > 0.25 * (double)max_a && (double)a[2] > 0.25 * (double)a[1]);
                    if (!has_f1 && !has_23) continue;
                    if (odd < 0.22 * even && !has_23) continue;
                }

                /* Local spectral prominence above neighboring bins (kills broadband sweep humps) */
                float bg1 = read_best_bg(r_lo, r_md, r_hi, f_exact);
                float bg2 = (2.0 * f_exact < 5800.0) ? read_best_bg(r_lo, r_md, r_hi, 2.0 * f_exact) : 0.0f;
                double snr1 = (double)a[0] / ((double)bg1 + snr_reg);
                double snr2 = (double)a[1] / ((double)bg2 + snr_reg);
                if (snr1 < 2.0 && snr2 < 2.5) continue;
                /* Deep bass (< 75 Hz) during percussive drum fills needs stronger tonal SNR */
                if (midi_p <= 38 && h_ratio < 0.55 && snr1 < 2.6 && snr2 < 2.8) continue;

                /* High-register (> D5 / MIDI 74) needs progressively sharper tonal peak
                 * to reject cymbal partials, residual upper harmonics, & ambient reverb shimmer */
                if (midi_p > 84 && snr1 < 5.0) continue;
                else if (midi_p > 76 && snr1 < 3.2) continue;
                if (midi_p >= 65) {
                    int one_sided = (midi_p < 70);
                    double h_sh = (f_exact < 1500.0)
                        ? sample_h_sharpness(hmd, IND_NFFT_MD, IND_NB_MD, f_exact, one_sided)
                        : sample_h_sharpness(hhi, IND_NFFT_HI, IND_NB_HI, f_exact, one_sided);
                    double min_sh = (midi_p >= 76) ? 4.6 : ((midi_p >= 70) ? 3.6 : 3.0);
                    if (h_sh < min_sh) continue;
                    /* Blurry AND wandering (>26 cents off semitone center) -> resonant noise wash */
                    if (midi_p >= 70 && h_sh < 6.0 && fabs(f_exact - f_nom) > 0.015 * f_nom) continue;
                }

                /* Klapuri-style compressed harmonic salience */
                double sal = 0.0;
                for (int h = 0; h < n_h; ++h) {
                    if (a[h] > 0.0f) sal += harm_w[h] * pow((double)a[h], 0.67);
                }
                /* Mild subharmonic damping when odd << even */
                if (even > 1e-9 && odd < 0.75 * even) {
                    double r_oe = odd / (0.75 * even);
                    sal *= (0.55 + 0.45 * r_oe);
                }
                /* Taper extreme high-register (> E5 / MIDI 76) salience when no 2nd harmonic
                 * confirms it as a real instrument note rather than a lone upper partial */
                if (midi_p >= 76 && n_h >= 2 && (double)a[1] < 0.12 * (double)a[0]) {
                    sal *= 0.62;
                }

                /* Perceptually balanced threshold gate INSIDE candidate loop so a sub-threshold
                 * deep-bass ghost can never win unweighted ranking and prematurely abort the pass
                 * loop while valid mid/high chord voices remain above threshold! */
                double perc_sal = sal * c->p_perc_wt[pi];
                double rel_coef = (midi_p >= 45 && midi_p <= 64)
                    ? (0.15 + 0.018 * (double)pass)
                    : ((midi_p >= 65 && midi_p <= 74)
                        ? (0.18 + 0.025 * (double)pass)
                        : (0.23 + 0.032 * (double)pass));
                double rel_thr = (pass > 0) ? (frame_ref_sal * rel_coef * noise_mult) : 0.0;
                double thr_pi = abs_thr > rel_thr ? abs_thr : rel_thr;
                if (perc_sal < thr_pi * 0.55) continue;

                /* Low-first extraction order guarantees fundamentals (bass -> mid -> lead)
                 * are always subtracted BEFORE their upper 2f/3f harmonics can be picked */
                double order_wt = (midi_p <= 64) ? 1.0 : (1.0 / (1.0 + 0.025 * (double)(midi_p - 64)));
                double rank_sc = sal * order_wt;
                if (rank_sc > best_score) {
                    best_score = rank_sc;
                    best_perc_sal = perc_sal;
                    best_thr = thr_pi;
                    best_pi = pi;
                    best_f0 = f_exact;
                    memcpy(best_a, a, sizeof(best_a));
                }
            }

            if (best_pi < 0) break;

            int best_midi = IND_P_LO + best_pi;
            double perc_sal = best_perc_sal;
            if (pass == 0) {
                frame_ref_sal = perc_sal;
                double rel_coef0 = (best_midi >= 45 && best_midi <= 64) ? 0.15
                                 : ((best_midi >= 65 && best_midi <= 74) ? 0.18 : 0.20);
                double rel_thr0 = frame_ref_sal * rel_coef0 * noise_mult;
                best_thr = abs_thr > rel_thr0 ? abs_thr : rel_thr0;
            }
            double thr = best_thr;

            /* Record activation ratio (>1.0 = above threshold, 0.55..1.0 = soft sustain) */
            picked[best_pi] = 1;
            act_row[best_pi] = (float)(perc_sal / (thr > 1e-12 ? thr : 1e-12));
            amp_row[best_pi] = best_a[0] + 0.5f * best_a[1] + 0.25f * best_a[2];

            /* Iterative smooth-envelope harmonic cancellation across ALL 3 residual spectra */
            double a1_ref = (double)best_a[0];
            if (a1_ref < 0.35 * (double)best_a[1]) a1_ref = 0.55 * (double)best_a[1];

            for (int h = 1; h <= 10; ++h) {
                double fh = (double)h * best_f0;
                if (fh > 6500.0) break;
                float ah = (h <= IND_MAX_HARM) ? best_a[h - 1]
                                               : read_best_res(r_lo, r_md, r_hi, fh, NULL);
                if (ah <= 0.0f) continue;

                float sub;
                if (h == 1) {
                    /* Remove fundamental completely; for >= 220 Hz clear r_md/r_hi at their own
                     * local peak so chorused pads picked in 8192-pt r_lo leave no residual in
                     * wider-bin 2048-pt r_md, without over-widening subtraction below 220 Hz */
                    if (fh < 1200.0) {
                        float slo = (fh >= 220.0) ? sample_spec_peak(r_lo, IND_NFFT_LO, IND_NB_LO, fh, NULL) : ah;
                        subtract_partial(r_lo, IND_NFFT_LO, IND_NB_LO, fh, slo > ah ? slo : ah);
                    }
                    if (fh < 5900.0) {
                        float smd = (fh >= 220.0) ? sample_spec_peak(r_md, IND_NFFT_MD, IND_NB_MD, fh, NULL) : ah;
                        subtract_partial(r_md, IND_NFFT_MD, IND_NB_MD, fh, smd > ah ? smd : ah);
                    }
                    if (fh < 7400.0) {
                        float shi = (fh >= 1200.0) ? sample_spec_peak(r_hi, IND_NFFT_HI, IND_NB_HI, fh, NULL) : ah;
                        subtract_partial(r_hi, IND_NFFT_HI, IND_NB_HI, fh, shi > ah ? shi : ah);
                    }
                    continue;
                } else if ((best_midi <= 42 && h >= 2 && h <= 4) ||
                           (best_midi <= 49 && h == 2)) {
                    /* Bass & octave-bass (<= C#3) lower harmonics: 1/h-bounded gentle cancellation
                     * suppresses pure-bass overtones while preserving layered octave/5th/double-octave
                     * mid chord voices (e.g. C-3 under C-4, A-2 under A-3, Bb2 under Bb3) */
                    double cap = a1_ref * (0.85 / pow((double)h, 0.95));
                    double est = ((double)ah < cap) ? (double)ah : cap;
                    sub = (float)(0.68 * est);
                } else {
                    /* Strong overtone suppression for higher harmonics & mid/high voices
                     * (eliminates 2f/3f/4f MIDI 76..96 chatter on bright synths & leads) */
                    double cap = a1_ref * (1.35 / pow((double)h, 0.58));
                    double est = ((double)ah < cap) ? (double)ah : cap;
                    sub = (float)(0.94 * est);
                }
                if (fh < 1200.0) subtract_partial(r_lo, IND_NFFT_LO, IND_NB_LO, fh, sub);
                if (fh < 5900.0) subtract_partial(r_md, IND_NFFT_MD, IND_NB_MD, fh, sub);
                if (fh < 7400.0) subtract_partial(r_hi, IND_NFFT_HI, IND_NB_HI, fh, sub);
            }
        }
    }
}

/* =========================================================================
 * Stage 3: Per-Pitch Viterbi HMM Note Decoding + Re-Articulation + Cleanup
 * ========================================================================= */

struct cand_note {
    double onset;
    double offset;
    int pitch;
    double strength;   /* mean activation ratio */
    double amp_lin;    /* mean linear harmonic amplitude */
    double sustain;    /* late/early envelope ratio (-1 if short) */
    double bright;     /* (P2+P3+P4)/P1 */
    double even_odd;   /* (P2+P4)/(P1+P3) */
    int role;          /* 0=bass, 1=mid, 2=high */
    int keep;
};

static int cmp_cand_note(const void *pa, const void *pb) {
    const struct cand_note *a = (const struct cand_note *)pa;
    const struct cand_note *b = (const struct cand_note *)pb;
    if (a->onset < b->onset) return -1;
    if (a->onset > b->onset) return 1;
    if (a->pitch != b->pitch) return a->pitch - b->pitch;
    return (a->offset > b->offset) - (a->offset < b->offset);
}

static int cmp_midi_note(const void *pa, const void *pb) {
    const struct midi_note *a = (const struct midi_note *)pa;
    const struct midi_note *b = (const struct midi_note *)pb;
    if (a->onset < b->onset) return -1;
    if (a->onset > b->onset) return 1;
    return a->pitch - b->pitch;
}

static int decode_pitched_notes(const struct pitch_ctx *pc, double retune_ratio,
                                struct cand_note **out_notes, size_t *out_count) {
    int T = pc->T;
    *out_notes = NULL;
    *out_count = 0;
    if (T < 3) return 1;

    size_t cap = 256, n = 0;
    struct cand_note *notes = (struct cand_note *)malloc(cap * sizeof(*notes));
    double *dp0 = (double *)malloc((size_t)T * sizeof(double));
    double *dp1 = (double *)malloc((size_t)T * sizeof(double));
    uint8_t *bt0 = (uint8_t *)malloc((size_t)T);
    uint8_t *bt1 = (uint8_t *)malloc((size_t)T);
    uint8_t *state = (uint8_t *)malloc((size_t)T);
    double *env_db = (double *)malloc((size_t)T * sizeof(double));
    double *f1_db = (double *)malloc((size_t)T * sizeof(double));
    double *fe_db = (double *)malloc((size_t)T * sizeof(double));
    double *bg_db = (double *)malloc((size_t)T * sizeof(double));
    double *flux = (double *)malloc((size_t)T * sizeof(double));
    double *env_flux = (double *)malloc((size_t)T * sizeof(double));
    if (!notes || !dp0 || !dp1 || !bt0 || !bt1 || !state ||
        !env_db || !f1_db || !fe_db || !bg_db || !flux || !env_flux) {
        free(notes); free(dp0); free(dp1); free(bt0); free(bt1);
        free(state); free(env_db); free(f1_db); free(fe_db); free(bg_db); free(flux); free(env_flux);
        return 0;
    }

    const double dt = (double)IND_HOP16 / (double)IND_SR16; /* 0.02 s */
    const double hop_scale = dt * retune_ratio;

    for (int pi = 0; pi < IND_NP; ++pi) {
        int midi_p = IND_P_LO + pi;

        /* Pre-compute per-pitch smooth & fast short-window log-envelopes and tonal flux */
        for (int t = 0; t < T; ++t) {
            size_t idx = (size_t)t * IND_NP + (size_t)pi;
            env_db[t] = 20.0 * log10((double)pc->raw_env[idx] + 1e-7);
            f1_db[t]  = 20.0 * log10((double)pc->fast_f1[idx] + 1e-7);
            fe_db[t]  = 20.0 * log10((double)pc->fast_env[idx] + 1e-7);
            bg_db[t]  = 20.0 * log10((double)pc->fast_bg[idx] + 1e-7);
            if (t > 0) {
                double df_h = env_db[t] - env_db[t - 1];
                double df_f = fe_db[t] - fe_db[t - 1];
                double df_b = bg_db[t] - bg_db[t - 1];
                double tf = df_f - 0.65 * (df_b > 0.0 ? df_b : 0.0);
                env_flux[t] = df_h > 0.0 ? df_h : 0.0;
                double best = df_h > tf ? df_h : tf;
                flux[t] = best > 0.0 ? best : 0.0;
            } else {
                env_flux[t] = 0.0;
                flux[t] = 0.0;
            }
        }

        /* 2-state Viterbi HMM: state 0 = OFF, state 1 = ON */
        double s0 = (double)pc->act[pi];
        dp0[0] = 0.0;
        dp1[0] = (s0 > 0.0 ? (s0 - 0.68) : -0.95) - 2.2;
        bt0[0] = 0;
        bt1[0] = 0;

        for (int t = 1; t < T; ++t) {
            double s = (double)pc->act[(size_t)t * IND_NP + pi];
            /* Cap per-frame emission so a single 1-frame spike cannot trigger alone */
            double em1 = (s > 0.0) ? clamp_d(s - 0.68, -0.45, 1.35) : -0.95;

            /* Lower OFF->ON entry cost when pitch-specific harmonic onset rises sharply */
            double on_pen = (flux[t] >= 4.0) ? -1.40 : -2.25;
            double off_pen = -1.25;

            /* Transition into OFF */
            double f00 = dp0[t - 1];
            double f10 = dp1[t - 1] + off_pen;
            if (f00 >= f10) { dp0[t] = f00; bt0[t] = 0; }
            else { dp0[t] = f10; bt0[t] = 1; }

            /* Transition into ON */
            double f01 = dp0[t - 1] + on_pen + em1;
            double f11 = dp1[t - 1] + em1;
            if (f11 >= f01) { dp1[t] = f11; bt1[t] = 1; }
            else { dp1[t] = f01; bt1[t] = 0; }
        }

        /* Backtrack */
        state[T - 1] = (dp1[T - 1] > dp0[T - 1]) ? 1 : 0;
        for (int t = T - 2; t >= 0; --t) {
            state[t] = state[t + 1] ? bt1[t + 1] : bt0[t + 1];
        }

        /* Mid-register chord sustain bridging (45..64): heal brief 1..8 frame (20..160 ms)
         * masking dropouts caused by drum fills or bass octave jumps when raw HPSS harmonic
         * envelope env_db never actually dropped into a rest */
        if (midi_p >= 45 && midi_p <= 64) {
            int gt = 0;
            while (gt < T) {
                if (state[gt]) { ++gt; continue; }
                int ga = gt;
                while (gt < T && !state[gt]) ++gt;
                int gb = gt;
                int glen = gb - ga;
                if (glen >= 1 && glen <= 4 && ga >= 2 && gb <= T - 2 &&
                    state[ga - 1] && state[ga - 2] && state[gb] && state[gb + 1]) {
                    double e_l = 0.5 * (env_db[ga - 2] + env_db[ga - 1]);
                    double e_r = 0.5 * (env_db[gb] + env_db[gb + 1]);
                    double e_ref = fmin(e_l, e_r);
                    double e_min = env_db[ga];
                    for (int k = ga + 1; k < gb; ++k) {
                        if (env_db[k] < e_min) e_min = env_db[k];
                    }
                    if (e_min >= e_ref - 5.5) {
                        for (int k = ga; k < gb; ++k) state[k] = 1;
                    }
                } else if (glen >= 5 && glen <= 8 && ga >= 3 && gb <= T - 3 &&
                    state[ga - 1] && state[ga - 2] && state[ga - 3] &&
                    state[gb] && state[gb + 1] && state[gb + 2]) {
                    double e_l = (env_db[ga - 3] + env_db[ga - 2] + env_db[ga - 1]) / 3.0;
                    double e_r = (env_db[gb] + env_db[gb + 1] + env_db[gb + 2]) / 3.0;
                    double e_ref = fmin(e_l, e_r);
                    double e_min = env_db[ga];
                    double f1_ref = fmin(fmax(f1_db[ga - 1], f1_db[ga - 2]),
                                         fmax(f1_db[gb], f1_db[gb + 1]));
                    double f1_min = f1_db[ga];
                    for (int k = ga + 1; k < gb; ++k) {
                        if (env_db[k] < e_min) e_min = env_db[k];
                        if (f1_db[k] < f1_min) f1_min = f1_db[k];
                    }
                    if (e_min >= e_ref - 4.2 && f1_min >= f1_ref - 6.5) {
                        for (int k = ga; k < gb; ++k) state[k] = 1;
                    }
                }
            }
        }

        /* Extract contiguous ON segments & split repeated re-articulations / smeared gaps */
        int t = 0;
        while (t < T) {
            if (!state[t]) { ++t; continue; }
            int seg_a = t;
            while (t < T && state[t]) ++t;
            int seg_b = t;

            /* Dynamic split list (handles long bass lines > 256 repeats safely) */
            int max_sp = (seg_b - seg_a) / 4 + 4;
            int *splits = (int *)malloc((size_t)max_sp * sizeof(int));
            uint8_t *sp_gap = (uint8_t *)calloc((size_t)max_sp, 1);
            if (!splits || !sp_gap) {
                free(splits); free(sp_gap);
                free(notes); free(dp0); free(dp1); free(bt0); free(bt1);
                free(state); free(env_db); free(f1_db); free(fe_db); free(bg_db); free(flux); free(env_flux);
                return 0;
            }
            int n_sp = 0;
            splits[n_sp++] = seg_a;
            int last_sp = seg_a;
            double run_pk_fe = fe_db[seg_a];
            double run_pk_f1 = f1_db[seg_a];
            double run_pk_env = env_db[seg_a];

            for (int k = seg_a + 1; k < seg_b - 2; ++k) {
                if (fe_db[k - 1] > run_pk_fe) run_pk_fe = fe_db[k - 1];
                if (f1_db[k - 1] > run_pk_f1) run_pk_f1 = f1_db[k - 1];
                if (env_db[k - 1] > run_pk_env) run_pk_env = env_db[k - 1];
                /* Minimum 100 ms (5 frames) between re-articulations */
                if (k - last_sp < 5 || n_sp >= max_sp - 2) continue;

                int km2 = (k >= 2) ? (k - 2) : (k - 1);
                int kp2 = (k + 2 < seg_b) ? (k + 2) : (k + 1);

                /* 1. Low-register smeared-gap split on short-window fundamental (catches octave hops & rests
                 *    that the 512 ms 8192-pt Hann window bridged over) */
                double val_f1 = fmin(f1_db[k - 1], f1_db[km2]);
                double pk_f1_after = fmax(f1_db[k + 1], f1_db[kp2]);
                double dip_f1 = run_pk_f1 - val_f1;
                double jump_f1 = pk_f1_after - val_f1;
                double rf1_k = f1_db[k + 1] - f1_db[k - 1];
                double rf1_p = (k >= 2) ? (f1_db[k] - f1_db[k - 2]) : -99.0;
                double rf1_n = (k + 2 < seg_b) ? (f1_db[k + 2] - f1_db[k]) : -99.0;

                int is_f1_gap = (midi_p <= 48 && dip_f1 >= 5.5 && jump_f1 >= 4.5 &&
                                 rf1_k >= 2.0 && rf1_k >= rf1_p && rf1_k >= rf1_n);

                /* 2. Tonal-excess short-window harmonic re-articulation (splits repeated attacks
                 *    while rejecting broadband drum hits & chorused/vibrato pads like ice C#4) */
                double val_fe = fmin(fe_db[k - 1], fe_db[km2]);
                double pk_fe_after = fmax(fe_db[k + 1], fe_db[kp2]);
                double dip_fe = run_pk_fe - val_fe;
                double jump_fe = pk_fe_after - val_fe;
                double rfe_k = fe_db[k + 1] - fe_db[k - 1];
                double rfe_p = (k >= 2) ? (fe_db[k] - fe_db[k - 2]) : -99.0;
                double rfe_n = (k + 2 < seg_b) ? (fe_db[k + 2] - fe_db[k]) : -99.0;

                double bg_val = fmin(bg_db[k - 1], bg_db[km2]);
                double bg_after = fmax(bg_db[k + 1], bg_db[kp2]);
                double bg_jump = bg_after - bg_val;
                double tonal_jump = jump_fe - 0.72 * (bg_jump > 0.0 ? bg_jump : 0.0);

                double val_env = fmin(env_db[k - 1], env_db[km2]);
                double jump_env = env_db[k + 1] - env_db[k - 1];
                double dip_env = run_pk_env - val_env;

                int is_reartic = 0;
                if (midi_p <= 48) {
                    /* Bass (<= C-3): short-window harmonic attack with fundamental confirmation */
                    if (rfe_k >= 1.8 && rfe_k >= rfe_p && rfe_k >= rfe_n &&
                        dip_fe >= 2.8 && jump_fe >= 3.4 && tonal_jump >= 2.4 &&
                        pk_f1_after >= run_pk_f1 - 5.5) {
                        is_reartic = 1;
                    }
                } else {
                    /* Mid / High (> C-3): require smooth HPSS valley+rise so sustained chorused/vibrato
                     * pads (e.g. ice C#4) never over-split while genuine repeated leads/plucks split */
                    int smooth_split = (jump_env >= 5.5 && dip_env >= 4.5 &&
                                        env_flux[k] >= env_flux[k - 1] && env_flux[k] >= env_flux[k + 1]);
                    int sharp_pluck = (rfe_k >= 4.0 && rfe_k >= rfe_p && rfe_k >= rfe_n &&
                                       dip_fe >= 7.5 && jump_fe >= 8.0 && tonal_jump >= 7.0 &&
                                       dip_f1 >= 6.5 && jump_f1 >= 6.5 && dip_env >= 3.5);
                    if (smooth_split || sharp_pluck) {
                        is_reartic = 1;
                    }
                }

                if (is_f1_gap || is_reartic) {
                    int sp_k = k;
                    splits[n_sp] = sp_k;
                    sp_gap[n_sp] = is_f1_gap ? 1 : 0;
                    n_sp++;
                    last_sp = sp_k;
                    run_pk_fe = pk_fe_after;
                    run_pk_f1 = pk_f1_after;
                    run_pk_env = env_db[k + 1];
                }
            }
            splits[n_sp++] = seg_b;

            for (int si = 0; si < n_sp - 1; ++si) {
                int fa = splits[si];
                int fb = splits[si + 1];
                if (fb - fa < 3) continue; /* Min duration 60 ms */

                /* Trim weak tail frames where activation dropped to 0 */
                while (fb > fa + 2 && pc->act[(size_t)(fb - 1) * IND_NP + pi] <= 0.0f) fb--;
                if (fb - fa < 3) continue;

                /* Edge sharpening for notes using 512 ms 8192-pt Hann window (<= C#4 / MIDI 61):
                 * trim pre-onset lead-in bleed (bass & mid chords) and post-offset/gap-valley tail
                 * bleed (bass) using short-window f1_db so onsets land cleanly on the beat */
                int trimmed = 0;
                if (midi_p <= 61) {
                    double pk_f1 = f1_db[fa];
                    for (int k = fa + 1; k < fb; ++k) if (f1_db[k] > pk_f1) pk_f1 = f1_db[k];

                    double lead_cut = (midi_p <= 44) ? 8.0 : ((midi_p <= 48) ? 7.0 : 6.5);
                    double min_slope = (midi_p <= 48) ? 1.0 : 1.2;
                    int max_lead_trim = (midi_p <= 48) ? ((si == 0) ? 7 : 3)
                                                       : ((si == 0) ? 5 : 2);
                    while (trimmed < max_lead_trim && fa + 3 < fb &&
                           f1_db[fa] < pk_f1 - lead_cut && f1_db[fa + 1] > f1_db[fa] + min_slope) {
                        fa++;
                        trimmed++;
                    }

                    /* Trim trailing gap/release bleed for bass (<= C-3) */
                    if (midi_p <= 48) {
                        double tail_cut = (midi_p <= 44) ? 6.5 : 8.0;
                        int trim_tail = (si == n_sp - 2) || (si + 1 < n_sp && sp_gap[si + 1]);
                        if (trim_tail) {
                            while (fb - 3 > fa && f1_db[fb - 1] < pk_f1 - tail_cut) fb--;
                        }
                    }
                    if (fb - fa < 3) continue;
                }

                double sum_act = 0.0, max_act = 0.0, sum_amp = 0.0;
                double p1 = 0.0, p2 = 0.0, p3 = 0.0, p4 = 0.0;
                int n_pos = 0;
                for (int k = fa; k < fb; ++k) {
                    size_t idx = (size_t)k * IND_NP + pi;
                    double a = (double)pc->act[idx];
                    if (a > 0.0) { sum_act += a; if (a > max_act) max_act = a; n_pos++; }
                    sum_amp += (double)pc->amp[idx];
                    double r1 = (double)pc->p_h1[idx], r2 = (double)pc->p_h2[idx];
                    double r3 = (double)pc->p_h3[idx], r4 = (double)pc->p_h4[idx];
                    p1 += r1 * r1; p2 += r2 * r2; p3 += r3 * r3; p4 += r4 * r4;
                }
                double mean_act = n_pos ? (sum_act / (double)n_pos) : 0.0;
                if (mean_act < 0.85 || max_act < 1.05) continue;
                /* Short blips (< 100 ms) require strong confidence so 60-80 ms bleed/shimmer glitches vanish */
                if (fb - fa < 4 && mean_act < (midi_p >= 68 ? 2.15 : 1.90)) continue;
                if (fb - fa == 4 && mean_act < (midi_p <= 44 ? 1.50 : (midi_p >= 68 ? 1.80 : 1.55))) continue;
                if (midi_p >= 68 && fb - fa < 7 && mean_act < 1.32) continue;

                /* Sustain ratio (late/early) on notes >= 160 ms */
                double sust = -1.0;
                int span = fb - fa;
                if (span >= 8) {
                    int e1 = fa + (span * 35) / 100;
                    if (e1 <= fa) e1 = fa + 1;
                    int l0 = fa + (span * 60) / 100;
                    int l1 = fa + (span * 95) / 100;
                    if (l1 <= l0) l1 = l0 + 1;
                    if (l1 > fb) l1 = fb;
                    double de = 0.0, dl = 0.0;
                    for (int k = fa; k < e1; ++k) de += env_db[k];
                    for (int k = l0; k < l1; ++k) dl += env_db[k];
                    de /= (double)(e1 - fa);
                    dl /= (double)(l1 - l0);
                    sust = clamp_d(pow(10.0, (dl - de) / 20.0), 0.0, 2.0);
                }

                /* Snap onset back by up to 1 frame if sharp attack peaked right before fa
                 * (skip on Mid chords where lead-in trimming just moved fa out of Hann pre-smear) */
                int fa_sn = fa;
                if ((midi_p <= 48 || !trimmed) && fa > 0 && flux[fa] < flux[fa - 1] && flux[fa - 1] >= 4.0 &&
                    (si == 0 || fa - 1 > splits[si - 1])) {
                    fa_sn = fa - 1;
                }

                double on_s = (double)fa_sn * hop_scale;
                double off_s = (double)fb * hop_scale;
                if (si < n_sp - 2 && off_s - on_s > 0.05) off_s -= 0.012; /* Clean retrigger gap */

                if (n == cap) {
                    cap *= 2;
                    struct cand_note *g = (struct cand_note *)realloc(notes, cap * sizeof(*notes));
                    if (!g) {
                        free(splits); free(sp_gap);
                        free(notes); free(dp0); free(dp1); free(bt0); free(bt1);
                        free(state); free(env_db); free(f1_db); free(fe_db); free(bg_db); free(flux); free(env_flux);
                        return 0;
                    }
                    notes = g;
                }
                notes[n++] = (struct cand_note){
                    on_s, off_s, midi_p,
                    mean_act, sum_amp / (double)(fb - fa),
                    sust,
                    (p2 + p3 + p4) / (p1 + 1e-12),
                    (p2 + p4) / (p1 + p3 + 1e-12),
                    1, 1
                };
            }
            free(splits);
            free(sp_gap);
        }
    }

    free(dp0); free(dp1); free(bt0); free(bt1);
    free(state); free(env_db); free(f1_db); free(fe_db); free(bg_db); free(flux); free(env_flux);

    if (n > 1) qsort(notes, n, sizeof(*notes), cmp_cand_note);

    /* Post-cleanup 1: Adjacent-semitone spectral-leakage & high-register wobble suppression */
    for (size_t i = 0; i < n; ++i) {
        if (!notes[i].keep) continue;
        for (size_t j = i + 1; j < n; ++j) {
            if (notes[j].onset > notes[i].offset + 0.06) break;
            if (!notes[j].keep) continue;
            if (abs(notes[i].pitch - notes[j].pitch) != 1) continue;
            double di = notes[i].offset - notes[i].onset;
            double dj = notes[j].offset - notes[j].onset;
            double ov = fmin(notes[i].offset, notes[j].offset) - fmax(notes[i].onset, notes[j].onset);
            double md = fmin(di, dj);
            double si = notes[i].strength * sqrt(notes[i].amp_lin + 1e-9);
            double sj = notes[j].strength * sqrt(notes[j].amp_lin + 1e-9);
            if (md > 0.0 && ov > 0.55 * md) {
                if (si > 1.75 * sj) notes[j].keep = 0;
                else if (sj > 1.75 * si) { notes[i].keep = 0; break; }
            } else if (ov > -0.06 && notes[i].pitch >= 66 && notes[j].pitch >= 66) {
                /* Drop brief (<140 ms) weak adjacent-semitone vibrato/shimmer wobble next to a
                 * much longer & stronger neighbor note */
                if (dj < 0.14 && notes[j].strength < 1.55 && di >= 2.0 * dj && si >= 1.30 * sj) {
                    notes[j].keep = 0;
                } else if (di < 0.14 && notes[i].strength < 1.55 && dj >= 2.0 * di && sj >= 1.30 * si) {
                    notes[i].keep = 0;
                    break;
                }
            }
        }
    }

    /* Post-cleanup 2: Residual octave/twelfth/double-octave/17th overtone suppression
     * when lower note overlaps heavily and upper note is an upper partial ghost */
    for (size_t i = 0; i < n; ++i) {
        if (!notes[i].keep) continue;
        for (size_t j = 0; j < n; ++j) {
            if (i == j || !notes[j].keep) continue;
            int dp = notes[i].pitch - notes[j].pitch;
            if (dp != 12 && dp != 19 && dp != 24 && dp != 28) continue;
            double ov = fmin(notes[i].offset, notes[j].offset) - fmax(notes[i].onset, notes[j].onset);
            double di = notes[i].offset - notes[i].onset;
            if (di <= 0.0 || ov <= 0.65 * di) continue;
            int same_on = (fabs(notes[i].onset - notes[j].onset) <= 0.075);
            int upper_ghost = (notes[i].pitch >= 76 && notes[i].amp_lin < 0.55 * notes[j].amp_lin &&
                               (same_on || notes[i].onset >= notes[j].onset - 0.04));
            double weak_ratio = (notes[i].pitch >= 45 && notes[i].pitch <= 64) ? 0.12 : 0.24;
            int lower_weak_ot = (same_on && notes[i].strength < 1.35 && notes[i].amp_lin < weak_ratio * notes[j].amp_lin);
            if (upper_ghost || lower_weak_ot) {
                notes[i].keep = 0;
                break;
            }
        }
    }

    /* Compact survivors */
    size_t w = 0;
    for (size_t i = 0; i < n; ++i) {
        if (notes[i].keep) notes[w++] = notes[i];
    }

    *out_notes = notes;
    *out_count = w;
    return 1;
}

/* =========================================================================
 * Stage 4: Native-Rate Multi-Band Percussive Drum Transcriber
 * ========================================================================= */

static double parabolic_time(const double *x, int idx, int n, double dt) {
    if (idx > 0 && idx < n - 1 && x[idx] >= x[idx - 1] && x[idx] >= x[idx + 1]) {
        double a = x[idx - 1], b = x[idx], c = x[idx + 1];
        double den = a - 2.0 * b + c;
        if (den < -1e-12) {
            double off = 0.5 * (a - c) / den;
            if (off > -0.5 && off < 0.5) return ((double)idx + off) * dt;
        }
    }
    return (double)idx * dt;
}

static int transcribe_drums_dsp(const float *audio, size_t n_frames, unsigned sr,
                                struct midi_note **out_notes, size_t *out_count,
                                struct independent_stats *stats) {
    *out_notes = NULL;
    *out_count = 0;
    if (!audio || n_frames < 2048 || sr < 8000) return 1;

    int nfft = (sr >= 30000) ? 1024 : 512;
    int nb = nfft / 2 + 1;
    int nfft_lo = nfft * 2; /* 2048 @ 44.1k (21.5 Hz bins) for sharp sub/kick/body separation */
    double bin_lo = (double)sr / (double)nfft_lo;
    int nb_lo = clamp_i((int)ceil(620.0 / bin_lo) + 8, 16, nfft_lo / 2 + 1);

    int hop = (int)floor((double)sr * 0.010 + 0.5); /* 10 ms = 100 fps */
    if (hop < 1) hop = 1;
    int T = (int)(n_frames / (size_t)hop);
    if (T < 20) return 1;
    double dt = (double)hop / (double)sr;

    float *mag = NULL, *perc = NULL;
    float *mag_lo = NULL, *perc_lo = NULL;
    if (!compute_mag_stft(audio, n_frames, T, hop, nfft, nb, &mag)) return 0;
    perc = (float *)malloc((size_t)T * (size_t)nb * sizeof(float));
    if (!perc) { free(mag); return 0; }
    {
        /* HPSS to strip sustained bass & synth chords before drum band extraction */
        struct hpss_ctx hctx = { mag, NULL, perc, NULL, NULL, NULL, T, nb, 6, 8, 1.15f, 0.0f };
        nn_parallel_for(T, 64, hpss_worker, &hctx);
    }

    if (!compute_mag_stft(audio, n_frames, T, hop, nfft_lo, nb_lo, &mag_lo)) {
        free(mag); free(perc);
        return 0;
    }
    perc_lo = (float *)malloc((size_t)T * (size_t)nb_lo * sizeof(float));
    if (!perc_lo) { free(mag); free(perc); free(mag_lo); return 0; }
    {
        struct hpss_ctx hctx_lo = { mag_lo, NULL, perc_lo, NULL, NULL, NULL, T, nb_lo, 6, 5, 1.12f, 0.0f };
        nn_parallel_for(T, 64, hpss_worker, &hctx_lo);
    }

    double *e_kick  = (double *)calloc((size_t)T, sizeof(double));
    double *e_ksub  = (double *)calloc((size_t)T, sizeof(double));
    double *e_kmid  = (double *)calloc((size_t)T, sizeof(double));
    double *e_kbod  = (double *)calloc((size_t)T, sizeof(double));
    double *e_kraw  = (double *)calloc((size_t)T, sizeof(double));
    double *e_snlo  = (double *)calloc((size_t)T, sizeof(double));
    double *e_snhi  = (double *)calloc((size_t)T, sizeof(double));
    double *e_hat   = (double *)calloc((size_t)T, sizeof(double));
    double *e_hat6  = (double *)calloc((size_t)T, sizeof(double));
    double *e_tot   = (double *)calloc((size_t)T, sizeof(double));
    double *e_mtot  = (double *)calloc((size_t)T, sizeof(double));
    double *pr_k    = (double *)calloc((size_t)T, sizeof(double));
    double *pr_sn   = (double *)calloc((size_t)T, sizeof(double));
    double *pr_sh   = (double *)calloc((size_t)T, sizeof(double));
    double *pr_h    = (double *)calloc((size_t)T, sizeof(double));
    double *fl_sn   = (double *)calloc((size_t)T, sizeof(double));

    double *fx_ksub = (double *)calloc((size_t)T, sizeof(double));
    double *fx_kmid = (double *)calloc((size_t)T, sizeof(double));
    double *fx_kbod = (double *)calloc((size_t)T, sizeof(double));
    double *fx_k    = (double *)calloc((size_t)T, sizeof(double));
    double *fx_sn   = (double *)calloc((size_t)T, sizeof(double));
    double *fx_h    = (double *)calloc((size_t)T, sizeof(double));
    double *fx_h6   = (double *)calloc((size_t)T, sizeof(double));

    int ok = 0;
    if (!e_kick || !e_ksub || !e_kmid || !e_kbod || !e_kraw || !e_snlo || !e_snhi ||
        !e_hat || !e_hat6 || !e_tot || !e_mtot || !pr_k || !pr_sn || !pr_sh || !pr_h || !fl_sn ||
        !fx_ksub || !fx_kmid || !fx_kbod || !fx_k || !fx_sn || !fx_h || !fx_h6) {
        goto cleanup;
    }

    /* Fine-resolution low bins (2048 @ 44.1k): sub 35..95 Hz, kick-mid 95..165 Hz, body 165..350 Hz */
    int kl_s0 = clamp_i((int)ceil(35.0 / bin_lo), 1, nb_lo - 1);
    int kl_s1 = clamp_i((int)floor(95.0 / bin_lo), kl_s0, nb_lo - 1);
    int kl_m0 = clamp_i(kl_s1 + 1, 1, nb_lo - 1);
    int kl_m1 = clamp_i((int)floor(165.0 / bin_lo), kl_m0, nb_lo - 1);
    int kl_b0 = clamp_i(kl_m1 + 1, 1, nb_lo - 1);
    int kl_b1 = clamp_i((int)floor(350.0 / bin_lo), kl_b0, nb_lo - 1);

    /* Fast-resolution mid/high bins (1024 @ 44.1k): snare body, wire snap, hats */
    double bin_hz = (double)sr / (double)nfft;
    int k_s0 = clamp_i((int)ceil(170.0 / bin_hz), 1, nb - 1);
    int k_s1 = clamp_i((int)floor(1650.0 / bin_hz), k_s0, nb - 1);
    int k_sh0 = clamp_i((int)ceil(1800.0 / bin_hz), 1, nb - 1);
    int k_sh1 = clamp_i((int)floor(5200.0 / bin_hz), k_sh0, nb - 1);

    double hat_lo_hz = (sr >= 24000) ? 4500.0 : 3200.0;
    double hat_hi_hz = fmin(12500.0, 0.48 * (double)sr);
    int k_h0 = clamp_i((int)ceil(hat_lo_hz / bin_hz), 1, nb - 1);
    int k_h6 = clamp_i((int)ceil(fmin(6200.0, 0.40 * (double)sr) / bin_hz), k_h0, nb - 1);
    int k_h1 = clamp_i((int)floor(hat_hi_hz / bin_hz), k_h6, nb - 1);

    /* Per-frame band percussive energies, percussive ratios, and spectral flatness */
    for (int t = 0; t < T; ++t) {
        const float *plo = perc_lo + (size_t)t * (size_t)nb_lo;
        const float *mlo = mag_lo + (size_t)t * (size_t)nb_lo;
        const float *pm = perc + (size_t)t * (size_t)nb;
        const float *mm = mag + (size_t)t * (size_t)nb;

        double psub = 0.0, pmid = 0.0, pbod = 0.0, mk = 0.0;
        for (int k = kl_s0; k <= kl_s1; ++k) {
            psub += (double)plo[k] * (double)plo[k];
            mk += (double)mlo[k] * (double)mlo[k];
        }
        for (int k = kl_m0; k <= kl_m1; ++k) {
            pmid += (double)plo[k] * (double)plo[k];
            mk += (double)mlo[k] * (double)mlo[k];
        }
        for (int k = kl_b0; k <= kl_b1; ++k) {
            pbod += (double)plo[k] * (double)plo[k];
        }
        e_ksub[t] = psub;
        e_kmid[t] = pmid;
        e_kick[t] = psub + pmid;
        e_kbod[t] = pbod;
        e_kraw[t] = mk;
        pr_k[t] = (psub + pmid) / (mk + 1e-18);

        double ps = 0.0, ms = 0.0, log_sum = 0.0;
        int n_s = k_s1 - k_s0 + 1;
        for (int k = k_s0; k <= k_s1; ++k) {
            double vp = (double)pm[k] * (double)pm[k];
            double vm = (double)mm[k] * (double)mm[k];
            ps += vp; ms += vm;
            log_sum += log(vp + 1e-14);
        }
        e_snlo[t] = ps;
        pr_sn[t] = ps / (ms + 1e-18);
        double arith = ps / (double)n_s + 1e-14;
        fl_sn[t] = exp(log_sum / (double)n_s) / arith;

        double psh = 0.0, msh = 0.0;
        for (int k = k_sh0; k <= k_sh1; ++k) {
            psh += (double)pm[k] * (double)pm[k];
            msh += (double)mm[k] * (double)mm[k];
        }
        e_snhi[t] = psh;
        pr_sh[t] = psh / (msh + 1e-18);

        double ph = 0.0, mh = 0.0, ph6 = 0.0;
        for (int k = k_h0; k <= k_h1; ++k) {
            double vp = (double)pm[k] * (double)pm[k];
            double vm = (double)mm[k] * (double)mm[k];
            ph += vp; mh += vm;
            if (k >= k_h6) ph6 += vp;
        }
        e_hat[t] = ph;
        e_hat6[t] = ph6;
        pr_h[t] = ph / (mh + 1e-18);
        e_tot[t] = e_kick[t] + ps + psh + ph;
        double mt = 0.0;
        for (int k = 1; k < nb; ++k) mt += (double)mm[k] * (double)mm[k];
        e_mtot[t] = mt;
    }

    /* Spectral positive log-flux per band */
    for (int t = 1; t < T; ++t) {
        const float *l0 = perc_lo + (size_t)(t - 1) * (size_t)nb_lo;
        const float *l1 = perc_lo + (size_t)t * (size_t)nb_lo;
        const float *p0 = perc + (size_t)(t - 1) * (size_t)nb;
        const float *p1 = perc + (size_t)t * (size_t)nb;

        double fks = 0.0, fkm = 0.0, fkb = 0.0;
        for (int k = kl_s0; k <= kl_s1; ++k) {
            double d = log1p(80.0 * (double)l1[k]) - log1p(80.0 * (double)l0[k]);
            if (d > 0.0) fks += d;
        }
        for (int k = kl_m0; k <= kl_m1; ++k) {
            double d = log1p(90.0 * (double)l1[k]) - log1p(90.0 * (double)l0[k]);
            if (d > 0.0) fkm += d;
        }
        for (int k = kl_b0; k <= kl_b1; ++k) {
            double d = log1p(100.0 * (double)l1[k]) - log1p(100.0 * (double)l0[k]);
            if (d > 0.0) fkb += d;
        }
        fx_ksub[t] = (fks + fkm) / (double)(kl_m1 - kl_s0 + 1);
        fx_kmid[t] = fkm / (double)(kl_m1 - kl_m0 + 1);
        fx_kbod[t] = fkb / (double)(kl_b1 - kl_b0 + 1);

        double fsl = 0.0, fsh = 0.0, fh = 0.0, fh6 = 0.0;
        for (int k = k_s0; k <= k_s1; ++k) {
            double d = log1p(120.0 * (double)p1[k]) - log1p(120.0 * (double)p0[k]);
            if (d > 0.0) fsl += d;
        }
        for (int k = k_sh0; k <= k_sh1; ++k) {
            double d = log1p(150.0 * (double)p1[k]) - log1p(150.0 * (double)p0[k]);
            if (d > 0.0) fsh += d;
        }
        for (int k = k_h0; k <= k_h1; ++k) {
            double d = log1p(180.0 * (double)p1[k]) - log1p(180.0 * (double)p0[k]);
            if (d > 0.0) {
                fh += d;
                if (k >= k_h6) fh6 += d;
            }
        }
        /* Emphasize snare body (170-1650 Hz) over wire so hats don't trigger snare flux alone */
        fx_sn[t] = 0.68 * (fsl / (double)(k_s1 - k_s0 + 1)) +
                   0.32 * (fsh / (double)(k_sh1 - k_sh0 + 1));
        fx_h[t] = fh / (double)(k_h1 - k_h0 + 1);
        fx_h6[t] = fh6 / (double)(k_h1 - k_h6 + 1);
    }

    free(perc_lo); perc_lo = NULL;
    free(mag_lo); mag_lo = NULL;
    free(perc); perc = NULL;
    free(mag); mag = NULL;

    /* Unified Kick onset flux: combines immediate sub/kick-mid impulse AND downward pitch-sweep
     * kicks (165-350 Hz attack at t followed within 10-40 ms by a sharp 95-165 Hz surge) so both
     * 808/acoustic kicks and synth pitch-drop kicks land at exact onset time t! */
    for (int t = 0; t < T; ++t) {
        double fk = fx_ksub[t];
        if (t >= 3 && t + 4 < T && fx_kbod[t] > 0.055) {
            double km_pre = 0.5 * (e_kmid[t - 2] + e_kmid[t - 3]) + 1e-12;
            double km_fut = fmax(fmax(e_kmid[t + 1], e_kmid[t + 2]), fmax(e_kmid[t + 3], e_kmid[t + 4]));
            double kl_pre = 0.5 * (e_kick[t - 2] + e_kick[t - 3]) + 1e-12;
            double kl_fut = fmax(fmax(e_kick[t + 1], e_kick[t + 2]), fmax(e_kick[t + 3], e_kick[t + 4]));
            double km_arr = (e_kmid[t + 2] + e_kmid[t + 3]) / (e_kmid[t - 1] + e_kmid[t] + 1e-12);
            if (km_fut / km_pre >= 3.2 && kl_fut / kl_pre >= 2.2 && km_arr >= 1.25) {
                double fkm_fut = fmax(fmax(fx_kmid[t + 1], fx_kmid[t + 2]),
                                      fmax(fx_kmid[t + 3], fx_kmid[t + 4]));
                double sweep = 0.85 * fx_kbod[t] + 0.65 * fkm_fut;
                if (sweep > fk) fk = sweep;
            }
        }
        fx_k[t] = fk;
    }

    /* Global band scale statistics anchored at 99.5th / 99th percentile so sparse drum sections
     * (e.g. 3 snares in 12 s) never collapse thresholds onto background bleed; also compare
     * against total signal energy m95_all so drumless ambient tracks don't self-normalize swells */
    double e995_k   = ind_percentile(e_kick, (size_t)T, 0.995);
    double e995_sn  = ind_percentile(e_snlo, (size_t)T, 0.995);
    double e995_sh  = ind_percentile(e_snhi, (size_t)T, 0.995);
    double e995_tot = ind_percentile(e_tot,  (size_t)T, 0.995);
    double m95_all  = ind_percentile(e_mtot, (size_t)T, 0.95) + 1e-15;
    double e95_h    = ind_percentile(e_hat,  (size_t)T, 0.95);
    double f99_k    = ind_percentile(fx_k,   (size_t)T, 0.99);
    double f99_sn   = ind_percentile(fx_sn,  (size_t)T, 0.99);
    double f90_h    = ind_percentile(fx_h,   (size_t)T, 0.90);

    size_t cap = 256, n = 0;
    struct midi_note *hits = (struct midi_note *)malloc(cap * sizeof(*hits));
    uint8_t *kick_at = (uint8_t *)calloc((size_t)T, 1);
    uint8_t *snare_at = (uint8_t *)calloc((size_t)T, 1);
    if (!hits || !kick_at || !snare_at) { free(hits); free(kick_at); free(snare_at); goto cleanup; }

    #define PUSH_HIT(t_on, pitch_v, vel_v) do { \
        if (n == cap) { \
            cap *= 2; \
            struct midi_note *_g = (struct midi_note *)realloc(hits, cap * sizeof(*hits)); \
            if (!_g) { free(hits); free(kick_at); free(snare_at); goto cleanup; } \
            hits = _g; \
        } \
        hits[n++] = (struct midi_note){ (t_on), (t_on) + 0.10, (pitch_v), clamp_i((vel_v), 24, 127) }; \
    } while (0)

    /* Helper buffer: local median over +-24 frames (0.48 s) strided by 2 */
    double mbuf[31];

    /* ---- 1. Kick (GM 36) ---- */
    if (e995_k > 1e-8 && e995_k > e995_tot * 0.015 && f99_k > 0.055 &&
        e995_k > m95_all * 0.12 && e995_tot > m95_all * 0.22) {
        int last_k = -100;
        double e_floor = e995_k * 0.112; /* -9.5 dB below loudest kicks (catches syncopated kicks, rejects bleed) */
        for (int t = 3; t < T - 5; ++t) {
            if (t - last_k < 11) continue; /* 110 ms refractory (supports 16ths to 136 BPM, kills HPSS rebounds) */
            double v = fx_k[t];
            if (v < fx_k[t - 1] || v < fx_k[t + 1] || v < fx_k[t - 2] || v < fx_k[t + 2]) continue;

            int nm = 0;
            for (int d = -24; d <= 24; d += 2) {
                int idx = clamp_i(t + d, 0, T - 1);
                mbuf[nm++] = fx_k[idx];
            }
            double med = median_small_d(mbuf, nm);
            double thr = med * 2.30 + f99_k * 0.30 + 0.048;
            if (v < thr) continue;

            /* Look across [t..t+5] so both immediate 808/acoustic kicks and 40 ms pitch-drop kicks
             * are measured at their true sub+kick-mid peak */
            double e_post = e_kick[t], km_post = e_kmid[t], pr_max = pr_k[t], raw_pk = e_kraw[t];
            for (int d = 1; d <= 5 && t + d < T; ++d) {
                if (e_kick[t + d] > e_post) e_post = e_kick[t + d];
                if (e_kmid[t + d] > km_post) km_post = e_kmid[t + d];
                if (pr_k[t + d] > pr_max) pr_max = pr_k[t + d];
                if (e_kraw[t + d] > raw_pk) raw_pk = e_kraw[t + d];
            }
            double e_pre = 0.5 * (e_kick[t - 2] + e_kick[t - 3]) + 1e-12;
            double km_pre = 0.5 * (e_kmid[t - 2] + e_kmid[t - 3]) + 1e-12;
            double km_rise = km_post / km_pre;
            if (e_post < e_floor) continue;
            if (e_post / e_pre < 2.10 && km_rise < 3.4) continue;
            if (pr_max < 0.23) continue;

            /* Snare-to-kick bleed rejection: snare has dominant 165-350 Hz body + wire snap
             * with much weaker low-end punch relative to track kick scale */
            double bod_post = fmax(e_kbod[t], fmax(e_kbod[t + 1], e_kbod[t + 2]));
            double snh_post = fmax(e_snhi[t], e_snhi[t + 1]);
            if (bod_post > 3.2 * e_post && e_post < e995_k * 0.36) continue;
            if (bod_post > 1.8 * e_post && km_rise < 2.9) continue;
            if (snh_post > 0.30 * e_post && e_post < e995_k * 0.26 && bod_post > 2.0 * e_post) continue;

            /* Sustained bass-note / low-bed rejection */
            double raw_tail = 0.0;
            int n_tl = 0;
            for (int k = t + 9; k <= t + 15 && k < T; ++k) { raw_tail += e_kraw[k]; n_tl++; }
            double k_decay = (n_tl > 0) ? (raw_pk / (raw_tail / (double)n_tl + 1e-12)) : 2.0;
            double bod_pre = 0.5 * (e_kbod[t - 2] + e_kbod[t - 3]) + 1e-12;
            double bod_rise = bod_post / bod_pre;
            if (pr_max < 0.36 && km_rise < 2.8 && bod_rise < 2.4 && k_decay < 1.85) continue;
            if (e_post < e995_k * 0.22 && k_decay < 1.45 && pr_max < 0.52) continue;
            /* Reject pure-sub bass notes/drones lacking BOTH kick-mid punch (95-165 Hz) & click/body (165-350 Hz) */
            if (bod_post < 0.06 * e_post && km_post < 0.15 * e_post) continue;
            if (km_post < 0.12 * e_post && bod_post < 0.22 * e_post && k_decay < 2.60) continue;
            if (bod_post < 0.08 * e_post && (e_post < e995_k * 0.78 || k_decay < 2.15)) continue;

            double on_s = parabolic_time(fx_k, t, T, dt);
            double rel_db = clamp_d(10.0 * log10((e_post + 1e-12) / (e995_k + 1e-12)), -18.0, 3.0);
            int vel = (int)floor(108.0 * pow(10.0, rel_db / 40.0) + 0.5);
            PUSH_HIT(on_s, 36, vel);
            kick_at[t] = 1;
            last_k = t;
            if (stats) stats->kick_hits++;
        }
    }

    /* ---- 2. Snare (GM 38) ---- */
    if (e995_sn > 1e-8 && f99_sn > 0.035 && e995_sh > m95_all * 0.025) {
        int last_s = -100;
        double e_floor = e995_sn * 0.036; /* -14.5 dB below loudest snares (kills intro & hat bleed) */
        for (int t = 3; t < T - 3; ++t) {
            if (t - last_s < 8) continue; /* 80 ms refractory */
            double v = fx_sn[t];
            if (v < fx_sn[t - 1] || v < fx_sn[t + 1] || v < fx_sn[t - 2] || v < fx_sn[t + 2]) continue;

            int nm = 0;
            for (int d = -24; d <= 24; d += 2) {
                int idx = clamp_i(t + d, 0, T - 1);
                mbuf[nm++] = fx_sn[idx];
            }
            double med = median_small_d(mbuf, nm);
            double thr = med * 1.75 + f99_sn * 0.16 + 0.020;
            if (v < thr) continue;

            double e_post = fmax(e_snlo[t], fmax(e_snlo[t + 1], e_snlo[t + 2]));
            double e_hi_p = fmax(e_snhi[t], e_snhi[t + 1]);
            double e_hat_p = fmax(e_hat6[t], e_hat6[t + 1]);
            double e_pre = 0.5 * (e_snlo[t - 2] + e_snlo[t - 3]) + 1e-12;
            double e_hi_pre = 0.5 * (e_snhi[t - 2] + e_snhi[t - 3]) + 1e-12;
            if (e_post < e_floor) continue;

            /* Require genuine snare body rise (prevents pure hat transients from bypassing via wire band) */
            double body_rise = e_post / e_pre;
            double wire_rise = e_hi_p / e_hi_pre;
            if (body_rise < 1.65 && !(body_rise >= 1.35 && wire_rise >= 2.8 && e_post >= e995_sn * 0.06)) {
                continue;
            }

            /* Hat-dominance rejection: if >6.2 kHz cymbal energy dwarfs snare wire & body, it's a hat */
            if (e_hat_p > 1.70 * e_hi_p && e_hat_p > 0.55 * e_post) continue;
            if (e_post < e995_sn * 0.085 && e_hat_p > 0.95 * e_hi_p && e_hat_p > 0.30 * e_post) continue;

            /* Percussive & broadband wire gate (rejects tonal synth/guitar notes & ambient swells) */
            double pr_body = fmax(pr_sn[t], pr_sn[t + 1]);
            double pr_snap = fmax(pr_sh[t], pr_sh[t + 1]);
            double fl_max = fmax(fl_sn[t], fl_sn[t + 1]);
            if (pr_snap < 0.30 || (pr_body < 0.19 && pr_snap < 0.36)) continue;
            if (e_hi_p < 0.012 * e_post && fl_max < 0.14) continue;

            /* Cross-band kick & low-tom/sub-thump bleed rejection:
             * (a) even without a detected kick, reject sub-heavy low thumps lacking snare wire snap
             * (b) near a detected kick, allow simultaneous K+S (e.g. breakbeats) ONLY when broadband
             *     snare wire (1.8-5.2 kHz) is strong relative to the kick's low punch
             *     (solo pitch-drop kicks have snh/ek ~ 0.14 & fl ~ 0.17, K+S has snh/ek ~ 0.73 & fl ~ 0.48) */
            double ek_here = e_kick[t];
            for (int d = 1; d <= 5 && t + d < T; ++d)
                if (e_kick[t + d] > ek_here) ek_here = e_kick[t + d];
            if (ek_here > e995_k * 0.20 && e_hi_p < 0.05 * ek_here) continue;

            int near_kick = kick_at[t] || kick_at[t - 1] || kick_at[t + 1] ||
                            (t >= 2 && kick_at[t - 2]) || (t + 2 < T && kick_at[t + 2]);
            if (near_kick) {
                if (e_hi_p < 0.36 * ek_here || wire_rise < 1.8) continue;
                if (e_hi_p < 0.55 * ek_here && fl_max < 0.28) continue;
            }

            double on_s = parabolic_time(fx_sn, t, T, dt);
            double rel_db = clamp_d(10.0 * log10((e_post + 1e-12) / (e995_sn + 1e-12)), -18.0, 3.0);
            int vel = (int)floor(108.0 * pow(10.0, rel_db / 40.0) + 0.5);
            PUSH_HIT(on_s, 38, vel);
            snare_at[t] = 1;
            last_s = t;
            if (stats) stats->snare_hits++;
        }
    }

    /* ---- 3. Hi-Hats (GM 42 Closed / GM 46 Open) & Crash (GM 49) ---- */
    if (e95_h > 1e-9 && f90_h > 0.010) {
        int last_h = -100;
        int last_crash = -200;
        double e_floor = e95_h * 0.0025; /* -26 dB */
        for (int t = 3; t < T - 3; ++t) {
            if (t - last_h < 5) continue; /* 50 ms refractory (supports fast 16th groove hats) */
            double v = fx_h[t];
            if (v < fx_h[t - 1] || v < fx_h[t + 1] || v < fx_h[t - 2] || v < fx_h[t + 2]) continue;

            int nm = 0;
            for (int d = -24; d <= 24; d += 2) {
                int idx = clamp_i(t + d, 0, T - 1);
                mbuf[nm++] = fx_h[idx];
            }
            double med = median_small_d(mbuf, nm);
            double thr = med * 1.50 + f90_h * 0.25 + 0.010;

            /* Cross-band snare wire bleed rejection (allow real simultaneous hat+snare) */
            int near_sn = snare_at[t] || snare_at[t - 1] || snare_at[t + 1];
            if (near_sn && (v < thr * 1.15 || fx_h6[t] < thr * 0.72)) continue;
            if (v < thr) continue;

            double e_post = fmax(e_hat[t], fmax(e_hat[t + 1], e_hat[t + 2]));
            double e_pre = 0.5 * (e_hat[t - 2] + e_hat[t - 3]) + 1e-12;
            if (e_post < e_floor) continue;
            if (e_post / e_pre < 1.35) continue;
            if (fmax(pr_h[t], pr_h[t + 1]) < 0.22) continue;

            /* Measure post-onset tail decay (100..220 ms vs 0..40 ms) to separate 42/46/49 */
            double e_atk = 0.0, e_tail = 0.0;
            int na = 0, nt = 0;
            for (int k = t; k <= t + 4 && k < T; ++k) { e_atk += e_hat[k]; na++; }
            for (int k = t + 10; k <= t + 22 && k < T; ++k) { e_tail += e_hat[k]; nt++; }
            double decay_r = (na && nt && e_atk > 1e-15) ? ((e_tail / nt) / (e_atk / na)) : 0.0;

            int gm_key = 42; /* Closed HH */
            if (decay_r >= 0.65 && e_post > e95_h * 0.30 && (t - last_crash) >= 150) {
                gm_key = 49; /* Crash Cymbal */
                last_crash = t;
                if (stats) stats->crash_hits++;
            } else if (decay_r >= 0.36) {
                gm_key = 46; /* Open HH */
                if (stats) stats->hat_hits++;
            } else {
                if (stats) stats->hat_hits++;
            }

            double on_s = parabolic_time(fx_h, t, T, dt);
            double rel_db = clamp_d(10.0 * log10((e_post + 1e-12) / (e95_h + 1e-12)), -18.0, 3.0);
            int vel = (int)floor(98.0 * pow(10.0, rel_db / 40.0) + 0.5);
            PUSH_HIT(on_s, gm_key, vel);
            last_h = t;
        }
    }

    #undef PUSH_HIT
    if (n > 1) qsort(hits, n, sizeof(*hits), cmp_midi_note);
    free(kick_at);
    free(snare_at);
    *out_notes = hits;
    *out_count = n;
    ok = 1;

cleanup:
    free(perc_lo); free(mag_lo); free(perc); free(mag);
    free(e_kick); free(e_ksub); free(e_kmid); free(e_kbod); free(e_kraw);
    free(e_snlo); free(e_snhi); free(e_hat); free(e_hat6); free(e_tot); free(e_mtot);
    free(pr_k); free(pr_sn); free(pr_sh); free(pr_h); free(fl_sn);
    free(fx_ksub); free(fx_kmid); free(fx_kbod); free(fx_k); free(fx_sn); free(fx_h); free(fx_h6);
    return ok;
}

/* =========================================================================
 * Stage 5: Adaptive Role Clustering, Polyphony Limiting & Timbral GM Mapping
 * ========================================================================= */

static int choose_role_program(int role, double med_pitch, double med_dur,
                               double med_sus, double med_br, double med_eo,
                               const char **name_out) {
    if (role == 0) {
        /* Bass role */
        if (med_sus >= 0.45 || med_dur >= 0.35) {
            if (med_br >= 0.30) { *name_out = "synth bass 2"; return 39; }
            *name_out = "synth bass 1"; return 38;
        }
        if (med_br >= 0.40) { *name_out = "synth bass 2"; return 39; }
        *name_out = "electric bass"; return 33;
    } else if (role == 1) {
        /* Mid Chords / Pad / Rhythm */
        if (med_sus >= 0.42 || med_dur >= 0.36) {
            if (med_br >= 0.28) { *name_out = "synth saw"; return 81; }
            if (med_br >= 0.14) { *name_out = "polysynth pad"; return 90; }
            *name_out = "warm pad"; return 89;
        }
        if (med_br >= 0.35) { *name_out = "synth saw"; return 81; }
        *name_out = "electric piano"; return 4;
    } else {
        /* High Lead / Arp / Melody */
        if (med_pitch >= 64.0 && med_br < 0.10) {
            if (med_dur < 0.65) { *name_out = "celesta"; return 8; }
            *name_out = "synth ocarina"; return 79;
        }
        if (med_br >= 0.28 || (med_eo >= 0.25 && med_br >= 0.18)) {
            *name_out = "synth lead saw"; return 81;
        }
        if (med_sus >= 0.44 || med_dur >= 0.34 || med_br >= 0.10) {
            *name_out = "synth crystal"; return 98;
        }
        *name_out = "celesta"; return 8;
    }
}

/* Cap simultaneous notes in a single role track by keeping the strongest active notes. */
static void limit_role_polyphony(struct cand_note *arr, size_t n, int max_poly) {
    if (max_poly <= 0 || n <= (size_t)max_poly) return;
    /* Check each note's onset against already-kept overlapping notes */
    for (size_t i = 0; i < n; ++i) {
        if (!arr[i].keep) continue;
        double t_chk = arr[i].onset + 0.02;
        size_t active[16];
        int n_act = 0;
        for (size_t j = 0; j <= i; ++j) {
            if (!arr[j].keep) continue;
            if (arr[j].onset <= t_chk && arr[j].offset > t_chk + 0.02) {
                if (n_act < 16) active[n_act++] = j;
            }
        }
        while (n_act > max_poly) {
            /* Drop the weakest active note (preferring keeping stronger salience * amp) */
            int worst = 0;
            double worst_sc = 1e30;
            for (int k = 0; k < n_act; ++k) {
                const struct cand_note *cn = &arr[active[k]];
                double sc = cn->strength * sqrt(cn->amp_lin + 1e-9);
                if (sc < worst_sc) { worst_sc = sc; worst = k; }
            }
            arr[active[worst]].keep = 0;
            active[worst] = active[--n_act];
        }
    }
}

/* Unsupervised median Kick/Snare spectral template subtraction:
 * Estimates the track's own drum-sample body resonance (e.g. pitched/ringing kick sweep
 * or snare shell) as the median excess above local 20th-percentile background across
 * detected hits, then subtracts velocity-scaled templates from m_lo / m_md before HPSS.
 * Leaves sustained bass/chords untouched (already present in local background) and skips
 * automatically on tracks with < 12 hits of that class. */
static void subtract_drum_class_template(float *mag, int T, int nb, int nfft,
                                         double hop_scale,
                                         const struct midi_note *drums, size_t n_drums,
                                         int target_pitch, double f_lo_hz, double f_hi_hz,
                                         int tau_lo, int tau_hi, float sub_gain) {
    if (!mag || !drums || n_drums < 12 || T < 30 || hop_scale <= 0.0) return;

    int k0 = clamp_i((int)floor(f_lo_hz * (double)nfft / (double)IND_SR16), 1, nb - 1);
    int k1 = clamp_i((int)ceil(f_hi_hz * (double)nfft / (double)IND_SR16), k0, nb - 1);
    int nk = k1 - k0 + 1;
    int ntau = tau_hi - tau_lo + 1;
    if (nk <= 0 || ntau <= 0) return;

    /* Collect all hit frames & velocities for this drum class */
    int *h_fr = (int *)malloc(n_drums * sizeof(int));
    double *h_vel = (double *)malloc(n_drums * sizeof(double));
    if (!h_fr || !h_vel) { free(h_fr); free(h_vel); return; }
    size_t nh = 0;
    for (size_t i = 0; i < n_drums; ++i) {
        if (drums[i].pitch != target_pitch) continue;
        int fk = (int)floor(drums[i].onset / hop_scale + 0.5);
        if (fk >= 2 && fk < T - 2) {
            h_fr[nh] = fk;
            h_vel[nh] = (double)drums[i].velocity;
            nh++;
        }
    }
    if (nh < 12) { free(h_fr); free(h_vel); return; }

    double med_vel = ind_percentile(h_vel, nh, 0.50);
    if (med_vel < 1.0) med_vel = 64.0;

    /* Stride up to 96 representative hits evenly across the song for fast O(1) median estimation */
    enum { MAX_TMPL_HITS = 96 };
    int s_fr[MAX_TMPL_HITS];
    size_t ns = 0;
    if (nh <= MAX_TMPL_HITS) {
        for (size_t i = 0; i < nh; ++i) s_fr[ns++] = h_fr[i];
    } else {
        for (size_t i = 0; i < MAX_TMPL_HITS; ++i) {
            size_t idx = (i * nh) / MAX_TMPL_HITS;
            s_fr[ns++] = h_fr[idx];
        }
    }

    /* Mark frames covered by this drum class's hits so local background estimation reads
     * true sustained-chord/bass floor from non-hit gaps instead of absorbing overlapping drum tails */
    uint8_t *near_hit = (uint8_t *)calloc((size_t)T, 1);
    float *s_bg = (float *)calloc(ns * (size_t)nk, sizeof(float));
    float *tmpl = (float *)calloc((size_t)ntau * (size_t)nk, sizeof(float));
    float *vals = (float *)malloc(ns * sizeof(float));
    if (!near_hit || !s_bg || !tmpl || !vals) {
        free(near_hit); free(s_bg); free(tmpl); free(vals); free(h_fr); free(h_vel);
        return;
    }
    int m_lo = (tau_lo < -6) ? -6 : tau_lo;
    int m_hi = (tau_hi > 14) ? 14 : tau_hi;
    for (size_t i = 0; i < nh; ++i) {
        int a = clamp_i(h_fr[i] + m_lo, 0, T - 1);
        int b = clamp_i(h_fr[i] + m_hi, 0, T - 1);
        for (int f = a; f <= b; ++f) near_hit[f] = 1;
    }

    for (size_t i = 0; i < ns; ++i) {
        int fk = s_fr[i];
        float *bg_row = s_bg + i * (size_t)nk;
        int f_non[40], f_all[40];
        int nn = 0, na = 0;
        for (int d = -72; d <= 72; d += 4) {
            int f = clamp_i(fk + d, 0, T - 1);
            f_all[na++] = f;
            if (!near_hit[f]) f_non[nn++] = f;
        }
        const int *flist = (nn >= 6) ? f_non : f_all;
        int nlist = (nn >= 6) ? nn : na;
        int qpct = (nn >= 6) ? 15 : 10;
        for (int ki = 0; ki < nk; ++ki) {
            int k = k0 + ki;
            float wbuf[40];
            for (int w = 0; w < nlist; ++w)
                wbuf[w] = mag[(size_t)flist[w] * (size_t)nb + (size_t)k];
            for (int a = 1; a < nlist; ++a) {
                float key = wbuf[a];
                int b = a - 1;
                while (b >= 0 && wbuf[b] > key) { wbuf[b + 1] = wbuf[b]; --b; }
                wbuf[b + 1] = key;
            }
            int qidx = (nlist * qpct) / 100;
            if (qidx >= nlist) qidx = nlist - 1;
            bg_row[ki] = wbuf[qidx];
        }
    }

    /* Median excess across sampled hits for each (tau, k) */
    for (int ti = 0; ti < ntau; ++ti) {
        int tau = tau_lo + ti;
        float *trow = tmpl + (size_t)ti * (size_t)nk;
        for (int ki = 0; ki < nk; ++ki) {
            int k = k0 + ki;
            int nv = 0;
            for (size_t i = 0; i < ns; ++i) {
                int f = s_fr[i] + tau;
                if (f < 0 || f >= T) continue;
                float ex = mag[(size_t)f * (size_t)nb + (size_t)k] - s_bg[i * (size_t)nk + (size_t)ki];
                vals[nv++] = ex > 0.0f ? ex : 0.0f;
            }
            if (nv >= 8) {
                /* Insertion sort up to 96 floats */
                for (int a = 1; a < nv; ++a) {
                    float key = vals[a];
                    int b = a - 1;
                    while (b >= 0 && vals[b] > key) { vals[b + 1] = vals[b]; --b; }
                    vals[b + 1] = key;
                }
                trow[ki] = vals[nv / 2];
            }
        }
    }

    /* Keep only decaying transient bins (protects any steady sustained pitch) */
    int ti_edge0 = 0;
    int ti_edge1 = ntau - 1;
    for (int ki = 0; ki < nk; ++ki) {
        float pk = 0.0f;
        for (int ti = 0; ti < ntau; ++ti) {
            float v = tmpl[(size_t)ti * (size_t)nk + (size_t)ki];
            if (v > pk) pk = v;
        }
        float e0 = tmpl[(size_t)ti_edge0 * (size_t)nk + (size_t)ki];
        float e1 = tmpl[(size_t)ti_edge1 * (size_t)nk + (size_t)ki];
        if (pk <= 1e-6f || (e0 > 0.88f * pk && e1 > 0.88f * pk)) {
            for (int ti = 0; ti < ntau; ++ti) tmpl[(size_t)ti * (size_t)nk + (size_t)ki] = 0.0f;
        }
    }

    /* Subtract velocity-scaled template at every detected hit (vel ~ sqrt(amp) so amp ~ (vel/med)^2) */
    for (size_t i = 0; i < nh; ++i) {
        int fk = h_fr[i];
        double vr = h_vel[i] / med_vel;
        float alpha = (float)clamp_d(vr * vr, 0.45, 1.40) * sub_gain;
        for (int ti = 0; ti < ntau; ++ti) {
            int f = fk + tau_lo + ti;
            if (f < 0 || f >= T) continue;
            float *mrow = mag + (size_t)f * (size_t)nb;
            const float *trow = tmpl + (size_t)ti * (size_t)nk;
            for (int ki = 0; ki < nk; ++ki) {
                float sv = alpha * trow[ki];
                if (sv > 0.0f) {
                    float nv = mrow[k0 + ki] - sv;
                    mrow[k0 + ki] = nv > 0.0f ? nv : 0.0f;
                }
            }
        }
    }

    free(near_hit); free(s_bg); free(tmpl); free(vals); free(h_fr); free(h_vel);
}

static int extract_pitched_internal(const float *audio_retuned_16k, size_t n_retuned_16k,
                                    double retune_ratio,
                                    const struct midi_note *drum_notes, size_t n_drums,
                                    struct cand_note **cands_out, size_t *n_cands_out,
                                    double *harm_ratio_out,
                                    float **h1_db_out, float **h1_dba_out, int *T_out) {
    *cands_out = NULL;
    *n_cands_out = 0;
    if (harm_ratio_out) *harm_ratio_out = 0.0;
    if (h1_db_out) *h1_db_out = NULL;
    if (h1_dba_out) *h1_dba_out = NULL;
    if (T_out) *T_out = 0;
    if (!audio_retuned_16k || n_retuned_16k < IND_HOP16 * 4) return 1;

    int T = (int)(n_retuned_16k / IND_HOP16);
    if (T < 3) return 1;

    int ok = 0;
    float *m_lo = NULL, *m_md = NULL, *m_hi = NULL;
    float *h_lo = NULL, *h_md = NULL, *h_hi = NULL;
    float *t_lo = NULL, *t_md = NULL, *t_hi = NULL;
    double *h_e = NULL, *p_e = NULL;
    float *act = NULL, *amp = NULL, *raw_env = NULL;
    float *fast_f1 = NULL, *fast_env = NULL, *fast_bg = NULL;
    float *p_h1 = NULL, *p_h2 = NULL, *p_h3 = NULL, *p_h4 = NULL;

    /* 1. Tri-resolution STFT + 2D Median HPSS (keep raw m_md & m_hi until after pitch_frame_worker) */
    h_e = (double *)calloc((size_t)T, sizeof(double));
    p_e = (double *)calloc((size_t)T, sizeof(double));
    if (!h_e || !p_e) goto cleanup;

    double hop_scale = ((double)IND_HOP16 / (double)IND_SR16) * retune_ratio;

    /* Low resolution (8192): strip detected kick/snare body templates before HPSS, then
     * harmonic-floor sub=0.55 preserves mid/low chords without drum dropouts */
    if (!compute_mag_stft(audio_retuned_16k, n_retuned_16k, T, IND_HOP16, IND_NFFT_LO, IND_NB_LO, &m_lo)) goto cleanup;
    if (drum_notes && n_drums >= 12) {
        /* Gentle deep-sub kick removal (35..95 Hz) protects dense breakbeat basslines,
         * while full-tail kick-body removal (95..165 Hz) strips ringing pitched kicks (e.g. B-2) */
        subtract_drum_class_template(m_lo, T, IND_NB_LO, IND_NFFT_LO, hop_scale,
                                     drum_notes, n_drums, 36, 35.0, 95.0, -8, 13, 0.85f);
        subtract_drum_class_template(m_lo, T, IND_NB_LO, IND_NFFT_LO, hop_scale,
                                     drum_notes, n_drums, 36, 95.0, 165.0, -10, 18, 1.00f);
        subtract_drum_class_template(m_lo, T, IND_NB_LO, IND_NFFT_LO, hop_scale,
                                     drum_notes, n_drums, 36, 165.0, 260.0, -8, 13, 0.62f);
        subtract_drum_class_template(m_lo, T, IND_NB_LO, IND_NFFT_LO, hop_scale,
                                     drum_notes, n_drums, 38, 195.0, 260.0, -6, 10, 0.80f);
    }
    h_lo = (float *)malloc((size_t)T * IND_NB_LO * sizeof(float));
    t_lo = (float *)malloc((size_t)T * IND_NB_LO * sizeof(float));
    if (!h_lo || !t_lo) goto cleanup;
    {
        struct hpss_ctx hc = { m_lo, h_lo, NULL, t_lo, NULL, NULL, T, IND_NB_LO, 5, 12, 1.08f, 0.55f };
        nn_parallel_for(T, 32, hpss_worker, &hc);
    }
    free(m_lo); m_lo = NULL;

    /* Mid resolution (2048): strip kick/snare templates then harmonic-floor sub=0.58 */
    if (!compute_mag_stft(audio_retuned_16k, n_retuned_16k, T, IND_HOP16, IND_NFFT_MD, IND_NB_MD, &m_md)) goto cleanup;
    if (drum_notes && n_drums >= 12) {
        subtract_drum_class_template(m_md, T, IND_NB_MD, IND_NFFT_MD, hop_scale,
                                     drum_notes, n_drums, 36, 35.0, 175.0, -4, 12, 0.95f);
        subtract_drum_class_template(m_md, T, IND_NB_MD, IND_NFFT_MD, hop_scale,
                                     drum_notes, n_drums, 38, 195.0, 260.0, -2, 6, 0.75f);
    }
    h_md = (float *)malloc((size_t)T * IND_NB_MD * sizeof(float));
    t_md = (float *)malloc((size_t)T * IND_NB_MD * sizeof(float));
    if (!h_md || !t_md) goto cleanup;
    {
        struct hpss_ctx hc = { m_md, h_md, NULL, t_md, h_e, p_e, T, IND_NB_MD, 4, 10, 1.12f, 0.58f };
        nn_parallel_for(T, 32, hpss_worker, &hc);
    }

    /* High resolution (1024) */
    if (!compute_mag_stft(audio_retuned_16k, n_retuned_16k, T, IND_HOP16, IND_NFFT_HI, IND_NB_HI, &m_hi)) goto cleanup;
    h_hi = (float *)malloc((size_t)T * IND_NB_HI * sizeof(float));
    t_hi = (float *)malloc((size_t)T * IND_NB_HI * sizeof(float));
    if (!h_hi || !t_hi) goto cleanup;
    {
        struct hpss_ctx hc = { m_hi, h_hi, NULL, t_hi, NULL, NULL, T, IND_NB_HI, 3, 8, 1.15f, 0.85f };
        nn_parallel_for(T, 32, hpss_worker, &hc);
    }

    /* Global harmonicity & 95th percentile harmonic amplitude scale */
    double tot_he = 0.0, tot_pe = 0.0;
    double *h_rms = (double *)malloc((size_t)T * sizeof(double));
    if (!h_rms) goto cleanup;
    for (int t = 0; t < T; ++t) {
        tot_he += h_e[t];
        tot_pe += p_e[t];
        h_rms[t] = sqrt(h_e[t]);
    }
    double global_h_p95 = ind_percentile(h_rms, (size_t)T, 0.95);
    free(h_rms);
    if (harm_ratio_out) *harm_ratio_out = tot_he / (tot_he + tot_pe + 1e-18);

    /* 2. Multi-pitch iterative salience + harmonic cancellation */
    size_t tn = (size_t)T * IND_NP;
    act      = (float *)calloc(tn, sizeof(float));
    amp      = (float *)calloc(tn, sizeof(float));
    raw_env  = (float *)calloc(tn, sizeof(float));
    fast_f1  = (float *)calloc(tn, sizeof(float));
    fast_env = (float *)calloc(tn, sizeof(float));
    fast_bg  = (float *)calloc(tn, sizeof(float));
    p_h1     = (float *)calloc(tn, sizeof(float));
    p_h2     = (float *)calloc(tn, sizeof(float));
    p_h3     = (float *)calloc(tn, sizeof(float));
    p_h4     = (float *)calloc(tn, sizeof(float));
    if (!act || !amp || !raw_env || !fast_f1 || !fast_env || !fast_bg || !p_h1 || !p_h2 || !p_h3 || !p_h4) goto cleanup;

    struct pitch_ctx pctx;
    memset(&pctx, 0, sizeof(pctx));
    pctx.t_lo = t_lo; pctx.t_md = t_md; pctx.t_hi = t_hi;
    pctx.h_lo = h_lo; pctx.h_md = h_md; pctx.h_hi = h_hi;
    pctx.m_md = m_md; pctx.m_hi = m_hi;
    pctx.h_e = h_e; pctx.p_e = p_e;
    pctx.global_h_p95 = global_h_p95;
    pctx.T = T;
    pctx.act = act; pctx.amp = amp; pctx.raw_env = raw_env;
    pctx.fast_f1 = fast_f1; pctx.fast_env = fast_env; pctx.fast_bg = fast_bg;
    pctx.p_h1 = p_h1; pctx.p_h2 = p_h2; pctx.p_h3 = p_h3; pctx.p_h4 = p_h4;

    double a_db_tbl[IND_NP];
    for (int pi = 0; pi < IND_NP; ++pi) {
        int midi_p = IND_P_LO + pi;
        double f = 440.0 * exp2((double)(midi_p - 69) / 12.0);
        pctx.p_freq[pi] = f;
        a_db_tbl[pi] = ind_a_weight_db(f);
        double aw = clamp_d(a_db_tbl[pi], -32.0, 1.5);
        double hi_taper = (midi_p > 82) ? (1.0 - 0.025 * (double)(midi_p - 82)) : 1.0;
        if (hi_taper < 0.60) hi_taper = 0.60;
        pctx.p_perc_wt[pi] = pow(10.0, (0.28 * aw) / 20.0) * hi_taper;
    }
    nn_parallel_for(T, 32, pitch_frame_worker, &pctx);

    free(m_md); m_md = NULL; free(m_hi); m_hi = NULL;
    free(h_lo); h_lo = NULL; free(h_md); h_md = NULL; free(h_hi); h_hi = NULL;
    free(t_lo); t_lo = NULL; free(t_md); t_md = NULL; free(t_hi); t_hi = NULL;
    free(h_e); h_e = NULL; free(p_e); p_e = NULL;

    /* 3. Per-pitch Viterbi HMM note decoding */
    if (!decode_pitched_notes(&pctx, retune_ratio, cands_out, n_cands_out)) goto cleanup;

    /* Optional high-resolution HPSS dB/dBA grid for Stage B hybrid verification */
    if (h1_db_out && h1_dba_out) {
        float *db = (float *)malloc(tn * sizeof(float));
        float *dba = (float *)malloc(tn * sizeof(float));
        if (!db || !dba) { free(db); free(dba); free(*cands_out); *cands_out = NULL; *n_cands_out = 0; goto cleanup; }
        for (int t = 0; t < T; ++t) {
            const float *r1 = p_h1 + (size_t)t * IND_NP;
            float *d1 = db + (size_t)t * IND_NP;
            float *da = dba + (size_t)t * IND_NP;
            for (int pi = 0; pi < IND_NP; ++pi) {
                double v = 20.0 * log10((double)r1[pi] + 1e-7);
                d1[pi] = (float)v;
                da[pi] = (float)(v + a_db_tbl[pi]);
            }
        }
        *h1_db_out = db;
        *h1_dba_out = dba;
        if (T_out) *T_out = T;
    }

    ok = 1;

cleanup:
    free(act); free(amp); free(raw_env);
    free(fast_f1); free(fast_env); free(fast_bg);
    free(p_h1); free(p_h2); free(p_h3); free(p_h4);
    free(h_lo); free(h_md); free(h_hi);
    free(t_lo); free(t_md); free(t_hi);
    free(m_lo); free(m_md); free(m_hi);
    free(h_e); free(p_e);
    return ok;
}

int independent_transcribe(const float *audio_native, size_t n_native, unsigned native_rate,
                           const float *audio_retuned_16k, size_t n_retuned_16k,
                           double retune_ratio,
                           struct independent_track **tracks_out, size_t *n_tracks_out,
                           struct independent_stats *stats) {
    *tracks_out = NULL;
    *n_tracks_out = 0;
    if (stats) memset(stats, 0, sizeof(*stats));
    if (!audio_retuned_16k || n_retuned_16k < IND_HOP16 * 4) return 1;

    int ok = 0;
    struct cand_note *cands = NULL;
    size_t n_cands = 0;
    struct midi_note *drum_notes = NULL;
    size_t n_drums = 0;
    double harm_ratio = 0.0;

    /* 1. Native-rate multi-band percussive drum transcription FIRST so detected kick/snare
     *    templates can be cleanly subtracted from the low/mid pitched spectrograms */
    if (!transcribe_drums_dsp(audio_native, n_native, native_rate, &drum_notes, &n_drums, stats))
        goto cleanup;

    if (!extract_pitched_internal(audio_retuned_16k, n_retuned_16k, retune_ratio,
                                  drum_notes, n_drums,
                                  &cands, &n_cands, &harm_ratio, NULL, NULL, NULL))
        goto cleanup;
    if (stats) stats->harmonic_ratio = harm_ratio;

    /* 5. Adaptive register split (duration-weighted pitch histogram valleys) */
    double hist[128];
    memset(hist, 0, sizeof(hist));
    for (size_t i = 0; i < n_cands; ++i) {
        int p = clamp_i(cands[i].pitch, 0, 127);
        hist[p] += (cands[i].offset - cands[i].onset);
    }
    int split_bm = 42; /* default F#2: <=42 Bass, >=43 Mid */
    double min_bm = 1e30;
    for (int p = 39; p <= 45; ++p) {
        double v = 0.25 * hist[p - 1] + 0.50 * hist[p] + 0.25 * hist[p + 1];
        /* Mild tie-break bias toward 42 */
        double score = v + 0.02 * fabs((double)(p - 42));
        if (score < min_bm) { min_bm = score; split_bm = p; }
    }
    int split_mh = 64; /* default E4: <=63 Mid/Chords (keeps C4 triad tops with chords), >=64 High Lead */
    double min_mh = 1e30;
    for (int p = 60; p <= 67; ++p) {
        double v = 0.25 * hist[p - 1] + 0.50 * hist[p] + 0.25 * hist[p + 1];
        double score = v + 0.02 * fabs((double)(p - 64));
        if (score < min_mh) { min_mh = score; split_mh = p; }
    }
    if (stats) {
        stats->split_bass_mid = split_bm;
        stats->split_mid_high = split_mh;
    }

    for (size_t i = 0; i < n_cands; ++i) {
        if (cands[i].pitch <= split_bm) cands[i].role = 0;
        else if (cands[i].pitch < split_mh) cands[i].role = 1;
        else cands[i].role = 2;
    }

    /* Partition into role arrays, apply per-role polyphony limit, and choose GM patches */
    struct independent_track *out = (struct independent_track *)calloc(4, sizeof(*out));
    if (!out) goto cleanup;
    size_t n_out = 0;
    static const int role_max_poly[3] = { 2, 4, 3 };

    for (int r = 0; r < 3; ++r) {
        size_t cnt = 0;
        for (size_t i = 0; i < n_cands; ++i) if (cands[i].role == r) cnt++;
        if (cnt == 0) continue;

        struct cand_note *rc = (struct cand_note *)malloc(cnt * sizeof(*rc));
        if (!rc) { independent_tracks_free(out, n_out); goto cleanup; }
        size_t w = 0;
        for (size_t i = 0; i < n_cands; ++i) if (cands[i].role == r) rc[w++] = cands[i];

        limit_role_polyphony(rc, w, role_max_poly[r]);

        /* Gather surviving notes + track-level timbral medians */
        size_t n_keep = 0;
        for (size_t i = 0; i < w; ++i) if (rc[i].keep) n_keep++;
        if (n_keep == 0) { free(rc); continue; }

        double *pitches = (double *)malloc(n_keep * sizeof(double));
        double *durs    = (double *)malloc(n_keep * sizeof(double));
        double *susts   = (double *)malloc(n_keep * sizeof(double));
        double *brts    = (double *)malloc(n_keep * sizeof(double));
        double *eors    = (double *)malloc(n_keep * sizeof(double));
        double *amps    = (double *)malloc(n_keep * sizeof(double));
        struct midi_note *mn = (struct midi_note *)malloc(n_keep * sizeof(*mn));
        if (!pitches || !durs || !susts || !brts || !eors || !amps || !mn) {
            free(pitches); free(durs); free(susts); free(brts); free(eors); free(amps); free(mn);
            free(rc); independent_tracks_free(out, n_out); goto cleanup;
        }
        size_t k = 0, ns = 0;
        for (size_t i = 0; i < w; ++i) {
            if (!rc[i].keep) continue;
            pitches[k] = (double)rc[i].pitch;
            durs[k] = rc[i].offset - rc[i].onset;
            brts[k] = rc[i].bright;
            eors[k] = rc[i].even_odd;
            amps[k] = rc[i].amp_lin;
            if (rc[i].sustain >= 0.0) susts[ns++] = rc[i].sustain;
            k++;
        }
        double med_p = ind_percentile(pitches, k, 0.50);
        double med_d = ind_percentile(durs, k, 0.50);
        double med_s = (ns >= 3) ? ind_percentile(susts, ns, 0.50) : 0.42;
        double med_b = ind_percentile(brts, k, 0.50);
        double med_e = ind_percentile(eors, k, 0.50);
        double p90_a = ind_percentile(amps, k, 0.90) + 1e-9;

        const char *rname = "synth";
        int prog = choose_role_program(r, med_p, med_d, med_s, med_b, med_e, &rname);

        size_t mw = 0;
        for (size_t i = 0; i < w; ++i) {
            if (!rc[i].keep) continue;
            double rel_db = clamp_d(20.0 * log10((rc[i].amp_lin + 1e-9) / p90_a), -24.0, 4.0);
            int vel = clamp_i((int)floor(104.0 * pow(10.0, rel_db / 40.0) + 0.5), 32, 125);
            mn[mw++] = (struct midi_note){ rc[i].onset, rc[i].offset, rc[i].pitch, vel };
        }
        qsort(mn, mw, sizeof(*mn), cmp_midi_note);

        free(pitches); free(durs); free(susts); free(brts); free(eors); free(amps); free(rc);

        out[n_out++] = (struct independent_track){
            ind_dup_str(rname), prog, 0, mn, mw
        };
        if (stats) stats->pitched_notes += mw;
    }

    if (n_drums > 0) {
        out[n_out++] = (struct independent_track){
            ind_dup_str("Drums"), 0, 1, drum_notes, n_drums
        };
        drum_notes = NULL;
        if (stats) stats->drum_hits = n_drums;
    }

    *tracks_out = out;
    *n_tracks_out = n_out;
    ok = 1;

cleanup:
    free(drum_notes);
    free(cands);
    return ok;
}

/* =========================================================================
 * Stage B: Hybrid Acoustic Rescue (--mode hybrid, zero extra weights)
 * ========================================================================= */

struct hpss_pitch_check {
    double val_raw;
    double val_dba;
    double loc_gap_raw;
    double loc_gap_dba;
    double snr_raw;
    double snr_dba;
};

static double mean_grid_db(const float *mat, int f0, int f1, int pi) {
    double s = 0.0;
    for (int t = f0; t < f1; ++t) s += (double)mat[(size_t)t * IND_NP + (size_t)pi];
    return s / (double)(f1 - f0);
}

static void check_pitch_hpss(const float *h1_db, const float *h1_dba, int T,
                             double retune_ratio, int pitch, double onset, double offset,
                             struct hpss_pitch_check *out) {
    memset(out, 0, sizeof(*out));
    out->val_raw = out->val_dba = -120.0;
    out->loc_gap_raw = out->loc_gap_dba = 30.0;
    out->snr_raw = out->snr_dba = -10.0;

    int pi = pitch - IND_P_LO;
    if (pi < 0 || pi >= IND_NP || T <= 0) return;

    double hop_s = ((double)IND_HOP16 / (double)IND_SR16) * retune_ratio;
    int f0 = clamp_i((int)floor(onset / hop_s + 0.5), 0, T - 1);
    int f1 = clamp_i((int)floor(offset / hop_s + 0.5), f0 + 1, T);
    if (f1 <= f0) f1 = (f0 + 1 <= T) ? (f0 + 1) : T;

    double vr = mean_grid_db(h1_db, f0, f1, pi);
    double va = mean_grid_db(h1_dba, f0, f1, pi);
    out->val_raw = vr;
    out->val_dba = va;

    double max_r = vr, max_a = va;
    for (int d = -2; d <= 2; ++d) {
        int kb = pi + d;
        if (kb >= 0 && kb < IND_NP) {
            double r = mean_grid_db(h1_db, f0, f1, kb);
            double a = mean_grid_db(h1_dba, f0, f1, kb);
            if (r > max_r) max_r = r;
            if (a > max_a) max_a = a;
        }
    }
    out->loc_gap_raw = max_r - vr;
    out->loc_gap_dba = max_a - va;

    double nbr[4], nba[4];
    int nn = 0;
    static const int offs[4] = { -5, -4, 4, 5 };
    for (int i = 0; i < 4; ++i) {
        int kb = pi + offs[i];
        if (kb >= 0 && kb < IND_NP) {
            nbr[nn] = mean_grid_db(h1_db, f0, f1, kb);
            nba[nn] = mean_grid_db(h1_dba, f0, f1, kb);
            nn++;
        }
    }
    double bgr = nn ? median_small_d(nbr, nn) : vr;
    double bga = nn ? median_small_d(nba, nn) : va;
    out->snr_raw = vr - bgr;
    out->snr_dba = va - bga;
}

static size_t dedup_same_pitch(struct midi_note *notes, size_t n) {
    if (n <= 1) return n;
    qsort(notes, n, sizeof(*notes), cmp_midi_note);
    size_t w = 0;
    for (size_t i = 0; i < n; ++i) {
        int dup = 0;
        for (size_t j = w; j > 0; --j) {
            struct midi_note *prev = &notes[j - 1];
            if (notes[i].onset > prev->offset + 0.02) break;
            if (prev->pitch == notes[i].pitch) {
                if (notes[i].onset < prev->offset) {
                    if (fabs(notes[i].onset - prev->onset) <= 0.04) {
                        if (notes[i].offset > prev->offset) prev->offset = notes[i].offset;
                        if (notes[i].velocity > prev->velocity) prev->velocity = notes[i].velocity;
                        dup = 1;
                        break;
                    } else {
                        /* Trim previous offset cleanly to avoid MIDI NoteOff collision */
                        prev->offset = notes[i].onset - 0.005;
                        if (prev->offset < prev->onset + 0.015) prev->offset = prev->onset + 0.015;
                    }
                }
            }
        }
        if (!dup) notes[w++] = notes[i];
    }
    return w;
}

int independent_hybrid_fuse(const struct midi_track *base_tracks, size_t n_base_tracks,
                            const float *audio_retuned_16k, size_t n_retuned_16k,
                            double retune_ratio,
                            struct independent_track **out_tracks, size_t *n_out_tracks,
                            struct hybrid_stats *stats) {
    *out_tracks = NULL;
    *n_out_tracks = 0;
    if (stats) memset(stats, 0, sizeof(*stats));
    if (!base_tracks || n_base_tracks == 0) return 1;

    struct cand_note *cands = NULL;
    size_t n_cands = 0;
    float *h1_db = NULL, *h1_dba = NULL;
    int T = 0;
    if (!extract_pitched_internal(audio_retuned_16k, n_retuned_16k, retune_ratio,
                                  NULL, 0,
                                  &cands, &n_cands, NULL, &h1_db, &h1_dba, &T)) {
        return 0;
    }
    if (stats) stats->dsp_candidates = n_cands;

    int ok = 0;
    struct hpss_pitch_check *cand_chk = NULL;
    uint8_t **keep_base = NULL;
    struct hpss_pitch_check **base_chk = NULL;
    struct midi_note *resc_bass = NULL, *resc_mid = NULL;
    double *resc_bass_br = NULL, *resc_mid_br = NULL, *resc_mid_eo = NULL;
    size_t n_rb = 0, n_rm = 0;

    /* Global 95th percentile frame-peak raw dB (for bass) & A-weighted dBA (for mid/high) */
    double song_p95_raw = -40.0;
    double song_p95_dba = -40.0;
    if (T > 0 && h1_db && h1_dba) {
        double *fmax_r = (double *)malloc((size_t)T * sizeof(double));
        double *fmax_a = (double *)malloc((size_t)T * sizeof(double));
        if (fmax_r && fmax_a) {
            for (int t = 0; t < T; ++t) {
                const float *rr = h1_db + (size_t)t * IND_NP;
                const float *ra = h1_dba + (size_t)t * IND_NP;
                float mxr = rr[0], mxa = ra[0];
                for (int pi = 1; pi < IND_NP; ++pi) {
                    if (rr[pi] > mxr) mxr = rr[pi];
                    if (ra[pi] > mxa) mxa = ra[pi];
                }
                fmax_r[t] = (double)mxr;
                fmax_a[t] = (double)mxa;
            }
            song_p95_raw = ind_percentile(fmax_r, (size_t)T, 0.95);
            song_p95_dba = ind_percentile(fmax_a, (size_t)T, 0.95);
        }
        free(fmax_r);
        free(fmax_a);
    }

    cand_chk = n_cands ? (struct hpss_pitch_check *)calloc(n_cands, sizeof(*cand_chk)) : NULL;
    keep_base = (uint8_t **)calloc(n_base_tracks, sizeof(*keep_base));
    base_chk = (struct hpss_pitch_check **)calloc(n_base_tracks, sizeof(*base_chk));
    if ((n_cands && !cand_chk) || !keep_base || !base_chk) goto cleanup;

    for (size_t i = 0; i < n_cands; ++i) {
        check_pitch_hpss(h1_db, h1_dba, T, retune_ratio,
                         cands[i].pitch, cands[i].onset, cands[i].offset, &cand_chk[i]);
    }

    /* Measure all base Dettato pitched notes on the 8192-pt HPSS pitch grid */
    int existing_bass_track = -1;
    for (size_t ti = 0; ti < n_base_tracks; ++ti) {
        size_t cnt = base_tracks[ti].count;
        if (base_tracks[ti].is_drum || cnt == 0) continue;
        keep_base[ti] = (uint8_t *)malloc(cnt);
        base_chk[ti] = (struct hpss_pitch_check *)calloc(cnt, sizeof(**base_chk));
        if (!keep_base[ti] || !base_chk[ti]) goto cleanup;
        memset(keep_base[ti], 1, cnt);

        double *ps = (double *)malloc(cnt * sizeof(double));
        for (size_t i = 0; i < cnt; ++i) {
            const struct midi_note *nt = &base_tracks[ti].notes[i];
            if (ps) ps[i] = (double)nt->pitch;
            check_pitch_hpss(h1_db, h1_dba, T, retune_ratio,
                             nt->pitch, nt->onset, nt->offset, &base_chk[ti][i]);
        }
        if (ps) {
            double med_p = ind_percentile(ps, cnt, 0.50);
            /* Prefer a genuine sustained bass track (GM 32..39) as target for rescued bass */
            if (med_p <= 44.0) {
                int is_bass_gm = (base_tracks[ti].program >= 32 && base_tracks[ti].program <= 39);
                if (existing_bass_track < 0 || is_bass_gm) existing_bass_track = (int)ti;
            }
            free(ps);
        }
    }

    /* Step H1: Drop Dettato stuck/wrong-pitch notes where HPSS peak verification clearly fails
     * AND pure-DSP detects a strong verified competing note in the same register */
    for (size_t ti = 0; ti < n_base_tracks; ++ti) {
        if (base_tracks[ti].is_drum || !keep_base[ti]) continue;
        for (size_t i = 0; i < base_tracks[ti].count; ++i) {
            const struct midi_note *nt = &base_tracks[ti].notes[i];
            const struct hpss_pitch_check *chk = &base_chk[ti][i];
            int is_bass = (nt->pitch <= 44);
            double gap = is_bass ? chk->loc_gap_raw : chk->loc_gap_dba;
            double snr = is_bass ? chk->snr_raw : chk->snr_dba;
            int clearly_wrong = (gap > 2.2 && snr < 3.5) || (gap > 4.0 && snr < 5.5);
            int bass_off_peak = (is_bass && gap > 1.4 && snr < 5.5);
            if (!clearly_wrong && !bass_off_peak) continue;

            double nd = nt->offset - nt->onset;
            if (nd <= 0.0) continue;
            int has_dsp_comp = 0;
            for (size_t j = 0; j < n_cands; ++j) {
                if (cands[j].onset > nt->offset) break;
                if (cands[j].offset < nt->onset) continue;
                if (cands[j].pitch == nt->pitch) continue;
                int same_reg = (is_bass && cands[j].pitch <= 45) ||
                               (!is_bass && abs(cands[j].pitch - nt->pitch) <= 5);
                if (!same_reg) continue;
                double ov = fmin(nt->offset, cands[j].offset) - fmax(nt->onset, cands[j].onset);
                if (ov < 0.35 * fmin(nd, cands[j].offset - cands[j].onset)) continue;
                double dg = (cands[j].pitch <= 44) ? cand_chk[j].loc_gap_raw : cand_chk[j].loc_gap_dba;
                double ds = (cands[j].pitch <= 44) ? cand_chk[j].snr_raw : cand_chk[j].snr_dba;
                if (cands[j].strength >= 1.15 && dg <= 1.5 && ds >= 6.0) {
                    if (clearly_wrong || (bass_off_peak && cand_chk[j].val_raw >= chk->val_raw + 2.5)) {
                        has_dsp_comp = 1;
                        break;
                    }
                }
            }
            if (has_dsp_comp) {
                keep_base[ti][i] = 0;
                if (stats) stats->dettato_wrong_dropped++;
            }
        }
    }

    /* Step H2: Rescue high-confidence missed bass & prominent sustained mid-high notes */
    resc_bass = n_cands ? (struct midi_note *)malloc(n_cands * sizeof(*resc_bass)) : NULL;
    resc_mid  = n_cands ? (struct midi_note *)malloc(n_cands * sizeof(*resc_mid)) : NULL;
    resc_bass_br = n_cands ? (double *)malloc(n_cands * sizeof(double)) : NULL;
    resc_mid_br  = n_cands ? (double *)malloc(n_cands * sizeof(double)) : NULL;
    resc_mid_eo  = n_cands ? (double *)malloc(n_cands * sizeof(double)) : NULL;
    if (n_cands && (!resc_bass || !resc_mid || !resc_bass_br || !resc_mid_br || !resc_mid_eo))
        goto cleanup;

    for (size_t j = 0; j < n_cands; ++j) {
        const struct cand_note *d = &cands[j];
        const struct hpss_pitch_check *dc = &cand_chk[j];
        double dur = d->offset - d->onset;
        int is_bass = (d->pitch <= 44);

        if (is_bass) {
            if (dur < 0.16 || d->strength < 1.15) continue;
            if (dc->loc_gap_raw > 1.2 || dc->snr_raw < 6.5) continue;
            /* Unweighted raw dB gate so deep sub-bass (E1=41 Hz, G1=49 Hz, G#1=52 Hz)
             * is not killed by A-weighting's -34 dB roll-off below 60 Hz! */
            if (dc->val_raw < song_p95_raw - 24.0) continue;
        } else {
            if (d->pitch < 45 || d->pitch > 79) continue;
            if (dur < 0.32 || d->strength < 1.25) continue;
            if (dc->loc_gap_dba > 1.2 || dc->snr_dba < 8.5) continue;
            if (dc->val_dba < song_p95_dba - 17.0) continue;
        }

        /* Check against all surviving Dettato pitched notes for coverage / overtone / bass conflict */
        int covered = 0;
        int is_overtone = 0;
        int bass_verified_present = 0;

        for (size_t ti = 0; ti < n_base_tracks && !covered && !is_overtone; ++ti) {
            if (base_tracks[ti].is_drum || !keep_base[ti]) continue;
            for (size_t i = 0; i < base_tracks[ti].count; ++i) {
                if (!keep_base[ti][i]) continue;
                const struct midi_note *nt = &base_tracks[ti].notes[i];
                if (nt->onset > d->offset + 0.05) break;
                if (nt->offset < d->onset - 0.05) continue;
                double ov = fmin(nt->offset, d->offset) - fmax(nt->onset, d->onset);
                if (ov <= 0.0) continue;

                if (nt->pitch == d->pitch && (ov >= 0.30 * dur || fabs(nt->onset - d->onset) <= 0.08)) {
                    covered = 1;
                    break;
                }
                /* Overtone check against stronger surviving lower Dettato note */
                if (!is_bass) {
                    int dp = d->pitch - nt->pitch;
                    if ((dp == 12 || dp == 19 || dp == 24 || dp == 28) && ov >= 0.50 * dur) {
                        if (base_chk[ti][i].val_raw > dc->val_raw + 2.5) {
                            is_overtone = 1;
                            break;
                        }
                    }
                } else if (nt->pitch <= 44 && ov >= 0.45 * dur) {
                    /* Dettato already has an acoustically verified bass note covering this span */
                    if (base_chk[ti][i].loc_gap_raw <= 1.8 && base_chk[ti][i].snr_raw >= 4.5 &&
                        base_chk[ti][i].val_raw >= dc->val_raw - 5.0) {
                        bass_verified_present = 1;
                    }
                }
            }
        }
        if (covered || is_overtone) continue;
        if (is_bass && bass_verified_present) continue;

        /* Also skip mid-high rescue if it is an overtone of an already-rescued stronger bass note */
        if (!is_bass) {
            int ot_rb = 0;
            for (size_t k = 0; k < n_rb; ++k) {
                int dp = d->pitch - resc_bass[k].pitch;
                if (dp == 12 || dp == 19 || dp == 24) {
                    double ov = fmin(resc_bass[k].offset, d->offset) - fmax(resc_bass[k].onset, d->onset);
                    if (ov >= 0.55 * dur) { ot_rb = 1; break; }
                }
            }
            if (ot_rb) continue;
        }

        /* High initial velocity (96) ensures enhance.c treats rescued notes as high-confidence
         * before calibrating exact acoustic velocities + CC7 + CC11! */
        struct midi_note rn = { d->onset, d->offset, d->pitch, 96 };
        if (is_bass) {
            resc_bass_br[n_rb] = d->bright;
            resc_bass[n_rb++] = rn;
        } else {
            resc_mid_br[n_rm] = d->bright;
            resc_mid_eo[n_rm] = d->even_odd;
            resc_mid[n_rm++] = rn;
        }
    }

    /* Assemble fused tracks */
    int add_bass_tr = (n_rb > 0 && existing_bass_track < 0) ? 1 : 0;
    int add_mid_tr  = (n_rm > 0) ? 1 : 0;
    size_t max_tr = n_base_tracks + (size_t)add_bass_tr + (size_t)add_mid_tr;
    struct independent_track *out = (struct independent_track *)calloc(max_tr ? max_tr : 1, sizeof(*out));
    if (!out) goto cleanup;
    size_t n_out = 0;

    for (size_t ti = 0; ti < n_base_tracks; ++ti) {
        const struct midi_track *bt = &base_tracks[ti];
        if (bt->is_drum) {
            if (bt->count == 0) continue;
            struct midi_note *dn = (struct midi_note *)malloc(bt->count * sizeof(*dn));
            if (!dn) { independent_tracks_free(out, n_out); goto cleanup; }
            memcpy(dn, bt->notes, bt->count * sizeof(*dn));
            out[n_out++] = (struct independent_track){
                ind_dup_str(bt->name ? bt->name : "Drums"), 0, 1, dn, bt->count
            };
            continue;
        }

        size_t nk = 0;
        if (keep_base[ti]) {
            for (size_t i = 0; i < bt->count; ++i) if (keep_base[ti][i]) nk++;
        }
        size_t extra = ((int)ti == existing_bass_track) ? n_rb : 0;
        if (nk + extra == 0) continue;

        struct midi_note *mn = (struct midi_note *)malloc((nk + extra) * sizeof(*mn));
        if (!mn) { independent_tracks_free(out, n_out); goto cleanup; }
        size_t w = 0;
        for (size_t i = 0; i < bt->count; ++i) {
            if (keep_base[ti][i]) mn[w++] = bt->notes[i];
        }
        if (extra > 0) {
            memcpy(mn + w, resc_bass, n_rb * sizeof(*mn));
            w += n_rb;
            if (stats) stats->bass_rescued += n_rb;
        }
        w = dedup_same_pitch(mn, w);
        out[n_out++] = (struct independent_track){
            ind_dup_str(bt->name ? bt->name : "Track"), bt->program, 0, mn, w
        };
    }

    if (add_bass_tr) {
        struct midi_note *mn = (struct midi_note *)malloc(n_rb * sizeof(*mn));
        if (!mn) { independent_tracks_free(out, n_out); goto cleanup; }
        memcpy(mn, resc_bass, n_rb * sizeof(*mn));
        size_t w = dedup_same_pitch(mn, n_rb);
        double mb = ind_percentile(resc_bass_br, n_rb, 0.50);
        int prog = (mb >= 0.30) ? 39 : 38;
        out[n_out++] = (struct independent_track){
            ind_dup_str("synth bass rescue"), prog, 0, mn, w
        };
        if (stats) { stats->bass_rescued += w; stats->rescue_tracks_added++; }
    }

    if (add_mid_tr) {
        struct midi_note *mn = (struct midi_note *)malloc(n_rm * sizeof(*mn));
        if (!mn) { independent_tracks_free(out, n_out); goto cleanup; }
        memcpy(mn, resc_mid, n_rm * sizeof(*mn));
        size_t w = dedup_same_pitch(mn, n_rm);
        double mb = ind_percentile(resc_mid_br, n_rm, 0.50);
        double me = ind_percentile(resc_mid_eo, n_rm, 0.50);
        int prog = (mb >= 0.14 || me >= 0.20) ? 81 : 90;
        out[n_out++] = (struct independent_track){
            ind_dup_str("synth lead rescue"), prog, 0, mn, w
        };
        if (stats) { stats->mid_high_rescued += w; stats->rescue_tracks_added++; }
    }

    *out_tracks = out;
    *n_out_tracks = n_out;
    ok = 1;

cleanup:
    free(resc_bass); free(resc_mid);
    free(resc_bass_br); free(resc_mid_br); free(resc_mid_eo);
    if (keep_base) {
        for (size_t ti = 0; ti < n_base_tracks; ++ti) free(keep_base[ti]);
        free(keep_base);
    }
    if (base_chk) {
        for (size_t ti = 0; ti < n_base_tracks; ++ti) free(base_chk[ti]);
        free(base_chk);
    }
    free(cand_chk);
    free(h1_db); free(h1_dba);
    free(cands);
    return ok;
}
