"""Score practice uses the existing paired native engine and transport."""
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from vulturetracker import api
from vulturetracker.wavload import write_wav
from tests.test_engine import NODE, ROOT, SWAP_JS
from tests.test_gui import sine
from tests import test_tablature_page as page_helpers, test_tablature_sync as sync_helpers
from tests.test_tablature_sync import complete_song_seed


PRACTICE_JS = SWAP_JS.split('async function run')[0] + r"""
const assert=require('assert/strict'),plan=JSON.parse(fs.readFileSync(process.argv[4],'utf8'));
const quantum=p=>{const out=[new Float32Array(128),new Float32Array(128)];p.process([], [out]);return out};
const finish=p=>{let i=0;while(p.pending){assert.ok(++i<10000);quantum(p)}};
(async()=>{
 const p=await make(),messages=[];p.onmsg=m=>messages.push(m);
 p.command({type:'load',bytes:it.slice().buffer,plan,id:1});
 p.command({type:'tempo',factor:.8});finish(p);
 const span={from:[0,0],fromAt:[0,1],toAt:[1,1]};
 p.command({type:'loop',span});
 p.command({type:'practice',config:{from:80,to:100,step:10}});
 p.command({type:'play',order:0,row:0,countIn:[0,2400,4800]});finish(p);
 let energy=0;
 for(let i=0;i<37;i++){const out=quantum(p);for(const v of out[0])energy+=v*v;assert.equal(p.song.score.frame,0)}
 assert.ok(energy>.01,'Count-in must produce audio');
 p.command({type:'stop',pause:true});assert.equal(p.countIn.elapsed,4736);assert.equal(p.practice.percent,80);
 assert.ok(quantum(p).every(ch=>ch.every(v=>v===0)));assert.equal(p.countIn.elapsed,4736);
 p.command({type:'play'});
 quantum(p);assert.equal(p.song.score.frame,64,'Playback starts at exact count-in boundary');
 assert.deepEqual(messages.filter(m=>m.type==='countin').map(m=>m.beat),[1,2,0]);
 let invalidated=false;
 for(let i=0;i<3000&&messages.filter(m=>m.type==='practice').length<4;i++){
   // A mixer action can invalidate pre-roll immediately before a speed transition.
   if(!invalidated&&p.scoreLoop(p.song).to-p.song.score.frame<=128){p.command({type:'mute',ch:0,on:false});invalidated=true;}
   quantum(p);
   if(!p.pending)assert.equal(p.song.factorQ,p.E.factorQ(p.practice.percent/100));
 }
 assert.ok(invalidated);
 const passes=messages.filter(m=>m.type==='practice');
 assert.deepEqual(passes.map(m=>m.percent),[90,100,100,100]);
 assert.equal(p.song.factorQ,p.E.factorQ(1));
 assert.ok(!messages.some(m=>m.type==='error'),JSON.stringify(messages.filter(m=>m.type==='error')));
 p.command({type:'stop'});assert.equal(p.practice,null);assert.equal(p.countIn,null);
 const out=quantum(p);assert.ok(out.every(ch=>ch.every(v=>v===0)),'Stop must silence practice');
 // A tied tail crossing the backing-pattern boundary must replay identically at every new speed.
 p.command({type:'tempo',factor:.8});finish(p);
 p.command({type:'loop',span:{from:[0,42],fromAt:[7,2],toAt:[9,2]}});
 p.command({type:'practice',config:{from:80,to:100,step:10}});
 p.command({type:'play',order:0,row:42});finish(p);
 const expectedAudio=[[],[]],scratch=[new Float32Array(4096),new Float32Array(4096)];
 for(const percent of [80,90,100,100]){
   const reference=p.song.fresh(percent/100),begin=reference.scoreFrameAtTime([7n,2n]),end=reference.scoreFrameAtTime([9n,2n]);
   while(!reference.advanceTo(begin,4096,...scratch)){}
   while(reference.score.frame<end){const n=Math.min(128-expectedAudio[0].length%128,end-reference.score.frame);reference.read(sampleRate,n,...scratch);
     for(let ch=0;ch<2;ch++)for(let i=0;i<n;i++)expectedAudio[ch].push(scratch[ch][i]);}
   reference.free();
 }
 let error=0,peak=0;
 for(let at=0;at<expectedAudio[0].length;at+=128){const actual=quantum(p);
   for(let ch=0;ch<2;ch++)for(let i=0;i<128&&at+i<expectedAudio[ch].length;i++){
     error=Math.max(error,Math.abs(actual[ch][i]-expectedAudio[ch][at+i]));peak=Math.max(peak,Math.abs(actual[ch][i]));
   }
 }
 assert.ok(peak>.001);assert.ok(error<1e-6,`Ramping tied-loop PCM difference ${error}`);p.command({type:'stop'});
 // Exact meter points: mute song and compare detected clicks to native rational boundaries.
 p.command({type:'tempo',factor:.75});finish(p);
 for(let ch=0;ch<p.song.channels;ch++)p.command({type:'mute',ch,on:true});
 p.command({type:'loop',span:{from:[0,0],fromAt:[0,1],toAt:[4,1]}});
 p.command({type:'metro',on:true,points:[{at:[0,1],accent:true},{at:[1,2],accent:false},{at:[1,1],accent:false}]});
 p.command({type:'play',order:0,row:0});finish(p);
 const expected=[0,.5,1].map(q=>p.song.scoreFrameAtTime([BigInt(q*2),2n])),onsets=[];
 let quiet=true;
 for(let block=0;block<600;block++){const out=quantum(p)[0];for(let i=0;i<out.length;i++){
   const loud=Math.abs(out[i])>1e-5;if(loud&&quiet)onsets.push(block*128+i);quiet=!loud;
 }}
 // Ignore sine zero crossings inside a click; separated click groups have a >1000-frame gap.
 const groups=onsets.filter((n,i)=>i===0||n-onsets[i-1]>1000);
 assert.deepEqual(groups.slice(0,3),expected.map(n=>n+1));
 console.log(JSON.stringify({countInFrames:4800,passes:passes.map(m=>m.percent),tiedLoopPcmDifference:error,meterClicks:groups.slice(0,3),expected}));
 p.song.free();p.preview.free();p.clearLoopReplay();
})().catch(e=>{console.error(e.stack);process.exitCode=1});
"""


