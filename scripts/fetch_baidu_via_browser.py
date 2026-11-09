# -*- coding: utf-8 -*-
"""
fetch_baidu_via_browser.py — 城市级百度指数采集（webbridge UI 交互版 · 备用慢路线）

⚠ 备用路线: ~40s/词, 仅含 5 城码表。现役主路线是 fetch_baidu_fast.py（浏览器取
cipher-text 凭证后本地直连, ~2s/词, 15 城）, 主路线凭证失效时才用本脚本人工兜底。

原理: 百度指数接口对程序化请求风控(TLS指纹级), 但浏览器原生请求畅通。
本脚本通过 kimi-webbridge 驱动真实 Edge:
  1. 首页搜索框 fill+submit（SPA 路由到趋势页）
  2. 点击"全国 ▾"下拉 -> 选择目标城市（触发原生 SearchApi, 带 area 码）
  3. network 捕获响应 -> 本地调 ptbk 接口解密（ptbk 不在风控范围）

前置: daemon 由外层 shell 启动并托管（见 run_browser_fetch.sh）
"""
import json
import subprocess
import sys
import time
import urllib.request
from datetime import date, datetime, timedelta
from pathlib import Path

PROJ = Path(r"C:/Users/qi.shao/WorkBuddy/2026-11-05-16-40-57/flu-trend-tracker")
REQDIR = PROJ / "scripts"
DATA_FILE = PROJ / "data" / "flu_cities.json"
COOKIE_FILE = REQDIR / "baidu_cookie.txt"
WB = r"http://127.0.0.1:10086/command"
SESSION = "flu-trend"

KEYWORDS = ["发烧", "奥司他韦"]
CITIES = {"北京": 911, "上海": 910, "广州": 95, "深圳": 94, "成都": 97}

_reqfile = REQDIR / "_wb_req_tmp.json"


def call(action, args, timeout=40):
    """调 webbridge, 返回 envelope dict。响应走 stdout（不做任何文件删除, 避免触发安全钩子）。"""
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


def find_searchbox():
    env = call("snapshot", {})
    if not env.get("ok"):
        return None
    def walk(nodes):
        for n in nodes:
            if n.get("role") == "searchbox":
                return n.get("ref")
            r = walk(n.get("children", []))
            if r:
                return r
        return None
    return walk(env["data"]["tree"])


def _has_searchbox(env):
    def walk(nodes):
        for n in nodes:
            if n.get("role") == "searchbox":
                return True
            if walk(n.get("children", [])):
                return True
        return False
    return walk(env["data"].get("tree", []))


def ensure_home_page():
    """确保当前 tab 是干净的百度指数首页（有搜索框）。
    页面崩在坏 hash 时, 通过 blank 中转 + 清 storage + 重载自愈。"""
    for attempt in range(3):
        env = call("snapshot", {})
        if env.get("ok") and "index.baidu.com" in (env["data"].get("url") or "") \
                and _has_searchbox(env):
            return True
        print(f"  .. 页面异常, 恢复中 (attempt {attempt + 1})")
        call("navigate", {"url": "about:blank"})
        time.sleep(1.5)
        call("navigate", {"url": "https://index.baidu.com/v2/index.html"})
        time.sleep(4)
        # SPA 加载后立即清 storage 并跳回首页路由（防止 router 恢复坏状态）
        call("evaluate", {"code":
            "(() => { try { localStorage.clear(); sessionStorage.clear(); } catch (e) {}"
            " location.replace('https://index.baidu.com/v2/index.html#/'); return 'ok'; })()"})
        time.sleep(9)
    return False


def search_keyword(kw):
    """首页搜索关键词（SPA 路由到趋势页）。输入框是 input[type=search].search-input。"""
    sb = find_searchbox()
    if not sb:
        raise RuntimeError("searchbox not found")
    call("fill", {"selector": sb, "value": kw})
    r = call("evaluate", {"code":
        "(() => { const sb = document.querySelector('input.search-input');"
        " if (!sb) return 'no-input';"
        " const f = sb.closest('form');"
        " if (!f) return 'no-form';"
        " f.requestSubmit(); return 'submitted'; })()"})
    val = (r.get("data", {}) or {}).get("value")
    if val != "submitted":
        raise RuntimeError(f"submit 失败: {val}")
    time.sleep(8)


