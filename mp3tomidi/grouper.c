/* Native port of Dettato's grouper/{front,model,core,decode,instruments}.py,
 * revision 51ade0f09f2272f4674166026582185d26baaeaf. See vendor/dettato/. */
#include "grouper.h"
#include "features.h"
#include "nn.h"
#include <float.h>
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

enum {
    GP_D = 176,
    GP_DEPTH = 7,
    GP_HEADS = 4,
    GP_HD = 44,
    GP_FF = 352,
    GP_EMB = 32,
    GP_K = 73,
    GP_HD_H = 10,
    GP_HD_SUS = 4,
    GP_HD_KT = 14,
    GP_HD_NFEAT = 150,
    GP_HD_HID = 160,
    GP_LC = 128,
    GP_LDEPTH = 6,
    GP_LNLANES = 96,
    GP_LTS = 8,
    GP_LEXP = 256,
    GP_S15_HID = 256,
    GP_S15_DIM = 368,
    GP_MAX_NOTES = 768
};

static const int GP_PMIX_OFF[14] = {
    -2, -1, 1, 2, -12, 12, -19, 19, -24, 24, -28, 28, -31, 31
};
static const int GP_LDIL[6] = { 1, 2, 4, 8, 1, 2 };
static const int GP_HD_K[10] = { -2, 0, 2, 4, 8, 12, 16, 24, 32, 48 };
static const int GP_HD_SHIFT[10] = { 0, 36, 57, 72, 84, 93, 101, 108, 114, 120 };

/* 73-instrument vocabulary + GM program + family bitmask (matches grouper/instruments.py). */
enum {
    FAM_KEYS = 1 << 0, FAM_PLUCKED = 1 << 1, FAM_MALLETS = 1 << 2,
    FAM_ORGAN = 1 << 3, FAM_REEDS = 1 << 4, FAM_BASS = 1 << 5,
    FAM_STRINGS = 1 << 6, FAM_SYNTH = 1 << 7, FAM_VOICE = 1 << 8,
    FAM_BRASS = 1 << 9, FAM_FLUTES = 1 << 10, FAM_PERC = 1 << 11,
    FAM_SFX = 1 << 12
};

struct inst_entry {
    const char *name;
    int program;
    unsigned fam;
};

static const struct inst_entry INST_TABLE[GP_K] = {
    {"piano", 0, FAM_KEYS}, {"electric_piano", 4, FAM_KEYS}, {"harpsichord", 6, FAM_KEYS},
    {"clavinet", 7, FAM_KEYS}, {"harp", 46, FAM_KEYS | FAM_PLUCKED}, {"celesta", 8, FAM_MALLETS | FAM_KEYS},
    {"glockenspiel", 9, FAM_MALLETS}, {"music_box", 10, FAM_MALLETS}, {"vibraphone", 11, FAM_MALLETS},
    {"marimba", 12, FAM_MALLETS}, {"xylophone", 13, FAM_MALLETS}, {"tubular_bells", 14, FAM_MALLETS},
    {"dulcimer", 15, FAM_PLUCKED | FAM_MALLETS}, {"kalimba", 108, FAM_MALLETS}, {"tinkle_bell", 112, FAM_MALLETS},
    {"steel_drums", 114, FAM_MALLETS}, {"organ", 16, FAM_ORGAN}, {"church_organ", 19, FAM_ORGAN},
    {"reed_organ", 20, FAM_ORGAN}, {"accordion", 21, FAM_ORGAN}, {"harmonica", 22, FAM_ORGAN | FAM_REEDS},
    {"acoustic_guitar", 24, FAM_PLUCKED}, {"electric_guitar", 26, FAM_PLUCKED}, {"sitar", 104, FAM_PLUCKED},
    {"banjo", 105, FAM_PLUCKED}, {"shamisen", 106, FAM_PLUCKED}, {"koto", 107, FAM_PLUCKED},
    {"double_bass", 32, FAM_BASS | FAM_STRINGS}, {"electric_bass", 33, FAM_BASS},
    {"synth_bass", 38, FAM_BASS | FAM_SYNTH}, {"violin", 40, FAM_STRINGS}, {"viola", 41, FAM_STRINGS},
    {"cello", 42, FAM_STRINGS}, {"string_ensemble", 44, FAM_STRINGS}, {"synth_strings", 50, FAM_STRINGS | FAM_SYNTH},
    {"voice", 52, FAM_VOICE}, {"synth_voice", 54, FAM_VOICE | FAM_SYNTH}, {"trumpet", 56, FAM_BRASS},
    {"trombone", 57, FAM_BRASS}, {"tuba", 58, FAM_BRASS}, {"french_horn", 60, FAM_BRASS},
    {"brass_section", 61, FAM_BRASS}, {"synth_brass", 62, FAM_BRASS | FAM_SYNTH}, {"soprano_sax", 64, FAM_REEDS},
    {"alto_sax", 65, FAM_REEDS}, {"tenor_sax", 66, FAM_REEDS}, {"baritone_sax", 67, FAM_REEDS},
    {"oboe", 68, FAM_REEDS}, {"english_horn", 69, FAM_REEDS}, {"bassoon", 70, FAM_REEDS},
    {"clarinet", 71, FAM_REEDS}, {"bagpipe", 109, FAM_REEDS}, {"shanai", 111, FAM_REEDS},
    {"piccolo", 72, FAM_FLUTES}, {"flute", 73, FAM_FLUTES}, {"recorder", 74, FAM_FLUTES},
    {"pan_flute", 75, FAM_FLUTES}, {"blown_bottle", 76, FAM_FLUTES}, {"shakuhachi", 77, FAM_FLUTES},
    {"whistle", 78, FAM_FLUTES}, {"ocarina", 79, FAM_FLUTES}, {"orchestra_hit", 55, FAM_SYNTH},
    {"synth_lead", 80, FAM_SYNTH}, {"synth_pad", 88, FAM_SYNTH}, {"synth_fx", 96, FAM_SYNTH},
    {"timpani", 47, FAM_PERC}, {"agogo", 113, FAM_PERC}, {"woodblock", 115, FAM_PERC},
    {"taiko", 116, FAM_PERC}, {"melodic_tom", 117, FAM_PERC}, {"synth_drum", 118, FAM_PERC | FAM_SYNTH},
    {"reverse_cymbal", 119, FAM_PERC}, {"sound_effect", 120, FAM_SFX}
};

struct gp_lblock {
    float *dw_w, *dw_b;     /* [7, 128], [128] */
    float *pm;              /* [14, 128] */
    float *ln_w, *ln_b;     /* [128] */
    float *pw1_w, *pw1_b;   /* [256, 128], [256] */
    float *pw2_w, *pw2_b;   /* [128, 256], [128] */
    float *gamma;           /* [128] */
    int dil;
};

struct gp_lattn {
    float *ln_w, *ln_b;
    float *qkv_w, *qkv_b;   /* [384, 128], [384] */
    float *out_w, *out_b;   /* [128, 128], [128] */
    float *gamma;           /* [128] */
    float *rel_bias;        /* [4, 191] */
};

struct gp_tblock {
    float *ln1_w, *ln1_b;
    float *qkv_w, *qkv_b;   /* [528, 176], [528] */
    float *o_w, *o_b;       /* [176, 176], [176] */
    float *ln2_w, *ln2_b;
    float *ff0_w, *ff0_b;   /* [352, 176], [352] */
    float *ff2_w, *ff2_b;   /* [176, 352], [176] */
};

struct grouper_model {
    /* HDemix */
    float *hd_prior;        /* [10] */
    float *hd0_w, *hd0_b;   /* [160, 150], [160] */
    float *hd2_w, *hd2_b;   /* [176, 160], [176] */
    /* Prof */
    float *pr0_w, *pr0_b;   /* [64, 36], [64] */
    float *pr2_w, *pr2_b;   /* [176, 64], [176] */
    /* LaneFront */
    float *ls_w, *ls_b;     /* [128, 8, 3, 9], [128] */
    float *lo_w, *lo_b;     /* [128, 4], [128] */
    struct gp_lblock lblocks[GP_LDEPTH];
    struct gp_lattn lattn[2]; /* after block 2 and block 5 */
    float *lr_w, *lr_b;     /* [176, 256], [176] */
    /* s15 taps + pitch + scalar feat */
    float *s15_ln_w, *s15_ln_b; /* [368] */
    float *s15_0_w, *s15_0_b;   /* [256, 1104], [256] */
    float *s15_2_w, *s15_2_b;   /* [176, 256], [176] */
    float *pitch_emb;           /* [128, 176] */
    float *ft0_w, *ft0_b;       /* [64, 11], [64] */
    float *ft2_w, *ft2_b;       /* [176, 64], [176] */
    /* Transformer */
    float *ln_in_w, *ln_in_b;
    struct gp_tblock blocks[GP_DEPTH];
    float *ln_out_w, *ln_out_b;
    /* Heads */
    float *h_inst_w, *h_inst_b; /* [73, 176], [73] */
    float *h_emb_w, *h_emb_b;   /* [32, 176], [32] */
    float *th0_w, *th0_b;       /* [176, 182], [176] */
    float *th2_w, *th2_b;       /* [176, 176], [176] */
    float *th4_w, *th4_b;       /* [73, 176], [73] */
};

static float *gp_transpose(float *src, int rows, int cols) {
    if (!src) return NULL;
    float *dst = (float *)malloc((size_t)rows * cols * sizeof(float));
    if (!dst) { free(src); return NULL; }
    for (int r = 0; r < rows; ++r)
        for (int c = 0; c < cols; ++c)
            dst[(size_t)c * rows + r] = src[(size_t)r * cols + c];
    free(src);
    return dst;
}

struct grouper_model *grouper_load(const struct vtwt_file *wf) {
    struct grouper_model *m = (struct grouper_model *)calloc(1, sizeof(*m));
    if (!m) return NULL;
    char name[VTWT_NAME_MAX];

    uint32_t s_d[1] = {GP_D}, s_lc[1] = {GP_LC}, s_368[1] = {368};
    uint32_t s10[1] = {10}, s160[1] = {160}, s64[1] = {64}, s256[1] = {256}, s352[1] = {352}, s73[1] = {73}, s32[1] = {32};
    uint32_t sh0[2] = {160, 150}, sh2[2] = {176, 160};
    uint32_t sp0[2] = {64, 36}, sp2[2] = {176, 64};
    uint32_t slo[4] = {128, 4, 1, 1}, slr[2] = {176, 256};
    uint32_t ss0[2] = {256, 1104}, ss2[2] = {176, 256};
    uint32_t spe[2] = {128, 176}, sft0[2] = {64, 11}, sft2[2] = {176, 64};

    m->hd_prior = vtwt_read_f32(wf, "hd.prior", 1, s10);
    m->hd0_w = vtwt_read_f32(wf, "hd.enc.0.weight", 2, sh0);
    m->hd0_b = vtwt_read_f32(wf, "hd.enc.0.bias", 1, s160);
    m->hd2_w = vtwt_read_f32(wf, "hd.enc.2.weight", 2, sh2);
    m->hd2_b = vtwt_read_f32(wf, "hd.enc.2.bias", 1, s_d);

    m->pr0_w = vtwt_read_f32(wf, "prof.net.0.weight", 2, sp0);
    m->pr0_b = vtwt_read_f32(wf, "prof.net.0.bias", 1, s64);
    m->pr2_w = vtwt_read_f32(wf, "prof.net.2.weight", 2, sp2);
    m->pr2_b = vtwt_read_f32(wf, "prof.net.2.bias", 1, s_d);

    m->ls_w = vtwt_read_conv2d_nhwc(wf, "lanes.stem.weight", GP_LC, HCQT_CHANNELS, GP_LTS, 3);
    m->ls_b = vtwt_read_f32(wf, "lanes.stem.bias", 1, s_lc);
    m->lo_w = vtwt_read_f32(wf, "lanes.occ.weight", 4, slo);
    m->lo_b = vtwt_read_f32(wf, "lanes.occ.bias", 1, s_lc);
    m->lr_w = vtwt_read_f32(wf, "lanes.read.weight", 2, slr);
    m->lr_b = vtwt_read_f32(wf, "lanes.read.bias", 1, s_d);

    if (!m->hd_prior || !m->hd0_w || !m->hd0_b || !m->hd2_w || !m->hd2_b ||
        !m->pr0_w || !m->pr0_b || !m->pr2_w || !m->pr2_b ||
        !m->ls_w || !m->ls_b || !m->lo_w || !m->lo_b || !m->lr_w || !m->lr_b) goto fail;

    for (int i = 0; i < GP_LDEPTH; ++i) {
        struct gp_lblock *b = &m->lblocks[i];
        b->dil = GP_LDIL[i];
        uint32_t sdw[4] = {128, 1, 7, 1}, spm[2] = {128, 14}, sp1[4] = {256, 128, 1, 1}, sp2w[4] = {128, 256, 1, 1};
        snprintf(name, sizeof(name), "lanes.blocks.%d.dw_t.weight", i); b->dw_w = gp_transpose(vtwt_read_f32(wf, name, 4, sdw), 128, 7);
        snprintf(name, sizeof(name), "lanes.blocks.%d.dw_t.bias", i);   b->dw_b = vtwt_read_f32(wf, name, 1, s_lc);
        snprintf(name, sizeof(name), "lanes.blocks.%d.pm.taps", i);     b->pm = gp_transpose(vtwt_read_f32(wf, name, 2, spm), 128, 14);
        snprintf(name, sizeof(name), "lanes.blocks.%d.norm.w", i);      b->ln_w = vtwt_read_f32(wf, name, 1, s_lc);
        snprintf(name, sizeof(name), "lanes.blocks.%d.norm.b", i);      b->ln_b = vtwt_read_f32(wf, name, 1, s_lc);
        snprintf(name, sizeof(name), "lanes.blocks.%d.pw1.weight", i);  b->pw1_w = vtwt_read_f32(wf, name, 4, sp1);
        snprintf(name, sizeof(name), "lanes.blocks.%d.pw1.bias", i);    b->pw1_b = vtwt_read_f32(wf, name, 1, s256);
        snprintf(name, sizeof(name), "lanes.blocks.%d.pw2.weight", i);  b->pw2_w = vtwt_read_f32(wf, name, 4, sp2w);
        snprintf(name, sizeof(name), "lanes.blocks.%d.pw2.bias", i);    b->pw2_b = vtwt_read_f32(wf, name, 1, s_lc);
        snprintf(name, sizeof(name), "lanes.blocks.%d.gamma", i);       b->gamma = vtwt_read_f32(wf, name, 1, s_lc);
        if (!b->dw_w || !b->dw_b || !b->pm || !b->ln_w || !b->ln_b ||
            !b->pw1_w || !b->pw1_b || !b->pw2_w || !b->pw2_b || !b->gamma) goto fail;
    }

