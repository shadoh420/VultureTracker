"""Records a scripted tour of the real VultureTracker app window and assembles a demo video with Vantage as the
soundtrack: title card, a YAML card, a CLI card, the captured tour with captions, and a credits card.
Output: scratch/demo-video/vantage-demo.mp4 (1920x1080 H.264 + AAC). Needs pywebview, pywin32, Pillow and
imageio-ffmpeg (pip), a 1920x1080 primary screen at 100% scaling, and a checkout with the demo drums rendered.
Run: python tools/demo_video.py   (or --assemble-only to re-encode the last recording) Everything shown or heard is the project's own
or licensed (see THIRD_PARTY.md); no third-party audio or footage is used."""
import json
import os
import re
import subprocess
import sys
import threading
import time
from http.server import ThreadingHTTPServer
from pathlib import Path

os.environ["WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS"] = "--autoplay-policy=no-user-gesture-required"
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import imageio_ffmpeg  # noqa: E402
import webview  # noqa: E402
import win32gui  # noqa: E402
from PIL import Image, ImageDraw, ImageFont, ImageGrab  # noqa: E402
from vulturetracker import gui  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "scratch" / "demo-video"
FRAMES = OUT / "frames"
SONG = ROOT / "demo4" / "vantage.yaml"
WAV = ROOT / "demo4" / "vantage.wav"
W, H = 1600, 900                       # captured client area; scaled to 1920x1080 at assembly
FPS = 12
FONT, FONTB, MONO = "C:/Windows/Fonts/segoeui.ttf", "C:/Windows/Fonts/segoeuib.ttf", "C:/Windows/Fonts/consola.ttf"
BG, PANEL, INK, DIM, ACC = (10, 12, 13), (20, 23, 26), (214, 220, 223), (121, 132, 138), (126, 231, 135)


def font(path, size):
    return ImageFont.truetype(path, size)


# ---------------------------------------------------------------- cards

def card(bg=BG):
    return Image.new("RGB", (W, H), bg)


def text(d, xy, s, f, fill=INK):
    d.text(xy, s, font=f, fill=fill)


WM = [("Video made by Claude, Anthropic's AI assistant", True, INK),
      ("Music: \u201cVantage\u201d, an original track inspired by", False, INK),
      ("\u201cForegone Destruction\u201d by Michiel van den Bos", False, INK),
      ("Unreal Tournament (1999) \u00a9 Epic Games \u00b7 no audio or melody from it is used", False, DIM)]


def stamp(im):
    """The persistent top-right watermark: who made the video and what the music is inspired by."""
    im = im.convert("RGBA")
    fb, fr = font(FONTB, 18), font(FONT, 17)
    d0 = ImageDraw.Draw(im)
    widths = [d0.textlength(t, font=fb if b else fr) for t, b, _ in WM]
    bw, bh = int(max(widths)) + 36, 22 * len(WM) + 16
    box = Image.new("RGBA", (bw, bh), (8, 10, 11, 215))
    d = ImageDraw.Draw(box)
    for i, (t, b, col) in enumerate(WM):
        f = fb if b else fr
        d.text((bw - 18 - d.textlength(t, font=f), 8 + i * 22), t, font=f, fill=col)
    im.alpha_composite(box, (W - bw - 14, 10))
    return im.convert("RGB")


def card_music():
    im = card()
    d = ImageDraw.Draw(im)
    text(d, (100, 110), "About the music", font(FONTB, 54), INK)
    lines = [("\u201cVantage\u201d is an original composition, written for this demo as a study in the style of", INK),
             ("\u201cForegone Destruction\u201d by Michiel van den Bos, from the Unreal Tournament (1999) soundtrack,", ACC),
             ("\u00a9 Epic Games, Inc. It takes that track's tempo, grid and layer plan as its model.", INK),
             ("", INK),
             ("It contains no audio, no melody and no sample data from it: every sound is the project's own", INK),
             ("render or a licensed recording, credited at the end of this video and in the repository.", INK),
             ("", INK),
             ("Unreal Tournament is a trademark of Epic Games, Inc. This project is not affiliated with,", DIM),
             ("sponsored or endorsed by Epic Games or the composer.", DIM),
             ("PROVENANCE.md in the repository lists exactly what was taken from the reference and what was changed.", DIM)]
    for i, (line, col) in enumerate(lines):
        text(d, (102, 210 + i * 46), line, font(FONT, 30), col)
    return im


