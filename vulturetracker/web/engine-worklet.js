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
const PRE = 4;   // seconds a swapped-in song plays silently before it takes over (see load)
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
    this.pending = null;
    this.factor = 1;
    this.port.onmessage = e => this.command(e.data);
    loadOpenmpt(loadGlue, options.processorOptions.wasm).then(E => {
      this.E = E;
      this.port.postMessage({type: 'ready', version: E.version, rate: sampleRate});
    }, err => this.port.postMessage({type: 'error', text: 'libopenmpt: ' + (err && err.message || err)}));
  }

  command(m) {
    try {
      if (m.type === 'load') {
        const bytes = new Uint8Array(m.bytes), old = this.song, keep = m.keep && old;
        let song = null, preview = null;
        try {
          song = new this.E.Song(bytes);
          preview = new this.E.Song(bytes);
        } catch (err) {  // the first one is freed when the second fails, or it would stay in the wasm heap
          if (song) song.free();
          throw err;
        }
        this.loadId = m.id;
        for (let c = 0; c < preview.channels; c++) preview.mute(c, true);
        for (const c of m.muted || []) song.mute(c, true);
        if (this.factor !== 1) song.tempoFactor(this.factor);
        if (this.preview) this.preview.free();
        this.preview = preview;
        if (this.pending) this.pending.song.free();
        this.pending = null;
        if (keep && this.factor === 1) {
          // the swapped-in song starts PRE seconds back and plays that part silently, a few quanta's worth per quantum,
          // while the old one goes on; it takes over on the frame the old one has reached. A seek straight to the row
          // would give each channel its current note but drop the voices still fading from earlier notes (a pad's
          // tail under its next note's attack: the pad dipped by 12 dB for a second after an edit). A tail longer than PRE
          // is still cut. Only at speed 100 %: with a tempo factor libopenmpt's seconds run at real time, its seek by
          // seconds does not
          const t = old.position().seconds;
          song.seekSeconds(Math.max(0, t - PRE));
          this.pending = {song, id: m.id, need: Math.max(0, Math.round((t - song.position().seconds) * sampleRate))};
          if (!this.playing) this.catchUp(Infinity);
        } else if (keep) {
          // a seek lands on the start of the row: the part of the row already played is rendered again and dropped, so
          // the swapped-in song goes on from the same frame instead of repeating it (up to a row: 91 ms at tempo 110 speed 4)
          const at = old.position();
          old.seek(at.order, at.row);
          let skip = Math.max(0, Math.round((at.seconds - old.position().seconds) * sampleRate));
          song.seek(at.order, at.row);
          const L = new Float32Array(4096), R = new Float32Array(4096);
          while (skip > 0) { const got = song.read(sampleRate, Math.min(4096, skip), L, R); if (!got) break; skip -= got }
          this.take(song);
        } else {
          if (m.order != null) song.seek(m.order, m.row);
          this.take(song);
        }
      } else if (m.type === 'play') {
        if (this.pending) { const {song: s, id} = this.pending; this.pending = null; this.take(s, id) }
        if (m.order != null) this.song.seek(m.order, m.row);
        this.playing = true;
        this.lastRow = null;
      } else if (m.type === 'metro') {
        this.metro = m.on ? m : null;
      } else if (m.type === 'stop') {
        this.playing = false;
      } else if (m.type === 'mute') {
        this.song.mute(m.ch, m.on);
        if (this.pending) this.pending.song.mute(m.ch, m.on);
      } else if (m.type === 'loop') {
        this.loop = m.span;
      } else if (m.type === 'tempo') {
        this.factor = m.factor;
        this.song.tempoFactor(m.factor);
        if (this.pending) this.pending.song.tempoFactor(m.factor);
      } else if (m.type === 'note') {
        const on = this.playing ? 'song' : 'preview', ch = this[on].playNote(m.ins, m.note, m.vol == null ? 1 : m.vol, m.pan || 0);
        this.port.postMessage({type: 'note', id: m.id, ch, on});
      } else if (m.type === 'noteoff') {
        const s = this[m.on];
        if (s && m.ch >= 0) s.noteOff(m.ch);
      }
    } catch (err) {  // a failed load names its id, so the page's wait for it ends
      this.port.postMessage({type: 'error', id: m && m.type === 'load' ? m.id : undefined, text: String(err && err.message || err)});
    }
  }

  // the pending song renders (silently) up to `max` frames towards the old song's position; there, it takes over
  catchUp(max) {
    const P = this.pending, L = new Float32Array(4096), R = new Float32Array(4096);
    while (P.need > 0 && max > 0) { const got = P.song.read(sampleRate, Math.min(4096, P.need, max), L, R); if (!got) break; P.need -= got; max -= got }
    if (P.need > 0 && max > 0) P.need = 0;  // the song ended first
    if (P.need === 0) { this.pending = null; this.take(P.song, P.id) }
  }

  // `id`: the load that made the song (the page resolves its wait for that load and every earlier one)
  take(song, id = this.loadId) {
    if (this.song) this.song.free();
    this.song = song;
    this.port.postMessage({type: 'loaded', id, channels: song.channels, at: song.position()});
  }

  process(inputs, outputs) {
    const out = outputs[0], L = out[0], R = out[1] || out[0], n = L.length;
    L.fill(0);
    R.fill(0);
    if (!this.song) return true;
    const before = this.pending && this.song.position().seconds;
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
    if (this.pending) {
      const dt = this.song.position().seconds - before;
      if (dt < 0 || dt > 2 * n / sampleRate) {   // the old song jumped (a loop): the new one seeks there instead
        const p = this.song.position(), s = this.pending.song, id = this.pending.id;
        this.pending = null;
        s.seek(p.order, p.row);
        this.take(s, id);
      } else {
        if (this.playing) this.pending.need += n;
        this.catchUp(32 * n);
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
