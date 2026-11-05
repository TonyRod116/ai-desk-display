"""Compile and exercise the actual firmware configuration handler on the host."""
import pathlib
import shutil
import subprocess
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]


@unittest.skipUnless(shutil.which('g++'), 'needs g++')
class BoardFirmwareControlsTests(unittest.TestCase):
    def test_authorization_validation_persistence_and_clock_alignment(self):
        cpp = (ROOT / 'firmware/board/src/main.cpp').read_text()
        handler = cpp[cpp.index('static void handleConfig()'):cpp.index('// POST /pair?')]
        restore = cpp[cpp.index('  int oldSpeed = prefs.getInt'):cpp.index('  rotation = prefs.getInt')]
        mocks = r'''
#include "rotation.h"
#include "animation_clock.h"
#include <cassert>
#include <cstdlib>
#include <cstdio>
#include <map>
#include <string>
struct String : std::string {
 using std::string::string;
 String(const std::string &s) : std::string(s) {}
 String(int n) : std::string(std::to_string(n)) {}
 int toInt() const { return std::atoi(c_str()); }
};
struct Server {
 std::map<std::string,std::string> kv;
 int status = 0;
 bool hasArg(const char *key) { return kv.count(key); }
 String arg(const char *key) { return String(kv[key]); }
 int args() { return (int)kv.size(); }
 void send(int code, const char *, const char *) { status = code; }
} server;
struct Preferences {
 std::map<std::string,int> values;
 int writes = 0;
 void putInt(const char *key, int value) { values[key]=value; ++writes; }
 void putBool(const char *key, bool value) { values[key]=value; ++writes; }
 int getInt(const char *key, int fallback) { return values.count(key) ? values[key] : fallback; }
} prefs;
static RotationClock rotationClock;
static AnimationClock animationClock;
static uint32_t now = 0;
static bool allowed = false, indicatorMaskValid = true;
static bool invertColors = true, swapRedBlue = false, swapBytes = false;
static int rotation = 1, activePages = 8, page = 0, redraws = 0;
static const int PAGES = 8;
static int pageSpeeds[PAGES] = {100,100,100,100,100,100,100,100};
static int modeHoldSeconds=2, connectHoldSeconds=5;
static int brightLevel = 100, backlightChecks = 0;
static void serviceBacklight(unsigned long) { ++backlightChecks; }
static bool authorized() { return allowed; }
static uint32_t millis() { return now; }
static void saveSelection() { prefs.putInt("page", page); }
static void applyDisplayOptions() {}
static void drawPage() { ++redraws; }
'''
        checks = r'''
int main() {
 server.kv={{"cycle","30"},{"speed","125"}};
 handleConfig(); assert(server.status==401 && prefs.writes==0);
 allowed=true;
 server.kv={{"cycle","30x"},{"speed","125"}};
 handleConfig(); assert(server.status==400 && prefs.writes==0 && animationClock.speed()==100);
 server.kv={{"cycle","30"},{"speed","125x"}};
 handleConfig(); assert(server.status==400 && prefs.writes==0 && rotationClock.mode==0);
 rotationClock.sync(1800001799ULL,0); // one second before the half hour
 server.kv={{"cycle","30"},{"speed","125"}};
 handleConfig();
 assert(server.status==200 && prefs.values["cycle"]==30 && prefs.values["speed0"]==125);
 assert(rotationClock.mode==30 && animationClock.speed()==125 && redraws==1);
 assert(!rotationClock.due(999,true)); assert(rotationClock.due(1000,true));
 assert(!rotationClock.due(1001,true));
 now=1001; server.kv={{"speed","75"}}; handleConfig();
 assert(server.status==200 && animationClock.speed()==75 && prefs.values["speed0"]==75);
 assert(rotationClock.mode==30 && prefs.values["cycle"]==30);
 server.kv={{"speed","125"},{"speedpage","6"}}; handleConfig();
 assert(server.status==200 && pageSpeeds[6]==125 && prefs.values["speed6"]==125);
 assert(pageSpeeds[0]==75 && animationClock.speed()==75);
 int writes=prefs.writes;
 server.kv={{"speed","100"},{"holdmode","1"},{"holdconnect","4"}}; handleConfig();
 assert(server.status==400 && prefs.writes==writes && animationClock.speed()==75);
 server.kv={{"holdmode","1"},{"holdconnect","7"}}; handleConfig();
 assert(server.status==200 && modeHoldSeconds==1 && connectHoldSeconds==7);
 assert(prefs.values["holdmode"]==1 && prefs.values["holdconnect"]==7);
 server.kv={{"speed","100"},{"speedpage","8"}}; handleConfig();
 assert(server.status==400 && prefs.values["speed0"]==75);
 page=6; pageSpeeds[0]=pageSpeeds[6]=100; modeHoldSeconds=2; connectHoldSeconds=5;
 restoreControls();
 assert(pageSpeeds[0]==75 && pageSpeeds[6]==125 && animationClock.speed()==125);
 assert(modeHoldSeconds==1 && connectHoldSeconds==7);

 // Night mode: /config?bright=N is validated strictly, stored only when it changes, and a request that carries
 // nothing else repaints nothing (no page redraw, no panel options re-sent, no unrelated NVS writes).
 for (const char *bad : {"", "-1", "101", "25x", " 25", "+25", "025", "2.5", "abc", "1000000000000"}) {
  int writes=prefs.writes, redraws0=redraws;
  server.kv={{"bright",bad}}; handleConfig();
  assert(server.status==400 && prefs.writes==writes && redraws==redraws0 && brightLevel==100);
 }
 server.kv={{"bright","25"},{"speed","125x"}}; handleConfig();     // one bad option stops everything
 assert(server.status==400 && brightLevel==100 && !prefs.values.count("bright"));
 int redraws1=redraws, writes1=prefs.writes, checks1=backlightChecks;
 server.kv={{"bright","25"}}; handleConfig();
 assert(server.status==200 && brightLevel==25 && prefs.values["bright"]==25);
 assert(prefs.writes==writes1+1 && redraws==redraws1 && backlightChecks==checks1+1);
 writes1=prefs.writes;
 server.kv={{"bright","25"}}; handleConfig();                         // the same level again: no flash write at all
 assert(server.status==200 && prefs.writes==writes1 && redraws==redraws1);
 server.kv={{"bright","0"}}; handleConfig();                          // zero is accepted; the lamp still never goes off
 assert(server.status==200 && brightLevel==0 && prefs.values["bright"]==0);
 server.kv={{"bright","100"}}; handleConfig();
 assert(brightLevel==100);
 allowed=false; writes1=prefs.writes;
 server.kv={{"bright","10"}}; handleConfig();                         // the token is still required
 assert(server.status==401 && brightLevel==100 && prefs.writes==writes1);
 allowed=true;
 server.kv={{"bright","40"},{"cycle","60"}}; handleConfig();          // together with other settings the page is redrawn as before
 assert(server.status==200 && brightLevel==40 && rotationClock.mode==60 && redraws==redraws1+1);
}
'''
        with tempfile.TemporaryDirectory() as directory:
            source = pathlib.Path(directory) / 'controls.cpp'
            executable = pathlib.Path(directory) / 'controls'
            source.write_text(mocks + handler + '\nstatic void restoreControls() {\n' + restore + '\n}\n' + checks)
            subprocess.run(['g++', '-std=c++17', '-Wall', '-Wextra', '-Werror',
                            '-I', str(ROOT / 'firmware/board/src'), str(source),
                            '-o', str(executable)], check=True, capture_output=True)
            subprocess.run([str(executable)], check=True, capture_output=True)
