import StarterKit from '@tiptap/starter-kit';
import { TableKit } from '@tiptap/extension-table';
import Image from '@tiptap/extension-image';
import TaskList from '@tiptap/extension-task-list';
import TaskItem from '@tiptap/extension-task-item';
import { Markdown } from '@tiptap/markdown';
import { pluginExtensions } from './plugins.js';
import './rich-content.js';

const MediaImage = Image.extend({
  addNodeView() {
    return ({node}) => {
      const video = /\.(mp4|webm)(?:[?#]|$)/i.test(node.attrs.src || '');
      const audio = /\.(mp3|ogg|wav)(?:[?#]|$)/i.test(node.attrs.src || '');
      const dom = document.createElement(video ? 'video' : audio ? 'audio' : 'img');
      const source = node.attrs.src || '';
      if (!/^\s*(?:javascript|data|vbscript):/i.test(source)) dom.src = source;
      if (video || audio) dom.controls = true;
      else dom.alt = (node.attrs.alt || '').split('|')[0];
      const width = (node.attrs.alt || '').match(/\|(\d+)$/)?.[1];
      if (width) dom.style.maxWidth = Number(width) <= 100 ? width + '%' : width + 'px';
      if (node.attrs.title) dom.title = node.attrs.title;
      return {dom};
    };
  },
});

export const extensions = () => [StarterKit.configure({link: {openOnClick: false, autolink: false}}), TableKit.configure({table: {resizable: false}}), MediaImage.configure({inline: true, allowBase64: false}), TaskList, TaskItem.configure({nested: true}), ...pluginExtensions(), Markdown];

export function prepareMarkdown(source) {
  const refs = new Map();
  const prepared = source.replace(/\]\((\{\{<\s*relref\s+"([^"]+)"\s*>\}\})\)/g, (_, original, target) => {
    const href = '/__wiki_relref__/' + refs.size;
    refs.set(href, {original, target});
    return '](' + href + ')';
  });
  return {prepared, refs};
}

export function restoreMarkdown(markdown, refs) {
  for (const [href, ref] of refs) markdown = markdown.split('](' + href + ')').join('](' + ref.original + ')');
  return markdown;
}

export function sourceBody(original, initialDocument, currentDocument, generated, refs) {
  return JSON.stringify(initialDocument) === JSON.stringify(currentDocument) ? original : restoreMarkdown(generated, refs);
}
