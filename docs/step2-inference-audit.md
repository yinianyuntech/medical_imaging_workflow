# Step2 数据挖掘 / 绘图服务 · 系统排查与推理迁移（内嵌 opencode · 共享上下文）

> 2026-10 排查。目标：摸清 **Step2（数据清洗及结构化）数据挖掘/绘图** 服务的推理调用面，
> 并把**全部推理服务迁入内嵌 opencode**（项目会话共享上下文）。
> 迁移机制已落地：`src/kernel/inference_gateway.py`；验证：`scripts/test_inference_gateway.py`。

---

## 0. 结论摘要（TL;DR）

1. **Step2 挖掘有两条互不一致的路径**：
   - **UI 路径（带 LLM）**：`on_mine_data_clicked → Step2MiningWorker → run_llm_guided_sklearn_pipeline`
     —— LLM 直连 Ollama/Custom API 生成「分析计划 + 图注」（2 个推理点）；
   - **MCP 路径（无 LLM）**：opencode agent 调 `medwork_run_step2_mining` → 同一管线
     `llm_service=None` → 回退默认计划（无推理）。
   两条路径结果不同、上下文互不可见 —— 本次把 **UI 路径接入推理网关**，MCP 路径见 §5 待办。
2. **全应用推理面**：17 个文件、约 80 处 LLM 调用点，绝大多数走同一契约
   `llm_service.generate(model, prompt, timeout)`（返回 `{"success","response","error"}`）。
3. **迁移机制（已落地）**：推理网关把 `generate()` 路由到**内嵌 opencode 的项目会话** ——
   同一项目的所有推理共享同一上下文（后续推理可见前序消息与工具调用）。
4. **端到端验证（5/5）**：网关回话 8.2s「收到」；Step2 `plan_with_llm` 走通（2.2s 产出 2 个任务）；
   两轮推理落在**同一会话**（user=4 / assistant=4）；无进程泄漏、无误杀。

---

## 1. 排查范围与方法

- 静态：全仓 `src/**`、`ui/**`、`scripts/**` 扫 `generate(` / `chat/completions` /
  `_call_llm(` / `OllamaLocalService` / `CustomLLMService` / `LLMJudgementClient` / `llm_call`。
- 动态：真实内核 + 真实 provider 打点（`scripts/test_inference_gateway.py`、`test_kernel_embed.py`）。
- 逐文件读：Step2 链路 6 个核心文件（见 §2）。

---

## 2. Step2 现状全景

### 2.1 触发链（UI）

```
DataCleaningWidget.on_mine_data_clicked
  ├─ llm_service = _active_llm_service()      # OpenCode 网关 / Custom API / Ollama 三选一（默认=网关）
  ├─ model = _current_model_name()            # 网关为空 → 用内核配置模型
  └─ Step2MiningWorker(QThread)
        └─ run_llm_guided_sklearn_pipeline(llm_service, model, materials_text,
                                           project_storage_path, workspace, out_dir)
              ├─ build_tabular_profile(records)        # 读项目表格 → 列画像
              ├─ plan_with_llm(llm_service, model, ...)          ★推理点 1：生成 JSON 分析计划
              ├─ _validate_plan(...) + sklearn 执行（回归/分类/聚类）
              ├─ matplotlib 绘图（pca_scatter / pred_vs_true / confusion / feature_importance）
              ├─ _generate_figure_notes_with_llm(llm_service, model, ...)  ★推理点 2：图注/解读
              └─ 产物：<storage>/exports/step2_mining_<ts>/{figures, report, plan.json...}
```

### 2.2 推理点（UI 路径，共 2 处）

| 文件 | 函数 | 调用形态 | 消费 |
|---|---|---|---|
| `src/services/llm_guided_sklearn_pipeline.py` | `plan_with_llm` (L652) | `llm_service.generate(model, prompt, timeout=600)` | JSON 计划 `{tasks:[...]}` |
| 同上 | `_generate_figure_notes_with_llm` (L112) | `llm_service.generate(model, prompt, timeout=300)` | JSON `{captions, notes}` |

