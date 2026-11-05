"""Run the firmware's real backlight and night-mode code with a fake PWM and a fake clock.

The block of main.cpp between the "backlight and night mode" markers is compiled as it is; only the LEDC calls are faked.
"""
from pathlib import Path
import shutil
import subprocess

MOCK = r'''
#include <cassert>
#include <cstdint>
#include <cstdio>
#include <string>
#include <vector>

#define TFT_BL 21
struct Call { std::string what; int a, b, c; };
static std::vector<Call> calls;
static uint32_t lastDuty = 0xFFFFFFFFu;
static int writes = 0;
static void ledcSetup(int channel, uint32_t hz, int bits) { calls.push_back({"setup", channel, (int)hz, bits}); }
// As the real thing: the pin shows the duty only once attached, and attaching re-applies what the hardware reports, which is not
// a duty written a moment before (firmware 42 lit nothing at boot because of this).
static uint32_t pinDuty = 0;
static bool attached = false;
static void ledcWrite(int channel, uint32_t duty) { calls.push_back({"write", channel, (int)duty, 0}); lastDuty = duty; ++writes; if (attached) pinDuty = duty; }
static void ledcAttachPin(int pin, int channel) { calls.push_back({"attach", pin, channel, 0}); attached = true; pinDuty = 0; }
static bool haveBeat = false;
static unsigned long lastBeat = 0;
'''

MAIN = r'''
static void reset() {
  calls.clear(); lastDuty = 0xFFFFFFFFu; writes = 0; haveBeat = false; lastBeat = 0; pinDuty = 0; attached = false;
  brightLevel = 100; shownLevel = -1; wakeSet = false; wakeAt = 0; wokeByTouch = false;
}

int main(int argc, char **argv) {
  assert(argc == 2);
  std::string mode = argv[1];
  reset();
  if (mode == "the_level_is_perceptual_and_never_dark") {
    assert(backlightDuty(100) == 1023);
    assert(backlightDuty(50) == 255 && backlightDuty(25) == 63 && backlightDuty(15) == 23 && backlightDuty(10) == 10);
    for (int level = -50; level <= 150; level++) {
      assert(backlightDuty(level) >= 8);                       // never off: a night screen is dim, not dead
      assert(backlightDuty(level) <= 1023);
      if (level > -50) assert(backlightDuty(level) >= backlightDuty(level - 1));
    }
    assert(backlightDuty(0) == 8 && backlightDuty(-5) == 8 && backlightDuty(1000) == 1023);
    assert(clampLevel(-5) == 0 && clampLevel(250) == 100 && clampLevel(37) == 37);
  } else if (mode == "the_pin_is_handed_to_the_pwm_at_the_saved_level") {
    brightLevel = 25;                                           // a reboot at night
    startBacklight();
    assert(calls.size() == 3);
    assert(calls[0].what == "setup" && calls[0].a == 0 && calls[0].b == 20000 && calls[0].c == 10);   // 20 kHz, 10 bits
    assert(calls[1].what == "attach" && calls[1].a == 21 && calls[1].b == 0);                          // the pin first ...
    assert(calls[2].what == "write" && calls[2].b == 63);       // ... then the saved level, or the backlight stays off
    assert(pinDuty == 63 && shownLevel == 25);
  } else if (mode == "ten_silent_minutes_dim_it_and_a_heartbeat_restores_it") {
    brightLevel = 60; startBacklight(); haveBeat = true; lastBeat = 1000; writes = 0;
    serviceBacklight(1000 + 600000); assert(shownLevel == 60 && writes == 0);          // exactly ten minutes: still the scheduled level
    serviceBacklight(1000 + 600001); assert(shownLevel == 15 && lastDuty == 23 && writes == 1);
    serviceBacklight(1000 + 700000); assert(writes == 1);                              // no write while nothing changes
    lastBeat = 1000 + 800000; serviceBacklight(lastBeat); assert(shownLevel == 60 && lastDuty == backlightDuty(60));
  } else if (mode == "it_is_never_brighter_than_the_schedule_when_dimmed") {
    brightLevel = 10; startBacklight(); haveBeat = true; lastBeat = 0;
    serviceBacklight(700000); assert(shownLevel == 10);                                // the schedule is already below the low level
    brightLevel = 15; serviceBacklight(700000); assert(shownLevel == 15);
    brightLevel = 16; serviceBacklight(700000); assert(shownLevel == 15);
  } else if (mode == "a_board_that_never_heard_the_pc_dims_ten_minutes_after_boot") {
    brightLevel = 25; startBacklight();
    serviceBacklight(599999); assert(shownLevel == 25);
    serviceBacklight(600001); assert(shownLevel == 15);
  } else if (mode == "a_touch_wakes_it_for_a_minute") {
    brightLevel = 25; startBacklight(); haveBeat = true; lastBeat = 0;
    serviceBacklight(700000); assert(shownLevel == 15 && backlightAsleep(700000));
    wakeBacklight(700000); assert(shownLevel == 25 && !backlightAsleep(700000));
    serviceBacklight(700000 + 59999); assert(shownLevel == 25);
    serviceBacklight(700000 + 60000); assert(shownLevel == 15 && backlightAsleep(700000 + 60000));
    wakeBacklight(800000); serviceBacklight(800000 + 30000); assert(shownLevel == 25);   // a later touch starts a new minute
    wakeBacklight(800000 + 30000); serviceBacklight(800000 + 89999); assert(shownLevel == 25);   // and a touch extends it
    serviceBacklight(800000 + 90000); assert(shownLevel == 15);
  } else if (mode == "a_touch_while_awake_changes_nothing_and_swallows_nothing") {
    brightLevel = 25; startBacklight(); haveBeat = true; lastBeat = 100000;
    assert(!backlightAsleep(110000));                                                  // the PC is talking: nobody is asleep
    writes = 0; wakeBacklight(110000); assert(writes == 0 && shownLevel == 25);
  } else if (mode == "an_untouched_board_stays_dim_for_ever_even_after_a_day_of_uptime") {
    brightLevel = 25; startBacklight(); haveBeat = false;
    const unsigned long day = 86400000UL;
    serviceBacklight(day); assert(shownLevel == 15 && backlightAsleep(day));
    serviceBacklight(0xFFFFFF00UL); assert(shownLevel == 15 && backlightAsleep(0xFFFFFF00UL));   // 49 days: wakeSet was never true
  } else if (mode == "the_wake_window_survives_the_millis_wrap") {
    brightLevel = 25; startBacklight(); haveBeat = true; lastBeat = 0xFFFFF000UL - 700000UL;
    unsigned long t = 0xFFFFF000UL;
    serviceBacklight(t); assert(shownLevel == 15);
    wakeBacklight(t); assert(shownLevel == 25);
    serviceBacklight(t + 59000UL); assert(shownLevel == 25);                           // t + 59000 has wrapped past zero
    serviceBacklight(t + 61000UL); assert(shownLevel == 15);
  } else if (mode == "no_phantom_wake_right_after_the_millis_wrap") {
    brightLevel = 25; startBacklight(); haveBeat = true; lastBeat = 0xFFFFF000UL - 700000UL;     // silent for ~12 minutes, never touched
    unsigned long wrapped = 0x200UL;                                                               // the counter has just wrapped
    assert(silentMs(wrapped) > SILENT_DIM_MS);
    serviceBacklight(wrapped); assert(shownLevel == 15 && backlightAsleep(wrapped));
  } else if (mode == "a_heartbeat_returns_the_light_even_during_the_wake_window") {
    brightLevel = 80; startBacklight(); haveBeat = true; lastBeat = 0;
    serviceBacklight(700000); assert(shownLevel == 15);
    haveBeat = true; lastBeat = 710000; serviceBacklight(710000); assert(shownLevel == 80);
  } else if (mode == "changing_the_schedule_changes_the_lamp_at_once") {
    brightLevel = 100; startBacklight(); haveBeat = true; lastBeat = 1000; writes = 0;
    brightLevel = 25; serviceBacklight(2000); assert(shownLevel == 25 && lastDuty == 63 && writes == 1);
    brightLevel = 100; serviceBacklight(3000); assert(shownLevel == 100 && lastDuty == 1023);
  } else { return 2; }
  return 0;
}
'''

