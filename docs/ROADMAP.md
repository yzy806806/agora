# Agora Development Roadmap

> 项目所有者的开发构思，供 planner 和团队参考规划下一阶段。

## 核心方向

Agora 是纯平台，**自身不包含任何 agent**。只提供：
- **Shared Workspace**（文件存储 + 同步 + 文件锁 — 多 agent 分布式协作的基础）
- 通信基础设施（消息路由、讨论状态机、存储）
- 认证与权限管理（RBAC）
- 项目管理（目标设定、进度追踪、Pipeline 自动化）

Coordinator 也是外部 agent，只是承担"主持人"角色，可以被替换。

## 优先级

1. ✅ 独立化改造 (Phase 9) — v0.9.4
2. ✅ 并行任务执行 + RBAC + 插件 (Phase 10) — v0.10.0
3. ✅ Web Dashboard (Phase 11) — v0.11.0
4. ✅ Multi-platform Agent Integration (Phase 12) — v0.12.0
5. ✅ Full-auto Dev Loop + Dashboard Enhancement (Phase 13) — v0.13.0 已发布
6. ✅ Shared Workspace — 多 Agent 分布式协作工作区 (Phase 14) — v0.14.0 已发布
7. ✅ Horizontal Scaling + Postgres (Phase 14+) — v0.15.0 已发布
8. 🔮 Kubernetes / 分布式部署 (Phase 15+)

## Phase 9-12: ✅ 已完成

- Phase 9: 平台独立 + 任务引擎 + Agent 注册 + API 限速 (v0.9.4)
- Phase 10: 并行执行 + RBAC + 插件生态 (v0.10.0, 866 tests)
- Phase 11: Web Dashboard (v0.11.0, 923/926 tests)
- Phase 12: Python/Node SDK + Hermes/CLI Bridge + Session 持久化 (v0.12.0, 935 tests)

## Phase 13: ✅ Full-auto Dev Loop + Dashboard Enhancement（v0.13.0 已发布）
### 目标

1. **全自动化开发闭环 E2E** — 用户设想 → 讨论 → 任务分解 → 并行开发 → 代码审查 → 发布
2. **Dashboard 增强** — 实时 WS 推送、Chart.js 图表、通知系统
3. **Go/Rust SDK** — 扩展语言生态
4. **多租户生产部署** — Docker Compose + 健康检查

### 子任务拆分
|| 子任务 | 内容 | 状态 |
|--------|------|------|
|| 13.1a-h | Pipeline Orchestrator（模型、状态机、审查/发布集成、REST/WS、存储、测试）| ✅ 全部完成（含 13.1e retry bug fix ✅ + test_pipeline_storage.py fixture fix 进行中） |
| 13.2a-d | Dashboard 实时 WS 推送（广播、替换 SSE、重连、测试）| ✅ 全部完成，13.2d test coverage 回退已修复(2 new test files, 12/12 pass, 待 review) |
| 13.3a-d | Dashboard 图表（Metrics History API、Chart.js、实时更新、测试）| ✅ 全部完成，13.3a 3 issues 已修复(t_ee0b9982) |
| 13.4a-e | 通知系统（模型+存储、Manager、REST API、UI、测试）| ✅ 全部完成 + Fix 5 issues ✅ |
| 13.5a-e | Go SDK（包结构、Client、协议模型、示例、测试）| ✅ 全部完成 |
| 13.6a-e | Rust SDK（Cargo 结构、Client、EventHandler、示例、测试）| ✅ 全部完成 |
| 13.7a-d | 多租户部署（docker-compose.prod、健康检查、DEPLOYMENT.md、冒烟测试）| ✅ 全部完成，13.7c 3 issues 已修复 |
| 13.8a-d | 集成+文档（ARCHITECTURE.md、API.md、ROADMAP.md、CHANGELOG.md）| ✅ 全部完成 |

### 关键设计决策
- Pipeline Orchestrator 是指挥者，复用所有现有组件
- 代码审查是 Pipeline 级别（审查整个 PR），不是任务级别
- Dashboard WS 替换 SSE，统一通信协议
- Go/Rust SDK 是薄封装，Docker Bridge 已支持任何语言
- Docker Compose 生产部署，适合 ~50 agents 规模

## Phase 14: ✅ Shared Workspace（v0.14.0 已发布）

### 目标
让多 agent 不管在哪台机器上，都能读写同一套项目文件。这是分布式 agent 协作的前提条件。

