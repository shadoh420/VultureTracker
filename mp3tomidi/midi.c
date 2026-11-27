/* Standard MIDI File (SMF Type 1, 480 ticks/beat) writer and reader. */
#include "midi.h"
#include <math.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

enum { MIDI_TPB = 480 }; /* 120 BPM -> 960 ticks/second */

struct byte_buf {
    uint8_t *data;
    size_t len;
    size_t cap;
};

static int bb_reserve(struct byte_buf *b, size_t add) {
    if (b->len + add <= b->cap) return 1;
    size_t next = b->cap ? b->cap * 2 : 1024;
    while (next < b->len + add) next *= 2;
    uint8_t *p = (uint8_t *)realloc(b->data, next);
    if (!p) return 0;
    b->data = p;
    b->cap = next;
    return 1;
}

static int bb_u8(struct byte_buf *b, uint8_t v) {
    if (!bb_reserve(b, 1)) return 0;
    b->data[b->len++] = v;
    return 1;
}

static int bb_bytes(struct byte_buf *b, const void *src, size_t n) {
    if (!bb_reserve(b, n)) return 0;
    memcpy(b->data + b->len, src, n);
    b->len += n;
    return 1;
}

static int bb_u16be(struct byte_buf *b, uint16_t v) {
    uint8_t d[2] = { (uint8_t)(v >> 8), (uint8_t)(v & 0xFF) };
    return bb_bytes(b, d, 2);
}

static int bb_u32be(struct byte_buf *b, uint32_t v) {
    uint8_t d[4] = {
        (uint8_t)(v >> 24), (uint8_t)((v >> 16) & 0xFF),
        (uint8_t)((v >> 8) & 0xFF), (uint8_t)(v & 0xFF)
    };
    return bb_bytes(b, d, 4);
}

static int bb_vlq(struct byte_buf *b, uint64_t v) {
    uint8_t tmp[10];
    int n = 0;
    tmp[n++] = (uint8_t)(v & 0x7Fu);
    while ((v >>= 7) != 0) tmp[n++] = (uint8_t)((v & 0x7Fu) | 0x80u);
    if (!bb_reserve(b, (size_t)n)) return 0;
    for (int i = n - 1; i >= 0; --i) b->data[b->len++] = tmp[i];
    return 1;
}

static int bb_chunk(struct byte_buf *dst, const char tag[4], const struct byte_buf *payload) {
    return bb_bytes(dst, tag, 4) && bb_u32be(dst, (uint32_t)payload->len) &&
           bb_bytes(dst, payload->data, payload->len);
}

struct midi_ev {
    int64_t tick;
    int kind;   /* 0 = note off, 1 = control change, 2 = note on */
    uint8_t d1; /* pitch or CC number */
    uint8_t d2; /* velocity or CC value */
};

static int cmp_ev(const void *pa, const void *pb) {
    const struct midi_ev *a = (const struct midi_ev *)pa;
    const struct midi_ev *b = (const struct midi_ev *)pb;
    if (a->tick < b->tick) return -1;
    if (a->tick > b->tick) return 1;
    if (a->kind != b->kind) return a->kind - b->kind;
    if (a->d1 != b->d1) return (int)a->d1 - (int)b->d1;
    return (int)a->d2 - (int)b->d2;
}

static int clamp_int(int v, int lo, int hi) {
    return v < lo ? lo : (v > hi ? hi : v);
}

