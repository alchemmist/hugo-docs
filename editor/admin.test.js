import test from 'node:test';
import assert from 'node:assert/strict';
import {JSDOM} from 'jsdom';
import {mountAdmin} from './admin.js';

function setup(role, handler) {
  const dom = new JSDOM('<html lang="en"><body><div id="test-root" data-base-path="/docs/"></div></body></html>', {url:'https://wiki.test/docs/admin'});
  globalThis.document = dom.window.document;
  globalThis.FormData = dom.window.FormData;
  const calls = [];
  globalThis.fetch = async (path, options) => {
    calls.push({path, options});
    return {ok:true,json:async () => handler?.(path, options) || (path.endsWith('/session') ? {user:role ? {id:1,username:'alice',role} : null,writable:role !== 'reader',csrf_token:'csrf'} : path.endsWith('/users') ? {users:[]} : {git_enabled:false})};
  };
  return {root:document.getElementById('test-root'),calls};
}
const tick = () => new Promise(resolve => setTimeout(resolve,0));

test('anonymous admin visit redirects to prefixed login', async () => {
  const {root} = setup(null); const destinations=[];
  await mountAdmin(root, value => destinations.push(value));
  assert.deepEqual(destinations,['/docs/login?next=%2Fdocs%2Fadmin']);
});
test('reader can change password without admin or sync requests', async () => {
  const {root,calls} = setup('reader'); const destinations=[];
  await mountAdmin(root, value => destinations.push(value));
  assert.equal(root.querySelectorAll('form').length,1);
  assert.equal(root.querySelector('.wiki-admin-users'),null);
  root.querySelector('[name=current_password]').value='old-password';
  root.querySelector('[name=password]').value='new-password';
  root.querySelector('form').dispatchEvent(new document.defaultView.Event('submit',{cancelable:true})); await tick();
  assert.equal(calls[1].path,'/docs/api/auth/password');
  assert.equal(calls[1].options.headers['X-CSRF-Token'],'csrf');
  assert.equal(destinations.length,1);
});
test('administrator sees users and sync and can create a role', async () => {
  const {root,calls} = setup('admin'); await mountAdmin(root);
  assert.ok(root.querySelector('.wiki-admin-users'));
  assert.ok(root.querySelector('.wiki-admin-sync'));
  const create = [...root.querySelectorAll('form')].at(-1);
  create.elements.username.value='bob'; create.elements.password.value='new-password'; create.elements.role.value='editor';
  create.dispatchEvent(new document.defaultView.Event('submit',{cancelable:true})); await tick();
  assert.ok(calls.some(call => call.path.endsWith('/users') && call.options.body === JSON.stringify({username:'bob',password:'new-password',role:'editor'})));
});
test('network failure preserves password draft and permits retry', async () => {
  const {root} = setup('reader'); await mountAdmin(root);
  globalThis.fetch = async () => { throw new Error('Offline'); };
  const form=root.querySelector('form'); form.elements.password.value='keep-me';
  form.dispatchEvent(new document.defaultView.Event('submit',{cancelable:true})); await tick();
  assert.equal(form.elements.password.value,'keep-me');
  assert.match(form.textContent,/Offline/);
  assert.equal(form.querySelector('button').disabled,false);
});
test('password forms associate the correct username without sending it in password payload', async () => {
  const {root,calls} = setup('admin', path => path.endsWith('/users') ? {users:[{id:2,username:'bob',role:'reader',disabled:false}]} : undefined);
  await mountAdmin(root);
  const own = root.querySelector('form');
  const reset = root.querySelector('.wiki-admin-user-reset form');
  assert.equal(own.elements.username.value,'alice');
  assert.equal(reset.elements.username.value,'bob');
  for (const form of [own,reset]) { assert.equal(form.method,'post'); assert.equal(form.elements.username.autocomplete,'username'); assert.equal(form.elements.username.hidden,true); }
  reset.elements.password.value='new-password';
  reset.dispatchEvent(new document.defaultView.Event('submit',{cancelable:true})); await tick();
  assert.deepEqual(JSON.parse(calls.find(x=>x.path.endsWith('/2/password')).options.body),{password:'new-password'});
});
test('Russian admin error preserves form values',async () => {
  const {root}=setup('admin'); document.documentElement.lang='ru'; await mountAdmin(root);
  globalThis.fetch=async()=>({ok:false,json:async()=>({detail:'Username already exists'})});
  const form=[...root.querySelectorAll('form')].at(-1);
  form.elements.username.value='alice';form.elements.password.value='long-password';
  form.dispatchEvent(new document.defaultView.Event('submit',{cancelable:true}));await tick();
  assert.match(form.textContent,/Пользователь с таким логином уже существует/);
  assert.equal(form.elements.username.value,'alice');assert.equal(form.elements.password.value,'long-password');
});

