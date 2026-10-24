"""Guitar Pro 1 (v1, 1.01-1.04) and Guitar Pro 2 (2.20, 2.21) .gtp tabs, read as TuxGuitar 2.1.0's
GP1InputStream/GP2InputStream read them, into a PyGuitarPro Song for gpimport's native conversion.

Pinned source: helge17/tuxguitar 2c46e2a1, common/TuxGuitar-gtp/src/app/tuxguitar/io/gtp/GP{1,2}InputStream.java.
What TG reads and then discards, or normalizes, is reported in `warnings`, never dropped silently."""
import math

VERSIONS = {'FICHIER GUITARE PRO v1': (1, 0), 'FICHIER GUITARE PRO v1.01': (1, 1),
            'FICHIER GUITARE PRO v1.02': (1, 2), 'FICHIER GUITARE PRO v1.03': (1, 3),
            'FICHIER GUITARE PRO v1.04': (1, 4), 'FICHIER GUITAR PRO v2.20': (2, 0),
            'FICHIER GUITAR PRO v2.21': (2, 1)}
# TG's TRACK_CHANNELS: GM routes (primary, secondary) per track. Track 8's route 9
# makes it percussion (GTPSongNormalizer, after the reader).
ROUTES = ((0, 1), (2, 3), (4, 5), (6, 7), (8, 10), (11, 12), (13, 14), (9, 9))


def version_of(data):
    """TG's GTPFileFormatDetector: one length byte (clamped to 30), then 30 bytes."""
    if len(data) < 31:
        return None
    return data[1:1 + min(data[0], 30)].decode('utf-8', 'replace')


class _Stream:
    def __init__(self, data, encoding, warnings, strict):
        self.data, self.pos = data, 0
        self.encoding, self.warnings, self.strict = encoding, warnings, strict

    def read(self, n):
        if n < 0 or self.pos + n > len(self.data):
            raise ValueError('truncated Guitar Pro 1/2 file')
        self.pos += n
        return self.data[self.pos - n:self.pos]

    def u8(self):
        return self.read(1)[0]

    def i8(self):
        return int.from_bytes(self.read(1), 'little', signed=True)

    def i32(self):
        return int.from_bytes(self.read(4), 'little', signed=True)

    def string(self, size, length):  # GTPInputStream.readString(size, len)
        raw = self.read(size if size > 0 else length)
        raw = raw[:length if 0 <= length <= len(raw) else size]
        try:
            return raw.decode(self.encoding)
        except UnicodeDecodeError:
            if self.strict:
                raise
            self.warnings.append(f'GP1/2 text ending at byte {self.pos}: invalid {self.encoding} bytes '
                                 'were replaced; reimport with the correct text encoding to preserve them.')
            return raw.decode(self.encoding, 'replace')

    def string_byte(self, size=0):
        return self.string(size, self.u8())

    def string_sized(self):
        return self.string_byte(self.u8() - 1)


