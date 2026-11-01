"""The scrolling page dots remain accurate without repeated flash lookups."""
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


@unittest.skipUnless(shutil.which('g++'), 'needs g++')
class IndicatorCacheTests(unittest.TestCase):
    def test_cached_page_dots_follow_storage_and_capacity_changes(self):
        source = (Path(__file__).resolve().parents[1] / 'firmware/board/src/main.cpp').read_text()
        cache = source[source.index('static uint8_t indicatorPageMask'):
                       source.index('// A quiet page marker')]
        draw = source[source.index('static void drawIndicator()'):
                      source.index('static void drawStale()')]
        mock = r'''
#include <cassert>
#include <cstdint>
#include <string>
#include <vector>
static int activePages=8, page=2, checks=0;
static bool present[8]={true,false,true,false,false,false,true,false};
static std::string pagePath(int n) { return std::to_string(n); }
struct FS { bool exists(const std::string &name) { ++checks; return present[std::stoi(name)]; } } LittleFS;
static const uint16_t DOT_ACTIVE=1, DOT_IDLE=2;
struct Screen {
  std::vector<uint16_t> dots;
  int width() { return 320; }
  int height() { return 240; }
  void fillCircle(int,int,int,uint16_t colour) { dots.push_back(colour); }
} tft;
static void drawRotationIndicator() {}
'''
        check = r'''
int main() {
  drawIndicator();
  assert(checks==8 && tft.dots==std::vector<uint16_t>({2,1,2}));
  for (int i=0; i<30; ++i) { tft.dots.clear(); drawIndicator(); }
  assert(checks==8 && tft.dots==std::vector<uint16_t>({2,1,2}));
  present[1]=true; indicatorMaskValid=false; tft.dots.clear(); drawIndicator();
  assert(checks==16 && tft.dots==std::vector<uint16_t>({2,2,1,2}));
  activePages=2; indicatorMaskValid=false; tft.dots.clear(); drawIndicator();
  assert(checks==18 && tft.dots==std::vector<uint16_t>({2,2}));
}
'''
        with tempfile.TemporaryDirectory() as tmp:
            cpp = Path(tmp) / 'indicator.cpp'
            exe = Path(tmp) / 'indicator'
            cpp.write_text(mock + cache + draw + check)
            subprocess.run([shutil.which('g++'), '-std=c++17', '-O1', str(cpp), '-o', str(exe)],
                           check=True, capture_output=True, text=True)
            result = subprocess.run([str(exe)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