def card_title():
    im = card()
    d = ImageDraw.Draw(im)
    icon = Image.open(ROOT / "assets" / "vulturetracker.png").convert("RGBA").resize((360, 360), Image.LANCZOS)
    im.paste(icon, (200, 250), icon)
    text(d, (620, 300), "VultureTracker", font(FONTB, 96), INK)
    text(d, (626, 430), "Tracker music as text.", font(FONT, 46), ACC)
    text(d, (628, 510), "A song is a YAML file. It compiles to an Impulse Tracker module,", font(FONT, 30), DIM)
    text(d, (628, 552), "renders to WAV, and an app lets you choose the sounds in context.", font(FONT, 30), DIM)
    text(d, (628, 640), "A demo video made by Claude, Anthropic's AI assistant, with the project's author.", font(FONT, 26), ACC)
    return im


def card_yaml():
    src = SONG.read_text(encoding="utf-8")
    rows = re.findall(r"^      (\d\d): (.*)$", src[src.index("  g1:"):], re.M)[:6]
    lines = ["module:", "  title: Vantage", "  tempo: 140", "  speed: 5", "  channels:",
             "    - {name: Kick,  pan: 32, volume: 26}", "    - {name: Snare, pan: 32, volume: 40}", "    ...",
             "samples:", "  7: {file: ../samples/demo4/riff.wav, name: Sine riff, base_note: E-5, loop: from_wav}",
             "  8: {file: ../samples/demo4/bed1.wav, name: Minor bed, base_note: C-5, loop: from_wav}", "  ...",
             "patterns:", "  g1:", "    rows: 64", "    data: |"]
    lines += [f"      {r}: " + " | ".join(cells.split(" | ")[:5]) + " | ..." for r, cells in rows]
    lines += ["      ...", "orders: [i1, i2, i3, i4, b1, b2, b3, b4, g1, g2, g3, ...]"]
    im = card()
    d = ImageDraw.Draw(im)
    text(d, (100, 70), "A song is a YAML file", font(FONTB, 54), INK)
    text(d, (102, 140), "every note, sample, envelope and effect is plain text, so people and AIs edit it the same way",
         font(FONT, 26), DIM)
    d.rectangle((100, 200, W - 100, 830), fill=PANEL)
    mono = font(MONO, 22)
    for i, line in enumerate(lines):
        col = ACC if line.rstrip().endswith(":") and not line.startswith("      ") else INK
        text(d, (124, 218 + i * 28), line, mono, col)
    return im


def card_cli():
    r = subprocess.run([sys.executable, "-m", "vulturetracker", "build", "demo4/vantage.yaml", "--render", "demo4/vantage.wav"],
                       cwd=ROOT, capture_output=True, text=True, timeout=600)
    out = [l for l in r.stdout.splitlines() if l.strip()][:12]
    im = card()
    d = ImageDraw.Draw(im)
    text(d, (100, 70), "Build, verify, render", font(FONTB, 54), INK)
    text(d, (102, 140), "the compiler writes the .it, then libopenmpt loads it back and confirms what it sees",
         font(FONT, 26), DIM)
    d.rectangle((100, 200, W - 100, 700), fill=PANEL)
    mono = font(MONO, 24)
    text(d, (124, 222), "$ python -m vulturetracker build demo4/vantage.yaml --render demo4/vantage.wav", mono, ACC)
    maxw = (W - 100) - 124 - 24                      # keep every line inside the panel, eliding the long lists
    for i, line in enumerate(out):
        s = line
        while d.textlength(s, font=mono) > maxw:
            s = s[:-2].rstrip() + "…"
        text(d, (124, 266 + i * 32), s, mono, INK)
    text(d, (102, 740), "Also: check, render, info, import (an existing .it back into YAML), synth and audition (samples from",
         font(FONT, 24), DIM)
    text(d, (102, 774), "free synths and CC0 recordings), and tryout from the command line.", font(FONT, 24), DIM)
    return im


