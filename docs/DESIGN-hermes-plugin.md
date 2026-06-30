# Agora → Hermes Plugin 重构设计

> **状态**：设计阶段，待用户确认
> **日期**：2026-06-30
> **决策者**：用户

## 1. 为什么要重构

### 当前架构的问题

```
用户 → Agora Dashboard → Agora Coordinator (MCP Server, :8765)
                              ↕ MCP 协议
                         Hermes agent (按需启动)
                              ↕
                         LLM API
```

问题清单：

1. **MCP 是多余的中间层** — Agora 是 MCP Server，Hermes 是 MCP Client，但两者都在同一台机器上，MCP 协议只增加了延迟和复杂度
2. **唤醒机制是死结** — Agora 无法主动拉起 agent 进程，只能发 Matrix/Telegram 消息"请醒来"，agent 收到后还得自己连 MCP 拉任务。部署 Dendrite + Matrix bot + Telegram bot 的复杂度远超核心功能本身
3. **Agent 按需启动 ≠ 常驻在线** — Hermes agent 跑完就退出，MCP SSE 推送只对在线 session 有效，离线时通知丢失
4. **部署复杂度** — 装 Agora + 装 Hermes + 配 MCP + 配 Matrix + 配 profile + 配 SOUL.md，新用户根本跑不起来
5. **重复造轮子** — Agora 有自己的 task 系统，Hermes 有 kanban；Agora 有自己的 workspace，Hermes 有 file tools；Agora 有自己的通知，Hermes 有 kanban notifier

### 重构后的架构

```
用户 → Hermes Dashboard (内置 Agora Tab)
         ↕
     Hermes Gateway (常驻进程)
         ├── Agora 插件
         │     ├── ctx.llm.complete() → 直接调 LLM 驱动讨论
         │     ├── register_tool() → 暴露讨论/投票工具给 agent
         │     └── kanban_db.create_task() → 分派任务
         │
         ├── Kanban Dispatcher (已有)
         │     └── subprocess.Popen("hermes -p <profile> chat -q ...")
         │           → 自动拉起 worker，不需要 Matrix/Telegram
         │
         └── Worker Profile (被 dispatcher 拉起)
               ├── 加载 Agora 工具 (通过插件注册)
               ├── 加载 SOUL.md (角色定义)
               └── 执行任务 → kanban_complete
```

**一行安装**：`hermes plugins install yzy806806/agora`

## 2. Hermes 插件系统提供什么

研究 Hermes 源码 (`hermes_cli/plugins.py`, `agent/plugin_llm.py`) 后确认：

### 2.1 PluginContext API

| 方法 | 用途 | Agora 使用方式 |
|------|------|---------------|
| `ctx.register_tool(name, schema, handler)` | 注册工具给 agent 用 | 讨论/投票/workspace 工具 |
| `ctx.register_command(name, handler)` | 注册斜杠命令 | `/agora discuss <topic>` |
| `ctx.register_cli_command(name, ...)` | 注册 CLI 子命令 | `hermes agora init/discuss/serve` |
| `ctx.register_hook(hook_name, callback)` | 生命周期 hook | 监听任务完成、讨论事件 |
| `ctx.register_skill(name, path)` | 注册 skill | agora-discussion skill |
| `ctx.inject_message(content)` | 注入消息到当前对话 | 把讨论结果推给用户 |
| `ctx.llm.complete(messages)` | **直接调 LLM** | **核心：驱动多角色讨论** |
| `ctx.llm.complete_structured(...)` | 结构化 LLM 输出 | 共识检测、摘要生成 |
| `ctx.profile_name` | 当前 profile 名 | 区分 architect/developer/reviewer |

### 2.2 ctx.llm — 关键能力

```python
# 插件可以直接调 LLM，用用户的 API key 和 provider 配置
result = ctx.llm.complete(
    messages=[
        {"role": "system", "content": ARCHITECT_PROMPT},
        {"role": "user", "content": "讨论议题：是否用 PostgreSQL 替换 SQLite"},
    ],
    model="deepseekv4pro",      # 可选：覆盖模型
    temperature=0.3,
    max_tokens=1024,
)
print(result.text)  # LLM 回复
```

