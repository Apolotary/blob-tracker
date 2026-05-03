"""
pipeline.py — one-shot orchestrator. Brief in → finished mp4s out.

Stages:
  1. brief_to_queries.py
  2. ia_search.py
  3. pick_candidate.py        (Kimi vision)
  4. prepare_source.py
  5. compose_music.py         (Kimi spec → Python synth)
  6. blob_render.py × 2       (horizontal + vertical)
  7. title_and_desc.py        (Kimi text)

Usage:
    python pipeline.py --brief "<text>" [--slug <slug>] [--effects "..."]
"""
import argparse
import os
import re
import subprocess
import sys
import time
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent


def slugify(text):
    s = re.sub(r"[^a-zA-Z0-9]+", "-", text.lower()).strip("-")
    return s[:40] or "piece"


def run(cmd, env=None):
    print(f"\n$ {' '.join(cmd)}", flush=True)
    res = subprocess.run(cmd, env=env or os.environ.copy())
    if res.returncode != 0:
        print(f"step failed (exit {res.returncode})", file=sys.stderr)
        sys.exit(res.returncode)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--brief", required=True)
    ap.add_argument("--slug", default=None)
    ap.add_argument("--out-root", default=os.environ.get(
        "PV_OUT_DIR", str(Path.home() / "process-variations")))
    ap.add_argument("--duration", type=float, default=26.0)
    ap.add_argument("--effects", default=None,
                    help="effect list passed to blob_render.py")
    ap.add_argument("--cache-dir", default=None,
                    help="cache downloaded source mp4s between runs")
    args = ap.parse_args()

    if not os.environ.get("MOONSHOT_API_KEY"):
        print("MOONSHOT_API_KEY not set — required for Kimi calls", file=sys.stderr)
        sys.exit(2)

    slug = args.slug or slugify(args.brief)
    out_dir = Path(args.out_root) / slug
    out_dir.mkdir(parents=True, exist_ok=True)
    print(f"== process-variations: {slug} → {out_dir}")
    print(f"   brief: {args.brief}")

    queries     = out_dir / "queries.json"
    candidates  = out_dir / "candidates.json"
    winner      = out_dir / "winner.json"
    source_mp4  = out_dir / "source.mp4"
    audio_wav   = out_dir / "audio.wav"
    music_spec  = out_dir / "audio.json"
    metadata    = out_dir / "metadata.json"

    # 1. brief → queries
    run(["python", str(SCRIPTS / "brief_to_queries.py"),
         "--brief", args.brief, "--out", str(queries)])

    # 2. IA search
    run(["python", str(SCRIPTS / "ia_search.py"),
         "--queries", str(queries), "--out", str(candidates),
         "--max-per-query", "5"])

    # 3. Kimi vision pick
    run(["python", str(SCRIPTS / "pick_candidate.py"),
         "--candidates", str(candidates),
         "--brief", args.brief,
         "--out", str(winner)])

    # 4. prepare source
    prep_cmd = ["python", str(SCRIPTS / "prepare_source.py"),
                "--winner", str(winner),
                "--duration", str(args.duration),
                "--out", str(source_mp4)]
    if args.cache_dir:
        prep_cmd += ["--cache-dir", args.cache_dir]
    run(prep_cmd)

    # 5. compose music
    run(["python", str(SCRIPTS / "compose_music.py"),
         "--brief", args.brief,
         "--duration", str(args.duration),
         "--out", str(audio_wav),
         "--save-spec", str(music_spec)])

    # 6. render dual format
    fx_arg = []
    if args.effects:
        fx_arg = ["--effects", args.effects]
    for layout in ("horizontal", "vertical"):
        env = os.environ.copy(); env["LAYOUT"] = layout
        run(["python", str(SCRIPTS / "blob_render.py"),
             "--source", str(source_mp4), "--audio", str(audio_wav),
             "--slug", slug, "--out", str(out_dir),
             "--duration", str(args.duration)] + fx_arg, env=env)

    # 7. title + description
    run(["python", str(SCRIPTS / "title_and_desc.py"),
         "--winner", str(winner), "--music", str(music_spec),
         "--brief", args.brief, "--slug", slug,
         "--out", str(metadata)])

    print(f"\n== DONE → {out_dir}")
    for p in sorted(out_dir.iterdir()):
        if p.is_file():
            print(f"   {p.name:45} {p.stat().st_size//(1024):>7} KB")


if __name__ == "__main__":
    main()
