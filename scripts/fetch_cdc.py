#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
fetch_cdc.py — 抓取中国国家流感中心《中国流感监测周报》并解析关键指标
产出: data/flu_national.json

数据源: https://ivdc.chinacdc.cn/cnic/zyzx/lgzb/
每期周报提取:
  - 南方/北方省份 ILI% (流感样病例就诊百分比)
  - 南方/北方省份 标本检测阳性率
  - 型别分布 (A(H1N1)pdm09 / A(H3N2) / B(Victoria))
  - 暴发疫情起数
已解析的期次写入 PDF 缓存目录, 增量运行不重复下载。
"""

import json
import re
import sys
import urllib.request
from datetime import datetime, timezone, timedelta
from pathlib import Path

BASE = "https://ivdc.chinacdc.cn/cnic/zyzx/lgzb/"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")
ROOT = Path(__file__).resolve().parent.parent
DATA_FILE = ROOT / "data" / "flu_national.json"
CACHE_DIR = ROOT / "scripts" / "cache"

# 中国时区
CST = timezone(timedelta(hours=8))


def http_get(url: str, timeout: int = 120) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def fetch_week_list(max_pages: int = 1):
    """返回 [(year, week, detail_url, date_str), ...] 按新到旧。
    列表页每页 20 期, createPageHTML(30, 0, "index", "htm") => index_1.htm .. index_29.htm。"""
    pages = [BASE]
    for p in range(1, max_pages):
        pages.append(f"{BASE}index_{p}.htm")
    items = []
    for page_url in pages:
        try:
            html = http_get(page_url).decode("utf-8", errors="replace")
        except Exception as e:
            print(f"  !! 列表页 {page_url} 获取失败: {e}")
            continue
        for m in re.finditer(
            r'href="\./([^"]+\.htm)"[^>]*>(\d{4})\s*第(\d+)周\s*</a>.*?\((\d{4}-\d{2}-\d{2})\)',
            html, re.S,
        ):
            url = BASE + m.group(1)
            items.append({
                "year": int(m.group(2)),
                "week": int(m.group(3)),
                "url": url,
                "publish_date": m.group(4),
            })
    # 去重 + 按年份/周序排序（新到旧）
    seen, uniq = set(), []
    for it in items:
        key = (it["year"], it["week"])
        if key not in seen:
            seen.add(key)
            uniq.append(it)
    uniq.sort(key=lambda x: (x["year"], x["week"]), reverse=True)
    return uniq


def find_pdf_url(detail_url: str) -> str:
    html = http_get(detail_url).decode("utf-8", errors="replace")
    m = re.search(r'href="\.\/(P\d+\.pdf)"', html)
    if not m:
        raise RuntimeError(f"PDF link not found in {detail_url}")
    return detail_url.rsplit("/", 1)[0] + "/" + m.group(1)


def parse_pdf(pdf_path: Path, year: int, week: int) -> dict:
    import pdfplumber

    text = ""
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages[:6]:  # 摘要与核心表都在前 6 页
            t = page.extract_text() or ""
            text += t + "\n"

    def pct(pattern, default=None):
        m = re.search(pattern, text)
        return float(m.group(1)) if m else default

    rec = {"year": year, "week": week}

    # 南北方 ILI%: "南方省份哨点医院报告的ILI%为 4.5%，" / "北方省份哨点医院报告的ILI%为 3.0%，"
    # 注意: PDF 中可能为全角逗号, 且数字前可能有换行
    rec["south_ili_pct"] = pct(r"南方省份哨点医院报告的\s*ILI%\s*为\s*([\d.]+)\s*%\s*[，,]")
    rec["north_ili_pct"] = pct(r"北方省份哨点医院报告的\s*ILI%\s*为\s*([\d.]+)\s*%\s*[，,]")

    # 阳性率（表1）: "阳性数(%) 1933(18.0%) 480(4.9%) 2413(11.8%)"
    # 括号可能全角/半角混用: "2115（24.5%） 2768(32.8%)"
    m = re.search(
        r"阳性数\(%\)\s*(\d+)[(（]([\d.]+)%[)）]\s*(\d+)[(（]([\d.]+)%[)）]\s*(\d+)[(（]([\d.]+)%[)）]",
        text.replace("\n", " "),
    )
    if m:
        rec["south_positives"] = int(m.group(1))
        rec["south_pos_rate"] = float(m.group(2))
        rec["north_positives"] = int(m.group(3))
        rec["north_pos_rate"] = float(m.group(4))
        rec["total_positives"] = int(m.group(5))
        rec["total_pos_rate"] = float(m.group(6))
    # 检测数: "检测数 10720 9709 20429"
    m = re.search(r"检测数\s*(\d+)\s+(\d+)\s+(\d+)", text)
    if m:
        rec["total_tested"] = int(m.group(3))

    # 型别合计占比: "A型 1243(64.3%) ... 合计 A型 1630(67.6%)" -> 用合计列
    # 数量列可能为裸 0 无百分比后缀: "B型 14(10.8%) 0 14(9.7%)"
    def total_share(label):
        mm = re.search(
            rf"{label}\s+(\d+)(?:[(（][\d.]+%[)）]+)?\s+(\d+)(?:[(（][\d.]+%[)）]+)?\s+(\d+)(?:[(（][\d.]+%[)）]+)?",
            text.replace("\n", " "),
        )
        return int(mm.group(3)) if mm else None

    rec["type_a"] = total_share("A型")
    rec["type_b"] = total_share("B型")

    # 暴发疫情: "全国共报告145起…" / "全国报告3起…"（共字可无）
    # 春季低发期会写"全国未报告流感样病例暴发疫情" -> 0 起
    flat = text.replace("\n", "")
    m = re.search(r"全国(?:共)?报告\s*(\d+)\s*起流感样病例暴发疫情", flat)
    if m:
        rec["outbreaks"] = int(m.group(1))
    elif re.search(r"全国未报告流感样病例暴发疫情", flat):
        rec["outbreaks"] = 0

    return rec


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

    # 分页遍历深度: --pages N (默认 1=仅首页); 期数上限 --weeks
    max_pages = int(sys.argv[sys.argv.index("--pages") + 1]) if "--pages" in sys.argv else 1
    max_weeks = int(sys.argv[sys.argv.index("--weeks") + 1]) if "--weeks" in sys.argv else 12
    force = "--force" in sys.argv

    weeks = fetch_week_list(max_pages)
    print(f"发现 {len(weeks)} 期周报, 最新: {weeks[0]['year']}年第{weeks[0]['week']}周")

    updated = 0
    for it in weeks[:max_weeks]:
        key = (it["year"], it["week"])
        if key in existing and not force:
            continue
        pdf_path = CACHE_DIR / f"{it['year']}_w{it['week']:02d}.pdf"
        try:
            if not pdf_path.exists():
                pdf_url = find_pdf_url(it["url"])
                print(f"下载 {it['year']}年第{it['week']}周: {pdf_url}")
                pdf_path.write_bytes(http_get(pdf_url))
            elif force:
                print(f"重解析缓存 {it['year']}年第{it['week']}周")
            rec = parse_pdf(pdf_path, it["year"], it["week"])
            rec["publish_date"] = it["publish_date"]
            rec["source"] = it["url"]
            # 清洗 None 字段
            rec = {k: v for k, v in rec.items() if v is not None}
            existing[key] = rec
            updated += 1
            print(f"  -> ILI% 南 {rec.get('south_ili_pct')}% / 北 {rec.get('north_ili_pct')}%, "
                  f"阳性率 {rec.get('total_pos_rate')}%, 暴发 {rec.get('outbreaks')} 起")
        except Exception as e:
            print(f"  !! {it['year']}年第{it['week']}周 解析失败: {e}")

    records = sorted(existing.values(), key=lambda r: (r["year"], r["week"]))
    data["records"] = records
    data["meta"] = {
        "source": "中国国家流感中心《中国流感监测周报》",
        "source_url": BASE,
        "updated_at": datetime.now(CST).strftime("%Y-%m-%d %H:%M CST"),
        "latest": f"{weeks[0]['year']}年第{weeks[0]['week']}周",
        "history_pages": max_pages,
        "note": "南方/北方省份 ILI% 为哨点医院流感样病例占门急诊病例百分比; "
                "阳性率为监测网络实验室检测阳性率。数据仅供参考, 不构成任何医疗建议。",
    }
    DATA_FILE.write_text(
        json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
    )
    print(f"完成: 更新 {updated} 期, 共 {len(records)} 期 -> {DATA_FILE}")


if __name__ == "__main__":
    main()
