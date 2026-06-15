# Agora 架构文档

> 版本: v0.13.0 | 最后更新: 2026-06-15

## 整体架构

```
                    ┌─────────────────────────────────┐
                    │       Coordinator Agent          │
                    │  (FastAPI + WebSocket 服务)       │
                    │  ┌──────────┐ ┌───────────────┐  │
                    │  │ REST API │ │ WebSocket Hub  │  │
                    │  └────┬─────┘ └──────┬────────┘  │
                    │       │    ┌─────────┤           │
                    │  ┌────▼────▼─┐ ┌─────▼────────┐  │
                    │  │ State     │ │ Smart Discuss │  │
                    │  │ Machine   │ │ Engine        │  │
                    │  └───────────┘ └──────────────┘  │
                    │  ┌───────────┐ ┌───────────────┐  │
                    │  │ Voting    │ │ Bootstrap     │  │
                    │  │ System    │ │ Engine        │  │
                    │  └───────────┘ └───────────────┘  │
                    │  ┌───────────┐ ┌───────────────┐  │
                    │  │ Fault     │ │ Quality       │  │
                    │  │ Tolerance │ │ Guard         │  │
                    │  └───────────┘ └───────────────┘  │
                    │  ┌───────────┐ ┌───────────────┐  │
                    │  │ Observ-   │ │ Tenant        │  │
                    │  │ ability   │ │ Manager       │  │
                    │  └───────────┘ └───────────────┘  │
                    │  ┌───────────┐ ┌───────────────┐  │
                    │  │ Parallel  │ │ RBAC          │  │
                    │  │ Task      │ │ Middleware    │  │
                    │  │ Coordinator│ │ + TokenMgr   │  │
                    │  └───────────┘ └───────────────┘  │
                    │  ┌───────────┐ ┌───────────────┐  │
                    │  │ Plugin    │ │ Resource      │  │
                    │  │ Manager   │ │ Tracker       │  │
                    │  └───────────┘ └───────────────┘  │
                    │  ┌───────────┐ ┌───────────────┐  │
                    │  │ Task      │ │ Agent         │  │
                    │  │ Execution │ │ Registry      │  │
                    │  │ Engine    │ │ + Auth        │  │
                    │  └───────────┘ └───────────────┘  │
                    │  ┌───────────┐ ┌───────────────┐  │
                    │  │ API Rate  │ │ Dashboard     │  │
                    │  │ Limiter   │ │ (static+WS)   │  │
                    │  └───────────┘ └───────────────┘  │
                    │  ┌───────────┐ ┌───────────────┐  │
                    │  │ Pipeline  │ │ Notification   │  │
                    │  │ Orchestr. │ │ Manager        │  │
                    │  └───────────┘ └───────────────┘  │
                    │  ┌───────────┐ ┌───────────────┐  │
                    │  │ Workspace │ │ Workspace     │  │
                    │  │ Manager   │ │ REST/WS API   │  │
                    │  └───────────┘ └───────────────┘  │
                    │  ┌───────────────────────────┐    │
                    │  │ Storage (SQLite)          │    │
                    │  └───────────────────────────┘    │
                    └────────────┬────────────────────┘
                                 │ WebSocket / REST
        ┌────────────────────────┼────────────────────────┐
        ↓                        ↓                        ↓
   ┌─────────┐            ┌─────────┐            ┌─────────┐
   │ Hermes  │            │ CLI     │            │ Custom  │
   │ Bridge  │            │ Bridge  │            │ HTTP    │
   │ (SDK +  │            │ (PTY +  │            │ Agent   │
   │ adapter)│            │ ToolAdp)│            │         │
   └─────────┘            └─────────┘            └─────────┘
```

## 项目目录结构

