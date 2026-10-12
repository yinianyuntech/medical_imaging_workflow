# step2 / step3 能力补强（分析 + 文献）

> 对应两项需求：
> ① DeepSeek API 作为 **step1 OCR 的备份**；
> ② **step2**（数据清洗/统计/绘图/DuckDB/nature figure/关键词）与
> **step3**（检索论文/下载 PDF/docxtpl 模板出稿）的完整过程。

## 一、OCR API 备份（step1）

### 落地

| 文件 | 作用 |
|---|---|
| `src/services/ocr_api_backup.py` | 可配置的 **OpenAI 兼容 VL 端点** 客户端 |
| `src/services/ocr_service.py` | `extract_text_from_image()` 变为"先走原链路 + API 兜底"的包装 |

**关键设计：用"包装"而不是改十几条 return 分支。**
原 `extract_text_from_image` 有 Ollama / DeepSeek / vLLM / 传统 OCR / 显存不足
等十几条返回路径；把它重命名为 `_extract_text_from_image_primary`，
公开入口改成：

```python
def extract_text_from_image(self, image_path, config=None):
    res = self._extract_text_from_image_primary(image_path, config)
    return self._apply_api_backup(image_path, config, res)
```

→ **全部 17 个调用点自动获得备份能力**，且原链路一行未动（零回归风险）。
关闭备份：`config["backup_api"] = False`。

### ⚠️ 一个必须澄清的事实

**`api.deepseek.com` 目前只提供文本模型**（`deepseek-chat` / `deepseek-reasoner`），
**不接受图像输入**。所以"用 DeepSeek API 做 OCR"严格说需要 **VL 端点**。

因此实现为「可配置的 OpenAI 兼容 VL 端点」：

* 默认 `base_url` 指向 `https://api.deepseek.com/v1`、模型名 `deepseek-vl2`
  （满足"用 deepseek api"的诉求）；
* `base_url` / `model` 均可换 —— 指向任何兼容 VL 的网关即可真正工作
  （自建 vLLM + DeepSeek-VL2、第三方聚合网关、或日后 DeepSeek 开放 VL 时）；
* **不静默降级**：调用失败时把 provider 的原话一并返回。

### 配置优先级

```
1. 调用参数      config = {"ocr_api_base_url":…, "ocr_api_key":…, "ocr_api_model":…}
2. 环境变量      MIMW_OCR_API_BASE_URL / MIMW_OCR_API_KEY / MIMW_OCR_API_MODEL
3. 既有约定      RSNA_JUDGE_BASE_URL / RSNA_JUDGE_API_KEY
4. 宿主 profile  config/custom_api_profiles.json（第一个含 key 的 profile）
5. 内核 auth     <KERNEL_HOME>/data/opencode/auth.json（已为 opencode 导入过 key 时直接复用）
```

### 验证（`scripts/test_ocr_api_backup.py`，**不需要真 key**）

用本地 stub 服务器冒充 OpenAI 兼容端点，24 项断言全过：

| 验的东西 | 结果 |
|---|---|
| 图像编码：长边 >2000 自动缩放 + `data:image/jpeg;base64,` | ✅ 2400x900 → 2000x750 |
| 原链路失败 → 回退 API 且 `engine == "api_vision"` | ✅ |
| 请求体形状：`content=[text, image_url]`、model 透传、`Bearer` 头、`temperature=0` | ✅ |
| 原链路成功 → **零多余 API 流量** | ✅ |
| 未配 key → `used=False` 且原因明确 | ✅ |
| API 401 / "模型不支持图像" → **provider 原话暴露** | ✅ |
| `backup_api=False` 可关闭 | ✅ |

> 这个 stub 测试当场还抓出一个真 bug：`LLMJudgementClient.chat_completions`
> 成功时返回 `{"success", "content", "raw"}`，**不是**原始 OpenAI 结构；
> 按 `data.choices[0]` 取会得到空文本，表现为"调用了、200 了、但没内容"。

---

## 二、step2 / step3 能力（新增 9 个宿主 MCP 工具）

### 架构分工（沿用 playbook）

* **宿主 = 能力**：每个工具都是可单独调用、可验证的原子操作
* **opencode 内核 = 大脑**：按 skill 决定调用顺序与参数
* **skill = 流程知识**：`data-analysis` / `literature-to-docx` 两份 SKILL.md

### 工具清单（23 → 32）

