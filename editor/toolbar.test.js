import test from 'node:test';
import assert from 'node:assert/strict';
import {JSDOM} from 'jsdom';
import {createFormatToolbar} from './toolbar.js';

function fixture() {
  const dom = new JSDOM('<body></body>');
  const document = dom.window.document;
  const listeners = new Map();
  const editor = {on:(name,fn)=>listeners.set(name,fn),off:(name,fn)=>{if(listeners.get(name)===fn)listeners.delete(name);}};
  let active = false, busy = false, calls = 0;
  const toolbar = createFormatToolbar({document, editor, label:'Formatting', isBusy:()=>busy, groups:[{label:'Text',actions:[
    {id:'bold',label:'Bold',run:()=>calls++,active:()=>active},
    {id:'italic',label:'Italic',run:()=>calls++},
    {id:'link',label:'Link',run:()=>calls++}
  ]}]});
  document.body.append(toolbar.element);
  return {dom, document, listeners, ...toolbar, setActive:value=>active=value, setBusy:value=>busy=value, calls:()=>calls};
}

test('icon controls retain accessible names and preserve selection on mouse down', () => {
  const f = fixture(), button=f.buttons.get('bold');
  assert.equal(button.textContent,'');
  assert.equal(button.getAttribute('aria-label'),'Bold');
  assert.equal(button.title,'Bold');
  assert.equal(button.querySelector('svg').getAttribute('aria-hidden'),'true');
  const event = new f.dom.window.MouseEvent('mousedown',{cancelable:true,bubbles:true});
  button.dispatchEvent(event);
  assert.equal(event.defaultPrevented,true);
  button.click();
  assert.equal(f.calls(),1);
  f.setBusy(true);
  button.click();
  assert.equal(f.calls(),1);
});

test('selection and transaction changes update active state and destruction removes subscriptions', () => {
  const f=fixture(),button=f.buttons.get('bold');
  assert.equal(button.getAttribute('aria-pressed'),'false');
  f.setActive(true); f.listeners.get('selectionUpdate')();
  assert.equal(button.getAttribute('aria-pressed'),'true');
  f.setActive(false); f.listeners.get('transaction')();
  assert.equal(button.getAttribute('aria-pressed'),'false');
  f.listeners.get('destroy')();
  assert.equal(f.listeners.size,0);
});

test('toolbar roving focus wraps, skips disabled controls, and supports home and end', () => {
  const f=fixture(),bold=f.buttons.get('bold'),italic=f.buttons.get('italic'),link=f.buttons.get('link');
  const key=name=>f.document.activeElement.dispatchEvent(new f.dom.window.KeyboardEvent('keydown',{key:name,bubbles:true,cancelable:true}));
  bold.focus(); italic.disabled=true;
  key('ArrowRight'); assert.equal(f.document.activeElement,link);
  assert.equal(bold.tabIndex,-1); assert.equal(link.tabIndex,0);
  key('ArrowRight'); assert.equal(f.document.activeElement,bold);
  key('End'); assert.equal(f.document.activeElement,link);
  key('Home'); assert.equal(f.document.activeElement,bold);
  key('ArrowLeft'); assert.equal(f.document.activeElement,link);
});
