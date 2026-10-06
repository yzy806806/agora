# Agora 🏛️

> 让 Hermes Agent 变成一支自驱团队的多角色插件 — **v2.0.9**

**中文** | [English](./README.md)

Agora 把 Hermes 变成一支自驱团队：多个 AI 角色 —— 每个都是**真实的 Hermes agent 子进程**，拥有各自的 SOUL.md、工具和会话上下文 —— 共同讨论方案、搜索资料、撰写内容，并自动派发任务。一个 **leader**（只是从 "leader" 模板创建的 worker）在事件驱动讨论中担任 **chair**，动态选择发言者、评估进展、发起投票并总结结论。

**v2.0 的核心变化：讨论与执行统一在 Kanban 上。** 一次讨论（motion）就是团队频道根任务下的一个子任务；发言与投票是 `[agora:msg]` 注释；结论写入 `task.result`；被采纳的结论**自动变成执行任务**（父任务即该 motion，上下文由 Hermes 原生的 parent handoff 自动注入）。不再有独立的讨论数据库，也不再需要 leader 手工转述。

---

## 前置要求

- **Hermes Agent 已安装并可用**（建议 v0.20.x 或更新）
- **已配置模型 / Provider** —— 每个 worker profile 在创建时会各自复制一份全局 `config.yaml` 与 `.env`，无需逐个配置；也可在 Dashboard 里给单个 worker 指定不同模型
- **Gateway 正在运行** —— kanban dispatcher 属于 gateway，任务由它自动派发并 spawn worker。用 `hermes gateway status` 查看
- **一个项目工作目录** —— 你的代码仓库路径（不存在会被自动创建）

## 安装

```bash
hermes plugins install yzy806806/agora
hermes plugins enable agora
hermes agora setup         # 部署随插件附带的 worker skills
hermes gateway restart
hermes dashboard restart   # 如果 dashboard 在运行
```

> **注意：gateway 和 dashboard 都要重启。**
> gateway 负责加载插件的工具与 hooks；dashboard 在启动时才发现插件的侧边栏标签页。只重启 gateway 的话，dashboard 里不会出现 Agora 标签。

> **注意：`hermes agora setup` 用于部署随插件附带的 worker skills**，目标目录是
> `~/.hermes/skills/collaboration/`。安装插件本身不会写任何文件；启动项目时也会自动部署，
> 所以这条命令只在你想提前把 skills 放好时才需要。

### 审批机制与无人值守运行

worker 和 leader 都是以 `hermes -p <profile> chat -Q -q` 子进程运行的。`-q` 调用
**没有人在旁边应答审批提示**，所以**不开启绕过时，worker 的敏感操作会失败关闭（fail
closed）**——它能读、能搜、能讨论、能规划，但写文件和执行命令会被拒绝。

默认情况下 Agora **不**传递绕过参数：

```python
agora_start_project(name="my-project", workdir="/path/to/repo", goal="...")
# 审批照常生效 —— 安全，但团队无法落地实现
```

要让团队真正无人值守地写代码，需要显式开启：

```python
agora_start_project(..., allow_unattended=True)
```

开启后，该项目的每个 worker/leader 子进程都会带上 `--yolo --accept-hooks`，
即写文件与执行命令不再询问。**只对你愿意让 agent 无人值守修改的工作目录开启。**
该开关记录在项目注册表（`allow_unattended`）中；之后用 `allow_unattended=True`
重启项目即可打开。

---

## 快速上手

### 方式 A：对话式搭建（不需要 dashboard）

直接对 Hermes 说：*"安装 Agora 插件并搭一个开发团队。"*

Hermes 会读取 `agora-setup` skill 并完成整个流程：

1. `agora_list_templates()` —— 查看可用角色
2. `agora_create_worker(name="leader", role="leader")` —— 创建 worker
3. `agora_create_team(team_name="alpha", workers=[...])` —— 组建团队
4. `agora_start_project(name="my-project", workdir="/path/to/repo", goal="...", stop_condition="...")` —— 启动

