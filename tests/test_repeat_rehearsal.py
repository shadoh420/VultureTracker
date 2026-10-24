"""Performed rehearsal ranges and exact audio boundaries, using the shipped code."""
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from tests import test_tablature_page as pages, test_rehearsal_playback as practice
from tests.test_engine import NODE, ROOT, SWAP_JS
from tests.test_gui import sine
from vulturetracker import api, tablature, tgimport
from vulturetracker.wavload import write_wav


def repeat_song():
    song = pages.TestTablaturePage.four_bar_song()
    song['module'].update(title='Repeat-aware rehearsal', tempo=240)
    measures = song['score']['measures']
    measures[0]['repeat_open'] = True
    measures[1].update(repeat_close=1, endings=[1])
    measures[2]['endings'] = [2]
    return song


class TestRepeatRehearsal(unittest.TestCase):
    @unittest.skipUnless(NODE, 'node unavailable')
    def test_ranges_follow_returns_skipped_endings_and_selected_visits(self):
        song = repeat_song()
        plan = tablature.repeat_projection(song, tgimport._raw(song)).plan
        self.assertEqual([v['source_order'] for v in plan['occurrences']], [0, 1, 0, 2, 3])
        html = (ROOT/'vulturetracker/gui.html').read_text(encoding='utf-8')
        helpers = html[html.index('function rehearsalRat'):html.index('function rehearsalControls')]
        resolver = html[html.index('function rehearsalSpan'):html.index('async function rehearsalStart')]
        timeline = dict(ranges=[dict(authored=True, meter=[4, 4], **{'from': [i*4, 1], 'to': [(i+1)*4, 1]}) for i in range(4)],
                        offsets=[[oid, [i*4, 1]] for i, oid in enumerate(song['score']['order_ids'])])
        js = "const assert=require('assert/strict');\n" + helpers + resolver + '\n'
        js += 'const LV={plan:' + json.dumps(plan) + '}, SCORE={view:{score:{}}};\n'
        js += 'const timeline=' + json.dumps(timeline) + ';timeline.offsets=new Map(timeline.offsets);\n'
        js += "const VultureTab={timeline:()=>timeline};\n" + r"""
const all=rehearsalSpan(0,1),single=rehearsalSpan(0,1,'visit');
assert.deepEqual(all.toAt,[12,1]); // Return to bar1; skip first ending on pass2.
assert.deepEqual(single.toAt,[8,1]);
assert.equal(all.points.length,12);
assert.deepEqual(rehearsalSpan(0,2).toAt,[16,1]);
const second=rehearsalSpan(0,0,'visit',2);
assert.deepEqual(second.fromAt,[8,1]);assert.equal(second.from[0],2);
assert.equal(second.available,2);
assert.throws(()=>rehearsalSpan(1,2),/no contiguous/); // Cannot silently include bar1 outside range.
assert.throws(()=>rehearsalSpan(0,0,'visit',3),/2 available/);
assert.throws(()=>rehearsalSpan(3,2),/ordered range/);
// With no endings, the whole repeat includes every completed pass.
LV.plan.occurrences[3]={...LV.plan.occurrences[1],at:[12,1],pass:2};
assert.deepEqual(rehearsalSpan(0,1).toAt,[16,1]);
assert.deepEqual(rehearsalSpan(0,1,'visit',2).fromAt,[8,1]);
console.log('PASS full repeats, skipped ending, specific visit, unavailable and outside-range guards');
"""
        result = subprocess.run([NODE, '-'], input=js, capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        print(result.stdout.strip())

    @unittest.skipUnless(NODE, 'node unavailable')
    def test_play_once_and_expressive_seek_are_exact_and_silent_after_end(self):
        song = practice.sync_helpers.TestNativeLoadedModule().seek_song()
        # Existing fixture has a tie over the seek point and raw backing notes.
        repeated = repeat_song()
        repeated['samples'][1].update(file='tone.wav',loop=dict(start=0,end=512))
        first = repeated['score']['patterns'][repeated['orders'][0]]['beats'][0]['notes'][0]
        first.update(let_ring=True,bend=dict(points=[dict(position=0,value=0),dict(position=12,value=2)]))
        repeated['score']['patterns'][repeated['orders'][0]]['beats'].append(dict(id='pedal',track='guitar',voice=1,at=[0,1],written=dict(value=1),
            notes=[dict(id='pedal-note',pitch=40,string=6,fret=0,velocity=63)]))
        js = SWAP_JS.split('async function run')[0] + r"""
const assert=require('assert/strict'),plan=JSON.parse(fs.readFileSync(process.argv[4],'utf8'));
const quantum=p=>{const out=[new Float32Array(128),new Float32Array(128)];p.process([], [out]);return out};
const finish=p=>{let i=0;while(p.pending){assert.ok(++i<10000);quantum(p)}};
(async()=>{
 const p=await make(),messages=[];p.onmsg=m=>messages.push(m);
 const repeat=plan.occurrences.some(v=>v.pass===2),from=repeat?[2,6]:[0,42],fromAt=repeat?[17,2]:[7,2],toAt=repeat?[25,2]:[9,2];
 p.command({type:'load',bytes:it.slice().buffer,plan,id:1});finish(p);
 for(const percent of [80,100,125]){
  p.command({type:'tempo',factor:percent/100});finish(p);
  p.command({type:'metro',on:false});
  p.command({type:'loop',span:{from,fromAt,toAt,once:true}});
  p.command({type:'play',order:from[0],row:from[1]});finish(p);
  const reference=p.song.fresh(),begin=reference.scoreFrameAtTime(fromAt.map(BigInt)),end=reference.scoreFrameAtTime(toAt.map(BigInt));
  const scratch=[new Float32Array(4096),new Float32Array(4096)];
  while(!reference.advanceTo(begin,4096,...scratch)){}
  let error=0,peak=0;
  while(reference.score.frame<end){
   const count=Math.min(128,end-reference.score.frame),actual=quantum(p);
   reference.read(sampleRate,count,...scratch);
   for(let ch=0;ch<2;ch++)for(let i=0;i<128;i++){
    error=Math.max(error,Math.abs(actual[ch][i]-(i<count?scratch[ch][i]:0)));
    peak=Math.max(peak,Math.abs(actual[ch][i]));
   }
  }
  assert.ok(error<1e-6,`Exact seek/play-once PCM: ${error}`);assert.ok(peak>.001);
  assert.ok(quantum(p).every(ch=>ch.every(v=>v===0)));
  assert.equal(p.playing,false);assert.equal(p.song.score.frame,end);
  reference.free();
 }
 assert.equal(messages.filter(m=>m.type==='practice-ended').length,3);
 assert.ok(!messages.some(m=>m.type==='error'),JSON.stringify(messages));
 p.song.free();p.preview.free();p.clearLoopReplay();
 console.log('PASS exact '+(repeat?'bend/let-ring/second-voice repeat':'tied-tail/raw backing')+' seek/play-once at 80/100/125%, silence at range end');
})().catch(e=>{console.error(e.stack);process.exitCode=1});
"""
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            write_wav(folder/'tone.wav', 48000, [sine(220, seconds=.5)])
            (folder/'check.js').write_text(js, encoding='utf-8')
            for source in (song,repeated):
                with self.subTest(title=source['module'].get('title')):
                    prepared = api.prepare_playback(source, folder, 48000)
                    (folder/'backing.it').write_bytes(prepared['backing_it'])
                    (folder/'plan.json').write_text(json.dumps(prepared['plan']), encoding='utf-8')
                    result = subprocess.run([NODE,str(folder/'check.js'),str(ROOT/'vulturetracker/web'),str(folder/'backing.it'),str(folder/'plan.json')], capture_output=True, text=True, timeout=90)
                    self.assertEqual(result.returncode,0,result.stderr)
                    print(result.stdout.strip())
