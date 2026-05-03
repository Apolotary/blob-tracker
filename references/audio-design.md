# Audio design

The composer in `scripts/compose_music.py` is a five-layer numpy-only synth
that takes a Kimi-provided JSON spec and renders a 26-second stereo WAV.

## Spec format

```json
{
  "key":  "Eb",
  "mode": "major",                        // "major" | "minor" | "dorian"
  "bpm":  58,
  "mood": "warm contemplative",
  "progression": "I-vi-IV-V"              // Roman numerals, dash-separated
}
```

## Five layers

### 1. Chord pad
The four-chord progression voices each chord as root + third + fifth in
octave 3. Each note is `0.50 × sine(f) + 0.18 × saw(f × 1.004) + 0.10 × tri(f/2)`.
The 0.4 % saw detune adds beating; the sub-octave triangle thickens the bass.
1-pole low-pass at `600 + ci × 80 Hz` warms each chord. Long attack/release
envelopes (600/900 ms) cross-fade chords seamlessly.

### 2. String drone
A continuous root + perfect-fifth saw drone, detuned + 0.5 %, low-passed at
700 Hz, modulated by a 4 Hz tremolo (`1 + 0.10 × sin`). A long swell envelope
(2.5 s attack / 3.5 s release) hides the start/end edges.

### 3. Sparkles
Random pentatonic high pings sampled twice per second. Each ping is
`sine(f) + 0.15 × sine(2f)` with a fast-attack/slow-release ADSR (5 ms / 65 ms
release). Five-tap delay (220/480/820/1300/2000 ms) creates a long lush tail.

### 4. Sub pulse
Every 4 beats, a 110 → 40 Hz pitch-sweep sine with a 220 ms decay envelope.
Bass-only — 1-pole LPF at 180 Hz strips any harmonic colour. This is the
piece's heartbeat; it must be felt more than heard.

### 5. Emulsion-noise floor
Brown noise (cumulative integral of white), HPF 200 Hz / LPF 5 kHz, multiplied
by a slow LP'd-random "breath" envelope. Final gain `0.012` — barely audible
but adds the vintage-film hiss that makes the rest sit naturally in the mix.

## Master chain

1. `peak = max(|mix|)`; if `> 0.95`, attenuate.
2. `mix = tanh(mix × 1.15) × 0.88` — soft saturation to glue the layers.
3. Stereo widening via 18 ms Haas delay on the right channel only — adds
   spaciousness without breaking phase coherence on bass.

## Why these choices

- **No drums in the conventional sense.** The piece breathes; the sub-pulse
  is felt every ~4 seconds and is the only periodic element.
- **Pentatonic sparkles, not the full scale.** Avoids accidental dissonance
  with the underlying chord.
- **Saw + sine + sub-tri pad rather than a sampled string.** Fully self-
  contained, no asset dependencies, total render time ~ 4 seconds at 26 s
  duration.
- **Mode-aware chord builder.** A "minor / i-VII-VI-VII" brief produces
  Aeolian voicings automatically; a "dorian / i-iv-v-i" brief raises the 6th.
