package app.aidesk.tablet;

import android.app.Activity;
import android.content.Intent;
import android.content.IntentFilter;
import android.content.res.Configuration;
import android.graphics.Bitmap;
import android.graphics.Color;
import android.hardware.Sensor;
import android.hardware.SensorEvent;
import android.hardware.SensorEventListener;
import android.hardware.SensorManager;
import android.net.ConnectivityManager;
import android.net.Network;
import android.net.Uri;
import android.net.http.SslCertificate;
import android.net.http.SslError;
import android.os.BatteryManager;
import android.os.Build;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.os.SystemClock;
import android.os.VibrationEffect;
import android.os.Vibrator;
import android.util.TypedValue;
import android.view.Gravity;
import android.view.View;
import android.view.Window;
import android.view.WindowInsets;
import android.view.WindowInsetsController;
import android.view.WindowManager;
import android.webkit.ClientCertRequest;
import android.webkit.CookieManager;
import android.webkit.GeolocationPermissions;
import android.webkit.HttpAuthHandler;
import android.webkit.PermissionRequest;
import android.webkit.RenderProcessGoneDetail;
import android.webkit.SslErrorHandler;
import android.webkit.WebChromeClient;
import android.webkit.WebResourceError;
import android.webkit.WebResourceRequest;
import android.webkit.WebResourceResponse;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.FrameLayout;
import android.widget.ImageView;
import android.widget.LinearLayout;
import android.widget.TextView;
import android.window.OnBackInvokedCallback;
import android.window.OnBackInvokedDispatcher;

import java.io.ByteArrayInputStream;
import java.security.cert.X509Certificate;
import java.util.HashMap;

/**
 * AI Desk on the tablet: a bundled full-screen interface with verified scene resources saved in private app storage. The PC
 * supplies live readings and controls. The page stays one code base; the app adds the real backlight, a screen that stays on, full screen that
 * survives a reload, a pinned certificate instead of a warning, sounds without a first tap, battery and light readings.
 *
 * <p>Trust is narrow on purpose: the only address ever loaded is {@link Config#ORIGIN}; a certificate that is not the pinned
 * one is refused; the JavaScript bridge ({@link Bridge}) exists only for pages of that origin because nothing else can load.
 */
public final class MainActivity extends Activity {
    private static final long RELOAD_GAP_MS = 2_000L;   // the page cannot make the app reload in a tight loop
    private static final long RENDERER_RETRY_GAP_MS = 30_000L;   // a second renderer loss this soon waits for the ten-second retry

    private final Handler handler = new Handler(Looper.getMainLooper());
    private FrameLayout root;
    private WebView web;
    private LinearLayout overlay;
    private TextView overlayTitle;
    private TextView overlayHint;
    private Loader loader;                // decides when to load, wait and retry (plain Java, tested on a desktop JVM)
    private OfflineStore offline;
    private final Runnable offlineTick = new Runnable() {
        @Override public void run() {
            if (offline != null) offline.sync(false);
            handler.postDelayed(this, 60000);
        }
    };
    private final Updater updater = new Updater(new Updater.Host() {   // the update of this app from the PC, on the user's tap
        @Override
        public android.content.Context context() {
            return MainActivity.this;
        }

        @Override
        public String cookie() {
            return CookieManager.getInstance().getCookie(Config.ORIGIN);
        }

        @Override
        public void report(String state) {
            reportUpdate(state);
        }

        @Override
        public void confirm(final Intent intent) {
            runOnUiThread(new Runnable() {
                @Override
                public void run() {
                    try {
                        startActivity(intent);
                    } catch (RuntimeException e) {
                        reportUpdate("failed");
                    }
                }
            });
        }
    });

    private long lastReload;
    private long lastRendererLoss = -RENDERER_RETRY_GAP_MS;   // so that the first loss is never "repeated"
    private boolean resumed;

