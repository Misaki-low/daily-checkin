/**
 * 雨云登录态导出（本机跑，用于刷新 RAINYUN_COOKIES）
 *
 *   npm i && npx playwright install chromium
 *   node login.js
 *
 * 会打开浏览器窗口，手动登录雨云（建议勾「7 天内免登录」），登录成功后
 * 把 cookie 写到同目录 cookies.json，内容整段贴进仓库 Secret RAINYUN_COOKIES。
 */
const fs = require('fs');
const os = require('os');
const path = require('path');
const { chromium } = require('playwright');

const PROFILE = path.join(__dirname, '.login-profile');
const OUT = path.join(__dirname, 'cookies.json');
const START = 'https://app.rainyun.com/account/reward/earn';

(async () => {
  const ctx = await chromium.launchPersistentContext(PROFILE, {
    headless: false,
    viewport: { width: 1440, height: 1000 },
    locale: 'zh-CN',
  });
  const page = ctx.pages()[0] || (await ctx.newPage());
  await page.goto(START, { waitUntil: 'domcontentloaded', timeout: 90000 }).catch(() => {});
  console.log('窗口已打开，请登录雨云（勾选 7 天免登录）。登录成功后脚本自动收尾，最多等 10 分钟。');

  const deadline = Date.now() + 10 * 60 * 1000;
  let ok = false;
  while (Date.now() < deadline) {
    await page.waitForTimeout(3000);
    if (!/auth\/login/i.test(page.url())) { ok = true; break; }
  }
  if (!ok) {
    console.log('超时，未检测到登录成功');
    await ctx.close();
    process.exit(2);
  }

  await page.waitForTimeout(3000);
  const cookies = await ctx.cookies('https://app.rainyun.com');
  const out = {};
  for (const c of cookies) out[c.name] = c.value;
  fs.writeFileSync(OUT, JSON.stringify(out, null, 2), 'utf8');
  console.log('✅ 已写入 ' + OUT + '（' + cookies.length + ' 条 cookie）');
  console.log('   cookie 名字：' + cookies.map((c) => c.name).join(', '));
  console.log('   下一步：把文件内容整段复制到仓库 Secret RAINYUN_COOKIES');
  await ctx.close();
  process.exit(0);
})().catch((e) => { console.error('失败：', e.message); process.exit(1); });
