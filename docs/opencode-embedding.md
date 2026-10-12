# opencode 内嵌开发（MCP Bridge）· 实施说明

> 本文件记录本仓库按照 `opencode-embedding-playbook.md` 落地 opencode 内嵌的实现、
> 契约、开关与自检方式。代码位于 `src/kernel/`。

---

## 1. 架构（四方向）

| 方向 | 关系 | 协议 | 谁主动 | 落点 |
|---|---|---|---|---|
| **A** | 宿主作为 opencode 的 MCP 工具服务 | MCP (streamable-http) | 内核 | `src/kernel/mcp_server.py` + `tools/` |
| **B** | 宿主驱动内核（会话/投递/问答/权限） | HTTP legacy V1 | 宿主 | `kernel_client.py` + `kernel_driver.py` |
| **C** | 外部 agent 复用同一 MCP 工具面 | MCP | 外部 | 同 A |
| **D** | 宿主托管内核进程 | 子进程 | 宿主 | `kernel_client.spawn/adopt/stop` |

铁律：**opencode 只做 MCP 客户端，永不提供 MCP 服务端**；内核的 function calling
必须走原生 provider（本项目 = `deepseek/deepseek-flash`），宿主自己的 Ollama 只能作为
`llm_chat` 工具暴露。

---

## 2. 文件清单

| 文件 | 职责 |
|---|---|
| `src/kernel/kernel_paths.py` | 隔离 home、opencode.exe 查找（含 1.x 优先）、状态文件、`kernel_env()` |
| `src/kernel/kernel_config.py` | `opencode.json`(mcp)、`auth.json`、项目↔会话绑定、随包资产安装 |
| `src/kernel/kernel_client.py` | 进程托管 + legacy V1 HTTP + 问答/权限 + TUI + `mcp_list` |
| `src/kernel/kernel_driver.py` | `run_turn`、事件归一化、消息轮询、问答/权限回灌 |
| `src/kernel/kernel_boot.py` | 总控：起 MCP → 注册 → 起内核 → 校验 connected → 绑会话 |
| `src/kernel/inference_gateway.py` | **推理网关**：全部推理统一路由到内嵌 opencode 项目会话（共享上下文） |
| `src/kernel/mcp_server.py` | FastMCP 服务 + 工具注册 |
| `src/kernel/tools/ui_bridge.py` | Qt 信号桥（后台线程 → 主线程），含阻塞式 `ask()` |
| `src/kernel/tools/domain_tools.py` | 23 个领域工具 |
| `src/kernel/kernel_assets/` | `agent/loopx.md`（**默认 agent**）、`agent/medical-workflow.md`、`skill/{data-analysis,literature-to-docx,paper-pipeline}/SKILL.md` |
| `ui/widgets/opencode_panel.py` | MainWindow 底部「智能体」栏 |
| `scripts/test_kernel_embed.py` | 全链路自检 |
| `scripts/test_inference_gateway.py` | 推理网关自检（网关回话 / Step2 计划 / 共享会话） |

---

## 3. 契约（实测）

### 启动顺序（**不可调换**）

```
1) 起宿主 FastMCP（后台线程）            -> http://127.0.0.1:<port>/mcp
2) 先写 opencode.json 注册 MCP           <- 必须早于内核启动
3) 安装 agent/skill 资产 + 导入 auth.json
4) client.ensure_running()（adopt 优先）
5) 校验 mcp list 含 medwork，否则重启内核
```

### 端点（legacy V1，v1.19.0 实测通过）

| 目的 | 方法 + 路径 |
|---|---|
| 健康 | `GET /global/health` |
| 建会话 | `POST /session` |
| 阻塞投递 | `POST /session/:id/message` |
| 列消息 | `GET /session/:id/message` |
| 改标题 | `PATCH /session/:id` |
| 中断 | `POST /session/:id/abort` |
| 待决问题 | `GET /question` → `POST /question/:id/reply` |
| 待决权限 | `GET /permission` → `POST /permission/:id/reply` |
| TUI 切会话 | `POST /tui/select-session` |
| TUI 提示 | `POST /tui/show-toast` |

**实测结论（本机）**：`/global/health`、`/session`、`/question`、`/permission`
在 **opencode 1.19.0 / 1.18.35** 上全部可用；`api_family=legacy-v1`。
**2026-10 复验**：真实对话回合 FULL_TURN_OK（`deepseek/deepseek-flash` 4.16s 回话），
宿主凭据自动导入（见 §6）。

### 默认 agent：`loopx`（实测）

- 资产：`kernel_assets/agent/loopx.md`（`mode: primary`）。启动时
  `install_builtin_assets()` 装进隔离 home 的 `config/opencode/agent/`；
  `ensure_default_agent()` 把 `"default_agent": "loopx"` 写进 `opencode.json`。
