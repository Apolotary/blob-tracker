"""
fetch_demos.py — download a starter pack of free public-domain video clips
for testing blob-tracker. All clips are from the Internet Archive (Prelinger
collection / opensource_movies — public domain).

The clips land in `--out-dir` (default `~/blob-tracker/demos/`). Already-
downloaded files are skipped, so re-running is cheap.

Usage:
    python scripts/fetch_demos.py                # downloads all default clips
    python scripts/fetch_demos.py --only flowers # subset by tag
    python scripts/fetch_demos.py --list         # show what's available

Try one with the skill:
    python scripts/render.py --quick \\
        --video ~/blob-tracker/demos/bee-city.mp4 \\
        --detector mog2 --viz centroid-trail,network \\
        --output ~/Desktop/bee-tracked.mp4

For curated NON-Internet-Archive sources (Pexels, Pixabay, Coverr, NASA),
see references/demo-clips.md.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import requests


# Curated set — small, on-topic, public-domain.
DEMOS = [
    # ---- flowers / nature ----
    {
        "name": "bee-city.mp4",
        "tags": ["flowers", "nature"],
        "size_mb": 65,
        "title": "Bee City (1951) — bees + flowers",
        "url": "https://archive.org/download/BeeCity1951/BeeCity1951.mp4",
    },
    {
        "name": "seeds-and-dispersal.mp4",
        "tags": ["flowers", "botanical"],
        "size_mb": 82,
        "title": "Seeds and Seed Dispersal — botanical macro",
        "url": ("https://archive.org/download/"
                "6118_Seeds_and_Seed_Dispersal_01_01_08_27/"
                "6118_Seeds_and_Seed_Dispersal_01_01_08_27.mp4"),
    },
    # ---- fireworks ----
    {
        "name": "fireworks-vlog.mp4",
        "tags": ["fireworks"],
        "size_mb": 21,
        "title": "Vlog 03 - Fireworks! — direct firework footage",
        "url": ("https://archive.org/download/Vlog_03__Fireworks/"
                "vlog03_512kb.mp4"),
    },
    {
        "name": "design-for-dreaming.mp4",
        "tags": ["fireworks", "vintage"],
        "size_mb": 55,
        "title": "Design for Dreaming (1956) — surreal GM industrial film",
        "url": ("https://archive.org/download/Designfo1956/"
                "Designfo1956.mp4"),
    },
    # ---- archival fillers (always fun for blob tracking) ----
    {
        "name": "duck-and-cover.mp4",
        "tags": ["archival"],
        "size_mb": 17,
        "title": "Duck and Cover (1951) — civil-defense classic",
        "url": ("https://archive.org/download/DuckandC1951/"
                "DuckandC1951_512kb.mp4"),
    },
]


def download(url: str, dest: Path) -> bool:
    """Stream-download with a progress line. Returns True on success."""
    try:
        with requests.get(url, stream=True, timeout=60) as r:
            r.raise_for_status()
            total = int(r.headers.get("content-length", 0))
            done = 0
            with open(dest, "wb") as f:
                for chunk in r.iter_content(chunk_size=1 << 20):
                    if not chunk:
                        continue
                    f.write(chunk)
                    done += len(chunk)
                    if total:
                        pct = 100 * done / total
                        sys.stdout.write(
                            f"\r    {done//(1024*1024):4d} / "
                            f"{total//(1024*1024):4d} MB  ({pct:5.1f}%)")
                        sys.stdout.flush()
            sys.stdout.write("\n")
        return True
    except Exception as e:
        print(f"\n    ERROR: {e}", file=sys.stderr)
        if dest.exists():
            dest.unlink()
        return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-dir",
                    default=str(Path.home() / "blob-tracker" / "demos"),
                    help="where to put the clips")
    ap.add_argument("--only", default=None,
                    help="comma-separated tag filter (flowers, fireworks, "
                         "vintage, archival, nature, botanical)")
    ap.add_argument("--list", action="store_true",
                    help="list available clips and exit")
    args = ap.parse_args()

    if args.list:
        print("Available demo clips (Internet Archive, public domain):")
        for d in DEMOS:
            print(f"  {d['name']:30}  {d['size_mb']:4d} MB  "
                  f"[{','.join(d['tags']):20}]  {d['title']}")
        return

    selected = DEMOS
    if args.only:
        wanted = {t.strip() for t in args.only.split(",")}
        selected = [d for d in DEMOS if wanted & set(d["tags"])]
        if not selected:
            sys.exit(f"no clips match tags: {sorted(wanted)}")

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    total_mb = sum(d["size_mb"] for d in selected)
    print(f"fetching {len(selected)} clip(s), ~{total_mb} MB → {out_dir}")
    ok = 0
    for d in selected:
        dest = out_dir / d["name"]
        if dest.exists():
            print(f"  ✓ {d['name']:30} (cached)")
            ok += 1
            continue
        print(f"  ↓ {d['name']:30} {d['size_mb']:4d} MB  {d['title']}")
        if download(d["url"], dest):
            ok += 1
    print(f"\ndone: {ok}/{len(selected)} clips at {out_dir}")
    print(f"try: python scripts/render.py --quick "
          f"--video {out_dir/selected[0]['name']} "
          f"--detector mog2 --viz centroid-trail,network "
          f"--output ~/Desktop/demo-tracked.mp4")


if __name__ == "__main__":
    main()
