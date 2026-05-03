"""
detectors.py — registry of blob-detection flavors.

Every detector exposes a uniform interface:

    det = get_detector("mog2", **params)
    blobs, mask = det(frame_bgr)

`blobs` is a list of `Blob` namedtuples (x, y, w, h, score, id).
`mask` is a uint8 binary foreground mask (0/255), useful for visualizers
that paint contour fills, heatmaps, or content-aware ripples.

Some detectors are stateful (background subtractors, optical flow,
trackers) — instantiate one detector per video, then call it on every
frame in order.

Available flavors (registry keys):
    motion-diff      Frame-differencing + luma threshold.       Cheap, classic.
    mog2             OpenCV MOG2 background subtraction.         Lighting-tolerant.
    knn              OpenCV KNN background subtraction.          Better noise rejection.
    flow             Farneback dense optical flow.               Smooth motion.
    color-hsv        HSV range filter.                           Track a colour.
    color-cluster    K-means colour quantisation → cluster.      Multi-region colour.
    simple-blob      cv2.SimpleBlobDetector (LoG keypoints).     Spot detection.
    dog              Difference-of-Gaussians multi-scale.        Astronomy / micro.
    circles          Hough circle transform.                     Round things.
    saliency-fine    cv2.saliency Static Fine-Grained.           "What's interesting".
    saliency-spec    cv2.saliency Spectral Residual.             Frequency-domain salience.
    csrt             Multi-target CSRT trackers.                 Persistent IDs.
    edge             Canny + morphology + connected comps.       Outline-driven.
    accumulation     Exponentially-weighted motion accum.        Slow lingering trails.
    watershed        Marker-based watershed segmentation.        Touching-blob separation.
    contour-area     Plain luma threshold + contours.            Static high-contrast.
"""
from __future__ import annotations

import sys
from collections import namedtuple
from typing import Optional

import numpy as np
import cv2


Blob = namedtuple("Blob", ("x", "y", "w", "h", "score", "id"))


# ============================================================
# Base
# ============================================================

class BaseDetector:
    """Abstract: subclasses implement `detect(frame_bgr)` returning
    (blobs, mask)."""
    name: str = "base"
    needs_contrib: bool = False

    def __init__(self, *,
                 min_area: int = 900,
                 max_area: int = 400_000,
                 max_n: int = 14):
        self.min_area = min_area
        self.max_area = max_area
        self.max_n = max_n

    def __call__(self, frame_bgr: np.ndarray) -> tuple[list[Blob], np.ndarray]:
        return self.detect(frame_bgr)

    def detect(self, frame_bgr):
        raise NotImplementedError

    # helpers --------------------------------------------------------------

    def _contours_to_blobs(self, mask: np.ndarray) -> list[Blob]:
        cnts, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        blobs: list[Blob] = []
        for c in cnts:
            a = cv2.contourArea(c)
            if a < self.min_area or a > self.max_area:
                continue
            x, y, bw, bh = cv2.boundingRect(c)
            score = a + bw * bh * 0.05
            blobs.append(Blob(x, y, bw, bh, float(score), -1))
        blobs.sort(key=lambda b: b.score, reverse=True)
        return blobs[: self.max_n]

    def _morph_clean(self, mask: np.ndarray, ksize: int = 7) -> np.ndarray:
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (ksize, ksize))
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
        return mask


# ============================================================
# 1. motion-diff — frame differencing
# ============================================================

class MotionDiffDetector(BaseDetector):
    """Difference current vs previous frame, threshold by motion magnitude.
    Optionally OR with luma threshold so very bright static blobs are also
    picked up. The original detector from blob_render.py."""
    name = "motion-diff"

    def __init__(self, *,
                 motion_thresh: int = 14,
                 luma_thresh: int = 60,
                 use_luma: bool = True,
                 **kw):
        super().__init__(**kw)
        self.motion_thresh = motion_thresh
        self.luma_thresh = luma_thresh
        self.use_luma = use_luma
        self._prev_gray: Optional[np.ndarray] = None

    def detect(self, frame_bgr):
        gray = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY)
        if self._prev_gray is None:
            self._prev_gray = gray.copy()
        diff = cv2.absdiff(self._prev_gray, gray)
        _, motion_mask = cv2.threshold(diff, self.motion_thresh, 255, cv2.THRESH_BINARY)
        if self.use_luma:
            _, luma_mask = cv2.threshold(gray, self.luma_thresh, 255, cv2.THRESH_BINARY)
            mask = cv2.bitwise_or(motion_mask, luma_mask)
        else:
            mask = motion_mask
        mask = self._morph_clean(mask)
        blobs = self._contours_to_blobs(mask)
        self._prev_gray = gray
        return blobs, mask