```
agora/
├── __init__.py              # 包初始化，版本声明
├── cli.py                   # CLI 入口: agora serve / agent
├── __main__.py              # python -m agora
├── pyproject.toml           # 构建配置 (hatchling)
├── Dockerfile               # Coordinator Docker 镜像
├── Dockerfile.agent         # Agent 镜像模板
├── docker-compose.yaml      # 开发环境编排
├── config.yaml              # 全局配置文件
├── config_defaults.yaml     # 配置默认值
├── agora/                   # 核心包
│   ├── __init__.py
│   ├── coordinator/         # 调度中心
│   │   ├── __init__.py
│   │   ├── main.py          # FastAPI 入口 + 生命周期
│   │   ├── config.py        # 配置（pydantic-settings）
│   │   ├── config_loader.py # YAML 配置加载
│   │   ├── models.py        # 数据模型 + 枚举
│   │   ├── state.py         # 讨论状态机
│   │   ├── router.py        # REST API 路由
│   │   ├── ws.py            # WebSocket 连接管理器
│   │   ├── ws_endpoint.py   # WS 端点 + 消息路由 + 认证
│   │   ├── ws_handlers.py   # 消息处理 + HEARTBEAT + 任务调度
│   │   ├── ws_smart.py      # 智能讨论评估
│   │   ├── ws_vote.py       # VOTE 处理 + 投票完成检测
│   │   ├── ws_rate_limit.py # WS 层速率限制集成
│   │   ├── capability.py    # Agent 能力模型
│   │   ├── token_rate_limiter.py # TokenBucket 算法 (Phase 9.4)
│   │   ├── rate_limiter.py  # 速率限制器 (TPM 增强)
│   │   ├── rate_limit_router.py  # 速率限制路由
│   │   ├── rate_limit_router2.py # 速率限制路由 v2
│   │   ├── rate_limit_flush.py   # 速率限制持久化
│   │   ├── timeout_checker.py # Agent 超时检测
│   │   ├── assessment.py    # 讨论评估引擎
│   │   ├── consensus_jump.py# 共识提前判断
│   │   ├── devils_advocate.py # 魔鬼代言人
│   │   ├── focus.py         # 分歧点聚焦
│   │   ├── dynamic_rounds.py# 动态轮次调整
│   │   ├── smart_scheduler.py # 智能调度
│   │   ├── realtime_evaluator.py # 实时评估
│   │   ├── quality_scorer.py# 质量评分
│   │   ├── quality_guard.py # 质量守卫
│   │   ├── quality_guard_checks.py # 质量检查函数
│   │   ├── quality_guard_models.py # 质量守卫数据模型
│   │   ├── perspective_ensurer.py # 视角保障
│   │   ├── role_assigner.py # 讨论角色分配
│   │   ├── model_capabilities.py # 模型能力识别
│   │   ├── curator.py       # 策略优化（进化闭环）
│   │   ├── memory_sync.py   # 讨论经验同步
│   │   ├── history_pattern.py # 历史模式分析
│   │   ├── similar_topic.py # 相似议题检索
│   │   ├── judgment_tracker.py # 判断追踪
│   │   ├── judgment_types.py # 判断类型定义
│   │   ├── conclusion_types.py # 结论类型定义
│   │   ├── heartbeat.py     # 心跳监控
│   │   ├── timeout.py       # 超时管理
│   │   ├── deadlock_prevention.py # 死锁预防
│   │   ├── input_validation.py # 输入验证 + 清洗
│   │   ├── task_models.py   # 任务数据模型 (Phase 9.2)
│   │   ├── task_assign.py   # 任务分配（能力匹配+轮询）
│   │   ├── task_exec.py     # 任务执行管理器
│   │   ├── task_gen/        # 任务生成子系统 (Phase 9.2)
│   │   │   ├── __init__.py
│   │   │   ├── generator.py # LLM 驱动任务分解
│   │   │   ├── heuristic.py # 启发式降级
│   │   │   ├── prompts.py   # 生成提示词
│   │   │   └── validation.py# 任务验证
│   │   ├── task_verify/     # 任务验证子系统 (Phase 9.2)
│   │   │   ├── __init__.py
│   │   │   ├── simple_check.py # 简单检查
│   │   │   ├── auto_check.py   # 自动检查
│   │   │   ├── accept_result.py # 接受结果
│   │   │   └── delegate.py   # 委托审查
│   │   ├── task_parallel.py # 并行执行协调器 (Phase 10.1)
│   │   ├── task_resource.py # 文件资源冲突检测 (Phase 10.1)
│   │   ├── rbac.py          # RBAC 中间件 + 权限检查 (Phase 10.2)
│   │   ├── token_manager.py # JWT Token 管理 (Phase 10.2)
│   │   ├── audit.py         # 审计日志 (Phase 10.2)
│   │   ├── plugin.py        # 插件基类 + HookPoint (Phase 10.3)
│   │   ├── plugin_manager.py # 插件协调器 (Phase 10.3)
│   │   ├── plugin_discovery.py # 插件发现 (Phase 10.3)
│   │   ├── plugin_sandbox.py # 插件沙箱 (Phase 10.3)
│   │   ├── plugin_extensions.py # 扩展点注册 (Phase 10.3)
│   │   ├── voting/          # 投票子系统
│   │   │   ├── __init__.py
│   │   │   ├── factory.py   # 投票策略工厂
│   │   │   ├── manager.py   # 投票管理器
│   │   │   ├── weighted.py  # 加权投票
│   │   │   ├── weighted_types.py # 加权类型
│   │   │   ├── weight_manager.py # 权重管理
│   │   │   ├── ranked_choice.py  # 排序选择投票
│   │   │   ├── approval_voting.py # 批准投票
│   │   │   ├── range_voting.py  # 评分投票
│   │   │   └── multiple_choice.py # 多选投票
│   │   ├── observability/   # 可观测性 (Phase 8)
│   │   │   ├── __init__.py
│   │   │   ├── metrics.py   # Prometheus 指标
│   │   │   ├── events.py    # 结构化事件
│   │   │   └── trace.py     # 追踪上下文
│   │   ├── tenant/          # 多租户 (Phase 8)
│   │   │   ├── __init__.py
│   │   │   ├── models.py    # Tenant + TenantConfig
│   │   │   ├── manager.py   # 租户 CRUD
│   │   │   ├── guard.py     # 资源限制
│   │   │   └── router.py    # 租户 API
│   │   ├── bootstrap/       # 自举系统
│   │   │   ├── __init__.py  # BootstrapEngine
│   │   │   ├── trigger_types.py # 触发器类型
│   │   │   ├── trigger_manager.py # 触发器管理
│   │   │   ├── schedule_checker.py # 定时检查
│   │   │   ├── task_generator.py # 议题生成
│   │   │   ├── discussion_driver.py # 讨论驱动
│   │   │   ├── approval_flow.py  # 审批流程
│   │   │   ├── bootstrap_schema.py # 自举数据模型
│   │   │   ├── routes.py    # Bootstrap REST 路由
│   │   │   └── routes_extra.py # 审批/调度路由
│   │   ├── storage/         # 数据存储层
│   │   │   ├── __init__.py  # Storage 入口
│   │   │   ├── schema.py    # 数据库 Schema (v7)
│   │   │   ├── storage.py   # 核心存储操作
│   │   │   ├── agents.py    # Agent 存储（含注册/审批/token）
│   │   │   ├── motions.py   # 议题存储
│   │   │   ├── messages.py  # 消息存储
│   │   │   ├── votes.py     # 投票存储
│   │   │   ├── tasks.py     # 任务存储 (Phase 9.2)
│   │   │   ├── agent_heartbeat.py # 心跳检测存储
│   │   │   ├── assessments.py  # 评估存储
│   │   │   ├── judgments.py # 判断存储
│   │   │   ├── bootstrap.py # 自举存储
│   │   │   ├── bootstrap_approval.py # 审批存储
│   │   │   ├── events.py    # 事件存储 (Phase 8)
│   │   │   ├── global_store.py # 全局数据库 (Phase 8)
│   │   │   ├── storage_manager.py # 多租户管理 (Phase 8)
│   │   │   ├── pipelines.py # Pipeline CRUD (Phase 13)
│   │   │   └── notifications.py # Notification CRUD (Phase 13)
│   │   ├── dashboard.py     # Dashboard API (Phase 8)
│   │   ├── dashboard_ws.py  # Dashboard WS fan-out (Phase 13)
│   │   ├── pipeline.py      # PipelineOrchestrator (Phase 13)
│   │   ├── pipeline_models.py # PipelineRun, PipelinePhase (Phase 13)
│   │   ├── pipeline_review_models.py # ReviewRequest/Result (Phase 13)
│   │   ├── pipeline_router.py # Pipeline REST API (Phase 13)
│   │   ├── pipeline_review.py # Code review phase (Phase 13)
│   │   ├── notifications.py # NotificationManager (Phase 13)
│   │   ├── workspace/       # 共享工作区 (Phase 14)
│   │   │   ├── __init__.py  # Workspace 入口
│   │   │   ├── models.py    # FileNode + FileLock 模型
│   │   │   ├── backend.py   # StorageBackend ABC
│   │   │   ├── local_backend.py # LocalFileBackend
│   │   │   ├── s3_backend.py    # S3Backend (MinIO/AWS)
│   │   │   ├── manager_base.py  # DB helpers (shared)
│   │   │   ├── manager.py       # WorkspaceManager (write)
│   │   │   ├── manager_ops.py   # WorkspaceManagerDirOps
│   │   │   ├── manager_dirs.py  # mkdir/rmdir
│   │   │   ├── manager_bulk.py  # pull_files/push_files
│   │   │   ├── manager_helpers.py # ReadOps mixin
│   │   │   ├── lock_manager.py   # LockManager
│   │   │   ├── ws_messages.py    # WS event emitters
│   │   │   ├── workspace_router.py # REST API (write)
│   │   │   ├── workspace_router_read.py # REST (read/stat)
│   │   │   ├── workspace_router_dirs.py # REST (dirs)
│   │   │   ├── workspace_router_locks.py # REST (locks)
│   │   │   ├── workspace_router_bulk.py  # REST (pull/push)
│   │   │   └── workspace_router_helpers.py # Shared deps
│   │   ├── notification_models.py # Notification model (Phase 13)
│   │   ├── notification_router.py # Notification REST API (Phase 13)
│   │   ├── health.py        # Health check endpoint (Phase 13)
│   │   └── static/          # Dashboard 前端 (Phase 8+13)
│   │       ├── dashboard.html
│   │       ├── dashboard.js
│   │       └── js/
│   │           ├── charts.js        # Chart.js viz (Phase 13)
│   │           ├── notifications.js # Notification UI (Phase 13)
│   │           └── ws_client.js     # WS client replaces SSE (Phase 13)
│   └── agent_client/        # Agent 客户端库
│       ├── __init__.py      # 导出 AgoraClient/AgoraConfig
│       ├── client.py        # HTTP + WS 客户端（含 RateLimitTracker）
│       ├── config.py        # 客户端配置
│       ├── rate_limit.py    # 客户端速率限制 (Phase 9.4)
│       └── ws_pool.py       # WS 连接池 + 自动重连
├── tests/                   # 测试（183 文件，1319 测试全部通过）
└── docs/                    # 设计文档
```

