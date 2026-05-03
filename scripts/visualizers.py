"""
visualizers.py — registry of blob-aware visualization flavors.

Every visualizer exposes a uniform interface:

    v = get_visualizer("centroid-trail", **params)
    v.setup(frame_h, frame_w)
    canvas = v(canvas_bgr, blobs, mask, t=time_s, audio=audio_features)

Visualizers are STACKABLE — render.py composes a chain of them per frame:

    chain = [get_visualizer(n) for n in args.viz.split(",")]
    for v in chain: canvas = v(canvas, blobs, mask, t=t, audio=audio)

`audio` is an optional dict {"amp", "kick", "high", "onset"} produced by
audio_features.py — visualizers modulate intensity with whichever bands
they care about (or ignore audio entirely).

Available flavors (registry keys):
    bbox             Plain green rectangles around each blob.
    corner-ticks     L-shaped corner brackets + IDs (the original HUD).
    crosshair        Centroid cross + ID label.
    centroid-trail   Long-decay coloured ink trail per blob ID.
    network          Lines between nearby blob centres.
    letters          ASCII letters spawned along blob velocity.
    emojis           Color-emoji glyphs spawned along blob velocity (PIL).
    glyphs           Unicode shape constellation around each centroid.
    cctv-zoom        Corner inset of the largest blob, CCTV-style.
    silhouette       Fill the blob mask with hue-cycling colour.
    outline          Draw blob mask contour line.
    voronoi          Voronoi cells from blob centres.
    convex-hull      Convex polygon enclosing all blob centres.
    heatmap          Long-accumulating occupancy overlay.
    spatial-echo     Each blob bbox shows pixels sampled from elsewhere
                     in the same frame (mirror / offset / time-shift).
"""
from __future__ import annotations

import math
from typing import Optional

import numpy as np
import cv2


# ============================================================
# Base
# ============================================================

class BaseVisualizer:
    name: str = "base"

    def __init__(self, **params):
        self.params = params
        self._h: Optional[int] = None
        self._w: Optional[int] = None

    def setup(self, h: int, w: int):
        self._h = h
        self._w = w

    def __call__(self, canvas, blobs, mask, *, t: float = 0.0, audio=None):
        if self._h is None:
            self.setup(canvas.shape[0], canvas.shape[1])
        return self.render(canvas, blobs, mask, t=t, audio=audio or {})

    def render(self, canvas, blobs, mask, *, t, audio):
        raise NotImplementedError


def _audio(audio, key, default=0.0):
    if not audio:
        return default
    v = audio.get(key, default)
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


# ============================================================
# 1. bbox — plain rectangles
# ============================================================

class BBoxVisualizer(BaseVisualizer):
    """Plain rectangles. Optional label per box and optional audio-reactive
    thickness pulse for fast HUD-style trailers."""
    name = "bbox"

    def __init__(self, *, color=(255, 255, 255), thickness: int = 2,
                 show_label: bool = False,
                 pulse_audio: bool = False,
                 pulse_band: str = "kick",
                 max_thickness: int = 6,
                 **kw):
        super().__init__(**kw)
        self.color = tuple(int(c) for c in color)
        self.thickness = thickness
        self.show_label = show_label
        self.pulse_audio = pulse_audio
        self.pulse_band = pulse_band
        self.max_thickness = max_thickness

    def render(self, canvas, blobs, mask, *, t, audio):
        out = canvas.copy()
        if self.pulse_audio:
            level = max(_audio(audio, self.pulse_band),
                        _audio(audio, "onset"))
            thick = int(self.thickness +
                        (self.max_thickness - self.thickness) * level)
        else:
            thick = self.thickness
        for i, b in enumerate(blobs):
            cv2.rectangle(out, (b.x, b.y), (b.x + b.w, b.y + b.h),
                          self.color, thick, cv2.LINE_AA)
            if self.show_label:
                tag_id = b.id if b.id >= 0 else i
                cv2.putText(out, f"#{tag_id:02d} {int(b.score):05d}",
                            (b.x + 4, max(14, b.y - 6)),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.42,
                            self.color, 1, cv2.LINE_AA)
        return out


# ============================================================
# 2. corner-ticks — original HUD-style brackets
# ============================================================