def card_end():
    im = card()
    d = ImageDraw.Draw(im)
    icon = Image.open(ROOT / "assets" / "vulturetracker.png").convert("RGBA").resize((220, 220), Image.LANCZOS)
    im.paste(icon, (110, 90), icon)
    text(d, (370, 120), "VultureTracker", font(FONTB, 72), INK)
    text(d, (374, 215), "github.com/shadoh420/VultureTracker", font(FONT, 40), ACC)
    text(d, (374, 275), "MIT licensed. Free Windows download: vulturetracker.exe", font(FONT, 28), DIM)
    text(d, (110, 400), "Music: \"Vantage\", made with VultureTracker", font(FONTB, 32), INK)
    lines = [("An original track inspired by \u201cForegone Destruction\u201d by Michiel van den Bos, from the Unreal Tournament (1999)", ACC),
             ("soundtrack, \u00a9 Epic Games, Inc. No audio, melody or sample data from it is used. Not affiliated with Epic Games.", ACC),
             ("Drums: hits from MusicRadar's royalty-free drum-machine pack; break played by Big Rusty Drums", DIM),
             ("(Karoryfer Samples, CC0); cymbal swell and gong from VSCO 2 (Versilian Studios, CC0).", DIM),
             ("Synths: renders of Surge XT factory patches, plus additive sounds made by the project's own scripts.", DIM),
             ("Module playback and rendering: libopenmpt (OpenMPT project, BSD-3-Clause).", DIM),
             ("Full credits, license texts and provenance: THIRD_PARTY.md and PROVENANCE.md in the repository.", DIM),
             ("", DIM),
             ("Video made by Claude, Anthropic's AI assistant, with the project's author. September 2026.", INK)]
    for i, (line, col) in enumerate(lines):
        text(d, (110, 445 + i * 38), line, font(FONT, 25), col)
    return im


# ---------------------------------------------------------------- tour capture

class Recorder(threading.Thread):
    def __init__(self, bbox):
        super().__init__(daemon=True)
        self.bbox, self.cap, self.sub, self.stop, self.frames = bbox, "", "", False, []
        self.fcap, self.fsub = font(FONTB, 34), font(FONT, 26)

    def caption(self, cap, sub=""):
        self.cap, self.sub = cap, sub

    def run(self):
        n, t0 = 0, time.perf_counter()
        while not self.stop:
            due = t0 + n / FPS
            now = time.perf_counter()
            if now < due:
                time.sleep(due - now)
            im = ImageGrab.grab(bbox=self.bbox, all_screens=True).convert("RGBA")
            if self.cap:
                bar = Image.new("RGBA", (W, 96), (8, 10, 11, 205))
                d = ImageDraw.Draw(bar)
                d.text((28, 12), self.cap, font=self.fcap, fill=INK)
                d.text((30, 56), self.sub, font=self.fsub, fill=ACC)
                im.alpha_composite(bar, (0, H - 96))
            im.convert("RGB").save(FRAMES / f"f{n:05d}.jpg", quality=88)
            self.frames.append((n, time.perf_counter() - t0))
            n += 1


def js(w, code):
    return w.evaluate_js(code)


def wait(w, code, timeout=30):
    t0 = time.time()
    while time.time() - t0 < timeout:
        if js(w, code):
            return True
        time.sleep(0.2)
    return False


