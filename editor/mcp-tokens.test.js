import test from 'node:test';
import assert from 'node:assert/strict';
import {JSDOM} from 'jsdom';
import {mountMcpTokens} from './mcp-tokens.js';

const tick = () => new Promise(resolve => setTimeout(resolve, 0));
function setup() {
  const dom = new JSDOM('<html lang="en"><body><main></main></body></html>', {url:'https://wiki.test/admin'});
  globalThis.document = dom.window.document;
  return document.querySelector('main');
}
const session = {mcp_enabled:true,mcp_url:'https://wiki.test/mcp',user:{role:'editor'}};

test('disabled MCP has no UI or requests', async () => {
  const root = setup(); await mountMcpTokens(root, {...session,mcp_enabled:false}, () => assert.fail());
  assert.equal(root.children.length, 0);
});
test('create shows secret only in temporary field and revoke clears it', async () => {
  const root = setup(); const calls = []; let tokens = [];
  await mountMcpTokens(root, session, async (path, data, method) => {
    calls.push({path,data,method});
    if (method === 'DELETE') return {};
    if (data) { const token = {id:'abc',name:data.name,read_only:false,created_at:1700000000,expires_at:1800000000}; tokens=[token]; return {...token,token:'secret-once'}; }
    return {tokens};
  });
  const form = root.querySelector('form'); form.elements.token_name.value='Agent';
  form.dispatchEvent(new document.defaultView.Event('submit', {cancelable:true})); await tick();
  assert.deepEqual(calls[1].data,{name:'Agent',expires_days:90,read_only:false});
  assert.equal(root.querySelector('.wiki-mcp-secret input').value,'secret-once');
  assert.ok(!root.innerHTML.includes('secret-once'));
  assert.equal(document.defaultView.localStorage.length,0);
  assert.match(root.querySelector('pre').textContent, /Bearer <YOUR_TOKEN>/);
  root.querySelector('.wiki-mcp-token button').click(); await tick();
  assert.deepEqual(calls.at(-1),{path:'auth/tokens/abc',data:{},method:'DELETE'});
  assert.equal(root.querySelector('.wiki-mcp-secret').children.length,0);
});
test('reader tokens are read only and initialization errors can retry', async () => {
  const root = setup(); let fail = true;
  await mountMcpTokens(root, {...session,user:{role:'reader'}}, async () => { if (fail) throw new Error('Offline'); return {tokens:[]}; });
  assert.match(root.textContent,/Offline/);
  const input = root.querySelector('[name=read_only]'); assert.ok(input.checked && input.disabled);
  fail=false; [...root.querySelectorAll('button')].find(x => x.textContent==='Refresh').click(); await tick();
  assert.match(root.textContent,/No tokens yet/);
  assert.doesNotMatch(root.textContent,/Offline/);
});
test('creation failure preserves draft and enables retry', async () => {
  const root = setup(); await mountMcpTokens(root,session,async (path,data) => { if(data) throw new Error('Limit reached'); return {tokens:[]}; });
  const form=root.querySelector('form'); form.elements.token_name.value='Keep';
  form.dispatchEvent(new document.defaultView.Event('submit',{cancelable:true})); await tick();
  assert.equal(form.elements.token_name.value,'Keep'); assert.equal(form.querySelector('button').disabled,false);
  assert.match(root.textContent,/Limit reached/); assert.equal(root.querySelector('.wiki-mcp-secret').children.length,0);
});
