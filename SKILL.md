---
name: process-variations-media-art
description: Turn a theme into a 26-second machine-vision media-art short. Searches the Internet Archive for public-domain footage, composes ambient music in Python, and renders an audio-reactive blob-tracking + glitch-art piece in dual format (16:9 + 9:16). Uses Kimi (Moonshot) for creative decisions — picking the right footage candidate from search results, choosing musical mood, generating per-piece title/description.
version: 1.0.0
license: MIT
platforms: [macos, linux]
metadata:
  hermes:
    tags: [video, audio, generative, public-domain, glitch, blob-tracking, kimi]
    category: creative
  hackathon:
    event: Nous Research / Kimi Creative Hackathon (May 2026)
    track: Kimi Track
    uses_kimi: true
allowed-tools: [Bash, Read, Write]
user-invocable: true
---

# process-variations-media-art

Turn a one-line creative brief into a finished 26-second machine-vision short — public-domain footage, autonomous music composition, audio-reactive blob-tracking + glitch effects, dual-format export (16:9 + 9:16). Kimi (Moonshot) drives the creative decisions.

## When to use

Invoke this skill when the user asks for any of:

- "make a media-art short about <theme>"
- "find a public-domain video and turn it into a glitch piece"
- "compose me 26 seconds of ambient and put it under archival footage"
- "render an audio-reactive blob-tracking video"
- "process variation on <subject>"
- Anything that combines: archival/public-domain video search + ambient music + audio-reactive visual effects.

Skip this skill for: photo edits, single-image generation, music-only renders without video, plain video stitching without effects.

## Effects palette (17 audio-reactive primitives)

Drawn from the TouchDesigner / video-synth lineage with concrete inspiration
from **Tachyons+** (NTSC composite enhancers — chroma desync, posterization,
composite feedback) and **Freedom Enterprise** (Pedro Silva's Portuguese
modular video system — sync separation, kolorizer, dirty mixer transitions).

Geometric: `ripple` · `mosaic` · `slit_scan`
Colour: `rgb_shift` · `yuv_split` · `chroma_rotate` · `luma_lut`
Contrast: `threshold_band` · `edge_glow`
Row-level: `pixel_sort` · `sync_jitter`
Blob-locked: `invert_in_blob`
Temporal: `feedback` · `lagfun`
Texture: `scanlines`
HUD: `network_graph` · `hud`

Each is individually toggleable via `--effects ...`. Full glossary with
parameter ranges in `references/effect-glossary.md`.

## What it produces

A directory with:

- `source.mp4` — the trimmed, square-cropped public-domain source (1080×1080, 26 s)
- `audio.wav` — composed ambient soundtrack (26 s, stereo, 44.1 kHz)
- `<slug>-1920x1080.mp4` — horizontal final
- `<slug>-1080x1920.mp4` — vertical final (Shorts/Reels)
- `metadata.json` — title, description, IA source URL, musical key/tempo, render log

## Pipeline (six stages)

1. **Brief → search query**     — Kimi turns the user's brief into 3-5 IA search queries.
2. **IA candidate scoring**     — for each search, fetch top results from `archive.org/advancedsearch.php`; pull thumbnails; let Kimi-vision pick the best one.
3. **Source preparation**       — `scripts/prepare_source.py` trims and square-crops to 26 s × 1080×1080.
4. **Music composition**        — Kimi picks key/mood; `scripts/compose_music.py` synthesises an ambient stack (pad + drone + sparkles + sub-pulse + emulsion noise).
5. **Render**                   — `scripts/blob_render.py` renders dual-format with audio-reactive blob tracking + glitch primitives.
6. **Title + description**      — Kimi generates the title and YouTube description, written to `metadata.json`.

## Procedure (what the agent should do)

### 0. Preflight

```bash
# Required
test -n "$MOONSHOT_API_KEY" || { echo "MOONSHOT_API_KEY not set"; exit 2; }

# Recommended workspace (the scripts default here, override with PV_OUT_DIR)
export PV_OUT_DIR="${PV_OUT_DIR:-$HOME/process-variations}"
mkdir -p "$PV_OUT_DIR"
```

Dependencies (one-time):
```bash
pip install -r "$(dirname $0)/requirements.txt"
# numpy, opencv-python, pillow, librosa, requests, openai
```

### 1. Generate IA search queries via Kimi

```bash
python scripts/brief_to_queries.py \
  --brief "$USER_BRIEF" \
  --out "$PV_OUT_DIR/queries.json"
```

Calls Kimi (`kimi-k2.6`) with a short system prompt asking for 3–5 IA queries that would yield strong public-domain footage matching the brief. Output is a JSON array of queries.

### 2. Search IA + score candidates

```bash
python scripts/ia_search.py \
  --queries "$PV_OUT_DIR/queries.json" \
  --out "$PV_OUT_DIR/candidates.json" \
  --max-per-query 6

python scripts/pick_candidate.py \
  --candidates "$PV_OUT_DIR/candidates.json" \
  --brief "$USER_BRIEF" \
  --out "$PV_OUT_DIR/winner.json"
```

