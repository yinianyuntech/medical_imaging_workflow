---
name: literature-to-docx
description: step3 文献流程 —— 检索相关论文、下载 PDF、并用 docxtpl 模板生成结构化稿件。当用户要求"找相关文献/写综述/生成论文草稿/按模板出稿"时使用。
---

# step3 文献检索 → 下载 → docxtpl 出稿

## 何时用

用户进入 **step3（本地大模型数据科学总结）**，或提出：

- "检索相关论文" / "找几篇支持文献" / "查一下有没有人做过"
- "生成综述" / "按模板出一份稿子" / "写成 Word"

## 硬性约束（先读）

1. **绝不编造文献。** 每一条被引用的文献都必须来自 `search_papers` 的真实返回。
   没有检索到就如实说"未检索到"，**不要用记忆里的论文充数**（那会给出错误 DOI）。
2. **只引用检索到的元数据字段**（title/authors/journal/year/doi/url）。
   不要补写"页码""卷期"等返回里没有的字段。
3. **下载必须走 `download_paper_pdf`**（它校验 `%PDF` 魔数）。
   很多出版商链接返回的是登录页/错误页，直接 requests.get 存盘会得到**假 PDF**。
4. **来源限流要如实上报。** Europe PMC 偶发 503、arXiv 会 429 —— 这是上游状态，
   不是"没有文献"。把 `source_errors` 原样告诉用户。
5. **不覆盖用户已有的稿子。** 产物一律写到 `exports/` 下的新目录（工具已如此）。

## 流程

### 1) 检索

```
search_papers(query, sources="europepmc,crossref,arxiv", limit=8)
```

- `europepmc`：生物医学，含摘要与全文链接（**偶发 503 限流**）
- `crossref`：全学科元数据，**覆盖最广、最稳**（默认三源里它最可靠）
- `arxiv`：预印本，有 `pdf_url` 直链（**有 429 限流，需间隔 ≥3s**）

返回里注意三件事：
- `per_source`：每个源各拿到几条 —— 判断是否需要补检
- `source_errors`：哪个源失败了、为什么（**必须转述给用户**）
- `raw_count` vs `count`：去重前后数量

**检索策略**：先宽后窄。第一轮用主题词，看命中质量后，
再用 `AND`/引号等收敛（如 `radiomics AND "prognosis prediction"`）。

### 2) 下载全文（按需）

```
download_paper_pdf(project_id, arxiv_id=?|pmcid=?|url=?, out_name=?)
```

- arXiv 条目直接用返回里的 `arxiv_id`（最可靠）
- Europe PMC 的 `pmcid` 走全文接口，**注意**：可能返回 XML 而非 PDF
  （工具会明确告知并拒绝存成 .pdf，需另按 XML 处理）
- 失败时返回 `error` 里含 Content-Type —— 据此判断是登录页、错误页还是限流
- **不要为了"凑数量"下载无关 PDF**

### 3) 组织内容

`render_docx_template` 的 context 是普通 JSON。**能用真实数据填的字段就填**：

```json
{
  "title": "...",
  "topic": "...",
  "papers": [ {检索返回的条目}, ... ],
  "summary": "要点归纳（可用 llm_chat 生成，但要基于上面的 papers）",
  "abstract": "...", "keywords": "...",
  "introduction": "...", "methods": "...", "results": "...",
  "discussion": "...", "conclusion": "...",
  "data_availability": "..."
}
```

> 用 `compute_statistics` / `plot_nature_figure` 的**真实结果**去填
> results/methods —— 跨 skill 联动，别写空话。

### 4) 出稿

```
render_docx_template(project_id, context, template="builtin:manuscript", out_name=?)
```

| template | 结构 |
|---|---|
| `builtin:manuscript` | 题目/摘要/关键词/引言/方法/结果/讨论/结论/数据可用性/参考文献 |
| `builtin:literature-review` | 题目/检索信息/文献清单表/要点归纳/参考文献 |
| 任意 `.docx` 路径 | 用户自己的模板，占位符用 `{{ key }}` |

**一键版**（便捷入口，内部就是"检索→（可选）下载→出稿"）：

```
literature_to_docx(project_id, topic, limit=8,
                   template="builtin:literature-review", download=0)
```

## 收尾：给用户的结论怎么写

1. **检索**：用了哪些源、各命中几条、哪些源失败及原因
2. **纳入文献**：条数 + 逐条（年份/期刊/标题），标明来源
3. **产物**：docx 路径 + 用了哪个模板
4. **未做的事**：需要全文但没下到的、需要付费墙的，明确列出
5. **可复核性**：给出 DOI，让用户能自己点开核对

> ⚠️ 综述里**不要出现"研究表明……"却不给具体文献**的句子。
> 每个论断都要能指回 `papers` 里的某一条。