    static const int attn_ids[2] = {2, 5};
    for (int k = 0; k < 2; ++k) {
        struct gp_lattn *a = &m->lattn[k];
        int id = attn_ids[k];
        uint32_t sqkv[2] = {384, 128}, sqkvb[1] = {384}, sout[2] = {128, 128}, srb[2] = {4, 191};
        snprintf(name, sizeof(name), "lanes.attn.%d.ln.weight", id);  a->ln_w = vtwt_read_f32(wf, name, 1, s_lc);
        snprintf(name, sizeof(name), "lanes.attn.%d.ln.bias", id);    a->ln_b = vtwt_read_f32(wf, name, 1, s_lc);
        snprintf(name, sizeof(name), "lanes.attn.%d.qkv.weight", id); a->qkv_w = vtwt_read_f32(wf, name, 2, sqkv);
        snprintf(name, sizeof(name), "lanes.attn.%d.qkv.bias", id);   a->qkv_b = vtwt_read_f32(wf, name, 1, sqkvb);
        snprintf(name, sizeof(name), "lanes.attn.%d.out.weight", id); a->out_w = vtwt_read_f32(wf, name, 2, sout);
        snprintf(name, sizeof(name), "lanes.attn.%d.out.bias", id);   a->out_b = vtwt_read_f32(wf, name, 1, s_lc);
        snprintf(name, sizeof(name), "lanes.attn.%d.gamma", id);      a->gamma = vtwt_read_f32(wf, name, 1, s_lc);
        snprintf(name, sizeof(name), "lanes.attn.%d.rel_bias", id);   a->rel_bias = vtwt_read_f32(wf, name, 2, srb);
        if (!a->ln_w || !a->ln_b || !a->qkv_w || !a->qkv_b || !a->out_w || !a->out_b || !a->gamma || !a->rel_bias) goto fail;
    }

    m->s15_ln_w = vtwt_read_f32(wf, "s15_ln.weight", 1, s_368);
    m->s15_ln_b = vtwt_read_f32(wf, "s15_ln.bias", 1, s_368);
    m->s15_0_w = vtwt_read_f32(wf, "s15_net.0.weight", 2, ss0);
    m->s15_0_b = vtwt_read_f32(wf, "s15_net.0.bias", 1, s256);
    m->s15_2_w = vtwt_read_f32(wf, "s15_net.2.weight", 2, ss2);
    m->s15_2_b = vtwt_read_f32(wf, "s15_net.2.bias", 1, s_d);
    m->pitch_emb = vtwt_read_f32(wf, "pitch_emb.weight", 2, spe);
    m->ft0_w = vtwt_read_f32(wf, "feat.0.weight", 2, sft0);
    m->ft0_b = vtwt_read_f32(wf, "feat.0.bias", 1, s64);
    m->ft2_w = vtwt_read_f32(wf, "feat.2.weight", 2, sft2);
    m->ft2_b = vtwt_read_f32(wf, "feat.2.bias", 1, s_d);
    m->ln_in_w = vtwt_read_f32(wf, "ln_in.weight", 1, s_d);
    m->ln_in_b = vtwt_read_f32(wf, "ln_in.bias", 1, s_d);
    m->ln_out_w = vtwt_read_f32(wf, "ln_out.weight", 1, s_d);
    m->ln_out_b = vtwt_read_f32(wf, "ln_out.bias", 1, s_d);
    if (!m->s15_ln_w || !m->s15_ln_b || !m->s15_0_w || !m->s15_0_b || !m->s15_2_w || !m->s15_2_b ||
        !m->pitch_emb || !m->ft0_w || !m->ft0_b || !m->ft2_w || !m->ft2_b ||
        !m->ln_in_w || !m->ln_in_b || !m->ln_out_w || !m->ln_out_b) goto fail;

    for (int i = 0; i < GP_DEPTH; ++i) {
        struct gp_tblock *b = &m->blocks[i];
        uint32_t sq[2] = {528, 176}, sqb[1] = {528}, so[2] = {176, 176}, sf0[2] = {352, 176}, sf2[2] = {176, 352};
        snprintf(name, sizeof(name), "blocks.%d.ln1.weight", i);  b->ln1_w = vtwt_read_f32(wf, name, 1, s_d);
        snprintf(name, sizeof(name), "blocks.%d.ln1.bias", i);    b->ln1_b = vtwt_read_f32(wf, name, 1, s_d);
        snprintf(name, sizeof(name), "blocks.%d.qkv.weight", i);  b->qkv_w = vtwt_read_f32(wf, name, 2, sq);
        snprintf(name, sizeof(name), "blocks.%d.qkv.bias", i);    b->qkv_b = vtwt_read_f32(wf, name, 1, sqb);
        snprintf(name, sizeof(name), "blocks.%d.o.weight", i);    b->o_w = vtwt_read_f32(wf, name, 2, so);
        snprintf(name, sizeof(name), "blocks.%d.o.bias", i);      b->o_b = vtwt_read_f32(wf, name, 1, s_d);
        snprintf(name, sizeof(name), "blocks.%d.ln2.weight", i);  b->ln2_w = vtwt_read_f32(wf, name, 1, s_d);
        snprintf(name, sizeof(name), "blocks.%d.ln2.bias", i);    b->ln2_b = vtwt_read_f32(wf, name, 1, s_d);
        snprintf(name, sizeof(name), "blocks.%d.ff.0.weight", i); b->ff0_w = vtwt_read_f32(wf, name, 2, sf0);
        snprintf(name, sizeof(name), "blocks.%d.ff.0.bias", i);   b->ff0_b = vtwt_read_f32(wf, name, 1, s352);
        snprintf(name, sizeof(name), "blocks.%d.ff.2.weight", i); b->ff2_w = vtwt_read_f32(wf, name, 2, sf2);
        snprintf(name, sizeof(name), "blocks.%d.ff.2.bias", i);   b->ff2_b = vtwt_read_f32(wf, name, 1, s_d);
        if (!b->ln1_w || !b->ln1_b || !b->qkv_w || !b->qkv_b || !b->o_w || !b->o_b ||
            !b->ln2_w || !b->ln2_b || !b->ff0_w || !b->ff0_b || !b->ff2_w || !b->ff2_b) goto fail;
    }

    uint32_t shi[2] = {73, 176}, she[2] = {32, 176}, st0[2] = {176, 182}, st2[2] = {176, 176}, st4[2] = {73, 176};
    m->h_inst_w = vtwt_read_f32(wf, "heads.inst.weight", 2, shi);
    m->h_inst_b = vtwt_read_f32(wf, "heads.inst.bias", 1, s73);
    m->h_emb_w = vtwt_read_f32(wf, "heads.emb.weight", 2, she);
    m->h_emb_b = vtwt_read_f32(wf, "heads.emb.bias", 1, s32);
    m->th0_w = vtwt_read_f32(wf, "heads.th.0.weight", 2, st0);
    m->th0_b = vtwt_read_f32(wf, "heads.th.0.bias", 1, s_d);
    m->th2_w = vtwt_read_f32(wf, "heads.th.2.weight", 2, st2);
    m->th2_b = vtwt_read_f32(wf, "heads.th.2.bias", 1, s_d);
    m->th4_w = vtwt_read_f32(wf, "heads.th.4.weight", 2, st4);
    m->th4_b = vtwt_read_f32(wf, "heads.th.4.bias", 1, s73);
    if (!m->h_inst_w || !m->h_inst_b || !m->h_emb_w || !m->h_emb_b ||
        !m->th0_w || !m->th0_b || !m->th2_w || !m->th2_b || !m->th4_w || !m->th4_b) goto fail;

    return m;
fail:
    grouper_free(m);
    return NULL;
}

void grouper_free(struct grouper_model *m) {
    if (!m) return;
    free(m->hd_prior); free(m->hd0_w); free(m->hd0_b); free(m->hd2_w); free(m->hd2_b);
    free(m->pr0_w); free(m->pr0_b); free(m->pr2_w); free(m->pr2_b);
    free(m->ls_w); free(m->ls_b); free(m->lo_w); free(m->lo_b); free(m->lr_w); free(m->lr_b);
    for (int i = 0; i < GP_LDEPTH; ++i) {
        free(m->lblocks[i].dw_w); free(m->lblocks[i].dw_b); free(m->lblocks[i].pm);
        free(m->lblocks[i].ln_w); free(m->lblocks[i].ln_b);
        free(m->lblocks[i].pw1_w); free(m->lblocks[i].pw1_b);
        free(m->lblocks[i].pw2_w); free(m->lblocks[i].pw2_b);
        free(m->lblocks[i].gamma);
    }
    for (int i = 0; i < 2; ++i) {
        free(m->lattn[i].ln_w); free(m->lattn[i].ln_b);
        free(m->lattn[i].qkv_w); free(m->lattn[i].qkv_b);
        free(m->lattn[i].out_w); free(m->lattn[i].out_b);
        free(m->lattn[i].gamma); free(m->lattn[i].rel_bias);
    }
    free(m->s15_ln_w); free(m->s15_ln_b); free(m->s15_0_w); free(m->s15_0_b); free(m->s15_2_w); free(m->s15_2_b);
    free(m->pitch_emb); free(m->ft0_w); free(m->ft0_b); free(m->ft2_w); free(m->ft2_b);
    free(m->ln_in_w); free(m->ln_in_b); free(m->ln_out_w); free(m->ln_out_b);
    for (int i = 0; i < GP_DEPTH; ++i) {
        free(m->blocks[i].ln1_w); free(m->blocks[i].ln1_b);
        free(m->blocks[i].qkv_w); free(m->blocks[i].qkv_b);
        free(m->blocks[i].o_w); free(m->blocks[i].o_b);
        free(m->blocks[i].ln2_w); free(m->blocks[i].ln2_b);
        free(m->blocks[i].ff0_w); free(m->blocks[i].ff0_b);
        free(m->blocks[i].ff2_w); free(m->blocks[i].ff2_b);
    }
    free(m->h_inst_w); free(m->h_inst_b); free(m->h_emb_w); free(m->h_emb_b);
    free(m->th0_w); free(m->th0_b); free(m->th2_w); free(m->th2_b); free(m->th4_w); free(m->th4_b);
    free(m);
}

void grouped_tracks_free(struct grouped_track *tracks, size_t n_tracks) {
    if (!tracks) return;
    for (size_t i = 0; i < n_tracks; ++i) free(tracks[i].notes);
    free(tracks);
}

/* =========================================================================
 * Helper math + front-end PCEN + NoteNet window forward
 * ========================================================================= */

static inline int gp_clamp(int v, int lo, int hi) {
    return v < lo ? lo : (v > hi ? hi : v);
}

static void fft_radix2_f32(float *re, float *im, int n, int inverse) {
    for (int i = 1, j = 0; i < n; ++i) {
        int bit = n >> 1;
        while (j & bit) { j ^= bit; bit >>= 1; }
        j ^= bit;
        if (i < j) {
            float tr = re[i]; re[i] = re[j]; re[j] = tr;
            float ti = im[i]; im[i] = im[j]; im[j] = ti;
        }
    }
    const double tau = 6.2831853071795864769;
    double sign = inverse ? 1.0 : -1.0;
    for (int span = 2; span <= n; span <<= 1) {
        double ang = sign * tau / (double)span;
        float sr = (float)cos(ang), si = (float)sin(ang);
        int half = span >> 1;
        for (int start = 0; start < n; start += span) {
            float wr = 1.0f, wi = 0.0f;
            for (int j = start; j < start + half; ++j) {
                int k = j + half;
                float r = wr * re[k] - wi * im[k];
                float ii = wi * re[k] + wr * im[k];
                re[k] = re[j] - r; im[k] = im[j] - ii;
                re[j] += r; im[j] += ii;
                float nr = wr * sr - wi * si;
                wi = wi * sr + wr * si;
                wr = nr;
            }
        }
    }
    if (inverse) {
        float inv = 1.0f / (float)n;
        for (int i = 0; i < n; ++i) { re[i] *= inv; im[i] *= inv; }
    }
}

struct pcen_ctx {
    float *X_ct_f;
    const float *kre, *kim;
    int T, nfft;
};

