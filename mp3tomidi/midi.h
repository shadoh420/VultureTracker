/* Zero-dependency Standard MIDI File (SMF Type 1) writer and reader. */
#ifndef MP3TOMIDI_MIDI_H
#define MP3TOMIDI_MIDI_H

#include <stddef.h>
#include <stdint.h>

struct midi_note {
    double onset;
    double offset;
    int pitch;      /* 0..127 */
    int velocity;   /* 1..127 */
};

struct midi_cc {
    double time;
    uint8_t cc;     /* 0..127 (e.g. 7=Volume, 11=Expression, 74=Brightness) */
    uint8_t value;  /* 0..127 */
};

struct midi_track {
    const char *name;
    int program;    /* 0..127 (ignored for drums) */
    int is_drum;
    const struct midi_note *notes;
    size_t count;
    const struct midi_cc *ccs; /* optional; NULL when n_ccs == 0 */
    size_t n_ccs;
};

/* Write a Type-1 SMF at 120 BPM (480 ticks/beat) to `path` (Dettato parity format).
 * Returns 1 on success, 0 on failure (never partially overwrites on malloc error). */
int midi_write_file(const char *path, const struct midi_track *tracks, size_t n_tracks);

/* Write a Type-1 SMF at `bpm` (480 ticks/beat), including any CC events on tracks.
 * When bpm == 120.0 and all n_ccs == 0, output is byte-identical to midi_write_file. */
int midi_write_file_bpm(const char *path, const struct midi_track *tracks, size_t n_tracks, double bpm);

/* Loaded editable track returned by midi_read_file (owned strings & arrays). */
struct midi_loaded_track {
    char *name;
    int program;
    int is_drum;
    struct midi_note *notes;
    size_t count;
};

/* Read a Type-0 or Type-1 SMF into note tracks (for diagnostics and --enhance-midi).
 * Returns 1 on success, 0 on error. Free with midi_loaded_tracks_free. */
int midi_read_file(const char *path, struct midi_loaded_track **tracks_out, size_t *n_tracks_out);
void midi_loaded_tracks_free(struct midi_loaded_track *tracks, size_t n_tracks);

#endif
