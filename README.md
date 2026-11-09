# 流感监测趋势 · 每周自动更新

基于中国国家流感中心《中国流感监测周报》公开数据，自动抓取、解析并展示流感活动趋势。

**在线访问**：`https://<你的GitHub用户名>.github.io/flu-trend-tracker/`

## 内容

- 南方 / 北方省份 ILI%（流感样病例就诊百分比）走势（两年窗口，可缩放）
- 流感病毒检测阳性率走势（南方 / 北方 / 全国）
- 流感样病例暴发疫情周报起数
- **城市级趋势（百度指数代理）**：15 城 × 「发烧」「奥司他韦」双关键词，近一年逐日，城市切换 + 时间缩放
- **多病原分解（中疾控哨点监测）**：11 种呼吸道病原体门急诊阳性率（2024W46 起，103 周），病原体切换，叠 ILI% 双轴参考
- **法定报告流感月度发病数（国家疾控局）**：丙类法定传染病报告病例数（2022-11 起，47 个月）
- 明细数据表（含 A/B 型别构成、暴发起数）

数据为官方公开周报的机器解析结果，仅供参考，不构成任何医疗建议。

## 架构

```
.github/workflows/update-data.yml   GitHub Actions: 每周五自动抓取（CDC + 多病原 + 法定报告）
scripts/fetch_cdc.py                国家流感中心周报抓取 + PDF 解析（列表分页可回溯到 2015 年）
scripts/fetch_multipathogen.py      中疾控哨点监测抓取（HTML 表格结构化解析, 11 病原体 × 门急诊/住院）
scripts/fetch_notifiable.py         国家疾控局月报抓取（法定传染病流感发病数/死亡数）
scripts/fetch_baidu_fast.py         城市级采集 · 现役主路线（webbridge 凭证 + 本地直连）
scripts/fetch_baidu_via_browser.py  城市级采集 · 备用慢路线（webbridge UI 交互，仅 5 城码表）
scripts/run_browser_fetch.sh        webbridge daemon 托管入口（起 daemon → 等扩展 → 调主路线）
data/flu_national.json              全国/南北数据（每次更新提交回仓库）
data/flu_cities.json                城市级数据（增量合并，一年逐日）
data/flu_multipathogen.json         多病原哨点监测（2024W46 起, 增量合并）
data/flu_notifiable.json            法定报告月度病例（2022-11 起, 增量合并）
index.html                          自包含单页（内联 CSS/JS, 手写 SVG 图表, 无外部依赖）
verify_page.py                      数据完整性断言（CI 中强制执行, 43 项）
tests/test_parse_pdf.py             CDC PDF 解析 golden 回归（4 类措辞变体）
AUDIT-REPORT-2026-11-09.md          项目审计报告
```

- 定时任务每周五（UTC 16:10 / 北京时间周六 00:10）运行，`--pages 4 --weeks 80` 增量维护
  两年窗口，已解析期次自动跳过；数据有变化才 commit，commit 触发 GitHub Pages 重新部署。
- 页面零外部依赖（无 CDN、无框架），适配移动端。

## 多病原与法定报告数据说明

- **多病原**（`fetch_multipathogen.py`）：中疾控《全国急性呼吸道传染病哨点监测情况》
  （chinacdc.cn），HTML 表格结构化解析（`<table>/<tr>/<td>` 逐行提取，容忍 PDF 转写
  断字噪声如 `+ 2.2`、`鼻 病毒`、跨 span 断字、`第 4 2周`）。2025 年 4—5 月为多月
  合并发布宽表，已拆为逐周记录（该段无 ILI%）。103 周 × 11 病原体全部齐全，
  流感阳性率与国家流感中心周报 spot check 一致（差 < 15pp，口径差异）。
- **法定报告**（`fetch_notifiable.py`）：国家疾控局《全国（法定）传染病疫情概况》
  （ndcpa.gov.cn），列表页为 JS 渲染、文章数据以 JSON 内嵌，按对象切分解析。
  47 个月（2022-11 起）连续无断档，官方公报数字 spot check 全部命中。
- 两个数据源的抓取频率均随 CI 每周一次，缓存目录 `scripts/cache/mp/`、`scripts/cache/nf/`。

## 城市级数据采集（百度指数 · 现役路线）

百度指数接口是 **TLS 指纹级风控**：Python urllib / curl 直连一律被拦（status 10018），
纯 Cookie + 本地 AES cipher-text 的老路线已死。现役路线绕过方式：

1. 本地运行 [kimi-webbridge](https://github.com/) daemon（`~/.kimi-webbridge/bin/kimi-webbridge.exe`），
   Edge 装 Kimi 扩展并保持登录 index.baidu.com。
2. `bash scripts/run_browser_fetch.sh`（托管 daemon 生命周期：启动 → 等扩展连接 → 调用采集器）。
   采集器 `fetch_baidu_fast.py --days 365` 让浏览器搜一次词，从原生请求头捕获
   **cipher-text + 完整 Cookie**，之后全部本地 curl 直连任意城市 × 词组合（~2s/组）。
3. 数据写入 `data/flu_cities.json`，commit 推送后网页城市板块自动展示。

注意事项（均为实测经验）：

- **days 必须 ≤ 365**：超过后 API 静默切换周粒度，按日写入会造成日期错位污染
  （采集器已做上限拦截，`--days 400` 会直接拒绝执行）。
- daemon 与启动它的 shell 会话共生，必须在同一条 shell 命令内完成「启动 → 采集」。
- Edge 扩展断连时不要重启浏览器：等 30s 自动重连，或开新标签页温和唤醒 service worker。
- 百度会**回溯修订**历史值（如北京某日 147→165），重采会覆盖旧值，属正常。
- 小体量城市（重庆/杭州等）低于脱敏阈值的日子指数为 0，是真实数据不是采集失败。
- ptbk 解密走本地替换表（无 AES），词与词之间温和限速 1.5-2s。

城市码表与关键词在 `fetch_baidu_fast.py` 顶部配置（现役 15 城，社区逆向维护映射）。
`fetch_baidu_via_browser.py` 是 UI 交互备用路线（~40s/词），仅含 5 城码表，用于
直连路线凭证失效时人工兜底。

## 本地运行

```bash
pip install pdfplumber
python scripts/fetch_cdc.py --pages 4 --weeks 80   # 抓取并解析（增量）
python verify_page.py                              # 数据完整性验证
python tests/test_parse_pdf.py                     # 解析 golden 回归
python -m http.server 8080                         # 本地预览 http://localhost:8080
```

## 部署（github.io）

见 `GIT_PUSH.md`（git init → 建仓 → 推送 → 开 Pages 的完整命令序列）。

## 路线图

- [x] 城市级趋势：百度指数（"发烧""奥司他韦"关键词，城市粒度代理指标）
- [x] 历史数据回填（两年窗口 100 期在库，CI 增量维护）
- [x] 多病原分解：中疾控哨点监测 11 病原体门急诊阳性率（2024W46 起）
- [x] 法定报告流感月度发病数：国家疾控局月报（2022-11 起）
- [ ] 新冠月度数据（中疾控"全国新型冠状病毒感染疫情情况"）
- [ ] 微信小程序版（需企业主体或走云开发）

## 合规说明

- 小程序/网页文案均避免"诊断""治疗"等医疗用语，页脚带免责声明。
- 数据来源均为政府公开发布物，抓取频率每周一次，遵守源站访问压力最小化原则。
