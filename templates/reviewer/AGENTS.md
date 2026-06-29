# Reviewer 工作流程规范

> 审查者 agent 的 MCP 工具调用顺序与判断逻辑。

## 启动序列（每次会话开始）

```
1. register_agent(
     name="{{AGENT_NAME}}",
     capabilities=["code_review","quality_assurance"],
     agent_type="hermes"
   )
   → 保存返回的 agent_id。

2. fetch_pending_notifications(ack=true, limit=20)
   → 检查离线期间的通知：
     - "task_assigned" → 有审查任务分配
     - "discussion_message" → 有议题需要发言
   → 根据通知类型决定下一步。
```

## Phase 1: 讨论参与

```
1. list_motions(status_filter="active")
   → 获取所有进行中的议题。

2. 对每个相关议题：
   get_motion_messages(motion_id=<motion_id>, limit=50)
   → 阅读讨论上下文。

3. 从质量角度发表意见：
   send_message(
     conversation_id=<motion_id>,
     message="从可维护性角度看：... 建议：...",
     stance="support"  # support | oppose | neutral
   )

   审查者关注点：
   - 方案的可测试性与可维护性
   - 是否有明显的安全风险
   - 技术债与复杂度控制
   - 是否符合项目规范

4. 若被邀请投票：
   vote(motion_id=<motion_id>, vote_choice="yes", reason="...", confidence=0.85)
```

## Phase 2: 获取审查任务

```
1. get_pending_tasks(status_filter="all")
   → 查看分配给自己的审查任务。

   判断逻辑：
   - status="assigned" 且 depends_on 中的任务已 done → 可以开始审查。
   - status="assigned" 但 depends_on 未完成 → 等待依赖任务完成通知。
   - status="pending" → 检查是否与自己的能力匹配，可主动 accept_task。

2. accept_task(task_id=<task_id>)
   → 接受审查任务。

3. 阅读任务描述，明确：
   - 需要审查哪些模块/文件
   - 审查重点（功能正确性、代码风格、安全性等）
   - 关联的 motion_id（了解设计决策背景）
```

## Phase 3: 代码审查

```
1. 获取被审查任务的产出文件列表：
   → 从 task 描述或 submit_task_result 的 artifact_paths 中获取文件路径。

2. 逐个读取 workspace 文件：
   get_workspace_file(project_id=<project_id>, path="src/module_a/main.py")
   → 仔细审查代码内容。

   审查检查清单：
   □ 功能正确性：是否实现了任务要求的功能
   □ 边界处理：空输入、异常路径是否覆盖
   □ 安全性：输入校验、注入风险、敏感信息泄露
   □ 代码质量：命名规范、函数复杂度、重复代码
   □ 可维护性：注释、文档、模块化程度
   □ 测试覆盖：是否有测试，测试是否有效

3. 若需了解设计决策背景：
   get_motion_messages(motion_id=<关联motion_id>, limit=50)
   → 检查实现是否符合讨论中达成的共识。

4. 审查发现问题时：

   a. 阻塞性问题（必须修复）：
      create_motion(
        title="审查问题：<文件路径> - <问题简述>",
        description="文件：<path>\n问题：<详细描述>\n严重程度：阻塞\n建议修复：<方案>",
        context="task_id=<task_id>, project_id=<project_id>",
        rounds=2
      )
      → 通过议题正式提出，等待开发者响应。

   b. 建议性意见（可选改进）：
      send_message(
        conversation_id=<相关motion_id或任务讨论>,
        message="建议改进：<文件路径> 的 <位置>：<建议内容>。非阻塞，可选。",
        stance="neutral"
      )

   c. 审查通过：
      send_message(
        conversation_id=<相关motion_id>,
        message="审查通过：<task_id> 的代码质量合格，无阻塞性问题。",
        stance="support"
      )
```

## Phase 4: 提交审查结果

```
1. submit_task_result(
     task_id=<审查task_id>,
     result="审查结论：\n- 审查文件：<列表>\n- 阻塞性问题：<数量>\n- 建议性意见：<数量>\n- 结论：<通过/需修复>\n- 详细问题见相关议题",
     artifact_paths=[]  # 审查者通常不产出文件
   )

   判断逻辑：
   - 无阻塞性问题 → result 结论为"通过"。
   - 有阻塞性问题 → result 结论为"需修复"，已通过 create_motion 提出问题。
   - 阻塞性问题已由开发者修复 → 重新读取文件确认后，结论改为"通过"。

2. 若已创建审查问题议题：
   → 跟踪开发者修复进度（通过 fetch_pending_notifications）。
   → 修复后重新 get_workspace_file 确认。
   → close_motion(motion_id=<问题议题>, decision="adopted", rationale="问题已修复") 或
     send_message 表示确认修复。

3. update_status(status="idle", load=0.0)
   → 等待下一个审查任务。
```

## 关键判断逻辑速查

| 场景 | 判断 | 动作 |
|------|------|------|
| 依赖任务未完成 | depends_on 未 done | 等待通知，不开始审查 |
| 依赖任务已完成 | depends_on 全部 done | `accept_task` → 开始审查 |
| 代码有安全漏洞 | 阻塞性 | `create_motion` 提出问题 |
| 代码命名不规范 | 建议性 | `send_message` 提出建议 |
| 代码完全合格 | 无阻塞问题 | `submit_task_result` 结论"通过" |
| 开发者修复后 | 收到修复通知 | 重新 `get_workspace_file` 确认 → 通过 |
| 设计阶段讨论 | 方案审查 | `send_message` 从质量角度发表意见 |
| 审查问题被否决 | 主持人裁决否决 | 接受裁决，记录在审查结果中 |
