"""
compose_music.py — Kimi picks {key, mode, bpm, mood, palette} for the brief;
this script renders a 26 s ambient stack to .wav.

Layers:
  1. chord pad        I-vi-IV-V in chosen key, sine + saw + sub triangle
  2. drone            sustained root + 5th, slow tremolo
  3. sparkles         pentatonic high pings with long reverb tail
  4. sub pulse        sub-bass throb every 4 beats
  5. emulsion floor   filtered brown noise — vintage film breath

Usage:
    python compose_music.py --brief "<text>" --duration 26 --out audio.wav
    python compose_music.py --spec spec.json --out audio.wav   # bypass Kimi
"""
import argparse
import json
import sys
import wave
from pathlib import Path

import numpy as np

from kimi_client import chat_json

SR = 44100

KEY_TO_MIDI_ROOT = {
    "C": 60, "C#": 61, "Db": 61, "D": 62, "D#": 63, "Eb": 63,
    "E": 64, "F": 65, "F#": 66, "Gb": 66, "G": 67, "G#": 68,
    "Ab": 68, "A": 69, "A#": 70, "Bb": 70, "B": 71,
}
MAJOR_INTERVALS = [0, 2, 4, 5, 7, 9, 11]
MINOR_INTERVALS = [0, 2, 3, 5, 7, 8, 10]
DORIAN_INTERVALS = [0, 2, 3, 5, 7, 9, 10]


SYSTEM_SPEC = """You are a music director. Given a creative brief, return
EXACTLY one JSON object describing a 26-second ambient piece:

{
  "key":  "<one of: C C# D D# E F F# G G# A A# B (or flats Db Eb Gb Ab Bb)>",
  "mode": "major | minor | dorian",
  "bpm":  <integer 50-72>,
  "mood": "<3-6 word description of feel>",
  "progression": "<one of: I-vi-IV-V, i-VII-VI-VII, i-iv-v-i, I-IV-vi-V, ii-V-I-vi>"
}

Bias ambient/contemplative. Choose minor or dorian for melancholic briefs,
major for warm or playful, dorian for unresolved/wistful.
Return JSON only."""


def kimi_spec(brief):
    return chat_json(SYSTEM_SPEC, f"Brief: {brief}", temperature=0.4)


# ============================================================
# DSP helpers
# ============================================================

def midi_to_hz(n):
    return 440.0 * (2.0 ** ((n - 69) / 12.0))


def envelope(n, attack_ms=20, release_ms=400, sustain=1.0):
    a = max(1, int(SR * attack_ms / 1000))
    r = max(1, int(SR * release_ms / 1000))
    s = max(0, n - a - r)
    e = np.concatenate([np.linspace(0, sustain, a),
                        np.full(s, sustain),
                        np.linspace(sustain, 0, r)])
    if len(e) < n:
        e = np.concatenate([e, np.zeros(n - len(e))])
    return e[:n].astype(np.float32)


def adsr(n, a=0.01, d=0.1, s=0.7, r=0.3):
    aa = int(SR * a); dd = int(SR * d); rr = int(SR * r)
    ss = max(0, n - aa - dd - rr)
    parts = [np.linspace(0, 1, max(1, aa)),
             np.linspace(1, s, max(1, dd)),
             np.full(ss, s),
             np.linspace(s, 0, max(1, rr))]
    e = np.concatenate(parts)
    if len(e) < n:
        e = np.concatenate([e, np.zeros(n - len(e))])
    return e[:n].astype(np.float32)


def sine(f, n, ph=0.0):
    t = np.arange(n, dtype=np.float32) / SR
    return np.sin(2 * np.pi * f * t + ph).astype(np.float32)


def saw(f, n, ph=0.0):
    t = np.arange(n, dtype=np.float32) / SR
    return (2.0 * ((f * t + ph / (2 * np.pi)) % 1.0) - 1.0).astype(np.float32)


def tri(f, n, ph=0.0):
    t = np.arange(n, dtype=np.float32) / SR
    return (2 * np.abs(2 * ((f * t + ph / (2 * np.pi)) % 1.0) - 1.0) - 1.0
            ).astype(np.float32)


def lp1(x, fc):
    a = np.exp(-2 * np.pi * fc / SR)
    y = np.zeros_like(x); p = 0.0
    for i, s in enumerate(x):
        p = (1 - a) * s + a * p
        y[i] = p
    return y