### 方式 B：Dashboard 搭建

打开 `hermes dashboard` → **Agora** 标签 → **Team → Members**：

1. 选一个模板，给 worker 起个名字（如 `alice`、`bob`）
2. 按需创建多个 worker —— **包括一个 leader**（选 "leader" 模板）
3. 切到 **Team → Teams** —— 勾选 worker，组建团队

**角色模板：**

| 模板 | 图标 | 职责 |
|------|------|------|
| Team Leader | 👑 | 项目管理、讨论主持、完成判定（必需） |
| Architect | 🏗️ | 系统设计、API 契约、技术选型 |
| Developer | 💻 | 实现、测试、依赖管理 |
| Reviewer | 🔍 | 代码审查、安全、边界情况 |
| Tester | 🧪 | 测试策略、自动化、缺陷报告 |
| DevOps | 🚀 | CI/CD、部署、基础设施 |
| Researcher | 🔎 | 网络调研、趋势分析、信息综合 |
| Writer | ✍️ | 内容撰写、结构组织、语气把控 |

### 启动项目

在 **Projects** 标签点击 "Start Project"：

| 字段 | 说明 | 示例 |
|------|------|------|
| **Name** | 项目短名 | `myapp` |
| **Goal** | 高层目标（一行） | 「实现带鉴权和分页的 REST API」 |
| **Stop condition** | 自然语言完成标准，团队会投票判定 | 「所有端点测试通过且文档齐全」 |
| **Working directory** | 仓库绝对路径 | `/home/me/myapp` |
| **Team** | 选择上面组建的团队 | `alpha` |
| **Heartbeat member** | 选择 leader worker | `leader` |
| **Heartbeat interval** | 唤醒间隔（分钟，默认 15） | `15` |

---

## 跑起来后你会看到什么

**这一步最容易误判 —— 请先读完再判断项目是否正常。**

| 时间点 | 预期现象 |
|--------|----------|
| 启动后 **立即** | 项目出现在 Projects 标签，状态 `active`；AGENTS.md 已写入工作目录 |
| **最多一个心跳间隔内**（默认 15 分钟） | leader 首次被唤醒，读 AGENTS.md、检查 kanban，然后创建任务或发起讨论 |
| 之后 | 任务出现在 kanban 看板；dispatcher 自动 spawn 对应角色的 worker 执行 |
| 讨论发生时 | Agora 标签能看到讨论线程；团队频道里有 `[agora:msg]` 消息 |

> ⚠️ **最常见的误判：** 启动后几分钟内没有任何动静是**正常的** —— leader 只在心跳时刻被唤醒，默认间隔 15 分钟。想立刻看到动作，把 heartbeat interval 调小（如 2 分钟），或在 Projects 标签手动点一次 "Trigger"。

**怎么确认真的在跑：**

```
agora_project_status(name="myapp")     # 项目状态、轮次、心跳时间
hermes cron list                        # 应看到 heartbeat-myapp 任务
hermes gateway status                   # dispatcher 是否在跑
hermes kanban list                      # 任务列表
```

## 监控

```
# 项目状态
agora_project_status(name="myapp")

# 讨论
agora_list_motions(status="active")
agora_get_result(motion_id="t_xxx")
agora_get_messages(motion_id="t_xxx")

# 团队频道（2.0 新增）
agora_read_chat(project="myapp", limit=20)
```

或者直接开 Dashboard：`hermes dashboard` → **Agora** 标签（Projects / Team 两个页签，实时轮询）。

## 停止与清理

```
agora_stop_project(name="myapp")
```

停止项目会：暂停心跳 cron、把状态置为 `stopped`、**删除该项目所有 kanban 任务**（干净收尾，重启不会看到上一轮的残留）。

