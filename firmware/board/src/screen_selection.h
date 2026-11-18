#pragma once

constexpr unsigned pageMask(int count) { return (1u << count) - 1u; }

inline int nextEnabledPage(int from, int count, unsigned enabled, unsigned stored) {
  const unsigned present = enabled & stored;
  const unsigned mask = present ? present : enabled;
  for (int step = 1; step <= count; ++step) {
    const int slot = (from + step) % count;
    if (mask & (1u << slot)) return slot;
  }
  return from;
}
