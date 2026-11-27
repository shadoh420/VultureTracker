/* Cross-platform SIMD (AVX2+FMA / NEON / scalar) + pthread tensor math engine. */
#include "nn.h"
#include <math.h>
#include <pthread.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

#ifdef __x86_64__
#include <immintrin.h>
#endif
#ifdef __aarch64__
#include <arm_neon.h>
#endif

/* =========================================================================
 * Persistent pthread worker pool
 * ========================================================================= */

enum { NN_MAX_THREADS = 16 };

struct nn_pool {
    int initialized;
    int n_threads;
    int shutdown;
    pthread_t workers[NN_MAX_THREADS];
    pthread_mutex_t mu;
    pthread_cond_t work_cv;
    pthread_cond_t done_cv;
    uint64_t generation;
    int pending;
    /* Current task */
    nn_work_fn fn;
    void *ctx;
    int n_items;
    int n_chunks;
};

static struct nn_pool g_pool;
static int g_has_avx2_fma = 0;

struct worker_arg {
    int id;
};
static struct worker_arg g_wargs[NN_MAX_THREADS];

static void run_chunk(int tid) {
    int n = g_pool.n_items;
    int c = g_pool.n_chunks;
    if (tid >= c) return;
    int start = (int)((int64_t)n * tid / c);
    int end = (int)((int64_t)n * (tid + 1) / c);
    if (start < end) g_pool.fn(start, end, g_pool.ctx);
}

static void *worker_loop(void *arg) {
    int tid = ((struct worker_arg *)arg)->id;
    uint64_t last_gen = 0;
    for (;;) {
        pthread_mutex_lock(&g_pool.mu);
        while (!g_pool.shutdown && g_pool.generation == last_gen)
            pthread_cond_wait(&g_pool.work_cv, &g_pool.mu);
        if (g_pool.shutdown) {
            pthread_mutex_unlock(&g_pool.mu);
            break;
        }
        last_gen = g_pool.generation;
        pthread_mutex_unlock(&g_pool.mu);

        run_chunk(tid);

        pthread_mutex_lock(&g_pool.mu);
        if (--g_pool.pending == 0) pthread_cond_signal(&g_pool.done_cv);
        pthread_mutex_unlock(&g_pool.mu);
    }
    return NULL;
}

void nn_init(int num_threads) {
    if (g_pool.initialized) return;
#ifdef __x86_64__
    g_has_avx2_fma = (__builtin_cpu_supports("avx2") && __builtin_cpu_supports("fma")) ? 1 : 0;
#else
    g_has_avx2_fma = 0;
#endif
    if (num_threads <= 0) {
        const char *env = getenv("MP3TOMIDI_THREADS");
        if (env && atoi(env) > 0) {
            num_threads = atoi(env);
        } else {
            long ncpu = sysconf(_SC_NPROCESSORS_ONLN);
            if (ncpu < 1) ncpu = 1;
            num_threads = (int)ncpu;
            if (num_threads > NN_MAX_THREADS) num_threads = NN_MAX_THREADS;
        }
    }
    if (num_threads < 1) num_threads = 1;
    if (num_threads > NN_MAX_THREADS) num_threads = NN_MAX_THREADS;

    memset(&g_pool, 0, sizeof(g_pool));
    g_pool.n_threads = num_threads;
    g_pool.initialized = 1;
    if (num_threads > 1) {
        pthread_mutex_init(&g_pool.mu, NULL);
        pthread_cond_init(&g_pool.work_cv, NULL);
        pthread_cond_init(&g_pool.done_cv, NULL);
        for (int i = 1; i < num_threads; ++i) {
            g_wargs[i].id = i;
            if (pthread_create(&g_pool.workers[i], NULL, worker_loop, &g_wargs[i]) != 0) {
                g_pool.n_threads = i;
                break;
            }
        }
    }
}

void nn_shutdown(void) {
    if (!g_pool.initialized) return;
    if (g_pool.n_threads > 1) {
        pthread_mutex_lock(&g_pool.mu);
        g_pool.shutdown = 1;
        pthread_cond_broadcast(&g_pool.work_cv);
        pthread_mutex_unlock(&g_pool.mu);
        for (int i = 1; i < g_pool.n_threads; ++i)
            pthread_join(g_pool.workers[i], NULL);
        pthread_mutex_destroy(&g_pool.mu);
        pthread_cond_destroy(&g_pool.work_cv);
        pthread_cond_destroy(&g_pool.done_cv);
    }
    g_pool.initialized = 0;
    g_pool.n_threads = 0;
}

