# Paradise

The bundled beach works without extra files. Preview it with fictional data:

```bash
python scripts/render_gallery.py --out preview
```

## Optional local beach film

Newer boards can use an optional photo and a compact, animated water strip
prepared on your computer. The original photo or GIF is not uploaded by the
project. Use artwork you have permission to use and keep your original file.

The supplied preparation tool is fitted to a particular **384 × 480 animated
GIF with at least eight frames** and a specific composition. It crops and
stabilises the source, so another image may need adjustments to the tool to look
right. From the checkout, try it in a new directory first:

```bash
python -m tools.prepare_paradise_film ./my-beach.gif --output ./my-beach-prepared
```

Inspect the resulting `background.png`, `water.png` and `boat.png`. When you're
happy with them, copy those three files into
`~/.local/share/ai-desk-display/paradise-local/` and restart the local monitor.
Back up any existing files in that directory before replacing them. The source
GIF and prepared files stay on your computer; if the prepared set is missing or
invalid, the bundled beach remains available.

Firmware 37 samples the water according to the animation clock and spreads small
color changes across the image, so large groups of pixels do not change at the
same instant. On compatible boards the main loop aims for an even 40 ms between
water frames, up to 25 frames per second. The water keeps its 3.2-second cycle
and the boat its 6.4-second cycle at normal speed; the speed control still works.
The source-frame colors and the loop seam remain exact. Older WAVE2 animations
retain their original appearance.

When memory permits, the board caches the sharp photograph in separate bands and
keeps only the needed water-film frames in memory. The film is compacted in place
so loading it doesn't require a second large allocation. Cache allocation leaves
an 80 KiB heap reserve; if memory is tight, playback can use storage-backed
background reads. Animation runs on the board without streaming
video from the computer, and the photo is not reduced in resolution. Actual frame
rate depends on the device and may temporarily drop during screen updates.

See the [screen gallery](../README.md#eight-screens-zero-boredom) and [hardware guide](hardware.md).
