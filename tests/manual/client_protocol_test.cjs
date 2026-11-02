const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const path=require('node:path');
const requests=[],timers=new Map([[99,()=>{}]]),cleared=[];
const readers=[];
let timerId=99,clientId=0;
const storage=new Map();
const window={
  __DSH_MOUSE_BRIDGE_TIMER__:99,
  crypto:{randomUUID:()=>`client-${++clientId}`},
  localStorage:{getItem:k=>storage.get(k)||'0',setItem:(k,v)=>storage.set(k,v)},
  setInterval:fn=>{timers.set(++timerId,fn);return timerId;},
  clearInterval:id=>{cleared.push(id);timers.delete(id);},
  addEventListener(){},removeEventListener(){},dispatchEvent(){},
  fetch:(url,options)=>{
    requests.push({url,options});
    const pending=[];const reader={read:()=>new Promise(resolve=>pending.push(resolve)),cancel:async()=>{}};
    if(url.endsWith('/events'))readers.push({pending,options});
    return Promise.resolve({ok:true,json:async()=>({granted:false}),body:{getReader:()=>reader}});
  },
  __ModuleLoader__:{load:module=>module.factory(()=>({createElement(){}}))}
};
const context=vm.createContext({window,document:{addEventListener(){},removeEventListener(){}},CustomEvent:class{},AbortController,Date,Math});
const source=fs.readFileSync(path.join(__dirname,'../../plugin/client.js'),'utf8')
  .replace('__BRIDGE_TOKEN__','test-only-secret-with-at-least-32-characters')
  .replace('__BRIDGE_PORT__','18766');
(async()=>{
  vm.runInContext(source,context);
  assert.ok(cleared.includes(99),'Factory reload must stop the legacy heartbeat even without apply()');
  vm.runInContext(source,context);
  assert.equal(timers.size,1,'Exactly one current heartbeat must survive hot reload');
  [...timers.values()][0]();
  await new Promise(resolve=>setImmediate(resolve));
  const before=requests.filter(r=>r.options.method==='POST').length;
  const active=readers.at(-1);
  active.pending.shift()({done:false,value:new Uint8Array([1])});
  await new Promise(resolve=>setImmediate(resolve));
  assert.ok(requests.filter(r=>r.options.method==='POST').length>before,'Incoming events must keep the lease alive without timer callbacks');
  assert.ok(requests.length>=3);
  for(const {url,options} of requests){
    assert.ok(url==='http://127.0.0.1:18766/state'||url==='http://127.0.0.1:18766/events');
    assert.equal(options.mode,'cors');
    assert.ok(options.headers.Authorization.startsWith('Bearer '));
    assert.ok(!url.includes('?'),'Credentials must never be in request URLs');
  }
  console.log('client protocol and hot reload passed');
})().catch(error=>{console.error(error);process.exitCode=1;});