# ============================================================
# 2. mog2 — background subtraction
# ============================================================

class MOG2Detector(BaseDetector):
    """Mixture-of-Gaussians background model. Adapts to gradual lighting
    changes; gives a clean foreground mask once it has warmed up (~30 fr)."""
    name = "mog2"

    def __init__(self, *,
                 history: int = 200,
                 var_threshold: float = 25.0,
                 detect_shadows: bool = False,
                 **kw):
        super().__init__(**kw)
        self._bg = cv2.createBackgroundSubtractorMOG2(
            history=history, varThreshold=var_threshold,
            detectShadows=detect_shadows,
        )

    def detect(self, frame_bgr):
        mask = self._bg.apply(frame_bgr)
        # MOG2 with shadows on returns 127 for shadows; we threshold to keep FG only
        _, mask = cv2.threshold(mask, 200, 255, cv2.THRESH_BINARY)
        mask = self._morph_clean(mask)
        return self._contours_to_blobs(mask), mask


# ============================================================
# 3. knn — background subtraction (alternative)
# ============================================================

class KNNDetector(BaseDetector):
    """K-nearest-neighbours background subtraction. Generally cleaner than
    MOG2 on noisy footage at the cost of being a touch slower."""
    name = "knn"

    def __init__(self, *,
                 history: int = 200,
                 dist2_threshold: float = 400.0,
                 detect_shadows: bool = False,
                 **kw):
        super().__init__(**kw)
        self._bg = cv2.createBackgroundSubtractorKNN(
            history=history, dist2Threshold=dist2_threshold,
            detectShadows=detect_shadows,
        )

    def detect(self, frame_bgr):
        mask = self._bg.apply(frame_bgr)
        _, mask = cv2.threshold(mask, 200, 255, cv2.THRESH_BINARY)
        mask = self._morph_clean(mask)
        return self._contours_to_blobs(mask), mask


# ============================================================
# 4. flow — Farneback dense optical flow
# ============================================================

class OpticalFlowDetector(BaseDetector):
    """Farneback dense optical flow. Magnitude > threshold becomes the mask.
    Picks up smooth motion (camera pans, slow drift) that frame-differencing
    misses."""
    name = "flow"

    def __init__(self, *,
                 mag_thresh: float = 1.2,
                 pyr_scale: float = 0.5,
                 levels: int = 3,
                 winsize: int = 21,
                 **kw):
        super().__init__(**kw)
        self.mag_thresh = mag_thresh
        self.pyr_scale = pyr_scale
        self.levels = levels
        self.winsize = winsize
        self._prev_gray: Optional[np.ndarray] = None

    def detect(self, frame_bgr):
        gray = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY)
        if self._prev_gray is None:
            self._prev_gray = gray.copy()
            mask = np.zeros_like(gray)
            return [], mask
        flow = cv2.calcOpticalFlowFarneback(
            self._prev_gray, gray, None,
            self.pyr_scale, self.levels, self.winsize,
            iterations=3, poly_n=5, poly_sigma=1.2, flags=0,
        )
        mag = np.sqrt(flow[..., 0] ** 2 + flow[..., 1] ** 2)
        mask = (mag > self.mag_thresh).astype(np.uint8) * 255
        mask = self._morph_clean(mask, ksize=11)
        self._prev_gray = gray
        return self._contours_to_blobs(mask), mask


# ============================================================
# 5. color-hsv — HSV range filter
# ============================================================

