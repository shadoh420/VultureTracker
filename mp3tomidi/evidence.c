/* Native port of Dettato's evidence/{features,model,repair}.py,
 * revision 51ade0f09f2272f4674166026582185d26baaeaf. See vendor/dettato/. */
#include "evidence.h"
#include "nn.h"
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

enum {
    EV_D = 192,
    EV_LAYERS = 9,
    EV_HEADS = 6,
    EV_HD = 32,
    EV_FF = 576,
    EV_NEV = 769,
    EV_CONT = 110,
    EV_NDON = 201,
    EV_NDR = 161,
    EV_NDUR = 128,
    EV_NINSP = 49,
    EV_NINST = 401,
    EV_INS_DIM = 1 + 49 + 401 + 128, /* 579 */
    EV_MAX_WIN = 4096
};

static const double EV_TAU = 6.2831853071795864769;

struct ev_block {
    float *n1_w;
    float *q_w, *kv_w, *o_w;
    float *n2_w;
    float *ff_w1, *ff_w2;
};

struct evidence_model {
    float *emb_inst;    /* [130, 192] */
    float *emb_pitch;   /* [256, 192] */
    float *emb_vel;     /* [16, 192] */
    float *cont0_w, *cont0_b; /* [192, 110], [192] */
    float *cont2_w, *cont2_b; /* [192, 192], [192] */
    float *evm0_w, *evm0_b;   /* [192, 769], [192] */
    float *evm2_w, *evm2_b;   /* [192, 192], [192] */
    float *emb_norm_w;        /* [192] */
    struct ev_block blocks[EV_LAYERS];
    float *bb_norm_w;
    float *keep_w, *keep_b;   /* [1, 192], [1] */
    float *don_w, *don_b;     /* [201, 192], [201] */
    float *dur_w, *dur_b;     /* [161, 192], [161] */
    float *ins_w[2], *ins_b[2]; /* [579, 192], [579] */
    /* Precomputed constants */
    float dur_cent[EV_NDUR];
    float dur_W[EV_NDUR * EV_NDUR]; /* row-major [EV_NDUR, EV_NDUR] */
};

static float round_even_f(double x) {
    return (float)rint(x);
}

struct evidence_model *evidence_load(const struct vtwt_file *wf) {
    struct evidence_model *m = (struct evidence_model *)calloc(1, sizeof(*m));
    if (!m) return NULL;
    char name[VTWT_NAME_MAX];

    uint32_t s_inst[2] = {130, EV_D}, s_pitch[2] = {256, EV_D}, s_vel[2] = {16, EV_D};
    uint32_t s_d[1] = {EV_D}, s_dd[2] = {EV_D, EV_D};
    uint32_t s_c0[2] = {EV_D, EV_CONT}, s_e0[2] = {EV_D, EV_NEV};
    uint32_t s_kv[2] = {2 * EV_D, EV_D}, s_f1[2] = {2 * EV_FF, EV_D}, s_f2[2] = {EV_D, EV_FF};
    uint32_t s_kw[2] = {1, EV_D}, s_kb[1] = {1};
    uint32_t s_dw[2] = {EV_NDON, EV_D}, s_db[1] = {EV_NDON};
    uint32_t s_rw[2] = {EV_NDR, EV_D}, s_rb[1] = {EV_NDR};
    uint32_t s_iw[2] = {EV_INS_DIM, EV_D}, s_ib[1] = {EV_INS_DIM};

    m->emb_inst = vtwt_read_f32(wf, "emb.inst.weight", 2, s_inst);
    m->emb_pitch = vtwt_read_f32(wf, "emb.pitch.weight", 2, s_pitch);
    m->emb_vel = vtwt_read_f32(wf, "emb.vel.weight", 2, s_vel);
    m->cont0_w = vtwt_read_f32(wf, "emb.cont.0.weight", 2, s_c0);
    m->cont0_b = vtwt_read_f32(wf, "emb.cont.0.bias", 1, s_d);
    m->cont2_w = vtwt_read_f32(wf, "emb.cont.2.weight", 2, s_dd);
    m->cont2_b = vtwt_read_f32(wf, "emb.cont.2.bias", 1, s_d);
    m->evm0_w = vtwt_read_f32(wf, "emb.evm.0.weight", 2, s_e0);
    m->evm0_b = vtwt_read_f32(wf, "emb.evm.0.bias", 1, s_d);
    m->evm2_w = vtwt_read_f32(wf, "emb.evm.2.weight", 2, s_dd);
    m->evm2_b = vtwt_read_f32(wf, "emb.evm.2.bias", 1, s_d);
    m->emb_norm_w = vtwt_read_f32(wf, "emb.norm.w", 1, s_d);
    if (!m->emb_inst || !m->emb_pitch || !m->emb_vel || !m->cont0_w || !m->cont0_b ||
        !m->cont2_w || !m->cont2_b || !m->evm0_w || !m->evm0_b || !m->evm2_w ||
        !m->evm2_b || !m->emb_norm_w) goto fail;

    for (int i = 0; i < EV_LAYERS; ++i) {
        struct ev_block *b = &m->blocks[i];
        snprintf(name, sizeof(name), "bb.blocks.%d.n1.w", i); b->n1_w = vtwt_read_f32(wf, name, 1, s_d);
        snprintf(name, sizeof(name), "bb.blocks.%d.att.q.weight", i); b->q_w = vtwt_read_f32(wf, name, 2, s_dd);
        snprintf(name, sizeof(name), "bb.blocks.%d.att.kv.weight", i); b->kv_w = vtwt_read_f32(wf, name, 2, s_kv);
        snprintf(name, sizeof(name), "bb.blocks.%d.att.o.weight", i); b->o_w = vtwt_read_f32(wf, name, 2, s_dd);
        snprintf(name, sizeof(name), "bb.blocks.%d.n2.w", i); b->n2_w = vtwt_read_f32(wf, name, 1, s_d);
        snprintf(name, sizeof(name), "bb.blocks.%d.ff.w1.weight", i); b->ff_w1 = vtwt_read_f32(wf, name, 2, s_f1);
        snprintf(name, sizeof(name), "bb.blocks.%d.ff.w2.weight", i); b->ff_w2 = vtwt_read_f32(wf, name, 2, s_f2);
        if (!b->n1_w || !b->q_w || !b->kv_w || !b->o_w || !b->n2_w || !b->ff_w1 || !b->ff_w2) goto fail;
    }

