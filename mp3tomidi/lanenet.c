/* Native implementation of Dettato's transcriber/model.py (LaneNet),
 * revision 51ade0f09f2272f4674166026582185d26baaeaf. See vendor/dettato/. */
#include "lanenet.h"
#include "features.h"
#include "nn.h"
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static const int PMIX_OFFSETS[LANE_PMIX] = {
    -2, -1, 1, 2, -12, 12, -19, 19, -24, 24, -28, 28, -31, 31
};
static const int BLOCK_DILATIONS[4] = { 1, 2, 4, 8 };

struct bn_folded {
    float *scale;
    float *shift;
};

struct lane_block {
    float *dw_w;    /* [7, C] transposed from [C, 1, 7, 1] */
    float *dw_b;    /* [C] */
    float *pmix;    /* [14, C] transposed from [C, 14] */
    struct bn_folded norm;
    float *pw1_w;   /* [2C, C] */
    float *pw1_b;   /* [2C] */
    float *pw2_w;   /* [C, 2C] */
    float *pw2_b;   /* [C] */
    float *gamma;   /* [C] */
    int dt;
};

struct axial_attn {
    int is_time;
    float *ln_w, *ln_b;     /* [C] */
    float *qkv_w, *qkv_b;   /* [3C, C], [3C] */
    float *out_w, *out_b;   /* [C, C], [C] */
    float *gamma;           /* [C] */
    float *rel_bias;        /* [8, 255] if !is_time, else NULL */
};

struct lane_gru {
    float *ln_w, *ln_b;                 /* [C] */
    float *w_ih_f, *b_ih_f;             /* [3H, C], [3H] */
    float *w_hh_f, *b_hh_f;             /* [3H, H], [3H] */
    float *w_ih_r, *b_ih_r;             /* [3H, C], [3H] */
    float *w_hh_r, *b_hh_r;             /* [3H, H], [3H] */
    float *out_w, *out_b;               /* [C, 2H], [C] */
};

struct lanenet {
    /* Stem */
    struct bn_folded inorm;
    float *c1_w, *c1_b; struct bn_folded n1;
    float *c2_w, *c2_b; struct bn_folded n2;
    float *sdown_w, *sdown_b; struct bn_folded n3;
    /* Downsample depthwise 3x1 stride (2,1) */
    float *down_w; /* [3, C] */
    float *down_b; /* [C] */
    /* 15 LaneBlocks + 3x (pitch attn, time attn, gru) */
    struct lane_block blocks[LANE_DEPTH];
    struct axial_attn attn_p[3];
    struct axial_attn attn_t[3];
    struct lane_gru grus[3];
    /* Up norm + 2 refine blocks + head */
    struct bn_folded up_norm;
    struct lane_block refine[LANE_REFINE];
    float *head_w; /* [6, C] */
    float *head_b; /* [6] */
};

/* =========================================================================
 * Weight loading helpers
 * ========================================================================= */

static int load_bn(const struct vtwt_file *wf, const char *prefix, int C, struct bn_folded *bn) {
    char name[VTWT_NAME_MAX];
    uint32_t sh[1] = { (uint32_t)C };
    snprintf(name, sizeof(name), "%s.weight", prefix);
    float *w = vtwt_read_f32(wf, name, 1, sh);
    snprintf(name, sizeof(name), "%s.bias", prefix);
    float *b = vtwt_read_f32(wf, name, 1, sh);
    snprintf(name, sizeof(name), "%s.running_mean", prefix);
    float *m = vtwt_read_f32(wf, name, 1, sh);
    snprintf(name, sizeof(name), "%s.running_var", prefix);
    float *v = vtwt_read_f32(wf, name, 1, sh);
    if (!w || !b || !m || !v) {
        free(w); free(b); free(m); free(v);
        return 0;
    }
    bn->scale = (float *)malloc((size_t)C * sizeof(float));
    bn->shift = (float *)malloc((size_t)C * sizeof(float));
    if (!bn->scale || !bn->shift) {
        free(w); free(b); free(m); free(v);
        return 0;
    }
    nn_bn_params(w, b, m, v, 1e-5f, C, bn->scale, bn->shift);
    free(w); free(b); free(m); free(v);
    return 1;
}

static void free_bn(struct bn_folded *bn) {
    free(bn->scale);
    free(bn->shift);
    bn->scale = bn->shift = NULL;
}

static float *transpose_2d(float *src, int rows, int cols) {
    if (!src) return NULL;
    float *dst = (float *)malloc((size_t)rows * cols * sizeof(float));
    if (!dst) { free(src); return NULL; }
    for (int r = 0; r < rows; ++r)
        for (int c = 0; c < cols; ++c)
            dst[(size_t)c * rows + r] = src[(size_t)r * cols + c];
    free(src);
    return dst;
}

