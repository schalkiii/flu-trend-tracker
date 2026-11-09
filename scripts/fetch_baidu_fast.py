# -*- coding: utf-8 -*-
"""
fetch_baidu_fast.py — 城市级百度指数快速采集（本地直连版）

路线（已实测验证）:
  1. 浏览器(webbridge)搜索任意词一次 -> 从原生请求头捕获 cipher-text + 完整 cookie
     (cipher-text 由页面 JS 实时生成, 是百度指数风控的通行证, 格式: ts_ts_base64)
  2. 之后全部本地 curl 直连:
     SearchApi/index?area=<code>&word=[[{"name":"<kw>","wordType":1}]]&days=30 -> status 0 + 加密数据
     Interface/ptbk?uniqid=<id> -> 替换表 -> 本地解密
  比纯浏览器 UI 路线快 ~20 倍（每词 ~2s vs ~40s）, 无 UI 点击的时序脆弱性。

用法:
  python fetch_baidu_fast.py            # 全部 15 城 x 2 词
  python fetch_baidu_fast.py 北京,上海  # 指定城市
前置: daemon+Edge 运行中（由 run_browser_fetch.sh 托管, 或手动确保扩展已连接）
"""
import json
import subprocess
import sys
import time
import urllib.request
from datetime import date, datetime, timedelta
from pathlib import Path
from urllib.parse import quote

PROJ = Path(r"C:/Users/qi.shao/WorkBuddy/2026-11-05-16-40-57/flu-trend-tracker")
DATA_FILE = PROJ / "data" / "flu_cities.json"
WB = r"http://127.0.0.1:10086/command"
SESSION = "flu-trend"

KEYWORDS = ["发烧", "奥司他韦"]
# 15 城市代码（百度指数 area 码, 社区逆向维护）
CITIES = {
    "北京": 911, "上海": 910, "广州": 95, "深圳": 94, "成都": 97,
    "杭州": 96, "武汉": 90, "西安": 93, "南京": 83, "重庆": 92,
    "天津": 85, "苏州": 82, "长沙": 88, "沈阳": 84, "青岛": 86,
}
DAYS = 30

_reqfile = PROJ / "scripts" / "_wb_req_tmp.json"


def _cli_days():
    """--days N 命令行参数（默认 30）。"""
    if "--days" in sys.argv:
        return int(sys.argv[sys.argv.index("--days") + 1])
    return DAYS


def call(action, args, timeout=40):
    """调 webbridge, 返回 envelope dict。"""
    req = {"action": action, "args": args, "session": SESSION}
    json.dump(req, open(_reqfile, "w", encoding="utf-8"), ensure_ascii=False)
    r = subprocess.run(
        ["curl", "-s", "--noproxy", "*", "--max-time", str(timeout), "-X", "POST",
         WB, "-H", "Content-Type: application/json", "--data-binary", f"@{_reqfile}"],
        capture_output=True,
    )
    if not r.stdout:
        raise RuntimeError(f"daemon 无响应 ({action})")
    return json.loads(r.stdout.decode("utf-8", "replace"))


def _has_searchbox(env):
    def walk(nodes):
        for n in nodes:
            if n.get("role") == "searchbox":
                return True
            if walk(n.get("children", [])):
                return True
        return False
    return walk(env.get("data", {}).get("tree", []))


def get_cipher_from_browser():
    """让浏览器搜一次词, 捕获原生 SearchApi 请求的 cipher-text/cookie/UA。"""
    # 借 tab
    env = call("snapshot", {})
    if not env.get("ok") or "index.baidu.com" not in (env["data"].get("url") or ""):
        # 页面不对, 导航到首页
        call("navigate", {"url": "https://index.baidu.com/v2/index.html"})
        time.sleep(8)
        env = call("snapshot", {})

    # 找搜索框（首页）: fill+submit
    def find_searchbox(nodes):
        for n in nodes:
            if n.get("role") == "searchbox":
                return n.get("ref")
            r = find_searchbox(n.get("children", []))
            if r:
                return r
        return None

    sb = find_searchbox(env["data"].get("tree", []))
    call("network", {"cmd": "start"})
    if sb:
        call("fill", {"selector": sb, "value": KEYWORDS[0]})
        call("evaluate", {"code":
            "(() => { const sb = document.querySelector('input.search-input');"
            " if (!sb) return 'no-input';"
            " const f = sb.closest('form');"
            " if (!f) return 'no-form';"
            " f.requestSubmit(); return 'submitted'; })()"})
        time.sleep(8)
    else:
        # 已在趋势页: 直接刷新触发请求
        call("evaluate", {"code": "location.reload(); 'reloading'"})
        time.sleep(8)

    # 捕获原生请求
    env = call("network", {"cmd": "list", "filter": "SearchApi/index"})
    reqs = (env.get("data") or {}).get("requests", [])
    if not reqs:
        raise RuntimeError("未捕获到原生 SearchApi 请求")
    det = call("network", {"cmd": "detail", "requestId": reqs[0]["requestId"]})
    h = det["data"]["requestHeaders"]
    ct = h.get("cipher-text")
    if not ct:
        raise RuntimeError("原生请求无 cipher-text 头")
    return {"cipher_text": ct, "cookie": h["cookie"], "ua": h["user-agent"]}


