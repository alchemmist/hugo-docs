import CodeBlock from '@tiptap/extension-code-block';
import {textblockTypeInputRule} from '@tiptap/core';
import {t} from './i18n.js';

const languages = ['python','javascript','typescript','bash','json','yaml','go','sql','html','css'];
let sequence = 0;

export const WikiCodeBlock = CodeBlock.extend({
  addInputRules() {
    return [textblockTypeInputRule({find:/^ {0,3}(?:```|~~~)([\w.+#-]+)?[\s\n]$/,type:this.type,getAttributes:match=>({language:match[1] || null})})];
  },
  addNodeView() {
    return ({node,editor,getPos}) => {
      const dom = document.createElement('div');
      dom.className = 'wiki-code-block';
      const controls = document.createElement('div');
      controls.className = 'wiki-code-language';
      controls.contentEditable = 'false';
      const label = document.createElement('label');
      label.textContent = t('Язык кода');
      const input = document.createElement('input');
      input.setAttribute('aria-label',t('Язык кода'));
      input.placeholder = t('Обычный текст');
      input.value = node.attrs.language || '';
      input.autocomplete = 'off';
      input.maxLength = 64;
      input.spellcheck = false;
      const list = document.createElement('datalist');
      list.id = `wiki-code-languages-${++sequence}`;
      input.setAttribute('list',list.id);
      for (const language of languages) {
        const option = document.createElement('option');
        option.value = language;
        list.append(option);
      }
      label.append(input);
      controls.append(label,list);
      const pre = document.createElement('pre');
      const contentDOM = document.createElement('code');
      pre.append(contentDOM);
      dom.append(controls,pre);
      input.addEventListener('change',()=>{
        const position = getPos();
        const language = input.value.trim();
        if (typeof position !== 'number' || (language && !/^[\w.+#-]{1,64}$/.test(language))) {
          input.value = node.attrs.language || '';
          return;
        }
        editor.view.dispatch(editor.state.tr.setNodeMarkup(position,undefined,{...node.attrs,language:language || null}));
      });
      return {
        dom,contentDOM,
        update(next) {
          if (next.type !== node.type) return false;
          node = next;
          input.value = node.attrs.language || '';
          return true;
        },
        stopEvent:event=>controls.contains(event.target),
        ignoreMutation:mutation=>controls.contains(mutation.target),
      };
    };
  },
});

export function pasteCodeText(editor, event) {
  const text = event.clipboardData?.getData('text/plain') || '';
  event.preventDefault();
  const lines = text.replace(/\r\n?/g,'\n').trimEnd().split('\n');
  const opening = /^ {0,3}(`{3,}|~{3,})[^`]*$/.exec(lines[0]);
  const closing = /^ {0,3}(`{3,}|~{3,})[ \t]*$/.exec(lines.at(-1));
  if (!editor.isActive('codeBlock') && lines.length > 1 && opening && closing && closing[1][0] === opening[1][0] && closing[1].length >= opening[1].length) {
    const parsed = editor.markdown.parse(text);
    if (parsed.content?.length === 1 && parsed.content[0].type === 'codeBlock') {
      editor.commands.insertContent(parsed.content[0]);
      return true;
    }
  }
  editor.view.dispatch(editor.state.tr.insertText(text));
  return true;
}