static int load_lane_block(const struct vtwt_file *wf, const char *prefix, int dt, struct lane_block *blk) {
    char name[VTWT_NAME_MAX];
    blk->dt = dt;

    uint32_t sh_dw[4] = { LANE_C, 1, 7, 1 };
    snprintf(name, sizeof(name), "%s.dw_t.weight", prefix);
    blk->dw_w = transpose_2d(vtwt_read_f32(wf, name, 4, sh_dw), LANE_C, 7);

    uint32_t sh_c[1] = { LANE_C };
    snprintf(name, sizeof(name), "%s.dw_t.bias", prefix);
    blk->dw_b = vtwt_read_f32(wf, name, 1, sh_c);

    uint32_t sh_pm[2] = { LANE_C, LANE_PMIX };
    snprintf(name, sizeof(name), "%s.pmix.taps", prefix);
    blk->pmix = transpose_2d(vtwt_read_f32(wf, name, 2, sh_pm), LANE_C, LANE_PMIX);

    snprintf(name, sizeof(name), "%s.norm", prefix);
    if (!load_bn(wf, name, LANE_C, &blk->norm)) return 0;

    uint32_t sh_pw1[4] = { LANE_EXP, LANE_C, 1, 1 };
    snprintf(name, sizeof(name), "%s.pw1.weight", prefix);
    blk->pw1_w = vtwt_read_f32(wf, name, 4, sh_pw1);

    uint32_t sh_exp[1] = { LANE_EXP };
    snprintf(name, sizeof(name), "%s.pw1.bias", prefix);
    blk->pw1_b = vtwt_read_f32(wf, name, 1, sh_exp);

    uint32_t sh_pw2[4] = { LANE_C, LANE_EXP, 1, 1 };
    snprintf(name, sizeof(name), "%s.pw2.weight", prefix);
    blk->pw2_w = vtwt_read_f32(wf, name, 4, sh_pw2);

    snprintf(name, sizeof(name), "%s.pw2.bias", prefix);
    blk->pw2_b = vtwt_read_f32(wf, name, 1, sh_c);

    snprintf(name, sizeof(name), "%s.gamma", prefix);
    blk->gamma = vtwt_read_f32(wf, name, 1, sh_c);

    return blk->dw_w && blk->dw_b && blk->pmix && blk->pw1_w && blk->pw1_b &&
           blk->pw2_w && blk->pw2_b && blk->gamma;
}

static void free_lane_block(struct lane_block *blk) {
    free(blk->dw_w); free(blk->dw_b); free(blk->pmix);
    free_bn(&blk->norm);
    free(blk->pw1_w); free(blk->pw1_b);
    free(blk->pw2_w); free(blk->pw2_b);
    free(blk->gamma);
}

static int load_attn(const struct vtwt_file *wf, const char *prefix, int is_time, struct axial_attn *a) {
    char name[VTWT_NAME_MAX];
    a->is_time = is_time;
    uint32_t sh_c[1] = { LANE_C };
    uint32_t sh_qkv_w[2] = { 3 * LANE_C, LANE_C };
    uint32_t sh_qkv_b[1] = { 3 * LANE_C };
    uint32_t sh_out_w[2] = { LANE_C, LANE_C };

    snprintf(name, sizeof(name), "%s.ln.weight", prefix); a->ln_w = vtwt_read_f32(wf, name, 1, sh_c);
    snprintf(name, sizeof(name), "%s.ln.bias", prefix);   a->ln_b = vtwt_read_f32(wf, name, 1, sh_c);
    snprintf(name, sizeof(name), "%s.qkv.weight", prefix); a->qkv_w = vtwt_read_f32(wf, name, 2, sh_qkv_w);
    snprintf(name, sizeof(name), "%s.qkv.bias", prefix);   a->qkv_b = vtwt_read_f32(wf, name, 1, sh_qkv_b);
    snprintf(name, sizeof(name), "%s.out.weight", prefix); a->out_w = vtwt_read_f32(wf, name, 2, sh_out_w);
    snprintf(name, sizeof(name), "%s.out.bias", prefix);   a->out_b = vtwt_read_f32(wf, name, 1, sh_c);
    snprintf(name, sizeof(name), "%s.gamma", prefix);      a->gamma = vtwt_read_f32(wf, name, 1, sh_c);
    if (!is_time) {
        uint32_t sh_rb[2] = { LANE_ATTN_HEADS, 255 };
        snprintf(name, sizeof(name), "%s.rel_bias", prefix);
        a->rel_bias = vtwt_read_f32(wf, name, 2, sh_rb);
        if (!a->rel_bias) return 0;
    }
    return a->ln_w && a->ln_b && a->qkv_w && a->qkv_b && a->out_w && a->out_b && a->gamma;
}

static void free_attn(struct axial_attn *a) {
    free(a->ln_w); free(a->ln_b);
    free(a->qkv_w); free(a->qkv_b);
    free(a->out_w); free(a->out_b);
    free(a->gamma); free(a->rel_bias);
}

