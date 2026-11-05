import test from 'node:test';
import assert from 'node:assert/strict';
import {REASONS, collect, hash, readUsage, reasonOf} from '../integrations/claude-bank/reader.mjs';

const UUID = '11111111-1111-1111-1111-111111111111';
const OWNER = await hash('demo@example.invalid');
const PAIRING = {accountHash:OWNER, organization:UUID, secret:'a'.repeat(64)};
const ACCOUNT = {email_address:'Demo@example.invalid', uuid:UUID};
const NONCE = 'b'.repeat(64);
const iso = seconds => new Date(seconds * 1000).toISOString();
const INVENTORY = {cedar_ember:{eligible:true, grants:[{
  id:'PRIVATE-GRANT', label:'PRIVATE-LABEL', resets_total:2, resets_left:1,
  starts_at:1000, ends_at:2000, paused:false, usable_now:false
}]}};
const QUOTA = {
  five_hour:{utilization:12.5, resets_at:iso(1800), PRIVATE_FIELD:'x'},
  seven_day:{utilization:40, resets_at:'1970-01-01T00:33:20.123456+00:00', PRIVATE_FIELD:'x'},
  extra_usage:{PRIVATE_FIELD:'x'}
};
const SENT_QUOTA = {five_hour:{utilization:12.5, resets_at:1800}, seven_day:{utilization:40, resets_at:2000}};
function response(data, date=1500, status=200, headers={}) {
  return new Response(JSON.stringify(data), {status, headers:{Date:new Date(date*1000).toUTCString(), ...headers}});
}
function transport(responses, calls=[]) {
  return async (url, options) => {
    calls.push({url, options});
    assert.ok(responses.length, 'Unexpected extra request');
    return responses.shift();
  };
}
// The local panel answers its challenge; Claude's answers come from `claude`. Returns what the panel was told.
async function exchange(claude, {pairing=PAIRING, version=null, fail=null}={}) {
  const local = [], remote = [];
  const fake = async (url, options) => {
    if (url.startsWith('http:')) {
      const body = JSON.parse(options.body);
      local.push(body);
      return response(body.operation === 'challenge' ? {nonce:NONCE} : {status:'ok'});
    }
    remote.push({url, options});
    if (fail) throw fail;
    assert.ok(claude.length, 'Unexpected extra request');
    return claude.shift();
  };
  let error = null;
  try { await collect(pairing, fake, version); } catch (caught) { error = caught; }
  return {local, remote, error, last:local.at(-1)};
}
const usage = (extra={}, date=1501) => [response(ACCOUNT), response({...INVENTORY, ...extra}, date), response(ACCOUNT, 1502)];

