"""Immutable render snapshots shared by phrase comparisons and export jobs."""
import copy
import glob
import itertools
import os
from pathlib import Path
import re
import shutil
import tempfile
import threading
import uuid

from . import api
from .model import ORDER_END
from .notation import format_cell
from .openmpt import LoadedModule
from .fileio import atomic_write, device_name, link_new, protect_outputs, wav_bytes
from .history import digest

RATE = 44100


def map_jumps(spec, target):
    out = copy.deepcopy(spec)
    data = out.get('data', '') if isinstance(out, dict) else str(out)
    rows = []
    for row in data.splitlines(keepends=True):
        body, sep, comment = row.partition(';')
        rows.append(api._JUMP.sub(lambda m: f'B{target(int(m.group(1), 16)):02X}', body) + sep + comment)
    if isinstance(out, dict):
        out['data'] = ''.join(rows)
        return out
    return ''.join(rows)


def _ring_out(base, folder, mod, region, muted, mix, tail, loop=False):
    """(standalone IT, audio IT, seconds, seek) of `region`: the audio plays the orders before it for the player's state,
    then the region, then empty patterns through which what still sounds rings out. `loop`: the region plays twice and
    the audio starts at the second pass, so it begins with what its own end leaves ringing, as a looping game plays it."""
    from .gui import patch_it
    a, r0, b, r1 = map(int, region)
    if not 0 <= a <= b < len(mod.orders) or any(mod.orders[o] >= len(mod.patterns) for o in (a, b)):
        raise ValueError('Region endpoints must be playable orders')
    endpat = mod.patterns[mod.orders[b]]
    if not 0 <= r0 < len(mod.patterns[mod.orders[a]].rows) or not 0 <= r1 < len(endpat.rows) or (a == b and r0 > r1):
        raise ValueError('Invalid row range')
    # IT export is a standalone order slice; audio warms up all preceding orders to recover player state.
    standalone = copy.deepcopy(base)
    standalone['orders'] = list(base['orders'][a:b+1]) + ['---']
    standalone['patterns'] = {k: map_jumps(v, lambda t: t-a if a <= t <= b else b-a+1)
                              for k, v in base['patterns'].items() if k in base['orders'][a:b+1]}
    it = patch_it(api.compile_song(standalone, folder)[0], muted, mix)
    base = copy.deepcopy(base)
    base['patterns'] = {k: map_jumps(v, lambda t: t if t <= b else b+1) for k, v in base['patterns'].items()}
    base['orders'] = list(base['orders'][:b+1])
    name = next(n for n in (f'vt_end_{i}' for i in itertools.count()) if n not in base['patterns'])
    base['patterns'][name] = {'rows': r1+1, 'data': '\n'.join(' | '.join(format_cell(c) for c in row) for row in endpat.rows[:r1+1]) + '\n'}
    base['patterns'][name] = map_jumps(base['patterns'][name], lambda t: b+1)  # a jump out of it (a loop back too) ends the section
    # A break out of the last included pattern starts the empty tail at row zero.
    base['patterns'][name]['data'] = re.sub(r'(?<![^\s|])C[0-9A-F]{2}(?![^\s|])', 'C00', base['patterns'][name]['data'])
    base['patterns'][name+'_tail'] = {'rows': 200, 'data': ''}
    tails = [name+'_tail'] * (1 + int(tail / 1.9))
    s = a
    if loop:
        jumps = []
        for p in base['orders'][a:b]:
            map_jumps(base['patterns'].get(p, ''), lambda t: jumps.append(t) or t)
        if jumps:
            raise ValueError('A game loop needs a region without position jumps (Bxx) before its last pattern')
        s = b+1  # the second pass, whose end jumps on to the tail
        base['patterns'][name+'_again'] = map_jumps(base['patterns'][name], lambda t: 2*b-a+2)
        tails = list(base['orders'][a:b]) + [name+'_again'] + tails
    base['orders'] = base['orders'][:b] + [name] + tails
    render_it = patch_it(api.compile_song(base, folder)[0], muted, mix)
    with LoadedModule(render_it) as lm:
        end = lm.order_start(s+b-a+1)
        start = lm.order_start(s, r0)
    if end <= start:
        raise ValueError('The selected region does not have a forward playback span; adjust its jumps before exporting')
    return it, render_it, end-start, (s, r0)