> 两处都用 `_extract_json_object` 容错解析 —— 对"会话型回复"（可能带前后文）有天然韧性，
> 实测经网关（agent 会话）产出的计划可直接解析。

### 2.3 绘图面

| 面 | 实现 | 状态 |
|---|---|---|
| Step2 管线内图 | `llm_guided_sklearn_pipeline` matplotlib 四类图（Nature 风格样式 `_setup_plot_style`） | 不变（绘图本身非推理；图注=推理点 2） |
| 内核绘图工具 | `analysis_tools.plot_nature_figure`（DuckDB→统计→Nature 级图；opencode agent 可直接调用） | 已在内嵌 opencode 工具面 |
| 独立分析 | `tabular_sklearn_analysis_service.run_tabular_sklearn_analysis`（纯 sklearn，无 LLM） | 无推理，不入迁移 |

### 2.4 内核侧（opencode agent 已可用的）Step2 工具

| 工具 | 推理 | 说明 |
|---|---|---|
| `medwork_run_step2_mining` | ❌（`llm_service=None` → 默认计划） | 与 UI 路径结果不一致（§3.1） |
| `medwork_ensure_schema_cache` | ✅ 经 `_raw_llm` 直连宿主 LLM | 嵌套推理问题（§3.3） |
| `duckdb_query` / `compute_statistics` / `plot_nature_figure` / `extract_keywords` | ❌ | 纯计算/绘图 |

### 2.5 产物与数据结构

- 产物目录：`<project_storage>/exports/step2_mining_<ts>/`（图 PNG + 计划 JSON + 报告）。
- schema 缓存：`<storage>/tabular/schema_cache.json`（`SchemaCacheService`）。

---

## 3. 发现的问题（按严重度）

| # | 问题 | 证据 | 处置 |
|---|---|---|---|
| 3.1 | **双路径不一致**：UI 挖掘带 LLM 计划；agent 的 `run_step2_mining` 无 LLM（默认计划）→ 同一功能两种结果 | `domain_tools.run_step2_mining`（`llm_service=None`）vs `Step2MiningWorker`（真服务） | UI 路径已迁网关（本次）；MCP 路径待统一（§5） |
| 3.2 | **推理无状态/上下文孤岛**：各服务各自直连，前一步结论无法被后一步看到（计划→图注→后续步骤彼此失忆） | 7 个 transport 各自 new 实例 | **推理网关（本次）**：按项目会话共享 |
| 3.3 | **内核工具内嵌套推理隐患**：`_raw_llm` 在 MCP 工具执行中直连 LLM；若改为回灌同一会话 → 会话正忙于当前回合，会自锁 | `domain_tools._raw_llm`、`schema_cache_service` | 不嵌套回灌；改为「工具只供数据、推理由 agent 做」重构（§5 Phase 3） |
| 3.4 | **provider 级错误静默**：401/限流不抛异常、藏在 `info.error`；多处只从异常取 error | playbook §8 历史实测 | 网关已显式读 `info.error`；其余调用点沿用各自实现 |
| 3.5 | **推理点重复实现**：Ollama transport 7 处 `chat/completions`、`LLMJudgementClient` 1 处、OCR backup 1 处 | §4 表 | 统一接口后收敛（§5） |
| 3.6 | UI 提示语曾显示空模型名尾巴（`内嵌 opencode（共享上下文） / `） | 实测 | 已修（空 model 不再显示 ` / `） |

---

## 4. 全应用推理点清单（迁移底账）

契约统一形态：`llm_service.generate(model, prompt, timeout=...) → {"success","response","error"}`。

