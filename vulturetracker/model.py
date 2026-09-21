"""In-memory module model. Values are stored in IT's own units so the writer
and reader are straight byte mappings; text notation lives in notation.py."""
from dataclasses import dataclass, field

NOTE_FADE, NOTE_CUT, NOTE_OFF = 246, 254, 255
ORDER_SKIP, ORDER_END = 254, 255
MAX_CHANNELS = 64


@dataclass
class Cell:
    note: int | None = None        # 0..119 (C-0..B-9), NOTE_OFF/CUT/FADE
    instrument: int = 0            # 0 = none, else 1..99
    volcmd: int | None = None      # raw IT volume-column byte
    effect: int = 0                # 0 = none, 1 = A ... 26 = Z
    param: int = 0

    def is_empty(self):
        return self.note is None and not self.instrument and self.volcmd is None and not self.effect and not self.param


@dataclass
class Pattern:
    name: str
    rows: list[list[Cell]]         # rows[row][channel]


@dataclass
class Loop:
    start: int
    end: int                       # sample index AFTER the last looped frame
    pingpong: bool = False


@dataclass
class Sample:
    name: str = ""
    data: list[list[int]] = field(default_factory=list)   # one list per channel (1 or 2), signed ints
    bits: int = 16                 # 8 or 16
    c5_speed: int = 8363
    volume: int = 64               # 0..64
    global_volume: int = 64        # 0..64
    pan: int | None = None         # 0..64, None = don't override
    loop: Loop | None = None
    sustain_loop: Loop | None = None
    vibrato_type: int = 0          # 0 sine, 1 ramp down, 2 square, 3 random
    vibrato_speed: int = 0         # 0..64
    vibrato_depth: int = 0         # 0..64
    vibrato_rate: int = 0          # 0..255 (sweep)
    filename: str = ""

    @property
    def length(self):
        return len(self.data[0]) if self.data else 0


@dataclass
class Envelope:
    nodes: list[tuple[int, int]]   # (tick, value); value 0..64 for volume, -32..32 for pan/pitch
    enabled: bool = True
    loop: tuple[int, int] | None = None      # node indices
    sustain: tuple[int, int] | None = None
    filter: bool = False           # pitch envelope only: act as filter envelope
    carry: bool = False            # keep envelope position across new notes (OpenMPT extension flag)


@dataclass
class Instrument:
    name: str = ""
    keymap: list[tuple[int, int]] = field(default_factory=lambda: [(n, 0) for n in range(120)])  # [(note, sample)] * 120
    fadeout: int = 0               # 0..256
    nna: int = 0                   # 0 cut, 1 continue, 2 off, 3 fade
    dct: int = 0                   # 0 off, 1 note, 2 sample, 3 instrument
    dca: int = 0                   # 0 cut, 1 off, 2 fade
    global_volume: int = 128       # 0..128
    pan: int | None = None         # 0..64, None = don't override
    pitch_pan_separation: int = 0  # -32..32
    pitch_pan_center: int = 60     # note 0..119
    random_volume: int = 0         # 0..100 %
    random_pan: int = 0            # 0..64
    filter_cutoff: int | None = None     # 0..127
    filter_resonance: int | None = None  # 0..127
    volume_envelope: Envelope | None = None
    panning_envelope: Envelope | None = None
    pitch_envelope: Envelope | None = None
    filename: str = ""


@dataclass
class Channel:
    name: str = ""
    pan: int = 32                  # 0..64, 100 = surround
    volume: int = 64               # 0..64
    muted: bool = False


@dataclass
class Module:
    title: str = ""
    speed: int = 6
    tempo: int = 125
    global_volume: int = 128       # 0..128
    mix_volume: int = 48           # 0..128
    separation: int = 128          # 0..128
    linear_slides: bool = True
    old_effects: bool = False
    compatible_gxx: bool = False
    channels: list[Channel] = field(default_factory=list)
    samples: list[Sample] = field(default_factory=list)            # index 0 = sample 01
    instruments: list[Instrument] | None = None                    # None = sample mode
    patterns: list[Pattern] = field(default_factory=list)
    orders: list[int] = field(default_factory=list)
    message: str = ""
    row_highlight: tuple[int, int] = (4, 16)
