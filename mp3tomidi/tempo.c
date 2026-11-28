/* Native tempo & 16th-note grid estimator:
 * 1. 4-band log-flux onset strength at 100 Hz (512-pt FFT, 160-sample hop on 16 kHz audio)
 *    optionally reinforced by transcribed kick/snare/hat onsets.
 * 2. Comb-weighted FFT autocorrelation tempogram (60..200 BPM) with musical octave prior.
 * 3. 4-round 16th-note phase-fold stretch cross-correlation refinement (inspired by tools/tempo_check.py). */
#include "tempo.h"
#include "features.h"
#include <math.h>
#include <stdlib.h>
#include <string.h>

enum {
    TP_NFFT = 512,
    TP_HOP = 160,    /* 10 ms at 16 kHz -> 100 Hz onset rate */
    TP_FPS = 100,
    TP_BINS = 64     /* circular phase bins per 16th-note period */
};

static const double TP_TAU = 6.2831853071795864769;

static void tp_fft(double *re, double *im, int n, int inverse) {
    for (int i = 1, j = 0; i < n; ++i) {
        int bit = n >> 1;
        while (j & bit) { j ^= bit; bit >>= 1; }
        j ^= bit;
        if (i < j) {
            double tr = re[i]; re[i] = re[j]; re[j] = tr;
            double ti = im[i]; im[i] = im[j]; im[j] = ti;
        }
    }
    double sign = inverse ? 1.0 : -1.0;
    for (int span = 2; span <= n; span <<= 1) {
        double ang = sign * TP_TAU / (double)span;
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
    if (inverse) {
        double inv = 1.0 / (double)n;
        for (int i = 0; i < n; ++i) { re[i] *= inv; im[i] *= inv; }
    }
}

static void fold_range(const double *env, int i0, int i1, double p_frames, double out[TP_BINS]) {
    memset(out, 0, TP_BINS * sizeof(double));
    if (p_frames <= 1e-6 || i1 <= i0) return;
    for (int i = i0; i < i1; ++i) {
        double v = env[i];
        if (!isfinite(v) || v <= 0.0) continue;
        double ph = fmod((double)i, p_frames) / p_frames;
        if (ph < 0.0) ph += 1.0;
        double pos = ph * (double)TP_BINS;
        int b0 = (int)floor(pos) % TP_BINS;
        if (b0 < 0 || b0 >= TP_BINS) continue;
        int b1 = (b0 + 1) % TP_BINS;
        double f = pos - floor(pos);
        out[b0] += v * (1.0 - f);
        out[b1] += v * f;
    }
}

/* Circular cross-correlation peak shift (in seconds) of `a` relative to `ref`. */
static double circ_shift_s(const double a[TP_BINS], const double ref[TP_BINS], double p_sec) {
    double c[TP_BINS];
    int best = 0;
    double best_v = -1e30;
    for (int lag = 0; lag < TP_BINS; ++lag) {
        double s = 0.0;
        for (int j = 0; j < TP_BINS; ++j)
            s += a[(j + lag) % TP_BINS] * ref[j];
        c[lag] = s;
        if (s > best_v) { best_v = s; best = lag; }
    }
    double cm = c[(best + TP_BINS - 1) % TP_BINS];
    double c0 = c[best];
    double cp = c[(best + 1) % TP_BINS];
    double den = cm - 2.0 * c0 + cp;
    double frac = (den < -1e-12) ? (0.5 * (cm - cp) / den) : 0.0;
    if (frac < -0.5) frac = -0.5;
    if (frac > 0.5) frac = 0.5;
    double sh = ((double)best + frac) / (double)TP_BINS * p_sec;
    /* Wrap to [-p_sec/2, +p_sec/2) */
    sh = fmod(sh + 0.5 * p_sec, p_sec);
    if (sh < 0.0) sh += p_sec;
    return sh - 0.5 * p_sec;
}

int tempo_estimate(const float *audio_16k, size_t n_16k,
                   const struct midi_note *drums, size_t n_drums,
                   struct tempo_info *out) {
    memset(out, 0, sizeof(*out));
    out->bpm = 120.0;
    out->initial_bpm = 120.0;
    if (!audio_16k || n_16k < (size_t)(4 * MODEL_RATE)) return 1;

    int nfr = (int)(n_16k / TP_HOP);
    if (nfr < 400) return 1;

    double *oenv = (double *)calloc((size_t)nfr, sizeof(double));
    double *frm_e = (double *)calloc((size_t)nfr, sizeof(double));
    if (!oenv || !frm_e) { free(oenv); free(frm_e); return 0; }

    /* 1. Multi-band log-flux onset strength at 100 Hz */
    double win[TP_NFFT];
    for (int i = 0; i < TP_NFFT; ++i)
        win[i] = 0.5 - 0.5 * cos(TP_TAU * (double)i / (double)(TP_NFFT - 1));

    /* 4 bands: 31-188 Hz, 188-1000 Hz, 1000-3500 Hz, 3500-8000 Hz */
    static const int b_lo[4] = { 1, 6, 32, 112 };
    static const int b_hi[4] = { 6, 32, 112, 256 };
    static const double b_wt[4] = { 1.4, 1.1, 0.9, 1.0 };

    double *bflux[4];
    for (int b = 0; b < 4; ++b) {
        bflux[b] = (double *)calloc((size_t)nfr, sizeof(double));
        if (!bflux[b]) {
            for (int j = 0; j < b; ++j) free(bflux[j]);
            free(oenv); free(frm_e);
            return 0;
        }
    }

    double prev_lp[4] = { 0.0, 0.0, 0.0, 0.0 };
    double re[TP_NFFT], im[TP_NFFT];
    for (int f = 0; f < nfr; ++f) {
        int center = f * TP_HOP;
        double e_sum = 0.0;
        for (int i = 0; i < TP_NFFT; ++i) {
            int idx = center + i - TP_NFFT / 2;
            double s = (idx >= 0 && (size_t)idx < n_16k) ? (double)audio_16k[idx] : 0.0;
            re[i] = s * win[i];
            im[i] = 0.0;
            e_sum += s * s;
        }
        frm_e[f] = e_sum / (double)TP_NFFT;
        tp_fft(re, im, TP_NFFT, 0);
        for (int b = 0; b < 4; ++b) {
            double bp = 0.0;
            for (int k = b_lo[b]; k <= b_hi[b]; ++k)
                bp += re[k] * re[k] + im[k] * im[k];
            double lp = log1p(25.0 * bp);
            if (f > 0) {
                double df = lp - prev_lp[b];
                if (df > 0.0) bflux[b][f] = df;
            }
            prev_lp[b] = lp;
        }
    }

    for (int b = 0; b < 4; ++b) {
        double s2 = 0.0;
        for (int f = 0; f < nfr; ++f) s2 += bflux[b][f] * bflux[b][f];
        double rms = sqrt(s2 / (double)nfr) + 1e-12;
        for (int f = 0; f < nfr; ++f) oenv[f] += b_wt[b] * (bflux[b][f] / rms);
        free(bflux[b]);
    }

    /* Optional reinforcement from transcribed drum hits */
    if (drums && n_drums >= 8) {
        double *denv = (double *)calloc((size_t)nfr, sizeof(double));
        if (denv) {
            for (size_t i = 0; i < n_drums; ++i) {
                double w = 0.4;
                int p = drums[i].pitch;
                if (p == 35 || p == 36) w = 1.6;
                else if (p >= 37 && p <= 40) w = 1.3;
                else if (p == 42 || p == 44 || p == 46) w = 0.6;
                w *= (0.4 + 0.6 * (double)drums[i].velocity / 127.0);
                double fc = drums[i].onset * (double)TP_FPS;
                if (!isfinite(fc) || fc < -4.0 || fc > (double)nfr + 4.0) continue;
                int c0 = (int)floor(fc + 0.5);
                for (int d = -3; d <= 3; ++d) {
                    int idx = c0 + d;
                    if (idx >= 0 && idx < nfr) {
                        double dist = (double)idx - fc;
                        denv[idx] += w * exp(-0.5 * (dist * dist) / (1.2 * 1.2));
                    }
                }
            }
            double s_o = 0.0, s_d = 0.0;
            for (int f = 0; f < nfr; ++f) { s_o += oenv[f] * oenv[f]; s_d += denv[f] * denv[f]; }
            double scale = (s_d > 1e-12) ? (0.75 * sqrt(s_o / s_d)) : 0.0;
            for (int f = 0; f < nfr; ++f) oenv[f] += scale * denv[f];
            free(denv);
        }
    }

    /* Local adaptive mean subtraction (window +/- 40 frames = 0.8 s) */
    double *clean = (double *)calloc((size_t)nfr, sizeof(double));
    double *csum = (double *)calloc((size_t)(nfr + 1), sizeof(double));
    if (!clean || !csum) { free(clean); free(csum); free(oenv); free(frm_e); return 0; }
    for (int f = 0; f < nfr; ++f) csum[f + 1] = csum[f] + oenv[f];
    const int hw = 40;
    for (int f = 0; f < nfr; ++f) {
        int a = f - hw > 0 ? f - hw : 0;
        int b = f + hw + 1 < nfr ? f + hw + 1 : nfr;
        double mu = (csum[b] - csum[a]) / (double)(b - a);
        double v = oenv[f] - mu;
        clean[f] = v > 0.0 ? v : 0.0;
    }
    free(csum);

    /* 2. FFT autocorrelation tempogram over 60..200 BPM (lags 30..100 at 100 Hz) */
    int nfft = 1;
    while (nfft < 2 * nfr) nfft <<= 1;
    double *are = (double *)calloc((size_t)nfft, sizeof(double));
    double *aim = (double *)calloc((size_t)nfft, sizeof(double));
    if (!are || !aim) { free(are); free(aim); free(clean); free(oenv); free(frm_e); return 0; }
    for (int f = 0; f < nfr; ++f) are[f] = clean[f];
    tp_fft(are, aim, nfft, 0);
    for (int k = 0; k < nfft; ++k) {
        are[k] = are[k] * are[k] + aim[k] * aim[k];
        aim[k] = 0.0;
    }
    tp_fft(are, aim, nfft, 1);
    double r0 = are[0] > 1e-12 ? are[0] : 1.0;

    /* Score lags 30..100 (200..60 BPM) with harmonic comb + gentle 120 BPM octave prior */
    double score[105];
    memset(score, 0, sizeof(score));
    int best_lag = 50;
    double best_sc = -1e30;
    for (int lag = 30; lag <= 100; ++lag) {
        if (lag >= nfr) break;
        double r1 = are[lag] / r0;
        double r2 = (2 * lag < nfr) ? (are[2 * lag] / r0) : 0.0;
        double r3 = (3 * lag < nfr) ? (are[3 * lag] / r0) : 0.0;
        double r4 = (4 * lag < nfr) ? (are[4 * lag] / r0) : 0.0;
        double rh = (lag / 2 >= 12) ? (are[lag / 2] / r0) : 0.0;
        double bpm_c = 6000.0 / (double)lag;
        double oct = log2(bpm_c / 120.0);
        double prior = exp(-0.5 * (oct * oct) / (0.80 * 0.80));
        double comb = r1 + 0.60 * r2 + 0.30 * r3 + 0.25 * r4 + 0.35 * rh;
        double sc = comb * prior;
        score[lag] = sc;
        if (sc > best_sc) { best_sc = sc; best_lag = lag; }
    }
    free(are);
    free(aim);

    double ref_lag = (double)best_lag;
    if (best_lag > 30 && best_lag < 100) {
        double sm = score[best_lag - 1], s0 = score[best_lag], sp = score[best_lag + 1];
        double den = sm - 2.0 * s0 + sp;
        if (den < -1e-12) {
            double df = 0.5 * (sm - sp) / den;
            if (df > -0.5 && df < 0.5) ref_lag += df;
        }
    }
    double bpm = 6000.0 / ref_lag;
    out->initial_bpm = bpm;

    /* 3. 4-round 16th-note phase-fold stretch refinement (matches tools/tempo_check.py) */
    double dur_s = (double)nfr / (double)TP_FPS;
    int n_win = (int)(dur_s / 12.0);
    if (n_win < 2) n_win = 2;
    if (n_win > 8) n_win = 8;
    int wlen = nfr / n_win;

    double w_rms[8];
    double max_rms = 0.0;
    for (int w = 0; w < n_win; ++w) {
        double s = 0.0;
        for (int f = w * wlen; f < (w + 1) * wlen; ++f) s += frm_e[f];
        w_rms[w] = sqrt(s / (double)wlen);
        if (w_rms[w] > max_rms) max_rms = w_rms[w];
    }
    int use_idx[8], n_use = 0;
    for (int w = 0; w < n_win; ++w) {
        if (w_rms[w] > max_rms * 0.0316228) use_idx[n_use++] = w; /* > -30 dB */
    }

    double whole[TP_BINS], part[TP_BINS];
    double centers[8], shifts[8];
    double worst_ms = 0.0;

    if (n_use >= 2 && wlen >= 200) {
        for (int round = 0; round < 4; ++round) {
            double p_sec = 15.0 / bpm;
            double p_fr = p_sec * (double)TP_FPS;
            fold_range(clean, 0, nfr, p_fr, whole);
            for (int k = 0; k < n_use; ++k) {
                int w = use_idx[k];
                centers[k] = ((double)w + 0.5) * (double)wlen / (double)TP_FPS;
                fold_range(clean, w * wlen, (w + 1) * wlen, p_fr, part);
                shifts[k] = circ_shift_s(part, whole, p_sec);
            }
            /* Unwrap shifts modulo p_sec */
            for (int k = 1; k < n_use; ++k) {
                double diff = shifts[k] - shifts[k - 1];
                while (diff > 0.5 * p_sec) { shifts[k] -= p_sec; diff -= p_sec; }
                while (diff < -0.5 * p_sec) { shifts[k] += p_sec; diff += p_sec; }
            }
            /* Linear regression shifts = b0 + slope * centers */
            double mx = 0.0, my = 0.0;
            for (int k = 0; k < n_use; ++k) { mx += centers[k]; my += shifts[k]; }
            mx /= (double)n_use; my /= (double)n_use;
            double sxx = 0.0, sxy = 0.0;
            for (int k = 0; k < n_use; ++k) {
                double dx = centers[k] - mx;
                sxx += dx * dx;
                sxy += dx * (shifts[k] - my);
            }
            double slope = (sxx > 1e-9) ? (sxy / sxx) : 0.0;
            double b0 = my - slope * mx;
            worst_ms = 0.0;
            for (int k = 0; k < n_use; ++k) {
                double res = fabs(shifts[k] - (b0 + slope * centers[k])) * 1000.0;
                if (res > worst_ms) worst_ms = res;
            }
            if (fabs(slope) < 0.04) {
                double next_bpm = 15.0 / (p_sec * (1.0 + slope));
                if (next_bpm >= 50.0 && next_bpm <= 220.0) bpm = next_bpm;
            }
        }
    }

    /* Final fold clarity & row-0 phase */
    double p_sec = 15.0 / bpm;
    fold_range(clean, 0, nfr, p_sec * (double)TP_FPS, whole);
    double wsum = 0.0, wmax = 0.0;
    int best_b = 0;
    for (int b = 0; b < TP_BINS; ++b) {
        wsum += whole[b];
        if (whole[b] > wmax) { wmax = whole[b]; best_b = b; }
    }
    double clarity = (wsum > 1e-12) ? (wmax / (wsum / (double)TP_BINS)) : 0.0;
    out->clarity = clarity;
    out->worst_drift_ms = worst_ms;
    out->row0_s = ((double)best_b / (double)TP_BINS) * p_sec;
    out->is_steady = (clarity >= 1.18 && worst_ms <= 10.0) ? 1 : 0;

    if (clarity >= 1.12 && bpm >= 50.0 && bpm <= 220.0) {
        out->bpm = bpm;
    } else {
        out->bpm = 120.0;
    }

    free(clean);
    free(oenv);
    free(frm_e);
    return 1;
}
