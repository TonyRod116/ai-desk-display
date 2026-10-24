# Cockpit: deep-space quota watch

![Cockpit with fictional usage readings](images/cockpit.gif)

Nebulae, a distant galaxy, a ringed ice planet and independently twinkling stars. A small UFO crosses the clear upper sky, dims as it leaves, then takes a break before its next visit. It's a lot of space for a 320×240 screen.

The large gauges show **weekly quota remaining** for Codex and Claude. Smaller rings keep Claude's five-hour allowance separate; reset indicators stay readable while the UFO passes overhead. Missing quota data remains unknown.

The UFO has **32 steps at 140 ms** intervals. The firmware updates its small sprite and the stars locally, so flying past doesn't require account queries or full-screen uploads. Firmware without native sprite support can use the star-only effect; the static fallback is also retained.

Start in `token_tv/board_space.py` and `token_tv/board_pages.py`. Preview with fictional readings:

```bash
python scripts/render_gallery.py --out preview
python scripts/render_animations.py --out preview
```

The GIF generator needs `g++`. [Full-color still](images/cockpit.png) · [All eight screens](../README.md#eight-screens-zero-boredom) · [Hardware guide](hardware.md).
