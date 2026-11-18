/**
 * 雨云每日签到（GitHub Actions 版 · 本地 OpenCV 求解器）
 *
 * 与旧版（视觉模型识别）的区别：验证码用 solve.py 的连通域 + Chamfer 匹配来解，
 * 不依赖外部模型额度，行为与本机版一致。
 *
 * 环境变量：
 *   RAINYUN_COOKIES  JSON 字符串：{"rain-session":"...","X-CSRF-Token":"...", ...}
 *
 * 退出码：0 成功/已签；1 失败；2 登录态失效
 */
const fs = require('fs');
const path = require('path');
const { execFileSync } = require('child_process');
const { chromium } = require('playwright');

const DIR = __dirname;
const ART = path.join(DIR, 'artifacts');
const EARN = 'https://app.rainyun.com/account/reward/earn';
const API_TASKS = 'https://api.v2.rainyun.com/user/reward/tasks';
const APPID = '2039519451';
const MAX_TRY = Number(process.env.MAX_TRY || 5);
const TEST = process.argv.includes('--test');

const UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
  + '(KHTML, like Gecko) Chrome/157.0.0.0 Safari/537.36';

if (!fs.existsSync(ART)) fs.mkdirSync(ART, { recursive: true });

function log(...a) {
  console.log(`[${new Date().toISOString()}]`, ...a);
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const rnd = (a, b) => Math.floor(a + Math.random() * (b - a));

function loadCookies() {
  const raw = process.env.RAINYUN_COOKIES || '';
  if (!raw) throw new Error('RAINYUN_COOKIES 未设置');
  return JSON.parse(raw);
}

async function readTasks(page) {
  return page.evaluate(async (url) => {
    try {
      const m = document.cookie.match(/X-CSRF-Token=([^;]+)/);
      const r = await fetch(url, {
        credentials: 'include',
        headers: m ? { 'X-CSRF-Token': m[1] } : {},
      });
      if (!r.ok) return { error: 'http_' + r.status };
      return await r.json();
    } catch (e) {
      return { error: String(e) };
    }
  }, API_TASKS);
}

function signinStatus(payload) {
  const list = Array.isArray(payload && payload.data) ? payload.data : [];
  const t = list.find((x) => String(x.Name || x.name || '').includes('签到'));
  return t ? t.Status : null;
}

async function solveCaptcha(frame, tag) {
  const bg = path.join(ART, `cap_bg_${tag}.png`);
  const hint = path.join(ART, `cap_hint_${tag}.png`);
  await frame.locator('#slideBg').screenshot({ path: bg });
  await frame.locator('div.tc-instruction-icon').screenshot({ path: hint });
  const txt = await frame.locator('#instructionText').innerText().catch(() => '');
  let out;
  try {
    out = execFileSync('python', [path.join(DIR, 'solve.py'), bg, hint], { encoding: 'utf8', timeout: 120000 });
  } catch (e) {
    log('  求解器异常：' + e.message.slice(0, 200));
    return null;
  }
  let data;
  try { data = JSON.parse(out.trim().split('\n').pop()); } catch (_) {
    log('  求解输出无法解析：' + String(out).slice(0, 200));
    return null;
  }
  if (data.error) { log('  求解失败：' + data.error); return null; }
  log(`  提示「${String(txt).replace(/\s+/g, ' ')}」→ 坐标 ${JSON.stringify(data.points)} 分数 ${JSON.stringify(data.scores)}`);

  const op = frame.locator('#tcOperation');
  for (const [x, y] of data.points) {
    await op.click({ position: { x, y }, timeout: 10000 }).catch((e) => log('  点击失败：' + e.message.slice(0, 100)));
    await sleep(rnd(280, 620));
  }
  await sleep(rnd(300, 700));
  const btn = frame.locator('div.tc-action.verify-btn').first();
  if (await btn.count()) {
    await btn.click({ timeout: 8000 }).catch(() => {});
    log('  已点「确定」');
  }
  return data;
}

async function captchaResult(page, timeoutMs = 25000) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    const r = await page.evaluate(() => window.__capResult || null).catch(() => null);
    if (r) return r;
    await sleep(800);
  }
  return null;
}

async function shoot(page, name) {
  try { await page.screenshot({ path: path.join(ART, name), fullPage: true }); } catch (_) {}
}

