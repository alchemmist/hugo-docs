globalThis.document = {documentElement:{lang:'ru'}};
import test from 'node:test';
import assert from 'node:assert/strict';
import {createWorkspace, batchPages} from './workspace.js';
const storage = () => { const data = new Map(); return {getItem:key=>data.get(key),setItem:(key,value)=>data.set(key,value)}; };
const page = {path:'start/a.md',title:'A',body:'Body',revision:'abc'};
test('workspace survives page navigation and reload with multiple drafts', () => {
  const disk = storage(), first = createWorkspace(disk);
  first.start(); first.put(page);
  const second = createWorkspace(disk);
  second.put({...page,path:'help/b.md',title:'B'});
  assert.equal(second.active(),true);
  assert.equal(createWorkspace(disk).drafts().length,2);
  assert.deepEqual(second.get(page.path),page);
});
test('batch preserves revisions and supports root new pages', () => {
  assert.deepEqual(batchPages([page,{path:'draft:new',creating:true,slug:'new',title:'New',body:'Text'}]),[page,{section:'',slug:'new',title:'New',body:'Text'}]);
});
test('conflict leaves drafts intact and successful acknowledgement preserves newer edits', () => {
  const workspace = createWorkspace(storage()); workspace.start(); workspace.put(page);
  const submitted = workspace.drafts();
  assert.deepEqual(workspace.drafts(),submitted);
  workspace.put({...page,body:'Edited while publishing'});
  workspace.acknowledge(submitted);
  assert.equal(workspace.drafts().length,1);
  workspace.acknowledge(workspace.drafts());
  assert.equal(workspace.drafts().length,0);
  assert.equal(workspace.active(),true);
});
test('folder move remaps nested drafts and discard exits workspace', () => {
  const workspace = createWorkspace(storage()); workspace.start(); workspace.put(page);
  workspace.move('start','help/start');
  assert.equal(workspace.get('help/start/a.md').body,'Body');
  workspace.discard(); assert.equal(workspace.active(),false); assert.equal(workspace.drafts().length,0);
});
test('failed persistence never acknowledges unsaved in-memory updates', () => {
  const disk = storage(), workspace = createWorkspace(disk);
  workspace.start(); workspace.put(page);
  disk.setItem = () => { throw new Error('quota'); };
  assert.throws(()=>workspace.put({...page,body:'Unsaved changes'}),/quota/);
  assert.deepEqual(workspace.get(page.path),page);
  assert.throws(()=>workspace.remove(page.path),/quota/);
  assert.deepEqual(workspace.get(page.path),page);
  assert.throws(()=>workspace.acknowledge([page]),/quota/);
  assert.deepEqual(workspace.get(page.path),page);
  assert.throws(()=>workspace.discard(),/quota/);
  assert.equal(workspace.active(),true);
});
const tree = () => ({revision:'tree1',nodes:[
  {id:'start',path:'start',page_path:'start/_index.md',kind:'folder',title:'Start',url:'/start/',children:[{id:'start/a.md',path:'start/a.md',page_path:'start/a.md',kind:'page',title:'A',url:'/start/a/'}]},
  {id:'help',path:'help',page_path:'help/_index.md',kind:'folder',title:'Help',url:'/help/',children:[]}
]});
test('combined workspace persists nested folder moves, order, and original draft identity', () => {
  const disk = storage(), workspace = createWorkspace(disk);
  workspace.start(); workspace.seedTree(tree()); workspace.put(page);
  workspace.stage({type:'folder',parent:'help',slug:'nested',title:'Nested'});
  workspace.stage({type:'move',source:'start',target_parent:'help/nested',before:null});
  workspace.stage({type:'move',source:'help/nested/start/a.md',target_parent:'help',before:'help/nested'});
  const restored = createWorkspace(disk);
  assert.equal(restored.operations().length,3);
  assert.equal(restored.originPath('help/a.md'),'start/a.md');
  assert.equal(restored.virtualPath('start/a.md'),'help/a.md');
  assert.equal(restored.get('help/a.md').body,'Body');
  restored.put({...page,path:'help/a.md',body:'Changed'});
  assert.equal(restored.drafts()[0].path,'start/a.md');
  assert.deepEqual(restored.tree().nodes[0].children.map(node=>node.id),['help/a.md','help/nested']);
  assert.equal(restored.hasChanges(),true);
  assert.equal(batchPages(restored.drafts())[0].path,'start/a.md');
});
test('failed structure validation leaves the persisted workspace unchanged', () => {
  const workspace = createWorkspace(storage()); workspace.seedTree(tree());
  const before = workspace.tree();
  for (const operation of [
    {type:'move',source:'start',target_parent:'start',before:null},
    {type:'move',source:'start/a.md',target_parent:'missing',before:null},
    {type:'move',source:'start/a.md',target_parent:'help',before:'missing'},
    {type:'folder',parent:'',slug:'help',title:'Duplicate'}
  ]) assert.throws(()=>workspace.stage(operation));
  assert.deepEqual(workspace.tree(),before);
  assert.deepEqual(workspace.operations(),[]);
});
test('new root pages can move beside folders and publish at original creation path', () => {
  const workspace = createWorkspace(storage());
  workspace.put({path:'draft:new',creating:true,slug:'new',title:'New',body:'Text'});
  workspace.seedTree(tree());
  workspace.stage({type:'move',source:'new.md',target_parent:'start',before:'start/a.md'});
  assert.equal(workspace.originPath('start/new.md'),'draft:new');
  assert.equal(workspace.virtualPath('draft:new'),'start/new.md');
  assert.deepEqual(batchPages(workspace.drafts()),[{section:'',slug:'new',title:'New',body:'Text'}]);
  assert.throws(()=>workspace.put({...workspace.get('draft:new'),slug:'renamed'}));
  assert.equal(workspace.get('draft:new').slug,'new');
  workspace.acknowledge(workspace.drafts(),workspace.operations());
  assert.equal(workspace.hasChanges(),false);
  assert.equal(workspace.tree(),undefined);
});
test('same-parent reorder uses sibling insertion position', () => {
  const workspace = createWorkspace(storage()); workspace.seedTree(tree());
  workspace.stage({type:'move',source:'help',target_parent:'',before:'start'});
  assert.deepEqual(workspace.tree().nodes.map(node=>node.id),['help','start']);
  assert.deepEqual(workspace.tree().nodes.map(node=>node.weight),[10,20]);
});
test('fresh server trees replace a clean baseline but cannot erase staged changes', () => {
  const workspace = createWorkspace(storage()); workspace.seedTree(tree());
  workspace.seedTree({...tree(),revision:'tree2'});
  assert.equal(workspace.tree().revision,'tree2');
  workspace.put(page);
  workspace.seedTree({...tree(),revision:'tree3'});
  assert.equal(workspace.tree().revision,'tree2');
  workspace.remove(page.path);
  workspace.stage({type:'move',source:'help',target_parent:'',before:'start'});
  workspace.seedTree({...tree(),revision:'tree4'});
  assert.equal(workspace.tree().revision,'tree2');
  assert.equal(workspace.tree().nodes[0].id,'help');
});