- opencode 1.18 二进制级校验：`default_agent` 目标必须存在、`mode=primary`、非 hidden，
  否则报 `default agent "X" not found` —— 所以**安装必须先于写配置**。
- 实测证据：`GET /config` → `default_agent:"loopx"`；`GET /agent` 含 `loopx (primary)`；
  `opencode agent list` 列出 `loopx (primary)`；V1 建会话显式 `agent:"loopx"` 回显一致；
  自检 `kernel.agent_default` PASS。
- 会话绑定：`kernel_boot.ensure_project_session()` 给新会话显式传
  `agent=kc.default_agent_name()`（`MIMW_KERNEL_AGENT` 可覆盖）。
- 同步义务：随包 `loopx.md` 是 `~/.config/opencode/agents/loopx.md` 的拷贝；
  loopx 定义升级后需同步该拷贝，保持内嵌默认 agent 与全局一致。

### 推理网关：全部推理转入内嵌 opencode（共享上下文）

- 模块：`src/kernel/inference_gateway.py`。宿主所有推理统一走
  `llm_service.generate(model, prompt, timeout=...)` 兼容契约（返回
  `{"success","response","error","session_id","finish"}`），可零改动替换
  `OllamaLocalService`。
- 路由：`InferenceGateway.infer()` → **项目会话**（`ensure_project_session`）→ 内嵌
  opencode（loopx 默认 agent）→ 需要数据时先调 medwork MCP 工具。
  同一项目的所有推理**共享同一上下文**；无项目场景落 `_inference` 伪项目会话。
- 绑定：`main.py` 在 `attach_opencode` 后调用 `bind_boot(_opencode_boot)` ——
  网关与底部智能体面板共享同一内核与会话。
- 开工时自动确保内核在跑（与面板同一个 `KernelBoot`）；同会话并发加锁串行；
  provider 级错误显式从 `info.error` 读取（不静默）。
- **Step2/3/4/5 均已接入**：Step2 挖掘、Step3 总结（含写作环与 judge）、Step4 预览、
  Step5 反馈的默认选择=网关；写作环经 CoreLoopWorker 注入；judge 走网关。
- **写作默认=委托引擎**（`src/ai/opencode_delegation.py`）：原程序内自建 skill loop
  （`agent_core_loop` 的编排 + 内嵌 skills + 评审循环）**已移出运行路径**，整篇写作/
  评审/精修委托给内嵌 opencode 会话（`MIMW_DRAFT_ENGINE=legacy` 可应急回退）。
  迁移底账与计划见 `docs/step2-inference-audit.md`。

### 版本要求

- 本嵌入按 **legacy V1** 契约实现，**要求内核 1.x**。
- `kernel_paths.opencode_exe(prefer_major=1)` 会主动跳过 2.x。
- 机器上同时装了 1.x 与 2.x 时，请用 `MIMW_OPENCODE_EXE` 显式指定 1.x。

---

## 4. 环境变量开关

| 变量 | 作用 | 默认 |
|---|---|---|
| `MIMW_KERNEL_AUTOSTART` | 随 GUI 自动启动内核 + 独立 TUI 控制台 | `1`（`=0` 可关） |
| `MIMW_KERNEL_HOME` | 隔离 home | `%LOCALAPPDATA%/MedicalImagingWorkflow/kernel` |
| `MIMW_OPENCODE_EXE` | 指定内核二进制 | 自动查找（1.x 优先） |
| `MIMW_KERNEL_MODEL` | 内核模型 | `deepseek/deepseek-flash` |
| `MIMW_KERNEL_AGENT` | 覆盖默认 agent | `loopx` |
| `MIMW_INFER_BACKEND` | 推理后端：`opencode`（网关）/ `legacy`（旧直连） | `opencode` |
| `MIMW_TUI_VISIBLE` | TUI 控制台可见性（独立 shell 窗口） | `1`（`=0` 隐藏） |
| `MIMW_DRAFT_ENGINE` | 写作引擎：`opencode`（委托内嵌 opencode）/ `legacy`（旧 core loop） | `opencode` |
| `MIMW_LLM_API_KEY` / `MIMW_LLM_PROVIDER` | 直接提供内核凭据 | — |
| `MIMW_LLM_PROFILE` | 从宿主 profile 里选一个 | 第一个有 key 的 |
| `MIMW_KERNEL_VERIFY_MCP` | 启动后校验 MCP 连接 | `1` |
| `MIMW_DRIVER` | `host` / `opencode` | `host` |

> ⚠️ XDG/OPENCODE 环境变量在 opencode 模块加载时求值，**运行中改无效** → 需重启内核。