int nn_num_threads(void) {
    if (!g_pool.initialized) nn_init(0);
    return g_pool.n_threads;
}

int nn_has_avx2_fma(void) {
    if (!g_pool.initialized) nn_init(0);
    return g_has_avx2_fma;
}

void nn_parallel_for(int n_items, int grain, nn_work_fn fn, void *ctx) {
    if (n_items <= 0) return;
    if (!g_pool.initialized) nn_init(0);
    if (grain < 1) grain = 1;
    int max_chunks = (n_items + grain - 1) / grain;
    int chunks = g_pool.n_threads < max_chunks ? g_pool.n_threads : max_chunks;
    if (chunks <= 1) {
        fn(0, n_items, ctx);
        return;
    }
    pthread_mutex_lock(&g_pool.mu);
    g_pool.fn = fn;
    g_pool.ctx = ctx;
    g_pool.n_items = n_items;
    g_pool.n_chunks = chunks;
    g_pool.pending = g_pool.n_threads - 1;
    g_pool.generation++;
    pthread_cond_broadcast(&g_pool.work_cv);
    pthread_mutex_unlock(&g_pool.mu);

    run_chunk(0);

    pthread_mutex_lock(&g_pool.mu);
    while (g_pool.pending > 0)
        pthread_cond_wait(&g_pool.done_cv, &g_pool.mu);
    pthread_mutex_unlock(&g_pool.mu);
}

/* =========================================================================
 * Tiled SGEMM: C[M, N] = A[M, K] @ B[N, K]^T (+ optional bias / accumulate)
 * ========================================================================= */

enum {
    GEMM_KC = 256,
    GEMM_MC = 96
};

/* Pack nr (<= 16) rows of B[n0..n0+nr-1, k0..k0+kc-1] into Bp[kc][16]. */
static inline void pack_b_16(const float *B, int ldb, int nr, int kc, float *Bp) {
    if (nr == 16) {
        for (int k = 0; k < kc; ++k) {
            float *dst = Bp + k * 16;
            for (int j = 0; j < 16; ++j)
                dst[j] = B[j * ldb + k];
        }
    } else {
        for (int k = 0; k < kc; ++k) {
            float *dst = Bp + k * 16;
            for (int j = 0; j < nr; ++j) dst[j] = B[j * ldb + k];
            for (int j = nr; j < 16; ++j) dst[j] = 0.0f;
        }
    }
}

