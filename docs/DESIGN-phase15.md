# Phase 15 设计文档：安全加固 + Dogfooding 稳定化

> 版本：v1.0  
> 日期：2026-06-18  
> 对应版本：v0.16.0  
> 状态：设计阶段

---

## 背景

Agora 到 Phase 14+ 为止已具备完整功能栈（DB、消息队列、Workspace、K8s、Webhook、Protocol v2），但安全基础薄弱：

- Dashboard 暴露在公网无认证保护（虽然有登录界面，但 `AGORA_DASHBOARD_USERS` 未配置时 login 返回 501，Dashboard 直接可访问）
- REST API 无强制认证（`AGORA_RBAC_ENFORCE` 默认 false，所有端点裸奔）
- Agent 注册虽然已有 `POST /api/v1/agents/register`，但需要已持有 token 才能调用（`@requires(Permission.AGENT_REGISTER)`），新 agent 无 token 无法注册——**鸡生蛋问题**

Phase 15 聚焦安全加固，然后通过真实 dogfooding 验证系统稳定性。

---

## 现状分析

### 已有基础

| 组件 | 文件 | 状态 |
|------|------|------|
| Dashboard 登录 UI | `static/dashboard.html` + `static/js/auth.js` | 有登录覆盖层，但无强制 |
| Dashboard 登录 API | `auth_router.py` — `POST /api/v1/auth/login` | 存在，依赖 `AGORA_DASHBOARD_USERS` 配置 |
| JWT TokenManager | `token_manager.py` | 完整（创建/验证/吊销/scope） |
| RBAC Middleware | `rbac_middleware.py` | 存在但 opt-in（`AGORA_RBAC_ENFORCE`） |
| Agent 注册 API | `router.py` — `POST /api/v1/agents/register` | 存在但需要已有 token |
| Agent 审批 API | `router.py` — `POST /admin/agents/{id}/approve` | 存在，admin only |
| RBAC 权限模型 | `rbac.py` | Role 枚举 + Permission 枚举 + `@requires()` |
| Token Scope | `token_scopes.py` | Phase 14+.E.6 已添加 |

### 核心问题

1. **Dashboard 无强制认证** — 虽然 `auth.js` 调用 `checkAuth()`，但 Dashboard 的 `/dashboard` 路由无条件返回 HTML，登录覆盖层是纯前端逻辑，可以被绕过（curl 直接访问也返回 HTML）
2. **API 无强制认证** — `AGORA_RBAC_ENFORCE` 默认 false，生产环境可能未开启
3. **新 Agent 无法自助注册** — 注册端点需要 `AGENT_REGISTER` 权限，但新 agent 没有任何 token

---

## Part A: Dashboard 强制认证

### 目标

Dashboard 的所有页面和 API 必须在认证后才能访问。未认证用户自动跳转登录页。

### 设计

#### A.1 Dashboard 页面保护

当前 `/dashboard` 路由无条件返回 `dashboard.html`，攻击者可以绕过前端登录直接看到页面结构（虽然数据 API 可能未授权）。

**方案：** Dashboard HTML 请求检查 cookie/header 中的 JWT，无效则重定向到 `/login` 页面。

```
GET /dashboard
  → 检查 Authorization header 或 dashboard_token cookie
  → 有效 JWT：返回 dashboard.html
  → 无/无效 JWT：返回 login.html（独立登录页）
```

新增独立登录页 `/static/login.html`（当前登录是 overlay，不是独立页面）：

- `login.html` — 独立登录页面，纯 HTML + CSS + 最小 JS（不依赖 ES modules）
- 登录成功后设置 `dashboard_token` cookie（httpOnly + secure + sameSite）
- 重定向到 `/dashboard`

#### A.2 Dashboard 数据 API 保护

Dashboard 使用的所有 `/api/v1/` 端点（events、agents、tasks 等）在 Part B API 加固中统一处理。

当前 `dashboard.py` 的端点部分没有 `@requires()` 装饰器。

#### A.3 Session 持久化

当前 `auth.js` 将 token 存 localStorage。改为同时设置 cookie，让服务端也能验证页面请求：

- `/api/v1/auth/login` 成功后在响应中 `Set-Cookie: dashboard_token=<jwt>; HttpOnly; Secure; SameSite=Strict; Path=/; Max-Age=86400`
- `/dashboard` 路由检查 cookie 中的 `dashboard_token`
- `/api/v1/auth/logout` 清除 cookie

### 涉及文件

