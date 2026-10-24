"""Validate a built vulturetracker.exe (or the launcher under Python): start it headless on a demo song, wait for
/api/state and the page, stop it, then run its --selfcheck (every packed module and data file). Exit 1 on any failure.

  python tools/exe_check.py dist/vulturetracker.exe
  python tools/exe_check.py --cmd "python tools/exe_entry.py"      # the same checks on the source checkout
"""
import argparse
import array
import copy
import io
import json
import os
import shlex
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
import wave
from fractions import Fraction
from pathlib import Path
from urllib.parse import urlencode

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from vulturetracker.fileio import user_dir  # noqa: E402  (the folder the app writes running.json to)


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def get(url, timeout=5, token=""):
    with urllib.request.urlopen(urllib.request.Request(url, headers={"X-VT-Token": token}), timeout=timeout) as r:
        return r.status, r.read()


def app_token(port):
    """The API token the app on `port` wrote to the user folder's running.json (agent.announce), else ""."""
    try:
        run = json.loads((user_dir() / "running.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ""
    return run.get("token", "") if run.get("port") == port else ""


def written_bar_count(view):
    """Authored measures plus four-quarter display groups in unmetered gaps."""
    offsets = {o['id']: Fraction(*o['at']) for o in view['occurrences']}
    ranges = sorted((offsets[m['from']['occurrence']] + Fraction(*m['from']['at']),
                     offsets[m['to']['occurrence']] + Fraction(*m['to']['at']))
                    for m in view['score'].get('measures', []))
    end, cursor, count = Fraction(*view['duration']), Fraction(0), 0
    for start, stop in ranges:
        if not cursor <= start < stop <= end:
            raise ValueError('Invalid written measure coverage in packaged score')
        count += -(-(start - cursor) // 4) + 1
        cursor = stop
    return count + -(-(end - cursor) // 4)


def native_shortcut_dialog(page, path, owner_pid, cancel=False, cancel_overwrite=False):
    """Drive only this app's native Windows Save dialog; caller holds the desktop lease."""
    import ctypes
    import threading
    from ctypes import wintypes
    user=ctypes.windll.user32
    user.SendMessageW.argtypes=[wintypes.HWND,wintypes.UINT,wintypes.WPARAM,wintypes.LPARAM]
    user.SendMessageW.restype=wintypes.LPARAM
    user.GetDlgItem.argtypes=[wintypes.HWND,ctypes.c_int];user.GetDlgItem.restype=wintypes.HWND
    callback=ctypes.WINFUNCTYPE(wintypes.BOOL,wintypes.HWND,wintypes.LPARAM)
    errors=[]
    def drive():
        dialog=None
        try:
            until=time.monotonic()+15
            while time.monotonic()<until and not dialog:
                found=[]
                @callback
                def visit(hwnd,_):
                    pid=wintypes.DWORD();user.GetWindowThreadProcessId(hwnd,ctypes.byref(pid))
                    name=ctypes.create_unicode_buffer(128);user.GetClassNameW(hwnd,name,128)
                    if pid.value==owner_pid and name.value=='#32770' and user.IsWindowVisible(hwnd):found.append(hwnd)
                    return True
                user.EnumWindows(visit,0)
                dialog=found[0] if found else None
                if not dialog:time.sleep(.05)
            if not dialog:raise RuntimeError('Owned native Save dialog did not appear')
            if cancel:
                user.PostMessageW(dialog,0x111,2,0)
            else:
                edit=user.GetDlgItem(dialog,1148)
                if not edit:
                    edits=[]
                    @callback
                    def child(hwnd,_):
                        name=ctypes.create_unicode_buffer(128);user.GetClassNameW(hwnd,name,128)
                        if name.value=='Edit' and user.GetDlgCtrlID(hwnd)==1001 and user.IsWindowVisible(hwnd):edits.append(hwnd)
                        return True
                    user.EnumChildWindows(dialog,child,0)
                    if len(edits)!=1:raise RuntimeError('Native Save filename control was not found')
                    edit=edits[0]
                value=ctypes.create_unicode_buffer(str(path))
                user.SendMessageW(edit,0x000C,0,ctypes.addressof(value))
                user.PostMessageW(dialog,0x111,1,0)
                if cancel_overwrite:
                    until=time.monotonic()+5;confirmation=None
                    while time.monotonic()<until and not confirmation:
                        found=[]
                        @callback
                        def confirm(hwnd,_):
                            pid=wintypes.DWORD();user.GetWindowThreadProcessId(hwnd,ctypes.byref(pid))
                            if pid.value==owner_pid and hwnd!=dialog and user.IsWindowVisible(hwnd):
                                @callback
                                def button(child,_):
                                    label=ctypes.create_unicode_buffer(128);user.GetWindowTextW(child,label,128)
                                    if label.value.replace('&','')=='No':found.append(child)
                                    return True
                                user.EnumChildWindows(hwnd,button,0)
                            return True
                        user.EnumWindows(confirm,0);confirmation=found[0] if found else None
                        if not confirmation:time.sleep(.05)
                    if not confirmation:raise RuntimeError('Native overwrite confirmation did not appear')
                    user.PostMessageW(confirmation,0x00F5,0,0)
                    time.sleep(.1);user.PostMessageW(dialog,0x111,2,0)
        except Exception as exc:
            errors.append(str(exc))
            if dialog:user.PostMessageW(dialog,0x0010,0,0)
    worker=threading.Thread(target=drive,daemon=True);worker.start()
    page.click('[data-t=project]');page.click('#song-shortcut')
    page.wait_for_function("!document.querySelector('#song-shortcut').disabled",timeout=20000)
    worker.join(1)
    if errors:raise RuntimeError('; '.join(errors))
    result=page.inner_text('#shortcut-result')
    expected='Cancelled' if cancel or cancel_overwrite else 'Saved shortcut:'
    if not result.startswith(expected):raise RuntimeError(result)
    print('ok actual native shortcut dialog:',result)


def native_page(base, token, timeout, target_frame=0, score_seconds=0, gp5_export=False, place_song=None, fit_song=None,
                capo_song=None, it_song=None, shortcut=None):
    """Exercise the packaged page/assets and worklet; caller holds a browser lease."""
    from playwright.sync_api import sync_playwright
    _, raw = get(base + '/api/score', timeout=timeout, token=token)
    view = json.loads(raw)
    expected_bars = written_bar_count(view)
    errors = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch(args=['--mute-audio'],
            **({'executable_path': os.environ['VT_CHROMIUM']} if os.environ.get('VT_CHROMIUM') else {}))
        try:
            page = browser.new_page(viewport={'width': 1400, 'height': 900})
            page.set_default_timeout(timeout * 1000)
            page.on('pageerror', lambda error: errors.append(str(error)))
            # Read response bodies outside callbacks: Playwright's synchronous body()
            # pumps events and can re-enter expect_response's listener cleanup.
            failed_responses = []
            closed_render_keys = set()
            page.on('response', lambda response: failed_responses.append(response) if response.status >= 400 else None)
            page.goto(base + '/?' + urlencode({'token': token}))
            page.wait_for_function("typeof S !== 'undefined' && S?.song?.facts?.native_score")
            page.wait_for_function("S.own?.status === 'ready'")
            if shortcut:
                path,pid=shortcut
                native_shortcut_dialog(page,path,pid)
                saved=path.read_bytes()
                native_shortcut_dialog(page,path,pid,cancel_overwrite=True)
                native_shortcut_dialog(page,path,pid,cancel=True)
                if path.read_bytes()!=saved:raise RuntimeError('Cancel changed the existing shortcut')
            response = page.request.get(page.evaluate("new URL(tok(srcFor(null)), location.href).href"))
            if response.status != 200:
                raise RuntimeError('Packaged SONG render is unavailable')
            with wave.open(io.BytesIO(response.body()), 'rb') as wav:
                rate, frames = wav.getframerate(), wav.getnframes()
                samples = array.array('h', wav.readframes(frames))
            last = len(samples)
            while last and samples[last - 1] == 0:
                last -= 1
            silent_after_score = frames - max(round(score_seconds * rate), (last + 1) // 2)
            if silent_after_score > 2:
                raise RuntimeError(f'Packaged SONG has {silent_after_score / rate:.3f}s of empty padding after score/decay')
            print(f'ok rendered SONG ending: {frames / rate:.5f}s, written score {score_seconds:.5f}s')
            page.evaluate("tab('tab')")
            page.wait_for_selector('.vt-tab-score .at-surface svg')
            if view.get('title') in ('Four bars - brush strokes','Four bars - swing feels','Four bars - fade in','Four bars - articulations','Four bars - layout','Four bars - notation','Four bars - lyrics','Four bars - tempo units'):
                engraved = page.locator('.vt-tab-score').inner_text()
                if any(label in engraved for label in ('Grace fret','Stroke up','Stroke down','MIDI track expression')):
                    raise RuntimeError('Packaged score has duplicate technique parameter annotations')
                print('ok packaged compact technique annotations')
                if view.get('title') in ('Four bars - notation','Four bars - lyrics'):
                    labels=page.locator('.vt-tab-score svg text').all_text_contents()
                    if not all(label in labels for label in ('Soft','light','C','F')):
                        raise RuntimeError('Packaged score lost its lyrics or chord labels')
                    print('ok packaged lyric words and chord diagram labels')
            if view.get('title') in ('Four bars - lyrics','Four bars - tempo units'):
                from tests.test_tablature_page import TestTablaturePage, lyric_boxes, tempo_marks
                words = 'Soft light drifts home'.split()
                print('ok packaged lyric spacing', lyric_boxes(page,'.vt-tab-score',words))
                def check_units(surface, selector):
                    if view['title'] != 'Four bars - tempo units': return
                    marks=tempo_marks(surface,selector)
                    expected=[('\ueca5\uecb7',60),('\ueca7',180),('\ueca3',45),('\ueca5',90)]
                    if [(m['glyph'],m['value']) for m in marks] != expected:
                        raise RuntimeError(f'Packaged tempo units differ: {marks}')
                    print('ok packaged authored tempo units', json.dumps(marks))
                check_units(page,'.vt-tab-score')
                preview = browser.new_page(viewport={'width':1920,'height':1080})
                preview.on('pageerror', lambda error: errors.append(str(error)))
                preview.goto(base + '/score-print?' + urlencode(dict(token=token,song=view['song'],revision=view['revision'])))
                TestTablaturePage().print_ready(preview)
                for mode in ('both','tab','staff'):
                    preview.select_option('[name=notation]',mode);preview.locator('form button[type=submit]').click()
                    TestTablaturePage().print_ready(preview)
                    print('ok packaged lyric print', mode, lyric_boxes(preview,'.vt-print-pages',words))
                    check_units(preview,'.vt-print-pages')
                preview.close()
            if view.get('title') == 'Four bars - layout':
                from tests.test_tablature_page import TestTablaturePage, articulation_harmonic_boxes
                print('ok packaged label gaps', articulation_harmonic_boxes(page, '.vt-tab-score'))
                preview = browser.new_page(viewport={'width':1920,'height':1080})
                preview.on('pageerror', lambda error: errors.append(str(error)))
                preview.goto(base + '/score-print?' + urlencode(dict(token=token,song=view['song'],revision=view['revision'])))
                TestTablaturePage().print_ready(preview)
                print('ok packaged print gaps', articulation_harmonic_boxes(preview,'.vt-print-pages'))
                preview.select_option('[name=notation]','tab')
                preview.locator('form button[type=submit]').click()
                TestTablaturePage().print_ready(preview)
                print('ok packaged TAB-only gaps', articulation_harmonic_boxes(preview,'.vt-print-pages'))
                preview.close()
            if view.get('title') == 'Tied duration editing':
                from tests.test_tablature_page import TestTablaturePage
                helper = TestTablaturePage()
                helper.tied_duration_edits(page, it_song)
                helper.click_tab_lane(page, 0, 0, 2); helper.settled(page, 'SCORE.view.order===0')
                page.evaluate('setEdit(false)')
                print('ok packaged tied duration: Longer/Shorter/dots/tuplets, Fit off/on, cross-bar ties, selection and exact Undo')
            if view.get('title') == 'Duration boundary editing':
                from tests.test_tablature_page import TestTablaturePage
                helper = TestTablaturePage()
                helper.duration_boundary_edits(page, it_song)
                helper.click_tab_lane(page, 0, 0, 2); helper.settled(page, 'SCORE.view.order===0')
                page.evaluate('setEdit(false)')
                print('ok packaged logged duration repair: Shorter/Longer with Fit off/on, final rest retained, exact Undo')
            if view.get('title') == 'Complete song authoring':
                from tests.test_tablature_page import TestCompleteSongArrangementPage, TestTablaturePage
                TestCompleteSongArrangementPage().run_arrangement_edits(page, it_song)
                helper = TestTablaturePage()
                helper.click_tab_lane(page, 0, 0, 2); helper.settled(page, 'SCORE.view.order===0')
                page.evaluate('setEdit(false)')
                print('ok packaged complete-song arrangement: 32 four-track bars, headers/markers, custom move and exact history')
            if view.get('title') == 'Portable phrase source':
                from tests.test_tablature_page import TestCompleteSongClipboardPage, TestTablaturePage
                TestCompleteSongClipboardPage().run_portable_edits(page, it_song, it_song.with_name('destination.yaml'))
                helper = TestTablaturePage()
                helper.click_tab_lane(page, 0, 0, 2); helper.settled(page, 'SCORE.view.order===0')
                page.evaluate('setEdit(false)')
                print('ok packaged portable phrases: destination tuning/routing, cross-song clipboard, exact Undo/Redo')
            if view.get('title') in ('Rehearsal phrase editing', 'Rehearsal setup editing'):
                from tests.test_tablature_page import TestTablaturePage
                if view['title'] == 'Rehearsal phrase editing':
                    from tests.test_rehearsal_edit_page import TestRehearsalEditPage
                    expected_refusal = TestRehearsalEditPage().rehearsal_phrase_edits(page, it_song)
                    failed_responses.remove(expected_refusal)
                else:
                    from tests.test_rehearsal_setup_page import TestRehearsalSetupPage
                    TestRehearsalSetupPage().run_setup_edits(page, it_song)
                helper = TestTablaturePage()
                helper.click_tab_lane(page, 0, 0, 2); helper.settled(page, 'SCORE.view.order===0')
                page.evaluate('setEdit(false)')
                print('ok packaged rehearsal authoring controls and exact history:', view['title'])
            if view.get('title') == 'Rehearsal-ready study':
                from tests.test_rehearsal_arrangement_page import TestRehearsalArrangementPage
                from tests.test_rehearsal_playback import run_rehearsal
                with tempfile.TemporaryDirectory(prefix='vt-packaged-arrangement-') as temporary:
                    TestRehearsalArrangementPage().blank_to_arrangement(page, it_song, Path(temporary) / 'arranged.yaml')
                    page.evaluate('async path=>{await openSong(path)}', str(it_song))
                    page.evaluate("tab('tab');setEdit(false)")
                    page.wait_for_function('SCORE.view.orders.length===32&&!SCORE.busy')
                print('ok packaged blank band to 32-bar arrangement: mapped parts, exact Undo/Redo, saved reopen, unchanged source')
                print('ok packaged rehearsal:', run_rehearsal(page, it_song))
            prepared_original = None
            if it_song and view.get('title') == 'Advanced rhythm editing':
                from tests.test_advanced_rhythm_page import TestAdvancedRhythmPage
                print('ok packaged advanced rhythm:', TestAdvancedRhythmPage().run_advanced(page, it_song))
                page.evaluate('setEdit(false)')
            if it_song and view.get('title') == 'Part-track selection':
                from tests.test_band_instruments_page import TestBandInstrumentsPage
                print('ok packaged Part/Track selection:', TestBandInstrumentsPage().run_part_track_selection(page, it_song))
                page.evaluate('setEdit(false)')
            if it_song and view.get('title') == 'Part adaptation':
                from tests.test_part_adaptation_page import TestPartAdaptationPage
                print('ok packaged part adaptation:', TestPartAdaptationPage().run_adaptation(page, it_song))
            if it_song and view.get('title') == 'Part playback marker':
                from tests.test_part_adaptation_page import TestPartAdaptationPage
                print('ok packaged part playback marker:', TestPartAdaptationPage().run_part_marker(page, it_song))
                print('ok packaged pending edit:', TestPartAdaptationPage().run_pending_edit(page, it_song))
            if view.get('title') == 'Keyboard playback caret':
                from tests.test_part_adaptation_page import TestPartAdaptationPage
                print('ok packaged keyboard caret:', TestPartAdaptationPage().run_keyboard_caret(page, Path(view['song'])))
            if it_song and view.get('title') == 'Mixer interchange':
                from tests.test_tablature_page import TestTablaturePage
                print('ok packaged mixer interchange:', TestTablaturePage().run_mixer_interchange(page, it_song))
            if it_song and view.get('title') == 'Library mixer':
                from tests.test_tablature_page import TestTablaturePage
                print('ok packaged library mixer:', TestTablaturePage().run_library_mixer(page,it_song))
            if it_song and view.get('title') == 'GP5 harmonic export':
                from tests.test_tablature_page import TestTablaturePage
                print('ok packaged GP5 harmonic export:',TestTablaturePage().run_gp5_harmonics(page,it_song))
            if it_song and view.get('title') == 'GP rhythm and clefs':
                from tests.test_tablature_page import TestTablaturePage
                print('ok packaged GP rhythm and clefs:',TestTablaturePage().run_gp_rhythm_clefs(page,it_song))
            if it_song and view.get('title') == 'MIDI export options':
                from tests.test_tablature_page import TestTablaturePage
                print('ok packaged MIDI export options:',TestTablaturePage().run_midi_export_options(page,it_song))
            if it_song and view.get('title') == 'MIDI import options':
                from tests.test_tablature_page import TestTablaturePage
                print('ok packaged MIDI import options:',TestTablaturePage().run_midi_import_options(page,it_song))
            if it_song and view.get('title') == 'GP text encodings':
                from tests.test_tablature_page import TestTablaturePage
                print('ok packaged GP text encodings:',TestTablaturePage().run_gp_encoding(page,it_song))
            if it_song and view.get('title') == 'Drum rolls and flams':
                from tests.test_tablature_page import TestTablaturePage
                print('ok packaged drum rolls and flams:',TestTablaturePage().run_drum_ornaments(page,it_song))
            if it_song and view.get('title') == 'Score view modes':
                from tests.test_tablature_page import TestTablaturePage
                print('ok packaged score view modes:',TestTablaturePage().run_score_view_modes(page,it_song,failed_responses))
            if it_song and view.get('title') == 'Active voice expressions':
                from tests.test_tablature_page import TestTablaturePage
                print('ok packaged active voice expressions:',TestTablaturePage().run_active_voice_expressions(page,it_song))
            if it_song and view.get('title') == 'Compact score spacing':
                from tests.test_tablature_page import TestTablaturePage
                print('ok packaged compact score:',TestTablaturePage().run_compact_score(page,it_song))
            if it_song and view.get('title') == 'Selection pitch editing':
                from tests.test_tablature_page import TestTablaturePage
                print('ok packaged selection pitch:',TestTablaturePage().run_selection_pitch(page,it_song,failed_responses))
            if it_song and view.get('title') == 'Selection delete and rest':
                from tests.test_tablature_page import TestTablaturePage
                print('ok packaged selection deletion:',TestTablaturePage().run_selection_delete(page,it_song))
            if it_song and view.get('title') == 'Beam group stems':
                from tests.test_tablature_page import TestTablaturePage
                print('ok packaged stem groups:',TestTablaturePage().run_stem_groups(page,it_song))
            if it_song and view.get('title') == 'Matrix entry study':
                from tests.test_tablature_page import TestTablaturePage
                print('ok packaged matrix entry:',TestTablaturePage().run_matrix_entry(page,it_song))
            if it_song and view.get('title') == 'Matrix free entry':
                from tests.test_tablature_page import TestTablaturePage
                print('ok packaged Matrix free entry:',TestTablaturePage().run_matrix_free(page,it_song))
            if it_song and view.get('title') == 'Free duration repacking':
                from tests.test_tablature_page import TestTablaturePage
                print('ok packaged Free duration:',TestTablaturePage().run_free_duration_repack(page,it_song))
            if it_song and view.get('title') == 'Invalid bar repair':
                from tests.test_tablature_page import TestTablaturePage
                print('ok packaged invalid bar repair:',TestTablaturePage().run_invalid_bar(page,it_song))
            if it_song and view.get('title') == 'Independent beat groups':
                from tests.test_tablature_page import TestTablaturePage
                print('ok packaged independent beat groups:',TestTablaturePage().run_free_cohorts(page,it_song))
            if it_song and view.get('title') == 'Cohort rest editing':
                from tests.test_tablature_page import TestTablaturePage
                print('ok packaged independent group rest editing:',TestTablaturePage().run_cohort_rest_fit(page,it_song))
            if it_song and view.get('title') == 'Group annotation transfer':
                from tests.test_tablature_page import TestTablaturePage
                print('ok packaged shared annotation transfer:',TestTablaturePage().run_cohort_annotations(page,it_song))
            if it_song and view.get('title') == 'Annotated rhythm Fit':
                from tests.test_tablature_page import TestTablaturePage
                print('ok packaged annotated Fit:',TestTablaturePage().run_annotated_fit(page,it_song))
            if it_song and view.get('title') == 'Clipboard workflow':
                from tests.test_tablature_page import TestTablaturePage
                print('ok packaged clipboard workflow:',TestTablaturePage().run_clipboard_workflow(page,it_song))
            if it_song and view.get('title') in ('Whole-beat replacement', 'Whole-beat silence'):
                from tests.test_tablature_page import TestTablaturePage
                print('ok packaged whole-beat replacement:',TestTablaturePage().run_whole_beat_paste(page,it_song,failed_responses))
            if it_song and view.get('title') in ('MIDI import options','GP text encodings'):
                page.wait_for_function('!AG.reporting')
                with page.expect_response(lambda r:r.url.endswith('/api/uistate') and r.request.method=='POST') as reported:
                    page.evaluate('agReportUI()')
                if reported.value.status!=200:
                    raise RuntimeError('Current-song UI telemetry did not recover after import checks')
                failed_responses[:]=[r for r in failed_responses if not (
                    r.url.endswith('/api/uistate') and r.status==400 and
                    r.json().get('error')=='ValueError: UI report belongs to another song')]
            if it_song and view.get('title') == 'Notation delivery':
                from tests.test_tablature_page import TestTablaturePage
                print('ok packaged notation options:', TestTablaturePage().run_notation_options(page, it_song))
                page.click('[data-t=tab]')
                page.wait_for_selector('.vt-tab-score .at-surface svg')
            if it_song and view.get('title') == 'Repeat-aware rehearsal':
                from tests.test_repeat_rehearsal_page import TestRepeatRehearsalPage
                print('ok packaged repeat rehearsal:', TestRepeatRehearsalPage().run_repeat_rehearsal(page, it_song))
            if it_song and view.get('title') == 'Crosscurrents - repeat performance':
                from tests.test_repeat_rehearsal_page import TestRepeatRehearsalPage
                print('ok packaged repeat study:', TestRepeatRehearsalPage().run_study(page, it_song))
            if it_song and view.get('title') in ('Crosscurrents - expressive arrangement', 'Crosscurrents - advanced rhythm', 'Crosscurrents - repeat performance', 'Crosscurrents - alternate tunings'):
                from tests.test_band_delivery_page import TestBandDeliveryPage
                destination = 'band-delivery-final' if view.get('title') == 'Crosscurrents - repeat performance' else 'band-delivery'
                delivered = TestBandDeliveryPage().run_band_delivery(page, it_song, it_song.parent.parent/destination)
                print('ok packaged complete band delivery:', json.dumps(delivered))
            if it_song and view.get('title') in ('Crosscurrents - complex-score study', 'Crosscurrents - expressive arrangement', 'Crosscurrents - advanced rhythm', 'Crosscurrents - repeat performance'):
                from tests.test_band_delivery_page import TestBandDeliveryPage
                from tests.test_real_interchange import TestRealInterchangePage
                from tests.test_score_collection_page import TestScoreCollectionPage
                advanced = view.get('title') in ('Crosscurrents - advanced rhythm', 'Crosscurrents - repeat performance')
                expressive = advanced or view.get('title') == 'Crosscurrents - expressive arrangement'
                if not expressive:
                    print('ok packaged complex score PDF:', TestBandDeliveryPage().run_delivery(page, it_song))
                collection = TestScoreCollectionPage()
                imports = it_song.parent.parent if advanced else it_song.parent.parent / 'interchange'
                with tempfile.TemporaryDirectory(prefix='vt-complex-import-') as temporary:
                    variants = (('study.gp5', 'study.tg') if advanced else ('crosscurrents.gp5', 'crosscurrents.gp5.rewritten.gp5') if expressive else
                                ('pickup-grace-gp6.gpx', 'pickup-grace-gp7.gp',
                                 'grace-3-32bar.tef', 'gp-oracle/sparse-grace.gp5'))
                    for relative in variants:
                        source = imports / relative
                        page.evaluate('collectionOpen()')
                        collection.scan(page, source.parent)
                        page.fill('#collection-filter', source.name)
                        page.get_by_role('checkbox', name=source.name, exact=True).check()
                        batch = collection.convert(page, Path(temporary) / source.name, 'yaml')
                        imported = batch['results'][0]
                        if imported['status'] != 'done':
                            raise RuntimeError(f'Packaged complex import failed: {imported}')
                        native = Path(imported['files'][0])
                        page.click('#collection-close')
                        closed_render_keys.update(page.evaluate("[S.own,...(S.candidates||[])].filter(x=>x?.key).map(x=>x.key)"))
                        page.evaluate('async path=>{await openSong(path)}', str(native))
                        page.evaluate("tab('tab')")
                        page.wait_for_function('path=>SCORE.view?.song===path&&!SCORE.fetching', arg=str(native))
                        print('ok packaged complex import/edit:', relative,
                              TestRealInterchangePage().run_imported_edits(page, native))
                        page.evaluate('collectionOpen()')
                        collection.scan(page, native.parent)
                        page.fill('#collection-filter', native.name)
                        page.get_by_role('checkbox', name=native.name, exact=True).check()
                        fmt = 'gp5' if source.suffix == '.gp5' else 'tg'
                        batch = collection.convert(page, Path(temporary) / (source.name + '-roundtrip'), fmt)
                        exported = batch['results'][0]
                        if exported['status'] != 'done':
                            raise RuntimeError(f'Packaged complex round trip failed: {exported}')
                        from vulturetracker import api as source_api, tgimport, gpimport
                        from tests.test_complex_interchange import sounding
                        data = Path(exported['files'][0]).read_bytes()
                        restored = (tgimport.read_tg(data)[0] if fmt == 'tg' else
                                    gpimport._native_gp_song(gpimport._read_native_gp(data), 'Packaged grace'))
                        if sounding(restored) != sounding(source_api.from_yaml(native.read_text(encoding='utf-8'))):
                            raise RuntimeError('Packaged complex round trip changed performed events')
                        if expressive:
                            from tests.test_expressive_gp5 import gp5_signature
                            if gp5_signature(restored) != gp5_signature(source_api.from_yaml(native.read_text(encoding='utf-8'))):
                                raise RuntimeError('Packaged imported GP5 round trip changed notation or metadata')
                        print('ok packaged complex round trip:', relative, fmt, 'equal performed events')
                        page.click('#collection-close')
                    closed_render_keys.update(page.evaluate("[S.own,...(S.candidates||[])].filter(x=>x?.key).map(x=>x.key)"))
                    page.evaluate('async path=>{await openSong(path)}', str(it_song))
                page.evaluate("tab('tab');setEdit(false)")
                page.wait_for_function('path=>SCORE.view?.song===path&&!SCORE.fetching', arg=str(it_song))
                page.wait_for_function('!AG.reporting')
                with page.expect_response(lambda r: r.url.endswith('/api/uistate') and r.request.method == 'POST') as reported:
                    page.evaluate('agReportUI()')
                if reported.value.status != 200:
                    raise RuntimeError('Current-song UI report did not recover after complex imports')
                failed_responses[:] = [r for r in failed_responses if not (
                    r.url.endswith('/api/uistate') and r.status == 400 and
                    r.json().get('error') == 'ValueError: UI report belongs to another song')]
            if it_song and view.get('title') in ('Complex voice routing', 'Sustained voice routing'):
                from tests.test_complex_routing_page import TestComplexRoutingPage
                print('ok packaged overlapping voices:', TestComplexRoutingPage().run_routing(page, it_song))
                prepared_original = it_song.read_bytes()
                prepared_revision = view['revision']
                with page.expect_response('**/api/score_command') as routed:
                    page.click('#part-voices-separate')
                result = routed.value.json()
                if not result.get('ok'):
                    raise RuntimeError(f'Separate voices for standalone IT: {result}')
                page.wait_for_function('revision=>SCORE.view.revision===revision&&!SCORE.busy', arg=result['revision'])
                view = json.loads(get(base + '/api/score', token=token)[1])
                page.evaluate('setEdit(false)')
            if it_song and view.get('title') == 'Complex rhythm editing':
                from tests.test_complex_rhythm_page import TestComplexRhythmPage
                print('ok packaged expressive rebar/move/paste:', TestComplexRhythmPage().run_rhythm(page, it_song))
                page.evaluate('setEdit(false)')
            if it_song and view.get('title') == 'Expressive arrangement':
                from tests.test_complex_rhythm_page import TestExpressiveArrangementPage
                print('ok packaged expressive editing:', TestExpressiveArrangementPage().run_expressive_edits(page, it_song))
                page.evaluate('setEdit(false)')
            if it_song and view.get('title') == 'Mixed library band study':
                from tests.test_band_instruments_page import TestBandInstrumentsPage
                from tests.test_band_delivery_page import TestBandDeliveryPage
                print('ok packaged part sounds:', TestBandInstrumentsPage().run_part_sound_edits(page, it_song))
                print('ok packaged PDF delivery:', TestBandDeliveryPage().run_delivery(page, it_song))
                from tests.test_real_interchange import TestRealInterchangePage
                from tests.test_score_collection_page import TestScoreCollectionPage
                collection = TestScoreCollectionPage()
                with tempfile.TemporaryDirectory(prefix='vt-packaged-band-import-') as temporary:
                    for kind, extension in (('ptb', 'ptb'), ('tef2', 'tef'), ('tef3', 'tef')):
                        source = it_song.parent.parent / f'original-32bar-{kind}.{extension}'
                        page.evaluate('collectionOpen()')
                        collection.scan(page, source.parent)
                        page.fill('#collection-filter', source.name)
                        page.get_by_role('checkbox', name=source.name, exact=True).check()
                        batch = collection.convert(page, Path(temporary)/kind, 'yaml')
                        imported = batch['results'][0]
                        if imported['status'] != 'done':
                            raise RuntimeError(f'Packaged {kind} import failed: {imported}')
                        native = Path(imported['files'][0])
                        page.click('#collection-close')
                        page.evaluate('async path=>{await openSong(path)}', str(native))
                        page.evaluate("tab('tab')")
                        page.wait_for_function('path=>SCORE.view?.song===path&&!SCORE.fetching', arg=str(native))
                        print('ok packaged native import/edit:', kind, TestRealInterchangePage().run_imported_edits(page, native))
                    page.evaluate('async path=>{await openSong(path)}', str(it_song))
                page.evaluate("tab('tab');setEdit(false)")
                page.wait_for_function('path=>SCORE.view?.song===path&&!SCORE.fetching', arg=str(it_song))
                page.wait_for_function('!AG.reporting')
                with page.expect_response(lambda r: r.url.endswith('/api/uistate') and r.request.method == 'POST') as reported:
                    page.evaluate('agReportUI()')
                if reported.value.status != 200:
                    raise RuntimeError('Current-song UI report did not recover after band imports')
                failed_responses[:] = [r for r in failed_responses if not (
                    r.url.endswith('/api/uistate') and r.status == 400 and
                    r.json().get('error') == 'ValueError: UI report belongs to another song')]
            if view.get('title') == 'Band expression editing':
                from tests.test_band_expression_page import TestBandExpressionPage
                print('ok packaged expressive phrase:', TestBandExpressionPage().run_expression(page, it_song))
                page.evaluate('setEdit(false)')
            if view.get('title') == 'Real-world arrangement':
                from tests.test_real_arrangement_page import TestRealArrangementPage
                print('ok packaged independent measures:', TestRealArrangementPage().run_arrangement(page, it_song))
                # This deliberately reused fixture has occurrence-dependent final
                # releases. Exercise the new preparation as the remedy before
                # strict IT export, then restore it after that qualification.
                prepared_original = it_song.read_bytes()
                prepared_revision = view['revision']
                if not page.locator('[data-action=prepare-measures]').is_visible():
                    page.click('[data-action=measures]')
                with page.expect_response('**/api/score_command') as preparing:
                    page.click('[data-action=prepare-measures]')
                result = preparing.value.json()
                if not result.get('ok'):
                    raise RuntimeError(f'Prepare for standalone IT: {result}')
                page.wait_for_function('revision=>SCORE.view.revision===revision&&!SCORE.busy', arg=result['revision'])
                view = json.loads(get(base + '/api/score', token=token)[1])
                page.click('[data-action=close-measures]')
                page.evaluate('setEdit(false)')
            if view.get('title') == 'Real-world tab study':
                from tests.test_real_workspace_page import TestRealWorkspacePage
                from tests.test_real_interchange import TestRealInterchangePage
                from tests.test_score_collection_page import TestScoreCollectionPage
                TestRealWorkspacePage().run_workspace(page, it_song)
                TestScoreCollectionPage().run_collection(page, it_song)
                helper = TestRealInterchangePage()
                for kind in ('tg', 'gp5', 'mid', 'gp3', 'gp4'):
                    imported = it_song.parent.parent / ('imported-' + kind) / 'song.yaml'
                    page.evaluate('async path=>{await openSong(path)}', str(imported))
                    print('ok packaged imported edit:', helper.run_imported_edits(page, imported))
                page.evaluate('async path=>{await openSong(path)}', str(it_song))
                page.evaluate("tab('tab');setEdit(false)")
                page.wait_for_function('path=>SCORE.view?.song===path&&SCORE.view.orders.length===32&&!SCORE.busy', arg=str(it_song))
                # Song switches can leave an already-sent UI telemetry report in
                # flight. The server must discard it; require a fresh report to
                # succeed before accepting only that explicit ownership refusal.
                page.wait_for_function('!AG.reporting')
                with page.expect_response(lambda r: r.url.endswith('/api/uistate') and r.request.method == 'POST') as reported:
                    page.evaluate('agReportUI()')
                if reported.value.status != 200:
                    raise RuntimeError('Current-song UI telemetry did not recover after imported-song checks')
                failed_responses[:] = [r for r in failed_responses if not (
                    r.url.endswith('/api/uistate') and r.status == 400 and
                    r.json().get('error') == 'ValueError: UI report belongs to another song')]
                print('ok packaged compact workspace, saved panels and contextual shortcuts')
            if view.get('title') in ('Four tracks - whole song', 'Rehearsal-ready study', 'Notation delivery'):
                from tests.test_tablature_page import TestScoreDeliveryPage
                preview = browser.new_page(viewport={'width':1600,'height':1000})
                preview.on('pageerror', lambda error: errors.append(error.stack or str(error)))
                preview.goto(base + '/score-print?' + urlencode(dict(token=token,song=view['song'],revision=view['revision'])))
                helper = TestScoreDeliveryPage(); helper.print_ready(preview)
                helper.export_preview(preview, it_song.parent / 'score-exports')
                for tid in ('guitar2', 'bass', 'drums'):
                    preview.uncheck(f'[name=track][value={tid}]')
                preview.click('button[type=submit]'); helper.print_ready(preview)
                (it_song.parent / 'score-exports/lead-guitar.pdf').write_bytes(preview.pdf(prefer_css_page_size=True, print_background=True))
                preview.close()
                print('ok packaged score delivery: four-track PDF, lead part, standalone SVG, PNG, JPEG and BMP')
            if view.get('title') == 'Section composition':
                from tests.test_tablature_page import TestTablaturePage
                helper = TestTablaturePage()
                helper.complete_section_edits(page, it_song)
                helper.click_tab_lane(page, 0, 0, 2); helper.settled(page, 'SCORE.view.order===0')
                page.evaluate('setEdit(false)')
                print('ok packaged section session: 16 bars, repeat/paste, passage move, meter, variation, exact Undo/Redo')
            if view.get('title') == 'Everyday rhythm editing':
                from tests.test_tablature_page import TestTablaturePage
                helper = TestTablaturePage()
                helper.everyday_rhythm_edits(page, it_song)
                helper.click_tab_lane(page, 0, 0, 2); helper.settled(page, 'SCORE.view.order===0')
                page.evaluate('setEdit(false)')
                print('ok packaged rhythm session: consumed/regenerated rests, Fit, retained ranges, Copy/velocity, exact Undo and no-room status')
            if view.get('title') == 'Range expression editing':
                from tests.test_tablature_page import TestTablaturePage
                helper=TestTablaturePage();original=it_song.read_bytes()
                helper.capture_engraving(page);page.select_option('[data-ui=track]','guitar')
                page.wait_for_function('window.tabRendered&&tabRenderApi.boundsLookup.isFinished')
                page.evaluate('setEdit(true)');page.locator('.vt-tab-inspector > summary').click()
                helper.click_tab_lane(page,2,0,3);end=helper.tab_lane_point(page,3,3,4)
                page.keyboard.down('Shift');page.mouse.click(end['x'],end['y']);page.keyboard.up('Shift')
                helper.settled(page,'SCORE.view.order===3')
                if 'accent' not in page.inner_text('[data-ui=range-expression-info]'):
                    raise RuntimeError('Packaged range expression did not show visible mixed articulation')
                page.select_option('[data-ui=dynamics]','79');page.click('[data-action=velocity]')
                helper.settled(page,"SCORE.view.score.patterns.C2.beats.every(b=>b.notes.every(n=>n.velocity===79))")
                page.click('[data-action=ghost]')
                helper.settled(page,"SCORE.view.score.patterns.C2.beats.every(b=>b.notes.every(n=>n.ghost))")
                page.click('[data-action=palm-mute]')
                helper.settled(page,"SCORE.view.score.patterns.C2.beats.every(b=>b.notes.every(n=>n.palm_mute))")
                page.evaluate("async()=>{SCORE.key=null;await scoreRefresh()}")
                helper.settled(page,"document.querySelectorAll('.vt-tab-selection').length===8")
                page.select_option('[data-ui=range-articulation]','clear');page.click('[data-action=ghost]')
                helper.settled(page,"SCORE.view.score.patterns.C2.beats.every(b=>b.notes.every(n=>!n.ghost))")
                page.locator('#tab-editor').focus()
                for _ in range(4):
                    page.keyboard.press('Control+z');page.wait_for_function('!EDQ.n&&!SCORE.fetching')
                if it_song.read_bytes()!=original:raise RuntimeError('Packaged range expression Undo changed source bytes')
                helper.click_tab_lane(page,0,0,2);helper.settled(page,'SCORE.view.order===0')
                page.evaluate('setEdit(false)');page.locator('.vt-tab-inspector > summary').click()
                print('ok packaged range dynamics/articulation mixed, explicit Set/Clear, retained selection and exact Undo')
            if view.get('title') == 'Range pitch editing':
                from tests.test_tablature_page import TestTablaturePage
                from vulturetracker import api as source_api
                helper=TestTablaturePage();original=it_song.read_bytes()
                helper.capture_engraving(page);page.select_option('[data-ui=track]','guitar')
                page.wait_for_function('window.tabRendered&&tabRenderApi.boundsLookup.isFinished')
                page.evaluate('setEdit(true)');page.locator('.vt-tab-inspector > summary').click()
                helper.click_tab_lane(page,2,0,2);end=helper.tab_lane_point(page,3,3,3)
                page.keyboard.down('Shift');page.mouse.click(end['x'],end['y']);page.keyboard.up('Shift')
                helper.settled(page,'SCORE.view.order===3')
                page.click('[data-action=transpose]')
                if page.input_value('[data-ui=transpose-scope]')!='selection' or not page.is_disabled('[data-ui=transpose-all]'):
                    raise RuntimeError('Packaged Transpose did not expose selected phrase scope')
                page.fill('[data-ui=transpose-semitones]','2');page.click('.vt-tab-transpose button[type=submit]')
                helper.settled(page,"SCORE.view.score.patterns.G.beats[0].notes[0].pitch===62")
                data=source_api.compile_song(it_song)[0]
                page.click('[data-action=close-transpose]');page.click('[data-action=string-down]')
                helper.settled(page,"SCORE.view.score.patterns.G.beats[0].notes[0].string===3")
                page.evaluate("async()=>{SCORE.key=null;await scoreRefresh()}")
                helper.settled(page,"document.querySelectorAll('.vt-tab-selection').length===8")
                if source_api.compile_song(it_song)[0]!=data:raise RuntimeError('String shift changed standalone IT')
                page.locator('#tab-editor').focus()
                for expected in (2,2):
                    page.keyboard.press('Control+z');page.wait_for_function('!EDQ.n&&!SCORE.fetching')
                if it_song.read_bytes()!=original:raise RuntimeError('Packaged range pitch Undo changed source bytes')
                helper.click_tab_lane(page,0,0,2);helper.settled(page,'SCORE.view.order===0')
                page.evaluate('setEdit(false)');page.locator('.vt-tab-inspector > summary').click()
                print('ok packaged selected-range Transpose, adjacent string shift, retained range, byte-identical IT and exact Undo')
            if view.get('title') in ('Cross-measure editing', 'Replacement editing', 'Cut Repeat editing'):
                from tests.test_tablature_page import TestTablaturePage
                from vulturetracker.itreader import read_it
                from vulturetracker import api as source_api
                helper = TestTablaturePage()
                original = it_song.read_bytes()
                replacement = view.get('title') == 'Replacement editing'
                commands = view.get('title') == 'Cut Repeat editing'
                original_score = view['score']['patterns']
                helper.capture_engraving(page)
                page.select_option('[data-ui=track]', 'guitar')
                page.wait_for_function('window.tabRendered && tabRenderApi.boundsLookup.isFinished')
                page.evaluate('setEdit(true)')
                helper.click_tab_lane(page, 0, 0, 2)
                end = helper.tab_lane_point(page, 1, 3, 3)
                page.keyboard.down('Shift'); page.mouse.click(end['x'], end['y']); page.keyboard.up('Shift')
                helper.settled(page, 'SCORE.view.order===1')
                page.keyboard.press('Control+c')
                page.wait_for_function("document.querySelector('.vt-tab-status').textContent.startsWith('Copied 8')")
                if commands:
                    page.keyboard.press('Control+x')
                    helper.settled(page,"SCORE.view.score.patterns.C.beats.every(b=>!b.notes.length)&&SCORE.view.score.patterns.F.beats.every(b=>!b.notes.length)")
                    page.keyboard.press('Control+z')
                    helper.settled(page,"SCORE.view.score.patterns.C.beats.every(b=>b.notes.length)")
                    if it_song.read_bytes()!=original: raise RuntimeError('Packaged range Cut Undo changed source bytes')
                    helper.click_tab_lane(page,0,0,2)
                    end=helper.tab_lane_point(page,1,3,3)
                    page.keyboard.down('Shift');page.mouse.click(end['x'],end['y']);page.keyboard.up('Shift')
                    helper.settled(page,'SCORE.view.order===1')
                    page.keyboard.press('Control+r')
                else:
                    helper.click_tab_lane(page, 2, 0, 1)
                    helper.settled(page, 'SCORE.view.order===2')
                if replacement:
                    with page.expect_response('**/api/score') as refusal_response:
                        page.keyboard.press('Control+v')
                    refusal = refusal_response.value
                    if (refusal.status != 400 or refusal.request.post_data_json.get('replace') is not False or
                            'cross-measure paste requires an empty destination span' not in refusal.json().get('error', '')):
                        raise RuntimeError('Safe paste did not return its expected occupied-span refusal')
                    failed_responses.remove(refusal)
                    page.wait_for_function("document.querySelector('.vt-tab-status').textContent.includes('empty destination span')")
                    if it_song.read_bytes() != original:
                        raise RuntimeError('Safe Ctrl+V changed occupied destination')
                    page.locator('.vt-tab-inspector > summary').click()
                    page.click('[data-action=paste-replace]')
                elif not commands:
                    page.keyboard.press('Control+v')
                helper.settled(page, "SCORE.view.score.patterns.C2.beats.length===4 && SCORE.view.score.patterns.C2.beats.every(b=>b.id.startsWith('copy_'))")
                if commands:
                    page.evaluate("async()=>{SCORE.key=null;await scoreRefresh()}")
                    helper.settled(page,"document.querySelectorAll('.vt-tab-selection').length===8")
                    if sorted(page.locator('.vt-tab-selection').evaluate_all('els=>els.map(e=>e.dataset.occurrence)')) != ['bar3']*4+['bar4']*4:
                        raise RuntimeError('Packaged Repeat lost occurrence-qualified selection after refresh')
                actual = page.evaluate('SCORE.view.score.patterns')
                for src, dst in (('C', 'G'), ('F', 'C2')):
                    if [b['at'] for b in actual[src]['beats']] != [b['at'] for b in actual[dst]['beats']]:
                        raise RuntimeError('Packaged cross-measure paste moved beat timing')
                standalone, _ = read_it(source_api.compile_song(it_song)[0])
                for p in (2, 3):
                    if sum(c.note is not None and c.note < 120 for row in standalone.patterns[p].rows for c in row) != 4:
                        raise RuntimeError('Packaged pasted phrase did not reopen as four tracker attacks per bar')
                page.keyboard.press('Control+z')
                helper.settled(page, f"JSON.stringify(SCORE.view.score.patterns) === {json.dumps(json.dumps(original_score, separators=(',', ':')))}")
                if it_song.read_bytes() != original:
                    raise RuntimeError('Packaged cross-measure Undo changed source bytes')
                helper.click_tab_lane(page, 0, 0, 2)
                helper.settled(page, 'SCORE.view.order===0')
                page.evaluate('setEdit(false)')
                if replacement:
                    page.locator('.vt-tab-inspector > summary').click()
                print('ok packaged cross-measure rendered selection, ' + ('Cut/Repeat' if commands else 'Copy/Paste') + (' replace (safe Ctrl+V refused)' if replacement else '') + ', editable standalone IT and exact Undo')
            caret = page.locator('.vt-tab-edit-caret:not([hidden])')
            caret.wait_for(state='visible')
            if page.locator('.vt-tab-grid').is_visible():
                raise RuntimeError('TAB opens with the separate grid instead of the score editor')
            # Click the actual engraved string, then navigate without changing the song.
            box = caret.bounding_box()
            page.mouse.click(box['x'] + box['width'] / 2, box['y'] + box['height'] / 2)
            selected_string = int(caret.get_attribute('data-string'))
            selected_track = page.locator('[data-ui=track]').input_value()
            track_spec = view['score']['tracks'][selected_track]
            if track_spec.get('midi', {}).get('bank') != 128:
                board = page.locator('.vt-fretboard')
                if not board.evaluate('e => e.open'):
                    board.locator(':scope > summary').click()
                cells = board.locator('[data-fb-string][data-fb-fret]')
                expected_cells = len(track_spec['tuning']) * (track_spec.get('max_fret', 29) + 1)
                page.wait_for_function('count => document.querySelectorAll(".vt-fretboard [data-fb-string][data-fb-fret]").length === count',
                                       arg=expected_cells)
                if board.locator('[data-fb=scale] option').count() != 276 or board.locator('[data-fb=root] option').count() != 17:
                    raise RuntimeError('Packaged fretboard is missing its scale catalogue or root spellings')
                board.locator('[data-fb=scale]').select_option('0')
                board.locator('[data-fb=direction]').select_option('left')
                first = cells.first
                if int(first.get_attribute('data-pitch')) != track_spec['tuning'][0] + track_spec.get('capo', 0):
                    raise RuntimeError('Packaged fretboard changed the open-string concert pitch')
                board.locator(':scope > summary').click()
                page.locator('#tab-editor').focus()
            piano = page.locator('.vt-piano')
            if not piano.evaluate('e => e.open'):
                piano.locator(':scope > summary').click()
            drum_keys = track_spec.get('midi', {}).get('bank') == 128
            expected_keys = list(range(1, 101)) if drum_keys else list(range(120))
            page.wait_for_function('count => document.querySelectorAll(".vt-piano [data-piano-pitch]").length === count',
                                   arg=len(expected_keys))
            if piano.locator('[data-piano-pitch]').evaluate_all(
                    'keys => keys.map(key => Number(key.dataset.pianoPitch))') != expected_keys:
                raise RuntimeError('Packaged piano has incorrect native pitch/drum boundaries')
            piano.locator(':scope > summary').click()
            page.locator('#tab-editor').focus()
            if len(view['score']['tracks'][selected_track]['tuning']) > 1:
                direction = -1 if selected_string > 1 else 1
                page.keyboard.press('ArrowUp' if direction < 0 else 'ArrowDown')
                page.wait_for_function("""value => {
                    const e = document.querySelector('.vt-tab-edit-caret:not([hidden])');
                    return e && Number(e.dataset.string) === value;
                }""", arg=selected_string + direction)
            _, selected_view = get(base + '/api/score', token=token)
            if json.loads(selected_view)['revision'] != view['revision']:
                raise RuntimeError('Score selection/navigation changed the song')
            page.wait_for_function("count => Number(document.querySelector('.vt-tab-score').dataset.bars) === count",
                                   arg=expected_bars)
            engraving = page.evaluate_handle("Array.from(document.querySelectorAll('.vt-tab-score .at-surface svg'))")

            def check_engraving():
                if not page.evaluate("""({saved, count}) => {
                    const host = document.querySelector('.vt-tab-score');
                    const current = [...host.querySelectorAll('.at-surface svg')];
                    return Number(host.dataset.bars) === count && saved.length > 0 &&
                        current.length === saved.length && saved.every((svg, i) => svg.isConnected && svg === current[i]);
                }""", {'saved': engraving, 'count': expected_bars}):
                    raise RuntimeError('Whole written TAB engraving was replaced or lost bars during navigation/playback')

            if len(view['orders']) > 1:
                last_order = len(view['orders']) - 1
                page.evaluate("async order => {setCursor(order,0,0,0); await scoreRefresh();}", last_order)
                page.wait_for_function('order => SCORE.view.order === order', arg=last_order)
                check_engraving()
            page.check('[data-ui=follow]')
            page.evaluate('setEdit(false)')
            page.evaluate("""async token => {
                const headers = {'X-VT-Token': token, 'Content-Type': 'application/json'};
                const request = async (path, body) => {
                    const r = await fetch(path, {method: body ? 'POST' : 'GET', headers,
                        ...(body ? {body: JSON.stringify(body)} : {})});
                    const result = await r.json();
                    if (!r.ok || result.error) throw Error(result.error || `${path}: ${r.status}`);
                    return result;
                };
                const view = await request('/api/score');
                const track = Object.keys(view.score.tracks).find(id =>
                    view.score.tracks[id].tuning.length === 6 && view.score.tracks[id].midi?.bank !== 128);
                if (!track) return;
                const generated = await request('/api/chord_generate',
                    {revision: view.revision, track, spec: {root: 0}, max_fret: 5, count: 3});
                if (!generated.chords.length) throw Error('Packaged generator returned no C shapes');
                const recognized = await request('/api/chord_recognize',
                    {revision: view.revision, track, chord: generated.chords[0]});
                if (!recognized.proposals.length) throw Error('Packaged recognizer returned no names');
                if ((await request('/api/score')).revision !== view.revision)
                    throw Error('Chord suggestions changed the song');
            }""", token)
            page.evaluate('async()=>{await lvPlay(0,0)}')
            page.wait_for_selector('.vt-tab-playhead:not([hidden])')
            marker = page.locator('.vt-tab-playhead').evaluate(
                "e => [e.dataset.occurrence,e.dataset.bar,e.dataset.at].join('|')")
            track = page.locator('[data-ui=track]').input_value()
            boundaries = {Fraction(0), *(Fraction(*p[key]) for p in view['positions']
                if p['kind'] == 'beat' and p['track'] == track and p['voice'] == 0
                for key in ('at', 'end') if Fraction(*p[key]) < Fraction(*view['duration']))}
            if expected_bars > 1 or len(boundaries) > 1:
                page.wait_for_function("""previous => {
                    const e = document.querySelector('.vt-tab-playhead:not([hidden])');
                    return LV.playing && e && [e.dataset.occurrence,e.dataset.bar,e.dataset.at].join('|') !== previous;
                }""", arg=marker)
            if len(view['orders']) > 1:
                page.wait_for_function("""first => {
                    const e = document.querySelector('.vt-tab-playhead:not([hidden])');
                    return LV.playing && e?.dataset.occurrence && e.dataset.occurrence !== first;
                }""", arg=view['score']['order_ids'][0])
            page.wait_for_function('frame => LV.playing && !LV.loading && LV.pos?.scoreFrame > frame', arg=target_frame)
            check_engraving()
            error = page.evaluate('LV.err')
            page.evaluate('lvStop()')
            if gp5_export:
                from vulturetracker.gpimport import _read_native_gp, _native_gp_song
                with tempfile.TemporaryDirectory(prefix='vt-gp5-check-') as folder:
                    page.evaluate("tab('export')")
                    page.locator('#export-format').select_option('gp5')
                    page.locator('#export-dest').fill(folder)
                    page.locator('#export-name').fill('packaged-score')
                    previous_job = page.evaluate('S.export?.job_id || null')
                    with page.expect_response('**/api/export') as requested:
                        page.locator('#export-go').click()
                    if requested.value.status != 200:
                        raise RuntimeError(f'Packaged GP5 export request: {requested.value.json()}')
                    page.wait_for_function("previous=>S.export?.job_id && S.export.job_id!==previous && ['done','failed'].includes(S.export.status)", arg=previous_job)
                    result = page.evaluate('S.export')
                    if result['status'] != 'done':
                        raise RuntimeError(f'Packaged GP5 export failed: {result.get("error")}')
                    data = (Path(folder) / 'packaged-score.gp5').read_bytes()
                    imported = _native_gp_song(_read_native_gp(data), 'Packaged GP5')
                    measures = len(imported['score']['measures'])
                    notes = sum(len(b['notes']) for p in imported['score']['patterns'].values() for b in p['beats'])
                    report = result['conversion']
                    if measures != report['measures'] or notes != report['notes']:
                        raise RuntimeError('Packaged GP5 readback differs from its reported measure/note counts')
                    def flags(score, orders):
                        keys = ('ghost', 'accent', 'heavy_accent', 'staccato', 'dead', 'palm_mute', 'let_ring',
                                'harmonic', 'trill', 'tremolo_picking', 'bend', 'slide', 'vibrato', 'hammer', 'tremolo_bar')
                        return {key: sum(bool(note.get(key)) for name in orders
                            for beat in score['patterns'].get(str(name), {}).get('beats', [])
                            for note in beat['notes']) for key in keys}
                    expected_flags = flags(view['score'], view['orders'])
                    if flags(imported['score'], imported['orders']) != expected_flags:
                        raise RuntimeError('Packaged GP5 readback lost or added note flags')
                    if it_song and view.get('title') in ('Crosscurrents - expressive arrangement', 'Crosscurrents - advanced rhythm', 'Crosscurrents - repeat performance', 'Crosscurrents - alternate tunings'):
                        from tests.test_expressive_gp5 import gp5_signature
                        from vulturetracker import api as source_api
                        source = source_api.from_yaml(it_song.read_text(encoding='utf-8'))
                        if gp5_signature(imported) != gp5_signature(source):
                            raise RuntimeError('Packaged GP5 changed written notes, ties, techniques, labels or performed events')
                        print('ok packaged GP5 full notation, chord/pick/brush metadata, ties and performed events')
                    print(f'ok packaged GP5 export/readback: {measures} measures, {notes} notes, flags {expected_flags}')
            if place_song is not None:
                before = place_song.read_bytes()
                page.evaluate("async()=>{tab('tab');setCursor(0,0,0,0);await scoreRefresh()}")
                page.wait_for_function("SCORE.view?.order===0 && !EDQ.n && !LV.playing")
                inspector = page.locator('.vt-tab-inspector')
                if not inspector.evaluate('e=>e.open'):
                    inspector.locator(':scope > summary').click()
                page.locator('[data-ui=at]').fill('9/4')
                page.locator('[data-action=go]').click()
                page.locator('[data-ui=duration]').select_option('8')
                page.locator('[data-ui=dots]').select_option('0')
                page.locator('[data-ui=tuple-n]').fill('1')
                page.locator('[data-ui=tuple-d]').fill('1')
                if not piano.evaluate('e=>e.open'):
                    piano.locator(':scope > summary').click()
                piano.locator('[data-piano=mode]').select_option('edit')
                with page.expect_response('**/api/score_command') as placed_response:
                    piano.locator('[data-piano-pitch="67"]').click()
                placed = placed_response.value.json()
                def check_placement(result, pitch, fret, revision=None):
                    if result.get('error'):
                        raise RuntimeError(f'Packaged Place refused: {result["error"]}')
                    page.wait_for_function("""revision => !EDQ.n && SCORE.view?.revision===revision &&
                        CUR.score?.at?.[0]===9 && CUR.score?.at?.[1]===4""", arg=revision or result['revision'])
                    selected = result['selection']
                    beats = page.evaluate("SCORE.view.score.patterns.verse.beats")
                    inserted = next(b for b in beats if b['id'] == selected['beats'][0])
                    if (selected['occurrence'] != 'pass-1' or selected['track'] != 'guitar' or selected['voice'] != 0 or
                            selected['at'] != [9,4] or inserted['at'] != [9,4] or
                            inserted['written'] != dict(value=8,dots=0,tuplet=[1,1]) or
                            [(n['pitch'],n['string'],n['fret']) for n in inserted['notes']] != [(pitch,1,fret)] or
                            selected['notes'] != [inserted['notes'][0]['id']] or
                            page.evaluate('[CUR.score.beat,CUR.score.note]') != [inserted['id'],inserted['notes'][0]['id']]):
                        raise RuntimeError('Packaged Place lost its exact source identity, caret, duration or fingering')
                    rests = [b for b in beats if not b['notes']]
                    if (len(rests) != 2 or
                            sorted((b['at'], b['written']['value']) for b in rests) != [([2,1],16),([11,4],16)] or
                            any(b['written'].get('dots',0) or b['written'].get('tuplet',[1,1]) != [1,1] for b in rests) or
                            next(b for b in rests if b['at'] == [2,1])['id'] != 'rest' or
                            len({b['id'] for b in beats}) != len(beats)):
                        raise RuntimeError('Packaged Place lost its exact rest remainders or source IDs')
                    original_notes = [b for b in view['score']['patterns']['verse']['beats'] if b['notes']]
                    if [b for b in beats if b['id'] != inserted['id'] and b['notes']] != original_notes:
                        raise RuntimeError('Packaged Place changed unrelated notes')
                check_placement(placed,67,5)
                page.locator('[data-action=undo]').click()
                page.wait_for_function('revision => !EDQ.n && SCORE.view?.revision===revision', arg=view['revision'])
                if place_song.read_bytes() != before:
                    raise RuntimeError('One packaged Undo did not restore the exact fixture bytes')
                print('ok packaged Place: piano click split bare rest, exact IDs/caret retained, one Undo restored bytes')
                piano.locator(':scope > summary').click()
                page.locator('[data-ui=at]').fill('9/4')
                page.locator('[data-action=go]').click()
                page.locator('[data-ui=duration]').select_option('8')
                requests, replies = [], []
                page.on('request', lambda r: requests.append(r.post_data_json)
                        if r.method == 'POST' and r.url.split('?')[0].endswith(('/api/score','/api/score_command')) else None)
                page.on('response', lambda r: replies.append(r.json())
                        if r.request.method == 'POST' and r.url.split('?')[0].endswith(('/api/score','/api/score_command')) else None)
                page.locator('#tab-editor').focus()
                page.keyboard.type('12')
                page.wait_for_function("""() => !EDQ.n && SCORE.view.score.patterns.verse.beats.some(
                    b=>b.at[0]===9 && b.at[1]===4 && b.notes[0]?.fret===12)""")
                if (len(requests) != 2 or len(replies) != 2 or requests[0].get('action') != 'place' or
                        requests[1].get('op') != 'note_set' or requests[1]['revision'] != replies[0]['revision'] or
                        requests[1]['beat'] != replies[0]['selection']['beats'][0] or
                        requests[1]['note']['id'] != replies[0]['selection']['notes'][0]):
                    raise RuntimeError('Packaged rapid fret12 did not chain its own revision/source identity')
                check_placement(replies[0],74,12,replies[1]['revision'])
                page.locator('[data-action=undo]').click()
                check_placement(replies[0],63,1)
                page.locator('[data-action=undo]').click()
                page.wait_for_function('revision => !EDQ.n && SCORE.view?.revision===revision', arg=view['revision'])
                if place_song.read_bytes() != before:
                    raise RuntimeError('Two per-digit Undo steps did not restore the exact fixture bytes')
                print('ok packaged direct TAB fret12: strict Place, stable IDs/caret/rests, per-digit byte-exact Undo')
            if fit_song is not None:
                before = fit_song.read_bytes()
                page.evaluate("async()=>{tab('tab');setCursor(0,0,0,0);await scoreRefresh()}")
                page.wait_for_function("SCORE.view?.order===0 && !EDQ.n && !LV.playing")
                inspector = page.locator('.vt-tab-inspector')
                if not inspector.evaluate('e=>e.open'):
                    inspector.locator(':scope > summary').click()
                page.locator('[data-ui=at]').fill('0')
                page.locator('[data-action=go]').click()
                fit = page.locator('[data-ui=fit]')
                if fit.is_checked():
                    raise RuntimeError('Packaged duration fit must default to unchecked')
                fit.check()
                page.locator('[data-ui=duration]').select_option('2')
                page.locator('[data-ui=dots]').select_option('0')
                page.locator('[data-ui=tuple-n]').fill('1')
                page.locator('[data-ui=tuple-d]').fill('1')
                with page.expect_response('**/api/score_command') as fit_response:
                    page.locator('[data-action=duration]').click()
                result = fit_response.value.json()
                if result.get('error') or result.get('fit',{}).get('outcome') != 'shifted':
                    raise RuntimeError(f'Packaged duration fit did not shift through the whole rest: {result}')
                page.wait_for_function('revision=>!EDQ.n && SCORE.view?.revision===revision',arg=result['revision'])
                expected = {b['id']:json.loads(json.dumps(b)) for b in view['score']['patterns']['A']['beats'] if b['id']!='r'}
                expected['a']['written'] = dict(value=2,dots=0,tuplet=[1,1])
                expected['b']['at'] = [2,1]
                actual = page.evaluate('SCORE.view.score.patterns.A.beats')
                if ({b['id']:b for b in actual} != expected or
                        fit_response.value.request.post_data_json.get('fit') != 'tg_duration' or
                        result['selection']['beats'] != ['a'] or result['selection']['at'] != [0,1] or
                        page.evaluate('[CUR.score.at,CUR.score.beat]') != [[0,1],'a'] or
                        page.locator('[data-ui=duration]').input_value() != '2'):
                    raise RuntimeError('Packaged duration fit lost source identity, applied duration or exact rest transformation')
                page.locator('[data-action=undo]').click()
                page.wait_for_function('revision=>!EDQ.n && SCORE.view?.revision===revision',arg=view['revision'])
                if fit_song.read_bytes() != before:
                    raise RuntimeError('Packaged fit Undo did not restore exact fixture bytes')
                _, raw_state = get(base+'/api/state',token=token)
                history = {key:json.loads(raw_state)[key] for key in ('undo','redo')}
                page.locator('[data-ui=duration]').select_option('4')
                with page.expect_response('**/api/score_command') as noop_response:
                    page.locator('[data-action=duration]').click()
                noop = noop_response.value.json()
                page.wait_for_function("!EDQ.n && !document.querySelector('[data-ui=fit]').disabled")
                _, raw_state = get(base+'/api/state',token=token)
                if (noop.get('fit',{}).get('outcome') != 'unchanged' or noop.get('revision') != view['revision'] or
                        {key:json.loads(raw_state)[key] for key in ('undo','redo')} != history or
                        not history['redo'] or fit_song.read_bytes() != before):
                    raise RuntimeError('Packaged unchanged fit altered bytes, revision or Undo/Redo')
                print('ok packaged fit: unchecked default, checkbox/duration whole-rest shift, exact Undo, unchanged fit retained redo')
            if capo_song is not None:
                # The owner's fix2 retest: Capo through the real Setup spinner, closed with Escape (no Apply track).
                import numpy as np

                def wait(what, js, arg=None):
                    try:
                        page.wait_for_function(js, arg=arg)
                    except Exception as e:
                        raise RuntimeError(f'Packaged capo: timed out waiting for {what}: '
                                           f"{page.evaluate('[S.own?.status, LV.key === lvKey(), LV.err, EDQ.n]')} capo field/score "
                                           f"{page.evaluate('[document.querySelector(`[data-ui=capo]`).value, Object.values(SCORE.view.score.tracks)[0].capo]')} "
                                           f"TAB status: {page.locator('.vt-tab-status').inner_text()!r}") from e
                before = capo_song.read_bytes()
                track = next(iter(view['score']['tracks']))

                def first_note_peak():
                    wait('the SONG render', "S.own?.status === 'ready' && S.own.key")
                    body = page.request.get(page.evaluate("new URL(tok(srcFor(null)), location.href).href")).body()
                    with wave.open(io.BytesIO(body), 'rb') as wav:
                        rate, pcm = wav.getframerate(), np.frombuffer(wav.readframes(wav.getnframes()), np.int16)
                        mono = pcm.reshape(-1, wav.getnchannels()).mean(axis=1)
                    start = int(np.argmax(np.abs(mono) > 100)) + int(0.05 * rate)
                    window = mono[start:start + int(0.35 * rate)]
                    spectrum = np.abs(np.fft.rfft(window * np.hanning(len(window)), 8 * len(window)))
                    return np.argmax(spectrum) * rate / (8 * len(window))

                def snapshot():
                    _, raw = get(base + '/api/playback?sample_rate=48000', token=token)
                    plan = sorted(e['pitch'] for e in json.loads(raw)['plan']['events'] if e['type'] == 'note_on')
                    _, raw = get(base + '/api/pattern/0?' + urlencode({'occurrence': view['score']['order_ids'][0]}), token=token)
                    cells = [c for row in json.loads(raw)['display_rows'] for c in row if c[:3] not in ('...', '===', '^^^', '~~~')]
                    return plan, cells, first_note_peak(), page.evaluate('S.own.key')

                page.evaluate("tab('tab')")
                page.locator('[data-ui=track]').select_option(track)
                plan0, cells0, peak0, key0 = snapshot()
                start = view['score']['tracks'][track].get('capo', 0)   # the song may already have a capo
                page.locator('[data-action=setup]').click()
                page.locator('[data-ui=capo]').focus()   # a click can land on the spinner and step it too
                page.keyboard.press('ArrowUp')
                page.keyboard.press('ArrowUp')
                page.keyboard.press('Escape')
                wait(f'capo {start + 2} in the score', f"SCORE.view?.score?.tracks?.[{json.dumps(track)}]?.capo === {start + 2} && !EDQ.n")
                wait('a new SONG render', f"S.own?.key && S.own.key !== {json.dumps(key0)}")
                plan1, cells1, peak1, _ = snapshot()
                from vulturetracker import api
                if api.from_yaml(capo_song.read_text(encoding='utf-8'))['score']['tracks'][track].get('capo') != start + 2:
                    raise RuntimeError('Packaged capo did not reach the song file')
                if plan1 != [p + 2 for p in plan0]:
                    raise RuntimeError(f'Packaged capo: live engine pitches {plan0[:4]} -> {plan1[:4]}, not +2')
                if cells1 == cells0:
                    raise RuntimeError('Packaged capo: Pattern view cells unchanged')
                if abs(peak1 / peak0 - 2 ** (2 / 12)) > 0.01:
                    raise RuntimeError(f'Packaged capo: render fundamental {peak0:.1f} -> {peak1:.1f} Hz, not +2 semitones')
                if not page.locator('.vt-tab-meter').inner_text().startswith(f'Capo {start + 2}'):
                    raise RuntimeError(f'Packaged capo: no "Capo {start + 2}" label')
                _, raw = get(base + '/api/state', token=token)
                if json.loads(raw)['undo'] != 2:
                    raise RuntimeError('Packaged capo: each spinner step must be its own Undo step')
                page.locator('[data-action=undo]').click()
                wait('the first Undo', f"!EDQ.n && SCORE.view?.score?.tracks?.[{json.dumps(track)}]?.capo === {start + 1}")
                page.locator('[data-action=undo]').click()
                wait('the second Undo', 'revision=>!EDQ.n && SCORE.view?.revision===revision', view['revision'])
                if capo_song.read_bytes() != before:
                    raise RuntimeError('Packaged capo Undo did not restore exact song bytes')
                # Back-to-back retunes can answer a live load with the server's "inputs changed ... retry"; the page
                # reloads on the next revision. Accept that answer only if the live engine ends current and error-free.
                wait('the live engine on the current song', "!LV.key || (LV.key === lvKey() && !LV.err)")
                failed_responses[:] = [r for r in failed_responses if 'Playback inputs changed during preparation' not in r.text()]
                print(f'ok packaged capo: two spinner steps from capo {start} applied at once, no Apply (two Undo steps); file, Pattern cells '
                      f'({cells0[0]} -> {cells1[0]}), live pitches +2, render {peak0:.1f} -> {peak1:.1f} Hz, "Capo {start + 2}" label, byte-exact Undo')
            if it_song is not None:
                # RENDER & EXPORT -> IT of a native score in the packaged app, reopened here without any native plan.
                from tests.test_tablature_sync import it_cells
                from vulturetracker import api as source_api
                before = it_song.read_bytes()
                destination = it_song.parent / 'native-it-export'
                page.locator('[data-t=export]').click()
                page.locator('#export-format').select_option('it')
                page.locator('#export-dest').fill(str(destination))
                page.locator('#export-name').fill('native')
                page.locator('#export-replace').check()   # rerun this harness's own export in the copied fixture
                previous_job = page.evaluate('S.export?.job_id || null')
                with page.expect_response(lambda r: r.url.endswith('/api/export') and r.request.method == 'POST') as exporting:
                    page.locator('#export-go').click()
                if exporting.value.status != 200 or exporting.value.json().get('error'):
                    raise RuntimeError(f'Packaged IT export request: {exporting.value.json()}')
                page.wait_for_function("previous=>S.export?.job_id && S.export.job_id!==previous && ['done','error','failed','cancelled'].includes(S.export.status)", arg=previous_job)
                if page.evaluate('S.export.status') != 'done':
                    raise RuntimeError(f"Packaged native IT export: {page.evaluate('S.export')}")
                cells, rows, seconds = it_cells((destination / 'native.it').read_bytes())
                attacks = [(r, ch, n, v) for r, ch, n, v, *_ in cells if n is not None and n < 120]
                expected = [(r, ch, n, v) for r, ch, n, v, *_ in it_cells(source_api.compile_song(it_song)[0])[0]
                            if n is not None and n < 120]
                if not attacks or attacks != expected:
                    raise RuntimeError(f'Packaged native IT: {len(attacks)} attacks differ from the source build ({len(expected)})')
                from vulturetracker.itreader import read_it
                actual_module, _ = read_it((destination / 'native.it').read_bytes())
                expected_module, _ = read_it(source_api.compile_song(it_song)[0])
                if ([i.keymap for i in actual_module.instruments or []] !=
                        [i.keymap for i in expected_module.instruments or []]):
                    raise RuntimeError('Packaged native IT instrument sample/pitch keymaps differ from source')
                def instruments(module):
                    return [cell.instrument for order in module.orders if order < 254
                            for row in module.patterns[order].rows for cell in row]
                if instruments(actual_module) != instruments(expected_module):
                    raise RuntimeError('Packaged native IT note instrument routing differs from source')
                pair = source_api.prepare_playback(it_song)
                plan = pair['plan']
                # Export may subdivide rows while preserving physical IT ticks.
                # Read Axx from the actual standalone module rather than assuming
                # that its rows still use the authored score's row_step.
                row_times, quarter, speed = [], Fraction(0), actual_module.speed
                for order in actual_module.orders:
                    if order >= 254:
                        continue
                    for row in actual_module.patterns[order].rows:
                        for cell in row:
                            if cell.effect == 1 and cell.param:
                                speed = cell.param
                        row_times.append(quarter)
                        quarter += Fraction(speed, 24)
                parents = source_api.compile_song(it_song)[1].score_projection.channel_parents
                performed = []
                for e in plan['events']:
                    if e['type'] != 'note_on': continue
                    layers = e.get('layers', [dict(pitch=e['pitch'])])
                    channels = [ch for ch,parent in parents.items() if parent==e['ch']][:len(layers)-1]+[e['ch']]
                    performed.extend((Fraction(*e['at']),ch,layer['pitch']) for ch,layer in zip(channels,layers))
                # Native simultaneous events use stable note IDs; tracker rows enumerate channels.
                performed_it = [(row_times[r] + (Fraction(param & 15,24) if fx==19 and param>>4==13 else 0), ch,n)
                                for r,ch,n,v,fx,param in cells if n is not None and n<120]
                if sorted(performed_it) != sorted(performed):
                    raise RuntimeError('Packaged native IT attack order/timing differs from native playback')
                # IT rounds audio tick lengths; the native plan uses exact rational frames.
                tolerance = float(Fraction(*plan['duration']['quarters']) * 24 / 44100) + 1 / 44100
                if abs(seconds - plan['duration']['frames'] / plan['sample_rate']) > tolerance:
                    raise RuntimeError('Packaged native IT duration differs from native playback beyond tick rounding')
                from vulturetracker.tablature import _IT_TECHNIQUES
                authored = source_api.from_yaml(before.decode('utf-8-sig'))
                if any(n.get(k) for p in authored['score']['patterns'].values() for b in p['beats']
                       for n in b['notes'] for k in _IT_TECHNIQUES):
                    from vulturetracker.openmpt import LoadedModule
                    from tests.test_pipeline import left, rms
                    paired = source_api.prepare_playback(it_song, sample_rate=48000)
                    with LoadedModule(paired['backing_it'], 48000, 1, plan=paired['plan']) as native:
                        reference = left(native.render(rate=48000, oversample=1, max_seconds=seconds))
                    with LoadedModule((destination / 'native.it').read_bytes(), 48000, 1) as standalone:
                        actual = left(standalone.render(rate=48000, oversample=1, max_seconds=seconds))
                    ratio = rms(actual) / rms(reference)
                    if abs(ratio - 1) > .04:
                        raise RuntimeError(f'Packaged technique IT rendered RMS differs from native: {ratio}')
                    print(f'ok packaged technique IT rendered without a plan: RMS/native {ratio:.4f}')
                if authored['module'].get('title') in ('Native IT pitch fixture', 'Native IT whammy fixture'):
                    from tests.test_tablature_sync import pitch_render_metrics
                    whammy = authored['module']['title'] == 'Native IT whammy fixture'
                    if 'IT pitch:' not in page.locator('#export-result').inner_text():
                        raise RuntimeError('Packaged pitch export lost the quantization warning')
                    for rate in (48000, 44100):
                        paired = source_api.prepare_playback(it_song, sample_rate=rate)
                        renders = []
                        for backing, plan in [(paired['backing_it'], paired['plan']), ((destination / 'native.it').read_bytes(), None)]:
                            with LoadedModule(backing, rate, 1, plan=plan) as played:
                                renders.append(played.render(rate=rate, oversample=1, max_seconds=2))
                        metrics = pitch_render_metrics(*renders, rate, whammy=whammy, plan=paired['plan'])
                        for name in (('dive', 'raise', 'mixed') if whammy else ('bend', 'vibrato', 'slide')):
                            if metrics[name]['cents'] > 38.5 or metrics[name]['milliseconds'] > 1000 / 48 + 1000 / (390 if whammy else 441) + 72000 / rate:
                                raise RuntimeError(f'Packaged pitch trajectory exceeds bound: {rate}, {metrics}')
                        endpoints = {'bar_low': -206.25, 'bar_high': 206.25, 'mixed_low': -93.75, 'mixed_high': 93.75} if whammy else {'bend_peak': 206.25}
                        bad_cycle = max(metrics['cycle_error_cents']) > 75 if whammy else min(metrics['minimum_cycle_cents']) < -1
                        if bad_cycle or abs(metrics['plain'][1]) > .5 or any(abs(metrics[k][1] - v) > .5 for k, v in endpoints.items()):
                            raise RuntimeError(f'Packaged pitch endpoints differ: {metrics}')
                        print(f'ok packaged pitch {rate}: {metrics}')
                if authored['module'].get('title') == 'Native IT harmonic layers':
                    from tests.test_tablature_sync import harmonic_render_metrics
                    for rate in (48000,44100):
                        paired=source_api.prepare_playback(it_song,sample_rate=rate)
                        renders=[]
                        for backing,plan in ((paired['backing_it'],paired['plan']),((destination/'native.it').read_bytes(),None)):
                            with LoadedModule(backing,rate,1,plan=plan) as played:
                                renders.append(played.render(rate=rate,oversample=1,max_seconds=4.2))
                        metrics=harmonic_render_metrics(*renders,rate,paired['plan'])
                        for attack,event in zip(metrics['attacks'],(e for e in paired['plan']['events'] if e['type']=='note_on')):
                            expected_shift=int(Fraction(*event['at'])*24)*int(rate*2.5/120)-event['frame']
                            if abs(attack['shift_frames']-expected_shift)>1 or attack['settled_error']>.02 or any(max(abs(c) for c in l['cents'])>.5 or abs(l['gain_ratio']-1)>.027 for l in attack['layers']):
                                raise RuntimeError(f'Packaged harmonic layer render mismatch: {rate}, {attack}')
                        if abs(metrics['last_audible_frames'][1]-metrics['last_audible_frames'][0])>(1 if rate==48000 else 176):
                            raise RuntimeError(f'Packaged harmonic release mismatch: {metrics}')
                        print(f'ok packaged harmonic layers {rate}: {metrics}')
                if authored['module'].get('title') == 'Native IT articulations':
                    plain = copy.deepcopy(authored)
                    for spec in plain['score']['patterns'].values():
                        for beat in spec['beats']:
                            for note in beat['notes']:
                                for flag in ('tapping','slapping','popping'): note.pop(flag,None)
                    if 'IT notation: tapping, slapping, popping markings omitted' not in page.locator('#export-result').inner_text():
                        raise RuntimeError('Packaged articulation export lost its notation-loss warning')
                    if source_api.compile_song(plain,it_song.parent)[0] != (destination/'native.it').read_bytes():
                        raise RuntimeError('Notation-only marks changed standalone IT bytes')
                    print('ok packaged articulation marks are sound-neutral; visible notation-loss warning')
                if authored['module'].get('title') in ('Four bars - notation','Four bars - lyrics','Four bars - tempo units'):
                    plain=copy.deepcopy(authored)
                    for track in plain['score']['tracks'].values():track.pop('lyrics',None)
                    for measure in plain['score'].get('measures',[]):measure.pop('tempo_unit',None)
                    for spec in plain['score']['patterns'].values():
                        for beat in spec['beats']:beat.pop('chord',None)
                    for label in ('IT notation: lyrics omitted','IT notation: chord diagrams omitted'):
                        if label not in page.locator('#export-result').inner_text():raise RuntimeError('Packaged export lost '+label)
                    if source_api.compile_song(plain,it_song.parent)[0]!=(destination/'native.it').read_bytes():
                        raise RuntimeError('Lyrics/diagrams changed musical IT data')
                    print('ok packaged lyrics/diagrams/tempo units: visible loss warnings and sound-neutral IT bytes')
                if authored['module'].get('title') in ('Native IT swing','Native IT articulations'):
                    from tests.test_tablature_sync import swing_render_metrics
                    for rate in (48000,44100):
                        print(f'ok packaged swing {rate}: {swing_render_metrics(it_song,(destination/"native.it").read_bytes(),rate)}')
                if authored['module'].get('title') == 'Native IT fade':
                    from tests.test_tablature_sync import fade_render_metrics
                    if 'IT fade_in:' not in page.locator('#export-result').inner_text():
                        raise RuntimeError('Packaged fade export lost its approximation warning')
                    for rate in (48000,44100):
                        metrics=fade_render_metrics(it_song,(destination/'native.it').read_bytes(),rate)
                        print(f'ok packaged fade {rate}: { {k:v for k,v in metrics.items() if k!="checks"} }')
                if authored['module'].get('title') == 'Native IT strokes':
                    from tests.test_tablature_sync import stroke_render_metrics
                    for rate in (48000,44100):
                        print(f'ok packaged strokes {rate}: {stroke_render_metrics(it_song,(destination/"native.it").read_bytes(),rate)}')
                if authored['module'].get('title') in ('Native IT repeat pulses','Native IT grace notes'):
                    from tests.test_tablature_sync import repetition_render_metrics
                    grace = authored['module']['title'] == 'Native IT grace notes'
                    if not grace and 'IT repetition:' not in page.locator('#export-result').inner_text():
                        raise RuntimeError('Packaged repetition export lost the final-keyoff warning')
                    for rate in (48000,44100):
                        paired = source_api.prepare_playback(it_song,sample_rate=rate)
                        renders = []
                        for backing,plan in [(paired['backing_it'],paired['plan']),((destination/'native.it').read_bytes(),None)]:
                            with LoadedModule(backing,rate,1,plan=plan) as played:
                                renders.append(played.render(rate=rate,oversample=1,max_seconds=2.2))
                        metrics = repetition_render_metrics(*renders,rate,paired['plan'])
                        for actual,event in zip(metrics['attacks'],[e for e in paired['plan']['events'] if e['type']=='note_on']):
                            if grace:
                                expected_shift=int(Fraction(*event['at'])*24)*int(rate*2.5/120)-event['frame']
                                if abs(actual['shift_frames']-expected_shift)>1:
                                    raise RuntimeError(f'Packaged grace attack timing differs: {rate}, {actual}')
                            if (abs(actual['shift_frames']) > event['frame']/rate*48+3 or actual['settled_rms_error']>.025 or
                                abs(actual['settled_level_ratio' if grace else 'level_ratio']-1)>(.02 if grace else .015) or abs(actual['pitch_cents'][1]-(200 if event['pitch']==66 else 0))>.5):
                                raise RuntimeError(f'Packaged repetition render mismatch: {rate}, {actual}')
                        if abs(metrics['last_audible_frames'][1]-metrics['last_audible_frames'][0]) > rate/1920+100:
                            raise RuntimeError(f'Packaged repetition release mismatch: {metrics}')
                        print(f'ok packaged {"grace" if grace else "repetition"} {rate}: {metrics}')
                if it_song.read_bytes() != before:
                    raise RuntimeError('Packaged native IT export changed the song file')
                print(f'ok packaged native IT export: {len(attacks)} attacks over {rows} rows, {seconds:.3f} s reopened '
                      f'without a plan, equal to the source build; volumes {sorted({v for *_, v in attacks if v is not None})}')
                if prepared_original is not None:
                    page.evaluate("tab('tab');setEdit(true)")
                    page.click('[data-action=undo]')
                    page.wait_for_function('revision=>SCORE.view.revision===revision&&!SCORE.busy', arg=prepared_revision)
                    if it_song.read_bytes() != prepared_original:
                        raise RuntimeError('Preparation and standalone IT qualification did not restore the source')
                    print('ok packaged preparation resolves standalone IT refusal; exact Undo')
            if error:
                errors.append(str(error))
            # Import/edit/reopen can invalidate a preparation already in flight.
            # This is a retry response, accepted only after the actual engine has
            # loaded the current revision without an error (as in the capo check).
            retries = [r for r in failed_responses if r.status == 400 and
                       '/api/playback?' in r.url and r.json().get('error') ==
                       'Playback inputs changed during preparation; retry with the current song and mix']
            if retries:
                page.wait_for_function('LV.key===lvKey()&&!LV.err&&!LV.loading&&!LV.preparing&&LV.planRevision?.startsWith(S.version.hash)')
                failed_responses[:] = [r for r in failed_responses if r not in retries]
                print(f'ok current playback revision recovered after {len(retries)} superseded preparations')
            # Closing a song discards its render registry. Requests already in
            # flight can receive 404; qualify only keys observed on closed songs,
            # and require the current audio, spectrum and meters to load instead.
            closed_assets = []
            if closed_render_keys:
                import re
                page.wait_for_function("S.own?.status==='ready'&&lastSrc==='/wav/'+S.own.key")
                current_key = page.evaluate('S.own.key')
                for response in failed_responses:
                    match = re.search(r'/(?:api/meters|spec|wav)/([^/?]+)', response.url)
                    if response.status == 404 and match and match[1] != current_key and match[1] in closed_render_keys:
                        closed_assets.append(response)
                if closed_assets:
                    for route in ('wav', 'spec', 'api/meters'):
                        response = page.request.get(base + '/' + route + '/' + current_key + '?' + urlencode({'token': token}))
                        if response.status != 200:
                            raise RuntimeError(f'Current {route} failed after song switching: {response.status}')
                    page.wait_for_function("audio.readyState>=2&&$('specimg').complete&&$('specimg').naturalWidth>0")
                    failed_responses[:] = [r for r in failed_responses if r not in closed_assets]
                    print(f'ok current audio/spectrum/meters after {len(closed_assets)} closed-song asset requests')
            # A response invalidated by navigation can retain its status while
            # its body request never resolves. Report remaining failures without
            # another blocking body read; never turn them into a passing check.
            errors.extend(f'{r.status} {r.url}' for r in tuple(failed_responses))
            if errors:
                raise RuntimeError('; '.join(errors))
            print(f'ok packaged native TAB: {expected_bars} written bars retained across navigation/playback; '
                  'direct score caret/navigation, native piano, pitched fretboard/catalogue, chord suggestions, local assets and live WASM')
        finally:
            browser.close()


def headless(cmd, song, timeout, browser=False, gp5_export=False, place=False, fit=False, capo=False, native_it=False,
             shortcut=None, launch_arguments=None, working=ROOT):
    """Start `cmd gui song --no-browser --port N`, wait for /api/state, GET /, stop it. Returns the failures."""
    port = free_port()
    base = f"http://127.0.0.1:{port}"
    log = ROOT / "build" / "exe_check.log"
    log.parent.mkdir(exist_ok=True)
    fails = []
    with open(log, "wb") as out:
        args = launch_arguments if launch_arguments is not None else ['gui',str(song)]
        proc = subprocess.Popen(cmd + args + ([] if shortcut else ['--no-browser']) + ['--port',str(port)],
                                cwd=working, stdout=out, stderr=subprocess.STDOUT,
                                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform=='win32' else 0)
        try:
            deadline = time.monotonic() + timeout
            state = None
            while time.monotonic() < deadline:
                if proc.poll() is not None:
                    fails.append(f"the app exited early with code {proc.returncode} (see {log})")
                    break
                try:
                    token = app_token(port)
                    if not token:
                        raise OSError("running.json does not name this port yet")
                    status, body = get(base + "/api/state", token=token)
                    state = json.loads(body)
                    break
                except (OSError, ValueError):
                    time.sleep(0.5)
            if state is None and not fails:
                fails.append(f"/api/state did not answer within {timeout} s (see {log})")
            if state is not None:
                song_state = state.get("song") or {}
                facts = song_state.get('facts') or {}
                print(f"ok /api/state on port {port}: {song_state.get('path', '?')} ({facts.get('title', '?')})")
                try:
                    status, page = get(base + "/", token=token)
                    if status != 200 or b"<html" not in page.lower():
                        fails.append(f"GET / returned {status}, {len(page)} bytes without <html")
                    else:
                        print(f"ok GET / {len(page)} bytes")
                    if facts.get('native_score'):
                        _, raw = get(base + '/api/playback?sample_rate=48000', timeout=timeout, token=token)
                        pair = json.loads(raw)
                        if (pair.get('song') != str(song) or pair.get('sample_rate') != 48000 or
                                not pair.get('backing_it') or not pair.get('plan') or not pair.get('revision')):
                            fails.append('native playback response is missing its paired backing/plan or identity')
                        else:
                            print(f"ok native playback pair: {len(pair['plan']['events'])} score events at 48000 Hz")
                        if browser:
                            held_parents = {e['ch'] for e in pair['plan']['events']
                                            if e.get('hold') or e.get('context')}
                            last_held_attack = max((e['frame'] for e in pair['plan']['events']
                                if e['type'] == 'note_on' and e['ch'] in held_parents), default=0)
                            shortcut_context=None
                            if shortcut:
                                lines=subprocess.check_output(['netstat','-ano','-p','tcp'],text=True).splitlines()
                                pids={int(line.split()[-1]) for line in lines if len(line.split())>=5 and line.split()[1]==f'127.0.0.1:{port}' and line.split()[3]=='LISTENING'}
                                if len(pids)!=1:raise RuntimeError('Cannot identify owned shortcut dialog process')
                                shortcut_context=(shortcut,pids.pop())
                            native_page(base, token, timeout, last_held_attack,
                                        pair['plan']['duration']['frames'] / pair['sample_rate'], gp5_export,
                                        song if place else None, song if fit else None, song if capo else None,
                                        song if native_it else None,shortcut_context)
                    elif browser:
                        fails.append('--browser requires a native score fixture')
                except OSError as e:
                    fails.append(f"GET / failed: {e}")
                except Exception as e:
                    import traceback
                    traceback.print_exc()
                    fails.append(f'packaged page check failed: {e}')
        finally:
            if proc.poll() is None:  # a onefile exe runs Python as a child: kill the tree, not just the bootloader
                if sys.platform == "win32":
                    subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)], capture_output=True)
                proc.kill()
                proc.wait(timeout=30)
    return fails


def main(argv=None):
    sys.stdout.reconfigure(errors="replace")  # selfcheck lines may carry non-ASCII paths; a cp1252 console must not stop it
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("exe", nargs="?", help="the exe to check (default dist/vulturetracker.exe)")
    ap.add_argument("--cmd", help="a command instead of an exe, e.g. \"python tools/exe_entry.py\"")
    ap.add_argument("--song", help="the song to open headless (default demo2/iron_relay.yaml; unavailable with --place or --fit)")
    ap.add_argument("--timeout", type=float, default=60, help="seconds to wait for /api/state (default 60)")
    ap.add_argument('--browser', action='store_true', help='Also exercise native TAB/assets/live WASM in headless Chromium (Playwright and browser resource lease required)')
    ap.add_argument('--gp5-export', action='store_true', help='With --browser, export the native fixture through the page and read back its GP5 counts')
    ap.add_argument('--place', action='store_true', help='With --browser, use a temporary piano fixture to check Place insertion and exact Undo (no --song)')
    ap.add_argument('--fit', action='store_true', help='With --browser, use a temporary model fixture to check duration fit, exact Undo and unchanged fit (no --song or --place)')
    ap.add_argument('--capo', action='store_true', help='With --browser and --song (a copy: it is edited, then undone), set Capo 2 through Setup and check file, Pattern cells, live pitches, render pitch and the label')
    ap.add_argument('--native-it', action='store_true', help='With --browser and --song (a copy), export the native score as IT through RENDER & EXPORT and reopen it without a plan')
    ap.add_argument('--song-shortcut',type=Path,help='Windows desktop lease: normal app native Save/overwrite-cancel dialog, real link readback and exact target/song launch; new .lnk test path')
    a = ap.parse_args(argv)
    if a.song_shortcut and (sys.platform!='win32' or not a.browser or not a.song or a.cmd or a.song_shortcut.exists()):
        ap.error('--song-shortcut needs Windows, packaged exe, --browser, --song and a new .lnk test path')
    if a.native_it and (not a.browser or not a.song):
        ap.error('--native-it requires --browser and --song (a copy of a native song)')
    if a.capo and (not a.browser or not a.song):
        ap.error('--capo requires --browser and --song (a copy of a native song)')
    if a.gp5_export and not a.browser:
        ap.error('--gp5-export requires --browser')
    if a.place and (not a.browser or a.song):
        ap.error('--place requires --browser and its own temporary fixture; do not supply --song')
    if a.fit and (not a.browser or a.song or a.place):
        ap.error('--fit requires --browser and its own temporary fixture; do not supply --song or --place')
    if a.cmd:
        cmd = shlex.split(a.cmd, posix=sys.platform != "win32")  # POSIX mode would eat Windows backslashes
    else:
        exe = Path(a.exe or ROOT / "dist" / "vulturetracker.exe").resolve()
        if not exe.exists():
            ap.error(f"no such exe: {exe}")
        cmd = [str(exe)]
        print(("ok" if (exe.parent / "ffmpeg.exe").exists() else "FAIL") + f" ffmpeg.exe beside {exe.name}")
    if a.place or a.fit:
        from tests.test_gui import RATE, sine
        from vulturetracker import api
        from vulturetracker.wavload import write_wav
        with tempfile.TemporaryDirectory(prefix='vt-fit-check-' if a.fit else 'vt-place-check-') as folder:
            song = Path(folder) / 'song.yaml'
            if a.fit:
                from tests.test_tablature import TestPlaceFitCommand
                fixture, _ = TestPlaceFitCommand().fixture()
                fixture['samples'][1]['file'] = 'a.wav'
            else:
                from tests.test_tablature_page import TestTablaturePage
                fixture = TestTablaturePage.piano_song()
                fixture['score']['tracks']['guitar']['max_fret'] = 29
                next(b for b in fixture['score']['patterns']['verse']['beats'] if b['id'] == 'rest').pop('text')
            write_wav(song.parent / 'a.wav', RATE, [sine(440)])
            song.write_bytes(api.to_yaml(fixture).encode('utf-8'))
            fails = headless(cmd, song, a.timeout, a.browser, a.gp5_export, place=a.place, fit=a.fit)
    else:
        song = (ROOT / (a.song or "demo2/iron_relay.yaml")).resolve()
        if not song.exists():
            ap.error(f"no such song: {song}")
        fails = headless(cmd, song, a.timeout, a.browser, a.gp5_export, capo=a.capo, native_it=a.native_it,
                         shortcut=a.song_shortcut.resolve() if a.song_shortcut else None)
        if a.song_shortcut and not fails:
            from tests.test_gui import read_song_shortcut
            link=read_song_shortcut(a.song_shortcut.resolve())
            expected=['gui',str(song)]
            if Path(link['target'])!=Path(cmd[0]) or link['args']!=subprocess.list2cmdline(expected) or Path(link['cwd'])!=Path(cmd[0]).parent:
                fails.append(f'Incorrect packaged shortcut readback: {link}')
            else:
                fails.extend(headless([link['target']],song,a.timeout,launch_arguments=expected,working=link['cwd']))
                print('ok shortcut exact target/arguments/working-directory readback and launch')
    r = subprocess.run(cmd + ["--selfcheck"], cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace")
    print((r.stdout or "").rstrip() or "(no selfcheck output)")
    if r.returncode != 0:
        fails.append(f"--selfcheck exited {r.returncode}" + (f": {r.stderr.strip().splitlines()[-1]}" if r.stderr.strip() else ""))
    if not a.cmd and not (Path(cmd[0]).parent / "ffmpeg.exe").exists():
        fails.append("ffmpeg.exe is not beside the exe (the MP3/OGG/FLAC export needs it)")
    for f in fails:
        print("FAIL " + f)
    print("exe check:", "FAILED" if fails else "passed")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