static void pcen_worker(int start, int end, void *arg) {
    struct pcen_ctx *c = (struct pcen_ctx *)arg;
    int T = c->T, n = c->nfft;
    const float sqrt2 = 1.414213562373095f;
    float *E = (float *)malloc((size_t)T * sizeof(float));
    float *re = (float *)malloc((size_t)n * sizeof(float));
    float *im = (float *)malloc((size_t)n * sizeof(float));
    if (!E || !re || !im) { free(E); free(re); free(im); return; }

    for (int job = start; job < end; ++job) {
        int ch = job / HCQT_BINS;
        int b = job % HCQT_BINS;
        float *Xc = c->X_ct_f + (size_t)ch * (size_t)T * HCQT_BINS;
        memset(re, 0, (size_t)n * sizeof(float));
        memset(im, 0, (size_t)n * sizeof(float));
        for (int t = 0; t < T; ++t) {
            float e = expf(Xc[(size_t)t * HCQT_BINS + b]);
            E[t] = e;
            re[t] = e;
        }
        fft_radix2_f32(re, im, n, 0);
        for (int k = 0; k < n; ++k) {
            float ar = re[k], ai = im[k];
            re[k] = ar * c->kre[k] - ai * c->kim[k];
            im[k] = ar * c->kim[k] + ai * c->kre[k];
        }
        fft_radix2_f32(re, im, n, 1);
        for (int t = 0; t < T; ++t) {
            float m = re[t] > 0.0f ? re[t] : 0.0f;
            float out = sqrtf(E[t] / powf(1e-6f + m, 0.98f) + 2.0f) - sqrt2;
            Xc[(size_t)t * HCQT_BINS + b] = logf(out + 1e-4f);
        }
    }
    free(E); free(re); free(im);
}

static void pcen_and_standardise(float *X_ct_f, int T) {
    const int K = 200;
    const float s = 0.025f;
    int n = 1;
    while (n < T + K) n <<= 1;
    float *kre = (float *)calloc((size_t)n, sizeof(float));
    float *kim = (float *)calloc((size_t)n, sizeof(float));
    if (!kre || !kim) { free(kre); free(kim); return; }
    for (int i = 0; i < K; ++i) kre[i] = s * powf(1.0f - s, (float)i);
    fft_radix2_f32(kre, kim, n, 0);

    struct pcen_ctx pctx = { X_ct_f, kre, kim, T, n };
    nn_parallel_for(HCQT_CHANNELS * HCQT_BINS, 16, pcen_worker, &pctx);
    free(kre); free(kim);

    for (int ch = 0; ch < HCQT_CHANNELS; ++ch) {
        float *Xc = X_ct_f + (size_t)ch * (size_t)T * HCQT_BINS;
        size_t n_ch = (size_t)T * HCQT_BINS;
        float mx = Xc[0];
        for (size_t i = 1; i < n_ch; ++i) if (Xc[i] > mx) mx = Xc[i];
        float thr = mx - 12.0f;
        double sum = 0.0;
        size_t cnt = 0;
        for (size_t i = 0; i < n_ch; ++i) {
            if (Xc[i] > thr) { sum += Xc[i]; cnt++; }
        }
        double denom = cnt > 0 ? (double)cnt : 1.0;
        double mu = sum / denom;
        double var = 0.0;
        for (size_t i = 0; i < n_ch; ++i) {
            if (Xc[i] > thr) { double d = Xc[i] - mu; var += d * d; }
        }
        double sd = sqrt(var / denom);
        if (sd < 0.5) sd = 0.5;
        float fmu = (float)mu, inv_sd = (float)(1.0 / sd);
        for (size_t i = 0; i < n_ch; ++i) Xc[i] = (Xc[i] - fmu) * inv_sd;
    }
}

/* LaneFront LBlock (same as LaneNet LaneBlock but c=128 and LayerNorm eps=1e-6) */
static void run_gp_lblock(const struct gp_lblock *blk, float *Y, int Tq,
                          float *buf_y, float *buf_z, float *buf_mid) {
    const int P = GP_LNLANES, C = GP_LC;
    /* dw_t (7x1 dilated along Tq) */
    for (int t = 0; t < Tq; ++t) {
        for (int p = 0; p < P; ++p) {
            float *dst = buf_y + ((size_t)t * P + p) * C;
            memcpy(dst, blk->dw_b, C * sizeof(float));
            for (int k = 0; k < 7; ++k) {
                int st = t + (k - 3) * blk->dil;
                if (st < 0 || st >= Tq) continue;
                const float *src = Y + ((size_t)st * P + p) * C;
                const float *wk = blk->dw_w + k * C;
                for (int c = 0; c < C; ++c) dst[c] += src[c] * wk[c];
            }
        }
    }
    /* y + pm(y) -> buf_z */
    for (int t = 0; t < Tq; ++t) {
        const float *yt = buf_y + (size_t)t * P * C;
        float *zt = buf_z + (size_t)t * P * C;
        for (int p = 0; p < P; ++p) {
            float *dst = zt + (size_t)p * C;
            memcpy(dst, yt + (size_t)p * C, C * sizeof(float));
            for (int k = 0; k < 14; ++k) {
                int j = p + GP_PMIX_OFF[k];
                if (j < 0 || j >= P) continue;
                const float *src = yt + (size_t)j * C;
                const float *tk = blk->pm + k * C;
                for (int c = 0; c < C; ++c) dst[c] += src[c] * tk[c];
            }
        }
    }
    int M = Tq * P;
    nn_layernorm(buf_z, buf_z, M, C, blk->ln_w, blk->ln_b, 1e-6f);
    nn_sgemm_nt(M, GP_LEXP, C, buf_z, C, blk->pw1_w, C, buf_mid, GP_LEXP, blk->pw1_b, 0);
    nn_gelu_inplace(buf_mid, (size_t)M * GP_LEXP);
    nn_sgemm_nt(M, C, GP_LEXP, buf_mid, GP_LEXP, blk->pw2_w, GP_LEXP, buf_z, C, blk->pw2_b, 0);
    for (int i = 0; i < M; ++i) {
        float *yi = Y + (size_t)i * C;
        const float *zi = buf_z + (size_t)i * C;
        for (int c = 0; c < C; ++c) yi[c] += zi[c] * blk->gamma[c];
    }
}

struct gp_lattn_ctx {
    const float *qkv, *rel_bias;
    float *out;
    int Tq;
};
static void gp_lattn_worker(int start, int end, void *arg) {
    struct gp_lattn_ctx *ctx = (struct gp_lattn_ctx *)arg;
    const int P = GP_LNLANES, C = GP_LC, H = 4, D = 32;
    const float scale = 1.0f / sqrtf((float)D);
    float scores[GP_LNLANES];
    for (int t = start; t < end; ++t) {
        const float *qt = ctx->qkv + (size_t)t * P * 3 * C;
        float *ot = ctx->out + (size_t)t * P * C;
        for (int h = 0; h < H; ++h) {
            const float *rb = ctx->rel_bias + h * (2 * P - 1);
            for (int qi = 0; qi < P; ++qi) {
                const float *qv = qt + (size_t)qi * 3 * C + h * D;
                float mx = -1e30f;
                for (int ki = 0; ki < P; ++ki) {
                    const float *kv = qt + (size_t)ki * 3 * C + C + h * D;
                    float dot = 0.0f;
                    for (int d = 0; d < D; ++d) dot += qv[d] * kv[d];
                    float s = dot * scale + rb[ki - qi + (P - 1)];
                    scores[ki] = s;
                    if (s > mx) mx = s;
                }
                float se = 0.0f;
                for (int ki = 0; ki < P; ++ki) { scores[ki] = expf(scores[ki] - mx); se += scores[ki]; }
                float inv = 1.0f / se;
                float *dst = ot + (size_t)qi * C + h * D;
                memset(dst, 0, D * sizeof(float));
                for (int ki = 0; ki < P; ++ki) {
                    float w = scores[ki] * inv;
                    const float *vv = qt + (size_t)ki * 3 * C + 2 * C + h * D;
                    for (int d = 0; d < D; ++d) dst[d] += w * vv[d];
                }
            }
        }
    }
}

static void run_gp_lattn(const struct gp_lattn *a, float *Y, int Tq,
                         float *buf_h, float *buf_qkv, float *buf_o) {
    int M = Tq * GP_LNLANES;
    nn_layernorm(Y, buf_h, M, GP_LC, a->ln_w, a->ln_b, 1e-5f);
    nn_sgemm_nt(M, 3 * GP_LC, GP_LC, buf_h, GP_LC, a->qkv_w, GP_LC, buf_qkv, 3 * GP_LC, a->qkv_b, 0);
    struct gp_lattn_ctx ctx = { buf_qkv, a->rel_bias, buf_h, Tq };
    nn_parallel_for(Tq, 4, gp_lattn_worker, &ctx);
    nn_sgemm_nt(M, GP_LC, GP_LC, buf_h, GP_LC, a->out_w, GP_LC, buf_o, GP_LC, a->out_b, 0);
    for (int i = 0; i < M; ++i) {
        float *yi = Y + (size_t)i * GP_LC;
        const float *oi = buf_o + (size_t)i * GP_LC;
        for (int c = 0; c < GP_LC; ++c) yi[c] += oi[c] * a->gamma[c];
    }
}

/* Run NoteNet on one 24 s window (audio length L = 25.5 s = 408000 samples, N notes >= 4).
 * Outputs:
 *   probs_out [N, 73] (softmax probabilities)
 *   emb_out   [N, 32] (L2-normalized embeddings)
 *   h_out     [N, 176] (ln_out features) */
