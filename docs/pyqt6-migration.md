# PyQt5 → PyQt6 框架迁移说明（第一步）

> 目标：**换框架、不动布局、不改业务代码**。已完成并实测通过。

## 方案：兼容层而非重写

源码里 PyQt5 风格的无作用域枚举（`Qt.AlignCenter`、`QMessageBox.Yes`）在 PyQt6 中
被强制作用域化（`Qt.AlignmentFlag.AlignCenter`、`QMessageBox.StandardButton.Yes`）。
全量改写调用点约 **430 处 + 103 处 import**，风险高且会污染业务代码。

因此引入单一兼容层 `src/core/qt_compat/`，把旧写法在**运行时还原**：

| 文件 | 作用 |
|---|---|
| `_enum.py` | `enum_index()` 收集类的全部嵌套枚举成员；`compat_class()` 用 `type()` 生成子类并挂枚举成员；`NamespaceProxy` 让 `Qt` 命名空间回落枚举 |
| `QtCore.py` | `PyQt6.QtCore` + `Qt` 代理 + `QEvent` 兼容子类 |
| `QtGui.py` | `PyQt6.QtGui` + `QPalette/QFont/QImage/QPainter/QTextCursor` 兼容子类 |
| `QtWidgets.py` | `PyQt6.QtWidgets` + 20 个控件兼容子类 + `QAction/QShortcut` 回填 + `QDesktopWidget` shim |

**源码改动只有 3 类**：

1. **91 行 import 重定向**（脚本化，零人工）
   `from PyQt5.QtWidgets import ...` → `from src.core.qt_compat.QtWidgets import ...`
2. **5 处 Qt6 移除 API**（`ui/widgets/main_window.py`）
   - `event.globalPos()` → `event.globalPosition().toPoint()`（×4）
   - `event.pos().y()` → `event.position().y()`（×1）
3. **1 处 Qt6 不兼容写法**（`src/core/event_bus.py`）
   - 移除 `EventBus.__new__` 单例：PyQt6/sip 下对 QObject 子类覆写 `__new__` 并调用
     `super().__new__()` 会导致 sip 重入 → **栈溢出 0xC00000FD**。单例改由既有的
     模块级 `get_event_bus()` 承担（该函数本就缓存实例）。

另有 2 处绑定相关项：
- `src/utils/theme_manager.py`：`qdarkstyle.load_stylesheet(qt_api="pyqt5" → "pyqt6")`
- `main.py` / `license_manage/main.py` 的 `Qt.AA_EnableHighDpiScaling` 等：`hasattr` 守卫
  在 PyQt6 下自动为 False **并正确跳过**（Qt6 高 DPI 恒开）

## 验证

| 检查 | 结果 |
|---|---|
| `scripts/test_qt_compat.py` | **61 / 61 PASS**（枚举 / **exec_ 绑定与真实调用** / QDesktopWidget / isinstance） |
| `scripts/test_dialog_flows.py` | **9 / 9 PASS**（新建项目 / 首启向导 / 授权 / 提示词 / 模板向导 / 自定义API / QMessageBox） |
| `scripts/verify_qt_migration.py --import` | **PASS**（无遗留 PyQt5；182 文件编译；关键模块可导入） |
| `scripts/smoke_gui_pyqt6.py` | **5 / 5 PASS**（完整构建 MainWindow：9 页 + opencode 面板 + 导航） |
| 运行时绑定确认 | `PyQt5 in sys.modules → False`；`PyQt6.QtWidgets → True` |
| GUI 实机启动（rsna311） | `boot:opencode_attached`，无错误 |

## `exec_` 绑定缺陷（已修，影响全工程 29 处对话框）

**现象**：新建项目报 `exec(self): first argument of unbound method must have type 'QDialog'`。
实际影响面远不止新建项目 —— 首启向导、授权对话框、以及**所有 `QMessageBox` 确认框**全部打不开。

**根因**（`src/core/qt_compat/_enum.py` 的 `_exec_alias`）：

```python
return {"exec_": getattr(real_cls, "exec")}      # ✗ 错的
```

PyQt6 里**类级访问** `cls.exec` 返回的是 `builtin_function_or_method`，它有两个陷阱：

| 事实 | 实测值 |
|---|---|
| 它**已经绑定到类**（不是未绑定函数） | `__self__ = <class 'PyQt6.QtWidgets.QDialog'>` |
| 它**不是描述符** | `type(obj).__get__` 不存在 |

把它塞进子类命名空间后，`dialog.exec_()` 不会重新绑定实例，而是直接拿**类**当 self
调用底层方法 → sip 认为 self 类型不对 → 报错。

真正的描述符藏在 `cls.__dict__["exec"]`（实测 `type=methoddescriptor`）。

**修法**：沿 MRO 找 `__dict__["exec"]` 取那个描述符：

```python
for klass in real_cls.__mro__:
    raw = klass.__dict__.get("exec")
    if raw is not None:
        return {"exec_": raw}
```

这样普通方法在实例级访问时**自动绑定**，而 `QApplication.exec` 这类**静态方法**
（`staticmethod` 对象不绑定）语义也天然正确 —— 一条代码覆盖两种情形。

### 为什么 58 条测试全绿却没抓到

原来的两条测试**只断言属性存在，从不调用**：

```python
chk("QApplication.exec_ alias", lambda: app.exec_)      # 取一下属性就算过
chk("QDialog instance .exec_", lambda: dlg.exec_)       # 同上
```

属性确实存在、取值也不报错 —— 但**"属性存在"不等于"能正确调用"**。
现在改成验证绑定 + **真实调用**（用 `QTimer` 自动关掉对话框，进/出模态循环各来一次）：

```python
# 实例级必须绑定到实例（而不是绑定到类！）
owner = getattr(inst.exec_, "__self__", None)
if owner is not inst: 失败

# 真的跑一遍模态循环
d = _D(); QTimer.singleShot(0, d.reject); d.exec_()
```

教训：涉及**描述符/绑定**的兼容层改动，必须用"真实调用"验证，不能只查属性。

## 附带发现（既存问题，非本次引入）

`src/api/routes/ocr_routes.py:74-76` 存在孤儿代码导致 `IndentationError`
（`git status` 显示未被本次改动触及）。该文件属于可选 Flask API，`main.py`
已通过 `_disable_fastapi_runtime()` 禁用该通道，故不影响运行。

## 工具脚本

```powershell
python scripts/migrate_pyqt5_to_qt_compat.py          # 干跑（默认）
python scripts/migrate_pyqt5_to_qt_compat.py --apply  # 执行迁移
python scripts/verify_qt_migration.py --import        # 校验
python scripts/test_qt_compat.py                      # 兼容层单测（含 exec_ 绑定/真实调用）
python scripts/test_dialog_flows.py                   # 所有对话框 exec_ 端到端验证
python scripts/smoke_gui_pyqt6.py                     # GUI 全量构建冒烟
python scripts/probe_exec_binding.py                  # 方法绑定行为取证（排查同类问题用）
```

## 下一步（第二步，未开始）

光影拟物化全局风格：统一 QSS（渐变/内阴影/圆角/描边）+ `QGraphicsDropShadowEffect`
分层投影 + 明暗双主题，保持现有布局不变。
