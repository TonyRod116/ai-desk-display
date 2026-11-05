"""Run the firmware's real build-trial, rollback and watchdog code through simulated boots.

The block of main.cpp between the "build trial, rollback and watchdog" markers is compiled as it is. Only the device edges are
faked: the NVS (kept across simulated restarts), the two OTA slots and their app descriptors, the reset reason, the
restart itself and the task watchdog. No board, network or flash is touched.
"""
from pathlib import Path
import shutil
import subprocess

MOCK = r'''
#include <cassert>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <map>
#include <string>
#include <vector>

struct String : std::string {
  String() {}
  String(const char *s) : std::string(s) {}
  String(const std::string &s) : std::string(s) {}
  bool endsWith(const String &suffix) const {
    return size() >= suffix.size() && compare(size() - suffix.size(), suffix.size(), suffix) == 0;
  }
};
inline String operator+(const String &a, const String &b) { return String(static_cast<const std::string &>(a) + static_cast<const std::string &>(b)); }
inline String operator+(const String &a, const char *b) { return String(static_cast<const std::string &>(a) + b); }
inline String operator+(const char *a, const String &b) { return String(std::string(a) + static_cast<const std::string &>(b)); }

// ---- the device edges ----
typedef int esp_err_t;
static const esp_err_t ESP_OK = 0, ESP_ERR_NOT_FOUND = 0x105, ESP_ERR_OTA_VALIDATE_FAILED = 0x1500 + 2;
enum esp_reset_reason_t { ESP_RST_UNKNOWN, ESP_RST_POWERON, ESP_RST_EXT, ESP_RST_SW, ESP_RST_PANIC, ESP_RST_INT_WDT,
                          ESP_RST_TASK_WDT, ESP_RST_WDT, ESP_RST_DEEPSLEEP, ESP_RST_BROWNOUT, ESP_RST_SDIO };
static esp_reset_reason_t mockReason = ESP_RST_POWERON;
static esp_reset_reason_t esp_reset_reason() { return mockReason; }

struct esp_app_desc_t { uint8_t app_elf_sha256[32]; };
struct esp_partition_t { uint32_t address; int index; };

struct Image { const char *fw; uint8_t sha[6]; bool healthy; bool logic; };   // logic=false: firmware 41 and older
enum Kind { Empty, Junk, App, BadApp };                                       // BadApp: a descriptor, but the image fails to validate
struct Slot { Kind kind; Image image; esp_partition_t part; };
static Slot slots[2];
static int running = 0, selected = 0;
static int setBootCalls = 0, setBootOk = 0;

static const esp_partition_t *esp_ota_get_running_partition() { return &slots[running].part; }
static const esp_partition_t *esp_ota_get_next_update_partition(const esp_partition_t *) { return &slots[1 - running].part; }
static esp_err_t esp_ota_get_partition_description(const esp_partition_t *p, esp_app_desc_t *desc) {
  const Slot &s = slots[p->index];
  if (s.kind == Empty || s.kind == Junk) return ESP_ERR_NOT_FOUND;
  memset(desc->app_elf_sha256, 0, 32);
  memcpy(desc->app_elf_sha256, s.image.sha, 6);
  return ESP_OK;
}
static esp_err_t esp_ota_set_boot_partition(const esp_partition_t *p) {
  ++setBootCalls;
  if (slots[p->index].kind != App) return ESP_ERR_OTA_VALIDATE_FAILED;
  selected = p->index;
  ++setBootOk;
  return ESP_OK;
}

struct Restart {};
struct Device { void restart() { throw Restart{}; } } ESP;

// An NVS that survives every simulated restart. putString can be made to fail (a full NVS).
struct Preferences {
  std::map<std::string, std::string> strings;
  std::map<std::string, int> ints;
  bool failStrings = false;
  int writes = 0;
  String getString(const char *key, const char *fallback) { return strings.count(key) ? String(strings[key]) : String(fallback); }
  size_t putString(const char *key, const String &value) { if (failStrings) return 0; strings[key] = value; ++writes; return value.size(); }
  int getInt(const char *key, int fallback) { return ints.count(key) ? ints[key] : fallback; }
  size_t putInt(const char *key, int value) { ints[key] = value; ++writes; return 4; }
  bool isKey(const char *key) { return strings.count(key) || ints.count(key); }
  bool remove(const char *key) { bool had = isKey(key); strings.erase(key); ints.erase(key); if (had) ++writes; return had; }
} prefs;

static const char *FIRMWARE = "ai-desk-display 42";

// The task watchdog: remembers how it was configured and whether the loop task is watched.
static int wdtInits = 0, wdtSeconds = 0, wdtAdds = 0, wdtDeletes = 0, wdtResets = 0;
static bool wdtPanic = false, wdtWatched = false;
static esp_err_t esp_task_wdt_init(uint32_t seconds, bool panic) { ++wdtInits; wdtSeconds = (int)seconds; wdtPanic = panic; return ESP_OK; }
static esp_err_t esp_task_wdt_status(void *) { return wdtWatched ? ESP_OK : ESP_ERR_NOT_FOUND; }
static esp_err_t esp_task_wdt_reset() { ++wdtResets; return wdtWatched ? ESP_OK : ESP_ERR_NOT_FOUND; }
static void enableLoopWDT() { ++wdtAdds; wdtWatched = true; }
static void disableLoopWDT() { ++wdtDeletes; wdtWatched = false; }
'''

