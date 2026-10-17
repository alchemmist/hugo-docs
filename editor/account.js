export async function mountAccount(root) {
  const base = root.dataset.basePath || '/';
  const label = document.documentElement.lang.startsWith('ru') ? 'Войти' : 'Sign in';
  let session = {user: null};
  try {
    const response = await fetch(base + 'api/editor/session', {credentials: 'same-origin', cache: 'no-store'});
    if (response.ok) session = await response.json();
  } catch {}
  const link = document.createElement('a');
  link.className = 'wiki-account-toggle';
  link.textContent = session.user?.username || label;
  link.href = base + (session.user ? 'admin' : 'login');
  document.body.append(link);
  return session;
}
