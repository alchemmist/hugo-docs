import test from 'node:test';
import assert from 'node:assert/strict';
import { JSDOM } from 'jsdom';
import { initializeTree } from './tree.js';

globalThis.requestAnimationFrame = callback => setTimeout(callback, 16);
globalThis.cancelAnimationFrame = clearTimeout;

const fixture = () => ({revision:'r1',nodes:[{id:'ai',title:'AI',kind:'folder',url:'/ai/',children:[{id:'ai/chat.md',title:'Chat',kind:'page',url:'/ai/chat/'}]}]});
async function setup(isDirty=false, structureDirty=isDirty) {
  const dom=new JSDOM('<nav class="page-tree"><a class="overview">Обзор</a><ul class="nav-root"><li>Static</li></ul></nav>',{url:'https://wiki.example/'});
  globalThis.document=dom.window.document;document.documentElement.lang='ru';globalThis.Option=dom.window.Option;
  const calls=[],messages=[],moves=[],events=[];let seed;const data=fixture();let resolvePublication;
  const controller=await initializeTree({api:async (endpoint,payload)=>{calls.push({endpoint,data:payload});return {...data,commit:'c1'};},dirty:()=>isDirty,structureDirty:()=>structureDirty,currentPath:()=> 'ai/chat.md',openPage:async value=>{seed=value;},moved:(source,target)=>{moves.push({source,target});events.push('moved');},changed:async()=>events.push('changed'),message:text=>messages.push(text),publication:()=>new Promise(resolve=>{resolvePublication=resolve;})});
  await controller.ready;
  return {dom,calls,messages,moves,events,data,controller,publish:()=>resolvePublication(true),getSeed:()=>seed};
}
const click = label => document.querySelector(`[aria-label="${label}"]`).click();
const tick = () => new Promise(resolve=>setTimeout(resolve,0));
const drag = (state,source,target,y=0) => {
  const row=document.querySelector(`[data-node-id="${source}"] > .nav-row`);
  const start=new state.dom.window.Event('dragstart',{bubbles:true,cancelable:true});
  Object.defineProperty(start,'dataTransfer',{value:{setData(){},effectAllowed:''}});row.dispatchEvent(start);
  const drop=new state.dom.window.MouseEvent('drop',{bubbles:true,cancelable:true,clientY:y});target.dispatchEvent(drop);
};
test('root toolbar contains only two named SVG icons without row controls',async()=>{
  await setup();const root=document.querySelector('.wiki-tree-root');
  assert.equal(root.querySelectorAll('button').length,2);assert.equal(root.querySelectorAll('svg').length,2);assert.equal(root.textContent,'');
  assert.equal(document.querySelector('.wiki-tree-controls'),null);assert.equal(document.querySelector('select'),null);
  assert.equal(document.querySelector('[data-node-id="ai/chat.md"] a').draggable,false);
});
test('new note opens article editor directly at root without publishing an empty page',async()=>{
  const state=await setup();click('Новая заметка');await tick();
  assert.deepEqual(state.getSeed(),{parent:'',title:'Новая заметка',slug:''});assert.equal(state.calls.length,1);
  assert.equal(document.querySelector('.wiki-tree-create'),null);
});
test('folder creation carries tree revision and always targets root',async()=>{
  const state=await setup();click('Новая папка');
  assert.equal(document.querySelector('select'),null);
  document.querySelector('[aria-label="Название новой папки"]').value='Folder';document.querySelector('[aria-label="Адрес новой папки"]').value='folder';click('Создать папку');await tick();
  assert.deepEqual(state.calls[1],{endpoint:'/folders',data:{parent:'',title:'Folder',slug:'folder',revision:'r1'}});assert.deepEqual(state.events,['changed']);
});
test('dirty article blocks new notes, folders and dragging',async()=>{
  const state=await setup(true);click('Новая папка');click('Новая заметка');
  drag(state,'ai/chat.md',document.querySelector('.wiki-tree-root'));await tick();
  assert.equal(state.getSeed(),undefined);assert.equal(state.calls.length,1);assert.equal(document.querySelector('.wiki-tree-create'),null);assert.match(state.messages.at(-1),/опубликуйте/i);
});
test('drag to root moves note with revision and updates article path',async()=>{
  const state=await setup();drag(state,'ai/chat.md',document.querySelector('.wiki-tree-root'));await tick();
  assert.deepEqual(state.calls[1],{endpoint:'/move',data:{source:'ai/chat.md',target_parent:'',before:null,revision:'r1'}});
  assert.deepEqual(state.moves,[{source:'ai/chat.md',target:'chat.md'}]);assert.deepEqual(state.events,['moved','changed']);
  assert.equal(document.querySelector('.wiki-tree-dragging'),null);
});
test('drag positions support before, after and inside folder',async()=>{
  for (const [y,parent,before] of [[10,'','ai'],[90,'','other.md'],[50,'ai',null]]) {
    const state=await setup();state.data.nodes.push({id:'other.md',kind:'page',title:'Other',url:'/other/'},{id:'note.md',kind:'page',title:'Note',url:'/note/'});await state.controller.refresh();
    const target=document.querySelector('[data-node-id="ai"] > .nav-row');target.getBoundingClientRect=()=>({top:0,height:100});
    drag(state,'note.md',target,y);await tick();
    assert.deepEqual(state.calls.at(-1),{endpoint:'/move',data:{source:'note.md',target_parent:parent,before,revision:'r1'}});
  }
});

