/* Acoustic verification, ghost/bleed pruning, smart GM program refinement, and
 * orthogonal audio-driven MIDI dynamics (CC7 + CC11 + velocity + optional CC74).
 *
 * Dynamics decomposition (zero double-counting):
 *   - CC11(t): tracks smooth macro loudness envelope M_db(t) - M_peak_db via exact
 *              SF2/GM concave inverse curve: v = 127 * 10^(delta_db / 40).
 *   - vel(note): tracks note's local acoustic accent relative to its track's median
 *                prominence above M_db(t_note).
 *   - CC7(track): balances tracks according to each track's median acoustic prominence
 *                 above M_db + gentle GM patch loudness normalization. */
#include "enhance.h"
#include "features.h"
#include "nn.h"
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

enum {
    EN_HOP_16K = 320,      /* 20 ms at 16 kHz (50 Hz) */
    EN_NFFT_LO = 4096,     /* 256 ms window (3.9 Hz bin) for MIDI 21..53 */
    EN_NFFT_HI = 1024,     /* 64 ms window (15.6 Hz bin) for MIDI 54..108 + global */
    EN_NFFT_NAT = 1024,    /* ~23 ms window at 44.1 kHz for drum bands + centroid */
    EN_PITCH_LO = 21,      /* A0 */
    EN_N_PITCH = 88,       /* MIDI 21..108 (C8) */
    EN_PITCH_SPLIT = 54    /* F#3: below uses 4096-pt FFT, >= uses 1024-pt FFT */
};

static const double EN_TAU = 6.2831853071795864769;

void enhance_opts_default(struct enhance_opts *opts) {
    opts->prune_ghosts = 1;
    opts->refine_gm = 1;
    opts->audio_dynamics = 1;
    opts->emit_cc74 = 1;
}

void enhance_tracks_free(struct enhance_track *tracks, size_t n_tracks) {
    if (!tracks) return;
    for (size_t i = 0; i < n_tracks; ++i) {
        free(tracks[i].name);
        free(tracks[i].notes);
        free(tracks[i].ccs);
    }
    free(tracks);
}

static int clamp_i(int v, int lo, int hi) {
    return v < lo ? lo : (v > hi ? hi : v);
}

static double clamp_d(double v, double lo, double hi) {
    return v < lo ? lo : (v > hi ? hi : v);
}

static int cmp_double(const void *pa, const void *pb) {
    double a = *(const double *)pa, b = *(const double *)pb;
    return (a > b) - (a < b);
}

static double percentile_copy(const double *arr, size_t n, double q) {
    if (!n) return 0.0;
    double *tmp = (double *)malloc(n * sizeof(double));
    if (!tmp) return arr[0];
    memcpy(tmp, arr, n * sizeof(double));
    qsort(tmp, n, sizeof(double), cmp_double);
    double idx = q * (double)(n - 1);
    size_t i0 = (size_t)floor(idx);
    size_t i1 = i0 + 1 < n ? i0 + 1 : n - 1;
    double f = idx - (double)i0;
    double v = tmp[i0] * (1.0 - f) + tmp[i1] * f;
    free(tmp);
    return v;
}