**这意味着 Agora 不需要外部 agent 来"发言"了** — 插件自己调 LLM，模拟 architect/developer/reviewer 三个角色进行多轮讨论。

### 2.3 Kanban 集成

```python
from hermes_cli import kanban_db

# 创建任务，指定 assignee（Hermes profile 名）
conn = kanban_db.connect()
task_id = kanban_db.create_task(
    conn,
    title="实现用户认证模块",
    body="基于 JWT 实现认证...",
    assignee="developer",          # Hermes profile 名
    workspace_kind="dir",
    workspace_path="/root/project",
    parents=["<parent_task_id>"],  # 依赖链
)
conn.close()

# Gateway 的 kanban dispatcher 每 60 秒扫一次
# 检测到 ready + assigned 的 task → 自动 Popen 拉起 worker
# worker 跑完调 kanban_complete → 任务完成
```

**不需要 Matrix、不需要 Telegram、不需要 MCP SSE** — kanban dispatcher 通过 SQLite 共享状态 + subprocess.Popen 拉起 worker，这是已经验证过的可靠机制。

### 2.4 Dashboard 集成

```
plugins/agora/
  dashboard/
    manifest.json    # 声明 tab
    plugin_api.py    # FastAPI routes → /api/plugins/agora/*
    dist/
      index.js       # 前端
      style.css
```

Dashboard 自带认证、布局、WebSocket 实时更新，Agora 只需要提供一个 tab。

## 3. 插件目录结构

```
agora/                              # GitHub repo: yzy806806/agora
├── plugin.yaml                     # 插件清单
├── __init__.py                     # register(ctx) 入口
├── agora/                          # 核心 Python 包（从现有代码移植）
│   ├── __init__.py
│   ├── discussion/
│   │   ├── __init__.py
│   │   ├── driver.py               # 多轮讨论驱动器（移植 discussion_llm_driver.py）
│   │   ├── roles.py                # 角色定义和 prompts（移植 role_prompts.py）
│   │   └── consensus.py            # 共识检测、摘要生成
│   ├── storage/
│   │   ├── __init__.py
│   │   ├── motions.py              # Motion/Message/Vote 存储（SQLite）
│   │   └── schema.sql              # 建表语句
│   ├── workspace/
│   │   └── files.py                # 共享文件存储（简化版）
│   └── config.py                   # 插件配置
├── tools/                          # 注册给 agent 的 MCP-style 工具
│   ├── __init__.py
│   ├── discussion_tools.py         # create_motion, get_messages, vote, close_motion
│   └── workspace_tools.py          # get_file, put_file, list_files
├── dashboard/                      # Hermes Dashboard tab
│   ├── manifest.json
│   ├── plugin_api.py               # REST API routes
│   └── dist/
│       ├── index.js
│       └── style.css
├── skills/                         # 插件提供的 skill
│   └── agora-deliberation/
│       └── SKILL.md                # 讨论方法论
├── templates/                      # 角色模板
│   ├── architect/
│   │   └── SOUL.md
│   ├── developer/
│   │   └── SOUL.md
│   └── reviewer/
│       └── SOUL.md
├── docs/
│   └── DESIGN-hermes-plugin.md     # 本文档
├── tests/
└── README.md
```

## 4. 核心设计

### 4.1 讨论驱动：ctx.llm 替代外部 agent

**之前**：创建 motion → 等 agent 连 MCP → agent 调 send_message 发言 → 等 agent 投票 → 等 coordinator 关闭 motion

**之后**：创建 motion → 插件直接调 `ctx.llm.complete()` 生成每个角色的发言 → 自动检测共识 → 关闭 motion → 生成 action items → 创建 kanban task 分派给 worker

