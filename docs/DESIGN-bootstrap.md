# Phase 4: Bootstrap Design

## 概述

设计 Agora 的自举机制：用 Agora 开发 Agora。通过 AI 团队讨论驱动项目开发方向，用户拍板确认，自动化任务生成和分配。

## 1. 目标

- AI 团队通过 Agora 讨论确定开发方向
- 用户拍板 + AI 团队方案论证
- 开发计划由讨论结果驱动
- 项目自组织、自进化

## 2. 系统架构

```
┌─────────────────────────────────────────────────────────────────┐
│                      Bootstrap Engine                           │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐             │
│  │  Trigger    │  │  Discuss    │  │  Task        │             │
│  │  Manager    │─▶│  Driver     │─▶│  Generator  │             │
│  └─────────────┘  └─────────────┘  └──────┬──────┘             │
│                                           │                    │
└───────────────────────────────────────────┼────────────────────┘
                                            ▼
┌─────────────────────────────────────────────────────────────────┐
│                       Agora Core                                │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐             │
│  │  motions    │  │   votes     │  │ assessments │             │
│  └─────────────┘  └─────────────┘  └─────────────┘             │
└─────────────────────────────────────────────────────────────────┘
                                            │
┌───────────────────────────────────────────┼────────────────────┐
│                       Kanban             ▼                      │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐             │
│  │  todo       │  │   running   │  │    done     │             │
│  └─────────────┘  └─────────────┘  └─────────────┘             │
└─────────────────────────────────────────────────────────────────┘
```

## 3. 核心模块设计

### 3.1 触发管理器 (Trigger Manager)

检测何时启动开发方向讨论。

支持的触发方式：
1. 定时触发：每天/每周固定时间检查
2. 用户触发：用户手动发起讨论请求
3. 事件触发：GitHub issues 更新、ROADMAP 变更

```python
# coordinator/bootstrap/trigger_manager.py

from enum import Enum
from dataclasses import dataclass
from datetime import datetime
from typing import Optional
import aiosqlite


class TriggerType(str, Enum):
    SCHEDULED = "scheduled"
    USER_REQUESTED = "user_requested"
    GITHUB_ISSUE = "github_issue"
    ROADMAP_CHANGE = "roadmap_change"


@dataclass
class TriggerEvent:
    """触发事件"""
    trigger_type: TriggerType
    topic: str
    source: str  # GitHub issue #, user_id, etc.
    context: str
    priority: int = 0
    created_at: datetime = None

    def __post_init__(self):
        if self.created_at is None:
            self.created_at = datetime.utcnow()


class TriggerManager:
    """触发管理器 - 检测何时启动开发方向讨论"""

    def __init__(self, db_path: str):
        self.db_path = db_path

    async def create_trigger(self, trigger_type: TriggerType, topic: str,
                            source: str, context: str, priority: int = 0) -> str:
        """创建触发事件"""
        event = TriggerEvent(
            trigger_type=trigger_type,
            topic=topic,
            source=source,
            context=context,
            priority=priority
        )

        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute("""
                INSERT INTO bootstrap_triggers 
                (trigger_type, topic, source, context, priority, status, created_at)
                VALUES (?, ?, ?, ?, ?, 'pending', ?)
            """, (event.trigger_type.value, event.topic, event.source,
                  event.context, event.priority, event.created_at.isoformat()))
            await db.commit()
            return str(cursor.lastrowid)

    async def get_pending_triggers(self, limit: int = 10) -> list[dict]:
        """获取待处理的触发事件"""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("""
                SELECT * FROM bootstrap_triggers 
                WHERE status = 'pending'
                ORDER BY priority DESC, created_at ASC
                LIMIT ?
            """, (limit,)) as cursor:
                rows = await cursor.fetchall()
                return [dict(row) for row in rows]

    async def mark_processed(self, trigger_id: str) -> None:
        """标记触发事件已处理"""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                UPDATE bootstrap_triggers 
                SET status = 'processed', processed_at = ?
                WHERE id = ?
            """, (datetime.utcnow().isoformat(), trigger_id))
            await db.commit()

    async def check_scheduled_triggers(self) -> list[dict]:
        """检查定时触发条件"""
        now = datetime.utcnow()
        triggers = []

        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("""
                SELECT * FROM bootstrap_schedules 
                WHERE enabled = 1 
                AND (next_run IS NULL OR next_run <= ?)
                ORDER BY next_run ASC
            """, (now.isoformat(),)) as cursor:
                rows = await cursor.fetchall()
                for row in rows:
                    triggers.append(dict(row))

        return triggers

    async def check_github_issues(self, repo: str) -> list[dict]:
        """检查 GitHub issues 是否有新需求"""
        # 可通过 gh CLI 或 GitHub API 实现
        # 筛选 label='needs-discussion' 的 issue
        pass
```

