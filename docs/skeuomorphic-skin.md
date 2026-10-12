# 光影拟物化皮肤（冷色蓝金属 · 科技风）

> 全局外观层。**不改任何布局与业务逻辑**；通过 `MIMW_SKIN` 一键开关。

## 1. 总开关

| 环境变量 | 作用 | 默认 |
|---|---|---|
| `MIMW_SKIN` | `metal`（启用）/ `off`（回退原浅色样式） | `metal` |
| `MIMW_SKIN_SHADOW` | `1`/`0`，是否启用 `QGraphicsDropShadowEffect` | `1` |

代码入口：`src/utils/skeuomorphic.py` → `apply_global(app)`（在 `main.py` 里
`ThemeManager.apply_theme()` **之后**调用，作为最后一道全局样式）。

## 2. 配色令牌（冷色蓝金属）

`MetalPalette` 色阶 `s900`（最深）→ `s200`（最亮），外加语义色：

| 令牌 | 深色（默认） | 说明 |
|---|---|---|
| `s900` / `s800` | `#04070E` / `#070D18` | 背光面 / 基板 |
| `s600` / `s500` / `s400` | `#112036` / `#182F4E` / `#1F3A5F` | 面板 / 受光面 / 高光面 |
| `accent` / `accent_hi` | `#1E90FF` / `#5CC8FF` | 电光蓝 / 高光青 |
| `edge_hi` / `edge_soft` | 蓝白半透明 | 面板顶部/左侧棱线（科技感关键） |
| `chip_text` | `#A8E0FF` | 标牌标题亮青 |

浅色主题（`LIGHT_ALU`）为同一色系的**阳极氧化铝**版本。

## 3. 三维绘制引擎（真立体，非渐变）

QSS **画不出**真正的立体：它没有 box-shadow / inset / 多层叠加 / 镜面高光。
所以立体观感由 `src/utils/skeuo_style.py` 的 **`QProxyStyle`** 用 QPainter 手绘，
在控件自身矩形内完成，因此 **零布局影响**（不需要 `border-width`，不动 padding）。

覆盖的 primitive：

| primitive / control | 接管对象 | 画法 |
|---|---|---|
| `PE_PanelButtonCommand` | QPushButton | 投射阴影 → 挤出侧面 → 受光面渐变 → 贴顶镜面高光 → 倒角棱线 |
| `PE_PanelLineEdit` / `PE_FrameLineEdit` | QLineEdit 等 | 井底渐变 → 顶部内阴影 → **下唇反光** → 顶暗底亮棱线 |
| `PE_FrameGroupBox` | QGroupBox | 投影 → 受光面 → 顶部内高光 → 底部内阴影 → 上亮下暗棱线 |
| `PE_IndicatorCheckBox` | QCheckBox | 内凹井 → 立体勾（暗描边 + 亮勾，嵌入感） |
| `PE_IndicatorRadioButton` | QRadioButton | 圆形内凹井 → 立体圆点 + 高光弧 |
| `CE_HeaderSection` | 表格表头 | 薄金属板（不画投影，避免相邻单元格互相压盖） |
| `CE_TabBarTabShape` | 标签页卡舌 | 选中抬起 + 顶部电光蓝；未选中下沉 |
| `CC_ComboBox` | 下拉框 | 凸起主体 + 立体箭头钮 + 自绘省略文本 |
| `CC_ScrollBar` | 滚动条 | 内凹槽 + 立体滑块 |
| `CC_Slider` | 滑块 | 内凹槽 + 电光蓝填充 + 立体圆钮（含镜面高光） |

**验证接管是否真的生效**：`SkeuomorphicStyle.hits` 计数器 + `scripts/probe_style_dispatch.py`。
实测：`button:4 well:4 groupbox:4 combo:4 scroll:8 slider:4 header:24 tab:12 checkbox:4 radio:4`。

> ⚠️ 陷阱：只要 QSS 给某控件保留了**背景/边框**（含 `::tab`、`::section`、`::indicator` 子控件规则），
> QStyleSheetStyle 就会接管绘制，引擎不再被调用 —— 必须删干净。
> 只设 `color` / `font-weight` / `width`/`height` 则**不会**阻断（已实测）。

倒角用 **"上下半区裁剪 + 整路径描边"**（`_stroke_bevel`）。
> ⚠️ 不要用 `drawArc` 画棱线：它画的是**整椭圆弧**，在宽扁控件上会渲染成巨大弧线
> （曾导致按钮变成"透镜形"）。

颗粒材质通过 `_overlay_texture()` 以 **纹理笔刷** 叠在渐变之上，保留磨砂质感。

> ⚠️ 一旦 QSS 给这些控件设置了 **背景/边框**，QStyleSheetStyle 就会接管绘制，
> 引擎不再被调用。所以 QSS 里只保留排版属性（padding/字体/颜色）。
> 实测：仅设置 `color` / `font-weight` **不会**阻断引擎（`groupbox` 命中计数不变）。

## 4. 字体与对比度

### 5.1 字体栈（实测决定，不是拍脑袋）

探测本机字体库发现：**没有 `Microsoft YaHei`**（所有 `font-family:'Microsoft YaHei'` 一直在走 Qt 替换）。
可用且更优的选择：

| 用途 | 字体 | 理由 |
|---|---|---|
| UI 正文 | **`Source Han Sans CN`（思源黑体）** | 本机可用，**7 字重**（ExtraLight/Light/Regular/Medium/Bold/Heavy）→ 能做出真正的排版层级 |
| 标题/西文 | **`Bahnschrift`** | DIN 风、科技感强；中文自动回落到思源黑体 |
| 数据/等宽 | **`Cascadia Mono`** | 科技感等宽，适合数值读数 |

回退链保留 `Microsoft YaHei UI / Microsoft YaHei / SimHei / Segoe UI`，换机器不塌。

### 5.2 排版层级

| 层级 | 字号 | 字重 |
|---|---|---|
| 标题栏 | 18pt | **800**（Heavy）+ 字距 0.9 |
| 分组标题 / 按钮 / 菜单 | 13pt | 700 / 600 / 600 |
| 正文 | 13pt（原 12pt） | 400 |
| 辅助 / 状态栏 | 12pt | 400 |

> ⚠️ Qt 的 QSS **不支持 `letter-spacing`** —— 字距必须走 `QFont.setLetterSpacing()`。
> 因此标题栏 QSS 只设 `color`，字体全交给 `ui_font()`。

### 5.3 数据字体（等宽 = 仪表感）

**表格 / 列表 / 数值输入**整体切等宽：