int midi_write_file_bpm(const char *path, const struct midi_track *tracks, size_t n_tracks, double bpm) {
    struct byte_buf file = {0};
    struct byte_buf trk = {0};
    struct midi_ev *evs = NULL;
    int ok = 0;

    if (!(bpm >= 20.0 && bpm <= 400.0)) bpm = 120.0;
    uint32_t us_per_beat = (uint32_t)floor(60000000.0 / bpm + 0.5);
    if (us_per_beat < 150000u) us_per_beat = 150000u;
    if (us_per_beat > 3000000u) us_per_beat = 3000000u;
    double ticks_per_sec = (1000000.0 / (double)us_per_beat) * (double)MIDI_TPB;

    /* SMF Header: Format 1, n_tracks + 1 (tempo track + instrument tracks), 480 TPB */
    if (!bb_bytes(&file, "MThd", 4) || !bb_u32be(&file, 6) ||
        !bb_u16be(&file, 1) || !bb_u16be(&file, (uint16_t)(n_tracks + 1)) ||
        !bb_u16be(&file, MIDI_TPB)) goto done;

    /* Track 0: tempo + 4/4 time signature */
    uint8_t tempo_meta[19] = {
        0x00, 0xFF, 0x51, 0x03,
        (uint8_t)((us_per_beat >> 16) & 0xFFu),
        (uint8_t)((us_per_beat >> 8) & 0xFFu),
        (uint8_t)(us_per_beat & 0xFFu),
        0x00, 0xFF, 0x58, 0x04, 0x04, 0x02, 0x18, 0x08,
        0x00, 0xFF, 0x2F, 0x00
    };
    if (!bb_bytes(&trk, tempo_meta, sizeof(tempo_meta)) || !bb_chunk(&file, "MTrk", &trk)) goto done;

    int next_pitched_ch = 0;
    for (size_t ti = 0; ti < n_tracks; ++ti) {
        const struct midi_track *t = &tracks[ti];
        trk.len = 0;
        int ch;
        if (t->is_drum) {
            ch = 9;
        } else {
            ch = next_pitched_ch++;
            if (ch == 9) ch = next_pitched_ch++;
            ch %= 16;
            if (ch == 9) ch = 10;
        }
        if (t->name && t->name[0]) {
            size_t nlen = strlen(t->name);
            if (!bb_vlq(&trk, 0) || !bb_u8(&trk, 0xFF) || !bb_u8(&trk, 0x03) ||
                !bb_vlq(&trk, nlen) || !bb_bytes(&trk, t->name, nlen)) goto done;
        }
        if (!t->is_drum) {
            uint8_t pc[3] = { 0x00, (uint8_t)(0xC0 | ch), (uint8_t)clamp_int(t->program, 0, 127) };
            if (!bb_bytes(&trk, pc, 3)) goto done;
        }
        size_t n_ev = t->count * 2 + (t->ccs ? t->n_ccs : 0);
        if (n_ev > 0) {
            evs = (struct midi_ev *)malloc(n_ev * sizeof(*evs));
            if (!evs) goto done;
            size_t w = 0;
            for (size_t i = 0; i < t->count; ++i) {
                double on = t->notes[i].onset < 0.0 ? 0.0 : t->notes[i].onset;
                double off = t->notes[i].offset < on ? on : t->notes[i].offset;
                int64_t t_on = (int64_t)floor(on * ticks_per_sec + 0.5);
                int64_t t_off = (int64_t)floor(off * ticks_per_sec + 0.5);
                if (t_off <= t_on) t_off = t_on + 1;
                uint8_t pitch = (uint8_t)clamp_int(t->notes[i].pitch, 0, 127);
                uint8_t vel = (uint8_t)clamp_int(t->notes[i].velocity, 1, 127);
                evs[w++] = (struct midi_ev){ t_on,  2, pitch, vel };
                evs[w++] = (struct midi_ev){ t_off, 0, pitch, 0 };
            }
            if (t->ccs) {
                for (size_t i = 0; i < t->n_ccs; ++i) {
                    double ct = t->ccs[i].time < 0.0 ? 0.0 : t->ccs[i].time;
                    int64_t tick = (int64_t)floor(ct * ticks_per_sec + 0.5);
                    uint8_t cc = (uint8_t)clamp_int((int)t->ccs[i].cc, 0, 127);
                    uint8_t val = (uint8_t)clamp_int((int)t->ccs[i].value, 0, 127);
                    evs[w++] = (struct midi_ev){ tick, 1, cc, val };
                }
            }
            qsort(evs, w, sizeof(*evs), cmp_ev);
            int64_t prev_tick = 0;
            for (size_t i = 0; i < w; ++i) {
                int64_t delta = evs[i].tick - prev_tick;
                if (delta < 0) delta = 0;
                prev_tick = evs[i].tick;
                uint8_t status;
                if (evs[i].kind == 0) status = (uint8_t)(0x80 | ch);
                else if (evs[i].kind == 1) status = (uint8_t)(0xB0 | ch);
                else status = (uint8_t)(0x90 | ch);
                if (!bb_vlq(&trk, (uint64_t)delta) || !bb_u8(&trk, status) ||
                    !bb_u8(&trk, evs[i].d1) || !bb_u8(&trk, evs[i].d2)) goto done;
            }
            free(evs);
            evs = NULL;
        }
        static const uint8_t eot[4] = { 0x00, 0xFF, 0x2F, 0x00 };
        if (!bb_bytes(&trk, eot, 4) || !bb_chunk(&file, "MTrk", &trk)) goto done;
    }

    FILE *fp = fopen(path, "wb");
    if (!fp) goto done;
    ok = (fwrite(file.data, 1, file.len, fp) == file.len);
    if (fclose(fp) != 0) ok = 0;

done:
    free(evs);
    free(trk.data);
    free(file.data);
    return ok;
}

