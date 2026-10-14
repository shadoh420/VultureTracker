// Karplus-Strong pluck with a pick position: a short noise burst, combed where the string is picked (a notch at
// every multiple of 1/position of the pitch), into the Faust library's Karplus-Strong string (pm.ks).
import("stdfaust.lib");
freq = hslider("freq", 220, 20, 4000, 0.01);
gain = hslider("gain", 0.8, 0, 1, 0.01);
gate = button("gate");
position = hslider("position", 0.15, 0.02, 0.5, 0.01);   // where the string is picked, from its end
damping = hslider("damping", 0.3, 0, 1, 0.01);           // higher: the high harmonics die sooner
burst = hslider("burst", 0.004, 0.001, 0.02, 0.001);     // seconds of noise in the pluck
pick = no.noise * en.ar(0.0005, burst, gate) * gain <: _, de.fdelay(8192, position * ma.SR / freq) : -;
process = pick : pm.ks(pm.f2l(freq), damping) * 0.6;