def tour(w):
    rec = None
    try:
        wait(w, "S&&S.song&&S.song.facts", 20)
        time.sleep(1.0)
        hwnd = win32gui.FindWindow(None, "VultureTracker")
        _, _, cw, ch = win32gui.GetClientRect(hwnd)
        sx, sy = win32gui.ClientToScreen(hwnd, (0, 0))
        print("client", cw, ch, "at", sx, sy, flush=True)
        rec = Recorder((sx, sy, sx + cw, sy + ch))
        js(w, "renderStart()")
        time.sleep(0.6)
        rec.start()
        rec.caption("The start screen: recent songs and the bundled demos")
        time.sleep(4.0)
        js(w, f"openSong({json.dumps(str(SONG))})")
        wait(w, "S&&S.song&&S.song.facts&&document.querySelectorAll('.cand').length>0", 20)
        rec.caption("Open a song: the module is compiled from the YAML, the tryout screen appears",
                    "left: the sample slot in question and the section to loop; middle: candidate WAVs; right: the chosen one")
        time.sleep(5.0)
        wait(w, "S.candidates.every(c=>c.status==='ready')", 60)
        js(w, "audio.muted=true")
        for i, n in enumerate((0, 1, 2)):
            js(w, f"pick(S.candidates[{n}].id)")
            if i == 0:
                js(w, "audio.play()")
                rec.caption("Pick a candidate: it plays inside the song with only that slot swapped",
                            "keys 1 to 0 switch candidates without losing the position; each is measured against the current sample")
            time.sleep(3.2)
        js(w, "act('rate',{id:S.candidates[2].id,stars:4})")
        rec.caption("Star, reject, note: ratings and the candidate list live next to the song", "sort by distance to the current sample, filter to the shortlist")
        time.sleep(3.5)
        js(w, "setSolo(true)")
        rec.caption("SOLO hears the sample alone; M puts it back in the mix", "")
        time.sleep(3.0)
        js(w, "setSolo(false)")
        js(w, "preset(1)")
        rec.caption("Loop one order, four orders or the whole song; click an order to start there",
                    "bright cells show where this slot plays")
        time.sleep(3.0)
        js(w, "setStart(8)")
        time.sleep(3.0)
        js(w, "preset(4)")
        time.sleep(2.0)
        js(w, "showDiff(S.candidates[2].id)")
        rec.caption("USE THIS shows the one-line YAML change before anything is written", "the song file stays the source of truth")
        time.sleep(4.5)
        js(w, "toggle('diff',false)")
        time.sleep(0.8)
        js(w, "tab('overview')")
        wait(w, "PAT.rows", 10)
        rec.caption("Song Overview: stems, arrangement, sample slots and a read-only pattern view", "")
        time.sleep(4.5)
        js(w, "muteCh(0);muteCh(1)")
        rec.caption("Mute or solo channels: the tryout section re-renders without them", "the YAML is untouched")
        wait(w, "S.candidates.every(c=>c.status==='ready')&&S.muted.length===2", 40)
        time.sleep(2.5)
        js(w, "soloCh(12)")
        wait(w, "S.candidates.every(c=>c.status==='ready')&&S.solo===12", 40)
        time.sleep(2.5)
        js(w, "resetStems()")
        time.sleep(1.5)
        js(w, "setStart(4)")
        rec.caption("Click an order in the arrangement: the pattern view follows", "note, instrument, volume and effect per channel, as the module has them")
        time.sleep(3.0)
        js(w, "setStart(20)")
        time.sleep(3.0)
        js(w, "setHex(true)")
        rec.caption("Rows in decimal like the YAML, or hex like a tracker", "")
        time.sleep(2.5)
        js(w, "setHex(false);setFocus('drums')")
        rec.caption("Filter the pattern view to the drums, the active channels or all 16", "")
        time.sleep(3.0)
        js(w, "setFocus(null);setStart(24)")
        js(w, "audio.muted=true;audio.play()")
        rec.caption("While the tryout plays, the pattern view follows the playhead", "")
        time.sleep(7.0)
        js(w, "audio.pause()")
        js(w, "act('stems')")
        rec.caption("EXPORT STEMS writes one WAV per playing channel next to the song", "")
        time.sleep(4.5)
        js(w, "tab('export');act('build',{render:false})")
        rec.caption("Render & Export: build the .it and verify it with libopenmpt", "")
        wait(w, "S.build&&S.build.status==='done'", 60)
        time.sleep(4.0)
        rec.caption("")
        time.sleep(0.8)
    except Exception as e:  # noqa: BLE001
        print("TOUR FAILED", repr(e), flush=True)
    finally:
        if rec:
            rec.stop = True
            rec.join(5)
            (OUT / "frames.json").write_text(json.dumps(rec.frames), encoding="utf-8")
            print("frames", len(rec.frames), flush=True)
        w.destroy()


