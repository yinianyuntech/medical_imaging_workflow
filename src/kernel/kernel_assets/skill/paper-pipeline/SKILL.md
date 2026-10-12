---
name: paper-pipeline
description: 端到端把项目数据变成科研草稿（Step2 挖掘 → 事实提取 → 草稿 → 导 Word）。当用户要求「生成论文/草稿/成稿」「跑完整流程」「数据转文章」时使用。
---

# Skill: paper-pipeline（项目数据 → 科研草稿）

## 前置条件

- 已确定 `project_id`（用 `medwork_list_projects` 查询）。
- 项目存储存在（`medwork_project_summary` 能返回非空结构）。

## 执行步骤

### 1. 事实收集（只读，必做）

```
medwork_project_summary(project_id)
medwork_list_samples(project_id)
medwork_list_storage_files(project_id, file_type="tabular")
medwork_aggregate_project(project_id)
```

记录：DICOM/OCR/文本/表格 计数；样本数；可用字段（来自 `medwork_get_schema_cache`）。

### 2. 结构化与统计（写，长任务）

若存在 tabular 文件：

```
medwork_ensure_schema_cache(project_id)      # 跨分支字段归一
medwork_run_step2_mining(project_id)         # 产出 exports/step2_mining_*/ 图表 + report.json
```

**调用前必须先告知用户可能耗时数分钟。**

### 3. 草稿撰写

用 Markdown 写正文，结构固定为：

```
## title
<标题>

## introduction
...（引用 medwork_aggregate_project 的事实，标注 [S1]/[S2] 样本来源）

## methods
...（写明数据来源、纳入样本数、统计方法；不确定处写 [MISSING_DATA: xxx]）

## results
...（数字必须来自工具返回，禁止估算）

## discussion

## conclusion

## reference
- [MISSING_DATA: reference]   # 若无真实文献来源，保留占位，不要编造
```

### 4. 持久化与导出

```
medwork_save_draft(project_id, title, content, model="opencode")
medwork_export_drafts_to_word(project_id)
```

## 质量闸门（自检）

| 检查 | 通过条件 |
|---|---|
| 数据溯源 | results 中每个数字都能指到某次工具返回 |
| 缺失标记 | 缺数据处使用 `[MISSING_DATA: ...]`，不得留空或编造 |
| 样本一致性 | 样本数与 `medwork_list_samples` 一致 |
| 不越权 | 未调用被拒绝的破坏性工具 |

## 失败处理

- `run_step2_mining` 返回 `success=false`：把 `error`/`warnings` 原样报告用户，不要伪造图表。
- 项目无表格数据：跳过第 2 步，直接基于 OCR/文本撰写，并在 methods 说明。
