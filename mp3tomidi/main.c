/* Standalone zero-dependency Cosmopolitan APE audio-to-MIDI CLI (pure DSP, zero neural weights). */
#include "enhance.h"
#include "features.h"
#include "independent.h"
#include "midi.h"
#include "nn.h"
#include "resample.h"
#include "retune.h"
#include "tempo.h"
#include <limits.h>
#include <math.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#define DR_MP3_IMPLEMENTATION
#define DR_MP3_FLOAT_OUTPUT
#include "vendor/dr_mp3.h"

struct decoded_audio {
    float *mono;
    size_t frames;
    unsigned sample_rate;
    unsigned channels;
};

static float sanitize_f32(float v) {
    return isfinite(v) ? v : 0.0f;
}

static int decode_mp3_mono(const char *path, struct decoded_audio *out) {
    memset(out, 0, sizeof(*out));
    drmp3 mp3;
    if (!drmp3_init_file(&mp3, path, NULL)) {
        fprintf(stderr, "Cannot decode MP3: %s\n", path);
        return 0;
    }
    if (mp3.channels < 1 || mp3.channels > 2 || !mp3.sampleRate) {
        fputs("Invalid MP3 channel count or sample rate.\n", stderr);
        drmp3_uninit(&mp3);
        return 0;
    }
    size_t cap = 65536;
    size_t total = 0;
    float *mono = (float *)malloc(cap * sizeof(*mono));
    if (!mono) {
        perror("audio buffer");
        drmp3_uninit(&mp3);
        return 0;
    }
    float pcm[2048 * 2];
    for (;;) {
        unsigned count = (unsigned)drmp3_read_pcm_frames_f32(&mp3, 2048, pcm);
        if (!count) break;
        if ((size_t)count > SIZE_MAX - total) {
            fputs("MP3 too large.\n", stderr);
            free(mono);
            drmp3_uninit(&mp3);
            return 0;
        }
        size_t need = total + count;
        if (need > cap) {
            size_t next_cap = cap;
            while (next_cap < need) {
                if (next_cap > SIZE_MAX / 2) { next_cap = need; break; }
                next_cap *= 2;
            }
            if (next_cap > SIZE_MAX / sizeof(*mono)) {
                fputs("MP3 buffer overflow.\n", stderr);
                free(mono);
                drmp3_uninit(&mp3);
                return 0;
            }
            float *grown = (float *)realloc(mono, next_cap * sizeof(*mono));
            if (!grown) {
                perror("audio buffer");
                free(mono);
                drmp3_uninit(&mp3);
                return 0;
            }
            mono = grown;
            cap = next_cap;
        }
        if (mp3.channels == 1) {
            for (unsigned i = 0; i < count; ++i)
                mono[total + i] = sanitize_f32(pcm[i]);
        } else {
            for (unsigned i = 0; i < count; ++i)
                mono[total + i] = sanitize_f32((pcm[2 * i] + pcm[2 * i + 1]) * 0.5f);
        }
        total += count;
    }
    out->sample_rate = mp3.sampleRate;
    out->channels = mp3.channels;
    drmp3_uninit(&mp3);
    if (!total) {
        fputs("MP3 contains no decodable frames.\n", stderr);
        free(mono);
        return 0;
    }
    out->mono = mono;
    out->frames = total;
    return 1;
}

static uint16_t rd_u16le(const uint8_t *p) {
    return (uint16_t)((uint16_t)p[0] | ((uint16_t)p[1] << 8));
}

static uint32_t rd_u32le(const uint8_t *p) {
    return (uint32_t)p[0] | ((uint32_t)p[1] << 8) |
           ((uint32_t)p[2] << 16) | ((uint32_t)p[3] << 24);
}

static uint64_t rd_u64le(const uint8_t *p) {
    return (uint64_t)rd_u32le(p) | ((uint64_t)rd_u32le(p + 4) << 32);
}

