# Agora 项目分析报告

> 分析日期: 2026-06-29
> 项目地址: https://github.com/yzy806806/agora
> 当前版本: v0.17.0
> 本地克隆: /root/agora

---

## 一、项目概述

**Agora** 是一个 MCP (Model Context Protocol) Server，用于多 Agent 协作完成软件开发。核心定位是 **纯调度层**——不包含任何 agent，只提供三样东西：

1. **MCP Server** — 给 AI 用的标准协议接口（tools + resources + notifications）
2. **Dashboard** — 给人用的 Web 界面（下任务、看进度、审查结果）
3. **Workspace** — 共享工作区（文件存储，多 agent 协作编辑）

### 核心设计理念

- Agora 是"古罗马广场"——多个 agent 在这里聚集、讨论、分工、执行
- 人类通过 Dashboard 下任务，AI 通过 MCP 分解、讨论、执行
- 自身不包含任何 agent，是纯平台
- Coordinator（主持人）也是外部 agent，只是承担调度角色，可替换

---

## 二、项目结构

```
agora/
├── agora/
│   ├── __init__.py / __main__.py / cli.py    # 入口和CLI
│   └── coordinator/
│       ├── main.py                            # FastAPI 应用入口+生命周期
│       ├── config.py                          # 配置管理 (pydantic-settings)
│       ├── models/                            # 数据模型 (_models.py, _enums.py)
│       ├── router.py                          # REST API路由 (agent注册/查询, motion CRUD, task CRUD)
│       ├── state.py                           # 讨论状态机
│       ├── pipeline*.py                       # Pipeline Orchestrator (全自动开发循环)
│       ├── task_*.py                          # 任务引擎
│       ├── storage/                           # 数据存储层 (Storage facade + SQLite/Postgres backend)
│       ├── workspace/                         # 共享工作区 (文件CRUD, 锁管理)
│       ├── rbac*.py                           # RBAC权限控制
│       ├── token_manager.py                   # JWT Token管理
│       ├── token_scopes.py                    # Token作用域
│       ├── event_bus.py                       # 事件总线 (统一发布Dashboard+ MCP通知)
│       ├── broadcast_bus.py / broadcast_bus_redis.py  # 消息总线 (LocalBus/RedisBus)
│       ├── bootstrap/                         # 自驱系统 (daemon, discussion_driver, task_generator)
│       ├── dashboard*.py                      # Dashboard (REST API + WebSocket)
│       ├── notification*.py                   # 通知系统
│       ├── audit*.py                          # 审计日志
│       ├── heartbeat.py / timeout.py          # 心跳和超时
│       ├── rate_limiter.py                    # 速率限制
│       ├── capability.py                      # Agent能力模型
│       ├── discovery_*.py                     # Agent发现端点
│       ├── webhook*.py                        # Webhook触发器
│       ├── tenant/                            # 多租户
│       ├── task_gen/                          # 任务自动生成
│       ├── task_verify/                       # 任务验证
│       └── mcp/                               # ★ MCP Server (Phase 16核心)
│           ├── server.py                      # FastMCP 实例创建
│           ├── auth.py                        # MCP认证中间件 (Bearer token)
│           ├── deps.py                        # 依赖注入 (Storage, TokenManager, WorkspaceManager)
│           ├── notifications.py               # MCPNotificationBridge (Agora事件 → SSE推送)
│           ├── session_map.py                 # MCPSessionMap (agent_id ↔ mcp_session_id)
│           ├── health.py                      # 健康检查 (/mcp/health)
│           ├── tools/                         # MCP Tools (9个)
│           │   ├── agent_tools.py             # register_agent, update_status
│           │   ├── task_tools.py              # get_pending_tasks, accept_task, submit_task_result
│           │   ├── comm_tools.py              # send_message, list_conversations
│           │   └── workspace_tools.py         # get_workspace_file, put_workspace_file
│           └── resources/                     # MCP Resources (4个)
│               ├── task_resources.py
│               ├── agent_resources.py
│               ├── conversation_resources.py
│               └── project_resources.py
├── packages/
│   ├── agora-agent-sdk/     # Python SDK (HTTP注册 + 桥接接口)
│   ├── agora-agent-sdk-go/  # Go SDK
│   ├── agora-agent-sdk-js/  # JavaScript SDK
│   ├── agora-agent-sdk-rust/# Rust SDK
│   ├── cli-bridge/          # CLI桥接 (Claude/Codex/OpenClaw adapter)
│   └── hermes-bridge/       # Hermes桥接 (daemon + polling)
├── deploy/                  # Kubernetes Helm Chart
├── docs/                    # 设计文档 (40+ DESIGN-*.md)
└── tests/                   # 集成测试 (~200个test文件)
```

