"""
render.py — single entry point for the blob-tracker skill.

Composes: video source → audio source → detector → viz chain →
(optional) postfx chain → encoded mp4.

Inputs are independent; any combination is valid:

    # 1. Pure: existing video, no audio
    python render.py --video clip.mp4 --output out.mp4

    # 2. Existing video + existing audio (audio-reactive)
    python render.py --video clip.mp4 --audio track.wav --output out.mp4

    # 3. Existing video + compose music
    python render.py --video clip.mp4 --compose-music \
                     --music-brief "ambient warm pad" --output out.mp4

    # 4. Find video + bring your own audio
    python render.py --find-video "lunar surface NASA" --audio track.wav \
                     --output out.mp4

    # 5. Full auto from brief: search video, compose music, render
    python render.py --brief "1920s botanical, dreamy ambient" \
                     --auto-flavor --output out.mp4

Detector / viz / postfx are pluggable:

    --detector mog2
    --viz centroid-trail,network,corner-ticks
    --postfx rgb-shift,scanlines

`--auto-flavor` asks Kimi-vision to pick detector + viz from a thumbnail
of the source video, optionally biased by `--brief`.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import numpy as np
import cv2

import detectors
import visualizers
import postfx
import audio_features


# ============================================================
# helpers
# ============================================================

def _slugify(text):
    s = re.sub(r"[^a-zA-Z0-9]+", "-", text.lower()).strip("-")
    return s[:40] or "piece"


def _check_ffmpeg():
    if shutil.which("ffmpeg") is None:
        sys.exit("ffmpeg not found on PATH — install with `brew install ffmpeg`")


def _square_crop_resize(src_path, out_path, size, duration, fps):
    """Trim, square-crop centre, scale to NxN, fps fixed, drop audio."""
    vf = (f"crop='min(iw,ih)':'min(iw,ih)':"
          f"(iw-min(iw\\,ih))/2:(ih-min(iw\\,ih))/2,"
          f"scale={size}:{size}:flags=lanczos,fps={fps}")
    cmd = ["ffmpeg", "-y", "-i", str(src_path),
           "-t", str(duration), "-vf", vf,
           "-c:v", "libx264", "-crf", "18", "-pix_fmt", "yuv420p",
           "-an", str(out_path)]
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        sys.exit("ffmpeg square-crop failed:\n" + res.stderr[-2000:])


def _layout_for(name):
    if name == "vertical":
        return dict(W=1080, H=1920, src_xy=(0, 420))
    if name == "horizontal":
        return dict(W=1920, H=1080, src_xy=(420, 0))
    return dict(W=None, H=None, src_xy=(0, 0))   # square = no padding


# ============================================================
# stage 1: resolve video source
# ============================================================

def resolve_video(args, out_dir, work_dir):
    """Returns Path to a square `size x size` mp4 ready to render."""
    size = args.size
    target = work_dir / "source.mp4"

    if args.video:
        src = Path(args.video)
        if not src.exists():
            sys.exit(f"--video not found: {src}")
        print(f"[video] using {src}")
        _square_crop_resize(src, target, size, args.duration, args.fps)
        return target

    # need to find one — call video_search
    if args.find_video or args.brief:
        import video_search
        winner = None
        if args.find_video:
            print(f"[video] searching IA for: {args.find_video!r}")
            winner = video_search.find_video(
                query=args.find_video, kimi_pick_enabled=False)
        else:
            print(f"[video] searching IA from brief: {args.brief!r}")
            winner = video_search.find_video(
                brief=args.brief, kimi_pick_enabled=True)
        (out_dir / "winner.json").write_text(json.dumps(winner, indent=2))
        print(f"[video] picked: {winner['identifier']} — {winner['title']}")
        # download via prepare_source
        import prepare_source
        if args.cache_dir:
            cache = Path(args.cache_dir); cache.mkdir(parents=True, exist_ok=True)
            dl_path = cache / f"{winner['identifier']}.mp4"
            if not dl_path.exists():
                prepare_source.download(winner["url"], dl_path)
        else:
            tmp_dir = Path(tempfile.mkdtemp(prefix="bt_src_"))
            dl_path = tmp_dir / f"{winner['identifier']}.mp4"
            prepare_source.download(winner["url"], dl_path)
        total = prepare_source.probe_duration(dl_path)
        if total <= args.duration:
            t_start = 0.0
        else:
            scores = prepare_source.scout_energy(dl_path, total)
            t_start = prepare_source.best_window(scores, args.duration, 1.0)
            print(f"[video] best window starts t={t_start:.1f}s")
        prepare_source.encode(dl_path, t_start, args.duration, size, target)
        return target

    sys.exit("need a video source: --video, --find-video, or --brief")


# ============================================================
# stage 2: resolve audio source
# ============================================================

def resolve_audio(args, out_dir, work_dir):
    """Returns Path to a .wav matching --duration, OR None if silent."""
    if args.audio:
        src = Path(args.audio)
        if not src.exists():
            sys.exit(f"--audio not found: {src}")
        print(f"[audio] using {src}")
        # If it's not a wav, transcode for librosa speed
        if src.suffix.lower() != ".wav":
            target = work_dir / "audio.wav"
            cmd = ["ffmpeg", "-y", "-i", str(src), "-t", str(args.duration),
                   "-ar", "44100", "-ac", "2", str(target)]
            res = subprocess.run(cmd, capture_output=True, text=True)
            if res.returncode != 0:
                sys.exit("ffmpeg audio transcode failed:\n"
                         + res.stderr[-2000:])
            return target
        return src

    if args.compose_music:
        target = work_dir / "audio.wav"
        spec_path = out_dir / "audio.json"
        # If user passed --music-spec, use as-is; else Kimi-derive from brief.
        import compose_music
        if args.music_spec:
            spec = json.loads(Path(args.music_spec).read_text())
        else:
            brief = args.music_brief or args.brief or "warm contemplative ambient"
            print(f"[audio] composing music from brief: {brief!r}")
            spec = compose_music.kimi_spec(brief)
        spec.setdefault("key", "Eb"); spec.setdefault("mode", "major")
        spec.setdefault("bpm", 58)
        spec.setdefault("progression", "I-vi-IV-V")
        spec.setdefault("mood", "warm contemplative")
        print(f"[audio] music spec: {spec}")
        spec_path.write_text(json.dumps(spec, indent=2))
        compose_music.render(spec, args.duration, target)
        return target

    print("[audio] no audio — running silent (visualizers receive zero-amp)")
    return None


# ============================================================
# stage 3: auto-flavor (optional Kimi vision pick)
# ============================================================

AUTO_FLAVOR_SYSTEM = """You are picking blob-tracking parameters for a
26-second media-art short. You'll see one frame from the source video and
optionally a creative brief.