```css
QTableView, QTreeView, QListWidget, QTableWidget, QTreeWidget {
    font-family: 'Cascadia Mono','Consolas','Source Han Sans CN',...;
}
QSpinBox, QDoubleSpinBox { font-family: <同上>; font-weight: 600; }
```

> **关键**：Cascadia Mono **没有 CJK 字形**，所以字体栈必须把**思源黑体放在回退位** ——
> 这样同一个控件里「数字/西文走等宽、中文自动回落黑体」各取所需，无需逐单元格设置。
> 实测：9 个表格/列表控件的 `font().family()` 全部为 `Cascadia Mono`。

**数值型标签**由 `apply_data_font()` 自动识别并切换：

| 判据 | 命中示例 |
|---|---|
| `\d+\.\d+`（小数） | `置信度: 0.82`、`面积 12.4`、`IoU = 0.91`、`版本 1.0` |
| `\d{2,}`（≥2 位数字） | `样本 24 个` |

自检 10/10：数值标签 → `Cascadia Mono`；纯文字标签（含 `第 2 步` 这种单个数字）→ `Source Han Sans CN`，**不误伤**。

效果：表格里 `12.4 / 13.4 / 14.4 / 15.4` 与 `0.81 / 0.84 / 0.87 / 0.90` 的**小数点垂直对齐**。

### 5.4 对比度

| 令牌 | 旧 | 新 | 说明 |
|---|---|---|---|
| `text` | `#D8E6FA` | **`#F2F7FF`** | 正文近白 |
| `text_dim` | `#8296B5` | **`#B3C6E0`** | 辅助文字提亮 |
| `text_strong` | — | `#FFFFFF` | 表头/悬停强调 |

**玻璃必须用暗色半透明**：早期版本玻璃是"半透明白"，多层叠加后越来越亮，
而下拉框里是近白文字 → **白字压浅底**。改为 `rgba(30,58,104,0.62)` → `rgba(10,22,44,0.70)`
（深色应用上的磨砂玻璃 = **暗面 + 亮边**），实测下拉框中心像素 `#142645`（暗），对比恢复。

### 5.5 字号放大的副作用与自动补偿

正文 12pt → 13pt 后，R7 立刻抓到 **3 处文字被裁**（固定高度的标签装不下）。

新增 `ensure_text_fits(root)`：对**多行/自动换行**标签**无条件**设最小高度到所需值，
父容器随之自然撑开。实测 `fixed: 13`，裁字归零。

> ⚠️ 不能在 `init_ui` 阶段用 `w.height()` 判断 —— 那时**布局还没算**，会漏判。
> 多行标签必须无条件设最小高度。

副作用红利：主窗口最小尺寸从 `1213x204` **降到 `760x201`**（更适配小屏）。

## 5. 浅色主题与热切换

### 10.1 浅色主题（冷色白玻璃）

| 令牌 | 深色 | 浅色 |
|---|---|---|
| `glass_hi` / `glass_lo` | `rgba(30,58,104,0.62)` / `rgba(10,22,44,0.70)` | `rgba(255,255,255,0.86)` / `rgba(226,238,252,0.62)` |
| `glass_rim` / `glass_edge` | 冷蓝白 / 深蓝 | `rgba(255,255,255,1.0)` / `rgba(130,158,196,0.55)` |
| `text` / `text_dim` | `#F2F7FF` / `#B3C6E0` | `#0A1524` / `#4A5B75` |
| `bg_glow` | `rgba(40,120,230,0.22)` | `rgba(150,205,255,0.55)` |

**倒角棱线随主题换色**（`_stroke_bevel(..., dark=)`）：深色用冷蓝白 + 近黑；
浅色用纯白高光 + 蓝灰投影（否则浅色下倒角糊成一片）。

### 10.2 热切换（无需重启）

`MainWindow.toggle_theme()` → `MainWindow.apply_theme_live(theme)`，顺序：

```
1) ThemeManager.apply_theme(app, theme)          铺底（qdarkstyle / palette）
2) skeuo_style.reset_texture_cache()             ★ 清颗粒贴图缓存（按主题分文件）
3) skeuomorphic.apply_global(app)                皮肤主样式表（重建材质 + 新 QSS）
4) skeuo_style.install(app)                      确保 3D 引擎在位
5) strip / apply_data_font / ensure_text_fits    重刷主题相关内联样式（均幂等）
6) 遍历 app.allWidgets() 调 refresh_theme()      控件级刷新协议（可选实现）
7) self.apply_styles()                           主窗口壳层 + 标题文字色
8) self._repolish_all()                          全树 unpolish→polish→update
```

**实测**：同进程切浅色，整窗平均亮度 **20.7 → 179.6（+159.0）**，深色主色 `#000018` 完全消失。

### 10.3 为热切做的三处修正

1. **`_TEX_CACHE` 缓存键加主题名**（原按 `kind` 缓存 → 切主题后颗粒不跟着变）
2. **`current_palette()` 支持 `MIMW_THEME=light|dark`**，并**同步 `ThemeManager._current_theme`**
   —— 否则会出现"调色板已切、但控件仍按旧主题分支取色"的错配（R9 实测踩到 `#3E3E3E`）
3. **冲突色名单补齐两个主题的写死色**：
   - 补 3 位简写 `#888/#777/#999/#aaa/#bbb/#ccc`（原来只有 6 位形式，实测漏掉 `color:#888`）
   - 补**深色主题专属紫** `#E879F9/#F5D0FE/#D8B4FE/#E9D5FF` 与灰阶 `#2D2D30/#3E3E42/...`

### 10.4 顺带修掉的两个真实缺陷

| 问题 | 根因 | 修复 |
|---|---|---|
| **功能模块按钮 150px 被压成 30px**，图标+文字被裁 | QSS 的 `padding` 让 Qt 用「`min-height` + 垂直 padding」重算最小高度，**覆盖了 `setFixedSize(300,150)`** | 移除全局 `QPushButton` 的 `min-height` → 恢复 `300x150` |
| 语义色按钮渲染成**浅灰底白字** | 部分控件样式表是**裸声明列表**（无 `QPushButton {}` 包裹），父级合成时解析不可靠 | 统一包一层 `QPushButton { ... }` + 追加 `background-image: none` |

### 10.5 已知待办（诚实记录）

浅色主题下 R9 仍报 **3 处低对比**。但我用**同一套坐标**导出的裁剪图人工核对：

- `开始科学分析 (RAG)`：实际渲染为**深蓝字压浅玻璃**，可读性良好 → **检测器误报**
  （该按钮 `styleSheet()` 为空；控件独立 grab 的中心像素为 `#0A156C`，深色）