### 3.2 讨论驱动 (Discussion Driver)

驱动 Agora 进行开发方向讨论。

```python
# coordinator/bootstrap/discussion_driver.py

from typing import Optional
from dataclasses import dataclass
from datetime import datetime


@dataclass
class DiscussionConfig:
    """讨论配置"""
    motion_title: str
    motion_description: str
    participants: list[str]  # Agent IDs
    voting_method: str = "ranked_choice"
    auto_approve_threshold: float = 0.8  # 自动通过阈值
    max_rounds: int = 5


@dataclass
class DiscussionResult:
    """讨论结果"""
    motion_id: str
    decision: str  # adopted/rejected/no_consensus
    recommended_actions: list[dict]
    confidence: float
    rationale: str
    risk_assessment: dict
    created_at: datetime


class DiscussionDriver:
    """讨论驱动 - 驱动 Agora 进行开发方向讨论"""

    def __init__(self, coordinator_url: str):
        self.coordinator_url = coordinator_url

    async def start_dev_discussion(self, config: DiscussionConfig) -> str:
        """启动开发方向讨论"""
        # 1. 创建 motion
        motion_id = await self._create_motion(
            title=config.motion_title,
            description=config.motion_description,
            voting_method=config.voting_method
        )

        # 2. 注册参与者
        for agent_id in config.participants:
            await self._register_participant(motion_id, agent_id)

        # 3. 启动讨论
        await self._start_discussion(motion_id, config.max_rounds)

        return motion_id

    async def _create_motion(self, title: str, description: str,
                            voting_method: str) -> str:
        """创建 motion"""
        import aiohttp
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{self.coordinator_url}/api/motions",
                json={
                    "title": title,
                    "description": description,
                    "voting_method": voting_method,
                    "context": "auto_bootstrap"
                }
            ) as resp:
                data = await resp.json()
                return data["id"]

    async def _register_participant(self, motion_id: str, agent_id: str) -> None:
        """注册参与者"""
        # 通过 WebSocket 或 API 注册
        pass

    async def _start_discussion(self, motion_id: str, max_rounds: int) -> None:
        """启动讨论"""
        # 触发讨论开始
        pass

    async def wait_for_result(self, motion_id: str, timeout: int = 3600) -> DiscussionResult:
        """等待讨论结果"""
        import asyncio
        start_time = datetime.utcnow()

        while (datetime.utcnow() - start_time).seconds < timeout:
            result = await self._check_motion_status(motion_id)
            if result:
                return result
            await asyncio.sleep(10)

        raise TimeoutError(f"Discussion {motion_id} timed out")

    async def _check_motion_status(self, motion_id: str) -> Optional[DiscussionResult]:
        """检查 motion 状态"""
        import aiohttp
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{self.coordinator_url}/api/motions/{motion_id}"
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    if data.get("status") == "closed":
                        return DiscussionResult(
                            motion_id=motion_id,
                            decision=data.get("decision", "no_consensus"),
                            recommended_actions=data.get("action_items", []),
                            confidence=data.get("confidence", 0.0),
                            rationale=data.get("rationale", ""),
                            risk_assessment=data.get("risk_assessment", {}),
                            created_at=datetime.utcnow()
                        )
        return None
```

### 3.3 任务生成器 (Task Generator)

将讨论结果转换为 Kanban 任务。