def read_gtp(data, warnings, encoding=None):
    """Return (a guitarpro.models.Song mirroring TG 2.1.0's GP1/GP2 reader, TG's raw balance per track);
    append losses to `warnings`."""
    from guitarpro import models as M
    from .gpimport import guitar_pro_encoding

    name = version_of(data)
    if name not in VERSIONS:
        raise ValueError('not a Guitar Pro 1/2 file')
    major, code = VERSIONS[name]
    s = _Stream(data, guitar_pro_encoding(encoding), warnings, encoding is not None)
    s.read(31)
    gp1 = major == 1
    tracks_n = 8 if not gp1 or code > 2 else 1

    def note_loss(what):
        warnings.append(f'GP{major} {what}')

    song = M.Song(versionTuple=(major, code, 0), tracks=[], measureHeaders=[])
    # Both pinned GP1/2 readers call this second information field author.
    song.title, song.music = s.string_sized(), s.string_sized()
    third = s.string_sized()
    if third:
        note_loss(f'third information string {third!r} is read and discarded by TuxGuitar 2.1.0')
    song.tempo = s.i32()
    swing = M.TripletFeel.eighth if s.i32() == 1 else M.TripletFeel.none
    key = 0
    if not gp1 or code > 2:
        key = s.i32()
    # TG stores this int raw as its key index: 0..7 sharps, 8..14 one..seven flats.
    if not 0 <= key <= 14:
        raise ValueError(f'GP{major} key signature {key} is outside TuxGuitar key indexes 0..14')
    keysig = M.KeySignature((key if key <= 7 else 7 - key, 0))

    for i in range(tracks_n):
        t = M.Track(song, number=i + 1, name='Track 1', fretCount=29, color=M.Color(255, 0, 0))
        t.channel = M.MidiChannel(channel=ROUTES[i][0], effectChannel=ROUTES[i][1])
        t.measures = []
        count = s.i32() if not gp1 or code > 1 else 6
        if not 1 <= count <= 25:
            raise ValueError(f'GP{major} track {i + 1}: {count} strings is outside 1..25')
        t.strings = [M.GuitarString(j + 1, s.i32()) for j in range(count)]
        song.tracks.append(t)
    measures = s.i32()
    raw_mix = []
    for i, t in enumerate(song.tracks):
        program = s.i32()
        if not 0 <= program <= 127:
            raise ValueError(f'GP{major} track {i + 1}: MIDI program {program} is outside 0..127')
        t.channel.instrument = program
        if gp1 and code <= 2:
            raw_mix.append((127, 64))  # TG keeps its channel defaults
            continue
        frets = s.i32()
        if frets != 29:
            note_loss(f'track {i + 1}: fret count {frets} is discarded by TuxGuitar 2.1.0 (it keeps 29)')
        t.name = s.string_sized()
        t.isSolo = s.u8() == 1
        volume, balance, chorus, reverb = (s.i32() for _ in range(4))
        t.channel.chorus, t.channel.reverb = chorus, reverb
        t.offset = s.i32()
        raw_mix.append((volume, balance))
    if not gp1 or code > 2:
        s.read(10)
    for i, (volume, balance) in enumerate(raw_mix):
        # TG uses these raw ints as MIDI 0..127; the conversion takes PyGuitarPro's
        # 0..128 scale (TG + 1). Exact pan is restored after conversion.
        if not 0 <= volume <= 127 or not 0 <= balance <= 127:
            raise ValueError(f'GP{major} track {i + 1}: volume/balance {volume}/{balance} is outside MIDI 0..127')
        t = song.tracks[i]
        t.channel.volume = (volume + 1) // 2 * 2
        t.channel.source_volume = volume
        t.channel.balance = (balance + 1) // 2 * 2
        if volume % 2 == 0:
            note_loss(f'track {i + 1}: MIDI volume {volume} maps to lane volume {(volume + 1) // 2} of 64, '
                      'while its exact source CC7 is retained for interchange')

    last = [None] * tracks_n  # TG's lastReadedStarts: previous beat per track
    generated = [0] * tracks_n
    dropped = {}

    def drop(what):
        dropped[what] = dropped.get(what, 0) + 1

    start = 960
    for number in range(1, measures + 1):
        header = M.MeasureHeader(number=number, start=start, keySignature=keysig, tripletFeel=swing)
        numerator, denominator = s.u8(), s.u8()
        if denominator not in (1, 2, 4, 8, 16, 32, 64):
            raise ValueError(f'GP{major} measure {number}: meter denominator {denominator} is unsupported')
        header.timeSignature = M.TimeSignature(numerator, M.Duration(denominator))
        s.read(6)
        beats = []
        for _ in range(tracks_n):
            s.read(2)
            n = s.u8()
            beats.append(0 if n > 127 else n)
            s.read(9)
        s.read(2)
        flags = s.u8()
        header.isRepeatOpen = bool(flags & 1)
        if flags & 2:
            header.repeatClose = s.u8()
        if flags & 4:
            value, existing = s.u8(), 0
            for h in song.measureHeaders:
                if h.isRepeatOpen:
                    existing = 0
                existing |= h.repeatAlternative
            header.repeatAlternative = ((1 << min(value, 8)) - 1) & ~existing
        song.measureHeaders.append(header)
        length = numerator * 3840 // denominator
        for ti, t in enumerate(song.tracks):
            measure = M.Measure(t, header)
            t.measures.append(measure)
            voice = measure.voices[0]
            at = start
            for _ in range(beats[ti]):
                at += _read_beat(M, s, major, code, t, voice, at, last, ti, drop, song)
            if at - start < length:
                generated[ti] += 1
        start += length
    if s.pos != len(data):
        note_loss(f'{len(data) - s.pos} trailing bytes after the last measure are ignored by TuxGuitar 2.1.0')
    # TG's slide target search (MidiSequenceParser.getNextNote, breakAtRest) stops
    # at its generated rests, which native import does not create.
    # ponytail: checks the next measure in file order, not each repeat jump target.
    for ti, t in enumerate(song.tracks):
        for mi, m in enumerate(t.measures):
            beats = m.voices[0].beats
            if not beats or not any(n.effect.slides for n in beats[-1].notes):
                continue
            gap = beats[-1].start + beats[-1].duration.time < m.start + m.length
            if gap or mi + 1 < len(t.measures) and not t.measures[mi + 1].voices[0].beats:
                raise ValueError(f'GP{major} track {ti + 1}, measure {mi + 1}: a slide reaches time TuxGuitar 2.1.0 '
                                 'fills with generated rests, so TG plays no slide; native import would')
    for ti, n in enumerate(generated):
        if n:
            note_loss(f'track {ti + 1}: TuxGuitar 2.1.0 fills the unwritten time of {n} measure(s) with generated '
                      'rests; native import leaves that time empty')
    if tracks_n == 8:
        # GTPSongNormalizer: GM route 9 -> percussion bank 128, program 0. TG then
        # plays key = capo + tuning + fret; native percussion has zero tuning/capo.
        t = song.tracks[7]
        t.isPercussionTrack = True
        if t.channel.instrument:
            note_loss(f'track 8: program {t.channel.instrument} is replaced by 0 when TuxGuitar 2.1.0 makes it percussion')
            t.channel.instrument = 0
        if t.offset or any(g.value for g in t.strings):
            if any(b.notes for m in t.measures for v in m.voices for b in v.beats):
                raise ValueError(f'GP{major} track 8 is percussion in TuxGuitar 2.1.0 and plays key = capo + tuning + '
                                 'fret; native percussion needs zero tuning and capo')
            note_loss(f'track 8 (percussion, no notes): source tuning {[g.value for g in t.strings]} and capo '
                      f'{t.offset} have no native percussion equivalent; zeroed')
            t.offset = 0
            for g in t.strings:
                g.value = 0
    for what, n in dropped.items():
        note_loss(f'{n} {what}')
    # Raw MIDI pan as TG reads it, except centre 64, which binds as 63 like GP3-5 imports (owner decision
    # 2026-10-20: GP3/4/5 export accepts it; CC10 differs from TuxGuitar by one step).
    return song, [63 if b == 64 else b for _, b in raw_mix]


