// A two-operator FM voice in the manner of the OPL2 chip: a modulator shifting a carrier's phase, each with one of the
// chip's four waves (0 sine, 1 half sine, 2 absolute sine, 3 quarter sine), a frequency multiple and an envelope.
import("stdfaust.lib");
freq = hslider("freq", 220, 20, 4000, 0.01);
gain = hslider("gain", 0.8, 0, 1, 0.01);
gate = button("gate");
wave(w, p) = s * (w == 0) + max(s, 0) * (w == 1) + abs(s) * (w == 2) + abs(s) * (ma.frac(p * 2) < 0.5) * (w == 3)
with { s = sin(2 * ma.PI * p); };
mwave = hslider("mod_wave", 0, 0, 3, 1);
cwave = hslider("car_wave", 0, 0, 3, 1);
mmul = hslider("mod_mult", 2, 0.5, 15, 0.5);
cmul = hslider("car_mult", 1, 0.5, 15, 0.5);
index = hslider("index", 1.5, 0, 8, 0.01);            // the modulator's depth, in cycles of the carrier's phase / 2 pi
mdecay = hslider("mod_decay", 0.4, 0.01, 4, 0.01);
modulator = wave(mwave, os.lf_sawpos(freq * mmul)) * index / (2 * ma.PI) * en.adsr(0.001, mdecay, 0.3, 0.2, gate);
carrier(m) = wave(cwave, ma.frac(os.lf_sawpos(freq * cmul) + m)) * en.adsr(0.002, 1.2, 0.6, 0.25, gate);
process = carrier(modulator) * gain * 0.7;
