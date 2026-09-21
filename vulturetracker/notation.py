"""Text notation for notes and pattern cells (OpenMPT clipboard style, IT semantics)."""
import re

from .model import Cell, NOTE_CUT, NOTE_FADE, NOTE_OFF

NOTE_NAMES = ["C-", "C#", "D-", "D#", "E-", "F-", "F#", "G-", "G#", "A-", "A#", "B-"]
SPECIAL_NOTES = {"===": NOTE_OFF, "^^^": NOTE_CUT, "~~~": NOTE_FADE}
SPECIAL_TEXT = {v: k for k, v in SPECIAL_NOTES.items()}

# Volume column: letter -> (base byte, max value). Values are decimal, as in OpenMPT.
VOLCMDS = {
    "v": (0, 64),     # set volume
    "p": (128, 64),   # set panning
    "a": (65, 9),     # fine volume slide up
    "b": (75, 9),     # fine volume slide down
    "c": (85, 9),     # volume slide up
    "d": (95, 9),     # volume slide down
    "e": (105, 9),    # pitch slide down
    "f": (115, 9),    # pitch slide up
    "g": (193, 9),    # tone portamento
    "h": (203, 9),    # vibrato depth
}

_NOTE_RE = re.compile(r"^([A-G])([-#])([0-9])$")
_INS_RE = re.compile(r"^[0-9]{2}$")
_VOL_RE = re.compile(r"^([a-z])([0-9]{2})$")
_FX_RE = re.compile(r"^([A-Z])([0-9A-F]{2})$")


class NotationError(ValueError):
    pass


def parse_note(text: str) -> int:
    """'C-5' -> 60, 'C#5' -> 61. Also ===, ^^^, ~~~."""
    if text in SPECIAL_NOTES:
        return SPECIAL_NOTES[text]
    m = _NOTE_RE.match(text)
    if not m:
        hint = ""
        if re.match(r"^[a-g][-#]\d$", text):
            hint = " (note letters are upper case)"
        elif re.match(r"^[A-G]b\d$", text):
            hint = " (use sharps: e.g. Db5 is C#5)"
        elif re.match(r"^[A-G]\d$", text):
            hint = f" (write {text[0]}-{text[1]})"
        raise NotationError(f"bad note '{text}'{hint}; expected e.g. C-5, F#3, === (off), ^^^ (cut), ~~~ (fade)")
    name = m.group(1) + m.group(2)
    if name not in NOTE_NAMES:
        raise NotationError(f"bad note '{text}': {name} does not exist (no E# or B#)")
    return NOTE_NAMES.index(name) + 12 * int(m.group(3))


def format_note(note: int | None) -> str:
    if note is None:
        return "..."
    if note in SPECIAL_TEXT:
        return SPECIAL_TEXT[note]
    if 0 <= note < 120:
        return f"{NOTE_NAMES[note % 12]}{note // 12}"
    return "~~~"  # IT treats any other value as note fade


def parse_volcmd(text: str) -> int:
    m = _VOL_RE.match(text)
    if not m or m.group(1) not in VOLCMDS:
        raise NotationError(f"bad volume column '{text}'; expected one of {', '.join(k + 'NN' for k in VOLCMDS)}")
    base, top = VOLCMDS[m.group(1)]
    value = int(m.group(2))
    if value > top:
        raise NotationError(f"volume column '{text}' out of range: {m.group(1)} takes 00..{top:02d}")
    return base + value


def format_volcmd(byte: int | None) -> str:
    if byte is None:
        return "..."
    for letter, (base, top) in VOLCMDS.items():
        if base <= byte <= base + top:
            return f"{letter}{byte - base:02d}"
    raise NotationError(f"volume column byte {byte} has no IT meaning")


def parse_cell(text: str) -> Cell:
    """Parse one channel cell. Fields are recognised by shape and must appear in the order
    note, instrument, volume, effect; any may be omitted. '...' and '..' are empty placeholders."""
    cell = Cell()
    stage = 0  # next field allowed: 0 note, 1 instrument, 2 volume, 3 effect
    for tok in text.split():
        if tok in ("...", ".."):
            continue
        if re.match(r"^[A-G]\d$", tok):
            raise NotationError(f"'{tok}' is ambiguous: write a note as {tok[0]}-{tok[1]} or an effect with two hex digits ({tok[0]}0{tok[1]})")
        if tok in SPECIAL_NOTES or _NOTE_RE.match(tok) or re.match(r"^[a-zA-Z][-#b]\d$", tok) or re.match(r"^[a-g]\d$", tok):
            field, order = "note", 0
        elif _INS_RE.match(tok):
            field, order = "instrument", 1
        elif _VOL_RE.match(tok):
            field, order = "volume", 2
        elif _FX_RE.match(tok):
            field, order = "effect", 3
        elif re.match(r"^[a-z][0-9]$", tok):
            raise NotationError(f"volume column '{tok}' needs two digits: {tok[0]}0{tok[1]}")
        elif re.match(r"^[a-z][0-9A-Fa-f]{2}$", tok) and tok[0] not in VOLCMDS:
            raise NotationError(f"'{tok}': effect letters are upper case (A-Z) and volume commands are one of "
                                f"{' '.join(VOLCMDS)}")
        elif re.match(r"^[A-Z][0-9A-Fa-f]{2}$", tok):
            raise NotationError(f"bad effect '{tok}': parameter must be two upper-case hex digits")
        elif re.match(r"^[0-9][0-9A-F]{2}$", tok):
            raise NotationError(f"bad effect '{tok}': IT effects are letters A-Z, not digits (MOD/XM style)")
        else:
            raise NotationError(f"unrecognised token '{tok}'; a cell is 'note ins vol effect', e.g. C-5 01 v64 A06")
        if order == stage - 1:
            raise NotationError(f"duplicate {field} '{tok}'")
        if order < stage:
            raise NotationError(f"'{tok}' ({field}) is out of order; fields go note, instrument, volume, effect")
        stage = order + 1
        if field == "note":
            cell.note = parse_note(tok)
        elif field == "instrument":
            cell.instrument = int(tok)
            if cell.instrument == 0:
                raise NotationError("instrument 00 does not exist; use '..' for no instrument")
        elif field == "volume":
            cell.volcmd = parse_volcmd(tok)
        else:
            cell.effect = ord(tok[0]) - ord("A") + 1
            cell.param = int(tok[1:], 16)
    return cell


def format_cell(cell: Cell) -> str:
    ins = f"{cell.instrument:02d}" if cell.instrument else ".."
    fx = f"{chr(ord('A') + cell.effect - 1)}{cell.param:02X}" if cell.effect else "..."
    return f"{format_note(cell.note)} {ins} {format_volcmd(cell.volcmd)} {fx}"
