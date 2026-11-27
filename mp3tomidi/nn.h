/* Cross-platform SIMD + pthread tensor math primitives for mp3tomidi.
 * Channels-last layout: (N, C) or (T, P, C) with C contiguous. */
#ifndef MP3TOMIDI_NN_H
#define MP3TOMIDI_NN_H

#include <stddef.h>

typedef void (*nn_work_fn)(int start, int end, void *ctx);

/* Initialize thread pool (num_threads <= 0 auto-detects physical core count). */
void nn_init(int num_threads);
void nn_shutdown(void);
int nn_num_threads(void);
int nn_has_avx2_fma(void);

/* Run fn(start, end, ctx) partitioned across [0, n_items) on the thread pool. */
void nn_parallel_for(int n_items, int grain, nn_work_fn fn, void *ctx);

/* C[M, N] = (add_to_c ? C : 0) + (bias ? bias[n] : 0) + A[M, K] @ B[N, K]^T. */
void nn_sgemm_nt(int M, int N, int K,
                 const float *A, int lda,
                 const float *B, int ldb,
                 float *C, int ldc,
                 const float *bias, int add_to_c);

/* Exact GELU: x * 0.5 * (1 + erf(x / sqrt(2))), multithreaded for large arrays. */
void nn_gelu_inplace(float *x, size_t n);

/* LayerNorm over the last axis C for N rows: y = (x - mean) / sqrt(var + eps) * w + b.
 * x and y may alias. */
void nn_layernorm(const float *x, float *y, int N, int C,
                  const float *w, const float *b, float eps);

/* Compute folded BatchNorm scale & shift: scale = w / sqrt(var + eps), shift = b - mean * scale. */
void nn_bn_params(const float *w, const float *b, const float *mean, const float *var,
                  float eps, int C, float *scale, float *shift);

/* Apply y[i, c] = x[i, c] * scale[c] + shift[c] over N rows of C channels (in-place allowed). */
void nn_affine_channel(const float *x, float *y, int N, int C,
                       const float *scale, const float *shift);

/* 2D convolution on NHWC tensors:
 * in:  [H, W, Cin]
 * w:   [Cout, kh, kw, Cin]  (repacked from PyTorch [Cout, Cin, kh, kw])
 * b:   [Cout] or NULL
 * out: [Hout, Wout, Cout] where Hout = (H + 2*ph - kh)/sh + 1, Wout = (W + 2*pw - kw)/sw + 1.
 * Returns 1 on success, 0 on OOM. */
int nn_conv2d_nhwc(const float *in, int H, int W, int Cin,
                   const float *w, const float *b,
                   int Cout, int kh, int kw, int sh, int sw, int ph, int pw,
                   float *out);

#endif
