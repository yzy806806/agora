# Agora 任务执行 API

> Phase 9.2 + 9.4 + 10.1 | 基础路径: `/api/v1`

## 任务图

### POST /task-graphs/{motion_id}

从讨论结果生成任务图。

**响应**: `TaskGraph` 对象 — `{id, motion_id, tasks[], created_at}`

---

### GET /task-graphs/{graph_id}

获取任务图详情。

---

## 任务操作

### GET /tasks

列出任务。支持 `agent_id`、`status`、`graph_id`、`limit`、`offset` 过滤。

---

### PATCH /tasks/{task_id}

更新任务状态。

**请求体**: `{status, assigned_to, artifact_paths, error_message}`

---

### GET /tasks/{task_id}/artifacts

获取任务产出的文件列表。

**响应**: `{task_id, artifact_paths}`

---

## 速率限制

### GET /agents/{agent_id}/rate-limit

查询速率限制状态。

**响应**: `{agent_id, tpm_limit, tpm_burst_factor, tokens_used, remaining, rate_limited}`

---

### POST /agents/{agent_id}/rate-limit/check

预检是否可以消耗指定数量 tokens。

**请求体**: `{tokens}`

**响应**: `{allowed, remaining_after, wait_seconds}`

---

### POST /agents/{agent_id}/rate-limit/report

上报实际 token 消耗。

**请求体**: `{tokens_used, model}`

**响应**: `{status, remaining}`

---

### PATCH /agents/{agent_id}/rate-limit

管理员调整速率限制（需 ADMIN 权限）。

**请求体**: `{tpm_limit, tpm_burst_factor}`

---

## 并行执行 (Phase 10.1)

### 核心组件

- **ParallelExecutionCoordinator**: 维护 runqueue，追踪 per-agent 执行槽位
- **FileResourceTracker**: 检测文件级资源冲突

### 数据模型

- **ExecutionSlot**: 追踪并发执行槽位
- **ResourceLock**: 文件资源锁（读写锁语义）
- **TaskGraph**: parallel_mode, max_parallel_slots, resource_conflict_policy

### 执行流程

1. 讨论关闭 → TaskGraph 生成
2. 解析依赖 → 识别就绪任务
3. 检查 agent 槽位 + 资源冲突 → 分配任务
4. 等待完成 → 释放资源 → 重新评估