def find_region_button():
    """趋势页搜索指数卡片的地域按钮。返回 (ref, 当前地域名) 或 (None, None)。
    树里有三个 ▾ 下拉（近30天/PC+移动/地域）, 必须精确匹配:
    name 去掉 ▾/空白后 == "全国" 或某城市名。"""
    env = call("snapshot", {})
    if not env.get("ok"):
        return None, None
    region_names = {"全国"} | set(CITIES.keys())

    def norm(name):
        return (name or "").replace("▾", "").replace("\xa0", " ").strip()

    def walk(nodes):
        for n in nodes:
            if n.get("role") == "button":
                if norm(n.get("name")) in region_names:
                    return n.get("ref"), norm(n.get("name"))
            r = walk(n.get("children", []))
            if r:
                return r
        return None

    r = walk(env["data"]["tree"])
    return r if r else (None, None)


# 城市所在省份（直辖市无需二级展开）
PROVINCE_OF = {"广州": "广东", "深圳": "广东", "成都": "四川"}

CLICK_TEXT_JS = (
    "(() => {"
    " const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);"
    " let node;"
    " while ((node = walker.nextNode())) {"
    "   if (node.textContent.trim() === '%s') {"
    "     const el = node.parentElement;"
    "     el.click(); return 'clicked';"
    "   }"
    " }"
    " return 'not-found';"
    "})()"
)


def reset_region_to_national():
    """把地域选择重置回"全国"。当前地域按钮的文字可能是城市名, 先找到它点开,
    若处于城市列表状态则先点"所有省份"回退, 再点"全国"。"""
    env = call("snapshot", {})
    if not env.get("ok"):
        return False
    region_names = {"全国"} | set(CITIES.keys())

    def norm(name):
        return (name or "").replace("▾", "").replace("\xa0", " ").strip()

    # 找当前地域按钮（值可能是全国/北京/.../成都）
    btn_ref = None
    def walk(nodes):
        nonlocal btn_ref
        for n in nodes:
            if n.get("role") == "button" and norm(n.get("name")) in region_names:
                btn_ref = n.get("ref")
                return
            walk(n.get("children", []))
    walk(env["data"]["tree"])
    if not btn_ref:
        return False
    call("click", {"selector": btn_ref})
    time.sleep(1.5)
    # 若出现"所有省份"（省份列表），直接点"全国"
    r = call("evaluate", {"code": CLICK_TEXT_JS % "全国"})
    if "clicked" in ((r.get("data", {}) or {}).get("value") or ""):
        time.sleep(4)
        return True
    # 若处于城市列表（上次选了省份），先回省份列表
    r = call("evaluate", {"code": CLICK_TEXT_JS % "所有省份"})
    if "clicked" in ((r.get("data", {}) or {}).get("value") or ""):
        time.sleep(1.5)
        r = call("evaluate", {"code": CLICK_TEXT_JS % "全国"})
        if "clicked" in ((r.get("data", {}) or {}).get("value") or ""):
            time.sleep(4)
            return True
    return False


def _dropdown_open():
    """下拉浮层是否打开（省份/城市列表特征文本出现）。"""
    r = call("evaluate", {"code":
        "(() => { const t = document.body.innerText;"
        " return (t.includes('所有省份') || t.includes('直辖市') ||"
        " t.includes('广东省') || t.includes('四川省')) ? 'open' : 'closed'; })()"})
    return "open" in ((r.get("data", {}) or {}).get("value") or "")


