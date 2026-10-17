import test from 'node:test';
import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { createPublishedView } from './published-view.js';

const hash = body=>createHash('sha256').update(body).digest('hex');
function setup(bodyHash=hash('old')) {
  const article={innerHTML:'<p>Old</p>'}, heading={textContent:'Old title'};
  return {article, heading, view:createPublishedView({article,heading,bodyHash})};
}
const page={title:'Saved title',body:'Saved body'};
test('cancel after saving restores the saved snapshot, including on repeated edits',()=>{
  const {view,article,heading}=setup();
  view.capture('Saved title','<p>Saved body</p>');
  article.innerHTML='<p>Unsaved</p>';heading.textContent='Unsaved';view.restore();
  assert.equal(article.innerHTML,'<p>Saved body</p>');assert.equal(heading.textContent,'Saved title');
  article.innerHTML='<p>Another edit</p>';view.restore();assert.equal(article.innerHTML,'<p>Saved body</p>');
});
test('refresh hydrates the latest saved Git content while static deployment is stale',async()=>{
  const {view,article,heading}=setup();const calls=[];
  await view.hydrate({path:'help.md',canApply:()=>true,api:async(endpoint,payload)=>{calls.push({endpoint,payload});return payload ? {html:'<p>Saved body</p>'}:page;}});
  assert.equal(article.innerHTML,'<p>Saved body</p>');assert.equal(heading.textContent,page.title);
  assert.equal(calls[1].endpoint,'/preview');article.innerHTML='Unsaved';view.restore();assert.equal(article.innerHTML,'<p>Saved body</p>');
});
test('current Hugo HTML is preserved without approximate preview',async()=>{
  const {view,article}=setup(hash('current'));let calls=0;
  await view.hydrate({path:'help.md',canApply:()=>true,api:async()=>{calls++;return {title:'Old title',body:'current'};}});
  assert.equal(calls,1);assert.equal(article.innerHTML,'<p>Old</p>');
});
test('delayed preview cannot overwrite active editing',async()=>{
  const {view,article}=setup();let resolvePreview,canApply=true;
  const pending=view.hydrate({path:'help.md',canApply:()=>canApply,api:async(endpoint,payload)=>payload ? new Promise(resolve=>{resolvePreview=resolve;}):page});
  while(!resolvePreview)await new Promise(resolve=>setTimeout(resolve,0));
  canApply=false;article.innerHTML='Editing';resolvePreview({html:'Saved'});await pending;
  assert.equal(article.innerHTML,'Editing');
});
test('delayed hydration cannot revert a newer successful save',async()=>{
  const {view,article}=setup();let resolvePage;
  const pending=view.hydrate({path:'help.md',canApply:()=>true,api:()=>new Promise(resolve=>{resolvePage=resolve;})});
  view.capture('Newest','Newest body');view.restore();resolvePage(page);await pending;
  assert.equal(article.innerHTML,'Newest body');
});
test('opening before background hydration finishes updates the cancel snapshot from fetched source',async()=>{
  const {view,article}=setup();
  await view.hydratePage({page,path:'help.md',canApply:()=>true,apply:false,api:async()=>({html:'<p>Latest</p>'})});
  assert.equal(article.innerHTML,'<p>Old</p>');
  article.innerHTML='Editor draft';view.restore();assert.equal(article.innerHTML,'<p>Latest</p>');
});
test('snapshot-only hydration begun before a save cannot restore the older source',async()=>{
  const {view,article}=setup();let resolvePage;
  const pending=view.hydrate({path:'help.md',apply:false,canApply:()=>true,api:()=>new Promise(resolve=>{resolvePage=resolve;})});
  view.capture('Newest','Newest body');resolvePage(page);await pending;
  article.innerHTML='Editing';view.restore();assert.equal(article.innerHTML,'Newest body');
});
