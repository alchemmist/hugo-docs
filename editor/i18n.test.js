import test from 'node:test';
import assert from 'node:assert/strict';
import {t, locale} from './i18n.js';

test('locale selects Russian region variants and defaults unsupported languages to English', () => {
  assert.equal(locale('ru-RU'), 'ru');
  assert.equal(locale('de'), 'en');
  assert.equal(t('Опубликовать', {}, 'en'), 'Publish');
  assert.equal(t('Publish', {}, 'ru'), 'Опубликовать');
});

test('translation follows the page language and preserves unknown keys and placeholders', () => {
  globalThis.document = {documentElement:{lang:'ru'}};
  assert.equal(t('New folder'), 'Новая папка');
  document.documentElement.lang = 'en';
  assert.equal(t('Новая папка'), 'New folder');
  assert.equal(t('Hello {name}: {missing}', {name:'Ada'}), 'Hello Ada: {missing}');
  delete globalThis.document;
  assert.equal(locale(), 'en');
});
