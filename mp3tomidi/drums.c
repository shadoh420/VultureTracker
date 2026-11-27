/* Native port of Dettato's drums/{features,model,infer}.py,
 * revision 51ade0f09f2272f4674166026582185d26baaeaf. See vendor/dettato/. */
#include "drums.h"
#include "nn.h"
#include "resample.h"
#include "transcribe.h"
#include <float.h>
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

enum {
    DR_SR = 44100,
    DR_N_LO = 128,
    DR_N_HI = 32,
    DR_N_MEL = 160,
    DR_N_CQ = 120,
    DR_N_BANDS = 280,
    DR_KEYS = 61,      /* GM drum keys 27..87 */
    DR_TIMP = 13,      /* timpani keys 41..53 */
    DR_W = 88,
    DR_COLLAPSE_M = 22,
    DR_TOWER_H = 18,
    DR_N_TOWERS = 5,
    DR_N_EXPERTS = 3
};

static const double DR_TAU = 6.2831853071795864769;
static const double DR_PI = 3.14159265358979323846;

/* Tower key indices into KEYS (27..87), exact order from dettato-drums/config.json. */
static const int TOWER_LENS[DR_N_TOWERS] = { 2, 4, 6, 10, 4 };
static const int TOWER_KEYS[DR_N_TOWERS][10] = {
    { 35 - 27, 36 - 27 },
    { 37 - 27, 38 - 27, 39 - 27, 40 - 27 },
    { 42 - 27, 44 - 27, 46 - 27, 51 - 27, 53 - 27, 59 - 27 },
    { 41 - 27, 43 - 27, 45 - 27, 47 - 27, 48 - 27, 50 - 27, 49 - 27, 52 - 27, 55 - 27, 57 - 27 },
    { 54 - 27, 69 - 27, 70 - 27, 82 - 27 }
};

/* =========================================================================
 * Model structures
 * ========================================================================= */

struct dr_bn {
    float *scale, *shift;
};

struct dr_res2d {
    int c;
    float *dw_w, *dw_b;  /* [9, c] transposed from [c, 1, 3, 3] */
    struct dr_bn bn1;
    float *pw_w, *pw_b;  /* [c, c], [c] */
    struct dr_bn bn2;
};

struct dr_bigru {
    int in_dim, hid;
    float *w_ih_f, *b_ih_f, *w_hh_f, *b_hh_f;
    float *w_ih_r, *b_ih_r, *w_hh_r, *b_hh_r;
};

struct drumnet {
    /* Stem: c16,r,r,p22,c32,r,r,r,p12,c56,r,r,r,p12,r,r,r */
    float *c0_w, *c0_b; struct dr_bn bn0;
    struct dr_res2d r0[2];
    float *c1_w, *c1_b; struct dr_bn bn1;
    struct dr_res2d r1[3];
    float *c2_w, *c2_b; struct dr_bn bn2;
    struct dr_res2d r2[3];
    struct dr_res2d r3[3];
    /* Collapse BandGRU */
    struct dr_bigru col_rnn;
    float *col_proj_w, *col_proj_b;
    /* Temporal: ConvBlock(88,k=15), GRUBlock(88,h=32), SongAttention(88,da=32,heads=2) */
    float *tb_dw_w, *tb_dw_b; struct dr_bn tb_bn; float *tb_pw_w, *tb_pw_b;
    float *gb_ln_w, *gb_ln_b; struct dr_bigru gb_rnn; float *gb_out_w, *gb_out_b;
    float *sa_ln_w, *sa_ln_b; float *sa_qkv_w, *sa_qkv_b; float *sa_o_w, *sa_o_b;
    /* Heads */
    struct dr_bigru towers[DR_N_TOWERS];
    float *thead_w[DR_N_TOWERS], *thead_b[DR_N_TOWERS];
    float *rest_w, *rest_b;
    float *vel0_w, *vel0_b, *vel1_w, *vel1_b;
};

struct orch_expert {
    struct drumnet base;
    /* CQBranch */
    float *cq_c1_w, *cq_c1_b, *cq_n1_w, *cq_n1_b;
    float *cq_c2_w, *cq_c2_b, *cq_n2_w, *cq_n2_b;
    float *cq_c3_w, *cq_c3_b, *cq_n3_w, *cq_n3_b;
    float *cq_proj_w, *cq_proj_b;
    /* Adapter */
    float *inp_w, *inp_b;
    struct dr_bigru rnn0, rnn1;
    float *qkv_w, *qkv_b, *ao_w, *ao_b, *ln_w, *ln_b;
    float *delta_w, *delta_b;
    float *timp_w, *timp_b;
    float *gate0_w, *gate0_b, *gate2_w, *gate2_b;
};

struct drums_model {
    struct drumnet kit;
    struct orch_expert experts[DR_N_EXPERTS];
};

/* =========================================================================
 * Weight loading / freeing
 * ========================================================================= */

static float *dr_transpose(float *src, int rows, int cols) {
    if (!src) return NULL;
    float *dst = (float *)malloc((size_t)rows * cols * sizeof(float));
    if (!dst) { free(src); return NULL; }
    for (int r = 0; r < rows; ++r)
        for (int c = 0; c < cols; ++c)
            dst[(size_t)c * rows + r] = src[(size_t)r * cols + c];
    free(src);
    return dst;
}

static int dr_load_bn(const struct vtwt_file *wf, const char *p, int c, struct dr_bn *bn) {
    char nm[256]; uint32_t s[1] = { (uint32_t)c };
    snprintf(nm, sizeof(nm), "%s.weight", p);       float *w = vtwt_read_f32(wf, nm, 1, s);
    snprintf(nm, sizeof(nm), "%s.bias", p);         float *b = vtwt_read_f32(wf, nm, 1, s);
    snprintf(nm, sizeof(nm), "%s.running_mean", p); float *m = vtwt_read_f32(wf, nm, 1, s);
    snprintf(nm, sizeof(nm), "%s.running_var", p);  float *v = vtwt_read_f32(wf, nm, 1, s);
    if (!w || !b || !m || !v) { free(w); free(b); free(m); free(v); return 0; }
    bn->scale = (float *)malloc((size_t)c * sizeof(float));
    bn->shift = (float *)malloc((size_t)c * sizeof(float));
    if (!bn->scale || !bn->shift) { free(w); free(b); free(m); free(v); return 0; }
    nn_bn_params(w, b, m, v, 1e-5f, c, bn->scale, bn->shift);
    free(w); free(b); free(m); free(v);
    return 1;
}

static void dr_free_bn(struct dr_bn *bn) { free(bn->scale); free(bn->shift); }

static int dr_load_res2d(const struct vtwt_file *wf, const char *p, int c, struct dr_res2d *r) {
    char nm[256];
    r->c = c;
    uint32_t sdw[4] = {(uint32_t)c, 1, 3, 3}, sc[1] = {(uint32_t)c}, spw[4] = {(uint32_t)c, (uint32_t)c, 1, 1};
    snprintf(nm, sizeof(nm), "%s.dw.weight", p);  r->dw_w = dr_transpose(vtwt_read_f32(wf, nm, 4, sdw), c, 9);
    snprintf(nm, sizeof(nm), "%s.dw.bias", p);    r->dw_b = vtwt_read_f32(wf, nm, 1, sc);
    snprintf(nm, sizeof(nm), "%s.bn1", p);        if (!dr_load_bn(wf, nm, c, &r->bn1)) return 0;
    snprintf(nm, sizeof(nm), "%s.pw1.weight", p); r->pw_w = vtwt_read_f32(wf, nm, 4, spw);
    snprintf(nm, sizeof(nm), "%s.pw1.bias", p);   r->pw_b = vtwt_read_f32(wf, nm, 1, sc);
    snprintf(nm, sizeof(nm), "%s.bn2", p);        if (!dr_load_bn(wf, nm, c, &r->bn2)) return 0;
    return r->dw_w && r->dw_b && r->pw_w && r->pw_b;
}

static void dr_free_res2d(struct dr_res2d *r) {
    free(r->dw_w); free(r->dw_b); dr_free_bn(&r->bn1);
    free(r->pw_w); free(r->pw_b); dr_free_bn(&r->bn2);
}

static int dr_load_bigru(const struct vtwt_file *wf, const char *p, int layer, int in_d, int hid, struct dr_bigru *g) {
    char nm[256];
    g->in_dim = in_d; g->hid = hid;
    uint32_t sih[2] = {(uint32_t)(3 * hid), (uint32_t)in_d};
    uint32_t shh[2] = {(uint32_t)(3 * hid), (uint32_t)hid};
    uint32_t sb[1] = {(uint32_t)(3 * hid)};
    snprintf(nm, sizeof(nm), "%s.weight_ih_l%d", p, layer);         g->w_ih_f = vtwt_read_f32(wf, nm, 2, sih);
    snprintf(nm, sizeof(nm), "%s.bias_ih_l%d", p, layer);           g->b_ih_f = vtwt_read_f32(wf, nm, 1, sb);
    snprintf(nm, sizeof(nm), "%s.weight_hh_l%d", p, layer);         g->w_hh_f = vtwt_read_f32(wf, nm, 2, shh);
    snprintf(nm, sizeof(nm), "%s.bias_hh_l%d", p, layer);           g->b_hh_f = vtwt_read_f32(wf, nm, 1, sb);
    snprintf(nm, sizeof(nm), "%s.weight_ih_l%d_reverse", p, layer); g->w_ih_r = vtwt_read_f32(wf, nm, 2, sih);
    snprintf(nm, sizeof(nm), "%s.bias_ih_l%d_reverse", p, layer);   g->b_ih_r = vtwt_read_f32(wf, nm, 1, sb);
    snprintf(nm, sizeof(nm), "%s.weight_hh_l%d_reverse", p, layer); g->w_hh_r = vtwt_read_f32(wf, nm, 2, shh);
    snprintf(nm, sizeof(nm), "%s.bias_hh_l%d_reverse", p, layer);   g->b_hh_r = vtwt_read_f32(wf, nm, 1, sb);
    return g->w_ih_f && g->b_ih_f && g->w_hh_f && g->b_hh_f &&
           g->w_ih_r && g->b_ih_r && g->w_hh_r && g->b_hh_r;
}