test('folder title only expands and never links to a nonexistent section page',async()=>{
  await setup();const row=document.querySelector('[data-node-id="ai"] > .nav-row');assert.equal(row.querySelector('a'),null);assert.equal(row.querySelector('svg path').getAttribute('d'),'m9 5 7 7-7 7');click('Раскрыть AI');assert.equal(document.querySelector('[data-node-id="ai"] > ul').hidden,true);
});
test('new page remains unlinked until its publication completes',async()=>{
  const state=await setup();state.data.nodes[0].children.push({id:'ai/new.md',kind:'page',title:'New',url:'/ai/new/'});await state.controller.refresh({pendingPage:'ai/new.md',commit:'c2'});
  assert.equal(document.querySelector('[data-node-id="ai/new.md"] a').hasAttribute('href'),false);state.publish();await tick();assert.equal(document.querySelector('[data-node-id="ai/new.md"] a').getAttribute('href'),'/ai/new/');
});

test('creation controls appear above overview before a slow tree request completes',async()=>{
  const dom=new JSDOM('<nav class="page-tree"><a class="overview">Обзор</a><ul class="nav-root"><li>Static</li></ul></nav>',{url:'https://wiki.example/'});
  globalThis.document=dom.window.document;document.documentElement.lang='ru';globalThis.Option=dom.window.Option;
  let release,seed;const response=new Promise(resolve=>{release=resolve;});
  const controller=await initializeTree({api:()=>response,dirty:()=>false,currentPath:()=>'',openPage:async value=>{seed=value;},moved:()=>{},message:()=>{},publication:async()=>true});
  assert.equal(document.querySelector('.page-tree').firstElementChild.className,'wiki-tree-root');
  assert.match(document.querySelector('.nav-root').textContent,/Static/);
  click('Новая заметка');await tick();assert.equal(seed.parent,'');
  click('Новая папка');const title=document.querySelector('[aria-label="Название новой папки"]');title.value='Keep this';title.focus();
  release(fixture());await controller.ready;
  assert.equal(document.querySelector('[aria-label="Название новой папки"]'),title);
  assert.equal(title.value,'Keep this');assert.equal(document.activeElement,title);
});

