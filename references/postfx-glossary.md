# Effect glossary

Each primitive lives in `scripts/blob_render.py`. Toggle individually via
`--effects rgb_shift,ripple,...`. The full set is **17** effects falling
into 8 ordered stages.

## Inspiration / lineage

The video-synth-flavoured primitives (`chroma_rotate`, `luma_lut`,
`sync_jitter`, `yuv_split`, `feedback`) are translations of effects from:

- **Tachyons+** (https://tachyonsplus.com) — circuit-bent NTSC composite
  enhancers (Vortex Decoder, Psychenizer, Opti-Glitch, etc.). Trademark look:
  chroma/luma desync, saturated psychedelic posterization, composite feedback
  loops, sync-edge tearing, VHS chroma noise + edge bloom.
- **Freedom Enterprise** (https://freedomenterprise.pt) — Pedro Silva's
  Portuguese composite-video modular system (MisMatcher series, Switchblade,
  KOL LITE Kolorizer, Viddy Rot Mixer). Trademark look: sync separation/mixing
  for rolling/tearing, enhancer feedback for color blow-out, composite
  signal-path patching, luma→chroma false-color remap, dirty-mixer transitions.
- **TouchDesigner** (https://derivative.ca) — the "lagfun" trail and the
  feedback-with-rotation+scale loop are TD-canonical.
- **zaebects** — friend of the project; chroma-rotate sliding band is a nod
  to their video-synth aesthetic.

None of the listed creators have endorsed or are affiliated with this skill.
The effect names + parameter ranges below are independent reimplementations
based on observed visual signatures.

## `rgb_shift`
Chromatic-aberration tear. Splits the red and blue channels by ±N pixels
along X. Intensity ∝ `0.4 + 1.4 × high_band`. Cheap, looks great on detailed
sources. Off when `intensity < 0.02`.

## `ripple`
Radial sine-displacement warp ("circuit-bending lens"). For each pixel,
displaces along its outward-from-centre vector by `sin(r·0.04 − t·6)·8·intensity`.
Intensity ∝ `0.30 + 0.5×high + 0.2×amp`. Engages after t > 1.0 s so the
opening frames remain calm.

## `pixel_sort`
Luminance-sorted contiguous pixel runs. Picks `15 % × intensity` of the
motion-masked rows; sorts each row's BGR pixels by greyscale luminance.
Engages on `high > 0.55`. Seeded from frame content to avoid strobing.

## `lagfun`
Phosphor-trail / "lagfun" TouchDesigner pattern: `out = max(prev × R, curr)`.
Retention `R = 0.55 + 0.20 × amp`. Long highlights leave glowing trails that
decay between onsets.

## `invert_in_blob`
Flickers a colour-invert inside the top-1 blob's bounding box on `kick > 0.55`.
Reads as a percussion-locked glitch flash on the brightest moving region.

## `scanlines`
Vintage-VHS interleave: every other row darkened by `intensity`. Intensity ∝
`0.18 + 0.15 × amp`. Cheap, gives the piece an emulsion patina.

## `network_graph`
Thin connection lines between blob centres when their distance is under
`280 + 220 × amp` pixels. Line alpha falls off with distance. Reads as a
"machine-vision is reasoning about the scene" overlay.

## `hud`
Always-on TouchDesigner-style HUD over each pane: corner-tick rectangles
around each blob with audio-reactive size + colour + thickness, crosshair
plus inside top-3 blobs, blob ID + score text, top-left pane label, bottom-left
"t=Xs blobs=N" diagnostic ticker. Scales with onset pulse for accent.

---

## `chroma_rotate`
Sliding HSV hue rotation. The Hue channel rotates by `t × 60° × intensity`
plus a vertically-rolling sine band that drifts up the image. Reads as a
rainbow-bleed band sliding across the frame (a video-synth chroma-band
classic). Amp-driven.

## `luma_lut`
Kolorizer / luma → false-colour LUT remap. Builds a 256-entry LUT from three
phase-offset sines (R/G/B), which cycles continuously in time. Each pixel's
brightness re-keys the LUT, and the result blends `intensity` against the
original. Direct translation of Freedom Enterprise's KOL LITE colourizer. High-
band-driven.

## `sync_jitter`
Per-row horizontal roll, magnitude noise-modulated. Picks a vertical band of
the image (~10 % height) and rolls each row of that band by a random amount
up to `15 % × intensity` of the width. Re-creates analog horizontal-sync loss
/ VHS tracking error. Triggered on kick > 0.55 OR onset.

## `yuv_split`
YUV chroma desync: convert to YUV, shift U and V along X by independent ±N px,
recombine. The hallmark Tachyons+ NTSC-subcarrier-instability look — the colour
"slides" off the luma image. High-band-driven.

## `feedback`
Iterated frame-feedback. Sample the previous output, rotate by
`t × 6° × intensity × 0.4`, scale by `1.02 + 0.02 × intensity`, blend with
current frame at `0.55 + 0.30 × intensity` decay. Creates self-similar trails
and the TD/Tachyons+ "video feedback" texture. Amp-driven.

## `edge_glow`
Canny edges + Gaussian glow + warm tint, composited over the soft frame at
`intensity × 1.3`. Adds a "machine-vision sees the contours" rim-light layer.
High-band-driven.

## `mosaic`
Spatial pixelation. Block size from 4 px to 36 px scaling with intensity.
Kick-driven — punches in with each sub-pulse.

## `threshold_band`
Stacked horizontal bands at varying luminance thresholds, blended into the
original at `intensity × 0.7`. Each band uses a different threshold from
60 → 220, producing a risograph / posterised silkscreen feel. Engages when
amp > 0.4. Kick-driven within the band-blend mix.

## `slit_scan`
Vertical-axis time-displacement. Maintains a 16-frame ring buffer; each row
in the central band (height ∝ intensity) is sampled from a different past
buffer entry. Top of band = oldest, bottom = newest. Reads as a "smeared
through time" stretch effect. Amp-driven.

---

## Blob-tracking primitives v2 (added after PJ Creations / PPPANIK / Xtal study)

## `centroid_trace`
Persistent ink-trail buffer. Each blob ID writes its centroid into a long-lived
RGBA-style accumulator with a stable per-ID hue (47-step hue wheel). The
buffer decays each frame (`× 0.965`) so paths fade over ~2 seconds. Cheap
nearest-blob match tracks IDs across frames. Different from `lagfun` —
that decays the pixel stream; this decays *ink* on top of the stream.
Amp-driven (line thickness 2-4 px, blend strength 0.5-0.9).
**Inspired by PJ Creations TouchDesigner trace tutorial.**

## `glyph_swarm`
Per-blob instanced glyphs (PPPANIK / nouses_kou style). At each blob
centroid, scatter K = 8-32 small Unicode geometric shapes (`◯◇◌○◍◐◑◒◓◔`)
in a 2D gaussian around `√(blob_area) × 0.6` radius. Count + scale
intensity-driven. Cheap re-implementation of TouchDesigner per-blob
SOP-instancing using `cv2.putText`. Kick + onset-driven.

## `letter_trails`
Motion-to-letters (Xtal style). Each frame, each blob spawns 1-5 ASCII
letters along its velocity vector with a 30-frame lifetime, drifting at
60 % of the blob's velocity. Letters fade linearly with age. The trail
becomes language-as-trace. High-band-driven (spawn rate scales with the
sparkle band of the music).

## `contour_followers`
Walks `cv2.findContours` of the motion mask, drawing dashes every step pixels
along each contour with a hue cycling along the contour position + time.
Phase crawls forward each frame so the dashes appear to chase along the
silhouette of moving regions. High-band-driven (dash density + thickness).
Distinct from `edge_glow` — that's a static glow over Canny edges; this is
animated motion-mask contours.

## `blob_zoom_inset`
CCTV-style picture-in-picture inset of the top-1 blob. Crops a region around
the largest blob (padded 30 % beyond the bounding box), upscales to a
top-right corner inset (~22 % of frame width), green border + crosshair +
"ZOOM" badge. Surveillance aesthetic. Always-on when enabled — gates only on
"is there a top-1 blob." Amp-driven (inset size 0.8-1.2× base).

## `mask_ripple`
Mask-anchored radial sine displacement. Same kernel as `ripple` (radial sine
warp in `cv2.remap`) but the amplitude is *gated by the gaussian-blurred
motion mask*. Background stays unwarped; only the moving regions bulge.
Reads as the surface stretching where someone moves. Amp-driven, capped at
12 px peak displacement.

# Audio reactivity vocabulary (updated)

# Audio reactivity vocabulary

The renderer extracts three normalised-to-[0,1] arrays at the output FPS:

- **`amp`** — RMS amplitude per output-frame chunk
- **`kick`** — energy in FFT bins 0..2 (sub + low)
- **`high`** — energy in FFT bins 30..63 (sparkle/cymbal/sibilant)

Plus a derived per-frame **`onset_pulse`** that spikes to 1.0 on a librosa
onset and decays by 0.78 each frame (≈ 80 ms half-life). Effects map cleanly:

| Signal       | Drives                                     |
|--------------|--------------------------------------------|
| `amp`        | scanline strength, lagfun retention, network distance, centroid_trace thickness, blob_zoom inset size, mask_ripple amplitude |
| `kick`       | invert-in-blob trigger, HUD accent pulse, glyph_swarm spawn count, mosaic block size |
| `high`       | rgb_shift intensity, pixel_sort gate, ripple amplitude, letter_trails spawn rate, contour_followers density |
| `onset_pulse`| corner-tick length, accent colour swap, glyph_swarm scale boost, sync_jitter trigger |
