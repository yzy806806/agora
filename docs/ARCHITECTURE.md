# Agora 架构文档

> 版本: v0.16.0 | 最后更新: 2026-06-19

## 整体架构

```
                    ┌─────────────────────────────────────┐
                    │       Agora Coordinator              │
                    │  (FastAPI + MCP Server)               │
                    │  ┌──────────┐ ┌───────────────────┐  │
                    │  │ REST API │ │ MCP Server        │  │
                    │  │(Dashboard│ │ (Tools/Resources/ │  │
                    │  │  CRUD)   │ │  Notifications)   │  │
                    │  └────┬─────┘ └────────┬──────────┘  │
                    │       │     ┌──────────┤             │
                    │  ┌────▼─────▼──┐ ┌─────▼──────────┐  │
                    │  │ State       │ │ Pipeline       │  │
                    │  │ Machine     │ │ Orchestrator   │  │
                    │  └─────────────┘ └────────────────┘  │
                    │  ┌───────────┐ ┌───────────────────┐ │
                    │  │ Task      │ │ RBAC Middleware   │ │
                    │  │ Engine    │ │ + TokenManager    │ │
                    │  └───────────┘ └───────────────────┘ │
                    │  ┌───────────┐ ┌───────────────────┐ │
                    │  │Workspace  │ │ Broadcast Bus     │ │
                    │  │ Manager   │ │ (Local/Redis)     │ │
                    │  └───────────┘ └───────────────────┘ │
                    │  ┌───────────────────────────────┐   │
                    │  │ Storage (SQLite / Postgres)    │   │
                    │  └───────────────────────────────┘   │
                    └─────────────┬────────────────────────┘
                                  │
            ┌─────────────────────┼─────────────────────┐
            ↓                     ↓                     ↓
       ┌─────────┐         ┌──────────┐         ┌──────────┐
       │ Browser │         │ MCP      │         │ MCP      │
       │Dashboard│         │ Client   │         │ Client   │
       │ (人类)   │         │(Hermes等)│         │(Claude等)│
       └─────────┘         └──────────┘         └──────────┘
```

## MCP Server 架构

MCP Server 挂载在 FastAPI 的 `/mcp` 路径下，独立于 REST API 和 WebSocket 运行：

```
┌─────────────────────────────────────────────────┐
│              FastAPI (main.py)                    │
│                                                   │
│  /api/v1/*  ─── REST API (Dashboard, 管理)       │
│  /ws/*      ─── WebSocket (已有 agent)            │
│  /mcp       ─── MCP Server (AI agent 推荐)       │
│       │                                          │
│       └── StreamableHTTPASGIApp (MCP SDK)         │
│              ├── MCPAuthMiddleware (独立认证)      │
│              ├── /health (无需认证)               │
│              ├── Tools (9个: 注册/任务/讨论/工作区) │
│              ├── Resources (4个: 只读数据源)       │
│              └── Notifications (SSE 推送)         │
│                    │                              │
│                    └── MCPNotificationBridge       │
│                         ↑ EventBus 事件           │
│                                                   │
│  共享层: Storage / TokenManager / Workspace /      │
│          EventBus / MCPSessionMap                 │
└─────────────────────────────────────────────────┘
```

### 交互流程

```
1. Agent → POST /mcp (InitializeRequest)
2. Agora → InitializeResult + Session-Id
3. Agent → GET /mcp (SSE stream, 长连接)
4. Agora → SSE: notifications/task_assigned
5. Agent → POST tools/call (accept_task)
6. Agora → SSE: notifications/discussion_message
7. Agent → POST tools/call (send_message)
```

详见 [ARCHITECTURE-mcp.md](ARCHITECTURE-mcp.md) 和 [MCP.md](MCP.md)。

## 项目目录结构

```
agora/
├── __init__.py              # 版本声明
├── cli.py                   # CLI: agora serve
├── pyproject.toml           # 构建配置
├── agora/coordinator/       # 核心包
│   ├── main.py              # FastAPI 入口 + 生命周期
│   ├── config.py            # 配置 (pydantic-settings)
│   ├── models/              # 数据模型
│   ├── state.py             # 讨论状态机
│   ├── router.py            # REST API 路由
│   ├── mcp/                 # MCP Server (Phase 16)
│   ├── pipeline*.py         # Pipeline Orchestrator
│   ├── task_*.py            # 任务执行引擎
│   ├── workspace/           # 共享工作区
│   ├── rbac*.py             # RBAC + 认证
│   ├── token_manager.py     # JWT Token 管理
│   ├── broadcast_*.py       # 消息总线 (Local/Redis)
│   ├── webhook_*.py         # Webhook 触发器
│   ├── capability*.py       # Agent 能力模型
│   ├── discovery_*.py       # Agent 发现端点
│   ├── dashboard*.py        # Dashboard (static + WS)
│   ├── notification*.py     # 通知系统
│   ├── health.py            # 健康检查
│   ├── storage/             # 数据存储层
│   └── static/              # Dashboard 前端
└── docs/                    # 设计文档
```

## 演进阶段

| Phase | 主题 | 核心模块 |
|-------|------|---------|
| 9-12 | 平台核心 | REST API, 任务引擎, Agent 注册, SDK |
| 13 | 全自动开发循环 | Pipeline Orchestrator, Dashboard 增强 |
| 14 | 共享工作区 | Workspace Manager + StorageBackend |
| 14+ | 水平扩展 | Postgres, Redis Bus, Helm, Webhook |
| 15 | 安全加固 | Dashboard 认证, API 认证, Agent 自助注册 |
| 16 | MCP Server | MCP Tools/Resources/Notifications |

## 关键设计决策

1. **MCP 为主要接入协议**：替代 WS 长连接，任何 MCP 兼容 agent 一行配置接入
2. **双协议共存**：MCP 端点 + REST API 并行，Dashboard 用 REST，Agent 用 MCP
3. **MCP Streamable HTTP**：SSE 长连接支持服务端推送，替代旧 WS 广播
4. **认证三模式**：AGORA_AUTH_MODE=none/token/rbac，从无认证到完整 RBAC
5. **存储后端可插拔**：SQLite（默认）→ Postgres，StorageBackend ABC 统一接口
6. **消息总线可插拔**：LocalBus（单机）→ RedisBus（集群），BroadcastBus ABC
7. **Workspace 元数据/内容分离**：元数据在 DB，文件字节在 StorageBackend

详细架构见拆分文档：
- [ARCHITECTURE-phase13-pipeline.md](ARCHITECTURE-phase13-pipeline.md)
- [ARCHITECTURE-phase13-dashboard.md](ARCHITECTURE-phase13-dashboard.md)
- [ARCHITECTURE-phase14-workspace.md](DESIGN-phase14-workspace.md)
- [DESIGN-phase14plus.md](DESIGN-phase14plus.md)