**结论**：R9 在**小尺寸按钮**上存在误报（疑与父级合成像素采样有关），属**工具侧待办**，
不是界面上真实的低对比问题。

## 6. 主题刷新协议与 R9 收敛

### 6.1 `refresh_theme()` 协议

`apply_theme_live()` 第 6 步会遍历 `app.allWidgets()`，对实现了 `refresh_theme()` 的控件调用。

已实现：

| 类 | 覆盖内容 |
|---|---|
| `DraftCard` | 卡片底/边框/悬停、时间文字、摘要文字、人工补充徽标、模型徽标 |
| `FeedbackOptimizationWidget` | 仪表盘底色、统计文字、标题、过滤标签，并**级联刷新所有卡片** |

做法：把原来写在 `__init__` 里的三元表达式抽成 `theme_colors()`（纯函数），
再用幂等的 `_apply_theme()` 统一套用 —— `__init__` 与 `refresh_theme()` 共用同一份逻辑。

**实测（往返验证）**：

| | 深色构造 | 热切浅色 | 切回深色 |
|---|---|---|---|
| `DraftCard` 背景 | `#333333` | `#FFFFFF` | `#333333` |
| 时间文字 | `#D8B4FE` | 置空→交给皮肤 | `#D8B4FE` |
| 人工补充徽标 | `#5B3A00` | `#FFF2CC` | `#5B3A00` |
| 仪表盘底 | `#3E3E3E` | `#f0f0f0` | `#3E3E3E` |

统计：全工程仍带主题分支色的控件从 **~40 处降到 2 个**（其余被 `strip_conflicting_stylesheets` 中和）。

### 6.2 R9 对比度判定的收敛（让检测器重新可信）

**问题**：浅色主题下 3 个小按钮被误报低对比，其中 `开始科学分析 (RAG)` 实测渲染完全正常。

**根因（逐层挖出来的）**：

1. ❌ **百分位极值法**：取"离中位数更远的一端"当前景。
   实测该按钮高光距中位数 `0.4538` > 文字 `0.4239` → **高光被当成前景**。
2. ❌ **聚类法**：找"第二显著亮度簇"。对带立体高光的按钮，引擎的镜面高光带占 30% 高度，
   簇比文字还大 → 仍选中高光（`#9F9432` 而非白色文字）。

**最终方案**：**读声明的文字色**（样式表 `color:` 优先，其次 `palette.WindowText`），
**只对背景做测量**（内部像素中位数）。

> 设计理由：文字色是**确定值**（Qt 就按它渲染），真正需要"测量"的是背景 ——
> 背景会受玻璃叠加、主题、语义色影响。这样既准确又保留了对"深色字压深色底"的检出能力。

### 6.3 R9 由此抓出的 4 个真实问题

| 问题 | 现象 | 修复 |
|---|---|---|
| 3 位简写色漏网 | `color:#888` 未被清理（名单只有 6 位形式） | 补 `#888/#777/#999/#aaa/#bbb/#ccc` |
| **语义色提亮过度** | 引擎把 `#2E7D32` 提亮 +34 → 白字仅 **3.23:1** | 语义按钮提亮降到 **+6**（4.72:1），并跳过镜面高光带 |
| `#009688` 未 remap | 白字压青底 **2.64:1** | 加入 `_CONTRAST_FIX` → `#00695C`（5.90:1） |
| **语义色被玻璃覆盖** | 控件样式表的 `background-color` 被引擎玻璃盖住 → 渲染成浅灰底白字 | 引擎新增 `_semantic_base()`：**读取**控件样式表的语义底色并自行绘制（顺带获得 3D 倒角） |

最终：**深色 0 / 浅色 0 / 自检 PASS**。

## 7. 为什么不用 box-shadow

Qt 样式表**不支持** `box-shadow` / `inset` / `text-shadow` / `filter`。光影用三招模拟：

1. **多段渐变** —— 顶部亮→底部暗 = 凸起；反向 = 内凹；
2. **分边异色边框** —— 上/左取高光色、下/右取阴影色 = 斜面倒角（`_bevel()`）；
3. **真实投影** —— 仅对必要外壳用 `QGraphicsDropShadowEffect`。

> ⚠️ 实测教训：把 `QGraphicsDropShadowEffect` 加在**标题栏或其子标签**上，会迫使 Qt
> 重新栅格化父级背景，导致拉丝贴图出现**色差接缝**并在栏下叠出**硬边暗矩形**。
> 现标题栏已完全改用描边+渐变表达深度。

## 8. 程序化材质：**磨砂玻璃**（非金属）

QSS 无法内联生成位图，因此把材质落成 PNG 再 `url()` / 纹理笔刷引用：

- 输出到 `%LOCALAPPDATA%/MedicalImagingWorkflow/cache/skin/`；
- 文件名带 **版本号 + 配色名**（`frost_dark_v6.png`），改生成器/换肤自动失效重建（`_MATERIAL_VERSION`）；
- **无缝前提**：每行横向恒定 + 颗粒边缘环绕绘制，`repeat-x` 平铺无接缝。

| 材质 | 特征 |
|---|---|
| `frost_pixmap()` | **各向同性**细颗粒 —— 与拉丝金属的**本质区别**（金属是定向横纹 + 刻度线）；边缘环绕绘制保证可平铺 |
| `surface_pixmap(kind)` | 半透明玻璃面（`panel`/`raised`/`sunken`）：纵向玻璃渐变 + 各向同性颗粒 + 顶部受光带 |

**玻璃令牌**（`MetalPalette` 新增）：

| 令牌 | 深色 | 作用 |
|---|---|---|
| `glass_hi` / `glass_lo` | `rgba(170,212,255,0.17)` / `rgba(108,158,228,0.05)` | 玻璃面上下渐变（**半透明**） |
| `glass_rim` | `rgba(218,240,255,0.36)` | 边缘反光（上/左） |
| `glass_edge` | `rgba(0,10,28,0.55)` | 外缘暗线（下/右） |
| `glass_shadow` | `rgba(0,4,14,0.42)` | 投射阴影 |
| `bg_glow` | `rgba(46,140,255,0.20)` | 背景装饰辉光（**让玻璃"有东西可模糊"**，否则纯色底上玻璃看起来就是一块亮矩形） |

> ⚠️ 玻璃填充必须用**保 alpha** 的调色助手 `_lighter_a()/_darker_a()`；
> 用普通 `_lighten()` 会把 alpha 重置为 255，玻璃立刻变成不透明色块。

