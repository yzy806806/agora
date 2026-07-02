# Agora 🏛️

> [Hermes Agent](https://hermes-agent.nousresearch.com) 的多角色自驱开发插件 — **v0.11.1**

Agora 把 Hermes 变成一个自驱动的团队：多个 AI 角色——每个都是**真正的 Hermes agent 子进程**，拥有自己的 SOUL.md、MEMORY.md、工具和会话上下文——讨论方案、搜索信息、撰写内容、自动分配任务。**Leader**（只是用 "leader" 模板创建的 worker）在事件驱动的讨论中担任**主持人**，动态选择发言者、评估进展、发起投票、总结结论。讨论结果写入每个参与者的 MEMORY.md。Leader 自动规划进度，达成目标后自动停止。全部在 Dashboard 上操作，不需要命令行。

## 核心能力

| 能力 | 说明 |
|------|------|
| **统一 worker 模型** | 没有独立的 leader 概念——leader 只是用 "leader" 模板创建的 worker（`is_leader=true`）。一切通过 `worker_manager` 管理 |
| **事件驱动讨论引擎** | Leader 担任主持人：开场点题、动态选择发言者、每轮后评估进展、发起投票、总结——不再固定轮询 |
| **真正的 agent 子进程** | 每个发言者都是真实的 `hermes -p <profile> chat -q` 子进程，拥有 SOUL.md、MEMORY.md、工具和会话上下文——非无状态 LLM 调用 |
| **项目级会话隔离** | Leader 使用 `--resume` 配合项目专属 `session_id`——不同项目间上下文不串扰 |
| **共享经验** | 同一个 leader profile 可管理多个项目——MEMORY.md、SOUL.md、skills 跨项目共享 |
| **心跳配置在项目上** | `heartbeat_member`、`heartbeat_minutes`、`heartbeat_cron_id` 存储在项目上——一个 leader 可以不同间隔跑不同项目 |
| **团队感知** | `AGENTS.md` 自动生成在项目工作目录——worker 和 leader 能看到团队成员、角色和项目上下文。心跳和 `kanban_task_claimed` 时刷新 |
| **记忆持久化** | 讨论决策和行动项写入每个参与者的 MEMORY.md，团队知识持续积累 |
| **8 种角色模板** | Architect/Developer/Reviewer/Tester/DevOps/Researcher/Writer/Leader |
| **项目自驱** | 心跳定时唤醒 Leader，检查看板、解阻塞、推进下一阶段 |
| **项目停止** | Leader 判断目标达成后输出 PROJECT_COMPLETE，自动停心跳 |
| **3 个看板钩子** | `kanban_task_completed`（记忆+评论回写）、`kanban_task_claimed`（日志+AGENTS.md 刷新）、`kanban_task_blocked`（设计决策自动触发讨论） |
| **人类参与讨论** | 讨论进行中可随时插入消息，引导讨论方向 |
| **Dashboard** | Projects tab（默认）、Team tab（Members + Teams 子页签）、Profiles tab |

## 安装

```bash
hermes plugins install yzy806806/agora
hermes plugins enable agora
hermes gateway restart
```

## 快速开始

### 1. 从 Dashboard 创建 worker

打开 `hermes dashboard`，进入 **Agora** tab → **Team → Members**：

1. 选模板，给 worker 起名（如 `alice`、`bob`）
2. 按需创建多个 worker——包括一个 leader（用 "leader" 模板）
3. 进入 **Team → Teams** — 选 worker 组队

**预置模板：**

| 模板 | 图标 | 职责 |
|------|------|------|
| Architect | 🏗️ | 系统设计、API 契约、技术选型 |
| Developer | 💻 | 功能实现、测试编写、依赖管理 |
| Reviewer | 🔍 | 代码审查、安全漏洞、边界条件 |
| Tester | 🧪 | 测试策略、自动化测试、Bug 报告 |
| DevOps | 🚀 | CI/CD、容器化、部署、监控 |
| Researcher | 🔎 | 上网搜索、趋势分析、信息汇总 |
| Writer | ✍️ | 内容撰写、结构组织、文风把控 |
| Team Leader | 👨‍💼 | 项目监控、规划下一阶段、判断完成 |

每个 worker 是一个 Hermes profile，包含：`config.yaml`（从父 profile 克隆）、`SOUL.md`（从模板渲染）、`memories/MEMORY.md`、`memories/USER.md`、`skills/`。Worker 跨项目持久化——记忆、技能和身份随身携带，就像真实员工。

### 2. 启动项目

在 **Projects** tab 点"Start Project"：
- **项目名**（如 `fashion-report`）
- **目标**（如"写一篇 2026 春夏时尚潮流 PDF"）
- **工作目录**
- **团队** — 选已组建的团队
- **心跳成员** — 选一个 leader worker 作为心跳唤醒对象
- **心跳间隔** — 分钟数（默认 15）
- 点创建

心跳 cron 自动创建。`AGENTS.md` 写入项目工作目录，所有 worker 都能看到团队上下文。

### 3. 观测和参与

点进项目详情：

- **概览** — 进度统计（todo/running/blocked/done）
- **看板** — 实时任务状态，谁在做
- **讨论** — 事件驱动讨论流：主持人引导、发言轮次、投票、总结，底部输入框可随时发言
- **团队** — 成员状态（空闲/执行中）

### 4. Leader 自驱

Leader 每次心跳：
1. 检查阻塞任务 → 解阻塞/拆分/重分配
2. 检查 triage/失败任务 → 分析、修复、重新入队
3. 全部完成 → 参考 goal 规划下一阶段，直接创建任务
4. 方向性决策 → raise motion 团队讨论
5. 目标达成 → 输出 `PROJECT_COMPLETE` → 自动停心跳

讨论主持人从 `project.heartbeat_member` 自动解析。

## 事件驱动讨论引擎

每场讨论是一场**真正的 agent 会议**：

### 工作原理

```
1. 主持人 (Leader) 开场  → 陈述议题，指定首位发言者 + 引导问题
2. 发言者发言            → 真正的 Hermes agent 子进程 (hermes -p <profile> chat -q)
                           携带 SOUL.md、MEMORY.md、工具和 --resume 会话上下文
3. 主持人评估            → 继续？投票？结束？（基于 JSON 的元决策）
4. 重复 2-3             → 直到结束或达到 max_steps（默认 30）
5.（可选）投票           → 每位参与者投票 → 主持人决定结果
6. 总结                  → 主持人生成行动项 + 写入每位参与者的 MEMORY.md
```

### 关键设计

| 方面 | 实现 |
|------|------|
| **发言者启动** | `hermes -p <profile> --yolo chat -q` — 完整的 agent，带工具、记忆和身份 |
| **会话连续性** | Worker 使用 `--resume <session_id>` 在看板任务和讨论间保持对话上下文 |
| **项目级隔离** | Leader 每个项目有独立 `session_id`——上下文不串扰，但 MEMORY.md/skills 共享 |
| **主持人 (Leader)** | 无状态元调用者 — 评估讨论状态、选择下一位发言者、发起投票。不需要 `--resume` |
| **主持人自动解析** | 若未指定 `chair_profile`，从 `project.heartbeat_member` 自动解析 |
| **角色身份** | 来自每个 worker 的 SOUL.md（含 **Discussion Protocol** 段落） |
| **Leader SOUL.md** | 包含 **Heartbeat Protocol** + **Chair Protocol** 段落 |
| **记忆持久化** | 讨论决策 + 行动项写入每位参与者的 MEMORY.md |
| **配置继承** | Worker profile 继承根 `config.yaml`（压缩、审批等设置） |

### 人类参与

Dashboard 讨论视图展示完整的事件驱动流程：主持人开场、发言者轮次及引导、投票调用、最终总结。人类可随时在讨论输入框中输入消息——该消息会成为讨论历史的一部分，主持人和发言者都能看到。

## 团队感知 (AGENTS.md)

`AGENTS.md` 文件自动生成在项目工作目录。Hermes 自动将其加载到每个 worker 的系统提示中，让 worker 感知到：
- 项目名称、目标和状态
- 心跳成员和间隔
- 团队成员表（名称 → 角色）
- 工作流指引（看板检查、任务完成、阻塞、发起讨论）

**刷新时机：**
- `start_project`（首次写入）
- Leader 心跳（成员可能已增减）
- `kanban_task_claimed` 钩子（worker 启动前）

## 看板钩子

| 钩子 | 时机 | 动作 |
|------|------|------|
| `kanban_task_completed` | Worker 完成任务 | 将讨论结果写为评论 + 记忆条目；若无待处理任务，通知 leader |
| `kanban_task_claimed` | 调度器分配任务（worker 启动前） | 记录日志；刷新 `AGENTS.md`；若有来源 motion 则注入决策为任务评论 |
| `kanban_task_blocked` | Worker 阻塞任务 | 若原因含"设计决策"或"motion" → 自动创建讨论 motion；否则记录等 leader 处理 |

## 工作流

```
用户在 Dashboard 启动项目（选团队 + 心跳成员 + 间隔）
  → AGENTS.md 写入工作目录
  → Leader 心跳（cron 定时）
    ├── 刷新 AGENTS.md
    ├── 检查 blocked → 解阻塞/拆分/重分配
    ├── 检查 triage → 分析失败、修复
    ├── 检查 running → 有则放行，无则继续
    ├── 全部 done → 参考 goal 规划下一阶段
    │   ├── 明确下一步 → 直接创建 kanban 任务
    │   └── 方向性决策 → raise motion 团队讨论
    │       → 人类可参与讨论
    │       → action items → 新任务
    └── 目标达成 → PROJECT_COMPLETE → 自动停心跳
```

## Dashboard 结构

| Tab | 内容 |
|-----|------|
| **Projects**（默认） | 项目列表、启动新项目（含心跳配置）、项目详情（看板/讨论/团队） |
| **Team** | **Members** 子页签（统一 Workers + Leaders）/ **Teams** 子页签（团队管理） |
| **Profiles** | Profile 配置管理（模型/SOUL.md/skills） |

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
          max_steps: 30           # 事件驱动：最大发言轮次，超过后强制结束
```

## 架构

```
agora/
├── plugin.yaml                  # 插件清单（工具 + 钩子）
├── __init__.py                  # register(ctx) — 18 工具 + dashboard API + CLI + 3 钩子
├── tools/__init__.py            # 18 工具定义（统一入口：仅 POST /workers）
├── cli.py                       # hermes agora CLI
├── hooks/__init__.py            # 3 看板钩子：completed、claimed、blocked
├── project_planner.py           # 项目生命周期 + 心跳配置 + AGENTS.md 生成
├── agora/
│   ├── utils.py                 # 共享工具函数
│   ├── discussion/              # 事件驱动讨论引擎
│   │   ├── driver.py            #   DiscussionDriver: 主持人 → 发言者 → 评估 → 结束
│   │   ├── agent_spawn.py       #   启动真正的 Hermes agent 子进程 (hermes -p chat -q)
│   │   ├── chair.py             #   主持人 (Leader) 提示词: 开场、评估、投票、总结
│   │   └── roles.py             #   共识检查 + 讨论模板
│   ├── storage/                 # SQLite 存储
│   ├── session_manager.py       # 项目级会话跟踪 + 轮转
│   ├── worker_templates.py      # 8 角色模板（SOUL.md 渲染）
│   ├── worker_manager.py        # Worker 生命周期 — 统一管理（leader = leader 模板的 worker）
│   ├── team_manager.py          # 团队组建 + 分配路由
│   └── leader_loop.py           # 心跳启动 + PROJECT_COMPLETE 检测
├── dashboard/                   # Web UI + REST API（Members 页签、StartProjectForm）
└── skills/
```

## License

MIT