int midi_write_file(const char *path, const struct midi_track *tracks, size_t n_tracks) {
    return midi_write_file_bpm(path, tracks, n_tracks, 120.0);
}

/* =========================================================================
 * Minimal SMF reader (for --enhance-midi rapid iteration on existing MIDIs)
 * ========================================================================= */

static uint16_t rd_u16be(const uint8_t *p) {
    return (uint16_t)(((uint16_t)p[0] << 8) | p[1]);
}

static uint32_t rd_u32be(const uint8_t *p) {
    return ((uint32_t)p[0] << 24) | ((uint32_t)p[1] << 16) |
           ((uint32_t)p[2] << 8) | (uint32_t)p[3];
}

static int rd_vlq(const uint8_t *buf, size_t len, size_t *pos, uint64_t *out) {
    uint64_t v = 0;
    for (int i = 0; i < 4; ++i) {
        if (*pos >= len) return 0;
        uint8_t b = buf[(*pos)++];
        v = (v << 7) | (uint64_t)(b & 0x7Fu);
        if ((b & 0x80u) == 0) { *out = v; return 1; }
    }
    return 0;
}

struct tempo_pt {
    uint64_t tick;
    uint32_t us_per_beat;
    double sec_at_tick;
};

static int cmp_tempo_pt(const void *pa, const void *pb) {
    const struct tempo_pt *a = (const struct tempo_pt *)pa;
    const struct tempo_pt *b = (const struct tempo_pt *)pb;
    return (a->tick > b->tick) - (a->tick < b->tick);
}

static double tick_to_sec(const struct tempo_pt *tmap, size_t n_tmap, uint16_t tpb, uint64_t tick) {
    size_t idx = 0;
    for (size_t i = 1; i < n_tmap; ++i) {
        if (tmap[i].tick <= tick) idx = i;
        else break;
    }
    double dt = (double)(tick - tmap[idx].tick);
    return tmap[idx].sec_at_tick + dt * ((double)tmap[idx].us_per_beat * 1e-6) / (double)tpb;
}

static int cmp_loaded_note(const void *pa, const void *pb) {
    const struct midi_note *a = (const struct midi_note *)pa;
    const struct midi_note *b = (const struct midi_note *)pb;
    if (a->onset < b->onset) return -1;
    if (a->onset > b->onset) return 1;
    return (a->pitch > b->pitch) - (a->pitch < b->pitch);
}

void midi_loaded_tracks_free(struct midi_loaded_track *tracks, size_t n_tracks) {
    if (!tracks) return;
    for (size_t i = 0; i < n_tracks; ++i) {
        free(tracks[i].name);
        free(tracks[i].notes);
    }
    free(tracks);
}

