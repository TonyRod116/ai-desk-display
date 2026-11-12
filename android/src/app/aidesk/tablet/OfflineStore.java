package app.aidesk.tablet;

import android.content.Context;
import android.net.Uri;
import android.util.AtomicFile;
import android.webkit.WebResourceRequest;
import android.webkit.WebResourceResponse;

import org.json.JSONArray;
import org.json.JSONException;
import org.json.JSONObject;

import java.io.ByteArrayInputStream;
import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.IOException;
import java.io.InputStream;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.concurrent.atomic.AtomicBoolean;

import javax.net.ssl.HttpsURLConnection;

/** Bundled executable UI; persistent verified artwork only. Live APIs and credentials are never stored here. */
final class OfflineStore {
    interface Host { String cookie(); void changed(); }
    private static final int MANIFEST_LIMIT = 128 * 1024;
    private static final String CSP = "default-src 'none'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self'; media-src 'self'; connect-src 'self'; form-action 'self'; base-uri 'none'; frame-ancestors 'none'";
    private final Context context;
    private final Host host;
    private final AtomicBoolean busy = new AtomicBoolean();
    private final AtomicFile index;
    private OfflineFiles files;
    private volatile Pack current;
    private volatile HttpsURLConnection connection;
    private volatile boolean active;
    private volatile long attempted, succeeded;
    private volatile int done, count;
    private volatile long bytes, total;
    private volatile String state = "waiting";

    private static final class Pack {
        final String revision;
        final long total;
        final Map<String, OfflineFiles.Entry> entries;
        final byte[] raw;
        Pack(byte[] raw) throws JSONException, IOException {
            JSONObject value = new JSONObject(new String(raw, StandardCharsets.UTF_8));
            if (!(value.opt("schema") instanceof Number) || value.getDouble("schema") != 1) throw new IOException("offline schema");
            revision = value.getString("revision");
            if (!revision.matches("[0-9a-f]{64}")) throw new IOException("offline revision");
            JSONArray list = value.getJSONArray("files");
            if (list.length() < 2 || list.length() > OfflineFiles.MAX_FILES) throw new IOException("offline file limit");
            entries = new LinkedHashMap<>();
            long sum = 0;
            for (int i = 0; i < list.length(); i++) {
                JSONObject row = list.getJSONObject(i);
                Object number = row.get("size");
                if (!(number instanceof Number) || ((Number) number).doubleValue() != ((Number) number).longValue()) throw new IOException("offline file size");
                OfflineFiles.Entry entry = new OfflineFiles.Entry(row.getString("path"), row.getString("sha256"), row.getString("mime"), ((Number) number).longValue());
                if (entries.put(entry.path, entry) != null) throw new IOException("duplicate offline path");
                sum += entry.size;
                if (sum > OfflineFiles.MAX_TOTAL) throw new IOException("offline storage limit");
            }
            if (!entries.containsKey("/api/scenes") || !entries.containsKey("/api/photos") || value.getLong("total") != sum) throw new IOException("incomplete offline manifest");
            total = sum; this.raw = raw;
        }
    }

    OfflineStore(Context context, Host host) {
        this.context = context; this.host = host;
        File root = new File(context.getFilesDir(), "offline-v1");
        index = new AtomicFile(new File(root, "current.json"));
        try {
            files = new OfflineFiles(new File(root, "objects"));
            Pack saved;
            try (InputStream in = index.openRead()) { saved = new Pack(read(in, MANIFEST_LIMIT)); }
            boolean complete = true;
            for (OfflineFiles.Entry entry : saved.entries.values()) if (!files.has(entry)) complete = false;
            if (complete) { current = saved; state = "ready"; total = bytes = saved.total; count = done = saved.entries.size(); }
        } catch (IOException | JSONException | RuntimeException ignored) { /* the bundled UI still opens */ }
    }

    void resume() { active = true; }
    void pause() { active = false; HttpsURLConnection c = connection; if (c != null) c.disconnect(); }

    String status() {
        try {
            return new JSONObject().put("state", state).put("ready", current != null).put("busy", busy.get())
                    .put("done", done).put("count", count).put("bytes", bytes).put("total", total)
                    .put("revision", current == null ? "" : current.revision).toString();
        } catch (JSONException e) { return "{}"; }
    }

    String sync(boolean force) {
        long now = android.os.SystemClock.elapsedRealtime();
        if (!active || files == null) return "waiting";
        if (busy.get()) return "busy";
        if (!force && current != null && succeeded > 0 && now - succeeded < 300000) return "ready";
        if (attempted > 0 && now - attempted < 10000) return "waiting";
        String cookie = host.cookie();
        if (cookie == null || cookie.isEmpty()) return "waiting";
        if (!busy.compareAndSet(false, true)) return "busy";
        attempted = now;
        Thread worker = new Thread(() -> {
            try { work(cookie); }
            finally { connection = null; busy.set(false); host.changed(); }
        }, "ai-desk-offline");
        worker.setPriority(Thread.MIN_PRIORITY); worker.setDaemon(true); worker.start();
        return "started";
    }

