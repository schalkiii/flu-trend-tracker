# flu-trend-tracker 审计报告（2026-11-09）

> 面向执行 Agent 的体检结论与改进清单。审计基线：CDC 100 期数据（2024W49→2026W44）+
> 15 城 × 2 词 × 365 天百度指数，verify_page.py 30 项断言全绿。

## 一、现状描述

- **规模**：7 个代码文件共 ~1780 行（index.html 534 / fetch_baidu_via_browser.py 423 /
  fetch_baidu_fast.py 236 / fetch_baidu_index.py 207 / fetch_cdc.py 209 / verify_page.py 85 /
  update-data.yml 55 / run_browser_fetch.sh 34），加 README、GIT_PUSH.md、.gitignore。
- **结构**：单页静态站（index.html 零外部依赖手写 SVG）+ 三条采集流水线
  （CDC PDF 解析 / 百度指数 webbridge 快速直连 / webbridge UI 交互备用）+ 数据级验证脚本 + GitHub Actions 周更。
- **数据产物**：data/flu_national.json（100 期，零字段缺失）、data/flu_cities.json（252KB，一年逐日）。
  scripts/cache/ 194 份 PDF 共 874MB（其中 95 份在两年数据窗口之外）。
- **质量水平**：验证只有数据级断言（30 项），无解析单元测试；文档与代码存在多处脱节（见下）。
  git 尚未初始化（GIT_PUSH.md 待用户手动执行）。

## 二、问题清单（七维）

### 维度 1：文档一致性

| # | 位置 | 问题 | 严重 | 影响 |
|---|------|------|------|------|
| A1 | index.html「方法与限度」第 4 条 | 写"城市搜索数据……覆盖近 30 天"，实际已扩到近一年逐日 | **高** | 用户可见的错误陈述 |
| A2 | README「城市级数据」整节 | 主推 fetch_baidu_index.py + Cookie + pycryptodome 路线；该路线已被实测否决（TLS 指纹风控，urllib/curl 全被拦，status 10018），现役路线是 fetch_baidu_fast.py（webbridge cipher-text 复用），README 完全未提及 | **高** | 下次接手者会走死路 |
| A3 | README「架构」清单 | 缺 fetch_baidu_fast.py / fetch_baidu_via_browser.py / run_browser_fetch.sh；"增量抓取最近 8 期"与 CI 实际 `--pages 4 --weeks 80` 不符 | 中 | 交接成本 |
| A4 | README 路线图 | "[ ] 历史数据回填（2024–2025 全量周报）"已完成（100 期在库）未勾选 | 低 | 状态失真 |
| A5 | update-data.yml / GIT_PUSH.md 注释段 | "可选 CI 化城市数据（BAIDU_COOKIE + fetch_baidu_index.py）"实际不可行（本地直连被 TLS 风控拦截，CI 同样会被拦），误导配置 | 中 | 用户配置后必然失败 |
| A6 | run_browser_fetch.sh | 入口调用的是慢路线 fetch_baidu_via_browser.py（~40s/词），现役主路线 fetch_baidu_fast.py（~2s/词）没有被任何 shell 入口托管 daemon 生命周期 | 中 | 主路线裸奔、备用当主力 |

### 维度 2：文档缺漏

| # | 位置 | 问题 | 严重 | 影响 |
|---|------|------|------|------|
| B1 | fetch_baidu_fast.py | 无 `days ≤ 365` 约束说明：实测 days>365 时 API 静默切换周粒度（58 点跨 400 天），按日写入会造成日期错位污染（本轮已实际发生并清理 1740 个污染点） | **高** | 同类事故必复发 |
| B2 | 项目根 | 无 CLAUDE.md/AGENTS.md，采集路线的选型史（为何 index.py 死、fast.py 活）无沉淀 | 中 | 下一会话重复踩坑 |
| B3 | 无文档 | 百度指数数据会回溯修订（北京 2026-11-05 值 147→165）、小城市脱敏 0 值等非显然经验只存在于会话记忆 | 低 | 认知损耗 |

### 维度 3：架构

| # | 位置 | 问题 | 严重 | 影响 |
|---|------|------|------|------|
| C1 | fetch_baidu_index.py | 整条路线已死（TLS 指纹拦截），且其 CITIES 码表（杭州138/武汉28/西安165/南京125/重庆11/天津164/沈阳150/长沙43/郑州168/哈尔滨152）与实测有效的 fast 版码表（杭州96/武汉90/西安93/南京83/重庆92/天津85/苏州82/长沙88/沈阳84/青岛86）**城市集合与映射全不同**——留着必误导 | **高** | 两套冲突真相 |
| C2 | 三条百度采集脚本 | KEYWORDS/CITIES/解密逻辑重复三份 | 低（两份已废弃一份） | 删 C1 后自然消解 |

### 维度 4：代码写法

| # | 位置 | 问题 | 严重 | 影响 |
|---|------|------|------|------|
| D1 | fetch_baidu_fast.py `fetch_one` | `word_enc` 定义后未使用（死变量，word_param 才是用的） | 低 | 噪声 |
| D2 | fetch_baidu_fast.py `main` | `days` 参数无上限校验（B1 的代码面） | **高** | 污染复发的直接根源 |
| D3 | fetch_cdc.py L16 | `import io` 未使用（死导入） | 低 | 噪声 |
| D4 | fetch_baidu_via_browser.py | CITIES 仅 5 城、PROVINCE_OF 仅 3 城映射，与 fast 版 15 城不一致，docstring 未说明差异 | 低 | 备用脚本，标注即可 |

### 维度 5：测试覆盖率

