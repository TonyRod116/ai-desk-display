package app.aidesk.tablet;

/**
 * The loading / waiting / retry logic of the shell, in plain Java (no Android classes) so that a desktop JVM can run it
 * (tests/test_tablet_app.py does). The activity supplies the effects (load the page, show or hide the waiting screen) and the clock.
 *
 * <p>States: LOADING (an attempt is running; the waiting screen covers the page), WAITING (the attempt failed; the next one starts in
 * ten seconds) and LIVE (the page is showing; nothing covers it). Whatever happens, the page is never left half shown: it is either
 * LIVE or covered, and while the app is on screen and the page is not LIVE a timer always guarantees another attempt. While the app is
 * away (pause) nothing is scheduled at all, and a page that is not showing starts again when it is back (resume).
 *
 * <p>WebView reports events without saying which attempt they belong to, so a late "finished" or "error" of the PREVIOUS attempt can
 * arrive after the next one was started. {@link #pageStarted()} is the marker: a failure keeps rejecting "loaded" until the new
 * navigation has actually begun, so the error page of an old attempt can never uncover the screen.
 */
final class Loader {
    static final long RETRY_MS = 10_000L;       // pause between attempts while the PC does not answer
    static final long LOAD_LIMIT_MS = 25_000L;  // an attempt that has shown nothing by then counts as failed

    enum State { LOADING, WAITING, LIVE }

    enum Screen { CONNECTING, WAITING, CERTIFICATE }

    /** What the activity does for the loader. All calls come on one thread (the main thread). */
    interface Host {
        void load();                                  // start loading the page
        void stopLoading();                           // stop the attempt that is running
        void showScreen(Screen screen);               // cover the page with the waiting screen saying this
        void hideScreen();                            // uncover the page
        void schedule(Runnable task, long delayMs);   // run the task later, once
        void unschedule(Runnable task);               // forget a task that has not run yet
    }

    private final Host host;
    private final Runnable retryTask = new Runnable() {
        @Override
        public void run() {
            if (state == State.WAITING && !paused) {
                start();
            }
        }
    };
    private final Runnable limitTask = new Runnable() {
        @Override
        public void run() {
            if (state == State.LOADING && !paused) {
                host.stopLoading();
                fail(false);
            }
        }
    };

    private State state = State.LOADING;
    private boolean paused;               // the app is away: no timers, no loading
    private boolean everFailed;           // the very first attempt says "connecting"; after a failure the screen says "waiting"
    private boolean attemptFailed;        // a failure was reported and the next navigation has not begun: reject "loaded"
    private boolean attemptCertificate;   // ... and it was because of the certificate (or the secure handshake)
    private boolean certificateProblem;   // what the screen is saying now

    Loader(Host host) {
        this.host = host;
    }

    State state() {
        return state;
    }

    boolean isLive() {
        return state == State.LIVE;
    }

    /** One attempt at the page. The screen stays up until the page really shows. While the app is away it only covers the page. */
    void start() {
        host.unschedule(retryTask);
        host.unschedule(limitTask);
        state = State.LOADING;
        host.showScreen(screen());
        if (paused) {
            return;   // resume() makes the attempt when the app is back
        }
        host.load();
        host.schedule(limitTask, LOAD_LIMIT_MS);
    }

    /**
     * A new main-frame navigation began (WebViewClient.onPageStarted for the PC's address): what the earlier attempt reported late no
     * longer counts, so the events that follow belong to this attempt.
     */
    void pageStarted() {
        attemptFailed = false;
        attemptCertificate = false;
    }

    /** The page shows (first paint or finished). Ignored after a failure that the next navigation has not replaced, and when it already shows. */
    void loaded() {
        if (attemptFailed || state == State.LIVE) {
            return;
        }
        state = State.LIVE;
        everFailed = false;
        certificateProblem = false;
        host.unschedule(retryTask);
        host.unschedule(limitTask);
        host.hideScreen();
    }

    /** The attempt (or a page that was showing) failed; {@code certificate} says the certificate is not the pinned one or the secure handshake failed. */
    void fail(boolean certificate) {
        attemptFailed = true;
        attemptCertificate |= certificate;
        certificateProblem = attemptCertificate;
        everFailed = true;
        host.unschedule(limitTask);
        if (state != State.WAITING) {
            state = State.WAITING;
            if (!paused) {
                host.schedule(retryTask, RETRY_MS);   // not moved by later errors of the same outage; never armed while the app is away
            }
        }
        host.showScreen(screen());
    }

    /** Wi-Fi is back: try at once instead of waiting out the rest of the ten seconds. */
    void networkAvailable() {
        if (state == State.WAITING && !paused) {
            start();
        }
    }

    /** The app left the screen: no timers while it is away, and a failure that arrives now arms none. */
    void pause() {
        paused = true;
        host.unschedule(retryTask);
        host.unschedule(limitTask);
    }

    /** The app is on screen again: a page that is not showing starts again. */
    void resume() {
        paused = false;
        if (state != State.LIVE) {
            start();
        }
    }

    private Screen screen() {
        if (certificateProblem) {
            return Screen.CERTIFICATE;
        }
        return everFailed ? Screen.WAITING : Screen.CONNECTING;
    }
}