| step | 工具 | 作用 |
|---|---|---|
| 2 | `duckdb_tables` | 列出可查视图（项目存储的 csv/parquet/xlsx + 主库表）+ 行数/列名 |
| 2 | `duckdb_query` | **只读** DuckDB SQL（写操作被关键字守卫拒绝） |
| 2 | `compute_statistics` | 描述统计 + 正态性 + Levene + t/Welch/Mann-Whitney/ANOVA/Kruskal + 相关 |
| 2 | `plot_nature_figure` | 投稿级绘图，**同时出 PDF(矢量)+SVG+PNG(600dpi)** |
| 2 | `extract_keywords` | 中英混排关键词（英文按词 + 中文 2~4 字 n-gram + 覆盖率加权） |
| 3 | `search_papers` | 多源检索：Europe PMC + **CrossRef（最稳）** + arXiv，逐源回报错误 |
| 3 | `download_paper_pdf` | 下载并**校验 `%PDF` 魔数**（拒绝假 PDF） |
| 3 | `render_docx_template` | docxtpl 渲染；**自带 2 套内建模板** |
| 3 | `literature_to_docx` | 一键：检索 →（可选）下载 → 出稿 |

### Nature 级绘图的硬规范（`_nature_style()` 一次设好）

| 项 | 值 |
|---|---|
| 尺寸 | 单栏 89mm / 半栏 120mm / 双栏 183mm |
| 字号 | 正文 7pt、刻度 6pt |
| 轴线 | 细轴线 0.6pt，**去掉上/右轴线**，默认无网格 |
| 字体 | 优先 Source Han Sans CN（缺则降级），PDF TrueType 嵌入（`fonttype=42`） |
| 色板 | Okabe–Ito 色盲友好 |
| 导出 | PDF/SVG 矢量（投稿首选）+ PNG 600dpi |
| SVG | `svg.fonttype="none"` → 文字**可编辑** |

### 验证（`scripts/test_step23_tools.py`，32/32 PASS）

用合成数据（120 行 CSV，三组）真跑，**用临时目录当项目存储、零 DB 残留**：

```
duckdb_tables        views=1，列出 measurements + 列名
duckdb_query         GROUP BY 三组，均值 14.504 / 10.512 / 9.431 ✔
只读守卫             DROP / DELETE 均被拒 ✔
compute_statistics   Shapiro p=0.0055 → 自动选 oneway_anova，p=2.77e-30 ✔
                     相关性：Spearman r=-0.045 p=0.62 n=120 ✔
plot_nature_figure   6 种图型全部出 PDF+SVG+PNG（bar 宽度精确 89mm）✔
extract_keywords     Top: 影像/图像/特征/科学/随访/复发… ✔
render_docx_template manuscript + literature-review 均无残留占位符 ✔
search_papers        crossref 命中 5 条（europepmc 503、arxiv 429 已逐源回报）✔
download_paper_pdf   假 PDF（HTML）被拒绝 ✔
literature_to_docx   一键出稿 ✔
```

### 过程中修掉的 4 个真 bug（都是"静默失败"类）

| # | 现象 | 根因 | 修法 |
|---|---|---|---|
| 1 | `duckdb_tables` 视图数 0 且无任何提示 | `CREATE VIEW ... read_csv_auto(?)` → **DuckDB 的视图定义不接受预处理参数** | 路径内联为 SQL 字面量（单引号转义）；并把 `attach_failed` **回报到结果里** |
| 2 | 无分组列时"相关性检验"静默返回空 | 拼出 `SELECT "", "value", "age"` —— 空列名非法 | 按需拼列；并改为**按列名取值**，不再依赖 `r[0]/r[1]` 位置假设 |
| 3 | docxtpl `unknown tag 'endfor'` / `unknown tag 'tr'` | `{%p%}` 必须**独占段落**、`{%tr%}` 必须**独占单元格** | 按 docxtpl 规则重写内建模板（三段式表格循环） |
| 4 | 检索"无结果" | 上游 503/429 被报成"无结果" | 逐源回报真实 HTTP 状态；**新增 CrossRef 源**（实测最稳）并自动容错 |

> 共同教训：**把"失败"如实带出来**。这 4 个里前两个最初都被
> `except Exception: logger.info(...)` 吞成了"列表是空的"，排查时只能靠加探针重跑。

---

## 三、复跑命令

```powershell
# OCR API 备份（无需真 key）
python scripts/test_ocr_api_backup.py

# step2 / step3 工具（合成数据，跑完自动清理）
python scripts/test_step23_tools.py
python scripts/test_step23_tools.py --keep      # 保留产物供人工查看

# 内核侧：确认 skill 与工具数
python scripts/test_kernel_embed.py --offline   # config.assets {'agent':1,'skill':3}
python scripts/test_kernel_embed.py             # mcp.server tools=32

# 外网诊断（区分"网络不通"与"上游限流"）
python scripts/diag_network.py
```

## 四、待办

* OCR API 备份**真正可用**需要 VL 端点（DeepSeek 当前不提供）；
  配好 `MIMW_OCR_API_KEY` + VL 模型后跑 `test_ocr_api_backup.py` 即为真链路。
* `search_papers` 的 Europe PMC 受上游 503 限流影响，已可用 CrossRef 兜住；
  若需要更多全文，可再接入 Unpaywall / PMC OA 子集。
* 尚未把这些工具串进 GUI 的按钮（当前是 agent 可调用）；
  若要"点一下就出图/出稿"，在对应页面加调用即可（工具已就绪）。
