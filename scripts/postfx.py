"""
postfx.py — non-blob glitch / video-art primitives.

These are *post-processing* effects applied after the blob visualizers.
They are global (don't consume blobs) — purely aesthetic chrome that
makes the output feel less clinical and more media-art.

Same interface as visualizers.py:
    fx = get_postfx("rgb-shift", **params)
    canvas = fx(canvas, blobs, mask, t=t, audio=audio)

Available primitives (registry keys):
    rgb-shift          chromatic aberration on highs
    yuv-split          NTSC chroma desync (Tachyons+ look)
    chroma-rotate      rolling HSV hue shift
    luma-lut           kolorizer false-colour LUT (Freedom Enterprise)
    sync-jitter        per-row horizontal roll (analog tracking error)
    ripple             radial sine displacement
    mosaic             pixelate / blocky downsample
    threshold-band     stacked posterised luminance bands
    edge-glow          Canny rim-light overlay
    feedback           rotated-scaled prev-frame iterated feedback
    lagfun             max-of-decayed-prev-and-curr trail
    scanlines          alternating horizontal scanline darken
    slit-scan          row Y comes from prev_buf[Y] (temporal slit)
"""
from __future__ import annotations

from typing import Optional

import numpy as np
import cv2


def _audio(audio, key, default=0.0):
    if not audio:
        return default
    try:
        return float(audio.get(key, default))
    except (TypeError, ValueError):
        return default


# ============================================================
# Base
# ============================================================

class BasePostFX:
    name: str = "base"

    def __init__(self, **params):
        self.params = params
        self._h: Optional[int] = None
        self._w: Optional[int] = None

    def setup(self, h: int, w: int):
        self._h = h
        self._w = w

    def __call__(self, canvas, blobs=None, mask=None, *, t: float = 0.0,
                 audio=None):
        if self._h is None:
            self.setup(canvas.shape[0], canvas.shape[1])
        return self.render(canvas, blobs, mask, t=t, audio=audio or {})

    def render(self, canvas, blobs, mask, *, t, audio):
        raise NotImplementedError


# ============================================================
# RGBShift
# ============================================================

class RGBShiftFX(BasePostFX):
    name = "rgb-shift"

    def render(self, canvas, blobs, mask, *, t, audio):
        intensity = 0.4 + 1.4 * _audio(audio, "high")
        if intensity < 0.02:
            return canvas
        dx = int(round(intensity * 12))
        if dx == 0:
            return canvas
        h, w = canvas.shape[:2]
        out = canvas.copy()
        M  = np.float32([[1, 0,  dx], [0, 1, 0]])
        M2 = np.float32([[1, 0, -dx], [0, 1, 0]])
        out[..., 2] = cv2.warpAffine(canvas[..., 2], M, (w, h),
                                       borderMode=cv2.BORDER_REPLICATE)
        out[..., 0] = cv2.warpAffine(canvas[..., 0], M2, (w, h),
                                       borderMode=cv2.BORDER_REPLICATE)
        return out


# ============================================================
# YUV split
# ============================================================

class YUVSplitFX(BasePostFX):
    name = "yuv-split"

    def render(self, canvas, blobs, mask, *, t, audio):
        intensity = 0.25 + 0.7 * _audio(audio, "high")
        if intensity < 0.02:
            return canvas
        yuv = cv2.cvtColor(canvas, cv2.COLOR_BGR2YUV)
        dx_u = int(round(intensity * 14))
        dx_v = -int(round(intensity * 14))
        if dx_u != 0:
            yuv[..., 1] = np.roll(yuv[..., 1], dx_u, axis=1)
        if dx_v != 0:
            yuv[..., 2] = np.roll(yuv[..., 2], dx_v, axis=1)
        return cv2.cvtColor(yuv, cv2.COLOR_YUV2BGR)


# ============================================================
# Chroma rotate
# ============================================================

class ChromaRotateFX(BasePostFX):
    name = "chroma-rotate"

    def render(self, canvas, blobs, mask, *, t, audio):
        intensity = min(0.40, 0.10 + 0.30 * _audio(audio, "amp"))
        if intensity < 0.02:
            return canvas
        hsv = cv2.cvtColor(canvas, cv2.COLOR_BGR2HSV).astype(np.float32)
        h, w = hsv.shape[:2]
        rot = (t * 60.0 * intensity) % 180
        yy = np.arange(h, dtype=np.float32)[:, None]
        band = (np.sin(yy / 80.0 - t * 2.0) * 0.5 + 0.5) * 60.0 * intensity
        hsv[..., 0] = (hsv[..., 0] + rot + band) % 180
        return cv2.cvtColor(hsv.astype(np.uint8), cv2.COLOR_HSV2BGR)


# ============================================================
# Luma LUT (kolorizer)
# ============================================================

