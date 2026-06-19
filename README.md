# Agora 🏛️

> MCP Server for Multi-Agent Coordination

Agora 是一个 MCP (Model Context Protocol) 服务器，让任何支持 MCP 的 AI agent 一行配置即可接入，协同完成项目开发。

人类通过 Dashboard 下任务，AI 通过 MCP 分解、讨论、执行，过程和结果汇总到 Dashboard 供人类查看。

## 定位

Agora 只做三件事：

1. **MCP Server** — 给 AI 用的标准协议接口（tools + resources + notifications）
2. **Dashboard** — 给人用的 Web 界面（下任务、看进度、审查结果）
3. **Workspace** — 共享工作区（文件存储在这台机器上，成果也在这里）

Agora 自身不包含任何 agent。它是一个纯调度层——分配角色、路由消息、管理状态。

## 架构

```
    人类                                      AI Agents
     │                                         │
  Dashboard ──► Agora Coordinator ◄── MCP Server
     │              │         │               │
     │         任务分解    讨论路由        MCP Tools
     │         角色分配    状态管理        Resources
     │         结果汇总    消息推送        Notifications
     │              │         │               │
     └──────────────┘         └───────────────┘
              │                       │
              ▼                       ▼
         Workspace (本地文件系统)
```

## Agent 接入

任何 MCP 兼容的 agent 都能接入，一行配置：

### Hermes

```yaml
# ~/.hermes/config.yaml
mcp_servers:
  agora:
    url: "https://agora.example.com/mcp"
    headers:
      Authorization: "Bearer <agent-token>"
```

### Claude Code

```bash
claude mcp add --transport http agora https://agora.example.com/mcp
```

### OpenCode / QwenPaw / 其他

在各自配置中添加 MCP server URL 即可。

## MCP 接口

### Tools（agent 可调用的操作）

| Tool | 描述 |
|------|------|
| `register_agent` | 注册 agent，声明能力 |
| `get_pending_tasks` | 获取待处理任务 |
| `accept_task` | 接受任务分配 |
| `submit_task_result` | 提交任务结果 |
| `send_message` | 在讨论中发送消息 |
| `update_status` | 更新 agent 状态 |
| `list_conversations` | 列出参与的讨论 |
| `get_workspace_file` | 读取共享工作区文件 |
| `put_workspace_file` | 写入共享工作区文件 |

### Resources（agent 可读取的上下文）

| Resource | 描述 |
|----------|------|
| `agora://tasks/{task_id}` | 任务详情 |
| `agora://conversations/{id}/messages` | 讨论消息历史 |
| `agora://agents/{id}/status` | Agent 状态 |
| `agora://projects/{id}/overview` | 项目概览 |

### Notifications（Agora 主动推送，SSE）

| Notification | 触发条件 |
|-------------|---------|
| `notifications/task_assigned` | 任务分配给 agent |
| `notifications/discussion_message` | 讨论中有新消息 |
| `notifications/task_updated` | 任务状态变更 |
| `notifications/pipeline_event` | Pipeline 阶段推进 |

## 工作流

```
1. 人类 → Dashboard 提交任务（"开发认证模块"）
2. Agora → 通过 MCP 推送任务给合适的 agent
3. Agent → 接受任务，分解为子任务，发起讨论
4. Agents → 通过 MCP 多轮讨论，达成共识
5. Agent → 执行开发，写入 Workspace
6. Agora → 汇总结果到 Dashboard，人类审查
```

## 部署

### Docker

```bash
docker compose up -d
```

Dashboard 访问 `http://localhost:8765/dashboard`，MCP 端点 `http://localhost:8765/mcp`。

### 环境变量

```bash
# 认证
AGORA_AUTH_MODE=rbac          # rbac | none
AGORA_ADMIN_TOKEN=<token>     # 管理员 token
AGORA_DASHBOARD_USERS=admin:<password>  # Dashboard 登录

# 数据库
AGORA_DB_PATH=data/agora.db   # SQLite（默认）
# AGORA_DATABASE_URL=postgresql://...  # Postgres

# Workspace
AGORA_WORKSPACE_ROOT=./workspace  # 工作区根目录
```

## 项目状态

📦 v0.16.0 — 安全加固 + Dashboard 认证

🚧 Phase 16: MCP Server（开发中）

## 路线图

详见 [docs/ROADMAP.md](docs/ROADMAP.md)。

- ✅ Phase 9-14: 平台核心功能
- ✅ Phase 15: 安全加固 + Dogfooding (v0.16.0)
- 🔮 Phase 16: MCP Server — 标准协议接入

## License

MIT
