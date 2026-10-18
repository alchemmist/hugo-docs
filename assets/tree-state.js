(() => {
  const siteKey = document.currentScript?.dataset.siteKey || document.body?.dataset.siteKey || '/';
  const key = `hugo-docs:${siteKey}:tree`;
  const scrollKey = `${key}:scroll`;
  const state = Object.create(null);
  const normalize = id => String(id).replace(/^\/+|\/+$/g, '');
  try {
    const saved = JSON.parse(localStorage.getItem(key) || '{}');
    if (saved && typeof saved === 'object' && !Array.isArray(saved)) {
      for (const [id, value] of Object.entries(saved)) {
        if (typeof value === 'boolean') state[normalize(id)] = value;
      }
      localStorage.setItem(key, JSON.stringify(state));
    }
  } catch {}
  let scroll = null;
  try {
    const value = sessionStorage.getItem(scrollKey);
    if (value !== null && Number.isFinite(Number(value)) && Number(value) >= 0) scroll = Number(value);
  } catch {}
  const get = (id, fallback) => state[normalize(id)] ?? fallback;
  const set = (id, open) => {
    const normalized = normalize(id);
    const next = Boolean(open);
    if (state[normalized] === next) return;
    state[normalized] = next;
    try { localStorage.setItem(key, JSON.stringify(state)); } catch {}
  };
  const saveScroll = value => {
    if (!Number.isFinite(value) || value < 0) return;
    scroll = value;
    try { sessionStorage.setItem(scrollKey, String(value)); } catch {}
  };
  const restoreScroll = nav => {
    if (nav && scroll !== null) nav.scrollTop = scroll;
  };
  const restoreStatic = (root = document) => {
    let ui = {};
    try { ui = JSON.parse(document.body?.dataset.ui || '{}'); } catch {}
    for (const button of root.querySelectorAll('button[data-section][aria-controls]')) {
      const target = document.getElementById(button.getAttribute('aria-controls'));
      if (!target) continue;
      const fallback = button.getAttribute('aria-expanded') === 'true';
      if (get(button.dataset.section) === undefined && fallback) set(button.dataset.section, true);
      const open = get(button.dataset.section, fallback);
      button.setAttribute('aria-expanded', String(open));
      target.hidden = !open;
      const label = open ? ui.collapseFolder : ui.expandFolder;
      if (label) button.setAttribute('aria-label', `${label} ${button.dataset.title}`);
    }
  };
  window.WikiTreeState = { normalize, get, set, restoreStatic, readScroll: () => scroll, saveScroll, restoreScroll };
  let interacted = false;
  const touch = event => {
    if (event.target?.closest?.('.page-tree')) interacted = true;
  };
  for (const event of ['wheel', 'touchstart', 'pointerdown', 'keydown']) document.addEventListener(event, touch, { passive: true, capture: true });
  document.addEventListener('scroll', event => {
    if (interacted && event.target?.matches?.('.page-tree')) saveScroll(event.target.scrollTop);
  }, { passive: true, capture: true });
  addEventListener('pagehide', () => {
    const nav = document.querySelector('.page-tree');
    if (nav) saveScroll(nav.scrollTop);
  });
  const restore = () => {
    restoreStatic();
    if (!interacted) restoreScroll(document.querySelector('.page-tree'));
  };
  const observer = new MutationObserver(restore);
  observer.observe(document.documentElement, { childList: true, subtree: true });
  const finish = () => {
    restore();
    observer.disconnect();
    const nav = document.querySelector('.page-tree');
    if (!nav) return;
    requestAnimationFrame(() => { if (!interacted) restoreScroll(nav); });
    document.fonts?.ready.then(() => { if (!interacted) restoreScroll(nav); });
    addEventListener('pageshow', event => { if (event.persisted) restoreScroll(nav); });
  };
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', finish, { once: true });
  else finish();
})();
