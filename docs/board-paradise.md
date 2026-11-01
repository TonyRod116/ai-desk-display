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

Firmware 30 adds intermediate water positions and reduces per-frame color
calculations. The waves and boat keep their original pace, and animation runs on
the board rather than streaming video from the computer. The actual frame rate
depends on the hardware and may temporarily drop while a screen is being updated.

See the [screen gallery](../README.md#eight-screens-zero-boredom) and [hardware guide](hardware.md).
