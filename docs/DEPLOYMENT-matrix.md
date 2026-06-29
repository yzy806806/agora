# Matrix Wakeup Bridge 部署指南

> Phase 20 | v0.18.0+

## 概述

当 Agora 给 agent 分配任务但 agent 没有活跃的 MCP session（离线）时，Agora 通过 Matrix 协议发送 @mention 消息唤醒 agent。Agent 的 Hermes 实例通过 Matrix gateway 收到消息后，自动通过 MCP 连接 Agora 拉取任务。

```
┌─────────────────────────────────────────────────────────┐
│                    Agora Server                          │
│  ┌──────────────┐    ┌──────────────────────────────┐   │
│  │ Agora Core   │    │ MatrixWakeupClient           │   │
│  │ (task assign)│───►│ (matrix-nio AsyncClient)     │   │
│  └──────────────┘    └──────────┬───────────────────┘   │
│                                 │                         │
│  ┌──────────────┐              │                         │
│  │ MCP Server   │◄─────────────┼─────────────────────────┼──┐
│  │ (/mcp)       │              │                         │  │
│  └──────────────┘              ▼                         │  │ MCP
│                         ┌──────────────┐                 │  │ (agent→server)
│                         │ Dendrite     │                 │  │
│                         │ (Matrix HS)  │                 │  │
│                         └──────┬───────┘                 │  │
└────────────────────────────────┼─────────────────────────┘  │
                                 │ Matrix protocol            │
                                 │ (双向，穿透 NAT)            │
                                 ▼                            │
                    ┌──────────────────────┐                  │
                    │ Hermes Agent         │──────────────────┘
                    │ (Matrix gateway)     │
                    │ Room: #agora-wakeup  │
                    └──────────────────────┘
```

## 1. 部署 Dendrite Matrix Homeserver

### 1.1 Docker Compose

```yaml
# /opt/matrix/dendrite/docker-compose.yml
services:
  postgres:
    image: postgres:16-alpine
    container_name: dendrite-postgres
    restart: unless-stopped
    environment:
      POSTGRES_USER: dendrite
      POSTGRES_PASSWORD: dendritepass
      POSTGRES_DB: dendrite
    volumes:
      - ./postgres:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U dendrite"]
      interval: 5s
      timeout: 5s
      retries: 5

  dendrite:
    image: matrixdotorg/dendrite-monolith:latest
    container_name: dendrite
    restart: unless-stopped
    depends_on:
      postgres:
        condition: service_healthy
    ports:
      - "8008:8008"
      - "8448:8448"
    volumes:
      - ./config:/etc/dendrite
    command: -config /etc/dendrite/dendrite.yaml
```

### 1.2 Dendrite 配置

关键配置项（`/opt/matrix/dendrite/config/dendrite.yaml`）：

```yaml
server_name: "agora.local"

database:
  connection_string: "postgresql://dendrite:dendritepass@postgres:5432/dendrite?sslmode=disable"

client_api:
  registration_disabled: false    # 允许注册
  guests_disabled: true
  login_password_enabled: true

federation:
  federation_disabled: true       # 内网用途，关闭 federation

key_server:
  database:
    connection_string: "postgresql://dendrite:dendritepass@postgres:5432/dendrite?sslmode=disable"
```

### 1.3 生成 TLS 证书和签名密钥

```bash
# 生成 TLS 自签名证书
openssl req -x509 -newkey rsa:4096 -keyout /opt/matrix/dendrite/config/tls.key \
  -out /opt/matrix/dendrite/config/tls.crt -days 3650 -nodes \
  -subj "/CN=agora.local"

# 生成 Matrix ed25519 签名密钥
docker run --rm -v /opt/matrix/dendrite/config:/etc/dendrite \
  matrixdotorg/dendrite-monolith:latest \
  -config /etc/dendrite/dendrite.yaml -generate-keys
```

### 1.4 启动

```bash
cd /opt/matrix/dendrite
docker compose up -d
```

验证：`curl http://localhost:8008/_matrix/client/versions`

## 2. 创建 Matrix Bot 账号和 Room

### 2.1 注册 Agora Bot 账号

```bash
curl -X POST http://localhost:8008/_matrix/client/v3/register \
  -H "Content-Type: application/json" \
  -d '{
    "username": "agora-bot",
    "password": "your-bot-password",
    "auth": {"type": "m.login.dummy"}
  }'
```

### 2.2 获取 Bot Access Token

```bash
curl -X POST http://localhost:8008/_matrix/client/v3/login \
  -H "Content-Type: application/json" \
  -d '{
    "type": "m.login.password",
    "identifier": {"type": "m.id.user", "user": "agora-bot"},
    "password": "your-bot-password"
  }'
```