test('folder submission waits for the initial revision and does not duplicate the tree fetch',async()=>{
  const dom=new JSDOM('<nav class="page-tree"><a>Обзор</a><ul class="nav-root"></ul></nav>',{url:'https://wiki.example/'});
  globalThis.document=dom.window.document;document.documentElement.lang='ru';globalThis.Option=dom.window.Option;
  let release;const response=new Promise(resolve=>{release=resolve;});const calls=[];
  const controller=await initializeTree({api:async(endpoint,payload)=>{calls.push({endpoint,payload});return endpoint==='/tree'?response:{...fixture(),commit:'c1'};},dirty:()=>false,currentPath:()=>'',openPage:()=>{},moved:()=>{},message:()=>{},publication:async()=>true});
  click('Новая папка');document.querySelector('[aria-label="Название новой папки"]').value='Folder';document.querySelector('[aria-label="Адрес новой папки"]').value='folder';click('Создать папку');await tick();
  assert.equal(calls.length,1);
  release(fixture());await controller.ready;await tick();
  assert.equal(calls.length,2);assert.equal(calls[1].payload.revision,'r1');
});

test('failed initial tree loading keeps controls and retries on demand',async()=>{
  const dom=new JSDOM('<nav class="page-tree"><a>Обзор</a><ul class="nav-root"><li>Static</li></ul></nav>',{url:'https://wiki.example/'});
  globalThis.document=dom.window.document;document.documentElement.lang='ru';globalThis.Option=dom.window.Option;let count=0;
  const controller=await initializeTree({api:async()=>{if(++count===1)throw new Error('Offline');return fixture();},dirty:()=>false,currentPath:()=>'',openPage:()=>{},moved:()=>{},message:()=>{},publication:async()=>true});
  await controller.ready;assert.equal(document.querySelector('.wiki-tree-root').children.length,2);assert.match(document.querySelector('.nav-root').textContent,/Static/);
  assert.equal(await controller.ensureRevision(),'r1');assert.equal(count,2);
});

function pointerEvent(state, type, target, x, y) {
  const event = new state.dom.window.MouseEvent(type, {bubbles:true, cancelable:true, clientX:x, clientY:y, button:0});
  Object.defineProperty(event, 'pointerId', {value:1}); target.dispatchEvent(event); return event;
}
test('pointer dragging starts from folder button and moves the folder beside another folder', async()=>{
  const state=await setup();state.data.nodes.push({id:'help',kind:'folder',title:'Help',children:[]});await state.controller.refresh();
  const source=document.querySelector('[data-node-id="ai"] button'),target=document.querySelector('[data-node-id="help"] > .nav-row');
  target.getBoundingClientRect=()=>({top:100,height:32});document.elementFromPoint=()=>target.querySelector('span');
  pointerEvent(state,'pointerdown',source,10,10);pointerEvent(state,'pointermove',source,30,130);
  assert.equal(document.querySelector('[data-node-id="help"]').dataset.drop,'after');
  assert.match(document.querySelector('.wiki-tree-drag-hint').textContent,/После/);
  pointerEvent(state,'pointerup',source,30,130);await tick();
  assert.deepEqual(state.calls.at(-1),{endpoint:'/move',data:{source:'ai',target_parent:'',before:null,revision:'r1'}});
});
test('pointer dragging from note text places it inside a folder and can be cancelled',async()=>{
  const state=await setup();state.data.nodes.push({id:'help',kind:'folder',title:'Help',children:[]});await state.controller.refresh();
  const source=document.querySelector('[data-node-id="ai/chat.md"] a'),target=document.querySelector('[data-node-id="help"] > .nav-row');
  target.getBoundingClientRect=()=>({top:100,height:32});document.elementFromPoint=()=>target;
  pointerEvent(state,'pointerdown',source,10,10);pointerEvent(state,'pointermove',source,20,116);
  assert.equal(target.dataset.drop,'inside');pointerEvent(state,'pointercancel',source,20,116);
  assert.equal(document.querySelector('[data-drop]'),null);assert.equal(state.calls.filter(c=>c.endpoint==='/move').length,0);
  pointerEvent(state,'pointerdown',source,10,10);pointerEvent(state,'pointermove',source,20,116);pointerEvent(state,'pointerup',source,20,116);await tick();
  assert.deepEqual(state.calls.at(-1),{endpoint:'/move',data:{source:'ai/chat.md',target_parent:'help',before:null,revision:'r1'}});
});
test('pointer move under threshold remains a click and cyclic folder drops are rejected',async()=>{
  const state=await setup();const source=document.querySelector('[data-node-id="ai"] button'),target=document.querySelector('[data-node-id="ai/chat.md"] > .nav-row');
  document.elementFromPoint=()=>target;target.getBoundingClientRect=()=>({top:100,height:32});
  pointerEvent(state,'pointerdown',source,10,10);pointerEvent(state,'pointermove',source,11,12);pointerEvent(state,'pointerup',source,11,12);
  assert.equal(document.querySelector('.wiki-tree-dragging'),null);
  pointerEvent(state,'pointerdown',source,10,10);pointerEvent(state,'pointermove',source,20,116);pointerEvent(state,'pointerup',source,20,116);await tick();
  assert.equal(state.calls.filter(c=>c.endpoint==='/move').length,0);
});

