# A new life for an old tablet

Turn a portrait tablet into a little window onto your desk: animated scenes, the time, Claude and Codex usage, and computer readings. **You do not need a NerdMiner or ESP32 board**; use the tablet alone, the small display alone, or both. A computer still runs the monitor and readers for fresh data.

## Try it without an account

Install the project as described in the [README](../README.md#try-it-without-a-display-or-an-account), then run:

```bash
python scripts/sample_tablet.py
```

Open **http://127.0.0.1:18861/** on the computer. This is a local demo: its quotas, disks, board and weather are fictional, and it does not contact your accounts or hardware. Its temporary scenes are simple test pictures, not the finished personal backgrounds shown on my devices. It cleans up its temporary files when stopped with `Ctrl+C`.

## Set up your tablet

1. On the computer, [create your private configuration](setup.md#1-create-your-private-configuration), then [start the monitor and readers](setup.md#3-enable-fresh-readings). If you only want the tablet, skip board pairing and firmware; you do not need a board address.
2. In another terminal, start the tablet service:

   ```bash
   python -m token_tv.tablet_server
   ```

   It needs Python, Pillow and `openssl`; the reference host is Linux or WSL. The service chooses a private network address. If you have multiple interfaces, `python -m token_tv.tablet_server --help` shows how to select one.
3. On the **computer**, open **http://127.0.0.1:8666/** and choose a unique password of at least ten characters. The setup page shows the tablet's HTTPS address and certificate fingerprint.
4. On the tablet, connected to the same trusted network, enter that complete address **including `https://`**. The certificate is generated on your computer, so the browser will not recognise its issuer. Compare its fingerprint with the setup page before trusting it; a warning alone does not establish that you reached the right computer. Sign in with the password you chose.
5. Open the scene selector and try picture mode by tapping the clock. Swipe left or right to change scenes, or double-tap the picture to open the selector. The settings button controls language, rotation, night mode, motion and more.

The computer and monitor must be running for fresh quota readings; the tablet cannot query the providers by itself. An unavailable or expired reading is displayed as unknown. Codex's extra credits replace the percentage only when its verified week is exactly exhausted and its confirmed balance is positive. Missing, zero or negative balances keep the quota display; any positive quota remainder stays quota. The bar always represents the weekly allowance. Claude's spending cap is not a prepaid credit balance.

Computer metrics depend on the operating system and sensors: Windows/WSL and an NVIDIA GPU are the reference setup. Multiple fixed disks are listed separately. CPU temperature needs a supported sensor; the optional MSI helper and manually triggered memory trim have their own [computer-controls guide](tablet-host-controls.md). On WSL, the collector can recover a stale local Windows relay; unavailable readings stay unknown. A virtual cloud-drive volume may show cache capacity instead of cloud quota.

## Add some scenes

The repository includes code to draw several original tablet scenes. Generate the isometric city, coastal drive and fighting scene into the tablet's local scene folder:

```bash
SCENES="$HOME/.local/share/ai-desk-display/tablet"
python scripts/prepare_game_city_iso.py --out "$SCENES" --manifest
python scripts/prepare_game_token_run.py --out "$SCENES" --manifest
python scripts/prepare_game_fighting.py --out "$SCENES" --manifest
python scripts/prepare_game_handheld.py --out "$SCENES"
```

Isometric City uses procedural artwork from this repository. Its buildings show weekly quota, and its lighting follows the configured location and time. Traffic, ferries, helicopters, markets and stadium events animate locally; if you enable weather, the city can reflect the current conditions reported by the existing weather feed. Weather is optional and off by default.

These commands run locally and can take a while. The handheld demo uses simple original stand-in graphics and never requires a cartridge; its preparer refuses to overwrite an existing handheld scene. Reopen or reload the tablet page after they finish. The surf renderer can use a compatible locally prepared backdrop; the photo and cinematic tools likewise need images or footage you have permission to use. They are not generic one-click animation tools. See the scripts' `--help` for their inputs. My personal backgrounds, videos and game artwork are not distributed with the repository.

After updating the project code, rebuild and update the Android app so it receives the new interface and scene engine. Regenerate changed scenes, then wait for the complete offline pack to finish saving before disconnecting the tablet. The browser version uses the updated code after a page reload.

You can also prepare a slideshow from your own pictures with `python scripts/prepare_tablet_photos.py --help`. Source media stays on the computer; the Android app can save the prepared resources privately on the tablet. Its gallery only lists prepared scenes. [Offline operation and resource updates](tablet-offline.md).

## Make it feel like an appliance

A browser can enter full screen and request that the screen stays awake, although Android may still restrict that. The [Android app](tablet-app.md) adds a bundled interface and persistent saved scenes, keeps the display awake while open, pins the computer's certificate and restores full screen after a reload. Wait for **Settings → APP → Ready offline** before testing with the tablet's Wi-Fi off. You build it for your own computer; no preconfigured APK or signing key is distributed here.

The repository does not automatically start the monitor or tablet service when the computer boots. Arrange startup for your own system if desired. If the computer's local address or certificate changes, follow the Android guide to rebuild the app; reserving the computer's address in your router can help.

## Privacy and network notes

- The setup page is local to the computer. The tablet service is password-protected and listens on the selected private network interface; do not expose it to the Internet or configure port forwarding.
- The tablet receives filtered usage and computer readings. Its optional small-screen remote can send a limited set of commands to the local board control room; it is not an administrative proxy.
- Live readings are not saved in the Android resource cache. Offline scene choices and display settings are saved locally and synchronize as preferences only; controls that need the PC are not replayed later. Remote screen buttons show dimmed previews read from the monitor's existing cache, without asking the physical board to render new images.
- The account readers still contact their official providers. The optional weather feature is **off by default**; enabling it sends a rounded location to Open-Meteo. Set your location in the tablet settings first.
- Password hashes, sessions, certificates, keys, local configuration, your artwork and actual readings stay outside the repository. Avoid sharing screenshots with real quotas or personal information.
