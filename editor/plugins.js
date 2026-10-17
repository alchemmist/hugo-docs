import { Node } from '@tiptap/core';

export const PLUGIN_API_VERSION = 1;
const registry = new Map();

export function registerPlugin(plugin) {
  if (plugin.apiVersion !== PLUGIN_API_VERSION) throw new Error('Unsupported wiki plugin API version');
  if (!/^[a-z][a-z0-9_]*$/i.test(plugin.name) || registry.has(plugin.name)) throw new Error('Invalid or duplicate wiki plugin name');
  for (const name of ['parse', 'serialize', 'validate']) if (typeof plugin[name] !== 'function') throw new Error(`Plugin requires ${name}`);
  if (!['inline', 'block'].includes(plugin.level)) throw new Error('Plugin requires inline or block level');
  registry.set(plugin.name, Object.freeze({...plugin}));
  return () => registry.delete(plugin.name);
}

export function pluginExtensions() {
  return [...registry.values()].map(plugin => Node.create({
    name: plugin.name,
    group: plugin.level,
    inline: plugin.level === 'inline',
    atom: true,
    addAttributes() { return {source: {default: ''}, parameters: {default: {}}}; },
    parseHTML() { return [{tag: `[data-wiki-node="${plugin.name}"]`}]; },
    renderHTML({node}) { return [plugin.level === 'inline' ? 'span' : 'div', {'data-wiki-node': plugin.name, class: 'wiki-rich-node'}, plugin.label || plugin.name, ['code', {}, node.attrs.source]]; },
    addNodeView() {
      return ({node, getPos, editor}) => {
        const dom = document.createElement(plugin.level === 'inline' ? 'span' : 'div');
        dom.className = 'wiki-rich-node';
        dom.dataset.wikiNode = plugin.name;
        dom.contentEditable = 'false';
        if (plugin.view) plugin.view(dom, node.attrs);
        else {
          const label = document.createElement('strong');
          label.textContent = plugin.label || plugin.name;
          const source = document.createElement('code');
          source.textContent = node.attrs.source;
          dom.append(label, source);
        }
        if (plugin.editable) dom.addEventListener('dblclick', () => {
          if (!editor.isEditable || dom.querySelector('textarea')) return;
          const input = document.createElement('textarea');
          input.value = node.attrs.source;
          dom.replaceChildren(input);
          input.focus();
          input.addEventListener('blur', () => {
            const parsed = plugin.parse(input.value);
            if (!parsed || parsed.raw !== input.value || !plugin.validate(parsed.parameters || {})) { input.setCustomValidity('Invalid content'); input.reportValidity(); return; }
            editor.commands.command(({tr}) => {
              const pos = getPos();
              if (typeof pos !== 'number') return false;
              tr.setNodeMarkup(pos, undefined, {source: input.value, parameters: parsed.parameters || {}});
              return true;
            });
          });
        });
        return {dom, stopEvent: event => event.target.tagName === 'TEXTAREA'};
      };
    },
    addCommands() { return plugin.commands || {}; },
    markdownTokenName: plugin.name,
    parseMarkdown(token) {
      if (!plugin.validate(token.parameters || {})) throw new Error(`Invalid ${plugin.name} parameters`);
      return {type: plugin.name, attrs: {source: token.raw, parameters: token.parameters || {}}};
    },
    renderMarkdown(node) {
      if (!plugin.validate(node.attrs.parameters || {})) throw new Error(`Invalid ${plugin.name} parameters`);
      return plugin.serialize(node.attrs);
    },
    markdownTokenizer: {
      name: plugin.name,
      level: plugin.level,
      start: plugin.start,
      tokenize(source) {
        const result = plugin.parse(source);
        return result && result.raw ? {...result, type: plugin.name} : undefined;
      },
    },
  }));
}