---

## 三、项目整体架构

### 3.1 架构总揽

```
                    人类 (Browser Dashboard)
                          │
                          ▼
             ┌───────────────────────────────────┐
             │        Agora Coordinator          │
             │      (FastAPI + MCP Server)       │
             │                                   │
             │  /api/v1/*  ← REST API            │
             │  /mcp        ← MCP Server         │
             │  /ws/*       ← WebSocket (历史)    │
             │                                   │
             │  ┌─────────┐ ┌──────────────┐     │
             │  │ Task    │ │ Pipeline     │     │
             │  │ Engine  │ │ Orchestrator │     │
             │  └────┬────┘ └──────┬───────┘     │
             │       │              │             │
             │  ┌────▼──────────────▼──────┐     │
             │  │  Event Bus + BroadcastBus│     │
             │  └──────────────────────────┘     │
             │  ┌──────────────────────────┐     │
             │  │ Storage (SQLite/Postgres)│     │
             │  └──────────────────────────┘     │
             │  ┌──────────────────────────┐     │
             │  │ Workspace Manager        │     │
             │  │ (Local FS / S3)          │     │
             │  └──────────────────────────┘     │
             └───────────────────────────────────┘
                          │
             ┌────────────┼────────────┐
             ▼            ▼            ▼
        MCP Client   MCP Client   MCP Client
        (Hermes)     (Claude)     (其他)
```

### 3.2 关键设计决策

1. **MCP 为主要接入协议**：替代 WebSocket 长连接，任何 MCP 兼容 agent 一行配置接入
2. **双协议共存**：MCP 端点 + REST API 并行，Dashboard 用 REST，Agent 用 MCP
3. **MCP Streamable HTTP**：SSE 长连接支持服务端推送
4. **认证三模式**：`AGORA_AUTH_MODE=none/token/rbac`
5. **存储后端可插拔**：SQLite→Postgres，`StorageBackend` ABC
6. **消息总线可插拔**：`LocalBus`（单机）→ `RedisBus`（集群）

### 3.3 核心组件职责

| 组件 | 职责 |
|------|------|
| **MCP Server** | 标准协议接口，agent 通过 MCP tools 与 Agora 交互 |
| **REST API** | Dashboard 和管理接口 |
| **Task Engine** | 任务创建、分配、状态流转、并行执行 |
| **Pipeline Orchestrator** | 全自动开发闭环：讨论→任务分解→开发→审查→发布 |
| **Workspace Manager** | 共享工作区文件 CRUD + 文件锁 |
| **Event Bus** | 事件中枢，连接 Dashboard WS 和 MCP SSE |
| **BroadcastBus** | 跨实例消息广播（Local/Redis）|
| **Bootstrap System** | 自驱循环：daemon + discussion_driver + task_generator + trigger_manager |
| **RBAC + TokenManager** | 权限控制和认证 |
| **Storage** | 统一数据访问层，支持 SQLite 和 Postgres |

---

## 四、Agent 之间如何通信和协作

### 4.1 通信机制概览

Agora 设计了**三层通信机制**，经过 Phase 16 演进后的现状：

