#include "drums.h"
#include "enhance.h"
#include "evidence.h"
#include "features.h"
#include "grouper.h"
#include "lanenet.h"
#include "midi.h"
#include "nn.h"
#include "resample.h"
#include "retune.h"
#include "tempo.h"
#include "transcribe.h"
#include "weights.h"
#include <math.h>
#include <stdint.h>
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
        if (total + count > cap) {
            size_t next_cap = cap;
            while (next_cap < total + count) next_cap *= 2;
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
            memcpy(mono + total, pcm, count * sizeof(float));
        } else {
            for (unsigned i = 0; i < count; ++i)
                mono[total + i] = (pcm[2 * i] + pcm[2 * i + 1]) * 0.5f;
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

static double now_s(void) {
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return (double)ts.tv_sec + (double)ts.tv_nsec * 1e-9;
}

static int write_f32_file(const char *path, const float *data, size_t count) {
    FILE *fp = fopen(path, "wb");
    if (!fp) return 0;
    int ok = (fwrite(data, sizeof(float), count, fp) == count);
    if (fclose(fp) != 0) ok = 0;
    return ok;
}

static int run_lanenet_test(const char *weights_path, const char *audio_f32_path, const char *out_prefix) {
    nn_init(0);
    FILE *fp = fopen(audio_f32_path, "rb");
    if (!fp) { fprintf(stderr, "Cannot open audio f32: %s\n", audio_f32_path); return 1; }
    fseek(fp, 0, SEEK_END);
    long sz = ftell(fp);
    rewind(fp);
    if (sz <= 0 || (sz % 4) != 0) { fclose(fp); fputs("Invalid f32 audio size.\n", stderr); return 1; }
    int samples = (int)(sz / 4);
    float *audio = (float *)malloc((size_t)sz);
    if (!audio || fread(audio, 1, (size_t)sz, fp) != (size_t)sz) {
        free(audio); fclose(fp); fputs("Failed reading audio f32.\n", stderr); return 1;
    }
    fclose(fp);

    double t_load0 = now_s();
    struct vtwt_file wf;
    if (!vtwt_load(weights_path, &wf)) {
        free(audio); fprintf(stderr, "Cannot load weights: %s\n", weights_path); return 1;
    }
    struct lanenet *net = lanenet_load(&wf);
    vtwt_free(&wf);
    if (!net) { free(audio); fputs("Failed to initialize LaneNet.\n", stderr); return 1; }
    double t_load = now_s() - t_load0;

    int T10 = samples / HCQT_HOP;
    int T = (T10 + 1) / 2;
    float *logits = (float *)malloc((size_t)T * LANE_KEYS * LANE_HEADS * sizeof(float));
    float *stem = (float *)malloc((size_t)T * LANE_KEYS * LANE_C * sizeof(float));
    float *hidden = (float *)malloc((size_t)T * LANE_KEYS * LANE_C * sizeof(float));
    int status = 1;
    if (!logits || !stem || !hidden) { fputs("OOM allocating outputs.\n", stderr); goto cleanup; }

    double t_run0 = now_s();
    int out_T = lanenet_forward(net, audio, samples, logits, stem, hidden);
    double t_run = now_s() - t_run0;
    if (out_T != T) { fputs("lanenet_forward failed.\n", stderr); goto cleanup; }

    char p_logits[512], p_stem[512], p_hidden[512];
    snprintf(p_logits, sizeof(p_logits), "%s.logits.f32", out_prefix);
    snprintf(p_stem, sizeof(p_stem), "%s.stem.f32", out_prefix);
    snprintf(p_hidden, sizeof(p_hidden), "%s.hidden.f32", out_prefix);
    if (!write_f32_file(p_logits, logits, (size_t)T * LANE_KEYS * LANE_HEADS) ||
        !write_f32_file(p_stem, stem, (size_t)T * LANE_KEYS * LANE_C) ||
        !write_f32_file(p_hidden, hidden, (size_t)T * LANE_KEYS * LANE_C)) {
        fputs("Failed writing output tensors.\n", stderr);
        goto cleanup;
    }
    printf("{\"T\":%d,\"threads\":%d,\"avx2_fma\":%d,\"load_s\":%.4f,\"forward_s\":%.4f}\n",
           T, nn_num_threads(), nn_has_avx2_fma(), t_load, t_run);
    status = 0;

cleanup:
    free(logits); free(stem); free(hidden);
    lanenet_free(net);
    free(audio);
    nn_shutdown();
    return status;
}

static int load_model_weights(const char *weights_dir, const char *filename, struct vtwt_file *out) {
    char path[1024];
    if (weights_dir && weights_dir[0]) {
        snprintf(path, sizeof(path), "%s/%s", weights_dir, filename);
        if (vtwt_load(path, out)) return 1;
    }
    snprintf(path, sizeof(path), "/zip/weights/%s", filename);
    return vtwt_load(path, out);
}

static int conf_to_vel(float conf) {
    double x = ((double)conf - 0.25) / 0.75;
    int v = (int)floor(1.0 + 126.0 * x + 0.5);
    if (v < 1) v = 1;
    if (v > 127) v = 127;
    return v;
}

static int run_transcribe_cli(const char *input_mp3, const char *output_mid,
                              const char *weights_dir, int enhanced, int emit_cc74) {
    struct vtwt_file wf_tr = {0}, wf_ev = {0}, wf_gp = {0}, wf_dr = {0};
    if (!load_model_weights(weights_dir, "transcriber.vtwt", &wf_tr)) {
        fprintf(stderr, "Cannot load transcriber weights (pass --weights-dir DIR or use embedded build).\n");
        return 1;
    }
    int has_ev = load_model_weights(weights_dir, "evidence.vtwt", &wf_ev);
    int has_gp = has_ev && load_model_weights(weights_dir, "grouper.vtwt", &wf_gp);
    int has_dr = load_model_weights(weights_dir, "drums.vtwt", &wf_dr);

    struct decoded_audio audio;
    if (!decode_mp3_mono(input_mp3, &audio)) {
        vtwt_free(&wf_tr); vtwt_free(&wf_ev); vtwt_free(&wf_gp); vtwt_free(&wf_dr);
        return 1;
    }

    nn_init(0);
    int status = 1;
    float *audio_16k = NULL, *retuned = NULL;
    size_t n_16k = 0, n_retuned = 0;
    struct lanenet *net = NULL;
    struct evidence_model *evm = NULL;
    struct grouper_model *gpm = NULL;
    struct drums_model *dm = NULL;
    struct transcribe_run tr = {0};
    struct vt_note *raw_notes = NULL; size_t n_raw = 0;
    struct repaired_note *rep_notes = NULL; size_t n_rep = 0;
    struct repair_info rinfo = {0};
    struct grouped_track *gtracks = NULL; size_t n_gtracks = 0;
    struct midi_note *fallback_notes = NULL;
    struct midi_note *drum_notes = NULL; size_t n_drums = 0;
    struct drums_info dinfo = {0};
    struct midi_track *out_tracks = NULL;
    struct midi_track *enh_midi_tracks = NULL;
    struct enhance_track *enh_tracks = NULL; size_t n_enh_tracks = 0;
    char **track_names = NULL;
    size_t n_out_tracks = 0;

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
    if (!enhanced) { free(audio_16k); audio_16k = NULL; }

    net = lanenet_load(&wf_tr);
    vtwt_free(&wf_tr);
    if (!net) { fputs("Failed to load LaneNet model.\n", stderr); goto done; }

    if (!transcribe_windows(net, retuned, n_retuned, has_ev, has_gp, &tr)) {
        fputs("Windowed transcription failed.\n", stderr);
        goto done;
    }
    lanenet_free(net); net = NULL;

    if (!transcribe_decode(tr.maps, tr.T, &raw_notes, &n_raw)) {
        fputs("Note decoding failed.\n", stderr);
        goto done;
    }

    if (has_ev) {
        evm = evidence_load(&wf_ev);
        vtwt_free(&wf_ev);
        if (!evm || !evidence_repair(evm, tr.maps, tr.hidden_f16, tr.T,
                                     raw_notes, n_raw, &rep_notes, &n_rep, &rinfo)) {
            fputs("Evidence repair failed.\n", stderr);
            goto done;
        }
        evidence_free(evm); evm = NULL;
        free(tr.maps); tr.maps = NULL;
        free(tr.hidden_f16); tr.hidden_f16 = NULL;
        free(raw_notes); raw_notes = NULL;
    }

    if (has_gp) {
        gpm = grouper_load(&wf_gp);
        vtwt_free(&wf_gp);
        if (!gpm || !grouper_run(gpm, retuned, n_retuned, &tr,
                                 rep_notes, n_rep, rt.ratio, &gtracks, &n_gtracks)) {
            fputs("Instrument grouping failed.\n", stderr);
            goto done;
        }
        grouper_free(gpm); gpm = NULL;
        transcribe_run_free(&tr);
        free(rep_notes); rep_notes = NULL;
    }
    free(retuned); retuned = NULL;

    /* Drum stage (uses native source audio, only when source_rate >= 40 kHz) */
    int drums_ran = 0;
    if (has_dr && audio.sample_rate >= DRUMS_MIN_SOURCE_RATE) {
        dm = drums_load(&wf_dr);
        vtwt_free(&wf_dr);
        if (!dm || !drums_transcribe(dm, audio.mono, audio.frames, audio.sample_rate,
                                     &drum_notes, &n_drums, &dinfo)) {
            fputs("Drum transcription failed.\n", stderr);
            goto done;
        }
        drums_free(dm); dm = NULL;
        drums_ran = 1;
    } else {
        vtwt_free(&wf_dr);
    }

    /* Assemble base MIDI tracks */
    size_t max_tr = (has_gp ? n_gtracks : 1) + (n_drums > 0 ? 1 : 0);
    out_tracks = (struct midi_track *)calloc(max_tr ? max_tr : 1, sizeof(*out_tracks));
    track_names = (char **)calloc(max_tr ? max_tr : 1, sizeof(*track_names));
    if (!out_tracks || !track_names) { fputs("OOM assembling tracks.\n", stderr); goto done; }

    size_t total_pitched = 0;
    if (has_gp) {
        for (size_t i = 0; i < n_gtracks; ++i) {
            size_t len = strlen(gtracks[i].instrument);
            char *nm = (char *)malloc(len + 1);
            if (!nm) goto done;
            for (size_t k = 0; k <= len; ++k)
                nm[k] = (gtracks[i].instrument[k] == '_') ? ' ' : gtracks[i].instrument[k];
            track_names[n_out_tracks] = nm;
            out_tracks[n_out_tracks++] = (struct midi_track){
                nm, gtracks[i].program, 0, gtracks[i].notes, gtracks[i].count, NULL, 0
            };
            total_pitched += gtracks[i].count;
        }
    } else if (has_ev) {
        fallback_notes = n_rep ? (struct midi_note *)malloc(n_rep * sizeof(*fallback_notes)) : NULL;
        if (n_rep && !fallback_notes) goto done;
        for (size_t i = 0; i < n_rep; ++i) {
            fallback_notes[i].onset = rep_notes[i].onset * rt.ratio;
            fallback_notes[i].offset = rep_notes[i].offset * rt.ratio;
            fallback_notes[i].pitch = rep_notes[i].pitch;
            fallback_notes[i].velocity = conf_to_vel(rep_notes[i].score);
        }
        out_tracks[n_out_tracks++] = (struct midi_track){
            "Acoustic Grand Piano", 0, 0, fallback_notes, n_rep, NULL, 0
        };
        total_pitched = n_rep;
    } else {
        fallback_notes = n_raw ? (struct midi_note *)malloc(n_raw * sizeof(*fallback_notes)) : NULL;
        if (n_raw && !fallback_notes) goto done;
        for (size_t i = 0; i < n_raw; ++i) {
            fallback_notes[i].onset = raw_notes[i].onset * rt.ratio;
            fallback_notes[i].offset = raw_notes[i].offset * rt.ratio;
            fallback_notes[i].pitch = raw_notes[i].pitch;
            fallback_notes[i].velocity = conf_to_vel(raw_notes[i].conf);
        }
        out_tracks[n_out_tracks++] = (struct midi_track){
            "Acoustic Grand Piano", 0, 0, fallback_notes, n_raw, NULL, 0
        };
        total_pitched = n_raw;
    }

    if (n_drums > 0) {
        out_tracks[n_out_tracks++] = (struct midi_track){ "Drums", 0, 1, drum_notes, n_drums, NULL, 0 };
    }

    if (!enhanced) {
        if (!midi_write_file(output_mid, out_tracks, n_out_tracks)) {
            fprintf(stderr, "Failed writing MIDI file: %s\n", output_mid);
            goto done;
        }
        double elapsed = now_s() - t0;
        printf("{\"mode\":\"parity\",\"source_rate\":%u,\"seconds\":%.3f,\"tuning_cents\":%.2f,\"tuning_shift\":%.2f,"
               "\"notes\":%zu,\"drums\":%zu,\"drums_model\":\"%s\",\"tracks\":%zu,\"elapsed_s\":%.3f}\n",
               audio.sample_rate, (double)audio.frames / (double)audio.sample_rate,
               rt.delta_cents, rt.shift_cents, total_pitched, n_drums,
               drums_ran ? (dinfo.used_orchestral ? "orchestral" : "drum-kit") : "skipped",
               n_out_tracks, elapsed);
    } else {
        struct tempo_info tinfo;
        if (!tempo_estimate(audio_16k, n_16k, drum_notes, n_drums, &tinfo)) {
            fputs("Tempo estimation failed.\n", stderr);
            goto done;
        }
        struct enhance_opts eopts;
        enhance_opts_default(&eopts);
        eopts.emit_cc74 = emit_cc74;
        struct enhance_stats estats = {0};
        if (!enhance_tracks(out_tracks, n_out_tracks,
                            audio.mono, audio.frames, audio.sample_rate,
                            audio_16k, n_16k, &eopts,
                            &enh_tracks, &n_enh_tracks, &estats)) {
            fputs("MIDI enhancement failed.\n", stderr);
            goto done;
        }
        enh_midi_tracks = (struct midi_track *)calloc(n_enh_tracks ? n_enh_tracks : 1, sizeof(*enh_midi_tracks));
        if (!enh_midi_tracks) goto done;
        for (size_t i = 0; i < n_enh_tracks; ++i) {
            enh_midi_tracks[i] = (struct midi_track){
                enh_tracks[i].name, enh_tracks[i].program, enh_tracks[i].is_drum,
                enh_tracks[i].notes, enh_tracks[i].count, enh_tracks[i].ccs, enh_tracks[i].n_ccs
            };
        }
        if (!midi_write_file_bpm(output_mid, enh_midi_tracks, n_enh_tracks, tinfo.bpm)) {
            fprintf(stderr, "Failed writing enhanced MIDI file: %s\n", output_mid);
            goto done;
        }
        double elapsed = now_s() - t0;
        printf("{\"mode\":\"enhanced\",\"source_rate\":%u,\"seconds\":%.3f,\"tuning_cents\":%.2f,\"tuning_shift\":%.2f,"
               "\"bpm\":%.3f,\"tempo_clarity\":%.3f,\"tempo_steady\":%d,"
               "\"notes\":%zu,\"notes_in\":%zu,\"dups_dropped\":%zu,\"ghosts_dropped\":%zu,"
               "\"drums\":%zu,\"drums_in\":%zu,\"drum_bleed_dropped\":%zu,"
               "\"programs_refined\":%d,\"cc_events\":%zu,\"tracks\":%zu,\"elapsed_s\":%.3f}\n",
               audio.sample_rate, (double)audio.frames / (double)audio.sample_rate,
               rt.delta_cents, rt.shift_cents, tinfo.bpm, tinfo.clarity, tinfo.is_steady,
               estats.pitched_out, estats.pitched_in, estats.dups_dropped, estats.ghosts_dropped,
               estats.drums_out, estats.drums_in, estats.drum_bleed_dropped,
               estats.programs_refined, estats.cc_events_total, n_enh_tracks, elapsed);
    }
    status = 0;

done:
    free(enh_midi_tracks);
    enhance_tracks_free(enh_tracks, n_enh_tracks);
    if (track_names) {
        for (size_t i = 0; i < n_out_tracks; ++i) free(track_names[i]);
        free(track_names);
    }
    free(out_tracks);
    free(drum_notes);
    free(fallback_notes);
    grouped_tracks_free(gtracks, n_gtracks);
    free(rep_notes);
    free(raw_notes);
    transcribe_run_free(&tr);
    drums_free(dm); grouper_free(gpm); evidence_free(evm); lanenet_free(net);
    free(retuned); free(audio_16k); free(audio.mono);
    vtwt_free(&wf_tr); vtwt_free(&wf_ev); vtwt_free(&wf_gp); vtwt_free(&wf_dr);
    nn_shutdown();
    return status;
}

static int run_enhance_midi_cli(const char *input_mp3, const char *in_mid, const char *out_mid, int emit_cc74) {
    struct decoded_audio audio;
    if (!decode_mp3_mono(input_mp3, &audio)) return 1;
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
    float *a16 = NULL; size_t n16 = 0;
    struct midi_track *in_tr = NULL, *out_mt = NULL;
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

    struct tempo_info tinfo;
    if (!tempo_estimate(a16, n16, drums_ptr, n_drums, &tinfo)) goto done;
    struct enhance_opts eopts;
    enhance_opts_default(&eopts);
    eopts.emit_cc74 = emit_cc74;
    struct enhance_stats estats = {0};
    if (!enhance_tracks(in_tr, n_loaded, audio.mono, audio.frames, audio.sample_rate,
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
    printf("{\"mode\":\"enhance-midi\",\"bpm\":%.3f,\"initial_bpm\":%.3f,\"row0_ms\":%.1f,"
           "\"tempo_clarity\":%.3f,\"worst_drift_ms\":%.2f,\"tempo_steady\":%d,"
           "\"notes\":%zu,\"notes_in\":%zu,\"dups_dropped\":%zu,\"ghosts_dropped\":%zu,"
           "\"tracks_dropped\":%zu,\"drums\":%zu,\"drums_in\":%zu,\"drum_bleed_dropped\":%zu,"
           "\"programs_refined\":%d,\"cc_events\":%zu,\"tracks\":[",
           tinfo.bpm, tinfo.initial_bpm, tinfo.row0_s * 1000.0, tinfo.clarity, tinfo.worst_drift_ms, tinfo.is_steady,
           estats.pitched_out, estats.pitched_in, estats.dups_dropped, estats.ghosts_dropped,
           estats.tracks_dropped, estats.drums_out, estats.drums_in, estats.drum_bleed_dropped,
           estats.programs_refined, estats.cc_events_total);
    for (size_t i = 0; i < n_enh; ++i) {
        printf("%s{\"name\":\"%s\",\"program\":%d,\"is_drum\":%s,\"notes\":%zu,\"ccs\":%zu}",
               i ? "," : "", enh[i].name, enh[i].program, enh[i].is_drum ? "true" : "false",
               enh[i].count, enh[i].n_ccs);
    }
    printf("],\"elapsed_s\":%.3f}\n", elapsed);
    status = 0;

done:
    free(out_mt);
    enhance_tracks_free(enh, n_enh);
    free(in_tr);
    free(a16);
    midi_loaded_tracks_free(loaded, n_loaded);
    free(audio.mono);
    nn_shutdown();
    return status;
}

static int run_tempo_test(const char *input_mp3) {
    struct decoded_audio audio;
    if (!decode_mp3_mono(input_mp3, &audio)) return 1;
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

static int run_evidence_test(const char *weights_dir, const char *input_mp3) {
    struct vtwt_file wf_tr = {0}, wf_ev = {0};
    if (!load_model_weights(weights_dir, "transcriber.vtwt", &wf_tr) ||
        !load_model_weights(weights_dir, "evidence.vtwt", &wf_ev)) {
        vtwt_free(&wf_tr); vtwt_free(&wf_ev);
        fputs("Cannot load transcriber/evidence weights.\n", stderr);
        return 1;
    }
    struct decoded_audio audio;
    if (!decode_mp3_mono(input_mp3, &audio)) {
        vtwt_free(&wf_tr); vtwt_free(&wf_ev);
        return 1;
    }
    nn_init(0);
    int status = 1;
    float *a16 = NULL, *retuned = NULL;
    size_t n16 = 0, n_rt = 0;
    struct lanenet *net = NULL;
    struct evidence_model *evm = NULL;
    struct transcribe_run tr = {0};
    struct vt_note *raw = NULL; size_t n_raw = 0;
    struct repaired_note *rep = NULL; size_t n_rep = 0;
    struct repair_info rinfo = {0};

    if (!resample_mono(audio.mono, audio.frames, (double)audio.sample_rate, (double)MODEL_RATE, &a16, &n16)) goto done;
    struct retune_info rt;
    retune_estimate(a16, n16, &rt);
    if (!retune_apply(a16, n16, &rt, &retuned, &n_rt)) goto done;
    net = lanenet_load(&wf_tr); vtwt_free(&wf_tr);
    if (!net) goto done;
    if (!transcribe_windows(net, retuned, n_rt, 1, 0, &tr)) goto done;
    lanenet_free(net); net = NULL;
    if (!transcribe_decode(tr.maps, tr.T, &raw, &n_raw)) goto done;
    evm = evidence_load(&wf_ev); vtwt_free(&wf_ev);
    if (!evm) goto done;
    if (!evidence_repair(evm, tr.maps, tr.hidden_f16, tr.T, raw, n_raw, &rep, &n_rep, &rinfo)) goto done;
    if (rt.ratio != 1.0) {
        for (size_t i = 0; i < n_rep; ++i) {
            rep[i].onset *= rt.ratio;
            rep[i].offset *= rt.ratio;
        }
    }
    printf("{\"info\":{\"transcribed\":%zu,\"kept\":%zu,\"dropped\":%zu,\"inserted\":%zu},\"notes\":[",
           rinfo.transcribed, rinfo.kept, rinfo.dropped, rinfo.inserted);
    for (size_t i = 0; i < n_rep; ++i) {
        printf("%s[%.4f,%.4f,%d,%d,%.4f]", i ? "," : "",
               rep[i].onset, rep[i].offset, rep[i].pitch, rep[i].inserted, rep[i].score);
    }
    puts("]}");
    status = 0;

done:
    free(rep); free(raw);
    transcribe_run_free(&tr);
    evidence_free(evm); lanenet_free(net);
    free(retuned); free(a16); free(audio.mono);
    vtwt_free(&wf_tr); vtwt_free(&wf_ev);
    nn_shutdown();
    return status;
}

static int run_grouper_test(const char *weights_dir, const char *input_mp3) {
    struct vtwt_file wf_tr = {0}, wf_ev = {0}, wf_gp = {0};
    if (!load_model_weights(weights_dir, "transcriber.vtwt", &wf_tr) ||
        !load_model_weights(weights_dir, "evidence.vtwt", &wf_ev) ||
        !load_model_weights(weights_dir, "grouper.vtwt", &wf_gp)) {
        vtwt_free(&wf_tr); vtwt_free(&wf_ev); vtwt_free(&wf_gp);
        fputs("Cannot load transcriber/evidence/grouper weights.\n", stderr);
        return 1;
    }
    struct decoded_audio audio;
    if (!decode_mp3_mono(input_mp3, &audio)) {
        vtwt_free(&wf_tr); vtwt_free(&wf_ev); vtwt_free(&wf_gp);
        return 1;
    }
    nn_init(0);
    int status = 1;
    float *a16 = NULL, *retuned = NULL;
    size_t n16 = 0, n_rt = 0;
    struct lanenet *net = NULL;
    struct evidence_model *evm = NULL;
    struct grouper_model *gpm = NULL;
    struct transcribe_run tr = {0};
    struct vt_note *raw = NULL; size_t n_raw = 0;
    struct repaired_note *rep = NULL; size_t n_rep = 0;
    struct repair_info rinfo = {0};
    struct grouped_track *tracks = NULL; size_t n_tracks = 0;

    if (!resample_mono(audio.mono, audio.frames, (double)audio.sample_rate, (double)MODEL_RATE, &a16, &n16)) goto done;
    struct retune_info rt;
    retune_estimate(a16, n16, &rt);
    if (!retune_apply(a16, n16, &rt, &retuned, &n_rt)) goto done;

    net = lanenet_load(&wf_tr); vtwt_free(&wf_tr);
    if (!net || !transcribe_windows(net, retuned, n_rt, 1, 1, &tr)) goto done;
    lanenet_free(net); net = NULL;
    if (!transcribe_decode(tr.maps, tr.T, &raw, &n_raw)) goto done;

    evm = evidence_load(&wf_ev); vtwt_free(&wf_ev);
    if (!evm || !evidence_repair(evm, tr.maps, tr.hidden_f16, tr.T, raw, n_raw, &rep, &n_rep, &rinfo)) goto done;
    evidence_free(evm); evm = NULL;
    /* Free main-run buffers before grouper runs to minimize peak RAM */
    free(tr.maps); tr.maps = NULL;
    free(tr.hidden_f16); tr.hidden_f16 = NULL;

    gpm = grouper_load(&wf_gp); vtwt_free(&wf_gp);
    if (!gpm || !grouper_run(gpm, retuned, n_rt, &tr, rep, n_rep, rt.ratio, &tracks, &n_tracks)) goto done;

    printf("{\"tuning_cents\":%.2f,\"tracks\":[", rt.delta_cents);
    for (size_t ti = 0; ti < n_tracks; ++ti) {
        printf("%s{\"instrument\":\"%s\",\"program\":%d,\"notes\":[",
               ti ? "," : "", tracks[ti].instrument, tracks[ti].program);
        for (size_t ni = 0; ni < tracks[ti].count; ++ni) {
            const struct midi_note *n = &tracks[ti].notes[ni];
            printf("%s[%.4f,%.4f,%d,%d]", ni ? "," : "", n->onset, n->offset, n->pitch, n->velocity);
        }
        fputs("]}", stdout);
    }
    puts("]}");
    status = 0;

done:
    grouped_tracks_free(tracks, n_tracks);
    free(rep); free(raw);
    transcribe_run_free(&tr);
    grouper_free(gpm); evidence_free(evm); lanenet_free(net);
    free(retuned); free(a16); free(audio.mono);
    vtwt_free(&wf_tr); vtwt_free(&wf_ev); vtwt_free(&wf_gp);
    nn_shutdown();
    return status;
}

static int run_drums_test(const char *weights_dir, const char *input_mp3) {
    struct vtwt_file wf_dr = {0};
    if (!load_model_weights(weights_dir, "drums.vtwt", &wf_dr)) {
        fputs("Cannot load drums weights.\n", stderr);
        return 1;
    }
    struct decoded_audio audio;
    if (!decode_mp3_mono(input_mp3, &audio)) { vtwt_free(&wf_dr); return 1; }
    nn_init(0);
    int status = 1;
    struct drums_model *dm = NULL;
    struct midi_note *notes = NULL;
    size_t n_notes = 0;
    struct drums_info dinfo = {0};

    if (audio.sample_rate < DRUMS_MIN_SOURCE_RATE) {
        printf("{\"skipped\":true,\"source_rate\":%u,\"hits\":[]}\n", audio.sample_rate);
        status = 0;
        goto done;
    }
    dm = drums_load(&wf_dr); vtwt_free(&wf_dr);
    if (!dm) { fputs("Failed loading drums model.\n", stderr); goto done; }
    if (!drums_transcribe(dm, audio.mono, audio.frames, audio.sample_rate, &notes, &n_notes, &dinfo)) {
        fputs("Drum transcription failed.\n", stderr); goto done;
    }
    printf("{\"skipped\":false,\"router\":%.6f,\"model\":\"%s\",\"hits\":[",
           dinfo.router, dinfo.used_orchestral ? "orchestral" : "drum-kit");
    for (size_t i = 0; i < n_notes; ++i) {
        printf("%s[%.4f,%.4f,%d,%d]", i ? "," : "",
               notes[i].onset, notes[i].offset, notes[i].pitch, notes[i].velocity);
    }
    puts("]}");
    status = 0;
done:
    free(notes);
    drums_free(dm);
    free(audio.mono);
    vtwt_free(&wf_dr);
    nn_shutdown();
    return status;
}

static void usage(FILE *out) {
    fputs("Usage: mp3tomidi INPUT.mp3 -o OUTPUT.mid [--mode parity|enhanced] [--no-cc74] [--weights-dir DIR]\n"
          "       mp3tomidi --enhance-midi INPUT.mp3 BASE.mid -o OUTPUT.mid [--no-cc74]\n"
          "       mp3tomidi --tempo-test INPUT.mp3\n"
          "       mp3tomidi --inspect INPUT.mp3\n"
          "       mp3tomidi --features INPUT.mp3\n"
          "       mp3tomidi --retune-test INPUT.mp3\n"
          "       mp3tomidi --lanenet-test WEIGHTS.vtwt AUDIO16K.f32 OUT_PREFIX\n"
          "       mp3tomidi --evidence-test WEIGHTS_DIR INPUT.mp3\n"
          "       mp3tomidi --grouper-test WEIGHTS_DIR INPUT.mp3\n"
          "       mp3tomidi --drums-test WEIGHTS_DIR INPUT.mp3\n"
          "  -o PATH          Write transcribed Standard MIDI File to PATH.\n"
          "  --mode parity    Dettato-parity baseline (default; 120 BPM, confidence velocities).\n"
          "  --mode enhanced  Path A enhanced MIDI (tempo grid, audio dynamics/CC7/CC11/CC74,\n"
          "                   acoustic ghost/bleed pruning, register/envelope-aware GM patches).\n"
          "  --no-cc74        Disable CC74 Brightness controller emission in enhanced mode.\n"
          "  --inspect        Report source rate, channels, decoded frames and mono RMS.\n"
          "  --features       Write float32 HCQT frames to stdout (16 kHz, first 8 s).\n", out);
}

int main(int argc, char **argv) {
    if (argc == 2 && strcmp(argv[1], "--help") == 0) { usage(stdout); return 0; }
    if (argc == 5 && strcmp(argv[1], "--lanenet-test") == 0) {
        return run_lanenet_test(argv[2], argv[3], argv[4]);
    }
    if (argc == 4 && strcmp(argv[1], "--evidence-test") == 0) {
        return run_evidence_test(argv[2], argv[3]);
    }
    if (argc == 4 && strcmp(argv[1], "--grouper-test") == 0) {
        return run_grouper_test(argv[2], argv[3]);
    }
    if (argc == 4 && strcmp(argv[1], "--drums-test") == 0) {
        return run_drums_test(argv[2], argv[3]);
    }
    if (argc == 3 && strcmp(argv[1], "--tempo-test") == 0) {
        return run_tempo_test(argv[2]);
    }
    if (argc >= 6 && strcmp(argv[1], "--enhance-midi") == 0) {
        const char *in_mp3 = argv[2];
        const char *in_mid = argv[3];
        const char *out_mid = NULL;
        int emit_cc74 = 1;
        for (int i = 4; i < argc; ++i) {
            if (strcmp(argv[i], "-o") == 0 && i + 1 < argc) out_mid = argv[++i];
            else if (strcmp(argv[i], "--no-cc74") == 0) emit_cc74 = 0;
            else { usage(stderr); return 2; }
        }
        if (!out_mid) { usage(stderr); return 2; }
        return run_enhance_midi_cli(in_mp3, in_mid, out_mid, emit_cc74);
    }
    if (argc == 3 && strcmp(argv[1], "--retune-test") == 0) {
        struct decoded_audio audio;
        if (!decode_mp3_mono(argv[2], &audio)) return 1;
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
    if (argc == 3 && (strcmp(argv[1], "--inspect") == 0 || strcmp(argv[1], "--features") == 0)) {
        /* Handled below */
    } else {
        /* Parse: INPUT.mp3 -o OUTPUT.mid [--mode parity|enhanced] [--no-cc74] [--weights-dir DIR] */
        const char *input_mp3 = NULL;
        const char *output_mid = NULL;
        const char *weights_dir = NULL;
        int enhanced = 0;
        int emit_cc74 = 1;
        for (int i = 1; i < argc; ++i) {
            if (strcmp(argv[i], "-o") == 0 && i + 1 < argc) {
                output_mid = argv[++i];
            } else if (strcmp(argv[i], "--weights-dir") == 0 && i + 1 < argc) {
                weights_dir = argv[++i];
            } else if (strcmp(argv[i], "--mode") == 0 && i + 1 < argc) {
                const char *m = argv[++i];
                if (strcmp(m, "parity") == 0) enhanced = 0;
                else if (strcmp(m, "enhanced") == 0) enhanced = 1;
                else { fprintf(stderr, "Unknown --mode: %s (expected parity or enhanced)\n", m); return 2; }
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
            return run_transcribe_cli(input_mp3, output_mid, weights_dir, enhanced, emit_cc74);
        }
        usage(stderr);
        return 2;
    }
    int features = strcmp(argv[1], "--features") == 0;
    struct decoded_audio audio;
    if (!decode_mp3_mono(argv[2], &audio)) return 1;

    int status = 1;
    float *resampled = NULL;
    if (features) {
        const float *model_in = audio.mono;
        size_t model_len = audio.frames;
        if (audio.sample_rate != MODEL_RATE) {
            if (!resample_mono(audio.mono, audio.frames,
                               (double)audio.sample_rate, (double)MODEL_RATE,
                               &resampled, &model_len)) {
                fputs("Failed to resample audio to 16 kHz.\n", stderr);
                goto done;
            }
            model_in = resampled;
        }
        if (model_len > WINDOW_SAMPLES) model_len = WINDOW_SAMPLES;
        if (!write_features(stdout, model_in, (int)model_len)) {
            perror("features");
            goto done;
        }
    } else {
        double squares = 0.0;
        for (size_t i = 0; i < audio.frames; ++i)
            squares += (double)audio.mono[i] * (double)audio.mono[i];
        printf("{\"rate\":%u,\"channels\":%u,\"frames\":%llu,\"mono_rms\":%.9g}\n",
               audio.sample_rate, audio.channels,
               (unsigned long long)audio.frames, sqrt(squares / (double)audio.frames));
    }
    if (fflush(stdout) || ferror(stdout)) { perror("output"); goto done; }
    status = 0;
done:
    free(resampled);
    free(audio.mono);
    return status;
}
