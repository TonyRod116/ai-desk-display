#pragma once
#include <stdint.h>

enum class Gesture { None, Page, Mode, Connect };
inline Gesture gesture(uint32_t held) {
  return held >= 5000 ? Gesture::Connect : held >= 2000 ? Gesture::Mode :
         held > 30 ? Gesture::Page : Gesture::None;
}

// Local civil time supplied by the authenticated PC heartbeat. No NTP/cloud.
class RotationClock {
  uint64_t wallMs = 0;
  uint32_t lastTick = 0;
  uint64_t bucket = 0;
  void tick(uint32_t now) {
    if (synced) wallMs += uint32_t(now - lastTick);
    lastTick = now;
  }
  uint64_t currentBucket() const { return mode ? wallMs / (uint64_t(mode)*60000) : 0; }
public:
  int mode = 0; // fixed, half-hour, hour
  bool synced = false;
  void setMode(int value, uint32_t now) {
    tick(now); mode = value == 30 || value == 60 ? value : 0; bucket = currentBucket();
  }
  void sync(uint64_t civilSeconds, uint32_t now) {
    tick(now);
    uint64_t incoming = civilSeconds * 1000;
    uint64_t difference = incoming > wallMs ? incoming-wallMs : wallMs-incoming;
    bool rebase = !synced || difference > 5000;
    wallMs = incoming; synced = true; lastTick = now;
    if (rebase) bucket = currentBucket(); // boot/DST/clock adjustment: no surprise page jump
  }
  bool due(uint32_t now, bool enabled) {
    tick(now);
    if (!synced || !mode) return false;
    uint64_t next = currentBucket(), previous = bucket;
    if (next < previous) return false; // small clock jitter must not replay a boundary
    bucket = next; // suppress catch-up after stale/info/update or long stalls
    return enabled && next == previous + 1;
  }
  unsigned progress(uint32_t now) {
    tick(now);
    return synced && mode ? unsigned((wallMs % (uint64_t(mode)*60000))*100/(uint64_t(mode)*60000)) : 0;
  }
};
