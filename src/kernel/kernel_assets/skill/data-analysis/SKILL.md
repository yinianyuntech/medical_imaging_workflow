---
name: data-analysis
description: step2 数据分析流程 —— 用 DuckDB 查项目数据、做统计检验、按 Nature 投稿规范出图、提关键词。当用户要求"数据清洗后的统计分析/绘图/关键词提取/做图表"时使用。
---

# step2 数据分析（DuckDB → 统计 → Nature 级图 → 关键词）

## 何时用

用户进入 **step2（数据清洗及结构化）**，或提出下列诉求时：

- "统计一下这批数据" / "做个图" / "提取关键词" / "差异有没有显著性"
- 需要**投稿级**图表（不是随手截图）

## 硬性约束（先读，避免返工）

1. **只用工具取数，不要凭记忆编数字。** 所有数值必须来自
   `duckdb_query` / `compute_statistics` 的真实返回。
2. **不许 p-hacking。** 检验方法由数据前提决定，不能为了"显著"换检验。
   `compute_statistics` 已按 前提（正态性 / 方差齐性）自动选检验，**直接采信它的选择**，
   并在结论里写明用了哪个检验。
3. **报效应量不只报 p。** 至少给出：n、均值/中位数、标准差、检验名、统计量、p、组间差值。
4. **图必须走 `plot_nature_figure`**（它已内置投稿规范）。
   不要自己写 matplotlib 脚本绕过它——尺寸/字号/色板一致性靠它保证。
5. **不改原始数据。** 这些工具只产出 `exports/` 下的新文件；不要试图写回。

## 流程

### 1) 先看有什么数据

```
duckdb_tables(project_id)
```

返回每个可查视图（项目存储里的 csv/parquet/xlsx + 主库表）及其行数、列名。
**列名以这里为准**，不要猜。

若返回 `attach_failed`，说明个别文件挂不上 —— 向用户如实说明是哪个文件、什么错。

### 2) 取数与清洗核对

```
duckdb_query(project_id, sql)
```

- **只读**（INSERT/UPDATE/DELETE/DROP 等会被拒绝，这是设计如此）
- 先做质量核对再分析：`count(*)`、缺失值 `count(*) - count(col)`、
  异常值范围、分组样本量是否均衡
- 分组样本量差距过大时**先告知用户**，不要默默跑检验

### 3) 统计检验

```
compute_statistics(project_id, table, value_column, group_column=?, second_column=?)
```

- 两组：自动 Levene → 学生 t / Welch t；非正态 → Mann-Whitney U
- 多组：Levene → 单因素 ANOVA；非正态 → Kruskal-Wallis
- 给 `second_column` 且无分组：Pearson（正态）/ Spearman
- 返回里 `test.name` / `test.p` / `levene_p` / `normality` 都要进结论

### 4) 出图（Nature 规范）

```
plot_nature_figure(project_id, spec, out_name)
```

`kind` 支持 `bar|line|scatter|box|violin|hist|heatmap`。要点：

| 需求 | 参数 |
|---|---|
| 单栏图 | `"width": "col1"`（89mm） |
| 双栏图 | `"width": "col2"`（183mm） |
| 半栏 | `"width": "col15"`（120mm） |
| 高度 | `"height_mm": 60` |
| 误差棒 | bar 图自动带 SEM 误差棒 |
| 分组排序 | `"sort": true`（按均值降序） |

- **产物三件套**：`pdf`（矢量，投稿首选）+ `svg`（可编辑）+ `png`（600dpi 预览）
- 每张图**只讲一件事**；多子图请分别出图后交给用户拼版
- 配色已用色盲友好板；如需强调分组，用 `"palette"`

### 5) 关键词

```
extract_keywords(project_id, table=?, column=?, text=?, top_k=30)
```

中英混排（英文按词、中文按 2~4 字 n-gram）+ 停用词 + 文档覆盖率加权。
结果可直接作为 step3 的检索主题词或论文 keywords。

## 收尾：给用户的结论怎么写

按这个顺序，缺一不可：

1. **数据**：n、分组样本量、缺失情况
2. **方法**：用了什么检验、为什么（前提检验结果）
3. **结果**：统计量、p、效应量、置信区间（若有）
4. **图**：文件路径 + 一句话说明它展示什么
5. **限制**：样本量/均衡性/多重比较是否校正

> ⚠️ 如果前提不满足、样本量过小、或检验选择有歧义，**主动说明并给出替代方案**，
> 不要为了让结论好看而隐藏不确定性。
