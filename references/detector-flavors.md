# Detector flavors

Sixteen blob-detection algorithms, all exposing the same interface in
`scripts/detectors.py`. Each is selected via `--detector NAME` on
`render.py`, with optional `--detector-params '{...}'` for kwargs.

Every detector returns:

- `blobs` — list of `Blob(x, y, w, h, score, id)` namedtuples
- `mask`  — uint8 binary foreground mask the visualizers can paint over

Detectors marked **(contrib)** require `opencv-contrib-python` (already
in `requirements.txt`).

---

## motion-diff (default)

Frame differencing + optional luma threshold. The original detector from
the early prototype. Cheap, works on most footage with a static or
slow-moving camera.

| Param | Default | Notes |
|---|---|---|
| `motion_thresh` | 14 | per-pixel diff threshold |
| `luma_thresh` | 60 | OR'd luma mask threshold |
| `use_luma` | True | combine motion + luma masks |
| `min_area` | 900 | smallest blob (px²) |
| `max_area` | 400000 | biggest blob (px²) |
| `max_n` | 14 | top-N by score |

Best for: archival film, security-cam, anything with a stationary camera.

## mog2

OpenCV's Mixture-of-Gaussians background subtractor. Builds a per-pixel
GMM background model that adapts to gradual lighting changes. Needs ~30
frames to warm up.

| Param | Default | Notes |
|---|---|---|
| `history` | 200 | frames in the background model |
| `var_threshold` | 25.0 | foreground decision threshold |
| `detect_shadows` | False | drop shadow halftones |

Best for: outdoor footage with moving clouds, indoor with changing
lights.

## knn

K-nearest-neighbours background subtractor. Generally cleaner than MOG2
on grainy / noisy footage, slightly slower.

| Param | Default | Notes |
|---|---|---|
| `history` | 200 | frames in the model |
| `dist2_threshold` | 400.0 | squared distance threshold |
| `detect_shadows` | False | drop shadow halftones |

## flow

Farneback dense optical flow → magnitude threshold → mask. Picks up
smooth motion (camera pans, slow drifts) that frame-differencing misses.

| Param | Default | Notes |
|---|---|---|
| `mag_thresh` | 1.2 | flow magnitude threshold |
| `pyr_scale` | 0.5 | Gaussian pyramid scale |
| `levels` | 3 | pyramid levels |
| `winsize` | 21 | averaging window size |

Best for: handheld / drone footage, slow-pan landscapes.

## color-hsv

HSV range filter. Track a single colour by setting `hsv_target` (centre)
and `hsv_tol` (tolerance per channel).

| Param | Default | Notes |
|---|---|---|
| `hsv_target` | (20, 200, 200) | (H 0–180, S 0–255, V 0–255) |
| `hsv_tol` | (15, 80, 80) | per-channel tolerance |

Example: track yellow flowers
```bash
--detector color-hsv \
--detector-params '{"hsv_target": [25, 220, 230], "hsv_tol": [10, 60, 60]}'
```

## color-cluster

K-means colour quantisation, then return bboxes for every quantised
cluster except the dominant background colour. Subsamples the frame
for speed.

| Param | Default | Notes |
|---|---|---|
| `k` | 6 | number of clusters |
| `sample_w` | 160 | downsample width for k-means |

Best for: paintings, illustrations, anything with broad colour regions.

## simple-blob

OpenCV's `SimpleBlobDetector` — multi-scale Laplacian-of-Gaussian
keypoint detector. Each keypoint becomes a square bbox sized by the
keypoint's scale. Good for distinct circular spots.

| Param | Default | Notes |
|---|---|---|
| `min_threshold` | 30 | low threshold for binarisation cascade |
| `max_threshold` | 220 | high threshold |
| `min_circularity` | 0.0 | filter by circularity (0 = off) |
| `min_inertia` | 0.0 | filter by inertia ratio |
| `min_convexity` | 0.0 | filter by convexity |

## dog

Difference of Gaussians at two sigmas. Threshold the response, take
connected components. The astronomy / spot-detector classic.

| Param | Default | Notes |
|---|---|---|
| `sigma_low` | 1.5 | inner Gaussian σ |
| `sigma_high` | 6.0 | outer Gaussian σ |
| `thresh` | 7.0 | DoG response threshold |

