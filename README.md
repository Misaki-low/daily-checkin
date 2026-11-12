# daily-checkin

把雨云每日签到放到 GitHub Actions 上跑，本机不再开浏览器。

SakuraFrp 继续留在原仓库 `Misaki-low/SakuraFrpQiandao`（Secrets 已配好），
这里只放它的「修复版 workflow」备查：`patches/sakurafrp_sign_fixed.yml`
（cron 加了北京 11:00 补签一次，解决 fork 仓库定时漂移）。

## 结构

```
.github/workflows/rainyun.yml   每天 09:05（北京）签到雨云
.github/workflows/keepalive.yml 每 14 天空提交一次，防止定时任务被 GitHub 停用
rainyun/main.py                 签到主程序（Playwright + 智谱 GLM-4V 解腾讯点选）
deploy.py                       一键建库 / 推代码 / 写 Secrets
patches/                        SakuraFrp 原仓库的修复版 workflow
```

## 需要的 Secrets

| Secret | 说明 |
|---|---|
| `RAINYUN_COOKIES` | 雨云登录态 JSON（`rain-session`、`X-CSRF-Token` 等） |
| `BASE_URL` | 视觉模型 OpenAI 兼容接口（智谱：`https://open.bigmodel.cn/api/paas/v4/`） |
| `API_KEY` | 视觉模型 key |
| `MODEL` | 视觉模型名（`glm-4.1v-thinking-flash`） |

## 部署

1. `pat.txt` 里放一个 GitHub PAT（classic，勾 `repo` + `workflow`）。
2. `python deploy.py`：建公开仓库 → 推代码 → 写 Secrets。要私有加 `--private`。

## 备注

- 视觉模型用的是「智谱 GLM-4V」，免费额度够每天一次签到。
- 雨云验证码识别失败会自动刷新重试，默认最多 8 轮。