static int run_notenet_window(const struct grouper_model *m,
                              const float *win_audio, int audio_len,
                              const float *win_notes12, /* [N, 12] */
                              const float *win_feat3,   /* [N, 3 * 368] */
                              int N,
                              float *probs_out, float *emb_out, float *h_out) {
    int T = audio_len / HCQT_HOP;
    int Tq = T / GP_LTS;
    float *X_ctf = (float *)malloc((size_t)HCQT_CHANNELS * T * HCQT_BINS * sizeof(float));
    float *P_net = (float *)malloc((size_t)HCQT_EXTENDED * T * sizeof(float));
    float *X_nhwc = (float *)malloc((size_t)T * HCQT_BINS * HCQT_CHANNELS * sizeof(float));
    float *tok = (float *)calloc((size_t)N * GP_D, sizeof(float));
    int ok = 0;
    if (!X_ctf || !P_net || !X_nhwc || !tok) goto fail_early;

    /* 1. Front: HCQT + PCEN + standardise */
    compute_hcqt_with_power(win_audio, audio_len, X_ctf, P_net);
    pcen_and_standardise(X_ctf, T);

    /* Transpose X_ctf [9, T, 288] -> X_nhwc [T, 288, 9] */
    for (int t = 0; t < T; ++t) {
        float *dst_t = X_nhwc + (size_t)t * HCQT_BINS * HCQT_CHANNELS;
        for (int b = 0; b < HCQT_BINS; ++b) {
            float *p = dst_t + b * HCQT_CHANNELS;
            for (int ch = 0; ch < HCQT_CHANNELS; ++ch)
                p[ch] = X_ctf[((size_t)ch * T + t) * HCQT_BINS + b];
        }
    }

    /* 2. pitch_emb + feat MLP */
    {
        float *sc11 = (float *)malloc((size_t)N * 11 * sizeof(float));
        float *mid64 = (float *)malloc((size_t)N * 64 * sizeof(float));
        if (!sc11 || !mid64) { free(sc11); free(mid64); goto fail_early; }
        for (int i = 0; i < N; ++i) {
            const float *nt = win_notes12 + (size_t)i * 12;
            int pi = gp_clamp((int)rint(nt[2]), 0, 127);
            memcpy(tok + (size_t)i * GP_D, m->pitch_emb + (size_t)pi * GP_D, GP_D * sizeof(float));
            float dur = nt[1] - nt[0];
            if (dur < 0.01f) dur = 0.01f;
            float *s = sc11 + (size_t)i * 11;
            s[0] = logf(dur);
            for (int k = 0; k < 9; ++k) s[1 + k] = nt[3 + k];
            s[10] = nt[2] / 64.0f - 1.0f;
        }
        nn_sgemm_nt(N, 64, 11, sc11, 11, m->ft0_w, 11, mid64, 64, m->ft0_b, 0);
        nn_gelu_inplace(mid64, (size_t)N * 64);
        nn_sgemm_nt(N, GP_D, 64, mid64, 64, m->ft2_w, 64, tok, GP_D, m->ft2_b, 1);
        free(sc11); free(mid64);
    }

    /* 3. HDemix */
    {
        float pi_w[GP_HD_H];
        for (int h = 0; h < GP_HD_H; ++h) pi_w[h] = log1pf(expf(m->hd_prior[h]));
        int T1 = T + 1;
        float *occ = (float *)calloc((size_t)HCQT_EXTENDED * T1, sizeof(float));
        int *f_on = (int *)malloc((size_t)N * sizeof(int));
        int *f_off = (int *)malloc((size_t)N * sizeof(int));
        int *lane = (int *)malloc((size_t)N * sizeof(int));
        float *hd_in = (float *)malloc((size_t)N * GP_HD_NFEAT * sizeof(float));
        float *hd_mid = (float *)malloc((size_t)N * GP_HD_HID * sizeof(float));
        if (!occ || !f_on || !f_off || !lane || !hd_in || !hd_mid) {
            free(occ); free(f_on); free(f_off); free(lane); free(hd_in); free(hd_mid);
            goto fail_early;
        }
        for (int i = 0; i < N; ++i) {
            const float *nt = win_notes12 + (size_t)i * 12;
            int a = gp_clamp((int)rint(((double)nt[0] + 0.5) * 100.0), 0, T - 1);
            int b = (int)rint(((double)nt[1] + 0.5) * 100.0);
            if (b > T) b = T;
            if (b < a + 1) b = a + 1;
            int ln = gp_clamp((int)rint(nt[2]) - 21, 0, 87);
            f_on[i] = a; f_off[i] = b; lane[i] = ln;
            for (int h = 0; h < GP_HD_H; ++h) {
                int bin = 3 * ln + 36 + GP_HD_SHIFT[h];
                if (bin < HCQT_EXTENDED) {
                    occ[(size_t)bin * T1 + a] += pi_w[h];
                    occ[(size_t)bin * T1 + b] -= pi_w[h];
                }
            }
        }
        for (int bin = 0; bin < HCQT_EXTENDED; ++bin) {
            float *row = occ + (size_t)bin * T1;
            double acc = 0.0;
            for (int t = 0; t < T; ++t) { acc += row[t]; row[t] = (float)acc; }
        }
        static const float sus_fr[4] = {0.25f, 0.5f, 0.75f, 0.95f};
        for (int i = 0; i < N; ++i) {
            int a = f_on[i], b = f_off[i], ln = lane[i];
            float dur = (float)(b - a);
            int tk[GP_HD_KT];
            for (int k = 0; k < 10; ++k) tk[k] = gp_clamp(a + GP_HD_K[k], 0, T - 1);
            for (int k = 0; k < 4; ++k) tk[10 + k] = gp_clamp(a + (int)(dur * sus_fr[k]), 0, T - 1);
            float lE[GP_HD_H * GP_HD_KT];
            float valid_b[GP_HD_H];
            float mx = -1e30f;
            for (int h = 0; h < GP_HD_H; ++h) {
                int bin = 3 * ln + 36 + GP_HD_SHIFT[h];
                int vb = (bin < HCQT_EXTENDED) ? 1 : 0;
                valid_b[h] = (float)vb;
                int b_cl = vb ? bin : HCQT_EXTENDED - 1;
                for (int k = 0; k < GP_HD_KT; ++k) {
                    int t = tk[k];
                    int act = (t >= a && t < b) ? 1 : 0;
                    float og = occ[(size_t)b_cl * T1 + t];
                    float den = og + pi_w[h] * (float)(1 - act);
                    if (den < 1e-6f) den = 1e-6f;
                    float share = pi_w[h] / den;
                    if (share > 1.0f) share = 1.0f;
                    float pg = P_net[(size_t)b_cl * T + t];
                    float v = vb ? logf(pg * share + 1e-7f) : 0.0f;
                    lE[h * GP_HD_KT + k] = v;
                    if (v > mx) mx = v;
                }
            }
            float *dst = hd_in + (size_t)i * GP_HD_NFEAT;
            for (int j = 0; j < GP_HD_H * GP_HD_KT; ++j) {
                float v = lE[j] - mx;
                if (v < -20.0f) v = -20.0f;
                dst[j] = v * 0.1f;
            }
            for (int h = 0; h < GP_HD_H; ++h) dst[GP_HD_H * GP_HD_KT + h] = valid_b[h];
        }
        nn_sgemm_nt(N, GP_HD_HID, GP_HD_NFEAT, hd_in, GP_HD_NFEAT, m->hd0_w, GP_HD_NFEAT, hd_mid, GP_HD_HID, m->hd0_b, 0);
        nn_gelu_inplace(hd_mid, (size_t)N * GP_HD_HID);
        nn_sgemm_nt(N, GP_D, GP_HD_HID, hd_mid, GP_HD_HID, m->hd2_w, GP_HD_HID, tok, GP_D, m->hd2_b, 1);

        /* 4. Prof (reuses f_on, f_off, lane on X_nhwc) */
        float *pr_in = (float *)malloc((size_t)N * 36 * sizeof(float));
        float *pr_mid = (float *)malloc((size_t)N * 64 * sizeof(float));
        if (!pr_in || !pr_mid) {
            free(pr_in); free(pr_mid); free(occ); free(f_on); free(f_off); free(lane); free(hd_in); free(hd_mid);
            goto fail_early;
        }
        for (int i = 0; i < N; ++i) {
            int a = f_on[i], b = f_off[i], fb = 3 * lane[i];
            float inv_n = 1.0f / (float)(b > a ? b - a : 1);
            float *dst = pr_in + (size_t)i * 36;
            for (int off = 0; off < 2; ++off) {
                int fbb = gp_clamp(fb + off, 0, HCQT_BINS - 1);
                double s1[9] = {0}, s2[9] = {0};
                for (int t = a; t < b; ++t) {
                    const float *xp = X_nhwc + ((size_t)t * HCQT_BINS + fbb) * HCQT_CHANNELS;
                    for (int ch = 0; ch < 9; ++ch) {
                        double v = xp[ch];
                        s1[ch] += v;
                        s2[ch] += v * v;
                    }
                }
                for (int ch = 0; ch < 9; ++ch) {
                    double m1 = s1[ch] * inv_n;
                    double v2 = s2[ch] * inv_n - m1 * m1;
                    if (v2 < 0.0) v2 = 0.0;
                    dst[off * 18 + ch] = (float)m1;
                    dst[off * 18 + 9 + ch] = sqrtf((float)v2 + 1e-4f);
                }
            }
        }
        nn_sgemm_nt(N, 64, 36, pr_in, 36, m->pr0_w, 36, pr_mid, 64, m->pr0_b, 0);
        nn_gelu_inplace(pr_mid, (size_t)N * 64);
        nn_sgemm_nt(N, GP_D, 64, pr_mid, 64, m->pr2_w, 64, tok, GP_D, m->pr2_b, 1);

        free(pr_in); free(pr_mid); free(occ); free(f_on); free(f_off); free(lane); free(hd_in); free(hd_mid);
    }
    free(X_ctf); X_ctf = NULL;
    free(P_net); P_net = NULL;

    /* 5. LaneFront */
    {
        float *Y = (float *)malloc((size_t)Tq * GP_LNLANES * GP_LC * sizeof(float));
        float *R = (float *)calloc((size_t)(Tq + 1) * GP_LNLANES * 4, sizeof(float));
        float *buf_a = (float *)malloc((size_t)Tq * GP_LNLANES * GP_LC * sizeof(float));
        float *buf_b = (float *)malloc((size_t)Tq * GP_LNLANES * GP_LC * sizeof(float));
        float *buf_big = (float *)malloc((size_t)Tq * GP_LNLANES * 3 * GP_LC * sizeof(float));
        int *ron = (int *)malloc((size_t)N * sizeof(int));
        int *roff = (int *)malloc((size_t)N * sizeof(int));
        int *rlane = (int *)malloc((size_t)N * sizeof(int));
        float *read_in = (float *)malloc((size_t)N * 2 * GP_LC * sizeof(float));
        if (!Y || !R || !buf_a || !buf_b || !buf_big || !ron || !roff || !rlane || !read_in) {
            free(Y); free(R); free(buf_a); free(buf_b); free(buf_big);
            free(ron); free(roff); free(rlane); free(read_in);
            goto fail_early;
        }
        if (!nn_conv2d_nhwc(X_nhwc, T, HCQT_BINS, HCQT_CHANNELS, m->ls_w, m->ls_b,
                            GP_LC, GP_LTS, 3, GP_LTS, 3, 0, 1, Y)) {
            free(Y); free(R); free(buf_a); free(buf_b); free(buf_big);
            free(ron); free(roff); free(rlane); free(read_in);
            goto fail_early;
        }
        /* Build 4-channel rasters [Tq, 96, 4] at fps = 12.5 */
        double fps = 100.0 / (double)GP_LTS;
        for (int i = 0; i < N; ++i) {
            const float *nt = win_notes12 + (size_t)i * 12;
            int a = gp_clamp((int)floor(((double)nt[0] + 0.5) * fps), 0, Tq - 1);
            int b = (int)floor(((double)nt[1] + 0.5) * fps);
            if (b > Tq) b = Tq;
            if (b < a + 1) b = a + 1;
            int ln = gp_clamp((int)rint(nt[2]) - 21, 0, GP_LNLANES - 1);
            ron[i] = a; roff[i] = b; rlane[i] = ln;
            float conf = (nt[3] > 0.5f) ? nt[5] : nt[4];
            float s2 = (nt[3] > 0.5f) ? 1.0f : 0.0f;
            float *ra = R + ((size_t)a * GP_LNLANES + ln) * 4;
            float *rb = R + ((size_t)b * GP_LNLANES + ln) * 4;
            ra[0] += 1.0f;
            ra[1] += 1.0f;
            rb[1] -= 1.0f;
            ra[2] += conf;
            ra[3] += s2;
        }
        /* Cumsum channel 1 along time */
        for (int p = 0; p < GP_LNLANES; ++p) {
            float acc = 0.0f;
            for (int t = 0; t < Tq; ++t) {
                float *rp = R + ((size_t)t * GP_LNLANES + p) * 4;
                acc += rp[1];
                rp[1] = acc;
            }
        }
        /* Y += occ(R) */
        nn_sgemm_nt(Tq * GP_LNLANES, GP_LC, 4, R, 4, m->lo_w, 4, Y, GP_LC, m->lo_b, 1);

        int attn_k = 0;
        for (int bi = 0; bi < GP_LDEPTH; ++bi) {
            run_gp_lblock(&m->lblocks[bi], Y, Tq, buf_a, buf_b, buf_big);
            if (bi == 2 || bi == 5)
                run_gp_lattn(&m->lattn[attn_k++], Y, Tq, buf_a, buf_big, buf_b);
        }

        for (int i = 0; i < N; ++i) {
            int a = ron[i], b = roff[i], ln = rlane[i];
            float *dst = read_in + (size_t)i * 2 * GP_LC;
            memcpy(dst, Y + ((size_t)a * GP_LNLANES + ln) * GP_LC, GP_LC * sizeof(float));
            float *mean = dst + GP_LC;
            memset(mean, 0, GP_LC * sizeof(float));
            for (int t = a; t < b; ++t) {
                const float *src = Y + ((size_t)t * GP_LNLANES + ln) * GP_LC;
                for (int c = 0; c < GP_LC; ++c) mean[c] += src[c];
            }
            float inv = 1.0f / (float)(b > a ? b - a : 1);
            for (int c = 0; c < GP_LC; ++c) mean[c] *= inv;
        }
        nn_sgemm_nt(N, GP_D, 2 * GP_LC, read_in, 2 * GP_LC, m->lr_w, 2 * GP_LC, tok, GP_D, m->lr_b, 1);

        free(Y); free(R); free(buf_a); free(buf_b); free(buf_big);
        free(ron); free(roff); free(rlane); free(read_in);
    }
    free(X_nhwc); X_nhwc = NULL;

    /* 6. s15 transcriber taps: standardise per channel across the N notes, LayerNorm(368), MLP */
    {
        int F3 = 3 * GP_S15_DIM;
        float *fn = (float *)malloc((size_t)N * F3 * sizeof(float));
        float *s15_mid = (float *)malloc((size_t)N * GP_S15_HID * sizeof(float));
        if (!fn || !s15_mid) { free(fn); free(s15_mid); goto fail_early; }
        for (int j = 0; j < F3; ++j) {
            double sum = 0.0;
            for (int i = 0; i < N; ++i) sum += win_feat3[(size_t)i * F3 + j];
            double mu = sum / (double)N;
            double var = 0.0;
            for (int i = 0; i < N; ++i) { double d = win_feat3[(size_t)i * F3 + j] - mu; var += d * d; }
            double sd = sqrt(var / (double)N);
            if (sd < 1e-3) sd = 1e-3;
            float fmu = (float)mu, inv = (float)(1.0 / sd);
            for (int i = 0; i < N; ++i) fn[(size_t)i * F3 + j] = (win_feat3[(size_t)i * F3 + j] - fmu) * inv;
        }
        nn_layernorm(fn, fn, N * 3, GP_S15_DIM, m->s15_ln_w, m->s15_ln_b, 1e-5f);
        nn_sgemm_nt(N, GP_S15_HID, F3, fn, F3, m->s15_0_w, F3, s15_mid, GP_S15_HID, m->s15_0_b, 0);
        nn_gelu_inplace(s15_mid, (size_t)N * GP_S15_HID);
        nn_sgemm_nt(N, GP_D, GP_S15_HID, s15_mid, GP_S15_HID, m->s15_2_w, GP_S15_HID, tok, GP_D, m->s15_2_b, 1);
        free(fn); free(s15_mid);
    }

    /* 7. ln_in + 7 Transformer blocks with RoPE(pos = on * 10.0) + ln_out + heads */
    {
        nn_layernorm(tok, tok, N, GP_D, m->ln_in_w, m->ln_in_b, 1e-5f);
        float *h = (float *)malloc((size_t)N * GP_D * sizeof(float));
        float *qkv = (float *)malloc((size_t)N * 3 * GP_D * sizeof(float));
        float *ff = (float *)malloc((size_t)N * GP_FF * sizeof(float));
        float *rcos = (float *)malloc((size_t)N * (GP_HD / 2) * sizeof(float));
        float *rsin = (float *)malloc((size_t)N * (GP_HD / 2) * sizeof(float));
        float *scores = (float *)malloc((size_t)N * sizeof(float));
        float *inst_lg = (float *)malloc((size_t)N * GP_K * sizeof(float));
        if (!h || !qkv || !ff || !rcos || !rsin || !scores || !inst_lg) {
            free(h); free(qkv); free(ff); free(rcos); free(rsin); free(scores); free(inst_lg);
            goto fail_early;
        }
        const int half = GP_HD / 2;
        double freqs[GP_HD / 2];
        for (int d = 0; d < half; ++d) freqs[d] = 1.0 / pow(10000.0, (double)d / (double)half);
        for (int i = 0; i < N; ++i) {
            double pos = (double)win_notes12[(size_t)i * 12] * 10.0;
            for (int d = 0; d < half; ++d) {
                double a = pos * freqs[d];
                rcos[i * half + d] = (float)cos(a);
                rsin[i * half + d] = (float)sin(a);
            }
        }
        const float att_scale = 1.0f / sqrtf((float)GP_HD);
        for (int bi = 0; bi < GP_DEPTH; ++bi) {
            const struct gp_tblock *blk = &m->blocks[bi];
            nn_layernorm(tok, h, N, GP_D, blk->ln1_w, blk->ln1_b, 1e-5f);
            nn_sgemm_nt(N, 3 * GP_D, GP_D, h, GP_D, blk->qkv_w, GP_D, qkv, 3 * GP_D, blk->qkv_b, 0);
            /* Split-half RoPE on q and k */
            for (int i = 0; i < N; ++i) {
                const float *c = rcos + i * half, *s = rsin + i * half;
                for (int hd = 0; hd < GP_HEADS; ++hd) {
                    float *qh = qkv + (size_t)i * 3 * GP_D + 0 * GP_D + hd * GP_HD;
                    float *kh = qkv + (size_t)i * 3 * GP_D + 1 * GP_D + hd * GP_HD;
                    for (int d = 0; d < half; ++d) {
                        float q1 = qh[d], q2 = qh[d + half];
                        qh[d] = q1 * c[d] - q2 * s[d];
                        qh[d + half] = q1 * s[d] + q2 * c[d];
                        float k1 = kh[d], k2 = kh[d + half];
                        kh[d] = k1 * c[d] - k2 * s[d];
                        kh[d + half] = k1 * s[d] + k2 * c[d];
                    }
                }
            }
            /* Attention -> h */
            for (int hd = 0; hd < GP_HEADS; ++hd) {
                for (int qi = 0; qi < N; ++qi) {
                    const float *qv = qkv + (size_t)qi * 3 * GP_D + hd * GP_HD;
                    float mx = -1e30f;
                    for (int ki = 0; ki < N; ++ki) {
                        const float *kv = qkv + (size_t)ki * 3 * GP_D + GP_D + hd * GP_HD;
                        float dot = 0.0f;
                        for (int d = 0; d < GP_HD; ++d) dot += qv[d] * kv[d];
                        float sc = dot * att_scale;
                        scores[ki] = sc;
                        if (sc > mx) mx = sc;
                    }
                    float se = 0.0f;
                    for (int ki = 0; ki < N; ++ki) { scores[ki] = expf(scores[ki] - mx); se += scores[ki]; }
                    float inv = 1.0f / se;
                    float *dst = h + (size_t)qi * GP_D + hd * GP_HD;
                    memset(dst, 0, GP_HD * sizeof(float));
                    for (int ki = 0; ki < N; ++ki) {
                        float w = scores[ki] * inv;
                        const float *vv = qkv + (size_t)ki * 3 * GP_D + 2 * GP_D + hd * GP_HD;
                        for (int d = 0; d < GP_HD; ++d) dst[d] += w * vv[d];
                    }
                }
            }
            nn_sgemm_nt(N, GP_D, GP_D, h, GP_D, blk->o_w, GP_D, tok, GP_D, blk->o_b, 1);
            nn_layernorm(tok, h, N, GP_D, blk->ln2_w, blk->ln2_b, 1e-5f);
            nn_sgemm_nt(N, GP_FF, GP_D, h, GP_D, blk->ff0_w, GP_D, ff, GP_FF, blk->ff0_b, 0);
            nn_gelu_inplace(ff, (size_t)N * GP_FF);
            nn_sgemm_nt(N, GP_D, GP_FF, ff, GP_FF, blk->ff2_w, GP_FF, tok, GP_D, blk->ff2_b, 1);
        }
        nn_layernorm(tok, h_out, N, GP_D, m->ln_out_w, m->ln_out_b, 1e-5f);
        nn_sgemm_nt(N, GP_K, GP_D, h_out, GP_D, m->h_inst_w, GP_D, inst_lg, GP_K, m->h_inst_b, 0);
        nn_sgemm_nt(N, GP_EMB, GP_D, h_out, GP_D, m->h_emb_w, GP_D, emb_out, GP_EMB, m->h_emb_b, 0);
        for (int i = 0; i < N; ++i) {
            const float *lg = inst_lg + (size_t)i * GP_K;
            float *pr = probs_out + (size_t)i * GP_K;
            float mx = lg[0];
            for (int k = 1; k < GP_K; ++k) if (lg[k] > mx) mx = lg[k];
            double se = 0.0;
            for (int k = 0; k < GP_K; ++k) { pr[k] = expf(lg[k] - mx); se += pr[k]; }
            float inv = (float)(1.0 / se);
            for (int k = 0; k < GP_K; ++k) pr[k] *= inv;

            float *ev = emb_out + (size_t)i * GP_EMB;
            double n2 = 0.0;
            for (int d = 0; d < GP_EMB; ++d) n2 += (double)ev[d] * (double)ev[d];
            float inv_n = (float)(1.0 / (sqrt(n2) > 1e-12 ? sqrt(n2) : 1e-12));
            for (int d = 0; d < GP_EMB; ++d) ev[d] *= inv_n;
        }
        free(h); free(qkv); free(ff); free(rcos); free(rsin); free(scores); free(inst_lg);
    }
    ok = 1;

fail_early:
    free(X_ctf); free(P_net); free(X_nhwc); free(tok);
    return ok;
}

