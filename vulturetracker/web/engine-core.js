// The live engine's core: libopenmpt compiled to WebAssembly (web/libopenmpt.js + .wasm, the patched 0.8.9 build) behind a
// small API. Used inside the AudioWorklet (engine-worklet.js) and by the node check (tests/engine_check.js). The glue does
// not export the heap views or the function table, so both come from the wasm instance (instantiateWasm hook); the
// interactive interface (mute, play_note, note_off) is a struct of function pointers, called through that table.
// One rational clock for worklet scheduling, replay and TAB highlighting.
// Tempo changes stay in musical coordinates; round only the absolute frame.
function nativeScoreClock(plan) {
  if (!Number.isSafeInteger(plan.tempo) || plan.tempo <= 0) throw new Error('Invalid native score tempo');
  const reduce = (n, d) => { let a = n < 0n ? -n : n, b = d; while (b) [a, b] = [b, a % b]; return [n / a, d / a]; };
  const pair = p => {
    if (!Array.isArray(p) || p.length !== 2 || p.some(v => typeof v !== 'bigint' && !Number.isSafeInteger(v)))
      throw new Error('Invalid native score clock coordinate');
    const [n, d] = p.map(BigInt);
    if (n < 0n || d <= 0n) throw new Error('Invalid native score clock coordinate');
    return reduce(n, d);
  };
  const add = (a, b) => reduce(a[0] * b[1] + b[0] * a[1], a[1] * b[1]);
  const sub = (a, b) => reduce(a[0] * b[1] - b[0] * a[1], a[1] * b[1]);
  const mul = (a, n, d = 1n) => reduce(a[0] * n, a[1] * d);
  const cmp = (a, b) => a[0] * b[1] - b[0] * a[1];
  const hasMap = Object.hasOwn(plan, 'tempos');
  const source = hasMap ? plan.tempos : [{at: [0, 1], bpm: plan.tempo}];
  if (!Array.isArray(source) || !source.length || source.length > 200000) throw new Error('Invalid native tempo map');
  const points = source.map(p => {
    if (!p || !Number.isSafeInteger(p.bpm) || p.bpm <= 0 || (hasMap && (p.bpm < 32 || p.bpm > 255)))
      throw new Error('Invalid native score tempo');
    return {at: pair(p.at), bpm: BigInt(p.bpm), seconds: [0n, 1n]};
  });
  if (points[0].at[0] !== 0n) throw new Error('Native tempo map must start at zero');
  for (let i = 1; i < points.length; i++) {
    const p = points[i - 1], next = points[i];
    if (cmp(next.at, p.at) <= 0n) throw new Error('Native tempo map must increase strictly');
    next.seconds = add(p.seconds, mul(sub(next.at, p.at), 60n, p.bpm));
  }
  function segment(value, field) {
    let lo = 0, hi = points.length;
    while (lo + 1 < hi) { const mid = (lo + hi) >> 1; if (cmp(points[mid][field], value) <= 0n) lo = mid; else hi = mid; }
    return points[lo];
  }
  const secondsAt = at => { at = pair(at); const p = segment(at, 'at'); return add(p.seconds, mul(sub(at, p.at), 60n, p.bpm)); };
  const quartersAt = seconds => { seconds = pair(seconds); const p = segment(seconds, 'seconds'); return add(p.at, mul(sub(seconds, p.seconds), p.bpm, 60n)); };
  const scale = (rate, q) => {
    if (!Number.isSafeInteger(rate) || rate <= 0 || !Number.isSafeInteger(q) || q <= 0) throw new Error('Invalid native clock scale');
    return BigInt(rate) * BigInt(q);
  };
  return {
    secondsAt, quartersAt,
    frameAt(at, rate, q = 65536) {
      const [n, d] = mul(secondsAt(at), scale(rate, q), 65536n);
      const frame = Number((2n * n + d) / (2n * d));
      if (!Number.isSafeInteger(frame)) throw new Error('Native score frame exceeds safe integer range');
      return frame;
    },
    timeAtFrame(frame, rate, q = 65536) {
      if (!Number.isSafeInteger(frame) || frame < 0) throw new Error('Invalid native score frame');
      return quartersAt([BigInt(frame) * 65536n, scale(rate, q)]);
    }
  };
}

