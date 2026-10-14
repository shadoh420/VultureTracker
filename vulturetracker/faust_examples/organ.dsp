// A drawbar organ: nine sines at the tonewheel organ's footages (16', 5 1/3', 8', 4', 2 2/3', 2', 1 3/5', 1 1/3',
// 1'), each drawbar 0-8, with a key click and the organ's instant on and off.
import("stdfaust.lib");
freq = hslider("freq", 220, 20, 2000, 0.01);
gain = hslider("gain", 0.8, 0, 1, 0.01);
gate = button("gate");
bar(i, d) = hslider("bar%i", d, 0, 8, 1) / 8;
ratios = (0.5, 1.5, 1, 2, 3, 4, 5, 6, 8);
defaults = (0, 0, 8, 8, 0, 0, 0, 0, 0);              // 008800000: the 8' and 4' (16' sounds an octave down)
pipe(i) = os.osc(freq * ba.take(i + 1, ratios)) * bar(i + 1, ba.take(i + 1, defaults)) * (freq * ba.take(i + 1, ratios) < ma.SR / 2.2);
click = hslider("click", 0.3, 0, 1, 0.01);
env = en.asr(0.004, 1, 0.01, gate);
process = (sum(i, 9, pipe(i)) / 4 + no.noise * click * en.ar(0.0005, 0.006, gate) * 0.2) * env * gain;