static double a_weight_db(double f) {
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

/* Convert relative dB (<= 0) to MIDI 0..127 using exact SF2/FluidSynth concave curve (40*log10(v/127)). */
static int db_to_cc(double delta_db, int base_cc, int lo, int hi) {
    double v = (double)base_cc * pow(10.0, delta_db / 40.0);
    return clamp_i((int)floor(v + 0.5), lo, hi);
}

static void en_fft_f64(double *re, double *im, int n) {
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
        double ang = -EN_TAU / (double)span;
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

/* =========================================================================
 * Parallel acoustic analysis grid (50 Hz = 20 ms hop)
 * ========================================================================= */

struct pitch_bin_spec {
    int use_lo;      /* 1 = EN_NFFT_LO, 0 = EN_NFFT_HI */
    int k0, k1;      /* inclusive FFT bin range */
    double center;   /* fractional FFT bin */
    double radius;   /* half-bandwidth in FFT bins */
    double a_db;     /* A-weighting offset (dB) */
};

struct acoustic_grid {
    int T;              /* number of 20 ms frames */
    float *e_raw_db;    /* [T, EN_N_PITCH] narrowband pitch power (dB) */
    float *e_dba;       /* [T, EN_N_PITCH] A-weighted pitch power (dB) */
    double *macro_db;   /* [T] smoothed macro loudness (0.6 dBA + 0.4 unweighted RMS dB) */
    double *band_lo_db; /* [T] smoothed < 200 Hz band dB */
    double *band_md_db; /* [T] smoothed 200..1500 Hz band dB */
    double *band_hi_db; /* [T] smoothed 1500..12000 Hz band dB */
    double *cent_hz;    /* [T] smoothed spectral centroid (Hz) */
    double *kick_db;    /* [T] 30..160 Hz dB (native rate) */
    double *snare_db;   /* [T] 180..1800 Hz dB (native rate) */
    double *hat_db;     /* [T] 3500..12000 Hz dB (native rate) */
    double *hat_flux;   /* [T] positive log-flux of 3500..12000 Hz */
    double macro_peak_db;
    double band_peak_db[3];
    double med_cent_hz;
};

static void acoustic_grid_free(struct acoustic_grid *g) {
    if (!g) return;
    free(g->e_raw_db); free(g->e_dba);
    free(g->macro_db); free(g->band_lo_db); free(g->band_md_db); free(g->band_hi_db);
    free(g->cent_hz);
    free(g->kick_db); free(g->snare_db); free(g->hat_db); free(g->hat_flux);
    memset(g, 0, sizeof(*g));
}

struct p16_ctx {
    const float *a16;
    size_t n16;
    int T;
    const double *win_lo, *win_hi;
    const struct pitch_bin_spec *bins;
    float *e_raw_db, *e_dba;
    double *rms_db;
    int oom;
};

static void p16_worker(int start, int end, void *arg) {
    struct p16_ctx *c = (struct p16_ctx *)arg;
    double *re_lo = (double *)malloc(EN_NFFT_LO * sizeof(double));
    double *im_lo = (double *)malloc(EN_NFFT_LO * sizeof(double));
    double *pw_lo = (double *)malloc((EN_NFFT_LO / 2 + 1) * sizeof(double));
    double re_hi[EN_NFFT_HI], im_hi[EN_NFFT_HI], pw_hi[EN_NFFT_HI / 2 + 1];
    if (!re_lo || !im_lo || !pw_lo) {
        __atomic_store_n(&c->oom, 1, __ATOMIC_RELAXED);
        free(re_lo); free(im_lo); free(pw_lo); return;
    }

    const double norm_lo = 4.0 / ((double)EN_NFFT_LO * (double)EN_NFFT_LO * 0.25);
    const double norm_hi = 4.0 / ((double)EN_NFFT_HI * (double)EN_NFFT_HI * 0.25);

    for (int t = start; t < end; ++t) {
        int center = t * EN_HOP_16K;
        /* Long FFT for low pitches */
        for (int i = 0; i < EN_NFFT_LO; ++i) {
            int idx = center + i - EN_NFFT_LO / 2;
            re_lo[i] = (idx >= 0 && (size_t)idx < c->n16) ? (double)c->a16[idx] * c->win_lo[i] : 0.0;
            im_lo[i] = 0.0;
        }
        en_fft_f64(re_lo, im_lo, EN_NFFT_LO);
        for (int k = 0; k <= EN_NFFT_LO / 2; ++k)
            pw_lo[k] = (re_lo[k] * re_lo[k] + im_lo[k] * im_lo[k]) * norm_lo;

        /* Short FFT for mid/high pitches + RMS */
        double s2 = 0.0;
        for (int i = 0; i < EN_NFFT_HI; ++i) {
            int idx = center + i - EN_NFFT_HI / 2;
            double s = (idx >= 0 && (size_t)idx < c->n16) ? (double)c->a16[idx] : 0.0;
            s2 += s * s;
            re_hi[i] = s * c->win_hi[i];
            im_hi[i] = 0.0;
        }
        c->rms_db[t] = 10.0 * log10(s2 / (double)EN_NFFT_HI + 1e-12);
        en_fft_f64(re_hi, im_hi, EN_NFFT_HI);
        for (int k = 0; k <= EN_NFFT_HI / 2; ++k)
            pw_hi[k] = (re_hi[k] * re_hi[k] + im_hi[k] * im_hi[k]) * norm_hi;

        float *row_raw = c->e_raw_db + (size_t)t * EN_N_PITCH;
        float *row_dba = c->e_dba + (size_t)t * EN_N_PITCH;
        for (int p = 0; p < EN_N_PITCH; ++p) {
            const struct pitch_bin_spec *b = &c->bins[p];
            const double *pw = b->use_lo ? pw_lo : pw_hi;
            double num = 0.0, den = 0.0;
            for (int k = b->k0; k <= b->k1; ++k) {
                double w = 1.0 - fabs((double)k - b->center) / b->radius;
                if (w > 0.0) { num += w * pw[k]; den += w; }
            }
            double val = (den > 0.0) ? (num / den) : 0.0;
            double db = 10.0 * log10(val + 1e-12);
            row_raw[p] = (float)db;
            row_dba[p] = (float)(db + b->a_db);
        }
    }
    free(re_lo); free(im_lo); free(pw_lo);
}

struct pnat_ctx {
    const float *anat;
    size_t n_nat;
    unsigned sr;
    int T;
    const double *win;
    const double *a_lin;
    const double *freqs;
    double *dba_raw, *band_lo, *band_md, *band_hi, *cent_raw;
    double *kick_db, *snare_db, *hat_db, *hat_lp;
};

static void pnat_worker(int start, int end, void *arg) {
    const struct pnat_ctx *c = (const struct pnat_ctx *)arg;
    double re[EN_NFFT_NAT], im[EN_NFFT_NAT];
    double hop_nat = 0.02 * (double)c->sr;
    double norm = 4.0 / ((double)EN_NFFT_NAT * (double)EN_NFFT_NAT * 0.25);

    for (int t = start; t < end; ++t) {
        int center = (int)floor((double)t * hop_nat + 0.5);
        for (int i = 0; i < EN_NFFT_NAT; ++i) {
            int idx = center + i - EN_NFFT_NAT / 2;
            re[i] = (idx >= 0 && (size_t)idx < c->n_nat) ? (double)c->anat[idx] * c->win[i] : 0.0;
            im[i] = 0.0;
        }
        en_fft_f64(re, im, EN_NFFT_NAT);
        double p_dba = 0.0, p_lo = 0.0, p_md = 0.0, p_hi = 0.0;
        double p_kick = 0.0, p_snare = 0.0, p_hat = 0.0;
        double c_num = 0.0, c_den = 0.0;
        for (int k = 1; k <= EN_NFFT_NAT / 2; ++k) {
            double f = c->freqs[k];
            double pw = (re[k] * re[k] + im[k] * im[k]) * norm;
            double pa = pw * c->a_lin[k];
            if (f >= 20.0 && f <= 14000.0) p_dba += pa;
            if (f >= 20.0 && f < 200.0) p_lo += pw;
            if (f >= 200.0 && f < 1500.0) p_md += pa;
            if (f >= 1500.0 && f <= 12000.0) p_hi += pa;
            if (f >= 30.0 && f <= 160.0) p_kick += pw;
            if (f >= 180.0 && f <= 1800.0) p_snare += pw;
            if (f >= 3500.0 && f <= 12000.0) p_hat += pw;
            if (f >= 60.0 && f <= 12000.0) { c_num += f * pw; c_den += pw; }
        }
        c->dba_raw[t] = 10.0 * log10(p_dba + 1e-12);
        c->band_lo[t] = 10.0 * log10(p_lo + 1e-12);
        c->band_md[t] = 10.0 * log10(p_md + 1e-12);
        c->band_hi[t] = 10.0 * log10(p_hi + 1e-12);
        c->kick_db[t] = 10.0 * log10(p_kick + 1e-12);
        c->snare_db[t] = 10.0 * log10(p_snare + 1e-12);
        c->hat_db[t] = 10.0 * log10(p_hat + 1e-12);
        c->hat_lp[t] = log1p(1e5 * p_hat);
        c->cent_raw[t] = (c_den > 1e-12) ? (c_num / c_den) : 1000.0;
    }
}

static void box_smooth(const double *src, double *dst, int n, int half_w) {
    for (int i = 0; i < n; ++i) {
        int a = i - half_w > 0 ? i - half_w : 0;
        int b = i + half_w < n ? i + half_w : n - 1;
        double s = 0.0;
        for (int j = a; j <= b; ++j) s += src[j];
        dst[i] = s / (double)(b - a + 1);
    }
}

static int build_acoustic_grid(const float *audio_native, size_t n_native, unsigned native_rate,
                               const float *audio_16k, size_t n_16k,
                               struct acoustic_grid *g) {
    memset(g, 0, sizeof(*g));
    int T = (int)(n_16k / EN_HOP_16K);
    if (T < 1) T = 1;
    g->T = T;

    g->e_raw_db = (float *)calloc((size_t)T * EN_N_PITCH, sizeof(float));
    g->e_dba = (float *)calloc((size_t)T * EN_N_PITCH, sizeof(float));
    g->macro_db = (double *)calloc((size_t)T, sizeof(double));
    g->band_lo_db = (double *)calloc((size_t)T, sizeof(double));
    g->band_md_db = (double *)calloc((size_t)T, sizeof(double));
    g->band_hi_db = (double *)calloc((size_t)T, sizeof(double));
    g->cent_hz = (double *)calloc((size_t)T, sizeof(double));
    g->kick_db = (double *)calloc((size_t)T, sizeof(double));
    g->snare_db = (double *)calloc((size_t)T, sizeof(double));
    g->hat_db = (double *)calloc((size_t)T, sizeof(double));
    g->hat_flux = (double *)calloc((size_t)T, sizeof(double));

    double *rms_db = (double *)calloc((size_t)T, sizeof(double));
    double *dba_raw = (double *)calloc((size_t)T, sizeof(double));
    double *blo_raw = (double *)calloc((size_t)T, sizeof(double));
    double *bmd_raw = (double *)calloc((size_t)T, sizeof(double));
    double *bhi_raw = (double *)calloc((size_t)T, sizeof(double));
    double *cent_raw = (double *)calloc((size_t)T, sizeof(double));
    double *hat_lp = (double *)calloc((size_t)T, sizeof(double));
    double *macro_raw = (double *)calloc((size_t)T, sizeof(double));

    if (!g->e_raw_db || !g->e_dba || !g->macro_db || !g->band_lo_db || !g->band_md_db ||
        !g->band_hi_db || !g->cent_hz || !g->kick_db || !g->snare_db || !g->hat_db ||
        !g->hat_flux || !rms_db || !dba_raw || !blo_raw || !bmd_raw || !bhi_raw ||
        !cent_raw || !hat_lp || !macro_raw) {
        free(rms_db); free(dba_raw); free(blo_raw); free(bmd_raw);
        free(bhi_raw); free(cent_raw); free(hat_lp); free(macro_raw);
        acoustic_grid_free(g);
        return 0;
    }

    double win_lo[EN_NFFT_LO], win_hi[EN_NFFT_HI], win_nat[EN_NFFT_NAT];
    for (int i = 0; i < EN_NFFT_LO; ++i)
        win_lo[i] = 0.5 - 0.5 * cos(EN_TAU * (double)i / (double)(EN_NFFT_LO - 1));
    for (int i = 0; i < EN_NFFT_HI; ++i)
        win_hi[i] = 0.5 - 0.5 * cos(EN_TAU * (double)i / (double)(EN_NFFT_HI - 1));
    for (int i = 0; i < EN_NFFT_NAT; ++i)
        win_nat[i] = 0.5 - 0.5 * cos(EN_TAU * (double)i / (double)(EN_NFFT_NAT - 1));

    struct pitch_bin_spec bins[EN_N_PITCH];
    double semi_half = exp2(0.5 / 12.0) - 1.0;
    for (int p = 0; p < EN_N_PITCH; ++p) {
        int midi_p = EN_PITCH_LO + p;
        double f = 440.0 * exp2((double)(midi_p - 69) / 12.0);
        int use_lo = (midi_p < EN_PITCH_SPLIT) ? 1 : 0;
        int nfft = use_lo ? EN_NFFT_LO : EN_NFFT_HI;
        double center = f * (double)nfft / (double)MODEL_RATE;
        double rad = f * semi_half * (double)nfft / (double)MODEL_RATE;
        if (rad < 1.15) rad = 1.15;
        int k0 = (int)floor(center - rad);
        int k1 = (int)ceil(center + rad);
        if (k0 < 1) k0 = 1;
        if (k1 > nfft / 2) k1 = nfft / 2;
        bins[p] = (struct pitch_bin_spec){ use_lo, k0, k1, center, rad, a_weight_db(f) };
    }

    struct p16_ctx c16 = { audio_16k, n_16k, T, win_lo, win_hi, bins, g->e_raw_db, g->e_dba, rms_db, 0 };
    nn_parallel_for(T, 32, p16_worker, &c16);
    if (c16.oom) {
        free(rms_db); free(dba_raw); free(blo_raw); free(bmd_raw);
        free(bhi_raw); free(cent_raw); free(hat_lp); free(macro_raw);
        acoustic_grid_free(g);
        return 0;
    }

    double freqs_nat[EN_NFFT_NAT / 2 + 1], a_lin_nat[EN_NFFT_NAT / 2 + 1];
    for (int k = 0; k <= EN_NFFT_NAT / 2; ++k) {
        freqs_nat[k] = (double)k * (double)native_rate / (double)EN_NFFT_NAT;
        a_lin_nat[k] = pow(10.0, a_weight_db(freqs_nat[k]) / 10.0);
    }
    struct pnat_ctx cnat = {
        audio_native, n_native, native_rate, T, win_nat, a_lin_nat, freqs_nat,
        dba_raw, blo_raw, bmd_raw, bhi_raw, cent_raw,
        g->kick_db, g->snare_db, g->hat_db, hat_lp
    };
    nn_parallel_for(T, 64, pnat_worker, &cnat);

    for (int t = 0; t < T; ++t) {
        macro_raw[t] = 0.60 * dba_raw[t] + 0.40 * rms_db[t];
        g->hat_flux[t] = (t > 0 && hat_lp[t] > hat_lp[t - 1]) ? (hat_lp[t] - hat_lp[t - 1]) : 0.0;
    }

    /* Smooth macro & band envelopes (+/- 4 frames = 180 ms box) and centroid (+/- 3 frames = 140 ms) */
    box_smooth(macro_raw, g->macro_db, T, 4);
    box_smooth(blo_raw, g->band_lo_db, T, 4);
    box_smooth(bmd_raw, g->band_md_db, T, 4);
    box_smooth(bhi_raw, g->band_hi_db, T, 4);
    box_smooth(cent_raw, g->cent_hz, T, 3);

    /* Active frames (> max - 45 dB) for p95 macro reference & median centroid */
    double mmax = g->macro_db[0];
    for (int t = 1; t < T; ++t) if (g->macro_db[t] > mmax) mmax = g->macro_db[t];
    double *act_m = (double *)malloc((size_t)T * sizeof(double));
    double *act_b0 = (double *)malloc((size_t)T * sizeof(double));
    double *act_b1 = (double *)malloc((size_t)T * sizeof(double));
    double *act_b2 = (double *)malloc((size_t)T * sizeof(double));
    double *act_c = (double *)malloc((size_t)T * sizeof(double));
    size_t na = 0;
    if (act_m && act_b0 && act_b1 && act_b2 && act_c) {
        for (int t = 0; t < T; ++t) {
            if (g->macro_db[t] > mmax - 45.0) {
                act_m[na] = g->macro_db[t];
                act_b0[na] = g->band_lo_db[t];
                act_b1[na] = g->band_md_db[t];
                act_b2[na] = g->band_hi_db[t];
                act_c[na] = g->cent_hz[t];
                na++;
            }
        }
    }
    if (na > 0) {
        g->macro_peak_db = percentile_copy(act_m, na, 0.95);
        g->band_peak_db[0] = percentile_copy(act_b0, na, 0.95);
        g->band_peak_db[1] = percentile_copy(act_b1, na, 0.95);
        g->band_peak_db[2] = percentile_copy(act_b2, na, 0.95);
        g->med_cent_hz = percentile_copy(act_c, na, 0.50);
    } else {
        g->macro_peak_db = mmax;
        g->band_peak_db[0] = g->band_peak_db[1] = g->band_peak_db[2] = mmax;
        g->med_cent_hz = 1500.0;
    }
    if (g->med_cent_hz < 150.0) g->med_cent_hz = 150.0;

    free(act_m); free(act_b0); free(act_b1); free(act_b2); free(act_c);
    free(rms_db); free(dba_raw); free(blo_raw); free(bmd_raw);
    free(bhi_raw); free(cent_raw); free(hat_lp); free(macro_raw);
    return 1;
}

/* =========================================================================
 * Per-note acoustic measurements & enhancement pipeline
 * ========================================================================= */

struct note_meas {
    double raw_db;       /* mean narrowband pitch power (unweighted dB) */
    double dba;          /* mean A-weighted pitch power (dB) */
    double mix_db;       /* blended fundamental + 2nd/3rd harmonic acoustic level */
    double snr_loc;      /* local prominence vs +/- 4..5 semitones (dBA) */
    double loc_max_gap;  /* loc_max(+/-2) - dba (>= 0; 0 means exact peak) */
    double sustain;      /* amplitude ratio late/early for notes >= 0.16 s (-1 if short) */
    double even_odd;     /* (P_2f + P_4f) / (P_1f + P_3f + P_5f) */
    double bright;       /* (P_2f + P_3f + P_4f) / P_1f */
    double macro_at_on;  /* macro_db at note onset */
    double conf;         /* recovered neural confidence 0..1 */
    int is_peak;         /* 1 if local CQT peak with snr_loc >= 3.0 dB */
    int keep;            /* 1 = survive pruning */
};

static double mean_pitch_db(const float *mat, int f0, int f1, int k) {
    double s = 0.0;
    for (int t = f0; t < f1; ++t) s += (double)mat[(size_t)t * EN_N_PITCH + k];
    return s / (double)(f1 - f0);
}

static int double_to_frame(double v, int lo, int hi) {
    if (!isfinite(v)) return lo;
    double f = floor(v);
    if (f <= (double)lo) return lo;
    if (f >= (double)hi) return hi;
    return (int)f;
}

static void measure_note(const struct acoustic_grid *g, const struct midi_note *nt, struct note_meas *m) {
    memset(m, 0, sizeof(*m));
    m->keep = 1;
    m->sustain = -1.0;
    m->conf = clamp_d(((double)nt->velocity - 20.0) / 107.0, 0.0, 1.0);

    int f0 = double_to_frame(nt->onset / 0.02 + 0.5, 0, g->T - 1);
    int f1 = double_to_frame(nt->offset / 0.02 + 0.5, f0 + 1, g->T);
    if (f1 <= f0) f1 = f0 + 1 <= g->T ? f0 + 1 : g->T;
    m->macro_at_on = g->macro_db[f0];

    int k = nt->pitch - EN_PITCH_LO;
    if (k < 0 || k >= EN_N_PITCH) {
        m->raw_db = m->dba = m->mix_db = -80.0;
        m->snr_loc = -10.0;
        m->loc_max_gap = 20.0;
        return;
    }

    m->raw_db = mean_pitch_db(g->e_raw_db, f0, f1, k);
    m->dba = mean_pitch_db(g->e_dba, f0, f1, k);

    /* Harmonic energy ratios at +12 (2f), +19 (3f), +24 (4f), +28 (5f) */
    double p1 = pow(10.0, m->raw_db / 10.0);
    double p2 = (k + 12 < EN_N_PITCH) ? pow(10.0, mean_pitch_db(g->e_raw_db, f0, f1, k + 12) / 10.0) : 0.0;
    double p3 = (k + 19 < EN_N_PITCH) ? pow(10.0, mean_pitch_db(g->e_raw_db, f0, f1, k + 19) / 10.0) : 0.0;
    double p4 = (k + 24 < EN_N_PITCH) ? pow(10.0, mean_pitch_db(g->e_raw_db, f0, f1, k + 24) / 10.0) : 0.0;
    double p5 = (k + 28 < EN_N_PITCH) ? pow(10.0, mean_pitch_db(g->e_raw_db, f0, f1, k + 28) / 10.0) : 0.0;

    /* Acoustic level blending fundamental + mild 2nd/3rd harmonic + half A-weight so bass stays full */
    double harm_lin = p1 + 0.35 * p2 + 0.15 * p3;
    double harm_raw_db = 10.0 * log10(harm_lin + 1e-12);
    double a_half = 0.5 * (m->dba - m->raw_db);
    m->mix_db = harm_raw_db + a_half;
    m->even_odd = (p2 + p4) / (p1 + p3 + p5 + 1e-12);
    m->bright = (p2 + p3 + p4) / (p1 + 1e-12);

    /* Local SNR vs +/- 4..5 semitones & +/- 2 semitone local peak */
    double nb[4];
    int n_nb = 0;
    static const int offs[4] = { -5, -4, 4, 5 };
    for (int i = 0; i < 4; ++i) {
        int kb = k + offs[i];
        if (kb >= 0 && kb < EN_N_PITCH) nb[n_nb++] = mean_pitch_db(g->e_dba, f0, f1, kb);
    }
    double bg = n_nb ? percentile_copy(nb, (size_t)n_nb, 0.5) : m->dba;
    m->snr_loc = m->dba - bg;

    double loc_max = m->dba;
    for (int d = -2; d <= 2; ++d) {
        int kb = k + d;
        if (kb >= 0 && kb < EN_N_PITCH) {
            double v = mean_pitch_db(g->e_dba, f0, f1, kb);
            if (v > loc_max) loc_max = v;
        }
    }
    m->loc_max_gap = loc_max - m->dba;
    m->is_peak = (m->loc_max_gap <= 1.5 && m->snr_loc >= 3.0) ? 1 : 0;

    /* Sustain ratio on notes >= 160 ms (8 frames): late [60..95%] vs early [0..35%] */
    int span = f1 - f0;
    if (span >= 8) {
        int e_end = f0 + (span * 35) / 100;
        if (e_end <= f0) e_end = f0 + 1;
        int l_beg = f0 + (span * 60) / 100;
        int l_end = f0 + (span * 95) / 100;
        if (l_end <= l_beg) l_end = l_beg + 1;
        if (l_end > f1) l_end = f1;
        double db_early = mean_pitch_db(g->e_raw_db, f0, e_end, k);
        double db_late = mean_pitch_db(g->e_raw_db, l_beg, l_end, k);
        m->sustain = clamp_d(pow(10.0, (db_late - db_early) / 20.0), 0.0, 2.0);
    }
}

static char *dup_str(const char *s) {
    if (!s) s = "";
    size_t len = strlen(s);
    char *p = (char *)malloc(len + 1);
    if (p) memcpy(p, s, len + 1);
    return p;
}

static int is_synth_program(int p) {
    return (p == 38 || p == 39 || p == 50 || p == 51 || p == 62 || p == 63 || (p >= 80 && p <= 103));
}

/* Mild patch-loudness trim (dB) based on empirical TimGM6mb / standard GM loudness profile. */
static double gm_patch_trim_db(int prog, double med_pitch) {
    double trim = 0.0;
    if (prog == 38) trim += 4.0;             /* SynthBass1 tends to sit quiet */
    else if (prog == 39) trim += 2.0;        /* SynthBass2 */
    else if (prog == 50 || prog == 51) trim += 5.0; /* Synth Strings are quiet in SF2 */
    else if (prog == 89 || prog == 90) trim += 2.5; /* Pads */
    else if (prog == 46) trim -= 2.5;        /* Harp attacks cut hot */
    else if (prog == 80) trim -= 2.0;        /* Square lead sits loud */
    if (med_pitch < 46.0) trim += 2.5;       /* Keep bass foundation solid */
    else if (med_pitch >= 66.0) trim -= 2.0; /* Prevent high piercing lines from overpowering bass */
    return trim;
}

/* Emit CC7 (once at t=0), CC11 macro expression curve (every 80 ms near active notes),
 * and optional CC74 brightness curve (every 120 ms near active notes). */
static int build_track_ccs(const struct acoustic_grid *g,
                           const struct midi_note *notes, size_t count,
                           int is_drum, double med_pitch, int cc7_val,
                           int emit_cc11, int emit_cc74,
                           struct midi_cc **ccs_out, size_t *n_ccs_out) {
    *ccs_out = NULL;
    *n_ccs_out = 0;
    if (!count) return 1;

    uint8_t *active = (uint8_t *)calloc((size_t)g->T, 1);
    if (!active) return 0;
    for (size_t i = 0; i < count; ++i) {
        int a = double_to_frame((notes[i].onset - 0.16) / 0.02, 0, g->T - 1);
        int b = double_to_frame(ceil((notes[i].offset + 0.16) / 0.02), 0, g->T - 1);
        for (int t = a; t <= b; ++t) active[t] = 1;
    }

    size_t cap = 64, n = 0;
    struct midi_cc *ccs = (struct midi_cc *)malloc(cap * sizeof(*ccs));
    if (!ccs) { free(active); return 0; }

    #define PUSH_CC(tm, num, val) do { \
        if (n == cap) { \
            cap *= 2; \
            struct midi_cc *_g = (struct midi_cc *)realloc(ccs, cap * sizeof(*ccs)); \
            if (!_g) { free(ccs); free(active); return 0; } \
            ccs = _g; \
        } \
        ccs[n++] = (struct midi_cc){ (tm), (uint8_t)(num), (uint8_t)(val) }; \
    } while (0)

    PUSH_CC(0.0, 7, clamp_i(cc7_val, 1, 127));

    /* Choose register band for subtle 25% band-envelope blending on pitched tracks */
    int band_idx = (med_pitch < 48.0) ? 0 : (med_pitch < 66.0 ? 1 : 2);
    const double *band_arr = (band_idx == 0) ? g->band_lo_db : (band_idx == 1 ? g->band_md_db : g->band_hi_db);
    double band_pk = g->band_peak_db[band_idx];

    if (emit_cc11) {
        int last_cc11 = -1;
        for (int t = 0; t < g->T; t += 4) { /* 80 ms steps */
            if (t > 0 && !active[t]) continue;
            double dm = g->macro_db[t] - g->macro_peak_db;
            double env_rel = dm;
            if (!is_drum) {
                double db = band_arr[t] - band_pk;
                env_rel = 0.75 * dm + 0.25 * db;
            }
            /* Mild 0.84 slope compensates for natural polyphonic track-density growth
             * between sparse intros and dense climaxes so LRA matches source. */
            env_rel = clamp_d(0.84 * env_rel, -32.0, 0.0);
            int val = db_to_cc(env_rel, 127, 16, 127);
            if (last_cc11 < 0 || abs(val - last_cc11) >= 2) {
                PUSH_CC((double)t * 0.02, 11, val);
                last_cc11 = val;
            }
        }
    }

    if (emit_cc74 && !is_drum) {
        int last_cc74 = -1;
        for (int t = 0; t < g->T; t += 6) { /* 120 ms steps */
            if (t > 0 && !active[t]) continue;
            double ratio = g->cent_hz[t] / g->med_cent_hz;
            if (ratio < 0.125) ratio = 0.125;
            if (ratio > 8.0) ratio = 8.0;
            int val = clamp_i((int)floor(64.0 + 28.0 * log2(ratio) + 0.5), 20, 124);
            if (last_cc74 < 0 || abs(val - last_cc74) >= 3) {
                PUSH_CC((double)t * 0.02, 74, val);
                last_cc74 = val;
            }
        }
    }

    #undef PUSH_CC
    free(active);
    *ccs_out = ccs;
    *n_ccs_out = n;
    return 1;
}

int enhance_tracks(const struct midi_track *in_tracks, size_t n_in_tracks,
                   const float *audio_native, size_t n_native, unsigned native_rate,
                   const float *audio_16k, size_t n_16k,
                   const struct enhance_opts *opts_in,
                   struct enhance_track **out_tracks, size_t *n_out_tracks,
                   struct enhance_stats *stats) {
    *out_tracks = NULL;
    *n_out_tracks = 0;
    if (stats) memset(stats, 0, sizeof(*stats));
    if (!in_tracks || n_in_tracks == 0) return 1;

    struct enhance_opts opts;
    if (opts_in) opts = *opts_in;
    else enhance_opts_default(&opts);

    struct acoustic_grid grid;
    if (!build_acoustic_grid(audio_native, n_native, native_rate, audio_16k, n_16k, &grid))
        return 0;

    /* Allocate per-track note measurements */
    struct note_meas **meas = (struct note_meas **)calloc(n_in_tracks, sizeof(*meas));
    int *track_drop = (int *)calloc(n_in_tracks, sizeof(int));
    int *track_prog = (int *)calloc(n_in_tracks, sizeof(int));
    char **track_name = (char **)calloc(n_in_tracks, sizeof(char *));
    double *track_med_pitch = (double *)calloc(n_in_tracks, sizeof(double));
    double *track_prom_db = (double *)calloc(n_in_tracks, sizeof(double));
    int *track_cc7 = (int *)calloc(n_in_tracks, sizeof(int));
    int ok = 0;
    if (!meas || !track_drop || !track_prog || !track_name || !track_med_pitch || !track_prom_db || !track_cc7)
        goto cleanup;

    size_t total_pitched = 0;
    int is_electronic_mix = 0;
    for (size_t ti = 0; ti < n_in_tracks; ++ti) {
        track_prog[ti] = in_tracks[ti].program;
        track_name[ti] = dup_str(in_tracks[ti].name ? in_tracks[ti].name : (in_tracks[ti].is_drum ? "Drums" : "Track"));
        if (!track_name[ti]) goto cleanup;
        if (!in_tracks[ti].is_drum) {
            total_pitched += in_tracks[ti].count;
            if (is_synth_program(in_tracks[ti].program)) is_electronic_mix = 1;
            if (in_tracks[ti].count > 0) {
                meas[ti] = (struct note_meas *)calloc(in_tracks[ti].count, sizeof(struct note_meas));
                if (!meas[ti]) goto cleanup;
                for (size_t i = 0; i < in_tracks[ti].count; ++i)
                    measure_note(&grid, &in_tracks[ti].notes[i], &meas[ti][i]);
            }
        } else {
            if (stats) stats->drums_in += in_tracks[ti].count;
        }
    }
    if (stats) stats->pitched_in = total_pitched;

    /* ---- Stage 1: Cross-track duplicate & low-SNR ghost pruning ---- */
    if (opts.prune_ghosts) {
        /* 1a. Cross-track exact pitch duplicates (keep larger track / higher confidence) */
        for (size_t a = 0; a < n_in_tracks; ++a) {
            if (in_tracks[a].is_drum || !meas[a]) continue;
            for (size_t b = a + 1; b < n_in_tracks; ++b) {
                if (in_tracks[b].is_drum || !meas[b]) continue;
                size_t j_start = 0;
                for (size_t i = 0; i < in_tracks[a].count; ++i) {
                    if (!meas[a][i].keep) continue;
                    const struct midi_note *na = &in_tracks[a].notes[i];
                    while (j_start < in_tracks[b].count && in_tracks[b].notes[j_start].offset < na->onset - 0.05)
                        j_start++;
                    for (size_t j = j_start; j < in_tracks[b].count; ++j) {
                        const struct midi_note *nb = &in_tracks[b].notes[j];
                        if (nb->onset > na->offset + 0.05) break;
                        if (!meas[b][j].keep || nb->pitch != na->pitch) continue;
                        double ov = fmin(na->offset, nb->offset) - fmax(na->onset, nb->onset);
                        double min_d = fmin(na->offset - na->onset, nb->offset - nb->onset);
                        if (fabs(na->onset - nb->onset) <= 0.035 || (min_d > 0.0 && ov > 0.55 * min_d)) {
                            /* Drop the weaker track's duplicate */
                            double sa = (double)in_tracks[a].count * 0.001 + meas[a][i].conf;
                            double sb = (double)in_tracks[b].count * 0.001 + meas[b][j].conf;
                            if (sa >= sb) meas[b][j].keep = 0;
                            else meas[a][i].keep = 0;
                            if (stats) stats->dups_dropped++;
                            if (!meas[a][i].keep) break;
                        }
                    }
                }
            }
        }

        /* 1b. Individual low-SNR ghost pruning & dead sparse-track pruning */
        for (size_t ti = 0; ti < n_in_tracks; ++ti) {
            if (in_tracks[ti].is_drum || !meas[ti] || in_tracks[ti].count == 0) continue;
            size_t cnt = in_tracks[ti].count;
            double *snrs = (double *)malloc(cnt * sizeof(double));
            if (!snrs) goto cleanup;
            size_t n_pk = 0, n_alive = 0;
            for (size_t i = 0; i < cnt; ++i) {
                if (!meas[ti][i].keep) continue;
                snrs[n_alive++] = meas[ti][i].snr_loc;
                if (meas[ti][i].is_peak) n_pk++;
            }
            double med_snr = n_alive ? percentile_copy(snrs, n_alive, 0.5) : -10.0;
            double pk_rate = n_alive ? ((double)n_pk / (double)n_alive) : 0.0;
            free(snrs);

            /* Drop entire sparse track ONLY if overwhelmingly unsupported across whole piece */
            if (total_pitched >= 100 && n_alive <= 80 &&
                (double)n_alive < 0.025 * (double)total_pitched &&
                med_snr < 2.0 && pk_rate < 0.35) {
                track_drop[ti] = 1;
                if (stats) { stats->tracks_dropped++; stats->ghosts_dropped += n_alive; }
                continue;
            }

            /* Individual ghost note pruning (strict so real quiet notes with high SNR stay!) */
            for (size_t i = 0; i < cnt; ++i) {
                if (!meas[ti][i].keep) continue;
                struct note_meas *m = &meas[ti][i];
                int dead_silence = (m->macro_at_on < grid.macro_peak_db - 52.0);
                int bad_ghost = (m->snr_loc < 1.0 && m->loc_max_gap > 2.5 && m->conf < 0.55);
                int severe_ghost = (m->snr_loc < -1.5 && m->loc_max_gap > 4.0 && m->conf < 0.72);
                if (dead_silence || bad_ghost || severe_ghost) {
                    m->keep = 0;
                    if (stats) stats->ghosts_dropped++;
                }
            }
        }
    }

    /* ---- Stage 2: Register-, Envelope-, & Harmonicity-Aware GM Program Refinement ---- */
    for (size_t ti = 0; ti < n_in_tracks; ++ti) {
        if (in_tracks[ti].is_drum || track_drop[ti] || !meas[ti]) continue;
        size_t cnt = in_tracks[ti].count;
        double *pitches = (double *)malloc(cnt * sizeof(double));
        double *durs = (double *)malloc(cnt * sizeof(double));
        double *susts = (double *)malloc(cnt * sizeof(double));
        double *eors = (double *)malloc(cnt * sizeof(double));
        double *brts = (double *)malloc(cnt * sizeof(double));
        size_t n_k = 0, n_sus = 0, n_long = 0;
        if (!pitches || !durs || !susts || !eors || !brts) {
            free(pitches); free(durs); free(susts); free(eors); free(brts);
            goto cleanup;
        }
        for (size_t i = 0; i < cnt; ++i) {
            if (!meas[ti][i].keep) continue;
            const struct midi_note *nt = &in_tracks[ti].notes[i];
            double dur = nt->offset - nt->onset;
            pitches[n_k] = (double)nt->pitch;
            durs[n_k] = dur;
            eors[n_k] = meas[ti][i].even_odd;
            brts[n_k] = meas[ti][i].bright;
            if (dur >= 0.75) n_long++;
            if (meas[ti][i].sustain >= 0.0) susts[n_sus++] = meas[ti][i].sustain;
            n_k++;
        }
        if (n_k == 0) {
            track_drop[ti] = 1;
            free(pitches); free(durs); free(susts); free(eors); free(brts);
            continue;
        }
        double med_p = percentile_copy(pitches, n_k, 0.50);
        double p90_p = percentile_copy(pitches, n_k, 0.90);
        double med_d = percentile_copy(durs, n_k, 0.50);
        double med_sus = n_sus >= 3 ? percentile_copy(susts, n_sus, 0.50) : 0.40;
        double med_eo = percentile_copy(eors, n_k, 0.50);
        double med_br = percentile_copy(brts, n_k, 0.50);
        track_med_pitch[ti] = med_p;

        if (opts.refine_gm) {
            int orig_p = track_prog[ti];
            int new_p = orig_p;
            const char *new_nm = NULL;

            /* Rule 1: Bass-register Synth Lead -> Synth Bass 1/2 */
            if (orig_p >= 80 && orig_p <= 87 && med_p <= 45.0 && p90_p <= 54.0) {
                new_p = (med_br >= 0.45) ? 39 : 38;
                new_nm = (new_p == 39) ? "synth bass pulse" : "synth bass low";
            }
            /* Rule 2: Square Lead (80) with strong even harmonics -> Sawtooth Lead (81) */
            else if (orig_p == 80 && med_eo >= 0.30) {
                new_p = 81;
                new_nm = "synth saw lead";
            }
            /* Rule 3: Sustained electronic chords misclassified as plucked guitar (24..28) */
            else if (orig_p >= 24 && orig_p <= 28 && is_electronic_mix &&
                     ((med_sus >= 0.48 && n_sus >= 5) || (med_d >= 0.55) || ((double)n_long >= 0.25 * (double)n_k))) {
                new_p = (med_br >= 0.65) ? 81 : 90; /* Saw Lead or Pad 3 Polysynth */
                new_nm = (new_p == 81) ? "synth saw" : "polysynth pad";
            }
            /* Rule 4: Non-plucked electronic high sequence misclassified as Orchestral Harp (46) */
            else if (orig_p == 46 && is_electronic_mix && med_sus >= 0.44) {
                new_p = (med_br >= 0.35) ? 81 : 98; /* Lead 2 Sawtooth or FX 3 Crystal */
                new_nm = (new_p == 81) ? "synth arp lead" : "synth crystal";
            }
            /* Rule 5: Bright Synth Bass 1 (38) -> Synth Bass 2 (39) for fuller harmonic presence */
            else if (orig_p == 38 && med_br >= 0.35) {
                new_p = 39;
                new_nm = "synth bass 2";
            }

            if (new_p != orig_p) {
                track_prog[ti] = new_p;
                if (new_nm) {
                    char *nm = dup_str(new_nm);
                    if (!nm) {
                        free(pitches); free(durs); free(susts); free(eors); free(brts);
                        goto cleanup;
                    }
                    free(track_name[ti]);
                    track_name[ti] = nm;
                }
                if (stats) stats->programs_refined++;
            }
        }
        free(pitches); free(durs); free(susts); free(eors); free(brts);
    }

    /* Ensure unique track names across surviving tracks */
    for (size_t ti = 0; ti < n_in_tracks; ++ti) {
        if (track_drop[ti] || !track_name[ti]) continue;
        int dup_cnt = 0;
        for (size_t prev = 0; prev < ti; ++prev) {
            if (!track_drop[prev] && track_name[prev] && strcmp(track_name[prev], track_name[ti]) == 0)
                dup_cnt++;
        }
        if (dup_cnt > 0) {
            size_t nlen = strlen(track_name[ti]) + 16;
            char *renamed = (char *)malloc(nlen);
            if (renamed) {
                snprintf(renamed, nlen, "%s %d", track_name[ti], dup_cnt + 1);
                free(track_name[ti]);
                track_name[ti] = renamed;
            }
        }
    }

    /* ---- Stage 3: Per-Track Acoustic Prominence -> CC7 Balance ---- */
    double max_prom = -1e9;
    for (size_t ti = 0; ti < n_in_tracks; ++ti) {
        if (in_tracks[ti].is_drum || track_drop[ti] || !meas[ti]) continue;
        size_t cnt = in_tracks[ti].count;
        double *rels = (double *)malloc(cnt * sizeof(double));
        size_t nk = 0;
        if (!rels) goto cleanup;
        for (size_t i = 0; i < cnt; ++i) {
            if (!meas[ti][i].keep) continue;
            rels[nk++] = meas[ti][i].mix_db - meas[ti][i].macro_at_on;
        }
        track_prom_db[ti] = nk ? percentile_copy(rels, nk, 0.50) : -20.0;
        free(rels);
        if (track_prom_db[ti] > max_prom) max_prom = track_prom_db[ti];
    }
    for (size_t ti = 0; ti < n_in_tracks; ++ti) {
        if (track_drop[ti]) continue;
        if (in_tracks[ti].is_drum) {
            track_cc7[ti] = 122;
        } else {
            double trim = gm_patch_trim_db(track_prog[ti], track_med_pitch[ti]);
            double rel = clamp_d((track_prom_db[ti] - max_prom) + trim, -18.0, 4.0);
            track_cc7[ti] = db_to_cc(rel, 114, 54, 127);
        }
    }

    /* Compute adaptive high-band flux stats for peripheral drum bleed pruning */
    double hat_flux_thr = 0.0;
    {
        double *nz = (double *)malloc((size_t)grid.T * sizeof(double));
        size_t nnz = 0;
        if (nz) {
            for (int t = 0; t < grid.T; ++t)
                if (grid.hat_flux[t] > 1e-4 && grid.macro_db[t] > grid.macro_peak_db - 45.0)
                    nz[nnz++] = grid.hat_flux[t];
            hat_flux_thr = nnz ? percentile_copy(nz, nnz, 0.50) * 0.85 : 0.0;
            free(nz);
        }
    }

    /* ---- Stage 4: Build Final Enhanced Tracks (Audio Velocities + CC7/CC11/CC74) ---- */
    struct enhance_track *out = (struct enhance_track *)calloc(n_in_tracks, sizeof(*out));
    if (!out) goto cleanup;
    size_t n_out = 0;

    for (size_t ti = 0; ti < n_in_tracks; ++ti) {
        if (track_drop[ti]) continue;
        const struct midi_track *in_t = &in_tracks[ti];

        if (!in_t->is_drum) {
            size_t nk = 0;
            for (size_t i = 0; i < in_t->count; ++i) if (meas[ti][i].keep) nk++;
            if (nk == 0) continue;

            struct midi_note *notes = (struct midi_note *)malloc(nk * sizeof(*notes));
            if (!notes) { enhance_tracks_free(out, n_out); goto cleanup; }
            size_t w = 0;
            for (size_t i = 0; i < in_t->count; ++i) {
                if (!meas[ti][i].keep) continue;
                struct midi_note nt = in_t->notes[i];
                if (opts.audio_dynamics) {
                    /* Local relative accent above/below track's typical prominence (zero double-counting with CC11!) */
                    double local_prom = meas[ti][i].mix_db - meas[ti][i].macro_at_on;
                    double accent_db = clamp_d(local_prom - track_prom_db[ti], -16.0, 8.0);
                    int v_audio = db_to_cc(accent_db, 94, 26, 127);
                    int v_conf = clamp_i((int)floor(40.0 + 80.0 * meas[ti][i].conf + 0.5), 26, 127);
                    nt.velocity = clamp_i((int)floor(0.85 * (double)v_audio + 0.15 * (double)v_conf + 0.5), 24, 127);
                }
                notes[w++] = nt;
            }
            struct midi_cc *ccs = NULL;
            size_t n_ccs = 0;
            if (opts.audio_dynamics) {
                if (!build_track_ccs(&grid, notes, w, 0, track_med_pitch[ti], track_cc7[ti],
                                     1, opts.emit_cc74, &ccs, &n_ccs)) {
                    free(notes); enhance_tracks_free(out, n_out); goto cleanup;
                }
            }
            char *nm = dup_str(track_name[ti]);
            if (!nm) { free(notes); free(ccs); enhance_tracks_free(out, n_out); goto cleanup; }
            out[n_out++] = (struct enhance_track){
                nm, track_prog[ti], 0, notes, w, ccs, n_ccs
            };
            if (stats) { stats->pitched_out += w; stats->cc_events_total += n_ccs; }
        } else {
            /* Drum track: prune peripheral filter-sweep bleed + audio-calibrate velocities + CC11 */
            if (in_t->count == 0) continue;
            struct midi_note *notes = (struct midi_note *)malloc(in_t->count * sizeof(*notes));
            double *hit_rel = (double *)malloc(in_t->count * sizeof(double));
            if (!notes || !hit_rel) { free(notes); free(hit_rel); enhance_tracks_free(out, n_out); goto cleanup; }

            /* Compute per-band median prominence for drum hit relative accents */
            double kick_med = 0.0, snare_med = 0.0, hat_med = 0.0;
            {
                double *karr = (double *)malloc(in_t->count * sizeof(double));
                double *sarr = (double *)malloc(in_t->count * sizeof(double));
                double *harr = (double *)malloc(in_t->count * sizeof(double));
                size_t nk = 0, ns = 0, nh = 0;
                if (karr && sarr && harr) {
                    for (size_t i = 0; i < in_t->count; ++i) {
                        int tf = double_to_frame(in_t->notes[i].onset / 0.02 + 0.5, 0, grid.T - 1);
                        int p = in_t->notes[i].pitch;
                        if (p == 35 || p == 36) karr[nk++] = grid.kick_db[tf] - grid.macro_db[tf];
                        else if (p >= 37 && p <= 40) sarr[ns++] = grid.snare_db[tf] - grid.macro_db[tf];
                        else harr[nh++] = grid.hat_db[tf] - grid.macro_db[tf];
                    }
                    if (nk) kick_med = percentile_copy(karr, nk, 0.50);
                    if (ns) snare_med = percentile_copy(sarr, ns, 0.50);
                    if (nh) hat_med = percentile_copy(harr, nh, 0.50);
                }
                free(karr); free(sarr); free(harr);
            }

            size_t w = 0;
            for (size_t i = 0; i < in_t->count; ++i) {
                struct midi_note nt = in_t->notes[i];
                int tf = double_to_frame(nt.onset / 0.02 + 0.5, 0, grid.T - 1);
                int p = nt.pitch;

                if (opts.prune_ghosts) {
                    /* Drop hits in true audio silence */
                    if (grid.macro_db[tf] < grid.macro_peak_db - 55.0) {
                        if (stats) stats->drum_bleed_dropped++;
                        continue;
                    }
                    /* Peripheral shaker/cabasa/tambourine gate against high-band percussive transient */
                    if (p == 69 || p == 70 || p == 82 || p == 54) {
                        double pk_flux = 0.0;
                        for (int d = -1; d <= 1; ++d) {
                            int idx = clamp_i(tf + d, 0, grid.T - 1);
                            if (grid.hat_flux[idx] > pk_flux) pk_flux = grid.hat_flux[idx];
                        }
                        double loc_bg[11];
                        int nbg = 0;
                        for (int d = -5; d <= 5; ++d) {
                            int idx = tf + d;
                            if (idx >= 0 && idx < grid.T) loc_bg[nbg++] = grid.hat_flux[idx];
                        }
                        double bg_med = nbg ? percentile_copy(loc_bg, (size_t)nbg, 0.50) : 0.0;
                        int is_transient = (pk_flux >= hat_flux_thr && pk_flux >= bg_med * 1.35 + 1e-4);
                        if (!is_transient && nt.velocity < 92) {
                            if (stats) stats->drum_bleed_dropped++;
                            continue;
                        }
                    }
                }

                if (opts.audio_dynamics) {
                    double band_rel;
                    if (p == 35 || p == 36) band_rel = (grid.kick_db[tf] - grid.macro_db[tf]) - kick_med;
                    else if (p >= 37 && p <= 40) band_rel = (grid.snare_db[tf] - grid.macro_db[tf]) - snare_med;
                    else band_rel = (grid.hat_db[tf] - grid.macro_db[tf]) - hat_med;
                    band_rel = clamp_d(band_rel, -14.0, 6.0);
                    int v_aud = db_to_cc(band_rel, 98, 28, 127);
                    nt.velocity = clamp_i((int)floor(0.50 * (double)nt.velocity + 0.50 * (double)v_aud + 0.5), 22, 127);
                }
                notes[w++] = nt;
            }
            free(hit_rel);
            if (w == 0) { free(notes); continue; }

            struct midi_cc *ccs = NULL;
            size_t n_ccs = 0;
            if (opts.audio_dynamics) {
                if (!build_track_ccs(&grid, notes, w, 1, 60.0, track_cc7[ti], 1, 0, &ccs, &n_ccs)) {
                    free(notes); enhance_tracks_free(out, n_out); goto cleanup;
                }
            }
            char *nm = dup_str(track_name[ti]);
            if (!nm) { free(notes); free(ccs); enhance_tracks_free(out, n_out); goto cleanup; }
            out[n_out++] = (struct enhance_track){
                nm, 0, 1, notes, w, ccs, n_ccs
            };
            if (stats) { stats->drums_out += w; stats->cc_events_total += n_ccs; }
        }
    }

    *out_tracks = out;
    *n_out_tracks = n_out;
    ok = 1;

cleanup:
    if (meas) {
        for (size_t ti = 0; ti < n_in_tracks; ++ti) free(meas[ti]);
        free(meas);
    }
    if (track_name) {
        for (size_t ti = 0; ti < n_in_tracks; ++ti) free(track_name[ti]);
        free(track_name);
    }
    free(track_drop); free(track_prog); free(track_med_pitch); free(track_prom_db); free(track_cc7);
    acoustic_grid_free(&grid);
    return ok;
}
