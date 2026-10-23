#!/usr/bin/env python3
"""Generate the dash's WAV sounds into ../sounds/.

You only need this to change or recreate the sounds; the dash itself just plays
the WAV files. Needs numpy:  pip install numpy

  startup.wav  warm chord swell + rising bell arpeggio  ("system ready")
  alarm.wav    urgent triple chime, loops seamlessly     (red alarm)
  warning.wav  soft two-note marimba ding               (new amber warning)
  nosignal.wav radio static, then three falling notes    (a sensor stopped answering: NO SIGNAL)
  keyoff.wav   the startup bells, falling, over a soft chord (key turned off: shutting down)

You can replace any of these with your own WAV files. The paths are in config.toml [audio].
"""
import os
import wave

import numpy as np

RATE = 44100
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "sounds")


def t_axis(dur):
    return np.arange(int(dur * RATE)) / RATE


def env(dur, attack, decay_rate, release=0.02):
    """Fast-ish attack, exponential decay, short release so nothing clicks."""
    t = t_axis(dur)
    e = np.minimum(1.0, t / max(attack, 1e-4)) * np.exp(-decay_rate * t)
    n_rel = int(release * RATE)
    if n_rel:
        e[-n_rel:] *= np.linspace(1, 0, n_rel)
    return e


def fm_bell(freq, dur, ratio=3.5, index=2.5, decay=3.0, attack=0.004):
    """FM synthesis bell: the modulation fades, so the tone mellows as it rings."""
    t = t_axis(dur)
    idx = index * np.exp(-decay * 1.5 * t)
    mod = idx * np.sin(2 * np.pi * freq * ratio * t)
    return np.sin(2 * np.pi * freq * t + mod) * env(dur, attack, decay)


def marimba(freq, dur, decay=6.0):
    t = t_axis(dur)
    body = np.sin(2 * np.pi * freq * t) * np.exp(-decay * t)
    tine = 0.35 * np.sin(2 * np.pi * freq * 4.0 * t) * np.exp(-decay * 4 * t)  # bright strike, dies fast
    return (body + tine) * env(dur, 0.003, 0.0)


def pad(freqs, dur, attack=0.5, release=1.2):
    """Soft chord: a few detuned sines per note, slow swell in and out."""
    t = t_axis(dur)
    out = np.zeros_like(t)
    for f in freqs:
        for detune in (-0.25, 0.0, 0.25):
            out += np.sin(2 * np.pi * (f + detune) * t + np.random.rand() * 6.28)
            out += 0.25 * np.sin(2 * np.pi * 2 * (f + detune) * t)
    shape = np.minimum(1, t / attack) * np.minimum(1, (dur - t) / release)
    return out * np.clip(shape, 0, 1) ** 2


def lowpass(x, cutoff):
    """One-pole low-pass, done in the frequency domain (gentle 6 dB/oct slope)."""
    X = np.fft.rfft(x)
    f = np.fft.rfftfreq(len(x), 1 / RATE)
    return np.fft.irfft(X / np.sqrt(1 + (f / cutoff) ** 2), len(x))


def reverb(x, seconds=1.2, wet=0.25, tone=4000):
    """Convolve with a synthetic room: decaying, darkened noise."""
    rng = np.random.default_rng(7)
    ir = rng.standard_normal(int(seconds * RATE)) * np.exp(-np.arange(int(seconds * RATE)) / (RATE * seconds / 5))
    ir = lowpass(ir, tone)
    ir /= np.sqrt(np.sum(ir ** 2))
    n = len(x) + len(ir)
    wet_sig = np.fft.irfft(np.fft.rfft(x, n) * np.fft.rfft(ir, n), n)
    dry = np.concatenate([x, np.zeros(len(ir))])
    return dry * (1 - wet) + wet_sig * wet * 3


def place(buf, sig, at):
    i = int(at * RATE)
    end = min(len(buf), i + len(sig))
    buf[i:end] += sig[: end - i]


def finish(x, peak_db=-1.0, fade=0.03):
    n = int(fade * RATE)
    x = x.copy()
    x[-n:] *= np.linspace(1, 0, n)
    return x / np.max(np.abs(x)) * 10 ** (peak_db / 20)


def save(name, x):
    os.makedirs(OUT, exist_ok=True)
    path = os.path.join(OUT, name)
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes((np.clip(x, -1, 1) * 32767).astype("<i2").tobytes())
    print(f"wrote {path}  ({len(x) / RATE:.2f} s)")


