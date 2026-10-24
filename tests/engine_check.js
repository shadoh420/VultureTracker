// Node check of the live engine (web/engine-core.js on the official libopenmpt 0.8.9 wasm build), run by tests/test_engine.py:
//   node tests/engine_check.js <module.it> <rate> <frames> <mute channel> <instrument> <note>
// Prints one JSON line: the library version, the render (int16 LE, base64) of the whole module and of it with the channel
// muted through the interactive interface, the position after a seek, and a note preview rendered from a copy with every
// channel muted.
const fs = require('fs'), path = require('path');
const WEB = path.join(__dirname, '..', 'vulturetracker', 'web');
const ASSETS = process.env.VT_ENGINE_DIR || WEB;
const {loadOpenmpt} = require(path.join(WEB, 'engine-core.js'));
const glue = new Function('libopenmpt', 'require', '__dirname', fs.readFileSync(path.join(ASSETS, 'libopenmpt.js'), 'utf8') + '\nreturn Module;');
const args = process.argv.slice(2), scoreMode = args[0] === '--score';
// Raw Vxx has ordinary mixer block rounding: compare identical partitions for those richer fixtures.
const matchingReplay = scoreMode && args[3] === '--matching-replay';
const [itPath, rate, frames, muteCh, ins, note] = scoreMode ? [args[1]] : args;