class CornerTicksVisualizer(BaseVisualizer):
    name = "corner-ticks"

    def __init__(self, *, primary_color=(255, 240, 220),
                 accent_color=(40, 255, 80),
                 label: str = "", **kw):
        super().__init__(**kw)
        self.primary = tuple(int(c) for c in primary_color)
        self.accent = tuple(int(c) for c in accent_color)
        self.label = label

    def render(self, canvas, blobs, mask, *, t, audio):
        out = canvas.copy()
        h, w = out.shape[:2]
        amp = _audio(audio, "amp")
        onset = _audio(audio, "onset")
        for i, b in enumerate(blobs):
            cx, cy = b.x + b.w // 2, b.y + b.h // 2
            thick = 2 if i == 0 else 1
            tl = 14 + int(8 * onset) + (4 if i == 0 else 0)
            col = self.primary if i > 0 else self.accent
            for (px, py, dx, dy) in [
                (b.x, b.y, tl, 0), (b.x, b.y, 0, tl),
                (b.x + b.w, b.y, -tl, 0), (b.x + b.w, b.y, 0, tl),
                (b.x, b.y + b.h, tl, 0), (b.x, b.y + b.h, 0, -tl),
                (b.x + b.w, b.y + b.h, -tl, 0),
                (b.x + b.w, b.y + b.h, 0, -tl),
            ]:
                cv2.line(out, (px, py), (px + dx, py + dy), col,
                         thick, cv2.LINE_AA)
            if i < 3:
                cv2.line(out, (cx - 10, cy), (cx + 10, cy), col, 1, cv2.LINE_AA)
                cv2.line(out, (cx, cy - 10), (cx, cy + 10), col, 1, cv2.LINE_AA)
            tag_id = b.id if b.id >= 0 else i
            cv2.putText(out, f"#{tag_id:02d}  {int(b.score):05d}",
                        (b.x + 4, max(14, b.y - 6)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.40, col, 1, cv2.LINE_AA)
        if self.label:
            cv2.putText(out, self.label, (16, 30),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.85, self.primary,
                        2, cv2.LINE_AA)
        cv2.putText(out, f"t={t:5.2f}s  blobs={len(blobs):02d}",
                    (16, h - 18), cv2.FONT_HERSHEY_SIMPLEX, 0.45,
                    self.primary, 1, cv2.LINE_AA)
        return out


# ============================================================
# 3. crosshair — cross + ID at centroid
# ============================================================

class CrosshairVisualizer(BaseVisualizer):
    name = "crosshair"

    def __init__(self, *, color=(80, 255, 240), arm: int = 18, **kw):
        super().__init__(**kw)
        self.color = tuple(int(c) for c in color)
        self.arm = arm

    def render(self, canvas, blobs, mask, *, t, audio):
        out = canvas.copy()
        for b in blobs:
            cx, cy = b.x + b.w // 2, b.y + b.h // 2
            cv2.line(out, (cx - self.arm, cy), (cx + self.arm, cy),
                     self.color, 1, cv2.LINE_AA)
            cv2.line(out, (cx, cy - self.arm), (cx, cy + self.arm),
                     self.color, 1, cv2.LINE_AA)
            cv2.circle(out, (cx, cy), 3, self.color, -1, cv2.LINE_AA)
            tag_id = b.id if b.id >= 0 else -1
            if tag_id >= 0:
                cv2.putText(out, f"{tag_id:02d}",
                            (cx + self.arm + 3, cy + 5),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.42, self.color,
                            1, cv2.LINE_AA)
        return out


# ============================================================
# 4. centroid-trail — long-decay ink trail per blob ID
# ============================================================

class CentroidTrailVisualizer(BaseVisualizer):
    """Persistent buffer that decays each frame. Each blob ID gets a
    stable hue. Lifted from the original blob_render.py CentroidTraceBuffer."""
    name = "centroid-trail"

    def __init__(self, *, decay: float = 0.965, line_thickness: int = 2,
                 **kw):
        super().__init__(**kw)
        self.decay = decay
        self.line_thickness = line_thickness
        self._buf: Optional[np.ndarray] = None
        self._prev: dict[int, tuple[int, int]] = {}

    def setup(self, h, w):
        super().setup(h, w)
        self._buf = np.zeros((h, w, 3), dtype=np.float32)

    @staticmethod
    def _color_for(tid: int):
        hue = (tid * 47) % 180
        hsv = np.uint8([[[hue, 230, 245]]])
        bgr = cv2.cvtColor(hsv, cv2.COLOR_HSV2BGR)[0, 0]
        return (int(bgr[0]), int(bgr[1]), int(bgr[2]))

    def render(self, canvas, blobs, mask, *, t, audio):
        amp = _audio(audio, "amp")
        self._buf *= self.decay
        new_prev: dict[int, tuple[int, int]] = {}
        thick = self.line_thickness + int(2 * amp)
        for b in blobs:
            tid = b.id if b.id >= 0 else None
            if tid is None:
                continue
            cx, cy = b.x + b.w // 2, b.y + b.h // 2
            color = self._color_for(tid)
            if tid in self._prev:
                px, py = self._prev[tid]
                cv2.line(self._buf, (px, py), (cx, cy),
                         color, thick, cv2.LINE_AA)
            new_prev[tid] = (cx, cy)
        self._prev = new_prev
        buf_u8 = np.clip(self._buf, 0, 255).astype(np.uint8)
        return cv2.addWeighted(canvas, 1.0, buf_u8, 0.5 + 0.4 * amp, 0)


# ============================================================
# 5. network — connecting lines between blob centres
# ============================================================

class NetworkVisualizer(BaseVisualizer):
    name = "network"

    def __init__(self, *, color=(255, 255, 255),
                 max_distance: int = 280,
                 thickness: int = 1,
                 pulse_audio: bool = False,
                 pulse_band: str = "kick",
                 max_thickness: int = 3,
                 **kw):
        super().__init__(**kw)
        self.color = tuple(int(c) for c in color)
        self.max_d = max_distance
        self.thickness = thickness
        self.pulse_audio = pulse_audio
        self.pulse_band = pulse_band
        self.max_thickness = max_thickness

    def render(self, canvas, blobs, mask, *, t, audio):
        amp = _audio(audio, "amp")
        if self.pulse_audio:
            level = max(_audio(audio, self.pulse_band),
                        _audio(audio, "onset"))
            thick = int(self.thickness +
                        (self.max_thickness - self.thickness) * level)
        else:
            thick = self.thickness
        out = canvas.copy()
        threshold = self.max_d + 220 * amp
        centers = [(b.x + b.w // 2, b.y + b.h // 2) for b in blobs]
        for i in range(len(centers)):
            for j in range(i + 1, len(centers)):
                d = math.hypot(centers[i][0] - centers[j][0],
                               centers[i][1] - centers[j][1])
                if d < threshold:
                    alpha = max(0.0, 1.0 - d / threshold)
                    col = tuple(int(c * (0.4 + 0.6 * alpha)) for c in self.color)
                    cv2.line(out, centers[i], centers[j], col,
                             thick, cv2.LINE_AA)
        return out


# ============================================================
# 6. letters — ASCII glyph particles along blob velocity
# ============================================================

class LettersVisualizer(BaseVisualizer):
    """Lifted from blob_render.LetterTrails. Each tracked blob spawns a few
    letters per frame along its velocity vector; letters age out over
    `lifetime` frames with linear alpha decay."""
    name = "letters"

    def __init__(self, *, lifetime: int = 30,
                 charset: Optional[str] = None,
                 seed: int = 7, **kw):
        super().__init__(**kw)
        self.lifetime = lifetime
        if charset is None:
            charset = ("ABCDEFGHIJKLMNOPQRSTUVWXYZ"
                       "abcdefghijklmnopqrstuvwxyz0123456789")
        self.charset = charset
        self._rng = np.random.default_rng(seed)
        self._particles: list[dict] = []
        self._prev: dict[int, tuple[int, int]] = {}

    def render(self, canvas, blobs, mask, *, t, audio):
        high = _audio(audio, "high")
        intensity = 0.30 + 0.60 * high
        new_prev: dict[int, tuple[int, int]] = {}
        for b in blobs[:6]:
            tid = b.id if b.id >= 0 else hash((b.x, b.y)) & 0xffff
            cx, cy = b.x + b.w // 2, b.y + b.h // 2
            new_prev[tid] = (cx, cy)
            vx = vy = 0
            if tid in self._prev:
                px, py = self._prev[tid]
                vx, vy = cx - px, cy - py
            vmag = float(np.hypot(vx, vy))
            n_spawn = int(1 + intensity * (1 + min(vmag / 6.0, 4.0)))
            for _ in range(n_spawn):
                ch = self.charset[self._rng.integers(0, len(self.charset))]
                self._particles.append({
                    "x": float(cx) + float(self._rng.normal(0, 4)),
                    "y": float(cy) + float(self._rng.normal(0, 4)),
                    "vx": vx * 0.6, "vy": vy * 0.6,
                    "ch": ch, "age": 0,
                })
        self._prev = new_prev
        out = canvas.copy()
        h, w = out.shape[:2]
        survivors = []
        for p in self._particles:
            p["age"] += 1
            if p["age"] >= self.lifetime:
                continue
            p["x"] += p["vx"] * 0.5
            p["y"] += p["vy"] * 0.5
            xi, yi = int(p["x"]), int(p["y"])
            if 0 <= xi < w and 0 <= yi < h:
                alpha = max(0.0, 1.0 - p["age"] / self.lifetime)
                shade = int(255 * alpha)
                color = (shade, shade, int(shade * 0.7))
                cv2.putText(out, p["ch"], (xi, yi),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.55,
                            color, 1, cv2.LINE_AA)
            survivors.append(p)
        self._particles = survivors
        return out


# ============================================================
# 6.5. emojis — color-emoji particles via PIL
# ============================================================

class EmojisVisualizer(BaseVisualizer):
    """Like LettersVisualizer but renders Unicode color emoji via PIL.
    OpenCV's `putText` only knows ASCII vector glyphs, so we route through
    PIL with a system color-emoji font.

    Font auto-detection (override with `font_path` param):
      macOS  → /System/Library/Fonts/Apple Color Emoji.ttc
      Debian → /usr/share/fonts/truetype/noto/NotoColorEmoji.ttf
      Fedora → /usr/share/fonts/google-noto-color-emoji/NotoColorEmoji.ttf
      Arch   → /usr/share/fonts/noto-color-emoji/NotoColorEmoji.ttf

    Apple Color Emoji renders best at ~32-48 px; bitmap fonts are
    auto-resized but get jagged below 16 px or above 96 px.
    """
    name = "emojis"

    DEFAULT_FONT_PATHS = (
        "/System/Library/Fonts/Apple Color Emoji.ttc",
        "/usr/share/fonts/truetype/noto/NotoColorEmoji.ttf",
        "/usr/share/fonts/google-noto-color-emoji/NotoColorEmoji.ttf",
        "/usr/share/fonts/noto-color-emoji/NotoColorEmoji.ttf",
    )
    DEFAULT_CHARSET = "🌸🌺🌻🌷✨🎆🎇🌟⭐💫🌿"

    def __init__(self, *, lifetime: int = 30,
                 charset: Optional[str] = None,
                 font_path: Optional[str] = None,
                 font_size: int = 36,
                 seed: int = 7, **kw):
        super().__init__(**kw)
        self.lifetime = lifetime
        self.charset = charset if charset else self.DEFAULT_CHARSET
        self.font_size = font_size
        self._rng = np.random.default_rng(seed)
        self._particles: list[dict] = []
        self._prev: dict[int, tuple[int, int]] = {}
        # PIL imports — local so import-time stays cheap when this viz
        # is unused
        try:
            from PIL import Image, ImageDraw, ImageFont
        except ImportError as e:
            raise SystemExit(
                "emojis viz needs Pillow. pip install pillow") from e
        self._Image = Image
        self._ImageDraw = ImageDraw
        # find font
        from pathlib import Path as _Path
        candidates = [font_path] if font_path else self.DEFAULT_FONT_PATHS
        self._font_path = next(
            (p for p in candidates if p and _Path(p).exists()), None)
        if self._font_path is None:
            print(f"WARN: emojis viz: no color-emoji font found in "
                  f"{self.DEFAULT_FONT_PATHS}; emojis will render as boxes.",
                  file=__import__("sys").stderr)
            self._font = ImageFont.load_default()
        elif self._font_path.endswith(".ttc"):
            # Apple Color Emoji is a TTC — index 0 is the emoji face
            try:
                self._font = ImageFont.truetype(self._font_path,
                                                 font_size, index=0)
            except Exception:
                self._font = ImageFont.load_default()
        else:
            try:
                self._font = ImageFont.truetype(self._font_path, font_size)
            except Exception:
                self._font = ImageFont.load_default()
        # Each emoji codepoint may be one or two UTF-16 surrogates; build a
        # list of grapheme strings so charset[i] always gives one full emoji
        self._glyphs = list(self.charset)

    def render(self, canvas, blobs, mask, *, t, audio):
        # spawn new emojis from each blob's velocity
        high = _audio(audio, "high")
        intensity = 0.30 + 0.60 * high
        new_prev: dict[int, tuple[int, int]] = {}
        for b in blobs[:6]:
            tid = b.id if b.id >= 0 else hash((b.x, b.y)) & 0xffff
            cx, cy = b.x + b.w // 2, b.y + b.h // 2
            new_prev[tid] = (cx, cy)
            vx = vy = 0
            if tid in self._prev:
                px, py = self._prev[tid]
                vx, vy = cx - px, cy - py
            vmag = float(np.hypot(vx, vy))
            n_spawn = int(1 + intensity * (1 + min(vmag / 6.0, 4.0)))
            for _ in range(n_spawn):
                idx = int(self._rng.integers(0, len(self._glyphs)))
                ch = self._glyphs[idx]
                self._particles.append({
                    "x": float(cx) + float(self._rng.normal(0, 6)),
                    "y": float(cy) + float(self._rng.normal(0, 6)),
                    "vx": vx * 0.6, "vy": vy * 0.6,
                    "ch": ch, "age": 0,
                })
        self._prev = new_prev

        # age + drift particles, batch-draw on a single PIL pass
        h, w = canvas.shape[:2]
        # convert BGR → RGB for PIL once
        pil_img = self._Image.fromarray(
            cv2.cvtColor(canvas, cv2.COLOR_BGR2RGB))
        draw = self._ImageDraw.Draw(pil_img)
        survivors = []
        for p in self._particles:
            p["age"] += 1
            if p["age"] >= self.lifetime:
                continue
            p["x"] += p["vx"] * 0.5
            p["y"] += p["vy"] * 0.5
            xi, yi = int(p["x"]), int(p["y"])
            if -self.font_size < xi < w and -self.font_size < yi < h:
                # offset so the glyph centre lands on (xi, yi)
                gx = xi - self.font_size // 2
                gy = yi - self.font_size // 2
                try:
                    draw.text((gx, gy), p["ch"], font=self._font,
                              embedded_color=True)
                except Exception:
                    # If embedded_color isn't supported, fall back to plain
                    try:
                        draw.text((gx, gy), p["ch"], font=self._font,
                                  fill=(255, 255, 255))
                    except Exception:
                        pass
            survivors.append(p)
        self._particles = survivors

        # convert RGB → BGR for cv2
        return cv2.cvtColor(np.array(pil_img), cv2.COLOR_RGB2BGR)


# ============================================================
# 7. glyphs — Unicode shape constellation around each blob
# ============================================================

class GlyphsVisualizer(BaseVisualizer):
    """Scatter `K` Unicode shape glyphs in a 2-D gaussian cloud centred on
    each blob. Cheap stand-in for instanced point sprites."""
    name = "glyphs"

    def __init__(self, *, charset: str = "OXVT*+-=#@%", seed: int = 11,
                 **kw):
        super().__init__(**kw)
        self.charset = charset
        self._rng = np.random.default_rng(seed)

    def render(self, canvas, blobs, mask, *, t, audio):
        kick = _audio(audio, "kick")
        onset = _audio(audio, "onset")
        intensity = 0.20 + 0.55 * (kick + 0.4 * onset)
        if intensity < 0.02 or not blobs:
            return canvas
        out = canvas.copy()
        K = max(4, int(8 + 24 * intensity))
        for b in blobs[:8]:
            cx, cy = b.x + b.w // 2, b.y + b.h // 2
            radius = max(40, int(np.sqrt(b.w * b.h) * 0.6))
            for _ in range(K):
                ox = int(self._rng.normal(0, radius * 0.7))
                oy = int(self._rng.normal(0, radius * 0.7))
                gx, gy = cx + ox, cy + oy
                ch = self.charset[self._rng.integers(0, len(self.charset))]
                scale = 0.4 + 0.7 * intensity
                color = (220, 240 - int(60 * intensity),
                         255 - int(40 * intensity))
                cv2.putText(out, ch, (gx, gy),
                            cv2.FONT_HERSHEY_SIMPLEX, scale, color,
                            1, cv2.LINE_AA)
        return out


# ============================================================
# 8. cctv-zoom — corner inset of the largest blob
# ============================================================

class CCTVZoomVisualizer(BaseVisualizer):
    name = "cctv-zoom"

    def __init__(self, *, inset_w_frac: float = 0.22,
                 border_color=(60, 255, 80), **kw):
        super().__init__(**kw)
        self.inset_w_frac = inset_w_frac
        self.border = tuple(int(c) for c in border_color)

    def render(self, canvas, blobs, mask, *, t, audio):
        if not blobs:
            return canvas
        amp = _audio(audio, "amp")
        intensity = 0.50 + 0.30 * amp
        h, w = canvas.shape[:2]
        b = blobs[0]
        cx, cy = b.x + b.w // 2, b.y + b.h // 2
        pad = int(max(b.w, b.h) * 0.65)
        crop_size = max(120, pad * 2)
        cx0 = max(0, cx - crop_size // 2); cy0 = max(0, cy - crop_size // 2)
        cx1 = min(w, cx0 + crop_size);     cy1 = min(h, cy0 + crop_size)
        if cx1 <= cx0 + 8 or cy1 <= cy0 + 8:
            return canvas
        crop = canvas[cy0:cy1, cx0:cx1]
        dst_w = int(w * self.inset_w_frac * (0.8 + 0.4 * intensity))
        dst_h = int(dst_w * (cy1 - cy0) / (cx1 - cx0))
        dst_w = min(dst_w, w // 3)
        dst_h = min(dst_h, h // 3)
        inset = cv2.resize(crop, (dst_w, dst_h), interpolation=cv2.INTER_LINEAR)
        out = canvas.copy()
        px, py = w - dst_w - 16, 16
        out[py:py + dst_h, px:px + dst_w] = inset
        cv2.rectangle(out, (px - 2, py - 2),
                      (px + dst_w + 1, py + dst_h + 1),
                      self.border, 2, cv2.LINE_AA)
        icx, icy = px + dst_w // 2, py + dst_h // 2
        cv2.line(out, (icx - 10, icy), (icx + 10, icy), self.border, 1)
        cv2.line(out, (icx, icy - 10), (icx, icy + 10), self.border, 1)
        cv2.putText(out, "ZOOM", (px + 4, py + 14),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.40, self.border, 1, cv2.LINE_AA)
        return out


# ============================================================
# 9. silhouette — fill blob mask with hue-cycling colour
# ============================================================

class SilhouetteVisualizer(BaseVisualizer):
    """Composite a hue-cycling colour wash over the foreground mask. Like a
    traffic-cam overlay but with a slow chromatic drift."""
    name = "silhouette"

    def __init__(self, *, alpha: float = 0.45, **kw):
        super().__init__(**kw)
        self.alpha = alpha

    def render(self, canvas, blobs, mask, *, t, audio):
        if mask is None or mask.max() == 0:
            return canvas
        hue = int((t * 12) % 180)
        wash = np.zeros_like(canvas)
        hsv = np.uint8([[[hue, 220, 250]]])
        bgr = cv2.cvtColor(hsv, cv2.COLOR_HSV2BGR)[0, 0]
        wash[:] = (int(bgr[0]), int(bgr[1]), int(bgr[2]))
        m3 = cv2.cvtColor(mask, cv2.COLOR_GRAY2BGR)
        wash = cv2.bitwise_and(wash, m3)
        return cv2.addWeighted(canvas, 1.0, wash, self.alpha, 0)


# ============================================================
# 10. outline — draw blob mask contour line
# ============================================================

class OutlineVisualizer(BaseVisualizer):
    name = "outline"

    def __init__(self, *, color=(255, 255, 255), thickness: int = 2,
                 **kw):
        super().__init__(**kw)
        self.color = tuple(int(c) for c in color)
        self.thickness = thickness

    def render(self, canvas, blobs, mask, *, t, audio):
        if mask is None or mask.max() == 0:
            return canvas
        cnts, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL,
                                    cv2.CHAIN_APPROX_NONE)
        out = canvas.copy()
        cv2.drawContours(out, cnts, -1, self.color, self.thickness,
                         cv2.LINE_AA)
        return out


# ============================================================
# 11. voronoi — voronoi cells from blob centres
# ============================================================

class VoronoiVisualizer(BaseVisualizer):
    """Subdivide the canvas with Voronoi edges from blob centres. Cheap
    Subdiv2D approach — draws facet boundaries only."""
    name = "voronoi"

    def __init__(self, *, color=(220, 200, 240), thickness: int = 1, **kw):
        super().__init__(**kw)
        self.color = tuple(int(c) for c in color)
        self.thickness = thickness

    def render(self, canvas, blobs, mask, *, t, audio):
        if len(blobs) < 2:
            return canvas
        h, w = canvas.shape[:2]
        rect = (0, 0, w, h)
        subdiv = cv2.Subdiv2D(rect)
        for b in blobs:
            cx = b.x + b.w // 2; cy = b.y + b.h // 2
            cx = max(0, min(w - 1, cx)); cy = max(0, min(h - 1, cy))
            try:
                subdiv.insert((float(cx), float(cy)))
            except cv2.error:
                continue
        try:
            facets, _centers = subdiv.getVoronoiFacetList([])
        except cv2.error:
            return canvas
        out = canvas.copy()
        for facet in facets:
            pts = np.array(facet, dtype=np.int32)
            cv2.polylines(out, [pts], True, self.color,
                          self.thickness, cv2.LINE_AA)
        return out


# ============================================================
# 12. convex-hull — polygon enclosing all blob centres
# ============================================================

class ConvexHullVisualizer(BaseVisualizer):
    name = "convex-hull"

    def __init__(self, *, color=(80, 220, 255), thickness: int = 2, **kw):
        super().__init__(**kw)
        self.color = tuple(int(c) for c in color)
        self.thickness = thickness

    def render(self, canvas, blobs, mask, *, t, audio):
        if len(blobs) < 3:
            return canvas
        pts = np.array([(b.x + b.w // 2, b.y + b.h // 2) for b in blobs],
                       dtype=np.int32)
        hull = cv2.convexHull(pts)
        out = canvas.copy()
        cv2.polylines(out, [hull], True, self.color, self.thickness,
                      cv2.LINE_AA)
        return out


# ============================================================
# 13. heatmap — long-accumulating occupancy overlay
# ============================================================

class HeatmapVisualizer(BaseVisualizer):
    """Accumulate blob bboxes into a per-pixel "where-have-they-been" map,
    apply a colour LUT, alpha-blend with the canvas."""
    name = "heatmap"

    def __init__(self, *, decay: float = 0.992, alpha: float = 0.55,
                 colormap: int = cv2.COLORMAP_INFERNO, **kw):
        super().__init__(**kw)
        self.decay = decay
        self.alpha = alpha
        self.colormap = colormap
        self._heat: Optional[np.ndarray] = None

    def setup(self, h, w):
        super().setup(h, w)
        self._heat = np.zeros((h, w), dtype=np.float32)

    def render(self, canvas, blobs, mask, *, t, audio):
        self._heat *= self.decay
        for b in blobs:
            x0 = max(0, b.x); y0 = max(0, b.y)
            x1 = min(self._w, b.x + b.w); y1 = min(self._h, b.y + b.h)
            if x1 > x0 and y1 > y0:
                self._heat[y0:y1, x0:x1] += 1.0
        norm = np.clip(self._heat, 0, 255).astype(np.uint8)
        coloured = cv2.applyColorMap(norm, self.colormap)
        return cv2.addWeighted(canvas, 1.0, coloured, self.alpha, 0)


# ============================================================
# 14. spatial-echo — bbox shows pixels from elsewhere in same frame
# ============================================================

class SpatialEchoVisualizer(BaseVisualizer):
    """Each blob's bbox becomes a window onto a DIFFERENT region of the
    same frame. Configurable displacement modes:
      - mirror     sample the horizontally-mirrored point
      - flip-y     sample the vertically-mirrored point
      - rotate     sample 180 deg rotated point (== flip both)
      - offset     sample at (cx + ox, cy + oy) where (ox, oy) drift in t
      - random     each frame picks a new offset per blob (jittery)

    Optionally `time_shift_frames` samples from a previous-frame buffer
    instead of the current frame, producing a small slit-scan-style echo
    inside each blob bbox.
    """
    name = "spatial-echo"

    def __init__(self, *, mode: str = "mirror",
                 offset=(220, 0),
                 time_shift_frames: int = 0,
                 buf_len: int = 32,
                 alpha: float = 1.0,
                 border_color=(255, 100, 200),
                 border_thickness: int = 2,
                 **kw):
        super().__init__(**kw)
        if mode not in ("mirror", "flip-y", "rotate", "offset", "random"):
            raise SystemExit(f"spatial-echo: unknown mode '{mode}'")
        self.mode = mode
        self.offset = tuple(int(v) for v in offset)
        self.time_shift = int(time_shift_frames)
        self.buf_len = max(1, int(buf_len))
        self.alpha = alpha
        self.border = tuple(int(c) for c in border_color)
        self.border_thickness = border_thickness
        self._frame_buf: list[np.ndarray] = []
        self._rng = np.random.default_rng(13)

    def _source_for(self, blob, frame):
        """Compute the source rectangle in `frame` to copy into `blob`'s
        bbox. Returns (sx, sy, sw, sh) clipped to the frame."""
        h, w = frame.shape[:2]
        bw, bh = blob.w, blob.h
        cx, cy = blob.x + bw // 2, blob.y + bh // 2
        if self.mode == "mirror":
            sx_c = w - cx
            sy_c = cy
        elif self.mode == "flip-y":
            sx_c = cx
            sy_c = h - cy
        elif self.mode == "rotate":
            sx_c = w - cx
            sy_c = h - cy
        elif self.mode == "offset":
            sx_c = cx + self.offset[0]
            sy_c = cy + self.offset[1]
        else:  # random
            sx_c = cx + int(self._rng.integers(-w // 3, w // 3))
            sy_c = cy + int(self._rng.integers(-h // 3, h // 3))
        sx = int(sx_c - bw // 2); sy = int(sy_c - bh // 2)
        sx = max(0, min(w - bw, sx)); sy = max(0, min(h - bh, sy))
        return sx, sy, bw, bh

    def render(self, canvas, blobs, mask, *, t, audio):
        # update the frame buffer (so time_shift can sample older frames)
        self._frame_buf.append(canvas.copy())
        if len(self._frame_buf) > self.buf_len:
            self._frame_buf.pop(0)
        if not blobs:
            return canvas
        if self.time_shift > 0 and len(self._frame_buf) > self.time_shift:
            src_frame = self._frame_buf[-1 - self.time_shift]
        else:
            src_frame = canvas
        out = canvas.copy()
        h, w = out.shape[:2]
        for b in blobs:
            if b.w < 8 or b.h < 8:
                continue
            sx, sy, sw, sh = self._source_for(b, src_frame)
            patch = src_frame[sy:sy + sh, sx:sx + sw]
            if patch.shape[0] != sh or patch.shape[1] != sw:
                continue
            dx = max(0, b.x); dy = max(0, b.y)
            dx2 = min(w, b.x + sw); dy2 = min(h, b.y + sh)
            patch_w = dx2 - dx; patch_h = dy2 - dy
            if patch_w <= 0 or patch_h <= 0:
                continue
            patch = patch[: patch_h, : patch_w]
            if self.alpha >= 0.999:
                out[dy:dy + patch_h, dx:dx + patch_w] = patch
            else:
                roi = out[dy:dy + patch_h, dx:dx + patch_w]
                blend = cv2.addWeighted(roi, 1.0 - self.alpha,
                                         patch, self.alpha, 0)
                out[dy:dy + patch_h, dx:dx + patch_w] = blend
            if self.border_thickness > 0:
                cv2.rectangle(out, (b.x, b.y), (b.x + b.w, b.y + b.h),
                              self.border, self.border_thickness,
                              cv2.LINE_AA)
        return out


# ============================================================
# Registry
# ============================================================

REGISTRY: dict[str, type[BaseVisualizer]] = {
    cls.name: cls
    for cls in (
        BBoxVisualizer,
        CornerTicksVisualizer,
        CrosshairVisualizer,
        CentroidTrailVisualizer,
        NetworkVisualizer,
        LettersVisualizer,
        EmojisVisualizer,
        GlyphsVisualizer,
        CCTVZoomVisualizer,
        SilhouetteVisualizer,
        OutlineVisualizer,
        VoronoiVisualizer,
        ConvexHullVisualizer,
        HeatmapVisualizer,
        SpatialEchoVisualizer,
    )
}


def get_visualizer(name: str, **params) -> BaseVisualizer:
    if name not in REGISTRY:
        raise SystemExit(
            f"unknown visualizer '{name}'. Available: {sorted(REGISTRY)}")
    return REGISTRY[name](**params)


def list_visualizers() -> list[str]:
    return list(REGISTRY)


def build_chain(spec: str, params: Optional[dict] = None) -> list[BaseVisualizer]:
    """Build a chain from a comma-separated spec like
    "centroid-trail,network,corner-ticks". `params` is an optional
    name → kwargs dict for per-viz overrides."""
    params = params or {}
    return [get_visualizer(n.strip(), **(params.get(n.strip(), {})))
            for n in spec.split(",") if n.strip()]
