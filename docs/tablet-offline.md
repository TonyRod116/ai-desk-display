# Scenes that can stay when the PC leaves

The Android app carries its complete interface, translations and scene engines inside the signed APK. Prepared artwork is copied separately from your computer into the app's private storage. Nothing is fetched from an art service, and there is no preconfigured APK or signing key in this repository.

## First save

1. [Set up the tablet service](tablet.md) and [build/install your Android app](tablet-app.md).
2. Sign in on the tablet, keep the computer available and open **Settings → APP**.
3. Wait for **Scenes on this tablet → Ready offline**. **Save / update scenes** requests another sync. The first copy depends on your media size and the tablet's available storage.
4. Disable only the tablet's Wi-Fi and reopen the app to check your own device. Reconnect afterwards for fresh readings. Do not stop a computer that has other important work running just to test this.

The clock, date, saved scenes, animations, picture mode, swipes, rotation/daypart schedules and display preferences run locally. Settings survive an app restart. Preference changes made offline synchronize when the computer returns; memory actions and board commands are never queued for later execution.

Fresh quotas, reset/credit balances, computer readings, weather refreshes and the small-screen remote still need the computer. Unavailable readings stay unknown. A browser tab remains the computer-served version; the persistent local copy belongs to the Android app.

## Resource updates and storage

The authenticated `/api/offline` endpoint inventories only allowlisted scene files and scene/photo catalogues. The app uses its existing cookie and baked certificate pin, refuses redirects and arbitrary paths, and streams each file through size and SHA-256 checks. An incomplete new pack never replaces the previous complete one. Completed objects can be reused after an interrupted save; obsolete objects are pruned after a replacement commits. Videos support byte ranges without loading a whole movie into RAM.

Limits are 256 files, 48 MiB per resource and 2 GiB per pack, retaining at least 256 MiB of free device storage. Images and metadata also have the server's smaller limits. If space is insufficient, free space on your tablet and retry. Clearing app data removes the saved pack, preferences and sign-in; clearing the ordinary WebView cache is not the same thing.

The cache never stores provider credentials, live quotas, balances, computer metrics, administrative pages or executable scripts from the server. The APK contains UI code; optional pictures, movies and game artwork are not embedded in it or supplied by this repository. Android backup remains disabled. Keep your own artwork permissions in mind.

Executable interface changes require a rebuilt APK; scene-resource changes can sync separately. If a film already on screen still looks unchanged after a completed resource update, choose another scene and return to reopen it. Build counters are local to your computer, not a global release number. The APK must keep the same signing key for in-app updates.

## Your own Peaceful House

The optional seaside-house preparer works with a specific window/sea composition; it is not a universal photo animation tool. Supply your own permitted source photo, a compatible local ocean sequence and, optionally, your own wildlife sprites. Start with the scripts' `--help` and adapt their masks to your image.

`prepare_tablet_house_life.py` now renders eight 7.5-second water cycles in each 60-second, 24 fps daypart film. The bird's visit and distant-bird timing stay separate. Dusk and night reflections share the sun/moon positions with the sky, use broken highlights modulated by photographed wave crests, and stay clipped to exposed water. This is photographic compositing, not a fluid simulation. Rendering can use one encoder thread; prepare media offline rather than during a dashboard request. Originals, footage and generated output belong outside Git.

Tests and browser previews use fictional data/art. The maintainer has checked resource saving and playback on their tablet, but offline startup, video performance, available storage and Android restrictions are **not verified** for every device. Check yours before relying on it as a permanent display.
