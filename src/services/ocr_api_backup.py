#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""OCR 的 **API 备份引擎**（step 1 的兜底通道）。

════════════════════════════════════════════════════════════════════════
为什么需要
════════════════════════════════════════════════════════════════════════

本地 DeepSeek-OCR 需要 GPU + 权重文件；首次加载慢、显存不足、模型缺失、
Ollama 未启动等任一环节出问题，整条 OCR 就完全没有产出。这时用 API 兜底，
至少能拿到文本，而不是"什么都没识别出来"。

════════════════════════════════════════════════════════════════════════
⚠️ 关于"用 DeepSeek API 做 OCR"——必须讲清的事实
════════════════════════════════════════════════════════════════════════

`api.deepseek.com` 目前只提供**文本**模型（`deepseek-chat` / `deepseek-reasoner`），
**不接受图像输入**。所以"用 DeepSeek API 做 OCR"在严格意义上不成立 ——
OCR 必须有 **VL（视觉）端点**。

本模块因此实现为「**可配置的 OpenAI 兼容 VL 端点**」：

* 默认 `base_url` 就指向 DeepSeek（`https://api.deepseek.com/v1`），
  满足"用 deepseek api 作为备份"的诉求；
* 但 `base_url` / `model` 均可配置 —— 指向任何兼容 VL 的网关即可真正工作
  （自建 vLLM + DeepSeek-VL2、第三方聚合网关、或日后 DeepSeek 开放 VL 时）；
* **不做静默降级**：调用失败时把 provider 的原话（含 HTTP 状态与 message）
  一并返回，让用户知道到底卡在哪。

配置优先级（高 → 低）：
    1. 调用时传入的 `config`（`ocr_api_base_url` / `ocr_api_key` / `ocr_api_model`）
    2. 环境变量 `MIMW_OCR_API_BASE_URL` / `MIMW_OCR_API_KEY` / `MIMW_OCR_API_MODEL`
    3. 环境变量 `RSNA_JUDGE_BASE_URL` / `RSNA_JUDGE_API_KEY`（复用既有约定）
    4. 宿主 `config/custom_api_profiles.json` 里第一个含 key 的 profile
    5. 内核隔离 home 的 `auth.json`（若用户已为 opencode 导入过 deepseek key）
