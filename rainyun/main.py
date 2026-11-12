"""
雨云每日签到（GitHub Actions 版）

依赖环境变量（通过仓库 Secrets 注入）：
  RAINYUN_COOKIES    JSON 字符串，形如 {"rain-session":"...","user-data":"...","X-CSRF-Token":"...","dev-code":"..."}
  BASE_URL           视觉模型 OpenAI 兼容接口（默认智谱）
  API_KEY            视觉模型 key
  MODEL              视觉模型名（默认 glm-4.1v-thinking-flash）

流程：先查状态 → 未签则开浏览器点「领取奖励」→ 解腾讯「依次点选」验证码 → 校验状态。
返回码 0=成功/已签，1=失败。
"""
import base64
import json
import os
import random
import re
import sys
import time

import requests
from playwright.sync_api import sync_playwright
from openai import OpenAI

BASE_URL = os.environ.get("BASE_URL", "https://open.bigmodel.cn/api/paas/v4/")
API_KEY = os.environ.get("API_KEY", "")
MODEL = os.environ.get("MODEL", "glm-4.1v-thinking-flash")
MAX_TRY = int(os.environ.get("MAX_TRY", "8"))

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/157.0.0.0 Safari/537.36")


def log(*a):
    print(*a, flush=True)


def load_cookies() -> dict:
    raw = os.environ.get("RAINYUN_COOKIES", "")
    if not raw:
        raise ValueError("RAINYUN_COOKIES 未设置")
    return json.loads(raw)


def status_of(cookies: dict) -> str:
    csrf = cookies.get("X-CSRF-Token", "")
    cookie_header = "; ".join(f"{k}={v}" for k, v in cookies.items())
    try:
        r = requests.get(
            "https://api.v2.rainyun.com/user/reward/tasks",
            headers={
                "Cookie": cookie_header,
                "X-CSRF-Token": csrf,
                "RYS": f"{time.time():.3f}",
                "Accept": "application/json",
                "Origin": "https://app.rainyun.com",
                "Referer": "https://app.rainyun.com/",
                "User-Agent": UA,
            },
            timeout=30,
        )
        d = r.json()
        tasks = d.get("data") or []
        t = next((x for x in tasks if x.get("Name") == "每日签到"), None)
        if not t:
            return "unknown"
        return "claimable" if t.get("Status") == 1 else ("done" if t.get("Status") == 2 else f"status{t.get('Status')}")
    except Exception as e:
        log("状态查询异常:", e)
        return "api-error"


def solve_captcha(img_bytes: bytes):
    """把验证码截图交给视觉模型，返回归一化(0-1000)顺序点击坐标。"""
    client = OpenAI(base_url=BASE_URL, api_key=API_KEY)
    prompt = (
        "这是腾讯验证码（依次点选）。顶部有一行提示，指示需要按顺序点选的 3 个目标图标；"
        "下方是包含很多干扰图标的大图。"
        "请按提示顺序，在大图中找到对应的目标，给出每个目标中心的坐标。"
        "坐标以整张截图的宽和高分别归一化到 0-1000 的整数（左上角 0,0，右下角 1000,1000）。"
        '只输出 JSON，不要解释：{"count":3,"points":[[x,y],[x,y],[x,y]],"note":"你看到的提示"}'
    )
    b64 = base64.b64encode(img_bytes).decode()
    for i in range(3):
        try:
            resp = client.chat.completions.create(
                model=MODEL,
                messages=[{"role": "user", "content": [
                    {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}},
                    {"type": "text", "text": prompt},
                ]}],
                stream=False,
            )
            content = resp.choices[0].message.content
            log("模型输出:", content[:300])
            m = re.search(r"\{[\s\S]*\}", content)
            if not m:
                continue
            obj = json.loads(m.group(0))
            pts = obj.get("points")
            if isinstance(pts, list) and len(pts) >= 1:
                return obj
        except Exception as e:
            log("视觉模型异常:", e)
            time.sleep(3)
    return None


