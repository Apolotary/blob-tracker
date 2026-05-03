"""
brief_to_queries.py — turn a one-line creative brief into 3-5 Internet Archive
search queries via Kimi.

Usage:
    python brief_to_queries.py --brief "<text>" --out queries.json
"""
import argparse
import json
import sys
from pathlib import Path

from kimi_client import chat_json

SYSTEM = """You design searches against the Internet Archive (archive.org) for
public-domain video footage. Given a creative brief, return 3-5 short
keyword/title queries that are likely to surface evocative public-domain
material.

Rules:
- Each query is 2-5 words.
- Prefer concrete nouns over moods.
- Mix wide and narrow queries.
- Bias toward US National Archives, Prelinger Archive, NASA, USDA, BBC archive.
- Return STRICT JSON: {"queries": ["query 1", "query 2", ...]}."""

USER_TEMPLATE = """Brief: {brief}

Return 3-5 search queries as JSON."""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--brief", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    user = USER_TEMPLATE.format(brief=args.brief)
    data = chat_json(SYSTEM, user, temperature=0.6, max_tokens=300)
    queries = data.get("queries", [])
    if not isinstance(queries, list) or not queries:
        print("Kimi returned no queries; falling back to brief itself", file=sys.stderr)
        queries = [args.brief]

    Path(args.out).write_text(json.dumps({"queries": queries}, indent=2))
    print(f"wrote {len(queries)} queries → {args.out}")
    for q in queries:
        print(f"  • {q}")


if __name__ == "__main__":
    main()