"""

from __future__ import annotations

import base64
import io
import json
import os
import time
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

# 默认指向 DeepSeek（按需求"用 deepseek api"）。
# ⚠️ 该默认模型名是**VL 命名**：api.deepseek.com 当前不提供，调用会返回 provider 的
#    明确报错（不静默）。要真正可用，请把 base_url/model 指向 VL 端点。
DEFAULT_BASE_URL = "https://api.deepseek.com/v1"
DEFAULT_MODEL = "deepseek-vl2"

DEFAULT_PROMPT = (
    "请对这张图片做 OCR：逐行输出图中的全部文字，保持原有阅读顺序与换行。"
    "如果是表格，用制表符分隔列。不要翻译、不要总结、不要添加任何解释。"
)

# 长边超过该值就等比缩小（控制 base64 体积，避免超出 provider 的请求上限）
MAX_SIDE = 2000
JPEG_QUALITY = 88


def _logger():
    try:
        from src.utils.logger import get_logger
        return get_logger(__name__)
    except Exception:  # pragma: no cover
        import logging
        return logging.getLogger(__name__)


class APIVisionOCR:
    """OpenAI 兼容 VL 端点的 OCR 客户端。"""

    def __init__(self, config: Optional[Dict[str, Any]] = None,
                 logger: Any = None):
        self.logger = logger or _logger()
        self.config = dict(config or {})
        self.base_url, self.api_key, self.model, self.source = self._resolve()

    # ---------------------------------------------------------------- 配置
    @staticmethod
    def _first_key(d: Any, names) -> str:
        if not isinstance(d, dict):
            return ""
        for n in names:
            v = d.get(n)
            if isinstance(v, str) and v.strip():
                return v.strip()
        return ""

    def _resolve(self) -> Tuple[str, str, str, str]:
        """返回 (base_url, api_key, model, 来源说明)。"""
        cfg = self.config
        base = str(cfg.get("ocr_api_base_url") or "").strip()
        key = str(cfg.get("ocr_api_key") or "").strip()
        model = str(cfg.get("ocr_api_model") or "").strip()
        if base or key:
            return (base or DEFAULT_BASE_URL, key, model or DEFAULT_MODEL,
                    "explicit_config")

        base = os.environ.get("MIMW_OCR_API_BASE_URL", "").strip()
        key = os.environ.get("MIMW_OCR_API_KEY", "").strip()
        model = os.environ.get("MIMW_OCR_API_MODEL", "").strip()
        if base or key:
            return (base or DEFAULT_BASE_URL, key, model or DEFAULT_MODEL,
                    "env:MIMW_OCR_API_*")

        base = os.environ.get("RSNA_JUDGE_BASE_URL", "").strip()
        key = os.environ.get("RSNA_JUDGE_API_KEY", "").strip()
        if base or key:
            return (base or DEFAULT_BASE_URL, key, model or DEFAULT_MODEL,
                    "env:RSNA_JUDGE_*")

        host = self._host_profile()
        if host:
            b, k, m = host
            return (b or DEFAULT_BASE_URL, k, m or model or DEFAULT_MODEL,
                    "host:custom_api_profiles.json")

        kern = self._kernel_auth_key()
        if kern:
            return (base or DEFAULT_BASE_URL, kern, model or DEFAULT_MODEL,
                    "kernel:auth.json(deepseek)")

        return (base or DEFAULT_BASE_URL, "", model or DEFAULT_MODEL, "none")

    @staticmethod
    def _host_profile():
        """读宿主 config/custom_api_profiles.json 里第一个带 key 的 profile。"""
        try:
            import sys
            root = Path(getattr(sys, "_MEIPASS", "")) if getattr(sys, "frozen", False) \
                else Path(__file__).resolve().parents[2]
            p = Path(root) / "config" / "custom_api_profiles.json"
            if not p.exists():
                return None
            data = json.loads(p.read_text(encoding="utf-8"))
            profs = data.get("profiles") if isinstance(data, dict) else data
            if isinstance(profs, dict):
                profs = list(profs.values())
            if not isinstance(profs, list):
                return None
            for pr in profs:
                if not isinstance(pr, dict):
                    continue
                k = APIVisionOCR._first_key(pr, ("api_key", "key", "token",
                                                 "apikey", "apiKey"))
                if not k:
                    continue
                b = APIVisionOCR._first_key(pr, ("base_url", "url", "api_base",
                                                 "endpoint", "baseUrl"))
                m = APIVisionOCR._first_key(pr, ("model", "model_id", "modelId",
                                                 "vision_model"))
                return (b, k, m)
        except Exception:
            return None
        return None

    @staticmethod
    def _kernel_auth_key() -> str:
        """读内核隔离 home 的 auth.json（用户为 opencode 导入过 key 时可直接复用）。"""
        try:
            from src.kernel import kernel_config as kc
            auth = kc.read_auth() or {}
            for name in ("deepseek", "openai", "siliconflow", "moonshot"):
                v = auth.get(name)
                if isinstance(v, dict):
                    k = str(v.get("key") or "").strip()
                    if k:
                        return k
        except Exception:
            pass
        return ""

    # ---------------------------------------------------------------- 状态
    def available(self) -> Tuple[bool, str]:
        """(是否可用, 原因)。"可用"= 有 key；端点能力由 provider 自己回答。"""
        if not self.api_key:
            return (False,
                    "未配置 OCR API key（可设 MIMW_OCR_API_KEY，"
                    "或在 config/custom_api_profiles.json 里配 profile，"
                    "或用 kernel_cli import-key 为内核导入 key）")
        if not self.base_url:
            return (False, "未配置 base_url")
        return (True, f"{self.source} model={self.model}")

    def summary(self) -> Dict[str, Any]:
        return {
            "available": bool(self.api_key),
            "source": self.source,
            "base_url": self.base_url,
            "model": self.model,
            "key_len": len(self.api_key),
        }

    # ---------------------------------------------------------------- 图像编码
    @staticmethod
    def encode_image(image_path: str, max_side: int = MAX_SIDE) -> Dict[str, Any]:
        """把图片缩放并编码为 data URL。返回 {ok, data_url, size, error}。"""
        try:
            from PIL import Image
            img = Image.open(str(image_path))
            if img.mode not in ("RGB", "L"):
                img = img.convert("RGB")
            elif img.mode == "L":
                img = img.convert("RGB")
            w, h = img.size
            scale = 1.0
            if max(w, h) > max_side:
                scale = float(max_side) / float(max(w, h))
                img = img.resize((max(1, int(w * scale)), max(1, int(h * scale))),
                                 Image.LANCZOS)
            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=JPEG_QUALITY, optimize=True)
            raw = buf.getvalue()
            b64 = base64.b64encode(raw).decode("ascii")
            return {
                "ok": True,
                "data_url": f"data:image/jpeg;base64,{b64}",
                "bytes": len(raw),
                "orig_size": (w, h),
                "sent_size": img.size,
                "scale": round(scale, 4),
            }
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "error": f"{type(e).__name__}: {e}"}

    # ---------------------------------------------------------------- 调用
    def recognize(self, image_path: str, config: Optional[Dict[str, Any]] = None,
                  prompt: str = "", max_tokens: int = 4096,
                  timeout_s: float = 180.0) -> Dict[str, Any]:
        """对单张图做 OCR。返回统一结构（**失败也带 provider 原话**）。"""
        cfg = dict(self.config)
        cfg.update(config or {})
        t0 = time.time()

        enc = self.encode_image(image_path,
                                int(cfg.get("ocr_api_max_side") or MAX_SIDE))
        if not enc.get("ok"):
            return {"success": False, "text": "", "engine": "api_vision",
                    "error": f"encode_failed:{enc.get('error')}",
                    "elapsed_s": round(time.time() - t0, 2)}

        ok, why = self.available()
        if not ok:
            return {"success": False, "text": "", "engine": "api_vision",
                    "error": f"unavailable:{why}",
                    "elapsed_s": round(time.time() - t0, 2)}

        try:
            from src.services.llm_judgement_client import LLMJudgementClient
            client = LLMJudgementClient(base_url=self.base_url,
                                        api_key=self.api_key,
                                        timeout_s=float(timeout_s))
        except Exception as e:  # noqa: BLE001
            return {"success": False, "text": "", "engine": "api_vision",
                    "error": f"client_init_failed:{type(e).__name__}: {e}",
                    "elapsed_s": round(time.time() - t0, 2)}

        messages = [{
            "role": "user",
            "content": [
                {"type": "text", "text": (prompt or DEFAULT_PROMPT)},
                {"type": "image_url",
                 "image_url": {"url": enc["data_url"], "detail": "high"}},
            ],
        }]
        res = client.chat_completions(self.model, messages,
                                      temperature=0.0, max_tokens=int(max_tokens))
        dt = round(time.time() - t0, 2)

        if not res.get("success"):
            err = str(res.get("error") or "unknown")
            msg = str(res.get("message") or "")[:600]
            self.logger.warning(f"OCR API 备份失败: {err} {msg[:160]}")
            return {"success": False, "text": "", "engine": "api_vision",
                    "model": self.model, "base_url": self.base_url,
                    "error": f"{err}: {msg}" if msg else err,
                    "http_error": err, "provider_message": msg,
                    "elapsed_s": dt, "image": {"bytes": enc["bytes"],
                                               "sent_size": enc["sent_size"]}}

        # ⚠️ `LLMJudgementClient.chat_completions` 成功时返回的是
        #     {"success": True, "content": <文本>, "raw": <原始 json>}
        #    —— **不是**原始 OpenAI 结构。按 `data.choices[0]...` 去取会取空，
        #    表现为"API 调用了、也 200 了，但文本是空的"。
        #    （实测：本地 stub 回归里正是这样暴露出来的。）
        text = str(res.get("content") or "").strip()
        if not text:
            try:
                choices = ((res.get("raw") or {}).get("choices") or [])
                if choices:
                    text = str((choices[0].get("message") or {})
                               .get("content") or "").strip()
            except Exception:
                text = ""
        usage = {}
        try:
            usage = (res.get("raw") or {}).get("usage") or {}
        except Exception:
            usage = {}
        return {
            "success": bool(text),
            "text": text,
            "engine": "api_vision",
            "model": self.model,
            "base_url": self.base_url,
            "usage": usage,
            "elapsed_s": dt,
            "image": {"bytes": enc["bytes"], "sent_size": enc["sent_size"]},
            "error": "" if text else "empty_response",
        }


# ---------------------------------------------------------------- 便捷入口
_CACHE: Dict[str, APIVisionOCR] = {}


def get_backup(config: Optional[Dict[str, Any]] = None,
               logger: Any = None) -> APIVisionOCR:
    """按配置缓存实例（同一套配置复用连接池）。"""
    key = json.dumps({
        "b": (config or {}).get("ocr_api_base_url"),
        "k": bool((config or {}).get("ocr_api_key")),
        "m": (config or {}).get("ocr_api_model"),
    }, sort_keys=True)
    inst = _CACHE.get(key)
    if inst is None:
        inst = APIVisionOCR(config, logger=logger)
        _CACHE[key] = inst
    return inst