#ifdef __x86_64__
__attribute__((target("avx2,fma")))
static void micro_6x16_avx2(int kc, const float *A, int lda, const float *Bp,
                            float *C, int ldc, int mr, int nr) {
    if (mr == 6 && nr == 16) {
        __m256 c00 = _mm256_loadu_ps(C + 0 * ldc);
        __m256 c01 = _mm256_loadu_ps(C + 0 * ldc + 8);
        __m256 c10 = _mm256_loadu_ps(C + 1 * ldc);
        __m256 c11 = _mm256_loadu_ps(C + 1 * ldc + 8);
        __m256 c20 = _mm256_loadu_ps(C + 2 * ldc);
        __m256 c21 = _mm256_loadu_ps(C + 2 * ldc + 8);
        __m256 c30 = _mm256_loadu_ps(C + 3 * ldc);
        __m256 c31 = _mm256_loadu_ps(C + 3 * ldc + 8);
        __m256 c40 = _mm256_loadu_ps(C + 4 * ldc);
        __m256 c41 = _mm256_loadu_ps(C + 4 * ldc + 8);
        __m256 c50 = _mm256_loadu_ps(C + 5 * ldc);
        __m256 c51 = _mm256_loadu_ps(C + 5 * ldc + 8);

        const float *a0 = A + 0 * lda;
        const float *a1 = A + 1 * lda;
        const float *a2 = A + 2 * lda;
        const float *a3 = A + 3 * lda;
        const float *a4 = A + 4 * lda;
        const float *a5 = A + 5 * lda;

        for (int k = 0; k < kc; ++k) {
            __m256 b0 = _mm256_load_ps(Bp + k * 16);
            __m256 b1 = _mm256_load_ps(Bp + k * 16 + 8);
            __m256 va;
            va = _mm256_broadcast_ss(a0 + k); c00 = _mm256_fmadd_ps(va, b0, c00); c01 = _mm256_fmadd_ps(va, b1, c01);
            va = _mm256_broadcast_ss(a1 + k); c10 = _mm256_fmadd_ps(va, b0, c10); c11 = _mm256_fmadd_ps(va, b1, c11);
            va = _mm256_broadcast_ss(a2 + k); c20 = _mm256_fmadd_ps(va, b0, c20); c21 = _mm256_fmadd_ps(va, b1, c21);
            va = _mm256_broadcast_ss(a3 + k); c30 = _mm256_fmadd_ps(va, b0, c30); c31 = _mm256_fmadd_ps(va, b1, c31);
            va = _mm256_broadcast_ss(a4 + k); c40 = _mm256_fmadd_ps(va, b0, c40); c41 = _mm256_fmadd_ps(va, b1, c41);
            va = _mm256_broadcast_ss(a5 + k); c50 = _mm256_fmadd_ps(va, b0, c50); c51 = _mm256_fmadd_ps(va, b1, c51);
        }

        _mm256_storeu_ps(C + 0 * ldc, c00); _mm256_storeu_ps(C + 0 * ldc + 8, c01);
        _mm256_storeu_ps(C + 1 * ldc, c10); _mm256_storeu_ps(C + 1 * ldc + 8, c11);
        _mm256_storeu_ps(C + 2 * ldc, c20); _mm256_storeu_ps(C + 2 * ldc + 8, c21);
        _mm256_storeu_ps(C + 3 * ldc, c30); _mm256_storeu_ps(C + 3 * ldc + 8, c31);
        _mm256_storeu_ps(C + 4 * ldc, c40); _mm256_storeu_ps(C + 4 * ldc + 8, c41);
        _mm256_storeu_ps(C + 5 * ldc, c50); _mm256_storeu_ps(C + 5 * ldc + 8, c51);
        return;
    }
    float tmp[6][16] __attribute__((aligned(32)));
    memset(tmp, 0, sizeof(tmp));
    for (int i = 0; i < mr; ++i)
        for (int j = 0; j < nr; ++j)
            tmp[i][j] = C[i * ldc + j];
    for (int i = 0; i < mr; ++i) {
        __m256 acc0 = _mm256_load_ps(tmp[i]);
        __m256 acc1 = _mm256_load_ps(tmp[i] + 8);
        const float *ai = A + i * lda;
        for (int k = 0; k < kc; ++k) {
            __m256 va = _mm256_broadcast_ss(ai + k);
            acc0 = _mm256_fmadd_ps(va, _mm256_load_ps(Bp + k * 16), acc0);
            acc1 = _mm256_fmadd_ps(va, _mm256_load_ps(Bp + k * 16 + 8), acc1);
        }
        _mm256_store_ps(tmp[i], acc0);
        _mm256_store_ps(tmp[i] + 8, acc1);
    }
    for (int i = 0; i < mr; ++i)
        for (int j = 0; j < nr; ++j)
            C[i * ldc + j] = tmp[i][j];
}
#endif

#ifdef __aarch64__
static void micro_4x16_neon(int kc, const float *A, int lda, const float *Bp,
                            float *C, int ldc, int mr, int nr) {
    float tmp[4][16];
    memset(tmp, 0, sizeof(tmp));
    for (int i = 0; i < mr; ++i)
        for (int j = 0; j < nr; ++j)
            tmp[i][j] = C[i * ldc + j];
    for (int i = 0; i < mr; ++i) {
        float32x4_t acc0 = vld1q_f32(tmp[i] + 0);
        float32x4_t acc1 = vld1q_f32(tmp[i] + 4);
        float32x4_t acc2 = vld1q_f32(tmp[i] + 8);
        float32x4_t acc3 = vld1q_f32(tmp[i] + 12);
        const float *ai = A + i * lda;
        for (int k = 0; k < kc; ++k) {
            float32x4_t va = vdupq_n_f32(ai[k]);
            const float *bk = Bp + k * 16;
            acc0 = vfmaq_f32(acc0, va, vld1q_f32(bk + 0));
            acc1 = vfmaq_f32(acc1, va, vld1q_f32(bk + 4));
            acc2 = vfmaq_f32(acc2, va, vld1q_f32(bk + 8));
            acc3 = vfmaq_f32(acc3, va, vld1q_f32(bk + 12));
        }
        vst1q_f32(tmp[i] + 0, acc0);
        vst1q_f32(tmp[i] + 4, acc1);
        vst1q_f32(tmp[i] + 8, acc2);
        vst1q_f32(tmp[i] + 12, acc3);
    }
    for (int i = 0; i < mr; ++i)
        for (int j = 0; j < nr; ++j)
            C[i * ldc + j] = tmp[i][j];
}
#endif