static int load_gru(const struct vtwt_file *wf, const char *prefix, struct lane_gru *g) {
    char name[VTWT_NAME_MAX];
    uint32_t sh_c[1] = { LANE_C };
    uint32_t sh_ih[2] = { 3 * LANE_GRU_H, LANE_C };
    uint32_t sh_hh[2] = { 3 * LANE_GRU_H, LANE_GRU_H };
    uint32_t sh_b[1] = { 3 * LANE_GRU_H };
    uint32_t sh_out[2] = { LANE_C, 2 * LANE_GRU_H };

    snprintf(name, sizeof(name), "%s.ln.weight", prefix); g->ln_w = vtwt_read_f32(wf, name, 1, sh_c);
    snprintf(name, sizeof(name), "%s.ln.bias", prefix);   g->ln_b = vtwt_read_f32(wf, name, 1, sh_c);
    snprintf(name, sizeof(name), "%s.gru.weight_ih_l0", prefix); g->w_ih_f = vtwt_read_f32(wf, name, 2, sh_ih);
    snprintf(name, sizeof(name), "%s.gru.bias_ih_l0", prefix);   g->b_ih_f = vtwt_read_f32(wf, name, 1, sh_b);
    snprintf(name, sizeof(name), "%s.gru.weight_hh_l0", prefix); g->w_hh_f = vtwt_read_f32(wf, name, 2, sh_hh);
    snprintf(name, sizeof(name), "%s.gru.bias_hh_l0", prefix);   g->b_hh_f = vtwt_read_f32(wf, name, 1, sh_b);
    snprintf(name, sizeof(name), "%s.gru.weight_ih_l0_reverse", prefix); g->w_ih_r = vtwt_read_f32(wf, name, 2, sh_ih);
    snprintf(name, sizeof(name), "%s.gru.bias_ih_l0_reverse", prefix);   g->b_ih_r = vtwt_read_f32(wf, name, 1, sh_b);
    snprintf(name, sizeof(name), "%s.gru.weight_hh_l0_reverse", prefix); g->w_hh_r = vtwt_read_f32(wf, name, 2, sh_hh);
    snprintf(name, sizeof(name), "%s.gru.bias_hh_l0_reverse", prefix);   g->b_hh_r = vtwt_read_f32(wf, name, 1, sh_b);
    snprintf(name, sizeof(name), "%s.out.weight", prefix); g->out_w = vtwt_read_f32(wf, name, 2, sh_out);
    snprintf(name, sizeof(name), "%s.out.bias", prefix);   g->out_b = vtwt_read_f32(wf, name, 1, sh_c);

    return g->ln_w && g->ln_b && g->w_ih_f && g->b_ih_f && g->w_hh_f && g->b_hh_f &&
           g->w_ih_r && g->b_ih_r && g->w_hh_r && g->b_hh_r && g->out_w && g->out_b;
}

static void free_gru(struct lane_gru *g) {
    free(g->ln_w); free(g->ln_b);
    free(g->w_ih_f); free(g->b_ih_f); free(g->w_hh_f); free(g->b_hh_f);
    free(g->w_ih_r); free(g->b_ih_r); free(g->w_hh_r); free(g->b_hh_r);
    free(g->out_w); free(g->out_b);
}

struct lanenet *lanenet_load(const struct vtwt_file *wf) {
    struct lanenet *net = (struct lanenet *)calloc(1, sizeof(*net));
    if (!net) return NULL;

    uint32_t sh_mid[1] = { LANE_MID };
    uint32_t sh_c[1] = { LANE_C };
    uint32_t sh_down[4] = { LANE_C, 1, 3, 1 };
    uint32_t sh_hw[4] = { LANE_HEADS, LANE_C, 1, 1 };
    uint32_t sh_hb[1] = { LANE_HEADS };

    if (!load_bn(wf, "stem.inorm", HCQT_CHANNELS, &net->inorm)) goto fail;
    net->c1_w = vtwt_read_conv2d_nhwc(wf, "stem.c1.weight", LANE_MID, HCQT_CHANNELS, 3, 3);
    net->c1_b = vtwt_read_f32(wf, "stem.c1.bias", 1, sh_mid);
    if (!net->c1_w || !net->c1_b || !load_bn(wf, "stem.n1", LANE_MID, &net->n1)) goto fail;

    net->c2_w = vtwt_read_conv2d_nhwc(wf, "stem.c2.weight", LANE_MID, LANE_MID, 3, 3);
    net->c2_b = vtwt_read_f32(wf, "stem.c2.bias", 1, sh_mid);
    if (!net->c2_w || !net->c2_b || !load_bn(wf, "stem.n2", LANE_MID, &net->n2)) goto fail;

    net->sdown_w = vtwt_read_conv2d_nhwc(wf, "stem.down.weight", LANE_C, LANE_MID, 3, 3);
    net->sdown_b = vtwt_read_f32(wf, "stem.down.bias", 1, sh_c);
    if (!net->sdown_w || !net->sdown_b || !load_bn(wf, "stem.n3", LANE_C, &net->n3)) goto fail;

    net->down_w = transpose_2d(vtwt_read_f32(wf, "down.weight", 4, sh_down), LANE_C, 3);
    net->down_b = vtwt_read_f32(wf, "down.bias", 1, sh_c);
    if (!net->down_w || !net->down_b) goto fail;

    int layer_idx = 0;
    int stage = 0;
    for (int i = 0; i < LANE_DEPTH; ++i) {
        char prefix[32];
        snprintf(prefix, sizeof(prefix), "layers.%d", layer_idx++);
        if (!load_lane_block(wf, prefix, BLOCK_DILATIONS[i % 4], &net->blocks[i])) goto fail;
        if ((i + 1) == 5 || (i + 1) == 10 || (i + 1) == 15) {
            snprintf(prefix, sizeof(prefix), "layers.%d", layer_idx++);
            if (!load_attn(wf, prefix, 0, &net->attn_p[stage])) goto fail;
            snprintf(prefix, sizeof(prefix), "layers.%d", layer_idx++);
            if (!load_attn(wf, prefix, 1, &net->attn_t[stage])) goto fail;
            snprintf(prefix, sizeof(prefix), "layers.%d", layer_idx++);
            if (!load_gru(wf, prefix, &net->grus[stage])) goto fail;
            stage++;
        }
    }