test('fixed first-party GETs, ambient login, account checked twice, sanitized bank and quota', async () => {
  const calls=[];
  const reading = await readUsage(PAIRING, transport([response(ACCOUNT),response({...INVENTORY, ...QUOTA},1501),response(ACCOUNT,1502)],calls));
  assert.equal(reading.inventory.grants[0].resets_left,1);
  assert.equal(reading.organization_hash,await hash(UUID));
  assert.deepEqual(reading.quota, SENT_QUOTA);
  assert.equal(reading.reason, null);
  assert.equal(calls.length, 3);
  for (const call of calls) {
    assert.equal(call.options.method,'GET'); assert.equal(call.options.credentials,'include');
    assert.equal(call.options.redirect,'error'); assert.equal(call.options.cache,'no-store');
    assert.deepEqual(call.options.headers,{'Cache-Control':'no-cache'});
    assert.ok(call.url.startsWith('https://claude.ai/api/'));
    assert.ok(!JSON.stringify(call).includes(PAIRING.secret));
  }
  assert.equal(calls[1].url, `https://claude.ai/api/organizations/${UUID}/usage?cedar_ember=1`, 'the quota adds no query');
  const text=JSON.stringify(reading);
  for (const privateText of ['demo@example.invalid',UUID,'PRIVATE-GRANT','PRIVATE-LABEL','PRIVATE_FIELD','usable_now','extra_usage']) assert.ok(!text.includes(privateText));
});
test('stopped or disabled local server prevents all provider requests', async () => {
  const calls=[];
  await assert.rejects(collect(PAIRING,transport([response({},1500,403)],calls)));
  assert.equal(calls.length,1); assert.ok(calls[0].url.startsWith('http://127.0.0.1:8787/'));
});
test('wrong account before query and account switch afterward fail closed', async () => {
  let calls=[];
  await assert.rejects(readUsage(PAIRING,transport([response({...ACCOUNT,email_address:'other@example.invalid'})],calls)),/wrong_account/);
  assert.equal(calls.length,1);
  calls=[];
  await assert.rejects(readUsage(PAIRING,transport([response(ACCOUNT),response(INVENTORY),response({...ACCOUNT,uuid:'22222222-2222-2222-2222-222222222222'})],calls)),/account_changed/);
  assert.equal(calls.length,3);
});
test('successful observation answers its single-use local challenge with the extension version', async () => {
  const {local, remote, error} = await exchange(usage(QUOTA), {version:'1.1.0'});
  assert.equal(error, null);
  assert.equal(remote.length, 3);
  assert.deepEqual(local.map(body => body.operation), ['challenge', 'observation']);
  assert.deepEqual(local[0], {operation:'challenge'}, 'the challenge stays exactly what an older panel accepts');
  const body = local[1];
  assert.equal(body.nonce, NONCE); assert.equal(body.version, '1.1.0');
  assert.equal(body.inventory.grants[0].resets_left, 1);
  assert.deepEqual(body.quota, SENT_QUOTA);
  assert.equal(body.quota_reason, undefined);
  for (const key of ['identity_before', 'identity_after', 'account_before', 'account_after', 'organization_hash', 'provider_before', 'provider_at', 'provider_after']) assert.ok(key in body, key);
});
test('a malformed or missing version is not sent', async () => {
  for (const version of [null, undefined, '', 'v1', '1', '1.1.0-beta', '1.'.repeat(30), 7]) {
    const {last} = await exchange(usage(QUOTA), {version});
    assert.equal(last.operation, 'observation'); assert.ok(!('version' in last), String(version));
  }
});

const REASON_CASES = {
  'HTTP 429': [[response(ACCOUNT), response({}, 1500, 429)], 'rate_limited'],
  'HTTP 401': [[response({}, 1500, 401)], 'access_denied'],
  'HTTP 403': [[response(ACCOUNT), response({}, 1500, 403)], 'access_denied'],
  'HTTP 500': [[response(ACCOUNT), response({}, 1500, 500)], 'provider_unavailable'],
  'old provider date': [[response(ACCOUNT), response(INVENTORY, 1300), response(ACCOUNT, 1502)], 'cached_response'],
  'Age header': [[response(ACCOUNT), response(INVENTORY, 1500, 200, {Age:'5'}), response(ACCOUNT, 1502)], 'cached_response'],
  'no Date header': [[response(ACCOUNT), new Response(JSON.stringify(INVENTORY))], 'missing_provider_date'],
  'oversized body': [[response(ACCOUNT), response({padding:'x'.repeat(140000)}, 1500)], 'response_too_large'],
  'not JSON': [[response(ACCOUNT), new Response('PRIVATE-BODY <html>', {headers:{Date:new Date(1500000).toUTCString()}})], 'malformed_response'],
  'no email': [[response({uuid:UUID})], 'identity_unavailable'],
  'other account': [[response({...ACCOUNT, email_address:'other@example.invalid'})], 'wrong_account'],
  'account switched': [[response(ACCOUNT), response(INVENTORY), response({...ACCOUNT, uuid:'22222222-2222-2222-2222-222222222222'})], 'account_changed'],
};
for (const [name, [claude, reason]] of Object.entries(REASON_CASES)) {
  test(`${name} is reported as ${reason}, with the version and nothing else`, async () => {
    const {local, remote, error, last} = await exchange(claude, {version:'1.1.0'});
    assert.equal(error.message, reason, 'the extension rethrows only the fixed id');
    assert.deepEqual(last, {operation:'unavailable', reason, nonce:NONCE, version:'1.1.0'});
    assert.ok(remote.every(call => call.options.method === 'GET'));
    assert.ok(!JSON.stringify(local).includes('PRIVATE'));
  });
}
test('network failures and timeouts are reported as such, without the browser\'s own message', async () => {
  for (const [fail, reason] of [[new TypeError('Failed to fetch PRIVATE-URL'), 'network_error'],
                                [new DOMException('PRIVATE', 'TimeoutError'), 'timeout'],
                                [new DOMException('PRIVATE', 'AbortError'), 'timeout']]) {
    const {last, error} = await exchange([], {fail});
    assert.equal(error.message, reason);
    assert.deepEqual(last, {operation:'unavailable', reason, nonce:NONCE});
  }
});
test('an invalid pairing is reported before any request to Claude', async () => {
  const {remote, last} = await exchange([], {pairing:{...PAIRING, organization:'../attacker'}});
  assert.equal(remote.length, 0);
  assert.deepEqual(last, {operation:'unavailable', reason:'invalid_pairing', nonce:NONCE});
});
test('reason ids are a fixed list: anything else becomes unknown', () => {
  assert.equal(new Set(REASONS).size, REASONS.length);
  for (const id of ['not_offered', 'not_eligible', 'malformed_inventory']) assert.ok(REASONS.includes(id), id);
  assert.ok(!REASONS.includes('inventory_unavailable'), 'the catch-all is gone');
  for (const id of REASONS) assert.equal(reasonOf(Error(id)), id);
  for (const caught of [Error('PRIVATE'), Error(''), 'rate_limited', null, undefined, {message:'x'}, new SyntaxError('Unexpected token PRIVATE')]) assert.equal(reasonOf(caught), 'unknown');
});

