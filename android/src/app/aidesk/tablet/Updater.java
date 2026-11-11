package app.aidesk.tablet;

import android.app.PendingIntent;
import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;
import android.content.IntentFilter;
import android.content.pm.PackageInstaller;
import android.net.Uri;
import android.os.Build;
import android.os.SystemClock;

import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.URL;
import java.security.GeneralSecurityException;
import java.security.cert.CertificateException;
import java.security.cert.X509Certificate;
import java.util.concurrent.atomic.AtomicBoolean;

import javax.net.ssl.HostnameVerifier;
import javax.net.ssl.HttpsURLConnection;
import javax.net.ssl.SSLContext;
import javax.net.ssl.SSLSession;
import javax.net.ssl.SSLSocketFactory;
import javax.net.ssl.TrustManager;
import javax.net.ssl.X509TrustManager;

/**
 * Updates this app from the PC, on the user's tap: it downloads the APK the PC offers at {@link #PATH}, checks it against the SHA-256 the
 * page read from the PC's own status, and hands it to Android's installer, which shows its own "update this app?" screen and refuses any
 * package that is not signed with this app's key.
 *
 * <p>Trust is as narrow as the rest of the shell: the only address is {@link Config#ORIGIN}; the TLS certificate must hash to the baked
 * fingerprint (the same pin the WebView uses) and the host name must be the baked host; redirects are not followed; the answer is read
 * up to {@link Guard#MAX_UPDATE_BYTES}; the page's sign-in cookie is sent only to that origin. Nothing is stored on disk by the app (the
 * bytes go into the installer's own session); nothing else is downloaded. One update at a time.
 */
final class Updater {
    /** What the updater needs from the activity. */
    interface Host {
        Context context();

        /** The page's sign-in cookie for the PC's origin, or null. */
        String cookie();

        /** A fixed state word for the page: "downloading", "confirm", "done", "failed". */
        void report(String state);

        /** The system installer's own confirmation screen. */
        void confirm(Intent intent);
    }

    static final String PATH = "/app/ai-desk-tablet.apk";
    static final String ACTION = "app.aidesk.tablet.UPDATE_RESULT";
    private static final long STALE_MS = 5 * 60 * 1000L;   // an update that never answered is forgotten after five minutes

    private final Host host;
    private final AtomicBoolean busy = new AtomicBoolean(false);
    private volatile long since;
    private BroadcastReceiver receiver;

    Updater(Host host) {
        this.host = host;
    }

    /**
     * Starts an update whose package must hash to {@code expectedSha256}. Returns at once: "started", "busy" (one is under way) or
     * "invalid" (not a SHA-256). Progress arrives through {@link Host#report}.
     */
    String start(String expectedSha256) {
        final String expected = Guard.sha256Hex(expectedSha256);
        if (expected == null) {
            return "invalid";
        }
        if (busy.get() && SystemClock.elapsedRealtime() - since > STALE_MS) {
            release();
            busy.set(false);
        }
        if (!busy.compareAndSet(false, true)) {
            return "busy";
        }
        since = SystemClock.elapsedRealtime();
        Thread worker = new Thread(new Runnable() {
            @Override
            public void run() {
                work(expected);
            }
        }, "ai-desk-update");
        worker.setDaemon(true);
        worker.start();
        return "started";
    }

    /** Stops listening for the installer's answer (the activity is going away). */
    synchronized void release() {
        if (receiver != null) {
            try {
                host.context().unregisterReceiver(receiver);
            } catch (RuntimeException ignored) {
                // already gone
            }
            receiver = null;
        }
    }

    private void work(String expected) {
        host.report("downloading");
        byte[] apk = download();
        if (apk == null || !Guard.updateMatches(apk, expected)) {
            finish("failed");
            return;
        }
        try {
            install(apk);
        } catch (IOException | RuntimeException e) {
            finish("failed");
        }
    }

    private void finish(String state) {
        release();
        busy.set(false);
        host.report(state);
    }

    // ---------------------------------------------------------------- the download: pinned TLS, one address, bounded