test('reorders pages both ways within a folder and moves nested folders beside root folders',async()=>{
  for (const [source,targetId,y,parent,before] of [
    ['ai/last.md','ai/chat.md',101,'ai','ai/chat.md'],
    ['ai/chat.md','ai/last.md',130,'ai','ai/nested'],
    ['ai/nested','help',101,'','help'],
  ]) {
    const state=await setup();state.data.nodes[0].children.push({id:'ai/last.md',kind:'page',title:'Last',url:'/ai/last/'},{id:'ai/nested',kind:'folder',title:'Nested',children:[]});state.data.nodes.push({id:'help',kind:'folder',title:'Help',children:[]});await state.controller.refresh();
    const origin=document.querySelector(`[data-node-id="${source}"] > .nav-row`),target=document.querySelector(`[data-node-id="${targetId}"] > .nav-row`);
    target.getBoundingClientRect=()=>({top:100,height:32});document.elementFromPoint=()=>target;
    pointerEvent(state,'pointerdown',origin,10,10);pointerEvent(state,'pointermove',origin,20,y);pointerEvent(state,'pointerup',origin,20,y);await tick();
    assert.deepEqual(state.calls.at(-1),{endpoint:'/move',data:{source,target_parent:parent,before,revision:'r1'}});
  }
});

test('hover opens a closed folder without replacing the active drag nodes',async()=>{
  const state=await setup();state.data.nodes.push({id:'help',kind:'folder',title:'Help',children:[{id:'help/guide.md',kind:'page',title:'Guide',url:'/help/guide/'}]});await state.controller.refresh();
  const source=document.querySelector('[data-node-id="ai/chat.md"] a'),target=document.querySelector('[data-node-id="help"] > .nav-row');
  target.getBoundingClientRect=()=>({top:100,height:32});document.elementFromPoint=()=>target;
  const children=target.parentElement.querySelector(':scope > ul');assert.equal(children.hidden,true);
  pointerEvent(state,'pointerdown',source,10,10);pointerEvent(state,'pointermove',source,20,116);
  await new Promise(resolve=>setTimeout(resolve,700));
  assert.equal(children.hidden,false);assert.equal(document.querySelector('[data-node-id="help"] > .nav-row'),target);
  pointerEvent(state,'pointercancel',source,20,116);
  assert.equal(state.calls.filter(c=>c.endpoint==='/move').length,0);
});

test('workspace drafts block structural mutations but allow adding another draft and navigation',async()=>{
  const state=await setup(false,true);click('Новая папка');
  assert.equal(document.querySelector('.wiki-tree-create'),null);
  click('Новая заметка');await tick();assert.equal(state.getSeed().title,'Новая заметка');
  const event=new state.dom.window.MouseEvent('click',{bubbles:true,cancelable:true});
  document.querySelector('[data-node-id="ai/chat.md"] a').dispatchEvent(event);
  assert.equal(event.defaultPrevented,false);
  drag(state,'ai/chat.md',document.querySelector('.wiki-tree-root'));await tick();
  assert.equal(state.calls.length,1);assert.match(state.messages.at(-1),/структуры/);
});

