#!/usr/bin/env bash
# make_trailer.sh — render the 5-shot trailer.
#
# Aesthetic: consistent white HUD frame on every shot
#   - bbox(white, label, audio-pulse) — square boxes everywhere
#   - network(white, audio-pulse)     — connecting lines between centers
# Plus one varying inside-effect per shot. The source video is kept clean
# (no global postfx), so the footage shows through unaltered.
#
# Detectors are tuned per shot for "boxes everywhere" — small min_area and
# high max_n so we get 30-80 simultaneous detections.

set -euo pipefail

# ---- config ----
SOURCE_DIR="${SOURCE_DIR:-$HOME/Downloads}"
MUSIC_FILE="${MUSIC_FILE:-$HOME/Downloads/vvøid - Gnawing.mp3}"
MUSIC_START="${MUSIC_START:-00:00:20}"
TRAILER_DIR="${TRAILER_DIR:-/Volumes/GNUSMAS/blob-tracker-results/trailer}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(dirname "$SCRIPT_DIR")"
PYTHON="${PYTHON:-$REPO_DIR/.venv/bin/python}"

mkdir -p "$TRAILER_DIR"

# Common viz-params block — same HUD on every shot. Inner effect (centroid
# trail / spatial echo / emojis / glyphs) is also tuned a bit.
COMMON_VP='{
  "bbox":          {"color":[255,255,255], "thickness":1, "show_label":true,
                    "pulse_audio":false},
  "network":       {"color":[255,255,255], "thickness":1,
                    "pulse_audio":false, "max_distance":140},
  "spatial-echo":  {"mode":"mirror", "border_thickness":1,
                    "border_color":[255,255,255]},
  "glyphs":        {"charset":"·+◦*"},
  "emojis":        {"font_size":56, "lifetime":18,
                    "charset":"🔥✨💫🌟⭐🎆"}
}'

# ---- 5 shots: slug | match | detector | det-params | inside-effect ----
# Target ~25-35 boxes per shot. Network max_distance=140 keeps mesh sparse.
declare -a SHOTS=(
  # marigolds: dog finds petal edges; few clean boxes
  "marigolds|Cinematic time-lapse|dog|{\"sigma_low\":1.2,\"sigma_high\":4.0,\"thresh\":5.0,\"min_area\":250,\"max_n\":30}|"
  # murmuration: many small boxes for the bird clusters; no inner effect
  # (the boxes' own re-detection per frame *is* the movement)
  "murmuration|Massive flock|dog|{\"sigma_low\":0.8,\"sigma_high\":2.5,\"thresh\":2.5,\"min_area\":25,\"max_n\":35}|"
  # bee: simple-blob picks bee + petal pockets; spatial-echo trick inside
  "bee|Extreme close-up|simple-blob|{\"min_threshold\":20,\"min_area\":350,\"max_n\":25}|spatial-echo"
  # fireflies: dog catches each glowing point; glyphs scatter inside
  "fireflies|Ethereal forest|dog|{\"sigma_low\":1.2,\"sigma_high\":3.5,\"thresh\":4.0,\"min_area\":80,\"max_n\":25}|glyphs"
  # lava: simple-blob at lower threshold catches more sparks; emojis inside
  "lava|Volcanic eruption|simple-blob|{\"min_threshold\":140,\"min_area\":80,\"max_n\":35}|emojis"
)

# ---- step 1: full 30 s music slice (for the final mux) ----
MUSIC_SLICE="$TRAILER_DIR/trailer-music.wav"
echo "==> slicing music: $MUSIC_START + 30 s → $MUSIC_SLICE"
ffmpeg -y -loglevel error -ss "$MUSIC_START" -t 30 -i "$MUSIC_FILE" \
       -ar 44100 -ac 2 "$MUSIC_SLICE"

# ---- step 2: render each shot ----
RENDERS=()
for i in "${!SHOTS[@]}"; do
  IFS='|' read -r SLUG MATCH DET DET_PARAMS INNER <<< "${SHOTS[$i]}"
  shot_idx=$((i + 1))
  offset_s=$((i * 6))
  # build viz chain: HUD frame + optional inner effect
  if [[ -n "$INNER" ]]; then
    VIZ="bbox,network,$INNER"
  else
    VIZ="bbox,network"
  fi
  echo
  echo "==> shot $shot_idx/5: $SLUG  ($DET → $VIZ)"

  SRC=$(find "$SOURCE_DIR" -maxdepth 1 -type f -name "*${MATCH}*.mp4" -print -quit)
  if [[ -z "${SRC:-}" ]]; then
    echo "ERROR: no source found matching: $MATCH" >&2
    exit 2
  fi

  # slice this shot's 6 s of audio so reactivity is timed to the music
  SHOT_AUDIO="$TRAILER_DIR/_audio_${shot_idx}_${SLUG}.wav"
  ffmpeg -y -loglevel error -ss "$offset_s" -t 6 -i "$MUSIC_SLICE" \
         -ar 44100 -ac 2 "$SHOT_AUDIO"

  SHOT_OUT="$TRAILER_DIR/_shot_${shot_idx}_${SLUG}.mp4"
  "$PYTHON" "$SCRIPT_DIR/render.py" \
    --video "$SRC" --audio "$SHOT_AUDIO" \
    --duration 6 --size 1080 --fps 30 \
    --detector "$DET" \
    --detector-params "$DET_PARAMS" \
    --viz "$VIZ" \
    --viz-params "$COMMON_VP" \
    --output "$SHOT_OUT" \
    --slug "trailer-$shot_idx-$SLUG" \
    --out-dir "$TRAILER_DIR/_workspace" 2>&1 \
    | grep -E "(\[render\]|frame [0-9]+/[0-9]+|DONE|ERROR)" || true
  RENDERS+=("$SHOT_OUT")
done

# ---- step 3: concat the 5 shots ----
echo
echo "==> concatenating ${#RENDERS[@]} shots → trailer"
CONCAT_LIST="$TRAILER_DIR/_concat.txt"
: > "$CONCAT_LIST"
for r in "${RENDERS[@]}"; do
  printf "file '%s'\n" "$r" >> "$CONCAT_LIST"
done

FINAL="$TRAILER_DIR/blob-tracker-trailer.mp4"
ffmpeg -y -loglevel error -f concat -safe 0 -i "$CONCAT_LIST" \
       -c:v libx264 -crf 18 -pix_fmt yuv420p -preset medium \
       -c:a aac -b:a 192k \
       "$FINAL"

echo
echo "==> DONE → $FINAL"
ls -lh "$FINAL"
