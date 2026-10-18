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

test('inline monospace toggles only selected text and supports undo and Markdown reopening', () => {
  const editor = new Editor({element:document.createElement('div'), extensions:extensions(), content:'before selected after', contentType:'markdown'});
  editor.commands.setTextSelection({from:8,to:16});
  editor.commands.toggleCode();
  assert.equal(editor.isActive('code'),true);
  assert.equal(editor.getMarkdown(),'before `selected` after');
  assert.equal(editor.getJSON().content[0].type,'paragraph');
  const reopened = new Editor({element:document.createElement('div'), extensions:extensions(), content:editor.getMarkdown(), contentType:'markdown'});
  assert.deepEqual(reopened.getJSON(),editor.getJSON());
  editor.commands.undo();
  assert.equal(editor.getMarkdown(),'before selected after');
  editor.commands.toggleCode();
  editor.commands.toggleCode();
  assert.equal(editor.getMarkdown(),'before selected after');
  editor.destroy(); reopened.destroy();
});

for (const text of ['hello world','a`b', 'a``b']) test('inline monospace preserves literal text: '+JSON.stringify(text), () => {
  const editor = new Editor({element:document.createElement('div'),extensions:extensions(),content:{type:'doc',content:[{type:'paragraph',content:[{type:'text',text}]}]}});
  editor.commands.selectAll(); editor.commands.toggleCode();
  const reopened = new Editor({element:document.createElement('div'),extensions:extensions(),content:editor.getMarkdown(),contentType:'markdown'});
  assert.deepEqual(reopened.getJSON(),editor.getJSON());
  editor.destroy(); reopened.destroy();
});

for (const content of ['**selected**','*selected*','[selected](https://example.com)']) test('monospace retains existing marks: '+content, () => {
  const editor = new Editor({element:document.createElement('div'),extensions:extensions(),content,contentType:'markdown'});
  const marks = editor.getJSON().content[0].content[0].marks;
  editor.commands.selectAll(); editor.commands.toggleCode();
  for (const mark of marks) assert.equal(editor.isActive(mark.type),true);
  const reopened = new Editor({element:document.createElement('div'),extensions:extensions(),content:editor.getMarkdown(),contentType:'markdown'});
  assert.deepEqual(reopened.getJSON(),editor.getJSON());
  editor.destroy(); reopened.destroy();
});

test('selection boundary spaces survive inline monospace publication', () => {
  const editor = new Editor({element:document.createElement('div'),extensions:extensions(),content:'before selected after',contentType:'markdown'});
  editor.commands.setTextSelection({from:7,to:17}); editor.commands.toggleCode();
  const reopened = new Editor({element:document.createElement('div'),extensions:extensions(),content:editor.getMarkdown(),contentType:'markdown'});
  assert.equal(reopened.getText(),editor.getText());
  assert.equal(reopened.getJSON().content[0].content.find(node=>node.marks?.some(mark=>mark.type==='code')).text,'selected');
  editor.destroy(); reopened.destroy();
});
