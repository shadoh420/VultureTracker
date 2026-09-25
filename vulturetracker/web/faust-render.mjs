// Faust code compiled and rendered offline with faustwasm (GRAME's Faust compiler as WebAssembly, LGPL-3.0, fetched on
// demand into the faustwasm folder, never shipped): in node for sample recipes (`faust:`, vulturetracker/faust.py) and in
// the page for the FAUST tab. One note: a "freq" control is set to the note's pitch, "gain" to the velocity, a "gate"
// button is held for `hold` seconds and released for `tail`; other controls by their label (params).
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

// the DSP's controls: [{address, label, type, init, min, max, step}]
export function controls(proc) {
  const out = [];
  const walk = items => items.forEach(it => {
    if (it.items) walk(it.items);
    else if (it.address) out.push({address: it.address, label: it.label, type: it.type, init: it.init ?? 0,
                                   min: it.min ?? 0, max: it.max ?? 1, step: it.step ?? 0});
  });
  walk(proc.getUI());
  return out;
}

export async function compileFaust(F, code, rate = 44100) {
  const gen = new F.lib.FaustMonoDspGenerator();
  try {
    await gen.compile(F.compiler, 'vt', code, '-ftz 2');
  } catch (e) {
    throw new Error(String(F.compiler.getErrorMessage() || e.message || e).trim());
  }
  const proc = await gen.createOfflineProcessor(rate, 128);
  if (!proc) throw new Error(String(F.compiler.getErrorMessage() || 'the Faust code did not compile').trim());
  return proc;
}

// one note: returns {channels: Float32Array[], controls}
export function renderNote(proc, {hz = 261.6256, velocity = 100, hold = 1, tail = 0.5, params = {}, rate = 44100} = {}) {
  const cs = controls(proc), find = name => cs.find(c => c.label.toLowerCase() === String(name).toLowerCase() || c.address === name);
  for (const c of cs) proc.setParamValue(c.address, c.init);
  const set = (name, v) => { const c = find(name); if (c) proc.setParamValue(c.address, v); return !!c };
  set('freq', hz);
  set('gain', velocity / 127);
  for (const [k, v] of Object.entries(params)) if (!set(k, +v)) throw new Error(`the Faust code has no control named "${k}" (it has: ${cs.map(c => c.label).join(', ') || 'none'})`);
  const gate = find('gate');
  if (gate) proc.setParamValue(gate.address, 1);
  const a = proc.render(undefined, Math.max(1, Math.round(hold * rate)));
  if (gate) proc.setParamValue(gate.address, 0);
  const b = proc.render(undefined, Math.max(0, Math.round(tail * rate)));
  const channels = a.map((ch, i) => { const out = new Float32Array(ch.length + (b[i] ? b[i].length : 0)); out.set(ch); if (b[i]) out.set(b[i], ch.length); return out });
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
      const proc = await compileFaust(F, job.code, job.rate || 44100);
      const {channels, controls: cs} = renderNote(proc, job);
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
