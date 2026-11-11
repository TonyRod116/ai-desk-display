package app.aidesk.tablet;

import android.webkit.JavascriptInterface;

/**
 * {@code window.AiDeskApp}: the only door from the page into the app. Exactly these nine methods are visible to JavaScript
 * (only methods marked {@code @JavascriptInterface} are), the object is handed to pages of the PC's origin alone (the shell
 * blocks every other address), and each method checks what it is given and does nothing on bad input.
 * Android calls them on a background thread; the activity moves anything that touches views to the main thread.
 */
final class Bridge {
    private final MainActivity app;

    Bridge(MainActivity app) {
        this.app = app;
    }

    /** The app's version, "<contract>.<build>" (for example "1.7"). */
    @JavascriptInterface
    public String version() {
        return Config.VERSION_NAME;
    }

    /** 0.02 to 1.0 sets this window's brightness (the real backlight); -1 hands control back to the system. */
    @JavascriptInterface
    public void setBrightness(double level) {
        app.setBrightness(level);
    }

    /** Keeps the screen on (the default) or lets Android turn it off. */
    @JavascriptInterface
    public void keepAwake(boolean on) {
        app.keepAwake(on);
    }

    /** Reloads the page; the app stays in full screen. */
    @JavascriptInterface
    public void reload() {
        app.reloadPage();
    }

    /** One short buzz of 1 to 500 milliseconds (longer asks are cut to 500). Nothing on a tablet without a motor. */
    @JavascriptInterface
    public void vibrate(double milliseconds) {
        app.vibrate(milliseconds);
    }

    /** {"percent":87,"charging":true} as text, or "" when Android does not say. */
    @JavascriptInterface
    public String battery() {
        return app.batteryJson();
    }

    /** Ambient light in lux, or -1 when there is no sensor or no reading yet (the first call starts the sensor). */
    @JavascriptInterface
    public double light() {
        return app.lightLux();
    }

    /**
     * Updates the app from the PC: downloads the APK the PC offers (pinned certificate, that address only), checks that it hashes to
     * {@code sha256} (64 hex digits, read from the PC's status by the page) and opens Android's own installer. Returns "started", "busy"
     * or "invalid" at once; "downloading", "confirm", "done" or "failed" follow through {@code window.aiDeskAppUpdate(state)}.
     */
    @JavascriptInterface
    public String installUpdate(String sha256) {
        return app.installUpdate(sha256);
    }

    /** The certificate fingerprint this app trusts: 64 lower-case hex digits (SHA-256 of the server certificate). */
    @JavascriptInterface
    public String fingerprint() {
        return Config.FINGERPRINT;
    }
}
