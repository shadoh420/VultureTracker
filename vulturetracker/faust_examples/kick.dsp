// A kick: a sine falling from `start` to `end` Hz (`slope` seconds to fall most of the way), an amplitude decay of
// `env` seconds, and `dist` of tanh drive. The note's pitch does not change it (play it at its root).
import("stdfaust.lib");
gain = hslider("gain", 0.9, 0, 1, 0.01);
gate = button("gate");
start = hslider("start", 180, 40, 1000, 1);
end = hslider("end", 45, 20, 200, 1);
slope = hslider("slope", 0.04, 0.002, 0.5, 0.001);
envtime = hslider("env", 0.45, 0.05, 3, 0.01);
dist = hslider("dist", 0.2, 0, 1, 0.01);
trig = gate : ba.impulsify;
age = ((+(1) : *(1 - trig)) ~ _) / ma.SR;                // seconds since the note began
pitch = end + (start - end) * exp(-age / slope * 3);
amp = exp(-age / envtime * 5) * (age < envtime * 2);
drive = 1 + dist * 9;
process = sin(2 * ma.PI * os.lf_sawpos(pitch)) * amp : *(drive) : ma.tanh : /(ma.tanh(drive)) : *(gain);
