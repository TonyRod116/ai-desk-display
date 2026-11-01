# Platform World · page 7

An original pixel-art platform level inspired by Super Mario World, rendered at the board's native 320 × 240 resolution. The animation below shows a custom local art set with **fictional sample data**. A different original-art version is included without the optional files.

![Animated platform scene with sample data](images/cockpit.gif?v=c11b1ebc70)

The top scoreboard shows each provider's remaining **weekly** quota and time to its weekly reset. Old readings are marked `OLD`; unknown values are dashes. The three little coins represent saved resets: bright for available, dim for unavailable, with a subtle dot when unknown or old. Claude's two smaller rows show its five-hour session quota and time remaining, and are omitted when that session is unknown or old. When an exhausted Codex week has a verified credit balance, credits replace its percentage. None of these values is invented by the scene.

Firmware 20 can also display an optional, privately supplied art set with eight 56 × 64 mounted-character poses, a coin and a moving shell. Source assets stay on the user's computer; this repository does not include or download the original game or separate game sprite files. The preview above depicts a customized example, not a license to reuse its artwork. The display stores the finished scene locally and continues animating without streaming frames. If those private files are missing or damaged, the host automatically uses the firmware 19 scene. The movement is a short, scripted display animation, not the original game's engine.

Firmware 21 advertises `scroll:4` and moves the original-art landscape across the entire screen, including behind the outlined, stationary scoreboard. Its compact transparent overlay preserves the live numbers, their unknown/old states, the session bars and the verified credit badge. The board continues rendering locally; the extra scenery is not streamed as video. Older boards keep their existing formats, and missing private artwork still falls back to the bundled scene.

Firmware 25 draws the original coin released by a hit block at the same 3× scale
as the coins in the landscape, centred over that block. It rises fully above the
block before disappearing. The scripted jump is unchanged.

The optional files live in `~/.local/share/ai-desk-display/smw-original/`: an RGB `world.png` (512 × 96), eight transparent `rider-0.png` … `rider-7.png` poses (28 × 32 each), transparent `coin.png` (8 × 16), `shell.png` and `used-block.png` (both 16 × 16), two RGB `block-bg-0.png` and `block-bg-1.png` backgrounds (16 × 18), plus a 512-byte `heights.bin`. This is a local customization format; you must provide suitable artwork yourself. Firmware 20 advertises `scroll:3`, while firmware 19 and earlier keep receiving their compatible formats.

With firmware 19 and the explicit `scroll:2` capability, the rider is 48 × 54 pixels and the camera is closer. The rider clears each enemy in a continuous jump, then bumps the underside of a block and releases a coin. The block, coin and characters remain inside a seamless 23.04-second landscape loop; the scoreboard stays fixed and a quota refresh preserves the camera position. The indexed landscape and five rider poses are stored on the board and drawn locally, without frame-by-frame network traffic or extra flash writes. The panel's real perceived smoothness still needs to be judged on the physical device.

Firmware 17–18 advertise `scroll:1` and receive their original 30.72-second camera loop with four rider poses. A board only gets the larger scene if it explicitly advertises `scroll:2`; the host does not guess from the firmware version.

Firmware 18 adds intermediate camera and jump positions every 60 ms, while keeping the same travel speed and the exact same stored animation format. During a page transfer it limits drawing to at most one frame per 100 ms so the board can continue receiving data and responding to touch. Firmware 17 can still read the same page at its original 120 ms cadence.

Firmware 29 adds one-pixel intermediate positions every 15 ms for the zoomed
scenes, without changing the camera speed, jump duration, block contact or
landscape loop. It reuses repeated background rows and sends larger bands to
the display, while retaining the transfer-time budget. These timeline positions
are not a guaranteed frame rate: the panel and network work can take longer.

Earlier animation-capable firmware still receives the previous four-sprite level; boards without animation get a still. The PC only sends the scrolling format when the board explicitly advertises `scroll`, never by assuming support from a version number.

The former space scene remains in `token_tv/board_space.py` and can be restored locally. Slot seven keeps its internal `cockpit` identifier for compatibility. Firmware 17 is required for the continuous camera; older boards can still display the earlier animated or static version.