class LumaLUTFX(BasePostFX):
    name = "luma-lut"

    def render(self, canvas, blobs, mask, *, t, audio):
        intensity = 0.20 + 0.50 * _audio(audio, "high")
        if intensity < 0.02:
            return canvas
        luma = cv2.cvtColor(canvas, cv2.COLOR_BGR2GRAY)
        lut = np.zeros((256, 1, 3), dtype=np.uint8)
        phase = t * 0.6
        for i in range(256):
            u = i / 255.0
            r = 0.5 + 0.5 * np.sin(2 * np.pi * (u + phase + 0.00))
            g = 0.5 + 0.5 * np.sin(2 * np.pi * (u + phase + 0.33))
            b = 0.5 + 0.5 * np.sin(2 * np.pi * (u + phase + 0.66))
            lut[i, 0, 2] = int(255 * r)
            lut[i, 0, 1] = int(255 * g)
            lut[i, 0, 0] = int(255 * b)
        custom = np.zeros_like(canvas)
        custom[..., 0] = lut[luma, 0, 0]
        custom[..., 1] = lut[luma, 0, 1]
        custom[..., 2] = lut[luma, 0, 2]
        return cv2.addWeighted(canvas, 1.0 - intensity, custom, intensity, 0)


# ============================================================
# Sync jitter
# ============================================================

class SyncJitterFX(BasePostFX):
    name = "sync-jitter"

    def __init__(self, *, seed: int = 20, **kw):
        super().__init__(**kw)
        self._rng = np.random.default_rng(seed)

    def render(self, canvas, blobs, mask, *, t, audio):
        kick = _audio(audio, "kick")
        onset = _audio(audio, "onset")
        if kick < 0.55 and onset < 0.05:
            return canvas
        intensity = 0.30 + 0.50 * kick
        h, w = canvas.shape[:2]
        out = canvas.copy()
        band_y = self._rng.integers(0, h)
        band_h = max(8, int(h * 0.1 * (0.4 + 0.6 * intensity)))
        band_y2 = min(h, int(band_y + band_h))
        max_shift = int(w * 0.15 * intensity)
        if max_shift <= 1:
            return canvas
        for y in range(int(band_y), band_y2):
            s = int(self._rng.integers(-max_shift, max_shift + 1))
            out[y] = np.roll(canvas[y], s, axis=0)
        return out


# ============================================================
# Ripple
# ============================================================

class RippleFX(BasePostFX):
    name = "ripple"

    def render(self, canvas, blobs, mask, *, t, audio):
        if t < 1.0:
            return canvas
        intensity = 0.30 + 0.5 * _audio(audio, "high") + 0.2 * _audio(audio, "amp")
        if intensity < 0.02:
            return canvas
        h, w = canvas.shape[:2]
        cx, cy = w / 2, h / 2
        yy, xx = np.indices((h, w), dtype=np.float32)
        rx = xx - cx; ry = yy - cy
        r = np.sqrt(rx * rx + ry * ry) + 1
        phase = r * 0.04 - t * 6.0
        amp = 8.0 * intensity
        disp = np.sin(phase) * amp
        sx = np.clip(xx + (rx / r) * disp, 0, w - 1).astype(np.float32)
        sy = np.clip(yy + (ry / r) * disp, 0, h - 1).astype(np.float32)
        return cv2.remap(canvas, sx, sy, interpolation=cv2.INTER_LINEAR,
                         borderMode=cv2.BORDER_REPLICATE)


# ============================================================
# Mosaic
# ============================================================