# ---------------------------------------------------------------- assembly

def assemble():
    ff = imageio_ffmpeg.get_ffmpeg_exe()
    frames = json.loads((OUT / "frames.json").read_text(encoding="utf-8"))
    for name, fn in (("title", card_title), ("music", card_music), ("yaml", card_yaml), ("end", card_end), ("cli", card_cli)):
        stamp(fn()).save(OUT / f"{name}.jpg", quality=95)
        print("card", name, flush=True)
    WM_FRAMES = OUT / "frames_wm"
    WM_FRAMES.mkdir(exist_ok=True)
    for n, _ in frames:
        stamp(Image.open(FRAMES / f"f{n:05d}.jpg")).save(WM_FRAMES / f"f{n:05d}.jpg", quality=88)
    print("stamped", len(frames), "frames", flush=True)
    cards = [("title", 6.0), ("music", 11.0), ("yaml", 9.0), ("cli", 9.0)]
    lst = []
    for name, dur in cards:
        lst += [f"file '{(OUT / (name + '.jpg')).as_posix()}'", f"duration {dur}"]
    for i, (n, t) in enumerate(frames):
        nxt = frames[i + 1][1] if i + 1 < len(frames) else t + 1 / FPS
        lst += [f"file '{(WM_FRAMES / f'f{n:05d}.jpg').as_posix()}'", f"duration {max(0.02, nxt - t):.4f}"]
    lst += [f"file '{(OUT / 'end.jpg').as_posix()}'", "duration 12.0", f"file '{(OUT / 'end.jpg').as_posix()}'"]
    (OUT / "list.txt").write_text("\n".join(lst) + "\n", encoding="utf-8")
    total = sum(d for _, d in cards) + (frames[-1][1] + 1 / FPS if frames else 0) + 12.0
    cmd = [ff, "-y", "-hide_banner", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(OUT / "list.txt"),
           "-i", str(WAV), "-filter_complex",
           f"[0:v]fps=24,scale=1920:1080:flags=lanczos:in_range=pc:out_range=tv,format=yuv420p[v];[1:a]afade=t=in:d=1.5,afade=t=out:st={total - 5:.2f}:d=5[a]",
           "-map", "[v]", "-map", "[a]", "-t", f"{total:.2f}", "-c:v", "libx264", "-preset", "medium", "-crf", "19",
           "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", str(OUT / "vantage-demo.mp4")]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=1800)
    print("ffmpeg:", r.returncode, r.stderr[-800:], flush=True)
    print("video length", round(total, 1), "s ->", OUT / "vantage-demo.mp4", (OUT / "vantage-demo.mp4").stat().st_size, "bytes")


if __name__ == "__main__":
    FRAMES.mkdir(parents=True, exist_ok=True)
    if "--assemble-only" not in sys.argv:
        for f in FRAMES.glob("*.jpg"):
            f.unlink()
        srv = ThreadingHTTPServer(("127.0.0.1", 0), gui.Handler)
        url = f"http://127.0.0.1:{srv.server_address[1]}/"
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        gui.Handler.open_song(str(SONG))                        # warm the render cache before recording
        for _ in range(600):
            s = gui.Handler.state.snapshot()
            if s["candidates"] and all(c["status"] == "ready" for c in s["candidates"]):
                break
            time.sleep(0.5)
        print("cache warm:", sum(1 for c in s["candidates"] if c["status"] == "ready"), "of", len(s["candidates"]), flush=True)
        w = webview.create_window("VultureTracker", url, x=0, y=0, width=W + 16, height=H + 39, on_top=True, background_color="#0a0c0d")
        gui.Handler.window = w
        webview.start(tour, w)
    assemble()
