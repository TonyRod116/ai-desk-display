"""Fictional files only: exercise the Android app's storage core on the installed JDK."""
from pathlib import Path
import unittest

from scripts import build_tablet_app as app

ROOT = Path(__file__).resolve().parents[1]

CHECK = r'''
package app.aidesk.tablet;
import java.io.*;
import java.nio.file.*;
import java.security.*;
import java.util.*;
public final class OfflineCheck {
    static void check(boolean ok) { if (!ok) throw new AssertionError("offline contract"); }
    static void refused(String path, String mime) throws Exception {
        try { new OfflineFiles.Entry(path, "a".repeat(64), mime, 10); throw new AssertionError(path); }
        catch (IOException expected) { }
    }
    public static void main(String[] args) throws Exception {
        for(String path:new String[]{"/api/status","/api/settings","/api/memory/release","/api/board/preview/0.png","/app.js","/login","/assets/../auth.json","/assets/%2e%2e/auth.json"}) refused(path,"application/json");
        refused("/assets/scene-surf.png","text/html");
        byte[] bytes="fictional-scene".getBytes("UTF-8");
        String hash=OfflineFiles.hex(MessageDigest.getInstance("SHA-256").digest(bytes));
        OfflineFiles.Entry entry=new OfflineFiles.Entry("/assets/scene-surf.png",hash,"image/png",bytes.length);
        File root=Files.createTempDirectory("offline-check-").toFile();
        try {
            OfflineFiles store=new OfflineFiles(root,()->OfflineFiles.MAX_TOTAL);
            check(!store.has(entry));
            try { store.save(entry,new ByteArrayInputStream("corrupted".getBytes("UTF-8"))); throw new AssertionError(); } catch(IOException expected) { }
            check(!store.has(entry)); check(root.listFiles().length==0);
            try { store.save(entry,new ByteArrayInputStream(new byte[bytes.length+1])); throw new AssertionError(); } catch(IOException expected) { }
            check(!store.has(entry));
            OfflineFiles full=new OfflineFiles(root,()->0);
            try { full.save(entry,new ByteArrayInputStream(bytes)); throw new AssertionError(); } catch(IOException expected) { }
            check(!full.has(entry));
            store.save(entry,new ByteArrayInputStream(bytes)); check(store.has(entry));
            check(new OfflineFiles(root).has(entry)); // restart the store
            try(InputStream slice=store.stream(entry,new long[]{1,6})) {
                check(slice.available()==6); check(slice.read()=='i'); check(slice.skip(2)==2); check(slice.read()=='i');
                byte[] rest=new byte[10]; check(slice.read(rest,0,10)==2); check(rest[0]=='o'&&rest[1]=='n');
                check(slice.read(rest,0,0)==0); check(slice.available()==0); check(slice.read()==-1);
            }
            try(InputStream slice=store.stream(entry,new long[]{2,4})) {check(slice.skip(Long.MAX_VALUE)==3);check(slice.read()==-1);}
            store.save(entry,new ByteArrayInputStream(bytes)); check(root.listFiles().length==1);
            check(Arrays.equals(OfflineFiles.range(null,10),new long[]{0,9}));
            check(Arrays.equals(OfflineFiles.range("bytes=2-4",10),new long[]{2,4}));
            check(Arrays.equals(OfflineFiles.range("bytes=-3",10),new long[]{7,9}));
            check(Arrays.equals(OfflineFiles.range("bytes=2-",10),new long[]{2,9}));
            for(String value:new String[]{"bytes=-0","bytes=10-","bytes=5-4","bytes=0-3,5-8","bytes=999999999999999999999999-","bytes=-","bad"}) check(OfflineFiles.range(value,10)==null);
            store.prune(Collections.singletonList(entry)); check(store.has(entry));
            store.prune(Collections.emptyList()); check(!store.has(entry));
        } finally { for(File f:root.listFiles()) f.delete(); root.delete(); }
        System.out.println("OFFLINE STORAGE OK");
    }
}
'''


class OfflineAndroidTests(unittest.TestCase):
    def test_actual_storage_core_on_jvm(self):
        try:
            tools = app.find_toolchain()
        except app.BuildError:
            self.skipTest('Android SDK/JDK unavailable')
        with app.workspace(tools) as work:
            folder = work / 'app/aidesk/tablet'
            folder.mkdir(parents=True)
            source = ROOT / 'android/src/app/aidesk/tablet/OfflineFiles.java'
            (folder / 'OfflineFiles.java').write_text(source.read_text())
            (folder / 'OfflineCheck.java').write_text(CHECK)
            classes = work / 'classes'
            classes.mkdir()
            app.call(tools.javac, '-J-Xmx128m', '--release', '11', '-d', classes,
                     folder / 'OfflineFiles.java', folder / 'OfflineCheck.java', cwd=work, timeout=60)
            result = app.call(tools.java, '-Xmx128m', '-cp', classes, 'app.aidesk.tablet.OfflineCheck', cwd=work, timeout=30)
            self.assertIn('OFFLINE STORAGE OK', result)