class ColorHSVDetector(BaseDetector):
    """Threshold by an HSV range. `hsv_target` is the centre (H,S,V) and
    `hsv_tol` the tolerance per channel. OpenCV uses H in [0,180]."""
    name = "color-hsv"

    def __init__(self, *,
                 hsv_target=(20, 200, 200),
                 hsv_tol=(15, 80, 80),
                 **kw):
        super().__init__(**kw)
        self.target = tuple(int(v) for v in hsv_target)
        self.tol = tuple(int(v) for v in hsv_tol)

    def detect(self, frame_bgr):
        hsv = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2HSV)
        h, s, v = self.target
        dh, ds, dv = self.tol
        # H wraps mod 180 — need two ranges if the band crosses 0/180
        lo1 = np.array([max(0, h - dh), max(0, s - ds), max(0, v - dv)], dtype=np.uint8)
        hi1 = np.array([min(180, h + dh), min(255, s + ds), min(255, v + dv)], dtype=np.uint8)
        mask = cv2.inRange(hsv, lo1, hi1)
        if h - dh < 0:
            lo2 = np.array([180 + (h - dh), max(0, s - ds), max(0, v - dv)], dtype=np.uint8)
            hi2 = np.array([180, min(255, s + ds), min(255, v + dv)], dtype=np.uint8)
            mask = cv2.bitwise_or(mask, cv2.inRange(hsv, lo2, hi2))
        if h + dh > 180:
            lo2 = np.array([0, max(0, s - ds), max(0, v - dv)], dtype=np.uint8)
            hi2 = np.array([(h + dh) - 180, min(255, s + ds), min(255, v + dv)], dtype=np.uint8)
            mask = cv2.bitwise_or(mask, cv2.inRange(hsv, lo2, hi2))
        mask = self._morph_clean(mask, ksize=9)
        return self._contours_to_blobs(mask), mask


# ============================================================
# 6. color-cluster — k-means colour quantisation
# ============================================================

class ColorClusterDetector(BaseDetector):
    """K-means colour quantisation, then return the bounding box of each
    quantised colour cluster (excluding the dominant background colour).
    Subsamples for speed."""
    name = "color-cluster"

    def __init__(self, *, k: int = 6, sample_w: int = 160, **kw):
        super().__init__(**kw)
        self.k = k
        self.sample_w = sample_w

    def detect(self, frame_bgr):
        h, w = frame_bgr.shape[:2]
        sw = self.sample_w
        sh = max(1, int(h * sw / w))
        small = cv2.resize(frame_bgr, (sw, sh), interpolation=cv2.INTER_AREA)
        z = small.reshape(-1, 3).astype(np.float32)
        crit = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 8, 1.0)
        _, labels, centers = cv2.kmeans(z, self.k, None, crit, 2,
                                          cv2.KMEANS_RANDOM_CENTERS)
        labels = labels.reshape(sh, sw)
        # find which cluster is the largest (= background) and exclude
        counts = np.bincount(labels.flatten(), minlength=self.k)
        bg = int(np.argmax(counts))
        full_mask = np.zeros((h, w), dtype=np.uint8)
        labels_full = cv2.resize(labels.astype(np.uint8), (w, h),
                                  interpolation=cv2.INTER_NEAREST)
        for i in range(self.k):
            if i == bg:
                continue
            cluster_mask = (labels_full == i).astype(np.uint8) * 255
            full_mask = cv2.bitwise_or(full_mask, cluster_mask)
        full_mask = self._morph_clean(full_mask, ksize=9)
        return self._contours_to_blobs(full_mask), full_mask


# ============================================================
# 7. simple-blob — cv2.SimpleBlobDetector
# ============================================================

class SimpleBlobDetector(BaseDetector):
    """OpenCV's SimpleBlobDetector — multi-scale Laplacian-of-Gaussian
    keypoint detector. Each keypoint becomes a square bbox of side
    `keypoint.size`. Good for distinct circular spots."""
    name = "simple-blob"

    def __init__(self, *,
                 min_threshold: float = 30,
                 max_threshold: float = 220,
                 min_circularity: float = 0.0,
                 min_inertia: float = 0.0,
                 min_convexity: float = 0.0,
                 **kw):
        super().__init__(**kw)
        params = cv2.SimpleBlobDetector_Params()
        params.minThreshold = float(min_threshold)
        params.maxThreshold = float(max_threshold)
        params.filterByArea = True
        params.minArea = float(self.min_area / 4.0)  # SimpleBlob uses pixels
        params.maxArea = float(self.max_area / 4.0)
        # OpenCV's validator rejects min<=0 even when the corresponding
        # filterBy flag is False — only override when user enables filtering.
        if min_circularity > 0:
            params.filterByCircularity = True
            params.minCircularity = float(min_circularity)
        else:
            params.filterByCircularity = False
        if min_inertia > 0:
            params.filterByInertia = True
            params.minInertiaRatio = float(min_inertia)
        else:
            params.filterByInertia = False
        if min_convexity > 0:
            params.filterByConvexity = True
            params.minConvexity = float(min_convexity)
        else:
            params.filterByConvexity = False
        self._det = cv2.SimpleBlobDetector_create(params)

    def detect(self, frame_bgr):
        gray = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY)
        kps = self._det.detect(gray)
        h, w = gray.shape
        mask = np.zeros((h, w), dtype=np.uint8)
        blobs: list[Blob] = []
        for k in kps:
            r = max(4, int(k.size / 2))
            cx, cy = int(k.pt[0]), int(k.pt[1])
            x = max(0, cx - r); y = max(0, cy - r)
            bw = min(w - x, r * 2); bh = min(h - y, r * 2)
            cv2.circle(mask, (cx, cy), r, 255, -1)
            blobs.append(Blob(x, y, bw, bh, float(k.response or k.size), -1))
        blobs.sort(key=lambda b: b.score, reverse=True)
        return blobs[: self.max_n], mask


