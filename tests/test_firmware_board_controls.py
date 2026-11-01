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
 std::map<std::string,std::string> args;
 int status = 0;
 bool hasArg(const char *key) { return args.count(key); }
 String arg(const char *key) { return String(args[key]); }
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
static bool authorized() { return allowed; }
static uint32_t millis() { return now; }
static void saveSelection() { prefs.putInt("page", page); }
static void applyDisplayOptions() {}
static void drawPage() { ++redraws; }
'''
        checks = r'''
int main() {
 server.args={{"cycle","30"},{"speed","125"}};
 handleConfig(); assert(server.status==401 && prefs.writes==0);
 allowed=true;
 server.args={{"cycle","30x"},{"speed","125"}};
 handleConfig(); assert(server.status==400 && prefs.writes==0 && animationClock.speed()==100);
 server.args={{"cycle","30"},{"speed","125x"}};
 handleConfig(); assert(server.status==400 && prefs.writes==0 && rotationClock.mode==0);
 rotationClock.sync(1800001799ULL,0); // one second before the half hour
 server.args={{"cycle","30"},{"speed","125"}};
 handleConfig();
 assert(server.status==200 && prefs.values["cycle"]==30 && prefs.values["speed0"]==125);
 assert(rotationClock.mode==30 && animationClock.speed()==125 && redraws==1);
 assert(!rotationClock.due(999,true)); assert(rotationClock.due(1000,true));
 assert(!rotationClock.due(1001,true));
 now=1001; server.args={{"speed","75"}}; handleConfig();
 assert(server.status==200 && animationClock.speed()==75 && prefs.values["speed0"]==75);
 assert(rotationClock.mode==30 && prefs.values["cycle"]==30);
 server.args={{"speed","125"},{"speedpage","6"}}; handleConfig();
 assert(server.status==200 && pageSpeeds[6]==125 && prefs.values["speed6"]==125);
 assert(pageSpeeds[0]==75 && animationClock.speed()==75);
 int writes=prefs.writes;
 server.args={{"speed","100"},{"holdmode","1"},{"holdconnect","4"}}; handleConfig();
 assert(server.status==400 && prefs.writes==writes && animationClock.speed()==75);
 server.args={{"holdmode","1"},{"holdconnect","7"}}; handleConfig();
 assert(server.status==200 && modeHoldSeconds==1 && connectHoldSeconds==7);
 assert(prefs.values["holdmode"]==1 && prefs.values["holdconnect"]==7);
 server.args={{"speed","100"},{"speedpage","8"}}; handleConfig();
 assert(server.status==400 && prefs.values["speed0"]==75);
 page=6; pageSpeeds[0]=pageSpeeds[6]=100; modeHoldSeconds=2; connectHoldSeconds=5;
 restoreControls();
 assert(pageSpeeds[0]==75 && pageSpeeds[6]==125 && animationClock.speed()==125);
 assert(modeHoldSeconds==1 && connectHoldSeconds==7);
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