int midi_read_file(const char *path, struct midi_loaded_track **tracks_out, size_t *n_tracks_out) {
    *tracks_out = NULL;
    *n_tracks_out = 0;
    FILE *fp = fopen(path, "rb");
    if (!fp) return 0;
    if (fseek(fp, 0, SEEK_END) != 0) { fclose(fp); return 0; }
    long fsz = ftell(fp);
    rewind(fp);
    if (fsz < 14) { fclose(fp); return 0; }
    uint8_t *buf = (uint8_t *)malloc((size_t)fsz);
    if (!buf || fread(buf, 1, (size_t)fsz, fp) != (size_t)fsz) {
        free(buf); fclose(fp); return 0;
    }
    fclose(fp);
    size_t len = (size_t)fsz;

    if (memcmp(buf, "MThd", 4) != 0 || rd_u32be(buf + 4) < 6) { free(buf); return 0; }
    uint32_t hdr_len = rd_u32be(buf + 4);
    uint16_t n_chunks = rd_u16be(buf + 10);
    uint16_t tpb = rd_u16be(buf + 12);
    if (tpb == 0 || (tpb & 0x8000u)) { free(buf); return 0; }

    /* Collect all MTrk byte ranges */
    const uint8_t **trk_ptr = (const uint8_t **)calloc(n_chunks ? n_chunks : 1, sizeof(*trk_ptr));
    size_t *trk_len = (size_t *)calloc(n_chunks ? n_chunks : 1, sizeof(*trk_len));
    size_t found = 0;
    size_t pos = 8 + hdr_len;
    while (pos + 8 <= len && found < n_chunks) {
        uint32_t clen = rd_u32be(buf + pos + 4);
        if (pos + 8 + clen > len) break;
        if (memcmp(buf + pos, "MTrk", 4) == 0) {
            trk_ptr[found] = buf + pos + 8;
            trk_len[found] = clen;
            found++;
        }
        pos += 8 + clen;
    }

    /* Pass 1: collect tempo map across all tracks */
    struct tempo_pt *tmap = (struct tempo_pt *)malloc(16 * sizeof(*tmap));
    size_t n_tmap = 0, cap_tmap = 16;
    if (!trk_ptr || !trk_len || !tmap) {
        free(trk_ptr); free(trk_len); free(tmap); free(buf); return 0;
    }
    tmap[n_tmap++] = (struct tempo_pt){ 0, 500000u, 0.0 };

    for (size_t ti = 0; ti < found; ++ti) {
        const uint8_t *d = trk_ptr[ti];
        size_t dl = trk_len[ti], p = 0;
        uint64_t tick = 0;
        uint8_t running = 0;
        while (p < dl) {
            uint64_t dt = 0;
            if (!rd_vlq(d, dl, &p, &dt) || p >= dl) break;
            tick += dt;
            uint8_t st = d[p];
            if (st & 0x80u) { p++; if (st < 0xF0u) running = st; }
            else { st = running; }
            if (st == 0xFFu) {
                if (p >= dl) break;
                uint8_t mtype = d[p++];
                uint64_t mlen = 0;
                if (!rd_vlq(d, dl, &p, &mlen) || p + mlen > dl) break;
                if (mtype == 0x51u && mlen == 3) {
                    uint32_t us = ((uint32_t)d[p] << 16) | ((uint32_t)d[p + 1] << 8) | d[p + 2];
                    if (n_tmap == cap_tmap) {
                        cap_tmap *= 2;
                        struct tempo_pt *g = (struct tempo_pt *)realloc(tmap, cap_tmap * sizeof(*g));
                        if (!g) { free(trk_ptr); free(trk_len); free(tmap); free(buf); return 0; }
                        tmap = g;
                    }
                    tmap[n_tmap++] = (struct tempo_pt){ tick, us ? us : 500000u, 0.0 };
                }
                p += (size_t)mlen;
            } else if (st == 0xF0u || st == 0xF7u) {
                uint64_t slen = 0;
                if (!rd_vlq(d, dl, &p, &slen) || p + slen > dl) break;
                p += (size_t)slen;
            } else {
                uint8_t hi = st & 0xF0u;
                size_t need = (hi == 0xC0u || hi == 0xD0u) ? 1 : 2;
                if (p + need > dl) break;
                p += need;
            }
        }
    }
    qsort(tmap, n_tmap, sizeof(*tmap), cmp_tempo_pt);
    /* Deduplicate identical tick entries (keep latest) and integrate sec_at_tick */
    size_t tw = 0;
    for (size_t i = 0; i < n_tmap; ++i) {
        if (tw > 0 && tmap[tw - 1].tick == tmap[i].tick) tmap[tw - 1] = tmap[i];
        else tmap[tw++] = tmap[i];
    }
    n_tmap = tw;
    tmap[0].sec_at_tick = 0.0;
    for (size_t i = 1; i < n_tmap; ++i) {
        double dt = (double)(tmap[i].tick - tmap[i - 1].tick);
        tmap[i].sec_at_tick = tmap[i - 1].sec_at_tick +
                              dt * ((double)tmap[i - 1].us_per_beat * 1e-6) / (double)tpb;
    }

    /* Pass 2: parse each track's notes */
    struct midi_loaded_track *out = (struct midi_loaded_track *)calloc(found ? found : 1, sizeof(*out));
    size_t n_out = 0;
    if (!out) { free(trk_ptr); free(trk_len); free(tmap); free(buf); return 0; }

    for (size_t ti = 0; ti < found; ++ti) {
        const uint8_t *d = trk_ptr[ti];
        size_t dl = trk_len[ti], p = 0;
        uint64_t tick = 0;
        uint8_t running = 0;
        char *tname = NULL;
        int prog = 0, is_drum = 0;
        int active_vel[16][128];
        double active_on[16][128];
        memset(active_vel, 0, sizeof(active_vel));
        struct midi_note *notes = NULL;
        size_t count = 0, cap = 0;

        while (p < dl) {
            uint64_t dt = 0;
            if (!rd_vlq(d, dl, &p, &dt) || p >= dl) break;
            tick += dt;
            uint8_t st = d[p];
            if (st & 0x80u) { p++; if (st < 0xF0u) running = st; }
            else { st = running; }
            if (st == 0xFFu) {
                if (p >= dl) break;
                uint8_t mtype = d[p++];
                uint64_t mlen = 0;
                if (!rd_vlq(d, dl, &p, &mlen) || p + mlen > dl) break;
                if (mtype == 0x03u && mlen > 0 && !tname) {
                    tname = (char *)malloc((size_t)mlen + 1);
                    if (tname) { memcpy(tname, d + p, (size_t)mlen); tname[mlen] = '\0'; }
                }
                p += (size_t)mlen;
            } else if (st == 0xF0u || st == 0xF7u) {
                uint64_t slen = 0;
                if (!rd_vlq(d, dl, &p, &slen) || p + slen > dl) break;
                p += (size_t)slen;
            } else {
                uint8_t hi = st & 0xF0u;
                int ch = st & 0x0Fu;
                size_t need = (hi == 0xC0u || hi == 0xD0u) ? 1 : 2;
                if (p + need > dl) break;
                uint8_t b1 = d[p], b2 = (need == 2) ? d[p + 1] : 0;
                p += need;
                if (hi == 0xC0u) {
                    prog = (int)(b1 & 0x7Fu);
                } else if (hi == 0x90u || hi == 0x80u) {
                    int pitch = (int)(b1 & 0x7Fu);
                    int vel = (hi == 0x90u) ? (int)(b2 & 0x7Fu) : 0;
                    double sec = tick_to_sec(tmap, n_tmap, tpb, tick);
                    if (ch == 9) is_drum = 1;
                    if (vel > 0) {
                        if (active_vel[ch][pitch] > 0) {
                            if (count == cap) {
                                cap = cap ? cap * 2 : 128;
                                notes = (struct midi_note *)realloc(notes, cap * sizeof(*notes));
                            }
                            if (notes) {
                                double off = sec > active_on[ch][pitch] + 0.01 ? sec : active_on[ch][pitch] + 0.01;
                                notes[count++] = (struct midi_note){ active_on[ch][pitch], off, pitch, active_vel[ch][pitch] };
                            }
                        }
                        active_vel[ch][pitch] = vel;
                        active_on[ch][pitch] = sec;
                    } else if (active_vel[ch][pitch] > 0) {
                        if (count == cap) {
                            cap = cap ? cap * 2 : 128;
                            notes = (struct midi_note *)realloc(notes, cap * sizeof(*notes));
                        }
                        if (notes) {
                            double off = sec > active_on[ch][pitch] + 0.01 ? sec : active_on[ch][pitch] + 0.01;
                            notes[count++] = (struct midi_note){ active_on[ch][pitch], off, pitch, active_vel[ch][pitch] };
                        }
                        active_vel[ch][pitch] = 0;
                    }
                }
            }
        }
        /* Flush any unclosed notes */
        double end_sec = tick_to_sec(tmap, n_tmap, tpb, tick);
        for (int ch = 0; ch < 16; ++ch) {
            for (int pitch = 0; pitch < 128; ++pitch) {
                if (active_vel[ch][pitch] > 0) {
                    if (count == cap) {
                        cap = cap ? cap * 2 : 128;
                        notes = (struct midi_note *)realloc(notes, cap * sizeof(*notes));
                    }
                    if (notes) {
                        double off = end_sec > active_on[ch][pitch] + 0.05 ? end_sec : active_on[ch][pitch] + 0.05;
                        notes[count++] = (struct midi_note){ active_on[ch][pitch], off, pitch, active_vel[ch][pitch] };
                    }
                }
            }
        }
        if (count > 0) {
            qsort(notes, count, sizeof(*notes), cmp_loaded_note);
            if (!tname) {
                const char *def = is_drum ? "Drums" : "Track";
                tname = (char *)malloc(strlen(def) + 1);
                if (tname) strcpy(tname, def);
            }
            out[n_out++] = (struct midi_loaded_track){ tname, prog, is_drum, notes, count };
        } else {
            free(tname);
            free(notes);
        }
    }

    free(trk_ptr); free(trk_len); free(tmap); free(buf);
    *tracks_out = out;
    *n_tracks_out = n_out;
    return 1;
}