def snapshot(song, folder, region=None, mix=None, muted=(), tail=2.0, loop=False):
    from .gui import patch_it, voice_entry
    base = copy.deepcopy(song)
    base.pop('sections', None)
    assets = {p.resolve(): digest(p.read_bytes()) for p in api.output_sources(base, folder)}
    mix = copy.deepcopy(mix or {})
    for num, edit in (mix.get('instrument') or {}).items():
        if int(num) in (base.get('instruments') or {}):
            base['instruments'][int(num)] = voice_entry(base['instruments'][int(num)], edit)
    whole, mod, warnings = api.compile_song(base, folder)
    it = patch_it(whole, muted, mix)
    with LoadedModule(it) as lm:
        duration = lm.duration()
    seek = None
    tail = float(tail)
    if not 0 <= tail <= 10:
        raise ValueError('Tail must be between 0 and 10 seconds')
    if region:
        it, render_it, duration, seek = _ring_out(base, folder, mod, region, muted, mix, tail, loop)
    else:
        render_it = it
        # The whole song rings out like a section when it ends on its last order (a loop back there included); when a
        # jump elsewhere ends it, the tail stays silence.
        stop = mod.orders.index(ORDER_END) if ORDER_END in mod.orders else len(mod.orders)
        last = max((i for i in range(stop) if mod.orders[i] < len(mod.patterns)), default=None)
        if tail and last is not None:
            try:
                ring = _ring_out(base, folder, mod, (0, 0, last, len(mod.patterns[mod.orders[last]].rows) - 1), muted, mix, tail)
                if abs(ring[2] - duration) < 1e-3:
                    render_it = ring[1]
            except ValueError:
                pass
    if any(not p.is_file() or digest(p.read_bytes()) != sha for p, sha in assets.items()):
        raise ValueError('A source asset changed while compiling the export snapshot; retry after it is saved')
    return {'it': it, 'render_it': render_it, 'seek': seek, 'seconds': duration,
            'frames': round((duration+tail)*RATE), 'channels': len(mod.channels), 'warnings': warnings,
            'loop': (0, round(duration*RATE)) if loop and region else None}


PPQ = 480  # OpenMPT's MIDI export resolution


def _vlq(n):
    out = [n & 0x7F]
    while n > 0x7F:
        n >>= 7
        out.insert(0, 0x80 | (n & 0x7F))
    return bytes(out)


def _midi_track(events):
    """An MTrk from [(tick, order, bytes)]: sorted by tick, then order (meta and controllers, note-offs, note-ons, as
    OpenMPT queues a row's note-ons last), delta times, the end-of-track meta."""
    body, now = b"", 0
    for tick, _, msg in sorted(events, key=lambda e: (e[0], e[1])):
        body += _vlq(tick - now) + msg
        now = tick
    body += b"\0\xff\x2f\0"
    return b"MTrk" + len(body).to_bytes(4, "big") + body


def _meta(kind, data):
    return bytes([0xFF, kind]) + _vlq(len(data)) + data


