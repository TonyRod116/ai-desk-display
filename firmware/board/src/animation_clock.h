#pragma once
#include <stdint.h>

inline bool validAnimationSpeed(int percent) {
  return percent == 75 || percent == 100 || percent == 125;
}

// An animation timeline, separate from touch, wall time and network deadlines.
// Changing the rate never changes its current position or hardware frame cap.
class AnimationClock {
  uint32_t last = 0, value = 0, fraction = 0;
  int rate = 100;
  bool initialized = false;
public:
  uint32_t time(uint32_t now) {
    if (!initialized) { initialized = true; last = now; value = now; return value; }
    uint64_t scaled = uint64_t(uint32_t(now - last)) * rate + fraction;
    value += uint32_t(scaled / 100);
    fraction = uint32_t(scaled % 100);
    last = now;
    return value;
  }
  bool setSpeed(uint32_t now, int percent) {
    if (!validAnimationSpeed(percent)) return false;
    time(now);
    rate = percent;
    return true;
  }
  int speed() const { return rate; }
};
