import assert from 'node:assert/strict';

// Reusable Playwright check, like browser-runtime.mjs. Supply a long local page
// with at least one H2; no browser dependency is added to the published theme.
export async function verifyReadingChrome(page, {origin, path}) {
  const url = new URL(path, origin);
  assert.ok(['localhost', '127.0.0.1', '[::1]'].includes(url.hostname), 'Use a disposable local site');
  await page.setViewportSize({width: 1440, height: 900});
  await page.goto(url.href);
  await page.evaluate(() => document.fonts.ready);
  const anchor = page.locator('.hc-content h2 a.link').first();
  const style = () => anchor.evaluate((element) => {
    const css = getComputedStyle(element);
    return {font: css.fontFamily.toLowerCase(), size: parseFloat(css.fontSize),
      headingSize: parseFloat(getComputedStyle(element.parentElement).fontSize),
      weight: css.fontWeight, opacity: css.opacity, transform: css.transform,
      shadow: css.textShadow, decoration: css.textDecorationLine};
  });
  const normal = await style();
  assert.ok(normal.font.includes('computer modern typewriter'));
  assert.equal(normal.size, normal.headingSize * 1.4);
  assert.equal(normal.weight, '300');
  assert.equal(normal.opacity, '0.3');
  assert.equal(normal.decoration, 'none');
  await anchor.hover();
  const hover = await style();
  assert.equal(hover.opacity, '0.7');
  assert.equal(hover.transform, 'matrix(1.1, 0, 0, 1.1, 0, 0)');
  assert.equal(hover.shadow, 'rgba(13, 71, 161, 0.2) 0px 0px 5px');
  const fragment = await anchor.getAttribute('href');
  await anchor.click();
  await page.waitForFunction((hash) => decodeURIComponent(location.hash) === decodeURIComponent(hash), fragment);
  await page.waitForFunction(() => {
    const target = document.getElementById(decodeURIComponent(location.hash.slice(1)));
    return Math.abs(target.getBoundingClientRect().top) < 2;
  });
  await page.reload();
  await page.waitForFunction(() => Math.abs(document.getElementById(decodeURIComponent(location.hash.slice(1))).getBoundingClientRect().top) < 2);

  for (const width of [1440, 390, 320]) {
    await page.setViewportSize({width, height: 900});
    await page.goto(url.href);
    if (width < 761) await page.locator('#menu-toggle').click();
    for (const selector of ['.sidebar', '.page-tree']) {
      const bottom = await page.locator(selector).evaluate((element) => element.getBoundingClientRect().bottom);
      assert.ok(Math.abs(bottom - 900) < 2, `${selector} must reach viewport bottom at ${width}px`);
    }
    assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
    if (width < 761) {
      await page.locator('#menu-toggle').click();
      await page.locator('.hc-content h2 a.link').first().click();
      await page.waitForFunction(() => {
        const target = document.getElementById(decodeURIComponent(location.hash.slice(1)));
        return target && Math.abs(target.getBoundingClientRect().top - 80) < 2;
      });
    }
  }
  return {normal, hover, fragment};
}

// Use a specimen containing paragraphs, inline code and highlighted fenced code.
// These are the blog's hugo-content metrics; UI typography is a separate concern.
export async function verifyContentTypography(page, {origin, path, interfaceFamily}) {
  const url = new URL(path, origin);
  assert.ok(['localhost', '127.0.0.1', '[::1]'].includes(url.hostname));
  for (const width of [1440, 700, 650, 390, 320]) {
    await page.setViewportSize({width, height: 900});
    await page.goto(url.href);
    await page.evaluate(() => document.fonts.ready);
    const metrics = await page.evaluate(() => {
      const get = (selector) => {
        const css = getComputedStyle(document.querySelector(selector));
        return {font: css.fontFamily.toLowerCase(), size: parseFloat(css.fontSize),
          weight: css.fontWeight, line: css.lineHeight, padding: css.padding,
          margin: css.margin, background: css.backgroundColor};
      };
      return {prose: get('.hc-content p'), inline: get('.hc-content p code'),
        code: get('.hc-content pre code'), token: get('.hc-content pre code span'),
        ui: get('.sidebar'), overflow: document.documentElement.scrollWidth > innerWidth};
    });
    const mobile = width <= 650;
    assert.ok(metrics.prose.font.includes('computer modern roman'));
    assert.equal(metrics.prose.size, mobile ? 16 : 18);
    assert.equal(metrics.prose.weight, '400');
    assert.equal(metrics.prose.line, 'normal');
    assert.equal(metrics.prose.margin, mobile ? '8px 0px' : '9px 0px');
    for (const key of ['inline', 'code', 'token']) {
      assert.ok(metrics[key].font.includes('computer modern typewriter'), `${key}: ${metrics[key].font}`);
      assert.ok(!metrics[key].font.includes('couriercyr'));
    }
    assert.equal(metrics.inline.size, mobile ? 14.4 : 16.2);
    assert.equal(metrics.inline.background, 'rgba(0, 0, 0, 0.04)');
    assert.equal(metrics.code.size, mobile ? 13.6 : 17.28);
    assert.equal(metrics.token.size, metrics.code.size);
    assert.equal(metrics.code.line, mobile ? '16.32px' : '20.736px');
    assert.equal(metrics.token.line, metrics.code.line);
    assert.equal(metrics.code.padding, mobile ? '12.8px' : '16px');
    assert.equal(metrics.code.background, 'rgba(0, 0, 0, 0.02)');
    if (interfaceFamily) assert.ok(metrics.ui.font.includes(interfaceFamily.toLowerCase()));
    assert.equal(metrics.overflow, false);
  }
}
