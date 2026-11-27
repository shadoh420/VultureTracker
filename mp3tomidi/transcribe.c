/* Native port of Dettato's transcriber/core.py and transcriber/decode.py,
 * revision 51ade0f09f2272f4674166026582185d26baaeaf. See vendor/dettato/. */
#include "transcribe.h"
#include "features.h"
#include <math.h>
#include <stdlib.h>
#include <string.h>

static const double HOP_S = 0.02;
static const double TR_TAU = 6.2831853071795864769;

uint16_t vt_f32_to_f16(float x) {
    uint32_t u;
    memcpy(&u, &x, sizeof(u));
    uint32_t sign = (u >> 16) & 0x8000u;
    int exp = (int)((u >> 23) & 0xFFu) - 127 + 15;
    uint32_t mant = u & 0x7FFFFFu;
    if (exp <= 0) {
        if (exp < -10) return (uint16_t)sign;
        mant = (mant | 0x800000u) >> (1 - exp);
        return (uint16_t)(sign | ((mant + 0x1000u) >> 13));
    }
    if (exp >= 31) {
        if (exp == 128 + 15 && mant != 0) return (uint16_t)(sign | 0x7E00u);
        return (uint16_t)(sign | 0x7C00u);
    }
    uint32_t rounded = mant + 0x1000u;
    if (rounded & 0x800000u) {
        rounded = 0;
        exp++;
        if (exp >= 31) return (uint16_t)(sign | 0x7C00u);
    }
    return (uint16_t)(sign | ((uint32_t)exp << 10) | (rounded >> 13));
}

float vt_f16_to_f32(uint16_t h) {
    uint32_t sign = ((uint32_t)h & 0x8000u) << 16;
    uint32_t exp = (h >> 10) & 0x1Fu;
    uint32_t mant = h & 0x3FFu;
    uint32_t bits;
    if (exp == 0) {
        if (mant == 0) bits = sign;
        else {
            exp = 1;
            while ((mant & 0x400u) == 0) { mant <<= 1; exp--; }
            mant &= 0x3FFu;
            bits = sign | ((exp + 127 - 15) << 23) | (mant << 13);
        }
    } else if (exp == 31) {
        bits = sign | 0x7F800000u | (mant << 13);
    } else {
        bits = sign | ((exp + 127 - 15) << 23) | (mant << 13);
    }
    float out;
    memcpy(&out, &bits, sizeof(out));
    return out;
}

static inline float sigmoidf(float x) {
    return 1.0f / (1.0f + expf(-x));
}

static void add_tap_f16(uint16_t *dst_f16, const float *src_f32, int a, int b, int g0, const float *hann) {
    size_t row = (size_t)LANE_KEYS * LANE_C;
    for (int t = a; t < b; ++t) {
        float wt = hann[t - g0];
        uint16_t *dp = dst_f16 + (size_t)t * row;
        const float *sp = src_f32 + (size_t)(t - g0) * row;
        for (size_t i = 0; i < row; ++i) {
            float val = vt_f16_to_f32(dp[i]) + sp[i] * wt;
            dp[i] = vt_f32_to_f16(val);
        }
    }
}

static void finish_tap_f16(uint16_t *dst_f16, const float *wsum, int T) {
    size_t row = (size_t)LANE_KEYS * LANE_C;
    for (int t = 0; t < T; ++t) {
        float ws = wsum[t] < 1e-6f ? 1e-6f : wsum[t];
        float inv_ws = 1.0f / ws;
        uint16_t *dp = dst_f16 + (size_t)t * row;
        for (size_t i = 0; i < row; ++i)
            dp[i] = vt_f32_to_f16(vt_f16_to_f32(dp[i]) * inv_ws);
    }
}

