# Agora ↔ Hermes 集成分析

> 哪些 Hermes 能力 Agora 可以复用，哪些是 Agora 独有的

## 已复用

| Hermes 能力 | Agora 使用方式 | 状态 |
|------------|---------------|------|
| `ctx.llm.complete()` | 驱动多角色讨论 | ✅ 已用 |
| `ctx.register_tool()` | 注册 4 个 agora 工具 | ✅ 已用 |
| `ctx.register_command()` | `/agora` 斜杠命令 | ✅ 已用 |
| `ctx.register_cli_command()` | `hermes agora` CLI | ✅ 已用 |
| `ctx.register_skill()` | agora-deliberation skill | ✅ 已用 |
| `ctx.profile_name` | 区分来源 profile | ✅ 已用 |
| Dashboard 插件系统 | manifest + plugin_api.py | ✅ 已用 |
| `kanban_db.create_task()` | action items → kanban tasks | ✅ 已用 |
| `kanban_db.block_task/unblock_task` | blocking 讨论 | ✅ 已用 |

## 应该复用但还没用

### 1. kanban 生命周期 hooks

**Hermes 已有**：
```python
VALID_HOOKS = {
    "kanban_task_completed",   # 任务完成时触发
    "kanban_task_blocked",     # 任务被阻塞时触发
    "kanban_task_claimed",     # 任务被认领时触发
    ...
}
```

**Agora 应该**：注册 `kanban_task_completed` hook，当 worker 完成任务时自动检查：
- 这个 task 是否关联了 motion（source_task_id）
- 如果有，检查 motion 是否还有未处理的 follow-up
- 如果 worker 在完成报告中提到了新问题，自动建议发起讨论

```python
# __init__.py
def register(ctx):
    ...
    ctx.register_hook("kanban_task_completed", on_task_completed)

async def on_task_completed(task_id: str, **fields):
    """当 kanban task 完成时，检查是否需要触发后续讨论。"""
    # 读取 task 的 result/summary
    # 如果 result 中提到 "需要讨论"、"建议方案" 等关键词
    # 自动建议发起 motion（不自动发，只建议给用户）
```

### 2. kanban comment 系统

**Hermes 已有**：
```python
from hermes_cli import kanban_db
kanban_db.add_comment(conn, task_id, author, body)
```

**Agora 应该**：讨论结果已经通过 `add_comment` 写入 task（driver.py 里已实现），但可以更系统化：
- agent 调 `agora_raise_motion` 时自动在 source task 写 comment
- 讨论中每轮结果也写 comment（让 worker 不用等讨论结束就能看到进展）

### 3. memory 系统

**Hermes 已有**：`memory` 工具（MEMORY.md + USER.md），跨 session 持久化。

**Agora 应该**：讨论结论写入 memory，让 agent 在后续 session 中记得：
- "上次讨论决定了用 PostgreSQL，理由是..."
- "architect 建议的分阶段迁移方案是..."

```python
# 讨论结束后
from tools.memory_tool import memory_add
memory_add(
    target="memory",
    content=f"Agora Motion {motion_id}: {title} → {decision}. "
            f"Summary: {summary}. Action items: {action_items}",
)
```

### 4. session_search

**Hermes 已有**：`session_search` 工具，FTS5 全文搜索历史会话。

**Agora 应该**：讨论消息存入 motions.db，但讨论发生的上下文（哪个 session、哪个 task）可以通过 session_search 追溯。在 `agora_get_messages` 返回中附带 session_id，让 agent 能用 `session_search` 找到讨论时的完整上下文。

### 5. delegate_task

**Hermes 已有**：`delegate_task` 工具，spawn 子 agent 执行任务。

**Agora 可以用**：讨论中的某个角色发言如果需要深度分析（比如 architect 需要读代码再发言），可以用 `delegate_task` spawn 一个子 agent 去做调研，结果回来后继续讨论。

但这和当前的 `ctx.llm.complete()` 模式不同——当前是同步调 LLM，delegate 是异步 spawn 子进程。适合未来的"深度讨论"模式。

### 6. project_tools

**Hermes 已有**：`project_list`、`project_create`、`project_switch`。

**Agora 可以用**：motion 关联到具体项目。讨论 "是否用 PostgreSQL" 时，自动读取项目信息（技术栈、现有代码结构），给 LLM 更多上下文。

### 7. cronjob_tools

**Hermes 已有**：`cronjob` 工具，定时触发。

**Agora 可以用**：
- 定时讨论："每周五下午自动发起一个回顾讨论"
- 定时检查：扫描已关闭的 motion，看 action items 是否都完成了

### 8. transform_llm_output middleware

**Hermes 已有**：`transform_llm_output` middleware，可以改写 LLM 输出。

**Agora 可以用**：当 agent 在对话中提到"我们需要讨论一下"时，自动建议调用 `agora_raise_motion`。不用改 LLM 输出，只是在输出后附加提示。

### 9. kanban 的 goal_mode

**Hermes 已有**：kanban task 支持 `goal_mode=True`，worker 被反复唤醒直到任务完成。

**Agora 可以用**：复杂的 action item（比如"重构认证模块"）创建为 goal_mode task，worker 会被多次唤醒逐步完成，而不是一次跑完就退出。

### 10. kanban 的 parents 依赖链

**Hermes 已有**：`kanban_db.create_task(parents=[...])` 建立任务依赖。

**Agora 应该更积极地用**：讨论产生的 action items 之间经常有依赖关系。比如"先写迁移脚本"→"再添加抽象层"→"最后写测试"。在 `_create_kanban_tasks` 中根据 action item 内容自动建立 parent-child 链。

## Agora 独有（Hermes 没有的）

| 能力 | 说明 |
|------|------|
| **多角色 LLM 讨论** | ctx.llm 只做单次 completion，Agora 驱动多轮多角色讨论 |
| **共识检测** | LLM 分析讨论内容判断是否达成共识 |
| **结构化摘要** | 从自由文本讨论中提取 action items + owner |
| **Motion 生命周期** | create → discuss → vote → close → action items |
| **角色 prompt 系统** | architect/developer/reviewer 各有独立 system prompt |

## 优先级

### 立即做（高价值低成本）
1. **kanban_task_completed hook** — 任务完成后检查是否需要讨论
2. **memory 写入** — 讨论结论持久化到 agent memory
3. **kanban parents 依赖链** — action items 之间建立依赖

### 后续做（中价值中成本）
4. **project 集成** — 讨论关联项目上下文
5. **cronjob 定时讨论** — 定期回顾
6. **goal_mode action items** — 复杂任务多轮执行

### 暂不做（低价值高成本）
7. **delegate_task 深度讨论** — 需要重新设计讨论架构
8. **transform_llm_output** — 侵入性太强
9. **session_search 关联** — 需要改 session 记录格式
