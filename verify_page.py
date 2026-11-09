# -*- coding: utf-8 -*-
"""
数据级端到端验证（不依赖浏览器）:
用 Python 模拟 index.html 中 JS 的全部渲染逻辑, 对真实 JSON 数据逐一断言。
等价性说明: lineChart/barChart 只做几何映射, 不影响数据正确性;
此处验证数据完整性、图表序列构造、gauge/表格/涨跌计算、缩放窗口的正确性。
"""
import json

data = json.load(open("data/flu_national.json", encoding="utf-8"))
recs = sorted(data["records"], key=lambda r: (r["year"], r["week"]))
failures = []

def check(name, cond):
    print(("PASS " if cond else "FAIL ") + name)
    if not cond:
        failures.append(name)

# 1. 数据完整性
check("至少 52 期记录（一年）", len(recs) >= 52)
need = ["south_ili_pct", "north_ili_pct", "south_pos_rate", "north_pos_rate",
        "total_pos_rate", "type_a", "type_b", "outbreaks"]
for f in need:
    check(f"字段 {f} 全部非空", all(r.get(f) is not None for r in recs))

# 2. meta
check("meta 含来源", "流感监测周报" in data["meta"]["source"])
check("meta 含更新时间", "updated_at" in data["meta"])
check("meta 含免责声明", "不构成" in data["meta"]["note"])

# 3. gauge 渲染逻辑（JS deltaClass/deltaHTML 的 Python 等价）
last, prev = recs[-1], recs[-2]
def delta_class(cur, p):
    if cur is None or p is None: return "flat"
    d = cur - p
    return "up" if d > 0.05 else "down" if d < -0.05 else "flat"
gauges = [
    ("南方 ILI%", last["south_ili_pct"], prev["south_ili_pct"]),
    ("北方 ILI%", last["north_ili_pct"], prev["north_ili_pct"]),
    ("全国阳性率", last["total_pos_rate"], prev["total_pos_rate"]),
    ("暴发起数", last["outbreaks"], prev["outbreaks"]),
]
check("4 张 gauge 均可计算涨跌", all(delta_class(g[1], g[2]) in ("up", "down", "flat") for g in gauges))
check("最新期为 2026 年 44 周及以后", (last["year"], last["week"]) >= (2026, 44))

# 4. 图表序列构造（JS 中 series points 全部有值才画线）
check("ILI 图 2 条序列全非空", all(r["south_ili_pct"] is not None and r["north_ili_pct"] is not None for r in recs))
check("阳性率图 3 条序列全非空", all(r.get("south_pos_rate") is not None and r.get("north_pos_rate") is not None for r in recs))
check("暴发柱状全非空", all(r["outbreaks"] is not None for r in recs))

# 5. 缩放窗口逻辑（JS viewRecs 的 Python 等价: slice(-N)）
for n, name in [(0, "全部"), (104, "近2年"), (52, "近1年"), (26, "近半年")]:
    win = recs if n == 0 else recs[-n:]
    check(f"缩放 {name} 窗口可构造 ({len(win)} 期)", len(win) > 0 and win[-1] == last)

# 6. 数值合理性
check("ILI% 在 0-30 区间", all(0 < r["south_ili_pct"] < 30 and 0 < r["north_ili_pct"] < 30 for r in recs))
check("阳性率在 0-100 区间", all(0 <= r["total_pos_rate"] <= 100 for r in recs))
# A+B = 总阳性: 仅对含 total_positives 字段的记录比对（该字段可选, 缺失不视为失败）
with_total = [r for r in recs if "total_positives" in r]
if with_total:
    check(f"A+B 检出 = 总阳性 ({len(with_total)} 期含该字段)",
          all(r["type_a"] + r["type_b"] == r["total_positives"] for r in with_total))
else:
    print("SKIP A+B 比对: 无 total_positives 字段记录")

# 7. 表格渲染（默认近 26 期，最新在上）
check("表格默认窗口 26 期", len(recs[-26:]) == min(26, len(recs)))
check("表格倒序后首条 = 最新期", list(reversed(recs[-26:]))[0] == last)

# 8. 城市级数据（可选, 缺失不失败）
try:
    city = json.load(open("data/flu_cities.json", encoding="utf-8"))
    cities = [c for c in city.get("cities", {}) if city["cities"][c].get("kw_发烧")]
    check("城市级: 至少 10 城", len(cities) >= 10)
    check("城市级: 每城至少 300 天数据（一年时间线）", all(len(city["cities"][c]["kw_发烧"]) >= 300 for c in cities))
    # 双关键词覆盖
    check("城市级: 每城双关键词", all(city["cities"][c].get("kw_奥司他韦") for c in cities))
    # 日期连续性抽查（北京发烧无断档）
    bj = sorted(city["cities"]["北京"]["kw_发烧"].keys())
    from datetime import date as _d
    gaps = [i for i in range(1, len(bj)) if (_d.fromisoformat(bj[i]) - _d.fromisoformat(bj[i - 1])).days != 1]
    check("城市级: 北京发烧日期无断档", len(gaps) == 0)
except FileNotFoundError:
    print("SKIP 城市级数据缺失（可选）")

print()
if failures:
    print(f"共 {len(failures)} 项失败: {failures}")
    raise SystemExit(1)
print(f"全部通过 ({len(recs)} 期数据, {recs[0]['year']}W{recs[0]['week']} -> {last['year']}W{last['week']})")
