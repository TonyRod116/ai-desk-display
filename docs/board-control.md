# Your display's local control room

With the monitor running on your computer, open
**http://127.0.0.1:8787/board** or choose **Desk display** from the usage
dashboard. The page and the display communicate through your computer on the
local network; they do not need an external dashboard service.

Choose any of the eight scenes, set animation speed to **Slower**, **Normal**
or **Faster**, and select **Never**, **30 min** or **1 hour** for automatic
rotation. When rotation is enabled and the clock is synced, the display changes
on the hour or half hour, rather than counting from when you clicked. The
display saves the scene, speed and rotation, including across restarts. On
firmware 27 and newer the speed is saved separately for each screen slot, so changing
Mario's speed does not change Paradise, for example. Firmware 26 uses one speed
for all scenes. Speed changes how fast a scene moves; it does not set its frame
rate.

Each of the eight slots also has a **Change screen** button. It opens a local
visual library with previews of the current screens and earlier versions, including Deep Space,
Game Boy Pocket, Prism, older Code Forge and Neon City designs, and the original
Paradise beach. Choose the slot and the version you want, then confirm
**Replace screen**. The original remains in the library and can be restored
later. A slot keeps its animation speed when you replace its screen.

Library previews use the latest locally cached readings, including for unassigned
and queued screens; unknown or expired readings remain unknown. Confirmed screens
show their delivered preview. Open thumbnails refresh once a minute. The display
uses your actual local readings once the screen has been delivered. A green **Sending data** indicator means the computer is
currently communicating with the display; it is not a delivery confirmation.
**Queued** means the choice was saved on the computer and has not yet been
confirmed on the display. The monitor retries when the display reconnects.
Scene choices survive restarts on the computer; no third-party server is used.

Both pages have an **EN / ES** language selector. English is the default;
the browser remembers your choice on that computer. It does not change the
language of the images on the physical display.

The optional **Violet Horizon** and **Neon District** scenes use local photos.
The weekly quota remaining lights the two central towers in Violet Horizon and
the two rooftop figures in Neon District: pink for Codex, blue for Claude.
Separate neon labels show the values, or Codex credits when its weekly quota is
exhausted and a verified balance is available. Violet Horizon's clouds and city
lights and Neon District's illuminated signs animate independently on the display,
without streaming video. To use your own photos on another
installation, save JPEGs as `violet-horizon.jpg` and `neon-district.jpg` inside
`~/.local/share/ai-desk-display/cyber-scenes/`. The matching scene appears in
the library when its image exists; the pictures are not uploaded anywhere.
If an image for a selected scene is removed, the slot is preserved and a
missing-image message appears until the image is restored.

In the **Usage dashboard**, a verified, exhausted Codex weekly allowance is
replaced by the remaining extra-credit balance when that balance is available.
An unknown balance is shown as `?`, rather than an estimate. Extra credits and
the saved-reset hearts are separate things.

Under **Dashboard appearance**, choose **Screen library** to show any current
or retained screen on the computer page. Screens assigned to the device come
first; earlier versions follow. This choice is remembered in this browser and
does not alter the device or any of its eight slots. The screen uses the same
locally cached readings as device previews, and animated screens play when
available; the detailed usage cards remain below it. Previews update once a
minute while the page is open and hide if the local monitor disconnects. To
avoid leaving outdated numbers on the selection thumbnails, the library pauses
after two minutes and offers to reload them. Open
**Desk display** to change the physical screen instead.

Under **Touch controls**, choose how long to hold before cycling rotation modes
(1–4 seconds) and opening the connection screen (5–10 seconds). The defaults
are 2 and 5 seconds respectively. Release your finger to perform the action;
a short tap still changes scenes. The screen shows the action that will happen
when you release. These settings require firmware 27 or newer and are remembered
after a restart.

Animated scenes also move in the current-screen view, slot cards and library.
The computer generates a compact preview from the page already in memory; it
does not request video frames from the display. Previews use normal animation
speed and need not be in sync with the physical screen. They are generated on
demand, kept in memory, and stay still when the browser requests reduced motion
or animated WebP is unavailable. Screens designed without animation stay still.
The control room refreshes its status every 15 seconds and its previews every
minute. It can be closed after changing settings. Keep the monitor running for
fresh usage data and clock updates.
Faster motion can look less smooth on very detailed scenes, depending on the
display hardware.

The connected display must be paired with the monitor. Screen selection works
on compatible older firmware; speed and rotation controls require firmware
reporting `board_controls: 1` (AI Desk Display 26 or newer). Installing firmware
still requires a physical press and release to open the connection screen, for
the configured connection duration (5 seconds by default), followed by the
authenticated update. If the panel reports that the
display is offline, check its power, Wi-Fi and saved local address. Changes are
reported as saved only after the display confirms them.