test('workspace stages folder and move with edited text without API writes',async()=>{
  const {createWorkspace,batchPages}=await import('./workspace.js');
  const data=new Map(),workspace=createWorkspace({getItem:key=>data.get(key),setItem:(key,value)=>data.set(key,value)});
  workspace.start();workspace.put({path:'ai/chat.md',title:'Edited',body:'New text',revision:'page1'});
  const dom=new JSDOM('<nav class="page-tree"><a>Обзор</a><ul class="nav-root"></ul></nav>',{url:'https://wiki.example/'});
  globalThis.document=dom.window.document;document.documentElement.lang='ru';
  const calls=[];
  const controller=await initializeTree({api:async(endpoint,payload)=>{calls.push({endpoint,payload});return fixture();},workspace,dirty:()=>false,structureDirty:()=>true,begin:()=>true,currentPath:()=>workspace.virtualPath('ai/chat.md'),openPage:async()=>{},moved:()=>{},message:()=>{},publication:async()=>true});
  await controller.ready;
  click('Новая папка');
  document.querySelector('[aria-label="Название новой папки"]').value='Folder';document.querySelector('[aria-label="Адрес новой папки"]').value='folder';click('Создать папку');await tick();
  const target=document.querySelector('[data-node-id="folder"] > .nav-row');
  target.getBoundingClientRect=()=>({top:0,height:40});
  drag({dom},'ai/chat.md',target,20);await tick();
  assert.equal(calls.length,1);
  assert.deepEqual(workspace.operations(),[{type:'folder',parent:'',title:'Folder',slug:'folder'},{type:'move',source:'ai/chat.md',target_parent:'folder',before:null}]);
  assert.equal(document.querySelector('[data-node-id="folder/chat.md"] a').pathname,'/ai/chat/');
  assert.equal(batchPages(workspace.drafts())[0].path,'ai/chat.md');
  workspace.discard();await controller.reset();
  assert.equal(document.querySelector('[data-node-id="folder"]'),null);
  assert.equal(calls.every(call=>call.payload===undefined),true);
});

test('reading mode blocks pointer and native dragging before and after editing',async()=>{
  const {createWorkspace}=await import('./workspace.js');
  const data=new Map(),workspace=createWorkspace({getItem:key=>data.get(key),setItem:(key,value)=>data.set(key,value)});
  const dom=new JSDOM('<nav class="page-tree"><ul class="nav-root"></ul></nav>',{url:'https://wiki.example/'});
  globalThis.document=dom.window.document;document.documentElement.lang='ru';
  const controller=await initializeTree({api:async()=>fixture(),workspace,dirty:()=>false,currentPath:()=> 'ai/chat.md',openPage:()=>{},moved:()=>{},message:()=>{},publication:async()=>true});
  await controller.ready;
  const gesture=()=>{
    const source=document.querySelector('[data-node-id="ai/chat.md"] a'),target=document.querySelector('.wiki-tree-root');
    document.elementFromPoint=()=>target;
    pointerEvent({dom},'pointerdown',source,10,100);pointerEvent({dom},'pointermove',source,30,10);pointerEvent({dom},'pointerup',source,30,10);
  };
  gesture();drag({dom},'ai/chat.md',document.querySelector('.wiki-tree-root'));await tick();
  assert.equal(workspace.active(),false);assert.deepEqual(workspace.operations(),[]);assert.equal(document.querySelector('.wiki-tree-dragging'),null);
  workspace.start();gesture();await tick();assert.equal(workspace.operations().length,1);
  workspace.discard();await controller.reset();gesture();await tick();
  assert.deepEqual(workspace.operations(),[]);assert.equal(workspace.active(),false);
});