```
┌─────────────────────────────────────────────────────────┐
│                    通信机制对比                           │
├──────────────┬─────────────────┬────────────────────────┤
│   协议层      │   传输方式       │   当前状态              │
├──────────────┼─────────────────┼────────────────────────┤
│ MCP Tools    │ POST JSON-RPC   │ ★ 主力 (Phase 16)      │
│ MCP SSE      │ Server-Sent Evt  │ ★ 推送通知              │
│ REST API     │ HTTP POST/GET    │ Dashboard + 管理        │
│ WebSocket    │ 长连接 (已废弃)   │ ⚠ 历史遗留，被MCP替代   │
└──────────────┴─────────────────┴────────────────────────┘
```

### 4.2 协作工作流

#### 典型流程（人类下任务）

```
1. 人类 → Dashboard → POST /api/v1/tasks
2. Agora → Pipeline Orchestrator 启动讨论
3. Agora → MCP SSE → notifications/pipeline_event 推送给所有agent
4. Agent 们 → MCP tools/call (send_message) 多轮讨论
5. Agora → MCP SSE → notifications/discussion_message 广播消息
6. 达成共识后 → Task Generator 生成任务图
7. Agora → MCP SSE → notifications/task_assigned 分配任务给agent
8. Agent → MCP tools/call (accept_task) 接受
9. Agent → MCP tools/call (put_workspace_file) 写文件
10. Agent → MCP tools/call (submit_task_result) 提交结果
```

#### 代码层面的关键路径

1. **Agent 注册**：`mcp/tools/agent_tools.py::register_agent()` → `storage.agents.register_agent()`
2. **任务分配**：`task_assign.py::assign_tasks()` → `event_bus.publish("TASK_ASSIGNED")` → `MCPNotificationBridge.on_task_assigned()` → SSE push to agent
3. **讨论消息**：`mcp/tools/comm_tools.py::send_message()` → `storage.messages.add_message()` → `event_bus.publish("DISCUSSION_MESSAGE")` → `MCPNotificationBridge.on_discussion_message()` → SSE push to all participants
4. **任务状态变更**：`mcp/tools/task_tools.py::accept_task/submit_task_result()` → `event_bus.publish("TASK_STATUS")` → 推送给 Dashboard + MCP

### 4.3 消息传递链路（核心！）

消息传递的完整链路如下：

```
一个 Agent 调用 send_message(tool)
        │
        ▼
comm_tools.py::send_message()
        │
        ├── storage.add_message()           # 持久化到数据库
        │
        └── event_bus.publish("DISCUSSION_MESSAGE", ...)
                │
                ├── dashboard_hub.broadcast_event()   # → Dashboard WebSocket
                │
                └── _forward_to_mcp(event_type, payload)
                        │
                        ▼
                MCPNotificationBridge.on_discussion_message()
                        │
                        ├── 查询 conversation 的 participants
                        │    (排除 sender_id)
                        │
                        └── 对每个 participant:
                            └── _send_to_agent(agent_id, method, params)
                                    │
                                    ├── _find_session_id(agent_id)
                                    │    └── MCPSessionMap.get_session_id(agent_id)
                                    │         └── 查找 agent_id → mcp_session_id
                                    │
                                    ├── _send_notification(session_id, method, params)
                                    │    └── 通过 FastMCP SDK 的 session manager
                                    │         ↓
                                    │    session.send_notification(method, params)
                                    │         ↓
                                    └── SSE 流推送到目标 Agent 的 MCP 客户端
```

---

## 五、核心问题分析："agent 不能主动唤醒接入的 agent 干活"

### 5.1 问题描述

**核心问题**：MCP 协议下，Agora Coordinator 虽然可以通过 SSE 推送通知给 agent，但 **agent 本身处于被动状态**——只有当 agent 的 MCP 客户端（如 Hermes）处于活跃状态时，才能接收 SSE 通知。如果 agent 没有活跃的 MCP session（比如 Hermes 没有在运行），Coordinator 就无法"叫醒"它来干活。