```python
# agora/discussion/driver.py（核心逻辑）

class DiscussionDriver:
    """驱动多角色讨论，使用 ctx.llm 直接调 LLM。"""

    def __init__(self, ctx):
        self.ctx = ctx          # PluginContext
        self.roles = ["architect", "developer", "reviewer"]

    async def run_discussion(self, motion_id: str, title: str, description: str):
        """运行完整讨论流程。"""

        history = []

        for round_num in range(1, self.max_rounds + 1):
            for role in self.roles:
                # 构建 prompt
                system_prompt = ROLE_PROMPTS[role]
                user_prompt = self._build_prompt(title, description, history, role, round_num)

                # 直接调 LLM — 不需要外部 agent
                result = self.ctx.llm.complete(
                    messages=[
                        {"role": "system", "content": system_prompt},
                        *history,
                        {"role": "user", "content": user_prompt},
                    ],
                    model=self._role_model(role),  # 可选：每角色用不同模型
                )

                # 存储发言
                message = {
                    "role": role,
                    "content": result.text,
                    "round": round_num,
                }
                history.append({"role": "assistant", "content": f"[{role}]: {result.text}"})
                self._store_message(motion_id, message)

            # 检查共识
            if self._check_consensus(history):
                break

        # 生成摘要 + 关闭
        summary = self._summarize(history)
        self._close_motion(motion_id, summary)

        # 创建 kanban task 分派工作
        for item in summary.action_items:
            self._create_kanban_task(item)
```

### 4.2 任务分派：复用 kanban_db

讨论结束后，action items 转为 kanban task：

```python
from hermes_cli import kanban_db

def _create_kanban_task(self, action_item: dict):
    """把讨论结果转为 kanban task。"""
    conn = kanban_db.connect()
    task_id = kanban_db.create_task(
        conn,
        title=action_item["title"],
        body=action_item["description"],
        assignee=action_item.get("owner", "developer"),  # Hermes profile 名
        workspace_kind="dir",
        workspace_path=self.workspace_path,
        parents=[],  # 可选：链接到父任务
    )
    conn.close()
    # kanban dispatcher 自动拉起 worker — 不需要我们做任何事
```

### 4.3 工具注册：agent 也能发起和参与讨论

注册工具让 agent 在执行任务时能主动发起讨论、查看讨论结果、参与投票：

```python
# __init__.py

def register(ctx):
    # 用户发起讨论（斜杠命令或 Dashboard）
    ctx.register_command(
        "agora",
        handler=lambda args: agora_command_handler(ctx, args),
        description="Agora 讨论：/agora discuss <topic>",
    )

    # --- agent 可调用的工具 ---

    # 1. Agent 主动发起讨论
    ctx.register_tool(
        name="agora_raise_motion",
        toolset="agora",
        schema={
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "议题标题"},
                "description": {"type": "string", "description": "详细描述"},
                "context": {"type": "string", "description": "来源（如 task ID + 发现场景）"},
                "priority": {"type": "string", "enum": ["low", "normal", "high"], "default": "normal"},
                "blocking": {"type": "boolean", "default": False,
                             "description": "是否阻塞当前 task 等讨论结果"},
                "participants": {
                    "type": "array",
                    "items": {"type": "string", "enum": ["architect", "developer", "reviewer"]},
                    "description": "参与角色，默认全部",
                },
            },
            "required": ["title"],
        },
        handler=lambda args: raise_motion_handler(ctx, args),
        is_async=True,
    )

    # 2. 查看讨论消息（agent 读取讨论进展）
    ctx.register_tool(
        name="agora_get_messages",
        toolset="agora",
        schema={
            "type": "object",
            "properties": {
                "motion_id": {"type": "string"},
            },
            "required": ["motion_id"],
        },
        handler=lambda args: get_messages_handler(args),
    )

    # 3. 查看讨论结果（agent 读取已关闭讨论的决策和 action items）
    ctx.register_tool(
        name="agora_get_result",
        toolset="agora",
        schema={
            "type": "object",
            "properties": {
                "motion_id": {"type": "string"},
            },
            "required": ["motion_id"],
        },
        handler=lambda args: get_result_handler(args),
    )

    # 4. 列出活跃讨论（agent 巡检是否有待处理的议题）
    ctx.register_tool(
        name="agora_list_motions",
        toolset="agora",
        schema={
            "type": "object",
            "properties": {
                "status": {"type": "string", "enum": ["active", "closed", "all"], "default": "active"},
            },
        },
        handler=lambda args: list_motions_handler(args),
    )

    # 斜杠命令
    ctx.register_command(
        "agora",
        handler=lambda args: agora_command_handler(ctx, args),
        description="Agora 讨论：/agora discuss <topic>",
    )

    # CLI 命令
    ctx.register_cli_command(
        "agora",
        help="Agora 多角色讨论平台",
        setup_fn=setup_agora_cli,
    )
```