static void micro_scalar(int kc, const float *A, int lda, const float *Bp,
                         float *C, int ldc, int mr, int nr) {
    for (int i = 0; i < mr; ++i) {
        float *ci = C + i * ldc;
        const float *ai = A + i * lda;
        for (int k = 0; k < kc; ++k) {
            float a = ai[k];
            const float *bk = Bp + k * 16;
            for (int j = 0; j < nr; ++j)
                ci[j] += a * bk[j];
        }
    }
}

static void sgemm_block(int m_start, int m_end, int n_start, int n_end, int K,
                        const float *A, int lda, const float *B, int ldb,
                        float *C, int ldc, const float *bias, int add_to_c) {
    /* Initialize C tile */
    for (int m = m_start; m < m_end; ++m) {
        float *cm = C + m * ldc;
        if (!add_to_c) {
            if (bias) memcpy(cm + n_start, bias + n_start, (size_t)(n_end - n_start) * sizeof(float));
            else memset(cm + n_start, 0, (size_t)(n_end - n_start) * sizeof(float));
        } else if (bias) {
            for (int n = n_start; n < n_end; ++n) cm[n] += bias[n];
        }
    }

    float Bp[GEMM_KC * 16] __attribute__((aligned(32)));
    int use_avx2 = g_has_avx2_fma;
#ifdef __x86_64__
    int mr_step = use_avx2 ? 6 : 4;
#else
    int mr_step = 4;
#endif
    (void)use_avx2;

    for (int k0 = 0; k0 < K; k0 += GEMM_KC) {
        int kc = K - k0;
        if (kc > GEMM_KC) kc = GEMM_KC;
        for (int m0 = m_start; m0 < m_end; m0 += GEMM_MC) {
            int mc = m_end - m0;
            if (mc > GEMM_MC) mc = GEMM_MC;
            for (int n0 = n_start; n0 < n_end; n0 += 16) {
                int nr = n_end - n0;
                if (nr > 16) nr = 16;
                pack_b_16(B + n0 * ldb + k0, ldb, nr, kc, Bp);
                for (int mi = 0; mi < mc; mi += mr_step) {
                    int mr = mc - mi;
                    if (mr > mr_step) mr = mr_step;
                    const float *a_ptr = A + (m0 + mi) * lda + k0;
                    float *c_ptr = C + (m0 + mi) * ldc + n0;
#ifdef __x86_64__
                    if (use_avx2) micro_6x16_avx2(kc, a_ptr, lda, Bp, c_ptr, ldc, mr, nr);
                    else micro_scalar(kc, a_ptr, lda, Bp, c_ptr, ldc, mr, nr);
#elif defined(__aarch64__)
                    micro_4x16_neon(kc, a_ptr, lda, Bp, c_ptr, ldc, mr, nr);
#else
                    micro_scalar(kc, a_ptr, lda, Bp, c_ptr, ldc, mr, nr);
#endif
                }
            }
        }
    }
}

struct sgemm_ctx {
    int M, N, K;
    const float *A; int lda;
    const float *B; int ldb;
    float *C; int ldc;
    const float *bias;
    int add_to_c;
    int split_n;
};

static void sgemm_worker(int start, int end, void *arg) {
    struct sgemm_ctx *ctx = (struct sgemm_ctx *)arg;
    if (ctx->split_n) {
        int n0 = start * 16;
        int n1 = end * 16;
        if (n1 > ctx->N) n1 = ctx->N;
        if (n0 < n1)
            sgemm_block(0, ctx->M, n0, n1, ctx->K, ctx->A, ctx->lda,
                        ctx->B, ctx->ldb, ctx->C, ctx->ldc, ctx->bias, ctx->add_to_c);
    } else {
        int m0 = start * 6;
        int m1 = end * 6;
        if (m1 > ctx->M) m1 = ctx->M;
        if (m0 < m1)
            sgemm_block(m0, m1, 0, ctx->N, ctx->K, ctx->A, ctx->lda,
                        ctx->B, ctx->ldb, ctx->C, ctx->ldc, ctx->bias, ctx->add_to_c);
    }
}

