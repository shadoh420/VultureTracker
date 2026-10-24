"""Native TAB on a disposable real app song; run under the browser resource lease.

These tests exercise the renderer and shared server/history path. The UI worker
authors them; the integration lead owns browser execution and visual acceptance.
"""
import os
import shutil
import io
import json
import re
import subprocess
import sys
import tempfile
import unittest
import wave
from contextlib import contextmanager
from urllib.parse import urlencode, urlsplit
from pathlib import Path
from fractions import Fraction
from unittest import mock
from types import SimpleNamespace

from tests import test_release100_page as page_fixture
from tests.test_gui import RATE, sine
from vulturetracker import gui, api
from vulturetracker.wavload import write_wav


def tempo_marks(page, selector):
    """Read the actual engraved symbols and numbers, not the automation model."""
    return page.locator(selector).evaluate("""root=>{
        const texts=[...root.querySelectorAll('svg text')], result=[], measure=document.createElement('canvas').getContext('2d');
        const ink=(e,text,offset=0)=>{
            const style=getComputedStyle(e), p=e.getStartPositionOfChar(offset).matrixTransform(e.getScreenCTM());
            measure.font=`${style.fontStyle} ${style.fontWeight} ${style.fontSize} ${style.fontFamily}`;
            const m=measure.measureText(text);
            return {left:p.x-m.actualBoundingBoxLeft,right:p.x+m.actualBoundingBoxRight,top:p.y-m.actualBoundingBoxAscent};
        };
        texts.forEach((e,i)=>{
            if(!/^ = [0-9]+$/.test(e.textContent)) return;
            const glyph=texts[i-1];
            if(![...glyph.textContent].some(c=>c.charCodeAt(0)>=0xeca2&&c.charCodeAt(0)<=0xecad)) return;
            // The native label starts with a space; its advance box can overlap
            // the music glyph's overhang while the painted '=' remains clear.
            const a=ink(glyph,glyph.textContent), b=ink(e,e.textContent.slice(1),1);
            // Plain quarters use alphaTab's unchanged painter; its tiny-scale
            // bounding ink can overlap horizontally despite separate contours.
            if(a.right<=a.left||b.right<=b.left||(glyph.textContent!=='\ueca5'&&b.left<a.right)) throw Error('Tempo symbol/number ink overlap '+JSON.stringify({glyph:glyph.textContent,a,b}));
            result.push({glyph:glyph.textContent,value:+e.textContent.slice(3),left:a.left,right:b.right,top:b.top});
        });return result;
    }""")


def lyric_boxes(page, selector, words):
    """Check the actual ink, including repeated words, at the rendered scale."""
    boxes = page.locator(selector).evaluate("""(root,words)=>[...root.querySelectorAll('svg text')]
        .filter(e=>words.includes(e.textContent)).map(e=>({text:e.textContent,...e.getBoundingClientRect().toJSON()}))""", words)
    boxes.sort(key=lambda b: (round(b['top'], 1), b['left']))
    assert sorted(b['text'] for b in boxes) == sorted(words), boxes
    gaps = []
    for a, b in zip(boxes, boxes[1:]):
        assert a['width'] > 0 and b['width'] > 0
        if abs(a['top']-b['top']) < min(a['height'], b['height']) / 2:
            gap = b['left']-a['right']
            assert gap >= min(a['height'], b['height']) * .15, (a, b, gap)
            gaps.append(gap)
    return dict(words=len(boxes), min_gap=min(gaps) if gaps else None,
                lines=len({round(b['top'], 1) for b in boxes}))


def articulation_harmonic_boxes(page, selector):
    """The demonstrated combined-label collision must stay separated in real SVG output."""
    boxes = page.locator(selector).evaluate("""root=>[...root.querySelectorAll('svg text')].map(e=>({
        text:e.textContent, ...e.getBoundingClientRect().toJSON()}))""")
    gaps = {}
    for mark, harmonic in (('T', 'A.H.'), ('S', 'N.H.'), ('P', 'S.H.')):
        marks = [b for b in boxes if b['text'] == mark or b['text'].endswith(' · '+mark)]
        labels = [b for b in boxes if b['text'] == harmonic]
        assert marks and len(labels) == 1, (mark, marks, labels)
        b = labels[0]
        a = min(marks, key=lambda a: abs(a['top']-b['top']))
        assert a['width'] > 0 and b['width'] > 0
        gap = max(b['top']-a['bottom'], a['top']-b['bottom'])
        assert gap >= 1, (mark, harmonic, a, b)
        gaps[mark+'/'+harmonic] = gap
    return gaps


SONG = """\
module: {title: Tab fixture, tempo: 125, speed: 2, channels: [{name: High}, {name: Low}]}
samples:
  1: {file: a.wav, name: Guitar}
patterns:
  verse:
    rows: 25
    data: |
      00: ... .. ... D07 | ... .. ... ...
orders: [verse]
score:
  version: 1
  tracks:
    guitar: {tuning: [64, 59], channels: [0, 1], capo: 0, instrument: 1}
  order_ids: [occ-verse]
  patterns:
    verse:
      row_step: [1, 12]
      beats:
        - {id: beat-a, track: guitar, voice: 0, at: [0, 1], written: {value: 8, dots: 0, tuplet: [3, 2]}, notes: [{id: note-a, pitch: 64, string: 1, fret: 0}]}
        - {id: beat-b, track: guitar, voice: 0, at: [1, 1], written: {value: 4, dots: 0, tuplet: [1, 1]}, notes: [{id: note-b, pitch: 62, string: 2, fret: 3}]}
  ties: []
"""

TIE_SONG = SONG.replace(
    'at: [1, 1], written: {value: 4, dots: 0, tuplet: [1, 1]}, notes: [{id: note-b, pitch: 62, string: 2, fret: 3}]',
    'at: [1, 3], written: {value: 8, dots: 0, tuplet: [3, 2]}, notes: [{id: note-b, pitch: 64, string: 1, fret: 0}]')
RAW_SONG = SONG.split('score:\n')[0].replace(
    '00: ... .. ... D07 | ... .. ... ...',
    '00: E-5 01 ... D07 | ... .. ... ...\n'
    '      01: ... .. ... ... | ... .. ... ...\n'
    '      02: ... .. ... ... | ... .. ... ...\n'
    '      03: ... .. ... ... | ... .. ... ...\n'
    '      04: === .. ... ... | ... .. ... ...') + """score:
  version: 1
  tracks:
    guitar: {tuning: [64, 59], channels: [0, 1], capo: 0, instrument: 1}
  order_ids: [occ-verse]
  patterns: {}
  ties: []
"""

PRINT_SONG = """\
module: {title: Full song print, tempo: 125, speed: 2, channels: [{name: Lead high}, {name: Lead low}, {name: Bass high}, {name: Bass low}]}
samples:
  1: {file: a.wav, name: Guitar}
patterns:
  verse: {rows: 48, data: ''}
  bridge: {rows: 48, data: ''}
  repeat: {rows: 48, data: ''}
orders: [verse, bridge, repeat, repeat]
score:
  version: 1
  tracks:
    lead: {name: Lead guitar, tuning: [64, 59], channels: [0, 1], capo: 0, instrument: 1, clef: treble, key: {fifths: 6, mode: major}}
    bass: {name: Bass guitar, tuning: [40, 35], channels: [2, 3], capo: 0, instrument: 1, clef: bass, key: {fifths: -3, mode: minor}}
  order_ids: [verse-1, bridge-1, repeat-1, repeat-2]
  patterns:
    verse:
      row_step: [1, 12]
      beats:
        - {id: lead-a, track: lead, voice: 0, at: [0, 1], written: {value: 1}, notes: [{id: lead-note-a, pitch: 65, string: 1, fret: 1, spelling: {step: E, alter: 1}}]}
        - {id: bass-a, track: bass, voice: 0, at: [0, 1], written: {value: 2, dots: 1}, notes: [{id: bass-note-a, pitch: 40, string: 1, fret: 0}]}
    repeat:
      row_step: [1, 12]
      beats:
        - {id: lead-r, track: lead, voice: 0, at: [0, 1], written: {value: 2, dots: 1}, notes: [{id: lead-note-r, pitch: 65, string: 1, fret: 1, spelling: {step: E, alter: 1}}]}
        - {id: bass-r, track: bass, voice: 0, at: [0, 1], written: {value: 2, dots: 1}, notes: [{id: bass-note-r, pitch: 40, string: 1, fret: 0}]}
    bridge:
      row_step: [1, 12]
      beats:
        - {id: lead-b, track: lead, voice: 0, at: [0, 1], written: {value: 2, dots: 1}, notes: [{id: lead-note-b, pitch: 65, string: 1, fret: 1, spelling: {step: E, alter: 1}}]}
        - {id: bass-b, track: bass, voice: 0, at: [0, 1], written: {value: 2, dots: 1}, notes: [{id: bass-note-b, pitch: 43, string: 1, fret: 3}]}
  measures:
    - {id: crossing, from: {occurrence: verse-1, at: [0, 1]}, to: {occurrence: bridge-1, at: [2, 1]}, meter: [6, 4]}
    - {id: bridge-tail, from: {occurrence: bridge-1, at: [2, 1]}, to: {occurrence: repeat-1, at: [0, 1]}, meter: [2, 4]}
    - {id: repeated-verse, from: {occurrence: repeat-1, at: [0, 1]}, to: {occurrence: repeat-2, at: [4, 1]}, meter: [8, 4]}
  ties:
    - {from: {occurrence: verse-1, note: lead-note-a}, to: {occurrence: bridge-1, note: lead-note-b}}
"""

NATIVE_SONG = """\
module: {title: Exact native TAB, tempo: 137, speed: 2, channels: [{name: Guitar}]}
samples:
  1: {file: a.wav, name: Guitar}
patterns:
  verse: {rows: 48, data: ''}
orders: [verse, verse, verse]
score:
  version: 1
  tracks:
    guitar: {tuning: [64], channels: [0], instrument: 1}
  order_ids: [pass-1, pass-2, pass-3]
  patterns:
    verse:
      row_step: [1, 12]
      beats:
""" + ''.join(
    f'        - {{id: beat-{i}, track: guitar, voice: 0, at: [{4*i}, 13], '
    f'written: {{value: 8, tuplet: [13, 8]}}, notes: [{{id: note-{i}, pitch: 64}}]}}\n'
    for i in range(13)
) + """\
  ties:
    - {from: {occurrence: pass-1, note: note-12}, to: {occurrence: pass-2, note: note-0}}
"""

NATIVE_RAW_SONG = """\
module: {title: Native raw preview, tempo: 137, speed: 2, channels: [{name: High}, {name: Low}]}
samples:
  1: {file: a.wav, name: Guitar}
patterns:
  verse:
    rows: 48
    data: |
""" + ''.join(
    f'      {i:02d}: ' + {
        0: 'C-5 01 ... ... | B-4 01 ... V40',
        4: '... .. ... ... | === .. ... ...',
        8: '... .. ... ... | B-4 01 ... ...',
        12: '=== .. ... ... | B-4 01 ... ...',
        16: '... .. ... ... | ^^^ .. ... ...',
        20: '... .. ... ... | B-4 01 ... ...',
    }.get(i, '... .. ... ... | ... .. ... ...') + '\n'
    for i in range(48)
) + """\
  unplayed:
    rows: 48
    data: |
      00: ... .. ... ... | B-4 01 ... ...
orders: [verse, verse, verse]
score:
  version: 1
  tracks:
    guitar: {tuning: [64, 59], channels: [0, 1], instrument: 1}
  order_ids: [pass-1, pass-2, pass-3]
  patterns:
    verse:
      row_step: [1, 12]
      beats:
        - {id: exact, track: guitar, voice: 0, at: [4, 13], written: {value: 8, tuplet: [13, 8]}, notes: [{id: exact-note, pitch: 64, string: 1, fret: 0}]}
  ties: []
"""

def roll_scroll(page, selector):
    """Scroll a ROLL element into view, let the onscroll re-render settle, and return its fresh rect.

    #rollscroll re-renders the whole roll on scroll, so a held Playwright handle can be
    detached mid-action; query afresh in the page instead."""
    page.wait_for_selector(selector, state='attached')
    return page.evaluate("""s=>new Promise(r=>{document.querySelector(s).scrollIntoView({block:'nearest',inline:'nearest'});
        requestAnimationFrame(()=>requestAnimationFrame(()=>{const b=document.querySelector(s).getBoundingClientRect();
            r({x:b.x,y:b.y,width:b.width,height:b.height})}))})""", selector)


NATIVE_TRANSFORM_SONG = NATIVE_SONG.replace(
    'channels: [{name: Guitar}]', 'channels: [{name: Guitar}, {name: Raw}]'
).replace("  verse: {rows: 48, data: ''}", '  verse:\n    data: |\n' + ''.join(
    f'      {i:02d}: ' + {
        3: '... .. v17 V40 | ... .. ... ...',
        7: '... .. ... ... | C-5 01 v23 X80',
        8: '... .. ... ... | === .. ... ...',
    }.get(i, '... .. ... ... | ... .. ... ...') + '\n'
    for i in range(48)
).rstrip())


class TestTablatureSyntax(unittest.TestCase):
    def test_fretboard_catalogue_spelling_and_preferences(self):
        node = shutil.which('node')
        if not node:
            self.skipTest('node unavailable')
        script = r"""
const fs=require('fs'),vm=require('vm'),assert=require('assert');
const target={},hook='window.VultureTab = {mount, mountPrint};';
vm.runInNewContext(fs.readFileSync('vulturetracker/web/tablature.js','utf8').replace(hook,
 hook+'window.fb={scaleCatalogue,scaleRoots,rootPitch,scaleHas,scaleFifths,keySpelling,fretboardPreferences};'),{window:target});
const f=target.fb,major=f.scaleCatalogue[0][1];
assert.equal(f.scaleCatalogue.length,275);assert.equal(f.scaleRoots.length,17);
assert.equal(f.scaleCatalogue[0][0],'Major Scale');
assert.equal(f.scaleCatalogue.find(s=>s[0]==='Chromatic Scale')[1],4095);
assert(f.scaleCatalogue.some((s,i,a)=>a.some((x,j)=>i!==j&&x[1]===s[1]))); // source aliases retained
for(const [root,fifths] of [['C',0],['D',2],['Db',-5],['C#',7],['F#',6],['Gb',-6],['F',-1]]){
 assert.equal(f.scaleFifths(major,root),fifths,root);
 for(let p=0;p<128;p++)assert.equal(f.scaleHas(major,f.rootPitch(root),p),
  [0,2,4,5,7,9,11].includes((p-f.rootPitch(root)+120)%12));
}
assert.equal(f.keySpelling(65,7).step,'E');assert.equal(f.keySpelling(60,7).step,'B');
assert.equal(f.keySpelling(59,-6).step,'C');
const p=f.fretboardPreferences({font:'serif',root:'Db',scale:274,spacing:60,notes:'#123456',size:999,direction:'oops',open:true});
assert.equal(p.size,12);assert.equal(p.direction,'right');assert.equal(p.font,'serif');
assert.equal(p.root,'Db');assert.equal(p.scale,274);assert.equal(p.spacing,60);assert.equal(p.notes,'#123456');assert(p.open);
"""
        result = subprocess.run([node, '-e', script], cwd=Path(__file__).resolve().parents[1],
                                capture_output=True, text=True, encoding='utf-8')
        self.assertEqual(result.returncode, 0, result.stderr[-3000:])

    def test_percussion_projection_keys_symbols_lanes_ties_and_source_immutability(self):
        node = shutil.which('node')
        if not node:
            self.skipTest('node unavailable')
        script = r"""
const fs=require('fs'),vm=require('vm'),assert=require('assert'),alphaTab=require('./vulturetracker/web/alphaTab.min.js');
const target={},hook='window.VultureTab = {mount, mountPrint};';
vm.runInNewContext(fs.readFileSync('vulturetracker/web/tablature.js','utf8').replace(hook,
 hook+'window.project=notationTrack;'),{window:target,alphaTab});
const spec={tuning:[0,0,0],channels:[0,1,2],capo:0,midi:{bank:128,program:0},clef:'bass',key:{fifths:4}};
const note=(id,key,lane)=>({id,pitch:key,string:lane,fret:key});
const notes=[[note('h1',42,1),note('h2',42,2)],[note('t2',42,2),note('t1',42,1)],
 [note('low',1,1),note('snare',38,2)],[note('high',100,1),note('open',46,2)],[note('hat',42,1),note('kick',36,2)]];
const source=notes.map((notes,i)=>({id:'b'+i,track:'d',voice:0,at:[i,1],written:{value:4},notes}));
const before=JSON.stringify([spec,source]),score=new alphaTab.model.Score(),seen=[];
const ranges=[{from:[0,1],to:[4,1],meter:[4,4],authored:true},{from:[4,1],to:[8,1],meter:[4,4],authored:true}];
const track=target.project(score,'d',spec,ranges,source,new Set(['t1','t2']),()=>{},
 (n,original)=>seen.push({n,original}));
score.finish(new alphaTab.Settings());
const staff=track.staves[0],art=track.percussionArticulations,by=id=>seen.find(x=>x.original.id===id).n;
assert(staff.isPercussion);assert.equal(staff.showTablature,false);assert.equal(staff.tuning.length,0);
assert(staff.bars.every(b=>b.clef===alphaTab.model.Clef.Neutral&&b.keySignature===0));
for(let key=1;key<=100;key++)assert.equal(art[key].outputMidiNumber,key);
for(const {n,original} of seen){assert(n.isPercussion);assert(!n.isStringed);
 assert.equal(art[n.percussionArticulation].outputMidiNumber,original.pitch);}
assert.equal(by('high').percussionArticulation,100);assert.equal(art[100].staffLine,0);
assert.equal(art[100].noteHeadDefault,alphaTab.model.MusicFontSymbol.NoteheadBlack);
assert.equal(by('h1').percussionArticulation,101);assert.equal(by('t1').percussionArticulation,42);
assert.equal(by('hat').percussionArticulation,101);
assert.equal(by('t1').tieOrigin,by('h1'));assert.equal(by('t2').tieOrigin,by('h2'));
assert.equal(art[46].noteHeadDefault,alphaTab.model.MusicFontSymbol.NoteheadXBlack);
assert.equal(art[46].techniqueSymbol,alphaTab.model.MusicFontSymbol.FretboardO);
assert.equal(art[101].techniqueSymbol,alphaTab.model.MusicFontSymbol.NoteheadPlusBlack);
const cropped=new alphaTab.model.Score();
target.project(cropped,'d',spec,[{from:[1,1],to:[4,1],meter:[3,4],authored:true}],source,new Set());
cropped.finish(new alphaTab.Settings());
assert(cropped.tracks[0].staves[0].bars[0].voices[0].beats[0].notes.every(n=>n.percussionArticulation===42));
assert.equal(JSON.stringify([spec,source]),before);
"""
        result = subprocess.run([node, '-e', script], cwd=Path(__file__).resolve().parents[1],
                                capture_output=True, text=True, encoding='utf-8')
        self.assertEqual(result.returncode, 0, result.stderr[-3000:])

    def test_lyrics_projection_occurrences_voices_fragments_and_crop(self):
        node = shutil.which('node')
        if not node:
            self.skipTest('node unavailable')
        script = r"""
const fs=require('fs'),vm=require('vm'),assert=require('assert'),alphaTab=require('./vulturetracker/web/alphaTab.min.js');
const target={},hook='window.VultureTab = {mount, mountPrint};';
vm.runInNewContext(fs.readFileSync('vulturetracker/web/tablature.js','utf8').replace(hook,
 hook+'window.project=notationTrack;window.timeline=printTimeline;'),{window:target,alphaTab});
const source=[
 {id:'rest',track:'g',voice:0,at:[0,1],written:{value:4},notes:[]},
 {id:'head',track:'g',voice:1,at:[0,1],written:{value:4},notes:[{id:'n',pitch:64,string:1,fret:0}]},
 {id:'tail',track:'g',voice:1,at:[1,1],written:{value:4},notes:[{id:'t',pitch:64,string:1,fret:0}]}];
const view={orders:['p','p'],pattern_names:['p'],rows:[48],row_step:[1,12],
 lyrics:{anchors:[['A','head',1,'hy-phen + _ [x]'],['A','tail',1,''],['B','head',1,'\u00a0word\u00a0'],['B','tail',1,'last']]
 .map(([occurrence,beat,voice,display_text])=>({track:'g',pattern:'p',occurrence,beat,voice,display_text})),errors:[]},
 score:{order_ids:['A','B'],tracks:{g:{tuning:[64],lyrics:{from_measure:1,text:'raw untouched'}}},
 patterns:{p:{row_step:[1,12],beats:source}},ties:[{from:{occurrence:'A',note:'n'},to:{occurrence:'A',note:'t'}}]}};
const before=JSON.stringify(view),timeline=target.timeline(view);
function project(ranges){
 const score=new alphaTab.model.Score(),seen=[];
 target.project(score,'g',view.score.tracks.g,ranges,timeline.source,timeline.tieTargets,
  (b,o,at,end,voice)=>{if(b.lyrics)seen.push([o.sourceOccurrence,o.id,voice,b.lyrics[0]])});
 score.finish(new alphaTab.Settings());return seen;
}
const ranges=[{from:[0,1],to:[1,2],meter:[1,8],authored:true},
 {from:[1,2],to:[4,1],meter:[7,8],authored:true},{from:[4,1],to:[8,1],meter:[4,4],authored:true}];
assert.deepStrictEqual(project(ranges),[['A','head',1,'hy-phen + _ [x]'],['B','head',1,'\u00a0word\u00a0'],['B','tail',1,'last']]);
assert.deepStrictEqual(project(ranges.slice(2)),[['B','head',1,'\u00a0word\u00a0'],['B','tail',1,'last']]);
assert.deepStrictEqual(project([{from:[9,2],to:[8,1],meter:[7,8],authored:true}]),[['B','tail',1,'last']]);
assert.equal(JSON.stringify(view),before);
"""
        result = subprocess.run([node, '-e', script], cwd=Path(__file__).resolve().parents[1],
                                capture_output=True, text=True, encoding='utf-8')
        self.assertEqual(result.returncode, 0, result.stderr[-2000:])

    def test_fixture_compiles_in_state(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(gui, 'remember_song'):
            folder = Path(tmp)
            write_wav(folder / 'a.wav', RATE, [sine(440)])
            path = folder / 'song.yaml'
            path.write_bytes(SONG.encode('utf-8'))
            state = gui.State(path, headless=True)
            try:
                self.assertFalse(state.error, state.error)
                self.assertEqual(len(state.mod.patterns[0].rows), 25)
                positions = state.score_view()['positions']
                self.assertEqual([(p['note'], p['row'], p['end_row']) for p in positions if p['kind'] == 'note'],
                                 [('note-a', [0, 1], [4, 1]), ('note-b', [12, 1], [24, 1])])
            finally:
                state.close()

    def test_script_parses(self):
        node = shutil.which('node')
        if not node:
            self.skipTest('node unavailable')
        script = Path(__file__).resolve().parents[1] / 'vulturetracker' / 'web' / 'tablature.js'
        result = subprocess.run([node, '--check', str(script)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        html = script.parent.parent / 'gui.html'
        for body in re.findall(r'<script(?:\s[^>]*)?>(.*?)</script>', html.read_text(encoding='utf-8'), re.S):
            result = subprocess.run([node, '-e', "new Function(require('fs').readFileSync(0,'utf8'))"],
                                    input=body, capture_output=True, text=True, encoding='utf-8')
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_repeat_transport_contract_preserves_authored_selection(self):
        node = shutil.which('node')
        if not node:
            self.skipTest('node unavailable')
        script = r"""
const fs=require('fs'),assert=require('assert');
const html=fs.readFileSync('vulturetracker/gui.html','utf8');
const code=html.split('// ---- source/play coordinate mapping')[1].split('// ---- song overview')[0];
assert(code,'mapping helpers missing');
let S={version:{hash:'rev'},playback_revision:'rev-full',orders:null,song:{facts:{duration:10,orders:[
 {order:0,index:4,occurrence:'A',rows:4,playback_loop_error:'Source region maps to disjoint played spans'},
 {order:1,index:5,occurrence:'B',rows:4},
 {order:2,index:4,occurrence:'C',rows:4,playback_loop:{from:[4,0],to:[4,3]}}]}}},LV={pos:null,plan:null},solo=false;
const visits=[0,1,0,1,2].map((source,i)=>({order:i,index:10+i,id:'v'+i,
 source_order:source,source_occurrence:['A','B','C'][source],source_from:[0,1],source_to:[4,1],
 at:[i*4,1],duration:[4,1],pass:i<2?1:2,rows:4,start:i*2,seconds:2,row_times:[0,.5,1,1.5,2]}));
S.song.facts.playback_orders=visits;
eval(code+`
assert.equal(sourceVisit(0,1).visit.id,'v0');
LV.pos={playId:'v2',revision:'rev-full'};
assert.equal(sourceVisit(0,1).visit.id,'v2');
assert.equal(sourceVisit(2,1).visit.id,'v4'); // same pattern, different source occurrence
assert.throws(()=>sourceVisit(9,0),/reachable/);
const m={order:2,row:1,sourceOrder:0,sourceOccurrence:'A',sourceRow:1,
 sourceAt:[3,2],sourceScoreRow:[3,2],playId:'v2',pass:2,revision:'rev-full'};
assert.equal(sourcePosition(m).o,0);
assert.equal(sourcePosition(m).playOrder,2);
assert.deepEqual(sourcePosition(m).exactRow,[3,2]);
assert.equal(sourcePosition({...m,revision:'old'}),null);
assert.equal(sourcePosition({...m,sourceOccurrence:'C'}),null);
assert.throws(()=>patternPlaybackLoop(0),/disjoint/);
assert.deepEqual(patternPlaybackLoop(2),{from:[4,0],to:[4,3]});
S.playback_region={revision:'rev-full',from:[2,0],to:[3,3],start:4,end:8};
assert.deepEqual(playbackWindow(),{start:4,end:8});
assert.deepEqual(renderPlaybackOrders().map(x=>x.id),['v2','v3']);
S.playback_region.revision='old';
assert.equal(playbackWindow(),null);
delete S.song.facts.playback_orders;
assert.equal(playbackOrders(),null);
assert.deepEqual(sourceVisit(0,2),{order:0,row:2});
`);
"""
        result = subprocess.run([node, '-e', script], cwd=Path(__file__).resolve().parents[1],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_report_position_omits_private_playback_plan_and_visit(self):
        node = shutil.which('node')
        if not node:
            self.skipTest('node unavailable')
        script = r"""
const fs=require('fs'),assert=require('assert'),html=fs.readFileSync('vulturetracker/gui.html','utf8');
const code='function reportPlayPosition'+html.split('function reportPlayPosition')[1].split('async function agReportUI')[0];
eval(code+`
const p={o:0,row:30,exactRow:[61,2],occurrence:'A',playId:'pass2',playOrder:3,playRow:6,pass:2,
 revision:'full-revision',scoreFrame:48000,visit:{row_times:Array(4000).fill(1.234)},
 playbackPlan:{events:Array(1000).fill({id:'attack',frame:1})}};
assert(JSON.stringify(p).length>8192);
const report=reportPlayPosition(p);
assert(JSON.stringify(report).length<512);
assert(!('visit' in report));assert(!('playbackPlan' in report));
assert.equal(report.row,30);assert.equal(report.playRow,6);assert.deepEqual(report.exactRow,[61,2]);
assert.equal(report.playId,'pass2');assert.equal(reportPlayPosition(null),null);
`);
"""
        result = subprocess.run([node, '-e', script], cwd=Path(__file__).resolve().parents[1],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_fragment_source_rows_offline_time_and_backend_loop_contract(self):
        node = shutil.which('node')
        if not node:
            self.skipTest('node unavailable')
        script = r"""
const fs=require('fs'),assert=require('assert'),html=fs.readFileSync('vulturetracker/gui.html','utf8');
const helpers=html.split('// ---- source/play coordinate mapping')[1].split('// ---- song overview')[0];
const pos='function posAt'+html.split('function posAt')[1].split('function playPos')[0];
const time='function timeAt'+html.split('function timeAt')[1].split('function loopSpan')[0];
let S={version:{hash:'rev'},playback_revision:'rev-full',orders:null,
 song:{facts:{duration:8,orders:[{order:0,occurrence:'A',rows:48,playback_loop:{from:[0,0],to:[3,23]}}]}}},
 LV={pos:{playId:'tail2',revision:'rev-full'}};
S.song.facts.playback_orders=[0,1,2,3].map(i=>({id:['head1','tail1','head2','tail2'][i],
 order:i,source_order:0,source_occurrence:'A',source_from:[i%2*2,1],source_to:[i%2*2+2,1],
 at:[i*2,1],duration:[2,1],rows:24,start:i*2,seconds:2,row_times:Array.from({length:25},(_,r)=>r/12)}));
eval(helpers+pos+time+`
assert.deepEqual(sourceVisit(0,30).row,6);assert.equal(sourceVisit(0,30).order,3);
assert.deepEqual(sourceVisit(0,[61,2]).row,[13,2]);
assert.equal(sourceVisit(0,24,null).order,1);
assert.throws(()=>sourceVisit(0,48),/reachable/);
const p=posAt(6.5);assert.equal(p.row,30);assert.equal(p.playRow,6);assert.equal(p.playOrder,3);
assert.equal(timeAt(0,30),6.5);
S.playback_region={revision:'rev-full',start:6.25,end:7.5};
assert.deepEqual(renderPlaybackOrders().map(v=>v.id),['tail2']);
assert.equal(posAt(.25).row,30);assert.equal(timeAt(0,30),.25);
assert.deepEqual(patternPlaybackLoop(0),{from:[0,0],to:[3,23]});
S.song.facts.orders[0].playback_loop_error='disjoint';
assert.throws(()=>patternPlaybackLoop(0),/disjoint/);
assert.throws(()=>fragmentRowOffset({source_from:[1,13],duration:[2,1],rows:24}),/row grid/);
`);
"""
        result = subprocess.run([node, '-e', script], cwd=Path(__file__).resolve().parents[1],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
    def test_repeat_tab_playhead_uses_performed_clock_and_source_binding(self):
        node = shutil.which('node')
        if not node:
            self.skipTest('node unavailable')
        script = r"""
const fs=require('fs'),assert=require('assert'),{nativeScoreClock}=require('./vulturetracker/web/engine-core.js');
const js=fs.readFileSync('vulturetracker/web/tablature.js','utf8');
const helpers=js.slice(js.indexOf('  const gcd'),js.indexOf('  const divisions'));
const marker=js.slice(js.indexOf('    function markPlayhead()'),js.indexOf('    function setPlayhead'));
const plan={tempo:120,tempos:[{at:[0,1],bpm:120},{at:[4,1],bpm:60}],row_step:[1,12]};
let view={order:0,tempo:120,row_step:[1,12],orders:['p'],score:{order_ids:['A']},occurrences:[{id:'A',at:[0,1]}]},clock=nativeScoreClock(view),
 playbackClockPlan=null,playbackClock=null,voice=0,renderedBeats=[],api=null,track='g',board={open:false},piano={open:false};
const occurrence=()=>'A',rowStep=()=>[1,12],beats=()=>[
 {id:'first',at:[0,1],written:{value:4}},{id:'second',at:[1,1],written:{value:4}}];
const resolvedBeats=()=>beats().map(b=>({...b,track:'g',voice:0}));
const buttons=beats().map(b=>({dataset:{beat:b.id},classList:{toggle(k,on){this.on=on}}}));
const grid={querySelectorAll:()=>buttons},scoreCursor={},scoreHost={querySelector:()=>null};
let playhead={o:0,occurrence:'A',visit:{at:[8,1],source_from:[0,1],source_to:[4,1]},
 playbackPlan:plan,scoreFrame:7*48000,sampleRate:48000,factorQ:65536};
eval(helpers+marker+`
markPlayhead();
assert.deepEqual(buttons.map(b=>b.classList.on),[false,true]); // source beat 1 at performed quarter 9
playhead.scoreFrame--;
markPlayhead();assert.deepEqual(buttons.map(b=>b.classList.on),[true,false]);
playhead.occurrence='B';markPlayhead();assert(buttons.every(b=>!b.classList.on));
playhead.occurrence='A';playhead.playbackPlan=null;
markPlayhead();assert(buttons.every(b=>!b.classList.on)); // no authored clock fallback
`);
"""
        result = subprocess.run([node, '-e', script], cwd=Path(__file__).resolve().parents[1],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_repeat_reload_resolves_source_before_resuming(self):
        node = shutil.which('node')
        if not node:
            self.skipTest('node unavailable')
        script = r"""
const fs=require('fs'),assert=require('assert');
const html=fs.readFileSync('vulturetracker/gui.html','utf8');
const code='async function lvLoad'+html.split('async function lvLoad')[1].split('function lvMsg')[0];
let S={version:{hash:'new'},song:{path:'song',facts:{orders:[{occurrence:'B'},{occurrence:'A'}]}}},
 CUR={o:0,row:0},messages=[],calls=[],valid=true;
const bundle={song:'song',revision:'new-full',sample_rate:48000,backing_it:'',plan:{tempo:120}};
const fetch=async()=>({ok:true,json:async()=>bundle}),lvKey=()=>S.version.hash,
 playbackOrders=()=>[{}],renderLiveBar=()=>{},lvSync=()=>valid,REHEARSAL={active:false};
const sourceVisit=(oi,row,current)=>{calls.push([oi,row,current]);return {order:3,row}};
let LV={ctx:{sampleRate:48000},planRevision:'old-full',playing:true,
 pos:{sourceOccurrence:'A',sourceScoreRow:[13,2]},node:{port:{postMessage(m){
 messages.push(m);if(m.type==='load')queueMicrotask(()=>LV.loads[m.id].ok());
 }}}};
eval(code+`
(async()=>{
 await lvLoad(true);
 assert.deepEqual(calls,[[1,[13,2],{sourceOccurrence:'A',sourceScoreRow:[13,2],revision:'new-full'}]]);
 assert.equal(messages[0].keep,false);
 assert.equal(messages[0].revision,'new-full');
 assert.deepEqual([messages[0].order,messages[0].row],[3,[13,2]]);
 assert.deepEqual(messages[1],{type:'play',order:3,row:[13,2]});
 messages=[];calls=[];await lvLoad(true);
 assert.equal(messages[0].keep,true);assert.equal(messages.length,1);assert.equal(calls.length,0);
 LV.planRevision='old-full';messages=[];valid=false;await lvLoad(true);
 assert.equal(messages.length,1); // a refused current selection cannot be restarted after load
})().catch(e=>{console.error(e);process.exitCode=1});
`);
"""
        result = subprocess.run([node, '-e', script], cwd=Path(__file__).resolve().parents[1],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_repeat_notation_projects_authored_bars_and_additional_pass_count(self):
        node = shutil.which('node')
        if not node:
            self.skipTest('node unavailable')
        script = r"""
const fs=require('fs'),vm=require('vm'),assert=require('assert'),alphaTab=require('./vulturetracker/web/alphaTab.min.js');
const code=fs.readFileSync('./vulturetracker/web/tablature.js','utf8'),hook='window.VultureTab = {mount, mountPrint};',target={};
vm.runInNewContext(code.replace(hook,hook+'window.project=notationTrack;window.timeline=printTimeline;'),{window:target,alphaTab});
const view={orders:['a','b','a'],pattern_names:['a','b'],rows:[48,48],row_step:[1,12],score:{order_ids:['A','B','C'],tracks:{guitar:{tuning:[64,59]}},
 patterns:{a:{row_step:[1,12],beats:[]},b:{row_step:[1,12],beats:[]}},ties:[],measures:[
 {id:'A',from:{occurrence:'A',at:[0,1]},to:{occurrence:'A',at:[4,1]},meter:[4,4],repeat_open:true},
 {id:'B',from:{occurrence:'B',at:[0,1]},to:{occurrence:'B',at:[4,1]},meter:[4,4],repeat_close:100,endings:[1,8]},
 {id:'C',from:{occurrence:'C',at:[0,1]},to:{occurrence:'C',at:[4,1]},meter:[4,4]}]}};
const before=JSON.stringify(view),timeline=target.timeline(view),score=new alphaTab.model.Score();
target.project(score,'guitar',{tuning:[64,59]},timeline.ranges,timeline.source,timeline.tieTargets);
assert.equal(score.masterBars.length,3); // authored once, not the performed traversal
assert.equal(score.masterBars[0].isRepeatStart,true);
assert.equal(score.masterBars[1].repeatCount,101);
assert.equal(score.masterBars[1].alternateEndings,129);
assert.equal(score.masterBars[2].repeatCount,0);
assert.equal(JSON.stringify(view),before);
"""
        result = subprocess.run([node, '-e', script], cwd=Path(__file__).resolve().parents[1],
                                capture_output=True, text=True, encoding='utf-8')
        self.assertEqual(result.returncode, 0, result.stderr[-2000:])

    def test_fragment_notation_marks_only_actual_measure_edges(self):
        node = shutil.which('node')
        if not node:
            self.skipTest('node unavailable')
        script = r"""
const fs=require('fs'),vm=require('vm'),assert=require('assert'),alphaTab=require('./vulturetracker/web/alphaTab.min.js');
const target={},hook='window.VultureTab = {mount, mountPrint};';
vm.runInNewContext(fs.readFileSync('vulturetracker/web/tablature.js','utf8').replace(hook,
 hook+'window.project=notationTrack;window.ranges=measureRanges;'),{window:target,alphaTab});
const spec={tuning:[64]},view={orders:['p','p','p'],rows:[48],pattern_names:['p'],row_step:[1,12],score:{
 order_ids:['A','B','C'],tracks:{guitar:spec},patterns:{p:{row_step:[1,12],beats:[]}},measures:[
 {from:{occurrence:'A',at:[0,1]},to:{occurrence:'A',at:[2,1]},meter:[2,4]},
 {from:{occurrence:'A',at:[2,1]},to:{occurrence:'C',at:[0,1]},meter:[6,4],
  repeat_open:true,repeat_close:1,endings:[1,2],marker:{title:'Crossing'},swing:'eighth'},
 {from:{occurrence:'C',at:[0,1]},to:{occurrence:'C',at:[4,1]},meter:[4,4]}]}};
const bars=oid=>{const score=new alphaTab.model.Score();
 target.project(score,'guitar',spec,target.ranges(view,oid),[],new Set());return score.masterBars};
const a=bars('A'),b=bars('B'),c=bars('C');
assert.equal(a.length,2);assert.equal(a[1].isRepeatStart,true);assert.equal(a[1].repeatCount,0);
assert.equal(a[1].alternateEndings,3);assert.equal(a[1].section.text,'Crossing');
assert.equal(b.length,1);assert.equal(b[0].isRepeatStart,false);assert.equal(b[0].repeatCount,2);
assert.equal(b[0].alternateEndings,0);assert.equal(b[0].section,null);assert.equal(b[0].tripletFeel,0);
assert.equal(c.length,1);assert.equal(c[0].repeatCount,0); // B-end and C-start are one boundary
"""
        result = subprocess.run([node, '-e', script], cwd=Path(__file__).resolve().parents[1],
                                capture_output=True, text=True, encoding='utf-8')
        self.assertEqual(result.returncode, 0, result.stderr[-2000:])

    def test_tap_slap_pop_projection_mixed_voices_ties_and_fragments(self):
        node = shutil.which('node')
        if not node:
            self.skipTest('node unavailable')
        script = r"""
const fs=require('fs'),vm=require('vm'),assert=require('assert'),alphaTab=require('./vulturetracker/web/alphaTab.min.js');
const target={},hook='window.VultureTab = {mount, mountPrint};';
vm.runInNewContext(fs.readFileSync('vulturetracker/web/tablature.js','utf8').replace(hook,
 hook+'window.project=notationTrack;window.timeline=printTimeline;'),{window:target,alphaTab});
const source=[
 {id:'mixed',track:'g',voice:0,at:[0,1],written:{value:4},text:'Keep cue',notes:[
  {id:'hi',pitch:64,string:1,fret:0,tapping:true,harmonic:{type:'tapped',data:0},velocity:79},
  {id:'lo',pitch:59,string:2,fret:0,popping:true}]},
 {id:'other',track:'g',voice:1,at:[0,1],written:{value:4},notes:[{id:'other',pitch:65,string:1,fret:1,slapping:true}]},
 {id:'tail',track:'g',voice:0,at:[1,1],written:{value:4},notes:[{id:'tail',pitch:64,string:1,fret:0,tapping:true}]}];
const view={orders:['p'],pattern_names:['p'],rows:[48],row_step:[1,12],score:{order_ids:['o'],
 tracks:{g:{tuning:[64,59]}},patterns:{p:{row_step:[1,12],beats:source}},
 ties:[{from:{occurrence:'o',note:'hi'},to:{occurrence:'o',note:'tail'}}]}};
const before=JSON.stringify(view),timeline=target.timeline(view),score=new alphaTab.model.Score(),seen=[];
target.project(score,'g',view.score.tracks.g,
 [{from:[0,1],to:[1,2],meter:[1,8],authored:true},{from:[1,2],to:[4,1],meter:[7,8],authored:true}],
 timeline.source,timeline.tieTargets,(b,o,at,end,voice)=>seen.push({b,o,voice}));
score.finish(new alphaTab.Settings());
const marked=seen.filter(x=>x.b.tap||x.b.slap||x.b.pop);
assert.deepStrictEqual(marked.map(x=>[x.o.id,x.voice,x.b.tap,x.b.slap,x.b.pop]),
 [['other',1,false,true,false],['tail',0,true,false,false]]);
const mixed=seen.filter(x=>x.b.text?.includes('Tap: string 1'));
assert.equal(mixed.length,1);assert(mixed[0].b.text.includes('Pop: string 2'));assert(mixed[0].b.text.includes('Keep cue'));
assert(!mixed[0].b.tap&&!mixed[0].b.slap&&!mixed[0].b.pop);
assert.equal(mixed[0].b.notes.find(n=>n.string===2).harmonicType,alphaTab.model.HarmonicType.Tap);
assert.equal(JSON.stringify(view),before);
for (const type of ['natural','artificial','tapped','pinch','semi']) for (const [flag,letter] of [['tapping','T'],['slapping','S'],['popping','P']]) {
 const s=new alphaTab.model.Score(),ns=[{id:'h',pitch:76,string:1,fret:12,harmonic:{type,data:0},[flag]:true}],bs=[];
 target.project(s,'g',view.score.tracks.g,[{from:[0,1],to:[4,1],meter:[4,4]}],
  [{id:'h',track:'g',voice:0,at:[0,1],written:{value:4},text:'Keep cue',notes:ns}],new Set(),b=>bs.push(b));
 assert.equal(bs[0].text,'Keep cue');assert(bs[0][{T:'tap',S:'slap',P:'pop'}[letter]]);
 assert.notEqual(bs[0].notes[0].harmonicType,alphaTab.model.HarmonicType.None);
}
"""
        result = subprocess.run([node, '-e', script], cwd=Path(__file__).resolve().parents[1],
                                capture_output=True, text=True, encoding='utf-8')
        self.assertEqual(result.returncode, 0, result.stderr[-2000:])

    def test_chord_note_impact_resolved_strings_reused_ties_and_all_muted(self):
        node = shutil.which('node')
        if not node:
            self.skipTest('node unavailable')
        script = r"""
const fs=require('fs'),vm=require('vm'),assert=require('assert'),target={},hook='window.VultureTab = {mount, mountPrint};';
vm.runInNewContext(fs.readFileSync('vulturetracker/web/tablature.js','utf8').replace(hook,
 hook+'window.impact=chordNoteImpact;'),{window:target});
const own={id:'own',track:'g',voice:0,at:[0,1],notes:[{id:'a',string:2}]},
 other={id:'other',track:'g',voice:1,at:[0,2],notes:[{id:'b'},{id:'c',string:3}]};
const view={order:0,orders:['p','p'],positions:[{kind:'note',pattern:'p',occurrence:'first',note:'b',string:1,fret:0}],
 score:{order_ids:['first','again'],patterns:{p:{beats:[own,other]}},ties:[
 {from:{occurrence:'first',note:'a'},to:{occurrence:'first',note:'tail'}},
 {from:{occurrence:'again',note:'b'},to:{occurrence:'again',note:'tail2'}}]}};
const before=JSON.stringify(view),chord={frets:[0,-1,-1]},i=target.impact(view,'p','own',chord);
assert.equal(i.affected.length,1);assert.equal(i.affected[0].id,'b');assert.equal(i.uses,2);assert.equal(i.ties.length,2);
assert.equal(i.unresolved.length,0);assert(!i.noOp);assert.equal(JSON.stringify(view),before);
view.positions=[];assert.equal(target.impact(view,'p','own',chord).unresolved[0].id,'b');
const muted={frets:[-1,-1,-1]};assert.equal(target.impact(view,'p','own',muted).affected.length,0);
own.notes=[];assert(!target.impact(view,'p','own',muted).noOp);
other.notes=[];assert(target.impact(view,'p','own',muted).noOp);
"""
        result = subprocess.run([node, '-e', script], cwd=Path(__file__).resolve().parents[1],
                                capture_output=True, text=True, encoding='utf-8')
        self.assertEqual(result.returncode, 0, result.stderr[-2000:])

    def test_chord_diagram_projection_sparse_rest_anchor_auto_fret_and_unique_ids(self):
        node = shutil.which('node')
        if not node:
            self.skipTest('node unavailable')
        script = r"""
const fs=require('fs'),vm=require('vm'),assert=require('assert'),alphaTab=require('./vulturetracker/web/alphaTab.min.js');
const target={},hook='window.VultureTab = {mount, mountPrint};';
vm.runInNewContext(fs.readFileSync('vulturetracker/web/tablature.js','utf8').replace(hook,
 hook+'window.project=notationTrack;window.timeline=printTimeline;'),{window:target,alphaTab});
const open={name:'C',first_fret:0,frets:[0,1,0,2,3,-1]},
 high={name:'C',first_fret:8,frets:[8,10,8,9,10,-1]},muted={name:'',first_fret:0,frets:Array(6).fill(-1)};
const source=[
 {id:'rest',track:'guitar',voice:0,at:[0,2],written:{value:4},notes:[]},
 {id:'sparse',track:'guitar',voice:1,at:[0,1],written:{value:4},chord:open,notes:[{id:'n',pitch:64,string:1,fret:0}]},
 {id:'high',track:'guitar',voice:0,at:[1,1],written:{value:4},chord:high,notes:[]},
 {id:'muted',track:'guitar',voice:1,at:[2,1],written:{value:4},chord:muted,notes:[]}];
const view={orders:['p'],pattern_names:['p'],rows:[48],row_step:[1,12],score:{order_ids:['o'],
 tracks:{guitar:{tuning:[64,59,55,50,45,40]}},patterns:{p:{row_step:[1,12],beats:source}},ties:[]}};
const before=JSON.stringify(view),timeline=target.timeline(view),score=new alphaTab.model.Score(),anchors=[];
const ranges=[{from:[0,1],to:[1,2],meter:[1,8],authored:true},{from:[1,2],to:[4,1],meter:[7,8],authored:true}];
target.project(score,'guitar',view.score.tracks.guitar,ranges,timeline.source,timeline.tieTargets,
 (b,o,at,end,v)=>{if(b.chordId)anchors.push({id:o.id,voice:v,chordId:b.chordId,chord:b.chord})});
score.finish(new alphaTab.Settings());
assert.equal(anchors.length,3);assert.deepStrictEqual(anchors.map(x=>x.voice),[0,0,1]);
assert.equal(new Set(anchors.map(x=>x.chordId)).size,3);
assert.deepStrictEqual(anchors.map(x=>x.chord.firstFret),[1,8,1]);
assert.equal(JSON.stringify(anchors.map(x=>x.chord.strings)),JSON.stringify([open.frets,high.frets,muted.frets]));
assert(anchors.every(x=>x.chord.showDiagram&&!x.chord.showFingering&&!x.chord.barreFrets.length));
assert(!anchors[2].chord.showName);
assert.equal(JSON.stringify(view),before);
"""
        result = subprocess.run([node, '-e', script], cwd=Path(__file__).resolve().parents[1],
                                capture_output=True, text=True, encoding='utf-8')
        self.assertEqual(result.returncode, 0, result.stderr[-2000:])

    def test_fade_projection_preserves_sparse_chords_voices_and_tied_markings(self):
        node = shutil.which('node')
        if not node:
            self.skipTest('node unavailable')
        script = r"""
const fs=require('fs'),vm=require('vm'),assert=require('assert'),alphaTab=require('./vulturetracker/web/alphaTab.min.js');
const target={},hook='window.VultureTab = {mount, mountPrint};';
vm.runInNewContext(fs.readFileSync('vulturetracker/web/tablature.js','utf8').replace(hook,
 hook+'window.project=notationTrack;window.timeline=printTimeline;'),{window:target,alphaTab});
const source=[
 {id:'chord',track:'guitar',voice:0,at:[0,1],written:{value:4},text:'Keep cue',notes:[
   {id:'hi',pitch:64,string:1,fret:0,fade_in:true},{id:'lo',pitch:59,string:2,fret:0}]},
 {id:'other',track:'guitar',voice:1,at:[0,1],written:{value:4},notes:[{id:'other',pitch:65,string:1,fret:1}]},
 {id:'tail',track:'guitar',voice:0,at:[1,1],written:{value:4},notes:[{id:'tail',pitch:64,string:1,fret:0,fade_in:true}]}];
const view={orders:['p'],pattern_names:['p'],rows:[48],row_step:[1,12],score:{order_ids:['o'],
 tracks:{guitar:{tuning:[64,59]}},patterns:{p:{row_step:[1,12],beats:source}},
 ties:[{from:{occurrence:'o',note:'hi'},to:{occurrence:'o',note:'tail'}}]}};
for(const uniform of [false,true]){
 source[0].notes[1].fade_in=uniform;
 const before=JSON.stringify(view),timeline=target.timeline(view),score=new alphaTab.model.Score();
 target.project(score,'guitar',view.score.tracks.guitar,timeline.ranges,timeline.source,timeline.tieTargets);
 score.finish(new alphaTab.Settings());
 const voices=score.tracks[0].staves[0].bars[0].voices,chord=voices[0].beats[0],tail=voices[0].beats[1];
 assert.equal(chord.fade,uniform?alphaTab.model.FadeType.FadeIn:alphaTab.model.FadeType.None);
 assert(chord.text.includes('Keep cue')&&!chord.text.includes('MIDI track expression'));
 if(!uniform)assert(chord.text.includes('Fade-in: string 1'));else assert.equal(chord.text,'Keep cue');
 assert.equal(voices[1].beats[0].fade,alphaTab.model.FadeType.None);
 assert.equal(tail.fade,alphaTab.model.FadeType.FadeIn);assert(tail.notes[0].isTieDestination);assert(!tail.text);
 assert.deepStrictEqual([chord.displayStart,chord.displayDuration,tail.displayStart,tail.displayDuration],[0,960,960,960]);
 assert.equal(JSON.stringify(view),before);
}
"""
        result = subprocess.run([node, '-e', script], cwd=Path(__file__).resolve().parents[1],
                                capture_output=True, text=True, encoding='utf-8')
        self.assertEqual(result.returncode, 0, result.stderr[-2000:])

    def test_stroke_and_pick_projection_are_shared_glyphs_with_written_anchors(self):
        node = shutil.which('node')
        if not node:
            self.skipTest('node unavailable')
        script = r"""
const fs=require('fs'),vm=require('vm'),assert=require('assert'),alphaTab=require('./vulturetracker/web/alphaTab.min.js');
const target={},hook='window.VultureTab = {mount, mountPrint};';
vm.runInNewContext(fs.readFileSync('vulturetracker/web/tablature.js','utf8').replace(hook,
 hook+'window.project=notationTrack;window.timeline=printTimeline;'),{window:target,alphaTab});
const stroke={direction:'down',value:4},source=[
 {id:'chord',track:'guitar',voice:0,at:[0,1],written:{value:4},text:'Keep cue',stroke,pick_stroke:'up',notes:[
   {id:'hi',pitch:64,string:1,fret:0},{id:'lo',pitch:59,string:2,fret:0}]},
 {id:'rest',track:'guitar',voice:1,at:[0,1],written:{value:16},stroke,pick_stroke:'up',notes:[]}];
const view={orders:['p'],pattern_names:['p'],rows:[48],row_step:[1,12],score:{order_ids:['o'],
 tracks:{guitar:{tuning:[64,59]}},patterns:{p:{row_step:[1,12],beats:source}},ties:[]}};
for(const holder of ['both',0,1]){
source.forEach((b,i)=>{delete b.stroke;delete b.pick_stroke;if(holder==='both'||holder===i){b.stroke=stroke;b.pick_stroke='up'}});
const before=JSON.stringify(view),timeline=target.timeline(view),score=new alphaTab.model.Score(),anchors=[];
target.project(score,'guitar',view.score.tracks.guitar,timeline.ranges,timeline.source,timeline.tieTargets,
 (b,o,at,end,v)=>{if(o)anchors.push([o.id,at,end,v])});
score.finish(new alphaTab.Settings());
const voices=score.tracks[0].staves[0].bars[0].voices,main=voices[0].beats[0],rest=voices[1].beats[0];
assert.equal(main.brushType,alphaTab.model.BrushType.BrushDown);
assert.equal(main.pickStroke,alphaTab.model.PickStroke.Up);
assert.strictEqual(main.text,'Keep cue');
assert.equal(rest.brushType,0);assert.equal(rest.pickStroke,0); // one cohort glyph
assert.equal(main.displayStart,0);assert.equal(main.displayDuration,960);
assert.equal(rest.displayStart,0);assert.equal(rest.displayDuration,240);
assert.equal(JSON.stringify(view),before);
}
"""
        result = subprocess.run([node, '-e', script], cwd=Path(__file__).resolve().parents[1],
                                capture_output=True, text=True, encoding='utf-8')
        self.assertEqual(result.returncode, 0, result.stderr[-2000:])

    def test_repetition_projection_uses_note_trills_and_scoped_tremolo(self):
        node = shutil.which('node')
        if not node:
            self.skipTest('node unavailable')
        script = """
const fs=require('fs'),vm=require('vm'),assert=require('assert'),alphaTab=require('./vulturetracker/web/alphaTab.min.js');
const testWindow={},hook='window.VultureTab = {mount, mountPrint};';
const code=fs.readFileSync('./vulturetracker/web/tablature.js','utf8');
assert(code.includes(hook));
vm.runInNewContext(code.replace(hook,hook+'window.project=notationTrack;'),{window:testWindow,alphaTab});
const spec={tuning:[64,59],capo:2},note=(id,string,extra={})=>({id,string,fret:0,pitch:spec.tuning[string-1]+2,...extra});
const source=[
 {id:'trill',voice:0,at:[0,1],written:{value:4},notes:[note('t',1,{trill:{fret:7,value:4}}),note('plain',2,{let_ring:true})]},
 {id:'both',voice:0,at:[1,1],written:{value:2},notes:[note('a',1,{tremolo_picking:{value:16}}),note('b',2,{tremolo_picking:{value:16}})]},
 {id:'mixed',voice:0,at:[3,1],written:{value:4},text:'Keep cue',notes:[note('c',1,{tremolo_picking:{value:8}}),note('d',2)]}
];
const before=JSON.stringify(source),score=new alphaTab.model.Score();
testWindow.project(score,'guitar',spec,[{from:[0,1],to:[4,1],meter:[4,4],authored:true}],source,new Set());
score.finish(new alphaTab.Settings());
const beats=score.tracks[0].staves[0].bars[0].voices[0].beats;
assert.strictEqual(beats[0].notes[0].trillValue,73);
assert.strictEqual(beats[0].notes[0].trillFret,7);
assert.strictEqual(beats[0].notes[0].trillSpeed,4);
assert.strictEqual(beats[0].notes[1].isTrill,false);
assert.strictEqual(beats[0].notes[0].isLetRing,false);
assert.strictEqual(beats[0].notes[1].isLetRing,true);
assert.strictEqual(beats[1].tremoloSpeed,16);
assert.strictEqual(beats[1].tremoloPicking.marks,3);
assert.strictEqual(beats[2].isTremolo,false);
assert(beats[2].text.includes('Keep cue'));
assert(beats[2].text.includes('Tremolo picking: string 1 1/8'));
assert.strictEqual(JSON.stringify(source),before);
"""
        result = subprocess.run([node, '-e', script], cwd=Path(__file__).resolve().parents[1],
                                capture_output=True, text=True, encoding='utf-8')
        self.assertEqual(result.returncode, 0, result.stderr[-2000:])

    def test_grace_projection_keeps_written_voices_anchors_and_mixed_timing(self):
        node = shutil.which('node')
        if not node:
            self.skipTest('node unavailable')
        script = """
const fs=require('fs'),vm=require('vm'),assert=require('assert'),alphaTab=require('./vulturetracker/web/alphaTab.min.js');
const target={},hook='window.VultureTab = {mount, mountPrint};';
vm.runInNewContext(fs.readFileSync('./vulturetracker/web/tablature.js','utf8').replace(hook,hook+'window.project=notationTrack;'),{window:target,alphaTab});
const grace=(value,on_beat=false)=>({fret:2,value,velocity:47,on_beat,transition:'slide'});
const note=(id,string,g)=>({id,string,fret:0,pitch:string===1?64:59,grace:g});
const source=[
 {id:'first',voice:0,at:[0,1],written:{value:4},text:'Keep grace cue',notes:[note('a',1,grace(16)),note('b',2,grace(64))]},
 {id:'mixed',voice:0,at:[1,1],written:{value:4},notes:[note('c',1,grace(32,true)),note('d',2,grace(16))]},
 {id:'voice1',voice:1,at:[0,1],written:{value:2},notes:[note('e',1,grace(32,true))]}
],before=JSON.stringify(source),score=new alphaTab.model.Score(),refs=[],anchors=[];
target.project(score,'guitar',{tuning:[64,59]},[{from:[0,1],to:[4,1],meter:[4,4],authored:true}],
 source,new Set(),(b,o,start,end,v)=>{if(o)anchors.push([b.graceType,o.id,start,end,v]);},
 (n,o,b,v)=>refs.push([o.id,b.id,v]));
score.finish(new alphaTab.Settings());
const voices=score.tracks[0].staves[0].bars[0].voices;
assert.strictEqual(voices.length,2);
assert.strictEqual(voices[0].beats.filter(b=>b.graceType!==0).length,1);
assert.deepStrictEqual(voices[0].beats[0].notes.map(n=>n.fret),[2,2]);
assert.strictEqual(voices[0].beats[0].displayDuration,0);
const mains=voices[0].beats.filter(b=>b.graceType===0);
assert.deepStrictEqual(mains.slice(0,2).map(b=>[b.duration,b.displayStart,b.displayDuration]),[[4,0,960],[4,960,960]]);
assert.strictEqual(mains[0].text,'Keep grace cue');
assert.strictEqual(mains[1].text,'Grace (mixed timing)');
assert(voices[0].beats[0].notes.every(n=>n.slideOutType===0&&!n.isHammerPullOrigin));
assert.strictEqual(voices[1].beats[0].graceType,alphaTab.model.GraceType.OnBeat);
assert.strictEqual(voices[1].beats[1].duration,2);
assert(voices.every(v=>v.beats.reduce((n,b)=>n+b.displayDuration,0)===3840));
assert.deepStrictEqual(anchors[0],[alphaTab.model.GraceType.BeforeBeat,'first',[0,1],[0,1],0]);
assert.strictEqual(refs.filter(r=>r[0]==='a'&&r[1]==='first').length,2);
assert.strictEqual(JSON.stringify(source),before);
"""
        result = subprocess.run([node, '-e', script], cwd=Path(__file__).resolve().parents[1],
                                capture_output=True, text=True, encoding='utf-8')
        self.assertEqual(result.returncode, 0, result.stderr[-2000:])

    def test_swing_projection_and_print_keep_straight_written_positions(self):
        node = shutil.which('node')
        if not node:
            self.skipTest('node unavailable')
        script = """
const fs=require('fs'),vm=require('vm'),assert=require('assert'),alphaTab=require('./vulturetracker/web/alphaTab.min.js');
const target={},hook='window.VultureTab = {mount, mountPrint};';
vm.runInNewContext(fs.readFileSync('./vulturetracker/web/tablature.js','utf8').replace(hook,hook+'window.projection={notationTrack,printTimeline};'),{window:target,alphaTab});
const beat=(id,at,value)=>({id,track:'guitar',voice:0,at,written:{value},notes:[{id:id+'-note',pitch:64,string:1,fret:0}]});
const view={orders:['p'],pattern_names:['p'],rows:[144],row_step:[1,12],score:{
 order_ids:['o'],tracks:{guitar:{tuning:[64]}},ties:[],patterns:{p:{row_step:[1,12],beats:[
 beat('e0',[0,1],8),beat('e1',[1,2],8),beat('s0',[4,1],16),beat('s1',[17,4],16),beat('plain',[8,1],4)]}},
 measures:['eighth','sixteenth','none'].map((swing,i)=>({id:'m'+i,swing,meter:[4,4],
 from:{occurrence:'o',at:[i*4,1]},to:{occurrence:'o',at:[(i+1)*4,1]},
 marker:{title:'Part '+i,color:'#123456'}}))}};
const before=JSON.stringify(view),timeline=target.projection.printTimeline(view),score=new alphaTab.model.Score();
target.projection.notationTrack(score,'guitar',view.score.tracks.guitar,timeline.ranges,timeline.source,timeline.tieTargets);
score.finish(new alphaTab.Settings());
assert.deepStrictEqual(score.masterBars.map(b=>b.tripletFeel),[
 alphaTab.model.TripletFeel.Triplet8th,alphaTab.model.TripletFeel.Triplet16th,alphaTab.model.TripletFeel.NoTripletFeel]);
const bars=score.tracks[0].staves[0].bars;
assert.deepStrictEqual(bars[0].voices[0].beats.slice(0,2).map(b=>[b.duration,b.displayStart,b.displayDuration]),[[8,0,480],[8,480,480]]);
assert.deepStrictEqual(bars[1].voices[0].beats.slice(0,2).map(b=>[b.duration,b.displayStart,b.displayDuration]),[[16,0,240],[16,240,240]]);
assert.strictEqual(score.masterBars[0].section.text,'Part 0');
assert.strictEqual(JSON.stringify(view),before);
"""
        result = subprocess.run([node, '-e', script], cwd=Path(__file__).resolve().parents[1],
                                capture_output=True, text=True, encoding='utf-8')
        self.assertEqual(result.returncode, 0, result.stderr[-2000:])

    def test_full_song_projection_without_browser(self):
        node = shutil.which('node')
        if not node:
            self.skipTest('node unavailable')
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(gui, 'remember_song'):
            folder = Path(tmp)
            write_wav(folder / 'a.wav', RATE, [sine(440)])
            path = folder / 'song.yaml'
            path.write_bytes(PRINT_SONG.encode('utf-8'))
            state = gui.State(path, headless=True)
            try:
                self.assertFalse(state.error, state.error)
                script = """
const fs=require('fs'), vm=require('vm'), assert=require('assert');
const alphaTab=require('./vulturetracker/web/alphaTab.min.js'), testWindow={};
let code=fs.readFileSync('./vulturetracker/web/tablature.js','utf8');
const hook='window.VultureTab = {mount, mountPrint};';
assert(code.includes(hook));
vm.runInNewContext(code.replace(hook, hook+'window.projection={printTimeline,notationTrack};'), {window:testWindow,alphaTab});
const view=JSON.parse(fs.readFileSync(0,'utf8'));
view.score.measures[1].double_bar=true;
const lead=Object.keys(view.score.tracks)[0];
view.score.tracks[lead].key={fifths:0,mode:'major'};
view.score.measures[1].staff={[lead]:{key:{fifths:2,mode:'major'}}};
const before=JSON.stringify(view);
const p=testWindow.projection.printTimeline(view), score=new alphaTab.model.Score();
for(const [id,spec] of Object.entries(view.score.tracks)) testWindow.projection.notationTrack(score,id,spec,p.ranges,p.source.filter(b=>b.track===id),p.tieTargets);
score.finish(new alphaTab.Settings());
assert.strictEqual(JSON.stringify(view),before);
assert.deepStrictEqual(score.masterBars.map(b=>[b.timeSignatureNumerator,b.timeSignatureDenominator]),[[6,4],[2,4],[8,4]]);
const notes=score.tracks[0].staves[0].bars.flatMap(b=>b.voices[0].beats.flatMap(b=>b.notes));
assert.deepStrictEqual(notes.map(n=>n.realValue),[65,65,65,65,65]);
assert.deepStrictEqual(notes.map(n=>n.isTieDestination),[false,true,true,false,false]);
assert.strictEqual(notes[1].tieOrigin,notes[0]);
assert.strictEqual(notes[2].tieOrigin,notes[1]);
assert.strictEqual(score.tracks[1].staves[0].bars.length,3);
assert.deepStrictEqual(score.masterBars.map(b=>b.isDoubleBar),[false,true,false]);
assert.deepStrictEqual(score.tracks[0].staves[0].bars.map(b=>b.keySignature),[0,2,2]);
"""
                result = subprocess.run([node, '-e', script], input=json.dumps(state.score_view()), capture_output=True,
                                        text=True, encoding='utf-8', cwd=Path(__file__).resolve().parents[1])
                self.assertEqual(result.returncode, 0, result.stderr[-3000:])
            finally:
                state.close()

    def test_native_print_resolves_each_occurrence(self):
        node = shutil.which('node')
        if not node:
            self.skipTest('node unavailable')
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(gui, 'remember_song'):
            folder = Path(tmp)
            write_wav(folder / 'a.wav', RATE, [sine(440)])
            path = folder / 'song.yaml'
            path.write_bytes(NATIVE_SONG.encode('utf-8'))
            state = gui.State(path, headless=True)
            try:
                self.assertFalse(state.error, state.error)
                view = state.score_view()
                self.assertTrue(view['native'])
                script = """
const fs=require('fs'), vm=require('vm'), assert=require('assert');
const alphaTab=require('./vulturetracker/web/alphaTab.min.js'), testWindow={};
let code=fs.readFileSync('./vulturetracker/web/tablature.js','utf8');
const hook='window.VultureTab = {mount, mountPrint};';
assert(code.includes(hook));
vm.runInNewContext(code.replace(hook,hook+'window.projection={printTimeline,notationTrack};'),{window:testWindow,alphaTab});
const view=JSON.parse(fs.readFileSync(0,'utf8'));
// Print snapshots have no active order. Editor snapshots may be on any repeat.
for(const order of [undefined,2]){
  view.order=order; const before=JSON.stringify(view);
  const p=testWindow.projection.printTimeline(view), score=new alphaTab.model.Score();
  assert.strictEqual(p.source.length,39);
  for(const beat of p.source) for(const note of beat.notes){
    const [occurrence,id]=JSON.parse(note.id);
    const position=view.positions.find(p=>p.occurrence===occurrence&&p.note===id);
    assert(position);
    assert.strictEqual(note.string,position.string);
    assert.strictEqual(note.fret,position.fret);
  }
  testWindow.projection.notationTrack(score,'guitar',view.score.tracks.guitar,p.ranges,p.source,p.tieTargets);
  score.finish(new alphaTab.Settings());
  const notes=score.tracks[0].staves[0].bars.flatMap(b=>b.voices[0].beats.flatMap(b=>b.notes));
  assert.strictEqual(notes.length,39);
  assert.deepStrictEqual(notes.flatMap((n,i)=>n.isTieDestination?[i]:[]),[13]);
  assert.strictEqual(notes[13].tieOrigin,notes[12]);
  assert.strictEqual(JSON.stringify(view),before);
}
"""
                result = subprocess.run([node, '-e', script], input=json.dumps(view), capture_output=True,
                                        text=True, encoding='utf-8', cwd=Path(__file__).resolve().parents[1])
                self.assertEqual(result.returncode, 0, result.stderr[-3000:])
            finally:
                state.close()

    def test_tie_and_raw_fixtures_compile_in_state(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(gui, 'remember_song'):
            folder = Path(tmp)
            write_wav(folder / 'a.wav', RATE, [sine(440)])
            for name, source in [('tie', TIE_SONG), ('raw', RAW_SONG), ('print', PRINT_SONG)]:
                with self.subTest(fixture=name):
                    path = folder / (name + '.yaml')
                    path.write_bytes(source.encode('utf-8'))
                    state = gui.State(path, headless=True)
                    try:
                        self.assertIsNone(state.error, state.error)
                        view = state.score_view()
                        if name == 'tie':
                            self.assertEqual([(p['row'], p['end_row']) for p in view['positions'] if p['kind'] == 'note'], [([0, 1], [4, 1]), ([4, 1], [8, 1])])
                        elif name == 'raw':
                            self.assertEqual([(p['row'], p['end_row'], p['pitch']) for p in view['raw_positions']], [(0, [4, 1], 64)])
                        else:
                            self.assertEqual(len(view['score']['measures']), 3)
                    finally:
                        state.close()


@unittest.skipIf(page_fixture.sync_playwright is None, 'playwright not installed')
class TestTablaturePage(unittest.TestCase):
    @contextmanager
    def muted_page(self, *args, **kwargs):
        from playwright.sync_api import BrowserType
        launch = BrowserType.launch

        def muted(browser, **options):
            options['args'] = [*(options.get('args') or []), '--mute-audio']
            if os.environ.get('VT_HEADED') == '1':
                options['headless'] = False
            return launch(browser, **options)

        with mock.patch.object(BrowserType, 'launch', muted):
            with self.page(*args, **kwargs) as result:
                yield result

    def test_pattern_order_controls_browse_short_bars_without_editing(self):
        song = api.from_yaml(SONG)
        song['orders'] = ['verse'] * 3
        song['score']['order_ids'] = ['first', 'second', 'third']
        with self.muted_page(api.to_yaml(song), compact=True) as (page, state, folder):
            original = (folder/'song.yaml').read_bytes()
            history = list(state.history)
            errors = []
            page.on('pageerror', lambda e: errors.append(str(e)))
            page.evaluate("tab('pattern')")
            page.wait_for_function('PAT.rows?.length>0')
            page.uncheck('#pat-continuous')  # Retained single-pattern navigation mode.
            count = page.locator('#pat-order option').count()
            self.assertGreater(count, 1)
            page.select_option('#pat-order', '0')
            self.assertTrue(page.locator('#pat-prev').is_disabled())
            page.click('#pat-next')
            page.wait_for_function('PAT.order===1 && PAT.rows?.length>0')
            self.assertFalse(page.is_checked('#pat-follow'))
            # A short bar has nothing inside it to scroll; wheel crosses into the next order.
            page.locator('#patscroll').hover()
            page.mouse.wheel(0, -500)
            page.wait_for_function('PAT.order===0 && PAT.rows?.length>0')
            page.mouse.wheel(0, -500)
            self.assertEqual(page.evaluate('PAT.order'), 0)
            page.select_option('#pat-order', str(count-1))
            page.wait_for_function(f'PAT.order==={count-1} && PAT.rows?.length>0')
            self.assertTrue(page.locator('#pat-next').is_disabled())
            page.mouse.wheel(0, 500)
            self.assertEqual(page.evaluate('PAT.order'), count-1)
            self.assertEqual(page.evaluate('viewOrder()'), count-1)
            page.check('#pat-follow')
            self.assertTrue(page.is_checked('#pat-follow'))
            self.assertEqual((folder/'song.yaml').read_bytes(), original)
            self.assertEqual(list(state.history), history)
            self.assertEqual(errors, [])

    def test_continuous_pattern_scroll_select_edit_and_follow(self):
        song = api.from_yaml(RAW_SONG)
        song['patterns']['verse']['rows'] = 8
        song['orders'] = ['verse'] * 40
        song['score']['order_ids'] = [f'occ-{i}' for i in range(40)]
        with self.muted_page(api.to_yaml(song), compact=True, width=1920, height=1040) as (page, state, folder):
            original = (folder/'song.yaml').read_bytes()
            errors = []
            page.on('pageerror', lambda e: errors.append(str(e)))
            page.evaluate("tab('pattern')")
            page.wait_for_selector('.pat-preview[data-order="1"] .pat-preview-row')
            self.assertTrue(page.is_checked('#pat-continuous'))
            visible = """()=>{const r=$('patscroll').getBoundingClientRect();return [...document.querySelectorAll('.pat-song-title')].filter(e=>{const b=e.getBoundingClientRect();return b.top>=r.top&&b.bottom<=r.bottom}).length}"""
            self.assertGreaterEqual(page.evaluate(visible), 3)
            page.locator('#patscroll').hover()
            page.mouse.wheel(0, 650)
            page.wait_for_function("$('patscroll').scrollTop>500")
            self.assertFalse(page.is_checked('#pat-follow'))
            # Scrollbar reaches the last occurrence without changing the document.
            page.locator('#patscroll').evaluate('(e)=>e.scrollTop=e.scrollHeight')
            page.wait_for_selector('.pat-preview[data-order="39"] .pat-preview-row')
            page.click('.pat-preview[data-order="39"] .pat-preview-row[data-row="0"] [data-ch="0"]')
            page.wait_for_function("PAT.order===39&&PAT.rows?.length===8&&CUR.o===39")
            self.assertEqual(page.evaluate('PAT.occurrence'), 'occ-39')
            self.assertEqual((folder/'song.yaml').read_bytes(), original)
            page.evaluate('setEdit(true)')
            page.click('#pat .pt[data-r="0"] .n')
            page.keyboard.press('Delete')
            self.settled(page, "PAT.rows?.[0]?.[0].startsWith('...')")
            edited = (folder/'song.yaml').read_bytes()
            self.assertNotEqual(edited, original)
            page.click('#lv-undo')
            self.settled(page, "PAT.rows?.[0]?.[0].startsWith('E-5')")
            self.assertEqual((folder/'song.yaml').read_bytes(), original)
            page.click('#lv-redo')
            self.settled(page, "PAT.rows?.[0]?.[0].startsWith('...')")
            self.assertEqual((folder/'song.yaml').read_bytes(), edited)
            # A repeated pattern's preview must refresh after edit/Undo/Redo.
            page.locator('#patscroll').evaluate('(e)=>e.scrollTop=0')
            page.wait_for_function("document.querySelector('.pat-preview[data-order=\"0\"] [data-ch=\"0\"]')?.textContent.startsWith('...')")
            page.evaluate('setEdit(false)')
            page.check('#pat-follow')
            page.click('#livebar [onclick="lvPlay(0,0,true)"]')
            page.wait_for_function('LV.playing&&PAT.order<3&&PAT.rows?.length>0')
            page.wait_for_function("PAT.order>=1&&!!document.querySelector('#pat .pt.now')", timeout=20000)
            self.assertTrue(page.is_checked('#pat-follow'))
            self.assertLess(page.evaluate("$('patscroll').scrollTop"), 2000)
            page.evaluate('lvStop()')
            self.assertEqual(errors, [])

    def test_continuous_native_occurrence_columns_keyboard_and_undo(self):
        song = api.from_yaml(SONG)
        song['orders'] = ['verse'] * 8
        song['score']['order_ids'] = [f'occ-{i}' for i in range(8)]
        with self.muted_page(api.to_yaml(song), compact=True, width=1920, height=1040) as (page, state, folder):
            original = (folder/'song.yaml').read_bytes()
            page.evaluate("tab('pattern')")
            page.wait_for_selector('.pat-preview[data-order="1"] .pat-preview-row')
            page.click('.pat-preview[data-order="1"] .pat-preview-row[data-row="0"] [data-ch="0"] [data-col="2"]')
            page.wait_for_function('PAT.order===1&&PAT.rows?.length>0&&CUR.col===2')
            self.assertEqual(page.evaluate('PAT.occurrence'), 'occ-1')
            self.assertTrue(page.evaluate("PAT.score_positions.every(p=>p.occurrence==='occ-1')"))
            page.click('#lv-edit')
            page.click('#pat .pt[data-r="0"] .n >> nth=0')
            page.keyboard.press('Delete')
            self.settled(page, 'S.undo===1')
            self.assertEqual(state.song['score']['patterns']['verse']['beats'][0]['notes'], [])
            edited = (folder/'song.yaml').read_bytes()
            page.click('#lv-undo'); self.settled(page, 'S.undo===0')
            self.assertEqual((folder/'song.yaml').read_bytes(), original)
            page.click('#lv-redo'); self.settled(page, 'S.undo===1')
            self.assertEqual((folder/'song.yaml').read_bytes(), edited)
            page.click('#pat .pt[data-r="0"] .n >> nth=0')
            page.keyboard.press('ArrowUp')
            page.wait_for_function('PAT.order===0&&CUR.o===0&&CUR.row===24&&PAT.rows?.length===25')
            page.keyboard.press('ArrowDown')
            page.wait_for_function('PAT.order===1&&CUR.o===1&&CUR.row===0&&PAT.rows?.length===25')
            self.assertEqual((folder/'song.yaml').read_bytes(), edited)

    def test_tuxguitar_view_preset_preserves_pitch_and_history(self):
        with self.muted_page(api.to_yaml(self.score_view_song()), compact=True, width=1920, height=1040) as (page, state, folder):
            original = (folder/'song.yaml').read_bytes()
            history = list(state.history)
            page.evaluate("tab('tab')")
            page.wait_for_selector('.vt-tab-score svg')
            self.capture_engraving(page)
            page.click('[data-ui=view-tuxguitar]')
            page.wait_for_function('window.tabRendered && tabRenderApi.boundsLookup?.isFinished')
            self.assertEqual(page.get_attribute('.vt-tab-score', 'data-layout'), 'horizontal')
            self.assertEqual(page.get_attribute('.vt-tab-score', 'data-tracks'), 'guitar,guitar2,bass,drums')
            self.assertFalse(page.is_checked('[data-ui=view-dynamics]'))
            self.assertEqual(page.input_value('[data-ui=view-pitch]'), 'tuxguitar')
            self.assertEqual(page.evaluate('tabRendered.tracks.map(t=>t.staves[0].displayTranspositionPitch)'), [-12, -12, -12, 0])
            self.assertFalse(page.evaluate('tabRenderApi.settings.notation.elements.get(alphaTab.NotationElement.EffectDynamics)'))
            pitches_js = 'tabRendered.tracks.flatMap(t=>t.staves.flatMap(s=>s.bars.flatMap(b=>b.voices.flatMap(v=>v.beats.flatMap(b=>b.notes.map(n=>n.realValue))))))'
            pitches = page.evaluate(pitches_js)
            before = page.evaluate('window.tabRenderCount')
            page.select_option('[data-ui=view-pitch]', 'concert')
            page.wait_for_function('n=>tabRenderCount>n && tabRenderApi.boundsLookup?.isFinished', arg=before)
            self.assertEqual(page.evaluate(pitches_js), pitches)
            self.assertEqual((folder/'song.yaml').read_bytes(), original)
            self.assertEqual(list(state.history), history)
            page.reload()
            page.wait_for_function('S&&!S.rendering')
            page.evaluate("tab('tab')")
            page.wait_for_selector('.vt-tab-score svg')
            self.assertEqual(page.get_attribute('.vt-tab-score', 'data-layout'), 'horizontal')
            self.assertFalse(page.is_checked('[data-ui=view-dynamics]'))

    def test_clean_score_default_and_explicit_saved_preferences(self):
        with self.muted_page(api.to_yaml(self.score_view_song()), compact=True, score_view=None,
                             width=1920, height=1040) as (page, state, folder):
            original = (folder/'song.yaml').read_bytes()
            page.evaluate("tab('tab')")
            page.wait_for_selector('.vt-tab-score svg')
            self.assertEqual(page.get_attribute('.vt-tab-score', 'data-layout'), 'horizontal')
            self.assertEqual(page.get_attribute('.vt-tab-score', 'data-scale'), '80')
            self.assertEqual(page.get_attribute('.vt-tab-score', 'data-tracks'), 'guitar,guitar2,bass,drums')
            self.assertFalse(page.is_checked('[data-ui=view-dynamics]'))
            self.assertEqual(page.input_value('[data-ui=view-pitch]'), 'tuxguitar')
            self.capture_engraving(page)
            page.locator('.vt-tab-view > summary').click()
            page.select_option('[data-ui=view-pitch]', 'concert')
            page.wait_for_function('window.tabRendered&&tabRenderApi.boundsLookup?.isFinished')
            pitches = page.evaluate('tabRendered.tracks.flatMap(t=>t.staves.flatMap(s=>s.bars.flatMap(b=>b.voices.flatMap(v=>v.beats.flatMap(b=>b.notes.map(n=>n.realValue))))))')
            page.click('[data-ui=view-tuxguitar]')
            page.wait_for_function('tabRendered.tracks[0].staves[0].displayTranspositionPitch===-12&&tabRenderApi.boundsLookup?.isFinished')
            self.assertEqual(page.evaluate('tabRendered.tracks.flatMap(t=>t.staves.flatMap(s=>s.bars.flatMap(b=>b.voices.flatMap(v=>v.beats.flatMap(b=>b.notes.map(n=>n.realValue))))))'), pitches)
            self.assertFalse(page.evaluate('tabRenderApi.settings.notation.elements.get(alphaTab.NotationElement.EffectDynamics)'))
            page.select_option('[data-ui=view-layout]', 'page')
            page.uncheck('[data-ui=view-multitrack]')
            page.check('[data-ui=view-dynamics]')
            page.select_option('[data-ui=view-pitch]', 'concert')
            page.reload(); page.wait_for_function('S&&!S.rendering')
            page.evaluate("tab('tab')"); page.wait_for_selector('.vt-tab-score svg')
            self.assertEqual(page.get_attribute('.vt-tab-score', 'data-layout'), 'page')
            self.assertEqual(page.get_attribute('.vt-tab-score', 'data-tracks'), 'guitar')
            self.assertTrue(page.is_checked('[data-ui=view-dynamics]'))
            self.assertEqual(page.input_value('[data-ui=view-pitch]'), 'concert')
            self.assertEqual((folder/'song.yaml').read_bytes(), original)
            self.assertEqual(list(state.history), [])

    def test_tuxguitar_written_staff_click_accounts_for_capo_and_undo(self):
        song=api.from_yaml(SONG)
        track=song['score']['tracks']['guitar'];track['capo']=2;track['tuning']=[n-2 for n in track['tuning']]
        with self.muted_page(api.to_yaml(song),compact=True) as (page,state,folder):
            before=(folder/'song.yaml').read_bytes()
            page.evaluate("tab('tab');setEdit(true)");page.wait_for_selector('.vt-tab-score svg')
            self.capture_engraving(page)
            page.click('[data-ui=view-tuxguitar]')
            page.wait_for_function('window.tabRendered&&tabRenderApi.boundsLookup?.isFinished')
            point=page.evaluate("""()=>{
              const beat=tabRendered.tracks[0].staves[0].bars[0].voices[0].beats.find(b=>b.notes.some(n=>n.fret===3));
              const bounds=tabRenderApi.boundsLookup.findBeats(beat)[0];
              const renderer=tabRenderApi.renderer.instance.layout.getRendererForBar('score',beat.voice.bar);
              const surface=document.querySelector('.vt-tab-score .at-surface');
              const marker=document.createElement('div');Object.assign(marker.style,{position:'absolute',left:bounds.onNotesX+'px',
                top:(bounds.barBounds.visualBounds.y+renderer.getLineY(1))+'px',width:'1px',height:'1px',pointerEvents:'none'});
              surface.append(marker);marker.scrollIntoView({block:'center'});const m=marker.getBoundingClientRect();marker.remove();return {x:m.x,y:m.y};
            }""")
            page.mouse.click(point['x'],point['y'])  # Written D5 -> sounding E4 with capo 2.
            self.settled(page,'SCORE.view.score.patterns.verse.beats.find(b=>b.id==="beat-b").notes.some(n=>n.pitch===64)')
            edited=(folder/'song.yaml').read_bytes();self.assertNotEqual(edited,before)
            page.click('[data-action=undo]')
            self.settled(page,'!SCORE.view.score.patterns.verse.beats.find(b=>b.id==="beat-b").notes.some(n=>n.pitch===64)')
            self.assertEqual((folder/'song.yaml').read_bytes(),before)
            page.click('[data-action=redo]')
            self.settled(page,'SCORE.view.score.patterns.verse.beats.find(b=>b.id==="beat-b").notes.some(n=>n.pitch===64)')
            self.assertEqual((folder/'song.yaml').read_bytes(),edited)

    def test_native_song_wav_stops_at_score_extent_without_silent_margin(self):
        source = api.from_yaml(NATIVE_SONG)
        source['module']['tempo'] = 120
        source['orders'] = ['verse']
        source['patterns']['verse']['rows'] = 24
        source['score']['order_ids'] = ['pass-1']
        source['score']['ties'] = []
        source['score']['patterns']['verse']['beats'] = [
            dict(id='short-tone', track='guitar', voice=0, at=[0,1],
                 written=dict(value=4), notes=[dict(id='tone',pitch=64,string=1,fret=0)])]
        # Two quarter notes at 120 BPM: 1 second. The fixture's unlooped,
        # 0.3-second decaying sample finishes before that boundary, so no tail is due.
        expected = 1.0
        with self.muted_page(api.to_yaml(source), compact=True) as (page, state, folder):
            self.assertFalse(state.error, state.error)
            self.assertIsNotNone(state.mod.native_score)
            page.wait_for_function("S.own && ['ready','failed'].includes(S.own.status)", timeout=15000)
            self.assertEqual(page.evaluate('S.own.status'), 'ready', page.evaluate('S.own.error'))
            page.wait_for_function("audio.readyState>=1 && audio.src.includes(S.own.key)", timeout=10000)
            # Inspect the normal SONG resource actually selected by the page,
            # not an explicitly length-limited export or the live engine.
            response = page.request.get(page.evaluate("new URL(tok(srcFor(null)),location.href).href"))
            self.assertEqual(response.status, 200)
            with wave.open(io.BytesIO(response.body()), 'rb') as rendered:
                rate, frames = rendered.getframerate(), rendered.getnframes()
                pcm = rendered.readframes(frames)
            self.assertTrue(any(pcm), 'the short native tone must be present')
            self.assertAlmostEqual(frames / rate, expected, delta=2 / rate)
            self.assertAlmostEqual(page.evaluate('audio.duration'), expected, delta=2 / rate)
            self.assertTrue(page.evaluate('audio.paused && !LV.playing'))

    @staticmethod
    def roll_gesture_song():
        source = api.from_yaml(SONG)
        source['patterns'] = {
            name: dict(rows=48, data='\n'.join(
                f'{row:02d}: ... .. ... ... | ' + {24:'C-5 01 ... ...',36:'=== .. ... ...',40:'... .. ... X80'}
                .get(row,'... .. ... ...') for row in range(48)))
            for name in ('a','b')}
        source['orders'] = ['a','b','a']
        source['score']['order_ids'] = ['a-first','b-first','a-repeat']
        source['score']['tracks']['guitar'].update(tuning=[64],channels=[0])
        source['score']['patterns'] = {
            name: dict(row_step=[1,12], beats=[
                dict(id=name+'-beat',track='guitar',voice=0,at=[1,13],
                     written=dict(value=4),notes=[
                         dict(id=name+'-note',pitch=64,string=1,fret=0,staccato=True)])])
            for name in ('a','b')}
        return api.to_yaml(source)

    @staticmethod
    def begin_roll_drag(page, *, resize=False, raw=False):
        channel = 1 if raw else 0
        page.evaluate(f"tab('pattern');setEdit(true);setCursor(0,0,{channel},0);showPattern(0)")
        page.wait_for_function("PAT.order===0 && PAT.occurrence==='a-first' && PAT.rows && PAT.revision && PAT.score_positions?.length")
        page.evaluate("if(!ROLL.on)rollToggle()")
        selector = '#roll .rnote[data-row="24"]' if raw else '#roll .rnote[data-score-id="a-first/a-note"]'
        box = roll_scroll(page, selector)
        scale = page.evaluate('zf()')
        x = box['x'] + box['width'] - 2*scale if resize else box['x'] + min(box['width']/2, 10*scale)
        y = box['y'] + box['height']/2
        page.mouse.move(x, y)
        page.mouse.down()
        page.mouse.move(x + (6 if raw else 12)*page.evaluate('ROLL.RW')*scale, y)

    def test_roll_drag_cancels_stale_pattern_occurrence_and_revision(self):
        for change in ('occurrence','pattern','revision'):
            for resize in (False,True):
                with self.subTest(change=change,resize=resize), self.muted_page(self.roll_gesture_song(),compact=True) as (page,state,folder):
                    self.assertFalse(state.error,state.error)
                    self.begin_roll_drag(page,resize=resize)
                    if change == 'revision':
                        page.evaluate("""async()=>{await scoreCommit({op:'note_set',pattern:0,beat:'a-beat',
                            note:{id:'a-note',velocity:94}},PAT.revision)}""")
                        page.wait_for_function("!EDQ.n && PAT.revision?.startsWith(S.version.hash) && PAT.score_positions?.some(p=>p.note==='a-note')")
                    else:
                        order = 2 if change == 'occurrence' else 1
                        page.evaluate(f"setCursor({order},0,0,0);showPattern({order})")
                        page.wait_for_function(f"PAT.order==={order} && PAT.rows && PAT.revision && PAT.score_positions?.length")
                    before = (folder/'song.yaml').read_bytes(),len(state.history),json.loads(json.dumps(state.mod.native_score['plan']))
                    posts = []
                    page.on('request',lambda r: posts.append(r.url) if r.method=='POST' and urlsplit(r.url).path in ('/api/score','/api/edit') else None)
                    page.mouse.up()
                    page.wait_for_function("!EDQ.n && !SCORE.fetching")
                    self.assertEqual(posts,[],'stale gesture must not submit even a backend-rejected request')
                    self.assertEqual(((folder/'song.yaml').read_bytes(),len(state.history),state.mod.native_score['plan']),before)
                    self.assertIn('cancel',page.inner_text('#rollhint').lower())

    def test_roll_drag_guard_preserves_exact_edits_and_raw_behavior(self):
        from vulturetracker.model import NOTE_OFF, NOTE_CUT
        with self.muted_page(self.roll_gesture_song(),compact=True) as (page,state,folder):
            before = (folder/'song.yaml').read_bytes()
            original_plan = json.loads(json.dumps(state.mod.native_score['plan']))
            for raw in (False,True):
                for resize in (False,True):
                    with self.subTest(raw=raw,resize=resize):
                        self.begin_roll_drag(page,resize=resize,raw=raw)
                        if not raw and not resize:
                            page.evaluate("async()=>{await refresh()}")  # Ordinary polling must not invalidate a valid gesture.
                        page.mouse.up()
                        page.wait_for_function("!EDQ.n && !SCORE.fetching && S.undo===1")
                        beat = state.song['score']['patterns']['a']['beats'][0]
                        self.assertEqual(beat['notes'][0]['id'],'a-note')
                        self.assertTrue(beat['notes'][0]['staccato'])
                        self.assertIn('X80',state.song['patterns']['a']['data'])
                        if not raw:
                            self.assertEqual(beat['at'],[1,13] if resize else [14,13])
                            self.assertEqual(beat['written']['value'],2 if resize else 4)
                        else:
                            self.assertEqual(beat['at'],[1,13])
                            self.assertEqual(state.mod.patterns[0].rows[24 if resize else 30][1].note,60)
                            # Existing sample-only resize uses CUT; a move retains the source OFF.
                            self.assertEqual(state.mod.patterns[0].rows[42][1].note,NOTE_CUT if resize else NOTE_OFF)
                        page.evaluate("patUndo(false)")
                        page.wait_for_function("!EDQ.n && !SCORE.fetching && S.undo===0")
                        self.assertEqual((folder/'song.yaml').read_bytes(),before)
                        self.assertEqual(state.mod.native_score['plan'],original_plan)
            for change in ('channel','edit','approved'):
                with self.subTest(change=change):
                    self.begin_roll_drag(page,raw=True)
                    if change == 'channel':
                        page.evaluate("setCursor(0,24,0,0)")
                    elif change == 'edit':
                        page.evaluate("setEdit(false)")
                    else:
                        page.evaluate("S.marks.patterns.a={approved:true}")
                    posts = []
                    page.on('request',lambda r: posts.append(r.url) if r.method=='POST' and urlsplit(r.url).path in ('/api/score','/api/edit') else None)
                    page.mouse.up()
                    page.wait_for_function("!EDQ.n")
                    self.assertEqual(posts,[])
                    self.assertEqual((folder/'song.yaml').read_bytes(),before)
                    self.assertEqual(len(state.history),0)
                    self.assertRegex(page.inner_text('#rollhint').lower(),'cancel|approved')
                    page.evaluate("S.marks.patterns.a={};setEdit(true)")

    @staticmethod
    def track_roll_song():
        # Guitar voices 1 and 2 sound the same pitch at once on different strings/channels.
        # A later bass note at that pitch and a raw note on a trackless channel stay ghosts.
        source = api.from_yaml(SONG)
        source['module']['channels'] = [dict(name=n) for n in ('High','Low','Bass','Raw')]
        source['patterns'] = {'a': dict(rows=48, data='\n'.join(
            f'{row:02d}: ' + ' | '.join(['... .. ... ...']*3 + [
                {36:'E-5 01 ... ...',44:'=== .. ... ...'}.get(row,'... .. ... ...')]) for row in range(48)))}
        source['orders'] = ['a','a']
        score = source['score']
        score['order_ids'] = ['a-1','a-2']
        score['tracks'] = {'guitar': dict(tuning=[64,59],channels=[0,1],capo=0,instrument=1),
                           'bass': dict(name='Bass',tuning=[52],channels=[2],capo=0,instrument=1)}
        beat = lambda bid, track, voice, at, nid, string, fret, volume: dict(
            id=bid, track=track, voice=voice, at=at, written=dict(value=4),
            notes=[dict(id=nid, pitch=64, string=string, fret=fret, volume=volume)])
        score['patterns'] = {'a': dict(row_step=[1,12], beats=[
            beat('g-v0','guitar',0,[0,1],'g0',1,0,40), beat('g-v1','guitar',1,[0,1],'g1',2,5,20),
            beat('b-v0','bass',0,[2,1],'b0',1,12,30)])}
        score['ties'] = []
        return api.to_yaml(source)

    @staticmethod
    def open_track_roll(page, notes=3):
        page.evaluate("tab('pattern');setEdit(true);setCursor(0,0,0,0);showPattern(0)")
        page.wait_for_function("PAT.order===0 && PAT.native && PAT.revision && PAT.score_positions?.filter(p=>p.kind==='note').length==="+str(notes))
        page.evaluate("if(!ROLL.on)rollToggle()")
        page.select_option('#roll-scope','track')
        page.wait_for_function("""rollTrack()==='guitar' && ['a-1/g0','a-1/g1'].every(id=>
            document.querySelector(`#roll [data-score-id="${id}"]`) && document.querySelector(`#rollvel [data-score-id="${id}"]`))""")

    @staticmethod
    def roll_hit(page, selector, *, resize=False):
        """Pointer coordinates on an element, and whether that element is what the point actually hits."""
        box, scale = roll_scroll(page, selector), page.evaluate('zf()')
        x = box['x'] + box['width'] - 2*scale if resize else box['x'] + min(box['width']/2, 10*scale)
        y = box['y'] + box['height']/2
        hit = page.evaluate("([x,y,s])=>document.elementFromPoint(x,y)===document.querySelector(s)", [x, y, selector])
        return x, y, hit

    def test_native_track_roll_overlapping_voices_target_their_own_source(self):
        with self.muted_page(self.track_roll_song(), compact=True) as (page, state, folder):
            self.assertFalse(state.error, state.error)
            errors = []
            page.on('pageerror', lambda e: errors.append(str(e)))
            before = (folder/'song.yaml').read_bytes()
            plan = json.loads(json.dumps(state.mod.native_score['plan']))
            self.open_track_roll(page)
            self.assertEqual(page.evaluate("[...$('roll-track').options].map(o=>o.value)"), ['guitar','bass'])
            geometry = {}
            for nid in ('g0','g1'):
                for host in ('roll','rollvel'):
                    x, y, hit = self.roll_hit(page, f'#{host} [data-score-id="a-1/{nid}"]')
                    self.assertTrue(hit, f'{host} {nid} must be hittable')
                    # Content coordinates distinguish lanes even when scrolling
                    # different notes to the edge gives them the same viewport y.
                    geometry[host, nid] = page.locator(f'#{host} [data-score-id="a-1/{nid}"]').evaluate(
                        'e=>[e.offsetLeft,e.offsetTop]')
            self.assertNotEqual(geometry['roll','g0'][1], geometry['roll','g1'][1], 'same-pitch voices need separate lanes')
            self.assertNotEqual(geometry['rollvel','g0'][0], geometry['rollvel','g1'][0])
            ghosts = page.evaluate("""[...document.querySelectorAll('#roll [data-roll-ghost]')].map(e=>
                [e.dataset.rollGhost,!!e.dataset.scoreId,getComputedStyle(e).pointerEvents])""")
            self.assertEqual(sorted(ghosts), [['raw',False,'none'],['track',False,'none']])
            for nid in ('g0','g1'):
                x, y, hit = self.roll_hit(page, f'#roll [data-score-id="a-1/{nid}"]')
                self.assertTrue(hit)
                page.mouse.click(x, y)
                self.assertEqual(page.evaluate('[CUR.score.id,CUR.score.voice,CUR.ch]'),
                                 [f'a-1/{nid}', int(nid[1]), int(nid[1])])
            self.assertEqual((folder/'song.yaml').read_bytes(), before, 'a plain click selects; it does not edit')

            def notes():
                return {n['id']: (b['id'], b['at'], b['written']['value'], n.get('volume'))
                        for b in state.song['score']['patterns']['a']['beats'] for n in b['notes']}
            original = notes()
            posts = []
            page.on('request', lambda r: posts.append(r.post_data_json)
                    if r.method=='POST' and urlsplit(r.url).path in ('/api/score','/api/edit') else None)
            for action, nid in (('volume','g1'),('move','g1'),('resize','g0')):
                with self.subTest(action=action, nid=nid):
                    posts.clear()
                    host = 'rollvel' if action == 'volume' else 'roll'
                    x, y, hit = self.roll_hit(page, f'#{host} [data-score-id="a-1/{nid}"]', resize=action=='resize')
                    self.assertTrue(hit)
                    if action == 'volume':
                        page.mouse.click(x, y)
                    else:
                        page.mouse.move(x, y)
                        page.mouse.down()
                        page.mouse.move(x + 12*page.evaluate('ROLL.RW*zf()'), y)
                        page.mouse.up()
                    self.settled(page, 'S.undo===1')
                    self.assertEqual([p['op'] for p in posts],
                                     [{'volume':'note_set','move':'note_move','resize':'beat_resize'}[action]])
                    # The edit's pattern reload must not drop the roll back to Channel scope.
                    self.assertEqual(page.evaluate("[$('roll-scope').value,rollTrack()]"), ['track','guitar'])
                    after, other = notes(), 'g0' if nid == 'g1' else 'g1'
                    self.assertEqual(after[other], original[other])
                    self.assertEqual(after['b0'], original['b0'])
                    expected = list(original[nid])
                    if action == 'volume':
                        self.assertNotEqual(after[nid][3], original[nid][3])
                        expected[3] = after[nid][3]
                    elif action == 'move':
                        expected[1] = [1,1]
                    else:
                        expected[2] = 2
                    self.assertEqual(list(after[nid]), expected)
                    page.evaluate("patUndo(false)")
                    self.settled(page, 'S.undo===0')
                    self.assertEqual((folder/'song.yaml').read_bytes(), before)
                    self.assertEqual(state.mod.native_score['plan'], plan)
                    page.wait_for_function("""['a-1/g0','a-1/g1'].every(id=>document.querySelector(`#roll [data-score-id="${id}"]`))""")
            page.select_option('#roll-track', 'bass')
            page.wait_for_function("""document.querySelector('#roll [data-score-id="a-1/b0"]') &&
                !document.querySelector('#roll [data-score-id="a-1/g0"]')""")
            self.assertEqual(page.locator('#roll [data-roll-ghost=track]').count(), 2)
            self.assertEqual(errors, [])

    def test_native_track_roll_ghosts_and_blank_clicks_do_not_edit(self):
        with self.muted_page(self.track_roll_song(), compact=True) as (page, state, folder):
            self.assertFalse(state.error, state.error)
            before = (folder/'song.yaml').read_bytes()
            self.open_track_roll(page)
            page.select_option('#roll-from', 'next')
            page.wait_for_function("ROLL.from?.positions?.some(p=>p.occurrence==='a-2') && document.querySelectorAll('#roll .rnote.from').length")
            self.assertEqual(page.evaluate("[...document.querySelectorAll('#roll .rnote.from')].filter(e=>e.dataset.scoreId).length"), 0)
            posts = []
            page.on('request', lambda r: posts.append(r.url)
                    if r.method=='POST' and urlsplit(r.url).path in ('/api/score','/api/edit','/api/score_command') else None)
            # Ghosts sit after the guitar notes (bass at row 24, raw and its foreign copy at row 36).
            foreign_index = page.evaluate("""()=>{const e=[...document.querySelectorAll('#roll .rnote.from')]
                .sort((a,b)=>parseFloat(b.style.left)-parseFloat(a.style.left))[0];
                return [...e.parentElement.children].indexOf(e)+1}""")
            for name, selector in [('foreign', f'#roll > :nth-child({foreign_index})'),
                                   ('track', '#roll [data-roll-ghost=track]'),
                                   ('raw', '#roll [data-roll-ghost=raw]'),
                                   ('blank', '#roll [data-score-id="a-1/g0"]')]:
                for button in ('left','right'):
                    with self.subTest(target=name, button=button):
                        box = roll_scroll(page, selector)
                        x = box['x'] + (box['width'] + 30*page.evaluate('zf()') if name == 'blank' else box['width']/2)
                        y = box['y'] + box['height']/2
                        # Ghosts let the pointer through to the roll's background, never to a note.
                        self.assertTrue(page.evaluate("""([x,y])=>{const e=document.elementFromPoint(x,y);
                            return $('roll').contains(e)&&!e.closest('.rnote')}""", [x, y]))
                        # A left click on blank space enters a note (its own test); here EDIT is off for it.
                        page.evaluate(f"setEdit({'false' if button == 'left' else 'true'});$('rollhint').textContent=''")
                        page.mouse.click(x, y, button=button)
                        page.wait_for_function('!EDQ.n')
                        self.assertEqual(posts, [])
                        self.assertIn('turn EDIT on' if button == 'left' else 'Native track scope', page.inner_text('#rollhint'))
            self.assertEqual(page.evaluate('S.undo'), 0)
            self.assertEqual(len(state.history), 0)
            self.assertEqual((folder/'song.yaml').read_bytes(), before)

    def test_native_track_roll_grid_follows_meter_and_persists_outside_the_song(self):
        source = api.from_yaml(self.track_roll_song())
        source['score']['measures'] = [dict(id='m68', meter=[6,8],
            **{'from': dict(occurrence='a-1', at=[0,1])}, to=dict(occurrence='a-1', at=[3,1]))]
        with self.muted_page(api.to_yaml(source), compact=True) as (page, state, folder):
            self.assertFalse(state.error, state.error)
            before = (folder/'song.yaml').read_bytes()
            self.open_track_roll(page)
            guides = lambda: page.evaluate("""[...document.querySelectorAll('#roll [data-grid-row]')]
                .map(e=>[+e.dataset.gridRow,+e.dataset.gridKind])""")
            # 6/8 beats are eighths: division 2 is 1/4 quarter (3 rows); the 4/4 display group after it is 1/2 quarter.
            self.assertEqual(page.input_value('#roll-grid'), '2')
            self.assertEqual(guides(), [[r, 2 if r == 0 else 1 if r % 6 == 0 else 0] for r in range(0, 36, 3)] + [[36,2],[42,0]])
            page.select_option('#roll-grid', '3')
            self.assertEqual([r for r,_ in guides()], list(range(0, 36, 2)) + [36,40,44])
            self.assertEqual(page.locator('#roll [data-score-id]').count(), 2)
            self.assertEqual((folder/'song.yaml').read_bytes(), before, 'the grid is display only')
            self.assertEqual(len(state.history), 0)
            for saved, shown in (('3','3'), ('5','2')):  # An invalid saved division falls back to 2, as TuxGuitar.
                page.evaluate(f"localStorage.rollgrid='{saved}'")
                page.reload()
                page.wait_for_function("typeof S!=='undefined'&&S?.song?.facts")
                self.open_track_roll(page)
                self.assertEqual(page.input_value('#roll-grid'), shown)
            page.select_option('#roll-scope', 'channel')
            self.assertTrue(page.is_hidden('#roll-grid-label'))
            self.assertEqual(page.locator('#roll [data-grid-row]').count(), 0)

    def test_native_track_roll_percussion_rows_are_named(self):
        source = api.from_yaml(self.track_roll_song())
        score = source['score']
        score['tracks']['bass'].update(name='Kit', tuning=[0], midi=dict(bank=128, program=0))
        score['patterns']['a']['beats'][2:] = [
            dict(id=f'k{key}', track='bass', voice=0, at=[i,1], written=dict(value=4),
                 notes=[dict(id=f'key{key}', pitch=key, string=1, fret=key)])
            for i, key in enumerate((27, 42, 87, 100))]
        with self.muted_page(api.to_yaml(source), compact=True) as (page, state, folder):
            self.assertFalse(state.error, state.error)
            self.open_track_roll(page, notes=6)
            self.assertEqual(page.locator('#roll .rdrum').count(), 0, 'a pitched track keeps note names')
            page.select_option('#roll-track', 'bass')
            page.wait_for_function("""document.querySelector('#roll [data-score-id="a-1/key42"]')""")
            names = page.evaluate("""Object.fromEntries([...document.querySelectorAll('#roll [data-roll-pitch]')]
                .map(e=>[e.dataset.rollPitch,e.querySelector('.rdrum')?.textContent]))""")
            self.assertEqual({k: names[k] for k in ('26','27','42','87','88','100')},
                             {'26':'Drum key 26','27':'High Q','42':'Closed Hi-Hat','87':'Open Surdo','88':'Drum key 88','100':'Drum key 100'})
            note = page.locator('#roll [data-score-id="a-1/key42"]')
            self.assertEqual(note.inner_text(), '42')
            self.assertIn('Closed Hi-Hat', note.get_attribute('title'))
            self.assertIn('42', page.evaluate("[...document.querySelectorAll('#roll .rlab')].map(e=>e.textContent)"))

    @staticmethod
    def roll_point(page, pitch, row, lane=0):
        """Viewport point of a ROLL pitch row (and lane) at a fractional pattern row."""
        roll_scroll(page, f'#roll [data-roll-pitch="{pitch}"]')
        return page.evaluate("""([pitch,row,lane])=>{const r=$('roll').getBoundingClientRect(),z=zf();
            return [r.left+(40+row*ROLL.RW)*z,r.top+((ROLL.hi-pitch)*ROLL.pitchHeight+lane*ROLL.PH+ROLL.PH/2)*z]}""", [pitch, row, lane])

    def test_native_track_roll_blank_click_enters_a_note_on_the_grid(self):
        source = api.from_yaml(self.track_roll_song())
        source['score']['patterns']['a']['beats'][1]['written']['value'] = 8  # g1 shorter: lane 2 is blank after it
        with self.muted_page(api.to_yaml(source), compact=True) as (page, state, folder):
            self.assertFalse(state.error, state.error)
            errors = []
            page.on('pageerror', lambda e: errors.append(str(e)))
            before = (folder/'song.yaml').read_bytes()
            original = json.loads(json.dumps(state.song['score']['patterns']['a']['beats']))
            self.open_track_roll(page)
            posts = []
            page.on('request', lambda r: posts.append(r.post_data_json)
                    if r.method=='POST' and urlsplit(r.url).path in ('/api/score','/api/edit','/api/score_command') else None)
            for grid, row, at in (('2', 14.5, [1,1]), ('4', 16.2, [5,4])):
                with self.subTest(grid=grid):
                    posts.clear()
                    page.select_option('#roll-grid', grid)
                    x, y = self.roll_point(page, 67, row)
                    self.assertTrue(page.evaluate("([x,y])=>!document.elementFromPoint(x,y).closest('.rnote')", [x, y]))
                    page.mouse.click(x, y)
                    self.settled(page, 'S.undo===1')
                    self.assertEqual([p.get('action') for p in posts], ['place'])
                    beats = state.song['score']['patterns']['a']['beats']
                    added = [b for b in beats if b['id'] not in {o['id'] for o in original}]
                    self.assertEqual(len(added), 1)
                    self.assertEqual((added[0]['track'], added[0]['voice'], added[0]['at'], added[0]['written']['value']),
                                     ('guitar', 0, at, 4))
                    self.assertEqual([(n['pitch'], n['string'], n['fret']) for n in added[0]['notes']], [(67, 1, 3)])
                    self.assertEqual([b for b in beats if b['id'] in {o['id'] for o in original}], original)
                    self.assertEqual([page.evaluate("$('roll-scope').value"), len(state.history)], ['track', 1])
                    page.evaluate("patUndo(false)")
                    self.settled(page, 'S.undo===0')
                    self.assertEqual((folder/'song.yaml').read_bytes(), before)
                    page.wait_for_function("""document.querySelector('#roll [data-score-id="a-1/g0"]')""")
            # Grid 1 floors a click in g1's empty second lane back to onset 0, where pitch 64 already sounds:
            # piano entry would toggle (delete) it, so the roll refuses instead.
            posts.clear()
            page.select_option('#roll-grid', '1')
            x, y = self.roll_point(page, 64, 8, lane=1)
            self.assertTrue(page.evaluate("([x,y])=>!document.elementFromPoint(x,y).closest('.rnote')", [x, y]))
            page.mouse.click(x, y)
            page.wait_for_function('!EDQ.n')
            self.assertEqual(posts, [])
            page.wait_for_function("$('rollhint').textContent.includes('already has that pitch')")
            self.assertEqual((folder/'song.yaml').read_bytes(), before)
            self.assertEqual(errors, [])

    def test_native_track_roll_blank_click_voice_2_and_percussion_key(self):
        for case in ('voice2', 'drums'):
            source = api.from_yaml(self.track_roll_song())
            if case == 'drums':
                score = source['score']
                score['tracks']['bass'].update(name='Kit', tuning=[0], midi=dict(bank=128, program=0))
                score['patterns']['a']['beats'][2] = dict(id='k42', track='bass', voice=0, at=[0,1], written=dict(value=4),
                                                          notes=[dict(id='key42', pitch=42, string=1, fret=42)])
            with self.subTest(case=case), self.muted_page(api.to_yaml(source), compact=True) as (page, state, folder):
                self.assertFalse(state.error, state.error)
                before = (folder/'song.yaml').read_bytes()
                original = {b['id'] for b in state.song['score']['patterns']['a']['beats']}
                self.open_track_roll(page)
                if case == 'voice2':
                    page.mouse.click(*self.roll_hit(page, '#roll [data-score-id="a-1/g1"]')[:2])  # select a voice-2 note
                    self.assertEqual(page.evaluate('CUR.score.voice'), 1)
                    pitch, expected = 67, ('guitar', 1, 67, 1, 3)
                else:
                    page.select_option('#roll-track', 'bass')
                    page.wait_for_function("""document.querySelector('#roll [data-score-id="a-1/key42"]')""")
                    pitch, expected = 38, ('bass', 0, 38, 1, 38)
                x, y = self.roll_point(page, pitch, 14.5)
                self.assertTrue(page.evaluate("([x,y])=>!document.elementFromPoint(x,y).closest('.rnote')", [x, y]))
                page.mouse.click(x, y)
                self.settled(page, 'S.undo===1')
                added = [b for b in state.song['score']['patterns']['a']['beats'] if b['id'] not in original]
                self.assertEqual(len(added), 1)
                n = added[0]['notes'][0]
                self.assertEqual((added[0]['track'], added[0]['voice'], n['pitch'], n['string'], n['fret']), expected)
                self.assertEqual(added[0]['at'], [1,1])
                page.evaluate("patUndo(false)")
                self.settled(page, 'S.undo===0')
                self.assertEqual((folder/'song.yaml').read_bytes(), before)

    def test_native_track_roll_non_native_reload_resets_scope_and_hint(self):
        with self.muted_page(self.track_roll_song(), compact=True) as (page, state, folder):
            self.assertFalse(state.error, state.error)
            self.open_track_roll(page)
            self.assertTrue(page.inner_text('#rollhint').startswith('Native track'))
            # The state a reload leaves when the song no longer has a score.
            version = page.evaluate("PAT.native=false;const v=ROLL.scopeVersion;renderRoll();ROLL.scopeVersion-v")
            self.assertEqual(version, 1, 'a forced scope change cancels any held drag')
            self.assertEqual(page.evaluate("[$('roll-scope').value,$('roll-scope').querySelector('[value=track]').disabled]"),
                             ['channel', True])
            self.assertTrue(page.inner_text('#rollhint').startswith('Channel / raw'))

    def test_native_track_roll_drag_cancels_on_scope_track_and_revision_change(self):
        for change in ('scope','track','revision'):
            with self.subTest(change=change), self.muted_page(self.track_roll_song(), compact=True) as (page, state, folder):
                self.assertFalse(state.error, state.error)
                self.open_track_roll(page)
                x, y, hit = self.roll_hit(page, '#roll [data-score-id="a-1/g0"]')
                self.assertTrue(hit)
                page.mouse.move(x, y)
                page.mouse.down()
                page.mouse.move(x + 12*page.evaluate('ROLL.RW*zf()'), y)
                if change == 'scope':
                    page.select_option('#roll-scope', 'channel')
                elif change == 'track':
                    page.select_option('#roll-track', 'bass')
                else:
                    revision = page.evaluate('PAT.revision')
                    page.evaluate("""async()=>{await scoreCommit({op:'note_set',pattern:0,beat:'g-v1',
                        note:{id:'g1',velocity:94}},PAT.revision)}""")
                    page.wait_for_function(f"!EDQ.n && PAT.revision && PAT.revision!=={json.dumps(revision)}")
                before = (folder/'song.yaml').read_bytes(), len(state.history), json.loads(json.dumps(state.mod.native_score['plan']))
                posts = []
                page.on('request', lambda r: posts.append(r.url)
                        if r.method=='POST' and urlsplit(r.url).path in ('/api/score','/api/edit') else None)
                page.mouse.up()
                page.wait_for_function("!EDQ.n && !SCORE.fetching")
                self.assertEqual(posts, [])
                self.assertEqual(((folder/'song.yaml').read_bytes(), len(state.history), state.mod.native_score['plan']), before)
                self.assertIn('cancel', page.inner_text('#rollhint').lower())

    @staticmethod
    def piano_song():
        source = api.from_yaml(NATIVE_SONG)
        source['module']['channels'] = [dict(name=f'String {i}') for i in range(3)]
        score = source['score']
        score['tracks']['guitar'].update(tuning=[60,64,55], channels=[0,1,2], capo=2, max_fret=10)
        score['ties'] = []
        score['patterns']['verse']['beats'] = [
            dict(id=f'voice-{v}', track='guitar', voice=v, at=[1,1], written=dict(value=8),
                 notes=[dict(id=f'n{v}', pitch=66, string=v+1, fret=4 if v == 0 else 0,
                             velocity=0, staccato=True)])
            for v in range(2)] + [
                dict(id='rest', track='guitar', voice=0, at=[2,1], written=dict(value=4), notes=[], text='Keep me')]
        source['patterns']['bridge'] = dict(rows=48, data='')
        source['orders'][1] = 'bridge'
        return source

    def test_native_fret_place_serial_digits_and_drum_100(self):
        for drums, digits, expected in [(False,'12',[1,12]),(True,'100',[1,10,100])]:
            source = self.piano_song()
            source['score']['tracks']['guitar']['max_fret'] = 29
            rest = source['score']['patterns']['verse']['beats'][-1]
            rest.pop('text')
            if drums:
                source['score']['tracks']['guitar'].update(tuning=[0,0,0],capo=0,midi=dict(bank=128,program=0))
                source['score']['patterns']['verse']['beats'] = [rest]
            with self.subTest(drums=drums), self.muted_page(api.to_yaml(source),compact=True) as (page,state,folder):
                self.assertFalse(state.error,state.error)
                before = (folder/'song.yaml').read_bytes()
                page.evaluate("tab('tab')")
                page.wait_for_selector('.vt-tab-inspector')
                page.locator('.vt-tab-inspector > summary').click()
                page.fill('[data-ui=at]','9/4')
                page.click('[data-action=go]')
                page.select_option('[data-ui=duration]','8')
                held, requests, responses = [], [], []
                page.route('**/api/score_command',lambda route: held.append(route))
                page.on('request',lambda r: requests.append(r.post_data_json)
                        if r.method=='POST' and urlsplit(r.url).path in ('/api/score','/api/score_command') else None)
                page.on('response',lambda r: responses.append(r.json())
                        if r.request.method=='POST' and urlsplit(r.url).path in ('/api/score','/api/score_command') else None)
                revision = page.evaluate('SCORE.view.revision')
                page.locator('#tab-editor').focus()
                page.keyboard.type(digits)
                page.wait_for_function('EDQ.n===1')
                self.assertEqual(len(held),1)
                held[0].continue_()
                self.settled(page,f"SCORE.view.score.patterns.verse.beats.some(b=>b.at[0]===9&&b.at[1]===4&&b.notes[0]?.fret==={expected[-1]})")
                self.assertEqual(len(requests),len(digits))
                self.assertEqual(requests[0]['action'],'place')
                self.assertNotIn('fit',requests[0])
                self.assertEqual(requests[0]['revision'],revision)
                self.assertEqual([r['revision'] for r in requests[1:]],[r['revision'] for r in responses[:-1]])
                inserted = next(b for b in state.song['score']['patterns']['verse']['beats'] if b['at']==[9,4])
                nid,bid = inserted['notes'][0]['id'],inserted['id']
                self.assertTrue(all(r['note']['id']==nid and r['beat']==bid for r in requests[1:]))
                self.assertEqual(inserted['notes'][0]['pitch'],100 if drums else 74)
                self.assertEqual(page.evaluate('[CUR.score.at,CUR.score.beat,CUR.score.note]'),[[9,4],bid,nid])
                self.assertEqual(len(state.history),len(digits))
                if not drums:
                    for digit,value in [('3',3),('0',0),('1',1)]:
                        page.keyboard.type(digit)
                        self.settled(page,f"SCORE.view.score.patterns.verse.beats.find(b=>b.id==='{bid}').notes[0].fret==={value}")
                        expected.append(value)
                    page.wait_for_timeout(1100)
                    page.keyboard.type('2')  # Past the source timeout: replace with 2, not 12.
                    self.settled(page,f"SCORE.view.score.patterns.verse.beats.find(b=>b.id==='{bid}').notes[0].fret===2")
                    expected.append(2)
                else:
                    count = len(requests)
                    page.keyboard.type('0')  # 1000 is out of the bounded drum range.
                    self.assertIn('1 to 100',page.locator('.vt-tab-status').inner_text())
                    self.assertEqual(len(requests),count)
                for value in reversed(expected[:-1]):
                    page.click('[data-action=undo]')
                    self.settled(page,f"SCORE.view.score.patterns.verse.beats.find(b=>b.id==='{bid}').notes[0].fret==={value}")
                page.click('[data-action=undo]')
                self.settled(page,f"!SCORE.view.score.patterns.verse.beats.some(b=>b.id==='{bid}')")
                self.assertEqual((folder/'song.yaml').read_bytes(),before)

    def test_edit_completion_preserves_new_voice_selection(self):
        for action in ('velocity', 'duration', 'string-down', 'paste-safe'):
            source = self.piano_song()
            source['score']['patterns']['verse']['beats'] = [
                b for b in source['score']['patterns']['verse']['beats'] if b['voice'] == 0]
            source['score']['patterns']['verse']['beats'][-1].pop('text')
            with self.subTest(action=action), self.muted_page(api.to_yaml(source)) as (page, state, folder):
                original = state.song_path.read_bytes()
                page.click('[data-t=tab]')
                page.wait_for_selector('.vt-tab-grid [data-note=n0]')
                self.settled(page, '!SCORE.pending')
                page.click('.vt-tab-grid [data-note=n0]')
                if action in ('velocity', 'duration'):
                    page.click('[data-action=select-all]')
                if action == 'velocity':
                    page.fill('[data-ui=velocity]', '63')
                elif action == 'duration':
                    page.select_option('[data-ui=duration]', '16')
                elif action == 'paste-safe':
                    page.click('[data-action=copy]')
                    page.wait_for_function("document.querySelector('.vt-tab-status').textContent.startsWith('Copied')")
                    page.fill('[data-ui=at]', '3/2')
                    page.click('[data-action=go]')
                held = []
                endpoint = '**/api/score*'
                page.route(endpoint, lambda route: held.append(route) if route.request.method == 'POST' else route.continue_())
                with page.expect_request(lambda r: r.method == 'POST' and urlsplit(r.url).path in ('/api/score', '/api/score_command')):
                    page.click(f'[data-action={action}]')
                page.wait_for_function('EDQ.n===1')
                self.assertEqual(len(held), 1)
                page.select_option('[data-ui=voice]', label='2')
                self.assertEqual(page.input_value('[data-ui=voice]'), '1')
                selected = page.evaluate('JSON.stringify(CUR.score)')
                held[0].continue_()
                self.settled(page, "!document.querySelector('[data-ui=track]').disabled")
                page.unroute(endpoint)
                self.assertEqual(len(state.history), 1, page.inner_text('.vt-tab-status'))
                self.assertEqual(page.evaluate('JSON.stringify(CUR.score)'), selected,
                                 'Finishing an edit must not undo later navigation')
                self.assertEqual(page.input_value('[data-ui=voice]'), '1')
                edited = next(b for b in state.song['score']['patterns']['verse']['beats'] if b['id'] == 'voice-0')
                note = next(n for n in edited['notes'] if n['id'] == 'n0')
                if action == 'velocity':
                    self.assertEqual(note['velocity'], 63)
                elif action == 'duration':
                    self.assertEqual(edited['written']['value'], 16)
                elif action == 'string-down':
                    self.assertEqual((note['pitch'], note['string'], note['fret']), (66, 2, 0))
                else:
                    pasted = next(b for b in state.song['score']['patterns']['verse']['beats'] if b['at'] == [3, 2])
                    self.assertEqual(pasted['notes'][0]['pitch'], 66)
                    self.assertNotEqual(pasted['notes'][0]['id'], 'n0')
                saved = state.song_path.read_bytes()
                self.assertNotEqual(saved, original)
                page.click('[data-action=undo]')
                self.settled(page, 'S.undo===0')
                self.assertEqual(state.song_path.read_bytes(), original)
                page.click('[data-action=redo]')
                self.settled(page, 'S.redo===0')
                self.assertEqual(state.song_path.read_bytes(), saved)

    def test_native_fret_queued_cancellation_preserves_completed_first_edit(self):
        for change in ('voice','string','away-back','external','failed'):
            source = self.piano_song()
            source['score']['tracks']['guitar']['max_fret'] = 29
            if change != 'failed':
                source['score']['patterns']['verse']['beats'][-1].pop('text')
            with self.subTest(change=change), self.muted_page(api.to_yaml(source),compact=True) as (page,state,folder):
                before = (folder/'song.yaml').read_bytes()
                page.evaluate("tab('tab')")
                page.wait_for_selector('.vt-tab-inspector')
                page.locator('.vt-tab-inspector > summary').click()
                page.fill('[data-ui=at]','9/4')
                page.click('[data-action=go]')
                page.select_option('[data-ui=duration]','8')
                held, requests = [], []
                page.route('**/api/score_command',lambda route: held.append(route))
                page.on('request',lambda r: requests.append(r.post_data_json)
                        if r.method=='POST' and urlsplit(r.url).path in ('/api/score','/api/score_command') else None)
                page.locator('#tab-editor').focus()
                page.keyboard.type('12')
                page.wait_for_function('EDQ.n===1')
                self.assertEqual(len(held),1)
                if change in ('voice','string','away-back'):
                    page.evaluate("""kind=>{
                        const p={order:0,pattern:'verse',track:'guitar',voice:0,at:[9,4],string:1};
                        SCORE.editor.setSelection({...p,...(kind==='voice'?{voice:1}:kind==='string'?{string:2}:{at:[7,2]})});
                        if(kind==='away-back') SCORE.editor.setSelection(p);
                    }""",change)
                if change == 'external':
                    # Commit digit1 but withhold its response; a separate authoritative edit follows.
                    response = held[0].fetch()
                    first = response.json()
                    result = page.evaluate("""async revision=>{
                        const r=await fetch('/api/score',{method:'POST',headers:{'content-type':'application/json'},
                            body:JSON.stringify({op:'note_set',pattern:'verse',beat:'voice-0',note:{id:'n0',velocity:95},revision})});
                        return r.json();
                    }""",first['revision'])
                    self.assertNotIn('error',result)
                    page.evaluate("revision=>SCORE.editor.update({...SCORE.view,revision})",result['revision'])
                    held[0].fulfill(response=response)
                else:
                    held[0].continue_()
                page.wait_for_function("!EDQ.n && document.querySelector('.vt-tab-status').textContent.includes('queued digits were cancelled')")
                self.assertEqual(len(requests),2 if change=='external' else 1)
                if change == 'failed':
                    self.assertEqual((folder/'song.yaml').read_bytes(),before)
                    self.assertEqual(len(state.history),0)
                else:
                    inserted = next(b for b in state.song['score']['patterns']['verse']['beats'] if b['at']==[9,4])
                    self.assertEqual(inserted['notes'][0]['fret'],1)
                    self.assertEqual(len(state.history),2 if change=='external' else 1)
                    if change == 'external':
                        self.assertEqual(next(b for b in state.song['score']['patterns']['verse']['beats'] if b['id']=='voice-0')['notes'][0]['velocity'],95)
                        page.click('[data-action=undo]')
                        self.settled(page,"SCORE.view.score.patterns.verse.beats.find(b=>b.id==='voice-0').notes[0].velocity===0")
                    page.click('[data-action=undo]')
                    self.settled(page,"SCORE.view.score.patterns.verse.beats.length===3")
                    self.assertEqual((folder/'song.yaml').read_bytes(),before)

    def test_native_fret_cancel_before_dispatch_and_unchanged_refresh(self):
        source = self.piano_song()
        source['score']['tracks']['guitar']['max_fret']=29
        source['score']['patterns']['verse']['beats'][-1].pop('text')
        with self.muted_page(api.to_yaml(source),compact=True) as (page,state,folder):
            before=(folder/'song.yaml').read_bytes()
            page.evaluate("tab('tab')")
            page.wait_for_selector('.vt-tab-inspector')
            page.locator('.vt-tab-inspector > summary').click()
            page.fill('[data-ui=at]','9/4')
            page.click('[data-action=go]')
            page.select_option('[data-ui=duration]','8')
            requests=[]
            page.on('request',lambda r: requests.append(r.post_data_json)
                    if r.method=='POST' and urlsplit(r.url).path in ('/api/score','/api/score_command') else None)
            for mutation in [
                "SCORE.editor.update({...SCORE.view,revision:'external'})",
                "SCORE.editor.update({...SCORE.view,order:2})",
                "SCORE.editor.setSelection({...p,string:2}); SCORE.editor.setSelection(p)",
            ]:
                page.evaluate("""() => {SCORE.editor.update(SCORE.view);
                    SCORE.editor.setSelection({order:0,pattern:'verse',track:'guitar',voice:0,at:[9,4],string:1})}""")
                page.evaluate("""() => {
                    const p={order:0,pattern:'verse',track:'guitar',voice:0,at:[9,4],string:1};
                    document.querySelector('#tab-editor').dispatchEvent(new KeyboardEvent('keydown',{key:'1',bubbles:true}));
                    """+mutation+"}")
                page.wait_for_function("document.querySelector('.vt-tab-status').textContent.includes('queued digits were cancelled')")
            self.assertEqual(requests,[])
            self.assertEqual((folder/'song.yaml').read_bytes(),before)
            self.assertEqual(len(state.history),0)
            page.evaluate("""() => {
                SCORE.editor.update(SCORE.view);
                SCORE.editor.setSelection({order:0,pattern:'verse',track:'guitar',voice:0,at:[9,4],string:1});
                document.querySelector('#tab-editor').dispatchEvent(new KeyboardEvent('keydown',{key:'1',bubbles:true}));
                SCORE.editor.update({...SCORE.view});
            }""")
            self.settled(page,"SCORE.view.score.patterns.verse.beats.some(b=>b.at[0]===9&&b.at[1]===4&&b.notes[0]?.fret===1)")
            self.assertEqual(len(requests),1)
            page.click('[data-action=undo]')
            self.settled(page,"SCORE.view.score.patterns.verse.beats.length===3")
            self.assertEqual((folder/'song.yaml').read_bytes(),before)

    def test_piano_exact_entry_toggle_duration_allocation_and_preview(self):
        with self.muted_page(api.to_yaml(self.piano_song()), compact=True) as (page, state, folder):
            self.assertFalse(state.error, state.error)
            before = (folder / 'song.yaml').read_bytes()
            errors = []
            page.on('pageerror', lambda e: errors.append(str(e)))
            page.evaluate("tab('tab')")
            page.wait_for_selector('.vt-piano')
            self.assertFalse(page.locator('.vt-piano').evaluate('e=>e.open'))
            page.locator('.vt-piano > summary').click()
            # The details toggle event fills the keyboard after the click returns.
            page.wait_for_function("document.querySelectorAll('[data-piano-pitch]').length === 120")
            self.assertEqual(page.locator('[data-piano-pitch]').count(), 120)
            self.assertNotIn('[object Object]', page.locator('.vt-piano').inner_text())
            page.locator('.vt-fretboard > summary').click()
            page.select_option('[data-fb=scale]', '0')
            page.select_option('[data-fb=root]', 'D')
            self.assertEqual(page.locator('[data-piano-pitch="66"]').get_attribute('data-scale'), 'true')
            self.assertEqual(page.locator('[data-piano-pitch="68"]').get_attribute('data-scale'), 'false')
            select = """SCORE.editor.setSelection({order:0,pattern:'verse',occurrence:'pass-1',
                track:'guitar',voice:1,at:[1,1],string:2})"""
            page.evaluate(select)
            key = lambda n: page.locator(f'[data-piano-pitch="{n}"]')
            self.assertEqual(key(66).get_attribute('data-voices'), '0,1')
            key(66).click()
            self.settled(page, "SCORE.view.score.patterns.verse.beats[0].notes.length===0")
            self.assertEqual(state.song['score']['patterns']['verse']['beats'][1]['notes'][0]['id'], 'n1')
            self.assertEqual(len(state.history), 1)
            page.click('[data-action=undo]')
            self.settled(page, "SCORE.view.score.patterns.verse.beats[0].notes.length===1")
            self.assertEqual((folder / 'song.yaml').read_bytes(), before)
            # Both voices occupy strings 1/2; a new pitch uses string 3 without replacing either.
            page.evaluate(select)
            key(67).focus()
            page.keyboard.press('Enter')
            self.settled(page, "SCORE.view.score.patterns.verse.beats[1].notes.length===2")
            n = state.song['score']['patterns']['verse']['beats'][1]['notes'][1]
            self.assertEqual((n['pitch'], n['string'], n['fret']), (67,3,10))
            self.assertEqual(state.song['score']['patterns']['verse']['beats'][1]['notes'][0]['velocity'], 0)
            page.click('[data-action=undo]')
            self.settled(page, "SCORE.view.score.patterns.verse.beats[1].notes.length===1")
            # Shared preview preserves zero velocity and makes no edits; keyboard stays inside piano.
            page.evaluate("window.pianoPreview=[];lvNoteOn=(...args)=>pianoPreview.push(args);lvNoteOff=()=>{}")
            page.select_option('[data-piano=mode]', 'audition')
            key(66).click()
            self.assertEqual(page.evaluate('pianoPreview.at(-1).slice(2)'), [66,0])
            key(66).focus()
            page.keyboard.press('ArrowRight')
            self.assertEqual(page.evaluate('document.activeElement.dataset.pianoPitch'), '67')
            page.keyboard.press('Space')
            self.assertEqual(page.evaluate('pianoPreview.at(-1)[2]'), 67)
            self.assertEqual((folder / 'song.yaml').read_bytes(), before)
            page.select_option('[data-piano=mode]', 'edit')
            # Gap insertion is exact and uses source string order, not backend minimum-fret allocation.
            page.evaluate("""SCORE.editor.setSelection({order:0,pattern:'verse',track:'guitar',voice:1,at:[1,13],string:1});
                document.querySelector('[data-ui=duration]').value='16';
                document.querySelector('[data-ui=dots]').value='1';
                document.querySelector('[data-ui=tuple-n]').value='3';
                document.querySelector('[data-ui=tuple-d]').value='2';""")
            page.evaluate("SCORE.editor.enterPitch(67,{velocity:0})")
            self.settled(page, "SCORE.view.score.patterns.verse.beats.length===4")
            b = next(b for b in state.song['score']['patterns']['verse']['beats'] if b['at'] == [1,13])
            self.assertEqual((b['voice'], b['notes'][0]['string'], b['notes'][0]['fret'], b['notes'][0]['velocity']), (1,1,5,0))
            self.assertEqual(b['written'], dict(value=16,dots=1,tuplet=[3,2]))
            self.assertEqual(page.evaluate('[CUR.score.at,CUR.score.beat,CUR.score.note]'),
                             [[1,13],b['id'],b['notes'][0]['id']])
            page.click('[data-action=undo]')
            self.settled(page, "SCORE.view.score.patterns.verse.beats.length===3")
            self.assertEqual((folder / 'song.yaml').read_bytes(), before)
            # Restructuring an annotated rest refuses; unchanged-duration entry still preserves its text/id.
            page.evaluate("""SCORE.editor.setSelection({order:0,pattern:'verse',track:'guitar',voice:0,at:[2,1],string:1});
                document.querySelector('[data-ui=duration]').value='8';""")
            page.evaluate("SCORE.editor.enterPitch(67)")
            self.assertIn('annotated rest', page.locator('.vt-tab-status').inner_text())
            self.assertEqual((folder / 'song.yaml').read_bytes(), before)
            page.evaluate("document.querySelector('[data-ui=duration]').value='4'; SCORE.editor.enterPitch(67)")
            self.settled(page, "SCORE.view.score.patterns.verse.beats.find(b=>b.id==='rest').notes.length===1")
            rest = next(b for b in state.song['score']['patterns']['verse']['beats'] if b['id'] == 'rest')
            self.assertEqual((rest['text'], rest['written']['value']), ('Keep me',4))
            page.click('[data-action=undo]')
            self.settled(page, "SCORE.view.score.patterns.verse.beats.find(b=>b.id==='rest').notes.length===0")
            self.assertEqual((folder / 'song.yaml').read_bytes(), before)
            self.assertEqual(errors, [])

    def test_piano_refusals_and_captured_targets(self):
        with self.muted_page(api.to_yaml(self.piano_song()), compact=True) as (page, state, folder):
            page.evaluate("tab('tab')")
            page.wait_for_selector('.vt-piano')
            before = (folder / 'song.yaml').read_bytes()
            posts = []
            page.on('request', lambda r: posts.append(r.post_data_json) if r.method == 'POST' and urlsplit(r.url).path in ('/api/score','/api/score_command') else None)
            select_gap = """SCORE.editor.setSelection({order:0,pattern:'verse',track:'guitar',voice:0,at:[1,13],string:1});
                document.querySelector('[data-ui=duration]').value='8'"""
            for at, pitch, phrase in [([5,4],67,'inside an authored'), ([5,2],67,'annotated rest'),
                                      ([1,13],73,'first available string'), ([1,13],120,'0–119'),
                                      ([1,13],-1,'0–119'), ([15,4],67,'pattern boundary')]:
                page.evaluate("""x=>SCORE.editor.setSelection({order:0,pattern:'verse',track:'guitar',voice:0,at:x,string:1})""", at)
                page.evaluate('n=>SCORE.editor.enterPitch(n)', pitch)
                self.assertIn(phrase, page.locator('.vt-tab-status').inner_text())
            self.assertEqual(len(posts), 2)  # Backend owns rest/boundary admission.
            self.assertTrue(all(p.get('action') == 'place' for p in posts))
            posts.clear()
            for change in [
                "SCORE.editor.setSelection({order:0,pattern:'verse',track:'guitar',voice:1,at:[1,13],string:1})",
                "SCORE.editor.update({...SCORE.view,order:2})",
                "SCORE.editor.update({...SCORE.view,order:1,pattern:'bridge'})",
                "SCORE.editor.update({...SCORE.view,song:'another-song'})",
                "SCORE.editor.update({...SCORE.view,revision:'changed'})",
                "SCORE.editor.update({...SCORE.view,editable:false})",
                "LV.playing=true",
            ]:
                page.evaluate("LV.playing=false;SCORE.editor.update(SCORE.view);" + select_gap)
                page.evaluate("() => { void SCORE.editor.enterPitch(67); " + change + "; }")
                page.wait_for_function("document.querySelector('.vt-tab-status').textContent.includes('selection changed')")
            page.evaluate("LV.playing=false;SCORE.editor.update(SCORE.view)")
            self.assertEqual(posts, [])
            self.assertEqual((folder / 'song.yaml').read_bytes(), before)
            self.assertEqual(len(state.history), 0)
            page.evaluate("SCORE.editor.update({...SCORE.view,editable:false})")
            page.evaluate("SCORE.editor.enterPitch(67)")
            self.assertIn('Enable editing', page.locator('.vt-tab-status').inner_text())
            page.evaluate("SCORE.editor.update(SCORE.view); LV.playing=true")
            page.evaluate("SCORE.editor.enterPitch(67)")
            self.assertIn('Stop playback', page.locator('.vt-tab-status').inner_text())
            page.evaluate("LV.playing=false")
            # Semantically unchanged refresh is allowed and sends the captured full revision.
            page.evaluate(select_gap)
            revision = page.evaluate('SCORE.view.revision')
            page.evaluate("() => { void SCORE.editor.enterPitch(67); SCORE.editor.update({...SCORE.view}); }")
            self.settled(page, "SCORE.view.score.patterns.verse.beats.length===4")
            self.assertEqual(len(posts), 1)
            self.assertEqual(posts[0]['revision'], revision)
            page.click('[data-action=undo]')
            self.settled(page, "SCORE.view.score.patterns.verse.beats.length===3")
            self.assertEqual((folder / 'song.yaml').read_bytes(), before)

    def test_piano_place_rest_spans_duration_clipboard_and_response_navigation(self):
        from tests.test_tablature import beat, note
        source = api.from_yaml(NATIVE_SONG)
        source['module']['channels'] = [dict(name='High'), dict(name='Low')]
        score = source['score']
        score['ties'] = []
        score['tracks']['guitar'].update(tuning=[64,59], channels=[0,1])
        score['patterns']['verse']['beats'] = [
            dict(beat('chord', [0,1], [note('high',64,1,0),note('low',59,2,0)]), text='Sounding metadata'),
            beat('rest',[1,1],[]),
            beat('next',[2,1],[note('next-n',65,1,1)]),
            beat('other',[2,1],[note('other-n',59,2,0)],voice=1),
            beat('tail',[3,1],[note('tail-n',66,1,2)])]
        with self.muted_page(api.to_yaml(source), compact=True) as (page,state,folder):
            self.assertFalse(state.error,state.error)
            before = (folder/'song.yaml').read_bytes()
            original = json.loads(json.dumps(state.song['score']['patterns']['verse']['beats']))
            page.evaluate("tab('tab')")
            page.wait_for_selector('.vt-piano')
            requests, responses = [], []
            page.locator('.vt-tab-inspector > summary').click()
            page.on('request', lambda r: requests.append((urlsplit(r.url).path,r.post_data_json))
                    if r.method == 'POST' and urlsplit(r.url).path in ('/api/score','/api/score_command') else None)
            page.on('response', lambda r: responses.append(r.json()) if urlsplit(r.url).path == '/api/score_command' else None)
            page.evaluate("SCORE.editor.setSelection({order:0,pattern:'verse',track:'guitar',voice:0,at:[0,1],string:1})")
            page.click('[data-action=copy]')
            page.wait_for_function("document.querySelector('.vt-tab-status').textContent.startsWith('Copied')")
            # Interior entry splits only the bare rest and selects the returned exact source identity.
            page.evaluate("""SCORE.editor.setSelection({order:0,pattern:'verse',track:'guitar',voice:0,at:[5,4],string:1});
                document.querySelector('[data-ui=duration]').value='8'""")
            revision = page.evaluate('SCORE.view.revision')
            history = len(state.history)
            page.evaluate("SCORE.editor.enterPitch(67)")
            self.settled(page, "SCORE.view.score.patterns.verse.beats.some(b=>b.at[0]===5&&b.at[1]===4&&b.notes.length)")
            self.assertEqual(len(state.history), history+1)
            self.assertEqual(len(requests),1)
            self.assertEqual((requests[0][0],requests[0][1]['action'],requests[0][1]['revision']),
                             ('/api/score_command','place',revision))
            actual = next(b for b in state.song['score']['patterns']['verse']['beats'] if b['at']==[5,4])
            selected = responses[-1]['selection']
            self.assertEqual((selected['at'],selected['beats']),([5,4],[actual['id']]))
            self.assertEqual(page.evaluate('[CUR.score.at,CUR.score.beat,CUR.score.note]'),
                             [[5,4],actual['id'],actual['notes'][0]['id']])
            rests = [b for b in state.song['score']['patterns']['verse']['beats'] if not b['notes']]
            self.assertEqual(sorted((b['at'],b['written']['value']) for b in rests), [([1,1],16),([7,4],16)])
            self.assertEqual(next(b for b in rests if b['at']==[1,1])['id'],'rest')
            page.click('[data-action=undo]')
            self.settled(page, "SCORE.view.score.patterns.verse.beats.length===5")
            self.assertEqual((folder/'song.yaml').read_bytes(),before)
            # Same-onset entry keeps the original rest ID, even after shortening.
            page.evaluate("""SCORE.editor.setSelection({order:0,pattern:'verse',track:'guitar',voice:0,at:[1,1],string:1});
                document.querySelector('[data-ui=duration]').value='8'; SCORE.editor.enterPitch(67)""")
            self.settled(page, "SCORE.view.score.patterns.verse.beats.find(b=>b.id==='rest').notes.length===1")
            self.assertEqual(page.evaluate('[CUR.score.at,CUR.score.beat]'), [[1,1],'rest'])
            self.assertEqual(responses[-1]['selection']['beats'], ['rest'])
            page.click('[data-action=undo]')
            self.settled(page, "SCORE.view.score.patterns.verse.beats.find(b=>b.id==='rest').notes.length===0")
            self.assertEqual((folder/'song.yaml').read_bytes(),before)
            # Native duration growth consumes rests; shrink leaves explicit tail rests, one undo each.
            for value, end in [('2',Fraction(2)),('8',Fraction(1,2))]:
                page.evaluate("""SCORE.editor.setSelection({order:0,pattern:'verse',track:'guitar',voice:0,at:[0,1],string:1})""")
                page.click('[data-action=go]')  # Publish the caret through the same UI path as a user.
                page.select_option('[data-ui=duration]',value)
                count, history = len(requests), len(state.history)
                page.click('[data-action=duration]')
                self.settled(page, f"SCORE.view.score.patterns.verse.beats.find(b=>b.id==='chord').written.value==={value}")
                self.assertEqual(len(requests),count+1)
                self.assertEqual(len(state.history),history+1)
                actual_beats = state.song['score']['patterns']['verse']['beats']
                head = next(b for b in actual_beats if b['id']=='chord')
                self.assertEqual((head['notes'],head['text']),(original[0]['notes'],'Sounding metadata'))
                for identity in ['next','other','tail']:
                    self.assertEqual(next(b for b in actual_beats if b['id']==identity),next(b for b in original if b['id']==identity))
                self.assertEqual(page.evaluate('[CUR.score.at,CUR.score.beat,CUR.score.note]'), [[0,1],'chord','high'])
                if end == Fraction(1,2):
                    self.assertTrue(any(b['at']==[1,2] and not b['notes'] for b in actual_beats))
                page.click('[data-action=undo]')
                self.settled(page, "SCORE.view.score.patterns.verse.beats.find(b=>b.id==='chord').written.value===4")
                self.assertEqual((folder/'song.yaml').read_bytes(),before)
            # A whole-note resize would hit sounding material; no shifting or fallback is allowed.
            page.select_option('[data-ui=duration]','1')
            page.click('[data-action=duration]')
            self.settled(page, "document.querySelector('.vt-tab-status').textContent.includes('unchanged')")
            self.assertEqual((folder/'song.yaml').read_bytes(),before)
            # Place must not replace Copy's clipboard; inspect the attempted paste into occupied material.
            page.evaluate("SCORE.editor.setSelection({order:0,pattern:'verse',track:'guitar',voice:0,at:[3,1],string:1})")
            page.click('[data-action=paste-safe]')
            page.wait_for_function("document.querySelector('.vt-tab-status').textContent.startsWith('Edit refused')")
            self.assertEqual([n['id'] for n in requests[-1][1]['clipboard']['beats'][0]['notes']],['high','low'])
            self.assertEqual((folder/'song.yaml').read_bytes(),before)
            # Navigation after submission is not undone by the returned selection.
            def navigate_during_request(route):
                page.evaluate('setCursor(2,0,0,0)')
                route.continue_()
            page.route('**/api/score_command',navigate_during_request)
            page.evaluate("""SCORE.editor.setSelection({order:0,pattern:'verse',track:'guitar',voice:0,at:[5,4],string:1});
                document.querySelector('[data-ui=duration]').value='8'; void SCORE.editor.enterPitch(67)""")
            self.settled(page, "SCORE.view.order===2 && SCORE.view.score.patterns.verse.beats.some(b=>b.at[0]===5&&b.at[1]===4&&b.notes.length)")
            self.assertEqual(page.evaluate('[CUR.o,CUR.row]'),[2,0])
            self.assertEqual(page.input_value('[data-ui=at]'),'0')
            page.unroute('**/api/score_command',navigate_during_request)
            page.click('[data-action=undo]')
            self.settled(page, "SCORE.view.score.patterns.verse.beats.length===5")
            self.assertEqual((folder/'song.yaml').read_bytes(),before)

    @staticmethod
    def fit_song(insufficient=False):
        from tests.test_tablature import TestPlaceFitCommand
        source = api.from_yaml(NATIVE_SONG)
        source['module']['channels'] = [dict(name='High'), dict(name='Low')]
        source['score']['tracks']['guitar'].update(tuning=[64,59], channels=[0,1])
        source['score']['ties'] = []
        model, _ = TestPlaceFitCommand().fixture(insufficient)
        source['score']['patterns']['verse']['beats'] = model['score']['patterns']['A']['beats']
        return source

    def test_native_fit_duration_outcomes_history_clipboard_and_defaults(self):
        for insufficient in (False, True):
            with self.subTest(insufficient=insufficient), self.muted_page(
                    api.to_yaml(self.fit_song(insufficient)), compact=True) as (page,state,folder):
                self.assertFalse(state.error,state.error)
                before = (folder/'song.yaml').read_bytes()
                original = json.loads(json.dumps(state.song['score']['patterns']['verse']['beats']))
                page.evaluate("tab('tab')")
                page.wait_for_selector('[data-ui=fit]')
                page.locator('.vt-tab-inspector > summary').click()
                page.evaluate("SCORE.editor.setSelection({order:0,pattern:'verse',track:'guitar',voice:0,at:[0,1],string:1})")
                page.click('[data-action=go]')
                self.assertFalse(page.is_checked('[data-ui=fit]'))
                page.click('[data-action=copy]')
                page.wait_for_function("document.querySelector('.vt-tab-status').textContent.startsWith('Copied')")
                requests = []
                page.on('request', lambda r: requests.append(r.post_data_json)
                        if r.method=='POST' and urlsplit(r.url).path in ('/api/score','/api/score_command') else None)

                def duration(value, checked=True):
                    page.set_checked('[data-ui=fit]',checked)
                    page.select_option('[data-ui=duration]',str(value))
                    with page.expect_response('**/api/score_command') as response:
                        page.click('[data-action=duration]')
                    result = response.value.json()
                    self.settled(page,"!document.querySelector('[data-ui=fit]').disabled")
                    return result

                # Unchecked remains strict, even though the model offers a qualified fit.
                result = duration(2,False)
                self.assertEqual(result['outcomes'], ['unchanged'])
                self.assertEqual(result['kept_durations'][0]['reason'], 'no_space')
                self.assertNotIn('fit',requests[-1])
                self.assertEqual((folder/'song.yaml').read_bytes(),before)
                self.assertEqual(len(state.history),0)
                # Shrink is an exact fit; undo creates the redo branch used by the no-op check.
                result = duration(8)
                self.assertEqual(result['outcomes'],['exact'])
                self.assertEqual(requests[-1]['fit'],'tg_duration')
                self.assertEqual(page.inner_text('.vt-tab-status'),'Selected rhythm updated; one Undo restores it.')
                self.assertEqual(page.input_value('[data-ui=duration]'),'8')
                self.assertEqual(len(state.history),1)
                page.click('[data-action=undo]')
                self.settled(page,"SCORE.view.score.patterns.verse.beats.find(b=>b.id==='a').written.value===4")
                self.assertEqual((folder/'song.yaml').read_bytes(),before)
                revision = page.evaluate('SCORE.view.revision')
                future = json.loads(json.dumps(state.future))
                # Same duration is a no-op; insufficient room is the other unchanged outcome.
                result = duration(1 if insufficient else 4)
                self.assertEqual(result['outcomes'],['unchanged'])
                self.assertTrue(page.inner_text('.vt-tab-status').startswith('Duration unchanged.'))
                self.assertEqual(page.input_value('[data-ui=duration]'),'4')
                self.assertEqual(page.evaluate('SCORE.view.revision'),revision)
                self.assertEqual((folder/'song.yaml').read_bytes(),before)
                self.assertEqual((len(state.history),state.future),(0,future))
                self.assertFalse(page.is_disabled('[data-action=redo]'))
                self.assertEqual(page.evaluate('[CUR.score.at,CUR.score.beat,CUR.score.note]'),[[0,1],'a','a-note'])
                if not insufficient:
                    result = duration(2)
                    self.assertEqual(result['outcomes'],['shifted'])
                    self.assertEqual(page.inner_text('.vt-tab-status'),'Selected rhythm updated; one Undo restores it. Fit moved or resized following beats.')
                    actual = state.song['score']['patterns']['verse']['beats']
                    self.assertEqual({b['id']:b['at'] for b in actual},{'a':[0,1],'b':[2,1],'c':[3,1]})
                    self.assertEqual(next(b for b in actual if b['id']=='b')['notes'],original[1]['notes'])
                    self.assertEqual(page.input_value('[data-ui=duration]'),'2')
                    self.assertEqual(len(state.history),1)
                    page.click('[data-action=undo]')
                    self.settled(page,"SCORE.view.score.patterns.verse.beats.find(b=>b.id==='a').written.value===4")
                    self.assertEqual((folder/'song.yaml').read_bytes(),before)
                # Read the actual Paste payload without changing the fixture.
                page.route('**/api/score',lambda route: route.fulfill(
                    status=200,content_type='application/json',body='{"error":"clipboard inspected"}'))
                page.click('[data-action=paste]')
                self.settled(page,"document.querySelector('.vt-tab-status').textContent.includes('clipboard inspected')")
                self.assertEqual(requests[-1]['clipboard']['beats'][0]['notes'][0]['id'],'a-note')
                page.unroute('**/api/score')
                page.reload()
                page.wait_for_function("typeof S!=='undefined'&&S?.song?.facts")
                page.evaluate("tab('tab')")
                page.wait_for_selector('[data-ui=fit]')
                self.assertFalse(page.is_checked('[data-ui=fit]'))

    def test_native_remove_unused_voice_button_removes_rests_in_one_step(self):
        from tests.test_tablature import beat
        source = self.fit_song()
        source['score']['patterns']['verse']['beats'] += [beat(f'v1-{i}', [2*i,1], [], value=2, voice=1) for i in range(2)]
        with self.muted_page(api.to_yaml(source)) as (page,state,folder):
            self.assertFalse(state.error,state.error)
            before = (folder/'song.yaml').read_bytes()
            voice0 = [b for b in json.loads(json.dumps(state.song['score']['patterns']['verse']['beats'])) if b['voice'] == 0]
            page.evaluate("tab('tab');setEdit(true)")
            page.wait_for_selector('.vt-tab-grid [data-note="a-note"]')
            requests = []
            page.on('request', lambda r: requests.append(r.post_data_json)
                    if r.method=='POST' and urlsplit(r.url).path in ('/api/score','/api/score_command') else None)
            page.click('.vt-tab-grid [data-note="a-note"]')
            page.click('[data-action=remove-unused-voice]')
            self.settled(page, "SCORE.view.score.patterns.verse.beats.every(b=>b.voice===0)")
            self.assertEqual([(r['action'], r['beats']) for r in requests], [('remove_unused_voice', ['a'])])
            self.assertEqual(page.inner_text('.vt-tab-status'), 'Removed 2 rests of voice 2.')
            self.assertEqual(state.song['score']['patterns']['verse']['beats'], voice0)
            self.assertEqual(len(state.history), 1)
            page.click('[data-action=undo]')
            self.settled(page, "SCORE.view.score.patterns.verse.beats.some(b=>b.voice===1)")
            self.assertEqual((folder/'song.yaml').read_bytes(), before)

    def test_native_tab_drag_selects_the_beat_range_and_shows_it(self):
        source=self.fit_song()
        # This case tests one-bar hit/range editing. Reusing its last sustained note
        # at both a loop boundary and song end correctly fails the IT release guard.
        source['orders']=['verse'];source['score']['order_ids']=['pass-1']
        with self.muted_page(api.to_yaml(source), compact=True) as (page,state,folder):
            self.assertFalse(state.error,state.error)
            before = (folder/'song.yaml').read_bytes()
            page.evaluate("tab('tab');setEdit(true)")
            page.wait_for_selector('[data-ui=track]', state='attached')
            self.capture_engraving(page)
            page.select_option('[data-ui=track]', 'guitar')
            page.wait_for_function('window.tabRendered && tabRenderApi.boundsLookup?.isFinished')
            # fit_song: a, b, a rest r and c, one per quarter of the first bar.
            start, end = (self.tab_lane_point(page, 0, i, 1) for i in (0, 2))
            page.mouse.move(start['x'], start['y'])
            page.mouse.down()
            page.mouse.move(start['x'] + 2, start['y'])   # under the drag distance: still a plain selection
            self.assertEqual(page.locator('.vt-tab-selection').count(), 0)
            page.mouse.move(end['x'], end['y'], steps=4)
            page.mouse.up()
            self.assertEqual(page.inner_text('.vt-tab-status'), 'Selected 3 beats.')
            self.assertEqual(sorted(page.evaluate("[...document.querySelectorAll('.vt-tab-selection')].map(e=>e.dataset.beat)")),
                             ['a', 'b', 'r'])
            # The range is the one TAB commands use: Shorter on it is one set_duration of those three beats.
            with page.expect_request('**/api/score_command') as request:
                page.keyboard.press('-')
            self.assertEqual(sorted(request.value.post_data_json['beats']), ['a', 'b', 'r'])
            # Strict Place splits the notes; the selected rest coalesces with its remainder.
            self.settled(page, "SCORE.view.score.patterns.verse.beats.filter(b=>['a','b'].includes(b.id)&&b.written.value===8).length===2")
            self.assertEqual(page.evaluate("SCORE.view.score.patterns.verse.beats.find(b=>b.id==='r').written.value"),4)
            page.click('[data-action=undo]')
            self.settled(page, "SCORE.view.score.patterns.verse.beats.every(b=>b.written.value===4)")
            self.assertEqual((folder/'song.yaml').read_bytes(), before)
            # A plain click afterwards clears the range and its highlight.
            self.click_tab_lane(page, 0, 3, 1)
            self.assertEqual(page.locator('.vt-tab-selection').count(), 0)

    def test_native_extend_and_clear_selection_buttons(self):
        with self.muted_page(api.to_yaml(self.fit_song())) as (page,state,folder):
            self.assertFalse(state.error,state.error)
            before = (folder/'song.yaml').read_bytes()
            page.evaluate("tab('tab');setEdit(true)")
            page.wait_for_selector('.vt-tab-grid [data-note="a-note"]')
            page.click('.vt-tab-grid [data-note="b-note"]')   # fit_song: a, b, rest r, c in one 4/4 display bar
            shaded = lambda: sorted(page.evaluate("[...document.querySelectorAll('.vt-tab-selection')].map(e=>e.dataset.beat)"))
            for action, status, beats in (
                    ('select-right', 'Selected 2 beats.', ['b', 'r']),
                    ('select-right', 'Selected 3 beats.', ['b', 'c', 'r']),
                    ('select-left', 'Selected 2 beats.', ['b', 'r']),
                    ('select-previous', 'Selected 2 beats.', ['a', 'b']),       # to the measure start, anchor b kept
                    ('select-next', 'Selected 3 beats.', ['b', 'c', 'r']),       # to the measure end
                    ('select-next', 'Selected 7 beats.', ['a', 'b', 'b', 'c', 'c', 'r', 'r']),
                    ('select-first', 'Selected 2 beats.', ['a', 'b']),
                    ('select-last', 'Selected 11 beats.', ['a', 'a', 'b', 'b', 'b', 'c', 'c', 'c', 'r', 'r', 'r']),
                    ('select-next', 'The selection cannot extend past the written song.', ['a', 'a', 'b', 'b', 'b', 'c', 'c', 'c', 'r', 'r', 'r']),
                    ('select-all', 'Selected 12 beats.', sorted(['a', 'b', 'c', 'r'] * 3)),
                    ('select-none', 'Selection cleared.', [])):
                with self.subTest(action=action, status=status):
                    page.click(f'[data-action={action}]')
                    self.assertEqual(page.inner_text('.vt-tab-status'), status)
                    self.assertEqual(shaded(), beats)
                    if action == 'select-last':
                        self.settled(page, 'SCORE.view.order===2')
            # The extended range is what the range commands use.
            page.click('.vt-tab-grid [data-note="b-note"]')
            page.click('[data-action=select-right]')
            with page.expect_request('**/api/score_command') as request:
                page.locator('#tab-editor').focus()
                page.keyboard.press('-')
            self.assertEqual(sorted(request.value.post_data_json['beats']), ['b', 'r'])
            self.settled(page, "SCORE.view.score.patterns.verse.beats.find(b=>b.id===`b`).written.value===8")
            page.click('[data-action=undo]')
            self.settled(page, "SCORE.view.score.patterns.verse.beats.find(b=>b.id===`b`).written.value===4")
            self.assertEqual((folder/'song.yaml').read_bytes(), before)

    def test_native_tab_shift_click_extends_from_the_anchor(self):
        with self.muted_page(api.to_yaml(self.fit_song()), compact=True) as (page,state,folder):
            self.assertFalse(state.error,state.error)
            page.evaluate("tab('tab');setEdit(true)")
            page.wait_for_selector('[data-ui=track]', state='attached')
            self.capture_engraving(page)
            page.select_option('[data-ui=track]', 'guitar')
            page.wait_for_function('window.tabRendered && tabRenderApi.boundsLookup?.isFinished')
            shaded = lambda: sorted(page.evaluate("[...document.querySelectorAll('.vt-tab-selection')].map(e=>e.dataset.beat)"))

            def shift_click(beat):
                point = self.tab_lane_point(page, 0, beat, 1)
                page.keyboard.down('Shift'); page.mouse.click(point['x'], point['y']); page.keyboard.up('Shift')

            self.click_tab_lane(page, 0, 1, 1)                     # caret on b
            shift_click(3)
            self.assertEqual((page.inner_text('.vt-tab-status'), shaded()), ('Selected 3 beats.', ['b', 'c', 'r']))
            shift_click(0)                                         # the anchor (b) stays
            self.assertEqual((page.inner_text('.vt-tab-status'), shaded()), ('Selected 2 beats.', ['a', 'b']))
            self.click_tab_lane(page, 0, 2, 1)                     # a plain click starts again
            self.assertEqual(shaded(), [])
            self.assertEqual(page.evaluate('CUR.score.beat'), 'r')

    @staticmethod
    def open_panel(page, name, action=None):
        """Open a TAB side panel afresh: its button toggles, so an open panel is closed and reopened."""
        if page.is_visible(f'form.vt-tab-panel[data-panel="{name}"]'):
            page.click(f'[data-action="{action or name}"]')
        page.click(f'[data-action="{action or name}"]')

    @staticmethod
    def open_setup(page):
        """Open Track setup with fresh fields: the button toggles, so an open panel is closed and reopened."""
        if page.is_visible('.vt-tab-setup:not(.vt-tab-lyrics):not(.vt-tab-chord):not(.vt-tab-curve)'):
            page.click('[data-action=setup]')
        page.click('[data-action=setup]')

    def test_owner_fixes_play_button_tab_playhead_panels_and_setup_label(self):
        with self.muted_page(NATIVE_SONG, compact=True) as (page, state, folder):
            self.assertFalse(state.error, state.error)
            page.evaluate("tab('tab')")
            page.wait_for_selector('[data-ui=track]', state='attached')
            self.capture_engraving(page)
            page.select_option('[data-ui=track]', 'guitar')
            page.wait_for_function('window.tabRendered && tabRenderApi.boundsLookup?.isFinished')
            # (1) Space plays through the live engine; the main button must show pause, then play again.
            page.locator('#tab-editor').focus()
            page.keyboard.press(' ')
            page.wait_for_function('LV.playing')
            page.wait_for_function("document.getElementById('playbtn').textContent==='❚❚'", timeout=3000)
            page.evaluate('lvStop()')
            page.wait_for_function("document.getElementById('playbtn').textContent==='▶'", timeout=3000)
            # (2) The playhead marker spans the TAB staff as well as standard notation. The page's follow tick
            # would replace a hand-set playhead with the stopped transport's, so it is paused here.
            page.evaluate('followScorePlayhead=()=>{}')
            page.evaluate("SCORE.editor.setPlayhead({o:0,row:12})")
            page.wait_for_selector('.vt-tab-playhead:not([hidden])')
            span = page.evaluate("""() => {
                const el=document.querySelector('.vt-tab-playhead'),beat=tabRendered.tracks[0].staves[0].bars[0].voices[0].beats.find(b=>b.notes.length);
                const all=tabRenderApi.boundsLookup.findBeats(beat),tab=all.at(-1).barBounds.visualBounds,score=all[0].barBounds.visualBounds;
                return {top:parseFloat(el.style.top),bottom:parseFloat(el.style.top)+parseFloat(el.style.height),
                        staves:all.length,scoreTop:score.y,tabBottom:tab.y+tab.h};
            }""")
            self.assertGreaterEqual(span['staves'], 2)
            self.assertLessEqual(span['top'], span['scoreTop'] + 0.5)
            self.assertGreaterEqual(span['bottom'], span['tabBottom'] - 0.5)
            page.evaluate("SCORE.editor.setPlayhead(null)")
            # (5) Track setup names tuning and capo, and opens at the tuning field.
            self.assertEqual(page.inner_text('[data-action=setup]'), 'Track setup')
            self.assertIn('tuning', page.get_attribute('[data-action=setup]', 'title').lower())
            for panel, button, close in (('.vt-tab-setup:not(.vt-tab-lyrics):not(.vt-tab-chord):not(.vt-tab-curve)', 'setup', 'close-setup'),
                                         ('.vt-tab-lyrics', 'lyrics', 'lyrics-close')):
                with self.subTest(panel=button):
                    hidden = lambda: page.evaluate(f"document.querySelector('{panel}').hidden")
                    page.click(f'[data-action={button}]')
                    self.assertFalse(hidden())
                    if button == 'setup':
                        self.assertEqual(page.evaluate("document.activeElement.dataset.ui"), 'tuning')
                    page.click(f'[data-action={button}]')   # (4) the button toggles
                    self.assertTrue(hidden())
                    page.click(f'[data-action={button}]')
                    page.locator(f'{panel} .vt-tab-close').click()   # (4) a Close at the top
                    self.assertTrue(hidden())
                    page.click(f'[data-action={button}]')
                    page.keyboard.press('Escape')   # (4) Escape, also with focus in a field
                    self.assertTrue(hidden())

    def test_free_edit_insert_rest_overfills_a_full_bar_and_is_flagged(self):
        from tests.test_tablature_sync import TestMeasureMenuState
        source = TestMeasureMenuState.full_bar_song()
        source['samples'][1]['file'] = 'a.wav'
        with self.muted_page(api.to_yaml(source)) as (page, state, folder):
            self.assertFalse(state.error, state.error)
            before = (folder / 'song.yaml').read_bytes()
            page.evaluate("tab('tab');setEdit(true)")
            page.wait_for_selector('[data-ui=track]', state='attached')
            page.evaluate('async i=>{setCursor(i,0);await scoreRefresh()}', 2)
            page.wait_for_selector('.vt-tab-grid [data-note="n0"]')
            self.assertFalse(page.is_checked('[data-ui=free-edit]'))   # strict, TuxGuitar's default
            page.wait_for_function("document.querySelector('.vt-tab-meter').textContent.startsWith('2 measure errors')")

            def insert():
                page.click('.vt-tab-grid [data-note="n0"]')
                page.locator('#tab-editor').focus()
                page.keyboard.press('Insert')
            insert()
            self.settled(page, "document.querySelector('.vt-tab-status').textContent.includes('needs room')")
            self.assertEqual((folder / 'song.yaml').read_bytes(), before)
            page.check('[data-ui=free-edit]')
            insert()
            self.settled(page, "SCORE.view.score.measures[2].to.at[0] === 5")
            self.assertEqual(page.inner_text('.vt-tab-status'), 'Rest inserted; the measure is now overfull (free edit).')
            self.assertEqual(state.song['patterns']['c']['rows'], 60)
            page.wait_for_function("document.querySelector('.vt-tab-meter').textContent.startsWith('3 measure errors')")
            self.assertIn('Bar 3, voice 1: is too long (overfull)', page.get_attribute('.vt-tab-meter', 'title'))
            self.assertEqual(len(state.history), 1)
            page.click('[data-action=undo]')
            self.settled(page, "SCORE.view.score.measures[2].to.at[0] === 4")
            self.assertEqual((folder / 'song.yaml').read_bytes(), before)

    def test_move_beats_buttons_shift_the_track_across_bars_with_exact_undo(self):
        from tests.test_tablature_sync import score_song
        source = score_song()
        source['samples'][1]['file'] = 'a.wav'
        with self.muted_page(api.to_yaml(source)) as (page, state, folder):
            self.assertFalse(state.error, state.error)
            before = (folder / 'song.yaml').read_bytes()
            page.evaluate("tab('tab');setEdit(true)")
            page.wait_for_selector('.vt-tab-grid [data-note="e"]')
            page.click('.vt-tab-grid [data-note="e"]')   # the chord at 0 in bar 1
            page.click('[data-action=move-beats-right]')
            self.settled(page, "SCORE.view.score.ties[0]?.from.occurrence === 'second'")
            self.assertTrue(page.inner_text('.vt-tab-status').startswith('Moved '))
            tail = next(b for b in state.song['score']['patterns']['b']['beats'] if any(n['id'] == 'tie_a' for n in b['notes']))
            self.assertEqual(tail['at'], [1, 2])   # crossed the bar line by the chord's quarter
            self.assertEqual(len(state.history), 1)
            page.click('[data-action=undo]')
            self.settled(page, "SCORE.view.score.ties[0]?.from.occurrence === 'first'")
            self.assertEqual((folder / 'song.yaml').read_bytes(), before)

    # User-path backfill (BACKLOG testing rule): each drives a control as a user and checks what the user sees.
    def test_user_path_track_buttons_new_track_and_enharmonic(self):
        with self.muted_page(PRINT_SONG) as (page, state, folder):
            before = (folder / 'song.yaml').read_bytes()
            page.evaluate("tab('tab');setEdit(true)")
            page.wait_for_selector('.vt-tab-grid button[data-note="lead-note-a"]')
            page.click('[data-action=track-last]')
            self.assertEqual(page.input_value('[data-ui=track]'), 'bass')
            page.click('[data-action=track-first]')
            self.assertEqual(page.input_value('[data-ui=track]'), 'lead')
            page.click('[data-action=new-track]')   # a fresh Setup: empty, editable name
            self.assertTrue(page.is_visible('form.vt-tab-panel[data-panel="setup"]'))
            self.assertEqual(page.input_value('[data-ui=name]'), '')
            self.assertFalse(page.evaluate("document.querySelector('[data-ui=name]').readOnly"))
            page.keyboard.press('Escape')
            page.click('.vt-tab-grid button[data-note="lead-note-a"]')
            page.click('[data-action=enharmonic]')
            # The fixture spells this F as E#; the toggle gives the key's spelling, F, and Undo E# again.
            spelled = "SCORE.view.score.patterns[SCORE.view.pattern].beats.some(b=>b.notes.some(n=>n.id==='lead-note-a' && n.spelling?.step==='%s'))"
            self.settled(page, spelled % 'F')
            self.assertEqual(len(state.history), 1)
            page.click('[data-action=undo]')
            self.settled(page, spelled % 'E')
            self.assertEqual((folder / 'song.yaml').read_bytes(), before)

    def test_user_path_setup_max_fret_and_instrument_refuse_readably(self):
        with self.muted_page(SONG) as (page, state, folder):
            before = (folder / 'song.yaml').read_bytes()
            self.open_tab(page)
            self.open_setup(page)
            self.assertEqual((page.input_value('[data-ui=max-fret]'), page.input_value('[data-ui=instrument]')), ('29', '1'))
            page.fill('[data-ui=max-fret]', '2')   # note-b sits on fret 3
            page.locator('.vt-tab-setup button[type=submit]').first.click()
            self.settled(page, "document.querySelector('.vt-tab-status').textContent.startsWith('Edit refused')")
            self.assertEqual((folder / 'song.yaml').read_bytes(), before)
            self.open_setup(page)
            page.fill('[data-ui=instrument]', '0')   # below 1: the browser's own check stops the form before sending
            page.locator('.vt-tab-setup button[type=submit]').first.click()
            self.assertFalse(page.evaluate("document.querySelector('[data-ui=instrument]').validity.valid"))
            self.assertEqual((folder / 'song.yaml').read_bytes(), before)

    def test_user_path_transpose_options_unticked_send_tuxguitars_flags(self):
        with self.muted_page(SONG) as (page, state, folder):
            before = (folder / 'song.yaml').read_bytes()
            self.open_tab(page)
            requests = []
            page.on('request', lambda r: requests.append(r.post_data_json)
                    if r.method == 'POST' and urlsplit(r.url).path == '/api/score_command' else None)
            self.open_panel(page, 'transpose')
            for box in ('all', 'chords', 'strings'):
                page.uncheck(f'[data-ui=transpose-{box}]')
            page.fill('[data-ui=transpose-semitones]', '1')
            page.click('.vt-tab-transpose button[type=submit]')
            self.settled(page, "SCORE.view.score.patterns.verse.beats.find(b=>b.id===`beat-a`).notes[0].pitch===65")
            self.assertEqual({k: requests[0][k] for k in ('all_tracks', 'apply_to_chords', 'try_keep_strings')},
                             dict(all_tracks=False, apply_to_chords=False, try_keep_strings=False))
            page.click('[data-action=undo]')
            self.settled(page, "SCORE.view.score.patterns.verse.beats.find(b=>b.id===`beat-a`).notes[0].pitch===64")
            self.assertEqual((folder / 'song.yaml').read_bytes(), before)

    def test_user_path_measure_fields_add_after_all_tracks_meter_to_end_and_move_left(self):
        from tests.test_tablature_sync import repeat_song, score_song
        source = repeat_song()
        source['samples'][1]['file'] = 'a.wav'
        with self.muted_page(api.to_yaml(source)) as (page, state, folder):
            before = (folder / 'song.yaml').read_bytes()
            page.evaluate("tab('tab');setEdit(true)")
            self.settled(page, 'SCORE.view?.native')
            self.open_panel(page, 'measures')
            page.fill('[data-ui=ops-from]', '1'); page.fill('[data-ui=ops-to]', '1')
            page.click('[data-action=measure-add-after]')
            self.settled(page, 'SCORE.view.orders.length===4')
            self.assertEqual([str(o) for o in state.song['orders']][:2], ['a', 'bar1'])
            page.click('[data-action=undo]')
            self.settled(page, 'SCORE.view.orders.length===3')
            page.check('[data-ui=ops-all]')
            page.click('[data-action=measure-copy]')
            page.wait_for_function("document.querySelector('.vt-tab-status').textContent==='Copied measure 1 (all tracks).'")
            # The occurrence pickers name each order readably; an overlapping new measure refuses.
            self.assertIn('1: a (first)', page.inner_text('[data-ui=measure-from-occ]'))
            page.select_option('[data-ui=measure]', '')
            page.select_option('[data-ui=measure-from-occ]', 'first')
            page.select_option('[data-ui=measure-to-occ]', 'second')
            page.click('.vt-tab-measures button[type=submit]')
            self.settled(page, "document.querySelector('.vt-tab-status').textContent.startsWith('Edit refused')")
            # 6/8 to the end from bar 2 (bar 1 holds a tracker tempo command, which re-barring would move): bars 2 and
            # 3 take it, and bar 3's note keeps its time, a quarter into its shorter bar.
            page.evaluate('async i=>{setCursor(i,0);await scoreRefresh()}', 1)
            self.open_panel(page, 'measures')
            page.select_option('[data-ui=measure]', 'b')
            page.fill('[data-ui=meter-n]', '6')
            page.select_option('[data-ui=meter-d]', '8')
            page.check('[data-ui=meter-to-end]')
            page.click('.vt-tab-measures button[type=submit]')
            self.settled(page, "SCORE.view.score.measures.slice(1).every(m => m.meter[0]===6 && m.meter[1]===8)")
            self.assertEqual([state.song['patterns'][n]['rows'] for n in 'abc'], [48, 36, 36])
            self.assertEqual(state.song['score']['patterns']['c']['beats'][0]['at'], [1, 1])
            page.click('[data-action=undo]')
            self.settled(page, "SCORE.view.score.measures.every(m => m.meter[0]===4)")
            self.assertEqual((folder / 'song.yaml').read_bytes(), before)
        source = score_song()
        source['samples'][1]['file'] = 'a.wav'
        with self.muted_page(api.to_yaml(source)) as (page, state, folder):
            before = (folder / 'song.yaml').read_bytes()
            page.evaluate("tab('tab');setEdit(true)")
            page.wait_for_selector('.vt-tab-grid [data-note="e"]')
            page.click('.vt-tab-grid [data-note="e"]')
            page.click('[data-action=move-beats-left]')
            self.settled(page, "!SCORE.view.score.patterns.a.beats.some(b=>b.notes.some(n=>n.id==='e'))")
            self.assertTrue(page.inner_text('.vt-tab-status').startswith('Moved '))
            page.click('[data-action=undo]')
            self.settled(page, "SCORE.view.score.patterns.a.beats.some(b=>b.notes.some(n=>n.id==='e'))")
            self.assertEqual((folder / 'song.yaml').read_bytes(), before)

    def check_side_panels(self, page, note):
        """Every TAB side panel opens from its button, which also closes it, has one ✕ Close at its top and closes on
        Escape (the owner could not close Measures). `note` is a grid note for the chord and curve panels."""
        names = page.evaluate("[...document.querySelectorAll('form.vt-tab-panel')].map(f => f.dataset.panel)")
        self.assertEqual(sorted(names), ['chord', 'curve', 'lyrics', 'measures', 'properties', 'setup', 'transpose'])
        openers = {'properties': 'properties', 'setup': 'setup', 'lyrics': 'lyrics', 'measures': 'measures', 'transpose': 'transpose',
                   'chord': 'chord-diagram', 'curve': 'bend'}
        for name, action in openers.items():
            with self.subTest(panel=name):
                form = f'form.vt-tab-panel[data-panel="{name}"]'
                hidden = lambda: page.evaluate(f"document.querySelector('{form}').hidden")

                def open_():
                    if name in ('chord', 'curve'):
                        page.click(f'.vt-tab-grid [data-note="{note}"]')
                    page.click(f'[data-action="{action}"]')
                    self.assertFalse(hidden())
                self.assertEqual(page.evaluate(f"[...document.querySelector('{form}').children].filter(c => c.matches('.vt-tab-close')).length"), 1)
                self.assertTrue(page.evaluate(f"document.querySelector('{form}').firstElementChild.matches('.vt-tab-close')"))
                open_()
                page.click(f'[data-action="{action}"]')   # the button toggles
                self.assertTrue(hidden())
                open_()
                page.click(f'{form} > .vt-tab-close')
                self.assertTrue(hidden())
                open_()
                page.locator(f'{form} input, {form} select, {form} textarea').first.focus()
                page.keyboard.press('Escape')   # also with focus in a field
                self.assertTrue(hidden())

    def test_every_side_panel_toggles_and_closes_by_x_and_escape(self):
        with self.muted_page(SONG) as (page, state, folder):
            self.assertFalse(state.error, state.error)
            before = (folder / 'song.yaml').read_bytes()
            self.open_tab(page)
            page.evaluate('setEdit(true)')
            self.check_side_panels(page, 'note-a')
            self.assertEqual((folder / 'song.yaml').read_bytes(), before)
            self.assertEqual(len(state.history), 0)

    @staticmethod
    def four_bar_song():
        """A four-bar guitar piece like the owner's four-bars example: one pattern and one 4/4 measure per bar."""
        tuning, bars = [64, 59, 55, 50, 45, 40], [[(2, 1), (1, 0), (1, 3), (1, 0)], [(4, 3), (3, 2), (2, 1), (3, 2)],
                                                  [(3, 0), (2, 0), (2, 3), (2, 0)], [(2, 1), (1, 0), (1, 3), (2, 1)]]
        names, ids = ['C', 'F', 'G', 'C2'], ['bar1', 'bar2', 'bar3', 'bar4']
        return {'module': {'title': 'Four-bar TAB example', 'tempo': 90, 'speed': 2, 'channels': [{'name': f'String {i + 1}'} for i in range(6)]},
                'samples': {1: {'file': 'a.wav', 'name': 'Guitar'}}, 'instruments': {1: {'sample': 1}},
                'patterns': {n: {'rows': 48, 'data': ''} for n in names}, 'orders': names,
                'score': {'version': 1, 'tracks': {'guitar': {'name': 'Guitar', 'tuning': tuning, 'capo': 0, 'instrument': 1, 'channels': list(range(6))}},
                          'order_ids': ids, 'ties': [],
                          'patterns': {n: {'row_step': [1, 12], 'beats': [
                              dict(id=f'beat{i}', track='guitar', voice=0, at=[i, 1], written=dict(value=4, dots=0, tuplet=[1, 1]),
                                   notes=[dict(id=f'note{i}', pitch=tuning[s - 1] + f, string=s, fret=f, velocity=95)])
                              for i, (s, f) in enumerate(bars[b])]} for b, n in enumerate(names)},
                          'measures': [dict(id=o, meter=[4, 4], **{'from': dict(occurrence=o, at=[0, 1]), 'to': dict(occurrence=o, at=[4, 1])})
                                       for o in ids]}}

    @staticmethod
    def duration_boundary_song():
        """The logged boundary selection: a final sixteenth rest and the next bar's sixteenth note."""
        import copy
        song = TestTablaturePage.four_bar_song()
        song['module']['title'] = 'Duration boundary editing'
        for visit, name in enumerate(('G', 'C2')):
            beats = []
            for index, original in enumerate(song['score']['patterns'][name]['beats']):
                beat = copy.deepcopy(original)
                beat['id'] = f'copy_visit{visit}_beat{index}'
                beat['notes'][0]['id'] = f'copy_visit{visit}_note{index}'
                beat['written'] = dict(value=8, dots=1, tuplet=[1, 1])
                beats.extend([beat, dict(id=f'rest_copy_visit{visit}_beat{index}', track='guitar', voice=0,
                    at=[index * 4 + 3, 4], written=dict(value=16, dots=0, tuplet=[1, 1]), notes=[])])
            song['score']['patterns'][name]['beats'] = beats
        head = song['score']['patterns']['C2']['beats'][0]
        head['written'] = dict(value=16, dots=0, tuplet=[1, 1])
        head['notes'][0].update(pitch=55, string=5, fret=10, channel=3)
        song['score']['patterns']['C2']['beats'].append(dict(id='rest_copy_visit1_beat0_2', track='guitar', voice=0,
            at=[1, 4], written=dict(value=8, dots=0, tuplet=[1, 1]), notes=[]))
        return song

    def duration_boundary_edits(self, page, song_path):
        """Shared by the real page and final packaged check; each edit gets one exact-source Undo."""
        original = song_path.read_bytes()
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.evaluate("tab('tab');setEdit(true)")
        page.wait_for_selector('[data-ui=track]', state='attached')
        self.capture_engraving(page)
        page.select_option('[data-ui=track]', 'guitar')
        for fit in (False, True):
            for action, value in (('shorter', 32), ('longer', 8)):
                page.wait_for_function('window.tabRendered&&tabRenderApi.boundsLookup?.isFinished')
                self.click_tab_lane(page, 2, 7, 5)
                self.settled(page, 'SCORE.view.order===2')
                page.keyboard.down('Shift')
                try:
                    self.click_tab_lane(page, 3, 0, 5)
                finally:
                    page.keyboard.up('Shift')
                self.settled(page, "document.querySelectorAll('.vt-tab-selection').length===2")
                page.set_checked('[data-ui=fit]', fit)
                with page.expect_request('**/api/score_command') as request:
                    page.click(f'[data-action={action}]')
                self.assertEqual(request.value.post_data_json['ui_context']['fit'], fit)
                self.settled(page, f"SCORE.view.score.patterns.C2.beats.find(b=>b.id==='copy_visit1_beat0').written.value==={value}")
                status = page.inner_text('.vt-tab-status')
                self.assertNotIn('refused', status)
                if action == 'longer':
                    self.assertIn('kept at the previous duration', status)
                self.assertEqual(page.evaluate("SCORE.view.score.patterns.G.beats.find(b=>b.id==='rest_copy_visit0_beat3').written.value"),
                                 16 if action == 'longer' else 32)
                # The API refresh completes before alphaTab's postRenderFinished paints the range.
                self.settled(page, "tabRenderApi.boundsLookup?.isFinished&&document.querySelector('.vt-tab-score').dataset.bars==='4'&&document.querySelectorAll('.vt-tab-selection').length==="
                             + ('4' if action == 'shorter' else '2'))
                page.click('[data-action=undo]')
                self.settled(page, "SCORE.view.score.patterns.C2.beats.find(b=>b.id==='copy_visit1_beat0').written.value===16")
                page.wait_for_function("tabRenderApi.boundsLookup?.isFinished&&document.querySelector('.vt-tab-score').dataset.bars==='4'")
                self.assertEqual(song_path.read_bytes(), original)
        self.assertFalse(errors, errors)

    def test_cross_range_duration_boundary_rest_and_tick_note(self):
        with self.muted_page(api.to_yaml(self.duration_boundary_song()), width=1920, height=1080) as (page, state, folder):
            self.duration_boundary_edits(page, folder / 'song.yaml')

    @staticmethod
    def tied_duration_song():
        """A bar-line sustain, room to lengthen its continuation, and an independent lower voice."""
        song = TestTablaturePage.four_bar_song()
        song['module']['title'] = 'Tied duration editing'
        for pattern, index in (('C', 3), ('F', 0)):
            song['score']['patterns'][pattern]['beats'][index]['notes'] = [
                dict(id=f'tie_{pattern}', pitch=64, string=1, fret=0, velocity=95)]
        song['score']['patterns']['F']['beats'][1]['notes'] = []
        song['score']['patterns']['F']['beats'].append(dict(id='lower', track='guitar', voice=1,
            at=[0, 1], written=dict(value=1, dots=0, tuplet=[1, 1]),
            notes=[dict(id='low', pitch=40, string=6, fret=0, velocity=95)]))
        song['score']['ties'] = [{'from': dict(occurrence='bar1', note='tie_C'),
                                  'to': dict(occurrence='bar2', note='tie_F')}]
        return song

    def tied_duration_edits(self, page, song_path):
        """Real duration controls, shared with the packaged check; every change has exact-source Undo."""
        original = song_path.read_bytes()
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.evaluate("tab('tab');setEdit(true)")
        self.settled(page, 'SCORE.view?.score&&SCORE.editor')
        self.capture_engraving(page)
        page.select_option('[data-ui=track]', 'guitar')
        peer = None
        for fit in (False, True):
            for action, value, dots, tuplet in (('shorter', 8, 0, [1, 1]), ('longer', 2, 0, [1, 1]),
                                                ('dots', 4, 1, [1, 1]), ('tuplet', 4, 0, [3, 2])):
                page.wait_for_function('window.tabRendered&&tabRenderApi.boundsLookup?.isFinished')
                self.click_tab_lane(page, 1, 0, 1)
                self.settled(page, 'SCORE.view.order===1')
                if peer is None:
                    peer = page.evaluate("SCORE.view.score.patterns.F.beats.find(b=>b.id==='lower')")
                page.set_checked('[data-ui=fit]', fit)
                with page.expect_request('**/api/score_command') as request:
                    if action in ('shorter', 'longer'):
                        page.click(f'[data-action={action}]')
                    else:
                        page.locator('#tab-editor').focus()
                        page.keyboard.press('*' if action == 'dots' else '/')
                self.assertEqual(request.value.post_data_json['ui_context']['fit'], fit)
                expected = dict(value=value, dots=dots, tuplet=tuplet)
                self.settled(page, "JSON.stringify(SCORE.view.score.patterns.F.beats.find(b=>b.id==='beat0').written)==="
                             + json.dumps(json.dumps(expected, separators=(',', ':'))))
                self.assertNotIn('refused', page.inner_text('.vt-tab-status'))
                self.assertEqual(page.evaluate('SCORE.view.score.ties.length'), 1)
                self.assertEqual(page.evaluate("SCORE.view.score.patterns.F.beats.find(b=>b.id==='lower')"), peer)
                self.settled(page, "tabRenderApi.boundsLookup?.isFinished&&document.querySelector('.vt-tab-grid [data-note=\"tie_F\"]').getAttribute('aria-pressed')==='true'")
                self.assertEqual(page.input_value('[data-ui=duration]'), str(value))
                page.click('[data-action=undo]')
                self.settled(page, "SCORE.view.score.patterns.F.beats.find(b=>b.id==='beat0').written.value===4&&SCORE.view.score.patterns.F.beats.find(b=>b.id==='beat0').written.dots===0&&SCORE.view.score.patterns.F.beats.find(b=>b.id==='beat0').written.tuplet[0]===1")
                self.assertEqual(song_path.read_bytes(), original)
        for ranged in (False, True):
            page.wait_for_function('tabRenderApi.boundsLookup?.isFinished')
            self.click_tab_lane(page, 0, 3, 1)
            self.settled(page, 'SCORE.view.order===0')
            if ranged:
                page.keyboard.down('Shift')
                try:
                    self.click_tab_lane(page, 1, 0, 1)
                finally:
                    page.keyboard.up('Shift')
                self.settled(page, "document.querySelectorAll('.vt-tab-selection').length===3")
            page.click('[data-action=shorter]')
            self.settled(page, "SCORE.view.score.patterns.C.beats.find(b=>b.id==='beat3').written.value===8&&SCORE.view.score.ties.length===0")
            self.assertIn('1 tie removed; separated notes play normally.', page.inner_text('.vt-tab-status'))
            self.assertEqual(page.evaluate("SCORE.view.score.patterns.F.beats.find(b=>b.id==='lower')"), peer)
            # The full-bar peer keeps the existing F rest in the phrase, alongside both new tails.
            self.settled(page, "tabRenderApi.boundsLookup?.isFinished&&" + ("document.querySelectorAll('.vt-tab-selection').length===6" if ranged
                         else "document.querySelector('.vt-tab-grid [data-note=\"tie_C\"]').getAttribute('aria-pressed')==='true'"))
            if ranged:
                self.assertEqual(page.evaluate("SCORE.view.score.patterns.F.beats.find(b=>b.id==='beat0').written.value"), 8)
            page.click('[data-action=undo]')
            self.settled(page, "SCORE.view.score.ties.length===1&&SCORE.view.score.patterns.C.beats.find(b=>b.id==='beat3').written.value===4")
            self.assertEqual(song_path.read_bytes(), original)
        self.assertFalse(errors, errors)

    def test_tied_duration_controls_history_and_voice(self):
        with self.muted_page(api.to_yaml(self.tied_duration_song()), width=1920, height=1080) as (page, state, folder):
            self.assertFalse(state.error, state.error)
            self.tied_duration_edits(page, folder / 'song.yaml')

    @staticmethod
    def everyday_rhythm_song():
        """Two editable note/rest phrases, a lower voice, and two untouched response bars."""
        song = TestTablaturePage.four_bar_song()
        song['module']['title'] = 'Everyday rhythm editing'
        for name in ('C', 'F'):
            phrase = []
            for i, beat in enumerate(song['score']['patterns'][name]['beats']):
                beat['written']['value'] = 8
                phrase.extend([beat, dict(id=f'rest{i}', track='guitar', voice=0, at=[2 * i + 1, 2],
                    written=dict(value=8, dots=0, tuplet=[1, 1]), notes=[])])
            song['score']['patterns'][name]['beats'] = phrase
        song['score']['patterns']['C']['beats'].append(dict(id='lower', track='guitar', voice=1,
            at=[0, 1], written=dict(value=1, dots=0, tuplet=[1, 1]),
            notes=[dict(id='low', pitch=40, string=6, fret=0, velocity=95)]))
        song['score']['patterns']['G']['beats'] = [b for b in song['score']['patterns']['G']['beats'] if b['id'] != 'beat2']
        song['score']['patterns']['G']['beats'].append(dict(id='peer-rest', track='guitar', voice=1,
            at=[0, 1], written=dict(value=1, dots=0, tuplet=[1, 1]), notes=[]))
        song['patterns']['C2']['data'] = '00: ... .. ... X40\n'
        return song

    def everyday_rhythm_edits(self, page, song_path):
        """A sustained editing session, shared with the packaged check, without reselecting after each edit."""
        original = song_path.read_bytes()
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.evaluate("tab('tab');setEdit(true)")
        page.wait_for_selector('[data-ui=track]', state='attached')
        self.capture_engraving(page)
        page.select_option('[data-ui=track]', 'guitar')
        if page.locator('.vt-tab-inspector').get_attribute('open') is None:
            page.locator('.vt-tab-inspector > summary').click()
        original_revision = page.evaluate('SCORE.view.revision')
        rendered = "window.tabRendered&&SCORE.view.revision===" + json.dumps(original_revision) + \
            "&&tabRenderedRevision===SCORE.view.revision&&tabRenderApi.boundsLookup?.isFinished&&document.querySelector('.vt-tab-score').dataset.bars==='4'"
        for fit in (False, True):
            page.wait_for_function(rendered)
            self.click_tab_lane(page, 0, 0, 2)
            self.settled(page, 'SCORE.view.order===0')
            page.keyboard.down('Shift')
            try:
                self.click_tab_lane(page, 1, 7, 3)
            finally:
                page.keyboard.up('Shift')
            self.settled(page, "document.querySelectorAll('.vt-tab-selection').length===17")
            peer = page.evaluate("SCORE.view.score.patterns.C.beats.find(b=>b.id==='lower')")
            page.set_checked('[data-ui=fit]', fit)
            changed_bytes = []
            for action, value, dots, tuplet, highlights in (
                    ('longer', 4, 0, [1, 1], 9), ('shorter', 8, 0, [1, 1], 17),
                    ('dots', 8, 1, [1, 1], None), ('tuplet', 8, 1, [3, 2], None)):
                with page.expect_request('**/api/score_command') as request:
                    if action in ('longer', 'shorter'):
                        page.click(f'[data-action={action}]')
                    else:
                        page.locator('#tab-editor').focus()
                        page.keyboard.press('*' if action == 'dots' else '/')
                self.assertEqual(request.value.post_data_json['ui_context']['fit'], fit)
                self.settled(page, "['C','F'].every(p=>SCORE.view.score.patterns[p].beats.filter(b=>b.voice===0&&b.notes.length).every(b=>"
                    + f"b.written.value==={value}&&b.written.dots==={dots}&&b.written.tuplet[0]==={tuplet[0]}))")
                self.assertNotIn('refused', page.inner_text('.vt-tab-status'))
                self.assertEqual(page.evaluate("SCORE.view.score.patterns.C.beats.find(b=>b.id==='lower')"), peer)
                self.settled(page, 'tabRenderApi.boundsLookup?.isFinished' +
                             (f"&&document.querySelectorAll('.vt-tab-selection').length==={highlights}" if highlights else ''))
                changed_bytes.append(song_path.read_bytes())
                # Copy must see a complete phrase, including current rest fills, after every duration change.
                page.click('[data-action=copy]')
                page.wait_for_function("document.querySelector('.vt-tab-status').textContent.startsWith('Copied ')")
            page.fill('[data-ui=velocity]', '63')
            page.click('[data-action=velocity]')
            self.settled(page, "['C','F'].every(p=>SCORE.view.score.patterns[p].beats.filter(b=>b.voice===0).every(b=>b.notes.every(n=>n.velocity===63)))")
            self.assertEqual(page.evaluate("SCORE.view.score.patterns.C.beats.find(b=>b.id==='lower')"), peer)
            self.assertNotIn('refused', page.inner_text('.vt-tab-status'))
            page.click('[data-action=copy]')
            page.wait_for_function("document.querySelector('.vt-tab-status').textContent.startsWith('Copied ')")
            saved = song_path.read_bytes()
            page.click('[data-action=undo]')
            self.settled(page, "SCORE.view.score.patterns.C.beats.find(b=>b.id==='beat0').notes[0].velocity===95")
            self.assertEqual(song_path.read_bytes(), changed_bytes[-1])
            page.click('[data-action=redo]')
            self.settled(page, "SCORE.view.score.patterns.C.beats.find(b=>b.id==='beat0').notes[0].velocity===63")
            self.assertEqual(song_path.read_bytes(), saved)
            for _ in range(5):
                page.click('[data-action=undo]')
                self.settled(page, '!EDQ.n')
            self.assertEqual(song_path.read_bytes(), original)
        # An invalid bar's implicit gap enables Free and preserves the following note's duration.
        page.wait_for_function(rendered)
        self.click_tab_lane(page, 2, 0, 3)
        self.settled(page, 'SCORE.view.order===2')
        peer_rest = page.evaluate("SCORE.view.score.patterns.G.beats.find(b=>b.id==='peer-rest')")
        page.check('[data-ui=fit]')
        page.select_option('[data-ui=dots]', '2')
        page.click('[data-action=duration]')
        self.settled(page, "SCORE.view.score.patterns.G.beats.find(b=>b.id==='beat0').written.dots===2&&SCORE.view.score.patterns.G.beats.find(b=>b.id==='beat1').written.value===4")
        self.assertNotIn('refused', page.inner_text('.vt-tab-status'))
        self.assertEqual(page.evaluate("SCORE.view.score.patterns.G.beats.find(b=>b.id==='beat1').at"), [7, 4])
        self.assertEqual(page.evaluate("SCORE.view.score.patterns.G.beats.find(b=>b.id==='beat3').at"), [11, 4])
        self.assertEqual(page.evaluate("SCORE.view.score.patterns.G.beats.find(b=>b.id==='peer-rest')"), peer_rest)
        self.assertEqual(page.input_value('[data-ui=dots]'), '2')
        page.click('[data-action=undo]')
        self.settled(page, "SCORE.view.score.patterns.G.beats.find(b=>b.id==='beat0').written.dots===0")
        self.assertEqual(song_path.read_bytes(), original)
        # Ordinary no-room and bar-end choices are visible no-ops, not an error or a new history entry.
        for bar, beat, string in ((3, 0, 2), (3, 3, 2)):
            page.wait_for_function(rendered)
            self.click_tab_lane(page, bar, beat, string)
            self.settled(page, f'SCORE.view.order==={bar}')
            for fit in (False, True):
                page.set_checked('[data-ui=fit]', fit)
                page.click('[data-action=longer]')
                self.settled(page, "document.querySelector('.vt-tab-status').textContent.includes('unchanged')")
                self.assertNotIn('refused', page.inner_text('.vt-tab-status'))
                self.assertEqual(page.input_value('[data-ui=duration]'), '4')
                self.assertEqual(song_path.read_bytes(), original)
        self.assertFalse(errors, errors)

    def test_everyday_rhythm_sequence_selection_copy_expression_and_history(self):
        with self.muted_page(api.to_yaml(self.everyday_rhythm_song()), width=1920, height=1080) as (page, state, folder):
            self.assertFalse(state.error, state.error)
            self.everyday_rhythm_edits(page, folder / 'song.yaml')

    def complete_section_edits(self, page, song_path):
        """Compose, arrange and vary sixteen bars through real controls; shared with the package check."""
        original = song_path.read_bytes()
        errors = []
        page.on('pageerror', lambda error: errors.append(error.stack or str(error)))
        page.on('requestfailed', lambda request: print('section request failed:', request.method,
            urlsplit(request.url).path, request.failure) if request.failure != 'net::ERR_ABORTED' else None)
        page.evaluate("tab('tab');setEdit(true)")
        page.wait_for_selector('[data-ui=track]', state='attached')
        self.capture_engraving(page)
        page.select_option('[data-ui=track]', 'guitar')
        if page.locator('.vt-tab-inspector').get_attribute('open') is None:
            page.locator('.vt-tab-inspector > summary').click()
        self.settled(page, 'SCORE.view?.native')
        original_revision = page.evaluate('SCORE.view.revision')
        snapshots = [(original, original_revision)]

        def rendered():
            self.settled(page, 'window.tabRendered&&tabRenderedRevision===SCORE.view.revision&&tabRenderApi.boundsLookup?.isFinished')

        def select(first, last, first_beat=0, last_beat=3):
            rendered()
            self.click_tab_lane(page, first, first_beat, 2)
            self.settled(page, f'SCORE.view.order==={first}')
            page.keyboard.down('Shift')
            try:
                self.click_tab_lane(page, last, last_beat, 2)
            finally:
                page.keyboard.up('Shift')
            self.settled(page, f'SCORE.view.order==={last}&&document.querySelectorAll(".vt-tab-selection").length>1')

        def edit(selector, endpoint='score_command', remember=True):
            with page.expect_response('**/api/' + endpoint) as response:
                page.click(selector)
            result = response.value.json()
            self.assertTrue(result.get('ok'), result)
            self.settled(page, 'SCORE.view.revision===' + json.dumps(result['revision']))
            self.assertNotIn('refused', page.inner_text('.vt-tab-status'))
            if remember:
                snapshots.append((song_path.read_bytes(), result['revision']))
            return result

        def undo(expected):
            page.click('[data-action=undo]')
            self.settled(page, 'SCORE.view.revision===' + json.dumps(expected[1]))
            self.assertEqual(song_path.read_bytes(), expected[0])

        select(0, 3)
        for total in (8, 12, 16):
            result = edit('[data-action=repeat]')
            self.assertEqual(page.evaluate('SCORE.view.orders.length'), total)
            self.assertEqual(len(result['selection']['range']), 4)
            self.assertGreater(page.locator('.vt-tab-selection').count(), 15)
        self.open_panel(page, 'measures')
        page.fill('[data-ui=ops-from]', '13')
        page.fill('[data-ui=ops-to]', '16')
        page.fill('[data-ui=ops-destination]', '5')
        before_orders = page.evaluate('SCORE.view.orders')
        edit('[data-action=measure-move]')
        self.assertEqual(page.evaluate('SCORE.view.orders'), before_orders[:4] + before_orders[12:] + before_orders[4:12])
        page.click('[data-action=close-measures]')
        select(12, 15)
        self.open_panel(page, 'transpose')
        self.assertEqual(page.input_value('[data-ui=transpose-scope]'), 'selection')
        self.assertTrue(page.is_disabled('[data-ui=transpose-all]'))
        page.fill('[data-ui=transpose-semitones]', '2')
        edit('.vt-tab-transpose button[type=submit]')
        page.click('[data-action=close-transpose]')
        edit('[data-action=shorter]')
        page.click('[data-action=copy]')
        page.wait_for_function("document.querySelector('.vt-tab-status').textContent.startsWith('Copied ')")
        page.fill('[data-ui=velocity]', '78')
        edit('[data-action=velocity]')
        self.assertTrue(page.evaluate("SCORE.view.orders.slice(12).every(p=>SCORE.view.score.patterns[p].beats.filter(b=>b.voice===0&&b.track==='guitar').every(b=>b.notes.every(n=>n.velocity===78)))"))
        # Changing the second bar to5/4 splits crossing bass notes and preserves sounding events (State check).
        rendered()
        self.click_tab_lane(page, 1, 0, 2)
        self.settled(page, 'SCORE.view.order===1')
        self.open_panel(page, 'measures')
        measure_id = page.evaluate('SCORE.view.score.measures[1].id')
        page.select_option('[data-ui=measure]', measure_id)
        page.fill('[data-ui=meter-n]', '5')
        edit('.vt-tab-measures button[type=submit]')
        self.assertEqual(page.evaluate('SCORE.view.score.measures[1].meter'), [5, 4])
        page.fill('[data-ui=ops-from]', '9')
        page.fill('[data-ui=ops-to]', '9')
        page.fill('[data-ui=ops-count]', '2')
        edit('[data-action=measure-add-before]')
        self.assertEqual(page.evaluate('SCORE.view.orders.length'), 18)
        page.fill('[data-ui=ops-from]', '9')
        page.fill('[data-ui=ops-to]', '10')
        edit('[data-action=measure-remove]')
        self.assertEqual(page.evaluate('SCORE.view.orders.length'), 16)
        page.click('[data-action=close-measures]')
        undo(snapshots[-2])
        page.click('[data-action=redo]')
        self.settled(page, 'SCORE.view.revision===' + json.dumps(snapshots[-1][1]))
        self.assertEqual(song_path.read_bytes(), snapshots[-1][0])
        for snapshot in reversed(snapshots[:-1]):
            undo(snapshot)

        # Boundary ties no longer block whole-phrase rest, delete and clean operations.
        for action in ('rest', 'delete', 'delete-beat', 'clean-beat'):
            select(0, 1)
            edit('[data-action=' + action + ']', remember=False)
            source = page.evaluate('SCORE.view.score')
            for name in ('C', 'F'):
                beats = source['patterns'][name]['beats']
                if action == 'delete-beat':
                    self.assertEqual(beats, [])
                else:
                    self.assertTrue(all(not b['notes'] for b in beats if action == 'clean-beat' or b.get('voice', 0) == 0))
            self.assertFalse(source['ties'])
            undo(snapshots[0])

        # Copy the head of an external tie, then replace the first quarter of a destination half note.
        rendered()
        self.click_tab_lane(page, 1, 3, 2)
        self.settled(page, 'SCORE.view.order===1')
        page.click('[data-action=copy]')
        page.wait_for_function("document.querySelector('.vt-tab-status').textContent.startsWith('Copied ')")
        self.click_tab_lane(page, 2, 0, 2)
        self.settled(page, 'SCORE.view.order===2')
        edit('[data-action=paste-span]', endpoint='score', remember=False)
        self.assertTrue(page.evaluate("SCORE.view.score.patterns.G.beats.some(b=>b.id.startsWith('copy_')&&b.written.value===4&&b.notes.length)"))
        self.assertTrue(page.evaluate("SCORE.view.score.patterns.G.beats.some(b=>b.id==='n1'&&b.at[0]===2)"))
        page.click('[data-action=copy]')
        page.wait_for_function("document.querySelector('.vt-tab-status').textContent.startsWith('Copied ')")
        undo(snapshots[0])

        rendered()
        self.click_tab_lane(page, 0, 0, 2)
        self.settled(page, 'SCORE.view.order===0')
        edit('[data-action=move-beats-right]', remember=False)
        self.assertEqual(page.evaluate('SCORE.view.orders.length'), 5)
        self.assertGreater(page.evaluate('SCORE.view.score.ties.length'), 1)
        undo(snapshots[0])
        self.assertFalse(errors, errors)

    def test_complete_section_composition_arrangement_and_boundary_edits(self):
        from tests.test_tablature_sync import complete_section_song
        source = complete_section_song()
        source['samples'][1]['file'] = 'a.wav'
        with self.muted_page(api.to_yaml(source), width=1920, height=1080) as (page, state, folder):
            self.assertFalse(state.error, state.error)
            self.complete_section_edits(page, folder / 'song.yaml')

    def test_render_export_it_of_a_native_score_reopens_as_tracker_notes(self):
        self.check_render_export_native_it(False)

    def test_render_export_it_repeats_and_endings_follow_performed_order(self):
        self.check_render_export_native_it(True)

    def test_render_export_it_percussion_keymaps_and_repeats(self):
        self.check_render_export_native_it(True, percussion=True)

    def test_render_export_it_technique_controls_and_standalone_audio(self):
        self.check_render_export_native_it(True, percussion=True, techniques=True)

    def test_render_export_it_pitch_controls_and_warning(self):
        self.check_render_export_it_pitch_controls(False)

    def test_render_export_it_whammy_control_and_warning(self):
        self.check_render_export_it_pitch_controls(True)

    def test_render_export_it_repetition_controls_and_warning(self):
        from tests.test_tablature_sync import native_repetition_it_song, repetition_render_metrics, it_cells
        from tests.test_pipeline import sine as tone
        from vulturetracker.openmpt import LoadedModule
        song = native_repetition_it_song()
        song['samples'][1]['file'], song['samples'][2]['file'] = 'a.wav', 'b.wav'
        edits = [(0,'trill',16),(1,'tremolo_picking',32),(3,'trill',4)]
        for index, flag, value in edits:
            song['score']['patterns']['a']['beats'][index]['notes'][0].pop(flag)
        with mock.patch.object(page_fixture,'sine',lambda hz:tone(hz*441/440)), self.muted_page(api.to_yaml(song)) as (page,state,folder):
            page.evaluate("tab('tab');setEdit(true)")
            for index, flag, value in edits:
                identity = song['score']['patterns']['a']['beats'][index]['notes'][0]['id']
                page.wait_for_selector(f'.vt-tab-grid [data-note={identity}]')
                page.click(f'.vt-tab-grid [data-note={identity}]')
                page.select_option('[data-ui=repetition-type]',flag)
                if flag=='trill': page.fill('[data-ui=trill-fret]','2')
                page.select_option('[data-ui=repetition-value]',str(value))
                page.click('[data-action=repetition]')
                self.settled(page,f'SCORE.view.score.patterns.a.beats[{index}].notes[0].{flag}?.value==={value}')
            before = (folder/'song.yaml').read_bytes(),len(state.history)
            page.click('[data-t=export]')
            page.select_option('#export-format','it')
            page.fill('#export-dest',str(folder/'pulse-output'))
            page.fill('#export-name','pulses')
            page.click('#export-go')
            page.wait_for_function("['done','error','failed','cancelled'].includes(S.export?.status)",timeout=20000)
            self.assertEqual(page.evaluate('S.export.status'),'done',page.evaluate('S.export'))
            self.assertIn('IT repetition:',page.inner_text('#export-result'))
            data = (folder/'pulse-output/pulses.it').read_bytes()
            self.assertEqual(sum(n is not None and n<120 for _,_,n,*_ in it_cells(data)[0]),14)
            pair = api.prepare_playback(folder/'song.yaml',sample_rate=48000)
            renders = []
            for backing,plan in [(pair['backing_it'],pair['plan']),(data,None)]:
                with LoadedModule(backing,48000,1,plan=plan) as module:
                    renders.append(module.render(rate=48000,oversample=1,max_seconds=2.2))
            metrics = repetition_render_metrics(*renders,48000,pair['plan'])
            self.assertLess(max(a['settled_rms_error'] for a in metrics['attacks']),.025,metrics)
            self.assertTrue(all(a['shift_frames']==0 for a in metrics['attacks']),metrics)
            self.assertEqual(((folder/'song.yaml').read_bytes(),len(state.history)),before)

    def test_render_export_it_harmonic_controls_layers_and_audio(self):
        from tests.test_tablature_sync import native_harmonic_it_song, harmonic_render_metrics, it_cells
        from tests.test_pipeline import sine as tone
        from vulturetracker.openmpt import LoadedModule
        song=native_harmonic_it_song()
        song['samples'][1]['file']='a.wav'
        edits=[(i,b['notes'][0].pop('harmonic')) for i,b in enumerate(song['score']['patterns']['a']['beats'])]
        with mock.patch.object(page_fixture,'sine',lambda _:tone(441)), self.muted_page(api.to_yaml(song)) as (page,state,folder):
            page.evaluate("tab('tab');setEdit(true)")
            for index,value in [(0,dict(type='semi',data=0))]+edits:
                page.wait_for_selector(f'.vt-tab-grid [data-note=h{index}]')
                page.click(f'.vt-tab-grid [data-note=h{index}]')
                page.select_option('[data-ui=harmonic-type]',value['type'])
                if value['type']!='natural': page.select_option('[data-ui=harmonic-data]',str(value['data']))
                page.click('[data-action=harmonic]')
                self.settled(page,f"SCORE.view.score.patterns.a.beats[{index}].notes[0].harmonic?.type==='{value['type']}'")
                self.assertIn(value['type']+' harmonic',page.get_attribute(f'.vt-tab-grid [data-note=h{index}]','title'))
            before=(folder/'song.yaml').read_bytes(),len(state.history)
            page.click('[data-t=export]'); page.select_option('#export-format','it')
            page.fill('#export-dest',str(folder/'harmonic-output')); page.fill('#export-name','harmonics')
            page.click('#export-go')
            page.wait_for_function("['done','error','failed','cancelled'].includes(S.export?.status)",timeout=20000)
            self.assertEqual(page.evaluate('S.export.status'),'done',page.evaluate('S.export'))
            data=(folder/'harmonic-output/harmonics.it').read_bytes()
            self.assertEqual(sum(n is not None and n<120 for _,_,n,*_ in it_cells(data)[0]),14)
            pair=api.prepare_playback(folder/'song.yaml',sample_rate=48000)
            renders=[]
            for backing,plan in ((pair['backing_it'],pair['plan']),(data,None)):
                with LoadedModule(backing,48000,1,plan=plan) as mod:
                    renders.append(mod.render(rate=48000,oversample=1,max_seconds=4.2))
            metrics=harmonic_render_metrics(*renders,48000,pair['plan'])
            self.assertLess(max(a['settled_error'] for a in metrics['attacks']),.02,metrics)
            self.assertEqual(((folder/'song.yaml').read_bytes(),len(state.history)),before)

    def test_harmonic_articulation_labels_separated_controls_print_and_undo(self):
        from tests.test_tablature_sync import native_harmonic_it_song
        from tests.test_tablature import beat, note
        song = native_harmonic_it_song(); song['samples'][1]['file'] = 'a.wav'
        song['samples'][1]['loop']['end'] = 8820
        song['score']['patterns']['a']['beats'] = [
            dict(beat('artificial', [0,1], [dict(note('artificial',64,1,0), velocity=95, harmonic=dict(type='artificial',data=0))]), text='Keep cue'),
            beat('natural', [1,1], [dict(note('natural',76,1,12), velocity=95, harmonic=dict(type='natural'))]),
            beat('semi', [2,1], [dict(note('semi',64,1,0), velocity=95, harmonic=dict(type='semi',data=0))])]
        song['score']['patterns']['b']['beats'] = []
        with self.muted_page(api.to_yaml(song), width=1920, height=1080) as (page,state,folder):
            before = (folder/'song.yaml').read_bytes()
            baseline = api.compile_song(folder/'song.yaml')[0]
            events = json.loads(json.dumps(state.mod.native_score['plan']['events']))
            page.evaluate("tab('tab');setEdit(true)"); page.wait_for_selector('.vt-tab-grid [data-note=semi]')
            self.capture_engraving(page)
            for identity, flag in zip(('artificial','natural','semi'), ('tapping','slapping','popping')):
                page.click(f'.vt-tab-grid [data-note={identity}]')
                page.select_option('[data-ui=tap-slap-pop]',flag);page.click('[data-action=tap-slap-pop]')
                self.settled(page,f'SCORE.view.score.patterns.a.beats.find(b=>b.id==={json.dumps(identity)}).notes[0].{flag}')
            page.wait_for_function("[...document.querySelectorAll('.vt-tab-score svg text')].some(e=>e.textContent==='P')")
            print('editor label gaps', articulation_harmonic_boxes(page,'.vt-tab-score'))
            self.assertIn('Keep cue', page.inner_text('.vt-tab-score'))
            saved = (folder/'song.yaml').read_bytes()
            self.assertEqual(api.compile_song(folder/'song.yaml')[0],baseline)
            self.assertEqual(state.mod.native_score['plan']['events'],events)
            preview=page.context.browser.new_page(viewport={'width':1920,'height':1080})
            preview.goto(self.print_url(page,state));self.print_ready(preview)
            print('print label gaps', articulation_harmonic_boxes(preview,'.vt-print-pages'))
            self.assertIn('Keep cue',preview.inner_text('.vt-print-pages'))
            preview.locator('form button[type=submit]').click();self.print_ready(preview)
            articulation_harmonic_boxes(preview,'.vt-print-pages')  # Repeated render remains stable.
            preview.select_option('[name=notation]','tab')
            preview.locator('form button[type=submit]').click();self.print_ready(preview)
            print('TAB-only label gaps', articulation_harmonic_boxes(preview,'.vt-print-pages'))
            for scale in ('40','150'):
                preview.fill('[name=scale]',scale)
                preview.locator('form button[type=submit]').click();self.print_ready(preview)
                print('TAB-only scale',scale,articulation_harmonic_boxes(preview,'.vt-print-pages'))
            preview.close()
            self.assertEqual((folder/'song.yaml').read_bytes(),saved)
            for _ in range(3):
                revision=page.evaluate('SCORE.view.revision');page.click('[data-action=undo]')
                self.settled(page,f'SCORE.view.revision!=={json.dumps(revision)}')
            self.assertEqual((folder/'song.yaml').read_bytes(),before)

    def test_render_export_it_articulation_controls_warning_audio_and_undo(self):
        from tests.test_tablature_sync import native_articulations_it_song, swing_render_metrics
        from tests.test_pipeline import sine as tone
        song = native_articulations_it_song()
        song['samples'][1]['file'] = 'a.wav'; song['samples'][2]['file'] = 'b.wav'
        for b in song['score']['patterns']['a']['beats']:
            for flag in ('tapping', 'slapping', 'popping'): b['notes'][0].pop(flag, None)
        with mock.patch.object(page_fixture, 'sine', lambda hz: tone(hz*441/440)), self.muted_page(api.to_yaml(song)) as (page, state, folder):
            before = (folder/'song.yaml').read_bytes()
            baseline = api.compile_song(folder/'song.yaml')[0]
            events = json.loads(json.dumps(state.mod.native_score['plan']['events']))
            page.evaluate("tab('tab');setEdit(true)"); page.wait_for_selector('.vt-tab-grid [data-note=e0]')
            self.capture_engraving(page)
            for identity, flag in zip(('e0', 'e1', 's0'), ('tapping', 'slapping', 'popping')):
                page.click(f'.vt-tab-grid [data-note={identity}]')
                page.select_option('[data-ui=tap-slap-pop]', flag); page.click('[data-action=tap-slap-pop]')
                self.settled(page, f'SCORE.view.score.patterns.a.beats.find(b=>b.id==={json.dumps(identity)}).notes[0].{flag}')
                self.assertEqual(page.input_value('[data-ui=tap-slap-pop]'), flag)
            self.assertEqual(state.mod.native_score['plan']['events'], events)
            page.click('[data-t=export]'); page.select_option('#export-format', 'it')
            page.fill('#export-dest', str(folder/'marks-output')); page.fill('#export-name', 'marks'); page.click('#export-go')
            page.wait_for_function("['done','error','failed','cancelled'].includes(S.export?.status)", timeout=20000)
            self.assertEqual(page.evaluate('S.export.status'), 'done', page.evaluate('S.export'))
            self.assertIn('IT notation: tapping, slapping, popping markings omitted', page.inner_text('#export-result'))
            data = (folder/'marks-output/marks.it').read_bytes()
            self.assertEqual(data, baseline)
            swing_render_metrics(folder/'song.yaml', data, 48000)
            page.evaluate("tab('tab')")
            for _ in range(3):
                revision = page.evaluate('SCORE.view.revision'); page.click('[data-action=undo]')
                self.settled(page, f'SCORE.view.revision!=={json.dumps(revision)}')
            self.assertEqual((folder/'song.yaml').read_bytes(), before)

    def test_lyrics_diagram_it_controls_warnings_undo_and_shortcut(self):
        from vulturetracker import server
        from tests.test_gui import read_song_shortcut
        source=self.four_bar_song()
        with self.muted_page(api.to_yaml(source),width=1920,height=1080) as (page,state,folder):
            before=(folder/'song.yaml').read_bytes();baseline=api.compile_song(folder/'song.yaml')[0]
            events=json.loads(json.dumps(state.mod.native_score['plan']['events']))
            page.evaluate("tab('tab');setEdit(true)");page.wait_for_selector('.vt-tab-score svg');self.capture_engraving(page)
            page.click('[data-action=lyrics]');page.fill('[data-ui=lyrics-text]','Soft light drifts home')
            page.click('[data-ui=lyrics-apply]');self.settled(page,"SCORE.view.score.tracks.guitar.lyrics?.text==='Soft light drifts home'")
            page.click('[data-action=chord-diagram]');page.fill('[data-ui=chord-name]','Em')
            for i,fret in enumerate((0,0,0,2,2,0),1):page.fill(f'[data-chord-string="{i}"]',str(fret))
            page.locator('.vt-tab-chord button[type=submit]').click()
            self.settled(page,"Object.values(SCORE.view.score.patterns).some(p=>p.beats.some(b=>b.chord?.name==='Em'))")
            self.assertEqual(state.mod.native_score['plan']['events'],events)
            self.assertEqual(api.compile_song(folder/'song.yaml')[0],baseline)
            page.click('[data-t=export]');page.select_option('#export-format','it')
            page.fill('#export-dest',str(folder/'notation-output'));page.fill('#export-name','notation');page.click('#export-go')
            page.wait_for_function("['done','error','failed'].includes(S.export?.status)",timeout=20000)
            self.assertEqual(page.evaluate('S.export.status'),'done',page.evaluate('S.export'))
            for label in ('IT notation: lyrics omitted','IT notation: chord diagrams omitted'):
                self.assertIn(label,page.inner_text('#export-result'))
            self.assertEqual((folder/'notation-output/notation.it').read_bytes(),baseline)
            from vulturetracker.itreader import read_it
            self.assertTrue(read_it(baseline)[0].patterns)
            if os.name=='nt':
                link=folder/"Café's & $ shortcut.lnk";window=mock.Mock()
                window.create_file_dialog.side_effect=[(str(link),),None]
                page.click('[data-t=project]')
                with mock.patch.dict(sys.modules, {'webview': SimpleNamespace(SAVE_DIALOG=30)}), \
                     mock.patch.object(server.Handler,'window',window):
                    page.click('#song-shortcut');page.wait_for_function("document.querySelector('#shortcut-result').textContent.startsWith('Saved shortcut:')")
                    self.assertIn(str(folder/'song.yaml'),read_song_shortcut(link)['args'])
                    page.click('#song-shortcut');page.wait_for_function("document.querySelector('#shortcut-result').textContent.startsWith('Cancelled')")
            page.evaluate("tab('tab')")
            for _ in range(2):
                rev=page.evaluate('SCORE.view.revision');page.click('[data-action=undo]');self.settled(page,f'SCORE.view.revision!=={json.dumps(rev)}')
            self.assertEqual((folder/'song.yaml').read_bytes(),before)

    @unittest.skipUnless(os.name=='nt' and os.environ.get('VT_NATIVE_DIALOG')=='1','Opt-in native Save dialog; desktop lease required')
    def test_windows_shortcut_native_save_cancel(self):
        from tools.exe_check import native_shortcut_dialog
        from tests.test_gui import read_song_shortcut
        with self.muted_page(NATIVE_SONG) as (page,state,folder):
            before=(folder/'song.yaml').read_bytes()
            link=folder/"Café's & $ shortcut.lnk"
            native_shortcut_dialog(page,link,os.getpid())
            self.assertIn(str(folder/'song.yaml'),read_song_shortcut(link)['args'])
            saved=link.read_bytes()
            native_shortcut_dialog(page,link,os.getpid(),cancel_overwrite=True)
            self.assertEqual(link.read_bytes(),saved)
            native_shortcut_dialog(page,link,os.getpid(),cancel=True)
            self.assertEqual(link.read_bytes(),saved);self.assertEqual((folder/'song.yaml').read_bytes(),before)

    def test_render_export_it_fade_control_warning_audio_and_undo(self):
        from tests.test_tablature_sync import native_fade_it_song,fade_render_metrics
        from tests.test_pipeline import sine as tone
        song=native_fade_it_song();song['samples'][1]['file']='a.wav';song['samples'][2]['file']='b.wav'
        song['score']['patterns']['a']['beats'][0]['notes'][0].pop('fade_in')
        with mock.patch.object(page_fixture,'sine',lambda hz:tone(hz*441/440)),self.muted_page(api.to_yaml(song)) as (page,state,folder):
            before=(folder/'song.yaml').read_bytes()
            page.evaluate("tab('tab');setEdit(true)");page.wait_for_selector('.vt-tab-grid [data-note=fade]')
            self.capture_engraving(page);page.click('.vt-tab-grid [data-note=fade]');page.click('[data-action=fade-in]')
            self.settled(page,'SCORE.view.score.patterns.a.beats[0].notes[0].fade_in')
            self.assertEqual(page.get_attribute('[data-action=fade-in]','aria-pressed'),'true')
            self.assertTrue(any(e['type']=='gain' for e in state.mod.native_score['plan']['events']))
            page.click('[data-t=export]');page.select_option('#export-format','it')
            page.fill('#export-dest',str(folder/'fade-output'));page.fill('#export-name','fade');page.click('#export-go')
            page.wait_for_function("['done','error','failed','cancelled'].includes(S.export?.status)",timeout=20000)
            self.assertEqual(page.evaluate('S.export.status'),'done',page.evaluate('S.export'))
            self.assertIn('IT fade_in:',page.inner_text('#export-result'))
            fade_render_metrics(folder/'song.yaml',(folder/'fade-output/fade.it').read_bytes(),48000)
            page.evaluate("tab('tab')");page.click('[data-action=undo]')
            self.settled(page,'!SCORE.view.score.patterns.a.beats[0].notes[0].fade_in')
            self.assertEqual((folder/'song.yaml').read_bytes(),before)

    def test_render_export_it_swing_controls_and_standalone_audio(self):
        from tests.test_tablature_sync import native_swing_it_song,swing_render_metrics,it_cells
        from tests.test_pipeline import sine as tone
        song=native_swing_it_song();song['samples'][1]['file']='a.wav';song['samples'][2]['file']='b.wav'
        for m in song['score']['measures']:m.pop('swing')
        with mock.patch.object(page_fixture,'sine',lambda hz:tone(hz*441/440)),self.muted_page(api.to_yaml(song)) as (page,state,folder):
            page.evaluate("tab('tab');setEdit(true)");page.wait_for_selector('.vt-tab-score svg')
            self.capture_engraving(page);self.open_panel(page,'measures')
            for index,mode in enumerate(('eighth','sixteenth')):
                page.select_option('[data-ui=measure]',mode);page.select_option('[data-ui=measure-swing]',mode)
                page.click('.vt-tab-measures button[type=submit]')
                self.settled(page,f'SCORE.view.score.measures[{index}].swing==="{mode}"')
                self.assertEqual(page.input_value('[data-ui=measure-swing]'),mode)
            self.assertEqual(page.evaluate('tabRendered.masterBars.slice(0,2).map(b=>b.tripletFeel)'),
                page.evaluate('[alphaTab.model.TripletFeel.Triplet8th,alphaTab.model.TripletFeel.Triplet16th]'))
            before=(folder/'song.yaml').read_bytes(),len(state.history)
            page.click('[data-t=export]');page.select_option('#export-format','it')
            page.fill('#export-dest',str(folder/'swing-output'));page.fill('#export-name','swing');page.click('#export-go')
            page.wait_for_function("['done','error','failed','cancelled'].includes(S.export?.status)",timeout=20000)
            self.assertEqual(page.evaluate('S.export.status'),'done',page.evaluate('S.export'))
            data=(folder/'swing-output/swing.it').read_bytes()
            self.assertEqual(sum(n is not None and n<120 for _,_,n,*_ in it_cells(data)[0]),5)
            swing_render_metrics(folder/'song.yaml',data,48000)
            self.assertEqual(((folder/'song.yaml').read_bytes(),len(state.history)),before)

    def test_compact_stroke_grace_annotations_preserve_cues_tooltips_and_print(self):
        from tests.test_tablature import note
        source=self.four_bar_song()
        patterns=source['score']['patterns']
        stroke=patterns['C']['beats'][3];stroke['stroke']=dict(direction='up',value=4)
        stroke['notes'].append(dict(note('brush',60,2,1),velocity=79))
        patterns['F']['beats'][0]['text']='Play softly'
        patterns['G']['beats'][0]['notes'][0]['grace']=dict(fret=2,value=16,velocity=63,on_beat=True,transition='hammer')
        with self.muted_page(api.to_yaml(source),width=1920,height=1080) as (page,state,folder):
            before=(folder/'song.yaml').read_bytes(),len(state.history)
            events=json.dumps(state.mod.native_score['plan'],sort_keys=True)
            page.evaluate("tab('tab');setEdit(false)")
            page.wait_for_selector('.vt-tab-score svg');self.capture_engraving(page)
            page.select_option('[data-ui=track]','guitar')
            page.wait_for_function('window.tabRendered && window.tabRenderApi?.boundsLookup')
            summary="""()=>{const beats=tabRendered.tracks.flatMap(t=>t.staves.flatMap(s=>s.bars.flatMap(b=>b.voices.flatMap(v=>v.beats))));
                return {texts:beats.map(b=>b.text).filter(Boolean),brushes:beats.filter(b=>b.brushType!==0).length,
                    graces:beats.filter(b=>b.graceType!==0).length};}"""
            expected=dict(texts=['Play softly'],brushes=1,graces=1)
            self.assertEqual(page.evaluate(summary),expected)
            self.assertIn('Stroke up · 1/4',page.get_attribute('.vt-tab-grid [data-note=note3]','title'))
            page.evaluate('setCursor(2,0,0,0)');self.settled(page,'SCORE.view.order===2')
            self.assertIn('Grace fret 2, 1/16, velocity 63, on beat, hammer (notation only)',
                          page.get_attribute('.vt-tab-grid [data-note=note0]','title'))
            self.assertNotIn('Grace fret',page.inner_text('.vt-tab-score'))
            self.assertNotIn('Stroke up',page.inner_text('.vt-tab-score'))
            preview=page.context.browser.new_page(viewport={'width':1920,'height':1080})
            preview.goto(self.print_url(page,state));self.print_ready(preview);self.capture_engraving(preview)
            preview.locator('form button[type=submit]').click();self.print_ready(preview)
            self.assertEqual(preview.evaluate(summary),expected)
            self.assertNotIn('Grace fret',preview.locator('body').inner_text())
            self.assertNotIn('Stroke up',preview.locator('body').inner_text())
            preview.close()
            self.assertEqual(((folder/'song.yaml').read_bytes(),len(state.history)),before)
            self.assertEqual(json.dumps(state.mod.native_score['plan'],sort_keys=True),events)

    def test_render_export_it_stroke_controls_and_standalone_audio(self):
        from tests.test_tablature_sync import native_stroke_it_song,stroke_render_metrics,it_cells
        from tests.test_pipeline import sine as tone
        song=native_stroke_it_song();song['samples'][1]['file']='a.wav'
        for b in song['score']['patterns']['a']['beats']: b.pop('stroke',None)
        with mock.patch.object(page_fixture,'sine',lambda _:tone(441)),self.muted_page(api.to_yaml(song)) as (page,state,folder):
            page.evaluate("tab('tab');setEdit(true)")
            for index,direction in enumerate(('down','up')):
                page.wait_for_selector(f'.vt-tab-grid [data-note={direction}1]')
                page.click(f'.vt-tab-grid [data-note={direction}1]')
                page.select_option('[data-ui=stroke-direction]',direction)
                page.select_option('[data-ui=stroke-value]','4');page.click('[data-action=stroke]')
                self.settled(page,f'SCORE.view.score.patterns.a.beats[{index}].stroke?.direction==="{direction}"')
                self.assertEqual(page.input_value('[data-ui=stroke-direction]'),direction)
            before=(folder/'song.yaml').read_bytes(),len(state.history)
            page.click('[data-t=export]');page.select_option('#export-format','it')
            page.fill('#export-dest',str(folder/'stroke-output'));page.fill('#export-name','strokes');page.click('#export-go')
            page.wait_for_function("['done','error','failed','cancelled'].includes(S.export?.status)",timeout=20000)
            self.assertEqual(page.evaluate('S.export.status'),'done',page.evaluate('S.export'))
            data=(folder/'stroke-output/strokes.it').read_bytes()
            self.assertEqual(sum(n is not None and n<120 for _,_,n,*_ in it_cells(data)[0]),9)
            stroke_render_metrics(folder/'song.yaml',data,48000)
            self.assertEqual(((folder/'song.yaml').read_bytes(),len(state.history)),before)

    def test_render_export_it_grace_controls_and_standalone_audio(self):
        from tests.test_tablature_sync import native_grace_it_song,repetition_render_metrics,it_cells
        from tests.test_pipeline import sine as tone
        from vulturetracker.openmpt import LoadedModule
        song=native_grace_it_song()
        song['samples'][1]['file'],song['samples'][2]['file']='a.wav','b.wav'
        edits=[(i,b['notes'][0].pop('grace')) for i,b in enumerate(song['score']['patterns']['a']['beats'])]
        with mock.patch.object(page_fixture,'sine',lambda hz:tone(hz*441/440)),self.muted_page(api.to_yaml(song)) as (page,state,folder):
            page.evaluate("tab('tab');setEdit(true)")
            for index,value in edits:
                nid=song['score']['patterns']['a']['beats'][index]['notes'][0]['id']
                page.wait_for_selector(f'.vt-tab-grid [data-note={nid}]'); page.click(f'.vt-tab-grid [data-note={nid}]')
                page.select_option('[data-ui=grace-kind]','grace')
                page.fill('[data-ui=grace-fret]',str(value['fret']))
                page.fill('[data-ui=grace-velocity]',str(value['velocity']))
                page.select_option('[data-ui=grace-value]',str(value['value']))
                page.select_option('[data-ui=grace-timing]','on' if value['on_beat'] else 'before')
                page.select_option('[data-ui=grace-transition]',value['transition'])
                page.click('[data-action=grace]')
                self.settled(page,f'SCORE.view.score.patterns.a.beats[{index}].notes[0].grace?.value==={value["value"]}')
                self.assertEqual(page.input_value('[data-ui=grace-velocity]'),str(value['velocity']))
            before=(folder/'song.yaml').read_bytes(),len(state.history)
            page.click('[data-t=export]');page.select_option('#export-format','it')
            page.fill('#export-dest',str(folder/'grace-output'));page.fill('#export-name','grace');page.click('#export-go')
            page.wait_for_function("['done','error','failed','cancelled'].includes(S.export?.status)",timeout=20000)
            self.assertEqual(page.evaluate('S.export.status'),'done',page.evaluate('S.export'))
            data=(folder/'grace-output/grace.it').read_bytes()
            self.assertEqual(sum(n is not None and n<120 for _,_,n,*_ in it_cells(data)[0]),6)
            pair=api.prepare_playback(folder/'song.yaml',sample_rate=48000)
            renders=[]
            for backing,plan in ((pair['backing_it'],pair['plan']),(data,None)):
                with LoadedModule(backing,48000,1,plan=plan) as mod:
                    renders.append(mod.render(rate=48000,oversample=1,max_seconds=2.2))
            metrics=repetition_render_metrics(*renders,48000,pair['plan'])
            self.assertLess(max(a['settled_rms_error'] for a in metrics['attacks']),.035)
            self.assertEqual(((folder/'song.yaml').read_bytes(),len(state.history)),before)

    def check_render_export_it_pitch_controls(self, whammy):
        from tests.test_tablature_sync import native_pitch_it_song, native_whammy_it_song, pitch_render_metrics
        from tests.test_pipeline import sine as tone
        from vulturetracker.openmpt import LoadedModule
        song = native_whammy_it_song() if whammy else native_pitch_it_song()
        song['samples'][1]['file'] = 'a.wav'
        flags = ('tremolo_bar',) * 3 if whammy else ('bend', 'vibrato', 'slide')
        edits = [(beat['notes'][0]['id'], flag, beat['notes'][0].pop(flag))
                 for beat, flag in zip(song['score']['patterns']['a']['beats'], flags)]
        with mock.patch.object(page_fixture, 'sine', lambda _: tone(441)), self.muted_page(api.to_yaml(song)) as (page, state, folder):
            page.evaluate("tab('tab');setEdit(true)")
            for index, (identity, flag, value) in enumerate(edits):
                page.wait_for_selector(f'.vt-tab-grid [data-note={identity}]')
                page.click(f'.vt-tab-grid [data-note={identity}]')
                page.click(f'[data-action={flag.replace("_", "-")}]')
                if flag in ('bend', 'tremolo_bar'):
                    page.fill('[data-ui=curve-points]', ', '.join(f"{p['position']}:{p['value']}" for p in value['points']))
                    page.click('[data-ui=curve-apply]')
                self.settled(page, f'SCORE.view.score.patterns.a.beats[{index}].notes[0].{flag}')
            before = (folder / 'song.yaml').read_bytes(), len(state.history)
            page.click('[data-t=export]')
            page.select_option('#export-format', 'it')
            page.fill('#export-dest', str(folder / 'pitch-output'))
            page.fill('#export-name', 'pitch')
            page.click('#export-go')
            page.wait_for_function("['done','error','failed','cancelled'].includes(S.export?.status)", timeout=20000)
            self.assertEqual(page.evaluate('S.export.status'), 'done', page.evaluate('S.export'))
            self.assertIn('IT pitch:', page.inner_text('#export-result'))
            data = (folder / 'pitch-output/pitch.it').read_bytes()
            pair = api.prepare_playback(folder / 'song.yaml', sample_rate=48000)
            renders = []
            for backing, plan in [(pair['backing_it'], pair['plan']), (data, None)]:
                with LoadedModule(backing, 48000, 1, plan=plan) as module:
                    renders.append(module.render(rate=48000, oversample=1, max_seconds=2))
            metrics = pitch_render_metrics(*renders, 48000, whammy=whammy, plan=pair['plan'])
            self.assertLess(metrics['mixed' if whammy else 'slide']['cents'], 38.5, metrics)
            self.assertLess(max(metrics['cycle_error_cents']), 75, metrics)
            self.assertLess(abs(metrics['plain'][1]), .5, metrics)
            self.assertEqual(((folder / 'song.yaml').read_bytes(), len(state.history)), before)

    def check_render_export_native_it(self, repeated, percussion=False, techniques=False):
        """Drive the real export control, then reopen editable IT cells without a native playback plan."""
        from tests.test_tablature_sync import it_cells
        song = self.four_bar_song()
        if percussion:
            from tests.test_tablature_sync import native_percussion_it_song
            song = native_percussion_it_song()
            if techniques:
                from tests.test_tablature_sync import native_technique_it_song
                song = native_technique_it_song()
                first = song['score']['patterns']['a']['beats'][0]['notes'][0]
                first.pop('ghost')
                first.pop('staccato')
            for sample in song['samples'].values():
                sample['file'] = 'a.wav'
            song['score']['measures'][1]['repeat_close'] = 1
        elif repeated:
            song['score']['measures'][0]['repeat_open'] = True
            song['score']['measures'][1].update(repeat_close=1, endings=[1])
            song['score']['measures'][2]['endings'] = [2]
        with self.muted_page(api.to_yaml(song)) as (page, state, folder):
            self.assertFalse(state.error, state.error)
            if techniques:
                page.evaluate("tab('tab');setEdit(true)")
                page.wait_for_selector('.vt-tab-grid [data-note=n0]')
                page.click('.vt-tab-grid [data-note=n0]')
                for flag in ('ghost', 'staccato'):
                    page.click(f'[data-action={flag}]')
                    self.settled(page, f'SCORE.view.score.patterns.a.beats[0].notes[0].{flag}')
                    self.assertEqual(page.get_attribute(f'[data-action={flag}]', 'aria-pressed'), 'true')
            before = (folder / 'song.yaml').read_bytes(), len(state.history)
            destination = folder / 'it-output'
            page.click('[data-t=export]')
            page.select_option('#export-format', 'it')
            page.fill('#export-dest', str(destination))
            page.fill('#export-name', 'four-bars')
            page.click('#export-go')
            page.wait_for_function("['done','error','failed','cancelled'].includes(S.export?.status)", timeout=20000)
            self.assertEqual(page.evaluate('S.export.status'), 'done', page.evaluate('S.export'))
            self.assertTrue(page.inner_text('#export-result').startswith('done · 1/1 files'))
            cells, rows, seconds = it_cells((destination / 'four-bars.it').read_bytes())
            attacks = [(r, n, v) for r, ch, n, v, *_ in cells if n is not None and n < 120]
            if percussion:
                from vulturetracker.itreader import read_it
                module, _ = read_it((destination / 'four-bars.it').read_bytes())
                self.assertEqual(module.instruments[1].keymap[36], (60, 2))
                self.assertEqual(module.instruments[1].keymap[42], (62, 3))
                self.assertEqual(module.instruments[2].keymap[100], (48, 3))
                self.assertEqual((len(attacks), rows), (22, 192))
                self.assertAlmostEqual(seconds, 6 if techniques else 8, delta=.01)
                expected = [(r, n, v) for r, ch, n, v, *_ in it_cells(api.compile_song(folder / 'song.yaml')[0])[0]
                            if n is not None and n < 120]
            else:
                expected_rows = 240 if repeated else 192
                self.assertEqual(len(attacks), expected_rows // 12)
                self.assertEqual(attacks[:4], [(0, 60, 48), (12, 64, 48), (24, 67, 48), (36, 64, 48)])
                self.assertEqual(rows, expected_rows)
                self.assertAlmostEqual(seconds, expected_rows * 2 * 2.5 / 90, delta=0.01)
                expected = [(round(Fraction(*e['at']) * 12), e['pitch'], 48)
                            for e in state.mod.native_score['plan']['events'] if e['type'] == 'note_on']
            self.assertEqual(attacks, expected)
            if techniques:
                from vulturetracker.openmpt import LoadedModule
                from tests.test_pipeline import left, rms
                pair = api.prepare_playback(folder / 'song.yaml', sample_rate=48000)
                with LoadedModule(pair['backing_it'], 48000, 1, plan=pair['plan']) as native:
                    reference = left(native.render(rate=48000, oversample=1, max_seconds=6))
                with LoadedModule((destination / 'four-bars.it').read_bytes(), 48000, 1) as standalone:
                    actual = left(standalone.render(rate=48000, oversample=1, max_seconds=6))
                self.assertAlmostEqual(rms(actual) / rms(reference), 1, delta=.04)
                self.assertIn((6, 0, 255, None, 0, 0), cells)  # the enabled staccato actually releases early
                self.assertIn((0, 0, 64, 40, 0, 0), cells)  # the enabled ghost uses performed velocity
            self.assertEqual(((folder / 'song.yaml').read_bytes(), len(state.history)), before)

    def test_time_signature_to_the_end_reflows_notes_keep_their_times(self):
        """TuxGuitar's time signature from bar 2 to the end on the four-bar piece: 3/4 bars, notes at the same times,
        one bar added for the last beat; Pattern, the live engine's onsets and the engraving all follow."""
        from vulturetracker.notation import parse_cell
        with self.muted_page(api.to_yaml(self.four_bar_song())) as (page, state, folder):
            self.assertFalse(state.error, state.error)
            before = (folder / 'song.yaml').read_bytes()
            onsets = lambda: sorted((e['frame'], e['pitch']) for e in state.mod.native_score['plan']['events'] if e['type'] == 'note_on')
            played = onsets()
            page.evaluate("tab('tab');setEdit(true)")
            page.wait_for_selector('[data-ui=track]', state='attached')
            self.capture_engraving(page)
            page.select_option('[data-ui=track]', 'guitar')
            page.wait_for_selector('.vt-tab-grid [data-note="note0"]')
            page.evaluate('async i=>{setCursor(i,0);await scoreRefresh()}', 1)
            self.open_panel(page, 'measures')
            page.select_option('[data-ui=measure]', 'bar2')
            page.fill('[data-ui=meter-n]', '3')
            page.check('[data-ui=meter-to-end]')
            page.click('.vt-tab-measures button[type=submit]')
            self.settled(page, 'SCORE.view.orders.length === 5')
            self.assertEqual(page.inner_text('.vt-tab-status'),
                             'Time signature 3/4 from measure 2 to the end; notes keep their times, 1 measure added.')
            self.assertEqual(onsets(), played)   # what the live engine plays: every note at the same frame
            # Bar 3 (pattern G) now starts at quarter 7: bar 2's last quarter (F's fourth note, A3) opens it.
            self.assertEqual(parse_cell(state.pattern_rows(2, occurrence='bar3')['display_rows'][0][2]).note, 57)
            page.wait_for_function('window.tabRendered && tabRenderApi.boundsLookup?.isFinished && tabRendered.masterBars.length === 5')
            self.assertEqual(len(state.history), 1)
            page.click('[data-action=undo]')
            self.settled(page, 'SCORE.view.orders.length === 4')
            self.assertEqual((folder / 'song.yaml').read_bytes(), before)

    def test_ui_audit_panels_labels_note_names_layout_and_whole_score(self):
        """The shared UI audit: panels close three ways, every button is named, pitches read as note names, toolbar
        controls neither overlap nor clip at the default and a narrow width, and the whole piece is engraved. A
        screenshot of the score is kept for a look (VT_UI_AUDIT_DIR, else the test folder)."""
        with self.muted_page(api.to_yaml(self.four_bar_song())) as (page, state, folder):
            self.assertFalse(state.error, state.error)
            before = (folder / 'song.yaml').read_bytes()
            page.evaluate("tab('tab');setEdit(true)")
            page.wait_for_selector('[data-ui=track]', state='attached')
            self.capture_engraving(page)
            page.select_option('[data-ui=track]', 'guitar')
            page.wait_for_function('window.tabRendered && tabRenderApi.boundsLookup?.isFinished')
            page.wait_for_selector('.vt-tab-grid [data-note="note0"]')
            self.check_side_panels(page, 'note0')
            unnamed = page.evaluate("""[...document.querySelectorAll('#tab-editor button')]
                .filter(b => !(b.textContent.trim() || b.title || b.getAttribute('aria-label'))).map(b => b.outerHTML.slice(0, 80))""")
            self.assertEqual(unnamed, [])
            # Readable pitches: note names where a guitarist reads them, not MIDI numbers.
            self.open_setup(page)
            self.assertEqual(page.input_value('[data-ui=tuning]'), 'E4 B3 G3 D3 A2 E2')
            page.keyboard.press('Escape')
            headers = page.evaluate("[...document.querySelectorAll('.vt-tab-grid tr th:first-child')].slice(1).map(t => t.textContent)")
            self.assertEqual(headers, ['1 · E4', '2 · B3', '3 · G3', '4 · D3', '5 · A2', '6 · E2'])
            board = page.locator('details.vt-fretboard')
            if not board.evaluate('e => e.open'):
                board.locator(':scope > summary').click()
            page.wait_for_function("document.querySelector('[data-fb=context]').textContent.includes('tuning')")
            self.assertIn('tuning E4 B3 G3 D3 A2 E2', page.inner_text('[data-fb=context]'))
            # Layout at the default and the narrowest width: no two toolbar controls overlap, none is clipped or pushed off.
            for width in (1400, 1180):   # 1180: the app's own minimum (#app min-width); narrower, the whole app scrolls
                with self.subTest(width=width):
                    page.set_viewport_size({'width': width, 'height': 900})
                    page.wait_for_timeout(300)
                    problems = page.evaluate("""() => {
                        const controls = [...document.querySelectorAll('#tab-editor .vt-tab-tools button, #tab-editor .vt-tab-tools input, #tab-editor .vt-tab-tools select, #tab-editor .vt-tab-nav button')]
                            .filter(e => e.checkVisibility());
                        const rects = controls.map(e => [e, e.getBoundingClientRect()]), out = [];
                        const name = e => (e.dataset.action || e.dataset.ui || e.textContent.trim()).slice(0, 30);
                        const page = document.documentElement.clientWidth;
                        for (const [e, r] of rects) {
                            if (r.right > page + 1) out.push('off the page: ' + name(e));
                            if (e.tagName === 'BUTTON' && e.scrollWidth > e.clientWidth + 1) out.push('clipped: ' + name(e));
                        }
                        for (let i = 0; i < rects.length; i++) for (let j = i + 1; j < rects.length; j++) {
                            const [a, p] = rects[i], [b, q] = rects[j];
                            const w = Math.min(p.right, q.right) - Math.max(p.left, q.left), h = Math.min(p.bottom, q.bottom) - Math.max(p.top, q.top);
                            if (w > 1 && h > 1) out.push('overlap: ' + name(a) + ' / ' + name(b));
                        }
                        return out;
                    }""")
                    self.assertEqual(problems, [])
            page.set_viewport_size({'width': 1400, 'height': 900})
            # The whole piece is engraved: four bars, each drawn inside the score area.
            page.wait_for_function('window.tabRendered && tabRenderApi.boundsLookup?.isFinished')
            self.assertEqual(page.evaluate('tabRendered.masterBars.length'), 4)
            shot = Path(os.environ.get('VT_UI_AUDIT_DIR') or folder) / 'four-bars-score.png'
            shot.parent.mkdir(parents=True, exist_ok=True)
            page.locator('.vt-tab-score').screenshot(path=str(shot))
            self.assertGreater(shot.stat().st_size, 1000)
            self.assertEqual((folder / 'song.yaml').read_bytes(), before)

    def test_native_staff_click_adds_and_removes_the_clicked_pitch(self):
        with self.muted_page(SONG, compact=True) as (page, state, folder):
            self.assertFalse(state.error, state.error)
            before = (folder/'song.yaml').read_bytes()
            page.evaluate("tab('tab');setEdit(true)")
            page.wait_for_selector('[data-ui=track]', state='attached')
            self.capture_engraving(page)
            page.select_option('[data-ui=track]', 'guitar')
            page.wait_for_function('window.tabRendered && tabRenderApi.boundsLookup?.isFinished')
            self.assertEqual(page.input_value('[data-ui=staff-mode]'), 'natural')   # TuxGuitar's default edition mode
            # The treble staff's G4 line (second from the bottom: six steps under the top line F5) at beat-b (D4).
            point = page.evaluate("""() => {
                const beat=tabRendered.tracks[0].staves[0].bars[0].voices[0].beats.find(b=>b.notes.some(n=>n.fret===3));
                const bounds=tabRenderApi.boundsLookup.findBeats(beat)[0];
                const renderer=tabRenderApi.renderer.instance.layout.getRendererForBar('score',beat.voice.bar);
                const top=bounds.barBounds.visualBounds.y+renderer.getLineY(0),spacing=renderer.getLineY(1)-renderer.getLineY(0);
                const surface=document.querySelector('.vt-tab-score .at-surface'),r=surface.getBoundingClientRect(),s=r.width/surface.offsetWidth;
                const marker=document.createElement('div');Object.assign(marker.style,{position:'absolute',left:bounds.onNotesX+'px',
                    top:(top+3*spacing)+'px',width:'1px',height:'1px',pointerEvents:'none'});
                surface.append(marker);marker.scrollIntoView({block:'center'});const m=marker.getBoundingClientRect();marker.remove();
                return {x:m.x,y:m.y};
            }""")
            beat_b = "SCORE.view.score.patterns.verse.beats.find(b=>b.id===`beat-b`)"
            page.mouse.click(point['x'], point['y'])
            self.settled(page, f"{beat_b}.notes.some(n=>n.pitch===67)")
            notes = next(b for b in state.song['score']['patterns']['verse']['beats'] if b['id'] == 'beat-b')['notes']
            self.assertEqual(sorted(n['pitch'] for n in notes), [62, 67])
            page.mouse.click(point['x'], point['y'])   # the same pitch again: TuxGuitar removes it
            self.settled(page, f"!{beat_b}.notes.some(n=>n.pitch===67)")
            self.assertEqual(state.song['score'], api.from_yaml(before.decode('utf-8'))['score'])
            page.select_option('[data-ui=staff-mode]', 'select')
            history = len(state.history)
            page.mouse.click(point['x'], point['y'])
            page.wait_for_timeout(300)
            self.assertEqual(len(state.history), history)

    def test_native_insert_key_inserts_a_rest_and_moves_the_voice(self):
        with self.muted_page(api.to_yaml(self.fit_song(True))) as (page, state, folder):   # a 0, b 1, c 2, rest r 3
            self.assertFalse(state.error, state.error)
            before = (folder/'song.yaml').read_bytes()
            page.evaluate("tab('tab');setEdit(true)")
            page.wait_for_selector('.vt-tab-grid [data-note="b-note"]')
            page.click('.vt-tab-grid [data-note="b-note"]')
            page.locator('#tab-editor').focus()
            with page.expect_request('**/api/score_command') as request:
                page.keyboard.press('Insert')
            self.assertEqual(request.value.post_data_json['action'], 'insert_rest')
            self.settled(page, "SCORE.view.score.patterns.verse.beats.find(b=>b.id===`b`).at[0]===2")
            at = {b['id']: b['at'] for b in state.song['score']['patterns']['verse']['beats']}
            self.assertEqual((at['a'], at['b'], at['c']), ([0, 1], [2, 1], [3, 1]))
            self.assertNotIn('r', at)
            self.assertEqual(page.inner_text('.vt-tab-status'), 'Rest inserted; 1 trailing rest dropped.')
            self.assertEqual(len(state.history), 1)
            page.click('[data-action=undo]')
            self.settled(page, "SCORE.view.score.patterns.verse.beats.find(b=>b.id===`b`).at[0]===1")
            self.assertEqual((folder/'song.yaml').read_bytes(), before)

    def test_native_transpose_dialog_sends_tuxguitar_defaults(self):
        with self.muted_page(SONG) as (page, state, folder):
            self.assertFalse(state.error, state.error)
            before = (folder/'song.yaml').read_bytes()
            self.open_tab(page)
            requests = []
            page.on('request', lambda r: requests.append(r.post_data_json)
                    if r.method == 'POST' and urlsplit(r.url).path in ('/api/score', '/api/score_command') else None)
            page.click('[data-action=transpose]')
            self.assertEqual([page.is_checked(f'[data-ui=transpose-{k}]') for k in ('all', 'chords', 'strings')], [True] * 3)
            self.assertEqual(page.input_value('[data-ui=transpose-scope]'), 'track')
            page.fill('[data-ui=transpose-semitones]', '13')
            page.click('.vt-tab-transpose button[type=submit]')
            self.assertEqual(requests, [])   # out of range: the form refuses before sending
            page.fill('[data-ui=transpose-semitones]', '2')
            page.click('.vt-tab-transpose button[type=submit]')
            self.settled(page, "SCORE.view.score.patterns.verse.beats.find(b=>b.id===`beat-a`).notes[0].pitch===66")
            self.assertEqual(len(requests), 1)
            self.assertEqual({k: requests[0][k] for k in ('action', 'semitones', 'scope', 'all_tracks', 'apply_to_chords', 'try_keep_strings')},
                             dict(action='transpose', semitones=2, scope='track', all_tracks=True, apply_to_chords=True, try_keep_strings=True))
            notes = {n['id']: (n['pitch'], n['string'], n['fret']) for b in state.song['score']['patterns']['verse']['beats'] for n in b['notes']}
            self.assertEqual(notes, {'note-a': (66, 1, 2), 'note-b': (64, 2, 5)})   # strings kept, frets +2
            self.assertTrue(page.inner_text('.vt-tab-status').startswith('Transposed'))
            self.assertEqual(len(state.history), 1)
            page.click('[data-action=undo]')
            self.settled(page, "SCORE.view.score.patterns.verse.beats.find(b=>b.id===`beat-a`).notes[0].pitch===64")
            self.assertEqual((folder/'song.yaml').read_bytes(), before)

    def test_native_setup_tuning_change_retunes_keeping_pitch_or_frets(self):
        for keep, expected in (('pitch', (62, 5)), ('frets', (60, 3))):   # SONG: note-b D4 = string 2 (B3) fret 3
            with self.subTest(keep=keep), self.muted_page(SONG) as (page, state, folder):
                self.assertFalse(state.error, state.error)
                before = (folder/'song.yaml').read_bytes()
                self.open_tab(page)
                requests = []
                page.on('request', lambda r: requests.append(r.post_data_json)
                        if r.method == 'POST' and urlsplit(r.url).path in ('/api/score', '/api/score_command') else None)
                self.open_setup(page)
                page.fill('[data-ui=tuning]', '64, 57')   # string 2 down a tone
                page.select_option('[data-ui=retune-keep]', keep)
                page.locator('.vt-tab-setup button[type=submit]').first.click()
                self.settled(page, "SCORE.view.score.tracks.guitar.tuning[1]===57")
                self.assertEqual([(r.get('action'), r.get('keep')) for r in requests], [('retune', keep)])
                note = next(n for b in state.song['score']['patterns']['verse']['beats'] for n in b['notes'] if n['id'] == 'note-b')
                self.assertEqual((note['pitch'], note['fret']), expected)
                self.assertTrue(page.inner_text('.vt-tab-status').startswith('Retuned'))
                self.assertEqual(len(state.history), 1)
                page.click('[data-action=undo]')
                self.settled(page, "SCORE.view.score.tracks.guitar.tuning[1]===59")
                self.assertEqual((folder/'song.yaml').read_bytes(), before)

    def test_native_setup_note_name_tuning_presets_and_capo(self):
        with self.muted_page(SONG) as (page, state, folder):   # SONG: guitar E4 B3; note-a E4 open, note-b D4 = string 2 fret 3
            self.assertFalse(state.error, state.error)
            before = (folder/'song.yaml').read_bytes()
            self.open_tab(page)
            requests = []
            page.on('request', lambda r: requests.append(r.post_data_json)
                    if r.method == 'POST' and urlsplit(r.url).path in ('/api/score', '/api/score_command') else None)
            self.open_setup(page)
            self.assertEqual(page.input_value('[data-ui=tuning]'), 'E4 B3')
            page.select_option('[data-ui=tuning-preset]', label='Drop D')
            self.assertEqual(page.input_value('[data-ui=tuning]'), 'E4 B3 G3 D3 A2 D2')
            self.assertIn('6 strings', page.inner_text('.vt-tab-status'))
            self.assertEqual(requests, [])
            # Names in either case, with commas, sharps or flats: the same E4 B3; then a capo on the second fret.
            page.fill('[data-ui=tuning]', 'e4, Cb4')
            page.fill('[data-ui=capo]', '2')
            page.locator('.vt-tab-setup button[type=submit]').first.click()
            self.settled(page, "SCORE.view.score.tracks.guitar.capo===2")
            self.assertEqual([(r.get('action'), r.get('tuning'), r.get('capo')) for r in requests], [('retune', [64, 59], 2)])
            # TuxGuitar's offset, as on a real guitar: strings and frets stay, the sound rises by the capo.
            notes = {n['id']: (n['string'], n['fret'], n['pitch']) for b in state.song['score']['patterns']['verse']['beats'] for n in b['notes']}
            self.assertEqual(notes, {'note-a': (1, 0, 66), 'note-b': (2, 3, 64)})
            self.assertTrue(page.inner_text('.vt-tab-meter').startswith('Capo 2 · '))
            self.assertEqual(len(state.history), 1)
            page.click('[data-action=undo]')
            self.settled(page, "!SCORE.view.score.tracks.guitar.capo")
            self.assertFalse(page.inner_text('.vt-tab-meter').startswith('Capo'))
            self.assertEqual((folder/'song.yaml').read_bytes(), before)

    def test_native_capo_spinner_applies_without_apply_and_raises_cells_live_and_render(self):
        """The owner's fix2 retest: a capo set in Setup only took effect on Apply track, so closing the panel lost it."""
        import numpy as np
        from vulturetracker.notation import parse_cell

        def render_peak(page):
            page.wait_for_function("S.own && S.own.status==='ready' && S.own.key", timeout=30000)
            body = page.request.get(page.evaluate("new URL(tok(srcFor(null)),location.href).href")).body()
            with wave.open(io.BytesIO(body), 'rb') as w:
                rate, pcm = w.getframerate(), np.frombuffer(w.readframes(w.getnframes()), np.int16)
            mono = pcm.reshape(-1, w.getnchannels()).mean(axis=1)[int(0.55 * rate):int(0.9 * rate)]   # note-b
            spectrum = np.abs(np.fft.rfft(mono * np.hanning(len(mono)), 8 * len(mono)))
            return np.argmax(spectrum) * rate / (8 * len(mono))

        def live_pitches(page):
            plan = page.request.get(page.evaluate("new URL(tok('/api/playback?sample_rate=48000'),location.href).href")).json()['plan']
            return sorted(e['pitch'] for e in plan['events'] if e['type'] == 'note_on')

        with self.muted_page(SONG) as (page, state, folder):
            self.assertFalse(state.error, state.error)
            before = (folder/'song.yaml').read_bytes()
            self.open_tab(page)
            cell = lambda: parse_cell(state.pattern_rows(0, 'occ-verse')['display_rows'][0][0]).note
            cells0, live0, peak0 = cell(), live_pitches(page), render_peak(page)
            key0 = page.evaluate('S.own.key')
            # The live engine loaded (not playing), every error text it shows recorded: back-to-back retunes can get the
            # server's "inputs changed, retry" for a superseded load, which must not show.
            page.evaluate("""async () => {await lvStart(); let shown = null; window.liveErrors = [];
                Object.defineProperty(LV, 'err', {get: () => shown, set: v => { shown = v; if (v) window.liveErrors.push(v); }})}""")
            self.open_setup(page)
            page.locator('[data-ui=capo]').focus()   # a click can land on the spinner and step it too
            page.keyboard.press('ArrowUp')
            page.keyboard.press('ArrowUp')
            page.keyboard.press('Escape')   # closes Setup without Apply track
            self.settled(page, "SCORE.view.score.tracks.guitar.capo===2")
            self.assertEqual(api.from_yaml((folder/'song.yaml').read_text())['score']['tracks']['guitar']['capo'], 2)
            self.assertEqual(len(state.history), 2)   # each spinner step is its own retune and Undo
            self.assertEqual(cell(), cells0 + 2)   # Pattern view
            self.assertEqual(live_pitches(page), [p + 2 for p in live0])   # what the live engine is fed
            page.wait_for_function(f"S.own && S.own.key && S.own.key!=={key0!r}", timeout=30000)
            self.assertAlmostEqual(render_peak(page) / peak0, 2 ** (2 / 12), delta=0.01)   # the offline render
            self.assertTrue(page.inner_text('.vt-tab-meter').startswith('Capo 2 · '))
            page.wait_for_function('LV.key === lvKey() && !LV.err', timeout=15000)
            # The server's retry answer for a superseded load, forced once: nothing shows, and the load is retried.
            page.evaluate("""() => {const real = window.fetch; window.playbackFetches = 0; LV.key = 'stale';
                window.fetch = (url, ...rest) => {
                    if (String(url).includes('/api/playback') && window.playbackFetches++ === 0)
                        return Promise.resolve(new Response(JSON.stringify({error: 'Playback inputs changed during preparation; retry with the current song and mix'}), {status: 400}));
                    return real(url, ...rest);
                };
                lvLoad(true);}""")
            page.wait_for_function('window.playbackFetches >= 2 && LV.key === lvKey()', timeout=15000)
            self.assertEqual(page.evaluate('window.liveErrors'), [])
            page.click('[data-action=undo]')
            self.settled(page, "SCORE.view.score.tracks.guitar.capo===1")
            page.click('[data-action=undo]')
            self.settled(page, "!SCORE.view.score.tracks.guitar.capo")
            self.assertEqual((folder/'song.yaml').read_bytes(), before)
            # Typed digits settle into one change: "12" is one retune, not 1 then 12; no Apply, Setup closed at once.
            self.open_setup(page)
            page.fill('[data-ui=capo]', '')
            page.locator('[data-ui=capo]').press_sequentially('12')
            page.keyboard.press('Escape')
            self.settled(page, "SCORE.view.score.tracks.guitar.capo===12")
            self.assertEqual(len(state.history), 1)

    def test_native_measure_menu_add_remove_clean_copy_paste_with_exact_undo(self):
        from tests.test_tablature_sync import repeat_song
        source = repeat_song()
        source['samples'][1]['file'] = 'a.wav'
        with self.muted_page(api.to_yaml(source)) as (page, state, folder):
            self.assertFalse(state.error, state.error)
            before = (folder/'song.yaml').read_bytes()
            page.evaluate("tab('tab');setEdit(true)")
            page.wait_for_selector('[data-ui=track]', state='attached')
            self.settled(page, 'SCORE.view?.native')
            # TuxGuitar's measure errors: each bar holds one quarter note, so each voice ends early.
            page.wait_for_function("document.querySelector('.vt-tab-meter').textContent.startsWith('3 measure errors · ')")
            self.assertIn('Bar 1, voice 1: ends early', page.get_attribute('.vt-tab-meter', 'title'))
            self.open_panel(page, 'measures')
            self.assertEqual(page.input_value('[data-ui=ops-from]'), '1')
            self.assertTrue(page.is_disabled('[data-action=measure-paste]'))
            orders = lambda: [str(o) for o in state.song['orders']]

            def undo(expected_orders):
                page.click('[data-action=undo]')
                self.settled(page, f"SCORE.view.orders.length==={len(expected_orders)}")
                self.assertEqual((folder/'song.yaml').read_bytes(), before)

            def run(action, condition):
                page.click(f'[data-action={action}]')
                self.settled(page, condition)

            page.fill('[data-ui=ops-from]', '2'); page.fill('[data-ui=ops-to]', '2'); page.fill('[data-ui=ops-count]', '2')
            run('measure-add-before', 'SCORE.view.orders.length===5')
            self.assertEqual(orders(), ['a', 'bar1', 'bar2', 'b', 'c'])
            self.assertTrue(page.inner_text('.vt-tab-status').startswith('Added 2 measures at 2'))
            undo(['a', 'b', 'c'])
            page.fill('[data-ui=ops-from]', '2'); page.fill('[data-ui=ops-to]', '2')
            run('measure-remove', 'SCORE.view.orders.length===2')
            self.assertEqual(orders(), ['a', 'c'])
            undo(['a', 'b', 'c'])
            page.fill('[data-ui=ops-from]', '1'); page.fill('[data-ui=ops-to]', '1'); page.fill('[data-ui=ops-count]', '1')
            page.click('[data-action=measure-copy]')
            page.wait_for_function("document.querySelector('.vt-tab-status').textContent==='Copied measure 1 (guitar).'")
            page.fill('[data-ui=ops-from]', '3')
            run('measure-paste', "SCORE.view.score.patterns.c.beats[0].notes[0].pitch===64")
            self.assertEqual(orders(), ['a', 'b', 'c'])
            page.click('[data-action=undo]')
            self.settled(page, "SCORE.view.score.patterns.c.beats[0].notes[0].pitch===67")
            self.assertEqual((folder/'song.yaml').read_bytes(), before)
            page.fill('[data-ui=ops-from]', '3')
            run('measure-paste-insert', 'SCORE.view.orders.length===4')
            self.assertEqual(orders(), ['a', 'b', 'bar1', 'c'])
            undo(['a', 'b', 'c'])
            page.fill('[data-ui=ops-from]', '2'); page.fill('[data-ui=ops-to]', '3')
            run('measure-clean', '!SCORE.view.score.patterns.b.beats.length && !SCORE.view.score.patterns.c.beats.length')
            self.assertEqual(len(state.history), 1)
            undo(['a', 'b', 'c'])
            # TuxGuitar's time signature: 3/4 on measure 3 resizes its pattern; one Undo restores the bytes.
            page.evaluate('async i=>{setCursor(i,0);await scoreRefresh()}', 2)
            self.open_panel(page, 'measures')
            page.select_option('[data-ui=measure]', 'c')
            page.fill('[data-ui=meter-n]', '3')
            page.click('.vt-tab-measures button[type=submit]')
            self.settled(page, 'SCORE.view.score.measures[2].meter[0]===3')
            self.assertEqual(state.song['patterns']['c']['rows'], 36)
            self.assertEqual(len(state.history), 1)
            undo(['a', 'b', 'c'])
            # The tempo's beat unit (TuxGuitar's tempo base) is notation: 83 quarters per minute (T53) is 166 eighths.
            page.evaluate('async i=>{setCursor(i,0);await scoreRefresh()}', 2)
            self.open_panel(page, 'measures')
            page.select_option('[data-ui=measure]', 'c')
            page.select_option('[data-ui=tempo-unit]', '4.')
            page.click('.vt-tab-measures button[type=submit]')
            self.assertEqual(page.inner_text('.vt-tab-status'), '83 quarter notes per minute has no exact dotted quarter value.')
            page.select_option('[data-ui=tempo-unit]', '8')
            page.click('.vt-tab-measures button[type=submit]')
            self.settled(page, 'SCORE.view.score.measures[2].tempo_unit?.value===166')
            self.assertEqual(state.song['score']['measures'][2]['tempo_unit'], dict(base=8, dotted=False, value=166))
            self.assertIn('written 166 eighths per minute', page.inner_text('[data-ui=tempo-effective]'))
            undo(['a', 'b', 'c'])
            page.fill('[data-ui=ops-from]', '1'); page.fill('[data-ui=ops-to]', '3')
            page.click('[data-action=measure-remove]')
            self.settled(page, "document.querySelector('.vt-tab-status').textContent.includes('keep at least one')")
            self.assertEqual((folder/'song.yaml').read_bytes(), before)

    def test_native_tuxguitar_default_keys(self):
        import copy
        source = self.fit_song()
        # Independent written bars avoid unrelated occurrence-dependent IT release differences.
        for i in (2,3):
            name=f'verse{i}';source['orders'][i-1]=name
            source['patterns'][name]=copy.deepcopy(source['patterns']['verse'])
            source['score']['patterns'][name]=copy.deepcopy(source['score']['patterns']['verse'])
        source['score']['measures'] = [dict(id=f'm{i}', meter=[4,4], marker=dict(title=t, color='#123456'),
                                            **{'from': dict(occurrence=o, at=[0,1])}, to=dict(occurrence=o, at=[4,1]))
                                       for i, (o, t) in enumerate((('pass-1','A'), ('pass-3','C')))]
        for b in source['score']['patterns']['verse']['beats']:
            for n in b['notes']:
                n['velocity'] = 95   # a hammer-on needs explicit velocities
        with self.muted_page(api.to_yaml(source)) as (page,state,folder):
            self.assertFalse(state.error,state.error)
            before = (folder/'song.yaml').read_bytes()
            page.evaluate("tab('tab');setEdit(true)")
            page.wait_for_selector('.vt-tab-grid [data-note="a-note"]')
            requests = []
            page.on('request', lambda r: requests.append(r.post_data_json)
                    if r.method=='POST' and urlsplit(r.url).path in ('/api/score','/api/score_command') else None)
            beat = lambda: next(b for b in state.song['score']['patterns']['verse']['beats'] if b['id'] == 'a')

            def press(key, condition):
                page.click('.vt-tab-grid [data-note="a-note"]')
                page.locator('#tab-editor').focus()
                page.keyboard.press(key)
                self.settled(page, condition)

            def undo_all():
                while page.evaluate('S.undo'):
                    page.click('[data-action=undo]')
                    self.settled(page, 'true')
                self.assertEqual((folder/'song.yaml').read_bytes(), before)

            for key, flag in (('x','dead'), ('o','ghost'), ('h','hammer'), ('p','palm_mute'), ('s','slide'), ('v','vibrato'), ('f','fade_in')):
                with self.subTest(key=key):
                    press(key, f"SCORE.view.score.patterns.verse.beats.find(b=>b.id===`a`).notes[0].{flag}")
                    self.assertTrue(beat()['notes'][0].get(flag))
                    undo_all()
            # / makes the quarter a triplet; * then dots it, which is exactly one quarter again (no overlap).
            press('/', "SCORE.view.score.patterns.verse.beats.find(b=>b.id===`a`).written.tuplet?.[0]===3")
            press('*', "SCORE.view.score.patterns.verse.beats.find(b=>b.id===`a`).written.dots===1")
            self.assertEqual(beat()['written'], {'value': 4, 'dots': 1, 'tuplet': [3, 2]})
            undo_all()
            requests.clear()
            page.click('.vt-tab-grid [data-note="a-note"]')
            page.locator('#tab-editor').focus()
            page.keyboard.press('Control+a')
            self.assertTrue(page.inner_text('.vt-tab-status').startswith('Selected 12 beats'))
            # Select All spans every written occurrence; this shortcut check edits a local range.
            self.capture_engraving(page);page.select_option('[data-ui=track]','guitar')
            self.settled(page,'window.tabRendered&&tabRenderApi.boundsLookup?.isFinished')
            start,end=(self.tab_lane_point(page,0,i,1) for i in (0,3))
            page.mouse.move(start['x'],start['y']);page.mouse.down();page.mouse.move(end['x'],end['y'],steps=5);page.mouse.up()
            page.locator('#tab-editor').focus()
            page.keyboard.press('-')
            self.settled(page, "SCORE.view.score.patterns.verse.beats.filter(b=>b.notes.length).every(b=>b.written.value===8)")
            self.assertEqual(next(b for b in state.song['score']['patterns']['verse']['beats'] if b['id']=='r')['written']['value'],4)
            self.assertEqual([(r['action'], sorted(r['beats'])) for r in requests], [('set_duration', ['a','b','c','r'])])
            undo_all()
            page.click('.vt-tab-grid [data-note="a-note"]')
            page.locator('#tab-editor').focus()
            page.keyboard.press('Control+2')
            self.assertEqual(page.input_value('[data-ui=voice]'), '1')
            page.keyboard.press('Control+1')
            self.assertEqual(page.input_value('[data-ui=voice]'), '0')
            press('Control+Delete', "!SCORE.view.score.patterns.verse.beats.find(b=>b.id===`a`).notes.length")
            undo_all()
            page.click('.vt-tab-grid [data-note="a-note"]')
            page.locator('#tab-editor').focus()
            page.keyboard.press('Alt+ArrowRight')
            page.wait_for_function('SCORE.view.order===2')
            page.keyboard.press('Alt+Shift+ArrowLeft')
            page.wait_for_function('SCORE.view.order===0')
            self.assertEqual((folder/'song.yaml').read_bytes(), before)

    def test_native_clean_beat_button_rests_both_voices_in_one_step(self):
        from tests.test_tablature import beat, note
        source = self.fit_song()
        beats = source['score']['patterns']['verse']['beats']
        next(b for b in beats if b['id'] == 'a')['text'] = 'clean me'
        beats.append(beat('v1', [0,1], [note('v1-note', 59, 2, 0)], voice=1))
        with self.muted_page(api.to_yaml(source)) as (page,state,folder):
            self.assertFalse(state.error,state.error)
            before = (folder/'song.yaml').read_bytes()
            page.evaluate("tab('tab');setEdit(true)")
            page.wait_for_selector('.vt-tab-grid [data-note="a-note"]')
            page.click('.vt-tab-grid [data-note="a-note"]')
            with page.expect_response('**/api/score_command') as response:
                page.click('[data-action=clean-beat]')
            self.assertEqual(sorted(response.value.json()['cleaned']), ['a','v1'])
            self.settled(page, "SCORE.view.score.patterns.verse.beats.filter(b=>['a','v1'].includes(b.id)&&!b.notes.length&&!b.text).length===2")
            self.assertEqual(page.inner_text('.vt-tab-status'), 'Cleaned 2 beats.')
            after = {b['id']:b for b in state.song['score']['patterns']['verse']['beats']}
            self.assertEqual([after[i]['notes'] for i in ('a','v1')], [[],[]])
            self.assertEqual(len(after['b']['notes']), 1)
            self.assertEqual(len(state.history), 1)
            page.click('[data-action=undo]')
            self.settled(page, "SCORE.view.score.patterns.verse.beats.find(b=>b.id===`a`).notes.length===1")
            self.assertEqual((folder/'song.yaml').read_bytes(), before)

    def test_native_duration_keys_apply_to_the_selected_beat_range_in_one_step(self):
        with self.muted_page(api.to_yaml(self.fit_song())) as (page,state,folder):
            self.assertFalse(state.error,state.error)
            before = (folder/'song.yaml').read_bytes()
            original = {b['id']:b for b in json.loads(json.dumps(state.song['score']['patterns']['verse']['beats']))}
            page.evaluate("tab('tab');setEdit(true)")
            page.wait_for_selector('.vt-tab-grid [data-note="b-note"]')
            requests = []
            page.on('request', lambda r: requests.append(r.post_data_json)
                    if r.method=='POST' and urlsplit(r.url).path in ('/api/score','/api/score_command') else None)
            page.click('.vt-tab-grid [data-note="a-note"]')
            page.click('.vt-tab-grid [data-note="b-note"]', modifiers=['Control'])
            page.locator('#tab-editor').focus()
            page.keyboard.press('-')
            self.settled(page, "SCORE.view.score.patterns.verse.beats.filter(b=>['a','b'].includes(b.id)&&b.written.value===8).length===2")
            self.assertEqual([(r['action'], r['beats'], r['written']['value']) for r in requests], [('set_duration', ['a','b'], 8)])
            self.assertNotIn('fit', requests[0])
            self.assertEqual(page.inner_text('.vt-tab-status'), 'Selected rhythm updated; one Undo restores it.')
            after = {b['id']:b for b in state.song['score']['patterns']['verse']['beats']}
            self.assertEqual([after[i]['at'] for i in ('a','b')], [original[i]['at'] for i in ('a','b')])
            self.assertEqual(after['c'], original['c'])
            self.assertEqual(len(state.history), 1)
            page.click('[data-action=undo]')
            self.settled(page, "SCORE.view.score.patterns.verse.beats.find(b=>b.id==='a').written.value===4")
            self.assertEqual((folder/'song.yaml').read_bytes(), before)
            # Strict + keeps blocked a and grows b into the available rest, in one Undo.
            requests.clear()
            page.click('.vt-tab-grid [data-note="a-note"]')
            page.click('.vt-tab-grid [data-note="b-note"]', modifiers=['Control'])
            page.locator('#tab-editor').focus()
            page.keyboard.press('+')
            self.settled(page, "SCORE.view.score.patterns.verse.beats.find(b=>b.id==='b').written.value===2")
            self.assertEqual([r['action'] for r in requests], ['set_duration'])
            after = {b['id']:b for b in state.song['score']['patterns']['verse']['beats']}
            self.assertEqual(after['a'], original['a'])
            self.assertEqual(after['c'], original['c'])
            self.assertNotIn('r', after)
            self.assertEqual(len(state.history), 1)
            page.click('[data-action=undo]')
            self.settled(page, "SCORE.view.score.patterns.verse.beats.find(b=>b.id==='b').written.value===4")
            self.assertEqual((folder/'song.yaml').read_bytes(), before)
            self.assertEqual(len(state.history), 0)

    def test_native_fit_duration_reuses_peer_only_destination(self):
        from tests.test_tablature import TestPlacePeerFitCommand
        source = self.fit_song()
        model, _, length = TestPlacePeerFitCommand().fixture()
        self.assertEqual(length, Fraction(3,2))
        source['score']['patterns']['verse']['beats'] = model['score']['patterns']['A']['beats']
        with self.muted_page(api.to_yaml(source), compact=True) as (page,state,folder):
            self.assertFalse(state.error,state.error)
            before = (folder/'song.yaml').read_bytes()
            original = {b['id']:b for b in json.loads(json.dumps(state.song['score']['patterns']['verse']['beats']))}
            page.evaluate("tab('tab')")
            page.wait_for_selector('[data-ui=fit]')
            page.locator('.vt-tab-inspector > summary').click()
            page.evaluate("SCORE.editor.setSelection({order:0,pattern:'verse',track:'guitar',voice:0,at:[0,1],string:1})")
            page.click('[data-action=go]')
            page.set_checked('[data-ui=fit]',True)
            page.select_option('[data-ui=duration]','4')
            page.select_option('[data-ui=dots]','1')
            with page.expect_response('**/api/score_command') as response:
                page.click('[data-action=duration]')
            result = response.value.json()
            self.settled(page,"!document.querySelector('[data-ui=fit]').disabled")
            self.assertEqual(result['outcomes'],['shifted'],result)
            self.assertEqual(page.inner_text('.vt-tab-status'),'Selected rhythm updated; one Undo restores it. Fit moved or resized following beats.')
            after = {b['id']:b for b in state.song['score']['patterns']['verse']['beats']}
            self.assertEqual(set(after), set(original)-{'r'})
            for identity in ('prefix','peer','suffix'):
                self.assertEqual(after[identity],original[identity])
            self.assertEqual((after['b']['at'],after['c']['at']),([3,2],[5,2]))
            self.assertEqual(len(state.history),1)
            page.click('[data-action=undo]')
            self.settled(page,"SCORE.view.score.patterns.verse.beats.some(b=>b.id==='r')")
            self.assertEqual((folder/'song.yaml').read_bytes(),before)

    def test_native_fit_insertion_capture_navigation_and_protected_refusal(self):
        from tests.test_tablature import beat, note
        for case in ('shifted','old_duration','partial','protected'):
            source = self.fit_song(case=='old_duration')
            if case=='protected':
                source['score']['patterns']['verse']['beats'].append(
                    beat('peer',[1,1],[note('peer-note',59,2,0)],voice=1))
            with self.subTest(case=case), self.muted_page(api.to_yaml(source),compact=True) as (page,state,folder):
                self.assertFalse(state.error,state.error)
                before = (folder/'song.yaml').read_bytes()
                page.evaluate("tab('tab')")
                page.wait_for_selector('[data-ui=fit]')
                page.locator('.vt-tab-inspector > summary').click()
                page.evaluate("SCORE.editor.setSelection({order:0,pattern:'verse',track:'guitar',voice:0,at:[0,1],string:1})")
                page.click('[data-action=go]')
                page.check('[data-ui=fit]')
                page.select_option('[data-ui=duration]','1' if case=='old_duration' else '2' if case=='shifted' else '4')
                if case in ('partial','protected'):
                    page.select_option('[data-ui=dots]','1')  # Partial movement involving a peer voice refuses.
                with page.expect_response('**/api/score_command') as response:
                    # Capture before dispatch; even a programmatic later change cannot rebase it.
                    self.assertTrue(page.evaluate("""() => {
                        void SCORE.editor.enterPitch(59);
                        const fit=document.querySelector('[data-ui=fit]'), disabled=fit.disabled;
                        fit.checked=false;return disabled;
                    }"""))
                result = response.value.json()
                self.settled(page,"!document.querySelector('[data-ui=fit]').disabled")
                self.assertEqual(response.value.request.post_data_json['fit'],'tg_insert')
                if case=='protected':
                    self.assertIn('overlapping notes require independent channels',result['error'])
                    self.assertEqual((folder/'song.yaml').read_bytes(),before)
                    self.assertEqual(len(state.history),0)
                    continue
                self.assertEqual(result['fit']['outcome'],'shifted' if case=='partial' else case)
                actual = next(b for b in state.song['score']['patterns']['verse']['beats'] if b['id']=='a')
                added = actual['notes'][-1]
                self.assertEqual([n['pitch'] for n in actual['notes']],[64,59])
                self.assertEqual(page.evaluate('[CUR.score.at,CUR.score.beat,CUR.score.note]'),[[0,1],'a',added['id']])
                self.assertEqual(page.input_value('[data-ui=duration]'),'2' if case=='shifted' else '4')
                self.assertEqual(page.input_value('[data-ui=dots]'),'1' if case=='partial' else '0')
                if case=='partial':
                    from vulturetracker.tablature import duration_quarters
                    following = next(b for b in state.song['score']['patterns']['verse']['beats'] if b['id']=='b')
                    self.assertEqual((following['at'],duration_quarters(following['written'])),([3,2],Fraction(3,2)))
                self.assertEqual(page.inner_text('.vt-tab-status'),'Note added at the previous duration.' if case=='old_duration'
                                 else 'Duration applied; following notes moved or resized.')
                self.assertEqual(len(state.history),1)
                page.click('[data-action=undo]')
                self.settled(page,"SCORE.view.score.patterns.verse.beats.find(b=>b.id==='a').notes.length===1")
                self.assertEqual((folder/'song.yaml').read_bytes(),before)
                if case=='shifted':
                    # A submitted fit may finish after the user changes occurrence.
                    def navigate(route):
                        page.evaluate('setCursor(2,0,0,0)')
                        route.continue_()
                    page.route('**/api/score_command',navigate)
                    page.check('[data-ui=fit]')
                    page.select_option('[data-ui=duration]','2')
                    page.evaluate('void SCORE.editor.enterPitch(59)')
                    self.settled(page,"SCORE.view.order===2 && SCORE.view.score.patterns.verse.beats.find(b=>b.id==='a').notes.length===2")
                    self.assertEqual(page.evaluate('[CUR.o,CUR.row]'),[2,0])
                    self.assertEqual(page.input_value('[data-ui=at]'),'0')
                    page.unroute('**/api/score_command')

    def test_piano_cross_voice_onset_and_tie_refusal(self):
        source = self.piano_song()
        beats = source['score']['patterns']['verse']['beats']
        beats[0]['written'] = dict(value=4)  # Voice 0 covers the explicit onset in voice 1.
        beats[1]['at'] = [3,2]
        with self.muted_page(api.to_yaml(source), compact=True) as (page, state, folder):
            self.assertFalse(state.error, state.error)
            before = (folder / 'song.yaml').read_bytes()
            page.evaluate("tab('tab')")
            page.wait_for_selector('.vt-piano')
            page.evaluate("""SCORE.editor.setSelection({order:0,pattern:'verse',track:'guitar',voice:0,at:[3,2],string:1});
                SCORE.editor.enterPitch(66)""")
            self.settled(page, "SCORE.view.score.patterns.verse.beats[1].notes.length===0")
            self.assertEqual(state.song['score']['patterns']['verse']['beats'][0]['notes'][0]['id'], 'n0')
            page.click('[data-action=undo]')
            self.settled(page, "SCORE.view.score.patterns.verse.beats[1].notes.length===1")
            self.assertEqual((folder / 'song.yaml').read_bytes(), before)
        with self.muted_page(NATIVE_SONG, compact=True) as (page, state, folder):
            before = (folder / 'song.yaml').read_bytes()
            page.evaluate("tab('tab')")
            page.wait_for_selector('.vt-piano')
            page.evaluate("""SCORE.editor.setSelection({order:0,pattern:'verse',track:'guitar',voice:0,at:[48,13],string:1});
                SCORE.editor.enterPitch(64)""")
            page.wait_for_function("document.querySelector('.vt-tab-status').textContent.includes('cannot delete a tied')")
            self.assertEqual((folder / 'song.yaml').read_bytes(), before)
            self.assertEqual(len(state.history), 0)
            page.select_option('[data-ui=duration]','16')
            page.click('[data-action=duration]')
            self.settled(page, "document.querySelector('.vt-tab-status').textContent.includes('not representable on row_step')")
            self.assertEqual((folder / 'song.yaml').read_bytes(), before)
            self.assertEqual(len(state.history), 0)

    def test_piano_percussion_lanes_and_raw_boundary(self):
        source = api.from_yaml(NATIVE_RAW_SONG)
        source['module']['channels'] += [dict(name='Drum 1'), dict(name='Drum 2')]
        source['score']['tracks']['drums'] = dict(tuning=[0,0], channels=[2,3], instrument=1, midi=dict(bank=128,program=0))
        with self.muted_page(api.to_yaml(source), compact=True) as (page, state, folder):
            self.assertFalse(state.error, state.error)
            before = (folder / 'song.yaml').read_bytes()
            page.evaluate("tab('tab')")
            page.wait_for_selector('.vt-piano')
            page.locator('.vt-piano > summary').click()
            page.evaluate("SCORE.editor.setSelection({order:0,pattern:'verse',row:0,ch:1})")
            page.evaluate("SCORE.editor.enterPitch(64)")
            self.assertIn('Adopt this Pattern note', page.locator('.vt-tab-status').inner_text())
            # Cached playback highlights cannot carry a guitar pitch into the drum panel.
            markers = page.evaluate("""() => {
                LV.playing=true; SCORE.editor.setPlayhead({order:0,o:0,at:[4,13],occurrence:'pass-1'});
                const before=document.querySelector('[data-piano-pitch="64"]').getAttribute('aria-pressed');
                const track=document.querySelector('[data-ui=track]'); track.value='drums'; track.dispatchEvent(new Event('change',{bubbles:true}));
                const after=document.querySelector('[data-piano-pitch="64"]').getAttribute('aria-pressed');
                LV.playing=false; SCORE.editor.setPlayhead(null); return [before,after];
            }""")
            self.assertEqual(markers, ['true','false'])
            page.evaluate("SCORE.editor.setSelection({order:0,pattern:'verse',track:'drums',voice:1,at:[0,1],string:1})")
            self.assertEqual(page.locator('[data-piano-pitch]').count(), 100)
            self.assertEqual(page.locator('[data-piano-pitch="1"]').get_attribute('aria-label'), 'Drum key 1')
            for n in [0,101]:
                page.evaluate('n=>SCORE.editor.enterPitch(n)', n)
                self.assertIn('1 to 100', page.locator('.vt-tab-status').inner_text())
            page.locator('[data-piano-pitch="1"]').click()
            self.settled(page, "SCORE.view.score.patterns.verse.beats.some(b=>b.track==='drums')")
            page.locator('[data-piano-pitch="100"]').click()
            self.settled(page, "SCORE.view.score.patterns.verse.beats.find(b=>b.track==='drums').notes.length===2")
            b = next(b for b in state.song['score']['patterns']['verse']['beats'] if b['track'] == 'drums')
            self.assertEqual(b['voice'], 1)
            self.assertEqual([(n['pitch'],n['string'],n['fret']) for n in b['notes']], [(1,1,1),(100,2,100)])
            page.evaluate("SCORE.editor.enterPitch(38)")
            self.assertIn('No unused', page.locator('.vt-tab-status').inner_text())
            page.evaluate("SCORE.editor.setSelection({order:0,pattern:'verse',track:'drums',voice:0,at:[0,1],string:1})")
            page.locator('[data-piano-pitch="100"]').click()
            self.settled(page, "SCORE.view.score.patterns.verse.beats.find(b=>b.track==='drums').notes.length===1")
            for condition in ["SCORE.view.score.patterns.verse.beats.find(b=>b.track==='drums').notes.length===2",
                              "SCORE.view.score.patterns.verse.beats.find(b=>b.track==='drums').notes.length===1",
                              "!SCORE.view.score.patterns.verse.beats.some(b=>b.track==='drums')"]:
                page.click('[data-action=undo]')
                self.settled(page, condition)
            self.assertEqual((folder / 'song.yaml').read_bytes(), before)

    def test_fretboard_capo_scales_both_voice_toggle_history_and_guards(self):
        source = api.from_yaml(NATIVE_SONG)
        source['module']['channels'] = [dict(name='High'), dict(name='Reentrant')]
        score = source['score']
        score['tracks']['guitar'].update(tuning=[64,67], channels=[0,1], capo=2, max_fret=29)
        score['ties'] = []
        score['patterns']['verse']['beats'] = [
            dict(id=f'voice-{v}', track='guitar', voice=v, at=[4,13],
                 written=dict(value=8, tuplet=[13,8]),
                 notes=[dict(id=f'n{v}', pitch=66, string=1, fret=0, velocity=0, staccato=True)])
            for v in range(2)]
        with self.muted_page(api.to_yaml(source), compact=True) as (page, state, folder):
            self.assertFalse(state.error, state.error)
            before = (folder / 'song.yaml').read_bytes()
            plan = json.loads(json.dumps(state.mod.native_score['plan']))
            errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.evaluate("tab('tab')")
            page.wait_for_selector('.vt-tab-edit-caret:not([hidden])')
            self.assertFalse(page.locator('.vt-fretboard').evaluate('e=>e.open'))
            page.locator('.vt-fretboard > summary').click()
            cell = lambda s, f: page.locator(f'[data-fb-string="{s}"][data-fb-fret="{f}"]')
            page.wait_for_selector('[data-fb-string="1"][data-fb-fret="0"]')
            self.assertEqual(cell(1, 29).get_attribute('data-pitch'), '95')
            self.assertEqual(cell(2, 0).get_attribute('data-pitch'), '69')
            self.assertEqual(page.locator('[data-fb=scale] option').count(), 276)
            self.assertEqual(page.locator('[data-fb=root] option').count(), 17)
            page.select_option('[data-fb=scale]', '0')
            page.select_option('[data-fb=root]', 'D')
            self.assertEqual(cell(1, 0).get_attribute('data-scale'), 'true')  # F# with capo, not unshifted E.
            self.assertEqual(cell(1, 1).get_attribute('data-scale'), 'true')
            self.assertEqual(cell(1, 2).get_attribute('data-scale'), 'false')
            right = cell(1, 0).bounding_box()['x'] < cell(1, 1).bounding_box()['x']
            self.assertTrue(right)
            page.select_option('[data-fb=direction]', 'left')
            self.assertGreater(cell(1, 0).bounding_box()['x'], cell(1, 1).bounding_box()['x'])
            self.assertLess(cell(1, 0).bounding_box()['y'], cell(2, 0).bounding_box()['y'])
            page.locator('.vt-fretboard-settings > summary').click()
            page.check('[data-fb=noteText]')
            page.fill('[data-fb=font]', 'serif')
            page.locator('[data-fb=font]').press('Tab')
            page.fill('[data-fb=size]', '16')
            page.locator('[data-fb=size]').press('Tab')
            self.assertEqual((folder / 'song.yaml').read_bytes(), before)
            self.assertEqual(len(state.history), 0)
            page.evaluate("""SCORE.editor.setSelection({order:0,pattern:'verse',occurrence:'pass-1',
                track:'guitar',voice:1,at:[4,13],string:1})""")
            self.assertEqual(cell(1, 0).get_attribute('data-voices'), '0,1')
            # Explicit source-order target wins even when the other voice is active.
            cell(1, 0).click()
            self.settled(page, "SCORE.view.score.patterns.verse.beats[0].notes.length===0")
            self.assertEqual(state.song['score']['patterns']['verse']['beats'][1]['notes'][0]['id'], 'n1')
            page.click('[data-action=undo]')
            self.settled(page, "SCORE.view.score.patterns.verse.beats[0].notes.length===1")
            self.assertEqual((folder / 'song.yaml').read_bytes(), before)
            # A different fret replaces the active string note while retaining its identity/techniques.
            cell(1, 1).click()
            self.settled(page, "SCORE.view.score.patterns.verse.beats[0].notes[0]?.fret===1")
            note = state.song['score']['patterns']['verse']['beats'][0]['notes'][0]
            self.assertEqual((note['id'], note['pitch'], note['velocity'], note['staccato']), ('n0',67,0,True))
            page.evaluate("window.fbPreview=[];lvNoteOn=(...a)=>fbPreview.push(a);lvNoteOff=()=>{}")
            page.select_option('[data-fb=mode]', 'audition')
            snapshot = (folder / 'song.yaml').read_bytes()
            cell(1, 1).click()
            self.assertEqual(page.evaluate('fbPreview[0].slice(2)'), [67,0])
            self.assertEqual((folder / 'song.yaml').read_bytes(), snapshot)
            # Keyboard hit testing follows left-handed columns and never leaks into TAB fret entry.
            cell(1, 1).focus()
            page.keyboard.press('ArrowLeft')
            self.assertEqual(page.evaluate('document.activeElement.dataset.fbFret'), '2')
            page.keyboard.press('Enter')
            self.assertEqual(page.evaluate('fbPreview.at(-1).slice(2)'), [68,0])
            page.select_option('[data-fb=mode]', 'edit')
            # TAB's editable capability is independent of Pattern's EDIT recording mode.
            page.evaluate("SCORE.editor.update({...SCORE.view,editable:false})")
            self.assertEqual(cell(2, 2).get_attribute('aria-disabled'), 'true')
            cell(2, 2).click(force=True)  # Exercise the handler guard as well as disabled semantics.
            self.assertIn('Enable editing', page.locator('.vt-tab-status').inner_text())
            self.assertEqual((folder / 'song.yaml').read_bytes(), snapshot)
            page.evaluate("SCORE.editor.update(SCORE.view)")
            # Hold the host's playing flag without starting its audio engine.
            page.evaluate("LV.playing=true;SCORE.editor.setPlayhead({order:0,o:0,at:[4,13],occurrence:'pass-1'})")
            cell(2, 2).click(force=True)
            self.assertIn('Stop playback', page.locator('.vt-tab-status').inner_text())
            self.assertEqual((folder / 'song.yaml').read_bytes(), snapshot)
            page.evaluate("LV.playing=false;SCORE.editor.setPlayhead(null)")
            # A queued click cannot mutate the old target after a same-pattern caret move.
            page.evaluate("""() => {
                document.querySelector('[data-fb-string="2"][data-fb-fret="3"]')
                    .dispatchEvent(new MouseEvent('click',{bubbles:true}));
                SCORE.editor.setSelection({order:0,pattern:'verse',track:'guitar',voice:1,at:[0,1],string:1});
            }""")
            page.wait_for_function("document.querySelector('.vt-tab-status').textContent.includes('selection changed')")
            self.assertEqual((folder / 'song.yaml').read_bytes(), snapshot)
            page.click('[data-action=undo]')
            self.settled(page, "SCORE.view.score.patterns.verse.beats[0].notes[0]?.fret===0")
            self.assertEqual((folder / 'song.yaml').read_bytes(), before)
            self.assertEqual(state.mod.native_score['plan'], plan)
            # Insert on an empty exact onset in the repeated occurrence.
            page.evaluate("setCursor(2,0,0,0)")
            self.settled(page, "SCORE.view.order===2")
            page.evaluate("""SCORE.editor.setSelection({order:2,pattern:'verse',occurrence:'pass-3',
                track:'guitar',voice:1,at:[8,13],string:2})""")
            cell(2, 29).click()
            self.settled(page, "SCORE.view.score.patterns.verse.beats.some(b=>b.voice===1&&b.at[0]===8&&b.at[1]===13&&b.notes.some(n=>n.pitch===98))")
            page.click('[data-action=undo]')
            self.settled(page, "SCORE.view.score.patterns.verse.beats.length===2")
            self.assertEqual((folder / 'song.yaml').read_bytes(), before)
            page.reload()
            page.wait_for_function('S && S.song')
            page.evaluate("tab('tab')")
            page.wait_for_selector('[data-fb-string="1"][data-fb-fret="0"]')
            self.assertEqual(page.input_value('[data-fb=root]'), 'D')
            self.assertEqual(page.input_value('[data-fb=direction]'), 'left')
            self.assertEqual(page.input_value('[data-fb=font]'), 'serif')
            self.assertTrue(page.is_checked('[data-fb=noteText]'))
            page.locator('.vt-fretboard-settings > summary').click()
            page.click('[data-fb=reset]')
            self.assertEqual(page.input_value('[data-fb=direction]'), 'right')
            self.assertEqual(page.input_value('[data-fb=root]'), 'D')
            self.assertFalse(page.is_checked('[data-fb=noteText]'))
            self.assertEqual(errors, [])

    def test_fretboard_dense_percussion_and_raw_boundaries(self):
        source = api.from_yaml(NATIVE_RAW_SONG)
        source['module']['channels'] += [dict(name=f'String {i}') for i in range(26)]
        source['score']['tracks']['dense'] = dict(tuning=[119]+[64]*24, channels=list(range(2,27)), instrument=1, max_fret=29)
        source['score']['tracks']['drums'] = dict(tuning=[0], channels=[27], instrument=1, midi=dict(bank=128,program=0))
        with self.muted_page(api.to_yaml(source), compact=True) as (page, state, folder):
            self.assertFalse(state.error, state.error)
            before = (folder / 'song.yaml').read_bytes()
            page.evaluate("tab('tab')")
            page.wait_for_selector('.vt-fretboard')
            page.locator('.vt-fretboard > summary').click()
            page.select_option('[data-ui=track]', 'dense')
            self.assertEqual(page.locator('[data-fb-string]').count(), 25*30)
            self.assertFalse(page.locator('.vt-fretboard svg').evaluate("e=>/NaN|undefined/.test(e.outerHTML)"))
            page.set_viewport_size(dict(width=800, height=700))
            page.select_option('[data-fb=direction]', 'left')
            self.assertEqual(page.locator('[data-fb-string="25"][data-fb-fret="29"]').get_attribute('data-pitch'), '93')
            page.select_option('[data-fb=mode]', 'audition')
            page.locator('[data-fb-string="1"][data-fb-fret="1"]').click()
            self.assertIn('preview engine range', page.locator('.vt-tab-status').inner_text())
            page.locator('[data-fb-string="1"][data-fb-fret="9"]').click(force=True)
            self.assertIn('playable range', page.locator('.vt-tab-status').inner_text())
            page.select_option('[data-fb=mode]', 'edit')
            page.select_option('[data-ui=track]', 'drums')
            self.assertEqual(page.locator('[data-fb-string]').count(), 0)
            self.assertTrue(page.locator('[data-fb=scale]').is_disabled())
            page.select_option('[data-ui=track]', 'guitar')
            self.assertFalse(page.locator('[data-fb=scale]').is_disabled())
            page.evaluate("SCORE.editor.setSelection({order:0,pattern:'verse',row:0,ch:1})")
            page.locator('[data-fb-string="2"][data-fb-fret="2"]').click(force=True)
            self.assertIn('Adopt this Pattern note', page.locator('.vt-tab-status').inner_text())
            self.assertEqual((folder / 'song.yaml').read_bytes(), before)

    def test_percussion_key_entry_lanes_controls_history_and_print(self):
        from tests.test_tablature import beat, note
        source = api.from_yaml(NATIVE_SONG)
        source['module']['channels'] = [dict(name=f'Lane {i+1}') for i in range(5)]
        score = source['score']
        score['tracks']['guitar'].update(name='Drums', tuning=[0,0,0], channels=[0,1,2],
                                        midi=dict(bank=128, program=0))
        score['tracks']['strings'] = dict(tuning=[64,59], channels=[3,4], instrument=1)
        score['ties'] = []
        score['patterns']['verse']['beats'] = [
            beat(f'd{i}', [i,1], [note(f'key-{key}', key, 1, key)])
            for i, key in enumerate([36,38,42,46])] + [dict(beat('voice-rest', [0,1], []), voice=1)]
        with self.muted_page(api.to_yaml(source), compact=True) as (page, state, folder):
            self.assertFalse(state.error, state.error)
            before = (folder / 'song.yaml').read_bytes()
            plan = json.loads(json.dumps(state.mod.native_score['plan']))
            errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.evaluate("tab('tab')")
            page.wait_for_selector('.vt-tab-edit-caret:not([hidden])')
            self.capture_engraving(page)
            page.select_option('[data-ui=track]', 'guitar')
            page.wait_for_function('window.tabRendered && tabRenderApi.boundsLookup?.isFinished')
            self.assertEqual(page.locator('[data-ui=entry-label]').inner_text(), 'Drum key')
            self.assertTrue(page.locator('[data-ui=fret]').is_visible())
            self.assertTrue(page.locator('.vt-tab-grid').is_hidden())
            self.assertTrue(page.evaluate('tabRendered.tracks[0].staves[0].isPercussion'))
            self.assertFalse(page.evaluate('tabRendered.tracks[0].staves[0].showTablature'))
            self.assertFalse(page.locator('.vt-tab-score svg').evaluate_all(
                "nodes=>nodes.some(e=>/NaN|undefined/.test(e.outerHTML))"))
            self.click_score_note(page, 2)
            self.settled(page, "CUR.o===2 && CUR.score.note==='key-36'")
            page.select_option('[data-ui=lane]', '2')
            page.locator('#tab-editor').focus()
            page.keyboard.type('100')
            self.settled(page, "SCORE.view.score.patterns.verse.beats[0].notes.some(n=>n.string===2&&n.pitch===100&&n.fret===100)")
            page.keyboard.press('Shift+ArrowDown')
            self.settled(page, "SCORE.view.score.patterns.verse.beats[0].notes.some(n=>n.string===3&&n.pitch===100)")
            self.assertEqual(page.locator('.vt-tab-edit-caret').get_attribute('data-string'), '3')
            revision = state.text_sha()
            page.fill('[data-ui=fret]', '101')
            page.click('[data-action=fret]')
            self.assertIn('1 to 100', page.locator('.vt-tab-status').inner_text())
            self.assertEqual(state.text_sha(), revision)
            page.locator('#tab-editor').focus()
            page.keyboard.press('e')
            self.assertIn('not supported on percussion', page.locator('.vt-tab-status').inner_text())
            self.assertEqual(state.text_sha(), revision)
            page.locator('.vt-tab-inspector > summary').click()
            page.fill('[data-ui=velocity]', '95')
            page.click('[data-action=velocity]')
            self.settled(page, "SCORE.view.score.patterns.verse.beats[0].notes.some(n=>n.string===3&&n.velocity===95)")
            for action in ('bend','hammer','chord-diagram','stroke'):
                self.assertTrue(page.locator(f'[data-action="{action}"]').is_disabled(), action)
            for action in ('ghost','accent','heavy-accent','staccato','dead','palm-mute'):
                self.assertFalse(page.locator(f'[data-action="{action}"]').is_disabled(), action)
                page.click(f'[data-action="{action}"]')
                flag = action.replace('-', '_')
                self.settled(page, f"SCORE.view.score.patterns.verse.beats[0].notes.some(n=>n.string===3&&n.{flag})")
            self.assertFalse(page.locator('[data-action=let-ring]').is_disabled())
            page.click('[data-action=let-ring]')
            self.settled(page, "SCORE.view.score.patterns.verse.beats[0].notes.some(n=>n.string===3&&n.let_ring&&!n.palm_mute&&!n.staccato)")
            page.fill('[data-ui=velocity]', '0')
            page.click('[data-action=velocity]')
            self.settled(page, "SCORE.view.score.patterns.verse.beats[0].notes.some(n=>n.string===3&&n.velocity===0)")
            page.evaluate("window.drumPreview=[];lvNoteOn=(...args)=>drumPreview.push(args);lvNoteOff=()=>{}")
            page.click('[data-action=preview]')
            self.assertEqual(page.evaluate('drumPreview[0].slice(2)'), [100, 0])
            self.open_setup(page)
            self.assertTrue(page.locator('[data-ui=track-kind]').is_disabled())
            revision = state.text_sha()
            page.fill('[data-ui=midi-program]', '')
            page.click('.vt-tab-setup button[type=submit]')
            self.assertIn('explicit kit program', page.locator('.vt-tab-status').inner_text())
            self.assertEqual(state.text_sha(), revision)
            page.fill('[data-ui=midi-program]', '0')
            page.fill('[data-ui=display-name]', 'Drum lanes')
            page.click('.vt-tab-setup button[type=submit]')
            self.settled(page, "SCORE.view.score.tracks.guitar.name==='Drum lanes'")
            self.assertEqual(state.song['score']['tracks']['guitar']['midi']['bank'], 128)
            page.click('[data-action=close-setup]')
            # Undo the exact edits through the shared history, then qualify print.
            while state.history:
                old = len(state.history)
                page.click('[data-action=undo]')
                page.wait_for_function('!EDQ.n && !SCORE.fetching')
                self.assertLess(len(state.history), old)
            self.assertEqual((folder / 'song.yaml').read_bytes(), before)
            page.select_option('[data-ui=voice]', index=1)
            page.select_option('[data-ui=lane]', '2')
            page.fill('[data-ui=fret]', '1')
            page.click('[data-action=fret]')
            self.settled(page, "SCORE.view.score.patterns.verse.beats[4].notes[0]?.pitch===1")
            self.assertEqual(state.song['score']['patterns']['verse']['beats'][4]['notes'][0]['string'], 2)
            page.click('[data-action=undo]')
            self.settled(page, "SCORE.view.score.patterns.verse.beats[4].notes.length===0")
            self.assertEqual((folder / 'song.yaml').read_bytes(), before)
            self.assertEqual(state.mod.native_score['plan'], plan)
            preview = page.context.browser.new_page()
            preview.goto(self.print_url(page, state)); self.print_ready(preview)
            self.capture_engraving(preview)
            for mode in ('staff','tab','both'):
                preview.select_option('[name=notation]', mode)
                preview.get_by_role('button', name='Update preview', exact=True).click()
                self.print_ready(preview)
                self.assertEqual(preview.evaluate('[tabRendered.tracks[0].staves[0].showStandardNotation,tabRendered.tracks[0].staves[0].showTablature]'), [True, False])
                self.assertGreater(preview.locator('.vt-print-pages svg').count(), 0)
            preview.close()
            page.select_option('[data-ui=track]', 'strings')
            self.assertEqual(page.locator('[data-ui=entry-label]').inner_text(), 'Fret')
            self.assertTrue(page.locator('[data-ui=lane-label]').is_hidden())
            self.assertNotEqual(page.locator('[data-action=pitch-up]').get_attribute('title'), 'Not supported on percussion tracks')
            self.assertEqual(errors, [])

    def test_direct_tab_blank_strings_rests_voices_and_keyboard_history(self):
        from tests.test_tablature import beat, note
        source = api.from_yaml(NATIVE_SONG)
        source['module']['channels'] = [dict(name=f'String {i + 1}') for i in range(6)]
        score = source['score']
        score['tracks']['guitar'].update(tuning=[64, 59, 55, 50, 45, 40], channels=list(range(6)))
        score['tracks']['guitar']['lyrics'] = dict(from_measure=1, text='One two three')
        score['ties'] = []
        score['patterns']['verse']['beats'] = [
            beat('head', [0, 1], [note('high', 64, 1, 0)]),
            beat('rest', [1, 1], []),
            beat('tail', [2, 1], [note('low', 40, 6, 0)]),
            # Keep the coincident fret/voice hit target, with independent IT routing.
            dict(beat('second', [0, 1], [note('middle', 55, 3, 0), dict(note('unison', 64, 1, 0), channel=4)]), voice=1),
        ]
        with self.muted_page(api.to_yaml(source), compact=True) as (page, state, folder):
            before = (folder / 'song.yaml').read_bytes()
            errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.evaluate("tab('tab')")
            page.wait_for_selector('.vt-tab-score svg')
            # Coincident source voices require an explicit editing voice.
            page.select_option('[data-ui=voice]', index=0)
            page.wait_for_selector('.vt-tab-edit-caret:not([hidden])')
            self.capture_engraving(page)
            page.select_option('[data-ui=track]', 'guitar')
            page.wait_for_function('window.tabRendered && tabRenderApi.boundsLookup?.isFinished')
            self.assertFalse(page.locator('.vt-tab-inspector').evaluate('e=>e.open'))
            self.assertFalse(page.locator('.vt-tab-grid-details').evaluate('e=>e.open'))
            self.assertTrue(page.locator('.vt-tab-grid').is_hidden())
            self.assertTrue(page.locator('[data-ui=beat-text]').is_hidden())
            # Blank string under a chord, on a reused occurrence.
            self.click_tab_lane(page, 2, 0, 6)
            self.settled(page, "CUR.o===2 && CUR.score.string===6 && CUR.score.voice===0")
            self.assertEqual(page.evaluate('[CUR.score.occurrence,CUR.score.at,CUR.score.note]'),
                             ['pass-3', [0, 1], None])
            page.keyboard.press('7')
            self.settled(page, "SCORE.view.score.patterns.verse.beats[0].notes.some(n=>n.string===6&&n.fret===7)")
            self.assertEqual(page.locator('.vt-tab-edit-caret').get_attribute('data-occurrence'), 'pass-3')
            page.keyboard.press('Delete')
            self.settled(page, "SCORE.view.score.patterns.verse.beats[0].notes.length===1")
            page.keyboard.press('Control+z')
            self.settled(page, "SCORE.view.score.patterns.verse.beats[0].notes.length===2")
            page.keyboard.press('Control+z')
            self.settled(page, "SCORE.view.score.patterns.verse.beats[0].notes.length===1")
            # An occupied fret chooses its own voice, even with voice 1 selected.
            self.click_tab_lane(page, 2, 0, 3, voice=1)
            self.settled(page, "CUR.score.voice===1 && CUR.score.note==='middle'")
            self.click_tab_lane(page, 2, 0, 1, voice=1)
            self.settled(page, "CUR.score.voice===1 && CUR.score.note==='unison'")
            page.select_option('[data-ui=voice]', index=0)
            self.click_tab_lane(page, 2, 0, 1)
            self.settled(page, "CUR.score.voice===0 && CUR.score.note==='high'")
            # Explicit rest: any line is an entry target, without opening the grid.
            self.click_tab_lane(page, 1, 1, 2)
            self.settled(page, "CUR.o===1 && CUR.score.beat==='rest' && CUR.score.string===2")
            page.keyboard.press('5')
            self.settled(page, "SCORE.view.score.patterns.verse.beats.find(b=>b.id==='rest').notes[0]?.fret===5")
            page.keyboard.press('-')
            self.settled(page, "SCORE.view.score.patterns.verse.beats.find(b=>b.id==='rest').written.value===8")
            page.keyboard.press('Control+z')
            self.settled(page, "SCORE.view.score.patterns.verse.beats.find(b=>b.id==='rest').written.value===4")
            page.click('[data-action=rest]')
            self.settled(page, "SCORE.view.score.patterns.verse.beats.find(b=>b.id==='rest').notes.length===0")
            page.keyboard.press('Control+z')
            self.settled(page, "SCORE.view.score.patterns.verse.beats.find(b=>b.id==='rest').notes.length===1")
            page.keyboard.press('Control+z')
            self.settled(page, "SCORE.view.score.patterns.verse.beats.find(b=>b.id==='rest').notes.length===0")
            # The final implicit rest is also editable, and uses the same tie path.
            self.click_tab_lane(page, 2, 3, 6)
            self.settled(page, "CUR.o===2 && CUR.score.at[0]===3 && CUR.score.beat===null")
            page.keyboard.press('0')
            self.settled(page, "SCORE.view.score.patterns.verse.beats.some(b=>b.at[0]===3&&b.notes[0]?.fret===0)")
            page.keyboard.press('l')
            self.settled(page, "SCORE.view.score.ties.length===1")
            page.keyboard.press('Control+z')
            self.settled(page, "SCORE.view.score.ties.length===0")
            page.keyboard.press('Control+z')
            self.settled(page, "SCORE.view.score.patterns.verse.beats.length===4")
            self.click_tab_lane(page, 0, 0, 3, voice=1)
            page.locator('.vt-tab-inspector > summary').click()
            page.select_option('[data-ui=beat-stem]', 'down')
            held = []
            page.route('**/api/score_command', lambda route: held.append(route))
            page.click('[data-action=beat-stem]')
            page.wait_for_function('EDQ.n===1')
            self.assertEqual(page.evaluate('document.activeElement.id'), 'tab-editor')
            # Undo remains usable while the focused action button is disabled.
            page.keyboard.press('Control+z')
            page.wait_for_function('EDQ.n===2')
            held.pop().continue_()
            page.unroute('**/api/score_command')
            self.settled(page, "SCORE.view.score.patterns.verse.beats[3].stem==null")
            page.keyboard.press('Control+y')
            self.settled(page, "SCORE.view.score.patterns.verse.beats[3].stem==='down'")
            page.keyboard.press('Control+z')
            self.settled(page, "SCORE.view.score.patterns.verse.beats[3].stem==null")
            page.locator('.vt-tab-inspector > summary').click()
            self.assertEqual((folder / 'song.yaml').read_bytes(), before)
            self.assertEqual(errors, [])
            self.assertFalse(page.locator('.vt-tab-inspector').evaluate('e=>e.open'))
            self.assertFalse(page.locator('.vt-tab-grid-details').evaluate('e=>e.open'))

    def test_score_playback_follow_orders_manual_edits_and_muted_transport(self):
        from tests.test_tablature import beat, note
        source = api.from_yaml(NATIVE_SONG)
        source['module'].update(tempo=240, channels=[dict(name=f'String {i + 1}') for i in range(6)])
        names = ['C', 'F', 'G', 'C2']
        source['orders'] = names
        source['patterns'] = {name: dict(rows=48, data='') for name in names}
        score = source['score']
        score['order_ids'], score['ties'] = ['bar1', 'bar2', 'bar3', 'bar4'], []
        score['tracks']['guitar'].update(tuning=[64, 59, 55, 50, 45, 40], channels=list(range(6)))
        score['patterns'] = {name: dict(row_step=[1, 12], beats=[
            beat(f'b{i}', [i, 1], [dict(note(f'n{i}', pitch), velocity=64)])
            for i, pitch in enumerate(pitches)])
            for name, pitches in zip(names, [[60, 64, 67, 64], [53, 57, 60, 57], [55, 59, 62, 59], [60, 64, 67, 60]])}
        score['measures'] = [dict(id=f'm{i}', meter=[4, 4],
            **{'from': dict(occurrence=oid, at=[0, 1]), 'to': dict(occurrence=oid, at=[4, 1])})
            for i, oid in enumerate(score['order_ids'])]
        with self.muted_page(api.to_yaml(source)) as (page, state, folder):
            self.assertFalse(state.error, state.error)
            before = (folder / 'song.yaml').read_bytes()
            plan = json.loads(json.dumps(state.mod.native_score['plan']))
            page.evaluate("tab('tab');setEdit(false)")
            page.wait_for_selector('.vt-tab-score svg')
            self.capture_engraving(page)
            page.select_option('[data-ui=track]', 'guitar')
            page.check('[data-ui=follow]')
            page.wait_for_function("document.querySelector('.vt-tab-score').dataset.bars==='4'")
            rendered = page.evaluate('tabRenderCount')
            page.fill('[data-ui=at]', '2')
            page.click('[data-action=go]')
            page.locator('#tab-editor').focus()
            page.keyboard.press('ArrowRight')
            self.assertEqual(page.input_value('[data-ui=at]'), '3')
            page.keyboard.press('ArrowRight')
            self.settled(page, 'CUR.o===1')
            self.assertEqual(page.input_value('[data-ui=at]'), '0')
            page.keyboard.press('ArrowLeft')
            self.settled(page, 'CUR.o===0')
            self.assertEqual(page.input_value('[data-ui=at]'), '3')
            page.click('[data-action=measure-first]')
            page.check('[data-ui=follow]')
            cursor = page.evaluate('JSON.stringify(CUR)')
            score_requests = []
            page.on('request', lambda request: score_requests.append(request.url) if urlsplit(request.url).path == '/api/score' else None)

            def position(order):
                page.evaluate("""order=>{
                    LV.playing=true;LV.pos={order,row:0,occurrence:'bar'+(order+1)};
                    followScorePlayhead();
                }""", order)

            for order in (1, 2, 3, 0, 3):
                position(order)
                page.wait_for_function(f"document.querySelector('.vt-tab-playhead:not([hidden])')?.dataset.occurrence==='bar{order + 1}'")
                self.assertEqual(page.evaluate('JSON.stringify(CUR)'), cursor)
                self.assertEqual(page.evaluate('SCORE.view.order'), 0)
                self.assertEqual(page.evaluate('tabRendered.masterBars.length'), 4)
                self.assertEqual(page.evaluate('tabRenderCount'), rendered)
                self.assertNotIn('Velocity:', page.locator('.vt-tab-score').text_content())
            self.assertEqual(score_requests, [])
            page.click('[data-action=measure-last]')
            page.click('[data-action=measure-previous]')
            self.settled(page, 'SCORE.view.order===2')
            self.assertFalse(page.is_checked('[data-ui=follow]'))
            position(1)
            page.wait_for_timeout(150)
            self.assertEqual(page.evaluate('[SCORE.view.order,CUR.o]'), [2, 2])
            page.check('[data-ui=follow]')
            self.assertEqual(page.evaluate('SCORE.view.order'), 2)
            self.assertEqual(page.evaluate('CUR.o'), 2)
            page.click('[data-action=lyrics]')
            position(3)
            page.wait_for_timeout(150)
            self.assertEqual(page.evaluate('SCORE.view.order'), 2)
            page.click('[data-action=lyrics-close]')
            page.evaluate('setEdit(true)')
            protected = page.evaluate('JSON.stringify(CUR)')
            position(2)
            page.wait_for_timeout(150)
            self.assertEqual(page.evaluate('SCORE.view.order'), 2)
            self.assertEqual(page.evaluate('JSON.stringify(CUR)'), protected)
            page.evaluate('setEdit(false)')
            page.evaluate('setCursor(2,0);scoreRefresh()')
            self.settled(page, 'SCORE.view.order===2')
            page.fill('[data-ui=beat-text]', 'Unsaved cue')
            position(0)
            page.wait_for_timeout(150)
            self.assertEqual(page.input_value('[data-ui=beat-text]'), 'Unsaved cue')
            self.assertEqual(page.evaluate('SCORE.view.order'), 2)
            self.assertFalse(page.is_checked('[data-ui=follow]'))
            page.fill('[data-ui=beat-text]', '')
            page.check('[data-ui=follow]')
            page.evaluate("LV.playing=false;LV.pos=null")
            # The actual native engine runs with Chromium's output muted.
            page.evaluate("""async()=>{
                window.followedOrders=[];
                const follow=followScorePlayhead;
                followScorePlayhead=()=>{follow();const o=playPos()?.o;
                    if(followedOrders.at(-1)!==o)followedOrders.push(o)};
                await lvPlay(0,0);
            }""")
            page.wait_for_function('followedOrders.includes(3)', timeout=15000)
            self.assertEqual(page.evaluate('followedOrders.slice(0,4)'), [0, 1, 2, 3])
            page.evaluate('lvStop()')
            self.assertIsNone(page.evaluate('LV.err'))
            self.assertEqual(page.evaluate('tabRenderCount'), rendered)
            self.assertEqual(page.evaluate('tabRendered.masterBars.length'), 4)
            self.click_score_note(page, 3)
            self.settled(page, "CUR.o===3 && CUR.score.pattern==='C2' && CUR.score.note==='n0'")
            page.fill('[data-ui=fret]', '2')
            page.click('[data-action=fret]')
            self.settled(page, "SCORE.view.score.patterns.C2.beats[0].notes[0].pitch===61")
            self.assertEqual(state.song['score']['patterns']['C']['beats'][0]['notes'][0]['pitch'], 60)
            page.click('[data-action=undo]')
            self.settled(page, "SCORE.view.score.patterns.C2.beats[0].notes[0].pitch===60")
            self.assertEqual((folder / 'song.yaml').read_bytes(), before)
            self.assertEqual(state.mod.native_score['plan'], plan)

    def test_score_follow_repeat_occurrences_and_stale_messages(self):
        source = api.from_yaml(PRINT_SONG)
        # Full authored measures permit a real repeat expansion over the first
        # two patterns; later repeated pattern names have distinct occurrences.
        score = source['score']
        score['measures'] = [dict(id=f'm{i}', meter=[4, 4],
            **{'from': dict(occurrence=oid, at=[0, 1]), 'to': dict(occurrence=oid, at=[4, 1])})
            for i, oid in enumerate(score['order_ids'])]
        score['measures'][0]['repeat_open'] = True
        score['measures'][1]['repeat_close'] = 1
        with self.muted_page(api.to_yaml(source)) as (page, state, folder):
            self.assertFalse(state.error, state.error)
            page.evaluate("tab('tab');setEdit(false)")
            page.wait_for_selector('.vt-tab-score svg')
            visits = page.evaluate('S.song.facts.playback_orders')
            self.assertEqual([v['source_occurrence'] for v in visits],
                             ['verse-1', 'bridge-1', 'verse-1', 'bridge-1', 'repeat-1', 'repeat-2'])
            cursor = page.evaluate('JSON.stringify(CUR)')
            for i, visit in enumerate(visits):
                page.evaluate("""i=>{
                    const v=S.song.facts.playback_orders[i];
                    LV.playing=true;LV.pos={order:i,row:0,sourceOrder:v.source_order,
                        sourceOccurrence:v.source_occurrence,sourceRow:0,playId:v.id,pass:v.pass,
                        revision:S.playback_revision};followScorePlayhead();
                }""", i)
                order = score['order_ids'].index(visit['source_occurrence'])
                page.wait_for_function("oid=>document.querySelector('.vt-tab-playhead:not([hidden])')?.dataset.occurrence===oid", arg=visit['source_occurrence'])
                self.assertEqual(page.get_attribute('.vt-tab-score', 'data-bars'), '4')
                self.assertEqual(page.evaluate('SCORE.view.order'), 0)
                self.assertEqual(page.evaluate('JSON.stringify(CUR)'), cursor)
            page.evaluate("LV.pos={...LV.pos,order:0,revision:'stale'};followScorePlayhead()")
            self.assertTrue(page.locator('.vt-tab-playhead').is_hidden())
            page.evaluate('LV.playing=false;LV.pos=null;followScorePlayhead()')
            self.assertEqual(page.evaluate('SCORE.view.order'), 0)

    def test_full_score_wrapped_occurrence_hits_edit_undo_and_scroll(self):
        from tests.test_tablature import beat, note
        source = api.from_yaml(NATIVE_SONG)
        source['module']['channels'] = [dict(name=f'String {i + 1}') for i in range(6)]
        source['orders'] = ['verse'] * 32
        score = source['score']
        score['tracks']['guitar'].update(tuning=[64, 59, 55, 50, 45, 40], channels=list(range(6)))
        score['order_ids'] = [f'pass-{i + 1}' for i in range(32)]
        score['ties'] = []
        score['patterns']['verse']['beats'] = [beat('head', [0, 1], [note('hit', 64, 1, 0)], value=1)]
        score['measures'] = [dict(id=f'm{i}', meter=[4, 4],
            **{'from': dict(occurrence=oid, at=[0, 1]), 'to': dict(occurrence=oid, at=[4, 1])})
            for i, oid in enumerate(score['order_ids'])]
        with self.muted_page(api.to_yaml(source), width=900, height=800, compact=True) as (page, state, folder):
            before = (folder / 'song.yaml').read_bytes()
            page.evaluate("tab('tab');setEdit(false)")
            page.wait_for_selector('.vt-tab-score[data-bars="32"]')
            self.capture_engraving(page)
            page.select_option('[data-ui=track]', 'guitar')
            page.wait_for_function('tabRenderApi.boundsLookup?.isFinished')
            self.assertGreater(page.evaluate('tabRenderApi.boundsLookup.staffSystems.length'), 1)
            count = page.evaluate('tabRenderCount')
            page.check('[data-ui=follow]')
            page.evaluate("LV.playing=true;LV.pos={order:31,row:0,occurrence:'pass-32'};followScorePlayhead()")
            page.wait_for_selector('.vt-tab-playhead[data-occurrence="pass-32"]:not([hidden])')
            self.assertTrue(page.locator('.vt-tab-playhead').evaluate(
                "e=>{const r=e.getBoundingClientRect(),v=document.querySelector('#t-tab').getBoundingClientRect();return r.top>=v.top&&r.bottom<=v.bottom}"))
            self.assertEqual(page.evaluate('CUR.o'), 0)
            self.assertEqual(page.evaluate('tabRenderCount'), count)
            page.locator('#tab-editor').dispatch_event('wheel', dict(deltaY=-100))
            self.assertFalse(page.is_checked('[data-ui=follow]'))
            page.evaluate("document.querySelector('#tab-editor').scrollTop=0;document.querySelector('#t-tab').scrollTop=0")
            scroll = page.evaluate("[document.querySelector('#tab-editor').scrollTop,document.querySelector('#t-tab').scrollTop]")
            page.evaluate("LV.pos={order:30,row:0,occurrence:'pass-31'};followScorePlayhead()")
            self.assertEqual(page.evaluate("[document.querySelector('#tab-editor').scrollTop,document.querySelector('#t-tab').scrollTop]"), scroll)
            page.check('[data-ui=follow]')
            page.locator('#tab-editor').dispatch_event('keydown', dict(key='PageUp'))
            self.assertFalse(page.is_checked('[data-ui=follow]'))
            page.evaluate("LV.pos={order:0,row:0,occurrence:'pass-1'};followScorePlayhead()")
            self.assertEqual(page.evaluate('tabRenderCount'), count)
            page.evaluate('LV.playing=false;LV.pos=null')
            # Keyboard navigation brings the edit caret into view, independently
            # of the paused playback follower, including across staff systems.
            page.locator('#tab-editor').focus()
            page.keyboard.press('Control+Shift+ArrowRight')
            self.settled(page, 'CUR.o===31')
            self.assertTrue(page.locator('.vt-tab-edit-caret').evaluate(
                "e=>{const r=e.getBoundingClientRect(),v=document.querySelector('#t-tab').getBoundingClientRect();return r.top>=v.top&&r.bottom<=v.bottom}"))
            page.keyboard.press('Control+Shift+ArrowLeft')
            self.settled(page, 'CUR.o===0')
            self.assertTrue(page.locator('.vt-tab-edit-caret').evaluate(
                "e=>{const r=e.getBoundingClientRect(),v=document.querySelector('#t-tab').getBoundingClientRect();return r.top>=v.top&&r.bottom<=v.bottom}"))
            self.click_tab_lane(page, 31, 0, 1)
            self.settled(page, 'CUR.o===31 && SCORE.view.order===31')
            self.assertEqual(page.evaluate('[CUR.score.occurrence,CUR.score.note,CUR.score.beat,CUR.score.voice]'),
                             ['pass-32', 'hit', 'head', 0])
            self.assertEqual(page.evaluate('tabRenderCount'), count)
            self.assertEqual(page.get_attribute('.vt-tab-score', 'data-bars'), '32')
            page.keyboard.press('ArrowLeft')
            self.settled(page, 'CUR.o===30 && SCORE.view.order===30')
            self.assertEqual(page.input_value('[data-ui=at]'), '0')
            page.keyboard.press('ArrowRight')
            self.settled(page, 'CUR.o===31 && SCORE.view.order===31')
            self.assertEqual(page.input_value('[data-ui=at]'), '0')
            self.assertEqual(page.evaluate('tabRenderCount'), count)
            page.keyboard.press('2')
            self.settled(page, 'SCORE.view.score.patterns.verse.beats[0].notes[0].fret===2')
            page.wait_for_selector('.vt-tab-score[data-bars="32"]')
            self.assertEqual(page.evaluate('tabRendered.tracks[0].staves[0].bars.map(b=>b.voices[0].beats[0].notes[0].fret)'), [2] * 32)
            self.assertEqual(len(state.history), 1)
            page.click('[data-action=undo]')
            self.settled(page, 'SCORE.view.score.patterns.verse.beats[0].notes[0].fret===0')
            self.assertEqual((folder / 'song.yaml').read_bytes(), before)

    def test_tab_preview_preserves_explicit_zero_velocity_and_inheritance(self):
        source = api.from_yaml(NATIVE_SONG)
        source['score']['patterns']['verse']['beats'][0]['notes'][0]['velocity'] = 64
        with self.muted_page(api.to_yaml(source)) as (page, state, folder):
            page.evaluate("tab('tab');setEdit(true)")
            page.wait_for_selector('.vt-tab-grid [data-note=note-0]')
            page.click('.vt-tab-grid [data-note=note-0]')
            # Inspect the real UI-to-host callback without starting any audio.
            page.evaluate("window.previewCalls=[];lvNoteOn=(...args)=>previewCalls.push(args);lvNoteOff=()=>{}")
            for value in (64, 0, None):
                if value != 64:
                    page.fill('[data-ui=velocity]', '' if value is None else str(value))
                    page.click('[data-action=velocity]')
                    expected = '==null' if value is None else f'==={value}'
                    self.settled(page, f'SCORE.view.score.patterns.verse.beats[0].notes[0].velocity{expected}')
                page.click('[data-action=preview]')
                self.assertEqual(page.evaluate('previewCalls.at(-1)'),
                                 ['tab', 0, 64, 1 if value is None else value / 127])
            self.assertEqual(page.evaluate('previewCalls.length'), 3)
            self.assertIsNone(page.evaluate('LV.ctx'))

    def test_lyrics_raw_text_history_guards_and_clear(self):
        from vulturetracker import server
        source = api.from_yaml(NATIVE_SONG)
        raw = 'one\r\ntwo\rthree\nhy-phen + _ [x]\t\u00a0'
        source['score']['tracks']['guitar']['lyrics'] = dict(from_measure=1, text=raw)
        source['score']['tracks']['guitar']['midi'] = dict(
            program=25, bank=3, source_pan=dict(value=63, mixer_pan=32))
        with self.muted_page(api.to_yaml(source)) as (page, state, folder):
            self.assertFalse(state.error, state.error)
            before = (folder / 'song.yaml').read_bytes()
            plan = json.loads(json.dumps(state.mod.native_score['plan']))
            page.evaluate("tab('tab');setEdit(true)")
            page.wait_for_selector('[data-action=lyrics]')
            page.click('[data-action=lyrics]')
            self.assertIn('authored measures', page.inner_text('[data-ui=lyrics-map]'))
            preview = page.context.browser.new_page()
            preview.goto(self.print_url(page, state))
            self.print_ready(preview)
            self.assertIn('authored measures', preview.inner_text('[data-print=lyrics]'))
            preview.close()
            self.assertEqual(page.input_value('[data-ui=lyrics-text]'), raw.replace('\r\n', '\n').replace('\r', '\n'))
            self.assertIsNone(page.get_attribute('[data-ui=lyrics-text]', 'maxlength'))
            page.fill('[data-ui=lyrics-text]', 'cancelled')
            page.click('[data-action=lyrics-close]')
            self.assertEqual((folder / 'song.yaml').read_bytes(), before)
            self.open_setup(page)
            page.fill('[data-ui=display-name]', 'Preserved lyrics')
            page.locator('.vt-tab-setup button[type=submit]').first.click()
            self.settled(page, "SCORE.view.score.tracks.guitar.name==='Preserved lyrics'")
            self.assertEqual(state.song['score']['tracks']['guitar']['lyrics']['text'], raw)
            page.click('[data-action=close-setup]')
            page.click('[data-action=undo]')
            self.settled(page, "!SCORE.view.score.tracks.guitar.name")
            self.assertEqual((folder / 'song.yaml').read_bytes(), before)
            page.click('[data-action=lyrics]')
            page.fill('[data-ui=lyrics-from]', '2147483647')
            history = len(state.history)
            page.click('[data-ui=lyrics-apply]')
            self.settled(page, 'SCORE.view.score.tracks.guitar.lyrics.from_measure===2147483647')
            self.assertEqual(state.song['score']['tracks']['guitar']['lyrics']['text'], raw)
            self.assertEqual(len(state.history), history + 1)
            self.assertEqual(state.song['score']['tracks']['guitar']['midi'], source['score']['tracks']['guitar']['midi'])
            self.assertEqual(state.mod.native_score['plan'], plan)
            saved = (folder / 'song.yaml').read_bytes()
            page.click('[data-action=undo]')
            self.settled(page, 'SCORE.view.score.tracks.guitar.lyrics.from_measure===1')
            self.assertEqual((folder / 'song.yaml').read_bytes(), before)
            page.click('[data-action=redo]')
            self.settled(page, 'SCORE.view.score.tracks.guitar.lyrics.from_measure===2147483647')
            self.assertEqual((folder / 'song.yaml').read_bytes(), saved)
            page.evaluate('async path=>{await openSong(path)}', str(folder / 'song.yaml'))
            state = server.Handler.state
            page.evaluate("tab('tab');setEdit(true)")
            page.wait_for_selector('[data-action=lyrics]')
            self.assertEqual(state.song['score']['tracks']['guitar']['lyrics']['text'], raw)
            page.click('[data-action=lyrics]')
            page.evaluate("LV.playing=true;SCORE.editor.setPlayhead(null)")
            self.assertTrue(page.is_disabled('[data-ui=lyrics-apply]'))
            page.locator('.vt-tab-lyrics').evaluate("e=>e.dispatchEvent(new Event('submit',{cancelable:true}))")
            self.assertIn('Stop playback', page.inner_text('[data-ui=lyrics-status]'))
            self.assertEqual((folder / 'song.yaml').read_bytes(), saved)
            page.evaluate("LV.playing=false;SCORE.editor.setPlayhead(null)")
            page.fill('[data-ui=lyrics-text]', 'x' * 65537)
            page.click('[data-ui=lyrics-apply]')
            self.assertIn('no text was truncated', page.inner_text('[data-ui=lyrics-status]'))
            self.assertEqual(len(page.input_value('[data-ui=lyrics-text]')), 65537)
            self.assertEqual((folder / 'song.yaml').read_bytes(), saved)
            page.fill('[data-ui=lyrics-text]', 'edited\r\nline\rend')
            page.click('[data-ui=lyrics-apply]')
            self.settled(page, "SCORE.view.score.tracks.guitar.lyrics.text==='edited\\nline\\nend'")
            self.assertEqual(state.song['score']['tracks']['guitar']['lyrics']['text'], 'edited\nline\nend')
            page.click('[data-action=lyrics]')
            page.click('[data-action=undo]')
            self.settled(page, "SCORE.view.score.tracks.guitar.lyrics.text!=='edited\\nline\\nend'")
            stale = (folder / 'song.yaml').read_bytes()
            page.click('[data-ui=lyrics-apply]')
            self.assertIn('revision changed', page.inner_text('[data-ui=lyrics-status]'))
            self.assertEqual((folder / 'song.yaml').read_bytes(), stale)
            page.click('[data-action=lyrics-close]')
            page.click('[data-action=lyrics]')
            page.fill('[data-ui=lyrics-text]', '')
            page.click('[data-ui=lyrics-apply]')
            self.settled(page, "SCORE.view.score.tracks.guitar.lyrics.text===''")
            self.assertEqual(state.song['score']['tracks']['guitar']['lyrics'], dict(from_measure=2147483647, text=''))
            page.click('[data-action=lyrics]')
            page.click('[data-action=lyrics-remove]')
            self.settled(page, "!('lyrics' in SCORE.view.score.tracks.guitar)")
            self.assertEqual(state.mod.native_score['plan'], plan)

    def test_section_labels_track_names_and_rerender_overlays(self):
        source = self.four_bar_song()
        source['score']['tracks']['guitar']['name'] = 'Lead guitar'
        source['score']['measures'][0]['marker'] = dict(title='Opening')
        for pattern in source['score']['patterns'].values():
            for beat in pattern['beats']:
                for note in beat['notes']:
                    note['vibrato'] = True
        boxes = """selector => {
          const texts=[...document.querySelectorAll(selector+' svg text')];
          const marker=texts.find(e=>e.textContent==='Opening').getBoundingClientRect();
          const name=texts.find(e=>e.textContent==='Lead guitar').getBoundingClientRect();
          const wave=texts.find(e=>e.textContent.includes('\ueab2'));
          const canvas=document.createElement('canvas').getContext('2d');
          canvas.font=getComputedStyle(wave).font;
          const ink=canvas.measureText(wave.textContent);
          const top=new DOMPoint(0,-ink.actualBoundingBoxAscent).matrixTransform(wave.getScreenCTM()).y;
          return {clearance:top-marker.bottom,nameWidth:name.width,nameHeight:name.height};
        }"""
        with self.muted_page(api.to_yaml(source), width=1400, height=1000, compact=True) as (page, state, folder):
            before = state.song_path.read_bytes()
            page.evaluate("tab('tab')")
            page.wait_for_selector('.vt-tab-score svg')
            page.evaluate('() => document.fonts.ready')
            layout = page.evaluate(boxes, '.vt-tab-score')
            self.assertGreater(layout['clearance'], 2, layout)
            self.assertGreater(layout['nameWidth'], layout['nameHeight'] * 3, layout)
            for opened in (False, True):
                page.locator('#part-sounds').evaluate('(e,v)=>e.open=v', opened)
                self.assertTrue(page.evaluate("document.querySelector('#part-sounds').getBoundingClientRect().bottom <= document.querySelector('#tab-editor').getBoundingClientRect().top"))
            page.locator('#part-sounds').evaluate('e=>e.open=false')
            # Resizing and rerendering must not turn our caret into an SVG part.
            for width in (1600, 1400):
                page.set_viewport_size(dict(width=width, height=1000))
                page.wait_for_timeout(250)  # alphaTab's debounced resize
                caret = page.locator('.vt-tab-edit-caret')
                self.assertEqual(caret.locator('svg').count(), 0)
                self.assertAlmostEqual(caret.bounding_box()['width'], 20, delta=1)
            preview = page.context.browser.new_page()
            preview.goto(self.print_url(page, state)); self.print_ready(preview)
            layout = preview.evaluate(boxes, '.vt-print-pages')
            self.assertGreater(layout['clearance'], 2, layout)
            self.assertGreater(layout['nameWidth'], layout['nameHeight'] * 3, layout)
            preview.close()
            self.assertEqual(state.song_path.read_bytes(), before)

    def test_dense_lyrics_spacing_controls_print_and_navigation(self):
        from tests.test_tablature import beat, note
        source = self.four_bar_song()
        words = ('Soft light drifts home Silver morning carries whispers '
                 'Through the quiet valley gently floating over water '
                 'Underneath branches daylight gathers slowly Beyond the hills '
                 'we follow home again').split()
        for pattern, value in zip(source['score']['patterns'].values(), (8, 16, 4, 4)):
            pattern['beats'] = [beat(f'b{i}', [i * 4, value], [note(f'n{i}', 64, 1, 0)], value=value)
                                for i in range(value)]
        for i, b in enumerate(source['score']['patterns']['C']['beats']):
            b['voice'] = i % 2  # Authoritative lyric anchors alternate voices at each onset.
        with self.muted_page(api.to_yaml(source), width=1920, height=1080, compact=True) as (page, state, folder):
            self.assertFalse(state.error, state.error)
            before = state.song_path.read_bytes()
            data = api.compile_song(state.song_path)[0]
            events = json.loads(json.dumps(state.mod.native_score['plan']['events']))
            errors = []; page.on('pageerror', lambda error: errors.append(str(error)))
            page.evaluate("tab('tab');setEdit(true)")
            page.wait_for_selector('.vt-tab-score svg'); self.capture_engraving(page)
            page.click('[data-action=lyrics]'); page.fill('[data-ui=lyrics-text]', ' '.join(words))
            page.click('[data-ui=lyrics-apply]')
            self.settled(page, "SCORE.view.score.tracks.guitar.lyrics?.text.startsWith('Soft light')")
            page.wait_for_function("document.querySelector('.vt-tab-score')?.textContent.includes('Underneath')")
            print('dense editor:', lyric_boxes(page, '.vt-tab-score', words))
            self.assertEqual(page.evaluate("tabRendered.tracks[0].staves[0].bars.flatMap(b=>b.voices.flatMap(v=>v.beats).filter(b=>b.lyrics).sort((a,b)=>a.absoluteDisplayStart-b.absoluteDisplayStart).map(b=>b.lyrics[0]))"), words)
            self.assertEqual(api.compile_song(state.song_path)[0], data)
            self.assertEqual(state.mod.native_score['plan']['events'], events)
            # Native hit bounds must move together with the spaced notes.
            point = self.tab_lane_point(page, 0, 3, 1, voice=1)
            page.mouse.click(point['x'], point['y'])
            page.wait_for_selector('.vt-tab-edit-caret:not([hidden])')
            self.assertEqual(Fraction(page.locator('.vt-tab-edit-caret').get_attribute('data-at')), Fraction(3, 2))
            page.evaluate("followScorePlayhead=()=>{};SCORE.editor.setPlayhead({o:0,row:18})")
            page.wait_for_selector('.vt-tab-playhead:not([hidden])')
            positions = page.evaluate("""()=>{
                const b=tabRendered.tracks[0].staves[0].bars[0].voices[1].beats[3];
                return {expected:tabRenderApi.boundsLookup.findBeats(b).at(-1).onNotesX,
                    actual:parseFloat(document.querySelector('.vt-tab-playhead').style.left)};
            }""")
            self.assertAlmostEqual(positions['actual'], positions['expected'], delta=1)
            page.evaluate('SCORE.editor.setPlayhead(null)')
            page.set_viewport_size(dict(width=900,height=1080))
            page.wait_for_timeout(300)
            print('dense narrow editor:', lyric_boxes(page, '.vt-tab-score', words))
            page.locator('.vt-tab-score').evaluate("e=>e.style.width='480px'")
            page.wait_for_function("document.querySelector('.vt-tab-score .at-surface').hidden")
            self.assertIn('need more width', page.locator('.vt-tab-status').inner_text())
            page.locator('.vt-tab-score').evaluate("e=>e.style.width=''")
            page.wait_for_function("!document.querySelector('.vt-tab-score .at-surface').hidden")
            self.assertNotIn('need more width', page.locator('.vt-tab-status').inner_text())
            lyric_boxes(page, '.vt-tab-score', words)
            preview = page.context.browser.new_page()
            preview.goto(self.print_url(page, state))
            preview.wait_for_function("document.querySelector('.vt-print-status')?.textContent.startsWith('Cannot print')")
            self.assertIn('Lyrics in bar 2 need more width', preview.inner_text('.vt-print-status'))
            self.assertTrue(preview.locator('[data-print=print]').is_disabled())
            for mode, scale in (('both',40),('tab',40),('staff',40),('both',40)):
                preview.select_option('[name=notation]', mode); preview.fill('[name=scale]', str(scale))
                preview.locator('form button[type=submit]').click(); self.print_ready(preview)
                print('dense print:', mode, scale, lyric_boxes(preview, '.vt-print-pages', words))
            preview.select_option('[name=orientation]', 'landscape'); preview.fill('[name=scale]', '80')
            preview.locator('form button[type=submit]').click(); self.print_ready(preview)
            print('dense landscape:', lyric_boxes(preview, '.vt-print-pages', words))
            preview.close()
            page.click('[data-action=undo]'); self.settled(page, "!SCORE.view.score.tracks.guitar.lyrics")
            self.assertEqual(state.song_path.read_bytes(), before)
            self.assertEqual(api.compile_song(state.song_path)[0], data)
            page.click('[data-action=lyrics]'); page.fill('[data-ui=lyrics-text]', 'Soft light drifts home')
            page.click('[data-ui=lyrics-apply]'); self.settled(page, "!!SCORE.view.score.tracks.guitar.lyrics")
            page.wait_for_function("document.querySelector('.vt-tab-score')?.textContent.includes('drifts')")
            lyric_boxes(page, '.vt-tab-score', words[:4])
            preview = page.context.browser.new_page()
            preview.goto(self.print_url(page, state)); self.print_ready(preview)
            for scale in (80,150):
                preview.fill('[name=scale]', str(scale)); preview.locator('form button[type=submit]').click(); self.print_ready(preview)
                print('phrase print:', scale, lyric_boxes(preview, '.vt-print-pages', words[:4]))
            preview.close()
            page.click('[data-action=undo]'); self.settled(page, "!SCORE.view.score.tracks.guitar.lyrics")
            self.assertEqual(state.song_path.read_bytes(), before)
            self.assertFalse(errors, errors)

    def test_lyrics_written_engraving_print_and_mapping_error(self):
        from tests.test_tablature import beat, note
        source = api.from_yaml(NATIVE_SONG)
        score = source['score']
        score['patterns']['verse']['beats'] = [
            beat('rest', [0, 1], []),
            beat('sound', [0, 1], [note('n', 64, 1, 0)], voice=1),
            beat('tail', [1, 1], [note('t', 64, 1, 0)], voice=1)]
        score['ties'] = [{'from': dict(occurrence='pass-1', note='n'), 'to': dict(occurrence='pass-1', note='t')}]
        score['measures'] = [dict(id=f'm{i}', meter=[4, 4],
            **{'from': dict(occurrence=oid, at=[0, 1]), 'to': dict(occurrence=oid, at=[4, 1])})
            for i, oid in enumerate(score['order_ids'])]
        score['tracks']['guitar']['lyrics'] = dict(from_measure=1, text='hy-phen + _ [x] \u00a0word\u00a0 last')
        source['module']['channels'] = [dict(name=f'String {i + 1}') for i in range(6)] + [dict(name='Other')]
        score['tracks']['guitar'].update(tuning=[64, 59, 55, 50, 45, 40], channels=list(range(6)))
        score['tracks']['other'] = dict(tuning=[59], channels=[6], instrument=1)
        with self.muted_page(api.to_yaml(source)) as (page, state, folder):
            self.assertFalse(state.error, state.error)
            page.evaluate("tab('tab');setEdit(true)")
            page.wait_for_selector('[data-action=lyrics]')
            self.capture_engraving(page)
            page.select_option('[data-ui=track]', 'guitar')
            expression = "tabRendered.tracks[0].staves[0].bars.flatMap(b=>b.voices.flatMap(v=>v.beats)).filter(b=>b.lyrics).map(b=>[b.voice.index,b.lyrics[0]])"
            all_lyrics = [[1, word] for word in ['hy-phen', '+', '_', '[x]', '\u00a0word\u00a0', 'last']]
            self.assertEqual(page.evaluate(expression), all_lyrics)
            page.wait_for_function("document.querySelector('.vt-tab-score')?.textContent.includes('hy-phen')")
            self.assertEqual(page.locator('.vt-tab-score svg text').filter(has_text='hy-phen').count(), 1)
            page.evaluate('async()=>{setCursor(1,0);await scoreRefresh()}')
            self.assertEqual(page.evaluate(expression), all_lyrics)
            preview = page.context.browser.new_page()
            preview.goto(self.print_url(page, state))
            self.print_ready(preview)
            self.capture_engraving(preview)
            preview.locator('form button[type=submit]').click()
            self.print_ready(preview)
            self.assertEqual(preview.evaluate(expression),
                             [[1, word] for word in ['hy-phen', '+', '_', '[x]', '\u00a0word\u00a0', 'last']])
            self.assertEqual(preview.locator('.vt-print-page svg text').filter(has_text='hy-phen').count(), 1)
            self.assertEqual(preview.locator('.vt-print-page svg text').filter(has_text='[x]').count(), 1)
            for notation in ('staff', 'tab', 'both'):
                preview.select_option('[name=notation]', notation)
                preview.locator('form button[type=submit]').click()
                self.print_ready(preview)
                self.assertEqual(preview.locator('.vt-print-page svg text').filter(has_text='hy-phen').count(), 1)
            self.assertEqual(preview.inner_text('[data-print=lyrics]'), '')
            preview.close()
            page.click('[data-action=lyrics]')
            self.assertEqual(page.inner_text('[data-ui=lyrics-map]'), '')
            saved = (folder / 'song.yaml').read_bytes()
            page.select_option('[data-ui=track]', 'other')
            page.click('[data-ui=lyrics-apply]')
            self.assertIn('track or revision changed', page.inner_text('[data-ui=lyrics-status]'))
            self.assertEqual((folder / 'song.yaml').read_bytes(), saved)
            page.select_option('[data-ui=track]', 'guitar')
            page.click('[data-action=lyrics-close]')
            page.click('[data-action=lyrics]')

    # Reuse the existing server/browser fixture without inheriting its test cases.
    @contextmanager
    def page(self, *args, compact=False, score_view='page', **kwargs):
        with tempfile.TemporaryDirectory() as library_dir, mock.patch(
                'vulturetracker.chord_library.user_dir', return_value=Path(library_dir)):
            self.chord_library_dir = Path(library_dir)
            with page_fixture.TestRelease100Page.page(self, *args, **kwargs) as result:
                if score_view == 'page':
                    # Geometry/editing fixtures explicitly use the original single-track sounding-pitch view.
                    # Fresh-install defaults are exercised separately with score_view=None.
                    result[0].evaluate("""localStorage.setItem('vt.scoreView',JSON.stringify({layout:'page',scale:100,
                        notation:'both',multitrack:false,compact:false,chordNames:true,chordDiagrams:true,
                        dynamics:true,pitch:'concert'}))""")
                if not compact:
                    # Existing feature tests exercise the optional controls.
                    # Direct-score tests use compact=True to test collapsed editing panels.
                    result[0].evaluate("""() => {
                        const expand=()=>{const inspector=document.querySelector('.vt-tab-inspector');
                            if(!inspector)return false;
                            inspector.open=true;document.querySelector('.vt-tab-grid-details').open=true;return true;};
                        if(!expand()){const observer=new MutationObserver(()=>{if(expand())observer.disconnect()});
                            observer.observe(document.body,{childList:true,subtree:true});}
                    }""")
                yield result

    def test_written_overlap_pattern_identity_range_clipboard_and_release_navigation(self):
        from tests.test_tablature_sync import written_voice_song
        source = written_voice_song()
        source['samples'][1]['file'] = 'a.wav'
        source['instruments'][2] = dict(sample=1)
        for b in source['score']['patterns']['a']['beats']:
            b['notes'][0].update(pitch=65, fret=1, velocity=95, volume=32)
        with self.page(api.to_yaml(source)) as (page, state, folder):
            self.assertFalse(state.error, state.error)
            before = (folder / 'song.yaml').read_bytes()
            page.evaluate("tab('tab');setEdit(true)")
            page.wait_for_selector('.vt-tab-grid [data-note=long]')
            page.evaluate("tab('pattern');setFocus('all');setCursor(0,0,0,0)")
            page.wait_for_function("PAT.native && PAT.collisions?.length && PAT.score_positions?.length")
            self.assertEqual(page.evaluate('PAT.rows[0][0]'), '... .. ... ...')
            chips = page.locator('#pat [data-role=attack][data-score-id]')
            self.assertEqual(chips.count(), 2)
            self.assertIn('V1 F-5 · long', chips.nth(0).inner_text())
            self.assertIn('V2 F-5 · short', chips.nth(1).inner_text())
            for action in ('selTranspose(1)', 'selClear()', 'selCopy(false)', 'cursorCopy()',
                           "editKey({key:'Delete'},'delete')"):
                page.evaluate('EDQ.err=null;' + action)
                self.assertIn('Choose a source note', page.evaluate('EDQ.err'))
                self.assertEqual((folder / 'song.yaml').read_bytes(), before)
            page.click('#pat [data-role=attack][data-score-id="first/short"]')
            self.assertEqual(page.evaluate('agSelection().source_note'),
                             dict(id='first/short', beat='short', note='short', voice=1, occurrence='first'))
            self.assertFalse(page.evaluate('agSelection().all_heads'))
            page.evaluate("tab('tab')")
            self.settled(page, "SCORE.view.pattern==='a'")
            self.assertEqual(page.input_value('[data-ui=voice]'), '1')
            self.assertEqual(page.get_attribute('.vt-tab-grid [data-note=short]', 'aria-pressed'), 'true')
            page.evaluate('setCursor(0,0,0,0)')
            self.assertEqual(page.input_value('[data-ui=voice]'), '1')
            self.assertEqual(page.locator('.vt-tab-grid [aria-pressed=true]').count(), 0)
            page.evaluate("tab('pattern')")
            page.click('#pat [data-role=attack][data-score-id="first/short"]')
            page.keyboard.press('Control+q')
            page.wait_for_function("!EDQ.n && PAT.score_positions?.some(p=>p.note==='short'&&p.pitch===66)")
            notes = {n['id']: n for b in state.song['score']['patterns']['a']['beats'] for n in b['notes']}
            self.assertEqual([notes['long']['pitch'], notes['short']['pitch']], [65, 66])
            page.click('#lv-undo')
            page.wait_for_function("!EDQ.n && PAT.score_positions?.some(p=>p.note==='short'&&p.pitch===65)")
            self.assertEqual((folder / 'song.yaml').read_bytes(), before)
            page.click('#pat [data-role=attack][data-score-id="first/short"]')
            page.evaluate("$('lv-step').value='0'")
            page.keyboard.press('ArrowRight')
            page.keyboard.press('ArrowRight')
            page.keyboard.press('4')
            page.keyboard.press('8')
            page.wait_for_function("!EDQ.n && (EDQ.err||PAT.score_positions?.some(p=>p.note==='short'&&p.volume===48))")
            self.assertIsNone(page.evaluate('EDQ.err'))
            notes = {n['id']: n for b in state.song['score']['patterns']['a']['beats'] for n in b['notes']}
            self.assertEqual([notes['long']['volume'], notes['short']['volume']], [32, 48])
            page.click('#lv-undo')
            page.wait_for_function("!EDQ.n && PAT.score_positions?.some(p=>p.note==='short'&&p.volume===4)")
            page.click('#lv-undo')
            page.wait_for_function("!EDQ.n && PAT.score_positions?.some(p=>p.note==='short'&&p.volume===32)")
            page.click('#pat [data-role=attack][data-score-id="first/short"]')
            page.evaluate("$('lv-ins').value='1';selSetIns()")
            page.wait_for_function("!EDQ.n && PAT.score_positions?.some(p=>p.note==='short'&&p.source_instrument===2)")
            self.assertEqual(page.evaluate("PAT.score_positions.find(p=>p.kind==='note'&&p.note==='long').source_instrument"), 1)
            page.click('#lv-undo')
            page.wait_for_function("!EDQ.n && PAT.score_positions?.some(p=>p.note==='short'&&p.source_instrument===1)")
            page.click('#pat [data-role=attack][data-score-id="first/short"]')
            page.keyboard.press('ArrowRight')
            page.keyboard.press('Delete')
            page.wait_for_function('!EDQ.n && !!EDQ.err')
            self.assertEqual((folder / 'song.yaml').read_bytes(), before)
            page.click('#pat [data-role=attack][data-score-id="first/short"]')
            page.click('[onclick="selCopy(false)"]')
            page.wait_for_function('!EDQ.n && CLIP?.native')
            self.assertEqual(page.evaluate('CLIP.native.score.beats.flatMap(b=>b.notes.map(n=>n.id))'), ['short'])
            page.evaluate("SEL={o:0,a:{row:0,ch:0,col:0},b:{row:1,ch:0,col:2}};renderPat()")
            self.assertTrue(page.evaluate('agSelection().all_heads'))
            self.assertNotIn('source_note', page.evaluate('agSelection()'))
            page.click('[onclick="selCopy(false)"]')
            page.wait_for_function('!EDQ.n && CLIP?.native.score.beats.length===2')
            self.assertEqual(page.evaluate('CLIP.native.score.beats.map(b=>b.voice)'), [0, 1])
            page.evaluate("SEL=null;setCursor(1,0,0,0);showPattern(1)")
            page.wait_for_function("PAT.native && PAT.occurrence==='second' && PAT.rows")
            page.click('#sel-paste')
            page.wait_for_function("!EDQ.n && PAT.score_positions?.filter(p=>p.kind==='note').length===2")
            self.assertIsNone(page.evaluate('EDQ.err'))
            self.assertEqual([b['voice'] for b in state.song['score']['patterns']['b']['beats']], [0, 1])
            page.click('#lv-undo')
            page.wait_for_function("!EDQ.n && PAT.score_positions?.length===0")
            self.assertEqual((folder / 'song.yaml').read_bytes(), before)
            page.evaluate("setCursor(0,0,0,0);showPattern(0)")
            page.wait_for_function("PAT.occurrence==='first' && PAT.score_positions?.length")
            page.click('#pat [data-role=release][data-score-id="first/short"]')
            self.assertEqual(page.evaluate('[CUR.row,CUR.score.note,CUR.score.readonly]'), [3, 'short', True])
            self.assertEqual(page.locator('#pat .pt[data-r="3"] .pc .n').first.inner_text(), '...')
            self.assertEqual(page.locator('#pat .score-events .on').count(), 1)
            page.keyboard.press('Delete')
            self.assertEqual((folder / 'song.yaml').read_bytes(), before)
            page.click('#pat [data-role=attack][data-score-id="first/short"]')
            page.keyboard.press('Delete')
            page.wait_for_function("!EDQ.n && PAT.score_positions?.filter(p=>p.kind==='note').length===1")
            self.assertEqual([n['id'] for b in state.song['score']['patterns']['a']['beats'] for n in b['notes']], ['long'])
            page.click('#lv-undo')
            page.wait_for_function("!EDQ.n && PAT.collisions?.length")
            self.assertEqual((folder / 'song.yaml').read_bytes(), before)
            page.evaluate('async path=>{await openSong(path)}', str(folder / 'song.yaml'))
            page.evaluate("tab('pattern')")
            page.wait_for_function("PAT.collisions?.some(c=>c.owners.length===2)")
            self.assertEqual(page.locator('#pat [data-role=attack][data-score-id]').count(), 2)

    def test_written_overlap_roll_identical_heads_have_distinct_note_and_velocity_hits(self):
        from tests.test_tablature_sync import written_voice_song
        source = written_voice_song()
        source['samples'][1]['file'] = 'a.wav'
        for b in source['score']['patterns']['a']['beats']:
            b['written']['value'] = 4
            b['notes'][0].update(pitch=65, fret=1, velocity=95, volume=32)
        with self.page(api.to_yaml(source)) as (page, state, folder):
            before = (folder / 'song.yaml').read_bytes()
            page.evaluate("tab('pattern');setEdit(true);setFocus('all');setCursor(0,0,0,0)")
            page.wait_for_function('PAT.collisions?.length && PAT.score_positions?.length')
            self.assertEqual(page.locator('#pat [data-role=release]').count(), 2)
            page.evaluate('rollToggle()')
            for identity in ('long', 'short'):
                for host in ('roll', 'rollvel'):
                    roll_scroll(page, f'#{host} [data-score-id="first/{identity}"]')
                    target = page.locator(f'#{host} [data-score-id="first/{identity}"]')
                    self.assertTrue(target.evaluate("""e=>{const r=e.getBoundingClientRect();
                        return document.elementFromPoint(r.x+r.width/2,r.y+r.height/2)===e}"""))
                page.locator(f'#roll [data-score-id="first/{identity}"]').click()
                self.assertEqual(page.evaluate('CUR.score.note'), identity)
            for action in ('rollLength(0,6)', 'rollMove(0,4,66)'):
                page.evaluate('EDQ.err=null;' + action)
                self.assertIn('Choose a source note', page.evaluate('EDQ.err'))
                self.assertEqual((folder / 'song.yaml').read_bytes(), before)
            for identity in ('long', 'short'):
                target = page.locator(f'#roll [data-score-id="first/{identity}"]')
                page.evaluate('EDQ.err=null')
                target.click(button='right')
                page.wait_for_function("!EDQ.n && (EDQ.err||PAT.score_positions?.filter(p=>p.kind==='note').length===1)")
                self.assertIsNone(page.evaluate('EDQ.err'))
                self.assertEqual([n['id'] for b in state.song['score']['patterns']['a']['beats'] for n in b['notes']],
                                 ['short' if identity == 'long' else 'long'])
                page.click('#lv-undo')
                page.wait_for_function("!EDQ.n && PAT.score_positions?.filter(p=>p.kind==='note').length===2")
                self.assertEqual((folder / 'song.yaml').read_bytes(), before)
            page.locator('#rollvel [data-score-id="first/short"]').click()
            page.wait_for_function("!EDQ.n && PAT.score_positions?.some(p=>p.note==='short'&&p.volume!==32)")
            notes = {n['id']: n for b in state.song['score']['patterns']['a']['beats'] for n in b['notes']}
            self.assertEqual(notes['long']['volume'], 32)
            page.click('#lv-undo')
            page.wait_for_function("!EDQ.n && PAT.score_positions?.every(p=>p.kind!=='note'||p.volume===32)")
            self.assertEqual((folder / 'song.yaml').read_bytes(), before)

    def test_written_overlap_release_can_navigate_to_a_head_in_another_order(self):
        from tests.test_tablature_sync import written_voice_song
        from tests.test_tablature import beat, note
        source = written_voice_song()
        source['samples'][1]['file'] = 'a.wav'
        source['score']['patterns']['a']['beats'][0]['written']['value'] = 1
        source['score']['patterns']['b']['beats'] = [
            beat('tail', [0, 1], [note('tail', 65, 1, 1)]),
            beat('other', [0, 1], [note('other', 65, 1, 1)], value=2, voice=1)]
        source['score']['ties'] = [dict(
            **{'from': dict(occurrence='first', note='long')},
            to=dict(occurrence='second', note='tail'))]
        with self.page(api.to_yaml(source)) as (page, state, folder):
            self.assertFalse(state.error, state.error)
            before = (folder / 'song.yaml').read_bytes()
            page.evaluate("tab('pattern');setEdit(true);setCursor(1,12,0,0);showPattern(1)")
            page.wait_for_function("PAT.occurrence==='second' && PAT.bindings?.some(b=>b.note==='long'&&b.sounding_overlap)")
            chip = page.locator('#pat [data-role=release][data-score-id="first/long"]')
            self.assertEqual(chip.count(), 1)
            chip.click()
            page.wait_for_function("PAT.occurrence==='first' && CUR.score?.id==='first/long'")
            self.assertEqual(page.evaluate('[CUR.o,CUR.score.readonly]'), [0, True])
            page.keyboard.press('Delete')
            self.assertEqual((folder / 'song.yaml').read_bytes(), before)

    def test_chord_generation_settings_order_draft_library_annotation_and_notes(self):
        from tests.test_tablature_sync import score_song
        from vulturetracker.chord_library import read_library
        source = score_song()
        source['samples'][1]['file'] = 'a.wav'
        source['patterns']['a']['data'] = ''
        source['score']['ties'] = []
        source['score']['patterns']['b']['beats'] = []
        with self.page(api.to_yaml(source)) as (page, state, folder):
            before = (folder / 'song.yaml').read_bytes()
            events = json.loads(json.dumps(state.mod.native_score['plan']['events']))
            page.evaluate("tab('tab');setEdit(true)")
            page.wait_for_selector('.vt-tab-grid [data-note=e]')
            page.click('.vt-tab-grid [data-note=e]')
            page.click('[data-action=chord-diagram]')
            page.fill('[data-ui=chord-name]', 'Keep authored label')
            page.click('[data-ui=chord-generator] summary')
            self.assertTrue(page.is_disabled('[data-gen=extension_shift]'))
            for key, value in [('root', '1'), ('quality', 'm7'), ('bass', '4'), ('extension', '13'),
                               ('extension_shift', '1'), ('fifth_shift', '-1'), ('ninth_shift', '1'),
                               ('eleventh_shift', '-1'), ('sharp', 'false'), ('profile', 'inversions')]:
                page.select_option(f'[data-gen={key}]', value)
            page.fill('[data-gen=min_fret]', '3')
            page.fill('[data-gen=max_fret]', '7')
            page.fill('[data-gen=count]', '2')
            page.check('[data-gen=open_strings]')
            with page.expect_response('**/api/chord_generate') as response:
                page.click('[data-action=chord-generate]')
            result = response.value.json()
            self.assertNotIn('error', result, result)
            self.assertEqual(result['spec'], dict(root=1, quality='m7', bass=4, extension=13,
                extension_shift=1, fifth_shift=-1, ninth_shift=1, eleventh_shift=-1, add=False, sharp=False))
            self.assertEqual(result['settings'], dict(profile='inversions', min_fret=3, max_fret=7, open_strings=True, count=2))
            page.wait_for_function("!document.querySelector('[data-action=chord-generate]').disabled")
            page.check('[data-gen=add]')
            self.assertTrue(page.is_disabled('[data-gen=ninth_shift]'))
            self.assertTrue(page.is_disabled('[data-gen=eleventh_shift]'))
            page.select_option('[data-gen=quality]', 'dim')
            self.assertTrue(page.is_disabled('[data-gen=extension]'))
            self.assertFalse(page.is_checked('[data-gen=add]'))
            self.assertEqual(page.input_value('[data-gen=fifth_shift]'), '0')
            page.select_option('[data-gen=quality]', 'M')
            page.select_option('[data-gen=root]', '0')
            page.select_option('[data-gen=bass]', '')
            page.fill('[data-gen=min_fret]', '0')
            page.fill('[data-gen=max_fret]', '5')
            page.fill('[data-gen=count]', '3')
            page.uncheck('[data-gen=open_strings]')
            for profile in ('inversions', 'close-voiced', 'open-voiced', 'normal'):
                page.select_option('[data-gen=profile]', profile)
                with page.expect_response('**/api/chord_generate') as response:
                    page.click('[data-action=chord-generate]')
                result = response.value.json()
                self.assertNotIn('error', result, result)
                page.wait_for_function("!document.querySelector('[data-action=chord-generate]').disabled")
                self.assertEqual(result['settings']['profile'], profile)
                expected = result['chords']
                self.assertGreater(len(expected), 0)
                self.assertEqual(page.locator('[data-generated-index]').count(), len(expected))
                actual_frets = page.locator('[data-generated-index]').evaluate_all(
                    "es=>es.map(e=>[...e.querySelectorAll('svg [data-fret]')].sort((a,b)=>+a.dataset.string-+b.dataset.string).map(n=>+n.dataset.fret))")
                self.assertEqual(actual_frets, [c['frets'] for c in expected])
                self.assertEqual(page.input_value('[data-ui=chord-name]'), 'Keep authored label')
                self.assertEqual((folder / 'song.yaml').read_bytes(), before)
                self.assertEqual(len(state.history), 0)
            chosen = expected[0]
            page.click('[data-generated-index="0"]')
            self.assertEqual(page.input_value('[data-ui=chord-name]'), chosen['name'])
            self.assertEqual(page.input_value('[data-ui=chord-first]'), '0')
            self.assertEqual([page.input_value(f'[data-chord-string="{i}"]') for i in range(1,7)],
                             ['X' if f < 0 else str(f) for f in chosen['frets']])
            self.assertEqual((folder / 'song.yaml').read_bytes(), before)
            page.click('[data-ui=chord-library] summary')
            page.wait_for_function("document.querySelector('[data-ui=library-status]').textContent.includes('0 saved')")
            page.fill('[data-ui=library-name]', 'Generated choice')
            page.click('[data-action=library-add]')
            page.wait_for_function("document.querySelector('[data-ui=library-status]').textContent.startsWith('Library saved')")
            self.assertEqual(read_library()['chords'][0], {**chosen, 'name': 'Generated choice'})
            self.assertEqual(len(state.history), 0)
            page.locator('.vt-tab-chord button[type=submit]').click()
            self.settled(page, '!!SCORE.view.score.patterns.a.beats[0].chord')
            self.assertEqual(state.song['score']['patterns']['a']['beats'][0]['chord'], chosen)
            self.assertEqual(state.mod.native_score['plan']['events'], events)
            page.click('[data-action=undo]')
            self.settled(page, '!SCORE.view.score.patterns.a.beats[0].chord')
            self.assertEqual((folder / 'song.yaml').read_bytes(), before)
            page.click('[data-action=chord-diagram]')
            page.click('[data-action=chord-generate]')
            page.wait_for_selector('[data-generated-index="0"]')
            page.click('[data-generated-index="0"]')
            page.click('[data-action=chord-notes]')
            self.settled(page, '!!SCORE.view.score.patterns.a.beats[0].chord')
            notes = state.song['score']['patterns']['a']['beats'][0]['notes']
            tuning = source['score']['tracks']['guitar']['tuning']
            self.assertEqual([(n['string'], n['pitch']) for n in notes],
                             [(i+1, tuning[i]+f) for i, f in enumerate(chosen['frets']) if f >= 0])
            self.assertEqual(len(state.history), 1)
            saved = (folder / 'song.yaml').read_bytes()
            page.evaluate('async path=>{await openSong(path)}', str(folder / 'song.yaml'))
            page.evaluate("tab('tab');setEdit(true)")
            page.wait_for_selector('.vt-tab-grid [data-beat=chord]')
            page.click('.vt-tab-grid [data-beat=chord][data-string="1"]')
            page.click('[data-action=chord-diagram]')
            self.assertEqual(page.input_value('[data-ui=chord-name]'), chosen['name'])
            self.assertEqual((folder / 'song.yaml').read_bytes(), saved)

    def test_chord_generation_delayed_settings_target_revision_and_bounded_refusal(self):
        from tests.test_tablature_sync import score_song
        source = score_song()
        source['samples'][1]['file'] = 'a.wav'
        source['patterns']['a']['data'] = ''
        source['score']['ties'] = []
        source['score']['patterns']['b']['beats'] = []
        with self.page(api.to_yaml(source)) as (page, state, folder):
            before = (folder / 'song.yaml').read_bytes()
            page.evaluate("tab('tab');setEdit(true)")
            page.wait_for_selector('.vt-tab-grid [data-note=e]')
            page.click('.vt-tab-grid [data-note=e]')
            page.click('[data-action=chord-diagram]')
            page.click('[data-ui=chord-generator] summary')
            page.fill('[data-ui=chord-name]', 'Draft')
            pending = []
            page.route('**/api/chord_generate', lambda route: pending.append(route))
            for change in ('settings', 'closed'):
                with page.expect_request('**/api/chord_generate'):
                    page.click('[data-action=chord-generate]')
                page.wait_for_function("document.querySelector('[data-action=chord-generate]').disabled")
                held = pending.pop()
                response = held.fetch()
                self.assertEqual(response.status, 200)
                if change == 'settings':
                    page.select_option('[data-gen=profile]', 'inversions')
                else:
                    page.click('[data-action=close-chord-diagram]')
                    page.click('.vt-tab-grid [data-beat=tail][data-string="1"]')
                    page.click('[data-action=chord-diagram]')
                    page.fill('[data-ui=chord-name]', 'Reopened')
                with page.expect_response('**/api/chord_generate') as completed:
                    held.fulfill(response=response)
                self.assertIn('chords', completed.value.json())
                self.assertEqual(page.locator('[data-generated-index]').count(), 0)
            page.unroute('**/api/chord_generate')
            self.assertEqual((folder / 'song.yaml').read_bytes(), before)
            page.click('[data-action=chord-generate]')
            page.wait_for_selector('[data-generated-index="0"]')
            page.fill('[data-ui=beat-text]', 'Changed score')
            page.click('[data-action=beat-text]')
            self.settled(page, "SCORE.view.score.patterns.a.beats.at(-1).text==='Changed score'")
            changed = (folder / 'song.yaml').read_bytes()
            page.click('[data-generated-index="0"]')
            self.assertIn('song or generator settings changed', page.inner_text('[data-ui=generation-status]'))
            self.assertEqual(page.input_value('[data-ui=chord-name]'), 'Reopened')
            self.assertEqual((folder / 'song.yaml').read_bytes(), changed)
            self.assertEqual(len(state.history), 1)
        from tests.test_tablature import beat, note
        source['module']['channels'] = [dict(name=f'String {i}') for i in range(25)]
        source['score']['tracks']['guitar'].update(tuning=[64]*25, channels=list(range(25)), max_fret=25)
        source['score']['patterns']['a']['beats'] = [beat('dense', [0,1], [note('dense',64,1,0)])]
        with self.page(api.to_yaml(source)) as (page, state, folder):
            before = (folder / 'song.yaml').read_bytes()
            page.evaluate("tab('tab');setEdit(true)")
            page.wait_for_selector('.vt-tab-grid [data-note=dense]')
            page.click('.vt-tab-grid [data-note=dense]')
            page.click('[data-action=chord-diagram]')
            page.click('[data-ui=chord-generator] summary')
            page.click('[data-action=chord-generate]')
            page.wait_for_function("document.querySelector('[data-ui=generation-status]').textContent.includes('limit')")
            self.assertIn('narrow', page.inner_text('[data-ui=generation-status]').lower())
            self.assertEqual(page.locator('[data-generated-index]').count(), 0)
            self.assertEqual((folder / 'song.yaml').read_bytes(), before)
            self.assertEqual(len(state.history), 0)

    def test_chord_recognition_names_are_ordered_explicit_draft_only_and_spelled(self):
        from tests.test_tablature_sync import score_song
        source = score_song()
        source['samples'][1]['file'] = 'a.wav'
        source['score']['ties'] = []
        source['score']['patterns']['b']['beats'] = []
        with self.page(api.to_yaml(source)) as (page, state, folder):
            before = (folder / 'song.yaml').read_bytes()
            page.evaluate("tab('tab');setEdit(true)")
            page.wait_for_selector('.vt-tab-grid [data-note=e]')
            page.click('.vt-tab-grid [data-note=e]')
            page.click('[data-action=chord-diagram]')
            page.fill('[data-ui=chord-name]', 'My authored name')
            frets = [1, 2, 1, 3, 4, -1]
            for i, fret in enumerate(frets, 1):
                page.fill(f'[data-chord-string="{i}"]', str(fret) if fret >= 0 else 'X')
            for spelling, expected in [('sharp', 'C#'), ('flat', 'Db')]:
                page.select_option('[data-ui=recognition-spelling]', spelling)
                with page.expect_response('**/api/chord_recognize') as response:
                    page.click('[data-action=chord-recognize]')
                result = response.value.json()
                page.wait_for_function("document.querySelector('[data-ui=recognition-status]').textContent.includes('proposed name(s)')")
                names = [p['name'] for p in result['proposals']]
                self.assertEqual(names[0], expected)
                self.assertEqual(page.locator('[data-ui=recognized-name] option').all_text_contents()[1:], names)
                self.assertEqual(page.input_value('[data-ui=chord-name]'), 'My authored name')
                self.assertTrue(page.is_disabled('[data-action=recognition-apply]'))
                self.assertEqual((folder / 'song.yaml').read_bytes(), before)
                self.assertEqual(len(state.history), 0)
            page.select_option('[data-ui=recognized-name]', '0')
            page.click('[data-action=recognition-apply]')
            self.assertEqual(page.input_value('[data-ui=chord-name]'), 'Db')
            self.assertEqual([page.input_value(f'[data-chord-string="{i}"]') for i in range(1, 7)],
                             ['1', '2', '1', '3', '4', 'X'])
            self.assertEqual((folder / 'song.yaml').read_bytes(), before)
            self.assertEqual(len(state.history), 0)
            self.assertFalse((self.chord_library_dir / 'custom-chords.json').exists())
            for i in range(1, 7):
                page.fill(f'[data-chord-string="{i}"]', 'X')
            page.click('[data-action=chord-recognize]')
            page.wait_for_function("document.querySelector('[data-ui=recognition-status]').textContent.includes('No names found')")
            self.assertEqual(page.input_value('[data-ui=chord-name]'), 'Db')
            page.click('[data-action=close-chord-diagram]')
            self.assertEqual((folder / 'song.yaml').read_bytes(), before)

    def test_chord_recognition_rejects_delayed_changed_closed_and_stale_results(self):
        from tests.test_tablature_sync import score_song
        source = score_song()
        source['samples'][1]['file'] = 'a.wav'
        source['score']['ties'] = []
        source['score']['patterns']['b']['beats'] = []
        with self.page(api.to_yaml(source)) as (page, state, folder):
            before = (folder / 'song.yaml').read_bytes()
            page.evaluate("tab('tab');setEdit(true)")
            page.wait_for_selector('.vt-tab-grid [data-note=e]')
            page.click('.vt-tab-grid [data-note=e]')
            page.click('[data-action=chord-diagram]')
            for i, fret in enumerate([0, 1, 0, 2, 3, -1], 1):
                page.fill(f'[data-chord-string="{i}"]', str(fret) if fret >= 0 else 'X')
            pending = []
            page.route('**/api/chord_recognize', lambda route: pending.append(route))
            for changed in ('diagram', 'closed'):
                with page.expect_request('**/api/chord_recognize'):
                    page.click('[data-action=chord-recognize]')
                page.wait_for_function("document.querySelector('[data-action=chord-recognize]').disabled")
                held = pending.pop()
                response = held.fetch()
                self.assertEqual(response.status, 200)
                if changed == 'diagram':
                    page.fill('[data-ui=chord-name]', 'Edited while recognizing')
                else:
                    page.click('[data-action=close-chord-diagram]')
                    page.click('.vt-tab-grid [data-beat=tail][data-string="1"]')
                    page.click('[data-action=chord-diagram]')
                    page.fill('[data-ui=chord-name]', 'Reopened target')
                with page.expect_response('**/api/chord_recognize') as completed:
                    held.fulfill(response=response)
                self.assertIn('proposals', completed.value.json())
                self.assertEqual(page.locator('[data-ui=recognized-name] option').count(), 1)
                self.assertTrue(page.is_disabled('[data-action=recognition-apply]'))
                self.assertEqual(page.input_value('[data-ui=chord-name]'),
                                 'Edited while recognizing' if changed == 'diagram' else 'Reopened target')
            page.unroute('**/api/chord_recognize')
            self.assertEqual((folder / 'song.yaml').read_bytes(), before)
            self.assertEqual(len(state.history), 0)
            for i, fret in enumerate([0, 1, 0, 2, 3, -1], 1):
                page.fill(f'[data-chord-string="{i}"]', str(fret) if fret >= 0 else 'X')
            page.click('[data-action=chord-recognize]')
            page.wait_for_function("document.querySelector('[data-ui=recognition-status]').textContent.includes('proposed name(s)')")
            page.select_option('[data-ui=recognized-name]', '0')
            page.fill('[data-ui=beat-text]', 'Changed score')
            page.click('[data-action=beat-text]')
            self.settled(page, "SCORE.view.score.patterns.a.beats.at(-1).text==='Changed score'")
            changed = (folder / 'song.yaml').read_bytes()
            page.click('[data-action=recognition-apply]')
            self.assertIn('diagram or song changed', page.inner_text('[data-ui=recognition-status]'))
            self.assertEqual(page.input_value('[data-ui=chord-name]'), 'Reopened target')
            page.click('[data-action=chord-recognize]')
            self.assertIn('song changed', page.inner_text('[data-ui=recognition-status]'))
            self.assertEqual((folder / 'song.yaml').read_bytes(), changed)
            self.assertEqual(len(state.history), 1)

    def test_chord_library_lifecycle_draft_copy_cancel_and_song_history(self):
        from vulturetracker.chord_library import read_library
        with self.page(SONG) as (page, state, folder):
            before = (folder / 'song.yaml').read_bytes()
            page.evaluate("tab('tab');setEdit(true)")
            page.wait_for_selector('.vt-tab-grid [data-note=note-a]')
            page.click('.vt-tab-grid [data-note=note-a]')
            page.click('[data-action=chord-diagram]')
            page.fill('[data-ui=chord-name]', 'Draft only')
            page.fill('[data-chord-string="1"]', '0')
            page.fill('[data-chord-string="2"]', '1')
            page.click('[data-ui=chord-library] summary')
            page.wait_for_function("document.querySelector('[data-ui=library-status]').textContent.includes('0 saved')")
            self.assertIn('not tuning', page.inner_text('[data-ui=chord-library]'))
            self.assertIn('even if you cancel', page.inner_text('[data-ui=chord-library]'))
            self.assertFalse((self.chord_library_dir / 'custom-chords.json').exists())
            page.fill('[data-ui=library-name]', ' ')
            page.click('[data-action=library-add]')
            self.assertIn('nonblank', page.inner_text('[data-ui=library-status]'))
            page.fill('[data-ui=library-name]', 'Shape <one>')
            page.click('[data-action=library-add]')
            page.wait_for_function("document.querySelector('[data-ui=library-status]').textContent.startsWith('Library saved')")
            self.assertEqual(read_library()['chords'], [dict(name='Shape <one>', first_fret=0, frets=[0, 1])])
            self.assertEqual(page.input_value('[data-ui=chord-name]'), 'Draft only')
            self.assertEqual((folder / 'song.yaml').read_bytes(), before)
            self.assertEqual(len(state.history), 0)
            page.fill('[data-ui=library-name]', 'Renamed')
            page.click('[data-action=library-rename]')
            page.wait_for_function("document.querySelector('[data-ui=library-chord]').value==='Renamed'")
            self.assertEqual(read_library()['revision'], 2)
            saved_library = (self.chord_library_dir / 'custom-chords.json').read_bytes()
            page.click('[data-action=library-add]')
            page.wait_for_function("document.querySelector('[data-ui=library-status]').textContent.includes('already has that name')")
            self.assertEqual((self.chord_library_dir / 'custom-chords.json').read_bytes(), saved_library)
            page.click('[data-action=library-load]')
            self.assertEqual(page.input_value('[data-ui=chord-name]'), 'Renamed')
            page.fill('[data-chord-string="1"]', '3')
            self.assertEqual(read_library()['chords'][0]['frets'], [0, 1])
            page.click('[data-action=close-chord-diagram]')
            self.assertEqual((folder / 'song.yaml').read_bytes(), before)
            self.assertEqual(len(state.history), 0)
            page.reload()
            page.wait_for_function("typeof S!=='undefined' && S?.song?.facts")
            page.evaluate("tab('tab');setEdit(true)")
            # The reload drops the fixture's opened optional panels: open the inspector and grid again.
            page.wait_for_selector('.vt-tab-grid [data-note=note-a]', state='attached')
            page.evaluate("document.querySelector('.vt-tab-inspector').open=true;document.querySelector('.vt-tab-grid-details').open=true")
            page.click('.vt-tab-grid [data-note=note-a]')
            page.click('[data-action=chord-diagram]')
            page.click('[data-ui=chord-library] summary')
            page.wait_for_function("document.querySelector('[data-ui=library-status]').textContent.includes('1 saved')")
            page.select_option('[data-ui=library-chord]', 'Renamed')
            page.click('[data-action=library-load]')
            self.assertEqual(page.input_value('[data-chord-string="1"]'), '0')
            self.assertEqual(page.input_value('[data-ui=chord-first]'), '0')
            self.assertEqual((folder / 'song.yaml').read_bytes(), before)
            page.locator('.vt-tab-chord button[type=submit]').click()
            self.settled(page, "SCORE.view.score.patterns.verse.beats[0].chord?.name==='Renamed'")
            self.assertEqual(len(state.history), 1)
            page.click('[data-action=undo]')
            self.settled(page, '!SCORE.view.score.patterns.verse.beats[0].chord')
            self.assertEqual((folder / 'song.yaml').read_bytes(), before)
            self.assertEqual((self.chord_library_dir / 'custom-chords.json').read_bytes(), saved_library)
            page.click('[data-action=chord-diagram]')
            page.wait_for_function("document.querySelector('[data-ui=library-status]').textContent.includes('1 saved')")
            page.click('[data-action=library-remove]')
            page.wait_for_function("document.querySelector('[data-ui=library-status]').textContent.startsWith('Library saved')")
            self.assertEqual(read_library(), dict(version=1, revision=3, chords=[]))
            page.click('[data-action=close-chord-diagram]')
            self.assertEqual((folder / 'song.yaml').read_bytes(), before)
            self.assertEqual(len(state.history), 0)

    def test_chord_library_incompatible_shapes_stale_locked_and_corrupt_refuse(self):
        from vulturetracker.chord_library import edit_library, read_library
        from vulturetracker.fileio import lock_file, unlock_file
        source = api.from_yaml(SONG)
        source['score']['tracks']['guitar']['max_fret'] = 12
        with self.page(api.to_yaml(source)) as (page, state, folder):
            shapes = [dict(name='Three strings', first_fret=0, frets=[0, 1, -1]),
                      dict(name='High shape', first_fret=30, frets=[30, 31]),
                      dict(name='Valid shape', first_fret=0, frets=[0, 1])]
            for revision, chord in enumerate(shapes):
                edit_library(dict(op='add', revision=revision, chord=chord))
            before = (folder / 'song.yaml').read_bytes()
            page.evaluate("tab('tab');setEdit(true)")
            page.wait_for_selector('.vt-tab-grid [data-note=note-a]')
            page.click('.vt-tab-grid [data-note=note-a]')
            page.click('[data-action=chord-diagram]')
            page.fill('[data-ui=chord-name]', 'Keep draft')
            page.fill('[data-chord-string="1"]', '2')
            page.click('[data-ui=chord-library] summary')
            page.wait_for_function("document.querySelector('[data-ui=library-status]').textContent.includes('3 saved')")
            for name, message in [('Three strings', 'has 3 strings'), ('High shape', 'maximum fret 12')]:
                page.select_option('[data-ui=library-chord]', name)
                page.click('[data-action=library-load]')
                self.assertIn(message, page.inner_text('[data-ui=library-status]'))
                self.assertEqual(page.input_value('[data-ui=chord-name]'), 'Keep draft')
                self.assertEqual(page.input_value('[data-chord-string="1"]'), '2')
                self.assertEqual(page.locator('[data-ui=chord-strings] input').count(), 2)
            page.select_option('[data-ui=library-chord]', 'Valid shape')
            edit_library(dict(op='rename', revision=3, name='Valid shape', new_name='Concurrent'))
            path = self.chord_library_dir / 'custom-chords.json'
            concurrent = path.read_bytes()
            page.fill('[data-ui=library-name]', 'Wanted')
            page.click('[data-action=library-rename]')
            page.wait_for_function("document.querySelector('[data-ui=library-status]').textContent.includes('changed; refresh')")
            self.assertEqual(path.read_bytes(), concurrent)
            page.click('[data-action=library-refresh]')
            page.wait_for_function("document.querySelector('[data-ui=library-status]').textContent.includes('3 saved')")
            page.select_option('[data-ui=library-chord]', 'Concurrent')
            locked = lock_file(path.with_suffix('.lock'))
            self.assertIsNotNone(locked)
            try:
                page.click('[data-action=library-remove]')
                page.wait_for_function("document.querySelector('[data-ui=library-status]').textContent.includes('another app')")
                self.assertEqual(path.read_bytes(), concurrent)
            finally:
                unlock_file(locked)
            self.assertEqual(read_library()['revision'], 4)
            path.write_bytes(b'{')
            page.click('[data-action=library-refresh]')
            page.wait_for_function("document.querySelector('[data-ui=library-status]').textContent.includes('Cannot read')")
            self.assertTrue(page.is_disabled('[data-action=library-add]'))
            self.assertTrue(page.is_disabled('[data-action=library-load]'))
            self.assertEqual(path.read_bytes(), b'{')
            self.assertEqual(page.input_value('[data-ui=chord-name]'), 'Keep draft')
            self.assertEqual((folder / 'song.yaml').read_bytes(), before)
            self.assertEqual(len(state.history), 0)

    def test_tap_slap_pop_controls_mixed_voices_ties_print_history_reopen(self):
        from tests.test_tablature import beat, note
        source = api.from_yaml(SONG)
        source['patterns']['verse'] = dict(rows=48, data='')
        harmonic = dict(type='tapped', data=0)
        source['score']['patterns']['verse']['beats'] = [
            dict(beat('chord', [0, 1], [
                dict(note('hi', 64, 1, 0), harmonic=harmonic, velocity=79, fade_in=True),
                note('lo', 59, 2, 0)]), text='Keep cue'),
            beat('other', [0, 1], [note('other', 65, 1, 1)], voice=1),
            beat('tail', [1, 1], [dict(note('tail', 64, 1, 0), harmonic=harmonic, velocity=79)])]
        source['score']['ties'] = [{'from': dict(occurrence='occ-verse', note='hi'),
                                   'to': dict(occurrence='occ-verse', note='tail')}]
        with self.page(api.to_yaml(source)) as (page, state, folder):
            self.assertFalse(state.error, state.error)
            before = (folder / 'song.yaml').read_bytes()
            events = json.loads(json.dumps(state.mod.native_score['plan']['events']))
            page.evaluate("tab('tab');setEdit(true)")
            page.wait_for_selector('.vt-tab-grid [data-note=hi]')
            self.capture_engraving(page)
            page.click('.vt-tab-grid [data-note=hi]')
            self.assertIn('Tapped harmonic is separate', page.inner_text('#tab-editor'))
            page.select_option('[data-ui=tap-slap-pop]', 'tapping')
            page.click('[data-action=tap-slap-pop]')
            self.settled(page, 'SCORE.view.score.patterns.verse.beats[0].notes[0].tapping')
            engraving = 'tabRendered.tracks[0].staves[0].bars[0].voices'
            self.assertFalse(page.evaluate(engraving + '[0].beats[0].tap'))
            self.assertIn('Tap: string 1', page.evaluate(engraving + '[0].beats[0].text'))
            self.assertEqual(page.input_value('[data-ui=harmonic-type]'), 'tapped')
            self.assertEqual(state.song['score']['patterns']['verse']['beats'][0]['notes'][0]['harmonic'], harmonic)
            page.click('[data-action=chord]')
            self.assertEqual(page.input_value('[data-ui=tap-slap-pop]'), 'mixed')
            page.click('[data-action=tap-slap-pop]')
            self.assertIn('Choose None, Tap, Slap or Pop', page.inner_text('.vt-tab-status'))
            page.select_option('[data-ui=tap-slap-pop]', 'slapping')
            page.click('[data-action=tap-slap-pop]')
            self.settled(page, 'SCORE.view.score.patterns.verse.beats[0].notes.every(n=>n.slapping&&!n.tapping)')
            self.assertEqual(page.evaluate(engraving + '[0].beats[0].slap'), True)
            self.assertIn('Keep cue', page.evaluate(engraving + '[0].beats[0].text'))
            self.assertEqual(page.evaluate(engraving + '[0].beats[0].tap'), False)
            page.click('.vt-tab-grid [data-note=lo]')
            page.select_option('[data-ui=tap-slap-pop]', 'popping')
            page.click('[data-action=tap-slap-pop]')
            self.settled(page, 'SCORE.view.score.patterns.verse.beats[0].notes[1].popping')
            self.assertIn('Slap: string 1', page.evaluate(engraving + '[0].beats[0].text'))
            self.assertIn('Pop: string 2', page.evaluate(engraving + '[0].beats[0].text'))
            self.assertFalse(page.evaluate(engraving + '[0].beats[0].slap'))
            page.select_option('[data-ui=voice]', index=1)
            page.click('.vt-tab-grid [data-note=other]')
            page.select_option('[data-ui=tap-slap-pop]', 'popping')
            page.click('[data-action=tap-slap-pop]')
            self.settled(page, 'SCORE.view.score.patterns.verse.beats[1].notes[0].popping')
            page.select_option('[data-ui=voice]', index=0)
            page.click('.vt-tab-grid [data-note=tail]')
            page.select_option('[data-ui=tap-slap-pop]', 'tapping')
            page.click('[data-action=tap-slap-pop]')
            self.settled(page, 'SCORE.view.score.patterns.verse.beats[2].notes[0].tapping')
            self.assertEqual(state.mod.native_score['plan']['events'], events)
            self.assertEqual(state.song['score']['ties'], source['score']['ties'])
            saved = (folder / 'song.yaml').read_bytes()
            flags = '.map(v=>v.beats.slice(0,2).map(b=>[b.tap,b.slap,b.pop]))'
            expected = [[[False, False, False], [True, False, False]],
                        [[False, False, True], [False, False, False]]]
            self.assertEqual(page.evaluate(engraving + flags), expected)
            preview = page.context.browser.new_page()
            preview.goto(self.print_url(page, state))
            self.print_ready(preview)
            self.capture_engraving(preview)
            preview.locator('form button[type=submit]').click()
            self.print_ready(preview)
            self.assertEqual(preview.evaluate(engraving + flags), expected)
            self.assertIn('Pop: string 2', preview.evaluate(engraving + '[0].beats[0].text'))
            preview.close()
            page.select_option('[data-ui=tap-slap-pop]', '')
            page.click('[data-action=tap-slap-pop]')
            self.settled(page, 'SCORE.view.score.patterns.verse.beats[2].notes[0].tapping===false')
            self.assertEqual(state.mod.native_score['plan']['events'], events)
            for i in range(6):
                revision = page.evaluate('SCORE.view.revision')
                page.click('[data-action=undo]')
                self.settled(page, f'SCORE.view.revision!=={json.dumps(revision)}')
                if i == 0:
                    self.assertEqual((folder / 'song.yaml').read_bytes(), saved)
            self.assertEqual((folder / 'song.yaml').read_bytes(), before)
            for _ in range(5):
                revision = page.evaluate('SCORE.view.revision')
                page.click('[data-action=redo]')
                self.settled(page, f'SCORE.view.revision!=={json.dumps(revision)}')
            self.assertEqual((folder / 'song.yaml').read_bytes(), saved)
            page.evaluate('async path=>{await openSong(path)}', str(folder / 'song.yaml'))
            page.evaluate("tab('tab');setEdit(true)")
            page.wait_for_selector('.vt-tab-grid [data-note=hi]')
            page.click('.vt-tab-grid [data-note=hi]')
            page.click('[data-action=chord]')
            self.assertEqual(page.input_value('[data-ui=tap-slap-pop]'), 'mixed')
            self.assertEqual((folder / 'song.yaml').read_bytes(), saved)

    def test_chord_note_all_muted_rest_noop_default_entry_and_clear(self):
        from tests.test_tablature_sync import score_song
        from tests.test_tablature import beat
        source = score_song()
        source['samples'][1]['file'] = 'a.wav'
        source['patterns']['a']['data'] = ''
        source['score']['ties'] = []
        source['score']['patterns']['a']['beats'] = [beat('rest', [0, 1], [])]
        source['score']['patterns']['b']['beats'] = []
        with self.page(api.to_yaml(source)) as (page, state, folder):
            self.assertFalse(state.error, state.error)
            before = (folder / 'song.yaml').read_bytes()
            initial_history = len(state.history)
            page.evaluate("tab('tab');setEdit(true)")
            page.wait_for_selector('.vt-tab-grid [data-beat=rest]')
            page.click('.vt-tab-grid [data-beat=rest][data-string="1"]')
            page.click('[data-action=chord-diagram]')
            page.fill('[data-ui=chord-name]', 'New muted annotation')
            self.assertIn('whole beat already rests', page.inner_text('[data-ui=chord-notes-preview]'))
            revision = page.evaluate('SCORE.view.revision')
            page.click('[data-action=chord-notes]')
            page.wait_for_selector('.vt-tab-chord', state='hidden')
            self.assertEqual(page.evaluate('SCORE.view.revision'), revision)
            self.assertEqual((folder / 'song.yaml').read_bytes(), before)
            self.assertEqual(len(state.history), initial_history)
            page.click('[data-action=chord-diagram]')
            page.fill('[data-chord-string="2"]', '0')
            page.click('[data-action=chord-notes]')
            self.settled(page, 'SCORE.view.score.patterns.a.beats[0].notes.length===1')
            n = state.song['score']['patterns']['a']['beats'][0]['notes'][0]
            self.assertEqual((n['pitch'], n['string'], n['velocity']), (59, 2, 95))
            page.click('[data-action=chord-diagram]')
            page.fill('[data-ui=chord-name]', 'Muted')
            page.fill('[data-chord-string="2"]', 'X')
            self.assertIn('clears the voice', page.inner_text('[data-ui=chord-notes-preview]'))
            page.click('[data-action=chord-notes]')
            self.settled(page, 'SCORE.view.score.patterns.a.beats[0].notes.length===0')
            self.assertEqual(state.song['score']['patterns']['a']['beats'][0]['chord'],
                             dict(name='Muted', first_fret=0, frets=[-1] * 6))
            page.click('[data-action=chord-diagram]')
            page.fill('[data-ui=chord-name]', 'Annotation only')
            page.fill('[data-ui=chord-velocity]', '128')
            page.locator('.vt-tab-chord button[type=submit]').click()
            self.settled(page, "SCORE.view.score.patterns.a.beats[0].chord.name==='Annotation only'")
            self.assertEqual(state.song['score']['patterns']['a']['beats'][0]['notes'], [])

    def test_chord_note_replace_preview_ties_pattern_sync_history_stale_and_reopen(self):
        from tests.test_tablature_sync import score_song
        from tests.test_tablature import beat, note
        from vulturetracker import server
        source = score_song()
        source['samples'][1]['file'] = 'a.wav'
        source['instruments'] = {1: dict(sample=1), 2: dict(sample=1)}
        source['patterns']['a']['data'] = ''
        source['orders'] = ['a', 'b', 'a']
        source['score']['order_ids'] = ['first', 'middle', 'again']
        source['score']['tracks']['guitar']['capo'] = 2
        source['score']['patterns']['b']['beats'] = []
        source['score']['patterns']['a']['beats'] = [
            dict(beat('target', [0, 1], [dict(note('old', 61, 2, 0), fade_in=True, velocity=31, instrument=2)]), text='Keep cue'),
            beat('other', [0, 1], [note('replace-other', 66, 1, 0), note('keep-other', 57, 3, 0)], voice=1),
            beat('tail', [1, 1], [dict(note('tail', 61, 2, 0), velocity=31, instrument=2)]),
            beat('other-tail', [1, 1], [note('other-tail', 66, 1, 0)], voice=1)]
        source['score']['ties'] = [
            {'from': dict(occurrence=o, note=a), 'to': dict(occurrence=o, note=b)}
            for o in ('first', 'again') for a, b in [('old', 'tail'), ('replace-other', 'other-tail')]]
        with self.page(api.to_yaml(source)) as (page, state, folder):
            self.assertFalse(state.error, state.error)
            before = (folder / 'song.yaml').read_bytes()
            initial_history = len(state.history)
            page.evaluate("tab('tab');setEdit(true)")
            # The controls mount before the initial score request restores the
            # tracker caret (voice 2 here). Choose voice 1 after that restore.
            page.wait_for_function('SCORE.view && !SCORE.fetching')
            page.select_option('[data-ui=voice]', index=0)
            page.click('.vt-tab-grid [data-note=old]')
            page.click('[data-action=chord-diagram]')
            self.assertEqual(page.input_value('[data-ui=chord-velocity]'), '95')
            page.fill('[data-ui=chord-name]', 'Authored voicing')
            for i, fret in enumerate([1, -1, -1, 2, -1, -1], 1):
                page.fill(f'[data-chord-string="{i}"]', 'X' if fret < 0 else str(fret))
            preview = page.inner_text('[data-ui=chord-notes-preview]')
            for expected in ('voice 1', 'preserve duration 1/4', 'track instrument 1',
                             '2 affected occurrence(s)', 'voice 2 string 1 (replace-other)', 'notes and their effects'):
                self.assertIn(expected, preview)
            self.assertNotIn('string 3 (keep-other)', preview)
            self.assertIn('4 affected tie(s)', page.inner_text('[data-ui=chord-ties-preview]'))
            page.fill('[data-ui=chord-velocity]', '128')
            page.click('[data-action=chord-notes]')
            self.assertIn('integer from 0 to 127', page.inner_text('[data-ui=chord-status]'))
            self.assertEqual((folder / 'song.yaml').read_bytes(), before)
            page.fill('[data-ui=chord-velocity]', '79')
            page.click('[data-action=chord-notes]')
            page.wait_for_function("document.querySelector('[data-ui=chord-status]').textContent.includes('remove_ties')")
            self.assertEqual((folder / 'song.yaml').read_bytes(), before)
            self.assertEqual(len(state.history), initial_history)
            page.check('[data-ui=chord-remove-ties]')
            page.click('[data-action=chord-notes]')
            self.settled(page, "SCORE.view.score.patterns.a.beats[0].notes.length===2")
            beats = state.song['score']['patterns']['a']['beats']
            new_notes = beats[0]['notes']
            self.assertEqual([(n['string'], n['fret'], n['pitch'], n['velocity']) for n in new_notes],
                             [(1, 1, 67, 79), (4, 2, 54, 79)])
            self.assertTrue(all(set(n) == {'id', 'string', 'fret', 'pitch', 'velocity'} for n in new_notes))
            self.assertFalse({'old', 'replace-other'} & {n['id'] for n in new_notes})
            self.assertEqual(beats[0]['written'], source['score']['patterns']['a']['beats'][0]['written'])
            self.assertEqual(beats[0]['text'], 'Keep cue')
            self.assertEqual([n['id'] for n in beats[1]['notes']], ['keep-other'])
            self.assertEqual(state.song['score']['ties'], [])
            self.assertEqual(len(state.history), initial_history + 1)
            attacks = [e for e in state.mod.native_score['plan']['events'] if e['type'] == 'note_on'
                       and e['note'] in {n['id'] for n in new_notes}]
            self.assertEqual(sorted(e['pitch'] for e in attacks), [54, 54, 67, 67])
            saved = (folder / 'song.yaml').read_bytes()
            page.evaluate("tab('pattern');setCursor(0,0,0,0)")
            page.wait_for_function("PAT.score_positions?.some(p=>p.kind==='note'&&p.pitch===67)")
            self.assertEqual(page.evaluate('PAT.rows[0][0].slice(0,3)'), 'G-5')
            self.assertEqual(page.evaluate('PAT.rows[0][3].slice(0,3)'), 'F#4')
            self.assertEqual(page.evaluate('PAT.rows[0][2].slice(0,3)'), 'A-4')
            page.evaluate("tab('tab')")
            page.click('[data-action=undo]')
            self.settled(page, "SCORE.view.score.patterns.a.beats[0].notes[0].id==='old'")
            self.assertEqual((folder / 'song.yaml').read_bytes(), before)
            page.click('[data-action=redo]')
            self.settled(page, "SCORE.view.score.patterns.a.beats[0].notes.length===2")
            self.assertEqual((folder / 'song.yaml').read_bytes(), saved)
            page.click('.vt-tab-grid [data-beat=target][data-string="1"]')
            page.click('[data-action=chord-diagram]')
            self.assertEqual(page.input_value('[data-ui=chord-velocity]'), '79')
            self.assertFalse(page.is_checked('[data-ui=chord-remove-ties]'))
            page.fill('[data-ui=beat-text]', 'Changed while open')
            page.click('[data-action=beat-text]')
            self.settled(page, "SCORE.view.score.patterns.a.beats[0].text==='Changed while open'")
            changed = (folder / 'song.yaml').read_bytes()
            page.click('[data-action=chord-notes]')
            self.assertIn('song changed', page.inner_text('[data-ui=chord-status]'))
            self.assertEqual((folder / 'song.yaml').read_bytes(), changed)
            page.click('[data-action=close-chord-diagram]')
            page.click('[data-action=undo]')
            self.settled(page, "SCORE.view.score.patterns.a.beats[0].text==='Keep cue'")
            self.assertEqual((folder / 'song.yaml').read_bytes(), saved)
            page.evaluate('async path=>{await openSong(path)}', str(folder / 'song.yaml'))
            state = server.Handler.state
            page.evaluate("tab('tab');setEdit(true)")
            page.wait_for_selector('.vt-tab-grid [data-beat=target]')
            page.click('.vt-tab-grid [data-beat=target][data-string="1"]')
            page.click('[data-action=chord-diagram]')
            self.assertEqual(page.input_value('[data-ui=chord-name]'), 'Authored voicing')
            self.assertEqual([n['pitch'] for n in state.song['score']['patterns']['a']['beats'][0]['notes']], [67, 54])
            self.assertEqual((folder / 'song.yaml').read_bytes(), saved)

    def test_chord_diagram_editor_sparse_rest_preview_print_copy_clear_history_reopen(self):
        from tests.test_tablature_sync import score_song
        from tests.test_tablature import beat, note
        source = score_song()
        source['samples'][1]['file'] = 'a.wav'
        source['patterns']['a']['data'] = ''
        source['score']['ties'] = []
        source['score']['patterns']['b']['beats'] = []
        shape = dict(name='C', first_fret=0, frets=[0, 1, 0, 2, 3, -1])
        source['score']['patterns']['a']['beats'] = [
            beat('rest', [0, 1], []),
            dict(beat('sound', [0, 1], [note('n', 64, 1, 0)], voice=1), chord=shape)]
        with self.page(api.to_yaml(source)) as (page, state, folder):
            self.assertFalse(state.error, state.error)
            before = (folder / 'song.yaml').read_bytes()
            events = json.loads(json.dumps(state.mod.native_score['plan']['events']))
            notes = [b['notes'] for b in source['score']['patterns']['a']['beats']]
            page.evaluate("tab('tab');setEdit(true)")
            page.wait_for_selector('[data-ui=voice]')
            page.select_option('[data-ui=voice]', index=0)
            page.wait_for_selector('.vt-tab-grid [data-beat=rest]')
            self.capture_engraving(page)
            page.select_option('[data-ui=track]', 'guitar')
            page.click('.vt-tab-grid [data-beat=rest][data-string="1"]')
            page.click('[data-action=chord-diagram]')
            self.assertEqual(page.input_value('[data-ui=chord-name]'), 'C')
            self.assertEqual(page.input_value('[data-ui=chord-first]'), '0')
            self.assertEqual(page.locator('[data-ui=chord-strings] input').evaluate_all(
                'es=>es.map(e=>[e.dataset.chordString,e.value])'),
                [['6', 'X'], ['5', '3'], ['4', '2'], ['3', '0'], ['2', '1'], ['1', '0']])
            preview = '[data-ui=chord-preview]'
            self.assertEqual(page.locator(preview + ' [data-string="1"]').text_content(), 'O')
            self.assertEqual(page.locator(preview + ' [data-string="6"]').text_content(), 'X')
            self.assertGreater(float(page.get_attribute(preview + ' [data-string="1"]', 'x')),
                               float(page.get_attribute(preview + ' [data-string="6"]', 'x')))
            self.assertIn('saved first fret remains 0', page.inner_text('[data-ui=chord-status]'))
            page.fill('[data-ui=chord-name]', 'Cancelled')
            page.click('[data-action=close-chord-diagram]')
            self.assertEqual((folder / 'song.yaml').read_bytes(), before)
            self.assertNotIn('chord', state.song['score']['patterns']['a']['beats'][0])
            page.click('[data-action=chord-diagram]')
            page.fill('[data-ui=chord-first]', '8')
            page.locator('.vt-tab-chord button[type=submit]').click()
            self.assertIn('five-fret window', page.inner_text('[data-ui=chord-status]'))
            self.assertEqual((folder / 'song.yaml').read_bytes(), before)
            high = dict(name='High C', first_fret=8, frets=[8, 10, 8, 9, 10, -1])
            page.fill('[data-ui=chord-name]', high['name'])
            for i, fret in enumerate(high['frets'], 1):
                page.fill(f'[data-chord-string="{i}"]', 'X' if fret == -1 else str(fret))
            self.assertEqual(page.get_attribute(preview + ' circle[data-string="1"]', 'cy'), '50')
            self.assertGreater(float(page.get_attribute(preview + ' circle[data-string="1"]', 'cx')),
                               float(page.get_attribute(preview + ' [data-string="6"]', 'x')))
            page.locator('.vt-tab-chord button[type=submit]').click()
            self.settled(page, "SCORE.view.score.patterns.a.beats.every(b=>b.chord?.name==='High C')")
            self.assertTrue(all(b['chord'] == high for b in state.song['score']['patterns']['a']['beats']))
            self.assertEqual([b['notes'] for b in state.song['score']['patterns']['a']['beats']], notes)
            self.assertEqual(state.mod.native_score['plan']['events'], events)
            saved = (folder / 'song.yaml').read_bytes()
            engraving = 'tabRendered.tracks[0].staves[0]'
            self.assertEqual(page.evaluate(engraving + '.bars.flatMap(b=>b.voices.flatMap(v=>v.beats)).filter(b=>b.chordId).length'), 1)
            self.assertEqual(page.evaluate(engraving + '.bars[0].voices[0].beats[0].chord.strings'), high['frets'])
            print_page = page.context.browser.new_page()
            print_page.goto(self.print_url(page, state))
            self.print_ready(print_page)
            self.capture_engraving(print_page)
            print_page.locator('form button[type=submit]').click()
            self.print_ready(print_page)
            self.assertEqual(print_page.evaluate(engraving + '.bars.flatMap(b=>b.voices.flatMap(v=>v.beats)).filter(b=>b.chordId).map(b=>[b.voice.index,b.chord.name,b.chord.firstFret,b.chord.strings])'),
                             [[0, 'High C', 8, high['frets']]])
            print_page.close()
            page.click('[data-action=copy]')
            page.wait_for_function("document.querySelector('.vt-tab-status').textContent.startsWith('Copied')")
            page.fill('[data-ui=at]', '1')
            page.click('[data-action=go]')
            page.click('[data-action=select-none]')
            page.click('[data-action=paste-safe]')
            self.settled(page, 'SCORE.view.score.patterns.a.beats.length===3')
            copied = state.song['score']['patterns']['a']['beats'][-1]
            self.assertEqual(copied['chord'], high)
            self.assertEqual(copied['notes'], [])
            self.assertEqual(state.mod.native_score['plan']['events'], events)
            page.click('[data-action=undo]')
            self.settled(page, 'SCORE.view.score.patterns.a.beats.length===2')
            self.assertEqual((folder / 'song.yaml').read_bytes(), saved)
            page.select_option('[data-ui=voice]', index=1)
            page.click('.vt-tab-grid [data-note=n]')
            page.click('[data-action=chord-diagram]')
            self.assertEqual(page.input_value('[data-ui=chord-name]'), 'High C')
            page.fill('[data-ui=chord-name]', '')
            page.fill('[data-ui=chord-first]', '0')
            for i in range(1, 7):
                page.fill(f'[data-chord-string="{i}"]', 'X')
            self.assertEqual(page.locator(preview + ' [data-fret="-1"]').count(), 6)
            page.locator('.vt-tab-chord button[type=submit]').click()
            self.settled(page, "SCORE.view.score.patterns.a.beats.every(b=>b.chord?.name==='')")
            muted = (folder / 'song.yaml').read_bytes()
            self.assertTrue(all(b['chord'] == dict(name='', first_fret=0, frets=[-1] * 6)
                                for b in state.song['score']['patterns']['a']['beats']))
            self.assertEqual(state.mod.native_score['plan']['events'], events)
            page.click('[data-action=chord-diagram]')
            page.click('[data-action=remove-chord-diagram]')
            self.settled(page, 'SCORE.view.score.patterns.a.beats.every(b=>!b.chord)')
            self.assertEqual([b['notes'] for b in state.song['score']['patterns']['a']['beats']], notes)
            page.click('[data-action=undo]')
            self.settled(page, "SCORE.view.score.patterns.a.beats.every(b=>b.chord?.name==='')")
            self.assertEqual((folder / 'song.yaml').read_bytes(), muted)
            page.click('[data-action=undo]')
            self.settled(page, "SCORE.view.score.patterns.a.beats.every(b=>b.chord?.name==='High C')")
            self.assertEqual((folder / 'song.yaml').read_bytes(), saved)
            page.click('[data-action=undo]')
            self.settled(page, "SCORE.view.score.patterns.a.beats[1].chord?.name==='C'")
            self.assertEqual((folder / 'song.yaml').read_bytes(), before)
            page.click('[data-action=redo]')
            self.settled(page, "SCORE.view.score.patterns.a.beats.every(b=>b.chord?.name==='High C')")
            page.evaluate('async path=>{await openSong(path)}', str(folder / 'song.yaml'))
            page.evaluate("tab('tab');setEdit(true)")
            page.wait_for_selector('[data-ui=voice]')
            page.select_option('[data-ui=voice]', index=0)
            page.click('.vt-tab-grid [data-beat=rest][data-string="1"]')
            page.click('[data-action=chord-diagram]')
            self.assertEqual(page.input_value('[data-ui=chord-first]'), '8')
            self.assertEqual(page.input_value('[data-chord-string="1"]'), '8')
            self.assertEqual((folder / 'song.yaml').read_bytes(), saved)

    def test_fade_controls_sparse_chord_voice_tie_print_clear_history_and_reopen(self):
        from tests.test_tablature import beat, note
        source = api.from_yaml(SONG)
        source['patterns']['verse'] = dict(rows=48, data='')
        source['score']['patterns']['verse']['beats'] = [
            dict(beat('chord', [0, 1], [note('hi', 64, 1, 0), note('lo', 59, 2, 0)]), text='Keep cue'),
            beat('other', [0, 1], [note('other', 65, 1, 1)], voice=1),
            beat('tail', [1, 1], [note('tail', 64, 1, 0)])]
        source['score']['ties'] = [dict(
            **{'from': dict(occurrence='occ-verse', note='hi')},
            to=dict(occurrence='occ-verse', note='tail'))]
        with self.page(api.to_yaml(source)) as (page, state, folder):
            self.assertFalse(state.error, state.error)
            before = (folder / 'song.yaml').read_bytes()
            events = [{k: v for k, v in event.items() if k != 'fade_in'}
                      for event in state.mod.native_score['plan']['events']]
            page.evaluate("tab('tab');setEdit(true)")
            page.wait_for_selector('.vt-tab-grid [data-note=hi]')
            self.capture_engraving(page)
            page.click('.vt-tab-grid [data-note=hi]')
            self.assertIn('whole track', page.inner_text('#tab-editor'))
            self.assertIn('playback and exports', page.inner_text('#tab-editor'))
            page.click('[data-action=fade-in]')
            self.settled(page, "SCORE.view.score.patterns.verse.beats[0].notes[0].fade_in")
            self.assertFalse(state.song['score']['patterns']['verse']['beats'][0]['notes'][1].get('fade_in'))
            self.assertFalse(state.song['score']['patterns']['verse']['beats'][1]['notes'][0].get('fade_in'))
            engraving = 'tabRendered.tracks[0].staves[0].bars[0].voices'
            self.assertEqual(page.evaluate(engraving + '[0].beats[0].fade'), 0)
            self.assertIn('Fade-in: string 1', page.evaluate(engraving + '[0].beats[0].text'))
            page.click('.vt-tab-grid th [data-at="0/1"]')
            self.assertEqual(page.get_attribute('[data-action=fade-in]', 'aria-pressed'), 'mixed')
            page.click('[data-action=fade-in]')
            self.settled(page, "SCORE.view.score.patterns.verse.beats[0].notes.every(n=>n.fade_in)")
            self.assertEqual(page.evaluate(engraving + '[0].beats[0].fade'), 1)
            page.click('[data-action=fade-in]')
            self.settled(page, "SCORE.view.score.patterns.verse.beats[0].notes.every(n=>n.fade_in===false)")
            page.select_option('[data-ui=voice]', index=1)
            self.assertEqual(page.locator('.vt-tab-grid [data-note=other]').count(), 1)
            page.click('.vt-tab-grid [data-note=other]')
            page.click('[data-action=fade-in]')
            self.settled(page, "SCORE.view.score.patterns.verse.beats[1].notes[0].fade_in")
            page.select_option('[data-ui=voice]', index=0)
            page.click('.vt-tab-grid [data-note=tail]')
            page.click('[data-action=fade-in]')
            self.settled(page, "SCORE.view.score.patterns.verse.beats[2].notes[0].fade_in")
            self.assertTrue(page.evaluate(engraving + '[0].beats[1].notes[0].isTieDestination'))
            self.assertEqual([{k: v for k, v in event.items() if k != 'fade_in'}
                              for event in state.mod.native_score['plan']['events'] if event['type'] != 'gain'], events)
            self.assertEqual(state.song['score']['ties'], source['score']['ties'])
            saved = (folder / 'song.yaml').read_bytes()
            preview = page.context.browser.new_page()
            preview.goto(self.print_url(page, state))
            self.print_ready(preview)
            self.capture_engraving(preview)
            preview.locator('form button[type=submit]').click()
            self.print_ready(preview)
            self.assertEqual(preview.evaluate(engraving + '.map(v=>v.beats.slice(0,2).map(b=>b.fade))'),
                             [[0, 1], [1, 0]])
            preview.close()
            page.click('[data-action=fade-in]')
            self.settled(page, "SCORE.view.score.patterns.verse.beats[2].notes[0].fade_in===false")
            page.select_option('[data-ui=voice]', index=1)
            page.click('.vt-tab-grid [data-note=other]')
            page.click('[data-action=fade-in]')
            self.settled(page, "SCORE.view.score.patterns.verse.beats.every(b=>b.notes.every(n=>!n.fade_in))")
            for i in range(7):
                revision = page.evaluate('SCORE.view.revision')
                page.click('[data-action=undo]')
                self.settled(page, f"SCORE.view.revision!=={json.dumps(revision)}")
                if i == 1:
                    self.assertEqual((folder / 'song.yaml').read_bytes(), saved)
            self.assertEqual((folder / 'song.yaml').read_bytes(), before)
            for _ in range(5):
                revision = page.evaluate('SCORE.view.revision')
                page.click('[data-action=redo]')
                self.settled(page, f"SCORE.view.revision!=={json.dumps(revision)}")
            self.assertEqual((folder / 'song.yaml').read_bytes(), saved)
            page.evaluate('async path=>{await openSong(path)}', str(folder / 'song.yaml'))
            page.evaluate("tab('tab');setEdit(true)")
            page.wait_for_selector('[data-ui=voice]')
            page.select_option('[data-ui=voice]', index=0)
            page.wait_for_selector('.vt-tab-grid [data-note=tail]')
            page.click('.vt-tab-grid [data-note=tail]')
            self.assertEqual(page.get_attribute('[data-action=fade-in]', 'aria-pressed'), 'true')
            self.assertEqual((folder / 'song.yaml').read_bytes(), saved)

    def test_stroke_controls_cohort_timing_pick_print_clear_undo_reopen(self):
        from tests.test_tablature import beat, note
        from vulturetracker import server
        source = api.from_yaml(SONG)
        source['module']['tempo'] = 120
        source['patterns']['verse'] = dict(rows=48, data='')
        source['score']['patterns']['verse']['beats'] = [
            dict(beat('chord', [0, 1], [note('hi', 64, 1, 0), note('lo', 59, 2, 0)]), text='Keep cue'),
            beat('rest', [0, 1], [], value=16, voice=1)]
        with self.muted_page(api.to_yaml(source)) as (page, state, folder):
            before = (folder / 'song.yaml').read_bytes()
            page.evaluate("tab('tab');setEdit(true)")
            page.wait_for_selector('.vt-tab-grid [data-note=hi]')
            self.capture_engraving(page)
            page.click('.vt-tab-grid [data-note=hi]')
            page.select_option('[data-ui=stroke-direction]', 'down')
            page.select_option('[data-ui=stroke-value]', '4')
            page.click('[data-action=stroke]')
            self.settled(page, "SCORE.view.score.patterns.verse.beats.every(b=>b.stroke?.direction==='down')")
            self.assertTrue(all(b['stroke'] == dict(direction='down', value=4)
                                for b in state.song['score']['patterns']['verse']['beats']))
            onsets = {e['note']: e['at'] for e in state.mod.native_score['plan']['events'] if e['type'] == 'note_on'}
            self.assertEqual(onsets, {'hi': [1, 32], 'lo': [0, 1]})  # Shortest written voice is a sixteenth rest.
            self.assertEqual(page.evaluate('CUR.row'), 0)
            self.assertEqual(page.evaluate('tabRendered.tracks[0].staves[0].bars[0].voices[0].beats[0].displayStart'), 0)
            self.assertEqual(page.evaluate('tabRendered.tracks[0].staves[0].bars[0].voices[0].beats[0].brushType'),
                             page.evaluate('alphaTab.model.BrushType.BrushDown'))
            # Inspect exact performed boundaries without moving the written cursor.
            frame = round(48000 * .5 / 32)
            marker = dict(o=0, occurrence='occ-verse', row=0, scoreFrame=frame - 1,
                          sampleRate=48000, factorQ=65536)
            highlighted = """p=>{SCORE.editor.setPlayhead(p);return ['hi','lo'].map(id=>
                document.querySelector('.vt-tab-grid [data-note='+id+']').classList.contains('playing'))}"""
            self.assertEqual(page.evaluate(highlighted, marker), [False, True])
            marker['scoreFrame'] = frame
            self.assertEqual(page.evaluate(highlighted, marker), [True, True])
            events = json.loads(json.dumps(state.mod.native_score['plan']['events']))
            page.select_option('[data-ui=pick-stroke]', 'up')
            page.click('[data-action=pick-stroke]')
            self.settled(page, "SCORE.view.score.patterns.verse.beats.every(b=>b.pick_stroke==='up')")
            self.assertEqual([{k: v for k, v in event.items() if k != 'pick_stroke'}
                              for event in state.mod.native_score['plan']['events']], events)
            saved = (folder / 'song.yaml').read_bytes()
            self.assertEqual(page.evaluate('tabRendered.tracks[0].staves[0].bars[0].voices[0].beats[0].pickStroke'),
                             page.evaluate('alphaTab.model.PickStroke.Up'))
            preview = page.context.browser.new_page()
            preview.goto(self.print_url(page, state))
            self.print_ready(preview)
            self.capture_engraving(preview)
            preview.locator('form button[type=submit]').click()
            self.print_ready(preview)
            self.assertEqual(preview.evaluate("""tabRendered.tracks[0].staves[0].bars[0].voices
                .map(v=>[v.beats[0].brushType,v.beats[0].pickStroke])"""), [[2, 1], [0, 0]])
            preview.close()
            page.select_option('[data-ui=pick-stroke]', '')
            page.click('[data-action=pick-stroke]')
            self.settled(page, 'SCORE.view.score.patterns.verse.beats.every(b=>!b.pick_stroke)')
            page.select_option('[data-ui=stroke-direction]', '')
            page.click('[data-action=stroke]')
            self.settled(page, 'SCORE.view.score.patterns.verse.beats.every(b=>!b.stroke)')
            self.assertEqual(api.from_yaml((folder / 'song.yaml').read_text(encoding='utf-8')), api.from_yaml(before.decode()))
            for remaining in (3, 2):
                revision = page.evaluate('SCORE.view.revision')
                page.click('[data-action=undo]')
                self.settled(page, f"SCORE.view.revision!=={json.dumps(revision)}")
                self.assertEqual(len(state.history), remaining)
            page.evaluate('async path=>{await openSong(path)}', str(folder / 'song.yaml'))
            state = server.Handler.state
            page.evaluate("tab('tab');setEdit(true)")
            page.wait_for_selector('.vt-tab-grid [data-note=hi]')
            page.click('.vt-tab-grid [data-note=hi]')
            self.assertEqual(page.input_value('[data-ui=stroke-direction]'), 'down')
            self.assertEqual(page.input_value('[data-ui=stroke-value]'), '4')
            self.assertEqual(page.input_value('[data-ui=pick-stroke]'), 'up')
            self.assertEqual((folder / 'song.yaml').read_bytes(), saved)

    def test_sparse_stroke_metadata_controls_both_voices_without_source_rewrite(self):
        from tests.test_tablature import beat, note
        for holder in (0, 1):
            with self.subTest(metadata_voice=holder):
                source = api.from_yaml(SONG)
                source['module']['tempo'] = 120
                source['patterns']['verse'] = dict(rows=48, data='')
                source['score']['patterns']['verse']['beats'] = beats = [
                    beat('chord', [0, 1], [note('hi', 64, 1, 0), note('lo', 59, 2, 0)]),
                    beat('rest', [0, 1], [], value=16, voice=1)]
                beats[holder].update(stroke=dict(direction='down', value=4), pick_stroke='up')
                with self.page(api.to_yaml(source)) as (page, state, folder):
                    before = (folder / 'song.yaml').read_bytes()
                    page.evaluate("tab('tab');setEdit(true)")
                    page.wait_for_selector('.vt-tab-grid [data-note=hi]')
                    self.capture_engraving(page)
                    page.select_option('[data-ui=track]', 'guitar')
                    page.click('.vt-tab-grid [data-note=hi]')
                    for voice in ('0', '1'):
                        page.select_option('[data-ui=voice]', index=int(voice))
                        self.assertEqual(page.input_value('[data-ui=stroke-direction]'), 'down')
                        self.assertEqual(page.input_value('[data-ui=stroke-value]'), '4')
                        self.assertEqual(page.input_value('[data-ui=pick-stroke]'), 'up')
                    self.assertEqual(page.evaluate("""tabRendered.tracks[0].staves[0].bars[0].voices
                        .map(v=>[v.beats[0].brushType,v.beats[0].pickStroke])"""), [[2, 1], [0, 0]])
                    page.select_option('[data-ui=voice]', index=0)
                    self.assertEqual(page.evaluate("""()=>{
                        SCORE.editor.setPlayhead({o:0,occurrence:'occ-verse',row:0,scoreFrame:749,
                            sampleRate:48000,factorQ:65536});
                        return ['hi','lo'].map(id=>document.querySelector('.vt-tab-grid [data-note='+id+']')
                            .classList.contains('playing'));
                    }"""), [False, True])
                    self.assertEqual((folder / 'song.yaml').read_bytes(), before)
                    self.assertNotIn('stroke', state.song['score']['patterns']['verse']['beats'][1 - holder])

    def test_repeated_context_live_ui_report_stays_under_server_limit(self):
        from tests.test_tablature_sync import repeat_song
        from tests.test_tablature import beat, note
        source = repeat_song()
        source['samples'][1]['file'] = 'a.wav'
        source['samples'][2] = dict(file='b.wav', loop=dict(start=0, end=RATE // 10))
        source['instruments'][2] = dict(sample=2)
        first = source['score']['patterns']['a']['beats'][0]['notes'][0]
        first.update(let_ring=True, trill=dict(fret=2, value=16), velocity=95)
        source['score']['patterns']['a']['beats'].extend([
            beat('other', [1, 1], [dict(note('other', 66, 1, 2), instrument=2, velocity=83)]),
            beat('rest', [2, 1], [])])
        with self.page(api.to_yaml(source)) as (page, state, folder):
            page.evaluate("tab('tab');setEdit(true)")
            page.wait_for_selector('.vt-tab-grid [data-note=head]')
            page.evaluate('async()=>{await lvPlay(0,0);LV.pos=null}')
            page.wait_for_function('LV.playing&&LV.pos?.scoreFrame>0&&playPos()?.playbackPlan&&!LV.err')
            raw_size = page.evaluate('JSON.stringify(playPos()).length')
            self.assertGreater(raw_size, 8192)
            # The old payload shape is concretely rejected by this same real server.
            bad_status = page.evaluate("""async()=>{
                const r=await fetch('/api/uistate',{method:'POST',headers:{'content-type':'application/json'},
                  body:JSON.stringify({song:S.song.path,state:{playback:{position:playPos()}}})});
                return r.status;
            }""")
            self.assertEqual(bad_status, 400)
            with page.expect_response(lambda r: r.url.endswith('/api/uistate')) as reported:
                page.evaluate('agReportUI()')
            self.assertEqual(reported.value.status, 200)
            report = reported.value.request.post_data_json['state']
            self.assertLess(len(json.dumps(report)), 8192)
            position = report['playback']['position']
            self.assertNotIn('playbackPlan', position)
            self.assertNotIn('visit', position)
            self.assertIsNotNone(position.get('playId'))
            self.assertIn(position['occurrence'], source['score']['order_ids'])
            print(f'repeat/context UI report: old position {raw_size} chars rejected HTTP 400; '
                  f'bounded state {len(json.dumps(report))} chars accepted HTTP 200')
            page.evaluate('lvStop()')

    def test_repeat_measure_controls_print_clear_refusal_undo_and_reopen(self):
        from tests.test_tablature_sync import repeat_song
        from vulturetracker import server
        source = repeat_song()
        source['samples'][1]['file'] = 'a.wav'
        with self.page(api.to_yaml(source)) as (page, state, folder):
            page.evaluate("tab('tab');setEdit(true)")
            page.wait_for_selector('.vt-tab-grid [data-note=head]')
            def measure(order, name):
                page.evaluate('async i=>{setCursor(i,0);await scoreRefresh()}', order)
                self.open_panel(page, 'measures')
                page.select_option('[data-ui=measure]', name)
            measure(1, 'b')
            self.assertEqual(page.input_value('[data-ui=measure-repeat-close]'), '1')
            page.fill('[data-ui=measure-repeat-close]', '2')
            page.check('[data-ending="1"]'); page.check('[data-ending="2"]')
            page.click('.vt-tab-measures button[type=submit]')
            self.settled(page, "SCORE.view.score.measures[1].repeat_close===2")
            self.assertEqual(state.song['score']['measures'][1]['endings'], [1, 2])
            self.assertEqual(state.song['orders'], ['a', 'b', 'c'])
            self.assertEqual(state.song['score']['patterns'], source['score']['patterns'])
            unchanged = (folder / 'song.yaml').read_bytes()
            # TGRepeatAlternativeDialog: after b's endings 1 and 2 (since a's repeat start), c can take 3..8 only.
            measure(2, 'c')
            self.assertEqual([page.is_disabled(f'[data-ending="{i}"]') for i in range(1, 9)], [True, True] + [False] * 6)
            measure(1, 'b')
            # An end that no longer matches the meter must be refused by the shared model (a new meter would
            # resize the bar instead, as TuxGuitar's time signature does).
            page.fill('[data-ui=measure-to]', '3')
            page.click('.vt-tab-measures button[type=submit]')
            page.wait_for_function("document.querySelector('.vt-tab-status').textContent.startsWith('Edit refused')")
            self.assertEqual((folder / 'song.yaml').read_bytes(), unchanged)
            self.assertEqual(len(state.history), 1)
            preview = page.context.browser.new_page()
            preview.goto(self.print_url(page, state))
            self.print_ready(preview)
            self.capture_engraving(preview)
            preview.locator('form button[type=submit]').click()
            self.print_ready(preview)
            self.assertEqual(preview.evaluate('tabRendered.masterBars.length'), 3)
            self.assertEqual(preview.evaluate('tabRendered.masterBars[1].repeatCount'), 3)
            self.assertEqual(preview.evaluate('tabRendered.masterBars[1].alternateEndings'), 3)
            preview.close()
            measure(0, 'a')
            self.assertTrue(page.is_checked('[data-ui=measure-repeat-open]'))
            measure(1, 'b')
            page.fill('[data-ui=measure-repeat-close]', '0')
            page.uncheck('[data-ending="1"]'); page.uncheck('[data-ending="2"]')
            page.click('.vt-tab-measures button[type=submit]')
            self.settled(page, "!SCORE.view.score.measures[1].repeat_close")
            self.assertNotIn('endings', state.song['score']['measures'][1])
            measure(0, 'a')
            page.uncheck('[data-ui=measure-repeat-open]')
            page.click('.vt-tab-measures button[type=submit]')
            self.settled(page, "!SCORE.view.score.measures[0].repeat_open")
            self.assertFalse(page.evaluate('!!S.song.facts.playback_orders'))
            for remaining in (2, 1):
                revision = page.evaluate('SCORE.view.revision')
                page.click('[data-action=undo]')
                self.settled(page, f"SCORE.view.revision!=={json.dumps(revision)}")
                self.assertEqual(len(state.history), remaining)
            page.evaluate('async path=>{await openSong(path)}', str(folder / 'song.yaml'))
            state = server.Handler.state
            page.evaluate("tab('tab');setEdit(true)")
            page.wait_for_selector('.vt-tab-grid [data-note=head]')
            measure(1, 'b')
            self.assertEqual(page.input_value('[data-ui=measure-repeat-close]'), '2')
            self.assertEqual([page.is_checked(f'[data-ending="{i}"]') for i in range(1, 9)], [True, True] + [False] * 6)
            self.assertEqual((folder / 'song.yaml').read_bytes(), unchanged)

    def test_repeat_live_pass_maps_to_shared_source_and_rejects_disjoint_loop(self):
        import copy
        source = api.from_yaml(SONG)
        source['module']['tempo'] = 120
        source['patterns']['verse'] = dict(rows=48, data='')
        source['patterns']['bridge'] = dict(rows=48, data='')
        source['orders'] = ['verse', 'bridge', 'verse']
        source['score']['order_ids'] = ['A', 'B', 'C']
        source['score']['patterns']['bridge'] = copy.deepcopy(source['score']['patterns']['verse'])
        source['score']['measures'] = [
            dict(id=oid, meter=[4, 4], **{'from': dict(occurrence=oid, at=[0, 1])},
                 to=dict(occurrence=oid, at=[4, 1]), **flags)
            for oid, flags in [('A', dict(repeat_open=True)), ('B', dict(repeat_close=1)), ('C', {})]]
        with self.page(api.to_yaml(source)) as (page, state, folder):
            page.evaluate("tab('tab');setEdit(true);setSpeed(1)")
            page.wait_for_selector('.vt-tab-grid [data-note=note-b]')
            self.assertEqual(page.evaluate('S.song.facts.orders.length'), 3)
            self.assertEqual(page.evaluate('S.song.facts.playback_orders.map(v=>v.source_occurrence)'),
                             ['A', 'B', 'A', 'B', 'C'])
            self.assertEqual(page.evaluate('posAt(4.6).revision'), state.text_sha())
            self.assertEqual(page.evaluate("""async()=>{
              const p=posAt(4.6),r=await fetch('/api/sounding/'+p.o+'?'+new URLSearchParams({
                play_id:p.playId,revision:p.revision}));
              return r.status;
            }"""), 200)
            page.evaluate("""async()=>{
              await lvStart();
              const v=S.song.facts.playback_orders[2];
              LV.pos={order:2,row:12,sourceOrder:0,sourceOccurrence:'A',sourceRow:12,
                sourceAt:[1,1],sourceScoreRow:[12,1],playId:v.id,pass:v.pass,revision:LV.planRevision};
              await lvPlay(0,12);
            }""")
            page.wait_for_function("LV.playing&&LV.pos?.order===2&&LV.pos?.row>=12&&LV.oi===0")
            self.assertEqual(page.evaluate('[playPos().o,playPos().playOrder,playPos().occurrence]'),
                             [0, 2, 'A'])
            page.wait_for_function("document.querySelector('.vt-tab-grid [data-beat=\"beat-b\"]')?.classList.contains('playing')")
            page.evaluate("agCue({action:'pause'},S.song.path)")
            page.evaluate("addNote()")
            page.wait_for_function("S.notes?.length===1")
            self.assertGreaterEqual(page.evaluate('S.notes[0].time'), 4.5)
            page.evaluate("lvStop()")
            self.assertEqual(page.evaluate('CUR.o'), 0)
            # Source A's two visits are separated by B: never broaden its pattern loop.
            page.evaluate("lvLoopPattern()")
            page.wait_for_function("LV.err?.includes('disjoint')")
            self.assertFalse(page.evaluate('LV.playing'))
            page.evaluate("""async()=>{
              lvPatLoop=false;
              await scoreCommit({op:'note_set',pattern:'verse',beat:'beat-b',
                note:{id:'note-b',pitch:63,string:2,fret:4}});
            }""")
            self.settled(page, "SCORE.view.score.patterns.verse.beats[1].notes[0].pitch===63")
            self.assertEqual(state.song['orders'], source['orders'])
            self.assertEqual(state.song['score']['order_ids'], ['A', 'B', 'C'])
            attacks = [e for e in state.mod.native_score['plan']['events']
                       if e['type'] == 'note_on' and e.get('note') == 'note-b' and e['pitch'] == 63]
            self.assertEqual(len(attacks), 3)  # Both A visits plus shared-pattern occurrence C.

    def test_repeat_fragments_live_offline_loop_note_and_source_edit(self):
        from tests.test_tablature_sync import repeat_fragment_song
        from vulturetracker import server
        source = repeat_fragment_song()
        source['samples'][1]['file'] = 'a.wav'
        with self.page(api.to_yaml(source)) as (page, state, folder):
            before = (folder / 'song.yaml').read_bytes()
            page.evaluate("tab('tab');setEdit(true);setSpeed(1)")
            page.wait_for_selector('.vt-tab-grid [data-note=later]')
            self.capture_engraving(page)
            page.select_option('[data-ui=track]', 'guitar')  # Re-select invalidates the notation render cache.
            page.wait_for_function('window.tabRendered?.masterBars.length===2')
            self.assertEqual(page.evaluate('S.song.facts.orders.length'), 1)
            self.assertEqual(page.evaluate('S.song.facts.playback_orders.map(v=>v.rows)'), [24] * 4)
            self.assertEqual(page.evaluate('S.song.facts.playback_orders.map(v=>v.source_from)'), [[0, 1], [2, 1]] * 2)
            self.assertEqual(page.evaluate('patternPlaybackLoop(0)'), {'from': [0, 0], 'to': [3, 23]})
            self.assertEqual(page.evaluate('tabRendered.masterBars.map(b=>[b.isRepeatStart,b.repeatCount])'),
                             [[True, 0], [False, 2]])
            self.assertEqual(page.evaluate("""(()=>{
              const v=S.song.facts.playback_orders[3],p=posAt(v.start+v.row_times[6]+.001);
              return [p.o,p.row,p.playOrder,p.playRow];
            })()"""), [0, 30, 3, 6])
            pattern = page.evaluate("""async()=>{
              const r=await fetch('/api/pattern/0?occurrence=first');return {status:r.status,body:await r.json()};
            }""")
            self.assertEqual(pattern['status'], 200, pattern)
            self.assertEqual(len(pattern['body']['rows']), 48)
            page.evaluate("""async()=>{
              await lvStart();const v=S.song.facts.playback_orders[3];
              LV.pos={order:3,row:6,sourceOrder:0,sourceOccurrence:'first',sourceRow:30,
                sourceAt:[5,2],sourceScoreRow:[30,1],playId:v.id,pass:v.pass,revision:LV.planRevision};
              await lvPlay(0,30);
            }""")
            page.wait_for_function("LV.playing&&LV.pos?.order===3&&LV.pos.sourceRow>=30&&LV.oi===0")
            page.wait_for_function("document.querySelector('.vt-tab-grid [data-beat=later]')?.classList.contains('playing')")
            self.assertEqual(page.evaluate('playPos().row-playPos().playRow'), 24)
            self.assertEqual(page.evaluate('sourceVisit(0,30).row'), 6)
            self.assertAlmostEqual(page.evaluate('timeAt(0,30)'),
                                   page.evaluate('S.song.facts.playback_orders[3].start+S.song.facts.playback_orders[3].row_times[6]'))
            page.evaluate("agCue({action:'pause'},S.song.path)")
            page.evaluate('addNote()')
            page.wait_for_function('S.notes?.length===1')
            saved = page.evaluate('S.notes[0]')
            self.assertEqual(saved['play_order'], 3)
            self.assertEqual(saved['row'] - saved['play_row'], 24)
            timing = state.facts['playback_orders'][3]
            self.assertAlmostEqual(saved['time'], timing['start'] + timing['row_times'][saved['play_row']], delta=.011)
            page.evaluate('lvStop();lvLoopPattern()')
            page.wait_for_function('LV.playing&&lvPatLoop')
            self.assertEqual(page.evaluate('JSON.parse(LV.sent.loop)'), {'from': [0, 0], 'to': [3, 23]})
            page.evaluate('lvStop()')
            page.click('.vt-tab-grid [data-note=later]')
            self.assertEqual(page.evaluate('CUR.row'), 24)
            page.evaluate("""async()=>{await scoreCommit({op:'note_set',pattern:'a',beat:'later',
              note:{id:'later',pitch:67,string:1,fret:3}})}""")
            self.settled(page, 'SCORE.view.score.patterns.a.beats[1].notes[0].pitch===67')
            self.assertEqual(state.song['orders'], ['a'])
            self.assertEqual(state.song['score']['order_ids'], ['first'])
            self.assertEqual([e['pitch'] for e in state.mod.native_score['plan']['events']
                              if e['type'] == 'note_on' and e['note'] == 'later'], [67, 67])
            page.click('[data-action=undo]')
            self.settled(page, 'SCORE.view.score.patterns.a.beats[1].notes[0].pitch===66')
            self.assertEqual((folder / 'song.yaml').read_bytes(), before)
            page.evaluate('async path=>{await openSong(path)}', str(folder / 'song.yaml'))
            state = server.Handler.state
            self.assertEqual(len(state.facts['playback_orders']), 4)
            self.assertEqual((folder / 'song.yaml').read_bytes(), before)

    def test_native_grace_controls_print_anchor_playback_clear_and_undo(self):
        from tests.test_tablature import beat, note
        source = api.from_yaml(SONG)
        source['module']['tempo'] = 120
        source['samples'][1]['loop'] = {'start': 0, 'end': RATE // 10}
        source['patterns']['verse'] = {'rows': 48, 'data': ''}
        source['score']['patterns']['verse']['beats'] = [
            beat('main', [1, 1], [dict(note('main-note', 64, 1, 0), staccato=True)], value=2)]
        with self.page(api.to_yaml(source)) as (page, state, folder):
            before = (folder / 'song.yaml').read_bytes()
            page.evaluate("tab('tab');setEdit(true);setSpeed(1)")
            page.wait_for_selector('.vt-tab-grid [data-note=main-note]')
            self.capture_engraving(page)
            page.click('.vt-tab-grid [data-note=main-note]')
            page.select_option('[data-ui=grace-kind]', 'grace')
            for field, value, message in [('grace-fret', '30', 'grace fret'),
                                           ('grace-fret', '', 'grace fret')]:
                page.fill(f'[data-ui={field}]', value)
                page.click('[data-action=grace]')
                self.assertIn(message, page.inner_text('.vt-tab-status'))
            page.fill('[data-ui=grace-fret]', '2')
            page.fill('[data-ui=grace-velocity]', '128')
            page.click('[data-action=grace]')
            self.assertIn('Grace velocity', page.inner_text('.vt-tab-status'))
            self.assertEqual((folder / 'song.yaml').read_bytes(), before)
            page.fill('[data-ui=grace-velocity]', '47')
            page.select_option('[data-ui=grace-timing]', 'on')
            page.select_option('[data-ui=grace-transition]', 'hammer')
            page.click('[data-action=grace]')
            self.settled(page, "SCORE.view.score.patterns.verse.beats[0].notes[0].grace?.on_beat")
            written = state.song['score']['patterns']['verse']['beats'][0]
            self.assertEqual((written['at'], written['written']['value']), ([1, 1], 2))
            self.assertTrue(written['notes'][0]['staccato'])
            self.assertNotIn('velocity', written['notes'][0])
            self.assertEqual(len(written['notes']), 1)
            events = state.mod.native_score['plan']['events']
            grace = next(e for e in events if e['type'] == 'note_on' and e.get('role') == 'grace')
            main = next(e for e in events if e['type'] == 'note_on' and e.get('role') != 'grace')
            self.assertEqual((grace['pitch'], grace['velocity'], grace['at']), (66, 47, [1, 1]))
            self.assertEqual(main['at'], [5, 4])
            self.assertEqual(grace['source_id'], main['id'])
            beats = 'tabRendered.tracks[0].staves[0].bars[0].voices[0].beats'
            self.assertEqual(page.evaluate(beats + '.filter(b=>b.graceType!==0).map(b=>b.notes[0].fret)'), [2])
            self.assertEqual(page.evaluate(beats + '.find(b=>b.graceType===0&&!b.isRest).displayStart'), 960)
            self.assertEqual(page.evaluate(beats + '.find(b=>b.graceType===0&&!b.isRest).duration'), 2)
            self.assertIn('hammer (notation only)', page.get_attribute('.vt-tab-grid [data-note=main-note]', 'title'))
            self.assertEqual(page.evaluate('CUR.row'), 12)
            preview = page.context.browser.new_page()
            preview.goto(self.print_url(page, state))
            self.print_ready(preview)
            self.capture_engraving(preview)
            preview.locator('form button[type=submit]').click()
            self.print_ready(preview)
            self.assertEqual(preview.evaluate(beats + '.filter(b=>b.graceType!==0).map(b=>b.notes[0].fret)'), [2])
            self.assertEqual(preview.evaluate(beats + '.find(b=>b.graceType===0&&!b.isRest).duration'), 2)
            preview.close()
            page.evaluate('async()=>{await lvPlay(0,0);LV.pos=null}')
            page.wait_for_function("""()=>{
                if(!LV.playing||LV.err||!LV.an||(LV.pos?.scoreFrame||0)<LV.ctx.sampleRate*.51)return false;
                const x=new Float32Array(LV.an.fftSize);LV.an.getFloatTimeDomainData(x);
                return Math.max(...x.map(Math.abs))>.0001;
            }""")
            self.assertIsNone(page.evaluate('LV.err'))
            page.evaluate('lvStop()')
            page.fill('[data-ui=grace-velocity]', '0')
            page.select_option('[data-ui=grace-value]', '64')
            page.select_option('[data-ui=grace-timing]', 'before')
            page.select_option('[data-ui=grace-transition]', 'bend')
            page.check('[data-ui=grace-dead]')
            page.click('[data-action=grace]')
            self.settled(page, "SCORE.view.score.patterns.verse.beats[0].notes[0].grace?.velocity===0")
            grace = state.song['score']['patterns']['verse']['beats'][0]['notes'][0]['grace']
            self.assertEqual(grace, dict(fret=2, value=64, velocity=0, on_beat=False, transition='bend', dead=True))
            page.select_option('[data-ui=grace-kind]', '')
            page.click('[data-action=grace]')
            self.settled(page, "!SCORE.view.score.patterns.verse.beats[0].notes[0].grace")
            self.assertTrue(state.song['score']['patterns']['verse']['beats'][0]['notes'][0]['staccato'])
            self.assertEqual(page.evaluate(beats + '.filter(b=>b.graceType!==0).length'), 0)
            self.assertEqual(len(state.history), 3)
            for _ in range(3):
                revision = page.evaluate('SCORE.view.revision')
                page.click('[data-action=undo]')
                self.settled(page, f"SCORE.view.revision!=={json.dumps(revision)}")
            self.assertEqual((folder / 'song.yaml').read_bytes(), before)

    def test_native_grace_chord_mixed_timing_clear_and_uniform_entry(self):
        from tests.test_tablature import beat, note
        source = api.from_yaml(SONG)
        source['patterns']['verse'] = {'rows': 48, 'data': ''}
        source['score']['patterns']['verse']['beats'] = [
            beat('chord', [1, 1], [
                dict(note('high', 64, 1, 0), grace=dict(fret=2, value=16, velocity=47, on_beat=True)),
                dict(note('low', 59, 2, 0), grace=dict(fret=1, value=64, velocity=31))])]
        with self.page(api.to_yaml(source)) as (page, state, folder):
            before = (folder / 'song.yaml').read_bytes()
            page.evaluate("tab('tab');setEdit(true)")
            page.wait_for_selector('.vt-tab-grid [data-note=high]')
            self.capture_engraving(page)
            page.select_option('[data-ui=track]', 'guitar')
            beats = 'tabRendered.tracks[0].staves[0].bars[0].voices[0].beats'
            self.assertEqual(page.evaluate(beats + '.filter(b=>b.graceType!==0).length'), 0)
            label = page.evaluate(beats + '.find(b=>!b.isRest).text')
            self.assertEqual(label, 'Grace (mixed timing)')
            self.assertIn('on beat',page.get_attribute('.vt-tab-grid [data-note=high]','title'))
            self.assertIn('before beat',page.get_attribute('.vt-tab-grid [data-note=low]','title'))
            page.click('.vt-tab-grid th [data-at="1/1"]')
            self.assertEqual(page.input_value('[data-ui=grace-kind]'), 'mixed')
            page.select_option('[data-ui=grace-kind]', '')
            page.click('[data-action=grace]')
            self.settled(page, "SCORE.view.score.patterns.verse.beats[0].notes.every(n=>!n.grace)")
            page.select_option('[data-ui=grace-kind]', 'grace')
            page.fill('[data-ui=grace-fret]', '3')
            page.fill('[data-ui=grace-velocity]', '31')
            page.select_option('[data-ui=grace-value]', '32')
            page.click('[data-action=grace]')
            self.settled(page, "SCORE.view.score.patterns.verse.beats[0].notes.every(n=>n.grace?.fret===3)")
            self.assertEqual(page.evaluate(beats + '.filter(b=>b.graceType!==0).map(b=>b.notes.map(n=>n.fret))'), [[3, 3]])
            self.assertEqual(len(state.history), 2)
            for _ in range(2):
                revision = page.evaluate('SCORE.view.revision')
                page.click('[data-action=undo]')
                self.settled(page, f"SCORE.view.revision!=={json.dumps(revision)}")
            self.assertEqual((folder / 'song.yaml').read_bytes(), before)

    def observe_score_dispatch(self, page, mode):
        """Observe the real ABI dispatch; AudioWorklet fetches bypass browser routing."""
        flag, dispatch, prefix = {'held': ('hasHolds', 'dispatchHeld', 'held'),
                                  'context': ('hasContexts', 'dispatchContexts', 'context')}[mode]
        worklet_url = f'{urlsplit(page.url).scheme}://{urlsplit(page.url).netloc}/engine-worklet.js'
        response = page.request.get(worklet_url)
        self.assertEqual(response.status, 200)
        script, anchor = response.text(), 'this.E = E;'
        self.assertEqual(script.count(anchor), 1)
        probe = """
                  const probePort=this.port, originalEvents=E.Song.prototype.scoreEvents;
                  E.Song.prototype.scoreEvents=function(...args){
                    const s=this.score;
                    if(!s?.FLAG)return originalEvents.apply(this,args);
                    const frame=s.frame, attacks=s.events.slice(s.index).filter(e=>e.frame===frame&&e.type==='note_on');
                    const dispatch=s.DISPATCH;let calls=0,result=null;
                    s.DISPATCH=(...values)=>{calls++;result=dispatch(...values);return result};
                    try{return originalEvents.apply(this,args)}
                    finally{
                      s.DISPATCH=dispatch;
                      if(calls&&attacks.length)probePort.postMessage({
                        type:'PREFIX-page-probe',frame,rate:s.rate,calls,result,
                        attacks:attacks.map(e=>({id:e.id,ch:e.ch,hold:e.hold===true,
                          source:e.source_instrument,head:e.source_id||e.id,role:e.role,
                          context:e.context,open:e.context_open,close:e.context_close,
                          pulse:e.pulse,layers:e.layers?.length||1})),
                        voices:[...s.voices].map(([id,h])=>({id,handles:(Array.isArray(h)?h:[h]).map(String)}))
                      });
                    }
                  };
        """.replace('FLAG', flag).replace('DISPATCH', dispatch).replace('PREFIX', prefix)
        page.evaluate("""script=>{
                const add=AudioWorklet.prototype.addModule;
                AudioWorklet.prototype.addModule=function(url,...args){
                    if(String(url)!=='/engine-worklet.js')return add.call(this,url,...args);
                    const blob=URL.createObjectURL(new Blob([script],{type:'text/javascript'}));
                    return add.call(this,blob,...args).finally(()=>URL.revokeObjectURL(blob));
                };
        }""", script.replace(anchor, anchor + probe))
        page.evaluate("""prefix=>{
            window[prefix+'PageProbes']=[];const old=lvMsg;
            lvMsg=m=>{if(m.type===prefix+'-page-probe')window[prefix+'PageProbes'].push(m);old(m)};
        }""", prefix)

    def test_native_let_ring_same_parent_held_dispatch_live_overlap_and_history(self):
        from tests.test_tablature_sync import let_ring_song
        source = let_ring_song()
        source['samples'][1]['file'] = 'a.wav'
        source['score']['patterns']['a']['beats'][0]['notes'][0].pop('let_ring')
        source['score']['patterns']['a']['beats'][1]['notes'][0].update(pitch=66, string=1, fret=2)
        written = json.loads(json.dumps(source['score']['patterns']['a']['beats']))
        with self.page(api.to_yaml(source)) as (page, state, folder):
            before = (folder / 'song.yaml').read_bytes()
            self.observe_score_dispatch(page, 'held')
            page.evaluate("""()=>{
                tab('tab');setEdit(true);setSpeed(1);
            }""")
            page.wait_for_selector('.vt-tab-grid [data-note=ring]')
            self.capture_engraving(page)
            page.click('.vt-tab-grid [data-note=ring]')
            page.click('[data-action=let-ring]')
            self.settled(page, "SCORE.view.score.patterns.a.beats[0].notes[0].let_ring")
            plan = state.mod.native_score['plan']
            attacks = [e for e in plan['events'] if e['type'] == 'note_on']
            releases = [e for e in plan['events'] if e['type'] == 'note_off']
            self.assertEqual([(e['id'], e['ch'], e['at'], e.get('hold', False)) for e in attacks],
                             [('first/ring', 0, [0, 1], True), ('first/next', 0, [1, 1], False)])
            self.assertTrue(all(e['at'] == [2, 1] for e in releases))
            self.assertTrue(all(e['velocity'] is None for e in attacks))
            pattern = page.evaluate("""async()=>{
                const r=await fetch('/api/pattern/0?occurrence=first');
                return {status:r.status,body:await r.json()};
            }""")
            self.assertEqual(pattern['status'], 200, pattern)
            self.assertNotIn('error', pattern['body'])
            actual = json.loads(json.dumps(state.song['score']['patterns']['a']['beats']))
            actual[0]['notes'][0].pop('let_ring')
            self.assertEqual(actual, written)
            self.assertEqual(page.evaluate('CUR.row'), 0)
            page.click('.vt-tab-grid [data-note=next]')
            self.assertEqual(page.evaluate('CUR.row'), 12)
            self.assertEqual(page.evaluate("""tabRendered.tracks[0].staves[0].bars[0].voices[0].beats
                .filter(b=>!b.isRest).map(b=>[b.displayStart,b.duration])"""), [[0, 4], [960, 4]])
            start = float(Fraction(*attacks[1]['seconds'])) + .08
            end = float(Fraction(*releases[0]['seconds'])) - .05
            page.evaluate('async()=>{await lvPlay(0,0);LV.pos=null}')
            page.wait_for_function("""({start,end})=>{
                const seconds=(LV.pos?.scoreFrame||0)/(LV.ctx?.sampleRate||1);
                if(!LV.playing||LV.err||!LV.an||seconds<start||seconds>end)return false;
                const x=new Float32Array(LV.an.fftSize);LV.an.getFloatTimeDomainData(x);
                return Math.max(...x.map(Math.abs))>.0001;
            }""", arg=dict(start=start, end=end))
            try:
                page.wait_for_function("heldPageProbes.some(p=>p.attacks.some(a=>a.id==='first/next'))", timeout=5000)
            except page_fixture.PlaywrightError as error:
                self.fail(f'{error}; '
                          f'diagnostics={page.evaluate("({probes:heldPageProbes,error:LV.err,position:LV.pos})")}')
            probes = page.evaluate('heldPageProbes')
            first = next(p for p in probes if any(a['id'] == 'first/ring' for a in p['attacks']))
            replacement = next(p for p in probes if any(a['id'] == 'first/next' for a in p['attacks']))
            self.assertEqual((first['calls'], first['result'], first['attacks'][0]['hold']), (1, 1, True))
            self.assertEqual((replacement['calls'], replacement['result']), (1, 1))
            voices = {v['id']: v['handles'] for v in replacement['voices']}
            self.assertEqual(set(voices), {'first/ring', 'first/next'})
            self.assertTrue(all(int(h) > 0 for handles in voices.values() for h in handles))
            self.assertNotEqual(voices['first/ring'], voices['first/next'])
            self.assertIsNone(page.evaluate('LV.err'))
            page.evaluate('lvStop()')
            self.assertEqual(len(state.history), 1)
            page.click('[data-action=undo]')
            self.settled(page, "!SCORE.view.score.patterns.a.beats[0].notes[0].let_ring")
            self.assertFalse(any(e.get('hold') for e in state.mod.native_score['plan']['events']))
            self.assertEqual((folder / 'song.yaml').read_bytes(), before)
            page.click('[data-action=redo]')
            self.settled(page, "SCORE.view.score.patterns.a.beats[0].notes[0].let_ring")
            self.assertTrue(any(e.get('hold') for e in state.mod.native_score['plan']['events']))
            page.click('[data-action=undo]')
            self.settled(page, "!SCORE.view.score.patterns.a.beats[0].notes[0].let_ring")
            self.assertEqual((folder / 'song.yaml').read_bytes(), before)

    def test_native_concurrent_head_context_dispatch_sources_history_and_reopen(self):
        from tests.test_tablature import beat, note
        from vulturetracker import server
        cases = {
            'trill': ('first', dict(let_ring=True, trill=dict(fret=2, value=16))),
            'picking': ('first', dict(let_ring=True, tremolo_picking=dict(value=16))),
            'before_grace': ('second', dict(grace=dict(fret=3, value=16, velocity=79))),
            'harmonic': ('first', dict(let_ring=True, harmonic=dict(type='semi', data=0))),
        }
        for kind, (edited, effects) in cases.items():
            with self.subTest(kind=kind):
                source = api.from_yaml(SONG)
                source['module']['tempo'] = 60
                source['patterns']['verse'] = dict(rows=48, data='')
                source['samples'][1]['loop'] = dict(start=0, end=RATE // 10)
                source['samples'][2] = dict(file='b.wav', name='Independent source',
                                            loop=dict(start=0, end=RATE // 10))
                source['instruments'] = {1: dict(sample=1), 2: dict(sample=2)}
                source['score']['patterns']['verse']['beats'] = [
                    beat('first', [0, 1], [dict(note('first', 64, 1, 0), instrument=1, velocity=95)]),
                    beat('second', [1, 1], [dict(note('second', 66, 1, 2), instrument=2, velocity=83)]),
                    beat('rest', [2, 1], [])]
                written = source['score']['patterns']['verse']['beats']
                with self.page(api.to_yaml(source)) as (page, state, folder):
                    before = (folder / 'song.yaml').read_bytes()
                    self.observe_score_dispatch(page, 'context')
                    page.evaluate("tab('tab');setEdit(true);setSpeed(1)")
                    page.wait_for_selector('.vt-tab-grid [data-note=first]')
                    self.capture_engraving(page)
                    page.evaluate("""async edit=>{await scoreCommit({
                        op:'note_set',pattern:'verse',beat:edit.id,note:edit
                    })}""", dict(id=edited, **effects))
                    self.settled(page, f"!!SCORE.view.score.patterns.verse.beats[{0 if edited == 'first' else 1}].notes[0].{next(iter(effects))}")
                    changed = (folder / 'song.yaml').read_bytes()
                    plan = state.mod.native_score['plan']
                    attacks = [e for e in plan['events'] if e['type'] == 'note_on']
                    self.assertTrue(all('context' in e for e in attacks), attacks)
                    first = [e for e in attacks if e['note'] == 'first']
                    second = [e for e in attacks if e['note'] == 'second']
                    self.assertEqual({e['ch'] for e in attacks}, {0})
                    self.assertEqual({e['source_instrument'] for e in first}, {1})
                    self.assertEqual({e['source_instrument'] for e in second}, {2})
                    self.assertEqual(len({e['context'] for e in first}), 1)
                    self.assertEqual(len({e['context'] for e in second}), 1)
                    self.assertNotEqual(first[0]['context'], second[0]['context'])
                    overlap = next(e for e in second if e.get('role') == 'grace') if kind == 'before_grace' else second[0]
                    start = float(Fraction(*overlap['seconds'])) + .04
                    first_offs = [e for e in plan['events'] if e['type'] == 'note_off' and e['note'] == 'first']
                    end = float(Fraction(*max(first_offs, key=lambda e: Fraction(*e['at']))['seconds'])) - .04
                    pattern = page.evaluate("""async()=>{
                        const r=await fetch('/api/pattern/0?occurrence=occ-verse');
                        return {status:r.status,body:await r.json()};
                    }""")
                    self.assertEqual(pattern['status'], 200, pattern)
                    self.assertNotIn('error', pattern['body'])
                    positions = [p for p in state.score_view()['positions'] if p['kind'] == 'note']
                    self.assertEqual([(p['note'], p['row'], p['end_row']) for p in positions],
                                     [('first', [0, 1], [12, 1]), ('second', [12, 1], [24, 1])])
                    for identity, row in (('first', 0), ('second', 12)):
                        page.click(f'.vt-tab-grid [data-note={identity}]')
                        self.assertEqual(page.evaluate('CUR.row'), row)
                    self.assertEqual(page.evaluate("""tabRendered.tracks[0].staves[0].bars[0].voices[0].beats
                        .filter(b=>!b.isRest&&!b.graceType).map(b=>b.displayStart)"""), [0, 960])
                    actual = json.loads(json.dumps(state.song['score']['patterns']['verse']['beats']))
                    for key in effects:
                        actual[0 if edited == 'first' else 1]['notes'][0].pop(key)
                    self.assertEqual(actual, written)
                    page.evaluate('async()=>{await lvPlay(0,0);LV.pos=null}')
                    page.wait_for_function("""({start,end})=>{
                        const t=(LV.pos?.scoreFrame||0)/(LV.ctx?.sampleRate||1);
                        if(!LV.playing||LV.err||!LV.an||t<start||t>end)return false;
                        const x=new Float32Array(LV.an.fftSize);LV.an.getFloatTimeDomainData(x);
                        return Math.max(...x.map(Math.abs))>.0001;
                    }""", arg=dict(start=start, end=end), timeout=10000)
                    with page.expect_response(lambda r: r.url.endswith('/api/uistate')) as reported:
                        page.evaluate('agReportUI()')
                    self.assertEqual(reported.value.status, 200)
                    report = reported.value.request.post_data_json['state']
                    self.assertLess(len(json.dumps(report)), 8192)
                    self.assertNotIn('playbackPlan', report['playback']['position'])
                    self.assertNotIn('visit', report['playback']['position'])
                    page.wait_for_function("id=>contextPageProbes.some(p=>p.attacks.some(a=>a.id===id))",
                                           arg=overlap['id'], timeout=5000)
                    probes = page.evaluate('contextPageProbes')
                    observed = next(p for p in probes if any(a['id'] == overlap['id'] for a in p['attacks']))
                    self.assertEqual((observed['calls'], observed['result']), (1, 1))
                    by_id = {e['id']: e for e in attacks}
                    voices = {v['id']: v['handles'] for v in observed['voices']}
                    old = [identity for identity in voices if by_id.get(identity, {}).get('context') == first[0]['context']]
                    self.assertTrue(old, observed)
                    self.assertIn(overlap['id'], voices)
                    old_handles = {int(h) for identity in old for h in voices[identity]}
                    new_handles = {int(h) for h in voices[overlap['id']]}
                    self.assertTrue(old_handles and new_handles and min(old_handles | new_handles) > 0)
                    self.assertFalse(old_handles & new_handles)
                    if kind == 'harmonic':
                        self.assertEqual(len(voices[first[0]['id']]), len(first[0]['layers']))
                        self.assertGreater(len(old_handles), 1)
                    if kind in ('trill', 'picking'):
                        later = next(e for e in first if e['frame'] > overlap['frame'])
                        page.wait_for_function("id=>contextPageProbes.some(p=>p.attacks.some(a=>a.id===id))",
                                               arg=later['id'], timeout=5000)
                        pulse = page.evaluate("""id=>contextPageProbes
                            .find(p=>p.attacks.some(a=>a.id===id))""", later['id'])
                        attack = next(e for e in pulse['attacks'] if e['id'] == later['id'])
                        self.assertEqual((pulse['calls'], pulse['result'], attack['source'], attack['context']),
                                         (1, 1, 1, first[0]['context']))
                        self.assertFalse(attack['open'])
                        self.assertIn(second[0]['id'], {v['id'] for v in pulse['voices']})
                    self.assertIsNone(page.evaluate('LV.err'))
                    page.evaluate('lvStop()')
                    self.assertEqual(len(state.history), 1)
                    page.click('[data-action=undo]')
                    self.settled(page, f"!SCORE.view.score.patterns.verse.beats[{0 if edited == 'first' else 1}].notes[0].{next(iter(effects))}")
                    self.assertEqual((folder / 'song.yaml').read_bytes(), before)
                    self.assertFalse(any('context' in e for e in state.mod.native_score['plan']['events']))
                    page.click('[data-action=redo]')
                    self.settled(page, f"!!SCORE.view.score.patterns.verse.beats[{0 if edited == 'first' else 1}].notes[0].{next(iter(effects))}")
                    page.evaluate('async path=>{await openSong(path)}', str(folder / 'song.yaml'))
                    state = server.Handler.state
                    page.evaluate("tab('tab');setEdit(true)")
                    page.wait_for_selector('.vt-tab-grid [data-note=first]')
                    self.assertEqual((folder / 'song.yaml').read_bytes(), changed)
                    self.assertEqual({e['source_instrument'] for e in state.mod.native_score['plan']['events']
                                      if e['type'] == 'note_on'}, {1, 2})
                    self.assertTrue(any('context' in e for e in state.mod.native_score['plan']['events']))

    def test_native_let_ring_note_chord_print_sustain_exclusions_clear_and_undo(self):
        from tests.test_tablature import beat, note
        source = api.from_yaml(SONG)
        source['module']['tempo'] = 120
        source['samples'][1]['loop'] = {'start': 0, 'end': RATE // 10}
        source['patterns']['verse'] = {'rows': 48, 'data': ''}
        source['score']['patterns']['verse']['beats'] = [
            beat('opening', [0, 1], [
                dict(note('high', 64, 1, 0), palm_mute=True),
                dict(note('low', 59, 2, 0), staccato=True)]),
            beat('following', [3, 1], [
                note('high-next', 65, 1, 1), note('low-next', 60, 2, 1)])]
        with self.page(api.to_yaml(source)) as (page, state, folder):
            self.assertIsNotNone(state.mod.native_score)
            before = (folder / 'song.yaml').read_bytes()
            page.evaluate("tab('tab');setEdit(true);setSpeed(1)")
            page.wait_for_selector('.vt-tab-grid [data-note=high]')
            self.assertTrue(page.evaluate('SCORE.view.native'))
            self.capture_engraving(page)
            page.click('.vt-tab-grid [data-note=high]')
            page.click('[data-action=let-ring]')
            self.settled(page, "SCORE.view.score.patterns.verse.beats[0].notes[0].let_ring")
            notes = state.song['score']['patterns']['verse']['beats'][0]['notes']
            self.assertFalse(notes[0].get('palm_mute'))
            self.assertFalse(notes[1].get('let_ring'))
            self.assertTrue(all('velocity' not in n for n in notes))
            self.assertIn('Let ring', page.get_attribute('.vt-tab-grid [data-note=high]', 'title'))
            rendered = 'tabRendered.tracks[0].staves[0].bars[0].voices[0].beats[0]'
            self.assertEqual(page.evaluate(rendered + '.notes.map(n=>n.isLetRing)'), [True, False])
            page.click('.vt-tab-grid th [data-at="0/1"]')
            self.assertEqual(page.get_attribute('[data-action=let-ring]', 'aria-pressed'), 'mixed')
            page.click('[data-action=let-ring]')
            self.settled(page, "SCORE.view.score.patterns.verse.beats[0].notes.every(n=>n.let_ring)")
            notes = state.song['score']['patterns']['verse']['beats'][0]['notes']
            self.assertTrue(all(not n.get('palm_mute') and not n.get('staccato') for n in notes))
            self.assertEqual(len(state.history), 2)
            self.assertEqual(page.evaluate(rendered + '.notes.map(n=>n.isLetRing)'), [True, True])
            releases = [e for e in state.mod.native_score['plan']['events']
                        if e['type'] == 'note_off' and e['note'] in ('high', 'low')]
            self.assertEqual(len(releases), 2)
            self.assertEqual({e['ch'] for e in releases}, {0, 1})
            self.assertTrue(all(Fraction(*e['at']) == 2 for e in releases))
            self.assertEqual([b['written']['value'] for b in
                              state.song['score']['patterns']['verse']['beats']], [4, 4])
            preview = page.context.browser.new_page()
            preview.goto(self.print_url(page, state))
            self.print_ready(preview)
            self.capture_engraving(preview)
            preview.locator('form button[type=submit]').click()
            self.print_ready(preview)
            self.assertEqual(preview.evaluate(rendered + '.notes.map(n=>n.isLetRing)'), [True, True])
            preview.close()
            # The next unmarked chord adds its written quarter, excluding the gap:
            # release is quarter 2 (1 s), before that chord at quarter 3 (1.5 s).
            # Check output after the original written end (.5 s), before release.
            page.evaluate('async()=>{await lvPlay(0,0);LV.pos=null}')
            page.wait_for_function("""()=>{
                const seconds=(LV.pos?.scoreFrame||0)/(LV.ctx?.sampleRate||1);
                if(!LV.playing||LV.err||!LV.an||seconds<.7||seconds>.9)return false;
                const x=new Float32Array(LV.an.fftSize);LV.an.getFloatTimeDomainData(x);
                return Math.max(...x.map(Math.abs))>.0001;
            }""")
            self.assertIsNone(page.evaluate('LV.err'))
            page.evaluate('lvStop()')
            for flag, action in [('palm_mute', 'palm-mute'), ('staccato', 'staccato')]:
                page.click(f'[data-action={action}]')
                self.settled(page, f"SCORE.view.score.patterns.verse.beats[0].notes.every(n=>n.{flag}&&!n.let_ring)")
                self.assertEqual(page.get_attribute('[data-action=let-ring]', 'aria-pressed'), 'false')
                self.assertEqual(page.evaluate(rendered + '.notes.map(n=>n.isLetRing)'), [False, False])
                page.click('[data-action=let-ring]')
                self.settled(page, f"SCORE.view.score.patterns.verse.beats[0].notes.every(n=>n.let_ring&&!n.{flag})")
            page.click('[data-action=let-ring]')
            self.settled(page, "SCORE.view.score.patterns.verse.beats[0].notes.every(n=>!n.let_ring)")
            self.assertEqual(page.evaluate(rendered + '.notes.map(n=>n.isLetRing)'), [False, False])
            self.assertNotIn('Let ring', page.get_attribute('.vt-tab-grid [data-note=high]', 'title') or '')
            releases = [e for e in state.mod.native_score['plan']['events']
                        if e['type'] == 'note_off' and e['note'] in ('high', 'low')]
            self.assertTrue(all(Fraction(*e['at']) == 1 for e in releases))
            self.assertEqual(len(state.history), 7)
            for remaining in range(6, -1, -1):
                revision = page.evaluate('SCORE.view.revision')
                page.click('[data-action=undo]')
                self.settled(page, f"SCORE.view.revision!=={json.dumps(revision)}")
                self.assertEqual(len(state.history), remaining)
            self.assertEqual((folder / 'song.yaml').read_bytes(), before)

    def test_native_repetition_entry_print_playback_exclusions_clear_and_undo(self):
        from tests.test_tablature import beat, note
        source = api.from_yaml(NATIVE_SONG)
        source['module']['tempo'] = 120
        source['samples'][1]['loop'] = {'start': 0, 'end': RATE // 10}
        source['orders'], source['score']['order_ids'], source['score']['ties'] = ['verse'], ['only'], []
        source['score']['tracks']['guitar']['tuning'] = [40]
        item = dict(note('repeated', 52, 1, 12), volume=23, vibrato=True,
                    bend={'points': [{'position': 0, 'value': 0}, {'position': 12, 'value': 4}]})
        source['score']['patterns']['verse']['beats'] = [beat('long', [0, 1], [item], value=1)]
        source['score']['measures'] = [dict(id='whole', meter=[4, 4], **{
            'from': dict(occurrence='only', at=[0, 1]), 'to': dict(occurrence='only', at=[4, 1])})]
        with self.page(api.to_yaml(source)) as (page, state, folder):
            before = (folder / 'song.yaml').read_bytes()
            page.evaluate("tab('tab');setEdit(true);setSpeed(1)")
            page.wait_for_selector('.vt-tab-grid [data-note=repeated]')
            self.capture_engraving(page)
            page.click('.vt-tab-grid [data-note=repeated]')
            page.select_option('[data-ui=repetition-type]', 'trill')
            page.fill('[data-ui=trill-fret]', '17')
            page.select_option('[data-ui=repetition-value]', '16')
            page.click('[data-action=repetition]')
            self.assertIn('explicit velocity', page.inner_text('.vt-tab-status'))
            self.assertEqual((folder / 'song.yaml').read_bytes(), before)
            page.fill('[data-ui=velocity]', '95')
            page.click('[data-action=velocity]')
            self.settled(page, "SCORE.view.score.patterns.verse.beats[0].notes[0].velocity===95")
            page.select_option('[data-ui=harmonic-type]', 'semi')
            page.click('[data-action=harmonic]')
            self.settled(page, "SCORE.view.score.patterns.verse.beats[0].notes[0].harmonic?.type==='semi'")
            saved = (folder / 'song.yaml').read_bytes()
            page.select_option('[data-ui=repetition-type]', 'trill')
            for invalid in ('-1', '30', '1.5', ''):
                page.fill('[data-ui=trill-fret]', invalid)
                page.click('[data-action=repetition]')
                self.assertIn('alternate fret', page.inner_text('.vt-tab-status'))
                self.assertEqual((folder / 'song.yaml').read_bytes(), saved)
            page.fill('[data-ui=trill-fret]', '17')
            self.assertEqual(page.locator('[data-ui=repetition-value] option').evaluate_all('xs=>xs.map(x=>x.value)'),
                             ['4', '8', '16', '32', '64'])
            page.select_option('[data-ui=repetition-value]', '16')
            page.click('[data-action=repetition]')
            self.settled(page, "SCORE.view.score.patterns.verse.beats[0].notes[0].trill?.fret===17")
            written = state.song['score']['patterns']['verse']['beats'][0]['notes'][0]
            self.assertEqual((written['pitch'], written['volume'], written['velocity']), (52, 23, 95))
            self.assertEqual(written['harmonic']['type'], 'semi')
            self.assertFalse(written.get('bend') or written.get('vibrato'))
            attacks = [e for e in state.mod.native_score['plan']['events'] if e['type'] == 'note_on']
            self.assertEqual([e['pitch'] for e in attacks], [52, 57] * 8)
            self.assertTrue(all(e['velocity'] == 95 and 'layers' not in e for e in attacks))
            rendered = 'tabRendered.tracks[0].staves[0].bars[0].voices[0].beats[0]'
            self.assertEqual(page.evaluate(rendered + '.notes.map(n=>[n.trillFret,n.trillSpeed])'), [[17, 16]])
            self.assertIn('Trill to fret 17 (1/16)', page.get_attribute('.vt-tab-grid [data-note=repeated]', 'title'))
            preview = page.context.browser.new_page()
            preview.goto(self.print_url(page, state))
            self.print_ready(preview)
            self.capture_engraving(preview)
            preview.locator('form button[type=submit]').click()
            self.print_ready(preview)
            self.assertEqual(preview.evaluate(rendered + '.notes.map(n=>[n.trillFret,n.trillSpeed])'), [[17, 16]])
            preview.close()
            page.evaluate('async()=>{await lvPlay(0,0)}')
            page.wait_for_function("""()=>{
                if(!LV.playing||LV.err||!LV.an||!LV.pos?.scoreFrame)return false;
                const x=new Float32Array(LV.an.fftSize);LV.an.getFloatTimeDomainData(x);
                return Math.max(...x.map(Math.abs))>.0001;
            }""")
            self.assertIsNone(page.evaluate('LV.err'))
            page.evaluate('lvStop()')
            page.select_option('[data-ui=repetition-type]', 'tremolo_picking')
            self.assertEqual(page.locator('[data-ui=repetition-value] option').evaluate_all('xs=>xs.map(x=>x.value)'),
                             ['8', '16', '32'])
            page.select_option('[data-ui=repetition-value]', '32')
            page.click('[data-action=repetition]')
            self.settled(page, "SCORE.view.score.patterns.verse.beats[0].notes[0].tremolo_picking?.value===32")
            self.assertNotIn('trill', state.song['score']['patterns']['verse']['beats'][0]['notes'][0])
            self.assertEqual(page.evaluate(rendered + '.tremoloSpeed'), 32)
            self.assertEqual(page.evaluate(rendered + '.tremoloPicking.marks'), 5)
            preview = page.context.browser.new_page()
            preview.goto(self.print_url(page, state))
            self.print_ready(preview)
            self.capture_engraving(preview)
            preview.locator('form button[type=submit]').click()
            self.print_ready(preview)
            self.assertEqual(preview.evaluate(rendered + '.tremoloSpeed'), 32)
            preview.close()
            page.select_option('[data-ui=repetition-type]', '')
            page.click('[data-action=repetition]')
            self.settled(page, "!SCORE.view.score.patterns.verse.beats[0].notes[0].tremolo_picking")
            self.assertEqual(page.evaluate(rendered + '.isTremolo'), False)
            self.assertEqual(state.song['score']['patterns']['verse']['beats'][0]['notes'][0]['harmonic']['type'], 'semi')
            # Enabling a conflicting effect clears repetition in the shared model.
            page.select_option('[data-ui=repetition-type]', 'trill')
            page.fill('[data-ui=trill-fret]', '17')
            page.click('[data-action=repetition]')
            self.settled(page, "!!SCORE.view.score.patterns.verse.beats[0].notes[0].trill")
            page.click('[data-action=vibrato]')
            self.settled(page, "SCORE.view.score.patterns.verse.beats[0].notes[0].vibrato")
            self.assertEqual(page.input_value('[data-ui=repetition-type]'), '')
            self.assertNotIn('trill', state.song['score']['patterns']['verse']['beats'][0]['notes'][0])
            self.assertEqual(len(state.history), 7)
            for remaining in range(6, -1, -1):
                revision = page.evaluate('SCORE.view.revision')
                page.click('[data-action=undo]')
                self.settled(page, f"SCORE.view.revision!=={json.dumps(revision)}")
                self.assertEqual(len(state.history), remaining)
            self.assertEqual((folder / 'song.yaml').read_bytes(), before)

    def test_native_repetition_chord_mixed_engraving_and_one_step_edits(self):
        from tests.test_tablature import beat, note
        source = api.from_yaml(SONG)
        source['patterns']['verse']['data'] = ''
        source['score']['patterns']['verse']['beats'] = [dict(beat('chord', [0, 1], [
            dict(note('high', 64, 1, 0), velocity=95, tremolo_picking={'value': 16}),
            dict(note('low', 59, 2, 0), velocity=95)]), text='Keep cue')]
        with self.page(api.to_yaml(source)) as (page, state, folder):
            before = (folder / 'song.yaml').read_bytes()
            page.evaluate("tab('tab');setEdit(true)")
            page.wait_for_selector('.vt-tab-grid [data-note=high]')
            self.capture_engraving(page)
            page.select_option('[data-ui=track]', 'guitar')
            rendered = 'tabRendered.tracks[0].staves[0].bars[0].voices[0].beats[0]'
            self.assertFalse(page.evaluate(rendered + '.isTremolo'))
            self.assertIn('Keep cue', page.evaluate(rendered + '.text'))
            self.assertIn('Tremolo picking: string 1 1/16', page.evaluate(rendered + '.text'))
            page.click('.vt-tab-grid th [data-at="0/1"]')
            self.assertEqual(page.input_value('[data-ui=repetition-type]'), 'mixed')
            page.select_option('[data-ui=repetition-type]', 'trill')
            page.fill('[data-ui=trill-fret]', '3')
            page.select_option('[data-ui=repetition-value]', '8')
            page.click('[data-action=repetition]')
            self.settled(page, "SCORE.view.score.patterns.verse.beats[0].notes.every(n=>n.trill?.value===8)")
            self.assertEqual(len(state.history), 1)
            self.assertEqual(page.evaluate(rendered + '.notes.map(n=>[n.trillValue,n.trillSpeed])'), [[67, 8], [62, 8]])
            page.select_option('[data-ui=repetition-type]', 'tremolo_picking')
            page.select_option('[data-ui=repetition-value]', '16')
            page.click('[data-action=repetition]')
            self.settled(page, "SCORE.view.score.patterns.verse.beats[0].notes.every(n=>n.tremolo_picking?.value===16)")
            self.assertEqual(len(state.history), 2)
            self.assertEqual(page.evaluate(rendered + '.tremoloSpeed'), 16)
            page.select_option('[data-ui=repetition-type]', '')
            page.click('[data-action=repetition]')
            self.settled(page, "SCORE.view.score.patterns.verse.beats[0].notes.every(n=>!n.trill&&!n.tremolo_picking)")
            self.assertEqual(len(state.history), 3)
            for _ in range(3):
                revision = page.evaluate('SCORE.view.revision')
                page.click('[data-action=undo]')
                self.settled(page, f"SCORE.view.revision!=={json.dumps(revision)}")
            self.assertEqual((folder / 'song.yaml').read_bytes(), before)

    def test_native_measure_swing_plan_print_clear_undo_and_reopen(self):
        from tests.test_tablature import beat, note
        from vulturetracker import server
        source = api.from_yaml(SONG)
        source['patterns']['verse'] = {'rows': 48, 'data': ''}
        source['score']['patterns']['verse']['beats'] = [
            beat(identity, at, [note(identity, pitch, 1, pitch - 64)], value=value)
            for identity, at, pitch, value in [
                ('e0', [0, 1], 64, 8), ('e1', [1, 2], 66, 8),
                ('s0', [1, 1], 67, 16), ('s1', [5, 4], 69, 16)]]
        measure = dict(id='whole', meter=[4, 4], marker=dict(title='Swing study', color='#123456'), **{
            'from': dict(occurrence='occ-verse', at=[0, 1]), 'to': dict(occurrence='occ-verse', at=[4, 1])})
        source['score']['measures'] = [measure]
        with self.page(api.to_yaml(source)) as (page, state, folder):
            before = (folder / 'song.yaml').read_bytes()
            page.evaluate("tab('tab');setEdit(true)")
            page.wait_for_selector('.vt-tab-grid [data-note=e0]')
            self.capture_engraving(page)
            self.open_panel(page, 'measures')
            page.select_option('[data-ui=measure]', 'whole')
            self.assertEqual(page.input_value('[data-ui=measure-swing]'), 'none')
            page.select_option('[data-ui=measure-swing]', 'eighth')
            page.click('.vt-tab-measures button[type=submit]')
            self.settled(page, "SCORE.view.score.measures[0].swing==='eighth'")
            self.assertEqual(state.song['score']['measures'], [dict(measure, swing='eighth')])
            self.assertEqual(state.song['score']['patterns'], source['score']['patterns'])
            def intervals():
                events = state.mod.native_score['plan']['events']
                offs = {e['id']: e['at'] for e in events if e['type'] == 'note_off'}
                return [(e['note'], e['at'], offs[e['id']]) for e in events if e['type'] == 'note_on']
            self.assertEqual(intervals(), [('e0', [0, 1], [2, 3]), ('e1', [2, 3], [1, 1]),
                                          ('s0', [1, 1], [5, 4]), ('s1', [5, 4], [3, 2])])
            second = next(p for p in state.mod.native_score['plan']['positions'] if p['note'] == 'e1')
            self.assertEqual((second['at'], second['sounding_start']), ([1, 2], [2, 3]))
            self.assertEqual(page.evaluate('tabRendered.masterBars[0].tripletFeel'),
                             page.evaluate('alphaTab.model.TripletFeel.Triplet8th'))
            self.assertEqual(page.evaluate("""tabRendered.tracks[0].staves[0].bars[0].voices[0].beats
                .filter(b=>!b.isRest).map(b=>b.displayStart)"""), [0, 480, 960, 1200])
            preview = page.context.browser.new_page()
            preview.goto(self.print_url(page, state))
            self.print_ready(preview)
            self.capture_engraving(preview)
            preview.locator('form button[type=submit]').click()
            self.print_ready(preview)
            self.assertEqual(preview.evaluate('tabRendered.masterBars[0].tripletFeel'),
                             preview.evaluate('alphaTab.model.TripletFeel.Triplet8th'))
            self.assertEqual(preview.evaluate('tabRendered.masterBars[0].section.text'), 'Swing study')
            preview.close()
            page.select_option('[data-ui=measure-swing]', 'sixteenth')
            page.click('.vt-tab-measures button[type=submit]')
            self.settled(page, "SCORE.view.score.measures[0].swing==='sixteenth'")
            self.assertEqual(intervals(), [('e0', [0, 1], [1, 2]), ('e1', [1, 2], [1, 1]),
                                          ('s0', [1, 1], [4, 3]), ('s1', [4, 3], [3, 2])])
            self.assertEqual(state.song['score']['measures'], [dict(measure, swing='sixteenth')])
            self.assertEqual(page.evaluate('tabRendered.masterBars[0].tripletFeel'),
                             page.evaluate('alphaTab.model.TripletFeel.Triplet16th'))
            page.select_option('[data-ui=measure-swing]', 'none')
            page.click('.vt-tab-measures button[type=submit]')
            self.settled(page, "!SCORE.view.score.measures[0].swing")
            self.assertEqual(state.song['score'], source['score'])
            self.assertEqual(page.evaluate('tabRendered.masterBars[0].tripletFeel'), 0)
            self.assertEqual(len(state.history), 3)
            page.click('[data-action=undo]')
            self.settled(page, "SCORE.view.score.measures[0].swing==='sixteenth'")
            page.evaluate('async path=>{await openSong(path)}', str(folder / 'song.yaml'))
            state = server.Handler.state
            page.evaluate("tab('tab');setEdit(true)")
            page.wait_for_selector('.vt-tab-grid [data-note=e0]')
            self.open_panel(page, 'measures')
            page.select_option('[data-ui=measure]', 'whole')
            self.assertEqual(page.input_value('[data-ui=measure-swing]'), 'sixteenth')
            self.assertEqual(state.song['score']['patterns'], source['score']['patterns'])
            for remaining in (1, 0):
                revision = page.evaluate('SCORE.view.revision')
                page.click('[data-action=undo]')
                self.settled(page, f"SCORE.view.revision!=={json.dumps(revision)}")
                self.assertEqual(len(state.history), remaining)
            self.assertEqual((folder / 'song.yaml').read_bytes(), before)

    def test_tempo_units_controls_exact_undo_and_print(self):
        source = self.four_bar_song(); source['module']['tempo'] = 120
        with self.muted_page(api.to_yaml(source), width=1920, height=1080) as (page,state,folder):
            self.assertFalse(state.error,state.error)
            before=state.song_path.read_bytes(); data=api.compile_song(state.song_path)[0]
            events=json.loads(json.dumps(state.mod.native_score['plan']['events']))
            errors=[]; page.on('pageerror',lambda e:errors.append(str(e)))
            page.evaluate("tab('tab');setEdit(true)"); page.wait_for_selector('.vt-tab-score svg')
            self.capture_engraving(page)
            for choice,value,symbol in [('1',30,0xeca2),('2.',40,0xeca3),('2',60,0xeca3),
                    ('4.',80,0xeca5),('8',240,0xeca7),('8.',160,0xeca7),('16',480,0xeca9)]:
                with self.subTest(unit=choice):
                    self.open_panel(page,'measures'); page.select_option('[data-ui=measure]','bar1')
                    page.select_option('[data-ui=tempo-unit]',choice)
                    page.click('.vt-tab-measures button[type=submit]')
                    self.settled(page,f'SCORE.view.score.measures[0].tempo_unit?.value==={value}')
                    page.wait_for_function(f"document.querySelector('.vt-tab-score').textContent.includes(' = {value}')")
                    mark=tempo_marks(page,'.vt-tab-score')[0]
                    self.assertEqual((mark['glyph'],mark['value']),(chr(symbol)+('\uecb7' if choice.endswith('.') else ''),value))
                    self.assertEqual(page.evaluate('tabRendered.masterBars[0].tempoAutomations[0].value'),120)
                    self.assertEqual(api.compile_song(state.song_path)[0],data)
                    self.assertEqual(state.mod.native_score['plan']['events'],events)
                    preview=page.context.browser.new_page(); preview.goto(self.print_url(page,state)); self.print_ready(preview)
                    for mode,scale in [('both',40),('tab',80),('staff',150)]:
                        preview.select_option('[name=notation]',mode); preview.fill('[name=scale]',str(scale))
                        preview.locator('form button[type=submit]').click(); self.print_ready(preview)
                        printed=tempo_marks(preview,'.vt-print-pages')[0]
                        self.assertEqual((printed['glyph'],printed['value']),(mark['glyph'],value))
                    preview.close()
                    page.click('[data-action=undo]'); self.settled(page,'!SCORE.view.score.measures[0].tempo_unit')
                    self.assertEqual(state.song_path.read_bytes(),before)
            self.assertEqual(errors,[])

    def test_tempo_units_integer_midbar_imported_stale_repair_reopen(self):
        from vulturetracker import server
        source=self.four_bar_song(); source['module']['tempo']=91
        source['patterns']['C']['data']='\n'.join(f'{row:02}: ... .. ... '+('T78' if row==24 else '...') for row in range(48))
        units=[dict(base=4,dotted=True,value=61),dict(base=1,dotted=False,value=30),
               dict(base=32,dotted=True,value=640),dict(base=64,dotted=True,value=1280)]
        for measure,unit in zip(source['score']['measures'],units): measure['tempo_unit']=unit
        with self.muted_page(api.to_yaml(source),width=1920,height=1080) as (page,state,folder):
            self.assertFalse(state.error,state.error)
            before=state.song_path.read_bytes(); data=api.compile_song(state.song_path)[0]
            events=json.loads(json.dumps(state.mod.native_score['plan']['events']))
            errors=[]; page.on('pageerror',lambda e:errors.append(str(e)))
            page.evaluate("tab('tab');setEdit(true)");page.wait_for_selector('.vt-tab-score svg')
            self.capture_engraving(page)
            expected=[('\ueca5\uecb7',61),('\ueca5',120),('\ueca2',30),('\uecab\uecb7',640),('\uecad\uecb7',1280)]
            marks=tempo_marks(page,'.vt-tab-score')
            self.assertEqual([(m['glyph'],m['value']) for m in marks],expected)
            self.assertGreater(marks[1]['left']-marks[0]['right'],0)
            preview=page.context.browser.new_page();preview.goto(self.print_url(page,state));self.print_ready(preview)
            self.assertEqual([(m['glyph'],m['value']) for m in tempo_marks(preview,'.vt-print-pages')],expected)
            preview.close()
            # Reopen uses saved units, never inverse-rounded 91/1.5 instead of 61.
            page.evaluate('async path=>{await openSong(path)}',str(state.song_path));state=server.Handler.state
            page.evaluate("tab('tab');setEdit(true)");page.wait_for_selector('.vt-tab-score svg')
            self.assertEqual([(m['glyph'],m['value']) for m in tempo_marks(page,'.vt-tab-score')],expected)
            self.open_panel(page,'measures');page.select_option('[data-ui=measure]','bar1')
            page.click('.vt-tab-measures button[type=submit]');self.settled(page,'true')
            self.assertEqual(state.song['score']['measures'][0]['tempo_unit']['value'],61)
            self.assertEqual(state.song_path.read_bytes(),before)
            page.evaluate('async()=>{setCursor(3,0);await scoreRefresh()}')
            self.open_panel(page,'measures');page.select_option('[data-ui=measure]','bar4')
            self.assertEqual(page.input_value('[data-ui=tempo-unit]'),'64.')
            page.fill('[data-ui=tempo-bpm]','150');page.click('[data-action=tempo-set]')
            self.settled(page,"SCORE.view.tempo_commands.some(c=>c.pattern==='C2'&&c.bpm===150)")
            page.wait_for_function("!document.querySelector('[data-ui=tempo-warning]').hidden")
            self.assertIn('written tempo is stale',page.inner_text('[data-ui=tempo-effective]'))
            self.assertEqual(tempo_marks(page,'.vt-tab-score')[-1]['value'],150)
            self.assertEqual(state.song['score']['measures'][3]['tempo_unit'],units[3])
            stale=state.song_path.read_bytes()
            preview=page.context.browser.new_page();preview.goto(self.print_url(page,state));self.print_ready(preview)
            self.assertIn('Bar 4: written tempo is stale; showing 150',preview.inner_text('.vt-print-status'))
            self.assertEqual(tempo_marks(preview,'.vt-print-pages')[-1]['glyph'],'\ueca5');preview.close()
            page.click('.vt-tab-measures button[type=submit]')
            self.settled(page,'SCORE.view.score.measures[3].tempo_unit.value===1600')
            page.wait_for_function("document.querySelector('[data-ui=tempo-warning]').hidden")
            self.assertEqual(tempo_marks(page,'.vt-tab-score')[-1]['value'],1600)
            page.click('[data-action=undo]');self.settled(page,'SCORE.view.score.measures[3].tempo_unit.value===1280')
            self.assertEqual(state.song_path.read_bytes(),stale)
            page.click('[data-action=undo]');self.settled(page,"!SCORE.view.tempo_commands.some(c=>c.pattern==='C2')")
            self.assertEqual(state.song_path.read_bytes(),before)
            self.assertEqual(api.compile_song(state.song_path)[0],data)
            self.assertEqual(state.mod.native_score['plan']['events'],events)
            self.assertEqual(errors,[])

    def test_native_tempo_measure_set_update_clear_pattern_sync_undo_and_reopen(self):
        from tests.test_tablature_sync import score_song
        from vulturetracker import server
        source = score_song()
        source['samples'][1]['file'] = 'a.wav'
        source['orders'], source['score']['order_ids'], source['score']['ties'] = ['a'], ['first'], []
        source['patterns'].pop('b')
        source['score']['patterns'].pop('b')
        source['score']['measures'] = [dict(id='middle', meter=[1, 4], **{
            'from': dict(occurrence='first', at=[1, 1]), 'to': dict(occurrence='first', at=[2, 1])})]
        with self.page(api.to_yaml(source)) as (page, state, folder):
            before = (folder / 'song.yaml').read_bytes()
            page.evaluate("tab('tab');setEdit(true)")
            page.wait_for_selector('.vt-tab-grid [data-note=e]')
            self.capture_engraving(page)
            self.open_panel(page, 'measures')
            page.select_option('[data-ui=measure]', 'middle')
            self.assertIn('Saved measure start', page.inner_text('[data-ui=tempo-target]'))
            self.assertEqual(page.inner_text('[data-ui=tempo-effective]'), 'Effective: 120 BPM')
            self.assertEqual(page.input_value('[data-ui=tempo-bpm]'), '')
            self.assertTrue(page.locator('[data-action=tempo-clear]').is_disabled())
            # Explicit no-op commands must remain distinguishable from inheritance.
            page.fill('[data-ui=tempo-bpm]', '120')
            page.click('[data-action=tempo-set]')
            self.settled(page, "SCORE.view.tempo_commands?.some(c=>c.pattern==='a'&&c.row===12&&c.bpm===120)")
            self.assertEqual(page.input_value('[data-ui=tempo-bpm]'), '120')
            self.assertFalse(page.locator('[data-action=tempo-clear]').is_disabled())
            self.assertEqual(len(state.history), 1)
            page.fill('[data-ui=tempo-bpm]', '180')
            page.click('[data-action=tempo-set]')
            self.settled(page, "SCORE.view.tempo_commands?.some(c=>c.row===12&&c.bpm===180)")
            self.assertEqual(len(state.history), 2)
            self.assertEqual(page.inner_text('[data-ui=tempo-effective]'), 'Effective: 180 BPM')
            self.assertEqual([(c.effect, c.param) for c in state.mod.patterns[0].rows[12] if c.effect], [(20, 180)])
            self.assertEqual(page.evaluate("""tabRendered.masterBars.flatMap(bar =>
                bar.tempoAutomations.map(tempo => tempo.value))"""), [120, 180])
            page.click('[data-t=pattern]')
            page.wait_for_function("PAT.rows?.[12]?.some(cell=>cell.includes('TB4'))")
            page.click('[data-t=tab]')
            self.open_panel(page, 'measures')
            page.select_option('[data-ui=measure]', 'middle')
            # Endpoint edits affect the measure, never relocate the Pattern T.
            page.fill('[data-ui=measure-from]', '2')
            page.fill('[data-ui=measure-to]', '3')
            page.click('.vt-tab-measures button[type=submit]')
            self.settled(page, "SCORE.view.score.measures[0].from.at[0]===2")
            self.assertEqual(state.mod.patterns[0].rows[12][0].param, 180)
            self.assertEqual(page.input_value('[data-ui=tempo-bpm]'), '')
            self.assertEqual(page.inner_text('[data-ui=tempo-effective]'), 'Effective: 180 BPM')
            revision = page.evaluate('SCORE.view.revision')
            page.click('[data-action=undo]')
            self.settled(page, f"SCORE.view.revision!=={json.dumps(revision)}")
            page.select_option('[data-ui=measure]', 'middle')
            page.fill('[data-ui=tempo-bpm]', '150')
            page.click('[data-action=tempo-set]')
            self.settled(page, "SCORE.view.tempo_commands?.some(c=>c.row===12&&c.bpm===150)")
            self.assertEqual(len(state.history), 3)
            saved = (folder / 'song.yaml').read_bytes()
            for invalid in ('31', '256', '32.5', ''):
                page.fill('[data-ui=tempo-bpm]', invalid)
                page.click('[data-action=tempo-set]')
                self.assertIn('integer from 32 to 255', page.inner_text('.vt-tab-status'))
                self.assertEqual((folder / 'song.yaml').read_bytes(), saved)
                self.assertEqual(len(state.history), 3)
            page.click('[data-action=tempo-clear]')
            self.settled(page, "!SCORE.view.tempo_commands?.some(c=>c.pattern==='a'&&c.row===12)")
            self.assertEqual(len(state.history), 4)
            self.assertEqual(page.inner_text('[data-ui=tempo-effective]'), 'Effective: 120 BPM')
            self.assertEqual(page.input_value('[data-ui=tempo-bpm]'), '')
            self.assertEqual(state.song['score'], source['score'])
            revision = page.evaluate('SCORE.view.revision')
            page.click('[data-action=undo]')
            self.settled(page, f"SCORE.view.revision!=={json.dumps(revision)}")
            self.assertEqual(page.input_value('[data-ui=tempo-bpm]'), '150')
            page.evaluate('async path=>{await openSong(path)}', str(folder / 'song.yaml'))
            state = server.Handler.state
            page.evaluate("tab('tab');setEdit(true)")
            page.wait_for_selector('.vt-tab-grid [data-note=e]')
            self.open_panel(page, 'measures')
            page.select_option('[data-ui=measure]', 'middle')
            self.assertEqual(page.input_value('[data-ui=tempo-bpm]'), '150')
            self.assertEqual(page.inner_text('[data-ui=tempo-effective]'), 'Effective: 150 BPM')
            for remaining in (2, 1, 0):
                revision = page.evaluate('SCORE.view.revision')
                page.click('[data-action=undo]')
                self.settled(page, f"SCORE.view.revision!=={json.dumps(revision)}")
                self.assertEqual(len(state.history), remaining)
            self.assertEqual((folder / 'song.yaml').read_bytes(), before)
            self.assertFalse(page.evaluate('LV.playing'))

    def test_native_tempo_occurrence_start_shared_scope_refusal_and_all_uses(self):
        with self.page(NATIVE_SONG) as (page, state, folder):
            before = (folder / 'song.yaml').read_bytes()
            page.evaluate("tab('tab');setEdit(true)")
            page.wait_for_selector('.vt-tab-grid [data-note=note-0]')
            page.fill('[data-ui=at]', '1')
            page.click('[data-action=go]')
            self.open_panel(page, 'measures')
            self.assertEqual(page.input_value('[data-ui=measure]'), '')
            self.assertIn('Occurrence start · pass-1 · 0/1', page.inner_text('[data-ui=tempo-target]'))
            self.assertIn('3 uses', page.inner_text('[data-ui=tempo-help]'))
            self.assertEqual(page.input_value('[data-ui=tempo-scope]'), 'occurrence')
            page.fill('[data-ui=tempo-bpm]', '180')
            page.click('[data-action=tempo-set]')
            page.wait_for_function("document.querySelector('.vt-tab-status').textContent.includes('Make unique')")
            self.assertEqual((folder / 'song.yaml').read_bytes(), before)
            self.assertEqual(state.history, [])
            page.select_option('[data-ui=tempo-scope]', 'pattern')
            page.click('[data-action=tempo-set]')
            self.settled(page, "SCORE.view.tempo_commands?.some(c=>c.pattern==='verse'&&c.row===0&&c.bpm===180)")
            self.assertEqual(len(state.history), 1)
            self.assertEqual(state.song['orders'], ['verse'] * 3)
            self.assertEqual(state.mod.native_score['plan']['tempos'], [{'at': [0, 1], 'bpm': 180}])
            self.assertEqual(page.inner_text('[data-ui=tempo-effective]'), 'Effective: 180 BPM')
            page.click('[data-action=tempo-clear]')
            self.settled(page, "!SCORE.view.tempo_commands?.length")
            self.assertEqual(len(state.history), 2)
            self.assertEqual(page.inner_text('[data-ui=tempo-effective]'), 'Effective: 137 BPM')
            for _ in range(2):
                revision = page.evaluate('SCORE.view.revision')
                page.click('[data-action=undo]')
                self.settled(page, f"SCORE.view.revision!=={json.dumps(revision)}")
            self.assertEqual((folder / 'song.yaml').read_bytes(), before)

    def test_native_tempo_fractional_measure_start_refuses_without_write(self):
        source = api.from_yaml(SONG)
        source['patterns']['verse']['data'] = ''
        source['score']['measures'] = [dict(id='fractional', meter=[1, 4], **{
            'from': dict(occurrence='occ-verse', at=[1, 13]),
            'to': dict(occurrence='occ-verse', at=[14, 13])})]
        with self.page(api.to_yaml(source)) as (page, state, folder):
            before = (folder / 'song.yaml').read_bytes()
            page.evaluate("tab('tab');setEdit(true)")
            page.wait_for_selector('.vt-tab-grid [data-note=note-a]')
            self.open_panel(page, 'measures')
            page.select_option('[data-ui=measure]', 'fractional')
            page.fill('[data-ui=tempo-bpm]', '180')
            page.click('[data-action=tempo-set]')
            page.wait_for_function("document.querySelector('.vt-tab-status').textContent.includes('integral row')")
            self.assertEqual((folder / 'song.yaml').read_bytes(), before)
            self.assertEqual(state.history, [])

    def test_native_listening_note_shows_tempo_row_time(self):
        source = api.from_yaml(SONG)
        source['module']['tempo'] = 120
        source['patterns']['verse']['data'] = ''.join(
            f"{row:02d}: ... .. ... {'T3C' if row == 12 else '...'}\n" for row in range(25))
        with self.page(api.to_yaml(source)) as (page, state, folder):
            before = (folder / 'song.yaml').read_bytes()
            result = page.evaluate("""async()=>await act('note',
                {order:0,row:12,text:'Tempo boundary fixture',source:'agent annotation'})""")
            self.assertEqual(result['time'], .5)
            page.click('[data-t=notes]')
            page.wait_for_function("document.querySelector('#notelist')?.textContent.includes('0:00.50')")
            self.assertIn('row 12', page.inner_text('#notelist'))
            self.assertEqual(page.input_value('#notelist input.note'), 'Tempo boundary fixture')
            self.assertEqual(json.loads(state.notes_path.read_text(encoding='utf-8'))['notes'][0]['time'], .5)
            self.assertEqual((folder / 'song.yaml').read_bytes(), before)
            self.assertFalse(page.evaluate('LV.playing'))

    def test_native_midi_page_harmonics_pitch_tempo_and_capacity_refusal(self):
        import mido
        from tests.test_tablature import beat
        from tests.test_tablature_sync import score_song
        source = score_song()
        source['samples'][1]['file'] = 'a.wav'
        source['orders'], source['score']['order_ids'], source['score']['ties'] = ['a'], ['first'], []
        source['patterns'].pop('b')
        source['score']['patterns'].pop('b')
        source['patterns']['a']['data'] = ''.join(
            f"{row:02d}: ... .. ... {'TB4' if row == 6 else '...'}\n" for row in range(48))
        source['score']['tracks']['guitar']['midi'] = {'program': 24, 'bank': 129}
        source['score']['patterns']['a']['beats'] = [beat('combined', [0, 1], [
            dict(id='harmonic', string=6, fret=12, pitch=52, velocity=95,
                 harmonic={'type': 'semi', 'data': 0},
                 bend={'points': [{'position': 0, 'value': 0}, {'position': 12, 'value': 4}]}),
            dict(id='independent', string=1, fret=0, pitch=64, velocity=73, vibrato=True)])]
        with self.page(api.to_yaml(source)) as (page, state, folder):
            before = {name: (folder / name).read_bytes() for name in ('song.yaml', 'a.wav', 'b.wav')}
            dialogs, console_errors = [], []
            page.on('dialog', lambda dialog: (dialogs.append(dialog.message), dialog.accept()))
            page.on('console', lambda message: console_errors.append(message.text) if message.type == 'error' else None)
            page.click('[data-t=tab]')
            page.wait_for_selector('.vt-tab-grid [data-note=harmonic]')
            self.capture_engraving(page)
            page.select_option('[data-ui=track]', 'guitar')
            page.wait_for_function("window.tabRendered?.masterBars?.length > 0")
            self.assertEqual(page.evaluate("""tabRendered.masterBars.map(bar =>
                bar.tempoAutomations.map(tempo => [tempo.value, tempo.ratioPosition]))"""),
                [[[120, 0], [180, .125]]])
            page.wait_for_selector('.vt-tab-score svg')
            page.click('[data-t=export]')
            page.select_option('#export-format', 'mid')
            destination = folder / 'layered-midi'
            page.fill('#export-dest', str(destination))
            page.fill('#export-name', 'harmonic-tempo')
            page.select_option('#export-tail-mode', 'cut')
            page.click('#export-go')
            page.wait_for_function("['done','error','failed','cancelled'].includes(S.export?.status)", timeout=20000)
            result = page.evaluate('S.export')
            self.assertEqual(result['status'], 'done', result)
            output = destination / 'harmonic-tempo.mid'
            self.assertEqual(result['files'], [str(output)])
            report = result['conversion']
            self.assertEqual((report['note_count'], report['quantized_events']), (4, 0))
            self.assertEqual([segment['source_bpm'] for segment in report['tempo']['segments']], [120, 180])
            self.assertTrue(page.locator('#export-result').is_visible())
            visible = page.inner_text('#export-result')
            self.assertIn('MIDI: 4 notes · 4 channels · exact beat timing · tempo 120 BPM', visible)
            self.assertIn('MIDI tempo rounds to integer microseconds per quarter', visible)
            self.assertIn('Pitch channels remain owned through their last in-range control', visible)
            midi = mido.MidiFile(output, charset='utf-8')
            events = []
            for track in midi.tracks:
                tick = 0
                for message in track:
                    tick += message.time
                    events.append((Fraction(tick, midi.ticks_per_beat), message))
            attacks = [(at, m.note, m.velocity, m.channel) for at, m in events if m.type == 'note_on']
            self.assertEqual(sorted((at, pitch, velocity) for at, pitch, velocity, _ in attacks),
                             [(0, 52, 31), (0, 52, 47), (0, 64, 73), (0, 64, 95)])
            self.assertEqual(len({channel for _, _, _, channel in attacks}), 4)
            self.assertNotIn(9, {channel for _, _, _, channel in attacks})
            self.assertEqual([(at, m.tempo) for at, m in events if m.type == 'set_tempo'],
                             [(Fraction(0), 500000), (Fraction(1, 2), 333333)])
            plan = state.mod.native_score['plan']
            for voice in report['voices']:
                channel = voice['midi_channel']
                channel_events = [(at, m) for at, m in events if getattr(m, 'channel', None) == channel]
                self.assertEqual([(at, m.note) for at, m in channel_events if m.type == 'note_off'],
                                 [(Fraction(1), voice['pitch'])])
                rpn = [(m.control, m.value) for _, m in channel_events if m.type == 'control_change'
                       and m.control in (101, 100, 6, 38)]
                self.assertEqual(rpn, [(101, 0), (100, 0), (6, 12), (38, 0), (101, 127), (100, 127)])
                expected_pitch = [(Fraction(*e['at']), int(e['semitones'] * 8192 / 12))
                                  for e in plan['events'] if e['type'] == 'pitch' and e['id'] == voice['id']]
                self.assertEqual([(at, m.pitch) for at, m in channel_events if m.type == 'pitchwheel'],
                                 [(Fraction(0), 0), *expected_pitch, (Fraction(*voice['controls_end']), 0)])
                kinds = [m.type for at, m in channel_events if at == 0]
                self.assertLess(kinds.index('program_change'), kinds.index('note_on'))
                self.assertLess(kinds.index('pitchwheel'), kinds.index('note_on'))
            self.assertEqual({name: (folder / name).read_bytes() for name in before}, before)
            self.assertEqual((dialogs, console_errors), ([], []))
            self.assertFalse(page.evaluate('LV.playing'))
        # Six semi harmonics require 18 independent channels. The same real
        # export form must refuse before creating a destination or partial file.
        source['score']['patterns']['a']['beats'][0]['notes'] = [
            dict(id=f'layer{i}', string=i + 1, fret=0, pitch=pitch, velocity=95, harmonic={'type': 'semi'})
            for i, pitch in enumerate(source['score']['tracks']['guitar']['tuning'])]
        with self.page(api.to_yaml(source)) as (page, state, folder):
            before = (folder / 'song.yaml').read_bytes()
            destination = folder / 'capacity-refusal'
            page.on('dialog', lambda dialog: dialog.accept())
            page.click('[data-t=export]')
            page.select_option('#export-format', 'mid')
            page.fill('#export-dest', str(destination))
            page.fill('#export-name', 'too-many-layers')
            with page.expect_response(lambda response: response.url.endswith('/api/export')) as response:
                with page.expect_event('dialog') as refusal:
                    page.click('#export-go')
            self.assertEqual(response.value.status, 400)
            self.assertIn('more than 15 independent melodic channels', refusal.value.message)
            self.assertIn('multiport routing is not enabled', refusal.value.message)
            page.wait_for_function("!$('export-go').disabled")
            self.assertIsNone(state.export_job)
            self.assertIsNone(state.export_result)
            self.assertFalse(destination.exists())
            self.assertFalse(list(folder.rglob('*.mid')))
            self.assertEqual((folder / 'song.yaml').read_bytes(), before)
            self.assertFalse(page.evaluate('LV.playing'))

    def test_native_tempo_steps_share_tab_pattern_seek_and_speed_clock(self):
        from vulturetracker.tablature import TempoClock
        source = api.from_yaml(SONG)
        source['module']['tempo'] = 137
        source['patterns']['verse']['data'] = ''.join(
            f"{row:02d}: ... .. ... { {12: 'T53', 18: 'TFB'}.get(row, '...')} | ... .. ... ...\n"
            for row in range(25))
        source['samples'][1]['loop'] = {'start': 0, 'end': RATE // 10}
        source['score']['patterns']['verse']['beats'][1]['notes'][0].update(
            velocity=95, harmonic={'type': 'semi', 'data': 0})
        with self.page(api.to_yaml(source)) as (page, state, folder):
            before = (folder / 'song.yaml').read_bytes()
            page.evaluate("tab('tab');setSpeed(1)")
            page.wait_for_selector('.vt-tab-grid [data-note=note-b]')
            plan = state.mod.native_score['plan']
            clock = TempoClock(plan['tempo'], plan['tempos'])
            self.assertEqual(page.evaluate('SCORE.view.tempos'), plan['tempos'])
            for row in (0, 12, 13, 18, 24):
                self.assertAlmostEqual(page.evaluate('r=>timeAt(0,r)', row), float(clock.seconds_at(Fraction(row, 12))))
                self.assertEqual(page.evaluate('r=>posAt(timeAt(0,r)).row', row), row)
            page.evaluate('async()=>{await lvPlay(0,12)}')
            page.wait_for_function('LV.playing && LV.pos?.row>=12 && !LV.loading')
            page.evaluate('setSpeed(1.3)')
            q = round(65536 / 1.3)
            page.wait_for_function(f'LV.playing && LV.pos?.factorQ==={q} && !LV.loading')
            self.assertIsNone(page.evaluate('LV.err'))
            sample = page.evaluate("""()=>{const p=playPos();SCORE.editor.setPlayhead(p);
                return {p,notes:[...document.querySelectorAll('.vt-tab-grid .playing')].map(e=>e.dataset.note).filter(Boolean)}}""")
            p = sample['p']
            rate = p['sampleRate']
            def frame(at):
                exact = clock.seconds_at(at) * rate * q / 65536
                return (2 * exact.numerator + exact.denominator) // (2 * exact.denominator)
            expected = [b['notes'][0]['id'] for b in source['score']['patterns']['verse']['beats']
                        if frame(Fraction(*b['at'])) <= p['scoreFrame'] < frame(Fraction(*b['at']) +
                            (Fraction(1, 3) if b['id'] == 'beat-a' else 1))]
            self.assertEqual(sample['notes'], expected)
            boundary_frame = frame(Fraction(1))
            at = clock.quarters_at(Fraction(boundary_frame * 65536, rate * q))
            boundary = dict(o=0, occurrence='occ-verse', scoreFrame=boundary_frame, sampleRate=rate,
                            factorQ=q, at=[at.numerator, at.denominator])
            page.evaluate("""p=>{lvStop();window.tempoPosition=p;playPos=()=>window.tempoPosition;SCORE.editor.setPlayhead(p)}""", boundary)
            page.wait_for_selector('.vt-tab-grid [data-note=note-b].playing')
            boundary['scoreFrame'] -= 1
            page.evaluate('p=>{window.tempoPosition=p;SCORE.editor.setPlayhead(p)}', boundary)
            self.assertFalse(page.locator('.vt-tab-grid [data-note=note-b].playing').count())
            self.assertEqual((folder / 'song.yaml').read_bytes(), before)

    def test_native_harmonic_controls_engraving_layers_playback_and_undo(self):
        """Run after the qualified grouped runtime is promoted."""
        from tests.test_tablature import beat, note
        source = api.from_yaml(NATIVE_SONG)
        source['module'].update(tempo=120, channels=[{'name': 'Harmonic'}])
        source['samples'][1]['loop'] = {'start': 0, 'end': RATE // 10}
        source['orders'], source['score']['order_ids'], source['score']['ties'] = ['verse'], ['pass-1'], []
        source['score']['tracks']['guitar'].update(tuning=[40], channels=[0])
        source['score']['patterns']['verse']['beats'] = [beat('h', [0, 1], [note('harmonic', 52, 1, 12)], value=1)]
        with self.page(api.to_yaml(source)) as (page, state, folder):
            before = (folder / 'song.yaml').read_bytes()
            page.evaluate("tab('tab');setEdit(true);setSpeed(1)")
            page.wait_for_selector('.vt-tab-grid [data-note=harmonic]')
            self.capture_engraving(page)
            page.click('.vt-tab-grid [data-note=harmonic]')
            page.select_option('[data-ui=harmonic-type]', 'semi')
            page.click('[data-action=harmonic]')
            self.assertIn('explicit velocity', page.inner_text('.vt-tab-status'))
            self.assertEqual((folder / 'song.yaml').read_bytes(), before)
            page.fill('[data-ui=velocity]', '95')
            page.click('[data-action=velocity]')
            self.settled(page, 'SCORE.view.score.patterns.verse.beats[0].notes[0].velocity===95')
            rendered = 'tabRendered.tracks[0].staves[0].bars[0].voices[0].beats[0].notes[0]'
            for kind, enum, pitch in [('semi', 5, 12), ('artificial', 2, 12), ('tapped', 4, 12), ('pinch', 3, 12), ('natural', 1, 12)]:
                page.select_option('[data-ui=harmonic-type]', kind)
                if kind != 'natural':
                    page.select_option('[data-ui=harmonic-data]', '0')
                page.click('[data-action=harmonic]')
                self.settled(page, f"SCORE.view.score.patterns.verse.beats[0].notes[0].harmonic?.type==='{kind}'")
                self.assertEqual(page.evaluate(rendered + '.harmonicType'), enum)
                self.assertEqual(page.evaluate(rendered + '.harmonicPitch'), pitch)
                self.assertEqual(state.song['score']['patterns']['verse']['beats'][0]['notes'][0]['pitch'], 52)
                self.assertIn(kind + ' harmonic', page.get_attribute('.vt-tab-grid [data-note=harmonic]', 'title'))
            page.select_option('[data-ui=harmonic-type]', 'semi')
            page.click('[data-action=harmonic]')
            self.settled(page, "SCORE.view.score.patterns.verse.beats[0].notes[0].harmonic?.type==='semi'")
            attack = next(e for e in state.mod.native_score['plan']['events'] if e['type'] == 'note_on')
            self.assertEqual(attack['layers'], [{'pitch': 52, 'velocity': 47}, {'pitch': 52, 'velocity': 31}, {'pitch': 64, 'velocity': 95}])
            page.evaluate('async()=>{await lvPlay(0,0)}')
            page.wait_for_function('LV.playing && LV.pos?.scoreFrame>512 && !LV.loading')
            self.assertIsNone(page.evaluate('LV.err'))
            page.evaluate('lvStop()')
            page.select_option('[data-ui=harmonic-type]', '')
            page.click('[data-action=harmonic]')
            self.settled(page, "!('harmonic' in SCORE.view.score.patterns.verse.beats[0].notes[0])")
            for _ in range(len(state.history)):
                revision = page.evaluate('SCORE.view.revision')
                page.click('[data-action=undo]')
                self.settled(page, f'SCORE.view.revision!=={json.dumps(revision)}')
            self.assertEqual((folder / 'song.yaml').read_bytes(), before)

    def test_native_tg_page_export_rejection_archive_import_and_playback(self):
        from tests.test_tablature_sync import score_song
        from vulturetracker import server
        from vulturetracker.tgimport import read_tg
        source = score_song()
        source['samples'][1]['file'] = 'a.wav'
        source['patterns']['a']['data'] = ''
        source['score']['tracks']['guitar']['midi'] = {'program': 24, 'bank': 129}
        for pattern in source['score']['patterns'].values():
            for beat in pattern['beats']:
                for note in beat['notes']:
                    note['velocity'] = 95
        # TuxGuitar closes a gap between written beats on opening, so the writer refuses one: fill 2 to 3.5.
        source['score']['patterns']['a']['beats'].append(dict(id='gap-rest', track='guitar', voice=0, at=[2, 1],
                                                              written=dict(value=4, dots=1, tuplet=[1, 1]), notes=[]))
        source['score']['measures'] = [
            {'id': f'm{i}', 'meter': [4, 4], 'from': {'occurrence': oid, 'at': [0, 1]},
             'to': {'occurrence': oid, 'at': [4, 1]}}
            for i, oid in enumerate(source['score']['order_ids'])]
        with self.page(api.to_yaml(source)) as (page, state, folder):
            before = (folder / 'song.yaml').read_bytes()
            destination = folder / 'tg-output'
            dialogs = []
            def accept_dialog(dialog):
                dialogs.append(dialog.message)
                dialog.accept()
            page.on('dialog', accept_dialog)
            page.click('[data-t=export]')
            page.select_option('#export-format', 'tg')
            page.fill('#export-dest', str(destination))
            page.fill('#export-name', 'rejected')
            page.check('#export-stems')
            with page.expect_response(lambda r: r.url.endswith('/api/export')) as response:
                page.click('#export-go')
            rejection = response.value.json()
            self.assertIn('no stems or repeat', rejection['error'])
            page.wait_for_function("!$('export-go').disabled")
            self.assertTrue(any('no stems or repeat' in message for message in dialogs))
            self.assertFalse((destination / 'rejected.tg').exists())
            self.assertEqual((folder / 'song.yaml').read_bytes(), before)
            page.uncheck('#export-stems')
            page.fill('#export-name', 'archive')
            page.click('#export-go')
            page.wait_for_function("['done','error','failed','cancelled'].includes(S.export?.status)", timeout=20000)
            result = page.evaluate('S.export')
            self.assertEqual(result['status'], 'done', result)
            output = destination / 'archive.tg'
            self.assertEqual(result['files'], [str(output)])
            self.assertIn('TuxGuitar: 7 notes · 1 tracks · 2 measures', page.inner_text('#export-result'))
            archive = output.read_bytes()
            decoded, _ = read_tg(archive)
            self.assertEqual(len(decoded['score']['measures']), 2)
            self.assertEqual(next(iter(decoded['score']['tracks'].values()))['midi'], {'program': 24, 'bank': 129})
            decoded_notes = [n for p in decoded['score']['patterns'].values() for b in p['beats'] for n in b['notes']]
            self.assertEqual(len(decoded_notes), 7)
            self.assertTrue(all(n['velocity'] == 95 for n in decoded_notes))
            self.assertEqual(len(decoded['score']['ties']), 1)
            page.evaluate('renderStart()')
            page.wait_for_selector('#imppath')
            page.fill('#imppath', str(output))
            page.uncheck('#impnative')  # Current .tg import remains native regardless of the GP checkbox.
            with page.expect_response(lambda r: r.url.endswith('/api/import')) as response:
                page.press('#imppath', 'Enter')
            imported_result = response.value.json()
            self.assertNotIn('error', imported_result)
            self.assertEqual(imported_result['path'], str(destination / 'archive.yaml'))
            page.wait_for_function(f"!$('startmodal').classList.contains('on') && S?.song?.path==={json.dumps(imported_result['path'])}")
            imported = server.Handler.state
            self.assertIsNone(imported.error)
            self.assertIsNotNone(imported.mod.native_score)
            self.assertEqual(imported.song['score'], decoded['score'])
            self.assertEqual(len(list((destination / 'archive_samples').glob('*.wav'))), 7)
            page.evaluate("tab('tab')")
            page.wait_for_selector('.vt-tab-grid [data-note]:not([data-note=""])')
            page.wait_for_selector('.vt-tab-score svg')
            self.assertNotIn('rendering failed', page.inner_text('.vt-tab-status'))
            page.evaluate('async()=>{setSpeed(1);await lvPlay(0,0)}')
            page.wait_for_function("""()=>{
                if(!LV.playing || LV.err || !LV.an || !LV.pos?.scoreFrame)return false;
                const x=new Float32Array(LV.an.fftSize);LV.an.getFloatTimeDomainData(x);
                return Math.max(...x.map(Math.abs))>.0001;
            }""")
            self.assertIsNone(page.evaluate('LV.err'))
            page.evaluate('lvStop()')
            self.assertEqual(output.read_bytes(), archive)
            self.assertEqual((folder / 'song.yaml').read_bytes(), before)
            self.assertEqual(imported.history, [])

    def run_notation_options(self,page,path):
        from tests.test_score_collection_page import TestScoreCollectionPage
        from vulturetracker import notation_export,tgimport
        original=path.read_bytes()
        errors=[]
        page.on('pageerror',lambda error:errors.append(str(error)))
        settings=dict(track=2,measureFrom=2,measureTo=3,score=False,tablature=True,trackName=False,
                      trackGroup=True,lyrics=False,text=False,chordDiagram=False,version='2.14.0')
        def set_options(prefix):
            for key,value in settings.items():
                selector=f'#{prefix}-ly-{key}'
                if isinstance(value,bool): page.locator(selector).set_checked(value)
                else: page.fill(selector,str(value))
        expected=notation_export.native_to_lilypond(api.from_yaml(original.decode()),
            tgimport._raw(api.from_yaml(original.decode())),settings=settings)[0]
        with tempfile.TemporaryDirectory(prefix='vt-notation-options-') as temporary:
            folder=Path(temporary)
            page.click('[data-t=export]');page.select_option('#export-format','ly')
            self.assertTrue(page.is_visible('#export-lilypond'))
            set_options('export')
            page.uncheck('#export-stems');page.fill('#export-dest',str(folder));page.fill('#export-name','selected-part')
            page.click('#export-go')
            page.wait_for_function('S.export?.status==="done"&&S.export.files?.some(p=>p.endsWith("selected-part.ly"))',timeout=30000)
            self.assertEqual((folder/'selected-part.ly').read_text(encoding='utf-8'),expected)
            collection=TestScoreCollectionPage()
            page.evaluate('collectionOpen()')
            collection.scan(page,path.parent)
            page.fill('#collection-filter',path.name)
            page.locator('#collection-files input[type=checkbox]').check()
            page.select_option('#collection-format','ly');set_options('collection')
            previous=page.evaluate("localStorage.getItem('vt-delivery-settings')")
            try:
                page.get_by_role('button',name='Remember delivery settings',exact=True).click()
                page.reload();page.wait_for_function('S?.song?.facts')
                page.evaluate('collectionOpen()')
                self.assertEqual(page.evaluate('lilypondSettings("collection")'),settings)
                collection.scan(page,path.parent);page.fill('#collection-filter',path.name)
                page.locator('#collection-files input[type=checkbox]').check()
                result=collection.convert(page,folder/'batch','ly')['results'][0]
                self.assertEqual(result['status'],'done',result)
                self.assertEqual(Path(result['files'][0]).read_text(encoding='utf-8'),expected)
                page.click('#collection-close')
            finally:
                page.evaluate("v=>{if(v===null)localStorage.removeItem('vt-delivery-settings');else localStorage.setItem('vt-delivery-settings',v)}",previous)
        self.assertEqual(path.read_bytes(),original)
        self.assertEqual(errors,[])
        return dict(single_and_batch_settings=True,persisted_options=True,source_unchanged=True,page_errors=errors)

    def test_notation_delivery_options_real_controls(self):
        from tests.test_tablature_sync import complete_song_seed
        song=complete_song_seed()
        song['module']['title']='Notation delivery'
        for sample in song['samples'].values():sample['file']='a.wav'
        with self.muted_page(api.to_yaml(song)) as (page,state,folder):
            self.assertFalse(state.error,state.error)
            self.run_notation_options(page,folder/'song.yaml')

    @staticmethod
    def score_view_song():
        from tests.test_tablature_sync import complete_song_seed
        song=complete_song_seed();song['module']['title']='Score view modes'
        for sample in song['samples'].values():sample['file']='a.wav'
        song['score']['patterns']['C']['beats'][0]['chord']=dict(name='C',first_fret=1,frets=[0,1,0,2,3,-1])
        return song

    @staticmethod
    def compact_score_song():
        song=TestTablaturePage.score_view_song();song['module']['title']='Compact score spacing'
        song['module']['tempo']=120
        pattern=song['score']['patterns']['C']
        pattern['beats']=[b for b in pattern['beats'] if b['track']!='guitar' or b['voice']==1]
        specs=[([0,1],4,0,[1,1]),([1,1],8,0,[1,1]),([3,2],4,1,[1,1]),
               ([3,1],8,0,[3,2]),([10,3],8,0,[3,2]),([11,3],8,0,[3,2])]
        for i,(at,value,dots,tuplet) in enumerate(specs):
            pattern['beats'].append(dict(id=f'compact{i}',track='guitar',voice=0,at=at,
                written=dict(value=value,dots=dots,tuplet=tuplet),notes=[
                    dict(id=f'compact-note{i}',pitch=60,string=2,fret=1,velocity=95)]))
        lead=[b for b in song['score']['patterns']['F']['beats'] if b['track']=='guitar' and b['voice']==0]
        for b in lead[:2]:b['chord']=dict(name='C major',first_fret=1,frets=[0,1,0,2,3,-1])
        lead[0]['notes'][0]['grace']=dict(fret=0,value=16,velocity=79,transition='none',on_beat=True,dead=False)
        lead[2]['notes'][0]['bend']=dict(points=[dict(position=0,value=0),dict(position=12,value=2)])
        # A later bar introduces shorter notes after the earlier bars were laid out.
        later=song['score']['patterns']['G']['beats']
        first=next(b for b in later if b['track']=='guitar' and b['voice']==0 and b['at']==[0,1])
        later[:]=[b for b in later if not(b['track']=='guitar' and b['voice']==0 and b['at']==[0,1])]
        for i in range(4):
            later.append(dict(id=f'dense{i}',track='guitar',voice=0,at=[i,4],
                written=dict(value=16,dots=0,tuplet=[1,1]),notes=first['notes'] if i==0 else [
                    dict(id=f'dense-note{i}',pitch=60,string=2,fret=1,velocity=95)]))
        return song

    def run_compact_score(self,page,path):
        original=path.read_bytes();errors=[];writes=[]
        page.set_viewport_size(dict(width=1920,height=1080))
        page.on('pageerror',lambda error:errors.append(str(error)))
        page.on('request',lambda r:writes.append(r.url) if '/api/score_' in r.url and r.method=='POST' else None)
        saved=page.evaluate("localStorage.getItem('vt.scoreView')")
        page.evaluate("tab('tab');setEdit(true)");page.wait_for_selector('.vt-tab-score svg')
        for selector in ('.vt-tab-view','.vt-tab-inspector'):
            if not page.locator(selector).evaluate('e=>e.open'):page.locator(selector+' > summary').click()
        page.select_option('[data-ui=track]','guitar');page.select_option('[data-ui=staff-mode]','select')
        self.capture_engraving(page)
        def rendered():
            self.settled(page,'window.tabRendered&&tabRenderedRevision===SCORE.view.revision&&tabRenderApi.boundsLookup?.isFinished')
        def change(field,value):
            count=page.evaluate('window.tabRenderCount||0');control=page.locator('[data-ui=view-'+field+']')
            if (control.is_checked() == value if isinstance(value,bool) else control.input_value() == str(value)):
                return
            if isinstance(value,bool):control.set_checked(value)
            elif field=='scale':control.fill(str(value));control.press('Tab')
            else:control.select_option(value)
            page.wait_for_function('n=>(window.tabRenderCount||0)>n',arg=count);rendered()
        def gaps():
            return page.evaluate("""() => {
                const beats=tabRendered.tracks[0].staves[0].bars[0].voices[0].beats;
                const xs=beats.map(b=>tabRenderApi.boundsLookup.findBeats(b).at(-1).onNotesX);
                return xs.slice(1).map((x,i)=>x-xs[i]);
            }""")
        change('multitrack',False);change('scale',100)
        change('layout','horizontal');change('notation','tab')
        normal=gaps();change('compact',True);compact=gaps()
        self.assertTrue(all(x>0 for x in compact),compact)
        self.assertLess(abs(compact[0]/compact[1]-1),abs(normal[0]/normal[1]-1),(normal,compact))
        self.assertAlmostEqual(compact[0],compact[2],delta=1)
        geometry=page.evaluate("""() => tabRendered.tracks[0].staves[0].bars.map(bar=>{
            const info=tabRenderApi.renderer.instance.layout.getRendererForBar('tab',bar).layoutingInfo;
            const springs=[...info.springs.values()].sort((a,b)=>a.timePosition-b.timePosition);
            return springs.map((s,i)=>({space:1/s.springConstant,floor:s.postSpringWidth+(springs[i+1]?.preSpringWidth||0)}));
        })""")
        for bar in geometry:
            for spring in bar:self.assertGreaterEqual(spring['space']+1e-8,spring['floor'])
        self.assertAlmostEqual(geometry[0][0]['space'],21,delta=1e-6)
        self.assertAlmostEqual(geometry[0][1]['space'],20,delta=1e-6)
        self.assertAlmostEqual(geometry[0][2]['space'],21,delta=1e-6)
        self.assertEqual(path.read_bytes(),original);self.assertEqual(writes,[])
        # A real reload retains the presentation choice without creating history.
        page.reload();page.wait_for_function('S&&!S.rendering');page.evaluate("tab('tab');setEdit(true)")
        page.wait_for_selector('.vt-tab-score svg')
        for selector in ('.vt-tab-view','.vt-tab-inspector'):
            if not page.locator(selector).evaluate('e=>e.open'):page.locator(selector+' > summary').click()
        self.assertTrue(page.locator('[data-ui=view-compact]').is_checked())
        self.capture_engraving(page);change('scale',80)
        smaller=gaps();self.assertLess(smaller[0],compact[0])
        change('multitrack',True)
        self.assertTrue(page.locator('[data-ui=view-compact]').is_disabled())
        change('multitrack',False)
        self.assertFalse(page.locator('[data-ui=view-compact]').is_disabled())
        self.assertTrue(page.locator('[data-ui=view-compact]').is_checked())
        change('layout','page');change('notation','both');change('scale',100)
        page.set_viewport_size(dict(width=1280,height=900))
        page.wait_for_function('tabRenderApi.boundsLookup?.isFinished')
        self.assertEqual(path.read_bytes(),original);self.assertEqual(writes,[])
        # Font metrics can make the narrow page trigger the existing chord-label
        # width guard. Follow its instruction before testing edit hit targets.
        page.set_viewport_size(dict(width=1920,height=1080))
        change('scale',80);change('scale',100)
        self.assertNotIn('need more width',page.locator('.vt-tab-status').inner_text())
        # Georgia is absent on Linux. Its serif fallback exposed page justification
        # shrinking compact label spacing below the glyph collision minimum.
        page.evaluate("""() => new Promise(resolve=>{
            const api=tabRenderApi;
            api.settings.display.resources.elementFonts.get(alphaTab.NotationElement.EffectChordNames).families=['Times New Roman','serif'];
            api.postRenderFinished.on(()=>resolve());api.updateSettings();api.render();
        })""")
        self.assertFalse(page.locator('.vt-tab-score .at-surface').evaluate('e=>e.hidden'))
        gap, floor = page.evaluate("""() => {
            const bar=tabRendered.tracks[0].staves[0].bars[1],beats=bar.voices[0].beats.filter(b=>b.hasChord),
                info=tabRenderApi.renderer.instance.layout.getRendererForBar('tab',bar).layoutingInfo,
                springs=[...info.springs.values()].sort((a,b)=>a.timePosition-b.timePosition);
            return [tabRenderApi.boundsLookup.findBeat(beats[1]).onNotesX-tabRenderApi.boundsLookup.findBeat(beats[0]).onNotesX,
                springs[0].postSpringWidth+springs[1].preSpringWidth];
        }""")
        self.assertGreaterEqual(gap+1e-6,floor)
        # Hit targets, selection and playback markers use the compact geometry.
        self.click_tab_lane(page,0,1,2)
        self.settled(page,"CUR.score?.note==='compact-note1'")
        self.assertEqual(page.get_attribute('.vt-tab-edit-caret','data-track'),'guitar')
        marker=page.evaluate("() => {SCORE.editor.setPlayhead({o:0,row:12});const e=document.querySelector('.vt-tab-playhead');return {track:e.dataset.track,hidden:e.hidden}}")
        self.assertEqual(marker,dict(track='guitar',hidden=False))
        def action(name):
            rev=page.evaluate('SCORE.view.revision');page.click('[data-action='+name+']')
            self.settled(page,f'SCORE.view.revision!=={json.dumps(rev)}');rendered()
        action('ghost');edited=path.read_bytes()
        score=api.from_yaml(edited.decode('utf-8'))['score']
        self.assertEqual([n['id'] for p in score['patterns'].values() for b in p['beats'] for n in b['notes'] if n.get('ghost')],['compact-note1'])
        action('undo');self.assertEqual(path.read_bytes(),original)
        action('redo');self.assertEqual(path.read_bytes(),edited)
        action('undo');self.assertEqual(path.read_bytes(),original)
        self.assertEqual(errors,[])
        page.evaluate("v=>{if(v===null)localStorage.removeItem('vt.scoreView');else localStorage.setItem('vt.scoreView',v)}",saved)
        return dict(normal_gaps=normal,compact_gaps=compact,persisted=True,multitrack_guard=True,exact_history=True,page_errors=errors)

    def test_compact_score_spacing_real_controls(self):
        with self.muted_page(api.to_yaml(self.compact_score_song()),width=1920,height=1080,compact=True) as (page,state,folder):
            self.assertFalse(state.error,state.error);history=list(state.history)
            self.run_compact_score(page,folder/'song.yaml')
            self.assertEqual(list(state.history),history)

    def test_compact_score_25_strings_real_controls(self):
        song=self.compact_score_song();track=song['score']['tracks']['guitar']
        first=len(song['module']['channels'])
        track['tuning'].extend([40]*19);track['channels'].extend(range(first,first+19))
        song['module']['channels'].extend(dict(name=f'Extra string {i}') for i in range(19))
        for pattern in song['score']['patterns'].values():
            for beat in pattern['beats']:
                if beat['track']=='guitar' and 'chord' in beat:beat['chord']['frets'].extend([-1]*19)
        with self.muted_page(api.to_yaml(song),width=1920,height=1080,compact=True) as (page,state,folder):
            self.assertFalse(state.error,state.error);history=list(state.history)
            self.run_compact_score(page,folder/'song.yaml')
            self.assertEqual(list(state.history),history)

    @staticmethod
    def selection_pitch_song():
        song=TestTablaturePage.score_view_song();song['module']['title']='Selection pitch editing'
        song['score']['tracks']['guitar']['max_fret']=24
        note=next(b for b in song['score']['patterns']['C2']['beats'] if b['id']=='n3')['notes'][0]
        note.update(fret=24,pitch=83)
        return song

    @staticmethod
    def selection_delete_song():
        song=TestTablaturePage.score_view_song();song['module']['title']='Selection delete and rest'
        return song

    def run_selection_delete(self,page,path):
        original=path.read_bytes();source=api.from_yaml(original.decode('utf-8'));errors=[]
        page.on('pageerror',lambda error:errors.append(str(error)))
        page.evaluate("tab('tab');setEdit(true)");page.wait_for_selector('.vt-tab-score svg')
        if not page.locator('.vt-tab-inspector').evaluate('e=>e.open'):page.locator('.vt-tab-inspector > summary').click()
        self.capture_engraving(page);page.select_option('[data-ui=track]','guitar')
        self.settled(page,'window.tabRendered&&tabRenderApi.boundsLookup?.isFinished')
        def action(key):
            rev=page.evaluate('SCORE.view.revision')
            if key in ('Delete','Control+x','Control+Delete'):
                page.locator('#tab-editor').focus();page.keyboard.press(key)
            else:page.click('[data-action='+key+']')
            self.settled(page,f'SCORE.view.revision!=={json.dumps(rev)}&&tabRenderedRevision===SCORE.view.revision&&tabRenderApi.boundsLookup?.isFinished')
        def select(voice,local):
            page.select_option('[data-ui=voice]',index=voice)
            if local:
                self.click_tab_lane(page,0,0,2)
                self.settled(page,'SCORE.view.order===0&&tabRenderApi.boundsLookup?.isFinished')
                start,end=(self.tab_lane_point(page,0,i,2) for i in (0,1))
                page.mouse.move(start['x'],start['y']);page.mouse.down();page.mouse.move(end['x'],end['y'],steps=5);page.mouse.up()
            else:
                page.locator('#tab-editor').focus();page.keyboard.press('Control+a')
        for local,voice in ((True,0),(False,1)):
            for key in ('Delete','Control+x','rest','Control+Delete'):
                select(voice,local)
                if key=='Control+x':
                    with page.expect_response('**/api/score_command') as response:action(key)
                    self.assertEqual({b['voice'] for b in response.value.json()['clipboard']['beats']},{0,1})
                else:action(key)
                self.assertEqual(page.evaluate('CUR.score.voice'),voice)
                saved=path.read_bytes();actual=api.from_yaml(saved.decode('utf-8'))
                for name,p in actual['score']['patterns'].items():
                    for b in p['beats']:
                        old=next(x for x in source['score']['patterns'][name]['beats'] if x['id']==b['id'])
                        selected=b['track']=='guitar' and (not local or name=='C' and Fraction(*b['at'])<=1)
                        changed=selected and (key=='Control+Delete' or b['voice']==voice)
                        if changed:
                            self.assertEqual(b['notes'],[]);self.assertEqual(b['at'],old['at']);self.assertEqual(b['written'],old['written'])
                        else:self.assertEqual(b,old)
                action('undo');self.assertEqual(path.read_bytes(),original)
                action('redo');self.assertEqual(path.read_bytes(),saved)
                action('undo');self.assertEqual(path.read_bytes(),original)
        # Whole-track deletion in an empty voice is an exact no-op, not peer deletion.
        page.select_option('[data-ui=track]','bass');select(1,False)
        with page.expect_response('**/api/score_command') as response:page.keyboard.press('Delete')
        self.assertEqual(response.value.status,200)
        self.settled(page,"document.querySelector('.vt-tab-status').textContent.startsWith('Selected phrase updated')")
        self.assertEqual(path.read_bytes(),original);self.assertEqual(errors,[])
        page.select_option('[data-ui=voice]',index=0);page.select_option('[data-ui=track]','guitar')
        self.settled(page,'tabRenderedRevision===SCORE.view.revision&&tabRenderApi.boundsLookup?.isFinished')
        page.evaluate('setEdit(false)')
        return dict(local_and_whole_track=True,active_voice=True,clipboard_both_voices=True,clean_both_voices=True,empty_voice_noop=True,exact_history=True,page_errors=errors)

    def test_selection_delete_real_controls(self):
        with self.muted_page(api.to_yaml(self.selection_delete_song()),width=1920,height=1080,compact=True) as (page,state,folder):
            self.assertFalse(state.error,state.error);history=list(state.history)
            self.run_selection_delete(page,folder/'song.yaml');self.assertEqual(list(state.history),history)

    @staticmethod
    def stem_group_song():
        from tools.tg_edit_oracle import stem_song
        song=stem_song();song['module']['title']='Beam group stems'
        song['samples'][1]['file']='a.wav'
        return song

    def run_stem_groups(self,page,path):
        original=path.read_bytes();source=api.from_yaml(original.decode('utf-8'));errors=[]
        page.on('pageerror',lambda error:errors.append(str(error)))
        page.evaluate("tab('tab');setEdit(true)");page.wait_for_selector('.vt-tab-score svg')
        if not page.locator('.vt-tab-inspector').evaluate('e=>e.open'):page.locator('.vt-tab-inspector > summary').click()
        self.capture_engraving(page);page.select_option('[data-ui=track]','guitar')
        self.settled(page,'window.tabRendered&&tabRenderApi.boundsLookup?.isFinished')
        def action(key):
            rev=page.evaluate('SCORE.view.revision')
            if key.startswith('Control+'):
                page.locator('#tab-editor').focus();page.keyboard.press(key)
            else:page.click('[data-action='+key+']')
            self.settled(page,f'SCORE.view.revision!=={json.dumps(rev)}&&tabRenderedRevision===SCORE.view.revision&&tabRenderApi.boundsLookup?.isFinished')
        for bar,voice,count in ((0,0,2),(0,1,1),(1,0,3),(1,1,3),(3,0,3)):
            self.click_tab_lane(page,bar,0,1 if voice==0 else 6,voice=voice)
            self.settled(page,f'CUR.score.voice==={voice}&&SCORE.view.order==={bar}')
            if bar==0 and voice==0:
                page.locator('#tab-editor').focus();page.keyboard.press('Control+a')
            action('Control+ArrowDown')
            self.assertEqual(page.input_value('[data-ui=beat-stem]'),'down')
            saved=path.read_bytes();actual=api.from_yaml(saved.decode('utf-8'))
            for name,p in actual['score']['patterns'].items():
                for b in p['beats']:
                    old=next(x for x in source['score']['patterns'][name]['beats'] if x['id']==b['id'])
                    changed=name==f'm{bar+1}' and b['voice']==voice and b['id'] in [f'v{voice}b{i}' for i in range(count)]
                    self.assertEqual(b,dict(old,stem='down') if changed else old)
            directions=page.evaluate(f'tabRendered.tracks[0].staves[0].bars[{bar}].voices[{voice}].beats.slice(0,{count}).map(b=>b.preferredBeamDirection)')
            self.assertEqual(directions,[1]*count)
            action('undo');self.assertEqual(path.read_bytes(),original)
            action('redo');self.assertEqual(path.read_bytes(),saved)
            action('undo');self.assertEqual(path.read_bytes(),original)
        self.click_tab_lane(page,0,0,1);action('Control+ArrowUp')
        self.assertEqual(page.evaluate('tabRendered.tracks[0].staves[0].bars[0].voices[0].beats.slice(0,2).map(b=>b.preferredBeamDirection)'),[0,0])
        page.select_option('[data-ui=beat-stem]','auto');action('beat-stem')
        self.assertEqual(page.evaluate('tabRendered.tracks[0].staves[0].bars[0].voices[0].beats.slice(0,2).map(b=>b.preferredBeamDirection)'),[None,None])
        action('undo');action('undo');self.assertEqual(path.read_bytes(),original)
        self.click_tab_lane(page,2,1,1)
        self.assertTrue(page.locator('[data-action=beat-stem]').is_disabled())
        requests=[];page.on('request',lambda r:requests.append(r.url) if r.url.endswith('/api/score_command') else None)
        page.locator('#tab-editor').focus();page.keyboard.press('Control+ArrowUp')
        self.assertEqual(path.read_bytes(),original);self.assertEqual(requests,[])
        self.click_tab_lane(page,0,0,1);page.evaluate('setEdit(false)')
        self.assertEqual(errors,[])
        return dict(caret_group_only=True,voices=[0,1],compound_and_triplets=True,projected_directions=True,rest_noop=True,exact_history=True,page_errors=errors)

    @staticmethod
    def matrix_entry_song():
        from tests.test_tablature import TestMatrixEntry, beat, note
        song,_=TestMatrixEntry().fixture();song['module']['title']='Matrix entry study'
        song['samples'][1]['file']='a.wav'
        song['score']['patterns']['B']['beats']=[beat('chord',[0,1],[note('e',64,1,0),note('b',59,2,0)]),
            beat('next',[1,1],[note('nextn',65,1,1)]),beat('rest',[2,1],[],2)]
        return song

    def run_matrix_entry(self,page,path):
        original=path.read_bytes();errors=[];posts=[]
        page.on('pageerror',lambda e:errors.append(str(e)))
        page.on('request',lambda r:posts.append(r.post_data_json) if r.method=='POST' and urlsplit(r.url).path=='/api/score_command' else None)
        page.evaluate("tab('tab');setEdit(true)");page.wait_for_selector('.vt-tab-score svg')
        if not page.locator('.vt-tab-inspector').evaluate('e=>e.open'):page.locator('.vt-tab-inspector > summary').click()
        page.select_option('[data-ui=track]','guitar')
        def roll(order=0):
            page.evaluate("o=>{tab('pattern');setCursor(o,0,0,0);showPattern(o)}",order)
            self.settled(page,f'PAT.order==={order}&&PAT.native')
            page.evaluate('if(!ROLL.on)rollToggle()');page.select_option('#roll-scope','track')
            page.select_option('#roll-entry','matrix');self.settled(page,"rollTrack()==='guitar'")
        def undo_redo():
            saved=path.read_bytes()
            page.evaluate('patUndo(false)');self.settled(page,'S.undo===0');self.assertEqual(path.read_bytes(),original)
            page.evaluate('patUndo(true)');self.settled(page,'S.undo===1');self.assertEqual(path.read_bytes(),saved)
            page.evaluate('patUndo(false)');self.settled(page,'S.undo===0');self.assertEqual(path.read_bytes(),original)
        # Changing only the painted grid cannot change the Matrix target.
        for grid in ('1','4'):
            roll();page.evaluate("tab('tab')");page.select_option('[data-ui=duration]','4')
            page.evaluate("tab('pattern')");page.select_option('#roll-grid',grid);posts.clear()
            page.mouse.click(*self.roll_point(page,67,32.4))
            self.settled(page,'S.undo===1')
            self.assertEqual([p['action'] for p in posts],['matrix_entry'])
            song=api.from_yaml(path.read_text(encoding='utf-8'));placed=next(b for b in song['score']['patterns']['A']['beats'] if b['notes'])
            self.assertEqual(placed['at'],[2,1]);self.assertEqual(placed['notes'][0]['pitch'],67)
            # Click the rendered note itself to toggle it, still one shared edit.
            page.mouse.click(*self.roll_point(page,67,32.4));self.settled(page,'S.undo===2')
            self.assertFalse([b for b in api.from_yaml(path.read_text(encoding='utf-8'))['score']['patterns']['A']['beats'] if b['notes']])
            page.evaluate('patUndo(false)');self.settled(page,'S.undo===1')
            undo_redo()
        # A shorter caret duration resizes the chord and inserts into the new rest,
        # atomically, while the next sounding beat stays at quarter 1.
        roll(1);page.evaluate("tab('tab')");page.select_option('[data-ui=duration]','8');page.evaluate("tab('pattern')")
        page.mouse.click(*self.roll_point(page,67,8.4));self.settled(page,'S.undo===1')
        actual=api.from_yaml(path.read_text(encoding='utf-8'))['score']['patterns']['B']['beats']
        self.assertEqual(next(b for b in actual if b['id']=='chord')['written']['value'],8)
        self.assertEqual(next(b for b in actual if any(n['pitch']==67 for n in b['notes']))['at'],[1,2])
        self.assertEqual(next(b for b in actual if b['id']=='next')['at'],[1,1])
        undo_redo()
        roll();page.select_option('#roll-entry','grid');page.evaluate("tab('tab');setEdit(false)")
        self.assertEqual(errors,[])
        return dict(grid_independent=True,toggle=True,chord_retarget=True,exact_history=True,page_errors=errors)

    def test_matrix_entry_real_controls(self):
        with self.muted_page(api.to_yaml(self.matrix_entry_song()),width=1920,height=1080,compact=True) as (page,state,folder):
            self.assertFalse(state.error,state.error);history=list(state.history)
            self.run_matrix_entry(page,folder/'song.yaml');self.assertEqual(list(state.history),history)

    def test_matrix_cross_voice_toggle_and_atomic_peer_refusal(self):
        from tests.test_tablature import beat, note
        with self.muted_page(self.track_roll_song(),compact=True) as (page,state,folder):
            original=(folder/'song.yaml').read_bytes();self.open_track_roll(page)
            page.select_option('#roll-entry','matrix')
            # TG searches voice 1 first even when the click hits voice 2's lane.
            page.mouse.click(*self.roll_hit(page,'#roll [data-score-id="a-1/g1"]')[:2])
            self.settled(page,'S.undo===1')
            notes=[n['id'] for b in state.song['score']['patterns']['a']['beats'] for n in b['notes']]
            self.assertNotIn('g0',notes);self.assertIn('g1',notes)
            page.evaluate('patUndo(false)');self.settled(page,'S.undo===0')
            self.assertEqual((folder/'song.yaml').read_bytes(),original)
        source=self.matrix_entry_song()
        source['score']['patterns']['A']['beats'].append(beat('peer',[1,1],[note('p',66,1,2)],voice=1))
        with self.muted_page(api.to_yaml(source),compact=True) as (page,state,folder):
            original=(folder/'song.yaml').read_bytes()
            page.evaluate("tab('pattern');setEdit(true);setCursor(0,0,0,0);showPattern(0)")
            self.settled(page,'PAT.native&&PAT.order===0');page.evaluate('if(!ROLL.on)rollToggle()')
            page.select_option('#roll-scope','track');page.select_option('#roll-entry','matrix')
            page.evaluate("tab('tab')")
            if not page.locator('.vt-tab-inspector').evaluate('e=>e.open'):page.locator('.vt-tab-inspector > summary').click()
            page.select_option('[data-ui=duration]','4');page.evaluate("tab('pattern')")
            page.mouse.click(*self.roll_point(page,67,14.4))
            page.wait_for_function("document.querySelector('#rollhint').textContent.includes('occupied by the other voice')")
            self.assertEqual((folder/'song.yaml').read_bytes(),original);self.assertFalse(state.history)

    @staticmethod
    def whole_beat_paste_song():
        from tests.test_tablature import TestWholeBeatPaste
        song,_=TestWholeBeatPaste().fixture();song['module']['title']='Whole-beat replacement';song['samples'][1]['file']='a.wav'
        beats=song['score']['patterns']['A']['beats']
        beats[:]=[b for b in beats if b['voice']==0 or b['at'] in ([0,1],[2,1])]
        for b in beats:
            if b['voice']==1:b['written']['value']=2
        return song

    @staticmethod
    def implicit_silence_paste_song():
        from tests.test_tablature import TestWholeBeatPaste
        song, _ = TestWholeBeatPaste().fixture()
        song['module']['title'] = 'Whole-beat silence'
        song['samples'][1]['file'] = 'a.wav'
        beats = song['score']['patterns']['A']['beats']
        beats[:] = [b for b in beats if b['voice'] == 0 and b['at'] in ([0, 1], [2, 1])]
        beats[-1]['written']['value'] = 2
        return song

    @staticmethod
    def matrix_free_song():
        from tests.test_tablature import beat,note
        song=TestTablaturePage.matrix_entry_song();song['module']['title']='Matrix free entry'
        chord=song['score']['patterns']['B']['beats'][0]
        chord['notes'][0]['velocity']=0;chord['notes'][1]['velocity']=63
        song['score']['patterns']['B']['beats'].append(beat('peer',[0,1],[note('low',40,6,0)],2,voice=1))
        return song

    @staticmethod
    def free_duration_repack_song():
        from tests.test_tablature import TestPlaceFitCommand,beat,note
        song,_=TestPlaceFitCommand().fixture();song['module']['title']='Free duration repacking'
        song['samples'][1]['file']='a.wav'
        song['score']['measures']=[dict(id='m'+str(i),meter=[4,4],**{
            'from':dict(occurrence=oid,at=[0,1]),'to':dict(occurrence=oid,at=[4,1])})
            for i,oid in enumerate(song['score']['order_ids'])]
        song['score']['patterns']['A']['beats'].extend([
            beat('peer',[0,1],[note('peer-note',59,2,0)],2,voice=1),
            beat('peer-tail',[2,1],[note('peer-tail-note',60,2,1)],2,voice=1)])
        return song

    @staticmethod
    def free_cohort_song():
        from tests.test_advanced_rhythm import free_cohort_song
        song=free_cohort_song();song['samples'][1]['file']='a.wav'
        return song

    @staticmethod
    def cohort_rest_song():
        from tests.test_advanced_rhythm import cohort_rest_song
        song=cohort_rest_song();song['samples'][1]['file']='a.wav'
        return song

    @staticmethod
    def cohort_annotations_song():
        from tests.test_advanced_rhythm import cohort_rest_song
        song=cohort_rest_song(True);song['samples'][1]['file']='a.wav'
        song['module']['title']='Group annotation transfer'
        next(b for b in song['score']['patterns']['A']['beats'] if b['id']=='c').update(
            text='Keep this text',stroke=dict(direction='up',value=4),pick_stroke='up',
            chord=dict(name='Em',first_fret=1,frets=[0,0,0,2,2,0]))
        return song

    def run_cohort_annotations(self,page,path):
        original=path.read_bytes();errors=[]
        page.on('pageerror',lambda e:errors.append(str(e)))
        page.evaluate("tab('tab');setEdit(true)");page.wait_for_selector('.vt-tab-score svg')
        for panel in ('.vt-tab-inspector','.vt-tab-grid-details'):
            if not page.locator(panel).evaluate('e=>e.open'):page.locator(panel+' > summary').click()
        page.select_option('[data-ui=track]','guitar');page.select_option('[data-ui=voice]',index=0)
        def action(name):
            before=page.evaluate('SCORE.view.revision');page.click('[data-action='+name+']')
            self.settled(page,f'SCORE.view.revision!=={json.dumps(before)}&&SCORE.view.revision.startsWith(S.version.hash)')
        page.click('.vt-tab-grid [data-beat="b"][data-string="1"]');action('cut')
        saved=path.read_bytes();page.click('.vt-tab-grid [data-note="c-note"]')
        self.assertEqual(page.input_value('[data-ui=stroke-direction]'),'up')
        self.assertEqual(page.input_value('[data-ui=stroke-value]'),'4')
        self.assertEqual(page.input_value('[data-ui=pick-stroke]'),'up')
        self.assertEqual(page.input_value('[data-ui=beat-text]'),'')
        page.click('[data-action=chord-diagram]')
        self.assertEqual(page.input_value('[data-ui=chord-name]'),'Em')
        page.click('[data-action=close-chord-diagram]')
        page.click('.vt-tab-grid [data-beat="r"][data-string="1"]')
        self.assertEqual(page.input_value('[data-ui=beat-text]'),'Keep this text')
        self.assertEqual(page.input_value('[data-ui=stroke-direction]'),'')
        action('undo');self.assertEqual(path.read_bytes(),original)
        action('redo');self.assertEqual(path.read_bytes(),saved)
        action('undo');self.assertEqual(path.read_bytes(),original)
        page.locator('.vt-tab-grid-details > summary').click();page.evaluate('setEdit(false)');self.assertEqual(errors,[])
        return dict(chord_stroke_transferred=True,text_retained=True,exact_history=True,page_errors=errors)

    @staticmethod
    def annotated_fit_song():
        from tests.test_advanced_rhythm import cohort_rest_song
        song=cohort_rest_song();song['samples'][1]['file']='a.wav';song['module']['title']='Annotated rhythm Fit'
        for track in song['score']['tracks'].values():track['midi']=dict(program=25,bank=0)
        for pattern in song['score']['patterns'].values():
            for beat in pattern['beats']:
                for note in beat['notes']:note['velocity']=95
        next(b for b in song['score']['patterns']['A']['beats'] if b['id']=='b').update(
            text='Follow the phrase',stroke=dict(direction='up',value=4),pick_stroke='up',
            chord=dict(name='Em',first_fret=1,frets=[0,0,0,2,2,0]))
        return song

    def run_annotated_fit(self,page,path):
        original=path.read_bytes();errors=[]
        page.on('pageerror',lambda e:errors.append(str(e)))
        page.evaluate("tab('tab');setEdit(true)");page.wait_for_selector('.vt-tab-score svg')
        for panel in ('.vt-tab-inspector','.vt-tab-grid-details'):
            if not page.locator(panel).evaluate('e=>e.open'):page.locator(panel+' > summary').click()
        page.select_option('[data-ui=track]','guitar');page.select_option('[data-ui=voice]',index=0)
        def action(name):
            before=page.evaluate('SCORE.view.revision');page.click('[data-action='+name+']')
            self.settled(page,f'SCORE.view.revision!=={json.dumps(before)}&&SCORE.view.revision.startsWith(S.version.hash)')
        for value,dots,at in (('2','0',[2,1]),('4','1',[3,2])):
            page.click('.vt-tab-grid [data-note="a-note"]');page.check('[data-ui=fit]')
            self.assertFalse(page.is_checked('[data-ui=free-edit]'))
            page.select_option('[data-ui=duration]',value);page.select_option('[data-ui=dots]',dots);action('duration')
            saved=path.read_bytes();beats=api.from_yaml(saved.decode('utf-8'))['score']['patterns']['A']['beats']
            self.assertEqual(next(b for b in beats if b['id']=='b')['at'],at)
            page.click('.vt-tab-grid [data-note="b-note"]')
            self.assertEqual(page.input_value('[data-ui=beat-text]'),'Follow the phrase')
            self.assertEqual(page.input_value('[data-ui=stroke-direction]'),'up')
            self.assertEqual(page.input_value('[data-ui=pick-stroke]'),'up')
            page.click('[data-action=chord-diagram]');self.assertEqual(page.input_value('[data-ui=chord-name]'),'Em')
            page.click('[data-action=close-chord-diagram]')
            if dots=='1':
                from vulturetracker import gpimport
                with tempfile.TemporaryDirectory(prefix='vt-annotated-fit-') as destination:
                    page.click('[data-t=export]');page.select_option('#export-format','gp5');page.uncheck('#export-stems')
                    page.fill('#export-dest',destination);page.fill('#export-name','fitted')
                    with page.expect_response('**/api/export') as response:page.click('#export-go')
                    self.assertEqual(response.value.status,200,response.value.text())
                    page.wait_for_function("['done','error','failed','cancelled'].includes(S.export?.status)",timeout=20000)
                    self.assertEqual(page.evaluate('S.export.status'),'done',page.evaluate('S.export'))
                    restored=gpimport._native_gp_song(gpimport._read_native_gp((Path(destination)/'fitted.gp5').read_bytes()),'Fit')
                    annotated=[b for p in restored['score']['patterns'].values() for b in p['beats'] if b.get('text')=='Follow the phrase']
                    self.assertEqual(len(annotated),1);self.assertEqual(annotated[0]['at'],[3,2])
                    self.assertEqual(annotated[0]['chord']['name'],'Em')
                self.assertEqual(path.read_bytes(),saved);page.evaluate("tab('tab')")
            action('undo');self.assertEqual(path.read_bytes(),original)
            action('redo');self.assertEqual(path.read_bytes(),saved)
            action('undo');self.assertEqual(path.read_bytes(),original)
        page.locator('.vt-tab-grid-details > summary').click();page.evaluate('setEdit(false)');self.assertEqual(errors,[])
        return dict(half_fit=True,dotted_fit=True,annotations=True,gp5_export=True,exact_history=True,page_errors=errors)

    def test_annotated_fit_real_controls(self):
        with self.muted_page(api.to_yaml(self.annotated_fit_song()),width=1920,height=1080,compact=True) as (page,state,folder):
            self.assertFalse(state.error,state.error);self.run_annotated_fit(page,folder/'song.yaml')

    def test_cohort_annotations_real_controls(self):
        with self.muted_page(api.to_yaml(self.cohort_annotations_song()),width=1920,height=1080,compact=True) as (page,state,folder):
            self.assertFalse(state.error,state.error);self.run_cohort_annotations(page,folder/'song.yaml')

    def run_cohort_rest_fit(self,page,path):
        original=path.read_bytes();errors=[]
        page.on('pageerror',lambda e:errors.append(str(e)))
        page.evaluate("tab('tab');setEdit(true)");page.wait_for_selector('.vt-tab-score svg')
        for panel in ('.vt-tab-inspector','.vt-tab-grid-details'):
            if not page.locator(panel).evaluate('e=>e.open'):page.locator(panel+' > summary').click()
        page.select_option('[data-ui=track]','guitar');page.select_option('[data-ui=voice]',index=0)
        def action(name):
            before=page.evaluate('SCORE.view.revision');page.click('[data-action='+name+']')
            self.settled(page,f'SCORE.view.revision!=={json.dumps(before)}&&SCORE.view.revision.startsWith(S.version.hash)')
        def beats():return {b['id']:b for b in api.from_yaml(path.read_text(encoding='utf-8'))['score']['patterns']['A']['beats']}
        page.click('.vt-tab-grid [data-note="b-note"]');self.assertFalse(page.is_checked('[data-ui=free-edit]'))
        action('insert-rest');inserted=path.read_bytes();current=beats()
        self.assertEqual([current[k]['at'] for k in ('b','c')],[[2,1],[3,1]])
        rest=next(b for b in current.values() if b['voice']==0 and b['at']==[1,1])
        self.assertEqual(rest.get('cohort',0),current['peer-tail'].get('cohort',0))
        action('undo');self.assertEqual(path.read_bytes(),original)
        action('redo');self.assertEqual(path.read_bytes(),inserted)
        action('undo');self.assertEqual(path.read_bytes(),original)
        page.click('.vt-tab-grid [data-note="a-note"]');page.check('[data-ui=fit]')
        page.select_option('[data-ui=duration]','4');page.select_option('[data-ui=dots]','1');action('duration')
        fitted=path.read_bytes();current=beats()
        self.assertEqual([current[k]['at'] for k in ('b','c','peer-tail')],[[3,2],[5,2],[1,1]])
        action('undo');self.assertEqual(path.read_bytes(),original)
        action('redo');self.assertEqual(path.read_bytes(),fitted)
        action('undo');self.assertEqual(path.read_bytes(),original)
        page.uncheck('[data-ui=fit]');page.click('.vt-tab-grid [data-note="b-note"]');action('rest');rested=path.read_bytes()
        page.click('.vt-tab-grid [data-beat="b"][data-string="1"]');action('cut');cut=path.read_bytes();current=beats()
        self.assertEqual(current['c']['at'],[1,1])
        self.assertEqual(current['c'].get('cohort',0),current['peer-tail'].get('cohort',0))
        self.assertEqual(current['peer-tail']['notes'][0]['pitch'],60)
        for expected in (rested,original):action('undo');self.assertEqual(path.read_bytes(),expected)
        for expected in (rested,cut):action('redo');self.assertEqual(path.read_bytes(),expected)
        for expected in (rested,original):action('undo');self.assertEqual(path.read_bytes(),expected)
        page.locator('.vt-tab-grid-details > summary').click();page.evaluate('setEdit(false)');self.assertEqual(errors,[])
        return dict(insert_rebinds=True,fit_preserves_peer=True,rest_cut_rebinds=True,exact_history=True,page_errors=errors)

    def test_cohort_rest_fit_real_controls(self):
        with self.muted_page(api.to_yaml(self.cohort_rest_song()),width=1920,height=1080,compact=True) as (page,state,folder):
            self.assertFalse(state.error,state.error);self.run_cohort_rest_fit(page,folder/'song.yaml')

    def run_free_cohorts(self,page,path):
        original=path.read_bytes();errors=[]
        page.on('pageerror',lambda e:errors.append(str(e)))
        def open_tab():
            page.evaluate("tab('tab');setEdit(true)");page.wait_for_selector('.vt-tab-score svg')
            for panel in ('.vt-tab-inspector','.vt-tab-grid-details'):
                if not page.locator(panel).evaluate('e=>e.open'):page.locator(panel+' > summary').click()
            page.select_option('[data-ui=track]','guitar')
        def action(name):
            before=page.evaluate('SCORE.view.revision');page.click('[data-action='+name+']')
            self.settled(page,f'SCORE.view.revision!=={json.dumps(before)}&&SCORE.view.revision.startsWith(S.version.hash)')
        open_tab();page.select_option('[data-ui=voice]',index=1);page.click('.vt-tab-grid [data-note="pn0"]')
        self.assertEqual(page.evaluate('CUR.score.voice'),1)
        page.check('[data-ui=free-edit]');page.select_option('[data-ui=duration]','4');action('duration')
        aligned=path.read_bytes();beats=api.from_yaml(aligned.decode('utf-8'))['score']['patterns']['A']['beats']
        self.assertEqual({b['id']:b['at'] for b in beats if b['id'] in ('b','peer-tail')},
                         {'b':[1,1],'peer-tail':[1,1]})
        self.assertEqual(next(b for b in beats if b['id']=='peer-tail')['cohort'],1)
        page.reload();page.wait_for_function("typeof S!=='undefined'&&S?.song?.facts");open_tab()
        page.select_option('[data-ui=voice]',index=0);page.click('.vt-tab-grid [data-note="a-note"]');page.check('[data-ui=free-edit]')
        page.select_option('[data-ui=duration]','8');action('duration');separated=path.read_bytes()
        beats=api.from_yaml(separated.decode('utf-8'))['score']['patterns']['A']['beats']
        self.assertEqual({b['id']:b['at'] for b in beats},
                         dict(a=[0,1],b=[1,2],c=[3,2],peer=[0,1],**{'peer-tail':[1,1]}))
        self.assertEqual(page.evaluate('CUR.score.beat'),'a')
        self.assertEqual(page.input_value('[data-ui=duration]'),'8')
        for expected in (aligned,original):action('undo');self.assertEqual(path.read_bytes(),expected)
        for expected in (aligned,separated):action('redo');self.assertEqual(path.read_bytes(),expected)
        for expected in (aligned,original):action('undo');self.assertEqual(path.read_bytes(),expected)
        page.uncheck('[data-ui=free-edit]');page.locator('.vt-tab-grid-details > summary').click()
        page.evaluate('setEdit(false)');self.assertEqual(errors,[])
        return dict(distinct_groups=True,reload=True,repeated_duration=True,exact_two_step_history=True,page_errors=errors)

    def test_free_cohorts_real_controls(self):
        with self.muted_page(api.to_yaml(self.free_cohort_song()),width=1920,height=1080,compact=True) as (page,state,folder):
            self.assertFalse(state.error,state.error);self.run_free_cohorts(page,folder/'song.yaml')

    def run_free_duration_repack(self,page,path):
        original=path.read_bytes();errors=[]
        page.on('pageerror',lambda e:errors.append(str(e)))
        page.evaluate("tab('tab');setEdit(true)");page.wait_for_selector('.vt-tab-score svg')
        if not page.locator('.vt-tab-inspector').evaluate('e=>e.open'):page.locator('.vt-tab-inspector > summary').click()
        grid_open=page.locator('.vt-tab-grid-details').evaluate('e=>e.open')
        if not grid_open:page.locator('.vt-tab-grid-details > summary').click()
        page.select_option('[data-ui=track]','guitar')
        def action(name):
            before=page.evaluate('SCORE.view.revision');page.click('[data-action='+name+']')
            self.settled(page,f'SCORE.view.revision!=={json.dumps(before)}&&SCORE.view.revision.startsWith(S.version.hash)')
        for value,positions,rows in (('8',{'a':[0,1],'b':[1,2],'r':[2,1],'c':[3,1],'peer':[0,1],'peer-tail':[2,1]},48),
                                     ('2',{'a':[0,1],'b':[2,1],'r':[3,1],'c':[4,1],'peer':[0,1],'peer-tail':[3,1]},60)):
            page.click('.vt-tab-grid [data-note="a-note"]');page.check('[data-ui=free-edit]');page.check('[data-ui=fit]')
            page.select_option('[data-ui=duration]',value)
            with page.expect_request('**/api/score_command') as request:action('duration')
            self.assertTrue(request.value.post_data_json['free'])
            actual=api.from_yaml(path.read_text(encoding='utf-8'));beats=actual['score']['patterns']['A']['beats']
            self.assertEqual({b['id']:b['at'] for b in beats},positions)
            self.assertEqual(actual['patterns']['A']['rows'],rows)
            self.assertEqual(page.input_value('[data-ui=duration]'),value)
            self.assertEqual(page.evaluate('CUR.score.beat'),'a')
            self.assertEqual(page.evaluate('S.undo'),1)
            if rows==60:self.assertTrue(any('long' in e['errors'] for e in page.evaluate('SCORE.view.measure_errors')))
            saved=path.read_bytes();action('undo');self.assertEqual(path.read_bytes(),original)
            action('redo');self.assertEqual(path.read_bytes(),saved)
            action('undo');self.assertEqual(path.read_bytes(),original)
        page.uncheck('[data-ui=free-edit]');page.uncheck('[data-ui=fit]');page.evaluate('setEdit(false)')
        if not grid_open:page.locator('.vt-tab-grid-details > summary').click()
        self.assertEqual(errors,[])
        return dict(shrink=True,growth=True,paired_voice_cohorts=True,free_precedes_fit=True,
                    caret_retained=True,exact_history=True,page_errors=errors)

    def test_free_duration_repack_real_controls(self):
        with self.muted_page(api.to_yaml(self.free_duration_repack_song()),width=1920,height=1080,compact=True) as (page,state,folder):
            self.assertFalse(state.error,state.error);self.run_free_duration_repack(page,folder/'song.yaml')

    @staticmethod
    def invalid_bar_song():
        song=TestTablaturePage.free_duration_repack_song();song['module']['title']='Invalid bar repair'
        song['score']['measures']=[]
        return song

    def run_invalid_bar(self,page,path):
        original=path.read_bytes();errors=[]
        page.on('pageerror',lambda e:errors.append(str(e)))
        def open_tab():
            page.evaluate("tab('tab');setEdit(true)");page.wait_for_selector('.vt-tab-score svg')
            for panel in ('.vt-tab-inspector','.vt-tab-grid-details'):
                if not page.locator(panel).evaluate('e=>e.open'):page.locator(panel+' > summary').click()
            page.select_option('[data-ui=track]','guitar')
        def action(name):
            before=page.evaluate('SCORE.view.revision');page.click('[data-action='+name+']')
            self.settled(page,f'SCORE.view.revision!=={json.dumps(before)}&&SCORE.view.revision.startsWith(S.version.hash)')
        open_tab();page.click('.vt-tab-grid [data-note="a-note"]')
        self.assertFalse(page.is_checked('[data-ui=free-edit]'));page.check('[data-ui=free-edit]')
        page.select_option('[data-ui=duration]','2');action('duration');grown=path.read_bytes()
        measure=api.from_yaml(grown.decode('utf-8'))['score']['measures'][0]
        self.assertEqual(measure['meter'],[4,4]);self.assertEqual(measure['to']['at'],[5,1])
        page.reload();page.wait_for_function("typeof S!=='undefined'&&S?.song?.facts");open_tab()
        page.click('.vt-tab-grid [data-note="a-note"]')
        self.assertTrue(page.is_checked('[data-ui=free-edit]'));self.assertTrue(page.is_disabled('[data-ui=free-edit]'))
        self.assertTrue(page.is_visible('[data-ui=free-required]'))
        page.select_option('[data-ui=duration]','4');action('duration');corrected=path.read_bytes()
        self.assertFalse(page.is_disabled('[data-ui=free-edit]'));self.assertFalse(page.is_checked('[data-ui=free-edit]'))
        self.assertTrue(page.is_hidden('[data-ui=free-required]'))
        page.click('[data-action=measures]');page.select_option('[data-ui=measure]',measure['id'])
        before=page.evaluate('SCORE.view.revision');page.get_by_role('button',name='Apply measure',exact=True).click()
        self.settled(page,f'SCORE.view.revision!=={json.dumps(before)}&&S.undo===3')
        page.click('[data-action=close-measures]');repaired=path.read_bytes()
        self.assertEqual(api.from_yaml(repaired.decode('utf-8'))['patterns']['A']['rows'],48)
        for expected in (corrected,grown,original):action('undo');self.assertEqual(path.read_bytes(),expected)
        for expected in (grown,corrected,repaired):action('redo');self.assertEqual(path.read_bytes(),expected)
        for expected in (corrected,grown,original):action('undo');self.assertEqual(path.read_bytes(),expected)
        page.locator('.vt-tab-grid-details > summary').click();page.evaluate('setEdit(false)')
        self.assertEqual(errors,[])
        return dict(nominal_meter_retained=True,automatic_after_reload=True,required_mode_visible=True,
                    mode_clears_when_valid=True,repair_empty_rows=True,exact_three_step_history=True,page_errors=errors)

    def test_invalid_bar_automatic_free_and_repair_real_controls(self):
        with self.muted_page(api.to_yaml(self.invalid_bar_song()),width=1920,height=1080,compact=True) as (page,state,folder):
            self.assertFalse(state.error,state.error);self.run_invalid_bar(page,folder/'song.yaml')

    def run_matrix_free(self,page,path):
        original=path.read_bytes();errors=[]
        page.on('pageerror',lambda e:errors.append(str(e)))
        page.evaluate("tab('tab');setEdit(true)");page.wait_for_selector('.vt-tab-score svg')
        if not page.locator('.vt-tab-inspector').evaluate('e=>e.open'):page.locator('.vt-tab-inspector > summary').click()
        page.select_option('[data-ui=track]','guitar')
        page.evaluate("""async()=>{await lvStart();window.matrixSounds=[];window.matrixLiveOn=lvNoteOn;window.matrixLiveOff=lvNoteOff;
          lvNoteOn=(...a)=>matrixSounds.push({kind:'on',args:a,time:performance.now()});
          lvNoteOff=(...a)=>matrixSounds.push({kind:'off',args:a,time:performance.now()});}""")
        def roll(order):
            page.evaluate("o=>{tab('pattern');setCursor(o,0,0,0);showPattern(o)}",order)
            self.settled(page,f'PAT.order==={order}&&PAT.native')
            page.evaluate('async()=>{await scoreRefresh()}')
            page.evaluate('if(!ROLL.on)rollToggle()');page.select_option('#roll-scope','track')
            page.select_option('#roll-entry','matrix');self.settled(page,"rollTrack()==='guitar'")
        def sounds(pitches):
            page.wait_for_function('n=>matrixSounds.filter(e=>e.kind==="off").length===n',arg=len(pitches))
            events=page.evaluate('matrixSounds');ons=[e for e in events if e['kind']=='on'];offs=[e for e in events if e['kind']=='off']
            self.assertEqual(sorted(e['args'][2] for e in ons),sorted(pitches))
            self.assertEqual(len({e['args'][0] for e in ons}),len(pitches))
            for on in ons:
                off=next(e for e in offs if e['args'][0]==on['args'][0])
                self.assertGreaterEqual(off['time']-on['time'],450)
            return ons
        def ready(count):self.settled(page,f'S.undo==={count}&&SCORE.view.revision.startsWith(S.version.hash)')
        def history():
            saved=path.read_bytes()
            for redo,expected,count in ((False,original,0),(True,saved,1),(False,original,0)):
                page.evaluate('async redo=>{patUndo(redo);await EDQ.chain;await scoreRefresh()}',redo)
                ready(count);self.assertEqual(path.read_bytes(),expected)
        roll(0);page.evaluate("tab('tab')");page.select_option('[data-ui=duration]','4')
        page.check('[data-ui=free-edit]');page.check('[data-ui=fit]');page.evaluate("tab('pattern');matrixSounds=[]")
        page.mouse.click(*self.roll_point(page,67,32.4));ready(1);sounds([67])
        current=api.from_yaml(path.read_text(encoding='utf-8'));added=next(b for b in current['score']['patterns']['A']['beats'] if b['notes'])
        self.assertEqual(added['at'],[0,1]);history()
        for free,expected,at in ((True,[40,59,64,67],[0,1]),(False,[40,59,64],[1,2])):
            roll(1);page.evaluate("tab('tab')");page.select_option('[data-ui=duration]','8')
            page.locator('[data-ui=free-edit]').set_checked(free);page.evaluate("tab('pattern');matrixSounds=[]")
            page.mouse.click(*self.roll_point(page,67,8.4));ready(1);ons=sounds(expected)
            self.assertEqual(next(e['args'][3] for e in ons if e['args'][2]==64),0)
            current=api.from_yaml(path.read_text(encoding='utf-8'))
            added=next(b for b in current['score']['patterns']['B']['beats'] if any(n['pitch']==67 for n in b['notes']))
            self.assertEqual(added['at'],at);history()
        roll(0);page.evaluate("tab('tab')")
        page.select_option('[data-ui=voice]',index=1)
        self.assertEqual(page.evaluate('[CUR.score?.voice,document.querySelector("[data-ui=voice]").value]'),[1,'1'])
        page.evaluate("tab('pattern');matrixSounds=[]")
        self.assertEqual(page.evaluate('[CUR.score?.voice,document.querySelector("[data-ui=voice]").value]'),[1,'1'])
        page.mouse.click(*self.roll_point(page,67,8.4))
        self.settled(page,"document.querySelector('#rollhint').textContent.includes('Audition only')")
        sounds([67]);self.assertEqual(path.read_bytes(),original);self.assertEqual(page.evaluate('S.undo'),0)
        # A transport boundary while the engine starts cancels the queued preview.
        page.evaluate("()=>{matrixSounds=[];window.matrixStart=lvStart;lvStart=()=>new Promise(resolve=>window.matrixRelease=resolve)}")
        page.mouse.click(*self.roll_point(page,67,8.4));page.wait_for_function('typeof matrixRelease==="function"')
        page.evaluate('async()=>{playEpoch++;matrixRelease();lvStart=matrixStart;await Promise.resolve();await Promise.resolve()}')
        self.assertEqual(page.evaluate('matrixSounds'),[]);self.assertEqual(path.read_bytes(),original)
        page.evaluate("tab('tab')");page.select_option('[data-ui=voice]','0');page.uncheck('[data-ui=free-edit]')
        page.uncheck('[data-ui=fit]');page.evaluate('setEdit(false);lvNoteOn=matrixLiveOn;lvNoteOff=matrixLiveOff');self.assertEqual(errors,[])
        return dict(free_anchor=True,free_precedes_fit=True,normal_retarget=True,original_cohort_preview=True,
                    simultaneous_500ms=True,zero_velocity=True,absent_voice_no_edit=True,exact_history=True,page_errors=errors)

    def test_matrix_free_entry_and_audition_real_controls(self):
        with self.muted_page(api.to_yaml(self.matrix_free_song()),width=1920,height=1080,compact=True) as (page,state,folder):
            self.assertFalse(state.error,state.error);self.run_matrix_free(page,folder/'song.yaml')

    def run_whole_beat_paste(self,page,path,failed_responses=None):
        original=path.read_bytes();errors=[];posts=[]
        implicit = api.from_yaml(original.decode('utf-8'))['module']['title'] == 'Whole-beat silence'
        second_index = 2 if implicit else 1
        page.on('pageerror',lambda e:errors.append(str(e)))
        page.on('request',lambda r:posts.append(r.post_data_json) if r.method=='POST' and urlsplit(r.url).path=='/api/score' else None)
        page.evaluate("tab('tab');setEdit(true)");page.wait_for_selector('.vt-tab-score svg')
        if not page.locator('.vt-tab-inspector').evaluate('e=>e.open'):page.locator('.vt-tab-inspector > summary').click()
        self.capture_engraving(page);page.select_option('[data-ui=track]','guitar')
        self.settled(page,'window.tabRendered&&tabRenderApi.boundsLookup?.isFinished')
        def ready(count):
            self.settled(page,f'S.undo==={count}&&SCORE.view.revision.startsWith(S.version.hash)&&tabRenderedRevision===SCORE.view.revision&&tabRenderApi.boundsLookup?.isFinished')
        self.click_tab_lane(page,0,0,1)
        page.keyboard.down('Shift');self.click_tab_lane(page,0,second_index,1);page.keyboard.up('Shift')
        page.click('[data-action=copy]');page.wait_for_function(f"document.querySelector('.vt-tab-status').textContent.startsWith('Copied {2 if implicit else 3} beats')")
        for action,mode,onset in (('paste-replace','tg_replace',[2,1]),('paste-span',None,[second_index,1]),('keyboard','tg_replace',[2,1])):
            self.click_tab_lane(page,1,0,1);posts.clear()
            if action=='keyboard':page.locator('#tab-editor').focus();page.keyboard.press('Control+v')
            else:page.click(f'[data-action={action}]')
            ready(1)
            self.assertEqual(posts[-1].get('mode'),mode)
            target=api.from_yaml(path.read_text(encoding='utf-8'))['score']['patterns']['B']['beats']
            second=next(b for b in target if any(n['id'].startswith(f'copy_0n{second_index}') for n in b['notes']))
            self.assertEqual(second['at'],onset)
            self.assertEqual(any(b['voice']==1 and b['at']==[2,1] and b['notes'] for b in target),mode is None)
            if mode:
                self.assertIn(f'copy_0b{second_index}',page.locator('.vt-tab-selection').evaluate_all('els=>els.map(e=>e.dataset.beat)'))
            saved=path.read_bytes()
            for redo,expected,count in ((False,original,0),(True,saved,1),(False,original,0)):
                page.evaluate('redo=>patUndo(redo)',redo);ready(count);self.assertEqual(path.read_bytes(),expected)
        # Same complete clipboard at the final quarter must refuse as one transaction.
        self.click_tab_lane(page,1,3,1);page.click('[data-action=paste-replace]')
        page.wait_for_function("document.querySelector('.vt-tab-status').textContent.includes('insufficient room')")
        self.assertEqual(path.read_bytes(),original);self.assertEqual(page.evaluate('S.undo'),0)
        if failed_responses is not None:
            failed_responses[:]=[r for r in failed_responses if not (
                r.url.endswith('/api/score') and r.status==400 and
                r.json().get('error')=='ValueError: whole-beat paste has insufficient room; no notes were cleared')]
        self.click_tab_lane(page,0,0,1);page.evaluate('setEdit(false)');self.assertEqual(errors,[])
        return dict(whole_both_voices=True,unequal_cohort_advance=True,span_preserved=True,
                    keyboard=True,exact_history=True,atomic_overflow=True,page_errors=errors)

    def test_whole_beat_paste_real_controls_and_span_alternative(self):
        with self.muted_page(api.to_yaml(self.whole_beat_paste_song()),width=1920,height=1080,compact=True) as (page,state,folder):
            self.assertFalse(state.error,state.error)
            self.run_whole_beat_paste(page,folder/'song.yaml');self.assertFalse(state.history)

    def test_implicit_silence_paste_real_controls_and_span_alternative(self):
        with self.muted_page(api.to_yaml(self.implicit_silence_paste_song()),width=1920,height=1080,compact=True) as (page,state,folder):
            self.run_whole_beat_paste(page,folder/'song.yaml');self.assertFalse(state.history)

    @staticmethod
    def clipboard_workflow_song():
        from tests.test_tablature import TestMatrixEntry,beat,note
        song,_=TestMatrixEntry().fixture();song['module']['title']='Clipboard workflow';song['samples'][1]['file']='a.wav'
        for name,base in (('A',64),('B',69)):
            song['score']['patterns'][name]['beats']=[beat(f'{name}{i}',[i,1],[note(f'{name}n{i}',base+i,1,base+i-64)]) for i in range(4)]
        song['score']['measures']=[dict(id=name,meter=[4,4],**{'from':dict(occurrence=oid,at=[0,1]),'to':dict(occurrence=oid,at=[4,1])})
                                   for name,oid in (('A','oa'),('B','ob'))]
        return song

    def run_clipboard_workflow(self,page,path):
        original=path.read_bytes();errors=[];posts=[]
        page.on('pageerror',lambda e:errors.append(str(e)))
        page.on('request',lambda r:posts.append(r.post_data_json) if r.method=='POST' and urlsplit(r.url).path in ('/api/score','/api/score_command') else None)
        page.evaluate("tab('tab');setEdit(true)");page.wait_for_selector('.vt-tab-score svg')
        if not page.locator('.vt-tab-inspector').evaluate('e=>e.open'):page.locator('.vt-tab-inspector > summary').click()
        self.capture_engraving(page);page.select_option('[data-ui=track]','guitar')
        self.settled(page,'window.tabRendered&&tabRenderApi.boundsLookup?.isFinished')
        def key(keys):page.locator('#tab-editor').focus();page.keyboard.press(keys)
        def history():
            saved=path.read_bytes()
            for redo,expected,count in ((False,original,0),(True,saved,1),(False,original,0)):
                page.evaluate('redo=>patUndo(redo)',redo)
                self.settled(page,f'S.undo==={count}&&SCORE.view.revision.startsWith(S.version.hash)&&tabRenderedRevision===SCORE.view.revision&&tabRenderApi.boundsLookup?.isFinished')
                self.assertEqual(path.read_bytes(),expected)
        self.click_tab_lane(page,0,0,1);key('Control+c')
        self.assertTrue(page.locator('[data-panel=measures]').is_visible());self.assertEqual(posts,[])
        page.click('[data-action=close-measures]')
        page.click('[data-action=copy]');page.wait_for_function("document.querySelector('.vt-tab-status').textContent.startsWith('Copied 1 beat')")
        self.open_panel(page,'measures');page.fill('[data-ui=ops-from]','2');page.fill('[data-ui=ops-to]','2')
        page.click('[data-action=measure-copy]');page.wait_for_function("document.querySelector('.vt-tab-status').textContent.startsWith('Copied measure 2')")
        page.click('[data-action=close-measures]');posts.clear();key('Control+v')
        self.assertTrue(page.locator('[data-panel=measures]').is_visible());self.assertEqual(posts,[])
        self.assertTrue(page.is_disabled('[data-action=paste-safe]'))
        page.fill('[data-ui=ops-from]','1');page.fill('[data-ui=ops-count]','1');page.click('[data-action=measure-paste]')
        self.settled(page,'S.undo===1&&tabRenderedRevision===SCORE.view.revision&&tabRenderApi.boundsLookup?.isFinished')
        actual=api.from_yaml(path.read_text(encoding='utf-8'))
        self.assertEqual([n['pitch'] for b in actual['score']['patterns']['A']['beats'] for n in b['notes']],[69,70,71,72])
        page.click('[data-action=close-measures]');history()
        self.click_tab_lane(page,0,0,1);page.click('[data-action=copy]')
        page.wait_for_function("document.querySelector('.vt-tab-status').textContent.startsWith('Copied 1 beat')")
        self.assertTrue(page.is_disabled('[data-action=measure-paste]'))
        # Cancelling the no-selection measure dialog retains the successful beat copy.
        key('Control+c');self.assertTrue(page.locator('[data-panel=measures]').is_visible());page.click('[data-action=close-measures]')
        for first,last,pattern,onset in (([1,1],[1,3],'B',1),([1,3],[1,1],'B',1),([0,3],[1,1],'A',3)):
            self.click_tab_lane(page,*first,1)
            page.keyboard.down('Shift');self.click_tab_lane(page,*last,1);page.keyboard.up('Shift')
            posts.clear();key('Control+v')
            self.settled(page,'S.undo===1&&tabRenderedRevision===SCORE.view.revision&&tabRenderApi.boundsLookup?.isFinished')
            request=next(p for p in posts if p.get('op')=='beats_paste')
            self.assertTrue(request['replace']);self.assertEqual(request['occurrence'],'oa' if pattern=='A' else 'ob')
            self.assertEqual(request['row'],[onset*12,1])
            actual=api.from_yaml(path.read_text(encoding='utf-8'))
            changed=next(b for b in actual['score']['patterns'][pattern]['beats'] if b['at']==[onset,1])
            self.assertEqual(changed['notes'][0]['pitch'],64)
            self.assertEqual(len([n for p in actual['score']['patterns'].values() for b in p['beats'] for n in b['notes']]),8)
            history()
        self.click_tab_lane(page,0,0,1);page.evaluate('setEdit(false)');self.assertEqual(errors,[])
        return dict(latest_clipboard_kind=True,cancel_preserves_copy=True,measure_replace=True,selection_first=True,
                    directions=['forward','backward','cross-bar'],exact_history=True,page_errors=errors)

    def test_clipboard_context_and_selection_start_real_controls(self):
        with self.muted_page(api.to_yaml(self.clipboard_workflow_song()),width=1920,height=1080,compact=True) as (page,state,folder):
            self.assertFalse(state.error,state.error);history=list(state.history)
            self.run_clipboard_workflow(page,folder/'song.yaml');self.assertEqual(list(state.history),history)

    def test_failed_measure_copy_blocks_paste_and_keeps_beat_clipboard(self):
        with self.muted_page(api.to_yaml(self.clipboard_workflow_song()),compact=True) as (page,state,folder):
            original=(folder/'song.yaml').read_bytes();page.evaluate("tab('tab');setEdit(true)")
            page.wait_for_selector('.vt-tab-score svg')
            if not page.locator('.vt-tab-inspector').evaluate('e=>e.open'):page.locator('.vt-tab-inspector > summary').click()
            page.click('[data-action=copy]');page.wait_for_function("document.querySelector('.vt-tab-status').textContent.startsWith('Copied 1 beat')")
            self.open_panel(page,'measures')
            page.route('**/api/measure_copy',lambda route:route.fulfill(status=200,content_type='application/json',body='{"error":"measure copy test refusal"}'))
            posts=[];page.on('request',lambda r:posts.append(r.url) if r.method=='POST' and urlsplit(r.url).path in ('/api/score','/api/score_command') else None)
            page.evaluate("""()=>{document.querySelector('[data-action=measure-copy]').click();const root=document.getElementById('tab-editor');root.focus();
                root.dispatchEvent(new KeyboardEvent('keydown',{key:'v',ctrlKey:true,bubbles:true,cancelable:true}))}""")
            page.wait_for_function("document.querySelector('.vt-tab-status').textContent.includes('measure copy test refusal')")
            self.assertEqual(posts,[]);self.assertEqual((folder/'song.yaml').read_bytes(),original)
            page.click('[data-action=close-measures]')
            self.assertFalse(page.is_disabled('[data-action=paste-safe]'))
            page.evaluate("async()=>{setCursor(1,0,0,0);await scoreRefresh()}");self.settled(page,'SCORE.view.order===1')
            page.locator('#tab-editor').focus();page.keyboard.press('Control+v');self.settled(page,'S.undo===1')
            self.assertEqual(next(b for b in state.song['score']['patterns']['B']['beats'] if b['at']==[0,1])['notes'][0]['pitch'],64)
            page.evaluate('patUndo(false)');self.settled(page,'S.undo===0');self.assertEqual((folder/'song.yaml').read_bytes(),original)

    def test_stem_group_real_controls(self):
        with self.muted_page(api.to_yaml(self.stem_group_song()),width=1920,height=1080,compact=True) as (page,state,folder):
            self.assertFalse(state.error,state.error);history=list(state.history)
            self.run_stem_groups(page,folder/'song.yaml');self.assertEqual(list(state.history),history)

    def run_selection_pitch(self,page,path,expected_failures=None):
        original=path.read_bytes();source=api.from_yaml(original.decode('utf-8'));errors=[]
        page.on('pageerror',lambda error:errors.append(str(error)))
        page.evaluate("tab('tab');setEdit(true)");page.wait_for_selector('.vt-tab-score svg')
        if not page.locator('.vt-tab-inspector').evaluate('e=>e.open'):page.locator('.vt-tab-inspector > summary').click()
        self.capture_engraving(page);page.select_option('[data-ui=track]','guitar')
        self.settled(page,'window.tabRendered&&tabRenderApi.boundsLookup?.isFinished')
        def local_range():
            page.select_option('[data-ui=voice]',index=0)
            start,end=(self.tab_lane_point(page,0,i,2) for i in (0,1))
            page.mouse.move(start['x'],start['y']);page.mouse.down();page.mouse.move(end['x'],end['y'],steps=5);page.mouse.up()
            page.locator('#tab-editor').focus()
        def action(key):
            rev=page.evaluate('SCORE.view.revision')
            if key.startswith('Shift+'):page.locator('#tab-editor').focus();page.keyboard.press(key)
            else:page.click('[data-action='+key+']')
            self.settled(page,f'SCORE.view.revision!=={json.dumps(rev)}&&tabRenderedRevision===SCORE.view.revision&&tabRenderApi.boundsLookup?.isFinished')
        def history():
            saved=path.read_bytes();self.assertNotEqual(saved,original)
            action('undo');self.assertEqual(path.read_bytes(),original)
            action('redo');self.assertEqual(path.read_bytes(),saved)
            action('undo');self.assertEqual(path.read_bytes(),original)
            return api.from_yaml(saved.decode('utf-8'))
        local_range();action('Shift+ArrowRight');pitched=history()
        for name,pattern in pitched['score']['patterns'].items():
            for b in pattern['beats']:
                old=next(x for x in source['score']['patterns'][name]['beats'] if x['id']==b['id'])
                if name=='C' and b['id'] in ('n0','n1'):
                    self.assertEqual(b['notes'][0]['pitch'],old['notes'][0]['pitch']+1)
                    self.assertEqual(b['notes'][0]['string'],old['notes'][0]['string'])
                else:self.assertEqual(b,old)
        local_range();action('Shift+ArrowDown')
        self.assertEqual(page.evaluate('CUR.score.string'),3)
        shifted=history()
        for b in shifted['score']['patterns']['C']['beats']:
            old=next(x for x in source['score']['patterns']['C']['beats'] if x['id']==b['id'])
            if b['id'] in ('n0','n1'):
                self.assertEqual(b['notes'][0]['string'],3);self.assertEqual(b['notes'][0]['pitch'],old['notes'][0]['pitch'])
            else:self.assertEqual(b,old)
        page.select_option('[data-ui=voice]',index=1);page.locator('#tab-editor').focus();page.keyboard.press('Control+a')
        self.assertEqual(page.locator('.vt-tab-selection').count(),19)
        action('Shift+ArrowRight');self.assertEqual(page.evaluate('CUR.score.voice'),1);lower=history()
        for name,pattern in lower['score']['patterns'].items():
            for b in pattern['beats']:
                old=next(x for x in source['score']['patterns'][name]['beats'] if x['id']==b['id'])
                if b['track']=='guitar' and b['voice']==1:self.assertEqual(b['notes'][0]['pitch'],old['notes'][0]['pitch']+1)
                else:self.assertEqual(b,old)
        page.select_option('[data-ui=voice]',index=0);page.locator('#tab-editor').focus();page.keyboard.press('Control+a')
        with page.expect_response('**/api/score_command') as refused:page.keyboard.press('Shift+ArrowRight')
        response=refused.value;self.assertEqual(response.status,400);self.assertIn('fret range',response.json()['error'])
        self.settled(page,"document.querySelector('.vt-tab-status').textContent.startsWith('Range edit refused:')")
        self.assertEqual(path.read_bytes(),original)
        if expected_failures is not None:
            expected_failures[:]=[r for r in expected_failures if r.url!=response.url or r.status!=400 or r.body()!=response.body()]
        self.assertEqual(errors,[])
        return dict(local_pitch_and_strings=True,whole_track_selection=19,active_voice_retained=True,atomic_fret_limit=True,exact_history=True,page_errors=errors)

    def test_selection_pitch_real_controls(self):
        with self.muted_page(api.to_yaml(self.selection_pitch_song()),width=1920,height=1080,compact=True) as (page,state,folder):
            self.assertFalse(state.error,state.error);history=list(state.history)
            self.run_selection_pitch(page,folder/'song.yaml');self.assertEqual(list(state.history),history)

    def test_select_all_duration_error_preserves_selection(self):
        song=self.selection_pitch_song()
        next(b for b in song['score']['patterns']['C2']['beats'] if b['id']=='n3')['written']['value']=8
        with self.muted_page(api.to_yaml(song),width=1920,height=1080,compact=True) as (page,state,folder):
            self.assertFalse(state.error,state.error);original=(folder/'song.yaml').read_bytes()
            page.evaluate("tab('tab');setEdit(true)");page.wait_for_selector('.vt-tab-score svg')
            self.capture_engraving(page);page.select_option('[data-ui=track]','guitar')
            self.settled(page,'window.tabRendered&&tabRenderApi.boundsLookup?.isFinished')
            self.click_tab_lane(page,0,0,2);page.locator('#tab-editor').focus()
            before=page.evaluate("[...document.querySelectorAll('.vt-tab-selection')].map(e=>({...e.dataset}))")
            page.keyboard.press('Control+a')
            self.assertIn('measure-duration errors',page.inner_text('.vt-tab-status'))
            self.assertEqual(page.evaluate("[...document.querySelectorAll('.vt-tab-selection')].map(e=>({...e.dataset}))"),before)
            self.assertEqual((folder/'song.yaml').read_bytes(),original);self.assertFalse(state.history)

    def run_active_voice_expressions(self,page,path):
        original=path.read_bytes();source=api.from_yaml(original.decode('utf-8'));errors=[]
        page.on('pageerror',lambda error:errors.append(str(error)))
        page.evaluate("tab('tab');setEdit(true)");page.wait_for_selector('.vt-tab-score svg')
        was_open=page.locator('.vt-tab-inspector').evaluate('e=>e.open')
        if not was_open:page.locator('.vt-tab-inspector > summary').click()
        page.select_option('[data-ui=track]','guitar')
        def select_voice(voice):
            # Index avoids the overlapping displayed labels (1/2) and values (0/1).
            self.assertEqual(page.select_option('[data-ui=voice]',index=voice),[str(voice)])
            page.locator('#tab-editor').focus();page.keyboard.press('Control+a')
            self.assertEqual(page.evaluate('CUR.score.voice'),voice)
            self.assertFalse(page.locator('[data-ui=range-expression]').is_hidden())
        def action(name):
            rev=page.evaluate('SCORE.view.revision');page.click('[data-action='+name+']')
            self.settled(page,f'SCORE.view.revision!=={json.dumps(rev)}')
        def history():
            saved=path.read_bytes();self.assertNotEqual(saved,original)
            action('undo');self.assertEqual(path.read_bytes(),original)
            action('redo');self.assertEqual(path.read_bytes(),saved)
            actual=api.from_yaml(saved.decode('utf-8'))
            action('undo');self.assertEqual(path.read_bytes(),original)
            return actual
        for voice in (0,1):
            select_voice(voice)
            with page.expect_response('**/api/score_copy') as copied:page.keyboard.press('Control+c')
            payload=copied.value.json()
            self.assertEqual({b['voice'] for b in payload['clipboard']['beats']},{0,1})
            self.assertEqual(path.read_bytes(),original)
            self.assertEqual(page.input_value('[data-ui=velocity]'),'95' if voice==0 else '63')
            with page.expect_request('**/api/score_command') as request:page.click('[data-action=ghost]')
            self.assertEqual(request.value.post_data_json['voice'],voice)
            self.settled(page,'SCORE.view.score.patterns.C.beats.some(b=>b.notes.some(n=>n.ghost))')
            actual=history()
            for name,pattern in actual['score']['patterns'].items():
                for b in pattern['beats']:
                    old=next(x for x in source['score']['patterns'][name]['beats'] if x['id']==b['id'])
                    if b['track']=='guitar' and b['voice']==voice:
                        self.assertTrue(all(n.get('ghost') for n in b['notes']))
                    else:self.assertEqual(b,old)
            select_voice(voice);page.fill('[data-ui=velocity]','47');action('velocity');actual=history()
            for name,pattern in actual['score']['patterns'].items():
                for b in pattern['beats']:
                    old=next(x for x in source['score']['patterns'][name]['beats'] if x['id']==b['id'])
                    if b['track']=='guitar' and b['voice']==voice:self.assertEqual([n['velocity'] for n in b['notes']],[47]*len(b['notes']))
                    else:self.assertEqual(b,old)
        # An empty active voice does not borrow the other voice's notes or controls.
        page.select_option('[data-ui=track]','bass');select_voice(1)
        for name in ('ghost','velocity','harmonic','grace','repetition','bend'):
            self.assertTrue(page.locator('[data-action='+name+']').is_disabled(),name)
        self.assertEqual(path.read_bytes(),original)
        page.select_option('[data-ui=voice]','0');page.select_option('[data-ui=track]','guitar')
        page.evaluate('setEdit(false)')
        if not was_open:page.locator('.vt-tab-inspector > summary').click()
        self.assertEqual(errors,[])
        return dict(active_voices=[0,1],peer_notes_preserved=True,empty_voice_disabled=True,exact_undo_redo=True,page_errors=errors)

    def test_active_voice_expressions_real_controls(self):
        song=self.score_view_song();song['module']['title']='Active voice expressions'
        with self.muted_page(api.to_yaml(song),width=1920,height=1080,compact=True) as (page,state,folder):
            self.assertFalse(state.error,state.error)
            before=list(state.history)
            self.run_active_voice_expressions(page,folder/'song.yaml')
            self.assertEqual(list(state.history),before)

    def run_score_view_modes(self,page,path,expected_failures=None):
        original=path.read_bytes();errors=[];requests=[]
        page.on('pageerror',lambda error:errors.append(str(error)))
        page.on('request',lambda r:requests.append(r.url) if '/api/score_' in r.url and r.method=='POST' else None)
        page.evaluate("tab('tab');setEdit(true)");page.wait_for_selector('.vt-tab-score svg')
        saved=page.evaluate("localStorage.getItem('vt.scoreView')")
        saved_staff=page.input_value('[data-ui=staff-mode]')
        page.select_option('[data-ui=staff-mode]','select')
        opened=[]
        for selector in ('.vt-tab-view','.vt-tab-inspector'):
            if not page.locator(selector).evaluate('e=>e.open'):
                page.locator(selector+' > summary').click();opened.append(selector)
        self.capture_engraving(page)
        def rendered():
            self.settled(page,'window.tabRendered&&tabRenderedRevision===SCORE.view.revision&&tabRenderApi.boundsLookup?.isFinished&&document.querySelector(".vt-tab-score").dataset.bars')
        def change_view(field,value):
            count=page.evaluate('window.tabRenderCount||0')
            control=page.locator('[data-ui=view-'+field+']')
            if isinstance(value,bool):control.set_checked(value)
            elif field=='scale':control.fill(str(value));control.press('Tab')
            else:control.select_option(value)
            page.wait_for_function('n=>(window.tabRenderCount||0)>n',arg=count);rendered()
        def action(name):
            rev=page.evaluate('SCORE.view.revision');page.click('[data-action='+name+']')
            self.settled(page,f'SCORE.view.revision!=={json.dumps(rev)}');rendered()
        change_view('multitrack',True)
        self.assertEqual(page.get_attribute('.vt-tab-score','data-tracks'),'guitar,guitar2,bass,drums')
        self.assertEqual(page.evaluate('tabRendered.tracks.length'),4)
        for field,value in (('layout','horizontal'),('scale',80),('notation','staff'),('chord-names',False),('chord-diagrams',False)):
            change_view(field,value)
        self.assertTrue(page.evaluate('tabRendered.tracks.every(t=>t.staves[0].showStandardNotation&&!t.staves[0].showTablature)'))
        self.assertTrue(page.evaluate('[...tabRendered.tracks[0].staves[0].chords.values()].every(c=>!c.showName&&!c.showDiagram)'))
        self.assertEqual(path.read_bytes(),original);self.assertEqual(requests,[])
        # Preferences survive a real reload without entering the shared edit history.
        page.reload();page.wait_for_function('S&&!S.rendering');page.evaluate("tab('tab');setEdit(true)")
        page.wait_for_selector('.vt-tab-score svg')
        for selector in ('.vt-tab-view','.vt-tab-inspector'):
            if not page.locator(selector).evaluate('e=>e.open'):page.locator(selector+' > summary').click()
        self.assertEqual(page.get_attribute('.vt-tab-score','data-layout'),'horizontal')
        self.assertEqual(page.get_attribute('.vt-tab-score','data-scale'),'80')
        self.assertEqual(page.get_attribute('.vt-tab-score','data-notation'),'staff')
        self.assertEqual(path.read_bytes(),original);self.assertEqual(requests,[])
        self.capture_engraving(page);change_view('scale',90)
        # Actual notehead clicks select the clicked part, including bass and drums.
        for index,track in enumerate(('guitar2','bass','drums'),1):
            self.click_score_note(page,0,index)
            self.settled(page,'CUR.score?.track==='+json.dumps(track))
            self.assertEqual(page.get_attribute('.vt-tab-edit-caret','data-track'),track)
            self.assertIn(page.evaluate('CUR.ch'),page.evaluate('SCORE.view.score.tracks['+json.dumps(track)+'].channels'))
            action('ghost');edited=path.read_bytes();self.assertNotEqual(edited,original)
            actual=api.from_yaml(edited.decode('utf-8'))
            ghosts=[b['track'] for p in actual['score']['patterns'].values() for b in p['beats'] for n in b['notes'] if n.get('ghost')]
            self.assertEqual(ghosts,[track])
            action('undo');self.assertEqual(path.read_bytes(),original)
            action('redo');self.assertEqual(path.read_bytes(),edited)
            action('undo');self.assertEqual(path.read_bytes(),original)
            marker=page.evaluate("() => {SCORE.editor.setPlayhead({o:0,row:0});const e=document.querySelector('.vt-tab-playhead');return {track:e.dataset.track,hidden:e.hidden}}")
            self.assertEqual(marker,dict(track=track,hidden=False))
        change_view('layout','page');change_view('notation','both')
        change_view('scale',100)
        start,end=(self.tab_lane_point(page,0,i,3,track_index=1) for i in (0,1))
        page.mouse.move(start['x'],start['y']);page.mouse.down();page.mouse.move(end['x'],end['y'],steps=5);page.mouse.up()
        self.assertEqual(page.evaluate("[...document.querySelectorAll('.vt-tab-selection')].map(e=>e.dataset.track)"),['guitar2','guitar2'])
        action('ghost');edited=path.read_bytes()
        ghosts=[b['track'] for p in api.from_yaml(edited.decode('utf-8'))['score']['patterns'].values() for b in p['beats'] for n in b['notes'] if n.get('ghost')]
        self.assertEqual(ghosts,['guitar2']*4)
        action('undo');self.assertEqual(path.read_bytes(),original)
        action('redo');self.assertEqual(path.read_bytes(),edited)
        action('undo');self.assertEqual(path.read_bytes(),original)
        # A one-bar range uses the same atomic expression path as a phrase spanning bars.
        start,end=(self.tab_lane_point(page,0,i,3,track_index=1) for i in (0,1))
        page.mouse.move(start['x'],start['y']);page.mouse.down();page.mouse.move(end['x'],end['y'],steps=5);page.mouse.up()
        page.fill('[data-ui=velocity]','47');action('velocity');edited=path.read_bytes()
        actual=api.from_yaml(edited.decode('utf-8'))
        selected=[n['velocity'] for b in actual['score']['patterns']['C']['beats'] if b['track']=='guitar2' for n in b['notes']]
        self.assertEqual(selected,[47]*4)
        action('undo');self.assertEqual(path.read_bytes(),original)
        action('redo');self.assertEqual(path.read_bytes(),edited)
        action('undo');self.assertEqual(path.read_bytes(),original)
        start,end=(self.tab_lane_point(page,0,i,3,track_index=1) for i in (0,1))
        page.mouse.move(start['x'],start['y']);page.mouse.down();page.mouse.move(end['x'],end['y'],steps=5);page.mouse.up()
        # At 96 BPM the palm-mute cap falls between IT ticks; the whole range must refuse.
        with page.expect_response(lambda r:r.url.endswith('/api/score_command') and r.request.method=='POST') as refused:
            page.click('[data-action=palm-mute]')
        self.settled(page,"document.querySelector('.vt-tab-status').textContent.startsWith('Range edit refused:')")
        refusal=refused.value
        self.assertEqual(refusal.status,400)
        self.assertIn('not representable on the IT tick grid',refusal.json()['error'])
        self.assertEqual(path.read_bytes(),original)
        if expected_failures is not None and refusal in expected_failures:expected_failures.remove(refusal)
        change_view('notation','tab')
        self.assertTrue(page.evaluate('tabRendered.tracks.slice(0,3).every(t=>!t.staves[0].showStandardNotation&&t.staves[0].showTablature)'))
        self.assertTrue(page.evaluate('tabRendered.tracks[3].staves[0].showStandardNotation&&!tabRendered.tracks[3].staves[0].showTablature'))
        change_view('scale',50);page.click('[data-ui=view-reset-scale]');rendered()
        self.assertEqual(page.input_value('[data-ui=view-scale]'),'100')
        change_view('notation','both');change_view('chord-names',True);change_view('chord-diagrams',True);change_view('multitrack',False)
        page.select_option('[data-ui=track]','guitar');rendered();page.evaluate('SCORE.editor.setPlayhead(null);setEdit(false)')
        page.select_option('[data-ui=staff-mode]',saved_staff)
        for selector in reversed(opened):
            if page.locator(selector).evaluate('e=>e.open'):page.locator(selector+' > summary').click()
        page.evaluate("value=>{if(value===null)localStorage.removeItem('vt.scoreView');else localStorage.setItem('vt.scoreView',value)}",saved)
        self.assertEqual(path.read_bytes(),original);self.assertEqual(errors,[])
        return dict(tracks=4,layouts=['page','horizontal'],notation=['both','staff','tab'],preferences_no_writes=True,
                    reload=True,part_hits=True,part_range=True,exact_undo_redo=True,atomic_refusal=True,playhead=True,page_errors=errors)

    def test_score_view_modes_real_controls(self):
        with self.muted_page(api.to_yaml(self.score_view_song()),width=1920,height=1080,compact=True) as (page,state,folder):
            self.assertFalse(state.error,state.error)
            before=(list(state.history),list(state.future))
            self.run_score_view_modes(page,folder/'song.yaml')
            self.assertEqual(list(state.history),before[0])

    def run_drum_ornaments(self,page,path):
        from tests.test_gpimport import TestPercussionOrnamentInterchange as Fixture
        from vulturetracker import gpimport,tgimport
        original=path.read_bytes();errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
        page.evaluate("tab('tab');setEdit(true)");opened=[]
        for selector in ('.vt-tab-inspector','.vt-tab-grid-details'):
            if not page.locator(selector).evaluate('e=>e.open'):
                page.locator(selector+' > summary').click();opened.append(selector)
        self.capture_engraving(page)
        def changed(action):
            rev=page.evaluate('SCORE.view.revision');page.click('[data-action='+action+']')
            self.settled(page,f'SCORE.view.revision!=={json.dumps(rev)}')
            self.settled(page,'window.tabRendered&&tabRenderedRevision===SCORE.view.revision&&tabRenderApi.boundsLookup?.isFinished')
        def history():
            saved=path.read_bytes();self.assertNotEqual(saved,original)
            changed('undo');self.assertEqual(path.read_bytes(),original)
            changed('redo');self.assertEqual(path.read_bytes(),saved)
            return api.from_yaml(saved.decode('utf-8'))
        with tempfile.TemporaryDirectory(prefix='vt-drum-ornaments-') as temporary:
            folder=Path(temporary)
            for rate in (8,32):
                page.click('.vt-tab-grid [data-note=roll]')
                self.assertFalse(page.locator('[data-action=repetition]').is_disabled())
                self.assertTrue(page.locator('[data-ui=repetition-type] option[value=trill]').evaluate('e=>e.disabled'),
                    page.evaluate('({track:document.querySelector("[data-ui=track]").value,score:SCORE.view.score.tracks})'))
                self.assertEqual(page.locator('[data-ui=repetition-type] option[value=tremolo_picking]').inner_text(),'Drum roll')
                page.select_option('[data-ui=repetition-type]','tremolo_picking');page.select_option('[data-ui=repetition-value]',str(rate))
                changed('repetition');song=history()
                self.assertEqual(song['score']['patterns']['a']['beats'][0]['notes'][0]['tremolo_picking'],dict(value=rate))
                self.assertTrue(page.locator('.vt-tab-score svg').count())
                changed('undo');self.assertEqual(path.read_bytes(),original)
            for value,on,dead,key in ((32,False,False,42),(16,True,True,38),(64,False,False,42)):
                page.click('.vt-tab-grid [data-note=flam]')
                self.assertEqual(page.inner_text('[data-ui=grace-key-label]'),'Grace drum key')
                self.assertFalse(page.locator('[data-action=grace]').is_disabled())
                page.select_option('[data-ui=grace-kind]','grace');page.fill('[data-ui=grace-fret]',str(key))
                page.select_option('[data-ui=grace-value]',str(value));page.fill('[data-ui=grace-velocity]','47')
                page.select_option('[data-ui=grace-timing]','on' if on else 'before');page.locator('[data-ui=grace-dead]').set_checked(dead)
                changed('grace');song=history()
                self.assertIn('Grace drum key '+str(key),page.locator('.vt-tab-grid [data-note=flam]').get_attribute('title'))
                actual=page.evaluate('tabRendered.tracks[0].staves[0].bars.flatMap(b=>b.voices.flatMap(v=>v.beats.filter(b=>b.graceType!==alphaTab.model.GraceType.None).flatMap(b=>b.notes.map(n=>n.percussionArticulation))))')
                self.assertEqual(actual,[key])
                page.click('[data-t=export]');page.uncheck('#export-stems');page.fill('#export-dest',str(folder))
                for fmt in ('tg','gp5'):
                    name=f'grace{value}-{int(on)}-{int(dead)}-{fmt}'
                    page.select_option('#export-format',fmt);page.fill('#export-name',name);page.click('#export-go')
                    page.wait_for_function('suffix=>S.export?.status==="done"&&S.export.files?.some(p=>p.endsWith(suffix))',arg=name+'.'+fmt,timeout=30000)
                    data=(folder/(name+'.'+fmt)).read_bytes()
                    restored=tgimport.read_tg(data)[0] if fmt=='tg' else gpimport._native_gp_song(gpimport._read_native_gp(data),song['module']['title'])
                    self.assertEqual(Fixture.performance(restored),Fixture.performance(song))
                page.click('[data-t=tab]');changed('undo');self.assertEqual(path.read_bytes(),original)
        page.click('[data-action=print]')
        frame=page.locator('#score-print-frame').element_handle().content_frame();self.print_ready(frame)
        self.capture_engraving(frame);frame.locator('form button[type=submit]').click();self.print_ready(frame)
        frame.wait_for_function('window.tabRendered&&tabRenderApi.boundsLookup?.isFinished')
        self.assertTrue(frame.evaluate('tabRendered.tracks[0].staves[0].isPercussion'))
        self.assertEqual(frame.evaluate('tabRendered.tracks[0].staves[0].bars.flatMap(b=>b.voices.flatMap(v=>v.beats.filter(b=>b.graceType!==alphaTab.model.GraceType.None).flatMap(b=>b.notes.map(n=>n.percussionArticulation))))'),[42])
        self.assertGreater(frame.locator('.vt-print-page svg').count(),0)
        page.get_by_role('button',name='Close preview',exact=True).click()
        page.evaluate('setEdit(false)')
        for selector in reversed(opened):page.locator(selector+' > summary').click()
        self.assertEqual(errors,[])
        return dict(rolls=[8,16,32],grace_values=[16,32,64],drum_articulations=True,print=True,tg_gp5=True,exact_undo_redo=True,page_errors=errors)

    def test_drum_ornaments_real_controls(self):
        from tests.test_gpimport import TestPercussionOrnamentInterchange as Fixture
        song=Fixture.fixture();song['samples'][2]['file']='a.wav'
        with self.muted_page(api.to_yaml(song),width=1920,height=1080,compact=True) as (page,state,folder):
            self.assertFalse(state.error,state.error)
            self.run_drum_ornaments(page,folder/'song.yaml')

    def run_gp_encoding(self,page,path):
        from tests.test_score_collection_page import TestScoreCollectionPage
        from tests.test_real_interchange import TestRealInterchangePage
        from tests.test_gpimport import TestGuitarProEncoding
        from vulturetracker import gpimport
        original=path.read_bytes();song=api.from_yaml(original.decode('utf-8'))
        errors=[];page.on('pageerror',lambda error:errors.append(str(error)))
        saved=page.evaluate("localStorage.getItem('vt-delivery-settings')")
        def verify(target,encoding=None):
            data=Path(target).read_bytes()
            actual=(gpimport._native_gp_song(gpimport._read_native_gp(data,encoding),'GP text encodings') if encoding else api.from_yaml(data.decode('utf-8')))
            self.assertEqual(actual['score'],song['score'])
        with tempfile.TemporaryDirectory(prefix='vt-gp-encoding-') as temporary:
            folder=Path(temporary)
            try:
                TestRealInterchangePage().run_imported_edits(page,path)
                page.click('[data-t=export]');page.select_option('#export-format','gp5')
                self.assertTrue(page.is_visible('#export-gp-options'))
                page.uncheck('#export-stems');page.fill('#export-dest',str(folder))
                for encoding in ('utf-8','shift_jis'):
                    page.fill('#export-gp-encoding',encoding);page.fill('#export-name',encoding);page.click('#export-go')
                    page.wait_for_function('name=>S.export?.status==="done"&&S.export.files?.some(p=>p.endsWith(name+".gp5"))',arg=encoding,timeout=30000)
                    verify(folder/(encoding+'.gp5'),encoding)
                source=folder/'utf-8.gp5';data=source.read_bytes()
                page.evaluate('renderStart()');page.check('#impnative')
                page.locator('#import-gp-options > summary').click();page.fill('#import-gp-encoding','utf-8')
                page.fill('#imppath',str(source))
                with page.expect_response('**/api/import') as response:page.press('#imppath','Enter')
                result=response.value.json();self.assertNotIn('error',result,result)
                target=Path(result['path']);verify(target)
                page.wait_for_function('p=>S?.song?.path===p&&S.song.facts.native_score',arg=str(target))
                page.wait_for_selector('.vt-tab-score .at-surface svg')
                TestRealInterchangePage().run_imported_edits(page,target)
                collection=TestScoreCollectionPage();page.evaluate('collectionOpen()')
                page.locator('#collection-gp-options > summary').click();page.fill('#collection-gp-encoding','utf-8')
                page.get_by_role('button',name='Remember delivery settings',exact=True).click()
                page.reload();page.wait_for_function('S?.song?.facts');page.evaluate('collectionOpen()')
                self.assertEqual(page.evaluate('gpEncoding("collection")'),'utf-8')
                collection.scan(page,folder);page.fill('#collection-filter','utf-8.gp5')
                page.locator('#collection-files input[type=checkbox]').check()
                result=collection.convert(page,folder/'batch','gp5')['results'][0]
                self.assertEqual(result['status'],'done',result);verify(next(p for p in result['files'] if p.endswith('.gp5')),'utf-8')
                with page.expect_response('**/api/import') as response:page.locator('#collection-files button').click()
                result=response.value.json();self.assertNotIn('error',result,result);verify(result['path'])
                page.wait_for_function('p=>S?.song?.path===p',arg=result['path'])
                self.assertEqual(source.read_bytes(),data)
            finally:
                page.evaluate("v=>{if(v===null)localStorage.removeItem('vt-delivery-settings');else localStorage.setItem('vt-delivery-settings',v)}",saved)
                page.evaluate('async p=>{await openSong(p)}',str(path))
        page.click('[data-t=tab]');page.evaluate('setEdit(false)');self.settled(page,'!SCORE.busy')
        self.assertEqual(path.read_bytes(),original);self.assertEqual(errors,[])
        return dict(encodings=['utf-8','shift_jis'],single_batch_collection_open=True,remembered_settings=True,source_unchanged=True,exact_undo_redo=True,page_errors=errors)

    def test_gp_encoding_real_controls(self):
        from tests.test_gpimport import TestGuitarProEncoding
        song=TestGuitarProEncoding.fixture('音楽')
        song['module']['title']=song['score']['metadata']['title']='GP text encodings'
        song['samples']={1:dict(file='a.wav',name='Guitar')}
        with self.muted_page(api.to_yaml(song),width=1920,height=1080,compact=True) as (page,state,folder):
            self.assertFalse(state.error,state.error)
            self.run_gp_encoding(page,folder/'song.yaml')

    def run_midi_export_options(self,page,path):
        from tests.test_score_collection_page import TestScoreCollectionPage
        from tests.test_real_interchange import TestRealInterchangePage
        from vulturetracker import export
        original=path.read_bytes();song=api.from_yaml(original.decode())
        snap=export.snapshot(song,path.parent,tail=0)
        errors=[];page.on('pageerror',lambda error:errors.append(str(error)))
        TestRealInterchangePage().run_imported_edits(page,path)
        settings=dict(transpose=12,strip=True)
        expected=export.native_to_midi(snap,settings)[0]
        def set_options(prefix,value):
            page.fill('#'+prefix+'-midi-export-transpose',str(value['transpose']))
            page.locator('#'+prefix+'-midi-export-strip').set_checked(value['strip'])
        with tempfile.TemporaryDirectory(prefix='vt-midi-export-options-') as temporary:
            folder=Path(temporary)
            page.click('[data-t=export]');page.select_option('#export-format','mid')
            self.assertTrue(page.is_visible('#export-midi-export'))
            page.uncheck('#export-stems');page.select_option('#export-tail-mode','cut');page.fill('#export-dest',str(folder))
            for name,value in (('defaults',dict(transpose=0,strip=False)),('transposed',settings)):
                set_options('export',value);page.fill('#export-name',name);page.click('#export-go')
                page.wait_for_function('name=>S.export?.status==="done"&&S.export.files?.some(p=>p.endsWith(name+".mid"))',arg=name,timeout=30000)
                self.assertEqual((folder/(name+'.mid')).read_bytes(),export.native_to_midi(snap,value)[0])
            self.assertTrue(any('grace' in w for w in page.evaluate('S.export.warnings')))
            collection=TestScoreCollectionPage();page.evaluate('collectionOpen()')
            collection.scan(page,path.parent);page.fill('#collection-filter',path.name)
            page.locator('#collection-files input[type=checkbox]').check()
            page.select_option('#collection-format','mid');set_options('collection',settings)
            previous=page.evaluate("localStorage.getItem('vt-delivery-settings')")
            try:
                page.get_by_role('button',name='Remember delivery settings',exact=True).click()
                page.reload();page.wait_for_function('S?.song?.facts')
                page.evaluate('collectionOpen()');self.assertEqual(page.evaluate('midiExportSettings("collection")'),settings)
                collection.scan(page,path.parent);page.fill('#collection-filter',path.name)
                page.locator('#collection-files input[type=checkbox]').check()
                result=collection.convert(page,folder/'batch','mid')['results'][0]
                self.assertEqual(result['status'],'done',result)
                self.assertEqual(Path(result['files'][0]).read_bytes(),expected)
                page.click('#collection-close')
            finally:page.evaluate("v=>{if(v===null)localStorage.removeItem('vt-delivery-settings');else localStorage.setItem('vt-delivery-settings',v)}",previous)
        page.evaluate("tab('tab');setEdit(false)")
        self.assertEqual(path.read_bytes(),original);self.assertEqual(errors,[])
        return dict(defaults=True,transpose=12,strip=True,single_and_batch=True,persisted_options=True,source_unchanged=True,exact_undo_redo=True,page_errors=errors)

    def test_midi_export_options_real_controls(self):
        from tests.test_workflow import midi_export_options_song
        with self.muted_page(api.to_yaml(midi_export_options_song()),compact=True) as (page,state,folder):
            self.assertFalse(state.error,state.error)
            self.run_midi_export_options(page,folder/'song.yaml')

    def run_gp5_harmonics(self,page,path):
        from vulturetracker import gpimport
        from tests.test_gpexport_legacy import plan
        original=path.read_bytes();source=api.from_yaml(original.decode())
        errors=[];page.on('pageerror',lambda error:errors.append(str(error)))
        target=source['score']['patterns']['m1']['beats'][-1]['notes'][0]['id']
        page.evaluate("tab('tab');setEdit(true)")
        opened=[]
        for selector in ('.vt-tab-inspector','.vt-tab-grid-details'):
            panel=page.locator(selector)
            if not panel.evaluate('e=>e.open'):
                panel.locator('summary').first.click();opened.append(selector)
        page.wait_for_selector(f'.vt-tab-grid [data-note="{target}"]')
        with tempfile.TemporaryDirectory(prefix='vt-gp5-harmonics-') as destination:
            for kind,data in [('tapped',i) for i in range(1,6)]+[('pinch',0),('semi',0),('artificial',2),('artificial',3)]:
                page.click(f'.vt-tab-grid [data-note="{target}"]')
                page.select_option('[data-ui=harmonic-type]',kind)
                page.select_option('[data-ui=harmonic-data]',str(data))
                revision=page.evaluate('SCORE.view.revision')
                page.click('[data-action=harmonic]')
                self.settled(page,f'SCORE.view.revision!=={json.dumps(revision)}')
                changed=path.read_bytes();song=api.from_yaml(changed.decode())
                self.assertEqual(song['score']['patterns']['m1']['beats'][-1]['notes'][0]['harmonic'],dict(type=kind,data=data))
                self.assertNotEqual(changed,original)
                revision=page.evaluate('SCORE.view.revision');page.click('[data-action=undo]')
                self.settled(page,f'SCORE.view.revision!=={json.dumps(revision)}');self.assertEqual(path.read_bytes(),original)
                revision=page.evaluate('SCORE.view.revision');page.click('[data-action=redo]')
                self.settled(page,f'SCORE.view.revision!=={json.dumps(revision)}');self.assertEqual(path.read_bytes(),changed)
                page.click('[data-t=export]');page.uncheck('#export-stems')
                for version in ((4,) if kind=='artificial' else (4,5) if kind in ('pinch','semi') else (5,)):
                    fmt=f'gp{version}';page.select_option('#export-format',fmt)
                    name=f'{kind}-{data}-{fmt}';page.fill('#export-dest',destination);page.fill('#export-name',name);page.click('#export-go')
                    page.wait_for_function('suffix=>S.export?.status==="done"&&S.export.files?.some(p=>p.endsWith(suffix))',arg=name+'.'+fmt,timeout=30000)
                    restored=gpimport._native_gp_song(gpimport._read_native_gp((Path(destination)/(name+'.'+fmt)).read_bytes()),song['module']['title'])
                    self.assertEqual(restored['score'],song['score']);self.assertEqual(plan(restored),plan(song))
                page.click('[data-t=tab]');self.settled(page,'SCORE.view.score.patterns.m1')
                revision=page.evaluate('SCORE.view.revision');page.click('[data-action=undo]')
                self.settled(page,f'SCORE.view.revision!=={json.dumps(revision)}');self.assertEqual(path.read_bytes(),original)
        page.evaluate('setEdit(false)')
        for selector in reversed(opened):page.locator(selector+' > summary').click()
        self.assertEqual(errors,[])
        return dict(tapped_intervals=6,pinch=True,semi=True,gp4_artificial=[2,3],gp4_gp5_roundtrip=True,exact_undo_redo=True,page_errors=errors)

    def test_gp5_harmonic_exports_real_controls(self):
        from tests.test_gpimport import TestGp5ExtendedHarmonicExport
        song=TestGp5ExtendedHarmonicExport.fixture()
        song['samples']={1:dict(file='a.wav',base_note='A-4')}
        with self.muted_page(api.to_yaml(song),compact=True) as (page,state,folder):
            self.assertFalse(state.error,state.error)
            self.run_gp5_harmonics(page,folder/'song.yaml')

    def run_gp_rhythm_clefs(self,page,path):
        from tests.test_real_interchange import TestRealInterchangePage
        original=path.read_bytes()
        errors=[];page.on('pageerror',lambda error:errors.append(str(error)))
        page.click('[data-t=tab]');page.wait_for_selector('.vt-tab-score .at-surface svg');self.capture_engraving(page)
        page.select_option('[data-ui=track]','t1')
        self.settled(page,'window.tabRendered&&tabRenderedRevision===SCORE.view.revision&&tabRenderApi.boundsLookup?.isFinished')
        def verify(surface):
            self.assertEqual(surface.evaluate('tabRendered.tracks[0].staves[0].bars.map(b=>b.clef)'),
                surface.evaluate('[alphaTab.model.Clef.F4,alphaTab.model.Clef.C3,alphaTab.model.Clef.C4,alphaTab.model.Clef.G2]'))
            self.assertEqual(surface.evaluate('tabRendered.tracks[0].staves[0].bars.map(b=>b.voices[0].beats[0].dots)'),[2]*4)
        verify(page)
        TestRealInterchangePage().run_imported_edits(page,path)
        verify(page)
        page.click('[data-action=print]')
        frame=page.locator('#score-print-frame').element_handle().content_frame();self.print_ready(frame)
        self.capture_engraving(frame)
        frame.locator('form button[type=submit]').click();self.print_ready(frame)
        frame.wait_for_function('window.tabRendered&&tabRenderApi.boundsLookup?.isFinished')
        verify(frame)
        self.assertGreater(frame.locator('.vt-print-page svg').count(),0)
        page.get_by_role('button',name='Close preview',exact=True).click()
        page.evaluate('setEdit(false)')
        self.assertEqual(path.read_bytes(),original);self.assertEqual(errors,[])
        return dict(double_dots=True,clefs=['bass','alto','tenor','treble'],editor_and_print=True,exact_undo_redo=True,page_errors=errors)

    def test_gp_rhythm_clefs_real_controls(self):
        from tests.test_gpx import rhythm_clef_fixture,gp6,gp7
        for version,pack in ((6,gp6),(7,gp7)):
            with self.subTest(version=version),tempfile.TemporaryDirectory() as temporary:
                folder=Path(temporary);src=folder/('source.gpx' if version==6 else 'source.gp')
                src.write_bytes(pack(rhythm_clef_fixture(version,True)))
                target,_=gui.import_song(src,folder/'song.yaml',folder/'samples',native_tab=True)
                song=api.from_yaml(target.read_text(encoding='utf-8'))
                for sample in song['samples'].values():sample['file']=str((folder/sample['file']).resolve())
                with self.muted_page(api.to_yaml(song),width=1920,height=1080) as (page,state,controls):
                    self.assertFalse(state.error,state.error)
                    self.run_gp_rhythm_clefs(page,controls/'song.yaml')

    def run_midi_import_options(self,page,path):
        from tests.test_real_interchange import midi_workflow_bytes,TestRealInterchangePage
        from tests.test_score_collection_page import TestScoreCollectionPage
        from vulturetracker import midiimport
        original=path.read_bytes()
        settings=dict(transpose=12,quantize=True,max_duration=32,max_division=3)
        data=midi_workflow_bytes()
        expected,_=midiimport.read_midi_score(data,**settings)
        errors=[];page.on('pageerror',lambda error:errors.append(str(error)))
        saved=page.evaluate("localStorage.getItem('vt-delivery-settings')")
        def set_options(prefix):
            page.locator('#'+prefix+'-midi-options > summary').click()
            page.fill('#'+prefix+'-midi-transpose','12')
            page.check('#'+prefix+'-midi-quantize')
            page.select_option('#'+prefix+'-midi-max_duration','32')
            page.select_option('#'+prefix+'-midi-max_division','3')
        def imported(target):
            self.assertEqual(api.from_yaml(target.read_text(encoding='utf-8'))['score'],expected['score'])
        with tempfile.TemporaryDirectory(prefix='vt-midi-options-') as temporary:
            folder=Path(temporary);source=folder/'study.mid';source.write_bytes(data)
            try:
                page.evaluate('renderStart()');page.wait_for_selector('#imppath')
                page.check('#impnative');set_options('import');page.fill('#imppath',str(source))
                with page.expect_response('**/api/import') as response:page.press('#imppath','Enter')
                result=response.value.json();self.assertNotIn('error',result,result)
                target=Path(result['path'])
                page.wait_for_function('p=>S?.song?.path===p&&S.song.facts.native_score',arg=str(target))
                page.wait_for_selector('.vt-tab-score .at-surface svg');imported(target)
                TestRealInterchangePage().run_imported_edits(page,target)
                collection=TestScoreCollectionPage();page.evaluate('collectionOpen()')
                set_options('collection')
                page.get_by_role('button',name='Remember delivery settings',exact=True).click()
                page.reload();page.wait_for_function('S?.song?.facts');page.evaluate('collectionOpen()')
                self.assertEqual(page.evaluate('midiImportSettings("collection")'),settings)
                collection.scan(page,folder);page.fill('#collection-filter','study.mid')
                page.locator('#collection-files input[type=checkbox]').check()
                result=collection.convert(page,folder/'batch','yaml')['results'][0]
                self.assertEqual(result['status'],'done',result);imported(Path(result['files'][0]))
                with page.expect_response('**/api/import') as response:page.locator('#collection-files button').click()
                result=response.value.json();self.assertNotIn('error',result,result)
                self.assertNotEqual(result['path'],str(target));imported(Path(result['path']))
                page.wait_for_function('p=>S?.song?.path===p',arg=result['path'])
                self.assertEqual(source.read_bytes(),data)
            finally:
                page.evaluate("v=>{if(v===null)localStorage.removeItem('vt-delivery-settings');else localStorage.setItem('vt-delivery-settings',v)}",saved)
                page.evaluate('async p=>{await openSong(p)}',str(path))
        page.click('[data-t=tab]');page.evaluate('setEdit(false)')
        self.settled(page,'!SCORE.busy')
        self.assertEqual(path.read_bytes(),original);self.assertEqual(errors,[])
        return dict(single_batch_collection_open=True,persisted_settings=settings,imported_notes=28,source_unchanged=True,exact_note_undo_redo=True,page_errors=errors)

    def test_midi_import_options_real_controls(self):
        from tests.test_tablature_sync import complete_song_seed
        song=complete_song_seed()
        for sample in song['samples'].values():sample['file']='a.wav'
        with self.muted_page(api.to_yaml(song),width=1920,height=1080) as (page,state,folder):
            self.assertFalse(state.error,state.error)
            self.run_midi_import_options(page,folder/'song.yaml')

    def run_library_mixer(self,page,path):
        """Imported part mix, note editing and actual export share the original document."""
        from tests.test_real_interchange import TestRealInterchangePage
        from vulturetracker import tgimport
        import mido
        original=path.read_bytes()
        source=api.from_yaml(original.decode('utf-8'))
        tracks=source['score']['tracks']
        tid=next(iter(tracks));track=tracks[tid]
        wanted=tgimport.track_midi_mix(source,track)
        channel=track['channels'][0]
        volume=source['module']['channels'][channel]['volume']
        errors=[];page.on('pageerror',lambda error:errors.append(str(error)))
        page.click('[data-t=tab]');page.select_option('[data-ui=track]',tid)
        self.open_setup(page)
        feedback=page.inner_text('[data-ui=midi-source-pan]')
        self.assertIn(f"pan {wanted['pan']}, volume {wanted['volume']}",feedback)
        page.click('[data-action=close-setup]')
        TestRealInterchangePage().run_imported_edits(page,path)
        page.click('[data-t=overview]')
        page.click(f'#mv{channel}');page.fill('.typein',str(volume));page.press('.typein','Enter')
        page.wait_for_function('([ch,v])=>S.mix?.volume?.[ch]===v',arg=[str(channel),volume])
        page.click('#writemix');page.wait_for_selector('#diffmodal');page.click('#diffmodal .btn.big')
        page.wait_for_function('ch=>!S.source_volume_channels?.includes(ch)',arg=channel)
        changed=path.read_bytes()
        self.assertNotEqual(changed,original)
        self.assertNotIn('source_volume',api.from_yaml(changed.decode())['score']['tracks'][tid]['midi'])
        page.click('[data-t=tab]')
        for action,expected in [('undo',original),('redo',changed),('undo',original)]:
            self.settled(page, 'SCORE.view.revision.startsWith(S.version.hash)')
            revision=page.evaluate('SCORE.view.revision')
            page.click(f'[data-action={action}]')
            self.settled(page,'SCORE.view.revision!=='+json.dumps(revision))
            self.assertEqual(path.read_bytes(),expected)
        with tempfile.TemporaryDirectory(prefix='vt-library-mix-') as temporary:
            destination=Path(temporary)
            page.click('[data-t=export]');page.uncheck('#export-stems');page.fill('#export-dest',str(destination))
            for fmt in ('tg','mid'):
                page.select_option('#export-format',fmt);page.fill('#export-name','imported-'+fmt);page.click('#export-go')
                page.wait_for_function('name=>S.export?.status==="done"&&S.export.files?.some(p=>p.includes(name))',arg='imported-'+fmt,timeout=30000)
                output=destination/('imported-'+fmt+'.'+fmt)
                if fmt=='tg':
                    again,_=tgimport.read_tg(output.read_bytes())
                    self.assertEqual([tgimport.track_midi_mix(again,t) for t in again['score']['tracks'].values()],
                                     [tgimport.track_midi_mix(source,t) for t in tracks.values()])
                else:
                    messages=[m for t in mido.MidiFile(output).tracks for m in t]
                    for cc,key in ((7,'volume'),(10,'pan')):
                        self.assertTrue(any(m.type=='control_change' and m.control==cc and m.value==wanted[key] for m in messages))
        page.click('[data-t=tab]');page.evaluate('setEdit(false)')
        self.settled(page,'!SCORE.busy')
        self.assertEqual(path.read_bytes(),original)
        self.assertEqual(errors,[])
        return dict(source_mix=wanted,note_and_mix_undo_redo=True,exports=['tg','mid'],source_unchanged=True,page_errors=errors)

    def test_library_import_mix_real_controls(self):
        from tests.test_band_imports import ptb_fixture,tef2_fixture,tef3_fixture
        for name,fixture,values in [('ptb',ptb_fixture,dict(volume=63,pan=15)),
                                    ('tef2',tef2_fixture,dict(volume=6,pan=3)),
                                    ('tef3',tef3_fixture,dict(volume=6,pan=3))]:
            with self.subTest(format=name),tempfile.TemporaryDirectory() as temporary:
                folder=Path(temporary)
                source=folder/('source.ptb' if name=='ptb' else 'source.tef')
                source.write_bytes(fixture(**values))
                target,_=gui.import_song(source,folder/'song.yaml',folder/'samples')
                song=api.from_yaml(target.read_text(encoding='utf-8'))
                for sample in song['samples'].values():sample['file']=str((folder/sample['file']).resolve())
                with self.muted_page(api.to_yaml(song),width=1920,height=1080) as (page,state,controls):
                    self.assertFalse(state.error,state.error)
                    self.run_library_mixer(page,controls/'song.yaml')

    def run_mixer_interchange(self, page, path):
        from vulturetracker import tgimport, gpimport
        import mido
        original = path.read_bytes()
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.evaluate("tab('tab');setEdit(true)")
        page.wait_for_selector('[data-ui=track]')
        page.select_option('[data-ui=track]', 'guitar')
        self.open_setup(page)
        self.assertIn('pan 15, volume 63', page.inner_text('[data-ui=midi-source-pan]'))
        page.fill('[data-ui=display-name]', 'Imported mix retained')
        page.locator('.vt-tab-setup button[type=submit]').first.click()
        self.settled(page, "SCORE.view.score.tracks.guitar.name==='Imported mix retained'")
        self.assertEqual(api.from_yaml(path.read_text())['score']['tracks']['guitar']['midi']['source_volume']['value'],63)
        page.click('[data-action=undo]')
        self.settled(page, "SCORE.view.score.tracks.guitar.name!=='Imported mix retained'")
        self.assertEqual(path.read_bytes(),original)
        page.evaluate("tab('overview')")
        page.wait_for_function('S.source_volume_channels?.includes(0)')
        page.click('#mv0'); page.fill('.typein','32'); page.press('.typein','Enter')
        page.wait_for_function("S.mix?.volume?.['0']===32")
        self.assertEqual(path.read_bytes(),original)
        page.click('#writemix'); page.wait_for_selector('#diffmodal')
        self.assertIn('source_volume',page.inner_text('#difflines'))
        page.click('#diffmodal .btn.big')
        page.wait_for_function('!S.source_volume_channels?.includes(0)')
        changed = path.read_bytes()
        changed_song = api.from_yaml(changed.decode())
        self.assertNotIn('source_volume',changed_song['score']['tracks']['guitar']['midi'])
        self.assertIn('source_pan',changed_song['score']['tracks']['guitar']['midi'])
        page.evaluate("tab('tab')")
        self.settled(page,'!SCORE.view.score.tracks.guitar.midi.source_volume')
        page.click('[data-action=undo]')
        self.settled(page,'SCORE.view.score.tracks.guitar.midi.source_volume?.value===63')
        self.assertEqual(path.read_bytes(),original)
        page.click('[data-action=redo]')
        self.settled(page,'!SCORE.view.score.tracks.guitar.midi.source_volume')
        self.assertEqual(path.read_bytes(),changed)
        page.click('[data-action=undo]')
        self.settled(page,'SCORE.view.score.tracks.guitar.midi.source_volume?.value===63')
        self.assertEqual(path.read_bytes(),original)
        with tempfile.TemporaryDirectory(prefix='vt-mixer-export-') as destination:
            page.click('[data-t=export]')
            page.uncheck('#export-stems')
            page.fill('#export-dest',destination)
            for fmt in ('tg','gp5','mid'):
                page.select_option('#export-format',fmt)
                page.fill('#export-name','mixer-'+fmt)
                page.click('#export-go')
                page.wait_for_function('name=>S.export?.files?.some(p=>p.includes(name))&&S.export.status==="done"',arg='mixer-'+fmt,timeout=30000)
                output = Path(destination)/('mixer-'+fmt+'.'+fmt)
                if fmt=='tg':
                    channel = tgimport._xml(output.read_bytes()).find('TGChannel')
                    self.assertEqual((channel.findtext('volume'),channel.findtext('balance')),('63','15'))
                elif fmt=='gp5':
                    channel = gpimport._read_native_gp(output.read_bytes()).tracks[0].channel
                    self.assertEqual((channel.volume,channel.balance),(64,16))
                else:
                    messages = [m for track in mido.MidiFile(output).tracks for m in track]
                    self.assertTrue(any(m.type=='control_change' and m.control==7 and m.value==63 for m in messages))
                    self.assertTrue(any(m.type=='control_change' and m.control==10 and m.value==15 for m in messages))
        page.evaluate("tab('tab');setEdit(false)")
        self.settled(page,'SCORE.view.score.tracks.guitar.midi.source_volume?.value===63')
        self.assertEqual(path.read_bytes(),original)
        self.assertEqual(errors,[])
        return dict(source_mix=True,same_value_write=True,exact_undo_redo=True,exports=['tg','gp5','mid'],page_errors=errors)

    def test_mixer_interchange_real_controls(self):
        from tests.test_tablature_sync import complete_song_seed
        source = complete_song_seed()
        source['module']['title'] = 'Mixer interchange'
        for sample in source['samples'].values(): sample['file']='a.wav'
        track = source['score']['tracks']['guitar']
        for ch in track['channels']: source['module']['channels'][ch].update(volume=32,pan=8)
        track['midi'].update(source_volume=dict(value=63,mixer_volume=32),source_pan=dict(value=15,mixer_pan=8))
        with self.muted_page(api.to_yaml(source)) as (page,state,folder):
            self.assertFalse(state.error,state.error)
            self.run_mixer_interchange(page,folder/'song.yaml')

    def test_track_source_pan_setup_same_center_write_mix_and_undo(self):
        from vulturetracker import server
        source = api.from_yaml(NATIVE_SONG)
        source['module']['channels'] = [dict(name='Guitar', pan=32), dict(name='Unused', pan=32)]
        source['score']['tracks']['guitar']['midi'] = dict(
            program=25, bank=3, source_pan=dict(value=63, mixer_pan=32))
        binding = dict(value=63, mixer_pan=32)
        with self.page(api.to_yaml(source)) as (page, state, folder):
            self.assertFalse(state.error, state.error)
            page.evaluate("tab('tab');setEdit(true)")
            page.wait_for_selector('.vt-tab-grid [data-note=note-0]')
            self.open_setup(page)
            self.assertIn('clearing the program or reassigning channels removes the bindings', page.inner_text('[data-ui=midi-source-pan]'))
            for field, value, condition in [
                    ('display-name', 'Imported guitar', "SCORE.view.score.tracks.guitar.name==='Imported guitar'"),
                    ('midi-program', '26', 'SCORE.view.score.tracks.guitar.midi.program===26'),
                    ('midi-bank', '', "!('bank' in SCORE.view.score.tracks.guitar.midi)")]:
                page.fill(f'[data-ui={field}]', value)
                page.locator('.vt-tab-setup button[type=submit]').first.click()
                self.settled(page, condition)
                self.assertEqual(state.song['score']['tracks']['guitar']['midi']['source_pan'], binding)
            saved = (folder / 'song.yaml').read_bytes()
            page.evaluate('async path=>{await openSong(path)}', str(folder / 'song.yaml'))
            state = server.Handler.state
            page.evaluate("tab('tab');setEdit(true)")
            page.wait_for_selector('.vt-tab-grid [data-note=note-0]')
            self.open_setup(page)
            self.assertEqual(state.song['score']['tracks']['guitar']['midi']['source_pan'], binding)
            page.fill('[data-ui=midi-program]', '')
            page.locator('.vt-tab-setup button[type=submit]').first.click()
            self.settled(page, '!SCORE.view.score.tracks.guitar.midi')
            self.assertNotIn('midi', state.song['score']['tracks']['guitar'])
            page.click('[data-action=undo]')
            self.settled(page, 'SCORE.view.score.tracks.guitar.midi?.source_pan?.value===63')
            self.assertEqual((folder / 'song.yaml').read_bytes(), saved)
            page.wait_for_function('S.source_pan_channels?.includes(0)')
            page.evaluate("tab('overview')")
            page.click('#mp1')
            page.fill('.typein', '32')
            page.press('.typein', 'Enter')
            page.wait_for_function('!S.mix?.pan')
            page.click('#mp0')
            page.fill('.typein', '32')
            page.press('.typein', 'Enter')
            page.wait_for_function("S.mix?.pan?.['0']===32")
            self.assertEqual(state.song['score']['tracks']['guitar']['midi']['source_pan'], binding)
            self.assertEqual((folder / 'song.yaml').read_bytes(), saved)
            page.click('#writemix')
            page.wait_for_selector('#diffmodal')
            self.assertIn('source_pan', page.inner_text('#difflines'))
            page.click('#diffmodal .btn.big')
            page.wait_for_function('S.source_pan_channels?.length===0')
            self.assertNotIn('source_pan', state.song['score']['tracks']['guitar']['midi'])
            self.assertEqual(state.song['module']['channels'][0]['pan'], 32)
            page.evaluate("tab('tab')")
            page.wait_for_function('!SCORE.view.score.tracks.guitar.midi.source_pan')
            page.click('[data-action=undo]')
            self.settled(page, 'SCORE.view.score.tracks.guitar.midi?.source_pan?.value===63')
            self.assertEqual((folder / 'song.yaml').read_bytes(), saved)
            self.open_setup(page)
            page.uncheck('[data-ui=auto-channels]')
            page.fill('[data-ui=channels]', '2')
            page.locator('.vt-tab-setup button[type=submit]').first.click()
            self.settled(page, 'SCORE.view.score.tracks.guitar.channels[0]===1')
            self.assertNotIn('source_pan', state.song['score']['tracks']['guitar']['midi'])
            page.click('[data-action=undo]')
            self.settled(page, 'SCORE.view.score.tracks.guitar.midi?.source_pan?.value===63')
            self.assertEqual((folder / 'song.yaml').read_bytes(), saved)

    def test_track_midi_assignment_save_preserve_reopen_clear_and_undo(self):
        from vulturetracker import server
        with self.page(NATIVE_SONG) as (page, state, folder):
            before = (folder / 'song.yaml').read_bytes()
            beats = json.loads(json.dumps(state.song['score']['patterns']))
            events = json.loads(json.dumps(state.mod.native_score['plan']['events']))
            page.evaluate("tab('tab');setEdit(true)")
            page.wait_for_selector('.vt-tab-grid [data-note=note-0]')
            self.open_setup(page)
            self.assertEqual(page.input_value('[data-ui=midi-program]'), '')
            self.assertEqual(page.input_value('[data-ui=midi-bank]'), '')
            page.fill('[data-ui=midi-program]', '127')
            page.fill('[data-ui=midi-bank]', '16383')
            page.click('.vt-tab-setup button[type=submit]')
            self.settled(page, "SCORE.view.score.tracks.guitar.midi?.bank===16383")
            self.assertEqual(state.song['score']['tracks']['guitar']['midi'], {'program': 127, 'bank': 16383})
            self.assertEqual(state.song['score']['patterns'], beats)
            self.assertEqual(state.mod.native_score['plan']['events'], events)
            page.fill('[data-ui=display-name]', 'Export guitar')
            page.click('.vt-tab-setup button[type=submit]')
            self.settled(page, "SCORE.view.score.tracks.guitar.name==='Export guitar'")
            self.assertEqual(state.song['score']['tracks']['guitar']['midi'], {'program': 127, 'bank': 16383})
            saved = (folder / 'song.yaml').read_bytes()
            for field, value in (('midi-program', '128'), ('midi-program', '-1'),
                                 ('midi-program', '1.5'), ('midi-bank', '16384'),
                                 ('midi-bank', '-1'), ('midi-bank', '1.5')):
                page.fill('[data-ui=midi-program]', '127')
                page.fill('[data-ui=midi-bank]', '16383')
                page.fill(f'[data-ui={field}]', value)
                page.click('.vt-tab-setup button[type=submit]')
                self.assertFalse(page.locator(f'[data-ui={field}]').evaluate('e=>e.validity.valid'))
                self.assertEqual((folder / 'song.yaml').read_bytes(), saved)
            page.fill('[data-ui=midi-program]', '0')
            page.fill('[data-ui=midi-bank]', '')
            page.click('.vt-tab-setup button[type=submit]')
            self.settled(page, "SCORE.view.score.tracks.guitar.midi?.program===0")
            self.assertEqual(state.song['score']['tracks']['guitar']['midi'], {'program': 0})
            page.evaluate('async path=>{await openSong(path)}', str(folder / 'song.yaml'))
            state = server.Handler.state
            page.evaluate("tab('tab');setEdit(true)")
            page.wait_for_selector('.vt-tab-grid [data-note=note-0]')
            self.open_setup(page)
            self.assertEqual(page.input_value('[data-ui=midi-program]'), '0')
            self.assertEqual(page.input_value('[data-ui=midi-bank]'), '')
            self.assertEqual(state.song['score']['patterns'], beats)
            self.assertEqual(state.mod.native_score['plan']['events'], events)
            page.fill('[data-ui=midi-program]', '')
            page.fill('[data-ui=midi-bank]', '400')  # Blank program clears even with a remaining valid bank.
            page.click('.vt-tab-setup button[type=submit]')
            self.settled(page, "!('midi' in SCORE.view.score.tracks.guitar)")
            self.assertNotIn('midi', api.load(folder / 'song.yaml')['score']['tracks']['guitar'])
            self.assertEqual(len(state.history), 4)
            for remaining in range(3, -1, -1):
                revision = page.evaluate('SCORE.view.revision')
                page.click('[data-action=undo]')
                self.settled(page, f"SCORE.view.revision!=={json.dumps(revision)}")
                self.assertEqual(len(state.history), remaining)
            self.assertEqual((folder / 'song.yaml').read_bytes(), before)
            self.open_setup(page)
            self.assertEqual(page.input_value('[data-ui=midi-program]'), '')
            self.assertEqual(page.input_value('[data-ui=midi-bank]'), '')

    def test_hammer_engraving_falls_back_beyond_renderer_link_range(self):
        from tests.test_tablature import beat, note
        source = api.from_yaml(NATIVE_SONG)
        source['orders'], source['score']['order_ids'], source['score']['ties'] = ['verse'], ['only'], []
        source['patterns']['verse']['rows'] = 60
        first, last = note('origin', 64), note('target', 67)
        first['hammer'] = last['hammer'] = True
        last['velocity'] = 95
        source['score']['patterns']['verse']['beats'] = [
            {**beat('first', [0, 1], [first]), 'text': 'Across long rest'},
            {**beat('last', [4, 1], [last]), 'text': 'End'}]
        source['score']['measures'] = [
            {'id': f'm{i}', 'from': {'occurrence': 'only', 'at': [i, 1]},
             'to': {'occurrence': 'only', 'at': [i + 1, 1]}, 'meter': [1, 4]} for i in range(5)]
        with self.page(api.to_yaml(source)) as (page, state, folder):
            before = (folder / 'song.yaml').read_bytes()
            page.evaluate("tab('tab')")
            page.wait_for_selector('.vt-tab-grid [data-note=origin]')
            self.capture_engraving(page)
            page.evaluate("""()=>{
                const view=JSON.parse(JSON.stringify(SCORE.view));
                view.score.tracks.guitar.name='Fallback engraving';
                SCORE.editor.update(view);
            }""")
            displayed = page.evaluate("""tabRendered.tracks[0].staves[0].bars.flatMap(
                b=>b.voices[0].beats).filter(b=>b.notes.length).map(
                b=>({text:b.text,link:b.notes[0].isHammerPullOrigin}))""")
            self.assertEqual(displayed, [
                {'text': 'Across long rest · Hammer-on/pull-off: string 1', 'link': False},
                {'text': 'End · Hammer-on/pull-off: string 1', 'link': False}])
            page.wait_for_selector('.vt-tab-score svg')
            self.assertIn('Hammer-on/pull-off: string 1', page.inner_text('.vt-tab-score'))
            self.assertNotIn('rendering failed', page.inner_text('.vt-tab-status'))
            self.assertEqual((folder / 'song.yaml').read_bytes(), before)
            self.assertEqual(state.history, [])

    def test_native_ghost_accents_hammer_refusals_chord_engraving_audio_and_undo(self):
        from tests.test_tablature import beat, note
        source = api.from_yaml(NATIVE_SONG)
        source['module'].update(tempo=120, channels=[{'name': 'High'}, {'name': 'Low'}])
        source['samples'][1]['loop'] = {'start': 0, 'end': RATE // 10}
        source['orders'], source['score']['order_ids'], source['score']['ties'] = ['verse'], ['only'], []
        source['score']['tracks']['guitar'].update(tuning=[64, 59], channels=[0, 1])
        high, low = note('high', 64), note('low', 59, 2, 0)
        high['slide'] = True
        low['volume'] = 23
        source['score']['patterns']['verse']['beats'] = [
            beat('origin', [0, 1], [high, low], value=2),
            beat('rest', [2, 1], [], value=4),
            beat('target', [3, 1], [note('next-high', 67, 1, 3), note('next-low', 62, 2, 3)], value=4)]
        with self.page(api.to_yaml(source)) as (page, state, folder):
            before = (folder / 'song.yaml').read_bytes()
            page.evaluate("tab('tab');setEdit(true);setSpeed(1)")
            page.wait_for_selector('.vt-tab-grid [data-note=high]')
            self.capture_engraving(page)
            rendered = 'tabRendered.tracks[0].staves[0].bars[0].voices[0].beats[0]'
            page.click('.vt-tab-grid th [data-at="0/1"]')
            page.click('[data-action=ghost]')
            page.wait_for_function("!EDQ.n && document.querySelector('.vt-tab-status').textContent.includes('explicit authored MIDI velocity')")
            self.assertEqual((folder / 'song.yaml').read_bytes(), before)
            self.assertEqual(page.input_value('[data-ui=velocity]'), '')
            page.select_option('[data-ui=dynamics]', '95')
            page.click('[data-action=velocity]')
            self.settled(page, "SCORE.view.score.patterns.verse.beats[0].notes.every(n=>n.velocity===95)")

            def rms(row=0):
                page.evaluate(f"async()=>{{await lvPlay(0,{row});LV.an.fftSize=8192;LV.pos=null}}")
                page.wait_for_function(f"LV.playing && !LV.loading && LV.pos?.scoreFrame>LV.ctx.sampleRate*({row}/24+.25)")
                result = page.evaluate("""()=>{
                    const x=new Float32Array(LV.an.fftSize);LV.an.getFloatTimeDomainData(x);
                    return {rms:Math.sqrt(x.reduce((sum,v)=>sum+v*v,0)/x.length),error:LV.err};
                }""")
                page.evaluate('lvStop()')
                self.assertIsNone(result['error'])
                return result['rms']

            plain = rms()
            self.assertGreater(plain, .001)
            for action, field, performed, accent in (
                    ('ghost', 'ghost', 79, 0), ('accent', 'accent', 111, 1),
                    ('heavy-accent', 'heavy_accent', 127, 2)):
                page.click(f'[data-action={action}]')
                self.settled(page, f"SCORE.view.score.patterns.verse.beats[0].notes.every(n=>n.{field})")
                notes = state.song['score']['patterns']['verse']['beats'][0]['notes']
                for n in notes:
                    self.assertEqual([key for key in ('ghost', 'accent', 'heavy_accent') if n.get(key)], [field])
                    self.assertEqual(n['velocity'], 95)
                self.assertNotIn('string', notes[0])
                self.assertEqual(notes[1]['volume'], 23)
                self.assertEqual(page.input_value('[data-ui=velocity]'), '95')
                self.assertEqual(page.evaluate(rendered + '.notes.map(n=>n.isGhost)'), [field == 'ghost'] * 2)
                self.assertEqual(page.evaluate(rendered + '.notes.map(n=>n.accentuated)'), [accent] * 2)
                if field == 'ghost':
                    self.assertEqual(page.inner_text('.vt-tab-grid [data-note=high]'), '(0)')
                self.assertAlmostEqual(rms() / plain, performed / 95, delta=.035)
            page.click('[data-action=heavy-accent]')
            self.settled(page, "SCORE.view.score.patterns.verse.beats[0].notes.every(n=>!n.heavy_accent)")
            page.click('.vt-tab-grid [data-note=high]')
            page.click('[data-action=ghost]')
            self.settled(page, "SCORE.view.score.patterns.verse.beats[0].notes[0].ghost")
            page.click('.vt-tab-grid th [data-at="0/1"]')
            self.assertEqual(page.get_attribute('[data-action=ghost]', 'aria-pressed'), 'mixed')
            page.click('[data-action=ghost]')
            self.settled(page, "SCORE.view.score.patterns.verse.beats[0].notes.every(n=>n.ghost)")
            for _ in range(2):
                revision = page.evaluate('SCORE.view.revision')
                page.click('[data-action=undo]')
                self.settled(page, f"SCORE.view.revision!=={json.dumps(revision)}")
            self.assertEqual(len(state.history), 5)
            saved = (folder / 'song.yaml').read_bytes()
            page.click('.vt-tab-grid th [data-at="0/1"]')
            page.click('[data-action=hammer]')
            page.wait_for_function("!EDQ.n && document.querySelector('.vt-tab-status').textContent.includes('hammer predecessor')")
            self.assertEqual((folder / 'song.yaml').read_bytes(), saved)
            self.assertTrue(state.song['score']['patterns']['verse']['beats'][0]['notes'][0]['slide'])
            page.click('.vt-tab-grid th [data-at="3/1"]')
            self.assertEqual(page.input_value('[data-ui=velocity]'), '')
            page.select_option('[data-ui=dynamics]', '95')
            page.click('[data-action=velocity]')
            self.settled(page, "SCORE.view.score.patterns.verse.beats[2].notes.every(n=>n.velocity===95)")
            target_plain = rms(36)
            page.click('.vt-tab-grid th [data-at="0/1"]')
            page.click('[data-action=hammer]')
            self.settled(page, "SCORE.view.score.patterns.verse.beats[0].notes.every(n=>n.hammer)")
            self.assertFalse(state.song['score']['patterns']['verse']['beats'][0]['notes'][0].get('slide'))
            self.assertEqual(page.evaluate(rendered + '.notes.map(n=>n.isHammerPullOrigin)'), [True, True])
            self.assertEqual(page.evaluate(rendered + '.notes.map(n=>n.hammerPullDestination.fret)'), [3, 3])
            self.assertAlmostEqual(rms(36) / target_plain, 70 / 95, delta=.035)
            self.assertEqual(len(state.history), 7)
            for remaining in range(6, -1, -1):
                revision = page.evaluate('SCORE.view.revision')
                page.click('[data-action=undo]')
                self.settled(page, f"SCORE.view.revision!=={json.dumps(revision)}")
                self.assertEqual(len(state.history), remaining)
            self.assertEqual((folder / 'song.yaml').read_bytes(), before)

    def test_native_gp_import_ui_retains_annotations_velocity_and_plays(self):
        from tests.test_gpimport import guitarpro, M, native_tab
        from vulturetracker import server
        if guitarpro is None:
            self.skipTest('PyGuitarPro not installed')
        with self.muted_page() as (page, state, folder):
            original = (folder / 'song.yaml').read_bytes()
            fixture = native_tab()
            fixture.measureHeaders[0].marker = M.Marker(title='Verse café', color=M.Color(23, 45, 67))
            fixture.measureHeaders[0].hasDoubleBar = True
            fixture.measureHeaders[1].keySignature = M.KeySignature.DMajor
            fixture.tracks[0].clefTranspose = 12
            fixture.tracks[0].measures[0].voices[0].beats[0].notes[0].durationPercent = .75
            fixture.tracks[0].measures[0].voices[0].beats[0].text = 'Let it breathe <softly>'
            path = folder / 'source.gp5'
            guitarpro.write(fixture, str(path), version=(5, 1, 0))
            source_bytes = path.read_bytes()
            page.evaluate('renderStart()')
            page.wait_for_selector('#imppath')
            page.fill('#imppath', str(path))
            self.assertTrue(page.is_checked('#impnative'))
            with page.expect_response(lambda r: r.url.endswith('/api/import')) as response:
                page.press('#imppath', 'Enter')
            result = response.value.json()
            self.assertNotIn('error', result)
            self.assertEqual(result['path'], str(folder / 'source.yaml'))
            page.wait_for_function(f"!$('startmodal').classList.contains('on') && S?.song?.path==={json.dumps(result['path'])}")
            imported = server.Handler.state
            self.assertEqual(imported.song_path, folder / 'source.yaml')
            saved = api.load(imported.song_path)
            self.assertEqual(saved['score']['measures'][0]['marker'], {'title': 'Verse café', 'color': '#172d43'})
            self.assertTrue(saved['score']['measures'][0]['double_bar'])
            self.assertEqual(saved['score']['measures'][1]['staff']['t1']['key']['fifths'], 2)
            first = saved['score']['patterns']['m1']['beats'][0]
            self.assertEqual(first['text'], 'Let it breathe <softly>')
            self.assertEqual(first['notes'][0]['velocity'], 95)
            self.assertNotIn('volume', first['notes'][0])
            self.assertEqual(len(list((folder / 'source_samples').glob('*.wav'))), 7)
            page.evaluate("scoreScript('/web/alphaTab.min.js')")
            self.capture_engraving(page)
            page.evaluate("tab('tab');setEdit(true)")
            page.wait_for_selector('.vt-tab-grid [data-note=t1_v1_b1_s1]')
            page.click('.vt-tab-grid [data-note=t1_v1_b1_s1]')
            self.assertEqual(page.input_value('[data-ui=beat-text]'), 'Let it breathe <softly>')
            self.assertEqual(page.input_value('[data-ui=dynamics]'), '95')
            self.assertEqual(page.locator('[data-marker]').first.evaluate('e=>e.style.borderLeftColor'), 'rgb(23, 45, 67)')
            page.wait_for_selector('.vt-tab-score svg')
            self.assertIn('Let it breathe <softly>', page.inner_text('.vt-tab-score'))
            self.assertIn('Verse café', page.inner_text('.vt-tab-score'))
            self.assertTrue(page.evaluate('tabRendered.masterBars[0].isDoubleBar'))
            self.assertEqual(page.evaluate('tabRendered.tracks[0].staves[0].bars.map(b=>b.keySignature)'), [0, 2])
            page.evaluate('async()=>{setSpeed(1);await lvPlay(0,0)}')
            page.wait_for_function("""()=>{
                if(!LV.playing || LV.err || !LV.an || !LV.pos?.scoreFrame)return false;
                const x=new Float32Array(LV.an.fftSize);LV.an.getFloatTimeDomainData(x);
                return Math.max(...x.map(Math.abs))>.0001;
            }""")
            self.assertIsNone(page.evaluate('LV.err'))
            page.evaluate('lvStop()')
            imported_bytes = imported.song_path.read_bytes()
            page.fill('[data-ui=beat-text]', 'Editable import')
            page.click('[data-action=beat-text]')
            self.settled(page, "SCORE.view.score.patterns.m1.beats[0].text==='Editable import'")
            edited_bytes = imported.song_path.read_bytes()
            self.assertNotEqual(edited_bytes, imported_bytes)
            self.assertTrue(imported.song['score']['measures'][0]['double_bar'])
            for action, expected in (('undo', imported_bytes), ('redo', edited_bytes), ('undo', imported_bytes)):
                revision = page.evaluate('SCORE.view.revision')
                page.click(f'[data-action={action}]')
                self.settled(page, f'SCORE.view.revision!=={json.dumps(revision)}')
                self.assertEqual(imported.song_path.read_bytes(), expected)
            self.assertEqual(path.read_bytes(), source_bytes)
            self.assertEqual((folder / 'song.yaml').read_bytes(), original)
            self.assertEqual(imported.history, [])

    def test_native_annotations_save_navigation_split_print_and_undo(self):
        from tests.test_tablature import beat, note
        source = api.from_yaml(NATIVE_SONG)
        source['module']['channels'] = [{'name': 'High'}, {'name': 'Low'}]
        source['orders'], source['score']['order_ids'], source['score']['ties'] = ['verse', 'verse'], ['first', 'second'], []
        source['score']['tracks']['guitar'].update(tuning=[64, 59], channels=[0, 1])
        high, low = note('high', 64), note('low', 59, 2, 0)
        high.update(velocity=73, slide=True)
        low.update(volume=23, tremolo_bar={'points': [{'position': 0, 'value': 0}, {'position': 12, 'value': 0}]})
        source['score']['patterns']['verse']['beats'] = [beat('long', [0, 1], [high, low], value=1)]
        source['score']['measures'] = [
            {'id': 'intro', 'from': {'occurrence': 'first', 'at': [0, 1]},
             'to': {'occurrence': 'first', 'at': [1, 1]}, 'meter': [1, 4],
             'marker': {'title': 'Intro', 'color': '#2468ac'}},
            {'id': 'return', 'from': {'occurrence': 'second', 'at': [1, 3]},
             'to': {'occurrence': 'second', 'at': [4, 3]}, 'meter': [1, 4],
             'marker': {'title': 'Return', 'color': '#aa3355'}}]
        with self.muted_page(api.to_yaml(source)) as (page, state, folder):
            before = (folder / 'song.yaml').read_bytes()
            page.evaluate("tab('tab');setEdit(true)")
            page.wait_for_selector('.vt-tab-grid [data-note=high]')
            self.capture_engraving(page)
            page.click('.vt-tab-grid [data-note=high]')
            annotation = 'Let ring <naturally> & breathe "café"'
            page.fill('[data-ui=beat-text]', annotation)
            page.click('[data-action=beat-text]')
            self.settled(page, f"SCORE.view.score.patterns.verse.beats[0].text==={json.dumps(annotation)}")
            chord = state.song['score']['patterns']['verse']['beats'][0]
            self.assertNotIn('string', chord['notes'][0])
            self.assertEqual(chord['notes'], source['score']['patterns']['verse']['beats'][0]['notes'])
            texts = page.evaluate('tabRendered.tracks[0].staves[0].bars.flatMap(b=>b.voices[0].beats).map(b=>b.text)')
            self.assertEqual(sum(annotation in (text or '') for text in texts), 2)
            self.assertIn('Tremolo bar: string 2', texts[0])
            self.assertNotIn('Velocity:', ' '.join(t or '' for t in texts))
            self.assertIn('string 1=73, string 2=inherit', page.inner_text('[data-ui=velocity-info]'))
            self.assertIn('Slide: string 1', texts[-1])
            self.assertEqual(page.evaluate('tabRendered.masterBars[0].section.text'), 'Intro')
            page.wait_for_selector('.vt-tab-score svg')
            self.assertIn(annotation, page.inner_text('.vt-tab-score'))
            self.assertNotIn('rendering failed', page.inner_text('.vt-tab-status'))

            self.open_panel(page, 'measures')
            page.select_option('[data-ui=measure]', 'intro')
            self.assertEqual(page.input_value('[data-ui=marker-color]'), '#2468ac')
            page.fill('[data-ui=marker-title]', 'Opening <A>')
            page.click('.vt-tab-measures button[type=submit]')
            self.settled(page, "SCORE.view.score.measures[0].marker.title==='Opening <A>'")
            self.assertEqual(state.song['score']['measures'][0]['marker']['color'], '#2468ac')
            self.assertEqual(page.locator('[data-marker=intro]').evaluate('e=>e.style.borderLeftColor'), 'rgb(36, 104, 172)')
            self.assertEqual(page.evaluate('tabRendered.masterBars[0].section.text'), 'Opening <A>')
            page.click('[data-action=close-measures]')
            page.click('[data-action=marker-next]')
            self.settled(page, "SCORE.view.order===1 && CUR.o===1 && CUR.row===4")
            self.assertEqual(page.input_value('[data-ui=at]'), '1/3')
            page.click('[data-action=marker-previous]')
            self.settled(page, "SCORE.view.order===0 && CUR.o===0 && CUR.row===0")
            page.click('[data-marker=return]')
            self.settled(page, "SCORE.view.order===1 && CUR.row===4")
            self.assertEqual(page.input_value('[data-ui=at]'), '1/3')
            self.assertEqual(len(state.history), 2)

            preview = page.context.browser.new_page()
            preview.goto(self.print_url(page, state))
            self.print_ready(preview)
            self.capture_engraving(preview)
            preview.locator('form button[type=submit]').click()
            self.print_ready(preview)
            self.assertEqual(preview.evaluate("tabRendered.masterBars.map(b=>b.section?.text).filter(t=>t && t!=='Unmetered')"),
                             ['Opening <A>', 'Return'])
            printed = preview.evaluate('tabRendered.tracks[0].staves[0].bars.flatMap(b=>b.voices[0].beats).map(b=>b.text)')
            self.assertEqual(sum(annotation in (text or '') for text in printed), 2)
            self.assertIn(annotation, preview.inner_text('.vt-print-pages'))
            preview.close()

            page.click('[data-marker=intro]')
            self.settled(page, "SCORE.view.order===0 && CUR.row===0")
            self.open_panel(page, 'measures')
            page.select_option('[data-ui=measure]', 'intro')
            page.fill('[data-ui=marker-color]', '')
            page.click('.vt-tab-measures button[type=submit]')
            self.settled(page, "!('color' in SCORE.view.score.measures[0].marker)")
            self.assertEqual(state.song['score']['measures'][0]['marker'], {'title': 'Opening <A>'})
            page.fill('[data-ui=marker-title]', '')
            page.click('.vt-tab-measures button[type=submit]')
            self.settled(page, "!SCORE.view.score.measures[0].marker")
            self.assertEqual(page.locator('[data-marker=intro]').count(), 0)
            page.click('[data-action=close-measures]')
            page.fill('[data-ui=beat-text]', '')
            page.click('[data-action=beat-text]')
            self.settled(page, "!('text' in SCORE.view.score.patterns.verse.beats[0])")
            self.assertEqual(len(state.history), 5)
            for remaining in range(4, -1, -1):
                revision = page.evaluate('SCORE.view.revision')
                page.click('[data-action=undo]')
                self.settled(page, f"SCORE.view.revision!=={json.dumps(revision)}")
                self.assertEqual(len(state.history), remaining)
            self.assertEqual((folder / 'song.yaml').read_bytes(), before)

    def test_native_dynamics_presets_custom_chord_inherit_undo_and_live_gain(self):
        """Run after the qualified vt_gain runtime is promoted."""
        from tests.test_tablature import beat, note
        source = api.from_yaml(NATIVE_SONG)
        source['module'].update(tempo=120, channels=[{'name': 'High'}, {'name': 'Low'}])
        source['samples'][1]['loop'] = {'start': 0, 'end': RATE // 10}
        source['orders'], source['score']['order_ids'], source['score']['ties'] = ['verse'], ['pass-1'], []
        source['score']['tracks']['guitar'].update(tuning=[64, 59], channels=[0, 1])
        low = note('low', 59, 2, 0)
        low['volume'] = 23
        source['score']['patterns']['verse']['beats'] = [
            beat('chord', [0, 1], [note('high', 64), low], value=1)]
        with self.muted_page(api.to_yaml(source)) as (page, state, folder):
            before = (folder / 'song.yaml').read_bytes()
            original = json.loads(json.dumps(state.song['score']['patterns']['verse']['beats'][0]))
            page.evaluate("tab('tab');setEdit(true);setSpeed(1)")
            page.wait_for_selector('.vt-tab-grid [data-note=high]')
            self.capture_engraving(page)
            rendered = 'tabRendered.tracks[0].staves[0].bars[0].voices[0].beats[0]'
            page.click('.vt-tab-grid [data-note=high]')
            self.assertEqual(page.input_value('[data-ui=dynamics]'), '')
            self.assertEqual(page.input_value('[data-ui=velocity]'), '')
            page.select_option('[data-ui=dynamics]', label='mp')
            self.assertEqual(page.input_value('[data-ui=velocity]'), '63')
            page.click('[data-action=velocity]')
            self.settled(page, "SCORE.view.score.patterns.verse.beats[0].notes[0].velocity===63")
            self.assertNotIn('velocity', state.song['score']['patterns']['verse']['beats'][0]['notes'][1])
            self.assertIsNone(page.evaluate(rendered + '.dynamics'))
            self.assertIsNone(page.evaluate(rendered + '.text'))
            self.assertIn('string 1=63, string 2=inherit', page.inner_text('[data-ui=velocity-info]'))
            self.assertIn('Velocity: 63', page.get_attribute('.vt-tab-grid [data-note=high]', 'title'))
            saved = (folder / 'song.yaml').read_bytes()
            for invalid in ('128', '-1', '1.5'):
                page.fill('[data-ui=velocity]', invalid)
                page.click('[data-action=velocity]')
                self.assertIn('integer from 0 to 127', page.inner_text('.vt-tab-status'))
                self.assertEqual((folder / 'song.yaml').read_bytes(), saved)
            page.fill('[data-ui=velocity]', '73')
            page.click('[data-action=velocity]')
            self.settled(page, "SCORE.view.score.patterns.verse.beats[0].notes[0].velocity===73")
            self.assertEqual(page.input_value('[data-ui=dynamics]'), 'custom')
            page.click('.vt-tab-grid th [data-at="0/1"]')
            self.assertEqual(page.get_attribute('[data-ui=velocity]', 'placeholder'), 'mixed')
            self.assertEqual(page.input_value('[data-ui=dynamics]'), 'custom')
            saved = (folder / 'song.yaml').read_bytes()
            page.click('[data-action=velocity]')
            self.assertIn('mixed chord', page.inner_text('.vt-tab-status'))
            self.assertEqual((folder / 'song.yaml').read_bytes(), saved)
            page.select_option('[data-ui=dynamics]', label='mf')
            page.click('[data-action=velocity]')
            self.settled(page, "SCORE.view.score.patterns.verse.beats[0].notes.every(n=>n.velocity===79)")
            self.assertEqual(len(state.history), 3)
            self.assertEqual(page.evaluate(rendered + '.dynamics'), 4)
            self.assertEqual(page.evaluate(rendered + '.notes.map(n=>n.dynamics)'), [4, 4])
            self.assertIsNone(page.evaluate(rendered + '.text'))
            page.select_option('[data-ui=dynamics]', label='Instrument default')
            page.click('[data-action=velocity]')
            self.settled(page, "SCORE.view.score.patterns.verse.beats[0].notes.every(n=>n.velocity==null)")
            self.assertEqual(state.song['score']['patterns']['verse']['beats'][0], original)
            self.assertEqual(page.evaluate(rendered + '.dynamics'), 5)
            self.assertIsNone(page.evaluate(rendered + '.text'))

            def rms():
                page.evaluate("async()=>{await lvPlay(0,0);LV.an.fftSize=16384;LV.pos=null}")
                page.wait_for_function("LV.playing && LV.pos?.scoreFrame>LV.ctx.sampleRate*.6 && !LV.loading")
                result = page.evaluate("""()=>{
                    const x=new Float32Array(LV.an.fftSize);LV.an.getFloatTimeDomainData(x);
                    return {rms:Math.sqrt(x.reduce((sum,v)=>sum+v*v,0)/x.length),error:LV.err};
                }""")
                page.evaluate('lvStop()')
                self.assertIsNone(result['error'])
                return result['rms']

            plain = rms()
            self.assertGreater(plain, .001)
            for velocity in (127, 64, 0, None):
                if velocity == 127:
                    page.select_option('[data-ui=dynamics]', label='fff')
                elif velocity is None:
                    page.select_option('[data-ui=dynamics]', label='Instrument default')
                else:
                    page.fill('[data-ui=velocity]', str(velocity))
                page.click('[data-action=velocity]')
                condition = 'n.velocity==null' if velocity is None else f'n.velocity==={velocity}'
                self.settled(page, f"SCORE.view.score.patterns.verse.beats[0].notes.every(n=>{condition})")
                if velocity in (0, 64):
                    self.assertEqual(page.evaluate(rendered + '.dynamics'), None if velocity == 0 else 3)
                    self.assertIsNone(page.evaluate(rendered + '.text'))
                    self.assertIn(f'string 1={velocity}, string 2={velocity}', page.inner_text('[data-ui=velocity-info]'))
                else:
                    self.assertEqual(page.evaluate(rendered + '.dynamics'), 5 if velocity is None else 7)
                value = rms()
                if velocity == 0:
                    self.assertLess(value, 1e-6)
                else:
                    self.assertAlmostEqual(value / plain, 1 if velocity is None else velocity / 127, delta=.03)
                chord = state.song['score']['patterns']['verse']['beats'][0]
                self.assertEqual(chord['written'], original['written'])
                self.assertNotIn('volume', chord['notes'][0])
                self.assertNotIn('string', chord['notes'][0])
                self.assertEqual(chord['notes'][1]['volume'], 23)
            self.assertEqual(len(state.history), 8)
            for remaining in range(7, -1, -1):
                revision = page.evaluate('SCORE.view.revision')
                page.click('[data-action=undo]')
                self.settled(page, f"SCORE.view.revision!=={json.dumps(revision)}")
                self.assertEqual(len(state.history), remaining)
            self.assertEqual((folder / 'song.yaml').read_bytes(), before)

    def test_native_pitch_curves_reach_live_audio_after_editor_save(self):
        """Run only after the qualified pitch runtime has been promoted."""
        from tests.test_tablature import beat, note
        source = api.from_yaml(NATIVE_SONG)
        source['module']['tempo'] = 120
        source['samples'][1]['loop'] = {'start': 0, 'end': RATE // 10}
        source['orders'], source['score']['order_ids'], source['score']['ties'] = ['verse'], ['pass-1'], []
        source['score']['patterns']['verse']['beats'] = [
            beat('long', [0, 1], [note('tone', 64)], value=2),
            beat('target', [2, 1], [note('target-note', 67)], value=2)]
        with self.page(api.to_yaml(source)) as (page, state, folder):
            before = (folder / 'song.yaml').read_bytes()
            page.evaluate("tab('tab');setEdit(true);setSpeed(1)")
            page.wait_for_selector('.vt-tab-grid [data-note=tone]')
            page.click('.vt-tab-grid [data-note=tone]')

            def frequency():
                page.evaluate("async()=>{await lvPlay(0,0);LV.an.fftSize=8192;LV.pos=null}")
                page.wait_for_function("LV.playing && LV.pos?.scoreFrame>LV.ctx.sampleRate*.35 && !LV.loading")
                result = page.evaluate("""() => {
                    const x=new Float32Array(LV.an.fftSize);LV.an.getFloatTimeDomainData(x);
                    const crossings=[];let energy=0;
                    for(let i=1;i<x.length;i++){energy+=x[i]*x[i];if(x[i-1]<0&&x[i]>=0)crossings.push(i-1-x[i-1]/(x[i]-x[i-1]));}
                    return {hz:(crossings.length-1)*LV.ctx.sampleRate/(crossings.at(-1)-crossings[0]),
                        rms:Math.sqrt(energy/x.length),error:LV.err,playing:LV.playing};
                }""")
                page.evaluate('lvStop()')
                self.assertIsNone(result['error'])
                self.assertTrue(result['playing'])
                self.assertGreater(result['rms'], .001)
                return result['hz']

            plain = frequency()
            for action, points in [('bend', '0:4, 12:4'), ('tremolo-bar', '0:-2, 12:-2')]:
                page.click(f'[data-action={action}]')
                page.fill('[data-ui=curve-points]', points)
                page.click('[data-ui=curve-apply]')
                field = 'bend' if action == 'bend' else 'tremolo_bar'
                self.settled(page, f"!!SCORE.view.score.patterns.verse.beats[0].notes[0].{field}")
                pitch_event = next(e for e in state.mod.native_score['plan']['events'] if e['type'] == 'pitch')
                expected_ratio = 2 ** ((pitch_event['bend_value'] - 64) * 12 / (64 * 12))
                measured = frequency()
                self.assertAlmostEqual(measured / plain, expected_ratio, delta=.008)
            page.click('[data-action=tremolo-bar]')
            page.click('[data-action=remove-curve]')
            self.settled(page, "SCORE.view.score.patterns.verse.beats[0].notes[0].tremolo_bar==null")
            page.click('[data-action=vibrato]')
            self.settled(page, "SCORE.view.score.patterns.verse.beats[0].notes[0].vibrato")
            self.assertTrue(any(e['type'] == 'pitch' for e in state.mod.native_score['plan']['events']))
            page.evaluate("""async()=>{
                window.pitchPositions=[];window.pitchOldMessage=lvMsg;
                lvMsg=m=>{if(m.type==='pos')window.pitchPositions.push({frame:m.scoreFrame,playing:m.playing,factor:m.factorQ});window.pitchOldMessage(m)};
                setSpeed(1.3);lvPatLoop=true;await lvPlay(0,[7,13]);
            }""")
            page.wait_for_function("""LV.playing && !LV.err && pitchPositions.some(p=>p.playing && p.factor===Math.round(65536/1.3)) &&
                pitchPositions.some((p,i)=>i && p.playing && p.frame<pitchPositions[i-1].frame)""")
            self.assertGreater(page.evaluate("""()=>{const a=new Float32Array(LV.an.fftSize);LV.an.getFloatTimeDomainData(a);
                return Math.max(...a.map(Math.abs))}"""), .001)
            page.evaluate('lvStop();lvMsg=window.pitchOldMessage;setSpeed(1)')
            page.click('[data-action=slide]')
            self.settled(page, "SCORE.view.score.patterns.verse.beats[0].notes[0].slide")
            self.assertTrue(state.song['score']['patterns']['verse']['beats'][0]['notes'][0]['vibrato'])
            self.assertTrue(any(e['type'] == 'pitch' for e in state.mod.native_score['plan']['events']))
            slid = frequency()
            self.assertGreater(slid / plain, 1.01)
            self.assertLess(slid / plain, 1.21)
            for _ in range(5):
                revision = page.evaluate('SCORE.view.revision')
                page.click('[data-action=undo]')
                self.settled(page, f"SCORE.view.revision!=={json.dumps(revision)}")
            self.assertEqual((folder / 'song.yaml').read_bytes(), before)

    def test_native_slide_chord_exclusions_retriggered_engraving_and_undo(self):
        source = api.from_yaml(NATIVE_SONG)
        source['module']['channels'] = [{'name': 'High'}, {'name': 'Low'}]
        source['score']['tracks']['guitar'].update(tuning=[64, 59], channels=[0, 1])
        chord = source['score']['patterns']['verse']['beats'][1]
        chord['notes'][0].update(bend={'points': [{'position': 0, 'value': 0}, {'position': 12, 'value': 4}]},
                                 vibrato=True)
        chord['notes'].append(dict(id='low', pitch=59, string=2, fret=0, volume=23,
                                  tremolo_bar={'points': [{'position': 0, 'value': 0}, {'position': 12, 'value': -2}]}))
        source['score']['patterns']['verse']['beats'][2]['notes'][0]['pitch'] = 66
        with self.page(api.to_yaml(source)) as (page, state, folder):
            before = (folder / 'song.yaml').read_bytes()
            page.evaluate("tab('tab');setEdit(true)")
            page.wait_for_selector('.vt-tab-grid [data-note="note-1"]')
            self.capture_engraving(page)
            page.click('.vt-tab-grid th [data-at="4/13"]')
            page.click('[data-action=slide]')
            self.settled(page, "SCORE.view.score.patterns.verse.beats[1].notes.every(n=>n.slide)")
            notes = state.song['score']['patterns']['verse']['beats'][1]['notes']
            self.assertTrue(all(not n.get('bend') and not n.get('tremolo_bar') and not n.get('dead') for n in notes))
            self.assertTrue(notes[0]['vibrato'])
            self.assertNotIn('string', notes[0])
            self.assertEqual(notes[1]['volume'], 23)
            self.assertEqual(len(state.history), 1)
            rendered = 'tabRendered.tracks[0].staves[0].bars[0].voices[0].beats[1]'
            self.assertEqual(page.evaluate(rendered + '.notes.map(n=>n.slideOutType)'), [1, 0])
            self.assertEqual(page.evaluate(rendered + '.notes[0].slideTarget.fret'), 2)
            self.assertIn('no following note', page.evaluate(rendered + '.text'))
            page.click('.vt-tab-grid [data-note="note-1"]')
            page.click('[data-action=dead]')
            self.settled(page, "SCORE.view.score.patterns.verse.beats[1].notes[0].dead")
            self.assertFalse(state.song['score']['patterns']['verse']['beats'][1]['notes'][0].get('slide'))
            self.assertTrue(state.song['score']['patterns']['verse']['beats'][1]['notes'][1]['slide'])
            page.click('[data-action=bend]')
            page.click('[data-ui=curve-apply]')
            self.settled(page, "!!SCORE.view.score.patterns.verse.beats[1].notes[0].bend")
            n = state.song['score']['patterns']['verse']['beats'][1]['notes'][0]
            self.assertFalse(n.get('slide') or n.get('dead'))
            self.assertTrue(n['vibrato'])
            for remaining in range(2, -1, -1):
                revision = page.evaluate('SCORE.view.revision')
                page.click('[data-action=undo]')
                self.settled(page, f"SCORE.view.revision!=={json.dumps(revision)}")
                self.assertEqual(len(state.history), remaining)
            self.assertEqual((folder / 'song.yaml').read_bytes(), before)

    def test_pitch_curve_engraving_splits_at_authored_measure_without_restarting(self):
        from tests.test_tablature import beat, note
        source = api.from_yaml(NATIVE_SONG)
        source['orders'], source['score']['order_ids'], source['score']['ties'] = ['verse'], ['pass-1'], []
        n = note('bend', 64)
        n['bend'] = {'points': [{'position': 0, 'value': 0}, {'position': 6, 'value': 4}, {'position': 12, 'value': 0}]}
        source['score']['patterns']['verse']['beats'] = [beat('long', [0, 1], [n], value=2)]
        source['score']['measures'] = [dict(id=f'm{i}', meter=[1, 4], **{
            'from': dict(occurrence='pass-1', at=[i, 1]), 'to': dict(occurrence='pass-1', at=[i+1, 1])}) for i in range(2)]
        with self.page(api.to_yaml(source)) as (page, state, folder):
            before = (folder / 'song.yaml').read_bytes()
            page.evaluate("tab('tab');setEdit(true)")
            page.wait_for_selector('.vt-tab-grid [data-note=bend]')
            self.capture_engraving(page)
            # A display-only name change triggers a new engraving without a write.
            page.evaluate("()=>{const v=structuredClone(SCORE.view);v.score.tracks.guitar.name='Curve split';SCORE.editor.update(v)}")
            curves = page.evaluate("""tabRendered.tracks[0].staves[0].bars.slice(0,2).map(
                b=>b.voices[0].beats[0].notes[0].bendPoints.map(p=>[p.offset,p.value]))""")
            self.assertEqual(curves, [[[0, 0], [60, 4]], [[0, 4], [60, 0]]])
            self.assertTrue(page.evaluate('tabRendered.tracks[0].staves[0].bars[1].voices[0].beats[0].notes[0].isTieDestination'))
            self.assertEqual((folder / 'song.yaml').read_bytes(), before)

    def test_native_pitch_curve_editor_validation_engraving_and_atomic_history(self):
        source = api.from_yaml(NATIVE_SONG)
        source['module']['channels'] = [{'name': 'High'}, {'name': 'Low'}]
        source['score']['tracks']['guitar'].update(tuning=[64, 59], channels=[0, 1])
        chord = source['score']['patterns']['verse']['beats'][1]
        chord['notes'][0]['dead'] = True
        chord['notes'].append(dict(id='low', pitch=59, string=2, fret=0, volume=23))
        with self.page(api.to_yaml(source)) as (page, state, folder):
            page.evaluate("tab('tab');setEdit(true)")
            page.wait_for_selector('.vt-tab-grid [data-note="note-1"]')
            self.capture_engraving(page)
            before = (folder / 'song.yaml').read_bytes()
            page.click('.vt-tab-grid [data-note="note-1"]')
            page.click('[data-action=bend]')
            self.assertEqual(page.input_value('[data-ui=curve-points]'), '0:0, 6:4, 12:4')
            page.fill('[data-ui=curve-points]', '6:4, 0:0')
            page.click('[data-ui=curve-apply]')
            self.assertIn('time order', page.inner_text('[data-ui=curve-status]'))
            self.assertEqual((folder / 'song.yaml').read_bytes(), before)
            page.fill('[data-ui=curve-points]', '0:0, 6:4, 6:2, 12:0')
            self.assertEqual(page.locator('[data-ui=curve-preview] circle').count(), 4)
            page.click('[data-ui=curve-apply]')
            self.settled(page, "SCORE.view.score.patterns.verse.beats[1].notes[0].bend?.points.length===4")
            note = state.song['score']['patterns']['verse']['beats'][1]['notes'][0]
            expected = [{'position': p, 'value': v} for p, v in [(0, 0), (6, 4), (6, 2), (12, 0)]]
            self.assertEqual(note['bend']['points'], expected)
            self.assertFalse(note.get('dead'))
            self.assertNotIn('string', note)
            self.assertNotIn('volume', note)
            rendered = 'tabRendered.tracks[0].staves[0].bars[0].voices[0].beats[1]'
            self.assertEqual(page.evaluate(rendered + '.notes[0].bendPoints.map(p=>[p.offset,p.value])'),
                             [[0, 0], [30, 4], [30, 2], [60, 0]])
            page.click('[data-action=bend]')
            page.click('[data-action=vibrato]')
            self.settled(page, "SCORE.view.score.patterns.verse.beats[1].notes[0].vibrato")
            page.click('[data-ui=curve-apply]')
            self.assertIn('song changed', page.inner_text('.vt-tab-status'))
            self.assertEqual(len(state.history), 2)
            page.click('[data-action=close-curve]')
            self.assertEqual(page.evaluate(rendered + '.notes[0].vibrato'), 1)
            self.assertEqual(state.song['score']['patterns']['verse']['beats'][1]['notes'][0]['bend']['points'], expected)

            page.click('.vt-tab-grid th [data-at="4/13"]')
            page.click('[data-action=tremolo-bar]')
            self.assertEqual(page.input_value('[data-ui=curve-points]'), '0:0, 6:-2, 12:0')
            page.click('[data-ui=curve-apply]')
            self.settled(page, "SCORE.view.score.patterns.verse.beats[1].notes.every(n=>n.tremolo_bar)")
            notes = state.song['score']['patterns']['verse']['beats'][1]['notes']
            self.assertTrue(all(not n.get('bend') and not n.get('dead') for n in notes))
            self.assertTrue(notes[0]['vibrato'])
            self.assertEqual(notes[1]['volume'], 23)
            self.assertNotIn('string', notes[0])
            self.assertEqual(page.evaluate(rendered + '.whammyBarPoints.map(p=>[p.offset,p.value])'),
                             [[0, 0], [30, -4], [60, 0]])
            self.assertEqual(len(state.history), 3)  # The whole chord is one transaction.
            # Different per-note bar curves are retained, not merged into a
            # misleading single alphaTab beat-level curve.
            page.click('.vt-tab-grid [data-note="low"]')
            page.click('[data-action=tremolo-bar]')
            page.select_option('[data-ui=curve-preset]', label='Dive')
            page.click('[data-ui=curve-apply]')
            self.settled(page, "SCORE.view.score.patterns.verse.beats[1].notes[1].tremolo_bar.points[1].position===9")
            self.assertIsNone(page.evaluate(rendered + '.whammyBarPoints'))
            self.assertIn('individual curves', page.evaluate(rendered + '.text'))
            self.assertEqual(state.song['score']['patterns']['verse']['beats'][1]['written'], chord['written'])

            page.click('[data-action=tremolo-bar]')
            page.click('[data-action=remove-curve]')
            self.settled(page, "SCORE.view.score.patterns.verse.beats[1].notes[1].tremolo_bar==null")
            self.assertTrue(state.song['score']['patterns']['verse']['beats'][1]['notes'][0]['tremolo_bar'])
            for remaining in range(4, -1, -1):
                revision = page.evaluate('SCORE.view.revision')
                page.click('[data-action=undo]')
                self.settled(page, f"SCORE.view.revision!=={json.dumps(revision)}")
                self.assertEqual(len(state.history), remaining)
            self.assertEqual((folder / 'song.yaml').read_bytes(), before)

    def test_native_note_technique_controls_chord_engraving_and_undo(self):
        source = api.from_yaml(NATIVE_SONG)
        source['module']['channels'] = [{'name': 'High'}, {'name': 'Low'}]
        source['score']['tracks']['guitar'].update(tuning=[64, 59], channels=[0, 1])
        source['score']['patterns']['verse']['beats'][1]['notes'].append(
            dict(id='low', pitch=59, string=2, fret=0, volume=23))
        with self.page(api.to_yaml(source)) as (page, state, folder):
            page.evaluate("tab('tab');setEdit(true)")
            page.wait_for_selector('.vt-tab-grid [data-note="note-1"]')
            self.capture_engraving(page)
            before = (folder / 'song.yaml').read_bytes()
            original = json.loads(json.dumps(source['score']['patterns']['verse']['beats'][1]))
            page.click('.vt-tab-grid [data-note="note-1"]')
            page.click('[data-action=staccato]')
            self.settled(page, "SCORE.view.score.patterns.verse.beats[1].notes[0].staccato")
            self.assertEqual(page.get_attribute('[data-action=staccato]', 'aria-pressed'), 'true')
            self.assertFalse(state.song['score']['patterns']['verse']['beats'][1]['notes'][1].get('staccato'))
            engraving = 'tabRendered.tracks[0].staves[0].bars[0].voices[0].beats[1].notes'
            self.assertEqual(page.evaluate(engraving + '.map(n=>n.isStaccato)'), [True, False])

            page.click('.vt-tab-grid th [data-at="4/13"]')
            self.assertEqual(page.get_attribute('[data-action=staccato]', 'aria-pressed'), 'mixed')
            page.click('[data-action=palm-mute]')
            self.settled(page, "SCORE.view.score.patterns.verse.beats[1].notes.every(n=>n.palm_mute)")
            chord = state.song['score']['patterns']['verse']['beats'][1]
            self.assertTrue(all(not n.get('staccato') for n in chord['notes']))
            self.assertEqual(chord['written'], original['written'])
            self.assertEqual(chord['at'], original['at'])
            self.assertEqual(chord['notes'][1]['volume'], 23)
            self.assertNotIn('volume', chord['notes'][0])
            self.assertNotIn('string', chord['notes'][0])
            self.assertNotIn('fret', chord['notes'][0])
            self.assertEqual(page.evaluate(engraving + '.map(n=>[n.isPalmMute,n.isStaccato])'), [[True, False], [True, False]])
            self.assertEqual(len(state.history), 2)
            page.click('[data-action=undo]')
            self.settled(page, "SCORE.view.score.patterns.verse.beats[1].notes[0].staccato")
            self.assertFalse(state.song['score']['patterns']['verse']['beats'][1]['notes'][1].get('palm_mute'))
            page.click('[data-action=redo]')
            self.settled(page, "SCORE.view.score.patterns.verse.beats[1].notes.every(n=>n.palm_mute)")

            page.click('.vt-tab-grid [data-note="note-1"]')
            page.click('[data-action=dead]')
            self.settled(page, "SCORE.view.score.patterns.verse.beats[1].notes[0].dead")
            self.assertEqual(page.inner_text('.vt-tab-grid [data-note="note-1"]'), 'x')
            self.assertEqual(page.evaluate(engraving + '.map(n=>n.isDead)'), [True, False])
            chord = state.song['score']['patterns']['verse']['beats'][1]
            self.assertEqual(chord['notes'][0]['pitch'], original['notes'][0]['pitch'])
            self.assertNotIn('volume', chord['notes'][0])
            positions = [p for p in state.score_view()['positions'] if p['kind'] == 'note' and p['note'] == 'note-1']
            self.assertTrue(all(p['gate_effect'] == 'dead' and Fraction(*p['sounding_end']) < Fraction(*p['end']) for p in positions))
            page.click('[data-action=undo]')
            self.settled(page, "!SCORE.view.score.patterns.verse.beats[1].notes[0].dead")
            page.click('[data-action=undo]')
            self.settled(page, "SCORE.view.score.patterns.verse.beats[1].notes[0].staccato")
            page.click('[data-action=undo]')
            self.settled(page, "!SCORE.view.score.patterns.verse.beats[1].notes[0].staccato")
            self.assertEqual((folder / 'song.yaml').read_bytes(), before)

    def test_native_tab_cut_repeat_selection_rest_overflow_and_playback_guard(self):
        from tests.test_tablature import beat, note
        source = api.from_yaml(NATIVE_SONG)
        source['module']['channels'] = [{'name': 'High'}, {'name': 'Low'}]
        source['orders'] = ['verse']
        source['score']['order_ids'] = ['pass-1']
        source['score']['ties'] = []
        source['score']['tracks']['guitar'].update(tuning=[64, 59], channels=[0, 1])
        source['score']['patterns']['verse']['beats'] = [
            beat('chord', [0, 1], [note('high', 64, 1, 0), note('low', 59, 2, 0)]),
            beat('rest', [1, 1], []),
            beat('next', [2, 1], [note('next-n', 65, 1, 1)]),
            beat('other', [2, 1], [note('other-n', 59, 2, 0)], voice=1),
            beat('tail', [3, 1], [note('tail-n', 66, 1, 2)])]
        source['score']['measures'] = [dict(id='m', meter=[4, 4], **{
            'from': dict(occurrence='pass-1', at=[0, 1]), 'to': dict(occurrence='pass-1', at=[4, 1])})]
        with self.page(api.to_yaml(source)) as (page, state, folder):
            before = (folder / 'song.yaml').read_bytes()
            history = len(state.history)
            page.evaluate("tab('tab');setEdit(true)")
            page.wait_for_selector('.vt-tab-grid [data-note=high]')
            page.click('.vt-tab-grid [data-note=high]')
            page.click('[data-action=cut]')
            self.settled(page, "!SCORE.view.score.patterns.verse.beats.find(b=>b.id==='chord').notes.some(n=>n.id==='high')")
            self.assertEqual(state.song['score']['patterns']['verse']['beats'][0]['notes'][0]['id'], 'low')
            self.assertEqual(page.input_value('[data-ui=at]'), '0')
            self.assertEqual(len(state.history), history + 1)
            page.click('[data-action=cut]')
            page.wait_for_function("document.querySelector('.vt-tab-status').textContent.startsWith('Cut saved')")
            self.assertEqual(state.song['score']['patterns']['verse']['beats'][0]['notes'][0]['id'], 'low')
            self.assertEqual(len(state.history), history + 1)
            page.click('[data-action=undo]')
            self.settled(page, "SCORE.view.score.patterns.verse.beats.find(b=>b.id==='chord').notes.length===2")
            self.assertEqual((folder / 'song.yaml').read_bytes(), before)

            page.click('.vt-tab-grid [data-note=high]')
            page.click('[data-action=copy]')
            page.wait_for_function("document.querySelector('.vt-tab-status').textContent.startsWith('Copied')")
            page.click('.vt-tab-grid [data-note=next-n]')
            writes = []
            page.on('request', lambda r: writes.append(r.post_data_json)
                    if r.method == 'POST' and urlsplit(r.url).path == '/api/score' else None)
            with mock.patch.object(state, '_write_step', side_effect=OSError('test write refused')):
                page.evaluate("""() => {const root=document.getElementById('tab-editor');root.focus();
                    for(const key of ['x','v'])root.dispatchEvent(new KeyboardEvent('keydown',{key,ctrlKey:true,bubbles:true,cancelable:true}))}""")
                page.wait_for_function("document.querySelector('.vt-tab-status').textContent.startsWith('Cut refused')")
            self.assertEqual(writes, [])  # Failed Cut blocks the immediately dependent Paste.
            self.assertEqual((folder / 'song.yaml').read_bytes(), before)
            page.click('[data-action=paste-safe]')  # A later deliberate safe Paste still has the previous clipboard.
            page.wait_for_function("document.querySelector('.vt-tab-status').textContent.startsWith('Edit refused')")
            self.assertEqual([n['id'] for n in writes[-1]['clipboard']['beats'][0]['notes']], ['high', 'low'])
            self.assertEqual((folder / 'song.yaml').read_bytes(), before)

            # Ctrl-click two strings in one beat selects both notes, not a
            # toggle that accidentally deselects the entire chord.
            page.click('.vt-tab-grid [data-note=high]')
            page.click('.vt-tab-grid [data-note=low]', modifiers=['Control'])
            page.click('[data-action=cut]')
            self.settled(page, "SCORE.view.score.patterns.verse.beats.find(b=>b.id==='chord').notes.length===0")
            chord = next(b for b in state.song['score']['patterns']['verse']['beats'] if b['id'] == 'chord')
            self.assertEqual(chord['written']['value'], 4)
            page.click('[data-action=undo]')
            self.settled(page, "SCORE.view.score.patterns.verse.beats.find(b=>b.id==='chord').notes.length===2")

            page.click('.vt-tab-grid th [data-at="1/1"]')
            page.click('[data-action=cut]')
            self.settled(page, "!SCORE.view.score.patterns.verse.beats.some(b=>b.id==='rest')")
            positions = {b['id']: b['at'] for b in state.song['score']['patterns']['verse']['beats']}
            self.assertEqual(positions, {'chord': [0, 1], 'next': [1, 1], 'other': [2, 1], 'tail': [2, 1], 'rest_rest': [3, 1]})
            page.click('[data-action=undo]')
            self.settled(page, "SCORE.view.score.patterns.verse.beats.some(b=>b.id==='rest')")

            page.click('.vt-tab-grid th [data-at="0/1"]')
            page.focus('#tab-editor')
            page.keyboard.press('Control+r')
            self.settled(page, "SCORE.view.score.patterns.verse.beats.some(b=>b.id==='copy_chord')")
            copied = next(b for b in state.song['score']['patterns']['verse']['beats'] if b['id'] == 'copy_chord')
            self.assertEqual(copied['at'], [1, 1])
            self.assertEqual([n['id'] for n in copied['notes']], ['copy_high', 'copy_low'])
            self.assertEqual(page.input_value('[data-ui=at]'), '1')
            self.assertEqual(len(state.history), history + 1)
            page.click('[data-action=undo]')
            self.settled(page, "!SCORE.view.score.patterns.verse.beats.some(b=>b.id==='copy_chord')")
            self.assertEqual((folder / 'song.yaml').read_bytes(), before)

            page.click('.vt-tab-grid [data-note=tail-n]')
            page.click('[data-action=repeat]')
            self.settled(page, "SCORE.view.orders.length===2 && SCORE.view.order===1")
            self.assertEqual(page.input_value('[data-ui=at]'), '0')
            self.assertEqual(state.song['score']['patterns'][state.song['orders'][1]]['beats'][0]['notes'][0]['pitch'], 66)
            self.assertEqual(len(state.history), history + 1)
            page.click('[data-action=undo]')
            self.settled(page, "SCORE.view.orders.length===1")
            self.assertEqual((folder / 'song.yaml').read_bytes(), before)

            page.evaluate("setCursor(0,0,0,0);scoreRefresh()")
            self.settled(page, "SCORE.view.order===0")
            page.click('.vt-tab-grid [data-note=high]')
            page.click('[data-action=play]')
            page.wait_for_function('LV.playing')
            page.wait_for_function("document.querySelector('[data-action=cut]').disabled && document.querySelector('[data-action=repeat]').disabled")
            requests = []
            page.on('request', lambda r: requests.append(r.post_data_json)
                    if r.method == 'POST' and urlsplit(r.url).path == '/api/score_command' else None)
            page.evaluate("""() => {const root=document.getElementById('tab-editor');root.focus();
                for(const key of ['x','r'])root.dispatchEvent(new KeyboardEvent('keydown',{key,ctrlKey:true,bubbles:true,cancelable:true}))}""")
            page.evaluate('lvStop()')
            self.assertEqual(requests, [])
            self.assertEqual((folder / 'song.yaml').read_bytes(), before)

    def test_native_tab_failed_copy_blocks_dependent_paste_keeps_previous_clipboard(self):
        with self.page(api.to_yaml(self.clipboard_workflow_song())) as (page, state, folder):
            page.evaluate("tab('tab');setEdit(true)")
            page.wait_for_selector('.vt-tab-grid [data-note="An0"]')
            page.click('.vt-tab-grid [data-note="An0"]')
            page.click('[data-action=copy]')
            page.wait_for_function("document.querySelector('.vt-tab-status').textContent.startsWith('Copied')")
            page.evaluate("async()=>{setCursor(1,0,0,0);await scoreRefresh()}")
            self.settled(page, 'SCORE.view.order===1')
            page.click('.vt-tab-grid [data-note="Bn0"]')
            page.click('.vt-tab-grid [data-note="Bn1"]', modifiers=['Control'])
            before = (folder / 'song.yaml').read_bytes()
            mutations = []
            page.on('request', lambda r: mutations.append(r.post_data_json)
                    if r.method == 'POST' and urlsplit(r.url).path == '/api/score' else None)
            with mock.patch.object(state,'score_clipboard',side_effect=ValueError('test copy refused')):
                page.evaluate("""() => {
                    const root=document.getElementById('tab-editor');root.focus();
                    for(const key of ['c','v'])root.dispatchEvent(new KeyboardEvent('keydown',{key,ctrlKey:true,bubbles:true}));
                }""")
                page.wait_for_function("document.querySelector('.vt-tab-status').textContent.startsWith('Copy refused')")
            self.assertIn('test copy refused', page.inner_text('.vt-tab-status'))
            self.assertEqual(mutations, [])
            self.assertEqual((folder / 'song.yaml').read_bytes(), before)
            # A later deliberate paste can still use the previous successful copy.
            page.click('.vt-tab-grid [data-note="Bn2"]')
            page.click('[data-action=delete-beat]')
            self.settled(page, "!SCORE.view.score.patterns.B.beats.some(b=>b.id==='B2')")
            page.click('[data-action=paste-safe]')
            self.settled(page, 'SCORE.view.score.patterns.B.beats.length===4')
            copied = next(b for b in state.song['score']['patterns']['B']['beats'] if b['at'] == [2,1])
            self.assertEqual(copied['notes'][0]['pitch'],64)
            self.assertTrue(copied['notes'][0]['id'].startswith('copy_An0'))

    def test_native_tab_speed_130_uses_sounding_factor_and_rounded_boundary(self):
        with self.page(NATIVE_SONG) as (page, state, folder):
            before = (folder / 'song.yaml').read_bytes()
            page.evaluate("tab('tab');setSpeed(1.3)")
            page.wait_for_selector('.vt-tab-grid [data-note="note-1"]')
            page.wait_for_selector('.vt-tab-score svg')
            page.click('.vt-tab-grid [data-note="note-1"]')
            page.click('[data-action=play]')
            q = 50412  # Engine's half-up 16.16 inverse of 1.3.
            page.wait_for_function('q=>LV.playing && LV.pos?.factorQ===q && LV.pos.scoreFrame>0', arg=q)
            sample = page.evaluate("""() => {
                const p=playPos();SCORE.editor.setPlayhead(p);
                return {position:p,notes:[...document.querySelectorAll('.vt-tab-grid .playing')].map(e=>e.dataset.note)};
            }""")
            p = sample['position']
            self.assertEqual(p['factorQ'], q)
            rate, tempo = p['sampleRate'], 137
            origin = Fraction(4*p['o'])
            def exact(at):
                return (origin+at)*60*rate*q/(tempo*65536)
            def rounded(at):
                f = exact(at)
                return (2*f.numerator+f.denominator)//(2*f.denominator)
            active = next(i for i in range(13)
                          if rounded(Fraction(4*i, 13)) <= p['scoreFrame'] < rounded(Fraction(4*(i+1), 13)))
            self.assertEqual(sample['notes'], [f'note-{active}'])
            # Use the actual sounding clock at an onset rounded below musical time.
            i = next(i for i in range(1, 13) if 0 < exact(Fraction(4*i, 13)) % 1 < Fraction(1, 2))
            frame = rounded(Fraction(4*i, 13))
            local = Fraction(frame*tempo*65536, 60*rate*q)-origin
            self.assertLess(local, Fraction(4*i, 13))
            boundary = dict(o=p['o'], occurrence=p['occurrence'], scoreFrame=frame,
                            sampleRate=rate, factorQ=q, at=[local.numerator, local.denominator])
            page.evaluate("""p=>{
                lvStop();setSpeed(.5);window.tabPosition=p;
                playPos=()=>window.tabPosition;SCORE.editor.setPlayhead(p);
            }""", boundary)
            page.wait_for_selector(f'.vt-tab-grid [data-note="note-{i}"].playing')
            self.assertEqual(page.get_attribute('.vt-tab-playhead', 'data-at'), f'{4*i}/13')
            boundary['scoreFrame'] -= 1
            page.evaluate("p=>{window.tabPosition=p;SCORE.editor.setPlayhead(p)}", boundary)
            page.wait_for_selector(f'.vt-tab-grid [data-note="note-{i-1}"].playing')
            self.assertEqual((folder / 'song.yaml').read_bytes(), before)

    def test_native_pattern_mixed_copy_paste_and_fractional_cut_undo(self):
        text = NATIVE_TRANSFORM_SONG.replace('orders: [verse, verse, verse]',
            "  blank: {rows: 48, data: ''}\norders: [verse, verse, verse, blank]"
        ).replace('order_ids: [pass-1, pass-2, pass-3]', 'order_ids: [pass-1, pass-2, pass-3, destination]')
        with self.page(text) as (page, state, folder):
            self.assertFalse(state.error, state.error)
            before = (folder / 'song.yaml').read_bytes()
            source = json.loads(json.dumps(state.song['score']['patterns']['verse']))
            raw = state.pattern_rows(0, occurrence='pass-3')['rows']
            page.evaluate("tab('pattern');setCursor(2,3,0,0);showPattern(2)")
            page.wait_for_function("PAT.native && PAT.occurrence==='pass-3' && PAT.rows")
            page.evaluate("setEdit(true);setFocus('all');SEL={o:2,a:{row:3,ch:0,col:0},b:{row:7,ch:1,col:4}};renderPat()")
            page.click('[onclick="selCopy(false)"]')
            page.wait_for_function('!EDQ.n && CLIP?.native')
            clipboard = page.evaluate('CLIP.native')
            self.assertEqual({n['id'] for b in clipboard['score']['beats'] for n in b['notes']}, {'note-1', 'note-2'})
            self.assertTrue(clipboard['raw'])
            self.assertEqual((folder / 'song.yaml').read_bytes(), before)
            page.evaluate("SEL=null;setCursor(3,0,0,0);showPattern(3)")
            page.wait_for_function("PAT.native && PAT.occurrence==='destination' && PAT.rows")
            page.click('#sel-paste')
            page.wait_for_function("!EDQ.n && PAT.score_positions?.filter(p=>p.kind==='note').length===2")
            self.assertIsNone(page.evaluate('EDQ.err'))
            copied = state.song['score']['patterns']['blank']['beats']
            self.assertEqual([b['at'] for b in copied], [[3, 52], [19, 52]])
            self.assertTrue(all(n['id'] not in {'note-1', 'note-2'} for b in copied for n in b['notes']))
            self.assertEqual(state.song['score']['patterns']['verse'], source)
            self.assertEqual(state.pattern_rows(0, occurrence='pass-3')['rows'], raw)
            destination = state.pattern_rows(1, occurrence='destination')['rows']
            self.assertEqual(destination[0][0], '... .. v17 V40')
            self.assertEqual(destination[4][1], 'C-5 01 v23 X80')
            self.assertEqual(page.evaluate('CLIP.native'), clipboard)
            pasted = (folder / 'song.yaml').read_bytes()
            # Occupied and unsupported paste modes must refuse without changing anything.
            for selector, overflow in [('#sel-paste', False), ('#sel-mix', False),
                                       ('#sel-push', False), ('#sel-flood', False), ('#sel-paste', True)]:
                page.evaluate('EDQ.err=null')
                if overflow:
                    page.check('#sel-over')
                page.click(selector)
                page.wait_for_function('!EDQ.n && !!EDQ.err')
                if selector != '#sel-paste' or overflow:
                    self.assertIn('not supported', page.evaluate('EDQ.err'))
                self.assertEqual((folder / 'song.yaml').read_bytes(), pasted)
                self.assertEqual(page.evaluate('CLIP.native'), clipboard)
                if overflow:
                    page.uncheck('#sel-over')
            page.click('#lv-undo')
            page.wait_for_function("!EDQ.n && PAT.score_positions?.length===0")
            self.assertEqual((folder / 'song.yaml').read_bytes(), before)

            page.evaluate("setCursor(2,3,0,0);showPattern(2)")
            page.wait_for_function("PAT.occurrence==='pass-3' && PAT.score_positions?.length")
            page.click('#pat [data-score-id="pass-3/note-1"]')
            page.click('[onclick="selCopy(true)"]')
            page.wait_for_function("!EDQ.n && PAT.score_positions && !PAT.score_positions.some(p=>p.note==='note-1')")
            cut_clipboard = page.evaluate('CLIP.native')
            self.assertEqual(cut_clipboard['raw'], [])
            self.assertEqual(cut_clipboard['origin'], [48, 13])
            self.assertEqual(state.pattern_rows(0, occurrence='pass-3')['rows'], raw)
            page.evaluate("setCursor(3,[25,13],0,0,{row:[25,13]});showPattern(3)")
            page.wait_for_function("PAT.native && PAT.occurrence==='destination' && PAT.rows")
            with page.expect_response(lambda r: urlsplit(r.url).path == '/api/pattern_paste' and r.request.method == 'POST') as paste:
                page.click('#sel-paste')
            self.assertNotIn('error', paste.value.json(), paste.value.json())
            page.wait_for_function("revision=>!EDQ.n && PAT.score_positions && PAT.revision===revision", arg=state.text_sha())
            actual = page.evaluate("({order:PAT.order,occurrence:PAT.occurrence,positions:PAT.score_positions,cursor:CUR,error:EDQ.err})")
            self.assertEqual(len([p for p in actual['positions'] if p['kind'] == 'note']), 1, json.dumps(actual))
            self.assertEqual(state.song['score']['patterns']['blank']['beats'][0]['at'], [25, 156])
            self.assertEqual(page.evaluate('CLIP.native'), cut_clipboard)
            page.click('#lv-undo')
            page.wait_for_function("!EDQ.n && PAT.score_positions?.length===0")
            page.click('#lv-undo')
            page.wait_for_function('!EDQ.n && S.redo===2')
            self.assertEqual((folder / 'song.yaml').read_bytes(), before)
            # An external tie refuses cut and leaves the prior clipboard intact.
            page.evaluate("setCursor(1,0,0,0);showPattern(1)")
            page.wait_for_function("PAT.occurrence==='pass-2' && PAT.score_positions?.length")
            page.click('#pat [data-score-id="pass-2/note-0"]')
            page.evaluate('EDQ.err=null')
            page.click('[onclick="selCopy(true)"]')
            page.wait_for_function('!EDQ.n && !!EDQ.err')
            self.assertIn('tie', page.evaluate('EDQ.err'))
            self.assertEqual(page.evaluate('CLIP.native'), cut_clipboard)
            self.assertEqual((folder / 'song.yaml').read_bytes(), before)

    def test_native_pattern_immediate_copy_paste_uses_new_clipboard(self):
        self.immediate_native_clipboard(False)

    def test_native_pattern_immediate_cut_paste_uses_new_clipboard(self):
        self.immediate_native_clipboard(True)

    def test_native_pattern_failed_cut_blocks_dependent_paste_keeps_clipboard(self):
        self.immediate_native_clipboard(True, fail=True)

    def immediate_native_clipboard(self, cut, fail=False):
        with self.page(NATIVE_TRANSFORM_SONG) as (page, state, folder):
            before = (folder / 'song.yaml').read_bytes()
            raw = state.pattern_rows(0, occurrence='pass-1')['rows']
            page.evaluate("tab('pattern');showPattern(0)")
            page.wait_for_function('PAT.native && PAT.score_positions?.length')
            page.click('#pat [data-score-id="pass-1/note-2"]')
            page.click('[onclick="selCopy(false)"]')
            page.wait_for_function("!EDQ.n && CLIP?.native?.score?.beats[0].notes[0].id==='note-2'")
            page.wait_for_function('PAT.rows && PAT.revision')
            previous_clipboard = page.evaluate('CLIP.native')
            selected = 'note-12' if fail else 'note-1'
            page.click(f'#pat [data-score-id="pass-1/{selected}"]')
            pasted = []
            page.on('request', lambda r: pasted.append(r.post_data_json)
                    if r.method == 'POST' and urlsplit(r.url).path == '/api/pattern_paste' else None)
            # Both commands happen before the asynchronous copy response arrives.
            page.evaluate('cut => {selCopy(cut);selPaste(false);setCursor(0,33,0,0)}', cut)
            page.wait_for_function('!EDQ.n')
            if fail:
                self.assertEqual(pasted, [])
                self.assertIn('earlier edit failed', page.evaluate('EDQ.err').lower())
                self.assertEqual(page.evaluate('CLIP.native'), previous_clipboard)
                self.assertEqual((folder / 'song.yaml').read_bytes(), before)
                return
            self.assertEqual(len(pasted), 1)
            self.assertEqual(pasted[0]['clipboard']['score']['beats'][0]['notes'][0]['id'], 'note-1')
            self.assertEqual(pasted[0]['row'], [48, 13])
            self.assertEqual(pasted[0]['occurrence'], 'pass-1')
            if cut:
                self.assertIsNone(page.evaluate('EDQ.err'))
                copied = state.song['score']['patterns']['verse']['beats'][1]['notes']
                self.assertEqual(len(copied), 1)
                self.assertNotEqual(copied[0]['id'], 'note-1')
                self.assertEqual(copied[0]['pitch'], 64)
                self.assertEqual(state.pattern_rows(0, occurrence='pass-1')['rows'], raw)
                page.click('#lv-undo')
                page.wait_for_function("!EDQ.n && PAT.score_positions && !PAT.score_positions.some(p=>p.kind==='note' && p.beat==='beat-1')")
                page.click('#lv-undo')
                page.wait_for_function("!EDQ.n && PAT.score_positions?.some(p=>p.note==='note-1')")
                self.assertEqual((folder / 'song.yaml').read_bytes(), before)
            else:
                self.assertIn('occupied', page.evaluate('EDQ.err'))
                self.assertEqual((folder / 'song.yaml').read_bytes(), before)

    def test_native_phrase_capture_raw_alternative_audition_accept_and_undo(self):
        self.native_phrase_page(1)

    def test_native_untied_phrase_capture_raw_alternative_audition_accept_and_undo(self):
        self.native_phrase_page(2)

    def native_phrase_page(self, order):
        with self.page(NATIVE_TRANSFORM_SONG) as (page, state, folder):
            self.assertFalse(state.error, state.error)
            before = (folder / 'song.yaml').read_bytes()
            score = json.loads(json.dumps(state.song['score']['patterns']['verse']))
            occurrence = f'pass-{order+1}'
            page.evaluate("o=>{tab('pattern');setCursor(o,1,0,0);showPattern(o)}", order)
            page.wait_for_function("o=>PAT.native && PAT.occurrence===o && PAT.rows", arg=occurrence)
            page.evaluate("o=>{setFocus('all');SEL={o,a:{row:1,ch:0,col:0},b:{row:5,ch:1,col:4}};renderPat()}", order)
            page.click('[data-t="phrases"]')
            with page.expect_response(lambda r: urlsplit(r.url).path == '/api/phrase' and r.request.method == 'POST') as capture:
                page.get_by_role('button', name='NEW COMPARISON FROM PATTERN SELECTION').click()
            self.assertNotIn('error', capture.value.json(), capture.value.json())
            page.wait_for_function('S.phrase?.variants?.length===3')
            positions = page.evaluate('S.phrase.score_positions')
            self.assertEqual([(p['note'], p['row'], p['occurrence']) for p in positions],
                             [('note-1', [48, 13], occurrence)])
            rows = page.input_value('#phrase-data').splitlines()
            self.assertEqual(len(rows), 5)
            cells = rows[1].split('|')
            cells[1] = ' C-5 01 v32 D07'
            rows[1] = '|'.join(cells)
            page.fill('#phrase-name', 'Native neighbor')
            page.fill('#phrase-data', '\n'.join(rows))
            page.get_by_role('button', name='SAVE ALTERNATIVE / RATING / NOTE').click()
            page.wait_for_function("S.phrase.variants[0].name==='Native neighbor'")
            self.assertEqual(page.evaluate('S.phrase.score_positions'), positions)
            self.assertEqual((folder / 'song.yaml').read_bytes(), before)
            page.get_by_role('button', name='▶ Native neighbor', exact=True).click()
            page.wait_for_function("!$('phrase-audio').paused && $('phrase-audio').currentTime>.02")
            response = page.request.get(page.eval_on_selector('#phrase-audio', 'a=>a.src'))
            self.assertEqual(response.status, 200)
            def frame(at):
                exact = at * 60 * 44100 / 137
                return (2 * exact.numerator + exact.denominator) // (2 * exact.denominator)
            with wave.open(io.BytesIO(response.body()), 'rb') as rendered:
                self.assertEqual(rendered.getframerate(), 44100)
                self.assertEqual(rendered.getnframes(), frame(4*order + Fraction(1, 2)) - frame(4*order + Fraction(1, 12)))
                self.assertTrue(any(rendered.readframes(rendered.getnframes())))
            self.assertEqual(page.evaluate('S.phrase.score_positions'), positions)
            self.assertEqual((folder / 'song.yaml').read_bytes(), before)
            page.evaluate("$('phrase-audio').pause()")
            page.get_by_role('button', name='YAML DIFF / ACCEPT').click()
            page.wait_for_selector('#workflowmodal.on')
            self.assertIn('C-5 01 v32 D07', page.inner_text('#workflow-diff'))
            self.assertEqual((folder / 'song.yaml').read_bytes(), before)
            page.click('#workflow-confirm')
            page.wait_for_function('S.phrase.accepted===0')
            name = state.song['orders'][order]
            self.assertNotEqual(name, 'verse')
            self.assertEqual([name for i, name in enumerate(state.song['orders']) if i != order], ['verse', 'verse'])
            self.assertEqual(state.song['score']['patterns']['verse'], score)
            self.assertEqual(state.song['score']['patterns'][name], score)
            self.assertIn('C-5 01 v32 D07', state.song['patterns'][name]['data'])
            self.assertEqual(page.evaluate('S.phrase.score_positions'), positions)
            page.click('[data-t="project"]')
            page.get_by_role('button', name='UNDO', exact=True).click()
            page.wait_for_function('S.redo===1')
            self.assertEqual((folder / 'song.yaml').read_bytes(), before)

    def test_native_pattern_cursor_transpose_amplify_and_undo(self):
        with self.page(NATIVE_TRANSFORM_SONG) as (page, state, folder):
            self.assertFalse(state.error, state.error)
            before = (folder / 'song.yaml').read_bytes()
            raw = state.pattern_rows(0, occurrence='pass-3')['rows']
            requests = []
            page.on('request', lambda r: requests.append(r.post_data_json)
                    if r.method == 'POST' and urlsplit(r.url).path == '/api/transform' else None)
            page.evaluate("tab('pattern');setCursor(2,0,0,0);showPattern(2)")
            page.wait_for_function("PAT.native && PAT.occurrence==='pass-3' && PAT.score_positions?.length")
            page.click('#pat [data-score-id="pass-3/note-1"]')
            revision = state.text_sha()
            page.click('[onclick="selTranspose(1)"]')
            page.wait_for_function("!EDQ.n && PAT.score_positions?.some(p=>p.note==='note-1' && p.pitch===65)")
            self.assertIsNone(page.evaluate('EDQ.err'))
            note = state.song['score']['patterns']['verse']['beats'][1]['notes'][0]
            self.assertEqual((note['pitch'], note['fret']), (65, 1))
            self.assertEqual(state.pattern_rows(0, occurrence='pass-3')['rows'], raw)
            self.assertEqual(requests[0]['revision'], revision)
            self.assertEqual(requests[0]['selections'][0]['notes'], ['note-1'])
            self.assertEqual(requests[0]['selections'][0]['occurrence'], 'pass-3')
            page.fill('#sel-amp', '50')
            page.click('[onclick="selAmplify()"]')
            page.wait_for_function("!EDQ.n && PAT.score_positions?.some(p=>p.note==='note-1' && p.volume===32)")
            self.assertEqual(state.pattern_rows(0, occurrence='pass-3')['rows'], raw)
            self.assertEqual(requests[1]['selections'][0]['notes'], ['note-1'])
            page.evaluate("tab('tab')")
            self.settled(page, "SCORE.view.order===2 && SCORE.view.score.patterns.verse.beats[1].notes[0].volume===32")
            self.assertEqual(page.input_value('[data-ui=at]'), '4/13')
            self.assertEqual(page.input_value('[data-ui=fret]'), '1')
            page.evaluate("tab('pattern')")
            page.click('#lv-undo')
            page.wait_for_function("!EDQ.n && PAT.score_positions?.some(p=>p.note==='note-1' && p.volume==null)")
            self.assertEqual(state.song['score']['patterns']['verse']['beats'][1]['notes'][0]['pitch'], 65)
            page.click('#lv-undo')
            page.wait_for_function("!EDQ.n && PAT.score_positions?.some(p=>p.note==='note-1' && p.pitch===64)")
            self.assertEqual((folder / 'song.yaml').read_bytes(), before)

    def test_native_pattern_range_transforms_fractional_notes_preserve_other_fields(self):
        with self.page(NATIVE_TRANSFORM_SONG) as (page, state, folder):
            self.assertFalse(state.error, state.error)
            original = json.loads(json.dumps(state.song['score']['patterns']['verse']['beats']))
            raw = state.pattern_rows(0, occurrence='pass-1')['rows']
            page.evaluate("tab('pattern');showPattern(0)")
            page.wait_for_function('PAT.native && PAT.rows && PAT.score_positions?.length')
            page.evaluate("setEdit(true);setFocus('all');SEL={o:0,a:{row:3,ch:0,col:0},b:{row:7,ch:0,col:0}};renderPat()")
            page.click('[onclick="selTranspose(1)"]')
            page.wait_for_function("!EDQ.n && PAT.score_positions?.filter(p=>p.pitch===65).length===2")
            beats = state.song['score']['patterns']['verse']['beats']
            self.assertEqual([b['notes'][0]['pitch'] for b in beats], [64, 65, 65] + [64]*10)
            self.assertEqual([b for i, b in enumerate(beats) if i not in (1, 2)],
                             [b for i, b in enumerate(original) if i not in (1, 2)])
            self.assertEqual(state.pattern_rows(0, occurrence='pass-1')['rows'], raw)
            transposed = json.loads(json.dumps(beats))
            page.click('[onclick="selClear()"]')
            page.wait_for_function("!EDQ.n && PAT.score_positions && !PAT.score_positions.some(p=>['note-1','note-2'].includes(p.note))")
            self.assertEqual(state.song['score']['patterns']['verse']['beats'][1]['notes'], [])
            self.assertEqual(state.song['score']['patterns']['verse']['beats'][2]['notes'], [])
            self.assertEqual(state.pattern_rows(0, occurrence='pass-1')['rows'], raw)
            page.click('#lv-undo')
            page.wait_for_function("!EDQ.n && PAT.score_positions?.filter(p=>p.pitch===65).length===2")
            self.assertEqual(state.song['score']['patterns']['verse']['beats'], transposed)
            page.fill('#sel-hum', '6')
            page.click('[onclick="selHumanize()"]')
            page.wait_for_function("!EDQ.n && PAT.score_positions?.filter(p=>p.volume!=null).length===2")
            beats = state.song['score']['patterns']['verse']['beats']
            for i in (1, 2):
                self.assertGreaterEqual(beats[i]['notes'][0]['volume'], 58)
                self.assertLessEqual(beats[i]['notes'][0]['volume'], 64)
            self.assertEqual([b for i, b in enumerate(beats) if i not in (1, 2)],
                             [b for i, b in enumerate(original) if i not in (1, 2)])
            self.assertEqual(state.pattern_rows(0, occurrence='pass-1')['rows'], raw)
            page.click('#lv-undo')
            page.wait_for_function("!EDQ.n && PAT.score_positions && !PAT.score_positions.some(p=>p.volume!=null)")
            self.assertEqual(state.song['score']['patterns']['verse']['beats'], transposed)

    def test_native_roll_ghost_occurrences_fractional_geometry_and_read_only_source(self):
        text = NATIVE_SONG.replace(
            "  verse: {rows: 48, data: ''}", "  verse: {rows: 48, data: ''}\n  blank: {rows: 48, data: ''}"
        ).replace('orders: [verse, verse, verse]', 'orders: [verse, blank, verse, verse]'
        ).replace('order_ids: [pass-1, pass-2, pass-3]', 'order_ids: [pass-1, gap, pass-2, pass-3]'
        ).replace('occurrence: pass-1, note: note-12', 'occurrence: pass-2, note: note-12'
        ).replace('occurrence: pass-2, note: note-0', 'occurrence: pass-3, note: note-0')
        with self.page(text) as (page, state, folder):
            self.assertFalse(state.error, state.error)
            source = json.loads(json.dumps(state.song['score']['patterns']['verse']))
            page.evaluate("tab('pattern');setCursor(1,0,0,0);showPattern(1)")
            page.wait_for_function("PAT.order===1 && PAT.rows")
            page.evaluate('rollToggle()')
            page.select_option('#roll-from', 'prev')
            page.wait_for_function("ROLL.from?.positions?.some(p=>p.occurrence==='pass-1') && document.querySelectorAll('#roll .rnote.from').length===13")
            self.assertEqual(page.evaluate("[...new Set(ROLL.from.positions.map(p=>p.occurrence))]"), ['pass-1'])
            geometry = page.evaluate("""() => {
                const el=document.querySelectorAll('#roll .rnote.from')[1];
                return {left:parseFloat(el.style.left),width:parseFloat(el.style.width),rw:ROLL.RW,
                    pointer:getComputedStyle(el).pointerEvents,row:el.dataset.row,id:el.dataset.scoreId};
            }""")
            self.assertAlmostEqual(geometry['left'], 41 + 48/13*geometry['rw'], places=3)
            self.assertAlmostEqual(geometry['width'], 48/13*geometry['rw']-2, places=3)
            self.assertEqual(geometry['pointer'], 'none')
            self.assertIsNone(geometry['row'])
            self.assertIsNone(geometry['id'])
            page.select_option('#roll-from', 'next')
            page.wait_for_function("ROLL.from?.positions?.some(p=>p.occurrence==='pass-2')")
            self.assertEqual(page.evaluate("[...new Set(ROLL.from.positions.map(p=>p.occurrence))]"), ['pass-2'])
            self.assertEqual(page.locator('#roll .rnote.from').count(), 13)
            # A click through the ghost edits the blank destination, never the source.
            page.evaluate("setEdit(true);$('rollscroll').scrollTop=(ROLL.hi-64)*ROLL.PH-30")
            page.evaluate('() => new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)))')
            point = page.evaluate("""() => {
                const el=document.querySelectorAll('#roll .rnote.from')[1],r=el.getBoundingClientRect();
                const x=r.x+r.width/2,y=r.y+r.height/2,target=document.elementFromPoint(x,y);
                return {x,y,ghost:target?.classList.contains('from'),inside:document.getElementById('roll').contains(target)};
            }""")
            self.assertFalse(point['ghost'])
            self.assertTrue(point['inside'])
            page.mouse.click(point['x'], point['y'])
            self.settled(page, "PAT.raw_rows?.some(r=>!r[0].startsWith('...'))")
            self.assertEqual(state.song['score']['patterns']['verse'], source)
            page.evaluate("setCursor(2,0,0,0);showPattern(2)")
            page.wait_for_function("PAT.order===2 && ROLL.from?.positions?.some(p=>p.occurrence==='pass-3')")
            self.assertEqual(page.evaluate("[...new Set(ROLL.from.positions.map(p=>p.occurrence))]"), ['pass-3'])
            self.assertTrue(page.evaluate("ROLL.from.positions.find(p=>p.note==='note-0').tied_in"))
            self.assertEqual(page.locator('#roll .rnote.from').count(), 13)

    def test_native_section_wav_export_from_page(self):
        with self.page(NATIVE_SONG + 'sections:\n  First: [0, 1]\n') as (page, state, folder):
            self.assertFalse(state.error, state.error)
            before = (folder / 'song.yaml').read_bytes()
            destination = folder / 'section-export'
            page.click('[data-t="export"]')
            self.assertEqual(page.input_value('#export-format'), 'wav')
            page.fill('#export-dest', str(destination))
            page.fill('#export-name', 'first-section')
            page.select_option('#export-region', 'First')
            page.select_option('#export-tail-mode', 'cut')
            page.check('#export-stems')
            page.click('#export-go')
            page.wait_for_function("['done','error','cancelled'].includes(S.export?.status)", timeout=20000)
            result = page.evaluate('S.export')
            self.assertEqual(result['status'], 'done', result)
            files = [Path(p) for p in result['files']]
            self.assertEqual(len(files), 2)  # Song plus the guitar channel's aligned stem.
            self.assertEqual(set(files), set(destination.rglob('*.wav')))
            self.assertEqual(result['done'], result['total'])
            exact_frames = Fraction(4 * 60 * 44100, 137)
            expected_frames = (2 * exact_frames.numerator + exact_frames.denominator) // (2 * exact_frames.denominator)
            for path in files:
                with wave.open(str(path), 'rb') as output:
                    self.assertEqual(output.getframerate(), 44100)
                    self.assertEqual(output.getnchannels(), 2)
                    self.assertEqual(output.getsampwidth(), 2)
                    self.assertEqual(output.getnframes(), expected_frames)
                    self.assertTrue(any(output.readframes(expected_frames)))
            self.assertIn('done', page.inner_text('#export-result'))
            self.assertEqual((folder / 'song.yaml').read_bytes(), before)

    def test_native_raw_preview_occurrence_boundaries_adoption_and_undo(self):
        with self.page(NATIVE_RAW_SONG) as (page, state, folder):
            self.assertFalse(state.error, state.error)
            before = (folder / 'song.yaml').read_bytes()
            authored = json.loads(json.dumps(state.song['score']['patterns']['verse']['beats']))
            requests = []
            page.on('request', lambda r: requests.append(r.post_data_json)
                    if r.method == 'POST' and urlsplit(r.url).path == '/api/score' else None)
            page.evaluate("tab('tab')")
            page.wait_for_selector('.vt-tab-raw [data-raw-row="0"]')
            self.assertEqual(page.locator('.vt-tab-raw [data-raw-row]').count(), 5)
            self.assertEqual(page.locator('.vt-tab-raw [data-occurrence="pass-1"]').count(), 5)
            page.click('.vt-tab-raw [data-raw-row="0"][data-raw-ch="0"]')
            self.assertIn('Row 0 → 48/13', page.inner_text('.vt-tab-raw'))
            self.assertIn('explicit raw note-off', page.inner_text('[data-ui=cursor]'))
            self.assertTrue(page.is_disabled('[data-action=adopt]'))
            for row, reason in [(8, 'explicit raw note-off'), (12, 'cut/fade'), (20, 'unknown duration')]:
                page.click(f'.vt-tab-raw [data-raw-row="{row}"][data-raw-ch="1"]')
                self.assertIn(reason, page.inner_text('[data-ui=cursor]'))
                self.assertTrue(page.is_disabled('[data-action=adopt]'))
            self.assertEqual((folder / 'song.yaml').read_bytes(), before)
            page.evaluate("async () => {setCursor(2,0,1,0);await scoreRefresh()}")
            self.settled(page, 'SCORE.view.order===2')
            self.assertEqual(page.locator('.vt-tab-raw [data-raw-row]').count(), 5)
            self.assertEqual(page.locator('.vt-tab-raw [data-occurrence="pass-3"]').count(), 5)
            page.click('.vt-tab-raw [data-raw-row="0"][data-raw-ch="1"]')
            self.assertEqual(page.evaluate('CUR.score.occurrence'), 'pass-3')
            self.assertFalse(page.is_disabled('[data-action=adopt]'))
            page.click('[data-action=adopt]')
            self.settled(page, "SCORE.view.score.patterns.verse.beats.length===2")
            self.assertEqual(page.locator('.vt-tab-raw [data-raw-row]').count(), 4)
            self.assertEqual(state.song['score']['patterns']['verse']['beats'][:1], authored)
            adopted = state.song['score']['patterns']['verse']['beats'][1]
            self.assertEqual(adopted['at'], [0, 1])
            self.assertEqual(adopted['notes'][0]['channel'], 1)
            self.assertEqual(state.pattern_rows(0, occurrence='pass-3')['rows'][0][1], '... .. ... V40')
            self.assertEqual(state.pattern_rows(0, occurrence='pass-3')['rows'][4][1], '... .. ... ...')
            self.assertEqual([r['occurrence'] for r in requests if r.get('op') == 'promote_pattern'], ['pass-3'])
            page.locator('#tab-editor').focus()
            page.keyboard.press('Control+z')
            self.settled(page, 'SCORE.view.score.patterns.verse.beats.length===1')
            self.assertEqual(page.locator('.vt-tab-raw [data-occurrence="pass-3"]').count(), 5)
            self.assertEqual((folder / 'song.yaml').read_bytes(), before)

    def test_roll_selection_refreshes_stale_tab_occurrence(self):
        self.roll_selection_refreshes_stale_tab_occurrence(False)

    def test_roll_selection_after_playback_refreshes_stale_tab_occurrence(self):
        self.roll_selection_refreshes_stale_tab_occurrence(True)

    def test_narrow_roll_selection_after_playback_refreshes_stale_tab_occurrence(self):
        self.roll_selection_refreshes_stale_tab_occurrence(True, width=432, height=540)

    def roll_selection_refreshes_stale_tab_occurrence(self, playback, width=1400, height=900):
        with self.page(NATIVE_SONG, width=width, height=height) as (page, state, folder):
            self.assertFalse(state.error, state.error)
            page.evaluate("tab('tab')")
            page.wait_for_selector('.vt-tab-grid [data-note="note-1"]')
            page.click('.vt-tab-grid [data-note="note-1"]')
            page.fill('[data-ui=fret]', '2')
            page.click('[data-action=fret]')
            self.settled(page, "SCORE.view.score.patterns.verse.beats[1].notes[0].pitch===66")
            # TAB stays on order zero while Pattern follows a later occurrence.
            if playback:
                page.click('[data-action=play]')
                page.evaluate("tab('pattern')")
                page.wait_for_function('LV.playing && LV.oi===2 && LV.pos.row>=30')
                page.evaluate('lvStop()')
            else:
                page.evaluate("tab('pattern');showPattern(2)")
            page.wait_for_function("PAT.order===2 && PAT.score_positions?.some(p=>p.id==='pass-3/note-1')")
            if not playback:
                page.evaluate('setCursor(2,39,0,0)')
            page.evaluate("rollToggle();setEdit(true)")
            self.assertEqual(page.evaluate('SCORE.view.order'), 0)
            # Scrolling redraws ROLL; roll_scroll queries the current element, not an old handle.
            roll_scroll(page, '#roll [data-score-id="pass-3/note-1"]')
            note = page.locator('#roll [data-score-id="pass-3/note-1"]')
            hit = page.evaluate("""() => {
                const el=document.querySelector('#roll [data-score-id="pass-3/note-1"]');
                const rect = e => {const r=e.getBoundingClientRect();return {x:r.x,y:r.y,width:r.width,height:r.height}};
                const r=el.getBoundingClientRect(), x=r.x+r.width/2, y=r.y+r.height/2;
                const target=document.elementFromPoint(x,y), scroll=document.getElementById('rollscroll');
                return {note:rect(el),target:target?.outerHTML.slice(0,300),hits:target===el||el.contains(target),
                    scroll:{...rect(scroll),clientHeight:scroll.clientHeight,scrollHeight:scroll.scrollHeight,scrollTop:scroll.scrollTop},
                    velocity:rect(document.getElementById('rollvel'))};
            }""")
            self.assertTrue(hit['hits'], json.dumps(hit))
            note.click()
            selected = page.evaluate('CUR.score')
            self.assertIsNotNone(selected)
            self.assertEqual(selected['id'], 'pass-3/note-1')
            self.assertEqual(selected['row'], [48, 13])
            self.assertEqual(selected['at'], [4, 13])
            page.evaluate("tab('tab')")
            self.settled(page, 'SCORE.view.order===2')
            self.assertEqual(page.evaluate('CUR.score'), selected)
            self.assertEqual(page.input_value('[data-ui=at]'), '4/13')
            self.assertEqual(page.input_value('[data-ui=fret]'), '2')
            self.assertEqual(page.get_attribute('.vt-tab-grid [data-note="note-1"]', 'aria-pressed'), 'true')

    def test_native_clipboard_pastes_at_fractional_row(self):
        from tests.test_tablature import beat,note
        source=api.from_yaml(NATIVE_SONG);source['score']['ties']=[]
        source['score']['patterns']['verse']['beats']=[beat('beat-0',[0,1],[note('note-0',64,1,0)],32)]
        with self.page(api.to_yaml(source)) as (page, state, folder):
            self.assertFalse(state.error, state.error)
            page.evaluate("tab('tab');setEdit(true)")
            page.wait_for_selector('.vt-tab-grid [data-note="note-0"]')
            page.click('.vt-tab-grid [data-note="note-0"]')
            page.click('[data-action=copy]')
            page.wait_for_function("document.querySelector('.vt-tab-status').textContent.startsWith('Copied')")
            before=(folder/'song.yaml').read_bytes()
            page.evaluate("SCORE.editor.setSelection({order:0,occurrence:'pass-1',track:'guitar',at:[1,8],row:[3,2]})")
            page.click('[data-action=paste-safe]')
            self.settled(page, "SCORE.view.score.patterns.verse.beats.length===2")
            copied = next(b for b in state.song['score']['patterns']['verse']['beats'] if b['at'] == [1,8])
            self.assertNotEqual(copied['id'],'beat-0')
            self.assertNotEqual(copied['notes'][0]['id'],'note-0')
            self.assertEqual(copied['written']['value'],32)
            self.assertEqual(copied['notes'][0]['pitch'], 64)
            self.assertEqual([p['row'] for p in state.score_view()['positions']
                              if p['kind'] == 'note' and p['note'] == copied['notes'][0]['id']], [[3,2]] * 3)
            api.compile_song(folder/'song.yaml')
            page.evaluate('patUndo(false)');self.settled(page,'S.undo===0');self.assertEqual((folder/'song.yaml').read_bytes(),before)

    def test_cross_measure_rendered_selection_copy_paste_history_and_views(self):
        from vulturetracker.itreader import read_it
        source = self.four_bar_song()
        names = source['orders']
        for name in names[2:]:
            source['score']['patterns'][name]['beats'] = []
        with self.muted_page(api.to_yaml(source), width=1920, height=1080) as (page, state, folder):
            self.assertFalse(state.error, state.error)
            before = (folder / 'song.yaml').read_bytes()
            errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.evaluate("tab('tab');setEdit(true)")
            page.wait_for_selector('[data-ui=track]', state='attached')
            self.capture_engraving(page)
            page.select_option('[data-ui=track]', 'guitar')
            page.wait_for_function("window.tabRendered && tabRenderApi.boundsLookup?.isFinished")
            # Drag and Extend Right cross the same order boundary as Shift-click.
            start = self.tab_lane_point(page, 0, 3, 1)
            end = self.tab_lane_point(page, 1, 0, 1)
            page.mouse.move(start['x'], start['y']); page.mouse.down()
            page.mouse.move(end['x'], end['y'], steps=4); page.mouse.up()
            page.click('[data-action=copy]')
            page.wait_for_function("document.querySelector('.vt-tab-status').textContent.startsWith('Copied 2')")
            page.select_option('[data-ui=track]', 'guitar')
            self.assertEqual(page.locator('.vt-tab-selection').count(), 0)
            self.click_tab_lane(page, 0, 3, 1)
            page.click('[data-action=select-right]')
            self.settled(page, 'SCORE.view.order===1')
            page.click('[data-action=copy]')
            page.wait_for_function("document.querySelector('.vt-tab-status').textContent.startsWith('Copied 2')")
            self.click_tab_lane(page, 0, 3, 1)
            self.settled(page, 'SCORE.view.order===0')
            point = self.tab_lane_point(page, 1, 0, 1)
            page.keyboard.down('Shift'); page.mouse.click(point['x'], point['y']); page.keyboard.up('Shift')
            self.settled(page, 'SCORE.view.order===1')
            self.settled(page, "document.querySelectorAll('.vt-tab-selection').length>=2")
            page.click('[data-action=copy]')
            page.wait_for_function("document.querySelector('.vt-tab-status').textContent.startsWith('Copied 2')")
            with page.expect_response('**/api/score_command') as response:
                page.click('[data-action=delete-beat]')
            self.assertTrue(response.value.json().get('ok'), response.value.json())
            self.settled(page, 'S.undo===1')
            page.click('[data-action=undo]')
            self.settled(page, 'S.undo===0')
            self.assertEqual((folder / 'song.yaml').read_bytes(), before)
            # Use the rendered blank destination bar, then its exact quarter position.
            self.click_tab_lane(page, 2, 0, 1)
            self.settled(page, 'SCORE.view.order===2')
            page.fill('[data-ui=at]', '3'); page.click('[data-action=go]')
            page.click('[data-action=select-none]')
            page.click('[data-action=paste-span]')
            self.settled(page, f"SCORE.view.score.patterns[{json.dumps(names[3])}].beats.length===1")
            saved = (folder / 'song.yaml').read_bytes()
            copied = [state.song['score']['patterns'][name]['beats'][0] for name in names[2:]]
            self.assertEqual([b['at'] for b in copied], [[3, 1], [0, 1]])
            module, _ = read_it(api.compile_song(folder / 'song.yaml')[0])
            for pi, row, b in zip((2, 3), (36, 0), copied):
                n = b['notes'][0]
                self.assertEqual(module.patterns[pi].rows[row][n['string'] - 1].note, n['pitch'])
            page.evaluate("tab('pattern');showPattern(3)")
            page.wait_for_function("PAT.order===3 && PAT.score_positions?.some(p=>p.kind==='note')")
            page.evaluate('rollToggle()')
            page.wait_for_selector('#roll [data-score-id]')
            self.assertEqual(page.locator('#roll [data-score-id]').count(), 1)
            page.click('#lv-undo')
            page.wait_for_function('!EDQ.n')
            self.assertEqual((folder / 'song.yaml').read_bytes(), before)
            page.evaluate("tab('tab')")
            self.settled(page, 'SCORE.view.order===2')
            # A range ending in an empty bar still edits its selected authored
            # source group, leaving the empty destination untouched.
            self.click_tab_lane(page, 1, 3, 1)
            point = self.tab_lane_point(page, 2, 0, 1)
            page.keyboard.down('Shift'); page.mouse.click(point['x'], point['y']); page.keyboard.up('Shift')
            self.settled(page, 'SCORE.view.order===2')
            page.click('[data-action=copy]')
            page.wait_for_function("document.querySelector('.vt-tab-status').textContent.startsWith('Copied 1')")
            page.click('[data-action=rest]')
            self.settled(page, "SCORE.view.score.patterns.F.beats.find(b=>b.id==='beat3').notes.length===0")
            self.assertEqual(state.song['score']['patterns']['G']['beats'], [])
            page.click('[data-action=undo]')
            self.settled(page, "SCORE.view.score.patterns.F.beats.find(b=>b.id==='beat3').notes.length===1")
            self.assertEqual((folder / 'song.yaml').read_bytes(), before)
            self.assertFalse(errors, errors)

    def test_replacement_paste_controls_preserve_safe_paste_and_history(self):
        import copy
        from vulturetracker.itreader import read_it
        source = self.four_bar_song()
        with self.muted_page(api.to_yaml(source), width=1920, height=1080) as (page, state, folder):
            self.assertFalse(state.error, state.error)
            before = (folder / 'song.yaml').read_bytes()
            errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.evaluate("tab('tab');setEdit(true)")
            page.wait_for_selector('[data-ui=track]', state='attached')
            self.capture_engraving(page)
            page.select_option('[data-ui=track]', 'guitar')
            page.wait_for_function('window.tabRendered && tabRenderApi.boundsLookup?.isFinished')
            self.assertTrue(page.is_disabled('[data-action=paste-replace]'))
            self.click_tab_lane(page, 0, 0, 2)
            end = self.tab_lane_point(page, 1, 3, 3)
            page.keyboard.down('Shift'); page.mouse.click(end['x'], end['y']); page.keyboard.up('Shift')
            self.settled(page, 'SCORE.view.order===1')
            page.click('[data-action=copy]')
            page.wait_for_function("document.querySelector('.vt-tab-status').textContent.startsWith('Copied 8')")
            self.assertFalse(page.is_disabled('[data-action=paste-replace]'))
            self.click_tab_lane(page, 2, 0, 1)
            self.settled(page, 'SCORE.view.order===2')
            page.click('[data-action=paste-safe]')
            page.wait_for_function("document.querySelector('.vt-tab-status').textContent.includes('empty destination span')")
            self.assertEqual((folder / 'song.yaml').read_bytes(), before)
            page.click('[data-action=paste-replace]')
            self.settled(page, "SCORE.view.score.patterns.G.beats.every(b=>b.id.startsWith('copy_'))")
            first = copy.deepcopy(state.song)
            compiled = read_it(api.compile_song(folder / 'song.yaml')[0])[0]
            for src, dst in (('C', 'G'), ('F', 'C2')):
                for left, right in zip(first['score']['patterns'][src]['beats'], first['score']['patterns'][dst]['beats']):
                    self.assertEqual(left['at'], right['at'])
                    self.assertEqual([n['pitch'] for n in left['notes']], [n['pitch'] for n in right['notes']])
            self.assertEqual(len([e for e in state.mod.native_score['plan']['events'] if e['type']=='note_on']), 16)
            self.assertEqual(sum(c.note is not None and c.note < 120 for p in compiled.patterns for row in p.rows for c in row), 16)
            page.click('[data-action=paste-replace]')
            old_ids = [b['id'] for b in first['score']['patterns']['G']['beats']]
            self.settled(page, f"SCORE.view.score.patterns.G.beats.every(b=>!{json.dumps(old_ids)}.includes(b.id))")
            page.evaluate("tab('pattern');showPattern(3)")
            page.wait_for_function("PAT.order===3 && PAT.score_positions?.some(p=>p.kind==='note')")
            page.evaluate('rollToggle()'); page.wait_for_selector('#roll [data-score-id]')
            page.select_option('#roll-scope', 'track')
            page.select_option('#roll-track', 'guitar')
            self.assertEqual(page.locator('#roll [data-score-id]').count(), 4)
            page.click('#lv-undo'); page.wait_for_function('!EDQ.n')
            self.assertEqual(state.song, first)
            page.click('#lv-undo'); page.wait_for_function('!EDQ.n')
            self.assertEqual((folder / 'song.yaml').read_bytes(), before)
            self.assertFalse(errors, errors)

    def test_cross_range_duration_voice_dots_tuplet_refresh_and_history(self):
        import copy
        source=self.four_bar_song()
        # Retained second voice has independent duration and routing.
        peer=copy.deepcopy(source['score']['patterns']['C']['beats'][0])
        peer.update(id='lower',voice=1,written=dict(value=1,dots=0,tuplet=[1,1]));peer['notes']=[dict(id='low',pitch=40,string=6,fret=0,velocity=95)]
        source['score']['patterns']['C']['beats'].append(peer)
        with self.muted_page(api.to_yaml(source),width=1920,height=1080) as (page,state,folder):
            original=(folder/'song.yaml').read_bytes();errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
            page.evaluate("tab('tab');setEdit(true)")
            page.wait_for_selector('[data-ui=track]',state='attached');self.capture_engraving(page)
            page.select_option('[data-ui=track]','guitar');page.wait_for_function('window.tabRendered&&tabRenderApi.boundsLookup?.isFinished')
            self.click_tab_lane(page,0,0,2);self.settled(page,'SCORE.view.order===0')
            page.keyboard.down('Shift')
            try:self.click_tab_lane(page,1,3,3)
            finally:page.keyboard.up('Shift')
            self.settled(page,"document.querySelectorAll('.vt-tab-selection').length===9")
            self.assertIn('voice 1',page.inner_text('[data-ui=range-duration]'))
            # Ordinary lack of room is a logged no-op; diagnostics still include the user's control and selection.
            with self.assertLogs(gui._log,level='INFO') as logged, page.expect_request('**/api/score_command') as request:
                page.click('[data-action=longer]')
                page.wait_for_function("document.querySelector('.vt-tab-status').textContent.includes('unchanged')")
            page.wait_for_function("document.querySelector('.vt-tab-status').textContent.includes('unchanged')")
            self.settled(page,'!EDQ.n&&!SCORE.fetching')
            sent=request.value.post_data_json
            self.assertEqual(sent['ui_context']['action'],'longer')
            self.assertFalse(sent['ui_context']['fit'])
            self.assertEqual(sent['ui_context']['written']['value'],4)
            self.assertEqual(sent['written']['value'],2)
            event=next(json.loads(r.getMessage().removeprefix('TAB edit ')) for r in logged.records
                       if r.getMessage().startswith('TAB edit '))
            self.assertEqual(event['outcome'],'noop')
            self.assertEqual(event['ui_context'],sent['ui_context'])
            self.assertEqual(event['song'],str(folder/'song.yaml'))
            self.assertEqual(event['selected_total'],9)
            self.assertEqual(event['before_revision'],event['after_revision'])
            self.assertEqual((folder/'song.yaml').read_bytes(),original)
            self.assertEqual(len(state.history),0)
            def changed(value,dots=0,n=1,d=1):
                self.settled(page,f"['C','F'].every(p=>SCORE.view.score.patterns[p].beats.filter(b=>b.voice===0&&b.notes.length).every(b=>b.written.value==={value}&&b.written.dots==={dots}&&b.written.tuplet[0]==={n}&&b.written.tuplet[1]==={d}))")
                self.assertEqual(next(b for b in state.song['score']['patterns']['C']['beats'] if b['id']=='lower'),peer)
            page.locator('#tab-editor').focus()
            with page.expect_request('**/api/score_command') as request:
                page.keyboard.press('-')
            changed(8)
            self.assertEqual(request.value.post_data_json['ui_context']['action'],'shorter')
            self.assertEqual(request.value.post_data_json['written']['value'],8)
            page.evaluate("async()=>{SCORE.key=null;await scoreRefresh()}")
            self.settled(page,"document.querySelectorAll('.vt-tab-selection').length===17")
            saved=(folder/'song.yaml').read_bytes();count=len(state.history)
            page.click('[data-action=duration]');self.settled(page,'!EDQ.n&&!SCORE.fetching')
            self.assertEqual((folder/'song.yaml').read_bytes(),saved);self.assertEqual(len(state.history),count)
            page.click('[data-action=longer]');changed(4)
            page.click('[data-action=shorter]');changed(8)
            page.select_option('[data-ui=dots]','1');page.click('[data-action=duration]');changed(8,1)
            page.fill('[data-ui=tuple-n]','3');page.fill('[data-ui=tuple-d]','2')
            page.click('[data-action=duration]');changed(8,1,3,2)
            # +/- clear dots, retain tuplet and apply caret-chosen spelling to every selected active beat.
            page.click('[data-action=longer]');changed(4,0,3,2)
            page.locator('#tab-editor').focus();page.keyboard.press('/')
            changed(4)
            page.check('[data-ui=fit]');saved=(folder/'song.yaml').read_bytes();count=len(state.history)
            page.click('[data-action=longer]')
            page.wait_for_function("document.querySelector('.vt-tab-status').textContent.includes('unchanged')")
            self.assertEqual((folder/'song.yaml').read_bytes(),saved);self.assertEqual(len(state.history),count)
            for _ in range(count):
                page.click('[data-action=undo]');page.wait_for_function('!EDQ.n&&!SCORE.fetching')
            self.assertEqual((folder/'song.yaml').read_bytes(),original);self.assertFalse(errors,errors)

    def test_cross_range_expression_mixed_set_clear_and_history(self):
        source=self.four_bar_song()
        source['module']['tempo']=120  # Palm-mute's native cap lands exactly on this IT tick grid.
        source['score']['patterns']['C']['beats'][0]['notes'][0].update(velocity=63,accent=True)
        source['score']['patterns']['F']['beats'][1]['notes'][0].pop('velocity',None)
        with self.muted_page(api.to_yaml(source),width=1920,height=1080) as (page,state,folder):
            original=(folder/'song.yaml').read_bytes();errors=[]
            page.on('pageerror',lambda e:errors.append(str(e)))
            page.evaluate("tab('tab');setEdit(true)")
            page.wait_for_selector('[data-ui=track]',state='attached');self.capture_engraving(page)
            page.select_option('[data-ui=track]','guitar')
            page.wait_for_function('window.tabRendered&&tabRenderApi.boundsLookup?.isFinished')
            self.click_tab_lane(page,0,0,2);page.keyboard.down('Shift')
            try:self.click_tab_lane(page,1,3,3)
            finally:page.keyboard.up('Shift')
            self.settled(page,"document.querySelectorAll('.vt-tab-selection').length===8")
            self.assertEqual(page.get_attribute('[data-ui=velocity]','placeholder'),'mixed')
            self.assertIn('accent',page.inner_text('[data-ui=range-expression-info]'))
            self.assertEqual(page.get_attribute('[data-action=accent]','aria-pressed'),'mixed')
            page.locator('#tab-editor').focus();page.keyboard.press('Control+c')
            page.wait_for_function("document.querySelector('.vt-tab-status').textContent.startsWith('Copied 8')")
            page.click('[data-action=ghost]')
            page.wait_for_function("document.querySelector('.vt-tab-status').textContent.includes('requires explicit')")
            self.assertEqual((folder/'song.yaml').read_bytes(),original);self.assertEqual(len(state.history),0)
            page.select_option('[data-ui=dynamics]','63');page.click('[data-action=velocity]')
            self.settled(page,"SCORE.view.score.patterns.F.beats.every(b=>b.notes.every(n=>n.velocity===63))")
            page.click('[data-action=ghost]')
            self.settled(page,"SCORE.view.score.patterns.F.beats.every(b=>b.notes.every(n=>n.ghost))")
            self.assertEqual(page.get_attribute('[data-action=accent]','aria-pressed'),'false')
            page.evaluate("async()=>{SCORE.key=null;await scoreRefresh()}")
            self.settled(page,"document.querySelectorAll('.vt-tab-selection').length===8")
            saved=(folder/'song.yaml').read_bytes();count=len(state.history)
            page.click('[data-action=ghost]');self.settled(page,'!EDQ.n&&!SCORE.fetching')
            self.assertEqual((folder/'song.yaml').read_bytes(),saved);self.assertEqual(len(state.history),count)
            page.click('[data-action=staccato]')
            self.settled(page,"SCORE.view.score.patterns.F.beats.every(b=>b.notes.every(n=>n.staccato))")
            page.click('[data-action=palm-mute]')
            self.settled(page,"SCORE.view.score.patterns.F.beats.every(b=>b.notes.every(n=>n.palm_mute&&!n.staccato))")
            page.select_option('[data-ui=range-articulation]','clear')
            self.assertTrue(page.get_attribute('[data-action=ghost]','title').startswith('Clear'))
            page.click('[data-action=ghost]')
            self.settled(page,"SCORE.view.score.patterns.F.beats.every(b=>b.notes.every(n=>!n.ghost))")
            page.click('[data-action=palm-mute]')
            self.settled(page,"SCORE.view.score.patterns.F.beats.every(b=>b.notes.every(n=>!n.palm_mute))")
            # Exact custom velocity, including silent attacks, uses the same range path.
            page.fill('[data-ui=velocity]','0');page.click('[data-action=velocity]')
            self.settled(page,"SCORE.view.score.patterns.F.beats.every(b=>b.notes.every(n=>n.velocity===0))")
            self.assertEqual(state.song['score']['patterns']['G'],source['score']['patterns']['G'])
            for _ in range(7):
                revision=page.evaluate('SCORE.view.revision');page.click('[data-action=undo]')
                self.settled(page,'SCORE.view.revision!=='+json.dumps(revision))
            self.assertEqual((folder/'song.yaml').read_bytes(),original)
            # Range expression never replaces the copied payload, including failed commands.
            self.click_tab_lane(page,2,0,1)
            self.settled(page,'SCORE.view.order===2&&SCORE.view.revision==='+json.dumps(state.text_sha()))
            page.click('[data-action=paste-replace]')
            self.settled(page,"SCORE.view.score.patterns.C2.beats.every(b=>b.id.startsWith('copy_'))")
            pasted=state.song['score']['patterns']['G']['beats'][0]['notes'][0]
            self.assertEqual(pasted['velocity'],63);self.assertTrue(pasted['accent'])
            page.click('[data-action=undo]');page.wait_for_function('!EDQ.n&&!SCORE.fetching')
            self.assertEqual((folder/'song.yaml').read_bytes(),original);self.assertFalse(errors,errors)

    def test_cross_range_pitch_controls_refresh_undo_and_tracker(self):
        import copy
        from vulturetracker.itreader import read_it
        source=self.four_bar_song()
        with self.muted_page(api.to_yaml(source),width=1920,height=1080) as (page,state,folder):
            self.assertFalse(state.error,state.error)
            original=(folder/'song.yaml').read_bytes();errors=[]
            page.on('pageerror',lambda e:errors.append(str(e)))
            page.evaluate("tab('tab');setEdit(true)")
            page.wait_for_selector('[data-ui=track]',state='attached');self.capture_engraving(page)
            page.select_option('[data-ui=track]','guitar')
            page.wait_for_function('window.tabRendered&&tabRenderApi.boundsLookup?.isFinished')
            self.click_tab_lane(page,0,0,1);page.keyboard.down('Shift')
            try:self.click_tab_lane(page,1,3,1)
            finally:page.keyboard.up('Shift')
            self.settled(page,"document.querySelectorAll('.vt-tab-selection').length===8")
            page.locator('#tab-editor').focus();page.keyboard.press('Shift+ArrowRight')
            self.settled(page,"SCORE.view.score.patterns.C.beats[0].notes[0].pitch===61")
            page.evaluate("async()=>{SCORE.key=null;await scoreRefresh()}")
            self.settled(page,"document.querySelectorAll('.vt-tab-selection').length===8")
            page.keyboard.press('Shift+ArrowLeft')
            self.settled(page,"SCORE.view.score.patterns.C.beats[0].notes[0].pitch===60")
            page.click('[data-action=transpose]')
            self.assertEqual(page.input_value('[data-ui=transpose-scope]'),'selection')
            self.assertTrue(page.is_disabled('[data-ui=transpose-all]'))
            self.assertFalse(page.is_checked('[data-ui=transpose-all]'))
            page.select_option('[data-ui=transpose-scope]','track')
            self.assertTrue(page.is_checked('[data-ui=transpose-all]'));self.assertFalse(page.is_disabled('[data-ui=transpose-all]'))
            page.select_option('[data-ui=transpose-scope]','selection')
            page.fill('[data-ui=transpose-semitones]','2');page.click('.vt-tab-transpose button[type=submit]')
            self.settled(page,"SCORE.view.score.patterns.F.beats[0].notes[0].pitch===55")
            page.click('[data-action=close-transpose]')
            pitched=(folder/'song.yaml').read_bytes();plan=copy.deepcopy(state.mod.native_score['plan']['events'])
            it=api.compile_song(folder/'song.yaml')[0]
            page.click('[data-action=string-down]')
            self.settled(page,"SCORE.view.score.patterns.C.beats[0].notes[0].string===3")
            page.evaluate("async()=>{SCORE.key=null;await scoreRefresh()}")
            self.settled(page,"document.querySelectorAll('.vt-tab-selection').length===8")
            self.assertEqual(state.mod.native_score['plan']['events'],plan)
            self.assertEqual(api.compile_song(folder/'song.yaml')[0],it)
            self.assertEqual(state.song['score']['patterns']['G'],source['score']['patterns']['G'])
            page.click('[data-action=string-up]')
            self.settled(page,"SCORE.view.score.patterns.C.beats[0].notes[0].string===2")
            self.assertEqual(api.compile_song(folder/'song.yaml')[0],it)
            compiled=read_it(it)[0]
            self.assertEqual([c.note for row in compiled.patterns[0].rows for c in row if c.note is not None and c.note<120],[62,66,69,66])
            page.evaluate("setCursor(1,0,0,0);tab('pattern');showPattern(1)")
            page.wait_for_function("PAT.order===1&&PAT.score_positions?.some(p=>p.kind==='note')")
            page.evaluate('rollToggle()');page.select_option('#roll-scope','track');page.select_option('#roll-track','guitar')
            page.wait_for_function("document.querySelectorAll('#roll .rnote[data-score-id]').length===4")
            for _ in range(5):
                page.click('#lv-undo');page.wait_for_function('!EDQ.n&&!SCORE.fetching')
            self.assertEqual((folder/'song.yaml').read_bytes(),original)
            self.assertEqual(errors,[])

    def test_cross_cut_repeat_clipboard_failure_history_and_roll(self):
        from vulturetracker.itreader import read_it
        source = self.four_bar_song()
        # A partial tie is supported; an approved destination provides the real Cut refusal.
        n = source['score']['patterns']['C']['beats'][2]['notes'][0]
        n.update(pitch=64, string=1, fret=0)
        source['score']['ties'] = [{'from': dict(occurrence='bar1', note='note1'),
                                   'to': dict(occurrence='bar1', note='note2')}]
        with self.muted_page(api.to_yaml(source), width=1920, height=1080) as (page, state, folder):
            self.assertFalse(state.error, state.error)
            original = (folder/'song.yaml').read_bytes()
            errors=[]; page.on('pageerror',lambda e:errors.append(str(e)))
            page.evaluate("tab('tab');setEdit(true)")
            page.wait_for_selector('[data-ui=track]',state='attached'); self.capture_engraving(page)
            page.select_option('[data-ui=track]','guitar')
            page.wait_for_function('window.tabRendered && tabRenderApi.boundsLookup?.isFinished')
            def select(firstbar,firstbeat,lastbar,lastbeat):
                self.click_tab_lane(page,firstbar,firstbeat,1)
                self.settled(page,f'SCORE.view.order==={firstbar} && tabRenderApi.boundsLookup?.isFinished')
                end=self.tab_lane_point(page,lastbar,lastbeat,1)
                page.keyboard.down('Shift');page.mouse.click(end['x'],end['y']);page.keyboard.up('Shift')
                self.settled(page,f'SCORE.view.order==={lastbar}')
                self.settled(page,f'document.querySelectorAll(".vt-tab-selection").length==={(lastbar-firstbar)*4+lastbeat-firstbeat+1}')
            self.click_tab_lane(page,0,0,2); page.click('[data-action=copy]')
            page.wait_for_function("document.querySelector('.vt-tab-status').textContent.startsWith('Copied 1')")
            page.evaluate("tab('song')")
            page.locator('span[title="approved: an agent\'s tools leave this pattern alone"]').nth(1).click()
            self.settled(page,"S.marks.patterns.F?.approved")
            protected=(folder/'song.yaml').read_bytes()
            page.evaluate("tab('tab')");self.settled(page,'tabRenderApi.boundsLookup?.isFinished')
            select(0,2,1,0)
            page.locator('#tab-editor').focus(); page.keyboard.press('Control+x')
            self.settled(page,"document.querySelector('.vt-tab-status').textContent.includes('approved')")
            self.assertEqual((folder/'song.yaml').read_bytes(),protected)
            page.click('[data-action=undo]');self.settled(page,"!S.marks.patterns.F?.approved")
            self.assertEqual((folder/'song.yaml').read_bytes(),original)
            # A failed Cut must keep the previous one-beat clipboard, not the failed range.
            self.click_tab_lane(page,2,0,1); self.settled(page,'SCORE.view.order===2')
            page.click('[data-action=paste-replace]')
            self.settled(page,"SCORE.view.score.patterns.G.beats.some(b=>b.id==='copy_beat0')")
            pasted=next(b for b in state.song['score']['patterns']['G']['beats'] if b['id']=='copy_beat0')
            self.assertEqual(pasted['notes'][0]['pitch'],60)
            page.click('[data-action=undo]'); self.settled(page,"!SCORE.view.score.patterns.G.beats.some(b=>b.id==='copy_beat0')")
            self.assertEqual((folder/'song.yaml').read_bytes(),original)
            select(0,0,1,3)
            page.locator('#tab-editor').focus();page.keyboard.press('Control+x')
            self.settled(page,"SCORE.view.score.patterns.C.beats.every(b=>!b.notes.length)&&SCORE.view.score.patterns.F.beats.every(b=>!b.notes.length)")
            self.assertEqual(state.song['score']['ties'],[])
            self.click_tab_lane(page,2,0,1); self.settled(page,'SCORE.view.order===2')
            page.click('[data-action=paste-replace]')
            self.settled(page,"SCORE.view.score.patterns.C2.beats.every(b=>b.id.startsWith('copy_'))")
            self.assertEqual(len(state.song['score']['ties']),1)
            for _ in range(2):
                page.click('[data-action=undo]'); page.wait_for_function('!EDQ.n&&!SCORE.fetching')
            self.assertEqual((folder/'song.yaml').read_bytes(),original)
            select(0,0,1,3)
            page.locator('#tab-editor').focus();page.keyboard.press('Control+r')
            self.settled(page,"SCORE.view.order===2&&SCORE.view.score.patterns.C2.beats.every(b=>b.id.startsWith('copy_'))")
            page.evaluate("async()=>{SCORE.key=null;await scoreRefresh()}")
            page.wait_for_function('tabRenderApi.boundsLookup?.isFinished')
            self.settled(page,"document.querySelectorAll('.vt-tab-selection').length===8")
            self.assertEqual(sorted(page.locator('.vt-tab-selection').evaluate_all('els=>els.map(e=>e.dataset.occurrence)')),
                             ['bar3']*4+['bar4']*4)
            saved=(folder/'song.yaml').read_bytes()
            page.keyboard.press('Control+r')
            self.settled(page,'SCORE.view.orders.length===6')
            page.click('[data-action=undo]');self.settled(page,'SCORE.view.orders.length===4')
            self.assertEqual((folder/'song.yaml').read_bytes(),saved)
            compiled=read_it(api.compile_song(folder/'song.yaml')[0])[0]
            self.assertEqual(sum(c.note is not None and c.note<120 for p in compiled.patterns for row in p.rows for c in row),14)
            page.evaluate("tab('pattern');showPattern(3)")
            page.wait_for_function("PAT.order===3&&PAT.score_positions?.some(p=>p.kind==='note')")
            page.evaluate('rollToggle()');page.select_option('#roll-scope','track');page.select_option('#roll-track','guitar')
            self.assertEqual(page.locator('#roll .rnote[data-score-id]').count(),4)
            page.click('#lv-undo');page.wait_for_function('!EDQ.n')
            self.assertEqual((folder/'song.yaml').read_bytes(),original)
            self.assertFalse(errors,errors)

    def test_native_selection_transport_and_rounded_frame_playhead(self):
        with self.muted_page(NATIVE_SONG) as (page, state, folder):
            self.assertFalse(state.error, state.error)
            before = (folder / 'song.yaml').read_bytes()
            page.evaluate("tab('tab')")
            page.wait_for_function("SCORE.view?.native && document.querySelector('.vt-tab-grid [data-note=\"note-1\"]')")
            page.wait_for_selector('.vt-tab-score svg')
            page.click('.vt-tab-grid [data-note="note-1"]')
            selection = page.evaluate('CUR.score')
            self.assertEqual({k: selection[k] for k in ('id', 'occurrence', 'beat', 'note', 'track', 'voice', 'string', 'at', 'row')},
                             dict(id='pass-1/note-1', occurrence='pass-1', beat='beat-1', note='note-1',
                                  track='guitar', voice=0, string=1, at=[4, 13], row=[48, 13]))
            self.assertEqual(page.evaluate('CUR.row'), 3)  # Pattern's containing row is display-only.
            page.evaluate("async () => {SCORE.key=null;await scoreRefresh()}")
            self.assertEqual(page.evaluate('CUR.score'), selection)
            self.assertEqual(page.input_value('[data-ui=at]'), '4/13')
            page.evaluate("() => {lvPlay=(order,row)=>{window.tabTransport={order,row}}}")
            page.click('[data-action=play]')
            self.assertEqual(page.evaluate('window.tabTransport'), dict(order=0, row=[48, 13]))
            page.locator('#tab-editor').focus()
            page.keyboard.press('Space')
            self.assertEqual(page.evaluate('window.tabTransport'), dict(order=0, row=[48, 13]))

            # Repeated patterns carry occurrence identity through refresh and selection.
            page.evaluate("async () => {setCursor(2,0,0,0);await scoreRefresh()}")
            self.settled(page, 'SCORE.view.order===2')
            page.click('.vt-tab-grid [data-note="note-1"]')
            self.assertEqual(page.evaluate('CUR.score.id'), 'pass-3/note-1')
            page.evaluate("SCORE.editor.setSelection({order:2,occurrence:'pass-2',at:[0,1],track:'guitar'})")
            self.assertEqual(page.input_value('[data-ui=at]'), '4/13')
            page.click('[data-action=play]')
            self.assertEqual(page.evaluate('window.tabTransport'), dict(order=2, row=[48, 13]))

            # Choose an onset whose half-up frame lies just before its musical time.
            rate, tempo = 48000, 137
            origin = Fraction(8)
            i = next(i for i in range(1, 13)
                     if (origin + Fraction(4*i, 13)) * 60 * rate / tempo % 1 < Fraction(1, 2))
            exact = (origin + Fraction(4*i, 13)) * 60 * rate / tempo
            frame = (2*exact.numerator + exact.denominator) // (2*exact.denominator)
            local = Fraction(frame*tempo, 60*rate) - origin
            self.assertLess(local, Fraction(4*i, 13))
            position = dict(o=2, occurrence='pass-3', at=[local.numerator, local.denominator],
                            scoreFrame=frame, sampleRate=rate)
            page.evaluate("p => {window.tabPosition=p;playPos=()=>window.tabPosition;SCORE.editor.setPlayhead(p)}", position)
            page.wait_for_selector(f'.vt-tab-grid [data-note="note-{i}"].playing')
            page.wait_for_selector('.vt-tab-playhead:not([hidden])')
            self.assertEqual(page.get_attribute('.vt-tab-playhead', 'data-at'), f'{4*i}/13')
            position['scoreFrame'] = frame-1
            page.evaluate("p => {window.tabPosition=p;SCORE.editor.setPlayhead(p)}", position)
            page.wait_for_selector(f'.vt-tab-grid [data-note="note-{i-1}"].playing')
            # Hosts without a frame clock can provide exact rational row positions.
            position = dict(o=2, occurrence='pass-3', row=3, exactRow=[48, 13])
            page.evaluate("p => {window.tabPosition=p;SCORE.editor.setPlayhead(p)}", position)
            page.wait_for_selector('.vt-tab-grid [data-note="note-1"].playing')
            position['occurrence'] = 'pass-2'
            page.evaluate("p => {window.tabPosition=p;SCORE.editor.setPlayhead(p)}", position)
            self.assertEqual(page.locator('.vt-tab-grid .playing').count(), 0)
            self.assertTrue(page.is_hidden('.vt-tab-playhead'))
            self.assertEqual((folder / 'song.yaml').read_bytes(), before)

    def open_tab(self, page):
        page.evaluate("tab('tab')")
        page.wait_for_function("SCORE.editor && SCORE.view?.score && document.querySelector('.vt-tab-grid [data-note=\"note-a\"]')")
        page.wait_for_selector('.vt-tab-score svg')
        self.assertNotIn('rendering failed', page.inner_text('.vt-tab-status'))
        self.assertNotIn('12:1', page.inner_text('.vt-tab-score'))
        self.assertIn('unmetered display groups', page.inner_text('.vt-tab-meter'))

    def settled(self, page, condition):
        try:
            page.wait_for_function("!EDQ.n && !SCORE.fetching && (" + condition + ")", timeout=10000)
        except page_fixture.PlaywrightError as error:
            diagnostic = page.evaluate("""() => ({
                queue: {pending: EDQ.n, error: EDQ.err}, fetching: SCORE.fetching,
                status: document.querySelector('.vt-tab-status')?.textContent,
                highlights: [...document.querySelectorAll('.vt-tab-selection')].map(e=>({...e.dataset})),
                cursor: {...CUR}, focus: {tag: document.activeElement?.tagName, id: document.activeElement?.id,
                    html: document.activeElement?.outerHTML.slice(0, 300)},
                view: {song: SCORE.view?.song, pattern: SCORE.view?.pattern, order: SCORE.view?.order,
                    revision: SCORE.view?.revision, score: SCORE.view?.score},
                events: window.tabKeyTrace || []
            })""")
            self.fail(f'{condition}\n{error}\nTAB diagnostics: {json.dumps(diagnostic, ensure_ascii=False)}')

    def click_score_note(self, page, bar, track_index=0):
        point = page.evaluate("""({bar,track_index})=>{
            const beat=tabRendered.tracks[track_index].staves[0].bars[bar].voices[0].beats.find(b=>b.notes.length);
            const bounds=tabRenderApi.boundsLookup.findBeat(beat).notes.find(n=>n.note===beat.notes[0]).noteHeadBounds;
            const marker=document.createElement('div');
            Object.assign(marker.style,{position:'absolute',left:bounds.x+'px',top:bounds.y+'px',
                width:bounds.w+'px',height:bounds.h+'px',pointerEvents:'none'});
            document.querySelector('.vt-tab-score .at-surface').append(marker);
            marker.scrollIntoView({block:'center'});
            const r=marker.getBoundingClientRect(),point={x:r.x+r.width/2,y:r.y+r.height/2};
            marker.remove();return point;
        }""", dict(bar=bar,track_index=track_index))
        page.mouse.click(point['x'], point['y'])

    def click_tab_lane(self, page, bar, beat, string, voice=0, track_index=0):
        point = self.tab_lane_point(page, bar, beat, string, voice, track_index)
        page.mouse.click(point['x'], point['y'])

    @staticmethod
    def tab_lane_point(page, bar, beat, string, voice=0, track_index=0):
        return page.evaluate("""({bar,beat,string,voice,track_index})=>{
            const b=tabRendered.tracks[track_index].staves[0].bars[bar].voices[voice].beats[beat];
            if (!b) throw new Error('Missing rendered beat '+JSON.stringify({bar,beat,voice,
                counts:tabRendered.tracks[track_index].staves[0].bars.map(b=>b.voices.map(v=>v.beats.length)),
                revision:SCORE.view.revision,renderedRevision:window.tabRenderedRevision}));
            const bounds=tabRenderApi.boundsLookup.findBeats(b).at(-1);
            const renderer=tabRenderApi.renderer.instance.layout.getRendererForBar('tab',b.voice.bar);
            const x=bounds.onNotesX,y=bounds.barBounds.visualBounds.y+renderer.getLineY(string-1);
            const marker=document.createElement('div');
            Object.assign(marker.style,{position:'absolute',left:x+'px',top:y+'px',
                width:'1px',height:'1px',pointerEvents:'none'});
            document.querySelector('.vt-tab-score .at-surface').append(marker);
            marker.scrollIntoView({block:'center'});
            const r=marker.getBoundingClientRect();marker.remove();return {x:r.x,y:r.y};
        }""", dict(bar=bar, beat=beat, string=string, voice=voice, track_index=track_index))

    def capture_engraving(self, page):
        page.evaluate("""() => {
            const render = alphaTab.AlphaTabApi.prototype.renderScore;
            alphaTab.AlphaTabApi.prototype.renderScore = function(score, ...args) {
                window.tabRendered = score;
                window.tabRenderedRevision = typeof SCORE === 'undefined' ? null : SCORE.view?.revision;
                window.tabRenderApi = this;
                window.tabRenderCount = (window.tabRenderCount || 0) + 1;
                return render.call(this, score, ...args);
            };
        }""")

    def print_ready(self, page):
        page.wait_for_function("document.querySelector('[data-print=print]:not(:disabled)') || document.querySelector('.vt-print-status')?.textContent.startsWith('Cannot print')")
        self.assertFalse(page.locator('[data-print=print]').is_disabled(), page.inner_text('.vt-print-status'))

    def print_url(self, page, state, **overrides):
        query = dict(token=page.url.split('token=')[1], song=str(state.song_path), revision=state.text_sha())
        query.update(overrides)
        return f'{urlsplit(page.url).scheme}://{urlsplit(page.url).netloc}/score-print?{urlencode(query)}'

    def test_full_song_print_occurrences_ties_layout_and_no_writes(self):
        with self.page(PRINT_SONG) as (page, state, folder):
            self.assertFalse(state.error, state.error)
            before = (folder / 'song.yaml').read_bytes()
            history = (list(state.history), list(state.future))
            page.evaluate("tab('tab')")
            page.wait_for_selector('[data-action=print]')
            page.click('[data-action=print]')
            page.wait_for_selector('#score-print-frame')
            frame = page.locator('#score-print-frame').element_handle().content_frame()
            self.print_ready(frame)
            frame.get_by_role('button', name='Print / Save PDF', exact=True).evaluate('e=>{window.printCalls=0;window.print=()=>window.printCalls++}')
            frame.get_by_role('button', name='Print / Save PDF', exact=True).click()
            self.assertEqual(frame.evaluate('window.printCalls'), 1)
            page.evaluate('() => {window.printTransportCalls=0; window.printSavedPlay=lvPlay; lvPlay=()=>window.printTransportCalls++;}')
            page.get_by_role('button', name='Close preview', exact=True).focus()
            page.keyboard.press('F6')
            self.assertEqual(page.evaluate('window.printTransportCalls'), 0)
            page.evaluate('lvPlay=window.printSavedPlay; delete window.printSavedPlay')
            frame.get_by_role('button', name='Print / Save PDF', exact=True).focus()
            page.keyboard.press('Escape')
            self.assertFalse(page.locator('#score-print-dialog').is_visible())
            page.click('[data-action=print]')
            page.wait_for_selector('#score-print-frame')
            self.print_ready(page.locator('#score-print-frame').element_handle().content_frame())
            page.get_by_role('button', name='Close preview', exact=True).click()
            self.assertFalse(page.locator('#score-print-dialog').is_visible())
            preview = page.context.browser.new_page()
            preview.goto(self.print_url(page, state))
            errors = []
            preview.on('pageerror', lambda error: errors.append(str(error)))
            self.print_ready(preview)
            self.assertIn('4 order occurrences · 3 authored measures · 3 displayed bars', preview.inner_text('[data-print=summary]'))
            self.capture_engraving(preview)
            preview.evaluate('() => {window.printCalls = 0; window.print = () => { window.printCalls++; };}')
            preview.select_option('[name=breaks]', ['1', '2'])
            preview.fill('[name=composer]', 'Print-only composer')
            preview.get_by_role('button', name='Update preview', exact=True).click()
            self.print_ready(preview)
            model = preview.evaluate("""() => ({title: tabRendered.title, composer: tabRendered.music, tempo: tabRendered.tempo,
                meters: tabRendered.masterBars.map(b => [b.timeSignatureNumerator,b.timeSignatureDenominator]),
                tracks: tabRendered.tracks.map(t => ({name:t.name, clef:t.staves[0].bars[0].clef,key:t.staves[0].bars[0].keySignature,
                    notes:t.staves[0].bars.flatMap(b=>b.voices[0].beats.flatMap(b=>b.notes.map(n=>({pitch:n.realValue,tied:n.isTieDestination,spelling:n.accidentalMode}))))}))})""")
            self.assertEqual(model['title'], 'Full song print')
            self.assertEqual(model['composer'], 'Print-only composer')
            self.assertEqual(model['tempo'], 125)
            self.assertEqual(model['meters'], [[6, 4], [2, 4], [8, 4]])
            self.assertEqual([t['name'] for t in model['tracks']], ['Lead guitar', 'Bass guitar'])
            self.assertEqual(preview.evaluate('tabRenderApi.tracks.map(t=>t.name)'), ['Lead guitar', 'Bass guitar'])
            self.assertIn('Lead guitar', preview.inner_text('.vt-print-pages'))
            self.assertIn('Bass guitar', preview.inner_text('.vt-print-pages'))
            self.assertEqual([t['key'] for t in model['tracks']], [6, -3])
            self.assertNotEqual(model['tracks'][0]['clef'], model['tracks'][1]['clef'])
            self.assertEqual([n['pitch'] for n in model['tracks'][0]['notes']], [65, 65, 65, 65, 65])
            self.assertEqual([n['tied'] for n in model['tracks'][0]['notes']], [False, True, True, False, False])
            self.assertTrue(all(n['spelling'] == preview.evaluate('alphaTab.model.NoteAccidentalMode.ForceSharp') for n in model['tracks'][0]['notes']))
            self.assertEqual(preview.locator('.vt-print-page').count(), 3)
            self.assertEqual(preview.evaluate('window.printCalls'), 0)
            preview.get_by_role('button', name='Print / Save PDF', exact=True).click()
            self.assertEqual(preview.evaluate('window.printCalls'), 1)
            preview.emulate_media(media='print')
            self.assertTrue(preview.locator('.vt-print-controls').is_hidden())
            self.assertTrue(preview.evaluate("[...document.querySelectorAll('.vt-print-content')].every(e=>e.scrollHeight<=e.clientHeight+1 && e.scrollWidth<=e.clientWidth+1)"))
            pdf = preview.pdf(prefer_css_page_size=True, print_background=True)
            self.assertTrue(pdf.startswith(b'%PDF-'))
            self.assertEqual(len(re.findall(rb'/Type /Page\b', pdf)), 3)
            self.assertEqual((folder / 'song.yaml').read_bytes(), before)
            self.assertEqual((state.history, state.future), history)
            self.assertEqual(errors, [])
            preview.close()

    def test_print_modes_track_selection_invalid_geometry_and_stale_snapshot(self):
        with self.page(PRINT_SONG) as (page, state, folder):
            before = (folder / 'song.yaml').read_bytes()
            preview = page.context.browser.new_page()
            preview.goto(self.print_url(page, state))
            self.print_ready(preview)
            self.capture_engraving(preview)
            preview.uncheck('[name=track][value=lead]')
            preview.select_option('[name=notation]', 'staff')
            preview.select_option('[name=paper]', 'letter')
            preview.select_option('[name=orientation]', 'landscape')
            preview.fill('[name=left]', '20')
            preview.get_by_role('button', name='Update preview', exact=True).click()
            self.print_ready(preview)
            self.assertEqual(preview.evaluate('tabRendered.tracks.map(t=>[t.name,t.staves[0].showStandardNotation,t.staves[0].showTablature])'), [['Bass guitar', True, False]])
            self.assertEqual(preview.locator('.vt-print').evaluate("e=>[e.style.getPropertyValue('--vt-paper-width'),e.style.getPropertyValue('--vt-paper-height')]"), ['279.4mm', '215.9mm'])
            preview.select_option('[name=notation]', 'tab')
            preview.get_by_role('button', name='Update preview', exact=True).click()
            self.print_ready(preview)
            self.assertEqual(preview.evaluate('[tabRendered.tracks[0].staves[0].showStandardNotation,tabRendered.tracks[0].staves[0].showTablature]'), [False, True])
            preview.fill('[name=scale]', '150')
            preview.fill('[name=top]', '60')
            preview.fill('[name=bottom]', '60')
            preview.select_option('[name=notation]', 'both')
            preview.check('[name=track][value=lead]')
            preview.get_by_role('button', name='Update preview', exact=True).click()
            preview.wait_for_function("document.querySelector('.vt-print-status').textContent.startsWith('Cannot print') || !document.querySelector('[data-print=print]').disabled")
            self.assertIn('taller than the page', preview.inner_text('.vt-print-status'))
            self.assertTrue(preview.locator('[data-print=print]').is_disabled())
            preview.uncheck('[name=track][value=lead]')
            preview.uncheck('[name=track][value=bass]')
            preview.get_by_role('button', name='Update preview', exact=True).click()
            self.assertIn('Choose at least one track', preview.inner_text('.vt-print-status'))
            self.assertTrue(preview.locator('[data-print=print]').is_disabled())
            for override in ({'revision': 'stale'}, {'song': 'another-song.yaml'}):
                preview.goto(self.print_url(page, state, **override))
                preview.wait_for_selector('#score-print[role=alert]')
                self.assertIn('song changed', preview.inner_text('#score-print'))
                self.assertEqual(preview.locator('.vt-print-page').count(), 0)
            self.assertEqual((folder / 'song.yaml').read_bytes(), before)
            preview.close()

    def test_long_score_print_automatic_pages_and_unmetered_remainder(self):
        song = PRINT_SONG.replace('orders: [verse, bridge, repeat, repeat]',
            'orders: [verse, bridge, ' + ', '.join(['repeat'] * 80) + ']').replace(
            'order_ids: [verse-1, bridge-1, repeat-1, repeat-2]',
            'order_ids: [verse-1, bridge-1, ' + ', '.join(f'repeat-{i}' for i in range(1, 81)) + ']')
        with self.page(song) as (page, state, folder):
            self.assertFalse(state.error, state.error)
            preview = page.context.browser.new_page()
            preview.goto(self.print_url(page, state))
            self.print_ready(preview)
            self.assertIn('82 order occurrences · 3 authored measures · 81 displayed bars', preview.inner_text('[data-print=summary]'))
            self.assertIn('Unmetered', preview.inner_text('.vt-print-pages'))
            page_count = preview.locator('.vt-print-page').count()
            self.assertGreater(page_count, 1)
            self.assertEqual(preview.locator('.vt-print-part[data-last-bar="80"]').count(), 1)
            pdf = preview.pdf(prefer_css_page_size=True, print_background=True)
            self.assertEqual(len(re.findall(rb'/Type /Page\b', pdf)), page_count)
            preview.close()

    def test_print_narrow_preview_keeps_both_paper_edges_reachable(self):
        with self.page(PRINT_SONG) as (page, state, folder):
            preview = page.context.browser.new_page(viewport={'width': 368, 'height': 900})
            preview.goto(self.print_url(page, state))
            self.print_ready(preview)
            geometry = preview.locator('.vt-print-pages').evaluate("""e=>{
                e.scrollLeft=0; const paper=e.querySelector('.vt-print-page'), left=paper.getBoundingClientRect().left,
                    container=e.getBoundingClientRect();
                e.scrollLeft=e.scrollWidth; const right=paper.getBoundingClientRect().right;
                return {left, containerLeft:container.left, right, containerRight:container.right, width:paper.getBoundingClientRect().width};
            }""")
            self.assertGreaterEqual(geometry['left'], geometry['containerLeft'] - 1)
            self.assertLessEqual(geometry['right'], geometry['containerRight'] + 1)
            self.assertAlmostEqual(geometry['width'], 210 * 96 / 25.4, delta=1)
            preview.close()

    def test_measure_and_track_navigation_preserves_occurrences_and_song(self):
        with self.page(PRINT_SONG) as (page, state, folder):
            before = (folder / 'song.yaml').read_bytes()
            history = (list(state.history), list(state.future))
            page.evaluate("tab('tab')")
            page.wait_for_selector('.vt-tab-grid button[data-note="lead-note-a"]')
            page.click('.vt-tab-grid button[data-note="lead-note-a"]')
            page.keyboard.press('Control+ArrowRight')
            self.settled(page, "CUR.o===1 && CUR.row===24 && SCORE.view.order===1")
            self.assertEqual(page.input_value('[data-ui=at]'), '2')
            page.keyboard.press('Control+Shift+ArrowDown')
            self.assertEqual(page.input_value('[data-ui=track]'), 'bass')
            self.assertEqual(page.evaluate('[CUR.o,CUR.row,CUR.ch]'), [1, 24, 2])
            self.assertEqual(page.input_value('[data-ui=at]'), '2')
            page.keyboard.press('Control+Shift+ArrowDown')
            self.assertEqual(page.input_value('[data-ui=track]'), 'bass')
            page.keyboard.press('Control+Shift+ArrowUp')
            self.assertEqual(page.input_value('[data-ui=track]'), 'lead')
            page.keyboard.press('Control+ArrowRight')
            self.settled(page, "CUR.o===2 && CUR.row===0 && SCORE.view.order===2")
            page.keyboard.press('Control+ArrowRight')
            self.assertEqual(page.evaluate('[CUR.o,CUR.row]'), [2, 0])
            page.keyboard.press('Control+Shift+ArrowLeft')
            self.settled(page, "CUR.o===0 && CUR.row===0 && SCORE.view.order===0")
            page.keyboard.press('Control+ArrowLeft')
            self.assertEqual(page.evaluate('[CUR.o,CUR.row]'), [0, 0])
            page.keyboard.press('Control+Shift+ArrowRight')
            self.settled(page, "CUR.o===2 && CUR.row===0 && SCORE.view.order===2")
            page.get_by_role('button', name='Last track', exact=True).focus()
            page.keyboard.press('Enter')
            self.assertEqual(page.input_value('[data-ui=track]'), 'bass')
            page.get_by_role('button', name='First track', exact=True).focus()
            page.keyboard.press('Enter')
            self.assertEqual(page.input_value('[data-ui=track]'), 'lead')
            page.get_by_role('button', name='Previous measure', exact=True).click()
            self.settled(page, "CUR.o===1 && CUR.row===24 && SCORE.view.order===1")
            page.select_option('[data-ui=track]', 'bass')
            self.assertEqual(page.input_value('[data-ui=at]'), '2')
            # Text controls retain their normal Ctrl+arrow behavior.
            page.fill('[data-ui=at]', '2')
            page.keyboard.press('Control+ArrowLeft')
            self.assertEqual(page.evaluate('[CUR.o,CUR.row,CUR.ch]'), [1, 24, 2])
            # TAB bindings do not replace Pattern's own cursor movement.
            page.evaluate("tab('pattern'); setCursor(1,24,0,0)")
            page.keyboard.press('Control+ArrowRight')
            self.assertEqual(page.evaluate('CUR.o'), 1)
            self.assertEqual((folder / 'song.yaml').read_bytes(), before)
            self.assertEqual((state.history, state.future), history)

    def test_unmetered_navigation_uses_repeated_order_occurrences(self):
        song = SONG.replace('orders: [verse]', 'orders: [verse, verse]').replace(
            'order_ids: [occ-verse]', 'order_ids: [occ-verse, occ-repeat]')
        with self.page(song) as (page, state, folder):
            self.open_tab(page)
            page.click('.vt-tab-grid button[data-note="note-a"]')
            page.keyboard.press('Control+ArrowRight')
            self.settled(page, "CUR.o===1 && CUR.row===0 && SCORE.view.order===1")
            self.assertEqual(page.evaluate('SCORE.view.score.order_ids[CUR.o]'), 'occ-repeat')
            page.keyboard.press('Control+ArrowRight')
            self.assertEqual(page.evaluate('CUR.o'), 1)
            page.keyboard.press('Control+ArrowLeft')
            self.settled(page, "CUR.o===0 && SCORE.view.order===0")
            self.assertEqual(state.history, [])

    def test_plain_arrows_cross_empty_and_repeated_occurrences_without_adoption(self):
        song = SONG.replace('voice: 0', 'voice: 1').replace('orders: [verse]',
            '  empty:\n    rows: 12\n    data: |\n'
            '      00: ... .. ... ... | D-5 01 ... D07\n'
            '      01: ... .. ... ... | ... .. ... ...\n'
            '      02: ... .. ... ... | ... .. ... ...\n'
            '      03: ... .. ... ... | ... .. ... ...\n'
            '      04: ... .. ... ... | === .. ... ...\n'
            'orders: [verse, empty, verse]').replace(
            'order_ids: [occ-verse]', 'order_ids: [occ-verse, occ-empty, occ-repeat]')
        with self.page(song) as (page, state, folder):
            self.assertFalse(state.error, state.error)
            before = (folder / 'song.yaml').read_bytes()
            revision, raw = state.text_sha(), state.score_view()['raw_positions']
            page.evaluate("tab('tab')")
            page.wait_for_function('SCORE.view?.score && SCORE.editor')
            # The first option's label "1" equals the second option's value;
            # select by index to avoid Playwright's value-or-label ambiguity.
            page.select_option('[data-ui=voice]', index=1)
            page.click('.vt-tab-grid button[data-note="note-b"]')
            page.keyboard.press('ArrowRight')
            self.assertEqual(page.evaluate('[CUR.o,CUR.row,CUR.ch]'), [0, 24, 1])
            page.keyboard.press('ArrowRight')
            self.settled(page, "CUR.o===1 && CUR.row===0 && SCORE.view.order===1")
            self.assertEqual(page.input_value('[data-ui=voice]'), '1')
            self.assertEqual(page.input_value('[data-ui=track]'), 'guitar')
            self.assertIn('string 2', page.inner_text('[data-ui=cursor]'))
            self.assertTrue(page.locator('[data-action=adopt]').is_disabled())
            # The empty order sits inside a 4/4 display bar: its fourth beat is a written rest starting at row 11.
            page.keyboard.press('ArrowRight')
            self.assertEqual(page.evaluate('[CUR.o,CUR.row,CUR.ch]'), [1, 11, 1])
            page.keyboard.press('ArrowRight')
            self.settled(page, "CUR.o===2 && CUR.row===0 && SCORE.view.order===2")
            self.assertEqual(page.evaluate('SCORE.view.score.order_ids[CUR.o]'), 'occ-repeat')
            self.assertEqual(page.input_value('[data-ui=voice]'), '1')
            self.assertIn('string 2', page.inner_text('[data-ui=cursor]'))
            # This order starts at 37/12: the 4/4 display bar line at 48/12 splits its rest at row 11.
            for expected in (4, 11, 12, 24):
                page.keyboard.press('ArrowRight')
                self.assertEqual(page.evaluate('[CUR.o,CUR.row,CUR.ch]'), [2, expected, 1])
            page.keyboard.press('ArrowRight')
            self.assertEqual(page.evaluate('[CUR.o,CUR.row]'), [2, 24])
            for expected in (12, 11, 4, 0):
                page.keyboard.press('ArrowLeft')
                self.assertEqual(page.evaluate('[CUR.o,CUR.row,CUR.ch]'), [2, expected, 1])
            page.keyboard.press('ArrowLeft')
            self.settled(page, "CUR.o===1 && CUR.row===11 && SCORE.view.order===1")
            page.keyboard.press('ArrowLeft')
            self.assertEqual(page.evaluate('[CUR.o,CUR.row]'), [1, 0])
            self.assertTrue(page.locator('[data-action=adopt]').is_disabled())
            page.keyboard.press('ArrowLeft')
            self.settled(page, "CUR.o===0 && CUR.row===24 && SCORE.view.order===0")
            for expected in (12, 8, 4, 0):
                page.keyboard.press('ArrowLeft')
                self.assertEqual(page.evaluate('[CUR.o,CUR.row,CUR.ch]'), [0, expected, 1])
            page.keyboard.press('ArrowLeft')
            self.assertEqual(page.evaluate('[CUR.o,CUR.row]'), [0, 0])
            page.fill('[data-ui=at]', '0')
            page.keyboard.press('ArrowRight')
            page.keyboard.press('ArrowLeft')
            self.assertEqual(page.evaluate('[CUR.o,CUR.row]'), [0, 0])
            self.assertEqual((folder / 'song.yaml').read_bytes(), before)
            self.assertEqual(state.text_sha(), revision)
            self.assertEqual(state.score_view()['raw_positions'], raw)
            self.assertEqual((state.history, state.future), ([], []))

    def test_track_notation_and_beat_stem_reach_renderer_without_retuning(self):
        with self.muted_page(SONG) as (page, state, folder):
            self.open_tab(page)
            self.capture_engraving(page)
            played = state.pattern_rows(0, occurrence='occ-verse')['rows']
            self.open_setup(page)
            self.assertTrue(page.locator('[data-ui=name]').evaluate('(e) => e.readOnly'))
            page.fill('[data-ui=display-name]', 'Lead guitar')
            page.fill('[data-ui=color]', '#2468ac')
            page.fill('[data-ui=key-fifths]', '-3')
            page.select_option('[data-ui=key-mode]', 'minor')
            page.select_option('[data-ui=track-stem]', 'down')
            for clef, enum_name in [('bass', 'F4'), ('alto', 'C3'), ('tenor', 'C4'), ('percussion', 'Neutral'), ('treble', 'G2')]:
                page.select_option('[data-ui=clef]', clef)
                page.click('.vt-tab-setup button[type=submit]')
                self.settled(page, f"SCORE.view.score.tracks.guitar.clef === '{clef}'")
                page.wait_for_function(f"tabRendered.tracks[0].staves[0].bars[0].clef === alphaTab.model.Clef.{enum_name}")
                self.assertNotIn('rendering failed', page.inner_text('.vt-tab-status'))
            self.assertEqual(page.evaluate("[tabRendered.tracks[0].name,tabRendered.tracks[0].staves[0].bars[0].keySignature,tabRendered.tracks[0].staves[0].bars[0].keySignatureType]"), ['Lead guitar', -3, 1])
            self.assertEqual(page.evaluate("tabRendered.tracks[0].color.rgba.toLowerCase()"), '#2468ac')
            self.assertEqual(page.inner_text('[data-ui=track] option:checked'), 'Lead guitar')
            page.click('[data-action=close-setup]')
            page.click('.vt-tab-grid [data-note="note-a"]')
            for selected, expected in [('up', 0), ('auto', None), ('inherit', 1)]:
                page.select_option('[data-ui=beat-stem]', selected)
                page.click('[data-action=beat-stem]')
                condition = "!('stem' in SCORE.view.score.patterns.verse.beats[0])" if selected == 'inherit' else f"SCORE.view.score.patterns.verse.beats[0].stem === '{selected}'"
                self.settled(page, condition)
                self.assertEqual(page.evaluate('tabRendered.tracks[0].staves[0].bars[0].voices[0].beats[0].preferredBeamDirection'), expected)
            self.assertEqual(state.pattern_rows(0, occurrence='occ-verse')['rows'], played)

    def test_enharmonic_spelling_renderer_undo_and_invalid_spelling(self):
        song = SONG.replace('pitch: 64, string: 1, fret: 0', 'pitch: 66, string: 1, fret: 2')
        with self.page(song) as (page, state, folder):
            self.open_tab(page)
            self.capture_engraving(page)
            played = state.pattern_rows(0, occurrence='occ-verse')['rows']
            page.click('.vt-tab-grid [data-note="note-a"]')
            page.keyboard.press('e')
            self.settled(page, "SCORE.view.score.patterns.verse.beats[0].notes[0].spelling?.step === 'G'")
            self.assertEqual(state.song['score']['patterns']['verse']['beats'][0]['notes'][0]['spelling'], {'step': 'G', 'alter': -1})
            self.assertEqual(page.evaluate('tabRendered.tracks[0].staves[0].bars[0].voices[0].beats[0].notes.map(n=>[n.accidentalMode,n.realValue,n.string,n.fret])'), [[5, 66, 2, 2]])
            page.keyboard.press('e')
            self.settled(page, "SCORE.view.score.patterns.verse.beats[0].notes[0].spelling?.step === 'F'")
            self.assertEqual(page.evaluate('tabRendered.tracks[0].staves[0].bars[0].voices[0].beats[0].notes[0].accidentalMode'), 3)
            page.keyboard.press('Control+z')
            self.settled(page, "SCORE.view.score.patterns.verse.beats[0].notes[0].spelling?.step === 'G'")
            page.select_option('[data-ui=spelling-alter]', '2')
            page.select_option('[data-ui=spelling-step]', 'E')
            page.click('[data-action=spelling]')
            self.settled(page, "SCORE.view.score.patterns.verse.beats[0].notes[0].spelling?.alter === 2")
            self.assertEqual(page.evaluate('tabRendered.tracks[0].staves[0].bars[0].voices[0].beats[0].notes[0].accidentalMode'), 4)
            before, history = (folder / 'song.yaml').read_bytes(), len(state.history)
            page.select_option('[data-ui=spelling-alter]', '1')
            page.select_option('[data-ui=spelling-step]', 'C')
            page.click('[data-action=spelling]')
            page.wait_for_function("!EDQ.n && document.querySelector('.vt-tab-status').textContent.includes('spelling does not match pitch')")
            self.assertEqual(((folder / 'song.yaml').read_bytes(), len(state.history)), (before, history))
            page.select_option('[data-ui=spelling-alter]', 'auto')
            page.click('[data-action=spelling]')
            self.settled(page, '!SCORE.view.score.patterns.verse.beats[0].notes[0].spelling')
            self.assertEqual(page.evaluate('tabRendered.tracks[0].staves[0].bars[0].voices[0].beats[0].notes[0].accidentalMode'), 0)
            page.click('.vt-tab-grid [data-note="note-b"]')
            self.assertFalse(page.locator('[data-ui=spelling-alter] option[value="0"]').evaluate('(e)=>e.disabled || e.matches(":disabled")'), page.locator('[data-ui=spelling-alter]').evaluate('(e)=>e.outerHTML'))
            page.select_option('[data-ui=spelling-alter]', '0')
            page.select_option('[data-ui=spelling-step]', 'D')
            page.click('[data-action=spelling]')
            self.settled(page, "SCORE.view.score.patterns.verse.beats[1].notes[0].spelling?.step === 'D'")
            self.assertEqual(page.evaluate('tabRendered.tracks[0].staves[0].bars[0].voices[0].beats.flatMap(b=>b.notes).at(-1).accidentalMode'), 2)
            self.assertEqual(state.pattern_rows(0, occurrence='occ-verse')['rows'], played)
            self.assertNotIn('rendering failed', page.inner_text('.vt-tab-status'))

    def test_duration_plus_minus_clear_dots_keep_tuplet_and_undo(self):
        with self.page(SONG) as (page, state, folder):
            self.open_tab(page)
            page.click('.vt-tab-grid [data-note="note-a"]')
            page.select_option('[data-ui=dots]', '1')
            page.click('[data-action=duration]')
            self.settled(page, 'SCORE.view.score.patterns.verse.beats.find(b=>b.id===`beat-a`).written.dots === 1')
            page.locator('#tab-editor').focus()
            page.keyboard.press('+')
            self.settled(page, 'SCORE.view.score.patterns.verse.beats.find(b=>b.id===`beat-a`).written.value === 4')
            self.assertEqual(next(b for b in state.song['score']['patterns']['verse']['beats'] if b['id'] == 'beat-a')['written'], {'value': 4, 'dots': 0, 'tuplet': [3, 2]})
            page.keyboard.press('-')
            self.settled(page, 'SCORE.view.score.patterns.verse.beats.find(b=>b.id===`beat-a`).written.value === 8')
            self.assertEqual(next(b for b in state.song['score']['patterns']['verse']['beats'] if b['id'] == 'beat-a')['written'], {'value': 8, 'dots': 0, 'tuplet': [3, 2]})
            page.keyboard.press('Control+z')
            self.settled(page, 'SCORE.view.score.patterns.verse.beats.find(b=>b.id===`beat-a`).written.value === 4')
            page.keyboard.press('Control+z')
            self.settled(page, 'SCORE.view.score.patterns.verse.beats.find(b=>b.id===`beat-a`).written.dots === 1')
            # Out-of-range commands are no-ops and do not clear draft dots.
            before, history = (folder / 'song.yaml').read_bytes(), len(state.history)
            page.select_option('[data-ui=duration]', '1')
            page.click('[data-action=longer]')
            self.assertEqual(page.input_value('[data-ui=dots]'), '1')
            page.select_option('[data-ui=duration]', '64')
            page.click('[data-action=shorter]')
            self.assertEqual(page.input_value('[data-ui=dots]'), '1')
            self.assertEqual(((folder / 'song.yaml').read_bytes(), len(state.history)), (before, history))

    def test_track_delete_refuses_used_then_explicit_removal_preserves_raw_and_undo(self):
        mixed = TIE_SONG.replace('00: ... .. ... D07 | ... .. ... ...',
            '00: ... .. ... D07 | C-5 01 ... ...\n'
            '      01: ... .. ... ... | ... .. ... ...\n'
            '      02: ... .. ... ... | ... .. ... ...\n'
            '      03: ... .. ... ... | ... .. ... ...\n'
            '      04: ... .. ... ... | === .. ... ...')
        with self.muted_page(mixed) as (page, state, folder):
            self.open_tab(page)
            page.click('.vt-tab-grid [data-note="note-b"]')
            page.keyboard.press('l')
            self.settled(page, 'SCORE.view.score.ties.length === 1')
            before = (folder / 'song.yaml').read_bytes()
            self.open_setup(page)
            page.click('[data-action=delete-track]')
            page.wait_for_function("!EDQ.n && document.querySelector('.vt-tab-status').textContent.includes('track contains')")
            self.assertEqual((folder / 'song.yaml').read_bytes(), before)
            page.check('[data-ui=remove-notes]')
            page.click('[data-action=delete-track]')
            self.settled(page, 'Object.keys(SCORE.view.score.tracks).length === 0')
            self.assertEqual(state.song['score']['patterns']['verse']['beats'], [])
            self.assertEqual(state.song['score']['ties'], [])
            self.assertEqual(state.mod.patterns[0].rows[0][1].note, 60)
            self.assertIn('D07', state.pattern_rows(0, occurrence='occ-verse')['rows'][0][0])   # the view needs a played occurrence
            self.assertEqual(len(state.song['module']['channels']), 2)
            self.assertIn(1, state.song['samples'])
            page.locator('#tab-editor').focus()
            page.keyboard.press('Control+z')
            self.settled(page, 'SCORE.view.score.ties.length === 1 && SCORE.view.score.tracks.guitar')
            page.wait_for_selector('.vt-tab-score svg')
            self.assertEqual((folder / 'song.yaml').read_bytes(), before)
            # Use the actual transport: its regular stopped-position refresh
            # correctly clears synthetic playheads injected while stopped.
            page.keyboard.press('F6')
            page.wait_for_function('LV.playing && LV.pos')
            page.wait_for_selector('.vt-tab-playhead:not([hidden])')
            page.keyboard.press('Escape')
            page.wait_for_function('!LV.playing')

    def test_exact_measure_edit_refusal_delete_and_unmetered_remainder(self):
        with self.page(SONG) as (page, state, folder):
            self.open_tab(page)
            self.capture_engraving(page)
            played = state.pattern_rows(0, occurrence='occ-verse')['rows']
            self.open_panel(page, 'measures')
            page.fill('[data-ui=measure-from]', '0')
            page.fill('[data-ui=measure-to]', '1')
            page.click('.vt-tab-measures button[type=submit]')
            self.settled(page, 'SCORE.view.score.measures?.length === 1')
            measure = state.song['score']['measures'][0]
            self.assertEqual(measure['from'], {'occurrence': 'occ-verse', 'at': [0, 1]})
            self.assertEqual(measure['to'], {'occurrence': 'occ-verse', 'at': [1, 1]})
            self.assertEqual(measure['meter'], [1, 4])
            self.assertIn('unmetered display groups', page.inner_text('.vt-tab-meter'))
            self.assertEqual(page.evaluate('tabRendered.tracks[0].staves[0].bars.flatMap(b=>b.voices.flatMap(v=>v.beats)).filter(b=>b.notes.length).length'), 2)
            self.assertEqual(page.evaluate('tabRendered.masterBars.map(b=>[b.timeSignatureNumerator,b.timeSignatureDenominator])'), [[1, 4], [4, 4]])
            # A note beyond the authored measure remains engraved and follows playback.
            page.evaluate('SCORE.editor.setPlayhead({o:0,row:12})')
            page.wait_for_function("document.querySelector('.vt-tab-playhead')?.dataset.at === '1/1'")
            before = (folder / 'song.yaml').read_bytes()
            page.fill('[data-ui=meter-n]', '2')
            page.click('.vt-tab-measures button[type=submit]')
            page.wait_for_function("!EDQ.n && document.querySelector('.vt-tab-status').textContent.includes('exact span')")
            self.assertEqual((folder / 'song.yaml').read_bytes(), before)
            page.fill('[data-ui=measure-to]', '2')
            page.click('.vt-tab-measures button[type=submit]')
            self.settled(page, 'SCORE.view.score.measures[0].meter[0] === 2')
            self.assertEqual(state.song['score']['measures'][0]['id'], measure['id'])
            self.assertEqual(state.pattern_rows(0, occurrence='occ-verse')['rows'], played)
            page.click('[data-action=delete-measure]')
            self.settled(page, 'SCORE.view.score.measures.length === 0')
            self.assertIn('unmetered display groups', page.inner_text('.vt-tab-meter'))
            page.locator('#tab-editor').focus()
            page.keyboard.press('Control+z')
            self.settled(page, 'SCORE.view.score.measures.length === 1')
            self.assertEqual(state.song['score']['measures'][0]['meter'], [2, 4])

    def test_actual_ord_new_retains_occurrence_identity_and_undo(self):
        with self.page(SONG) as (page, state, folder):
            self.open_tab(page)
            before = (folder / 'song.yaml').read_bytes()
            page.evaluate('ORD_SEL=0;ordNew()')
            page.wait_for_function('!EDQ.n && ordList().length === 2')
            new_name = state.song['orders'][1]
            self.assertIn(new_name, state.song['patterns'])
            self.assertEqual(state.song['score']['order_ids'][0], 'occ-verse')
            self.assertEqual(len(set(state.song['score']['order_ids'])), 2)
            page.locator('#tab-editor').focus()
            page.keyboard.press('Control+z')
            self.settled(page, 'SCORE.view.score.order_ids.length === 1')
            self.assertEqual((folder / 'song.yaml').read_bytes(), before)

    def test_fret_chord_duration_pattern_history_and_reload(self):
        with self.page(SONG) as (page, state, folder):
            self.open_tab(page)
            self.assertEqual(page.input_value('[data-ui=tuple-n]'), '3')
            page.click('.vt-tab-grid [data-string="1"][data-at="0/1"]')
            page.keyboard.type('12')
            # Digits commit immediately and combine even while the first save is pending.
            self.settled(page, "SCORE.view.score.patterns.verse.beats.find(b=>b.id===`beat-a`).notes[0].fret === 12")
            self.assertEqual(next(b for b in state.song['score']['patterns']['verse']['beats'] if b['id'] == 'beat-a')['notes'][0]['pitch'], 76)
            page.click('.vt-tab-grid [data-string="2"][data-at="0/1"]')
            page.keyboard.type('1')
            self.settled(page, "SCORE.view.score.patterns.verse.beats.find(b=>b.id===`beat-a`).notes.length === 2")
            self.assertEqual(len(next(b for b in state.song['score']['patterns']['verse']['beats'] if b['id'] == 'beat-a')['notes']), 2)
            page.click('[data-action=chord]')
            page.select_option('[data-ui=duration]', '8')
            page.fill('[data-ui=tuple-n]', '1')
            page.fill('[data-ui=tuple-d]', '1')
            page.click('[data-action=duration]')
            self.settled(page, "SCORE.view.score.patterns.verse.beats.find(b=>b.id===`beat-a`).written.tuplet[0] === 1")
            self.assertIn('D07', (folder / 'song.yaml').read_text(encoding='utf-8'))
            page.locator('#tab-editor').focus()
            page.keyboard.press('Control+z')
            self.settled(page, "SCORE.view.score.patterns.verse.beats.find(b=>b.id===`beat-a`).written.tuplet[0] === 3")
            page.keyboard.press('Control+y')
            self.settled(page, "SCORE.view.score.patterns.verse.beats.find(b=>b.id===`beat-a`).written.tuplet[0] === 1")
            # Change the same source event through Pattern; TAB must follow its pitch/fingering.
            page.evaluate("tab('pattern');setEdit(true);showPattern(0)")
            page.wait_for_function('PAT.rows && PAT.order === 0')
            page.evaluate("const c=cellOf(PAT.rows[0][1]);c.n='D-5';patEdit([{row:0,ch:1,cell:cellText(c)}])")
            page.wait_for_function("!EDQ.n && PAT.rows[0][1].startsWith('D-5')")
            page.evaluate("tab('tab')")
            self.settled(page, "SCORE.view.score.patterns.verse.beats.find(b=>b.id===`beat-a`).notes.some(n=>n.pitch===62)")
            page.reload()
            page.wait_for_function('S && S.song && S.song.facts')
            self.open_tab(page)
            self.assertIn('D07', (folder / 'song.yaml').read_text(encoding='utf-8'))
            # After reload the optional grid is collapsed again (hidden text reads ''); check its content.
            self.assertEqual(page.text_content('.vt-tab-grid [data-string="2"][data-at="0/1"]'), '3')

    def test_refused_duration_recovers_and_playhead_is_shared(self):
        from tests.test_tablature import beat
        source = api.from_yaml(SONG)
        source['patterns']['verse']['rows'] = 24
        source['score']['patterns']['verse']['beats'].insert(1, beat('gap', [1,3], [], value=4, tuplet=[3,2]))
        source['score']['measures'] = [dict(id='bar', meter=[2,4], **{
            'from': dict(occurrence='occ-verse', at=[0,1]), 'to': dict(occurrence='occ-verse', at=[2,1])})]
        with self.page(api.to_yaml(source)) as (page, state, folder):
            page.evaluate("tab('tab')")
            page.wait_for_selector('.vt-tab-grid [data-note="note-b"]')
            page.wait_for_selector('.vt-tab-score svg')
            before = (folder / 'song.yaml').read_bytes()
            page.click('.vt-tab-grid [data-note="note-b"]')
            page.select_option('[data-ui=duration]', '1')
            page.click('[data-action=duration]')
            self.settled(page, "document.querySelector('.vt-tab-status').textContent.includes('unchanged')")
            self.assertEqual((folder / 'song.yaml').read_bytes(), before)
            page.select_option('[data-ui=duration]', '8')
            page.click('[data-action=duration]')
            self.settled(page, "SCORE.view.score.patterns.verse.beats.find(b=>b.id===`beat-b`).written.value === 8")
            # The page's 100 ms follow tick would replace this hand-set playhead with the stopped transport's (none).
            page.evaluate('followScorePlayhead=()=>{}')
            page.evaluate("SCORE.editor.setPlayhead({o:0,row:12})")
            self.assertIn('playing', page.get_attribute('.vt-tab-grid [data-note="note-b"]', 'class'))
            page.wait_for_selector('.vt-tab-playhead:not([hidden])')
            self.assertEqual(page.get_attribute('.vt-tab-playhead', 'data-at'), '1/1')
            marker = page.locator('.vt-tab-playhead').bounding_box()
            surface = page.locator('.vt-tab-score .at-surface').bounding_box()
            self.assertGreater(marker['height'], 0)
            self.assertGreater(marker['x'], surface['x'])
            self.assertLess(marker['x'], surface['x'] + surface['width'])
            page.evaluate("SCORE.editor.setPlayhead({o:0,row:0})")
            self.assertEqual(page.get_attribute('.vt-tab-playhead', 'data-at'), '0/1')
            self.assertLess(page.locator('.vt-tab-playhead').bounding_box()['x'], marker['x'])
            # The shared position also marks engraved rests between authored beats.
            page.evaluate("SCORE.editor.setPlayhead({o:0,row:4})")
            self.assertEqual(page.get_attribute('.vt-tab-playhead', 'data-at'), '1/3')
            self.assertEqual(page.locator('.vt-tab-grid .playing[data-note]:not([data-note=""])').count(), 0)
            page.evaluate("SCORE.editor.setPlayhead({o:1,row:0})")
            self.assertTrue(page.is_hidden('.vt-tab-playhead'))
            self.assertEqual(page.evaluate('[CUR.o,CUR.row,CUR.ch]'), [0, 12, 1])
            page.evaluate('SCORE.editor.setPlayhead(null)')
            self.assertEqual(page.locator('.vt-tab-grid .playing').count(), 0)
            self.assertTrue(page.is_hidden('.vt-tab-playhead'))

    def test_first_track_setup_preserves_existing_pattern_cells(self):
        with self.page(SONG.split('score:\n')[0]) as (page, state, folder):
            page.evaluate("tab('tab')")
            page.wait_for_function('SCORE.editor && SCORE.view')
            self.open_setup(page)
            page.fill('[data-ui=tuning]', '64,59')
            page.uncheck('[data-ui=auto-channels]')
            page.fill('[data-ui=channels]', '1,2')
            page.click('.vt-tab-setup button[type=submit]')
            self.settled(page, "SCORE.view.score?.tracks?.guitar")
            self.assertEqual(state.song['score']['tracks']['guitar']['channels'], [0, 1])
            self.assertIn('D07', (folder / 'song.yaml').read_text(encoding='utf-8'))

    def test_roll_length_resizes_whole_score_chord(self):
        with self.page(SONG) as (page, state, folder):
            self.open_tab(page)
            page.click('.vt-tab-grid [data-string="2"][data-at="0/1"]')
            page.keyboard.type('1')
            self.settled(page, "SCORE.view.score.patterns.verse.beats[0].notes.length === 2")
            original_ids = [n['id'] for n in state.song['score']['patterns']['verse']['beats'][0]['notes']]
            page.evaluate("tab('pattern');setEdit(true);showPattern(0)")
            page.wait_for_function("PAT.rows && PAT.score_positions?.filter(p=>p.kind==='note' && p.beat==='beat-a').length === 2 && PAT.revision")
            # Exercise the actual roll resize entry point, not a direct score API call.
            page.evaluate("setCursor(0,0,0,0);if(!ROLL.on)rollToggle();rollLength(0,6)")
            page.wait_for_function("!EDQ.n && PAT.score_positions?.filter(p=>p.kind==='note' && p.beat==='beat-a' && scoreRowNumber(p.end_row)===6).length === 2")
            beat = state.song['score']['patterns']['verse']['beats'][0]
            self.assertEqual([n['id'] for n in beat['notes']], original_ids)
            self.assertEqual(beat['written'], {'value': 8, 'dots': 0, 'tuplet': [1, 1]})
            self.assertIn('D07', (folder / 'song.yaml').read_text(encoding='utf-8'))
            page.evaluate("tab('tab')")
            self.settled(page, "SCORE.view.positions.filter(p=>p.kind==='note' && p.beat==='beat-a' && scoreRowNumber(p.end_row)===6).length === 2")
            page.locator('#tab-editor').focus()
            page.keyboard.press('Control+z')
            self.settled(page, "SCORE.view.positions.filter(p=>p.kind==='note' && p.beat==='beat-a' && scoreRowNumber(p.end_row)===4).length === 2")
            self.assertEqual(len(state.song['score']['patterns']['verse']['beats'][0]['notes']), 2)

    def test_numeric_fret_timeout_maximum_and_string_context(self):
        with self.muted_page(SONG) as (page, state, folder):
            self.open_tab(page)
            page.click('.vt-tab-grid [data-note="note-a"]')
            page.keyboard.type('12')
            self.settled(page, "SCORE.view.score.patterns.verse.beats[0].notes[0].fret === 12")
            page.keyboard.type('3')  # A preceding two-digit fret starts a new number.
            self.settled(page, "SCORE.view.score.patterns.verse.beats[0].notes[0].fret === 3")
            page.keyboard.type('0')  # 30 exceeds default maximum 29, so this is open string.
            self.settled(page, "SCORE.view.score.patterns.verse.beats[0].notes[0].fret === 0")
            page.keyboard.type('1')
            self.settled(page, "SCORE.view.score.patterns.verse.beats[0].notes[0].fret === 1")
            page.wait_for_timeout(1100)  # Exercise the actual source-defined timeout.
            page.keyboard.type('2')
            self.settled(page, "SCORE.view.score.patterns.verse.beats[0].notes[0].fret === 2")
            page.keyboard.press('ArrowDown')
            page.keyboard.type('1')
            self.settled(page, "SCORE.view.score.patterns.verse.beats[0].notes.some(n=>n.string===2 && n.fret===1)")
            self.assertEqual([n['fret'] for n in state.song['score']['patterns']['verse']['beats'][0]['notes']], [2, 1])

    def test_semitone_and_adjacent_string_preserve_note_identity(self):
        with self.page(SONG) as (page, state, folder):
            self.open_tab(page)
            page.click('.vt-tab-grid [data-note="note-a"]')
            page.keyboard.press('Shift+ArrowRight')
            self.settled(page, "SCORE.view.score.patterns.verse.beats[0].notes[0].pitch === 65")
            self.assertEqual(state.song['score']['patterns']['verse']['beats'][0]['notes'][0]['fret'], 1)
            page.keyboard.press('Shift+ArrowDown')
            self.settled(page, "SCORE.view.score.patterns.verse.beats[0].notes[0].string === 2")
            note = state.song['score']['patterns']['verse']['beats'][0]['notes'][0]
            self.assertEqual((note['id'], note['pitch'], note['fret']), ('note-a', 65, 6))
            self.assertEqual(page.evaluate('CUR.ch'), 1)
            page.keyboard.press('Control+z')
            self.settled(page, "SCORE.view.score.patterns.verse.beats[0].notes[0].string === 1")

    def test_tie_toggle_removes_continuation_attack_and_restores_it(self):
        with self.page(TIE_SONG) as (page, state, folder):
            self.open_tab(page)
            page.click('.vt-tab-grid [data-note="note-b"]')
            page.keyboard.press('l')
            self.settled(page, 'SCORE.view.score.ties.length === 1')
            from vulturetracker.notation import parse_cell
            attack = lambda: parse_cell(state.pattern_rows(0, occurrence='occ-verse')['display_rows'][4][0]).note
            self.assertIsNone(attack())   # the Pattern view's row 4: a tied continuation has no attack
            self.assertEqual(state.song['score']['ties'][0], {
                'from': {'occurrence': 'occ-verse', 'note': 'note-a'},
                'to': {'occurrence': 'occ-verse', 'note': 'note-b'}})
            page.keyboard.press('l')
            self.settled(page, 'SCORE.view.score.ties.length === 0')
            self.assertEqual(attack(), 64)

    def test_actual_roll_move_preserves_note_id_and_undo(self):
        with self.page(SONG) as (page, state, folder):
            self.open_tab(page)
            page.evaluate("tab('pattern');setEdit(true);showPattern(0)")
            page.wait_for_function("PAT.rows && PAT.score_positions?.some(p=>p.note==='note-a') && PAT.revision")
            page.evaluate("setCursor(0,0,0,0);if(!ROLL.on)rollToggle();rollMove(0,6,65)")
            page.wait_for_function("!EDQ.n && PAT.rows[0][0].startsWith('...') && PAT.rows[6][0].startsWith('F-5')")
            # Native notes play from the score plan, not module cells: check the displayed rows.
            self.assertEqual([state.pattern_rows(0, occurrence='occ-verse')['display_rows'][r][0][:3] for r in (0, 6)], ['...', 'F-5'])
            notes = [(b, n) for b in state.song['score']['patterns']['verse']['beats'] for n in b['notes'] if n['id'] == 'note-a']
            self.assertEqual(len(notes), 1)
            self.assertEqual((notes[0][0]['at'], notes[0][1]['pitch']), ([1, 2], 65))
            self.assertIn('D07', (folder / 'song.yaml').read_text(encoding='utf-8'))
            page.evaluate("tab('tab')")
            self.settled(page, "SCORE.view.positions.some(p=>p.note==='note-a' && scoreRowNumber(p.row)===6)")
            page.locator('#tab-editor').focus()
            page.keyboard.press('Control+z')
            self.settled(page, "SCORE.view.positions.some(p=>p.note==='note-a' && scoreRowNumber(p.row)===0)")
            self.assertEqual([state.pattern_rows(0, occurrence='occ-verse')['display_rows'][r][0][:3] for r in (0, 6)], ['E-5', '...'])

    def test_actual_horizontal_roll_move_preserves_whole_chord(self):
        with self.page(SONG) as (page, state, folder):
            self.open_tab(page)
            page.click('.vt-tab-grid [data-string="2"][data-at="0/1"]')
            page.keyboard.type('1')
            self.settled(page, "SCORE.view.score.patterns.verse.beats[0].notes.length === 2")
            original = json.loads(json.dumps(state.song['score']['patterns']['verse']['beats'][0]))
            page.evaluate("tab('pattern');setEdit(true);showPattern(0)")
            page.wait_for_function("PAT.rows && PAT.score_positions?.filter(p=>p.kind==='note' && p.beat==='beat-a').length === 2 && PAT.revision")
            page.evaluate("setCursor(0,0,0,0);if(!ROLL.on)rollToggle();rollMove(0,6,64)")
            page.wait_for_function("!EDQ.n && PAT.score_positions?.filter(p=>p.kind==='note' && p.beat==='beat-a' && scoreRowNumber(p.row)===6).length === 2")
            moved = state.song['score']['patterns']['verse']['beats'][0]
            self.assertEqual(moved, dict(original, at=[1, 2]))
            self.assertEqual([state.pattern_rows(0, occurrence='occ-verse')['display_rows'][0][ch][:3] for ch in (0, 1)], ['...', '...'])
            self.assertEqual([state.pattern_rows(0, occurrence='occ-verse')['display_rows'][6][ch][:3] for ch in (0, 1)], ['E-5', 'C-5'])
            self.assertIn('D07', state.pattern_rows(0, occurrence='occ-verse')['display_rows'][0][0])
            page.evaluate("tab('tab')")
            self.settled(page, "SCORE.view.positions.filter(p=>p.kind==='note' && p.beat==='beat-a' && scoreRowNumber(p.row)===6).length === 2")
            page.locator('#tab-editor').focus()
            page.keyboard.press('Control+z')
            self.settled(page, "SCORE.view.positions.filter(p=>p.kind==='note' && p.beat==='beat-a' && scoreRowNumber(p.row)===0).length === 2")
            self.assertEqual(state.song['score']['patterns']['verse']['beats'][0], original)
            self.assertEqual([state.pattern_rows(0, occurrence='occ-verse')['display_rows'][6][ch][:3] for ch in (0, 1)], ['...', '...'])

    def test_copy_chord_and_selected_beats_paste_fresh_ids_and_undo(self):
        with self.page(SONG.replace('rows: 25', 'rows: 49')) as (page, state, folder):
            self.open_tab(page)
            page.click('.vt-tab-grid [data-string="2"][data-at="0/1"]')
            page.keyboard.type('1')
            self.settled(page, "SCORE.view.score.patterns.verse.beats[0].notes.length === 2")
            original = json.loads(json.dumps(state.song['score']['patterns']['verse']['beats']))
            page.click('.vt-tab-grid [data-note="note-a"]')
            page.click('.vt-tab-grid [data-note="note-b"]', modifiers=['Control'])
            # The clicked strings' notes are shown selected; Copy still takes their whole beats.
            self.assertEqual(page.locator('.vt-tab-grid .copy-selected').count(), 2)
            page.keyboard.press('Control+c')
            page.wait_for_function("document.querySelector('.vt-tab-status').textContent.includes('Copied 2 beats')")
            page.fill('[data-ui=at]', '2')
            page.click('[data-action=go]')
            page.click('[data-action=select-none]')
            page.click('[data-action=paste-safe]')
            self.settled(page, "SCORE.view.score.patterns.verse.beats.length === 4")
            pasted = state.song['score']['patterns']['verse']['beats']
            self.assertEqual(pasted[:2], original)
            self.assertEqual([b['at'] for b in pasted[2:]], [[2, 1], [3, 1]])
            self.assertEqual([len(b['notes']) for b in pasted[2:]], [2, 1])
            self.assertEqual(len({b['id'] for b in pasted}), 4)
            self.assertEqual(len({n['id'] for b in pasted for n in b['notes']}), 6)
            for source, copied in zip(original, pasted[2:]):
                self.assertEqual(copied['written'], source['written'])
                self.assertEqual([{k: v for k, v in n.items() if k != 'id'} for n in copied['notes']],
                                 [{k: v for k, v in n.items() if k != 'id'} for n in source['notes']])
            self.assertIn('D07', state.pattern_rows(0, occurrence='occ-verse')['rows'][0][0])   # the view needs a played occurrence
            self.assertNotIn('D07', state.pattern_rows(0, occurrence='occ-verse')['rows'][24][0])
            page.keyboard.press('Control+z')
            self.settled(page, "SCORE.view.score.patterns.verse.beats.length === 2")
            self.assertEqual(state.song['score']['patterns']['verse']['beats'], original)

    def test_existing_pattern_note_is_selectable_without_adoption(self):
        with self.page(RAW_SONG) as (page, state, folder):
            before = (folder / 'song.yaml').read_bytes()
            page.evaluate("tab('tab')")
            page.wait_for_selector('.vt-tab-raw [data-raw-row="0"][data-raw-ch="0"]')
            page.click('.vt-tab-raw [data-raw-row="0"][data-raw-ch="0"]')
            self.assertEqual(page.evaluate('[CUR.o,CUR.row,CUR.ch]'), [0, 0, 0])
            self.assertTrue(page.is_disabled('[data-action=fret]'))
            self.assertIn('notation boundary from raw/score events', page.inner_text('.vt-tab-raw'))   # its note-off ends it
            page.keyboard.type('1')
            self.assertIn('Adopt', page.inner_text('.vt-tab-status'))
            self.assertEqual((folder / 'song.yaml').read_bytes(), before)
            self.assertEqual(state.song['score']['patterns'], {})
            played = state.pattern_rows(0, occurrence='occ-verse')['display_rows']
            page.click('[data-action=adopt]')
            self.settled(page, "SCORE.view.raw_positions.length === 0 && SCORE.view.positions.some(p=>p.kind==='note' && scoreRowNumber(p.row)===0 && p.ch===0)")
            self.assertEqual(state.pattern_rows(0, occurrence='occ-verse')['display_rows'], played)
            adopted = state.song['score']['patterns']['verse']['beats'][0]
            self.assertEqual(adopted['duration_source'], 'tracker_boundary')
            self.assertEqual(adopted['notes'][0]['channel'], 0)
            page.locator('#tab-editor').focus()
            page.keyboard.press('Control+z')
            self.settled(page, "SCORE.view.raw_positions.some(p=>p.row===0 && p.ch===0)")
            self.assertEqual(state.song['score']['patterns'], {})


class TestScoreDeliveryPage(unittest.TestCase):
    """Portable images and PDF use the same paginated score as the preview."""
    page = TestTablaturePage.page
    print_ready = TestTablaturePage.print_ready
    print_url = TestTablaturePage.print_url
    def capture_engraving(self, page):
        page.evaluate("""() => {
          const render = alphaTab.AlphaTabApi.prototype.renderScore;
          alphaTab.AlphaTabApi.prototype.renderScore = function(score, ...args) {
            window.tabRendered = score; return render.call(this, score, ...args);
          };
        }""")

    def export_preview(self, preview, folder, *, native=False):
        """Exercise real Save buttons; replace only the native file chooser endpoint."""
        import base64
        from PIL import Image, ImageFilter, ImageChops
        folder = Path(folder)
        folder.mkdir(parents=True, exist_ok=True)
        count = preview.locator('.vt-print-page').count()
        self.assertGreater(count, 0)
        index = min(1, count - 1)
        preview.select_option('[name=imagePage]', str(index))
        paper = preview.locator('.vt-print-page').nth(index)
        expected = Image.open(io.BytesIO(paper.screenshot())).convert('RGB')
        captured = []
        def save(route):
            body = route.request.post_data_json
            self.assertIn(body['format'], ('svg', 'png', 'jpg', 'bmp'))
            self.assertTrue(body['song'])
            self.assertTrue(body['revision'])
            target = folder / ('score-page.' + body['format'])
            captured.append(body)
            if native:
                route.continue_()
            else:
                target.write_bytes(base64.b64decode(body['data'], validate=True))
                route.fulfill(json={'path': str(target)})
        preview.route('**/api/score_export', save)
        try:
            for fmt in ('svg', 'png', 'jpg', 'bmp'):
                preview.click(f'[data-print={fmt}]')
                preview.wait_for_function("document.querySelector('.vt-print-status').textContent.startsWith('Saved ') || document.querySelector('.vt-print-status').textContent.startsWith('Image export failed')")
                self.assertTrue(preview.inner_text('.vt-print-status').startswith('Saved '), preview.inner_text('.vt-print-status'))
            self.assertEqual([body['format'] for body in captured], ['svg', 'png', 'jpg', 'bmp'])
        finally:
            preview.unroute('**/api/score_export', save)
        svg = (folder / 'score-page.svg').read_text(encoding='utf-8')
        self.assertIn('data:', svg)
        self.assertIn('VTExportMusic', svg)
        self.assertIn('SIL OPEN FONT LICENSE', svg)
        self.assertNotIn('url(/', svg)
        self.assertNotIn('foreignObject', svg)
        image = Image.open(folder / 'score-page.png').convert('RGB')
        for fmt in ('jpg', 'bmp'):
            other = Image.open(folder / ('score-page.' + fmt)).convert('RGB')
            self.assertEqual(other.size, image.size)
            if fmt == 'bmp':
                self.assertIsNone(ImageChops.difference(other,image).getbbox())
            else:
                difference = ImageChops.difference(other,image)
                self.assertLess(sum(v*n for v,n in enumerate(difference.convert('L').histogram()))/(image.width*image.height),2)
        self.assertAlmostEqual(image.width / expected.width, 2, delta=.01)
        self.assertAlmostEqual(image.height / expected.height, 2, delta=.01)
        # Ink overlap detects missing music fonts, shifted systems and empty raster exports.
        def mask(image):
            return image.convert('L').point(lambda v: 255 if v < 150 else 0)
        actual = mask(image.resize(expected.size, Image.Resampling.LANCZOS))
        wanted = mask(expected)
        wanted_ink = sum(wanted.histogram()[128:])
        self.assertGreater(wanted_ink, 1000)
        overlap = ImageChops.multiply(actual.filter(ImageFilter.MaxFilter(3)), wanted)
        self.assertGreater(sum(overlap.histogram()[128:]) / wanted_ink, .92)
        self.assertLess(sum(actual.histogram()[128:]) / wanted_ink, 1.4)
        offline = preview.context.browser.new_page(viewport={'width': expected.width, 'height': expected.height})
        try:
            offline.route('http://**/*', lambda route: route.abort())
            offline.route('https://**/*', lambda route: route.abort())
            offline.goto((folder / 'score-page.svg').resolve().as_uri())
            offline.evaluate('document.fonts.ready')
            self.assertTrue(offline.evaluate("document.fonts.check('20px VTExportMusic')"))
            offline.bring_to_front()
            offline.screenshot(path=str(folder / 'score-svg-offline.png'))
        finally:
            offline.close()
        pdf = preview.pdf(prefer_css_page_size=True, print_background=True)
        (folder / 'score.pdf').write_bytes(pdf)
        self.assertTrue(pdf.startswith(b'%PDF-'))
        self.assertEqual(len(re.findall(rb'/Type /Page\b', pdf)), count)
        print('score delivery:', count, 'PDF pages;', image.size, 'PNG; embedded offline music font')

    def test_selected_tracks_bar_range_portable_svg_png_and_pdf(self):
        with self.page(PRINT_SONG) as (page, state, folder):
            original = state.song_path.read_bytes()
            history = (list(state.history), list(state.future))
            preview = page.context.browser.new_page()
            try:
                preview.goto(self.print_url(page, state)); self.print_ready(preview)
                self.capture_engraving(preview)
                preview.select_option('[name=breaks]', ['1', '2'])
                preview.click('button[type=submit]'); self.print_ready(preview)
                self.assertEqual(preview.locator('.vt-print-page').count(), 3)
                output = Path(os.environ.get('VT_SCORE_DELIVERY_EVIDENCE', folder / 'exports')).resolve()
                from vulturetracker import server
                window = mock.Mock()
                window.create_file_dialog.side_effect = [(str(output / ('score-page.'+fmt)),) for fmt in ('svg','png','jpg','bmp')]
                with mock.patch.dict(sys.modules, {'webview': SimpleNamespace(SAVE_DIALOG=30)}), \
                     mock.patch.object(server.Handler, 'window', window):
                    self.export_preview(preview, output, native=True)
                self.assertEqual(window.create_file_dialog.call_count, 4)
                preview.uncheck('[name=track][value=bass]')
                preview.fill('[name=first]', '2'); preview.fill('[name=last]', '3')
                self.assertTrue(preview.is_disabled('[data-print=svg]'))
                preview.click('button[type=submit]'); self.print_ready(preview)
                self.assertEqual(preview.evaluate('tabRendered.tracks.map(t=>t.name)'), ['Lead guitar'])
                self.assertEqual(preview.evaluate('tabRendered.masterBars.map(b=>b.timeSignatureNumerator)'), [2, 8])
                self.assertIn('Source bars 2', preview.inner_text('.vt-print-pages'))
                self.assertEqual(preview.locator('.vt-print-page').count(), 2)
                self.assertIn('Bars 2', preview.inner_text('.vt-print-status'))
                preview.fill('[name=first]', '3'); preview.fill('[name=last]', '2')
                preview.click('button[type=submit]')
                self.assertIn('first bar must not follow', preview.inner_text('.vt-print-status'))
                self.assertTrue(preview.is_disabled('[data-print=png]'))
                self.assertEqual(state.song_path.read_bytes(), original)
                self.assertEqual((state.history, state.future), history)
            finally:
                preview.close()


@unittest.skipIf(page_fixture.sync_playwright is None, 'playwright not installed')
class TestCompleteSongClipboardPage(unittest.TestCase):
    """Copy/Paste controls retain a portable phrase across track and song changes."""
    page = TestTablaturePage.page
    muted_page = TestTablaturePage.muted_page
    settled = TestTablaturePage.settled
    capture_engraving = TestTablaturePage.capture_engraving
    click_tab_lane = TestTablaturePage.click_tab_lane
    tab_lane_point = staticmethod(TestTablaturePage.tab_lane_point)

    def run_portable_edits(self, page, song_path, dest_path):
        original, destination_original = song_path.read_bytes(), dest_path.read_bytes()
        errors = []
        page.on('pageerror', lambda error: errors.append(error.stack or str(error)))
        page.evaluate("tab('tab');setEdit(true)")
        page.wait_for_selector('[data-ui=track]', state='attached')
        self.capture_engraving(page)

        def prepare(track):
            page.select_option('[data-ui=track]', track)
            if page.locator('.vt-tab-inspector').get_attribute('open') is None:
                page.locator('.vt-tab-inspector > summary').click()
            self.settled(page, 'window.tabRendered&&tabRenderedRevision===SCORE.view.revision&&tabRenderApi.boundsLookup?.isFinished')

        def paste(track, path, expected):
            prepare(track)
            self.click_tab_lane(page, 0, 0, 2)
            self.settled(page, 'SCORE.view.order===0')
            before_revision = page.evaluate('SCORE.view.revision')
            with page.expect_response('**/api/score') as response:
                page.click('[data-action=paste-span]')
            result = response.value.json()
            self.assertTrue(result.get('ok'), result)
            self.assertEqual(result['selection']['track'], track)
            self.assertEqual(len(result['selection']['range']), 4)
            self.settled(page, 'SCORE.view.revision===' + json.dumps(result['revision']))
            self.assertIn('Pasted phrase selected', page.inner_text('.vt-tab-status'))
            self.assertGreater(page.locator('.vt-tab-selection').count(), 15)
            current = api.from_yaml(path.read_text(encoding='utf-8'))
            beats = [b for p in current['score']['patterns'].values() for b in p['beats'] if b['track'] == track]
            self.assertEqual({b['voice'] for b in beats}, {0, 1})
            self.assertEqual(len(beats), 19)
            self.assertTrue(all('instrument' not in n and 'channel' not in n for b in beats for n in b['notes']))
            self.assertEqual(current['score']['tracks'][track]['instrument'], expected)
            saved = path.read_bytes()
            page.click('[data-action=undo]')
            self.settled(page, 'SCORE.view.revision===' + json.dumps(before_revision))
            page.click('[data-action=redo]')
            self.settled(page, 'SCORE.view.revision===' + json.dumps(result['revision']))
            self.assertEqual(path.read_bytes(), saved)
            page.click('[data-action=undo]')
            self.settled(page, 'SCORE.view.revision===' + json.dumps(before_revision))

        prepare('guitar')
        self.click_tab_lane(page, 0, 0, 2)
        page.keyboard.down('Shift')
        try:
            self.click_tab_lane(page, 3, 3, 2)
        finally:
            page.keyboard.up('Shift')
        self.settled(page, 'SCORE.view.order===3&&document.querySelectorAll(".vt-tab-selection").length>15')
        page.click('[data-action=copy]')
        page.wait_for_function("document.querySelector('.vt-tab-status').textContent.startsWith('Copied 19')")
        paste('reply', song_path, 2)
        self.assertEqual(song_path.read_bytes(), original)
        # Open song is a navigation boundary; the user's next edit is still the real Paste control.
        page.evaluate('async path=>{await openSong(path)}', str(dest_path))
        page.evaluate("tab('tab');setEdit(true)")
        page.wait_for_function("SCORE.view?.score?.tracks?.part")
        self.assertFalse(page.is_disabled('[data-action=paste]'))
        paste('part', dest_path, 7)
        self.assertEqual(dest_path.read_bytes(), destination_original)
        self.assertEqual(song_path.read_bytes(), original)
        page.evaluate('async path=>{await openSong(path)}', str(song_path))
        page.evaluate("tab('tab');setEdit(true)")
        page.wait_for_function("SCORE.view?.score?.tracks?.guitar")
        prepare('guitar')
        self.assertFalse(errors, errors)

    def test_cross_track_and_cross_song_real_copy_paste_and_history(self):
        from tests.test_tablature_sync import TestCompleteSongClipboardState
        source, destination = TestCompleteSongClipboardState.song_pair()
        with self.muted_page(api.to_yaml(source), width=1920, height=1080) as (page, state, folder):
            self.assertFalse(state.error, state.error)
            dest = folder / 'destination.yaml'
            dest.write_text(api.to_yaml(destination), encoding='utf-8', newline='\n')
            self.run_portable_edits(page, folder / 'song.yaml', dest)


@unittest.skipIf(page_fixture.sync_playwright is None, 'playwright not installed')
class TestCompleteSongArrangementPage(unittest.TestCase):
    """Whole-song measure operations through the same controls shipped in the package."""
    page = TestTablaturePage.page
    muted_page = TestTablaturePage.muted_page
    settled = TestTablaturePage.settled
    capture_engraving = TestTablaturePage.capture_engraving
    click_tab_lane = TestTablaturePage.click_tab_lane
    tab_lane_point = staticmethod(TestTablaturePage.tab_lane_point)
    open_panel = staticmethod(TestTablaturePage.open_panel)

    def prepare(self, page):
        page.evaluate("tab('tab');setEdit(true)")
        page.wait_for_selector('[data-ui=track]', state='attached')
        self.capture_engraving(page)
        page.select_option('[data-ui=track]', 'guitar')
        if page.locator('.vt-tab-inspector').get_attribute('open') is None:
            page.locator('.vt-tab-inspector > summary').click()
        self.rendered(page)

    def rendered(self, page):
        self.settled(page, 'window.tabRendered&&tabRenderedRevision===SCORE.view.revision&&tabRenderApi.boundsLookup?.isFinished')

    def command(self, page, selector, endpoint='score_command'):
        with page.expect_response('**/api/' + endpoint) as response:
            page.click(selector)
        result = response.value.json()
        self.assertTrue(result.get('ok'), result)
        self.settled(page, 'SCORE.view.revision===' + json.dumps(result['revision']))
        self.assertNotIn('refused', page.inner_text('.vt-tab-status'))
        return result

    def restore(self, page, path, snapshot):
        page.click('[data-action=undo]')
        self.settled(page, 'SCORE.view.revision===' + json.dumps(snapshot[1]))
        self.assertEqual(path.read_bytes(), snapshot[0])
        self.rendered(page)

    def run_arrangement_edits(self, page, song_path):
        original = song_path.read_bytes()
        errors = []
        page.on('pageerror', lambda error: errors.append(error.stack or str(error)))
        self.prepare(page)
        self.assertEqual(page.evaluate('SCORE.view.orders.length'), 4)
        self.assertEqual(page.evaluate('Object.keys(SCORE.view.score.tracks).length'), 4)
        snapshots = [(original, page.evaluate('SCORE.view.revision'))]
        self.click_tab_lane(page, 0, 0, 2)
        self.settled(page, 'SCORE.view.order===0')
        self.open_panel(page, 'measures')
        first = page.evaluate('SCORE.view.score.measures[0].id')
        page.select_option('[data-ui=measure]', first)
        page.fill('[data-ui=marker-title]', 'Whole song theme')
        page.fill('[data-ui=marker-color]', '#2f84aa')
        page.check('[data-ui=measure-repeat-open]')
        page.fill('[data-ui=measure-repeat-close]', '1')
        result = self.command(page, '.vt-tab-measures button[type=submit]', endpoint='score')
        snapshots.append((song_path.read_bytes(), result['revision']))
        page.fill('[data-ui=ops-from]', '1'); page.fill('[data-ui=ops-to]', '4')
        page.check('[data-ui=ops-all]'); page.check('[data-ui=ops-headers]'); page.check('[data-ui=ops-markers]')
        with page.expect_response('**/api/measure_copy') as response:
            page.click('[data-action=measure-copy]')
        copied = response.value.json()
        self.assertIn('segment', copied, copied)
        self.assertEqual(copied['segment']['tracks'], ['guitar', 'guitar2', 'bass', 'drums'])
        page.wait_for_function("document.querySelector('.vt-tab-status').textContent.startsWith('Copied measures')")
        self.assertEqual(page.locator('[data-ui=ops-track-map] select').count(), 4)
        self.assertTrue(page.is_checked('[data-ui=ops-markers]'))
        self.assertTrue(page.is_checked('[data-ui=ops-headers]'))
        page.fill('[data-ui=ops-from]', '5'); page.fill('[data-ui=ops-count]', '7')
        result = self.command(page, '[data-action=measure-paste-insert]')
        snapshots.append((song_path.read_bytes(), result['revision']))
        self.assertEqual(page.evaluate('SCORE.view.orders.length'), 32)
        source = api.from_yaml(song_path.read_text(encoding='utf-8'))
        measures = source['score']['measures']
        self.assertEqual(len(measures), 32)
        for header in measures[::4]:
            self.assertEqual(header['marker'], dict(title='Whole song theme', color='#2f84aa'))
            self.assertTrue(header['repeat_open'])
            self.assertEqual(header['repeat_close'], 1)
        for name in source['orders']:
            self.assertEqual({b['track'] for b in source['score']['patterns'][name]['beats']},
                             {'guitar', 'guitar2', 'bass', 'drums'})
        self.assertIn('Pasted 28 measures', page.inner_text('.vt-tab-status'))
        page.click('[data-action=close-measures]')
        self.restore(page, song_path, snapshots[-2])
        page.click('[data-action=redo]')
        self.settled(page, 'SCORE.view.revision===' + json.dumps(snapshots[-1][1]))
        self.assertEqual(song_path.read_bytes(), snapshots[-1][0])
        self.restore(page, song_path, snapshots[-2])
        self.restore(page, song_path, snapshots[0])

        # Custom movement is exact in native time and leaves every other instrument untouched.
        self.click_tab_lane(page, 0, 0, 2)
        self.settled(page, 'SCORE.view.order===0')
        before = api.from_yaml(original.decode('utf-8'))
        page.fill('[data-ui=move-amount]', '1/3')
        self.command(page, '[data-action=move-beats-right]')
        moved = api.from_yaml(song_path.read_text(encoding='utf-8'))
        first_pattern = moved['score']['patterns'][moved['orders'][0]]
        self.assertEqual(min(Fraction(*b['at']) for b in first_pattern['beats'] if b['track'] == 'guitar'), Fraction(1, 3))
        for name in before['orders']:
            self.assertEqual([b for b in before['score']['patterns'][name]['beats'] if b['track'] != 'guitar'],
                             [b for b in moved['score']['patterns'][name]['beats'] if b['track'] != 'guitar'])
        self.assertEqual(page.input_value('[data-ui=move-amount]'), '1/3')
        self.restore(page, song_path, snapshots[0])
        page.fill('[data-ui=move-amount]', '')
        self.assertFalse(errors, errors)
        self.assertEqual(song_path.read_bytes(), original)
        print('complete-song arrangement: 32 four-track bars; copied headers/markers; exact custom move and Undo/Redo')

    @staticmethod
    def source():
        from tests.test_tablature_sync import complete_song_seed
        source = complete_song_seed()
        for sample in source['samples'].values():
            sample['file'] = 'a.wav'
        return source

    def test_32_bar_four_track_headers_markers_custom_move_and_history(self):
        with self.muted_page(api.to_yaml(self.source()), width=1920, height=1080) as (page, state, folder):
            self.assertFalse(state.error, state.error)
            self.run_arrangement_edits(page, folder / 'song.yaml')

    def test_make_passage_unique_preserves_occurrences_ties_and_exact_undo(self):
        source = self.source()
        unused = source['orders'][-1]
        source['orders'][-1] = source['orders'][0]
        source['patterns'].pop(unused)
        source['score']['patterns'].pop(unused)
        with self.muted_page(api.to_yaml(source), width=1920, height=1080) as (page, state, folder):
            self.assertFalse(state.error, state.error)
            path = folder / 'song.yaml'
            original = path.read_bytes()
            self.prepare(page)
            revision = page.evaluate('SCORE.view.revision')
            self.open_panel(page, 'measures')
            page.fill('[data-ui=ops-from]', '4'); page.fill('[data-ui=ops-to]', '4')
            self.command(page, '[data-action=measure-unique]')
            after = api.from_yaml(path.read_text(encoding='utf-8'))
            name = after['orders'][-1]
            self.assertNotEqual(name, source['orders'][0])
            self.assertEqual(after['score']['patterns'][name], source['score']['patterns'][source['orders'][0]])
            self.assertEqual(after['score']['order_ids'], source['score']['order_ids'])
            self.assertEqual(after['score']['ties'], source['score']['ties'])
            self.assertIn('Made 1 measure independent', page.inner_text('.vt-tab-status'))
            page.click('[data-action=close-measures]')
            self.restore(page, path, (original, revision))


if __name__ == '__main__':
    unittest.main()