# ============================================================
# 8. dog — Difference-of-Gaussians multi-scale
# ============================================================

class DoGDetector(BaseDetector):
    """Difference of Gaussians at two sigmas, threshold the response, take
    connected components. The astronomy / spot-detector classic."""
    name = "dog"

    def __init__(self, *,
                 sigma_low: float = 1.5,
                 sigma_high: float = 6.0,
                 thresh: float = 7.0,
                 **kw):
        super().__init__(**kw)
        self.sigma_low = sigma_low
        self.sigma_high = sigma_high
        self.thresh = thresh

    def detect(self, frame_bgr):
        gray = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY).astype(np.float32)
        g1 = cv2.GaussianBlur(gray, (0, 0), sigmaX=self.sigma_low)
        g2 = cv2.GaussianBlur(gray, (0, 0), sigmaX=self.sigma_high)
        dog = g1 - g2
        mask = (dog > self.thresh).astype(np.uint8) * 255
        mask = self._morph_clean(mask, ksize=5)
        return self._contours_to_blobs(mask), mask


# ============================================================
# 9. circles — Hough circle transform
# ============================================================

class HoughCirclesDetector(BaseDetector):
    """Hough circle transform. Returns square bboxes around each circle.
    Mask is filled circles."""
    name = "circles"

    def __init__(self, *,
                 dp: float = 1.2,
                 min_dist: int = 40,
                 param1: float = 100,
                 param2: float = 30,
                 min_radius: int = 10,
                 max_radius: int = 120,
                 **kw):
        super().__init__(**kw)
        self.dp = dp
        self.min_dist = min_dist
        self.param1 = param1
        self.param2 = param2
        self.min_radius = min_radius
        self.max_radius = max_radius

    def detect(self, frame_bgr):
        gray = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY)
        gray = cv2.medianBlur(gray, 5)
        h, w = gray.shape
        mask = np.zeros((h, w), dtype=np.uint8)
        circles = cv2.HoughCircles(
            gray, cv2.HOUGH_GRADIENT, dp=self.dp, minDist=self.min_dist,
            param1=self.param1, param2=self.param2,
            minRadius=self.min_radius, maxRadius=self.max_radius,
        )
        blobs: list[Blob] = []
        if circles is not None:
            for (cx, cy, r) in np.round(circles[0]).astype(int):
                x = max(0, cx - r); y = max(0, cy - r)
                bw = min(w - x, r * 2); bh = min(h - y, r * 2)
                cv2.circle(mask, (cx, cy), r, 255, -1)
                blobs.append(Blob(x, y, bw, bh, float(r * r * np.pi), -1))
        blobs.sort(key=lambda b: b.score, reverse=True)
        return blobs[: self.max_n], mask


# ============================================================
# 10/11. saliency — fine-grained / spectral residual (contrib)
# ============================================================