static void dr_free_bigru(struct dr_bigru *g) {
    free(g->w_ih_f); free(g->b_ih_f); free(g->w_hh_f); free(g->b_hh_f);
    free(g->w_ih_r); free(g->b_ih_r); free(g->w_hh_r); free(g->b_hh_r);
}

static int load_drumnet(const struct vtwt_file *wf, const char *p, struct drumnet *d) {
    char nm[256];
    uint32_t s16[1] = {16}, s32[1] = {32}, s56[1] = {56}, sw[1] = {DR_W}, s61[1] = {DR_KEYS};
    snprintf(nm, sizeof(nm), "%s.stem.net.0.weight", p); d->c0_w = vtwt_read_conv2d_nhwc(wf, nm, 16, 1, 3, 3);
    snprintf(nm, sizeof(nm), "%s.stem.net.0.bias", p);   d->c0_b = vtwt_read_f32(wf, nm, 1, s16);
    snprintf(nm, sizeof(nm), "%s.stem.net.1", p);        if (!dr_load_bn(wf, nm, 16, &d->bn0)) return 0;
    for (int i = 0; i < 2; ++i) { snprintf(nm, sizeof(nm), "%s.stem.net.%d", p, 3 + i); if (!dr_load_res2d(wf, nm, 16, &d->r0[i])) return 0; }

    snprintf(nm, sizeof(nm), "%s.stem.net.6.weight", p); d->c1_w = vtwt_read_conv2d_nhwc(wf, nm, 32, 16, 3, 3);
    snprintf(nm, sizeof(nm), "%s.stem.net.6.bias", p);   d->c1_b = vtwt_read_f32(wf, nm, 1, s32);
    snprintf(nm, sizeof(nm), "%s.stem.net.7", p);        if (!dr_load_bn(wf, nm, 32, &d->bn1)) return 0;
    for (int i = 0; i < 3; ++i) { snprintf(nm, sizeof(nm), "%s.stem.net.%d", p, 9 + i); if (!dr_load_res2d(wf, nm, 32, &d->r1[i])) return 0; }

    snprintf(nm, sizeof(nm), "%s.stem.net.13.weight", p); d->c2_w = vtwt_read_conv2d_nhwc(wf, nm, 56, 32, 3, 3);
    snprintf(nm, sizeof(nm), "%s.stem.net.13.bias", p);   d->c2_b = vtwt_read_f32(wf, nm, 1, s56);
    snprintf(nm, sizeof(nm), "%s.stem.net.14", p);        if (!dr_load_bn(wf, nm, 56, &d->bn2)) return 0;
    for (int i = 0; i < 3; ++i) { snprintf(nm, sizeof(nm), "%s.stem.net.%d", p, 16 + i); if (!dr_load_res2d(wf, nm, 56, &d->r2[i])) return 0; }
    for (int i = 0; i < 3; ++i) { snprintf(nm, sizeof(nm), "%s.stem.net.%d", p, 20 + i); if (!dr_load_res2d(wf, nm, 56, &d->r3[i])) return 0; }

    snprintf(nm, sizeof(nm), "%s.collapse.rnn", p);
    if (!dr_load_bigru(wf, nm, 0, 56, DR_COLLAPSE_M, &d->col_rnn)) return 0;
    uint32_t sww[2] = {DR_W, DR_W};
    snprintf(nm, sizeof(nm), "%s.collapse.proj.weight", p); d->col_proj_w = vtwt_read_f32(wf, nm, 2, sww);
    snprintf(nm, sizeof(nm), "%s.collapse.proj.bias", p);   d->col_proj_b = vtwt_read_f32(wf, nm, 1, sw);

    uint32_t sdw15[3] = {DR_W, 1, 15}, spw1[3] = {DR_W, DR_W, 1};
    snprintf(nm, sizeof(nm), "%s.temporal.0.dw.weight", p); d->tb_dw_w = dr_transpose(vtwt_read_f32(wf, nm, 3, sdw15), DR_W, 15);
    snprintf(nm, sizeof(nm), "%s.temporal.0.dw.bias", p);   d->tb_dw_b = vtwt_read_f32(wf, nm, 1, sw);
    snprintf(nm, sizeof(nm), "%s.temporal.0.bn", p);        if (!dr_load_bn(wf, nm, DR_W, &d->tb_bn)) return 0;
    snprintf(nm, sizeof(nm), "%s.temporal.0.pw.weight", p); d->tb_pw_w = vtwt_read_f32(wf, nm, 3, spw1);
    snprintf(nm, sizeof(nm), "%s.temporal.0.pw.bias", p);   d->tb_pw_b = vtwt_read_f32(wf, nm, 1, sw);

    uint32_t sgb_o[2] = {DR_W, 64};
    snprintf(nm, sizeof(nm), "%s.temporal.1.norm.weight", p); d->gb_ln_w = vtwt_read_f32(wf, nm, 1, sw);
    snprintf(nm, sizeof(nm), "%s.temporal.1.norm.bias", p);   d->gb_ln_b = vtwt_read_f32(wf, nm, 1, sw);
    snprintf(nm, sizeof(nm), "%s.temporal.1.rnn", p);         if (!dr_load_bigru(wf, nm, 0, DR_W, 32, &d->gb_rnn)) return 0;
    snprintf(nm, sizeof(nm), "%s.temporal.1.out.weight", p);  d->gb_out_w = vtwt_read_f32(wf, nm, 2, sgb_o);
    snprintf(nm, sizeof(nm), "%s.temporal.1.out.bias", p);    d->gb_out_b = vtwt_read_f32(wf, nm, 1, sw);

    uint32_t sqkv[2] = {96, DR_W}, sqb[1] = {96}, sao[2] = {DR_W, 32};
    snprintf(nm, sizeof(nm), "%s.temporal.2.n.weight", p);   d->sa_ln_w = vtwt_read_f32(wf, nm, 1, sw);
    snprintf(nm, sizeof(nm), "%s.temporal.2.n.bias", p);     d->sa_ln_b = vtwt_read_f32(wf, nm, 1, sw);
    snprintf(nm, sizeof(nm), "%s.temporal.2.qkv.weight", p); d->sa_qkv_w = vtwt_read_f32(wf, nm, 2, sqkv);
    snprintf(nm, sizeof(nm), "%s.temporal.2.qkv.bias", p);   d->sa_qkv_b = vtwt_read_f32(wf, nm, 1, sqb);
    snprintf(nm, sizeof(nm), "%s.temporal.2.o.weight", p);   d->sa_o_w = vtwt_read_f32(wf, nm, 2, sao);
    snprintf(nm, sizeof(nm), "%s.temporal.2.o.bias", p);     d->sa_o_b = vtwt_read_f32(wf, nm, 1, sw);

    for (int g = 0; g < DR_N_TOWERS; ++g) {
        snprintf(nm, sizeof(nm), "%s.on.towers.%d", p, g);
        if (!dr_load_bigru(wf, nm, 0, DR_W, DR_TOWER_H, &d->towers[g])) return 0;
        uint32_t shw[2] = {(uint32_t)TOWER_LENS[g], DR_W + 2 * DR_TOWER_H};
        uint32_t shb[1] = {(uint32_t)TOWER_LENS[g]};
        snprintf(nm, sizeof(nm), "%s.on.heads.%d.weight", p, g); d->thead_w[g] = vtwt_read_f32(wf, nm, 2, shw);
        snprintf(nm, sizeof(nm), "%s.on.heads.%d.bias", p, g);   d->thead_b[g] = vtwt_read_f32(wf, nm, 1, shb);
        if (!d->thead_w[g] || !d->thead_b[g]) return 0;
    }
    uint32_t srw[2] = {DR_KEYS, DR_W}, sv0w[2] = {16, DR_W}, sv1w[2] = {DR_KEYS, 16};
    snprintf(nm, sizeof(nm), "%s.on.rest.weight", p); d->rest_w = vtwt_read_f32(wf, nm, 2, srw);
    snprintf(nm, sizeof(nm), "%s.on.rest.bias", p);   d->rest_b = vtwt_read_f32(wf, nm, 1, s61);
    snprintf(nm, sizeof(nm), "%s.vel.0.weight", p);   d->vel0_w = vtwt_read_f32(wf, nm, 2, sv0w);
    snprintf(nm, sizeof(nm), "%s.vel.0.bias", p);     d->vel0_b = vtwt_read_f32(wf, nm, 1, s16);
    snprintf(nm, sizeof(nm), "%s.vel.1.weight", p);   d->vel1_w = vtwt_read_f32(wf, nm, 2, sv1w);
    snprintf(nm, sizeof(nm), "%s.vel.1.bias", p);     d->vel1_b = vtwt_read_f32(wf, nm, 1, s61);

    return d->c0_w && d->c0_b && d->c1_w && d->c1_b && d->c2_w && d->c2_b &&
           d->col_proj_w && d->col_proj_b && d->tb_dw_w && d->tb_dw_b && d->tb_pw_w && d->tb_pw_b &&
           d->gb_ln_w && d->gb_ln_b && d->gb_out_w && d->gb_out_b &&
           d->sa_ln_w && d->sa_ln_b && d->sa_qkv_w && d->sa_qkv_b && d->sa_o_w && d->sa_o_b &&
           d->rest_w && d->rest_b && d->vel0_w && d->vel0_b && d->vel1_w && d->vel1_b;
}

static void free_drumnet(struct drumnet *d) {
    free(d->c0_w); free(d->c0_b); dr_free_bn(&d->bn0);
    for (int i = 0; i < 2; ++i) dr_free_res2d(&d->r0[i]);
    free(d->c1_w); free(d->c1_b); dr_free_bn(&d->bn1);
    for (int i = 0; i < 3; ++i) dr_free_res2d(&d->r1[i]);
    free(d->c2_w); free(d->c2_b); dr_free_bn(&d->bn2);
    for (int i = 0; i < 3; ++i) { dr_free_res2d(&d->r2[i]); dr_free_res2d(&d->r3[i]); }
    dr_free_bigru(&d->col_rnn); free(d->col_proj_w); free(d->col_proj_b);
    free(d->tb_dw_w); free(d->tb_dw_b); dr_free_bn(&d->tb_bn); free(d->tb_pw_w); free(d->tb_pw_b);
    free(d->gb_ln_w); free(d->gb_ln_b); dr_free_bigru(&d->gb_rnn); free(d->gb_out_w); free(d->gb_out_b);
    free(d->sa_ln_w); free(d->sa_ln_b); free(d->sa_qkv_w); free(d->sa_qkv_b); free(d->sa_o_w); free(d->sa_o_b);
    for (int g = 0; g < DR_N_TOWERS; ++g) {
        dr_free_bigru(&d->towers[g]); free(d->thead_w[g]); free(d->thead_b[g]);
    }
    free(d->rest_w); free(d->rest_b);
    free(d->vel0_w); free(d->vel0_b); free(d->vel1_w); free(d->vel1_b);
}

