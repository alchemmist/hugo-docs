import test from 'node:test';
import assert from 'node:assert/strict';
import {JSDOM} from 'jsdom';
import {mountAccount} from './account.js';

function setup(session) {
  const dom=new JSDOM('<html lang="en"><body><div id="wiki-editor" data-base-path="/docs/"></div></body></html>',{url:'https://wiki.test/docs/'});
  globalThis.document=dom.window.document;
  const calls=[];
  globalThis.fetch=async(path,options)=>{calls.push({path,options});return {ok:true,json:async()=>path.endsWith('/users')?{users:[]}:session};};
  return {root:document.getElementById('wiki-editor'),calls};
}

test('anonymous account uses configured base path and exposes login without editor privileges',async()=>{
  const {root,calls}=setup({user:null,writable:false});
  const session=await mountAccount(root);
  assert.equal(session.writable,false);
  assert.equal(calls[0].path,'/docs/api/editor/session');
  assert.equal(document.querySelector('.wiki-account-toggle').textContent,'Sign in');
  assert.equal(document.querySelectorAll('form').length,1);
  assert.equal(document.querySelector('input[name=password]').autocomplete,'current-password');
});

test('bootstrap is offered only when server says no administrator exists',async()=>{
  const {root}=setup({user:null,writable:false,bootstrap_required:true});
  await mountAccount(root);
  assert.ok(document.querySelector('input[name=secret]'));
});

test('reader account can change own password but cannot manage users',async()=>{
  const {root,calls}=setup({user:{id:1,username:'reader',role:'reader'},writable:false});
  await mountAccount(root);
  assert.ok(document.querySelector('input[name=current_password]'));
  assert.equal(document.querySelector('.wiki-account-users'),null);
  assert.equal(calls.length,1);
});

test('administrator account exposes user management and loads list',async()=>{
  const {root,calls}=setup({user:{id:1,username:'owner',role:'admin'},writable:true});
  await mountAccount(root);
  assert.ok(document.querySelector('.wiki-account-users'));
  assert.equal(calls[1].path,'/docs/api/admin/users');
});

test('Git status loads on account open and displays conflicts without polling',async()=>{
  const {root}=setup({user:{id:1,username:'editor',role:'editor'},writable:true});
  const calls=[];
  globalThis.fetch=async path=>{calls.push(path);return {ok:true,json:async()=>path.endsWith('/sync')?{git_enabled:true,pending:2,error:'Remote branch changed'}:{user:{id:1,username:'editor',role:'editor'},writable:true}};};
  await mountAccount(root);
  assert.equal(calls.length,1);
  document.querySelector('dialog').showModal=()=>{};
  document.querySelector('.wiki-account-toggle').click();
  await new Promise(resolve=>setTimeout(resolve,0));
  assert.equal(calls.length,2);
  assert.match(document.querySelector('.wiki-account-sync').textContent,/Synchronization failed.*Remote branch changed/);
});