void nn_sgemm_nt(int M, int N, int K,
                 const float *A, int lda,
                 const float *B, int ldb,
                 float *C, int ldc,
                 const float *bias, int add_to_c) {
    if (M <= 0 || N <= 0) return;
    if (!g_pool.initialized) nn_init(0);
    struct sgemm_ctx ctx = { M, N, K, A, lda, B, ldb, C, ldc, bias, add_to_c, 0 };
    int64_t flops = (int64_t)M * (int64_t)N * (int64_t)K;
    if (flops < 262144 || g_pool.n_threads <= 1) {
        sgemm_block(0, M, 0, N, K, A, lda, B, ldb, C, ldc, bias, add_to_c);
        return;
    }
    int m_tiles = (M + 5) / 6;
    int n_tiles = (N + 15) / 16;
    if (m_tiles >= g_pool.n_threads * 2 || m_tiles >= n_tiles) {
        ctx.split_n = 0;
        nn_parallel_for(m_tiles, 1, sgemm_worker, &ctx);
    } else {
        ctx.split_n = 1;
        nn_parallel_for(n_tiles, 1, sgemm_worker, &ctx);
    }
}

/* =========================================================================
 * Elementwise / Normalization / Conv2d helpers
 * ========================================================================= */

struct gelu_ctx { float *x; size_t chunk; size_t total; };
static void gelu_worker(int start, int end, void *arg) {
    struct gelu_ctx *c = (struct gelu_ctx *)arg;
    size_t i0 = (size_t)start * c->chunk;
    size_t i1 = (size_t)end * c->chunk;
    if (i1 > c->total) i1 = c->total;
    const float inv_sqrt2 = 0.7071067811865475244f;
    float *x = c->x;
    for (size_t i = i0; i < i1; ++i) {
        float v = x[i];
        x[i] = 0.5f * v * (1.0f + erff(v * inv_sqrt2));
    }
}

void nn_gelu_inplace(float *x, size_t n) {
    if (n < 65536) {
        const float inv_sqrt2 = 0.7071067811865475244f;
        for (size_t i = 0; i < n; ++i) {
            float v = x[i];
            x[i] = 0.5f * v * (1.0f + erff(v * inv_sqrt2));
        }
        return;
    }
    size_t chunk = 4096;
    int blocks = (int)((n + chunk - 1) / chunk);
    struct gelu_ctx ctx = { x, chunk, n };
    nn_parallel_for(blocks, 4, gelu_worker, &ctx);
}

struct ln_ctx {
    const float *x; float *y; int C; const float *w; const float *b; float eps;
};
static void ln_worker(int start, int end, void *arg) {
    struct ln_ctx *c = (struct ln_ctx *)arg;
    int C = c->C;
    float inv_c = 1.0f / (float)C;
    for (int i = start; i < end; ++i) {
        const float *xi = c->x + (size_t)i * C;
        float *yi = c->y + (size_t)i * C;
        double sum = 0.0;
        for (int j = 0; j < C; ++j) sum += (double)xi[j];
        float mean = (float)(sum * inv_c);
        double var_sum = 0.0;
        for (int j = 0; j < C; ++j) {
            double d = (double)xi[j] - (double)mean;
            var_sum += d * d;
        }
        float inv_std = 1.0f / sqrtf((float)(var_sum * inv_c) + c->eps);
        if (c->w && c->b) {
            for (int j = 0; j < C; ++j)
                yi[j] = (xi[j] - mean) * inv_std * c->w[j] + c->b[j];
        } else {
            for (int j = 0; j < C; ++j)
                yi[j] = (xi[j] - mean) * inv_std;
        }
    }
}

void nn_layernorm(const float *x, float *y, int N, int C,
                  const float *w, const float *b, float eps) {
    struct ln_ctx ctx = { x, y, C, w, b, eps };
    if (N < 128) ln_worker(0, N, &ctx);
    else nn_parallel_for(N, 32, ln_worker, &ctx);
}