class TestRehearsalEngine(unittest.TestCase):
    @unittest.skipUnless(NODE, 'node unavailable')
    def test_count_in_ramp_exact_meter_clicks_and_stop(self):
        song = sync_helpers.TestNativeLoadedModule().seek_song()
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            write_wav(folder / 'tone.wav', 48000, [sine(220, seconds=.5)])
            prepared = api.prepare_playback(song, folder, 48000)
            (folder / 'backing.it').write_bytes(prepared['backing_it'])
            (folder / 'plan.json').write_text(json.dumps(prepared['plan']), encoding='utf-8')
            (folder / 'practice.js').write_text(PRACTICE_JS, encoding='utf-8')
            result = subprocess.run([NODE, str(folder / 'practice.js'), str(ROOT / 'vulturetracker/web'),
                str(folder / 'backing.it'), str(folder / 'plan.json')], capture_output=True, text=True, timeout=90)
            self.assertEqual(result.returncode, 0, result.stderr)
            print(result.stdout.strip())


def run_rehearsal(page, song_path, first=25, last=25, expected_order=None):
    """Exercise the real practice controls on a source or packaged four-part score."""
    before = Path(song_path).read_bytes()
    page.evaluate("tab('tab')")
    page.wait_for_selector('.vt-tab-grid [data-note]', state='attached')
    page.click('#rehearsal-open')
    page.fill('#rehearsal-first', str(first)); page.fill('#rehearsal-last', str(last))
    page.fill('#rehearsal-from', '80'); page.fill('#rehearsal-to', '100'); page.fill('#rehearsal-step', '5')
    page.uncheck('#rehearsal-count')
    page.select_option('#rehearsal-track', 'bass')
    page.click('#rehearsal-solo')
    assert page.get_attribute('#rehearsal-solo', 'aria-pressed') == 'true'
    page.click('#rehearsal-start')
    page.wait_for_function("REHEARSAL.active&&LV.playing&&LV.pos?.factorQ===Math.floor(65536/.8+.5)")
    span = page.evaluate('REHEARSAL.span')
    if expected_order is not None: assert span['from'][0] == expected_order
    assert page.evaluate('S.song.facts.channels.map((_,i)=>rehearsalAudible(i))') == page.evaluate(
        'S.song.facts.channels.map((_,i)=>SCORE.view.score.tracks.bass.channels.includes(i))')
    page.wait_for_function('REHEARSAL.percent>=85', timeout=15000)
    assert 'written tempo unchanged' in page.inner_text('#rehearsal-status')
    percent = page.evaluate('REHEARSAL.percent')
    page.evaluate("agCue({action:'pause'})")
    page.wait_for_function('!LV.playing&&pausedTransport?.engine==="live"')
    assert page.evaluate('REHEARSAL.active')
    page.evaluate("agCue({action:'resume'},S.song.path)")
    page.wait_for_function('LV.playing&&REHEARSAL.active')
    page.click('#rehearsal-stop')
    page.wait_for_function('!LV.playing&&!REHEARSAL.active')
    page.click('#rehearsal-solo'); page.click('#rehearsal-mute')
    assert page.get_attribute('#rehearsal-mute', 'aria-pressed') == 'true'
    page.check('#rehearsal-count')
    page.click('#rehearsal-start')
    page.wait_for_function("document.querySelector('#rehearsal-status').textContent.startsWith('Count-in ')")
    page.click('#rehearsal-stop')
    # Stop during asynchronous engine preparation must cancel the pending Start.
    page.evaluate("""() => {globalThis.practiceOriginalStart=lvStart;
        lvStart=()=>practiceOriginalStart().then(()=>new Promise(resolve=>globalThis.practiceReady=resolve))}""")
    page.click('#rehearsal-start')
    page.wait_for_function('typeof practiceReady==="function"')
    page.click('#rehearsal-stop')
    assert page.evaluate("""async () => {lvStart=practiceOriginalStart;practiceReady();
        await new Promise(requestAnimationFrame);return [REHEARSAL.active,LV.playing]}""") == [False, False]
    page.click('#rehearsal-reset')
    page.click('#rehearsal-close')
    assert Path(song_path).read_bytes() == before
    return {'source_bars': [first, last], 'performed_from': span['from'], 'from': span['fromAt'],
            'to': span['toAt'], 'ramped_percent': percent, 'source_unchanged': True}


class TestRehearsalPage(unittest.TestCase):
    page = page_helpers.TestTablaturePage.page

    def test_practice_controls_track_mix_repeat_selection_and_source_unchanged(self):
        song = complete_song_seed()
        song['module']['tempo'] = 240
        for sample in song['samples'].values(): sample['file'] = 'a.wav'
        song['score']['measures'][0]['repeat_open'] = True
        song['score']['measures'][1]['repeat_close'] = 1
        with self.page(api.to_yaml(song)) as (page, state, folder):
            history = (list(state.history), list(state.future))
            # Bar2's second visit reaches bar3 without returning to bar1.
            print(json.dumps(run_rehearsal(page, state.song_path, first=2, last=3, expected_order=3)))
            self.assertEqual((state.history, state.future), history)