    m->bb_norm_w = vtwt_read_f32(wf, "bb.norm.w", 1, s_d);
    m->keep_w = vtwt_read_f32(wf, "keep.weight", 2, s_kw);
    m->keep_b = vtwt_read_f32(wf, "keep.bias", 1, s_kb);
    m->don_w = vtwt_read_f32(wf, "don.weight", 2, s_dw);
    m->don_b = vtwt_read_f32(wf, "don.bias", 1, s_db);
    m->dur_w = vtwt_read_f32(wf, "dur.weight", 2, s_rw);
    m->dur_b = vtwt_read_f32(wf, "dur.bias", 1, s_rb);
    for (int s = 0; s < 2; ++s) {
        snprintf(name, sizeof(name), "ins.%d.weight", s); m->ins_w[s] = vtwt_read_f32(wf, name, 2, s_iw);
        snprintf(name, sizeof(name), "ins.%d.bias", s);   m->ins_b[s] = vtwt_read_f32(wf, name, 1, s_ib);
        if (!m->ins_w[s] || !m->ins_b[s]) goto fail;
    }
    if (!m->bb_norm_w || !m->keep_w || !m->keep_b || !m->don_w || !m->don_b || !m->dur_w || !m->dur_b) goto fail;

    /* Precompute DUR_CENT and _dur_matrix W[i, j] = (|c[j] - c[i]| <= max(0.2*c[i], 0.05)) */
    double log_lo = log(0.01), log_hi = log(16.0);
    double edges[EV_NDUR + 1];
    for (int i = 0; i <= EV_NDUR; ++i)
        edges[i] = exp(log_lo + (log_hi - log_lo) * (double)i / (double)EV_NDUR);
    for (int i = 0; i < EV_NDUR; ++i)
        m->dur_cent[i] = (float)sqrt(edges[i] * edges[i + 1]);
    for (int i = 0; i < EV_NDUR; ++i) {
        float ci = m->dur_cent[i];
        float tol = 0.2f * ci;
        if (tol < 0.05f) tol = 0.05f;
        for (int j = 0; j < EV_NDUR; ++j)
            m->dur_W[i * EV_NDUR + j] = (fabsf(m->dur_cent[j] - ci) <= tol) ? 1.0f : 0.0f;
    }
    return m;

fail:
    evidence_free(m);
    return NULL;
}

void evidence_free(struct evidence_model *m) {
    if (!m) return;
    free(m->emb_inst); free(m->emb_pitch); free(m->emb_vel);
    free(m->cont0_w); free(m->cont0_b); free(m->cont2_w); free(m->cont2_b);
    free(m->evm0_w); free(m->evm0_b); free(m->evm2_w); free(m->evm2_b);
    free(m->emb_norm_w);
    for (int i = 0; i < EV_LAYERS; ++i) {
        free(m->blocks[i].n1_w); free(m->blocks[i].q_w); free(m->blocks[i].kv_w);
        free(m->blocks[i].o_w); free(m->blocks[i].n2_w);
        free(m->blocks[i].ff_w1); free(m->blocks[i].ff_w2);
    }
    free(m->bb_norm_w);
    free(m->keep_w); free(m->keep_b);
    free(m->don_w); free(m->don_b);
    free(m->dur_w); free(m->dur_b);
    for (int s = 0; s < 2; ++s) { free(m->ins_w[s]); free(m->ins_b[s]); }
    free(m);
}

/* =========================================================================
 * Evidence vector extraction (matches evidence/features.py)
 * ========================================================================= */

static inline int clamp_i(int v, int lo, int hi) {
    return v < lo ? lo : (v > hi ? hi : v);
}

static void std_quant(const float *x, int n, float *q_out, float *log_sd_out) {
    double sum = 0.0;
    for (int i = 0; i < n; ++i) sum += (double)x[i];
    double mu = sum / (double)n;
    double var = 0.0;
    for (int i = 0; i < n; ++i) {
        double d = (double)x[i] - mu;
        var += d * d;
    }
    double sd = sqrt(var / (double)n) + 1e-6;
    *log_sd_out = (float)log(sd);
    for (int i = 0; i < n; ++i) {
        double z = ((double)x[i] - mu) / sd;
        if (z < -3.96) z = -3.96;
        if (z > 3.96) z = 3.96;
        int8_t qi = (int8_t)round_even_f(z * 32.0);
        q_out[i] = (float)qi / 32.0f;
    }
}

