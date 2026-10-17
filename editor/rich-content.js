import { registerPlugin } from './plugins.js';

let basePath = '/';
let diagramLibrary;
let mathLibrary;
let diagramId = 0;
export function configureRichContent(options = {}) {
  basePath = '/' + (options.basePath || '').replace(/^\/+|\/+$/g, '');
  if (!basePath.endsWith('/')) basePath += '/';
}
function libraries(name) { return basePath + 'hugo-content/lib/' + name; }
function mathView(dom, attributes) {
  dom.textContent = attributes.source;
  if (typeof window === 'undefined') return;
  if (!mathLibrary) mathLibrary = (async () => {
    if (!window.MathJax?.startup?.promise) {
      window.MathJax = {tex: {displayMath: [['$$', '$$'], ['\\[', '\\]']], inlineMath: [['$', '$'], ['\\(', '\\)']]}, loader: {paths: {mathjax: libraries('mathjax')}, load: ['ui/safe']}, svg: {fontCache: 'local'}, options: {enableMenu: false}, startup: {typeset: false}};
      await new Promise((resolve, reject) => {
        const script = document.createElement('script');
        script.src = libraries('mathjax/tex-svg.js');
        script.onload = resolve; script.onerror = reject;
        document.head.append(script);
      });
    }
    await window.MathJax.startup.promise;
    return window.MathJax;
  })();
  mathLibrary.then(library => { if (dom.isConnected && !dom.querySelector('textarea')) return library.typesetPromise([dom]); }).catch(() => {});
}
function diagramView(dom, attributes) {
  const source = attributes.source.replace(/^(?:`{3,}|~{3,})mermaid[^\n]*\n/, '').replace(/\n(?:`{3,}|~{3,})$/, '');
  dom.textContent = source;
  if (!diagramLibrary) diagramLibrary = import(libraries('mermaid.js')).then(({default: library}) => {
    library.initialize({startOnLoad: false, securityLevel: 'strict'});
    return library;
  });
  diagramLibrary.then(library => library.render('wiki-diagram-' + (++diagramId), source)).then(({svg}) => {
    if (dom.isConnected && !dom.querySelector('textarea')) dom.innerHTML = svg;
  }).catch(() => {});
}
function alertView(dom, attributes) {
  const type = attributes.source.match(/^>\s*\[!([^\]]+)\]/)?.[1].toLowerCase() || 'note';
  dom.classList.add('markdown-alert', 'markdown-alert--' + type);
  const title = document.createElement('strong');
  title.textContent = attributes.source.match(/^>\s*\[!([^\]]+)\]/)?.[1] || 'Note';
  const body = document.createElement('div');
  body.textContent = attributes.source.replace(/^>[^\n]*\n?/, '').replace(/^>\s?/gm, '');
  dom.append(title, body);
}
export function insertRichContent(editor, kind) {
  const snippets = {math: {type: 'wikiDisplayMath', attrs: {source: '$$\nx^2\n$$'}}, mermaid: {type: 'wikiMermaid', attrs: {source: '```mermaid\ngraph TD; A-->B\n```'}}, alert: {type: 'wikiAlert', attrs: {source: '> [!NOTE]\n> Note'}}, footnote: {type: 'wikiFootnote', attrs: {source: '[^note]'}}};
  if (kind === 'task') return editor.chain().focus().toggleTaskList().run();
  if (!snippets[kind]) return false;
  const content = kind === 'footnote' ? snippets[kind] : [snippets[kind], {type: 'paragraph'}];
  return editor.chain().focus().insertContent(content).run();
}

function sourcePlugin(name, label, level, pattern, start, editable = true, view) {
  registerPlugin({
    apiVersion: 1, name, label, level, start, editable, view,
    parse(source) { const match = source.match(pattern); return match ? {raw: match[0]} : undefined; },
    serialize(attributes) { return attributes.source; },
    validate() { return true; },
  });
}

sourcePlugin('wikiMermaid', 'Mermaid', 'block', /^(`{3,}|~{3,})mermaid[^\n]*\n[\s\S]*?\n\1(?=\n|$)/, source => source.search(/(?:^|\n)(?:`{3,}|~{3,})mermaid/), true, diagramView);
sourcePlugin('wikiDisplayMath', 'Formula', 'block', /^(?:\$\$[\s\S]*?\$\$|\\\[[\s\S]*?\\\])(?=\n|$)/, source => source.search(/\$\$|\\\[/), true, mathView);
sourcePlugin('wikiInlineMath', 'Formula', 'inline', /^(?:\$(?!\$)[^\n$]+\$|\\\([^\n]*?\\\))/, source => source.search(/\$|\\\(/), true, mathView);
sourcePlugin('wikiAlert', 'Callout', 'block', /^>\s*\[![A-Za-z]+\][^\n]*(?:\n>[^\n]*)*/, source => source.search(/^>\s*\[!/m), true, alertView);
sourcePlugin('wikiFootnoteDefinition', 'Footnote', 'block', /^\[\^[^\]\n]+\]:[^\n]*(?:\n(?:[ \t]{2,}[^\n]*|(?=\n[ \t]{2,})))*/, source => source.search(/^\[\^.+\]:/m));
sourcePlugin('wikiFootnote', 'Footnote', 'inline', /^\[\^[^\]\n]+\]/, '[^');
sourcePlugin('wikiShortcode', 'Hugo component', 'inline', /^\{\{([<%])\s*([A-Za-z][\w-]*)\b[\s\S]*?[>%]\}\}(?:[\s\S]*?\{\{[<%]\s*\/\2\s*[>%]\}\})?/, '{{', false);
sourcePlugin('wikiProtectedHTML', 'HTML (protected)', 'inline', /^(?:<!--[^]*?-->|<([A-Za-z][\w:-]*)\b[^>]*>[\s\S]*?<\/\1\s*>|<\/?[A-Za-z][^>]*>)/, '<', false);
sourcePlugin('wikiProtectedBlockHTML', 'HTML (protected)', 'block', /^(?:<!--[^]*?-->|<([A-Za-z][\w:-]*)\b[^>]*>[\s\S]*?<\/\1\s*>|<\/?[A-Za-z][^>]*>)(?=\s*(?:\n|$))/, source => source.search(/^</m), false);
