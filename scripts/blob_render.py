"""
blob_render.py — render a square 1080×1080 source.mp4 + audio.wav into a
dual-format final piece with audio-reactive blob tracking + a configurable
stack of glitch / media-art effects.

Layouts:
  horizontal 1920x1080 — pillarboxed: source centred 1080×1080, 420 px
                         black gutters left + right
  vertical   1080x1920 — letterboxed: source centred 1080×1080, 420 px
                         black gutters top + bottom

Effects (ordered, all optional via --effects ...):
  rgb_shift           chromatic aberration on high-band peaks
  ripple              radial sine displacement (circuit-bending)
  pixel_sort          luminance-sorted contiguous segments on motion peaks
  lagfun              max-of-decayed-prev-and-current trail
  invert_in_blob      colour invert inside the top-1 detected blob
  scanlines           vintage-VHS scanline interleave
  network_graph       thin lines between blob centres
  hud                 corner-tick rects + crosshairs + IDs (always-on)

Usage:
  LAYOUT=horizontal python blob_render.py \
      --source source.mp4 --audio audio.wav --slug demo --out outdir \
      --effects rgb_shift,ripple,network_graph,hud
"""
import argparse
import json
import math
import os
import subprocess
import sys
import time
from pathlib import Path

import numpy as np
import cv2
import librosa


# ============================================================
# config
# ============================================================

SR = 44100


def get_layout():
    layout = os.environ.get("LAYOUT", "horizontal")
    if layout == "vertical":
        return dict(layout=layout, W=1080, H=1920,
                    src_w=1080, src_h=1080, src_xy=(0, 420))
    else:
        return dict(layout=layout, W=1920, H=1080,
                    src_w=1080, src_h=1080, src_xy=(420, 0))


# ============================================================
# audio features
# ============================================================

def audio_features(audio_i16, sr, fps, n_frames):
    chunk = sr // fps
    amp = np.zeros(n_frames, dtype=np.float32)
    kick = np.zeros(n_frames, dtype=np.float32)
    high = np.zeros(n_frames, dtype=np.float32)
    for f in range(n_frames):
        s = f * chunk; e = min(s + chunk, len(audio_i16))
        c = audio_i16[s:e]
        if len(c) < 8:
            continue
        amp[f] = float(np.sqrt(np.mean(c.astype(np.float32) ** 2)))
        spec = np.abs(np.fft.rfft(c, n=2048)).astype(np.float32)
        bins = np.array_split(spec[:1024], 64)
        bm = np.array([float(b.mean()) for b in bins])
        kick[f] = float(bm[:3].mean())
        high[f] = float(bm[30:].mean())
    if amp.max() > 0:  amp  /= amp.max()
    if kick.max() > 0: kick /= kick.max()
    if high.max() > 0: high /= high.max()
    return amp, kick, high


# ============================================================
# Source frame cache (lazy on disk)
# ============================================================

class JPGFrameCache:
    def __init__(self, cache_dir, n):
        self.cache_dir = Path(cache_dir); self.n = n
    def __len__(self): return self.n
    def __getitem__(self, idx):
        idx = max(0, min(self.n - 1, int(idx)))
        return cv2.imread(str(self.cache_dir / f"f_{idx:05d}.jpg"))


def cache_video_frames(path, target_w, target_h, cache_dir):
    cache_dir = Path(cache_dir); cache_dir.mkdir(parents=True, exist_ok=True)
    cap = cv2.VideoCapture(str(path))
    nf = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    meta_file = cache_dir / ".src_meta.json"
    src_stat = Path(path).stat()
    src_meta = {"mtime": int(src_stat.st_mtime), "size": src_stat.st_size,
                "nf": nf, "w": target_w, "h": target_h}
    if (cache_dir / "f_00000.jpg").exists() and meta_file.exists():
        try:
            old = json.loads(meta_file.read_text())
            if all(old.get(k) == src_meta[k] for k in src_meta):
                cap.release()
                return JPGFrameCache(cache_dir, nf)
        except Exception:
            pass
    for i in range(nf):
        ok, fr = cap.read()
        if not ok or fr is None:
            nf = i; break
        fr = cv2.resize(fr, (target_w, target_h), interpolation=cv2.INTER_AREA)
        cv2.imwrite(str(cache_dir / f"f_{i:05d}.jpg"), fr,
                    [cv2.IMWRITE_JPEG_QUALITY, 92])
    cap.release()
    src_meta["nf"] = nf
    meta_file.write_text(json.dumps(src_meta))
    return JPGFrameCache(cache_dir, nf)


# ============================================================
# Effect primitives
# ============================================================

def fx_rgb_shift(img, intensity):
    if intensity < 0.02:
        return img
    h, w = img.shape[:2]
    dx = int(round(intensity * 12))
    if dx == 0:
        return img
    out = img.copy()
    M = np.float32([[1, 0, dx], [0, 1, 0]])
    M2 = np.float32([[1, 0, -dx], [0, 1, 0]])
    out[..., 2] = cv2.warpAffine(img[..., 2], M, (w, h),
                                  borderMode=cv2.BORDER_REPLICATE)
    out[..., 0] = cv2.warpAffine(img[..., 0], M2, (w, h),
                                  borderMode=cv2.BORDER_REPLICATE)
    return out


