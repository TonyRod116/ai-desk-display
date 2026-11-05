"""Run the firmware's real details-card code (parser, formatting and drawing) with a fake display.

The block of main.cpp between the "details card" markers is compiled as it is. Only the display is faked: a framebuffer
that renders text from the very font tables TFT_eSPI uses (fonts 2 and 4, the algorithm of its drawChar/drawString), so
a capture shows what the panel would. The tables come from the PlatformIO library folder; without it (a machine that never
built the firmware) the rendering is skipped and only the parser runs against a display that draws nothing.
"""
from pathlib import Path
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[1]
FONTS = ROOT / '.pio/libdeps/cyd/TFT_eSPI/Fonts'

MOCK = r'''
#include <algorithm>
#include <cassert>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <string>
#include <vector>

#define PROGMEM
#ifdef WITH_FONTS
#include "Font16.c"
#include "Font32rle.c"
#endif

struct String {
  std::string s;
  String(const char *c = "") : s(c) {}
  String(const std::string &c) : s(c) {}
  unsigned length() const { return (unsigned)s.size(); }
  const char *c_str() const { return s.c_str(); }
};

enum { TL_DATUM = 0, TC_DATUM = 1, TR_DATUM = 2, ML_DATUM = 3, MC_DATUM = 4, MR_DATUM = 5, BL_DATUM = 6, BC_DATUM = 7, BR_DATUM = 8 };
static uint32_t nowMs = 0;
static uint32_t millis() { return nowMs; }
static uint32_t confirmationUntil = 0;
static bool showingCard = false;
static uint32_t cardUntil = 0;
static int drawPages = 0;
static void drawPage() { ++drawPages; }
#ifdef HARNESS_SWAP_RB                  // a panel that needs red and blue swapped: every colour the card draws must follow
static uint16_t fixColor(uint16_t p) { return (uint16_t)(((p & 0xF800) >> 11) | (p & 0x07E0) | ((p & 0x001F) << 11)); }
#else
static uint16_t fixColor(uint16_t c) { return c; }
#endif

struct Box { int x0, y0, x1, y1; std::string text; int font; uint16_t colour; };
struct FakeTft {
  uint16_t fb[320 * 240];
  uint16_t fg = 0xFFFF, bg = 0;
  int datum = 0;
  std::vector<Box> boxes;                 // every string drawn, with the box it occupies
  int width() { return 320; }
  int height() { return 240; }
  void put(int x, int y, uint16_t c) { if (x >= 0 && y >= 0 && x < 320 && y < 240) fb[y * 320 + x] = c; }
  void fillScreen(uint16_t c) { for (auto &p : fb) p = c; boxes.clear(); }
  void fillRect(int x, int y, int w, int h, uint16_t c) { for (int j = 0; j < h; j++) for (int i = 0; i < w; i++) put(x + i, y + j, c); }
  void drawFastHLine(int x, int y, int w, uint16_t c) { fillRect(x, y, w, 1, c); }
  void setTextColor(uint16_t f, uint16_t b) { fg = f; bg = b; }
  void setTextDatum(int d) { datum = d; }
  int heightOf(int font) { return font == 2 ? 16 : font == 4 ? 26 : 8; }
  int charWidth(unsigned char ch, int font) {
    (void)ch;
#ifdef WITH_FONTS
    const unsigned char *table = font == 2 ? widtbl_f16 : font == 4 ? widtbl_f32 : nullptr;
    if (table) return ch > 31 && ch < 128 ? table[ch - 32] : table[0];
#endif
    return font == 2 ? 8 : font == 4 ? 14 : 6;
  }
  int textWidth(const char *s, int font) { int w = 0; for (; *s; s++) w += charWidth((unsigned char)*s, font); return w; }
  int drawChar(unsigned char ch, int x, int y, int font) {
    if (ch < 32 || ch > 127) return 0;
    const int width = charWidth(ch, font), height = heightOf(font);
#ifdef WITH_FONTS
    if (font == 2) {                       // one bit per pixel, rows of (width + 6) / 8 bytes, most significant bit left
      const unsigned char *rows = chrtbl_f16[ch - 32];
      const int bytes = (width + 6) / 8;
      for (int r = 0; r < height; r++) {
        int px = width;
        for (int k = 0; k < bytes; k++) {
          unsigned char line = rows[bytes * r + k];
          for (unsigned char mask = 0x80; mask && px; mask >>= 1, px--) put(x + (width - px), y + r, (line & mask) ? fg : bg);
        }
      }
    } else if (font == 4) {                // run-length coded: bit 7 set = foreground run, else background run
      const unsigned char *run = chrtbl_f32[ch - 32];
      int total = width * height, pc = 0;
      while (pc < total) {
        unsigned char line = *run++;
        const bool on = line & 0x80;
        int count = (line & 0x7F) + 1;
        while (count-- && pc < total) { put(x + pc % width, y + pc / width, on ? fg : bg); pc++; }
      }
    }
#else
    fillRect(x, y, width, height, bg);
#endif
    return width;
  }
  int drawString(const char *text, int x, int y, int font) {
    const int w = textWidth(text, font), h = heightOf(font);
    int px = x, py = y;
    switch (datum) {
      case TC_DATUM: px -= w / 2; break;
      case TR_DATUM: px -= w; break;
      case MC_DATUM: px -= w / 2; py -= h / 2; break;
      default: break;
    }
    boxes.push_back({px, py, px + w, py + h, text, font, fg});
    int sum = 0;
    for (const char *p = text; *p; p++) sum += drawChar((unsigned char)*p, px + sum, py, font);
    return w;
  }
} tft;
'''

