#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""OCR API 备份验证（用本地 stub 服务器，**不需要真实 key**）。

要验的五件事：
  1. 原链路失败时**确实回退**到 API，且返回 `engine == "api_vision"`
  2. 请求体**形状正确**：含 `data:image/...;base64,` 图像 URL + 正确的 model
  3. 原链路成功时**不打扰 API**（零多余流量）
  4. 没配 key 时 `backup.used == False` 且原因明确（不静默）
  5. API 报 401 时**把 provider 原话暴露出来**（不静默）
  6. `backup_api: False` 可关闭备份

用法：
    python scripts/test_ocr_api_backup.py
"""

import json
import os
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
os.environ.setdefault("MIMW_SKIN", "metal")

for _s in ("stdout", "stderr"):
    try:
        getattr(sys, _s).reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

OUT = []
RESULTS = []


def say(s=""):
    OUT.append(str(s))
    print(s)


def chk(label, ok, detail=""):
    RESULTS.append((label, bool(ok), detail))
    say(f"   [{'PASS' if ok else 'FAIL'}] {label}: {detail}")


# ================================================================ stub 服务器
CAPTURED = []
MODE = {"kind": "ok"}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):   # 静音
        pass

    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(n) if n else b""
        try:
            body = json.loads(raw.decode("utf-8"))
        except Exception:
            body = {"__raw__": raw[:400].decode("utf-8", "replace")}
        CAPTURED.append({"path": self.path, "body": body,
                         "auth": self.headers.get("Authorization", "")})

        kind = MODE["kind"]
        if kind == "401":
            payload = {"error": {"message": "Authentication Fails, invalid key",
                                 "type": "authentication_error"}}
            data = json.dumps(payload).encode()
            self.send_response(401)
        elif kind == "no_vision":
            payload = {"error": {"message": "model does not support image input",
                                 "type": "invalid_request_error"}}
            data = json.dumps(payload).encode()
            self.send_response(400)
        else:
            payload = {
                "id": "chatcmpl-stub", "object": "chat.completion",
                "model": body.get("model") or "?",
                "choices": [{"index": 0, "finish_reason": "stop",
                             "message": {"role": "assistant",
                                         "content": "识别结果第一行\n识别结果第二行"}}],
                "usage": {"prompt_tokens": 111, "completion_tokens": 22},
            }
            data = json.dumps(payload).encode()
            self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


srv = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
PORT = srv.server_address[1]
threading.Thread(target=srv.serve_forever, daemon=True).start()
BASE = f"http://127.0.0.1:{PORT}/v1"
say(f"stub 服务器: {BASE}")

# ================================================================ 测试图
tmpdir = os.path.join(os.environ.get("TEMP", "."), "ocr_backup_test")
os.makedirs(tmpdir, exist_ok=True)
IMG = os.path.join(tmpdir, "sample.png")
try:
    from PIL import Image, ImageDraw
    im = Image.new("RGB", (2400, 900), "white")   # 故意大于 MAX_SIDE=2000
    d = ImageDraw.Draw(im)
    d.text((40, 40), "HELLO OCR 1234567890\nSecond line for the stub test", fill="black")
    for i in range(12):
        d.line((40, 120 + i * 40, 2300, 120 + i * 40), fill="gray")
    im.save(IMG)
    say(f"测试图: {IMG}  ({im.size[0]}x{im.size[1]}，故意超过缩放阈值)")
except Exception as e:  # noqa: BLE001
    say(f"测试图生成失败: {e}")
    sys.exit(2)

from src.services.ocr_api_backup import APIVisionOCR  # noqa: E402

say("")
say("=" * 88)
say("1) 图像编码（缩放 + data URL）")
say("=" * 88)
enc = APIVisionOCR.encode_image(IMG)
chk("编码成功", enc.get("ok") is True, f"bytes={enc.get('bytes')}")
chk("长边被缩到 <= 2000", max(enc.get("sent_size") or (0, 0)) <= 2000,
    f"{enc.get('orig_size')} → {enc.get('sent_size')} scale={enc.get('scale')}")
chk("data URL 前缀正确",
    str(enc.get("data_url") or "").startswith("data:image/jpeg;base64,"),
    (enc.get("data_url") or "")[:40] + "…")

say("")
say("=" * 88)
say("2) 回退路由 + 请求体形状（原链路失败 → 应调 API）")
say("=" * 88)
CAPTURED.clear()
MODE["kind"] = "ok"

from src.services.ocr_service import OCRService  # noqa: E402

svc = OCRService()
# 让"原链路"必定失败（模拟本地模型不可用）
svc._extract_text_from_image_primary = lambda p, c=None: {
    "text": "", "extracted_text": "", "engine": "deepseek_ocr",
    "status": "error", "error": "simulated_local_failure",
}
cfg = {"ocr_api_base_url": BASE, "ocr_api_key": "sk-stub-key",
       "ocr_api_model": "stub-vl-model"}
res = svc.extract_text_from_image(IMG, cfg)

chk("原链路失败时回退到 API", str(res.get("engine")) == "api_vision",
    f"engine={res.get('engine')}")
chk("拿到 stub 返回的文本", "识别结果第一行" in str(res.get("text") or ""),
    repr(str(res.get("text"))[:40]))
chk("记录了备份信息", bool((res.get("backup") or {}).get("used")),
    json.dumps(res.get("backup") or {}, ensure_ascii=False)[:150])
chk("记录了原链路的失败原因",
    "simulated_local_failure" in str((res.get("backup") or {}).get("primary_error") or ""),
    str((res.get("backup") or {}).get("primary_error"))[:60])

chk("stub 收到 1 次请求", len(CAPTURED) == 1, f"次数={len(CAPTURED)}")
if CAPTURED:
    body = CAPTURED[0]["body"]
    say(f"   请求体摘要: model={body.get('model')} "
        f"messages={len(body.get('messages') or [])} "
        f"auth={(CAPTURED[0]['auth'] or '')[:24]}…")
    content = ((body.get("messages") or [{}])[0].get("content") or [])
    kinds = [c.get("type") for c in content if isinstance(c, dict)]
    url = ""
    for c in content:
        if isinstance(c, dict) and c.get("type") == "image_url":
            url = str((c.get("image_url") or {}).get("url") or "")
    chk("model 透传正确", body.get("model") == "stub-vl-model",
        f"model={body.get('model')}")
    chk("content 含 text + image_url", kinds == ["text", "image_url"],
        f"kinds={kinds}")
    chk("image_url 是 data URL", url.startswith("data:image/jpeg;base64,"),
        url[:34] + "…")
    chk("Authorization 头带上 key",
        "sk-stub-key" in str(CAPTURED[0]["auth"]),
        str(CAPTURED[0]["auth"])[:30])
    chk("temperature=0（OCR 要确定性）", body.get("temperature") == 0.0,
        f"temperature={body.get('temperature')}")

say("")
say("=" * 88)
say("3) 原链路成功 → 不得打扰 API（零多余流量）")
say("=" * 88)
CAPTURED.clear()
svc2 = OCRService()
svc2._extract_text_from_image_primary = lambda p, c=None: {
    "text": "本地识别成功", "extracted_text": "本地识别成功",
    "engine": "deepseek_ocr", "status": "ok",
}
res2 = svc2.extract_text_from_image(IMG, cfg)
chk("沿用本地结果", str(res2.get("engine")) == "deepseek_ocr",
    f"engine={res2.get('engine')}")
chk("未发起 API 请求", len(CAPTURED) == 0, f"次数={len(CAPTURED)}")
chk("无 backup 字段", "backup" not in res2, f"keys={list(res2.keys())[:8]}")

say("")
say("=" * 88)
say("4) 未配 key → 明确给出原因（不静默）")
say("=" * 88)
CAPTURED.clear()
os.environ.pop("MIMW_OCR_API_KEY", None)
os.environ.pop("RSNA_JUDGE_API_KEY", None)
b = APIVisionOCR({})              # 显式空配置 + 环境也无 key
ok_avail, why = b.available()
chk("available() 为 False", ok_avail is False, why[:70])
say(f"   summary={json.dumps(b.summary(), ensure_ascii=False)}")

say("")
say("=" * 88)
say("5) API 报 401 → provider 原话必须暴露")
say("=" * 88)
CAPTURED.clear()
MODE["kind"] = "401"
svc3 = OCRService()
svc3._extract_text_from_image_primary = lambda p, c=None: {
    "text": "", "extracted_text": "", "status": "error",
    "error": "simulated_local_failure",
}
res3 = svc3.extract_text_from_image(IMG, cfg)
bk = res3.get("backup") or {}
chk("backup.used=True", bk.get("used") is True, str(bk.get("used")))
chk("backup.success=False", bk.get("success") is False, str(bk.get("success")))
chk("暴露 http_401", "401" in str(bk.get("error") or ""),
    str(bk.get("error"))[:90])
chk("暴露 provider message",
    "Authentication Fails" in str(bk.get("error") or ""),
    str(bk.get("error"))[:110])

say("")
say("=" * 88)
say("6) backup_api=False 可关闭备份")
say("=" * 88)
CAPTURED.clear()
MODE["kind"] = "ok"
res4 = svc.extract_text_from_image(IMG, {**cfg, "backup_api": False})
chk("未回退（engine 仍是原链路）", str(res4.get("engine")) != "api_vision",
    f"engine={res4.get('engine')}")
chk("未发起请求", len(CAPTURED) == 0, f"次数={len(CAPTURED)}")

say("")
say("=" * 88)
say("7) '模型不支持图像' 这类错误也要原样暴露")
say("=" * 88)
CAPTURED.clear()
MODE["kind"] = "no_vision"
res5 = svc.extract_text_from_image(IMG, cfg)
bk5 = res5.get("backup") or {}
chk("暴露 no_vision 原话",
    "does not support image" in str(bk5.get("error") or ""),
    str(bk5.get("error"))[:110])

srv.shutdown()

failed = [r for r in RESULTS if not r[1]]
say("")
say("=" * 88)
say(f"total={len(RESULTS)} passed={len(RESULTS) - len(failed)} failed={len(failed)}")
for l, ok, d in RESULTS:
    if not ok:
        say(f"   !! {l}: {d}")
say("RESULT: " + ("PASS" if not failed else "ISSUES"))

rep = os.path.join("docs", "screenshots", "ocr_api_backup.txt")
os.makedirs(os.path.dirname(rep), exist_ok=True)
with open(rep, "w", encoding="utf-8") as fh:
    fh.write("\n".join(OUT) + "\n")
print("\n报告 ->", os.path.abspath(rep))
sys.exit(0 if not failed else 1)
