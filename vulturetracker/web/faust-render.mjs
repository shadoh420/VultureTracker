// Faust code compiled and rendered offline with faustwasm (GRAME's Faust compiler as WebAssembly, LGPL-3.0, fetched on
// demand into the faustwasm folder, never shipped): in node for sample recipes (`faust:`, vulturetracker/faust.py) and in
// the page for the FAUST tab, whose live node (createNode) comes from the same compiled code. Polyphonic, Faust's way:
// each note is a voice whose controls ending in /freq, /gain and /gate get the note's pitch, velocity / 127 and 1 at
// key-on (0 at key-off); the other controls are shared by all voices (params, by label); `effect = ...;` in the code
// runs once on the voices' sum.
//   node faust-render.mjs <faustwasm folder> <job.json> <out.f32>   prints {"channels", "frames", "controls"}

const isNode = typeof window === 'undefined';

async function at(base, rel) {
  if (!isNode) return `${base.replace(/\/$/, '')}/${rel}`;
  const {pathToFileURL} = await import('url');
  const path = await import('path');
  return rel.endsWith('.js') && rel.startsWith('dist') ? pathToFileURL(path.join(base, rel)).href : path.join(base, rel);
}

export async function loadFaust(base) {
  const lib = await import(await at(base, 'dist/esm/index.js'));
  const mod = await lib.instantiateFaustModuleFromFile(await at(base, 'libfaust-wasm/libfaust-wasm.js'));
  const compiler = new lib.FaustCompiler(new lib.LibFaust(mod));
  return {lib, compiler, version: compiler.version()};
}

// the DSP's controls: [{address, label, type, init, min, max, step, midi}], midi the [midi:...] mapping ('ctrl 1',
// 'pitchwheel') or ''
export function controls(proc) {
  const out = [];
  const walk = items => items.forEach(it => {
    if (it.items) walk(it.items);
    else if (it.address) out.push({address: it.address, label: it.label, type: it.type, init: it.init ?? 0,
                                   min: it.min ?? 0, max: it.max ?? 1, step: it.step ?? 0,
                                   midi: ((it.meta || []).find(m => m.midi) || {midi: ''}).midi.trim()});
  });
  walk(proc.getUI());
  return out;
}

// a FaustPolyDspGenerator: offline renders (renderNotes) and live nodes (createNode) are made from it
export async function compileFaust(F, code) {
  const gen = new F.lib.FaustPolyDspGenerator();
  try {
    if (!await gen.compile(F.compiler, 'vt', code, '-ftz 2')) throw new Error('the Faust code did not compile');
    // faustwasm compiles the voice alone when `effect` fails, whatever the reason: compiled as faustwasm tries it (on the
    // code's first line, so the error's line numbers are the code's), anything but "no effect" is the code's error
    if (!gen.effectFactory && /\beffect\b/.test(code)) {
      try {
        await F.compiler.createPolyDSPFactory('vt', `dsp_code = environment{${code}\n};\nprocess = dsp_code.effect;`, '-ftz 2');
      } catch (e) {
        if (!/undefined symbol : effect\b/.test(e.message)) throw e;
      }
    }
    return gen;
  } catch (e) {
    throw new Error(String(F.compiler.getErrorMessage() || e.message || e).trim());
  }
}

// notes [{note, start, length, velocity}] (note as MIDI, C-5 = 60, fractional between keys; start and length in seconds),
// a voice each (as many voices as notes: a render never steals one), keyed on and off at their frames, at least one frame
// apart; `seconds` long (default: the last key-off plus `tail`). Returns {channels: Float32Array[], controls}
export async function renderNotes(gen, {notes, seconds, tail = 0.5, params = {}, rate = 44100}) {
  const proc = await gen.createOfflineProcessor(rate, 128, Math.max(1, notes.length));
  const cs = controls(proc), find = name => cs.find(c => c.label.toLowerCase() === String(name).toLowerCase() || c.address === name);
  for (const [k, v] of Object.entries(params)) {
    const c = find(k);
    if (!c) throw new Error(`the Faust code has no control named "${k}" (it has: ${cs.map(c => c.label).join(', ') || 'none'})`);
    proc.setParamValue(c.address, +v);
  }
  // faustwasm 0.18.5 (pinned): a poly DSP's compute(inputs, outputs, events) applies {frame, apply} at its frame in the
  // block. A note takes its voice as the DSP's keyOn would (getFreeVoice) and its key-off releases that voice: the DSP's
  // keyOff goes by pitch and would release the oldest voice of it, another note's when two of one pitch overlap
  const dsp = proc.fDSPCode, B = 128, ev = [];
  for (const n of notes) {
    const on = Math.round(n.start * rate);
    let v;
    ev.push({at: on, off: 0, apply: () => { v = dsp.fVoiceTable[dsp.getFreeVoice()]; v.keyOn(n.note, n.velocity) }},
            {at: Math.max(on + 1, Math.round((n.start + n.length) * rate)), off: 1, apply: () => v.keyOff()});
  }
  ev.sort((a, b) => a.at - b.at || b.off - a.off);
  const total = Math.max(1, Math.round((seconds ?? Math.max(...notes.map(n => n.start + n.length)) + tail) * rate));
  const ins = Array.from({length: dsp.getNumInputs()}, () => new Float32Array(B));
  const outs = Array.from({length: dsp.getNumOutputs()}, () => new Float32Array(B));
  const channels = outs.map(() => new Float32Array(total));
  dsp.start();
  for (let at = 0, k = 0; at < total; at += B) {
    const evs = [];
    while (k < ev.length && ev[k].at < at + B) { const e = ev[k++]; evs.push({frame: e.at - at, apply: e.apply}) }
    dsp.compute(ins, outs, evs);
    outs.forEach((o, c) => channels[c].set(o.subarray(0, Math.min(B, total - at)), at));
  }
  return {channels, controls: cs};
}

if (isNode) {
  const {pathToFileURL} = await import('url');
  if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
    const fs = await import('fs');
    const [base, jobFile, outFile] = process.argv.slice(2);
    try {
      const job = JSON.parse(fs.readFileSync(jobFile, 'utf8'));
      const F = await loadFaust(base);
      // a job is notes (and seconds), or one note: hz, velocity, held for hold, then tail
      const one = !job.notes, hold = job.hold ?? 1;
      const notes = job.notes || [{note: 69 + 12 * Math.log2((job.hz || 261.6256) / 440), start: 0, length: hold, velocity: job.velocity ?? 100}];
      const {channels, controls: cs} = await renderNotes(await compileFaust(F, job.code),
                                                         {...job, notes, seconds: one ? hold + (job.tail ?? 0.5) : job.seconds});
      const n = channels[0] ? channels[0].length : 0, inter = new Float32Array(n * channels.length);
      channels.forEach((ch, c) => { for (let i = 0; i < n; i++) inter[i * channels.length + c] = ch[i] });
      fs.writeFileSync(outFile, Buffer.from(inter.buffer));
      console.log(JSON.stringify({channels: channels.length, frames: n, controls: cs, version: F.version}));
    } catch (e) {
      console.log(JSON.stringify({error: String(e && e.message || e)}));
      process.exitCode = 1;
    }
  }
}