def _read_beat(M, s, major, code, track, voice, at, last, ti, drop, song):
    s.i32()
    value = s.i8()
    if not -2 <= value <= 4:
        raise ValueError(f'GP{major}: written duration byte {value} is outside whole..64th')
    duration = M.Duration(1 << (value + 2))
    flags = s.u8()
    mix = None
    if major == 2:
        flags2 = s.u8()
        if flags2 & 2:
            mix = _read_mix(M, s, drop)
        if flags2 & 1:
            s.read(2)
            drop('GP2 stroke type/duration bytes discarded by TuxGuitar 2.1.0')
    duration.isDotted = bool(flags & 0x10)
    if flags & 0x20:
        duration.tuplet = M.Tuplet(3, 2)
        s.read(1)
    beat = M.Beat(voice, start=at, duration=duration, status=M.BeatStatus.normal)
    if mix is not None:
        beat.effect.mixTableChange = mix
    # TG keeps ONE note effect per beat: the beat byte sets it, each note's
    # effect byte then changes it in place, and every note gets a copy.
    state = dict(vibrato=False, hammer=False, slide=False, bend=None, harmonic=None)
    beat_flags = 0
    if flags & 4:
        beat_flags = s.u8()
        state['vibrato'] = beat_flags in (1, 2)
        if beat_flags == 3:
            state['bend'] = _read_bend(s)
        elif beat_flags in (8, 9):
            state['harmonic'] = 'natural' if beat_flags == 8 else 'artificial'
    if flags & 2:
        _read_chord(M, s, major, code, track, beat, drop)
    if flags & 1:
        beat.text = s.string_byte(0)
    if flags & 0x40:
        if beat_flags:
            drop('beat effects on tied beats (TuxGuitar 2.1.0 copies the tied notes without them)')
        previous = last[ti]
        if previous is not None and previous.start < at:
            for p in previous.notes:
                beat.notes.append(M.Note(beat, value=p.value, string=p.string, velocity=p.velocity,
                                         type=M.NoteType.tie))
    elif not flags & 8:
        strings, effects = s.u8(), s.u8()
        graces = s.u8() if major == 2 else 0
        for i in range(5, -1, -1):
            if strings & (1 << i):
                fret = s.u8()
                velocity = 95  # TGVelocities.DEFAULT
                if major == 2:
                    velocity = 16 * s.u8() - 1
                if effects & (1 << i):
                    # TGNoteEffect's setters: a true hammer, slide or bend clears the others.
                    kind = s.u8()
                    state['hammer'] = kind in (1, 2)
                    if state['hammer']:
                        state['bend'], state['slide'] = None, False
                    state['slide'] = kind in (3, 4)
                    if state['slide']:
                        state['bend'], state['hammer'] = None, False
                    if kind in (5, 6):
                        state['bend'], state['slide'], state['hammer'] = _read_bend(s), False, False
                number = len(track.strings) - i
                if number < 1:
                    raise ValueError(f'GP{major}: string bit {i} maps to string {number} on a '
                                     f'{len(track.strings)}-string track')
                dead = fret >= 100  # setDeadNote on the copy clears its bend, slide and hammer
                note = M.Note(beat, value=0 if dead else fret, string=number, velocity=velocity,
                              type=M.NoteType.dead if dead else M.NoteType.normal)
                e = note.effect
                e.vibrato, e.hammer = state['vibrato'], state['hammer'] and not dead
                if state['slide'] and not dead:
                    e.slides = [M.SlideType.shiftSlideTo]
                if state['bend'] is not None and not dead:
                    e.bend = M.BendEffect(type=M.BendType.bend, value=0,
                                          points=[M.BendPoint(p, v, False) for p, v in state['bend']])
                if state['harmonic']:
                    e.harmonic = M.NaturalHarmonic() if state['harmonic'] == 'natural' else M.ArtificialHarmonic()
                beat.notes.append(note)
            if graces & (1 << i):
                s.read(3)
                drop('GP2 grace notes discarded by TuxGuitar 2.1.0')
        if beat.notes:
            beat.effect.fadeIn = beat_flags == 4
            beat.effect.slapEffect = M.SlapEffect({5: 1, 6: 2, 7: 3}.get(beat_flags, 0))
    if not beat.notes:
        beat.status = M.BeatStatus.rest
        if beat_flags and not flags & 0x40:
            drop('beat effects on rests (TuxGuitar 2.1.0 has no note to carry them)')
    voice.beats.append(beat)
    last[ti] = beat
    return duration.time


