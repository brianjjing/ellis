// Playwright happy path (spec: one happy-path UI test). Needs the API (seeded) and `npm run dev` running.
// Run: NODE_PATH=$(npm root -g) node e2e/happy-path.cjs   (or with a local playwright install)
// Clinic UI: login, case list, case detail, demo autofill, review queue decisions, mark ready; then applicant signs.
const { chromium } = require('playwright');
(async () => {
  const b = await chromium.launch();
  const ctx = await b.newContext({ viewport: { width: 1360, height: 900 } });
  const p = await ctx.newPage();
  const logs = [];
  p.on('pageerror', e => logs.push('PAGEERROR ' + e.message));
  p.on('console', m => { if (m.type() === 'error') logs.push('console ' + m.text()) });
  await p.goto('' + (process.env.ELLIS_WEB ?? 'http://localhost:5173') + '/clinic'); // logged out: the one sign-in page
  await p.fill('#em', 'dana@valle.demo');
  await p.fill('#pw', 'ellis-demo');
  await p.click('button[type=submit]');
  await p.waitForSelector('text=Cases');
  await p.waitForTimeout(800);
  await p.screenshot({ path: './e2e-shots/c1-cases.png', fullPage: true });
  await p.click('text=María T.');
  await p.waitForSelector('text=Ready gate');
  await p.click('text=Demo tools');
  await p.click('text=Simulate remaining intake (demo)');
  await p.waitForTimeout(7000);
  await p.screenshot({ path: './e2e-shots/c2-detail.png', fullPage: false });
  await p.click('a[href="/clinic/review"]');
  await p.waitForSelector('text=Review queue');
  await p.waitForTimeout(1000);
  await p.screenshot({ path: './e2e-shots/c3-queue.png', fullPage: false });
  const items = await p.$$eval('.q-row', els => els.map(e => e.textContent));
  console.log('QUEUE', JSON.stringify(items));
  for (let i = 0; i < 6; i++) {
    const rows = await p.$$('.q-row');
    if (!rows.length) break;
    await rows[0].click();
    const label = await rows[0].textContent();
    await p.fill('#note', label.includes('ABSENCE') ? 'Applicant informed a licensed professional can assess continuous residence; proceeding is her choice.' : 'Reviewed; paid citation with receipt.');
    const btn = label.includes('ABSENCE') ? 'Clear with referral' : 'Clear';
    await p.click(`.q-detail button:text-is("${btn}")`);
    await p.waitForTimeout(1500);
  }
  await p.waitForTimeout(6000);
  await p.goto('' + (process.env.ELLIS_WEB ?? 'http://localhost:5173') + '/clinic/cases/c_maria');
  await p.waitForSelector('text=Ready gate');
  await p.waitForTimeout(1500);
  const gate = await p.textContent('.gate');
  console.log('GATE', gate);
  await p.screenshot({ path: './e2e-shots/c2-gate.png', fullPage: false });
  const ready = await p.$('button:text-is("Mark ready")');
  if (ready && await ready.isEnabled()) { await ready.click(); await p.waitForTimeout(1500); console.log('MARKED READY', await p.textContent('[role=status]')); }
  // applicant signs
  const a = await (await b.newContext({ viewport: { width: 420, height: 900 } })).newPage();
  // Her demo account logs in and lands on the chat; its next-step card leads to /review once the case is ready.
  await a.goto('' + (process.env.ELLIS_WEB ?? 'http://localhost:5173') + '/signin');
  await a.fill('#em', 'maria@valle.demo');
  await a.fill('#pw', 'ellis-demo');
  await a.click('button[type=submit]');
  await a.waitForSelector('#next');
  const sign = await a.$('#next a:text-is("Review and sign")');
  if (sign) { await sign.click(); await a.waitForSelector('.attest'); }
  await a.waitForTimeout(1000);
  await a.screenshot({ path: './e2e-shots/a8-review.png', fullPage: true });
  if (await a.$('.attest')) {
    await a.click('.attest input');
    await a.fill('#nm', 'Maria Torres');
    await a.click('button:text-is("Sign"), button:text-is("Firmar")');
    await a.waitForSelector('text=/Your packet is ready|Su paquete está listo/', { timeout: 20000 });
    await a.waitForTimeout(1500);
    await a.screenshot({ path: './e2e-shots/a9-packet.png', fullPage: true });
    console.log('PACKET', JSON.stringify(await a.$$eval('a.btn', els => els.map(e => e.textContent))));
  }
  console.log('ERRORS', logs.join('\n'));
  await b.close();
})();
