import test from 'node:test';
import assert from 'node:assert/strict';
import {JSDOM} from 'jsdom';
import {mountAccount} from './account.js';

for (const user of [null, {username:'reader',role:'reader'}, {username:'admin',role:'admin'}]) {
  test('account navigation uses a full page for ' + (user?.role || 'anonymous'), async () => {
    const dom = new JSDOM('<html lang="en"><body><div id="root" data-base-path="/docs/"></div></body></html>', {url:'https://wiki.test/docs/'});
    globalThis.document = dom.window.document;
    const calls = [];
    globalThis.fetch = async path => { calls.push(path); return {ok:true,json:async () => ({user})}; };
    await mountAccount(document.getElementById('root'));
    const link = document.querySelector('.wiki-account-toggle');
    assert.equal(link.getAttribute('href'), '/docs/' + (user ? 'admin' : 'login'));
    assert.equal(document.querySelector('dialog'), null);
    assert.deepEqual(calls, ['/docs/api/editor/session']);
  });
}