test('reused virtual path never steals an existing page original identity',()=>{
  const workspace=createWorkspace(storage());
  workspace.seedTree({revision:'tree',nodes:[{id:'a.md',kind:'page',title:'Original',url:'/a/'},{id:'folder',kind:'folder',title:'Folder',children:[]}]});
  workspace.put({path:'a.md',title:'Original edited',body:'Original text',revision:'a1'});
  workspace.stage({type:'move',source:'a.md',target_parent:'folder',before:null});
  assert.throws(()=>workspace.put({path:'draft:new',creating:true,slug:'a',title:'New',body:'Different text'}),/Этот адрес уже принадлежит другой заметке/);
  assert.equal(workspace.get('a.md').body,'Original text');
  assert.equal(workspace.get('draft:new'),undefined);
  workspace.put({path:'a.md',title:'Original edited again',body:'Second edit',revision:'a1'});
  assert.equal(batchPages(workspace.drafts())[0].path,'a.md');
  assert.equal(workspace.virtualPath('a.md'),'folder/a.md');
});

test('new page slug remains editable after unrelated operations and locks after its own move',()=>{
  const workspace=createWorkspace(storage());workspace.seedTree(tree());
  workspace.stage({type:'folder',parent:'',slug:'new-folder',title:'New folder'});
  for(const slug of ['a','ab','abc'])workspace.put({path:'draft:new',creating:true,slug,title:'New',body:'Text'});
  assert.equal(workspace.slugLocked('draft:new'),false);
  workspace.stage({type:'move',source:'abc.md',target_parent:'new-folder',before:null});
  assert.equal(workspace.slugLocked('draft:new'),true);
  assert.throws(()=>workspace.put({path:'draft:new',creating:true,slug:'abcd',title:'New',body:'Text'}),/Нельзя изменить адрес/);
  workspace.stage({type:'move',source:'new-folder',target_parent:'',before:'start'});
  for(const slug of ['x','xy','xyz'])workspace.put({path:'draft:another',creating:true,slug,title:'Another',body:'Text'});
  assert.equal(workspace.slugLocked('draft:another'),false);
});