class SaliencyFineDetector(BaseDetector):
    """`cv2.saliency.StaticSaliencyFineGrained` — spatially-detailed
    salience map. Blobs = thresholded high-salience regions. Requires
    opencv-contrib-python."""
    name = "saliency-fine"
    needs_contrib = True

    def __init__(self, *, thresh: float = 0.55, **kw):
        super().__init__(**kw)
        if not hasattr(cv2, "saliency"):
            raise RuntimeError(
                "saliency-fine requires opencv-contrib-python. "
                "pip install opencv-contrib-python")
        self._sal = cv2.saliency.StaticSaliencyFineGrained_create()
        self.thresh = thresh

    def detect(self, frame_bgr):
        ok, sal = self._sal.computeSaliency(frame_bgr)
        if not ok:
            return [], np.zeros(frame_bgr.shape[:2], dtype=np.uint8)
        mask = (sal > self.thresh).astype(np.uint8) * 255
        mask = self._morph_clean(mask, ksize=9)
        return self._contours_to_blobs(mask), mask


class SaliencySpectralDetector(BaseDetector):
    """Spectral-residual saliency — frequency-domain "what's unusual"
    detection. Often picks up edges / boundaries the fine-grained model
    misses. Requires opencv-contrib-python."""
    name = "saliency-spec"
    needs_contrib = True

    def __init__(self, *, thresh: float = 0.4, **kw):
        super().__init__(**kw)
        if not hasattr(cv2, "saliency"):
            raise RuntimeError("saliency-spec requires opencv-contrib-python")
        self._sal = cv2.saliency.StaticSaliencySpectralResidual_create()
        self.thresh = thresh

    def detect(self, frame_bgr):
        ok, sal = self._sal.computeSaliency(frame_bgr)
        if not ok:
            return [], np.zeros(frame_bgr.shape[:2], dtype=np.uint8)
        # spectral residual outputs a small map; resize to frame
        sal = cv2.resize(sal, (frame_bgr.shape[1], frame_bgr.shape[0]))
        mask = (sal > self.thresh).astype(np.uint8) * 255
        mask = self._morph_clean(mask, ksize=9)
        return self._contours_to_blobs(mask), mask


# ============================================================
# 12. csrt — multi-target CSRT trackers (contrib)
# ============================================================

class CSRTDetector(BaseDetector):
    """Multi-target CSRT trackers. Seeds new trackers from a motion-diff
    detection, then carries them forward across frames with stable IDs.
    Re-seeds every `reseed_every` frames so tracks are refreshed.

    Requires opencv-contrib-python (cv2.legacy.TrackerCSRT_create or
    cv2.TrackerCSRT_create)."""
    name = "csrt"
    needs_contrib = True

    def __init__(self, *,
                 reseed_every: int = 30,
                 max_targets: int = 6,
                 **kw):
        super().__init__(**kw)
        self.reseed_every = reseed_every
        self.max_targets = max_targets
        self._frame_count = 0
        self._next_id = 0
        self._trackers: list[tuple[int, object]] = []   # (id, tracker)
        self._last_boxes: list[tuple[int, tuple[int, int, int, int]]] = []
        self._seeder = MotionDiffDetector(min_area=self.min_area,
                                            max_area=self.max_area,
                                            max_n=self.max_targets)
        # CSRT creator, with version-tolerant fallback
        creator = (getattr(getattr(cv2, "legacy", None), "TrackerCSRT_create", None)
                   or getattr(cv2, "TrackerCSRT_create", None))
        if creator is None:
            raise RuntimeError("CSRT tracker not available — install opencv-contrib-python")
        self._make_tracker = creator

    def _seed(self, frame_bgr):
        seeds, _ = self._seeder(frame_bgr)
        self._trackers = []
        for b in seeds[: self.max_targets]:
            try:
                tr = self._make_tracker()
                tr.init(frame_bgr, (int(b.x), int(b.y), int(b.w), int(b.h)))
                self._trackers.append((self._next_id, tr))
                self._next_id += 1
            except Exception:
                continue

    def detect(self, frame_bgr):
        if self._frame_count % self.reseed_every == 0:
            self._seed(frame_bgr)
        self._frame_count += 1
        h, w = frame_bgr.shape[:2]
        mask = np.zeros((h, w), dtype=np.uint8)
        blobs: list[Blob] = []
        keep: list[tuple[int, object]] = []
        for tid, tr in self._trackers:
            ok, box = tr.update(frame_bgr)
            if not ok:
                continue
            x, y, bw, bh = (int(v) for v in box)
            x = max(0, x); y = max(0, y)
            bw = min(w - x, bw); bh = min(h - y, bh)
            if bw < 4 or bh < 4:
                continue
            cv2.rectangle(mask, (x, y), (x + bw, y + bh), 255, -1)
            blobs.append(Blob(x, y, bw, bh, float(bw * bh), tid))
            keep.append((tid, tr))
        self._trackers = keep
        return blobs, mask