static int load_expert(const struct vtwt_file *wf, int idx, struct orch_expert *e) {
    char p[32], nm[VTWT_NAME_MAX];
    snprintf(p, sizeof(p), "orchestral.%d.base", idx);
    if (!load_drumnet(wf, p, &e->base)) return 0;

    snprintf(p, sizeof(p), "orchestral.%d", idx);
    uint32_t s24[1] = {24}, s32[1] = {32}, s128[1] = {128}, s192[1] = {192}, s256[1] = {256};
    uint32_t s768[1] = {768}, s61[1] = {61}, s13[1] = {13}, s64[1] = {64}, s1[1] = {1};
    uint32_t spj[2] = {128, 3840}, sinp[2] = {192, 277}, sqkv[2] = {768, 256}, sao[2] = {256, 256};
    uint32_t sdel[2] = {61, 256}, stim[2] = {13, 256}, sg0[2] = {64, 256}, sg2[2] = {1, 64};

    snprintf(nm, sizeof(nm), "%s.cq.c1.weight", p); e->cq_c1_w = vtwt_read_conv2d_nhwc(wf, nm, 24, 3, 5, 7);
    snprintf(nm, sizeof(nm), "%s.cq.c1.bias", p);   e->cq_c1_b = vtwt_read_f32(wf, nm, 1, s24);
    snprintf(nm, sizeof(nm), "%s.cq.n1.weight", p); e->cq_n1_w = vtwt_read_f32(wf, nm, 1, s24);
    snprintf(nm, sizeof(nm), "%s.cq.n1.bias", p);   e->cq_n1_b = vtwt_read_f32(wf, nm, 1, s24);
    snprintf(nm, sizeof(nm), "%s.cq.c2.weight", p); e->cq_c2_w = vtwt_read_conv2d_nhwc(wf, nm, 32, 24, 3, 5);
    snprintf(nm, sizeof(nm), "%s.cq.c2.bias", p);   e->cq_c2_b = vtwt_read_f32(wf, nm, 1, s32);
    snprintf(nm, sizeof(nm), "%s.cq.n2.weight", p); e->cq_n2_w = vtwt_read_f32(wf, nm, 1, s32);
    snprintf(nm, sizeof(nm), "%s.cq.n2.bias", p);   e->cq_n2_b = vtwt_read_f32(wf, nm, 1, s32);
    snprintf(nm, sizeof(nm), "%s.cq.c3.weight", p); e->cq_c3_w = vtwt_read_conv2d_nhwc(wf, nm, 32, 32, 3, 5);
    snprintf(nm, sizeof(nm), "%s.cq.c3.bias", p);   e->cq_c3_b = vtwt_read_f32(wf, nm, 1, s32);
    snprintf(nm, sizeof(nm), "%s.cq.n3.weight", p); e->cq_n3_w = vtwt_read_f32(wf, nm, 1, s32);
    snprintf(nm, sizeof(nm), "%s.cq.n3.bias", p);   e->cq_n3_b = vtwt_read_f32(wf, nm, 1, s32);
    snprintf(nm, sizeof(nm), "%s.cq.proj.weight", p); e->cq_proj_w = vtwt_read_f32(wf, nm, 2, spj);
    snprintf(nm, sizeof(nm), "%s.cq.proj.bias", p);   e->cq_proj_b = vtwt_read_f32(wf, nm, 1, s128);

    snprintf(nm, sizeof(nm), "%s.inp.weight", p); e->inp_w = vtwt_read_f32(wf, nm, 2, sinp);
    snprintf(nm, sizeof(nm), "%s.inp.bias", p);   e->inp_b = vtwt_read_f32(wf, nm, 1, s192);
    snprintf(nm, sizeof(nm), "%s.rnn", p);
    if (!dr_load_bigru(wf, nm, 0, 192, 128, &e->rnn0) || !dr_load_bigru(wf, nm, 1, 256, 128, &e->rnn1)) return 0;
    snprintf(nm, sizeof(nm), "%s.qkv.weight", p); e->qkv_w = vtwt_read_f32(wf, nm, 2, sqkv);
    snprintf(nm, sizeof(nm), "%s.qkv.bias", p);   e->qkv_b = vtwt_read_f32(wf, nm, 1, s768);
    snprintf(nm, sizeof(nm), "%s.ao.weight", p);  e->ao_w = vtwt_read_f32(wf, nm, 2, sao);
    snprintf(nm, sizeof(nm), "%s.ao.bias", p);    e->ao_b = vtwt_read_f32(wf, nm, 1, s256);
    snprintf(nm, sizeof(nm), "%s.ln.weight", p);  e->ln_w = vtwt_read_f32(wf, nm, 1, s256);
    snprintf(nm, sizeof(nm), "%s.ln.bias", p);    e->ln_b = vtwt_read_f32(wf, nm, 1, s256);
    snprintf(nm, sizeof(nm), "%s.delta.weight", p); e->delta_w = vtwt_read_f32(wf, nm, 2, sdel);
    snprintf(nm, sizeof(nm), "%s.delta.bias", p);   e->delta_b = vtwt_read_f32(wf, nm, 1, s61);
    snprintf(nm, sizeof(nm), "%s.timp.weight", p);  e->timp_w = vtwt_read_f32(wf, nm, 2, stim);
    snprintf(nm, sizeof(nm), "%s.timp.bias", p);    e->timp_b = vtwt_read_f32(wf, nm, 1, s13);
    snprintf(nm, sizeof(nm), "%s.gate.0.weight", p); e->gate0_w = vtwt_read_f32(wf, nm, 2, sg0);
    snprintf(nm, sizeof(nm), "%s.gate.0.bias", p);   e->gate0_b = vtwt_read_f32(wf, nm, 1, s64);
    snprintf(nm, sizeof(nm), "%s.gate.2.weight", p); e->gate2_w = vtwt_read_f32(wf, nm, 2, sg2);
    snprintf(nm, sizeof(nm), "%s.gate.2.bias", p);   e->gate2_b = vtwt_read_f32(wf, nm, 1, s1);

    return e->cq_c1_w && e->cq_c1_b && e->cq_n1_w && e->cq_n1_b &&
           e->cq_c2_w && e->cq_c2_b && e->cq_n2_w && e->cq_n2_b &&
           e->cq_c3_w && e->cq_c3_b && e->cq_n3_w && e->cq_n3_b &&
           e->cq_proj_w && e->cq_proj_b && e->inp_w && e->inp_b &&
           e->qkv_w && e->qkv_b && e->ao_w && e->ao_b && e->ln_w && e->ln_b &&
           e->delta_w && e->delta_b && e->timp_w && e->timp_b &&
           e->gate0_w && e->gate0_b && e->gate2_w && e->gate2_b;
}

static void free_expert(struct orch_expert *e) {
    free_drumnet(&e->base);
    free(e->cq_c1_w); free(e->cq_c1_b); free(e->cq_n1_w); free(e->cq_n1_b);
    free(e->cq_c2_w); free(e->cq_c2_b); free(e->cq_n2_w); free(e->cq_n2_b);
    free(e->cq_c3_w); free(e->cq_c3_b); free(e->cq_n3_w); free(e->cq_n3_b);
    free(e->cq_proj_w); free(e->cq_proj_b);
    free(e->inp_w); free(e->inp_b);
    dr_free_bigru(&e->rnn0); dr_free_bigru(&e->rnn1);
    free(e->qkv_w); free(e->qkv_b); free(e->ao_w); free(e->ao_b); free(e->ln_w); free(e->ln_b);
    free(e->delta_w); free(e->delta_b); free(e->timp_w); free(e->timp_b);
    free(e->gate0_w); free(e->gate0_b); free(e->gate2_w); free(e->gate2_b);
}

struct drums_model *drums_load(const struct vtwt_file *wf) {
    struct drums_model *m = (struct drums_model *)calloc(1, sizeof(*m));
    if (!m) return NULL;
    if (!load_drumnet(wf, "drum_kit", &m->kit)) goto fail;
    for (int i = 0; i < DR_N_EXPERTS; ++i)
        if (!load_expert(wf, i, &m->experts[i])) goto fail;
    return m;
fail:
    drums_free(m);
    return NULL;
}

void drums_free(struct drums_model *m) {
    if (!m) return;
    free_drumnet(&m->kit);
    for (int i = 0; i < DR_N_EXPERTS; ++i) free_expert(&m->experts[i]);
    free(m);
}

/* =========================================================================
 * Drum feature extraction (radix-2 512, Bluestein 1411, 3x2048 6144 FFTs)
 * ========================================================================= */

