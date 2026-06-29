# Agora Agent 唤醒机制 — 框架对比与改造方案

> 日期: 2026-06-29
> 问题: Agora 的 agent 不能主动唤醒接入的 agent 干活

---

## 一、问题本质

Agora 选择了 MCP 协议，而 MCP 是严格的 Client→Server 模型：

```
Agent (MCP Client) ──主动连接──► Agora (MCP Server)
Agent (MCP Client) ◄──SSE 推送── Agora (MCP Server)
```

**Agora 只能推送给"已连接"的 agent。agent 不在线 → 通知静默丢弃 → 任务永远卡住。**

这不是 bug，是 MCP 协议的架构性限制。所有基于 MCP 的多 agent 系统都会遇到这个问题。

---

## 二、主流框架的唤醒/调度机制对比

### 2.1 AutoGen (Microsoft)

**架构**: 对话驱动，GroupChat Manager 集中调度

**唤醒机制**:
- **同步调用模型**: Manager 的 `run_chat()` 是一个同步循环，依次调用每个 agent 的 `generate_reply()`
- Agent 不是独立进程，是同一个 Python 进程内的对象
- Manager 直接调用 agent 方法，不存在"唤醒"问题——agent 就是函数调用

**对 Agora 的启发**:
- ⚠️ 不可直接借鉴——AutoGen 的 agent 是进程内对象，Agora 的 agent 是远程独立进程
- ✅ 但 Manager 的"集中调度"模式值得参考：Agora 需要一个类似的 Scheduler 组件

### 2.2 CrewAI

**架构**: 任务委派，Sequential/Hierarchical Process

**唤醒机制**:
- **Sequential Process**: 任务链式执行，上一个完成自动触发下一个
- **Hierarchical Process**: Manager Agent 通过 LLM 决策委派任务给 worker
- Agent 之间通过 `delegate_work()` 和 `ask_question()` 工具互相调用
- 底层是**同步函数调用**，agent 在同一个进程内

**对 Agora 的启发**:
- ✅ **任务队列模式**: CrewAI 的 Task 有 `async_execution` 属性，支持并行
- ✅ **回调机制**: `task.callback` 在任务完成时触发，可用于链式唤醒
- ⚠️ 但 CrewAI 同样假设 agent 始终可用（进程内）

### 2.3 LangGraph (LangChain)

**架构**: 图状态机，节点 + 条件边

**唤醒机制**:
- **图执行引擎**: `graph.invoke()` 或 `graph.stream()` 驱动状态在节点间流转
- 每个节点是一个函数/agent，执行完返回新状态
- 条件边决定下一个节点是谁——本质是**状态驱动的自动流转**
- 支持 `interrupt` 和 `checkpointer`，可以从断点恢复

**对 Agora 的启发**:
- ✅✅ **状态机 + Checkpoint 是最佳参考**:
  - 任务状态持久化到 DB
  - Agent 上线后查询"有没有我的待处理任务"
  - 超时未处理 → 自动流转到下一个 agent 或重新分配
- ✅ **条件边** → Agora 的任务流转逻辑可以建模为状态图
- ✅ **Human-in-the-loop** → LangGraph 的 `interrupt_before` 模式可用于需要人工审批的步骤

### 2.4 MetaGPT

**架构**: SOP 驱动，角色扮演

**唤醒机制**:
- **消息池 (Message Pool)**: 所有 agent 共享一个消息池，agent 从池中读取消息
- **订阅模式**: agent 订阅特定类型的消息（role、cause_by 等）
- **轮询驱动**: agent 的 `_observe()` 方法从消息池拉取自己关心的消息
- 每个 agent 在自己的 `run()` 循环中不断 observe → think → act

**对 Agora 的启发**:
- ✅✅ **消息池 + 订阅 + 轮询** 是最接近 Agora 需求的模式:
  - Agora 的 Storage 已经充当了"消息池"
  - Agent 上线后调用 `get_pending_tasks` 就是"轮询"
  - 缺的是：把轮询做成 agent 的标准行为，而不是可选的
