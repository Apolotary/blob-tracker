# Free / open demo clips for blob-tracker

## Quickest path: use `fetch_demos.py`

Run once to grab a curated 240 MB starter pack from the Internet Archive
(public domain — Prelinger collection):

```bash
python scripts/fetch_demos.py
# or only fireworks:
python scripts/fetch_demos.py --only fireworks
# list what's bundled:
python scripts/fetch_demos.py --list
```

Default destination: `~/blob-tracker/demos/`. Already-downloaded files
are skipped on re-run.

## Bundled clips (Internet Archive — public domain)

| File | Tags | MB | Source |
|---|---|---|---|
| `bee-city.mp4` | flowers, nature | 65 | [BeeCity1951](https://archive.org/details/BeeCity1951) |
| `seeds-and-dispersal.mp4` | flowers, botanical | 82 | [Seeds and Seed Dispersal](https://archive.org/details/6118_Seeds_and_Seed_Dispersal_01_01_08_27) |
| `fireworks-vlog.mp4` | fireworks | 21 | [Vlog 03 - Fireworks](https://archive.org/details/Vlog_03__Fireworks) |
| `design-for-dreaming.mp4` | fireworks, vintage | 55 | [Design for Dreaming (1956)](https://archive.org/details/Designfo1956) |
| `duck-and-cover.mp4` | archival | 17 | [Duck and Cover (1951)](https://archive.org/details/DuckandC1951) |

These are all in the public domain (Prelinger / opensource collections)
so you can use them in any context, commercial or not, without
attribution required.

## Other free / open sources (manual download)

For modern, high-quality clips (4K, slow-mo, etc.) the Internet Archive
isn't your best bet. These platforms host CC0 / royalty-free video that
you can grab manually and pass to `--video`:

### Pixabay — CC0, no attribution required
- Flowers: https://pixabay.com/videos/search/flowers/
- Fireworks: https://pixabay.com/videos/search/fireworks/
- Time-lapse flowers: https://pixabay.com/videos/search/time%20lapse%20flower/
- License: https://pixabay.com/service/license-summary/ (no attribution required, modify allowed)

### Pexels — Pexels License (free, no attribution required)
- Flowers: https://www.pexels.com/search/videos/flowers/
- Fireworks: https://www.pexels.com/search/videos/fireworks/
- License: https://www.pexels.com/license/

### Coverr — CC0 / Coverr License
- Browse: https://coverr.co/
- License: free for commercial use, no attribution required

### NASA Image and Video Library — public domain
- Browse: https://images.nasa.gov/
- Examples: solar plasma loops, Earth-from-orbit, planetary flybys

### Wikimedia Commons — varies (CC, public domain)
- Search videos: https://commons.wikimedia.org/wiki/Category:Videos
- Specific: https://commons.wikimedia.org/wiki/Category:Videos_of_fireworks

## Meme / YouTube clips

For testing with TikTok / YouTube content, [`yt-dlp`](https://github.com/yt-dlp/yt-dlp)
is the standard tool:

```bash
brew install yt-dlp
yt-dlp -f 'best[height<=720][ext=mp4]' -o '%(title)s.mp4' "<youtube-url>"
```

**Caveat**: most YouTube/TikTok content is copyrighted. For personal /
research use this falls under fair use in most jurisdictions, but you
**cannot redistribute the resulting renders** unless the source itself
was uploaded under a permissive licence (CC, public domain) or you have
permission from the creator. Look for "Creative Commons" videos via
YouTube's filter to find truly free content.

## Picking the right clip for blob-tracker

Different detectors want different footage characteristics:

| Source quality | Recommended detector |
|---|---|
| Static camera, things moving across frame | `motion-diff`, `mog2`, `knn` |
| Camera pans / drifts (handheld, time-lapse) | `flow` |
| Bright spots on dark bg (fireworks, stars) | `simple-blob`, `dog`, `circles` |
| Solid-coloured subjects (flowers) | `color-hsv`, `color-cluster` |
| Outline-driven (line drawings, ink) | `edge`, `contour-area` |

For the bundled clips:

- `bee-city.mp4` → `mog2 + centroid-trail,network` (bees moving on flowers)
- `seeds-and-dispersal.mp4` → `simple-blob + glyphs,heatmap` (macros)
- `fireworks-vlog.mp4` → `simple-blob + crosshair,letters` (bright bursts)
- `design-for-dreaming.mp4` → `flow + spatial-echo,silhouette` (motion + colour)
- `duck-and-cover.mp4` → `motion-diff + corner-ticks,cctv-zoom` (classic look)
