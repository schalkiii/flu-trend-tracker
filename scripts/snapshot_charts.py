# -*- coding: utf-8 -*-
"""流感监测站图表截图：index.html → 各图表 PNG（小红书发布素材）。

技术路线与 etf-national-team-monitor/scripts/snapshot_charts.py 一致（2026-11-09
实测定型）：
  ① Playwright 在本机 launch 握手挂起 → 弃用，用 Edge 原生 headless CLI。
  ② Edge stdout 在 python 子进程下被吞 → 一切走文件，不用 dump-dom。
  ③ --screenshot 写文件正常。
  marker 定位：给图表容器注入高饱和荧光色 outline（不占布局空间），
  全页截图后按颜色扫描像素定位 → 精确裁剪。

用法：
  python scripts/snapshot_charts.py                # 最新线上数据 → out/xhs/
  python scripts/snapshot_charts.py --out D:\\xhs  # 指定输出目录
"""
from __future__ import annotations

import argparse
import subprocess
import urllib.request
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# 图表容器 → (输出文件名, marker 颜色 RGB)
# 高饱和荧光色，站点米纸底色下不存在，扫描零误报
CHART_TARGETS: list[tuple[str, str, tuple[int, int, int]]] = [
    ("chart-ili", "01_ili", (255, 0, 254)),           # 图1 ILI% 走势
    ("chart-pos", "02_pos", (0, 255, 254)),           # 图2 阳性率
    ("chart-outbreak", "03_outbreak", (255, 254, 0)),  # 图3 暴发疫情
    ("chart-city", "04_city", (255, 0, 127)),         # 图4 城市搜索代理
    ("chart-pathogen", "05_pathogen", (0, 127, 255)),  # 图5 多病原分解
    ("chart-notifiable", "06_notifiable", (127, 255, 0)),  # 图6 法定月度病例
]

# 站点容器 max-width 1080 + 页边距 → 视口 1140
VIEWPORT_W = 1140
PAGE_H_DEFAULT = 14000   # 实测全页 ~10500 CSS px,分档递增防截断
SCALE = 2                # force-device-scale-factor
MARKER_W = 6             # outline 宽度(px)
# outline 默认贴着元素边框内侧画,会把紧贴 sec-note 右缘等处裁掉几像素。
# 加 outline-offset 让 marker 画在 section 外侧,裁剪时沿 marker 外缘取框,
# 内容区域完整覆盖,零内缩零损失。
MARKER_OFFSET = 2        # outline-offset,marker 外缘距内容边界 = MARKER_W + MARKER_OFFSET

# 截图窗口（最短档）：图1-3 用近半年(26周)，图4 用近30天
SHORTEST_WINDOW = """
document.querySelectorAll('[data-range]').forEach(b => {
  if (b.dataset.range === "26") b.click();
});
document.querySelectorAll('[data-crange]').forEach(b => {
  if (b.dataset.crange === "30") b.click();
});
"""

MARKER_CSS_TMPL = "#{sid}{{outline:{w}px solid rgb({r},{g},{b});outline-offset:{off}px;}}"


def find_edge() -> str:
    for c in (r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
              r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
              r"C:\Program Files\Google\Chrome\Application\chrome.exe"):
        if Path(c).exists():
            return c
    raise SystemExit("未找到 msedge.exe / chrome.exe")


def fetch_page(tmp_html: Path) -> None:
    """抓线上 index.html 并本地化（去 nav 锚点跳转依赖不影响截图,数据走相对路径 data/）。"""
    html = urllib.request.urlopen(
        "https://schalkiii.github.io/flu-trend-tracker/", timeout=30).read().decode("utf-8")
    tmp_html.write_text(html, encoding="utf-8")


def inject_markers(html: str) -> str:
    # marker 打在整个 <section> 上：标题/图例/切换按钮一并入图（chart-box 只是裸图）
    sections = ["g-ili", "g-pos", "g-outbreak", "g-city", "g-pathogen", "g-notifiable"]
    rules = "\n".join(
        MARKER_CSS_TMPL.format(sid=sid, w=MARKER_W, off=MARKER_OFFSET,
                               r=c[0], g=c[1], b=c[2])
        for sid, (_, _, c) in zip(sections, CHART_TARGETS)
    )
    # 数据 fetch 完成后自动切最短窗口（脚本在 </body> 前,fetch 回调晚于此执行,
    # 用 setInterval 轮询等按钮渲染/绑定完成后再点击）
    auto_click = f"""<script>
(function poll() {{
  var r = document.querySelectorAll('[data-range]'), c = document.querySelectorAll('[data-crange]');
  if (r.length && c.length) {{ {SHORTEST_WINDOW.strip()} }}
  else {{ setTimeout(poll, 100); }}
}})();
</script>"""
    return html.replace("</head>", f"<style>{rules}</style></head>", 1) \
               .replace("</body>", f"{auto_click}</body>", 1)


def edge_screenshot(browser: str, target, out_png: Path, page_h: int) -> None:
    """target: 本地 HTML 路径或 http URL 字符串。"""
    uri = target if isinstance(target, str) else target.resolve().as_uri()
    r = subprocess.run(
        [browser, "--headless", "--disable-gpu",
         f"--screenshot={out_png}",
         f"--window-size={VIEWPORT_W},{page_h}",
         f"--force-device-scale-factor={SCALE}",
         "--virtual-time-budget=15000",
         uri],
        capture_output=True, timeout=180)
    if not out_png.exists() or out_png.stat().st_size < 10000:
        raise SystemExit(f"截图失败: {r.stderr.decode('utf-8', errors='replace')[:300]}")


