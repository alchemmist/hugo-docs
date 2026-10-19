import {test} from 'node:test';
import assert from 'node:assert/strict';
import {JSDOM} from 'jsdom';
import {Editor} from '@tiptap/core';
import {extensions} from './markdown.js';
const dom = new JSDOM('<html><body></body></html>');
for (const name of ['window','document','navigator','Node','HTMLElement','getComputedStyle']) Object.defineProperty(globalThis,name,{value:dom.window[name],configurable:true});
globalThis.requestAnimationFrame = () => 0;
function create(content = '') { return new Editor({element:document.createElement('div'),extensions:extensions(),content,contentType:'markdown'}); }
function type(editor, text) {
  for (const character of text) {
    const {from,to} = editor.state.selection;
    const handled = editor.view.someProp('handleTextInput', handler => handler(editor.view,from,to,character,()=>editor.state.tr.insertText(character,from,to)));
    if (!handled) editor.view.dispatch(editor.state.tr.insertText(character));
  }
}
for (const ending of [' ', 'Enter']) test(`typed fence with ${ending} creates a Python block`, () => {
  const editor = create();
  type(editor,'```python');
  if (ending === 'Enter') editor.view.someProp('handleKeyDown',handler=>handler(editor.view,new window.KeyboardEvent('keydown',{key:'Enter'})));
  else type(editor,ending);
  assert.equal(editor.getJSON().content[0].type,'codeBlock');
  assert.equal(editor.getJSON().content[0].attrs.language,'python');
  editor.destroy();
});

async function paste(editor,text) {
  const {pasteCodeText} = await import('./code-block.js');
  let prevented = false;
  pasteCodeText(editor,{preventDefault(){prevented=true;},clipboardData:{getData:()=>text}});
  assert.ok(prevented);
}

test('pastes fenced Python as a block preserving language and indentation', async () => {
  const editor = create();
  await paste(editor,'```python\ndef run():\n    print("Hello")\n```');
  const block = editor.getJSON().content[0];
  assert.equal(block.type,'codeBlock');
  assert.equal(block.attrs.language,'python');
  assert.equal(block.content[0].text,'def run():\n    print("Hello")');
  assert.match(editor.getMarkdown(),/^```python\n/);
  editor.destroy();
});
test('pasting fenced text inside code preserves literal nested fences', async () => {
  const editor = create('```python\nx\n```');
  editor.commands.setTextSelection(2);
  const source = '\n```javascript\nlet x = 1;\n```';
  await paste(editor,source);
  assert.equal(editor.getJSON().content.filter(node=>node.type==='codeBlock').length,1);
  assert.equal(editor.getJSON().content[0].content[0].text,'x'+source);
  editor.destroy();
});
test('partial fences and inline backticks paste literally', async () => {
  for (const text of ['```python','text `inline` text','```python\nprint(1)']) {
    const editor = create();
    await paste(editor,text);
    assert.equal(editor.getJSON().content[0].type,'paragraph');
    assert.equal(editor.state.doc.textContent,text);
    editor.destroy();
  }
});
test('language input updates block attrs without serializing controls', () => {
  const editor = create();
  editor.commands.toggleCodeBlock();
  const input = editor.view.dom.querySelector('.wiki-code-language input');
  assert.ok(input);
  input.value = 'custom-lang';
  input.dispatchEvent(new window.Event('change',{bubbles:true}));
  assert.equal(editor.getJSON().content[0].attrs.language,'custom-lang');
  assert.match(editor.getMarkdown(),/^```custom-lang\n/);
  assert.doesNotMatch(editor.getMarkdown(),/Code language|datalist|input/);
  const roundtrip = create(editor.getMarkdown());
  assert.equal(roundtrip.getJSON().content[0].attrs.language,'custom-lang');
  roundtrip.destroy();
  input.value = '';
  input.dispatchEvent(new window.Event('change',{bubbles:true}));
  assert.equal(editor.getJSON().content[0].attrs.language,null);
  editor.destroy();
});
test('typed indented fence supports nonalphabetic language tokens', () => {
  const editor = create();
  type(editor,'  ```c++ ');
  assert.equal(editor.getJSON().content[0].attrs.language,'c++');
  editor.destroy();
});
test('existing literal inline fences remain unchanged on load', () => {
  const editor = create('` ```python `\n\n`print("Hello")`\n\n` ``` `');
  assert.equal(editor.getJSON().content[0].type,'paragraph');
  assert.equal(editor.getJSON().content[0].content[0].marks[0].type,'code');
  editor.destroy();
});
test('single backtick typing still creates inline code', () => {
  const editor = create();
  type(editor,'`word`');
  assert.equal(editor.getJSON().content[0].content[0].marks[0].type,'code');
  editor.destroy();
});
test('multiple fenced blocks with intervening content paste literally', async () => {
  const editor = create();
  const text = '```python\nx\n```\n\nordinary **text** <b>HTML</b>\n\n```js\ny\n```';
  await paste(editor,text);
  assert.equal(editor.getJSON().content[0].type,'paragraph');
  assert.equal(editor.state.doc.textContent,text);
  editor.destroy();
});
for (const text of ['```python\n```','```python\nx\n````','~~~python\nx\n~~~~']) test(`complete fenced block accepts ${JSON.stringify(text)}`, async () => {
  const editor = create();
  await paste(editor,text);
  assert.equal(editor.getJSON().content[0].type,'codeBlock');
  assert.equal(editor.getJSON().content[0].attrs.language,'python');
  editor.destroy();
});
test('language rejects control characters and oversized tokens', () => {
  const editor = create('```python\nx\n```');
  const input = editor.view.dom.querySelector('.wiki-code-language input');
  for (const value of ['bad language','x'.repeat(65),'<script>']) {
    input.value=value;
    input.dispatchEvent(new window.Event('change',{bubbles:true}));
    assert.equal(editor.getJSON().content[0].attrs.language,'python');
    assert.equal(input.value,'python');
  }
  editor.destroy();
});
