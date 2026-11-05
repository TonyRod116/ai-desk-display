# Hyrule Quest

![Bundled Hyrule Quest demo with fictional usage readings](images/quest.gif?v=quest-2)

*This preview shows the bundled original-art demo. It is not the maintainer's
custom Zelda scene, which uses locally supplied artwork.*

Take a tiny trip to a pixel-art village while your AI limits become life bars.
The left meter represents Codex and the right one Claude; each fills from the
bottom according to the verified weekly allowance remaining. Next to each are
the percentage, time until reset and up to three saved-reset hearts when known.
Claude's five-hour indicators and Codex credits appear when available; missing
readings stay unknown. With supported firmware, the bundled traveller cuts a bush
and finds a little gem while a fairy and a butterfly move through the scene.

The included village and traveller are **original artwork drawn by the project**
and work without any game files. The preview shows this included version; a
private custom setup may look different. You can provide artwork locally in
`~/.local/share/ai-desk-display/zelda-local/`:

- `link-walk.png`: an optional transparent **192 × 26** strip with eight
  **24 × 26** poses, the first four facing right and the rest facing left.
- For a completely custom scene, provide all three: `landscape.png` (**320 × 240**),
  `action.png` (**232 × 30**, eight **29 × 30** RGBA poses) and `guard.png`
  (**192 × 24**, eight **24 × 24** RGBA poses). The action and guard strips
  appear at fixed positions and follow the scene's loop.

If the three custom-scene images are missing or invalid, the included village
is used with the optional traveller strip, falling back to the bundled traveller
when necessary. Use artwork you have permission to use. The project does not
ship, fetch or require a ROM or extracted game sprites.

Generate the included scene and animation with made-up readings:

```bash
python scripts/render_quest_preview.py --out preview
```

This preview uses the bundled artwork even if you have local custom art. The
animation simulator needs `g++`; it does not contact an account or a display.
