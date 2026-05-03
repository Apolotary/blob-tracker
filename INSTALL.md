# Install — blob-tracker

A 5-minute setup, then one command produces a finished blob-tracked
video.

## 1. Drop the skill into Hermes

```bash
mkdir -p ~/.hermes/skills/creative
git clone https://github.com/Apolotary/blob-tracker.git \
    ~/.hermes/skills/creative/blob-tracker
```

(Or `~/.claude/skills/blob-tracker/` for Claude Code — same SKILL.md
format works in both.)

Alternative: install via the Hermes CLI directly from the repo:
```bash
hermes skills install Apolotary/blob-tracker
```

Or point Hermes at any external dir via `~/.hermes/config.yaml`:
```yaml
skills:
  external_dirs:
    - ~/Documents/Github/blob-tracker
```

## 2. Install Python deps

```bash
cd ~/.hermes/skills/creative/blob-tracker
pip install -r requirements.txt
```

The deps: `numpy opencv-contrib-python pillow librosa requests openai`.
Pure Python except for OpenCV's wheels. No GPU required.

> **Note**: We use `opencv-contrib-python` (not plain `opencv-python`)
> because some detectors need contrib modules (saliency, CSRT tracker).
> If you already have `opencv-python` installed, replace it:
> `pip uninstall opencv-python && pip install opencv-contrib-python`.

`ffmpeg` must be on your `$PATH`:
```bash
brew install ffmpeg            # macOS
sudo apt install ffmpeg        # Debian/Ubuntu
```

## 3. (Optional) Set the Kimi key

Only needed when using `--brief`, `--auto-flavor`, or
`--compose-music` *without* `--music-spec`. Pure renders with explicit
`--video` + (optional) `--audio` work without any API key.

```bash
export MOONSHOT_API_KEY=sk-...
```

Get one at https://platform.kimi.ai/console/api-keys.

## 4. Run

```bash
# Basic — blob-track an existing video, no audio
python ~/.hermes/skills/creative/blob-tracker/scripts/render.py \
    --video myvid.mp4 --output myvid-tracked.mp4

# Add audio reactivity
python ~/.hermes/skills/creative/blob-tracker/scripts/render.py \
    --video myvid.mp4 --audio mytrack.wav \
    --detector mog2 --viz centroid-trail,network,corner-ticks \
    --output out.mp4
```

About 1–3 minutes later (most of which is rendering frames) you'll
have an mp4 with the chosen detector + viz combo applied.

## 5. Use in Hermes chat

Once installed, the slash command becomes available:

```
hermes chat
> /blob-tracker --video myvid.mp4 --detector mog2 --viz centroid-trail
```

Or via natural conversation:
```
hermes chat --toolsets skills -q "blob-track my video at ~/Desktop/clip.mp4 with the heatmap visualization"
hermes chat --toolsets skills -q "find a NASA solar clip and add an ambient pad"
```

## Output layout

A typical run with `--brief` writes to `$BLOB_OUT_DIR/<slug>/`
(default `~/blob-tracker/<slug>/`):

```
~/blob-tracker/<auto-slug>/
├── source.mp4                   ← input video, square-cropped 1080²
├── audio.wav                    ← composed soundtrack (if --compose-music)
├── audio.json                   ← Kimi's musical decisions (key/mode/bpm)
├── winner.json                  ← chosen IA item + Kimi's reasoning
├── auto_flavor_thumb.jpg        ← thumbnail Kimi looked at (if --auto-flavor)
└── <slug>.mp4                   ← final blob-tracked render
                                  (or <slug>-1920x1080 + <slug>-1080x1920 if --dual-format)
```

## Try it without Kimi

Every Kimi-driven step has a non-Kimi escape hatch:

```bash
# Fixed-spec music (skip Kimi music director):
python scripts/compose_music.py \
    --spec '{"key":"D","mode":"minor","bpm":54,"progression":"i-VII-VI-VII"}' \
    --duration 26 --out audio.wav

# IA search alone (no Kimi pick):
python scripts/video_search.py --query "tropical fish" --no-pick \
    --out winner.json

# Render with explicit detector + viz (no Kimi):
python scripts/render.py --video clip.mp4 --audio track.wav \
    --detector mog2 --viz centroid-trail,network --output out.mp4
```

## Troubleshooting

- **`MOONSHOT_API_KEY not set`** — only needed for Kimi-driven flows
  (brief/auto-flavor/compose-music). Pure renders work without it.
- **`No such attribute: cv2.saliency`** — you have `opencv-python`
  installed instead of `opencv-contrib-python`. Reinstall as above.
- **`No candidates found`** — IA query was too narrow; try broader
  keywords (people/places > moods). Or pass `--queries` directly.
- **`ffmpeg failed`** — confirm `ffmpeg -version` works at the shell.
- **OOM during render** — reduce duration (`--duration 12`) or render
  one layout at a time. Peak memory ~2 GB on 8 GB Mac mini.
- **Slow IA download** — `archive.org` mp4s are 50–500 MB. Pass
  `--cache-dir ~/iacache` so re-runs skip the download.
