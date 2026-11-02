const assert=require('node:assert/strict'), fs=require('node:fs'), vm=require('node:vm'), path=require('node:path');
const requests=[], timers=new Map([[99,()=>{}]]), cleared=[], events=new Map(), pending=[], opened=[];
let timerId=99, value, Pill;
const react={
  createElement:(tag,props,...children)=>({tag,props,children}),
  useState:initial=>[value===undefined?(value=typeof initial==='function'?initial():initial):value,v=>{value=v;}],
  useEffect:effect=>effect(),
};
const window={
  __DSH_MOUSE_BRIDGE_TIMER__:99,
  localStorage:{removeItem(){}},
  setInterval:fn=>{timers.set(++timerId,fn);return timerId;},
  clearInterval:id=>{cleared.push(id);timers.delete(id);},
  setTimeout:()=>++timerId,clearTimeout(){},
  addEventListener:(event,fn)=>{events.set(event,fn);},removeEventListener(){},
  dispatchEvent:event=>{const fn=events.get(event.type);if(fn)fn();},
  open:url=>opened.push(url),
  fetch:(url,options)=>{requests.push({url,options});return new Promise((resolve,reject)=>pending.push({resolve,reject}));},
  __ModuleLoader__:{load:module=>{module.factory(()=>react).apply({slots:{
    inject:(name,fn)=>fn(),register:(options,component)=>{Pill=component;}
  }});}},
};
const context=vm.createContext({window,CustomEvent:class{constructor(type){this.type=type;}},AbortController});
const source=fs.readFileSync(path.join(__dirname,'../../plugin/client.js'),'utf8').replace('__BRIDGE_PORT__','18766');
const flush=()=>new Promise(resolve=>setImmediate(resolve));
const reply=(request,state)=>request.resolve({ok:true,json:async()=>state});
(async()=>{
  vm.runInContext(source,context);
  assert.ok(cleared.includes(99));
  assert.equal(Pill().props['data-mouse-permission'],'unknown');
  Pill().props.onClick({isTrusted:false});
  assert.equal(opened.length,0);
  Pill().props.onClick({isTrusted:true});
  assert.equal(opened[0],'icon-control://permissions');
  assert.equal(Pill().props['data-mouse-permission'],'unknown','Opening UI must not optimistically grant');
  reply(pending.shift(),{granted:true,revision:1,session:'test'});await flush();
  assert.equal(Pill().props['data-mouse-permission'],'granted');
  [...timers.values()][0]();
  pending.shift().reject(new Error('offline'));await flush();
  assert.equal(Pill().props['data-mouse-permission'],'unknown','Lost response must not show confirmed revoke');
  vm.runInContext(source,context);value=undefined;
  assert.equal(timers.size,1);
  assert.equal(Pill().props['data-mouse-permission'],'unknown');
  reply(pending.shift(),{granted:false,revision:2,session:'test'});await flush();
  assert.equal(Pill().props['data-mouse-permission'],'denied');
  for(const {url,options} of requests){
    assert.equal(url,'http://127.0.0.1:18766/status');
    assert.equal(options.method,'GET');
    assert.equal(options.credentials,'omit');
    assert.equal(options.headers,undefined,'Renderer must never receive an authorization credential');
  }
  assert.ok(!source.includes('__BRIDGE_TOKEN__'));
  console.log('client protocol and hot reload passed; confirmed-only status, no grants or credentials');
})().catch(error=>{console.error(error);process.exitCode=1;});