def api_get(creds, url):
    """本地 curl 直连（带 cipher-text）。"""
    r = subprocess.run(["curl", "-s", "--max-time", "15",
        "-H", f"User-Agent: {creds['ua']}",
        "-H", "Referer: https://index.baidu.com/v2/main/index.html",
        "-H", "Accept: application/json, text/plain, */*",
        "-H", f"cipher-text: {creds['cipher_text']}",
        "-H", f"Cookie: {creds['cookie']}",
        url], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=25)
    if not r.stdout:
        return None
    try:
        return json.loads(r.stdout)
    except Exception:
        return None


def fetch_one(creds, area, kw, days=DAYS):
    """拉一个城市×词。返回 (series_dict, meta) 或 None。
    注意: days 必须 ≤ 365。超过后 API 静默切换周粒度（如 days=400 返回 58 点跨 400 天），
    而本函数按"连续日期"写值，会造成日期错位污染 —— main 已对 days 做上限拦截。"""
    word_param = quote("[" + json.dumps([{"name": kw, "wordType": 1}], ensure_ascii=False) + "]", safe="")
    url = (f"https://index.baidu.com/api/SearchApi/index?area={area}"
           f"&word={word_param}&days={days}")
    j = api_get(creds, url)
    if not j or j.get("status") != 0:
        return None
    data = j["data"]
    uis = data.get("userIndexes") or []
    if not uis:
        return None
    ui = uis[0]
    w = ui.get("word")
    wname = w[0].get("name") if isinstance(w, list) and w else None
    if wname != kw:
        return None
    # ptbk 解密
    req = urllib.request.Request(
        f"https://index.baidu.com/Interface/ptbk?uniqid={data['uniqid']}",
        headers={"User-Agent": creds["ua"],
                 "Referer": "https://index.baidu.com/v2/index.html",
                 "Cookie": creds["cookie"]})
    with urllib.request.urlopen(req, timeout=15) as resp:
        pj = json.loads(resp.read().decode())
    if pj.get("status") != 0 or not pj.get("data"):
        return None
    ptbk = pj["data"]
    n = len(ptbk) // 2
    table = dict(zip(ptbk[:n], ptbk[n:]))
    dec = "".join(table.get(c, "") for c in ui["all"]["data"])
    if not dec:
        return None
    vals = [int(v) if v else 0 for v in dec.split(",")]
    d = date.fromisoformat(ui["all"]["startDate"])
    series = {}
    for v in vals:
        series[d.isoformat()] = v
        d += timedelta(days=1)
    return series, ui["all"]["startDate"], ui["all"]["endDate"]


def main():
    only = set(sys.argv[1].split(",")) if len(sys.argv) > 1 and not sys.argv[1].startswith("--") else None
    days = _cli_days()
    if days > 365:
        # API 粒度陷阱: days>365 静默切周粒度, 按日写入会错位污染（见 fetch_one docstring）
        print(f"!! 拒绝执行: days={days} 超过 365。API 会切周粒度导致日期错位。")
        print("   需要更早的历史时, 分多次 ≤365 天窗口采集后合并。")
        sys.exit(2)

    if DATA_FILE.exists():
        data = json.loads(DATA_FILE.read_text(encoding="utf-8"))
    else:
        data = {"meta": {}, "cities": {}}

    # 1. 浏览器拿凭证（只需一次）
    print(f"== 从浏览器获取 cipher-text 凭证 (days={days}) ==")
    creds = get_cipher_from_browser()
    print(f"   OK (cipher-text {creds['cipher_text'][:40]}...)")

    ok_count = 0
    for city, area in CITIES.items():
        if only and city not in only:
            continue
        for kw in KEYWORDS:
            try:
                r = fetch_one(creds, area, kw, days=days)
                if not r:
                    print(f"  {city} [{kw}]: 拉取/解密失败")
                    time.sleep(2)
                    continue
                series, start, end = r
                cd = data["cities"].setdefault(city, {})
                key = f"kw_{kw}"
                merged = cd.get(key, {})
                merged.update(series)
                cd[key] = merged
                cd["area_code"] = area
                ok_count += 1
                print(f"  {city} [{kw}]: OK {len(series)} 天 ({start}~{end}), 最新 {list(series.values())[-1]}")
                time.sleep(1.5)  # 温和限速
            except Exception as e:
                print(f"  {city} [{kw}]: 异常 {str(e)[:60]}")
                time.sleep(2)

    data["meta"] = {
        "source": "百度指数（index.baidu.com）搜索指数（本地直连采集）",
        "keywords": KEYWORDS,
        "city_count": len(data["cities"]),
        "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "note": "搜索指数为相对值, 与流感活动相关性经文献验证 (r≈0.85, 领先 ILI 1-2 周)。仅供参考, 不构成任何医疗建议。",
    }
    DATA_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"== 完成: {ok_count} 组入库, 共 {len(data['cities'])} 城 -> {DATA_FILE.name} ==")


if __name__ == "__main__":
    main()
