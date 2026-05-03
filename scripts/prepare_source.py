"""
prepare_source.py — download winner.json's video, find the most visually
energetic 26-second window, square-crop, scale to target size, write
source.mp4.

Visual-energy score = mean motion magnitude + luminance variance, sampled
once per second.

Usage:
    python prepare_source.py --winner winner.json --duration 26 --size 1080 --out source.mp4
"""
import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np
import cv2
import requests


def download(url, out_path):
    print(f"  downloading {url}")
    with requests.get(url, stream=True, timeout=120) as r:
        r.raise_for_status()
        total = int(r.headers.get("content-length", 0))
        done = 0
        with open(out_path, "wb") as f:
            for chunk in r.iter_content(chunk_size=1 << 20):
                if not chunk:
                    continue
                f.write(chunk)
                done += len(chunk)
        print(f"  done: {done//(1024*1024)}MB")


def probe_duration(path):
    cmd = ["ffprobe", "-v", "error", "-show_entries", "format=duration",
           "-of", "default=nw=1:nk=1", str(path)]
    return float(subprocess.check_output(cmd, text=True).strip())


def scout_energy(path, total_sec, sample_sec=1.0):
    """Sample 1 frame per second; compute (motion + variance) score."""
    cap = cv2.VideoCapture(str(path))
    fps = cap.get(cv2.CAP_PROP_FPS) or 30
    n_samples = int(total_sec / sample_sec)
    scores = np.zeros(n_samples, dtype=np.float32)
    prev = None
    for i in range(n_samples):
        t = i * sample_sec
        cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000)
        ok, fr = cap.read()
        if not ok or fr is None:
            continue
        small = cv2.resize(fr, (160, 120), interpolation=cv2.INTER_AREA)
        gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
        var = float(np.var(gray.astype(np.float32))) / 255.0
        motion = 0.0
        if prev is not None:
            motion = float(np.mean(cv2.absdiff(gray, prev))) / 255.0
        scores[i] = var + 4.0 * motion
        prev = gray
    cap.release()
    return scores


def best_window(scores, window_sec, sample_sec):
    w = max(1, int(window_sec / sample_sec))
    if len(scores) < w:
        return 0
    sums = np.convolve(scores, np.ones(w, dtype=np.float32), mode="valid")
    return int(np.argmax(sums)) * sample_sec


def encode(src, t_start, duration, size, out):
    """ffmpeg: trim, square-crop centre, scale to NxN, drop audio, h264 crf18."""
    # Use ffmpeg's smartautocrop or compute on the fly:
    # crop=size_h:size_h:(w-h)/2:0 if landscape else (h-w)/2 etc.
    # Use a generic 'crop=ih*1:ih:(iw-ih)/2:0' for landscape sources, but films
    # may be portrait. Use min(iw,ih) as the crop dim, centred.
    vf = (f"crop='min(iw,ih)':'min(iw,ih)':(iw-min(iw\\,ih))/2:(ih-min(iw\\,ih))/2,"
          f"scale={size}:{size}:flags=lanczos,fps=30")
    cmd = ["ffmpeg", "-y", "-ss", str(t_start), "-i", str(src),
           "-t", str(duration), "-vf", vf,
           "-c:v", "libx264", "-crf", "18", "-pix_fmt", "yuv420p",
           "-an", str(out)]
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        print("ffmpeg failed:\n" + res.stderr[-2000:], file=sys.stderr)
        sys.exit(1)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--winner", required=True)
    ap.add_argument("--duration", type=float, default=26.0)
    ap.add_argument("--size", type=int, default=1080)
    ap.add_argument("--out", required=True)
    ap.add_argument("--cache-dir", default=None,
                    help="dir to cache downloaded source mp4 between runs")
    args = ap.parse_args()

    winner = json.loads(Path(args.winner).read_text())
    url = winner["url"]
    ident = winner["identifier"]

    if args.cache_dir:
        Path(args.cache_dir).mkdir(parents=True, exist_ok=True)
        dl_path = Path(args.cache_dir) / f"{ident}.mp4"
        if not dl_path.exists():
            download(url, dl_path)
    else:
        td = tempfile.mkdtemp(prefix="pv_src_")
        dl_path = Path(td) / f"{ident}.mp4"
        download(url, dl_path)

    total = probe_duration(dl_path)
    print(f"  total duration: {total:.1f}s")

    if total <= args.duration:
        t_start = 0.0
    else:
        scores = scout_energy(dl_path, total)
        t_start = best_window(scores, args.duration, 1.0)
        print(f"  best window starts at t={t_start:.1f}s (energy peak)")

    encode(dl_path, t_start, args.duration, args.size, args.out)
    print(f"  wrote {args.out}")


if __name__ == "__main__":
    main()