function openmptEngine(M, memory, table) {
  const u8 = () => new Uint8Array(memory.buffer), f32 = () => new Float32Array(memory.buffer), i32 = () => new Int32Array(memory.buffer), i64 = () => new BigInt64Array(memory.buffer);
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
  function factorQ(f) {
    if (typeof f !== 'number' || !Number.isFinite(f) || f <= 0 || f > 4)
      throw new Error('Tempo factor must be finite and greater than 0 through 4');
    return Math.min(0xffffffff, Math.floor(65536 / f + 0.5));
  }
  function fraction(p) {
    if (!Array.isArray(p) || p.length !== 2 || !p.every(Number.isSafeInteger) || p[0] < 0 || p[1] <= 0)
      throw new Error('Invalid native score coordinate');
    return p.map(BigInt);
  }
  const eventRank = {note_off: 0, note_on: 1, pitch: 2, gain: 3};
  function scorePlan(plan) {
    const integer = (n, lo, hi) => Number.isSafeInteger(n) && n >= lo && n <= hi;
    if (plan.version !== 1 || !integer(plan.sample_rate, 8000, 384000) ||
        !integer(plan.duration?.frames, 1, Number.MAX_SAFE_INTEGER) || !Array.isArray(plan.events) || plan.events.length > 200000)
      throw new Error('Invalid native score plan');
    const active = new Map(), used = new Set(), lastOwned = new Map(), layerCounts = new Map();
    let previous = -1, previousRank = -1, hasPitch = false, hasGain = false, hasGroups = false, hasHolds = false, hasContexts = false;
    const contexts = new Map(), contextParents = new Set(plan.events.filter(e => Object.hasOwn(e, 'context')).map(e => e.ch));
    let closing = new Set(), frameHeads = new Set(), lastContext = 0;
    let parents = new Set(), offCount = 0;
    for (const [index, e] of plan.events.entries()) {
      if (!integer(e.frame, 0, plan.duration.frames) || e.frame < previous || typeof e.id !== 'string' || !e.id ||
          typeof e.type !== 'string' || !Object.hasOwn(eventRank, e.type) || e.frame === previous && eventRank[e.type] < previousRank)
        throw new Error('Invalid native score event order');
      if (e.frame !== previous) {
        for (const key of closing) contexts.delete(key);
        closing = new Set(); frameHeads = new Set(); parents = new Set(); offCount = 0;
      }
      if (e.type !== 'note_on' && Object.hasOwn(e, 'layers')) throw new Error('Native score layers belong only to attacks');
      if (Object.hasOwn(e, 'hold') && (e.type !== 'note_on' || typeof e.hold !== 'boolean'))
        throw new Error('Native score hold must be a boolean on an attack');
      if (['context', 'context_open', 'context_close'].some(k => Object.hasOwn(e, k)) &&
          (e.type !== 'note_on' || !integer(e.context, 1, 2147483647) ||
           typeof e.context_open !== 'boolean' || typeof e.context_close !== 'boolean'))
        throw new Error('Invalid native score context fields');
      if (e.type === 'note_on') {
        if (e.context != null) {
          hasContexts = hasGroups = true;
          if (frameHeads.has(e.context) || !integer(e.source_instrument, 1, 99) || e.hold)
            throw new Error('Native score context requires one explicit attack per head/frame, without hold');
          const binding = `${e.ch}/${e.source_instrument}`;
          if (e.context_open) {
            if (e.context <= lastContext || contexts.size >= 64) throw new Error('Native score context key/capacity violation');
            contexts.set(e.context, binding); lastContext = e.context;
          } else if (contexts.get(e.context) !== binding) throw new Error('Native score context is closed or its parent/source changed');
          frameHeads.add(e.context);
          if (e.context_close) closing.add(e.context);
        } else if (contextParents.has(e.ch)) throw new Error('Every attack on a context parent needs its own head context');
        if (e.hold) {
          if (!integer(e.source_instrument, 1, 99) || Object.hasOwn(e, 'layers') || Object.hasOwn(e, 'source_id'))
            throw new Error('Native score hold requires an explicit ordinary attack');
          hasHolds = hasGroups = true;
        }
        if (Object.hasOwn(e, 'layers')) {
          if (!Array.isArray(e.layers) || e.layers.length < 1 || e.layers.length > 3 ||
              e.layers.some(l => !l || Object.keys(l).length !== 2 || !integer(l.pitch, 0, 119) || !integer(l.velocity, 0, 127)))
            throw new Error('Invalid native score layers');
          hasGroups = hasGain = true;
        }
        if (e.velocity != null) {
          if (!integer(e.velocity, 0, 127)) throw new Error('Invalid native score velocity');
          hasGain = true;
        }
        const parent = e.context != null ? `context/${e.context}` : `parent/${e.ch}`;
        if (used.has(e.id) || e.frame === plan.duration.frames || parents.has(parent) || parents.size >= 64 || !integer(e.ch, 0, 63) || !integer(e.pitch, 0, 119) ||
            !integer(e.source_instrument, 0, 99) || !(e.volume === null || integer(e.volume, 0, 64)))
          throw new Error('Invalid native score attack');
        active.set(e.id, e.frame); used.add(e.id);
        layerCounts.set(e.id, e.layers?.length ?? 1);
        parents.add(parent);
      } else if (e.type === 'note_off') {
        if (!active.has(e.id) || active.get(e.id) >= e.frame) throw new Error('Invalid native score release');
        offCount += layerCounts.get(e.id);
        if (offCount > 256) throw new Error('Too many simultaneous native score releases');
        active.delete(e.id);
      } else if (e.type === 'gain') {
        if (!used.has(e.id) || !Array.isArray(e.gains) || e.gains.length !== layerCounts.get(e.id) ||
            e.gains.some(g => typeof g !== 'number' || !Number.isFinite(g) || g < 0 || g > 1))
          throw new Error('Invalid native score gain control identity/values');
        hasGain = true;
      } else {
        if (!used.has(e.id) || typeof e.semitones !== 'number' || !Number.isFinite(e.semitones) || e.semitones < -12 || e.semitones > 12)
          throw new Error('Invalid native score pitch control identity/semitones');
        hasPitch = true;
      }
      lastOwned.set(e.id, index);
      previous = e.frame; previousRank = eventRank[e.type];
    }
    if (active.size) throw new Error('Native score plan has unreleased notes');
    if ([...contexts.keys()].some(key => !closing.has(key))) throw new Error('Native score plan is missing context closes');
    if (hasContexts && hasHolds) throw new Error('Native score context plans must include held parents as contexts');
    return {rate: plan.sample_rate, end: plan.duration.frames,
            events: plan.events.map(e => ({...e, ...(e.gains ? {gains: [...e.gains]} : {}), ...(e.layers ? {layers: e.layers.map(l => ({...l}))} : {})})),
            frame: 0, index: 0, voices: new Map(), tail: false, lastOwned, hasPitch, hasGain, hasGroups, hasHolds, hasContexts};
  }
  class Song {
    #nativeInput = null;
    #clock = null;
    #factorQ = 65536;
    #checkpoint = null;
    #checkpointFns = null;
    #overrides = {mute: new Map(), channelVolume: new Map(), channelPan: new Map()};
    // one loaded module; `bytes` a Uint8Array of the .it. Mixed like the app's renders: the 8-tap interpolation filter.
    constructor(bytes, plan = null, factor = 1) {
      this.outputGain = 1;
      this.#factorQ = factorQ(factor);
      if (plan !== null) {
        scorePlan(plan); // Validate before JSON copying can turn non-finite authored fields into null.
        // Keep the pair private: caller edits or transferred buffers cannot change a future replay.
        plan = JSON.parse(JSON.stringify(plan));
        bytes = new Uint8Array(bytes);
        this.#nativeInput = {bytes, plan};
        this.#clock = nativeScoreClock(plan);
        plan = {...plan, duration: {...plan.duration, frames: this.#clock.frameAt(plan.duration.quarters, plan.sample_rate, this.#factorQ)},
                events: plan.events.map(e => ({...e, frame: this.#clock.frameAt(e.at, plan.sample_rate, this.#factorQ)}))
                  .sort((a, b) => a.frame - b.frame || eventRank[a.type] - eventRank[b.type])};
      }
      this.score = plan === null ? null : scorePlan(plan);
      this.bufL = this.bufR = this.batchOffs = this.batchNotes = this.batchIds = this.batchHolds = this.batchKeys = this.batchCloses = this.checkpointOld = this.checkpointNew = 0;
      const p = M._malloc(bytes.length);
      u8().set(bytes, p);
      this.ext = M._openmpt_module_ext_create_from_memory(p, bytes.length, 0, 0, 0, 0, 0, 0, 0);
      M._free(p);
      if (!this.ext) throw new Error('libopenmpt could not load the module');
      this.mod = M._openmpt_module_ext_get_module(this.ext);
      try {
      const a = iface(this.ext, 'interactive', 16), b = iface(this.ext, 'interactive2', 6);
      this.fn = {tempoFactor: a[2], channelVolume: a[8], mute: a[10], muted: a[11], playNote: a[14], stopNote: a[15],
                 noteOff: b[0], noteFade: b[1], channelPan: b[2]};
      if (!this.fn.tempoFactor(this.ext, 65536 / this.#factorQ)) throw new Error('Tempo factor initialization failed');
      M._openmpt_module_set_render_param(this.mod, 3, 8);  // OPENMPT_MODULE_RENDER_INTERPOLATIONFILTER_LENGTH
      M._openmpt_module_set_repeat_count(this.mod, this.score ? 0 : -1);
      if (this.score) {
        const [dispatch] = iface(this.ext, 'vt_parent_batch', 1);
        const [clock] = iface(this.ext, 'vt_exact_clock', 1), [tail] = iface(this.ext, 'vt_tail', 1);
        Object.assign(this.score, {dispatch, clock, beginTail: tail});
        if (this.score.hasPitch) [this.score.setPitch] = iface(this.ext, 'vt_pitch', 1);
        if (this.score.hasGain) [this.score.setGain] = iface(this.ext, 'vt_gain', 1);
        if (this.score.hasGroups) [this.score.dispatchGroups] = iface(this.ext, 'vt_parent_groups', 1);
        if (this.score.hasHolds) [this.score.dispatchHeld] = iface(this.ext, 'vt_held_score', 1);
        if (this.score.hasContexts) [this.score.dispatchContexts] = iface(this.ext, 'vt_score_contexts', 1);
        if (!clock(this.ext, 1)) throw new Error('Native score clock initialization failed');
        this.score.orderFrames = plan.occurrences.map((_, order) => this.scoreFrameAt(order, 0));
        this.batchOffs = M._malloc(8 * 256);
        this.batchNotes = M._malloc(4 * (this.score.hasContexts ? 8 : this.score.hasGroups ? 7 : 4) * 64);
        this.batchIds = M._malloc(8 * (this.score.hasGroups ? 3 : 1) * 64);
        if (this.score.hasHolds) this.batchHolds = M._malloc(4 * 64);
        if (this.score.hasContexts) { this.batchKeys = M._malloc(8 * 64); this.batchCloses = M._malloc(8 * 64); }
        this.#checkpointFns = iface(this.ext, 'vt_checkpoint', 3);
        this.checkpointOld = M._malloc(8 * 256);
        this.checkpointNew = M._malloc(8 * 256);
      }
      this.channels = M._openmpt_module_get_num_channels(this.mod);
      if (this.score?.events.some(e => e.type === 'note_on' && e.ch >= this.channels))
        throw new Error('Native score channel is absent from its backing IT');
      this.bufL = M._malloc(4 * MAXN);
      this.bufR = M._malloc(4 * MAXN);
      if (this.score?.hasGroups) {
        M._openmpt_module_read_float_stereo(this.mod, this.score.rate, 0, this.bufL, this.bufR);
        const result = this.score.hasContexts ?
          this.score.dispatchContexts(this.ext, this.score.rate, 0, this.batchOffs, 0, this.batchCloses, 0, this.batchKeys, this.batchNotes, 0, this.batchIds) :
          this.score.hasHolds ?
          this.score.dispatchHeld(this.ext, this.score.rate, 0, this.batchOffs, 0, this.batchNotes, this.batchHolds, 0, this.batchIds) :
          this.score.dispatchGroups(this.ext, this.score.rate, 0, this.batchOffs, 0, this.batchNotes, 0, this.batchIds);
        if (result !== 1)
          throw new Error('Native score group initialization failed');
      }
      } catch (error) { this.free(); throw error; }
    }
    // render n frames (n <= 4096) at `rate` into Float32Arrays L and R from index `at`; `add` mixes into them instead.
    // Returns frames rendered.
    read(rate, n, L, R, add, at = 0) {
      if (!this.ext) throw new Error('Song has been freed');
      if (!this.score) return this.readRaw(rate, n, L, R, add, at);
      const s = this.score;
      if (rate !== s.rate) throw new Error('Native score plan must use the actual mixer sample rate');
      if (!Number.isInteger(n) || n < 0 || n > MAXN) throw new Error('Invalid native score read size');
      let done = 0;
      this.scoreEvents();
      while (done < n) {
        const next = Math.min(s.events[s.index]?.frame ?? Infinity, s.tail ? Infinity : s.end);
        const count = Math.min(n - done, next - s.frame);
        if (count <= 0) throw new Error('Native score scheduling did not advance');
        const got = this.readRaw(rate, count, L, R, add, at + done);
        if (got !== count) throw new Error('Native score backing ended before its scheduled read');
        done += got; s.frame += got;
        this.scoreEvents();
      }
      return done;
    }
    scoreEvents() {
      const s = this.score;
      // The caller bounds tail reads. Raw backing never repeats on its own.
      if (!s.tail && s.frame === s.end) {
        if (!s.beginTail(this.ext)) throw new Error('Native score tail transition failed');
        s.tail = true;
      }
      if (s.events[s.index]?.frame !== s.frame) return;
      let stop = s.index, offs = 0, notes = 0, closes = 0, grouped = s.hasContexts || s.hasHolds;
      while (s.events[stop]?.frame === s.frame) {
        if (s.events[stop].layers) grouped = true;
        stop++;
      }
      const offHeap = i64(), noteHeap = i32();
      for (let index = s.index; index < stop; index++) {
        const e = s.events[index];
        if (e.type === 'note_on') {
          if (s.hasHolds) noteHeap[(this.batchHolds >> 2) + notes] = e.hold ? 1 : 0;
          if (s.hasContexts) {
            offHeap[(this.batchKeys >> 3) + notes] = BigInt(e.context ?? 0);
            if (e.context_close) offHeap[(this.batchCloses >> 3) + closes++] = BigInt(e.context);
          }
          const at = (this.batchNotes >> 2) + notes++ * (s.hasContexts ? 8 : grouped ? 7 : 4);
          noteHeap[at] = e.ch;
          if (grouped) {
            noteHeap[at + 1] = e.source_instrument; noteHeap[at + 2] = e.volume === null ? -1 : e.volume;
            noteHeap[at + 3] = e.layers?.length ?? 1;
            for (let i = 0; i < 3; i++) noteHeap[at + 4 + i] = e.layers ? e.layers[i]?.pitch ?? 0 : i ? 0 : e.pitch;
            if (s.hasContexts) noteHeap[at + 7] = e.context != null ? e.context_open ? 1 : 2 : 0;
          } else {
            noteHeap[at + 1] = e.pitch;
            noteHeap[at + 2] = e.source_instrument; noteHeap[at + 3] = e.volume === null ? -1 : e.volume;
          }
        } else if (e.type === 'note_off') {
          const handles = s.voices.get(e.id) ?? 0n;
          if (Array.isArray(handles)) for (const handle of handles) offHeap[(this.batchOffs >> 3) + offs++] = handle;
          else offHeap[(this.batchOffs >> 3) + offs++] = handles;
        }
      }
      const result = s.hasContexts ? s.dispatchContexts(this.ext, s.rate, offs, this.batchOffs, closes, this.batchCloses, notes, this.batchKeys, this.batchNotes, notes * 3, this.batchIds) :
        s.hasHolds ? s.dispatchHeld(this.ext, s.rate, offs, this.batchOffs, notes, this.batchNotes, this.batchHolds, notes * 3, this.batchIds) :
        grouped ? s.dispatchGroups(this.ext, s.rate, offs, this.batchOffs, notes, this.batchNotes, notes * 3, this.batchIds) :
        s.dispatch(this.ext, s.rate, offs, this.batchOffs, notes, this.batchNotes, this.batchIds);
      if (result !== 1) {
        this.free(); // A runtime backing conflict can have advanced its row; never retry this consumer.
        throw new Error('Native score event batch failed');
      }
      const identities = i64(); notes = 0;
      while (s.index < stop) {
        const index = s.index++, e = s.events[index];
        if (e.type === 'note_on') {
          const offset = (this.batchIds >> 3) + notes++ * (grouped ? 3 : 1);
          const handles = e.layers ? Array.from(identities.subarray(offset, offset + e.layers.length)) : [identities[offset]];
          if (handles.some(id => id < 0n) || handles.some(Boolean) && !handles.every(Boolean)) {
            this.free();
            throw new Error('Native score attack failed');
          }
          s.voices.set(e.id, e.layers ? handles : handles[0]); // Zero is an ignored keymap entry.
          for (let i = 0; i < handles.length; i++) {
            const velocity = e.layers ? e.layers[i].velocity : e.velocity;
            if (handles[i] && velocity != null && s.setGain(this.ext, handles[i], velocity / 127) !== 1) {
              this.free(); // Never emit partially scaled PCM or retry an advanced consumer.
              throw new Error('Native score gain initialization failed');
            }
          }
        } else if (e.type === 'pitch') {
          const identity = s.voices.get(e.id) ?? 0n;
          if (Array.isArray(identity)) {
            for (let i = 0; i < identity.length; i++)
              if (identity[i] && !s.setPitch(this.ext, identity[i], e.semitones)) identity[i] = 0n;
          } else if (identity && !s.setPitch(this.ext, identity, e.semitones))
            s.voices.delete(e.id); // A retired identity never acquires a later note on the same parent.
        } else if (e.type === 'gain') {
          const identity = s.voices.get(e.id) ?? 0n;
          const handles = Array.isArray(identity) ? identity : [identity];
          const updated = handles.map((id, i) => id && s.setGain(this.ext, id, e.gains[i]) ? id : 0n);
          s.voices.set(e.id, Array.isArray(identity) ? updated : updated[0]);
        }
        if (s.lastOwned.get(e.id) === index) s.voices.delete(e.id);
      }
    }
    readRaw(rate, n, L, R, add, at = 0) {
      const got = M._openmpt_module_read_float_stereo(this.mod, rate, n, this.bufL, this.bufR), f = f32();
      const l = f.subarray(this.bufL >> 2, (this.bufL >> 2) + got), r = f.subarray(this.bufR >> 2, (this.bufR >> 2) + got);
      if (add) for (let i = 0; i < got; i++) { L[at + i] += l[i]; R[at + i] += r[i] }
      else { L.set(l, at); R.set(r, at) }
      return got;
    }
    scoreTimeAtRow(order, row, {afterRow = false} = {}) {
      const plan = this.#nativeInput?.plan, occurrences = plan?.occurrences;
      if (!occurrences?.length || !Number.isSafeInteger(order) ||
          order < 0 || order > occurrences.length || typeof afterRow !== 'boolean')
        throw new Error('Invalid native score order/row');
      const [rn, rd] = fraction(Array.isArray(row) ? row : [row, 1]);
      if (order === occurrences.length && rn === 0n && !afterRow) return fraction(plan.duration.quarters);
      if (order === occurrences.length) throw new Error('Native score end position has no rows');
      const [sn, sd] = fraction(plan.row_step), [an, ad] = fraction(occurrences[order].at),
            [dn, dd] = fraction(occurrences[order].duration), r = rn + BigInt(afterRow) * rd;
      if (sn === 0n || rn * sn * dd >= dn * sd * rd ||
          r * sn * dd > dn * sd * rd)
        throw new Error('Native score row is outside its occurrence');
      return [an * sd * rd + r * sn * ad, ad * sd * rd];
    }
    scoreFrameAt(order, row, options) {
      return this.scoreFrameAtTime(this.scoreTimeAtRow(order, row, options));
    }
    // BigInt musical coordinates remain internal to replay. Position messages
    // expose reduced safe-number pairs instead.
    scoreTimeAt(frame = this.score?.frame) {
      if (!this.score || !Number.isSafeInteger(frame) || frame < 0 || frame > this.score.end)
        throw new Error('Invalid native replay musical position');
      return this.#clock.timeAtFrame(frame, this.score.rate, this.#factorQ);
    }
    scoreFrameAtTime(time, {clamp = false} = {}) {
      if (!this.score || !Array.isArray(time) || time.length !== 2 ||
          time.some(n => typeof n !== 'bigint') || time[0] < 0n || time[1] <= 0n)
        throw new Error('Invalid native replay musical time');
      // Round the absolute rational position once, half up. Never rescale an
      // already rounded seek target or add rounded row lengths.
      const frame = this.#clock.frameAt(time, this.score.rate, this.#factorQ);
      if (frame > this.score.end && !clamp)
        throw new Error('Native score position is outside its arrangement');
      return Math.min(frame, this.score.end);
    }
    get factorQ() { return this.#factorQ }
    get checkpointAvailable() { return !!this.#checkpointFns }
    hasCheckpoint(frame) { return !!this.#checkpoint && this.#checkpoint.frame === frame }
    captureCheckpoint() {
      if (!this.ext || !this.score) throw new Error('Checkpoint requires a live native consumer');
      if (!this.#checkpointFns) throw new Error('Native checkpoint interface is unavailable');
      const s = this.score;
      // Initialize the mixer even for a silent frame-zero prefix. Empty batches
      // prepare the current row without advancing its output clock.
      if (s.frame === 0 && !s.dispatch(this.ext, s.rate, 0, this.batchOffs, 0, this.batchNotes, this.batchIds))
        throw new Error('Native checkpoint mixer initialization failed');
      const token = this.#checkpointFns[0](this.ext);
      if (token <= 0n) throw new Error('Native checkpoint capture refused');
      this.#checkpoint = {token, frame: s.frame, index: s.index, tail: s.tail,
        voices: new Map(Array.from(s.voices, ([id, handles]) => [id, Array.isArray(handles) ? [...handles] : handles]))};
    }
    restoreCheckpoint() {
      if (!this.ext || !this.#checkpoint) throw new Error('No live native checkpoint to restore');
      const saved = this.#checkpoint;
      try {
        const count = this.#checkpointFns[1](this.ext, saved.token, this.checkpointOld, this.checkpointNew);
        if (!Number.isInteger(count) || count < 0 || count > 256) throw new Error('Native checkpoint restore refused');
        const ids = i64(), mapping = new Map();
        for (let i = 0; i < count; i++) {
          const old = ids[(this.checkpointOld >> 3) + i], fresh = ids[(this.checkpointNew >> 3) + i];
          if (old <= 0n || fresh <= 0n || mapping.has(old)) throw new Error('Invalid native checkpoint identity mapping');
          mapping.set(old, fresh);
        }
        Object.assign(this.score, {frame: saved.frame, index: saved.index, tail: saved.tail,
          voices: new Map(Array.from(saved.voices, ([name, original]) => [name, Array.isArray(original) ?
            original.map(handle => mapping.get(handle) ?? 0n) : mapping.get(original) ?? 0n]))});
      } catch (error) {
        this.free(); // Native state may already have changed. This consumer cannot be retried.
        throw error;
      }
    }
    clearCheckpoint() {
      if (this.#checkpoint && this.ext) this.#checkpointFns[2](this.ext, this.#checkpoint.token);
      this.#checkpoint = null;
    }
    // Map an output frame through exact musical time, including a different
    // speed/tempo/rate in the replacement. No rounded intermediate seconds.
    scoreFrameFrom(source, frame = source.score?.frame) {
      if (!this.score || !source.score || !Number.isSafeInteger(frame) || frame < 0 || frame > source.score.end)
        throw new Error('Invalid native replay musical position');
      return this.scoreFrameAtTime(source.scoreTimeAt(frame), {clamp: true});
    }
    fresh(factor = 65536 / this.#factorQ) {
      if (!this.ext) throw new Error('Song has been freed');
      if (!this.#nativeInput) throw new Error('Fresh replay requires a native score pair');
      const song = new Song(this.#nativeInput.bytes, this.#nativeInput.plan, factor);
      song.outputGain = this.outputGain;
      song.revision = this.revision;
      try {
        for (const [method, values] of Object.entries(this.#overrides))
          for (const [ch, value] of values) song[method](ch, value);
        return song;
      } catch (error) { song.free(); throw error; }
    }
    advanceTo(frame, maxFrames, L, R) {
      if (!this.ext) throw new Error('Song has been freed');
      const s = this.score;
      if (!s || !Number.isSafeInteger(frame) || frame < s.frame || frame > s.end ||
          !Number.isSafeInteger(maxFrames) || maxFrames < 0)
        throw new Error('Native score replay requires a forward target and bounded frame budget');
      const capacity = Math.min(MAXN, maxFrames, frame - s.frame);
      if (!(L instanceof Float32Array) || !(R instanceof Float32Array) || L.length < capacity || R.length < capacity)
        throw new Error('Native score replay scratch buffers are too small');
      let remaining = Math.min(maxFrames, frame - s.frame);
      while (remaining > 0) {
        const n = Math.min(MAXN, remaining);
        this.read(s.rate, n, L, R);
        remaining -= n;
      }
      this.scoreEvents(); // Include frame-zero and exact-target events even for a zero-frame advance.
      return s.frame === frame;
    }
    seek(order, row) {
      this.clearCheckpoint();
      if (this.score) throw new Error('Native score seeking requires paired event replay');
      return M._openmpt_module_set_position_order_row(this.mod, order, row || 0);
    }
    seekSeconds(t) {
      this.clearCheckpoint();
      if (this.score) throw new Error('Native score seeking requires paired event replay');
      return M._openmpt_module_set_position_seconds(this.mod, t);
    }
    position() {
      if (this.score) {
        const s = this.score, plan = this.#nativeInput.plan;
        let lo = 0, hi = s.orderFrames.length;
        while (lo + 1 < hi) { const mid = (lo + hi) >> 1; if (s.orderFrames[mid] <= s.frame) lo = mid; else hi = mid; }
        const occurrence = plan.occurrences[lo], [an, ad] = occurrence.at.map(BigInt),
              [sn, sd] = plan.row_step.map(BigInt), [dn, dd] = occurrence.duration.map(BigInt);
        const [tn, td] = this.#clock.timeAtFrame(Math.min(s.frame, s.end), s.rate, this.#factorQ);
        let n = tn * ad - an * td, d = td * ad;
        if (n < 0n) n = 0n;
        if (n * dd > dn * d) { n = dn; d = dd; }
        const pair = (n, d) => {
          let a = n, b = d; while (b) [a, b] = [b, a % b];
          const p = [Number(n / a), Number(d / a)];
          return p.every(Number.isSafeInteger) ? p : null;
        };
        // The cell follows the same rounded frame boundary as seek and note dispatch. The precise
        // musical coordinate below can still lie half a frame before that cell's written onset.
        const rows = Number(dn * sd / (dd * sn));
        let row = Math.min(Number(n * sd / (d * sn)), Math.max(0, rows - 1)), upper = rows;
        if (row + 1 < upper && this.scoreFrameAt(lo, row + 1) <= s.frame) {
          row++;
          while (row + 1 < upper) {
            const mid = Math.floor((row + upper) / 2);
            if (this.scoreFrameAt(lo, mid) <= s.frame) row = mid; else upper = mid;
          }
        }
        const position = {order: lo, row, seconds: s.frame / s.rate,
                scoreFrame: s.frame, sampleRate: s.rate, occurrence: occurrence.id,
                scoreAt: pair(n, d), scoreRow: pair(n * sd, d * sn),
                scoreTime: pair(tn, td), factorQ: this.#factorQ, revision: this.revision};
        if (occurrence.source_occurrence != null) {
          const [fn, fd] = fraction(occurrence.source_from), sourceN = n * fd + fn * d, sourceD = d * fd;
          Object.assign(position, {sourceOrder: occurrence.source_order, sourceOccurrence: occurrence.source_occurrence,
            sourceRow: Number(fn * sd / (fd * sn)) + position.row,
            sourceAt: pair(sourceN, sourceD), sourceScoreRow: pair(sourceN * sd, sourceD * sn),
            playId: occurrence.id, pass: occurrence.pass});
        }
        return position;
      }
      return {order: M._openmpt_module_get_current_order(this.mod), row: M._openmpt_module_get_current_row(this.mod),
              seconds: M._openmpt_module_get_position_seconds(this.mod)};
    }
    vu() { const v = []; for (let c = 0; c < this.channels; c++) v.push(M._openmpt_module_get_current_channel_vu_mono(this.mod, c)); return v }
    mute(ch, on) {
      this.clearCheckpoint();
      const ok = this.fn.mute(this.ext, ch, on ? 1 : 0);
      if (ok && this.score) this.#overrides.mute.set(ch, !!on);
      return ok;
    }
    muted(ch) { return !!this.fn.muted(this.ext, ch) }
    // instrument 0-based (sample, in a module without instruments); note 0-119, 60 = C-5; returns the channel or -1
    playNote(ins, note, vol = 1, pan = 0) { return this.fn.playNote(this.ext, ins, note, vol, pan) }
    noteOff(ch) { return this.fn.noteOff(this.ext, ch) }
    stopNote(ch) { return this.fn.stopNote(this.ext, ch) }
    tempoFactor(f) {
      this.clearCheckpoint();
      const q = factorQ(f);
      if (this.score) {
        if (q !== this.#factorQ) throw new Error('Native score tempo changes require fresh rescheduling');
        return true;
      }
      const ok = this.fn.tempoFactor(this.ext, 65536 / q);
      if (ok) this.#factorQ = q;
      return ok;
    }
    // a channel's volume (0-1: the header's channel volume / 64, what Mxx sets) and pan (-1 left .. 1 right), as it plays
    channelVolume(ch, v) {
      this.clearCheckpoint();
      const ok = this.fn.channelVolume(this.ext, ch, v);
      if (ok && this.score) this.#overrides.channelVolume.set(ch, v);
      return ok;
    }
    channelPan(ch, p) {
      this.clearCheckpoint();
      const ok = this.fn.channelPan(this.ext, ch, p);
      if (ok && this.score) this.#overrides.channelPan.set(ch, p);
      return ok;
    }
    free() {
      if (!this.ext) return;
      M._openmpt_module_ext_destroy(this.ext);
      M._free(this.bufL);
      M._free(this.bufR);
      M._free(this.batchOffs); M._free(this.batchNotes); M._free(this.batchIds);
      M._free(this.batchHolds);
      M._free(this.batchKeys);
      M._free(this.batchCloses);
      M._free(this.checkpointOld); M._free(this.checkpointNew);
      this.#checkpoint = null;
      this.ext = this.mod = 0;
    }
  }
  const vp = M._openmpt_get_string(cstr('library_version'));
  let version = '';
  for (let h = u8(), i = vp; h[i]; i++) version += String.fromCharCode(h[i]);
  return {Song, version, MAXN, factorQ};
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
if (typeof module !== 'undefined') module.exports = {openmptEngine, loadOpenmpt, nativeScoreClock};