```python
# coordinator/bootstrap/task_generator.py

from dataclasses import dataclass
from typing import Optional
import json


@dataclass
class TaskSpec:
    """任务规格"""
    title: str
    description: str
    assignee: str  # profile name: dev-merger, reviewer, etc.
    priority: int
    parent_task_id: Optional[str] = None
    skills: list[str] = None
    workspace_kind: str = "scratch"

    def __post_init__(self):
        if self.skills is None:
            self.skills = []


class TaskGenerator:
    """任务生成器 - 将讨论结果转换为 Kanban 任务"""

    def __init__(self, kanban_board: str = "default"):
        self.kanban_board = kanban_board

    async def generate_tasks(self, discussion_result: dict) -> list[str]:
        """从讨论结果生成任务"""
        tasks = []

        action_items = discussion_result.get("action_items", [])
        for idx, item in enumerate(action_items):
            task = await self._create_task(
                title=item.get("title", f"Task {idx + 1}"),
                description=item.get("description", ""),
                priority=item.get("priority", idx),
                category=item.get("category", "development")
            )
            tasks.append(task)

        return tasks

    async def _create_task(self, title: str, description: str,
                          priority: int, category: str) -> str:
        """创建 Kanban 任务"""
        assignee = self._infer_assignee(category)

        # 调用 Hermes kanban API
        import aiohttp
        async with aiohttp.ClientSession() as session:
            async with session.post(
                "http://localhost:8000/api/kanban/tasks",
                json={
                    "title": title,
                    "body": description,
                    "assignee": assignee,
                    "priority": priority,
                    "board": self.kanban_board
                }
            ) as resp:
                data = await resp.json()
                return data["task_id"]

    def _infer_assignee(self, category: str) -> str:
        """根据类别推断处理者"""
        mapping = {
            "development": "dev-merger",
            "review": "reviewer",
            "research": "planner",
            "release": "releaser",
            "documentation": "dev-merger",
        }
        return mapping.get(category, "dev-merger")

    async def create_approval_task(self, motion_id: str, decision: str) -> str:
        """创建用户审批任务"""
        import aiohttp
        async with aiohttp.ClientSession() as session:
            async with session.post(
                "http://localhost:8000/api/kanban/tasks",
                json={
                    "title": f"[审批] 讨论结果 {motion_id}",
                    "body": f"请审批开发方向讨论结果：{decision}",
                    "assignee": "user",
                    "priority": 100,
                    "board": self.kanban_board,
                    "skills": ["approval"]
                }
            ) as resp:
                data = await resp.json()
                return data["task_id"]
```

### 3.4 用户审批流程

用户拍板 + AI 方案论证机制。

```
AI团队讨论 → 生成方案 → 用户审批 → 确认/驳回 → 任务生成
     ↑                                               |
     └────────--- 驳回则重新讨论 ─────────────────────┘
```

```python
# coordinator/bootstrap/approval_flow.py

from enum import Enum
from dataclasses import dataclass
from datetime import datetime


class ApprovalStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


@dataclass
class ApprovalRequest:
    """审批请求"""
    motion_id: str
    decision: str
    rationale: str
    action_items: list[dict]
    requested_at: datetime


class ApprovalFlow:
    """审批流程 - 用户拍板 + AI 论证"""

    def __init__(self, coordinator_url: str):
        self.coordinator_url = coordinator_url

    async def submit_for_approval(self, motion_id: str) -> str:
        """提交审批请求"""
        # 1. 获取讨论结果
        result = await self._get_motion_result(motion_id)

        # 2. 创建审批任务
        approval_task = await self._create_approval_task(
            motion_id=motion_id,
            result=result
        )

        return approval_task

    async def handle_approval(self, approval_task_id: str,
                             approved: bool, feedback: str = None) -> dict:
        """处理审批结果"""
        if approved:
            return await self._process_approval(approval_task_id, feedback)
        else:
            return await self._process_rejection(approval_task_id, feedback)

    async def _process_approval(self, task_id: str, feedback: str) -> dict:
        """处理批准 - 生成开发任务"""
        # 更新任务状态为 approved
        # 生成开发任务
        return {"status": "approved", "tasks_created": True}

    async def _process_rejection(self, task_id: str, feedback: str) -> dict:
        """处理驳回 - 触发重新讨论"""
        # 记录驳回原因
        # 重新启动讨论（带反馈）
        return {"status": "rejected", "discussion_restarted": True}
```