def fx_ripple(img, t, intensity):
    """Radial sine displacement — 'circuit-bending' lens warp."""
    if intensity < 0.02:
        return img
    h, w = img.shape[:2]
    cx, cy = w / 2, h / 2
    yy, xx = np.indices((h, w), dtype=np.float32)
    rx = xx - cx; ry = yy - cy
    r = np.sqrt(rx * rx + ry * ry)
    phase = r * 0.04 - t * 6.0
    amp = 8.0 * intensity
    disp = np.sin(phase) * amp
    sx = np.clip(xx + (rx / (r + 1)) * disp, 0, w - 1).astype(np.float32)
    sy = np.clip(yy + (ry / (r + 1)) * disp, 0, h - 1).astype(np.float32)
    return cv2.remap(img, sx, sy, interpolation=cv2.INTER_LINEAR,
                     borderMode=cv2.BORDER_REPLICATE)


def fx_pixel_sort_rows(img, mask, intensity):
    """Sort pixels in masked rows by luminance — vintage glitch look."""
    if intensity < 0.02:
        return img
    h, w = img.shape[:2]
    out = img.copy()
    luma = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    n_rows = max(1, int(h * 0.15 * intensity))
    candidate = np.where(mask.sum(axis=1) > 0)[0]
    if len(candidate) == 0:
        return img
    rng = np.random.default_rng(int(t_seed_anchor(img)))
    pick = rng.choice(candidate, size=min(n_rows, len(candidate)), replace=False)
    for y in pick:
        row = img[y]
        order = np.argsort(luma[y])
        out[y] = row[order]
    return out


def t_seed_anchor(img):
    """Stable per-frame seed based on the image content (avoids strobing)."""
    return int(img[0, 0, 0]) * 31 + int(img[-1, -1, -1])


def fx_lagfun(prev, curr, retention):
    """Max-of-decayed-prev and curr — phosphor-trail / lagfun TouchDesigner."""
    return np.maximum((prev.astype(np.float32) * retention).astype(np.uint8), curr)


def fx_invert_in_blob(img, blobs, kick):
    if kick < 0.55 or not blobs:
        return img
    x, y, bw, bh, _ = blobs[0]
    h, w = img.shape[:2]
    x = max(0, x); y = max(0, y); x2 = min(w, x + bw); y2 = min(h, y + bh)
    if x2 > x and y2 > y:
        img = img.copy()
        img[y:y2, x:x2] = 255 - img[y:y2, x:x2]
    return img


def fx_scanlines(img, intensity=0.18):
    h, w = img.shape[:2]
    mask = np.ones((h, 1, 1), dtype=np.float32)
    mask[::2, 0, 0] = 1.0 - intensity
    return (img.astype(np.float32) * mask).astype(np.uint8)


# --- additional primitives, video-synth lineage ---

def fx_chroma_rotate(img, t, intensity):
    """Sliding HSV hue rotation. The Hue channel rotates by `t * 60 * intensity`
    degrees and is shifted along Y by an audio-reactive offset, producing a
    classic video-synth chroma-rainbow band that drifts up the image."""
    if intensity < 0.02:
        return img
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV).astype(np.float32)
    h, w = hsv.shape[:2]
    rot = (t * 60.0 * intensity) % 180  # OpenCV hue is 0..180
    # vertical rolling band: hue shift varies along Y
    yy = np.arange(h, dtype=np.float32)[:, None]
    band = (np.sin(yy / 80.0 - t * 2.0) * 0.5 + 0.5) * 60.0 * intensity
    hsv[..., 0] = (hsv[..., 0] + rot + band) % 180
    out = cv2.cvtColor(hsv.astype(np.uint8), cv2.COLOR_HSV2BGR)
    return out


def fx_luma_lut(img, t, intensity):
    """Kolorizer / luma-to-chroma LUT remap (Freedom Enterprise / Tachyons+).
    Build a 256-entry false-colour LUT that cycles in time, apply per pixel
    keyed on luminance. Intensity blends between the original and the LUT."""
    if intensity < 0.02:
        return img
    luma = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    lut = np.zeros((256, 1, 3), dtype=np.uint8)
    phase = t * 0.6
    for i in range(256):
        u = i / 255.0
        # three offset sines = R,G,B
        r = 0.5 + 0.5 * np.sin(2 * np.pi * (u + phase + 0.00))
        g = 0.5 + 0.5 * np.sin(2 * np.pi * (u + phase + 0.33))
        b = 0.5 + 0.5 * np.sin(2 * np.pi * (u + phase + 0.66))
        lut[i, 0, 2] = int(255 * r)
        lut[i, 0, 1] = int(255 * g)
        lut[i, 0, 0] = int(255 * b)
    flat = cv2.applyColorMap(luma, cv2.COLORMAP_JET)
    # custom LUT path
    custom = np.zeros_like(img)
    custom[..., 0] = lut[luma, 0, 0]
    custom[..., 1] = lut[luma, 0, 1]
    custom[..., 2] = lut[luma, 0, 2]
    return cv2.addWeighted(img, 1.0 - intensity, custom, intensity, 0)