    private SensorManager sensors;
    private volatile boolean lightWanted;
    private boolean lightRegistered;
    private volatile float lux = -1f;
    private final SensorEventListener lightListener = new SensorEventListener() {
        @Override
        public void onSensorChanged(SensorEvent event) {
            if (event.values != null && event.values.length > 0) {
                lux = event.values[0];
            }
        }

        @Override
        public void onAccuracyChanged(Sensor sensor, int accuracy) {
        }
    };
    private ConnectivityManager.NetworkCallback networkCallback;

    // ---------------------------------------------------------------- lifecycle

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        WebView.setWebContentsDebuggingEnabled(Config.DEBUG);   // false unless built with --debug
        getWindow().addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);   // on by default; the page may change it
        if (Build.VERSION.SDK_INT >= 28) {
            WindowManager.LayoutParams params = getWindow().getAttributes();
            params.layoutInDisplayCutoutMode = Build.VERSION.SDK_INT >= 30
                    ? WindowManager.LayoutParams.LAYOUT_IN_DISPLAY_CUTOUT_MODE_ALWAYS
                    : WindowManager.LayoutParams.LAYOUT_IN_DISPLAY_CUTOUT_MODE_SHORT_EDGES;
            getWindow().setAttributes(params);
        }
        sensors = (SensorManager) getSystemService(SENSOR_SERVICE);
        offline = new OfflineStore(this, new OfflineStore.Host() {
            @Override public String cookie() { return CookieManager.getInstance().getCookie(Config.ORIGIN); }
            @Override public void changed() {
                runOnUiThread(() -> { if (web != null) web.evaluateJavascript("window.aiDeskOfflineChanged && window.aiDeskOfflineChanged()", null); });
            }
        });

        root = new FrameLayout(this);
        root.setBackgroundColor(Color.BLACK);
        root.setOnApplyWindowInsetsListener((view, insets) -> {
            if (Build.VERSION.SDK_INT >= 30) {
                // Edge-to-edge windows are not resized by the keyboard any more: make room for it ourselves (the sign-in form).
                view.setPadding(0, 0, 0, insets.getInsets(WindowInsets.Type.ime()).bottom);
            }
            return insets;
        });
        web = createWebView();
        root.addView(web, new FrameLayout.LayoutParams(FrameLayout.LayoutParams.MATCH_PARENT, FrameLayout.LayoutParams.MATCH_PARENT));
        overlay = buildOverlay();
        root.addView(overlay, new FrameLayout.LayoutParams(FrameLayout.LayoutParams.MATCH_PARENT, FrameLayout.LayoutParams.MATCH_PARENT));
        setContentView(root);
        LoaderHost host = new LoaderHost();
        loader = new Loader(host);
        host.showScreen(Loader.Screen.CONNECTING);   // covered from the very first frame; onStart makes the first attempt
        hideSystemUi();
        if (Build.VERSION.SDK_INT >= 33) {
            registerBackCallback();
        }
    }

    @Override
    protected void onStart() {
        super.onStart();
        watchNetwork();
        offline.resume();
        handler.postDelayed(offlineTick, 60000);
        loader.resume();   // a page that is not showing starts again; one that shows is left alone
    }

    @Override
    protected void onResume() {
        super.onResume();
        resumed = true;
        if (web != null) {
            web.onResume();
        }
        registerLight();
        hideSystemUi();
    }

    @Override
    protected void onPause() {
        resumed = false;
        unregisterLight();
        CookieManager.getInstance().flush();   // the 90-day sign-in cookie must reach the disk
        if (web != null) {
            web.onPause();
        }
        super.onPause();
    }

    @Override
    protected void onStop() {
        loader.pause();   // no retry timers while the app is away
        offline.pause();
        handler.removeCallbacks(offlineTick);
        unwatchNetwork();
        super.onStop();
    }

    @Override
    protected void onDestroy() {
        updater.release();
        if (offline != null) offline.pause();
        handler.removeCallbacksAndMessages(null);
        if (web != null) {
            root.removeView(web);
            web.destroy();
            web = null;
        }
        super.onDestroy();
    }

    @Override
    protected void onNewIntent(Intent intent) {
        super.onNewIntent(intent);
        hideSystemUi();
    }

    @Override
    public void onConfigurationChanged(Configuration newConfig) {
        super.onConfigurationChanged(newConfig);   // rotating or resizing never recreates the page (see configChanges)
        hideSystemUi();
    }

    @Override
    public void onWindowFocusChanged(boolean hasFocus) {
        super.onWindowFocusChanged(hasFocus);
        if (hasFocus) {
            hideSystemUi();   // sticky immersive mode: bring it back whenever the window regains focus
        }
    }

    /** Back never leaves the app: it walks the page's own history if there is any, else it does nothing. Home leaves normally. */
    @Override
    @SuppressWarnings("deprecation")
    public void onBackPressed() {
        goBackOrStay();
    }

    private void goBackOrStay() {
        if (loader.isLive() && web != null && web.canGoBack()) {
            web.goBack();
        }
    }

    private void registerBackCallback() {
        getOnBackInvokedDispatcher().registerOnBackInvokedCallback(OnBackInvokedDispatcher.PRIORITY_DEFAULT,
                new OnBackInvokedCallback() {
                    @Override
                    public void onBackInvoked() {
                        goBackOrStay();
                    }
                });
    }

    // ---------------------------------------------------------------- full screen

    private void hideSystemUi() {
        Window window = getWindow();
        if (Build.VERSION.SDK_INT >= 30) {
            window.setDecorFitsSystemWindows(false);
            WindowInsetsController controller = window.getInsetsController();
            if (controller != null) {
                controller.hide(WindowInsets.Type.systemBars());
                controller.setSystemBarsBehavior(WindowInsetsController.BEHAVIOR_SHOW_TRANSIENT_BARS_BY_SWIPE);
            }
        } else {
            window.getDecorView().setSystemUiVisibility(View.SYSTEM_UI_FLAG_LAYOUT_STABLE
                    | View.SYSTEM_UI_FLAG_LAYOUT_HIDE_NAVIGATION | View.SYSTEM_UI_FLAG_LAYOUT_FULLSCREEN
                    | View.SYSTEM_UI_FLAG_HIDE_NAVIGATION | View.SYSTEM_UI_FLAG_FULLSCREEN
                    | View.SYSTEM_UI_FLAG_IMMERSIVE_STICKY);
        }
    }

    // ---------------------------------------------------------------- the WebView

    private WebView createWebView() {
        WebView view = new WebView(this);
        view.setBackgroundColor(Color.BLACK);
        view.setOverScrollMode(View.OVER_SCROLL_NEVER);
        view.setVerticalScrollBarEnabled(false);
        view.setHorizontalScrollBarEnabled(false);
        view.setHapticFeedbackEnabled(false);

        WebSettings settings = view.getSettings();
        settings.setJavaScriptEnabled(true);
        settings.setDomStorageEnabled(true);
        settings.setMediaPlaybackRequiresUserGesture(false);   // alert sounds and scene videos start without a first tap
        settings.setAllowFileAccess(false);
        settings.setAllowContentAccess(false);
        settings.setAllowFileAccessFromFileURLs(false);
        settings.setAllowUniversalAccessFromFileURLs(false);
        settings.setMixedContentMode(WebSettings.MIXED_CONTENT_NEVER_ALLOW);
        settings.setSupportZoom(false);
        settings.setBuiltInZoomControls(false);
        settings.setDisplayZoomControls(false);
        settings.setSupportMultipleWindows(false);
        settings.setJavaScriptCanOpenWindowsAutomatically(false);
        settings.setGeolocationEnabled(false);
        settings.setSafeBrowsingEnabled(false);   // a private address: nothing to look up, nothing sent to Google
        settings.setUseWideViewPort(false);       // lay out at the view's width, as the page expects
        settings.setLoadWithOverviewMode(false);
        settings.setTextZoom(100);                // the page scales itself; Android's font size must not distort it

        CookieManager cookies = CookieManager.getInstance();
        cookies.setAcceptCookie(true);            // the sign-in cookie lasts 90 days and must survive a restart
        cookies.setAcceptThirdPartyCookies(view, false);

        view.setWebViewClient(new Client());
        view.setWebChromeClient(new Chrome());
        view.setDownloadListener((url, userAgent, contentDisposition, mimeType, contentLength) -> { });
        view.addJavascriptInterface(new Bridge(this), "AiDeskApp");
        return view;
    }

    /**
     * The renderer process died (memory pressure, a crash): build a fresh WebView instead of letting the app die with it. The first loss
     * is answered with an attempt at once; a second one within 30 s waits the usual ten seconds, so a renderer that dies on every load
     * cannot make the app spin.
     */
    private boolean rebuildWebView(WebView dead) {
        if (dead != web || root == null) {
            return true;
        }
        root.removeView(web);
        web.destroy();
        web = createWebView();
        root.addView(web, 0, new FrameLayout.LayoutParams(FrameLayout.LayoutParams.MATCH_PARENT, FrameLayout.LayoutParams.MATCH_PARENT));
        long now = SystemClock.elapsedRealtime();
        boolean repeated = now - lastRendererLoss < RENDERER_RETRY_GAP_MS;
        lastRendererLoss = now;
        if (repeated) {
            loader.fail(false);
        } else {
            loader.start();
        }
        return true;
    }

    private final class Client extends WebViewClient {
        @Override
        public boolean shouldOverrideUrlLoading(WebView view, WebResourceRequest request) {
            // true = the app handles it (by doing nothing). Only the PC's own address may be navigated to.
            return !Guard.sameOrigin(Config.ORIGIN, request.getUrl().toString());
        }

        @Override
        public WebResourceResponse shouldInterceptRequest(WebView view, WebResourceRequest request) {
            Uri uri = request.getUrl();
            String scheme = uri.getScheme();
            boolean network = "http".equalsIgnoreCase(scheme) || "https".equalsIgnoreCase(scheme);
            if (network && !Guard.sameOrigin(Config.ORIGIN, uri.toString())) {
                return new WebResourceResponse("text/plain", "utf-8", 403, "Blocked",
                        new HashMap<String, String>(), new ByteArrayInputStream(new byte[0]));
            }
            if (network && offline != null) {
                WebResourceResponse saved = offline.serve(request);
                if (saved != null) return saved;
            }
            return null;
        }

        @Override
        public void onReceivedSslError(WebView view, SslErrorHandler handler, SslError error) {
            // The one rule that replaces the browser's warning: proceed ONLY for the PC's own address AND the exact
            // certificate this app was built with (SHA-256 of its DER bytes). Anything else is refused.
            boolean ours = Guard.sameOrigin(Config.ORIGIN, error.getUrl());
            if (ours && Guard.matchesPin(derOf(error.getCertificate()), Config.FINGERPRINT)) {
                handler.proceed();
                return;
            }
            handler.cancel();
            if (ours && view == web && !OfflineStore.localPage(view.getUrl())) {
                loader.fail(true);
            }
        }

        @Override
        public void onReceivedClientCertRequest(WebView view, ClientCertRequest request) {
            request.cancel();   // the PC never asks for one; nobody else gets to
        }

        @Override
        public void onReceivedHttpAuthRequest(WebView view, HttpAuthHandler handler, String host, String realm) {
            handler.cancel();
        }

        // Every callback below ignores a WebView that was already replaced (a crashed renderer): only the current one speaks.

        @Override
        public void onPageStarted(WebView view, String url, Bitmap favicon) {
            if (view == web && Guard.sameOrigin(Config.ORIGIN, url)) {
                loader.pageStarted();   // late events of the previous attempt stop counting here
            }
        }

        @Override
        public void onReceivedError(WebView view, WebResourceRequest request, WebResourceError error) {
            if (view == web && request.isForMainFrame()) {
                // A failed secure handshake gets the certificate screen even when WebView remembers an earlier refusal
                // and no longer calls onReceivedSslError for it.
                loader.fail(error.getErrorCode() == ERROR_FAILED_SSL_HANDSHAKE);
            }
        }

        @Override
        public void onReceivedHttpError(WebView view, WebResourceRequest request, WebResourceResponse response) {
            if (view == web && request.isForMainFrame() && response.getStatusCode() >= 400) {
                loader.fail(false);   // an error body is not a page worth showing
            }
        }

        @Override
        public void onPageCommitVisible(WebView view, String url) {
            if (view == web && Guard.sameOrigin(Config.ORIGIN, url)) {
                loader.loaded();
            }
        }

        @Override
        public void onPageFinished(WebView view, String url) {
            CookieManager.getInstance().flush();
            if (view == web && Guard.sameOrigin(Config.ORIGIN, url)) {
                loader.loaded();
                if (OfflineStore.localPage(url)) offline.sync(false);
            }
        }

        @Override
        public boolean onRenderProcessGone(WebView view, RenderProcessGoneDetail detail) {
            return rebuildWebView(view);
        }
    }

    private static final class Chrome extends WebChromeClient {
        @Override
        public Bitmap getDefaultVideoPoster() {
            return Bitmap.createBitmap(1, 1, Bitmap.Config.ARGB_8888);   // transparent: no grey play button while a scene loads
        }

        @Override
        public void onPermissionRequest(PermissionRequest request) {
            request.deny();   // the page never gets the camera, the microphone or anything else
        }

        @Override
        public void onGeolocationPermissionsShowPrompt(String origin, GeolocationPermissions.Callback callback) {
            callback.invoke(origin, false, false);
        }
    }

    /** The server certificate's DER bytes, or null when Android does not hand them over. */
    private static byte[] derOf(SslCertificate certificate) {
        if (certificate == null) {
            return null;
        }
        try {
            if (Build.VERSION.SDK_INT >= 29) {
                X509Certificate x509 = certificate.getX509Certificate();
                return x509 == null ? null : x509.getEncoded();
            }
            Bundle saved = SslCertificate.saveState(certificate);   // Android 8 to 9: the DER bytes ride in the saved state
            return saved == null ? null : saved.getByteArray("x509-certificate");
        } catch (Exception e) {
            return null;
        }
    }

    // ---------------------------------------------------------------- loading, waiting, retrying (the decisions are in Loader)

    /** The loader decides; the activity loads the page, covers or uncovers it with the waiting screen, and keeps the time. */
    private final class LoaderHost implements Loader.Host {
        @Override
        public void load() {
            if (web != null) {
                web.loadUrl(Config.START_URL);
            }
        }

        @Override
        public void stopLoading() {
            if (web != null) {
                web.stopLoading();
            }
        }

        @Override
        public void showScreen(Loader.Screen screen) {
            switch (screen) {
                case CERTIFICATE:
                    overlayTitle.setText(R.string.status_certificate);
                    overlayHint.setText(R.string.status_certificate_hint);
                    break;
                case WAITING:
                    overlayTitle.setText(R.string.status_waiting);
                    overlayHint.setText(R.string.status_waiting_hint);
                    break;
                default:
                    overlayTitle.setText(R.string.status_connecting);
                    overlayHint.setText("");
                    break;
            }
            overlay.setVisibility(View.VISIBLE);
        }

        @Override
        public void hideScreen() {
            overlay.setVisibility(View.GONE);
            hideSystemUi();
        }

        @Override
        public void schedule(Runnable task, long delayMs) {
            handler.postDelayed(task, delayMs);
        }

        @Override
        public void unschedule(Runnable task) {
            handler.removeCallbacks(task);
        }
    }

    /** As soon as Wi-Fi comes back, try again instead of waiting out the rest of the ten seconds. */
    private void watchNetwork() {
        if (networkCallback != null) {
            return;
        }
        try {
            ConnectivityManager manager = (ConnectivityManager) getSystemService(CONNECTIVITY_SERVICE);
            if (manager == null) {
                return;
            }
            networkCallback = new ConnectivityManager.NetworkCallback() {
                @Override
                public void onAvailable(Network network) {
                    handler.post(new Runnable() {
                        @Override
                        public void run() {
                            if (web != null) {
                                loader.networkAvailable();
                                if (offline != null) offline.sync(false);
                            }
                        }
                    });
                }
            };
            manager.registerDefaultNetworkCallback(networkCallback);
        } catch (RuntimeException e) {
            networkCallback = null;   // the ten-second timer still works without it
        }
    }

    private void unwatchNetwork() {
        if (networkCallback == null) {
            return;
        }
        try {
            ((ConnectivityManager) getSystemService(CONNECTIVITY_SERVICE)).unregisterNetworkCallback(networkCallback);
        } catch (RuntimeException e) {
            // already gone
        }
        networkCallback = null;
    }

    // ---------------------------------------------------------------- the waiting screen (native: no page, no history)

    private int dp(float value) {
        return Math.round(TypedValue.applyDimension(TypedValue.COMPLEX_UNIT_DIP, value, getResources().getDisplayMetrics()));
    }

    private TextView label(float sp, int color) {
        TextView view = new TextView(this);
        view.setTextSize(TypedValue.COMPLEX_UNIT_SP, sp);
        view.setTextColor(color);
        view.setGravity(Gravity.CENTER);
        return view;
    }

    private LinearLayout buildOverlay() {
        LinearLayout box = new LinearLayout(this);
        box.setOrientation(LinearLayout.VERTICAL);
        box.setGravity(Gravity.CENTER);
        box.setBackgroundColor(Color.BLACK);
        box.setClickable(true);   // taps end here and never reach the page underneath
        box.setPadding(dp(40), dp(40), dp(40), dp(40));

        ImageView mark = new ImageView(this);
        mark.setImageResource(R.drawable.ic_mark);
        box.addView(mark, new LinearLayout.LayoutParams(dp(96), dp(96)));

        overlayTitle = label(22, getColor(R.color.ink));
        LinearLayout.LayoutParams titleParams = new LinearLayout.LayoutParams(LinearLayout.LayoutParams.WRAP_CONTENT, LinearLayout.LayoutParams.WRAP_CONTENT);
        titleParams.topMargin = dp(24);
        box.addView(overlayTitle, titleParams);

        overlayHint = label(15, getColor(R.color.muted));
        overlayHint.setMaxWidth(dp(480));
        LinearLayout.LayoutParams hintParams = new LinearLayout.LayoutParams(LinearLayout.LayoutParams.WRAP_CONTENT, LinearLayout.LayoutParams.WRAP_CONTENT);
        hintParams.topMargin = dp(12);
        box.addView(overlayHint, hintParams);

        TextView address = label(13, getColor(R.color.dim));   // which PC this app was built for, and which build it is (for support)
        address.setText(Config.ORIGIN.replaceFirst("^https://", "") + "  -  app " + Config.VERSION_NAME + (Config.DEBUG ? " (debug)" : ""));
        LinearLayout.LayoutParams addressParams = new LinearLayout.LayoutParams(LinearLayout.LayoutParams.WRAP_CONTENT, LinearLayout.LayoutParams.WRAP_CONTENT);
        addressParams.topMargin = dp(20);
        box.addView(address, addressParams);
        return box;
    }

    // ---------------------------------------------------------------- what the bridge can do (inputs are validated in Guard)

    /** 0.02 to 1.0 is the window's brightness (the real backlight, below the system's lowest setting); -1 gives control back. */
    void setBrightness(double level) {
        final float value = Guard.brightness(level);
        if (Float.isNaN(value)) {
            return;   // not a usable level: ignored
        }
        runOnUiThread(new Runnable() {
            @Override
            public void run() {
                WindowManager.LayoutParams params = getWindow().getAttributes();
                params.screenBrightness = value;
                getWindow().setAttributes(params);
            }
        });
    }

    void keepAwake(final boolean on) {
        runOnUiThread(new Runnable() {
            @Override
            public void run() {
                if (on) {
                    getWindow().addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);
                } else {
                    getWindow().clearFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);
                }
            }
        });
    }

    /** Starts the update of this app (see {@link Updater}); "started", "busy" or "invalid". */
    String installUpdate(String sha256) {
        return updater.start(sha256);
    }

    /** Tells the page, with a fixed word, how the update is going: it defines window.aiDeskAppUpdate(state). */
    void reportUpdate(final String state) {
        runOnUiThread(new Runnable() {
            @Override
            public void run() {
                if (web != null) {
                    web.evaluateJavascript("window.aiDeskAppUpdate&&window.aiDeskAppUpdate('" + state + "')", null);
                }
            }
        });
    }

    String offlineStatus() { return offline == null ? "{}" : offline.status(); }

    String syncOffline() { return offline == null ? "waiting" : offline.sync(true); }

    void reloadPage() {
        runOnUiThread(new Runnable() {
            @Override
            public void run() {
                long now = SystemClock.elapsedRealtime();
                if (web == null || now - lastReload < RELOAD_GAP_MS) {
                    return;
                }
                lastReload = now;
                hideSystemUi();   // the app stays in full screen: only the page is reloaded
                if (loader.isLive()) {
                    web.reload();
                } else {
                    loader.start();
                }
            }
        });
    }

    void vibrate(double milliseconds) {
        long duration = Guard.vibrationMillis(milliseconds);
        if (duration <= 0L) {
            return;   // not a usable length: ignored
        }
        Vibrator vibrator = (Vibrator) getSystemService(VIBRATOR_SERVICE);
        if (vibrator != null && vibrator.hasVibrator()) {
            vibrator.vibrate(VibrationEffect.createOneShot(duration, VibrationEffect.DEFAULT_AMPLITUDE));
        }
    }

    /** {"percent":87,"charging":true}, or "" when Android does not say. "charging" means on external power (also when full or paused). */
    String batteryJson() {
        Intent intent = registerReceiver(null, new IntentFilter(Intent.ACTION_BATTERY_CHANGED));   // sticky: no receiver kept
        if (intent == null) {
            return "";
        }
        int status = intent.getIntExtra(BatteryManager.EXTRA_STATUS, BatteryManager.BATTERY_STATUS_UNKNOWN);
        boolean charging = status == BatteryManager.BATTERY_STATUS_CHARGING || status == BatteryManager.BATTERY_STATUS_FULL
                || intent.getIntExtra(BatteryManager.EXTRA_PLUGGED, 0) != 0;
        return Guard.batteryJson(intent.getIntExtra(BatteryManager.EXTRA_LEVEL, -1), intent.getIntExtra(BatteryManager.EXTRA_SCALE, -1), charging);
    }

    /** Lux from the ambient light sensor; the first call starts listening (only while the app is on screen), -1 until a reading. */
    double lightLux() {
        if (!lightWanted) {
            lightWanted = true;
            handler.post(new Runnable() {
                @Override
                public void run() {
                    registerLight();
                }
            });
        }
        return Guard.lux(lux);
    }

    private void registerLight() {
        if (!lightWanted || !resumed || lightRegistered || sensors == null) {
            return;
        }
        Sensor sensor = sensors.getDefaultSensor(Sensor.TYPE_LIGHT);
        if (sensor != null) {
            lightRegistered = sensors.registerListener(lightListener, sensor, SensorManager.SENSOR_DELAY_NORMAL);
        }
    }

    private void unregisterLight() {
        if (lightRegistered && sensors != null) {
            sensors.unregisterListener(lightListener);
        }
        lightRegistered = false;
        lux = -1f;   // an old reading is not a current one
    }
}
