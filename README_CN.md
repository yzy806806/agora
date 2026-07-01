# Agora 🏛️

> [Hermes Agent](https://hermes-agent.nousresearch.com) 的多角色自驱开发插件 — **v0.9.1**

Agora 把 Hermes 变成一个自驱动的团队：多个 AI 角色——每个都是**真正的 Hermes agent 子进程**，拥有自己的 SOUL.md、MEMORY.md、工具和会话上下文——讨论方案、搜索信息、撰写内容、自动分配任务。Leader 在事件驱动的讨论中担任**主持人**，动态选择发言者、评估进展、发起投票、总结结论。讨论结果写入每个参与者的 MEMORY.md。Leader 自动规划进度，达成目标后自动停止。全部在 Dashboard 上操作，不需要命令行。

## 核心能力

| 能力 | 说明 |
|------|------|
| **事件驱动讨论引擎** | Leader 担任主持人：开场点题、动态选择发言者、每轮后评估进展、发起投票、总结——不再固定轮询 |
| **真正的 agent 子进程** | 每个发言者都是真实的 `hermes -p <profile> chat -q` 子进程，拥有 SOUL.md、MEMORY.md、工具和会话上下文——非无状态 LLM 调用 |
| **会话连续性** | Worker 使用 `--resume` 在看板任务和讨论之间保持完整对话上下文 |
| **记忆持久化** | 讨论决策和行动项写入每个参与者的 MEMORY.md，团队知识持续积累 |
| **8 种角色模板** | Architect/Developer/Reviewer/Tester/DevOps/Researcher/Writer/Leader |
| **自定义角色参与讨论** | 自定义（AI 生成）角色自动参与讨论——身份来自其 SOUL.md，无需预注册 |
| **Leader = 规划者 + 主持人** | Leader 规划下一阶段、创建任务、判断项目完成，并主持所有团队讨论 |
| **项目自驱** | 心跳定时唤醒 Leader，检查进度、解阻塞、推进下一阶段 |
| **项目停止** | Leader 判断目标达成后输出 PROJECT_COMPLETE，自动停心跳 |
| **人类参与讨论** | 讨论进行中可随时插入消息，引导讨论方向 |
| **Dashboard** | Projects/Team/Profiles 三个 tab，事件驱动讨论流（步骤、主持人引导、发言轮次、投票） |

## 安装

```bash
hermes plugins install yzy806806/agora
hermes plugins enable agora
hermes gateway restart
```

## 快速开始

### 1. 从 Dashboard 创建团队

打开 `hermes dashboard`，进入 **Agora** tab：

1. **Team → Workers** — 选模板或用 AI 生成自定义角色
2. **Team → Leaders** — 创建 Leader，设心跳周期
3. **Team → Teams** — 选 worker 组队

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

**AI 生成角色：** 输入角色名 + 一句话描述（如"时尚编辑，负责事实核查和润色"），LLM 自动生成完整 SOUL.md。

### 2. 启动项目

在 **Projects** tab 点"Start Project"：
- 填项目名（如 `fashion-report`）
- 填目标（如"写一篇 2026 春夏时尚潮流 PDF"）
- 填工作目录
- 选团队和 Leader
- 点创建

### 3. 观测和参与

点进项目详情：

- **概览** — 进度统计（todo/running/blocked/done）
- **看板** — 实时任务状态，谁在做
- **讨论** — 事件驱动讨论流：主持人引导、发言轮次、投票、总结，底部输入框可随时发言
- **团队** — 成员状态（空闲/执行中）

### 4. Leader 自驱

Leader 每次心跳：
1. 检查阻塞任务 → 解阻塞/拆分/重分配
2. 全部完成 → 参考 goal 规划下一阶段，直接创建任务
3. 方向性决策 → raise motion 团队讨论
4. 目标达成 → 输出 `PROJECT_COMPLETE` → 自动停心跳

## 事件驱动讨论引擎

讨论引擎在 v0.9.0 中完全重写。不再使用旧的轮询 `ctx.llm.complete` 方式，每场讨论现在是一场**真正的 agent 会议**：

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
| **主持人 (Leader)** | 无状态元调用者 — 评估讨论状态、选择下一位发言者、发起投票。不需要 `--resume` |
| **角色身份** | 来自每个 worker 的 SOUL.md（含**Discussion Protocol**段落）。自定义角色自动适用 |
| **Leader SOUL.md** | 包含**Chair Protocol**段落：开场、评估、重定向、投票、总结 |
| **记忆持久化** | 讨论决策 + 行动项写入每位参与者的 MEMORY.md |
| **配置继承** | Worker profile 继承根 `config.yaml`（压缩、审批等设置） |

### 人类参与

Dashboard 讨论视图展示完整的事件驱动流程：主持人开场、发言者轮次及引导、投票调用、最终总结。人类可随时在讨论输入框中输入消息——该消息会成为讨论历史的一部分，主持人和发言者都能看到。

## 工作流

```
用户在 Dashboard 启动项目
  → Leader 心跳（cron 定时）
    ├── 检查 blocked → 解阻塞/拆分/重分配
    ├── 检查 triage → 分析失败、修复
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
| **Projects** | 项目列表、启动新项目、项目详情（看板/讨论/团队） |
| **Team** | Workers / Leaders / Teams 管理 |
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
├── plugin.yaml                  # 插件清单
├── __init__.py                  # register(ctx)
├── tools/__init__.py            # 18 工具定义
├── cli.py                       # hermes agora CLI
├── hooks/__init__.py            # kanban_task_completed hook（记忆 + 评论回写）
├── project_planner.py           # 项目生命周期管理
├── agora/
│   ├── utils.py                 # 共享工具函数
│   ├── discussion/              # 事件驱动讨论引擎 (v0.9.0+)
│   │   ├── driver.py            #   DiscussionDriver: 主持人 → 发言者 → 评估 → 结束
│   │   ├── agent_spawn.py       #   启动真正的 Hermes agent 子进程 (hermes -p chat -q)
│   │   ├── chair.py             #   主持人 (Leader) 提示词: 开场、评估、投票、总结
│   │   └── roles.py             #   共识检查 + 讨论模板
│   ├── storage/                 # SQLite 存储
│   ├── worker_templates.py      # 8 角色模板 + AI 生成 SOUL.md (Discussion/Chair Protocol)
│   ├── worker_manager.py        # Worker 创建/列表/删除 (profile 继承根 config.yaml)
│   ├── team_manager.py          # 团队组建 + 轮询分配
│   ├── leader_manager.py        # Leader 管理 + cron 自动创建
│   └── leader_loop.py           # 心跳触发 + 项目完成检测
├── dashboard/                   # Web UI + REST API（事件驱动讨论流）
└── skills/
```

## 工具列表

| 工具 | 说明 |
|------|------|
| `agora_raise_motion` | 发起讨论 |
| `agora_get_messages` | 读取讨论消息 |
| `agora_get_result` | 读取讨论结果 |
| `agora_list_motions` | 列出讨论 |
| `agora_start_project` | 启动项目 |
| `agora_stop_project` | 停止项目 |
| `agora_project_status` | 查看项目状态 |
| `agora_create_worker` | 创建 worker |
| `agora_list_workers` | 列出 worker |
| `agora_remove_worker` | 删除 worker |
| `agora_list_templates` | 列出角色模板 |
| `agora_create_team` | 组建团队 |
| `agora_list_teams` | 列出团队 |
| `agora_remove_team` | 删除团队 |
| `agora_create_leader` | 创建 Leader |
| `agora_list_leaders` | 列出 Leader |
| `agora_remove_leader` | 删除 Leader |
| `agora_leader_heartbeat` | 手动触发心跳 |

## License

MIT
