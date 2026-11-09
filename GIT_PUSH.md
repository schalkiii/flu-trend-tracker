# git 推送命令序列（Windows Git Bash / PowerShell 均可）

> 作用域：`flu-trend-tracker/` 项目目录。
> 替换 `<你的用户名>` 后逐段执行。

## 1. 初始化仓库并首次提交

```bash
cd C:/Users/qi.shao/WorkBuddy/2026-11-05-16-40-57/flu-trend-tracker

git init -b main
git add .
git status                    # 确认: baidu_cookie.txt / scripts/cache/ 不在列表中
git commit -m "init: flu trend tracker (CDC weekly + baidu index city module)"
```

## 2. 在 GitHub 建仓并推送

先在 GitHub 网页新建**公开**仓库 `flu-trend-tracker`（不要勾选初始化 README），然后：

```bash
git remote add origin https://github.com/<你的用户名>/flu-trend-tracker.git
git push -u origin main
```

## 3. 开启 GitHub Pages

网页操作：仓库 **Settings → Pages → Source 选 `Deploy from a branch` → Branch 选 `main` / `/ (root)` → Save**。

约 1-2 分钟后可访问：`https://<你的用户名>.github.io/flu-trend-tracker/`

## 4. 验证自动化

```bash
# 手动触发一次 Actions（验证周报抓取全链路）
# 网页操作: Actions -> Update flu data -> Run workflow
```

后续每周五自动运行；也可本地随时手动：

```bash
python scripts/fetch_cdc.py --pages 4 --weeks 80 && python verify_page.py
```

## 5.（可选）城市数据更新

城市级百度指数**无法在 CI 采集**（接口 TLS 指纹风控，需本机浏览器实时取凭证）。
本地运行：

```bash
bash scripts/run_browser_fetch.sh          # webbridge daemon 托管 + 现役快速路线
git add data/flu_cities.json && git commit -m "data: update city index" && git push
```

详见 README「城市级数据采集」节。