> ⚠️ Qt 的子控件默认不透明，"玻璃"实际是**半透明填充叠在继承背景色上**，
> 不是真正的背景模糊。视觉上依靠 **边缘反光 + 颗粒 + 投射阴影** 三件套成立。

## 9. 局部样式清理（让全局皮肤真正生效）

各页面大量使用内联 `setStyleSheet`（浅色主题遗留），会覆盖全局 QSS。
`strip_conflicting_stylesheets(root)` 在窗口构建完成后统一处理：

- **清理**：含"浅色外壳色"（`#FFFFFF`/`#E0E0E0`/`#2E86AB`…）的内联样式；
- **保留**：含**功能性语义色**（`#4CAF50` 成功绿 / `#F44336` 危险红 / `#FF9800` 警告橙）
  的样式，避免破坏状态色含义。

实测：`{'scanned': 70, 'stripped': 21, 'kept': 49}`。

## 10. 防遮挡保障（`scripts/check_occlusion.py`）

| 规则 | 检查 |
|---|---|
| R2 溢出 | 子控件/页面超出父容器或视口 |
| R3 同级重叠 | 同一父容器下两个可见控件互相遮挡 |
| R4 塌陷 | 可见控件被压成 ≤2px |
| R5 屏幕遮挡 | 窗口最小尺寸超出屏幕可用区（**底部被屏幕裁掉**） |
| R6 渲染伪影 | 贴图横条的**持续性色阶断层**（接缝）/ 硬边尖峰（残影） |
| R7 文字适配 | **R7A** 横向截断、**R7B** 纵向裁切（含 `\n` 多行） |
| R8 材质纯色性 | 面板材质必须是纯冷蓝（逐像素 `b>=r 且 b>=g`），杂色率 >0.5% 报警 |
| **R9 对比度** | 逐控件抓**合成像素**算 WCAG 对比度；正文要求 4.5:1、大字号 3:1；禁用控件豁免 |

> R9 实测踩过的三个坑（都写进注释了）：
> 1. 单独 grab 透明背景的 QLabel → 背景变黑 → 假阳性；必须**抓整页再按坐标裁剪**。
> 2. 按"颜色桶 + 面积百分比"设阈 → 抗锯齿把字形摊到多个桶 → 3 行文字被判成 1.00:1；
>    改用**亮度百分位**（0.2% 暗端/亮端）。
> 3. 大而空的标签（661×202 只放 4 个字，文字占 0.05%）任何统计都定位不到字形
>    → 加**有效性守卫**（区域过于平坦 / 文字面积占比 < 1/25）直接跳过，避免假阳性。
>    实测检查覆盖 77/139 个文本控件，其余由 R7 与人工核对覆盖。
| R8 材质纯色性 | 面板材质必须是纯冷蓝（逐像素 `b>=r 且 b>=g`），杂色率 >0.5% 报警 |

> R1「挤压」已确认为**死规则**：Qt 强制遵守 minimum size，控件只会"变大溢出"（由 R2 捕获），
> 不会"被压小"。

**防假阴性**：`--self-test` 会植入已知缺陷并断言规则命中
（R2 溢出 / R3 重叠 / R7A 截断 / R7B 换行裁切 / R7B 多行裁切 均验证可捕获）。

### 已修复的真实遮挡

| 问题 | 根因 | 修复 |
|---|---|---|
| 窗口底部被屏幕裁掉 | 页面 `minimumSizeHint` 高达 1090px → 主窗口最小高 **1224px** > 1080p | 每页包 `QScrollArea` → 最小高降到 **205px** |
| **`当前项目` 第 3 行被裁** | 分组框 `setFixedHeight(120)` 写死 + 皮肤 `margin/padding` 多吃 13px | 去掉固定高度改 `setMinimumHeight`；皮肤内边距对齐原值（12+8=20px） |
| 标题栏接缝 + 硬边残影 | `QGraphicsDropShadowEffect` 重栅格化父背景 | 去掉图形特效，改 QSS 描边/渐变 |
| 下拉框/面板出现白底 | 21 处浅色内联样式覆盖全局皮肤 | `strip_conflicting_stylesheets()` |
| **语义色（绿/红/橙）被材质盖住** | Qt 视 `background-image` 与 widget 自身 `background-color` 为不同属性，贴图覆盖语义色，且 `background-image:none` 无法取消 | 按钮**不用** `background-image`，改用 `background` 简写（可被语义色覆写）；颗粒质感由面板/输入框承担。像素级验证：新建样本 `#4CAF50`、刷新 `#FF9800` |

当前结果：**9 页面 + 壳层 + 标题栏 + 材质纯色性 = 0 issues**；
139 个文本控件全部通过适配检查；面板材质非冷蓝像素 **0.00%**。

## 11. 预览与验证

```powershell
python scripts/preview_skin.py                      # 渲染皮肤预览图到 docs/screenshots/
python scripts/check_occlusion.py                   # 遮挡/文字/伪影体检（0 issues 为通过）
python scripts/check_occlusion.py --self-test       # 验证检测器本身有效
python scripts/check_occlusion.py --dump button     # 几何转储
python scripts/check_states_real.py --theme dark    # 真机四态点验（真实鼠标）
python scripts/check_states_real.py --theme light
python scripts/probe_motion.py                      # 过渡动画取证（中间帧 + 不变量）
python scripts/audit_visual_defects.py              # 溢出 + 重影结构检查（0 命中为通过）
python scripts/audit_visual_defects.py --self-test  # 植入缺陷验证检测器本身有效
python scripts/zoom_suspects.py                     # 可疑控件 3~4 倍放大裁剪，供目视判定
```

> ⚠️ `preview_skin.py` 默认使用**真实 windows 平台**——`QT_QPA_PLATFORM=offscreen`
> 在本构建下**没有任何字体**（`font families = 0`），渲染出来全是方框，无法评审外观。
> 需要无头运行时加 `--offscreen`。

---

## 12. 真机四态点验（悬停 / 按下 / 禁用 / 选中）

### 12.1 为什么必须先修测量工具

**第一版工具会骗人**。它用 `setAttribute(Qt.WA_UnderMouse, True)` + `sendEvent(Enter)`
伪造悬停。在绘制时刻打印 `option.state` 得到：

```
[button] bits=['Enabled', 'HasFocus', 'Active']  underMouse=True
```

`underMouse()` 确实变成了 True，但 Qt **不会**把 `State_MouseOver` 放进 `QStyleOption`
→ 引擎收到的 `hovered` 永远是 False → **所有悬停态都被测成「像素差 0」**。

