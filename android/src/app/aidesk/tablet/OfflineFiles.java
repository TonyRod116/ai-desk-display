package app.aidesk.tablet;

import java.io.File;
import java.io.FileOutputStream;
import java.io.FileInputStream;
import java.io.FilterInputStream;
import java.io.IOException;
import java.io.InputStream;
import java.nio.file.Files;
import java.nio.file.LinkOption;
import java.nio.file.StandardCopyOption;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.HashSet;
import java.util.Set;

/** Private immutable media objects. No Android dependency, so failures run on a real JVM in tests. */
final class OfflineFiles {
    static final int MAX_FILES = 256;
    static final long MAX_FILE = 48L * 1024 * 1024;
    static final long MAX_TOTAL = 2L * 1024 * 1024 * 1024;
    static final long RESERVE = 256L * 1024 * 1024;

    static final class Entry {
        final String path, hash, mime;
        final long size;
        Entry(String path, String hash, String mime, long size) throws IOException {
            if (!allowed(path, mime) || hash == null || !hash.matches("[0-9a-f]{64}") || size <= 0 || size > MAX_FILE
                    || (path.startsWith("/api/") && size > 256 * 1024)) throw new IOException("invalid offline entry");
            this.path = path; this.hash = hash; this.mime = mime; this.size = size;
        }
    }

    interface Space { long available(); }
    private final File root;
    private final Space space;

    OfflineFiles(File root) throws IOException { this(root, () -> root.getUsableSpace()); }
    OfflineFiles(File root, Space space) throws IOException {
        if (!root.isDirectory() && !root.mkdirs()) throw new IOException("offline directory unavailable");
        if (Files.isSymbolicLink(root.toPath())) throw new IOException("invalid offline directory");
        this.root = root; this.space = space;
    }

    static boolean allowed(String path, String mime) {
        if (path == null || mime == null) return false;
        if (path.equals("/api/scenes") || path.equals("/api/photos")) return mime.equals("application/json");
        if (!path.matches("/assets/(?:(?:scene|thumb)-[a-z0-9-]{1,64}|photo-(?:0[1-9]|[1-3][0-9]|40)|city|paradise)\\.(?:png|jpg|webp|webm|json)")) return false;
        String ext = path.substring(path.lastIndexOf('.') + 1);
        return (ext.equals("png") && mime.equals("image/png")) || (ext.equals("jpg") && mime.equals("image/jpeg"))
                || (ext.equals("webp") && mime.equals("image/webp")) || (ext.equals("webm") && mime.equals("video/webm"))
                || (ext.equals("json") && mime.equals("application/json"));
    }

    File object(Entry entry) { return new File(root, entry.hash); }
    boolean has(Entry entry) { return Files.isRegularFile(object(entry).toPath(), LinkOption.NOFOLLOW_LINKS) && object(entry).length() == entry.size; }
    long free() { return space.available(); }

    InputStream stream(Entry entry, long[] span) throws IOException {
        if (span == null || span.length != 2 || span[0] < 0 || span[1] < span[0] || span[1] >= entry.size) throw new IOException("invalid local range");
        FileInputStream in = new FileInputStream(object(entry));
        try {
            in.getChannel().position(span[0]);
            return new FilterInputStream(in) {
                private long remaining = span[1] - span[0] + 1;
                @Override public int read() throws IOException { if (remaining == 0) return -1; int v = in.read(); if (v >= 0) remaining--; return v; }
                @Override public int read(byte[] b, int off, int len) throws IOException {
                    if (len == 0) return 0;
                    if (remaining == 0) return -1;
                    int n = in.read(b, off, (int) Math.min(len, remaining)); if (n > 0) remaining -= n; return n;
                }
                @Override public long skip(long n) throws IOException { long moved = in.skip(Math.min(Math.max(0,n), remaining)); remaining -= moved; return moved; }
                @Override public int available() throws IOException { return (int) Math.min(in.available(), remaining); }
            };
        } catch (IOException | RuntimeException e) { in.close(); throw e; }
    }

    /** Nothing is published until both exact length and SHA-256 match. A failure deletes only our own partial file. */
    void save(Entry entry, InputStream in) throws IOException {
        if (has(entry)) return;
        if (free() < RESERVE + entry.size) throw new IOException("offline storage full");
        File partial = new File(root, entry.hash + ".part");
        try {
            MessageDigest digest = MessageDigest.getInstance("SHA-256");
            long total = 0;
            try (FileOutputStream out = new FileOutputStream(partial)) {
                byte[] buffer = new byte[65536];
                int read;
                while ((read = in.read(buffer)) != -1) {
                    if (Thread.currentThread().isInterrupted()) throw new IOException("offline download paused");
                    total += read;
                    if (total > entry.size || free() < RESERVE) throw new IOException("offline size or space limit");
                    digest.update(buffer, 0, read); out.write(buffer, 0, read);
                }
                if (total != entry.size || !hex(digest.digest()).equals(entry.hash)) throw new IOException("offline integrity mismatch");
                out.getFD().sync();
            }
            Files.move(partial.toPath(), object(entry).toPath(), StandardCopyOption.ATOMIC_MOVE, StandardCopyOption.REPLACE_EXISTING);
        } catch (NoSuchAlgorithmException e) { throw new IOException("SHA-256 unavailable", e); }
        finally { if (partial.exists()) partial.delete(); }
    }

    void prune(Iterable<Entry> entries) {
        Set<String> keep = new HashSet<>();
        for (Entry entry : entries) keep.add(entry.hash);
        File[] files = root.listFiles();
        if (files == null) return;
        for (File file : files) if (file.getName().matches("[0-9a-f]{64}(?:\\.part)?") && !keep.contains(file.getName())) file.delete();
    }

    static String hex(byte[] bytes) {
        StringBuilder out = new StringBuilder(bytes.length * 2);
        for (byte b : bytes) { out.append(Character.forDigit((b >>> 4) & 15, 16)); out.append(Character.forDigit(b & 15, 16)); }
        return out.toString();
    }

    /** Single HTTP byte range; malformed, overflowing or unsatisfiable ranges never allocate or touch a file. */
    static long[] range(String text, long size) {
        if (size <= 0) return null;
        if (text == null) return new long[]{0, size - 1};
        if (!text.matches("bytes=[0-9]*-[0-9]*")) return null;
        String[] bits = text.substring(6).split("-", -1);
        try {
            long start, end;
            if (bits[0].isEmpty()) {
                if (bits[1].isEmpty()) return null;
                long count = Long.parseLong(bits[1]); if (count <= 0) return null;
                start = count >= size ? 0 : size - count; end = size - 1;
            } else {
                start = Long.parseLong(bits[0]); end = bits[1].isEmpty() ? size - 1 : Math.min(size - 1, Long.parseLong(bits[1]));
            }
            return start < 0 || start > end || start >= size ? null : new long[]{start, end};
        } catch (NumberFormatException e) { return null; }
    }
}
