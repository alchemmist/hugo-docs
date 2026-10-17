import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readdirSync, readFileSync } from 'node:fs';
import { JSDOM } from 'jsdom';
import { Editor } from '@tiptap/core';
import { extensions, prepareMarkdown, restoreMarkdown, sourceBody } from './markdown.js';
const dom = new JSDOM('<html><body></body></html>');
for (const name of ['window', 'document', 'navigator', 'Node', 'HTMLElement', 'getComputedStyle']) Object.defineProperty(globalThis, name, {value: dom.window[name], configurable: true});
function files(path) { return readdirSync(path, {withFileTypes:true}).flatMap(item => item.isDirectory() ? files(path + '/' + item.name) : [path + '/' + item.name]); }
for (const path of files('exampleSite/content').filter(path => path.endsWith('.md'))) test('roundtrip ' + path, () => {
  const original = readFileSync(path, 'utf8').replace(/^---\n[\s\S]*?\n---\n/, '');
  const {prepared, refs} = prepareMarkdown(original);
  const editor = new Editor({element: document.createElement('div'), extensions: extensions(), content: prepared, contentType: 'markdown'});
  const initial = editor.getJSON();
  const markdown = restoreMarkdown(editor.getMarkdown(), refs);
  assert.equal(sourceBody(original, initial, editor.getJSON(), editor.getMarkdown(), refs), original);
  const reparsed = prepareMarkdown(markdown);
  const second = new Editor({element: document.createElement('div'), extensions: extensions(), content: reparsed.prepared, contentType: 'markdown'});
  assert.deepEqual(second.getJSON(), initial);
  for (const {original: ref} of refs.values()) assert.ok(markdown.includes(ref));
  editor.destroy(); second.destroy();
});
