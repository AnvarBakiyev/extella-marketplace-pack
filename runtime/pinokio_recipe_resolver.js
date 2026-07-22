// Резолвер Pinokio-рецептов → плоские shell.run шаги + порт (детерминированно, свой мини-kernel).
// node recipe_resolve.js <app_dir> <entry.js> [gpu] [platform] [fixed_port]
const path = require('path');
const os = require('os');
const net = require('net');
const cp = require('child_process');
const fs = require('fs');
const vm = require('vm');

// ── ПЕСОЧНИЦА ──────────────────────────────────────────────────────────────
// Рецепты — чужой JS из склонированного репо. НЕЛЬЗЯ исполнять его с полными
// правами Node (fs/child_process/сеть/process.env-секреты). Грузим рецепт в
// vm-контекст: доступны только module/exports, безвредные path|os, и require
// соседних .js рецептов (тоже в песочнице). Всё остальное (fs, child_process,
// net, http…) — заблокировано. Опасные операции (which/exists) делает НАШ
// kernel, а не рецепт.
const SAFE_MODULES = { path: path, os: { platform:()=>process.platform, arch:()=>os.arch(), homedir:()=>os.homedir(), cpus:()=>os.cpus(), totalmem:()=>os.totalmem(), type:()=>os.type() } };
function makeSandboxRequire(baseDir, kernel, seen){
  return function sandboxRequire(spec){
    if(SAFE_MODULES[spec]) return SAFE_MODULES[spec];
    if(/^\.\.?\//.test(spec)){                         // соседний файл-рецепт
      let f = path.resolve(baseDir, spec);
      if(!/\.js(on)?$/.test(f) && fs.existsSync(f+'.js')) f=f+'.js';
      if(f.endsWith('.json')){ try{ return JSON.parse(fs.readFileSync(f,'utf8')); }catch(e){ return {}; } }
      if(!f.startsWith(kernel._root)) throw new Error('sandbox: путь вне приложения: '+spec);
      if(seen.has(f)) return {};                        // защита от циклов
      seen.add(f);
      return runInSandbox(f, kernel, seen);
    }
    throw new Error('sandbox: модуль запрещён: '+spec); // fs/child_process/net/http/…
  };
}
function runInSandbox(file, kernel, seen){
  const code = fs.readFileSync(file, 'utf8');
  const sandbox = {
    module:{exports:{}}, exports:{},
    require: makeSandboxRequire(path.dirname(file), kernel, seen),
    console: { log:()=>{}, error:()=>{}, warn:()=>{} },
    // безвредный process: только платформа/арх, БЕЗ env/exit/cwd-записи/argv
    process: { platform:process.platform, arch:os.arch(), env:{}, version:process.version },
    Buffer: Buffer, setTimeout:()=>{}, clearTimeout:()=>{}, __dirname:path.dirname(file), __filename:file,
  };
  sandbox.global = sandbox; sandbox.globalThis = sandbox;
  vm.createContext(sandbox);
  vm.runInContext(code, sandbox, { filename:file, timeout:5000 });   // 5с потолок на загрузку
  const me = sandbox.module.exports;                                  // функция ИЛИ непустой объект → это и есть рецепт
  if(typeof me==='function' || (me && Object.keys(me).length)) return me;
  return sandbox.exports;
}

function detectGpu(){ if(process.platform==='darwin') return os.arch()==='arm64'?'apple':'cpu';
  try{ cp.execSync('nvidia-smi',{stdio:'ignore'}); return 'nvidia'; }catch(e){} return 'cpu'; }
function freePortSync(pref){
  if(pref) return pref;
  try{ const s=net.createServer(); return new Promise(res=>{ s.listen(0,()=>{const p=s.address().port; s.close(()=>res(p));}); }); }
  catch(e){ return 7860; }
}

// Мини-kernel (то, что рецепты ждут от Pinokio)
function makeKernel(root, forcedPort){
  const gpu = process.env.REC_GPU || detectGpu();
  const platform = process.env.REC_PLATFORM || process.platform;
  let _port = forcedPort || null;
  return {
    _root: path.resolve(root),
    gpu, platform, arch: os.arch(), homedir: os.homedir(),
    port: async () => { if(!_port){ _port = await freePortSync(null); } return _port; },
    path: (...a) => path.resolve(root, ...a),
    which: (c) => { try{ return cp.execSync((process.platform==='win32'?'where ':'which ')+c).toString().trim().split('\n')[0]; }catch(e){ return null; } },
    exists: (p) => require('fs').existsSync(path.resolve(root,p)),
    api: {}, memory: {}, bin: { path: ()=>path.join(os.homedir(),'pinokio','bin') },
    _getPort: () => _port,
  };
}