def run() -> int:
    cookies = load_cookies()
    log("初始状态:", status_of(cookies))
    if status_of(cookies) == "done":
        log("✅ 今日已签到")
        return 0

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage",
                  "--disable-blink-features=AutomationControlled", "--lang=zh-CN"],
        )
        ctx = browser.new_context(viewport={"width": 1366, "height": 900}, locale="zh-CN",
                                  timezone_id="Asia/Shanghai", user_agent=UA)
        ctx.add_init_script("Object.defineProperty(navigator, 'webdriver', { get: () => undefined });")
        ctx.add_cookies([
            {"name": k, "value": v, "domain": ".rainyun.com", "path": "/",
             "httpOnly": k == "rain-session", "secure": True, "sameSite": "Lax"}
            for k, v in cookies.items()
        ])
        page = ctx.new_page()
        page.set_default_timeout(20000)

        page.goto("https://app.rainyun.com/account/reward/earn", wait_until="domcontentloaded", timeout=90000)
        time.sleep(random.uniform(4, 6))

        for attempt in range(1, MAX_TRY + 1):
            log(f"—— 第 {attempt}/{MAX_TRY} 轮 ——")
            btn = page.locator("text=领取奖励").first()
            if btn.count() == 0:
                log("页面没有「领取奖励」，状态:", status_of(cookies))
                break
            try:
                btn.click(timeout=15000)
            except Exception as e:
                log("点领取失败:", str(e).split("\n")[0], "→ 刷新重来")
                page.reload(wait_until="domcontentloaded")
                time.sleep(random.uniform(4, 6))
                continue
            time.sleep(random.uniform(2.5, 4))

            ifr = page.locator('iframe[src*="turing.captcha"], iframe[src*="captcha"]').first()
            if ifr.count() == 0:
                log("没出现验证码，直接校验状态")
                time.sleep(3)
                if status_of(cookies) == "done":
                    log("✅ 签到成功")
                    browser.close()
                    return 0
                continue

            box = ifr.bounding_box()
            if not box:
                log("验证码 iframe 无边界")
                continue
            shot = ifr.screenshot()
            res = solve_captcha(shot)
            if not res or not res.get("points"):
                log("识别失败，刷新重来")
                page.reload(wait_until="domcontentloaded")
                time.sleep(random.uniform(4, 6))
                continue
            log("模型结果:", res)

            frame = page.frame_locator('iframe[src*="turing.captcha"], iframe[src*="captcha"]').first()
            for (nx, ny) in res["points"]:
                cx = box["x"] + nx / 1000 * box["width"]
                cy = box["y"] + ny / 1000 * box["height"]
                # 拟人化移动
                page.mouse.move(cx + random.uniform(-60, 60), cy + random.uniform(-50, 50), steps=5)
                time.sleep(random.uniform(0.12, 0.26))
                page.mouse.click(cx, cy)
                time.sleep(random.uniform(0.4, 0.85))

            time.sleep(random.uniform(1.2, 1.8))
            # 点「确定」：优先 iframe 内按钮，失败按坐标兜底
            try:
                ok = frame.locator("text=确定").first()
                if ok.count() and ok.is_visible():
                    ok.click(timeout=5000)
                    log("已点确定")
            except Exception:
                page.mouse.click(box["x"] + box["width"] * 0.88, box["y"] + box["height"] * 0.93)
                log("已点确定（坐标兜底）")

            time.sleep(random.uniform(4, 6))
            st = status_of(cookies)
            log("状态:", st)
            if st == "done":
                log("✅ 签到成功")
                browser.close()
                return 0
            page.reload(wait_until="domcontentloaded")
            time.sleep(random.uniform(4, 6))

        final = status_of(cookies)
        log("最终状态:", final)
        browser.close()
        return 0 if final == "done" else 1


if __name__ == "__main__":
    try:
        sys.exit(run())
    except Exception as e:
        log("ERROR", e)
        sys.exit(1)