/* =========================================================================
 * Clustering, Hungarian assignment, and track naming (matches grouper/decode.py)
 * ========================================================================= */

/* Average-linkage (UPGMA) flat clustering cut at distance tau.
 * Returns number of clusters (labels 0..nl-1 in lab_out[0..m-1]). */
static int cluster_window_upgma(const float *e, const float *p, int m, double tau, double lam, int *lab_out) {
    if (m <= 0) return 0;
    if (m == 1) { lab_out[0] = 0; return 1; }
    double *pn = (double *)malloc((size_t)m * GP_K * sizeof(double));
    double *D = (double *)malloc((size_t)m * m * sizeof(double));
    double *sz = (double *)malloc((size_t)m * sizeof(double));
    int *alive = (int *)malloc((size_t)m * sizeof(int));
    int *rep = (int *)malloc((size_t)m * sizeof(int));
    if (!pn || !D || !sz || !alive || !rep) {
        free(pn); free(D); free(sz); free(alive); free(rep);
        for (int i = 0; i < m; ++i) lab_out[i] = 0;
        return 1;
    }
    for (int i = 0; i < m; ++i) {
        double n2 = 0.0;
        for (int k = 0; k < GP_K; ++k) n2 += (double)p[i * GP_K + k] * (double)p[i * GP_K + k];
        double inv = 1.0 / (sqrt(n2) > 1e-9 ? sqrt(n2) : 1e-9);
        for (int k = 0; k < GP_K; ++k) pn[i * GP_K + k] = (double)p[i * GP_K + k] * inv;
        sz[i] = 1.0; alive[i] = 1; rep[i] = i;
    }
    for (int i = 0; i < m; ++i) {
        D[i * m + i] = DBL_MAX;
        for (int j = i + 1; j < m; ++j) {
            double de = 0.0, dp = 0.0;
            for (int d = 0; d < GP_EMB; ++d) de += (double)e[i * GP_EMB + d] * (double)e[j * GP_EMB + d];
            if (lam > 0.0) {
                for (int k = 0; k < GP_K; ++k) dp += pn[i * GP_K + k] * pn[j * GP_K + k];
            }
            double dist = (1.0 - de) + (lam > 0.0 ? lam * (1.0 - dp) : 0.0);
            if (dist < 0.0) dist = 0.0;
            D[i * m + j] = D[j * m + i] = dist;
        }
    }
    for (;;) {
        int bi = -1, bj = -1;
        double best = DBL_MAX;
        for (int i = 0; i < m; ++i) {
            if (!alive[i]) continue;
            for (int j = i + 1; j < m; ++j) {
                if (alive[j] && D[i * m + j] < best) { best = D[i * m + j]; bi = i; bj = j; }
            }
        }
        if (bi < 0 || best > tau) break;
        double si = sz[bi], sj = sz[bj], ssum = si + sj;
        for (int k = 0; k < m; ++k) {
            if (alive[k] && k != bi && k != bj) {
                double nd = (si * D[bi * m + k] + sj * D[bj * m + k]) / ssum;
                D[bi * m + k] = D[k * m + bi] = nd;
            }
        }
        sz[bi] = ssum;
        alive[bj] = 0;
        for (int k = 0; k < m; ++k) if (rep[k] == bj) rep[k] = bi;
    }
    int *remap = (int *)malloc((size_t)m * sizeof(int));
    for (int i = 0; i < m; ++i) remap[i] = -1;
    int nl = 0;
    for (int i = 0; i < m; ++i) {
        int r = rep[i];
        if (remap[r] < 0) remap[r] = nl++;
        lab_out[i] = remap[r];
    }
    free(remap); free(pn); free(D); free(sz); free(alive); free(rep);
    return nl;
}

/* Hungarian algorithm minimizing cost[nr, nc] (handles rectangular nr x nc).
 * Writes col_for_row[r] = assigned col (or -1 if nr > nc and unassigned). */
static void hungarian_min(const double *cost, int nr, int nc, int *col_for_row) {
    for (int r = 0; r < nr; ++r) col_for_row[r] = -1;
    if (nr <= 0 || nc <= 0) return;
    int transposed = (nr > nc);
    int n = transposed ? nc : nr;
    int m = transposed ? nr : nc;
    /* 1-indexed Kuhn-Munkres (n <= m) */
    double *u = (double *)calloc((size_t)(n + 1), sizeof(double));
    double *v = (double *)calloc((size_t)(m + 1), sizeof(double));
    int *p = (int *)calloc((size_t)(m + 1), sizeof(int));
    int *way = (int *)calloc((size_t)(m + 1), sizeof(int));
    double *minv = (double *)malloc((size_t)(m + 1) * sizeof(double));
    uint8_t *used = (uint8_t *)malloc((size_t)(m + 1));
    if (!u || !v || !p || !way || !minv || !used) {
        free(u); free(v); free(p); free(way); free(minv); free(used);
        return;
    }
    for (int i = 1; i <= n; ++i) {
        p[0] = i;
        int j0 = 0;
        for (int j = 0; j <= m; ++j) { minv[j] = DBL_MAX; used[j] = 0; }
        do {
            used[j0] = 1;
            int i0 = p[j0], j1 = 0;
            double delta = DBL_MAX;
            for (int j = 1; j <= m; ++j) {
                if (used[j]) continue;
                double c_ij = transposed ? cost[(j - 1) * nc + (i0 - 1)] : cost[(i0 - 1) * nc + (j - 1)];
                double cur = c_ij - u[i0] - v[j];
                if (cur < minv[j]) { minv[j] = cur; way[j] = j0; }
                if (minv[j] < delta) { delta = minv[j]; j1 = j; }
            }
            for (int j = 0; j <= m; ++j) {
                if (used[j]) { u[p[j]] += delta; v[j] -= delta; }
                else { minv[j] -= delta; }
            }
            j0 = j1;
        } while (p[j0] != 0);
        do {
            int j1 = way[j0];
            p[j0] = p[j1];
            j0 = j1;
        } while (j0 != 0);
    }
    for (int j = 1; j <= m; ++j) {
        if (p[j] > 0) {
            if (transposed) col_for_row[j - 1] = p[j] - 1;
            else col_for_row[p[j] - 1] = j - 1;
        }
    }
    free(u); free(v); free(p); free(way); free(minv); free(used);
}

struct gp_win_rec {
    double t0;
    size_t *sel;
    size_t m;
    float *emb;   /* [m, 32] */
    float *probs; /* [m, 73] */
};

struct gp_nt_item {
    double on, off;
    int pitch;
    int slot;
};

static int cmp_gp_nt(const void *pa, const void *pb) {
    const struct gp_nt_item *a = (const struct gp_nt_item *)pa;
    const struct gp_nt_item *b = (const struct gp_nt_item *)pb;
    if (a->on < b->on) return -1;
    if (a->on > b->on) return 1;
    return a->pitch - b->pitch;
}

static int cmp_size_desc_idx(const void *pa, const void *pb) {
    const struct { int id; double sz; } *a = pa, *b = pb;
    if (a->sz > b->sz) return -1;
    if (a->sz < b->sz) return 1;
    return a->id - b->id;
}

static int cmp_size_asc_idx(const void *pa, const void *pb) {
    const struct { int id; double sz; } *a = pa, *b = pb;
    if (a->sz < b->sz) return -1;
    if (a->sz > b->sz) return 1;
    return a->id - b->id;
}

static int cmp_midi_note_on(const void *pa, const void *pb) {
    const struct midi_note *a = (const struct midi_note *)pa;
    const struct midi_note *b = (const struct midi_note *)pb;
    if (a->onset < b->onset) return -1;
    if (a->onset > b->onset) return 1;
    return a->pitch - b->pitch;
}

static int cmp_track_len_desc(const void *pa, const void *pb) {
    const struct grouped_track *a = (const struct grouped_track *)pa;
    const struct grouped_track *b = (const struct grouped_track *)pb;
    if (a->count > b->count) return -1;
    if (a->count < b->count) return 1;
    return 0;
}

static double credit_val(int a, int b) {
    if (a == b) return 1.0;
    return (INST_TABLE[a].fam & INST_TABLE[b].fam) ? 0.5 : 0.0;
}

static void matvec_f64(int out_dim, int in_dim, const float *W, const float *b,
                       const double *x, double *y) {
    for (int o = 0; o < out_dim; ++o) {
        double acc = (double)b[o];
        const float *wo = W + (size_t)o * in_dim;
        for (int i = 0; i < in_dim; ++i) acc += (double)wo[i] * x[i];
        y[o] = acc;
    }
}

static void gelu_f64(double *x, int n) {
    const double inv_s2 = 0.7071067811865475244;
    for (int i = 0; i < n; ++i) x[i] = 0.5 * x[i] * (1.0 + erf(x[i] * inv_s2));
}

