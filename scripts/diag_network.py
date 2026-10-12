#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""外网连通性诊断（决定 step3 的文献检索为何 0 结果）。

逐个目标对比两种方式：**走环境代理** vs **绕过环境代理**（`trust_env=False`）。
本项目里既有 `_should_bypass_env_proxy()` 说明"某些域名必须绕过代理"，
所以这里必须两种都试，才能区分"网络不通"与"代理配置不当"。
"""

import os
import sys
import time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

for _s in ("stdout", "stderr"):
    try:
        getattr(sys, _s).reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

import requests  # noqa: E402

TARGETS = [
    ("EuropePMC",
     "https://www.ebi.ac.uk/europepmc/webservices/rest/search"
     "?query=radiomics&format=json&pageSize=1"),
    ("arXiv",
     "http://export.arxiv.org/api/query?search_query=all:radiomics&max_results=1"),
    ("CrossRef",
     "https://api.crossref.org/works?query=radiomics&rows=1"),
    ("DeepSeek",
     "https://api.deepseek.com/v1/models"),
    ("GitHub",
     "https://api.github.com/zen"),
]

print("=" * 84)
print("环境代理变量")
print("=" * 84)
found = False
for k, v in sorted(os.environ.items()):
    if "proxy" in k.lower():
        print(f"   {k} = {v}")
        found = True
if not found:
    print("   （无）")

print()
print("=" * 84)
print("逐目标连通性（走代理 / 绕过代理）")
print("=" * 84)
for name, url in TARGETS:
    for bypass in (False, True):
        tag = "绕过代理" if bypass else "走环境代理"
        try:
            t0 = time.time()
            if bypass:
                s = requests.Session()
                s.trust_env = False
                r = s.get(url, timeout=15)
            else:
                r = requests.get(url, timeout=15)
            print(f"   {name:10} {tag:8} HTTP {r.status_code:<4} "
                  f"{time.time() - t0:5.2f}s  len={len(r.content)}")
            break
        except Exception as e:  # noqa: BLE001
            print(f"   {name:10} {tag:8} 失败 {type(e).__name__}: {str(e)[:78]}")
    else:
        print(f"   {name:10} 两种方式都失败")