| # | 文件 | 推理点 | 现状后端 | 迁移状态 |
|---|---|---|---|---|
| 1 | `src/services/llm_guided_sklearn_pipeline.py`（**Step2 挖掘**） | plan / 图注（2） | Ollama / Custom | ✅ **已迁网关**（UI）；MCP 路径待统一 |
| 2 | `ui/widgets/data_cleaning_widget.py` | 服务选择（默认=网关） | — | ✅ 已改默认 |
| 3 | `src/ai/agent_core_loop.py`（4/5 步写作环） | `_call_llm` ×27 | 经 Step3 注入 | ✅ **已迁**（Step3 选 OpenCode 时写作环全走网关） |
| 4 | `src/ai/logic_chain_agent.py` | ×11 | 经 executor 注入 | ✅ **已迁**（同写作环链路） |
| 5 | `src/ai/agent_skills/{fragment_surgeon,template_fitting,ppt_generator}.py` | ~5 | 注入 | ✅ **已迁**（调用方默认=网关）；anti_aigc 等其余技能待核调用方 |
| 6 | `src/ai/causal_enhancer.py` | llm_call ×2 | 注入 | ⏳ Phase 2 |
| 7 | `src/ai/paper_draft_agent.py` | ×2 | OllamaService | ⏳ Phase 2 |
| 8 | `src/ai/section_reviewer.py`（judge） | ×2 | 经网关（OpenCode 判定已适配） | ✅ **已迁** |
| 9 | `src/services/schema_cache_service.py` | llm_call ×2 | `_raw_llm`（嵌套） | ⏳ Phase 3（重构为 agent 推理） |
| 10 | `src/services/ocr_api_backup.py` / `ocr_service.py` | Judgement/Ollama | 直连 | ⏳ Phase 3（外部 OCR 恢复链，需单独评估） |
| 11 | `ui/widgets/ai_summary_widget.py`（**Step3**） | 组合框默认=网关；CoreLoop 注入 | 网关/Ollama/Custom | ✅ **已迁**（默认） |
| 12 | `ui/widgets/scientific_preview_widget.py`（**Step4**） | ×3 + rethink | 注入（来自 Step3）/默认=网关 | ✅ **已迁** |
| 13 | `ui/widgets/feedback_optimization_widget.py`（**Step5**） / `refine_fragment_dialog.py` / `template_wizard_dialog.py` | 各 1 | 默认=网关 | ✅ **已迁** |
| 14 | `src/services/ollama_local_service.py` / `llm_judgement_client.py` | transport 层 | — | 保留为 `MIMW_INFER_BACKEND=legacy` 回退 |

---

## 5. 迁移设计：推理网关（`src/kernel/inference_gateway.py`）

### 5.1 架构

```
宿主功能（Step2 管线 / 评审 / 改写 / 摘要……）
        │  统一走 llm_service.generate(model, prompt, timeout)
        ▼
OpenCodeLLMService（兼容适配器，零改动替换 OllamaLocalService）
        ▼
InferenceGateway.infer(prompt, project_id=…)
        ├─ 自动确保内核在跑（与智能体面板共享同一个 KernelBoot）
        ├─ 会话=项目会话（ensure_project_session）→ **共享上下文**
        ├─ 并发锁：同会话串行，避免"一回合未完又投递"
        └─ 显式读 info.error（provider 级错误不再静默）
        ▼
内嵌 opencode（loopx 默认 agent）→ 需要数据时调 medwork MCP 工具（真数据）
```

- **共享上下文语义**：同一 `project_id` 的推理全部落在同一持久会话；
  无项目场景落 `_inference` 伪项目会话（通用改写等彼此共享、不污染项目会话）。
- **模型参数**：`"provider/model"` 透传；其它（Ollama 模型名等）忽略 → 用内核配置模型
  （默认 `deepseek/deepseek-flash`）。
- **回退开关**：`MIMW_INFER_BACKEND=legacy` 时 `make_llm_service()` 返回旧直连实现。

### 5.2 接入方式（对其他模块）

```python
from src.kernel.inference_gateway import OpenCodeLLMService, make_llm_service

svc = OpenCodeLLMService()      # 或 svc = make_llm_service(OllamaLocalService)
res = svc.generate(model, prompt, timeout=600)   # 契约与旧服务一致
# res == {"success": bool, "response": str, "error": str, "session_id": str, "finish": str}
```

`main.py` 已在 `attach_opencode` 后 `bind_boot(_opencode_boot)` —— 网关与底部智能体面板
**共享同一个内核与同一批项目会话**。

