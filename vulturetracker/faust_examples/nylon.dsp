// A nylon-string guitar: the Faust library's physical model (pm.nylonGuitar), plucked at `position`.
import("stdfaust.lib");
freq = hslider("freq", 220, 40, 1500, 0.01);
gain = hslider("gain", 0.8, 0, 1, 0.01);
gate = button("gate");
position = hslider("position", 0.25, 0.05, 0.9, 0.01);
process = pm.nylonGuitar(pm.f2l(freq), position, gain, gate) * 0.8;
