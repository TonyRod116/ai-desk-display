"""Run the firmware's real over-the-wifi update handlers with a fake Update library.

The physical gate (the token AND the connection screen on display) must stay exactly as it is, and every chunk feeds the
watchdog. Only device edges are faked; handleUpdateUpload and handleUpdateDone are cut out of main.cpp as they are.
"""
from pathlib import Path
import shutil
import subprocess

MOCK = r'''
#include <algorithm>
#include <cassert>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <string>
using String = std::string;
using std::max;
static unsigned long now = 1000, lastFeed = 1000, maxFeedGap = 0;
static int feeds = 0, restarts = 0, drawn = 0, messages = 0, status = 0;
static std::string sentBody;
static void delay(int n) { now += n; }
static void feedWatchdog() { feeds++; maxFeedGap = max(maxFeedGap, now - lastFeed); lastFeed = now; }
static bool auth = false, showingInfo = false, showingCard = false, stale = false;
static bool authorized() { return auth; }
static void message(const char *, const char * = "", const char * = "") { ++messages; }
static void drawPage() { ++drawn; }
static const size_t UPDATE_SIZE_UNKNOWN = 0xFFFFFFFF;
static bool updateAllowed = false, updateStarted = false, updateOk = false;
struct UpdateLib {
  int begins = 0, writes = 0, ends = 0, aborts = 0;
  size_t bytes = 0;
  bool failBegin = false, failWrite = false, endOk = true;
  bool begin(size_t) { ++begins; return !failBegin; }
  size_t write(const uint8_t *, size_t n) { ++writes; now += 50; if (failWrite) return 0; bytes += n; return n; }
  bool end(bool) { ++ends; now += 800; return endOk; }
  void abort() { ++aborts; }
} Update;
enum { UPLOAD_FILE_START, UPLOAD_FILE_WRITE, UPLOAD_FILE_END, UPLOAD_FILE_ABORTED };
struct HTTPUpload { int status; size_t currentSize; uint8_t buf[1024]; };
struct Server {
  HTTPUpload u;
  HTTPUpload &upload() { return u; }
  void send(int code, const char *, const char *body) { status = code; sentBody = body; }
} server;
struct Device { void restart() { ++restarts; } } ESP;

'''

HELPERS = r'''
static void chunk(int phase, size_t size = 0) { server.u.status = phase; server.u.currentSize = size; handleUpdateUpload(); }
// A whole upload of `chunks` pieces, then the handler that answers it.
static void upload(int chunks) {
  chunk(UPLOAD_FILE_START);
  for (int i = 0; i < chunks; i++) chunk(UPLOAD_FILE_WRITE, 1024);
  chunk(UPLOAD_FILE_END);
  handleUpdateDone();
}
static void reset() {
  Update = UpdateLib(); auth = showingInfo = showingCard = stale = false; updateAllowed = updateStarted = updateOk = false;
  now = lastFeed = 1000; maxFeedGap = 0; feeds = restarts = drawn = messages = status = 0; sentBody.clear();
}
'''

MAIN = r'''
int main(int argc, char **argv) {
  assert(argc == 2);
  std::string mode = argv[1];
  reset();
  if (mode == "no_token_no_update") {
    auth = false; showingInfo = true;
    upload(400);
    assert(Update.begins == 0 && Update.writes == 0 && restarts == 0 && status == 401 && sentBody == "token");
  } else if (mode == "token_without_the_connection_screen_is_not_enough") {
    auth = true; showingInfo = false;
    upload(400);
    assert(Update.begins == 0 && Update.writes == 0 && restarts == 0 && status == 401 && sentBody == "touch");
  } else if (mode == "a_details_card_is_not_the_connection_screen") {
    auth = true; showingInfo = false; showingCard = true;
    upload(400);
    assert(Update.begins == 0 && restarts == 0 && status == 401 && sentBody == "touch");
  } else if (mode == "stale_screen_is_not_the_connection_screen") {
    auth = true; showingInfo = false; stale = true;
    upload(10);
    assert(Update.begins == 0 && restarts == 0 && status == 401);
  } else if (mode == "token_and_connection_screen_install_and_restart") {
    auth = true; showingInfo = true;
    upload(1000);
    assert(Update.begins == 1 && Update.writes == 1000 && Update.bytes == 1024u * 1000 && Update.ends == 1);
    assert(status == 200 && sentBody == "OK" && restarts == 1);
    assert(feeds >= 1000 && maxFeedGap <= 1000);          // a megabyte of flash writes never nears the watchdog
  } else if (mode == "a_bad_image_is_refused_and_the_board_keeps_running") {
    auth = true; showingInfo = true; Update.endOk = false;
    upload(100);
    assert(status == 400 && sentBody == "bad firmware" && restarts == 0 && drawn >= 1);
  } else if (mode == "a_failed_write_aborts_the_update") {
    auth = true; showingInfo = true; Update.failWrite = true;
    upload(10);
    assert(Update.aborts == 1 && Update.ends == 0 && restarts == 0 && status == 400);
  } else if (mode == "an_aborted_upload_is_cleaned_up") {
    auth = true; showingInfo = true;
    chunk(UPLOAD_FILE_START); chunk(UPLOAD_FILE_WRITE, 1024); chunk(UPLOAD_FILE_ABORTED);
    assert(Update.aborts == 1 && !updateStarted);
  } else { return 2; }
  return 0;
}
'''

MODES = (
    'no_token_no_update',
    'token_without_the_connection_screen_is_not_enough',
    'a_details_card_is_not_the_connection_screen',
    'stale_screen_is_not_the_connection_screen',
    'token_and_connection_screen_install_and_restart',
    'a_bad_image_is_refused_and_the_board_keeps_running',
    'a_failed_write_aborts_the_update',
    'an_aborted_upload_is_cleaned_up',
)


def build(directory):
    cpp = (Path(__file__).resolve().parents[1] / 'src/main.cpp').read_text()
    handlers = cpp[cpp.index('static void handleUpdateDone()'):cpp.index('static void handleShow()')]
    source = Path(directory) / 'update.cpp'
    # The update flags are declared in main.cpp (before the handlers); the harness declares them itself in MOCK.
    source.write_text(MOCK + handlers + HELPERS + MAIN)
    exe = Path(directory) / 'update'
    subprocess.run([shutil.which('g++'), '-std=c++17', '-O1', '-g', '-Wall', '-Wextra', '-Werror',
                    '-fsanitize=address,undefined', '-fno-omit-frame-pointer', str(source), '-o', str(exe)],
                   check=True, capture_output=True, text=True)
    return exe
