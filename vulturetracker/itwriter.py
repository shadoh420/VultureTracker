"""Module model -> Impulse Tracker (.it) bytes. Layout follows ITTECH.TXT (IT 2.14)."""
import struct
import sys
from array import array

from .model import Envelope, Loop, Module, ORDER_END

HEADER_SIZE = 0xC0
INSTRUMENT_SIZE = 554
SAMPLE_HEADER_SIZE = 80


def _name(text, size):
    """Null-terminated, zero-padded ASCII field."""
    raw = text.encode("ascii", "replace")[: size - 1]
    return raw.ljust(size, b"\0")


def _envelope(env: Envelope | None, offset: int) -> bytes:
    """82-byte IT envelope; `offset` is 0 for volume, 32 for pan/pitch (values stored signed)."""
    if env is None or not env.nodes:
        # IT always stores two nodes, even for an unused envelope.
        env = Envelope([(0, 64 - offset), (10, 64 - offset)] if offset == 0 else [(0, 0), (10, 0)], enabled=False)
    flags = (1 if env.enabled else 0) | (2 if env.loop else 0) | (4 if env.sustain else 0)         | (8 if env.carry else 0) | (0x80 if env.filter else 0)
    lpb, lpe = env.loop or (0, 0)
    slb, sle = env.sustain or (0, 0)
    out = bytearray(struct.pack("<6B", flags, len(env.nodes), lpb, lpe, slb, sle))
    for tick, value in env.nodes:
        out += struct.pack("<bH", value, tick)
    out += bytes(75 - 3 * len(env.nodes))
    out += b"\0"  # reserved
    return bytes(out)


def _instrument(ins) -> bytes:
    out = bytearray(b"IMPI" + _name(ins.filename, 12))
    ifc = (ins.filter_cutoff | 0x80) if ins.filter_cutoff is not None else 0
    ifr = (ins.filter_resonance | 0x80) if ins.filter_resonance is not None else 0
    dfp = ins.pan if ins.pan is not None else (32 | 0x80)
    nos = len({s for _, s in ins.keymap if s})
    out += struct.pack("<BBBBHbBBBBBHBB", 0, ins.nna, ins.dct, ins.dca, ins.fadeout,
                       ins.pitch_pan_separation, ins.pitch_pan_center, ins.global_volume, dfp,
                       ins.random_volume, ins.random_pan, 0x0214, nos, 0)
    out += _name(ins.name, 26)
    out += struct.pack("<BBBBH", ifc, ifr, 0, 0xFF, 0xFFFF)  # no MIDI channel/program/bank
    for note, smp in ins.keymap:
        out += struct.pack("<BB", note, smp)
    out += _envelope(ins.volume_envelope, 0)
    out += _envelope(ins.panning_envelope, 32)
    out += _envelope(ins.pitch_envelope, 32)
    out += bytes(4)
    assert len(out) == INSTRUMENT_SIZE
    return bytes(out)


def _sample_header(smp, data_offset) -> bytes:
    has_data = smp.length > 0
    flags = 0
    if has_data:
        flags = 1 | (2 if smp.bits == 16 else 0) | (4 if len(smp.data) == 2 else 0)
        if smp.loop:
            flags |= 0x10 | (0x40 if smp.loop.pingpong else 0)
        if smp.sustain_loop:
            flags |= 0x20 | (0x80 if smp.sustain_loop.pingpong else 0)
    lp = smp.loop or Loop(0, 0)
    sl = smp.sustain_loop or Loop(0, 0)
    dfp = (smp.pan | 0x80) if smp.pan is not None else 32
    out = b"IMPS" + _name(smp.filename, 12)
    out += struct.pack("<BBBB", 0, smp.global_volume, flags, smp.volume)
    out += _name(smp.name, 26)
    out += struct.pack("<BB", 1, dfp)  # Cvt bit 0: signed samples
    out += struct.pack("<IIIIIIIBBBB", smp.length, lp.start, lp.end, smp.c5_speed, sl.start, sl.end,
                       data_offset if has_data else 0,
                       smp.vibrato_speed, smp.vibrato_depth, smp.vibrato_rate, smp.vibrato_type)
    assert len(out) == SAMPLE_HEADER_SIZE
    return out