def hp1(x, fc):
    a = np.exp(-2 * np.pi * fc / SR)
    y = np.zeros_like(x); px = 0.0; py = 0.0
    for i, s in enumerate(x):
        cy = a * (py + s - px)
        y[i] = cy; px = s; py = cy
    return y


def multitap(x, delays_ms, gains):
    out = x.copy()
    for d_ms, g in zip(delays_ms, gains):
        d = int(SR * d_ms / 1000)
        if d < len(x):
            t = np.zeros_like(x); t[d:] = x[:len(x) - d] * g
            out = out + t
    return out


# ============================================================
# Layer generators
# ============================================================

def progression_voicings(spec):
    """Map mode + progression name to chord MIDI triads, root in octave 3."""
    root_midi = KEY_TO_MIDI_ROOT.get(spec["key"], 63) - 12  # octave 3
    mode = spec["mode"].lower()
    prog = spec.get("progression", "I-vi-IV-V").upper()
    intervals = (MAJOR_INTERVALS if mode == "major" else
                 MINOR_INTERVALS if mode == "minor" else
                 DORIAN_INTERVALS)

    # roman numeral → degree (1-based) in the scale
    rn_map = {
        "I": 1, "II": 2, "III": 3, "IV": 4, "V": 5, "VI": 6, "VII": 7,
        "i": 1, "ii": 2, "iii": 3, "iv": 4, "v": 5, "vi": 6, "vii": 7,
    }
    chords = []
    for token in prog.split("-"):
        deg = rn_map.get(token, 1)
        # build triad: root, third, fifth from the scale
        root = root_midi + intervals[(deg - 1) % 7]
        third = root_midi + intervals[(deg + 1) % 7] + (12 if deg + 1 > 7 else 0)
        fifth = root_midi + intervals[(deg + 3) % 7] + (12 if deg + 3 > 7 else 0)
        chords.append((root, third, fifth))
    return chords


def chord_pad(n_total, chords):
    out = np.zeros(n_total, dtype=np.float32)
    chord_n = n_total // len(chords)
    for ci, (r, th, fi) in enumerate(chords):
        s = ci * chord_n
        e = s + chord_n if ci < len(chords) - 1 else n_total
        seg_n = e - s
        env = envelope(seg_n, attack_ms=600, release_ms=900, sustain=1.0)
        for note in (r, th, fi):
            f = midi_to_hz(note)
            tone = (sine(f, seg_n) * 0.50
                    + saw(f * 1.004, seg_n) * 0.18
                    + tri(f * 0.5, seg_n) * 0.10)
            tone = lp1(tone, 600.0 + ci * 80)
            out[s:e] += tone * env * 0.07
    return out


def string_drone(n_total, key_midi):
    root_hz = midi_to_hz(key_midi)
    fifth_hz = midi_to_hz(key_midi + 7)
    a = saw(root_hz, n_total) + saw(root_hz * 1.005, n_total) * 0.7
    b = saw(fifth_hz, n_total) * 0.5 + saw(fifth_hz * 1.005, n_total) * 0.3
    drone = (a + b) * 0.5
    drone = lp1(drone, 700.0)
    t = np.arange(n_total, dtype=np.float32) / SR
    drone *= 1.0 + 0.10 * np.sin(2 * np.pi * 4.0 * t)
    swell = envelope(n_total, attack_ms=2500, release_ms=3500, sustain=0.85)
    return (drone * swell * 0.040).astype(np.float32)


def sparkle_layer(n_total, scale_intervals, key_midi, seed=20):
    rng = np.random.default_rng(seed)
    out = np.zeros(n_total, dtype=np.float32)
    duration = n_total / SR
    n_sparkles = int(duration * 1.1)
    # pentatonic subset — pick {0, 2, 4, 7, 9} positions if the mode has them
    penta = [i for i in (0, 2, 4, 7, 9) if i in scale_intervals]
    if not penta:
        penta = scale_intervals[:5]
    for _ in range(n_sparkles):
        t_pos = rng.uniform(0.4, duration - 0.6)
        deg = rng.choice(penta)
        oct_offset = rng.choice([24, 36])  # +2 or +3 octaves
        note = key_midi + deg + oct_offset
        f = midi_to_hz(note)
        seg_n = int(SR * 0.7)
        idx = int(t_pos * SR)
        if idx + seg_n > n_total:
            continue
        seg = sine(f, seg_n) * 0.7 + sine(f * 2, seg_n) * 0.15
        seg *= adsr(seg_n, a=0.005, d=0.04, s=0.20, r=0.65)
        out[idx:idx + seg_n] += seg * 0.05
    return multitap(out, [220, 480, 820, 1300, 2000],
                    [0.45, 0.30, 0.20, 0.12, 0.06])