    if (!load_bn(wf, "up_norm", LANE_C, &net->up_norm)) goto fail;
    for (int i = 0; i < LANE_REFINE; ++i) {
        char prefix[32];
        snprintf(prefix, sizeof(prefix), "refine.%d", i);
        if (!load_lane_block(wf, prefix, 1, &net->refine[i])) goto fail;
    }

    net->head_w = vtwt_read_f32(wf, "head.weight", 4, sh_hw);
    net->head_b = vtwt_read_f32(wf, "head.bias", 1, sh_hb);
    if (!net->head_w || !net->head_b) goto fail;

    return net;
fail:
    lanenet_free(net);
    return NULL;
}

void lanenet_free(struct lanenet *net) {
    if (!net) return;
    free_bn(&net->inorm);
    free(net->c1_w); free(net->c1_b); free_bn(&net->n1);
    free(net->c2_w); free(net->c2_b); free_bn(&net->n2);
    free(net->sdown_w); free(net->sdown_b); free_bn(&net->n3);
    free(net->down_w); free(net->down_b);
    for (int i = 0; i < LANE_DEPTH; ++i) free_lane_block(&net->blocks[i]);
    for (int i = 0; i < 3; ++i) {
        free_attn(&net->attn_p[i]);
        free_attn(&net->attn_t[i]);
        free_gru(&net->grus[i]);
    }
    free_bn(&net->up_norm);
    for (int i = 0; i < LANE_REFINE; ++i) free_lane_block(&net->refine[i]);
    free(net->head_w); free(net->head_b);
    free(net);
}

/* =========================================================================
 * Forward-pass layer kernels
 * ========================================================================= */

/* Depthwise 3x1 stride-(2,1) padding-(1,0) along T on [T, P, C] -> [T2, P, C]. */
struct down_ctx {
    const float *x, *w, *b;
    float *y;
    int T, T2, P;
};
static void down_worker(int start, int end, void *arg) {
    struct down_ctx *c = (struct down_ctx *)arg;
    const float *w0 = c->w + 0 * LANE_C;
    const float *w1 = c->w + 1 * LANE_C;
    const float *w2 = c->w + 2 * LANE_C;
    const float *b = c->b;
    for (int ot = start; ot < end; ++ot) {
        int it0 = ot * 2 - 1;
        int it1 = ot * 2;
        int it2 = ot * 2 + 1;
        for (int p = 0; p < c->P; ++p) {
            float *dst = c->y + ((size_t)ot * c->P + p) * LANE_C;
            memcpy(dst, b, LANE_C * sizeof(float));
            if (it0 >= 0 && it0 < c->T) {
                const float *src = c->x + ((size_t)it0 * c->P + p) * LANE_C;
                for (int ch = 0; ch < LANE_C; ++ch) dst[ch] += src[ch] * w0[ch];
            }
            if (it1 >= 0 && it1 < c->T) {
                const float *src = c->x + ((size_t)it1 * c->P + p) * LANE_C;
                for (int ch = 0; ch < LANE_C; ++ch) dst[ch] += src[ch] * w1[ch];
            }
            if (it2 >= 0 && it2 < c->T) {
                const float *src = c->x + ((size_t)it2 * c->P + p) * LANE_C;
                for (int ch = 0; ch < LANE_C; ++ch) dst[ch] += src[ch] * w2[ch];
            }
        }
    }
}

/* LaneBlock step 1: depthwise 7x1 dilated conv along T. */
struct dwt_ctx {
    const float *x, *w, *b;
    float *y;
    int T, P, dt;
};
static void dwt_worker(int start, int end, void *arg) {
    struct dwt_ctx *c = (struct dwt_ctx *)arg;
    for (int t = start; t < end; ++t) {
        for (int p = 0; p < c->P; ++p) {
            float *dst = c->y + ((size_t)t * c->P + p) * LANE_C;
            memcpy(dst, c->b, LANE_C * sizeof(float));
            for (int k = 0; k < 7; ++k) {
                int st = t + (k - 3) * c->dt;
                if (st < 0 || st >= c->T) continue;
                const float *src = c->x + ((size_t)st * c->P + p) * LANE_C;
                const float *wk = c->w + k * LANE_C;
                for (int ch = 0; ch < LANE_C; ++ch) dst[ch] += src[ch] * wk[ch];
            }
        }
    }
}