危险之处在于它制造**假阴性可信度**：按下/禁用/选中都能测出来，报告看起来"部分可信"，
很容易让人得出"悬停压根没实现"的错误结论。

**正确做法**：用 Windows `SetCursorPos` 移动**真实光标**，让操作系统派发
`WM_MOUSEMOVE`，走 Qt 真正的 enter/leave 机制；按下态用真实 `mouse_event(LEFTDOWN/LEFTUP)`。
并带三层自校验：`underMouse()` 为真、`WindowFromPoint` 命中的是**本窗口**、目标在屏内。

### 12.2 由此抓出的 3 个真实缺陷

| # | 缺陷 | 根因 | 修复 |
|---|---|---|---|
| 1 | **悬停写进死变量** | `paint_raised` 的 hovered 只提亮 `top`/`mid`/`bot`，而真正画面部渐变的是 `gh`/`gl`；`top`/`mid` **从未参与面部绘制** | 提亮改到 `gh`/`gl`（`_lighter_a` 保 alpha）+ 镜面高光带增强 + 棱线 `light_extra=30` |
| 2 | **3D 挤出侧壁不可见** | `side` 与 `face` 都是 `translated(0, depth)` → 两矩形完全相同，面把侧壁 100% 覆盖 | 侧壁改为**贴底窄带、画在面之上**并裁剪进面部路径（`3b` 步） |
| 3 | **表头悬停完全无反馈** | `QHeaderView` **不把** `State_MouseOver` 放进 option（真实光标在表头上、`underMouse=True` 时，绘制时刻 state 位只有 `['Enabled']`）—— 表头悬停是由 `QStyleSheetStyle` 的 `:hover` 伪状态实现的 | 引擎自己判定：`QCursor.pos()` 反查命中的 section 并与 `option.section` 比对 |

另外补齐：`paint_well` / `paint_check` / `paint_radio` 增加 `hovered` / `disabled`；
`_combo` / `_slider` / `_scrollbar` 派发状态；禁用态用 `disabled_text` 画勾/圆点/箭头。

> ⚠️ 半透明填充（井底 / 玻璃面）**只能用** `_lighter_a` / `_darker_a` / `_with_alpha` 调色。
> `_lighten` / `_lerp` 返回 3 参数 QColor（**alpha 丢失**）→ 玻璃立刻变不透明。

### 12.3 最终结果（两套主题各 22/22 全过）

数字 = 最大通道差 / 超过 4 的像素数。底噪实测 **0.000%**，故任何非零差异都是真信号。

| 控件 | hover | pressed | disabled | selected |
|---|---|---|---|---|
| button | ✓ 39 / 3474px | ✓ 116 / 3877px | ✓ 94 / 4945px | – |
| button2 | ✓ 39 / 3927px | ✓ 116 / 4322px | – | – |
| line | ✓ 34 / 31420px | – | ✓ 63 / 30481px | ✓ focus 244 |
| combo | ✓ 41 / 3962px | – | ✓ 87 / 4002px | ✓ 232 |
| check | ✓ 14 / 439px | – | ✓ 19 / 445px | ✓ 238 |
| radio | ✓ 16 / 384px | – | – | ✓ 230 |
| slider | ✓ 35 / 2174px | – | ✓ 159 / 3819px | – |
| scroll | ✓ 35 / 7045px | ✓ 114 / 7168px | ✓ 54 / 6304px | – |
| header | ✓ 31 / 18994px | – | – | – |
| tabs | – | – | – | ✓ 237 / 6362px |

```
dark :  22 项，异常 0 项   RESULT: PASS
light:  22 项，异常 0 项   RESULT: PASS
```

**回归**：浅色 0 issues / 深色 0 issues / 检测器自检 PASS / 10 个控件接管计数全部正常。

### 12.4 踩过的坑

* **测量工具必须先自校验**：`underMouse()` 为真 ≠ 状态位为真。任何"某状态完全没效果"
  的结论，都要先用"绘制时刻打印 state 位"取证，再下判断。
* **真实光标会抖动**：窗口丢失置顶/激活时光标不落在本窗口上；光标位置未变时 Windows
  不派发新的 `WM_MOUSEMOVE`。→ 重试 + 1px 抖动 + 重新置顶 + `WindowFromPoint` 校验。
* **误点风险**：真实左键点击前必须确认光标落在本窗口，否则会点到别的窗口上。
* **测试结束要还原光标原位**。
* `scripts/check_states.py`（第一版）已改成**指路牌**，运行会直接退出并提示改用
  `check_states_real.py`——避免以后有人再被它误导。

---

## 13. 过渡动画与统一焦点环

### 13.1 为什么动画必须单独一层

`QProxyStyle` 是**无状态绘制器** —— Qt 每次重绘都独立调用它，它拿不到"上一帧画到哪儿了"。
所以过渡进度**只能存在控件上**（动态属性 `_sk_hover` / `_sk_focus`），
由应用级事件过滤器驱动 `QVariantAnimation` 更新，绘制时再读回来。
见 `src/utils/skeuo_motion.py`。

三条设计不变量：

1. **布尔决定"是否画"，浮点决定"画多强"**
   `hovered` 决定走不走悬停分支，`hover_k` 决定提亮多少。
   关键是 `hover_k == 0` 必须**逐像素等于**不悬停 —— 否则动画首帧会跳变。
   （实测：`hover_k=0` vs 无动画层未悬停 = **最大通道差 0** ✅）
2. **门控必须由动画驱动，不能由 state 位驱动**
   离开控件时 Qt **立刻**清掉 `State_MouseOver`。若用 state 位门控，
   离场动画没有插值机会、会"啪"地跳回去（比不做动画更难看）。
3. **无动画层时自动退化为布尔**
   离屏渲染、`preview_skin.py`、体检脚本不装动画层 → `motion()` 返回 `None`
   → 引擎退回读 state 位 → **既有渲染逐像素不变**。

### 13.2 实测动画曲线（`scripts/probe_motion.py`）

```
      t(ms)   hover_k   亮度      underMouse
       26.7      0.000   0.2790   True    ← 进入，属性初始化
       76.9      0.386   0.2939   True    ← 动画开始
       90.2      0.546   0.3001   True
      102.4      0.666   0.3044   True
      127.8      0.850   0.3117   True
      153.6      0.950   0.3156   True
      166.6      0.975   0.3169   True
      203.6      1.000   0.3169   True    ← 到位
```

