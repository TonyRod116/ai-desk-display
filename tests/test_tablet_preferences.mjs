import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

const app = fs.readFileSync(new URL('../token_tv/tablet_web/app.js', import.meta.url), 'utf8');
const source = name => app.match(new RegExp('(?:async )?function ' + name + '\\([^]*?\\n  \\}'))[0];
const defaults = vm.runInNewContext('(' + app.match(/const DEFAULT_SETTINGS = (\{[^]*?\});/)[1] + ')');
const plain = value => JSON.parse(JSON.stringify(value));
const clean = vm.runInNewContext('(' + source('cleanSettings') + ')', {DEFAULT_SETTINGS:defaults});

test('only display preferences can be persisted, with bounded values and no prototype keys', () => {
  const value = JSON.parse('{"scene":"surf","auto":{"minutes":30,"rotate":["surf","surf","paradise"]},"night":{"level":40},"providers":{"claude":{"credits":123}},"__proto__":{"polluted":true}}');
  assert.deepEqual(plain(clean(value)), {scene:'surf', auto:{minutes:30,rotate:['surf','paradise']},night:{level:40}});
  assert.equal({}.polluted, undefined);
  for (const value of [{auto:'bad'}, {scene:42}, {motion:'unknown'}, {auto:{minutes:0}}, {auto:{mode:'invalid'}}, {night:{start:'25:01'}}, {place:{lat:91}}, {photos:{seconds:Infinity}}]) assert.deepEqual(plain(clean(value)), {});
  assert.deepEqual(plain(clean({sound:{enabled:false,volume:0},place:{lat:0,lon:0}})),{sound:{enabled:false,volume:0},place:{lat:0,lon:0}});
});

test('a failed settings send survives restart and preserves edits made while it was in flight', async () => {
  let reject, persisted;
  const sandbox = {pendingPatch:{scene:'paradise',night:{level:40}},settings:{scene:'surf'}, settingsInFlight:{}, sendingSettings:false,
    AbortController, setTimeout, clearTimeout,
    setStored:(key,value)=>{if(key==='tablet-settings-pending-v1')persisted=JSON.parse(value);},
    fetch:()=>new Promise((resolve,no)=>{reject=no;})};
  sandbox.assignDeep=vm.runInNewContext('(' + source('assignDeep') + ')');
  sandbox.keepSettings=vm.runInNewContext('(' + source('keepSettings') + ')',sandbox);
  const send=vm.runInNewContext('(' + source('sendSettings') + ')',sandbox);
  const action=send();
  assert.deepEqual(persisted,{scene:'paradise',night:{level:40}},'in-flight changes remain durable');
  sandbox.pendingPatch={scene:'surf',motion:'off'};
  sandbox.keepSettings();
  assert.deepEqual(persisted,{scene:'surf',night:{level:40},motion:'off'});
  reject(new Error('fictional PC offline'));
  await action;
  assert.deepEqual(plain(sandbox.pendingPatch),{scene:'surf',night:{level:40},motion:'off'});
  assert.deepEqual(persisted,plain(sandbox.pendingPatch));
  assert.deepEqual(plain(sandbox.settingsInFlight),{});
});

test('successful preference sync clears only the patch actually sent', async () => {
  let resolve;
  const calls=[];
  const sandbox={pendingPatch:{scene:'surf'},settings:{},settingsInFlight:{},sendingSettings:false,AbortController,setTimeout,clearTimeout,
    keepSettings:()=>{},fetch:(path,options)=>{calls.push({path,body:JSON.parse(options.body)});return new Promise(yes=>{resolve=yes;});}};
  sandbox.assignDeep=vm.runInNewContext('(' + source('assignDeep') + ')');
  const send=vm.runInNewContext('(' + source('sendSettings') + ')',sandbox);
  const action=send();sandbox.pendingPatch={motion:'off'};
  resolve({ok:true});await action;
  assert.deepEqual(calls,[{path:'/api/settings',body:{scene:'surf'}}]);
  assert.deepEqual(plain(sandbox.pendingPatch),{motion:'off'});
});

test('a delayed PC settings response cannot undo an offline choice already acknowledged by a parallel send', async () => {
  let answer;
  const sandbox={DEFAULT_SETTINGS:plain(defaults), settings:plain(defaults), settingsRevision:0,
    pendingPatch:{scene:'surf'},settingsInFlight:{},settingsLoaded:false,keepSettings:()=>{},settingsChanged:()=>{},sendSettings:()=>{},
    fetch:()=>new Promise(resolve=>{answer=resolve;})};
  for(const name of ['cleanSettings','mergeSettings','assignDeep']) sandbox[name]=vm.runInNewContext('(' + source(name) + ')',sandbox);
  const load=vm.runInNewContext('(' + source('loadSettings') + ')',sandbox);
  const action=load();
  sandbox.pendingPatch={}; // the parallel POST succeeded before the older GET came back
  answer({ok:true,status:200,json:async()=>({settings:plain(defaults)})});
  await action;
  assert.equal(sandbox.settings.scene,'surf');
});
