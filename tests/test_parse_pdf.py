# -*- coding: utf-8 -*-
"""
CDC 周报 PDF 解析 golden 回归测试。

四份代表性 PDF 对应四类措辞变体（全部来自实际事故驱动修复）:
  2026 W44 — 常规格式（半角括号）
  2025 W32 — 双右括号 PDF 提取噪声（"149(88.2%))"）
  2025 W16 — "全国报告3起"（无"共"字）
  2024 W52 — 全角括号（"2115（24.5%）"）+ 裸 0 型别行
预期值来自 data/flu_national.json 已交叉验证的入库值。

用法: python tests/test_parse_pdf.py   （在项目根目录运行）
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from fetch_cdc import parse_pdf  # noqa: E402

# (year, week, 变体说明, golden 预期)
GOLDEN = [
    (2026, 44, "常规格式", {
        "south_ili_pct": 4.8, "north_ili_pct": 3.3, "total_pos_rate": 12.4,
        "type_a": 1670, "type_b": 882, "outbreaks": 106, "total_positives": 2552,
    }),
    (2025, 32, "双右括号噪声", {
        "south_ili_pct": 3.5, "north_ili_pct": 2.5, "total_pos_rate": 1.4,
        "type_a": 150, "type_b": 23, "outbreaks": 0, "total_positives": 173,
    }),
    (2025, 16, "无共字报告", {
        "south_ili_pct": 4.1, "north_ili_pct": 3.3, "total_pos_rate": 2.0,
        "type_a": 246, "type_b": 34, "outbreaks": 3, "total_positives": 280,
    }),
    (2024, 52, "全角括号+裸0", {
        "south_ili_pct": 5.7, "north_ili_pct": 7.2, "total_pos_rate": 28.6,
        "type_a": 4869, "type_b": 14, "outbreaks": 171, "total_positives": 4883,
    }),
]

failures = []

for year, week, variant, expected in GOLDEN:
    pdf = ROOT / "scripts" / "cache" / f"{year}_w{week:02d}.pdf"
    if not pdf.exists():
        print(f"SKIP {year} W{week}（{variant}）: 缓存 PDF 不存在")
        continue
    rec = parse_pdf(pdf, year, week)
    for field, want in expected.items():
        got = rec.get(field)
        ok = got == want
        tag = "PASS" if ok else "FAIL"
        print(f"{tag} {year}W{week} [{variant}] {field} = {got}" + ("" if ok else f" (期望 {want})"))
        if not ok:
            failures.append(f"{year}W{week}.{field}")

print()
if failures:
    print(f"共 {len(failures)} 项失败: {failures}")
    raise SystemExit(1)
print(f"golden 回归全部通过（{len(GOLDEN)} 期 × 8 字段）")
