# flu-trend-tracker

流感监测趋势静态站：CDC 周报机器解析 + 城市百度指数代理，部署于 GitHub Pages。

## 怎么跑

```bash
pip install pdfplumber
python scripts/fetch_cdc.py --pages 4 --weeks 80   # CDC 抓取（增量, PDF 缓存复用）
python verify_page.py                              # 数据断言（CI 强制, 30 项）
python tests/test_parse_pdf.py                     # 解析 golden 回归（4 类措辞变体）
python -m http.server 8080                         # 本地预览
bash scripts/run_browser_fetch.sh --days 365       # 城市采集（需 webbridge + Edge 登录）
```

## 技术栈与结构

- 纯 Python 3 标准库 + pdfplumber（解析）；index.html 零外部依赖手写 SVG（禁止引入 CDN）。
- `scripts/fetch_cdc.py`：周报列表分页（30 页可回溯 2015 年）→ PDF 缓存 → pdfplumber 正则解析。
- `scripts/fetch_baidu_fast.py`：现役城市采集主路线；`fetch_baidu_via_browser.py` 为 UI 备用慢路线。
- 数据产物：`data/flu_national.json`（100 期两年窗口）、`data/flu_cities.json`（15 城 × 2 词 × 365 天）。

## 硬约束（违反必出事故）

- **百度指数 days ≤ 365**：超过后 API 静默切周粒度，按日写入造成日期错位污染（fast.py 已做拦截）。
- 百度指数是 TLS 指纹级风控：任何 urllib/curl 直连都 10018，必须经浏览器取 cipher-text。
- webbridge daemon 与 shell 会话共生：起 daemon 与采集必须在同一条 shell 命令内。
- 绝不重启/强杀 Edge：扩展断连等 30s 自动重连或开新标签页温和唤醒。
- `scripts/baidu_cookie.txt`、`scripts/cache/` 已 gitignore，严禁入库。
- 城市采集无法 CI 化（需本机浏览器实时凭证），CDC 由 GitHub Actions 周五自动跑。

## 约定

- CDC 周报措辞变体（全角括号/双右括号/裸 0/"未报告"=0）修复时必须同步加 golden 用例。
- 小城市指数 0 值是真实数据（脱敏阈值）；百度会回溯修订历史值，重采覆盖属正常。
- 文档事实以代码为准；README「城市级数据采集」节是现役路线唯一权威描述。

## 当前状态与下一步

- 就绪待部署：数据全绿（verify 30 项 + golden 32 项），git 未初始化，按 GIT_PUSH.md 手动推送。
- 下一步：用户推送 GitHub + 开 Pages；可选做新冠月度数据模块（见 README 路线图）。
