// The live engine's core: libopenmpt compiled to WebAssembly (web/libopenmpt.js + .wasm, the official 0.8.9 build) behind a
// small API. Used inside the AudioWorklet (engine-worklet.js) and by the node check (tests/engine_check.js). The glue does
// not export the heap views or the function table, so both come from the wasm instance (instantiateWasm hook); the
// interactive interface (mute, play_note, note_off) is a struct of function pointers, called through that table.
function openmptEngine(M, memory, table) {
  const u8 = () => new Uint8Array(memory.buffer), f32 = () => new Float32Array(memory.buffer), i32 = () => new Int32Array(memory.buffer);
  function cstr(s) {
    const p = M._malloc(s.length + 1), h = u8();
    for (let i = 0; i < s.length; i++) h[p + i] = s.charCodeAt(i);
    h[p + s.length] = 0;
    return p;
  }
  // openmpt_module_ext_get_interface fills a struct of `n` function pointers (4 bytes each in wasm32)
  function iface(ext, name, n) {
    const p = M._malloc(4 * n), s = cstr(name), ok = M._openmpt_module_ext_get_interface(ext, s, p, 4 * n);
    const fns = ok ? Array.from(i32().subarray(p >> 2, (p >> 2) + n), f => table.get(f)) : null;
    M._free(s);
    M._free(p);
    if (!fns) throw new Error(`libopenmpt has no "${name}" interface`);
    return fns;
  }
  const MAXN = 4096;
  class Song {
    // one loaded module; `bytes` a Uint8Array of the .it. Mixed like the app's renders: the 8-tap interpolation filter.
    constructor(bytes) {
      const p = M._malloc(bytes.length);
      u8().set(bytes, p);
      this.ext = M._openmpt_module_ext_create_from_memory(p, bytes.length, 0, 0, 0, 0, 0, 0, 0);
      M._free(p);
      if (!this.ext) throw new Error('libopenmpt could not load the module');
      this.mod = M._openmpt_module_ext_get_module(this.ext);
      const a = iface(this.ext, 'interactive', 16), b = iface(this.ext, 'interactive2', 6);
      this.fn = {tempoFactor: a[2], channelVolume: a[8], mute: a[10], muted: a[11], playNote: a[14], stopNote: a[15],
                 noteOff: b[0], noteFade: b[1]};
      M._openmpt_module_set_render_param(this.mod, 3, 8);  // OPENMPT_MODULE_RENDER_INTERPOLATIONFILTER_LENGTH
      M._openmpt_module_set_repeat_count(this.mod, -1);    // the song loops until stopped
      this.channels = M._openmpt_module_get_num_channels(this.mod);
      this.bufL = M._malloc(4 * MAXN);
      this.bufR = M._malloc(4 * MAXN);
    }
    // render n frames (n <= 4096) at `rate` into Float32Arrays L and R from index `at`; `add` mixes into them instead.
    // Returns frames rendered.
    read(rate, n, L, R, add, at = 0) {
      const got = M._openmpt_module_read_float_stereo(this.mod, rate, n, this.bufL, this.bufR), f = f32();
      const l = f.subarray(this.bufL >> 2, (this.bufL >> 2) + got), r = f.subarray(this.bufR >> 2, (this.bufR >> 2) + got);
      if (add) for (let i = 0; i < got; i++) { L[at + i] += l[i]; R[at + i] += r[i] }
      else { L.set(l, at); R.set(r, at) }
      return got;
    }
    seek(order, row) { return M._openmpt_module_set_position_order_row(this.mod, order, row || 0) }
    position() {
      return {order: M._openmpt_module_get_current_order(this.mod), row: M._openmpt_module_get_current_row(this.mod),
              seconds: M._openmpt_module_get_position_seconds(this.mod)};
    }
    vu() { const v = []; for (let c = 0; c < this.channels; c++) v.push(M._openmpt_module_get_current_channel_vu_mono(this.mod, c)); return v }
    mute(ch, on) { return this.fn.mute(this.ext, ch, on ? 1 : 0) }
    muted(ch) { return !!this.fn.muted(this.ext, ch) }
    // instrument 0-based (sample, in a module without instruments); note 0-119, 60 = C-5; returns the channel or -1
    playNote(ins, note, vol = 1, pan = 0) { return this.fn.playNote(this.ext, ins, note, vol, pan) }
    noteOff(ch) { return this.fn.noteOff(this.ext, ch) }
    stopNote(ch) { return this.fn.stopNote(this.ext, ch) }
    tempoFactor(f) { return this.fn.tempoFactor(this.ext, f) }
    free() {
      M._openmpt_module_ext_destroy(this.ext);
      M._free(this.bufL);
      M._free(this.bufR);
      this.ext = this.mod = 0;
    }
  }
  const vp = M._openmpt_get_string(cstr('library_version'));
  let version = '';
  for (let h = u8(), i = vp; h[i]; i++) version += String.fromCharCode(h[i]);
  return {Song, version, MAXN};
}

// Load the glue (a classic script whose `Module` reads the `libopenmpt` object it finds in scope) with the wasm bytes given,
// capturing the instance's memory and table. `glue` is a function(libopenmpt, require, __dirname) wrapping the glue text.
function loadOpenmpt(glue, wasmBytes, extra) {
  return new Promise((resolve, reject) => {
    let memory, table;
    const M = glue(Object.assign({
      instantiateWasm(imports, done) {
        WebAssembly.instantiate(wasmBytes, imports).then(({instance}) => {
          for (const v of Object.values(instance.exports)) {
            if (v instanceof WebAssembly.Memory) memory = v;
            if (v instanceof WebAssembly.Table) table = v;
          }
          done(instance);
        }, reject);
        return {};
      },
      onRuntimeInitialized() { try { resolve(openmptEngine(M, memory, table)) } catch (e) { reject(e) } },
      print() {}, printErr() {},
    }, extra || {}));
  });
}
if (typeof module !== 'undefined') module.exports = {openmptEngine, loadOpenmpt};