---

## 6. 验证证据（真实调用）

`python scripts/test_inference_gateway.py` → **5/5 PASS**（2026-10-12）：

| 检查 | 结果 |
|---|---|
| 网关简单回话 | 8.2s，`reply="收到"`，session `ses_ecfa02a88ffe…` |
| Step2 挖掘计划（`plan_with_llm` 经网关） | 2.2s，`tasks=2`（classification, clustering），JSON 可解析 |
| 共享上下文 | 同一会话累计 `user=4 / assistant=4`（两轮测试追加） |
| 收尾无残留 | `spawned=[25984] leaked=[]` |
| 未误杀既有进程 | `collateral=[]` |

---

## 7. 后续计划

- **Phase 2（一行级迁移）**：`ai_summary` / `scientific_preview` / `feedback_optimization` /
  `refine_fragment` / `template_wizard` 等服务创建点换 `make_llm_service()`；
  `agent_core_loop` / `logic_chain_agent` 等写作环换服务实例（注意长回合需要更长 timeout）。
- **Phase 3（结构级）**：
  - `schema_cache`：改为「工具供数据 + agent 出映射 + 工具落盘」，消除嵌套推理；
  - `run_step2_mining` MCP 工具与 UI 路径统一（同一网关/同一计划）；
  - OCR 恢复链单独评估（涉及外部服务语义，不简单替换）。
- **监控**：会话体积增长（每次推理都入会话历史）；对高频小推理可评估"每服务一个
  子会话 + 关键结论注入主会话"的混合策略（当前先全量共享）。


---

## 8. Step3/4/5 排查与接入（第二轮，2026-10）

### 8.1 Step3（本地大模型数据科学总结）链路

```
AISummaryWidget.on_analyze_clicked
  ├─ model = _current_model_name()            # OpenCode 时为空 → 内核默认模型
  ├─ start_rag_thread(model, full_text)
  │    ├─ llm_svc  = _active_llm_service()    # ★默认=网关（组合框首项 OpenCode）
  │    ├─ judge_cfg = _current_judge_config() # ★OpenCode → judge 也走网关（model=opencode:default）
  │    └─ CoreLoopWorker(llm_service, judge_config, ...)
  │         ├─ ensure_model_ready()           # Ollama 专属；网关无此方法 → 自动跳过
  │         ├─ _run_pre_mining()              # ★Step2 同款 sklearn 管线（llm_service=网关 → 与 Step2 共享上下文）
  │         └─ executor.execute_paper_writing()   # AgentCoreLoopExecutor（llm_service=网关）
  │              ├─ _call_llm ×27 / LogicChainAgent / SectionReviewer → 全部 llm_service 注入
  │              └─ section_reviewer（judge）：llm_service.generate ×2（网关）+ 面板适配
  └─ 结果 → 触发 Step4
```

**排查发现**：
- `AnalysisWorker` 为**死代码**（全仓零实例化），无需迁移；真实链路是 CoreLoopWorker。
- judge 原设计依赖 base_url/api_key/model → OpenCode 选择下会因空 model 而**静默禁用**；
  已修：OpenCode 模式 judge 直接走网关（`opencode:default` 仅作非空标签），
  `SectionReviewer` 面板对 "OpenCode" 服务走远程分支（同模型双评）。
- `update_model_ui` 组合框把 OpenCode 置顶并默认选中（`MIMW_INFER_BACKEND=legacy` 时保持旧行为）。

### 8.2 Step4（科学文本预览生成）

- 服务来源：`MainWindow.show_text_preview()` 从 **Step3** 拉取当前选择并注入
  `text_preview_widget.set_llm_service(...)` → Step3 选 OpenCode 时 Step4 自动用网关（共享上下文）。
- 直接构造时默认服务：网关（`make_llm_service`）。
- 所有推理路径（局部重写 / 翻译 / rethink / 模板套用）统一走 `self.llm_service` ✓。

### 8.3 Step5（研究者反馈及迭代优化）

