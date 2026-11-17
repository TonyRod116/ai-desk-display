# Blue Lightning flight scene

The tablet has a portrait flight scene with coordinated aircraft, terrain and cloud movement. It is decorative: the normal interface owns the clock and usage readings, and no flight action changes account data. The engine is an adaptation inspired by the Atari Lynx game, not an emulator or an official port.

The public demo is complete without a cartridge. Its aircraft and clouds are original geometric stand-ins drawn locally with Pillow; terrain, water, ground objects and effects are procedural. The aircraft banks, climbs and dives, while enemies approach or pass from behind. Three altitude levels change the view of the terrain and clouds. The ordinary fictional tablet demo includes this scene in its scene chooser.

To preview just the flight scene without preparing the other backgrounds, choose a new empty folder:

```bash
python3 scripts/prepare_game_blue_lightning_demo.py --out preview/flight
python3 scripts/sample_tablet.py --port 18861 --scenes preview/flight
```

Open `http://127.0.0.1:18861/` and choose **Blue Lightning**. Readings and computer details in this sample are fictional. The preparer refuses to replace existing flight assets, so it can also add the original demo to a scene folder without overwriting a customized flight scene.

An optional separate extractor, `scripts/prepare_game_blue_lightning_private.py`, can prepare owner-supplied cartridge artwork for a private local installation. It supports one exact cartridge version in a ZIP: a different revision or archive layout is rejected. Its reference must contain the supported straight-flight sprite at the expected position and scale, with a palette that passes the consistency check; an arbitrary gameplay screenshot is insufficient. It creates a separate private output directory.

The original enemy and cloud families additionally require `--enemy-metadata` and `--cloud-metadata` inputs with privately captured palettes and observed mirrors. This repository does not provide or generate those trace inputs. Without them, the engine uses procedural or legacy alternatives for the missing families. None of the cartridge, reference, palette inputs or extracted graphics are included, downloaded or needed by the public demo. The server and Android app never read a cartridge. Do not assume the code's MIT licence grants rights to third-party game artwork.

The extractor preserves previous atlas rectangles when adding pose families, writes transparent pixel art with anchors, and binds its PNG and JSON with `atlas_sha256`. The engine validates optional families against the loaded image and retains procedural or legacy fallbacks when resources are absent or incomplete. A caller publishing custom files must validate the pair and preserve unrelated scene entries; the preparer does not publish or restart a service.

The unit and browser fixtures use synthetic cartridge streams and invented graphics. Browser checks prove the local web rendering and controls tested; they do not establish appearance or performance on a physical Android tablet.