static void build_evidence_row(const float *maps, const uint16_t *hidden_f16, int T,
                               const struct vt_note *note, float *ev_out) {
    size_t stride = (size_t)T * LANE_KEYS;
    const float *on1 = maps + HEAD_ONSET * stride;
    const float *fr1 = maps + HEAD_FRAME * stride;
    const float *off1 = maps + HEAD_OFFSET * stride;
    const float *on2 = maps + HEAD_ONSET2 * stride;
    const float *fr2 = maps + HEAD_FRAME2 * stride;
    const float *off2 = maps + HEAD_OFFSET2 * stride;

    int L = clamp_i(note->pitch - PITCH_LO, 0, LANE_KEYS - 1);
    int A = clamp_i((int)rint(note->onset / 0.02), 0, T - 1);
    int B = clamp_i((int)rint(note->offset / 0.02), A + 1, T);
    int span = B - A;
    if (span < 1) span = 1;

    const float *own_on = (note->slot == 1) ? on1 : on2;
    const float *own_fr = (note->slot == 1) ? fr1 : fr2;
    const float *own_off = (note->slot == 1) ? off1 : off2;
    const float *oth_on = (note->slot == 1) ? on2 : on1;
    const float *oth_fr = (note->slot == 1) ? fr2 : fr1;

    float mf[33];
    int idx = 0;
    for (int d = -2; d <= 2; ++d)
        mf[idx++] = own_on[(size_t)clamp_i(A + d, 0, T - 1) * LANE_KEYS + L];
    for (int j = 0; j < 8; ++j)
        mf[idx++] = own_fr[(size_t)clamp_i(A + (j * span) / 8, 0, T - 1) * LANE_KEYS + L];
    static const int aft[4] = {1, 3, 6, 12};
    for (int j = 0; j < 4; ++j)
        mf[idx++] = own_fr[(size_t)clamp_i(B - 1 + aft[j], 0, T - 1) * LANE_KEYS + L];
    float pre_max = 0.0f;
    for (int k = 1; k <= 5; ++k) {
        float v = (A - k >= 0) ? own_fr[(size_t)(A - k) * LANE_KEYS + L] : 0.0f;
        if (k == 1 || v > pre_max) pre_max = v;
    }
    mf[idx++] = pre_max;

    float om = 0.0f, opos = 0.0f;
    int seg_end = B + 12 < T ? B + 12 : T;
    if (A + 1 < seg_end) {
        int best_j = 0;
        float best_v = own_off[(size_t)(A + 1) * LANE_KEYS + L];
        for (int t = A + 2; t < seg_end; ++t) {
            float v = own_off[(size_t)t * LANE_KEYS + L];
            if (v > best_v) { best_v = v; best_j = t - (A + 1); }
        }
        om = best_v;
        opos = (float)(best_j + 1) / (float)span;
        if (opos > 2.0f) opos = 2.0f;
    }
    mf[idx++] = om;
    mf[idx++] = opos;
    mf[idx++] = own_off[(size_t)clamp_i(B - 1, 0, T - 1) * LANE_KEYS + L];

    float oth_on_max = -1.0f;
    for (int d = -1; d <= 1; ++d) {
        float v = oth_on[(size_t)clamp_i(A + d, 0, T - 1) * LANE_KEYS + L];
        if (v > oth_on_max) oth_on_max = v;
    }
    mf[idx++] = oth_on_max;
    mf[idx++] = oth_fr[(size_t)clamp_i(A, 0, T - 1) * LANE_KEYS + L];
    float oth_fr_sum = 0.0f;
    for (int j = 0; j < 4; ++j)
        oth_fr_sum += oth_fr[(size_t)clamp_i(A + (j * span) / 4, 0, T - 1) * LANE_KEYS + L];
    mf[idx++] = oth_fr_sum * 0.25f;

    mf[idx++] = (note->slot == 2) ? 1.0f : 0.0f;
    static const int dls[6] = {-1, 1, -12, 12, 19, 24};
    for (int j = 0; j < 6; ++j) {
        int l2 = L + dls[j];
        if (l2 >= 0 && l2 < LANE_KEYS) {
            float mx = -1.0f;
            for (int d = -1; d <= 1; ++d) {
                float v = on1[(size_t)clamp_i(A + d, 0, T - 1) * LANE_KEYS + l2];
                if (v > mx) mx = v;
            }
            mf[idx++] = mx;
        } else {
            mf[idx++] = 0.0f;
        }
    }

    float at_vec[LANE_C], mean_vec[LANE_C];
    const uint16_t *h_at = hidden_f16 + ((size_t)A * LANE_KEYS + L) * LANE_C;
    for (int c = 0; c < LANE_C; ++c) {
        at_vec[c] = vt_f16_to_f32(h_at[c]);
        mean_vec[c] = 0.0f;
    }
    for (int t = A; t < B; ++t) {
        const uint16_t *ht = hidden_f16 + ((size_t)t * LANE_KEYS + L) * LANE_C;
        for (int c = 0; c < LANE_C; ++c) mean_vec[c] += vt_f16_to_f32(ht[c]);
    }
    float inv_span = 1.0f / (float)span;
    for (int c = 0; c < LANE_C; ++c) mean_vec[c] *= inv_span;

    float la = 0.0f, lmn = 0.0f;
    std_quant(at_vec, LANE_C, ev_out + 33, &la);
    std_quant(mean_vec, LANE_C, ev_out + 33 + LANE_C, &lmn);
    mf[31] = la;
    mf[32] = lmn;
    /* Match Python's float16 round-trip on the 33 scalar features */
    for (int i = 0; i < 33; ++i) ev_out[i] = vt_f16_to_f32(vt_f32_to_f16(mf[i]));
}

/* =========================================================================
 * Transformer forward pass on one 8 s window of N notes
 * ========================================================================= */

static inline float siluf(float x) {
    return x / (1.0f + expf(-x));
}

static void rmsnorm(const float *x, float *y, int N, int D, const float *w, float eps) {
    float inv_d = 1.0f / (float)D;
    for (int i = 0; i < N; ++i) {
        const float *xi = x + (size_t)i * D;
        float *yi = y + (size_t)i * D;
        double s2 = 0.0;
        for (int d = 0; d < D; ++d) s2 += (double)xi[d] * (double)xi[d];
        float sc = 1.0f / sqrtf((float)(s2 * inv_d) + eps);
        for (int d = 0; d < D; ++d) yi[d] = xi[d] * sc * w[d];
    }
}