int transcribe_windows(const struct lanenet *net, const float *audio_16k, size_t n_samples,
                       int want_hidden, int want_sub, struct transcribe_run *out) {
    memset(out, 0, sizeof(*out));
    if (!net || !audio_16k || n_samples == 0) return 0;

    const int W = WINDOW_SAMPLES;          /* 128000 (8 s) */
    const int Fw = 400;                    /* 8.0 / 0.02 */
    const int step = W / 4;                /* 32000 (2 s, hop_frac=0.25) */
    const int sub_step = W / 2;            /* 64000 (4 s, sub_hop_frac=0.5) */
    const int pad = W / 2;                 /* 64000 (4 s) */
    const int g_pad = 200;                 /* 4.0 / 0.02 */
    int T = (int)ceil((double)n_samples / (double)MODEL_RATE / HOP_S);
    if (T < 1) T = 1;

    float hann[400];
    /* np.hanning(Fw + 2)[1:-1] */
    for (int i = 0; i < Fw; ++i)
        hann[i] = (float)(0.5 - 0.5 * cos(TR_TAU * (double)(i + 1) / (double)(Fw + 1)));

    size_t map_elems = (size_t)LANE_HEADS * (size_t)T * LANE_KEYS;
    size_t tap_elems = (size_t)T * LANE_KEYS * LANE_C;

    out->T = T;
    out->maps = (float *)calloc(map_elems, sizeof(float));
    float *wsum = (float *)calloc((size_t)T, sizeof(float));
    float *sub_wsum = want_sub ? (float *)calloc((size_t)T, sizeof(float)) : NULL;
    if (want_hidden) out->hidden_f16 = (uint16_t *)calloc(tap_elems, sizeof(uint16_t));
    if (want_sub) {
        out->sub_maps = (float *)calloc(map_elems, sizeof(float));
        out->sub_hidden_f16 = (uint16_t *)calloc(tap_elems, sizeof(uint16_t));
        out->sub_stem_f16 = (uint16_t *)calloc(tap_elems, sizeof(uint16_t));
    }

    float *win_audio = (float *)malloc((size_t)W * sizeof(float));
    float *win_logits = (float *)malloc((size_t)Fw * LANE_KEYS * LANE_HEADS * sizeof(float));
    float *win_hidden = (want_hidden || want_sub) ? (float *)malloc((size_t)Fw * LANE_KEYS * LANE_C * sizeof(float)) : NULL;
    float *win_stem = want_sub ? (float *)malloc((size_t)Fw * LANE_KEYS * LANE_C * sizeof(float)) : NULL;

    if (!out->maps || !wsum || !win_audio || !win_logits ||
        (want_hidden && !out->hidden_f16) ||
        (want_sub && (!sub_wsum || !out->sub_maps || !out->sub_hidden_f16 || !out->sub_stem_f16 || !win_stem)) ||
        ((want_hidden || want_sub) && !win_hidden)) {
        goto fail;
    }

    size_t stop = n_samples + (size_t)pad;
    for (size_t s0 = 0; s0 < stop; s0 += (size_t)step) {
        /* Copy padded window [s0, s0 + W) where original audio sits at [pad, pad + n_samples) */
        memset(win_audio, 0, (size_t)W * sizeof(float));
        size_t w_end = s0 + (size_t)W;
        size_t ov_lo = s0 > (size_t)pad ? s0 : (size_t)pad;
        size_t ov_hi = w_end < (size_t)pad + n_samples ? w_end : (size_t)pad + n_samples;
        if (ov_hi > ov_lo) {
            memcpy(win_audio + (ov_lo - s0), audio_16k + (ov_lo - (size_t)pad),
                   (ov_hi - ov_lo) * sizeof(float));
        }

        int is_sub = want_sub && ((s0 % (size_t)sub_step) == 0);
        int got_T = lanenet_forward(net, win_audio, W, win_logits,
                                    is_sub ? win_stem : NULL,
                                    (want_hidden || is_sub) ? win_hidden : NULL);
        if (got_T != Fw) goto fail;

        int g0 = (int)floor((double)s0 / (double)MODEL_RATE / HOP_S + 0.5) - g_pad;
        int a = g0 > 0 ? g0 : 0;
        int b = (g0 + Fw) < T ? (g0 + Fw) : T;
        if (b <= a) continue;

        /* Accumulate maps */
        for (int t = a; t < b; ++t) {
            float wt = hann[t - g0];
            wsum[t] += wt;
            if (is_sub) sub_wsum[t] += wt;
            const float *src_t = win_logits + (size_t)(t - g0) * LANE_KEYS * LANE_HEADS;
            for (int k = 0; k < LANE_KEYS; ++k) {
                const float *lg = src_t + (size_t)k * LANE_HEADS;
                for (int hd = 0; hd < LANE_HEADS; ++hd) {
                    float pr = sigmoidf(lg[hd]) * wt;
                    size_t idx = ((size_t)hd * (size_t)T + (size_t)t) * LANE_KEYS + (size_t)k;
                    out->maps[idx] += pr;
                    if (is_sub) out->sub_maps[idx] += pr;
                }
            }
        }
        if (want_hidden) add_tap_f16(out->hidden_f16, win_hidden, a, b, g0, hann);
        if (is_sub) {
            add_tap_f16(out->sub_hidden_f16, win_hidden, a, b, g0, hann);
            add_tap_f16(out->sub_stem_f16, win_stem, a, b, g0, hann);
        }
    }

    /* Normalize by weight sums */
    for (int hd = 0; hd < LANE_HEADS; ++hd) {
        for (int t = 0; t < T; ++t) {
            float ws = wsum[t] < 1e-6f ? 1e-6f : wsum[t];
            float inv = 1.0f / ws;
            float *row = out->maps + ((size_t)hd * (size_t)T + (size_t)t) * LANE_KEYS;
            for (int k = 0; k < LANE_KEYS; ++k) row[k] *= inv;
        }
    }
    if (want_hidden) finish_tap_f16(out->hidden_f16, wsum, T);
    if (want_sub) {
        for (int hd = 0; hd < LANE_HEADS; ++hd) {
            for (int t = 0; t < T; ++t) {
                float ws = sub_wsum[t] < 1e-6f ? 1e-6f : sub_wsum[t];
                float inv = 1.0f / ws;
                float *row = out->sub_maps + ((size_t)hd * (size_t)T + (size_t)t) * LANE_KEYS;
                for (int k = 0; k < LANE_KEYS; ++k) row[k] *= inv;
            }
        }
        finish_tap_f16(out->sub_hidden_f16, sub_wsum, T);
        finish_tap_f16(out->sub_stem_f16, sub_wsum, T);
    }

    free(wsum); free(sub_wsum);
    free(win_audio); free(win_logits); free(win_hidden); free(win_stem);
    return 1;

fail:
    free(wsum); free(sub_wsum);
    free(win_audio); free(win_logits); free(win_hidden); free(win_stem);
    transcribe_run_free(out);
    return 0;
}

