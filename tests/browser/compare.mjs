import assert from 'node:assert/strict';
import { resolve } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { chromium } from 'playwright';

const fixture = new URL('../../.comparison/index.html', import.meta.url);
const heading = 'Paid Search activation flips direction';
const evidence = 'Read the generated report evidence';
const readings = [
  { name: 'A · Original', delta: '−17.3', last: '39.62%', raw: -17.32 },
  { name: 'B · Edited', delta: '+37.4', last: '94.34%', raw: 37.4 },
];

export function verifyGeometry({ width, scrollWidth, rows }) {
  assert.ok(scrollWidth <= width, `horizontal overflow: ${scrollWidth} > ${width}`);
  assert.equal(rows.length, readings.length);
  for (const [index, { track, fill }] of rows.entries()) {
    assert.ok(track.width > 0, 'chart track has width');
    const measure = Math.abs(readings[index].raw) / 80;
    const center = (track.left + track.right) / 2;
    assert.ok(Math.abs(fill.width - track.width * measure) < 1.5, 'bar represents the scaled change');
    assert.ok(Math.abs((index === 0 ? fill.right : fill.left) - center) < 1.5,
      'negative bars end at zero and positive bars start at zero');
    assert.ok(fill.left >= track.left && fill.right <= track.right, 'bar stays within track');
  }
}

async function checkFixture(browser, width) {
  const context = await browser.newContext({ viewport: { width, height: 900 },
    offline: true, serviceWorkers: 'block' });
  try {
    const page = await context.newPage();
    page.setDefaultTimeout(5_000);
    const requests = [];
    page.on('request', request => {
      if (!request.url().startsWith('file:')) requests.push(request.url());
    });
    await page.goto(fixture.href);
    const figure = page.getByRole('figure', { name: heading, exact: true });
    await figure.waitFor();
    const rateRegion = figure.getByRole('region', { name: 'Paid Search activation rates behind each bar' });
    await rateRegion.waitFor();
    for (const [index, reading] of readings.entries()) {
      const card = rateRegion.locator('.rate-card').filter({
        has: page.getByRole('heading', { name: reading.name, exact: true }),
      });
      assert.deepEqual(await card.locator('dt').allTextContents(), ['Apr 6', 'May 25']);
      assert.deepEqual(await card.locator('dd').allTextContents(), ['56.94%', reading.last]);
      assert.equal(await figure.locator('.reading strong').nth(index).textContent(), reading.delta);
    }
    const snapshot = () => page.evaluate(() => {
      const rect = element => {
        const { left, right, width } = element.getBoundingClientRect();
        return { left, right, width };
      };
      return { width: document.documentElement.clientWidth,
        scrollWidth: document.documentElement.scrollWidth,
        rows: [...document.querySelectorAll('.plot-row')].map(row => ({
          track: rect(row.querySelector('.track')), fill: rect(row.querySelector('.fill')),
        })) };
    });
    verifyGeometry(await snapshot());
    const details = page.locator('details');
    const summary = details.locator('summary');
    assert.equal(await summary.textContent(), evidence);
    const original = page.getByRole('link', { name: 'Open original report JSON', exact: true });
    const edited = page.getByRole('link', { name: 'Open edited report JSON', exact: true });
    assert.equal(await original.count(), 0, 'collapsed evidence is hidden from the accessibility tree');
    await page.keyboard.press('Tab');
    assert.equal(await summary.evaluate(el => document.activeElement === el), true, 'summary keyboard focus');
    await page.keyboard.press('Enter');
    assert.equal(await details.evaluate(el => el.open), true, 'Enter expands native evidence disclosure');
    verifyGeometry(await snapshot());
    await page.keyboard.press('Tab');
    assert.equal(await original.evaluate(el => document.activeElement === el), true, 'original evidence keyboard focus');
    assert.equal(new URL(await original.getAttribute('href'), fixture).href,
      new URL('reports/original-report.json', fixture).href);
    await page.keyboard.press('Tab');
    assert.equal(await edited.evaluate(el => document.activeElement === el), true, 'edited evidence keyboard focus');
    const editedUrl = new URL('reports/edited-report.json', fixture).href;
    await Promise.all([page.waitForURL(editedUrl), page.keyboard.press('Enter')]);
    assert.equal(page.url(), editedUrl, 'keyboard follows local evidence link');
    const report = JSON.parse(await page.locator('body').innerText());
    assert.equal(report.snapshot.status, 'fixture');
    assert.equal(report.snapshot.datasets.channel_summary.find(row => row.acquisition_channel === 'Paid Search')
      .activation_rate_change_pp, 37.4);
    assert.deepEqual(requests, [], 'offline comparison must not attempt an external request');
    console.log(`PASS ${width}px: chart and rates, no overflow, keyboard disclosure and evidence, offline fixture`);
  } finally {
    await context.close();
  }
}

async function run() {
  const executablePath = process.env.COMPARISON_CHROMIUM;
  const browser = await chromium.launch(executablePath ? { executablePath } : {});
  try {
    for (const width of [320, 390, 1280]) await checkFixture(browser, width);
  } finally {
    await browser.close();
  }
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  await run();
}