static void write_fourier(float val, int n, double lo, double hi, float *out) {
    double l0 = log(lo), l1 = log(hi);
    for (int i = 0; i < n; ++i) {
        double lam = exp(l0 + (l1 - l0) * (double)i / (double)(n - 1));
        double a = EV_TAU * (double)val / lam;
        out[i] = (float)sin(a);
        out[n + i] = (float)cos(a);
    }
}

static float signed_log(float x) {
    float s = x > 0.0f ? 1.0f : (x < 0.0f ? -1.0f : 0.0f);
    return s * log1pf(fabsf(x) * 20.0f);
}

struct ev_in_note {
    int inst;
    int pitch;
    int vel;
    double on;
    double off;
    size_t orig_idx;
};

static int cmp_ev_in(const void *pa, const void *pb) {
    const struct ev_in_note *a = (const struct ev_in_note *)pa;
    const struct ev_in_note *b = (const struct ev_in_note *)pb;
    if (a->on < b->on) return -1;
    if (a->on > b->on) return 1;
    if (a->inst != b->inst) return a->inst - b->inst;
    if (a->pitch != b->pitch) return a->pitch - b->pitch;
    return (a->orig_idx > b->orig_idx) - (a->orig_idx < b->orig_idx);
}

struct ev_cand {
    int inst;
    int pitch;
    double on;
    double off;
    float score;
    int kind;   /* 0 = kept edit, 1 = insertion */
};

static int box_argmax_softmax(const float *logits, int len, int half) {
    float mx = logits[0];
    for (int i = 1; i < len; ++i) if (logits[i] > mx) mx = logits[i];
    float p[512];
    double sum = 0.0;
    for (int i = 0; i < len; ++i) {
        p[i] = expf(logits[i] - mx);
        sum += p[i];
    }
    float inv = (float)(1.0 / sum);
    for (int i = 0; i < len; ++i) p[i] *= inv;
    int best = 0;
    float best_v = -1.0f;
    for (int i = 0; i < len; ++i) {
        int lo = i - half; if (lo < 0) lo = 0;
        int hi = i + half; if (hi >= len) hi = len - 1;
        float s = 0.0f;
        for (int j = lo; j <= hi; ++j) s += p[j];
        if (s > best_v) { best_v = s; best = i; }
    }
    return best;
}

