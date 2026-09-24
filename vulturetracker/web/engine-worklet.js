// The live engine's AudioWorklet processor. The server serves /engine-worklet.js as the libopenmpt glue wrapped in
// loadGlue(), then engine-core.js, then this file. The page passes the wasm bytes in processorOptions and talks over the
// port: load (module bytes, optionally at an order/row: an edit swaps the module where it plays), play (from an order/row),
// stop, mute, loop (a span of [order, row] .. [order, row], module order indices, `to` inclusive; null: the song loops
// whole), note / noteoff (a preview: on the playing song, or on a copy with every channel muted while stopped), tempo,
// metro (a click on every beat row while the song plays, higher on the bar's first row: {on, beat, bar} in rows).
// Every 4 render quanta it posts the position and each channel's VU.

// an AudioWorkletGlobalScope has no performance clock (the glue's emscripten_get_now): the audio clock stands in
if (typeof performance === 'undefined') globalThis.performance = {now: () => currentTime * 1000};
// nor crypto, which seeds libopenmpt's random generator (random volume and pan): Math.random is enough for that
if (typeof crypto === 'undefined') {
  globalThis.crypto = {getRandomValues(a) {
    const b = new Uint8Array(a.buffer, a.byteOffset, a.byteLength);
    for (let i = 0; i < b.length; i++) b[i] = Math.random() * 256;
    return a;
  }};
}
// nor a TextDecoder, which the glue uses for C strings: a UTF-8 decoder for it
if (typeof TextDecoder === 'undefined') {
  globalThis.TextDecoder = class {
    decode(b) {
      let s = '';
      b = b || new Uint8Array(0);
      for (let i = 0; i < b.length;) {
        let c = b[i++];
        if (c > 0x7f) {
          const n = c >= 0xf0 ? 3 : c >= 0xe0 ? 2 : 1;
          c &= 0x3f >> n;
          for (let k = 0; k < n; k++) c = (c << 6) | (b[i++] & 0x3f);
        }
        s += String.fromCodePoint(c);
      }
      return s;
    }
  };
}
class VTEngine extends AudioWorkletProcessor {
  constructor(options) {
    super();
    this.E = null;
    this.song = null;
    this.preview = null;
    this.playing = false;
    this.quanta = 0;
    this.loop = null;
    this.metro = null;
    this.click = null;
    this.lastRow = null;
    this.port.onmessage = e => this.command(e.data);
    loadOpenmpt(loadGlue, options.processorOptions.wasm).then(E => {
      this.E = E;
      this.port.postMessage({type: 'ready', version: E.version, rate: sampleRate});
    }, err => this.port.postMessage({type: 'error', text: 'libopenmpt: ' + (err && err.message || err)}));
  }

  command(m) {
    try {
      if (m.type === 'load') {
        const bytes = new Uint8Array(m.bytes), old = this.song, at = m.keep && old ? old.position() : null;
        const song = new this.E.Song(bytes), preview = new this.E.Song(bytes);
        for (let c = 0; c < preview.channels; c++) preview.mute(c, true);
        if (at) song.seek(at.order, at.row);
        else if (m.order != null) song.seek(m.order, m.row);
        for (const c of m.muted || []) song.mute(c, true);
        this.song = song;
        if (old) old.free();
        if (this.preview) this.preview.free();
        this.preview = preview;
        this.port.postMessage({type: 'loaded', channels: song.channels, at: song.position()});
      } else if (m.type === 'play') {
        if (m.order != null) this.song.seek(m.order, m.row);
        this.playing = true;
        this.lastRow = null;
      } else if (m.type === 'metro') {
        this.metro = m.on ? m : null;
      } else if (m.type === 'stop') {
        this.playing = false;
      } else if (m.type === 'mute') {
        this.song.mute(m.ch, m.on);
      } else if (m.type === 'loop') {
        this.loop = m.span;
      } else if (m.type === 'tempo') {
        this.song.tempoFactor(m.factor);
      } else if (m.type === 'note') {
        const on = this.playing ? 'song' : 'preview', ch = this[on].playNote(m.ins, m.note, m.vol == null ? 1 : m.vol, m.pan || 0);
        this.port.postMessage({type: 'note', id: m.id, ch, on});
      } else if (m.type === 'noteoff') {
        const s = this[m.on];
        if (s && m.ch >= 0) s.noteOff(m.ch);
      }
    } catch (err) {
      this.port.postMessage({type: 'error', text: String(err && err.message || err)});
    }
  }

  process(inputs, outputs) {
    const out = outputs[0], L = out[0], R = out[1] || out[0], n = L.length;
    L.fill(0);
    R.fill(0);
    if (!this.song) return true;
    if (this.playing && !this.loop && !this.metro) this.song.read(sampleRate, n, L, R);
    else if (this.playing) {  // in steps of 32 frames: past the loop's end (or before its start) it jumps back, and a new
      // beat row starts a click, each within 0.7 ms
      const cmp = (o, r, x) => o - x[0] || r - x[1];
      for (let i = 0; i < n; i += 32) {
        this.song.read(sampleRate, Math.min(32, n - i), L, R, false, i);
        let p = this.song.position();
        if (this.loop && (cmp(p.order, p.row, this.loop.to) > 0 || cmp(p.order, p.row, this.loop.from) < 0)) {
          this.song.seek(this.loop.from[0], this.loop.from[1]);
          p = this.song.position();
        }
        const at = p.order * 1024 + p.row;
        if (this.metro && at !== this.lastRow) {
          this.lastRow = at;
          if (p.row % this.metro.beat === 0) this.click = {n: 0, at: Math.min(n, i + 32), f: p.row % this.metro.bar === 0 ? 2000 : 1250};
        }
      }
    }
    if (this.click) {  // 30 ms of a decaying sine
      const c = this.click, len = 0.03 * sampleRate;
      for (let j = c.at; j < n && c.n < len; j++, c.n++) {
        const v = 0.25 * Math.exp(-c.n / (0.006 * sampleRate)) * Math.sin(2 * Math.PI * c.f * c.n / sampleRate);
        L[j] += v;
        R[j] += v;
      }
      c.at = 0;
      if (c.n >= len) this.click = null;
    }
    this.preview.read(sampleRate, n, L, R, true);
    if (++this.quanta % 4 === 0) {
      const p = this.song.position();
      this.port.postMessage({type: 'pos', order: p.order, row: p.row, seconds: p.seconds, playing: this.playing, vu: this.song.vu(), frame: currentFrame});
    }
    return true;
  }
}
registerProcessor('vt-engine', VTEngine);
