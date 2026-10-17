import test from 'node:test';
import assert from 'node:assert/strict';
import {JSDOM} from 'jsdom';
import {resolvePreviewLinks} from './preview-links.js';
test('saved reading snapshot resolves Hugo links including relative pages and local anchors', () => {
  globalThis.document = new JSDOM('').window.document;
  const refs = new Map([['__wiki_relref_0__',{target:'/help/problems.md#network'}],['__wiki_relref_1__',{target:'services.md'}],['__wiki_relref_2__',{target:'#local'}]]);
  const html = resolvePreviewLinks('<a href="__wiki_relref_0__">Help</a><a href="__wiki_relref_1__">Services</a><a href="__wiki_relref_2__">Local</a>',refs,'start/edit-wiki.md');
  const node = document.createElement('div'); node.innerHTML=html;
  assert.deepEqual([...node.querySelectorAll('a')].map(link=>link.getAttribute('href')),['/help/problems/#network','/start/services/','#local']);
  assert.doesNotMatch(html,/__wiki_relref/);
});

test('preview links retain the runtime base path', () => {
  globalThis.document = new JSDOM('').window.document;
  const html=resolvePreviewLinks('<a href="ref">Help</a>',new Map([['ref',{target:'/help.md'}]]),'index.md','/docs/');
  assert.match(html,/href="\/docs\/help\/"/);
});