### 4.4 配置

在 Hermes 的 `config.yaml` 中配置：

```yaml
plugins:
  entries:
    agora:
      enabled: true
      # 讨论角色模型（可选，不配则用用户默认模型）
      llm:
        allow_model_override: true
      # Agora 专用配置
      agora:
        roles:
          architect:
            model: deepseekv4pro      # 架构决策用长上下文模型
          developer:
            model: astron-code-latest  # 编码用强编码模型
          reviewer:
            model: kimi2.6             # 审查用不同模型提供多样性
        discussion:
          max_rounds: 3
          consensus_threshold: 0.7
          auto_create_tasks: true       # 讨论结束自动创建 kanban task
        workspace:
          root: ~/projects              # 共享工作区根目录
```

### 4.5 讨论发起方：不只是用户

讨论有三种发起来源：

#### 来源 1：用户直接发起

```
用户：/agora discuss "是否应该用 PostgreSQL 替换 SQLite"
```

或通过 Dashboard 的"发起新讨论"表单。

#### 来源 2：Agent 在工作中主动发起

Worker 在执行 kanban task 时发现问题（设计矛盾、技术选型分歧、实现风险），主动调 `agora_raise_motion` 工具发起讨论：

```python
# agent 调用工具
agora_raise_motion(
    title="认证模块的 JWT 过期时间应该设多长？",
    description="当前设计是 1 小时，但移动端用户会频繁掉线。建议讨论 1h vs 24h vs refresh token 方案。",
    context="task-auth-abc123: 实现 JWT 认证时发现",
    priority="normal",      # low/normal/high — 决定是否阻塞当前 task
    blocking=False,         # True = 阻塞当前 task 等讨论结果
)
```

**关键设计**：
- `blocking=True` 时，agent 调 `kanban_block(reason="waiting for agora motion #xxx")`，讨论结束后自动 unblock
- `blocking=False` 时，agent 记录到 task comment 继续干活，讨论结果作为后续 task 的输入
- 讨论不一定要所有角色参与 — agent 可以指定 `participants=["architect", "reviewer"]` 只拉需要的角色
- 讨论结果通过 kanban comment 回写到原 task，agent 下次被唤醒时能看到

#### 来源 3：Reviewer 在审查时发起

Reviewer 发现代码问题不只 block task，还可以发起讨论让团队对齐认知：

```python
# reviewer 审查完代码后
agora_raise_motion(
    title="错误处理统一用 exception 还是 result type？",
    description="这次 PR 用了 exception，但项目其他地方混用了 result type。需要统一方向。",
    context="task-auth-abc123 review: 发现风格不一致",
    priority="high",
    blocking=True,
    participants=["architect", "developer"],  # 不拉 reviewer，因为是代码风格决策
)
```

#### 讨论触发后的流程

不论谁发起，流程一样：

```
agora_raise_motion() 
  → 创建 motion 记录
  → 如果 blocking=True：调 kanban_block() 阻塞当前 task
  → DiscussionDriver.run_discussion() 异步启动
    → ctx.llm 驱动各角色发言（被指定的 participants）
    → 共识检测
    → 生成摘要 + action items
    → 关闭 motion
  → 如果 blocking=True：调 kanban_unblock() 恢复 task
  → action items 转为 kanban task（assigned 给对应角色）
  → 讨论结果写入原 task 的 comment（agent 下次能看到）
  → 通知用户（ctx.inject_message 或 kanban notifier）
```

### 4.6 完整使用流程