async function deleteSetup(active=true) {
  const {createWorkspace}=await import('./workspace.js');
  const data=new Map(),workspace=createWorkspace({getItem:key=>data.get(key),setItem:(key,value)=>data.set(key,value)});
  if(active)workspace.start();
  const dom=new JSDOM('<nav class="page-tree"><ul class="nav-root"></ul></nav>',{url:'https://wiki.example/'});
  globalThis.document=dom.window.document;document.documentElement.lang='ru';
  const calls=[],removed=[];
  const controller=await initializeTree({api:async(endpoint,payload)=>{calls.push({endpoint,payload});return fixture();},workspace,dirty:()=>false,currentPath:()=> 'ai/chat.md',openPage:()=>{},moved:()=>{},removed:node=>removed.push(node.id),message:()=>{},publication:async()=>true});
  await controller.ready;
  return {dom,workspace,controller,calls,removed};
}
test('delete controls exist only in editing mode and page deletion stays staged until publication',async()=>{
  const state=await deleteSetup(false);
  assert.equal(document.querySelector('.wiki-tree-delete'),null);
  state.workspace.start();state.controller.render();
  click('Удалить заметку Chat');await tick();
  assert.equal(document.querySelector('[data-node-id="ai/chat.md"]'),null);
  assert.deepEqual(state.workspace.operations(),[{type:'delete',source:'ai/chat.md'}]);
  assert.deepEqual(state.removed,['ai/chat.md']);assert.equal(state.calls.length,1);
  state.workspace.discard();await state.controller.reset();
  assert.ok(document.querySelector('[data-node-id="ai/chat.md"]'));
  assert.equal(document.querySelector('.wiki-tree-delete'),null);
});
test('folder deletion requires a second click and confirmation resets on leave escape focus and another row',async()=>{
  const state=await deleteSetup();
  const row=document.querySelector('[data-node-id="ai"] > .nav-row');
  const arm=()=>{click('Удалить папку AI');assert.match(document.querySelector('[role="tooltip"]').textContent,/все заметки/);assert.deepEqual(state.workspace.operations(),[]);};
  arm();assert.equal(document.querySelector('[role="tooltip"]').parentElement,document.body);document.querySelector('.page-tree').dispatchEvent(new state.dom.window.Event('scroll'));assert.equal(document.querySelector('[role="tooltip"]'),null);
  arm();state.dom.window.dispatchEvent(new state.dom.window.Event('resize'));assert.equal(document.querySelector('[role="tooltip"]'),null);
  arm();row.dispatchEvent(new state.dom.window.Event('pointerleave'));assert.equal(document.querySelector('[role="tooltip"]'),null);
  arm();document.dispatchEvent(new state.dom.window.KeyboardEvent('keydown',{key:'Escape'}));assert.equal(document.querySelector('[role="tooltip"]'),null);
  arm();row.dispatchEvent(new state.dom.window.FocusEvent('focusout',{relatedTarget:document.body}));assert.equal(document.querySelector('[role="tooltip"]'),null);
  arm();document.querySelector('[data-node-id="ai/chat.md"] > .nav-row').dispatchEvent(new state.dom.window.Event('pointerenter'));assert.equal(document.querySelector('[role="tooltip"]'),null);
  arm();click('Подтвердить удаление папки AI');await tick();
  assert.equal(document.querySelector('[data-node-id="ai"]'),null);
  assert.deepEqual(state.workspace.operations(),[{type:'delete',source:'ai'}]);assert.equal(state.calls.length,1);
});
test('delete button does not start dragging toggle a folder or retain confirmation after leaving edit mode',async()=>{
  const state=await deleteSetup(),button=document.querySelector('[aria-label="Удалить папку AI"]');
  const children=document.querySelector('[data-node-id="ai"] > ul'),wasHidden=children.hidden;
  pointerEvent(state,'pointerdown',button,10,10);pointerEvent(state,'pointermove',button,30,30);pointerEvent(state,'pointerup',button,30,30);
  assert.equal(document.querySelector('.wiki-tree-dragging'),null);
  const event=new state.dom.window.Event('dragstart',{bubbles:true,cancelable:true});button.dispatchEvent(event);assert.equal(event.defaultPrevented,true);
  button.click();assert.equal(children.hidden,wasHidden);
  state.workspace.discard();state.controller.render();
  assert.equal(document.querySelector('[role="tooltip"]'),null);assert.equal(document.querySelector('.wiki-tree-delete'),null);
});