test('navigation reflects role and enabled capabilities', async () => {
  for (const [role, expected] of [['reader',['account','mcp']],['editor',['account','sync','mcp']],['admin',['account','sync','mcp','users']]]) {
    const {root,calls} = setup(role, path => path.endsWith('/session') ? {user:{username:'alice',role},writable:role !== 'reader',mcp_enabled:true,mcp_url:'https://wiki.test/mcp'} : path.endsWith('/tokens') ? {tokens:[]} : undefined);
    await mountAdmin(root);
    assert.deepEqual([...root.querySelectorAll('nav a')].map(link => link.hash.slice(1)), expected);
    assert.deepEqual([...root.querySelectorAll('.wiki-admin-panels > section:not([hidden])')].map(panel => panel.id), ['admin-account']);
    assert.equal(root.querySelector('[aria-current="page"]').hash,'#account');
    if (role !== 'admin') assert.equal(calls.some(call => call.path.includes('/admin/users')),false);
    if (role === 'reader') assert.equal(calls.some(call => call.path.endsWith('/sync')),false);
  }
});

test('section deep links and history preserve form drafts', async () => {
  const {root} = setup('admin');
  const view = document.defaultView;
  view.history.replaceState(null,'','#users');
  await mountAdmin(root);
  assert.equal(root.querySelector('[aria-current="page"]').hash,'#users');
  const create = root.querySelector('.wiki-admin-create form');
  create.elements.username.value = 'draft-user';
  view.history.pushState(null,'','#account'); view.dispatchEvent(new view.HashChangeEvent('hashchange'));
  assert.equal(root.querySelector('#admin-account').hidden,false);
  assert.equal(root.querySelector('#admin-users').hidden,true);
  view.history.back(); await new Promise(resolve => setTimeout(resolve,30));
  assert.equal(root.querySelector('#admin-users').hidden,false);
  assert.equal(create.elements.username.value,'draft-user');
  view.history.replaceState(null,'','#unknown'); view.dispatchEvent(new view.HashChangeEvent('hashchange'));
  assert.equal(root.querySelector('#admin-account').hidden,false);
});

test('account and navigation render before slow services finish', async () => {
  const {root} = setup('admin');
  let releaseSync, releaseUsers;
  globalThis.fetch = async path => ({ok:true,json:async () => path.endsWith('/session') ? {user:{username:'alice',role:'admin'},writable:true} : path.endsWith('/sync') ? new Promise(resolve => {releaseSync=resolve;}) : new Promise(resolve => {releaseUsers=resolve;})});
  const mounted = mountAdmin(root);
  await tick();
  assert.equal(root.querySelectorAll('nav a').length,3);
  assert.equal(root.querySelector('#admin-account').hidden,false);
  assert.ok(root.querySelector('#admin-account [name=current_password]'));
  releaseSync({git_enabled:false}); releaseUsers({users:[]}); await mounted;
});

test('remount replaces its history listener', async () => {
  const {root} = setup('reader'); const view=document.defaultView;
  const add=view.addEventListener.bind(view), remove=view.removeEventListener.bind(view);
  const registered=[],removed=[];
  view.addEventListener=(type,listener,...args)=>{if(type==='hashchange')registered.push(listener);return add(type,listener,...args);};
  view.removeEventListener=(type,listener,...args)=>{if(type==='hashchange')removed.push(listener);return remove(type,listener,...args);};
  await mountAdmin(root); await mountAdmin(root);
  assert.equal(registered.length,2);assert.deepEqual(removed,[registered[0]]);
});

