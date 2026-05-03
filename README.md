# process-variations-media-art

A Hermes Agent skill (also Claude-Code-skill compatible) that turns a one-line
creative brief into a finished 26-second machine-vision short — autonomous
public-domain footage search, ambient music composition, audio-reactive
blob-tracking + glitch render, dual-format export.

Built for the **Nous Research / Kimi Creative Hackathon (May 2026)**, Kimi
Track. All LLM/vision calls go to Kimi (Moonshot AI) `kimi-k2.6`.

## What it does (six stages)

1. **Brief → search queries** — Kimi picks 3-5 IA queries from the brief.
2. **IA candidate scoring** — fetch top results from `archive.org`; Kimi-vision
   picks the best one by examining thumbnails.
3. **Source preparation** — auto-find the most visually-energetic 26-second
   window; centre-square-crop to 1080×1080.
4. **Music composition** — Kimi picks `{key, mode, bpm, mood, progression}`;
   pure-numpy synth renders a 5-layer ambient stack.
5. **Render** — single-pane source with audio-reactive blob tracking + a
   configurable stack of glitch/media-art primitives. Outputs 1920×1080 +
   1080×1920.
6. **Title + description** — Kimi writes the YouTube metadata.

## Install

```bash
# Hermes Agent — clone directly into the skill install path
mkdir -p ~/.hermes/skills/creative
git clone https://github.com/Apolotary/blob-tracker.git \
    ~/.hermes/skills/creative/process-variations-media-art

# Claude Code (also compatible — same SKILL.md format)
mkdir -p ~/.claude/skills
git clone https://github.com/Apolotary/blob-tracker.git \
    ~/.claude/skills/process-variations-media-art

# Dependencies
pip install -r ~/.hermes/skills/creative/process-variations-media-art/requirements.txt
```

## Run

```bash
export MOONSHOT_API_KEY=sk-...
export PV_OUT_DIR=$HOME/process-variations

cd ~/.hermes/skills/creative/process-variations-media-art/scripts
python pipeline.py --brief "1950s home movie of a flower garden, dreamy ambient pad"
```

After ~3 minutes you'll have a directory under `$PV_OUT_DIR/<slug>/` with:

- `<slug>-1920x1080.mp4` — horizontal final
- `<slug>-1080x1920.mp4` — vertical final (Shorts/Reels)
- `source.mp4` — the trimmed public-domain source
- `audio.wav` — the composed ambient score
- `audio.json` — Kimi's musical decisions
- `winner.json` — the IA candidate Kimi picked + reason
- `metadata.json` — Kimi's title + description

## Scripts

| Script                 | Uses Kimi | What it does                                  |
|------------------------|-----------|-----------------------------------------------|
| `kimi_client.py`       | —         | shared client (OpenAI-compatible)             |
| `brief_to_queries.py`  | text      | brief → 3-5 IA search queries                 |
| `ia_search.py`         | —         | live IA search, returns h.264 mp4 candidates  |
| `pick_candidate.py`    | vision    | thumbnail comparison → pick best fit          |
| `prepare_source.py`    | —         | download, energy-scout, square-crop, scale    |
| `compose_music.py`     | text      | spec → 5-layer numpy synth → 26 s WAV         |
| `blob_render.py`       | —         | render with audio-reactive HUD + glitch fx    |
| `title_and_desc.py`    | text      | metadata for YouTube/Shorts upload            |
| `pipeline.py`          | —         | one-shot orchestrator                         |

Both `compose_music.py` and `blob_render.py` work standalone without Kimi
(use `--spec` and pre-existing inputs respectively).

## Effects

`blob_render.py --effects rgb_shift,ripple,pixel_sort,lagfun,invert_in_blob,scanlines,network_graph,hud`

All eight primitives are documented in `references/effect-glossary.md`. They
are individually toggleable; the default stack is everything-on. Each is
audio-reactive — see `references/audio-design.md` for the signal→effect
mapping table.

## Why Kimi for the agentic decisions

- Picking from search results requires *taste*, not just retrieval. Kimi's
  vision model can look at six tiny thumbnails and judge which one will yield
  rich 26 seconds of footage.
- Choosing musical key/mode from a single creative brief is a
  small-but-creative judgement; `kimi-k2.6` does it well at a fraction of a
  cent per call.
- Title-and-description writing benefits from Kimi's compression and tone
  control — this skill specifically asks for "terse, technical, media-art
  register, no hype."

## Hackathon submission notes

- The repository is the skill itself. Drop into `~/.hermes/skills/creative/`
  and the agent has a new `/process-variations-media-art` slash command.
- The included **demo piece** (PV020 in the parent project) was produced with
  an earlier proprietary version of this pipeline — see the demo video tweet.
- All footage in any output is public-domain (Internet Archive Prelinger /
  NASA / NARA collections by default).
- All Kimi calls go through `kimi_client.py` — swap the model ID via
  `KIMI_MODEL=...` env if you want to try `kimi-k2.5` or older.

## License

MIT.
