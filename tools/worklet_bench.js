// The live engine's audio-thread cost of its position message (vulturetracker/web/engine-worklet.js posts one every 4
// quanta): process() timed over a minute of a module with postMessage as a real structured clone (what MessagePort
// serialization does) and as a no-op, plus position() + vu() alone. Measured 2026-10-14 (LMMS-review phase 6): about
// 5 us a message, 0.05% of a 128-frame quantum at 48 kHz, so the SharedArrayBuffer path was not built. Rerun it after
// changing the worklet.
//
//   node tools/worklet_bench.js demo4/vantage.it [more.it ...]
// Native paired /api/playback JSON is accepted too. --loop FROM_ORDER:FROM_ROW:TO_ORDER:TO_ROW
// measures a native loop after its initial preparation (rows inclusive). Run timing under a quiet lease.
const fs = require('fs'), path = require('path');
const files = process.argv.slice(2);
let loop = null;
const loopArg = files.indexOf('--loop');
if (loopArg >= 0) {
  const values = (files[loopArg + 1] || '').split(':').map(Number);
  if (values.length !== 4 || values.some(x => !Number.isSafeInteger(x) || x < 0)) {
    console.error('--loop requires four nonnegative integers: FROM_ORDER:FROM_ROW:TO_ORDER:TO_ROW');
    process.exit(2);
  }
  loop = {from: values.slice(0, 2), to: values.slice(2)};
  files.splice(loopArg, 2);
}
if (!files.length || files.some(f => !fs.existsSync(f))) {
  console.error('usage: node tools/worklet_bench.js MODULE.it|PLAYBACK.json [...] [--loop 0:0:0:0]  (compiled modules, e.g. demo4/vantage.it: ' +
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
  const pair = file.endsWith('.json') ? JSON.parse(fs.readFileSync(file, 'utf8')) : null;
  if (pair && (!pair.plan || typeof pair.backing_it !== 'string')) throw new Error('JSON must be a native /api/playback pair');
  if (loop && !pair) throw new Error('--loop currently requires a native playback pair');
  const it = new Uint8Array(pair ? Buffer.from(pair.backing_it, 'base64') : fs.readFileSync(file));
  let ready;
  const wait = new Promise(ok => ready = ok);
  post = m => m.type === 'ready' && ready();
  const p = new Proc({processorOptions: {wasm: fs.readFileSync(path.join(WEB, 'libopenmpt.wasm'))}});
  await wait;
  const L = new Float32Array(128), R = new Float32Array(128), ms = {};
  let bytes = 0, preparationPauses = 0, timings = [];
  for (const mode of ['noop', 'clone', 'noop', 'clone']) {  // each twice, the second pass kept (warm)
    post = m => {
      if (m.type === 'error') throw new Error(m.text);
      if (m.type === 'preparing') preparationPauses++;
      if (mode === 'clone' && m.type === 'pos') bytes = JSON.stringify(structuredClone(m)).length;
    };
    p.command({type: 'load', bytes: it.slice().buffer, plan: pair?.plan ?? null, gain: pair?.gain ?? 1});
    p.command({type: 'loop', span: loop});
    p.command({type: 'play', order: loop?.from[0] ?? 0, row: loop?.from[1] ?? 0});
    for (let b = 0; b < 400; b++) p.process([], [[L, R]]);
    if (p.pending) throw new Error('Playback is still preparing after warmup; use a shorter prefix for this benchmark');
    preparationPauses = 0; timings = [];
    const t0 = process.hrtime.bigint();
    for (let b = 0; b < BLOCKS; b++) {
      const start = pair ? process.hrtime.bigint() : null;
      p.process([], [[L, R]]);
      if (pair) timings.push(us(start));
    }
    ms[mode] = us(t0) / 1e3;
  }
  const s = p.song, reps = 20000, m = {type: 'pos', ...s.position(), playing: true, vu: s.vu(), frame: 0};
  let t0 = process.hrtime.bigint();
  for (let i = 0; i < reps; i++) { s.position(); s.vu() }
  const posvu = us(t0) / reps;
  t0 = process.hrtime.bigint();
  for (let i = 0; i < reps; i++) structuredClone(m);
  const clone = us(t0) / reps, msgs = BLOCKS / 4;
  timings.sort((a, b) => a - b);
  const nativeTiming = pair ? {loop, preparation_pauses_after_warmup: preparationPauses,
    process_p95_us: +timings[Math.floor(timings.length * .95)].toFixed(1),
    process_max_us: +timings[timings.length - 1].toFixed(1)} : {};
  p.pending?.song.free(); p.loopReplay?.song.free(); p.song?.free(); p.preview?.free();
  return {file, ...nativeTiming, message_json_bytes: bytes, vu_channels: m.vu.length, position_plus_vu_us: +posvu.toFixed(2),
    structured_clone_us: +clone.toFixed(2), extra_per_message_us: +((ms.clone - ms.noop) * 1e3 / msgs).toFixed(2),
    process_per_quantum_us: +(ms.noop * 1e3 / BLOCKS).toFixed(1), quantum_budget_us: Math.round(128 / 48000 * 1e6),
    messages_per_second: 48000 / 512};
}

(async () => { for (const f of files) console.log(JSON.stringify(await bench(f))) })().catch(e => {
  console.error(e.message); process.exitCode = 1;
});