MAIN = r'''
// ---- the simulation ----
static const char *KEEP[] = {"token", "page", "np", "cycle", "speed0", "speed5", "holdmode", "holdconnect", "rot", "inv",
                             "swap", "bswap", "srest", "bright", "wifi.ssid", "wifi.pass"};
static void fillForeignKeys() {
  prefs.strings["token"] = "0123456789abcdef"; prefs.strings["wifi.ssid"] = "home"; prefs.strings["wifi.pass"] = "secret";
  prefs.ints["page"] = 4; prefs.ints["np"] = 8; prefs.ints["cycle"] = 30; prefs.ints["speed0"] = 125; prefs.ints["speed5"] = 75;
  prefs.ints["holdmode"] = 3; prefs.ints["holdconnect"] = 7; prefs.ints["rot"] = 3; prefs.ints["inv"] = 1; prefs.ints["swap"] = 0;
  prefs.ints["bswap"] = 0; prefs.ints["srest"] = 2; prefs.ints["bright"] = 25;
}
static void assertForeignKeysUntouched() {
  for (const char *key : KEEP) {
    bool a = prefs.strings.count(key) || prefs.ints.count(key);
    assert(a);
  }
  assert(prefs.strings["token"] == "0123456789abcdef" && prefs.strings["wifi.ssid"] == "home" && prefs.strings["wifi.pass"] == "secret");
  assert(prefs.ints["page"] == 4 && prefs.ints["np"] == 8 && prefs.ints["cycle"] == 30 && prefs.ints["speed0"] == 125 &&
         prefs.ints["speed5"] == 75 && prefs.ints["holdmode"] == 3 && prefs.ints["holdconnect"] == 7 && prefs.ints["rot"] == 3 &&
         prefs.ints["inv"] == 1 && prefs.ints["swap"] == 0 && prefs.ints["bswap"] == 0 && prefs.ints["srest"] == 2 &&
         prefs.ints["bright"] == 25);
}
static Image img(const char *fw, uint8_t id, bool healthy, bool logic = true) {
  Image i{fw, {id, 0x11, 0x22, 0x33, 0x44, 0x55}, healthy, logic};
  return i;
}
static void install(int index, Kind kind, Image image) {
  slots[index].kind = kind; slots[index].image = image; slots[index].part = {index == 0 ? 0x10000u : 0x110000u, index};
}
static void resetRam() { buildSha = ""; buildOnTrial = false; buildArrivedByRollback = false; fallbackReady = false; buildStrikes = 0; watchdogArmed = false; wdtWatched = false; }

static int boots = 0, restartsByRollback = 0;
// One boot of the image in the running slot. Returns false when setup() handed the board to the other slot.
static bool boot(esp_reset_reason_t reason) {
  mockReason = reason;
  FIRMWARE = slots[running].image.fw;
  resetRam();
  ++boots;
  if (!slots[running].image.logic) return true;
  try { checkBuildTrial(); armWatchdog(); } catch (Restart &) { running = selected; ++restartsByRollback; return false; }
  return true;
}
// Boots until the running image is healthy (and has confirmed itself) or `limit` boots passed.
// A crashing image dies after each boot (panic); the boot after a rollback comes from a software restart.
static void runBoots(int limit, esp_reset_reason_t first = ESP_RST_SW) {
  esp_reset_reason_t reason = first;
  while (boots < limit) {
    if (!boot(reason)) { reason = ESP_RST_SW; continue; }
    const Image &im = slots[running].image;
    if (im.healthy) { if (im.logic) confirmBuild(120000); return; }
    reason = ESP_RST_PANIC;
  }
}

static std::string fw() { return slots[running].image.fw; }

int main(int argc, char **argv) {
  assert(argc == 2);
  std::string mode = argv[1];
  fillForeignKeys();
  if (mode == "healthy_confirms_after_a_minute_and_a_half") {
    install(0, App, img("ai-desk-display 42", 0x42, true)); install(1, App, img("ai-desk-display 41", 0x41, true, false));
    assert(boot(ESP_RST_SW) && buildOnTrial && buildStrikes == 0 && fallbackReady);
    confirmBuild(89999); assert(buildOnTrial && !prefs.isKey("fwgood"));          // too early
    confirmBuild(90000); assert(!buildOnTrial && prefs.strings["fwgood"] == "ai-desk-display 42 421122334455");
    assert(!prefs.isKey("fwtries") && !prefs.isKey("fwtrial") && !prefs.isKey("fwrbto"));
    int writes = prefs.writes; confirmBuild(200000); assert(prefs.writes == writes);   // a second heartbeat writes nothing
    assert(boot(ESP_RST_SW) && !buildOnTrial);                                    // and the next boot is not on trial
    assertForeignKeysUntouched();
  } else if (mode == "a_crashing_trial_goes_back_to_the_previous_image_once") {
    install(0, App, img("ai-desk-display 42", 0x42, false)); install(1, App, img("ai-desk-display 41", 0x41, true, false));
    runBoots(50);
    assert(running == 1 && restartsByRollback == 1 && setBootOk == 1);
    assert(boots == 5);   // install restart, three deaths counted, then the switch and the old image
    assert(fw() == "ai-desk-display 41");
    assertForeignKeysUntouched();
    assert(prefs.strings["fwrbto"].size() == 12 && prefs.ints["fwtries"] == 0);
  } else if (mode == "two_deaths_are_not_enough") {
    install(0, App, img("ai-desk-display 42", 0x42, false)); install(1, App, img("ai-desk-display 41", 0x41, true, false));
    boot(ESP_RST_SW); boot(ESP_RST_PANIC); boot(ESP_RST_TASK_WDT);
    assert(running == 0 && buildStrikes == 2 && setBootCalls == 0);
  } else if (mode == "an_empty_or_junk_other_slot_stays_put") {
    for (Kind kind : {Empty, Junk}) {
      prefs = Preferences(); fillForeignKeys(); boots = 0; setBootCalls = 0; setBootOk = 0; restartsByRollback = 0; running = 0;
      install(0, App, img("ai-desk-display 42", 0x42, false)); install(1, kind, img("junk", 0x00, true, false));
      runBoots(60);
      assert(boots == 60 && running == 0 && setBootCalls == 0 && !fallbackReady);
      assertForeignKeysUntouched();
    }
  } else if (mode == "an_image_that_fails_validation_is_not_retried_in_a_loop") {
    install(0, App, img("ai-desk-display 42", 0x42, false)); install(1, BadApp, img("ai-desk-display 41", 0x41, true, false));
    runBoots(100);
    assert(running == 0 && restartsByRollback == 0);
    assert(setBootCalls == 33);   // one attempt per three deaths (boots 4, 7, 10, ...), never one per boot
    assert(!prefs.isKey("fwrbto"));
  } else if (mode == "the_same_image_in_both_slots_is_no_fallback") {
    install(0, App, img("ai-desk-display 42", 0x42, false)); install(1, App, img("ai-desk-display 42", 0x42, false));
    runBoots(40);
    assert(running == 0 && setBootCalls == 0 && !fallbackReady);
  } else if (mode == "two_bad_builds_never_bounce_between_the_slots") {
    install(0, App, img("ai-desk-display 43", 0x43, false)); install(1, App, img("ai-desk-display 42", 0x42, false));
    runBoots(2000);
    assert(boots == 2000);
    assert(setBootOk == 1 && restartsByRollback == 1 && running == 1);
    assertForeignKeysUntouched();
  } else if (mode == "a_good_older_build_that_returns_does_not_switch_again") {
    // 42 is confirmed good; 43 is installed, dies three times and the board returns to 42.
    install(0, App, img("ai-desk-display 42", 0x42, true)); install(1, App, img("ai-desk-display 41", 0x41, true, false));
    runBoots(5); assert(!buildOnTrial && prefs.isKey("fwgood"));
    install(1, App, img("ai-desk-display 43", 0x43, false)); running = 1;       // the OTA wrote the other slot and restarted into it
    boots = 0; runBoots(50);
    assert(running == 0 && fw() == "ai-desk-display 42" && restartsByRollback == 1);
    assert(!buildOnTrial);                                                    // 42 is still the confirmed build
    assert(!prefs.isKey("fwrbto") && !prefs.isKey("fwtries"));                // its own boot cleaned the marks
    // 42 then dies ten times (a brown-out storm): it is a confirmed build, so nothing can undo it.
    int calls = setBootCalls;
    for (int i = 0; i < 10; i++) { assert(boot(ESP_RST_BROWNOUT)); assert(!buildOnTrial); }
    assert(setBootCalls == calls && running == 0);
    assertForeignKeysUntouched();
  } else if (mode == "only_the_confirmed_build_is_a_fallback") {
    // 42 was confirmed; someone then wrote another image into the other slot over USB: not a way back.
    install(0, App, img("ai-desk-display 42", 0x42, true)); install(1, App, img("ai-desk-display 41", 0x41, true, false));
    runBoots(5);
    install(1, App, img("ai-desk-display 43", 0x43, false)); running = 1; boots = 0;
    install(0, App, img("ai-desk-display 99", 0x99, true, false));             // a stranger now fills the slot 42 had
    runBoots(60);
    assert(running == 1 && setBootCalls == 0 && !fallbackReady);
  } else if (mode == "a_pc_that_is_off_never_undoes_anything") {
    for (bool confirmed : {false, true}) {
      prefs = Preferences(); fillForeignKeys(); boots = 0; setBootCalls = 0; setBootOk = 0; restartsByRollback = 0; running = 0;
      install(0, App, img("ai-desk-display 42", 0x42, true)); install(1, App, img("ai-desk-display 41", 0x41, true, false));
      assert(boot(ESP_RST_SW));
      if (confirmed) confirmBuild(120000);
      for (int i = 0; i < 1000; i++) {   // silence restarts, power cuts, the reset button, USB serial resets
        esp_reset_reason_t reason = i % 3 == 0 ? ESP_RST_SW : i % 3 == 1 ? ESP_RST_POWERON : ESP_RST_EXT;
        assert(boot(reason));
      }
      assert(running == 0 && setBootCalls == 0 && buildStrikes == 0);
      assert(confirmed == !buildOnTrial);
      assertForeignKeysUntouched();
    }
  } else if (mode == "brown_outs_and_watchdogs_count_but_a_reset_button_does_not") {
    install(0, App, img("ai-desk-display 42", 0x42, false)); install(1, App, img("ai-desk-display 41", 0x41, true, false));
    boot(ESP_RST_SW); boot(ESP_RST_BROWNOUT); assert(buildStrikes == 1);
    boot(ESP_RST_EXT); boot(ESP_RST_POWERON); boot(ESP_RST_DEEPSLEEP); boot(ESP_RST_UNKNOWN); assert(buildStrikes == 1);
    boot(ESP_RST_INT_WDT); assert(buildStrikes == 2);
    assert(!boot(ESP_RST_WDT) && running == 1);                                // the third death hands the board back
  } else if (mode == "strikes_belong_to_the_build_that_earned_them") {
    install(0, App, img("ai-desk-display 42", 0x42, false)); install(1, App, img("ai-desk-display 41", 0x41, true, false));
    boot(ESP_RST_SW); boot(ESP_RST_PANIC); boot(ESP_RST_PANIC); assert(buildStrikes == 2);
    install(0, App, img("ai-desk-display 43", 0x43, false));                    // another build is installed over it
    assert(boot(ESP_RST_SW) && buildStrikes == 0);
    assert(boot(ESP_RST_PANIC) && buildStrikes == 1 && running == 0);
  } else if (mode == "a_full_nvs_keeps_the_build_on_trial_until_it_can_be_saved") {
    install(0, App, img("ai-desk-display 42", 0x42, true)); install(1, App, img("ai-desk-display 41", 0x41, true, false));
    boot(ESP_RST_SW);
    prefs.failStrings = true;
    confirmBuild(120000); assert(buildOnTrial && !prefs.isKey("fwgood"));
    prefs.failStrings = false;
    confirmBuild(180000); assert(!buildOnTrial && prefs.isKey("fwgood"));
  } else if (mode == "a_first_trial_without_any_record_accepts_a_valid_app") {
    // Firmware 41 knows nothing of "fwgood": the first trial goes back to whatever valid app is there.
    install(0, App, img("ai-desk-display 42", 0x42, false)); install(1, App, img("ai-desk-display 41", 0x41, true, false));
    assert(!prefs.isKey("fwgood"));
    runBoots(20);
    assert(running == 1 && restartsByRollback == 1);
  } else if (mode == "an_image_without_a_sha_is_never_trusted_as_a_fallback_once_a_build_is_confirmed") {
    install(0, App, img("ai-desk-display 42", 0x42, true)); install(1, App, img("ai-desk-display 41", 0x41, true, false));
    runBoots(5);
    install(1, App, img("ai-desk-display 43", 0x43, false)); running = 1; boots = 0;
    memset(slots[0].image.sha, 0, 6);                                           // the slot of 42 reads back without a sha
    runBoots(40);
    assert(running == 1 && setBootCalls == 0);
  } else if (mode == "an_image_without_a_sha_still_has_an_identity") {
    install(0, App, img("ai-desk-display 42", 0x00, true)); memset(slots[0].image.sha, 0, 6);
    install(1, App, img("ai-desk-display 41", 0x41, true, false));
    assert(boot(ESP_RST_SW) && buildSha == "" && buildOnTrial);
    confirmBuild(120000); assert(prefs.strings["fwgood"] == "ai-desk-display 42");
    assert(boot(ESP_RST_SW) && !buildOnTrial);
  } else if (mode == "the_watchdog_is_armed_for_two_minutes_and_paused_for_the_portal") {
    install(0, App, img("ai-desk-display 42", 0x42, true)); install(1, App, img("ai-desk-display 41", 0x41, true, false));
    assert(boot(ESP_RST_SW));
    assert(wdtInits == 1 && wdtSeconds == 120 && wdtPanic && wdtWatched && watchdogArmed && wdtAdds == 1);
    pauseWatchdog(); assert(!wdtWatched && !watchdogArmed);                    // the Wi-Fi setup portal waits for a person
    armWatchdog(); assert(wdtWatched && watchdogArmed && wdtInits == 2 && wdtAdds == 2);
    armWatchdog(); assert(wdtAdds == 2);                                        // never subscribed twice
    int resets = wdtResets; feedWatchdog(); assert(wdtResets == resets + 1);
  } else { return 2; }
  return 0;
}
'''

