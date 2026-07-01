# Agora 🏛️

> [Hermes Agent](https://hermes-agent.nousresearch.com) 的多角色自驱开发插件

Agora 把 Hermes 变成一个自驱动的开发团队：多个 AI 角色讨论方案、达成共识、生成任务、分配执行、自动审查——全部在一个 Hermes 实例内完成。

## 核心能力

| 能力 | 说明 |
|------|------|
| **多角色讨论** | LLM 驱动的架构师/开发者/审查者辩论，自动达成共识 |
| **任务自动派发** | 讨论结论自动转为 kanban 任务，带依赖关系 |
| **Worker 管理** | 6 种角色模板，从 Dashboard 创建独立 profile |
| **团队组建** | 选 worker 组队，轮询分配任务，跨项目复用 |
| **Leader 心跳** | 定时唤醒 Leader 检查项目健康，解阻塞/拆任务/规划下一阶段 |
| **Dashboard** | Web 界面管理 worker/leader/team，查看讨论记录 |

## 安装

```bash
hermes plugins install yzy806806/agora
hermes plugins enable agora
hermes gateway restart
```

## 快速开始

### 1. 从 Dashboard 创建团队

打开 `hermes dashboard`，进入 **Agora** tab：

1. **Team → Workers** — 选模板（如 Developer 💻）→ 命名（如 `backend-dev`）→ 创建
2. **Team → Leaders** — 命名、选项目、设心跳周期（如 15 分钟）→ 创建
3. **Team → Teams** — 选 worker 组队，绑定到项目

每个 worker 创建时自动生成：
- `SOUL.md` — 角色身份定义（行为准则、职责边界）
- `MEMORY.md` — 个人记忆（跨项目积累经验）
- `USER.md` — 用户信息
- `skills/` — 独立技能目录
- `config.yaml` — 从父 profile 克隆的配置（API key、模型等）

### 2. 创建讨论

在聊天中：
```
/agora discuss 是否应该用 PostgreSQL 替代 SQLite？
```

或 agent 自动触发：
```python
agora_raise_motion(
    title="JWT 过期时间：1小时 vs 24小时 vs refresh token？",
    description="移动端用户反馈频繁掉登录",
    blocking=True,  # 暂停当前任务等讨论结果
)
```

### 3. 查看讨论

```
/agora list                     — 列出所有讨论
/agora show motion-abc123       — 查看讨论消息
/agora result motion-abc123     — 查看决议和行动项
```

CLI：
```bash
hermes agora list
hermes agora show motion-abc123
hermes agora result motion-abc123
hermes agora stats
```

### 4. 自驱项目开发

```python
# 启动项目（生成初始任务）
agora_start_project(
    name="my-app",
    goal="构建一个 REST API 服务",
    workdir="/root/my-app",
    team="my-team",       # 之前创建的团队
    max_rounds=10,
)

# Leader 自动每 15 分钟心跳：
# 1. 检查 blocked 任务 → 解阻塞/拆分/重分配
# 2. 检查 triage 任务 → 分析失败原因
# 3. 全部完成 → 规划下一阶段
# 4. 检查停滞讨论 → 关闭并决策
```

## 角色模板

| 模板 | 图标 | 职责 |
|------|------|------|
| Architect | 🏗️ | 系统设计、API 契约、技术选型 |
| Developer | 💻 | 功能实现、测试编写、依赖管理 |
| Reviewer | 🔍 | 代码审查、安全漏洞、边界条件 |
| Tester | 🧪 | 测试策略、自动化测试、Bug 报告 |
| DevOps | 🚀 | CI/CD、容器化、部署、监控 |
| Team Leader | 👨‍💼 | 项目监控、解阻塞、规划下一阶段 |

**Profile = 一个人**：config/memory/skills/persona 跨项目复用；kanban 任务/motions/workdir 按项目隔离。

## Dashboard

打开 `hermes dashboard`，Agora tab 有三个子页面：

### Team（新）

- **Workers** — 模板画廊、创建表单、worker 列表（角色/模型/项目）
- **Leaders** — 创建 Leader、心跳周期配置、暂停/恢复/手动触发、修改心跳间隔
- **Teams** — 选 worker 组队、绑定项目、查看团队阵容

### Profiles

- 创建/删除 Hermes profile
- 编辑 config（模型、provider、toolsets）
- 编辑 SOUL.md（角色身份定义）
- 查看可用 skills

### Discussions

- 浏览历史讨论
- 查看每条消息（角色/轮次/立场）
- 查看决议和行动项

## 工作流

### 讨论流程

```
/agora discuss "话题"
  │
  ▼
DiscussionDriver (ctx.llm)
  ├── Round 1: architect → developer → reviewer
  ├── 共识检查（置信度 ≥ 0.7 提前结束）
  ├── Round 2: 基于上一轮深入
  ├── ...（最多 3 轮）
  │
  ▼
总结（结构化 JSON）
  ├── decision: adopted / rejected / no_consensus
  ├── action_items: [{item, owner, depends_on}]
  │
  ▼
Kanban 派发
  ├── 创建任务（带父子依赖）
  ├── 结果写回源任务
  ├── 决议写入 MEMORY.md
  └── Dispatcher 自动唤醒 worker
```

### 自驱循环

```
Cron 定时器 → Leader 心跳
  │
  ├── 检查 blocked 任务 → 解阻塞/拆分/重分配
  ├── 检查 triage 任务 → 分析失败、修复
  ├── 检查进度 → 全部完成则规划下一阶段
  └── 检查停滞讨论 → 关闭并决策
        │
        ▼
  raise motion → 讨论 → action items → 新任务
  → dispatcher 轮询分配 → worker 执行 → 任务完成
  → hook 触发 → 下次心跳检查
```

## 配置

`~/.hermes/config.yaml`：

```yaml
plugins:
  enabled:
    - agora
  entries:
    agora:
      enabled: true
      agora:
        discussion:
          max_rounds: 3
          consensus_threshold: 0.7
          auto_create_tasks: true
        roles:
          architect:
            model: deepseekv4pro
          developer:
            model: astron-code-latest
          reviewer:
            model: kimi2.6
```

## 架构

```
agora/
├── plugin.yaml                  # 插件清单（18 工具 + 1 hook）
├── __init__.py                  # register(ctx) — 工具/命令/CLI/hooks 注册
├── tools/__init__.py            # 18 个工具定义
├── cli.py                       # hermes agora CLI
├── hooks/__init__.py            # kanban_task_completed 生命周期 hook
├── project_planner.py           # 自驱项目引擎
├── agora/
│   ├── discussion/
│   │   ├── driver.py            # LLM 讨论引擎
│   │   └── roles.py             # 角色提示词 + 模板
│   ├── storage/
│   │   └── motions.py           # SQLite 存储（motions + messages + votes）
│   ├── worker_templates.py      # 6 角色模板（SOUL.md 定义）
│   ├── worker_manager.py        # Worker 创建/列表/删除
│   ├── team_manager.py          # 团队组建 + 轮询分配
│   ├── leader_manager.py        # Leader 管理 + cron 自动创建
│   └── leader_loop.py           # 心跳触发逻辑
├── dashboard/
│   ├── manifest.json            # Dashboard tab 声明
│   ├── plugin_api.py            # REST API 端点
│   └── dist/
│       ├── index.js             # React 前端
│       └── style.css
└── skills/
    └── agora-deliberation/SKILL.md
```

## 工具列表

| 工具 | 说明 |
|------|------|
| `agora_raise_motion` | 发起讨论 |
| `agora_get_messages` | 读取讨论消息 |
| `agora_get_result` | 读取已关闭讨论的结果 |
| `agora_list_motions` | 列出讨论 |
| `agora_start_project` | 启动自驱项目 |
| `agora_stop_project` | 停止项目 |
| `agora_project_status` | 查看项目状态 |
| `agora_create_worker` | 从模板创建 worker |
| `agora_list_workers` | 列出所有 worker |
| `agora_remove_worker` | 删除 worker |
| `agora_list_templates` | 列出可用角色模板 |
| `agora_create_team` | 组建团队 |
| `agora_list_teams` | 列出所有团队 |
| `agora_remove_team` | 删除团队 |
| `agora_create_leader` | 创建 Leader（自动创建 cron） |
| `agora_list_leaders` | 列出所有 Leader |
| `agora_remove_leader` | 删除 Leader（自动删 cron） |
| `agora_leader_heartbeat` | 手动触发 Leader 心跳 |

## Hermes 集成

| Hermes 能力 | Agora 使用方式 |
|-------------|---------------|
| `ctx.llm.complete()` | 驱动多角色讨论 |
| `ctx.register_tool()` | 18 个工具 |
| `ctx.register_command()` | `/agora` 命令 |
| `ctx.register_cli_command()` | `hermes agora` CLI |
| `ctx.register_hook()` | `kanban_task_completed` |
| `hermes cron` | Leader 心跳定时调度 |
| `hermes profile` | Worker/Leader profile 管理 |
| `kanban_db` | 任务创建/分配/状态管理 |
| `MemoryStore` | 决议持久化到 MEMORY.md |
| Dashboard 插件系统 | 团队管理 + 讨论查看 |

## License

MIT