const BANK_CASES = {
  'field absent': [{}, 'not_offered'],
  'field null': [{cedar_ember:null}, 'not_offered'],
  'not eligible': [{cedar_ember:{eligible:false, grants:[]}}, 'not_eligible'],
  'eligible missing': [{cedar_ember:{grants:[]}}, 'not_eligible'],
  'eligible a word': [{cedar_ember:{eligible:'yes', grants:[]}}, 'malformed_inventory'],
  'no grants list': [{cedar_ember:{eligible:true}}, 'malformed_inventory'],
  'too many grants': [{cedar_ember:{eligible:true, grants:new Array(201).fill({})}}, 'malformed_inventory'],
  'field a string': [{cedar_ember:'yes'}, 'malformed_inventory'],
  'field a list': [{cedar_ember:[]}, 'malformed_inventory'],
};
for (const [name, [bank, reason]] of Object.entries(BANK_CASES)) {
  test(`bank: ${name} is ${reason}, and a good quota still travels with it`, async () => {
    const {local, error, last, remote} = await exchange([response(ACCOUNT), response({...bank, ...QUOTA}, 1501), response(ACCOUNT, 1502)], {version:'1.1.0'});
    assert.equal(error.message, reason);
    assert.equal(remote.length, 3, 'the same three GETs, no new query');
    assert.deepEqual(local.map(body => body.operation), ['challenge', 'unavailable']);
    assert.equal(last.reason, reason);
    assert.deepEqual(last.quota, SENT_QUOTA);
    assert.ok(!('inventory' in last));
    for (const key of ['identity_before', 'account_after', 'organization_hash', 'provider_before', 'provider_at', 'provider_after']) assert.ok(key in last, key);
  });
}