Choose ONE detector and 2–4 visualizers from the available lists:

DETECTORS (pick one):
  motion-diff    — frame-differencing. Cheap, works on most footage.
  mog2           — background subtraction. Good for static-camera lighting changes.
  knn            — alt background subtractor. Cleaner on noisy footage.
  flow           — optical flow. Smooth motion; pans, drifts.
  color-hsv      — HSV range. Track a single colour.
  simple-blob    — LoG keypoints. Distinct circular spots.
  dog            — Difference of Gaussians. Astronomy / micro / spots.
  circles        — Hough circles. Round things only.
  saliency-fine  — what's interesting. No motion needed.
  saliency-spec  — frequency-domain salience. Good for boundaries.
  csrt           — multi-target persistent ID trackers.
  edge           — Canny + components. Outline-driven.
  accumulation   — slow lingering motion trails.
  watershed      — segmentation, splits touching regions.
  contour-area   — pure luma threshold. Static high-contrast.

VISUALIZERS (pick 2-4 to combine):
  bbox             plain rectangles
  corner-ticks     L-bracket corners + IDs (the original HUD)
  crosshair        cross + ID at centroid
  centroid-trail   long colour-coded ink trail per ID
  network          lines between nearby blob centres
  letters          ASCII letters along blob velocity
  glyphs           Unicode shape constellation
  cctv-zoom        corner inset of largest blob
  silhouette       hue-cycling fill on blob mask
  outline          contour line on blob mask
  voronoi          voronoi cells from centres
  convex-hull      hull polygon enclosing all centres
  heatmap          accumulated occupancy overlay
  spatial-echo     blob bbox shows pixels from ELSEWHERE in frame

