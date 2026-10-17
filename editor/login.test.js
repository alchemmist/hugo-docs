import test from 'node:test';
import assert from 'node:assert/strict';
import {JSDOM} from 'jsdom';
import {mountLogin} from './login.js';

async function setup(search, session = {}) {
  const dom = new JSDOM('<html lang="en"><body><div id="test-root" data-base-path="/docs/"></div></body></html>', {url:'https://wiki.test/docs/login' + search});
  globalThis.document = dom.window.document; globalThis.location = dom.window.location; globalThis.FormData = dom.window.FormData;
  const calls=[]; const destinations=[];
  globalThis.fetch=async (path, options) => { calls.push({path, options}); return {ok:true,json:async () => session}; };
  const root=document.getElementById('test-root'); await mountLogin(root,url => destinations.push(url));
  return {root,calls,destinations};
}
for (const next of ['https://evil.test/', '//evil.test/', '/outside', '/docs/\\evil.test']) {
  test('login rejects unsafe next ' + next, async () => {
    const {destinations}=await setup('?next='+encodeURIComponent(next),{user:{username:'alice'}});
    assert.deepEqual(destinations,['/docs/admin']);
  });
}
test('login preserves local return target',async () => {
  const {destinations}=await setup('?next=%2Fdocs%2Fstart%2F',{user:{username:'alice'}});
  assert.deepEqual(destinations,['/docs/start/']);
});
test('bootstrap fields only shown for uninitialized instance',async () => {
  const {root}=await setup('',{bootstrap_required:true});
  assert.ok(root.querySelector('[name=secret]'));
  assert.equal(root.querySelector('[name=password]').autocomplete,'new-password');
});
test('failed login keeps credentials and reenables submit', async () => {
  const {root}=await setup('');
  globalThis.fetch=async () => ({ok:false,json:async () => ({detail:'Invalid credentials'})});
  const form=root.querySelector('form'); form.elements.username.value='alice';form.elements.password.value='password';
  form.dispatchEvent(new document.defaultView.Event('submit',{cancelable:true}));
  await new Promise(resolve=>setTimeout(resolve,0));
  assert.match(form.textContent,/Invalid credentials/);
  assert.equal(form.elements.password.value,'password');
  assert.equal(form.querySelector('button').disabled,false);
});
test('submission during session initialization never sends credentials or submits natively', async () => {
  const dom = new JSDOM('<html lang="en"><body><div id="test-root" data-base-path="/docs/"></div></body></html>', {url:'https://wiki.test/docs/login'});
  globalThis.document = dom.window.document;
  globalThis.location = dom.window.location;
  globalThis.FormData = dom.window.FormData;
  let resolveSession;
  const calls = [];
  globalThis.fetch = (path, options) => {
    calls.push({path, options});
    return new Promise(resolve => { resolveSession = resolve; });
  };
  const root = document.getElementById('test-root');
  const mounting = mountLogin(root);
  const form = root.querySelector('form');
  form.elements.username.value = 'alice'; form.elements.password.value = 'secret';
  assert.equal(form.method, 'post');
  assert.equal(form.querySelector('button').disabled, true);
  const event = new dom.window.Event('submit', {cancelable:true});
  form.dispatchEvent(event);
  assert.equal(event.defaultPrevented, true);
  assert.equal(calls.length, 1);
  resolveSession({ok:true,json:async () => ({bootstrap_required:true})});
  await mounting;
  assert.equal(form.querySelector('button').disabled, false);
  assert.ok(form.elements.secret);
});
test('Russian login translates authentication errors and keeps entered credentials', async () => {
  const {root}=await setup('');
  document.documentElement.lang='ru';
  globalThis.fetch=async()=>({ok:false,json:async()=>({detail:'Invalid credentials'})});
  const form=root.querySelector('form');form.elements.username.value='alice';form.elements.password.value='password';
  form.dispatchEvent(new document.defaultView.Event('submit',{cancelable:true}));await new Promise(resolve=>setTimeout(resolve,0));
  assert.match(form.textContent,/Неверный логин или пароль/);
  assert.equal(form.elements.username.value,'alice');assert.equal(form.elements.password.value,'password');
});
