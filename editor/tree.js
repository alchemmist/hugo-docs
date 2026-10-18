import {t} from './i18n.js';

export async function initializeTree({api, workspace, begin = () => true, dirty, structureDirty = dirty, openPage, currentPath, moved, renamed = async () => {}, removed = async () => {}, changed = async () => {}, message, publication}) {
  const nav = document.querySelector('.page-tree');
  if (!nav) return;
  const pendingLinks = new Map();
  let confirmation, renaming, renameSaving;
  const clearConfirmation = () => { if (confirmation) { confirmation.reset(); confirmation = null; } };
  let tree, loading, treeGeneration = 0, pending = false, dragging = '', expanded = new Set(), chooser, pointer, drop, expandTimer, expandId, scrollFrame;
  const state = nav.ownerDocument.defaultView?.WikiTreeState;
  const normalize = id => state?.normalize(id) ?? String(id).replace(/^\/+|\/+$/g, '');
  const remembered = new Map();
  function rememberExpansion(id, value) {
    id = normalize(id);
    remembered.set(id, value);
    state?.set(id, value);
    value ? expanded.add(id) : expanded.delete(id);
    for (const toggle of nav.querySelectorAll('.tree-toggle[data-section]')) {
      if (normalize(toggle.dataset.section) === id) toggle.setAttribute('aria-expanded', String(value));
    }
  }
  function captureExpansion() {
    for (const toggle of nav.querySelectorAll('.tree-toggle[data-section]')) {
      const id = normalize(toggle.dataset.section);
      const value = state?.get(id, toggle.getAttribute('aria-expanded') === 'true') ?? (toggle.getAttribute('aria-expanded') === 'true');
      remembered.set(id, value);
      if (value) state?.set(id, true);
    }
    expanded = new Set();
    for (const node of flatten(tree.nodes)) {
      if (node.kind !== 'folder') continue;
      const fallback = remembered.has(normalize(node.id)) ? remembered.get(normalize(node.id)) : currentPath().startsWith(node.id + '/');
      const value = state?.get(node.id, fallback) ?? fallback;
      remembered.set(normalize(node.id), value);
      if (value) state?.set(node.id, true);
      if (value) expanded.add(node.id);
    }
  }
  const error = text => message(text, true);
  const button = (text, label, action) => {
    const el = document.createElement('button'); el.type = 'button'; el.textContent = text; el.setAttribute('aria-label', label); el.title = label; el.addEventListener('click', action); return el;
  };
  const flatten = nodes => nodes.flatMap(node => [node, ...flatten(node.children || [])]);
  const parentOf = id => id.includes('/') ? id.slice(0, id.lastIndexOf('/')) : '';
  const canDrag = () => !workspace || workspace.active();
  const guard = (structure = true) => {
    if (pending) return false;
    if (dirty() || !workspace && structure && structureDirty()) { error(t("Publish or discard wiki changes before changing its structure.")); return false; }
    message(''); return true;
  };
  function loadTree() {
    if (!loading) {
      const generation = treeGeneration;
      loading = api('/tree').then(value => { if (generation === treeGeneration) { if (workspace) { workspace.seedTree(value); tree = workspace.tree(); } else tree = value; } return tree; }).finally(() => { loading = null; });
    }
    return loading;
  }
  async function ensureRevision() {
    if (!tree) await loadTree();
    return tree.revision;
  }
  function watchPublication(commit) {
    const snapshot = new Map(pendingLinks);
    publication(commit).then(published => {
      if (!published) return;
      for (const [id, url] of snapshot) if (pendingLinks.get(id) === url) pendingLinks.delete(id);
      render();
    });
  }
  const refresh = async ({pendingPage, commit} = {}) => {
    if (pendingPage) pendingLinks.set(pendingPage, null);
    await loadTree(); render();
    if (commit) watchPublication(commit);
  };
  async function mutate(endpoint, payload) {
    if (!guard()) return;
    pending = true; nav.setAttribute('aria-busy', 'true');
    try {
      if (loading) await loading;
      const revision = await ensureRevision();
      let result;
      if (workspace) {
        if (!begin()) return;
        workspace.stage({type:endpoint === "/move" ? "move" : endpoint === "/delete" ? "delete" : endpoint === "/rename" ? "rename" : "folder",...payload});
        result = workspace.tree();
      } else result = await api(endpoint, {...payload, revision});
      const oldNodes = flatten(tree.nodes);
      if (endpoint === '/move') {
        const target = payload.target_parent ? payload.target_parent + '/' + payload.source.split('/').pop() : payload.source.split('/').pop();
        captureExpansion();
        for (const node of oldNodes.filter(n => n.kind === 'folder' && (n.id === payload.source || n.id.startsWith(payload.source + '/')))) {
          rememberExpansion(target + node.id.slice(payload.source.length), expanded.has(node.id));
        }
        for (const node of oldNodes.filter(n => n.kind === 'page' && (n.id === payload.source || n.id.startsWith(payload.source + '/')))) pendingLinks.set(target + node.id.slice(payload.source.length), pendingLinks.has(node.id) ? pendingLinks.get(node.id) : node.url);
      }
      treeGeneration++; tree = result; chooser?.remove(); render(); if (!workspace) watchPublication(result.commit);
      return result;
    } catch (e) {
      if (e.status === 409 && !workspace) { await refresh(); error(t("The structure changed. The list was refreshed; try again.")); }
      else error(e.message);
    } finally { pending = false; nav.removeAttribute('aria-busy'); }
  }
  async function move(source, target_parent, before = null) {
    if (source === target_parent || target_parent.startsWith(source + '/') || source === before) return;
    const result = await mutate('/move', {source, target_parent, before});
    if (result) { moved(source, target_parent ? target_parent + '/' + source.split('/').pop() : source.split('/').pop()); render(); await changed(); }
  }
  async function removeNode(node) {
    if (!workspace?.active()) return;
    clearConfirmation();
    const result = await mutate('/delete', {source:node.id});
    if (result) { await removed(node); await changed(); }
  }
  function renameFolder(node, row) {
    if (!workspace?.active() || pending || dirty()) return;
    clearConfirmation(); renaming?.cancel();
    const toggle = row.querySelector('.tree-toggle');
    const input = document.createElement('input');
    input.className = 'wiki-tree-rename-input'; input.value = node.title; input.maxLength = 200;
    input.setAttribute('aria-label', t("Folder name: ") + node.title);
    const cancel = () => { if (renaming?.input !== input) return; renaming = null; input.replaceWith(toggle); };
    const save = () => {
      if (renaming?.input !== input) return renameSaving || Promise.resolve(true);
      if (!workspace.active()) { cancel(); return Promise.resolve(true); }
      const title = input.value.trim();
      if (!title || title.length > 200 || /[\r\n]/.test(input.value)) { error(t("Enter a folder name with 1–200 characters and no line breaks.")); input.focus(); return Promise.resolve(false); }
      if (title === node.title) { cancel(); return Promise.resolve(true); }
      cancel();
      renameSaving = (async () => {
        const result = await mutate('/rename', {source:node.id,title});
        if (result) { await renamed(node.id,title); await changed(); }
        return !!result;
      })().finally(() => { renameSaving = null; });
      return renameSaving;
    };
    renaming = {input,cancel,save};
    toggle.replaceWith(input); input.focus(); input.select();
    input.addEventListener('pointerdown', event => event.stopPropagation());
    input.addEventListener('click', event => event.stopPropagation());
    input.addEventListener('keydown', event => {
      if (event.key === 'Escape') { event.preventDefault(); event.stopPropagation(); cancel(); row.querySelector('.wiki-tree-rename')?.focus(); }
      else if (event.key === 'Enter') { event.preventDefault(); event.stopPropagation(); save(); }
    });
    input.addEventListener('blur', save);
  }
  function createFolder(anchor) {
    if (!guard()) return;
    chooser?.remove(); chooser = document.createElement('div'); chooser.className = 'wiki-tree-create';
    const title = document.createElement('input'); title.placeholder = t("Folder name"); title.setAttribute('aria-label',t("New folder name")); title.maxLength = 200;
    const slug = document.createElement('input'); slug.placeholder = 'folder-address'; slug.setAttribute('aria-label',t("New folder address"));
    const submit = button(t("Create"),t("Create folder"), async () => {
      if (!title.value.trim() || !/^[a-z0-9]+(-[a-z0-9]+)*$/.test(slug.value)) { error(t("Enter a name and address using Latin letters, numbers and hyphens.")); return; }
      const result = await mutate('/folders',{parent:'',title:title.value.trim(),slug:slug.value});
      if (result) await changed();
    });
    chooser.append(title,slug,submit,button('×',t("Cancel creation"),()=>chooser.remove())); anchor.after(chooser); title.focus();
  }
  function iconButton(label, paths, action) {
    const el = button('', label, action);
    const svg = document.createElementNS('http://www.w3.org/2000/svg','svg');
    for (const [key,value] of Object.entries({width:'18',height:'18',viewBox:'0 0 24 24',fill:'none',stroke:'currentColor','stroke-width':'1.5','stroke-linecap':'round','stroke-linejoin':'round','aria-hidden':'true'})) svg.setAttribute(key,value);
    for (const d of paths) { const path = document.createElementNS('http://www.w3.org/2000/svg','path'); path.setAttribute('d',d); svg.append(path); }
    el.append(svg); return el;
  }
  nav.addEventListener('scroll', clearConfirmation);
  document.defaultView?.addEventListener('resize', clearConfirmation);
  const dragHint = document.createElement('div');
  dragHint.className = 'wiki-tree-drag-hint'; dragHint.hidden = true; dragHint.setAttribute('role', 'status'); nav.append(dragHint);
  function clearDrop() {
    nav.querySelectorAll('[data-drop]').forEach(el => delete el.dataset.drop);
    drop = null; dragHint.hidden = true;
  }
  function finishDrag() {
    clearTimeout(expandTimer); expandId = ''; cancelAnimationFrame(scrollFrame);
    dragging = ''; pointer = null; nav.classList.remove('wiki-tree-dragging');
    nav.querySelectorAll('.wiki-tree-source').forEach(el => el.classList.remove('wiki-tree-source'));
    clearDrop();
  }
  function targetAt(row, node, siblings, event) {
    if (!dragging || dragging === node.id || node.id.startsWith(dragging + '/')) return;
    const rect = row.getBoundingClientRect(), offset = event.clientY - rect.top;
    const edge = Math.min(10, rect.height / 3);
    const where = node.kind === 'folder' && offset > edge && offset < rect.height - edge ? 'inside' : offset < rect.height / 2 ? 'before' : 'after';
    const remaining = siblings.filter(item => item.id !== dragging);
    return {row, node, where, parent: where === 'inside' ? node.id : parentOf(node.id), before: where === 'inside' ? null : where === 'before' ? node.id : remaining[remaining.indexOf(node) + 1]?.id || null};
  }
  function showDrop(target, event) {
    clearDrop();
    if (!target) { clearTimeout(expandTimer); expandId = ''; return; }
    drop = target;
    const marker = target.where === 'after' && target.node?.kind === 'folder' ? target.row.parentElement : target.row;
    marker.dataset.drop = target.where;
    dragHint.textContent = target.node ? `${target.where === 'inside' ? t("Into folder") : target.where === 'before' ? t("Before") : t("After")} «${target.node.title}»` : t("At root");
    dragHint.hidden = false; dragHint.style.left = `${event.clientX + 14}px`; dragHint.style.top = `${event.clientY + 16}px`;
    const nextExpand = target.where === 'inside' && target.node?.kind === 'folder' && !expanded.has(target.node.id) ? target.node.id : '';
    if (nextExpand !== expandId) {
      clearTimeout(expandTimer); expandId = nextExpand;
      if (nextExpand) expandTimer = setTimeout(() => {
        rememberExpansion(nextExpand, true);
        const children = target.row.parentElement.querySelector(':scope > ul');
        if (children) children.hidden = false;
        target.row.querySelector('[aria-expanded]')?.setAttribute('aria-expanded', 'true');
      }, 650);
    }
  }
  function executeDrop() {
    const source = dragging, target = drop;
    finishDrag();
    if (canDrag() && source && target) {
      if (target.where === 'inside' && target.node) rememberExpansion(target.node.id, true);
      move(source, target.parent, target.before);
    }
  }
  function dropTarget(row, node, siblings) {
    row.wikiDropTarget = event => targetAt(row, node, siblings, event);
    row.addEventListener('dragover', event => {
      const target = row.wikiDropTarget(event);
      if (!target) return;
      event.preventDefault(); event.stopPropagation(); showDrop(target, event);
    });
    row.addEventListener('drop', event => {
      event.preventDefault(); event.stopPropagation(); showDrop(row.wikiDropTarget(event), event); executeDrop();
    });
  }
  function updatePointer(event) {
    const hit = document.elementFromPoint(event.clientX, event.clientY);
    const row = hit?.closest('.wiki-tree-row');
    const root = hit?.closest('.wiki-tree-root');
    showDrop(row && nav.contains(row) ? row.wikiDropTarget(event) : root && nav.contains(root) ? {row: root, where: 'inside', parent: '', before: null} : null, event);
  }
  function scrollDuringDrag() {
    if (!pointer || !dragging) return;
    const container = nav, bounds = container.getBoundingClientRect();
    const speed = pointer.y < bounds.top + 40 ? -10 : pointer.y > bounds.bottom - 40 ? 10 : 0;
    if (speed) { container.scrollTop += speed; updatePointer({clientX: pointer.x, clientY: pointer.y}); }
    scrollFrame = requestAnimationFrame(scrollDuringDrag);
  }
  nav.addEventListener('pointermove', event => {
    if (!pointer || event.pointerId !== pointer.id) return;
    if (!canDrag()) { finishDrag(); return; }
    pointer.x = event.clientX; pointer.y = event.clientY;
    if (!dragging) {
      if (Math.hypot(event.clientX - pointer.startX, event.clientY - pointer.startY) < 5) return;
      if (!guard()) { finishDrag(); return; }
      dragging = pointer.node.id; nav.classList.add('wiki-tree-dragging'); pointer.row.classList.add('wiki-tree-source');
      nav.setPointerCapture?.(event.pointerId); scrollFrame = requestAnimationFrame(scrollDuringDrag);
    }
    event.preventDefault(); updatePointer(event);
  });
  nav.addEventListener('pointerup', event => {
    if (!pointer || event.pointerId !== pointer.id) return;
    if (dragging) {
      event.preventDefault();
      const suppress = event => { event.preventDefault(); event.stopPropagation(); };
      nav.addEventListener('click', suppress, {capture: true, once: true});
      setTimeout(() => nav.removeEventListener('click', suppress, true), 0);
      executeDrop();
    } else pointer = null;
  });
  nav.addEventListener('pointercancel', event => { if (pointer?.id === event.pointerId) finishDrag(); });
  nav.addEventListener('lostpointercapture', () => { if (pointer) finishDrag(); });
  document.addEventListener('keydown', event => { if (event.key === 'Escape') { clearConfirmation(); if (pointer) finishDrag(); } });
  function list(nodes, depth=0) {
    const ul=document.createElement('ul');ul.className='nav-level'+(!depth?' nav-root':'');
    for(const node of nodes) {
      const li=document.createElement('li');li.className='nav-item'+(node.kind==='folder'?' nav-section':'');li.dataset.nodeId=node.id;
      const row=document.createElement('div');row.className='nav-row wiki-tree-row';row.draggable=false;
      row.addEventListener('pointerdown', event => {
        if (event.target.closest('.wiki-tree-delete, .wiki-tree-rename, .wiki-tree-rename-input') || event.button !== 0 || pending || !canDrag()) return;
        pointer = {id: event.pointerId, node, row, startX: event.clientX, startY: event.clientY, x: event.clientX, y: event.clientY};
      });
      row.addEventListener('dragstart',event=>{if(event.target.closest('.wiki-tree-delete, .wiki-tree-rename, .wiki-tree-rename-input') || !canDrag() || !guard()){event.preventDefault();return;} dragging=node.id;nav.classList.add('wiki-tree-dragging');event.dataTransfer.setData('text/plain',node.id);event.dataTransfer.effectAllowed='move';});
      row.addEventListener('dragend',finishDrag);
      if(node.kind==='folder') {
        const toggle=button('', t("Expand ")+node.title,()=>{rememberExpansion(node.id, !expanded.has(node.id));render();});
        toggle.dataset.section=node.id; toggle.dataset.title=node.title; toggle.className='tree-toggle wiki-tree-folder'; toggle.setAttribute('aria-expanded',String(expanded.has(node.id)));
        const svg=document.createElementNS('http://www.w3.org/2000/svg','svg');
        for(const [key,value] of Object.entries({class:'icon',width:'20',height:'20',viewBox:'0 0 24 24',fill:'none',stroke:'currentColor','stroke-width':'1.5','stroke-linecap':'round','stroke-linejoin':'round','aria-hidden':'true'}))svg.setAttribute(key,value);
        const chevron=document.createElementNS('http://www.w3.org/2000/svg','path');chevron.setAttribute('d','m9 5 7 7-7 7');svg.append(chevron);
        const label=document.createElement('span');label.textContent=node.title;toggle.append(svg,label);row.append(toggle);
      } else {
        const link=document.createElement('a');link.draggable=false;link.href=node.origin_url || pendingLinks.get(node.id) || node.url;link.textContent=node.title;
        if((node.page_path || node.id)===currentPath())link.setAttribute('aria-current','page');
        if(pendingLinks.has(node.id) && !pendingLinks.get(node.id)) {link.removeAttribute('href');link.setAttribute('aria-disabled','true');link.title=t("Awaiting publication");}
        link.addEventListener('click',event=>{if(node.draft_path){event.preventDefault();openPage({draftPath:node.draft_path});return;}if(!link.hasAttribute('href')){event.preventDefault();return;}if(dirty()){event.preventDefault();error(t("Publish or discard page changes first."));}});row.append(link);
      }
      if (workspace?.active()) {
        if (node.kind === 'folder') {
          const rename = iconButton(t("Rename folder ") + node.title, ['M16 3a2.1 2.1 0 0 1 3 3L8 17l-4 1 1-4Z','m14 5 3 3'], event => {
            event.preventDefault(); event.stopPropagation(); renameFolder(node, row);
          });
          rename.className = 'wiki-tree-rename'; rename.draggable = false;
          rename.addEventListener('pointerdown', event => event.stopPropagation());
          rename.addEventListener('dragstart', event => { event.preventDefault(); event.stopPropagation(); });
          row.append(rename);
        }
        const trash = ['M3 6h18','M9 6V4h6v2','M5 6l1 14h12l1-14','M10 10v6','M14 10v6'];
        const warning = ['M12 4 2 21h20L12 4Z','M12 10v4','M12 17h.01'];
        const label = t("Delete ") + (node.kind === 'folder' ? t("folder ") : t("page ")) + node.title;
        const remove = iconButton(label, trash, async event => {
          event.preventDefault(); event.stopPropagation();
          if (pending || !workspace.active()) return;
          if (node.kind !== 'folder' || confirmation?.node === node.id) { await removeNode(node); return; }
          clearConfirmation();
          const tooltip = document.createElement('span'); tooltip.className = 'wiki-tree-delete-tooltip'; tooltip.id = 'wiki-delete-confirmation'; tooltip.setAttribute('role','tooltip');
          tooltip.textContent = t("The folder and all pages inside will be deleted. Click again to confirm.");
          remove.replaceChildren(iconButton('', warning, () => {}).firstChild);
          remove.classList.add('is-confirming'); remove.setAttribute('aria-label',t("Confirm deletion of folder ") + node.title); remove.setAttribute('aria-describedby',tooltip.id); remove.title = ''; document.body.append(tooltip);
          const bounds = remove.getBoundingClientRect(), width = Math.min(250, document.defaultView.innerWidth - 24);
          tooltip.style.width = width + 'px';
          tooltip.style.left = Math.max(12, Math.min(bounds.right - width, document.defaultView.innerWidth - width - 12)) + 'px';
          tooltip.style.top = Math.max(12, Math.min(bounds.bottom + 6, document.defaultView.innerHeight - tooltip.getBoundingClientRect().height - 12)) + 'px';
          confirmation = {node:node.id, reset:()=>{tooltip.remove();remove.replaceChildren(iconButton('',trash,()=>{}).firstChild);remove.classList.remove('is-confirming');remove.setAttribute('aria-label',label);remove.removeAttribute('aria-describedby');remove.title=label;}};
        });
        remove.className = 'wiki-tree-delete'; remove.draggable = false;
        remove.addEventListener('pointerdown',event=>event.stopPropagation());
        remove.addEventListener('dragstart',event=>{event.preventDefault();event.stopPropagation();});
        row.addEventListener('pointerleave',()=>{if(confirmation?.node===node.id)clearConfirmation();});
        row.addEventListener('focusout',event=>{if(!row.contains(event.relatedTarget) && confirmation?.node===node.id)clearConfirmation();});
        row.addEventListener('pointerenter',()=>{if(confirmation && confirmation.node!==node.id)clearConfirmation();});
        row.append(remove);
      }
      li.append(row);dropTarget(row,node,nodes);
      if(node.children?.length){const children=list(node.children,depth+1);children.hidden=!expanded.has(node.id);li.append(children);}ul.append(li);
    }return ul;
  }
  function render() {
    renaming?.cancel();
    clearConfirmation();
    if (!tree) return;
    captureExpansion();
    const scrollTop = nav.scrollTop;
    const focused = nav.ownerDocument.activeElement;
    const focusId = focused?.matches('.tree-toggle[data-section]') ? normalize(focused.dataset.section) : null;
    const root = nav.querySelector('.nav-root');
    const replacement = list(tree.nodes);
    if (root) root.replaceWith(replacement); else nav.append(replacement);
    if (focusId !== null) {
      for (const toggle of replacement.querySelectorAll('.tree-toggle[data-section]')) {
        if (normalize(toggle.dataset.section) === focusId) toggle.focus({preventScroll:true});
      }
    }
    nav.scrollTop = scrollTop;
  }
  function mountToolbar() {
    const root=document.createElement('div');root.className='wiki-tree-root';
    root.append(
      iconButton(t("New page"),['M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8Z','M14 2v6h6','M12 12v6','M9 15h6'],async()=>{if(guard(false)){chooser?.remove();await openPage({parent:'',title:t("New page"),slug:''});}}),
      iconButton(t("New folder"),['M20 20H4a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h5l2 2h9a2 2 0 0 1 2 2v10a2 2 0 0 1-2 2Z','M12 10v6','M9 13h6'],()=>createFolder(root))
    );
    root.addEventListener('dragover',event=>{if(dragging){event.preventDefault();clearDrop();root.dataset.drop='inside';}});
    root.addEventListener('drop',event=>{event.preventDefault();showDrop({row:root,where:'inside',parent:'',before:null},event);executeDrop();});nav.prepend(root);
  }
  mountToolbar();
  const ready = loadTree().then(() => { render(); }).catch(e => error(e.message));
  return {refresh, finishRename:async()=>renaming ? renaming.save() : renameSaving || true, render:()=>{ if (workspace) tree = workspace.tree() || tree; render(); }, reset:()=>{finishDrag();tree=undefined;return refresh();}, revision:()=>tree?.revision, ensureRevision, ready};
}
