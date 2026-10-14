// A marimba: the Faust library's bar modes and resonator tube struck by its mallet model (pm.marimba's parts), with the
// bar's ring time as a control (pm.marimba fixes it at 0.1 s).
import("stdfaust.lib");
freq = hslider("freq", 440, 60, 4000, 0.01);
gain = hslider("gain", 0.8, 0, 1, 0.01);
gate = button("gate");
position = hslider("position", 0, 0, 4, 1);          // which point of the bar is struck (0-4)
cutoff = hslider("cutoff", 7000, 1000, 10000, 1);    // the mallet's brightness, Hz
sharpness = hslider("sharpness", 0.25, 0.01, 5, 0.01);
decay = hslider("decay", 0.8, 0.05, 4, 0.01);        // the lowest mode's T60, s; the higher modes ring shorter
process = pm.strikeModel(10, cutoff, sharpness, gain, gate)
        : pm.marimbaBarModel(freq, position, decay, 1, 5) : pm.marimbaResTube(pm.f2l(freq)) * 0.6;
