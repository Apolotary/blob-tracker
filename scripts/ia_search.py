"""
ia_search.py — search Internet Archive for public-domain video matching
a list of queries. Outputs candidates.json with metadata + download URL +
thumbnail URL for each.

Usage:
    python ia_search.py --queries queries.json --out candidates.json --max-per-query 6
"""
import argparse
import json
import sys
import time
from pathlib import Path

import requests

PREFERRED_COLLECTIONS = (
    "prelinger",
    "opensource_movies",
    "publicdomainmovies",
    "nasa",
    "nara",
    "internetarchive",
)


def search(query, max_results=6, prefer_collections=True):
    """Search IA for movies matching `query`."""
    base = "https://archive.org/advancedsearch.php"
    coll_clause = ""
    if prefer_collections:
        coll_clause = " AND (" + " OR ".join(
            f'collection:"{c}"' for c in PREFERRED_COLLECTIONS
        ) + ")"
    q = (f'({query}) AND mediatype:movies'
         f' AND format:("h.264" OR "MPEG4" OR "h.264 IA")'
         f'{coll_clause}')
    params = [
        ("q", q),
        ("fl[]", "identifier"),
        ("fl[]", "title"),
        ("fl[]", "description"),
        ("fl[]", "year"),
        ("fl[]", "downloads"),
        ("fl[]", "collection"),
        ("rows", str(max_results)),
        ("sort[]", "downloads desc"),
        ("output", "json"),
    ]
    r = requests.get(base, params=params, timeout=30)
    r.raise_for_status()
    return r.json().get("response", {}).get("docs", [])


def metadata(identifier):
    r = requests.get(f"https://archive.org/metadata/{identifier}", timeout=30)
    r.raise_for_status()
    return r.json()


def pick_video_file(meta):
    """From IA metadata, pick the best mp4 file. Returns (filename, size)."""
    files = meta.get("files", [])
    candidates = []
    for f in files:
        fmt = f.get("format", "")
        name = f.get("name", "")
        if not name.lower().endswith((".mp4", ".m4v")):
            continue
        if fmt not in ("h.264", "h.264 IA", "MPEG4", "h.264 HD", "512Kb MPEG4"):
            continue
        try:
            size = int(f.get("size", 0))
        except (TypeError, ValueError):
            size = 0
        candidates.append((name, size, fmt))
    if not candidates:
        return None, None
    # prefer h.264 over MPEG4, then largest
    candidates.sort(key=lambda c: (0 if c[2] == "h.264" else 1, -c[1]))
    return candidates[0][0], candidates[0][1]


def thumbnail_url(identifier):
    return f"https://archive.org/services/img/{identifier}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--queries", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--max-per-query", type=int, default=6)
    args = ap.parse_args()

    queries = json.loads(Path(args.queries).read_text()).get("queries", [])
    if not queries:
        print("no queries", file=sys.stderr); sys.exit(2)

    seen = set()
    candidates = []
    for q in queries:
        try:
            docs = search(q, max_results=args.max_per_query)
        except Exception as e:
            print(f"  search '{q}' failed: {e}", file=sys.stderr)
            continue
        for d in docs:
            ident = d.get("identifier")
            if not ident or ident in seen:
                continue
            seen.add(ident)
            try:
                m = metadata(ident)
            except Exception as e:
                print(f"  metadata '{ident}' failed: {e}", file=sys.stderr)
                continue
            fn, sz = pick_video_file(m)
            if not fn:
                continue
            candidates.append({
                "identifier": ident,
                "query": q,
                "title": d.get("title", ""),
                "description": str(d.get("description", ""))[:300],
                "year": d.get("year", ""),
                "downloads": d.get("downloads", 0),
                "filename": fn,
                "size_bytes": sz,
                "url": f"https://archive.org/download/{ident}/{fn}",
                "thumbnail": thumbnail_url(ident),
            })
            time.sleep(0.2)
        time.sleep(0.3)

    Path(args.out).write_text(json.dumps({"candidates": candidates}, indent=2))
    print(f"wrote {len(candidates)} candidates → {args.out}")
    for c in candidates[:10]:
        print(f"  • {c['identifier'][:40]:40} | {str(c['year'])[:4]:4} | "
              f"{c['size_bytes']//(1024*1024):4}MB | {c['title'][:50]}")


if __name__ == "__main__":
    main()
