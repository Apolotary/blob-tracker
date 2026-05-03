"""
video_search.py — find a public-domain video on the Internet Archive.

Consolidates three older scripts (brief_to_queries.py + ia_search.py +
pick_candidate.py) into one tool with several entry points:

    # Full Kimi flow: brief → queries → search → vision pick → winner
    python video_search.py --brief "1920s botanical" --out winner.json

    # Direct query (no Kimi expansion). With --kimi-pick adds vision selection.
    python video_search.py --query "lunar surface NASA" --kimi-pick \
                           --out winner.json

    # Direct query, take highest-download result without asking Kimi.
    python video_search.py --query "tropical fish" --no-pick --out winner.json

    # Multiple comma-separated queries (skip Kimi expansion).
    python video_search.py --queries "irises,fruit blossom,botanical 1920s" \
                           --out winner.json

The output JSON is the IA candidate dict (identifier, title, url,
thumbnail, year, downloads, size_bytes) plus a `pick_reason` field.
That dict is what `prepare_source.py` consumes downstream.
"""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
import time
from pathlib import Path

import requests


# ============================================================
# IA search — same logic as old ia_search.py
# ============================================================

PREFERRED_COLLECTIONS = (
    "prelinger",
    "opensource_movies",
    "publicdomainmovies",
    "nasa",
    "nara",
    "internetarchive",
)


def ia_search(query, max_results=6, prefer_collections=True):
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


def ia_metadata(identifier):
    r = requests.get(f"https://archive.org/metadata/{identifier}", timeout=30)
    r.raise_for_status()
    return r.json()


def _pick_video_file(meta):
    files = meta.get("files", [])
    out = []
    for f in files:
        fmt = f.get("format", "")
        name = f.get("name", "")
        if not name.lower().endswith((".mp4", ".m4v")):
            continue
        if fmt not in ("h.264", "h.264 IA", "MPEG4", "h.264 HD",
                       "512Kb MPEG4"):
            continue
        try:
            size = int(f.get("size", 0))
        except (TypeError, ValueError):
            size = 0
        out.append((name, size, fmt))
    if not out:
        return None, None
    out.sort(key=lambda c: (0 if c[2] == "h.264" else 1, -c[1]))
    return out[0][0], out[0][1]


def _thumbnail_url(identifier):
    return f"https://archive.org/services/img/{identifier}"


def collect_candidates(queries, max_per_query=6, sleep_s=0.2):
    """Run each query, dedupe by identifier, return list of candidate dicts."""
    seen = set()
    candidates = []
    for q in queries:
        try:
            docs = ia_search(q, max_results=max_per_query)
        except Exception as exc:
            print(f"  search '{q}' failed: {exc}", file=sys.stderr)
            continue
        for d in docs:
            ident = d.get("identifier")
            if not ident or ident in seen:
                continue
            seen.add(ident)
            try:
                meta = ia_metadata(ident)
            except Exception as exc:
                print(f"  metadata '{ident}' failed: {exc}", file=sys.stderr)
                continue
            fn, sz = _pick_video_file(meta)
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
                "thumbnail": _thumbnail_url(ident),
            })
            time.sleep(sleep_s)
        time.sleep(sleep_s)
    return candidates


# ============================================================
# Kimi: brief → queries
# ============================================================

QUERY_SYSTEM = """You design searches against the Internet Archive (archive.org)
for public-domain video footage. Given a creative brief, return 3-5 short
keyword/title queries that are likely to surface evocative public-domain
material.

Rules:
- Each query is 2-5 words.
- Prefer concrete nouns over moods.
- Mix wide and narrow queries.
- Bias toward US National Archives, Prelinger Archive, NASA, USDA, BBC archive.
- Return STRICT JSON: {"queries": ["query 1", "query 2", ...]}."""


def brief_to_queries(brief: str) -> list[str]:
    from kimi_client import chat_json
    user = f"Brief: {brief}\n\nReturn 3-5 search queries as JSON."
    data = chat_json(QUERY_SYSTEM, user, temperature=0.6, max_tokens=300)
    queries = data.get("queries", [])
    if not isinstance(queries, list) or not queries:
        return [brief]
    return queries


# ============================================================
# Kimi: vision pick from candidate thumbnails
# ============================================================