/* LaneBlock step 2: y + pmix(y) + folded BatchNorm -> z. */
struct pmix_bn_ctx {
    const float *y, *taps, *bn_scale, *bn_shift;
    float *z;
    int T, P;
};
static void pmix_bn_worker(int start, int end, void *arg) {
    struct pmix_bn_ctx *c = (struct pmix_bn_ctx *)arg;
    const float *sc = c->bn_scale, *sh = c->bn_shift;
    for (int t = start; t < end; ++t) {
        const float *yt = c->y + (size_t)t * c->P * LANE_C;
        float *zt = c->z + (size_t)t * c->P * LANE_C;
        for (int p = 0; p < c->P; ++p) {
            float *dst = zt + (size_t)p * LANE_C;
            memcpy(dst, yt + (size_t)p * LANE_C, LANE_C * sizeof(float));
            for (int k = 0; k < LANE_PMIX; ++k) {
                int j = p + PMIX_OFFSETS[k];
                if (j < 0 || j >= c->P) continue;
                const float *src = yt + (size_t)j * LANE_C;
                const float *tk = c->taps + k * LANE_C;
                for (int ch = 0; ch < LANE_C; ++ch) dst[ch] += src[ch] * tk[ch];
            }
            for (int ch = 0; ch < LANE_C; ++ch) dst[ch] = dst[ch] * sc[ch] + sh[ch];
        }
    }
}

/* Residual add: x[i, c] += z[i, c] * gamma[c]. */
struct res_ctx {
    float *x;
    const float *z, *gamma;
    int N;
};
static void res_worker(int start, int end, void *arg) {
    struct res_ctx *c = (struct res_ctx *)arg;
    const float *g = c->gamma;
    for (int i = start; i < end; ++i) {
        float *xi = c->x + (size_t)i * LANE_C;
        const float *zi = c->z + (size_t)i * LANE_C;
        for (int ch = 0; ch < LANE_C; ++ch) xi[ch] += zi[ch] * g[ch];
    }
}

static void run_lane_block(const struct lane_block *blk, float *x, int T, int P,
                           float *buf_y, float *buf_z, float *buf_mid) {
    struct dwt_ctx dc = { x, blk->dw_w, blk->dw_b, buf_y, T, P, blk->dt };
    nn_parallel_for(T, 4, dwt_worker, &dc);

    struct pmix_bn_ctx pc = { buf_y, blk->pmix, blk->norm.scale, blk->norm.shift, buf_z, T, P };
    nn_parallel_for(T, 4, pmix_bn_worker, &pc);

    int M = T * P;
    nn_sgemm_nt(M, LANE_EXP, LANE_C, buf_z, LANE_C, blk->pw1_w, LANE_C, buf_mid, LANE_EXP, blk->pw1_b, 0);
    nn_gelu_inplace(buf_mid, (size_t)M * LANE_EXP);
    nn_sgemm_nt(M, LANE_C, LANE_EXP, buf_mid, LANE_EXP, blk->pw2_w, LANE_EXP, buf_z, LANE_C, blk->pw2_b, 0);

    struct res_ctx rc = { x, buf_z, blk->gamma, M };
    nn_parallel_for(M, 64, res_worker, &rc);
}

/* Axial attention core: qkv is [N, L, 3*C], writes attn out [N, L, C]. */
struct attn_ctx {
    const float *qkv;
    float *out;
    const float *rel_bias; /* [8, 255] if pitch, NULL if time */
    const float *rope_cos; /* [L, 23] if time */
    const float *rope_sin; /* [L, 23] if time */
    int N, L, is_time;
};

static void apply_rope_vec(const float *in, float *out, const float *c, const float *s) {
    const int half = LANE_ATTN_DIM / 2;
    for (int d = 0; d < half; ++d) {
        float x1 = in[d], x2 = in[d + half];
        out[d]        = x1 * c[d] - x2 * s[d];
        out[d + half] = x1 * s[d] + x2 * c[d];
    }
}

static void attn_worker(int start, int end, void *arg) {
    struct attn_ctx *ctx = (struct attn_ctx *)arg;
    const int L = ctx->L;
    const int H = LANE_ATTN_HEADS;
    const int D = LANE_ATTN_DIM;
    const int C = LANE_C;
    const float scale = 1.0f / sqrtf((float)D);

    /* Stack/local buffers per thread: L <= 256 in practice, allocate dynamically if larger. */
    float *scores = (float *)malloc((size_t)L * sizeof(float));
    float *qr = ctx->is_time ? (float *)malloc((size_t)L * D * sizeof(float)) : NULL;
    float *kr = ctx->is_time ? (float *)malloc((size_t)L * D * sizeof(float)) : NULL;
    if (!scores || (ctx->is_time && (!qr || !kr))) {
        free(scores); free(qr); free(kr);
        return;
    }

    for (int n = start; n < end; ++n) {
        const float *qkv_n = ctx->qkv + (size_t)n * L * 3 * C;
        float *out_n = ctx->out + (size_t)n * L * C;
        for (int h = 0; h < H; ++h) {
            const float *rb = ctx->rel_bias ? (ctx->rel_bias + h * 255) : NULL;
            if (ctx->is_time) {
                for (int i = 0; i < L; ++i) {
                    const float *qi = qkv_n + (size_t)i * 3 * C + 0 * C + h * D;
                    const float *ki = qkv_n + (size_t)i * 3 * C + 1 * C + h * D;
                    const float *rc = ctx->rope_cos + (size_t)i * (D / 2);
                    const float *rs = ctx->rope_sin + (size_t)i * (D / 2);
                    apply_rope_vec(qi, qr + (size_t)i * D, rc, rs);
                    apply_rope_vec(ki, kr + (size_t)i * D, rc, rs);
                }
            }
            for (int qi = 0; qi < L; ++qi) {
                const float *qv = ctx->is_time
                    ? (qr + (size_t)qi * D)
                    : (qkv_n + (size_t)qi * 3 * C + 0 * C + h * D);
                float max_s = -1e30f;
                for (int ki = 0; ki < L; ++ki) {
                    const float *kv = ctx->is_time
                        ? (kr + (size_t)ki * D)
                        : (qkv_n + (size_t)ki * 3 * C + 1 * C + h * D);
                    float dot = 0.0f;
                    for (int d = 0; d < D; ++d) dot += qv[d] * kv[d];
                    float s = dot * scale;
                    if (rb) s += rb[ki - qi + 127];
                    scores[ki] = s;
                    if (s > max_s) max_s = s;
                }
                float sum_e = 0.0f;
                for (int ki = 0; ki < L; ++ki) {
                    float e = expf(scores[ki] - max_s);
                    scores[ki] = e;
                    sum_e += e;
                }
                float inv_sum = 1.0f / sum_e;
                float *dst = out_n + (size_t)qi * C + h * D;
                memset(dst, 0, (size_t)D * sizeof(float));
                for (int ki = 0; ki < L; ++ki) {
                    float w = scores[ki] * inv_sum;
                    const float *vv = qkv_n + (size_t)ki * 3 * C + 2 * C + h * D;
                    for (int d = 0; d < D; ++d) dst[d] += w * vv[d];
                }
            }
        }
    }
    free(scores);
    free(qr);
    free(kr);
}

