"""Original upbeat summer loop, synthesized from scratch (no samples, no third-party audio)."""
import numpy as np, wave, sys
SR = 44100
BPM = 112
beat = 60 / BPM
dur = float(sys.argv[1]) if len(sys.argv) > 1 else 16.0
N = int(SR * dur)
out = np.zeros((N, 2))

def note(f): return 440 * 2 ** ((f - 69) / 12)
def env(n, a=0.005, r=0.25):
    t = np.arange(n) / SR
    e = np.minimum(1, t / a) * np.exp(-t / r)
    return e
def add(sig, start, pan=0.0, gain=1.0):
    i = int(start * SR)
    if i >= N: return
    sig = sig[: N - i] * gain
    out[i:i + len(sig), 0] += sig * (1 - pan) * 0.5 * 2 ** 0.5
    out[i:i + len(sig), 1] += sig * (1 + pan) * 0.5 * 2 ** 0.5

# chords: C - G - Am - F  (bright, holiday feel), one bar each (4 beats)
prog = [[60, 64, 67], [55, 59, 62, 67], [57, 60, 64], [53, 57, 60, 65]]
bass = [36, 43, 45, 41]
bars = int(dur / (4 * beat)) + 1
for b in range(bars):
    t0 = b * 4 * beat
    ch = prog[b % 4]
    # off-beat plucked chords (reggaeton/tropical skank)
    for k in range(8):
        if k % 2 == 1:
            n = int(0.22 * SR); t = np.arange(n) / SR
            s = sum(np.sin(2 * np.pi * note(m + 12) * t) + 0.3 * np.sin(2 * np.pi * note(m + 24) * t) for m in ch)
            add(s * env(n, 0.003, 0.08), t0 + k * beat / 2, pan=0.2, gain=0.05)
    # warm pad
    n = int(4 * beat * SR); t = np.arange(n) / SR
    pad = sum(np.sin(2 * np.pi * note(m) * t + 0.3 * np.sin(2 * np.pi * 5 * t)) for m in ch)
    pad *= np.minimum(1, t / 0.4) * np.minimum(1, (4 * beat - t) / 0.3)
    add(pad, t0, pan=-0.2, gain=0.022)
    # bass on 1 and the "and" of 2
    for k, off in enumerate([0, 1.5, 2.5]):
        n = int(0.4 * SR); t = np.arange(n) / SR
        s = np.sin(2 * np.pi * note(bass[b % 4]) * t) + 0.25 * np.sin(2 * np.pi * 2 * note(bass[b % 4]) * t)
        add(s * env(n, 0.005, 0.18), t0 + off * beat, gain=0.18)
    # melody hook (marimba-like), bars 2+
    if b >= 1:
        mel = [[72, None, 76, 79, None, 76, 74, None], [74, None, 71, 74, None, 79, 76, None],
               [76, None, 72, 76, None, 79, 81, None], [77, None, 76, 72, None, 74, 72, None]][b % 4]
        for k, m in enumerate(mel):
            if m is None: continue
            n = int(0.3 * SR); t = np.arange(n) / SR
            s = np.sin(2 * np.pi * note(m) * t) + 0.4 * np.sin(2 * np.pi * note(m) * 4 * t) * np.exp(-t / 0.02)
            add(s * env(n, 0.002, 0.12), t0 + k * beat / 2, pan=0.35, gain=0.07)
    # drums: kick 4-on-floor, clap on 2 & 4, hats on 8ths
    for k in range(4):
        n = int(0.25 * SR); t = np.arange(n) / SR
        f = 120 * np.exp(-t / 0.04) + 45
        kick = np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t / 0.12)
        add(kick, t0 + k * beat, gain=0.35)
        if k in (1, 3):
            n2 = int(0.15 * SR); t2 = np.arange(n2) / SR
            clap = np.random.default_rng(b * 10 + k).standard_normal(n2) * np.exp(-t2 / 0.04)
            add(clap, t0 + k * beat, gain=0.06)
    for k in range(8):
        n = int(0.05 * SR); t = np.arange(n) / SR
        hat = np.random.default_rng(b * 100 + k).standard_normal(n)
        hat = np.diff(hat, prepend=0) * np.exp(-t / 0.012)
        add(hat, t0 + k * beat / 2 + 0.0, pan=-0.3, gain=0.05 if k % 2 else 0.03)

# fade in/out, normalize
fi, fo = int(0.3 * SR), int(1.2 * SR)
out[:fi] *= np.linspace(0, 1, fi)[:, None]
out[-fo:] *= np.linspace(1, 0, fo)[:, None]
out = np.tanh(out * 1.2)
out /= np.abs(out).max() / 0.85
with wave.open(sys.argv[2] if len(sys.argv) > 2 else 'music.wav', 'wb') as w:
    w.setnchannels(2); w.setsampwidth(2); w.setframerate(SR)
    w.writeframes((out * 32767).astype(np.int16).tobytes())
