import assert from 'node:assert/strict';

export async function verifyRuntimeEditor(page, {origin, username, password}) {
  const target=new URL(origin);
  if(!['127.0.0.1','localhost','[::1]'].includes(target.hostname))throw new Error('Browser smoke test requires a disposable localhost wiki');
  const slug='browser-proof-'+Date.now();
  await page.goto(origin);
  await page.evaluate(()=>sessionStorage.clear());
  await page.reload();
  if(await page.locator('.wiki-account-toggle').textContent()==='Sign in'){
    await page.locator('.wiki-account-toggle').click();
    await page.locator('input[name=username]').fill(username);
    await page.locator('input[name=password]').fill(password);
    await page.locator('.wiki-account form button[type=submit]').click();
  }
  await page.locator('[data-editor-open]').click();
  assert.equal(await page.locator('[data-editor-save]').textContent(),'Publish');
  await page.getByRole('button',{name:'New folder',exact:true}).click();
  await page.getByPlaceholder('Folder name').fill(slug);
  await page.getByPlaceholder('folder-address').fill(slug);
  await page.getByRole('button',{name:'Create folder',exact:true}).click();
  await page.getByRole('button',{name:'New page',exact:true}).click();
  await page.locator('#page-title').fill(slug+' note');
  await page.locator('input[name=slug]').fill(slug+'-note');
  await page.locator('.tiptap').fill('Browser publication proof');
  await page.getByRole('button',{name:'Formula',exact:true}).click();
  await page.getByRole('button',{name:'Diagram',exact:true}).click();
  await page.locator('[data-wiki-node=wikiDisplayMath] svg').waitFor();
  await page.locator('[data-wiki-node=wikiMermaid] svg').waitFor();
  const source=await page.locator('.wiki-tree-row').filter({has:page.getByRole('link',{name:slug+' note',exact:true})}).boundingBox();
  const folder=await page.locator('.wiki-tree-row').filter({has:page.getByRole('button',{name:'Expand '+slug,exact:true})}).boundingBox();
  await page.mouse.move(source.x+50,source.y+source.height/2);
  await page.mouse.down();
  await page.mouse.move(folder.x+60,folder.y+folder.height/2,{steps:15});
  await page.mouse.up();
  await page.locator('[data-editor-save]').click();
  await page.waitForURL('**/'+slug+'/'+slug+'-note/');
  await page.waitForLoadState('networkidle');
  await page.reload();
  assert.equal(await page.locator('#page-title').textContent(),slug+' note');
  await page.locator('mjx-container svg').waitFor();
  await page.locator('.mermaid svg').waitFor();
  await page.setViewportSize({width:390,height:844});
  await page.locator('[data-editor-open]').click();
  assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
  const bar=await page.locator('.wiki-editbar').boundingBox();
  assert.ok(bar.x>=0&&bar.x+bar.width<=390);
  return {page:page.url(),slug};
}