static int run_window(const struct evidence_model *m,
                      const struct ev_in_note *win_notes, const float *win_ev,
                      int N, double t0, struct ev_cand *cands_out) {
    float *on = (float *)malloc((size_t)N * sizeof(float));
    float *dur = (float *)malloc((size_t)N * sizeof(float));
    float *cont = (float *)malloc((size_t)N * EV_CONT * sizeof(float));
    float *x = (float *)malloc((size_t)N * EV_D * sizeof(float));
    float *h = (float *)malloc((size_t)N * EV_D * sizeof(float));
    float *tmp_d = (float *)malloc((size_t)N * EV_D * sizeof(float));
    float *q = (float *)malloc((size_t)N * EV_D * sizeof(float));
    float *kv = (float *)malloc((size_t)N * 2 * EV_D * sizeof(float));
    float *ff = (float *)malloc((size_t)N * 2 * EV_FF * sizeof(float));
    float *rcos = (float *)malloc((size_t)N * 14 * sizeof(float));
    float *rsin = (float *)malloc((size_t)N * 14 * sizeof(float));
    float *scores = (float *)malloc((size_t)N * sizeof(float));
    int ok = 0;
    if (!on || !dur || !cont || !x || !h || !tmp_d || !q || !kv || !ff || !rcos || !rsin || !scores)
        goto cleanup;

    for (int i = 0; i < N; ++i) {
        on[i] = (float)(win_notes[i].on - t0);
        float d = (float)(win_notes[i].off - win_notes[i].on);
        dur[i] = d > 0.0f ? d : 0.0f;
    }

    /* Grid features (shared period search over window) */
    double P_grid[72], R[72], phase[72], Rm[72];
    double gp0 = log(0.18), gp1 = log(1.5);
    for (int k = 0; k < 72; ++k) {
        P_grid[k] = exp(gp0 + (gp1 - gp0) * (double)k / 71.0);
        double zr = 0.0, zi = 0.0;
        for (int i = 0; i < N; ++i) {
            double ang = EV_TAU * (double)on[i] / P_grid[k];
            zr += cos(ang);
            zi += sin(ang);
        }
        R[k] = hypot(zr, zi) / (double)(N > 1 ? N : 1);
        phase[k] = atan2(zi, zr);
        Rm[k] = R[k];
    }
    int best_k[2];
    for (int p = 0; p < 2; ++p) {
        int bk = 0;
        for (int k = 1; k < 72; ++k) if (Rm[k] > Rm[bk]) bk = k;
        best_k[p] = bk;
        for (int k = 0; k < 72; ++k) if (abs(k - bk) <= 3) Rm[k] = -1.0;
    }

    /* Build cont[N, 110] and initial discrete embeddings x[N, 192] */
    static const int subdiv[6] = {1, 2, 3, 4, 6, 8};
    for (int i = 0; i < N; ++i) {
        int drum = (win_notes[i].inst == 128) ? 1 : 0;
        const float *ei = m->emb_inst + (size_t)win_notes[i].inst * EV_D;
        const float *ep = m->emb_pitch + (size_t)(win_notes[i].pitch + 128 * drum) * EV_D;
        const float *evv = m->emb_vel + (size_t)(win_notes[i].vel / 8) * EV_D;
        float *xi = x + (size_t)i * EV_D;
        for (int d = 0; d < EV_D; ++d) xi[d] = ei[d] + ep[d] + evv[d];

        float *ci = cont + (size_t)i * EV_CONT;
        float d_cl = dur[i] < 1e-4f ? 1e-4f : dur[i];
        float ld = logf(d_cl);
        write_fourier(on[i], 12, 0.01, 32.0, ci + 0);
        write_fourier(ld, 12, 0.04, 40.0, ci + 24);
        write_fourier(on[i] + dur[i], 12, 0.01, 32.0, ci + 48);
        ci[72] = (ld + 3.0f) / 3.0f;
        ci[73] = (dur[i] > 8.0f ? 8.0f : dur[i]) * 0.5f;

        /* Context features (8) */
        int key_i = win_notes[i].inst * 128 + win_notes[i].pitch;
        float off_i = on[i] + dur[i];
        float prev_gap_on = 10.0f; int prev_idx = 0;
        float next_gap_on = 10.0f;
        int chord = 0, dens = 0, dens_inst = 0, same_p_near = 0;
        for (int j = 0; j < N; ++j) {
            float dt = on[j] - on[i];
            float adt = fabsf(dt);
            int same_inst = (win_notes[j].inst == win_notes[i].inst);
            int sk = (j != i) && (win_notes[j].inst * 128 + win_notes[j].pitch == key_i);
            if (sk && dt <= 0.0f && -dt < prev_gap_on) { prev_gap_on = -dt; prev_idx = j; }
            if (sk && dt > 0.0f && dt < next_gap_on) next_gap_on = dt;
            if (adt < 0.035f && same_inst) chord++;
            if (adt < 0.5f) { dens++; if (same_inst) dens_inst++; }
            if (sk && adt < 0.25f) same_p_near++;
        }
        float prev_gap_off = (prev_gap_on < 10.0f) ? (on[i] - (on[prev_idx] + dur[prev_idx])) : 10.0f;
        float next_overlap = (next_gap_on < 10.0f) ? (off_i - (on[i] + next_gap_on)) : -10.0f;
        ci[74] = signed_log(prev_gap_on);
        ci[75] = signed_log(prev_gap_off);
        ci[76] = signed_log(next_gap_on);
        ci[77] = signed_log(next_overlap);
        ci[78] = log1pf((float)chord);
        ci[79] = log1pf((float)dens);
        ci[80] = log1pf((float)dens_inst);
        ci[81] = log1pf((float)same_p_near);

        /* Grid features (28) */
        int gi = 82;
        for (int p = 0; p < 2; ++p) {
            int bk = best_k[p];
            double base = EV_TAU * (double)on[i] / P_grid[bk] - phase[bk];
            for (int s = 0; s < 6; ++s) {
                ci[gi++] = (float)sin((double)subdiv[s] * base);
                ci[gi++] = (float)cos((double)subdiv[s] * base);
            }
            ci[gi++] = (float)R[bk];
            ci[gi++] = (float)log(P_grid[bk]);
        }
    }

    /* cont MLP + evm MLP added to x, then RMSNorm */
    nn_sgemm_nt(N, EV_D, EV_CONT, cont, EV_CONT, m->cont0_w, EV_CONT, tmp_d, EV_D, m->cont0_b, 0);
    for (int i = 0; i < N * EV_D; ++i) tmp_d[i] = siluf(tmp_d[i]);
    nn_sgemm_nt(N, EV_D, EV_D, tmp_d, EV_D, m->cont2_w, EV_D, x, EV_D, m->cont2_b, 1);

    nn_sgemm_nt(N, EV_D, EV_NEV, win_ev, EV_NEV, m->evm0_w, EV_NEV, tmp_d, EV_D, m->evm0_b, 0);
    for (int i = 0; i < N * EV_D; ++i) tmp_d[i] = siluf(tmp_d[i]);
    nn_sgemm_nt(N, EV_D, EV_D, tmp_d, EV_D, m->evm2_w, EV_D, x, EV_D, m->evm2_b, 1);

    rmsnorm(x, x, N, EV_D, m->emb_norm_w, 1e-6f);

    /* Precompute MultiAxisRope cos/sin for 14 pairs: 10 on time [0.02, 40], 4 on pitch [2, 96] */
    double w_rope[14];
    for (int k = 0; k < 10; ++k)
        w_rope[k] = EV_TAU / exp(log(0.02) + (log(40.0) - log(0.02)) * (double)k / 9.0);
    for (int k = 0; k < 4; ++k)
        w_rope[10 + k] = EV_TAU / exp(log(2.0) + (log(96.0) - log(2.0)) * (double)k / 3.0);
    for (int i = 0; i < N; ++i) {
        for (int k = 0; k < 10; ++k) {
            double a = (double)on[i] * w_rope[k];
            rcos[i * 14 + k] = (float)cos(a);
            rsin[i * 14 + k] = (float)sin(a);
        }
        for (int k = 0; k < 4; ++k) {
            double a = (double)win_notes[i].pitch * w_rope[10 + k];
            rcos[i * 14 + 10 + k] = (float)cos(a);
            rsin[i * 14 + 10 + k] = (float)sin(a);
        }
    }

    /* 9 Transformer blocks */
    const float att_scale = 1.0f / sqrtf((float)EV_HD);
    for (int li = 0; li < EV_LAYERS; ++li) {
        const struct ev_block *blk = &m->blocks[li];
        rmsnorm(x, h, N, EV_D, blk->n1_w, 1e-6f);
        nn_sgemm_nt(N, EV_D, EV_D, h, EV_D, blk->q_w, EV_D, q, EV_D, NULL, 0);
        nn_sgemm_nt(N, 2 * EV_D, EV_D, h, EV_D, blk->kv_w, EV_D, kv, 2 * EV_D, NULL, 0);

        /* Apply interleaved MultiAxisRope to q and k (first 28 of 32 dims per head) */
        for (int i = 0; i < N; ++i) {
            const float *c = rcos + i * 14, *s = rsin + i * 14;
            for (int hd = 0; hd < EV_HEADS; ++hd) {
                float *qh = q + i * EV_D + hd * EV_HD;
                float *kh = kv + i * 2 * EV_D + hd * EV_HD;
                for (int p = 0; p < 14; ++p) {
                    float q1 = qh[2 * p], q2 = qh[2 * p + 1];
                    qh[2 * p]     = q1 * c[p] - q2 * s[p];
                    qh[2 * p + 1] = q1 * s[p] + q2 * c[p];
                    float k1 = kh[2 * p], k2 = kh[2 * p + 1];
                    kh[2 * p]     = k1 * c[p] - k2 * s[p];
                    kh[2 * p + 1] = k1 * s[p] + k2 * c[p];
                }
            }
        }

        /* Scaled dot-product attention (all N notes unmasked) */
        for (int hd = 0; hd < EV_HEADS; ++hd) {
            for (int qi = 0; qi < N; ++qi) {
                const float *qv = q + qi * EV_D + hd * EV_HD;
                float mx = -1e30f;
                for (int ki = 0; ki < N; ++ki) {
                    const float *kvp = kv + ki * 2 * EV_D + hd * EV_HD;
                    float dot = 0.0f;
                    for (int d = 0; d < EV_HD; ++d) dot += qv[d] * kvp[d];
                    float sc = dot * att_scale;
                    scores[ki] = sc;
                    if (sc > mx) mx = sc;
                }
                float se = 0.0f;
                for (int ki = 0; ki < N; ++ki) {
                    float e = expf(scores[ki] - mx);
                    scores[ki] = e;
                    se += e;
                }
                float inv = 1.0f / se;
                float *dst = tmp_d + qi * EV_D + hd * EV_HD;
                memset(dst, 0, EV_HD * sizeof(float));
                for (int ki = 0; ki < N; ++ki) {
                    float w = scores[ki] * inv;
                    const float *vv = kv + ki * 2 * EV_D + EV_D + hd * EV_HD;
                    for (int d = 0; d < EV_HD; ++d) dst[d] += w * vv[d];
                }
            }
        }
        nn_sgemm_nt(N, EV_D, EV_D, tmp_d, EV_D, blk->o_w, EV_D, x, EV_D, NULL, 1);

        /* SwiGLU FFN */
        rmsnorm(x, h, N, EV_D, blk->n2_w, 1e-6f);
        nn_sgemm_nt(N, 2 * EV_FF, EV_D, h, EV_D, blk->ff_w1, EV_D, ff, 2 * EV_FF, NULL, 0);
        for (int i = 0; i < N; ++i) {
            const float *a = ff + (size_t)i * 2 * EV_FF;
            const float *b = a + EV_FF;
            float *dst = ff + (size_t)i * EV_FF;
            for (int d = 0; d < EV_FF; ++d) dst[d] = siluf(a[d]) * b[d];
        }
        nn_sgemm_nt(N, EV_D, EV_FF, ff, EV_FF, blk->ff_w2, EV_FF, x, EV_D, NULL, 1);
    }

    rmsnorm(x, h, N, EV_D, m->bb_norm_w, 1e-6f);

    /* Decode heads -> N keep candidates + 2*N insertion candidates */
    float *l_keep = (float *)malloc((size_t)N * sizeof(float));
    float *l_don = (float *)malloc((size_t)N * EV_NDON * sizeof(float));
    float *l_dur = (float *)malloc((size_t)N * EV_NDR * sizeof(float));
    float *l_ins0 = (float *)malloc((size_t)N * EV_INS_DIM * sizeof(float));
    float *l_ins1 = (float *)malloc((size_t)N * EV_INS_DIM * sizeof(float));
    if (!l_keep || !l_don || !l_dur || !l_ins0 || !l_ins1) {
        free(l_keep); free(l_don); free(l_dur); free(l_ins0); free(l_ins1);
        goto cleanup;
    }

    nn_sgemm_nt(N, 1, EV_D, h, EV_D, m->keep_w, EV_D, l_keep, 1, m->keep_b, 0);
    nn_sgemm_nt(N, EV_NDON, EV_D, h, EV_D, m->don_w, EV_D, l_don, EV_NDON, m->don_b, 0);
    nn_sgemm_nt(N, EV_NDR, EV_D, h, EV_D, m->dur_w, EV_D, l_dur, EV_NDR, m->dur_b, 0);
    nn_sgemm_nt(N, EV_INS_DIM, EV_D, h, EV_D, m->ins_w[0], EV_D, l_ins0, EV_INS_DIM, m->ins_b[0], 0);
    nn_sgemm_nt(N, EV_INS_DIM, EV_D, h, EV_D, m->ins_w[1], EV_D, l_ins1, EV_INS_DIM, m->ins_b[1], 0);

    for (int i = 0; i < N; ++i) {
        float pk = 1.0f / (1.0f + expf(-l_keep[i]));
        int don_b = box_argmax_softmax(l_don + (size_t)i * EV_NDON, EV_NDON, 10);
        int rb = box_argmax_softmax(l_dur + (size_t)i * EV_NDR, EV_NDR, 3);
        float d_cl = dur[i] < 1e-4f ? 1e-4f : dur[i];
        float dur_k = d_cl * expf((float)rb * 0.05f - 4.0f);
        float on_k = on[i] + ((float)don_b * 0.005f - 0.5f);
        cands_out[i] = (struct ev_cand){
            win_notes[i].inst, win_notes[i].pitch, (double)on_k, (double)(on_k + dur_k), pk, 0
        };

        const float *ins_ptrs[2] = {
            l_ins0 + (size_t)i * EV_INS_DIM,
            l_ins1 + (size_t)i * EV_INS_DIM
        };
        for (int s = 0; s < 2; ++s) {
            const float *ins = ins_ptrs[s];
            float pe = 1.0f / (1.0f + expf(-ins[0]));
            int ip_best = 0;
            for (int j = 1; j < EV_NINSP; ++j)
                if (ins[1 + j] > ins[1 + ip_best]) ip_best = j;
            int pitch_i = clamp_i(win_notes[i].pitch + (ip_best - 24), 0, 127);
            int it = box_argmax_softmax(ins + 1 + EV_NINSP, EV_NINST, 5);
            float on_i = on[i] + ((float)it * 0.01f - 1.0f);

            /* softmax(ins_dur) @ W -> argmax */
            const float *dl = ins + 1 + EV_NINSP + EV_NINST;
            float mx = dl[0];
            for (int j = 1; j < EV_NDUR; ++j) if (dl[j] > mx) mx = dl[j];
            float dp[EV_NDUR];
            double se = 0.0;
            for (int j = 0; j < EV_NDUR; ++j) { dp[j] = expf(dl[j] - mx); se += dp[j]; }
            for (int j = 0; j < EV_NDUR; ++j) dp[j] = (float)(dp[j] / se);
            int idd = 0;
            float best_dw = -1.0f;
            for (int col = 0; col < EV_NDUR; ++col) {
                float acc = 0.0f;
                for (int row = 0; row < EV_NDUR; ++row)
                    acc += dp[row] * m->dur_W[row * EV_NDUR + col];
                if (acc > best_dw) { best_dw = acc; idd = col; }
            }
            float dur_i = m->dur_cent[idd];
            cands_out[N + 2 * i + s] = (struct ev_cand){
                win_notes[i].inst, pitch_i, (double)on_i, (double)(on_i + dur_i), pe, 1
            };
        }
    }

    free(l_keep); free(l_don); free(l_dur); free(l_ins0); free(l_ins1);
    ok = 1;

cleanup:
    free(on); free(dur); free(cont); free(x); free(h); free(tmp_d);
    free(q); free(kv); free(ff); free(rcos); free(rsin); free(scores);
    return ok;
}

