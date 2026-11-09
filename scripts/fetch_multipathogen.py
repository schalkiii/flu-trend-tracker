#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
fetch_multipathogen.py — 抓取中疾控《全国急性呼吸道传染病哨点监测情况》
产出: data/flu_multipathogen.json

数据源: https://www.chinacdc.cn/jksj/jksj04_14275/ (列表页 12 期/页, index_1.html..index_7.html,
回溯至 2024 年第 46 周; 2025 年 4-5 月为多月合并期, 表1 为宽表多周列)
每期提取:
  - ILI% (哨点医院流感样病例占门急诊就诊总数, 全国/南方/北方)
  - 表1: 门急诊 ILI + 住院 SARI 各病原体核酸检测阳性率 (11 种病原体)
  - 门急诊前三位病原体
增量运行: HTML 缓存到 scripts/cache/mp/, 已解析期次跳过。--force 重解析。
"""

import json
import re
import sys
import urllib.request
from datetime import datetime, timezone, timedelta
from pathlib import Path

BASE = "https://www.chinacdc.cn/jksj/jksj04_14275/"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")
ROOT = Path(__file__).resolve().parent.parent
DATA_FILE = ROOT / "data" / "flu_multipathogen.json"
CACHE_DIR = ROOT / "scripts" / "cache" / "mp"

CST = timezone(timedelta(hours=8))

PATHOGENS = [
    "新型冠状病毒", "流感病毒", "呼吸道合胞病毒", "腺病毒", "人偏肺病毒",
    "副流感病毒", "普通冠状病毒", "博卡病毒", "鼻病毒", "肠道病毒", "肺炎支原体",
]


def http_get(url: str, timeout: int = 120) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def fetch_article_list(max_pages: int = 1):
    """返回 [{year, week, url, title}, ...] 按新到旧。
    列表页 URL: 首页 '' + index_1.html .. index_7.html (404 即到底)。"""
    pages = [BASE]
    for p in range(1, max_pages):
        pages.append(f"{BASE}index_{p}.html")
    items = []
    for page_url in pages:
        try:
            html = http_get(page_url).decode("utf-8", errors="replace")
        except Exception as e:
            print(f"  !! 列表页 {page_url} 获取失败: {e}")
            continue
        for m in re.finditer(
            r'href="\./(\d{6}/t\d+_\d+\.html)"[^>]*>\s*([^<]{4,120})<', html,
        ):
            rel, title = m.group(1), m.group(2).strip()
            # 标题形如 "全国急性呼吸道传染病哨点监测情况（2026年第44周）"
            # 或合并期 "（2025年4月，第14周—18周）"
            wm = re.search(r"(\d{4})年(?:\d+月，)?第(\d+)周[—\-—~]*\d*", title)
            if not wm:
                continue
            items.append({
                "year": int(wm.group(1)),
                "week": int(wm.group(2)),
                "url": BASE + rel,
                "title": title,
            })
    # 去重 + 排序（新到旧）
    seen, uniq = set(), []
    for it in items:
        key = (it["year"], it["week"])
        if key not in seen:
            seen.add(key)
            uniq.append(it)
    uniq.sort(key=lambda x: (x["year"], x["week"]), reverse=True)
    return uniq


def text_of(html: str) -> str:
    """HTML -> 平文本。仅用于正文段落（ILI 句、top3 句）, 不再用于表1。"""
    t = re.sub(r"<script[\s\S]*?</script>|<style[\s\S]*?</style>", "", html)
    t = re.sub(r"<[^>]+>", " ", t)
    t = re.sub(r"&nbsp;?;?|&#\d+;|[\u2000-\u200a\u3000]", " ", t)
    t = re.sub(r"\s+", " ", t)
    return t


def strip_cells(html: str) -> list:
    """提取一个 <tr>...</tr> 内的单元格纯文本列表。
    单元格内 PDF 转写噪声: 数字被空格打断 ("+ 2.2" / "-1 . 0" / "鼻 病毒")。"""
    cells = []
    for cm in re.finditer(r"<t[dh][^>]*>([\s\S]*?)</t[dh]>", html):
        c = re.sub(r"<[^>]+>", " ", cm.group(1))
        c = re.sub(r"&nbsp;?;?|&#\d+;|[\u2000-\u200a\u3000]", " ", c)
        c = re.sub(r"\s+", " ", c).strip()
        # 纯数字格: 符号后/整数-点-小数间的空格合并 ("+ 2.2"->"+2.2", "-1 . 0"->"-1.0")
        if re.fullmatch(r"[+-]?\s*\d+\s*(?:\.\s*\d+)?", c):
            c = re.sub(r"\s+", "", c)
        cells.append(c)
    return cells


def parse_table1_html(html: str):
    """结构化解析表1（门急诊 + 住院各病原体阳性率）。
    返回 (outpatient{p:[周值]}, inpatient{p:[周值]}, weeks[int]) 或 None。
    两种表形态:
      单周表: 表头 ['第N周','较上周*','',...], 数据行 5 格 = [名,值,变化量,值,变化量]
      宽表(合并期): 表头 ['第14周',...,'第18周','',...], 数据行 2n+1 格 = [名,门急诊n值,住院n值]
    """
    best = None
    for tm in re.finditer(r"<table[\s\S]*?</table>", html):
        tb = tm.group(0)
        if "病原体" not in tb or "门急诊" not in tb:
            continue
        rows = re.findall(r"<tr[^>]*>[\s\S]*?</tr>", tb)
        if not rows:
            continue
        # 表头行: 找含 "第N周" 的行, 提取周序列（门急诊段 + 住院段, 去重前 n 个）
        # 周数数字内部可能有空格 ("第 4 2周"), 匹配后去除内部空格
        head_cells = None
        for r in rows[:3]:
            cells = strip_cells(r)
            wks = []
            for c in cells:
                wm = re.search(r"第\s*((?:\d\s*)+)周", c)
                if wm:
                    wks.append(wm.group(1).replace(" ", ""))
            if len(wks) >= 2:
                head_cells = wks
                break
        if not head_cells:
            continue
        # 单周表: 门急诊+住院各 1 周但重复出现两次 -> n=1; 宽表: 前 n 个不同周
        uniq = []
        for w in head_cells:
            if w not in uniq:
                uniq.append(w)
        n = len(uniq)
        ntok = 4 if n == 1 else 2 * n
        op, ip = {}, {}
        for p in PATHOGENS:
            p_nospace = p.replace(" ", "")
            for r in rows:
                # 行内标签去除后再判断（"鼻</span><span>病毒" 跨 span 断字形态）
                r_plain = re.sub(r"<[^>]+>", "", r)
                if p_nospace not in r_plain.replace(" ", "").replace("&nbsp;", ""):
                    continue
                cells = strip_cells(r)
                # 名称格位置不定（老页面行首多一空格列; 名称内部也可能断字 "鼻 病毒"）:
                # 比较时双方去空格
                try:
                    ni = next(i for i, c in enumerate(cells) if c.replace(" ", "") == p_nospace)
                except StopIteration:
                    continue
                # 去掉名称格 + 分隔空格格 -> 数值格序列
                vals = [c for c in cells[ni + 1:] if c not in ("", "*")]
                nums = []
                ok = True
                for v in vals:
                    fm = re.fullmatch(r"[-+]?\d+(?:\.\d+)?", v)
                    if fm:
                        nums.append(float(v))
                    else:
                        ok = False
                        break
                if not ok or len(nums) < ntok:
                    continue
                if n == 1:
                    op[p] = [nums[0]]
                    ip[p] = [nums[2]]
                else:
                    op[p] = nums[:n]
                    ip[p] = nums[n:2 * n]
                break
        if op:
            weeks = [int(w) for w in uniq[:n]]
            best = (op, ip, weeks)
            if len(op) == len(PATHOGENS):
                break  # 11 种全中, 不再找
    return best


def parse_article(html: str, year: int, week: int) -> dict:
    """解析单期文章。合并期（如 2025 年 4 月）也按起始周入库, 表1 宽表取各周列。"""
    t = text_of(html)
    recs = []  # 单期通常 1 条; 合并期多条

    # ---- ILI%: "流感样病例百分比）为4.1%，南方省份（4.8%）高于北方省份（3.3%）"
    # 早期格式无南北拆分: "流感样病例百分比）为 3.2% ；哨点医院..."
    ili_national = ili_south = ili_north = None
    m = re.search(
        r"流感样病例百分比[）)]\s*为\s*([\d.]+)\s*%"
        r"(?:[，,]?\s*南方省份[（(]\s*([\d.]+)\s*%[）)]"
        r"\s*高于北方省份[（(]\s*([\d.]+)\s*%[）)])?",
        t,
    )
    if m:
        ili_national = float(m.group(1))
        ili_south = float(m.group(2)) if m.group(2) else None
        ili_north = float(m.group(3)) if m.group(3) else None

    # ---- 表1: 结构化 <table> 解析优先, 文本正则回退
    tbl = parse_table1_html(html)
    op = ip = weeks_covered = None
    if tbl:
        op, ip, weeks_covered = tbl

    # ---- 门急诊前三位: 由表1数值排序生成（文本句 "前三位病原体为..." 受断字干扰, 仅作校验）
    top3 = []
    if op:
        vals = sorted(op.items(), key=lambda kv: -kv[1][0] if kv[1][0] is not None else 0)
        top3 = [k for k, _ in vals[:3]]

    if weeks_covered and len(weeks_covered) > 1:
        # 合并期: 每周一条记录
        for idx, w in enumerate(weeks_covered):
            rec = {"year": year, "week": w}
            rec["outpatient"] = {p: op[p][idx] for p in op if idx < len(op[p])}
            rec["inpatient"] = {p: ip[p][idx] for p in ip if idx < len(ip[p])}
            recs.append(rec)
    else:
        rec = {"year": year, "week": week}
        if ili_national is not None:
            rec["ili_pct"] = ili_national
            rec["ili_south"] = ili_south
            rec["ili_north"] = ili_north
        if op:
            rec["outpatient"] = {p: op[p][0] for p in op}
            rec["inpatient"] = {p: ip[p][0] for p in ip}
        if top3:
            rec["top3_outpatient"] = top3[:3]
        recs.append(rec)
    return recs


def main():
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    DATA_FILE.parent.mkdir(parents=True, exist_ok=True)

    existing = {}
    if DATA_FILE.exists():
        data = json.loads(DATA_FILE.read_text(encoding="utf-8"))
        for r in data.get("records", []):
            existing[(r["year"], r["week"])] = r
    else:
        data = {"meta": {}, "records": []}

    max_pages = int(sys.argv[sys.argv.index("--pages") + 1]) if "--pages" in sys.argv else 1
    max_articles = int(sys.argv[sys.argv.index("--weeks") + 1]) if "--weeks" in sys.argv else 12
    force = "--force" in sys.argv

    articles = fetch_article_list(max_pages)
    print(f"发现 {len(articles)} 期哨点监测, 最新: {articles[0]['title'] if articles else '-'}")

    updated = 0
    for it in articles[:max_articles]:
        key = (it["year"], it["week"])
        cache_path = CACHE_DIR / f"{it['year']}_w{it['week']:02d}.html"
        try:
            if cache_path.exists() and not force:
                html = cache_path.read_text(encoding="utf-8")
            else:
                html = http_get(it["url"]).decode("utf-8", errors="replace")
                cache_path.write_text(html, encoding="utf-8")
            recs = parse_article(html, it["year"], it["week"])
            if not recs:
                print(f"  !! {it['title']} 解析为空, 跳过")
                continue
            for rec in recs:
                k = (rec["year"], rec["week"])
                rec["publish_date"] = it["url"].rsplit("/", 1)[0].split("/")[-1]
                rec["source"] = it["url"]
                existing[k] = rec
            updated += 1
            flu = next((r for r in recs if "outpatient" in r and "流感病毒" in r.get("outpatient", {})), recs[0])
            print(f"  -> {it['year']}W{it['week']:02d} 流感阳性率(门急诊) "
                  f"{flu.get('outpatient', {}).get('流感病毒')}% / ILI {flu.get('ili_pct')}")
        except Exception as e:
            print(f"  !! {it['title']} 解析失败: {e}")

    records = sorted(existing.values(), key=lambda r: (r["year"], r["week"]))
    data["records"] = records
    data["meta"] = {
        "source": "中国疾控中心《全国急性呼吸道传染病哨点监测情况》",
        "source_url": BASE,
        "updated_at": datetime.now(CST).strftime("%Y-%m-%d %H:%M CST"),
        "latest": articles[0]["title"] if articles else "",
        "pathogens": PATHOGENS,
        "note": "门急诊=流感样病例呼吸道样本, 住院=严重急性呼吸道感染病例呼吸道样本; "
                "数值为核酸检测阳性率(%)。2025年4-5月为多月合并发布, 已拆为逐周记录(无ILI%)。"
                "数据仅供参考, 不构成任何医疗建议。",
    }
    DATA_FILE.write_text(
        json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
    )
    print(f"完成: 更新 {updated} 期文章, 共 {len(records)} 周记录 -> {DATA_FILE}")


if __name__ == "__main__":
    main()
