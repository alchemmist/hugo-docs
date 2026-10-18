const paths = {
  paragraph: 'M13 5H9a4 4 0 0 0 0 8h4M13 5v15M18 5v15M9 5h11',
  heading2: 'M3 6v12M11 6v12M3 12h8M16 11c0-3 5-3 5 0 0 2-5 4-5 7h5',
  heading3: 'M3 6v12M11 6v12M3 12h8M16 9h5l-3 4c4 0 4 6-2 5',
  bold: 'M7 4h6a4 4 0 0 1 0 8H7zm0 8h7a4 4 0 0 1 0 8H7z',
  italic: 'M10 4h9M5 20h9M15 4 9 20',
  bullet: 'M9 6h12M9 12h12M9 18h12M3 6h.01M3 12h.01M3 18h.01',
  ordered: 'M10 6h11M10 12h11M10 18h11M3 4h1v5M3 9h3M2 14c0-3 4-3 4 0 0 2-4 3-4 5h4',
  task: 'M10 6h11M10 12h11M10 18h11M2 6l2 2 3-4M2 12l2 2 3-4M2 18l2 2 3-4',
  link: 'M10 13a5 5 0 0 0 7 0l3-3a5 5 0 0 0-7-7l-2 2M14 11a5 5 0 0 0-7 0l-3 3a5 5 0 0 0 7 7l2-2',
  code: 'M8 6l-6 6 6 6M16 6l6 6-6 6M14 4l-4 16',
  table: 'M3 4h18v16H3zM3 9h18M3 14h18M9 4v16M15 4v16',
  media: 'M3 3h18v18H3zM3 17l6-6 4 4 3-3 5 5M15 7h.01',
  math: 'M19 4H6l7 8-7 8h13M19 4v3M19 17v3',
  diagram: 'M9 3h6v6H9zM2 16h6v5H2zM16 16h6v5h-6zM12 9v4M5 16v-3h14v3',
  note: 'M3 4h18v13l-5 4H3zM16 21v-4h5M7 8h10M7 12h7',
  footnote: 'M4 8h9M8.5 8v12M16 5l2-1v7M16 11h5'
};

export function createFormatToolbar({document, editor, groups, label, isBusy = () => false}) {
  const element = document.createElement('div');
  element.className = 'wiki-formatbar';
  element.setAttribute('role', 'toolbar');
  element.setAttribute('aria-label', label);
  const buttons = new Map();
  const descriptors = [];
  for (const group of groups) {
    const container = document.createElement('div');
    container.className = 'wiki-formatbar-group';
    container.setAttribute('role', 'group');
    container.setAttribute('aria-label', group.label);
    for (const action of group.actions) {
      const button = document.createElement('button');
      button.type = 'button';
      button.title = action.label;
      button.setAttribute('aria-label', action.label);
      button.dataset.format = action.id;
      button.tabIndex = buttons.size ? -1 : 0;
      const icon = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
      for (const [key, value] of Object.entries({viewBox:'0 0 24 24', width:'20', height:'20', fill:'none', stroke:'currentColor', 'stroke-width':'1.75', 'stroke-linecap':'round', 'stroke-linejoin':'round', 'aria-hidden':'true', focusable:'false'})) icon.setAttribute(key, value);
      const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
      path.setAttribute('d', paths[action.id]);
      icon.append(path);
      button.append(icon);
      button.addEventListener('mousedown', event => event.preventDefault());
      button.addEventListener('click', () => { if (!isBusy() && !button.disabled) action.run(); });
      button.addEventListener('focus', () => { for (const item of buttons.values()) item.tabIndex = item === button ? 0 : -1; });
      buttons.set(action.id, button);
      descriptors.push([action, button]);
      container.append(button);
    }
    element.append(container);
  }
  element.addEventListener('keydown', event => {
    if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
    const available = [...buttons.values()].filter(button => !button.disabled);
    const index = available.indexOf(document.activeElement);
    if (index < 0) return;
    event.preventDefault();
    const next = event.key === 'Home' ? 0 : event.key === 'End' ? available.length - 1 : (index + (event.key === 'ArrowRight' ? 1 : -1) + available.length) % available.length;
    available[next].focus();
  });
  const refresh = () => {
    for (const [action, button] of descriptors) {
      if (action.active) button.setAttribute('aria-pressed', String(action.active()));
    }
  };
  const destroy = () => {
    editor.off('selectionUpdate', refresh);
    editor.off('transaction', refresh);
    editor.off('destroy', destroy);
  };
  editor.on('selectionUpdate', refresh);
  editor.on('transaction', refresh);
  editor.on('destroy', destroy);
  refresh();
  return {element, buttons};
}