### 3.5 数据库 Schema

新增自举相关表。

```sql
-- 触发事件表
CREATE TABLE bootstrap_triggers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    trigger_type TEXT NOT NULL,  -- scheduled, user_requested, github_issue
    topic TEXT NOT NULL,
    source TEXT,
    context TEXT,
    priority INTEGER DEFAULT 0,
    status TEXT DEFAULT 'pending',  -- pending, processing, processed, failed
    created_at TEXT NOT NULL,
    processed_at TEXT
);

-- 定时触发计划表
CREATE TABLE bootstrap_schedules (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    cron_expression TEXT NOT NULL,  -- 0 9 * * *
    topic_template TEXT NOT NULL,  -- 模板，支持变量替换
    enabled INTEGER DEFAULT 1,
    next_run TEXT,
    last_run TEXT
);

-- 审批记录表
CREATE TABLE bootstrap_approvals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    motion_id TEXT NOT NULL,
    decision TEXT NOT NULL,
    rationale TEXT,
    action_items TEXT,  -- JSON
    approval_status TEXT DEFAULT 'pending',  -- pending, approved, rejected
    approved_by TEXT,
    feedback TEXT,
    requested_at TEXT NOT NULL,
    processed_at TEXT
);

-- AI 团队成员配置表
CREATE TABLE bootstrap_agents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_id TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    role TEXT NOT NULL,  -- architect, developer, reviewer, researcher
    model TEXT,
    capabilities TEXT,  -- JSON
    active INTEGER DEFAULT 1
);
```

### 3.6 API 端点

```python
# coordinator/bootstrap/routes.py

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter(prefix="/api/bootstrap", tags=["bootstrap"])


class TriggerRequest(BaseModel):
    topic: str
    context: str
    source: str = "user"


class ApprovalRequest(BaseModel):
    task_id: str
    approved: bool
    feedback: str = None


@router.post("/trigger")
async def create_trigger(req: TriggerRequest):
    """创建触发事件"""
    pass


@router.get("/triggers")
async def list_triggers(status: str = None):
    """列出触发事件"""
    pass


@router.post("/approval")
async def submit_approval(motion_id: str):
    """提交审批请求"""
    pass


@router.post("/approval/decide")
async def decide_approval(req: ApprovalRequest):
    """处理审批决定"""
    pass


@router.get("/schedules")
async def list_schedules():
    """列出定时计划"""
    pass
```

### 3.7 主入口

```python
# coordinator/bootstrap/__init__.py

from .trigger_manager import TriggerManager
from .discussion_driver import DiscussionDriver
from .task_generator import TaskGenerator
from .approval_flow import ApprovalFlow


class BootstrapEngine:
    """自举引擎 - 协调所有模块"""

    def __init__(self, db_path: str, coordinator_url: str):
        self.trigger_mgr = TriggerManager(db_path)
        self.discussion_driver = DiscussionDriver(coordinator_url)
        self.task_generator = TaskGenerator()
        self.approval_flow = ApprovalFlow(coordinator_url)

    async def process_triggers(self):
        """处理待触发的事件"""
        triggers = await self.trigger_mgr.get_pending_triggers()

        for trigger in triggers:
            await self._process_trigger(trigger)

    async def _process_trigger(self, trigger: dict):
        """处理单个触发"""
        # 1. 创建讨论
        config = DiscussionConfig(
            motion_title=trigger["topic"],
            motion_description=trigger["context"],
            participants=["architect", "developer", "reviewer"]
        )

        motion_id = await self.discussion_driver.start_dev_discussion(config)

        # 2. 等待讨论结果
        result = await self.discussion_driver.wait_for_result(motion_id)

        # 3. 提交审批
        await self.approval_flow.submit_for_approval(motion_id)

        # 4. 标记触发已处理
        await self.trigger_mgr.mark_processed(trigger["id"])
```

## 4. 工作流程