test('new page used as insertion anchor locks its slug',()=>{
  const workspace=createWorkspace(storage());workspace.seedTree(tree());
  workspace.put({path:'draft:anchor',creating:true,slug:'anchor',title:'Anchor',body:'Text'});
  workspace.stage({type:'move',source:'start',target_parent:'',before:'anchor.md'});
  assert.equal(workspace.slugLocked('draft:anchor'),true);
});

test('moving pages and folders rejects their shared URL collision without changing drafts',()=>{
  for(const [source,occupied] of [['a.md','a'],['a','a.md']]){
    const workspace=createWorkspace(storage());
    workspace.seedTree({revision:'r1',nodes:[{id:source,kind:source.endsWith('.md')?'page':'folder',title:'Source',children:[]},{id:'target',kind:'folder',title:'Target',children:[{id:'target/'+occupied,kind:occupied.endsWith('.md')?'page':'folder',title:'Occupied',children:[]}]}]});
    const previous=workspace.tree();
    assert.throws(()=>workspace.stage({type:'move',source,target_parent:'target',before:null}),/Этот адрес уже занят/);
    assert.deepEqual(workspace.tree(),previous);
    assert.deepEqual(workspace.operations(),[]);
  }
});

test('recursive deletion preserves submitted edits and removes moved subtree across reload', () => {
  const disk = storage(), workspace = createWorkspace(disk);
  workspace.start(); workspace.seedTree(tree()); workspace.put(page);
  workspace.stage({type:'move',source:'start',target_parent:'help',before:null});
  workspace.stage({type:'delete',source:'help/start'});
  const restored = createWorkspace(disk);
  assert.deepEqual(restored.tree().nodes.map(node=>node.id),['help']);
  assert.deepEqual(restored.tree().nodes[0].children,[]);
  assert.equal(restored.isDeleted('start/a.md'),true);
  assert.equal(restored.isDeleted('help/start/a.md'),true);
  assert.equal(restored.isDeleted('start/_index.md'),true);
  assert.equal(restored.isDeleted('help/_index.md'),false);
  assert.deepEqual(batchPages(restored.drafts()),[page]);
  assert.deepEqual(restored.operations(),[
    {type:'move',source:'start',target_parent:'help',before:null},
    {type:'delete',source:'help/start'}
  ]);
  restored.put({...page,body:'Late autosave'});
  assert.deepEqual(restored.drafts(),[page]);
  restored.discard();
  assert.equal(restored.isDeleted(page.path),false);
  assert.equal(restored.hasChanges(),false);
  assert.deepEqual(restored.seedTree(tree()).nodes.map(node=>node.id),['start','help']);
});

test('new page creation survives deletion for pages-first operation replay without reinjection', () => {
  const disk = storage(), workspace = createWorkspace(disk);
  const draft = {path:'draft:new',creating:true,slug:'new',title:'New',body:'Text'};
  workspace.seedTree(tree()); workspace.put(draft);
  workspace.stage({type:'folder',parent:'',slug:'created',title:'Created'});
  workspace.stage({type:'move',source:'new.md',target_parent:'created',before:null});
  workspace.stage({type:'delete',source:'created'});
  const restored = createWorkspace(disk);
  restored.put({...draft,body:'Late autosave'});
  assert.equal(restored.isDeleted('draft:new'),true);
  assert.deepEqual(restored.drafts(),[draft]);
  assert.deepEqual(batchPages(restored.drafts()),[{section:'',slug:'new',title:'New',body:'Text'}]);
  assert.deepEqual(restored.operations().map(op=>op.type),['folder','move','delete']);
  assert.deepEqual(restored.seedTree(tree()).nodes.map(node=>node.id),['start','help']);
  restored.acknowledge(restored.drafts(),restored.operations());
  assert.equal(restored.hasChanges(),false);
  assert.equal(restored.isDeleted('draft:new'),false);
});

test('delete validation and failed persistence preserve the complete workspace', () => {
  const disk = storage(), workspace = createWorkspace(disk);
  workspace.seedTree(tree());
  assert.throws(()=>workspace.stage({type:'delete',source:'missing'}),/не найдена/);
  disk.setItem=()=>{throw new Error('quota');};
  assert.throws(()=>workspace.stage({type:'delete',source:'start'}),/quota/);
  assert.equal(workspace.isDeleted('start/a.md'),false);
  assert.deepEqual(workspace.operations(),[]);
  assert.equal(workspace.tree().nodes[0].id,'start');
});

