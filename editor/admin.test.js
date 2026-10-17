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
  const reset = root.querySelector('.wiki-admin-user form');
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
