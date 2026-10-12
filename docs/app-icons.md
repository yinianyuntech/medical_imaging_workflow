# 应用图标系统（app_icons · 矢量 · 主题自适应）

> 目标：给"优先按钮和功能入口"统一加图标，**零外部资源**、深浅主题自动换色、
> 任意 DPI 都清晰；不改任何业务逻辑。

## 1. 一键验证

```powershell
python scripts/preview_icons.py        # 渲染 docs/screenshots/icons_dark.png / icons_light.png
python scripts/preview_skin.py         # 主窗口整幅（含图标）
```

图标总览（深色 52 枚 + 浅色 52 枚）见 `docs/screenshots/icons_{dark,light}.png`，
放大样张见 `icons_zoom.png`。

## 2. 设计

| 约束 | 实现 |
|---|---|
| 零资源依赖 | SVG 源码内联在 `src/utils/app_icons.py`，打包（PyInstaller）无需收集 assets |
| 主题自适应 | 渲染时按 `current_palette()` 取色；深色取亮描边、浅色取深描边 |
| 高 DPI | `QSvgRenderer` 渲染到物理像素，**画完再 `setDevicePixelRatio`**（先标记会错位——实测 close 图标画出 53..127 而非 26..101） |
| 统一视觉 | 24×24 viewBox / 2px 描边 / 圆头圆角；实心形状（play/stop 三角）单独 fill |
| 染色 | SVG 先画成白色，再 `CompositionMode_SourceIn` 整体染色 |

## 3. API

```python
from src.utils.app_icons import apply_icon, icon, icon_pixmap

apply_icon(btn, "play", role="text", size=16)   # 按钮：设置图标并登记热刷新
apply_icon(btn, "trash", role="on")             # 实色按钮上（白图标）
icon("database", role="chip", size=48)          # 任意取用 QIcon
label.setPixmap(icon_pixmap("database", "chip", 46))  # 大图标直接给 QLabel
```

**role 语义**（映射到当前主题实际颜色）：

| role | 用途 |
|---|---|
| `text`（默认） | 金属皮肤按钮（浅色背景取深字色，深色背景取亮字色） |
| `on` | 语义实色按钮上的白图标（绿=新建、红=删除、蓝/青=执行） |
| `accent` / `chip` | 强调/标牌（电光蓝、亮青） |
| `dim` / `muted` | 次级、空态占位 |

⚠️ **只给"会被保留的语义色按钮"用 `on`**：内联浅色/深灰样式会被
`strip_conflicting_stylesheets` 清掉、按钮回退成金属面，此时 `on`（白）在
浅色金属上对比度反而差（E2E 实测过 p7 Rethink/Validate）——这类按钮要么删内联样式
（用 `text`），要么把底色固定成语义白名单色（如 `#2E7D32`/`#00796B`/`#D91035`）。

## 4. 主题热切换

`MainWindow.apply_theme_live()` 里调用 `app_icons.refresh_all()`：
遍历注册表（weakref，死对象自动清理）重设全部图标；缓存随主题清空重建。
实测：一次刷新 **78** 个按钮/菜单图标，颜色随主题翻转
（dark→light 时 `plus` 中心像素 `#f2f7ff` → `#0a1524`）。

## 5. 覆盖范围（本轮）

| 位置 | 图标 |
|---|---|
| 菜单（下拉项） | 第一步~第五步、系统/帮助/视图/智能体的**全部动作** |
| 标题栏 | 徽标芯片（medcross，accent_hi） |
| p0 项目管理 | 新建/删除/刷新/添加根目录、样本管理卡片(database)、新建/删除样本、刷新、DICOM/文本/OCR 导航 |
| p1 DICOM ROI | 选文件/文件夹/清空、覆盖层、开始处理、刷新/清除历史、上/下一张、上/下一覆盖层、保存/导出 |
| p2 文本处理 | 选文件/文件夹/清空、开始分析、导出、刷新、清除历史、复制/保存内容、复制关键词 |
| p3 OCR | 选文件/文件夹/清空、开始OCR、刷新、清除历史、复制/保存文本、保存标注图 |
| p4 MagicSeg | Open Folder / Prev / Next / Clear / Save ROI |
| p5 数据清洗 | Custom API(plug)、AI 挖掘(sparkles)、导出目录、刷新项目列表、上一页/下一页 |
| p6 大模型总结 | 刷新模型、Custom API、删除、提示词修改、开始分析(play)、同步/重建KB、Template Wizard |
| p7 预览生成 | Rethink(sparkles)、Template(wand)、Validate(check)、Proceed(arrow)、搜索/从磁盘打开 |
| p8 反馈优化 | View Details、Submit、Generate PPT、**空态占位（图表图标+引导文案）** |
| 对话框 | 首启向导、样本管理、新建项目、Template Wizard、Prompt Editor、Refine、授权激活 |
| 底部智能体栏 | 展开/收起(chevron)、启动内核(play)、停止(stop)、发送(send) |

## 6. 两个必须记住的 Qt 坑（实测）

### 6.1 菜单栏一级菜单**不能加图标**（QCommonStyle 丢文字）

Qt 的 `QCommonStyle` 对"带图标的菜单栏项"**只绘制图标、完全不测文字宽度**——
实测同一 QSS 下：纯文字项宽 **98px**，加图标后坍缩到 **42px**（= 图标 16 + 内边距），
一级菜单变成一排无字图标。

> 修复：一级菜单保持纯文字；**导航图标全部放在下拉菜单项**
> （`QMenu::item` 会同时画图标+文字，实测正常）。
> 曾误把图标挂到 `menuBar().addMenu().menuAction()` 上 → 菜单栏文字消失，
> 排查过程：`mb.actionGeometry(action).width()` 42 vs 98。

### 6.2 QAction 注册热刷新必须**强引用**

C++ 侧创建的 QAction（如 `QMenu.menuAction()`、QSS 菜单里的内建动作），
其 Python 包装器一旦无引用即被回收——`weakref` 立刻死亡，
`refresh_all()` 静默跳过 → 换主题后图标仍是旧描边色（浅色下"洗白"不可见）。

> 实测：8 个菜单 action 的 weakref 全部失效（87 注册 / 79 刷新）。
> 修复：`apply_icon` 对**控件**用 weakref（不泄漏），对**QAction**存强引用。

## 7. 回归验证（全部通过）

```powershell
python scripts/check_occlusion.py        # RESULT: PASS（无遮挡/挤压/溢出/塌陷）
python scripts/audit_visual_defects.py   # exit 0（无控件溢出、引擎不手绘文字）
python scripts/test_dialog_flows.py      # 9/9 对话框路径
python scripts/check_menus_and_pages.py  # 菜单弹窗 8/8 可见；导航 5/5 成功切页
```

主题热切换专项：下拉菜单图标颜色随主题翻转（dark `#f1f6ff` → light `#081322`），
菜单栏文字恢复显示（浅色下深字 `#35445A` 描边，对比度通过）。
