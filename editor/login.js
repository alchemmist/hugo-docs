import {authError} from './auth-errors.js';

export async function mountLogin(root, navigate = url => location.assign(url)) {
  const ru = document.documentElement.lang.startsWith('ru');
  const text = ru ? {title:'Войти',username:'Логин',password:'Пароль',secret:'Секрет первоначальной настройки',bootstrap:'Создать администратора',failed:'Не удалось войти. Проверьте логин и пароль.',loading:'Вход…'} : {title:'Sign in',username:'Username',password:'Password',secret:'Bootstrap secret',bootstrap:'Create administrator',failed:'Unable to sign in. Check your username and password.',loading:'Signing in…'};
  const base = root.dataset.basePath || '/';
  const h1 = document.createElement('h1'); h1.textContent = text.title; root.replaceChildren(h1);
  const form = document.createElement('form'); form.className = 'wiki-admin-form'; form.method = 'post';
  const field = (name, title, type) => { const label = document.createElement('label'); label.textContent = title; const input = document.createElement('input'); input.name = name; input.type = type; input.required = true; input.autocomplete = name === 'password' ? 'current-password' : name === 'username' ? 'username' : 'off'; label.append(input); form.append(label); return input; };
  field('username',text.username,'text'); const password = field('password',text.password,'password'); password.maxLength = 1024;
  const submit = document.createElement('button'); submit.type = 'submit'; submit.textContent = text.title; submit.disabled = true;
  const status = document.createElement('p'); status.className = 'wiki-admin-status'; status.setAttribute('role','status');
  form.append(submit,status); root.append(form);
  let bootstrap = false;
  let ready = false;
  const destination = () => {
    const requested = new URLSearchParams(location.search).get('next');
    if (requested && requested.startsWith(base) && !requested.startsWith('//') && !requested.includes('\\')) return requested;
    return base + 'admin';
  };
  form.addEventListener('submit', async event => {
    event.preventDefault();
    if (!ready || submit.disabled) return;
    submit.disabled = true; status.textContent = text.loading;
    try {
      const response = await fetch(base + 'api/auth/' + (bootstrap ? 'bootstrap' : 'login'), {method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/json'},body:JSON.stringify(Object.fromEntries(new FormData(form)))});
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(authError(typeof data.detail === 'string' ? data.detail : text.failed, document.documentElement.lang));
      if (bootstrap) {
        const login = await fetch(base + 'api/auth/login', {method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/json'},body:JSON.stringify({username:form.elements.username.value,password:password.value})});
        if (!login.ok) { navigate(base + 'login'); return; }
      }
      navigate(destination());
    } catch (error) { status.textContent = error.message; } finally { submit.disabled = false; }
  });
  try {
    const response = await fetch(base + 'api/editor/session', {credentials:'same-origin',cache:'no-store'});
    if (response.ok) {
      const session = await response.json();
      if (session.user) { navigate(destination()); return; }
      bootstrap = Boolean(session.bootstrap_required);
      if (bootstrap) { h1.textContent = text.bootstrap; submit.textContent = text.bootstrap; password.autocomplete = 'new-password'; password.minLength = 8; const secret = field('secret',text.secret,'password'); form.insertBefore(secret.parentElement,submit); }
    }
  } catch {}
  ready = true;
  submit.disabled = false;
}
const root = typeof document === 'undefined' ? null : document.getElementById('wiki-login');
if (root) mountLogin(root);
