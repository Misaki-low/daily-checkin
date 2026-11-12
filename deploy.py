#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
一键把 daily-checkin 部署到 GitHub。

准备：
  1. secrets.env 里的雨云 Cookie / 智谱 key 已预填，一般不用改
  2. 把 GitHub PAT（classic，勾 repo）写进同目录 pat.txt

用法：
  python deploy.py            # 建公开仓库
  python deploy.py --private  # 建私有仓库

流程：建仓库 → git 推代码 → 写 Secrets → 触发一次 SakuraFrp 测试。
"""
import base64
import json
import os
import subprocess
import sys
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_NAME = "daily-checkin"
REPO_DESC = "每日签到自动化（SakuraFrp / 雨云）"


def req(method, url, token=None, data=None):
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "deploy-script"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    body = None
    if data is not None:
        headers["Content-Type"] = "application/json"
        body = json.dumps(data).encode("utf-8")
    r = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(r, timeout=60) as resp:
            return resp.status, json.loads(resp.read().decode() or "{}")
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode() or "{}")


def load_env(path):
    d = {}
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            d[k.strip()] = v.strip()
    return d


def main():
    private = "--private" in sys.argv

    pat_path = os.path.join(HERE, "pat.txt")
    if not os.path.exists(pat_path):
        print("缺少 pat.txt（放一个 GitHub PAT，classic 勾 repo 权限）")
        return 1
    pat = open(pat_path, encoding="utf-8").read().strip()
    if not pat:
        print("pat.txt 是空的")
        return 1

    secrets = load_env(os.path.join(HERE, "secrets.env"))
    if not secrets.get("RAINYUN_COOKIES"):
        print("secrets.env 里 RAINYUN_COOKIES 是空的")
        return 1

    # 1. 拿账号名
    code, me = req("GET", "https://api.github.com/user", pat)
    if code != 200:
        print("PAT 无效：", me.get("message"))
        return 1
    owner = me["login"]
    print(f"账号: {owner}")

    # 2. 建仓库
    code, repo = req("POST", "https://api.github.com/user/repos", pat, {
        "name": REPO_NAME, "description": REPO_DESC, "private": private, "auto_init": False,
    })
    if code in (201, 200):
        print(f"仓库已创建: {owner}/{REPO_NAME} ({'私有' if private else '公开'})")
    elif code == 422:
        print(f"仓库已存在，直接复用: {owner}/{REPO_NAME}")
    else:
        print("建仓库失败：", repo.get("message"))
        return 1

    # 3. 推代码
    git = ["git"]
    subprocess.run(git + ["-C", HERE, "init", "-q"], check=False)
    subprocess.run(git + ["-C", HERE, "add", "-A"], check=False)
    subprocess.run(git + ["-C", HERE, "commit", "-q", "-m", "init daily-checkin", "--allow-empty"], check=False)
    subprocess.run(git + ["-C", HERE, "branch", "-M", "main"], check=False)
    remote = f"https://x-access-token:{pat}@github.com/{owner}/{REPO_NAME}.git"
    subprocess.run(git + ["-C", HERE, "remote", "remove", "origin"], check=False)
    subprocess.run(git + ["-C", HERE, "remote", "add", "origin", remote], check=False)
    r = subprocess.run(git + ["-C", HERE, "push", "-u", "origin", "main", "--force"], check=False,
                       capture_output=True, text=True)
    if r.returncode != 0:
        print("推送失败：")
        print(r.stderr[-2000:])
        return 1
    print("代码已推送")

    # 4. 写 Secrets
    try:
        import nacl.public
        import nacl.encoding
        has_nacl = True
    except ImportError:
        has_nacl = False

    if not has_nacl:
        print("\n本机没有 pynacl，无法自动写 Secrets。请先 `pip install pynacl` 再跑一次，")
        print("或手动到仓库 Settings → Secrets 添加：")
        for k in ["RAINYUN_COOKIES", "BASE_URL", "API_KEY", "MODEL"]:
            print(f"  {k}")
        return 1

    code, pk = req("GET", f"https://api.github.com/repos/{owner}/{REPO_NAME}/actions/secrets/public-key", pat)
    if code != 200:
        print("取公钥失败：", pk.get("message"))
        return 1
    pub = nacl.public.PublicKey(base64.b64decode(pk["key"]))
    for name in ["RAINYUN_COOKIES", "BASE_URL", "API_KEY", "MODEL"]:
        val = secrets.get(name, "")
        if not val:
            print(f"跳过空 Secret: {name}")
            continue
        sealed = base64.b64encode(nacl.public.SealedBox(pub).encrypt(val.encode())).decode()
        code, res = req("PUT", f"https://api.github.com/repos/{owner}/{REPO_NAME}/actions/secrets/{name}",
                        pat, {"encrypted_value": sealed, "key_id": pk["key_id"]})
        print(f"Secret {name}: {'ok' if code in (201, 204) else '失败 ' + str(res.get('message'))}")

    print("\n完成。到 Actions 页手动点一次 workflow_dispatch 测试，或等明天定时触发。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