| # | 位置 | 问题 | 严重 | 影响 |
|---|------|------|------|------|
| E1 | parse_pdf 无单元测试 | CDC 周报措辞有 4 类变体（全角括号 / 双右括号 PDF 噪声 / 裸 0 无百分比 / "未报告"=0），全部是靠事故驱动修复的，无 golden 回归保护；下次格式再变只能再事故一次 | 中 | 回归风险 |

### 维度 6：测试严谨性

| # | 位置 | 问题 | 严重 | 影响 |
|---|------|------|------|------|
| F1 | verify_page.py L63 | "表格可倒序渲染"断言 `len(list(reversed(x))) == len(x)` 是**恒真式**，零检出能力 | 中 | 假绿 |
| F2 | verify_page.py L59 | "A+B 检出 = 总阳性"在 total_positives 缺失时退化为恒真（fallback 就是 type_a+type_b） | 低 | 弱断言（字段确实可选，可接受但应显式区分） |

### 维度 7：工程规范

| # | 位置 | 问题 | 严重 | 影响 |
|---|------|------|------|------|
| G1 | scripts/cache/ | 874MB、194 份 PDF，其中 95 份在两年数据窗口外（2023 年与 2024 年前段），gitignored 但占磁盘 | 低 | 磁盘（删除候选，需用户确认） |
| G2 | .gitignore | 缺 `shots/`（426KB 验证截图会被 `git add .` 带进仓库） | 中 | 仓库体积污染 |
| G3 | scripts/baidu_cookie.txt | 含 BDUSS 完整凭证，现役 fast 路线不用它（从浏览器实时捕获），纯遗留泄露面 | 中 | 安全（删除候选，需用户确认） |
| G4 | __pycache__ | 已 ignore，无需处理 | — | 无问题 |

## 三、改进建议（可直接执行）

按优先级排序；P1/P2 各条目文件无重叠，**可并行**。

### P1（高，本轮必清）

| # | 做法 | 文件 | 验证 |
|---|------|------|------|
| 1 | 「方法与限度」第 4 条"覆盖近 30 天"→"覆盖近一年逐日" | index.html | grep 确认无"30 天"残留 |
| 2 | fetch_baidu_fast.py：main 入口对 days 做 `>365` 拒绝（明确报错退出，不允许静默错位）；docstring 写明粒度陷阱；删除死变量 word_enc | scripts/fetch_baidu_fast.py | `--days 400` 应报错退出；`--days 365` 正常；`python -c "import ast; ast.parse(...)"` 语法过 |
| 3 | README 重写「城市级数据」与「架构」节：fast 路线为唯一现役路线（webbridge 起 daemon → 浏览器搜一次拿 cipher-text → 本地直连），via_browser 为备用；架构清单补齐三脚本；CI 参数同步 `--pages 4 --weeks 80`；路线图勾选历史回填；删除"Cookie CI 化"误导段 | README.md | 通读对照代码事实 |
| 4 | 删除 fetch_baidu_index.py（死路线 + 冲突码表）；同步删 workflow 与 GIT_PUSH.md 中引用它的注释段 | scripts/fetch_baidu_index.py、.github/workflows/update-data.yml、GIT_PUSH.md | 全仓 grep 无 fetch_baidu_index 引用 |
| 5 | run_browser_fetch.sh 改调 fetch_baidu_fast.py（daemon 托管逻辑不变），保留 --days 透传 | scripts/run_browser_fetch.sh | bash -n 语法过；通读确认 |

### P2（中，本轮必清）

| # | 做法 | 文件 | 验证 |
|---|------|------|------|
| 6 | verify_page.py：删恒真断言"表格可倒序渲染"，改为"倒序后首条 = 最新期"；A+B 断言改为显式：有 total_positives 才比对，否则打印 SKIP 提示 | verify_page.py | `python verify_page.py` 全绿 |
| 7 | .gitignore 追加 `shots/` | .gitignore | `git check-ignore` 无 git 环境，肉眼复查条目 |
| 8 | fetch_cdc.py 删 `import io` | scripts/fetch_cdc.py | `python scripts/fetch_cdc.py --pages 1 --weeks 100 --force`（纯缓存重解析）跑通且 JSON 零缺失 |
| 9 | fetch_baidu_via_browser.py docstring 标注：备用慢路线，仅 5 城码表，主路线见 fetch_baidu_fast.py | scripts/fetch_baidu_via_browser.py | 通读 |
| 10 | 新增 parse_pdf golden 回归测试：从 cache 取 4 份代表性 PDF（常规 / 全角括号 / "未报告"0 / 裸0+双括号），断言关键字段值 | tests/test_parse_pdf.py | `python tests/test_parse_pdf.py` 全绿 |
| 11 | 新建 CLAUDE.md（≤60 行：定位/怎么跑/技术栈/目录约定/现状与下一步） | CLAUDE.md | neat-freak 五要素自查 |

### P3（删除候选 — 需用户确认，未确认不动）

| # | 对象 | 理由 |
|---|------|------|
| a | scripts/cache/ 中 2024W48 及更早的 95 份 PDF（~430MB） | 数据窗口外的可再生缓存 |
| b | scripts/baidu_cookie.txt | 现役路线不用，含 BDUSS 凭证的遗留泄露面 |
| c | __pycache__/ 两处 | 已 ignore 的本地产物，顺手清 |

## 四、验证基线

每完成一个改动点运行 `python verify_page.py`（当前 30 项全绿）；
涉及 fetch_cdc 的改动追加缓存重解析确认零字段缺失；
最终以本报告逐条对账清零。