| 指标 | 结果 |
|---|---|
| 进入中间帧（严格介于两端之间） | **4** 个 `[0.386, 0.546, 0.666, 0.666]` |
| 离开中间帧 | **4** 个 `[0.614, 0.465, 0.334, 0.334]` |
| `hover_k=0` == 未悬停 | 最大通道差 **0** ✅ |
| Enter/Leave 事件数 | **2 条**（无事件风暴） |

### 13.3 统一焦点环

**问题**：`line` 的焦点反馈来自全局 QSS 的 `QLineEdit:focus { border }`，
而 `combo` / `check` / `radio` / `slider` / `tabs` **完全没有** —— 键盘用户看不出焦点在哪。

**更糟的是那条 QSS 规则本身就是错的**：`:focus` 一旦有 `border`，
QStyleSheetStyle 就接管绘制并**跳过引擎** → 聚焦时 3D 井**整块消失**、
变成平涂 + 一条 1px 边框。实测 `line/focus` 像素差 244，本质是"3D 井没了"，
而不是"多了一圈焦点反馈"。

**修法**：删掉 QSS 的 `:focus` 边框，焦点环改由引擎统一绘制
（`SkeuoPainter.paint_focus_ring`：贴边内缩的电光蓝主环 + 外侧两圈柔光）。
环必须画在控件**内部** —— 画在外面会被父容器裁掉或与相邻控件压盖
（本项目最硬的一条约束就是"所有 block 没有遮挡"）。

顺带清掉了另外两处同类冲突：

| QSS 规则 | 原来发生的事 | 现在 |
|---|---|---|
| `QPushButton:disabled { background; border }` | 禁用按钮一直是 **QSS 平涂**，引擎里那段 disabled 玻璃**从未被执行** | 交给引擎画（`gh/gl` 降透明 + 棱线柔化） |
| `QPushButton:checked { background; bevel }` | 同上 | 交给引擎的 `sunken` 分支 |

> 只写 `color` 是安全的：`color` 不构成 drawable 规则，不会触发 QStyleSheetStyle 接管。
> 这是本项目反复踩到的坑 —— **QSS 里任何一个背景/边框属性都会让引擎在该状态下失效**。

### 13.4 焦点环实测（两套主题各 7 个控件全过）

| 控件 | dark 最大差/像素数 | light 最大差/像素数 |
|---|---|---|
| button | 233 / 1421 | 180 / 1419 |
| line | 247 / 8268 | 203 / 8261 |
| combo | 233 / 1639 | 163 / 1635 |
| check | 233 / 1170 | 157 / 1142 |
| radio | 232 / 1148 | 157 / 1125 |
| slider | 231 / 321 | 167 / 321 |
| tabs | 191 / 1373 | 166 / 1371 |

```
dark :  29 项，异常 0 项   RESULT: PASS
light:  29 项，异常 0 项   RESULT: PASS
```

**回归**：浅色 0 issues / 深色 0 issues / 检测器自检 PASS。

### 13.5 踩过的坑

* **动画不是"首尾两帧不同"就算做了**。必须采样时间序列、证明存在**严格介于两端之间**
  的中间值 —— 否则"瞬时切换"也能骗过只看首尾的检查。
* **测量前必须等动画稳定**。`grab()` 是同步渲染：在动画途中抓图，基线与被测帧可能
  都落在中间态 → 算出**假阴性"差 0"**（实测踩过：`line/hover` 报 0，其实只是基线还在归零途中）。
  现在 `check_states_real.py` 会先 `settle()` 到目标值再抓图，并在未稳定时明确标注。
* **一次抖动不该报成缺陷**："状态已确认到满但像素差为 0"时自动重测（最多 3 次）。
* `time.sleep()` 期间**事件循环不跑**：Enter 事件会一直躺在队列里，
  动画根本没起步。等待必须用 `processEvents()` 轮询，不能用纯 sleep。
* 光标位置未变化时 Windows **不派发新的 WM_MOUSEMOVE** → 停靠与悬停都要抖动 + 校验
  （`park_cursor()` 现在会校验 `park.underMouse()`）。

---

## 14. 重影与控件溢出（用户实测反馈）

### 14.1 控件溢出：三个独立成因

**① 皮肤的 QSS 反过来撑破了应用自己的固定行高**

`QStyleSheetStyle` 会把 QSS 的 `min-height` / `padding` 转成**真实的 `setMinimumSize`**，
从而**压过**应用里的 `setFixedHeight(24)`：

| 位置 | 应用设定 | QSS 强制 | 结果 |
|---|---|---|---|
| `ai_summary_widget.py:1228` 工具条 | `setFixedHeight(32)` | `QComboBox{min-height:16px; padding:6px 9px}` → 30px | 下拉框放 y=4 → **溢出 2px** |

实测该行固定高度只有 **22 / 24 / 26 / 32**（`setFixedHeight` 分布），
所以皮肤给控件的竖向占用必须压到 ~24px 以内。
**修法**：删掉 `min-height`，`padding` 从 `6px 9px` 降到 `3px 8px`
（引擎自己画井的立体感，视觉内边距不依赖 QSS padding）。

**② `QPushButton::sizeHint()` 被 Qt 重写成"只按文字算"，完全不看内部布局**

`create_function_button` 里给按钮塞了"图标 + 名称 + 3 行描述"的布局，
却写死 `setFixedSize(300, 150)` —— 而内容实际需要 ~163px。
按钮不会跟着内容长高，**描述标签被顶出 8px、最后一行"增删改查操作"被边缘切掉**。
**修法**：加完子控件后用布局算高度 —— `button_layout.totalSizeHint()` ——
再 `setMinimumSize(300, need_h)`（实测布局会尊重显式最小尺寸）。

**③ `ensure_text_fits` 无条件提高多行标签的最小高度**

它在"祖先里有固定尺寸容器"时会**把子控件顶出容器边界**（正是②的放大器）。
**修法**：新增 `_in_fixed_height_ancestor()` 守卫 —— 祖先高度固定时直接跳过，
让"内容比容器大"这类问题**由容器自己放宽尺寸解决，而不是被掩盖**。

> 教训：皮肤层**绝不能靠撑大控件来解决容纳问题**。容器尺寸是应用的契约，
> 皮肤要么在自己的帧缓冲里适配，要么如实报错。

### 14.2 重影：引擎与 Qt 各画一遍

**成因（结构性，一侧代码就能确认）**：`QComboBox::paintEvent` 的顺序是

```
drawComplexControl(CC_ComboBox, opt)   ← 走到引擎的 _combo
drawControl(CE_ComboBoxLabel, opt)     ← Qt 随后再画一遍文字
```

