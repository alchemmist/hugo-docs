const words = {
  en: {sync:'Git synchronization',syncDisabled:'Disabled',syncReady:'Up to date',syncPending:'Pending changes',syncError:'Synchronization failed',syncLoading:'Checking…',account:'Account', login:'Sign in', logout:'Sign out', username:'Username', password:'Password', current:'Current password', next:'New password', change:'Change password', users:'Users', create:'Create user', role:'Role', reader:'Reader', editor:'Editor', admin:'Administrator', disable:'Disable', enable:'Enable', reset:'Reset password', close:'Close', failed:'Request failed. Please try again.', saved:'Saved', secret:'Bootstrap secret', bootstrap:'Create administrator'},
  ru: {sync:'Синхронизация Git',syncDisabled:'Отключена',syncReady:'Все изменения отправлены',syncPending:'Ожидают отправки',syncError:'Ошибка синхронизации',syncLoading:'Проверка…',account:'Аккаунт', login:'Войти', logout:'Выйти', username:'Логин', password:'Пароль', current:'Текущий пароль', next:'Новый пароль', change:'Сменить пароль', users:'Пользователи', create:'Создать пользователя', role:'Роль', reader:'Читатель', editor:'Редактор', admin:'Администратор', disable:'Отключить', enable:'Включить', reset:'Сбросить пароль', close:'Закрыть', failed:'Не удалось выполнить запрос. Повторите попытку.', saved:'Сохранено', secret:'Секрет первоначальной настройки', bootstrap:'Создать администратора'}
};

export async function mountAccount(root) {
  const text = words[document.documentElement.lang.split('-')[0]] || words.en;
  const base = root.dataset.basePath || '/';
  let session = {user:null};
  const request = async (path, data, method='POST') => {
    const response = await fetch(base + 'api/' + path, {method:data === undefined?'GET':method,credentials:'same-origin',cache:'no-store',headers:data === undefined?{}:{'Content-Type':'application/json','X-CSRF-Token':session.csrf_token || session.csrf || ''},body:data === undefined?undefined:JSON.stringify(data)});
    const result = await response.json().catch(()=>({}));
    if (!response.ok) throw new Error(result.detail || result.error || text.failed);
    return result;
  };
  try { session = await request('editor/session'); } catch {}
  const toggle = document.createElement('button'); toggle.type='button'; toggle.className='wiki-account-toggle'; toggle.textContent=session.user?.username || text.login;
  const dialog=document.createElement('dialog'); dialog.className='wiki-account'; dialog.setAttribute('aria-label',text.account);
  const header=document.createElement('div'); header.className='wiki-account-header'; const title=document.createElement('h2');title.textContent=text.account;
  const close=document.createElement('button');close.type='button';close.textContent=text.close;close.addEventListener('click',()=>dialog.close());header.append(title,close);
  const status=document.createElement('p');status.setAttribute('role','status');status.className='wiki-account-status';
  dialog.append(header,status);document.body.append(toggle,dialog);toggle.addEventListener('click',()=>dialog.showModal());
  const field=(form,name,label,type='text')=>{const wrap=document.createElement('label');wrap.textContent=label;const input=document.createElement('input');input.name=name;input.type=type;input.required=true;input.autocomplete=type==='password'?(name==='current_password'?'current-password':'new-password'):'username';wrap.append(input);form.append(wrap);return input;};
  const action=(label,run)=>{const button=document.createElement('button');button.type='button';button.textContent=label;button.addEventListener('click',async()=>{button.disabled=true;status.textContent='';try{await run();}catch(error){status.textContent=error.message;}finally{button.disabled=false;}});return button;};
  const form=(label,fields,run)=>{const form=document.createElement('form');for(const [name,label,type] of fields)field(form,name,label,type);const submit=document.createElement('button');submit.type='submit';submit.textContent=label;form.append(submit);form.addEventListener('submit',async event=>{event.preventDefault();submit.disabled=true;status.textContent='';try{await run(Object.fromEntries(new FormData(form)));status.textContent=text.saved;}catch(error){status.textContent=error.message;}finally{submit.disabled=false;}});dialog.append(form);return form;};
  if(!session.user){
    const login=form(text.login,[['username',text.username],['password',text.password,'password']],async data=>{await request('auth/login',data);location.reload();});login.elements.password.autocomplete='current-password';
    if(session.bootstrap_required)form(text.bootstrap,[['secret',text.secret,'password'],['username',text.username],['password',text.password,'password']],async data=>{await request('auth/bootstrap',data);location.reload();});
    return session;
  }
  if(session.writable){
    const sync=document.createElement('p');sync.className='wiki-account-sync';sync.setAttribute('role','status');dialog.append(sync);
    let loading=false;
    toggle.addEventListener('click',async()=>{
      if(loading)return;loading=true;sync.textContent=text.sync+': '+text.syncLoading;
      try{const value=await request('editor/sync');const label=!value.git_enabled?text.syncDisabled:value.error?text.syncError:value.pending?text.syncPending+' ('+value.pending+')':text.syncReady;sync.textContent=text.sync+': '+label+(value.error?' — '+value.error:'');}
      catch(error){sync.textContent=text.sync+': '+error.message;}
      finally{loading=false;}
    });
  }
  form(text.change,[['current_password',text.current,'password'],['password',text.next,'password']],async data=>{await request('auth/password',data);location.reload();});
  dialog.append(action(text.logout,async()=>{await request('auth/logout',{});location.reload();}));
  if(session.user.role==='admin'){
    const heading=document.createElement('h3');heading.textContent=text.users;dialog.append(heading);
    const list=document.createElement('div');list.className='wiki-account-users';dialog.append(list);
    const roles=(container,value='reader')=>{const select=document.createElement('select');select.name='role';select.setAttribute('aria-label',text.role);for(const role of ['reader','editor','admin']){const option=document.createElement('option');option.value=role;option.textContent=text[role];select.append(option);}select.value=value;container.append(select);return select;};
    const refresh=async()=>{const data=await request('admin/users');list.replaceChildren();for(const user of data.users){const row=document.createElement('div');row.className='wiki-account-user';const name=document.createElement('span');name.textContent=user.username;row.append(name);const select=roles(row,user.role);select.addEventListener('change',async()=>{select.disabled=true;try{await request('admin/users/'+encodeURIComponent(user.id),{role:select.value},'PATCH');}catch(error){select.value=user.role;status.textContent=error.message;}finally{select.disabled=false;}});row.append(action(user.disabled?text.enable:text.disable,async()=>{await request('admin/users/'+encodeURIComponent(user.id),{disabled:!user.disabled},'PATCH');await refresh();}));const password=document.createElement('input');password.type='password';password.placeholder=text.next;password.setAttribute('aria-label',text.next);password.autocomplete='new-password';row.append(password,action(text.reset,async()=>{if(!password.value)return;await request('admin/users/'+encodeURIComponent(user.id)+'/password',{password:password.value});password.value='';status.textContent=text.saved;}));list.append(row);}};
    const create=form(text.create,[['username',text.username],['password',text.password,'password']],async data=>{await request('admin/users',data);create.reset();await refresh();});roles(create);refresh().catch(error=>{status.textContent=error.message;});
  }
  return session;
}
