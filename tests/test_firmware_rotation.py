"""Compile the firmware's actual gesture/clock logic with a deterministic clock."""
import pathlib
import shutil
import subprocess
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]

@unittest.skipUnless(shutil.which('g++'), 'needs g++')
class RotationTests(unittest.TestCase):
    def test_gestures_boundaries_clock_corrections_and_millis_wrap(self):
        source = r'''
#include "rotation.h"
#include <cassert>
int main() {
 assert(gesture(30)==Gesture::None);
 assert(gesture(31)==Gesture::Page);
 assert(gesture(1999)==Gesture::Page);
 assert(gesture(2000)==Gesture::Mode);
 assert(gesture(4999)==Gesture::Mode);
 assert(gesture(5000)==Gesture::Connect);
 assert(gesture(9000)==Gesture::Connect);
 RotationClock c;
 c.setMode(30,0); assert(!c.due(5000,true)); // no guessed wall time
 c.sync(1800001799ULL,5000); // one second before half-hour
 assert(!c.due(5999,true)); assert(c.due(6000,true));
 assert(!c.due(6000,true)); assert(!c.due(6001,true));

 c.setMode(60,6001); // mode change never advances immediately
 assert(!c.due(6001,true)); assert(c.due(1806000,true));
 assert(!c.due(1806001,true));
 c.sync(1800001000ULL,1806001); assert(!c.due(1806001,true)); // rewind
 c.sync(1800090000ULL,1806002); assert(!c.due(1806002,true)); // forward jump
 c.setMode(0,1806002); assert(!c.due(5406002,true));
 c.setMode(30,5406002); assert(!c.due(5406002,true));
 RotationClock disabled; disabled.setMode(30,0); disabled.sync(1800001799ULL,0);
 assert(!disabled.due(1000,false)); assert(!disabled.due(1100,true)); // no catchup from info/stale
 RotationClock wrap; wrap.setMode(30,0xfffffff0U); wrap.sync(1800001799ULL,0xfffffff0U);
 assert(wrap.due(984,true)); assert(!wrap.due(985,true));
 RotationClock heartbeat; heartbeat.setMode(30,0); heartbeat.sync(1800001799ULL,0);
 heartbeat.sync(1800001800ULL,1000); assert(heartbeat.due(1000,true));
 RotationClock jitter; jitter.setMode(30,0); jitter.sync(1800001799ULL,0);
 assert(jitter.due(1000,true)); jitter.sync(1800001799ULL,1001);
 assert(!jitter.due(1001,true)); assert(!jitter.due(2001,true));
 RotationClock boot; boot.setMode(60,0); boot.sync(1800003600ULL,0);
 assert(!boot.due(0,true)); // reboot exactly on boundary preserves selection
 assert(boot.progress(1800000)==50);
}
'''
        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory)
            (path/'test.cpp').write_text(source)
            subprocess.run(['g++','-std=c++17','-Wall','-Wextra','-Werror',
                            '-I',str(ROOT/'firmware/board/src'),str(path/'test.cpp'),'-o',str(path/'test')],check=True,capture_output=True)
            result = subprocess.run([str(path/'test')],capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)

    def test_real_release_handlers_persist_mode_page_and_never_unpair(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location('rotation_harness', ROOT/'firmware/board/tools/rotation_harness.py')
        module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as directory:
            exe = module.build(directory)
            subprocess.run([str(exe)],check=True,capture_output=True)
