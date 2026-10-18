const words = {
  en: {title:'MCP access',intro:'Connect an agent using a personal token. It has your current wiki permissions.',reader:'Your account can only read notes.',endpoint:'MCP endpoint',copy:'Copy',copied:'Copied',copyFailed:'Copy failed. Select and copy the value manually.',config:'Client configuration',name:'Token name',expires:'Expires in',days:'days',readOnly:'Read-only token',create:'Create token',secret:'New token',once:'Save this token securely. It is shown only once.',dismiss:'Hide token',tokens:'Your tokens',empty:'No tokens yet.',revoke:'Revoke',refresh:'Refresh',loading:'Loading…',expiry:'Expires',readonly:'Read only',write:'Read and write',created:'Created',invalid:'Enter a token name.'},
  ru: {title:'Доступ по MCP',intro:'Подключите агента с личным токеном. Он получает текущие права вашего аккаунта в wiki.',reader:'Ваш аккаунт может только читать заметки.',endpoint:'Адрес MCP',copy:'Копировать',copied:'Скопировано',copyFailed:'Не удалось скопировать. Выделите и скопируйте значение вручную.',config:'Конфигурация клиента',name:'Название токена',expires:'Срок действия',days:'дней',readOnly:'Только чтение',create:'Создать токен',secret:'Новый токен',once:'Сохраните токен в надёжном месте. Он показывается только один раз.',dismiss:'Скрыть токен',tokens:'Ваши токены',empty:'Токенов пока нет.',revoke:'Отозвать',refresh:'Обновить',loading:'Загрузка…',expiry:'Истекает',readonly:'Только чтение',write:'Чтение и запись',created:'Создан',invalid:'Введите название токена.'}
};

export async function mountMcpTokens(parent, session, request) {
  if (!session.mcp_enabled) return;
  const language = document.documentElement.lang || 'en';
  const text = words[language.split('-')[0]] || words.en;
  const node = (tag, value = '', className = '') => {
    const element = document.createElement(tag); element.textContent = value;
    if (className) element.className = className;
    return element;
  };
  const section = node('section', '', 'wiki-admin-section wiki-mcp');
  section.append(node('h2', text.title), node('p', text.intro));
  if (session.user.role === 'reader') section.append(node('p', text.reader));
  parent.append(section);
  const status = node('p', '', 'wiki-admin-status'); status.setAttribute('role', 'status');
  const button = (label, run) => {
    const element = node('button', label); element.type = 'button';
    element.addEventListener('click', async () => {
      element.disabled = true; status.textContent = '';
      try { await run(); } catch (error) { status.textContent = error.message; }
      finally { element.disabled = false; }
    });
    return element;
  };
  const copy = value => button(text.copy, async () => {
    try { await navigator.clipboard.writeText(value()); status.textContent = text.copied; }
    catch { status.textContent = text.copyFailed; }
  });
  const readonly = (label, value, parent) => {
    const wrap = node('label', label); const input = node('input');
    input.readOnly = true; input.value = value; input.autocomplete = 'off'; input.spellcheck = false;
    wrap.append(input); parent.append(wrap, copy(() => input.value)); return input;
  };
  const endpoint = node('div', '', 'wiki-mcp-value');
  readonly(text.endpoint, session.mcp_url, endpoint); section.append(endpoint);
  const details = node('details', '', 'wiki-mcp-config');
  details.append(node('summary', text.config));
  details.append(node('pre', JSON.stringify({mcpServers:{wiki:{url:session.mcp_url,headers:{Authorization:'Bearer <YOUR_TOKEN>'}}}}, null, 2)));
  section.append(details);
  const form = node('form', '', 'wiki-admin-form'); form.method = 'post';
  const nameLabel = node('label', text.name); const name = node('input');
  name.name = 'token_name'; name.required = true; name.maxLength = 100; name.autocomplete = 'off'; nameLabel.append(name);
  const expiresLabel = node('label', text.expires); const expires = node('select'); expires.name = 'expires_days';
  for (const days of [30,90,365]) { const option = node('option', days + ' ' + text.days); option.value = String(days); expires.append(option); }
  expires.value = '90'; expiresLabel.append(expires);
  const readLabel = node('label', '', 'wiki-mcp-checkbox'); const readOnly = node('input'); readOnly.type = 'checkbox'; readOnly.name = 'read_only';
  readOnly.checked = session.user.role === 'reader'; readOnly.disabled = session.user.role === 'reader';
  readLabel.append(readOnly, document.createTextNode(text.readOnly));
  const submit = node('button', text.create); submit.type = 'submit';
  form.append(nameLabel, expiresLabel, readLabel, submit); section.append(form);
  const secret = node('div', '', 'wiki-mcp-secret'); section.append(secret, status);
  let revealedId = null;
  const clearSecret = () => { secret.querySelectorAll('input').forEach(input => { input.value = ''; }); secret.replaceChildren(); revealedId = null; };
  section.append(node('h3', text.tokens));
  const list = node('div', '', 'wiki-mcp-tokens'); section.append(list);
  const date = value => {
    const parsed = new Date(typeof value === 'number' ? value * 1000 : value);
    return Number.isNaN(parsed.getTime()) ? String(value) : parsed.toLocaleString(language);
  };
  const refresh = async () => {
    const {tokens} = await request('auth/tokens'); list.replaceChildren();
    if (!tokens.length) list.append(node('p', text.empty));
    for (const token of tokens) {
      const row = node('div', '', 'wiki-mcp-token'); const info = node('div');
      info.append(node('h4', token.name), node('p', `${text.created}: ${date(token.created_at)} · ${text.expiry}: ${date(token.expires_at)} · ${token.read_only || session.user.role === 'reader' ? text.readonly : text.write}`));
      row.append(info, button(text.revoke, async () => {
        await request('auth/tokens/' + encodeURIComponent(token.id), {}, 'DELETE');
        if (revealedId === token.id) clearSecret();
        row.remove(); if (!list.children.length) list.append(node('p', text.empty));
      })); list.append(row);
    }
  };
  form.addEventListener('submit', async event => {
    event.preventDefault(); if (submit.disabled) return;
    if (!name.value.trim()) { status.textContent = text.invalid; name.focus(); return; }
    submit.disabled = true; status.textContent = '';
    try {
      const result = await request('auth/tokens', {name:name.value.trim(),expires_days:Number(expires.value),read_only:readOnly.checked});
      clearSecret(); revealedId = result.id;
      secret.append(node('p', text.once));
      const value = node('div', '', 'wiki-mcp-value'); const input = readonly(text.secret, result.token, value);
      secret.append(value, button(text.dismiss, clearSecret)); input.focus(); input.select(); form.reset(); expires.value = '90'; readOnly.checked = session.user.role === 'reader';
      await refresh();
    } catch (error) { status.textContent = error.message; }
    finally { submit.disabled = false; }
  });
  section.append(button(text.refresh, refresh));
  status.textContent = text.loading;
  try { await refresh(); status.textContent = ''; } catch (error) { status.textContent = error.message; }
}
