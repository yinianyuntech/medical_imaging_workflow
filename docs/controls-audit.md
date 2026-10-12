# step1~5 全控件功能排查

> 目标：把"第一步~第五步"里**每一个控件**是否功能正常查一遍，并**明确划出未验证的边界**。

## 一键复跑

```powershell
python scripts/audit_controls_step1_5.py --inventory        # 只清点（零风险）
python scripts/audit_controls_step1_5.py --step 1           # 测某一步
python scripts/audit_controls_step1_5.py --resume --step 2  # 崩溃后续跑
python scripts/audit_controls_step1_5.py --report           # 只看已有日志的报告
python scripts/audit_controls_step1_5.py --reset            # 清空日志重来
```

产出：

| 文件 | 内容 |
|---|---|
| `docs/screenshots/controls_audit.txt` | 人读报告（含覆盖边界） |
| `docs/screenshots/controls_audit.jsonl` | 逐条记录（append + flush，可跨进程累计） |

## 步骤 → 页面映射

| 步骤 | 页面 | 控件数 |
|---|---|---|
| 第一步 数据整理 | p0 项目管理 · p1 DICOM ROI · p2 文本处理 · p3 OCR · p4 Magic Seg | 109 |
| 第二步 数据清洗及结构化 | p5 DataCleaning | 7 |
| 第三步 本地大模型数据科学总结 | p6 AISummary | 14 |
| 第四步 科学文本预览生成 | p7 ScientificPreview | 7 |
| 第五步 研究者真实反馈及迭代优化 | p8 FeedbackOptimization | 2 |

## 安全设计（第一原则：绝不改动用户数据）

1. **破坏性控件绝不自动点击**（删除/清空/重置/覆盖/卸载/移除…），只报告可用性与连接情况。
2. **重任务控件不自动点击**（开始/执行/批量/一键/训练/加载/同步/重建/挖掘…），
   可能触发长流水线或覆盖产物。
3. **弹出的模态框一律 `reject()`** —— 即使某个"安全"按钮背后藏着破坏性确认框，也不会执行。
4. **关闭原生对话框**（`Qt.AA_DontUseNativeDialogs`）：Windows 原生文件对话框不是 Qt 控件，
   `activeModalWidget()` 拿不到它 → 自动关闭器失效 → 排查会**卡死**在"选择文件"上。
5. 运行前后核对**项目数 / 样本数 / 数据库文件**，并用 `select_project` **还原初始项目**。
6. 捕获三类失败：slot 内异常（`sys.excepthook`）、`logger ERROR`、对话框打不开/超时。

### ⚠️ 分类器里踩过的安全漏洞

第一版把关键词判定写成 `SAFE → DESTRUCTIVE → HEAVY`，结果：

```
清空选择   → 被判为 safe   ← ✗ "清空"是破坏性，却先命中了 SAFE 里的"选择"
```

**"清空选择"会被自动点击**。破坏性必须**最先**判定。同时修掉两个反向误判：

| 文本 | 原判定 | 问题 | 现判定 |
|---|---|---|---|
| `清空选择` | safe | **危险**：破坏性被当安全 | destructive |
| `上一覆盖层` | destructive | "覆盖层"(overlay) 被误判成"覆盖" | unknown（可安全点击） |
| `🗑` | unknown | **危险**：纯 emoji 无文字，会被当"未知"点击 | destructive |

## 架构：两阶段 + 逐条日志续跑

第一版把"枚举 → 逐个点击"写在同一个循环里，结果**进程硬崩溃（段错误）**：
有些按钮（刷新列表之类）会**重建 UI、销毁旧控件**，而循环还持有列表里后续的旧包装器
→ 访问已释放的 C++ 对象 → 段错误（**没有 Python 异常、没有任何提示**）。

因此改为：

1. **每次点击前重新枚举**该页控件，并校验 `sip.isdeleted()` / 存活。
2. **逐条写日志**（JSONL，append + flush）：硬崩溃只丢当前一条，`--resume` 续跑即可。
3. 报告从日志重建 → **跨进程完整**。

## 结果

```
已实际点击验证 : 60 个
slot 异常      : 0
logger ERROR   : 0
超时/卡死      : 0
数据变化        : projects 2→2，样本统计一致，初始项目已还原
```

### 已证明可用的关键路径

**12 个对话框成功打开并关闭**（这是"按钮是否真的能用"的硬证据）：

- `SampleManagementDialog`（样本管理）
- `QInputDialog`（新建分组）
- `ProjectCreateDialog`（创建新项目）← 用户报错的同一条路径
- `QFileDialog` × 7：DICOM 文件 / DICOM 文件夹 / 覆盖层文件夹 / 文本文件 /
  文本文件夹 / 图像文件 / 结果目录

其余代表性通过项：4 处"刷新"、全部选项类复选框/下拉框/滑杆/数字框、
`⟳` 刷新模型、`+ Custom API`、`📝 提示词修改`、`Rethink Draft (Loop)`、
`Validate All (CocoIndex)`、`Confirm & Proceed to Step 5`、覆盖层翻页。

## 未自动验证的边界（79 个，必须逐条讲清楚）

| 类别 | 数量 | 说明 |
|---|---|---|
| 破坏性 / 重任务 | **20** | 按安全策略**未触发**，需人工确认 |
| 当前不可用 | **25** | 多为「未选样本 / 未选文件」时的**正常禁用** |
| 非交互容器 | **34** | 分组框 / 文本区，本就不需要点击 |

### 破坏性 / 重任务（20 个）——需人工确认

```
p6 AISummary     同步KB(增量) / 重建KB(全量) / Template Wizard / 🗑 / 开始科学分析(RAG)
p5 DataCleaning  AI数据挖掘与绘图
p0 ProjectMgmt   删除勾选
p1 DicomRoi      自动保存结果 / 清除历史 / 保存结果 / 导出数据
p2 TextProcess   移除多余空白字符 / 移除空行 / 移除特殊字符 / 移除标点符号 /
                 自动保存结果 / 清除历史会话
p3 OCR           自动保存结果 / 清除历史会话
p4 MagicSeg      Clear Points
```

### 当前不可用（25 个）——「未选样本/文件」时的正常禁用

```
p0 删除样本 / DICOM / 文本 / OCR
p1 清空选择 / 处理覆盖层文件夹 / 开始处理 / 上一张 / 图像滑杆 / 下一张
p2 复制内容 / 保存内容 / 清空选择 / 开始文本分析 / 导出结果
p3 复制文本 / 保存为文本文件 / 保存标注图像 / 清空选择 / 开始OCR识别
p4 < Prev Image / Next Image > / Save ROI
p5 打开导出目录
p6 删除
```

> 这些控件的**禁用逻辑本身是正确的**（没数据时不该能点），
> 但它们的**实际功能**本轮没有验证 —— 要验证需要先选中真实样本/文件，
> 那会改动工作数据，超出"只排查不改动"的边界。

## 工具本身的已知局限

1. **非交互容器会被枚举出来**（`findChildren` 会连容器一起找）。
   报告里已按类型单独归类，不参与统计。
2. **"无信号连接"对输入类控件是正常的** —— 复选框/下拉框的状态是在使用时才被读取，
   不靠信号驱动。因此"疑似空按钮"只对 `QPushButton/QToolButton` 判定。
3. **不做视觉/语义验证**：只证明"点了不报错、能弹窗、状态能改回"，
   不证明业务结果正确（例如"刷新"后列表内容是否真的正确）。
   视觉层面另有 `check_occlusion.py` / `audit_visual_defects.py` / `check_states_real.py`。
