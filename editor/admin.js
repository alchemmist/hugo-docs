import {authError} from './auth-errors.js';
import {mountMcpTokens} from './mcp-tokens.js';

const mounts = new WeakMap();

const words = {
  en: {settings:'Settings',sections:'Settings sections',mcp:'MCP access',account:'Account',appearance:'Appearance',theme:'Theme',light:'Light',dark:'Dark',password:'Password',current:'Current password',next:'New password',change:'Change password',logout:'Sign out',username:'Username',status:'Status',actions:'Actions',role:'Role',reader:'Reader',editor:'Editor',admin:'Administrator',users:'Users',create:'Create user',disable:'Disable',enable:'Enable',reset:'Reset password',saved:'Saved',failed:'Request failed. Please try again.',loading:'Loading…',retry:'Try again',sync:'Git synchronization',syncDisabled:'Disabled',syncReady:'Up to date',syncPending:'Pending changes',syncError:'Synchronization failed',refresh:'Refresh',empty:'No users',disabled:'Disabled',active:'Active',required:'Enter a new password.'},
  ru: {settings:'Настройки',sections:'Разделы настроек',mcp:'Доступ по MCP',account:'Аккаунт',appearance:'Оформление',theme:'Тема',light:'Светлая',dark:'Тёмная',password:'Пароль',current:'Текущий пароль',next:'Новый пароль',change:'Сменить пароль',logout:'Выйти',username:'Логин',status:'Статус',actions:'Действия',role:'Роль',reader:'Читатель',editor:'Редактор',admin:'Администратор',users:'Пользователи',create:'Создать пользователя',disable:'Отключить',enable:'Включить',reset:'Сбросить пароль',saved:'Сохранено',failed:'Не удалось выполнить запрос. Повторите попытку.',loading:'Загрузка…',retry:'Повторить',sync:'Синхронизация Git',syncDisabled:'Отключена',syncReady:'Все изменения отправлены',syncPending:'Ожидают отправки',syncError:'Ошибка синхронизации',refresh:'Обновить',empty:'Нет пользователей',disabled:'Отключён',active:'Активен',required:'Введите новый пароль.'}
};

