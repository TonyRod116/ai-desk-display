# Set up AI Desk Display

This guide uses the **ESP32-2432S028R touchscreen** in the reference setup. Start with the [offline gallery](../README.md#try-it-without-a-display-or-an-account), then follow the [hardware guide](hardware.md) and [firmware instructions](../firmware/board/README.md) for your exact board and controller. Flashing replaces the program already on the board.

The reference account-reader setup runs on **Linux or WSL**. Native Windows and macOS have not received the same level of testing. Your computer and board need to be on the same reachable local network, and the computer needs Internet access for fresh account readings.

## 1. Create your private configuration

Install the project as shown in the README, activate its virtual environment, and install and sign in to the official Claude Code and/or Codex CLI clients you intend to use. Choose the account whose usage you actually want to display. Never share the clients' authentication files.

In a terminal, from the project directory:

```bash
ai-desk-display setup
ai-desk-display doctor
```

`setup` asks for account emails and login locations and creates a private configuration; it will not overwrite an existing one. For the reference local setup, use at most one Claude and one Codex account. Skip providers you don't use. The clock-address question refers to an optional **GeekMagic clock**; leave it blank if you only have the touchscreen board. `doctor` checks the installation without requesting live quota. `doctor --live` does contact providers, so use it only when you want that check.

The default Linux/WSL config is `~/.config/token-tv/config.json`. Keep this file private: after pairing it contains the board's pairing token, as well as account identifiers. Don't post it, copy another person's file, or put credentials into the repository.

## 2. Connect the touchscreen board

With the board powered on, hold its screen for **5 seconds and release** to open its connection screen. On firmware 9 or older, hold for about 2 seconds. Use the address shown there in the first command below; **`192.168.0.60` is only an example**:

```bash
ai-desk-display board --url http://192.168.0.60
ai-desk-display board --check
```

The first command pairs an unpaired board and stores its address and pairing token in your private config. An already paired board must belong to this computer's saved pairing. The second asks the board for its status. If the board says it is paired with a different computer, restore the original private pairing configuration; don't post the token or erase the pairing to work around it.

### Reserve its address in your router

This optional step is recommended: a **DHCP reservation** makes the router keep assigning the same local IP to the board. Without one, the board's address can change while the computer still points at the old one.

1. Note the current IP on the board's connection screen. In your router's connected-device list, find that IP and its **MAC address**; the device may be named `esp32` or similar.
2. Find the router's DHCP reservation or static-DHCP section. Select the board by its MAC address, reserve its current IP, and save. Menu names vary by router. If that IP is already reserved for another device, resolve the conflict before saving.
3. Check that the reservation appears in the router. Reopen the board's connection screen and use `ai-desk-display board --check` to check it is reachable. A normal router or board restart should keep the reservation; a factory reset or a different network can require setting it up again.

This is a local-network setting, not port forwarding. Don't open the board or dashboard to the Internet.

## 3. Enable fresh readings

The reference setup uses a local monitor and separate readers. Edit your private config and add these **top-level JSON properties** alongside the existing `accounts` and other properties. Merge them into the existing object; **do not replace the file with this example**:

```json
{
  "local_only": true,
  "automatic_codex_resets": true,
  "automatic_claude_usage": true,
  "display_enabled": false
}
```

Use `false` for a provider you don't use. `display_enabled: false` stops uploads to an optional GeekMagic clock; it does not disable the touchscreen board. The readers query the official providers and write local observations for the monitor; enabling them means those account requests will recur while they are running. The monitor itself uses the local observations.

From the checkout, with the virtual environment activated, start these in **separate terminals**:

```bash
# Terminal 1: local monitor and dashboard
ai-desk-display run
```

```bash
# Terminal 2: only if using Codex
python scripts/codex_reset_collector.py
```

```bash
# Terminal 3: only if using Claude
python scripts/claude_usage_collector.py
```

For a non-default configuration, pass `--config` with the same private path to each process. The dashboard is at `http://127.0.0.1:8787`. Leave the processes running while you want updates. Supported values depend on the installed clients, your plan and what the providers expose. Unknown or expired data stays unknown rather than becoming a made-up number.

Claude's saved-reset balance additionally needs the [paired local browser extension](claude-bank-local.md). Simply loading its source folder is not enough: pairing is deliberately private. Follow that guide before enabling `automatic_claude_resets`.

## Troubleshooting

### The board says NO DATA

This means the board has stopped hearing from the computer; it doesn't by itself tell you that an account is out of quota.

1. Check that the computer is awake, the monitor is running and the board and computer can reach each other on the local network.
2. Open the board's connection screen and note its current IP. Run `ai-desk-display board --check` on the computer.
3. If the address changed or the check fails, run `ai-desk-display board --url http://192.168.0.60`, **replacing the example with the address you just read on the board**. The command reuses the saved pairing privately for the explicitly identified board; it does not print the token. If the address was updated, restart just your display monitor or its service so it reloads the config, then check again.
4. Reserve the current address in the router as described above. If it still fails, check the board's power and Wi-Fi, and that the correct private pairing configuration is present. Do not reboot your router as a first troubleshooting step.

`ai-desk-display board --find` can search the saved address's local `/24` network. If it finds a paired board at a new address, verify that address on the physical screen and run `board --url` with it; discovery alone cannot prove a device's identity. If several boards answer, identify yours before choosing an address.

### Only Claude or Codex is missing

Check that the corresponding reader is running, the official CLI is signed in to the intended account and its plan is active. Compare with that provider's own usage page. A failed or rate-limited reading can temporarily appear as unavailable; restarting the router won't fix an account or provider error. The readers retry, but access and data availability still depend on the provider. Keep credentials, pairing tokens and private logs out of public issues.

If the board repeatedly restarts, also check its USB power supply and cable. See the [firmware recovery notes](../firmware/board/README.md) before changing firmware.

## Start automatically

The repository **does not install startup services automatically**. You can configure user services for the monitor and the readers on your own system; the [Windows/WSL startup notes](windows-startup-local.md) describe the reference arrangement. Adapt them to your machine instead of copying somebody else's private paths. When the computer is asleep or off, the board can animate stored scenes but cannot fetch fresh readings and will mark old data unavailable.

## Other displays

For a GeekMagic SmallTV Ultra, see [its guide](smalltv-ultra.md). It has different capabilities and does not use the touchscreen board's firmware. Do not flash an ESP32-2432S028R image to a different device.