function velocityGuards(plan, groups = false, holds = false, contexts = false) {
  const assert = require('assert/strict'), {openmptEngine} = require(path.join(WEB, 'engine-core.js'));
  function fixture({available = true, accepted = true, identity = 101n, groupAvailable = true, heldAvailable = true, contextAvailable = true, primeStatus = 1, batchStatus = 1, gainFailId = 0n} = {}) {
    const memory = new WebAssembly.Memory({initial: 16}), functions = [null], calls = [], interfaces = [];
    let cursor = 8, serial = 0n;
    const retired = new Set(), batches = [];
    const malloc = n => {const p=cursor;cursor=(cursor+n+7)&~7;return p};
    const heap32 = new Int32Array(memory.buffer), heap64 = new BigInt64Array(memory.buffer);
    const methods = {
      vt_parent_batch: (ext, rate, offs, offp, count, notes, ids) => {
        calls.push(['batch', count, count ? heap32[(notes >> 2) + 3] : null]);
        batches.push(Array.from(heap64.subarray(offp>>3,(offp>>3)+offs)));
        for (let i=0;i<count;i++) heap64[(ids >> 3)+i]=identity ? identity+serial++ : 0n;
        return 1;
      },
      vt_parent_groups: (ext, rate, offs, offp, count, notes, capacity, ids) => {
        const values=Array.from({length:count},(_,i)=>Array.from(heap32.subarray((notes>>2)+i*7,(notes>>2)+(i+1)*7)));
        calls.push(['groups',values,capacity]);
        batches.push(Array.from(heap64.subarray(offp>>3,(offp>>3)+offs)));
        if(!offs&&!count)return primeStatus;
        if(batchStatus!==1)return batchStatus;
        for(let i=0;i<count;i++)for(let j=0;j<3;j++)heap64[(ids>>3)+i*3+j]=j<values[i][3]&&identity ? identity+serial++ : 0n;
        return 1;
      },
      vt_gain: (ext, id, gain) => {calls.push(['gain', id, gain]);return +(accepted&&id!==gainFailId)},
      vt_pitch: (ext, id, pitch) => {calls.push(['pitch', id, pitch]);return +!retired.has(id)}
    };
    methods.vt_held_score = (ext, rate, offs, offp, count, notes, flags, capacity, ids) => {
      calls.push(['held', Array.from(heap32.subarray(flags >> 2, (flags >> 2) + count))]);
      return methods.vt_parent_groups(ext, rate, offs, offp, count, notes, capacity, ids);
    };
    methods.vt_score_contexts = (ext, rate, offs, offp, closes, closep, count, keys, notes, capacity, ids) => {
      const values=Array.from({length:count},(_,i)=>Array.from(heap32.subarray((notes>>2)+i*8,(notes>>2)+(i+1)*8)));
      calls.push(['contexts', Array.from(heap64.subarray(closep>>3,(closep>>3)+closes)),
                  Array.from(heap64.subarray(keys>>3,(keys>>3)+count)), values.map(v=>v[7]), capacity]);
      batches.push(Array.from(heap64.subarray(offp>>3,(offp>>3)+offs)));
      if(!offs&&!count)return primeStatus;
      if(batchStatus!==1)return batchStatus;
      for(let i=0;i<count;i++)for(let j=0;j<3;j++)heap64[(ids>>3)+i*3+j]=j<values[i][3]&&identity ? identity+serial++ : 0n;
      return 1;
    };
    const M = {
      _malloc: malloc, _free: () => {},
      _openmpt_get_string: () => 0,
      _openmpt_module_ext_create_from_memory: () => 1, _openmpt_module_ext_get_module: () => 1,
      _openmpt_module_ext_destroy: () => calls.push(['destroy']),
      _openmpt_module_get_num_channels: () => 2,
      _openmpt_module_set_render_param: () => 1, _openmpt_module_set_repeat_count: () => 1,
      _openmpt_module_read_float_stereo: (mod, rate, count) => {assert.equal(count,0);calls.push(['initialize',rate]);return 0},
      _openmpt_module_ext_get_interface: (ext, name, target, size) => {
        const bytes = new Uint8Array(memory.buffer);let end=name;while(bytes[end])end++;
        const key = Buffer.from(bytes.subarray(name,end)).toString();interfaces.push(key);
        if(key==='vt_gain'&&!available)return 0;
        if(key==='vt_parent_groups'&&!groupAvailable)return 0;
        if(key==='vt_held_score'&&!heldAvailable)return 0;
        if(key==='vt_score_contexts'&&!contextAvailable)return 0;
        for(let i=0;i<size/4;i++){functions.push(methods[key]||(()=>1));heap32[(target>>2)+i]=functions.length-1}
        return 1;
      }
    };
    return {E:openmptEngine(M,memory,{get:i=>functions[i]}),calls,interfaces,retired,batches};
  }
  if(contexts) {
    const missing=fixture({contextAvailable:false});
    assert.throws(()=>new missing.E.Song(new Uint8Array([1]),plan),/vt_score_contexts/);
    assert.deepEqual(missing.calls,[['destroy']]);
    for(const change of ['duplicate','closed','reopen','source','missing_close','orphan_flag','boolean_key','hold']) {
      const p=structuredClone(plan),a=p.events.filter(e=>e.type==='note_on');
      if(change==='duplicate')Object.assign(a[2],{context:1,context_open:false});
      if(change==='closed')a[0].context_close=true;
      if(change==='reopen')a[1].context_open=true;
      if(change==='source')a[1].source_instrument=2;
      if(change==='missing_close')a[1].context_close=false;
      if(change==='orphan_flag')delete a[0].context;
      if(change==='boolean_key')a[0].context=true;
      if(change==='hold')a[0].hold=true;
      assert.throws(()=>new (fixture().E.Song)(new Uint8Array([1]),p),/context|head/i);
    }
    const f=fixture(),s=new f.E.Song(new Uint8Array([1]),plan);
    for(const frame of [0,10,20,30,40]) {s.score.frame=frame;s.scoreEvents()}
    assert.deepEqual(f.calls.filter(c=>c[0]==='contexts').slice(0,3),
      [['contexts',[],[],[],0],['contexts',[],[1n],[1],3],['contexts',[1n,2n],[1n,2n],[2,1],6]]);
    assert.deepEqual(f.batches,[[],[],[101n],[],[103n],[102n]]);
    assert.equal(s.score.voices.size,0);s.free();
    return {context_guards:true};
  }
  if(holds) {
    const held=()=>{const p=structuredClone(plan);p.events[0].hold=true;return p};
    const missing=fixture({heldAvailable:false});
    assert.throws(()=>new missing.E.Song(new Uint8Array([1]),held()),/vt_held_score/);
    assert.deepEqual(missing.calls,[['destroy']]); // Capability is checked before even the zero-frame initialization.
    for(const invalid of [1,null,'true']) {
      const p=held();p.events[0].hold=invalid;
      assert.throws(()=>new (fixture().E.Song)(new Uint8Array([1]),p),/hold/);
    }
    const bad=held();bad.events[2].hold=true;
    assert.throws(()=>new (fixture().E.Song)(new Uint8Array([1]),bad),/hold/);
    const f=fixture(),song=new f.E.Song(new Uint8Array([1]),held());
    for(const frame of [0,10,20,30,40]) {song.score.frame=frame;song.scoreEvents()}
    assert.deepEqual(f.calls.filter(c=>c[0]==='held').map(c=>c[1]),[[],[1],[0],[],[],[]]);
    assert.deepEqual(f.batches, [[],[],[101n],[],[],[102n]]);
    assert.ok(f.calls.some(c=>c[0]==='pitch'&&c[1]===101n&&c[2]===3));
    assert.ok(f.calls.some(c=>c[0]==='pitch'&&c[1]===102n&&c[2]===4));
    assert.equal(song.score.voices.size,0);song.free();
    for(const options of [{primeStatus:-6},{batchStatus:-6}]) {
      const f=fixture(options);
      if(options.primeStatus)assert.throws(()=>new f.E.Song(new Uint8Array([1]),held()),/initialization/);
      else {const s=new f.E.Song(new Uint8Array([1]),held());assert.throws(()=>s.scoreEvents(),/batch/);assert.equal(s.ext,0)}
    }
    return {held_guards:true};
  }
  if(groups) {
    const layered=()=>{const p=structuredClone(plan);p.events[0].layers=[{pitch:52,velocity:47},{pitch:52,velocity:31},{pitch:64,velocity:95}];return p};
    for(const layers of [null,{},[],Array(4).fill({pitch:60,velocity:95}),[null],[{pitch:60}], [{pitch:120,velocity:95}],
      [{pitch:60,velocity:NaN}],[{pitch:60,velocity:true}],[{pitch:60,velocity:128}],[{pitch:60,velocity:95,extra:1}]]) {
      const p=layered();p.events[0].layers=layers;const f=fixture();
      assert.throws(()=>new f.E.Song(new Uint8Array([1]),p),/layers/);
    }
    const old=fixture({groupAvailable:false});
    assert.throws(()=>new old.E.Song(new Uint8Array([1]),layered()),/vt_parent_groups/);
    const ordinary=new old.E.Song(new Uint8Array([1]),plan);ordinary.free();
    for(const primeStatus of [0,-4]) {
      const f=fixture({primeStatus});
      assert.throws(()=>new f.E.Song(new Uint8Array([1]),layered()),/group initialization/);
      assert.deepEqual(f.calls,[['initialize',8000],['groups',[],0],['destroy']]);
    }
    for(const count of [85,86]) {
      const p=layered(),on=p.events[0],off=p.events[2];
      p.duration={frames:200,quarters:[1,20]};
      p.events=[...Array.from({length:count},(_,i)=>({...on,id:String(i),frame:i,at:[i,4000]})),
        ...Array.from({length:count},(_,i)=>({...off,id:String(i),frame:150,at:[150,4000]}))];
      const f=fixture();
      if(count===86)assert.throws(()=>new f.E.Song(new Uint8Array([1]),p),/simultaneous.*releases/);
      else new f.E.Song(new Uint8Array([1]),p).free();
    }
    const wrong=layered();wrong.events[2].layers=wrong.events[0].layers;
    assert.throws(()=>new (fixture().E.Song)(new Uint8Array([1]),wrong),/only to attacks/);
    const p=layered(),f=fixture(),song=new f.E.Song(new Uint8Array([1]),p);
    p.events[0].layers[0].pitch=10;p.events[0].layers[0].velocity=0;
    song.scoreEvents();
    assert.deepEqual(f.calls,[['initialize',8000],['groups',[],0],['groups',[[0,1,-1,3,52,52,64]],3],
      ['gain',101n,47/127],['gain',102n,31/127],['gain',103n,95/127],
      ['pitch',101n,1],['pitch',102n,1],['pitch',103n,1]]);
    song.score.frame=10;song.scoreEvents();assert.deepEqual(f.batches[2],[101n,102n,103n]);
    f.retired.add(102n);song.score.frame=20;song.scoreEvents();
    assert.deepEqual(song.score.voices.get('a'),[101n,0n,103n]);
    const before=f.calls.length;song.score.frame=30;song.scoreEvents();
    assert.deepEqual(f.calls.slice(before),[['batch',0,null],['pitch',101n,0],['pitch',103n,0]]);
    assert.equal(song.score.voices.has('a'),false);song.free();
    for(const options of [{batchStatus:0},{batchStatus:-4},{gainFailId:102n}]) {
      const f=fixture(options),s=new f.E.Song(new Uint8Array([1]),layered());
      assert.throws(()=>s.scoreEvents(),/batch|gain/);assert.equal(s.ext,0);
      assert.equal(f.calls.some(c=>c[0]==='pitch'),false);
    }
    const z=fixture({identity:0n}),ignored=new z.E.Song(new Uint8Array([1]),layered());ignored.scoreEvents();
    assert.deepEqual(ignored.score.voices.get('a'),[0n,0n,0n]);assert.equal(z.calls.some(c=>c[0]==='gain'||c[0]==='pitch'),false);ignored.free();
    const mixed=layered();Object.assign(mixed.events[3],{frame:0,at:[0,1],ch:1,velocity:127});
    mixed.events.sort((a,b)=>a.frame-b.frame||({note_off:0,note_on:1,pitch:2}[a.type]-{note_off:0,note_on:1,pitch:2}[b.type]));
    const m=fixture(),both=new m.E.Song(new Uint8Array([1]),mixed);both.scoreEvents();
    assert.deepEqual(m.calls[2],['groups',[[0,1,-1,3,52,52,64],[1,1,-1,1,60,0,0]],6]);
    assert.deepEqual(m.calls.slice(3,7),[['gain',101n,47/127],['gain',102n,31/127],['gain',103n,95/127],['gain',104n,1]]);
    assert.equal(both.score.voices.get('b'),104n);both.free();
    return {group_guards:true};
  }
  const withVelocity = value => {
    const p=structuredClone(plan);if(value!==undefined)p.events[0].velocity=value;return p;
  };
  for(const value of [-1,128,true,false,1.5,'64',NaN,Infinity,-Infinity]) {
    const f=fixture();
    assert.throws(()=>new f.E.Song(new Uint8Array([1]),withVelocity(value)),/velocity|attack/);
  }
  for(const value of [undefined,null,0,64,127]) {
    const f=fixture(),p=withVelocity(value),song=new f.E.Song(new Uint8Array([1]),p);
    assert.equal(f.interfaces.includes('vt_gain'),value!=null);
    p.events[0].velocity=12;
    song.scoreEvents();
    const expected=[['batch',1,-1]];
    if(value!=null)expected.push(['gain',101n,value/127]);
    expected.push(['pitch',101n,1]);
    assert.deepEqual(f.calls,expected);
    song.free();
  }
  for(const value of [undefined,null]) {
    const f=fixture({available:false}),song=new f.E.Song(new Uint8Array([1]),withVelocity(value));
    song.scoreEvents();assert.equal(f.interfaces.includes('vt_gain'),false);song.free();
  }
  for(const value of [0,127]) {
    const f=fixture({available:false});
    assert.throws(()=>new f.E.Song(new Uint8Array([1]),withVelocity(value)),/vt_gain/);
  }
  const failed=fixture({accepted:false}),song=new failed.E.Song(new Uint8Array([1]),withVelocity(64));
  assert.throws(()=>song.scoreEvents(),/gain/);
  assert.equal(song.ext,0);
  assert.deepEqual(failed.calls,[['batch',1,-1],['gain',101n,64/127],['destroy']]);
  const zero=fixture({identity:0n}),ignored=new zero.E.Song(new Uint8Array([1]),withVelocity(0));
  ignored.scoreEvents();assert.deepEqual(zero.calls,[['batch',1,-1]]);ignored.free();
  const simultaneous=withVelocity(0),f=fixture();
  Object.assign(simultaneous.events[3],{frame:0,at:[0,1],ch:1,velocity:127});
  simultaneous.events.sort((a,b)=>a.frame-b.frame||({note_off:0,note_on:1,pitch:2}[a.type]-{note_off:0,note_on:1,pitch:2}[b.type]));
  const chord=new f.E.Song(new Uint8Array([1]),simultaneous);chord.scoreEvents();
  assert.deepEqual(f.calls,[['batch',2,-1],['gain',101n,0],['gain',102n,1],['pitch',101n,1]]);chord.free();
  return {velocity_guards:true};
}