`ia_search.py` queries `archive.org/advancedsearch.php`, prefers `prelinger`/`opensource_movies`/`publicdomainmovies` collections, and returns the highest-download h.264 mp4s. `pick_candidate.py` downloads thumbnail JPGs (or extracts a frame from the source if no thumbnail) and asks Kimi-vision to pick the one whose imagery best fits the brief.

### 3. Prepare source

```bash
python scripts/prepare_source.py \
  --winner "$PV_OUT_DIR/winner.json" \
  --duration 26 \
  --size 1080 \
  --out "$PV_OUT_DIR/source.mp4"
```

Downloads the chosen mp4, finds a 26-second window with the highest visual energy (motion + variance), centre-crops to a square at 1080×1080.

### 4. Compose music

```bash
python scripts/compose_music.py \
  --brief "$USER_BRIEF" \
  --duration 26 \
  --out "$PV_OUT_DIR/audio.wav"
```

Asks Kimi for a JSON spec — `{"key": "Eb", "mode": "major", "bpm": 58, "mood": "warm/contemplative"}` — then synthesises chord pad + sustained string drone + sparse sparkles + sub-pulse + emulsion-noise floor with numpy.

### 5. Render dual-format

```bash
LAYOUT=horizontal python scripts/blob_render.py \
  --source "$PV_OUT_DIR/source.mp4" \
  --audio  "$PV_OUT_DIR/audio.wav" \
  --slug   "$PV_SLUG" \
  --out    "$PV_OUT_DIR"

LAYOUT=vertical   python scripts/blob_render.py \
  --source "$PV_OUT_DIR/source.mp4" \
  --audio  "$PV_OUT_DIR/audio.wav" \
  --slug   "$PV_SLUG" \
  --out    "$PV_OUT_DIR"
```

Renders single-pane (square source centred) with audio-reactive blob tracking + glitch primitives (RGB chromatic aberration on highs, radial-sine displacement, pixel-sort on motion-mask peaks, lagfun trail, in-blob colour invert, network-graph connection lines between blob centres, TouchDesigner-style HUD).

### 6. Title + description via Kimi

```bash
python scripts/title_and_desc.py \
  --winner "$PV_OUT_DIR/winner.json" \
  --music  "$PV_OUT_DIR/audio.json" \
  --brief  "$USER_BRIEF" \
  --out    "$PV_OUT_DIR/metadata.json"
```

## One-shot orchestrator

For typical use, just run:

```bash
python scripts/pipeline.py --brief "<USER_BRIEF>" --slug "<SLUG>"
```

It chains stages 1–6 and writes everything to `$PV_OUT_DIR/<SLUG>/`.

## Examples

**Brief**: "old botanical film with hallucinated colour and a slow ambient pad"
→ The agent finds *Fruits and Flowers* (Internet Archive 0780, ~1920); selects a 26 s iris + intertitle + macro-stamen segment; writes a 58 BPM Eb-major ambient score; renders blob-tracker over the footage with chromatic aberration on high-band peaks.

**Brief**: "1950s American family Christmas, glitched"
→ Finds a Prelinger home movie, picks a tree-and-presents segment; F-major bell-arp music; heavy datamosh + RGB shift; blob tracker draws network graph over moving family members.

**Brief**: "NASA solar plasma, dread, sub-bass"
→ Finds NASA SDO public-domain footage; C-minor drone + 40 Hz sub-pulse; full-rect blob track on plasma loops + pixel-sort on flares.

## Required env

- `MOONSHOT_API_KEY` — Kimi (Moonshot) API key. Get one at https://platform.kimi.ai/console/api-keys
- `KIMI_MODEL` *(optional)* — default `kimi-k2-turbo-preview` for text. Switch to `kimi-k2.6` for thinking-mode at the cost of ~5x more tokens per call.
- `KIMI_VISION_MODEL` *(optional)* — default `kimi-k2.6`. The only K2 model with reliable vision input as of 2026-05.
- `PV_OUT_DIR` *(optional)* — where to write outputs. Default `~/process-variations`.
- `PV_SLUG` *(optional)* — slug for the run. Auto-generated from brief if omitted.

## Costs (typical 26 s piece)

- Kimi calls: ~6 short calls (queries, vision-pick, music spec, title, description). ~$0.01 total at `kimi-k2.6` rates.
- Network: ~50–100 MB IA download.
- Compute: pure CPU, ~3 minutes wall on an Apple M1 / 8 GB; no GPU required.

## Reference

- `references/effect-glossary.md` — definitions and parameters for every glitch primitive used.
- `references/audio-design.md` — how the ambient stack is built and how Kimi's mood map turns into actual key/bpm choices.
- `templates/kimi-prompts.json` — prompt scaffolds for each Kimi call.
