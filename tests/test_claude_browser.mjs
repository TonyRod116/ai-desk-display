import test from 'node:test';
import assert from 'node:assert/strict';
import {collect, hash, readInventory} from '../integrations/claude-bank/reader.mjs';

const UUID = '11111111-1111-1111-1111-111111111111';
const OWNER = await hash('demo@example.invalid');
const PAIRING = {accountHash:OWNER, organization:UUID, secret:'a'.repeat(64)};
const ACCOUNT = {email_address:'Demo@example.invalid', uuid:UUID};
const INVENTORY = {cedar_ember:{eligible:true, grants:[{
  id:'PRIVATE-GRANT', label:'PRIVATE-LABEL', resets_total:2, resets_left:1,
  starts_at:1000, ends_at:2000, paused:false, usable_now:false
}]}};
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
test('fixed first-party GETs, ambient login, account checked twice, sanitized bank', async () => {
  const calls=[];
  const reading = await readInventory(PAIRING, transport([response(ACCOUNT),response(INVENTORY,1501),response(ACCOUNT,1502)],calls));
  assert.equal(reading.inventory.grants[0].resets_left,1);
  assert.equal(reading.organization_hash,await hash(UUID));
  for (const call of calls) {
    assert.equal(call.options.method,'GET'); assert.equal(call.options.credentials,'include');
    assert.equal(call.options.redirect,'error'); assert.equal(call.options.cache,'no-store');
    assert.deepEqual(call.options.headers,{'Cache-Control':'no-cache'});
    assert.ok(call.url.startsWith('https://claude.ai/api/'));
    assert.ok(!JSON.stringify(call).includes(PAIRING.secret));
  }
  const text=JSON.stringify(reading);
  for (const privateText of ['demo@example.invalid',UUID,'PRIVATE-GRANT','PRIVATE-LABEL','usable_now']) assert.ok(!text.includes(privateText));
});
test('stopped or disabled local server prevents all provider requests', async () => {
  const calls=[];
  await assert.rejects(collect(PAIRING,transport([response({},1500,403)],calls)));
  assert.equal(calls.length,1); assert.ok(calls[0].url.startsWith('http://127.0.0.1:8787/'));
});
test('wrong account before query and account switch afterward fail closed', async () => {
  let calls=[];
  await assert.rejects(readInventory(PAIRING,transport([response({...ACCOUNT,email_address:'other@example.invalid'})],calls)),/wrong_account/);
  assert.equal(calls.length,1);
  calls=[];
  await assert.rejects(readInventory(PAIRING,transport([response(ACCOUNT),response(INVENTORY),response({...ACCOUNT,uuid:'22222222-2222-2222-2222-222222222222'})],calls)),/account_changed/);
  assert.equal(calls.length,3);
});
test('stale response, missing bank and HTTP failures report unavailable with fresh nonce', async () => {
  for (const failed of [response(INVENTORY,1300),response(INVENTORY,1500,200,{Age:'5'}),response({},1500),response({},1500,429)]) {
    const calls=[];
    const responses=[response({nonce:'b'.repeat(64)}),response(ACCOUNT),failed,response(ACCOUNT,1502),response({status:'unknown'})];
    const fake=async (url,options) => {
      if (url.startsWith('http:') && JSON.parse(options.body).operation === 'unavailable') {
        calls.push({url,options}); return response({status:'unknown'});
      }
      return transport(responses,calls)(url,options);
    };
    await assert.rejects(collect(PAIRING,fake));
    const last=calls.at(-1);
    assert.deepEqual(JSON.parse(last.options.body),{operation:'unavailable',nonce:'b'.repeat(64)});
    assert.ok(calls.filter(c=>c.url.startsWith('https:')).every(c=>c.options.method==='GET'));
  }
});
test('successful observation answers its single-use local challenge', async () => {
  const calls=[];
  assert.deepEqual(await collect(PAIRING,transport([response({nonce:'b'.repeat(64)}),response(ACCOUNT),response(INVENTORY),response(ACCOUNT),response({status:'ok'})],calls)),{status:'ok'});
  const local=calls.filter(call=>call.url.startsWith('http:'));
  assert.equal(local.length,2);
  assert.equal(JSON.parse(local[1].options.body).nonce,'b'.repeat(64));
  assert.equal(JSON.parse(local[1].options.body).operation,'observation');
  assert.equal(local[1].options.headers.Authorization,'Bearer '+PAIRING.secret);
});
test('invalid organization or pairing cannot create another destination', async () => {
  for (const organization of ['../attacker','https://attacker.invalid',null]) {
    await assert.rejects(readInventory({...PAIRING,organization},()=>assert.fail('No network')),/invalid_pairing/);
  }
});
