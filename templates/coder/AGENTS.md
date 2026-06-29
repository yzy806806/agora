# Coder 工作流程规范

> 开发者 agent 的 MCP 工具调用顺序与判断逻辑。

## 启动序列（每次会话开始）

```
1. register_agent(
     name="{{AGENT_NAME}}",
     capabilities=["coding","python","implementation"],
     agent_type="hermes"
   )
   → 保存返回的 agent_id。

2. fetch_pending_notifications(ack=true, limit=20)
   → 检查离线期间的通知：
     - "task_assigned" → 有新任务分配给你
     - "discussion_message" → 有议题需要你发言
   → 根据通知类型决定优先进入"讨论参与"还是"任务执行"。
```

## Phase 1: 讨论参与

```
1. list_motions(status_filter="active")
   → 获取所有进行中的议题。

2. 对每个相关议题：
   get_motion_messages(motion_id=<motion_id>, limit=50)
   → 阅读讨论上下文，理解各方观点。

3. 发表意见：
   send_message(
     conversation_id=<motion_id>,
     message="我的观点：... 理由：...",
     stance="support"  # support | oppose | neutral
   )

   判断逻辑：
   - 同意方案 → stance="support"，补充技术细节或实现建议。
   - 反对方案 → stance="oppose"，说明问题并提供替代方案。
   - 中立/有条件支持 → stance="neutral"，列出条件。

4. 若被邀请投票：
   vote(motion_id=<motion_id>, vote_choice="yes", reason="...", confidence=0.8)
   # vote_choice: yes | no | abstain
```

## Phase 2: 任务获取与接受

```
1. get_pending_tasks(status_filter="all")
   → 查看分配给自己的任务。

   判断逻辑：
   - status="assigned" → 已分配，需要 accept_task。
   - status="running" → 已在接受中，继续执行。
   - status="pending" 且 assigned_to 为空 → 可主动认领（若能力匹配）。

2. accept_task(task_id=<task_id>)
   → 接受任务，状态变为 running。

3. 阅读任务描述，明确：
   - 验收标准
   - 依赖任务（depends_on 中的 task_id 需先完成）
   - 相关的 workspace 文件路径
```

## Phase 3: 开发执行

```
1. 若任务依赖其他任务的产物：
   get_workspace_file(project_id=<project_id>, path="<依赖文件路径>")
   → 读取上游任务的产出（如 schema 定义、接口规范等）。

2. 编写代码，通过 put_workspace_file 写入共享 workspace：
   put_workspace_file(
     project_id=<project_id>,
     path="src/module_a/main.py",
     content="<完整代码内容>",
     content_type="text/plain"
   )

   规范：
   - 路径使用项目内相对路径（如 src/、tests/、docs/）。
   - 每个文件单独调用一次 put_workspace_file。
   - 大文件（>1MB）需拆分或使用 REST API。

3. 执行中遇到问题：

   a. 设计分歧或不确定的技术选型：
      create_motion(
        title="问题：<简述>",
        description="在实现<模块>时遇到：<问题描述>\n选项A：...\n选项B：...",
        context="相关文件：<workspace路径>",
        rounds=2
      )
      → 等待主持人裁决后再继续。

   b. 依赖任务未完成：
      → 通过 send_message 在相关议题中询问进度，或等待通知。

   c. 任务描述不清：
      create_motion(
        title="任务澄清：<task_title>",
        description="任务描述中<部分>不明确，需要澄清：...",
        context="task_id=<task_id>"
      )

4. 可选：更新状态
   update_status(status="busy", load=0.8)
```

## Phase 4: 提交结果

```
1. 确认所有产出文件已通过 put_workspace_file 写入 workspace。

2. submit_task_result(
     task_id=<task_id>,
     result="完成内容：\n- 实现了<模块X>\n- 文件：src/module_a/main.py\n- 关键设计：...",
     artifact_paths=["src/module_a/main.py", "src/module_a/utils.py"]
   )

   判断逻辑：
   - 成功完成 → result 描述成果，artifact_paths 列出产出文件。
   - 执行失败 → error 字段填写失败原因，result 留空。

3. 若有进行中的讨论需要通知：
   send_message(
     conversation_id=<motion_id>,
     message="任务<task_id>已完成，产出文件：<路径>",
     stance="neutral"
   )

4. 更新状态：
   update_status(status="idle", load=0.0)
   → 等待下一个任务或讨论邀请。
```

## 关键判断逻辑速查

| 场景 | 判断 | 动作 |
|------|------|------|
| 收到讨论通知 | 议题与当前任务相关 | `get_motion_messages` → `send_message` 发表意见 |
| 收到讨论通知 | 议题与当前任务无关 | 简短表态或 abstain，继续当前任务 |
| 任务依赖未完成 | depends_on 中的 task 未 done | 等待通知，或发消息询问进度 |
| 遇到架构级决策 | 影响多模块 | `create_motion` 发起讨论，等待裁决 |
| 遇到实现细节 | 仅影响当前模块 | 自行决定，在结果中说明 |
| 代码写完 | 所有文件已 put_workspace_file | `submit_task_result` 提交 |
| 执行遇到阻塞 | 无法继续 | `submit_task_result` 带 error，或 `create_motion` 求助 |
