# Visualization flavors

Fourteen blob-aware visualizers, all exposing the same interface in
`scripts/visualizers.py`. Each is selected via `--viz NAME1,NAME2,...`
on `render.py` (a comma-separated chain), with optional
`--viz-params '{NAME: {...}}'` for per-viz overrides.

Visualizers are **stackable** — the chain runs in the order you give
them. Trail / heatmap / network usually go FIRST so HUDs and labels
stay on top.

Every visualizer accepts an `audio` dict with `{amp, kick, high, onset}`
floats in [0..1] and modulates intensity with one or more of those
bands. With no audio (`--audio` omitted and no `--compose-music`),
all bands are zero — visualizers fall back to their static behaviour.

---

## bbox

Plain rectangles around each blob. The simplest possible viz.

| Param | Default | Notes |
|---|---|---|
| `color` | (60, 255, 80) | BGR colour |
| `thickness` | 2 | line thickness |

## corner-ticks

L-shaped corner brackets + ID labels — the original HUD look from the
prototype. Onset pulses make ticks bigger; primary blob gets a brighter
accent colour.

| Param | Default | Notes |
|---|---|---|
| `primary_color` | (255, 240, 220) | base bracket colour |
| `accent_color` | (40, 255, 80) | primary-blob colour |
| `label` | "" | top-left label text |

Audio: `amp` controls bracket length, `onset` pulses the accent.

## crosshair

Cross at centroid + small ID label off to the side. Cleaner than
`corner-ticks` for dense scenes.

| Param | Default | Notes |
|---|---|---|
| `color` | (80, 255, 240) | cross colour |
| `arm` | 18 | cross arm length (px) |

## centroid-trail

Per-blob ink trail — each blob ID gets a stable hue from a colour
wheel. Accumulates into a long-decay buffer (`decay = 0.965` by
default, ~2s tail).

**Requires blob IDs.** Combine with the `csrt` detector or rely on the
built-in `IDTracker` (cheap nearest-centroid matching, used
automatically for stateless detectors).

| Param | Default | Notes |
|---|---|---|
| `decay` | 0.965 | per-frame decay (smaller = shorter) |
| `line_thickness` | 2 | base trail thickness |

Audio: `amp` boosts blend strength + thickness.

## network

Lines between nearby blob centres, with alpha falling off with distance.
Cheap "constellation" overlay.

| Param | Default | Notes |
|---|---|---|
| `color` | (255, 240, 220) | base line colour |
| `max_distance` | 280 | px — connection cutoff |

Audio: `amp` widens the connection radius.

## letters

ASCII letters spawned along each blob's velocity vector. Letters age
out over `lifetime` frames with linear alpha decay. Looks like motion
trails made of language.

| Param | Default | Notes |
|---|---|---|
| `lifetime` | 30 | frames a letter survives |
| `charset` | A-Z a-z 0-9 | source character set |
| `seed` | 7 | RNG seed |

Audio: `high` controls spawn intensity per blob.

## glyphs

Unicode shape constellation around each blob — `K` glyphs scattered
in a 2-D gaussian cloud at each centroid. Cheap per-frame instancing.

| Param | Default | Notes |
|---|---|---|
| `charset` | "OXVT*+-=#@%" | glyph set |
| `seed` | 11 | RNG seed |

Audio: `kick + 0.4 * onset` controls density.

## cctv-zoom

Corner inset of the largest blob — crops a region around blob #0,
upscales to a corner inset, draws a green border + crosshair. CCTV
surveillance look.

| Param | Default | Notes |
|---|---|---|
| `inset_w_frac` | 0.22 | inset width as fraction of canvas |
| `border_color` | (60, 255, 80) | border colour |

Audio: `amp` modulates inset size.

## silhouette

Hue-cycling colour wash inside the blob mask. Hue drifts continuously
with `t * 12` deg/sec.

| Param | Default | Notes |
|---|---|---|
| `alpha` | 0.45 | blend strength |

## outline

Single contour line traced around the blob mask. Pairs nicely with
`silhouette` (fill + outline) or stands alone for a wireframe look.

| Param | Default | Notes |
|---|---|---|
| `color` | (255, 255, 255) | line colour |
| `thickness` | 2 | line width |