---

## 5. MCP 工具面（23 个）

**只读**：`list_projects` `get_project` `project_summary` `list_samples`
`list_storage_files` `read_tabular` `get_schema_cache` `aggregate_project`
`list_dicom_sessions` `list_ocr_results` `list_documents`

**计算**：`run_step2_mining` `ensure_schema_cache` `save_draft` `export_drafts_to_word`

**破坏性（权限确认门）**：`create_project` `purge_project` `delete_sample`
→ 未注册确认钩子时**默认拒绝**；被拒绝时 agent 不应重试。

**LLM**：`llm_chat`（宿主 Ollama/自定义 API，内核不依赖它做 function calling）

**界面**（仅 emit 信号）：`gui_status` `gui_toast` `gui_navigate` `gui_log`

统一返回信封：`{"ok": true, "data": ...}` / `{"ok": false, "error": "..."}`。

---

## 6. 运行

```powershell
# 1) 依赖
pip install -r requirements.txt            # 含 mcp>=1.2.0

# 2) 内核二进制（172MB，不随仓库分发）
#    放到 <app_home>/opencode/opencode.exe，或设 MIMW_OPENCODE_EXE

# 3) 凭据（启动时自动导入，按候选路径顺序找 custom_api_profiles.json）：
#      COCO_DATA_DIR/custom_api_profiles.json
#      <app_home>/config/custom_api_profiles.json          （旧位置，兼容）
#      <app_home>/coco_data/custom_api_profiles.json       （宿主主位置；dev=仓库/coco_data）
#      %LOCALAPPDATA%/MedicalImagingWorkflow/coco_data/custom_api_profiles.json（冻结版写入）
#    provider 由 base_url/name 推断（api.deepseek.com → deepseek）。
#    也可手动：python -m src.kernel.kernel_cli import-key --provider deepseek --key sk-xxx

# 4) 自检
python scripts/test_kernel_embed.py --offline   # 静态
python scripts/test_kernel_embed.py             # 全链路（起内核）
python scripts/test_kernel_embed.py --prompt    # 追加真实对话

# 5) GUI
python main.py        # 底部「OPENCODE 智能体」栏 → 启动内核 → 展开 → 输入任务
```

---

## 7. 打包（PyInstaller）

在 `MedicalImagingWorkflow.spec` 中：

- `datas` 增加：
  - `opencode/opencode.exe` → 目标 `opencode`
  - `src/kernel/kernel_assets` → 目标 `kernel_assets`
- `hiddenimports` 增加：
  `src.kernel.kernel_paths`、`kernel_config`、`kernel_client`、`kernel_driver`、
  `kernel_boot`、`mcp_server`、`tools.domain_tools`、`tools.ui_bridge`
- **禁用 onefile**（内核会锁 `%TEMP%` 解包目录 → 主进程退出挂死）；只出 onedir。
- 打包后自检：`python -m src.kernel.kernel_cli selftest` 应 `ok=true`。

---

## 8. 已知限制

1. 仅针对 legacy V1 契约（1.x）；2.x 需另做 V2 面适配。
2. TUI attach 在装有 Windows Terminal 的机器上，`Popen.pid` 可能是 `wt.exe`；
   `spawn_tui` 已用**进程发现**取真实 attach pid。
3. `mcp_list` 等子进程输出已强制 UTF-8 解码（GBK 控制台会崩）。
4. 破坏性工具默认拒绝，需宿主注入确认钩子（`_common.set_confirm_hook`）。
5. `gui_status` 只返回主线程推入的快照，**绝不含 HTTP 密码**。


---

## 随包 loopx CLI（V2.0）

内嵌 openCode 的默认 agent（loopx）用 loopx 命令驱动 LoopX 控制平面。V2.0 起
**loopx CLI 随应用打包分发**，无需目标机单独安装：

- 构建：用 PyInstaller 在最小 venv（pillow/defusedxml/mcp）中对 loopx.entrypoint:main
  构建独立 loopx.exe（onedir，约 94 MB），产物放入 ssets/loopx/（二进制不入库，
  随 release 分发；完整版 spec 经 	ree_datas("assets") 自动收集）；
- 定位：kernel_paths.loopx_exe()：MIMW_LOOPX_EXE → 随包 ssets/loopx/loopx.exe
  （冻结=_MEIPASS）→ <app_home>/loopx/ → PATH；
- 注入：kernel_env() 把 loopx 目录**前置**到内核 PATH —— 内嵌 openCode 的 agent
  直接运行 loopx ... 即命中随包版本；
- 技能：loopx* 全套技能（13 个）已并入 kernel_assets/skill/，随内核安装进
  隔离 home（与 loopx agent 定义配套）。
