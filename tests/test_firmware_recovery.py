"""Run the firmware's real recovery loop with a fake clock, Wi-Fi and restart."""
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


@unittest.skipUnless(shutil.which('g++'), 'needs g++')
class RecoveryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        root = Path(__file__).resolve().parents[1]
        cpp = (root / 'firmware/board/src/main.cpp').read_text()
        start = cpp.index('  // The PC beats about once a minute.')
        recovery = cpp[start:cpp.index('\n}', start)]
        cls.directory = tempfile.TemporaryDirectory()
        directory = Path(cls.directory.name)
        source = r'''
#include <cassert>
#include <string>
static bool haveBeat = false;
static unsigned long lastBeat = 0, linkRenewals = 0;
static int silentRestarts = 0;
static const int WL_CONNECTED = 3;
struct Wifi {
  bool connected = true;
  int status() { return connected ? WL_CONNECTED : 0; }
  void reconnect() {}
} WiFi;
struct Prefs {
  int saved = 0;
  void putInt(const char*, int value) { saved = value; }
} prefs;
struct Restart {};
struct Device { void restart() { throw Restart{}; } } ESP;
static void recover(unsigned long now) {
''' + recovery + r'''
}
static bool restarted(unsigned long now) {
  try { recover(now); return false; } catch (Restart&) { return true; }
}
int main(int argc, char** argv) {
  assert(argc == 2);
  std::string mode = argv[1];
  if (mode == "separate_drops") {
    haveBeat = true; lastBeat = 90000;
    WiFi.connected = false; assert(!restarted(90000));
    WiFi.connected = true; lastBeat = 100000; assert(!restarted(100000));
    // A recovered old outage must not make a later brief drop reboot us.
    lastBeat = 220001; WiFi.connected = false;
    assert(!restarted(220001));
  } else if (mode == "budget_exhausted") {
    silentRestarts = 3; prefs.saved = 3; WiFi.connected = false;
    for (unsigned long now = 90000; now <= 7200000; now += 1000)
      assert(!restarted(now));
    assert(prefs.saved == 3 && linkRenewals > 0);
  } else if (mode == "allowed_restart") {
    silentRestarts = 2;
    assert(!restarted(600000));
    assert(restarted(600001) && prefs.saved == 3);
  } else if (mode == "renewal_throttle") {
    silentRestarts = 3;
    assert(!restarted(300000) && linkRenewals == 0);
    assert(!restarted(300001) && linkRenewals == 1);
    assert(!restarted(600001) && linkRenewals == 1);
    assert(!restarted(600002) && linkRenewals == 2);
  } else if (mode == "healthy") {
    haveBeat = true;
    for (unsigned long now = 60000; now <= 86400000; now += 60000) {
      lastBeat = now;
      assert(!restarted(now));
    }
    assert(linkRenewals == 0 && prefs.saved == 0);
  } else { return 2; }
}
'''
        (directory / 'recovery.cpp').write_text(source)
        cls.exe = directory / 'recovery'
        subprocess.run(['g++', '-std=c++17', '-Wall', '-Wextra', '-Werror',
                        str(directory / 'recovery.cpp'), '-o', str(cls.exe)],
                       check=True, capture_output=True)

    @classmethod
    def tearDownClass(cls):
        cls.directory.cleanup()

    def test_wifi_drops_obey_the_same_restart_budget_and_grace_period(self):
        for mode in ('separate_drops', 'budget_exhausted', 'allowed_restart',
                     'renewal_throttle', 'healthy'):
            with self.subTest(mode=mode):
                result = subprocess.run([str(self.exe), mode], capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