def select_region(region_ref, city_name):
    """点开地域下拉, 选择城市（原子操作, 不依赖前置状态）。
    下拉可能处于省份列表或城市列表状态:
      - 省份列表: 直辖市直接点; 地级市先点省份再点城市
      - 城市列表（上次选过省）: 先点"所有省份"回退
    点击 region_ref 后验证浮层是否打开; 未打开说明 ref 过期, 重新 snapshot 取新 ref 重试。"""
    opened = False
    for attempt in range(3):
        call("click", {"selector": region_ref})
        time.sleep(1.5)
        if _dropdown_open():
            opened = True
            break
        # ref 过期: 重新 snapshot 拿新 ref
        rb = find_region_button()
        if rb:
            region_ref = rb
        print(f"    [select_region] 下拉未打开, 重试 (attempt {attempt + 1})")
    if not opened:
        print("    [select_region] 下拉无法打开")
        return False

    def click_js(text, verbose=True):
        r = call("evaluate", {"code": CLICK_TEXT_JS % text})
        val = ((r.get("data", {}) or {}).get("value") or "")
        if verbose:
            print(f"    [select_region] click '{text}' -> {val}")
        return "clicked" in val

    province = PROVINCE_OF.get(city_name)

    # 1) 城市名直接点（直辖市在省份列表 / 恰好停在正确城市列表时）
    if click_js(city_name):
        time.sleep(4.5)
        return True

    # 2) 非直辖市: 先点省份（当前在省份列表视图时）
    if province and click_js(province):
        time.sleep(1.5)
        if click_js(city_name):
            time.sleep(4.5)
            return True

    # 3) 可能停在别的城市列表视图: 回省份列表再走一遍
    if click_js("所有省份", verbose=False):
        time.sleep(1.5)
        if province and click_js(province, verbose=False):
            time.sleep(1.5)
            if click_js(city_name):
                time.sleep(4.5)
                return True
        # 4) 直辖市在回退后的省份列表里
        if click_js(city_name, verbose=False):
            time.sleep(4.5)
            return True
    return False


def capture_area_request(area_code, kw):
    """捕获 SearchApi/index 且 area=code + word 含 kw 的请求。
    URL 形如: .../SearchApi/index?area=911&word=[[{"name":"发烧","wordType":1}]]&days=30
    body 的 userIndexes[0].word 是 list: [{"name": "发烧", "wordType": 1}]
    返回 {uniqid, enc, start, end} 或 None。"""
    env = call("network", {"cmd": "list", "filter": "SearchApi/index"})
    if not env.get("ok"):
        return None
    matched = None
    for r in reversed(env["data"].get("requests", [])):  # 从最新往回找
        u = r["url"]
        if not (f"area={area_code}&" in u or u.endswith(f"area={area_code}")):
            continue
        det = call("network", {"cmd": "detail", "requestId": r["requestId"]})
        if not det.get("ok"):
            continue
        body = det["data"]["body"]
        if body.get("status") != 0:
            continue
        data = body["data"]
        uis = data.get("userIndexes", [])
        if not uis:
            continue
        ui = uis[0]
        # word 是 list: [{"name": kw, ...}], 严格校验词一致
        w = ui.get("word")
        wname = w[0].get("name") if isinstance(w, list) and w else None
        if wname != kw:
            continue
        matched = {
            "uniqid": data["uniqid"],
            "enc": ui["all"]["data"],
            "start": ui["all"]["startDate"],
            "end": ui["all"]["endDate"],
        }
        break
    return matched


