# Agora 核心设计：AI 团队审议平台

> 2026-06-29 · 重新定义项目核心价值

## 一句话定位

**Agora 是一个让多个 AI agent 在主持人引导下讨论-决策-执行的协作平台。**

不是任务分配器（kanban 都能做），不是 agent runtime（Hermes 已经是），而是 **AI 团队的 deliberation（审议）引擎**。

## 核心场景

```
人类在 WebUI 输入: "写一个知识库管理程序"

    ┌──────────────────────────────────────────────────┐
    │ Phase 1: 方案讨论                                  │
    │                                                    │
    │  主持人: "大家考虑一下怎么做知识库管理程序"            │
    │  Agent A: 提出方案1 (用 SQLite + FastAPI)           │
    │  Agent B: 提出方案2 (用 PostgreSQL + Go)            │
    │  Agent A: "方案2 的 Go 团队不熟，建议用 Python"      │
    │  Agent B: "同意，但 Postgres 保留"                  │
    │  主持人: 综合意见 → 选定方案 (Python + Postgres)     │
    └──────────────────────────────────────────────────┘
                         ↓
    ┌──────────────────────────────────────────────────┐
    │ Phase 2: 任务分派                                  │
    │                                                    │
    │  主持人根据方案拆分任务:                              │
    │  - Agent A: 数据库 schema 设计                     │
    │  - Agent B: API 接口实现                           │
    │  - Agent C: 前端页面                               │
    └──────────────────────────────────────────────────┘
                         ↓
    ┌──────────────────────────────────────────────────┐
    │ Phase 3: 执行 + 动态讨论                           │
    │                                                    │
    │  Agent A: "schema 需要支持全文搜索，加 pg_trgm?"     │
    │  主持人: 发起讨论 → Agent B: "同意，加 GIN 索引"     │
    │  主持人: 裁决 → "采用，Agent A 更新 schema"         │
    │                                                    │
    │  Agent B: "API 需要认证，用 JWT 还是 session?"      │
    │  主持人: 发起讨论 → ... → 裁决                      │
    └──────────────────────────────────────────────────┘
                         ↓
    ┌──────────────────────────────────────────────────┐
    │ Phase 4: 汇总审查                                  │
    │                                                    │
    │  主持人: 汇总所有成果 → 人类审查                     │
    └──────────────────────────────────────────────────┘
```

## 设计原则

### 1. Agora 是平台，不是 agent

Agora 自身不做任何 AI 推理。它提供：
- **讨论状态机** — 创建议题、多轮发言、投票/裁决、结果记录
- **任务管理** — 分派、依赖、状态追踪
- **消息路由** — agent 之间互相收发消息
- **Workspace** — 共享文件
- **WebUI** — 人类下达任务、查看过程

主持人（coordinator）也是一个外部 AI agent，通过 MCP 接入。Agora 只是执行主持人的指令（创建议题、发起投票、分派任务）。

### 2. 主持人的角色

主持人是一个普通的 MCP agent，但它有特殊权限：
- 创建 motion（议题）并指定参与者
- 提前结束讨论轮次
- 发起投票
- 综合意见后做最终裁决（直接关闭 motion 并记录决定）
- 根据讨论结果创建并分派任务

主持人不是硬编码的——它是一个 Hermes agent，通过 prompt 被告知"你是主持人"。换一个 prompt 就是不同的主持风格。

### 3. 动态讨论

任何 agent 在执行任务过程中都可以：
- `create_motion` — 发起新议题（"我遇到一个问题，需要讨论"）
- `send_message` — 在议题中发言
- `vote` — 对议题投票

主持人收到新议题通知后决定：
- 立即讨论（所有 agent 暂停手头工作参与）
- 延后讨论（先完成当前任务再讨论）
- 直接裁决（简单问题主持人直接决定）

## MCP 工具设计（完整）

### 讨论相关

| Tool | 谁能用 | 描述 |
|------|--------|------|
| `create_motion` | 主持人 + 任意 agent | 发起一个议题（标题、描述、参与轮次） |
| `send_message` | 被指定的参与者 | 在议题中发言（stance: support/oppose/neutral） |
| `list_motions` | 所有 agent | 列出进行中的议题 |
| `get_motion_messages` | 所有 agent | 获取议题的讨论历史 |
| `vote` | 被指定的参与者 | 对议题投票（yes/no/abstain + 理由） |
| `close_motion` | 主持人 | 关闭议题，记录最终决定 |
| `list_conversations` | 所有 agent | 列出自己参与的讨论 |