static void print_json_str(const char *s) {
    putchar('"');
    if (s) {
        for (const unsigned char *p = (const unsigned char *)s; *p; ++p) {
            unsigned char c = *p;
            if (c == '"' || c == '\\') { putchar('\\'); putchar(c); }
            else if (c == '\b') fputs("\\b", stdout);
            else if (c == '\f') fputs("\\f", stdout);
            else if (c == '\n') fputs("\\n", stdout);
            else if (c == '\r') fputs("\\r", stdout);
            else if (c == '\t') fputs("\\t", stdout);
            else if (c < 0x20) printf("\\u%04x", (unsigned)c);
            else putchar(c);
        }
    }
    putchar('"');
}

static int is_wav_file(const char *path) {
    FILE *fp = fopen(path, "rb");
    if (!fp) return 0;
    uint8_t hdr[12];
    size_t got = fread(hdr, 1, sizeof(hdr), fp);
    fclose(fp);
    return (got == sizeof(hdr) &&
            memcmp(hdr, "RIFF", 4) == 0 &&
            memcmp(hdr + 8, "WAVE", 4) == 0);
}

static int decode_wav_mono(const char *path, struct decoded_audio *out) {
    memset(out, 0, sizeof(*out));
    FILE *fp = fopen(path, "rb");
    if (!fp) {
        fprintf(stderr, "Cannot open WAV: %s\n", path);
        return 0;
    }
    uint8_t hdr[12];
    if (fread(hdr, 1, 12, fp) != 12 ||
        memcmp(hdr, "RIFF", 4) != 0 || memcmp(hdr + 8, "WAVE", 4) != 0) {
        fprintf(stderr, "Invalid WAV header: %s\n", path);
        fclose(fp);
        return 0;
    }

    int have_fmt = 0;
    uint16_t fmt_tag = 0, channels = 0, bits = 0, block_align = 0;
    uint32_t sample_rate = 0;
    uint32_t data_bytes = 0;
    int have_data = 0;

    uint8_t chdr[8];
    while (fread(chdr, 1, 8, fp) == 8) {
        uint32_t csz = rd_u32le(chdr + 4);
        if (memcmp(chdr, "fmt ", 4) == 0) {
            if (csz < 16 || csz > 4096) {
                fputs("Unsupported WAV fmt chunk size.\n", stderr);
                fclose(fp);
                return 0;
            }
            uint8_t fbuf[4096];
            if (fread(fbuf, 1, csz, fp) != csz) {
                fputs("Truncated WAV fmt chunk.\n", stderr);
                fclose(fp);
                return 0;
            }
            fmt_tag = rd_u16le(fbuf + 0);
            channels = rd_u16le(fbuf + 2);
            sample_rate = rd_u32le(fbuf + 4);
            block_align = rd_u16le(fbuf + 12);
            bits = rd_u16le(fbuf + 14);
            if (fmt_tag == 0xFFFE && csz >= 40) {
                fmt_tag = rd_u16le(fbuf + 24); /* WAVE_FORMAT_EXTENSIBLE SubFormat tag */
            }
            have_fmt = 1;
            if (csz & 1u) fseek(fp, 1, SEEK_CUR);
        } else if (memcmp(chdr, "data", 4) == 0) {
            data_bytes = csz;
            have_data = 1;
            break;
        } else {
            uint64_t skip = (uint64_t)csz + (uint64_t)(csz & 1u);
            if (skip > (uint64_t)LONG_MAX || fseek(fp, (long)skip, SEEK_CUR) != 0) break;
        }
    }

    if (!have_fmt || !have_data || channels < 1 || channels > 16 || !sample_rate) {
        fprintf(stderr, "Unsupported or incomplete WAV: %s\n", path);
        fclose(fp);
        return 0;
    }
    int is_pcm = (fmt_tag == 1 && (bits == 8 || bits == 16 || bits == 24 || bits == 32));
    int is_flt = (fmt_tag == 3 && (bits == 32 || bits == 64));
    if (!is_pcm && !is_flt) {
        fprintf(stderr, "Unsupported WAV format tag=%u bits=%u: %s\n",
                (unsigned)fmt_tag, (unsigned)bits, path);
        fclose(fp);
        return 0;
    }
    unsigned bps = bits / 8u;
    unsigned frame_bytes = (block_align >= bps * channels) ? (unsigned)block_align : (bps * channels);
    if (!frame_bytes) {
        fclose(fp);
        return 0;
    }
    long data_pos = ftell(fp);
    if (data_pos >= 0 && fseek(fp, 0, SEEK_END) == 0) {
        long end_pos = ftell(fp);
        fseek(fp, data_pos, SEEK_SET);
        if (end_pos >= data_pos) {
            uint64_t rem = (uint64_t)(end_pos - data_pos);
            if ((uint64_t)data_bytes > rem) data_bytes = (uint32_t)rem;
        }
    }
    size_t n_frames = (size_t)(data_bytes / frame_bytes);
    if (!n_frames || n_frames > SIZE_MAX / sizeof(float)) {
        fputs("WAV contains no readable audio frames.\n", stderr);
        fclose(fp);
        return 0;
    }

    float *mono = (float *)malloc(n_frames * sizeof(float));
    enum { WAV_CHUNK = 2048 };
    uint8_t *raw = (uint8_t *)malloc((size_t)WAV_CHUNK * (size_t)frame_bytes);
    if (!mono || !raw) {
        perror("wav buffer");
        free(mono);
        free(raw);
        fclose(fp);
        return 0;
    }

    size_t total = 0;
    const float inv_ch = 1.0f / (float)channels;
    while (total < n_frames) {
        size_t want = n_frames - total;
        if (want > WAV_CHUNK) want = WAV_CHUNK;
        size_t got = fread(raw, frame_bytes, want, fp);
        if (!got) break;
        for (size_t i = 0; i < got; ++i) {
            const uint8_t *fr = raw + i * frame_bytes;
            float sum = 0.0f;
            for (unsigned c = 0; c < channels; ++c) {
                const uint8_t *s = fr + (size_t)c * bps;
                float v = 0.0f;
                if (fmt_tag == 1) {
                    if (bits == 8) {
                        v = ((float)s[0] - 128.0f) * (1.0f / 128.0f);
                    } else if (bits == 16) {
                        int16_t iv = (int16_t)rd_u16le(s);
                        v = (float)iv * (1.0f / 32768.0f);
                    } else if (bits == 24) {
                        int32_t iv = (int32_t)((uint32_t)s[0] | ((uint32_t)s[1] << 8) | ((uint32_t)s[2] << 16));
                        if (iv & 0x800000) iv |= (int32_t)0xFF000000u;
                        v = (float)iv * (1.0f / 8388608.0f);
                    } else {
                        int32_t iv = (int32_t)rd_u32le(s);
                        v = (float)((double)iv * (1.0 / 2147483648.0));
                    }
                } else if (bits == 32) {
                    uint32_t u = rd_u32le(s);
                    memcpy(&v, &u, 4);
                } else {
                    uint64_t u = rd_u64le(s);
                    double dv = 0.0;
                    memcpy(&dv, &u, 8);
                    v = (float)dv;
                }
                sum += sanitize_f32(v);
            }
            mono[total + i] = sanitize_f32(sum * inv_ch);
        }
        total += got;
    }
    free(raw);
    fclose(fp);
    if (!total) {
        fputs("WAV contains no readable frames.\n", stderr);
        free(mono);
        return 0;
    }
    out->mono = mono;
    out->frames = total;
    out->sample_rate = sample_rate;
    out->channels = channels;
    return 1;
}