def pulse_layer(n_total, bpm):
    out = np.zeros(n_total, dtype=np.float32)
    beat = 60.0 / bpm
    period = 4 * beat                       # every 4 beats
    duration = n_total / SR
    n_pulses = int(duration / period) + 1
    for i in range(n_pulses):
        idx = int(i * period * SR)
        thump_n = int(SR * 0.5)
        if idx + thump_n > n_total:
            break
        t = np.arange(thump_n, dtype=np.float32) / SR
        freq = 110 * np.exp(-t * 8) + 40
        phase = 2 * np.pi * np.cumsum(freq) / SR
        thump = np.sin(phase).astype(np.float32) * np.exp(-t * 4.5)
        out[idx:idx + thump_n] += thump * 0.18
    return lp1(out, 180.0)


def emulsion_noise(n_total, seed=7):
    rng = np.random.default_rng(seed)
    white = rng.standard_normal(n_total).astype(np.float32)
    brown = np.cumsum(white); brown -= np.mean(brown)
    brown /= (np.max(np.abs(brown)) + 1e-9)
    floor = lp1(hp1(brown, 200.0), 5000.0)
    breath_seed = rng.standard_normal(n_total).astype(np.float32)
    breath = lp1(breath_seed, 0.5)
    breath = (breath - breath.min()) / (breath.max() - breath.min() + 1e-9)
    return floor * (0.5 + 0.5 * breath) * 0.012


# ============================================================
# render
# ============================================================

def render(spec, duration, out_path):
    n = int(SR * duration)
    chords = progression_voicings(spec)
    key_midi = KEY_TO_MIDI_ROOT.get(spec["key"], 63)
    mode = spec["mode"].lower()
    intervals = (MAJOR_INTERVALS if mode == "major" else
                 MINOR_INTERVALS if mode == "minor" else
                 DORIAN_INTERVALS)
    print(f"  rendering {duration}s in {spec['key']} {mode}, "
          f"{spec['bpm']}bpm, prog {spec.get('progression','I-vi-IV-V')}")

    pad     = chord_pad(n, chords);                    print("    pad     done")
    drone   = string_drone(n, key_midi);               print("    drone   done")
    sparkle = sparkle_layer(n, intervals, key_midi);   print("    sparkle done")
    pulse   = pulse_layer(n, spec["bpm"]);             print("    pulse   done")
    floor   = emulsion_noise(n);                       print("    floor   done")

    mix = pad + drone + sparkle + pulse + floor
    peak = float(np.max(np.abs(mix)))
    if peak > 0.95:
        mix *= 0.95 / peak
    mix = np.tanh(mix * 1.15) * 0.88

    haas = int(SR * 0.018)
    left = mix.copy()
    right = np.concatenate([np.zeros(haas, dtype=np.float32), mix[:-haas]])
    audio16 = np.stack([(left * 32767).astype(np.int16),
                        (right * 32767).astype(np.int16)], axis=1)
    with wave.open(str(out_path), 'wb') as f:
        f.setnchannels(2); f.setsampwidth(2); f.setframerate(SR)
        f.writeframes(audio16.tobytes())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--brief", default=None)
    ap.add_argument("--spec", default=None)
    ap.add_argument("--duration", type=float, default=26.0)
    ap.add_argument("--out", required=True)
    ap.add_argument("--save-spec", default=None,
                    help="write the music spec JSON next to the wav")
    args = ap.parse_args()

    if args.spec:
        spec = json.loads(Path(args.spec).read_text())
    elif args.brief:
        spec = kimi_spec(args.brief)
    else:
        print("need --brief or --spec", file=sys.stderr); sys.exit(2)

    # safety defaults
    spec.setdefault("key", "Eb")
    spec.setdefault("mode", "major")
    spec.setdefault("bpm", 58)
    spec.setdefault("progression", "I-vi-IV-V")
    spec.setdefault("mood", "warm contemplative")

    print(f"  music spec: {spec}")
    if args.save_spec:
        Path(args.save_spec).write_text(json.dumps(spec, indent=2))
    render(spec, args.duration, args.out)
    print(f"  wrote {args.out}")


if __name__ == "__main__":
    main()
