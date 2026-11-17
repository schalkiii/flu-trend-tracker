#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
common.py — 三个 CI 数据源 fetch 脚本的共用工具
所有脚本经 `from common import ...` 使用, 保持签名一致。
"""

from datetime import datetime, timezone, timedelta
from pathlib import Path
import json
import urllib.request

# 中国时区
CST = timezone(timedelta(hours=8))

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")

# 项目根目录(scripts/ 的上一级)
ROOT = Path(__file__).resolve().parent.parent


def http_get(url: str, timeout: int = 120) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def now_cst() -> datetime:
    return datetime.now(CST)


def write_data(data_file: Path, data: dict) -> None:
    """统一 JSON 落盘格式: indent=1, 尾随换行, UTF-8 无 BOM。"""
    data_file.write_text(
        json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
    )


def load_data(data_file: Path) -> dict:
    """读入已有 JSON, 缺失/损坏返回空骨架。"""
    if data_file.exists():
        try:
            return json.loads(data_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    return {"meta": {}, "records": []}
