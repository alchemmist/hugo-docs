export function createPublishedView({article, heading, bodyHash}) {
  let html = article.innerHTML;
  let title = heading.textContent;
  let version = 0;
  const restore = () => {
    article.innerHTML = html;
    heading.textContent = title;
  };
  const capture = (nextTitle, nextHTML) => {
    title = nextTitle;
    html = nextHTML;
    bodyHash = null;
    version++;
  };
  const hydratePage = async ({api, path, page, canApply, apply = true, started = version}) => {
    if (!canApply() || started !== version) return;
    const digest = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(page.body.replace(/^\n+/, '')));
    const hash = Array.from(new Uint8Array(digest), byte=>byte.toString(16).padStart(2, '0')).join('');
    if (!canApply() || started !== version || hash === bodyHash && page.title === title) return;
    const preview = await api('/preview', {title:page.title, body:page.body, path});
    if (!canApply() || started !== version) return;
    capture(page.title, preview.html);
    bodyHash = hash;
    if (apply) restore();
  };
  const hydrate = async ({api, path, canApply, apply = true}) => {
    const started = version;
    const page = await api('/pages?path=' + encodeURIComponent(path));
    await hydratePage({api, path, page, canApply, apply, started});
  };
  return {capture, restore, hydrate, hydratePage};
}