static int decode_audio_mono(const char *path, struct decoded_audio *out) {
    if (is_wav_file(path)) return decode_wav_mono(path, out);
    return decode_mp3_mono(path, out);
}

static double now_s(void) {
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return (double)ts.tv_sec + (double)ts.tv_nsec * 1e-9;
}

static int run_independent_cli(const char *input_audio, const char *output_mid, int emit_cc74) {
    struct decoded_audio audio;
    if (!decode_audio_mono(input_audio, &audio)) return 1;

    nn_init(0);
    int status = 1;
    float *audio_16k = NULL, *retuned = NULL;
    size_t n_16k = 0, n_retuned = 0;
    struct independent_track *itracks = NULL;
    size_t n_itracks = 0;
    struct midi_track *base_tracks = NULL;
    struct enhance_track *enh_tracks = NULL;
    size_t n_enh_tracks = 0;
    struct midi_track *out_midi = NULL;

    double t0 = now_s();
    if (!resample_mono(audio.mono, audio.frames,
                       (double)audio.sample_rate, (double)MODEL_RATE,
                       &audio_16k, &n_16k)) {
        fputs("Failed to resample audio to 16 kHz.\n", stderr);
        goto done;
    }
    struct retune_info rt;
    retune_estimate(audio_16k, n_16k, &rt);
    if (!retune_apply(audio_16k, n_16k, &rt, &retuned, &n_retuned)) {
        fputs("Failed to apply tuning resampling.\n", stderr);
        goto done;
    }

    struct independent_stats istats = {0};
    if (!independent_transcribe(audio.mono, audio.frames, audio.sample_rate,
                                retuned, n_retuned, rt.ratio,
                                &itracks, &n_itracks, &istats)) {
        fputs("Independent DSP transcription failed.\n", stderr);
        goto done;
    }
    free(retuned); retuned = NULL;

    base_tracks = (struct midi_track *)calloc(n_itracks ? n_itracks : 1, sizeof(*base_tracks));
    if (!base_tracks) goto done;
    const struct midi_note *drums_ptr = NULL;
    size_t n_drums = 0;
    for (size_t i = 0; i < n_itracks; ++i) {
        base_tracks[i] = (struct midi_track){
            itracks[i].name, itracks[i].program, itracks[i].is_drum,
            itracks[i].notes, itracks[i].count, NULL, 0
        };
        if (itracks[i].is_drum && !drums_ptr) {
            drums_ptr = itracks[i].notes;
            n_drums = itracks[i].count;
        }
    }

    struct tempo_info tinfo;
    if (!tempo_estimate(audio_16k, n_16k, drums_ptr, n_drums, &tinfo)) {
        fputs("Tempo estimation failed.\n", stderr);
        goto done;
    }

    struct enhance_opts eopts;
    enhance_opts_default(&eopts);
    eopts.prune_ghosts = 0;
    eopts.refine_gm = 0;
    eopts.audio_dynamics = 1;
    eopts.emit_cc74 = emit_cc74;
    struct enhance_stats estats = {0};
    if (!enhance_tracks(base_tracks, n_itracks,
                        audio.mono, audio.frames, audio.sample_rate,
                        audio_16k, n_16k, &eopts,
                        &enh_tracks, &n_enh_tracks, &estats)) {
        fputs("MIDI dynamics calibration failed.\n", stderr);
        goto done;
    }

    out_midi = (struct midi_track *)calloc(n_enh_tracks ? n_enh_tracks : 1, sizeof(*out_midi));
    if (!out_midi) goto done;
    for (size_t i = 0; i < n_enh_tracks; ++i) {
        out_midi[i] = (struct midi_track){
            enh_tracks[i].name, enh_tracks[i].program, enh_tracks[i].is_drum,
            enh_tracks[i].notes, enh_tracks[i].count, enh_tracks[i].ccs, enh_tracks[i].n_ccs
        };
    }

    if (!midi_write_file_bpm(output_mid, out_midi, n_enh_tracks, tinfo.bpm)) {
        fprintf(stderr, "Failed writing MIDI file: %s\n", output_mid);
        goto done;
    }

    double elapsed = now_s() - t0;
    printf("{\"mode\":\"independent\",\"source_rate\":%u,\"seconds\":%.3f,\"tuning_cents\":%.2f,\"tuning_shift\":%.2f,"
           "\"bpm\":%.3f,\"tempo_clarity\":%.3f,\"tempo_steady\":%d,"
           "\"notes\":%zu,\"drums\":%zu,\"kicks\":%zu,\"snares\":%zu,\"hats\":%zu,\"crashes\":%zu,"
           "\"split_bm\":%d,\"split_mh\":%d,\"harmonic_ratio\":%.3f,"
           "\"cc_events\":%zu,\"tracks\":[",
           audio.sample_rate, (double)audio.frames / (double)audio.sample_rate,
           rt.delta_cents, rt.shift_cents, tinfo.bpm, tinfo.clarity, tinfo.is_steady,
           estats.pitched_out, estats.drums_out,
           istats.kick_hits, istats.snare_hits, istats.hat_hits, istats.crash_hits,
           istats.split_bass_mid, istats.split_mid_high, istats.harmonic_ratio,
           estats.cc_events_total);
    for (size_t i = 0; i < n_enh_tracks; ++i) {
        printf("%s{\"name\":", i ? "," : "");
        print_json_str(enh_tracks[i].name);
        printf(",\"program\":%d,\"is_drum\":%s,\"notes\":%zu,\"ccs\":%zu}",
               enh_tracks[i].program,
               enh_tracks[i].is_drum ? "true" : "false",
               enh_tracks[i].count, enh_tracks[i].n_ccs);
    }
    printf("],\"elapsed_s\":%.3f}\n", elapsed);
    status = 0;

done:
    free(out_midi);
    enhance_tracks_free(enh_tracks, n_enh_tracks);
    free(base_tracks);
    independent_tracks_free(itracks, n_itracks);
    free(retuned);
    free(audio_16k);
    free(audio.mono);
    nn_shutdown();
    return status;
}