    private HttpsURLConnection open(String path, String cookie) throws Exception {
        if (!active) throw new IOException("offline sync paused");
        HttpsURLConnection c = (HttpsURLConnection) new URL(Config.ORIGIN + path).openConnection();
        connection = c;
        c.setSSLSocketFactory(Updater.pinnedFactory());
        final String expected = Uri.parse(Config.ORIGIN).getHost();
        c.setHostnameVerifier((name, session) -> expected != null && expected.equals(name));
        c.setInstanceFollowRedirects(false); c.setUseCaches(false);
        c.setConnectTimeout(5000); c.setReadTimeout(20000);
        c.setRequestProperty("Cookie", cookie); c.setRequestProperty("Origin", Config.ORIGIN);
        c.setRequestProperty("Accept-Encoding", "identity");
        return c;
    }

    private void work(String cookie) {
        state = "saving"; done = count = 0; bytes = total = 0;
        HttpsURLConnection c = null;
        try {
            c = open("/api/offline", cookie);
            int status = c.getResponseCode();
            if (status == 401) { state = "sign_in"; return; }
            if (status != 200 || c.getContentLengthLong() > MANIFEST_LIMIT) throw new IOException("offline inventory unavailable");
            Pack next;
            try (InputStream in = c.getInputStream()) { next = new Pack(read(in, MANIFEST_LIMIT)); }
            c.disconnect(); c = null;
            count = next.entries.size(); total = next.total;
            if (current != null && current.revision.equals(next.revision)) { done = count; bytes = total; state = "ready"; succeeded = android.os.SystemClock.elapsedRealtime(); return; }
            long missing = 0;
            for (OfflineFiles.Entry entry : next.entries.values()) if (!files.has(entry)) missing += entry.size;
            if (files.free() < OfflineFiles.RESERVE + missing) { state = "storage"; return; }
            for (OfflineFiles.Entry entry : next.entries.values()) {
                if (!active) throw new IOException("offline download paused");
                if (!files.has(entry)) {
                    c = open(entry.path, cookie);
                    if (c.getResponseCode() != 200 || (c.getContentLengthLong() >= 0 && c.getContentLengthLong() != entry.size)) throw new IOException("offline resource changed");
                    try (InputStream in = c.getInputStream()) { files.save(entry, in); }
                    c.disconnect(); c = null;
                }
                done++; bytes += entry.size;
            }
            if (!active) throw new IOException("offline download paused");
            java.io.FileOutputStream out = index.startWrite();
            try { out.write(next.raw); index.finishWrite(out); }
            catch (IOException e) { index.failWrite(out); throw e; }
            current = next; state = "ready"; succeeded = android.os.SystemClock.elapsedRealtime();
            files.prune(next.entries.values());
        } catch (Exception ignored) { state = "waiting"; }
        finally { if (c != null) c.disconnect(); }
    }

    static boolean localPage(String url) { return Guard.sameOrigin(Config.ORIGIN, url) && (Config.ORIGIN + "/").equals(url); }

    WebResourceResponse serve(WebResourceRequest request) {
        if (!"GET".equals(request.getMethod()) || !Guard.sameOrigin(Config.ORIGIN, request.getUrl().toString())) return null;
        String path = request.getUrl().getEncodedPath();
        if (path == null || path.isEmpty()) path = "/";
        try {
            if (path.equals("/") || path.matches("/[a-z0-9-]{1,40}\\.(?:js|css)")) {
                String name = path.equals("/") ? "index.html" : path.substring(1);
                String mime = path.equals("/") ? "text/html" : path.endsWith(".js") ? "text/javascript" : "text/css";
                return response(mime, 200, headers(), context.getAssets().open("web/" + name));
            }
            Pack pack = current;
            OfflineFiles.Entry entry = pack == null ? null : pack.entries.get(path);
            if (entry == null || !files.has(entry)) return null;
            String wanted = null;
            for (Map.Entry<String, String> h : request.getRequestHeaders().entrySet()) if (h.getKey().equalsIgnoreCase("Range")) wanted = h.getValue();
            long[] span = OfflineFiles.range(wanted, entry.size);
            Map<String, String> headers = headers(); headers.put("Accept-Ranges", "bytes");
            if (span == null) { headers.put("Content-Range", "bytes */" + entry.size); return response(entry.mime, 416, headers, new ByteArrayInputStream(new byte[0])); }
            long length = span[1] - span[0] + 1;
            headers.put("Content-Length", Long.toString(length));
            if (wanted != null) headers.put("Content-Range", "bytes " + span[0] + "-" + span[1] + "/" + entry.size);
            return response(entry.mime, wanted == null ? 200 : 206, headers, files.stream(entry, span));
        } catch (IOException | RuntimeException ignored) { return null; }
    }

    private static Map<String, String> headers() {
        Map<String, String> h = new HashMap<>(); h.put("Cache-Control", "no-store");
        h.put("Content-Security-Policy", CSP); h.put("X-Content-Type-Options", "nosniff"); h.put("Referrer-Policy", "no-referrer");
        return h;
    }

    private static WebResourceResponse response(String mime, int code, Map<String, String> headers, InputStream in) {
        return new WebResourceResponse(mime, mime.startsWith("text/") || mime.equals("application/json") ? "UTF-8" : null,
                code, code == 206 ? "Partial Content" : code == 416 ? "Range Not Satisfiable" : "OK", headers, in);
    }

    private static byte[] read(InputStream in, int max) throws IOException {
        ByteArrayOutputStream out = new ByteArrayOutputStream(); byte[] buffer = new byte[8192]; int n;
        while ((n = in.read(buffer)) != -1) { if (out.size() + n > max) throw new IOException("offline inventory too large"); out.write(buffer, 0, n); }
        return out.toByteArray();
    }
}