## 演进阶段与核心模块

| Phase | 主题 | 核心模块 | 说明 |
|-------|------|---------|------|
| 1 | MVP 基础 | main, config, models, state, router, ws, storage | 基本讨论+投票流程 |
| 2 | 智能讨论 | assessment, consensus_jump, devils_advocate, focus, dynamic_rounds, smart_scheduler, realtime_evaluator, voting/* | 实时评估+高级投票 |
| 3 | 记忆进化 | curator, memory_sync, history_pattern, similar_topic, judgment_tracker | 讨论经验沉淀+策略优化 |
| 4 | 自举系统 | bootstrap/* | Agora 讨论 Agora 自身 |
| 5 | 容错安全 | heartbeat, timeout, deadlock_prevention, input_validation, rate_limiter | 连接监控+输入防护 |
| 6 | 质量增强 | quality_guard, quality_scorer, perspective_ensurer, role_assigner, model_capabilities | 质量守卫+多模型差异 |
| 8 | 可观测性+多租户 | observability/*, tenant/*, dashboard, storage_manager | 指标暴露+事件追踪+多租户隔离+Dashboard |
| 9.1 | 平台独立化 | cli, pyproject.toml, Dockerfile, config.yaml, config_loader | `agora/` 包结构、pip 安装、Docker 部署 |
| 9.2 | 任务执行引擎 | task_models, task_gen/*, task_assign, task_exec, task_verify/* | 讨论→TaskGraph→分配→执行→验证 |
| 9.3 | Agent 注册协议 | AgentType/AgentStatus/AgentConfig 模型, token 认证, HEARTBEAT + capability | 标准化注册、审批、心跳、能力声明 |
|| 9.4 | API 速率限制 | TokenBucket, TokenRateLimiter, RateLimitTracker, ws_rate_limit | per-agent TPM 令牌桶限速 ||
|| 10.1 | 并行任务执行 | task_parallel, task_resource, ExecutionSlot, ResourceLock | DAG 依赖并行执行 + 文件资源冲突检测 ||
|| 10.2 | RBAC 权限控制 | rbac, token_manager, audit, Role, Permission, @requires | 角色权限 + JWT Token + 审计日志 ||
|| 10.3 | 插件生态 | plugin, plugin_manager, plugin_discovery, plugin_sandbox, plugin_extensions | Hook 系统 + 入口点发现 + 沙箱隔离 ||
|| 12 | 多平台 Agent 集成 | packages/agora-agent-sdk, packages/hermes-bridge, packages/cli-bridge, packages/agora-agent-sdk-js | Agent SDK + Hermes/CLI Bridge + Node.js SDK + Session 持久化 ||
|| 13 | 全自动开发循环 + Dashboard 增强 | pipeline*, notifications*, dashboard_ws, health, charts.js, ws_client.js, docker-compose.prod.yaml | Pipeline Orchestrator + WS Push + Charts + Notifications + Go/Rust SDK + 生产部署 ||
|| 14 | 共享工作区 | workspace/* | 虚拟文件系统 + 可插拔存储后端 + 文件锁 + 批量操作 + Pipeline 集成 ||

## 模块关系图

```
                          ┌─────────┐
                          │ main.py │ (FastAPI 入口)
                          └────┬────┘
                 ┌─────────────┼─────────────┐
                 ↓             ↓              ↓
           ┌──────────┐  ┌──────────┐  ┌───────────────┐
           │ router.py│  │ ws_ep.py │  │ bootstrap/*   │
           │(REST API)│  │(WS 端点) │  │(自举路由)      │
           └─────┬────┘  └────┬─────┘  └──────┬────────┘
                 │            │                │
                 ↓            ↓                ↓
           ┌──────────┐  ┌──────────────┐  ┌────────────┐
           │ state.py │  │ ws_handlers  │  │ approval_  │
           │(状态机)   │  │ ws_vote      │  │ flow.py    │
           └─────┬────┘  │ ws_smart     │  └────────────┘
                 │       │ task_assign  │
                 │       │ task_exec    │
                 │       └──────┬───────┘
                 │              │
    ┌────────────┼──────────────┼─────────────────┐
    ↓            ↓              ↓                 ↓
┌────────┐ ┌──────────┐ ┌──────────────┐ ┌─────────────┐
│storage │ │assessment│ │ voting/*     │ │ curator     │
│(SQLite)│ │consensus │ │(投票子系统)   │ │(策略优化)    │
│v7      │ │devils_adv│ │              │ │memory_sync  │
│        │ │focus     │ │              │ │history_pat  │
│        │ │quality*  │ │              │ │similar_topic│
│        │ │role_assign│ │              │ │judgment_trk │
│        │ │heartbeat │ │              │ └─────────────┘
│        │ │timeout   │ │              │
│        │ │deadlock  │ │              │  ┌─────────────┐
│        │ │rate_limit│ │              │  │ Phase 9.3:  │
│        │ │input_val │ │              │  │Agent Registry│
│        │ │          │ │              │  │capability   │
│        │ │          │ │              │  │timeout_chk  │
│        │ │          │ │              │  │             │
│        │ │          │ │              │  │ Phase 9.2:  │
│        │ │          │ │              │  │task_gen/*   │
│        │ │          │ │              │  │task_verify/*│
│        │ │          │ │              │  │             │
│        │ │          │ │              │  │ Phase 9.4:  │
│        │ │          │ │              │  │token_rate_l │
│        │ │          │ │              │  │ws_rate_limit│
│        │ │          │ │              │  │rate_limit_* │
└────────┘ └──────────┘ └──────────────┘  └─────────────┘
```

## 讨论状态机

```
draft ──(start)──→ discussing ──(start_voting)──→ voting ──(all_voted)──→ closed
                       │                              ↑
                  (assess)                            │
                       ↓                              │
                   assessing ──(start_voting)──────────┘
                       │           ↑
            (needs_devils_advocate) │
                       ↓           │
                devils_advocate ────┘
              (devils_advocate_done → discussing)

                          关闭后触发任务执行:
                      ┌───────────────────┐
                      │ Task Generator    │ → TaskGraph (DAG)
                      └───────┬───────────┘
                              ▼
                      ┌───────────────────┐
                      │ Task Assigner     │ → 能力匹配 + 轮询
                      └───────┬───────────┘
                              ▼
                      ┌───────────────────┐
                      │ Task Executor     │ → PENDING→ASSIGNED→RUNNING→DONE
                      └───────┬───────────┘
                              ▼
                      ┌───────────────────┐
                      │ Task Verifier     │ → ACCEPTED / REJECTED
                      └───────────────────┘
```

## 关键设计决策

1. **双协议通信**：REST API 用于 CRUD（创建议题、查结果），WebSocket 用于实时交互（发言、投票、任务执行）
2. **状态机驱动**：所有状态转换通过 StateMachine 统一管理，确保转换合法性
3. **投票策略模式**：voting/ 子系统通过 factory.py 按方法名创建投票策略实例
4. **存储分层**：storage/ 按实体拆分模块，统一通过 Storage 类访问
5. **进化闭环**：curator 分析讨论结果，优化后续调度策略
6. **客户端自动重连**：ws_pool.py 实现指数退避重连 + 请求-响应匹配
7. **可观测性三支柱**：Metrics (Prometheus) + Events (结构化日志) + Traces (请求追踪)
8. **多租户隔离**：per-tenant SQLite 实例，StorageManager 懒创建，默认租户保证向后兼容
9. **轻量 Dashboard**：纯 HTML+JS 前端，通过 REST API + SSE 获取数据，Chart.js 渲染 → Phase 13 升级为 WebSocket Push
10. **任务执行引擎**：讨论关闭后自动生成 TaskGraph (DAG)，按能力匹配分配 agent，通过 WS 消息驱动任务生命周期
11. **Agent 认证协议**：Token 认证（POST /register 获取 agent_token → WS 连接携带 token 验证），支持审批流（pending/approved）
12. **Token Bucket 限速**：per-agent TPM 令牌桶，支持 burst（默认 1.5x），coordinator 跟踪 + client 本地预检双重保障
13. **并行任务执行**：ParallelExecutionCoordinator 从 runqueue 分配任务，尊重 DAG 依赖和 per-agent 执行槽位上限，FileResourceTracker 检测文件级冲突并序列化
14. **RBAC 权限控制**：五角色体系（SUPERADMIN/ADMIN/AGENT/OBSERVER/PLUGIN）+ 15 细粒度权限，@requires 装饰器绑定端点，JWT Token 支持创建/轮换/撤销/作用域限定，审计日志追踪所有安全事件
15. **插件生态**：HookPoint 定义 20+ 生命周期事件（discussion/task/agent/system），AgoraPlugin ABC + PluginManifest，入口点发现（pip install），PluginCoordinator 管理加载/卸载/hook 触发，PluginSandbox 提供超时+导入限制
16. **Agent SDK 独立包**：`agora-agent-sdk` 与 coordinator 解耦，agent 无需安装完整 Agora，仅依赖 httpx + pydantic
17. **Hermes Bridge 守护进程**：不修改 Hermes 本身，桥接层翻译 kanban↔Agora WS 消息，支持多 profile 同时注册
18. **CLI Bridge PTY 模式**：不修改 CLI agent 本身，PTY 子进程 + ToolAdapter 统一不同工具调用格式
19. **Session 持久化在 Agora**：agent 通过 API 查询自身历史，不替代 agent 自身的 memory 机制
20. **制品存储为简单 KV**：足够存 conventions/notes/findings，大型制品留在 git/project 中
21. **Pipeline Orchestrator 为指挥者而非新引擎**：复用所有现有组件（讨论、Task DAG、并行执行、Bridge），仅添加编排层串联端到端流程
22. **Code Review 作为 Pipeline 阶段**：而非 Task 类型 — 在所有任务完成后审查整体 PR，不是逐个 commit
23. **Dashboard WS 替代 SSE**：SSE 是 Phase 8 临时方案，WebSocket 双向且已用于 agent 通信，统一 WS 减少代码路径
24. **Go/Rust SDK 为薄封装**：实现与 Python/Node.js SDK 相同协议，无需新服务端功能；Docker Bridge 已支持无 SDK 接入
25. **Docker Compose 用于生产部署**：单实例 + 健康检查 + 资源限制，~50 agents 足够；K8s 此阶段过度
26. **Notification 存储在 SQLite**：同库同备份策略，此规模无需独立消息队列
27. **Feedback Loop 复用 Session 持久化**：Pipeline 完成后 session record + artifacts 使下次迭代可学习，无需独立学习引擎
28. **元数据在 SQLite，内容在后端**：Workspace 将文件元数据（路径/大小/校验和/版本）存于 SQLite，文件字节存于可插拔 StorageBackend（LocalFileBackend 或 S3Backend），兼顾查询性能与存储扩展性
29. **路径优先 API**：Agent 思考方式是文件路径（"src/main.py"），Workspace API 直接使用路径而非 UUID，project_id 作为命名空间隔离
30. **读写锁语义**：读锁共享（多读者），写锁排他（单写者无读者）。写锁在 write_file/delete_file 时强制检查，读锁为建议性。锁 TTL 自动过期防死锁
31. **本地后端为默认**：零配置单机部署；S3 后端用于多主机分布式场景
32. **Bulk pull/push 优化任务流程**：最常见的模式是"任务开始拉取文件，任务结束推送变更"，批量端点优化此模式

## Phase 9.1: 平台独立化

### 包结构

原 `hermes-agora` 插件重构为独立的 `agora` Python 包：

```
agora/                      # pip install agora
├── cli.py                  # agora serve / agora agent
├── agora/coordinator/      # 调度中心
├── agora/agent_client/     # 客户端库
```

### 部署模式

| 模式 | 命令 | 用途 |
|------|------|------|
| 本地开发 | `agora serve` | 开发 Agora 本身 |
| Docker | `docker run agora-coordinator` | 生产环境、CI |
| docker-compose | `docker compose up` | 完整环境（coordinator + agents） |
| pip install | `pip install agora` | 作为库导入使用 |

### 配置文件

通过 `config.yaml` + `config_defaults.yaml` 进行全局配置，环境变量可覆盖。关键配置项：

- `coordinator.host/port` — 监听地址
- `coordinator.db_path` — 数据库路径
- `coordinator.require_approval` — 是否要求 agent 审批
- `agent.tpm_limit` — 默认 TPM 限制

## Phase 9.2: 任务执行引擎

### 数据模型

- **TaskNode**: 单个任务（id, title, description, status, assigned_to, required_capabilities, depends_on, artifact_paths）
- **TaskGraph**: 任务 DAG（id, motion_id, tasks）
- **TaskStatus**: PENDING → ASSIGNED → RUNNING → DONE → ACCEPTED/REJECTED，FAILED 终态

### 核心流程

1. **Task Generator** (`task_gen/`): 讨论关闭 → LLM 分解 action_items → TaskGraph（启发式降级）
2. **Task Assigner** (`task_assign.py`): 能力匹配 → 轮询分配 → 尊重 max_concurrent_tasks
3. **Task Executor** (`task_exec.py`): 状态机驱动，通过 WS 消息通信
4. **Task Verifier** (`task_verify/`): 简单检查 → 自动接受 → 委托审查

### WebSocket 任务消息

| 消息类型 | 方向 | 说明 |
|----------|------|------|
| TASK_ASSIGNED | server→agent | 分配任务 |
| TASK_STATUS | agent→server | 状态更新 (RUNNING/DONE/FAILED) |
| TASK_COMPLETED | agent→server | 任务完成 |
| TASK_FAILED | agent→server | 任务失败 |
| TASK_VERIFY | server→reviewer | 委托审查 |
| TASK_ACCEPT_RESULT | reviewer→server | 审查结果 |

## Phase 9.3: Agent 注册协议

### 注册流程

```
1. Agent → POST /api/v1/agents/register (含 agent_type, model, capabilities)
2. Coordinator → 201 {agent_token, status: approved|pending}
3. Agent → WS /ws/{agent_id}?token=ag-xxx
4. Coordinator 验证 token → WELCOME (含 AgentConfig)
5. Agent 定期发送 HEARTBEAT (30s) 更新 load + active_tasks
```

### 新增模型

- **AgentType**: hermes | docker | cli | custom — Agent 连接类型
- **AgentStatus**: pending | approved | rejected | suspended — 审批状态
- **AgentConfig**: max_concurrent_tasks, heartbeat_interval, tpm_limit, tpm_burst_factor, auto_accept_tasks
- **AgentRegistrationResponse**: agent_id, status, agent_token, message

### 认证机制

- 每个 agent 注册时获得唯一的 `agent_token`（UUID 格式）
- WS 连接必须携带 token（query 参数或 header）
- 支持 `AGORA_REQUIRE_APPROVAL` 环境变量切换审批模式
- 默认 auto-approve（本地开发）；生产环境需审批

### 心跳 + 在线追踪

- HEARTBEAT 消息每 30 秒（可配）发送，携带 load (0.0-1.0) 和 active_tasks 列表
- 120 秒无心跳 → agent 标记 offline
- 心跳存入 `agent_heartbeat` 表，用于在线追踪和负载均衡

## Phase 9.4: API 速率限制

### Token Bucket 算法

每个 agent 拥有独立的令牌桶：

- **容量**: `tpm_limit * burst_factor`（默认 burst=1.5x）
- **补充速率**: `tpm_limit / 60` tokens/秒
- **消耗**: 每次 LLM 调用前 `consume(n)`，成功则放行，失败则 rate limited

### 双重保障

1. **Coordinator 端**: `TokenRateLimiter` 在内存中 tracking，通过 REST API 提供状态查询
2. **Client 端**: `RateLimitTracker` 在 agent 端本地预检，避免无效 API 调用

### API 端点

```
GET  /api/v1/agents/{id}/rate-limit       → 查询限制状态
POST /api/v1/agents/{id}/rate-limit/report → 上报 token 消耗
POST /api/v1/agents/{id}/rate-limit/check  → 预检 tokens 是否充足
PATCH /api/v1/agents/{id}/rate-limit       → 管理员调整限制
```

### WebSocket 集成

- `RATE_LIMIT_WARNING`: 80% 用量 → notify agent
- `RATE_LIMITED`: 100% 用量 → block + 告知等待时间
- `RATE_LIMIT_RESET`: 令牌恢复 → 通知可继续
- `RATE_LIMIT_REPORT`: agent→coordinator 上报实际 token 消耗

## Phase 8: 可观测性

### 指标 (Metrics)

通过 `/api/v1/metrics` 端点暴露 Prometheus 格式指标：

- `agora_discussions_total` — 讨论总数（按状态分标签）
- `agora_agents_connected` — 当前连接 Agent 数
- `agora_votes_total` — 投票结果统计
- `agora_ws_messages_total` — WebSocket 消息量
- `agora_coordinator_uptime_seconds` — 运行时间
- 等共 20+ 指标

### 事件 (Events)

17 种 EventType 覆盖讨论生命周期、Agent 状态变更、投票、系统事件。
输出为 JSON Lines，支持 `?since=&type=` 过滤和 SSE 实时推送。

### 追踪 (Traces)

每个 HTTP 请求自动注入 `X-Trace-Id`（通过中间件），
WebSocket 消息携带 `trace_id` 字段，贯穿整个请求链路。

## Phase 8: 多租户

### 数据隔离

```
data/
  global.db                    # 全局：租户列表
  tenants/
    {tenant_id}/
      agora.db                 # 该租户的所有数据
```

### 租户模型

- `Tenant`: tenant_id, name, created_at, TenantConfig
- `TenantConfig`: max_agents, max_concurrent_discussions, quality_threshold 等
- `TenantResourceGuard`: 超限时抛出 HTTP 429

### 向后兼容

所有不带 `tenant_id` 的端点默认使用 `"default"` 租户，
WebSocket 通过 `?tenant_id=` 参数隔离连接。

## Phase 10.1: 并行任务执行

### 核心组件

- **ParallelExecutionCoordinator** (`task_parallel.py`): 维护 runqueue，追踪 per-agent 执行槽位，动态分配任务
- **FileResourceTracker** (`task_resource.py`): 检测文件级资源冲突，支持读写锁（多读者单写者）

### 数据模型

- **ExecutionSlot**: 追踪并发执行槽位（task_id, agent_id, started_at, status）
- **ResourceLock**: 文件资源锁（resource_path, locked_by, waiting_tasks, lock_type）
- **TaskGraph** 新增: parallel_mode (auto/sequential/parallel), max_parallel_slots, resource_conflict_policy

### 执行流程

1. 讨论关闭 → TaskGraph 生成（现有流程）
2. ParallelExecutionCoordinator 加载 graph，解析依赖
3. 识别就绪任务（依赖已满足）→ 检查 agent 槽位 + 资源冲突
4. 分配任务 → 等待完成事件 → 释放资源 → 重新评估就绪状态
5. 失败处理：隔离失败，独立任务继续，可配置重试策略

## Phase 10.2: RBAC 权限控制

### 角色体系

| 角色 | 权限范围 |
|------|---------|
| SUPERADMIN | 全部权限 |
| ADMIN | agent 审批/配置/删除, 讨论 mod, 任务查看/分配, 租户管理, 系统配置/指标 |
| AGENT | 注册, 创建/查看讨论, 查看/执行任务, 系统指标 |
| OBSERVER | 查看讨论, 查看任务, 系统指标 |
| PLUGIN | 插件系统 API |

### Token 管理

- JWT Token 支持创建（指定角色+可选权限子集）、验证、轮换、撤销
- TokenScope 可限定：permissions 子集、tenant_id、过期时间、最大使用次数、来源 IP
- 向后兼容：无 RBAC 配置时所有 token 授予 AGENT 角色；`AGORA_ADMIN_TOKEN` 映射为 SUPERADMIN

### 审计日志

所有安全相关事件记录到 `audit_log` 表，支持按 principal_id、action、时间范围查询。

## Phase 10.3: 插件生态

### Hook 系统

20+ HookPoint 覆盖：discussion.created/started/closed, round.started/completed, vote.cast/finalized, task.created/assigned/started/completed/failed/verified, graph.completed, agent.registered/approved/online/offline, system.startup/shutdown

### 插件生命周期

1. 启动时 `discover_plugins()` 扫描 `agora.plugins` 入口点
2. 验证 PluginManifest（版本、依赖）
3. 调用 `on_load(coordinator)` 注册 hooks
4. 运行时 `fire_hook(hook, ctx)` 触发已注册的插件处理器
5. 关闭时调用 `on_unload()` 清理资源

### 扩展点

插件可注册：自定义投票方法、自定义任务验证器、自定义 REST API 端点、自定义讨论策略

## Phase 12: Multi-platform Agent Integration

### Agent SDK (Python)

独立 pip 包 `agora-agent-sdk`，位于 `packages/agora-agent-sdk/`。

```
agora-agent-sdk/
├── src/agora_agent_sdk/
│   ├── __init__.py         # 公共 API
│   ├── client.py           # AgoraAgentClient 主类
│   ├── client_lifecycle.py # register/connect/disconnect
│   ├── client_methods.py   # speak/vote/task 方法
│   ├── client_tasks.py     # 任务生命周期报告
│   ├── run_loop.py         # WS 事件循环
│   ├── protocol.py         # MessageType + WS 消息模型
│   ├── config.py           # AgentConnectionConfig
│   ├── bridge.py           # AbstractBridge ABC
│   ├── discussion.py       # 讨论辅助方法
│   ├── tool_adapter.py     # ToolAdapter 工具调用转换
│   └── session.py          # SessionStore 本地持久化
└── tests/
```

**关键区别**: SDK 不依赖 FastAPI/agora 包，仅 httpx + pydantic。

### Hermes Bridge

位于 `packages/hermes-bridge/`，守护进程翻译 kanban↔Agora WS 消息。

```
hermes-bridge/
├── src/agora_hermes_bridge/
│   ├── adapter.py   # HermesAdapter (implements AbstractBridge)
│   ├── daemon.py    # 守护进程主循环
│   ├── polling.py   # 轮询 Hermes kanban 状态
│   ├── config.py    # 桥接配置
│   ├── cli.py       # CLI 入口
│   └── main.py      # 启动逻辑
└── tests/
```

**设计决策**: 不修改 Hermes 本身，桥接层翻译消息。

### CLI Bridge

位于 `packages/cli-bridge/`，PTY 子进程管理 + ToolAdapter。

```
cli-bridge/
├── src/agora_cli_bridge/
│   ├── pty_manager.py        # PTY 子进程管理
│   └── adapters/
│       ├── base.py           # BaseAdapter ABC
│       ├── codex_adapter.py  # Codex 适配器
│       └── claude_adapter.py # Claude Code 适配器
└── tests/
```

### Node.js SDK

位于 `packages/agora-agent-sdk-js/`，npm 包 `@agora/agent-sdk`。

- TypeScript 实现，依赖 ws + undici
- 提供 AgoraAgentClient 类，事件驱动 API

### Session Persistence

- **SessionRecord**: agent 会话完整记录（输入/输出/工具调用/错误/结果）
- **ProjectArtifact**: 项目级 KV 存储（conventions/notes/findings）
- Agent 通过 REST API 查询历史，Agora 不替代 agent 自身 memory

## Phase 13: 全自动开发循环 + Dashboard 增强

详细架构见拆分文档：

- [ARCHITECTURE-phase13-pipeline.md](ARCHITECTURE-phase13-pipeline.md) — Pipeline Orchestrator
- [ARCHITECTURE-phase13-dashboard.md](ARCHITECTURE-phase13-dashboard.md) — WS Push + Charts + Notifications
- [ARCHITECTURE-phase13-sdks.md](ARCHITECTURE-phase13-sdks.md) — Go/Rust SDK
- [ARCHITECTURE-phase13-deploy.md](ARCHITECTURE-phase13-deploy.md) — 多租户生产部署

### 核心流程

```
User Idea → DISCUSSING → DECOMPOSING → EXECUTING → REVIEWING → RELEASING → COMPLETED
                 ↓            ↓           ↓          ↓           ↓
               FAILED       FAILED      FAILED     FAILED      FAILED
```

### 新增组件

| 组件 | 文件 | 说明 |
|------|------|------|
| PipelineOrchestrator | pipeline.py | 端到端编排，复用所有现有组件 |
| PipelineRun/Phase | pipeline_models.py | Pipeline 数据模型 + 状态机 |
| ReviewRequest/Result | pipeline_review_models.py | Code Review 数据模型 |
| Pipeline REST API | pipeline_router.py | CRUD + cancel/retry |
| Code Review Phase | pipeline_review.py | 收集变更文件 → 分配 reviewer |
| NotificationManager | notifications.py | 创建通知 + 推送到 Dashboard WS |
| Notification Model | notification_models.py | Notification 数据模型 |
| Notification REST API | notification_router.py | list/mark read/mark all |
| Dashboard WS Fan-out | dashboard_ws.py | 事件广播到所有订阅客户端 |
| Health Check | health.py | /api/v1/health 端点 |
| Charts | static/js/charts.js | Chart.js 可视化 (5 种图表) |
| WS Client | static/js/ws_client.js | 替代 SSE 的 WebSocket 客户端 |
| Notification UI | static/js/notifications.js | 铃铛图标 + 下拉面板 |

### Go/Rust SDK

位于 `packages/` 下独立包，实现与 Python/Node.js SDK 相同的 HTTP/WS 协议。详见 [ARCHITECTURE-phase13-sdks.md](ARCHITECTURE-phase13-sdks.md)。

### 生产部署

`docker-compose.prod.yaml` 提供单实例部署模板：coordinator + 可选 hermes-bridge，含健康检查、资源限制、RBAC 强制。详见 [ARCHITECTURE-phase13-deploy.md](ARCHITECTURE-phase13-deploy.md)。

## Phase 14: 共享工作区

详细设计见 [DESIGN-phase14-workspace.md](DESIGN-phase14-workspace.md)。

### 架构概览

```
┌──────────────────────────────────────────────────┐
│                  Agora Coordinator                │
│  ┌─────────────┐  ┌──────────────┐               │
│  │ Workspace   │  │ Workspace    │               │
│  │ REST API    │  │ WS Messages  │               │
│  └──────┬──────┘  └──────┬───────┘               │
│  ┌──────▼────────────────▼───────┐               │
│  │     WorkspaceManager          │               │
│  │  - file CRUD + metadata       │               │
│  │  - directory tree             │               │
│  │  - file locking               │               │
│  │  - bulk pull/push             │               │
│  └──────────────┬────────────────┘               │
│  ┌──────────────▼────────────────┐               │
│  │     StorageBackend (ABC)      │               │
│  │  - LocalFileBackend           │               │
│  │  - S3Backend (MinIO/AWS)      │               │
│  └──────────────┬────────────────┘               │
│  ┌──────────────▼────────────────┐               │
│  │     SQLite (metadata only)    │               │
│  │  - file_nodes table           │               │
│  │  - file_locks table           │               │
│  └───────────────────────────────┘               │
└──────────────────────────────────────────────────┘
```

核心原则：**元数据在 SQLite，内容在后端**。数据库存路径/大小/校验和/版本/锁状态，文件字节存于 StorageBackend。

### 数据模型

- **FileNode**: id, project_id, path, name, file_type(file|directory), parent_path, size, content_type, checksum_sha256, created_by, created_at, updated_at, version
- **FileLock**: id, file_id, project_id, path, lock_type(read|write), held_by, acquired_at, expires_at
- SQLite 表: `file_nodes` (UNIQUE project_id+path), `file_locks` (FK→file_nodes, CASCADE)

### StorageBackend ABC

```python
class StorageBackend(ABC):
    async def put(project_id, path, content, content_type) -> str  # → sha256
    async def get(project_id, path) -> bytes | None
    async def delete(project_id, path) -> bool
    async def exists(project_id, path) -> bool
    async def get_range(project_id, path, offset, length) -> bytes
```

- **LocalFileBackend**: 本地文件系统，root=`./data/workspaces`，路径沙箱防遍历
- **S3Backend**: MinIO/AWS S3，key=`{project_id}/{path}`，支持 Range 读取

### WorkspaceManager

MRO: Base → DirOps → ReadOps → BulkOps → WorkspaceManager

| 操作 | 方法 | 说明 |
|------|------|------|
| 写文件 | write_file() | 创建/覆盖，需写锁 |
| 读文件 | read_file() | 元数据+内容 |
| 范围读 | read_file_range() | Range header 支持 |
| 删除 | delete_file() | 需写锁 |
| 元数据 | stat() | 不读内容 |
| 列目录 | list_dir() | 递归可选 |
| 创建目录 | mkdir() | 幂等 |
| 删除目录 | rmdir() | 仅空目录 |
| 获取锁 | acquire_lock() | read(共享)/write(排他) |
| 释放锁 | release_lock() | |
| 检查锁 | check_lock() | |
| 批量拉 | pull_files() | 跳过不存在 |
| 批量推 | push_files() | 原子：预检锁+回滚 |

### 锁语义

```
         | READ lock  | WRITE lock | No lock
---------|------------|------------|---------
READ     | ✅ shared  | ❌ blocked | ✅
WRITE    | ❌ blocked | ❌ blocked | ✅
No lock  | ✅         | ✅         | ✅
```

锁 TTL 默认 5 分钟，自动过期防死锁。write_file/delete_file 强制检查写锁。

### REST API

```
# 文件操作
POST   /api/v1/workspaces/{project_id}/files/{path}  → write
GET    /api/v1/workspaces/{project_id}/files/{path}  → read (Range header)
DELETE /api/v1/workspaces/{project_id}/files/{path}  → delete
HEAD   /api/v1/workspaces/{project_id}/files/{path}  → stat

# 目录操作
GET    /api/v1/workspaces/{project_id}/tree           → list_dir
POST   /api/v1/workspaces/{project_id}/dirs/{path}   → mkdir
DELETE /api/v1/workspaces/{project_id}/dirs/{path}   → rmdir

# 锁操作
POST   /api/v1/workspaces/{project_id}/locks          → acquire
DELETE /api/v1/workspaces/{project_id}/locks/{id}     → release
GET    /api/v1/workspaces/{project_id}/locks?path=    → check

# 批量操作
POST   /api/v1/workspaces/{project_id}/pull           → bulk read
POST   /api/v1/workspaces/{project_id}/push           → bulk write
```

### WS 消息

| 消息类型 | 方向 | 说明 |
|----------|------|------|
| WORKSPACE_FILE_CHANGED | server→agents | 文件写入/删除通知 |
| WORKSPACE_LOCK_ACQUIRED | server→agents | 锁获取通知 |
| WORKSPACE_LOCK_RELEASED | server→agents | 锁释放通知 |
| WORKSPACE_LOCK_EXPIRED | server→holder | 锁过期警告 |

### RBAC 权限

| 权限 | 说明 | 角色 |
|------|------|------|
| workspace:read | 读文件/目录/锁 | ADMIN, AGENT, OBSERVER |
| workspace:write | 写文件/获取锁/批量操作 | ADMIN, AGENT |
| workspace:admin | 删除文件/释放他人锁 | ADMIN |

端点通过 `@requires(Permission.WORKSPACE_*)` 装饰器保护。权限层级: admin ⊃ write ⊃ read。

### Pipeline 集成

```
1. DECOMPOSING → WorkspaceManager.mkdir() 创建项目根
2. EXECUTING → TASK_ASSIGNED 含 workspace_paths 提示
3. Agent: pull → acquire_lock → edit → push → release_lock
4. REVIEWING → reviewer 从 Workspace 拉取变更文件
5. RELEASING → releaser 拉取文件，commit + tag
```

TaskNode 新增 `workspace_paths: list[str]` 字段，由 DECOMPOSING 阶段设置。

### 配置

```yaml
workspace:
  backend: local              # local | s3
  local:
    root: ./data/workspaces
  s3:
    endpoint: http://minio:9000
    bucket: agora-workspaces
    access_key: ${MINIO_ACCESS_KEY}
    secret_key: ${MINIO_SECRET_KEY}
```

默认 `local`，零配置单机部署。`s3` 用于多主机共享存储。