项目自然完成（leader 连续两次输出 `PROJECT_COMPLETE`）时执行同样的清理。

> 心跳 cron 在完成后是**暂停**而非删除；脚本文件保留在 `~/.hermes/scripts/leader_heartbeat.sh`，重新激活项目时会复用。

## 故障排查

| 现象 | 排查方向 |
|------|----------|
| 启动后长时间无动作 | 心跳还没到（默认 15 分钟）。查 `hermes cron list` 确认 `heartbeat-<项目名>` 存在；或手动 Trigger |
| Worker 不领取任务 | gateway 没在跑 → `hermes gateway status`。dispatcher 属于 gateway，不在跑就没人 spawn worker |
| 讨论不启动 | `agora_list_motions(status="active")` 看是否卡在 0 步；leader 心跳会自动救援卡住的 motion |
| Dashboard 里没有 Agora 标签 | 只重启了 gateway，没重启 dashboard → `hermes dashboard restart` |
| Worker 报 "No inference provider configured" | 全局模型配置缺失，或 `.env` 没同步到 profile。检查 `~/.hermes/.env` 与 `~/.hermes/profiles/<名字>/.env`（插件在创建 worker 时复制一份；重新创建该 worker 即可刷新） |
| Worker 频繁崩溃、日志有 429/503 | API 限流。给 worker profile 加 `api_max_retries`（如 50），或全局 `hermes config set agent.api_max_retries 50` |
| 心跳日志有 "Unknown toolsets: agora" | 装饰性时序警告（CLI 校验早于插件发现完成），工具实际正常，可忽略 |

更多排查细节见 `agora-setup` skill 的 Troubleshooting 章节。

---

## 为什么是 Agora？—— 结构化讨论能放大普通模型

多数多智能体框架假设每个节点都需要前沿模型。Agora 挑战这个假设。在 5 小时的生产监测中（docmind 项目，本地模型经 API 中转 —— 不是前沿模型），我们观察到：

- 一个 **Architect** 纠正 **Researcher** 提出的执行顺序，并引用确切的文件路径与行号
- 一个 **Developer** 用具体数字推翻工作量估算（"2-3 小时，不是几天"）
- 一个 **Tester** 引用现有的 125 个测试套件来确认回归风险
- 一个 **Writer** 精确指出 `gap-analysis.md` 里哪几行需要更新

这些输出都不需要任何单个模型把完整决策树装进脑子里。每个 agent 只需做一个**领域内判断** —— 结构化讨论框架把它们缝合成一个连贯的决策。

### 架构如何补偿模型缺陷

| 模型弱点 | Agora 的结构性补救 |
|----------|-------------------|
| **长上下文失焦** | 每个发言者看到的是紧凑的结构化历史（`[角色 (步骤类型)]: 内容`），不是原始对话。典型输入约 2000 字符 |
| **急于下结论** | 步骤化流程强制：开场 → 发言 → chair 评估 → 下一位发言者。无法跳步 |
| **盲区 / 单一视角** | chair 显式检查「谁还没发言？」，并把该角色派去调研。所有视角都被听取后才允许收尾 |
| **忘记既有决策** | 讨论结论落在 Kanban 上（motion 的 `task.result`）；被采纳的结论自动变成执行任务，worker 通过 parent handoff 看到上下文 |
| **卡住时无法自我评估** | chair 的元决策循环：`continue \| dispatch \| vote \| close` —— 框架在正确时机问正确的问题 |
| **无证据的幻觉** | dispatch 模式会把 worker 派去用真实工具调研（`web_search`、`read_file`、`terminal`），然后才形成观点 |

### chair 这个角色不一样

发言者做**领域推理**（"该用 SQLite 还是 PostgreSQL？"）—— 单跳、结构化输入、在自己专长内。chair 做**元推理**（"所有人都发言了吗？还有未解决的分歧吗？可以收尾了吗？"）—— 多跳、需要跟踪全局状态。