void nn_bn_params(const float *w, const float *b, const float *mean, const float *var,
                  float eps, int C, float *scale, float *shift) {
    for (int c = 0; c < C; ++c) {
        double s = (double)w[c] / sqrt((double)var[c] + (double)eps);
        scale[c] = (float)s;
        shift[c] = (float)((double)b[c] - (double)mean[c] * s);
    }
}

struct aff_ctx {
    const float *x; float *y; int C; const float *scale; const float *shift;
};
static void aff_worker(int start, int end, void *arg) {
    struct aff_ctx *ctx = (struct aff_ctx *)arg;
    int C = ctx->C;
    const float *sc = ctx->scale, *sh = ctx->shift;
    for (int i = start; i < end; ++i) {
        const float *xi = ctx->x + (size_t)i * C;
        float *yi = ctx->y + (size_t)i * C;
        for (int c = 0; c < C; ++c) yi[c] = xi[c] * sc[c] + sh[c];
    }
}

void nn_affine_channel(const float *x, float *y, int N, int C,
                       const float *scale, const float *shift) {
    struct aff_ctx ctx = { x, y, C, scale, shift };
    if ((int64_t)N * C < 65536) aff_worker(0, N, &ctx);
    else nn_parallel_for(N, 64, aff_worker, &ctx);
}

/* Im2col + SGEMM 2D convolution in NHWC, tiled by output rows to cap scratch RAM. */
struct im2col_ctx {
    const float *in;
    int H, W, Cin;
    int kh, kw, sh, sw, ph, pw;
    int Wout, row0;
    float *col;
};

static void im2col_worker(int start, int end, void *arg) {
    struct im2col_ctx *c = (struct im2col_ctx *)arg;
    int K = c->kh * c->kw * c->Cin;
    for (int r = start; r < end; ++r) {
        int oh = c->row0 + r;
        int ih0 = oh * c->sh - c->ph;
        for (int ow = 0; ow < c->Wout; ++ow) {
            int iw0 = ow * c->sw - c->pw;
            float *dst = c->col + ((size_t)r * c->Wout + ow) * K;
            for (int kh_i = 0; kh_i < c->kh; ++kh_i) {
                int ih = ih0 + kh_i;
                if (ih < 0 || ih >= c->H) {
                    memset(dst + (size_t)kh_i * c->kw * c->Cin, 0,
                           (size_t)c->kw * c->Cin * sizeof(float));
                    continue;
                }
                for (int kw_i = 0; kw_i < c->kw; ++kw_i) {
                    int iw = iw0 + kw_i;
                    float *p = dst + ((size_t)kh_i * c->kw + kw_i) * c->Cin;
                    if (iw < 0 || iw >= c->W) {
                        memset(p, 0, (size_t)c->Cin * sizeof(float));
                    } else {
                        memcpy(p, c->in + ((size_t)ih * c->W + iw) * c->Cin,
                               (size_t)c->Cin * sizeof(float));
                    }
                }
            }
        }
    }
}

int nn_conv2d_nhwc(const float *in, int H, int W, int Cin,
                   const float *w, const float *b,
                   int Cout, int kh, int kw, int sh, int sw, int ph, int pw,
                   float *out) {
    int Hout = (H + 2 * ph - kh) / sh + 1;
    int Wout = (W + 2 * pw - kw) / sw + 1;
    int K = kh * kw * Cin;
    if (Hout <= 0 || Wout <= 0) return 1;

    /* Tile Hout into strips so col buffer stays <= ~16 MB. */
    size_t row_floats = (size_t)Wout * (size_t)K;
    int strip_h = (int)((4 * 1024 * 1024) / (row_floats ? row_floats : 1));
    if (strip_h < 1) strip_h = 1;
    if (strip_h > Hout) strip_h = Hout;

    float *col = (float *)malloc((size_t)strip_h * row_floats * sizeof(float));
    if (!col) return 0;

    for (int r0 = 0; r0 < Hout; r0 += strip_h) {
        int rh = Hout - r0;
        if (rh > strip_h) rh = strip_h;
        struct im2col_ctx ictx = { in, H, W, Cin, kh, kw, sh, sw, ph, pw, Wout, r0, col };
        nn_parallel_for(rh, 2, im2col_worker, &ictx);
        int M = rh * Wout;
        nn_sgemm_nt(M, Cout, K, col, K, w, K,
                    out + (size_t)r0 * Wout * Cout, Cout, b, 0);
    }

    free(col);
    return 1;
}