test('folder rename is editing-only and stages a title without changing paths or toggling',async()=>{
  const state=await deleteSetup(false);
  assert.equal(document.querySelector('.wiki-tree-rename'),null);
  state.workspace.start();state.controller.render();
  assert.equal(document.querySelectorAll('.wiki-tree-rename').length,1);
  click('Удалить папку AI');click('Переименовать папку AI');
  assert.equal(document.querySelector('[role="tooltip"]'),null);
  const input=document.querySelector('.wiki-tree-rename-input');
  assert.equal(document.activeElement,input);
  pointerEvent(state,'pointerdown',input,10,10);pointerEvent(state,'pointermove',input,30,30);
  assert.equal(document.querySelector('.wiki-tree-dragging'),null);
  input.value='  Models  ';
  input.dispatchEvent(new state.dom.window.KeyboardEvent('keydown',{key:'Enter',bubbles:true}));
  await tick();
  assert.deepEqual(state.workspace.operations(),[{type:'rename',source:'ai',title:'Models'}]);
  assert.equal(state.workspace.tree().nodes[0].id,'ai');
  assert.ok(document.querySelector('[aria-label="Переименовать папку Models"]'));
  assert.equal(state.calls.length,1);
});

test('rename escape and edit-mode exit cancel while blur saves once and unchanged names do nothing',async()=>{
  const state=await deleteSetup();
  click('Переименовать папку AI');
  let input=document.querySelector('.wiki-tree-rename-input');input.value='Cancel';
  input.dispatchEvent(new state.dom.window.KeyboardEvent('keydown',{key:'Escape',bubbles:true}));
  assert.deepEqual(state.workspace.operations(),[]);
  click('Переименовать папку AI');
  input=document.querySelector('.wiki-tree-rename-input');
  input.dispatchEvent(new state.dom.window.FocusEvent('blur'));
  await tick();assert.deepEqual(state.workspace.operations(),[]);
  click('Переименовать папку AI');
  input=document.querySelector('.wiki-tree-rename-input');input.value='Models';
  input.dispatchEvent(new state.dom.window.FocusEvent('blur'));
  input.dispatchEvent(new state.dom.window.FocusEvent('blur'));
  await tick();assert.equal(state.workspace.operations().length,1);
  click('Переименовать папку Models');
  document.querySelector('.wiki-tree-rename-input').value='Discarded';
  state.workspace.discard();state.controller.render();
  assert.equal(document.querySelector('.wiki-tree-rename-input'),null);
  assert.deepEqual(state.workspace.operations(),[]);
});

test('publication flush validates focused rename and waits for a single staged operation',async()=>{
  const state=await deleteSetup();
  click('Переименовать папку AI');
  const input=document.querySelector('.wiki-tree-rename-input');
  input.value=' ';
  assert.equal(await state.controller.finishRename(),false);
  assert.equal(document.activeElement,input);
  assert.deepEqual(state.workspace.operations(),[]);
  input.value='Published name';
  input.dispatchEvent(new state.dom.window.FocusEvent('blur'));
  assert.equal(await state.controller.finishRename(),true);
  assert.equal(await state.controller.finishRename(),true);
  assert.deepEqual(state.workspace.operations(),[{type:'rename',source:'ai',title:'Published name'}]);
  click('Переименовать папку Published name');
  assert.equal(await state.controller.finishRename(),true);
  assert.equal(state.workspace.operations().length,1);
});

test('tree controls follow English page language', async () => {
  const state = await setup();
  document.documentElement.lang = 'en';
  state.controller.render();
  assert.ok(document.querySelector('[aria-label="Expand AI"]'));
  document.documentElement.lang = 'ru';
});

