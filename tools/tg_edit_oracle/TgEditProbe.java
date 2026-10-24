import java.nio.file.*;
import java.io.*;
import java.util.*;
import app.tuxguitar.io.base.*;
import app.tuxguitar.io.tg.TGSongReaderImpl;
import app.tuxguitar.io.tg.TGSongWriterImpl;
import app.tuxguitar.song.factory.TGFactory;
import app.tuxguitar.song.helpers.TGSongSegment;
import app.tuxguitar.song.helpers.TGSongSegmentHelper;
import app.tuxguitar.song.helpers.TGStoredBeatList;
import app.tuxguitar.song.managers.TGSongManager;
import app.tuxguitar.song.models.*;
import app.tuxguitar.graphics.control.TGFactoryImpl;
import app.tuxguitar.graphics.control.TGMeasureImpl;
import app.tuxguitar.graphics.control.TGVoiceImpl;
import app.tuxguitar.util.TGVersion;

/**
 * Applies a TuxGuitar editing sequence with TuxGuitar 2.1.0's own managers, headless, and writes the result.
 * Usage: java --class-path "C:\Program Files\tuxguitar\lib\*" TgEditProbe.java input.tg ops.txt output.tg
 * One operation per line; measures are 1-based, positions are quarter notes within the measure as n/d, voices
 * 0-based, the first track is edited. Each operation calls what the pinned TuxGuitar action calls (named below).
 */
public class TgEditProbe {
    static final TGFactory factory = new TGFactory();
    static final TGSongManager manager = new TGSongManager(factory);

    static TGSong read(Path path) throws Exception {
        TGSongReaderHandle handle = new TGSongReaderHandle(); handle.setFactory(factory);
        try (InputStream in = Files.newInputStream(path)) { handle.setInputStream(in); new TGSongReaderImpl().read(handle); }
        return handle.getSong();
    }

    static void write(TGSong song, Path path) throws Exception {
        TGSongWriterHandle handle = new TGSongWriterHandle(); handle.setFactory(factory); handle.setSong(song);
        try (OutputStream out = Files.newOutputStream(path)) { handle.setOutputStream(out); new TGSongWriterImpl().write(handle); }
    }

    static long quarters(String text) {   // n/d quarter notes as TuxGuitar precise time
        String[] p = text.split("/");
        long q = TGDuration.toPreciseTime(TGDuration.QUARTER_TIME);
        long n = Long.parseLong(p[0]) * q, d = p.length > 1 ? Long.parseLong(p[1]) : 1;
        if (n % d != 0) throw new IllegalArgumentException("position not on TuxGuitar's precise grid: " + text);
        return n / d;
    }

    static TGDuration duration(String value, String dots, String enters, String times) {
        TGDuration d = factory.newDuration();
        d.setValue(Integer.parseInt(value)); d.setDotted(dots.equals("1")); d.setDoubleDotted(dots.equals("2"));
        d.getDivision().setEnters(Integer.parseInt(enters)); d.getDivision().setTimes(Integer.parseInt(times));
        return d;
    }

    static TGMeasure measure(TGTrack track, String number) { return track.getMeasure(Integer.parseInt(number) - 1); }

    static TGBeat beat(TGMeasure m, String at) {
        long start = TGDuration.toPreciseTime(m.getStart()) + quarters(at);
        for (TGBeat b : m.getBeats()) if (b.getPreciseStart() == start) return b;
        throw new IllegalArgumentException("no beat at " + at + " in measure " + m.getNumber());
    }

