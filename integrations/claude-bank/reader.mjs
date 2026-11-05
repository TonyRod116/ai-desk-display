// Only first-party GETs. Never read cookies or return identity/grant identifiers.
const HASH = /^[0-9a-f]{64}$/;
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const VERSION = /^\d{1,4}(?:\.\d{1,4}){1,3}$/;
const ISO = /^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})(?:\.\d+)?(Z|[+-]\d{2}:\d{2})$/;

// Why a reading could not be made (Tony, 2026-11-03: the bank was silent for 19 days and the reason was thrown away). Fixed ids
// only, never a response body, account data or screen text. token_tv/claude_bank.py allow-lists the same ids; a test keeps them equal.
export const REASONS = ['rate_limited', 'access_denied', 'provider_unavailable', 'cached_response', 'missing_provider_date',
  'response_too_large', 'malformed_response', 'network_error', 'timeout', 'identity_unavailable', 'wrong_account',
  'account_changed', 'invalid_pairing', 'not_offered', 'not_eligible', 'malformed_inventory', 'unknown'];
export const reasonOf = error => REASONS.includes(error?.message) ? error.message : 'unknown';
const interrupted = error => Error(['TimeoutError', 'AbortError'].includes(error?.name) ? 'timeout' : 'network_error');

export async function hash(value) {
  const digest = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(value));
  return Array.from(new Uint8Array(digest), byte => byte.toString(16).padStart(2, '0')).join('');
}

function inventoryOf(usage) {
  const status = usage?.cedar_ember;
  if (status == null) throw Error('not_offered');
  if (typeof status !== 'object' || Array.isArray(status)) throw Error('malformed_inventory');
  if (status.eligible == null || status.eligible === false) throw Error('not_eligible');
  if (status.eligible !== true || !Array.isArray(status.grants) || status.grants.length > 200) throw Error('malformed_inventory');
  return {eligible:true, grants:status.grants.map(grant => ({
    resets_total:grant?.resets_total, resets_left:grant?.resets_left,
    starts_at:grant?.starts_at, ends_at:grant?.ends_at, paused:grant?.paused
  }))};
}

// Backup quota (Tony, 2026-10-25): the same response carries the windows of Claude Code's own usage. Parsed strictly and sent
// minimal; an inactive five-hour window is left out, and a week without a live reset is not a reading.
function epoch(text) {
  const match = typeof text === 'string' ? ISO.exec(text) : null;
  const ms = match ? Date.parse(match[1] + match[2]) : NaN;
  return Number.isFinite(ms) ? Math.floor(ms / 1000) : null;
}
function quotaOf(usage, providerAt) {
  const windowOf = (value, week) => {
    if (value == null) return week ? 'quota_missing' : null;
    if (typeof value !== 'object' || Array.isArray(value)) return 'quota_invalid';
    const used = value.utilization, reset = epoch(value.resets_at);
    if (!week && used == null && value.resets_at == null) return null;
    if (typeof used !== 'number' || !Number.isFinite(used) || used < 0 || used > 100) return 'quota_invalid';
    if (reset === null) return week || value.resets_at != null ? 'quota_invalid' : null;
    if (reset <= providerAt) return week ? 'quota_invalid' : null;
    return {utilization:used, resets_at:reset};
  };
  const five = windowOf(usage?.five_hour, false), seven = windowOf(usage?.seven_day, true);
  const failed = [five, seven].find(value => typeof value === 'string');
  return failed ? {quota:null, quota_reason:failed} : {quota:{five_hour:five, seven_day:seven}, quota_reason:null};
}

export async function readUsage(pairing, transport = fetch) {
  if (!HASH.test(pairing?.accountHash) || !UUID.test(pairing?.organization)) throw Error('invalid_pairing');
  async function get(path) {
    let response, text;
    try {
      response = await transport('https://claude.ai' + path, {
        method:'GET', credentials:'include', redirect:'error', cache:'no-store',
        headers:{'Cache-Control':'no-cache'}, signal:AbortSignal.timeout(6000)
      });
    } catch (error) { throw interrupted(error); }
    if (!response.ok) throw Error(response.status === 429 ? 'rate_limited' : [401, 403].includes(response.status) ? 'access_denied' : 'provider_unavailable');
    if (Number(response.headers.get('Age')) > 0) throw Error('cached_response');
    const date = Date.parse(response.headers.get('Date')) / 1000;
    if (!Number.isFinite(date) || date <= 0) throw Error('missing_provider_date');
    try { text = await response.text(); } catch (error) { throw interrupted(error); }
    if (text.length > 131072) throw Error('response_too_large');
    try { return {data:JSON.parse(text), date}; } catch { throw Error('malformed_response'); } // its own message quotes the body
  }
  async function identity(account) {
    if (typeof account?.email_address !== 'string' || !UUID.test(account?.uuid)) throw Error('identity_unavailable');
    if (await hash(account.email_address.trim().toLowerCase()) !== pairing.accountHash) throw Error('wrong_account');
    return hash(account.uuid);
  }
  const before = await get('/api/account'), accountBefore = await identity(before.data);
  const usage = await get('/api/organizations/' + pairing.organization + '/usage?cedar_ember=1');
  const after = await get('/api/account'), accountAfter = await identity(after.data);
  if (accountBefore !== accountAfter) throw Error('account_changed');
  if (after.date < before.date || after.date - before.date > 30
      || usage.date < before.date - 2 || usage.date > after.date + 2) throw Error('cached_response');
  // One response, two readings judged apart: a missing bank never costs the quota, nor a missing quota the bank.
  let inventory = null, reason = null;
  try { inventory = inventoryOf(usage.data); } catch (error) { reason = reasonOf(error); }
  return {
    identity_before:pairing.accountHash, identity_after:pairing.accountHash,
    account_before:accountBefore, account_after:accountAfter,
    organization_hash:await hash(pairing.organization),
    provider_before:before.date, provider_at:usage.date, provider_after:after.date,
    inventory, reason, ...quotaOf(usage.data, usage.date)
  };
}

// Local permission/challenge comes first: stopped/disabled panel => no Claude calls. The version (from the manifest) tells the
// panel whether the browser still runs old code.
export async function collect(pairing, transport = fetch, version = null) {
  if (!HASH.test(pairing?.secret)) throw Error('invalid_pairing');
  async function local(body) {
    const response = await transport('http://127.0.0.1:8787/display/claude-bank', {
      method:'POST', credentials:'omit', redirect:'error', cache:'no-store',
      headers:{'Content-Type':'application/json', 'Authorization':'Bearer ' + pairing.secret},
      body:JSON.stringify(body), signal:AbortSignal.timeout(4000)
    });
    if (!response.ok) throw Error('local_reader_unavailable');
    return response.json();
  }
  const challenge = await local({operation:'challenge'});
  if (!HASH.test(challenge?.nonce)) throw Error('invalid_challenge');
  const answer = {nonce:challenge.nonce, ...(VERSION.test(version) ? {version} : {})};
  let reading;
  try { reading = await readUsage(pairing, transport); }
  catch (error) {
    const reason = reasonOf(error);
    await local({operation:'unavailable', reason, ...answer});
    throw Error(reason);
  }
  const {inventory, reason, quota, quota_reason, ...evidence} = reading;
  Object.assign(answer, evidence, quota ? {quota} : {quota_reason});
  if (reason) {
    await local({operation:'unavailable', reason, ...answer});
    throw Error(reason);
  }
  return local({operation:'observation', inventory, ...answer});
}
