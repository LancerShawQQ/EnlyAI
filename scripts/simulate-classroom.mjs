#!/usr/bin/env node
/**
 * Real-user simulation against production classroom.
 * Loads /classroom/<id>, watches WS frames, console errors, slide transitions,
 * teacher-utterance gaps, silence-cue events.
 */
import { chromium } from 'playwright';
import { writeFileSync } from 'node:fs';

const BASE = process.env.SIM_BASE || 'https://www.enlyai.com';
const CLASSROOM_ID = process.env.SIM_CLASSROOM_ID || 'CbwQoPJ9ML';
const DURATION_MS = Number(process.env.SIM_DURATION_MS || 90000);

function ts() {
  return new Date().toISOString().slice(11, 23);
}

(async () => {
  const browser = await chromium.launch({
    headless: true,
    args: [
      '--use-fake-ui-for-media-stream',
      '--use-fake-device-for-media-stream',
      '--autoplay-policy=no-user-gesture-required',
    ],
  });
  const ctx = await browser.newContext({
    permissions: ['microphone'],
    viewport: { width: 1366, height: 800 },
    locale: 'zh-CN',
  });
  const page = await ctx.newPage();
  const events = [];
  const consoleErrors = [];
  const requestFailures = [];
  const wsFrames = [];
  let wsCount = 0;

  page.on('console', (msg) => {
    const type = msg.type();
    if (type === 'error' || type === 'warning') {
      const text = msg.text();
      consoleErrors.push({ t: ts(), type, text: text.slice(0, 500) });
    }
  });
  page.on('pageerror', (err) => {
    consoleErrors.push({ t: ts(), type: 'pageerror', text: String(err.message).slice(0, 500) });
  });
  page.on('requestfailed', (req) => {
    requestFailures.push({ t: ts(), url: req.url(), failure: req.failure()?.errorText });
  });
  page.on('websocket', (ws) => {
    wsCount++;
    const id = wsCount;
    events.push({ t: ts(), kind: 'ws-open', url: ws.url(), id });
    ws.on('framesent', (f) => {
      try {
        const p = typeof f.payload === 'string' ? f.payload : (f.payload?.toString('utf8') ?? '');
        const j = p.startsWith('{') ? JSON.parse(p) : null;
        wsFrames.push({ t: ts(), dir: 'tx', id, type: j?.type, len: p.length });
      } catch {
        wsFrames.push({ t: ts(), dir: 'tx', id, len: 0 });
      }
    });
    ws.on('framereceived', (f) => {
      try {
        const p = typeof f.payload === 'string' ? f.payload : (f.payload?.toString('utf8') ?? '');
        const j = p.startsWith('{') ? JSON.parse(p) : null;
        wsFrames.push({ t: ts(), dir: 'rx', id, type: j?.type, len: p.length });
      } catch {
        wsFrames.push({ t: ts(), dir: 'rx', id, len: 0 });
      }
    });
    ws.on('close', () => events.push({ t: ts(), kind: 'ws-close', id }));
  });

  // Register or login a test account first.
  const email = `e2e-bot+${Date.now()}@enlyai.test`;
  const password = 'TestBot!2026';
  try {
    const reg = await page.request.post(`${BASE}/api/auth/register`, {
      data: { email, password, nickname: 'E2EBot', avatar: '/avatars/avatar-1.png' },
    });
    events.push({ t: ts(), kind: 'register', status: reg.status() });
  } catch (e) {
    events.push({ t: ts(), kind: 'register-error', error: String(e).slice(0, 200) });
  }

  console.log(`[${ts()}] navigating to classroom...`);
  const t0 = Date.now();
  try {
    await page.goto(`${BASE}/classroom/${CLASSROOM_ID}`, {
      waitUntil: 'domcontentloaded',
      timeout: 30000,
    });
    events.push({ t: ts(), kind: 'nav-done', dt: Date.now() - t0 });
  } catch (e) {
    events.push({ t: ts(), kind: 'nav-error', error: String(e).slice(0, 200) });
  }

  // Wait for stage to load, then poll DOM for slide/phase signals.
  await page.waitForTimeout(4000);

  // Try to find and click a "start" / "begin" CTA if present.
  const ctaSelectors = [
    'button:has-text("开始")',
    'button:has-text("Start")',
    'button:has-text("进入")',
    'button:has-text("Begin")',
    'button:has-text("Got it")',
    'button:has-text("我知道了")',
  ];
  for (const sel of ctaSelectors) {
    const el = page.locator(sel).first();
    if (await el.count().catch(() => 0)) {
      try {
        await el.click({ timeout: 1500 });
        events.push({ t: ts(), kind: 'cta-click', selector: sel });
        await page.waitForTimeout(500);
        break;
      } catch {}
    }
  }

  // Snapshot slide signals every 2s.
  const slideHistory = [];
  const interval = setInterval(async () => {
    try {
      const snap = await page.evaluate(() => {
        const slide =
          document.querySelector('[data-slide-id]')?.getAttribute('data-slide-id') || null;
        const phase = document.querySelector('[data-phase]')?.getAttribute('data-phase') || null;
        const sceneIdx =
          document.querySelector('[data-scene-index]')?.getAttribute('data-scene-index') || null;
        const teacherSpeaking = document.querySelector('[data-teacher-speaking="true"]')
          ? true
          : false;
        const mic = !!document.querySelector('[data-mic-active="true"]');
        const subtitle =
          document.querySelector('[data-subtitle]')?.textContent?.slice(0, 100) || null;
        return { slide, phase, sceneIdx, teacherSpeaking, mic, subtitle };
      });
      slideHistory.push({ t: ts(), ...snap });
    } catch {}
  }, 2000);

  console.log(`[${ts()}] observing for ${DURATION_MS / 1000}s...`);
  await page.waitForTimeout(DURATION_MS);
  clearInterval(interval);

  // Capture final screenshot for inspection.
  try {
    await page.screenshot({ path: 'scripts/sim-final.png', fullPage: false });
  } catch {}

  // Aggregate summary.
  const wsTypes = {};
  for (const f of wsFrames) {
    const key = `${f.dir}:${f.type ?? 'unknown'}`;
    wsTypes[key] = (wsTypes[key] || 0) + 1;
  }
  const uniqSlides = [...new Set(slideHistory.map((s) => s.slide).filter(Boolean))];
  const uniqPhases = [...new Set(slideHistory.map((s) => s.phase).filter(Boolean))];

  const report = {
    base: BASE,
    classroomId: CLASSROOM_ID,
    durationMs: DURATION_MS,
    summary: {
      consoleErrors: consoleErrors.length,
      requestFailures: requestFailures.length,
      wsOpened: wsCount,
      wsFrameCount: wsFrames.length,
      wsTypes,
      slideCount: uniqSlides.length,
      uniqSlides,
      uniqPhases,
    },
    events,
    consoleErrors: consoleErrors.slice(0, 40),
    requestFailures: requestFailures.slice(0, 20),
    wsFrames: wsFrames.slice(-60),
    slideHistory,
  };

  const out = `scripts/sim-report-${Date.now()}.json`;
  writeFileSync(out, JSON.stringify(report, null, 2));
  console.log(`[${ts()}] report written: ${out}`);
  console.log(JSON.stringify(report.summary, null, 2));

  await browser.close();
})().catch((e) => {
  console.error('SIM-FATAL', e);
  process.exit(1);
});