### 5.2 代码层面卡住的具体位置

#### 卡点 1：MCPSessionMap 依赖活跃连接

**文件**：`agora/coordinator/mcp/session_map.py`

```python
class MCPSessionMap:
    _agent_to_session: dict[str, str] = {}
    _session_to_agent: dict[str, str] = {}

    def get_session_id(self, agent_id: str) -> Optional[str]:
        return self._agent_to_session.get(agent_id)  # agent不在线→返回None

    def is_agent_connected(self, agent_id: str) -> bool:
        return agent_id in self._agent_to_session  # 只有活跃MCP连接才存在映射
```

**问题**：`MCPSessionMap` 是一个**纯内存映射**，只有当 agent 的 MCP 客户端主动通过 Streamable HTTP 建立连接时，才会在 `MCPAuthMiddleware` 中调用 `register_agent_session()` 建立映射。如果 agent 没有运行，此映射不存在，Coordinator 无法找到目标 session。

#### 卡点 2：MCPNotificationBridge 无法找到离线 session

**文件**：`agora/coordinator/mcp/notifications.py`

```python
async def _send_to_agent(self, agent_id, method, params) -> bool:
    session_id = self._find_session_id(agent_id)
    if session_id is None:
        logger.debug("No MCP session for agent %s, skip %s", agent_id, method)
        return False  # ← 直接跳过，不发送！！！
    ...
```

**问题**：当 `session_id` 为 `None`（agent 不在线），通知被静默丢弃。没有任何重试、队列、或持久化机制。

#### 卡点 3：任务分配时的通知失败

**文件**：`agora/coordinator/task_assign.py`

```python
async def _notify_task_assignment(task, agent_id, hub=None) -> bool:
    # ...
    try:
        from .event_bus import publish
        await publish("TASK_ASSIGNED", {...}, channel="tasks")
    except Exception:
        logger.warning("MCP task assignment notification failed for %s", agent_id)
    return True  # ← 即使失败也返回 True，任务已分配但agent不会知道！
```

**问题**：任务分配的代码在本文件中有两处调用 `_notify_task_assignment`（`assign_tasks` 和 `reassign_task`），但即使通知失败，函数仍然返回 `True`，任务状态已经从 `PENDING`→`ASSIGNED`。agent 永远不知道有新任务。

#### 卡点 4：并行执行调度同样的问题

**文件**：`agora/coordinator/task_parallel_dispatch.py`

```python
async def _run_task(task, agent_id, hub=None) -> str:
    if hub is not None and hasattr(hub, "send"):
        await hub.send(agent_id, {...})
    else:
        try:
            from .event_bus import publish
            await publish("TASK_ASSIGNED", {...}, channel="tasks")
        except Exception:
            logger.warning("MCP task dispatch failed for %s", agent_id)
    return task.id  # ← 同样即使失败也返回成功
```

#### 卡点 5：MCP Auth 中间件的 session 注册是"被动"的

**文件**：`agora/coordinator/mcp/auth.py`

```python
async def dispatch(self, request, call_next):
    # ...
    mcp_sid = request.headers.get("mcp-session-id")
    if mcp_sid and agent_id != "admin":
        register_agent_session(agent_id, mcp_sid)
    # ...
```

**问题**：session 映射只在 MCP 客户端发起请求时建立。Agora 不能主动向 agent 发起 MCP 连接，因为 Agora 是 Server，agent 是 Client。这是 MCP 协议本身的 C/S 架构决定的。

### 5.3 问题本质

这是 **MCP 协议的架构性限制**：

```
MCP 协议角色：
┌──────────┐     主动发起连接     ┌──────────┐
│  MCP     │ ──────────────────► │  MCP     │
│  Client  │                     │  Server  │
│ (agent)  │ ◄────────────────── │ (Agora)  │
└──────────┘     SSE 推送通知     └──────────┘
```