class MosaicFX(BasePostFX):
    name = "mosaic"

    def render(self, canvas, blobs, mask, *, t, audio):
        intensity = 0.10 + 0.5 * _audio(audio, "kick")
        if intensity < 0.02:
            return canvas
        h, w = canvas.shape[:2]
        block = max(4, int(4 + 32 * intensity))
        small = cv2.resize(canvas, (max(1, w // block), max(1, h // block)),
                           interpolation=cv2.INTER_AREA)
        return cv2.resize(small, (w, h), interpolation=cv2.INTER_NEAREST)


# ============================================================
# Threshold band
# ============================================================

class ThresholdBandFX(BasePostFX):
    name = "threshold-band"

    def render(self, canvas, blobs, mask, *, t, audio):
        amp = _audio(audio, "amp")
        if amp < 0.4:
            return canvas
        intensity = 0.35 + 0.35 * _audio(audio, "kick")
        h, w = canvas.shape[:2]
        luma = cv2.cvtColor(canvas, cv2.COLOR_BGR2GRAY)
        n_bands = max(2, int(2 + 5 * intensity))
        band_h = h // n_bands
        out = canvas.copy()
        for i in range(n_bands):
            y0 = i * band_h
            y1 = y0 + band_h if i < n_bands - 1 else h
            thr = 60 + i * (160 / max(1, n_bands - 1))
            _, bw = cv2.threshold(luma[y0:y1], thr, 255, cv2.THRESH_BINARY)
            bw3 = cv2.cvtColor(bw, cv2.COLOR_GRAY2BGR)
            out[y0:y1] = cv2.addWeighted(canvas[y0:y1], 1.0 - intensity * 0.7,
                                          bw3, intensity * 0.7, 0)
        return out


# ============================================================
# Edge glow
# ============================================================

class EdgeGlowFX(BasePostFX):
    name = "edge-glow"

    def render(self, canvas, blobs, mask, *, t, audio):
        intensity = 0.25 + 0.45 * _audio(audio, "high")
        if intensity < 0.02:
            return canvas
        gray = cv2.cvtColor(canvas, cv2.COLOR_BGR2GRAY)
        edges = cv2.Canny(gray, 50, 150)
        edges = cv2.dilate(edges, np.ones((2, 2), np.uint8), iterations=1)
        glow = cv2.GaussianBlur(edges, (0, 0), sigmaX=2.0)
        glow_bgr = cv2.cvtColor(glow, cv2.COLOR_GRAY2BGR)
        glow_bgr[..., 0] = np.clip(glow_bgr[..., 0].astype(np.int16) + 60,
                                    0, 255)
        glow_bgr[..., 2] = np.clip(glow_bgr[..., 2].astype(np.int16) + 30,
                                    0, 255)
        return cv2.addWeighted(canvas, 1.0, glow_bgr, intensity * 1.3, 0)


# ============================================================
# Feedback (stateful)
# ============================================================

class FeedbackFX(BasePostFX):
    name = "feedback"

    def __init__(self, **kw):
        super().__init__(**kw)
        self._prev: Optional[np.ndarray] = None

    def render(self, canvas, blobs, mask, *, t, audio):
        intensity = 0.30 + 0.40 * _audio(audio, "amp")
        if intensity < 0.02 or self._prev is None:
            self._prev = canvas.copy()
            return canvas
        h, w = canvas.shape[:2]
        angle = (t * 6.0 + 1.5) * intensity * 0.4
        scale = 1.02 + 0.02 * intensity
        M = cv2.getRotationMatrix2D((w / 2, h / 2), angle, scale)
        warped = cv2.warpAffine(self._prev, M, (w, h),
                                 borderMode=cv2.BORDER_REFLECT_101)
        decay = 0.55 + 0.30 * intensity
        out = cv2.addWeighted(warped, decay, canvas, 1.0 - decay * 0.6, 0)
        self._prev = out.copy()
        return out


# ============================================================
# Lagfun (stateful)
# ============================================================

class LagfunFX(BasePostFX):
    name = "lagfun"

    def __init__(self, **kw):
        super().__init__(**kw)
        self._prev: Optional[np.ndarray] = None

    def render(self, canvas, blobs, mask, *, t, audio):
        retention = 0.55 + 0.20 * _audio(audio, "amp")
        if self._prev is None:
            self._prev = canvas.copy()
            return canvas
        out = np.maximum((self._prev.astype(np.float32) * retention)
                         .astype(np.uint8), canvas)
        self._prev = out.copy()
        return out


# ============================================================
# Scanlines
# ============================================================

class ScanlinesFX(BasePostFX):
    name = "scanlines"

    def render(self, canvas, blobs, mask, *, t, audio):
        intensity = 0.18 + 0.15 * _audio(audio, "amp")
        h, w = canvas.shape[:2]
        m = np.ones((h, 1, 1), dtype=np.float32)
        m[::2, 0, 0] = 1.0 - intensity
        return (canvas.astype(np.float32) * m).astype(np.uint8)


# ============================================================
# Slit-scan (stateful — needs ring buffer)
# ============================================================

class SlitScanFX(BasePostFX):
    name = "slit-scan"

    def __init__(self, *, buf_len: int = 16, **kw):
        super().__init__(**kw)
        self.buf_len = buf_len
        self._buf: list[np.ndarray] = []

    def render(self, canvas, blobs, mask, *, t, audio):
        intensity = 0.20 + 0.6 * _audio(audio, "amp")
        self._buf.append(canvas.copy())
        if len(self._buf) > self.buf_len:
            self._buf.pop(0)
        if intensity < 0.02 or len(self._buf) < 2:
            return canvas
        h, w = canvas.shape[:2]
        out = canvas.copy()
        n_buf = len(self._buf)
        n_rows = max(8, int(h * intensity))
        y_start = (h - n_rows) // 2
        for i in range(n_rows):
            y = y_start + i
            frac = i / max(1, n_rows - 1)
            buf_idx = min(n_buf - 1, int(frac * n_buf))
            out[y] = self._buf[buf_idx][y]
        return out


# ============================================================
# Registry
# ============================================================

REGISTRY: dict[str, type[BasePostFX]] = {
    cls.name: cls
    for cls in (
        RGBShiftFX,
        YUVSplitFX,
        ChromaRotateFX,
        LumaLUTFX,
        SyncJitterFX,
        RippleFX,
        MosaicFX,
        ThresholdBandFX,
        EdgeGlowFX,
        FeedbackFX,
        LagfunFX,
        ScanlinesFX,
        SlitScanFX,
    )
}


def get_postfx(name: str, **params) -> BasePostFX:
    if name not in REGISTRY:
        raise SystemExit(
            f"unknown postfx '{name}'. Available: {sorted(REGISTRY)}")
    return REGISTRY[name](**params)


def list_postfx() -> list[str]:
    return list(REGISTRY)


def build_chain(spec: str, params: Optional[dict] = None) -> list[BasePostFX]:
    if not spec:
        return []
    params = params or {}
    return [get_postfx(n.strip(), **(params.get(n.strip(), {})))
            for n in spec.split(",") if n.strip()]