static void fft_radix2(double *re, double *im, int n, int inverse) {
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
        double ang = sign * DR_TAU / (double)span;
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

/* Sparse triangular filterbank row */
struct fb_row {
    int first, last;
    float *w;
};

static double hz_to_mel(double f) { return 2595.0 * log10(1.0 + f / 700.0); }
static double mel_to_hz(double m) { return 700.0 * (pow(10.0, m / 2595.0) - 1.0); }

static struct fb_row *make_mel_fb(int sr, int n_fft, int n_mels, double fmin, double fmax) {
    int n_bins = n_fft / 2 + 1;
    struct fb_row *fb = (struct fb_row *)calloc((size_t)n_mels, sizeof(*fb));
    double *pts = (double *)malloc((size_t)(n_mels + 2) * sizeof(double));
    double m0 = hz_to_mel(fmin), m1 = hz_to_mel(fmax);
    for (int i = 0; i < n_mels + 2; ++i)
        pts[i] = mel_to_hz(m0 + (m1 - m0) * (double)i / (double)(n_mels + 1));
    for (int i = 0; i < n_mels; ++i) {
        double lo = pts[i], ctr = pts[i + 1], hi = pts[i + 2];
        double norm = 2.0 / (hi - lo);
        int f0 = n_bins, f1 = -1;
        for (int k = 0; k < n_bins; ++k) {
            double f = (double)k * (0.5 * (double)sr) / (double)(n_bins - 1);
            double up = (f - lo) / (ctr - lo > 1e-9 ? ctr - lo : 1e-9);
            double dn = (hi - f) / (hi - ctr > 1e-9 ? hi - ctr : 1e-9);
            double v = up < dn ? up : dn;
            if (v > 0.0) { if (k < f0) f0 = k; if (k > f1) f1 = k; }
        }
        if (f1 >= f0) {
            fb[i].first = f0; fb[i].last = f1;
            fb[i].w = (float *)malloc((size_t)(f1 - f0 + 1) * sizeof(float));
            for (int k = f0; k <= f1; ++k) {
                double f = (double)k * (0.5 * (double)sr) / (double)(n_bins - 1);
                double up = (f - lo) / (ctr - lo > 1e-9 ? ctr - lo : 1e-9);
                double dn = (hi - f) / (hi - ctr > 1e-9 ? hi - ctr : 1e-9);
                double v = up < dn ? up : dn;
                fb[i].w[k - f0] = (float)(v > 0.0 ? v * norm : 0.0);
            }
        } else {
            fb[i].first = 0; fb[i].last = -1;
        }
    }
    free(pts);
    return fb;
}

static struct fb_row *make_cq_fb(void) {
    const int sr = 16000, n_fft = 6144, bpo = 24, n = DR_N_CQ;
    const double fmin = 36.708;
    int n_bins = n_fft / 2 + 1;
    struct fb_row *fb = (struct fb_row *)calloc((size_t)n, sizeof(*fb));
    double c[DR_N_CQ + 2];
    for (int i = 0; i < n + 2; ++i) c[i] = fmin * exp2((double)(i - 1) / (double)bpo);
    double *tmp = (double *)malloc((size_t)n_bins * sizeof(double));
    for (int k = 0; k < n; ++k) {
        double lo = c[k], ce = c[k + 1], hi = c[k + 2];
        double sum = 0.0;
        for (int j = 0; j < n_bins; ++j) {
            double f = (double)j * (double)sr / (double)n_fft;
            double up = (f - lo) / (ce - lo);
            double dn = (hi - f) / (hi - ce);
            double v = up < dn ? up : dn;
            tmp[j] = v > 0.0 ? v : 0.0;
            sum += tmp[j];
        }
        if (sum < 1.0) {
            double jf = ce * (double)n_fft / (double)sr;
            int j0 = (int)floor(jf);
            double a = jf - (double)j0;
            fb[k].first = j0; fb[k].last = j0 + 1;
            fb[k].w = (float *)malloc(2 * sizeof(float));
            fb[k].w[0] = (float)(1.0 - a);
            fb[k].w[1] = (float)a;
        } else {
            int f0 = n_bins, f1 = -1;
            for (int j = 0; j < n_bins; ++j) if (tmp[j] > 0.0) { if (j < f0) f0 = j; if (j > f1) f1 = j; }
            fb[k].first = f0; fb[k].last = f1;
            fb[k].w = (float *)malloc((size_t)(f1 - f0 + 1) * sizeof(float));
            for (int j = f0; j <= f1; ++j) fb[k].w[j - f0] = (float)(tmp[j] / sum);
        }
    }
    free(tmp);
    return fb;
}

static void free_fb(struct fb_row *fb, int n) {
    if (!fb) return;
    for (int i = 0; i < n; ++i) free(fb[i].w);
    free(fb);
}

static inline void apply_fb_log(const double *power, const struct fb_row *fb, int n, float *dst) {
    for (int i = 0; i < n; ++i) {
        double acc = 0.0;
        for (int k = fb[i].first; k <= fb[i].last; ++k) acc += (double)fb[i].w[k - fb[i].first] * power[k];
        dst[i] = vt_f16_to_f32(vt_f32_to_f16((float)log(acc + 1e-5)));
    }
}

struct dr_feat_ctx {
    const float *x44, *x16;
    int n44, n16, T;
    const struct fb_row *fb_lo, *fb_hi, *fb_cq;
    double win512[512], win1411[1411], win6144[6144];
    /* Bluestein 1411 (M=4096) precomputed chirp and B = FFT(b) */
    double ch_re[1411], ch_im[1411];
    double blu_bre[4096], blu_bim[4096];
    /* 6144 = 3 * 2048 twiddles */
    double tw1_re[3073], tw1_im[3073], tw2_re[3073], tw2_im[3073];
    float *out; /* [T, 280] */
};

static void dr_feat_worker(int start, int end, void *arg) {
    struct dr_feat_ctx *c = (struct dr_feat_ctx *)arg;
    double *re = (double *)malloc(4096 * sizeof(double));
    double *im = (double *)malloc(4096 * sizeof(double));
    double *r0 = (double *)malloc(2048 * sizeof(double));
    double *i0 = (double *)malloc(2048 * sizeof(double));
    double *r1 = (double *)malloc(2048 * sizeof(double));
    double *i1 = (double *)malloc(2048 * sizeof(double));
    double *r2 = (double *)malloc(2048 * sizeof(double));
    double *i2 = (double *)malloc(2048 * sizeof(double));
    double *pwr = (double *)malloc(3073 * sizeof(double));
    if (!re || !im || !r0 || !i0 || !r1 || !i1 || !r2 || !i2 || !pwr) {
        free(re); free(im); free(r0); free(i0); free(r1); free(i1); free(r2); free(i2); free(pwr);
        return;
    }

    for (int f = start; f < end; ++f) {
        float *row = c->out + (size_t)f * DR_N_BANDS;

        /* 1. lo: 512-pt FFT on x16, hop=160 */
        int c16 = f * 160;
        for (int i = 0; i < 512; ++i) {
            int s = c16 + i - 256;
            re[i] = (s >= 0 && s < c->n16) ? (double)c->x16[s] * c->win512[i] : 0.0;
            im[i] = 0.0;
        }
        fft_radix2(re, im, 512, 0);
        for (int k = 0; k <= 256; ++k) pwr[k] = re[k] * re[k] + im[k] * im[k];
        apply_fb_log(pwr, c->fb_lo, DR_N_LO, row);

        /* 2. hi: 1411-pt Bluestein FFT (M=4096) on x44, hop=441 */
        int c44 = f * 441;
        memset(re, 0, 4096 * sizeof(double));
        memset(im, 0, 4096 * sizeof(double));
        for (int i = 0; i < 1411; ++i) {
            int s = c44 + i - 705;
            double v = (s >= 0 && s < c->n44) ? (double)c->x44[s] * c->win1411[i] : 0.0;
            re[i] = v * c->ch_re[i];
            im[i] = v * c->ch_im[i];
        }
        fft_radix2(re, im, 4096, 0);
        for (int k = 0; k < 4096; ++k) {
            double ar = re[k], ai = im[k];
            re[k] = ar * c->blu_bre[k] - ai * c->blu_bim[k];
            im[k] = ar * c->blu_bim[k] + ai * c->blu_bre[k];
        }
        fft_radix2(re, im, 4096, 1);
        for (int k = 0; k <= 705; ++k) {
            double xr = re[k] * c->ch_re[k] - im[k] * c->ch_im[k];
            double xi = re[k] * c->ch_im[k] + im[k] * c->ch_re[k];
            pwr[k] = xr * xr + xi * xi;
        }
        apply_fb_log(pwr, c->fb_hi, DR_N_HI, row + DR_N_LO);

        /* 3. cq: 6144-pt (3 x 2048) FFT on x16, hop=160 */
        for (int n = 0; n < 2048; ++n) {
            int s0 = c16 + 3 * n - 3072;
            int s1 = s0 + 1;
            int s2 = s0 + 2;
            r0[n] = (s0 >= 0 && s0 < c->n16) ? (double)c->x16[s0] * c->win6144[3 * n] : 0.0;
            r1[n] = (s1 >= 0 && s1 < c->n16) ? (double)c->x16[s1] * c->win6144[3 * n + 1] : 0.0;
            r2[n] = (s2 >= 0 && s2 < c->n16) ? (double)c->x16[s2] * c->win6144[3 * n + 2] : 0.0;
            i0[n] = i1[n] = i2[n] = 0.0;
        }
        fft_radix2(r0, i0, 2048, 0);
        fft_radix2(r1, i1, 2048, 0);
        fft_radix2(r2, i2, 2048, 0);
        for (int k = 0; k <= 3072; ++k) {
            int j = k & 2047;
            double x1r = r1[j] * c->tw1_re[k] - i1[j] * c->tw1_im[k];
            double x1i = r1[j] * c->tw1_im[k] + i1[j] * c->tw1_re[k];
            double x2r = r2[j] * c->tw2_re[k] - i2[j] * c->tw2_im[k];
            double x2i = r2[j] * c->tw2_im[k] + i2[j] * c->tw2_re[k];
            double xr = r0[j] + x1r + x2r;
            double xi = i0[j] + x1i + x2i;
            pwr[k] = xr * xr + xi * xi;
        }
        apply_fb_log(pwr, c->fb_cq, DR_N_CQ, row + DR_N_LO + DR_N_HI);
    }

    free(re); free(im); free(r0); free(i0); free(r1); free(i1); free(r2); free(i2); free(pwr);
}

static int compute_drum_features(const float *x44_in, size_t n44, float **feats_out, int *T_out) {
    *feats_out = NULL; *T_out = 0;
    /* Level normalize to -18 dBFS */
    double sq = 0.0;
    for (size_t i = 0; i < n44; ++i) sq += (double)x44_in[i] * (double)x44_in[i];
    double rms = sqrt(sq / (double)n44) + 1e-9;
    float gain = (float)(pow(10.0, -18.0 / 20.0) / rms);
    float *x44 = (float *)malloc(n44 * sizeof(float));
    if (!x44) return 0;
    for (size_t i = 0; i < n44; ++i) x44[i] = x44_in[i] * gain;

    float *x16 = NULL; size_t n16 = 0;
    if (!resample_mono(x44, n44, (double)DR_SR, 16000.0, &x16, &n16)) { free(x44); return 0; }
    int T_lo = (int)(n16 / 160);
    int T_hi = 1 + (int)(n44 / 441);
    int T = T_lo < T_hi ? T_lo : T_hi;
    T = (T / 2) * 2;
    if (T <= 0) { free(x44); free(x16); return 1; }

    float *feats = (float *)malloc((size_t)T * DR_N_BANDS * sizeof(float));
    struct dr_feat_ctx *ctx = (struct dr_feat_ctx *)calloc(1, sizeof(*ctx));
    struct fb_row *fb_lo = make_mel_fb(16000, 512, DR_N_LO, 20.0, 7800.0);
    struct fb_row *fb_hi = make_mel_fb(DR_SR, 1411, DR_N_HI, 7800.0, 20000.0);
    struct fb_row *fb_cq = make_cq_fb();
    if (!feats || !ctx || !fb_lo || !fb_hi || !fb_cq) {
        free(feats); free(ctx); free_fb(fb_lo, DR_N_LO); free_fb(fb_hi, DR_N_HI); free_fb(fb_cq, DR_N_CQ);
        free(x44); free(x16); return 0;
    }

    ctx->x44 = x44; ctx->x16 = x16; ctx->n44 = (int)n44; ctx->n16 = (int)n16; ctx->T = T;
    ctx->fb_lo = fb_lo; ctx->fb_hi = fb_hi; ctx->fb_cq = fb_cq; ctx->out = feats;
    for (int i = 0; i < 512; ++i) ctx->win512[i] = 0.5 - 0.5 * cos(DR_TAU * i / 512.0);
    for (int i = 0; i < 1411; ++i) ctx->win1411[i] = 0.5 - 0.5 * cos(DR_TAU * i / 1411.0);
    for (int i = 0; i < 6144; ++i) ctx->win6144[i] = 0.5 - 0.5 * cos(DR_TAU * i / 6144.0);
    for (int n = 0; n < 1411; ++n) {
        double ang = -DR_PI * (double)n * (double)n / 1411.0;
        ctx->ch_re[n] = cos(ang);
        ctx->ch_im[n] = sin(ang);
        ctx->blu_bre[n] = ctx->ch_re[n];
        ctx->blu_bim[n] = -ctx->ch_im[n];
        if (n > 0) {
            ctx->blu_bre[4096 - n] = ctx->ch_re[n];
            ctx->blu_bim[4096 - n] = -ctx->ch_im[n];
        }
    }
    fft_radix2(ctx->blu_bre, ctx->blu_bim, 4096, 0);
    for (int k = 0; k <= 3072; ++k) {
        double a1 = -DR_TAU * (double)k / 6144.0;
        ctx->tw1_re[k] = cos(a1); ctx->tw1_im[k] = sin(a1);
        ctx->tw2_re[k] = cos(2.0 * a1); ctx->tw2_im[k] = sin(2.0 * a1);
    }

    nn_parallel_for(T, 16, dr_feat_worker, ctx);

    free(ctx); free_fb(fb_lo, DR_N_LO); free_fb(fb_hi, DR_N_HI); free_fb(fb_cq, DR_N_CQ);
    free(x44); free(x16);
    *feats_out = feats; *T_out = T;
    return 1;
}

/* =========================================================================
 * Neural kernels for DrumNet & OrchestralExpert
 * ========================================================================= */

static inline float dr_silu(float x) { return x / (1.0f + expf(-x)); }
static inline float dr_sig(float x)  { return 1.0f / (1.0f + expf(-x)); }

static void silu_inplace(float *x, size_t n) {
    for (size_t i = 0; i < n; ++i) x[i] = dr_silu(x[i]);
}

/* Batched bidirectional GRU on x[B, L, in_dim] -> out[B, L, 2*hid] + optional hn[B, 2*hid]. */
static int run_bigru(const struct dr_bigru *g, const float *x, int B, int L,
                     float *out, float *hn_out) {
    int H = g->hid, H3 = 3 * H;
    float *ih = (float *)malloc((size_t)B * L * H3 * sizeof(float));
    float *hp = (float *)calloc((size_t)B * H, sizeof(float));
    float *hh = (float *)malloc((size_t)B * H3 * sizeof(float));
    if (!ih || !hp || !hh) { free(ih); free(hp); free(hh); return 0; }

    /* Forward */
    nn_sgemm_nt(B * L, H3, g->in_dim, x, g->in_dim, g->w_ih_f, g->in_dim, ih, H3, g->b_ih_f, 0);
    for (int t = 0; t < L; ++t) {
        if (t == 0) {
            for (int b = 0; b < B; ++b) memcpy(hh + (size_t)b * H3, g->b_hh_f, (size_t)H3 * sizeof(float));
        } else {
            nn_sgemm_nt(B, H3, H, hp, H, g->w_hh_f, H, hh, H3, g->b_hh_f, 0);
        }
        for (int b = 0; b < B; ++b) {
            const float *ip = ih + ((size_t)b * L + t) * H3;
            const float *hhp = hh + (size_t)b * H3;
            float *prev = hp + (size_t)b * H;
            float *dst = out + ((size_t)b * L + t) * (2 * H);
            for (int j = 0; j < H; ++j) {
                float r = dr_sig(ip[j] + hhp[j]);
                float z = dr_sig(ip[H + j] + hhp[H + j]);
                float n = tanhf(ip[2 * H + j] + r * hhp[2 * H + j]);
                float hn = (1.0f - z) * n + z * prev[j];
                prev[j] = hn; dst[j] = hn;
            }
        }
    }
    if (hn_out) {
        for (int b = 0; b < B; ++b)
            memcpy(hn_out + (size_t)b * (2 * H), hp + (size_t)b * H, (size_t)H * sizeof(float));
    }

    /* Reverse */
    memset(hp, 0, (size_t)B * H * sizeof(float));
    nn_sgemm_nt(B * L, H3, g->in_dim, x, g->in_dim, g->w_ih_r, g->in_dim, ih, H3, g->b_ih_r, 0);
    for (int t = L - 1; t >= 0; --t) {
        if (t == L - 1) {
            for (int b = 0; b < B; ++b) memcpy(hh + (size_t)b * H3, g->b_hh_r, (size_t)H3 * sizeof(float));
        } else {
            nn_sgemm_nt(B, H3, H, hp, H, g->w_hh_r, H, hh, H3, g->b_hh_r, 0);
        }
        for (int b = 0; b < B; ++b) {
            const float *ip = ih + ((size_t)b * L + t) * H3;
            const float *hhp = hh + (size_t)b * H3;
            float *prev = hp + (size_t)b * H;
            float *dst = out + ((size_t)b * L + t) * (2 * H) + H;
            for (int j = 0; j < H; ++j) {
                float r = dr_sig(ip[j] + hhp[j]);
                float z = dr_sig(ip[H + j] + hhp[H + j]);
                float n = tanhf(ip[2 * H + j] + r * hhp[2 * H + j]);
                float hn = (1.0f - z) * n + z * prev[j];
                prev[j] = hn; dst[j] = hn;
            }
        }
    }
    if (hn_out) {
        for (int b = 0; b < B; ++b)
            memcpy(hn_out + (size_t)b * (2 * H) + H, hp + (size_t)b * H, (size_t)H * sizeof(float));
    }
    free(ih); free(hp); free(hh);
    return 1;
}

static void run_res2d(const struct dr_res2d *r, float *x, int H, int W, float *tmp) {
    int C = r->c;
    for (int h = 0; h < H; ++h) {
        for (int w = 0; w < W; ++w) {
            float *dst = tmp + ((size_t)h * W + w) * C;
            memcpy(dst, r->dw_b, (size_t)C * sizeof(float));
            for (int kh = 0; kh < 3; ++kh) {
                int ih = h + kh - 1;
                if (ih < 0 || ih >= H) continue;
                for (int kw = 0; kw < 3; ++kw) {
                    int iw = w + kw - 1;
                    if (iw < 0 || iw >= W) continue;
                    const float *src = x + ((size_t)ih * W + iw) * C;
                    const float *wk = r->dw_w + (kh * 3 + kw) * C;
                    for (int c = 0; c < C; ++c) dst[c] += src[c] * wk[c];
                }
            }
            for (int c = 0; c < C; ++c)
                dst[c] = dr_silu(dst[c] * r->bn1.scale[c] + r->bn1.shift[c]);
        }
    }
    /* Fold bn2 into pw1 output on the fly: use a second buffer or fold into pw1 */
    float *pw_out = (float *)malloc((size_t)H * W * C * sizeof(float));
    if (!pw_out) return;
    nn_sgemm_nt(H * W, C, C, tmp, C, r->pw_w, C, pw_out, C, r->pw_b, 0);
    for (int i = 0; i < H * W; ++i) {
        float *xi = x + (size_t)i * C;
        const float *pi = pw_out + (size_t)i * C;
        for (int c = 0; c < C; ++c) xi[c] += pi[c] * r->bn2.scale[c] + r->bn2.shift[c];
    }
    free(pw_out);
}

static void maxpool2d_nhwc(const float *in, int H, int W, int C, int ph, int pw, float *out) {
    int Ho = H / ph, Wo = W / pw;
    for (int oh = 0; oh < Ho; ++oh) {
        for (int ow = 0; ow < Wo; ++ow) {
            float *dst = out + ((size_t)oh * Wo + ow) * C;
            for (int c = 0; c < C; ++c) dst[c] = -FLT_MAX;
            for (int kh = 0; kh < ph; ++kh) {
                for (int kw = 0; kw < pw; ++kw) {
                    const float *src = in + ((size_t)(oh * ph + kh) * W + (ow * pw + kw)) * C;
                    for (int c = 0; c < C; ++c) if (src[c] > dst[c]) dst[c] = src[c];
                }
            }
        }
    }
}

/* Self-attention (no positions, multithreaded over query rows) on qkv[T, 3*D] -> out[T, D]. */
struct dr_attn_ctx {
    const float *qkv;
    float *out;
    int T, D, heads;
};
static void dr_attn_worker(int start, int end, void *arg) {
    struct dr_attn_ctx *c = (struct dr_attn_ctx *)arg;
    int T = c->T, D = c->D, H = c->heads, hd = D / H;
    float scale = 1.0f / sqrtf((float)hd);
    float *sc = (float *)malloc((size_t)T * sizeof(float));
    if (!sc) return;
    for (int qi = start; qi < end; ++qi) {
        for (int h = 0; h < H; ++h) {
            const float *qv = c->qkv + (size_t)qi * 3 * D + h * hd;
            float mx = -1e30f;
            for (int ki = 0; ki < T; ++ki) {
                const float *kv = c->qkv + (size_t)ki * 3 * D + D + h * hd;
                float dot = 0.0f;
                for (int d = 0; d < hd; ++d) dot += qv[d] * kv[d];
                float s = dot * scale;
                sc[ki] = s;
                if (s > mx) mx = s;
            }
            float se = 0.0f;
            for (int ki = 0; ki < T; ++ki) { sc[ki] = expf(sc[ki] - mx); se += sc[ki]; }
            float inv = 1.0f / se;
            float *dst = c->out + (size_t)qi * D + h * hd;
            memset(dst, 0, (size_t)hd * sizeof(float));
            for (int ki = 0; ki < T; ++ki) {
                float w = sc[ki] * inv;
                const float *vv = c->qkv + (size_t)ki * 3 * D + 2 * D + h * hd;
                for (int d = 0; d < hd; ++d) dst[d] += w * vv[d];
            }
        }
    }
    free(sc);
}

/* DrumNet.embed on xm[T, 160] (even T) -> c_out[T/2, 88]. */
static int drumnet_embed_chunk(const struct drumnet *d, const float *xm, int T, float *c_out) {
    int T2 = T / 2;
    float *in = (float *)malloc((size_t)T * DR_N_MEL * sizeof(float));
    float *b16 = (float *)malloc((size_t)T * 160 * 16 * sizeof(float));
    float *t16 = (float *)malloc((size_t)T * 160 * 16 * sizeof(float));
    float *p16 = (float *)malloc((size_t)T2 * 80 * 16 * sizeof(float));
    float *b32 = (float *)malloc((size_t)T2 * 80 * 32 * sizeof(float));
    float *t32 = (float *)malloc((size_t)T2 * 80 * 32 * sizeof(float));
    float *p32 = (float *)malloc((size_t)T2 * 40 * 32 * sizeof(float));
    float *b56 = (float *)malloc((size_t)T2 * 40 * 56 * sizeof(float));
    float *t56 = (float *)malloc((size_t)T2 * 40 * 56 * sizeof(float));
    float *p56 = (float *)malloc((size_t)T2 * 20 * 56 * sizeof(float));
    int ok = 0;
    if (!in || !b16 || !t16 || !p16 || !b32 || !t32 || !p32 || !b56 || !t56 || !p56) goto done;

    for (size_t i = 0; i < (size_t)T * DR_N_MEL; ++i) in[i] = (xm[i] + 5.0f) / 3.0f;
    if (!nn_conv2d_nhwc(in, T, 160, 1, d->c0_w, d->c0_b, 16, 3, 3, 1, 1, 1, 1, b16)) goto done;
    nn_affine_channel(b16, b16, T * 160, 16, d->bn0.scale, d->bn0.shift);
    silu_inplace(b16, (size_t)T * 160 * 16);
    for (int i = 0; i < 2; ++i) run_res2d(&d->r0[i], b16, T, 160, t16);
    maxpool2d_nhwc(b16, T, 160, 16, 2, 2, p16);

    if (!nn_conv2d_nhwc(p16, T2, 80, 16, d->c1_w, d->c1_b, 32, 3, 3, 1, 1, 1, 1, b32)) goto done;
    nn_affine_channel(b32, b32, T2 * 80, 32, d->bn1.scale, d->bn1.shift);
    silu_inplace(b32, (size_t)T2 * 80 * 32);
    for (int i = 0; i < 3; ++i) run_res2d(&d->r1[i], b32, T2, 80, t32);
    maxpool2d_nhwc(b32, T2, 80, 32, 1, 2, p32);

    if (!nn_conv2d_nhwc(p32, T2, 40, 32, d->c2_w, d->c2_b, 56, 3, 3, 1, 1, 1, 1, b56)) goto done;
    nn_affine_channel(b56, b56, T2 * 40, 56, d->bn2.scale, d->bn2.shift);
    silu_inplace(b56, (size_t)T2 * 40 * 56);
    for (int i = 0; i < 3; ++i) run_res2d(&d->r2[i], b56, T2, 40, t56);
    maxpool2d_nhwc(b56, T2, 40, 56, 1, 2, p56);
    for (int i = 0; i < 3; ++i) run_res2d(&d->r3[i], p56, T2, 20, t56);

    /* Collapse BandGRU: B=T2, L=20, C=56 -> m=22 bidir */
    {
        float *gout = (float *)malloc((size_t)T2 * 20 * 44 * sizeof(float));
        float *ghn = (float *)malloc((size_t)T2 * 44 * sizeof(float));
        float *z88 = (float *)malloc((size_t)T2 * 88 * sizeof(float));
        if (!gout || !ghn || !z88) { free(gout); free(ghn); free(z88); goto done; }
        if (!run_bigru(&d->col_rnn, p56, T2, 20, gout, ghn)) {
            free(gout); free(ghn); free(z88); goto done;
        }
        for (int t = 0; t < T2; ++t) {
            float *zt = z88 + (size_t)t * 88;
            memcpy(zt, ghn + (size_t)t * 44, 44 * sizeof(float));
            memset(zt + 44, 0, 44 * sizeof(float));
            for (int f = 0; f < 20; ++f) {
                const float *gf = gout + ((size_t)t * 20 + f) * 44;
                for (int k = 0; k < 44; ++k) zt[44 + k] += gf[k];
            }
            for (int k = 0; k < 44; ++k) zt[44 + k] *= 0.05f;
        }
        nn_sgemm_nt(T2, DR_W, 88, z88, 88, d->col_proj_w, 88, c_out, DR_W, d->col_proj_b, 0);
        free(gout); free(ghn); free(z88);
    }
    ok = 1;
done:
    free(in); free(b16); free(t16); free(p16); free(b32); free(t32); free(p32); free(b56); free(t56); free(p56);
    return ok;
}

static int drumnet_embed(const struct drumnet *d, const float *feats_280, int T, float *c_out) {
    /* Extract xm [T, 160] in chunks of <= 8000 frames (margin 200) matching embed_long */
    const int chunk = 8000, margin = 200;
    if (T <= chunk + 2 * margin) {
        float *xm = (float *)malloc((size_t)T * DR_N_MEL * sizeof(float));
        if (!xm) return 0;
        for (int t = 0; t < T; ++t) memcpy(xm + (size_t)t * DR_N_MEL, feats_280 + (size_t)t * DR_N_BANDS, DR_N_MEL * sizeof(float));
        int ok = drumnet_embed_chunk(d, xm, T, c_out);
        free(xm);
        return ok;
    }
    for (int s = 0; s < T; s += chunk) {
        int a = s - margin; if (a < 0) a = 0;
        int b = s + chunk + margin; if (b > T) b = T;
        int len = ((b - a) / 2) * 2;
        float *xm = (float *)malloc((size_t)len * DR_N_MEL * sizeof(float));
        float *ch_out = (float *)malloc((size_t)(len / 2) * DR_W * sizeof(float));
        if (!xm || !ch_out) { free(xm); free(ch_out); return 0; }
        for (int t = 0; t < len; ++t)
            memcpy(xm + (size_t)t * DR_N_MEL, feats_280 + (size_t)(a + t) * DR_N_BANDS, DR_N_MEL * sizeof(float));
        int ok = drumnet_embed_chunk(d, xm, len, ch_out);
        free(xm);
        if (!ok) { free(ch_out); return 0; }
        int lo = (s - a) / 2;
        int want = ((s + chunk < T ? s + chunk : T) - s) / 2;
        memcpy(c_out + (size_t)(s / 2) * DR_W, ch_out + (size_t)lo * DR_W, (size_t)want * DR_W * sizeof(float));
        free(ch_out);
    }
    return 1;
}

/* DrumNet.trunk on c[T2, 88] -> h_out[T2, 88], z_out[T2, 61], v_out[T2, 61]. */
static int drumnet_trunk(const struct drumnet *d, const float *c_in, int T2,
                         float *h_out, float *z_out, float *v_out) {
    float *h = (float *)malloc((size_t)T2 * DR_W * sizeof(float));
    float *tmp = (float *)malloc((size_t)T2 * DR_W * sizeof(float));
    float *gout = (float *)malloc((size_t)T2 * 64 * sizeof(float));
    float *qkv = (float *)malloc((size_t)T2 * 96 * sizeof(float));
    float *att = (float *)malloc((size_t)T2 * 32 * sizeof(float));
    int ok = 0;
    if (!h || !tmp || !gout || !qkv || !att) goto done;
    memcpy(h, c_in, (size_t)T2 * DR_W * sizeof(float));

    /* Temporal 0: ConvBlock(w=88, k=15, pad=7) */
    for (int t = 0; t < T2; ++t) {
        float *dst = tmp + (size_t)t * DR_W;
        memcpy(dst, d->tb_dw_b, DR_W * sizeof(float));
        for (int k = 0; k < 15; ++k) {
            int st = t + k - 7;
            if (st < 0 || st >= T2) continue;
            const float *src = h + (size_t)st * DR_W;
            const float *wk = d->tb_dw_w + k * DR_W;
            for (int c = 0; c < DR_W; ++c) dst[c] += src[c] * wk[c];
        }
        for (int c = 0; c < DR_W; ++c)
            dst[c] = dr_silu(dst[c] * d->tb_bn.scale[c] + d->tb_bn.shift[c]);
    }
    nn_sgemm_nt(T2, DR_W, DR_W, tmp, DR_W, d->tb_pw_w, DR_W, h, DR_W, d->tb_pw_b, 1);

    /* Temporal 1: GRUBlock(w=88, h=32) */
    nn_layernorm(h, tmp, T2, DR_W, d->gb_ln_w, d->gb_ln_b, 1e-5f);
    if (!run_bigru(&d->gb_rnn, tmp, 1, T2, gout, NULL)) goto done;
    nn_sgemm_nt(T2, DR_W, 64, gout, 64, d->gb_out_w, 64, h, DR_W, d->gb_out_b, 1);

    /* Temporal 2: SongAttention(w=88, da=32, heads=2) */
    nn_layernorm(h, tmp, T2, DR_W, d->sa_ln_w, d->sa_ln_b, 1e-5f);
    nn_sgemm_nt(T2, 96, DR_W, tmp, DR_W, d->sa_qkv_w, DR_W, qkv, 96, d->sa_qkv_b, 0);
    {
        struct dr_attn_ctx ac = { qkv, att, T2, 32, 2 };
        nn_parallel_for(T2, 16, dr_attn_worker, &ac);
    }
    nn_sgemm_nt(T2, DR_W, 32, att, 32, d->sa_o_w, 32, h, DR_W, d->sa_o_b, 1);
    if (h_out) memcpy(h_out, h, (size_t)T2 * DR_W * sizeof(float));

    /* FamilyHeads */
    nn_sgemm_nt(T2, DR_KEYS, DR_W, h, DR_W, d->rest_w, DR_W, z_out, DR_KEYS, d->rest_b, 0);
    {
        float *tw_out = (float *)malloc((size_t)T2 * 2 * DR_TOWER_H * sizeof(float));
        float *cat = (float *)malloc((size_t)T2 * (DR_W + 2 * DR_TOWER_H) * sizeof(float));
        float *part = (float *)malloc((size_t)T2 * 10 * sizeof(float));
        if (!tw_out || !cat || !part) { free(tw_out); free(cat); free(part); goto done; }
        for (int g = 0; g < DR_N_TOWERS; ++g) {
            if (!run_bigru(&d->towers[g], h, 1, T2, tw_out, NULL)) {
                free(tw_out); free(cat); free(part); goto done;
            }
            int d_in = DR_W + 2 * DR_TOWER_H;
            for (int t = 0; t < T2; ++t) {
                memcpy(cat + (size_t)t * d_in, tw_out + (size_t)t * (2 * DR_TOWER_H), (2 * DR_TOWER_H) * sizeof(float));
                memcpy(cat + (size_t)t * d_in + 2 * DR_TOWER_H, h + (size_t)t * DR_W, DR_W * sizeof(float));
            }
            int klen = TOWER_LENS[g];
            nn_sgemm_nt(T2, klen, d_in, cat, d_in, d->thead_w[g], d_in, part, klen, d->thead_b[g], 0);
            for (int t = 0; t < T2; ++t)
                for (int j = 0; j < klen; ++j)
                    z_out[(size_t)t * DR_KEYS + TOWER_KEYS[g][j]] = part[(size_t)t * klen + j];
        }
        free(tw_out); free(cat); free(part);
    }

    /* Velocity head: Linear(88, 16) -> Linear(16, 61) */
    {
        float *v16 = (float *)malloc((size_t)T2 * 16 * sizeof(float));
        if (!v16) goto done;
        nn_sgemm_nt(T2, 16, DR_W, h, DR_W, d->vel0_w, DR_W, v16, 16, d->vel0_b, 0);
        nn_sgemm_nt(T2, DR_KEYS, 16, v16, 16, d->vel1_w, 16, v_out, DR_KEYS, d->vel1_b, 0);
        free(v16);
    }
    ok = 1;
done:
    free(h); free(tmp); free(gout); free(qkv); free(att);
    return ok;
}

/* GroupNorm(4 groups) on [H, W, C] in-place. */
static void groupnorm_nhwc(float *x, int H, int W, int C, int groups, const float *w, const float *b) {
    int cpg = C / groups;
    size_t hw = (size_t)H * W;
    double inv_n = 1.0 / (double)(hw * (size_t)cpg);
    for (int g = 0; g < groups; ++g) {
        int c0 = g * cpg;
        double sum = 0.0;
        for (size_t i = 0; i < hw; ++i) {
            const float *p = x + i * C + c0;
            for (int c = 0; c < cpg; ++c) sum += p[c];
        }
        double mu = sum * inv_n;
        double var = 0.0;
        for (size_t i = 0; i < hw; ++i) {
            const float *p = x + i * C + c0;
            for (int c = 0; c < cpg; ++c) { double d = p[c] - mu; var += d * d; }
        }
        float inv_sd = 1.0f / sqrtf((float)(var * inv_n) + 1e-5f);
        float fmu = (float)mu;
        for (size_t i = 0; i < hw; ++i) {
            float *p = x + i * C + c0;
            for (int c = 0; c < cpg; ++c)
                p[c] = (p[c] - fmu) * inv_sd * w[c0 + c] + b[c0 + c];
        }
    }
}

static int run_expert(const struct orch_expert *e, const float *feats_280, int T,
                      float *drum_p_out, float *timp_p_out, float *vel_p_out, double *router_out) {
    int T2 = T / 2;
    float *c_emb = (float *)malloc((size_t)T2 * DR_W * sizeof(float));
    float *h0 = (float *)malloc((size_t)T2 * DR_W * sizeof(float));
    float *z0 = (float *)malloc((size_t)T2 * DR_KEYS * sizeof(float));
    float *v0 = (float *)malloc((size_t)T2 * DR_KEYS * sizeof(float));
    float *cq_out = (float *)malloc((size_t)T2 * 128 * sizeof(float));
    int ok = 0;
    if (!c_emb || !h0 || !z0 || !v0 || !cq_out) goto done;

    if (!drumnet_embed(&e->base, feats_280, T, c_emb)) goto done;
    if (!drumnet_trunk(&e->base, c_emb, T2, h0, z0, v0)) goto done;
    free(c_emb); c_emb = NULL;

    /* CQBranch on feats_280[:, 160:280] -> [T2, 128] */
    {
        float *xc = (float *)malloc((size_t)T * DR_N_CQ * sizeof(float));
        float *z_in = (float *)malloc((size_t)T * DR_N_CQ * 3 * sizeof(float));
        float *z1 = (float *)malloc((size_t)T * DR_N_CQ * 24 * sizeof(float));
        float *z2 = (float *)malloc((size_t)T2 * DR_N_CQ * 32 * sizeof(float));
        float *z3 = (float *)malloc((size_t)T2 * DR_N_CQ * 32 * sizeof(float));
        float *flat = (float *)malloc((size_t)T2 * 3840 * sizeof(float));
        if (!xc || !z_in || !z1 || !z2 || !z3 || !flat) {
            free(xc); free(z_in); free(z1); free(z2); free(z3); free(flat); goto done;
        }
        double sum = 0.0;
        for (int t = 0; t < T; ++t) {
            const float *src = feats_280 + (size_t)t * DR_N_BANDS + DR_N_MEL;
            for (int f = 0; f < DR_N_CQ; ++f) { xc[(size_t)t * DR_N_CQ + f] = src[f]; sum += src[f]; }
        }
        float mean = (float)(sum / (double)((size_t)T * DR_N_CQ));
        float lo = FLT_MAX;
        for (size_t i = 0; i < (size_t)T * DR_N_CQ; ++i) {
            xc[i] = (xc[i] - mean) * 0.25f;
            if (xc[i] < lo) lo = xc[i];
        }
        for (int t = 0; t < T; ++t) {
            const float *row = xc + (size_t)t * DR_N_CQ;
            float *dst = z_in + (size_t)t * DR_N_CQ * 3;
            for (int f = 0; f < DR_N_CQ; ++f) {
                dst[f * 3 + 0] = row[f];
                dst[f * 3 + 1] = (f + 14 < DR_N_CQ) ? row[f + 14] : lo;
                dst[f * 3 + 2] = (f + 24 < DR_N_CQ) ? row[f + 24] : lo;
            }
        }
        free(xc); xc = NULL;
        if (!nn_conv2d_nhwc(z_in, T, DR_N_CQ, 3, e->cq_c1_w, e->cq_c1_b, 24, 5, 7, 1, 1, 2, 3, z1)) {
            free(z_in); free(z1); free(z2); free(z3); free(flat); goto done;
        }
        free(z_in); z_in = NULL;
        groupnorm_nhwc(z1, T, DR_N_CQ, 24, 4, e->cq_n1_w, e->cq_n1_b);
        silu_inplace(z1, (size_t)T * DR_N_CQ * 24);
        if (!nn_conv2d_nhwc(z1, T, DR_N_CQ, 24, e->cq_c2_w, e->cq_c2_b, 32, 3, 5, 2, 1, 1, 2, z2)) {
            free(z1); free(z2); free(z3); free(flat); goto done;
        }
        free(z1); z1 = NULL;
        groupnorm_nhwc(z2, T2, DR_N_CQ, 32, 4, e->cq_n2_w, e->cq_n2_b);
        silu_inplace(z2, (size_t)T2 * DR_N_CQ * 32);
        if (!nn_conv2d_nhwc(z2, T2, DR_N_CQ, 32, e->cq_c3_w, e->cq_c3_b, 32, 3, 5, 1, 1, 1, 2, z3)) {
            free(z2); free(z3); free(flat); goto done;
        }
        groupnorm_nhwc(z3, T2, DR_N_CQ, 32, 4, e->cq_n3_w, e->cq_n3_b);
        for (size_t i = 0; i < (size_t)T2 * DR_N_CQ * 32; ++i) z3[i] = dr_silu(z3[i]) + z2[i];
        free(z2); z2 = NULL;
        /* Permute [T2, F=120, C=32] -> [T2, C=32, F=120] before proj(3840 -> 128) */
        for (int t = 0; t < T2; ++t) {
            const float *src = z3 + (size_t)t * DR_N_CQ * 32;
            float *dst = flat + (size_t)t * 3840;
            for (int f = 0; f < DR_N_CQ; ++f)
                for (int c = 0; c < 32; ++c)
                    dst[c * DR_N_CQ + f] = src[f * 32 + c];
        }
        free(z3); z3 = NULL;
        nn_sgemm_nt(T2, 128, 3840, flat, 3840, e->cq_proj_w, 3840, cq_out, 128, e->cq_proj_b, 0);
        silu_inplace(cq_out, (size_t)T2 * 128);
        free(flat);
    }

    /* Adapter: concat [h0(88), cq(128), sig(z0)(61)] -> Linear(277,192) -> SiLU -> 2-layer BiGRU(128) -> Attn(4h) -> LN */
    {
        float *cat = (float *)malloc((size_t)T2 * 277 * sizeof(float));
        float *a = (float *)malloc((size_t)T2 * 192 * sizeof(float));
        float *r0 = (float *)malloc((size_t)T2 * 256 * sizeof(float));
        float *r1 = (float *)malloc((size_t)T2 * 256 * sizeof(float));
        float *qkv = (float *)malloc((size_t)T2 * 768 * sizeof(float));
        float *att = (float *)malloc((size_t)T2 * 256 * sizeof(float));
        float *del = (float *)malloc((size_t)T2 * DR_KEYS * sizeof(float));
        float *tmp = (float *)malloc((size_t)T2 * DR_TIMP * sizeof(float));
        if (!cat || !a || !r0 || !r1 || !qkv || !att || !del || !tmp) {
            free(cat); free(a); free(r0); free(r1); free(qkv); free(att); free(del); free(tmp); goto done;
        }
        for (int t = 0; t < T2; ++t) {
            float *dst = cat + (size_t)t * 277;
            memcpy(dst, h0 + (size_t)t * DR_W, DR_W * sizeof(float));
            memcpy(dst + DR_W, cq_out + (size_t)t * 128, 128 * sizeof(float));
            const float *zt = z0 + (size_t)t * DR_KEYS;
            for (int k = 0; k < DR_KEYS; ++k) dst[DR_W + 128 + k] = dr_sig(zt[k]);
        }
        nn_sgemm_nt(T2, 192, 277, cat, 277, e->inp_w, 277, a, 192, e->inp_b, 0);
        silu_inplace(a, (size_t)T2 * 192);
        free(cat); cat = NULL;

        if (!run_bigru(&e->rnn0, a, 1, T2, r0, NULL) || !run_bigru(&e->rnn1, r0, 1, T2, r1, NULL)) {
            free(a); free(r0); free(r1); free(qkv); free(att); free(del); free(tmp); goto done;
        }
        free(a); free(r0); a = r0 = NULL;

        nn_sgemm_nt(T2, 768, 256, r1, 256, e->qkv_w, 256, qkv, 768, e->qkv_b, 0);
        {
            struct dr_attn_ctx ac = { qkv, att, T2, 256, 4 };
            nn_parallel_for(T2, 16, dr_attn_worker, &ac);
        }
        nn_sgemm_nt(T2, 256, 256, att, 256, e->ao_w, 256, r1, 256, e->ao_b, 1);
        nn_layernorm(r1, r1, T2, 256, e->ln_w, e->ln_b, 1e-5f);

        nn_sgemm_nt(T2, DR_KEYS, 256, r1, 256, e->delta_w, 256, del, DR_KEYS, e->delta_b, 0);
        nn_sgemm_nt(T2, DR_TIMP, 256, r1, 256, e->timp_w, 256, tmp, DR_TIMP, e->timp_b, 0);
        for (size_t i = 0; i < (size_t)T2 * DR_KEYS; ++i) {
            drum_p_out[i] += dr_sig(z0[i] + del[i]);
            vel_p_out[i] += dr_sig(v0[i]);
        }
        for (size_t i = 0; i < (size_t)T2 * DR_TIMP; ++i)
            timp_p_out[i] += dr_sig(tmp[i]);

        /* Router: mean_t(r1) -> gate0(256->64) -> SiLU -> gate2(64->1) -> sigmoid */
        float rmean[256] = {0};
        for (int t = 0; t < T2; ++t) {
            const float *rt = r1 + (size_t)t * 256;
            for (int d = 0; d < 256; ++d) rmean[d] += rt[d];
        }
        float inv_t = 1.0f / (float)T2;
        for (int d = 0; d < 256; ++d) rmean[d] *= inv_t;
        float g64[64], g1[1];
        nn_sgemm_nt(1, 64, 256, rmean, 256, e->gate0_w, 256, g64, 64, e->gate0_b, 0);
        silu_inplace(g64, 64);
        nn_sgemm_nt(1, 1, 64, g64, 64, e->gate2_w, 64, g1, 1, e->gate2_b, 0);
        *router_out += (double)dr_sig(g1[0]);

        free(r1); free(qkv); free(att); free(del); free(tmp);
    }
    ok = 1;
done:
    free(c_emb); free(h0); free(z0); free(v0); free(cq_out);
    return ok;
}

/* =========================================================================
 * Peak picking & full drum transcription (matches drums/infer.py)
 * ========================================================================= */

struct dr_hit {
    double onset;
    int pitch;
    double vel;
    size_t seq;
};

static int cmp_dr_hit(const void *pa, const void *pb) {
    const struct dr_hit *a = (const struct dr_hit *)pa;
    const struct dr_hit *b = (const struct dr_hit *)pb;
    if (a->onset < b->onset) return -1;
    if (a->onset > b->onset) return 1;
    return (a->seq > b->seq) - (a->seq < b->seq);
}

static void pick_peaks(const float *prob, const float *vel_map, int T2, int L, int pitch_base,
                       float th, int gap, int is_timpani,
                       struct dr_hit **hits, size_t *count, size_t *cap) {
    int last[DR_KEYS];
    for (int l = 0; l < L; ++l) last[l] = -10;
    for (int t = 0; t < T2; ++t) {
        for (int l = 0; l < L; ++l) {
            float p = prob[(size_t)t * L + l];
            if (p < th) continue;
            float pl = t > 0 ? prob[(size_t)(t - 1) * L + l] : p;
            float pr = t + 1 < T2 ? prob[(size_t)(t + 1) * L + l] : p;
            if (p >= pl && p >= pr && (t - last[l] > gap - 1)) {
                last[l] = t;
                double onset = (double)t / 50.0;
                int pitch = pitch_base + l;
                if (is_timpani) {
                    int dup = 0;
                    for (size_t i = 0; i < *count; ++i) {
                        if ((*hits)[i].pitch == pitch && fabs((*hits)[i].onset - onset) <= 0.04) {
                            dup = 1; break;
                        }
                    }
                    if (dup) continue;
                }
                double v = is_timpani ? (double)p : (double)vel_map[(size_t)t * L + l];
                if (is_timpani) { if (v < 0.3) v = 0.3; if (v > 1.0) v = 1.0; }
                if (*count == *cap) {
                    size_t next = *cap ? *cap * 2 : 128;
                    struct dr_hit *g = (struct dr_hit *)realloc(*hits, next * sizeof(*g));
                    if (!g) return;
                    *hits = g; *cap = next;
                }
                (*hits)[(*count)++] = (struct dr_hit){ onset, pitch, v, *count };
            }
        }
    }
}

int drums_transcribe(const struct drums_model *m,
                     const float *audio_native, size_t n_frames, unsigned source_rate,
                     struct midi_note **notes_out, size_t *count_out,
                     struct drums_info *info) {
    *notes_out = NULL; *count_out = 0;
    if (info) memset(info, 0, sizeof(*info));
    if (!m || !audio_native || source_rate < DRUMS_MIN_SOURCE_RATE) return 1;

    float *x44 = NULL; size_t n44 = 0;
    if (!resample_mono(audio_native, n_frames, (double)source_rate, (double)DR_SR, &x44, &n44)) return 0;
    if (n44 < DR_SR / 10) { free(x44); return 1; }

    float *feats = NULL; int T = 0;
    if (!compute_drum_features(x44, n44, &feats, &T)) { free(x44); return 0; }
    free(x44);
    if (T < 2) { free(feats); return 1; }

    int T2 = T / 2;
    float *c_kit = (float *)malloc((size_t)T2 * DR_W * sizeof(float));
    float *z_kit = (float *)malloc((size_t)T2 * DR_KEYS * sizeof(float));
    float *v_kit = (float *)malloc((size_t)T2 * DR_KEYS * sizeof(float));
    float *drum_p = (float *)calloc((size_t)T2 * DR_KEYS, sizeof(float));
    float *timp_p = (float *)calloc((size_t)T2 * DR_TIMP, sizeof(float));
    float *vel_p = (float *)calloc((size_t)T2 * DR_KEYS, sizeof(float));
    int ok = 0;
    if (!c_kit || !z_kit || !v_kit || !drum_p || !timp_p || !vel_p) goto done;

    if (!drumnet_embed(&m->kit, feats, T, c_kit) || !drumnet_trunk(&m->kit, c_kit, T2, NULL, z_kit, v_kit)) goto done;
    for (size_t i = 0; i < (size_t)T2 * DR_KEYS; ++i) {
        z_kit[i] = dr_sig(z_kit[i]);
        v_kit[i] = dr_sig(v_kit[i]);
    }

    double router_sum = 0.0;
    for (int ei = 0; ei < DR_N_EXPERTS; ++ei) {
        if (!run_expert(&m->experts[ei], feats, T, drum_p, timp_p, vel_p, &router_sum)) goto done;
    }
    double router = router_sum / (double)DR_N_EXPERTS;
    float inv_e = 1.0f / (float)DR_N_EXPERTS;
    for (size_t i = 0; i < (size_t)T2 * DR_KEYS; ++i) { drum_p[i] *= inv_e; vel_p[i] *= inv_e; }
    for (size_t i = 0; i < (size_t)T2 * DR_TIMP; ++i) timp_p[i] *= inv_e;

    struct dr_hit *hits = NULL; size_t n_hits = 0, cap = 0;
    int use_orch = (router >= 0.5);
    if (!use_orch) {
        pick_peaks(z_kit, v_kit, T2, DR_KEYS, 27, 0.5f, 3, 0, &hits, &n_hits, &cap);
    } else {
        pick_peaks(drum_p, vel_p, T2, DR_KEYS, 27, 0.5f, 3, 0, &hits, &n_hits, &cap);
        pick_peaks(timp_p, NULL, T2, DR_TIMP, 41, 0.5f, 3, 1, &hits, &n_hits, &cap);
    }
    if (n_hits > 1) qsort(hits, n_hits, sizeof(*hits), cmp_dr_hit);

    struct midi_note *notes = n_hits ? (struct midi_note *)malloc(n_hits * sizeof(*notes)) : NULL;
    if (n_hits && !notes) { free(hits); goto done; }
    for (size_t i = 0; i < n_hits; ++i) {
        double on = rint(hits[i].onset * 1e4) / 1e4;
        double off = rint((hits[i].onset + 0.1) * 1e4) / 1e4;
        double vc = hits[i].vel;
        if (vc < 0.05) vc = 0.05;
        if (vc > 1.0) vc = 1.0;
        int vel = (int)rint(vc * 127.0);
        if (vel < 1) vel = 1;
        if (vel > 127) vel = 127;
        notes[i] = (struct midi_note){ on, off, hits[i].pitch, vel };
    }
    free(hits);
    *notes_out = notes;
    *count_out = n_hits;
    if (info) { info->router = router; info->used_orchestral = use_orch; info->hits = n_hits; }
    ok = 1;

done:
    free(feats); free(c_kit); free(z_kit); free(v_kit); free(drum_p); free(timp_p); free(vel_p);
    return ok;
}