**建议：** 如果预算受限，把最强的模型留给 Leader/Chair，其余角色用便宜模型。架构的结构性约束（轮流发言、引导式提示、交叉验证）能补偿较弱的发言者，但 chair 的元认知负载受益于更强的模型。

---

## 工具（20）

**项目管理**

| 工具 | 说明 |
|------|------|
| `agora_start_project` | 启动自驱项目 |
| `agora_stop_project` | 停止项目（并清理 kanban） |
| `agora_project_status` | 查看项目状态 |
| `agora_update_project` | 中途修改目标/停止条件（`reactivate=true` 可重启已完成项目） |

**任务**

| 工具 | 说明 |
|------|------|
| `agora_create_task` | 创建 kanban 任务 |
| `agora_close_task` | 关闭/流转任务（`complete` / `cancel` / `submit_review`） |

**讨论**

| 工具 | 说明 |
|------|------|
| `agora_raise_motion` | 发起团队讨论 |
| `agora_get_messages` | 读取讨论消息 |
| `agora_get_result` | 获取已结束讨论的结论 |
| `agora_list_motions` | 列出进行中/已结束的讨论 |
| `agora_close_motion` | 关闭已解决或过期的讨论 |

**团队频道（2.0 新增）**

| 工具 | 说明 |
|------|------|
| `agora_message` | 向团队频道发消息（`progress` / `blocking` / `mention`） |
| `agora_read_chat` | 读取团队频道最近消息 |

**Worker 与团队**

| 工具 | 说明 |
|------|------|
| `agora_create_worker` | 从模板创建 worker |
| `agora_list_workers` | 列出所有 worker |
| `agora_remove_worker` | 删除 worker |
| `agora_list_templates` | 列出角色模板 |
| `agora_create_team` | 组建团队 |
| `agora_list_teams` | 列出团队 |
| `agora_remove_team` | 删除团队 |

> **`agora_close_task` 的三种动作：**
> - `complete` —— 标记完成
> - `cancel` —— 归档任务
> - `submit_review` —— 流转到 `review` 状态并自动指派给 reviewer，dispatcher 自动 spawn reviewer；审查通过后任务转 `done`。团队里有 reviewer 角色时推荐走这条路径。

## Kanban Hooks（3）

| Hook | 触发时机 | 动作 |
|------|----------|------|
| `kanban_task_completed` | worker 完成任务 | 把对应 motion 的结论写成任务注释；若任务复杂（多次运行或超 30 分钟），追加一条「考虑沉淀为 skill」的提示注释 |
| `kanban_task_claimed` | dispatcher 指派任务 | 记录领取；把来源 motion 的决策作为注释注入任务 |
| `kanban_task_blocked` | worker 阻塞任务 | 若阻塞原因涉及「design decision」或「motion」，自动从该任务发起一次讨论（motion 依赖该任务，上下文自动带入） |

## AGENTS.md —— 唯一事实来源

AGENTS.md 由 Agora 自动生成在项目工作目录，Hermes 会通过 `TERMINAL_CWD` 的上下文文件扫描把它自动注入每个 agent 的系统提示（leader、讨论参与者、kanban worker 全都读到）。

**内容：**
- 项目名、目标、状态、描述
- 停止条件
- 团队成员表：`| Profile Name | Role (Template) |`
- 进行中的讨论列表
- 工作流指引

**刷新时机**（原子写入 —— 临时文件 + `os.replace`）：`start_project`、leader 心跳、`agora_update_project`、motion 创建、motion 关闭。

心跳提示词本身极简 —— 只是一次唤醒。所有上下文来自 AGENTS.md，不做提示词层面的重复注入。

## 架构