def local_ptbk_decrypt(uniqid, enc):
    """本地调 ptbk + 替换表解密。接口限速: 失败时指数退避重试。"""
    cookie = COOKIE_FILE.read_text(encoding="utf-8").strip()
    pj = None
    for attempt in range(4):
        req = urllib.request.Request(
            f"https://index.baidu.com/Interface/ptbk?uniqid={uniqid}",
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                              "(KHTML, like Gecko) Chrome/156.0.0.0 Safari/537.36 Edg/156.0.0.0",
                "Referer": "https://index.baidu.com/v2/index.html",
                "Cookie": cookie,
            })
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                pj = json.loads(resp.read().decode())
        except Exception:
            pj = None
        if pj and pj.get("status") == 0 and pj.get("data"):
            break
        # status 10001 = exceed speed limit -> 退避
        wait = 20 * (attempt + 1)
        print(f"  .. ptbk 限速/失败(status={pj.get('status') if pj else 'err'}), 等 {wait}s")
        time.sleep(wait)
    if not pj or pj.get("status") != 0 or not pj.get("data"):
        return None
    ptbk = pj["data"]
    n = len(ptbk) // 2
    table = dict(zip(ptbk[:n], ptbk[n:]))
    dec = "".join(table.get(ch, "") for ch in enc)
    if not dec:
        return None
    return [int(v) if v else 0 for v in dec.split(",")]


def main():
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else 2
    # 第2参数: 只采这些城市（逗号分隔），用于增量补采
    only = set(sys.argv[2].split(",")) if len(sys.argv) > 2 else None

    if DATA_FILE.exists():
        data = json.loads(DATA_FILE.read_text(encoding="utf-8"))
    else:
        data = {"meta": {}, "cities": {}}

    ok_count = 0
    for city, area in list(CITIES.items())[:limit]:
        if only and city not in only:
            continue
        for kw in KEYWORDS:
            print(f"=== {city}({area}) [{kw}] ===")
            try:
                # 1. 确保首页可用（页面崩溃自愈, 可能发生导航）
                if not ensure_home_page():
                    print("  !! 首页无法恢复, 跳过")
                    continue
                # 2. 搜索前开捕获（搜索触发的页面加载请求就带 area 参数）
                call("network", {"cmd": "start"})
                # 3. 搜索关键词（SPA 路由到趋势页）
                search_keyword(kw)
                # 4. 若地域按钮已是目标城市（上次残留）, 无需选择, 请求已在捕获中
                rb, cur = None, None
                for _ in range(3):  # 页面加载时序抖动, 重试
                    rb, cur = find_region_button()
                    if rb:
                        break
                    time.sleep(3)
                if not rb:
                    print("  !! 找不到地域按钮")
                    continue
                if cur == city:
                    print(f"  .. 地域已是 {city}, 跳过选择")
                    time.sleep(3)  # 等页面数据加载完
                elif not select_region(rb, city):
                    print(f"  !! 选择 {city} 失败")
                    continue
                # 5. 捕获请求（校验 words + area 双参数; 响应有延迟, 带轮询）
                cap = None
                for attempt in range(4):
                    cap = capture_area_request(area, kw)
                    if cap:
                        break
                    time.sleep(3)
                # 5. 解密
                vals = local_ptbk_decrypt(cap["uniqid"], cap["enc"])
                if not vals:
                    print("  !! ptbk 解密失败")
                    continue
                # 6. 入库
                d = date.fromisoformat(cap["start"])
                series = {}
                for v in vals:
                    series[d.isoformat()] = v
                    d += timedelta(days=1)
                cd = data["cities"].setdefault(city, {})
                key = f"kw_{kw}"
                merged = cd.get(key, {})
                merged.update(series)
                cd[key] = merged
                cd["area_code"] = area
                print(f"  OK: {len(series)} 天 ({cap['start']}~{cap['end']}), 最新值 {vals[-1]}")
                ok_count += 1
                # 7. 重置地域为全国（下次搜索会重置, 无需额外操作）
                time.sleep(2)
            except Exception as e:
                print(f"  !! 异常: {e}")

    data["meta"] = {
        "source": "百度指数（index.baidu.com）搜索指数（浏览器 UI 采集）",
        "keywords": KEYWORDS,
        "city_count": len(data["cities"]),
        "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "note": "搜索指数为相对值, 与流感活动相关性经文献验证 (r≈0.85, 领先 ILI 1-2 周)。仅供参考, 不构成任何医疗建议。",
    }
    DATA_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"=== 完成: {ok_count} 组数据入库 -> {DATA_FILE.name} ===")


if __name__ == "__main__":
    main()