| 文件 | 变更 |
|------|------|
| `static/login.html` | **新增** — 独立登录页面 |
| `static/dashboard.html` | 移除 login overlay（改为独立页面） |
| `static/js/auth.js` | 修改 — 支持 cookie 模式，移除 overlay 逻辑 |
| `main.py` | 修改 — `/dashboard` 路由增加 JWT 检查 + 重定向 |
| `auth_router.py` | 修改 — login 响应添加 Set-Cookie，新增 logout 端点 |

### 数据模型

无新数据模型。复用现有 TokenManager + JWT。

### 边界情况

- `AGORA_DASHBOARD_USERS` 未配置时：login 页面显示"管理员未配置 Dashboard 认证"，不暴露系统信息
- JWT 过期：页面请求返回 302 → `/login`；API 请求返回 401
- Cookie 被阻止：回退到 Authorization header 模式（前端 JS 添加）
- 首次启动无用户：提供 `AGORA_DASHBOARD_USERS` 环境变量文档和 `agora dashboard add-user` CLI 子命令

---

## Part B: API 强制认证

### 目标

所有 Coordinator REST API 端点默认需要认证，只有少数白名单端点（`/health`、`/api/v1/health`、`/api/v1/auth/login`、`/api/v1/discovery`）免认证。

### 设计

#### B.1 认证模式切换

当前 `AGORA_RBAC_ENFORCE` 控制 RBAC 中间件是否生效。Phase 15 改为：

- **新增 `AGORA_AUTH_MODE`** 环境变量，取值：
  - `"none"` — 完全无认证（开发环境，等同于当前 `AGORA_RBAC_ENFORCE=false`）
  - `"token"` — API 需要 Bearer token，但不检查 RBAC 权限（过渡模式）
  - `"rbac"` — API 需要 Bearer token + RBAC 权限检查（生产模式，等同于当前 `AGORA_RBAC_ENFORCE=true`）

默认值：**`"none"`**（向后兼容），推荐生产环境设 `"rbac"`。

#### B.2 认证白名单

以下端点**始终**免认证（即使 `AGORA_AUTH_MODE=rbac`）：

| 端点 | 原因 |
|------|------|
| `GET /health` | Docker 健康检查 |
| `GET /api/v1/health` | 同上 |
| `POST /api/v1/auth/login` | 登录（无 token 时唯一入口） |
| `GET /api/v1/discovery` | Agent 发现端点（新 agent 无 token） |
| `POST /api/v1/agents/register` | Agent 自助注册（见 Part C） |

#### B.3 Agent token vs Dashboard token

两种 token 共存：

- **Dashboard token**：用户登录获得，role=admin/observer，通过 cookie 或 Bearer header
- **Agent token**：agent 注册获得（`ag-` 前缀），通过 WebSocket 连接时 auth 消息或 Bearer header

RBAC middleware 已有逻辑：`ag-` 前缀 token → Role.AGENT，JWT → 解码 role。

#### B.4 中间件改造

当前 `RBACMiddleware` 在 `AGORA_RBAC_ENFORCE` 为 true 时才执行。改为：

1. 检查路径是否在白名单中 → 跳过
2. 根据 `AGORA_AUTH_MODE` 决定行为：
   - `none`：跳过
   - `token`：检查 token 存在且有效（不检查权限）
   - `rbac`：检查 token 存在 + 有效 + 权限

### 涉及文件

| 文件 | 变更 |
|------|------|
| `config.py` | 新增 `AGORA_AUTH_MODE` 配置项 |
| `rbac_middleware.py` | 改造 — 支持白名单 + 三种模式 |
| `rbac.py` | 修改 — `@requires()` 在 `token` 模式下只检查认证不检查权限 |
| `main.py` | `/dashboard` 路由改为检查认证 |

### 边界情况

- 环境变量切换：`AGORA_AUTH_MODE` 变更后需重启 Coordinator
- 过渡模式：`token` 模式允许所有已认证请求通过，方便渐进式迁移
- 向后兼容：默认 `none` 模式，现有部署不受影响
- Admin token 回退：`AGORA_ADMIN_TOKEN` 始终作为超级 token 有效

---

## Part C: Agent 自助注册

### 目标

全新 agent（无任何 token）能通过标准流程自助接入 Agora，无需管理员 SSH 到服务器手动配置。

### 设计

#### C.1 注册流程