```
agora/
├── plugin.yaml                  # 插件清单（20 个工具 + 3 个 hooks）
├── __init__.py                  # register(ctx)
├── tools/__init__.py            # 20 个工具定义 + _wrap_handler
├── cli.py                       # hermes agora CLI
├── hooks/__init__.py            # 3 个 kanban hooks
├── project_planner.py           # 项目生命周期 + 心跳 + AGENTS.md（原子写）+ 完成时清理 kanban
├── agora/
│   ├── chat.py                  # 团队频道总线：chat root、[agora:msg] 消息、游标拉取
│   ├── motion.py                # motion = kanban 子任务：发言/投票/结论 + 讨论调度器
│   ├── execution.py             # 讨论↔执行双向转化器（motion→task / blocked→motion）
│   ├── kanban_compat.py         # Hermes 模块拆分兼容桥（connect / notify 等）
│   ├── discussion/
│   │   ├── driver.py            # DiscussionDriver（发言/chair/投票/调研）+ 429 重试（10 次）
│   │   ├── agent_spawn.py       # spawn Hermes agent 子进程（3600s 超时）
│   │   ├── chair.py             # chair 提示词 + 发言者提示词构建
│   │   └── roles.py             # 讨论模板
│   ├── storage/
│   │   ├── motions_kanban.py    # 1.x motions API 的 Kanban 后端适配层（2.0 热路径）
│   │   └── motions.py           # 1.x SQLite 存储（保留供旧消费者，已退出 2.0 热路径）
│   ├── session_manager.py       # 会话体积跟踪与轮换
│   ├── worker_templates.py      # 8 个角色模板（SOUL.md 渲染，2 通道自我进化）
│   ├── worker_manager.py        # worker 生命周期（会话锁、工具集写入、.env 复制）
│   ├── team_manager.py          # 团队与指派路由
│   └── leader_loop.py           # 心跳 + 卡住 motion 救援 + 过期状态清理
├── dashboard/                   # Web UI + REST API
│   ├── plugin_api.py            # FastAPI 路由
│   └── dist/                    # 编译后的 React 前端
└── skills/
    ├── agora-setup/             # 运维上手引导
    ├── agora-awareness/         # 框架知识（每个 worker 都该知道）
    └── agora-deliberation/      # 讨论方法论
```

### 2.0 数据流

```
                    ┌─────────────────────────┐
                    │   Leader（chair + 仲裁）  │
                    └────────────┬────────────┘
                                 │ 心跳（默认 15 分钟）
                    ┌────────────▼────────────┐
                    │  团队频道 = 持久 kanban   │
                    │  任务（scheduled 状态）    │
                    │  消息 = [agora:msg] 注释  │
                    │  motion = 子任务          │
                    └────────────┬────────────┘
                                 │
              ┌──────────────────┼──────────────────┐
              │                  │                  │
        ┌─────▼─────┐      ┌─────▼─────┐      ┌─────▼─────┐
        │  worker   │      │  worker   │      │  worker   │
        │ 私有会话   │      │ 私有会话   │      │ 私有会话   │
        └───────────┘      └───────────┘      └───────────┘

讨论：motion 子任务内 → 发言 / 投票 → 结论写入 task.result
执行：结论被采纳 → 自动建任务（父任务 = motion）→ dispatcher 派发
上下文：Hermes 原生 parent handoff 自动注入，无需 leader 转述
```

## 超时配置

所有 LLM 相关超时默认 **1 小时（3600s）**：

| 场景 | 默认值 | 说明 |
|------|--------|------|
| 发言（`speak_timeout`） | 3600s | spawn worker 参与讨论 |
| chair 评估（`chair_timeout`） | 3600s | leader 评估讨论状态 |
| 调研 / dispatch | 3840s | `speak_timeout + 240s` 缓冲 |
| 投票 | 3600s | 同 `speak_timeout` |

Hermes 的 HTTP 客户端在超时时会自动重试；Agora 的子进程超时是硬上限 —— 超时则标记该 worker 失败，讨论继续。

## 许可

MIT

完整版本历史见 [CHANGELOG.md](./CHANGELOG.md)。