```
# 1. 安装
hermes plugins install yzy806806/agora

# 2. 用户发起讨论
用户：/agora discuss "是否应该用 PostgreSQL 替换 SQLite"

# 3. 插件自动运行
Agora: 开始讨论 "是否应该用 PostgreSQL 替换 SQLite"
  Round 1:
    [Architect]: 从架构角度看，PostgreSQL 更适合...
    [Developer]: 实现上需要注意...
    [Reviewer]: 安全方面要考虑...
  Round 2:
    [Architect]: 补充...
    [Developer]: 同意，但建议分阶段迁移...
    [Reviewer]: 需要补充测试...
  
  ✅ 共识达成 — 采纳
  
  Action Items:
    1. 编写 PostgreSQL schema 迁移脚本 → developer
    2. 添加数据库抽象层 → developer  
    3. 编写迁移测试 → reviewer

  📋 已创建 3 个 kanban task，dispatcher 将自动分派...

# 4. kanban dispatcher 自动拉起 worker 执行任务

# 5. Worker 在执行中发现问题，主动发起讨论
Worker (developer profile): 
  → 调 agora_raise_motion(
      title="迁移脚本应该支持回滚吗？",
      blocking=True
    )
  → kanban_block() 阻塞当前 task
  → Agora 驱动讨论...
  → 讨论结果：应该支持回滚，action item: 添加 rollback 方法
  → kanban_unblock() 恢复 task
  → Worker 继续执行，这次带上了讨论结论

# 6. 用户在 Dashboard 看到完整讨论链
  - 用户发起的讨论
  - Agent 发起的讨论（标注来源 task）
  - 每个讨论的完整记录、决策、action items

## 5. 代码移植清单

### 5.1 直接移植（改 import 路径）

| 现有文件 | 行数 | 移植到 | 改动 |
|---------|------|-------|------|
| `role_prompts.py` | 90 | `agora/discussion/roles.py` | 无 |
| `llm_driver.py` | 120 | **删除** | 被 `ctx.llm` 替代 |
| `discussion_llm_driver.py` | 476 | `agora/discussion/driver.py` | `LLMClient.chat()` → `ctx.llm.complete()` |
| `storage/storage.py` (motion/message/vote 部分) | ~2000 | `agora/storage/motions.py` | 简化，只保留 motion 相关 |
| `mcp/tools/discussion_tools.py` | 450 | `tools/discussion_tools.py` | `_get_current_agent_id()` → 用 `ctx.profile_name` |
| `mcp/tools/workspace_tools.py` | 139 | `tools/workspace_tools.py` | 简化 |
| `workspace/local_backend.py` | ~400 | `agora/workspace/files.py` | 简化 |

### 5.2 删除（被 Hermes 内置能力替代）

| 文件 | 行数 | 替代方案 |
|------|------|---------|
| `mcp/` 整个目录 | 2473 | Hermes 插件 tool 注册 |
| `matrix_wakeup.py` | 320 | kanban dispatcher 的 subprocess.Popen |
| `telegram_wakeup.py` | 157 | 同上 |
| `mcp/notifications.py` | 248 | kanban notifier |
| `mcp/session_map.py` | ~100 | 不需要 session 追踪 |
| `mcp/auth.py` | ~150 | Hermes 自带认证 |
| `coordinator/main.py` (FastAPI app) | 399 | 不需要独立 HTTP 服务 |
| `coordinator/router.py` | 747 | dashboard/plugin_api.py 替代 |
| `coordinator/config.py` | 230 | 插件配置走 Hermes config.yaml |
| `coordinator/cli.py` | 530 | `hermes agora` CLI 子命令 |
| `coordinator/rbac*.py` | ~400 | Hermes 自带权限 |
| `coordinator/webhook.py` | 287 | 不需要 |
| `coordinator/bootstrap/` | 1190 | kanban dispatcher 替代 |
| `coordinator/pipeline*.py` | ~600 | kanban 状态机替代 |
| `coordinator/telegram_wakeup.py` | 157 | 删除 |
| `coordinator/token_*.py` | ~350 | Hermes 自带 token 管理 |
| `coordinator/audit.py` | 168 | kanban event log 替代 |
| `coordinator/rate_limiter.py` | 167 | 不需要 |
| `coordinator/settings_manager.py` | 263 | Hermes config 替代 |
| `coordinator/broadcast_bus*.py` | ~300 | 不需要 |
| `coordinator/protocol.py` | ~200 | 不需要 |

**删除约 10,000 行代码**，保留核心 ~3,000 行。

### 5.3 新增

| 文件 | 说明 |
|------|------|
| `plugin.yaml` | 插件清单 |
| `__init__.py` | `register(ctx)` 入口 |
| `dashboard/manifest.json` | Dashboard tab 声明 |
| `dashboard/plugin_api.py` | REST API for dashboard |
| `dashboard/dist/index.js` | 前端讨论视图 |

## 6. 数据存储

### 6.1 讨论数据（Agora 自己存）

```sql
-- ~/.hermes/agora/motions.db
CREATE TABLE motions (
    id TEXT PRIMARY KEY,
    title TEXT,
    description TEXT,
    status TEXT DEFAULT 'discussing',  -- discussing / closed
    decision TEXT,                      -- adopted / rejected / no_consensus
    rationale TEXT,
    action_items TEXT,                  -- JSON array
    current_round INTEGER DEFAULT 0,
    max_rounds INTEGER DEFAULT 3,
    source TEXT DEFAULT 'user',         -- user / agent / reviewer / system
    source_task_id TEXT,                -- 发起讨论的 kanban task ID（agent 发起时）
    source_profile TEXT,                -- 发起讨论的 profile 名（agent 发起时）
    blocking INTEGER DEFAULT 0,         -- 是否阻塞了 source task
    participants TEXT,                  -- JSON array of roles
    created_at TEXT,
    closed_at TEXT
);