而 `_combo` 里**也** `drawText` 了一遍 → 同一串字被错位画两遍 = **重影**。

**修法**：删掉引擎里的手绘文字，交给 `CE_ComboBoxLabel`（它自带省略号处理，
禁用态还会用调色板的 disabled 颜色组）。至此**全引擎不再手绘任何文字** ——
表头、标签页、分组框标题一直是交给 Qt 画的。这一类重影被从结构上消灭。

### 14.3 为什么最终**放弃**了像素级重影检测

先按"同一串字错位画两遍 → 墨迹孪生率在错位量处升高"做了检测器
（`scripts/audit_visual_defects.py` 的 `ghost_score`，自检植入缺陷验证有效）。
但实测**对汉字不可用**：

| 样本 | 孪生率 | 目视 |
|---|---|---|
| 自检-单次绘制 | 0.557 | 干净 |
| 自检-错位两遍 | 0.783 | 重影 |
| `TXT` 组合框 | **0.916** | 干净（两个 `T` 是同一字形） |
| `刷新列表` 按钮 | **0.918** | 干净（4 倍放大确认） |

汉字致密、字形相似，**单次绘制的本底就有 0.56**，真实控件上到 0.92 ——
与真重影**无法区分**。

**改为结构性不变量**（零假阳性）：

```
R12_engine_draws_text —— 三维引擎的代码里不得出现 drawText(
```

（去注释与文档字符串后正则扫描 `skeuo_style.py`。检查器本身执行失败时
**主动报错而非静默通过** —— 第一版就因漏 `import re` 报错，正好证明了这条设计。）

### 14.4 新增审计工具

```powershell
python scripts/audit_visual_defects.py                 # 溢出 + 重影结构检查（0 命中为通过）
python scripts/audit_visual_defects.py --theme light
python scripts/audit_visual_defects.py --self-test     # 植入缺陷验证检测器本身有效
python scripts/zoom_suspects.py                        # 把可疑控件裁出 3~4 倍放大供目视
```

| 规则 | 判据 |
|---|---|
| `R10_child_out_of_parent` | 子控件矩形越出父容器矩形 |
| `R11_child_out_of_painted_body` | 子控件矩形越出父容器的**绘制面**（引擎画的面常比 widget 小，如分组框是 `adjusted(0,10,0,-1)`） |
| `R12_engine_draws_text` | 引擎代码里出现 `drawText(`（结构性，零假阳性） |

**结果**：两套主题各 **0 命中**；对比度回归 浅色 0 / 深色 0 / 自检 PASS；
真机四态 深色 29/29、浅色 29/29。

### 14.5 顺带修掉的第四个假阴性

浅色那轮**所有 focus 测量都是 0**。原因不是渲染，而是**窗口不是活动窗口**：
`setFocus()` 的 FocusIn、以及真实左键点击都要求窗口激活，
而 Windows 会阻止前台窗口被抢走（`activateWindow()` 底层 `SetForegroundWindow`
可能被静默忽略）。窗口属于**本进程**，所以 `SetActiveWindow` 是允许的 ——
`ensure_active()` 用它做校验，失败时明确记为"窗口未激活"而不是悄悄报 0。

---

## 15. 液态玻璃浅色主题（Liquid Glass，静态无动画）

浅色模式整体重设计为 **液态玻璃**：半透明玻璃体 + 环境光透射 + 镜面棱 + 冷蓝柔影。
**深色主题完全不动**（已验证逐项不变）。

### 15.1 设计要素

| 要素 | 实现 | 位置 |
|---|---|---|
| 环境背景 | 程序化生成：冰蓝空气渐变 + 5 团大尺度柔光斑（径向渐变=天然静态模糊） + 顶部斜向薄纱 + 极细颗粒 | skeuomorphic.backdrop_pixmap() |
| 整窗铺底 | order-image: url(backdrop) 0 0 0 0 stretch stretch（柔光斑拉伸变形无感） | global_qss / main_window.apply_styles |
| 玻璃面板 | 真半透明：glass_hi 白 0.78 → glass_lo 冰蓝 0.44；顶部 9% 内沿白色镜面高光；左上「受光点」径向柔光斑；底部冷蓝内阴影（玻璃厚度） | SkeuoPainter.paint_panel |
| 冷蓝柔影 | 投影不再是近黑 
gba(0,3,10)，改 
gba(84,114,164) 且扩散更大（黑色投影在亮玻璃上发脏） | paint_raised / paint_panel 浅色分支 |
| 凝胶按钮 | 顶部 44% 白高光盖（a=112~152），按住仍走内凹分支 | paint_raised 浅色分支 |
| 玻璃井 | 冷却蓝顶 → 近白底，冷蓝内阴影（替代纯黑），白色下唇反光 | paint_well 浅色分支 |
| 大圆角 | 按钮 6→8 / 井 5→7 / 面板 9→14 / 菜单 10→11 / 表格 10→12 / 页签 9→12（仅浅色） | skeuo_style._button/_well/_groupbox/_combo + global_qss |
| 亮玻璃 chrome | 菜单栏/状态栏/标题栏/弹层/表格底换成亮玻璃渐变；弹层用 0.97 高不透明度保正文对比度 | global_qss / 	itle_bar_qss |

**不做动态动画**（按要求）：所有效果都是静态绘制；既有的悬停/焦点过渡沿用原动画层，未新增。

### 15.2 令牌级换肤（LIGHT_ALU）

色阶整体提亮降饱和（s900 #8FA6C4→#AFC2DE … s600 #D6E2F0→#E4EDF9），
玻璃令牌改「上实下透」：glass_hi rgba(255,255,255,0.78)、glass_lo rgba(214,231,250,0.44)、
glass_edge rgba(146,174,212,0.52)、glass_shadow rgba(84,114,164,0.22)。
材质版本 _MATERIAL_VERSION 6→7（新增 backdrop 缓存自动重建）。

### 15.3 踩坑记录

- **QRadialGradient 漏 import**：ensure_materials 的生成器异常被 except: pass
  静默吞掉 → backdrop 文件根本没落盘、order-image 指向不存在的文件、
  窗口背景回退默认色。肉眼看上去只是有点平，极易漏掉。**新增材质后必须验证文件已生成**。
- 弹层/表格**不能用全透玻璃**：正文压在复杂环境上对比度不可控，
  所以菜单/下拉/表格用 0.78~0.97 的高不透明度玻璃，玻璃感靠边缘与高光表达。