def fx_sync_jitter(img, intensity, rng):
    """Per-row horizontal roll, magnitude noise-modulated. Re-creates analog
    horizontal-sync loss / VHS tracking error (Freedom Enterprise sync mixer
    territory)."""
    if intensity < 0.02:
        return img
    h, w = img.shape[:2]
    out = img.copy()
    # rolling band: only some rows jitter, governed by a slow envelope
    band_y = rng.integers(0, h)
    band_h = max(8, int(h * 0.1 * (0.4 + 0.6 * intensity)))
    band_y2 = min(h, band_y + band_h)
    max_shift = int(w * 0.15 * intensity)
    if max_shift <= 1:
        return img
    for y in range(band_y, band_y2):
        s = int(rng.integers(-max_shift, max_shift + 1))
        out[y] = np.roll(img[y], s, axis=0)
    return out


def fx_yuv_split(img, intensity):
    """YUV/YIQ chroma desync — split Y and UV apart, shift them separately,
    recombine. The hallmark Tachyons+ NTSC subcarrier-instability look."""
    if intensity < 0.02:
        return img
    yuv = cv2.cvtColor(img, cv2.COLOR_BGR2YUV).astype(np.uint8)
    h, w = yuv.shape[:2]
    dx_u = int(round(intensity * 14))
    dx_v = -int(round(intensity * 14))
    if dx_u != 0:
        yuv[..., 1] = np.roll(yuv[..., 1], dx_u, axis=1)
    if dx_v != 0:
        yuv[..., 2] = np.roll(yuv[..., 2], dx_v, axis=1)
    return cv2.cvtColor(yuv, cv2.COLOR_YUV2BGR)


def fx_feedback(prev, curr, t, intensity):
    """Iterated frame-feedback: blend the previous output with the current
    frame, sampled from a rotated+scaled version of itself. Audio-reactive
    decay. The TouchDesigner / Tachyons+ composite-feedback classic."""
    if intensity < 0.02 or prev is None:
        return curr
    h, w = curr.shape[:2]
    angle = (t * 6.0 + 1.5) * intensity * 0.4
    scale = 1.02 + 0.02 * intensity
    M = cv2.getRotationMatrix2D((w / 2, h / 2), angle, scale)
    warped = cv2.warpAffine(prev, M, (w, h),
                            borderMode=cv2.BORDER_REFLECT_101)
    decay = 0.55 + 0.30 * intensity
    out = cv2.addWeighted(warped, decay, curr, 1.0 - decay * 0.6, 0)
    return out


def fx_edge_glow(img, intensity):
    """Canny-edge overlay glow — rim-lit line-art layer composited over the
    soft frame. Adds a 'machine-vision sees the contours' feel."""
    if intensity < 0.02:
        return img
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    edges = cv2.Canny(gray, 50, 150)
    edges = cv2.dilate(edges, np.ones((2, 2), np.uint8), iterations=1)
    glow = cv2.GaussianBlur(edges, (0, 0), sigmaX=2.0)
    glow_bgr = cv2.cvtColor(glow, cv2.COLOR_GRAY2BGR)
    glow_bgr[..., 0] = np.clip(glow_bgr[..., 0].astype(np.int16) + 60, 0, 255)
    glow_bgr[..., 2] = np.clip(glow_bgr[..., 2].astype(np.int16) + 30, 0, 255)
    return cv2.addWeighted(img, 1.0, glow_bgr, intensity * 1.3, 0)