- ✅ **订阅过滤**: agent 只拉取自己角色/能力匹配的任务

### 2.5 Agno (原 Phidata)

**架构**: Agent 组合，Team 模式

**唤醒机制**:
- **Team Leader 委派**: Leader agent 通过 `transfer_task_to_member()` 委派
- **同步调用**: 底层是函数调用，agent 在同一进程
- 支持 `async_mode` 并行执行

**对 Agora 的启发**:
- ⚠️ 与 CrewAI 类似，进程内模型，参考价值有限
- ✅ Team 的"Leader 决策 → 委派 → 收集结果"模式值得借鉴

### 2.6 OpenAI Swarm / Agents SDK

**架构**: Handoff 机制，轻量级 agent 切换

**唤醒机制**:
- **Handoff**: agent 通过返回 `Handoff(target_agent)` 将控制权转移给另一个 agent
- 本质上是一个**函数返回 + 上下文切换**
- 没有持久化，没有独立进程

**对 Agora 的启发**:
- ✅ **Handoff 的语义**很适合 Agora: "这个任务我搞不定，转给 X"
- 可以在 MCP tools 里加一个 `handoff_task(target_agent, reason)` tool

### 2.7 Google ADK (Agent Development Kit)

**架构**: 事件驱动，Agent 图

**唤醒机制**:
- **事件驱动**: agent 之间通过 Event 通信
- **Agent 图**: 类似 LangGraph，agent 作为图的节点
- **异步回调**: `before_agent_callback` / `after_agent_callback`
- 支持 `LlmAgent` 和 `WorkflowAgent`

**对 Agora 的启发**:
- ✅ **事件驱动 + Agent 图** 是最先进的模式
- ✅ **回调链** 可以用于任务完成后的自动触发
- ⚠️ 但 ADK 同样假设 agent 在同一个运行时内

---

## 三、核心洞察：两种架构范式

调研后发现，所有框架分为两派：

### 范式 A：进程内 Agent（AutoGen / CrewAI / Agno / Swarm / ADK）

```
┌─────────────────────────────────┐
│  同一个 Python 进程              │
│  ┌──────┐  ┌──────┐  ┌──────┐  │
│  │Agent1│  │Agent2│  │Agent3│  │
│  └──┬───┘  └──┬───┘  └──┬───┘  │
│     │         │         │       │
│     └────┬────┴────┬────┘       │
│          ▼         ▼            │
│     Manager / Graph / Team      │
└─────────────────────────────────┘
```

- Agent 是函数/对象，不是独立进程
- "唤醒" = 函数调用，天然不存在问题
- **Agora 不能用这个模式**——它的 agent 是远程的 Hermes/Claude/Codex

### 范式 B：消息驱动 Agent（MetaGPT / LangGraph）

```
┌──────────┐     ┌──────────┐     ┌──────────┐
│ Agent 1  │     │ Agent 2  │     │ Agent 3  │
│ (独立进程)│     │ (独立进程)│     │ (独立进程)│
└────┬─────┘     └────┬─────┘     └────┬─────┘
     │                │                │
     │   poll/observe │   poll/observe │   poll/observe
     ▼                ▼                ▼
┌─────────────────────────────────────────────┐
│              共享消息池 / 状态存储            │
│           (Message Pool / State Graph)       │
└─────────────────────────────────────────────┘
```

- Agent 是独立进程，通过共享存储通信
- "唤醒" = agent 轮询发现自己有活干
- **这才是 Agora 应该走的路线**

---

## 四、Agora 的改造方案

### 4.1 核心思路：从"推送"转向"推送 + 拉取确认"

当前 Agora 的问题是**只推不确认**。解决方案不是放弃 MCP，而是在 MCP 之上加一层可靠性机制。

### 4.2 方案设计：三层改造