MODES = (
    'healthy_confirms_after_a_minute_and_a_half',
    'a_crashing_trial_goes_back_to_the_previous_image_once',
    'two_deaths_are_not_enough',
    'an_empty_or_junk_other_slot_stays_put',
    'an_image_that_fails_validation_is_not_retried_in_a_loop',
    'the_same_image_in_both_slots_is_no_fallback',
    'two_bad_builds_never_bounce_between_the_slots',
    'a_good_older_build_that_returns_does_not_switch_again',
    'only_the_confirmed_build_is_a_fallback',
    'a_pc_that_is_off_never_undoes_anything',
    'brown_outs_and_watchdogs_count_but_a_reset_button_does_not',
    'strikes_belong_to_the_build_that_earned_them',
    'a_full_nvs_keeps_the_build_on_trial_until_it_can_be_saved',
    'a_first_trial_without_any_record_accepts_a_valid_app',
    'an_image_without_a_sha_is_never_trusted_as_a_fallback_once_a_build_is_confirmed',
    'an_image_without_a_sha_still_has_an_identity',
    'the_watchdog_is_armed_for_two_minutes_and_paused_for_the_portal',
)


def source():
    cpp = (Path(__file__).resolve().parents[1] / 'src/main.cpp').read_text()
    start = cpp.index('// ---- build trial, rollback and watchdog')
    end = cpp.index('// ---- end build trial, rollback and watchdog')
    return MOCK + cpp[start:end] + MAIN


def build(directory):
    path = Path(directory) / 'trial.cpp'
    path.write_text(source())
    exe = Path(directory) / 'trial'
    subprocess.run([shutil.which('g++'), '-std=c++17', '-O1', '-g', '-Wall', '-Wextra', '-Werror',
                    '-fsanitize=address,undefined', '-fno-omit-frame-pointer', str(path), '-o', str(exe)],
                   check=True, capture_output=True, text=True)
    return exe
