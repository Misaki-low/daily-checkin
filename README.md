# daily-checkin

雨云每日签到跑在 GitHub Actions 上，本机不再开浏览器。验证码用 **OpenCV 点选求解**（连通域切符号 + 双向 Chamfer 匹配），不依赖视觉模型额度。

SakuraFrp 继续留在原仓库 `Misaki-low/SakuraFrpQiandao`（Secrets 已配好），
这里只放它的「修复版 workflow」备查：`patches/sakurafrp_sign_fixed.yml`
（cron 加了北京 11:00 补签一次，解决 fork 仓库定时漂移）。

## 结构

```
.github/workflows/rainyun-pw.yml   ✅ 在用：每天 09:10 / 11:10（北京）签到雨云
.github/workflows/rainyun.yml      ⛔ 已禁用：旧的 GLM-4V 版，仅存档
.github/workflows/keepalive.yml    每 14 天空提交一次，防止定时任务被 GitHub 停用
rainyun/pw/auto.js                 Playwright 签到主程序（Node）
rainyun/pw/solve.py                验证码求解器（OpenCV，输出点选坐标）
rainyun/main.py                    旧版主程序（视觉模型路线），仅存档
deploy.py                          一键建库 / 推代码 / 写 Secrets
patches/                           SakuraFrp 原仓库的修复版 workflow
```

## 需要的 Secrets

| Secret | 说明 |
|---|---|
| `RAINYUN_COOKIES` | 雨云登录态 JSON（`rain-session`、`X-CSRF-Token` 等），**唯一必需** |
| `BASE_URL` / `API_KEY` / `MODEL` | 只有旧的 GLM 版用得到，新流程不需要 |

## 执行流程

1. 注入 cookie → 打开 `app.rainyun.com/account/reward/earn`
2. 查 `POST api.v2.rainyun.com/user/reward/tasks`，签到项 `Status=2` 直接退出（幂等）
3. 点「领取奖励」→ 等腾讯验证码 iframe → 截背景图 + 提示条 → `solve.py` 求坐标 → 依次点击 → 确定
4. 验证码通过后前端没自动提交时，用 ticket 自己 POST
5. 复查状态，`Status=2` 即成功

失败自动换题重试 5 轮；截图存 artifact（`cap_bg_*` / `cap_hint_*` / `fail.png`）。

## 登录态过期怎么办

`rain-session` 约 7 天有效，每天跑会自动续期。真失效了（日志出现「登录态失效」）：

1. 本机克隆仓库，`cd rainyun/pw && npm i && npx playwright install chromium`
2. 本机跑一次带登录模式的脚本（`auto.js --login`，用 `channel: 'msedge'` 或本机 chromium），登录后导出 cookie
3. 把 cookie JSON 更新到仓库 Secret `RAINYUN_COOKIES`
4. 手动 dispatch 一次 `rainyun-pw.yml` 验证

## 部署

1. `pat.txt` 里放一个 GitHub PAT（classic，勾 `repo` + `workflow`）。
2. `python deploy.py`：建公开仓库 → 推代码 → 写 Secrets。要私有加 `--private`。

## 备注

- 2026-11-19 迁移自本机版（`Rainyun-Qiandao`），本机目录已删。
- 旧 GLM 版 2026-11-14 起连续 5 次失败（验证码票据 + 海外 IP），已禁用，别再开。

<!-- reindex -->