static int run_axial_attn(const struct axial_attn *a, float *x, int T, int P,
                          float *buf_s, float *buf_h, float *buf_qkv) {
    int M = T * P;
    int N, L;
    const float *in_seq;
    if (!a->is_time) {
        N = T; L = P;
        in_seq = x;
    } else {
        N = P; L = T;
        /* Permute (T, P, C) -> (P, T, C) */
        for (int t = 0; t < T; ++t)
            for (int p = 0; p < P; ++p)
                memcpy(buf_s + ((size_t)p * T + t) * LANE_C,
                       x + ((size_t)t * P + p) * LANE_C,
                       LANE_C * sizeof(float));
        in_seq = buf_s;
    }

    nn_layernorm(in_seq, buf_h, M, LANE_C, a->ln_w, a->ln_b, 1e-5f);
    nn_sgemm_nt(M, 3 * LANE_C, LANE_C, buf_h, LANE_C, a->qkv_w, LANE_C, buf_qkv, 3 * LANE_C, a->qkv_b, 0);

    float *rope_cos = NULL, *rope_sin = NULL;
    if (a->is_time) {
        int half = LANE_ATTN_DIM / 2;
        rope_cos = (float *)malloc((size_t)L * half * sizeof(float));
        rope_sin = (float *)malloc((size_t)L * half * sizeof(float));
        if (!rope_cos || !rope_sin) { free(rope_cos); free(rope_sin); return 0; }
        for (int d = 0; d < half; ++d) {
            double freq = 1.0 / pow(10000.0, (double)d / (double)half);
            for (int t = 0; t < L; ++t) {
                double ang = (double)t * freq;
                rope_cos[(size_t)t * half + d] = (float)cos(ang);
                rope_sin[(size_t)t * half + d] = (float)sin(ang);
            }
        }
    }

    /* Reuse buf_h for attention output [N, L, C]. */
    struct attn_ctx ac = { buf_qkv, buf_h, a->rel_bias, rope_cos, rope_sin, N, L, a->is_time };
    nn_parallel_for(N, 2, attn_worker, &ac);
    free(rope_cos);
    free(rope_sin);

    /* Output projection into buf_s [N, L, C]. */
    nn_sgemm_nt(M, LANE_C, LANE_C, buf_h, LANE_C, a->out_w, LANE_C, buf_s, LANE_C, a->out_b, 0);

    if (!a->is_time) {
        struct res_ctx rc = { x, buf_s, a->gamma, M };
        nn_parallel_for(M, 64, res_worker, &rc);
    } else {
        const float *g = a->gamma;
        for (int t = 0; t < T; ++t) {
            for (int p = 0; p < P; ++p) {
                float *dst = x + ((size_t)t * P + p) * LANE_C;
                const float *src = buf_s + ((size_t)p * T + t) * LANE_C;
                for (int ch = 0; ch < LANE_C; ++ch) dst[ch] += src[ch] * g[ch];
            }
        }
    }
    return 1;
}

static inline float fast_sigmoid(float x) {
    return 1.0f / (1.0f + expf(-x));
}

