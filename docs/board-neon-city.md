# Neon City

A moonlit city, flying cars, warm apartments and far too many neon signs. The bridge has a second job: keeping track of your weekly AI quota.

![Neon City with fictional readings](images/code-forge.gif)

## Read the bridge

- **Codex:** amber lamps on the left half.
- **Claude:** cyan lamps on the right half.
- At 100%, each half reaches the middle. As quota is spent, the lit part retreats toward its outer end.
- Small signs show the remaining weekly percentages. Below Claude, two five-part rows show five-hour quota and time until that session resets.
- At 0%, the relevant circuit goes dark. Missing or stale data shows `--` and sparse neutral lamps, so it cannot be mistaken for either a full or an empty allowance. An expired five-hour session disappears without hiding a valid week.

The tower lights are decorative. They stay on even when you have managed to burn through everything. Someone in this city should still be productive.

## Artwork and animation

The [1448×1086 artwork](art/neon-city-bridge-master.png) was created with the built-in image generator from the project's authorized original city reference. The [exact prompt](art/neon-city-bridge-prompt.txt) is included for further experiments. It preserves the orange rooftop emblem, city canyon, spacecraft and foreground car, with richer facades, neon signs, reflections and an added pedestrian bridge. See [asset permissions](../ASSETS.md).

`token_tv/assets/neon-city-bridge.png` is the 320×240 runtime derivative. The physical panel still has 320×240 pixels; the larger source is useful for adapting the scene to other displays.

Two cars and two small facade neons animate using the board's existing ANIM engine. The paths hide the car loop transitions behind buildings, and each neon has its own timing. Their restoration regions stay clear of the quota instruments. Animation uses 884 bytes; the complete board page is 154,500 bytes. No video streaming or firmware update is required.

The GIF above is captured from the real firmware simulator over 22.4 seconds, with fictional account readings. It uses a shared 256-color palette; the actual board receives RGB565 pixels.

## Tinker with it

The active renderer is `token_tv/board_neon_bridge.py`, in the third board slot (`code-forge`). Preview all scenes without accounts or hardware:

```bash
python scripts/render_gallery.py --out preview
python scripts/render_animations.py --out preview
```

The earlier `board_neon_realistic.py`, `board_neon_smooth.py` and `board_forge.py` variants and their source assets remain in the repository. To try the previous tower-lighting version, change the local import in `board_pages.render_board_pages` to `from token_tv.board_neon_realistic import render_neon_realistic as render_forge`, then adapt the integration test to that renderer.

Tests cover independent left/right depletion, low balances, unknown versus zero, session expiry, first-frame consistency and native animation restoration. The C++ sanitizer test compares 640 complete frames across valid and missing data states. Keep screenshots synthetic and account configuration out of commits.

See the [screen gallery](../README.md#eight-screens-zero-boredom) and [hardware guide](hardware.md).