int grouper_run(const struct grouper_model *m,
                const float *audio_y, size_t n_y,
                const struct transcribe_run *tr,
                const struct repaired_note *rep_notes, size_t n_rep,
                double retune_ratio,
                struct grouped_track **tracks_out, size_t *n_tracks_out) {
    *tracks_out = NULL;
    *n_tracks_out = 0;
    if (n_rep == 0) return 1;
    if (!m || !audio_y || !tr || !tr->sub_maps || !tr->sub_hidden_f16 || !tr->sub_stem_f16) return 0;

    int ok = 0;
    struct vt_note *tnotes = NULL; size_t n_tnotes = 0;
    struct gp_nt_item *nt = NULL;
    float *meta = NULL;       /* [n_rep, 12] */
    float *feat_all = NULL;   /* [n_rep, 3 * 368] (post int8+f16 round-trip) */
    int16_t *audio_i16 = NULL;
    struct gp_win_rec *wins = NULL; size_t n_wins = 0, wins_cap = 0;
    double *acc_probs = NULL, *wsum = NULL, *best_w = NULL, *acc_emb = NULL;
    uint16_t *h_f16 = NULL;
    int *track_id = NULL, *inv = NULL;

    /* 1. Decode sub_maps -> assign_slots */
    if (!transcribe_decode(tr->sub_maps, tr->T, &tnotes, &n_tnotes)) goto cleanup;
    nt = (struct gp_nt_item *)malloc(n_rep * sizeof(*nt));
    if (!nt) goto cleanup;
    for (size_t i = 0; i < n_rep; ++i) {
        double on = rep_notes[i].onset;
        double off = rep_notes[i].offset;
        if (off < on + 0.03) off = on + 0.03;
        int p = rep_notes[i].pitch;
        int slot = 0;
        double best_d = 1e9;
        for (size_t j = 0; j < n_tnotes; ++j) {
            if (tnotes[j].pitch == p) {
                double d = fabs(on - tnotes[j].onset);
                if (d < best_d) { best_d = d; slot = tnotes[j].slot - 1; }
            }
        }
        if (best_d > 0.1) slot = 0;
        nt[i] = (struct gp_nt_item){ on, off, p, slot };
    }
    free(tnotes); tnotes = NULL;
    qsort(nt, n_rep, sizeof(*nt), cmp_gp_nt);

    /* 2. Gather meta [n_rep, 12] and feat_all [n_rep, 3*368] from sub-run */
    meta = (float *)malloc(n_rep * 12 * sizeof(float));
    feat_all = (float *)malloc(n_rep * 3 * GP_S15_DIM * sizeof(float));
    if (!meta || !feat_all) goto cleanup;
    {
        int T = tr->T;
        size_t stride = (size_t)T * LANE_KEYS;
        const float *on1 = tr->sub_maps + HEAD_ONSET * stride;
        const float *fr1 = tr->sub_maps + HEAD_FRAME * stride;
        const float *off1 = tr->sub_maps + HEAD_OFFSET * stride;
        const float *on2 = tr->sub_maps + HEAD_ONSET2 * stride;
        const float *fr2 = tr->sub_maps + HEAD_FRAME2 * stride;
        const float *off2 = tr->sub_maps + HEAD_OFFSET2 * stride;
        for (size_t i = 0; i < n_rep; ++i) {
            int ln = gp_clamp(nt[i].pitch - PITCH_LO, 0, LANE_KEYS - 1);
            int t0 = gp_clamp((int)rint(nt[i].on / 0.02), 0, T - 1);
            int te = (int)ceil(nt[i].off / 0.02);
            if (te < t0 + 1) te = t0 + 1;
            if (te > T) te = T;

            float mx_on1 = -1.0f, mx_on2 = -1.0f, mx_off1 = -1.0f, mx_off2 = -1.0f;
            for (int d = -1; d <= 1; ++d) {
                int tt = gp_clamp(t0 + d, 0, T - 1);
                float v1 = on1[(size_t)tt * LANE_KEYS + ln]; if (v1 > mx_on1) mx_on1 = v1;
                float v2 = on2[(size_t)tt * LANE_KEYS + ln]; if (v2 > mx_on2) mx_on2 = v2;
                int tei = gp_clamp(te - 1 + d, 0, T - 1);
                float o1 = off1[(size_t)tei * LANE_KEYS + ln]; if (o1 > mx_off1) mx_off1 = o1;
                float o2 = off2[(size_t)tei * LANE_KEYS + ln]; if (o2 > mx_off2) mx_off2 = o2;
            }
            double s_fr1 = 0.0, s_fr2 = 0.0;
            for (int t = t0; t < te; ++t) {
                s_fr1 += fr1[(size_t)t * LANE_KEYS + ln];
                s_fr2 += fr2[(size_t)t * LANE_KEYS + ln];
            }
            float inv_sp = 1.0f / (float)(te > t0 ? te - t0 : 1);
            float *mi = meta + i * 12;
            mi[0] = (float)nt[i].on; mi[1] = (float)nt[i].off;
            mi[2] = (float)nt[i].pitch; mi[3] = (float)nt[i].slot;
            mi[4] = mx_on1; mi[5] = mx_on2;
            mi[6] = fr1[(size_t)t0 * LANE_KEYS + ln];
            mi[7] = fr2[(size_t)t0 * LANE_KEYS + ln];
            mi[8] = (float)s_fr1 * inv_sp;
            mi[9] = (float)s_fr2 * inv_sp;
            mi[10] = mx_off1; mi[11] = mx_off2;

            /* 3 taps: H[t0], mean(H[t0:min(te,t0+50)]), mean(S[t0:min(te,t0+10)]) */
            float taps[3][GP_S15_DIM];
            const uint16_t *h0 = tr->sub_hidden_f16 + ((size_t)t0 * LANE_KEYS + ln) * GP_S15_DIM;
            for (int c = 0; c < GP_S15_DIM; ++c) { taps[0][c] = vt_f16_to_f32(h0[c]); taps[1][c] = 0.0f; taps[2][c] = 0.0f; }
            int lim1 = te < t0 + 50 ? te : t0 + 50;
            for (int t = t0; t < lim1; ++t) {
                const uint16_t *ht = tr->sub_hidden_f16 + ((size_t)t * LANE_KEYS + ln) * GP_S15_DIM;
                for (int c = 0; c < GP_S15_DIM; ++c) taps[1][c] += vt_f16_to_f32(ht[c]);
            }
            float inv1 = 1.0f / (float)(lim1 > t0 ? lim1 - t0 : 1);
            for (int c = 0; c < GP_S15_DIM; ++c) taps[1][c] *= inv1;

            int lim2 = te < t0 + 10 ? te : t0 + 10;
            for (int t = t0; t < lim2; ++t) {
                const uint16_t *st = tr->sub_stem_f16 + ((size_t)t * LANE_KEYS + ln) * GP_S15_DIM;
                for (int c = 0; c < GP_S15_DIM; ++c) taps[2][c] += vt_f16_to_f32(st[c]);
            }
            float inv2 = 1.0f / (float)(lim2 > t0 ? lim2 - t0 : 1);
            for (int c = 0; c < GP_S15_DIM; ++c) taps[2][c] *= inv2;

            /* int8 + f16 scale quantization round-trip (matches core.py gather) */
            for (int tp = 0; tp < 3; ++tp) {
                float amax = 1e-6f;
                for (int c = 0; c < GP_S15_DIM; ++c) {
                    float a = fabsf(taps[tp][c]);
                    if (a > amax) amax = a;
                }
                float sc = amax / 127.0f;
                float sc_f16 = vt_f16_to_f32(vt_f32_to_f16(sc));
                float *dst = feat_all + (i * 3 + tp) * GP_S15_DIM;
                for (int c = 0; c < GP_S15_DIM; ++c) {
                    int q = gp_clamp((int)rint(taps[tp][c] / sc), -127, 127);
                    dst[c] = (float)q * sc_f16;
                }
            }
        }
    }

    /* 3. Audio int16 quantization (_Song) + 24 s windows every 12 s */
    audio_i16 = (int16_t *)malloc((n_y ? n_y : 1) * sizeof(int16_t));
    acc_probs = (double *)calloc(n_rep * GP_K, sizeof(double));
    wsum = (double *)calloc(n_rep, sizeof(double));
    best_w = (double *)malloc(n_rep * sizeof(double));
    acc_emb = (double *)calloc(n_rep * GP_EMB, sizeof(double));
    h_f16 = (uint16_t *)calloc(n_rep * GP_D, sizeof(uint16_t));
    if (!audio_i16 || !acc_probs || !wsum || !best_w || !acc_emb || !h_f16) goto cleanup;
    for (size_t i = 0; i < n_rep; ++i) best_w[i] = -1.0;
    for (size_t i = 0; i < n_y; ++i) {
        double v = rint((double)audio_y[i] * 32768.0);
        if (v < -32768.0) v = -32768.0;
        if (v > 32767.0) v = 32767.0;
        audio_i16[i] = (int16_t)v;
    }

    const double W = 24.0, hop = 12.0;
    const int win_samples = (int)rint((0.5 + W + 1.0) * MODEL_RATE); /* 408000 */
    float *win_audio = (float *)malloc((size_t)win_samples * sizeof(float));
    if (!win_audio) goto cleanup;

    double end_on = (double)meta[(n_rep - 1) * 12];
    double t0 = 0.0;
    for (;;) {
        size_t a = 0; while (a < n_rep && (double)meta[a * 12] < t0) a++;
        size_t b = a; while (b < n_rep && (double)meta[b * 12] < t0 + W) b++;
        size_t sel_end = (b - a > GP_MAX_NOTES) ? (a + GP_MAX_NOTES) : b;
        size_t nw = sel_end - a;
        if (nw >= 1) {
            int n_eff = (nw < 4) ? 4 : (int)nw;
            float *wn = (float *)malloc((size_t)n_eff * 12 * sizeof(float));
            float *wf = (float *)malloc((size_t)n_eff * 3 * GP_S15_DIM * sizeof(float));
            float *wp = (float *)malloc((size_t)n_eff * GP_K * sizeof(float));
            float *we = (float *)malloc((size_t)n_eff * GP_EMB * sizeof(float));
            float *wh = (float *)malloc((size_t)n_eff * GP_D * sizeof(float));
            if (!wn || !wf || !wp || !we || !wh) {
                free(wn); free(wf); free(wp); free(we); free(wh); free(win_audio);
                goto cleanup;
            }
            for (int k = 0; k < n_eff; ++k) {
                size_t idx = a + (size_t)(k % (int)nw);
                memcpy(wn + (size_t)k * 12, meta + idx * 12, 12 * sizeof(float));
                wn[k * 12 + 0] -= (float)t0;
                float off_rel = wn[k * 12 + 1] - (float)t0;
                if (off_rel > (float)(W + 1.0)) off_rel = (float)(W + 1.0);
                wn[k * 12 + 1] = off_rel;
                memcpy(wf + (size_t)k * 3 * GP_S15_DIM, feat_all + idx * 3 * GP_S15_DIM,
                       3 * GP_S15_DIM * sizeof(float));
            }
            /* Slice audio [t0 - 0.5, t0 + 25.0) */
            memset(win_audio, 0, (size_t)win_samples * sizeof(float));
            long long s0 = (long long)rint((t0 - 0.5) * MODEL_RATE);
            long long lo = s0 > 0 ? s0 : 0;
            long long hi = s0 + win_samples < (long long)n_y ? s0 + win_samples : (long long)n_y;
            for (long long s = lo; s < hi; ++s)
                win_audio[s - s0] = (float)audio_i16[s] / 32768.0f;

            if (!run_notenet_window(m, win_audio, win_samples, wn, wf, n_eff, wp, we, wh)) {
                free(wn); free(wf); free(wp); free(we); free(wh); free(win_audio);
                goto cleanup;
            }
            /* Accumulate predictions for first nw notes */
            if (n_wins == wins_cap) {
                size_t next = wins_cap ? wins_cap * 2 : 16;
                struct gp_win_rec *g = (struct gp_win_rec *)realloc(wins, next * sizeof(*g));
                if (!g) { free(wn); free(wf); free(wp); free(we); free(wh); free(win_audio); goto cleanup; }
                wins = g; wins_cap = next;
            }
            size_t *sel_arr = (size_t *)malloc(nw * sizeof(size_t));
            float *rec_e = (float *)malloc(nw * GP_EMB * sizeof(float));
            float *rec_p = (float *)malloc(nw * GP_K * sizeof(float));
            if (!sel_arr || !rec_e || !rec_p) {
                free(sel_arr); free(rec_e); free(rec_p);
                free(wn); free(wf); free(wp); free(we); free(wh); free(win_audio);
                goto cleanup;
            }
            for (size_t k = 0; k < nw; ++k) {
                size_t idx = a + k;
                sel_arr[k] = idx;
                double w = 1.0 - fabs(((double)meta[idx * 12] - t0) / W - 0.5) * 2.0;
                if (w < 0.05) w = 0.05;
                if (w > 1.0) w = 1.0;
                wsum[idx] += w;
                for (int c = 0; c < GP_K; ++c) {
                    acc_probs[idx * GP_K + c] += (double)wp[k * GP_K + c] * w;
                    rec_p[k * GP_K + c] = vt_f16_to_f32(vt_f32_to_f16(wp[k * GP_K + c]));
                }
                for (int d = 0; d < GP_EMB; ++d) {
                    acc_emb[idx * GP_EMB + d] += (double)we[k * GP_EMB + d] * w;
                    rec_e[k * GP_EMB + d] = vt_f16_to_f32(vt_f32_to_f16(we[k * GP_EMB + d]));
                }
                if (w > best_w[idx]) {
                    best_w[idx] = w;
                    for (int d = 0; d < GP_D; ++d)
                        h_f16[idx * GP_D + d] = vt_f32_to_f16(wh[k * GP_D + d]);
                }
            }
            wins[n_wins++] = (struct gp_win_rec){ t0, sel_arr, nw, rec_e, rec_p };
            free(wn); free(wf); free(wp); free(we); free(wh);
        }
        if (b >= n_rep && a + GP_MAX_NOTES >= b) break;
        if (b - a > GP_MAX_NOTES) {
            double cand_t = (double)meta[(a + GP_MAX_NOTES / 2) * 12];
            t0 = (t0 + 0.25 * hop > cand_t) ? (t0 + 0.25 * hop) : cand_t;
        } else {
            t0 += hop;
        }
        if (t0 > end_on) break;
    }
    free(win_audio);

    /* Finalize per-note probs and unit emb */
    for (size_t i = 0; i < n_rep; ++i) {
        double ws = wsum[i] > 1e-9 ? wsum[i] : 1e-9;
        for (int c = 0; c < GP_K; ++c) acc_probs[i * GP_K + c] /= ws;
        double n2 = 0.0;
        for (int d = 0; d < GP_EMB; ++d) n2 += acc_emb[i * GP_EMB + d] * acc_emb[i * GP_EMB + d];
        double inv_n = 1.0 / (sqrt(n2) > 1e-9 ? sqrt(n2) : 1e-9);
        for (int d = 0; d < GP_EMB; ++d) acc_emb[i * GP_EMB + d] *= inv_n;
    }

    /* 4. Decode step 1: group_chain across windows */
    track_id = (int *)malloc(n_rep * sizeof(int));
    int *owner = (int *)malloc(n_rep * sizeof(int));
    double *chain_bw = (double *)malloc(n_rep * sizeof(double));
    if (!track_id || !owner || !chain_bw) { free(owner); free(chain_bw); goto cleanup; }
    for (size_t i = 0; i < n_rep; ++i) { track_id[i] = -1; owner[i] = -1; chain_bw[i] = -1.0; }
    int n_glob = 0;
    for (size_t wi = 0; wi < n_wins; ++wi) {
        struct gp_win_rec *wr = &wins[wi];
        if (wr->m == 0) continue;
        int *lab = (int *)malloc(wr->m * sizeof(int));
        if (!lab) { free(owner); free(chain_bw); goto cleanup; }
        int nl = cluster_window_upgma(wr->emb, wr->probs, (int)wr->m, 0.1, 0.5, lab);
        int *glob_of = (int *)malloc((size_t)nl * sizeof(int));
        for (int i = 0; i < nl; ++i) glob_of[i] = -1;

        /* Collect unique positive prev owner ids */
        int *gids = (int *)malloc(wr->m * sizeof(int));
        int n_gids = 0;
        for (size_t k = 0; k < wr->m; ++k) {
            int pv = owner[wr->sel[k]];
            if (pv >= 0) {
                int found = 0;
                for (int j = 0; j < n_gids; ++j) if (gids[j] == pv) { found = 1; break; }
                if (!found) gids[n_gids++] = pv;
            }
        }
        if (n_gids > 0) {
            /* Sort gids ascending for deterministic matching */
            for (int i = 0; i < n_gids; ++i)
                for (int j = i + 1; j < n_gids; ++j)
                    if (gids[j] < gids[i]) { int t = gids[i]; gids[i] = gids[j]; gids[j] = t; }
            double *cost = (double *)calloc((size_t)nl * n_gids, sizeof(double));
            int *assign = (int *)malloc((size_t)nl * sizeof(int));
            for (size_t k = 0; k < wr->m; ++k) {
                int pv = owner[wr->sel[k]];
                if (pv >= 0) {
                    int gi = 0; while (gids[gi] != pv) gi++;
                    cost[lab[k] * n_gids + gi] -= 1.0;
                }
            }
            hungarian_min(cost, nl, n_gids, assign);
            for (int li = 0; li < nl; ++li) {
                int gi = assign[li];
                if (gi >= 0 && cost[li * n_gids + gi] < 0.0) glob_of[li] = gids[gi];
            }
            free(cost); free(assign);
        }
        free(gids);
        for (int li = 0; li < nl; ++li)
            if (glob_of[li] < 0) glob_of[li] = n_glob++;
        for (size_t k = 0; k < wr->m; ++k) {
            size_t idx = wr->sel[k];
            int g = glob_of[lab[k]];
            owner[idx] = g;
            double w = 1.0 - fabs(((double)meta[idx * 12] - wr->t0) / W - 0.5) * 2.0;
            if (w < 0.05) w = 0.05;
            if (w > 1.0) w = 1.0;
            if (w > chain_bw[idx]) { track_id[idx] = g; chain_bw[idx] = w; }
        }
        free(lab); free(glob_of);
    }
    free(owner); free(chain_bw);

    /* Compact to covered notes (track_id >= 0), matching decode.py idx = nonzero(track >= 0) */
    {
        size_t w = 0;
        for (size_t i = 0; i < n_rep; ++i) {
            if (track_id[i] < 0) continue;
            if (w != i) {
                nt[w] = nt[i];
                memcpy(meta + w * 12, meta + i * 12, 12 * sizeof(float));
                memcpy(acc_probs + w * GP_K, acc_probs + i * GP_K, GP_K * sizeof(double));
                memcpy(acc_emb + w * GP_EMB, acc_emb + i * GP_EMB, GP_EMB * sizeof(double));
                memcpy(h_f16 + w * GP_D, h_f16 + i * GP_D, GP_D * sizeof(uint16_t));
                track_id[w] = track_id[i];
            }
            w++;
        }
        n_rep = w;
        if (n_rep == 0) { ok = 1; goto cleanup; }
    }

    /* 5. Decode step 2: global _agglo on tracklets (tau2 = 0.4, lam = 0.5) */
    inv = (int *)malloc(n_rep * sizeof(int));
    if (!inv) goto cleanup;
    {
        /* Map unique track_ids to 0..M-1 */
        int *tids = (int *)malloc(n_rep * sizeof(int));
        int M = 0;
        for (size_t i = 0; i < n_rep; ++i) {
            int tid = track_id[i];
            int found = -1;
            for (int j = 0; j < M; ++j) if (tids[j] == tid) { found = j; break; }
            if (found < 0) { found = M; tids[M++] = tid; }
            inv[i] = found;
        }
        free(tids);

        if (M > 1) {
            double *me = (double *)calloc((size_t)M * GP_EMB, sizeof(double));
            double *mp = (double *)calloc((size_t)M * GP_K, sizeof(double));
            double *sz = (double *)calloc((size_t)M, sizeof(double));
            for (size_t i = 0; i < n_rep; ++i) {
                int c = inv[i];
                sz[c] += 1.0;
                for (int d = 0; d < GP_EMB; ++d) me[c * GP_EMB + d] += acc_emb[i * GP_EMB + d];
                double pn2 = 0.0;
                for (int k = 0; k < GP_K; ++k) pn2 += acc_probs[i * GP_K + k] * acc_probs[i * GP_K + k];
                double inv_pn = 1.0 / (sqrt(pn2) > 1e-9 ? sqrt(pn2) : 1e-9);
                for (int k = 0; k < GP_K; ++k) mp[c * GP_K + k] += acc_probs[i * GP_K + k] * inv_pn;
            }
            for (int c = 0; c < M; ++c) {
                for (int d = 0; d < GP_EMB; ++d) me[c * GP_EMB + d] /= sz[c];
                for (int k = 0; k < GP_K; ++k) mp[c * GP_K + k] /= sz[c];
            }
            double *Dm = (double *)malloc((size_t)M * M * sizeof(double));
            int *alive = (int *)malloc((size_t)M * sizeof(int));
            int *lab = (int *)malloc((size_t)M * sizeof(int));
            for (int i = 0; i < M; ++i) { alive[i] = 1; lab[i] = i; }
            for (int i = 0; i < M; ++i) {
                Dm[i * M + i] = DBL_MAX;
                for (int j = i + 1; j < M; ++j) {
                    double de = 0.0, dp = 0.0;
                    for (int d = 0; d < GP_EMB; ++d) de += me[i * GP_EMB + d] * me[j * GP_EMB + d];
                    for (int k = 0; k < GP_K; ++k) dp += mp[i * GP_K + k] * mp[j * GP_K + k];
                    Dm[i * M + j] = Dm[j * M + i] = (1.0 - de) + 0.5 * (1.0 - dp);
                }
            }
            if (M > 600) {
                struct { int id; double sz; } *ord = malloc((size_t)M * sizeof(*ord));
                for (int i = 0; i < M; ++i) { ord[i].id = i; ord[i].sz = sz[i]; }
                qsort(ord, (size_t)M, sizeof(*ord), cmp_size_desc_idx);
                for (int k = 600; k < M; ++k) {
                    int s = ord[k].id;
                    for (int j = 0; j < M; ++j) Dm[s * M + j] = Dm[j * M + s] = DBL_MAX;
                }
                free(ord);
            }
            for (;;) {
                int bi = -1, bj = -1; double best = DBL_MAX;
                for (int i = 0; i < M; ++i) {
                    if (!alive[i]) continue;
                    for (int j = i + 1; j < M; ++j) {
                        if (alive[j] && Dm[i * M + j] < best) { best = Dm[i * M + j]; bi = i; bj = j; }
                    }
                }
                if (bi < 0 || best > 0.4) break;
                double si = sz[bi], sj = sz[bj], ssum = si + sj;
                for (int d = 0; d < GP_EMB; ++d) me[bi * GP_EMB + d] = (si * me[bi * GP_EMB + d] + sj * me[bj * GP_EMB + d]) / ssum;
                for (int k = 0; k < GP_K; ++k) mp[bi * GP_K + k] = (si * mp[bi * GP_K + k] + sj * mp[bj * GP_K + k]) / ssum;
                sz[bi] = ssum;
                alive[bj] = 0;
                for (int k = 0; k < M; ++k) if (lab[k] == bj) lab[k] = bi;
                for (int k = 0; k < M; ++k) Dm[bj * M + k] = Dm[k * M + bj] = DBL_MAX;
                for (int k = 0; k < M; ++k) {
                    if (!alive[k] || k == bi) { Dm[bi * M + k] = Dm[k * M + bi] = DBL_MAX; continue; }
                    double de = 0.0, dp = 0.0;
                    for (int d = 0; d < GP_EMB; ++d) de += me[bi * GP_EMB + d] * me[k * GP_EMB + d];
                    for (int c = 0; c < GP_K; ++c) dp += mp[bi * GP_K + c] * mp[k * GP_K + c];
                    Dm[bi * M + k] = Dm[k * M + bi] = (1.0 - de) + 0.5 * (1.0 - dp);
                }
            }
            for (size_t i = 0; i < n_rep; ++i) inv[i] = lab[inv[i]];
            free(me); free(mp); free(sz); free(Dm); free(alive); free(lab);
        }
    }

    /* 6. Decode steps 3-4: compact labels, refine (2 passes), small fold, absorb_small */
    int T_tr = 0;
    {
        int *uniq = (int *)malloc(n_rep * sizeof(int));
        for (size_t i = 0; i < n_rep; ++i) {
            int v = inv[i], f = -1;
            for (int j = 0; j < T_tr; ++j) if (uniq[j] == v) { f = j; break; }
            if (f < 0) { f = T_tr; uniq[T_tr++] = v; }
            inv[i] = f;
        }
        free(uniq);
    }

    /* 2 k-means refine passes over tracks with size >= 30 */
    {
        int *sz = (int *)calloc((size_t)T_tr, sizeof(int));
        for (size_t i = 0; i < n_rep; ++i) sz[inv[i]]++;
        double *pn_all = (double *)malloc(n_rep * GP_K * sizeof(double));
        for (size_t i = 0; i < n_rep; ++i) {
            double n2 = 0.0;
            for (int k = 0; k < GP_K; ++k) n2 += acc_probs[i * GP_K + k] * acc_probs[i * GP_K + k];
            double inv_n = 1.0 / (sqrt(n2) > 1e-9 ? sqrt(n2) : 1e-9);
            for (int k = 0; k < GP_K; ++k) pn_all[i * GP_K + k] = acc_probs[i * GP_K + k] * inv_n;
        }
        for (int pass = 0; pass < 2; ++pass) {
            int *keepc = (int *)malloc((size_t)T_tr * sizeof(int));
            int nk = 0;
            for (int t = 0; t < T_tr; ++t) if (sz[t] >= 30) keepc[nk++] = t;
            if (nk < 2) { free(keepc); break; }
            double *cen = (double *)calloc((size_t)T_tr * GP_EMB, sizeof(double));
            double *pm = (double *)calloc((size_t)T_tr * GP_K, sizeof(double));
            for (size_t i = 0; i < n_rep; ++i) {
                int c = inv[i];
                for (int d = 0; d < GP_EMB; ++d) cen[c * GP_EMB + d] += acc_emb[i * GP_EMB + d];
                for (int k = 0; k < GP_K; ++k) pm[c * GP_K + k] += acc_probs[i * GP_K + k];
            }
            for (int j = 0; j < nk; ++j) {
                int c = keepc[j];
                double n2e = 0.0, n2p = 0.0;
                for (int d = 0; d < GP_EMB; ++d) n2e += cen[c * GP_EMB + d] * cen[c * GP_EMB + d];
                for (int k = 0; k < GP_K; ++k) n2p += pm[c * GP_K + k] * pm[c * GP_K + k];
                double ie = 1.0 / (sqrt(n2e) > 1e-9 ? sqrt(n2e) : 1e-9);
                double ip = 1.0 / (sqrt(n2p) > 1e-9 ? sqrt(n2p) : 1e-9);
                for (int d = 0; d < GP_EMB; ++d) cen[c * GP_EMB + d] *= ie;
                for (int k = 0; k < GP_K; ++k) pm[c * GP_K + k] *= ip;
            }
            memset(sz, 0, (size_t)T_tr * sizeof(int));
            for (size_t i = 0; i < n_rep; ++i) {
                int best_c = keepc[0];
                double best_s = -DBL_MAX;
                for (int j = 0; j < nk; ++j) {
                    int c = keepc[j];
                    double se = 0.0, sp = 0.0;
                    for (int d = 0; d < GP_EMB; ++d) se += acc_emb[i * GP_EMB + d] * cen[c * GP_EMB + d];
                    for (int k = 0; k < GP_K; ++k) sp += pn_all[i * GP_K + k] * pm[c * GP_K + k];
                    double sc = se + 0.5 * sp;
                    if (sc > best_s) { best_s = sc; best_c = c; }
                }
                inv[i] = best_c;
                sz[best_c]++;
            }
            free(keepc); free(cen); free(pm);
        }
        free(pn_all);

        /* Fold small tracks (< 30 notes) into best-matching big track */
        double *mass = (double *)calloc((size_t)T_tr * GP_K, sizeof(double));
        for (size_t i = 0; i < n_rep; ++i)
            for (int k = 0; k < GP_K; ++k) mass[inv[i] * GP_K + k] += acc_probs[i * GP_K + k];
        for (int t = 0; t < T_tr; ++t) {
            double n2 = 0.0;
            for (int k = 0; k < GP_K; ++k) n2 += mass[t * GP_K + k] * mass[t * GP_K + k];
            double inv_n = 1.0 / (sqrt(n2) > 1e-9 ? sqrt(n2) : 1e-9);
            for (int k = 0; k < GP_K; ++k) mass[t * GP_K + k] *= inv_n;
        }
        int *big = (int *)malloc((size_t)T_tr * sizeof(int));
        uint8_t *isbig = (uint8_t *)calloc((size_t)T_tr, 1);
        int nbig = 0, largest = 0;
        for (int t = 0; t < T_tr; ++t) {
            if (sz[t] > sz[largest]) largest = t;
            if (sz[t] >= 30) { big[nbig++] = t; isbig[t] = 1; }
        }
        if (nbig == 0) { big[nbig++] = largest; isbig[largest] = 1; }
        for (int t = 0; t < T_tr; ++t) {
            if (!isbig[t] && sz[t] > 0) {
                int best_b = big[0]; double best_s = -DBL_MAX;
                for (int j = 0; j < nbig; ++j) {
                    int b = big[j];
                    double s = 0.0;
                    for (int k = 0; k < GP_K; ++k) s += mass[b * GP_K + k] * mass[t * GP_K + k];
                    if (s > best_s) { best_s = s; best_b = b; }
                }
                for (size_t i = 0; i < n_rep; ++i) if (inv[i] == t) inv[i] = best_b;
            }
        }
        free(sz); free(mass); free(big); free(isbig);
    }

    /* absorb_small(frac=0.25, tau_a=0.3) */
    for (;;) {
        int *uniq = (int *)malloc(n_rep * sizeof(int));
        int *lab = (int *)malloc(n_rep * sizeof(int));
        int M = 0;
        for (size_t i = 0; i < n_rep; ++i) {
            int v = inv[i], f = -1;
            for (int j = 0; j < M; ++j) if (uniq[j] == v) { f = j; break; }
            if (f < 0) { f = M; uniq[M++] = v; }
            lab[i] = f;
        }
        if (M < 2) { free(uniq); free(lab); break; }
        double *sz = (double *)calloc((size_t)M, sizeof(double));
        double *cen = (double *)calloc((size_t)M * GP_EMB, sizeof(double));
        for (size_t i = 0; i < n_rep; ++i) {
            sz[lab[i]] += 1.0;
            for (int d = 0; d < GP_EMB; ++d) cen[lab[i] * GP_EMB + d] += acc_emb[i * GP_EMB + d];
        }
        for (int c = 0; c < M; ++c)
            for (int d = 0; d < GP_EMB; ++d) cen[c * GP_EMB + d] /= sz[c];
        struct { int id; double sz; } *ord = malloc((size_t)M * sizeof(*ord));
        for (int c = 0; c < M; ++c) { ord[c].id = c; ord[c].sz = sz[c]; }
        qsort(ord, (size_t)M, sizeof(*ord), cmp_size_asc_idx);
        int dissolved = 0;
        for (int oi = 0; oi < M; ++oi) {
            int t = ord[oi].id;
            double share = sz[t] / (double)n_rep;
            if (share >= 0.25) break;
            double thr = 0.3 * (1.0 - share / 0.25);
            double min_d = DBL_MAX;
            int has_big = 0;
            for (int b = 0; b < M; ++b) {
                if (sz[b] <= sz[t]) continue;
                has_big = 1;
                double dot = 0.0;
                for (int d = 0; d < GP_EMB; ++d) dot += cen[b * GP_EMB + d] * cen[t * GP_EMB + d];
                if (1.0 - dot < min_d) min_d = 1.0 - dot;
            }
            if (has_big && min_d < thr) {
                /* Dissolve track t: send each note to nearest larger track's normalized centre */
                double *cu = (double *)malloc((size_t)M * GP_EMB * sizeof(double));
                for (int b = 0; b < M; ++b) {
                    if (sz[b] <= sz[t]) continue;
                    double n2 = 0.0;
                    for (int d = 0; d < GP_EMB; ++d) n2 += cen[b * GP_EMB + d] * cen[b * GP_EMB + d];
                    double inv_n = 1.0 / (sqrt(n2) > 1e-9 ? sqrt(n2) : 1e-9);
                    for (int d = 0; d < GP_EMB; ++d) cu[b * GP_EMB + d] = cen[b * GP_EMB + d] * inv_n;
                }
                for (size_t i = 0; i < n_rep; ++i) {
                    if (lab[i] != t) continue;
                    int best_b = -1; double best_dot = -DBL_MAX;
                    for (int b = 0; b < M; ++b) {
                        if (sz[b] <= sz[t]) continue;
                        double dot = 0.0;
                        for (int d = 0; d < GP_EMB; ++d) dot += acc_emb[i * GP_EMB + d] * cu[b * GP_EMB + d];
                        if (dot > best_dot) { best_dot = dot; best_b = b; }
                    }
                    if (best_b >= 0) inv[i] = uniq[best_b];
                }
                free(cu);
                dissolved = 1;
                break;
            }
        }
        free(ord); free(sz); free(cen); free(uniq); free(lab);
        if (!dissolved) break;
    }

    /* 7. Step 5: Track naming (alpha = 0.5, track head in float64, expected CREDIT, merge by instrument) */
    {
        int *uniq = (int *)malloc(n_rep * sizeof(int));
        int M = 0;
        for (size_t i = 0; i < n_rep; ++i) {
            int v = inv[i], f = -1;
            for (int j = 0; j < M; ++j) if (uniq[j] == v) { f = j; break; }
            if (f < 0) uniq[M++] = v;
        }
        /* Map each note's cluster to instrument k in [0..72] */
        int *note_inst = (int *)malloc(n_rep * sizeof(int));
        for (int ci = 0; ci < M; ++ci) {
            int cid = uniq[ci];
            size_t cnt = 0;
            for (size_t i = 0; i < n_rep; ++i) if (inv[i] == cid) cnt++;
            size_t *ids = (size_t *)malloc(cnt * sizeof(size_t));
            size_t w = 0;
            for (size_t i = 0; i < n_rep; ++i) if (inv[i] == cid) ids[w++] = i;

            double pn[GP_K] = {0}, pn_sum = 0.0;
            double hmean[GP_D] = {0};
            double p_sum = 0.0, p_min = 1e9, p_max = -1e9;
            for (size_t j = 0; j < cnt; ++j) {
                size_t idx = ids[j];
                for (int k = 0; k < GP_K; ++k) { pn[k] += acc_probs[idx * GP_K + k]; pn_sum += acc_probs[idx * GP_K + k]; }
                for (int d = 0; d < GP_D; ++d) hmean[d] += (double)vt_f16_to_f32(h_f16[idx * GP_D + d]);
                double pn_val = (double)nt[idx].pitch / 64.0 - 1.0;
                p_sum += pn_val;
                if (pn_val < p_min) p_min = pn_val;
                if (pn_val > p_max) p_max = pn_val;
            }
            for (int d = 0; d < GP_D; ++d) hmean[d] /= (double)cnt;
            double p_mu = p_sum / (double)cnt, p_var = 0.0;
            for (size_t j = 0; j < cnt; ++j) {
                double d = ((double)nt[ids[j]].pitch / 64.0 - 1.0) - p_mu;
                p_var += d * d;
            }
            double poly = 0.0;
            if (cnt <= 3000) {
                size_t n_poly = 0;
                for (size_t a = 0; a < cnt; ++a) {
                    int ov = 0;
                    double oa = nt[ids[a]].on, ea = nt[ids[a]].off;
                    if (ea < oa + 0.02) ea = oa + 0.02;
                    for (size_t b = 0; b < cnt; ++b) {
                        double ob = nt[ids[b]].on, eb = nt[ids[b]].off;
                        if (eb < ob + 0.02) eb = ob + 0.02;
                        double mn_e = ea < eb ? ea : eb;
                        double mx_o = oa > ob ? oa : ob;
                        if (mn_e > mx_o + 0.03) ov++;
                    }
                    if (ov > 1) n_poly++;
                }
                poly = (double)n_poly / (double)cnt;
            }
            double th_in[GP_D + 6];
            memcpy(th_in, hmean, GP_D * sizeof(double));
            th_in[GP_D + 0] = p_mu;
            th_in[GP_D + 1] = sqrt(p_var / (double)cnt);
            th_in[GP_D + 2] = p_min;
            th_in[GP_D + 3] = p_max;
            th_in[GP_D + 4] = log1p((double)cnt) / 5.0;
            th_in[GP_D + 5] = poly;

            double t1[GP_D], t2[GP_D], lt[GP_K];
            matvec_f64(GP_D, GP_D + 6, m->th0_w, m->th0_b, th_in, t1); gelu_f64(t1, GP_D);
            matvec_f64(GP_D, GP_D, m->th2_w, m->th2_b, t1, t2); gelu_f64(t2, GP_D);
            matvec_f64(GP_K, GP_D, m->th4_w, m->th4_b, t2, lt);
            double lmax = lt[0];
            for (int k = 1; k < GP_K; ++k) if (lt[k] > lmax) lmax = lt[k];
            double lse = 0.0;
            for (int k = 0; k < GP_K; ++k) lse += exp(lt[k] - lmax);
            double log_z = lmax + log(lse);

            double z[GP_K], zmax = -DBL_MAX;
            for (int k = 0; k < GP_K; ++k) {
                double ln_k = log(pn[k] / pn_sum > 1e-9 ? pn[k] / pn_sum : 1e-9);
                z[k] = 0.5 * (lt[k] - log_z) + 0.5 * ln_k;
                if (z[k] > zmax) zmax = z[k];
            }
            double q[GP_K], qsum = 0.0;
            for (int k = 0; k < GP_K; ++k) { q[k] = exp(z[k] - zmax); qsum += q[k]; }
            for (int k = 0; k < GP_K; ++k) q[k] /= qsum;

            int best_k = 0; double best_ec = -DBL_MAX;
            for (int a = 0; a < GP_K; ++a) {
                double ec = 0.0;
                for (int b = 0; b < GP_K; ++b) ec += credit_val(a, b) * q[b];
                if (ec > best_ec) { best_ec = ec; best_k = a; }
            }
            for (size_t j = 0; j < cnt; ++j) note_inst[ids[j]] = best_k;
            free(ids);
        }
        free(uniq);

        /* Merge tracks with same instrument k, dedup within 30 ms per pitch, map times * retune_ratio */
        struct grouped_track *out_tr = (struct grouped_track *)calloc(GP_K, sizeof(*out_tr));
        size_t n_out = 0;
        for (int k = 0; k < GP_K; ++k) {
            size_t cnt = 0;
            for (size_t i = 0; i < n_rep; ++i) if (note_inst[i] == k) cnt++;
            if (cnt == 0) continue;
            struct midi_note *raw_m = (struct midi_note *)malloc(cnt * sizeof(*raw_m));
            size_t w = 0;
            for (size_t i = 0; i < n_rep; ++i) {
                if (note_inst[i] != k) continue;
                double on = nt[i].on * retune_ratio;
                double off = nt[i].off * retune_ratio;
                if (off < on + 0.02) off = on + 0.02;
                float conf = (nt[i].slot > 0) ? meta[i * 12 + 5] : meta[i * 12 + 4];
                int vel = gp_clamp((int)(20.0 + 107.0 * (double)conf), 1, 127);
                raw_m[w++] = (struct midi_note){ on, off, nt[i].pitch, vel };
            }
            /* Dedup same pitch within 0.03 s */
            struct midi_note *dedup = (struct midi_note *)malloc(cnt * sizeof(*dedup));
            size_t nd = 0;
            for (int p = 0; p < 128; ++p) {
                double last_on = -1e9;
                for (size_t i = 0; i < cnt; ++i) {
                    if (raw_m[i].pitch != p) continue;
                    if (raw_m[i].onset - last_on <= 0.03) continue;
                    last_on = raw_m[i].onset;
                    dedup[nd++] = raw_m[i];
                }
            }
            free(raw_m);
            qsort(dedup, nd, sizeof(*dedup), cmp_midi_note_on);
            out_tr[n_out++] = (struct grouped_track){
                INST_TABLE[k].name, INST_TABLE[k].program, dedup, nd
            };
        }
        free(note_inst);
        qsort(out_tr, n_out, sizeof(*out_tr), cmp_track_len_desc);
        *tracks_out = out_tr;
        *n_tracks_out = n_out;
    }
    ok = 1;

cleanup:
    for (size_t i = 0; i < n_wins; ++i) { free(wins[i].sel); free(wins[i].emb); free(wins[i].probs); }
    free(wins); free(tnotes); free(nt); free(meta); free(feat_all); free(audio_i16);
    free(acc_probs); free(wsum); free(best_w); free(acc_emb); free(h_f16);
    free(track_id); free(inv);
    return ok;
}
