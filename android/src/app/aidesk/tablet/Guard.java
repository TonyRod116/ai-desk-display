package app.aidesk.tablet;

import java.security.MessageDigest;

/**
 * What the shell trusts and what it accepts from the page, as small checks in plain Java: which addresses belong to the PC, which
 * certificate is the pinned one, and what each bridge method does with the values it is given. No Android classes on purpose: a
 * desktop JVM can run them (tests/test_tablet_app.py does), which the WebView callbacks that use them cannot be.
 */
final class Guard {
    /** The lowest window brightness the page may ask for: never fully off. */
    static final double MIN_BRIGHTNESS = 0.02;

    /** The longest buzz the page may ask for, in milliseconds. */
    static final double MAX_VIBRATION_MS = 500.0;

    /** The largest app update the shell will download; UI files are bundled, large media are saved separately. */
    static final int MAX_UPDATE_BYTES = 2 * 1024 * 1024;

    private Guard() {
    }

    /**
     * True when {@code url} is the PC's origin or lies under it. {@code origin} looks like {@code https://HOST:PORT}
     * (scheme, host and port exactly as the build baked them in; no trailing slash).
     *
     * <p>The comparison is done on the TEXT, not through a URL parser, because parsers disagree about odd addresses such as
     * {@code https://HOST:PORT@elsewhere.example/}. After the origin only {@code /}, {@code ?} or {@code #} (or the end) may
     * follow, so a longer port number, {@code @host}, {@code .evil.example} and a backslash all fail. Case is folded for ASCII
     * letters only, so look-alike letters from other alphabets never match.
     */
    static boolean sameOrigin(String origin, String url) {
        if (origin == null || url == null || origin.isEmpty() || url.length() < origin.length()) {
            return false;
        }
        for (int i = 0; i < origin.length(); i++) {
            if (!sameAscii(origin.charAt(i), url.charAt(i))) {
                return false;
            }
        }
        if (url.length() == origin.length()) {
            return true;
        }
        char next = url.charAt(origin.length());
        return next == '/' || next == '?' || next == '#';
    }

    private static boolean sameAscii(char a, char b) {
        if (a == b) {
            return true;
        }
        if (a >= 'A' && a <= 'Z') {
            a = (char) (a + 32);
        }
        if (b >= 'A' && b <= 'Z') {
            b = (char) (b + 32);
        }
        return a == b;
    }

    /** True when the certificate (its DER bytes) hashes with SHA-256 to exactly the pinned fingerprint (64 hex digits). */
    static boolean matchesPin(byte[] der, String pinHex) {
        if (der == null || der.length == 0) {
            return false;
        }
        byte[] expected = parseHex(pinHex);
        if (expected == null || expected.length != 32) {
            return false;
        }
        try {
            byte[] actual = MessageDigest.getInstance("SHA-256").digest(der);
            return MessageDigest.isEqual(actual, expected);
        } catch (java.security.GeneralSecurityException e) {
            return false;
        }
    }

    /** Hex text (either case) to bytes; null when it is not an even number of hex digits. */
    static byte[] parseHex(String hex) {
        if (hex == null || hex.isEmpty() || (hex.length() & 1) != 0) {
            return null;
        }
        byte[] out = new byte[hex.length() / 2];
        for (int i = 0; i < out.length; i++) {
            int high = nibble(hex.charAt(2 * i));
            int low = nibble(hex.charAt(2 * i + 1));
            if (high < 0 || low < 0) {
                return null;
            }
            out[i] = (byte) (high * 16 + low);
        }
        return out;
    }

    /** One ASCII hex digit; -1 for anything else (Character.digit would also accept digits of other alphabets). */
    private static int nibble(char c) {
        if (c >= '0' && c <= '9') {
            return c - '0';
        }
        if (c >= 'a' && c <= 'f') {
            return c - 'a' + 10;
        }
        if (c >= 'A' && c <= 'F') {
            return c - 'A' + 10;
        }
        return -1;
    }

    // ---- what the bridge accepts from the page ----

    /**
     * Window brightness for {@code setBrightness(level)}: -1 means "follow the system" and is passed through, 0.02 to 1.0 is used as it
     * is, and anything else gives NaN: ignore the call. Nothing is cut into range on purpose: WebView turns a value of the wrong type
     * (undefined, a string, null) into 0 before Java sees it, and that must not become "the dimmest backlight" by accident.
     */
    static float brightness(double level) {
        if (level == -1.0) {
            return -1f;
        }
        if (!(level >= MIN_BRIGHTNESS && level <= 1.0)) {   // also true for NaN, infinity, 0 and every other negative number
            return Float.NaN;
        }
        return (float) level;
    }

    /** Milliseconds for {@code vibrate(ms)}: 1 to 500 (a longer ask is cut to 500); 0 means "ignore" (NaN, infinity, below 1). */
    static long vibrationMillis(double milliseconds) {
        if (!(milliseconds >= 1.0) || Double.isInfinite(milliseconds)) {   // the first test is also true for NaN
            return 0L;
        }
        return (long) Math.min(milliseconds, MAX_VIBRATION_MS);
    }

    /** {"percent":87,"charging":true}, or "" when Android gave no usable level. */
    static String batteryJson(int level, int scale, boolean charging) {
        if (level < 0 || scale <= 0) {
            return "";
        }
        int percent = Math.max(0, Math.min(100, Math.round(level * 100f / scale)));
        return "{\"percent\":" + percent + ",\"charging\":" + charging + "}";
    }

    /** Lux for {@code light()} from a raw sensor value, to one decimal; -1 when there is no usable reading (0 lux in the dark is a reading). */
    static double lux(float reading) {
        if (Float.isNaN(reading) || Float.isInfinite(reading) || reading < 0f) {
            return -1.0;
        }
        return Math.round(reading * 10.0) / 10.0;
    }

    /** {@code text} as 64 lower-case hex digits when it is exactly a SHA-256 in either case; otherwise null. */
    static String sha256Hex(String text) {
        if (text == null || text.length() != 64) {
            return null;
        }
        byte[] bytes = parseHex(text);
        if (bytes == null || bytes.length != 32) {
            return null;
        }
        StringBuilder out = new StringBuilder(64);
        for (byte b : bytes) {
            out.append(Character.forDigit((b >> 4) & 15, 16)).append(Character.forDigit(b & 15, 16));
        }
        return out.toString();
    }

    /** True when the bytes hash with SHA-256 to exactly {@code expectedHex} (64 hex digits) and the size is in range for an update. */
    static boolean updateMatches(byte[] apk, String expectedHex) {
        String expected = sha256Hex(expectedHex);
        if (expected == null || apk == null || apk.length == 0 || apk.length > MAX_UPDATE_BYTES) {
            return false;
        }
        try {
            byte[] actual = MessageDigest.getInstance("SHA-256").digest(apk);
            return MessageDigest.isEqual(actual, parseHex(expected));
        } catch (java.security.GeneralSecurityException e) {
            return false;
        }
    }
}