def startup():
    np.random.seed(1)
    dur = 2.6
    buf = np.zeros(int(dur * RATE))
    # warm C major add9 chord swelling underneath
    place(buf, 0.10 * lowpass(pad([130.81, 196.0, 261.63, 329.63, 587.33], dur, attack=0.35, release=1.4), 1800), 0)
    # rising bell arpeggio G4 C5 E5 G5, last note rings
    for i, f in enumerate([392.0, 523.25, 659.25, 783.99]):
        ring = 1.9 if i == 3 else 1.2
        place(buf, (0.55 if i < 3 else 0.7) * fm_bell(f, ring, ratio=3.5, index=1.6, decay=2.2), 0.18 + i * 0.13)
    return finish(reverb(buf, 1.3, wet=0.3)[: int(3.2 * RATE)])


def alarm():
    # Loops seamlessly: three urgent chimes, then a gap. Reverb tail is folded
    # back to the start so the loop has no seam.
    period = 1.5
    buf = np.zeros(int(period * RATE))
    for i in range(3):
        f = 880.0
        tone = fm_bell(f, 0.32, ratio=1.0, index=3.0, decay=5.0, attack=0.002)   # brassy, cuts through noise
        tone += 0.6 * fm_bell(f * 1.5, 0.32, ratio=2.0, index=1.5, decay=6.0, attack=0.002)
        place(buf, tone, i * 0.17)
    wet = reverb(buf, 0.6, wet=0.18, tone=6000)
    looped = wet[: len(buf)].copy()
    looped[: len(wet) - len(buf)] += wet[len(buf):]
    looped /= np.max(np.abs(looped))
    return looped * 10 ** (-1 / 20)


def warning():
    dur = 1.4
    buf = np.zeros(int(dur * RATE))
    place(buf, 0.9 * marimba(1318.5, 0.9), 0.0)    # E6
    place(buf, 0.9 * marimba(987.77, 1.0), 0.16)   # B5
    return finish(reverb(buf, 1.0, wet=0.28)[: int(dur * RATE)])


def nosignal():
    """'Connection lost': a burst of radio static, then three notes gliding down (G5, D5, G4).
    Nothing like the alarm or the warning, so you know it's the wiring, not the machine."""
    dur = 1.6
    buf = np.zeros(int(dur * RATE))
    rng = np.random.default_rng(3)
    n = int(0.28 * RATE)
    static = rng.standard_normal(n) * (rng.random(n) < 0.35)            # crackly, not smooth hiss
    static = lowpass(static - lowpass(static, 900), 5000)              # band-pass: radio-ish
    static *= np.exp(-np.arange(n) / (0.09 * RATE))
    place(buf, 0.55 * static / np.max(np.abs(static)), 0.0)
    for i, (f0, f1) in enumerate([(784.0, 740.0), (587.3, 554.4), (392.0, 349.2)]):
        d = 0.26 if i < 2 else 0.5
        t = t_axis(d)
        f = f0 + (f1 - f0) * t / d                                     # each note sags as it fades
        phase = 2 * np.pi * np.cumsum(f) / RATE
        tone = np.sin(phase) + 0.3 * np.sin(3 * phase) + 0.12 * np.sin(5 * phase)   # hollow, square-ish
        place(buf, 0.75 * tone * env(d, 0.006, 4.0 if i < 2 else 3.0), 0.22 + i * 0.2)
    return finish(reverb(buf, 0.8, wet=0.22)[: int(dur * RATE)])


def keyoff():
    """The startup chime's mirror image: the same bells falling C6 G5 E5 C5 over a fading chord,
    so 'key off, shutting down' sounds like the end of the start-up sound."""
    np.random.seed(2)
    dur = 2.3
    buf = np.zeros(int(dur * RATE))
    place(buf, 0.08 * lowpass(pad([130.81, 196.0, 261.63, 329.63], dur, attack=0.05, release=1.8), 1500), 0)
    for i, f in enumerate([1046.5, 783.99, 659.25, 523.25]):
        ring = 1.6 if i == 3 else 1.0
        place(buf, (0.5 if i < 3 else 0.62) * fm_bell(f, ring, ratio=3.5, index=1.4, decay=2.6), 0.04 + i * 0.15)
    return finish(reverb(buf, 1.2, wet=0.3)[: int(2.8 * RATE)])


if __name__ == "__main__":
    save("startup.wav", startup())
    save("alarm.wav", alarm())
    save("warning.wav", warning())
    save("nosignal.wav", nosignal())
    save("keyoff.wav", keyoff())
