# flu-trend-tracker

流感监测趋势静态站：CDC 周报机器解析 + 中疾控多病原哨点监测 + 疾控局法定报告 + 城市百度指数代理，部署于 GitHub Pages。

## 怎么跑

```bash
pip install pdfplumber
python scripts/fetch_cdc.py --pages 4 --weeks 80   # 国家流感中心周报（增量, PDF 缓存复用）
python scripts/fetch_multipathogen.py --pages 8 --weeks 100  # 中疾控哨点监测（增量, HTML 缓存）
python scripts/fetch_notifiable.py                 # 疾控局月报（增量, HTML 缓存）
python verify_page.py                              # 数据断言（CI 强制, 43 项）
python tests/test_parse_pdf.py                     # 解析 golden 回归（4 类措辞变体）
python -m http.server 8080                         # 本地预览
bash scripts/run_browser_fetch.sh --days 365       # 城市采集（需 webbridge + Edge 登录）
```

## 技术栈与结构

- 纯 Python 3 标准库 + pdfplumber（解析）；index.html 零外部依赖手写 SVG（禁止引入 CDN）。
- `scripts/fetch_cdc.py`：周报列表分页（30 页可回溯 2015 年）→ PDF 缓存 → pdfplumber 正则解析。
- `scripts/fetch_multipathogen.py`：中疾控哨点监测，**HTML 表格结构化解析**（`<table>/<tr>/<td>`
  逐行提取）。不使用整页文本正则——PDF 转写断字噪声（`+ 2.2`、`鼻 病毒`、跨 span 断字、
  `第 4 2周`）会把相邻数值错误粘连。2025 年 4—5 月合并期宽表拆为逐周记录（无 ILI%）。
- `scripts/fetch_notifiable.py`：疾控局月报。列表页 JS 渲染、文章数据以 JSON 内嵌页面对象
  （`saT`=标题 / `aU`=URL / `id`），必须按 `'{"aTs"'` 切分对象独立配对，禁止跨对象正则。
- `scripts/fetch_baidu_fast.py`：现役城市采集主路线；`fetch_baidu_via_browser.py` 为 UI 备用慢路线。
- 数据产物：`data/flu_national.json`（100 期）、`data/flu_cities.json`（15 城 × 2 词 × 365 天）、
  `data/flu_multipathogen.json`（103 周 × 11 病原体）、`data/flu_notifiable.json`（47 个月）。

## 硬约束（违反必出事故）

- **百度指数 days ≤ 365**：超过后 API 静默切周粒度，按日写入造成日期错位污染（fast.py 已做拦截）。
- 百度指数是 TLS 指纹级风控：任何 urllib/curl 直连都 10018，必须经浏览器取 cipher-text。
- webbridge daemon 与 shell 会话共生：起 daemon 与采集必须在同一条 shell 命令内。
- 绝不重启/强杀 Edge：扩展断连等 30s 自动重连或开新标签页温和唤醒。
- `scripts/baidu_cookie.txt`、`scripts/cache/` 已 gitignore，严禁入库。
- 城市采集无法 CI 化（需本机浏览器实时凭证）；CDC/多病原/法定报告由 GitHub Actions 周五自动跑。

## 约定

- CDC 周报措辞变体（全角括号/双右括号/裸 0/"未报告"=0）修复时必须同步加 golden 用例。
- 多病原表1 解析改动后必须全量 `--force` 重解析并跑 verify（11 键齐全 + spot check）。
- 小城市指数 0 值是真实数据（脱敏阈值）；百度会回溯修订历史值，重采覆盖属正常。
- 文档事实以代码为准；README「城市级数据采集」节是现役路线唯一权威描述。

## 当前状态与下一步

- 已上线 https://schalkiii.github.io/flu-trend-tracker/ ：图1-6 + 表1，数据全绿
  （verify 43 项 + golden 32 项），CI 每周五自动更新三个数据源。
- 下一步：可选做新冠月度数据模块（见 README 路线图）。
