globalThis.document = {documentElement:{lang:'ru'}};
import test from 'node:test';
import assert from 'node:assert/strict';
import { createPublicationState } from './publication-state.js';
test('save distinguishes pending deployment, confirmed deployment and failure',()=>{
  const button={textContent:''},state=createPublicationState(button);
  const done=state.pending();assert.equal(button.textContent,'Сохранено · публикация…');
  done(true);assert.equal(button.textContent,'Опубликовано');
  state.pending()(false);assert.equal(button.textContent,'Сохранено · ошибка публикации');
});
test('old publication cannot overwrite new edits or a newer save',()=>{
  const button={textContent:''},state=createPublicationState(button);
  const old=state.pending();state.reset();old(true);assert.equal(button.textContent,'Опубликовать');
  const next=state.pending();old(false);assert.equal(button.textContent,'Сохранено · публикация…');
  next(true);assert.equal(button.textContent,'Опубликовано');
});