def scan_markers(full_png: Path) -> dict[str, dict]:
    from PIL import Image

    img = Image.open(full_png).convert("RGB")
    px = img.load()
    w_css, h_css = img.width // SCALE, img.height // SCALE

    results: dict[str, dict] = {}
    for cid, _, color in CHART_TARGETS:
        # 粗扫定位大致区域（步长4会有±4px误差,后面精扫修正）
        min_x, min_y, max_x, max_y = 10**9, 10**9, -1, -1
        for y in range(0, img.height, 4):
            for x in range(0, img.width, 4):
                p = px[x, y]
                if (abs(p[0] - color[0]) <= 12 and abs(p[1] - color[1]) <= 12
                        and abs(p[2] - color[2]) <= 12):
                    min_x, max_x = min(min_x, x), max(max_x, x)
                    min_y, max_y = min(min_y, y), max(max_y, y)
        if max_x < 0:
            continue

        def is_marker(x: int, y: int) -> bool:
            p = px[x, y]
            return (abs(p[0] - color[0]) <= 12 and abs(p[1] - color[1]) <= 12
                    and abs(p[2] - color[2]) <= 12)

        # 精扫：从粗扫边界向外逐像素推到 marker 真实外缘
        while min_x > 0 and is_marker(min_x - 1, (min_y + max_y) // 2):
            min_x -= 1
        while max_x < img.width - 1 and is_marker(max_x + 1, (min_y + max_y) // 2):
            max_x += 1
        while min_y > 0 and is_marker((min_x + max_x) // 2, min_y - 1):
            min_y -= 1
        while max_y < img.height - 1 and is_marker((min_x + max_x) // 2, max_y + 1):
            max_y += 1

        # marker 带 = offset(MARKER_OFFSET) + outline(MARKER_W),全在内容边界外侧。
        # 内容边界 = marker 外缘 + MARKER_W（贴 marker 内侧的 offset 区是透明的,
        # 露出底色,不属于内容,裁掉）→ 裁剪框 = marker 外缘向内收 MARKER_W,
        # 再加 1px 缓冲（覆盖 //SCALE 舍入误差）。marker 带自身完整排除在外。
        pad = MARKER_W + 1   # 7px
        x0 = max(0, min_x // SCALE + pad)
        y0 = max(0, min_y // SCALE + pad)
        x1 = min((max_x + 1) // SCALE - pad, w_css)
        y1 = min((max_y + 1) // SCALE - pad, h_css)
        if x1 - x0 < 50 or y1 - y0 < 50:
            continue
        results[cid] = {"x": x0, "y": y0, "w": x1 - x0, "h": y1 - y0}
    return results


def crop_charts(full_png: Path, coords: dict[str, dict], out_dir: Path) -> list[Path]:
    from PIL import Image

    img = Image.open(full_png)
    outputs: list[Path] = []
    for cid, name, _ in CHART_TARGETS:
        c = coords.get(cid)
        if not c:
            print(f"[skip] {cid}: marker 未找到或页面截断")
            continue
        box = (c["x"] * SCALE, c["y"] * SCALE,
               (c["x"] + c["w"]) * SCALE, (c["y"] + c["h"]) * SCALE)
        out_file = out_dir / f"flu_{name}.png"
        img.crop(box).save(out_file)
        outputs.append(out_file)
        print(f"[ok] {cid} {c['w']}x{c['h']} -> {out_file.name}")
    return outputs


def main() -> None:
    ap = argparse.ArgumentParser(description="流感站图表截图（发布素材）")
    ap.add_argument("--out", help="输出目录（默认 out/xhs/）")
    args = ap.parse_args()

    out_dir = Path(args.out) if args.out else PROJECT_ROOT / "out" / "xhs"
    out_dir.mkdir(parents=True, exist_ok=True)
    browser = find_edge()

    # 页面用 fetch("data/*.json") 加载数据,file:// 下被 CORS 拦截（图表全空）。
    # 必须走本地 HTTP 服务渲染。用仓库本地 index.html（与线上同步）。
    import http.server
    import socketserver
    import threading

    PORT = 8791
    handler = http.server.SimpleHTTPRequestHandler
    httpd = socketserver.TCPServer(("127.0.0.1", PORT), handler)
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    base = f"http://127.0.0.1:{PORT}/"

    # 带 marker 的临时页（仓库根下,fetch 相对路径不变）
    marked = PROJECT_ROOT / "_marked_snapshot.html"
    marked.write_text(
        inject_markers((PROJECT_ROOT / "index.html").read_text(encoding="utf-8")),
        encoding="utf-8")

    try:
        print(f"[1/3] Edge 全页截图（section 版+最短窗口,{VIEWPORT_W}x{PAGE_H_DEFAULT} @2x）...")
        marked_png = out_dir / "_marked_full.png"
        edge_screenshot(browser, base + "_marked_snapshot.html", marked_png, PAGE_H_DEFAULT)

        print("[2/3] 扫描 marker 坐标并裁剪 ...")
        coords = scan_markers(marked_png)
        print(f"      定位到 {len(coords)}/{len(CHART_TARGETS)} 个图表")
        files = crop_charts(marked_png, coords, out_dir)

        print("[3/3] 干净版全页图 ...")
        clean_png = out_dir / "_fullpage.png"
        edge_screenshot(browser, base + "index.html", clean_png, PAGE_H_DEFAULT)
    finally:
        httpd.shutdown()
        marked.unlink(missing_ok=True)
        marked_png.unlink(missing_ok=True)

    print(f"\n完成：{len(files)} 张图表图 + 全页图 -> {out_dir}")


if __name__ == "__main__":
    main()