def to_midi(it):
    """A standard MIDI file (type 1, 480 ticks a quarter) of the module `it`, as OpenMPT's MIDI export (mod2midi.cpp)
    writes one: a first track with the song's name, message, time signature (rows per bar over rows per beat, in
    quarters), tempo at each change of libopenmpt's BPM, and the global volume as a master-volume SysEx; then a track
    per instrument played (per sample in a song without instruments), named after it. A tracker channel plays on MIDI
    channel (channel mod 15, skipping 10), its pan as CC 10 at the first note; a note is the instrument's note map,
    its velocity the volume column (or the sample's volume) doubled, a note-off at the next note, `===`, `^^^`, `~~~`
    or the song's end. Rows are timed as libopenmpt plays them (jumps and loops included); a note delayed by SDx starts
    that many ticks into its row; a tone portamento (G) holds the note it slides. Every other effect is left out and
    counted in the warnings. Muted channels are left out. Returns (bytes, warnings)."""
    from .itreader import read_it
    from .model import NOTE_CUT, NOTE_FADE, NOTE_OFF
    mod, _ = read_it(it)
    with LoadedModule(it) as lm:
        rows = lm.row_starts(RATE)
        end = lm.end
    beat, bar = (mod.row_highlight[0] or 4), (mod.row_highlight[1] or 16)
    segs, bpm0 = [], None  # (second, tick, bpm) where the tempo changes

    def tick(t):
        s = next((s for s in reversed(segs) if s[0] <= t), segs[0])
        return round(s[1] + (t - s[0]) * s[2] * PPQ / 60)
    conductor = [(0, 0, _meta(3, mod.title.encode("latin-1", "replace")))]
    if mod.message:
        conductor.append((0, 0, _meta(1, mod.message.encode("latin-1", "replace"))))
    conductor.append((0, 0, _meta(0x58, bytes([max(1, bar // beat), 2, 24, 8]))))
    gv = lambda v: (lambda m: bytes([0xF0, 0x07, 0x7F, 0x7F, 0x04, 0x01, m & 0x7F, (m >> 7) & 0x7F, 0xF7]))(2 * v * 0x3FFF // 256)
    conductor.append((0, 0, gv(mod.global_volume)))
    tracks, pans_sent, dropped = {}, {}, {}
    sounding = {}  # tracker channel -> (track key, midi channel, note)
    last_ins = {}
    ins_mode = mod.instruments is not None
    for t, order, row, bpm, speed in rows:
        if bpm and bpm != bpm0:
            segs.append((t, tick(t) if segs else 0, bpm))
            conductor.append((tick(t), 0, _meta(0x51, round(60_000_000 / bpm).to_bytes(3, "big"))))
            bpm0 = bpm
        if not 0 <= order < len(mod.orders) or mod.orders[order] >= len(mod.patterns):
            continue
        cells = mod.patterns[mod.orders[order]].rows
        if row >= len(cells):
            continue
        for ch, cell in enumerate(cells[row]):
            if ch >= len(mod.channels) or mod.channels[ch].muted:
                continue
            letter = chr(64 + cell.effect) if 1 <= cell.effect <= 26 else ""
            delay = cell.param & 0xF if letter == "S" and cell.param >> 4 == 0xD else 0
            porta = letter == "G" or (cell.volcmd is not None and 193 <= cell.volcmd <= 202)
            if letter == "V":
                conductor.append((tick(t), 0, gv(min(cell.param, 128))))
            elif letter and letter not in "ABCT" and not (letter == "S" and cell.param >> 4 == 0xD):
                dropped[letter] = dropped.get(letter, 0) + 1
            if cell.volcmd is not None and cell.volcmd > 64:
                dropped["volume column"] = dropped.get("volume column", 0) + 1
            if cell.instrument:
                last_ins[ch] = cell.instrument
            if cell.note is None or (porta and cell.note < 120):
                continue
            if delay >= speed:  # IT plays no note delayed past its row
                continue
            at = tick(t + delay * 60 / (bpm0 * beat * speed))  # a tick lasts 60 / (bpm * rows per beat * speed) s
            if ch in sounding:
                key, mch, note = sounding.pop(ch)
                tracks.setdefault(key, []).append((at, 1, bytes([0x80 | mch, note, 0])))
            if cell.note in (NOTE_OFF, NOTE_CUT, NOTE_FADE) or cell.note >= 120:
                continue
            num = last_ins.get(ch, 0)
            if ins_mode:
                if not 1 <= num <= len(mod.instruments):
                    continue
                note, smp = mod.instruments[num - 1].keymap[cell.note]
            else:
                note, smp = cell.note, num
            if not 1 <= smp <= len(mod.samples) or not mod.samples[smp - 1].data:
                continue
            vol = cell.volcmd if cell.volcmd is not None and cell.volcmd <= 64 else mod.samples[smp - 1].volume
            mch = ch % 15 + (1 if ch % 15 >= 9 else 0)
            pan = min(127, 2 * (32 if mod.channels[ch].pan == 100 else mod.channels[ch].pan))
            if pans_sent.get(mch) != pan:
                tracks.setdefault(num, []).append((at, 0, bytes([0xB0 | mch, 10, pan])))
                pans_sent[mch] = pan
            tracks.setdefault(num, []).append((at, 2, bytes([0x90 | mch, note, min(2 * vol, 127)])))
            sounding[ch] = (num, mch, note)
    for key, mch, note in sounding.values():
        tracks[key].append((tick(end), 1, bytes([0x80 | mch, note, 0])))
    names = mod.instruments if ins_mode else mod.samples
    out = [_midi_track(conductor)]
    for key in sorted(tracks):
        name = (names[key - 1].name if key <= len(names) else "") or f"{'instrument' if ins_mode else 'sample'} {key}"
        out.append(_midi_track([(0, 0, _meta(3, name.encode("latin-1", "replace")))] + tracks[key]))
    data = b"MThd" + (6).to_bytes(4, "big") + (1).to_bytes(2, "big") + len(out).to_bytes(2, "big") + PPQ.to_bytes(2, "big")
    warnings = [f"MIDI: left out {', '.join(f'{n} {k}' if len(k) > 1 else f'{n} {k}xx' for k, n in sorted(dropped.items()))} "
                f"(effects a MIDI file does not hold)"] if dropped else []
    return data + b"".join(out), warnings


def render(snapshot, silenced=(), cancel=None, rate=RATE, depth=16, repeat=0):
    """The snapshot's audio as interleaved stereo bytes at `rate`: int16, or float32 for `depth` 24 and 'float'.
    `repeat` plays the whole song that many more times (its last pass ends where the song does, the tail silence)."""
    from .gui import patch_it
    frames = round((snapshot['frames'] / RATE + snapshot['seconds'] * repeat) * rate)
    width = 4 if depth == 16 else 8
    with LoadedModule(patch_it(snapshot['it'] if repeat else snapshot['render_it'], silenced)) as lm:
        lm.timed_at(rate)
        if snapshot['seek'] is not None:
            lm.order_start(*snapshot['seek'])
        pcm = lm.render(rate, repeat=repeat, max_seconds=frames/rate, cancel=cancel, floats=depth != 16)
    length = frames * width
    return pcm[:length].ljust(length, b'\0')


def sources(state):
    """Every file an output must not replace: the song, its samples and candidates and the app's files beside it."""
    paths = [state.song_path, *state.files, state.meta_path, state.history_store.path, state.history_store.journal,
             state.notes_path, state.notes_path.with_suffix('.md')]
    paths.extend(state.base_dir.glob(glob.escape(state.song_path.stem) + '.notes-*'))  # the notes archives
    paths.extend((state.base_dir / (state.song_path.stem + '.phrases')).glob('*.json'))  # earlier phrase comparisons
    paths.extend(p for v in (state.meta.get('candidates') or {}).values() for p in v)
    paths.extend(state.base_dir / p for p in (state.meta.get('phrase') or {}).get('assets', {}))
    return paths


RATES = (22050, 32000, 44100, 48000, 88200, 96000)


def render_settings(options, fmt, region):
    """The render settings in `options`, checked: rate (Hz), depth (16, 24 for WAV and FLAC, 'float' for WAV), bitrate
    (MP3 kbit/s), quality (OGG Vorbis -1 to 10) and repeat (more passes of the whole song, 0 to 16). The defaults are
    the export's: 44.1 kHz, 16 bits, MP3 at 192 kbit/s, OGG at quality 6, one pass."""
    rate = int(options.get('rate') or RATE)
    depth = options.get('depth') or 16
    depth = depth if depth == 'float' else int(depth)
    repeat = int(options.get('repeat') or 0)
    bitrate, quality = options.get('bitrate'), options.get('quality')
    if rate not in RATES:
        raise ValueError(f"Rate is one of {', '.join(map(str, RATES))} Hz")
    if depth not in (16, 24, 'float') or (depth == 24 and fmt not in ('wav', 'flac')) or (depth == 'float' and fmt != 'wav'):
        raise ValueError('Depth is 16 bits, 24 for WAV and FLAC, or float for WAV')
    if bitrate not in (None, '') and (fmt != 'mp3' or not 32 <= int(bitrate) <= 320):
        raise ValueError('Bitrate is for MP3: 32 to 320 kbit/s')
    if quality not in (None, '') and (fmt != 'ogg' or not -1 <= float(quality) <= 10):
        raise ValueError('Quality is for OGG: Vorbis -1 to 10')
    if not 0 <= repeat <= 16 or (repeat and region):
        raise ValueError('Repeat plays the whole song 0 to 16 more times (not a section or a game loop)')
    lufs, ceiling = options.get('master_lufs'), options.get('master_ceiling')
    if lufs not in (None, ''):
        lufs, ceiling = float(lufs), float(-1.0 if ceiling in (None, '') else ceiling)
        if fmt in ('it', 'mid') or not -40 <= lufs <= -5 or not -12 <= ceiling <= 0:
            raise ValueError('Normalise is for audio: -40 to -5 LUFS, a ceiling of -12 to 0 dBTP')
    else:
        lufs = None
    return {'rate': rate, 'depth': depth, 'repeat': repeat, 'bitrate': int(bitrate) if bitrate not in (None, '') else None,
            'quality': float(quality) if quality not in (None, '') else None,
            'master': {'lufs': lufs, 'ceiling': ceiling} if lufs is not None else None}


def master_gain(pcm, rate, lufs, ceiling):
    """(gain in dB, report) that brings float32 stereo `pcm` to `lufs` integrated loudness, held back where its true
    peak would pass `ceiling` dBTP (a gain, no limiter: the sound is not changed, only its level)."""
    import numpy as np
    from .dsp import measure_mix
    m = measure_mix(np.frombuffer(pcm, '<f4').reshape(-1, 2).T, rate)
    if m['lufs'] is None or m['true_peak_dbtp'] is None:
        return 0.0, 'Normalise: the mix is silent, left as it is'
    gain = lufs - m['lufs']
    held = m['true_peak_dbtp'] + gain > ceiling
    if held:
        gain = ceiling - m['true_peak_dbtp']
    return gain, (f"Normalised by {gain:+.2f} dB: {m['lufs'] + gain:.1f} LUFS, true peak {m['true_peak_dbtp'] + gain:.1f} "
                  f"dBTP" + (f" (the {ceiling:g} dBTP ceiling held it under {lufs:g} LUFS)" if held else "")
                  + "; the export differs from the module, the .it is untouched")


def _at_depth(pcm, gain, depth):
    """Float32 stereo bytes with `gain` dB applied, as int16 bytes for `depth` 16 (rounded, clipped), else float32."""
    import numpy as np
    x = np.frombuffer(pcm, '<f4') * np.float32(10 ** (gain / 20))
    if depth == 16:
        return np.clip(np.round(x * 32768), -32768, 32767).astype('<i2').tobytes()
    return x.astype('<f4').tobytes()


def prepare(state, options):
    """Compile before queueing so later edits, faders and WAV changes cannot alter this job."""
    with state.lock:
        state._need_compiled()
        if state.dirty():
            raise ValueError('Compare and RELOAD external edits before exporting')
        fmt = str(options.get('fmt', 'wav')).lower()
        if fmt not in ('it', 'wav', 'mp3', 'ogg', 'flac', 'mid'):
            raise ValueError('Choose IT, WAV, MP3, OGG, FLAC or MID')
        region_name = options.get('region') or ''
        loop = bool(options.get('loop'))
        if loop and fmt not in ('wav', 'ogg', 'flac'):
            raise ValueError('A game loop is exported as WAV (smpl chunk), OGG or FLAC (LOOPSTART and LOOPLENGTH tags)')
        render_opts = render_settings(options, fmt, loop or bool(region_name))
        region = None
        if region_name or loop:
            orders = state.mod.orders
            if region_name:
                if region_name not in (state.song.get('sections') or {}):
                    raise ValueError(f'No section named {region_name}')
                a, b = state.song['sections'][region_name]
            else:  # a loop without a section: the whole song, its orders up to the end marker
                a, b = 0, orders.index(ORDER_END) if ORDER_END in orders else len(orders)
            playable = [i for i in range(a, b) if state.mod.orders[i] < len(state.mod.patterns)]
            if not playable:
                raise ValueError('Section has no playable orders')
            region = (playable[0], 0, playable[-1], len(state.mod.patterns[state.mod.orders[playable[-1]]].rows)-1)
        mode, mutes = options.get('mix', 'saved'), options.get('mutes', 'ignore')
        if mode not in ('saved', 'current') or mutes not in ('ignore', 'respect'):
            raise ValueError('Choose saved/current mix and ignore/respect audition mutes')
        mix = state.mix() if mode == 'current' else {}
        silenced = state.silenced() if mutes == 'respect' else []
        base = api.from_yaml(state.patched_text(state.want)[0]) if mode == 'current' and state.want else state.song
        snap = snapshot(base, state.base_dir, region, mix, silenced, options.get('tail', 2), loop)
        folder = (state.base_dir / Path(options.get('destination') or '.').expanduser()).resolve()  # relative: beside the song
        name = str(options.get('name') or state.song_path.stem)
        if name in ('.', '..') or not name.strip() or re.search(r'[\\/:*?"<>|]', name) or device_name(name):
            raise ValueError('Output name must be a filename without directories or reserved characters, and not a '
                             'Windows device name (CON, PRN, AUX, NUL, COM1-9, LPT1-9)')
        chans = [i for i in range(snap['channels']) if any(u[i] for u in state.facts['use'])] if options.get('stems') else []
        stemfmt = 'wav' if fmt in ('it', 'mid') else fmt
        todo = [(folder / (name+'.'+fmt), None, fmt)] if options.get('song', True) else []
        if options.get('include_it') and fmt != 'it':
            todo.insert(0, (folder / (name+'.it'), None, 'it'))
        stemdir = folder / (name+'_stems')
        for i in chans:
            label = re.sub(r'[^\w-]+', '_', state.facts['channels'][i]).strip('_') or 'ch'
            todo.append((stemdir / f'{i+1:02d}-{label}.{stemfmt}', i, stemfmt))
        if not todo:
            raise ValueError('Choose song or stems to export')
        protected = sources(state)
        protect_outputs([p for p, _, _ in todo], protected)
        existing = {str(p): digest(p.read_bytes()) if p.exists() else None for p, _, _ in todo}
        if not options.get('replace', False) and any(v is not None for v in existing.values()):
            raise ValueError('An output exists. Choose another destination/name or enable Replace previous exports')
        return {'snapshot': snap, 'todo': todo, 'sources': protected, 'existing': existing, 'render': render_opts,
                'cancel': threading.Event(), 'folder': folder, 'region': region_name, 'mix': mode,
                'result': {'job_id': uuid.uuid4().hex, 'status': 'queued', 'done': 0, 'total': len(todo), 'dir': str(stemdir) if chans else None,
                           'song': str(todo[0][0]) if options.get('song', True) else None, 'fmt': fmt, 'error': None,
                           'files': [], 'seconds': snap['frames']/RATE + snap['seconds'] * render_opts['repeat'],
                           'snapshot': digest(snap['it'])[:12], 'rate': render_opts['rate'],
                           'warnings': snap['warnings'], 'mismatches': [], 'bytes': len(snap['it']),
                           'loop': (0, round(snap['seconds'] * render_opts['rate'])) if snap['loop'] else None}}


def run(job, encode):
    """Render every file privately, then publish; failed/cancelled jobs retain earlier outputs."""
    result, cancel = job['result'], job['cancel'].is_set
    stage = None
    published, backups, rendered_hashes = [], {}, {}
    try:
        if cancel():
            raise ValueError('Export cancelled')
        result['status'] = 'rendering'
        job['folder'].mkdir(parents=True, exist_ok=True)
        stage = Path(tempfile.mkdtemp(prefix='.vt-export-', dir=job['folder']))
        staged, gain = [], None
        for i, (path, ch, fmt) in enumerate(job['todo']):
            if cancel():
                raise ValueError('Export cancelled')
            tmp = stage / f'{i}.{fmt}'
            if fmt == 'it':
                atomic_write(tmp, job['snapshot']['it'])
            elif fmt == 'mid':
                data, notes = to_midi(job['snapshot']['it'])
                result['warnings'] = [*result['warnings'], *notes]
                atomic_write(tmp, data)
            else:
                opts = job.get('render') or {'rate': RATE, 'depth': 16, 'repeat': 0}
                silenced = [] if ch is None else [c for c in range(job['snapshot']['channels']) if c != ch]
                depth = opts['depth'] if fmt in ('wav', 'flac') else 16
                if opts.get('master'):  # one gain from the whole mix, for the song and every stem alike
                    if gain is None:
                        gain, report = master_gain(render(job['snapshot'], [], cancel, opts['rate'], 'float', opts['repeat']),
                                                   opts['rate'], opts['master']['lufs'], opts['master']['ceiling'])
                        result['warnings'] = [*result['warnings'], report]
                        result['master'] = round(gain, 2)
                    pcm = _at_depth(render(job['snapshot'], silenced, cancel, opts['rate'], 'float', opts['repeat']), gain, depth)
                else:
                    pcm = render(job['snapshot'], silenced, cancel, opts['rate'], depth, opts['repeat'])
                if fmt == 'wav':
                    atomic_write(tmp, wav_bytes(pcm, opts['rate'], result['loop'], depth))
                elif opts['rate'] == RATE and depth == 16 and not opts.get('bitrate') and opts.get('quality') is None:  # unchanged
                    encode(tmp, pcm, fmt, result['loop'])
                else:
                    encode(tmp, pcm, fmt, result['loop'], opts['rate'], depth, opts.get('bitrate'), opts.get('quality'))
            rendered_hashes[path] = digest(tmp.read_bytes())
            staged.append((path, tmp))
            result['done'] = i+1
        protect_outputs([p for p, _ in staged], job['sources'])
        for i, (path, tmp) in enumerate(staged):
            current = digest(path.read_bytes()) if path.exists() else None
            if current != job['existing'][str(path)]:
                raise ValueError(f'{path} changed while rendering; previous output kept')
            if current is not None:
                backup = stage / f'{i}.previous'
                shutil.copyfile(path, backup)
                backups[path] = backup
        if cancel():
            raise ValueError('Export cancelled')
        result['status'] = 'publishing'  # short commit phase; cancellation never interrupts it halfway
        for path, tmp in staged:
            protect_outputs([path], job['sources'])
            current = digest(path.read_bytes()) if path.exists() else None
            if current != job['existing'][str(path)]:
                raise ValueError(f'{path} changed before publication; previous output kept')
            path.parent.mkdir(parents=True, exist_ok=True)
            if job['existing'][str(path)] is None:
                link_new(tmp, path)  # exclusive creation; an intervening file is never replaced
            else:
                os.replace(tmp, path)
            published.append(path)
        result['files'] = [str(p) for p, _ in staged]
        result['status'] = 'done'
        for path, ch, fmt in job['todo']:
            if ch is None and fmt in ('it', 'wav'):
                result[fmt] = str(path)
    except Exception as error:
        failed_rollback = False
        for path in reversed(published):
            try:
                if not path.exists() or digest(path.read_bytes()) != rendered_hashes[path]:
                    raise OSError('A published output changed externally; recovery copies retained')
                if path in backups:
                    atomic_write(path, backups[path].read_bytes())
                else:
                    path.unlink()
            except OSError:
                failed_rollback = True
        result.update(status='cancelled' if cancel() else 'failed', error=str(error))
        if failed_rollback:
            result['error'] += f'; rollback incomplete: previous files retained in {stage}'
            stage = None  # preserve the recovery copies
    finally:
        if stage is not None:
            shutil.rmtree(stage)
    return result
