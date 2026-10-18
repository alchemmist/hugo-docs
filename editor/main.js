import { configureRichContent, insertRichContent } from './rich-content.js';
import { t } from './i18n.js';
import { createFormatToolbar } from './toolbar.js';
import { mountAccount } from './account.js';
import { resolvePreviewLinks } from './preview-links.js';
import { createWorkspace, batchPages } from './workspace.js';
import { initializeTree } from './tree.js';
import { createPublishedView } from './published-view.js';
import { createPublicationState } from './publication-state.js';
import { Editor } from '@tiptap/core';
import { extensions, prepareMarkdown, sourceBody } from './markdown.js';

const root = document.getElementById('wiki-editor');
if (root) mountAccount(root).then(session => { if (session?.writable) initialize(session); });
function initialize(session) {
  const basePath = root.dataset.basePath || "/";
  configureRichContent({basePath});
  const heading = document.getElementById('page-title');
  const article = document.querySelector('.document .hc-content');
  if (!heading || !article) return;
  const status = root.querySelector('[role="alert"]');
  heading.after(status);
  const editbar = root.querySelector('.wiki-editbar');
  const actions = root.querySelector('.wiki-editor-actions');
  const save = root.querySelector('[data-editor-save]');
  const publicationState = createPublicationState(save);
  const workspace = createWorkspace(sessionStorage, 'hugo-docs:' + location.origin + basePath + ':' + session.user.id, {basePath});
  const pageCache = new Map();
  const draftsNav = document.createElement('span'); draftsNav.className = 'wiki-workspace-drafts'; save.before(draftsNav);
  const draftCount = () => {
    const drafts = workspace.drafts(); const count = drafts.length + workspace.operations().length; save.textContent = busy ? t('Публикуется…') : count ? t('Опубликовать') + ' ' + count : t('Опубликовать');
    draftsNav.replaceChildren();
    for (const draft of drafts.filter(item=>item.creating && item.path!==path && !workspace.isDeleted(item.path))) {
      const button = document.createElement('button'); button.type='button'; button.textContent=draft.title || t('Новая заметка');
      button.addEventListener('click',async()=>{if(busy || !stop(false))return;path=draft.path;await open(false);}); draftsNav.append(button);
    }
  };
  const loadPage = target => { if (!pageCache.has(target)) pageCache.set(target, api('/pages?path=' + encodeURIComponent(target)).catch(error => { pageCache.delete(target); throw error; })); return pageCache.get(target); };
  const publications = new Map();
  const view = createPublishedView({article, heading, bodyHash: root.dataset.bodyHash});
  let csrf = '', revision = '', path = root.dataset.path, original = '', originalJSON, refs;
  let structure, stashFailed = false;
  let editor, toolbar, fields, linkForm, baselineTitle, creating = false, busy = false, generation = 0;
  const message = (text, error = false) => { status.textContent = error ? text : ''; status.hidden = !error; };
  const api = async (endpoint, data, method = 'POST') => {
    const response = await fetch(root.dataset.apiBase + endpoint, {method: data === undefined ? 'GET' : method, credentials: 'same-origin', cache: 'no-store', headers: data === undefined ? {} : {'Content-Type': 'application/json', 'X-CSRF-Token': csrf}, body: data === undefined ? undefined : JSON.stringify(data)});
    const result = await response.json().catch(() => ({}));
    if (!response.ok) { const error = new Error(response.status === 409 ? t('Wiki уже изменилась. Все ваши правки текста и структуры сохранены в черновике; публикация не применена.') : response.status === 401 || response.status === 403 ? t('Войдите снова или проверьте права доступа. Ваш текст остаётся на странице.') : result.error || result.detail || t('Не удалось выполнить запрос. Проверьте соединение и повторите попытку.')); error.status=response.status; throw error; }
    return result;
  };
  const dirty = () => editor && (creating || heading.textContent !== baselineTitle || JSON.stringify(editor.getJSON()) !== JSON.stringify(originalJSON));
  const setBusy = value => { busy = value; editbar.setAttribute('aria-busy', String(value)); draftCount(); save.disabled = value; root.querySelector('[data-editor-cancel]').disabled = value; editor?.setEditable(!value, false); heading.contentEditable = editor && !value ? 'true' : 'false'; };
  const stash = () => {
    if (!editor || workspace.isDeleted(path)) return true;
    const previous = workspace.get(path);
    const sidebarChanged = (previous?.title ?? baselineTitle) !== heading.textContent || creating && previous?.slug !== (fields?.querySelector('input')?.value || '');
    try {
    if (dirty()) workspace.put({path, revision, title:heading.textContent, body:sourceBody(original,originalJSON,editor.getJSON(),editor.getMarkdown(),refs), creating, slug:fields?.querySelector('input')?.value || '', baseline:{title:baselineTitle,body:original,revision}});
    else workspace.remove(path);
      stashFailed = false;
    } catch (error) { stashFailed = true; message(error.message || t('Не удалось сохранить черновик в браузере. Не закрывайте страницу до публикации.'),true); }
    draftCount(); if (sidebarChanged) structure?.render();
    return !stashFailed;
  };
  const stop = (discard = true) => {
    if (busy) return;
    if (!stash() && !discard) return false;
    if (discard && (dirty() || workspace.hasChanges()) && !confirm(t('Отменить все неопубликованные изменения wiki?'))) return;
    if (discard) { try { workspace.discard(); structure?.reset().catch(error=>message(error.message,true)); stashFailed=false; } catch { message(t('Не удалось очистить черновики браузера. Повторите отмену.'),true); return false; } }
    generation++;
    editor?.destroy(); editor = null;
    toolbar?.remove(); fields?.remove(); linkForm?.remove();
    view.restore();
    article.classList.remove('wiki-rich-editor');

    heading.removeAttribute('contenteditable');
    heading.removeAttribute('role');
    heading.removeAttribute('aria-label');
    editbar.hidden = true; actions.hidden = false;
    document.body.classList.remove('wiki-editing');
    structure?.render();
    message('');
    root.querySelector('[data-editor-open]')?.focus();
    return true;
  };
  function addToolbar() {
    const upload = document.createElement('input'); upload.type='file'; upload.accept='image/png,image/jpeg,image/webp,image/gif,video/mp4,video/webm,audio/mpeg,audio/ogg'; upload.hidden=true;
    const toggle = (id, label, command, node, attributes) => ({id, label:t(label), run:()=>editor.chain().focus()[command](attributes).run(), active:()=>editor.isActive(node, attributes)});
    const rich = (id, label, kind = id) => ({id, label:t(label), run:()=>insertRichContent(editor,kind)});
    const formatting = createFormatToolbar({document, editor, label:t('Форматирование текста'), isBusy:()=>busy, groups:[
      {label:'Text style', actions:[
        toggle('paragraph','Текст','setParagraph','paragraph'),
        toggle('heading2','Heading 2','toggleHeading','heading',{level:2}),
        toggle('heading3','Heading 3','toggleHeading','heading',{level:3}),
        toggle('bold','Жирный','toggleBold','bold'),
        toggle('italic','Курсив','toggleItalic','italic')
      ]},
      {label:'Lists', actions:[
        toggle('bullet','Список','toggleBulletList','bulletList'),
        toggle('ordered','1. Список','toggleOrderedList','orderedList'),
        {...rich('task','Задачи'), active:()=>editor.isActive('taskList')}
      ]},
      {label:'Insert', actions:[
        {id:'link', label:t('Ссылка'), active:()=>editor.isActive('link'), run:()=>{linkForm.hidden=!linkForm.hidden;if(!linkForm.hidden)linkForm.querySelector('input').focus();}},
        toggle('code','Код','toggleCodeBlock','codeBlock'),
        {id:'table',label:t('Таблица'),run:()=>editor.chain().focus().insertTable({rows:3,cols:2,withHeaderRow:true}).run()},
        {id:'media',label:t('Медиа'),run:()=>upload.click()}
      ]},
      {label:'Rich content', actions:[
        rich('math','Формула'),rich('diagram','Диаграмма','mermaid'),rich('note','Примечание','alert'),rich('footnote','Сноска')
      ]}
    ]});
    toolbar = formatting.element;
    const uploadButton = formatting.buttons.get('media');
    upload.addEventListener('change',async()=>{ const file=upload.files[0];if(!file || busy)return;uploadButton.disabled=true;try{if(file.size>8*1024*1024)throw new Error(t('Файл должен быть меньше 8 МБ.'));const content=await new Promise((resolve,reject)=>{const reader=new FileReader();reader.onload=()=>resolve(String(reader.result).split(',')[1]);reader.onerror=reject;reader.readAsDataURL(file);});const result=await api('/uploads',{name:file.name,content});workspace.addUpload(result.id);editor.chain().focus().setImage({src:result.url,alt:file.name}).run();stash();}catch(error){message(error.message,true);}finally{uploadButton.disabled=false;upload.value='';}});
    toolbar.append(upload);
    article.before(toolbar);
    linkForm = document.createElement('form'); linkForm.className = 'wiki-link-form'; linkForm.hidden = true;
    const input = document.createElement('input'); input.type = 'text'; input.placeholder = t('https://… или /раздел/заметка/'); input.setAttribute('aria-label', t('Адрес ссылки'));
    const apply = document.createElement('button'); apply.type = 'submit'; apply.textContent = t('Добавить ссылку');
    const remove = document.createElement('button'); remove.type = 'button'; remove.textContent = t('Убрать ссылку');
    remove.addEventListener('click', () => { editor.chain().focus().unsetLink().run(); linkForm.hidden = true; });
    linkForm.append(input, apply, remove); toolbar.after(linkForm);
    linkForm.addEventListener('submit', event => { event.preventDefault(); const href = input.value.trim(); if (!/^(https?:\/\/|mailto:|\/(?!\/)|#)/i.test(href)) { message(t('Укажите https://, mailto:, якорь или путь от корня сайта.'), true); return; } editor.chain().focus().extendMarkRange('link').setLink({href}).run(); linkForm.hidden = true; });
  }
  async function open(isNew, seed) {
    if (busy || editor) return;
    if (workspace.isDeleted(path)) { location.assign(basePath); return; }
    busy = true; generation++; publicationState.reset(); message('');
    try {
      creating = isNew;
      workspace.start();
      if (creating) path = 'draft:' + crypto.randomUUID();
      const draft = workspace.get(path);
      const page = draft?.baseline || (creating ? {title:seed?.title || t('Новая заметка'),body:'',revision:''} : await loadPage(path));
      creating = draft?.creating || creating;
      if (!creating) {
        const snapshotPath = path;
        view.hydrate({api:(endpoint,payload)=>payload === undefined ? loadPage(snapshotPath) : api(endpoint,payload),path:snapshotPath,apply:false,canApply:()=>path===snapshotPath}).then(()=>{
          if (path===snapshotPath && !editor && !busy && !workspace.active()) view.restore();
        }).catch(()=>{});
      }
      const prepared = prepareMarkdown(page.body);
      original = page.body; refs = prepared.refs; revision = page.revision;
      article.replaceChildren(); article.classList.add('wiki-rich-editor');
      editor = new Editor({onUpdate:()=>{ publicationState.reset(); stash(); }, element: article, extensions: extensions(), content: prepared.prepared, contentType:'markdown', editorProps:{
        attributes:{'aria-label':t('Текст заметки'),role:'textbox','aria-multiline':'true'},
        handlePaste(view, event) { event.preventDefault(); const text = event.clipboardData?.getData('text/plain') || ''; view.dispatch(view.state.tr.insertText(text)); return true; },
        handleDrop() { return true; }
      }});
      originalJSON = editor.getJSON(); baselineTitle = page.title;
      if (draft) { const restored = prepareMarkdown(draft.body); refs = restored.refs; editor.commands.setContent(restored.prepared, {contentType:'markdown',emitUpdate:false}); }
      heading.textContent = draft?.title ?? page.title; heading.contentEditable = 'true'; heading.setAttribute('role','textbox'); heading.setAttribute('aria-label',t('Название заметки'));
      addToolbar();
      if (creating) {
        fields = document.createElement('div'); fields.className = 'wiki-new-fields';
        const slugLabel = document.createElement('label'); slugLabel.textContent = t('Адрес: латинские буквы, цифры, дефисы');
        const slug = document.createElement('input'); slug.name = 'slug'; slug.placeholder = 'new-note'; slug.value = draft?.slug || seed?.slug || ''; slug.disabled=workspace.slugLocked(path); slug.addEventListener('input',stash); slugLabel.append(slug);
        fields.append(slugLabel); heading.parentElement.after(fields);
      }
      actions.hidden = true; editbar.hidden = false; document.body.classList.add('wiki-editing');
      message(''); draftCount(); structure?.render(); heading.focus();
    } catch (error) { message(error.message,true); }
    finally { setBusy(false); }
  }
  async function refreshArticleRevision() {
    if (!editor || dirty()) return;
    const activeEditor=editor, activePath=path, activeJSON=JSON.stringify(editor.getJSON()), activeTitle=heading.textContent;
    try {
      const page=await api('/pages?path='+encodeURIComponent(activePath));
      if(editor!==activeEditor || path!==activePath || heading.textContent!==activeTitle || JSON.stringify(editor.getJSON())!==activeJSON || dirty())return;
      if(page.body!==original || page.title!==baselineTitle){message(t('Содержимое заметки изменилось. Обновите страницу перед редактированием.'),true);return;}
      revision=page.revision;
    } catch(error) {message(error.message,true);}
  }
  function publication(commit) {
    if (publications.has(commit)) return publications.get(commit);
    const pending = (async () => {
      for (let attempt=0; attempt<120; attempt++) {
        if (attempt) await new Promise(resolve => setTimeout(resolve,5000));
        try {
          const result = await api('/publications/' + encodeURIComponent(commit));
          if (result.status === 'failed') { message(t('Изменения сохранены, но публикация не прошла. Обратитесь к администратору.'),true); return false; }
          if (result.status === 'published') return true;
        } catch {}
      }
      message(t('Изменения сохранены. Публикация ещё не подтверждена спустя 10 минут. Обратитесь к администратору.'),true);
      return false;
    })();
    publications.set(commit, pending);
    return pending;
  }

  save.addEventListener('click', async () => {
    if (busy) return;
    if (structure && !await structure.finishRename()) return;
    if (busy) return;
    setBusy(true); message('');
    try {
      await new Promise(resolve => { const fallback = setTimeout(resolve, 100); requestAnimationFrame(() => { clearTimeout(fallback); setTimeout(resolve, 0); }); });
      if (!stash()) return;
      const submitted = workspace.drafts();
      if (!submitted.length && !workspace.operations().length) { setBusy(false); stop(); return; }
      for (const draft of submitted) {
        if (!draft.title.trim() || draft.title.length > 200) { message(t('Укажите заголовки длиной до 200 символов.'),true); return; }
        if (draft.creating && !/^[a-z0-9]+(-[a-z0-9]+)*$/.test(draft.slug)) { message(t('В адресе новой заметки используйте латинские буквы, цифры и дефисы.'),true); return; }
      }
      const payload = {pages:batchPages(submitted),operations:workspace.operations(),uploads:workspace.uploads()};
      if ((payload.operations.length || submitted.some(draft => draft.creating)) && structure) payload.tree_revision = await structure.ensureRevision();
      const finalPath = workspace.virtualPath(path), currentDeleted = workspace.isDeleted(path);
      const result = await api('/batch',payload);
      workspace.acknowledge(submitted,payload.operations,payload.uploads);
      const index = submitted.findIndex(draft => draft.path === path);
      if (index >= 0 && editor && !result.pages[index]?.deleted) {
        const saved = submitted[index], published = result.pages[index];
        path = published.path; revision = published.revision; original = saved.body; originalJSON = editor.getJSON(); baselineTitle = saved.title; creating = false;
        fields?.remove(); fields = null;
        root.dataset.path = path;
        pageCache.set(path,Promise.resolve({title:baselineTitle,body:original,revision}));
        view.capture(baselineTitle,resolvePreviewLinks(editor.getHTML(),refs,path,basePath));
        if (published.url) history.replaceState(null,'',published.url);
      }
      setBusy(false);
      if (!stop()) return;
      if (payload.operations.length) {
        const flatten = nodes => nodes.flatMap(node=>[node,...flatten(node.children || [])]);
        const current = flatten(result.nodes || []).find(node=>(node.page_path || node.id)===finalPath);
        location.assign(currentDeleted ? basePath : current?.url || (finalPath === '_index.md' ? basePath : location.pathname)); return;
      }
    } catch(error) { message(error.message,true); }
    finally { setBusy(false); }
  });
  heading.addEventListener('input',()=>{if(editor){publicationState.reset();stash();}});
  heading.addEventListener('keydown', event => { if (editor && event.key==='Enter') {event.preventDefault();editor.commands.focus('start');} });
  heading.addEventListener('paste', event => { if (!editor) return; event.preventDefault(); document.execCommand('insertText',false,event.clipboardData.getData('text/plain').replace(/\s*\n\s*/g,' ')); });
  root.querySelector('[data-editor-open]').addEventListener('click',()=>open(false));
  root.querySelector('[data-editor-cancel]').addEventListener('click',stop);
  window.addEventListener('pagehide',stash);
  window.addEventListener('beforeunload',event=>{stash();if(stashFailed){event.preventDefault();event.returnValue='';}});
  document.addEventListener('click',event=>{ const link=event.target.closest('a[href]'); if (workspace.active() && link && new URL(link.href,location.href).origin===location.origin && !stash()) event.preventDefault(); },true);
  Promise.resolve(session).then(session=>{
    if(!session.writable || !session.csrf_token)return;
    csrf=session.csrf_token;root.hidden=false;actions.hidden=false;
    loadPage(path).then(page=>{
      if (workspace.active()) return open(false);
      const hydrationGeneration = generation;
      return view.hydratePage({api,path,page,canApply:()=>!busy && !editor && generation===hydrationGeneration});
    }).catch(error=>message(error.message,true));
    initializeTree({api, workspace, begin:()=>{
      if (!stash()) return false;
      workspace.start(); actions.hidden=true; editbar.hidden=false; document.body.classList.add('wiki-editing'); return true;
    }, dirty:()=>busy, currentPath:()=>workspace.virtualPath(path), message, changed:async()=>{draftCount();if(fields?.querySelector('input'))fields.querySelector('input').disabled=workspace.slugLocked(path);structure?.render();}, openPage:async seed=>{
      if(editor && !stop(false))return;
      if(seed.draftPath){path=seed.draftPath;await open(false);}else await open(true,seed);
    }, renamed:(source,title)=>{ if (workspace.originPath(source + '/_index.md') === path) { heading.textContent=title; if(editor)stash(); } }, removed:async()=>{ if (workspace.isDeleted(path)) { generation++; editor?.destroy(); editor=null; toolbar?.remove(); fields?.remove(); linkForm?.remove(); heading.removeAttribute('contenteditable'); location.assign(basePath); } }, moved:()=>{draftCount();}, publication:commit=>publication(commit)}).then(value=>{structure=value;}).catch(error=>message(error.message,true));
    const mobile=document.querySelector('.mobile-actions');const media=matchMedia('(max-width: 900px)');
    const position=()=>{if(media.matches&&mobile)mobile.prepend(actions);else root.prepend(actions);};media.addEventListener('change',position);position();
  }).catch(()=>{});
}
