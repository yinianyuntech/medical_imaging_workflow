#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""[已废弃] 原四态点验脚本 —— 它会**骗人**，请改用 check_states_real.py。

保留这个文件是为了留下记录，不要再用它。

================================ 为什么废弃 ================================

它用 `w.setAttribute(Qt.WA_UnderMouse, True)` + `sendEvent(QEvent.Enter)` 来伪造悬停。
实测（`scripts/probe_state_bits.py`，在绘制时刻打印 `option.state`）：

    [button] bits=['Enabled', 'HasFocus', 'Active']  underMouse=True

`underMouse()` 确实变成了 True，但 Qt **不会**把 `State_MouseOver` 放进 `QStyleOption`
→ 引擎收到的 hovered 永远是 False → **所有悬停态都被测成"像素差 0"**，
看起来像"压根没实现悬停"，实际上只是测不出来。

更糟的是它会制造**假阴性可信度**：其它状态（按下/禁用/选中）它能测出来，
所以报告看起来"部分可信"，容易让人得出错误结论。

============================ 正确做法 ============================

`scripts/check_states_real.py` —— 用 Windows `SetCursorPos` 移动**真实光标**，
让操作系统派发 `WM_MOUSEMOVE`，走 Qt 真正的 enter/leave 机制；
按下态用真实的 `mouse_event(LEFTDOWN/LEFTUP)`。并且带三层自校验：

  1. `underMouse()` 必须为 True
  2. `WindowFromPoint` 必须命中的是**我们自己的窗口**（防止光标落在别的窗口上）
  3. 目标坐标必须在屏幕范围内

用法：
    python scripts/check_states_real.py --theme dark
    python scripts/check_states_real.py --theme light
"""

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

for _s in ("stdout", "stderr"):
    try:
        getattr(sys, _s).reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

print(__doc__)
print("=" * 70)
print("请改用：python scripts/check_states_real.py --theme dark|light")
print("=" * 70)
sys.exit(3)
