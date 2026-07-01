# Agora 🏛️

> [Hermes Agent](https://hermes-agent.nousresearch.com) 的多角色自驱开发插件

Agora 把 Hermes 变成一个自驱动的团队：多个 AI 角色讨论方案、搜索信息、撰写内容、自动分配任务、审查质量——Leader 自动规划进度，达成目标后自动停止。全部在 Dashboard 上操作，不需要命令行。

## 核心能力

| 能力 | 说明 |
|------|------|
| **8 种角色模板** | Architect/Developer/Reviewer/Tester/DevOps/Researcher/Writer/Leader |
| **AI 生成角色** | 用自然语言描述角色，LLM 自动生成 SOUL.md |
| **Leader = Planner** | Leader 自己规划下一阶段、创建任务、判断项目完成 |
| **项目自驱** | 心跳定时唤醒 Leader，检查进度、解阻塞、推进下一阶段 |
| **项目停止** | Leader 判断目标达成后输出 PROJECT_COMPLETE，自动停心跳 |
| **人类参与讨论** | 讨论进行中可随时插入消息，引导讨论方向 |
| **Dashboard** | Projects/Team/Profiles 三个 tab，全 Web 操作 |

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
- **讨论** — 团队讨论实时流，底部输入框可随时发言
- **团队** — 成员状态（空闲/执行中）

### 4. Leader 自驱

Leader 每次心跳：
1. 检查阻塞任务 → 解阻塞/拆分/重分配
2. 全部完成 → 参考 goal 规划下一阶段，直接创建任务
3. 方向性决策 → raise motion 团队讨论
4. 目标达成 → 输出 `PROJECT_COMPLETE` → 自动停心跳

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
          auto_create_tasks: true
```

## 架构

```
agora/
├── plugin.yaml                  # 插件清单
├── __init__.py                  # register(ctx)
├── tools/__init__.py            # 18 工具定义
├── cli.py                       # hermes agora CLI
├── hooks/__init__.py            # kanban_task_completed hook
├── project_planner.py           # 项目生命周期管理
├── agora/
│   ├── utils.py                 # 共享工具函数
│   ├── discussion/              # LLM 讨论引擎
│   ├── storage/                 # SQLite 存储
│   ├── worker_templates.py      # 8 角色模板 + AI 生成 SOUL.md
│   ├── worker_manager.py        # Worker 创建/列表/删除
│   ├── team_manager.py          # 团队组建 + 轮询分配
│   ├── leader_manager.py        # Leader 管理 + cron 自动创建
│   └── leader_loop.py           # 心跳触发 + 项目完成检测
├── dashboard/                   # Web UI + REST API
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