MODES = (
    'the_level_is_perceptual_and_never_dark',
    'the_pin_is_handed_to_the_pwm_at_the_saved_level',
    'ten_silent_minutes_dim_it_and_a_heartbeat_restores_it',
    'it_is_never_brighter_than_the_schedule_when_dimmed',
    'a_board_that_never_heard_the_pc_dims_ten_minutes_after_boot',
    'a_touch_wakes_it_for_a_minute',
    'a_touch_while_awake_changes_nothing_and_swallows_nothing',
    'an_untouched_board_stays_dim_for_ever_even_after_a_day_of_uptime',
    'the_wake_window_survives_the_millis_wrap',
    'no_phantom_wake_right_after_the_millis_wrap',
    'a_heartbeat_returns_the_light_even_during_the_wake_window',
    'changing_the_schedule_changes_the_lamp_at_once',
)


def build(directory):
    cpp = (Path(__file__).resolve().parents[1] / 'src/main.cpp').read_text()
    block = cpp[cpp.index('// ---- backlight and night mode'):cpp.index('// ---- end backlight and night mode')]
    path = Path(directory) / 'backlight.cpp'
    path.write_text(MOCK + block + MAIN)
    exe = Path(directory) / 'backlight'
    subprocess.run([shutil.which('g++'), '-std=c++17', '-O1', '-g', '-Wall', '-Wextra', '-Werror',
                    '-fsanitize=address,undefined', '-fno-omit-frame-pointer', str(path), '-o', str(exe)],
                   check=True, capture_output=True, text=True)
    return exe