# ============================================================
# 13. edge — Canny + connected components
# ============================================================

class EdgeDetector(BaseDetector):
    """Canny edges, dilated and closed, then connected-components on the
    resulting line-art layer. Blobs become contour-bounded regions of
    the edge map. Good for ink-line / outline-driven aesthetics."""
    name = "edge"

    def __init__(self, *,
                 canny_low: int = 60,
                 canny_high: int = 160,
                 dilate_iter: int = 2,
                 **kw):
        super().__init__(**kw)
        self.canny_low = canny_low
        self.canny_high = canny_high
        self.dilate_iter = dilate_iter

    def detect(self, frame_bgr):
        gray = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY)
        edges = cv2.Canny(gray, self.canny_low, self.canny_high)
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
        edges = cv2.dilate(edges, kernel, iterations=self.dilate_iter)
        edges = cv2.morphologyEx(edges, cv2.MORPH_CLOSE, kernel, iterations=2)
        return self._contours_to_blobs(edges), edges


# ============================================================
# 14. accumulation — exponentially-weighted motion accumulation
# ============================================================

class AccumulationDetector(BaseDetector):
    """`cv2.accumulateWeighted` builds a slow-decaying running average of
    motion. Threshold of the accumulated diff gives masks where motion has
    been LATELY, not just instantaneously. Slow lingering trails."""
    name = "accumulation"

    def __init__(self, *,
                 alpha: float = 0.10,
                 thresh: int = 18,
                 **kw):
        super().__init__(**kw)
        self.alpha = alpha
        self.thresh = thresh
        self._accum: Optional[np.ndarray] = None

    def detect(self, frame_bgr):
        gray = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY).astype(np.float32)
        if self._accum is None:
            self._accum = gray.copy()
        cv2.accumulateWeighted(gray, self._accum, self.alpha)
        diff = cv2.absdiff(gray, self._accum)
        mask = (diff > self.thresh).astype(np.uint8) * 255
        mask = self._morph_clean(mask, ksize=9)
        return self._contours_to_blobs(mask), mask


# ============================================================
# 15. watershed — marker-based segmentation
# ============================================================

class WatershedDetector(BaseDetector):
    """Threshold + distance transform + marker-based watershed. Splits
    touching foreground regions cleanly. Works on roughly bimodal frames."""
    name = "watershed"

    def __init__(self, *,
                 luma_thresh: int = 80,
                 dist_thresh_frac: float = 0.45,
                 **kw):
        super().__init__(**kw)
        self.luma_thresh = luma_thresh
        self.dist_thresh_frac = dist_thresh_frac

    def detect(self, frame_bgr):
        gray = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY)
        _, fg = cv2.threshold(gray, self.luma_thresh, 255, cv2.THRESH_BINARY)
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
        fg = cv2.morphologyEx(fg, cv2.MORPH_OPEN, kernel, iterations=2)
        sure_bg = cv2.dilate(fg, kernel, iterations=3)
        dist = cv2.distanceTransform(fg, cv2.DIST_L2, 5)
        if dist.max() < 1.0:
            return [], np.zeros_like(gray)
        _, sure_fg = cv2.threshold(dist, self.dist_thresh_frac * dist.max(),
                                    255, 0)
        sure_fg = sure_fg.astype(np.uint8)
        unknown = cv2.subtract(sure_bg, sure_fg)
        n_markers, markers = cv2.connectedComponents(sure_fg)
        markers = markers + 1
        markers[unknown == 255] = 0
        markers = cv2.watershed(frame_bgr, markers)
        # build a mask from regions, ignore boundary (-1) and bg (1)
        mask = np.zeros(gray.shape, dtype=np.uint8)
        mask[markers > 1] = 255
        return self._contours_to_blobs(mask), mask


# ============================================================
# 16. contour-area — pure luma threshold
# ============================================================