async function main() {
  const cookies = loadCookies();
  log('==== 开始 ====', TEST ? '(测试模式)' : '');

  const browser = await chromium.launch({
    headless: true,
    args: ['--no-sandbox', '--disable-dev-shm-usage', '--disable-blink-features=AutomationControlled', '--lang=zh-CN'],
  });
  const ctx = await browser.newContext({
    viewport: { width: 1440, height: 1000 },
    deviceScaleFactor: 2,
    locale: 'zh-CN',
    timezoneId: 'Asia/Shanghai',
    userAgent: UA,
  });
  await ctx.addInitScript("Object.defineProperty(navigator,'webdriver',{get:()=>undefined});");
  await ctx.addCookies(Object.entries(cookies).map(([name, value]) => ({
    name, value, domain: '.rainyun.com', path: '/', secure: true, sameSite: 'Lax',
  })));

  const page = await ctx.newPage();
  page.setDefaultTimeout(45000);

  await page.goto(EARN, { waitUntil: 'networkidle', timeout: 90000 }).catch((e) => log('打开页面：' + e.message));
  await sleep(2500);

  if (/auth\/login/i.test(page.url())) {
    log('❌ 登录态失效（cookie 过期），需要本机重新执行 node auto.js --login 后更新 RAINYUN_COOKIES');
    await shoot(page, 'login_redirect.png');
    await browser.close();
    return 2;
  }
  log('已登录，页面：' + page.url());

  const before = await readTasks(page);
  const st = signinStatus(before);
  log('签到状态 Status =', st, '(2=已完成 / 1=可领取)');
  if (st === 2 && !TEST) {
    log('✅ 今日已签到，无需操作');
    await browser.close();
    return 0;
  }
  if (st === null) {
    log('⚠️ 读不到签到任务，返回体：' + JSON.stringify(before).slice(0, 300));
  }

  await page.evaluate((appid) => {
    window.__capResult = null;
    window.__capObj = new window.TencentCaptcha(appid, (r) => {
      window.__capResult = { ret: r.ret, ticket: r.ticket, randstr: r.randstr, errorCode: r.errorCode };
    });
  }, APPID).catch((e) => log('注入回调失败：' + e.message.slice(0, 120)));

  let solved = null;
  for (let attempt = 1; attempt <= MAX_TRY; attempt++) {
    log(`—— 第 ${attempt}/${MAX_TRY} 轮 ——`);
    if (attempt === 1 && !TEST) {
      const btn = page.locator('a.badge.badge-success').filter({ hasText: '领取奖励' }).first();
      if (!(await btn.count())) {
        log('页面没找到「领取奖励」按钮，改为直接弹验证码');
        await page.evaluate(() => window.__capObj && window.__capObj.show());
      } else {
        await btn.click({ timeout: 15000 }).catch((e) => log('点领取失败：' + e.message.slice(0, 120)));
      }
    } else {
      await sleep(600);
      await page.evaluate(() => window.__capObj && window.__capObj.show()).catch(() => {});
    }

    let frame = null;
    for (let i = 0; i < 20; i++) {
      await sleep(700);
      frame = page.frames().find((f) => /turing\.captcha/.test(f.url()));
      if (frame) break;
    }
    if (!frame) { log('  没等到验证码弹窗'); continue; }

    await sleep(rnd(1200, 2000));
    solved = await solveCaptcha(frame, attempt);
    if (!solved) continue;

    const res = await captchaResult(page, 20000);
    if (!res) { log('  未收到验证码回调'); continue; }
    log('  验证码结果 ret=' + res.ret + (res.errorCode ? ' errorCode=' + res.errorCode : '') + (res.ticket ? ' 已拿到 ticket' : ''));
    if (res.ret === 0 && res.ticket) {
      log('  ✅ 验证码通过');
      break;
    }
    log('  ✗ 验证码未通过，重试');
    solved = null;
    await page.evaluate(() => { window.__capResult = null; });
  }

  if (TEST) {
    log(solved ? '测试通过：点选流程可用（未提交）' : '测试失败：' + MAX_TRY + ' 轮都没过');
    await shoot(page, 'test_last.png');
    await browser.close();
    return solved ? 0 : 1;
  }

  await sleep(6000);
  let after = await readTasks(page);
  let st2 = signinStatus(after);
  if (st2 !== 2) {
    const res = await page.evaluate(() => window.__capResult || null).catch(() => null);
    if (res && res.ticket) {
      log('前端未完成提交，用 ticket 直接调接口');
      const r = await page.evaluate(async ({ url, vt, vr }) => {
        const m = document.cookie.match(/X-CSRF-Token=([^;]+)/);
        const resp = await fetch(url, {
          method: 'POST',
          credentials: 'include',
          headers: Object.assign({ 'Content-Type': 'application/json' }, m ? { 'X-CSRF-Token': m[1] } : {}),
          body: JSON.stringify({ task_name: '每日签到', verifyCode: '', vticket: vt, vrandstr: vr }),
        });
        return { status: resp.status, body: await resp.text() };
      }, { url: API_TASKS, vt: res.ticket, vr: res.randstr }).catch((e) => ({ status: 0, body: String(e) }));
      log('提交返回 ' + r.status + ' ' + String(r.body).slice(0, 200));
      await sleep(2500);
      after = await readTasks(page);
      st2 = signinStatus(after);
    }
  }

  await shoot(page, st2 === 2 ? 'success.png' : 'fail.png');
  await browser.close();
  if (st2 === 2) { log('✅ 签到成功'); return 0; }
  log('❌ 签到失败，最终状态 Status=' + st2);
  return 1;
}

main().then((code) => process.exit(code)).catch((e) => {
  log('异常退出：' + (e && e.stack ? e.stack : e));
  process.exit(1);
});