function tmpl(val,c){ if(typeof val!=='string'||!val.includes('{{')) return val;
  return val.replace(/\{\{([\s\S]*?)\}\}/g,(_,e)=>{ try{ const f=new Function('gpu','platform','arch','args','input','cwd','port','exists','which','kernel','path','return ('+e+')');
    const r=f(c.gpu,c.platform,c.arch,c.args||{},c.input||{},c.cwd,c.port,c.exists,c.which,c.kernel,path); return (r==null)?'':String(r);}catch(x){return '';} }); }
function tmplDeep(o,c){ if(Array.isArray(o)) return o.map(x=>tmplDeep(x,c)).filter(x=>x!==''&&x!==null);
  if(o&&typeof o==='object'){const r={};for(const k in o)r[k]=tmplDeep(o[k],c);return r;} return tmpl(o,c); }
function evalWhen(when,c){ if(!when) return true;
  // exists/which/path обязаны быть доступны — ReferenceError тихо давал false и шаги выпадали
  try{ const expr=String(when).replace(/^\{\{|\}\}$/g,''); return !!(new Function('gpu','platform','arch','args','exists','which','kernel','path','return ('+expr+')')(c.gpu,c.platform,c.arch,c.args||{},c.exists,c.which,c.kernel,path)); }catch(e){ return false; } }

async function loadRecipe(file, kernel){
  let m = runInSandbox(file, kernel, new Set([path.resolve(file)]));  // в песочнице, БЕЗ require()
  if(typeof m==='function'){ m = await m(kernel); }   // async(kernel)=>{} тоже
  return m;
}
async function resolve(root, entry, args, depth, out, kernel){
  if(depth>6) return;
  const file=path.resolve(root,entry);
  let rec; try{ rec=await loadRecipe(file,kernel); }catch(e){ out.meta.errors.push(entry+': '+e.message); return; }
  if(rec && rec.daemon) out.meta.daemon=true;
  const run=(rec&&rec.run)||[];
  const c={gpu:kernel.gpu,platform:kernel.platform,arch:kernel.arch,args:args||{},input:{event:['']},cwd:root,port:kernel._getPort(),exists:(p)=>kernel.exists(p),which:(x)=>kernel.which(x),kernel:kernel};
  for(const step of run){
    if(!evalWhen(step.when,c)) continue;
    const method=step.method||'';
    const p=tmplDeep(step.params||{},{...c,port:kernel._getPort()});
    if(method==='shell.run'){
      let msgs=p.message; if(typeof msgs==='string') msgs=[msgs]; msgs=(msgs||[]).filter(m=>m&&String(m).trim());
      if(msgs.length) out.steps.push({method:'shell.run',params:{venv:p.venv||null,path:p.path||'',env:p.env||{},message:msgs}});
    } else if(method==='script.start'||method==='script.run'){
      const uri=p.uri; const sub=(step.params&&step.params.params)||{};
      if(uri&&/\.js(on)?$/.test(uri)) await resolve(root,uri,sub,depth+1,out,kernel);
    } else if(method==='fs.download'||method==='fs.link'||method==='fs.copy'){ out.steps.push({method,params:p}); }
  }
}
(async()=>{
  const [,,appDir,entry,gpu,platform,fixedPort]=process.argv;
  if(gpu) process.env.REC_GPU=gpu; if(platform) process.env.REC_PLATFORM=platform;
  const kernel=makeKernel(appDir||'.', fixedPort?parseInt(fixedPort):null);
  await kernel.port();  // зафиксировать порт
  const out={steps:[],meta:{daemon:false,errors:[]}};
  await resolve(appDir||'.', entry||'install.js', {}, 0, out, kernel);
  console.log(JSON.stringify({gpu:kernel.gpu,platform:kernel.platform,port:kernel._getPort(),daemon:out.meta.daemon,errors:out.meta.errors,steps:out.steps},null,2));
})();