    static void stemGroup(TGMeasure original, String at, int voiceIndex, String stem) {
        // The live editor completes rests before calculateBeats. Use its installed
        // canJoin and division length, without creating a display or duplicating
        // their duration/meter rules. Only calculateBeats' per-voice traversal is
        // reproduced here; graphical layout and group painting are not exercised.
        manager.getMeasureManager().autoCompleteSilences(original);
        manager.getMeasureManager().orderBeats(original);
        manager.updatePreciseStart(original.getTrack());
        TGFactory graphical = new TGFactoryImpl() {
            public TGMeasure newMeasure(TGMeasureHeader header) {
                return new TGMeasureImpl(header) {
                    public long getDivisionLength() { return TGSongManager.getDivisionLength(getHeader()); }
                };
            }
        };
        TGMeasureImpl m = (TGMeasureImpl) original.clone(graphical, original.getHeader().clone(graphical));
        TGVoiceImpl selected = (TGVoiceImpl) beat(m, at).getVoice(voiceIndex);
        if (selected.isEmpty() || selected.isRestVoice()) return;
        TGVoiceImpl previous = null;
        List<TGVoiceImpl> group = null, selectedGroup = null;
        for (TGBeat b : m.getBeats()) {
            TGVoiceImpl current = (TGVoiceImpl) b.getVoice(voiceIndex);
            if (current.isEmpty()) continue;
            if (!current.isRestVoice()) {
                if (group == null || !m.canJoin(manager, current, previous)) group = new ArrayList<>();
                group.add(current);
                if (current == selected) selectedGroup = group;
            }
            previous = current;
        }
        if (selectedGroup == null) throw new IllegalStateException("no selected beat group");
        int direction = switch (stem) {
            case "up" -> TGVoice.DIRECTION_UP;
            case "down" -> TGVoice.DIRECTION_DOWN;
            case "auto" -> TGVoice.DIRECTION_NONE;
            default -> throw new IllegalArgumentException("invalid stem: " + stem);
        };
        for (TGVoiceImpl current : selectedGroup) for (TGBeat b : original.getBeats())
            if (b.getPreciseStart().longValue() == current.getBeat().getPreciseStart().longValue())
                manager.getMeasureManager().changeVoiceDirection(b.getVoice(voiceIndex), direction);
        System.out.println("installed TG canJoin stem group: measure=" + original.getNumber()
            + " voice=" + voiceIndex + " count=" + selectedGroup.size() + " stem=" + stem);
    }

