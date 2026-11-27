/* VTWT weight archive loader (F32 / IEEE-754 F16). */
#include "weights.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

_Static_assert(sizeof(struct vtwt_entry) == 152, "vtwt_entry layout mismatch");

static float f16_to_f32(uint16_t h) {
    uint32_t sign = ((uint32_t)h & 0x8000u) << 16;
    uint32_t exp = (h >> 10) & 0x1Fu;
    uint32_t mant = h & 0x3FFu;
    uint32_t bits;
    if (exp == 0) {
        if (mant == 0) {
            bits = sign;
        } else {
            exp = 1;
            while ((mant & 0x400u) == 0) {
                mant <<= 1;
                exp--;
            }
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

int vtwt_load(const char *path, struct vtwt_file *out) {
    memset(out, 0, sizeof(*out));
    FILE *fp = fopen(path, "rb");
    if (!fp) return 0;
    if (fseek(fp, 0, SEEK_END) != 0) { fclose(fp); return 0; }
    long sz = ftell(fp);
    if (sz < 16) { fclose(fp); return 0; }
    rewind(fp);

    uint8_t *buf = (uint8_t *)malloc((size_t)sz);
    if (!buf) { fclose(fp); return 0; }
    if (fread(buf, 1, (size_t)sz, fp) != (size_t)sz) {
        free(buf);
        fclose(fp);
        return 0;
    }
    fclose(fp);

    if (memcmp(buf, "VTWT", 4) != 0) { free(buf); return 0; }
    uint32_t version, num_tensors, header_size;
    memcpy(&version, buf + 4, 4);
    memcpy(&num_tensors, buf + 8, 4);
    memcpy(&header_size, buf + 12, 4);
    if (version != 1 || header_size > (size_t)sz) { free(buf); return 0; }
    if (16 + (size_t)num_tensors * sizeof(struct vtwt_entry) > header_size) {
        free(buf);
        return 0;
    }

    out->raw = buf;
    out->raw_size = (size_t)sz;
    out->num_tensors = num_tensors;
    out->entries = (const struct vtwt_entry *)(buf + 16);
    for (uint32_t i = 0; i < num_tensors; ++i) {
        const struct vtwt_entry *e = &out->entries[i];
        if (e->offset > out->raw_size || e->nbytes > out->raw_size - e->offset) {
            vtwt_free(out);
            return 0;
        }
    }
    return 1;
}

void vtwt_free(struct vtwt_file *f) {
    if (!f) return;
    free(f->raw);
    memset(f, 0, sizeof(*f));
}

const struct vtwt_entry *vtwt_find(const struct vtwt_file *f, const char *name) {
    if (!f || !f->entries || !name) return NULL;
    for (uint32_t i = 0; i < f->num_tensors; ++i) {
        if (strncmp(f->entries[i].name, name, VTWT_NAME_MAX) == 0)
            return &f->entries[i];
    }
    return NULL;
}

static size_t entry_numel(const struct vtwt_entry *e) {
    size_t n = 1;
    for (uint32_t i = 0; i < e->ndim && i < 4; ++i) n *= e->shape[i];
    return n;
}

float *vtwt_read_f32(const struct vtwt_file *f, const char *name,
                     uint32_t expect_ndim, const uint32_t *expect_shape) {
    const struct vtwt_entry *e = vtwt_find(f, name);
    if (!e) {
        fprintf(stderr, "Missing weight tensor: %s\n", name);
        return NULL;
    }
    if (expect_ndim > 0) {
        if (e->ndim != expect_ndim) {
            fprintf(stderr, "Tensor %s ndim=%u expected %u\n", name, e->ndim, expect_ndim);
            return NULL;
        }
        if (expect_shape) {
            for (uint32_t i = 0; i < expect_ndim; ++i) {
                if (expect_shape[i] != 0 && e->shape[i] != expect_shape[i]) {
                    fprintf(stderr, "Tensor %s shape[%u]=%u expected %u\n",
                            name, i, e->shape[i], expect_shape[i]);
                    return NULL;
                }
            }
        }
    }
    size_t n = entry_numel(e);
    float *out = (float *)malloc(n * sizeof(float));
    if (!out) return NULL;
    const uint8_t *src = f->raw + e->offset;
    if (e->dtype == VTWT_DTYPE_F32) {
        if (e->nbytes != n * 4) { free(out); return NULL; }
        memcpy(out, src, n * 4);
    } else if (e->dtype == VTWT_DTYPE_F16) {
        if (e->nbytes != n * 2) { free(out); return NULL; }
        const uint16_t *h = (const uint16_t *)src;
        for (size_t i = 0; i < n; ++i) out[i] = f16_to_f32(h[i]);
    } else {
        free(out);
        return NULL;
    }
    return out;
}

float *vtwt_read_conv2d_nhwc(const struct vtwt_file *f, const char *name,
                             uint32_t Cout, uint32_t Cin, uint32_t kh, uint32_t kw) {
    uint32_t shape[4] = { Cout, Cin, kh, kw };
    float *oihw = vtwt_read_f32(f, name, 4, shape);
    if (!oihw) return NULL;
    size_t n = (size_t)Cout * Cin * kh * kw;
    float *ohwi = (float *)malloc(n * sizeof(float));
    if (!ohwi) { free(oihw); return NULL; }
    for (uint32_t o = 0; o < Cout; ++o)
        for (uint32_t c = 0; c < Cin; ++c)
            for (uint32_t y = 0; y < kh; ++y)
                for (uint32_t x = 0; x < kw; ++x)
                    ohwi[(((size_t)o * kh + y) * kw + x) * Cin + c] =
                        oihw[(((size_t)o * Cin + c) * kh + y) * kw + x];
    free(oihw);
    return ohwi;
}