test('hydration preserves open unrelated branches and explicitly closed current ancestors',async()=>{
  const dom=new JSDOM('<nav class="page-tree"><ul class="nav-root"><li><button class="tree-toggle" data-section="/ai" aria-expanded="false">AI</button></li><li><button class="tree-toggle" data-section="/other" aria-expanded="true">Other</button></li></ul></nav>',{url:'https://wiki.example/'});
  globalThis.document=dom.window.document;
  const data=fixture();data.nodes.push({id:'other',title:'Other',kind:'folder',children:[{id:'other/a.md',title:'A',kind:'page',url:'/other/a/'}]});
  const controller=await initializeTree({api:async()=>data,dirty:()=>false,currentPath:()=> 'ai/chat.md',message:()=>{}});
  await controller.ready;
  assert.equal(document.querySelector('[data-section="ai"]').getAttribute('aria-expanded'),'false');
  assert.equal(document.querySelector('[data-section="other"]').getAttribute('aria-expanded'),'true');
  controller.render();
  assert.equal(document.querySelector('[data-section="other"]').getAttribute('aria-expanded'),'true');
});

test('pending hydration reads the latest static toggles and shared preferences',async()=>{
  const dom=new JSDOM('<nav class="page-tree"><ul class="nav-root"><li><button class="tree-toggle" data-section="/ai" aria-expanded="true">AI</button></li></ul></nav>',{url:'https://wiki.example/'});
  globalThis.document=dom.window.document;
  const preferences=new Map();const normalize=id=>id.replace(/^\/+|\/+$/g,'');
  dom.window.WikiTreeState={normalize,get:(id,fallback)=>preferences.get(normalize(id))??fallback,set:(id,value)=>preferences.set(normalize(id),value)};
  let resolve;const controller=await initializeTree({api:()=>new Promise(done=>{resolve=done;}),dirty:()=>false,currentPath:()=> 'ai/chat.md',message:()=>{}});
  document.querySelector('.tree-toggle').setAttribute('aria-expanded','false');
  preferences.set('ai',false);
  resolve(fixture());await controller.ready;
  const toggle=document.querySelector('[data-section="ai"]');
  assert.equal(toggle.getAttribute('aria-expanded'),'false');
  toggle.click();
  assert.equal(preferences.get('ai'),true);
});

test('rerender atomically replaces the tree while preserving scroll and focused folder',async()=>{
  const state=await setup();const nav=document.querySelector('.page-tree');
  nav.scrollTop=87;document.querySelector('.tree-toggle').focus();
  const records=[];const observer=new state.dom.window.MutationObserver(items=>records.push(...items));observer.observe(nav,{childList:true});
  state.controller.render();await tick();observer.disconnect();
  assert.equal(nav.scrollTop,87);
  assert.equal(document.activeElement.dataset.section,'ai');
  assert.equal(records.length,1);
  assert.equal(records[0].removedNodes.length,1);
  assert.equal(records[0].addedNodes.length,1);
});

test('hydration persists default open ancestors without storing default closed branches',async()=>{
  const dom=new JSDOM('<nav class="page-tree"><ul class="nav-root"></ul></nav>',{url:'https://wiki.example/'});
  globalThis.document=dom.window.document;
  const preferences=new Map();const normalize=id=>id.replace(/^\/+|\/+$/g,'');
  dom.window.WikiTreeState={normalize,get:(id,fallback)=>preferences.get(normalize(id))??fallback,set:(id,value)=>preferences.set(normalize(id),value)};
  const data=fixture();data.nodes.push({id:'other',title:'Other',kind:'folder',children:[]});
  const controller=await initializeTree({api:async()=>data,dirty:()=>false,currentPath:()=> 'ai/chat.md',message:()=>{}});
  await controller.ready;controller.render();
  assert.equal(preferences.get('ai'),true);
  assert.equal(preferences.has('other'),false);
  document.querySelector('[data-section="ai"]').click();
  assert.equal(preferences.get('ai'),false);
});