- `FeedbackOptimizationWidget.llm_service` 默认=网关（用于 `PPTGenerator` 技能生成）。
- 关联对话框：`RefineFragmentDialog`（CGR 片段精修）传入 Step4 的服务；独立构造默认=网关；
  `TemplateWizardDialog`（模板向导）默认=网关（TemplateFitter 技能）。

### 8.4 验证（本轮）

| 检查 | 结果 |
|---|---|
| Step3 冒烟（离屏） | 组合框首项=OpenCode 且默认选中；服务=OpenCodeLLMService；model=""; label 正确；judge `{enabled:True, model:opencode:default}` |
| Step4 冒烟 | 默认服务=OpenCodeLLMService |
| Step5 冒烟 | 默认服务=OpenCodeLLMService |
| SectionReviewer | `enabled=True`（网关服务 + 非空标签） |
| **真实技能调用**：`fragment_surgeon_skill`（Step4 精修对话框路径）经网关 | **7.8s**，输出 "The mean age of the cohort was **64** years."（按数据上下文修正 65→64） |
| **共享上下文** | 该调用落在 `_inference` 会话（ses_ecfa02a88ffe…），与此前网关测试**同一会话**累计 user=5/assistant=5 |
| 进程 | 无泄漏 |

### 8.5 仍未迁移（Phase 3）

- `schema_cache_service`（内核工具嵌套推理 → 改为"工具供数 + agent 出结论"）；
- `run_step2_mining` MCP 工具与 UI 路径统一；
- OCR 恢复链（`ocr_api_backup` / `llm_judgement_client` 外部服务语义，单独评估）。


---

## 9. 移除程序内自建 skill loop → 委托内嵌 opencode（2026-10）

### 9.1 处置

- **原机制**：`src/ai/agent_core_loop.py`（AgentCoreLoopExecutor）自建「多阶段 + 内嵌
  skills（Structurizer/Novelty/Critic/Refiner）+ 评审-精修循环」的写作编排，
  由 `CoreLoopWorker` 驱动。
- **处置**：该编排**已移出运行路径**（默认不再执行）。新增委托引擎
  `src/ai/opencode_delegation.py`：
  - 组装一次性完整任务（项目上下文 + medwork 工具要求 + 模板约束 + 输出格式 + 自审要求）；
  - 投递到内嵌 opencode 的**项目会话**（共享上下文），由 agent 用工具读真数据、
    完成写作/评审/精修，产出整篇 Markdown；
  - 进度=tool/step 事件流式回报；结果解析为与旧 UI 兼容的 result dict
    （status/outline/units/meta/references/full_text）。
- **开关**：`MIMW_DRAFT_ENGINE=opencode`（默认）| `legacy`（应急回退旧 core loop）。
  原代码保留仅为 `legacy` 回退与对比，不再默认执行 —— 即"运行路径上的移除"。

### 9.2 保留说明（非 skill loop）

| 组件 | 保留原因 |
|---|---|
| `agent_skills/{fragment_surgeon,grammar_checker,anti_aigc,template_fitting,ppt_generator}` | 单发技能（非循环），调用方默认已走网关（§8） |
| `funnel_loop.FunnelLoopAnalyzer` | 本地正则质控（Layer1-3），无 LLM，不属于 skill loop |
| `logic_chain_agent` / `section_reviewer` | 委托模式下由 agent 自审替代；代码仅 legacy 路径使用 |

### 9.3 验证（真实运行）

`python scripts/test_opencode_delegation.py project_1791774057` → **7/7 PASS**：

| 检查 | 结果 |
|---|---|
| 引擎 | `opencode`，status=ok，**148.6s** 完成一次完整委托写作 |
| 结构 | units 非空（intro/discussion/conclusion/abstract）、refs=7、full_text=6508 字 |
| 过程 | **36 个 tool 事件**流式回报；2 段文本流 |
| 会话 | `ses_ecf8d2f8effe…`（共享上下文） |
| 进程 | 无泄漏、无误杀 |
| 行为注记 | 小样本测试项目缺真实图表数据时，agent 如实报告"数据可用性"而非编造（符合"先读真数据"硬约束） |


