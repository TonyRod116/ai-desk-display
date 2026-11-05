# Hyrule Quest

![Hyrule Quest with fictional usage readings](images/quest.gif?v=quest-1)

Take a tiny walk by the river while two glowing crystals watch your AI limits.
The left crystal represents Codex, the right one Claude; their fill follows the
verified weekly allowance remaining. The top panel includes reset times, saved
resets when known and Claude's session information when available. Missing
readings stay unknown. With supported firmware the traveller, water and fairy
animate on the display.

The included scene has an **original traveller drawn by the project** and works
without any game files. You can optionally provide your own local sprite strip
at `~/.local/share/ai-desk-display/zelda-local/link-walk.png`: a transparent RGBA
image **192 × 26 pixels**, containing eight **24 × 26** poses side by side;
the first four face right and the last four face left. If it is missing or
invalid, the bundled traveller is used. Use artwork you have permission to use.
The project does not ship, fetch or require a ROM or extracted game sprites.

Generate the included scene and animation with made-up readings:

```bash
python scripts/render_quest_preview.py --out preview
```

This preview uses the bundled artwork even if you have local custom art. The
animation simulator needs `g++`; it does not contact an account or a display.