/* =========================================================================
 * Deduplication + full repair driver (matches evidence/repair.py)
 * ========================================================================= */

struct cand_ref {
    int key;
    double on;
    float score;
    size_t idx;
};

static int cmp_cand_key_on(const void *pa, const void *pb) {
    const struct cand_ref *a = (const struct cand_ref *)pa;
    const struct cand_ref *b = (const struct cand_ref *)pb;
    if (a->key != b->key) return a->key - b->key;
    if (a->on < b->on) return -1;
    if (a->on > b->on) return 1;
    return (a->idx > b->idx) - (a->idx < b->idx);
}

static int cmp_size_t(const void *pa, const void *pb) {
    size_t a = *(const size_t *)pa, b = *(const size_t *)pb;
    return (a > b) - (a < b);
}

static int conf_to_vel_ev(float conf) {
    double x = ((double)conf - 0.25) / 0.75;
    int v = (int)rint(1.0 + 126.0 * x);
    return clamp_i(v, 1, 127);
}

static double round4(double x) {
    return rint(x * 1e4) / 1e4;
}

int evidence_repair(const struct evidence_model *m,
                    const float *maps, const uint16_t *hidden_f16, int T,
                    const struct vt_note *raw_notes, size_t n_raw,
                    struct repaired_note **out_notes, size_t *out_count,
                    struct repair_info *info) {
    *out_notes = NULL;
    *out_count = 0;
    if (info) memset(info, 0, sizeof(*info));
    if (n_raw == 0) return 1;
    if (!m || !maps || !hidden_f16 || T <= 0) return 0;

    float *ev_raw = (float *)malloc(n_raw * EV_NEV * sizeof(float));
    struct ev_in_note *k = (struct ev_in_note *)malloc(n_raw * sizeof(*k));
    float *ev_sorted = (float *)malloc(n_raw * EV_NEV * sizeof(float));
    double *pk = (double *)malloc(n_raw * sizeof(double));
    double *on_r = (double *)malloc(n_raw * sizeof(double));
    double *off_r = (double *)malloc(n_raw * sizeof(double));
    uint8_t *has_pk = (uint8_t *)calloc(n_raw, 1);
    struct ev_cand *ins_all = NULL;
    size_t ins_count = 0, ins_cap = 0;
    int ok = 0;

    if (!ev_raw || !k || !ev_sorted || !pk || !on_r || !off_r || !has_pk) goto cleanup;

    for (size_t i = 0; i < n_raw; ++i) {
        build_evidence_row(maps, hidden_f16, T, &raw_notes[i], ev_raw + i * EV_NEV);
        double on = round4(raw_notes[i].onset);
        double off = round4(raw_notes[i].offset);
        if (off < on + 1e-3) off = on + 1e-3;
        k[i] = (struct ev_in_note){ 0, raw_notes[i].pitch, conf_to_vel_ev(raw_notes[i].conf), on, off, i };
    }
    qsort(k, n_raw, sizeof(*k), cmp_ev_in);
    for (size_t i = 0; i < n_raw; ++i)
        memcpy(ev_sorted + i * EV_NEV, ev_raw + k[i].orig_idx * EV_NEV, EV_NEV * sizeof(float));
    free(ev_raw); ev_raw = NULL;

    double end_t = 0.0;
    for (size_t i = 0; i < n_raw; ++i) if (k[i].off > end_t) end_t = k[i].off;

    for (double t0 = 0.0; t0 < end_t + 8.0; t0 += 8.0) {
        size_t lo = 0;
        while (lo < n_raw && k[lo].on < t0) lo++;
        size_t hi = lo;
        while (hi < n_raw && k[hi].on < t0 + 8.0) hi++;
        size_t nw = hi - lo;
        if (nw == 0 || nw > EV_MAX_WIN) continue;

        struct ev_cand *wc = (struct ev_cand *)malloc((nw + 2 * nw) * sizeof(*wc));
        if (!wc) goto cleanup;
        if (!run_window(m, k + lo, ev_sorted + lo * EV_NEV, (int)nw, t0, wc)) {
            free(wc); goto cleanup;
        }
        for (size_t i = 0; i < nw; ++i) {
            has_pk[lo + i] = 1;
            int in_win = (wc[i].on >= 0.0 && wc[i].on < 8.0);
            pk[lo + i] = in_win ? (double)wc[i].score : -1.0;
            on_r[lo + i] = wc[i].on + t0;
            off_r[lo + i] = wc[i].off + t0;
        }
        for (size_t i = nw; i < 3 * nw; ++i) {
            if (wc[i].kind != 0 && wc[i].on >= 0.0 && wc[i].on < 8.0 && wc[i].score >= 0.6f) {
                if (ins_count == ins_cap) {
                    size_t next = ins_cap ? ins_cap * 2 : 128;
                    struct ev_cand *g = (struct ev_cand *)realloc(ins_all, next * sizeof(*g));
                    if (!g) { free(wc); goto cleanup; }
                    ins_all = g; ins_cap = next;
                }
                struct ev_cand c = wc[i];
                c.on += t0; c.off += t0;
                ins_all[ins_count++] = c;
            }
        }
        free(wc);
    }

    /* Assemble kept + insertions (keep_th = 0.4, insert_th = 0.6) */
    size_t max_rows = n_raw + ins_count;
    struct ev_cand *rows = (struct ev_cand *)malloc((max_rows ? max_rows : 1) * sizeof(*rows));
    if (!rows) goto cleanup;
    size_t n_rows = 0;
    for (size_t i = 0; i < n_raw; ++i) {
        if (!has_pk[i]) {
            rows[n_rows++] = (struct ev_cand){ 0, k[i].pitch, k[i].on, k[i].off, 1.0f, 0 };
        } else if (pk[i] >= 0.4) {
            rows[n_rows++] = (struct ev_cand){ 0, k[i].pitch, on_r[i], off_r[i], (float)pk[i], 0 };
        }
    }
    size_t n_kept_rows = n_rows;
    for (size_t i = 0; i < ins_count; ++i) rows[n_rows++] = ins_all[i];

    /* Safe dedup: keep all kind==0; drop insertions within 0.03 s of kept same pitch;
     * dedup remaining insertions against each other (same pitch within 0.03 s -> keep higher score). */
    size_t *final_idx = (size_t *)malloc((n_rows ? n_rows : 1) * sizeof(size_t));
    size_t n_final = 0;
    if (!final_idx) { free(rows); goto cleanup; }
    for (size_t i = 0; i < n_kept_rows; ++i) final_idx[n_final++] = i;

    size_t n_ins_cand = n_rows - n_kept_rows;
    if (n_ins_cand > 0) {
        struct cand_ref *ins_ok = (struct cand_ref *)malloc(n_ins_cand * sizeof(*ins_ok));
        uint8_t *ins_keep = (uint8_t *)malloc(n_ins_cand);
        if (!ins_ok || !ins_keep) {
            free(ins_ok); free(ins_keep); free(final_idx); free(rows); goto cleanup;
        }
        size_t n_ok = 0;
        for (size_t i = n_kept_rows; i < n_rows; ++i) {
            int blocked = 0;
            for (size_t j = 0; j < n_kept_rows; ++j) {
                if (rows[j].pitch == rows[i].pitch && fabs(rows[j].on - rows[i].on) < 0.03) {
                    blocked = 1;
                    break;
                }
            }
            if (!blocked) {
                ins_ok[n_ok++] = (struct cand_ref){ rows[i].pitch, rows[i].on, rows[i].score, i };
            }
        }
        if (n_ok > 0) {
            qsort(ins_ok, n_ok, sizeof(*ins_ok), cmp_cand_key_on);
            memset(ins_keep, 1, n_ok);
            for (size_t j = 0; j + 1 < n_ok; ++j) {
                if (ins_ok[j].key == ins_ok[j + 1].key && (ins_ok[j + 1].on - ins_ok[j].on) < 0.03) {
                    if (!ins_keep[j]) continue;
                    if (ins_ok[j].score >= ins_ok[j + 1].score) ins_keep[j + 1] = 0;
                    else ins_keep[j] = 0;
                }
            }
            for (size_t j = 0; j < n_ok; ++j)
                if (ins_keep[j]) final_idx[n_final++] = ins_ok[j].idx;
        }
        free(ins_ok);
        free(ins_keep);
    }
    qsort(final_idx, n_final, sizeof(size_t), cmp_size_t);

    struct repaired_note *res = n_final ? (struct repaired_note *)malloc(n_final * sizeof(*res)) : NULL;
    if (n_final && !res) { free(final_idx); free(rows); goto cleanup; }
    size_t kept_c = 0, ins_c = 0;
    for (size_t i = 0; i < n_final; ++i) {
        const struct ev_cand *c = &rows[final_idx[i]];
        double on_v = round4(c->on);
        double off_raw = c->off < c->on + 0.01 ? c->on + 0.01 : c->off;
        double off_v = round4(off_raw);
        res[i] = (struct repaired_note){ on_v, off_v, c->pitch, c->kind == 1, c->score };
        if (c->kind == 1) ins_c++; else kept_c++;
    }
    free(final_idx);
    free(rows);

    *out_notes = res;
    *out_count = n_final;
    if (info) {
        info->transcribed = n_raw;
        info->kept = kept_c;
        info->dropped = n_raw - kept_c;
        info->inserted = ins_c;
    }
    ok = 1;

cleanup:
    free(ev_raw); free(k); free(ev_sorted); free(pk); free(on_r); free(off_r);
    free(has_pk); free(ins_all);
    return ok;
}