```
┌─────────────┐
│  触发检测   │ ◀── 定时/用户/事件
└──────┬──────┘
       │
       ▼
┌─────────────┐
│  AI 团队讨论 │ ◀── 启动 Agora
└──────┬──────┘
       │
       ▼
┌─────────────┐
│  方案生成   │ ◀── 结论 + 行动项
└──────┬──────┘
       │
       ▼
┌─────────────┐
│  用户审批   │ ◀── 拍板/驳回
└──────┬──────┘
       │
   ┌───┴───┐
   │       │
   ▼       ▼
批准      驳回
   │       │
   ▼       ▼
生成任务   重新讨论
```

## 5. 实现步骤

1. **数据库 Schema** - 添加 bootstrap 相关表
2. **Trigger Manager** - 实现触发检测逻辑
3. **Discussion Driver** - 集成 Agora Core
4. **Task Generator** - 实现任务生成
5. **Approval Flow** - 实现审批流程
6. **API 端点** - 暴露管理接口
7. **Cron 集成** - 定时触发

## 6. 参考

- Phase 3: Memory and Evolution Design
- Phase 2: Smart Discussion Design
- 现有 coordinator/ 模块结构

---

## 7. 重构记录 (v0.18+)

### 7.1 去掉 Kanban 依赖

**问题**：原 TaskGenerator 直接调 Hermes kanban API (`/api/kanban/tasks`)，
违反后端无关原则——Agora 是通用平台，后端可以是 Hermes、OpenCode 或任何框架。

**方案**：TaskGenerator 改为调 Agora 自身的 Task API (`POST /api/v1/tasks`)。
所有任务操作走 Agora 协议，不依赖任何特定 agent 框架。

### 7.2 内置 Daemon 模式

**问题**：原 auto_bootstrap.py 是外部脚本，公开项目不能靠用户自写运行逻辑。

**方案**：内置 `agora daemon` CLI 子命令：
```bash
agora daemon              # 循环运行，默认30分钟间隔
agora daemon --once       # 跑一次就退出
agora daemon --dry-run    # 只检测不执行
agora daemon --interval 15  # 自定义间隔
```

Daemon 循环：
1. 检查定时触发 (scheduled triggers)
2. 检查 GitHub issues (如果开启)
3. 处理 pending triggers → 启动讨论
4. 处理 pending approvals (自动审批或等待用户)
5. 自动 git commit (如果开启)

### 7.3 Dashboard Settings 页面

**问题**：GitHub token、LLM API key 等配置只能手动改 config.yaml 或环境变量。

**方案**：新增 Settings API + Dashboard 页面，支持运行时配置：

| 分类 | 配置项 |
|------|--------|
| 🐙 GitHub | token, repo, default_branch |
| 🧠 LLM | api_key, base_url, default_model |
| 🤖 Agents | architect/developer/reviewer 模型 |
| ⚙️ Daemon | interval, auto_approve, github_sync |
| 📝 Git | auto_commit, author_name, author_email |
| 📄 Docs | auto_update |

API 端点：
- `GET /api/v1/settings` — 获取所有配置（secrets 脱敏）
- `GET /api/v1/settings/schema` — 获取字段定义
- `PUT /api/v1/settings` — 批量更新
- `DELETE /api/v1/settings/{key}` — 删除（恢复默认）

Secrets 在磁盘上 base64 编码存储，API 返回时脱敏 (`sk-***xyz`)。

### 7.4 自驱逻辑完整流程

```
用户 → Dashboard 下任务/发讨论/配 Settings
                │
                ▼
         Agora Coordinator
         (8765 端口, FastAPI)
                │
    ┌───────────┼───────────┐
    │           │           │
    ▼           ▼           ▼
 architect   developer   reviewer
 (讨论+架构)  (执行任务)   (审查)
    │           │           │
    └───────────┼───────────┘
                │
                ▼
         Task Board (状态看板)
                │
    ┌───────────┼───────────┐
    │           │           │
    ▼           ▼           ▼
  pending    assigned     running
                │
                ▼
  completed → git commit → push → docs update
```

**任务来源**（优先级从高到低）：
1. 用户从 Dashboard 手动创建
2. 讨论结果自动生成 (action_items → tasks)
3. GitHub issues 同步 (label: needs-discussion)
4. 定时触发 (scheduled review)
5. Daemon 自动发现 (代码健康检查)