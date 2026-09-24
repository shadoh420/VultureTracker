// Node check of the live engine (web/engine-core.js on the official libopenmpt 0.8.9 wasm build), run by tests/test_engine.py:
//   node tests/engine_check.js <module.it> <rate> <frames> <mute channel> <instrument> <note>
// Prints one JSON line: the library version, the render (int16 LE, base64) of the whole module and of it with the channel
// muted through the interactive interface, the position after a seek, and a note preview rendered from a copy with every
// channel muted.
const fs = require('fs'), path = require('path');
const WEB = path.join(__dirname, '..', 'vulturetracker', 'web');
const {loadOpenmpt} = require(path.join(WEB, 'engine-core.js'));
const glue = new Function('libopenmpt', 'require', '__dirname', fs.readFileSync(path.join(WEB, 'libopenmpt.js'), 'utf8') + '\nreturn Module;');
const [itPath, rate, frames, muteCh, ins, note] = process.argv.slice(2);

function render(song, n) {
  const out = Buffer.alloc(4 * n), L = new Float32Array(1024), R = new Float32Array(1024);
  let done = 0;
  while (done < n) {
    const got = song.read(+rate, Math.min(1024, n - done), L, R);
    if (!got) break;
    for (let i = 0; i < got; i++) {
      out.writeInt16LE(Math.max(-32768, Math.min(32767, Math.round(L[i] * 32768))), 4 * (done + i));
      out.writeInt16LE(Math.max(-32768, Math.min(32767, Math.round(R[i] * 32768))), 4 * (done + i) + 2);
    }
    done += got;
  }
  return out.subarray(0, 4 * done);
}

loadOpenmpt((cfg) => glue(cfg, require, WEB), fs.readFileSync(path.join(WEB, 'libopenmpt.wasm'))).then(E => {
  const bytes = new Uint8Array(fs.readFileSync(itPath));
  const whole = new E.Song(bytes);
  const plain = render(whole, +frames);
  const muted = new E.Song(bytes);
  muted.mute(+muteCh, true);
  const mutedPcm = render(muted, +frames);
  const seekTo = whole.seek(1, 2), pos = whole.position();
  const prev = new E.Song(bytes);
  for (let c = 0; c < prev.channels; c++) prev.mute(c, true);
  const silent = render(prev, 2048);
  const ch = prev.playNote(+ins, +note, 1, 0);
  const on = render(prev, 8820);
  prev.noteOff(ch);
  const vu = muted.vu();
  console.log(JSON.stringify({version: E.version, channels: whole.channels, plain: plain.toString('base64'),
    muted: mutedPcm.toString('base64'), muted_flag: muted.muted(+muteCh), seek_seconds: seekTo, pos,
    preview_channel: ch, preview_silent_before: silent.toString('base64'), preview: on.toString('base64'), vu}));
  [whole, muted, prev].forEach(s => s.free());
}).catch(e => { console.error(e && e.stack || e); process.exit(1) });
