import { registerPlugin } from './plugins.js';

export function installBadgePlugin() {
  return registerPlugin({
    apiVersion: 1,
    name: 'wikiBadge',
    label: 'Badge',
    level: 'inline',
    start: '{{< badge',
    editable: true,
    parse(source) {
      const match = source.match(/^\{\{< badge "([^"\n]+)" >\}\}/);
      return match ? {raw: match[0], parameters: {label: match[1]}} : undefined;
    },
    serialize(attributes) { return attributes.source; },
    validate(parameters) { return typeof parameters.label === 'string' && parameters.label.length <= 80; },
    view(element, attributes) {
      element.classList.add('wiki-badge');
      element.textContent = attributes.parameters.label;
    },
    commands: {
      insertBadge: label => ({commands}) => commands.insertContent({type: 'wikiBadge', attrs: {source: `{{< badge "${label}" >}}`, parameters: {label}}}),
    },
  });
}
