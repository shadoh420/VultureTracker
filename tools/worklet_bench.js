// The live engine's audio-thread cost of its position message (vulturetracker/web/engine-worklet.js posts one every 4
// quanta): process() timed over a minute of a module with postMessage as a real structured clone (what MessagePort
// serialization does) and as a no-op, plus position() + vu() alone. Measured 2026-10-14 (LMMS-review phase 6): about
// 5 us a message, 0.05% of a 128-frame quantum at 48 kHz, so the SharedArrayBuffer path was not built. Rerun it after
// changing the worklet.
//
//   node tools/worklet_bench.js demo4/vantage.it [more.it ...]
const fs = require('fs'), path = require('path');
const files = process.argv.slice(2);
if (!files.length || files.some(f => !fs.existsSync(f))) {
  console.error('usage: node tools/worklet_bench.js MODULE.it [MODULE.it ...]  (compiled modules, e.g. demo4/vantage.it: ' +
                'python -m vulturetracker build demo4/vantage.yaml writes it)' + (files.length ? `\nnot found: ${files.filter(f => !fs.existsSync(f)).join(', ')}` : ''));
  process.exit(2);
}
const WEB = path.join(__dirname, '..', 'vulturetracker', 'web');
const glue = new Function('libopenmpt', 'require', '__dirname', fs.readFileSync(path.join(WEB, 'libopenmpt.js'), 'utf8') + '\nreturn Module;');
let post = m => {};
Object.assign(globalThis, {sampleRate: 48000, currentTime: 0, currentFrame: 0, loadGlue: cfg => glue(cfg, require, WEB),
  loadOpenmpt: require(path.join(WEB, 'engine-core.js')).loadOpenmpt,
  AudioWorkletProcessor: class { constructor() { this.port = {postMessage: m => post(m)} } },
  registerProcessor: (n, c) => { globalThis.Proc = c }});
require(path.join(WEB, 'engine-worklet.js'));
const BLOCKS = 48000 * 60 / 128;  // a minute of audio
const us = t0 => Number(process.hrtime.bigint() - t0) / 1e3;

async function bench(file) {
  const it = new Uint8Array(fs.readFileSync(file));
  let ready;
  const wait = new Promise(ok => ready = ok);
  post = m => m.type === 'ready' && ready();
  const p = new Proc({processorOptions: {wasm: fs.readFileSync(path.join(WEB, 'libopenmpt.wasm'))}});
  await wait;
  const L = new Float32Array(128), R = new Float32Array(128), ms = {};
  let bytes = 0;
  for (const mode of ['noop', 'clone', 'noop', 'clone']) {  // each twice, the second pass kept (warm)
    post = mode === 'clone' ? m => { if (m.type === 'pos') bytes = JSON.stringify(structuredClone(m)).length } : m => {};
    p.command({type: 'load', bytes: it.slice().buffer});
    p.command({type: 'play', order: 0, row: 0});
    for (let b = 0; b < 400; b++) p.process([], [[L, R]]);
    const t0 = process.hrtime.bigint();
    for (let b = 0; b < BLOCKS; b++) p.process([], [[L, R]]);
    ms[mode] = us(t0) / 1e3;
  }
  const s = p.song, reps = 20000, m = {type: 'pos', ...s.position(), playing: true, vu: s.vu(), frame: 0};
  let t0 = process.hrtime.bigint();
  for (let i = 0; i < reps; i++) { s.position(); s.vu() }
  const posvu = us(t0) / reps;
  t0 = process.hrtime.bigint();
  for (let i = 0; i < reps; i++) structuredClone(m);
  const clone = us(t0) / reps, msgs = BLOCKS / 4;
  return {file, message_json_bytes: bytes, vu_channels: m.vu.length, position_plus_vu_us: +posvu.toFixed(2),
    structured_clone_us: +clone.toFixed(2), extra_per_message_us: +((ms.clone - ms.noop) * 1e3 / msgs).toFixed(2),
    process_per_quantum_us: +(ms.noop * 1e3 / BLOCKS).toFixed(1), quantum_budget_us: Math.round(128 / 48000 * 1e6),
    messages_per_second: 48000 / 512};
}

(async () => { for (const f of files) console.log(JSON.stringify(await bench(f))) })();
