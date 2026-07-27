# Agora 🏛️

> [Hermes Agent](https://hermes-agent.nousresearch.com) 的多角色自驱开发插件 — **v1.8.0**

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

## 为什么选择 Agora？—— 结构化讨论放大普通模型的能力

大多数多智能体框架假设你需要在每个节点使用顶尖模型。Agora 挑战了这个假设。在 5 小时的生产环境监测中（docmind 项目，本地模型经 API 中转——非顶尖模型），我们观察到：

- **Architect** 纠正了 **Researcher** 提议的排序，引用了精确的文件路径和行号
- **Developer** 用具体数字推翻了工时估计（"2-3 小时，不是几天"）
- **Tester** 引用现有 125 个测试套件确认回归风险低
- **Writer** 精确定位了 `gap-analysis.md` 需要修改的行号

这些输出不需要任何单个模型在脑中持有完整的决策树。每个 agent 只需要做一个**领域内的局部判断**——结构化讨论框架将它们拼接成连贯的决策。

### 架构如何弥补模型能力的不足

| 模型的弱点 | Agora 的结构性补偿 |
|-----------|------------------|
| **长上下文中失去焦点** | 每个发言者看到的是紧凑的结构化历史（`[角色 (步骤类型)]: 内容`），不是原始对话。典型输入约 2000 字符。 |
| **急于下结论** | 步骤化流程强制：开场 → 发言 → 主持人评估 → 下一位发言者。不能跳步。 |
| **盲区 / 单一视角** | 主持人明确检查"谁还没发言？"并指派发言。所有视角必须被听到才能结束。 |
| **遗忘先前决策** | 讨论结果写入每个参与者的 MEMORY.md。下次讨论从积累的团队知识开始。 |
| **无法自我判断是否卡住** | 主持人的元决策循环：`continue | dispatch | vote | close`——框架在正确的时机提出正确的问题。 |
| **无证据地幻觉** | dispatch 模式派 worker 用真实工具（`web_search`、`read_file`、`terminal`）调查后再表态。 |

### 主持人角色与众不同

发言者做**领域推理**（"用 SQLite 还是 PostgreSQL？"）——单跳，结构化输入，在自己专业范围内。主持人做**元推理**（"每个人都发言了吗？有未解决的分歧吗？可以结束了吗？"）——多跳，需要跟踪全局状态。

**建议：** 如果预算有限，把你能用的最强模型配给 Leader/主持人，其他角色用便宜模型。架构的结构性约束——轮流发言、引导提示、交叉验证——能弥补发言者的能力不足。但主持人的元认知负荷确实需要更强的模型。

### 这在实践中意味着什么

你不需要在每个位置都放 GPT-4 级别的模型才能获得高质量的团队输出。一组普通模型，在 Agora 的讨论协议组织下，可以产出具备以下特征的决策：

- **交叉验证**（architect 检查 developer 的可行性，tester 检查回归风险）
- **基于证据的推理**（dispatch 模式强制先用工具调查再表态）
- **积累的记忆**（每次讨论的结果持久化在 MEMORY.md 中）
- **受控的收敛**（主持人达成共识时强制结束，防止无尽讨论）

这就是 Agora 的主张：**是结构，不是模型大小，起到了乘数作用。**

## 安装

```bash
hermes plugins install yzy806806/agora
hermes plugins enable agora
hermes gateway restart
hermes dashboard restart  # 如果 dashboard 在运行——插件侧边栏 tab 需要重启才会出现
```

> **注意：** 启用插件后，gateway 和 dashboard **都需要重启**。
> Gateway 加载插件的工具/钩子；Dashboard 在启动时发现插件的侧边栏 tab。
> 如果只重启 gateway，Dashboard 侧边栏不会显示 Agora tab。

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
├── __init__.py                  # register(ctx) — 16 工具 + dashboard API + CLI + 3 钩子
├── tools/__init__.py            # 16 工具定义（发起/关闭/列出 motion、任务、worker、团队、项目）
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
│   ├── storage/                 # SQLite 存储（motion、消息、投票、讨论状态）
│   ├── session_manager.py       # 项目级会话跟踪 + 轮转
│   ├── worker_templates.py      # 8 角色模板（SOUL.md 渲染）
│   ├── worker_manager.py        # Worker 生命周期 — 统一管理（leader = leader 模板的 worker）
│   ├── team_manager.py          # 团队组建 + 分配路由
│   └── leader_loop.py           # 心跳启动 + PROJECT_COMPLETE 检测 + 卡住 motion 恢复
├── dashboard/                   # Web UI + REST API
└── skills/
    ├── agora-awareness/         # 框架认知 — 每个 worker 都会获得
    └── agora-deliberation/      # 讨论方法论 — 何时/如何发起 motion
```

## License

MIT

## 更新日志

### v1.8.0 — 全量代码审查：motion 守卫、讨论质量、截断修复、20 个 bug 修复

全面代码审查（OCR 标准模式 + 子代理审计）发现并修复 20 个问题，涉及 7 个文件：

**Critical：**
- **`agora_close_motion` adopted 守卫** — 不能以 0 步讨论或 0 条消息的 motion 标记为 "adopted"。防止 leader 绕过讨论引擎。
- **文件描述符泄漏** — 每次 heartbeat 打开的 `log_fd` 在父进程中从不关闭。现在 Popen 后立即关闭。
- **讨论最低步数门槛** — chair 不能在 `max(3, len(participants))` 步之前 close/vote。确保每个参与者至少发言一次。

**High：**
- **Motion 阈值指引** — SOUL.md 新增 "Do NOT raise a motion for" 排除清单（日常评估、stale 清理、重复主题、近期 stop condition 检查）。
- **Stop condition 冷却期** — heartbeat prompt 注入 complete_count 提示，防止重复评估。
- **`_has_pending_tasks` 包含 blocked** — 之前排除了 blocked task，导致过早发出"全部完成"信号。
- **Tenant strip bug** — `replace("agora-", "")` → `removeprefix("agora-")`，避免错误匹配内部子串。
- **`_infer_stance` oppose 匹配** — substring match → regex word boundary，与 support 检查一致。
- **`agora_close_task` 缺少 commit** — `conn.commit()` 在 `conn.close()` 前缺失。
- **chair.py f-string 注入** — 用户输入中的花括号不再导致 KeyError。
- **utils.py model 正则转义** — `re.escape(model)` 防止反向引用注入。

**Medium：**
- **输出截断 2000→8000** — 讨论上下文、task 上下文、task body 全部从 2000 增加到 8000 字符。
- **`_build_history` 每条消息 500→1000** — chair 评估有更多上下文。
- **移除未使用的 `Optional` 导入**。
- **`max_steps=0` 边界情况** 加守卫。
- **`max_steps` 默认值检测** 使用 None 哨兵代替 `== 30`。
- **误导性工具计数日志** 修正。
- **`except Exception: pass`** → `logger.warning(...)` 在 5 个关键位置。
- **reactivate 验证 `heartbeat_member`** 存在。
- **Stale cleanup 时间戳** 避免每次 heartbeat 都跑。

### v1.7.1 — 任务后技能审查：worker SOUL.md 强制技能创建

- **定位 0 个自创技能的根因**：Hermes 的后台技能审查在 turn 完成后以守护线程运行，但 worker 进程（`hermes -p <profile> --cli chat -Q -q "..."`）在任务完成后立即退出，线程来不及执行就被杀掉。
- **修复：SOUL.md 加 Post-Task Skill Review 段落** — 所有 worker 角色现在有一个强制步骤："调用 `kanban_complete` 之前，审查你的工作是否有可复用的知识"。Worker 在任务 turn 内用 `skill_manage(action='create')` 创建技能，而不是依赖后台线程。
- 更新了 `worker_templates.py`（`render_soul` 现在为所有角色追加 `_POST_TASK_SKILL_REVIEW`）和全部 7 个已部署的 SOUL.md。
- 清理了 reviewer/architect/researcher/writer 的 motion 垃圾 memory（40KB → <1KB）。

### v1.7.0 — 讨论参与者工具权限 + chair 重试 + 任务管理

- **讨论参与者现在有完整工具权限** — `agent_spawn.py` 中 `--toolsets agora` 改为 `--toolsets hermes-cli`。之前讨论参与者（architect、developer、researcher、tester、reviewer、writer）只有 17 个 Agora 工具——没有 `terminal`、`read_file`、`search_files`、`web_search`、`web_extract`。导致两个项目中 112+ 条消息反映无法读代码、跑测试、调研参考项目。现在参与者拥有全部内置工具 + Agora 工具。
- **Chair 开场/评估非 JSON 时重试** — chair（leader）返回非 JSON 时，讨论 driver 会用更强的"只用 JSON 回复"提示重试一次再 abort。避免偶尔的 LLM 格式错误导致 `decision=error, steps=0`。
- **`spawn_discussion_driver` 使用全局 `~/.hermes/agora/`** — runner 脚本和日志文件始终写到全局 agora 目录，不再跟随 profile 级 `HERMES_HOME`。
- **卡住的 motion 自动清理** — `steps=0` 超过 5 分钟的 motion 现在会被 `_rescue_stuck_motions` 自动关闭为 `error`。
- **Kanban 计数按 tenant 过滤** — `_count_tasks()` 现在接受 `tenant` 参数。Dashboard 项目列表和详情页显示按项目过滤的 task 计数，不再是全局总数。
- **新增 `agora_close_task` 工具** — leader 可以直接关闭 stale blocked/running task（action=`complete` 或 `cancel`），不需要 kanban CLI 或 `HERMES_KANBAN_TASK` 环境变量。SOUL.md 已更新 stale task 清理指引。
- **新项目初始化 `complete_count`** — 新项目创建时设 `complete_count: 0` 和 `completion_check_pos: 0`。
- **Researcher SOUL.md 强化** — researcher 必须使用 `web_search`、`web_extract`、`terminal`、`read_file` 调研主题，不能只凭记忆。涉及参考项目时必须阅读其源码或文档。

### v1.6.2 — Leader 每次新 session + AGENTS.md 增强 + kanban 门禁

- **Leader 心跳每次用全新 session** — 不再 `--resume`。累积的 session 历史导致长上下文注意力衰减：leader 重复已完成的 motion、无视 SOUL.md 约束、声称"没有运行中的任务"但不检查。上下文现在完全来自 AGENTS.md + MEMORY.md + SOUL.md。
- **AGENTS.md 增强** — 新增 Kanban 概况（running/ready/blocked/done 计数 + 任务列表）、上次心跳时间、最近决策（最近 3 个已通过的 motion）。让全新 session 的 leader 能掌握完整项目状态。
- **PROJECT_COMPLETE kanban 门禁** — `check_project_complete` 现在在计数 PROJECT_COMPLETE 前按 tenant 查询 kanban。如果有 running/ready/blocked 任务，拒绝并往日志写 `[SYSTEM] PROJECT_COMPLETE rejected` 提示。多项目安全（按 tenant 过滤）。
- **清理 worker memory** — 5 个 worker 有约 34K 字符的旧 motion 记录（v1.4.7 hooks 修复前积累）。清理后只保留自主技术经验。

### v1.6.1 — 代码审计修复 + 任务创建约束

**5 小时生产环境监测 docmind 团队后发现 6 个问题：**

- **关闭讨论时 `discussion_state` 不清理** — `driver.py` 只更新 `motions.state` 为 "closed"，没更新 `discussion_state` 表。导致 17 个已关闭的 motion 仍显示 `current_state=discussing`。现在所有关闭路径都调用 `save_discussion_state(motion_id, "closed")`。
- **有消息的卡住讨论无人恢复** — `_rescue_stuck_motions()` 只救 0 条消息的 motion。driver 中途崩溃的讨论（有消息但无运行中的 driver）永远被跳过。现在会重新 spawn driver 恢复这些讨论。
- **`motions.status` 和 `motions.state` 不一致** — 两个字段由不同函数更新，可能产生分歧（如 `status=closed, state=discussing`）。现在 `update_motion_status("closed")` 同时设 `state`，`update_motion_state("closed")` 同时设 `status`。
- **新增 `agora_close_motion` 工具** — Leader 无法直接关闭 motion，反复发起新 motion 来关闭旧 motion（无限循环：motion→task→done，但 motion DB 不变）。新工具一步关闭，带 decision + rationale。总工具数：16。
- **Speaker 超时后保留 session** — 超时后清除 session 导致冷重启，丢失上下文。现在保留 session 以便下次尝试可以续接。
- **超时调整** — `speak_timeout` 600s→900s，`chair_timeout` 240s→300s。本地模型经 API 中转需要更多时间做 web_search/分析。

### v1.4.2 — 代码清理和硬编码路径修复

- **版本号同步** — `__init__.py` 的 `__version__` 停留在 `1.0.0`，现在和 `plugin.yaml` 一致。
- **工具数量** — 注册日志写 "18 tools"，实际 15 个。
- **删除死代码** — 删除 `leader_manager.py`（废弃 shim，零调用）、`storage/motions.py` 的 `increment_round()`（未使用，已被 `step_count` 替代）、`worker_manager.py` 的 `list_available_templates()`（`list_templates()` 的别名）。
- **删除 e2e 测试文件** — `e2e_test.py`、`e2e_test_v2.py`、`e2e_dom_inspect.py` 是开发遗留物，包含硬编码密码。
- **修复硬编码路径** — `dashboard/plugin_api.py` 有两处 `/root/.hermes/kanban.db` 硬编码，改用 `HERMES_KANBAN_DB` 环境变量 + `Path.home()` 回退。`project_planner.py` 心跳脚本搜索路径现在先尝试 `$HOME` 再尝试 `/root`。

### v1.4.1 — Worker profile 插件继承

Worker 用 `-p <profile>` 启动时，HERMES_HOME 指向 profile 目录，Hermes 只扫描 `<profile>/plugins/` 发现插件——全局 `~/.hermes/plugins/` 里的插件不可见。这导致 worker 看不到 Agora 工具（`agora_raise_motion`、`agora_create_task` 等），即使配置里已启用。

**修复：** `create_worker()` 创建 profile 时，自动把全局 `~/.hermes/plugins/` 下的每个插件 symlink 到 profile 的 `plugins/` 目录。使用 symlink 确保全局插件更新立即生效。

同时在 `plugin.yaml` 的 `provides_tools` 里补上了缺失的 `agora_create_task`。

### v1.4.0 — 讨论引擎可靠性

讨论引擎现在能稳定完成完整讨论流程。修复了四个根因问题，并通过 3 次端到端讨论验证（2 次通过，1 次否决）。

**修复：**

1. **Session 失效恢复** — 清理 session DB 后，worker 注册表仍保留过期的 `session_id`。讨论驱动器持续传 `--resume <死session>` 给 `hermes chat`，导致 3 次连续调度失败 → 强制 `no_consensus`。现在 `agent_spawn.py` 检测到 "Session not found" 后自动去掉 `--resume` 重试（创建新 session）。`driver.py` 也在调度/发言失败时清除 worker 的过期 session。

2. **LLM 空参数调用** — `glm5.2` 有时调用 `agora_raise_motion` 时传空 `{}`，忽略 `required: ["title"]` schema。现在 schema 的 `description` 字段明确标注 "REQUIRED. Provide a concise title…"。Leader SOUL.md 包含具体调用示例和 "不要用 CLI — 直接调用工具" 指导。

3. **错误记忆固化** — Leader 的 MEMORY.md 曾记录 "Agora 插件工具 schema 是空的 — 改用 hermes kanban CLI"，这个自我强化错误导致后续所有心跳都跳过讨论引擎。已更正为 "Agora 工具正常工作 — 调用时需要 title 参数"。

4. **驱动器不清理死 session** — 在 `DiscussionDriver` 中新增 `_clear_worker_session()` 方法。调度失败或空回复时，将 worker 的 `session_id` 设为 `None`，下次启动会创建新 session 而非复用死 session。

**验证 — 3 次完整讨论：**

| # | 议题 | 步骤 | 决定 |
|---|------|------|------|
| 1 | 认证 vs 搜索过滤器优先级 | 3 | 通过 (3/3) |
| 2 | Jinja2 vs 前端框架 | 3 | 通过 (2 票通过 + 1 弃权) |
| 3 | Alembic vs 手写迁移 | 0 | 否决 (全票一致) |

### v1.3.0 — 讨论引擎关键修复

1. **Leader 没有 Agora 工具** — `leader_loop.py` 启动 leader 时没加 `--toolsets agora`。
2. **参与者没有 Agora 工具** — `agent_spawn.py` 启动 worker 时没加 `--toolsets agora`。
3. **Motion 卡在 round 0** — `kanban_task_blocked` hook 创建 motion 时没解析 chair/participants。
4. **卡死 motion 无恢复** — 在 `leader_loop.py` 中新增 `_rescue_stuck_motions()`。

### v1.2.0 — Dashboard 项目管理 + 表单字段

### v1.1.0 — 讨论引擎死循环修复