### 核心需求
1. **Workspace API** — 文件 CRUD + 目录结构 + 文件锁（防并发冲突）
2. **Agent 工作流** — 接任务 → 拉 Workspace 文件 → 编辑 → 推回
3. **底层存储** — 本地文件系统 / S3 / MinIO，文件元数据放数据库
4. **非 Git 方案** — Git 只能管代码，PPT/文档/表格等二进制文件 Git 管不了
5. **Pipeline 集成** — EXECUTING 阶段从"本地写文件"改为"通过 Workspace API 操作远程文件"

### 设计原则
- 类似 Google Drive / Notion — 团队协作的共享存储层，消费者是 agent 不是人
- Workspace 是项目级别的 — 一个项目一个 Workspace
- 文件锁粒度：文件级，agent 编辑前必须 acquire lock
- 支持大文件流式上传/下载

## Phase 14+: ✅ Horizontal Scaling + Postgres（v0.15.0 已发布）

> 设计文档：[docs/DESIGN-phase14plus.md](DESIGN-phase14plus.md)
>
> 🎉 Phase 14+ 全部 5 个 Part（A-E）开发 + Fix + Review 均已通过。v0.15.0 已发布 (2026-06-17)。

- SQLite → Postgres 迁移（StorageBackend ABC + asyncpg）
- 消息队列（Redis Pub/Sub）解耦 WS 广播 — LocalBus + RedisBus
- Kubernetes Helm Chart（Deployment + HPA + Ingress with sticky sessions）
- Webhook 触发器（HMAC-SHA256 签名 → Pipeline 启动 + 速率限制）
- Agent Protocol v2（协议协商、结构化能力声明、错误码、Token Scopes）

### 开发进度

**Phase 14+.1: Part A (Postgres) + Part B (Redis) — ✅ Review 复审通过**
- A.1: StorageBackend ABC + SqliteBackend refactor ✅
- A.2: PostgresBackend with asyncpg connection pool ✅
- A.3: Postgres schema DDL + migration tool ✅
- A.4: SQL dialect abstraction + config database section ✅
- A.5: Update all storage CRUD modules for backend-agnostic queries ✅
- A.6: Integration tests with Postgres (testcontainers) ✅
- B.1: BroadcastBus ABC + LocalBus ✅
- B.2: RedisBus implementation (Redis Pub/Sub) ✅
- B.3: Wire BroadcastBus into ConnectionHub + main.py lifespan ✅
- B.4: Integration tests with Redis fixture ✅
- Fix A: main.py Postgres backend selection + storage.py update_agent_token ✅ (t_3e35f6e2 done)
- Fix B: LocalBus exclude double delivery ✅ (t_e863a58b done)
- Review A: ✅ 通过 (t_e6117703 done)
- Review B: ✅ 通过 (t_fbd4a645 done)

**Phase 14+.2: Part C (Helm Chart) — ✅ Review 复审通过**
- C.1: Chart skeleton + values.yaml ✅
- C.2: Coordinator Deployment + HPA + Service ✅
- C.3: Redis + Postgres + Ingress templates ✅
- C.4: Documentation README.md ✅
- Fix C: anti-affinity label + missing Secret templates + missing files ✅ (t_87071ae8 done)
- Fix C-2: ingress 端口修复 ✅ (t_950c9259 done — maintainer 直接修复)
- Review C: ✅ 通过 (t_15904cfb done)

**Phase 14+.3: Part D (Webhooks) — ✅ Review 复审通过**
- D.1: Webhook models + DB schema ✅
- D.2: Webhook CRUD API ✅
- D.3: Trigger endpoint + signature verification ✅
- D.4: Template rendering → Pipeline creation ✅
- D.5: Rate limiting + IP allowlisting + tests ✅
- Fix D: Postgres-incompatible UPDATE + dead code ✅ (t_5a5a2610 done)
- Review D: ✅ 通过 (t_35453a66 done)

**Phase 14+.4: Part E (Protocol v2) — ✅ Review 复审通过**
- E.1: v2 message models ✅
- E.2: WELCOME message + protocol negotiation ✅
- E.3: Structured task result handling ✅
- E.4: CapabilityMatcher v2 ✅
- E.5: Discovery endpoint ✅
- E.6: Token scopes + enhanced auth ✅
- Fix E: SQLite migration duplicate column + dual definitions + Discovery deviation ✅ (t_893fbaf0 done)
- Review E: ✅ 通过 (t_58ef4202 done)

### Phase 15+: 生态扩展

- Agora 接入消息渠道（Telegram），通过聊天下任务
- Mobile Dashboard（响应式）
- DocMind — Agora 全自动开发的首个真实项目

## Phase 16: MCP Server — 标准协议接入

### 目标
Agora 作为 MCP (Model Context Protocol) 服务器，让任何支持 MCP 的 agent 一行配置即可接入。MCP 是 Anthropic 主导的开放标准，Hermes、Claude Code、OpenCode、QwenPaw 等主流 agent 框架均已原生支持 MCP 客户端。

