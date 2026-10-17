import { test } from 'node:test';
import assert from 'node:assert/strict';
import { JSDOM } from 'jsdom';
import { Editor } from '@tiptap/core';
import { extensions, prepareMarkdown, restoreMarkdown, sourceBody } from './markdown.js';
import { insertRichContent } from './rich-content.js';
import { registerPlugin } from './plugins.js';
globalThis.requestAnimationFrame = () => 0;
const dom = new JSDOM('<html><body></body></html>');
for (const name of ['window', 'document', 'navigator', 'Node', 'HTMLElement', 'getComputedStyle']) Object.defineProperty(globalThis, name, {value: dom.window[name], configurable: true});
function parse(source) {
  const {prepared, refs} = prepareMarkdown(source);
  const editor = new Editor({element: document.createElement('div'), extensions: extensions(), content: prepared, contentType: 'markdown'});
  return {editor, refs};
}
for (const [type, source] of [
  ['image', '![example|400](image.png)'],
  ['taskList', '- [x] completed\n- [ ] pending'],
  ['wikiInlineMath', 'Formula $x^2$ here.'],
  ['wikiDisplayMath', '$$\nx^2\n$$'],
  ['wikiMermaid', '```mermaid\ngraph TD; A-->B\n```'],
  ['wikiAlert', '> [!NOTE]\n> Keep this text.'],
  ['wikiFootnoteDefinition', '[^note]: A footnote'],
  ['wikiFootnote', 'Text[^note]'],
  ['wikiShortcode', '{{< unknown param="value" >}}'],
  ['wikiProtectedHTML', 'Text <span data-x="1">inline</span>'],
]) test(`preserves and represents ${type}`, () => {
  const {editor, refs} = parse(source);
  const initial = editor.getJSON();
  assert.ok(JSON.stringify(initial).includes(`"type":"${type}"`), JSON.stringify(initial));
  assert.equal(sourceBody(source, initial, initial, editor.getMarkdown(), refs), source);
  const generated = restoreMarkdown(editor.getMarkdown(), refs);
  const second = parse(generated).editor;
  assert.deepEqual(second.getJSON(), initial);
  editor.destroy(); second.destroy();
});
test('plugins reject incompatible API versions and duplicate names', () => {
  assert.throws(() => registerPlugin({apiVersion: 2}));
  const plugin = {apiVersion: 1, name: 'example', level: 'inline', parse() {}, serialize() {}, validate() {return true;}};
  const remove = registerPlugin(plugin);
  assert.throws(() => registerPlugin(plugin));
  remove();
});
test('protected HTML never becomes active DOM', () => {
  const {editor} = parse('Before <script>alert(1)</script> after');
  assert.equal(editor.view.dom.querySelector('script'), null);
  assert.ok(editor.getMarkdown().includes('<script>alert(1)</script>'));
  editor.destroy();
});
test('unknown block HTML remains intact when nearby text changes', () => {
  const source = '<section data-custom="yes">\nUnknown **content**\n</section>';
  const {editor} = parse(source + '\n\nAfter');
  assert.ok(editor.getMarkdown().includes(source), editor.getMarkdown());
  editor.destroy();
});
test('external plugin takes precedence over protected shortcode fallback', async () => {
  const {installBadgePlugin} = await import('./plugins-example.js');
  const remove = installBadgePlugin();
  const {editor} = parse('{{< badge "Ready" >}}');
  assert.ok(JSON.stringify(editor.getJSON()).includes('wikiBadge'));
  assert.equal(editor.view.dom.querySelector('.wiki-badge').textContent, 'Ready');
  assert.ok(editor.getMarkdown().includes('{{< badge "Ready" >}}'));
  editor.destroy(); remove();
});
test('media image syntax creates a playable video', () => {
  const {editor} = parse('![|85](clip.mp4)');
  const video = editor.view.dom.querySelector('video');
  assert.ok(video);
  assert.equal(video.controls, true);
  assert.equal(video.style.maxWidth, '85%');
  editor.destroy();
});

test('sequential rich block insertions retain each previous block', () => {
  const {editor} = parse('');
  for (const kind of ['math', 'mermaid', 'alert']) assert.equal(insertRichContent(editor, kind), true);
  const types = editor.getJSON().content.map(node => node.type);
  assert.deepEqual(types.filter(type => type !== 'paragraph'), ['wikiDisplayMath', 'wikiMermaid', 'wikiAlert']);
  assert.equal(editor.state.selection.$from.parent.type.name, 'paragraph');
  assert.ok(editor.view.dom.querySelector('.markdown-alert--note'));
  editor.destroy();
});
