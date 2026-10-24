// The live engine's AudioWorklet processor. The server serves /engine-worklet.js as the libopenmpt glue wrapped in
// loadGlue(), then engine-core.js, then this file. The page passes the wasm bytes in processorOptions and talks over the
// port: load (module bytes, optionally at an order/row: an edit swaps the module where it plays), play (from an order/row),
// stop, mute, loop (a span of [order, row] .. [order, row], module order indices, `to` inclusive; null: the song loops
// whole), note / noteoff (a preview: on the playing song, or on a copy with every channel muted while stopped), tempo,
// metro (a click on every beat row while the song plays, higher on the bar's first row: {on, beat, bar} in rows), chvol /
// chpan (a fader as it moves: a channel's volume 0-1 or pan -1..1 at once; the swap its release brings makes it exact).
// Every 4 render quanta it posts the position and each channel's VU. Native seeks and loop preparation create fresh
// paired replay state; rendering reuses scratch buffers. The preview copy renders only while a preview note sounds.

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
const QUIET = 0.3;  // seconds of silence after its last held note that put the preview copy to sleep
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
    this.loopReplay = null;
    this.factor = 1;
    this.practice = null;
    this.countIn = null;
    this.metroFrames = null;
    this.sL = new Float32Array(4096);  // scratch for renders that are dropped or mixed in
    this.sR = new Float32Array(4096);
    this.held = new Set();   // preview channels whose key is down
    this.previewQuiet = -1;  // frames of silence from the preview since its last held note; -1: asleep
    this.port.onmessage = e => this.command(e.data);
    loadOpenmpt(loadGlue, options.processorOptions.wasm).then(E => {
      this.E = E;
      this.port.postMessage({type: 'ready', version: E.version, rate: sampleRate});
    }, err => this.port.postMessage({type: 'error', text: 'libopenmpt: ' + (err && err.message || err)}));
  }

  command(m) {
    try {
      if (m.type === 'load') {
        this.clearLoopReplay();
        const bytes = new Uint8Array(m.bytes), old = this.song, keep = m.keep && old;
        const pending = this.pending?.native ? this.pending : null;
        let song = null, preview = null, target = 0, time = null;
        try {
          song = new this.E.Song(bytes, m.plan ?? null, this.factor);
          song.revision = m.revision;
          preview = new this.E.Song(bytes);
          const gain = m.gain ?? 1;
          if (!Number.isFinite(gain) || gain < 0) throw new Error('Invalid playback output gain');
          song.outputGain = gain;
          // This copy can precede the pending transport's takeover.
          preview.outputGain = gain;
          if (song.score && song.score.rate !== sampleRate) throw new Error('Native score plan must use the AudioContext sample rate');
          if (song.score) {
            this.scoreLoop(song);
            time = keep && pending && !pending.follow ? pending.time :
              keep && old.score ? old.scoreTimeAt(Math.min(old.score.frame, old.score.end)) :
              !keep ? song.scoreTimeAtRow(m.order ?? 0, m.row ?? 0) : null;
            target = time ? song.scoreFrameAtTime(time, {clamp: true}) :
              keep ? (old.score ? song.scoreFrameFrom(old, Math.min(old.score.frame, old.score.end)) :
              Math.min(song.score.end, Math.round(old.position().seconds * sampleRate))) :
              song.scoreFrameAt(m.order ?? 0, m.row ?? 0);
          }
        } catch (err) {  // the first one is freed when the second fails, or it would stay in the wasm heap
          if (song) song.free();
          if (preview) preview.free();
          throw err;
        }
        this.loadId = m.id;
        for (let c = 0; c < preview.channels; c++) preview.mute(c, true);
        for (const c of m.muted || []) song.mute(c, true);
        if (this.preview) this.preview.free();
        this.preview = preview;
        this.held.clear();
        this.previewQuiet = -1;
        if (this.pending) this.pending.song.free();
        this.pending = null;
        if (song.score) {
          this.stageScore(song, target, m.id, !!keep && (pending ? pending.follow : this.playing),
                          keep && pending ? pending.play : this.playing, time);
        } else if (keep && this.factor === 1) {
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
          while (skip > 0) { const got = song.read(sampleRate, Math.min(4096, skip), this.sL, this.sR); if (!got) break; skip -= got }
          this.take(song);
        } else {
          if (m.order != null) song.seek(m.order, m.row);
          this.take(song);
        }
      } else if (m.type === 'play') {
        const source = this.pending?.song || this.song;
        if (m.countIn) {
          const frames = m.countIn;
          if (!source?.score || !Array.isArray(frames) || frames.length < 2 || frames.length > 65 ||
              frames[0] !== 0 || frames.some((n, i) => !Number.isSafeInteger(n) || n < 0 || n > sampleRate * 600 || i && n <= frames[i - 1]))
            throw new Error('Invalid native count-in frame boundaries');
          this.countIn = {frames, elapsed:0, next:0};
        } else if (m.order != null) this.countIn = null;
        if (source?.score) {
          if (m.order != null) {
            const target = source.scoreFrameAt(m.order, m.row ?? 0), replay = source.fresh();
            this.clearLoopReplay();
            const id = this.pending?.id ?? this.loadId;
            if (this.pending) this.pending.song.free();
            this.playing = false;
            this.stageScore(replay, target, id, false, true, replay.scoreTimeAtRow(m.order, m.row ?? 0));
          } else if (this.pending) this.pending.play = true;
          else this.playing = true;
          this.lastRow = null;
          return;
        }
        if (this.pending) { const {song: s, id} = this.pending; this.pending = null; this.take(s, id) }
        if (m.order != null) this.song.seek(m.order, m.row);
        this.playing = true;
        this.lastRow = null;
      } else if (m.type === 'metro') {
        this.metro = m.on ? m : null;
        this.metroFrames = null;
      } else if (m.type === 'practice') {
        if (m.config && (!(this.pending?.song || this.song)?.score ||
            !['from', 'to', 'step'].every(k => Number.isInteger(m.config[k])) ||
            m.config.from < 10 || m.config.to > 200 || m.config.from > m.config.to || m.config.step < 1 || m.config.step > 100))
          throw new Error('Practice needs a native score and 10–200% increasing tempo bounds');
        this.practice = m.config ? {...m.config, percent:m.config.from, pass:1} : null;
        this.clearLoopReplay();
      } else if (m.type === 'stop') {
        this.playing = false;
        if (!m.pause) { this.countIn = null; this.practice = null; }
        this.click = null;
        if (this.pending?.native) { this.pending.play = false; this.pending.follow = false; }
        else if (this.pending?.resume != null) this.pending.resume = false;
      } else if (m.type === 'mute') {
        this.clearLoopReplay();
        this.song?.mute(m.ch, m.on);
        if (this.pending) this.pending.song.mute(m.ch, m.on);
        this.loopReplay?.song.mute(m.ch, m.on);
      } else if (m.type === 'chvol' || m.type === 'chpan') {
        this.clearLoopReplay();
        for (const s of [this.song, this.pending && this.pending.song, this.loopReplay?.song])
          if (s && m.ch < s.channels) m.type === 'chvol' ? s.channelVolume(m.ch, m.value) : s.channelPan(m.ch, m.value);
      } else if (m.type === 'loop') {
        for (const s of [this.song, this.pending?.song]) if (s?.score) this.scoreLoop(s, m.span);
        this.loop = m.span;
        this.clearLoopReplay();
      } else if (m.type === 'tempo') {
        this.practice = null;
        this.clearLoopReplay();
        const q = this.E.factorQ(m.factor), source = this.pending?.song || this.song;
        if (source?.score) {
          if (source.factorQ === q) { this.factor = m.factor; return; }
          const candidate = source.fresh(m.factor);
          let target, time;
          try {
            this.scoreLoop(candidate);
            time = this.pending?.time ?? source.scoreTimeAt(Math.min(source.score.frame, source.score.end));
            target = candidate.scoreFrameAtTime(time, {clamp: true});
          } catch (error) { candidate.free(); throw error; }
          const id = this.pending?.id ?? this.loadId,
                follow = this.pending ? this.pending.follow : this.playing,
                play = this.pending ? this.pending.play : this.playing;
          this.pending?.song.free();
          this.pending = null;
          this.clearLoopReplay();
          this.factor = m.factor;
          this.stageScore(candidate, target, id, follow, play, time);
          if (this.pending) this.port.postMessage({type: 'preparing', reason: 'tempo', factorQ: q});
        } else {
          this.song?.tempoFactor(m.factor);
          this.pending?.song.tempoFactor(m.factor);
          this.factor = m.factor;
        }
      } else if (m.type === 'note') {
        const on = this.playing ? 'song' : 'preview', ch = this[on].playNote(m.ins, m.note, m.vol == null ? 1 : m.vol, m.pan || 0);
        if (on === 'preview' && ch >= 0) { this.held.add(ch); this.previewQuiet = 0 }
        this.port.postMessage({type: 'note', id: m.id, ch, on});
      } else if (m.type === 'noteoff') {
        const s = this[m.on];
        if (s && m.ch >= 0) s.noteOff(m.ch);
        if (m.on === 'preview') this.held.delete(m.ch);
      }
    } catch (err) {  // a failed load names its id, so the page's wait for it ends
      this.port.postMessage({type: 'error', id: m && m.type === 'load' ? m.id : undefined, text: String(err && err.message || err)});
    }
  }

  scoreLoop(song, span = this.loop) {
    if (!span) return {from: 0, to: song.score.end};
    const from = span.fromAt ? song.scoreFrameAtTime(span.fromAt.map(BigInt)) : song.scoreFrameAt(...span.from),
          to = span.toAt ? song.scoreFrameAtTime(span.toAt.map(BigInt)) : song.scoreFrameAt(...span.to, {afterRow: true});
    if (to <= from) throw new Error('Native score loop must have a positive duration');
    return {from, to};
  }

  clearLoopReplay() {
    this.loopReplay?.song.free();
    this.loopReplay = null;
    this.song?.clearCheckpoint();
  }

  prepareLoop(max, factor = null) {
    if (!this.song?.score || this.pending && max > 0) return;
    const {from} = this.scoreLoop(this.song);
    const nextFactor = factor ?? (this.practice ? Math.min(this.practice.to, this.practice.percent + this.practice.step) / 100 : this.factor);
    if (this.song.checkpointAvailable && this.E.factorQ(nextFactor) === this.song.factorQ) {
      if (this.song.hasCheckpoint(from)) return;
      if (this.song.score.frame === from) {
        this.song.captureCheckpoint();
        this.loopReplay?.song.free(); this.loopReplay = null;
        return;
      }
    }
    if (!this.loopReplay) {
      const candidate = this.song.fresh(nextFactor);
      this.loopReplay = {song: candidate, target: this.scoreLoop(candidate).from};
    }
    const replay = this.loopReplay;
    replay.ready = replay.song.advanceTo(replay.target, max, this.sL, this.sR);
    if (replay.ready && replay.song.checkpointAvailable && !replay.song.hasCheckpoint(replay.target))
      replay.song.captureCheckpoint();
  }

  // Both streams replay from zero. Each quantum does bounded work; an explicit seek remains paused until ready.
  stageScore(song, target, id, follow, play, time = null) {
    this.pending = {song, id, native: true, target, follow, play, time: time ?? song.scoreTimeAt(target)};
    this.catchUp(0);
  }

  // the pending song renders (silently) up to `max` frames towards the old song's position; there, it takes over
  catchUp(max) {
    const P = this.pending;
    if (P.native) {
      try {
      if (P.follow && this.song) {
        if (this.song.score) {
          P.time = this.song.scoreTimeAt(Math.min(this.song.score.frame, this.song.score.end));
          P.target = P.song.scoreFrameAtTime(P.time, {clamp: true});
        } else {
          P.target = Math.min(P.song.score.end, Math.round(this.song.position().seconds * sampleRate));
          P.time = P.song.scoreTimeAt(P.target);
        }
      }
      if (P.song.score.frame > P.target) {
        const replay = P.song.fresh();
        P.song.free(); P.song = replay;
      }
      if (P.song.advanceTo(P.target, max, this.sL, this.sR)) {
        this.pending = null;
        this.take(P.song, P.id);
        this.playing = P.play;
      }
      } catch (error) {
        this.pending = null;
        P.song.free();
        if (this.song?.score) this.factor = 65536 / this.song.factorQ;
        this.port.postMessage({type: 'error', id: P.id, text: String(error.message || error)});
      }
      return;
    }
    while (P.need > 0 && max > 0) { const got = P.song.read(sampleRate, Math.min(4096, P.need, max), this.sL, this.sR); if (!got) break; P.need -= got; max -= got }
    if (P.need > 0 && max > 0) P.need = 0;  // the song ended first
    if (P.need === 0) {
      this.pending = null; this.take(P.song, P.id);
      if (P.resume != null) this.playing = P.resume;
    }
  }

  // `id`: the load that made the song (the page resolves its wait for that load and every earlier one)
  take(song, id = this.loadId) {
    this.clearLoopReplay();
    if (this.song) this.song.free();
    this.song = song;
    this.metroFrames = null;
    this.port.postMessage({type: 'loaded', id, channels: song.channels, at: song.position()});
  }

  process(inputs, outputs) {
    try { return this.render(inputs, outputs); }
    catch (error) {
      const id = this.pending?.id;
      this.playing = false;
      this.pending?.song.free(); this.pending = null;
      this.clearLoopReplay();
      this.song?.free(); this.song = null;
      this.click = null;
      for (const channel of outputs[0]) channel.fill(0);
      this.port.postMessage({type: 'error', id, fatal: true, text: String(error.message || error)});
      return true; // Keep the processor alive so a newly prepared pair can replace the failed consumer.
    }
  }

  render(inputs, outputs) {
    const out = outputs[0], L = out[0], R = out[1] || out[0], n = L.length;
    L.fill(0);
    R.fill(0);
    if (!this.song && this.pending?.native) this.catchUp(32 * n);
    if (!this.song) return true;
    const before = this.pending && this.song.position().seconds;
    let start = 0;
    if (this.playing && !this.pending && this.countIn) {
      const c = this.countIn;
      while (start < n && c.elapsed < c.frames.at(-1)) {
        if (c.elapsed === c.frames[c.next]) {
          this.click = {n:0, at:start, f:c.next === 0 ? 2000 : 1250};
          this.port.postMessage({type:'countin', beat:c.next + 1, beats:c.frames.length - 1}); c.next++;
        }
        const count = Math.min(n - start, c.frames[c.next] - c.elapsed);
        c.elapsed += count; start += count;
      }
      if (c.elapsed === c.frames.at(-1)) { this.countIn = null; this.port.postMessage({type:'countin', beat:0}); }
    }
    if (this.playing && this.song.score) {
      for (let i = start; i < n;) {
        let bounds = this.scoreLoop(this.song);
        const changing = this.practice && this.practice.percent < this.practice.to;
        if (!changing && this.song.checkpointAvailable && this.song.score.frame === bounds.from &&
            !this.song.hasCheckpoint(bounds.from)) this.song.captureCheckpoint();
        if (this.song.score.frame >= bounds.to || this.song.score.frame < bounds.from) {
          if (this.loop?.once && this.song.score.frame >= bounds.to) {
            this.playing = false; this.practice = null; this.countIn = null; this.click = null;
            this.clearLoopReplay();
            this.port.postMessage({type:'practice-ended'});
            break;
          }
          if (this.practice && this.song.score.frame >= bounds.to) {
            this.practice.percent = Math.min(this.practice.to, this.practice.percent + this.practice.step);
            this.practice.pass++;
            this.factor = this.practice.percent / 100;
            this.port.postMessage({type:'practice', percent:this.practice.percent, pass:this.practice.pass});
          }
          if (!changing && this.song.hasCheckpoint(bounds.from)) {
            this.song.restoreCheckpoint();
            this.lastRow = null;
          } else {
          this.prepareLoop(0, this.factor);
          const replay = this.loopReplay;
          this.loopReplay = null;
          if (!replay?.ready) {
            // A deep, short range may outrun preparation. Freeze both timelines until its destination is ready.
            this.playing = false;
            if (this.pending?.native) {
              replay?.song.free();
              this.pending.target = this.scoreLoop(this.pending.song).from;
              this.pending.time = this.loop?.fromAt?.map(BigInt) ?? this.pending.song.scoreTimeAtRow(...(this.loop?.from ?? [0, 0]));
              this.pending.follow = false; this.pending.play = true;
            } else if (this.pending) {
              // The incoming legacy load still owns its candidate. Pause at the
              // boundary until that replay completes; never replace it with a
              // loop candidate and leak the newer load.
              replay?.song.free();
              this.pending.resume = true;
            } else {
              const candidate = replay?.song || this.song.fresh(this.factor);
              this.stageScore(candidate, this.scoreLoop(candidate).from, this.loadId, false, true,
                              this.loop?.fromAt?.map(BigInt) ?? this.song.scoreTimeAtRow(...(this.loop?.from ?? [0, 0])));
            }
            this.port.postMessage({type: 'preparing', reason: 'loop'});
            break;
          }
          this.song.free(); this.song = replay.song;
          this.metroFrames = null;
          this.lastRow = null;
          }
          bounds = this.scoreLoop(this.song);
        }
        let nextClick = Infinity;
        if (this.metro?.points) {
          if (this.metroFrames?.song !== this.song) this.metroFrames = {song:this.song,
            points:this.metro.points.map(p => ({frame:this.song.scoreFrameAtTime(p.at.map(BigInt)), accent:p.accent}))};
          const points = this.metroFrames.points, frame = this.song.score.frame;
          let low = 0, high = points.length;
          while (low < high) { const mid = (low + high) >> 1; if (points[mid].frame < frame) low = mid + 1; else high = mid; }
          if (points[low]?.frame === frame) {
            this.click = {n:0, at:i, f:points[low].accent ? 2000 : 1250}; low++;
          }
          nextClick = points[low]?.frame ?? Infinity;
        }
        const count = Math.min(n - i, bounds.to - this.song.score.frame, nextClick - this.song.score.frame,
                              this.metro && !this.metro.points ? 32 : n);
        this.song.read(sampleRate, count, L, R, false, i);
        i += count;
        const p = this.song.position(), at = p.order * 1024 + p.row;
        if (this.metro && !this.metro.points && at !== this.lastRow) {
          this.lastRow = at;
          if (p.row % this.metro.beat === 0) this.click = {n: 0, at: i, f: p.row % this.metro.bar === 0 ? 2000 : 1250};
        }
      }
    } else if (this.playing && !this.loop && !this.metro) this.song.read(sampleRate, n, L, R);
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
    if (this.song.outputGain !== 1) for (let i = 0; i < n; i++) { L[i] *= this.song.outputGain; R[i] *= this.song.outputGain; }
    if (this.playing && this.song.score && !this.pending && !this.loop?.once) this.prepareLoop(32 * n);
    if (this.pending) {
      if (this.pending.native) this.catchUp(32 * n);
      else {
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
    if (this.previewQuiet >= 0) {  // a preview note sounds, or did within QUIET seconds: mix the preview copy in
      const got = this.preview.read(sampleRate, n, this.sL, this.sR), a = this.sL, b = this.sR, gain = this.preview.outputGain;
      let peak = 0;
      for (let i = 0; i < got; i++) { L[i] += a[i] * gain; R[i] += b[i] * gain; peak = Math.max(peak, Math.abs(a[i]), Math.abs(b[i])) }
      this.previewQuiet = this.held.size || peak > 1e-5 ? 0 : this.previewQuiet + n;
      if (this.previewQuiet > QUIET * sampleRate) this.previewQuiet = -1;
    }
    if (++this.quanta % 4 === 0) {
      const p = this.song.position();
      this.port.postMessage({type: 'pos', ...p, playing: this.playing, vu: this.song.vu(), frame: currentFrame});
    }
    return true;
  }
}
registerProcessor('vt-engine', VTEngine);
