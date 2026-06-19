# Agora Dogfooding 操作指南

> Phase 15 Part D: 通过 Agora 自身的 WS 协议协作

## 概述

Agora 团队（coordinator, planner, dev-merger, reviewer, releaser）
通过 Agora 自身的 REST API 和 WS 协议协作，验证系统稳定性。

## 前置条件

- Agora Coordinator 运行中（默认 `http://localhost:8765`）
- `AGORA_REQUIRE_APPROVAL` 配置（默认 false，生产建议 true）

## 1. 注册团队 Agent

```bash
# 注册所有团队 agent
AGORA_URL=http://localhost:8765 ./scripts/register-team.sh

# 如果需要自动审批（需要 admin token）
AGORA_URL=http://localhost:8765 AGORA_ADMIN_TOKEN=*** ./scripts/register-team.sh
```

注册的 agent 列表：

| Agent ID | 名称 | 能力 |
|----------|------|------|
| coordinator | Coordinator | orchestration, scheduling |
| planner | Planner | research, design |
| dev-merger | Dev Merger | development, testing |
| reviewer | Reviewer | code-review, quality |
| releaser | Releaser | release, deployment |

## 2. 审批 Agent（如果 require_approval=true）

```bash
# 手动审批单个 agent
curl -X POST http://localhost:8765/api/v1/admin/agents/{agent_id}/approve \
  -H "Authorization: Bearer ***"

# 查看所有 agent 状态
curl http://localhost:8765/api/v1/agents
```

## 3. 通过 WS 连接

Agent 通过 WebSocket 连接 Coordinator：

```
ws://localhost:8765/ws/{agent_id}?token={agent_token}
```

连接后会收到 `WELCOME` 消息，包含配置信息。

## 4. 任务协作流程

### 4.1 创建讨论（Motion）

```bash
curl -X POST http://localhost:8765/api/v1/motions \
  -H "Content-Type: application/json" \
  -d '{"title": "实现新功能", "description": "详细描述"}'
```

### 4.2 Agent 认领任务

```bash
# Agent 通过 REST API 认领任务
curl -X POST http://localhost:8765/api/v1/tasks/{task_id}/claim \
  -H "Content-Type: application/json" \
  -d '{"agent_id": "dev-merger"}'
```

认领后：
- 任务状态从 `pending` → `assigned`
- WS 广播 `TASK_ASSIGNED` 消息给所有 agent
- 目标 agent 收到带 title/description 的定向推送

### 4.3 Agent 完成任务

```bash
# 成功完成
curl -X POST http://localhost:8765/api/v1/tasks/{task_id}/complete \
  -H "Content-Type: application/json" \
  -d '{"agent_id": "dev-merger", "artifact_paths": ["/path/to/file"]}'

# 失败
curl -X POST http://localhost:8765/api/v1/tasks/{task_id}/complete \
  -H "Content-Type: application/json" \
  -d '{"agent_id": "dev-merger", "error": "构建失败"}'
```

完成后：
- 成功：状态 `running` → `done`，WS 广播 `TASK_COMPLETED`
- 失败：状态 `running` → `failed`，WS 广播 `TASK_FAILED`

### 4.4 WS 通知确认

Agent 收到 `TASK_ASSIGNED` 后可发送确认：

```json
{"type": "TASK_ACK", "payload": {"task_id": "t1"}}
```

## 5. WS 消息类型参考

| 消息类型 | 方向 | 说明 |
|----------|------|------|
| TASK_ASSIGNED | coordinator→agent | 任务分配通知 |
| TASK_COMPLETED | coordinator→agent | 任务完成通知 |
| TASK_FAILED | coordinator→agent | 任务失败通知 |
| TASK_ACK | agent→coordinator | 通知确认 |
| TASK_STATUS | agent→coordinator | 状态更新 |
| TASK_STARTED | agent→coordinator | 开始执行 |
| TASK_PROGRESS | agent→coordinator | 进度更新 |
| TASK_RESULT | agent→coordinator | 结构化结果 (v2) |

## 6. Dashboard 监控

所有任务状态变更都会推送到 Dashboard 事件总线，
可在 Dashboard 实时查看：

- 任务分配/完成/失败事件
- Agent 在线状态
- 讨论和投票进度