def _sample_data(smp) -> bytes:
    # Stereo samples are stored as the full left channel followed by the full right channel.
    out = bytearray()
    for chan in smp.data:
        if smp.bits == 16:
            a = array("h", chan)
            if sys.byteorder == "big":
                a.byteswap()
            out += a.tobytes()
        else:
            out += array("b", chan).tobytes()
    return bytes(out)


def _pattern(pat, num_channels) -> bytes:
    # ponytail: always writes a full mask per cell (no last-value compression); files are a bit larger but valid.
    packed = bytearray()
    for row in pat.rows:
        for ch, cell in enumerate(row[:num_channels]):
            mask = 0
            data = bytearray()
            if cell.note is not None:
                mask |= 1
                data.append(cell.note)
            if cell.instrument:
                mask |= 2
                data.append(cell.instrument)
            if cell.volcmd is not None:
                mask |= 4
                data.append(cell.volcmd)
            if cell.effect or cell.param:
                mask |= 8
                data += bytes((cell.effect, cell.param))
            if mask:
                packed += bytes(((ch + 1) | 0x80, mask)) + data
        packed.append(0)
    return struct.pack("<HH4x", len(packed), len(pat.rows)) + packed


def write_it(mod: Module) -> bytes:
    orders = list(mod.orders)
    if not orders or orders[-1] != ORDER_END:
        orders.append(ORDER_END)
    if len(orders) % 2:  # IT pads the order list to an even length
        orders.append(ORDER_END)
    instruments = mod.instruments or []
    ins_blobs = [_instrument(i) for i in instruments]
    pat_blobs = [_pattern(p, len(mod.channels)) for p in mod.patterns]
    message = mod.message.replace("\r\n", "\n").replace("\n", "\r").encode("ascii", "replace") + b"\0" if mod.message else b""

    # Lay out the file: header, pointer tables, message, instruments, sample headers, patterns, sample data.
    pos = HEADER_SIZE + len(orders) + 4 * (len(instruments) + len(mod.samples) + len(mod.patterns))
    msg_offset = pos if message else 0
    pos += len(message)
    ins_offsets = []
    for blob in ins_blobs:
        ins_offsets.append(pos)
        pos += len(blob)
    smp_offsets = []
    for _ in mod.samples:
        smp_offsets.append(pos)
        pos += SAMPLE_HEADER_SIZE
    pat_offsets = []
    for blob in pat_blobs:
        pat_offsets.append(pos)
        pos += len(blob)
    smp_datas = [_sample_data(s) for s in mod.samples]
    data_offsets = []
    for blob in smp_datas:
        data_offsets.append(pos)
        pos += len(blob)

    flags = 1 | (4 if mod.instruments is not None else 0) | (8 if mod.linear_slides else 0) \
        | (0x10 if mod.old_effects else 0) | (0x20 if mod.compatible_gxx else 0)
    special = 1 if message else 0
    chnpan = bytearray([32 | 0x80] * 64)
    chnvol = bytearray([64] * 64)
    for i, ch in enumerate(mod.channels):
        chnpan[i] = ch.pan | (0x80 if ch.muted else 0)
        chnvol[i] = ch.volume

    out = bytearray(b"IMPM" + _name(mod.title, 26))
    out += struct.pack("<BB", mod.row_highlight[0], mod.row_highlight[1])
    out += struct.pack("<HHHHHHHH", len(orders), len(instruments), len(mod.samples), len(mod.patterns),
                       0x0214, 0x0214, flags, special)
    out += struct.pack("<BBBBBBHII", mod.global_volume, mod.mix_volume, mod.speed, mod.tempo,
                       mod.separation, 0, len(message), msg_offset, 0)
    out += chnpan + chnvol
    assert len(out) == HEADER_SIZE
    out += bytes(orders)
    for off in ins_offsets + smp_offsets + pat_offsets:
        out += struct.pack("<I", off)
    out += message
    for blob in ins_blobs:
        out += blob
    for smp, off in zip(mod.samples, data_offsets):
        out += _sample_header(smp, off)
    for blob in pat_blobs:
        out += blob
    for blob in smp_datas:
        out += blob
    assert len(out) == pos
    return bytes(out)