test('switching sections keeps a newly issued MCP token', async () => {
  const {root} = setup('reader', (path, options) => path.endsWith('/session') ? {user:{username:'alice',role:'reader'},writable:false,mcp_enabled:true,mcp_url:'https://wiki.test/mcp'} : path.endsWith('/tokens') ? options.method === 'POST' ? {id:'token-1',token:'wiki_personal_secret'} : {tokens:[]} : undefined);
  await mountAdmin(root);
  const view=document.defaultView;
  const activate = id => {view.history.replaceState(null,'','#'+id);view.dispatchEvent(new view.HashChangeEvent('hashchange'));};
  activate('mcp');
  const form=root.querySelector('#admin-mcp form');form.elements.token_name.value='agent';
  form.dispatchEvent(new view.Event('submit',{cancelable:true}));await tick();
  const secret=root.querySelector('.wiki-mcp-secret input');
  assert.equal(secret.value,'wiki_personal_secret');
  activate('account');activate('mcp');
  assert.equal(root.querySelector('.wiki-mcp-secret input'),secret);
  assert.equal(secret.value,'wiki_personal_secret');
});

test('users appear as compact semantic rows with collapsed creation and reset forms', async () => {
  const {root,calls} = setup('admin', path => path.endsWith('/users') ? {users:[{id:2,username:'bob',role:'reader',disabled:false},{id:3,username:'eve',role:'editor',disabled:true}]} : undefined);
  await mountAdmin(root);
  const table=root.querySelector('table.wiki-users-table');
  assert.deepEqual([...table.querySelectorAll('thead th')].map(cell=>[cell.scope,cell.textContent]),[['col','Username'],['col','Role'],['col','Status'],['col','Actions']]);
  assert.deepEqual([...table.querySelectorAll('tbody th')].map(cell=>[cell.scope,cell.textContent]),[['row','bob'],['row','eve']]);
  assert.equal(table.querySelectorAll('.wiki-admin-user').length,2);
  assert.equal(root.querySelector('.wiki-admin-create').open,false);
  const rows=[...table.querySelectorAll('.wiki-admin-user-reset')];
  assert.ok(rows.every(row=>row.hidden && row.firstChild.colSpan === 4));
  const toggles=[...table.querySelectorAll('[aria-controls]')];
  toggles[0].click();
  assert.equal(toggles[0].getAttribute('aria-expanded'),'true');
  assert.equal(rows[0].hidden,false);
  const input=rows[0].querySelector('[name=password]');
  assert.equal(document.activeElement,input);
  input.value='draft-password';
  toggles[1].click(); toggles[0].click(); toggles[0].click();
  assert.equal(rows[1].hidden,false);
  assert.equal(input.value,'draft-password');
  assert.equal(calls.some(call=>call.options.method !== 'GET'),false);
  rows[0].querySelector('form').dispatchEvent(new document.defaultView.Event('submit',{cancelable:true})); await tick();
  assert.equal(rows[0].hidden,true);
  assert.equal(toggles[0].getAttribute('aria-expanded'),'false');
  assert.equal(input.value,'');
  assert.equal(document.activeElement,toggles[0]);
});

test('role failure restores saved role and reset failure retains visible password draft', async () => {
  const {root} = setup('admin', path => path.endsWith('/users') ? {users:[{id:2,username:'bob',role:'reader',disabled:false}]} : undefined);
  await mountAdmin(root);
  globalThis.fetch=async()=>({ok:false,json:async()=>({detail:'Forbidden'})});
  const select=root.querySelector('.wiki-users-table select');
  assert.equal(select.getAttribute('aria-label'),'Role: bob');
  select.value='admin'; select.dispatchEvent(new document.defaultView.Event('change')); await tick();
  assert.equal(select.value,'reader'); assert.equal(select.disabled,false);
  const toggle=root.querySelector('.wiki-users-table [aria-controls]'); toggle.click();
  const details=root.querySelector('.wiki-admin-user-reset'), form=details.querySelector('form');
  form.elements.password.value='keep-this-password';
  form.dispatchEvent(new document.defaultView.Event('submit',{cancelable:true})); await tick();
  assert.equal(details.hidden,false);assert.equal(form.elements.password.value,'keep-this-password');
  assert.ok(form.querySelector('[role=status]').textContent);
  assert.equal(form.querySelector('button').disabled,false);
});