void transcribe_run_free(struct transcribe_run *r) {
    if (!r) return;
    free(r->maps);
    free(r->hidden_f16);
    free(r->sub_maps);
    free(r->sub_hidden_f16);
    free(r->sub_stem_f16);
    memset(r, 0, sizeof(*r));
}

/* =========================================================================
 * Two-voice peak-picking note decoder (matches transcriber/decode.py)
 * ========================================================================= */

static double refine_peak(const float *map, int T, int t, int l) {
    float C = map[(size_t)t * LANE_KEYS + l];
    float A = t > 0 ? map[(size_t)(t - 1) * LANE_KEYS + l] : C;
    float B = t + 1 < T ? map[(size_t)(t + 1) * LANE_KEYS + l] : C;
    float mn = A < B ? A : B;
    float den = 2.0f * (C - mn);
    if (den <= 1e-6f) return 0.0;
    double v = (double)(B - A) / (double)den;
    if (v < -0.5) v = -0.5;
    if (v > 0.5) v = 0.5;
    return v;
}

struct peak_item {
    int t;
    float val;
};

static int cmp_peak_desc(const void *pa, const void *pb) {
    const struct peak_item *a = (const struct peak_item *)pa;
    const struct peak_item *b = (const struct peak_item *)pb;
    if (a->val > b->val) return -1;
    if (a->val < b->val) return 1;
    return (a->t > b->t) - (a->t < b->t);
}

static int cmp_int_asc(const void *pa, const void *pb) {
    int a = *(const int *)pa, b = *(const int *)pb;
    return (a > b) - (a < b);
}

static int cmp_note(const void *pa, const void *pb) {
    const struct vt_note *a = (const struct vt_note *)pa;
    const struct vt_note *b = (const struct vt_note *)pb;
    if (a->onset < b->onset) return -1;
    if (a->onset > b->onset) return 1;
    if (a->offset < b->offset) return -1;
    if (a->offset > b->offset) return 1;
    return (a->pitch > b->pitch) - (a->pitch < b->pitch);
}

static int lower_bound_int(const int *arr, int n, int target) {
    int lo = 0, hi = n;
    while (lo < hi) {
        int mid = lo + (hi - lo) / 2;
        if (arr[mid] < target) lo = mid + 1;
        else hi = mid;
    }
    return lo;
}

