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
6. 🔴 Shared Workspace — 多 Agent 分布式协作工作区 (Phase 14 最高优先级)
7. 🔮 Horizontal Scaling + Postgres (Phase 14+)
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

## Phase 14: 🟡 Shared Workspace（代码+审查全部完成，v0.14.0 发布中）

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

## Phase 14+: 🔮 Horizontal Scaling + Postgres

- SQLite → Postgres 迁移（支持多实例 Coordinator）
- 消息队列（Redis Streams / NATS）解耦 WS 广播
- Kubernetes Helm Chart（替代 Docker Compose）
- Webhook 触发器（外部事件 → Pipeline 启动）
- Agent Protocol v2（基于多平台实践经验修订）

### Phase 15+: 生态扩展

- Mobile Dashboard（响应式或原生 App）
- PicoClaw 适配器
- 插件市场（社区贡献的 Hook + Extension）
- DocMind — Agora 全自动开发的首个真实项目

## Agent 自我进化策略

Agora 不替代 agent 的 skill/memory 机制。只提供：
1. Session 持久化 — 存储 session 数据，agent 可检索历史
2. Agent 状态协议 — 注册时声明 capabilities，coordinator 考虑经验分配任务
3. 不重新发明轮子 — Hermes agent 自带 skill/memory，Agora 只提供 session API

不自己开发 Agent Runtime。Agora 只做 Coordinator（讨论 + 调度），agent 全部用现成的。
