"""
make_logo.py — generate the project logo by running blob-tracker on a
synthesised source.

Approach:
  1. Render N drifting bright circles on a dark canvas (the tracked layer).
  2. Run a detector + viz chain on it for `burnin` warmup frames so that
     trails / network / heatmap accumulate richly.
  3. Composite the title "BLOB-TRACKER" ON TOP of the tracked frame so the
     title stays legible no matter what the tracking does.

Output: assets/logo.png (1280×720 by default)

Usage:
    python scripts/make_logo.py
    python scripts/make_logo.py --detector mog2 --viz centroid-trail,network
    python scripts/make_logo.py --width 1920 --height 1080
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import cv2

sys.path.insert(0, str(Path(__file__).resolve().parent))

import detectors
import visualizers


# ============================================================
# layers
# ============================================================

def make_dark_canvas(w: int, h: int, bg=(14, 10, 22)) -> np.ndarray:
    """Near-black with a subtle radial darkening at the edges."""
    img = np.full((h, w, 3), bg, dtype=np.uint8)
    # vignette
    yy, xx = np.indices((h, w), dtype=np.float32)
    cx, cy = w / 2, h / 2
    r = np.sqrt((xx - cx) ** 2 + (yy - cy) ** 2)
    r /= r.max()
    falloff = (1.0 - 0.35 * r ** 2)[..., None]
    return (img.astype(np.float32) * falloff).clip(0, 255).astype(np.uint8)


def add_moving_blobs(canvas: np.ndarray, frame_idx: int,
                     n_blobs: int = 8) -> np.ndarray:
    """Composite N drifting bright circles. Each has its own orbit + hue."""
    out = canvas.copy()
    h, w = out.shape[:2]
    for i in range(n_blobs):
        phase = i * (2 * np.pi / n_blobs)
        speed = 0.022 + i * 0.003
        cx = int(w * (0.5 + 0.36 * np.sin(speed * frame_idx + phase)))
        cy = int(h * (0.5 + 0.28 * np.cos(speed * frame_idx * 1.4 + phase)))
        r = max(28, int(min(w, h) * 0.05
                          * (0.7 + 0.45 * np.sin(frame_idx * 0.05 + i))))
        hue = int((i * 23 + frame_idx * 1.4) % 180)
        bgr = cv2.cvtColor(np.uint8([[[hue, 230, 255]]]), cv2.COLOR_HSV2BGR)[0, 0]
        col = (int(bgr[0]), int(bgr[1]), int(bgr[2]))
        # outer glow
        glow = out.copy()
        cv2.circle(glow, (cx, cy), int(r * 1.7), col, -1, cv2.LINE_AA)
        out = cv2.addWeighted(out, 1.0, glow, 0.18, 0)
        # core
        cv2.circle(out, (cx, cy), r, col, -1, cv2.LINE_AA)
    return out


def composite_title(canvas: np.ndarray,
                    title: str = "BLOB-TRACKER",
                    subtitle: str = "16 DETECTORS   |   14 VISUALIZERS   |   HERMES SKILL"
                    ) -> np.ndarray:
    """Render the title text ON TOP of the canvas with a slight scrim
    behind it so the type stays legible."""
    out = canvas.copy()
    h, w = out.shape[:2]
    # main title geometry
    font = cv2.FONT_HERSHEY_DUPLEX
    scale = h * 0.0042
    thick = max(2, int(h * 0.006))
    (tw, th), _ = cv2.getTextSize(title, font, scale, thick)
    tx = (w - tw) // 2
    ty = (h + th) // 2 - int(h * 0.04)
    # subtitle geometry
    sfont = cv2.FONT_HERSHEY_SIMPLEX
    sscale = h * 0.0015
    sthick = max(1, int(h * 0.0025))
    (sw, sh), _ = cv2.getTextSize(subtitle, sfont, sscale, sthick)
    sx = (w - sw) // 2
    sy = ty + int(h * 0.07)
    # scrim — semi-transparent dark band behind both text rows
    pad_x, pad_y = int(w * 0.04), int(h * 0.04)
    band_x0 = min(tx, sx) - pad_x
    band_y0 = ty - th - pad_y
    band_x1 = max(tx + tw, sx + sw) + pad_x
    band_y1 = sy + pad_y
    band_x0 = max(0, band_x0); band_y0 = max(0, band_y0)
    band_x1 = min(w, band_x1); band_y1 = min(h, band_y1)
    overlay = out.copy()
    cv2.rectangle(overlay, (band_x0, band_y0), (band_x1, band_y1),
                  (10, 8, 18), -1)
    out = cv2.addWeighted(out, 0.30, overlay, 0.70, 0)
    # title — drop shadow + main
    cv2.putText(out, title, (tx + 4, ty + 6), font, scale,
                (60, 40, 80), thick + 2, cv2.LINE_AA)
    cv2.putText(out, title, (tx, ty), font, scale,
                (245, 245, 250), thick, cv2.LINE_AA)
    # subtitle
    cv2.putText(out, subtitle, (sx, sy), sfont, sscale,
                (170, 180, 210), sthick, cv2.LINE_AA)
    return out


# ============================================================
# render
# ============================================================

def render_logo(width: int, height: int,
                detector_name: str, viz_names: list[str],
                burnin: int, capture_frame: int) -> np.ndarray:
    base = make_dark_canvas(width, height)
    det = detectors.get_detector(detector_name)
    tracker = detectors.IDTracker(max_match_dist=140)
    chain = [visualizers.get_visualizer(n) for n in viz_names]
    for v in chain:
        v.setup(height, width)

    captured = None
    for f in range(max(burnin, capture_frame) + 1):
        canvas = add_moving_blobs(base, f)
        blobs, mask = det(canvas)
        blobs = tracker.assign(blobs)
        out = canvas
        for v in chain:
            out = v(out, blobs, mask, t=f / 30.0,
                    audio={"amp": 0.5, "kick": 0.55, "high": 0.55,
                           "onset": 0.0})
        if f == capture_frame:
            captured = out.copy()
    if captured is None:
        captured = out
    return composite_title(captured)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--width", type=int, default=1280)
    ap.add_argument("--height", type=int, default=720)
    ap.add_argument("--detector", default="motion-diff",
                    choices=detectors.list_detectors())
    ap.add_argument("--viz",
                    default="heatmap,centroid-trail,network,corner-ticks",
                    help="comma-separated visualizers (note: spatial-echo"
                         " on text inverts it — keep it off for the logo)")
    ap.add_argument("--burnin", type=int, default=80,
                    help="warmup frames before capture")
    ap.add_argument("--capture", type=int, default=80,
                    help="which frame to capture (counts from 0)")
    ap.add_argument("--out", default=str(Path(__file__).resolve().parent.parent
                                          / "assets" / "logo.png"))
    args = ap.parse_args()

    viz_list = [s.strip() for s in args.viz.split(",") if s.strip()]
    img = render_logo(args.width, args.height,
                      args.detector, viz_list,
                      burnin=args.burnin, capture_frame=args.capture)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(out), img, [cv2.IMWRITE_PNG_COMPRESSION, 4])
    print(f"wrote {out}  ({out.stat().st_size//1024} KB, "
          f"{img.shape[1]}x{img.shape[0]})")


if __name__ == "__main__":
    main()
