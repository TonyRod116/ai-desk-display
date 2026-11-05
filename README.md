<div align="center">

# AI Desk Display

### Your AI limits deserve more personality than a progress bar.

Turn a little desk display into an animated home for your **Claude and Codex usage**.

[![Python 3.10+](https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python&logoColor=white)](pyproject.toml)
[![License: MIT](https://img.shields.io/badge/code-MIT-green)](LICENSE)
[![Local rendering](https://img.shields.io/badge/rendering-local-7c3aed)](#local-not-magic)

[Download ZIP](https://github.com/TonyRod116/ai-desk-display/archive/refs/heads/main.zip) · [The screens](#eight-screens-zero-boredom) · [Try it first](#try-it-without-a-display-or-an-account) · [Set it up](#okay-i-want-this-on-my-desk) · [Make it yours](#make-it-yours-with-or-without-ai)

</div>

I had a NerdMiner V2 sitting on my desk. After working out that finding a Bitcoin block could take an *average* of about **19 billion years** at an optimistic 1 MH/s,[^mining-math] I figured it might appreciate a career change.

Now it tells me when I'm running out of AI instead. Progress?

## Eight screens, zero boredom

Pick eight screens for your display and change them whenever you like. Here are a few favourites:

| | |
|:---:|:---:|
| **Game Boy**<br>Green pixels and a little nostalgia.<br>![Game Boy display with simulated usage updates](docs/images/game-boy.gif) | **Paradise**<br>A tropical break between prompts.<br>![Paradise beach with an animated shoreline and sailboat](docs/images/paradise.gif?v=8604eaf692)<br>*Optional local artwork* · [Setup](docs/board-paradise.md) |
| **Tidal Rush**<br>Catch a wave; ignore the token count for a second.<br>![Tidal Rush surfer riding an animated wave](docs/images/surf.gif?v=surf-2)<br>[Still](docs/images/surf.png?v=surf-2) · [Scene guide](docs/board-surf.md) | **Token Run**<br>A coastal drive with quotas on the dashboard.<br>![Token Run animated coastal drive](docs/images/dials.gif)<br>[Still](docs/images/dials.png) · [Scene guide](docs/board-run.md) |
| **Versus**<br>Claude vs Codex. Run out of quota? KO.<br>![Versus animated retro fighting game](docs/images/arcade.gif?v=arcade-2)<br>[Still](docs/images/arcade.png?v=arcade-2) · [Scene guide](docs/board-versus.md) | **Platform World**<br>A side-scrolling trip with Mario and Yoshi.<br>![Animated platform scene with Mario and Yoshi](docs/images/cockpit.gif?v=7887cab24d)<br>*Optional local artwork* · [Setup](docs/board-platform.md) |
| **Neon District**<br>Two rooftop figures glow with your remaining usage.<br>![Neon District animated cyberpunk city](docs/images/neon-district.gif?v=aa28bc1e23)<br>*Optional local artwork* | **Quota City**<br>An isometric skyline that changes with your limits.<br>![Quota City animated isometric skyline](docs/images/countdown.gif) |

All readings in these previews are **made up**. Some images show optional artwork that isn't included in a fresh download. Paradise and Platform World also have bundled alternatives; Neon District needs its own local image. The Paradise GIF shows an earlier wave; the current optional version reaches farther and moves more slowly. No game ROMs or separate extracted game sprites are included. See [asset notes](ASSETS.md) for provenance.

**Hyrule Quest** is in the library too, with life meters, hearts and an animated village scene. The repository includes an original-art demo; the custom Zelda artwork used on my display stays local and isn't included. [See the Quest guide and demo](docs/board-quest.md).

GIFs have a limited colour palette; the display receives RGB565 frames. Game Boy is normally static: its GIF simulates changing usage.

## What does it show?

The display turns account information into something a bit more fun:

- **Weekly usage remaining** for Codex and Claude, with the time until each reset.
- **Claude's five-hour limit**, where that reading is available.
- Up to **three saved-reset hearts** per provider when the balance is known.
- **Codex extra credits** when the weekly allowance is exhausted and a verified balance is available.

What you can see depends on your plan, clients and what the providers expose. Missing or expired readings stay unknown; the project doesn't guess a reset balance from your percentage.

On compatible hardware, the board plays its animations locally between updates. Your computer provides the fresh readings, so you don't need to keep an AI chat open or ask an AI to redraw the screen.

## A screen library, not just eight slots

The local **Desk display** page lets you preview the scenes, replace any of the eight slots and drag the tiles into a new order. Earlier designs stay in the library, so you can bring back Deep Space, Game Boy Pocket, Prism or an older city whenever you want. Violet Horizon and Neon District are available when you supply their local artwork.

![The local screen library with fictional readings and the bundled Quest demo](docs/images/screen-library.png?v=quest-2)

*This library example uses fictional readings and the included Quest demo.*

On compatible firmware, the same page lets you set animation speed, automatic rotation, touch-hold durations and night-mode dimming. A change can be queued while the board is offline; the page shows when it has been delivered. Animation speed changes how fast a scene moves, not its frame rate.

The **Usage dashboard** can show any available scene on the computer, above its detailed usage cards. Choosing a dashboard appearance doesn't change the screen on the physical display. Both web pages offer English and Spanish, with English as the default.

With the monitor running, open **http://127.0.0.1:8787/board** or choose **Desk display** from the dashboard. [Explore the control room](docs/board-control.md).

### One tap, another world

The default touch gestures take effect when you release your finger:

| Gesture | Action |
|---|---|
| Quick tap | Go to the next screen. |
| Hold for 2 to less than 5 seconds | Cycle between fixed, every 30 minutes and every hour. |
| Hold for 5 seconds or more | Open the connection screen. |

When the clock is synchronised, rotation happens on the hour and half hour, or on the hour only. A discreet indicator shows the selected mode. Supported firmware remembers the chosen screen and mode after a restart; the hold times can also be changed in the control room.

## Try it without a display or an account

You can render the bundled scenes with **fictional readings** before connecting anything. You'll need Python 3.10 or newer:

```bash
git clone https://github.com/TonyRod116/ai-desk-display.git
cd ai-desk-display
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
python scripts/render_gallery.py --out preview
```

Open `preview/gallery.png` to explore. For animated previews, install `g++` and run:

```bash
python scripts/render_animations.py --out preview
python scripts/render_quest_preview.py --out preview
```

The Quest command renders its **bundled demo**, even if you have custom artwork. These scripts don't contact your accounts or a display; installing dependencies does require a download.

On Windows, create the environment with `py -m venv .venv` and activate it with `.venv\Scripts\Activate.ps1`. Linux or WSL is the reference environment for the full account-reader setup; native Windows and macOS haven't received the same level of testing.

## Okay, I want this on my desk

The reference device is the **2.8-inch NerdMiner V2 touchscreen based on ESP32-2432S028R**, also known as the Cheap Yellow Display (CYD), at 320 × 240. NerdMiner V2 is available on other boards too, so check the board and display controller before flashing.

Installing this firmware replaces the mining application. This is still a tinkering project, not a one-click installer:

1. **Check the hardware.** Follow the [hardware guide](docs/hardware.md) and build the correct ILI9341 or ST7789 version from the [firmware instructions](firmware/board/README.md).
2. **Install the host and sign in.** Install the project as shown above, then sign in to the official Claude Code and/or Codex CLI with your own accounts.
3. **Pair and start the readers.** Follow the [setup guide](docs/setup.md) for the private configuration, board pairing, monitor and provider readers. Use only the providers you need.
4. **Open the local dashboard** at `http://127.0.0.1:8787` while the monitor is running, and choose your screens.

For Claude's saved-reset balance, the optional [local browser extension](docs/claude-bank-local.md) needs its own private pairing. Available readings can change with the provider or plan.

**Updating an existing board?** Follow the [firmware guide](firmware/board/README.md). For a Wi-Fi update, physically open the connection screen first: hold and release for the configured duration, five seconds by default.

The repository doesn't install startup services automatically. If you want the monitor and readers to start with your computer, see the [Windows/WSL startup notes](docs/windows-startup-local.md) and adapt them to your machine.

A GeekMagic SmallTV Ultra uses a different integration and does **not** run the ESP32 touchscreen firmware. See the [SmallTV guide](docs/smalltv-ultra.md).

### Keep the connection steady

A router can give the board a different local IP after a restart, leaving the computer looking at the old address. Reserving its address in your router helps prevent that:

1. Hold the board's screen for **5 seconds and release** to see its IP address. Older firmware may use a shorter hold.
2. Find that IP in the router's device list and note the board's MAC address; its name may start with `esp32`.
3. Add a **DHCP reservation** (sometimes called static DHCP) for that MAC address and the current IP. Don't use an address already reserved for another device.

This is a local-network setting, **not port forwarding**. If the board is unreachable for ten minutes, the monitor may automatically search its saved local subnet, at most once an hour. That search sends the pairing token to candidate devices over unencrypted HTTP, so an impersonating device could receive it; use a trusted network. Keep the monitor running for updates. If you see `NO DATA`, the [troubleshooting guide](docs/setup.md#troubleshooting) walks through the address, power and reader checks.

## Local, not magic

- The computer renders screens and sends them over your local network. The web dashboard listens on localhost.
- Enabled readers contact the **official providers** for current usage. Local rendering doesn't make those account requests work offline.
- The computer and monitor need to be running for fresh readings. The board can animate stored scenes while the host is away, but marks stale data unavailable.
- Startup, account sign-in and the optional extension are yours to configure; the repository doesn't include your credentials or pairing files.
- The board connection uses unencrypted HTTP. Keep it on a trusted network and don't expose the board or dashboard ports to the Internet.

## Make it yours, with or without AI

This project is meant to be changed. Ask an AI to tweak colours, rearrange a meter, invent a scene or adjust an animation. A lot of these screens came from exactly that process: try something, look at it, then say “okay… but more cyberpunk.”

You can also use AI to help adapt the project to **another display**. Rendering and device communication are separate starting points, but another resolution or connection may still require a new driver, protocol changes or different firmware. Test on your own hardware.

A useful first prompt:

> Read AGENTS.md and the Tidal Rush renderer. Give the scene a purple sunset palette, keep the usage readings intact, and make a preview with fictional data before touching the display or my accounts.

| I want to change… | Start here |
|---|---|
| Screens and their order | `token_tv/board_pages.py` and `token_tv/board_*.py` |
| Scene library and control room | [Control room guide](docs/board-control.md) and `token_tv/board_scenes.py` |
| Neon City and its bridge lights | [Neon City guide](docs/board-neon-city.md) |
| Board animation | `token_tv/board_anim.py`, `token_tv/board_wave.py` and `firmware/board/` |
| Classic clock faces | [Make a face](docs/clock-faces.md) |

## Made something cool?

I'd love to see it. Share a new screen, display adaptation or improvement in an [issue](https://github.com/TonyRod116/ai-desk-display/issues). Please use fictional readings in screenshots and keep account and pairing details private.

Run the local test suite with:

```bash
python -m unittest discover -s tests
```

Some firmware tests need a C++ compiler; JavaScript checks need Node. `scripts/e2e_live.py` is intended for a real device and isn't a routine test.

## Credits and license

Created by **Tony**, with a lot of help from **Claude Code and Codex**. Original inspiration and some retained components: [TokenTV, by click6067-ship-it](https://github.com/click6067-ship-it/token-tv); its MIT notice is preserved in [LICENSE](LICENSE).

Code is licensed under [MIT](LICENSE); fonts keep their own license files. See [ASSETS.md](ASSETS.md) for artwork provenance and permissions. This is an independent project and isn't affiliated with OpenAI, Anthropic, Nintendo or Atari.

If it ends up on your desk, mission accomplished. 🌊

[^mining-math]: Back-of-the-envelope estimate checked on 2026-10-23: Bitcoin difficulty **140,577,680,051,919.6**, from [mempool.space's mining API](https://mempool.space/api/v1/mining/hashrate/3d). Expected years ≈ `difficulty × 2^32 ÷ hashes_per_second ÷ 31,557,600` = **19.13 billion** at an assumed **1 MH/s**. That's a generous illustrative rate, not a measurement of this board; modified CYD firmware [reports roughly 990 kH/s](https://github.com/HenrysCat/NerdMiner-Modded). The calculation assumes continuous operation and unchanged difficulty forever. It's a statistical mean, not a countdown or guarantee: a lucky block could arrive sooner, and future difficulty changes the odds. [Solo mining wins a block reward plus fees](https://developer.bitcoin.org/devguide/mining.html#solo-mining), not exactly 1 BTC. The network figure is a dated snapshot; the linked API changes over time.