test('disabling a user refreshes the status and action', async () => {
  let disabled=false;
  const {root,calls}=setup('admin',(path,options)=>{
    if(path.endsWith('/users/2')) { disabled=JSON.parse(options.body).disabled; return {}; }
    if(path.endsWith('/users')) return {users:[{id:2,username:'bob',role:'reader',disabled}]};
  });
  await mountAdmin(root);
  root.querySelector('.wiki-admin-user-actions button').click();await tick();
  assert.equal(root.querySelector('.wiki-admin-user-state').textContent,'Disabled');
  assert.equal(root.querySelector('.wiki-admin-user-actions button').textContent,'Enable');
  assert.ok(calls.some(call=>call.options.method === 'PATCH'));
});

test('theme preference is available to every signed-in role without changing server-rendered theme', async () => {
  for (const role of ['reader','editor','admin']) {
    const {root}=setup(role, path => path.endsWith('/session') ? {user:{username:'alice',role,theme:'dark'},csrf_token:'csrf'} : undefined);
    document.documentElement.dataset.theme='dark';
    await mountAdmin(root);
    const control=root.querySelector('#admin-account .wiki-theme-preference select');
    assert.equal(control.value,'dark');
    assert.equal(control.parentElement.tagName,'LABEL');
    assert.equal(control.parentElement.firstChild.textContent,'Theme');
    assert.equal(document.documentElement.dataset.theme,'dark');
    assert.equal(root.querySelectorAll('[name=theme]').length,1);
    assert.equal(document.defaultView.localStorage.length,0);
    assert.equal(document.cookie,'');
  }
});

test('anonymous visits do not render appearance controls', async () => {
  const {root}=setup(null);
  await mountAdmin(root,()=>{});
  assert.equal(root.querySelector('.wiki-theme-preference'),null);
});

test('reader saves own theme with CSRF and waits for confirmation before applying it', async () => {
  const {root,calls}=setup('reader');
  document.documentElement.dataset.theme='light';
  const session=await mountAdmin(root);
  const select=root.querySelector('[name=theme]');
  let complete;
  globalThis.fetch=async(path,options)=>{
    calls.push({path,options});
    return {ok:true,json:()=>new Promise(resolve=>{complete=resolve;})};
  };
  select.value='dark';select.dispatchEvent(new document.defaultView.Event('change'));
  await tick();
  assert.equal(select.disabled,true);
  assert.equal(document.documentElement.dataset.theme,'light');
  const call=calls.at(-1);
  assert.equal(call.path,'/docs/api/auth/preferences');
  assert.equal(call.options.method,'POST');
  assert.equal(call.options.headers['X-CSRF-Token'],'csrf');
  assert.equal(call.options.credentials,'same-origin');
  assert.deepEqual(JSON.parse(call.options.body),{theme:'dark'});
  complete({theme:'dark'});await tick();
  assert.equal(document.documentElement.dataset.theme,'dark');
  assert.equal(session.user.theme,'dark');
  assert.equal(select.disabled,false);
  assert.equal(root.querySelector('.wiki-theme-preference [role=status]').textContent,'Saved');
  assert.equal(document.defaultView.localStorage.length,0);
  assert.equal(document.cookie,'');
});

test('theme failures restore the saved choice without changing the applied theme', async () => {
  for (const response of [{ok:false,json:async()=>({detail:'Forbidden'})},{ok:true,json:async()=>({theme:'unexpected'})}]) {
    const {root}=setup('reader',path=>path.endsWith('/session') ? {user:{username:'alice',role:'reader',theme:'dark'}} : undefined);
    document.documentElement.dataset.theme='dark';
    const session=await mountAdmin(root);
    globalThis.fetch=async()=>response;
    const select=root.querySelector('[name=theme]');
    select.value='light';select.dispatchEvent(new document.defaultView.Event('change'));await tick();
    assert.equal(select.value,'dark');
    assert.equal(select.disabled,false);
    assert.equal(session.user.theme,'dark');
    assert.equal(document.documentElement.dataset.theme,'dark');
    assert.ok(root.querySelector('.wiki-theme-preference [role=status]').textContent);
  }
});