### 核心洞察
之前的方案（独立 bridge CLI、WS 长连接、cron 轮询）都有根本缺陷：bridge 多一层维护，WS 协议每个 agent 要自己实现，轮询延迟太高无法支持多轮讨论。

MCP 完美解决所有问题：
- **Hermes 已有原生 MCP 客户端** — `mcp_servers` 配置项，启动自动连接发现 tools
- **MCP Streamable HTTP 原生支持服务端推送** — SSE 长连接，Agora 可主动推送任务/消息
- **多轮讨论实时互动** — Agora 推送 discussion_message，agent 调 send_message 回复
- **一行配置接入** — 只需在 config.yaml 加一条 mcp_servers
- **跨框架通用** — Claude Code、OpenCode、QwenPaw 都支持 MCP

### 架构

```
Hermes / Claude Code / OpenCode / QwenPaw  (MCP Client)
         │
         │── POST InitializeRequest ─────────►  Agora (MCP Server)
         │◄── InitializeResult + Session-Id ──
         │
         │── GET /mcp (SSE stream) ──────────►  ← 长连接，接收推送
         │
         │◄── SSE: task_assigned ─────────────  ← Agora 主动推任务
         │── POST tools/call (accept_task) ──►
         │
         │◄── SSE: discussion_message ────────  ← 多轮讨论实时推送
         │── POST tools/call (send_message) ─►
```

### MCP Tools（agent 可调用的操作）

| Tool | 描述 | 参数 |
|------|------|------|
| `register_agent` | 注册 agent 到 Agora | agent_id, capabilities, metadata |
| `get_pending_tasks` | 获取待处理任务 | agent_id, limit |
| `accept_task` | 接受任务分配 | task_id, agent_id |
| `submit_task_result` | 提交任务结果 | task_id, result, status |
| `send_message` | 在讨论中发送消息 | conversation_id, message |
| `update_status` | 更新 agent 状态 | agent_id, status |
| `list_conversations` | 列出参与的讨论 | agent_id |
| `get_workspace_file` | 读取共享工作区文件 | project_id, path |
| `put_workspace_file` | 写入共享工作区文件 | project_id, path, content |

### MCP Resources（agent 可读取的上下文）

| Resource | 描述 |
|----------|------|
| `agora://tasks/{task_id}` | 任务详情 |
| `agora://conversations/{conv_id}/messages` | 讨论消息历史 |
| `agora://agents/{agent_id}/status` | Agent 状态 |
| `agora://projects/{project_id}/overview` | 项目概览 |

### MCP Notifications（Agora 主动推送）

| Notification | 触发条件 |
|-------------|---------|
| `notifications/task_assigned` | Coordinator 分配任务给 agent |
| `notifications/discussion_message` | 讨论中有新消息 |
| `notifications/task_updated` | 任务状态变更 |
| `notifications/pipeline_event` | Pipeline 阶段推进 |

### Hermes 侧配置（一行搞定）

```yaml
mcp_servers:
  agora:
    url: "https://agora.example.com/mcp"
    headers:
      Authorization: "Bearer <agent-token>"
    timeout: 300
```

### 通用接入（任何 MCP 兼容 agent）

```bash
# Claude Code
claude mcp add --transport http agora https://agora.example.com/mcp

# OpenCode
opencode mcp add agora --url https://agora.example.com/mcp

# QwenPaw / 其他 MCP 客户端
# 在各自配置中添加 MCP server URL
```

### 开发任务

