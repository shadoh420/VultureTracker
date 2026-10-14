// An acid bass: a saw through the Faust library's diode ladder filter (ve.diodeLadder), its cutoff swept down from
// cutoff + envmod at each note, louder and brighter with accent.
import("stdfaust.lib");
freq = hslider("freq", 110, 20, 1000, 0.01);
gain = hslider("gain", 0.8, 0, 1, 0.01);
gate = button("gate");
cutoff = hslider("cutoff", 0.15, 0.01, 0.9, 0.001);   // of half the rate
envmod = hslider("envmod", 0.35, 0, 0.8, 0.001);
decay = hslider("decay", 0.25, 0.02, 2, 0.01);
resonance = hslider("resonance", 6, 0.7, 20, 0.01);
accent = hslider("accent", 0, 0, 1, 0.01);
env = en.ar(0.002, decay, gate);
process = os.sawtooth(freq) * 0.5
        : ve.diodeLadder(min(0.95, cutoff + (envmod + accent * 0.2) * env), resonance)
        * en.asr(0.002, 1, 0.02, gate) * gain * (1 + accent * 0.5);