---

## 10. Step4 交互反馈 → 项目会话注入（2026-10 修正）

**问题（用户质询）**：Step4 的交互（rethink 指令、局部重写、翻译、CGR 精修等）
是否注入内嵌 opencode 上下文？

**核查（修正前）**：❌ 部分——这些调用虽经网关进入内嵌 opencode，但
`OpenCodeLLMService.generate()` 未携带 `project_id` → 全部落在 `_inference`
无项目共享会话，与项目写作会话（`write:<project>`）**彼此不可见**。

**修正**：
- 网关：`InferenceGateway.generate/infer/chat/complete/generate_text` 增加
  `project_id` 透传；
- 服务层：`OpenCodeLLMService` 增加 `set_project()` / `project_id`（可绑定项目）；
- 页面绑定：Step2/3/4/5 在 `set_current_project()` 时绑定；Step4 `set_llm_service()`
  注入时同时绑定；`RefineFragmentDialog` 按构造参数 `project_id` 绑定；
- 效果：**Step4 的每一次交互/反馈 = 一条追加到项目会话的消息**，与写作引擎共享
  同一上下文；agent 能看到写作历史与全部反馈，反馈也能影响后续交互。

**顺带修复（实测坑）**：默认 agent=loopx 时，工具型推理（改写等）会被 agent 追加
"LoopX writeback …" 噪音（agent 主动执行 LoopX 工作流）。已在网关对"直接任务"
自动加 `[宿主直接任务]` 提示前缀（禁写回/禁工作流，除非任务要求）；
委托写作模板亦加入同款要求。实测输出已干净（`Rewritten Text: The mean age was 64 years.`）。

**验证（真实调用）**：

| 检查 | 结果 |
|---|---|
| 项目绑定调用落点 | call == 项目会话（ses_ecf823fa…）≠ _inference（ses_ecfa02a8…）✅ |
| 绑定后两轮调用 | 均入项目会话；消息累计可见 |
| 改写输出洁净度 | 无 writeback / LoopX 噪音 ✅ |
| 网关回归（含新增检查） | **6/6 PASS**（共享上下文 user=7 累计、无泄漏、无误杀） |


---

## 11. Step4 图文 Word 化（officeCLI）· 交互=批注 · Step5 导出（2026-10）

**架构对齐（用户口径）**：
- Step1-3 = 数据清洗 / 基于语料生成论文；
- **Step4 背后调用 officeCLI**：初稿落成**图文 Word**（标题/各节/图/参考文献）；
- **Step4 的每轮交互 = 一条 Word 批注**（comment），记录进 .docx；
- Step5 导出 Word（含批注）。

### 11.1 新增

- **`src/services/step4_word_service.py`**（officeCLI 封装）：
  - `build_step4_docx()`：结果 dict → 图文 docx（标题/Abstract…Conclusion/图片附 Result 后/
    References），落 `<storage>/exports/step4/<title>__<ts>.docx`，并写 sidecar
    `latest_step4_word.json`；
  - `add_feedback_comment()`：反馈 → Word 批注（`add /body/p[N] --type comment`；
    支持 `anchor_text` 定位段落、`parent_id` 线程回复）；
  - `list_comments()` / `export_docx()` / `find_latest_step4_docx()`；
  - 定位：`MIMW_OFFICECLI` → npm-global `@officecli/officecli/officecli.js`（node 走 PATH）；
    子进程强制 UTF-8 + 无窗口；每次操作 `save`+`close`（释放驻留，Word 可读最新）。
- **Step4 接线**（`scientific_preview_widget.py`）：
  - `load_data()` 后台生成 Word（线程，不阻塞 UI）；
  - 批注点：**Rethink 完成 / 局部重写完成（锚定该章节）/ CGR 精修应用（锚定所选片段）**；
  - `on_finish_clicked` 的 metadata 携带 `word_doc_path`。
