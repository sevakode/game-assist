'use strict';
const assert=require('node:assert/strict');
const parser=require('../remote_server/belmont-parser.js');
const {createController}=require('../remote_server/import.js');
const synthetic=()=>({version:'1.1.3',playerSave:{healthUpgradeFragmentCount:2,manaUpgradeFragmentCount:3,currentHealth:42.0,currentMana:50.0},worldSaves:{m_keys:['PRIVATE_WORLD'],m_values:[{savableEntityStates:{m_keys:['PRIVATE_ENTITY'],m_values:['{"activated":false}']}}]},secret:'DO_NOT_SEND'});
const raw=()=>JSON.stringify(synthetic());
const reject=(text)=>assert.throws(()=>parser.decodeText(text),parser.InvalidSave);
function parserTests(){
 const result=parser.decodeText(raw());
 assert.equal(result.player_scalars.currentHealth.value,42);
 for(const secret of ['PRIVATE_WORLD','PRIVATE_ENTITY','DO_NOT_SEND','activated','source_hash'])assert(!JSON.stringify(result).includes(secret));
 assert.deepEqual(Object.keys(result).sort(),['decoder_coverage','format_version','player_scalars','semantic_caveats']);
 assert.equal(result.decoder_coverage.world_structure,'validated_structural_only');
 assert.equal(parser.decodeText('{"version":"1.1.3"}').player_scalars.currentMana.status,'missing');
 assert.equal(parser.decodeText('{"version":"1.1.3","playerSave":{"currentMana":null}}').player_scalars.currentMana.status,'unknown');
 assert.equal(parser.decodeText('{"version":"1.1.3","playerSave":{"currentMana":0.1}}').player_scalars.currentMana.value,0.1);
 for(const value of ['true','-1','1.0','1e0','1.5','"2"','9007199254740992'])reject('{"version":"1.1.3","playerSave":{"healthUpgradeFragmentCount":'+value+'}}');
 for(const value of ['NaN','Infinity','1e999','1e-999','0.100000000000000000000001','9007199254740993'])reject('{"version":"1.1.3","playerSave":{"currentHealth":'+value+'}}');
 for(const text of ['{','[]','{"version":"1.1.3","version":"1.1.3"}','{"version":"1.1.3","noise":{"a":1,"\\u0061":2}}','{"version":"1.1.4"}','{"version":"1.1.3","playerSave":[]}','{"version":"1.1.3","noise":"\\ud800"}','{"version":"1.1.3","noise":01}'])reject(text);
 reject('{"version":"1.1.3","noise":'+'['.repeat(65)+'0'+']'.repeat(65)+'}');
 reject('{"version":"1.1.3","noise":['+'0,'.repeat(500000)+'0]}');
 reject(' '.repeat(parser.MAX_BYTES+1));
 let fixture=synthetic();fixture.worldSaves.m_keys.push('PRIVATE_WORLD');fixture.worldSaves.m_values.push(fixture.worldSaves.m_values[0]);reject(JSON.stringify(fixture));
 fixture=synthetic();fixture.worldSaves.m_values[0].savableEntityStates.m_values[0]='{"a":0,"a":1}';reject(JSON.stringify(fixture));
 fixture.worldSaves.m_values[0].savableEntityStates.m_values[0]='True';assert.equal(parser.decodeText(JSON.stringify(fixture)).format_version,'1.1.3');
 fixture.worldSaves.m_values[0].savableEntityStates.m_values[0]='NaN';reject(JSON.stringify(fixture));
 // Opaque numeric fields must not be rounded or rejected merely because their
 // lexemes exceed JavaScript precision. They never enter the public projection.
 fixture=synthetic();
 fixture.worldSaves.m_values[0].savableEntityStates.m_values[0]='{"opaqueFraction":0.12345678901234567890123,"opaqueInteger":9007199254740993,"tiny":1e-999}';
 const opaqueResult=parser.decodeText(JSON.stringify(fixture));
 assert.equal(opaqueResult.player_scalars.currentHealth.value,42);
 assert(!JSON.stringify(opaqueResult).includes('opaqueFraction'));
 assert(!JSON.stringify(opaqueResult).includes('9007199254740993'));
 reject('{"version":"1.1.3","noise":1e10001}');
 reject('{"version":"1.1.3","noise":'+ '9'.repeat(1001)+'}');
 fixture.worldSaves.m_values[0].savableEntityStates.m_values[0]='{"opaqueFraction":1e999}';reject(JSON.stringify(fixture));
 const dangerous=parser.decodeText('{"version":"1.1.3","__proto__":{"polluted":true},"playerSave":{"currentHealth":42}}');
 assert.equal({}.polluted,undefined);assert.equal(dangerous.player_scalars.currentHealth.value,42);
}
const deferred=()=>{let resolve,reject;const promise=new Promise((yes,no)=>{resolve=yes;reject=no;});return {promise,resolve,reject};};
const file={size:100,name:'PRIVATE_FILENAME',path:'PRIVATE_PATH'};
function harness(overrides={}){const renders=[],requests=[];let ids=0,reads=0;const ctl=createController({parser,readFile:async()=>{reads++;return raw();},uuid:()=>`id-${++ids}`,render:s=>renders.push(s),send:async(payload,eventId)=>{requests.push({payload,eventId});return {ok:true,status:200,accepted:true};},...overrides});return {ctl,renders,requests,reads:()=>reads};}
async function controllerTests(){
 let h=harness();await h.ctl.select(null);assert.equal(h.ctl.getState().phase,'empty');assert.equal(h.requests.length,0);
 await h.ctl.select({size:parser.MAX_BYTES+1});assert.equal(h.reads(),0);assert.equal(h.ctl.getState().phase,'error');
 h=harness({readFile:async()=>'{bad'});await h.ctl.select(file);await h.ctl.submit();assert.equal(h.requests.length,0);assert.equal(h.ctl.getState().payload,null);
 h=harness();await h.ctl.select(file);assert.equal(h.ctl.getState().phase,'preview');assert.equal(h.requests.length,0);await h.ctl.submit();assert.equal(h.ctl.getState().phase,'success');assert.equal(h.requests.length,1);assert(!JSON.stringify(h.requests).includes('PRIVATE'));assert.equal(h.ctl.getState().payload,null);
 let response=deferred(),calls=0;
 h=harness({send:()=>{calls++;return response.promise;}});await h.ctl.select(file);const first=h.ctl.submit();await h.ctl.submit();assert.equal(calls,1);await h.ctl.select(file);assert.equal(h.ctl.getState().phase,'sending');response.resolve({ok:true,status:200,accepted:true});await first;assert.equal(h.ctl.getState().phase,'success');
 let one=deferred(),two=deferred(),read=0;
 h=harness({readFile:()=>++read===1?one.promise:two.promise});const old=h.ctl.select(file),latest=h.ctl.select(file);two.resolve('{"version":"1.1.3","playerSave":{"currentHealth":20}}');await latest;one.resolve(raw());await old;assert.equal(h.ctl.getState().payload.player_scalars.currentHealth.value,20);
 one=deferred();h=harness({readFile:()=>one.promise});const pending=h.ctl.select(file);h.ctl.clear();one.resolve(raw());await pending;assert.equal(h.ctl.getState().phase,'empty');assert.equal(h.ctl.getState().payload,null);
 const retryIds=[];calls=0;h=harness({send:async(payload,id)=>{retryIds.push(id);if(++calls===1)throw new Error('PRIVATE_NETWORK_ERROR');return {status:200,ok:true,accepted:true};}});await h.ctl.select(file);await h.ctl.submit();assert.equal(h.ctl.getState().phase,'retry');await h.ctl.submit();assert.equal(retryIds[0],retryIds[1]);assert(!h.renders.some(s=>s.message.includes('PRIVATE_NETWORK_ERROR')));
 for(const status of [401,403]){h=harness({send:async()=>({ok:false,status})});await h.ctl.select(file);await h.ctl.submit();assert.equal(h.ctl.getState().phase,'blocked');assert.equal(h.ctl.getState().payload,null);await h.ctl.submit();assert.equal(h.ctl.getState().phase,'blocked');}
 h=harness({send:async()=>({ok:false,status:422})});await h.ctl.select(file);await h.ctl.submit();assert.equal(h.ctl.getState().phase,'error');
 response=deferred();h=harness({send:()=>response.promise});await h.ctl.select(file);const inflight=h.ctl.submit();h.ctl.clear();assert(!h.ctl.getState().message.includes('Ничего не отправлено'));response.resolve({ok:true,status:200,accepted:true});await inflight;assert.equal(h.ctl.getState().phase,'empty');h.ctl.clear();assert(!h.ctl.getState().message.includes('Ничего не отправлено'));
 h=harness();await h.ctl.select(file);h.ctl.clear();await h.ctl.submit();assert.equal(h.requests.length,0);
}
(async()=>{parserTests();await controllerTests();process.stdout.write('Manual import parser and controller tests passed\n');})().catch(error=>{process.stderr.write(error.stack+'\n');process.exitCode=1;});