const QUOTA_CASES = {
  'week missing': [{five_hour:QUOTA.five_hour}, 'quota_missing'],
  'no windows at all': [{}, 'quota_missing'],
  'week null': [{five_hour:QUOTA.five_hour, seven_day:null}, 'quota_missing'],
  'week not an object': [{seven_day:'40'}, 'quota_invalid'],
  'week list': [{seven_day:[]}, 'quota_invalid'],
  'percent above 100': [{seven_day:{utilization:100.1, resets_at:iso(2000)}}, 'quota_invalid'],
  'percent below 0': [{seven_day:{utilization:-1, resets_at:iso(2000)}}, 'quota_invalid'],
  'percent a word': [{seven_day:{utilization:'40', resets_at:iso(2000)}}, 'quota_invalid'],
  'percent null': [{seven_day:{utilization:null, resets_at:iso(2000)}}, 'quota_invalid'],
  'percent true': [{seven_day:{utilization:true, resets_at:iso(2000)}}, 'quota_invalid'],
  'week reset null': [{seven_day:{utilization:40, resets_at:null}}, 'quota_invalid'],
  'week reset passed': [{seven_day:{utilization:40, resets_at:iso(1500)}}, 'quota_invalid'],
  'week reset before the answer': [{seven_day:{utilization:40, resets_at:iso(1400)}}, 'quota_invalid'],
  'week reset without a zone': [{seven_day:{utilization:40, resets_at:'1970-01-01T00:33:20'}}, 'quota_invalid'],
  'week reset a number': [{seven_day:{utilization:40, resets_at:2000}}, 'quota_invalid'],
  'week reset garbage': [{seven_day:{utilization:40, resets_at:'soon'}}, 'quota_invalid'],
  'five-hour malformed': [{five_hour:{utilization:'x', resets_at:iso(1800)}, seven_day:QUOTA.seven_day}, 'quota_invalid'],
  'five-hour reset garbage': [{five_hour:{utilization:5, resets_at:'later'}, seven_day:QUOTA.seven_day}, 'quota_invalid'],
  'five-hour not an object': [{five_hour:5, seven_day:QUOTA.seven_day}, 'quota_invalid'],
};
for (const [name, [quota, reason]] of Object.entries(QUOTA_CASES)) {
  test(`quota: ${name} is ${reason}, and the bank still travels`, async () => {
    const {local, error, last} = await exchange(usage(quota), {version:'1.1.0'});
    assert.equal(error, null);
    assert.deepEqual(local.map(body => body.operation), ['challenge', 'observation']);
    assert.equal(last.inventory.grants[0].resets_left, 1);
    assert.ok(!('quota' in last)); assert.equal(last.quota_reason, reason);
  });
}
test('quota: an inactive or rolled-over five-hour window is left out, never sent as zero', async () => {
  for (const five_hour of [null, undefined, {utilization:null, resets_at:null}, {utilization:0, resets_at:null},
                           {utilization:80, resets_at:iso(1500)}, {utilization:80, resets_at:iso(1000)}]) {
    const {last} = await exchange(usage({five_hour, seven_day:QUOTA.seven_day}));
    assert.equal(last.operation, 'observation');
    assert.deepEqual(last.quota, {five_hour:null, seven_day:SENT_QUOTA.seven_day});
  }
});
test('quota: the limits of the range are accepted, offsets are honoured and fractions of a second are cut', async () => {
  const full = await exchange(usage({seven_day:{utilization:100, resets_at:'1970-01-01T01:33:20.999999+01:00'}}));
  assert.deepEqual(full.last.quota.seven_day, {utilization:100, resets_at:2000});
  const zero = await exchange(usage({seven_day:{utilization:0, resets_at:iso(2000)}}));
  assert.deepEqual(zero.last.quota.seven_day, {utilization:0, resets_at:2000});
});
test('both missing: bank and quota failures are reported, nothing is invented', async () => {
  const {last} = await exchange(usage({cedar_ember:null}), {});
  assert.equal(last.operation, 'unavailable'); assert.equal(last.reason, 'not_offered');
  assert.equal(last.quota_reason, 'quota_missing'); assert.ok(!('quota' in last));
});
test('nothing private is ever sent to the panel', async () => {
  const {local} = await exchange(usage({...QUOTA, email:'demo@example.invalid'}), {version:'1.1.0'});
  const text = JSON.stringify(local);
  for (const privateText of ['demo@example.invalid', UUID, 'PRIVATE-GRANT', 'PRIVATE-LABEL', 'PRIVATE_FIELD', 'usable_now', 'extra_usage', PAIRING.secret])
    assert.ok(!text.includes(privateText), privateText);
});
test('invalid organization or pairing cannot create another destination', async () => {
  for (const organization of ['../attacker','https://attacker.invalid',null]) {
    await assert.rejects(readUsage({...PAIRING,organization},()=>assert.fail('No network')),/invalid_pairing/);
  }
});