```
┌─────────────────────────────────────────────────────┐
│                   Agora Coordinator                  │
│                                                     │
│  ┌─────────────────────────────────────────────┐   │
│  │           Task Notification Queue            │   │
│  │  ┌──────┐ ┌──────┐ ┌──────┐ ┌──────┐       │   │
│  │  │task_1│ │task_2│ │task_3│ │task_4│  ...  │   │
│  │  │→ A1  │ │→ A2  │ │→ A1  │ │→ A3  │       │   │
│  │  └──────┘ └──────┘ └──────┘ └──────┘       │   │
│  │  pending_notifications 表 (SQLite/Postgres) │   │
│  └──────────────────────┬──────────────────────┘   │
│                         │                           │
│  ┌──────────────────────▼──────────────────────┐   │
│  │         Notification Dispatcher              │   │
│  │  - 尝试 SSE 推送 (agent 在线)                │   │
│  │  - 推送成功 → 标记 delivered                 │   │
│  │  - 推送失败 → 保留在队列，等 agent 拉取       │   │
│  │  - 超时未 ACK → 重新分配                     │   │
│  └──────────────────────┬──────────────────────┘   │
│                         │                           │
│  ┌──────────────────────▼──────────────────────┐   │
│  │         Agent Wakeup Triggers                │   │
│  │  - Webhook (agent 提供回调 URL)              │   │
│  │  - Hermes cron (已有 hermes-bridge)          │   │
│  │  - Agent SDK run_loop (恢复为主动轮询)       │   │
│  └─────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────┘
```

### 4.3 具体改造项

#### 改造 1：通知持久化队列（最关键）

**新增表**:
```sql
CREATE TABLE pending_notifications (
    id TEXT PRIMARY KEY,
    agent_id TEXT NOT NULL,
    notification_type TEXT NOT NULL,  -- TASK_ASSIGNED, DISCUSSION_MESSAGE, etc.
    payload TEXT NOT NULL,            -- JSON
    status TEXT DEFAULT 'pending',    -- pending, delivered, acked, expired
    created_at TEXT NOT NULL,
    delivered_at TEXT,
    acked_at TEXT,
    expires_at TEXT,
    retry_count INTEGER DEFAULT 0,
    max_retries INTEGER DEFAULT 3
);
```

**修改 `notifications.py`**:
```python
async def _send_to_agent(self, agent_id, method, params) -> bool:
    session_id = self._find_session_id(agent_id)
    if session_id is not None:
        # 在线 → 尝试推送
        success = await self._send_notification(session_id, method, params)
        if success:
            return True
    # 离线或推送失败 → 写入持久化队列
    await self.storage.add_pending_notification(
        agent_id=agent_id,
        notification_type=method,
        payload=params
    )
    return True  # 已排队，不算失败
```

#### 改造 2：Agent 上线时拉取积压通知

**新增 MCP Tool**: `fetch_pending_notifications`

```python
# mcp/tools/agent_tools.py
@mcp.tool()
async def fetch_pending_notifications() -> list[dict]:
    """Agent 上线后调用，拉取所有待处理的离线通知"""
    agent_id = get_current_agent_id()
    notifications = await storage.get_pending_notifications(agent_id)
    for n in notifications:
        await storage.mark_notification_delivered(n.id)
    return notifications
```

**Agent SDK 改动** (`run_loop.py`):
```python
async def run(client) -> None:
    """Agent 主循环：上线 → 拉积压 → 处理 → 等待新通知"""
    # 1. 拉取积压通知
    pending = await client.call_tool("fetch_pending_notifications", {})
    for notification in pending:
        await handle_notification(notification)
    
    # 2. 进入 SSE 监听循环
    async for notification in client.sse_stream():
        await handle_notification(notification)
```

#### 改造 3：任务超时自动重分配

**新增后台任务** (`task_timeout.py`):
```python
async def check_task_timeouts():
    """定期检查：分配超过 N 分钟未 ACK 的任务 → 重新分配"""
    while True:
        expired = await storage.get_expired_assignments(timeout_minutes=10)
        for task in expired:
            logger.warning(f"Task {task.id} assigned to {task.agent_id} timed out, reassigning")
            await reassign_task(task.id, exclude_agents=[task.agent_id])
        await asyncio.sleep(60)  # 每分钟检查一次
```