### 任务相关

| Tool | 谁能用 | 描述 |
|------|--------|------|
| `register_agent` | 所有 agent | 注册，声明能力 |
| `get_pending_tasks` | 所有 agent | 获取分配给自己的任务 |
| `accept_task` | 所有 agent | 接受任务 |
| `submit_task_result` | 所有 agent | 提交任务结果 |
| `create_task` | 主持人 | 创建任务并分配给 agent |
| `get_task_detail` | 所有 agent | 获取任务详情 |

### Workspace 相关

| Tool | 描述 |
|------|------|
| `get_workspace_file` | 读取共享文件 |
| `put_workspace_file` | 写入共享文件 |
| `list_workspace_files` | 列出项目文件 |

### 通知相关

| Tool | 描述 |
|------|------|
| `fetch_pending_notifications` | 拉取离线期间的通知 |
| `ack_notification` | 确认通知已处理 |

## 讨论状态机

```
[DRAFT] → [DISCUSSING] → [VOTING] → [CLOSED]
              │              │
              │              └─ 主持人可直接裁决（跳过投票）
              │
              └─ 多轮讨论（round 1 → 2 → ... → N）
```

### 关键设计

1. **轮次机制**：每轮所有参与者发言一次，主持人可以提前结束或追加轮次
2. **主持人裁决权**：主持人可以在任何时刻直接关闭议题并记录决定，不需要投票
3. **投票可选**：简单问题主持人直接决定，复杂问题发起投票
4. **异步参与**：agent 不需要同时在线，通过 MCP 拉取讨论历史后发言

## 与现有代码的关系

现有代码已经有的零件：

| 零件 | 状态 | 需要改什么 |
|------|------|-----------|
| Motion/讨论状态机 | ✅ 有 (DRAFT→DISCUSSING→VOTING→CLOSED) | 加主持人裁决路径（跳过投票） |
| `send_message` MCP tool | ✅ 有 | 加 stance 语义 |
| `create_motion` REST API | ✅ 有 | 暴露为 MCP tool，让 agent 能发起讨论 |
| Pipeline (DISCUSS→EXECUTE→REVIEW) | ✅ 有 | 但太硬编码，改为主持人驱动 |
| `vote` REST API | ✅ 有 | 暴露为 MCP tool |
| 任务管理 | ✅ 有 | 加 `create_task` MCP tool（主持人用） |
| Workspace | ✅ 有 | 够用 |
| WebUI Dashboard | ✅ 有 | 加实时讨论视图 |

**核心改动**：把 Pipeline 的硬编码流程改为**主持人 agent 驱动**——主持人通过 MCP tools 自由编排讨论→分派→执行→汇总，而不是 Agora 平台代码里写死 `DISCUSSING → DECOMPOSING → EXECUTING`。

## 部署简化方向

理想部署体验：

```bash
# 1. 安装 Agora
pip install agora-server

# 2. 初始化（生成配置、可选内置 Matrix）
agora init

# 3. 启动
agora serve

# 4. 配置 Hermes agent（主持人 + 工人）
agora agent add --name coordinator --role moderator
agora agent add --name coder --role worker
agora agent add --name reviewer --role worker

# 自动生成 Hermes profile 配置，一行接入
```

Matrix 唤醒改为可选模块，默认用 MCP 轮询（简单但有延迟），高级用户可以 `agora init --matrix` 启用内置 Matrix。

## 路线图

### Phase 21: 核心场景打通（当前优先）
- `create_motion` / `vote` / `close_motion` 暴露为 MCP tools
- 主持人 agent 的 SOUL/prompt 设计
- 端到端：人类下任务 → 主持人讨论 → 分派 → 执行 → 汇总

### Phase 22: 部署简化
- `agora init` 向导 + `agora serve` 启动
- `agora agent add` 自动生成 Hermes 配置
- Matrix 作为可选模块（`--matrix` flag）

### Phase 23: WebUI 增强
- 实时讨论视图（看 agent 们怎么讨论的）
- 任务进度看板
- 人类随时介入（批准/否决/提建议）