/* Bidirectional LaneGRU directly on (T, P, C) with zero transpose! */
static int run_lane_gru(const struct lane_gru *g, float *x, int T, int P,
                        float *buf_ln, float *buf_ih, float *buf_hbi) {
    const int H = LANE_GRU_H;
    const int H3 = 3 * H;
    int M = T * P;
    nn_layernorm(x, buf_ln, M, LANE_C, g->ln_w, g->ln_b, 1e-5f);

    float *h_prev = (float *)calloc((size_t)P * H, sizeof(float));
    float *hh = (float *)malloc((size_t)P * H3 * sizeof(float));
    if (!h_prev || !hh) { free(h_prev); free(hh); return 0; }

    /* Forward direction */
    nn_sgemm_nt(M, H3, LANE_C, buf_ln, LANE_C, g->w_ih_f, LANE_C, buf_ih, H3, g->b_ih_f, 0);
    for (int t = 0; t < T; ++t) {
        if (t == 0) {
            for (int p = 0; p < P; ++p)
                memcpy(hh + (size_t)p * H3, g->b_hh_f, (size_t)H3 * sizeof(float));
        } else {
            nn_sgemm_nt(P, H3, H, h_prev, H, g->w_hh_f, H, hh, H3, g->b_hh_f, 0);
        }
        const float *ih_t = buf_ih + (size_t)t * P * H3;
        float *out_t = buf_hbi + (size_t)t * P * (2 * H);
        for (int p = 0; p < P; ++p) {
            const float *ip = ih_t + (size_t)p * H3;
            const float *hp = hh + (size_t)p * H3;
            float *prev_p = h_prev + (size_t)p * H;
            float *dst_p = out_t + (size_t)p * (2 * H);
            for (int j = 0; j < H; ++j) {
                float r = fast_sigmoid(ip[j] + hp[j]);
                float z = fast_sigmoid(ip[H + j] + hp[H + j]);
                float n = tanhf(ip[2 * H + j] + r * hp[2 * H + j]);
                float hnew = (1.0f - z) * n + z * prev_p[j];
                prev_p[j] = hnew;
                dst_p[j] = hnew;
            }
        }
    }

    /* Reverse direction */
    memset(h_prev, 0, (size_t)P * H * sizeof(float));
    nn_sgemm_nt(M, H3, LANE_C, buf_ln, LANE_C, g->w_ih_r, LANE_C, buf_ih, H3, g->b_ih_r, 0);
    for (int t = T - 1; t >= 0; --t) {
        if (t == T - 1) {
            for (int p = 0; p < P; ++p)
                memcpy(hh + (size_t)p * H3, g->b_hh_r, (size_t)H3 * sizeof(float));
        } else {
            nn_sgemm_nt(P, H3, H, h_prev, H, g->w_hh_r, H, hh, H3, g->b_hh_r, 0);
        }
        const float *ih_t = buf_ih + (size_t)t * P * H3;
        float *out_t = buf_hbi + (size_t)t * P * (2 * H);
        for (int p = 0; p < P; ++p) {
            const float *ip = ih_t + (size_t)p * H3;
            const float *hp = hh + (size_t)p * H3;
            float *prev_p = h_prev + (size_t)p * H;
            float *dst_p = out_t + (size_t)p * (2 * H) + H;
            for (int j = 0; j < H; ++j) {
                float r = fast_sigmoid(ip[j] + hp[j]);
                float z = fast_sigmoid(ip[H + j] + hp[H + j]);
                float n = tanhf(ip[2 * H + j] + r * hp[2 * H + j]);
                float hnew = (1.0f - z) * n + z * prev_p[j];
                prev_p[j] = hnew;
                dst_p[j] = hnew;
            }
        }
    }

    free(h_prev);
    free(hh);

    /* Output projection + residual directly into x */
    nn_sgemm_nt(M, LANE_C, 2 * H, buf_hbi, 2 * H, g->out_w, 2 * H, x, LANE_C, g->out_b, 1);
    return 1;
}

/* =========================================================================
 * Full LaneNet forward pass
 * ========================================================================= */