- 面板 alpha 过高（≥0.85）会退化成白卡——环境光透不过来就没有液态玻璃可言。

### 15.4 验证（浅色液态玻璃 + 深色不变）

| 检查 | 结果 |
|---|---|
| preview_skin.py（浅色） | 面板透光可见光斑、棱线/受光点正常 |
| check_occlusion.py（深/浅两轮） | RESULT PASS，exit 0 |
| udit_visual_defects.py | []，exit 0（R10/R11/R12 无命中） |
| 浅色菜单文字对比度 | #0a1524 on #f5f9fe = 17.34:1 OK |
| 深色主题 | 与改前逐项一致（色阶/引擎分支全部走 dark 老路径） |
| check_menus_and_pages.py | 菜单 8/8、切页 5/5（热切换到浅色后页面截图均为液态玻璃） |

---

## 16. 鎏金深色主题（Dark Gold）

深色模式整体改为 **鎏金**：暖黑青铜底材 + 金琥珀（深黄）高光/选中/标题，
用金色凸显内容、字体、按钮、菜单。**浅色（液态玻璃）完全冻结**——
改后逐像素对比 **diff=0**（lg5 vs lg6 全图 0 差异）。

### 16.1 配色令牌（DARK_METAL）

| 令牌 | 旧（冷蓝） | 新（鎏金） |
|---|---|---|
| 色阶 s900…s200 | #04070E…蓝灰 | #0A0702 → #8A6F42（暖黑→黄铜） |
| accent / accent_hi | #1E90FF / #5CC8FF | **#D9A62E / #F3CB5A**（金/亮金） |
| text / text_dim | 冷白 / 蓝灰 | #F0E6C8（暖奶油）/ #B3A379（暖褐灰） |
| glass_hi / glass_lo | 蓝玻璃 | 青铜玻璃 rgba(96,72,30,.58) / rgba(30,21,8,.72) |
| glass_rim / bg_glow | 冷蓝棱/辉光 | 金棱 rgba(255,226,150,.40) / 琥珀辉光 |
| chip_text | #A8E0FF | #F5D680 |

对比度：奶油字在暖黑上 ≥13:1；**菜单栏文字 #F0E6C8 on #171107 = 15.06:1**（自检实测）。

### 16.2 引擎深色分支暖化（浅色分支逐条未动）

新增 _shadow_rgb(t, light_rgb)：共享阴影在浅色=冷黑蓝，深色=暖黑 (12,6,1)。
逐条替换的共享路径：倒角暗端/亮端、挤出下沿、按下内阴影、井内阴影、
勾选/单选内阴影与标记阴影、下拉箭头描边、薄板下沉态。
深色专属路径：井底 (14,8,2)/(58,42,16)、按钮镜面 (255,235,190)/(250,205,120)、
面板内高光 (255,215,140)、下唇反光 (255,210,130)。

### 16.3 QSS：选中态 = 亮金渐变 + 深字

鎏金 accent 是**亮色**，奶油字压金渐变下半段对比度不足 —— 深色专用：
- 菜单/表格/列表选中：_grad(accent_hi, accent) + color/#selection-color #241B04
- 输入框文本选中：selection-color: {sel_fg}（浅色仍 #FFFFFF）
- 弹层（QMenu/QComboBox popup）用青铜底 + 深字选中
- 表格底/标题栏底缘的海军蓝尾巴全部换成暖黑（
gba(12,7,1,*)、
gba(18,11,2,*)）

### 16.4 材质颗粒

rost_pixmap / surface_pixmap 的深色颗粒由冷蓝改为暖金
（浅色分支保持原蓝颗粒）。opencode_panel 的自持深色列同步暖化（亮度级保持，对比度对不变）。

### 16.5 顺带修复：R8 材质纯色性检查器主题感知化

check_occlusion.py 的 R8 原写死面板必须冷蓝（b≥r,g）——
鎏金主题下正常材质被误报 **99.97% 杂色**。改为：取当前调色板 s600
的最强通道，要求采样像素该通道 ≥ 其余两通道。
浅色主题 s600 最强通道仍是蓝 → 判据与旧版逐位一致；
--self-test 自检 PASS。

### 16.6 验证（鎏金 + 浅色回归）

| 检查 | 结果 |
|---|---|
| 浅色像素回归（改前 vs 改后同场景截图） | **diff=0，bbox=None**（冻结成立） |
| check_occlusion.py（深/浅两轮） | RESULT PASS，exit 0（R8 偏离主色 0.04%） |
| udit_visual_defects.py | []，exit 0 |
| 	est_dialog_flows.py | 9/9（含首启向导/授权/模板向导） |
| check_menus_and_pages.py | exit 0（菜单弹窗 + 切页 + 热切换） |
| 菜单栏对比度 | 15.06:1 OK |
| 菜单选中态 | 金渐变 + 深字（目视 + 取色 #e3b43f） |

### 16.7 返工修正（v2）：深蓝底 + 金只做强调

**用户反馈**：① 浅色不应被动过；② 深色不要黄色铺底，只要深黄（金）作
字体/按钮/菜单的**高亮强调色**。

修正内容：
- **浅色**：全量复查（新鲜渲染 + 深→浅热切换 + 页面），与冻结基线逐像素
  **diff=0**；浅色中仅有的偏暖像素=ClearType 亚像素镶边与**既有语义橙**
  （刷新按钮/警告图标 #B45309，皮肤建立以来即存在），非本轮引入。
- **深色底材回退**：DARK_METAL 色阶/玻璃令牌/文字/辉光/投影全部回原冷蓝金属；
  rost/surface 颗粒、表格/标题栏底缘、opencode 面板深色列同步回退；
  _shadow_rgb 改为透传（共享阴影恢复原值）。
- **金=强调色（新增/保留）**：
  | 面 | 处理 |
  |---|---|
  | 字体 | 分组标题/芯片等 accent_hi=#F3CB5A（原电光蓝→金） |
  | 按钮 | 默认/选中(按下)按钮文字金色 + **金色顶弧**（仅深色；浅色不动）；焦点环金 |
  | 菜单 | 选中项=亮金渐变+深字；**菜单栏悬停=金晕**（0.26/0.08 渐变+金边） |
  | 选中态 | 表格/列表/输入文本选择=金底深字（#241B04） |
  | 图标 | accent/accent_hi/chip 角色自动金（text/dim 保持原色） |
- 验证：深色遮挡 PASS（材质主色 'b' 复现）、审计 []、对话框 9/9、
  菜单文字对比度 15.40:1（与改前一致）、浅色遮挡 PASS + 像素 diff=0。