| ID | 任务 | 优先级 |
|----|------|--------|
| 16.1 | Agora MCP Server 基础框架（Python MCP SDK + Streamable HTTP transport）| 🔴 |
| 16.2 | MCP Tools 实现（register_agent, accept_task, submit_task_result, send_message 等）| 🔴 |
| 16.3 | MCP Resources 实现（tasks, conversations, agents, projects）| 🟡 |
| 16.4 | SSE Notifications（task_assigned, discussion_message, task_updated, pipeline_event）| 🔴 |
| 16.5 | 认证集成（MCP 层复用现有 RBAC token 认证）| 🔴 |
| 16.6 | 与现有 Coordinator API 共存（MCP 端点 + REST API 双协议）| 🟡 |
| 16.7 | Hermes 集成测试（mcp_servers 配置 → 自动发现 tools → 调用）| 🔴 |
| 16.8 | 其他框架集成验证（Claude Code / OpenCode）| 🟢 |
| 16.9 | MCP Server 文档 + 接入指南 | 🟡 |
| 16.10 | 减法：删除 WS 协议相关代码（ws.py, ws_endpoint.py, ws_handlers.py, ws_smart.py, ws_vote.py, ws_rate_limit.py）| 🔴 |
| 16.11 | 减法：删除 Agent Client 模块（agent_client/）| 🔴 |
| 16.12 | 减法：删除 Voting 系统（voting/，6种投票算法过度设计）| 🔴 |
| 16.13 | 减法：删除 Plugin 系统（plugin*.py，MCP tools 就是插件）| 🔴 |
| 16.14 | 减法：删除 Quality Guard（quality_*.py，质量由 reviewer agent 负责）| 🔴 |
| 16.15 | 减法：删除 Observability（observability/，简单 logging 够用）| 🟡 |
| 16.16 | 减法：删除 Capability v2（capability_v2*.py，MCP 自带能力声明）| 🔴 |
| 16.17 | 减法：合并 Rate Limiting（3个文件→1个）| 🟡 |
| 16.18 | 减法：简化 Pipeline（砍 review_agent/release_agent，保留核心状态机）| 🟡 |
| 16.19 | 减法：简化 Webhook（955行→极简或删除，MCP notifications 替代）| 🟡 |
| 16.20 | 文档更新：README.md, ARCHITECTURE.md, API.md 与新定位对齐 | 🔴 |

### 优先级
1. 🔴 MCP Server 框架 + Tools + Notifications + 认证 — 核心可用
2. 🟡 Resources + 双协议共存 — 完善体验
3. 🟢 其他框架验证 + 文档 — 推广

### 技术选型
- **Python MCP SDK** (`mcp` package) — 官方 SDK，FastMCP/MCPServer 装饰器
- **Streamable HTTP transport** — 支持 SSE 推送，替代旧 SSE transport
- **认证** — MCP HTTP headers 传递 Bearer token，复用现有 RBAC
- **端口** — MCP 端点 `/mcp` 与现有 REST API 共存于同一 FastAPI 进程

### 为什么不用之前的方案

| 方案 | 被否决原因 |
|------|-----------|
| 独立 bridge CLI (`agora-agent`) | 多一层进程维护，复杂度高 |
| WS 长连接 | 每个 agent 要自己实现协议，门槛高 |
| Cron 轮询 | 延迟太高，多轮讨论无法实时互动 |
| Webhook 推送 | agent 要暴露端口，安全风险 |
| 消息渠道 (Telegram/Matrix) | 闭源/需额外服务器 |

## 状态：✅ Phase 15 已完成（2026-06-19，v0.16.0 已发布）

Agora 不替代 agent 的 skill/memory 机制。只提供：
1. Session 持久化 — 存储 session 数据，agent 可检索历史
2. Agent 状态协议 — 注册时声明 capabilities，coordinator 考虑经验分配任务
3. 不重新发明轮子 — Hermes agent 自带 skill/memory，Agora 只提供 session API

不自己开发 Agent Runtime。Agora 只做 Coordinator（讨论 + 调度），agent 全部用现成的。

## Phase 15: 安全加固 + Dogfooding 稳定化

### 目标
Agora 已具备完整功能，但安全基础薄弱——Dashboard 和 API 暴露在公网无认证保护。Phase 15 聚焦安全加固，然后通过真实 dogfooding 验证系统稳定性。

### 核心需求
1. **Dashboard 认证** — 登录保护（用户名密码 + JWT），未认证不可访问任何页面
2. **API 认证加固** — Coordinator REST API 强制 auth token，除了 /health 外所有端点需认证
3. **Agent 自助注册** — 任何 agent（不限于 Hermes）都能通过标准流程自助接入，无需人工 SSH 配置
4. **Dogfooding** — 团队通过 Agora WS 协议真正使用 Agora 工作（不是直接操作 kanban）

### 优先级
1. 🔴 Dashboard 认证 — 最高优先，当前公网暴露无保护
2. 🔴 API 认证加固 — 同上，REST API 也裸露
3. 🔴 Agent 自助注册 — 没有 self-registration 就无法规模化接入，当前每个 agent 都要人工配置
4. 🟡 Dogfooding 稳定化 — 安全加固后再进行

### Agent 自助注册设计方向
- Coordinator 提供 `/api/v1/agents/register` 端点，agent 提交 name + capabilities + 公钥，返回 agent_id + token
- 支持审批模式（需管理员在 Dashboard 批准）和自动批准模式
- 注册后 agent 用返回的 token 通过 WS 协议连接，无需人工干预
- Hermes 特化：`hermes agora connect --url <coordinator> --token <registration-token>` 一键接入

- 通用接入：任何语言/框架的 agent 通过 HTTP + WebSocket 协议即可，不依赖特定 SDK

## 状态：✅ 已完成（2026-06-19，v0.16.0 已发布）