int lanenet_forward(const struct lanenet *net, const float *audio_16k, int samples,
                    float *logits_out, float *tap_stem_out, float *tap_hidden_out) {
    if (!net || !audio_16k || !logits_out || samples < HCQT_HOP) return 0;
    int T10 = samples / HCQT_HOP;
    int T = (T10 + 1) / 2;       /* stride 2, padding 1, kernel 3 */
    int T2 = (T + 1) / 2;        /* stride 2, padding 1, kernel 3 */
    const int F_STEM = 96;       /* (288 + 2 - 3)/3 + 1 */
    const int P = LANE_KEYS;     /* 88 */

    float *hcqt = (float *)malloc((size_t)T10 * HCQT_BINS * HCQT_CHANNELS * sizeof(float));
    float *s1 = (float *)malloc((size_t)T10 * HCQT_BINS * LANE_MID * sizeof(float));
    float *s2 = (float *)malloc((size_t)T10 * HCQT_BINS * LANE_MID * sizeof(float));
    float *stem_full = (float *)malloc((size_t)T * F_STEM * LANE_C * sizeof(float));
    float *skip = (float *)malloc((size_t)T * P * LANE_C * sizeof(float));
    float *h = NULL, *buf_a = NULL, *buf_b = NULL, *buf_big = NULL;

    if (!hcqt || !s1 || !s2 || !stem_full || !skip) goto fail;

    /* 1. HCQT frontend */
    compute_hcqt_nhwc(audio_16k, samples, hcqt);

    /* 2. Stem */
    nn_affine_channel(hcqt, hcqt, T10 * HCQT_BINS, HCQT_CHANNELS, net->inorm.scale, net->inorm.shift);
    if (!nn_conv2d_nhwc(hcqt, T10, HCQT_BINS, HCQT_CHANNELS, net->c1_w, net->c1_b,
                        LANE_MID, 3, 3, 1, 1, 1, 1, s1)) goto fail;
    free(hcqt); hcqt = NULL;
    nn_affine_channel(s1, s1, T10 * HCQT_BINS, LANE_MID, net->n1.scale, net->n1.shift);
    nn_gelu_inplace(s1, (size_t)T10 * HCQT_BINS * LANE_MID);

    if (!nn_conv2d_nhwc(s1, T10, HCQT_BINS, LANE_MID, net->c2_w, net->c2_b,
                        LANE_MID, 3, 3, 1, 1, 1, 1, s2)) goto fail;
    free(s1); s1 = NULL;
    nn_affine_channel(s2, s2, T10 * HCQT_BINS, LANE_MID, net->n2.scale, net->n2.shift);
    nn_gelu_inplace(s2, (size_t)T10 * HCQT_BINS * LANE_MID);

    if (!nn_conv2d_nhwc(s2, T10, HCQT_BINS, LANE_MID, net->sdown_w, net->sdown_b,
                        LANE_C, 3, 3, 2, 3, 1, 1, stem_full)) goto fail;
    free(s2); s2 = NULL;
    nn_affine_channel(stem_full, stem_full, T * F_STEM, LANE_C, net->n3.scale, net->n3.shift);

    /* Slice lanes 0..87 into skip (and tap_stem_out if requested) */
    for (int t = 0; t < T; ++t) {
        memcpy(skip + (size_t)t * P * LANE_C,
               stem_full + (size_t)t * F_STEM * LANE_C,
               (size_t)P * LANE_C * sizeof(float));
    }
    free(stem_full); stem_full = NULL;
    if (tap_stem_out) memcpy(tap_stem_out, skip, (size_t)T * P * LANE_C * sizeof(float));

    /* 3. Allocate backbone scratch (sized for max of T2*P*3C and T*P*2C) */
    size_t n_full = (size_t)T * P;
    size_t n_down = (size_t)T2 * P;
    size_t big_floats = n_down * (3 * LANE_C);
    if (n_full * LANE_EXP > big_floats) big_floats = n_full * LANE_EXP;
    size_t ab_floats = n_full * LANE_C;
    if (n_down * (2 * LANE_GRU_H) > ab_floats) ab_floats = n_down * (2 * LANE_GRU_H);

    h = (float *)malloc(n_down * LANE_C * sizeof(float));
    buf_a = (float *)malloc(ab_floats * sizeof(float));
    buf_b = (float *)malloc(ab_floats * sizeof(float));
    buf_big = (float *)malloc(big_floats * sizeof(float));
    if (!h || !buf_a || !buf_b || !buf_big) goto fail;

    /* 4. Downsample depthwise conv: skip [T, P, C] -> h [T2, P, C] */
    struct down_ctx dctx = { skip, net->down_w, net->down_b, h, T, T2, P };
    nn_parallel_for(T2, 4, down_worker, &dctx);

    /* 5. Backbone layers (15 LaneBlocks + 3x pitch attn, time attn, GRU) */
    int stage = 0;
    for (int i = 0; i < LANE_DEPTH; ++i) {
        run_lane_block(&net->blocks[i], h, T2, P, buf_a, buf_b, buf_big);
        if ((i + 1) == 5 || (i + 1) == 10 || (i + 1) == 15) {
            if (!run_axial_attn(&net->attn_p[stage], h, T2, P, buf_a, buf_b, buf_big)) goto fail;
            if (!run_axial_attn(&net->attn_t[stage], h, T2, P, buf_a, buf_b, buf_big)) goto fail;
            if (!run_lane_gru(&net->grus[stage], h, T2, P, buf_a, buf_big, buf_b)) goto fail;
            stage++;
        }
    }

    /* 6. Repeat-interleave upsample + skip + up_norm -> overwrite skip in-place */
    for (int t = 0; t < T; ++t) {
        const float *hs = h + (size_t)(t / 2) * P * LANE_C;
        float *dst = skip + (size_t)t * P * LANE_C;
        size_t len = (size_t)P * LANE_C;
        for (size_t k = 0; k < len; ++k) dst[k] += hs[k];
    }
    free(h); h = NULL;
    nn_affine_channel(skip, skip, T * P, LANE_C, net->up_norm.scale, net->up_norm.shift);

    /* 7. Refine blocks at full 20 ms resolution */
    for (int i = 0; i < LANE_REFINE; ++i)
        run_lane_block(&net->refine[i], skip, T, P, buf_a, buf_b, buf_big);

    if (tap_hidden_out) memcpy(tap_hidden_out, skip, (size_t)T * P * LANE_C * sizeof(float));

    /* 8. Head 1x1 conv: [T*P, 368] -> [T*P, 6] */
    nn_sgemm_nt(T * P, LANE_HEADS, LANE_C, skip, LANE_C, net->head_w, LANE_C,
                logits_out, LANE_HEADS, net->head_b, 0);

    free(skip);
    free(buf_a);
    free(buf_b);
    free(buf_big);
    return T;

fail:
    free(hcqt); free(s1); free(s2); free(stem_full); free(skip);
    free(h); free(buf_a); free(buf_b); free(buf_big);
    return 0;
}
