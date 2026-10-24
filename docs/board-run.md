# Token Run

A little coastal arcade escape for your desk: a red convertible, three lanes,
turquoise water, palms, windsurf sails and a seaside resort. The coast and road
share a horizon, and the shoreline reaches toward you alongside the asphalt.
The car has round tail lamps, mirrors, deck louvres and two riders enjoying a
considerably better commute than yours.

![Token Run still image with fictional usage](images/dials.png)

![Token Run captured from the firmware animation engine](images/dials.gif)

The scene is original art drawn locally in Python/Pillow, inspired by the
composition and colors of [SEGA's Out Run](https://archives.sega.jp/segaages/outrun/).
It includes no game sprites, screenshots, music or game code.

## The useful bits

The two dials show **weekly quota remaining**: Codex on the left, Claude on the
right. Twenty outer blocks run from red through amber to green as more quota
becomes available. The three chequered flags are saved resets, not extra quota;
a small dot marks unknown or old reset inventory. Claude's two inner rings show
its five-hour quota and time remaining when those readings are available.
Unknown usage stays unknown.

The road, kerbs, lane marks, palms and reflector posts advance in perspective.
Three cars hold their lanes ahead, while the convertible settles slightly on
its suspension. The two large resort palms on the right drift gently along the
bend, taking sixteen road cycles to move out and return without a jump. The nearer
palm travels further than its distant neighbor. The fixed palm above the left
sea is gone, leaving the sails and coastline clear. A gull still flaps overhead;
clouds and water glints keep their appearance in the static backdrop. The
existing gentle CRT treatment and hard 2×2 pixels complete the look.

## Try it locally

The scenery lives in `token_tv/board_drive.py`; the dials and scoreboard live in
`token_tv/board_dials.py`. Render every screen with fictional readings:

```bash
python scripts/render_gallery.py --out preview
python scripts/render_animations.py --out preview
```

Open `preview/dials.png` or `preview/dials.gif`. The animated preview runs the
actual firmware engine locally and needs `g++`; it doesn't contact an account
or a display. Its 120 ms sampling matches the stored scene's native cadence;
the GIF spans the complete 7.68-second joint loop of the road, palms and gull.

On compatible firmware, four sprites animate entirely on the board. The scene
uses 39,960 bytes of its 40,000-byte animation budget and a 193,576-byte complete
page. No continuous frame streaming or new firmware is required for this update.
The fallback for a display without animation support is the first complete pose.
Palms update every 480 ms while the road keeps its 120 ms cadence, so the slow
layers don't repeatedly restore tall rectangles on the fast road clock.

Page uploads and verified readback allow up to 60 seconds per socket operation:
animation-heavy scenes can take longer than the former 20-second limit. Control
requests keep their 20-second limit. Pairing, no-proxy routing and byte-for-byte
verification are unchanged.

Tests check the coast, seamless loop, quota masks, sprite restoration bounds,
static fallback and size limits, and run the real C++ engine with sanitizers.
See the [screen gallery](../README.md#eight-screens-zero-boredom) and
[hardware guide](hardware.md) for the other scenes and supported boards.
