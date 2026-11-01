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