export async function mountAdmin(root, navigate = url => location.assign(url)) {
  mounts.get(root)?.();
  const view = root.ownerDocument.defaultView;
  const text = words[document.documentElement.lang.split('-')[0]] || words.en;
  const base = root.dataset.basePath || '/';
  let session = {};
  const node = (tag, value, className) => {
    const element = document.createElement(tag);
    if (value) element.textContent = value;
    if (className) element.className = className;
    return element;
  };
  const title = node('h1', text.settings);
  root.replaceChildren(title);
  const status = node('p', text.loading, 'wiki-admin-status');
  status.setAttribute('role', 'status');
  root.append(status);
  const request = async (path, data, method = 'POST') => {
    const response = await fetch(base + 'api/' + path, {method: data === undefined ? 'GET' : method, credentials:'same-origin', cache:'no-store', headers:data === undefined ? {} : {'Content-Type':'application/json','X-CSRF-Token':session.csrf_token || session.csrf || ''}, body:data === undefined ? undefined : JSON.stringify(data)});
    const result = await response.json().catch(() => ({}));
    if (response.status === 401) navigate(base + 'login?next=' + encodeURIComponent(base + 'admin'));
    if (!response.ok) throw new Error(authError(typeof result.detail === 'string' ? result.detail : typeof result.error === 'string' ? result.error : text.failed, document.documentElement.lang));
    return result;
  };
  const action = (label, run, target = status) => {
    const button = node('button', label);
    button.type = 'button';
    button.addEventListener('click', async () => {
      button.disabled = true;
      target.textContent = '';
      try { await run(); } catch (error) { target.textContent = error.message; } finally { button.disabled = false; }
    });
    return button;
  };
  try { session = await request('editor/session'); } catch (error) {
    status.textContent = error.message;
    root.append(action(text.retry, () => mountAdmin(root, navigate)));
    return;
  }
  if (!session.user) { navigate(base + 'login?next=' + encodeURIComponent(base + 'admin')); return; }
  status.remove();
  const layout = node('div', '', 'wiki-admin-layout');
  const nav = node('nav', '', 'wiki-admin-nav');
  nav.setAttribute('aria-label', text.sections);
  const panels = node('div', '', 'wiki-admin-panels');
  layout.append(nav, panels); root.append(layout);
  const entries = new Map();
  const select = () => {
    const requested = view.location.hash.slice(1);
    const selected = entries.has(requested) ? requested : 'account';
    for (const [id, entry] of entries) {
      entry.panel.hidden = id !== selected;
      if (id === selected) entry.link.setAttribute('aria-current', 'page');
      else entry.link.removeAttribute('aria-current');
    }
  };
  const register = (id, label, panel) => {
    panel.id = 'admin-' + id;
    const link = node('a', label); link.href = '#' + id;
    nav.append(link); entries.set(id, {link, panel});
    select();
    return panel;
  };
  const section = (id, label) => {
    const panel = node('section', '', 'wiki-admin-section');
    panel.append(node('h2', label)); panels.append(panel);
    return register(id, label, panel);
  };
  view.addEventListener('hashchange', select);
  mounts.set(root, () => view.removeEventListener('hashchange', select));
  const account = section('account', text.account);
  const identity = node('p', session.user.username + ' · ' + text[session.user.role], 'wiki-admin-identity');
  const accountStatus = node('p', '', 'wiki-admin-status'); accountStatus.setAttribute('role', 'status');
  account.append(identity, action(text.logout, async () => { await request('auth/logout', {}); navigate(base); }, accountStatus), accountStatus, node('h3', text.password));
  const appearance = node('div', '', 'wiki-theme-preference');
  const themeLabel = node('label', text.theme);
  const themeSelect = node('select'); themeSelect.name = 'theme'; themeSelect.setAttribute('aria-label', text.theme);
  for (const theme of ['light','dark']) {
    const option = node('option', text[theme]); option.value = theme; themeSelect.append(option);
  }
  themeSelect.value = session.user.theme === 'dark' ? 'dark' : 'light';
  const themeStatus = node('p', '', 'wiki-admin-status'); themeStatus.setAttribute('role', 'status');
  themeLabel.append(themeSelect); appearance.append(node('h3', text.appearance), themeLabel, themeStatus);
  account.insertBefore(appearance, account.lastElementChild);
  themeSelect.addEventListener('change', async () => {
    const previous = session.user.theme === 'dark' ? 'dark' : 'light';
    themeSelect.disabled = true; themeStatus.textContent = '';
    try {
      const result = await request('auth/preferences', {theme:themeSelect.value});
      if (!['light','dark'].includes(result.theme)) throw new Error(text.failed);
      session.user.theme = result.theme;
      themeSelect.value = result.theme;
      document.documentElement.dataset.theme = result.theme;
      themeStatus.textContent = text.saved;
    } catch (error) { themeSelect.value = previous; themeStatus.textContent = error.message; }
    finally { themeSelect.disabled = false; }
  });
  const loading = [];
  const field = (form, name, label, type = 'text') => {
    const wrap = node('label', label);
    const input = node('input');
    input.name = name; input.type = type; input.required = true;
    if (type === 'password') { input.maxLength = 1024; if (name !== 'current_password') input.minLength = 8; }
    input.autocomplete = type === 'password' ? name === 'current_password' ? 'current-password' : 'new-password' : 'username';
    wrap.append(input); form.append(wrap);
    return input;
  };
  const roles = (form, value = 'reader') => {
    const label = node('label', text.role);
    const select = node('select'); select.name = 'role';
    for (const role of ['reader','editor','admin']) { const option = node('option', text[role]); option.value = role; select.append(option); }
    select.value = value; label.append(select); form.append(label);
    return select;
  };
  const form = (parent, label, fields, run, role, username) => {
    const form = node('form', '', 'wiki-admin-form');
    form.method = 'post';
    if (username) {
      const identity = node('input'); identity.type = 'text'; identity.name = 'username'; identity.autocomplete = 'username'; identity.value = username; identity.hidden = true;
      form.append(identity);
    }
    for (const args of fields) field(form, ...args);
    if (role) roles(form);
    const submit = node('button', label); submit.type = 'submit';
    const message = node('p', '', 'wiki-admin-status'); message.setAttribute('role','status');
    form.append(submit, message); parent.append(form);
    form.addEventListener('submit', async event => {
      event.preventDefault(); submit.disabled = true; message.textContent = '';
      const data = Object.fromEntries(new FormData(form));
      if (username) delete data.username;
      try { await run(data); form.reset(); message.textContent = text.saved; } catch (error) { message.textContent = error.message; } finally { submit.disabled = false; }
    });
    return form;
  };
  form(account, text.change, [['current_password',text.current,'password'],['password',text.next,'password']], async data => {
    await request('auth/password', data);
    navigate(base + 'login?next=' + encodeURIComponent(base + 'admin'));
  }, false, session.user.username);
  if (session.writable) {
    const sync = section('sync', text.sync);
    const message = node('p', '', 'wiki-admin-sync'); message.setAttribute('role','status'); sync.append(message);
    const refresh = async () => {
      message.textContent = text.loading;
      try {
        const value = await request('editor/sync');
        message.textContent = !value.git_enabled ? text.syncDisabled : value.error ? text.syncError + ': ' + value.error : value.pending ? text.syncPending + ' (' + value.pending + ')' : text.syncReady;
      } catch (error) { message.textContent = error.message; }
    };
    sync.append(action(text.refresh, refresh, message)); loading.push(refresh());
  }
  if (session.mcp_enabled) {
    loading.push(mountMcpTokens(panels, session, request));
    register('mcp', text.mcp, panels.lastElementChild);
  }
  if (session.user.role !== 'admin') { await Promise.all(loading); return session; }
  const users = section('users', text.users);
  const list = node('div', '', 'wiki-admin-users'); users.append(list);
  const listStatus = node('p', '', 'wiki-admin-status'); listStatus.setAttribute('role','status'); users.append(listStatus);
  const refresh = async () => {
    const data = await request('admin/users');
    list.replaceChildren();
    if (!data.users.length) { list.append(node('p', text.empty)); return; }
    const wrap = node('div', '', 'wiki-users-table-wrap');
    wrap.tabIndex = 0; wrap.setAttribute('role', 'region'); wrap.setAttribute('aria-label', text.users);
    const table = node('table', '', 'wiki-users-table'); table.setAttribute('aria-label', text.users);
    const head = node('thead'); const headings = node('tr');
    for (const label of [text.username,text.role,text.status,text.actions]) {
      const cell = node('th', label); cell.scope = 'col'; headings.append(cell);
    }
    head.append(headings); const body = node('tbody'); table.append(head,body); wrap.append(table); list.append(wrap);
    for (const [index, user] of data.users.entries()) {
      const row = node('tr', '', 'wiki-admin-user');
      const name = node('th', user.username); name.scope = 'row'; row.append(name);
      const role = node('td'); role.dataset.label = text.role; row.append(role);
      const select = roles(role, user.role);
      select.setAttribute('aria-label', text.role + ': ' + user.username);
      role.replaceChildren(select);
      const state = node('td'); state.dataset.label = text.status;
      state.append(node('span', user.disabled ? text.disabled : text.active, 'wiki-admin-user-state')); row.append(state);
      const controls = node('td', '', 'wiki-admin-user-actions'); controls.dataset.label = text.actions; row.append(controls);
      select.addEventListener('change', async () => {
        select.disabled = true; listStatus.textContent = '';
        try { await request('admin/users/' + encodeURIComponent(user.id), {role:select.value}, 'PATCH'); user.role = select.value; listStatus.textContent = text.saved; }
        catch (error) { select.value = user.role; listStatus.textContent = error.message; }
        finally { select.disabled = false; }
      });
      controls.append(action(user.disabled ? text.enable : text.disable, async () => {
        await request('admin/users/' + encodeURIComponent(user.id), {disabled:!user.disabled}, 'PATCH'); await refresh();
      }, listStatus));
      const details = node('tr', '', 'wiki-admin-user-reset'); details.hidden = true;
      details.id = 'wiki-user-reset-' + index;
      const cell = node('td'); cell.colSpan = 4; details.append(cell);
      const toggle = node('button', text.reset); toggle.type = 'button';
      toggle.setAttribute('aria-label', text.reset + ': ' + user.username);
      toggle.setAttribute('aria-expanded', 'false'); toggle.setAttribute('aria-controls', details.id);
      toggle.addEventListener('click', () => {
        details.hidden = !details.hidden; toggle.setAttribute('aria-expanded', String(!details.hidden));
        if (!details.hidden) reset.elements.password.focus();
      });
      controls.append(toggle);
      const reset = form(cell, text.reset, [['password',text.next,'password']], async data => {
        await request('admin/users/' + encodeURIComponent(user.id) + '/password', data);
        details.hidden = true; toggle.setAttribute('aria-expanded', 'false'); toggle.focus(); listStatus.textContent = text.saved;
      }, false, user.username);
      reset.elements.password.setAttribute('aria-label', text.next + ': ' + user.username);
      body.append(row, details);
    }
  };
  const load = async () => { listStatus.textContent = text.loading; try { await refresh(); listStatus.textContent = ''; } catch (error) { listStatus.textContent = error.message; } };
  users.append(action(text.refresh, load, listStatus));
  const create = node('details', '', 'wiki-admin-create'); create.append(node('summary', text.create)); users.append(create);
  form(create, text.create, [['username',text.username],['password',text.password,'password']], async data => { await request('admin/users', data); await refresh(); }, true);
  loading.push(load());
  await Promise.all(loading);
  return session;
}

const root = typeof document === 'undefined' ? null : document.getElementById('wiki-admin');
if (root) mountAdmin(root);
