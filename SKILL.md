---
name: blob-tracker
description: Render a video with audio-reactive blob tracking in any of 16 detector flavors and 14 visualization flavors, layered with optional glitch primitives. Bring your own video and audio, or have the skill find a public-domain clip on the Internet Archive and compose an ambient soundtrack. Built for the Nous Research / Kimi Creative Hackathon (May 2026), Kimi Track.
version: 2.0.0
license: MIT
platforms: [macos, linux]
metadata:
  hermes:
    tags: [video, computer-vision, blob-tracking, generative, public-domain, audio-reactive, kimi]
    category: creative
  hackathon:
    event: Nous Research / Kimi Creative Hackathon (May 2026)
    track: Kimi Track
    uses_kimi: true
allowed-tools: [Bash, Read, Write]
user-invocable: true
---

# blob-tracker

Render an arbitrary video with audio-reactive blob tracking. Choose from
**16 detector flavors** and **14 visualization flavors** that combine
freely. The skill fills in any missing inputs on demand: bring your own
video + audio, or have it find a public-domain clip on the Internet
Archive and compose an ambient soundtrack.

## When to use

Invoke this skill when the user asks for any of:

- "blob-track this video"
- "track motion in <clip>" / "find blobs in <clip>"
- "make a media-art piece from <video> with <audio>"
- "find a public-domain video and blob-track it"
- "compose music for this video and add a centroid trail"
- "render <video> with the [detector flavor] detector and [viz flavor]"
- "what blob detector should I use for this footage?" (then `--auto-flavor`)

Skip this skill for: still-image generation, music-only renders, plain
video stitching without tracking.

## CLI surface

```bash
python scripts/render.py [video source] [audio source] [tracking] [output]
```

### Video source (one of)

- `--video PATH` — use existing file
- `--find-video "<query>"` — search Internet Archive (no Kimi expansion)
- `--brief "<text>"` — Kimi expands to 3-5 IA queries, vision-picks the best

### Audio source (zero or one of)

- `--audio PATH` — use existing file (.wav/.mp3/.m4a)
- `--compose-music` — synthesise an ambient soundtrack (Kimi picks key/mode/bpm)
- `--music-brief "<text>"` — override brief just for music
- `--music-spec FILE.json` — bypass Kimi with explicit `{key, mode, bpm, progression}`
- (omit all three — render runs silent, visualizers receive zero amplitude)

### Detector + visualization