static int run_enhance_midi_cli(const char *input_audio, const char *in_mid, const char *out_mid,
                                int emit_cc74, int use_hybrid) {
    struct decoded_audio audio;
    if (!decode_audio_mono(input_audio, &audio)) return 1;
    struct midi_loaded_track *loaded = NULL;
    size_t n_loaded = 0;
    if (!midi_read_file(in_mid, &loaded, &n_loaded)) {
        fprintf(stderr, "Cannot read MIDI file: %s\n", in_mid);
        free(audio.mono);
        return 1;
    }

    nn_init(0);
    int status = 1;
    double t0 = now_s();
    float *a16 = NULL, *retuned = NULL; size_t n16 = 0, n_rt = 0;
    struct midi_track *in_tr = NULL, *hyb_mt = NULL, *out_mt = NULL;
    struct independent_track *hyb = NULL; size_t n_hyb = 0;
    struct enhance_track *enh = NULL; size_t n_enh = 0;

    if (!resample_mono(audio.mono, audio.frames, (double)audio.sample_rate, (double)MODEL_RATE, &a16, &n16)) goto done;
    in_tr = (struct midi_track *)calloc(n_loaded ? n_loaded : 1, sizeof(*in_tr));
    if (!in_tr) goto done;
    const struct midi_note *drums_ptr = NULL;
    size_t n_drums = 0;
    for (size_t i = 0; i < n_loaded; ++i) {
        in_tr[i] = (struct midi_track){ loaded[i].name, loaded[i].program, loaded[i].is_drum,
                                        loaded[i].notes, loaded[i].count, NULL, 0 };
        if (loaded[i].is_drum && !drums_ptr) { drums_ptr = loaded[i].notes; n_drums = loaded[i].count; }
    }

    const struct midi_track *enh_src = in_tr;
    size_t n_enh_src = n_loaded;
    struct hybrid_stats hstats = {0};
    if (use_hybrid) {
        struct retune_info rt;
        retune_estimate(a16, n16, &rt);
        if (!retune_apply(a16, n16, &rt, &retuned, &n_rt)) goto done;
        if (!independent_hybrid_fuse(in_tr, n_loaded, retuned, n_rt, rt.ratio, &hyb, &n_hyb, &hstats)) goto done;
        free(retuned); retuned = NULL;
        hyb_mt = (struct midi_track *)calloc(n_hyb ? n_hyb : 1, sizeof(*hyb_mt));
        if (!hyb_mt) goto done;
        for (size_t i = 0; i < n_hyb; ++i) {
            hyb_mt[i] = (struct midi_track){ hyb[i].name, hyb[i].program, hyb[i].is_drum,
                                             hyb[i].notes, hyb[i].count, NULL, 0 };
        }
        enh_src = hyb_mt;
        n_enh_src = n_hyb;
    }

    struct tempo_info tinfo;
    if (!tempo_estimate(a16, n16, drums_ptr, n_drums, &tinfo)) goto done;
    struct enhance_opts eopts;
    enhance_opts_default(&eopts);
    eopts.emit_cc74 = emit_cc74;
    struct enhance_stats estats = {0};
    if (!enhance_tracks(enh_src, n_enh_src, audio.mono, audio.frames, audio.sample_rate,
                        a16, n16, &eopts, &enh, &n_enh, &estats)) goto done;

    out_mt = (struct midi_track *)calloc(n_enh ? n_enh : 1, sizeof(*out_mt));
    if (!out_mt) goto done;
    for (size_t i = 0; i < n_enh; ++i) {
        out_mt[i] = (struct midi_track){ enh[i].name, enh[i].program, enh[i].is_drum,
                                         enh[i].notes, enh[i].count, enh[i].ccs, enh[i].n_ccs };
    }
    if (!midi_write_file_bpm(out_mid, out_mt, n_enh, tinfo.bpm)) {
        fprintf(stderr, "Failed writing MIDI file: %s\n", out_mid);
        goto done;
    }
    double elapsed = now_s() - t0;
    printf("{\"mode\":\"%s\",\"bpm\":%.3f,\"initial_bpm\":%.3f,\"row0_ms\":%.1f,"
           "\"tempo_clarity\":%.3f,\"worst_drift_ms\":%.2f,\"tempo_steady\":%d,"
           "\"notes\":%zu,\"notes_in\":%zu,\"wrong_dropped\":%zu,"
           "\"bass_rescued\":%zu,\"mid_high_rescued\":%zu,\"rescue_tracks_added\":%d,"
           "\"dups_dropped\":%zu,\"ghosts_dropped\":%zu,"
           "\"tracks_dropped\":%zu,\"drums\":%zu,\"drums_in\":%zu,\"drum_bleed_dropped\":%zu,"
           "\"programs_refined\":%d,\"cc_events\":%zu,\"tracks\":[",
           use_hybrid ? "hybrid-midi" : "enhance-midi",
           tinfo.bpm, tinfo.initial_bpm, tinfo.row0_s * 1000.0, tinfo.clarity, tinfo.worst_drift_ms, tinfo.is_steady,
           estats.pitched_out, estats.pitched_in, hstats.dettato_wrong_dropped,
           hstats.bass_rescued, hstats.mid_high_rescued, hstats.rescue_tracks_added,
           estats.dups_dropped, estats.ghosts_dropped,
           estats.tracks_dropped, estats.drums_out, estats.drums_in, estats.drum_bleed_dropped,
           estats.programs_refined, estats.cc_events_total);
    for (size_t i = 0; i < n_enh; ++i) {
        printf("%s{\"name\":", i ? "," : "");
        print_json_str(enh[i].name);
        printf(",\"program\":%d,\"is_drum\":%s,\"notes\":%zu,\"ccs\":%zu}",
               enh[i].program, enh[i].is_drum ? "true" : "false",
               enh[i].count, enh[i].n_ccs);
    }
    printf("],\"elapsed_s\":%.3f}\n", elapsed);
    status = 0;

done:
    free(out_mt);
    enhance_tracks_free(enh, n_enh);
    free(hyb_mt);
    independent_tracks_free(hyb, n_hyb);
    free(retuned);
    free(in_tr);
    free(a16);
    midi_loaded_tracks_free(loaded, n_loaded);
    free(audio.mono);
    nn_shutdown();
    return status;
}

