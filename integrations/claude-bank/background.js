import {PAIRING} from './pairing.js';
import {collect} from './reader.mjs';

const ALARM = 'token-tv-claude-bank';
let busy = false, backoff = 1;
async function poll() {
  if (busy) return;
  busy = true;
  try {
    const previous = await chrome.alarms.get(ALARM);
    if (previous?.periodInMinutes >= 1 && previous.periodInMinutes <= 15) backoff = previous.periodInMinutes;
    await collect(PAIRING); backoff = 1;
  }
  catch (error) {
    // No account data, response bodies or secret in browser logs/storage.
    backoff = error.message === 'rate_limited' ? Math.min(backoff * 2, 15) : 1;
  } finally {
    busy = false;
    chrome.alarms.create(ALARM, {delayInMinutes:backoff, periodInMinutes:backoff});
  }
}
chrome.alarms.onAlarm.addListener(alarm => { if (alarm.name === ALARM) void poll(); });
chrome.runtime.onStartup.addListener(() => { void poll(); });
chrome.runtime.onInstalled.addListener(() => { void poll(); });
// Re-establish the alarm even when Chromium discarded it after a restart.
void poll();
