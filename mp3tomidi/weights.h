/* Binary weight archive (VTWT) loader supporting F32 and F16 tensors.
 * Works seamlessly with regular files and Cosmopolitan /zip/... embedded paths. */
#ifndef MP3TOMIDI_WEIGHTS_H
#define MP3TOMIDI_WEIGHTS_H

#include <stddef.h>
#include <stdint.h>

enum {
    VTWT_DTYPE_F32 = 0,
    VTWT_DTYPE_F16 = 1,
    VTWT_NAME_MAX = 112
};

struct vtwt_entry {
    char name[VTWT_NAME_MAX];
    uint32_t dtype;
    uint32_t ndim;
    uint32_t shape[4];
    uint64_t offset;
    uint64_t nbytes;
};

struct vtwt_file {
    uint8_t *raw;
    size_t raw_size;
    uint32_t num_tensors;
    const struct vtwt_entry *entries;
};

int vtwt_load(const char *path, struct vtwt_file *out);
void vtwt_free(struct vtwt_file *f);

const struct vtwt_entry *vtwt_find(const struct vtwt_file *f, const char *name);

/* Decode tensor `name` into a newly malloc'd float32 array.
 * If expect_ndim > 0, checks ndim and shape[0..expect_ndim-1] (0 = wildcard).
 * Returns NULL on missing tensor, shape mismatch, or OOM. */
float *vtwt_read_f32(const struct vtwt_file *f, const char *name,
                     uint32_t expect_ndim, const uint32_t *expect_shape);

/* Decode a 4D Conv2d weight [Cout, Cin, kh, kw] and transpose to NHWC [Cout, kh, kw, Cin]. */
float *vtwt_read_conv2d_nhwc(const struct vtwt_file *f, const char *name,
                             uint32_t Cout, uint32_t Cin, uint32_t kh, uint32_t kw);

#endif