#### 改造 4：Webhook 唤醒（可选，进阶）

允许 agent 注册一个 webhook URL，Agora 有新任务时主动 HTTP POST 唤醒：

```python
# agent 注册时提供 webhook
POST /api/v1/agents/register
{
    "agent_id": "hermes-1",
    "capabilities": ["coding", "review"],
    "webhook_url": "http://10.0.0.5:9999/agora-wakeup"  # 可选
}

# Agora 有新任务时
async def wakeup_agent(agent_id, task_info):
    agent = await storage.get_agent(agent_id)
    if agent.webhook_url:
        await httpx.post(agent.webhook_url, json={
            "event": "new_task",
            "task": task_info
        })
```

#### 改造 5：Hermes Bridge 增强（已有基础）

`packages/hermes-bridge/` 已经有一个 daemon 模式，但目前功能有限。增强方向：

```python
# hermes-bridge 增强版
class HermesBridge:
    async def run_daemon(self):
        """持续运行，保持 MCP session 活跃"""
        while True:
            # 1. 确保 MCP 连接活跃
            if not self.mcp_session.is_connected:
                await self.mcp_session.connect()
            
            # 2. 拉取积压通知
            pending = await self.mcp_session.call_tool("fetch_pending_notifications", {})
            for n in pending:
                await self.dispatch_to_hermes(n)
            
            # 3. 等待 SSE 推送或超时
            try:
                async for notification in self.mcp_session.sse_stream(timeout=30):
                    await self.dispatch_to_hermes(notification)
            except TimeoutError:
                continue  # 心跳循环
```

---

## 五、改造优先级和建议

### 短期（1-2 周，解决核心痛点）

| 优先级 | 改造项 | 工作量 | 效果 |
|--------|--------|--------|------|
| P0 | 通知持久化队列 | 2-3天 | 离线 agent 不会丢任务 |
| P0 | `fetch_pending_notifications` tool | 1天 | agent 上线能拉到积压 |
| P0 | Agent SDK run_loop 恢复 | 1天 | agent 有标准的上线拉取行为 |
| P1 | 任务超时重分配 | 1-2天 | 挂掉的 agent 不阻塞流程 |

### 中期（1 个月，完善机制）

| 优先级 | 改造项 | 工作量 | 效果 |
|--------|--------|--------|------|
| P1 | Webhook 唤醒 | 2-3天 | 新任务即时唤醒 agent |
| P1 | 通知 ACK 确认 | 1天 | 可靠投递保证 |
| P2 | Hermes Bridge 增强 | 2-3天 | Hermes 原生支持 daemon 模式 |

### 长期（架构演进）

| 优先级 | 改造项 | 工作量 | 效果 |
|--------|--------|--------|------|
| P2 | 任务状态机 (LangGraph 风格) | 1-2周 | 可视化任务流转 |
| P2 | Agent 能力匹配路由 | 1周 | 智能分配而非手动指定 |
| P3 | 多 Agora 实例联邦 | 2-4周 | 跨集群协作 |

---

## 六、总结

**核心结论**: Agora 的问题不是 MCP 协议选错了，而是缺少 MCP 之上的**可靠性层**。

类比：
- MCP = TCP（传输层，只管连接和推送）
- Agora 缺的 = 应用层协议（消息队列、ACK、重试、超时）

参考 MetaGPT 的消息池 + LangGraph 的状态机，最务实的改造路径是：

1. **通知持久化** → 离线不丢消息
2. **Agent 上线拉取** → 恢复 run_loop
3. **超时重分配** → 不阻塞流程
4. **Webhook 唤醒** → 即时触发

这四个改造加起来大约 1-2 周工作量，能从根本上解决"agent 不能被唤醒"的问题。
