# -*- coding: utf-8 -*-
"""流感监测站 → 小红书图文发布（与 etf-national-team-monitor 同路线）。

流程：
  ① scripts/snapshot_charts.py 产出图表 PNG（前置,已单独运行）
  ② 组装文案（标题≤20字,正文≤1000字）
  ③ 调 xiaohongshu-mcp REST API (localhost:18060) 发布图文
     - 默认仅自己可见（试发验证）,--public 正式发布

用法：
  python scripts/publish_xhs.py                    # 试发（仅自己可见）
  python scripts/publish_xhs.py --public           # 正式公开发布
"""
from __future__ import annotations

import argparse
import json
import urllib.request
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

XHS_API = "http://127.0.0.1:18060/mcp"   # MCP JSON-RPC 端点（本机服务绕代理）
TAGS = ["流感", "流感监测", "健康科普", "数据可视化", "公共卫生"]


def _mcp_call(name: str, arguments: dict | None = None, timeout: int = 30) -> dict:
    handlers = [urllib.request.ProxyHandler({})]
    opener = urllib.request.build_opener(*handlers)
    payload = {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
               "params": {"name": name, "arguments": arguments or {}}}
    req = urllib.request.Request(
        XHS_API, data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json",
                 "Accept": "application/json, text/event-stream"},
        method="POST")
    with opener.open(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def check_login() -> bool:
    try:
        result = _mcp_call("check_login_status")
        for item in result.get("result", {}).get("content", []):
            if "未登录" in item.get("text", "") or "❌" in item.get("text", ""):
                return False
        return True
    except Exception:
        return False


def publish(title: str, body: str, images: list[Path], public: bool) -> dict:
    arguments = {
        "title": title,
        "content": body,
        "images": [str(p) for p in images],
        "tags": TAGS,
        "visibility": "公开可见" if public else "仅自己可见",
    }
    return _mcp_call("publish_content", arguments, timeout=180)


def main() -> None:
    ap = argparse.ArgumentParser(description="流感监测发布到小红书")
    ap.add_argument("--public", action="store_true", help="公开发布（默认仅自己可见）")
    ap.add_argument("--title", help="自定义标题")
    ap.add_argument("--body", help="自定义正文")
    args = ap.parse_args()

    charts = sorted((PROJECT_ROOT / "out" / "xhs").glob("flu_*.png"))
    if not charts:
        raise SystemExit("未找到图表 PNG,先运行: python scripts/snapshot_charts.py")

    title, body = build_content()
    if args.title:
        title = args.title
    if args.body:
        body = args.body

    # 平台硬约束
    if len(title) > 20:
        title = title[:20]
    if len(body) > 1000:
        body = body[:997] + "..."

    print(f"标题({len(title)}字): {title}")
    print(f"正文({len(body)}字) 图片({len(charts)}张)")
    for p in charts:
        print(f"  {p.name}")
    print(f"可见性: {'公开' if args.public else '仅自己'}")

    if not check_login():
        print("\n[!] 未登录。先运行登录工具扫码:")
        print(r"    C:\Users\qi.shao\.etf-ntm\xhs-mcp\xiaohongshu-login-windows-amd64.exe")
        raise SystemExit(1)

    result = publish(title, body, charts, args.public)
    print(f"\n发布结果: {json.dumps(result, ensure_ascii=False)[:400]}")


def build_content() -> tuple[str, str]:
    """从 data/*.json 读最新数据组装文案。"""
    nat = json.loads((PROJECT_ROOT / "data" / "flu_national.json").read_text(encoding="utf-8"))
    recs = nat["records"] if isinstance(nat, dict) else nat
    last, prev = recs[-1], recs[-2]

    mp = json.loads((PROJECT_ROOT / "data" / "flu_multipathogen.json").read_text(encoding="utf-8"))
    mpl = mp["records"][-1]
    top3 = mpl.get("top3_outpatient", [])
    top3_vals = [mpl.get("outpatient", {}).get(p) for p in top3]

    nf = json.loads((PROJECT_ROOT / "data" / "flu_notifiable.json").read_text(encoding="utf-8"))
    nfl = nf["records"][-1]
    # 历史冬峰单月最大值
    peak = max(nf["records"], key=lambda r: r["cases"])

    d_ili = last["south_ili_pct"] - prev["south_ili_pct"]
    d_pos = last["total_pos_rate"] - prev["total_pos_rate"]

    title = f"流感监测W{last['week']:02d}：阳性率{last['total_pos_rate']}%"

    top3_str = "、".join(
        f"{p}{v}%" for p, v in zip(top3, top3_vals) if v is not None)

    body_lines = [
        f"🤧 流感监测周报追踪 · {last['year']}年第{last['week']}周（{last.get('publish_date', '')}发布）",
        "",
        "【本周要点】",
        f"· 南方ILI% {last['south_ili_pct']}%（环比{'+' if d_ili >= 0 else ''}{d_ili:.1f}pct），北方 {last['north_ili_pct']}%",
        f"· 全国流感阳性率 {last['total_pos_rate']}%（环比{'+' if d_pos >= 0 else ''}{d_pos:.1f}pct），南方 {last['south_pos_rate']}% / 北方 {last['north_pos_rate']}%",
        f"· 暴发疫情 {last['outbreaks']} 起",
        f"· 多病原监测：{top3_str}",
        f"· 法定报告：{nfl['year']}年{nfl['month']}月全国发病 {nfl['cases']:,} 例",
        "",
        f"历史冬峰单月最高 {peak['cases']:,} 例（{peak['year']}-{peak['month']:02d}），"
        "当前仍处流行季爬坡早期。南方ILI通常领先北方进入冬季高峰，"
        "未来 4—8 周是关键观察窗口。",
        "",
        "【截图窗口说明】",
        "图1—3：近半年（26 周）逐周；图4：城市搜索代理，近 30 天逐日",
        "图5：病原体分解，全部数据（2024 年第 46 周以来）；图6：法定月报，2022 年 11 月以来全部月份",
        "",
        "数据源：国家流感中心周报 / 中疾控多病原哨点监测 / 国家疾控局月报，"
        "全部机器解析、无人工修改。搜索指数为行为代理，非监测值。"
        "本内容为信息整理，不构成医疗建议。",
        "",
        "在线页面：schalkiii.github.io/flu-trend-tracker",
    ]
    return title, "\n".join(body_lines)


if __name__ == "__main__":
    main()
