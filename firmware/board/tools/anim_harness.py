"""Build the firmware's scene-animation engine for the PC and run it against a simulated board.

The engine code is cut out of src/main.cpp (between its markers) and compiled with g++ against a few mocks of
the Arduino pieces it uses (a file, the panel, millis, random), so what runs here is the real code. Used by
tests/test_firmware_anim.py. Needs g++; AddressSanitizer is on, so a bad read or write fails loudly.

Usage of the built program: harness <page file> <output dir> <milliseconds> [capture_step_ms]. It dumps the
simulated screen (320x240 RGB565) as screen_<step>.bin at the end of each capture step (default 250 ms).
"""
import shutil
import subprocess
from pathlib import Path

MAIN_CPP = Path(__file__).resolve().parents[1] / 'src' / 'main.cpp'

MOCK = r'''
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <cstdlib>
#include <vector>
#include <string>
#include <map>
#include <algorithm>
#include <chrono>
using std::min; using std::max;
typedef std::string String;
static unsigned long g_now = 0;
static unsigned long millis() { return g_now; }
static unsigned long micros() { return std::chrono::duration_cast<std::chrono::microseconds>(std::chrono::steady_clock::now().time_since_epoch()).count(); }
static long random(long n) { return n <= 0 ? 0 : rand() % n; }
static bool swapRedBlue = false, swapBytes = false;
static int page = 4;
static uint16_t fixColor(uint16_t p) { return p; }
static String pagePath(int n) { return "/p" + std::to_string(n) + ".raw"; }
static std::map<String, std::vector<uint8_t>> g_files;
struct File {
  std::vector<uint8_t> *data = nullptr; size_t pos = 0;
  explicit operator bool() const { return data != nullptr; }
  size_t size() const { return data->size(); }
  bool seek(uint32_t p) { if (p > data->size()) return false; pos = p; return true; }
  size_t read(uint8_t *dst, size_t n) { size_t k = std::min(n, data->size() - pos); memcpy(dst, data->data() + pos, k); pos += k; return k; }
  void close() {}
};
struct FS { File open(const String &path, const char *) { File f; auto it = g_files.find(path); if (it != g_files.end()) f.data = &it->second; return f; } } LittleFS;
static uint16_t g_screen[320 * 240];
static int g_pushes = 0;
struct TFT {
  void pushImage(int x, int y, int w, int h, uint16_t *buf) {
    g_pushes++;
    if (x < 0 || y < 0 || x + w > 320 || y + h > 240) { fprintf(stderr, "PUSH OUT OF BOUNDS %d %d %d %d\n", x, y, w, h); exit(3); }
    for (int r = 0; r < h; r++) memcpy(&g_screen[(y + r) * 320 + x], buf + (size_t)r * w, (size_t)w * 2);
  }
  void fillRect(int x, int y, int w, int h, uint16_t c) {
    if (x < 0 || y < 0 || x + w > 320 || y + h > 240) { fprintf(stderr, "FILL OUT OF BOUNDS\n"); exit(3); }
    for (int r = 0; r < h; r++) for (int k = 0; k < w; k++) g_screen[(y + r) * 320 + x + k] = c;
  }
} tft;
'''

MAIN = r'''
static void dump(const char *dir, unsigned long t) {
  char path[512]; snprintf(path, sizeof path, "%s/screen_%lu.bin", dir, t);
  FILE *f = fopen(path, "wb"); fwrite(g_screen, 2, 320 * 240, f); fclose(f);
}
int main(int argc, char **argv) {
  FILE *f = fopen(argv[1], "rb");
  std::vector<uint8_t> bytes;
  uint8_t buf[4096]; size_t n;
  while ((n = fread(buf, 1, sizeof buf, f)) > 0) bytes.insert(bytes.end(), buf, buf + n);
  fclose(f);
  g_files[pagePath(page)] = bytes;
  const char *out = argv[2];
  unsigned long total = strtoul(argv[3], nullptr, 10);
  unsigned long capture = argc > 4 ? strtoul(argv[4], nullptr, 10) : 250;
  if (capture < 40) return 4;
  srand(7);
  memcpy(g_screen, bytes.data() + 8, 320 * 240 * 2);      // what drawFrame pushes first: the background
  File file = LittleFS.open(pagePath(page), "r");
  bool ok = readAnim(file, 320, 240);
  printf("readAnim=%d sprites=%d stars=%d meteor=%d region=%zu\n", ok, spriteCount, animStarCount, meteor.present, regionPixels);
  printf("wave=%d waveTexture=%u\n", (int)ocean.active, ocean.active ? ocean.offsets[WAVE_ROWS-1]+320-ocean.starts[WAVE_ROWS-1] : 0u);
  for (int i = 0; i < spriteCount; i++) {
    printf("sprite %d: %dx%d at %d,%d frames=%d steps=%d box=%d,%d %dx%d\n", i, sprites[i].w, sprites[i].h, sprites[i].x,
           sprites[i].y, sprites[i].frames, sprites[i].steps, sprites[i].bx, sprites[i].by, sprites[i].bw, sprites[i].bh);
    sprites[i].lastStep = 0;
    drawSpriteStep(sprites[i], 0, file);
  }
  file.close();
  dump(out, 0);
  for (unsigned long t = 20; t <= total; t += 20) {
    g_now = t;
    animTick(t);
    if ((t + 20) / capture != t / capture) dump(out, t / capture);  // the last 20 ms of the capture step
    if (t == 3040 || t == 3280 || t == 3520) dump(out, 100000 + t);   // frames with the shooting star in flight
  }
  dump(out, total);
  printf("pushes=%d meteorActive=%d\n", g_pushes, (int)meteor.active);
  freeAnim();
  return 0;
}
'''


def engine_source():
    text = MAIN_CPP.read_text()
    state = text.index('// Scene animation: a page may end with')
    state_end = text.index('\n', text.index('static bool redrawPending = false;')) + 1
    code = text.index('// ---- scene animation ----')
    code_end = text.index('static bool drawFrame(const String &path) {')
    return text[state:state_end] + '\n' + text[code:code_end]


def build(workdir):
    """Compile the harness into `workdir`; returns the executable path, or None when there is no g++."""
    compiler = shutil.which('g++')
    if not compiler:
        return None
    workdir = Path(workdir)
    source = workdir / 'harness.cpp'
    source.write_text(MOCK + engine_source() + MAIN)
    exe = workdir / 'harness'
    result = subprocess.run([compiler, '-std=c++17', '-g', '-O1', '-fsanitize=address,undefined',
                             '-fno-omit-frame-pointer', '-Wno-unused-function', '-Wno-unused-variable',
                             str(source), '-o', str(exe)], capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError(result.stderr[-2000:])
    return exe
