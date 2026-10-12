"""
opencode 内嵌开发内核包（见仓库根 `opencode-embedding-playbook.md`）。

四个方向：
  A  宿主作为 opencode 的 MCP 工具服务（内核 -> 宿主，MCP）
  B  宿主驱动内核（宿主 -> 内核，HTTP legacy V1）
  C  外部 agent 复用同一 MCP 工具面
  D  宿主托管内核进程（子进程）

模块：
  kernel_paths   隔离 home / opencode.exe 查找 / 资产根 / 状态文件 / 环境变量
  kernel_config  opencode.json(mcp) / auth.json / 项目<->会话绑定 / 随包资产安装
  kernel_client  进程托管 + legacy V1 HTTP + 问答/权限 + TUI
  kernel_driver  事件归一化 + run_turn + 轮询
  kernel_boot    GUI 总控（启动即拉起内核 + 注册 MCP + 绑会话）
  mcp_server     宿主 FastMCP（streamable-http）工具面
"""

__all__ = [
    "kernel_paths",
    "kernel_config",
    "kernel_client",
    "kernel_driver",
    "kernel_boot",
]