Return STRICT JSON: {"detector": "<name>", "viz": ["v1","v2",...],
  "reason": "<one short sentence>"}"""


def auto_flavor(source_video, brief, out_dir):
    """Sample a frame from the source, ask Kimi to pick detector + viz."""
    import kimi_client
    cap = cv2.VideoCapture(str(source_video))
    n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    cap.set(cv2.CAP_PROP_POS_FRAMES, n // 3)
    ok, fr = cap.read()
    cap.release()
    if not ok:
        sys.exit("auto-flavor: failed to read sample frame")
    thumb = out_dir / "auto_flavor_thumb.jpg"
    cv2.imwrite(str(thumb), fr, [cv2.IMWRITE_JPEG_QUALITY, 88])
    prompt = AUTO_FLAVOR_SYSTEM
    if brief:
        prompt += f"\n\nBRIEF: {brief}"
    raw = kimi_client.vision_pick(prompt, [thumb], temperature=0.3,
                                   max_tokens=300)
    s = raw.find("{"); e = raw.rfind("}")
    if s < 0 or e <= s:
        print(f"[auto-flavor] Kimi returned non-JSON, defaulting:\n  {raw[:200]}",
              file=sys.stderr)
        return "motion-diff", ["centroid-trail", "network", "corner-ticks"], "fallback"
    obj = json.loads(raw[s:e + 1])
    det = obj.get("detector", "motion-diff")
    viz = obj.get("viz", ["corner-ticks"])
    reason = obj.get("reason", "")
    print(f"[auto-flavor] detector={det}  viz={viz}")
    print(f"[auto-flavor] reason: {reason}")
    return det, viz, reason


# ============================================================
# stage 4: render + encode (streaming)
# ============================================================

def _scale_blobs(blobs, scale: float):
    """Multiply blob coords/sizes by `scale`, returning new namedtuples."""
    if scale == 1.0:
        return blobs
    out = []
    for b in blobs:
        out.append(detectors.Blob(
            int(round(b.x * scale)), int(round(b.y * scale)),
            int(round(b.w * scale)), int(round(b.h * scale)),
            b.score, b.id))
    return out


def _open_ffmpeg_writer(out_path: Path, *, w: int, h: int, fps: int,
                        audio_path):
    """Spawn ffmpeg reading raw BGR24 frames on stdin, encoding to `out_path`.
    Returns the Popen handle."""
    if out_path.exists():
        out_path.unlink()
    cmd = ["ffmpeg", "-y", "-loglevel", "error",
           "-f", "rawvideo", "-pix_fmt", "bgr24",
           "-s", f"{w}x{h}", "-r", str(fps),
           "-i", "-"]
    if audio_path is not None:
        cmd += ["-i", str(audio_path)]
    cmd += ["-c:v", "libx264", "-crf", "18", "-pix_fmt", "yuv420p"]
    if audio_path is not None:
        cmd += ["-c:a", "aac", "-b:a", "192k", "-shortest"]
    cmd += [str(out_path)]
    return subprocess.Popen(cmd, stdin=subprocess.PIPE)


def render_and_encode(source_video, audio_path, out_path, *,
                       detector_name, detector_params,
                       viz_names, viz_params,
                       postfx_names, postfx_params,
                       fps, duration, label, layout_name,
                       src_size, detect_scale: float = 1.0):
    """Render every frame and pipe BGR bytes straight into ffmpeg's stdin —
    no PNG round-trip. Single-pass."""
    layout = _layout_for(layout_name)
    if layout["W"] is None:
        layout["W"] = src_size; layout["H"] = src_size
    n_frames = int(duration * fps)

    # audio features
    if audio_path is not None:
        feats = audio_features.compute_features(audio_path, fps=fps,
                                                 n_frames=n_frames)
    else:
        feats = audio_features.silence_features(n_frames)

    # detector + tracker + viz + postfx chains
    det = detectors.get_detector(detector_name, **detector_params)
    tracker = detectors.IDTracker(max_match_dist=80)
    viz_chain = visualizers.build_chain(",".join(viz_names), viz_params)
    fx_chain = postfx.build_chain(",".join(postfx_names) if postfx_names else "",
                                    postfx_params)

    # cache source frames into memory once
    cap = cv2.VideoCapture(str(source_video))
    n_src = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    src_fps = cap.get(cv2.CAP_PROP_FPS) or fps
    print(f"[render] source: {n_src} frames @ {src_fps:.1f} fps; "
          f"target: {n_frames} frames @ {fps} fps; "
          f"layout={layout_name} {layout['W']}x{layout['H']}; "
          f"detect_scale={detect_scale}")
    print(f"[render] detector={detector_name}  viz={viz_names}  "
          f"postfx={postfx_names or '[]'}")
    frames = []
    for _ in range(n_src):
        ok, fr = cap.read()
        if not ok or fr is None:
            break
        if fr.shape[0] != src_size or fr.shape[1] != src_size:
            fr = cv2.resize(fr, (src_size, src_size),
                            interpolation=cv2.INTER_AREA)
        frames.append(fr)
    cap.release()
    if not frames:
        sys.exit("[render] source video produced no frames")
    n_src = len(frames)

    # detect-scale buffer: precompute downsampled frames if requested
    if detect_scale != 1.0:
        ds_size = max(64, int(round(src_size * detect_scale)))
        ds_frames = [cv2.resize(f, (ds_size, ds_size),
                                 interpolation=cv2.INTER_AREA)
                      for f in frames]
        coord_back = src_size / ds_size
    else:
        ds_frames = frames
        coord_back = 1.0

    # set up viz state at full canvas size
    for v in viz_chain:
        v.setup(src_size, src_size)
    for fx in fx_chain:
        fx.setup(src_size, src_size)

    # open ffmpeg pipe
    out_w, out_h = layout["W"], layout["H"]
    writer = _open_ffmpeg_writer(out_path, w=out_w, h=out_h, fps=fps,
                                  audio_path=audio_path)

    # render loop
    t0 = time.time()
    for f in range(n_frames):
        t = f / fps
        s_idx = int((f / max(1, n_frames - 1)) * (n_src - 1))
        pane = frames[s_idx].copy()

        # detection (possibly at lower resolution)
        blobs, mask = det(ds_frames[s_idx])
        if detect_scale != 1.0:
            blobs = _scale_blobs(blobs, coord_back)
            mask = cv2.resize(mask, (src_size, src_size),
                              interpolation=cv2.INTER_NEAREST)
        blobs = tracker.assign(blobs)
        a = audio_features.slice_at(feats, f)

        for v in viz_chain:
            pane = v(pane, blobs, mask, t=t, audio=a)
        for fx in fx_chain:
            pane = fx(pane, blobs, mask, t=t, audio=a)

        # compose into final canvas
        if out_w == src_size and out_h == src_size:
            canvas = pane
        else:
            canvas = np.zeros((out_h, out_w, 3), dtype=np.uint8)
            sx, sy = layout["src_xy"]
            canvas[sy:sy + src_size, sx:sx + src_size] = pane

        # ensure C-contiguous before pushing bytes
        if not canvas.flags["C_CONTIGUOUS"]:
            canvas = np.ascontiguousarray(canvas)
        try:
            writer.stdin.write(canvas.tobytes())
        except BrokenPipeError:
            sys.exit("[render] ffmpeg pipe broke — check ffmpeg stderr")

        if (f + 1) % 30 == 0 or f == n_frames - 1:
            dt = time.time() - t0
            fps_eff = (f + 1) / dt if dt > 0 else 0
            eta = (n_frames - f - 1) / fps_eff if fps_eff > 0 else 0
            print(f"  frame {f+1}/{n_frames}  blobs={len(blobs):2d}  "
                  f"{fps_eff:.1f}fps  eta={eta:.0f}s",
                  flush=True)

    writer.stdin.close()
    rc = writer.wait()
    if rc != 0:
        sys.exit(f"ffmpeg encode failed (exit {rc})")
    sz_mb = out_path.stat().st_size // (1024 * 1024)
    print(f"[{label}] DONE → {out_path}  ({sz_mb}MB)")


# ============================================================
# main
# ============================================================

def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                  formatter_class=argparse.RawDescriptionHelpFormatter)
    # video source
    ap.add_argument("--video", default=None,
                    help="path to existing video file")
    ap.add_argument("--find-video", default=None,
                    help="IA query string (no Kimi expansion)")
    ap.add_argument("--brief", default=None,
                    help="creative brief — Kimi expands to IA queries + vision pick")
    # audio source
    ap.add_argument("--audio", default=None,
                    help="path to existing audio file (.wav/.mp3/.m4a)")
    ap.add_argument("--compose-music", action="store_true",
                    help="synthesise an ambient soundtrack")
    ap.add_argument("--music-brief", default=None,
                    help="brief for compose_music (defaults to --brief)")
    ap.add_argument("--music-spec", default=None,
                    help="JSON path with music spec (bypasses Kimi)")
    # detector / viz
    ap.add_argument("--detector", default="motion-diff",
                    choices=detectors.list_detectors(),
                    help="blob detector flavor (default: motion-diff)")
    ap.add_argument("--detector-params", default="{}",
                    help="JSON dict of extra params for the detector")
    ap.add_argument("--viz", default="centroid-trail,network,corner-ticks",
                    help="comma-separated visualizers (default: "
                         "centroid-trail,network,corner-ticks)")
    ap.add_argument("--viz-params", default="{}",
                    help="JSON: {viz_name: {param: value}}")
    ap.add_argument("--postfx", default="",
                    help="comma-separated postfx primitives (default: empty)")
    ap.add_argument("--postfx-params", default="{}",
                    help="JSON: {fx_name: {param: value}}")
    ap.add_argument("--auto-flavor", action="store_true",
                    help="ask Kimi-vision to pick detector + viz")
    # render
    ap.add_argument("--output", default=None,
                    help="final mp4 path (default: <out-dir>/<slug>.mp4)")
    ap.add_argument("--duration", type=float, default=26.0)
    ap.add_argument("--fps", type=int, default=30)
    ap.add_argument("--size", type=int, default=1080,
                    help="square crop size (px)")
    ap.add_argument("--dual-format", action="store_true",
                    help="also export 1920x1080 + 1080x1920 letterboxed")
    ap.add_argument("--slug", default=None,
                    help="run name (default auto-generated)")
    ap.add_argument("--out-dir", default=os.environ.get(
        "BLOB_OUT_DIR", str(Path.home() / "blob-tracker")),
        help="workspace root for intermediate files")
    ap.add_argument("--cache-dir", default=None,
                    help="cache IA downloads between runs")
    ap.add_argument("--keep-intermediate", action="store_true",
                    help="keep the .src_cache_* dirs")
    # performance
    ap.add_argument("--detect-scale", type=float, default=1.0,
                    help="run detection at this fraction of source size "
                         "(0.5 = ~4x faster detection at cost of slightly "
                         "less precise blob bboxes)")
    ap.add_argument("--quick", action="store_true",
                    help="fast iteration preset: 480 px square, 8 s, "
                         "detect-scale 1.0 — overrides --size, --duration, "
                         "and --detect-scale unless they were given explicitly")
    args = ap.parse_args()
    if args.quick:
        # only override defaults — respect explicit user values
        if "--size" not in sys.argv:
            args.size = 480
        if "--duration" not in sys.argv:
            args.duration = 8.0

    _check_ffmpeg()

    slug = args.slug or _slugify(args.brief or args.find_video
                                  or (args.video and Path(args.video).stem)
                                  or "blob-track")
    out_dir = Path(args.out_dir) / slug
    out_dir.mkdir(parents=True, exist_ok=True)
    work_dir = out_dir
    print(f"== blob-tracker: {slug} → {out_dir}")

    # 1. video
    source = resolve_video(args, out_dir, work_dir)
    # 2. audio
    audio = resolve_audio(args, out_dir, work_dir)

    # 3. parameters (auto-flavor overrides --detector / --viz)
    if args.auto_flavor:
        det_name, viz_list, _reason = auto_flavor(source, args.brief, out_dir)
        viz_spec = ",".join(viz_list)
    else:
        det_name = args.detector
        viz_spec = args.viz

    det_params = json.loads(args.detector_params or "{}")
    viz_params = json.loads(args.viz_params or "{}")
    fx_params = json.loads(args.postfx_params or "{}")
    fx_list = [s.strip() for s in args.postfx.split(",") if s.strip()]
    viz_list = [s.strip() for s in viz_spec.split(",") if s.strip()]

    # 4. render — single-pass streaming: blob loop pipes BGR frames straight
    #    into ffmpeg's stdin, no PNG intermediates.
    label = slug.upper()[:14]
    layouts = ["square"] if not args.dual_format else ["horizontal", "vertical"]
    final_paths = []
    for layout_name in layouts:
        layout = _layout_for(layout_name)
        if layout["W"] is None:
            w_out, h_out = args.size, args.size
        else:
            w_out, h_out = layout["W"], layout["H"]
        if args.dual_format:
            out_path = work_dir / f"{slug}-{w_out}x{h_out}.mp4"
        elif args.output:
            out_path = Path(args.output)
        else:
            out_path = work_dir / f"{slug}.mp4"
        render_and_encode(
            source, audio, out_path,
            detector_name=det_name, detector_params=det_params,
            viz_names=viz_list, viz_params=viz_params,
            postfx_names=fx_list, postfx_params=fx_params,
            fps=args.fps, duration=args.duration, label=label,
            layout_name=layout_name, src_size=args.size,
            detect_scale=args.detect_scale,
        )
        final_paths.append(out_path)

    print(f"\n== blob-tracker DONE: {len(final_paths)} output(s)")
    for p in final_paths:
        print(f"   {p}")


if __name__ == "__main__":
    main()