static int run_tempo_test(const char *input_audio) {
    struct decoded_audio audio;
    if (!decode_audio_mono(input_audio, &audio)) return 1;
    float *a16 = NULL; size_t n16 = 0;
    int ok = resample_mono(audio.mono, audio.frames, (double)audio.sample_rate, (double)MODEL_RATE, &a16, &n16);
    free(audio.mono);
    if (!ok) return 1;
    struct tempo_info ti;
    tempo_estimate(a16, n16, NULL, 0, &ti);
    free(a16);
    printf("{\"bpm\":%.3f,\"initial_bpm\":%.3f,\"row0_ms\":%.1f,\"clarity\":%.3f,\"worst_drift_ms\":%.2f,\"steady\":%d}\n",
           ti.bpm, ti.initial_bpm, ti.row0_s * 1000.0, ti.clarity, ti.worst_drift_ms, ti.is_steady);
    return 0;
}

static void usage(FILE *out) {
    fputs("Usage: mp3tomidi-independent INPUT.{mp3|wav} -o OUTPUT.mid [--mode independent] [--no-cc74]\n"
          "       mp3tomidi-independent --enhance-midi INPUT.{mp3|wav} BASE.mid -o OUTPUT.mid [--no-cc74]\n"
          "       mp3tomidi-independent --hybrid-midi INPUT.{mp3|wav} BASE.mid -o OUTPUT.mid [--no-cc74]\n"
          "       mp3tomidi-independent --tempo-test INPUT.{mp3|wav}\n"
          "       mp3tomidi-independent --retune-test INPUT.{mp3|wav}\n"
          "       mp3tomidi-independent --inspect INPUT.{mp3|wav}\n"
          "  -o PATH              Write transcribed Standard MIDI File to PATH.\n"
          "  --mode independent   Zero-weight pure-DSP transcriber (default).\n"
          "  --no-cc74            Disable CC74 Brightness controller emission.\n"
          "  --inspect            Report source rate, channels, decoded frames and mono RMS.\n", out);
}

