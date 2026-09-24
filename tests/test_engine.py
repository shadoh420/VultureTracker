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
        self.assertEqual(r["version"].split("+")[0], library_version().split("+")[0])
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


# the page's MIDI input run under node: its functions cut from gui.html, the tracker helpers and the DOM stubbed
MIDI_JS = r"""
const NOTES=['C-','C#','D-','D#','E-','F-','F#','G-','G#','A-','A#','B-'],noteTxt=n=>NOTES[n%12]+Math.floor(n/12),pad=n=>String(n).padStart(2,'0');
const cellOf=s=>{const [n,i,v,e]=s.split(' ');return {n,i,v,e}},cellText=p=>`${p.n} ${p.i} ${p.v} ${p.e}`;
const out=[],tabs=new Set(['t-pattern']),$=id=>({classList:{contains:c=>tabs.has(id)}}),document={querySelector:()=>null};
let S={song:{facts:{}}},EDIT=false,PAT={rows:[['... .. v20 A06']],order:0},CUR={o:0,row:0,ch:0},INS_SEL=null,W={data:null};
const insNum=()=>3,putCell=(p,adv)=>out.push(['cell',cellText(p),adv]),lvNoteOn=(...a)=>out.push(['on',...a]),lvNoteOff=k=>out.push(['off',k]);
PAGE
MIDI.on=true;midiMsg([0x90,60,127]);midiMsg([0x80,60,0]);          // preview only
EDIT=true;midiMsg([0x90,61,64]);midiMsg([0x90,61,0]);  // edit mode: entered with the velocity, note-on at 0 = note-off
MIDI.vel=false;midiMsg([0x90,72,10]);                 // velocity off: the volume column is left alone, full loudness
MIDI.on=false;midiMsg([0x90,50,100]);                 // MIDI switched off: nothing
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
                               ["cell", "C#5 03 v32 A06", True], ["on", "m61", None, 61, 64 / 127], ["off", "m61"],
                               ["cell", "C-6 03 v20 A06", True], ["on", "m72", None, 72, 1],
                               ["on", "m64", 4, 64, 1]])


if __name__ == "__main__":
    unittest.main()