function scoreCheck(E, bytes, plan) {
  const assert = require('assert/strict');
  const copied = JSON.parse(JSON.stringify(plan));
  assert.throws(() => new E.Song(bytes, {...plan, events: [{...plan.events[0], frame: -1}]}), /event order/);
  const firstAttack = plan.events.find(e => e.type === 'note_on');
  if (firstAttack) {
    const ranked = events => events.sort((a, b) => a.frame - b.frame ||
      ({note_off: 0, note_on: 1, pitch: 2, gain: 3}[a.type] - {note_off: 0, note_on: 1, pitch: 2, gain: 3}[b.type]));
    for (const gains of [[NaN], [Infinity], [-.01], [1.01], [null], [true], ['1'], [], null]) {
      const events = ranked([...plan.events, {type: 'gain', id: firstAttack.id,
        frame: firstAttack.frame, at: firstAttack.at, gains}]);
      assert.throws(() => new E.Song(bytes, {...plan, events}), /gain control/);
    }
    for (const semitones of [NaN, Infinity, -Infinity, -12.01, 12.01, null, true, '1']) {
      const events = ranked([...plan.events, {type: 'pitch', id: firstAttack.id,
        frame: firstAttack.frame, at: firstAttack.at, semitones}]);
      assert.throws(() => new E.Song(bytes, {...plan, events}), /pitch control/);
    }
    const unknown = ranked([...plan.events, {type: 'pitch', id: 'unknown-owner',
      frame: firstAttack.frame, at: firstAttack.at, semitones: 1}]);
    assert.throws(() => new E.Song(bytes, {...plan, events: unknown}), /pitch control/);
    const before = [{type: 'pitch', id: firstAttack.id, frame: 0, at: [0, 1], semitones: 1}, ...plan.events];
    assert.throws(() => new E.Song(bytes, {...plan, events: before}), /pitch control|event order/);
  }
  let song;
  const inputBytes = bytes.slice();
  try { song = new E.Song(inputBytes, copied); }
  catch (error) {
    if (error.message.includes('has no "vt_')) return {available: false, error: error.message};
    throw error;
  }
  const count = plan.duration.frames + 1024;
  const renderScore = (s, block) => {
    const l = new Float32Array(count), r = new Float32Array(count);
    for (let at = 0; at < count; at += block) {
      const n = Math.min(block, count - at);
      assert.equal(s.read(plan.sample_rate, n, l, r, false, at), n);
    }
    const pcm = new Float32Array(count * 2);
    for (let i = 0; i < count; i++) { pcm[i * 2] = l[i]; pcm[i * 2 + 1] = r[i]; }
    return Buffer.from(pcm.buffer);
  };
  const renderSlice = (s, n) => {
    const l = new Float32Array(n), r = new Float32Array(n);
    for (let at = 0; at < n; at += 127) s.read(plan.sample_rate, Math.min(127, n - at), l, r, false, at);
    const pcm = new Float32Array(n * 2);
    for (let i = 0; i < n; i++) { pcm[i * 2] = l[i]; pcm[i * 2 + 1] = r[i]; }
    return Buffer.from(pcm.buffer);
  };
  let other, replay, baseline, coordinates;
  let pitchCalls = 0, gainCalls = 0;
  if (song.score.hasPitch || song.score.hasGain) {
    let preparedFrame = -1;
    const setPitch = song.score.setPitch, setGain = song.score.setGain, owned = new Map(), gains = new Set();
    for(const key of ['dispatch','dispatchGroups','dispatchHeld','dispatchContexts'])if(song.score[key]) {
      const dispatch=song.score[key];
      song.score[key]=(...args)=>{const ok=dispatch(...args);if(ok)preparedFrame=song.score.frame;return ok};
    }
    if (song.score.hasGain) song.score.setGain = (ext, identity, gain) => {
      const event = song.score.events[song.score.index - 1];
      assert.equal(preparedFrame, song.score.frame, 'Gain ran before its parent batch');
      assert.ok(['note_on', 'gain'].includes(event.type));
      const handles=[song.score.voices.get(event.id)].flat(),index=handles.indexOf(identity);
      assert.ok(index>=0);
      assert.equal(gain, event.type === 'gain' ? event.gains[index] : (event.layers ? event.layers[index].velocity : event.velocity) / 127);
      gains.add(identity);gainCalls++;
      return setGain(ext, identity, gain);
    };
    song.score.setPitch = (ext, identity, semitones) => {
      const event = song.score.events[song.score.index - 1];
      assert.equal(preparedFrame, song.score.frame, 'Pitch ran before its parent batch');
      assert.equal(event.type, 'pitch');
      const handles=[song.score.voices.get(event.id)].flat(),index=handles.indexOf(identity);
      assert.ok(index>=0, 'Pitch lost its source identity');
      assert.equal(semitones, event.semitones, 'Pitch controls changed stable input order');
      for (const attack of song.score.events.filter(e => e.type === 'note_on' && e.frame === event.frame && (e.layers || e.velocity != null)))
        for(const id of [song.score.voices.get(attack.id)].flat())if(id)assert.ok(gains.has(id),'Pitch ran before gain initialization');
      const key=event.id+':'+index;
      if (owned.has(key)) assert.equal(identity, owned.get(key), 'Released pitch retargeted another voice');
      owned.set(key, identity);
      pitchCalls++;
      return setPitch(ext, identity, semitones);
    };
  }
  try {
    assert.throws(() => song.read(plan.sample_rate + 1, 0, new Float32Array(0), new Float32Array(0)), /sample rate/);
    assert.throws(() => song.seek(0, 0), /replay/);
    assert.throws(() => song.seekSeconds(0.1), /replay/);
    assert.throws(() => song.tempoFactor(2), /rescheduling/);
    inputBytes.fill(0);
    copied.events[0].frame = plan.duration.frames; // A caller cannot mutate the installed schedule.
    if(copied.events[0].layers)copied.events[0].layers[0].pitch=0;
    if (copied.occurrences) copied.occurrences[0].at[0] = 1000000;
    const pcm = renderScore(song, 127);
    assert.equal(song.score.voices.size, 0, 'Consumed identities leaked past their final release/control');
    other = new E.Song(bytes, plan);
    const second = renderScore(other, matchingReplay ? 127 : 4096);
    assert.deepEqual(pcm, second, matchingReplay ? 'Fresh native render differs' : 'Native PCM depends on host block size');
    assert.equal(song.position().scoreFrame, count);
    const L = new Float32Array(4096), R = new Float32Array(4096);
    // Seek inside a sounding voice, onto an event boundary, and to the tail boundary.
    // This also exercises raw channel memory/NNA when the caller supplies that fixture.
    const firstOn = plan.events.find(e => e.type === 'note_on'),
          firstOff = plan.events.find(e => e.type === 'note_off' && e.id === firstOn.id);
    const targets = [...new Set([0, Math.floor((firstOn.frame + firstOff.frame) / 2), firstOff.frame,
      ...plan.events.filter(e => e.type === 'pitch').map(e => e.frame),
      ...(plan.occurrences || []).map((_, order) => song.scoreFrameAt(order, 0)),
      ...(plan.positions || []).filter(p => p.tied_in).map(p => Math.floor((p.frame + p.end_frame) / 2)),
      plan.duration.frames])];
    for (const target of targets) {
      replay = song.fresh();
      if (matchingReplay) baseline = new E.Song(bytes, plan);
      assert.equal(replay.advanceTo(target, 0, L, R), target === 0);
      assert.equal(replay.position().scoreFrame, 0);
      if (matchingReplay) baseline.read(plan.sample_rate, 0, L, R);
      while (replay.position().scoreFrame < target) {
        const before = replay.position().scoreFrame;
        const reached = replay.advanceTo(target, 113, L, R);
        assert.equal(replay.position().scoreFrame - before, Math.min(113, target - before));
        assert.equal(reached, replay.position().scoreFrame === target);
        if (matchingReplay) baseline.read(plan.sample_rate, replay.position().scoreFrame - before, L, R);
      }
      const expected = matchingReplay ? renderSlice(baseline, 512) : pcm.subarray(target * 8, (target + 512) * 8);
      assert.deepEqual(renderSlice(replay, 512), expected,
                       `Paired replay changed PCM at frame ${target}`);
      assert.throws(() => replay.advanceTo(0, 1, L, R), /forward target/);
      replay.free(); replay = null;
      baseline?.free(); baseline = null;
    }
    // Cancellation frees only the candidate; the source and a subsequent candidate remain usable.
    replay = song.fresh();
    replay.advanceTo(plan.duration.frames, 13, L, R);
    replay.free(); replay.free();
    assert.throws(() => replay.advanceTo(20, 1, L, R), /freed/);
    assert.throws(() => replay.fresh(), /freed/);
    replay = song.fresh();
    assert.throws(() => replay.advanceTo(plan.duration.frames + 1, 1, L, R), /forward target/);
    assert.throws(() => replay.advanceTo(1, Infinity, L, R), /bounded/);
    assert.throws(() => replay.advanceTo(1, 1, new Float32Array(0), R), /scratch buffers/);
    assert.deepEqual(renderSlice(replay, 512), pcm.subarray(0, 512 * 8));
    replay.free(); replay = null;
    baseline = new E.Song(bytes, plan);
    for (const s of [song, baseline]) {
      assert.ok(s.mute(0, true)); assert.ok(s.mute(0, false));
      if (s.channels > 1) assert.ok(s.mute(1, true));
      assert.ok(s.channelVolume(0, 0.37)); assert.ok(s.channelPan(0, -0.6));
    }
    replay = song.fresh();
    assert.equal(replay.muted(0), false);
    if (replay.channels > 1) assert.equal(replay.muted(1), true);
    const target = targets[1];
    while (!baseline.advanceTo(target, matchingReplay ? 71 : 4096, L, R)) {}
    while (!replay.advanceTo(target, 71, L, R)) {}
    assert.deepEqual(renderSlice(replay, 512), renderSlice(baseline, 512), 'Replay lost mixer overrides');
    replay.free(); replay = null;
    baseline.free(); baseline = null;
    const original = JSON.stringify(plan);
    song.outputGain = .42;
    // The shared clock has independent Fraction vectors in test_engine.py;
    // this harness checks scheduler/replay integration and native PCM parity.
    const clock = require(path.join(WEB, 'engine-core.js')).nativeScoreClock(plan);
    const frameAt = (at, q) => clock.frameAt(at, plan.sample_rate, q);
    for (const factor of [0.5, 0.75, 1.3, 2]) {
      const q = Math.floor(65536 / factor + 0.5);
      replay = song.fresh(factor);
      baseline = new E.Song(bytes, plan, factor);
      for (const s of [baseline]) {
        s.mute(0, false);
        if (s.channels > 1) s.mute(1, true);
        s.channelVolume(0, 0.37); s.channelPan(0, -0.6);
      }
      assert.equal(replay.factorQ, q);
      assert.equal(replay.outputGain, .42);
      assert.equal(replay.score.end, frameAt(plan.duration.quarters, q));
      for (const e of replay.score.events) assert.equal(e.frame, frameAt(e.at, q));
      const target = Math.floor(replay.score.end / 3);
      while (!replay.advanceTo(target, 113, L, R)) {}
      while (!baseline.advanceTo(target, 113, L, R)) {}
      const p = replay.position();
      assert.equal(p.factorQ, q);
      assert.ok(Array.isArray(p.scoreTime) && Array.isArray(p.scoreRow));
      assert.equal(replay.scoreFrameFrom(baseline), target);
      assert.deepEqual(renderSlice(replay, 512), renderSlice(baseline, 512), 'Speed replay lost pair or overrides');
      const again = replay.fresh();
      assert.equal(again.factorQ, q);
      assert.equal(again.score.end, replay.score.end);
      assert.equal(again.outputGain, replay.outputGain);
      const unity = again.fresh(1);
      assert.equal(unity.score.end, plan.duration.frames, 'Fresh speed compounded rounded frames');
      unity.free(); again.free();
      replay.free(); replay = null; baseline.free(); baseline = null;
    }
    assert.equal(JSON.stringify(plan), original, 'Speed mutated the input plan');
    if (song.score.hasPitch) {
      replay = song.fresh();
      const owner = plan.events.find(e => e.type === 'pitch').id, setPitch = replay.score.setPitch;
      const staleIds = new Set();
      replay.score.setPitch = (ext, identity, semitones) => {
        if (replay.score.events[replay.score.index - 1].id === owner) {
          assert.ok(!staleIds.has(identity), 'A retired pitch identity was reused');
          staleIds.add(identity);
          return 0; // Exercise native retirement without ever looking up the parent channel.
        }
        return setPitch(ext, identity, semitones);
      };
      renderScore(replay, 127);
      assert.equal(staleIds.size, plan.events.find(e=>e.type==='note_on'&&e.id===owner).layers?.length ?? 1);
      assert.equal(replay.score.voices.size, 0);
      replay.free(); replay = null;
    }
    assert.equal(E.factorQ(Number.MIN_VALUE), 0xffffffff);
    assert.equal(E.factorQ(4), 16384);
    assert.equal(E.factorQ(65536 / 65536.5), 65537);
    for (const factor of [NaN, Infinity, -Infinity, 0, -1, 4.01, null, '2']) {
      assert.throws(() => song.fresh(factor), /Tempo factor/);
      assert.throws(() => song.tempoFactor(factor), /Tempo factor/);
    }
    let checkpointRestores = 0;
    if (process.env.VT_REQUIRE_CHECKPOINT === '1') assert.ok(song.checkpointAvailable, 'Checkpoint ABI is required');
    if (song.checkpointAvailable) {
      for (const factor of [1, 1.3]) {
        const scaled = song.fresh(factor);
        const postRelease = scaled.score.events.find(e => e.type === 'pitch' &&
          scaled.score.events.some(off => off.type === 'note_off' && off.id === e.id && off.frame < e.frame));
        const checkpoints = [Math.max(0, scaled.score.events.find(e => e.type === 'note_off').frame - 40),
                             scaled.score.end - 30];
        if (postRelease) checkpoints.push(Math.floor((postRelease.frame +
          scaled.score.events.find(e => e.type === 'note_off' && e.id === postRelease.id).frame) / 2));
        scaled.free();
        for (const target of checkpoints) {
          replay = song.fresh(factor);
          while (!replay.advanceTo(target, 113, L, R)) {}
          if (postRelease && target === checkpoints[2])
            assert.ok(replay.score.voices.has(postRelease.id), 'Released identity was lost before its last pitch control');
          replay.captureCheckpoint();
          assert.ok(replay.hasCheckpoint(target));
          const captured = {frame: replay.score.frame, index: replay.score.index, tail: replay.score.tail},
                retired = new Set([...replay.score.voices.values()].flat().filter(id => id > 0n));
          for (const length of [1, 17, 127, 2049]) {
            replay.restoreCheckpoint();
            const expected = renderSlice(replay, length);
            for (let lap = 0; lap < 4; lap++) {
              replay.restoreCheckpoint();
              assert.equal(replay.score.frame, captured.frame);
              assert.equal(replay.score.index, captured.index);
              assert.equal(replay.score.tail, captured.tail);
              for (const id of [...replay.score.voices.values()].flat()) if (id > 0n) {
                assert.ok(!retired.has(id), 'Restore reused an old voice identity');
                retired.add(id);
              }
              assert.deepEqual(renderSlice(replay, length), expected, `Checkpoint PCM factor ${factor}, length ${length}`);
              checkpointRestores++;
            }
          }
          replay.restoreCheckpoint();
          for (const mutate of [
            () => replay.mute(0, false), () => replay.mute(-1, false),
            () => replay.channelVolume(0, .37), () => replay.channelVolume(-1, .37),
            () => replay.channelPan(0, -.6), () => replay.channelPan(-1, -.6),
            () => replay.tempoFactor(factor),
            () => assert.throws(() => replay.tempoFactor(0), /Tempo factor/),
            () => assert.throws(() => replay.seek(0, 0), /replay/),
          ]) {
            replay.captureCheckpoint();
            mutate();
            assert.equal(replay.hasCheckpoint(target), false);
          }
          replay.captureCheckpoint();
          // Bypass the host to prove native epoch refusal is fatal, never a
          // fallback into a potentially half-restored score-ID map.
          replay.fn.mute(replay.ext, 0, 0);
          assert.throws(() => replay.restoreCheckpoint(), /restore refused/);
          assert.equal(replay.ext, 0);
          replay = null;
        }
      }
    }
    // Tiny half-frame rows expose cumulative rounding; large exact fractions require BigInt products.
    const big = Number.MAX_SAFE_INTEGER;
    if (plan.repeat_projection) {
      const probe = song.fresh();
      probe.revision = 'repeat-test';
      try {
        const index = plan.occurrences.findIndex((o, i) => i > 0 && o.source_order === 0), visit = plan.occurrences[index];
        assert(index > 0);
        const target = probe.scoreFrameAt(index, 0), L = new Float32Array(4096), R = new Float32Array(4096);
        while (probe.score.frame < target) probe.advanceTo(target, 4096, L, R);
        const p = probe.position();
        assert.equal(p.order, index); assert.equal(p.sourceOrder, 0);
        assert.equal(p.playId, visit.id); assert.equal(p.sourceOccurrence, visit.source_occurrence);
        const sourceOffset = visit.source_from[0] * plan.row_step[1] / (visit.source_from[1] * plan.row_step[0]);
        assert.equal(p.pass, visit.pass); assert.equal(p.sourceRow, sourceOffset); assert.equal(p.revision, 'repeat-test');
        if (sourceOffset > 0) {
          const inside = probe.scoreFrameAt(index, 6);
          while (probe.score.frame < inside) probe.advanceTo(inside, 4096, L, R);
          const local = probe.position();
          assert.equal(local.row, 6); assert.equal(local.sourceRow, sourceOffset + 6);
          assert.equal(local.playId, visit.id);
        }
        const fresh = probe.fresh();
        try { assert.equal(fresh.position().revision, 'repeat-test'); } finally { fresh.free(); }
      } finally { probe.free(); }
    }
    const {tempos, ...constantPlan} = plan;
    coordinates = new E.Song(bytes, {...constantPlan, sample_rate: 8000, tempo: 128, events: [],
      row_step: [1, 7500], duration: {frames: 7500, quarters: [2, 1]},
      occurrences: [{at: [0, 1], duration: [1, 1]}, {at: [big, big], duration: [1, 1]}]});
    assert.equal(coordinates.scoreFrameAt(0, 1), 1);
    assert.equal(coordinates.scoreFrameAt(0, 3), 2);
    assert.equal(coordinates.scoreFrameAt(0, [3, 2]), 1);
    assert.equal(coordinates.scoreFrameAt(0, [7499, 1], {afterRow: true}), 3750);
    assert.equal(coordinates.scoreFrameAt(1, [3, 2]), 3751);
    assert.equal(coordinates.scoreFrameAt(0, 0, {afterRow: true}), 1);
    assert.equal(coordinates.scoreFrameAt(0, 7499, {afterRow: true}), 3750);
    assert.equal(coordinates.scoreFrameAt(1, 0), 3750);
    assert.equal(coordinates.scoreFrameAt(2, 0), 7500);
    for (const [order, row] of [[-1, 0], [0, -1], [0, 7500], [2, 1], [0, 0.5],
                              [0, [1, 0]], [0, [15000, 2]], [0, [-1, 3]]])
      assert.throws(() => coordinates.scoreFrameAt(order, row), /native score|outside its occurrence/i);
    return {available: true, frames: count, block_independent: !matchingReplay, guarded_transport: true,
            matching_replay_partitions: matchingReplay,
            paired_replay: true, replay_overrides: true, exact_row_frames: true, cancellation: true, speed: true,
            checkpoint: song.checkpointAvailable, checkpointRestores, pitch: !!song.score.hasPitch, contexts: !!song.score.hasContexts, pitchCalls, gainCalls,
            repeat_source_mapping: !!plan.repeat_projection, pcm: pcm.toString('base64'), position: song.position()};
  } finally { song.free(); other?.free(); replay?.free(); baseline?.free(); coordinates?.free(); }
}

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

if (['--velocity-guards','--group-guards','--held-guards','--context-guards'].includes(args[0])) {
  console.log(JSON.stringify(velocityGuards(JSON.parse(fs.readFileSync(0, 'utf8')), args[0] === '--group-guards', args[0] === '--held-guards', args[0] === '--context-guards')));
} else loadOpenmpt((cfg) => glue(cfg, require, ASSETS), fs.readFileSync(path.join(ASSETS, 'libopenmpt.wasm'))).then(E => {
  const bytes = new Uint8Array(fs.readFileSync(itPath));
  if (scoreMode) {
    console.log(JSON.stringify(scoreCheck(E, bytes, JSON.parse(fs.readFileSync(args[2], 'utf8')))));
    return;
  }
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