CREATE TABLE messages (
    id TEXT PRIMARY KEY,
    motion_id TEXT,
    role TEXT,          -- architect / developer / reviewer
    round_num INTEGER,
    stance TEXT,        -- support / oppose / neutral
    content TEXT,
    timestamp TEXT
);

CREATE TABLE votes (
    id TEXT PRIMARY KEY,
    motion_id TEXT,
    role TEXT,
    vote TEXT,          -- yes / no / abstain
    reason TEXT,
    confidence REAL,
    timestamp TEXT
);
```

### 6.2 任务数据（用 Hermes kanban DB）

不自己建 task 表，直接用 `kanban_db.create_task()` 创建任务。任务状态、分配、执行、完成全走 kanban 系统。

### 6.3 Workspace（简化）

```python
# 共享工作区就是项目目录，不需要额外的文件存储系统
# agent 通过 Hermes 的 file tools (read_file, write_file) 操作
# Agora 只需要记录哪些文件是哪个 task 产出的
```

## 7. 讨论驱动详细设计

### 7.1 角色定义

三个角色，每个有独立的 system prompt 和可选的独立模型：

```python
ROLES = {
    "architect": {
        "prompt": ARCHITECT_PROMPT,
        "model": None,  # None = 用用户默认模型
    },
    "developer": {
        "prompt": DEVELOPER_PROMPT,
        "model": None,
    },
    "reviewer": {
        "prompt": REVIEWER_PROMPT,
        "model": None,
    },
}
```

用户可以在 config.yaml 中为每个角色配置不同模型：
```yaml
plugins:
  entries:
    agora:
      agora:
        roles:
          architect:
            model: deepseekv4pro
          developer:
            model: astron-code-latest
          reviewer:
            model: kimi2.6
```

### 7.2 讨论流程

```
1. 用户/agent 调 agora_create_motion(title, description)
2. 插件创建 motion 记录
3. DiscussionDriver.run_discussion(motion_id) 启动：
   a. Round 1: architect 发言 → developer 发言 → reviewer 发言
   b. 检查共识（ctx.llm.complete_structured 分析讨论内容）
   c. 如果共识达成 → 进入总结
   d. Round 2: 基于上轮讨论继续
   e. 最多 N 轮（默认 3）
4. 生成摘要（ctx.llm.complete_structured with JSON schema）
5. 关闭 motion，记录 decision + action_items
6. 如果 auto_create_tasks=true：
   a. 为每个 action_item 创建 kanban task
   b. task.assignee = action_item.owner (Hermes profile 名)
   c. kanban dispatcher 自动拉起 worker