MAIN = r'''
static void show(const CardSide &c) {
  printf("present=%d week=%d hours=%d weekReset=%ld hoursReset=%ld age=%ld saved=%d old=%d why=[%s]\n", c.present, c.week, c.hours,
         (long)c.weekReset, (long)c.hoursReset, (long)c.age, c.saved, c.savedOld, c.why);
}

int main(int argc, char **argv) {
  std::string mode = argc > 1 ? argv[1] : "";
  if (mode == "parse") {                   // parse <line>: what a board would take from it, or REJECTED
    CardSide before[2];
    memcpy(before, cardSides, sizeof(before));
    acceptCard(String(argv[2]));
    if (!cardHave) { printf("REJECTED\n"); assert(cardRejected == 1 && !memcmp(before, cardSides, sizeof(before))); return 0; }
    printf("OK\n");
    show(cardSides[0]);
    show(cardSides[1]);
    return 0;
  }
  if (mode == "render") {                  // render <out> <seconds since arrival> <line | ->
    if (std::string(argv[4]) != "-") acceptCard(String(argv[4]));
    nowMs = (uint32_t)atol(argv[3]) * 1000u;
    drawCard();
    // Nothing may leave the screen's safe margins or sit on another string.
    for (size_t i = 0; i < tft.boxes.size(); i++) {
      const Box &a = tft.boxes[i];
      if (a.x0 < 12 || a.x1 > 308 || a.y0 < 4 || a.y1 > 236) { fprintf(stderr, "outside: [%s] %d,%d-%d,%d\n", a.text.c_str(), a.x0, a.y0, a.x1, a.y1); return 3; }
      for (size_t j = i + 1; j < tft.boxes.size(); j++) {
        const Box &b = tft.boxes[j];
        if (a.x0 < b.x1 && b.x0 < a.x1 && a.y0 < b.y1 && b.y0 < a.y1) { fprintf(stderr, "overlap: [%s] [%s]\n", a.text.c_str(), b.text.c_str()); return 4; }
      }
    }
    for (const Box &b : tft.boxes) printf("%d,%d-%d,%d font%d %04x [%s]\n", b.x0, b.y0, b.x1, b.y1, b.font, b.colour, b.text.c_str());
    FILE *f = fopen(argv[2], "wb");
    fwrite(tft.fb, 2, 320 * 240, f);
    fclose(f);
    return 0;
  }
  if (mode == "width") {                   // width <font> <text>: pixels the real font tables give
    printf("%d\n", tft.textWidth(argv[3], atoi(argv[2])));
    return 0;
  }
  if (mode == "lines") {                   // lines: one card line per row of standard input; answers OK or REJECTED for each
    char buffer[1024];
    while (fgets(buffer, sizeof(buffer), stdin)) {
      buffer[strcspn(buffer, "\n")] = 0;
      const unsigned long before = cardRejected;
      acceptCard(String(buffer));
      puts(cardRejected == before ? "OK" : "REJECTED");
    }
    return 0;
  }
  if (mode == "keeps_the_previous_card") {
    acceptCard(String("1,xw62,xr3600,xa30,xs2"));
    assert(cardHave && cardSides[0].week == 62 && cardCount == 1);
    CardSide good[2];
    memcpy(good, cardSides, sizeof(good));
    for (const char *bad : {"", "2,xw1", "1,xw101", "1,xw5,xw6", "1,zw5", "1,xq5", "1,xw5,", "1,,xw5", "1,xw-5", "1,xs100", "1,xs2oo"}) {
      acceptCard(String(bad));
      assert(!memcmp(good, cardSides, sizeof(good)));
    }
    assert(cardRejected == 11 && cardCount == 1);
    std::string embedded("1,xw7\0,xr1", 10);      // a NUL inside the line: refused whole, not cut short
    acceptCard(String(embedded));
    assert(!memcmp(good, cardSides, sizeof(good)) && cardRejected == 12);
    acceptCard(String(std::string("1,xw") + std::string(300, '9')));
    assert(!memcmp(good, cardSides, sizeof(good)) && cardRejected == 13);
    return 0;
  }
  if (mode == "fuzz") {                    // random and mutated lines: never a crash or an overread (run under the sanitizers)
    srand(7);
    const char *seeds[] = {"1,xw62,xr259000,xa95,xs2,lw75,lr259000,lh40,lk5400,la120,ls-,leSign-in needed",
                           "1,xw<,xr59,xs0o,lw0,leNo reading", "1,lw-,lr-,lh-,lk-,la-,ls-,leAccess blocked"};
    int accepted = 0;
    for (int i = 0; i < 20000; i++) {
      std::string line = seeds[i % 3];
      const int edits = 1 + rand() % 4;
      for (int e = 0; e < edits && !line.empty(); e++) {
        const size_t at = (size_t)rand() % line.size();
        switch (rand() % 5) {
          case 0: line[at] = (char)(rand() % 256); break;
          case 1: line.erase(at, 1 + rand() % 3); break;
          case 2: line.insert(at, 1, ",xwlrhkase0123456789<-o ,"[rand() % 26]); break;
          case 3: line.resize(at); break;
          case 4: line += line.substr(0, (size_t)rand() % line.size()); break;
        }
      }
      CardSide before[2];
      memcpy(before, cardSides, sizeof(before));
      const unsigned long rejected = cardRejected;
      acceptCard(String(line));
      if (cardRejected != rejected) assert(!memcmp(before, cardSides, sizeof(before)));
      else ++accepted;
      for (int s = 0; s < 2; s++) {        // whatever was accepted is inside every documented bound
        const CardSide &c = cardSides[s];
        assert(c.week >= -1 && c.week <= 101 && c.hours >= -1 && c.hours <= 101 && c.saved >= -1 && c.saved <= 99);
        assert(c.weekReset >= -1 && c.weekReset <= 9999999 && c.hoursReset >= -1 && c.hoursReset <= 99999 && c.age >= -1 && c.age <= 99999);
        assert(strlen(c.why) <= 17);
      }
    }
    printf("accepted %d of 20000\n", accepted);
    return 0;
  }
  if (mode == "formats") {                 // the words for numbers, exactly
    char out[32];
    struct { int32_t seconds; const char *span; } spans[] = {{-1, "--"}, {0, "<1 min"}, {59, "<1 min"}, {60, "1 min"}, {719, "11 min"},
        {3599, "59 min"}, {3600, "1h 0m"}, {5400, "1h 30m"}, {86399, "23h 59m"}, {86400, "1d 0h"}, {259000, "2d 23h"}, {9999999, "115d 17h"}};
    for (auto &c : spans) { cardSpan(out, sizeof(out), c.seconds); assert(std::string(out) == c.span); }
    struct { int32_t seconds; const char *age; } ages[] = {{-1, "--"}, {0, "0 s"}, {42, "42 s"}, {59, "59 s"}, {60, "1 min"}, {185, "3 min"}};
    for (auto &c : ages) { cardAgeText(out, sizeof(out), c.seconds); assert(std::string(out) == c.age); }
    struct { int16_t value; const char *text; } percents[] = {{-1, "--"}, {0, "0%"}, {1, "1%"}, {62, "62%"}, {100, "100%"}, {CARD_BELOW_ONE, "<1%"}};
    for (auto &c : percents) { cardPercent(out, sizeof(out), c.value); assert(std::string(out) == c.text); }
    // The countdowns run from the moment the line arrived and never go below zero or turn unknown into a number.
    acceptCard(String("1,xw50,xr100,xa10"));
    cardAt = 5000;
    assert(cardLeft(cardSides[0].weekReset, 5000) == 100 && cardLeft(cardSides[0].weekReset, 65000) == 40 && cardLeft(cardSides[0].weekReset, 500000) == 0);
    assert(cardOlder(cardSides[0].age, 65000) == 70 && cardLeft(-1, 99999) == -1 && cardOlder(-1, 99999) == -1);
    cardAt = 0xFFFFFF00u;                    // the 32-bit millisecond clock wraps between arrival and now
    assert(cardLeft(100, 0x100u) == 100 && cardLeft(100, 0x100u + 60000u) == 40 && cardOlder(10, 0x100u + 60000u) == 70);
    return 0;
  }
  return 2;
}
'''


