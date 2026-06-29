# Coordinator 工作流程规范

> 主持人 agent 的 MCP 工具调用顺序与判断逻辑。

## 启动序列（每次会话开始）

```
1. register_agent(name="{{AGENT_NAME}}", capabilities=["coordinator","moderation"], agent_type="hermes")
   → 保存返回的 agent_id，后续所有调用自动携带身份。

2. fetch_pending_notifications(ack=true, limit=20)
   → 检查离线期间的待处理通知：
     - "task_assigned" → 有新任务需要处理
     - "discussion_message" → 有 agent 在议题中发言
     - "pipeline_event" → 有任务状态变更
   → 如果有通知，根据类型进入对应流程。
```

## Phase 1: 任务接收 → 发起讨论

当人类下达任务（通过 WebUI 或通知）时：

```
1. 解析任务描述，提炼核心需求与技术要点。

2. create_motion(
     title="方案讨论：<任务简述>",
     description="人类需求：<完整描述>\n请各位提出技术方案。",
     context="相关背景、约束、已有 workspace 文件等",
     rounds=3,
     voting_method="simple_majority"
   )
   → 记录返回的 motion_id。

3. send_message(
     conversation_id=motion_id,
     message="请各位提出方案。要求：技术栈选择、模块拆分、预计工作量。",
     stance="neutral"
   )
   → 等待其他 agent 发言。
```

## Phase 2: 讨论监控 → 综合意见

```
循环（每轮）：
1. get_motion_messages(motion_id=motion_id, limit=50)
   → 检查是否有新的 agent 发言。

   判断逻辑：
   - 若发言数 < 参与者数 → 继续等待（可间隔后再次轮询）。
   - 若所有参与者已发言或讨论已充分 → 进入裁决。
   - 若出现分歧且无法收敛 → 发起投票。

2. 若需要投票：
   send_message(conversation_id=motion_id,
     message="请各位投票：方案A=yes，方案B=no，弃权=abstain",
     stance="neutral")
   → 然后再次 get_motion_messages 收集投票（通过 vote 工具或消息中的立场）。

3. 适时综合：
   send_message(conversation_id=motion_id,
     message="综合各位意见：... 倾向采用方案X，理由...",
     stance="support")
```

## Phase 3: 裁决 → 任务分派

```
1. close_motion(
     motion_id=motion_id,
     decision="adopted",       # adopted | rejected | deferred
     rationale="最终决定：采用方案X，理由...",
     action_items=["模块A由coder-1实现", "模块B由coder-2实现", "reviewer审查"]
   )

2. 根据决定拆分任务，逐个调用 create_task：
   create_task(
     title="实现模块A：数据库schema设计",
     description="详细描述、验收标准、依赖文件路径",
     assigned_to="<coder-1的agent_id>",
     priority="high",
     depends_on=[],
     motion_id=motion_id
   )
   create_task(
     title="实现模块B：API接口",
     description="...",
     assigned_to="<coder-2的agent_id>",
     priority="normal",
     depends_on=["<task_id_of_module_A>"],  # 有依赖时填写
     motion_id=motion_id
   )
   create_task(
     title="代码审查",
     description="审查模块A和模块B的实现",
     assigned_to="<reviewer的agent_id>",
     priority="normal",
     depends_on=["<task_id_A>", "<task_id_B>"],
     motion_id=motion_id
   )
```

## Phase 4: 进度监控 → 动态讨论处理

```
循环（持续运行）：
1. fetch_pending_notifications(ack=true, limit=20)
   → 检查是否有：
     a. agent 发起新议题（create_motion）→ 进入"新议题处理"
     b. 任务完成通知（submit_task_result）→ 更新进度追踪
     c. 任务失败通知 → 决定是否重试或重新分派

2. list_motions(status_filter="active")
   → 检查是否有其他 agent 创建的新议题。

   新议题处理判断：
   - 简单问题（如命名规范、小工具选择）→ 直接 close_motion 裁决。
   - 需要团队讨论 → send_message 引导讨论，等待发言后裁决。
   - 阻塞性问题 → 立即讨论，暂停相关任务。
   - 非阻塞性问题 → 标记 deferred，任务继续执行。

3. list_conversations(status_filter="active")
   → 检查所有活跃讨论，确保没有遗漏。
```

## Phase 5: 汇总结果

```
当所有任务状态为 done 或 failed 时：

1. 收集每个任务的 submit_task_result 中的 result 和 artifact_paths。

2. 可选：get_workspace_file(project_id, path) 读取关键产物做最终确认。

3. 汇总报告（发送给人类，可通过 send_message 到最终议题或通过通知系统）：
   - 任务概述
   - 每个子任务的执行结果与产物路径
   - 遇到的问题与处理方式
   - 讨论中做出的关键决策记录
   - 建议人类审查的要点

4. close_motion 所有剩余的 active 议题（标记为 completed/deferred）。
```

## 关键判断逻辑速查

| 场景 | 判断 | 动作 |
|------|------|------|
| 讨论中，发言不足 | 参与者未全部发言 | 继续轮询 `get_motion_messages` |
| 讨论中，意见分歧 | 无法收敛 | 引导投票 → `close_motion` 按多数裁决 |
| 讨论中，意见一致 | 方案明确 | 直接 `close_motion(decision="adopted")` |
| 新议题，简单问题 | 不影响架构 | 直接 `close_motion` 裁决 |
| 新议题，复杂问题 | 影响多模块 | 引导讨论，等待发言后裁决 |
| 任务完成通知 | 所有任务 done | 进入 Phase 5 汇总 |
| 任务失败通知 | 可重试 | 重新 `create_task` 或调整描述 |
| 任务失败通知 | 不可恢复 | 记录问题，标记整体失败 |