class ContourAreaDetector(BaseDetector):
    """Plain Otsu / fixed-luma threshold + connected components. No motion
    needed — ideal for static high-contrast frames (X-rays, silhouettes,
    illustrations)."""
    name = "contour-area"

    def __init__(self, *,
                 thresh: int = 0,
                 invert: bool = False,
                 use_otsu: bool = True,
                 **kw):
        super().__init__(**kw)
        self.thresh = thresh
        self.invert = invert
        self.use_otsu = use_otsu

    def detect(self, frame_bgr):
        gray = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY)
        flag = cv2.THRESH_BINARY_INV if self.invert else cv2.THRESH_BINARY
        if self.use_otsu:
            flag |= cv2.THRESH_OTSU
        _, mask = cv2.threshold(gray, self.thresh, 255, flag)
        mask = self._morph_clean(mask, ksize=7)
        return self._contours_to_blobs(mask), mask


# ============================================================
# Registry
# ============================================================

REGISTRY: dict[str, type[BaseDetector]] = {
    cls.name: cls
    for cls in (
        MotionDiffDetector,
        MOG2Detector,
        KNNDetector,
        OpticalFlowDetector,
        ColorHSVDetector,
        ColorClusterDetector,
        SimpleBlobDetector,
        DoGDetector,
        HoughCirclesDetector,
        SaliencyFineDetector,
        SaliencySpectralDetector,
        CSRTDetector,
        EdgeDetector,
        AccumulationDetector,
        WatershedDetector,
        ContourAreaDetector,
    )
}


def get_detector(name: str, **params) -> BaseDetector:
    if name not in REGISTRY:
        raise SystemExit(
            f"unknown detector '{name}'. Available: {sorted(REGISTRY)}")
    cls = REGISTRY[name]
    if cls.needs_contrib and not _has_contrib():
        print(f"WARNING: '{name}' needs opencv-contrib-python — install with "
              f"`pip install opencv-contrib-python` (instead of opencv-python)",
              file=sys.stderr)
    return cls(**params)


def _has_contrib() -> bool:
    return hasattr(cv2, "saliency") or hasattr(cv2, "legacy")


def list_detectors() -> list[str]:
    return list(REGISTRY)


# ============================================================
# Cross-frame ID assignment (for detectors that don't carry IDs)
# ============================================================

class IDTracker:
    """Cheap nearest-centroid ID assignment across frames. Use this to
    decorate stateless detectors (motion-diff, mog2, etc.) with stable
    blob IDs that visualizers can key off of."""

    def __init__(self, *, max_match_dist: int = 80):
        self.max_d = max_match_dist
        self._tracks: dict[int, tuple[int, int]] = {}
        self._next_id = 0

    def assign(self, blobs: list[Blob]) -> list[Blob]:
        used = set()
        new_tracks: dict[int, tuple[int, int]] = {}
        out: list[Blob] = []
        for b in blobs:
            if b.id >= 0:
                # already has an ID (e.g. CSRT) — keep it
                new_tracks[b.id] = (b.x + b.w // 2, b.y + b.h // 2)
                out.append(b)
                continue
            cx, cy = b.x + b.w // 2, b.y + b.h // 2
            best_id, best_d = -1, self.max_d ** 2
            for tid, (px, py) in self._tracks.items():
                if tid in used:
                    continue
                d = (cx - px) ** 2 + (cy - py) ** 2
                if d < best_d:
                    best_d, best_id = d, tid
            if best_id < 0:
                best_id = self._next_id; self._next_id += 1
            used.add(best_id)
            new_tracks[best_id] = (cx, cy)
            out.append(Blob(b.x, b.y, b.w, b.h, b.score, best_id))
        self._tracks = new_tracks
        return out


# ============================================================
# CLI smoke test
# ============================================================

def _cli():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True, help="video to scan")
    ap.add_argument("--detector", default="motion-diff",
                    choices=list_detectors())
    ap.add_argument("--frames", type=int, default=120)
    args = ap.parse_args()

    cap = cv2.VideoCapture(args.input)
    det = get_detector(args.detector)
    tr = IDTracker()
    print(f"running {args.detector} for {args.frames} frames…")
    for f in range(args.frames):
        ok, fr = cap.read()
        if not ok:
            break
        blobs, mask = det(fr)
        blobs = tr.assign(blobs)
        if f % 10 == 0:
            print(f"  frame {f:04d}  blobs={len(blobs):2d}  "
                  f"max_score={max((b.score for b in blobs), default=0):.0f}")
    cap.release()


if __name__ == "__main__":
    _cli()