def _read_bend(s):
    s.read(6)
    value = max(s.u8() / 8 - 26, 1)
    s.read(1)
    v = _round(value)  # TGEffectBend.SEMITONE_LENGTH = 1
    return [(0, 0), (6, v), (12, v)]


def _round(x):  # Java Math.round (half up)
    return math.floor(x + 0.5)


def _read_chord(M, s, major, code, track, beat, drop):
    if major == 1 and code <= 3:
        s.string_sized()
        drop('chord names discarded by TuxGuitar 2.1.0 (GP1 before v1.04 has no diagram)')
        return
    name = s.string_byte(0)
    s.read(1)
    if s.i32() < 12:
        s.read(32)
    first = s.i32()
    frets = [-1] * len(track.strings)
    if first != 0:
        for i in range(6):
            fret = s.i32()
            if i < len(frets):
                frets[i] = fret
    if not any(f >= 0 for f in frets):
        drop('name-only chord diagrams dropped by TuxGuitar 2.1.0')
        return
    chord = M.Chord(len(track.strings))
    chord.name, chord.firstFret, chord.strings = name, first, frets
    beat.effect.chord = chord


def _read_mix(M, s, drop):
    flags = s.u8()
    mix = None
    if flags & 0x20:
        tempo = s.i32()
        if s.u8():
            drop('GP2 tempo transition bytes discarded by TuxGuitar 2.1.0')
        mix = M.MixTableChange(tempo=M.MixTableItem(tempo, duration=0))
    for bit, what in ((0x10, 'reverb'), (0x08, 'chorus'), (0x04, 'balance'), (0x02, 'volume')):
        if flags & bit:
            s.read(2)
            drop(f'GP2 mix-table {what} changes discarded by TuxGuitar 2.1.0')
    if flags & 1:
        s.read(1)
        drop('GP2 mix-table instrument changes discarded by TuxGuitar 2.1.0')
    return mix