- MCP Client（agent）主动连接 MCP Server（Agora）
- MCP Server 只能通过已建立的 SSE 流推送通知
- **MCP Server 不能主动向 MCP Client 发起新连接**

这意味着：
- Agent 必须先运行并从自己这边连接到 Agora
- Agora 不能"摇醒"一个离线 agent
- 如果 Hermes 没有在运行，Agora 分配的任务它永远收不到

### 5.4 当前已有的缓解措施

1. **Hermes Bridge（独立进程轮询）**：`packages/hermes-bridge/` 提供了一个 daemon 模式，通过 cron/polling 定时拉取任务
2. **CLI Bridge**：`packages/cli-bridge/` 提供了为 Claude/Codex 等命令行 agent 的桥接
3. **Agent SDK run_loop**：`packages/agora-agent-sdk/src/agora_agent_sdk/run_loop.py` —— 但 Phase 16.10 之后这个被改成了 no-op：
   ```python
   async def run(client) -> None:
       """No-op: MCP agents don't need a WS event loop."""
       logger.info("MCP mode: no WS run loop needed")
   ```
4. **REST API 轮询**：agent 可以通过 `GET /api/v1/tasks?agent_id=X&status=pending` 主动查询自己的待处理任务

### 5.5 根本矛盾

Agora 在 Phase 16 选择了 **MCP 作为主要协议**，但 MCP 的 C/S 模型天然与"平台主动调度 agent"的需求存在矛盾：

- **期望行为**：Coordinator 是一个调度器，应该能随时给任何 agent 分配任务
- **实际可能**：Coordinator 只能推送给当前有活跃 MCP session 的 agent
- **缺失机制**：没有任务队列、没有离线消息存储、没有 agent 唤醒机制

当前的做法是：**任务状态改了，通知发了（或尝试发了），至于 agent 收到没收到，不关心**。

---

## 六、消息传递/事件机制

### 6.1 EventBus（事件总线）

**文件**：`agora/coordinator/event_bus.py`

EventBus 是消息传递的核心枢纽，统一处理两个方向的推送：

```
EventBus 架构：

publish(event_type, payload, channel)
        │
        ├── 1. Dashboard WebSocket 推送
        │    └── dashboard_hub.broadcast_event(event_type, payload, channel)
        │          └── 遍历所有 Dashboard WS 连接 → 发送 JSON
        │
        └── 2. MCP SSE 推送
             └── _forward_to_mcp(event_type, payload)
                   │
                   ├── "TASK_ASSIGNED" → MCPNotificationBridge.on_task_assigned()
                   ├── "TASK_STATUS"   → MCPNotificationBridge.on_task_updated()
                   ├── "DISCUSSION_MESSAGE" → MCPNotificationBridge.on_discussion_message()
                   └── "PIPELINE_EVENT" → MCPNotificationBridge.on_pipeline_event()
```

**初始化流程**（在 `main.py` lifespan 中）：

```python
# 1. 创建 DashboardHub
dashboard_hub.set_token_manager(token_mgr)

# 2. 初始化 EventBus 连接 DashboardHub
init_event_bus(dashboard_hub)

# 3. 创建 MCP session map 和 bridge
_mcp_session_map = MCPSessionMap()
_mcp_bridge = MCPNotificationBridge(_mcp_session_map, storage)

# 4. 将 bridge 注册到 EventBus
init_mcp_bridge(_mcp_bridge)
```

### 6.2 BroadcastBus（跨实例广播）

**文件**：`agora/coordinator/broadcast_bus.py` 和 `broadcast_bus_redis.py`

用于多实例 Coordinator 部署时的跨实例消息广播：

```
BroadcastBus (ABC)
├── LocalBus   → 单机模式（publish 是 no-op，本地已完成推送）
└── RedisBus   → 集群模式（通过 Redis Pub/Sub 跨实例广播）
```

