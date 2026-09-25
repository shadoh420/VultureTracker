"""The live engine (vulturetracker/web: libopenmpt compiled to WebAssembly, the page's AudioWorklet) against the vendored
DLL the renders use: same version, same samples, a channel muted through the interactive interface equals the channel
disabled in the header, seeking, and a note preview. Runs tests/engine_check.js under node; skipped without node."""
import base64
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from vulturetracker import api, gui
from vulturetracker.openmpt import LoadedModule, library_version
from vulturetracker.wavload import write_wav

from tests.test_gui import RATE, SONG, sine

ROOT = Path(__file__).resolve().parent.parent
NODE = shutil.which("node")


@unittest.skipUnless(NODE and (ROOT / "vulturetracker" / "web" / "libopenmpt.wasm").exists(), "needs node and web/libopenmpt.wasm")
class TestEngine(unittest.TestCase):
    def test_metronome_clicks_on_beat_rows(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            write_wav(d / "a.wav", RATE, [sine(440)], root_note=69)
            write_wav(d / "b.wav", RATE, [sine(880)])
            (d / "song.it").write_bytes(api.compile_song(api.from_yaml(SONG), d)[0])
            (d / "metro.js").write_text(METRO_JS, encoding="utf-8")
            out = subprocess.run([NODE, str(d / "metro.js"), str(ROOT / "vulturetracker" / "web"), str(d / "song.it")],
                                 capture_output=True, text=True, timeout=60, check=True)
        r = json.loads(out.stdout)
        expect = [f for f in r["expect"] if f < 128 * 600 - 32]
        self.assertGreater(len(expect), 5)  # rows 0 and 2 of both 4-row patterns, the song looping (0.12 s a row)
        self.assertEqual(len(r["onsets"]), len(expect))
        for got, want in zip(r["onsets"], expect):
            self.assertLessEqual(abs(got - want), 2)  # the first click sample is sin(0) = 0

    def test_swap_goes_on_from_the_same_frame(self):
        # a song swapped in while it plays (an edit, a fader) must not replay the part of the row already played: every
        # row after the swap starts on the frame it starts on without one
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            write_wav(d / "a.wav", RATE, [sine(440)], root_note=69)
            write_wav(d / "b.wav", RATE, [sine(880)])
            (d / "song.it").write_bytes(api.compile_song(api.from_yaml(SONG), d)[0])
            (d / "swap.js").write_text(SWAP_JS, encoding="utf-8")
            out = subprocess.run([NODE, str(d / "swap.js"), str(ROOT / "vulturetracker" / "web"), str(d / "song.it")],
                                 capture_output=True, text=True, timeout=60, check=True)
        r = json.loads(out.stdout)
        self.assertGreater(len(r["plain"]), 4)
        self.assertEqual(r["swapped"], r["plain"])

    def test_swap_keeps_the_voices_still_fading(self):
        # a note re-struck under NNA fade leaves the old voice fading under the new one; a song swapped in just after
        # (an edit) must keep that voice: a seek straight to the row dropped it (a pad dipped 12 dB for a second)
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            write_wav(d / "a.wav", RATE, [sine(440, seconds=2.0)])
            (d / "song.it").write_bytes(api.compile_song(api.from_yaml(FADE_SONG), d)[0])
            (d / "fade.js").write_text(FADE_JS, encoding="utf-8")
            out = subprocess.run([NODE, str(d / "fade.js"), str(ROOT / "vulturetracker" / "web"), str(d / "song.it")],
                                 capture_output=True, text=True, timeout=60, check=True)
        r = json.loads(out.stdout)
        self.assertGreater(r["level"], 0.05)       # the song sounds after the swap
        self.assertLess(r["diff"], 1e-4)           # and exactly as without one

    def test_a_moving_fader_plays_like_the_header_and_the_preview_sleeps(self):
        # chvol / chpan while the song plays = the channel's volume and pan written into the header (what the fader's
        # release then swaps in); the preview copy renders only while a preview note sounds, then sleeps
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            write_wav(d / "a.wav", RATE, [sine(440)], root_note=69)
            write_wav(d / "b.wav", RATE, [sine(880)])
            (d / "song.it").write_bytes(api.compile_song(api.from_yaml(SONG), d)[0])
            (d / "fader.js").write_text(FADER_JS, encoding="utf-8")
            out = subprocess.run([NODE, str(d / "fader.js"), str(ROOT / "vulturetracker" / "web"), str(d / "song.it")],
                                 capture_output=True, text=True, timeout=60, check=True)
        r = json.loads(out.stdout)
        self.assertGreater(r["level"], 0.05)
        self.assertLess(r["diff"], 1e-6)                  # a fader moved live = the same value in the header
        self.assertGreater(r["plain_diff"], 0.01)         # and the values do change the sound
        self.assertEqual(r["reads_playing"], 0)           # the preview copy is idle while the song plays
        self.assertEqual(r["reads_idle"], 0)              # and while stopped with no note
        self.assertGreater(r["preview_level"], 0.01)      # a preview note sounds
        self.assertTrue(r["asleep"])                      # and some silence after its key is up, the copy sleeps again

    def test_loads_report_their_id(self):
        # a module the engine cannot load answers with the load's id (the page's wait for it ends, E1); a swap replaced
        # by a newer one before it took over is covered by the newer one's 'loaded', whose id is higher (E2)
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            write_wav(d / "a.wav", RATE, [sine(440)], root_note=69)
            write_wav(d / "b.wav", RATE, [sine(880)])
            (d / "song.it").write_bytes(api.compile_song(api.from_yaml(SONG), d)[0])
            (d / "load.js").write_text(LOAD_JS, encoding="utf-8")
            out = subprocess.run([NODE, str(d / "load.js"), str(ROOT / "vulturetracker" / "web"), str(d / "song.it")],
                                 capture_output=True, text=True, timeout=60, check=True)
        msgs = json.loads(out.stdout)
        self.assertEqual(msgs[0][:2], ["error", 1])
        self.assertEqual(msgs[1:], [["loaded", 2], ["loaded", 4]])
        # the page's side: a 'loaded' ends the wait for its load and every earlier one, an 'error' the wait for its own
        page = (ROOT / "vulturetracker" / "gui.html").read_text(encoding="utf-8")
        a = page.index("function lvMsg(")
        b = page.index("\n// what the engine should be doing")
        with tempfile.TemporaryDirectory() as tmp:
            js = Path(tmp) / "msg.js"
            js.write_text(LVMSG_JS.replace("PAGE", page[a:b]), encoding="utf-8")
            got = json.loads(subprocess.run([NODE, str(js)], capture_output=True, text=True, timeout=30, check=True).stdout)
        self.assertEqual(got, {"done": ["ok 1", "fail 3 bad module", "ok 2", "ok 4"], "left": ["5"], "err": None})

    def test_wasm_engine_matches_the_dll(self):
        import numpy as np
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            write_wav(d / "a.wav", RATE, [sine(440)], root_note=69)
            write_wav(d / "b.wav", RATE, [sine(880)])
            it = api.compile_song(api.from_yaml(SONG), d)[0]
            (d / "song.it").write_bytes(it)
            rate = 48000
            with LoadedModule(it) as lm:
                frames = int(lm.duration() * rate)  # one pass: after it the DLL render stops, the engine loops the song
                ref = np.frombuffer(lm.render(rate, oversample=1), "<i2").astype(int)[: 2 * frames]
                seek = lm.order_start(1, 2)
            with LoadedModule(gui.patch_it(it, [0])) as lm:
                ref_muted = np.frombuffer(lm.render(rate, oversample=1), "<i2").astype(int)[: 2 * frames]
            out = subprocess.run([NODE, str(ROOT / "tests" / "engine_check.js"), str(d / "song.it"), str(rate), str(frames), "0", "0", "60"],
                                 capture_output=True, text=True, timeout=60)
            self.assertEqual(out.returncode, 0, out.stderr)
            r = json.loads(out.stdout)
        pcm = lambda k: np.frombuffer(base64.b64decode(r[k]), "<i2").astype(int)  # noqa: E731
        # the wasm build is 0.8.9, as the vendored DLL is; a system library of another version (Linux distributions ship
        # 0.7.x) is compared by its renders alone, which agree within 2 LSB all the same
        self.assertEqual(r["version"].split("+")[0], "0.8.9")
        if not library_version().startswith("0.8.9"):
            print(f"\n  note: libopenmpt {library_version()} here, the engine's {r['version']}: renders compared, versions not")
        plain, muted = pcm("plain"), pcm("muted")
        self.assertEqual(len(plain), len(ref))
        self.assertGreater(np.abs(ref).max(), 2000)
        self.assertLessEqual(np.abs(plain - ref).max(), 2)             # the same mixer: within 2 LSB of the DLL's int16 render
        self.assertLessEqual(np.abs(muted - ref_muted).max(), 2)       # interactive mute = the header's channel-disable bit
        self.assertTrue(r["muted_flag"])
        self.assertAlmostEqual(r["seek_seconds"], seek, places=6)
        self.assertEqual((r["pos"]["order"], r["pos"]["row"]), (1, 2))
        self.assertEqual(np.abs(pcm("preview_silent_before")).max(), 0)  # every song channel muted
        self.assertGreaterEqual(r["preview_channel"], 2)                 # a free channel past the pattern's two
        self.assertGreater(np.abs(pcm("preview")).max(), 1000)           # the note preview sounds


# the worklet's metronome under node: the processor itself (engine-worklet.js on engine-core.js and the wasm) with the
# AudioWorkletGlobalScope stubbed, rendered with and without the metronome; the clicks must start where a beat row starts
METRO_JS = r"""
const fs = require('fs'), path = require('path'), WEB = process.argv[2], it = new Uint8Array(fs.readFileSync(process.argv[3]));
const glue = new Function('libopenmpt', 'require', '__dirname', fs.readFileSync(path.join(WEB, 'libopenmpt.js'), 'utf8') + '\nreturn Module;');
Object.assign(globalThis, {sampleRate: 48000, currentTime: 0, currentFrame: 0, loadGlue: cfg => glue(cfg, require, WEB),
  loadOpenmpt: require(path.join(WEB, 'engine-core.js')).loadOpenmpt,
  AudioWorkletProcessor: class { constructor() { this.port = {postMessage: m => this.onmsg && this.onmsg(m)} } },
  registerProcessor: (n, c) => { globalThis.Proc = c }});
require(path.join(WEB, 'engine-worklet.js'));
const make = () => new Promise(ok => { const p = new Proc({processorOptions: {wasm: fs.readFileSync(path.join(WEB, 'libopenmpt.wasm'))}}); p.onmsg = m => m.type === 'ready' && ok(p) });
function run(p, metro, blocks) {
  p.command({type: 'load', bytes: it.slice().buffer});
  if (metro) p.command({type: 'metro', on: true, beat: 2, bar: 4});
  p.command({type: 'play', order: 0, row: 0});
  const out = [];
  for (let b = 0; b < blocks; b++) { const L = new Float32Array(128), R = new Float32Array(128); p.process([], [[L, R]]); out.push(...L) }
  return out;
}
(async () => {
  const blocks = 600, a = run(await make(), true, blocks), b = run(await make(), false, blocks);
  const onsets = [];
  for (let i = 0, quiet = 1e9; i < a.length; i++) { const d = Math.abs(a[i] - b[i]) > 1e-4; if (d && quiet > 400) onsets.push(i); quiet = d ? 0 : quiet + 1 }
  // where the processor sees each beat row start: the end of the 32-frame step after which the row changed
  const E = await loadOpenmpt(cfg => glue(cfg, require, WEB), fs.readFileSync(path.join(WEB, 'libopenmpt.wasm')));
  const s = new E.Song(it), L = new Float32Array(32), R = new Float32Array(32), expect = [];
  let last = null;
  for (let i = 0; i < 128 * blocks; i += 32) { s.read(48000, 32, L, R); const p = s.position(), k = p.order * 1024 + p.row; if (k !== last) { last = k; if (p.row % 2 === 0) expect.push(i + 32) } }
  console.log(JSON.stringify({onsets, expect}));
})();
"""


# the worklet's loads: garbage (id 1), a good module (2), then while playing two swaps in a row (3, 4): the second
# replaces the first before it takes over. Prints the loaded/error messages as [type, id]
LOAD_JS = r"""
const fs = require('fs'), path = require('path'), WEB = process.argv[2], it = new Uint8Array(fs.readFileSync(process.argv[3]));
const glue = new Function('libopenmpt', 'require', '__dirname', fs.readFileSync(path.join(WEB, 'libopenmpt.js'), 'utf8') + '\nreturn Module;');
Object.assign(globalThis, {sampleRate: 48000, currentTime: 0, currentFrame: 0, loadGlue: cfg => glue(cfg, require, WEB),
  loadOpenmpt: require(path.join(WEB, 'engine-core.js')).loadOpenmpt,
  AudioWorkletProcessor: class { constructor() { this.port = {postMessage: m => this.onmsg && this.onmsg(m)} } },
  registerProcessor: (n, c) => { globalThis.Proc = c }});
require(path.join(WEB, 'engine-worklet.js'));
(async () => {
  const p = await new Promise(ok => { const p = new Proc({processorOptions: {wasm: fs.readFileSync(path.join(WEB, 'libopenmpt.wasm'))}}); p.onmsg = m => m.type === 'ready' && ok(p) });
  const out = [];
  p.onmsg = m => { if (m.type === 'loaded' || m.type === 'error') out.push([m.type, m.id]) };
  p.command({type: 'load', bytes: new Uint8Array(100).buffer, id: 1});
  p.command({type: 'load', bytes: it.slice().buffer, id: 2});
  p.command({type: 'play', order: 0, row: 0});
  for (let b = 0; b < 50; b++) p.process([], [[new Float32Array(128), new Float32Array(128)]]);
  p.command({type: 'load', bytes: it.slice().buffer, keep: true, id: 3});
  p.command({type: 'load', bytes: it.slice().buffer, keep: true, id: 4});
  for (let b = 0; b < 200; b++) p.process([], [[new Float32Array(128), new Float32Array(128)]]);
  console.log(JSON.stringify(out));
})();
"""


# the page's lvMsg under node, with loads 1-5 waiting: an error for 3, then 'loaded' for 2 and for 4
LVMSG_JS = r"""
const done = [], LV = {loads: {}, err: null}, S = null, renderLiveBar = () => {}, $ = () => ({classList: {contains: () => false}});
for (const id of [1, 2, 3, 4, 5]) LV.loads[id] = {ok: () => done.push('ok ' + id), fail: e => done.push('fail ' + id + ' ' + e.message)};
PAGE
lvMsg({type: 'loaded', id: 1});
lvMsg({type: 'error', id: 3, text: 'bad module'});
lvMsg({type: 'loaded', id: 4});
console.log(JSON.stringify({done, left: Object.keys(LV.loads), err: LV.err}));
"""


# the worklet swapping the song in mid-row (load with keep, as the page does after an edit) against one that plays on:
# the frame (to the 128-frame block) where each row starts, over 300 blocks after the swap
SWAP_JS = r"""
const fs = require('fs'), path = require('path'), WEB = process.argv[2], it = new Uint8Array(fs.readFileSync(process.argv[3]));
const glue = new Function('libopenmpt', 'require', '__dirname', fs.readFileSync(path.join(WEB, 'libopenmpt.js'), 'utf8') + '\nreturn Module;');
Object.assign(globalThis, {sampleRate: 48000, currentTime: 0, currentFrame: 0, loadGlue: cfg => glue(cfg, require, WEB),
  loadOpenmpt: require(path.join(WEB, 'engine-core.js')).loadOpenmpt,
  AudioWorkletProcessor: class { constructor() { this.port = {postMessage: m => this.onmsg && this.onmsg(m)} } },
  registerProcessor: (n, c) => { globalThis.Proc = c }});
require(path.join(WEB, 'engine-worklet.js'));
const make = () => new Promise(ok => { const p = new Proc({processorOptions: {wasm: fs.readFileSync(path.join(WEB, 'libopenmpt.wasm'))}}); p.onmsg = m => m.type === 'ready' && ok(p) });
async function run(swapAt) {
  const p = await make(), rows = [];
  p.command({type: 'load', bytes: it.slice().buffer});
  p.command({type: 'play', order: 0, row: 0});
  let last = null;
  for (let b = 0; b < 400; b++) {
    if (b === swapAt) p.command({type: 'load', bytes: it.slice().buffer, keep: true});
    p.process([], [[new Float32Array(128), new Float32Array(128)]]);
    const q = p.song.position(), k = q.order * 1024 + q.row;
    if (k !== last) { last = k; if (b > 100) rows.push([b, k]) }
  }
  return rows;
}
(async () => { console.log(JSON.stringify({plain: await run(-1), swapped: await run(100)})) })();
"""


FADER_JS = SWAP_JS.split("async function run")[0] + r"""
function render(p, quanta) {
  const L = [], R = [];
  for (let b = 0; b < quanta; b++) {
    const o = [new Float32Array(128), new Float32Array(128)];
    p.process([], [o]);
    L.push(...o[0]); R.push(...o[1]);
  }
  return [L, R];
}
const maxDiff = (a, b) => a[0].reduce((m, v, i) => Math.max(m, Math.abs(v - b[0][i]), Math.abs(a[1][i] - b[1][i])), 0);
const peak = a => a[0].reduce((m, v, i) => Math.max(m, Math.abs(v), Math.abs(a[1][i])), 0);
(async () => {
  const header = it.slice();
  header[0x80] = 32;                        // channel 1 at volume 32 of 64
  header[0x41] = header[0x41] & 0x80;       // channel 2 panned hard left
  const a = await make();
  a.command({type: 'load', bytes: header.buffer});
  a.command({type: 'play', order: 0, row: 0});
  const want = render(a, 300);
  const b = await make();
  b.command({type: 'load', bytes: it.slice().buffer});
  let reads = 0;
  const read = b.preview.read.bind(b.preview);
  b.preview.read = (...x) => { reads++; return read(...x) };
  b.command({type: 'play', order: 0, row: 0});
  b.command({type: 'chvol', ch: 0, value: 0.5});
  b.command({type: 'chpan', ch: 1, value: -1});
  const got = render(b, 300), readsPlaying = reads;
  const c = await make();
  c.command({type: 'load', bytes: it.slice().buffer});
  c.command({type: 'play', order: 0, row: 0});
  const plain = render(c, 300);
  b.command({type: 'stop'});
  render(b, 20);
  const readsIdle = reads - readsPlaying;
  let ch = -1;
  b.onmsg = m => { if (m.type === 'note') ch = m.ch };
  b.command({type: 'note', id: 'k', ins: 0, note: 60});
  const note = render(b, 60);
  b.command({type: 'noteoff', ch, on: 'preview'});
  render(b, Math.ceil(2.5 * 48000 / 128));  // the 0.3 s sine's tail, then the quiet time
  console.log(JSON.stringify({level: peak(want), diff: maxDiff(got, want), plain_diff: maxDiff(plain, want),
    reads_playing: readsPlaying, reads_idle: readsIdle, preview_level: peak(note), asleep: b.previewQuiet === -1}));
})();
"""


# one channel, a two-second tone struck on rows 0 and 4 with NNA fade: after row 4 the first note fades under the second
FADE_SONG = """module: {title: F, tempo: 125, speed: 6, channels: [{name: A}]}
samples:
  1: {file: a.wav, name: A tone}
instruments:
  1: {name: Pad, sample: 1, nna: fade, fadeout: 8}
patterns:
  p1:
    rows: 8
    data: |
      00: C-5 01 ... ...
      01: ... .. ... ...
      02: ... .. ... ...
      03: ... .. ... ...
      04: C-5 01 ... ...
      05: ... .. ... ...
      06: ... .. ... ...
      07: ... .. ... ...
orders: [p1]
"""
# plays FADE_SONG from the start twice, once with the same song swapped in on row 5; prints the largest difference
# between the two from there on and the level there
FADE_JS = SWAP_JS.split("async function run")[0] + r"""
async function run(swap) {
  const p = await make(), out = [];
  p.command({type: 'load', bytes: it.slice().buffer});
  p.command({type: 'play', order: 0, row: 0});
  let at = -1;
  for (let b = 0; b < 700; b++) {
    if (at < 0 && p.song.position().row >= 5) { at = b; if (swap) p.command({type: 'load', bytes: it.slice().buffer, keep: true}) }
    const L = new Float32Array(128), R = new Float32Array(128);
    p.process([], [[L, R]]);
    if (at >= 0 && b < at + 200) out.push(...L);
  }
  return out;
}
(async () => {
  const a = await run(false), b = await run(true);
  let diff = 0, level = 0;
  for (let i = 0; i < a.length; i++) { diff = Math.max(diff, Math.abs(a[i] - b[i])); level = Math.max(level, Math.abs(a[i])) }
  console.log(JSON.stringify({diff, level}));
})();
"""


# the page's MIDI input run under node: its functions cut from gui.html, the tracker helpers and the DOM stubbed
MIDI_JS = r"""
const NOTES=['C-','C#','D-','D#','E-','F-','F#','G-','G#','A-','A#','B-'],noteTxt=n=>NOTES[n%12]+Math.floor(n/12),pad=n=>String(n).padStart(2,'0');
const cellOf=s=>{const [n,i,v,e]=s.split(' ');return {n,i,v,e}},cellText=p=>`${p.n} ${p.i} ${p.v} ${p.e}`;
const out=[],tabs=new Set(['t-pattern']),$=id=>({classList:{contains:c=>tabs.has(id)}}),document={querySelector:()=>null};
let S={song:{facts:{}}},EDIT=false,PAT={rows:[['... .. v20 A06'],['... .. ... ...'],['... .. ... ...']],order:0},CUR={o:0,row:0,ch:0},INS_SEL=null,W={data:null};
const LV={playing:false,pos:null,oi:-1};
const insNum=()=>3,putCell=(p,adv)=>out.push(['cell',cellText(p),adv,CUR.row]),lvNoteOn=(...a)=>out.push(['on',...a]),lvNoteOff=k=>out.push(['off',k]);
PAGE
MIDI.on=true;midiMsg([0x90,60,127]);midiMsg([0x80,60,0]);          // preview only
EDIT=true;midiMsg([0x90,61,64]);midiMsg([0x90,61,0]);  // edit mode: entered with the velocity, note-on at 0 = note-off
MIDI.vel=false;midiMsg([0x90,72,10]);                 // velocity off: the volume column is left alone, full loudness
MIDI.on=false;midiMsg([0x90,50,100]);                 // MIDI switched off: nothing
MIDI.on=true;LV.playing=true;LV.oi=0;LV.pos={order:0,row:2};midiMsg([0x90,62,127]);  // recorded at the row playing, no step
LV.oi=1;midiMsg([0x90,63,127]);LV.playing=false;                      // another pattern plays: at the cursor
EDIT=false;MIDI.on=true;tabs.clear();tabs.add('t-smp');W.data={player:[4,60]};midiMsg([0x90,64,127]);  // the Samples tab plays the slot's player
console.log(JSON.stringify(out));
"""


@unittest.skipUnless(NODE, "needs node")
class TestMidi(unittest.TestCase):
    def test_midi_input(self):
        page = (ROOT / "vulturetracker" / "gui.html").read_text(encoding="utf-8")
        a, b = page.index("function enterNote("), page.index("if(MIDI.on)midiStart();else renderMidi();")
        with tempfile.TemporaryDirectory() as tmp:
            js = Path(tmp) / "midi.js"
            js.write_text(MIDI_JS.replace("PAGE", page[a:b]), encoding="utf-8")
            out = json.loads(subprocess.run([NODE, str(js)], capture_output=True, text=True, timeout=30, check=True).stdout)
        self.assertEqual(out, [["on", "m60", None, 60, 1], ["off", "m60"],
                               ["cell", "C#5 03 v32 A06", True, 0], ["on", "m61", None, 61, 64 / 127], ["off", "m61"],
                               ["cell", "C-6 03 v20 A06", True, 0], ["on", "m72", None, 72, 1],
                               ["cell", "D-5 03 ... ...", False, 2], ["on", "m62", None, 62, 1],
                               ["cell", "D#5 03 ... ...", True, 2], ["on", "m63", None, 63, 1],
                               ["on", "m64", 4, 64, 1]])


if __name__ == "__main__":
    unittest.main()
