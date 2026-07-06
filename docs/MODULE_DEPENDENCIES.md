# Agora 模块依赖树文档

> 版本：v1.4.3
> 分析覆盖：20 个 Python 文件 + 2 个配置文件 + 2 个 Skill 文档

---

## 目录

1. [架构分层总览](#1-架构分层总览)
2. [模块清单与职责](#2-模块清单与职责)
3. [依赖关系树（ASCII）](#3-依赖关系树ascii)
4. [完整依赖矩阵](#4-完整依赖矩阵)
5. [循环依赖分析](#5-循环依赖分析)
6. [外部依赖清单](#6-外部依赖清单)
7. [入口点与调用链](#7-入口点与调用链)
8. [架构观察](#8-架构观察)

---

## 1. 架构分层总览

```
┌─────────────────────────────────────────────────────────────────────┐
│                        入口层 (Entry Layer)                          │
│  __init__.py (plugin register)  cli.py  hooks/  tools/  dashboard/  │
├─────────────────────────────────────────────────────────────────────┤
│                     编排层 (Orchestration Layer)                     │
│  project_planner.py     leader_loop.py     discussion/driver.py     │
├─────────────────────────────────────────────────────────────────────┤
│                      管理层 (Manager Layer)                          │
│  team_manager.py   worker_manager.py   session_manager.py           │
├─────────────────────────────────────────────────────────────────────┤
│                      讨论层 (Discussion Layer)                       │
│  discussion/agent_spawn.py   discussion/chair.py   discussion/roles │
├─────────────────────────────────────────────────────────────────────┤
│                       数据层 (Data Layer)                           │
│  storage/motions.py (SQLite: motions, messages, votes, discussion_  │
│  state)                                                              │
├─────────────────────────────────────────────────────────────────────┤
│                      基础层 (Foundation Layer)                       │
│  agora/utils.py          worker_templates.py (SOUL 模板)            │
├─────────────────────────────────────────────────────────────────────┤
│                      文档层 (Docs Layer)                            │
│  skills/agora-awareness/SKILL.md   skills/agora-deliberation/SKILL │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 2. 模块清单与职责

### 入口层

| 文件 | 职责 | 关键定义 |
|------|------|----------|
| `__init__.py` | 插件入口。注册 tools、hooks、CLI 子命令，部署 skills | `__version__`, `register(ctx)`, `_deploy_skills()` |
| `cli.py` | `hermes agora` CLI 子命令：list/show/result/discuss/stats | `setup_agora_cli()`, `handle_agora_cli()` |
| `hooks/__init__.py` | 生命周期钩子：任务完成/认领/阻塞 | `register_hooks()`, `_on_task_completed()`, `_on_task_claimed()`, `_on_task_blocked()` |
| `tools/__init__.py` | 注册 16 个 Agora 工具 + `/agora` 斜杠命令 | `register_all_tools()`, 16 个 JSON schema + handler |
| `dashboard/plugin_api.py` | FastAPI 路由，Dashboard REST API | `router`, 20+ 端点（profiles/workers/teams/projects/motions） |

### 编排层

| 文件 | 职责 | 关键定义 |
|------|------|----------|
| `project_planner.py` | 自驱动项目生命周期：注册项目、心跳 cron、会话管理、完成检测 | `start_project()`, `stop_project()`, `on_task_completed()`, `trigger_heartbeat()` 等 20+ 函数 |
| `leader_loop.py` | 心跳入口：cron 触发时 spawn leader agent，检测 PROJECT_COMPLETE，**恢复卡住的讨论** | `heartbeat()`, `_spawn_leader_agent()`, `_rescue_stuck_motions()`, `check_project_complete()` |
| `discussion/driver.py` | 事件驱动讨论编排器：open → speak → evaluate → vote → summary。**超时恢复 + session 保留** | `DiscussionDriver` 类, `DiscussionResult` dataclass, `_speaker_speak()`, `_investigator_speak()` |

### 管理层

| 文件 | 职责 | 关键定义 |
|------|------|----------|
| `worker_manager.py` | Worker profile 管理：创建/删除 Hermes profile，**自动 symlink 全局插件到 profile** | `create_worker()`, `remove_worker()`, `_link_global_plugins()`, `get_worker_session()`, `update_worker_session()` |
| `team_manager.py` | 团队管理：worker 集合 + 角色 round-robin 分派 | `create_team()`, `get_assignee_for_role()`, `get_team_for_project()` |
| `session_manager.py` | 会话膨胀检测与轮换 | `check_session_size()`, `rotate_session()` |

### 讨论层

| 文件 | 职责 | 关键定义 |
|------|------|----------|
| `discussion/agent_spawn.py` | spawn Hermes profile agent 子进程 | `spawn_agent_speak()`, `spawn_chair_speak()`, `spawn_discussion_driver()` |
| `discussion/chair.py` | Chair（Leader）的 prompt 模板 | `CHAIR_OPENING_PROMPT`, `CHAIR_EVALUATE_PROMPT`, `build_speaker_prompt()` |
| `discussion/roles.py` | 讨论模板 + 共识检查 prompt | `CONSENSUS_CHECKER_PROMPT`, `DISCUSSION_TEMPLATES` (6 种模板) |

### 数据层

| 文件 | 职责 | 关键定义 |
|------|------|----------|
| `storage/motions.py` | SQLite 存储：motions/messages/votes/discussion_state。**status/state 同步保证** | `create_motion()`, `add_message()`, `add_vote()`, `get_discussion_state()`, `save_discussion_state()`, `update_motion_status()`, `update_motion_state()` |

### 基础层

| 文件 | 职责 | 关键定义 |
|------|------|----------|
| `agora/utils.py` | 共享工具：路径解析、二进制查找、配置补丁、JSON 解析 | `get_global_root()`, `find_hermes_binary()`, `safe_name()`, `parse_json_response()` |
| `worker_templates.py` | 8 种角色 SOUL.md 模板 | `TEMPLATES` dict, `get_template()`, `render_soul()` |

### 配置与文档

| 文件 | 职责 |
|------|------|
| `plugin.yaml` | 插件清单：16 tools + 3 hooks + API/dashboard 声明 |
| `dashboard/manifest.json` | Dashboard 清单：入口文件、tab 位置、API 路由 |
| `skills/agora-awareness/SKILL.md` | Worker 协作框架文档 |
| `skills/agora-deliberation/SKILL.md` | 讨论方法论文档 |

---

## 3. 依赖关系树（ASCII）

```
__init__.py (插件入口)
├── D→ tools/__init__.py
│   ├── D→ agora/storage/motions.py
│   ├── D→ agora/discussion/roles.py
│   ├── D→ agora/discussion/agent_spawn.py
│   │   └── T→ agora/utils.py ←━━━━━━━━━━━━━━━━━━━━━━━━━━┓
│   ├── D→ agora/worker_manager.py                         ┃
│   │   ├── T→ agora/utils.py ━━━━━━━━━━━━━━━━━━━━━━━━━━━━┫
│   │   └── T→ agora/worker_templates.py (leaf)            ┃
│   ├── D→ agora/worker_templates.py                       ┃
│   ├── D→ agora/team_manager.py                           ┃
│   │   ├── T→ agora/utils.py ━━━━━━━━━━━━━━━━━━━━━━━━━━━━┫
│   │   ├── D→ agora/worker_manager.py ━━━━━━━━━━━━━━━━━━━┫
│   │   └── D→ project_planner.py ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ┃
│   │       ├── T→ agora/utils.py ━━━━━━━━━━━━━━━━━━━━━━━━┫
│   │       ├── D→ agora/team_manager.py ─ ─ ─ ─ ─ ─ ─ ─ ─ ┃ (cycle)
│   │       ├── D→ agora/worker_manager.py ━━━━━━━━━━━━━━━┫
│   │       └── D→ agora/leader_loop.py ─ ─ ─ ─ ─ ─ ─ ─ ─ ┃ (cycle)
│   │           ├── T→ agora/utils.py ━━━━━━━━━━━━━━━━━━━━┫
│   │           ├── D→ project_planner.py ─ ─ ─ ─ ─ ─ ─ ─ ┃ (cycle)
│   │           ├── D→ agora/worker_manager.py ━━━━━━━━━━━┫
│   │           └── D→ agora/session_manager.py            ┃
│   │               ├── D→ agora/storage/motions.py        ┃
│   │               └── D→ agora/worker_manager.py ━━━━━━━┫
│   └── D→ project_planner.py (见上)                       ┃
│                                                          ┃
├── D→ hooks/__init__.py                                   ┃
│   ├── D→ agora/storage/motions.py                        ┃
│   └── D→ project_planner.py (见上)                       ┃
│                                                          ┃
└── D→ cli.py                                              ┃
    └── D→ agora/storage/motions.py ━━━━━━━━━━━━━━━━━━━━━━┛


dashboard/plugin_api.py (FastAPI 路由)
├── D→ agora/storage/motions.py
├── D→ agora/discussion/agent_spawn.py
├── D→ agora/worker_manager.py
├── D→ agora/worker_templates.py
├── D→ agora/team_manager.py
├── D→ agora/utils.py
└── D→ project_planner.py


discussion/driver.py (讨论编排器，被 agent_spawn 间接调用)
├── T→ agora/storage/motions.py
├── T→ agora/utils.py
├── T→ agora/discussion/agent_spawn.py
├── T→ agora/discussion/chair.py (leaf)
├── D→ agora/worker_manager.py
├── D→ agora/session_manager.py
└── D→ agora/team_manager.py
```

**图例：**
- `T→` = top-level import（模块加载时执行）
- `D→` = deferred import（函数内部延迟导入）
- `───` = 实线，正常依赖
- `─ ─` = 虚线，循环依赖（通过 deferred import 安全处理）
- `(leaf)` = 叶子模块，无内部依赖

---

## 4. 完整依赖矩阵

行 = 导入方，列 = 被导入方。`T` = top-level import，`D` = deferred import

| 导入方 ↓ ＼ 被导入方 → | utils | worker_templates | storage/motions | worker_manager | team_manager | session_manager | leader_loop | project_planner | agent_spawn | chair | roles |
|---|---|---|---|---|---|---|---|---|---|---|---|
| `__init__.py` | | | | | | | | | | | |
| `cli.py` | | | D | | | | | | | | |
| `project_planner.py` | **T** | | | D | D | | D | — | | | |
| `leader_loop.py` | **T** | | D | D | | D | — | D | | | |
| `session_manager.py` | | | D | D | | — | | | | | |
| `team_manager.py` | **T** | | | D | — | | | D | | | |
| `worker_manager.py` | **T** | **T** | | — | | | | | | | |
| `worker_templates.py` | — (leaf) | | | | | | | | | | |
| `discussion/agent_spawn.py` | T | | | | | | | | — | | |
| `discussion/chair.py` | | | | | | | | | | — (leaf) | |
| `discussion/roles.py` | | | | | | | | | | | — (leaf) |
| `discussion/driver.py` | T | | T | D | D | D | | D | T | T | |
| `hooks/__init__.py` | | | D | | | | | D | | | |
| `tools/__init__.py` | D | D | D | D | D | | | D | D | | D |
| `dashboard/plugin_api.py` | D | D | D | D | D | | | D | D | | |

### 被依赖热度排行（被多少模块导入）

| 排名 | 模块 | 被导入次数 |
|------|------|-----------|
| 1 | `agora/utils.py` | **10** |
| 2 | `project_planner.py` | **7** |
| 3 | `agora/storage/motions.py` | **7** |
| 4 | `agora/worker_manager.py` | **6** |
| 5 | `agora/team_manager.py` | **5** |
| 6 | `agora/discussion/agent_spawn.py` | **3** |
| 7 | `agora/worker_templates.py` | **3** |
| 8 | `agora/session_manager.py` | **2** |
| 9 | `agora/leader_loop.py` | **1** |
| 10 | `agora/discussion/chair.py` | **1** |
| 11 | `agora/discussion/roles.py` | **1** |

---

## 5. 循环依赖分析

共发现 **2 组循环依赖**，全部通过 deferred import 安全处理：

### 5.1 `project_planner` ↔ `leader_loop`

```
project_planner.trigger_heartbeat()
  └─ D→ leader_loop.heartbeat()

leader_loop.heartbeat()
  └─ D→ project_planner.list_projects(), get_project(),
         update_heartbeat_status(), on_project_complete(),
         set_leader_session(), get_leader_session(),
         update_project_agents_md()
```

**安全原因：** 两端都是函数内部延迟导入，模块加载时不触发。

### 5.2 `project_planner` ↔ `team_manager`

```
project_planner.start_project()
  └─ D→ team_manager.get_team(), _bind_team_to_project()

team_manager._bind_team_to_project()
  └─ D→ project_planner._project_file(), get_project()
team_manager._unbind_team_from_project()
  └─ D→ project_planner._project_file(), get_project()
```

**安全原因：** 同上，全部是延迟导入。

---

## 6. 外部依赖清单

### 标准库

| 库 | 使用模块 |
|----|----------|
| `json` | utils, cli, project_planner, leader_loop, session_manager, team_manager, worker_manager, motions, hooks, tools, plugin_api, driver |
| `logging` | 几乎所有模块 |
| `os` | utils, project_planner, leader_loop, worker_manager, motions, hooks, tools, agent_spawn |
| `subprocess` | utils, project_planner, leader_loop, worker_manager, agent_spawn |
| `pathlib.Path` | utils, project_planner, leader_loop, session_manager, team_manager, worker_manager, motions, plugin_api, agent_spawn |
| `sqlite3` | motions, session_manager |
| `re` | utils, agent_spawn, driver |
| `uuid` | motions |
| `datetime` | utils, motions, team_manager, project_planner |
| `argparse` | cli |
| `shutil` | utils, worker_manager, `__init__` |
| `dataclasses` | driver |
| `typing` | 多个模块 |
| `sys` | agent_spawn, plugin_api, tools |
| `importlib` | tools, agent_spawn, project_planner (动态注册 plugin 路径) |

### 第三方 / Hermes 内部

| 库 | 使用模块 | 说明 |
|----|----------|------|
| `yaml` (PyYAML) | utils, plugin_api | 配置文件读写，延迟导入 |
| `fastapi` | plugin_api | Dashboard REST API，延迟导入 |
| `pydantic` | plugin_api | 请求模型验证 |
| `hermes_constants` | utils, motions | 获取 Hermes home 路径，optional with fallback |
| `hermes_cli.kanban_db` | project_planner, session_manager, driver, hooks, tools, plugin_api | Kanban 数据库操作 |
| `hermes_cli.profiles` | plugin_api | Profile 管理 |
| `tools.memory_tool.MemoryStore` | hooks | 写入 MEMORY.md |

---

## 7. 入口点与调用链

### 7.1 插件加载入口

```
Hermes 启动
  └─ __init__.register(ctx)
      ├─ tools.register_all_tools(ctx)     → 注册 16 个工具
      ├─ hooks.register_hooks(ctx)         → 注册 3 个钩子
      ├─ _deploy_skills()                  → 复制 skills 到 ~/.hermes/skills/
      └─ cli.setup_agora_cli(subparser)    → 注册 CLI 子命令
```

### 7.2 CLI 调用链

```
hermes agora <subcommand>
  └─ cli.handle_agora_cli(args)
      └─ D→ storage/motions (db)
          ├─ db.list_motions()    → list
          ├─ db.get_motion()      → show
          ├─ db.get_messages()    → show/result
          └─ db.get_votes()       → result
```

### 7.3 心跳自驱动链

```
Cron 触发 leader_heartbeat.sh
  └─ leader_loop.heartbeat()
      ├─ D→ project_planner.list_projects()    → 获取活跃项目
      ├─ _rescue_stuck_motions(project)         → 恢复卡住讨论
      │   └─ D→ storage/motions.list_motions()
      │   └─ D→ storage/motions.get_discussion_state()
      │   └─ D→ discussion/agent_spawn.spawn_discussion_driver()
      ├─ _spawn_leader_agent(project)
      │   ├─ D→ worker_manager.get_worker_session()
      │   ├─ D→ session_manager.check_session_size()
      │   │   └─ (if too large) rotate_session()
      │   │       └─ D→ worker_manager.update_worker_session()
      │   └─ subprocess: hermes -p <leader> chat -q --resume <session>
      └─ check_project_complete(project)
          └─ (if 2 consecutive PROJECT_COMPLETE)
              └─ D→ project_planner.on_project_complete()
                  └─ _remove_heartbeat_cron()
```

### 7.4 讨论调用链

```
用户/Agent 调用 agora_raise_motion 工具
  └─ tools._handle_raise_motion(ctx, args)
      ├─ storage/motions.create_motion()
      ├─ (if blocking) → kanban_db 标记阻塞
      └─ discussion/agent_spawn.spawn_discussion_driver()
          └─ 后台 Popen → driver.py (作为独立脚本运行)

driver.py 运行时：
  DiscussionDriver.run()
  ├─ _chair_open()          → agent_spawn.spawn_chair_speak()
  ├─ _speaker_speak()       → agent_spawn.spawn_agent_speak()
  │   └─ (超时后保留 session，不清除)
  ├─ _chair_evaluate()      → spawn_chair_speak() → JSON 决策
  │   └─ action: continue | dispatch | vote | close
  ├─ _investigator_speak()  → dispatch 模式 (新 session，带工具)
  ├─ (循环 speak → evaluate)
  ├─ _run_voting()          → 每个 participant spawn_agent_speak()
  ├─ _finalize()
  │   ├─ spawn_chair_speak() → 生成 summary
  │   ├─ D→ team_manager.get_assignee_for_role() → 创建 kanban 任务
  │   ├─ D→ kanban_db.create_task()
  │   ├─ _write_participant_memories()
  │   ├─ storage/motions.update_motion_status(closed)  → 同步 state=closed
  │   ├─ storage/motions.update_motion_state(closed)   → 同步 status=closed
  │   └─ storage/motions.save_discussion_state(closed) → 清理讨论状态
  └─ (异常时) _abort() → 同三重关闭
```

### 7.5 钩子调用链

```
Kanban 任务完成
  └─ hooks._on_task_completed(task_id, ...)
      ├─ _find_motion_for_task() → db.list_motions()
      ├─ (if found) → _write_kanban_comment() + _write_to_memory()
      └─ D→ project_planner.on_task_completed()
          └─ (if no pending tasks) → 可能触发 PROJECT_COMPLETE

Kanban 任务阻塞
  └─ hooks._on_task_blocked(task_id, reason, ...)
      └─ (if reason mentions "design decision" or "motion")
          → 自动创建 motion + 启动讨论
```

### 7.6 Dashboard API 调用链

```
浏览器 → /api/plugins/agora/*
  └─ plugin_api.py (FastAPI router)
      ├─ /profiles         → hermes_cli.profiles
      ├─ /workers          → worker_manager
      ├─ /teams            → team_manager
      ├─ /projects         → project_planner (含 cron 状态)
      ├─ /motions          → storage/motions
      └─ /motions/{id}/messages → motions.add_message() (人类参与讨论)
```

---

## 8. 架构观察

### 8.1 优点

- **延迟导入策略一致**：所有跨模块依赖都用 deferred import，干净避免了 import-time 循环错误
- **关注点分离清晰**：utils（基础）→ worker_manager/team_manager（管理）→ project_planner/leader_loop（编排）→ tools/hooks/dashboard（入口）
- **叶子模块零依赖**：`utils.py`、`worker_templates.py`、`chair.py`、`roles.py` 都没有内部依赖，可独立测试
- **数据层集中**：`storage/motions.py` 是唯一的持久化模块，SQLite + WAL 模式
- **角色身份与代码解耦**：SOUL.md 模板在 `worker_templates.py` 集中管理，修改角色不需要改逻辑代码
- **讨论状态三重一致性**：`update_motion_status`、`update_motion_state`、`save_discussion_state` 在关闭时同步，避免状态残留
- **卡住讨论自动恢复**：`_rescue_stuck_motions` 检测 driver 崩溃后重新 spawn，支持有消息和无消息两种情况

### 8.2 设计特点

| 特点 | 说明 |
|------|------|
| **importlib 动态注册** | `tools/__init__.py` 和 `agent_spawn.py` 用 `importlib.util.spec_from_file_location` 注册 `agora` 包和 `project_planner` 模块路径，绕过 Hermes 插件发现机制，确保 cron 脚本和 runner 脚本能正确 import |
| **Worker profile 插件继承** | `worker_manager._link_global_plugins()` 在创建 worker 时自动 symlink 全局 `~/.hermes/plugins/` 到 profile 的 `plugins/` 目录，解决 `-p <profile>` 下 `HERMES_HOME` 指向 profile 目录导致插件不可见的问题 |
| **Session 保留策略** | Speaker 超时后不清除 session，保留上下文以便下次 `--resume` 续接，降低重复工作 |
| **Dispatch 模式** | Chair 可将发言者转为 investigator（新 session，带工具），用于需要 web_search/read_file 的调查任务 |

### 8.3 依赖方向验证

```
✅ utils → (无内部依赖)           — 正确，基础层不应依赖上层
✅ worker_templates → (无内部依赖) — 正确，纯数据模板
✅ storage/motions → (仅 hermes_constants) — 正确，数据层不依赖业务逻辑
✅ worker_manager → utils + templates — 正确，管理层依赖基础层
✅ tools/hooks/dashboard → 所有子系统 — 正确，入口层可依赖一切
⚠️ project_planner ↔ leader_loop   — 循环但 deferred，可接受
⚠️ project_planner ↔ team_manager  — 循环但 deferred，可接受
```

---

*本文档覆盖 v1.4.3 全部 20 个 Python 源文件。*