```
Agent                          Coordinator                     Admin
  |                                |                              |
  |-- POST /api/v1/agents/register |                              |
  |   {name, capabilities, ...}    |                              |
  |                                |-- 创建 agent 记录 (pending)   |
  |   {agent_id, approval_status,  |                              |
  |    registration_token}         |                              |
  |                                |                              |
  |   [如果 require_approval=true] |                              |
  |                                |-- 通知 admin (Dashboard/WS)  |
  |                                |                        <admin 审批>
  |                                |                              |
  |   [轮询或 WS 等待审批]         |                              |
  |                                |                              |
  |   {agent_token (ag-xxx)}       |                              |
  |                                |                              |
  |-- WS /ws/{agent_id} 连接       |                              |
  |   auth: {token: "ag-xxx"}      |                              |
  |                                |-- 验证 token + 激活 agent    |
  |   connected                    |                              |
```

**关键区别：** `POST /api/v1/agents/register` 现在加入**白名单**（免认证），使新 agent 能在无 token 情况下调用。但需要防御滥用（见 C.4）。

#### C.2 注册端点改造

当前：
```python
@router.post("/agents/register", ...)
@requires(Permission.AGENT_REGISTER)  # ← 需要已有 token，鸡生蛋
```

改为：
- 移除 `@requires()` 装饰器
- 加入白名单（Part B.2）
- 返回 `registration_token`（临时 token，仅用于查询审批状态和轮询）
- 新增查询端点 `GET /api/v1/agents/register/{agent_id}/status`（免认证，使用 registration_token 验证身份）

#### C.3 数据模型变更

`AgentRegisterRequest` 增加字段：
```python
class AgentRegisterRequest(BaseModel):
    agent_id: str
    name: str
    model: str = "unknown"
    capabilities: list[str] = []
    agent_type: AgentType = AgentType.HERMES
    max_concurrent_tasks: int = 2
    # 新增
    public_key: str | None = None  # 可选的公钥，用于后续 mTLS
    contact_url: str | None = None  # agent 所有者的联系方式
```

`AgentRegistrationResponse` 增加字段：
```python
class AgentRegistrationResponse(BaseModel):
    agent_id: str
    status: AgentStatus
    agent_token: str | None = None  # 审批通过后才有
    registration_token: str | None = None  # 查询状态用
    message: str
    approval_required: bool
```

新增 model：
```python
class RegistrationStatusResponse(BaseModel):
    agent_id: str
    approval_status: str  # pending / approved / rejected
    agent_token: str | None = None  # 审批通过时返回
    message: str
```

#### C.4 防滥用措施

免认证的注册端点需要防护：

1. **速率限制** — 同一 IP 每分钟最多 3 次注册请求（复用现有 TokenRateLimiter 逻辑）
2. **agent_id 唯一性** — 已注册的 agent_id 返回 409
3. **registration_token 一次性** — 审批通过/拒绝后立即失效
4. **reCAPTCHA（可选）** — 配置 `AGORA_REGISTRATION_CAPTCHA_SECRET` 后启用
5. **审批模式默认开启** — `AGORA_REQUIRE_APPROVAL` 默认改为 `true`

#### C.5 Hermes 一键接入

```bash
hermes agora connect --url https://agora.example.com --name "my-agent" --capabilities "python,review"
```

内部流程：
1. 解析命令行参数 → 构造 `AgentRegisterRequest`
2. `POST /api/v1/agents/register`
3. 如果 `approval_required=true`：轮询 `GET /api/v1/agents/register/{agent_id}/status` 直到审批
4. 获得 `agent_token` → 打开 WebSocket 连接 `/ws/{agent_id}`
5. 发送 auth 消息 → 连接建立

首次使用时自动创建 Hermes profile 配置：
```yaml
# ~/.hermes/config.yaml
agora:
  url: https://agora.example.com
  agent_id: my-agent
  token: ag-xxxx
```

后续 `hermes agora connect` 直接使用已保存的配置。

#### C.6 Dashboard 审批界面

Agent 管理页面增加"待审批"标签页：
- 显示所有 `approval_status=pending` 的 agent
- 管理员可以 Approve / Reject
- 审批时可选填写 reason（reject 时必填）
- 审批通过后自动生成 agent_token

### 涉及文件

| 文件 | 变更 |
|------|------|
| `router.py` | 修改 — `/agents/register` 移除 @requires，加入白名单 |
| `models/_models.py` | 新增 `RegistrationStatusResponse`、修改 `AgentRegisterRequest`、`AgentRegistrationResponse` |
| `config.py` | `AGORA_REQUIRE_APPROVAL` 默认改为 true |
| `storage/agents.py` | 新增 `registration_token` 列 + `get_agent_by_registration_token()` |
| `static/js/pages/agents.js` | 新增"待审批"标签页 |
| `static/dashboard.html` | agents 页面增加 pending tab |
| `main.py` | 注册端点加入白名单（Part B） |