def source(fonts):
    cpp = (ROOT / 'src/main.cpp').read_text()
    block = cpp[cpp.index('// ---- details card'):cpp.index('// ---- end details card')]
    # serviceCard and its forward declaration need the page drawing of main.cpp; the harness has its own stand-ins.
    return MOCK + block + MAIN


def build(directory, fonts=True, swap_rb=False):
    """Compile the card harness. With `fonts` (and the TFT_eSPI tables present) the drawing is real."""
    name = ('card_fonts' if fonts else 'card') + ('_swapped' if swap_rb else '')
    path = Path(directory) / (name + '.cpp')
    path.write_text(source(fonts))
    exe = Path(directory) / name
    command = [shutil.which('g++'), '-std=c++17', '-O1', '-g', '-Wall', '-Wextra', '-Werror', '-Wno-unused-function',
               '-fsanitize=address,undefined', '-fno-omit-frame-pointer']
    if fonts:
        command += ['-DWITH_FONTS', '-I', str(FONTS)]
    if swap_rb:
        command += ['-DHARNESS_SWAP_RB']
    subprocess.run(command + [str(path), '-o', str(exe)], check=True, capture_output=True, text=True)
    return exe


def fonts_available():
    return (FONTS / 'Font16.c').is_file() and (FONTS / 'Font32rle.c').is_file()