static int decode_voice(const float *on, const float *fr, const float *off, int T,
                        float on_th, int slot,
                        struct vt_note **notes, size_t *count, size_t *cap) {
    const float off_th = 0.3f;
    const float fr_th = 0.4f;
    const int on_nms = 3;
    const int off_min_frames = 2;
    const double min_dur = 0.02;

    int *ons = (int *)malloc((size_t)T * sizeof(int));
    int *offs = (int *)malloc((size_t)T * sizeof(int));
    int *lows = (int *)malloc((size_t)T * sizeof(int));
    struct peak_item *order = (struct peak_item *)malloc((size_t)T * sizeof(struct peak_item));
    uint8_t *keep = (uint8_t *)malloc((size_t)T);
    if (!ons || !offs || !lows || !order || !keep) {
        free(ons); free(offs); free(lows); free(order); free(keep);
        return 0;
    }

    for (int l = 0; l < LANE_KEYS; ++l) {
        int n_on = 0, n_off = 0, n_low = 0;
        for (int t = 0; t < T; ++t) {
            float p_on = on[(size_t)t * LANE_KEYS + l];
            float l_on = t > 0 ? on[(size_t)(t - 1) * LANE_KEYS + l] : -1.0f;
            float r_on = t + 1 < T ? on[(size_t)(t + 1) * LANE_KEYS + l] : -1.0f;
            if (p_on >= on_th && p_on > l_on && p_on >= r_on) ons[n_on++] = t;

            float p_off = off[(size_t)t * LANE_KEYS + l];
            float l_off = t > 0 ? off[(size_t)(t - 1) * LANE_KEYS + l] : -1.0f;
            float r_off = t + 1 < T ? off[(size_t)(t + 1) * LANE_KEYS + l] : -1.0f;
            if (p_off >= off_th && p_off > l_off && p_off >= r_off) offs[n_off++] = t;

            int low0 = fr[(size_t)t * LANE_KEYS + l] < fr_th;
            int low1 = (t + 1 < T) ? (fr[(size_t)(t + 1) * LANE_KEYS + l] < fr_th) : 1;
            if (low0 && low1) lows[n_low++] = t;
        }
        if (n_on == 0) continue;

        /* NMS within on_nms frames */
        if (on_nms > 0 && n_on > 1) {
            for (int i = 0; i < n_on; ++i) {
                order[i].t = i;
                order[i].val = on[(size_t)ons[i] * LANE_KEYS + l];
                keep[i] = 1;
            }
            qsort(order, (size_t)n_on, sizeof(order[0]), cmp_peak_desc);
            for (int k = 0; k < n_on; ++k) {
                int oi = order[k].t;
                if (!keep[oi]) continue;
                int t_best = ons[oi];
                for (int j = 0; j < n_on; ++j) {
                    if (j != oi && abs(ons[j] - t_best) <= on_nms) keep[j] = 0;
                }
            }
            int w = 0;
            for (int i = 0; i < n_on; ++i)
                if (keep[i]) ons[w++] = ons[i];
            n_on = w;
            qsort(ons, (size_t)n_on, sizeof(int), cmp_int_asc);
        }

        for (int i = 0; i < n_on; ++i) {
            int t0 = ons[i];
            double u0 = (double)t0 + refine_peak(on, T, t0, l);
            int nxt = (i + 1 < n_on) ? ons[i + 1] : T;
            int j_fr = lower_bound_int(lows, n_low, t0 + 1);
            int e_fr = (j_fr < n_low) ? lows[j_fr] : T;
            int j_off = lower_bound_int(offs, n_off, t0 + off_min_frames);
            int e_off = (j_off < n_off) ? offs[j_off] : T;
            int min_fr_nxt = e_fr < nxt ? e_fr : nxt;

            double u1;
            if (e_off < T && e_off <= min_fr_nxt) {
                u1 = (double)e_off + refine_peak(off, T, e_off, l);
            } else if (e_fr <= nxt) {
                u1 = (double)e_fr - 0.5;
            } else {
                u1 = (double)nxt + (nxt < T ? refine_peak(on, T, nxt, l) : 0.0);
            }
            double on_s = u0 * HOP_S;
            double off_s = u1 * HOP_S;
            if (off_s < on_s + min_dur) off_s = on_s + min_dur;

            int tc = (int)floor(on_s / HOP_S + 0.5);
            if (tc < 0) tc = 0;
            if (tc >= T) tc = T - 1;
            float conf = on[(size_t)tc * LANE_KEYS + l];

            if (*count == *cap) {
                size_t next = *cap ? (*cap * 2) : 256;
                struct vt_note *grown = (struct vt_note *)realloc(*notes, next * sizeof(*grown));
                if (!grown) {
                    free(ons); free(offs); free(lows); free(order); free(keep);
                    return 0;
                }
                *notes = grown;
                *cap = next;
            }
            (*notes)[(*count)++] = (struct vt_note){ on_s, off_s, PITCH_LO + l, conf, slot };
        }
    }

    free(ons); free(offs); free(lows); free(order); free(keep);
    return 1;
}

int transcribe_decode(const float *maps, int T, struct vt_note **notes_out, size_t *count_out) {
    *notes_out = NULL;
    *count_out = 0;
    if (!maps || T <= 0) return 1;

    size_t stride = (size_t)T * LANE_KEYS;
    struct vt_note *notes = NULL;
    size_t count = 0, cap = 0;
    if (!decode_voice(maps + HEAD_ONSET * stride, maps + HEAD_FRAME * stride,
                      maps + HEAD_OFFSET * stride, T, 0.25f, 1, &notes, &count, &cap)) {
        free(notes); return 0;
    }
    if (!decode_voice(maps + HEAD_ONSET2 * stride, maps + HEAD_FRAME2 * stride,
                      maps + HEAD_OFFSET2 * stride, T, 0.30f, 2, &notes, &count, &cap)) {
        free(notes); return 0;
    }
    if (count > 1) qsort(notes, count, sizeof(*notes), cmp_note);
    *notes_out = notes;
    *count_out = count;
    return 1;
}