返回的 `access_token` 用于 Agora 配置。

### 2.3 创建 Wakeup Room

```bash
curl -X POST "http://localhost:8008/_matrix/client/v3/createRoom?access_token=BOT_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Agora Wakeup",
    "topic": "Agent wakeup notifications from Agora",
    "preset": "public_chat"
  }'
```

记录返回的 `room_id`（如 `!ThjFu3Ngw9JvfbRZ:agora.local`）。

## 3. 配置 Agora

### 3.1 环境变量

```bash
# Matrix wakeup
AGORA_MATRIX_HOMESERVER_URL=http://localhost:8008
AGORA_MATRIX_ACCESS_TOKEN=<bot-access-token>
AGORA_MATRIX_WAKEUP_ROOM_ID=<room-id>

# Agora 基础配置
AGORA_AUTH_MODE=none              # 内网测试用 none，生产用 rbac
AGORA_REQUIRE_APPROVAL=false      # 自动批准 agent 注册
AGORA_HOST=0.0.0.0
AGORA_PORT=8765
```

### 3.2 启动 Agora

```bash
cd /path/to/agora
AGORA_MATRIX_HOMESERVER_URL=http://localhost:8008 \
AGORA_MATRIX_ACCESS_TOKEN=<bot-token> \
AGORA_MATRIX_WAKEUP_ROOM_ID=<room-id> \
AGORA_AUTH_MODE=none \
AGORA_REQUIRE_APPROVAL=false \
python -m agora.coordinator.main
```

日志中应看到：
```
Matrix wakeup configured: homeserver=http://localhost:8008 room=!xxx:agora.local
Matrix wakeup enabled
```

## 4. 配置 Hermes Agent

### 4.1 MCP Server 配置

在 Hermes profile 的 `config.yaml` 中：

```yaml
mcp_servers:
  agora:
    url: http://localhost:8765/mcp
    headers:
      Authorization: "Bearer <agent-token>"
    timeout: 300
```

> **注意**：在 `none` auth 模式下，Bearer token 可以为任意值。Agent 身份通过 `register_agent` 工具调用时的 MCP session ID 解析。

### 4.2 注册时声明 Matrix User ID

Agent 通过 MCP 调用 `register_agent` 时，在 `metadata` 中传入 `matrix_user_id`：

```python
await session.call_tool("register_agent", {
    "name": "coder",
    "capabilities": ["coding", "testing"],
    "agent_type": "hermes",
    "metadata": {
        "matrix_user_id": "@coder:agora.local"
    }
})
```

### 4.3 Hermes Matrix Gateway（可选）

如果希望 Hermes agent 自动响应 Matrix @mention，配置 Hermes 的 Matrix gateway：

```yaml
# ~/.hermes/config.yaml
matrix:
  homeserver: http://localhost:8008
  access_token: <agent-matrix-token>
  user_id: "@coder:agora.local"
```

## 5. 唤醒流程

```
1. Agora 给 agent 分配任务
2. Agora 检查 agent 是否有活跃 MCP session
   ├─ 有 session → SSE 推送通知
   └─ 无 session → 进入离线流程
3. 离线流程：
   a. 通知入队到 pending_notifications 表
   b. MatrixWakeupClient 在 wakeup room 发消息：
      "@coder:agora.local 🔔 You have N pending tasks"
   c. Hermes Matrix gateway 收到 @mention
   d. Hermes 被触发，通过 MCP 连接 Agora
   e. Agent 调用 fetch_pending_notifications 拉取任务
   f. Agent 执行任务，submit_task_result 提交结果
```

## 6. 故障排查

### `get_pending_tasks` 返回空

检查 Agora 日志中 `resolved agent_id=` 的值：
- 如果是 `ag-xxxx`（token 本身）→ Bearer token 与 DB 不匹配，检查 Hermes config 中的 token
- 如果是 `unknown` 或 `None` → session_map 未注册，确保 agent 先调用了 `register_agent`

### Matrix 唤醒消息未发送

1. 检查 agent 的 `matrix_user_id` 是否已存入 DB：
   ```sql
   SELECT agent_id, name, matrix_user_id FROM agents;
   ```
2. 检查 Agora 日志中是否有 `Matrix wakeup configured` 和 `Sent Matrix wakeup`
3. 检查 bot 是否已加入 wakeup room：
   ```bash
   curl "http://localhost:8008/_matrix/client/v3/joined_rooms?access_token=BOT_TOKEN"
   ```

### `pending_notifications` 报 `ValueError: minute must be in 0..59`

已修复（v0.18.0）。确保 `pending_notifications.py` 使用 `timedelta` 而非 `datetime.replace(minute=...)`。
