"""Exercise the same animation clock compiled into the physical display."""
import pathlib
import shutil
import subprocess
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]


@unittest.skipUnless(shutil.which('g++'), 'needs g++')
class AnimationClockTests(unittest.TestCase):
    def test_speed_changes_are_continuous_and_survive_millis_wrap(self):
        source = r'''
#include "animation_clock.h"
#include <cassert>
int main() {
 AnimationClock c;
 assert(c.time(1000)==1000); assert(c.time(2000)==2000);
 assert(c.setSpeed(2000,75)); assert(c.time(2000)==2000);
 assert(c.time(2400)==2300);
 assert(!c.setSpeed(2400,0)); assert(c.speed()==75);
 assert(c.setSpeed(2400,125)); assert(c.time(2800)==2800);
 assert(c.setSpeed(2800,100)); assert(c.time(2900)==2900);
 AnimationClock f; f.time(0); assert(f.setSpeed(0,75));
 assert(f.time(1)==0); assert(f.time(2)==1); assert(f.time(4)==3);
 AnimationClock w; w.time(0xfffffff0U); assert(w.setSpeed(0xfffffff0U,125));
 assert(w.time(0x10U)==0x18U); // 32 real ms * 1.25 = 40 virtual ms
}
'''
        with tempfile.TemporaryDirectory() as directory:
            source_path = pathlib.Path(directory) / 'clock.cpp'
            binary = pathlib.Path(directory) / 'clock'
            source_path.write_text(source)
            subprocess.run(['g++', '-std=c++17', '-Wall', '-Wextra', '-Werror',
                            '-I', str(ROOT / 'firmware/board/src'), str(source_path),
                            '-o', str(binary)], check=True, capture_output=True)
            subprocess.run([str(binary)], check=True, capture_output=True)