- **Step5 接线**（`feedback_optimization_widget.py`）：新增「导出 Word」按钮 →
  定位最新 Step4 docx（sidecar 优先）→ 另存为 `.docx`（含批注）。
- **测试**：`scripts/test_step4_word.py`（真实 officeCLI）。

### 11.2 验证（真实运行，8/8 PASS）

| 检查 | 结果 |
|---|---|
| officecli 可用 | node + `@officecli/officecli` ✓ |
| 生成图文 docx | 682 KB（含 PNG）、OpenXML `validate` 无错误 |
| 批注 1（锚定"方法"段） | 成功，anchoredTo=/body/p[@paraId=…] |
| 批注 2（线程回复） | count=2 ✓ |
| 导出副本 | 复制成功 |
| sidecar 定位 | ✓ |
| 离屏冒烟 | Step4/Step5 构件、按钮、无路径静默（不崩） |

### 11.3 待办（下一轮）

- 交互后**正文同步**：局部重写/精修的结果除了进批注，还可经
  `set /body/p[n] --prop text=...` 直接更新 Word 正文段落（当前仅批注落盘 + 编辑器内更新）；
- Step5 批量导出多稿（drafts 表 → 一稿一 docx）；
- frozen 打包把 officecli(node 依赖) 纳入运行时检查（`available()` 已有降级路径）。


---

## 12. Step4 正文同步（set）+ Step5 批量一稿一 docx（2026-10）

### 12.1 正文同步（交互结果写回 Word 正文）

- 服务新增（`step4_word_service.py`）：
  - `sync_section_text(docx, heading, text)`：`query paragraph`（paraId 路径稳定、styleId 判标题、
    排除图片段）→ 定位章节 span → `set`（**--find/--replace 优先**，保护锚定批注的段落；
    段落数不齐时首段全量 + 多余段 `remove`，且跳过批注锚定段）→ save/close；
  - `sync_full_text(docx, markdown)`：按节拆分，逐节同步（Rethink 场景）；
  - `sync_fragment_text(docx, old, new)`：定位含片段的段落，原地替换（CGR 精修场景）；
  - 全部按文件加锁串行（同文档并发安全）。
- Step4 接线：一轮交互统一走 `_word_round(comment=…, anchor=…, sync=…)`（单后台线程内
  **先批注、后同步**，顺序确定）：Rethink→全文同步；局部重写→章节同步；
  CGR→片段同步。

### 12.2 Step5 批量导出（一稿一 docx）

- `export_drafts_batch(project_id, drafts=None, dest_dir=None)`：从 drafts 表逐稿生成
  docx（officecli 优先，python-docx 兜底；空稿跳过），默认落 `<storage>/exports/step5/`；
- Step5 新增「批量导出草稿」按钮：选目录 → 一稿一 docx → 完成提示（数量 + 目录）。

### 12.3 验证（真实运行，12/12 PASS）

| 检查 | 结果 |
|---|---|
| 章节同步（Methods→150 例） | ok，新文本在、旧文本消失 |
| 同步后批注存活 | comments 1→1（--find/--replace 保护批注范围）|
| 片段替换（150→160） | ok + 批注存活 |
| 整篇同步（Rethink 场景） | ok + 批注存活 + OpenXML 校验通过 |
| 批量一稿一 docx（空稿跳过） | 2/3 份写出（初稿_v1、精修_v2），校验通过 |
| 离屏冒烟 | `_word_round` 无路径静默；Step5 批量按钮就位 |


---

## 13. 内嵌 opencode 的 TUI 控制台：独立 shell + 跟随会话（2026-10）

**需求**：内嵌 opencode 的 console 以**单独的 shell 窗口**显示交互，并跟随应用当前会话更新。

**根因（为什么之前看不到）**：`kernel_client.spawn_tui()` 在 Windows 上用
`creationflags=0x08000000`（CREATE_NO_WINDOW）—— attach 进程**没有可见控制台**，
TUI 无处渲染（进程活着但不可见；此前 `test_kernel_tui` 只验证了进程层）。