def fx_mosaic(img, intensity):
    """Pixelate / mosaic. Block size scales with intensity from 4 → 36 px."""
    if intensity < 0.02:
        return img
    h, w = img.shape[:2]
    block = max(4, int(4 + 32 * intensity))
    small = cv2.resize(img, (max(1, w // block), max(1, h // block)),
                       interpolation=cv2.INTER_AREA)
    big = cv2.resize(small, (w, h), interpolation=cv2.INTER_NEAREST)
    return big


def fx_threshold_band(img, intensity):
    """Stacked horizontal bands at varying luminance thresholds — a
    high-contrast graphic glitch reminiscent of risograph / posterised
    silkscreen work. Intensity controls band count + threshold spread."""
    if intensity < 0.02:
        return img
    h, w = img.shape[:2]
    luma = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    n_bands = max(2, int(2 + 5 * intensity))
    band_h = h // n_bands
    out = img.copy()
    for i in range(n_bands):
        y0 = i * band_h
        y1 = y0 + band_h if i < n_bands - 1 else h
        thr = 60 + i * (160 / max(1, n_bands - 1))
        _, bw = cv2.threshold(luma[y0:y1], thr, 255, cv2.THRESH_BINARY)
        bw3 = cv2.cvtColor(bw, cv2.COLOR_GRAY2BGR)
        out[y0:y1] = cv2.addWeighted(img[y0:y1], 1.0 - intensity * 0.7,
                                      bw3, intensity * 0.7, 0)
    return out


def fx_slit_scan(prev_buf, curr, intensity):
    """Vertical-axis time-displacement: row Y is sampled from `prev_buf[Y]`
    instead of the current frame. Intensity controls how much of the image
    is slit-scanned. Requires a ring-buffer of recent frames."""
    if intensity < 0.02 or not prev_buf:
        return curr
    h, w = curr.shape[:2]
    # mix: top portion uses the oldest buffered frame, bottom portion blends
    # toward present. Length of buffer determines temporal range.
    n_buf = len(prev_buf)
    out = curr.copy()
    n_rows_glitch = max(8, int(h * intensity))
    y_start = (h - n_rows_glitch) // 2
    for i in range(n_rows_glitch):
        y = y_start + i
        # frac through the slit selects which past frame to sample
        frac = i / max(1, n_rows_glitch - 1)
        buf_idx = min(n_buf - 1, int(frac * n_buf))
        out[y] = prev_buf[buf_idx][y]
    return out


# --- additional primitives, video-art reference: PJ Creations / PPPANIK / Xtal ---

class CentroidTraceBuffer:
    """Per-blob persistent ink-trail buffer (PJ Creations technique).

    Each blob ID writes its centroid position into a long-lived RGBA-style
    accumulator with a stable per-ID hue. The buffer decays each frame so
    paths fade slowly over ~2 seconds. Cheap nearest-blob ID matching across
    frames keeps a single blob's color stable as it moves.
    """
    def __init__(self, h, w, decay=0.965, max_match_dist=80):
        self.buf = np.zeros((h, w, 3), dtype=np.float32)
        self.decay = decay
        self.max_d = max_match_dist
        self.tracks = {}    # id → last (x,y) center
        self._next_id = 0

    def _color_for(self, tid):
        # 8-step hue wheel, saturated
        hue = (tid * 47) % 180   # OpenCV hue 0..180
        hsv = np.uint8([[[hue, 230, 245]]])
        bgr = cv2.cvtColor(hsv, cv2.COLOR_HSV2BGR)[0, 0]
        return (int(bgr[0]), int(bgr[1]), int(bgr[2]))

    def step(self, blobs, line_thickness=2):
        """blobs: list of (x, y, w, h, score)."""
        # decay
        self.buf *= self.decay
        # match each blob to nearest tracked id
        used = set()
        new_tracks = {}
        for (x, y, bw, bh, _) in blobs:
            cx, cy = x + bw // 2, y + bh // 2
            best_id = None; best_d = self.max_d ** 2
            for tid, (px, py) in self.tracks.items():
                if tid in used:
                    continue
                d = (cx - px) ** 2 + (cy - py) ** 2
                if d < best_d:
                    best_d = d; best_id = tid
            if best_id is None:
                best_id = self._next_id; self._next_id += 1
            else:
                used.add(best_id)
                # draw line from previous to current
                px, py = self.tracks[best_id]
                color = self._color_for(best_id)
                cv2.line(self.buf, (int(px), int(py)), (int(cx), int(cy)),
                         color, line_thickness, cv2.LINE_AA)
            new_tracks[best_id] = (cx, cy)
        self.tracks = new_tracks


def fx_centroid_trace(canvas, trace_buf, intensity):
    """Composite the trace buffer over the current canvas. Intensity controls
    blend strength."""
    if intensity < 0.02:
        return canvas
    buf_u8 = np.clip(trace_buf.buf, 0, 255).astype(np.uint8)
    return cv2.addWeighted(canvas, 1.0, buf_u8, float(intensity), 0)


def fx_glyph_swarm(canvas, blobs, t, intensity, charset="◯◇◌○◍◐◑◒◓◔",
                   rng=None):
    """At each blob center, scatter a small constellation of glyphs (default
    Unicode geometric shapes). Count + scale ∝ intensity, position offset
    follows a 2D gaussian seeded from t to keep frame-to-frame motion smooth.
    PPPANIK / nouses_kou style instancing."""
    if intensity < 0.02 or not blobs:
        return canvas
    if rng is None:
        rng = np.random.default_rng(int(t * 1000) & 0xffff)
    out = canvas.copy()
    K = max(4, int(8 + 24 * intensity))
    for (x, y, bw, bh, _) in blobs[:8]:
        cx, cy = x + bw // 2, y + bh // 2
        radius = max(40, int(np.sqrt(bw * bh) * 0.6))
        for k in range(K):
            ox = int(rng.normal(0, radius * 0.7))
            oy = int(rng.normal(0, radius * 0.7))
            gx, gy = cx + ox, cy + oy
            ch = charset[rng.integers(0, len(charset))]
            scale = 0.4 + 0.7 * intensity
            color = (220, 240 - int(60 * intensity), 255 - int(40 * intensity))
            cv2.putText(out, ch, (gx, gy), cv2.FONT_HERSHEY_SIMPLEX, scale,
                        color, 1, cv2.LINE_AA)
    return out


class LetterTrails:
    """Motion-to-letters (Xtal style) — emit a single ASCII glyph along each
    blob's velocity vector, lifetime ~30 frames with linear alpha decay.

    Letters become tracer-ribbons of language. State carries lifetime list.
    """
    def __init__(self, charset=None, lifetime=30):
        # default: A-Z + 0-9 + a few symbols
        if charset is None:
            charset = ("ABCDEFGHIJKLMNOPQRSTUVWXYZ"
                       "abcdefghijklmnopqrstuvwxyz0123456789·×∗")
        self.charset = charset
        self.lifetime = lifetime
        self.particles = []   # list of dicts: x, y, vx, vy, ch, age
        self._idx = 0
        self.prev_centers = {}   # tid → (x,y)

    def step(self, blobs, intensity, rng):
        # spawn new letters from each blob's velocity
        used = set()
        new_centers = {}
        for i, (x, y, bw, bh, _) in enumerate(blobs[:6]):
            cx, cy = x + bw // 2, y + bh // 2
            # nearest prev (cheap O(N²) but bounded by 6)
            best_id, best_d = None, 90 ** 2
            for tid, (px, py) in self.prev_centers.items():
                if tid in used:
                    continue
                d = (cx - px) ** 2 + (cy - py) ** 2
                if d < best_d:
                    best_d = d; best_id = tid
            if best_id is None:
                best_id = i + self._idx * 100   # unique
            used.add(best_id)
            new_centers[best_id] = (cx, cy)
            # velocity
            if best_id in self.prev_centers:
                px, py = self.prev_centers[best_id]
                vx, vy = cx - px, cy - py
            else:
                vx = vy = 0
            vmag = float(np.hypot(vx, vy))
            # spawn count scales with intensity + speed
            n_spawn = int(1 + intensity * (1 + min(vmag / 6.0, 4.0)))
            for _ in range(n_spawn):
                ch = self.charset[rng.integers(0, len(self.charset))]
                jitter_x = float(rng.normal(0, 4))
                jitter_y = float(rng.normal(0, 4))
                self.particles.append({
                    "x": float(cx) + jitter_x, "y": float(cy) + jitter_y,
                    "vx": float(vx) * 0.6, "vy": float(vy) * 0.6,
                    "ch": ch, "age": 0,
                })
        self.prev_centers = new_centers
        self._idx += 1
        # age + drift existing particles
        survivors = []
        for p in self.particles:
            p["age"] += 1
            if p["age"] >= self.lifetime:
                continue
            p["x"] += p["vx"] * 0.5
            p["y"] += p["vy"] * 0.5
            survivors.append(p)
        self.particles = survivors

    def render(self, canvas):
        out = canvas.copy()
        h_can, w_can = out.shape[:2]
        for p in self.particles:
            age_frac = p["age"] / self.lifetime
            alpha = max(0.0, 1.0 - age_frac)
            x, y = int(p["x"]), int(p["y"])
            if 0 <= x < w_can and 0 <= y < h_can:
                shade = int(255 * alpha)
                color = (shade, shade, int(shade * 0.7))
                cv2.putText(out, p["ch"], (x, y), cv2.FONT_HERSHEY_SIMPLEX,
                            0.55, color, 1, cv2.LINE_AA)
        return out


def fx_contour_followers(canvas, motion_mask, t, intensity, rng=None):
    """Walk along each motion-mask contour spawning short polyline segments
    at every Nth vertex. Animates the silhouette of moving regions as a
    stream of glowing dashes."""
    if intensity < 0.02:
        return canvas
    if rng is None:
        rng = np.random.default_rng(int(t * 1000) & 0xffff)
    cnts, _ = cv2.findContours(motion_mask, cv2.RETR_EXTERNAL,
                                cv2.CHAIN_APPROX_NONE)
    if not cnts:
        return canvas
    out = canvas.copy()
    step = max(3, int(20 - 14 * intensity))   # 6..20 px between dashes
    dash_len = max(4, int(6 + 14 * intensity))
    phase = int(t * 60) % step                 # crawl along the contour
    for c in cnts:
        if cv2.contourArea(c) < 800:
            continue
        c = c.reshape(-1, 2)
        n = len(c)
        if n < 8:
            continue
        for i in range(phase, n - 1, step):
            j = min(i + dash_len, n - 1)
            p0 = tuple(c[i]); p1 = tuple(c[j])
            # color cycles with phase along contour
            hue = int((i / n * 180 + t * 40) % 180)
            hsv = np.uint8([[[hue, 220, 250]]])
            bgr = cv2.cvtColor(hsv, cv2.COLOR_HSV2BGR)[0, 0]
            cv2.line(out, (int(p0[0]), int(p0[1])),
                     (int(p1[0]), int(p1[1])),
                     (int(bgr[0]), int(bgr[1]), int(bgr[2])),
                     1 + int(intensity * 2), cv2.LINE_AA)
    return out


def fx_blob_zoom_inset(canvas, blobs, intensity, inset_w_frac=0.22):
    """CCTV-style zoom inset of the top-1 blob. Crops a region around the
    largest blob, upscales to a corner inset, draws a green border + crosshair.

    Always-on at intensity>0.02; intensity controls the inset size."""
    if intensity < 0.02 or not blobs:
        return canvas
    h_can, w_can = canvas.shape[:2]
    x, y, bw, bh, _ = blobs[0]
    # crop a square around the blob, padded by 30 %
    cx, cy = x + bw // 2, y + bh // 2
    pad = int(max(bw, bh) * 0.65)
    crop_size = max(120, pad * 2)
    cx0 = max(0, cx - crop_size // 2)
    cy0 = max(0, cy - crop_size // 2)
    cx1 = min(w_can, cx0 + crop_size)
    cy1 = min(h_can, cy0 + crop_size)
    if cx1 <= cx0 + 8 or cy1 <= cy0 + 8:
        return canvas
    crop = canvas[cy0:cy1, cx0:cx1]
    # destination size — top-right corner
    dst_w = int(w_can * inset_w_frac * (0.8 + 0.4 * intensity))
    dst_h = int(dst_w * (cy1 - cy0) / (cx1 - cx0))
    dst_w = min(dst_w, w_can // 3)
    dst_h = min(dst_h, h_can // 3)
    inset = cv2.resize(crop, (dst_w, dst_h), interpolation=cv2.INTER_LINEAR)
    px = w_can - dst_w - 16
    py = 16
    out = canvas.copy()
    out[py:py + dst_h, px:px + dst_w] = inset
    # green border
    cv2.rectangle(out, (px - 2, py - 2), (px + dst_w + 1, py + dst_h + 1),
                  (60, 255, 80), 2, cv2.LINE_AA)
    # crosshair in inset
    icx, icy = px + dst_w // 2, py + dst_h // 2
    cv2.line(out, (icx - 10, icy), (icx + 10, icy), (60, 255, 80), 1, cv2.LINE_AA)
    cv2.line(out, (icx, icy - 10), (icx, icy + 10), (60, 255, 80), 1, cv2.LINE_AA)
    cv2.putText(out, "ZOOM", (px + 4, py + 14),
                cv2.FONT_HERSHEY_SIMPLEX, 0.40, (60, 255, 80), 1, cv2.LINE_AA)
    return out


def fx_mask_anchored_ripple(img, motion_mask, t, intensity):
    """Local radial sine displacement, but ONLY inside motion-mask regions.
    The bulge is anchored to where the moving subjects are, leaving the
    background unwarped. Different from `fx_ripple` which warps everything."""
    if intensity < 0.02:
        return img
    h, w = img.shape[:2]
    # gaussian-blurred mask gives soft falloff
    mask_f = (motion_mask.astype(np.float32) / 255.0)
    mask_f = cv2.GaussianBlur(mask_f, (0, 0), sigmaX=18.0)
    mask_f = np.clip(mask_f, 0.0, 1.0)
    if mask_f.max() < 0.05:
        return img
    yy, xx = np.indices((h, w), dtype=np.float32)
    # one global ripple field but its amplitude is mask-gated
    cx, cy = w / 2, h / 2
    rx = xx - cx; ry = yy - cy
    r = np.sqrt(rx * rx + ry * ry) + 1
    phase = r * 0.05 - t * 7.0
    amp_field = np.sin(phase) * 12.0 * intensity * mask_f
    sx = np.clip(xx + (rx / r) * amp_field, 0, w - 1).astype(np.float32)
    sy = np.clip(yy + (ry / r) * amp_field, 0, h - 1).astype(np.float32)
    return cv2.remap(img, sx, sy, interpolation=cv2.INTER_LINEAR,
                     borderMode=cv2.BORDER_REPLICATE)


# ============================================================
# Blob tracking
# ============================================================

def find_blobs(prev_gray, curr_gray, motion_thresh=14, luma_thresh=60,
               min_area=900, max_area=400000, max_n=14):
    diff = cv2.absdiff(prev_gray, curr_gray)
    _, motion_mask = cv2.threshold(diff, motion_thresh, 255, cv2.THRESH_BINARY)
    _, luma_mask   = cv2.threshold(curr_gray, luma_thresh, 255, cv2.THRESH_BINARY)
    mask = cv2.bitwise_or(motion_mask, luma_mask)
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7, 7))
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN,  kernel)
    cnts, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    blobs = []
    for c in cnts:
        a = cv2.contourArea(c)
        if a < min_area or a > max_area:
            continue
        x, y, bw, bh = cv2.boundingRect(c)
        score = a + bw * bh * 0.05
        blobs.append((x, y, bw, bh, score))
    blobs.sort(key=lambda b: b[4], reverse=True)
    return blobs[:max_n], mask


def draw_hud(canvas, blobs, t, amp, kick, high, onset_pulse, label, draw_network):
    h_can, w_can = canvas.shape[:2]
    col_r = int(np.clip(220 - 100 * high, 0, 255))
    col_g = int(np.clip(240 - 80  * kick, 0, 255))
    col_b = int(np.clip(255 + 0   * amp,  0, 255))
    line_color = (col_b, col_g, col_r)
    accent_color = (int(40 + 200 * onset_pulse), 255, int(40 + 100 * high))

    if draw_network:
        centers = [(b[0] + b[2] // 2, b[1] + b[3] // 2) for b in blobs]
        for i in range(len(centers)):
            for j in range(i + 1, len(centers)):
                d = math.hypot(centers[i][0] - centers[j][0],
                               centers[i][1] - centers[j][1])
                if d < 280 + 220 * amp:
                    alpha = max(0.0, 1.0 - d / (280 + 220 * amp))
                    col = tuple(int(c * (0.4 + 0.6 * alpha)) for c in line_color)
                    cv2.line(canvas, centers[i], centers[j], col, 1, cv2.LINE_AA)

    for i, (x, y, bw, bh, sc) in enumerate(blobs):
        cx, cy = x + bw // 2, y + bh // 2
        thick = 2 if i == 0 else 1
        tl = 14 + int(8 * onset_pulse) + (4 if i == 0 else 0)
        col = line_color if i > 0 else accent_color
        for (px, py, dx, dy) in [(x, y, tl, 0), (x, y, 0, tl),
                                  (x + bw, y, -tl, 0), (x + bw, y, 0, tl),
                                  (x, y + bh, tl, 0), (x, y + bh, 0, -tl),
                                  (x + bw, y + bh, -tl, 0),
                                  (x + bw, y + bh, 0, -tl)]:
            cv2.line(canvas, (px, py), (px + dx, py + dy), col, thick, cv2.LINE_AA)
        if i < 3:
            cv2.line(canvas, (cx - 10, cy), (cx + 10, cy), col, 1, cv2.LINE_AA)
            cv2.line(canvas, (cx, cy - 10), (cx, cy + 10), col, 1, cv2.LINE_AA)
        cv2.putText(canvas, f"#{i:02d}  {int(sc):05d}",
                    (x + 4, max(14, y - 6)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.40, col, 1, cv2.LINE_AA)

    cv2.putText(canvas, label, (16, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.85,
                accent_color if onset_pulse > 0.6 else line_color, 2, cv2.LINE_AA)
    cv2.putText(canvas, f"t={t:5.2f}s  blobs={len(blobs):02d}",
                (16, h_can - 18), cv2.FONT_HERSHEY_SIMPLEX, 0.45, line_color,
                1, cv2.LINE_AA)


# ============================================================
# main
# ============================================================

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", required=True)
    ap.add_argument("--audio",  required=True)
    ap.add_argument("--slug",   required=True)
    ap.add_argument("--out",    required=True, help="output dir")
    ap.add_argument("--fps", type=int, default=30)
    ap.add_argument("--duration", type=float, default=26.0)
    ap.add_argument("--effects", default="rgb_shift,ripple,lagfun,invert_in_blob,scanlines,network_graph,hud",
                    help="comma-separated subset of: rgb_shift, ripple, "
                         "pixel_sort, lagfun, invert_in_blob, scanlines, "
                         "network_graph, hud, chroma_rotate, luma_lut, "
                         "sync_jitter, yuv_split, feedback, edge_glow, "
                         "mosaic, threshold_band, slit_scan, "
                         "centroid_trace, glyph_swarm, letter_trails, "
                         "contour_followers, blob_zoom_inset, mask_ripple")
    ap.add_argument("--effects-seed", type=int, default=20,
                    help="rng seed for stochastic effects (sync_jitter etc.)")
    args = ap.parse_args()

    layout = get_layout()
    out_dir = Path(args.out); out_dir.mkdir(parents=True, exist_ok=True)
    scratch = out_dir / f".scratch_{layout['layout']}"
    scratch.mkdir(parents=True, exist_ok=True)
    src_cache = out_dir / f".src_cache_{layout['src_w']}x{layout['src_h']}"

    enabled = {e.strip() for e in args.effects.split(",") if e.strip()}
    print(f"effects: {sorted(enabled)}")

    n_frames = int(args.duration * args.fps)

    # audio
    audio, sr = librosa.load(args.audio, sr=SR, mono=True)
    audio_i16 = (audio * 32767).astype(np.int16)
    amp_arr, kick_arr, high_arr = audio_features(audio_i16, sr, args.fps, n_frames)
    onsets_t = librosa.onset.onset_detect(y=audio, sr=sr, units="time", delta=0.06)
    onset_pulse = np.zeros(n_frames, dtype=np.float32)
    for ot in onsets_t:
        oi = int(ot * args.fps)
        if 0 <= oi < n_frames:
            onset_pulse[oi] = 1.0

    src = cache_video_frames(args.source, layout["src_w"], layout["src_h"],
                             src_cache)
    n_src = len(src)
    print(f"source frames: {n_src}")

    prev_gray = None
    prev_canvas = None
    pulse_state = 0.0
    pulse_decay = 0.78
    fx_rng = np.random.default_rng(args.effects_seed)
    slit_buf = []                              # ring-buffer for slit_scan
    SLIT_BUF_LEN = 16
    # Persistent state for new primitives (initialised to source dims)
    trace_state = CentroidTraceBuffer(layout["src_h"], layout["src_w"],
                                      decay=0.965)
    letter_state = LetterTrails(lifetime=30)

    # clear stale frames
    for old in scratch.glob("f_*.png"):
        old.unlink()

    print(f"rendering {n_frames} frames @ {layout['layout']}...")
    t_start = time.time()
    for f in range(n_frames):
        t = f / args.fps
        amp  = float(amp_arr[f])
        kick = float(kick_arr[f])
        high = float(high_arr[f])
        if onset_pulse[f] > 0:
            pulse_state = 1.0
        pulse_state *= pulse_decay

        s_idx = int((f / max(1, n_frames - 1)) * (n_src - 1))
        pane = src[s_idx]
        if pane is None:
            pane = np.zeros((layout["src_h"], layout["src_w"], 3), dtype=np.uint8)
        pane = pane.copy()

        # blob tracking on the source pane
        gray = cv2.cvtColor(pane, cv2.COLOR_BGR2GRAY)
        if prev_gray is None:
            prev_gray = gray.copy()
        blobs, motion_mask = find_blobs(prev_gray, gray)

        # === Effect chain (order matters) ===

        # 1. Geometric / spatial
        if "ripple" in enabled and t > 1.0:
            pane = fx_ripple(pane, t, 0.30 + 0.5 * high + 0.2 * amp)
        if "mask_ripple" in enabled:
            pane = fx_mask_anchored_ripple(pane, motion_mask, t,
                                           0.30 + 0.50 * amp)
        if "mosaic" in enabled:
            pane = fx_mosaic(pane, 0.10 + 0.5 * kick)
        if "slit_scan" in enabled:
            pane = fx_slit_scan(slit_buf, pane, 0.20 + 0.6 * amp)

        # 2. Colour-channel manipulations (NTSC-style chroma desync)
        if "rgb_shift" in enabled:
            pane = fx_rgb_shift(pane, 0.4 + 1.4 * high)
        if "yuv_split" in enabled:
            pane = fx_yuv_split(pane, 0.25 + 0.7 * high)
        if "chroma_rotate" in enabled:
            # capped at 0.40 (was up to 0.85) — feedback that this dominated
            pane = fx_chroma_rotate(pane, t, min(0.40, 0.10 + 0.30 * amp))

        # 3. Luma / contrast remaps
        if "luma_lut" in enabled:
            pane = fx_luma_lut(pane, t, 0.20 + 0.50 * high)
        if "threshold_band" in enabled and amp > 0.4:
            pane = fx_threshold_band(pane, 0.35 + 0.35 * kick)
        if "edge_glow" in enabled:
            pane = fx_edge_glow(pane, 0.25 + 0.45 * high)

        # 4. Row-level glitches
        if "pixel_sort" in enabled and high > 0.55:
            pane = fx_pixel_sort_rows(pane, motion_mask, high)
        if "sync_jitter" in enabled and (kick > 0.55 or onset_pulse[f] > 0):
            pane = fx_sync_jitter(pane, 0.30 + 0.50 * kick, fx_rng)

        # 5. Blob-locked accents
        if "invert_in_blob" in enabled:
            pane = fx_invert_in_blob(pane, blobs, kick)

        # 6. Temporal feedback / trails
        if "feedback" in enabled and prev_canvas is not None:
            pane = fx_feedback(prev_canvas, pane, t, 0.30 + 0.40 * amp)
        if "lagfun" in enabled and prev_canvas is not None:
            pane = fx_lagfun(prev_canvas, pane, retention=0.55 + 0.20 * amp)

        # 7. Persistent ink-trail buffer (PJ Creations) — runs every frame
        # when enabled, even if blobs is empty (so the buffer keeps decaying)
        if "centroid_trace" in enabled:
            trace_state.step(blobs, line_thickness=2 + int(2 * amp))
            pane = fx_centroid_trace(pane, trace_state, 0.50 + 0.40 * amp)

        # 8. Contour followers — particles walking the motion mask
        if "contour_followers" in enabled:
            pane = fx_contour_followers(pane, motion_mask, t,
                                         0.25 + 0.50 * high, fx_rng)

        # 9. Texture overlays
        if "scanlines" in enabled:
            pane = fx_scanlines(pane, intensity=0.18 + 0.15 * amp)

        # 10. HUD / blob tracker
        if "hud" in enabled:
            draw_hud(pane, blobs, t, amp, kick, high, pulse_state,
                     label=args.slug.upper()[:12],
                     draw_network=("network_graph" in enabled))

        # 11. Glyph instancing per blob (PPPANIK style)
        if "glyph_swarm" in enabled:
            pane = fx_glyph_swarm(pane, blobs, t,
                                   0.20 + 0.55 * (kick + 0.4 * onset_pulse[f]),
                                   rng=fx_rng)

        # 12. Motion-to-letters (Xtal style) — runs every frame to age existing
        if "letter_trails" in enabled:
            letter_state.step(blobs, 0.30 + 0.60 * high, fx_rng)
            pane = letter_state.render(pane)
        else:
            # if disabled, still age out any existing particles so re-enable
            # mid-render doesn't leak stale state
            letter_state.particles = []

        # 13. CCTV zoom inset (always on top)
        if "blob_zoom_inset" in enabled:
            pane = fx_blob_zoom_inset(pane, blobs, 0.50 + 0.30 * amp)

        prev_gray = gray
        prev_canvas = pane.copy()
        # update slit-scan ring buffer with the un-HUD'd pane content
        slit_buf.append(pane.copy())
        if len(slit_buf) > SLIT_BUF_LEN:
            slit_buf.pop(0)

        # compose into final canvas
        canvas = np.zeros((layout["H"], layout["W"], 3), dtype=np.uint8)
        sx, sy = layout["src_xy"]
        canvas[sy:sy + layout["src_h"], sx:sx + layout["src_w"]] = pane
        cv2.imwrite(str(scratch / f"f_{f:05d}.png"), canvas,
                    [cv2.IMWRITE_PNG_COMPRESSION, 3])

        if (f + 1) % 30 == 0 or f == n_frames - 1:
            dt = time.time() - t_start
            fps_eff = (f + 1) / dt if dt > 0 else 0
            eta = (n_frames - f - 1) / fps_eff if fps_eff > 0 else 0
            print(f"  frame {f+1}/{n_frames} blobs={len(blobs):02d} "
                  f"{fps_eff:.1f}fps eta={eta:.0f}s")

    out_path = out_dir / f"{args.slug}-{layout['W']}x{layout['H']}.mp4"
    if out_path.exists():
        out_path.unlink()
    cmd = ["ffmpeg", "-y", "-framerate", str(args.fps),
           "-i", str(scratch / "f_%05d.png"),
           "-i", args.audio,
           "-c:v", "libx264", "-crf", "18", "-pix_fmt", "yuv420p",
           "-c:a", "aac", "-b:a", "192k",
           "-shortest", str(out_path)]
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        print("ffmpeg failed:\n" + res.stderr[-2000:], file=sys.stderr)
        sys.exit(res.returncode)
    print(f"DONE → {out_path}  ({out_path.stat().st_size//(1024*1024)}MB)")


if __name__ == "__main__":
    main()
