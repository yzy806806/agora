# Matrix Wakeup Bridge — Design

## 问题

Agent 通过 MCP 连接 Agora 后，MCP 是 agent→server 的单向出站连接。当 Agora 给 agent 分配任务时，如果 agent 没有活跃的 MCP session，Agora 无法反向推送通知。

当前方案（Phase 19）用 Telegram Bot API 发消息唤醒 agent，但 Telegram 不是开源的，而且需要 agent 的 Hermes 配置 Telegram gateway。

## 方案：Matrix 作为信令通道

Matrix 是去中心化的开源 IM 协议，Hermes 原生支持 Matrix gateway。架构如下：

```
┌─────────────────────────────────────────────────────────────┐
│                      有公网 IP 的机器                        │
│  ┌──────────────────────┐    ┌───────────────────────────┐  │
│  │  Matrix Homeserver   │    │  Agora Coordinator        │  │
│  │  (Synapse/Dendrite)  │    │  ┌─────────────────────┐  │  │
│  │                      │    │  │  MatrixWakeupClient  │  │  │
│  │  Room: #agora-wakeup │◄───│  │  (mautrix client)   │  │  │
│  │                      │    │  └─────────────────────┘  │  │
│  └──────────────────────┘    └───────────────────────────┘  │
└─────────────────────────────────────────────────────────────┘
           │                              │
           │ Matrix 协议                   │ MCP (agent→server)
           │ (双向，穿透 NAT)               │
           ▼                              ▼
┌──────────────────────┐    ┌──────────────────────┐
│  Hermes Agent A      │    │  Hermes Agent B      │
│  (Matrix gateway)    │    │  (Matrix gateway)    │
│  Room: #agora-wakeup │    │  Room: #agora-wakeup │
└──────────────────────┘    └──────────────────────┘
```

### 工作流程

1. Agora 给 agent 分配任务，agent 离线（无 MCP session）
2. Agora 把通知入队到 `pending_notifications` 表（已有逻辑）
3. Agora 的 `MatrixWakeupClient` 在 `#agora-wakeup` room 发消息：
   `@agent_a:matrix.server 🔔 You have 3 pending tasks in Agora`
4. Agent A 的 Hermes（已配置 Matrix gateway）收到消息
5. Hermes 被触发，agent 通过 MCP 连上 Agora，调用 `fetch_pending_notifications`
6. Agent 拉取任务，开始执行

### 与 Telegram 方案的对比

| 维度 | Telegram | Matrix |
|------|----------|--------|
| 开源 | ❌ 闭源 | ✅ 完全开源 |
| 部署 | 依赖 Telegram 服务 | 可自建 homeserver |
| Hermes 支持 | ✅ 原生 | ✅ 原生 |
| NAT 穿透 | ✅ 出站连接 | ✅ 出站连接 |
| 消息格式 | Markdown | Markdown + HTML |
| 多 agent 隔离 | 需要多个 chat | 一个 room + @mention |
| 资源消耗 | 无（外部服务） | Synapse ~200MB, Dendrite ~50MB |

## 实现计划

### 1. Agora 侧：新增 `matrix_wakeup.py`

仿照 `telegram_wakeup.py` 的结构，新增 Matrix 客户端：

```python
# agora/coordinator/matrix_wakeup.py

class MatrixWakeupClient:
    """Agora → Matrix bridge for agent wakeup."""
    
    def __init__(self, homeserver_url: str, access_token: str, room_id: str):
        self._client = AsyncClient(homeserver_url, access_token)
        self._room_id = room_id
    
    async def start(self):
        """Connect and join the wakeup room."""
    
    async def wakeup_agent(self, agent_id: str, pending_count: int, summary: list[str]):
        """Send @mention message to wake up a specific agent."""
        # 发消息: "@agent_matrix_id:server 🔔 You have N pending tasks"
    
    async def close(self):
        """Disconnect."""
```

### 2. 配置项

在 `config.py` 的 `Settings` 中新增：

```python
# Matrix wakeup
matrix_homeserver_url: str = ""       # AGORA_MATRIX_HOMESERVER_URL
matrix_access_token: str = ""         # AGORA_MATRIX_ACCESS_TOKEN
matrix_wakeup_room_id: str = ""       # AGORA_MATRIX_WAKEUP_ROOM_ID
```

### 3. Agent 侧：配置 `matrix_user_id`

在 agent 注册/配置中新增字段 `matrix_user_id`（如 `@agent_a:matrix.example.org`），Agora 用这个 ID 做 @mention。

### 4. main.py 集成

在 `lifespan()` 中，如果配置了 Matrix，初始化 `MatrixWakeupClient`，替代或补充 `telegram_wakeup`。

### 5. 修改 `notifications.py`

`_send_to_agent()` 中，Telegram wakeup 的 `try_wakeup_agent()` 调用改为通用的 `try_wakeup_agent()`，内部根据 agent 配置选择 Matrix 或 Telegram。

## 依赖

- `mautrix` — Matrix Python SDK（Hermes 已经在用）
- Matrix homeserver — 可以部署在 Agora 同一台机器或有公网 IP 的机器上

## 部署 Matrix Homeserver

推荐 **Dendrite**（轻量，Go 实现，~50MB 内存）：

```bash
# docker-compose.yml
version: "3"
services:
  dendrite:
    image: matrixdotorg/dendrite-monolith:latest
    ports:
      - "8008:8008"
    volumes:
      - ./dendrite:/etc/dendrite
    command: -config /etc/dendrite/dendrite.yaml
```

或者用 **Synapse**（更成熟，~200MB 内存）：

```bash
# docker-compose.yml
services:
  synapse:
    image: matrixdotorg/synapse:latest
    ports:
      - "8008:8008"
    volumes:
      - ./synapse:/data
```

## Agent Hermes 配置

每个 agent 的 Hermes profile 需要配置 Matrix gateway：

```bash
# .env
MATRIX_HOMESERVER=https://matrix.example.org
MATRIX_ACCESS_TOKEN=syt_xxxxx
MATRIX_USER_ID=@agent_a:matrix.example.org
```

Hermes 会自动加入配置的 room 并响应 @mention。

## 实施步骤

1. [ ] 部署 Matrix homeserver（Dendrite，在 Agora 同机或公网机器）
2. [ ] 创建 `#agora-wakeup` room，获取 room ID
3. [ ] 创建 Agora bot 账号，获取 access token
4. [ ] 实现 `matrix_wakeup.py`
5. [ ] 在 `config.py` 添加 Matrix 配置项
6. [ ] 在 `main.py` 集成 Matrix wakeup client
7. [ ] 修改 `notifications.py` 支持 Matrix 唤醒
8. [ ] 为每个 agent 创建 Matrix 账号，配置 Hermes Matrix gateway
9. [ ] 在 agent 注册时关联 `matrix_user_id`
10. [ ] 端到端测试：任务分配 → Matrix 唤醒 → agent 拉取任务
