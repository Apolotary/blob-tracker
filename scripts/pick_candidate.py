"""
pick_candidate.py — given IA candidates and a creative brief, ask Kimi-vision
to pick the best one by examining their thumbnails.

Usage:
    python pick_candidate.py --candidates candidates.json --brief "..." --out winner.json
"""
import argparse
import json
import sys
import os
import tempfile
from pathlib import Path

import requests

from kimi_client import vision_pick


SYSTEM_PROMPT_TPL = """You are picking the single best public-domain video for
a creative brief. You will see thumbnails labelled #0, #1, #2 ... and a brief.

Brief: {brief}

Rules:
- Choose the thumbnail whose imagery best matches the brief's mood AND
  whose subject is concrete enough to drive 26 seconds of footage.
- Prefer rich visual texture, motion, recognisable subjects.
- Avoid thumbnails that are blank, all text, or extremely low-resolution.
- Respond with EXACTLY one line of JSON:
  {{"pick": <int>, "reason": "<one short sentence>"}}"""


def download_thumb(url, out_path):
    try:
        r = requests.get(url, timeout=15)
        r.raise_for_status()
        out_path.write_bytes(r.content)
        return True
    except Exception:
        return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--candidates", required=True)
    ap.add_argument("--brief", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--max-show", type=int, default=8,
                    help="number of candidates to show Kimi (top by downloads)")
    args = ap.parse_args()

    cands = json.loads(Path(args.candidates).read_text()).get("candidates", [])
    if not cands:
        print("no candidates", file=sys.stderr); sys.exit(2)
    cands = cands[: args.max_show]

    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        thumb_paths = []
        kept = []
        for i, c in enumerate(cands):
            tp = td / f"thumb_{i:02d}.jpg"
            if download_thumb(c["thumbnail"], tp):
                thumb_paths.append(tp)
                kept.append(c)
            else:
                print(f"  thumb {i} fetch failed: {c['identifier']}", file=sys.stderr)

        if not thumb_paths:
            print("no thumbs downloaded; defaulting to first candidate", file=sys.stderr)
            winner = cands[0]
            reason = "fallback (no thumbnails available)"
        else:
            prompt = SYSTEM_PROMPT_TPL.format(brief=args.brief) + "\n\n"
            prompt += "Candidates:\n"
            for i, c in enumerate(kept):
                prompt += (f"#{i}: {c['title'][:80]}  "
                           f"({c.get('year','?')}, "
                           f"{c['size_bytes']//(1024*1024)}MB)\n")
            try:
                raw = vision_pick(prompt, thumb_paths,
                                  temperature=0.2, max_tokens=200)
                # parse
                s = raw.find("{"); e = raw.rfind("}")
                if s < 0 or e <= s:
                    raise ValueError(f"no json in: {raw[:200]}")
                obj = json.loads(raw[s:e + 1])
                idx = int(obj.get("pick", 0))
                idx = max(0, min(len(kept) - 1, idx))
                winner = kept[idx]
                reason = obj.get("reason", "")
            except Exception as e:
                print(f"  Kimi vision failed: {e}; defaulting to highest-download",
                      file=sys.stderr)
                winner = kept[0]
                reason = "fallback (vision call failed)"

    out = dict(winner)
    out["pick_reason"] = reason
    Path(args.out).write_text(json.dumps(out, indent=2))
    print(f"winner → {winner['identifier']}")
    print(f"  title:  {winner['title']}")
    print(f"  url:    {winner['url']}")
    print(f"  reason: {reason}")


if __name__ == "__main__":
    main()