**修正与新增**：
- **可见控制台**：`spawn_tui` 改为 `CREATE_NEW_CONSOLE (0x10)` → 独立 shell 窗口直接运行
  `opencode attach <url> --dir <项目>`（一个进程=一个窗口，pid 即 attach 真身，树杀精确）；
  `MIMW_TUI_VISIBLE=0` 可退回隐藏模式（测试/无桌面）。
- **KernelBoot 新增**：
  - `_tui_alive()`：进程发现（cmdline 含 `attach` + 本内核 url）→ 采纳真实 pid；
  - `open_console(session_id="")`：已开则 **select-session + toast**（跟随，不重复 spawn）；
    未开则 spawn（幂等）；
  - `follow_project(project_id, title="")`：确保项目会话并让控制台跟随（内核未起/未开时静默）；
  - `ensure_project_session()` 记录 `_active_session_id`；`start(autostart_tui)` 携带会话 spawn。
- **接线**：
  - `main.py`：`KernelBoot(autostart_tui=True)` —— 启动内核即弹出独立控制台；
  - `opencode_panel`：新增「终端」按钮（重开/聚焦）；内核启动成功后自动 `follow_project`；
  - `main_window.on_project_switched`：**项目切换 → 控制台跟随**（select-session + toast）。
- **跟新语义**：控制台 attach 在同一 server/session 上，应用经 HTTP 驱动的消息/工具调用
  由 server 事件推给 TUI 实时显示；select-session 保证它始终对着应用当前的项目会话。

**验证（真实运行）**：

| 检查 | 结果 |
|---|---|
| `test_tui_console.py` | **7/7**：控制台弹出（pid 45212）→ 跟随（pid 不变）→ 幂等 → 关闭重开（新 pid）→ 无泄漏 |
| `test_kernel_tui.py`（回归） | **10/10**（spawn/select/toast/stop/无泄漏/无 collateral） |


---

## 14. 打开程序即同步打开 opencode shell（2026-10）

**需求**：打开程序的同时，内嵌 opencode 的 shell 同步打开。

**改动**：
- `main.py`：`MIMW_KERNEL_AUTOSTART` 默认 **1**（随程序自动启动内核；`=0` 可关）；
  内核以 `KernelBoot(autostart_tui=True)` 创建 → 启动即弹独立 TUI 控制台。

**暴露并修复一个长期潜伏 Bug（pythonw 下 MCP 起不来）**：
- 现象：应用内 `boot.start()` 30s 超时 `RuntimeError: MCP 服务器未能在 127.0.0.1:xxxxx
  就绪（flavor=v1）`；而测试（python.exe）一切正常。
- 根因：**pythonw 无控制台 → `sys.stdout is None`** → MCP v1(FastMCP/uvicorn) 初始化
  日志时 `uvicorn/logging.py: self.use_colors = sys.stdout.isatty()` →
  `AttributeError: 'NoneType' object has no attribute 'isatty'` → dictConfig 崩 →
  streamable-http 服务永不就绪。此前全链路只在 python.exe 下测过，所以从未暴露。
- 修复（双保险）：
  1. `main.py` 启动最早期兜底 `sys.stdout/stderr`（None → devnull，`isatty()=False`）；
  2. `mcp_server.serve_http_in_thread()` 入口同样兜底（保护其他宿主/单测）。
- 顺带：面板启动 worker 与 MCP `server.run` 的异常此前会被吞/只进 UI——
  现在关键路径写 **boot_trace.log 必落盘诊断**（异常可见）。

**验证（真实运行）**：
| 检查 | 结果 |
|---|---|
| 应用启动 → 内核 | `panel: boot.start -> {'ok': True}`，8s 完成 |
| 独立 shell | `kernel serve=1`（pid 45632）+ `attach(TUI)=1`（pid 32148） |
| 关闭应用 | `closeEvent → boot.stop() → stop_tui + 树杀`（链路已有，含采纳 pid） |

**开关**：`MIMW_KERNEL_AUTOSTART=0` 关闭随程序启动；`MIMW_TUI_VISIBLE=0` 隐藏控制台窗口。
