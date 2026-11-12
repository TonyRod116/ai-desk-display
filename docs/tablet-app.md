# Optional Android app

The tablet page also works in a browser. The Android app bundles that interface and its scene engines inside the signed APK, then saves prepared scene resources in private app storage. It keeps the screen on while open, adjusts its own brightness at night and trusts only the computer certificate used when the app was built. No provider login or credential files are copied to the tablet.

## Build and install

1. Follow the [tablet setup](tablet.md) and keep its service running. Check its address and certificate fingerprint on the computer's local setup page.
2. Install a compatible Android SDK, build tools and JDK. From the project folder, run `python scripts/build_tablet_app.py`. Use `--help` to select an SDK or JDK if they are not found automatically. The build reads the address and fingerprint from the computer's local setup page; it generates its own private signing key under `~/.local/share/ai-desk-display/tablet/app-signing/`.
3. Sign in from the tablet's browser and open `/app/ai-desk-tablet.apk` on the same HTTPS origin. Android may ask you to allow that browser to install this app; approve the installation on the tablet. An APK is specific to the address and certificate used during its build.
4. Open AI Desk Display. If the computer's address or certificate changes, build and install a new APK using the same signing key. Keep that key private and backed up: Android requires the same signing key for updates.
5. With the computer available, leave the app open until **Settings → APP → Scenes on this tablet** says **Ready offline**. The first save can take a while, depending on your media. You can then test it by disabling only the tablet's Wi-Fi and reopening the app. Live readings become unavailable; saved scenes, clock and display settings keep working. Reconnect for fresh data and resource updates.

For developers using Android debugging, the alternative is `adb pair`, `adb connect`, then `adb install -r` with the APK path, where supported by the device. Device debugging is optional. The **APP UPDATE** control downloads the newer APK from the same pinned computer and asks Android to confirm installation; it does not silently install it. The manifest requests `REQUEST_INSTALL_PACKAGES` for this user-confirmed flow.

## What the wrapper exposes

The page detects `AiDeskApp` only when running in the app. Its bridge offers `version()`, `setBrightness()`, `keepAwake()`, `reload()`, `vibrate()`, `battery()`, `light()`, `installUpdate()`, `fingerprint()`, `offlineStatus()` and `syncOffline()`. The last two report bounded storage progress and request only the fixed scene-resource sync; they accept no arbitrary URL or command. The browser works without the bridge. The app pins a certificate rather than trusting every certificate on the local network; changing it requires a new build.

Changing executable interface files requires rebuilding and updating the APK. Artwork-only changes can synchronize separately. The app downloads only from your pinned, authenticated computer, validates each saved resource's size and SHA-256, and keeps the previous complete pack if an update is interrupted. It adds no storage permission and caches no live API readings. [Offline details](tablet-offline.md).

The app has been used on the project's Android tablet; behaviour on other hardware and Android versions is **not verified** automatically. Please check full-screen, screen-on behaviour and certificate handling on your device.