- `--detector NAME` — see [Detector flavors](#detector-flavors-16) below
- `--viz NAME1,NAME2,…` — see [Visualization flavors](#visualization-flavors-14)
- `--postfx NAME1,…` — optional non-blob glitch layer
- `--auto-flavor` — Kimi-vision picks detector + viz from a frame thumbnail

### Output

- `--output PATH` — final mp4
- `--duration 26` — default 26 s
- `--fps 30` / `--size 1080` — square crop side
- `--dual-format` — also produce 1920×1080 + 1080×1920 (Shorts/Reels)

## Detector flavors (16)

| Flavor | Algorithm | Best for |
|---|---|---|
| `motion-diff` | Frame differencing + luma threshold | Static-camera, default |
| `mog2` | OpenCV MOG2 background subtraction | Lighting changes |
| `knn` | OpenCV KNN background subtraction | Better noise rejection |
| `flow` | Farneback dense optical flow | Smooth motion, pans, drifts |
| `color-hsv` | HSV range filter | Track a single colour |
| `color-cluster` | k-means colour quantisation | Multi-region colour scenes |
| `simple-blob` | `cv2.SimpleBlobDetector` (LoG keypoints) | Distinct circular spots |
| `dog` | Difference-of-Gaussians multi-scale | Astronomy / micro / spots |
| `circles` | Hough circle transform | Round things |
| `saliency-fine` | `cv2.saliency` static fine-grained | "What's interesting" |
| `saliency-spec` | spectral residual salience | Frequency-domain salience |
| `csrt` | multi-target CSRT trackers | Persistent IDs across frames |
| `edge` | Canny + morphology + connected comps | Outline-driven |
| `accumulation` | exponentially-weighted motion accum | Slow lingering trails |
| `watershed` | marker-based watershed segmentation | Touching-blob separation |
| `contour-area` | luma threshold + contours | Static high-contrast |

Pass extra detector params via `--detector-params '{"param": value}'`.
Full reference in [`references/detector-flavors.md`](references/detector-flavors.md).

## Visualization flavors (14)

| Flavor | What it draws |
|---|---|
| `bbox` | Plain rectangles |
| `corner-ticks` | L-shaped corner brackets + IDs (the original HUD) |
| `crosshair` | Cross + ID at centroid |
| `centroid-trail` | Long-decay coloured ink trail per blob ID |
| `network` | Lines between nearby blob centres |
| `letters` | ASCII letters along blob velocity |
| `glyphs` | Unicode shape constellation around centroids |
| `cctv-zoom` | Corner inset of largest blob, CCTV-style |
| `silhouette` | Hue-cycling fill on the foreground mask |
| `outline` | Contour line on the foreground mask |
| `voronoi` | Voronoi cells from blob centres |
| `convex-hull` | Polygon enclosing all centres |
| `heatmap` | Long-accumulating occupancy overlay |
| `spatial-echo` | Each blob bbox shows pixels from ELSEWHERE in the frame |

Combine freely: `--viz centroid-trail,network,corner-ticks`. Per-viz
params: `--viz-params '{"spatial-echo": {"mode": "rotate"}}'`. Full
reference in [`references/viz-flavors.md`](references/viz-flavors.md).

## Optional glitch postfx (13)

`--postfx rgb-shift,scanlines,lagfun` etc. — applied AFTER the blob viz
chain. Defaults to empty. Full list:
`rgb-shift, yuv-split, chroma-rotate, luma-lut, sync-jitter, ripple,
mosaic, threshold-band, edge-glow, feedback, lagfun, scanlines, slit-scan`.
See [`references/postfx-glossary.md`](references/postfx-glossary.md).

## Examples

```bash
# 1. Pure: existing video + existing audio
python scripts/render.py --video clip.mp4 --audio track.wav \
    --detector mog2 --viz centroid-trail,network \
    --output out.mp4

# 2. Compose music for an existing video
python scripts/render.py --video clip.mp4 --compose-music \
    --music-brief "warm contemplative ambient pad" \
    --viz silhouette,outline --output out.mp4

# 3. Find video on IA, bring your own audio
python scripts/render.py --find-video "lunar surface NASA" \
    --audio mytrack.wav --viz heatmap,corner-ticks --output out.mp4

# 4. Full auto from creative brief
python scripts/render.py --brief "1920s botanical, dreamy ambient pad" \
    --auto-flavor --dual-format

# 5. The "spatial echo" — blob bbox shows mirrored content
python scripts/render.py --video clip.mp4 \
    --detector mog2 --viz spatial-echo,corner-ticks \
    --viz-params '{"spatial-echo":{"mode":"rotate","time_shift_frames":12}}' \
    --output out.mp4
```

## Required env

- `MOONSHOT_API_KEY` — only when using `--brief`, `--auto-flavor`, or
  `--compose-music` without `--music-spec`. Pure renders with explicit
  `--video` + (optional) `--audio` need no API key.
- `KIMI_MODEL` *(optional)* — default `kimi-k2-turbo-preview` (text).
- `KIMI_VISION_MODEL` *(optional)* — default `kimi-k2.6` (vision-capable).
- `BLOB_OUT_DIR` *(optional)* — workspace root. Default `~/blob-tracker`.

## Costs (typical 26 s piece, full-auto from brief)

- Kimi calls: ~3 (query expansion + vision pick + auto-flavor).
- Network: 0–500 MB IA download (skip with `--video`).
- Compute: pure CPU, ~3 minutes wall on Apple M1 / 8 GB.

## Helpers (each independently CLI-invokable)

| Script | Purpose |
|---|---|
| `scripts/detectors.py` | Detector registry. CLI smoke test: `python detectors.py --input v.mp4 --detector mog2` |
| `scripts/visualizers.py` | Viz registry — used by render.py |
| `scripts/postfx.py` | Glitch primitives — used by render.py |
| `scripts/audio_features.py` | RMS / kick / high / onset extractor |
| `scripts/video_search.py` | `python video_search.py --brief "..." --out winner.json` |
| `scripts/compose_music.py` | `python compose_music.py --brief "..." --out a.wav` |
| `scripts/prepare_source.py` | Download + energy-scout + square-crop helper |
| `scripts/kimi_client.py` | Shared OpenAI-compatible Kimi client |
| `scripts/render.py` | Main entry point — composes all of the above |