### 边界情况

- agent_id 冲突：返回 409，提示 agent 已存在
- registration_token 过期：24 小时后自动失效
- 审批被拒：agent 可重新注册（相同 agent_id 需先删除旧记录或 7 天后自动清理）
- 注册后 coordinator 重启：registration_token 持久化到 DB
- 无审批模式：`AGORA_REQUIRE_APPROVAL=false` 时注册后立即可用

---

## Part D: Dogfooding 基础设施

### 目标

Agora 团队（coordinator + planner + dev-merger + reviewer + releaser）通过 Agora 自身的 WS 协议协作，而不是直接操作 Hermes kanban。

### 当前问题

当前团队成员直接通过 Hermes kanban（`hermes kanban claim/complete`）操作任务板，没有经过 Agora 的讨论/调度机制。Agora 的 Discussion 状态机、投票、Task Engine 等功能未被 dogfooding。

### 设计

#### D.1 Agora 作为 Kanban 后端

不是取代 kanban，而是让 **Agora 的 Task Engine 成为 kanban 的数据源**：

```
当前：Hermes kanban → SQLite DB → agent 直接操作
目标：Hermes kanban → Agora API → Agora DB → agent 通过 Agora 操作
```

即：Harness 层通过 Agora REST API 操作任务，agent 通过 WS 协议感知任务变化。

这是一个较大的改造，Phase 15 不做完整实现，而是做**最小可行 dogfooding**：

#### D.2 最小可行 Dogfooding（Phase 15 范围）

创建一个简单的 "Agora Agent" 配置，让它以 agent 身份连接 Agora Coordinator：

1. **注册 Agora 团队 agent** — 将 coordinator/planner/dev-merger/reviewer/releaser 注册为 Agora agent
2. **通过 Agora Discussion 做设计讨论** — planner 通过 WS 协议发起 motion、收集意见
3. **通过 Agora Task 分配开发任务** — coordinator 通过 `/api/v1/tasks` 创建任务
4. **agent 通过 WS 接收任务通知** — 任务创建/分配后通过 WS 推送

#### D.3 需要补充的端点

当前 Task Engine 已有基本的任务 CRUD（Phase 9.3 + Phase 10.1），但缺少：

1. **任务分配通知** — 任务分配给 agent 后 WS 推送
2. **任务状态变更事件** — status 变更推送 Dashboard WS
3. **Agent Claim 端点** — agent 通过 API 认领任务（当前只能通过 WS）

这些功能是 Phase 13 Pipeline 的一部分但并未完全暴露给普通 agent。

#### D.4 Phase 15 Dogfooding 范围（最小集）

| 功能 | 实现方式 |
|------|----------|
| 任务创建 | 已有 `/api/v1/tasks` (需确认) |
| Agent 认领任务 | 新增 `POST /api/v1/tasks/{id}/claim` |
| Agent 完成任务 | 新增 `POST /api/v1/tasks/{id}/complete` |
| WS 任务通知 | 已有 task_exec.py（需确认推送逻辑） |
| 讨论创建 | 已有 `/api/v1/motions` |
| Agent 投票 | 已有 vote 逻辑 |

#### D.5 Team Agent 注册脚本

提供 `scripts/register-team.sh` 脚本，一键注册默认团队 agent：

```bash
#!/bin/bash
# 注册 Agora 开发团队 agent
AGENTS=(
  "coordinator:Coordinator:admin:hermes"
  "planner:Planner:agent:hermes"
  "dev-merger:Dev Merger:agent:hermes"
  "reviewer:Reviewer:agent:hermes"
  "releaser:Releaser:agent:hermes"
)

for agent in "${AGENTS[@]}"; do
  IFS=':' read -r id name role atype <<< "$agent"
  curl -X POST "$AGORA_URL/api/v1/agents/register" \
    -H "Content-Type: application/json" \
    -d "{\"agent_id\":\"$id\",\"name\":\"$name\",\"agent_type\":\"$atype\",\"capabilities\":[\"development\"]}"
done
```

### 涉及文件

| 文件 | 变更 |
|------|------|
| `router.py` | 新增 `/tasks/{id}/claim`、`/tasks/{id}/complete` 端点 |
| `task_exec.py` | WS 推送逻辑确认和增强 |
| `scripts/register-team.sh` | **新增** — 团队 agent 注册脚本 |
| `docs/DOGFOODING.md` | **新增** — Dogfooding 操作指南 |

---

## 开发任务拆分