PICK_SYSTEM_TPL = """You are picking the single best public-domain video for
a creative brief. You will see thumbnails labelled #0, #1, #2 ... and a
brief.

Brief: {brief}

Rules:
- Choose the thumbnail whose imagery best matches the brief's mood AND
  whose subject is concrete enough to drive 26 seconds of footage.
- Prefer rich visual texture, motion, recognisable subjects.
- Avoid thumbnails that are blank, all text, or extremely low-resolution.
- Respond with EXACTLY one line of JSON:
  {{"pick": <int>, "reason": "<one short sentence>"}}"""


def _download(url, out_path) -> bool:
    try:
        r = requests.get(url, timeout=15)
        r.raise_for_status()
        Path(out_path).write_bytes(r.content)
        return True
    except Exception:
        return False


def kimi_pick(candidates, brief, *, max_show=8):
    """Returns (winner_dict, reason_str). Falls back to candidates[0] on
    any error so the caller always gets a usable winner."""
    from kimi_client import vision_pick
    cands = candidates[:max_show]
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        thumbs = []
        kept = []
        for i, c in enumerate(cands):
            tp = td / f"thumb_{i:02d}.jpg"
            if _download(c["thumbnail"], tp):
                thumbs.append(tp); kept.append(c)
        if not thumbs:
            return cands[0], "fallback (no thumbnails)"
        prompt = PICK_SYSTEM_TPL.format(brief=brief) + "\n\nCandidates:\n"
        for i, c in enumerate(kept):
            prompt += (f"#{i}: {c['title'][:80]}  ({c.get('year','?')}, "
                       f"{c['size_bytes']//(1024*1024)}MB)\n")
        try:
            raw = vision_pick(prompt, thumbs, temperature=0.2, max_tokens=200)
            s = raw.find("{"); e = raw.rfind("}")
            obj = json.loads(raw[s:e + 1])
            idx = max(0, min(len(kept) - 1, int(obj.get("pick", 0))))
            return kept[idx], obj.get("reason", "")
        except Exception as exc:
            print(f"  Kimi vision failed ({exc}); using top download",
                  file=sys.stderr)
            return kept[0], "fallback (vision call failed)"


# ============================================================
# High-level entry point
# ============================================================

def find_video(*, brief: str | None = None,
               query: str | None = None,
               queries: list[str] | None = None,
               max_per_query: int = 5,
               kimi_pick_enabled: bool = True) -> dict:
    """Programmatic entry. Returns the winner candidate dict
    (identifier, title, url, thumbnail, ..., pick_reason)."""
    if queries is None:
        if brief:
            queries = brief_to_queries(brief)
        elif query:
            queries = [query]
        else:
            raise ValueError("need one of: brief, query, queries")

    candidates = collect_candidates(queries, max_per_query=max_per_query)
    if not candidates:
        raise RuntimeError(f"no IA candidates for queries: {queries}")

    if kimi_pick_enabled and brief:
        winner, reason = kimi_pick(candidates, brief)
    else:
        winner = candidates[0]
        reason = "highest-download (no Kimi pick)"
    out = dict(winner)
    out["pick_reason"] = reason
    out["queries"] = queries
    return out


# ============================================================
# CLI
# ============================================================

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--brief", default=None,
                    help="creative brief — Kimi expands into 3-5 queries")
    ap.add_argument("--query", default=None,
                    help="single direct IA query (no Kimi expansion)")
    ap.add_argument("--queries", default=None,
                    help="comma-separated list of direct queries")
    ap.add_argument("--max-per-query", type=int, default=5)
    ap.add_argument("--no-pick", action="store_true",
                    help="don't call Kimi vision; take highest-download")
    ap.add_argument("--kimi-pick", action="store_true",
                    help="force Kimi vision pick even without --brief")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    queries = None
    if args.queries:
        queries = [q.strip() for q in args.queries.split(",") if q.strip()]

    pick = (not args.no_pick) and (args.brief is not None or args.kimi_pick)
    winner = find_video(
        brief=args.brief,
        query=args.query,
        queries=queries,
        max_per_query=args.max_per_query,
        kimi_pick_enabled=pick,
    )
    Path(args.out).write_text(json.dumps(winner, indent=2))
    print(f"winner → {winner['identifier']}")
    print(f"  title:  {winner['title']}")
    print(f"  url:    {winner['url']}")
    print(f"  reason: {winner.get('pick_reason', '')}")


if __name__ == "__main__":
    main()