7. 通知用户讨论结果（ctx.inject_message 或 kanban notifier）
```

### 7.3 共识检测

```python
def _check_consensus(self, history: list) -> dict:
    """用 LLM 分析讨论是否达成共识。"""
    result = self.ctx.llm.complete_structured(
        instructions="分析以下讨论，判断是否达成共识。",
        input=[PluginLlmTextInput(text=self._format_history(history))],
        json_schema={
            "type": "object",
            "properties": {
                "consensus": {"type": "boolean"},
                "confidence": {"type": "number"},
                "reason": {"type": "string"},
            },
            "required": ["consensus", "confidence", "reason"],
        },
    )
    return result.parsed
```

### 7.4 摘要生成

```python
def _summarize(self, history: list) -> dict:
    """生成讨论摘要和 action items。"""
    result = self.ctx.llm.complete_structured(
        instructions=SUMMARIZER_PROMPT,
        input=[PluginLlmTextInput(text=self._format_history(history))],
        json_schema={
            "type": "object",
            "properties": {
                "summary": {"type": "string"},
                "consensus_points": {"type": "array", "items": {"type": "string"}},
                "disagreements": {"type": "array", "items": {"type": "string"}},
                "action_items": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "item": {"type": "string"},
                            "owner": {"type": "string", "enum": ["architect", "developer", "reviewer"]},
                        },
                    },
                },
                "confidence": {"type": "number"},
            },
            "required": ["summary", "action_items", "confidence"],
        },
    )
    return result.parsed
```

## 8. 与 Hermes Kanban 的关系

### 8.1 分工

| 职责 | 由谁负责 |
|------|---------|
| 多角色讨论 | **Agora 插件**（ctx.llm 驱动） |
| 共识检测/裁决 | **Agora 插件** |
| 任务创建 | **Agora 插件**调 `kanban_db.create_task()` |
| 任务分派/拉起 worker | **Kanban dispatcher**（已内置） |
| 任务执行 | **Worker profile**（被 dispatcher 拉起） |
| 任务完成/阻塞 | **Worker**调 `kanban_complete/block` |
| 任务通知 | **Kanban notifier**（已内置） |
| 文件读写 | **Hermes file tools**（read_file, write_file 等） |

### 8.2 Agora 不维护自己的 task 系统

之前 Agora 有自己的 task table、task status、task assignment — 这些全部删除。任务就是 kanban task，用 kanban_db 管理。

Agora 只维护：
- **Motions**（讨论记录）
- **Messages**（讨论中的发言）
- **Votes**（投票记录）

## 9. Dashboard

### 9.1 讨论视图

```
Agora Tab
├── Active Discussions     ← 进行中的讨论
│   ├── Motion #abc123
│   │   ├── Title: "是否用 PostgreSQL 替换 SQLite"
│   │   ├── Status: Discussing (Round 2/3)
│   │   └── [展开] → 实时显示各角色发言
│   └── ...
├── Closed Discussions      ← 已完成的讨论
│   ├── Motion #def456
│   │   ├── Title: "添加用户认证"
│   │   ├── Decision: ✅ Adopted
│   │   ├── Action Items: 3 items → 3 kanban tasks
│   │   └── [展开] → 完整讨论记录
│   └── ...
└── Start New Discussion    ← 发起新讨论
    ├── Title: [____________]
    ├── Description: [____________]
    ├── Rounds: [3]
    └── [Start Discussion]
```

### 9.2 Dashboard API

```python
# dashboard/plugin_api.py
router = APIRouter()

@router.get("/motions")
async def list_motions(status: str = "all"):
    """列出讨论。"""

@router.get("/motions/{motion_id}")
async def get_motion(motion_id: str):
    """获取讨论详情 + 消息。"""

@router.post("/motions")
async def create_motion(title: str, description: str, rounds: int = 3):
    """发起新讨论。"""

@router.get("/motions/{motion_id}/messages")
async def get_messages(motion_id: str):
    """获取讨论消息。"""