Best for: microscopy, astrophotography, particle / star fields.

## circles

Hough circle transform. Returns square bboxes around each circle, mask
filled-in.

| Param | Default | Notes |
|---|---|---|
| `dp` | 1.2 | accumulator resolution ratio |
| `min_dist` | 40 | minimum distance between circles (px) |
| `param1` | 100 | Canny upper threshold |
| `param2` | 30 | accumulator threshold |
| `min_radius` | 10 | smallest radius (px) |
| `max_radius` | 120 | largest radius (px) |

Best for: footage with round objects (eyes, balls, cells, tail-lights).

## saliency-fine (contrib)

`cv2.saliency.StaticSaliencyFineGrained` — spatially-detailed salience
map. Threshold of high-salience regions becomes the blob mask. Doesn't
need motion or background model.

| Param | Default | Notes |
|---|---|---|
| `thresh` | 0.55 | salience score threshold (0..1) |

## saliency-spec (contrib)

Spectral-residual saliency — frequency-domain "what's unusual". Often
picks up edges and boundaries the fine-grained model misses.

| Param | Default | Notes |
|---|---|---|
| `thresh` | 0.4 | salience score threshold |

## csrt (contrib)

Multi-target CSRT trackers — initialised from a one-shot motion-diff
detection, then carried forward across frames with stable IDs. Re-seeds
every `reseed_every` frames.

| Param | Default | Notes |
|---|---|---|
| `reseed_every` | 30 | frames between re-init |
| `max_targets` | 6 | max simultaneous trackers |

Best for: pieces where you want **persistent IDs** across the full
26 seconds — crucial for `centroid-trail` and `letters` viz that key
off blob ID.

## edge

Canny edges, dilated and closed, then connected-components on the
resulting line-art. Blobs become contour-bounded regions of the edge
map.

| Param | Default | Notes |
|---|---|---|
| `canny_low` | 60 | Canny lower threshold |
| `canny_high` | 160 | Canny upper threshold |
| `dilate_iter` | 2 | dilation iterations on edges |

Best for: ink / line-art aesthetics, architectural footage.

## accumulation

`cv2.accumulateWeighted` builds a slow-decaying running average of the
input. Threshold of the accumulated diff gives masks where motion has
been LATELY, not just instantaneously. Slow lingering trails.

| Param | Default | Notes |
|---|---|---|
| `alpha` | 0.10 | accumulator decay (smaller = slower) |
| `thresh` | 18 | diff threshold |

Best for: dance / movement footage where you want lingering presence.

## watershed

Threshold + distance transform + marker-based watershed segmentation.
Splits touching foreground regions cleanly. Works on roughly bimodal
frames.

| Param | Default | Notes |
|---|---|---|
| `luma_thresh` | 80 | initial foreground threshold |
| `dist_thresh_frac` | 0.45 | distance-transform threshold (0..1 of max) |

Best for: cell-like / clumped subjects (microorganisms, crowds, fruit).

## contour-area

Plain Otsu / fixed-luma threshold + connected components. No motion
needed — works on a single static frame.

| Param | Default | Notes |
|---|---|---|
| `thresh` | 0 | manual threshold (ignored if `use_otsu`) |
| `invert` | False | invert the binarisation |
| `use_otsu` | True | auto-pick threshold via Otsu |

Best for: silhouettes, X-rays, ink illustrations.

---

## How to choose

| Scenario | Detector |
|---|---|
| Static-camera prelinger archival | `motion-diff` |
| Outdoor, lighting changes | `mog2` |
| Noisy / grainy video | `knn` |
| Slow camera pan / drift | `flow` |
| Coloured object tracking | `color-hsv` |
| Persistent IDs needed (trails, letters) | `csrt` |
| Dance / dwell-time visuals | `accumulation` |
| Astronomy / particles | `dog` |
| Round objects | `circles` |
| Static painting / illustration | `contour-area` or `color-cluster` |
| "Just pick something good" | `--auto-flavor` (Kimi-vision picks) |

When in doubt, start with `motion-diff` — it works on almost everything
and produces the textbook blob-tracker look.
