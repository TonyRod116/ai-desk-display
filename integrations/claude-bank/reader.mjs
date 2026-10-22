// Only first-party GETs. Never read cookies or return identity/grant identifiers.
const HASH = /^[0-9a-f]{64}$/;
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
export async function hash(value) {
  const digest = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(value));
  return Array.from(new Uint8Array(digest), byte => byte.toString(16).padStart(2, '0')).join('');
}

export async function readInventory(pairing, transport = fetch) {
  if (!HASH.test(pairing?.accountHash) || !UUID.test(pairing?.organization)) throw Error('invalid_pairing');
  async function get(path) {
    const response = await transport('https://claude.ai' + path, {
      method:'GET', credentials:'include', redirect:'error', cache:'no-store',
      headers:{'Cache-Control':'no-cache'}, signal:AbortSignal.timeout(6000)
    });
    if (!response.ok) throw Error(response.status === 429 ? 'rate_limited' : 'provider_unavailable');
    if (Number(response.headers.get('Age')) > 0) throw Error('cached_response');
    const date = Date.parse(response.headers.get('Date')) / 1000;
    if (!Number.isFinite(date) || date <= 0) throw Error('missing_provider_date');
    const text = await response.text();
    if (text.length > 131072) throw Error('response_too_large');
    return {data:JSON.parse(text), date};
  }
  async function identity(account) {
    if (typeof account?.email_address !== 'string' || !UUID.test(account?.uuid)) throw Error('identity_unavailable');
    if (await hash(account.email_address.trim().toLowerCase()) !== pairing.accountHash) throw Error('wrong_account');
    return hash(account.uuid);
  }
  const before = await get('/api/account'), accountBefore = await identity(before.data);
  const bank = await get('/api/organizations/' + pairing.organization + '/usage?cedar_ember=1');
  const after = await get('/api/account'), accountAfter = await identity(after.data);
  if (accountBefore !== accountAfter) throw Error('account_changed');
  if (after.date < before.date || after.date - before.date > 30
      || bank.date < before.date - 2 || bank.date > after.date + 2) throw Error('cached_response');
  const status = bank.data?.cedar_ember;
  if (!status || status.eligible !== true || !Array.isArray(status.grants) || status.grants.length > 200) throw Error('inventory_unavailable');
  return {
    identity_before:pairing.accountHash, identity_after:pairing.accountHash,
    account_before:accountBefore, account_after:accountAfter,
    organization_hash:await hash(pairing.organization),
    provider_before:before.date, provider_at:bank.date, provider_after:after.date,
    inventory:{eligible:true, grants:status.grants.map(grant => ({
      resets_total:grant?.resets_total, resets_left:grant?.resets_left,
      starts_at:grant?.starts_at, ends_at:grant?.ends_at, paused:grant?.paused
    }))}
  };
}

// Local permission/challenge comes first: stopped/disabled panel => no Claude calls.
export async function collect(pairing, transport = fetch) {
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
  let observation;
  try { observation = await readInventory(pairing, transport); }
  catch (error) {
    await local({operation:'unavailable', nonce:challenge.nonce});
    throw error;
  }
  return local({operation:'observation', nonce:challenge.nonce, ...observation});
}
