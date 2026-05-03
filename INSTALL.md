# Install — process-variations-media-art

A 5-minute setup, then one command produces a finished media-art short.

## 1. Drop the skill into Hermes

```bash
mkdir -p ~/.hermes/skills/creative
git clone https://github.com/Apolotary/blob-tracker.git \
    ~/.hermes/skills/creative/process-variations-media-art
```

(Or `~/.claude/skills/process-variations-media-art/` for Claude Code — same
SKILL.md format works in both.)

## 2. Install Python deps

```bash
cd ~/.hermes/skills/creative/process-variations-media-art
pip install -r requirements.txt
```

The deps are: `numpy opencv-python pillow librosa requests openai` — all pure
Python except for OpenCV's wheels. No GPU required.

`ffmpeg` must be on your `$PATH` (Homebrew: `brew install ffmpeg`).

## 3. Set the Kimi key

```bash
export MOONSHOT_API_KEY=sk-...
```

Get one free at https://platform.kimi.ai/console/api-keys.

## 4. Run

```bash
python ~/.hermes/skills/creative/process-variations-media-art/scripts/pipeline.py \
    --brief "1920s botanical film of irises with hallucinated colour and a slow ambient pad"
```

About three minutes later (most of which is the Internet Archive download)
you'll have:

```
~/process-variations/<auto-slug>/
├── source.mp4                      ← public-domain footage, 26s, 1080²
├── audio.wav                       ← composed ambient score
├── audio.json                      ← Kimi's musical decisions
├── winner.json                     ← chosen IA item + Kimi's reasoning
├── candidates.json                 ← full search-result list
├── queries.json                    ← Kimi's IA search queries
├── metadata.json                   ← Kimi-written title + description
├── <slug>-1920x1080.mp4           ← horizontal final
└── <slug>-1080x1920.mp4           ← vertical final (Shorts/Reels)
```

## Try it without Kimi

Every Kimi-driven step has a non-Kimi escape hatch so you can validate the
pipeline before committing the API key:

```bash
# Fixed-spec music (skip Kimi music director):
python scripts/compose_music.py \
    --spec '{"key":"D","mode":"minor","bpm":54,"progression":"i-VII-VI-VII"}' \
    --duration 26 --out audio.wav

# IA search alone (no Kimi):
echo '{"queries":["lunar surface","apollo"]}' > q.json
python scripts/ia_search.py --queries q.json --out cands.json --max-per-query 5

# Render any square mp4 + wav into the dual format (no Kimi):
LAYOUT=horizontal python scripts/blob_render.py \
    --source any-square.mp4 --audio any.wav \
    --slug demo --out ./out
```

## Troubleshooting

- **`MOONSHOT_API_KEY not set`** — export the key in the shell that runs
  `pipeline.py`. The skill does NOT load `.env` automatically.
- **`No candidates found`** — the brief was too narrow; try broader keywords
  (people/places > moods). Or pass `--queries` directly to `ia_search.py`.
- **`ffmpeg failed`** — confirm `ffmpeg -version` works at the shell level.
- **OOM during blob_render** — reduce duration (`--duration 12`) or render
  one layout at a time. The script uses ~2 GB peak on an 8 GB Mac mini.
- **Slow IA download** — `archive.org` mp4s are ~50–500 MB depending on the
  source; pass `--cache-dir ~/iacache` to `pipeline.py` so re-runs skip the
  download.
