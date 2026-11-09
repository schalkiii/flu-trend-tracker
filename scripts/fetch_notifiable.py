#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
fetch_notifiable.py — 抓取国家疾控局《全国(法定)传染病疫情概况》月报中的流感数据
产出: data/flu_notifiable.json

数据源: https://www.ndcpa.gov.cn/jbkzzx/c100016/common/list.html
列表页为 JS 渲染, 文章数据内嵌于页面 JSON ("id" + 标题), URL 模式
  /jbkzzx/c100016/common/content/content_{id}.html
列表页可见 50 条, 回溯至 2022-11。
每期提取统计表中: 流行性感冒 发病数/死亡数、丙类合计、甲乙丙总计。
"""

import json
import re
import sys
import urllib.request
from datetime import datetime, timezone, timedelta
from pathlib import Path

LIST_URL = "https://www.ndcpa.gov.cn/jbkzzx/c100016/common/list.html"
ART_URL = "https://www.ndcpa.gov.cn/jbkzzx/c100016/common/content/content_{}.html"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")
ROOT = Path(__file__).resolve().parent.parent
DATA_FILE = ROOT / "data" / "flu_notifiable.json"
CACHE_DIR = ROOT / "scripts" / "cache" / "ndcpa"

CST = timezone(timedelta(hours=8))


def http_get(url: str, timeout: int = 120) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def text_of(html: str) -> str:
    t = re.sub(r"<script[\s\S]*?</script>|<style[\s\S]*?</style>", "", html)
    t = re.sub(r"<[^>]+>", " ", t)
    t = re.sub(r"&nbsp;?;?|&#\d+;", " ", t)
    t = re.sub(r"\s+", " ", t)
    # PDF 转写噪声: 数字内部空格 ("2 346461" -> "2346461")
    t = re.sub(r"(\d) (\d{3})", r"\1\2", t)  # 千分位断裂
    t = re.sub(r"(\d) \.(\d)", r"\1.\2", t)
    return t


def fetch_article_list():
    """从列表页内嵌 JSON 提取月报文章 [(year, month, article_id, title), ...] 新到旧。
    页面 JSON 为对象数组, 每对象含 saT 标题与 aU 内容 URL; aU 值内嵌转义引号,
    用对象切分 + 各自独立匹配最稳。"""
    html = http_get(LIST_URL).decode("utf-8", errors="replace")
    items = []
    for obj in html.split('{"aTs"'):
        tm = re.search(r"(\d{4})年(\d{1,2})月全国(?:法定)?传染病疫情概况", obj)
        um = re.search(r"content_(\d+)\.html", obj)
        if tm and um:
            y, mo = int(tm.group(1)), int(tm.group(2))
            items.append({
                "article_id": um.group(1),
                "year": y,
                "month": mo,
                "title": f"{y}年{mo}月全国传染病疫情概况",
            })
    # 去重 + 排序（新到旧）
    seen, uniq = set(), []
    for it in items:
        key = (it["year"], it["month"])
        if key not in seen:
            seen.add(key)
            uniq.append(it)
    uniq.sort(key=lambda x: (x["year"], x["month"]), reverse=True)
    return uniq


def parse_article(html: str, year: int, month: int) -> dict:
    t = text_of(html)
    rec = {"year": year, "month": month}

    # 流行性感冒 发病数 死亡数
    m = re.search(r"流行性感冒\s+(\d+)\s+(\d+)", t)
    if m:
        rec["cases"] = int(m.group(1))
        rec["deaths"] = int(m.group(2))
    # 丙类合计
    m = re.search(r"丙类传染病(?:共)?报告发病\s*(\d+)\s*例", t)
    if m:
        rec["class_c_total"] = int(m.group(1))
    # 甲乙丙总计
    m = re.search(r"甲乙丙类传染病总计\s+(\d+)\s+(\d+)", t)
    if m:
        rec["all_notifiable_total"] = int(m.group(1))
    return rec


def main():
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    DATA_FILE.parent.mkdir(parents=True, exist_ok=True)

    existing = {}
    if DATA_FILE.exists():
        data = json.loads(DATA_FILE.read_text(encoding="utf-8"))
        for r in data.get("records", []):
            existing[(r["year"], r["month"])] = r
    else:
        data = {"meta": {}, "records": []}

    force = "--force" in sys.argv

    articles = fetch_article_list()
    print(f"发现 {len(articles)} 期月报, 最新: {articles[0]['title'] if articles else '-'}")

    updated = 0
    for it in articles:
        key = (it["year"], it["month"])
        if key in existing and not force:
            continue
        cache_path = CACHE_DIR / f"{it['year']}_{it['month']:02d}.html"
        try:
            if cache_path.exists() and not force:
                html = cache_path.read_text(encoding="utf-8")
            else:
                html = http_get(ART_URL.format(it["article_id"])).decode("utf-8", errors="replace")
                cache_path.write_text(html, encoding="utf-8")
            rec = parse_article(html, it["year"], it["month"])
            if rec.get("cases") is None:
                print(f"  !! {it['title']} 未找到流感数据, 跳过")
                continue
            rec["source"] = ART_URL.format(it["article_id"])
            existing[key] = rec
            updated += 1
            print(f"  -> {it['year']}-{it['month']:02d} 流感发病 {rec['cases']:,} 例 / 死亡 {rec.get('deaths')} 例")
        except Exception as e:
            print(f"  !! {it['title']} 解析失败: {e}")

    records = sorted(existing.values(), key=lambda r: (r["year"], r["month"]))
    data["records"] = records
    data["meta"] = {
        "source": "国家疾病预防控制局《全国(法定)传染病疫情概况》月度统计",
        "source_url": LIST_URL,
        "updated_at": datetime.now(CST).strftime("%Y-%m-%d %H:%M CST"),
        "latest": articles[0]["title"] if articles else "",
        "note": "流行性感冒为丙类法定传染病, 报告病例数为临床诊断+实验室确诊病例, "
                "按终审日期统计。数据仅供参考, 不构成任何医疗建议。",
    }
    DATA_FILE.write_text(
        json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
    )
    print(f"完成: 更新 {updated} 期, 共 {len(records)} 个月记录 -> {DATA_FILE}")


if __name__ == "__main__":
    main()
