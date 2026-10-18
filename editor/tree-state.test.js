import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { JSDOM } from 'jsdom';

const source = readFileSync(new URL('../assets/tree-state.js', import.meta.url), 'utf8');
const turn = () => new Promise(resolve => setTimeout(resolve, 0));
function setup(saved, scroll, denied = false) {
  const dom = new JSDOM('<head></head><body data-site-key="/docs/" data-ui=\'{"expandFolder":"Expand","collapseFolder":"Collapse"}\'></body>', { url: 'https://example.test/docs/', runScripts: 'outside-only', pretendToBeVisual: true });
  const { window } = dom;
  if (saved !== undefined) window.localStorage.setItem('hugo-docs:/docs/:tree', saved);
  if (scroll !== undefined) window.sessionStorage.setItem('hugo-docs:/docs/:tree:scroll', String(scroll));
  if (denied) {
    Object.defineProperty(window, 'localStorage', { get() { throw new Error('denied'); } });
    Object.defineProperty(window, 'sessionStorage', { get() { throw new Error('denied'); } });
  }
  window.eval(source);
  return dom;
}
const branch = '<nav class="page-tree"><li data-current-branch><button data-section="/folder" data-title="Folder" aria-controls="children" aria-expanded="true"></button><div id="children">Page</div></li></nav>';
test('restores parser-inserted branches before deferred initialization and respects explicit collapse', async () => {
  const dom = setup('{"/folder":false}');
  dom.window.document.body.insertAdjacentHTML('beforeend', branch);
  await Promise.resolve();
  assert.equal(dom.window.document.getElementById('children').hidden, true);
  assert.equal(dom.window.document.querySelector('button').getAttribute('aria-expanded'), 'false');
  assert.equal(dom.window.document.querySelector('button').getAttribute('aria-label'), 'Expand Folder');
  dom.window.close();
});
test('normalizes legacy keys and shares subsequent toggle state', () => {
  const dom = setup('{"/folder/":false,"/other":true}');
  const state = dom.window.WikiTreeState;
  assert.equal(state.get('folder', true), false);
  assert.equal(state.get('/other/', false), true);
  assert.equal(state.get('new', true), true);
  state.set('/folder/', true);
  assert.equal(state.get('folder', false), true);
  assert.deepEqual(JSON.parse(dom.window.localStorage.getItem('hugo-docs:/docs/:tree')), { folder: true, other: true });
  dom.window.close();
});
test('ignores malformed and array storage', () => {
  for (const saved of ['broken', '[false]', 'null', '{"x":"false"}']) {
    const dom = setup(saved);
    assert.equal(dom.window.WikiTreeState.get('x', true), true);
    dom.window.WikiTreeState.set('x', false);
    assert.equal(dom.window.WikiTreeState.get('x', true), false);
    dom.window.close();
  }
});
test('denied storage keeps session memory operational', () => {
  const dom = setup(undefined, undefined, true);
  const state = dom.window.WikiTreeState;
  state.set('folder', false);
  assert.equal(state.get('/folder', true), false);
  state.saveScroll(240);
  assert.equal(state.readScroll(), 240);
  dom.window.close();
});
test('restores scroll without persisting a transient initialization clamp', async () => {
  const dom = setup('{}', 320);
  const { document, WikiTreeState: state } = dom.window;
  document.body.insertAdjacentHTML('beforeend', branch);
  await turn();
  const nav = document.querySelector('nav');
  assert.equal(nav.scrollTop, 320);
  nav.scrollTop = 0;
  nav.dispatchEvent(new dom.window.Event('scroll'));
  assert.equal(state.readScroll(), 320);
  nav.dispatchEvent(new dom.window.Event('wheel'));
  nav.scrollTop = 120;
  nav.dispatchEvent(new dom.window.Event('scroll'));
  assert.equal(state.readScroll(), 120);
  assert.equal(dom.window.sessionStorage.getItem('hugo-docs:/docs/:tree:scroll'), '120');
  dom.window.close();
});

test('remembers default-open ancestors without storing closed defaults', async () => {
  const dom = setup('{}');
  const { document, WikiTreeState: state } = dom.window;
  document.body.insertAdjacentHTML('beforeend', branch + '<button data-section="/unseen" aria-controls="unseen-children" aria-expanded="false"></button><div id="unseen-children" hidden></div>');
  state.restoreStatic();
  assert.equal(state.get('folder'), true);
  assert.equal(state.get('unseen'), undefined);
  document.querySelector('[data-section="/folder"]').setAttribute('aria-expanded', 'false');
  state.restoreStatic();
  assert.equal(document.getElementById('children').hidden, false);
  state.set('folder', false);
  state.restoreStatic();
  assert.equal(document.getElementById('children').hidden, true);
  await turn();
  dom.window.close();
});

test('interaction during parsing survives late initialization and mutation restoration', async () => {
  const dom = setup('{}', 320);
  const { document, WikiTreeState: state } = dom.window;
  document.body.insertAdjacentHTML('beforeend', branch);
  const nav = document.querySelector('nav');
  nav.dispatchEvent(new dom.window.Event('wheel', { bubbles: true }));
  nav.scrollTop = 90;
  nav.dispatchEvent(new dom.window.Event('scroll'));
  document.body.insertAdjacentHTML('beforeend', '<div>Parser continuation</div>');
  await turn();
  assert.equal(nav.scrollTop, 90);
  assert.equal(state.readScroll(), 90);
  dom.window.close();
});