### Part A: Dashboard 强制认证（🔴 最高优先）

| 任务 | 内容 | 预估 |
|------|------|------|
| A.1 | 新增 `static/login.html` 独立登录页面 | 2h |
| A.2 | 修改 `auth_router.py`：login 添加 Set-Cookie，新增 logout 端点 | 1h |
| A.3 | 修改 `main.py`：`/dashboard` 路由添加 JWT 检查 + 重定向 | 1h |
| A.4 | 修改 `static/js/auth.js`：支持 cookie 模式，清理 overlay 逻辑 | 1h |
| A.5 | 修改 `static/dashboard.html`：移除 login overlay，更新入口 | 0.5h |
| A.6 | 测试：Dashboard 认证完整流程测试 | 2h |
| | **小计** | **7.5h** |

### Part B: API 强制认证（🔴 最高优先）

| 任务 | 内容 | 预估 |
|------|------|------|
| B.1 | `config.py` 添加 `AGORA_AUTH_MODE` | 0.5h |
| B.2 | `rbac_middleware.py` 改造：白名单 + 三种模式 | 2h |
| B.3 | 白名单端点标记（health、login、discovery、register） | 1h |
| B.4 | 所有现有路由添加 `@requires()` 装饰器（审计当前状态） | 2h |
| B.5 | 测试：三种模式下认证行为测试 | 3h |
| | **小计** | **8.5h** |

### Part C: Agent 自助注册（🔴 最高优先）

| 任务 | 内容 | 预估 |
|------|------|------|
| C.1 | `router.py`：注册端点移除 @requires，加入白名单 | 1h |
| C.2 | 新增 `GET /agents/register/{agent_id}/status` 查询端点 | 1h |
| C.3 | 数据模型扩展：`registration_token`、`RegistrationStatusResponse` | 1h |
| C.4 | `storage/agents.py`：registration_token 存储 + 查询 | 1h |
| C.5 | 注册端点速率限制（IP-based） | 1.5h |
| C.6 | Dashboard 审批界面：pending 标签页 + approve/reject 按钮 | 3h |
| C.7 | `config.py`：`AGORA_REQUIRE_APPROVAL` 默认改为 true | 0.5h |
| C.8 | 测试：自助注册 + 审批 + 连接完整流程 | 3h |
| | **小计** | **12h** |

### Part D: Dogfooding 基础设施（🟡）

| 任务 | 内容 | 预估 |
|------|------|------|
| D.1 | 新增 `POST /api/v1/tasks/{id}/claim` 端点 | 1h |
| D.2 | 新增 `POST /api/v1/tasks/{id}/complete` 端点 | 1h |
| D.3 | WS 任务通知推送确认/增强 | 2h |
| D.4 | `scripts/register-team.sh` 注册脚本 | 1h |
| D.5 | `docs/DOGFOODING.md` 操作指南 | 1.5h |
| D.6 | 测试：任务 claim/complete + WS 通知 | 2h |
| | **小计** | **8.5h** |

### 总计

| Part | 内容 | 预估 |
|------|------|------|
| A | Dashboard 认证 | 7.5h |
| B | API 认证加固 | 8.5h |
| C | Agent 自助注册 | 12h |
| D | Dogfooding 基础设施 | 8.5h |
| **总计** | | **~36.5h** (~5-7 天) |

---

## 向后兼容

1. `AGORA_AUTH_MODE` 默认 `none` — 现有部署不受影响
2. `AGORA_REQUIRE_APPROVAL` 默认改为 `true` — **行为变更**，文档说明
3. 现有 agent token（`ag-` 前缀）继续有效
4. 现有 Dashboard 用户通过 `AGORA_DASHBOARD_USERS` 配置继续可用
5. RBAC 中间件重构向后兼容 — 不传 token 时行为与当前 `none` 模式一致

---

## 风险

1. **Agent 注册端点开放** — 免认证后可能被滥用。缓解：IP 速率限制 + 审批模式默认开启
2. **API 认证模式切换** — 从 none 切到 rbac 可能破坏现有集成。缓解：提供 token 过渡模式
3. **Cookie 模式** — 某些 agent（非浏览器）不支持 cookie。缓解：始终支持 Authorization header 回退

---

## 与后续 Phase 的关系

- **Phase 15+ (K8s 分布式部署)** — Part B API 认证是 K8s 暴露公网的前提
- **Mobile Dashboard** — Part A Dashboard 认证需先完成
- **PicoClaw 适配器** — Part C Agent 自助注册提供标准接入方式
- **插件市场** — Part B API 认证保护插件管理端点
