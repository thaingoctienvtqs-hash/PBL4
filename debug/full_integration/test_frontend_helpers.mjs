import assert from 'node:assert/strict'
import fs from 'node:fs'
import path from 'node:path'
import {pathToFileURL, fileURLToPath} from 'node:url'
const repo=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'../..')
const args=process.argv.slice(2)
if(args.length!==2 || args[0]!=='--artifacts') throw new Error('Usage: node test_frontend_helpers.mjs --artifacts EXISTING_EXTERNAL_DIRECTORY')
const base=fs.realpathSync(path.resolve(args[1]))
const relative=path.relative(repo,base)
if(!relative || (!relative.startsWith('..'+path.sep) && relative!=='..' && !path.isAbsolute(relative))) throw new Error('Artifacts must be outside repository')
const dir=fs.mkdtempSync(path.join(base,'frontend_helpers_'))
const {default:ts}=await import(pathToFileURL(path.join(repo,'web/frontend/node_modules/typescript/lib/typescript.js')).href)
async function compile(file,name){let code=ts.transpileModule(fs.readFileSync(repo+'/web/frontend/src/'+file,'utf8'),{compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.ESNext}}).outputText
code=code.replace("from 'axios'","from '"+pathToFileURL(repo+'/web/frontend/node_modules/axios/index.js').href+"'")
const out=path.join(dir,name);fs.writeFileSync(out,code,{flag:'wx'});return import(pathToFileURL(out).href)}
const d=await compile('utils/datetime.ts','datetime_test_module.mjs'),c=await compile('api/client.ts','client_test_module.mjs')
let passed=0
async function test(name,fn){await fn();passed++;console.log('PASS '+name)}
for(const [name,value]of [['naive UTC','2026-10-28T12:00:00'],['Z UTC','2026-10-28T12:00:00Z'],['offset UTC','2026-10-28T19:00:00+07:00'],['space UTC','2026-10-28 12:00:00']])await test(name,()=>assert.equal(d.parseUtcTimestamp(value).toISOString(),'2026-10-28T12:00:00.000Z'))
await test('unknown timestamp',()=>{assert.equal(d.parseUtcTimestamp(null),null);assert.equal(d.parseUtcTimestamp('bad'),null)})
for(const [name,row,label]of [['demo',{source:'demo'},'DEMO'],['unverified AI',{source:'ai'},'UNVERIFIED'],['synthetic',{ingest:{data_origin:'SYNTHETIC_TEST'}},'SYNTHETIC_TEST'],['real',{ingest:{data_origin:'REAL_AI'}},'REAL_AI']])await test(name,()=>assert.equal(c.alertOriginLabel(row),label))
const original=c.api.get;let calls=[]
const signal=new AbortController().signal,rows=[{id:1,source:'demo'},{id:2,source:'synthetic_test'}]
try{
c.api.get=async(...args)=>{calls.push(args);return{data:{items:[{alert_id:2,event_id:'event2',data_origin:'SYNTHETIC_TEST'}]}}}
await test('single batch preserves source and uses abort signal',async()=>{let r=await c.withAlertOrigins(rows,{enabled:true},signal);assert.equal(calls.length,1);assert.equal(calls[0][1].params.alert_ids,'1,2');assert.equal(calls[0][1].signal,signal);assert.equal(r[1].ingest.event_id,'event2');assert.equal(r[0].ingest,undefined);assert.equal(rows[1].ingest,undefined)})
await test('legacy no metadata fetch',async()=>{calls=[];assert.equal(await c.withAlertOrigins(rows,null,signal),rows);assert.equal(calls.length,0)})
await test('empty no metadata fetch',async()=>{calls=[];await c.withAlertOrigins([],{enabled:true},signal);assert.equal(calls.length,0)})
await test('bounded batch',async()=>{calls=[];await assert.rejects(c.withAlertOrigins(Array.from({length:101},(_,id)=>({id})),{enabled:true},signal));assert.equal(calls.length,0)})
await test('404 legacy status no fake profile',async()=>{c.api.get=async()=>{throw{isAxiosError:true,response:{status:404}}};assert.equal(await c.getIntegrationStatus(signal),null)})
await test('500 propagates error',async()=>{c.api.get=async()=>{throw{isAxiosError:true,response:{status:500}}};await assert.rejects(c.getIntegrationStatus(signal))})
}finally{c.api.get=original}
console.log(JSON.stringify({suite:'frontend_helpers',passed,failed:0,mode:'OFFLINE_TEST_NO_NETWORK'}))

fs.writeFileSync(path.join(dir,'results.json'),JSON.stringify({suite:'frontend_helpers',passed,failed:0,mode:'OFFLINE_TEST_NO_NETWORK'},null,2),{flag:'wx'})
console.log('Artifacts: '+dir)