**注意**：BroadcastBus 主要用于 Dashboard WebSocket 的跨实例 fan-out。因为 Phase 16.10 移除了 Agent WebSocket 的 broadcast_bus 集成。

### 6.3 通知类型汇总

| 事件类型 | 触发者 | 接收者 | 传输方式 |
|---------|--------|--------|---------|
| `TASK_ASSIGNED` | Coordinator 分配任务 | 目标 Agent | MCP SSE |
| `TASK_STATUS` | Agent 状态变更 | Dashboard | Dashboard WS |
| `TASK_STATUS` | Agent 状态变更 | 目标 Agent | MCP SSE |
| `DISCUSSION_MESSAGE` | Agent 发消息 | 所有参与者 | MCP SSE |
| `DISCUSSION_MESSAGE` | Agent 发消息 | Dashboard | Dashboard WS |
| `PIPELINE_EVENT` | Pipeline 阶段推进 | 所有 Agent | MCP SSE |
| `PIPELINE_EVENT` | Pipeline 阶段推进 | Dashboard | Dashboard WS |
| `MOTION_STATUS` | 讨论状态变更 | Dashboard | Dashboard WS |

### 6.4 MCP 协议层面的消息流

```
[Agent MCP Client]                         [Agora MCP Server]
        │                                          │
        │── POST /mcp (InitializeRequest) ────────►│  ← 建立MCP会话
        │◄── InitializeResult + Session-Id ────────│
        │                                          │
        │── GET /mcp (SSE stream) ────────────────►│  ← 长连接
        │                                          │
        │                    ... time passes ...   │
        │                                          │
        │◄── SSE: notifications/task_assigned ─────│  ← 推送通知
        │                                          │
        │── POST tools/call (accept_task) ────────►│  ← Tool调用
        │◄── ContentResult ────────────────────────│
        │                                          │
        │── GET agora://tasks/{id} ───────────────►│  ← Resource读取
        │◄── ResourceContents ─────────────────────│
```

---

## 七、总结和关键发现

### 7.1 项目亮点

1. **架构清晰**：三层分离——MCP Server（agent端）、REST API（Dashboard/管理）、Workspace（共享存储）
2. **设计文档完善**：40+ 设计文档，每个 Phase 都有详细的设计方案
3. **存储层可插拔**：Storage Backend ABC，支持 SQLite 和 Postgres
4. **事件总线统一**：EventBus 同时连接 Dashboard WS 和 MCP SSE
5. **一行配置接入**：真正做到了 MCP agent 一行配置即可接入
6. **自驱系统**：Bootstrap daemon + GitHub issue sync + 自动讨论

### 7.2 关键瓶颈：MCP 协议的限制

**"agent 不能主动唤醒接入的 agent 干活"** 的根本原因是：

1. **MCP Server 不能主动连接 MCP Client**
2. **MCPSessionMap 纯内存映射，agent 离线则映射不存在**
3. **通知被静默丢弃，无重试/队列/持久化**
4. **任务状态已变更但 agent 可能永远不知道**

**缺失的关键能力**：
- ❌ 离线消息队列
- ❌ Agent 唤醒/触发机制  
- ❌ 任务通知确认 (ACK)
- ❌ 通知重试机制
- ❌ 超时后的自动重分配

### 7.3 可能的解决方向

1. **Agent 侧被动轮询**：agent 定期调用 `get_pending_tasks`（当前唯一可靠方式）
2. **Hermes Bridge daemon 模式**：独立进程持续运行，保持 MCP session 活跃
3. **增加任务通知队列 + 确认机制**：类似 TCP 的 ACK，未确认的任务重新分配
4. **Webhook/HTTP 回调**：Agora 主动 POST 到 agent 的 endpoint（需要 agent 暴露端口）
5. **消息队列集成**：Agora 发布任务到消息队列，agent 订阅消费