    private byte[] download() {
        String cookie = host.cookie();
        if (cookie == null || cookie.isEmpty()) {
            return null;   // not signed in: the PC would refuse anyway
        }
        HttpsURLConnection connection = null;
        try {
            connection = (HttpsURLConnection) new URL(Config.ORIGIN + PATH).openConnection();
            connection.setSSLSocketFactory(pinnedFactory());
            final String expectedHost = Uri.parse(Config.ORIGIN).getHost();
            connection.setHostnameVerifier(new HostnameVerifier() {
                @Override
                public boolean verify(String name, SSLSession session) {
                    return expectedHost != null && expectedHost.equals(name);
                }
            });
            connection.setInstanceFollowRedirects(false);
            connection.setUseCaches(false);
            connection.setConnectTimeout(8000);
            connection.setReadTimeout(20000);
            connection.setRequestProperty("Cookie", cookie);
            connection.setRequestProperty("Accept", "application/vnd.android.package-archive");
            if (connection.getResponseCode() != 200) {
                return null;
            }
            long declared = connection.getContentLengthLong();
            if (declared > Guard.MAX_UPDATE_BYTES) {
                return null;
            }
            InputStream in = connection.getInputStream();
            ByteArrayOutputStream out = new ByteArrayOutputStream(declared > 0 ? (int) declared : 32768);
            byte[] buffer = new byte[16384];
            int total = 0;
            int read;
            while ((read = in.read(buffer)) != -1) {
                total += read;
                if (total > Guard.MAX_UPDATE_BYTES) {
                    return null;
                }
                out.write(buffer, 0, read);
            }
            return total > 0 ? out.toByteArray() : null;
        } catch (IOException | GeneralSecurityException | RuntimeException e) {
            return null;
        } finally {
            if (connection != null) {
                connection.disconnect();
            }
        }
    }

    /** A socket factory that trusts exactly one certificate: the one whose SHA-256 is the baked fingerprint. */
    private static SSLSocketFactory pinnedFactory() throws GeneralSecurityException {
        TrustManager[] managers = new TrustManager[] {new X509TrustManager() {
            @Override
            public void checkClientTrusted(X509Certificate[] chain, String authType) throws CertificateException {
                throw new CertificateException("no client certificates");
            }

            @Override
            public void checkServerTrusted(X509Certificate[] chain, String authType) throws CertificateException {
                if (chain == null || chain.length == 0 || !Guard.matchesPin(chain[0].getEncoded(), Config.FINGERPRINT)) {
                    throw new CertificateException("not the pinned certificate");
                }
            }

            @Override
            public X509Certificate[] getAcceptedIssuers() {
                return new X509Certificate[0];
            }
        }};
        SSLContext context = SSLContext.getInstance("TLS");
        context.init(null, managers, null);
        return context.getSocketFactory();
    }

    // ---------------------------------------------------------------- the install: Android's own installer asks the user

    private void install(byte[] apk) throws IOException {
        Context context = host.context();
        PackageInstaller installer = context.getPackageManager().getPackageInstaller();
        PackageInstaller.SessionParams params = new PackageInstaller.SessionParams(PackageInstaller.SessionParams.MODE_FULL_INSTALL);
        params.setAppPackageName(context.getPackageName());
        params.setSize(apk.length);
        int id = installer.createSession(params);
        PackageInstaller.Session session = installer.openSession(id);
        try {
            OutputStream out = session.openWrite("ai-desk-tablet.apk", 0, apk.length);
            try {
                out.write(apk);
                session.fsync(out);
            } finally {
                out.close();
            }
            listen(context);
            int flags = PendingIntent.FLAG_UPDATE_CURRENT;
            if (Build.VERSION.SDK_INT >= 31) {
                flags |= PendingIntent.FLAG_MUTABLE;   // the installer adds its answer to this intent
            }
            Intent result = new Intent(ACTION).setPackage(context.getPackageName());
            session.commit(PendingIntent.getBroadcast(context, id, result, flags).getIntentSender());
        } catch (IOException | RuntimeException e) {
            session.abandon();
            throw e;
        } finally {
            session.close();
        }
    }

    private synchronized void listen(Context context) {
        release();
        receiver = new BroadcastReceiver() {
            @Override
            @SuppressWarnings("deprecation")
            public void onReceive(Context ignored, Intent intent) {
                int status = intent.getIntExtra(PackageInstaller.EXTRA_STATUS, PackageInstaller.STATUS_FAILURE);
                if (status == PackageInstaller.STATUS_PENDING_USER_ACTION) {
                    Intent confirm = intent.getParcelableExtra(Intent.EXTRA_INTENT);
                    if (confirm != null) {
                        host.report("confirm");
                        host.confirm(confirm);
                    } else {
                        finish("failed");
                    }
                    return;
                }
                finish(status == PackageInstaller.STATUS_SUCCESS ? "done" : "failed");
            }
        };
        IntentFilter filter = new IntentFilter(ACTION);
        if (Build.VERSION.SDK_INT >= 33) {
            context.registerReceiver(receiver, filter, Context.RECEIVER_NOT_EXPORTED);
        } else {
            context.registerReceiver(receiver, filter);
        }
    }
}