int main(int argc, char **argv) {
    if (argc == 2 && strcmp(argv[1], "--help") == 0) { usage(stdout); return 0; }
    if (argc == 3 && strcmp(argv[1], "--tempo-test") == 0) {
        return run_tempo_test(argv[2]);
    }
    if (argc >= 6 && (strcmp(argv[1], "--enhance-midi") == 0 || strcmp(argv[1], "--hybrid-midi") == 0)) {
        int use_hybrid = (strcmp(argv[1], "--hybrid-midi") == 0);
        const char *in_audio = argv[2];
        const char *in_mid = argv[3];
        const char *out_mid = NULL;
        int emit_cc74 = 1;
        for (int i = 4; i < argc; ++i) {
            if (strcmp(argv[i], "-o") == 0 && i + 1 < argc) out_mid = argv[++i];
            else if (strcmp(argv[i], "--no-cc74") == 0) emit_cc74 = 0;
            else { usage(stderr); return 2; }
        }
        if (!out_mid) { usage(stderr); return 2; }
        return run_enhance_midi_cli(in_audio, in_mid, out_mid, emit_cc74, use_hybrid);
    }
    if (argc == 3 && strcmp(argv[1], "--retune-test") == 0) {
        struct decoded_audio audio;
        if (!decode_audio_mono(argv[2], &audio)) return 1;
        float *a16 = NULL; size_t n16 = 0;
        int ok = resample_mono(audio.mono, audio.frames, (double)audio.sample_rate, (double)MODEL_RATE, &a16, &n16);
        free(audio.mono);
        if (!ok) return 1;
        struct retune_info rt;
        retune_estimate(a16, n16, &rt);
        free(a16);
        printf("{\"delta\":%.6f,\"strength\":%.6f,\"shift\":%.6f,\"ratio\":%.9f}\n",
               rt.delta_cents, rt.strength, rt.shift_cents, rt.ratio);
        return 0;
    }
    if (argc == 3 && strcmp(argv[1], "--inspect") == 0) {
        struct decoded_audio audio;
        if (!decode_audio_mono(argv[2], &audio)) return 1;
        double squares = 0.0;
        for (size_t i = 0; i < audio.frames; ++i)
            squares += (double)audio.mono[i] * (double)audio.mono[i];
        printf("{\"rate\":%u,\"channels\":%u,\"frames\":%llu,\"mono_rms\":%.9g}\n",
               audio.sample_rate, audio.channels,
               (unsigned long long)audio.frames, sqrt(squares / (double)audio.frames));
        free(audio.mono);
        return (fflush(stdout) || ferror(stdout)) ? 1 : 0;
    }

    const char *input_mp3 = NULL;
    const char *output_mid = NULL;
    int emit_cc74 = 1;
    for (int i = 1; i < argc; ++i) {
        if (strcmp(argv[i], "-o") == 0 && i + 1 < argc) {
            output_mid = argv[++i];
        } else if (strcmp(argv[i], "--mode") == 0 && i + 1 < argc) {
            const char *m = argv[++i];
            if (strcmp(m, "independent") != 0) {
                fprintf(stderr, "Unknown --mode: %s (expected independent)\n", m);
                return 2;
            }
        } else if (strcmp(argv[i], "--no-cc74") == 0) {
            emit_cc74 = 0;
        } else if (argv[i][0] != '-' && !input_mp3) {
            input_mp3 = argv[i];
        } else {
            usage(stderr);
            return 2;
        }
    }
    if (input_mp3 && output_mid) {
        return run_independent_cli(input_mp3, output_mid, emit_cc74);
    }
    usage(stderr);
    return 2;
}
