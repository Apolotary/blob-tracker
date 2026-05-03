"""
audio_features.py — extract per-frame audio features for visual reactivity.

Inputs:  a .wav (or any librosa-readable file), a target FPS, and a frame
         count.
Outputs: dict of np.ndarray, one entry per video frame:
   "amp"   broadband RMS amplitude   [0..1]
   "kick"  low-band energy           [0..1]
   "high"  high-band energy          [0..1]
   "onset" 1.0 on detected onsets, 0 otherwise

When no audio is available, `silence_features(n_frames)` returns the same
dict but with all-zero arrays — visualizers fall back to their static
behaviour and the rest of the pipeline keeps working.

Usage:
    feats = compute_features(audio_path, fps=30, n_frames=780)
    # access feats["amp"][f] in the render loop
"""
from __future__ import annotations

import numpy as np


SR = 44100


def compute_features(audio_path, *, fps: int, n_frames: int):
    """Returns a dict of per-frame feature arrays of length n_frames."""
    import librosa  # local import — keep audio_features importable for
                    # callers that never use audio reactivity

    audio, sr = librosa.load(str(audio_path), sr=SR, mono=True)
    audio_i16 = (audio * 32767).astype(np.int16)
    chunk = sr // fps
    amp  = np.zeros(n_frames, dtype=np.float32)
    kick = np.zeros(n_frames, dtype=np.float32)
    high = np.zeros(n_frames, dtype=np.float32)
    for f in range(n_frames):
        s = f * chunk
        e = min(s + chunk, len(audio_i16))
        c = audio_i16[s:e]
        if len(c) < 8:
            continue
        amp[f] = float(np.sqrt(np.mean(c.astype(np.float32) ** 2)))
        spec = np.abs(np.fft.rfft(c, n=2048)).astype(np.float32)
        bins = np.array_split(spec[:1024], 64)
        bm = np.array([float(b.mean()) for b in bins])
        kick[f] = float(bm[:3].mean())
        high[f] = float(bm[30:].mean())
    if amp.max()  > 0: amp  /= amp.max()
    if kick.max() > 0: kick /= kick.max()
    if high.max() > 0: high /= high.max()

    onset = np.zeros(n_frames, dtype=np.float32)
    onsets_t = librosa.onset.onset_detect(y=audio, sr=sr, units="time", delta=0.06)
    pulse_decay = 0.78
    state = 0.0
    for f in range(n_frames):
        if any(int(ot * fps) == f for ot in onsets_t):
            state = 1.0
        onset[f] = state
        state *= pulse_decay

    return {"amp": amp, "kick": kick, "high": high, "onset": onset}


def silence_features(n_frames: int):
    """All-zero feature dict — for renders without an audio track."""
    z = np.zeros(n_frames, dtype=np.float32)
    return {"amp": z, "kick": z, "high": z, "onset": z}


def slice_at(features: dict, frame: int) -> dict:
    """Return a scalar dict {amp, kick, high, onset} at the given frame
    index, suitable for passing to visualizer __call__()."""
    return {k: float(v[frame]) for k, v in features.items()}