test('a new page cannot reuse the URL of a folder staged for deletion',()=>{
  const workspace=createWorkspace(storage());workspace.seedTree(tree());
  workspace.stage({type:'delete',source:'start'});
  assert.throws(()=>workspace.put({path:'draft:new',creating:true,slug:'start',title:'New',body:''}),/адрес удалён/);
  assert.deepEqual(workspace.drafts(),[]);
  assert.deepEqual(workspace.operations(),[{type:'delete',source:'start'}]);
});

test('folder rename preserves draft body and persists through moves reload and deletion',()=>{
  const disk=storage(),workspace=createWorkspace(disk);
  workspace.start();workspace.seedTree({revision:'r',nodes:[{id:'a',kind:'folder',title:'A',url:'/a/',children:[]}]});
  workspace.put({path:'a/_index.md',title:'A',body:'Keep',revision:'r'});
  workspace.stage({type:'rename',source:'a',title:' Renamed '});
  assert.equal(workspace.get('a/_index.md').title,'Renamed');
  assert.equal(workspace.get('a/_index.md').body,'Keep');
  workspace.stage({type:'folder',parent:'',slug:'parent',title:'Parent'});
  workspace.stage({type:'move',source:'a',target_parent:'parent',before:null});
  workspace.stage({type:'rename',source:'parent/a',title:'Moved'});
  const restored=createWorkspace(disk);
  assert.equal(restored.tree().nodes[0].children[0].title,'Moved');
  assert.equal(restored.tree().nodes[0].children[0].page_path,'parent/a/_index.md');
  assert.equal(restored.get('parent/a/_index.md').title,'Moved');
  restored.stage({type:'delete',source:'parent/a'});
  assert.equal(restored.tree().nodes[0].children.length,0);
});

test('rename rejects invalid titles and page targets and skips unchanged names',()=>{
  const workspace=createWorkspace(storage());
  workspace.seedTree({revision:'r',nodes:[{id:'a',kind:'folder',title:'A',children:[]},{id:'p.md',kind:'page',title:'Page'}]});
  for(const title of ['', ' ', 'x\ny', 'x'.repeat(201), null]) assert.throws(()=>workspace.stage({type:'rename',source:'a',title}));
  assert.throws(()=>workspace.stage({type:'rename',source:'p.md',title:'P'}));
  workspace.stage({type:'rename',source:'a',title:' A '});
  assert.deepEqual(workspace.operations(),[]);
  workspace.stage({type:'folder',parent:'a',slug:'new',title:'New'});
  workspace.stage({type:'rename',source:'a/new',title:'Fresh'});
  assert.equal(workspace.tree().nodes[0].children[0].title,'Fresh');
});

test('editing a renamed folder heading after moving it updates the final rename operation',()=>{
  const workspace=createWorkspace(storage());workspace.start();
  workspace.seedTree({revision:'r',nodes:[{id:'a',kind:'folder',title:'A',children:[]},{id:'parent',kind:'folder',title:'Parent',children:[]}]});
  workspace.stage({type:'rename',source:'a',title:'Renamed'});
  workspace.stage({type:'move',source:'a',target_parent:'parent',before:null});
  workspace.put({path:'a/_index.md',title:'Latest heading',body:'Body',revision:'r'});
  assert.deepEqual(workspace.operations()[0],{type:'rename',source:'a',title:'Latest heading'});
  assert.equal(workspace.tree().nodes[0].children[0].title,'Latest heading');
});

test('workspace generated page and folder URLs honor the deployment subpath', () => {
  const workspace = createWorkspace(storage(), 'site:user', {basePath:'/docs/'});
  workspace.seedTree({revision:'r1',nodes:[]});
  workspace.put({path:'draft:new',creating:true,slug:'page',title:'Page',body:''});
  workspace.stage({type:'folder',parent:'',slug:'folder',title:'Folder'});
  workspace.stage({type:'move',source:'page.md',target_parent:'folder'});
  const [folder] = workspace.tree().nodes;
  assert.equal(folder.url, '/docs/folder/');
  assert.equal(folder.children[0].url, '/docs/folder/page/');
});

test('upload references survive reload and preserve uploads added during publication', () => {
  const disk = storage(), workspace = createWorkspace(disk);
  workspace.addUpload('first');
  workspace.addUpload('first');
  assert.deepEqual(createWorkspace(disk).uploads(), ['first']);
  const submitted = workspace.uploads();
  submitted.push('not-stored');
  assert.deepEqual(workspace.uploads(), ['first']);
  workspace.addUpload('second');
  workspace.acknowledge([], [], submitted);
  assert.deepEqual(workspace.uploads(), ['second']);
  workspace.acknowledge([]);
  assert.deepEqual(workspace.uploads(), []);
  workspace.addUpload('third');
  workspace.discard();
  assert.deepEqual(createWorkspace(disk).uploads(), []);
});
