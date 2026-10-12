# -*- mode: python ; coding: utf-8 -*-
import os
from pathlib import Path

# PROJECT_ROOT：优先环境变量；否则沿用历史硬编码路径（若存在）；再回退到 spec 所在目录。
_HARDCODED = Path(r"F:\RSNA\medical_imaging_workflow")
_SPEC_DIR = Path(globals().get("SPECPATH") or os.getcwd())  # PyInstaller 里 __file__ 未定义（实测踩坑）
PROJECT_ROOT = Path(
    os.environ.get("MIMW_PROJECT_ROOT")
    or (_HARDCODED if _HARDCODED.exists() else _SPEC_DIR)
)

# ── Helper: collect a directory tree including all files ──
def tree_datas(src_rel: str) -> list:
    full = PROJECT_ROOT / src_rel
    if not full.exists():
        return []
    out = []
    for root, dirs, files in os.walk(str(full)):
        rel = os.path.relpath(root, str(PROJECT_ROOT))
        dest = str(Path(rel).parent) if os.path.isfile(str(full)) else rel
        for f in files:
            if f.startswith(".") or f.startswith("~"):
                continue
            out.append((os.path.join(root, f), rel))
    return out


# ── Collect third-party hidden imports ──
hidden = [
    "_cffi_backend",
    "safetensors", "safetensors.torch",
    "pydicom", "pydicom.dataset",
    "easydict",
    "mpl_toolkits.mplot3d",
    # opencode embedding kernel
    "src.kernel.kernel_paths",
    "src.kernel.kernel_config",
    "src.kernel.kernel_client",
    "src.kernel.kernel_driver",
    "src.kernel.kernel_boot",
    "src.kernel.mcp_server",
    "src.kernel.tools._common",
    "src.kernel.tools.ui_bridge",
    "src.kernel.tools.domain_tools",
    "mcp.server.fastmcp",
    "mcp.server.mcpserver",
]

# ── Exclude unused heavy packages ──
excludes = [
    "tkinter", "PyQt5", "PySide2", "PySide6",
    "notebook", "jupyter", "jupyter_client", "ipython",
    "tensorflow", "tensorboard",
    "paddle", "paddleocr", "onnxruntime", "onnx",
    "bokeh", "plotly", "dash",
    "sphinx", "docutils",
    "devtools", "black", "isort", "pylint",
    "pytest",
    "Cython",
    "mypy",
    "pythoncom", "pywintypes", "win32com",
]

# ── opencode 内嵌：随包 agent/skill 资产 + 可选内核二进制 ──
# 内核 172MB，可用 MIMW_SKIP_KERNEL=1 排除（轻量包走后装/ runtime 查找）。
extra_datas = []
_kernel_assets = PROJECT_ROOT / "src" / "kernel" / "kernel_assets"
if _kernel_assets.exists():
    extra_datas.append((str(_kernel_assets), "kernel_assets"))
_opencode_dir = PROJECT_ROOT / "opencode"
if _opencode_dir.exists() and os.environ.get("MIMW_SKIP_KERNEL", "0") != "1":
    extra_datas.append((str(_opencode_dir), "opencode"))

block_cipher = None

a = Analysis(
    [str(PROJECT_ROOT / "main.py")],
    pathex=[str(PROJECT_ROOT)],
    binaries=[],
    datas=sum([
        tree_datas("config"),
        tree_datas("assets"),
        tree_datas("assets/ollama"),
        tree_datas("assets/models/deepseek_ocr"),
        tree_datas("assets/icon.ico"),
        tree_datas("assets/medlogo.png"),
        tree_datas("models/embedding"),
        tree_datas("models/sam"),
        tree_datas("poppler"),
        tree_datas("cocoindex"),
        tree_datas("segment-anything-main"),
        tree_datas("markitdown-main"),
        tree_datas("resources"),
    ], []) + extra_datas,
    hiddenimports=hidden,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=([str(PROJECT_ROOT / "build_scripts" / "runtime_hook.py")]
                  if (PROJECT_ROOT / "build_scripts" / "runtime_hook.py").is_file() else []),
    excludes=excludes,
    noarchive=True,
    optimize=0,
)

pyz = PYZ(a.pure, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="MedicalImagingWorkflow",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(PROJECT_ROOT / "assets/icon.ico"),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="MedicalImagingWorkflow",
)