    public static void main(String[] args) throws Exception {
        if (args.length != 3) throw new IllegalArgumentException("Usage: TgEditProbe input.tg ops.txt output.tg");
        if (TGVersion.CURRENT.getMajor() != 2 || TGVersion.CURRENT.getMinor() != 1 || TGVersion.CURRENT.getRevision() != 0)
            throw new IllegalStateException("Expected TuxGuitar 2.1.0, found " + TGVersion.CURRENT);
        TGSong song = read(Path.of(args[0]));
        TGTrack track = song.getTrack(0);
        Map<TGBeat,Integer> cohortIds = new IdentityHashMap<>();
        for (int mi=0; mi<track.countMeasures(); mi++) for (TGBeat b : track.getMeasure(mi).getBeats())
            cohortIds.put(b, cohortIds.size());
        for (String line : Files.readAllLines(Path.of(args[1]))) {
            String[] a = line.trim().split("\\s+");
            if (a.length == 0 || a[0].isEmpty() || a[0].startsWith("#")) continue;
            switch (a[0]) {
                case "drop_rests_probe" -> {
                    TGMeasure m=measure(track,a[1]);
                    for (TGBeat b : new ArrayList<>(m.getBeats())) {
                        boolean empty=true;
                        for(int v=0;v<TGBeat.MAX_VOICES;v++) if(b.getVoice(v).isRestVoice()) b.getVoice(v).setEmpty(true);
                        for(int v=0;v<TGBeat.MAX_VOICES;v++) if(!b.getVoice(v).isEmpty()) empty=false;
                        if(empty) manager.getMeasureManager().removeBeat(b);
                    }
                }
                case "snapshot" -> {
                    System.out.println("SNAPSHOT " + a[1]);
                    for (int mi=0; mi<track.countMeasures(); mi++) for (TGBeat b : track.getMeasure(mi).getBeats())
                        for (int v=0; v<TGBeat.MAX_VOICES; v++) if (!b.getVoice(v).isEmpty()) {
                            TGMeasure m=track.getMeasure(mi);
                            TGVoice voice=b.getVoice(v);
                            System.out.print("measure="+m.getNumber()+" cohort="+cohortIds.get(b)+" voice="+v+" start="+
                                (b.getPreciseStart()-m.getPreciseStart())+" duration="+voice.getDuration().getPreciseTime());
                            for (TGNote n : voice.getNotes()) System.out.print(" note="+n.getString()+":"+n.getValue()+":tie="+n.isTiedNote());
                            System.out.println(voice.isRestVoice() ? " rest" : "");
                        }
                }
                case "stem_group" -> stemGroup(measure(track, a[1]), a[2], Integer.parseInt(a[3]), a[4]);
                case "beats_paste", "beats_replace", "beats_replace_probe", "beats_cut", "beats_cut_rest_live", "beats_repeat" -> { // TGCopyAction -> TGStoredBeatList; TGPasteAction -> replaceBeats
                    // The live editor fills cleaned measures before the next action.
                    for (int i = 0; i < track.countMeasures(); i++)
                        manager.getMeasureManager().autoCompleteSilences(track.getMeasure(i));
                    manager.updatePreciseStart(track);
                    long from = beat(measure(track, a[1]), a[2]).getPreciseStart();
                    long to = beat(measure(track, a[3]), a[4]).getPreciseStart();
                    List<TGBeat> selected = new ArrayList<>();
                    for (int i = 0; i < track.countMeasures(); i++) for (TGBeat b : track.getMeasure(i).getBeats())
                        if (b.getPreciseStart() >= from && b.getPreciseStart() <= to) selected.add(b);
                    selected.sort(Comparator.comparingLong(TGBeat::getPreciseStart));
                    TGStoredBeatList stored = new TGStoredBeatList(selected, track.getStrings(), track.isPercussion(), factory);
                    if (a[0].equals("beats_cut") || a[0].equals("beats_cut_rest_live")) {
                        // TGCutAction's nonempty TGNoteRange deletes the selected notes only.
                        List<TGNote> notes = new ArrayList<>();
                        int selectedVoice = a.length > 5 ? Integer.parseInt(a[5]) : 0;
                        for (TGBeat b : selected) notes.addAll(b.getVoice(selectedVoice).getNotes());
                        if (notes.isEmpty()) {
                            // TGDeleteNoteOrRestAction's rest-only branch uses
                            // the same context voice for every selected beat.
                            // Keep that raw behavior; the named reference uses
                            // each selected rest so native gap closure is explicit.
                            TGVoice caret = selected.get(0).getVoice(selectedVoice);
                            for (TGBeat b : selected) manager.getMeasureManager().removeVoice(
                                a[0].equals("beats_cut_rest_live") ? b.getVoice(selectedVoice) : caret, true);
                        }
                        for (TGNote n : notes) {
                            TGVoice v=n.getVoice(); TGBeat b=v.getBeat();
                            manager.getMeasureManager().removeNote(b.getMeasure(),b.getStart(),v.getIndex(),n.getString());
                        }
                        break;
                    }
                    long target;
                    if (a[0].equals("beats_repeat")) {
                        // TGRepeatAction goes right from the final selected beat, then pastes.
                        TGBeat last=selected.get(selected.size()-1);
                        target=last.getPreciseStart()+last.getVoice(0).getDuration().getPreciseTime();
                    } else target = TGDuration.toPreciseTime(measure(track, a[5]).getStart()) + quarters(a[6]);
                    List<TGBeat> pasted = manager.getTrackManager().replaceBeats(track, stored.clone(factory).getBeats(), target);
                    // Compare actual written notes/rests, including any lost suffix;
                    // a short returned list must not hide a musical mismatch.
                    if (a[0].equals("beats_replace_probe"))
                        System.out.println("replaceBeats copied " + selected.size() + " cohorts, returned " + pasted.size());
                    else if (pasted.isEmpty()) throw new IllegalStateException("oracle paste returned no beats");
                }
                case "free" -> manager.setFreeEditionMode(a[1].equals("on"));   // Edit > Free edition mode
                case "fret" -> {   // fret M AT VOICE STRING FRET VALUE DOTS ENTERS TIMES: TGChangeNoteAction -> addNote
                    TGMeasure m = measure(track, a[1]);
                    TGNote note = factory.newNote(); note.setString(Integer.parseInt(a[4])); note.setValue(Integer.parseInt(a[5]));
                    note.setVelocity(95);
                    manager.getMeasureManager().addNote(m, TGDuration.toTime(TGDuration.toPreciseTime(m.getStart()) + quarters(a[2])),
                        note, duration(a[6], a[7], a[8], a[9]), Integer.parseInt(a[3]));
                }
                case "duration" -> {   // duration M AT VOICE VALUE DOTS ENTERS TIMES: TGSetDurationAction -> changeDuration
                    TGMeasure m = measure(track, a[1]);
                    manager.getMeasureManager().changeDuration(m, beat(m, a[2]), duration(a[4], a[5], a[6], a[7]),
                        Integer.parseInt(a[3]), true);
                }
                case "fix_ties" -> {
                    // TG 2.1.0 changeDuration leaves invalid tiedNote flags after a gap.
                    // Reproduce the explicit TGFixTiedNoteAction for each invalid note;
                    // print the uncorrected state rather than silently normalizing it.
                    int invalid = 0;
                    for (int i=0; i<track.countMeasures(); i++)
                        for (TGBeat b:track.getMeasure(i).getBeats())
                            for (int v=0; v<TGBeat.MAX_VOICES; v++) for (TGNote n:b.getVoice(v).getNotes())
                                if (n.isTiedNote() && manager.getTrackManager().getPreviousNoteForTie(n)==null) {
                                    invalid++;
                                    manager.getTrackManager().fixInvalidTiedNote(n);
                                }
                    System.out.println("explicit Fix tied note repaired " + invalid + " invalid flags after duration edit");
                }
                case "rest_delete_probe" -> { // one caret rest: TGDeleteNoteOrRestAction
                    TGBeat b = beat(measure(track, a[1]), a[2]); int v = Integer.parseInt(a[3]);
                    if (!b.getVoice(v).isRestVoice()) throw new IllegalArgumentException("caret is not a rest");
                    manager.getMeasureManager().removeVoice(b.getVoice(v), true);
                }
                case "insert_rest" -> {   // insert_rest M AT VOICE: TGInsertRestBeatAction
                    TGMeasure m = measure(track, a[1]); TGBeat b = beat(m, a[2]); int v = Integer.parseInt(a[3]);
                    TGVoice voice = b.getVoice(v);
                    if (manager.isFreeEditionMode(m)) manager.getMeasureManager().insertRestBeatWithoutControl(b, v);
                    else if (voice.isEmpty()) manager.getMeasureManager().addSilence(b, voice.getDuration().clone(factory), v);
                    else manager.getMeasureManager().moveVoicesPrecise(m, b.getPreciseStart(), voice.getDuration().getPreciseTime(),
                        v, voice.getDuration());
                }
                case "clean_beat" -> {   // clean_beat M AT: TGCleanBeatAction -> cleanBeat
                    TGMeasure m = measure(track, a[1]); manager.getMeasureManager().cleanBeat(beat(m, a[2]));
                }
                case "remove_unused_voice" -> manager.getMeasureManager().removeMeasureVoices(measure(track, a[1]), Integer.parseInt(a[2]));
                case "move_beats" -> {   // Optional AMOUNT in quarter notes: TGMoveBeatsAction's explicit move.
                    TGMeasure m = measure(track, a[1]); TGBeat b = beat(m, a[2]);
                    long move = b.getVoice(Integer.parseInt(a[3])).getDuration().getTime();
                    if (a.length > 5) move = quarters(a[5]) / TGDuration.toPreciseTime(1);
                    manager.getTrackManager().moveTrackBeats(track, m.getStart(), b.getStart(), a[4].equals("left") ? -move : move);
                }
                case "measure_add" -> manager.addNewMeasure(song, Integer.parseInt(a[1]));   // TGAddMeasureAction
                case "measure_remove" -> {   // measure_remove FROM TO: TGRemoveMeasureRangeAction
                    int from = Integer.parseInt(a[1]), to = Integer.parseInt(a[2]);
                    if (!(from == 1 && to == song.countMeasureHeaders()))
                        for (int i = from; i <= to; i++) manager.removeMeasure(song, from);
                }
                case "measure_clean" -> {   // TGCleanMeasureAction, optional selected last measure
                    for(int i=Integer.parseInt(a[1]);i<=Integer.parseInt(a.length>2?a[2]:a[1]);i++)
                        manager.getMeasureManager().cleanMeasure(track.getMeasure(i-1));
                }
                case "measure_paste", "measure_paste_portable" -> { // optional seventh token keeps markers
                    TGSongSegmentHelper helper = new TGSongSegmentHelper(manager);
                    TGSongSegment segment = helper.copyMeasures(song, Integer.parseInt(a[1]), Integer.parseInt(a[2]), track);
                    if (a.length < 7 || !a[6].equals("markers"))
                        for (TGMeasureHeader h : segment.getHeaders()) h.setMarker(null);
                    segment = helper.createSegmentCopies(segment, Integer.parseInt(a[5]));
                    TGMeasure m = measure(track, a[3]); TGMeasureHeader first = segment.getHeaders().get(0);
                    long theMove = m.getStart() - first.getStart();
                    int toTrack = track.getNumber();
                    if (a[4].equals("replace")) {
                        int free = track.countMeasures() - (m.getNumber() - 1);
                        for (int i = free; i < segment.getHeaders().size(); i++) manager.addNewMeasureBeforeEnd(song);
                        helper.replaceMeasures(song, segment.clone(factory), theMove, toTrack);
                    } else helper.insertMeasures(song, segment.clone(factory), m.getNumber(), theMove, toTrack);
                }
                case "repeat_open" -> manager.changeOpenRepeat(song, song.getMeasureHeader(Integer.parseInt(a[1]) - 1).getStart());
                case "track_clone" -> manager.cloneTrack(song, song.getTrack(Integer.parseInt(a[1]) - 1));
                case "track_independent_channel" -> {
                    TGTrack selected = song.getTrack(Integer.parseInt(a[1]) - 1);
                    TGChannel channel = manager.getChannel(song, selected.getChannelId()).clone(factory);
                    channel.setChannelId(manager.getNextChannelId(song));
                    manager.addChannel(song, channel);
                    selected.setChannelId(channel.getChannelId());
                }
                case "track_remove" -> manager.removeTrack(song, song.getTrack(Integer.parseInt(a[1]) - 1));
                case "track_move" -> {
                    TGTrack moving = song.getTrack(Integer.parseInt(a[1]) - 1);
                    int destination = Integer.parseInt(a[2]);
                    while (moving.getNumber() > destination) manager.moveTrackUp(song, moving);
                    while (moving.getNumber() < destination) manager.moveTrackDown(song, moving);
                }
                case "marker" -> {
                    TGMarker marker = factory.newMarker(); marker.setTitle(a[2]); marker.setMeasure(Integer.parseInt(a[1]));
                    song.getMeasureHeader(Integer.parseInt(a[1]) - 1).setMarker(marker);
                }
                case "line_break" -> song.getMeasureHeader(Integer.parseInt(a[1]) - 1).setLineBreak(true);
                case "repeat_close" -> manager.changeCloseRepeat(song, song.getMeasureHeader(Integer.parseInt(a[1]) - 1).getStart(), Integer.parseInt(a[2]));
                case "ending" -> manager.changeAlternativeRepeat(song, song.getMeasureHeader(Integer.parseInt(a[1]) - 1).getStart(), Integer.parseInt(a[2]));
                case "time_signature" -> {   // time_signature M NUM DEN to_end|one: TGChangeTimeSignatureAction
                    TGTimeSignature ts = factory.newTimeSignature();
                    ts.setNumerator(Integer.parseInt(a[2])); ts.getDenominator().setValue(Integer.parseInt(a[3]));
                    manager.changeTimeSignature(song, song.getMeasureHeader(Integer.parseInt(a[1]) - 1), ts, a[4].equals("to_end"));
                }
                case "tempo" -> {
                    for(int i=0;i<song.countMeasureHeaders();i++)song.getMeasureHeader(i).getTempo().setQuarterValue(Integer.parseInt(a[1]));
                }
                case "range_duration", "range_duration_live" -> {
                    // TGSetDurationAction snapshots the selected beats and applies one cloned caret duration.
                    // Optional first/last onset bounds; trailing "strict" is only our Fit-off comparison mode.
                    List<TGBeat> selected=new ArrayList<>();
                    Map<TGBeat,TGVoice> originalVoices=new IdentityHashMap<>();
                    for(int i=Integer.parseInt(a[1]);i<=Integer.parseInt(a[2]);i++) {
                        TGMeasure m=track.getMeasure(i-1);
                        for(TGBeat b:m.getBeats()) {
                            long at=b.getPreciseStart()-m.getPreciseStart();
                            if(a.length<=8 || ((i!=Integer.parseInt(a[1]) || at>=quarters(a[8])) &&
                                (i!=Integer.parseInt(a[2]) || at<=quarters(a[9])))) {
                                selected.add(b); originalVoices.put(b,b.getVoice(Integer.parseInt(a[3])));
                            }
                        }
                    }
                    int skipped=0;
                    for(TGBeat b:selected) {
                        // Explicit native safety difference: TG's actual action still
                        // edits detached originals. This reference omits only those.
                        TGVoice original=originalVoices.get(b);
                        if(a[0].equals("range_duration_live") && (!b.getMeasure().getBeats().contains(b) ||
                            b.getVoice(Integer.parseInt(a[3]))!=original || original.isEmpty())) { skipped++; continue; }
                        manager.getMeasureManager().changeDuration(b.getMeasure(),b,
                            duration(a[4],a[5],a[6],a[7]),Integer.parseInt(a[3]),true);
                    }
                    if(a[0].equals("range_duration_live"))System.out.println("live-target reference skipped " + skipped + " detached voices");
                }
                case "range_expression" -> {
                    var mm=manager.getMeasureManager();boolean on=Boolean.parseBoolean(a[4]);
                    // Tablature.getCurrentNoteRange passes only the caret voice to Selector.
                    int selectedVoice=a.length>5?Integer.parseInt(a[5]):0;
                    for(int i=Integer.parseInt(a[1]);i<=Integer.parseInt(a[2]);i++)
                        for(TGBeat b:track.getMeasure(i-1).getBeats())for(TGNote n:b.getVoice(selectedVoice).getNotes())
                            switch(a[3]) {
                                case "velocity" -> mm.changeVelocity(Integer.parseInt(a[4]),n);
                                case "ghost" -> mm.setGhostNote(n,on);
                                case "accent" -> mm.setAccentuatedNote(n,on);
                                case "heavy_accent" -> mm.setHeavyAccentuatedNote(n,on);
                                case "staccato" -> mm.setStaccato(n,on);
                                case "palm_mute" -> mm.setPalmMute(n,on);
                                case "dead" -> mm.setDeadNote(n,on);
                                case "let_ring" -> mm.setLetRing(n,on);
                                case "vibrato" -> mm.setVibrato(n,on);
                                case "hammer" -> mm.setHammerNote(n,on);
                                case "slide" -> mm.setSlideNote(n,on);
                                case "fade_in" -> mm.setFadeIn(n,on);
                                case "tapping" -> mm.setTapping(n,on);
                                case "slapping" -> mm.setSlapping(n,on);
                                case "popping" -> mm.setPopping(n,on);
                                default -> throw new IllegalArgumentException("unknown expression");
                            }
                }
                case "range_semitone" -> {
                    int direction=Integer.parseInt(a[3]), voice=Integer.parseInt(a[4]);
                    List<TGNote> notes=new ArrayList<>();
                    for(int i=Integer.parseInt(a[1]);i<=Integer.parseInt(a[2]);i++)
                        for(TGBeat b:track.getMeasure(i-1).getBeats()) notes.addAll(b.getVoice(voice).getNotes());
                    var mm=manager.getMeasureManager(); boolean possible=true;
                    for(TGNote n:notes) {
                        TGBeat b=n.getVoice().getBeat();
                        possible &= direction>0 ? mm.canMoveSemitoneUp(b.getMeasure(),b.getStart(),n.getString()) :
                            mm.canMoveSemitoneDown(b.getMeasure(),b.getStart(),n.getString());
                    }
                    if(possible) for(TGNote n:notes) {
                        TGBeat b=n.getVoice().getBeat();
                        if(direction>0) mm.moveSemitoneUp(b.getMeasure(),b.getStart(),n.getString());
                        else mm.moveSemitoneDown(b.getMeasure(),b.getStart(),n.getString());
                    }
                }
                case "range_transpose", "range_strings" -> {
                    for (int i=Integer.parseInt(a[1]); i<=Integer.parseInt(a[2]); i++) {
                        TGMeasure m=track.getMeasure(i-1);
                        if (a[0].equals("range_transpose")) manager.getMeasureManager().transposeNotes(m,Integer.parseInt(a[3]),true,true,-1);
                        else for (TGBeat b:m.getBeats()) {
                            List<Integer> strings=new ArrayList<>();
                            int voice=a.length>4?Integer.parseInt(a[4]):0, direction=Integer.parseInt(a[3]);
                            for(TGNote n:b.getVoice(voice).getNotes()) strings.add(n.getString());
                            strings.sort(direction>0?Comparator.reverseOrder():Comparator.naturalOrder());
                            for(int s:strings) {
                                if(direction>0) manager.getMeasureManager().shiftNoteDown(m,b.getStart(),s);
                                else manager.getMeasureManager().shiftNoteUp(m,b.getStart(),s);
                            }
                        }
                    }
                }
                case "transpose" -> manager.getTrackManager().transposeNotes(track, Integer.parseInt(a[1]), true, true, -1);   // TGTransposeAction, whole track
                case "retune", "allocate" -> { // allocate uses clipboard string allocation even for uniform transposition
                    List<TGString> strings = new ArrayList<>();
                    String[] values = a[1].split(",");
                    for (int i = 0; i < values.length; i++) { TGString s = factory.newString(); s.setNumber(i + 1); s.setValue(Integer.parseInt(values[i])); strings.add(s); }
                    int transposition = 0;
                    if (track.getStrings().size() == strings.size()) {
                        transposition = track.getString(1).getValue() - strings.get(0).getValue();
                        for (int i = 1; i < strings.size(); i++)
                            if (track.getString(i + 1).getValue() - strings.get(i).getValue() != transposition) { transposition = 0; break; }
                    }
                    if (transposition != 0 && a[0].equals("retune")) {
                        int[] t = new int[strings.size()]; Arrays.fill(t, transposition);
                        track.setStrings(strings); manager.getTrackManager().transposeNotes(track, t, true, true);
                    } else {
                        List<Integer> from = new ArrayList<>();
                        for (int i = 1; i <= track.getStrings().size(); i++) from.add(track.getString(i).getValue());
                        track.setStrings(strings); manager.getTrackManager().allocateNotesToStrings(from, track, strings);
                    }
                }
                case "capo" -> manager.getTrackManager().changeOffset(track, Integer.parseInt(a[1]));
                default -> throw new IllegalArgumentException("unknown operation: " + line);
            }
        }
        write(song, Path.of(args[2]));
    }
}