@router.websocket("/motions/{motion_id}/live")
async def live_updates(ws: WebSocket, motion_id: str):
    """WebSocket 实时推送讨论消息。"""
```

## 10. 迁移路径

### Phase 1：最小可用（MVP）
- [ ] `plugin.yaml` + `__init__.py` + `register(ctx)`
- [ ] `DiscussionDriver` 移植（ctx.llm 替代 LLMClient）
- [ ] Motion/Message/Vote 存储（SQLite，含 source/source_task_id 字段）
- [ ] `agora_raise_motion` 工具（agent 主动发起讨论）
- [ ] `agora_get_messages` + `agora_get_result` + `agora_list_motions` 工具
- [ ] `/agora discuss` 斜杠命令（用户发起讨论）
- [ ] 讨论结束后调 `kanban_db.create_task()` 分派任务
- [ ] blocking 讨论自动调 `kanban_block/unblock`
- [ ] 讨论结果写入原 task 的 kanban comment
- [ ] 基础测试

### Phase 2：Dashboard
- [ ] Dashboard tab + manifest
- [ ] 讨论列表/详情 API
- [ ] 讨论实时视图（WebSocket）
- [ ] 发起新讨论表单

### Phase 3：完善
- [ ] 角色模板（SOUL.md）
- [ ] `agora-deliberation` skill
- [ ] `hermes agora` CLI 子命令
- [ ] 共识检测优化
- [ ] 多模型支持（每角色不同模型）
- [ ] 讨论历史搜索

### Phase 4：适配其他后端
- [ ] 抽象 LLM 接口，支持非 Hermes 环境
- [ ] OpenCode adapter
- [ ] PicoClaw adapter
- [ ] 独立部署模式（不带 Hermes）

## 11. 与现有代码的关系

### 保留的核心理念
- **多角色讨论** — architect/developer/reviewer 三角色，各有独立 prompt
- **Motion 流程** — create → discuss → vote → close → action items
- **共识检测** — LLM 分析讨论内容判断是否达成共识
- **Action items → Tasks** — 讨论结果转为可执行任务

### 改变的核心理念
- **不再有 MCP Server** — 插件直接注册工具，不走 MCP 协议
- **不再有独立 HTTP 服务** — 寄生在 Hermes Gateway 里
- **不再有 agent 注册/心跳/唤醒** — 用 kanban dispatcher 的 subprocess 模式
- **不再有自己的 task 系统** — 用 kanban_db
- **不再有 Matrix/Telegram 唤醒** — 不需要了
- **不再有 RBAC/auth** — Hermes 自带

## 12. 风险和问题

### Q: ctx.llm 的 trust gate 会不会限制 Agora？
A: 需要在 config.yaml 中配置 `plugins.entries.agora.llm.allow_model_override: true`。用户自己的插件在自己的 Hermes 上，默认信任。

### Q: 讨论是同步的，会不会阻塞 Gateway？
A: `ctx.llm.complete()` 是同步调用，但讨论可以在 hook 或后台 task 中异步运行。需要用 `asyncio.create_task()` 包装。或者用 `ctx.llm.acomplete()` 异步版本。

### Q: 每次讨论要调多次 LLM（3 角色 × 3 轮 = 9 次 + 共识检测 + 摘要），成本高吗？
A: 9-12 次 LLM 调用，每次 ~1K tokens 输入 + ~1K tokens 输出。用 DeepSeek 等便宜模型，一次讨论成本约 ¥0.1-0.5。用户可以配置用便宜模型做讨论。

### Q: 如果用户没有配多个 Hermes profile，kanban task 分派给谁？
A: 可以配 `kanban.default_assignee`。如果只有一个 profile，所有 task 都分派给它。讨论中的"角色"是 LLM 模拟的，不需要对应真实 profile。只有执行阶段才需要 profile。

### Q: 这个插件和 Hermes kanban 的关系会不会让用户困惑？
A: 用户视角：发讨论 → 看到结果 → 任务自动出现在 kanban 看板上 → worker 自动执行。不需要理解内部机制。Dashboard 上 Agora tab 管讨论，Kanban tab 管任务执行。