## voronoi

Voronoi cells tessellate the canvas using blob centres as seed points.
Drawn with `cv2.Subdiv2D`. Edges only — no fills.

| Param | Default | Notes |
|---|---|---|
| `color` | (220, 200, 240) | edge colour |
| `thickness` | 1 | edge thickness |

Note: needs ≥ 2 blobs to render.

## convex-hull

A single convex polygon enclosing all blob centres. Useful for
showing "where the action is happening" as a gestural shape.

| Param | Default | Notes |
|---|---|---|
| `color` | (80, 220, 255) | line colour |
| `thickness` | 2 | line width |

Note: needs ≥ 3 blobs to render.

## heatmap

Long-decay accumulator that paints "where blobs have been" with a
colour map. Defaults to `COLORMAP_INFERNO`.

| Param | Default | Notes |
|---|---|---|
| `decay` | 0.992 | per-frame decay (~125 fr half-life) |
| `alpha` | 0.55 | blend over canvas |
| `colormap` | INFERNO | any `cv2.COLORMAP_*` constant |

Best stacked first in the chain so other viz draw on top.

## spatial-echo

The "blob bbox shows pixels from elsewhere" trick. Each blob's bbox
becomes a window onto a different region of the same frame.

| Param | Default | Notes |
|---|---|---|
| `mode` | "mirror" | "mirror" / "flip-y" / "rotate" / "offset" / "random" |
| `offset` | (220, 0) | (dx, dy) for `mode = "offset"` |
| `time_shift_frames` | 0 | sample from `N` frames ago instead of current |
| `buf_len` | 32 | frame buffer for time-shift |
| `alpha` | 1.0 | blend with original (1.0 = full replace) |
| `border_color` | (255, 100, 200) | bbox border colour |
| `border_thickness` | 2 | border thickness (0 = no border) |

Modes:

- **mirror** — sample from the horizontally-mirrored point in the same frame
- **flip-y** — sample from the vertically-mirrored point
- **rotate** — sample from the 180°-rotated point (mirror + flip-y)
- **offset** — sample at `(cx + dx, cy + dy)` with constant offset
- **random** — each frame picks a new offset per blob (jittery)

`time_shift_frames > 0` samples from a previous frame at the displaced
location, producing a small slit-scan-style echo inside each blob bbox.

Example combinations:

```bash
# Mirror trick — left blob shows right side, right blob shows left
--viz spatial-echo,corner-ticks
--viz-params '{"spatial-echo": {"mode": "mirror"}}'

# Rotation echo with 12-frame time shift — like a spatial-temporal warp
--viz spatial-echo,outline
--viz-params '{"spatial-echo": {"mode": "rotate", "time_shift_frames": 12}}'

# Random echo with 30% blend — chaotic
--viz spatial-echo
--viz-params '{"spatial-echo": {"mode": "random", "alpha": 0.6, "border_thickness": 0}}'
```

---

## Ordering recommendations

Render order matters — earlier viz draw underneath later ones.

| First (background) | Middle | Last (HUD on top) |
|---|---|---|
| `heatmap` | `silhouette` | `corner-ticks` |
| `centroid-trail` | `network` | `crosshair` |
| `voronoi` | `outline` | `letters` |
| `spatial-echo` | `glyphs` | `cctv-zoom` |
| | `convex-hull` | |

Default chain (`--viz centroid-trail,network,corner-ticks`) follows
this — trail is the background layer, network connects the blobs, HUD
ticks sit on top.

## Combining detector + viz

| Detector | Recommended viz combo |
|---|---|
| `motion-diff` | `corner-ticks` (default look) |
| `mog2` / `knn` | `silhouette,outline,corner-ticks` |
| `csrt` | `centroid-trail,network` (needs stable IDs) |
| `accumulation` | `heatmap,outline` |
| `flow` | `letters` (velocity-driven) |
| `color-hsv` | `silhouette,convex-hull` |
| `dog` / `circles` | `glyphs,crosshair` |
| `saliency-fine` | `spatial-echo,corner-ticks` |
| `edge` | `outline,letters` |
| `watershed` | `voronoi,silhouette` |

`--auto-flavor` will pick a sensible combination automatically by
showing Kimi-vision a sample frame.
