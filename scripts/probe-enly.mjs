import { chromium } from 'playwright';

const browser = await chromium.launch({ headless: true });
const ctx = await browser.newContext({
  viewport: { width: 1440, height: 900 },
  permissions: ['microphone'],
  ignoreHTTPSErrors: true,
});
const page = await ctx.newPage();

const events = [];
page.on('pageerror', (e) => events.push({ kind: 'pageerror', msg: e.message }));
page.on('console', (msg) => {
  const t = msg.type();
  if (t === 'error' || t === 'warning') {
    events.push({ kind: `console.${t}`, msg: msg.text().slice(0, 400) });
  }
});
page.on('requestfailed', (req) =>
  events.push({ kind: 'requestfailed', url: req.url(), failure: req.failure()?.errorText }),
);

const t0 = Date.now();
await page.goto('https://www.enlyai.com/', { waitUntil: 'domcontentloaded', timeout: 30000 });
await page.waitForTimeout(3500);
const title = await page.title();
const url = page.url();
const loadMs = Date.now() - t0;
const bodyText = (await page.textContent('body'))?.slice(0, 800);

// Look for navigation entries
const links = await page.$$eval('a', (as) =>
  as
    .slice(0, 30)
    .map((a) => ({ text: a.textContent?.trim().slice(0, 60), href: a.getAttribute('href') }))
    .filter((x) => x.text),
);
const buttons = await page.$$eval('button', (bs) =>
  bs
    .slice(0, 20)
    .map((b) => b.textContent?.trim().slice(0, 60))
    .filter(Boolean),
);

console.log(
  JSON.stringify(
    {
      title,
      url,
      loadMs,
      eventsCount: events.length,
      events: events.slice(0, 30),
      bodyPreview: bodyText,
      links,
      buttons,
    },
    null,
    2,
  ),
);
await page.screenshot({ path: 'scripts/enly-home.png', fullPage: false });
await browser.close();
